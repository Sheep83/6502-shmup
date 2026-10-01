# `buildSchedule` performance audit

**Date:** 2026-10-01
**Scope:** measurement and one bounded builder change. The executor, the
acceptance rule, the slot mapping, the publication model, the handoff and the
six-slot HW2–HW7 contract are untouched.
**Committed or pushed:** no. **No destructive git operation was used.**

---

## 0. The finding, first

The worst case does not come from population, geometry, sort order or batching.
**It comes from clipping.** Measured, on the real machine:

| six accepted sprites | `setup+accept` cycles | per sprite |
|---|---:|---:|
| 0 clipped | 1,866 | 311 |
| 3 clipped | 5,749 | 958 |
| 6 clipped | **9,805** | 1,634 |

An ordinary sprite costs **~312 cycles**; a clipped one costs **~1,632** — more
than five times as much. The extra is `jsr clipMakeScratch`, called from the
accept path, at **~1,320 cycles each**.

Population alone is almost perfectly linear and cheap by comparison: 1, 3, 6, 9
and 12 unclipped sprites cost 486, 1,036, 1,866, 2,799 and 3,738 — a flat
**312 cycles per sprite** with ~174 cycles of fixed overhead.

So the reported ~4,848-cycle worst build is roughly "a normal population with
two or three clipped sprites in it", and the lever that matters for future
headroom is `clipMakeScratch`, not the scheduler's own logic.

The scheduler's own logic turned out to be close to optimal. One clean saving
was found and taken; it is modest, and the report says so rather than dressing
it up.

---

## 1. Starting state

`git status` clean at `26f07c8 regenTick optimised`. Reports read:
`whole-frame-audit-and-regen-optimisation`, `mux-legality-window-batch-merge`,
`mux-glitch-diagnostic-pass-1`, `regen-contiguous-row-copy`,
`2026-09-13-fable-mux-capacity-audit`, `post-mux-test-gate-cleanup`.

**`buildSchedule` has been optimised before.** `mux-legality-window-batch-merge`
(2026-09-13) replaced exact-equality batch grouping with open-then-absorb over a
legality window. That work is present in the current source and was preserved;
the batch pass measured here is the merged one, not the old one.

---

## 2. The algorithm as it stands

```
buildSchedule                       $1000
  withdraw pending publication, reset stat counters, clipBuildBegin
  compute bs_base from schedNext, copy the 10-byte player block
  seed bs_enable / bs_d010 from the player's two bits
  ACCEPTANCE PASS   walk sortedIDs ascending-Y:
      clamp Y for clipped entries, range-test, capacity-test,
      reuse-test against accepted entry i-6, then accept:
      assign slot (acc mod 6) + 2, write 8 schedule fields,
      accumulate $D010 and $D015, clipMakeScratch if clipped
  bs_accepted_done  $11d6
  BATCH PASS        open-then-absorb over the legality window
  bs_batchDone      $12a3
  TAIL              batchD010 per batch, widest mid-screen batch
  bs_dDone
```

Every stage boundary is a real symbol, which is what made an exact ledger
possible without adding instrumentation to the build.

---

## 3. Method

Elapsed cycles between PC-verified breakpoints, read from VICE's own stopwatch
(`sw`). A monitor stop consumes no emulated cycles.

**Pure vs elapsed.** Stage figures are taken with the raster IRQ masked at
`$d01a` across the call and restored immediately after, so they measure the
algorithm rather than whatever the executor was doing. Whole-frame figures stay
elapsed, because that is what the 19,656-cycle PAL frame actually pays for.

**Pure is not noise-free, and the report does not pretend otherwise.** VIC
sprite-DMA theft still varies with where in the frame the build lands, so
repeated runs of the same case differ by a few hundred cycles. Every
single-number claim below is the **minimum of three runs** — the sample with
least DMA interference. Differences smaller than ~500 cycles in a one-shot total
are treated as noise.

**Driving the builder without hijacking the CPU.** The lab breaks on
`buildSchedule`'s own entry — main-thread by construction — and writes the
logical arrays there, so the builder runs its ordinary course on synthetic
input. Nothing sets `PC`, so the project's rule about never hijacking the CPU
inside the IRQ handler cannot be violated.

---

## 4. Stage ledger, before the change

Pure cycles, synthetic corpus:

| case | n | acc | batches | accept | batch | widest | d010 | total |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| empty | 0 | 0 | 0 | 241 | 75 | 55 | 18 | 389 |
| even-6 | 6 | 6 | 1 | 1,866 | 112 | 40 | 70 | 2,088 |
| even-8 | 8 | 8 | 2 | 2,488 | 274 | 81 | 122 | 2,965 |
| even-12 | 12 | 12 | 4 | 4,146 | 799 | 163 | 269 | 5,377 |
| even-16 | 16 | 16 | 6 | 5,530 | 1,236 | 288 | 330 | 7,384 |
| even-24 | 24 | 24 | 10 | 8,123 | 2,245 | 454 | 583 | 11,405 |
| clipped-mixed | 3 | 3 | 1 | 3,797 | 154 | 40 | 70 | 4,061 |

**`setup+accept` is 60–97% of every build.** The batch pass is ~220 cycles per
batch; the two tail loops together were ~110 at one batch and ~1,037 at ten.

### Scaling

* **per logical sprite**: 312 cycles, flat, whether accepted or rejected
  (a rejected sprite still pays clip, range and reuse tests — `cluster-12-sameY`
  rejects six and still costs 195 each);
* **per clipped sprite**: +1,320 on top;
* **per batch**: ~220 in the batch pass plus ~104 across the tails (before);
* **fixed**: ~174 in accept, plus ~150 across setup and the tails.

### What is *not* a cost

* **No full-capacity scan anywhere.** Every loop is bounded by `sortedCount`,
  `bs_acc` or `bs_nb`. The 389-cycle empty build is the stat resets, the
  10-byte player block copy and `clipBuildBegin` — all real work.
* **No schedule clearing.** Nothing wipes `MAX_SCHED` entries.
* **Sort order is free.** `sorted-8`, `sorted-8-ids-reversed` and
  `sorted-8-wide` cost the same. `buildSchedule` performs no sorting; it
  consumes `sortedIDs`. The separately measured `sortTick` is a different
  routine and is out of scope here, as instructed.
* **Reuse geometry is free.** Spacing below, at and above `MIN_REUSE_GAP`
  measured 2,009 / 1,867 / 1,866 — within noise.
* **`$D010` preparation is free.** `xmsb-mixed` and `xmsb-all-high` measured
  1,861 and 1,854 against a 1,866 baseline.

---

## 5. The corpus

Deterministic, driven directly into the logical arrays, independent of campaign
content. 31 cases: empty; 1; 2, 4, 6; 7, 8; 12, 16; 24 at capacity; same
population with different ID order; dense single-Y clusters at 6 and 12; two
separated clusters; spacings below/at/above `MIN_REUSE_GAP`; six needing no
reuse; top and bottom aperture edges; wholly out-of-range populations high and
low; mixed clip states; X either side of 256 and all-high; and four seeded fuzz
cases retained as fixtures.

**Order is a precondition, not a variable.** `buildSchedule` documents that
`sortedIDs` is ascending in Y — the reuse rule compares against accepted entry
*i−6* and is sound only on such a list — and `sortTick` guarantees it. An early
version of the corpus fed reversed and shuffled lists; those are not awkward
inputs, they are contract violations, and they were replaced with cases that
vary ID order under an ascending Y population.

### A real property the corpus exposed

**Clipping clamps Y to the aperture edge (55 or 226), so a list correctly
ascending in logical Y can present a descent in the Y the builder schedules.**
`clipped-mixed` (logical Y 100, 110, 120 with clip 0, 1, 2) schedules Y 100, 55,
55. The builder handles it: a negative reuse gap takes the `bs_unsafe` path and
the entry is rejected rather than scheduled illegally, counted in
`statRejUnsafe`. That is the deterministic handling the contract requires, and
the invariant checker was corrected to test ordering over unclipped entries
rather than assert something untrue of clipped ones.

---

## 6. The change

**The two tail loops are now one.** They walked the same range — batches
`0..nb-1` — each carrying its own compare, its own `clc / adc bs_bbase / tay`,
its own `inc` and its own `jmp`: about twenty cycles of loop overhead per batch,
paid twice, for a few cycles of real work.

`src/renderer.asm` only. `bs_mbLoop` / `bs_mbDone` removed; `bs_dLoop` does both
jobs. `statMaxBatch` still skips batch 0 (the handoff block); `batchD010` is
still the cumulative value belonging to the batch's last entry. No other
behaviour changed.

| batches | widest + d010, before | tail, after | saved |
|--:|--:|--:|--:|
| 1 | 40 + 70 = 110 | 97 | 13 |
| 2 | 81 + 122 = 203 | 169 | 34 |
| 4 | 163 + 269 = 432 | 313 | 119 |
| 6 | 288 + 330 = 618 | 500 | 118 |
| 10 | 454 + 583 = 1,037 | 835 | 202 |

**~13 cycles per batch.** Code size: `bs_dDone` moved `$1300` → `$12eb`,
**21 bytes smaller**.

That is a small win and it is reported as one. On a realistic two-batch build it
is ~34 cycles against ~3,000 — about 1%.

---

## 7. What was examined and rejected

* **Folding the tail into the batch pass entirely.** A batch's final count and
  last entry are known only when it closes, and closes happen at several jump
  targets inside the absorb loop. Folding would put work in the hot loop and
  touch the open-then-absorb logic that the previous mux work established and
  the glitch diagnostic validated. The ceiling is the ~835 cycles the merged
  tail still costs at ten batches, and realistic builds have two to four.
  Not worth the risk to that code.
* **Incremental schedule index.** `lda bs_acc / clc / adc bs_base / tay` per
  accepted entry is ~12 cycles and could be a maintained pointer at ~3. Saves
  ~9 of 312 per sprite — **3%**, against touching the accept path's register
  discipline. Rejected as not worth it on its own.
* **Skipping `bs_enable` accumulation after six entries.** The test costs what
  the `ora` costs. No saving.
* **Deriving `schedSlot2` in the executor** instead of storing it. It is read by
  the executor; moving the shift there pays it per frame per entry rather than
  per build. Worse, and it changes the executor contract.
* **Rewriting the accept path.** The 312 cycles per sprite are the loop head,
  the clip/range/capacity/reuse tests and twelve schedule stores. There is no
  large algorithmic win there without removing fields the executor needs.

**The accept path is close to optimal for what it must produce.** That is a
valid result and the brief says so; it was not rewritten merely to produce a
change.

---

## 8. Correctness

Mechanical invariant checking over all 31 corpus cases, reading the built
schedule back out of memory:

1. accepted count within `MAX_SCHED`;
2. `schedY` ascending over unclipped entries;
3. every accepted Y inside the aperture;
4. every slot inside the HW2–HW7 pool — HW0/HW1 never touched;
5. round-robin assignment: entry *i* owns slot `(i mod 6) + 2`;
6. every reuse clears `MIN_REUSE_GAP`;
7. no entry overlaps its slot's previous owner;
8. batches contiguous, ordered, `1..6` entries, covering exactly the accepted
   set;
9. every batch programmed at or before its entries' `Y − REUSE_LEAD` deadline;
10. X, X-MSB, pointer and colour carried through from the logical arrays;
11. `batchD010` equals the bit pattern implied by every entry up to that batch;
12. `schedEnable` has a bit for every slot in use.

**Result: 0 violations across 31 cases**, including the 24-entry capacity case,
the dense same-Y clusters, both aperture edges, mixed clipping, both sides of
X=256, and four seeded fuzz populations.

---

## 9. Whole-frame effect

The change saves ~13 cycles per batch. A realistic build has two to four
batches, so the whole-frame effect is **~30–120 cycles out of ~16,900** —
roughly **0.2–0.7%** of a PAL frame. It does not move the whole-frame worst case
into the 14.5–15.5k band the brief would like, and no honest reading of these
measurements suggests the scheduler's own logic could.

**Where that headroom actually lives, with numbers:** six clipped sprites cost
**9,805** cycles against **1,866** for six unclipped. `clipMakeScratch` is
~1,320 cycles per clipped sprite, called from inside `buildSchedule`'s accept
path. On a frame with three clipped sprites that is ~4,000 cycles — about 20% of
the entire PAL frame, spent in one subroutine.

That is the next lever, and it is a much larger one than anything left in the
scheduler. It is **not** attempted here: `clipMakeScratch` is a different
routine with its own correctness contract around the clip scratch pool, and the
brief scopes this task to `buildSchedule`. Reported as the recommended next
target, not as work done.

---

## 10. Tests

| suite | result |
|---|---|
| synthetic corpus, 31 cases | **0 invariant violations** |
| seeded fuzz fixtures (4) | **0 violations** |
| `test_clip_scratch.py` | **3 failures — pre-existing** |
| `test_ebullet_clipping.py` | pass |
| `make smoke` | **PASS** — `ENGINE HEALTH: PASS`, `ROUTINE REGRESSION: PASS`, every fatal counter zero, `schedBuildDefer` 0, `statLate` 0 |

### The `test_clip_scratch` failures are not mine

Proved rather than assumed. The same three assertions fail **identically** on a
binary built from the pre-change `renderer.asm` and on the changed one:

```
### AFTER  (my change)    === 3 FAILURES: every scratch bitmap is one of the
                             enemy's frames shifted ... ; a clipped enemy's true
                             logY ... ; clipping walks one row at a time ...
### BEFORE (pre-change)   === 3 FAILURES: (identical)
```

They assert that scratch bitmaps equal "one of the enemy's frames" — a property
of the enemy **artwork**, which changed when the roster landed and Ring 3
replaced the four-frame Sonic Ring. Stale content assertion, not an engine
fault, and out of scope here.

---

## 11. Raster and the architectural contract

Nothing in the executor, the handoff or the batch representation changed, so no
raster deadline moved. The change is confined to two statistics computed after
the batch records are already final:

* `statMaxBatch` — a diagnostic counter, read by nothing the executor depends on;
* `batchD010` — same value, same place, computed in the same order.

`MIN_REUSE_GAP`, `REUSE_LEAD`, `HANDOFF_LINE`, `MUX_SLOTS`, `MAX_SCHED` and the
HW0/HW1 reservation are untouched. The invariant sweep in §8 re-proves the
deadline and reuse contracts against the built schedule.

---

## 11a. Disk

`build/` 404K — only the current binary and symbols, no per-run directories.
Session scratchpad 264K (the lab, the corpus, the before/after renderer copies);
disposable, outside the repository.

---

## 12. Files changed

| File | Change |
|---|---|
| `src/renderer.asm` | the two tail loops merged into one; `bs_mbLoop`/`bs_mbDone` removed; 21 bytes smaller |
| `reports/buildschedule-performance-audit.md` | new |

No test file, level, tool or constant was changed.

---

## 13. Is this a sound baseline for the 6+2 vs 7+1 vs 8-slot experiment?

**Yes, and the measurements make the comparison sharper than it would have
been.**

The scheduler is now characterised rather than assumed: a flat 312 cycles per
logical sprite, ~220 per batch, ~174 fixed, and a clipping surcharge of ~1,320
per clipped sprite. Those four numbers predict a build's cost directly, so when
the slot count changes the *expected* cost can be computed and compared with the
measured one — which is a much stronger test than watching a single worst-case
number move.

Two cautions for that experiment:

1. **Slot count moves the batch term, not the per-sprite term.** More slots means
   fewer batches for the same population (~220 cycles each) and fewer rejections
   from the reuse rule. It does not change the 312 cycles a sprite costs.
2. **Clipping will dominate any slot-count difference.** A layout with three
   clipped sprites spends ~4,000 cycles in `clipMakeScratch` regardless of how
   the slots are arranged. The hostile layouts planned for that experiment
   should control for clipping explicitly, or the slot comparison will measure
   clipping instead.

The six-slot HW2–HW7 contract and the HW0/HW1 reservation are exactly as they
were, so the baseline is clean.

---

## 14. Status

- **Nothing committed, nothing pushed.**
- **No `git checkout`, `restore`, `reset`, `stash` or `clean` was used.** The
  before/after comparison in §10 was done by copying the file aside and back,
  never by asking git to discard anything.
- VICE: every instance launched through the harness. One instance was orphaned
  when a foreground test run timed out and its shell ended; it was identified by
  exact PID and command line (`-console`, port 6668 — a test instance, not a
  `-nativemonitor` session) and reaped individually. No `pkill`/`killall` was
  used; no user-launched VICE was touched; no focus was stolen.
