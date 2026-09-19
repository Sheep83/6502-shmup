# The boss heat gauge — a publication rate, not a heat bug

**Date:** 2026-09-19
**HEAD at start:** `6a69ab9` *Boss no-spawn event added* — level with `origin/main`, 0 behind / 0 ahead, working tree **clean**.
**Outcome:** the heat *state* was never affected by the boss. The gauge was being **published to VIC bank 2 at one seventh of the rate at which it changes**. One pinned slice copy fixes it.
**Nothing committed. Nothing pushed.**

---

## 1. The question the brief asked first

> *First determine whether the underlying heat state is itself updating less frequently / in larger increments during the boss.*

**It is not.** That was settled by measurement before anything was changed, and it is the finding that redirected the whole investigation. The report below is ordered the way the work actually went: state first, display second.

---

## 2. The heat path, traced end to end

| stage | code | gated by phase? |
|---|---|---|
| input | `playerTick` reads the stick | **no** |
| accumulation | `weaponTick`: `+WPN_HEAT_RISE` (2) per frame while a volley owns the cadence | **no** |
| cooldown | `weaponTick`: `−WPN_HEAT_FALL` (3) per frame otherwise | **no** |
| storage | `wpnHeatLo`/`wpnHeatHi`, 16-bit, 0..`WPN_HEAT_MAX` (300) | — |
| HUD feed | `weaponHudFeed` copies into `hudHeatLo/Hi`, calls `hudHeatPixels`, sets `HUD_DIRTY_HEAT` **only when the pixel count changes** | **no** |
| pixels | `heatPix: .fill 76, round(i * HUD_HEAT_PIXELS / 75)` — 300 heat → 48 pixels | — |
| redraw | `hudUpdate` in the idle spin, raster-gated to `HUD_SAFE_LO..HUD_SAFE_HI` (56..200) | **no** |
| **publication** | **`vicMirrorLive` → `vicMirrorHud`, one 128-byte slice per frame, round robin** | **bank 2 only** |

`gameFrame` calls `playerTick`, `weaponTick` and `weaponHudFeed` unconditionally. There is **no `lvlPhase` test anywhere on the heat path** — `grep -n lvlPhase src/main.asm` returns nothing. The only phase-dependent stage in the entire chain is the last one, and it is not part of the heat system at all.

---

## 3. Measurement 1 — the heat state. Identical in both phases.

A deterministic probe (`boot="exact"`, `stageHold` poked, one sample per displayed frame at a `gameFrame` breakpoint) with the trigger held:

```
--- ORDINARY GAMEPLAY (LP_LEVEL) ---
  heating, firing held   phase=LP_LEVEL  heat 2->80 | deltas seen [2]        | frames that moved 39/39 | hudHeatPix 0->13
  cooling, stick idle    phase=LP_LEVEL  heat 77->0 | deltas seen [-3,-2,0]  | frames that moved 26/39 | hudHeatPix 12->0
--- BOSS (LP_BOSS) ---
  heating, firing held   phase=LP_BOSS   heat 2->80 | deltas seen [2]        | frames that moved 39/39 | hudHeatPix 0->13
  cooling, stick idle    phase=LP_BOSS   heat 82->0 | deltas seen [-3,0,2]   | frames that moved 29/39 | hudHeatPix 13->0
```

**+2 on 39 frames out of 39 in both phases. `hudHeatPix` 0→13 in both.** The heat state, and the game's own belief about how many pixels to draw, are byte-for-byte the same cadence in the arena as in ordinary play.

This also rules out the obvious secondary suspects by construction: no frame divider, no accumulate-and-publish, no coarser step, no skipped `weaponTick`.

---

## 4. Measurement 2 — what the VIC actually fetches. Here is the bug.

The arena runs in **VIC bank 2**. The HUD's sprite bitmaps live at `$3200` in bank 0; in bank 2 the same bank-relative sprite pointers resolve to `$b200`, a **mirror** that `src/vicbank.asm` walks across one `VB_SLICE` = 128-byte slice per frame, round robin.

So "what the player sees" is a **different address in each phase** — and that is the only thing that changes about the heat gauge when the boss starts.

Sampling the live bitmap at `$3200` against the mirror at `$b200`, per frame, during `LP_BOSS`, trigger held:

```
   f 0 heat=  2 pix= 0 liveSum= 1530 mirrorSum= 5985 slice=4
   f 1 heat=  4 pix= 1 liveSum= 2682 mirrorSum= 5985 slice=5 LIVE-CHANGED
   f 2 heat=  6 pix= 1 liveSum= 2682 mirrorSum= 5985 slice=6
   f 3 heat=  8 pix= 1 liveSum= 2682 mirrorSum= 5985 slice=0
   f 4 heat= 10 pix= 1 liveSum= 2682 mirrorSum= 2682 slice=1 MIRROR-CROSSED
   f 5 heat= 12 pix= 2 liveSum= 3258 mirrorSum= 2682 slice=2 LIVE-CHANGED
   ...
   f11 heat= 24 pix= 4 liveSum= 3690 mirrorSum= 3690 slice=1 LIVE-CHANGED MIRROR-CROSSED
   ...
   f18 heat= 38 pix= 6 liveSum= 3798 mirrorSum= 3798 slice=1 MIRROR-CROSSED
   >>> over 23 frames: the live gauge changed 8 times, the MIRROR the VIC actually displays changed 3 times
```

The mirror crossed on frames **4, 11, 18** — every seven frames, exactly. And each crossing published everything that had accumulated: at **f11 the displayed gauge went from 1 pixel straight to 4**, a 3-pixel step; at f18, 4 → 6.

**The gauge stood still for six frames and then jumped.** That is precisely "advances and decrements in noticeably larger chunks", and it is coarser in both directions because cooling goes through the same mirror.

---

## 5. Root cause

```
.const VB_SLICE      = 128
.const VB_HUD_SLICES = (HUD_BLOCKS * 64) / VB_SLICE     // 14 * 64 / 128 = 7
```

`HUD_HEAT_L = HUD_SPRITES + 0*64` and `HUD_HEAT_R = HUD_SPRITES + 1*64`, so the heat gauge occupies bytes 0..127 of the HUD block: **the gauge is slice 0, whole and alone.** A 7-slice round robin therefore republishes it once every 7 frames.

The bar moves one pixel every **~3 frames** while firing (48 pixels over 150 frames at +2/frame) and every **~2.1 frames** while cooling (−3/frame). Publishing a thing that changes every 2–3 frames at a 7-frame cadence quantises it into 2- and 3-pixel steps.

`src/vicbank.asm`'s own design note states the assumption that failed:

> *"A seventh of a second of lag on a heat bar is not visible, and nothing else in the block changes during a boss fight at all."*

The reasoning is about **latency**, and as a latency claim it is correct — a seventh of a second behind is imperceptible. What the player actually sees is **quantisation**, and the same 7-frame period that is invisible as lag is very visible as a step size. The note is right about every other block: the score, the lives and the P economy change a few times a fight, so for them latency genuinely is the only question. The heat gauge is the one block in the HUD that **animates continuously**, and it was the one case the assumption did not cover.

**Why the boss specifically:** nothing in boss mode reduced the heat system's update frequency, deliberately or accidentally. In bank 0 the VIC reads the HUD bitmaps directly and there is no publication step at all. The boss is simply the only time the game runs in bank 2, and bank 2 is the only time a publication rate exists.

---

## 6. The fix

`src/vicbank.asm`, in `vicMirrorHud` — the heat slice is copied every frame, ahead of the rotation, which is otherwise untouched:

```asm
    lda #<HUD_HEAT_L
    sta vbCopySrc + 1
    lda #>HUD_HEAT_L
    sta vbCopySrc + 2
    lda #<(HUD_HEAT_L + VB2_BASE)
    sta vbCopyDst + 1
    lda #>(HUD_HEAT_L + VB2_BASE)
    sta vbCopyDst + 2
    jsr vicMirrorSlice
```

plus a build-time guard beside the slice constants:

```asm
.if (HUD_HEAT_L != HUD_SPRITES || HUD_HEAT_R - HUD_HEAT_L != 64 || VB_SLICE != 128) {
    .error "the heat gauge is no longer exactly slice 0 -- revisit vicMirrorHud's pin"
}
```

**This is not cosmetic smoothing.** Nothing interpolates, animates or eases the bar. The bar is drawn by `hud.asm` exactly as before, from the same heat state, at the same pixel values; the change is that each drawn state now actually reaches the memory the VIC fetches, instead of five of every eight being overwritten before they were ever published.

**What was deliberately left alone:** the rotation still walks 0..`VB_HUD_SLICES-1` and still raises `vicMirrorDone` on the wrap, so `src/boss.asm`'s pre-warm handshake means exactly what it did. The round robin remains correct for the blocks it was reasoned about. Slice 0 comes round once every seven frames and is copied twice that frame — ~1,800 wasted cycles a seventh of the time, which is cheaper than a cursor to dodge it.

The guard was verified to fire: moving `HUD_HEAT_L` to block 6 fails the build with its message.

---

## 7. Measured cadence after the fix

Same 23 boss frames, same probe:

```
   f 0 heat=  2 pix= 0 liveSum= 1530 mirrorSum= 1530 slice=4
   f 1 heat=  4 pix= 1 liveSum= 2682 mirrorSum= 2682 slice=5 LIVE-CHANGED MIRROR-CROSSED
   f 5 heat= 12 pix= 2 liveSum= 3258 mirrorSum= 2682 slice=2 LIVE-CHANGED
   f 6 heat= 14 pix= 2 liveSum= 3258 mirrorSum= 3258 slice=3 MIRROR-CROSSED
   f11 heat= 24 pix= 4 liveSum= 3690 mirrorSum= 3690 slice=1 LIVE-CHANGED MIRROR-CROSSED
   f18 heat= 38 pix= 6 liveSum= 3798 mirrorSum= 3798 slice=1 MIRROR-CROSSED
   >>> over 23 frames: the live gauge changed 8 times, the MIRROR the VIC actually displays changed 7 times
```

| | before | after |
|---|---|---|
| heat state, per frame, firing | **+2 on 39/39 frames** | **+2 on 39/39 frames** (unchanged — it was never the problem) |
| bar states drawn, 23 frames | 8 | 8 |
| bar states **published** | **3** | **7** (the 8th crosses on f24) |
| biggest displayed step, firing | **3 px** | **1 px** |
| biggest displayed step, cooling | **4 px** | 1–2 px |
| longest stretch with the gauge held still | **7 frames** | **5 frames** (ordinary play, which cannot lag at all, measures 4) |

Every published step is now a single pixel: `1530 → 2682 → 3258 → 3546 → 3690 → 3762 → 3798 → 3816`.

**The residual 2-pixel step while cooling is designed in and is not the defect.** `vicMirrorLive` copies at most once per displayed frame and only while the raster is inside `HUD_SAFE_LO..HUD_SAFE_HI`, because those are the bytes the VIC fetches for the HUD sprites and copying across that fetch would tear a digit. A frame whose `hudUpdate` ran late can push the copy past the window and defer it by one frame. Cooling earns a pixel every ~2.1 frames, so one deferral can occasionally merge two steps. That is a bounded one-frame lag, not a seven-frame plateau, and removing it would mean removing the tearing guard.

---

## 8. Regression protection

New file **`tests/test_heat_cadence.py`** (one VICE launch), wired as `make test-heat-cadence` and added to the default `make test`.

It is built around the distinction the brief asked for, because **the heat state and `hudHeatPix` were correct throughout this bug** — a test that asserted on either would have passed against the defect it was written for. So it asserts two things separately:

* **the heat STATE cadence** — `wpnHeatLo/Hi` rises by exactly `WPN_HEAT_RISE` on every frame the trigger is held, and falls on release, measured in `LP_LEVEL` and `LP_BOSS` and **compared directly in the same run**;
* **the PUBLISHED cadence** — read by population-counting a sprite row of the bar out of **the bitmap the VIC is actually fetching**, which is `$3200` in bank 0 and `$b200` in bank 2. `barFill` is a solid left-aligned run three bytes to a row, so the popcount *is* the pixel count.

Both are measured heating **and** cooling. The headline metric is the **plateau**: the longest run of frames over which the displayed bar does not move while the HUD is still redrawing it. A round robin of N slices distorts the gauge in exactly that shape — still for N−1 frames, then a jump — which separates the two regimes with room to spare.

**The test was verified to fail against the unfixed code.** Reverting `src/vicbank.asm`, rebuilding and re-running produced **8 failures**:

```
FAIL LP_BOSS: THE BITMAP THE VIC FETCHES never sits still for a whole slice cycle while the bar is moving
     -- 8 drawn, 3 published, biggest step 2 px, longest still stretch 7 frames
FAIL LP_BOSS: every pixel step the HUD draws reaches the player
FAIL LP_BOSS: COOLING is published at the same cadence -- the report was of coarseness in BOTH directions
     -- 7 drawn, 2 published, biggest step 4 px, longest still stretch 7 frames
FAIL ...and so is the cadence at which the gauge is PUBLISHED while firing
     -- LP_BOSS [8 drawn, 3 published] vs LP_LEVEL [8 drawn, 8 published]
FAIL THE ARENA NEVER HOLDS THE GAUGE STILL LONGER THAN ORDINARY PLAY DOES, which is the whole report
     -- firing 7 vs 4 frames, cooling 7 vs 3 frames
```

and, decisively:

```
ok   THE STATE CADENCE IS IDENTICAL in LP_LEVEL and LP_BOSS while firing -- LP_BOSS [2] vs LP_LEVEL [2]
```

**That line passes on both builds.** The test demonstrates, from the failing build itself, that the heat state cadence was never the defect and that the display alone was — which is exactly the distinction the brief required the regression to be able to draw. The pre-fix cooling numbers (**7 drawn, 2 published, 4-pixel steps**) are the reported symptom reproduced as an assertion.

`tests/test_boss_hud_transition.py` is **unchanged**. The cadence checks were prototyped inside it and removed again: holding the trigger to raise heat awards score and perturbs that file's run to the boss, which its later assertions depend on. A dedicated file with its own launch is both safer and a more direct answer to "compare `LP_LEVEL` and `LP_BOSS`". Its existing comment —

> *"Hold the value steady so the lagging feed has something to converge ON: a bar that moves every frame can never be caught by a mirror that is deliberately a few frames behind it"*

— is the old behaviour written down as a workaround, and is worth reading beside the new file.

---

## 9. Cost

| | |
|---|---|
| **Code** | **+23 bytes** — 4 × (`lda #imm` + `sta abs`) = 20, plus `jsr abs` = 3 |
| **RAM** | **none.** No new variable, no new cursor, no new flag |
| **Cycles** | **~1,829 per displayed frame** while bank 2 is up: 24 setup + 12 `jsr`/`rts` + 2 `ldy` + 1,791 for the 128-byte loop at 14 cycles a byte. **9.3 %** of a PAL frame's 19,656 |
| **Where it is paid** | in `LP_BOSS`, from the **idle spin** (`vicMirrorLive`), which is time the main thread was spinning anyway. During `LP_CLEARING` the pass runs from `bossClearTick` on the main thread for the ~7 frames of the HUD cycle — `ARENA_CLEAR_DEADLINE` is 200 frames |
| **In ordinary play** | **zero.** `vicMirrorLive` is five cycles and an `rts` in bank 0; `vicMirrorHud` is never reached |
| **`gameOverrun` / `scrollLate`** | **0 and 0**, asserted in the new test and across the boss suite |

---

## 10. Regression results

Twenty test files, run end to end against the fixed build. **Every boss, bank-2, HUD and lifecycle suite passes.**

| file | result |
|---|---|
| `test_heat_cadence` **(new)** | **ALL PASS** |
| `test_boss_hud_transition` | **ALL PASS** — unchanged file, the mirror's own regression suite |
| `test_bank2_arena` | **ALL PASS** |
| `test_boss` | **ALL PASS** |
| `test_lifecycle` | **ALL PASS** |
| `test_player_death` | **ALL PASS** |
| `test_boot`, `test_production` | **ALL PASS** |
| `test_turret_regression` | **ALL PASS** |
| `test_player_ship`, `test_pickup` | **ALL PASS** |
| `test_movement_pool`, `test_no_spawn_row`, `test_wave_triggers` | **ALL PASS** |
| `test_encounter_director` | 2 failures — **pre-existing** |
| `test_level_assets` | 3 failures — **pre-existing** |
| `test_sfx` | 3 failures — **pre-existing** |
| `test_token_encounter` | 2 failures — **pre-existing** |
| `test_dropper_flight` | 1 failure — **pre-existing** |
| `test_enemy_fire` | 1 failure — **pre-existing** |

**The six failing files were baselined against `HEAD` with the fix reverted and rebuilt**, rather than assumed pre-existing. Five of them fail **identically** — same assertions, same values:

| file | with the fix | HEAD, without it |
|---|---|---|
| `test_encounter_director` | `publishSkip -- 12`, `schedBuildDefer -- 1` | `publishSkip -- 12`, `schedBuildDefer -- 1` |
| `test_level_assets` | window pointers `[]`, `publishSkip -- 12`, `schedBuildDefer -- 1` | identical |
| `test_sfx` | `$1840 vs $1768`, state `10`, KILL `None` | identical |
| `test_token_encounter` | protector ascent `runs {}`, `schedBuildDefer -- 1` | identical |
| `test_dropper_flight` | `schedBuildDefer -- 1` | identical |
| `test_enemy_fire` | `the director keeps spawning -- spawned 21->21, started 4->4` | identical |

`test_enemy_fire` needed a second look: in the first full-suite pass it failed on a *different* assertion (`wvShots 5->5, ebFired 10->10`). Re-run twice on its own against the fixed build it produces exactly the baseline failure, so that file is flaky under suite load rather than sensitive to this change. Every other failure is byte-identical on both builds.

This is also what the code predicts: `vicMirrorHud` is reached only from `vicMirrorLive`/`vicMirrorTick`, both of which return immediately unless `vicBank2` is set. The failing suites are all ordinary-play paths that never enter the arena, so the changed instructions never execute during them.

`gameOverrun` and `scrollLate` are **0** — asserted in the new test and across `test_boss`, `test_bank2_arena` and `test_boss_hud_transition`.

---

## 11. Manual VICE

`x64sc` **PID 88519**, launched directly (never `open -a`, so no focus is stolen) with the manual configuration from the `run` target — `-saveres -pal -joydev2 2 -keyset -autostart build/shmup.d64`. Visible, **PAL, normal speed, no warp, no monitor**, which AGENTS.md notes is the only configuration in which what you see is what the machine really does.

**This instance is left running for you to judge.** The visual confirmation is genuinely yours to make and I have not claimed it: AGENTS.md records that *any monitor command halts the emulator, so a harness cannot observe a freely-running non-warp machine.* There is no way for me to watch the gauge move in real time — which is exactly why the automated evidence above reads the sprite bytes the VIC fetches rather than anything about appearance.

What to look for: hold fire into the boss arena and watch the heat bar fill, then release and watch it drain. It should creep pixel by pixel at the same rate it does during the level, instead of pausing and lurching forward two or three pixels at a time.

**Warp is not a factor in the automated figures.** VICE's warp scales host speed only; emulated raster and cycle timing are bit-identical, and every measurement above reads RAM rather than the rendered image.

---

## 12. Changed files

| file | change |
|---|---|
| `src/vicbank.asm` | **+53 lines** (23 bytes of code, the rest comment): the pinned heat-slice copy at the head of `vicMirrorHud`, and the build-time guard beside the slice constants |
| `tests/test_heat_cadence.py` | **new**, 335 lines. One VICE launch |
| `Makefile` | **+11 lines**: `test-heat-cadence` target, `.PHONY` entry, and the file added to the default `make test` |
| `reports/boss-heat-gauge-publication-cadence.md` | this report |

**Not touched:** `src/weapon.asm`, `src/hud.asm`, `src/main.asm`, `src/boss.asm`, the renderer, the sprite multiplexer, scrolling, the encounter director, `STAGE_NO_SPAWN_ROW`, the level package format. `tests/test_boss_hud_transition.py` is unmodified. No unrelated cleanup or refactoring.

**No deeper engine scheduling problem was found.** The brief asked me to stop and report before any broad architectural change if one appeared; none did. The frame loop, the schedule builder and the spin are all behaving as designed, and the defect was one block being published on the wrong cadence by a routine whose own comment records the assumption that produced it.

---

## 13. Repository status and disk

* **HEAD `6a69ab9`** *Boss no-spawn event added* — 0 behind / 0 ahead of `origin/main`.
* Working tree: `M Makefile`, `M src/vicbank.asm`, `?? tests/test_heat_cadence.py`, `?? reports/boss-heat-gauge-publication-cadence.md`.
* **Nothing committed. Nothing pushed.**
* `build/` — **344 KB**, the current binary and symbols only. No per-run directories. `shmup.prg` 51,164 B, `shmup.d64` 174,848 B, `level1.prg` 7,030 B.
* Scratch — **988 KB** in the session scratchpad (probe scripts, the saved copy of the patched `vicbank.asm` used for the revert-and-compare, VICE logs). Nothing written to `/tmp`; nothing left in the repo.
* VICE: every automated launch reaped by exact PID; `pgrep -x x64sc` was clean before and between runs. One instance, **PID 88519**, is deliberately left running for the manual check and is yours to close.
