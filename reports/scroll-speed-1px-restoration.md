# Scroll speed: restoration to 1 px/frame

**Date:** 2026-09-17
**HEAD:** `722dbbd` — *HUD bank switching, token progress* (unchanged; the checkout is still based on the same production HEAD the experiment used)
**Outcome:** the 2 px/frame trial is fully reverted. `src/main.asm`, `src/scroll.asm` and `src/turrets.asm` have **no diff relative to HEAD**.
**Nothing committed. Nothing pushed. No destructive reset.**

**1 px/frame is the production scroll speed.**

---

## 1. Proof the rollback is exact

The restored working tree was built and compared against a build from a
pristine `git archive HEAD` extraction in disposable scratch:

```
pristine HEAD build : 51,164 bytes  sha256 cbaeb0f41a005fb1bc8c20ef34764f25d923f72da5da7c10fdc5c6ab779803f7
restored tree build : 51,164 bytes  sha256 cbaeb0f41a005fb1bc8c20ef34764f25d923f72da5da7c10fdc5c6ab779803f7
```

**Byte-identical.** The engine is not merely equivalent to the pre-experiment
build — it *is* the pre-experiment build. That also settles every
"regression or pre-existing?" question by construction: any difference between
test runs now and before is run-to-run variation, because the binary is the same
binary.

---

## 2. Pre-rollback diff classification

Before touching anything, the working-tree diff was read hunk by hunk and
classified against the trial report's own inventory. `git log` confirmed HEAD was
still `722dbbd`, and `git diff --stat` matched the trial report exactly
(+101 / −32 across the same three files), so nothing had been edited in between.

| file | hunks | content | verdict |
|---|---|---|---|
| `src/main.asm` | 1 | Wholly additive: the `SCROLL_PX_PER_FRAME` comment block, the constant, its two range/divisibility guards, and `SCROLL_FRAMES_PER_COARSE_STEP` | **100 % experiment** |
| `src/scroll.asm` | 4 | (a) `ROWS_PER_TICK` literal `4` → `ceil(...)` plus rewritten comment; (b) idle-frame guard generalised + a new `mod()` guard + rewritten comment; (c) `inc scrollFine` → `lda/clc/adc #SCROLL_PX_PER_FRAME/sta`; (d) coarse-step wrap comment rewritten | **100 % experiment** |
| `src/turrets.asm` | 1 | `TURRET_PREPARE_FINE` literal `7` → `8 - SCROLL_PX_PER_FRAME`, plus rewritten comment | **100 % experiment** |

**No pre-existing modifications, and no user edits, existed in any of the three
files.** Every changed line was written by the trial task in this session. Only
once that was established was a targeted `git checkout -- <the three paths>`
used — never a repository-wide reset, never `git clean`, and nothing that could
touch the untracked reports.

The experiment was preserved first, to scratch outside the repository:
a full `git diff` patch (`2px-experiment.patch`, 10,732 bytes) and copies of all
three files, so the trial is recoverable without being in the tree.

---

## 3. Exactly what was removed

| removed | was |
|---|---|
| `.const SCROLL_PX_PER_FRAME = 2` | new constant + 20 lines of rationale |
| `.if (SCROLL_PX_PER_FRAME < 1 \|\| > 8)` guard | new |
| `.if (mod(8, SCROLL_PX_PER_FRAME) != 0)` guard | new |
| `.const SCROLL_FRAMES_PER_COARSE_STEP = 8 / SCROLL_PX_PER_FRAME` | new |
| `.const ROWS_PER_TICK = ceil(SCREEN_ROWS / (SCROLL_FRAMES_PER_COARSE_STEP - 1))` | → back to literal `.const ROWS_PER_TICK = 4` |
| `.const TURRET_PREPARE_FINE = 8 - SCROLL_PX_PER_FRAME` | → back to literal `.const TURRET_PREPARE_FINE = 7` |
| idle-frame guard vs `SCROLL_FRAMES_PER_COARSE_STEP` | → back to literal `>= 8` |
| `.if (mod(TURRET_PREPARE_FINE, SCROLL_PX_PER_FRAME) != 0)` guard | removed entirely |
| `lda scrollFine / clc / adc #SCROLL_PX_PER_FRAME / sta scrollFine` | → back to `inc scrollFine` |
| generalised comments in all three files | → back to the original 1 px/8 frame prose |

No generalisation machinery was left behind. The pre-experiment engine used
simple literals and that is what is in the tree — the constant was **not** merely
flipped from 2 to 1.

### Verified in the assembled binary, by address range

```
$4403  lda scrollFine ; cmp #8     scrollTick coarse-step compare (scroller $4340-$45a3)
$43ff  inc scrollFine              the 1 px fine step  <-- ADC form gone
$6fe6  lda scrollFine ; cmp #7     TURRET_PREPARE_FINE (turret code $6f00-$740c)
regenTick  ldy #4                  ROWS_PER_TICK
```

The only `lda scrollFine / clc / adc` left in the whole image is at **$521d**,
inside `main` ($5000–$52c5) — `adc #$30`, the pre-existing debug row that prints
the fine phase as a digit. It is not the scroll step and is untouched by HEAD.

---

## 4. Restored scroll semantics

| | restored value |
|---|---|
| fine step | `inc scrollFine` — **1 px per displayed PAL frame** |
| fine phases | **0,1,2,3,4,5,6,7** (all eight) |
| frames per coarse row | **8** |
| `worldProgress` | +1 per coarse crossing; `stageTopRow` −1 |
| invariant | `stageTopRow == (STAGE_START_ROW − worldProgress) mod STAGE_ROWS` |
| back-page regeneration | `ROWS_PER_TICK = 4`, 25 rows across 7 of the 8 frames, one frame of margin, peak ~4,630 cycles (18 % of the frame) |
| idle frame | the 8th, `scrollFine == 7` |
| turret preparation | `TURRET_PREPARE_FINE = 7` |
| full stage (395 coarse rows) | 3,160 frames ≈ **63 s** |

---

## 5. Probe results (1 px/frame)

Re-parameterised from the trial probe and run in disposable scratch, stepping
real frames under natural non-pinned scrolling:

```
ok   a long contiguous run of real frames was captured -- 200 of 200 samples
ok   fine scroll advances by exactly 1 px on every displayed frame -- 0 bad transitions
ok   the fine scroll visits exactly the phases [0, 1, 2, 3, 4, 5, 6, 7]
ok   one coarse row is traversed every 8 displayed frames -- gaps=[8] over 24 steps
ok   worldProgress advances exactly once per coarse-row crossing, never otherwise
ok   no coarse row is skipped or counted twice (coarseCount moves 1:1)
ok   stageTopRow steps back exactly once per crossing
ok   the scroller invariant holds: stageTopRow == (START - worldProgress) mod STAGE_ROWS
ok   the displayed page's stamp equals stageTopRow on every frame
ok   the back page is FINISHED by the idle frame (fine == 7)
ok   turrets are on the page at exactly their authored world rows
ok   scrollLate is zero under 1 px/frame scrolling -- 0
ok   gameOverrun is zero under 1 px/frame scrolling -- 0
```

That is brief items **1–8 and 11** directly. The sample contiguity is itself
evidence: **200 of 200** frames were captured consecutively, against **49 of 120**
under 2 px/frame — the machine keeps up with breakpoint stepping again.

### A correction to the trial report

The trial report said two probe assertions (first wave trigger, stage
completion) were inconclusive because degraded frame timing made poke-and-step
unreliable. **That attribution was wrong.** They fail at 1 px/frame too, on a
healthy engine, and the real cause is now known: `tests/harness.py` boots every
Vice with **`stageHold = 1`** — `src/scroll.asm`'s endless-stage diagnostic —
and `test_boss.py` is the one file that clears it (*"THIS file is the one that
wants the stage to end, so it releases the harness's hold"*). With `stageHold`
set, the coarse step never sets `stageComplete`, so the assertion could never
have passed. It was a probe defect, not an engine or timing symptom.

Items 9 and 10 are therefore taken from the project's own instruments rather
than from the ad-hoc probe, which is the right authority for them anyway.

---

## 6. Build and test results

**Build:** clean, no errors, all assembly-time guards pass. PRG 51,164 bytes.

| target | result | reading |
|---|---|---|
| `test-boss` | **ALL PASS** | **Item 10.** The stage boundary is still derived from authored geometry (105 × 4 − 25 = 395), the scroller freezes on the last complete authored screen with `stageTopRow` at zero and no wrap, and nothing new enters the ending arena |
| `test-turret-regression` | **ALL PASS** | **Items 7, 8.** Turret preparation, visibility and firing cadence intact at the original phase |
| `test-encounter-director` | 2 failures, both counters (`publishSkip` 21, `schedBuildDefer` 1) | **Item 9.** Every director/trigger assertion passed — wave triggers retain their authored spatial relationships |
| `test-production` | 2 failures: `publishSkip` 17; `the pool actually cycled … [3]` | **Item 11.** See below |

### The counters that catastrophically regressed have returned to baseline

| counter | pre-experiment baseline | at 2 px/frame | **now** |
|---|---|---|---|
| `gameOverrun` | 0 | **255** | **0** ✅ |
| `schedBuildDefer` | 0 | **255** | **0** (green in `test-production`) ✅ |
| `scrollLate` | 0 | 0 | **0** ✅ |
| `publishSkip` | 11 (already failing) | 255 | 17 (still the pre-existing failure) |

`gameOverrun` and `schedBuildDefer` are both absent from `test-production`'s
failure list, i.e. zero. **The severe 2 px/frame performance regression is gone.**

### Remaining failures, none of them fixed, hidden or weakened

- **`publishSkip` (17 here, 21 in the director test)** — pre-existing and failing
  before the experiment (11 at baseline). Untouched.
- **`the pool actually cycled during ordinary play -- [3]`** — a population-variation
  sampling assertion that passed in one baseline run (`[3,4,5,6,7,8]`) and fails
  here. Since the binary is byte-identical to HEAD's, this is run-to-run variation
  in what happens to be alive during the sample window, not a code difference.
- **`test-pickup`** — still crashes with `KeyError: 'waveTrigTokenLo'`, a symbol the
  engine removed when the token trigger column was deleted. Pre-existing, unrelated,
  deliberately not touched.
- **Player-movement sampling failures** — nondeterministic; appeared in some runs
  and not others both before and after.

---

## 7. Manual VICE status

- **PID 3039**, `x64sc`, PAL, visible window, `-saveres`, joystick as configured.
- **No warp, no acceleration.** Running the restored 1 px/frame build.
- You should see the familiar smooth one-pixel scroll, ~63 s to the boss, with
  none of the stutter or held frames the 2 px build showed. Manual visible output
  is authoritative.
- Owned by this task; close it yourself or say the word and I will terminate that
  exact PID. The trial's VICE (99760) was already closed before this task began.
  Every automated instance was reaped by exact PID (1217, plus each `make test-*`
  harness's own), `pgrep -fl x64sc` confirmed a clean field before each run, and
  no broad `pkill`/`killall` was used at any point.

---

## 8. Preservation of unrelated work

Nothing outside the three trial files was touched. Specifically untouched: the
HUD/P-token economy work, the boss bank-2 HUD mirror, wave definitions and
movement programmes, turret gameplay and content, player and enemy movement,
boss behaviour, level data, editor code, the memory layout, and every existing
test. No wave-contract migration or long-level storage work was begun.

The three pre-existing untracked reports are all present and unmodified:

- `reports/level-editor-current-engine-contract-review.md`
- `reports/wave-movement-architecture-and-editor-contract.md`
- `reports/scroll-speed-2px-per-frame-trial.md` — kept deliberately: it is the
  record of *why* 1 px/frame is the chosen speed, and its §7 cost analysis stands
  (subject to the §5 correction above).

---

## 9. Final status, diff and disk

```
$ git log --oneline -1
722dbbd HUD bank switching, token progress

$ git status --porcelain
?? reports/level-editor-current-engine-contract-review.md
?? reports/scroll-speed-1px-restoration.md
?? reports/scroll-speed-2px-per-frame-trial.md
?? reports/wave-movement-architecture-and-editor-contract.md

$ git diff --stat            (worktree)   <empty>
$ git diff --stat --cached   (index)      <empty>

$ du -sh build/    96K      (main.sym, main.vs, shmup.prg — no per-run directories)
$ du -sh .         7.8M
```

**`src/main.asm`, `src/scroll.asm` and `src/turrets.asm` have no diff relative to
HEAD**, in either the worktree or the index. The only untracked entries are the
four reports.

Scratch (376 K, outside the repository) holds the preserved experiment patch, the
two probes and the VICE logs; the pristine-HEAD build tree used for the hash
comparison was deleted after use.

**Nothing was committed. Nothing was pushed. No destructive reset was used, and
no test was fixed, hidden or weakened.**
