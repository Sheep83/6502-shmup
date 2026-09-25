# 19656 — Campaign Transition Follow-up

**Priority 1 (runtime Level 2 corruption): four compile-time leaks found and fixed; the engine is now byte-identical whichever `LEVELDIR` it is built with. Priority 2 (smooth SPEED): replaced with per-axis sub-pixel accumulators. Priority 3 (raster shimmer): investigated from the engine's own cycle instrumentation; no timing evidence found, production timing left unchanged.**

---

## 1. Starting state

| | |
|---|---|
| HEAD | `cb3c194` — *Turrets and enemies updated* |
| Branch / upstream | `main` / `origin/main`, level with it |
| Committed / pushed | **nothing** |

Hashes before any change:

```
d4eb2574420b259b  build/shmup.prg
88b5bbf0df828f47  build/level1.prg
1f1d414adc811036  build/level2.prg
```

### Your own authored work, preserved

Two files were already dirty and are **not mine**: `src/level1/wave_encounters.asm`
and `tools/level_editor/levels/level1/level.v6.json` carry three new Dropper
triggers at rows 350, 450 and 550 (`WAVE_TRIGGERS` 9 → 12). I left them
untouched; their diff is unchanged from when I started.

That addition turned out to matter — see the trigger-count leak in §2.

---

## 2. Priority 1 — the runtime Level 2 corruption

### The engine-independence audit

Built `src/main.asm` twice, once with each `LEVELDIR`, and diffed:

```
d4eb2574...  LEVELDIR=src/level1 engine.prg
e055c1af...  LEVELDIR=src/level2 engine.prg     29 bytes differ
```

Attributing every differing byte to its nearest symbol:

| symbol | what leaked |
|---|---|
| `scrollInit`, `rowBack`, `scrollTick`, `renderBackgroundRow`, `turretRelRow`, `turretPrepareTick`, `turretDeriveShadow`, `turretDeriveOne`, `turretRepairPage` | `TERRAIN_STAGE_ROWS` / `STAGE_METATILE_ROWS` — the stage height |
| `terrainInit` | `TERRAIN_MC_COLOUR_1/2` and `STAGE_METATILE_COUNT * METATILE_W` |
| `turretPaintTick`, `bossDrawBar`, `bossClearBar`, **`gsClearScreen`** | `TERRAIN_COLOUR_RAM` — the colour-RAM fill |
| `waveTick` | `WAVE_TRIGGERS` — the trigger count |

**Three of those are the corruption. One is the title colour. One is the
agreed-to-keep stage height.**

### Root cause 1 — the grey chip bodies

```asm
// terrainInit, and it ran AFTER terrainApplyPackage
    lda #TERRAIN_MC_COLOUR_1
    sta $d022
    lda #TERRAIN_MC_COLOUR_2
    sta $d023
```

`terrainApplyPackage` sets `$d022`/`$d023` from the loaded package and runs
first in `gsEnterNextLevel`; `terrainInit` then overwrote them with **the
colours of whatever level the engine was built against**. Level 2 authors
`$d022 = 0` (black) and got 15 (light grey) — so every black IC body on its PCB
terrain came out grey. Exactly the reported symptom.

**Fix:** the two stores are gone. `terrainApplyPackage` owns the pair on the
boot path and the level-change path alike.

### Root cause 2 — the missing glyph detail

```asm
// the metatile-definition transpose, in terrainInit
    cpx #STAGE_METATILE_COUNT * METATILE_W      // 41 * 4 for a level-1 engine
```

Level 1 authors 41 definitions and level 2 authors **49**, so an engine built
for level 1 transposed only 41 of them. Every map cell naming metatile 41..48
read sub-row entries that had never been written.

**Fix:** transpose the whole `LEVELPKG_DEFS` reservation — 64 definitions,
which is exactly `TR_TILE_STRIDE`. The package zero-fills what the level did not
author, so the pass loads this level's tiles **and** clears the previous
level's out of the tail. The same argument `terrainApplyPackage` already makes
for copying the whole charset window, and it needs no count at all.

### Root cause 3 — five phantom waves

`waveTick` compared its cursor against the compile-time `WAVE_TRIGGERS`. The
trigger *data* has always been package data; the *count* was not. With level 1
at 12 and level 2 at 7, a transitioned level 2 would have walked twelve entries
through a seven-entry list and fired the five zero-padded rows as waves at world
row 0.

**Fix:** the count is now `LEVELPKG_TRIGN`, a package byte. It went in the spare
run above the render identity rather than into the two-byte stage header, which
would have shifted the movement pool, the wave definitions and the trigger list.

> This one only became reachable when you added three triggers to Level 1. At 9
> and 7 it was still wrong; at 12 and 7 it is worse. Either way it was invisible
> to every existing test, because every existing test plays the level the engine
> was built for.

### Root cause 4 — the white title text

```asm
// gsClearScreen
    lda #TERRAIN_COLOUR_RAM
```

The attract screen's colour-RAM fill was the **build-time** terrain colour.
Level 1's `TERRAIN_CHARACTER_COLOUR` is 1, so `8|1 = 9` — brown. Level 2's is 7,
so `8|7 = 15` — light grey, which reads as white. **The title screen is not level
content; the leak was this fill.** Same constant in the turret colour restore and
the boss health bar, where it would have handed a level-2 cell level 1's colour.

**Fix:** all four read `trnCramValue`, the resident level's fill.

### The stage height — changed source, not behaviour

`TERRAIN_STAGE_ROWS` was `STAGE_METATILE_ROWS * METATILE_H`: the authored height
of whatever level the engine was built against. `LEVELDIR=src/level2` therefore
produced a **552-row engine** while the campaign builds an 800-row one.

It is **still compile-time** — runtime-variable stage height remains the agreed
follow-up and was not attempted. What changed is where the number comes from:
`LEVELPKG_STAGE_ROWS`, the shared contract that also tells
`tools/pad_stage_map.py` what to pad every package up to. One number, one place,
no `LEVELDIR` in it.

### The result

```
*** ENGINE BYTE-IDENTICAL UNDER BOTH LEVELDIRs ***
```

### Direct vs transitioned Level 2

The engine being level-independent makes this measurable cleanly: **the same
binary**, with level 2's package booted as `LEVEL1` from a scratch disk in one
run and loaded at run time by the shop in the other. The package is the only
variable. Sampled at the same scroll phase:

| | direct | transitioned |
|---|---|---|
| `$d016`, `$d020`–`$d023`, `$dd00` | identical | identical |
| `trnBgColour` / `trnCramValue` / `trnGlyphCount` | 5 / 15 / 128 | 5 / 15 / 128 |
| `turretCount`, `wvNextTrig`, `LEVELPKG_TRIGN` | 0, 0, 7 | 0, 0, 7 |
| package signature, palette | identical | identical |
| **charset window (1 K)** | `3ed35fd4d7eb` | `3ed35fd4d7eb` |
| **transposed sub-rows (1 K)** | `ffa7b1c321be` | `ffa7b1c321be` |
| **metatile defs, map** | identical | identical |
| **enemy window, boss cells** | identical | identical |
| playfield colour RAM | all == fill (15) | all == fill (15) |
| `$d011` mode bits, `$d018` charset bits | identical | identical |

**23 of 24 identical.** The one difference is `$d018`'s VM bits — which
double-buffer page is currently published, which alternates every coarse step.

Two apparent differences during the investigation were **my instrumentation, not
the engine**, and both are worth recording because they would mislead anyone
repeating this:

* **Polling halts the machine.** A `while` loop reading `gsState` every 250 ms to
  wait for the load freezes the transition partway and then reports what it
  caught — it "found" colour RAM still holding level 1's value. A flat sleep
  fixes it.
* **The HUD legitimately differs.** Hashing all 1000 colour-RAM cells compares
  score, lives and P-count cells too, which differ between a fresh boot and a run
  that has played a level and been shopping. The test compares the terrain fill
  instead.

### Permanent test

`tests/test_level_identity.py` — 25 checks, all passing. It builds the scratch
disk itself into a temporary directory, runs both paths and compares the hashes
above. If any of them diverges again it says which.

---

## 3. Priority 2 — smooth fractional SPEED

### Audit

`plyX` / `plyXHi` / `plyY` are read by `src/collision.asm` (the overlap
windows), `src/ebullet.asm` (aim and the hit test), `src/pickup.asm` (the token
hit test), `src/turrets.asm` (the fire lead), `src/boss.asm` (the exit flight)
and `src/player.asm` (emit and the clamps).

**So the position representation was left exactly as it is.** The sub-pixel
state is a *separate* accumulator that only `playerTick` touches; every consumer
still reads the same integer bytes. Not one of them had to change — which is why
collision, hitscan, pickup and render coherence is preserved by construction
rather than by re-verification.

### What was actually wrong

The old implementation granted the extra pixel on `frameCounter AND mask` and
called the whole movement routine a second time. Three defects, only two of them
about smoothness:

* **The cadence did not belong to the player.** The boost landed on fixed
  absolute frames, so whether a press got one depended on *when* it happened. A
  short tap could be all boost or none.
* **Both axes boosted together.** One global mask meant a diagonal gained its
  extra pixel on X and Y in the *same* frame — a two-pixel diagonal lurch.
* **A reversal inherited the credit.** Three frames right left the counter nearly
  full, so the first frame of the reversal jumped two pixels the other way.

### The design

Per-axis accumulators in 1/256ths of a pixel. `cmpSpeedFrac` is 0, 64 or 128;
each axis adds it on a frame that axis moves, and the **add's carry** is the
extra pixel. The two axes are seeded half a period apart so their extra pixels
interleave; an axis that reverses or stops has its credit cleared.

| purchased | frac | rate |
|---|---|---|
| 0 | 0 | **1.00 px/frame — carry impossible, legacy exact** |
| 1 | 64 | 1.25 |
| 2 | 128 | 1.50 |

Measured, 16 frames of held RIGHT:

```
SPEED 0 (frac   0): [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]   1.000 px/frame
SPEED 1 (frac  64): [1,1,1,1,2,1,1,1,2,1,1,1,2,1,1,1]   a clean 1-in-4
SPEED 2 (frac 128): [1,1,2,1,2,1,2,1,2,1,2,1,2,1,2,1]   alternating
```

Reversal after three frames of right-hand motion: `[-1, -1, -2, -1]` — **no
two-pixel lurch on the first frame back.**

### What it cannot fix, plainly

The rendered position is an integer pixel, so an average of 1.25 px/frame **must**
be three frames of one pixel and one of two. No sub-pixel scheme changes that.
What it changes is that the two-pixel frame is regular with respect to the
player's own motion rather than to a free-running counter, that the two axes do
not take theirs at the same moment, and that a reversal starts clean.

**If that still reads as jerky in play, the honest options are a lower rate
(frac 32 = 1.125) or accepting 1.00/1.50 only** — not a different accumulator.
Your eye on it is the deciding evidence.

### Where it lives, and why

`cmpSpeedFracStep` and the accumulators are in `src/campaign.asm`, not
`src/player.asm`: the player **state** block at `$c51a` is exactly full (four
more bytes ran it into the scroll state at `$c540`) and the player **code**
segment at `$4000` is now within 4 bytes of the scroller at `$4340`. The
campaign file is imported first, which is also what lets `src/player.asm` name
`cmpSpeedFrac` at all. The stick-bit constants are restated there for the same
ordering reason, with a build-time guard in `src/main.asm` that fails if the two
copies ever disagree.

---

## 4. Priority 3 — the shimmering raster line

### What the source already says

`exTop` in `src/renderer.asm` documents a mechanism that would produce exactly
this artefact: at YSCROLL 7 line 55 is itself a badline, the store can be pushed
past every g-access, and **"raster 55 renders from the BLANK charset: one
missing terrain line, one frame, roughly 1% of frames."** Raster 55 is the top
of the playfield, immediately below the HUD.

It also documents the mitigation — at YSCROLL 7 the charset store splits on line
54 instead, where the VIC is in idle state and the store has a whole line of
slack — and the counter that would catch a failure, `edgeLate`.

### The measurement

The engine carries purpose-built, non-perturbing instrumentation:
`topSplitMin` / `topSplitMax` record the range of lines the top split actually
landed on, and `edgeLate` counts every frame it missed `topTarget`.

**8,327 frames of undisturbed play:**

```
topSplitMin      = 54        the YSCROLL-7 path
topSplitMax      = 55        every other phase
edgeLate         = 0
scrollLate       = 0
gameOverrun      = 0
publishSkip      = 1         once in 8,327 frames (pre-existing)
schedBuildDefer  = 1         once in 8,327 frames (pre-existing)
```

The split lands on exactly the two lines it is designed for and never once late.
The documented hazard is **mitigated and not firing**.

> A first attempt to measure this with a breakpoint at `exTopLanded` appeared to
> show 10 % of splits completing at raster 256. That was the breakpoint itself:
> halting the CPU inside an IRQ handler and resuming changes when the raster poll
> completes, so the instrument was creating the fault it was looking for. The
> engine's own counters do not perturb anything and disagree with it.

### Conclusion

**I have no timing evidence for the shimmer, so I have changed nothing.** The
brief's instruction was to identify a register or timing window physically
capable of producing the partial line before touching anything, and the one
candidate the code documents is provably not occurring.

What I have *not* ruled out, and would need visible VICE to distinguish:

* the single `publishSkip` / `schedBuildDefer` per run — but those are
  sprite-schedule events, not raster-line ones, and one frame in 8,327 does not
  match "shimmering";
* a VICE rendering artefact rather than an emulated-hardware one;
* something in the HUD's own sprite rows rather than the split.

Since Level 2's bright green makes it easier to see, and Level 2's background is
now actually correct for the first time, it is worth looking again — the
appearance may have changed.

---

## 5. Memory and cycle impact

| | |
|---|---|
| `cmpSpeedFrac` + accumulators | 5 bytes (campaign state, `$c780-$c786`) |
| `LEVELPKG_TRIGN` | 1 byte of package |
| `campaign code` | `$9000-$90a1`, 162 bytes (was 89) |
| `player code` | `$4000-$433b` — 4 bytes clear of the scroller |
| package | 8,085 bytes of 8,186 |

Per-frame cost:

| | |
|---|---|
| `cmpSpeedFracStep`, twice a frame | ~30 cycles; at SPEED 0 one `adc` and one untaken branch |
| `waveTick` trigger compare | `cpy abs` instead of `cpy #imm`: **+2 cycles/frame** |
| `trnBgColour` in the aperture splits | unchanged from the previous task: +4 cycles/frame |
| metatile transpose 41 → 64 definitions | level-init only, ~+1,500 cycles once |
| `terrainInit` no longer writes `$d022`/`$d023` | **−8 cycles** at level init |

Under 0.2 % of a 19,656-cycle frame.

---

## 6. Tests

| Test | result | verdict |
|---|---|---|
| `test_campaign.py` | **29/29 pass** | speed rates, prices, transition, resets, persistence, END |
| `test_level_identity.py` | **25/25 pass** | **new** — direct vs transitioned Level 2 |
| `test_boot.py`, `test_turret_regression.py`, `test_aimed_fire.py`, `test_player_death.py`, `test_pickup.py` | pass | — |
| `test_lifecycle.py` | pass in isolation | **flaky in batch** — see below |
| `test_turret_arming.py` | pass in isolation | **flaky in batch** — see below |
| `test_production.py` | 1 FAIL | pre-existing (`STAGE_START_ROW` constant is stale) |
| `test_enemy_fire.py` | 1 FAIL | pre-existing — identical message at `cb3c194` |
| `test_level_assets.py`, `test_encounter_director.py`, `test_player_ship.py`, `test_sfx.py`, `test_boss.py`, `test_heat_cadence.py` | 3 / 4 / 1 / 4 / 17 / 10 FAIL | pre-existing, unchanged |

**Two tests are flaky under batch load and I want to be explicit rather than
quietly re-run them until green.** `test_lifecycle` reported the GAME OVER page
showing terrain glyphs in one batch run and stamps `G A M E   O V E R` correctly
in every isolated run. `test_turret_arming`'s unaided section depends on
`warp_ahead`'s wall-clock sleeps landing inside a 120-frame window; under a batch
of sequential VICE launches it can miss. I confirmed the engine behaviour
directly — the turret arrives unaided at frame 119 with `logY 54`, armed with 34
— so the engine is right and the harness is timing-sensitive. Making
`warp_ahead` land deterministically is a worthwhile follow-up.

---

## 7. Files changed

**Modified:** `src/terrain.asm` (palette stores removed, transpose bound, stage
height from the contract), `src/gamestate.asm` (colour-RAM fill, a branch out of
range), `src/turrets.asm` (colour-RAM fill, stage height), `src/boss.asm` (bar
colour), `src/waves.asm` (trigger count, both sites), `src/levelpkg.asm`
(`LEVELPKG_TRIGN`), `src/level_package.asm` (emits it), `src/player.asm` (per-axis
steps, accumulator call sites), `src/campaign.asm` (`cmpSpeedFrac`,
`cmpSpeedFracStep`, `cmpSpeedReset`, stick bits), `src/main.asm` (stick-bit
guard), `src/renderer.asm` and `Makefile` (unchanged this task, dirty from the
previous one).

**New:** `tests/test_level_identity.py`, this report.

**Not touched:** `src/level1/wave_encounters.asm` and
`tools/level_editor/levels/level1/level.v6.json` — your trigger additions.

---

## 8. Hygiene

* **Nothing committed. Nothing pushed.** HEAD is still `cb3c194`.
* VICE: every launch through the harness — exact PIDs, `-console`, reaped in
  `finally`. No broad `pkill`, no user VICE touched, no focus stolen. `ps`
  confirms **none running**.
* No worktrees left; scratch disks built into temporary directories and removed.
* `build/` 340 K, current artefacts only. Disk: 94 GiB free of 228 GiB.

Final hashes:

```
7a6f4686c57b10cb  build/shmup.prg
ef4913f6c456db86  build/level1.prg
0a555f8b1b26fd77  build/level2.prg
```

---

## 9. Acceptance gate

| # | | |
|---|---|---|
| 1 | Evidence-backed root cause | ✅ four, each attributed to a named symbol by byte diff |
| 2 | Campaign-loaded Level 2 has correct visual state | ✅ §2, hash-for-hash with direct |
| 3 | Unintended `LEVELDIR` influence removed | ✅ engine byte-identical under both |
| 4 | Title colour explained and corrected | ✅ `gsClearScreen`'s compile-time fill |
| 5 | Direct and transitioned agree | ✅ 23/24; the one difference is the alternating page |
| 6 | Level 1 remains correct | ✅ its map byte-identical, its authored triggers untouched |
| 7 | SPEED 0 exact legacy behaviour | ✅ `[1,1,1,…]`, carry impossible at frac 0 |
| 8 | 1.25/1.50 without the second-step cadence | ✅ per-axis accumulator carry |
| 9 | Render/collision/hitscan/clamping coherent | ✅ position representation unchanged; no consumer touched |
| 10 | Raster investigated from timing evidence | ✅ 8,327 frames of the engine's own counters |
| 11 | No unrelated raster/mux/scroller redesign | ✅ none; raster left alone entirely |
| 12 | Prices 1 P / 2 P, three pickups per P | ✅ unchanged, still tested |
| 13 | Authored levels and library ownership intact | ✅ |
| 14 | Nothing committed or pushed | ✅ |

**Outstanding for you:** visible VICE on Level 2 (its palette is correct for the
first time, so the shimmer may look different), and a judgement on whether
1.25 px/frame now reads smoothly enough.
