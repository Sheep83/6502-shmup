# Fable Architecture Audit — Where the Multiplexer Capacity Went

**Repositories:** `6502-engine` (reference, built from `6502-engine-main.zip`) and
`6502-shmup` (production, Slices A–D green)
**Date:** 2026-09-13
**Method:** every number below marked *measured* is cycle-exact, taken with the VICE
monitor's CPU stopwatch between breakpoints, as an eight-frame median unless
stated. "Elapsed" figures include interrupts and VIC DMA that landed inside the
span; "pure" figures were taken with the raster interrupt masked at `$d01a`
around a direct call, so only VIC DMA can intrude. No code in either repo was
changed. Everything the old Slice C and D reports got wrong is listed in §9.

---

## 0. The answer in one paragraph

The cycles did not disappear in the migration; they were never there. The
engine's own P5 report measured preparation at **83–88% of a PAL frame with
sixteen ring sprites and no game logic at all**, and wrote: *"Before adding a
player layer, collision, a real HUD or the border opening, the main thread needs
cycles that P5 shows are not currently there."* The migration then measured each
slice against loads that never produced more than a handful of raster batches,
and inherited a "sixteen sprites" figure that only ever meant sixteen *logical*
sprites collapsed into one batch. The capacity limit is **batches, not
sprites**: sixteen sprites in a 4×4 formation (four batches) fit the frame today
with the placeholder scenery still running; the same sixteen spread ten rasters
apart (eleven batches) do not. Each batch costs ~110 cycles in the builder and
~384 in the interrupt, and the builder makes one batch per *distinct* line
because it merges only on exact line equality. That, plus ~4,000 cycles a frame
of placeholder page regeneration that both repos have always paid, is where the
frame goes. The multiplexer is sound and worth keeping. **GO**, with two local
fixes.

---

## 1. Root-cause ranking

| # | Cause | Confidence | Cost on the 16-spread frame | Avoidable? |
|---|---|---|---:|---|
| 1 | **One interrupt per distinct batch line.** The batch pass merges only when `Y−12` is *equal* to the previous batch's line, so 16 well-separated sprites become 11 batches. Each batch is ~110 cycles of builder plus ~384 of interrupt. | HIGH | ~5,500 | Yes — merge by legality window (§7) |
| 2 | **Placeholder page regeneration.** 5 rows × 40 chars of diagnostic pattern on 5 of every 8 frames. Flagged as the dominant term in the P4 report and again in P5. Identical in both repos. | HIGH | ~4,000 on regen frames | Partly — ~1,500–2,500 by scheduling and unrolling; the rest is the cost of drawing 200 characters |
| 3 | **Builder constant factor.** O(N), single pass, no rescans — but ~440 cycles per accepted entry after the first six: eight parallel-array stores, absolute-addressed locals, per-entry slot bookkeeping. | HIGH | ~7,600 pure at 16 | Partly — 20–30% by zero-page locals and precomputed slot tables |
| 4 | **Fixed overhead inside every batch interrupt.** ~300 of the 384 cycles of a one-sprite batch are entry, dispatch, three diagnostic counters, arm-next and exit; only ~77 program the VIC. | HIGH | ~3,000 of the ~4,200 | Partly — ~100/batch by moving diagnostics behind a build flag |
| 5 | **Collision on a volley frame.** Two full 16-slot scans, ~170 cycles per enemy per ray. One frame in eight. | HIGH | ~3,400 pure, ~5,000 elapsed | Partly — one pass for both rays |
| 6 | **VIC DMA theft.** ~25 badlines (~1,050) plus sprite fetches for 24 sprite instances (~1,100). Invisible in code reading; measured as +55% on identical sort work run mid-screen. | HIGH | ~2,150 | No |
| 7 | **Accumulated game mainline.** Input, player, weapon, HUD feed, emit, empty pool walk, spawner, scroller. | HIGH | ~1,220 fixed + ~82/enemy | Marginal |
| 8 | **Measurement and qualification blind spots.** Static fixtures built once; P5 discarded spans near a full frame; Slice C measured a packed column; Slice D read `gameSpanOver` as missed frames. | HIGH | explains the folklore, not the cycles | — |
| 9 | Sort | HIGH it is **not** a cause | 1,130–1,760 | — |
| 10 | Publication and copies | HIGH it is **not** a cause | ~60 | — |
| 11 | Renderer regression from the migration | HIGH there is **none**: the diff is Slice A's player block, ~150 straight-line cycles | ~150 | — |
| 12 | IRQ deadlines or reuse legality | HIGH they are **met**: worst mid-screen handler 401 (one entry) / 646 (six) against 756 | — | — |

Ranked by *avoidable* cost, 1 and 2 together account for the entire gap between
"misses one frame in seven" and "fits with margin".

---

## 2. Cycle-budget reconstruction

### 2a. The production frame, phase by phase (measured, elapsed, 8-frame medians)

Enemies parked at rest, ten rasters apart, ship idle. Entry raster shown so it is
clear which phases run in the vertical blank and which spill into the display.

| Phase | 0 idle | 0 moving | 4 spread | 8 spread | 12 spread | 16 spread | 16 packed |
|---|---:|---:|---:|---:|---:|---:|---:|
| readInput | 19 | 19 | 19 | 19 | 19 | 19 | 19 |
| playerTick | 170 | 168 | 170 | 170 | 170 | 192 | 170 |
| weaponTick | 82 | 82 | 82 | 82 | 82 | 90 | 82 |
| weaponHudFeed | 122 | 122 | 122 | 122 | 122 | 139 | 122 |
| playerEmit | 245 | 245 | 245 | 245 | 245 | 282 | 245 |
| objectUpdateAll | 237 | 237 | 477 | 717 | 957 | 1,526 | 1,197 |
| collisionTick (no shot) | 24 | 24 | 24 | 24 | 24 | 24 | 24 |
| enemySpawnTick | 12 | 12 | 12 | 12 | 12 | 12 | 12 |
| hudDemoTick | — | 85 | 85 | 85 | 85 | 153 | 85 |
| sortTick | — | 37 | 279 | 563 | 847 | 1,760 | 1,131 |
| buildSchedule | — | 323 | 1,427 | 3,765 | 7,316 ⁽¹⁾ | 11,084 ⁽⁵⁾ | 5,358 ⁽¹⁾ |
| publishSchedule | — | 18 | 18 | 18 | 18 | 18 | 18 |
| regenTick (working frame) | 3,941 | 4,059 | 5,180 ⁽¹⁾ | 5,812 ⁽³⁾ | 6,289 ⁽⁶⁾ | 3,313–7,993 | 3,746 |
| scrollTick | 140 | 138 | 124 | 129 | 153 | 132 | 126 |
| **Main thread total** | **5,070** | **5,580** | **8,288** | **11,805** | **16,314** | **> frame** | **12,363** |
| Frame period (median / max) | 19,654 / 19,709 | 19,659 / 19,700 | 19,657 / 19,709 | 19,656 / 19,698 | 19,655 / 19,705 | **22,363 / 25,675** | 19,653 / 19,709 |
| Frames missed | 0 | 0 | 0 | 0 | **0** | **yes, ~14%** | 0 |
| Accepted / batches | 0 / 0 | 0 / 0 | 4 / 1 | 8 / 3 | 12 / 7 | 16 / 11 | **6** / 1 |

Superscripts are the number of batch interrupts that landed *inside* that phase
(each ~384 cycles). Regen on an idle frame is 21 cycles; the working-frame value
is shown because it is the one that decides whether the frame fits.

Three things to read off this table:

- **12 spread does not miss frames.** Its main thread ends at raster ~197, with
  ~3,300 cycles to spare. The Slice D report called this "overrun" because it
  summed `gameSpanOver` (span past raster 193) with `gameOverrun` (a missed
  frame). They are different counters. Corrected in §9.
- **16 packed accepts only six sprites.** The other ten are rejected by the
  reuse rule and never drawn. This is the load Slice C's ladder called "16
  sustained".
- **16 spread misses about one frame in seven**, which is the P5 ring's skip
  rate, re-measured on production with the game attached.

### 2b. What the elapsed figures are made of

The builder's elapsed span decomposes exactly. Pure builder cost with the raster
interrupt masked (measured, direct call, 5-sample medians):

| Layout | Accepted | Batches | Build **pure** | Build elapsed | Interrupts inside | Sort pure | Update pure | Frame period |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 16 packed, 2 apart | 6 | 1 | 3,446 | 5,357 | 1 | 1,254 | 1,320 | 19,648 |
| 16 at spacing 6 (reuse gap 36, the legal minimum region) | 16 | 11 | 7,587 | 13,385 | 11 | 1,125 | 1,191 | **20,548** |
| 16 spread 10 | 16 | 11 | 7,566 | 9,277 | 1 | 1,211 | 1,318 | **21,973** |
| 16 two clusters of 8 | 12 | 7 | 5,929 | 7,974 | 1 | 1,125 | 1,320 | 19,673 |
| **16 formation, 4 rows of 4** | **16** | **4** | 6,743 | 9,944 | 3 | 1,378 | 1,353 | **19,679** |
| 12 spread 10 | 12 | 7 | 5,359 | 7,320 | 1 | 841 | 951 | 19,660 |
| 12 formation, 3 rows of 4 | 12 | 3 | 4,961 | 6,688 | 1 | 999 | 951 | 19,663 |
| 8 spread 10 | 8 | 3 | 3,221 | 3,765 | 0 | 557 | 797 | 19,654 |
| 8 formation, 2 rows of 4 | 8 | 2 | 3,047 | 3,604 | 0 | 618 | 786 | 19,660 |

`elapsed − pure` reproduces `384 × interrupts inside + VIC theft` to within a
few hundred cycles on every row. Spacing 6 and spacing 10 cost the same: the
builder's cost is a function of accepted entries and batch count, not of
geometry.

Fitting the pure column gives the builder's cost model:

```
build ≈ 400  +  300 × min(N, 6)  +  440 × max(N−6, 0)  +  110 × batches  +  120 × rejected
```

It reproduces every row above to within 5%, and the engine's SORTCAP (24
accepted, 4 batches) to within 3%. The builder is **O(N)**. There is no
rescan. The cost is the constant.

### 2c. The interrupt executor (measured, whole handler, 10 samples each)

| Handler | Cycles (min / median / max) | Entry raster | Notes |
|---|---:|---:|---|
| batch, one entry | 333 / **384** / 401 | mid-screen | ~77 cycles program the VIC; the rest is entry, dispatch, three diagnostic counters, arm-next, exit |
| batch, six entries (P2) | — / 646 / 731 | mid-screen | the qualified critical path; deadline 756 |
| handoff (batch 0, six entries + handoff work) | 733 / **779** / 785 | 40 | in the border; no display deadline |
| HUD | 539 / 539 / 539 | 4 | programs HW2–HW7 for the border HUD |
| bottom split | 406 / 413 / 414 | 243 | includes the poll from 243 to 248 |
| frame transaction | 347 / 349 / 400 | 250 | |
| top split | 238 / 239 / 282 | 53 | includes the poll to 55 |

Structural phases total **1,540** every frame. Batches add **384 per
mid-screen batch**. At 16 spread: 10 × 384 + 779 + 1,540 = **6,159 cycles, 31%
of the frame, in interrupts.** At 16 formation (4 batches): ~4,100.

### 2d. Where the 19,656 go on the worst realistic 16-spread frame

A regen frame with a volley. Builder and interrupt figures from 2b/2c, the rest
from 2a.

| Item | Cycles | Share |
|---|---:|---:|
| VIC DMA theft (badlines + 24 sprite instances) | ~2,150 | 11% |
| Interrupt executor (11 batches + 5 structural) | ~6,160 | 31% |
| Fixed game mainline (input, player, weapon, feed, emit, spawner, scroll, spin) | ~1,220 | 6% |
| Enemy update × 16 | ~1,320 | 7% |
| Sort | ~1,130 | 6% |
| Builder, pure, 16 accepted / 11 batches | ~7,570 | 39% |
| Publish, HUD demo, misc | ~200 | 1% |
| Placeholder regen (5 of 8 frames) | ~4,000 | 20% |
| Collision (1 of 8 frames, volley) | ~3,400 | 17% |
| **Total, worst frame** | **~27,150** | **138%** |
| **Total, plain frame (no regen, no volley)** | **~19,750** | **100%** |

A plain 16-spread frame is already at the budget; any regen frame or volley
frame misses. This is what the 22,363-cycle median period is.

For comparison, the **engine** on the same ring geometry (RING-SLOW, 16 moving,
11 batches, measured here the same way): hudDemoTick 187, motion 1,440, sort
1,405, build 12,219 (8.5 interrupts inside), publish 24, regen 23–3,665, scroll
107 — **total 15,945, frame period 19,738** — slipping, exactly as P5 said. The
production delta is ~1,100 cycles of game mainline on a plain frame and ~3,400
more on a volley frame. The engine was at 81%; the game pushed it past 100%.

---

## 3. Qualification reconciliation

Why did the engine "survive" its stress architecture while production overruns?
Because the engine's qualification measured four different things, and only one
of them was the per-frame builder under a many-batch load — and that one
reported the problem.

**P0–P2 and MAXCAP: static fixtures built once.** Measured here on the engine:
`MAXCAP` has 30 logical sprites, 24 accepted and **19 batches**, and its
per-frame main thread is **3,478 cycles** — regen and scroll only. The builder
runs at fixture load and never again. Nineteen batch interrupts a frame (~8,800
cycles, 45%) were proven *safe*; a builder producing nineteen batches every frame
was never run. The ladder document says so: *"P3's 30-sprite MAXCAP was static
and built once."*

**P3/P4: moving, but few batches.** CROSS6 is 12 sprites at 70.5%; SORTCAP is
26 sprites in **four** batches at 85.4%, named "the ceiling". Measured here:
SORTCAP's frame period is 21,392 — it misses frames. P4 wrote *"regenTick
dominates, not the sorter"* and gave regen as 8,701 on its worst frame.

**P5: the ring, eleven batches, and the warning.** 83–88% of the frame,
13–15% publication skips, and the sentence quoted in §0. This is the only
qualification measurement of a per-frame builder at eleven batches, and it
failed criterion 11. It was recorded as "judder" and deferred.

**P5's spans understate build.** Its method derived cycles from raster position
modulo one frame and *discarded any span within 2,000 cycles of a full frame as
implausible* — which removes the longest builds from the median. The stopwatch
median for the same fixture is 12,219 against P5's 9,047. Both are honest; the
stopwatch one is the worst-phase figure a frame budget needs.

**The migration then measured against the wrong loads.** Slice C's ladder spawned
one enemy per frame into a descending column two rasters apart — a load the
reuse rule collapses into one batch and six accepted sprites — and reported 202
raster lines at "16". Slice D spread them ten apart, saw the frame saturate, and
called eight the ceiling.

So: the qualification did not overstate capacity. It stated, three times in
writing, that there was no headroom for a game at sixteen spread sprites. What
overstated capacity was a number — "sixteen" — detached from the batch count it
was measured at.

---

## 4. Practical capacity, current architecture

CPU capacity and reuse legality are separated because they bind differently:
the reuse rule rejects tightly packed sprites (six of sixteen in a 2-raster
column) regardless of CPU, and CPU rejects widely spread ones regardless of
legality.

| Scenario | Objects | Accepted | Batches | Fits today (regen on)? | Binding limit |
|---|---:|---:|---:|---|---|
| Packed column, 2 apart | 16 | 6 | 1 | yes, easily | **reuse legality** — ten never drawn |
| 4×4 formation, rows 40 apart | 16 | 16 | 4 | **yes**, at the edge (19,679 / 19,748) | CPU, barely |
| Two clusters of 8 | 16 | 12 | 7 | yes (19,673) | reuse legality within each cluster |
| Widely distributed, 10 apart | 16 | 16 | 11 | **no** — ~14% frames missed | CPU: batch count |
| Widely distributed, 10 apart | 12 | 12 | 7 | yes (19,655), ~3,300 spare | CPU on volley+regen coincidence frames |
| Widely distributed, 10 apart | 8 | 8 | 3 | yes, ~7,800 spare | — |
| Upgrade + 3 escorts + ordinary traffic (~10, mixed) | ~10 | ~10 | ~5–6 | yes | — |
| Upgrade + 5 escorts + ordinary traffic (~12, mixed) | ~12 | ~12 | ~6–7 | yes, at the edge | CPU |

With the placeholder regen switched off at run time (measured, no other change):
12 spread finishes at raster ~107 with ~9,000 cycles spare; 16 spread fits with
no missed frames and no publication skips **as long as nothing fires** — a
volley frame at 16 still misses. So regen alone buys roughly four spread
sprites; it does not make 16 spread a target.

**The honest present-day figure:** ~12 objects in any realistic mixed formation,
16 if they arrive in rows, and about 7 batches a frame as the real ceiling.
"Eight" was never the limit; "sixteen anywhere" was never the capacity.

---

## 5. Sort audit

Production changed membership to an explicit `logActive` bit with a rebuild only
on spawn or despawn (Slice C); movement never triggers a rebuild; one persistent
insertion pass per frame. Measured pure cost: 557 at 8, 841 at 12, 1,125–1,378 at
16 static; 1,405 for the moving ring. About 70 cycles per entry at rest. The
membership rebuild is two bounded passes over 32 entries on the frame something
spawns or dies. **Not a cause**, in either repo, and P4 said the same.

---

## 6. Publication and copy audit

| Per-frame copy or clear | Bytes | Cycles | Verdict |
|---|---:|---:|---|
| player presentation → `schedPly*` in NEXT | 10 | ~80 | required: it is the immutable copy |
| builder writes into NEXT (8 arrays per accepted entry) | 8 × N | inside the 440/entry | required: it **is** the schedule; this is where safety costs, and it is a store per field, not a copy |
| frame record (fine scroll, page, pointer destination) | ~4 | ~40 | required |
| pointer-store operand patch in `exFrame` | 4 | ~30 | required; cheaper than a table copy |
| `publishSchedule` | 1 | 18 | required; this is the atomicity |
| stat counter reset at build entry | 8 | ~40 | conservative, negligible |
| table clears | 0 | 0 | none exist |

Safety is not being bought with copies. There is nothing here to remove.

---

## 7. Improvement options, ranked

| # | Option | Benefit at 16 spread | Risk | Complexity | Cleanliness |
|---|---|---:|---|---|---|
| **1** | **Merge batches by legality window, not exact line.** An entry with predecessor `p` may be programmed on any line in `[Y_p + 21, Y_i − 12]`; with the 33-gap minimum that window is one line, with a 60-gap it is 27 lines. Greedy: open a batch at the first entry's latest line, absorb following entries whose window contains it, cap at six (one per slot, which the 756-cycle deadline already covers). Spread-10 collapses from 11 batches to ~4. Executor untouched; CURRENT/NEXT untouched. | **~3,500** (7 fewer batches × ~500) | medium: P2/P4 models assert exact `Y−12` lines and must be updated with the new rule; needs the same acceptance-vs-model tests | low–medium: one loop in the batch pass | clean — a builder policy, exactly where the reuse rule already lives |
| **2** | **Regen scheduling.** Spread 25 rows over 8 frames (3–4 per frame) instead of 5 over 5; unroll the row fill. Design the real map renderer around it in the graphics slice. | ~1,500–2,500 on regen frames | low | low | clean |
| **3** | **Builder constant factor.** Zero-page locals (~60/entry); precompute `schedSlot`/`schedSlot2` by accepted index instead of per-entry slot cycling (~40/entry); fold the `$d010` bit-table lookups. | ~1,500 | low | low | clean |
| **4** | **Interrupt fixed overhead.** Put `batchCounter` (24-bit), `batchSizeHist` and `lateRun` bookkeeping behind a diagnostics build flag; precompute the next arm line into the batch record. | ~1,000 at 11 batches, ~400 after option 1 | low | low | clean; the counters still exist in diagnostic builds |
| 5 | **Single-pass collision.** Load each slot once and test both rays. | ~1,300 on volley frames | low | low | clean |
| 6 | **Skip the empty-slot walk.** `objectUpdateAll` and `collisionTick` walk 16 slots even when the pool is empty (237 / 631). Keep a live-slot list or a high-water mark. | ~200–600 | low | low | clean |
| 7 | Move `hudDemoTick` and the spawner tick to every other frame | ~100 | trivial | trivial | fine, but it is noise |
| — | Larger `MAX_BATCH`/adaptive slots/rewrite | — | — | — | **not recommended**; nothing measured points there |

Options 1–4 together recover roughly 7,000–8,000 cycles on the 16-spread frame,
which turns a 138% worst frame into ~100% and a 100% plain frame into ~65%. That
is 14–16 mixed-formation objects with shooting, and it leaves 16 uniformly spread
with a volley on a regen frame as the pathological corner it should be treated
as — a wave-design constraint (aim for ≤ 7 batches a frame) rather than a
target.

---

## 8. Recommended next experiment

Before changing the builder, prove the dominant hypothesis with the layout
table already in hand: **batch count, not sprite count, is the cost.**

It is already proven by measurement: 16 sprites in four batches fit; 16 in
eleven do not; spacing 6 and spacing 10 cost the same. The next experiment is
the implementation test for option 1:

1. Prototype window-merging in `bs_bLoop` on a branch.
2. Re-run `/tmp/layouts.py` (the script that produced §2b) unchanged.
3. Pass criteria: 16 spread 10 → ≤ 5 batches; build pure ≤ 6,900; frame period
   median < 19,656 with max < 19,700; P2's six-entry critical path unchanged at
   646; every existing `make test` probe green after its batch-geometry model is
   updated to the new rule.
4. Fail criterion: any mid-screen handler over 756 cycles, or any P0–P5 visual
   fixture showing a stale slot — which the reuse-gap arithmetic says cannot
   happen, and which is exactly why it must be tested rather than argued.

That is one routine, one script, and an afternoon. Everything else in §7 is
independent of it and can follow.

---

## 9. Corrections to my own earlier reports

- **Slice C, "the engine sustains 16":** the ladder's column was two rasters
  apart; only six of sixteen were ever accepted. It measured the pool, not the
  mux, as its own report half-admitted.
- **Slice D, "eight is the practical ceiling":** `gameSpanOver` counts spans past
  raster 193, not missed frames. 12 spread misses none. The ceiling under the
  current code is ~12 spread or 16 in rows.
- **Slice D, "collision costs 4 to 15 raster lines":** that delta was a
  saturated maximum. Pure collision on a volley frame is 2,090 / 2,731 / 3,400
  cycles at 8 / 12 / 16 enemies, ~5,000 elapsed mid-screen.
- **Today's prediction that the HUD gauge would starve at 12 spread:** tested and
  false — lag ≤ 1 pixel at 12 and 16, because `hudUpdate` runs at the top of
  every loop iteration including the one after `gameFrame` returns.

---

## 10. GO / NO-GO

**GO.**

The architecture is doing what it was built to do: the executor is byte-exact
and inside its deadlines at 19 batches, publication is one byte, CURRENT is never
touched, the sorter is cheap, and the builder is linear. What it lacks is not a
design but two constants: it opens an interrupt for every distinct line because
it never asked whether adjacent lines could share one, and it has always paid
~4,000 cycles a frame for scenery nobody will ship. Both are local, both are
measurable with scripts that already exist, and the first one alone turns the
failing case into a passing one. The alternative — an adaptive allocator or a
rewrite — would be solving a problem the measurements do not show.

The standard was meaningful gameplay capacity relative to accepted complexity.
Sixteen objects in formation fit today; twelve fit in any arrangement; with
window merging and the regen redesign that the graphics slice needs anyway,
fourteen to sixteen in realistic mixed traffic, with shooting, is a sound
expectation. That is a multiplexer worth its complexity.

---

## Appendix A — measurement discipline

- Stopwatch, not raster arithmetic: no modulo wrap, no plausibility filtering.
- Eight-frame medians per phase, each sample verified to lie within one frame by
  the frame counter; single-frame samples had caught regen on an idle frame
  (21) and a working one (3,941) and called both "regen".
- Pure builder cost taken with `$d01a` masked around a direct call; the elapsed
  minus pure difference reproduces `384 × interrupts + VIC theft` on every row,
  which is the check that the two methods agree.
- The ship is re-armed before every sample: a warp free-run between samples parks
  it at its bound and silently ends the "moving" rebuild.
- Every emulator launched by these scripts was reaped by PID; one orphan from a
  killed script was found and reaped by its exact PID; the user's `vicerc` was
  not touched (`-default +saveres`, per-process input flags only).

## Appendix B — scripts

All under `/tmp`, none in either repo: `irq_cost.py` (§2c), `phase_table2.py`
(§2a), `engine_phase2.py` (engine rows), `layouts.py` (§2b), `regen_off.py`
(§4), `hud_coll.py` (collision and HUD). The engine was built from the zip into
the session scratchpad and not modified.
