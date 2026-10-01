# 19656 — Whole-Frame Performance Audit and `regenTick` Optimisation

**Date:** 2026-10-01
**Scope:** treat the whole game frame as an engine concern; start with the
largest identified cost, `regenTick`; re-measure; produce a fresh optimisation
map ranked by measured payoff.
**Outcome:** `regenTick` is cut **35%** (5,009 → 3,228 cycles per working
frame). The worst measured frame of the stripped stress encounter moves from
**20,036 cycles (101.9% of a PAL frame) to 17,446 (88.8%)**, and the engine's
own exact overrun counter `gameFrameOver` goes **1 → 0**. Equivalence is proved
byte-for-byte against the unmodified build, including the two cases the first
measurement could not see. **The 14,500–15,500 target is not reached**; §7 says
what would reach it and what it is worth.

No commit, no push. The stripped stress encounter is untouched and unweakened.

---

## 1. What `regenTick` actually is

Not a per-frame routine with a per-frame cost. It is **periodic multi-frame
work**, and a single frame's reading says almost nothing about it.

The scroller keeps two screen matrices (`SCREEN_A = $0400`,
`SCREEN_B = $2800`). One is displayed; the other is rebuilt a few rows at a
time and then flipped in. A coarse scroll step happens every 8 frames, and
`regenTick` rebuilds `ROWS_PER_TICK = 4` rows per frame — so all
`SCREEN_ROWS = 25` rows finish inside **7 of the 8 frames**, and the 8th is
deliberately left idle for `src/turrets.asm` to derive the next step's geometry
there (`TURRET_PREPARE_FINE = 7`).

The call tree, and where the time went in the unmodified build:

| | per row, elapsed | share |
|---|---:|---:|
| `regenTick` → `renderRow` | 1,443 | 100% |
| ` → renderTerrainRow` (metatile map → 40 character codes) | 1,218 | **85%** |
| ` → turretOverlayRow` (the turret composite) | ~225 | 15% |

`turretOverlayRow` early-exits on sub-rows 0 and 3, so its average is well under
its worst.

**A whole episode — one coarse step to the next — in the unmodified build:**

| scroll fine | rows done | cycles | % of a PAL frame |
|---:|---:|---:|---:|
| 0 | 4 | 6,199 | **31.5%** |
| 1 | 4 | 5,773 | 29.4% |
| 2 | 4 | 5,746 | 29.2% |
| 3 | 4 | 5,752 | 29.3% |
| 4 | 4 | 5,934 | 30.2% |
| 5 | 4 | 5,776 | 29.4% |
| 6 | 1 | 903 | 4.6% |
| 7 | 0 | 21 | 0.1% |
| **episode** | 25 | **36,104** | — |

All figures are **elapsed**: measured with breakpoint pairs and the emulator's
own cycle counter, so raster interrupts and VIC DMA theft are included. That is
what the 19,656-cycle PAL budget actually pays for. A monitor stop consumes no
emulated cycles.

---

## 2. Baseline whole-frame ledger

Measured on the stripped stress encounter with the **trigger held and the ship
swept**, because a parked ship with no volley is not the load that overruns.
5,499 frames.

**Whole frame body** (`gameFrame` → `gameSpan`, `src/main.asm:750`–`986`):

| | cycles | % of frame |
|---|---:|---:|
| median | 8,703 | 44.3% |
| 90th percentile | 9,756 | 49.6% |
| 99th percentile | 13,024 | 66.3% |
| **worst** | **20,036** | **101.9%** |

Frames over budget: **1 of 5,499**. `gameFrameOver` = **1**.

**Per phase, busy frames only** (population ≥ 4 — the frames that decide whether
the engine fits):

| phase | median | worst | % of frame | cumulative |
|---|---:|---:|---:|---:|
| `regenTick` | 5,009 | 5,741 | **25.5%** | 42.5% |
| `buildSchedule` | 2,753 | 4,845 | 14.0% | 65.8% |
| `objectUpdateAll` | 1,419 | 3,825 | 7.2% | 77.9% |
| `playerTick` | 393 | 456 | 2.0% | 81.2% |
| `playerEmit` | 373 | 404 | 1.9% | 84.4% |
| `sortTick` | 369 | 3,012 | 1.9% | 87.5% |
| `pickupPlayerTick` | 302 | 993 | 1.5% | 90.1% |
| `scrollTick` | 171 | 513 | 0.9% | 91.5% |

A first attempt at this table ran with the ship parked and reported
`collisionTick` at **24 cycles** — the cost of finding nothing in an empty pool.
A ranking built on that would have sent this pass at the wrong routine. **The
load has to be real for the ledger to mean anything.**

---

## 3. The alternatives considered

**A — leave it.** 25.5% of a busy frame, and the single largest term. No.

**B — do the same work more cheaply.** `renderTerrainRow` already uses a
transposed `trTiles` table, four self-modified page-high-byte patch sites, a
metatile-row id cache and a single-conditional modulo. Its inner loop is 77
cycles per metatile (18 index setup, 54 for four characters, 5 loop). Unrolling
it converts 4 patch sites into 40. Measured headroom: **≈55 cycles a row** — 4%
of the row, for a large increase in self-modified code. Rejected.

**C — schedule it differently.** Spreading 25 rows over more frames lowers the
per-frame peak but not the episode total, and the 8th frame is already spoken
for by turret preparation. The work must still finish before the next coarse
step. Rejected: it moves cost around rather than removing it.

**D — don't regenerate what already exists. Chosen.**

A coarse step moves the world by **exactly one character row**. So the page
being rebuilt shows the same terrain as the displayed one, shifted down a row:

```
    backRow[r] == frontRow[r - 1]        for r = 1 .. 24
```

Only **row 0** carries content that is new to the screen. The other twenty-four
were being recomputed, at 1,443 cycles each, from a metatile map — to produce
bytes that already sat **forty bytes away in the other page**.

Measured before being relied on: checked at the idle frame of **14 consecutive
coarse steps** with the player firing — **24/24 rows matched byte for byte every
time, turret overlay included, 0 mismatches**, delta always −1.

---

## 4. What was implemented

`src/scroll.asm`: `regenTick` decodes row 0 through the existing `renderRow` and
copies rows 1–24 from the displayed page through a new `copyRowFromFront`.

**The other page's high byte is one EOR.** `PAGE_HI_FLIP = (SCREEN_A >> 8) ^
(SCREEN_B >> 8)`, with a build-time `.error` asserting the two pages still
differ by a single EOR — it is the kind of trick that silently addresses nothing
if a page ever moves. The EOR is applied to the **page base** before the row's
high byte is added, not to the sum. EORing the sum also works today, but only
because `rowHi` never leaves the two bits that `$2c` happens to leave alone;
that is a coincidence, not a reason.

**The copy loop is rolled, and that is a measured choice, not laziness.**
Unrolling four bytes an iteration saves the `dey`/`bpl` three times out of four
— about 90 cycles a row — but each unrolled copy carries its **own** absolute
operand, so the setup must patch eight addresses instead of two: about 84
cycles. The two cancel. The rolled form runs at the same speed with a quarter of
the self-modified code to get wrong. (An intermediate version of this change had
the unrolled body with only two of its eight sites patched — the other six still
read and wrote `$ffff`.)

---

## 5. Equivalence: the same screen, byte for byte

A cycle saving on a renderer is worth nothing without this.

**(a) Ten complete pages against the unmodified build.** Ten back pages captured
from the unmodified engine at the idle frame of ten consecutive coarse steps,
turret overlay live, then replayed against the new build: **250/250 rows
byte-identical.**

Two methodology corrections were needed to make that comparison mean anything,
and both initially produced confident nonsense:

- **Frame numbers do not align across runs.** The warp boot loop is wall-clock
  sensitive (`tests/harness.py:350`), so two VICE runs reach a given frame at
  different scroll positions — here a constant 23 rows apart. Comparison is keyed
  on `regenTopRow`, the world position, which is the same world in both runs.
- **`regenPageHi` names the page about to be rebuilt.** Sampling at the flip
  returns content two coarse steps old, which showed up as the oracle's own row
  sequence rotated by exactly two. Pages are sampled only once the cursor has
  reached the last row.

A third correction was more serious: the comparison initially reported the
baseline and optimised builds as **identical to the cycle**, which was not
plausible. `tests/harness.py:277` silently substitutes the disk image for any
argument ending in `.prg`, because a bare PRG has no drive to load the level
package from — so overriding the PRG measured the current build whichever path
was passed. Both runs had been the optimised build. The probes now **refuse** a
`.prg` override rather than quietly measure the wrong thing.

**(b) A turret destroyed part way through a cycle.** The one event that can break
the copy: the overlay is not a function of the metatile map alone, it depends on
`turretAlive`, which changes in time. Destroyed at `regenRow` 4, 12 and 20, six
cycles each, both pages: **byte-identical to the unmodified build in all 36 page
pairs.**

The repair contract in `src/turrets.asm` does cover the copy, as its comment
claims — it repairs **both** pages, each against its own top row, and what it
writes is the authoritative decode rather than a cache.

An earlier version of this test appeared to find a **propagating corpse**: the
dead body copied from page to page, descending one row per coarse step, for
ever. That was the test's fault, not the engine's — it omitted the
`trtDeadPending` bit (`src/turrets.asm:1617`) that the repair actually waits on,
so no repair ever ran and *both* builds were wrong in their own way. The failure
mode is real enough to be worth pinning permanently, which is what §6 does.

**(c) The stage fold.** `regenTopRow` counts down and folds 0 → 799, so the
window's source jumps from one end of the metatile map to the other while the
screen still moves by a single row. Driven to the fold naturally using the
engine's own `stageHold` endless-stage diagnostic rather than by poking derived
scroll state into a configuration the engine would never reach: **11 cycles
spanning the fold, every page byte-identical to the unmodified build.**

---

## 6. The permanent test

`tests/test_regen_page_shift.py` — 7 checks, ~40s, added to `test-soak` (which
the Makefile already says to run when the scroller changes) and `test-full`.

The equality `backRow[r] == frontRow[r-1]` is now true **by construction**, so
asserting it would prove nothing. The test pins the two cases where the screen
is *not* simply the previous screen shifted: a turret destroyed mid-cycle, and
the stage fold. Both checks are self-referential — the turret case asserts an
absence, the fold case compares the stage against **itself one lap later** — so
no campaign bytes are frozen and re-authoring level 1 cannot make the file
wrong.

**It was built with a negative control, and needed it.** Two successive versions
of the corpse check passed when the repair trigger was deliberately withheld:

1. The first derived the body's character codes by watching which characters
   disappeared when the turret died — using the repair to identify the body, then
   checking the repair had removed it. Withholding the repair left nothing to look
   for, and the test passed. The body glyph set now comes from the engine's own
   constants (`TURRET_GLYPH_BASE`, span 4 → 226–229), which `src/turrets.asm:63`
   asserts at build time sits above every terrain glyph.
2. The second bounded body cells by the number of turrets still *alive* — but
   seven can be alive with only one anywhere near the aperture, so the allowance
   was 28 cells against a 4-cell corpse. The check now asks the precise question:
   does **this** turret's body still appear in **this** turret's columns, having
   first asserted no other standing turret shares them?

With the repair withheld the test now fails with exactly the right signature —
`back cells [(2,17),(2,18),(3,17),(3,18)] front cells [(1,17),(1,18),(2,17),(2,18)]`,
the one-row offset, descending.

---

## 7. After: measured

Same probe, same input sequence, 5,499 frames each.

**Whole frame body:**

| | baseline | optimised | change |
|---|---:|---:|---:|
| median | 8,703 | **6,647** | −2,056 (−10.5pp) |
| 90th percentile | 9,756 | 8,298 | −1,458 (−7.4pp) |
| 99th percentile | 13,024 | 11,311 | −1,713 (−8.7pp) |
| **worst** | **20,036 (101.9%)** | **17,446 (88.8%)** | **−2,590 (−13.2pp)** |
| frames over budget | 1 | **0** | |
| `gameFrameOver` | 1 | **0** | |

**By object population** — the gain is present at every load, not just the peak:

| live objects | baseline med/worst | optimised med/worst | median delta |
|---:|---:|---:|---:|
| 0 | 8,690 / 12,782 | 6,638 / 11,383 | −2,052 |
| 1 | 10,016 / 13,628 | 8,283 / 11,980 | −1,733 |
| 2 | 10,437 / 14,971 | 8,700 / 13,357 | −1,737 |
| 3 | 11,071 / 14,687 | 9,351 / 13,283 | −1,720 |
| 4 | 11,720 / 13,826 | 10,023 / 12,419 | −1,697 |
| 5 | 13,504 / 17,827 | 11,749 / 16,336 | −1,755 |
| 6 | 14,390 / **20,036** | 12,591 / **17,446** | −1,799 |

**`regenTick` itself:**

| | baseline | optimised | change |
|---|---:|---:|---:|
| episode total (25 rows) | 36,104 | **23,322** | **−35.4%** |
| per working frame, busy, median | 5,009 | **3,228** | −1,781 (−35.6%) |
| peak single frame | 6,199 (31.5%) | **4,813 (24.5%)** | −1,386 |

**The change is isolated.** Every other phase is unchanged to within noise —
`buildSchedule` 2,753 → 2,754, `objectUpdateAll` 1,419 → 1,419, `playerTick`
393 → 393. That is the strongest evidence that nothing else moved.

**Where the target stands.** The brief asked for worst normal gameplay frames
near 14,500–15,500 and said explicitly that substantial improvement without
reaching it is acceptable. Worst is **17,446**. `gameSpanOver` — frames whose
span exceeds 255 raster lines, i.e. 82% of a frame — is still non-zero, because
88.8% is still above 82%. **The headroom is real but it is not comfortable.**

---

## 8. Fresh optimisation map, ranked by measured payoff

Busy frames (population ≥ 4), optimised build:

| # | phase | median | worst | % frame | assessment |
|---|---|---:|---:|---:|---|
| 1 | `regenTick` | 3,228 | 3,924 | 16.4% | ~95% of it is now the copy; see below |
| 2 | `buildSchedule` | 2,754 | 4,849 | 14.0% | **untouched, and the worst case is the largest of any phase** |
| 3 | `objectUpdateAll` | 1,419 | 3,810 | 7.2% | scales with population |
| 4 | `playerTick` | 393 | 456 | 2.0% | flat and small |
| 5 | `playerEmit` | 373 | 404 | 1.9% | flat and small |
| 6 | `sortTick` | 369 | 3,019 | 1.9% | median small, worst 8× — spiky |
| 7 | `pickupPlayerTick` | 302 | 993 | 1.5% | small |
| 8 | `scrollTick` | 183 | 514 | 0.9% | small |

Everything below `scrollTick` is under 1% of a frame; there is nothing there
worth a pass.

**Recommended next target: a single contiguous block copy in `regenTick`.**
Back rows 1–24 are bytes 40..999 of one page; front rows 0–23 are bytes 0..959
of the other. These are **contiguous regions at a constant 40-byte offset** — so
the per-row loop, and all of its per-row address patching, is unnecessary. Four
rows a frame is one 160-byte copy with **one** setup instead of four, and a
contiguous copy can be unrolled freely because there is only one address pair to
patch. At an unroll of 8 (≈9.6 cycles a byte against the current 14) the
estimate is **≈800 pure cycles a frame, ≈1,080 elapsed** — about 5.5% of a
frame, for a routine that gets simpler rather than more complex. This is the
cheapest remaining win in the engine and it should be done first.

**Then `buildSchedule`.** 2,754 median and a 4,849 worst — the largest worst case
of any phase, and it has never been examined. It is the multiplexer's schedule
construction and it is now within 500 cycles of `regenTick`.

**`sortTick` and `objectUpdateAll`** are worth a look only for their spikes
(3,019 and 3,810 against medians of 369 and 1,419). A spike that lands on the
same frame as a `fine 0` regen is how a frame goes over, so the variance matters
more than the median here.

**Do not pursue `collisionTick` further.** 24 cycles median, 1,657 worst, after
the −34% in `reports/twin-ray-hitscan-optimisation.md`. It is not where the
frame goes.

---

## 9. Verification performed

- `make build` clean.
- `make smoke` **PASS** end to end — boot, campaign loop across two levels,
  4,066 frames, every fault counter zero (`gameOverrun`, `scrollLate`,
  `edgeLate`, `statOverflow`, `statPageMismatch`, `statPtrMismatch`,
  `objDoubleFree`, `objAllocFail`, `clipPoolFull`, `publishSkip`,
  `schedBuildDefer`, `statLate`), engine health PASS, routine regression PASS.
- `tests/test_regen_page_shift.py` **PASS** (7 checks), with the negative control
  confirmed to fail.
- `test_boot`, `test_production`, `test_lifecycle`, `test_level_assets`,
  `test_turret_arming` **PASS**.
- `test_turret_regression`, `test_clip_scratch`, `test_bank2_arena` **FAIL** —
  and fail **identically on HEAD**, with the same failure messages and counts,
  with `src/scroll.asm` reverted. Pre-existing, not caused by this change.
- Every suite run **serially on an idle machine**. Running the Tk suite or a
  build alongside a VICE suite contaminates results; `tests/harness.py:350`
  documents the warp boot loop as wall-clock sensitive.

**Working tree.** `git status` is exactly as it was at the start of the session:
`src/collision.asm`, `src/main.asm`, `src/renderer.asm`, `src/scroll.asm`
modified; `reports/twin-ray-hitscan-optimisation.md` and
`tests/test_hitscan_twin_ray.py` untracked — plus this report, the new test and
the Makefile tier registration. Baseline binaries for the before/after
comparison were built by temporarily substituting `git show HEAD:src/scroll.asm`
and restoring from a saved copy, verified byte-identical by checksum each time.
No destructive git operations. No commit, no push.

**Disk.** Scratchpad 36M (disposable probes, two baseline disk images, captured
page oracles); `build/` 340K.

**Not claimed.** No manual visual confirmation was performed. Every result above
is automated measurement. The stripped stress encounter remains the authoritative
case and should be played.
