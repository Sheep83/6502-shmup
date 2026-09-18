# 2 px/frame scroll-speed trial

**Date:** 2026-09-17
**HEAD worked from:** `722dbbd` — *HUD bank switching, token progress* (working tree carried only two untracked reports from earlier tasks)
**Files changed:** `src/main.asm`, `src/scroll.asm`, `src/turrets.asm` — 3 files, +101 / −32
**Nothing committed. Nothing pushed.**

---

## Verdict up front

The scroll change itself is **correct and proven exact**: the world now advances
2 px on every displayed PAL frame, one coarse row every 4 frames, with
`worldProgress` moving exactly once per crossing and every authored world
position landing where it was authored.

**But the build is not currently fit for a fair feel judgement.** At 2 px/frame
the main thread misses frames continuously — `gameOverrun`, `publishSkip` and
`schedBuildDefer` all saturate at 255 over 10 s of ordinary play, against a
baseline where `gameOverrun` and `schedBuildDefer` were **zero**. The cause is
structural, not a bug in the change: **every per-coarse-row cost in the engine
doubles when coarse rows arrive twice as fast**, and the largest of those is
rebuilding the entire 25-row back page.

VICE is up for you to look at anyway (PID **99760**, PAL, non-warp, no warp
acceleration), because you are the authority on feel — but read §7 first so you
know which artefacts are the speed and which are the engine running out of time.

---

## 1. Exact previous scroll semantics

| | value |
|---|---|
| fine step | `inc scrollFine` — **1 px per displayed frame** |
| fine phases visited | 0,1,2,3,4,5,6,7 (all eight) |
| coarse step | when `scrollFine` reaches 8 → reset to 0, `stageTopRow` −1, `worldProgress` +1, page flip |
| frames per coarse row | **8** |
| back-page regeneration | `ROWS_PER_TICK = 4`, 25 rows in `ceil(25/4) = 7` of the 8 frames |
| idle frame | the 8th, on which `scrollFine == 7` |
| turret geometry prepared on | `TURRET_PREPARE_FINE = 7` (literal) |
| full stage (395 coarse rows) | 3,160 frames ≈ **63 s** |

## 2. Exact new scroll semantics

| | value |
|---|---|
| fine step | `lda scrollFine / clc / adc #SCROLL_PX_PER_FRAME / sta scrollFine` — **2 px per displayed frame** |
| fine phases visited | **0,2,4,6 only** |
| coarse step | unchanged trigger (`cmp #8 / bcs`); reached exactly, never overshot |
| frames per coarse row | **4** |
| back-page regeneration | `ROWS_PER_TICK = 9` (derived), 25 rows in 3 of the 4 frames |
| idle frame | the 4th, on which `scrollFine == 6` |
| turret geometry prepared on | `TURRET_PREPARE_FINE = 8 - SCROLL_PX_PER_FRAME` = **6** (derived) |
| full stage (395 coarse rows) | 1,580 frames ≈ **31.6 s** |

**Verified in the assembled binary**, not merely in source:

```
scrollTick   ad 40 c5 18 69 02 8d 40 c5 c9 08 b0 03   lda scrollFine; clc; adc #2; sta; cmp #8; bcs
regenTick    a0 09                                     ldy #9          (ROWS_PER_TICK)
$6fe6        ad 40 c5 c9 06                            lda scrollFine; cmp #6  (TURRET_PREPARE_FINE)
```

### The configuration point

Added to `src/main.asm`, above the imports (three modules derive from it and
KickAssembler resolves constants in import order):

```asm
.const SCROLL_PX_PER_FRAME = 2
.const SCROLL_FRAMES_PER_COARSE_STEP = 8 / SCROLL_PX_PER_FRAME
```

Named for what it is — **pixels per frame**. The old editor's
`SCROLL_FRAME_DIVIDER` was deliberately **not** revived: a divider expresses
"one pixel every N frames", which is the opposite direction, and nothing in this
repository reads it. Guarded so it must divide 8 exactly, because the fine
scroll counts up and the coarse step fires when it *reaches* 8 — a speed that
does not divide 8 would overshoot onto a YSCROLL the previous frame never
displayed and leave a permanent sub-pixel residue.

Setting `SCROLL_PX_PER_FRAME = 1` restores the original engine exactly: the
derived `ROWS_PER_TICK` formula yields 4 and `TURRET_PREPARE_FINE` yields 7,
which are the literals that were there before.

---

## 3. The 1-px/frame assumptions found, and how each was handled

| # | assumption | where | consequence at 2 px | handling |
|---|---|---|---|---|
| 1 | **`TURRET_PREPARE_FINE = 7`** — a literal fine phase | `src/turrets.asm:432` | **The fine scroll never takes the value 7.** The comparison would never match, turret page geometry would never be derived, and every coarse step would adopt a shadow that was never built. Silent — no counter would have caught it. | Derived: `8 - SCROLL_PX_PER_FRAME` (= 6). Two new guards: that it equals that expression, and that it is a phase the scroll actually lands on (`mod(TURRET_PREPARE_FINE, SCROLL_PX_PER_FRAME) == 0`) |
| 2 | **`ROWS_PER_TICK = 4`** sized against "7 of 8 frames" | `src/scroll.asm:105` | Only 4 frames per cycle. 25 rows at 4/frame needs 7 → the page would be displayed unfinished, `scrollLate` firing every coarse step | Derived: `ceil(SCREEN_ROWS / (SCROLL_FRAMES_PER_COARSE_STEP - 1))` = 9. Reproduces 4 exactly at 1 px/frame |
| 3 | **The idle-frame guard** compared against a literal 8 | `src/scroll.asm:122` | Would no longer describe the cycle | Compares against `SCROLL_FRAMES_PER_COARSE_STEP` |
| 4 | Coarse-step comment: "7 → 0 moves the content up seven pixels" | `src/scroll.asm:385` | Wrong at any other speed | Restated in terms of `SCROLL_PX_PER_FRAME` |
| 5 | `logY = 47 + scrollFine + 8·matrixRow` | `src/turrets.asm:869` | **None.** Fully derived from scroll state; turrets stay terrain-locked at any speed. Bound still 246 | No change |
| 6 | `$d011` built as `D011_BASE ORA scrollFine` | `src/scroll.asm:529` | **None.** `scrollFine` ≤ 6 < 8 | No change |
| 7 | `finePhase` indexed `scrollFine × 2`, 16 bytes | `src/scroll.asm:493` | **None.** Max index 12. Only phases 0,2,4,6 accumulate — by design | No change |
| 8 | Debug row prints `scrollFine + '0'` | `src/main.asm:1113` | **None.** Single digit | No change |
| 9 | **P-token descent** `PICKUP_VY = 1` on alternate frames | `src/pickup.asm:64,70` | Token now falls at **¼** the scroll rate instead of ½ | **Deliberately left alone** — see below |

### On the P-token (a judgement call worth flagging)

`src/pickup.asm` carries two comments that disagree. The older one at line 56
says one pixel a frame is correct "BECAUSE THAT IS THE SCROLL". The newer one at
line 414 supersedes it: *"The token no longer matches the scroll, and that is
now correct — it should read as an object hanging in the encounter rather than
as part of the ground,"* and *"THIS IS NOT FINAL BALANCE."*

So the token's descent is a **deliberate absolute rate**, not a scroll
derivation — and the brief lists P-token behaviour under "do not alter". I left
it untouched. The visible consequence is that the token now drifts upward
relative to the terrain about twice as fast as before. That is a balance
question for you, not a correctness one, and it is a one-constant change if you
want it tracked to the new speed.

---

## 4. Effect on coarse-row / world-progress cadence

Nothing was compensated. World space means exactly what it meant:

| | 1 px/frame | 2 px/frame |
|---|---|---|
| frames per coarse row | 8 | **4** |
| `worldProgress` per coarse row | +1 | +1 (unchanged) |
| `stageTopRow` per coarse row | −1 | −1 (unchanged) |
| invariant `stageTopRow == (START − worldProgress) mod STAGE_ROWS` | holds | **holds** |
| first wave trigger | world row 48 | world row 48 (**same place**, reached in half the time) |
| turret at authored row R | on page when `T−1 ≤ R ≤ T+24` | identical rule, identical rows |
| stage end | `worldProgress == 395` | `worldProgress == 395` |
| wall-clock to the boss | ~63 s | **~31.6 s** |

---

## 5. Build and test results

**Build:** clean. Every assembly-time guard passes, including the three new ones.

### Baseline captured at HEAD *before* any edit (same harness, same method)

| target | result |
|---|---|
| `test-production` | 3 failures: `publishSkip` = 11; plus two **player**-movement sampling failures (`moved 4 px in 5 frames`) |
| `test-turret-regression` | ALL PASS |
| `test-boss` | ALL PASS |
| `test-pickup` | **crashes at HEAD** — `KeyError: 'waveTrigTokenLo'`, a symbol the engine removed when the token trigger column was deleted. Pre-existing, unrelated, out of scope |

`gameOverrun` and `schedBuildDefer` were **green at baseline**.

### After the change

| target | result |
|---|---|
| `test-boss` | **ALL PASS** — stage completion still occurs at the derived world position, the scroller still freezes on the last complete authored screen with `stageTopRow` at zero and no wrap |
| `test-turret-regression` | **ALL PASS** |
| `test-production` | `gameOverrun` **255**, `publishSkip` **255**, `schedBuildDefer` **255**, `scrollLate` **0** |

The two player-movement failures appeared in one run and not another, confirming
they are nondeterministic sampling artefacts rather than anything this change
touched.

---

## 6. Automated probe results

A focused probe (disposable scratch, not added to the repo) stepped real frames
under natural non-pinned scrolling:

```
ok   a long contiguous run of real frames was captured -- 49 of 120 samples
ok   fine scroll advances by exactly 2 px on every displayed frame -- 0 bad transitions
ok   the fine scroll visits exactly the phases [0, 2, 4, 6] -- saw [0, 2, 4, 6]
ok   one coarse row is traversed every 4 displayed frames -- gaps=[4] over 12 steps
ok   worldProgress advances exactly once per coarse-row crossing, never otherwise
ok   no coarse row is skipped or counted twice (coarseCount moves 1:1)
ok   stageTopRow steps back exactly once per crossing
ok   the scroller invariant holds: stageTopRow == (START - worldProgress) mod STAGE_ROWS
ok   the displayed page's stamp equals stageTopRow on every frame
ok   the back page is FINISHED by the idle frame (fine == 6)
ok   turrets are on the page at exactly their authored world rows
ok   scrollLate is zero under 2 px/frame scrolling -- 0
```

That covers brief items 1–6 directly. Item 7 (stage completion) is covered by
`test-boss`, which proves the boundary from authored geometry and passes. Item 8
is §5 above.

Wave-trigger spatiality follows transitively and was not separately asserted:
triggers fire on 16-bit `worldProgress` comparisons, and `worldProgress` is
proven to advance exactly once per coarse row with the scroller invariant intact,
so a trigger authored at a world row still fires at that world row. Two probe
assertions that tried to *drive* this by poking `worldProgress` returned no
result and are reported as inconclusive rather than as passes — the engine's
degraded frame timing (§7) makes poke-and-step probes unreliable, and
`test-boss` proves the same class of fact properly.

---

## 7. The architectural concern — and it is the headline

**2 px/frame doubles every per-coarse-row cost in the engine.** Coarse rows
arrive twice as fast, and three things are keyed to coarse rows:

1. **back-page regeneration** — the whole 25-row page, every coarse step;
2. **the coarse step itself** — 16-bit row arithmetic, `rowBack` twice, page flip, stamp;
3. **turret page-geometry preparation** — 8 turrets, once per coarse step.

Regeneration dominates. Measured against the file's own ~1,158 cycles per row:

| | rows/frame across the cycle | peak | **average** |
|---|---|---|---|
| 1 px/frame, `ROWS_PER_TICK = 4` | 4,4,4,4,4,4,1,0 | 4,632 cy | **3,619 cy — 18 % of the frame** |
| 2 px/frame, `ROWS_PER_TICK = 9` | 9,9,7,0 | 10,422 cy | **7,238 cy — 37 % of the frame** |
| 2 px/frame, `ROWS_PER_TICK = 7` | 7,7,7,4 | 8,106 cy | **7,238 cy — 37 % of the frame** |

### Three controlled runs isolate the cause

| configuration | `gameOverrun` | `scrollLate` | reading |
|---|---|---|---|
| 1 px, 4 rows (**baseline**) | **0** | 0 | healthy |
| 2 px, 9 rows (peak 10,422) | 255 | 0 | page finishes in time; frame budget blown |
| 2 px, 7 rows (peak 8,106 — the floor) | 255 | 0 | **identical** — lowering the peak changes nothing |
| 2 px, 4 rows (regen deliberately starved) | 193 | 255 | still overrunning even at baseline regen rate |

Two conclusions, both measured rather than argued:

- **It is the average, not the peak.** Halving the frames available to rebuild a
  page does not halve the work — it doubles the rate. `ROWS_PER_TICK` only
  redistributes it, which is why 9 and 7 behave identically.
- **Regeneration is the largest contributor but not the only one.** Starving it
  back to the baseline rate still leaves `gameOverrun` at 193, because the coarse
  step and the turret preparation also now run twice as often.

`scrollLate` staying at **0** in the shipped configuration is the useful part:
the scroller is meeting its own contract — the back page really is finished
before every coarse step, and the derived `ROWS_PER_TICK` is doing its job. The
engine simply does not have ~3,600 spare cycles per frame to give it. That in
turn says the main thread was already running near its ceiling at 1 px/frame.

**Making 2 px/frame affordable requires a scroller change, which this task was
scoped out of** — the obvious direction is to stop rebuilding all 25 rows when
only one row of content is new, but the current design regenerates precisely so
that "a stale row, a duplicated row or a one-row jump cannot survive", and
trading that away is a decision, not a tweak. I have not touched it.

---

## 8. Manual VICE status

Launched for your judgement, **not** by the automated harness:

- **PID 99760**, `x64sc`, PAL, visible window, `-saveres`, joystick as configured.
- **No warp, no acceleration** — the brief's requirement, and the only way
  scroll/render defects show honestly.
- Owned by this task. Close it yourself, or say the word and I will terminate
  that exact PID. No `pkill`/`killall` was used at any point; every automated
  VICE launched during this task was reaped by exact PID (97944, 99437, plus the
  harness's own in each `make test-*` run) and `pgrep -fl x64sc` confirmed a
  clean field before each run.

### What to look for, and what to discount

**Judge the speed:** terrain smoothness between coarse steps, whether turrets
are on screen long enough to be worth engaging, how enemies read against faster
ground (their own speeds are unchanged and deliberately so, so they will feel
slower relative to the terrain), wave pacing, and whether the ship stays
readable.

**Discount as engine-overrun, not scroll speed:** stutter, held frames, sprite
flicker or schedule artefacts. Those are `gameOverrun`/`publishSkip` saturating,
and they would disappear if the regeneration cost were addressed. If 2 px/frame
*feels* right underneath them, that is the answer worth having — the cost
problem is solvable separately.

---

## 9. Status and hygiene

```
$ git status --porcelain
 M src/main.asm
 M src/scroll.asm
 M src/turrets.asm
?? reports/level-editor-current-engine-contract-review.md
?? reports/wave-movement-architecture-and-editor-contract.md

$ git diff --stat
 src/main.asm    | 34 ++++++++++++++++++++++++++
 src/scroll.asm  | 74 +++++++++++++++++++++++++++++++++++++-------------
 src/turrets.asm | 25 +++++++++++++------
 3 files changed, 101 insertions(+), 32 deletions(-)

$ du -sh build/    96K
$ du -sh .         7.8M
```

`build/` holds only the current binary and symbols — no per-run directories. The
probe and the isolation-experiment backup live in the session scratchpad outside
the repository, not in `tests/`; the backup has been deleted. The two untracked
reports are from earlier tasks in this session.

**Nothing was committed. Nothing was pushed.** No test was weakened, no terrain,
wave, enemy, turret, player, boss, token, HUD or editor behaviour was altered,
and the scrolling architecture was not redesigned.
