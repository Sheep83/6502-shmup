# 19656 — `regenTick` Contiguous Row-Copy Optimisation

**Date:** 2026-10-01
**Scope:** the unchanged-row copy portion of back-page regeneration, and nothing
else.
**Outcome:** the proposed contiguous block copy is **valid** — the geometry is
confirmed from the running machine — but the naive version of it is a **measured
regression**, and only the unrolled version wins. Adopted: one contiguous copy
per frame, unrolled four bytes a pass. `regenTick` falls **3,553 → 2,926** cycles
on a working frame (−17.6%), the regeneration episode **23,041 → 19,346**
(−16.0%), and the worst stress frame **17,446 → 16,868** (88.8% → 85.8% of a PAL
frame). Output is byte-identical. The truthful overrun counter stays at 0.

**The ~2,000-cycle estimate in the brief was too optimistic.** The real figure is
about **630 cycles a working frame**. §6 explains exactly where the rest went and
why it is not reachable with legal NMOS code at a sane size.

No commit, no push.

---

## 1. Initial repository state

Clean tree at `42370f3 "Hitscan routines optimised"`, which is the user's commit
of the preceding pass — `src/scroll.asm`, `src/collision.asm`, `src/main.asm`,
`src/renderer.asm`, `tests/test_regen_page_shift.py`,
`tests/test_hitscan_twin_ray.py`, the Makefile tier registration and both prior
reports are all in it. `git status` reported no modifications and no untracked
files before this pass began.

Read first: `AGENTS.md`;
`reports/whole-frame-audit-and-regen-optimisation.md`;
`reports/twin-ray-hitscan-optimisation.md`; `src/scroll.asm` (regeneration,
state block, segment guards); `src/turrets.asm` (the repair contract and the
`$5800-$63ff` allocation); `tests/test_regen_page_shift.py`; `tests/harness.py`.

---

## 2. The copy contract, confirmed from the machine

The constants, from source rather than from the previous report:

| | value | from |
|---|---|---|
| `SCREEN_A` / `SCREEN_B` | `$0400` / `$2800` | `src/main.asm:86-87` |
| `SCREEN_ROWS` / `SCREEN_COLS` | 25 / 40 | `src/main.asm:289-290` |
| `ROWS_PER_TICK` | 4 | `src/scroll.asm:105` |
| row offset | `40 * row` | `rowLo`/`rowHi`, `src/scroll.asm` |

- **Source** — the displayed page, starting one row higher than the destination.
- **Destination** — the page being rebuilt (`regenPageHi`, `$04` or `$28`).
- **Rows copied** — 1..24. Row 0 is the only row decoded, by `renderRow`.
- **Stride** — 40 bytes a row; 960 bytes an episode; 120/160/40 a frame (below).
- **Group selection** — `regenTick` takes `ROWS_PER_TICK` rows a frame, fewer when
  the page runs out. Row 0's frame therefore decodes one row and copies three.
- **Boundaries** — the destination run never leaves the 1000-byte matrix: the last
  group is rows 20..23 (bytes 800..959) and then row 24 alone (960..999).
- **Publication** — unchanged. The page flips at the coarse step, by which time all
  25 rows are done; the engine's own `scrollLate` counter is the detector for a
  step arriving on an unfinished page, and it is 0 throughout.
- **HUD / colour / other state** — none involved. `renderRow` states that *every*
  row is terrain including 0 and 24, the aperture is clipped by a blank charset at
  fixed rasters rather than by blanked content, the HUD is sprite-based
  (`HUD_SPRITE_COUNT = 6`) with no character cells in the matrix, and colour RAM
  is filled once at init and never touched again. There is no non-screen-byte
  state in the copied region.

**Measured from the addresses the engine itself patches** into `cpSrc`/`cpDst`,
not from the listing — because the contiguity claim is a claim about addresses:

| fine | rows | source run | destination run | bytes | contiguous | src − dst |
|---:|---:|---|---|---:|:---:|---:|
| 0 | 3 | `$2800-$2877` | `$0428-$049f` | 120 | yes | `$23d8` |
| 1 | 4 | `$2878-$2917` | `$04a0-$053f` | 160 | yes | `$23d8` |
| 2 | 4 | `$2918-$29b7` | `$0540-$05df` | 160 | yes | `$23d8` |
| 3 | 4 | `$29b8-$2a57` | `$05e0-$067f` | 160 | yes | `$23d8` |
| 4 | 4 | `$2a58-$2af7` | `$0680-$071f` | 160 | yes | `$23d8` |
| 5 | 4 | `$2af8-$2b97` | `$0720-$07bf` | 160 | yes | `$23d8` |
| 6 | 1 | `$2b98-$2bbf` | `$07c0-$07e7` | 40 | yes | `$23d8` |
| 0 | 3 | `$0400-$0477` | `$2828-$289f` | 120 | yes | `−$2428` |

**So the proposed assumption holds.** Every frame's rows form one ascending run
with a single constant delta — `$2400 − 40` rebuilding A from B, `−($2400 + 40)`
the other way. A four-row group is one contiguous 160-byte source block and one
contiguous 160-byte destination block.

**Overlap is impossible.** The two runs lie in different screen matrices and
`SCREEN_A + 1000 = $07e8 < $2800`, so they cannot intersect at any row and the
copy direction is free. This is now a build-time assertion rather than an
observation, so moving a page can never silently make the direction load-bearing.

---

## 3. Baseline cost (A)

Elapsed, breakpoint pairs against the emulator's cycle counter, stripped stress
encounter, trigger held and ship swept.

| | measured |
|---|---:|
| `renderRow`, the one decoded row | 1,697 median, 2,090 worst |
| `copyRowFromFront`, one 40-byte row | **850** median, 652 min, 1,706 worst |
| — per byte | **21.25** elapsed cycles |
| `regenTick`, working frames | **3,553** median, **4,817** worst (24.5%) |
| one complete episode | **23,041** |

Where a 4-row frame's ~2,650 pure cycles go, by inspection of the instruction
stream (all state is absolute, not zero page — that matters for the arithmetic):

| | cycles | × per frame | total |
|---|---:|---:|---:|
| `jsr` + `rts` | 12 | 4 | 48 |
| `regenTick` loop bookkeeping (`tya/pha/…/dey/bne`) | ~37 | 4 | ~148 |
| address setup (2 operands patched) | 54 | 4 | 216 |
| copy loop, 40 bytes at 14 cycles | 559 | 4 | 2,236 |
| | | | **~2,648** |

**360 of those cycles are per-row overhead paid four times for 40 bytes each.**
That is what the contiguous form is trying to recover.

---

## 4. Alternatives measured

### B — one contiguous copy per group, rolled

One call, one setup, two patched operands, `lda abs,y` / `sta abs,y` over all 160
bytes.

**This is a regression, and the reason is specific and worth recording.** A
160-byte group needs an index that runs past 127, and `bpl` — the loop test the
40-byte version used — is then unusable: `ldy #159` already sets the sign bit, so
the loop would exit after copying four bytes of a hundred and sixty. The index
has to run down to 0 and wrap, and `$ff` is the only value that means finished,
so the test becomes `cpy #$ff` / `bne`: **16 cycles a byte instead of 14**. On 160
bytes that is +320 cycles, against the ~310 saved by setting up once instead of
four times. The two cancel, slightly the wrong way.

Measured, and it agrees:

| | A | B |
|---|---:|---:|
| copy, per byte, elapsed | 21.25 | **22.1** |
| `regenTick` working-frame median | 3,553 | **3,638** |
| `regenTick` worst | 4,817 | 4,827 |
| episode (sum of measured per-fine medians) | 23,041 | ~24,586 |

### C — one contiguous copy per group, unrolled four bytes a pass — **adopted**

Four `lda abs,y` / `sta abs,y` pairs with a `dey` between, one `cpy #$ff` / `bne`
per pass. Per pass 4×(4+5+2) + 2 + 3 = **49 cycles, 12.25 a byte**.

The unroll needs eight patched operands rather than two — but all eight hold the
*same* address, because only the index differs between the copies, so it is two
bytes written four times each. **That is the whole insight of this pass:** per
row, eight patch sites cost ~84 cycles to serve 40 bytes and cancelled the
saving exactly (which is why the previous pass measured unrolling as worthless
and left the loop rolled). Per group they cost the same ~54 extra cycles to serve
**160** bytes, and the economics invert.

| | A | B | **C** |
|---|---:|---:|---:|
| copy, per byte, elapsed | 21.25 | 22.1 | **17.5** |
| copy, per byte, pure (computed) | 14.0 | 16.0 | **12.25** |
| `regenTick` working-frame median | 3,553 | 3,638 | **2,926** |
| `regenTick` working-frame worst | 4,817 | 4,827 | **4,381** |
| `regenTick` busy-frame median (pop ≥ 4) | 3,228 | — | **2,618** |
| complete episode | 23,041 | ~24,586 | **19,346** |

### D — considered, rejected, and why

**Address-offset unrolling** (`lda src+0,y` … `lda src+7,y`, index stepping by 8)
is the only way to remove the `dey` and approach the 9-cycle-a-byte floor for an
indexed copy. It was rejected on measurement, not taste:

- At an unroll of 4 it buys **nothing**: stepping the index by 4 costs the same 8
  cycles as the four `dey`s it replaces.
- At an unroll of 8 it saves ~160 cycles a frame, but the eight source operands
  now hold eight *different* addresses (`base+0 … base+7`), so the setup must add
  and carry per operand — and a group's low byte can be high enough that `base+7`
  crosses into the next page, which makes the high byte differ too. That is a
  per-operand conditional in the setup, for ~0.8% of a frame.

**Fully unrolled absolute addressing** (8 cycles a byte, no index) needs 6 bytes
of code per byte copied — 960 bytes per group, 14 groups. Not considered
seriously.

So **12.25 cycles a byte is what clean code gets here**, against a practical
floor near 10.4 and an absolute floor of 9. Recording that so the next pass does
not re-litigate it.

---

## 5. What was implemented

`regenTick` (`src/scroll.asm`) now computes the group size once — `ROWS_PER_TICK`,
clamped to what the page has left — decodes row 0 when it is row 0's turn, and
makes **one** call for the rest. The row schedule is unchanged: rows 0–3, 4–7,
8–11, 12–15, 16–19, 20–23, 24, idle. Verified case by case against the old loop.

`copyRowsFromFront` replaces `copyRowFromFront`. It patches one source and one
destination address into four sites each and copies `40 × rgRows` bytes.

Four build-time assertions were added, each guarding something the code now
relies on:

- the two matrices do not intersect, so the copy direction is free;
- `SCREEN_COLS * ROWS_PER_TICK ≤ 256`, so the group index fits one register;
- `SCREEN_COLS` is a multiple of 4, so the unrolled body cannot overrun a group;
- (retained) the two page high bytes still differ by a single EOR.

`rgLastByte` is indexed by `rgRows`; entry 0 is documented as unreachable, with
the reason spelled out — there is no safe value for it, because a zero group
would run the index all the way round 256 bytes. The contract is the guard.

### Code size and placement

The routine grew from 50 to 118 bytes and `regenTick` from 41 to 52, which
overflowed the scroller's `$4340-$4600` segment by exactly 53 bytes. So
`copyRowsFromFront` was moved out, for the reason the file already gives for
`rowLo`/`rowHi`: it is a leaf reached by `jsr` that reads tables by absolute,X
and writes the screen by absolute,Y, so its address is immaterial, and the code
that needs the room is not.

It went to `$6300`, in the run `src/turrets.asm` documents as freed when the
stage map left for the level package — *"leaving `$5800-$63ff` free… the first
tenant of that space… still CPU-only data outside VIC bank 0"*. This is the
second tenant, placed at the **top** of the run so the turret tables keep their
growth room beneath it. **The turret tables' own ceiling was tightened from
`$6400` to `$6300`** so that growing into executable code is a build error rather
than silent corruption; they currently end at `$5a34`, leaving 2,252 bytes of
headroom.

Net effect on the crowded segment: the scroller now uses **39 bytes fewer** than
before. State grew by one byte (`rgRows`), `scrollStateEnd` `$c56e → $c56f`
against a `$c600` ceiling.

### Readability tradeoff

Eight self-modified operands is more than two, and that is the cost. It is
mitigated by all eight holding one address, by the comment stating why unrolling
pays here and did not pay per row, and by the `cpy #$ff` trap being documented at
the instruction rather than left for the next reader to rediscover. The rejected
alternative — address-offset unrolling — would have needed per-operand carry
handling for a further 0.8% of a frame, and that is where this stopped.

---

## 6. Performance, before and after

### `regenTick` and the copy

| | HEAD (A) | adopted (C) | change |
|---|---:|---:|---:|
| copy, elapsed cycles a byte | 21.25 | **17.5** | −17.6% |
| copy call, 160-byte group | 4 × 850 = 3,400 | **2,803** | −597 |
| `regenTick`, working-frame median | 3,553 | **2,926** | −627 (−17.6%) |
| `regenTick`, working-frame worst | 4,817 | **4,381** | −436 |
| `regenTick`, busy-frame median (pop ≥ 4) | 3,228 | **2,618** | −610 (−18.9%) |
| complete regeneration episode | 23,041 | **19,346** | −3,695 (−16.0%) |

### Whole frame, stripped stress encounter, 5,499 frames each

| | HEAD (A) | adopted (C) | change |
|---|---:|---:|---:|
| median | 6,647 | **5,954** | −693 (−3.5pp) |
| 90th percentile | 8,298 | 7,851 | −447 |
| 99th percentile | 11,316 | 10,829 | −487 |
| **worst** | **17,446 (88.8%)** | **16,868 (85.8%)** | −578 (−2.9pp) |
| frames over budget | 0 of 5,499 | **0 of 5,499** | — |
| `gameFrameOver` | 0 | **0** | clean |
| `gameSpanOver` | 2 | 2 | unchanged |

**By scroll fine phase — this is the internal consistency check that matters:**

| fine | rows copied | HEAD median | C median | change |
|---:|---:|---:|---:|---:|
| 0 | 3 (+1 decode) | 8,141 | 7,709 | −432 |
| 1 | 4 | 6,698 | 5,935 | −763 |
| 2 | 4 | 6,635 | 5,912 | −723 |
| 3 | 4 | 6,641 | 6,023 | −618 |
| 4 | 4 | 6,643 | 5,921 | −722 |
| 5 | 4 | 6,663 | 6,250 | −413 |
| 6 | 1 | 3,604 | 3,591 | −13 |
| 7 | 0 (idle) | 4,522 | 4,522 | **+0** |

The idle frame is unchanged to the cycle and the one-row frame barely moves —
its 40 bytes cannot amortise a setup that is now larger — while the four-row
frames carry the whole saving. Nothing moved that should not have.

**By object population** (median): −486 to −703 at every load from 0 to 6
objects; worst-case −385 to −578. The gain is load-independent, as a scroller
change should be.

### Why not ~2,000 cycles

The hypothesis assumed the per-row overhead was the dominant term. It was 360 of
~2,650 cycles a frame. The copy *loop* is 2,236 of it, and the loop can only go
from 14 cycles a byte to 12.25 without the impractical constructions in §4 — so
the available saving was ~360 (overhead) + ~280 (loop) ≈ 640 pure, which is what
was obtained. Reaching 1,000–1,500 total for `regenTick` would need the copy loop
at ~9 cycles a byte, i.e. hundreds of bytes of generated code per group.

---

## 7. Correctness evidence

Output must be byte-identical to the already-correct implementation, and is.

| what | evidence |
|---|---|
| copied rows byte-identical | 10 complete back pages, 250/250 rows, against the captured oracle — keyed on world position, not frame number |
| vs. the committed build, turret destroyed mid-regeneration | **36 page images** (3 kill phases × 6 coarse steps × both pages) byte-identical to HEAD |
| vs. the committed build, stage fold | **11 cycles spanning the fold** (world rows 5→0, 799→795), all 25 rows byte-identical to HEAD on every one |
| newly exposed row decoded correctly | row 0 still goes through the unchanged `renderRow`; it is the only row decoded, and the oracle comparison covers it |
| screen-page ownership | `regenPageHi` unchanged as the destination selector; `statPageMismatch` and `statPtrMismatch` 0 across smoke |
| no partial destination becomes visible | the row schedule is unchanged — 25 rows still complete in 7 of the 8 frames — and `scrollLate`, the counter for a coarse step arriving on an unfinished page, is 0 |
| regeneration phase progression | group size is clamped so `regenRow + rgRows ≤ SCREEN_ROWS`; the row schedule was verified case by case and the measured `regenRow` in/out per frame matches the old build exactly (0→4, 4→8, …, 24→25) |
| turret state changed during regeneration | `tests/test_regen_page_shift.py` passes, including the corpse check |
| no off-by-one row or 40-byte displacement | a displacement of one row would show in all 250 oracle rows and in all 36 kill-case images; a `$23d8`-vs-`$2400` error would show as a 40-byte shear |
| overlap safety | asserted at build time; the matrices are 9,216 bytes apart |
| all eight patched operands actually written | decoded from the built binary: 4 `lda abs,y`/`sta abs,y` pairs, 16 operand bytes, 16 absolute stores, exact set match — no unpatched site, no stray store |

**The test is still sensitive.** The negative control — withholding the
`trtDeadPending` bit that the page repair waits on — still fails against the new
code with the right signature: `back cells [(2,17),(2,18),(3,17),(3,18)] front
cells [(1,17),(1,18),(2,17),(2,18)]`, the one-row offset, descending.

---

## 8. Tests

- `make build` clean, all four new assertions satisfied.
- `make smoke` **PASS** — boot, campaign loop across two levels, 4,004 frames,
  every fault counter 0 (`gameOverrun`, `scrollLate`, `edgeLate`, `statOverflow`,
  `statPageMismatch`, `statPtrMismatch`, `objDoubleFree`, `objAllocFail`,
  `clipPoolFull`, `publishSkip`, `schedBuildDefer`, `statLate`), engine health
  PASS, routine regression PASS.
- `tests/test_regen_page_shift.py` **PASS**, 7 checks (turret destroyed
  mid-regeneration at `regenRow` 12; stage fold compared against itself a lap
  later on both sides).
- `test_boot`, `test_production`, `test_lifecycle`, `test_level_assets` **PASS**.
- `test_turret_arming` **FAILS**, and it is test debt, not a regression — but it
  took direct evidence to establish that, because it had passed earlier in the
  same session. **Both builds fail it, on the same checks**, with only the build
  artefacts swapped:

  | build | run 1 | run 2 | run 3 |
  |---|---|---|---|
  | adopted (C) | FAIL (3) | FAIL (3) | FAIL (3) |
  | HEAD, unchanged | FAIL (3) | FAIL (3) | FAIL (1) |

  The failing checks are only section 5, "the same numbers with NOTHING POKED".
  Sections 1-4 — which seed `stageTopRow` and step frame by frame — pass on both,
  so the arming mechanism itself is verified unchanged.

  The cause is in the test's own `warp_ahead`, whose docstring states it: it
  free-runs toward the turret's arrival in **wall-clock** slices
  (`time.sleep(0.25)`, then `0.05`) and *"`x` overshoots by whatever a slice
  happens to cover"*. The caller leaves a 120-frame margin. How many frames a
  0.05s slice covers depends on host warp throughput, so the landing point is not
  deterministic — which is why HEAD's third run failed a different number of
  checks from its first two. **This test will also get harder to pass as the
  engine gets faster**, since a cheaper frame means more frames per slice and a
  larger overshoot; that is worth fixing in the test (free-run to a frameCounter
  target rather than a sleep budget) but it is not this pass's scope.
- Also pre-existing and confirmed identical on HEAD in the previous session:
  `test_turret_regression`, `test_clip_scratch`, `test_bank2_arena`. Stale-content
  / timing-window test debt, not production failures.
- `make test-soak` — **the tier the Makefile names for a scroller change**
  (*"Run it when the renderer, scroller or level data changes"*): 5 passed,
  4 failed, 470s. `regen_page_shift`, `flight_paths`, `production`,
  `species_order`, `square_species` pass. The four failures are **pre-existing**,
  and attributed by running the same four suites against the HEAD reference
  binary with only the build artefacts swapped — **identical failure counts on
  both**:

  | suite | adopted (C) | HEAD, unchanged |
  |---|---|---|
  | `dropper_flight` | FAIL (12) | FAIL (12) |
  | `encounter_director` | FAIL (2) | FAIL (2) |
  | `ingress_egress` | FAIL (2) | FAIL (2) |
  | `token_encounter` | FAIL (1) | FAIL (1) |

  All four are gameplay/content assertions — flight bands, concurrent wave
  instances, where an enemy is freed, how three guards space themselves around a
  token. None reads the screen matrix. Test debt, not production failure.
- Mux and raster suites were **not** run: this change touches neither. It alters
  only how bytes reach the back matrix, not the schedule, the aperture, sprite
  ownership or any IRQ.
- Everything run **serially**; nothing else was on the machine.

---

## 9. Remaining largest whole-frame costs — context only, not touched

Busy frames (population ≥ 4), after this change:

| # | phase | median | worst | % frame |
|---|---|---:|---:|---:|
| 1 | `buildSchedule` | 2,750 | 4,848 | 14.0% |
| 2 | `regenTick` | 2,618 | 3,440 | 13.3% |
| 3 | `objectUpdateAll` | 1,422 | 3,810 | 7.2% |
| 4 | `playerTick` | 393 | 456 | 2.0% |
| 5 | `playerEmit` | 373 | 404 | 1.9% |
| 6 | `sortTick` | 369 | 3,012 | 1.9% |
| 7 | `pickupPlayerTick` | 302 | 993 | 1.5% |
| 8 | `scrollTick` | 169 | 515 | 0.9% |

**`regenTick` is no longer the largest phase.** `buildSchedule` now is, and it has
never been examined. Every other phase is unchanged to within noise
(`buildSchedule` 2,754 → 2,750, `objectUpdateAll` 1,419 → 1,422, `playerTick`
393 → 393, `sortTick` 369 → 369), which is the evidence that this change is
isolated to the copy.

Not pursued in this pass, per scope.

---

## 10. Housekeeping

**Files changed**

| file | change |
|---|---|
| `src/scroll.asm` | `regenTick` computes the group once; `copyRowFromFront` → `copyRowsFromFront` as one contiguous unrolled copy, relocated to `$6300`; `rgRows` state; 3 new assertions |
| `src/turrets.asm` | turret-tables ceiling tightened `$6400` → `$6300`, with the reason |
| `tests/test_regen_page_shift.py` | one new static section (3 checks) on the unrolled copy's patched operands |
| `reports/regen-contiguous-row-copy.md` | this report |

**The existing test needed no change to keep working** — its two behavioural
sections pin what can break a copying regeneration and they passed unmodified,
which is the right outcome for a test written against behaviour rather than
implementation.

What was *added* is deliberately an implementation check, and the only one in the
file: the unrolled copy now carries four `lda abs,y`/`sta abs,y` pairs whose
sixteen operand bytes the setup patches at run time, and an intermediate version
of this routine in the previous pass patched two of eight and left the other six
addressing `$ffff`. The new section decodes the routine out of the built binary
and asserts every operand byte is written. It needs no emulator, runs in
milliseconds, and names the byte that was missed.

Confirmed sensitive by negative control: deleting a single `sta cpSrc3 + 1` from
the setup makes it report `UNPATCHED: ['0x6363']` rather than passing.

**Disk.** Scratchpad 37M (disposable probes, the HEAD reference disk image, page
captures, variant sources); `build/` 340K. Nothing per-run was written under
`build/`, which holds only the current binary and symbols.

**VICE hygiene.** Every launch owned by PID and reaped; `pgrep x64sc` reports 0
afterwards; no broad `pkill`, no user session touched, all runs `-console`.

**Final `git status`** — three modified files and one new report, nothing else:

```
 M src/scroll.asm
 M src/turrets.asm
 M tests/test_regen_page_shift.py
?? reports/regen-contiguous-row-copy.md
```

**No commit and no push were made.**

**Not claimed.** No manual visual confirmation was performed in this pass. The
user has previously reported the visible skip gone; every result here is
automated measurement, and the stripped stress encounter remains the
authoritative case.
