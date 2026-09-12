# Migration audit: `c64Shooter` → `6502-shmup`

Independent architecture audit, 12 September 2026. PAL C64, KickAssembler 5.25, VICE 3.10.

Sources of record: `c64Shooter-main.zip` (old game, 10,216-line `src/main.asm` plus `raster_scheduler.asm`, `background_turrets.asm`, `variables.asm`, `src/generated/level{1,2}/*`) and `6502-shmup` at commit `3f7c3d3` (`src/main.asm`, `renderer.asm`, `scroll.asm`, `sorter.asm`, `motion.asm`, `hud.asm`, `sprites.asm`, fixtures, `docs/ENGINE_CONTRACT.md`, `tests/test_engine.py`). Line numbers below refer to those files as unpacked. Nothing in either repository was modified.

Evidence tags used throughout:

- **[S]** observed in source
- **[R]** recommended design
- **[U]** uncertain, requires runtime confirmation

---

## 1. Executive recommendation

**Go, with five contract decisions made up front.** The old game's behaviour layer (player, weapon, heat, waves, movement fragments, enemy lifecycle, bullets, turrets, score, lives, game states) is genuinely separable from its renderer. Almost every gameplay routine reads and writes the `OBJECT_*` arrays at old `main.asm:5176-5399` and nothing else; the renderer coupling is concentrated in a handful of places that must be discarded wholesale. The behavioural constants and data tables (attack catalogue, movement fragments, wave triggers, turret placement, heat curve, death timings) are portable as they stand.

The five decisions the new engine forces, none of which the old code answers for you:

1. **Scroll direction.** [S] The new scroller counts `scrollFine` **down** 7..0 and **increments** `worldRow`, so terrain moves **up** the screen (`scroll.asm:20-27`). The old game increments `SCROLL_FINE` 0..7 and **decrements** `SCROLL_ROW`, so terrain moves **down** the screen and the authored level is walked bottom-to-top (`main.asm:764-782`, `6627-6650`). These are opposite. A vertical shooter with the old level data needs the old direction. Flipping it is a change to `scrollTick`/`regen` world-row arithmetic and the top-split badline analysis, and must go through `make test-engine-full` before any gameplay is stacked on it. Decide this first.
2. **Multicolour.** [S] The new engine forces `$d01c = 0` on both sides of the handoff (`renderer.asm` `exHud`, `exHandoff`) and never writes `$d016`, `$d022`, `$d023`, `$d025`, `$d026`. Every old gameplay sprite (`playerSprite`, `enemySpriteA..D`, `enemyBulletSprite`, `playerExplosion1..4`, `main.asm:5413-5672`) is multicolour art, and the old terrain is multicolour text mode. Either the art is redrawn hires, or a multicolour extension joins the handoff contract (per-batch `$d01c`, `$d025/$d026` at handoff). Recommend: **hires for the player now** (the old two-layer hires player experiment maps exactly onto HW0/HW1), **defer multicolour enemies** behind a measured renderer extension slice, **multicolour terrain is boot-time state** and is fine.
3. **Player feed.** [S] No path exists today to program HW0/HW1. `exHud` and `exHandoff` write `$d015` and `$d010` as complete values with bits 0 and 1 clear. The player record must become part of the published schedule and be folded into those stores by the renderer. This is the one renderer change the migration cannot avoid, and it is small.
4. **RAM charset placement.** [S] The new aperture depends on a 2 KB **zero** charset at `$3800` and the ROM charset at `$1000`. The old terrain tileset lived in a RAM charset at `$3800` (codes 96..223 at `$3b00..$3eff`). A game charset needs a new bank-0 home (`$3000` is the candidate once HUD bitmaps move to `$2400` after the ring fixtures retire). This is a Slice H problem, not a Slice A problem; do not touch it earlier.
5. **Joystick.** [S] `Makefile` `VICE_OPTS` detaches both joysticks (`-joydev1 0 -joydev2 0 +keyset`) to protect fixture key selection, and the fixture keyboard scan writes `$dc00` (`main.asm:363-431`). Slice A retires the fixture keys and re-attaches port 2.

Classification headline: of 41 subsystems audited, 4 are A, 13 are B, 12 are C, 10 are D, 2 are E. Nothing from the old raster scheduler, multiplexer, render-plan, page-flip, coarse-scroll, bullet-suppression, clip-pool or HUD presentation code crosses. The old game contributes **behaviour and tables**, not an engine.

The recommended first Opus task is **Slice A: production main loop plus player on HW0/HW1**, specified in section 16. It replaces the fixture app's per-frame block with a game frame, adds a player record to the schedule, and reads the joystick. It touches the renderer in exactly three places and is measurable with the existing counters.

---

## 2. New-engine contracts that migration must not violate

All read out of `6502-shmup/src` and cross-checked against `docs/ENGINE_CONTRACT.md` and `tests/test_engine.py`. Where the document and source differ, source wins; none were found to differ.

| Contract | Value / rule | Where enforced |
|---|---|---|
| Frame | PAL, 19,656 cycles, legal NMOS only | `AGENTS.md` |
| Per-frame main-thread order | `motionTick` → `sortTick` → `buildSchedule` → `publishSchedule`; then `regenTick` → `scrollTick` | `main.asm:311-327`, `republish` |
| Publication | `publishSchedule` = one byte `schedPending`; `publishFrame` = one byte `framePending`; `buildSchedule` withdraws a pending publication before writing `schedNext` (`schedBuildDefer` counts it) | `renderer.asm:389-419`, `scroll.asm:publishFrame` |
| Immutable CURRENT | executor reads only `sched*[schedCurrent]` and `frame*[frameCurrent]`; adopted at raster 250 in `exFrame` | `renderer.asm` `exFrame`, `frameEntryLine == 250` asserted by every suite |
| Slots | HW0/HW1 reserved (player base/overlay); HW2..HW7 = `MUX_FIRST_SLOT=2`, `MUX_SLOTS=6`; accepted entry *i* → slot `2+(i mod 6)`; same-slot predecessor = *i-6* | `renderer.asm:31-33`, `bs_accept` |
| Admission | `MIN_SPRITE_Y=55`, `MAX_SPRITE_Y=226`, `SPRITE_HEIGHT=21`, `REUSE_LEAD=12`, `MIN_REUSE_GAP=33`; out-of-range sprites are **rejected and counted** (`statRejRange`), never clamped | `renderer.asm:83-102`, `bs_loop` |
| Capacity | `MAX_LOGICAL=32`, `MAX_SCHED=24`, `MAX_BATCH=24` | `renderer.asm:116-118` |
| Phase schedule | 4 `exHud`, 40 `exHandoff` + batch 0, 53 `exTop` (poll to 55, 54 at YSCROLL=7), 68+ batches, 243 `exBottom` (poll to 248), 250 `exFrame` | `renderer.asm` `irqHandler` dispatch and each phase |
| HUD ownership | HUD owns HW2..HW7 only between rasters 4 and 40; handoff rewrites `$d017`,`$d01b`,`$d01c`,`$d01d` unconditionally, then batch 0, then `$d015` last; `$d017` never non-zero; `$d01c` forced 0 both sides | `exHud`, `exHandoff`, arming tail after batch 0 |
| Ghost rule | never enable a sprite between rasters 250 and 4 (`$d015=0` written at 250) | `exFrame` |
| HUD bitmap window | `hudUpdate` runs only in rasters `HUD_SAFE_LO=56..HUD_SAFE_HI=200`, from the idle spin, not the per-frame block; `hudUpdWrapped` must stay 0 | `hud.asm:106-125`, `hudUpdate` |
| HUD logical inputs | `hudLives` 0..5, `hudUpgrade` 0..3, `hudHeatLo/Hi` 0..300, `hudScore[6]` decimal digits MSD first, `hudDirty` bits | `hud.asm:129-145` |
| Pages / pointers | `SCREEN_A=$0400`, `SCREEN_B=$2800`, pointer tables `$07f8`/`$2bf8`; exactly two pointer-writing instructions (`exPtrStore`, `huPtrStore`), both patched from the frame record in `exFrame`; only the adopted page's table is written | `renderer.asm` `exFrame`, `test_engine.py:source_invariants` |
| Aperture | blank charset `$3800` (2 KB zeros, also `$3fff` idle byte); real charset `$1000` (ROM); `$d018` A/B real `$14`/`$a4`, blank `$1e`/`$ae`; visible terrain rasters 55..247; RSEL=0; matrix rows 0 and 24 carry terrain | `main.asm:26-102`, `exTop`, `exBottom` |
| Scroller record | fine, `$d018` real+blank, pointer hi, page; `publishSkip` counts a record published while the previous was unadopted | `scroll.asm` |
| Direct VIC ownership | `$d000-$d010`,`$d015`,`$d017`,`$d01b-$d01d`,`$d027-$d02e`, pointer tables, `$d011`, `$d018` = `renderer.asm` only; `$d020`,`$d021`, colour RAM = boot once in `main.asm` | `test_engine.py:source_invariants` (regex over `src/*.asm`) |
| Memory | schedule/state at `$c000+` outside bank 0; code segments have growth guards (`* > $1800`, `$1a00`, `$1c00`, `HUD_SPRITES`) | each module tail |
| Deferred issue | RING-SLOW/RING-SHIFT ≈12 % `publishSkip`; not to be optimised against synthetic load | `ENGINE_CONTRACT.md §10` |

Two additional facts game code will depend on that are not in the contract document:

- [S] `sortTick` restates `sortedCount = logCount` every frame but never re-permutes `sortedIDs`; only `sortReset` (called by `loadFixture`) does. **If `logCount` shrinks, `sortedIDs[0..logCount-1]` can contain an ID ≥ `logCount`** and the builder will schedule a stale logical entry. Section 8 designs around this.
- [S] `hudScoreBump` (`hud.asm`) wraps `999999` → `000000` despite its comment saying it stops. The old `addScore` saturates at `SCORE_MAX`. Fix in Slice B with a pre-check.

---

## 3. Old-game architecture map

[S] All old code runs under the KERNAL (`$01` default, IRQ via `$0314`, `jmp $ea31/$ea81`), uses BASIC zero page `$2e-$36` as scratch (`variables.asm:23-33`), clears the screen with `$ffd2`. The new engine banks the KERNAL out (`$01=$35`) and vectors `$fffe` directly. None of that survives.

```
init (1030) ──► mainLoop router (1169)
                  ├─ GAME_STATE_MENU        attractMenu (1657): starfield + title/hiscore pages, fire → startGame
                  ├─ GAME_STATE_PLAYING     gameLoop (1194)
                  ├─ GAME_STATE_GAME_OVER   gameOverScreen (1349) → scoreQualifies (1375)
                  └─ GAME_STATE_ENTER_INITIALS enterInitialsScreen (1428) → insertHiscore (1568)

gameLoop per frame (1194-1273):
  waitForGameFrame ─ publishTurretGlyphs ─ applyFineScroll ─ swapRenderPlans ─ renderSprites ─ armFirstBatch
  finishBackgroundCoarse
  updateTurretStream ─ updateWaveTriggers ─ positionBackgroundTurrets ─ pulseTurretColour ─ updateTurretPressure
  updateEnemyHitEffects ─ updatePlayerCombatEffects ─ updateObjects ─ updateEnemyFire ─ updateBackgroundTurrets
  updatePlayerState ─ (endGame) ─ updateSpawner ─ updateBackgroundScroll
  buildSortedObjectList ─ sortObjectsByY ─ buildInitialSpriteSnapshot ─ buildBatchSpriteSchedule
  planCoarseBulletSuppression ─ predecodeNextStageRow ─ prepareBackgroundCoarse ─ noteCoarseSuppressionOutcome
  refreshHeatGaugeIfDirty ─ refreshScoreIfDirty
```

Layers, by ownership:

| Layer | Old files / labels | Verdict |
|---|---|---|
| Game states | `mainLoop`, `startGame`, `endGame`, `gameOverScreen`, `attractMenu`, `enterInitialsScreen`, `insertHiscore`, `seedHiscoreTable`, `formatHiscorePage` | behaviour keep, KERNAL/screen writes go |
| Player | `updatePlayer` (2348), `updatePlayerFire` (2418), `updatePlayerCombatEffects` (2690), `updatePlayerState` (4634), `PLAYER_*` state (5324-5332), player layers (9634-9849) | keep behaviour |
| Weapon | `tracePlayerCannon` (2480), `hitCannonTarget` (turrets 823), `damageEnemy` (2550), heat module (9874-10181) | keep |
| Enemies | `findFreeObject` (4842), `spawnEnemy` (4863), `updateSpawner` (4933), `moveEnemyPath` (3069), `easeVelocityTowardTarget` (3220), `accelerateEnemyDive` (3251), `updateEnemyHitEffects` (2715), `updateEnemyHealthSprite` (2580) | keep behaviour, drop health-sprite copy |
| Waves | `startRandomWave` (4787), `startAuthoredWave` (8534), `updateWaveTriggers` (8502), attack + fragment tables (5680-6152), `stage_waves.asm` | keep data |
| Bullets | `updateEnemyFire` (2809), `spawnEnemyBulletAt` (2888), `chooseEnemyBulletSlope` (2988), `moveEnemyBullet` (3005), encounter policy (7251-7440) | keep |
| Collision | `capturePlayerCollision` (4473), `checkEnemyPlayerOverlap` (4534), `checkBulletPlayerOverlap` (4584) | keep the two box tests, drop `$d01e` |
| Turrets | `background_turrets.asm` in full; `stage_turrets.asm` | keep behaviour, rewrite presentation hooks |
| Old renderer | `buildSortedObjectList`, `sortObjectsByY`, `buildInitialSpriteSnapshot`, `snapshotSpritePointer`, `buildClippedInitialSprite`, `buildBatchSpriteSchedule`, `swapRenderPlans`, `renderSprites`, `armFirstBatch`, `raster_scheduler.asm` in full, `hudBorderSetup`/`hudBorderHandoff` | discard |
| Old scroller | `initBackground` (6235), `renderStageRowToScreen`, `decodeStageCharacterRow` (6472), `updateBackgroundScroll` (6627), `prepareBackgroundCoarse` (6652), `finishBackgroundCoarse`, second-screen block (7472-8422), predecode (9000-9138), coarse stage 3 (9170-9278) | discard except the decoder |
| HUD | score module (9300-9603), heat gauge compose/publish (10039-10181), `hudProof*` tables | discard presentation, keep values |
| Diagnostics | `updateCycleDebug` (4190), `FORENSIC_RING`, `SUPPRESS_*`, `SS_*` stats, `POLICY_*` counters, 70 `tools/*.py` probes | discard |

---

## 4. Subsystem classification table

Categories: **A** reusable largely as-is · **B** reusable algorithm/data, rewrite integration boundary · **C** preserve behaviour, rewrite implementation · **D** obsolete/discard · **E** defer.

| # | Subsystem | Old source | Class | Reason |
|---|---|---|---|---|
| 1 | Game/main loop | `gameLoop` 1194-1273 | **D** | Every call in it is either renderer ownership (`renderSprites`, `armFirstBatch`, `swapRenderPlans`, coarse prepare/finish, suppression) or belongs to a module below. The new `mainLoop` frame-tick pattern (`main.asm:311-327`) is the loop. |
| 2 | Game-state machine | `mainLoop` router, `GAME_STATE_*`, `startGame`, `endGame` | **B** | Four-state router is fine. `endGame` tears down the IRQ chain and restores the KERNAL: forbidden; the renderer's IRQ chain is permanent. |
| 3 | Input | `updatePlayer` joystick read of `$dc00`, `waitFireRelease`, initials edge-detect | **A** | Plain `STICK_2` reads. Only hazard: fixture key scan writes `$dc00`; retire it. |
| 4 | Player state | `PLAYER_STATE_*`, `PLAYER_LIVES`, `PLAYER_STATE_TIMER`, `PLAYER_EXPLOSION_FRAME`, `PLAYER_BLINK_TIMER` | **B** | State lives in scalars, not the pool (good). Stored in `OBJECT_*[0]` for position: move to a dedicated player struct. |
| 5 | Player movement | `updatePlayer` 2348-2416 | **B** | 1 px/frame, no momentum (there is none implemented; "acceleration/momentum where implemented" = not implemented). Bounds `X 23..321`, `Y 55..237`. `PLAYER_MAX_Y` must become 226 (`MAX_SPRITE_Y`). |
| 6 | Player sprite presentation | `OBJECT_SPRITE[0]`/`OBJECT_COLOUR[0]` writes, `playerLayer*` 9634-9849, `PLAYER_LAYER_COUNT=2` | **C** | Two co-located hires layers is exactly HW0+HW1. Everything about how they reached hardware (sorted-list packing, `BATCH_MODE_MASK`, `PLAYER_HW_MASK`) is discarded. |
| 7 | Player death/explosion | `updatePlayerState` `!beginExplosion`…`!explosion4` | **B** | 4 bitmaps × `PLAYER_EXPLOSION_HOLD=5` frames, colours 7/8/2/9. Writes `OBJECT_SPRITE`: becomes player-record pointer writes. |
| 8 | Invulnerability/blink | `!startRespawn`, `!respawning` | **B** | `PLAYER_RESPAWN_TIME=100`, blink = bit 2 of a free-running counter (4 on / 4 off), collision ignored while `PLAYER_STATE != ALIVE`. |
| 9 | Player weapon/fire | `updatePlayerFire`, `tracePlayerCannon`, `hitCannonTarget` | **A** | Pure logical hitscan over `OBJECT_*`: two rays at `X+4` and `X+19`, nearest target above player with `0 ≤ rayX-enemyX < 24`, `PLAYER_FIRE_COOLDOWN=8`, `PLAYER_MUZZLE_TIME=3`. |
| 10 | Heat/cooling | `updateWeaponHeat` 9964-10037, `resetWeaponHeat` | **B** | Constants `HEAT_MAX=300`, `HEAT_REENABLE=150`, `+2/-3` per frame, exact 3.0 s / 1.0 s / 2.0 s timings. Strip the compose/publish half; feed `hudHeatLo/Hi`. |
| 11 | Score | `addScore`, `awardKillScore`, `SCORE_LO/MID/HI`, `convert24to6` | **C** | New HUD already holds six decimal digits. Make the digit array canonical; drop 24-bit binary and the seven-phase converter. Keep saturation. |
| 12 | Lives | `PLAYER_LIVES`, `PLAYER_START_LIVES=3`, `displayLives` | **B** | One byte; feed `hudLives`. |
| 13 | Upgrades | none implemented (constants only) | **E** | Feed `hudUpgrade=0`. |
| 14 | Logical object pool | `OBJECT_*` 5176-5209, `findFreeObject`, `MAX_OBJECTS=16`, slot 0 = player | **B** | Layout is sound. Remove presentation fields (`OBJECT_SPRITE`, `OBJECT_COLOUR`) from the canonical struct; player leaves the pool. See §8. |
| 15 | Enemy lifecycle | `spawnEnemy`, `updateEnemyHitEffects`, `damageEnemy` | **B** | `ENEMY_START_HEALTH=6`, hit flash 4 frames white→yellow→base, death 12 frames over 3 explosion frames, `awardKillScore` on release. |
| 16 | Enemy spawning | `updateSpawner` 4933-5028 | **A** | Atomic wave, `SPAWN_TIMER`/`WAVE_GAP_TIMER=150`, per-member `WAVE_ADD_X/Y` 9-bit offsets, pool-full retry. Only the `TURRET_PRESSURE_ACTIVE` gate reads outside the pool. |
| 17 | Wave/formation definitions | `attack*` tables 5680-5813, `randomAttackMap`, `stage_waves.asm` | **A** | Twelve curated attacks: interval, start X (9-bit), start Y, add X/Y, ingress/manoeuvre/egress IDs, four visual sets. Assemble-time join-compatibility guard 6127-6151 is worth keeping verbatim. |
| 18 | Enemy movement patterns | `moveEnemyPath`, fragments 5895-6122, `easeVelocityTowardTarget`, `accelerateEnemyDive` | **A** | 3-byte segments `(duration, vx, vy)`, `$ff` coast, `0` stage handoff, ease 1 unit/frame, dive accel every 12 frames capped at 3. Reads only `OBJECT_*`. |
| 19 | Sorting | `buildSortedObjectList`, `sortObjectsByY` | **D** | New `sorter.asm` is the persistent Y sort. The old collect step's *visibility filter* concept (Y 35..246) is replaced by admission bounds. |
| 20 | Old renderer/render plan | `buildInitialSpriteSnapshot`, `buildBatchSpriteSchedule`, `LIVE_PLAN/BUILD_PLAN`, `INITIAL_*`, `ASSIGN_*`, `BATCH_*` | **D** | Replaced by `buildSchedule`/`sched*`. |
| 21 | Old sprite multiplexer | `applyLiveRasterBatch`, `SLOT_FREE_RASTER` greedy allocator, 8-slot model | **D** | Eight-slot greedy with `Y+24` reuse; the new engine's 6-slot round robin with `MIN_REUSE_GAP=33` is the qualified model. |
| 22 | Raster IRQ code | `raster_scheduler.asm` entire (`rasterIRQ`, `dispatchRasterEvents`, `borderOpenHook`, `edgeMaskOpenHook`, forensic ring) | **D** | Replaced by `irqHandler` phases. The RSEL dodge and ECM masking it contains are superseded by the blank-charset aperture. |
| 23 | Sprite pointer handling | `HW_SPRITE_POINTER,x` in `renderSprites`, `ssBatchPtrStore` self-modified hi byte, `$2bf8` dual writes in `hudBorderSetup`/`hudBorderHandoff`/`ssMirrorSpritePtrs` | **D** | The dual-page "write both to be safe" pattern is exactly what §7 of the contract forbids. |
| 24 | Screen/page handling | `ssFlipPage`, `ssSelectPageA`, `ssInactiveBuild*`, `BG_ACTIVE_PAGE`, `ssActiveHiDelta` | **D** | The new frame record owns pages. |
| 25 | Scroller | `updateBackgroundScroll`, `prepareBackgroundCoarse`, `finishBackgroundCoarse`, predecode, coarse deadlines | **D** for machinery, **B** for semantics | Keep: `SCROLL_FRAME_DIVIDER=2`, 16-bit world row, bottom-origin start `STAGE_START_ROW = STAGE_LOGICAL_ROWS-23`, wrap-to-start with trigger/turret rewind. All of it becomes parameters of the new scroller. |
| 26 | Collision architecture | `capturePlayerCollision` (`$d01e` broad phase + `PLAYER_HW_MASK`, run from the IRQ), `DEBUG_PLAYER_INVULNERABLE` | **D** for `$d01e`/mask/IRQ placement; **A** for the two box tests | See §10. |
| 27 | Enemy damage/death | `damageEnemy`, `updateEnemyHealthSprite` | **B** / **D** | Damage and death: B. The per-enemy private 64-byte health-bar bitmap copy (`HEALTH_SPRITE_BASE=$3000`, self-modifying copy): D. Health feedback becomes a colour flash only, or a shared per-HP bitmap set later (E). |
| 28 | Player damage/death | `PLAYER_HIT` latch → `updatePlayerState` | **B** | Latch-then-consume order is good; the latch will now be set by software collision in the main thread. |
| 29 | Enemy bullets | `updateEnemyFire`, `spawnEnemyBulletAt`, `chooseEnemyBulletSlope`, `moveEnemyBullet`, shooter budget | **A** | Complete and working: cap 3, interval 42, `vy=3`, `vx ∈ {-2..2}` by distance thresholds 24/72, CIA-seeded scan start. `planCoarseBulletSuppression` (6989) is renderer coupling and is D. |
| 30 | Turret logic | `updateTurretStream`, `admitTurretSlot`, `updateBackgroundTurrets`, `traceTurretCannon`, `hitCannonTarget`, `markTurretDestroyed` | **B** | World-row streaming pool of 8, health 3, fire interval 100, combat window Y 72..231, fire window 88..200 with the player below. Reads `SCROLL_ROW`, `RASTER_DISPLAY_FINE` and `SORTED_COUNT` (the latter is a `TURRET_FIRE_NO_MITIGATION` gate: D). |
| 31 | Turret presentation | `installTurretRow`, `publishTurretGlyphs`, `restoreDeadTurretCells`, `pulseTurretColour`, `paintTurretCells`, `cacheTurretGroundCodes` | **C** | Glyph install belongs in the new back-page row renderer. Displayed-page pokes and per-frame colour-RAM painting need the bounded window treatment of §12. |
| 32 | Level/stage data | `stage_config.asm`, `stage_test.asm` (metatile defs + rows), `stage_charset.asm`, `decodeStageCharacterRow` | **A** data, **B** decoder | 4×4 metatiles, 10 per row, 16-bit row arithmetic. The decoder writes `BG_INCOMING_ROW`; re-target it at the regen row buffer. |
| 33 | Editor/export ABI | `tools/level_editor/*`, `ka_export.py` | **E** | Per the stated strategy. §12 states the runtime contract the exporter must later target. |
| 34 | HUD logic | `SCORE_*`, `PLAYER_LIVES`, `WEAPON_HEAT_*`, `WEAPON_OVERHEATED`, `HEAT_FLASH_*` | **B** | Values feed `hud*` fields. |
| 35 | HUD presentation | `hudBorderSetup`, `hudBorderHandoff`, `composeScoreSprites`, `publishScoreBuffer`, `composeHeatGauge`, `publishHeatBuffer`, `hudProofPtr` | **D** | `hud.asm` + `exHud` already do this correctly. Overheat flash (alternating gauge colour) is C: one byte into `hudCol`. |
| 36 | Timing/profiling | `updateCycleDebug`, `displayCycleMinimum`, `DEBUG_*`, coarse-defer counters | **C** | Replace with two counters in the new style: main-thread end-raster max and overrun count (§14). |
| 37 | Debug/diagnostics | `FORENSIC_RING`, `SS_*`, `SUPPRESS_*`, `POLICY_*`, `PLAYER_BUNDLE_SHORT`, `tools/vice_*.py` | **D** | Tied to old symbols and old failure modes. `POLICY_MAX_*` peak gauges are worth re-creating as engine-style saturating counters. |
| 38 | Audio | none | — | No SID code exists in the old repo (`$d400` reference at 1997 is the character ROM copy). |
| 39 | Attract starfield | `setupStarfieldCharset`, `updateStarfield`, `starGlyphData` | **E** | Per-cell screen writes and a charset copy; needs page-aware rewrite. Cosmetic; last. |
| 40 | High-score table/initials | `seedHiscoreTable`, `scoreQualifies`, `insertHiscore`, `enterInitialsScreen`, `drawInitialsScreen` | **B** | Logic fine; drawing via `$ffd2`/`drawTextRow` to `$0400` only is D. Compare on 6-digit arrays, not 24-bit. |
| 41 | Encounter policy | `initEncounterPolicy`, `updateTurretPressure`, `refreshShooterBudget`, `shooterEligible`, `countActiveEnemies` | **A** | Pure gameplay policy over `OBJECT_*`/`TURRET_*`. `NORMAL_WAVE_SIZE=5`, budgets 2/1, `TURRET_PRESSURE_MAX_Y=180`. |

---

## 5. Dangerous coupling / dependency map

Every item below was located by grepping the old source for VIC, CIA, page and plan symbols (`variables.asm` aliases included).

### 5.1 Systems that write VIC registers or VIC-visible memory

| Old site | Registers | What replaces it |
|---|---|---|
| `init` 1030-1062 | `$dd00`, `$d018`, `$d011`, `$d020`, `$d021`, `$3fff/$39ff` idle bytes | new boot in `main.asm:entry` |
| `setupSprites` 2268-2283 | `$d015`, `$d01c=$ff`, `$d025=$0b`, `$d026=$0f`, `$d017`, `$d01d`, `$d01b` | handoff owns all of these; **multicolour decision** |
| `renderSprites` 4343-4441 | `$07f8,x`, `$d027,x`, `$d000/$d001,y`, `$d010`, `$d015`, `$d01c` via `playerLayerModeInitial` | batch 0 in `exHandoff` |
| `applyLiveRasterBatch` (rs 846-895) | `$07f8,x` self-modified hi, `$d027`, `$d000/1`, `$d010`, `$d01c`; **reads `$d01e` and calls `checkCapturedPlayerCollision` from the IRQ** | mid-screen batches; collision → main thread |
| `hudBorderSetup` 8605-8672 | `$07f8+4..7`, `$2bf8+4..7` unconditionally, `$d027`, `$d000/1`, `$d015`, `$d01c`, `$d010` | `exHud` |
| `hudBorderHandoff` 8678-8757 | same set for slots 4..7, plus `PLAYER_HW_MASK` accumulation | `exHandoff` |
| `rasterFrameReset`, `publishRasterPlan`, `borderOpenHook`, `edgeMaskOpenHook` | `$d011` (RSEL dodge, ECM band), `$d016`, `$d022/$d023`, `$d012`, `$d019/$d01a`, `$0314` | `exFrame`, `exTop`, `exBottom`, `installRenderer` |
| `ssFlipPage`, `ssPublishCoarseFlip`, `ssSelectPageA` 7522-8378 | `$d018` mid-frame, `$2bf8` mirror | frame record + `exFrame` |
| `initBackground` 6235-6386 | `$d016` MCM, `$d021/$d022/$d023`, colour RAM fill, charset copy to `$3b00`, 25-row matrix fill on `BG_ACTIVE_PAGE` | boot-time palette + stage init through `regenAll` |
| `endGame` 1276-1335 | `$d01a`, `$d019`, `$0314`, `$dc0d`, `$d015`, `$d010`, `$d011`, `$d016`, `$d022/3`, `$d021`, `$d018` via `ssSelectPageA` | nothing: state changes must not touch the VIC |
| `publishScoreBuffer`, `publishHeatBuffer`, `resetWeaponHeat`, `refreshHeatGaugeIfDirty` | `hudProofPtr`/`hudProofColour` under `sei/cli` | `hudPtrLive`/`hudCol` single-byte writes, no `sei` |
| `pulseTurretColour`/`paintTurretCells`, `restoreDeadTurretCells`, `copyIncomingRowToScreen` | colour RAM `$d800+row*40+col`, screen RAM of the displayed page | §12 bounded-window rule |
| `updateEnemyHealthSprite` 2580 | writes sprite bitmap RAM `$3000+id*64` (VIC-fetched) at arbitrary raster | D |
| `buildClippedInitialSprite` 3629 | writes `CLIP_SPRITE_POOL $3400` | D |

### 5.2 Systems that assume a hardware slot

- `PLAYER_HW_MASK` (5324) built in `renderSprites`/`hudBorderHandoff`/`extendRasterPlanMasks`, consumed by `capturePlayerCollision`. The player had *no* fixed slot; the mask chased it. In the new engine the player has fixed slots 0/1 and no mask is needed.
- `HUD_SLOT_FIRST=4`, `SLOT_FREE_RASTER[4..7]` floor at `HUD_HANDOFF_COMPLETE_RASTER=56`, `BATCH_MODE_MASK` hires-below-handoff logic (`buildBatchSpriteSchedule` 3742-4043). All D.
- `BORDER_MARKER_SLOT=7` (rs 33). D.
- `TURRET_FIRE_NO_MITIGATION` gate on `SORTED_COUNT >= 8` (turrets 720-723): a gameplay rule that exists only because the old 8-slot allocator could not place a ninth sprite. **Do not port**; the new admission rule makes it meaningless.

### 5.3 Systems that depend on old screen-page addresses

`LIVES_SCREEN`, `GAME_OVER_SCREEN`, `MENU_TITLE_SCREEN`, `HISCORE_HEADING_SCREEN`, `INITIALS_*_SCREEN`, `DEBUG_SCREEN`, `starRowLo/Hi` (`$0400`-relative), `cramRowLo/Hi`, `drawTextRow` self-modified stores, `bgScreenB`. All assume page A at `$0400` is displayed. In the new engine either page may be on screen; all text must go through the page-aware row renderer (§11.4).

### 5.4 Systems that depend on old object-array layout

Everything gameplay-side indexes `OBJECT_*` by logical slot with `X` — that is fine and stays. Two hidden dependencies: (a) `SORTED_OBJECTS` packs the player layer index into the high nibble (`SORTED_LAYER_MASK`) and `sortObjectsByY`/`buildInitialSpriteSnapshot`/`buildBatchSpriteSchedule` all mask it: D. (b) `OBJECT_SPRITE`/`OBJECT_COLOUR` double as gameplay state machines (muzzle flash restores `playerSprite/64`; blink writes `blankSprite/64`; hit flash writes colour 1/7). These become render-intent fields of the game struct (§8).

### 5.5 Systems that depend on old renderer sort order

`planCoarseBulletSuppression` (reads `BATCH_RASTER`, `ASSIGN_OBJECT`), `playerLayerAudit`, `updateTurretPressure`'s `POLICY_MAX_SORTED`, the turret fire gate above. All D.

### 5.6 Collision logic that depends on slot identity

`capturePlayerCollision`/`checkCapturedPlayerCollision`: `lda $d01e / and PLAYER_HW_MASK`. Also called from **inside** `applyLiveRasterBatch` (IRQ) on every batch, reading mutable `OBJECT_X/Y` (the old Astra review flagged this as a 14-line early-frame slip). D.

### 5.7 Gameplay timing that depends on IRQ cadence rather than logical frames

- `waitForGameFrame`/`waitForFrameStart` poll raster bit 8 and `RASTER_PRESENT_READY`: replaced by the `frameCounter` tick.
- `updateWeaponHeat` is deliberately placed *after* coarse admission because of a pre-coarse budget; that constraint vanishes. Its cross-frame latch order (fire at N, heat at N, lock read at N+1) is a logical-frame property and survives.
- `refreshScoreIfDirty` spreads conversion over 7 frames for budget reasons: vanishes with decimal-digit score.
- `TURRET_Y` is derived from `RASTER_DISPLAY_FINE` (presented fine phase): becomes `scrollFine` of the frame being built.

### 5.8 Hidden coupling to diagnostics or fixtures

- `DEBUG_PLAYER_INVULNERABLE` compile-time switch in the collision path: keep as a build flag, harmless.
- `POLICY_DIAG` counters inside `updateSpawner`/`shooterEligible`: strip or convert to saturating bytes.
- `#define OPT_THREE_LAYER_PLAYER` threads through `buildSortedObjectList`, sort, snapshot, batch, masks, HUD handoff: D.
- `SUPPRESS_*`, `SS_*`, `COARSE_*`, `EDGE_MASK_*`, `RASTER_BORDER_*`: D.
- `initEncounterPolicy` is called from `startGame`; the test fixtures call `countActiveEnemies` directly: keep the routine, drop the fixture contract.

### 5.9 Data tables that are genuinely portable

`attackEnemyCount`, `attackInterval`, `attackStartXLo/Msb/Y`, `attackAddX/Y`, `attackIngressId/ManoeuvreId/EgressId`, `attackSpriteStart`, `enemySpriteSequence` (as indices, not pointers), `enemyColourSequence`, `randomAttackMap`, `ingressStartOffset`/`ingressFragments`, `manoeuvreStartOffset`/`manoeuvreFragments`, `egressStartOffset`/`egressFragments`, the three entry/exit class lists and the join guard, `healthBarByte*` (if a bar is ever wanted), `heatGaugeWidth` (already `heatPix` in the new HUD), `waveTrigger*`, `turretCols/Rows`, `turretArt`, `turretPulseTable`, `metatileDefs`, `stageMetatileRows`, `terrainGlyphs`, `scoreFont` (only if the new 8-px digit font is rejected), `starGlyphData` (E). Sprite bitmaps are portable **only after the multicolour decision**.

---

## 6. Portable gameplay data and algorithms

Grouped by what to copy byte-for-byte versus what to re-express.

**Copy verbatim (A):**

- Attack catalogue `main.asm:5722-5813`, 12 attacks. Keep the `.var List()` form and the three compile-time guards (`5860-5893`, `6127-6151`).
- Movement fragments `5895-6122`: 6 ingress, 9 manoeuvre, 3 egress fragments, 3-byte segments, `$ff` coast, `0,0,0` terminator.
- `moveEnemyPath` + `setFragmentPointer` + `easeVelocityTowardTarget` + `accelerateEnemyDive` (3069-3318). Needs a zero-page pointer (`FRAG_PTR` was `$f9/$fa`; `$f9/$fa` are free in the new engine, which uses only `$fb-$fe`).
- `updateSpawner` (4933-5028), `spawnEnemy` (4863-4931) minus the four `OBJECT_SPRITE/COLOUR/BASE_*` stores.
- `tracePlayerCannon`, `updatePlayerFire` cadence and cannon offsets, `hitCannonTarget` dispatch on bit 7 (turret vs enemy).
- Bullet trio (2809-3067) and `chooseEnemyBulletSlope`.
- `checkEnemyPlayerOverlap`, `checkBulletPlayerOverlap` (4534-4632). Note the bullet box is 8×8 at sprite origin, matching `enemyBulletSprite`.
- Encounter policy (7270-7438).
- Turret world logic: `updateTurretStream`, `turretRelInWindow`, `admitTurretSlot`, `markTurretDestroyed`/`turretIsDestroyed`, `positionBackgroundTurrets` (with `RASTER_DISPLAY_FINE` → `scrollFine`), `updateBackgroundTurrets` minus the `SORTED_COUNT` gate, `traceTurretCannon`, `hitCannonTarget`.
- `updateWeaponHeat` accumulator (9964-10037) verbatim; the function is pure over `WEAPON_HEAT_*`, `WEAPON_OVERHEATED`, `PLAYER_FIRE_COOLDOWN_TIMER`.
- `updatePlayerState` (4634-4785) with `OBJECT_SPRITE`/`OBJECT_COLOUR` writes redirected.
- `wrapBgLogicalRow`, `decodeStageCharacterRow` (6423-6590).
- `updateWaveTriggers`, `startAuthoredWave`, `initWaveTriggers` (8495-8579), subject to the direction decision (the compare is `SCROLL_ROW <= trigger row`, descending).
- `scoreQualifies`/`insertHiscore` shape, re-typed to 6 digits.

**Constants worth a single `game_constants.asm`:** every `.const` in `main.asm:520-990` under player, weapon, heat, enemy, wave, turret, encounter, score, lives, game-over, attract; and `background_turrets.asm:32-45`.

**Re-express (B/C):**

- `spritePointers`/`enemySpriteSequence` hold `label/64` pointer values into old bank-0 art at `$2400`. Re-express as **art indices** and map to the new sprite block once art placement is fixed.
- `OBJECT_HEALTH` visual: a colour flash only in the first pass.
- Score as `hudScore[6]`.

---

## 7. Code that should be discarded

Explicitly, so nobody argues them back in:

1. `raster_scheduler.asm` in its entirety, including `dispatchRasterEvents`'s "near target wait", the `RASTER_PRESENT_READY` replay path that calls `renderSprites` **from the IRQ**, `borderOpenHook`'s RSEL dodge, `edgeMaskOpenHook`'s ECM band, `FORENSIC_RING`.
2. The whole BUILD/LIVE plan (`LIVE_PLAN`, `BUILD_PLAN`, `INITIAL_*`, `ASSIGN_*`, `BATCH_*`, `RENDER_COUNT`, `SLOT_FREE_RASTER`, `swapRenderPlans`, `renderSprites`, `armFirstBatch`, `beginRasterPlanMasks`, `extendRasterPlanMasks`).
3. `buildBatchSpriteSchedule`'s eight-slot greedy allocator and its `Y-12` deadline / `Y+24` reuse constants. The new engine's `REUSE_LEAD=12`/`MIN_REUSE_GAP=33` were measured; the old numbers were not.
4. `buildInitialSpriteSnapshot`, `snapshotSpritePointer`, `buildClippedInitialSprite`, `CLIP_SPRITE_POOL`, `CLIP_SHADOW_*`, `CLIP_FULL_REBUILD_BUDGET`.
5. All second-screen code `7472-8422` (`ss*`), `legacyPageB*`, `shiftBackground*`, `saveCrossingRow`/`restoreCrossingRow`, `prepareBackgroundCoarse`, `finishBackgroundCoarse`, `predecodeNextStageRow`, `bgConsumePredecodedRow`, `bgCoarseHitGuaranteed`, the three coarse-deadline gates and every `COARSE_*`/`SS_*`/`BG_PREDECODE_*` counter.
6. `planCoarseBulletSuppression`/`noteCoarseSuppressionOutcome` (presentation-driven omission of a live projectile).
7. `hudBorderSetup`, `hudBorderHandoff`, `hudProofPtr/X/XMsb/Colour`, `HUD_SPRITE_BASE`, `composeScoreSprites`, `publishScoreBuffer`, `refreshScoreIfDirty`, `renderScoreHud*`, `convert24to6`, `convertScorePlace`, `scoreFont`, `composeHeatGauge`, `publishHeatBuffer`, `heatFillB*`, all `sei`/`cli` pairs around HUD pointer writes.
8. `capturePlayerCollision`'s `$d01e` read and `PLAYER_HW_MASK`; the IRQ call site in `applyLiveRasterBatch`.
9. `updateEnemyHealthSprite` and `healthSpritePool` (`$3000-$33ff`): a self-modifying 64-byte copy into VIC-fetched RAM at an unbounded raster.
10. `OPT_THREE_LAYER_PLAYER` plumbing: `playerLayerEmit/Snapshot/Assign/ModeInitial/Audit`, `SORTED_LAYER_MASK`, `BATCH_MODE_MASK`.
11. `setupSprites` (global `$d01c=$ff`, `$d025/$d026`), `endGame`'s VIC/IRQ teardown, `init`'s `$dd00`/`$d018` setup, `$ffd2` clears, `$ea31/$ea81` chaining, `$0314` vector, BASIC zero-page scratch `$2e-$36`.
12. `updateCycleDebug`/`displayCycleMinimum`/`HUD_FREE_*` glyphs, `initFixedHud`, `fixedHudText`.
13. `TURRET_FIRE_NO_MITIGATION` gate; `SS_TURRET_RECONCILE_*`; `ssReconcileTurretsOnNewPage`.
14. Every `tools/vice_*.py`, `tools/check_*.py`, `run_regression_suite.sh` (they read old symbols and old failure signatures). The **method** of `vice_weapon_heat_timing.py`, `vice_player_collision_check.py`, `vice_wave_cadence_probe.py`, `vice_encounter_fixtures.py` is worth re-deriving on the new harness (`tests/test_p0.py` `Monitor`/`free_run`).
15. `#define` toggle forest at `main.asm:1-270`. The new repository's rule is one architecture, no modes.

No exception is justified for any of the above. The one old *mechanism* that deserves a second look later is the top-clipped emergence bitmap (item 4): its behaviour (enemies emerging through the aperture one pixel at a time) is worth preserving, but its implementation must be a main-thread bitmap preparation with a fetch-window rule like `hudUpdate`, not a plan-indexed pool. That is E, not A.

---

## 8. Proposed logical game-object model

### 8.1 Gameplay state (canonical, owned by game code)

[R] One struct-of-arrays pool, `GAME_POOL = 16` entries, **player excluded** (the player has its own record, §9). Indexed by logical ID 0..15 with `X`. Outside bank 0 (`$c500+` is free after the ring state retires; or anywhere in `$4000-$bfff`).

```
objActive     0/1
objType       ENEMY=2, BULLET=3           (TYPE_PLAYER retired from the pool)
objX, objXHi  9-bit world X (screen X; the world does not scroll horizontally)
objY          screen Y, 0..255            (world Y is not needed: enemies fly in screen space)
objVelX, objVelY, objTgtVelX, objTgtVelY  signed
objStage, objPathStep, objPathTimer, objManoeuvreStep, objEgressStep, objAccelTimer
objPattern    attack ID (debug/scoring hook)
objHealth
objHitTimer, objDeathTimer
objArt        art index (enemy visual, explosion frame, bullet) – render intent, NOT a pointer
objColBase    formation colour
objFlash      0 = base colour, else colour override this frame (hit flash, death colours)
```

Compared with the old `OBJECT_*` set: `OBJECT_SPRITE`, `OBJECT_COLOUR`, `OBJECT_BASE_SPRITE` are gone (replaced by `objArt`, `objColBase`, `objFlash`), nothing else is added. Collision class is derived from `objType`; score value from a per-type table. Do not add fields until a slice needs them.

### 8.2 Render state (owned by the renderer's input arrays)

`logCount`, `logY[]`, `logX[]`, `logXHi[]`, `logPtr[]`, `logCol[]` in `motion.asm:69-77`, unchanged.

### 8.3 Emit: gameplay → render, once per frame

[R] Fixed 1:1 mapping, `logCount = GAME_POOL` always:

```
for i in 0..GAME_POOL-1:
    if objActive[i]:
        logY[i]   = objY[i]
        logX[i]   = objX[i];  logXHi[i] = objXHi[i]
        logPtr[i] = artPtr[objArt[i]]          // table: art index -> VIC pointer value
        logCol[i] = objFlash[i] ? objFlash[i] : objColBase[i]
    else:
        logY[i]   = 0                          // PARKED: rejected by admission, counted in statRejRange
```

Why parking instead of compaction: [S] `sortedIDs` persists across frames and is only re-permuted by `sortReset`. A compacting emit changes every ID each frame, defeats the O(N+inversions) argument in `sorter.asm`, and can leave a stale ID ≥ `logCount` in the sorted prefix when the count shrinks. Parking keeps IDs stable for the life of an object slot, keeps `sortedIDs` a permutation of 0..15 forever, and costs the builder 16 range checks per frame (a few hundred cycles). Parked entries all have Y=0, tie-break by ID, so they never move in the sort. Call `sortReset` once at game start and `logCount=16` once; never touch either again.

`statRejRange` will read non-zero on every frame; the contract already says it is "NOT a fault". A test that asserts it is zero on game scenes would be wrong and must not be written.

Off-screen enemies (Y < 55 during ingress, Y > 226 after egress) are rejected the same way, which is the intended visibility cull: [S] "if culling is ever added it belongs BETWEEN motion and sorting" — the emit step is exactly that place, and parking is the cull.

### 8.4 Order per frame (game version of `mainLoop`)

```
frame tick (frameCounter changed)
  input                     joystick snapshot
  gameTick                  waves, spawn, enemy paths, bullets, turrets, player, weapon, collision, damage, score
  playerEmit                player record -> schedule input
  objectEmit                pool -> logY/logX/logPtr/logCol
  sortTick / buildSchedule / publishSchedule      (unchanged engine)
  hudFeed                   lives/heat/score/upgrade -> hud* + hudDirty
  regenTick / scrollTick    (unchanged engine; scrollTick gains the divider and direction)
idle spin
  hudUpdate                 (unchanged)
```

Nothing in `gameTick` reads `sched*`, `frame*`, `sortedIDs`, `dispPage`, or any VIC register except `$dc00` for input and `$d012` for the diagnostic in §14.

---

## 9. Player integration architecture

**Should player state live outside the pool?** Yes. [S] The old game already kept all player state in scalars (`PLAYER_*`) and used pool slot 0 only for X/Y/sprite/colour. [R] Player record:

```
plyX, plyXHi, plyY
plyState (ALIVE/EXPLODING/RESPAWNING/GAME_OVER), plyStateTimer, plyExplosionFrame, plyBlinkTimer
plyFireCooldown, plyMuzzleTimer, plyLives
plyArtBase, plyArtOverlay        art indices for HW0 / HW1
plyColBase, plyColOverlay
plyVisible                       0/1: blink and post-death hide
```

**How HW0/HW1 are fed.** [R] Add a **player block to the published schedule** so it obeys the same adoption rule as everything else:

```
schedPlyX, schedPlyXHi, schedPlyY, schedPlyPtr0, schedPlyPtr1, schedPlyCol0, schedPlyCol1,
schedPlyEnable (bits 0..1), schedPlyD010 (bits 0..1)          — all [2] double-buffered
```

`buildSchedule` copies them from the player record into `schedNext` (main thread), and:

- `exHud` (raster 4) programs `$d000/$d001/$d002/$d003`, `$d027/$d028` and the two pointers through a third patched pointer store (`plPtrStore`, patched by `exFrame` exactly as `exPtrStore` and `huPtrStore` are), then writes `$d010 = HUD_D010 | schedPlyD010` and `$d015 = HUD_ENABLE | schedPlyEnable`. A separate two-slot loop reading the CURRENT player block is cleaner than widening the HUD tables, because the HUD tables are constants and the player block is per-frame state.
- `exHandoff`'s final store becomes `$d015 = schedEnable | schedPlyEnable`; every `batchD010` is built as `bs_d010 | schedPlyD010` (initialise `bs_d010` from it instead of 0).
- `exFrame` still writes `$d015=0` at 250. The player's Y is ≥ 55 by construction, so its Y compare cannot match on PAL lines 256..311 and the ghost rule is unaffected. [U] Confirm with `hudExitMax < 17` and `handoffExitMax < 53` still holding after the extra stores; the raster-4 phase has fourteen lines of margin, the handoff gains nothing.

Why raster 4 and not batch 0: [S] `handoffExitMax` measured up to 51 against `TOP_ARM_LINE=53`. Two more entries in batch 0 would spend most of that margin. `exHud` has room.

This is the only renderer change the player needs. It keeps "one writer per register", keeps the pointer write count at three instructions all in `renderer.asm` (update `test_engine.py`'s "exactly two" check to three, deliberately), and keeps HW0/HW1 out of the mux.

**Which old player sprite/layer behaviour is reusable?** The two-layer hires design (`PLAYER_LAYER_COUNT=2`, `playerLayer0/1` at `main.asm:9828-9842`, "no pixel set in more than one layer"). The bitmaps are diagnostic placeholders; the *concept* — hull in the per-sprite colour on HW0, highlight on HW1, both hires, co-located — is the intended production shape. The old muzzle-flash colour swap (`PLAYER_COLOUR_MUZZLE=2` for 3 frames) becomes `plyColBase`.

**Invulnerability/blink.** `plyVisible` toggles on bit 2 of `plyBlinkTimer` (old: 4 on / 4 off) and drives `schedPlyEnable` to 0 or `%11`. No pointer to `blankSprite`, no register write from game code.

**Death/explosion.** `plyArtBase = explosion frame n`, `plyArtOverlay = blank` (or same frame in a second colour), `schedPlyEnable = %01` during explosion; after the last frame `plyVisible=0` until respawn. Frame timings from `PLAYER_EXPLOSION_HOLD=5`.

**Collision.** Software, in the main thread, against the pool (§10). No `$d01e`.

**Bounds.** `PLAYER_MAX_Y` becomes `MAX_SPRITE_Y=226` (was 237); `X 23..321` unchanged; `MIN_Y=55` unchanged. The visible difference is 11 pixels of downward travel; the old value relied on the open lower border showing sprites below the aperture, which the contract forbids.

---

## 10. Collision architecture recommendation

**What the old code actually does.** [S] `capturePlayerCollision` (4473) reads `$d01e` once per frame at the top of `renderSprites`, and `applyLiveRasterBatch` reads it again on every mid-screen batch from inside the IRQ. If any bit in `PLAYER_HW_MASK` is set, it scans slots 1..15 and runs a software 24×21 (enemy) or 8×8-vs-24×21 (bullet) box test against `OBJECT_X/Y[0]`, then latches `PLAYER_HIT`. Enemy-vs-player-fire is entirely software (`tracePlayerCannon`). So the hardware register was only ever a broad phase for one pair type.

**Why it must not survive.** Three reasons, any one sufficient:

1. Slot identity is time-multiplexed on HW2..HW7; the old `PLAYER_HW_MASK` chase is what made `$d01e` interpretable. The player is now fixed at HW0/HW1, so bits 0/1 *would* be stable — but HW0 and HW1 are co-located, and any overlapping pixels between base and overlay set bits 0 and 1 every frame. Production art will overlap. The signal is dead on arrival.
2. `$d01e` accumulates over the frame and clears on read; reading it from the IRQ (old) or at a raster-dependent point in the main thread makes the result depend on where the main loop is in the frame. The renderer contract has no place for a register read whose meaning depends on phase.
3. The broad-phase saving is small: the confirm scan is 15 iterations of a few loads and compares (≈ 1,500 cycles worst case). At 16 pool entries that is under 8 % of a frame and is bounded, which the old IRQ-side scan was not.

**Production architecture.** [R]

- `collideTick` in the main thread, after movement and before emit:
  - for each active enemy with `objDeathTimer == 0`: `checkEnemyPlayerOverlap` (verbatim) → `plyHit = 1`.
  - for each active bullet: `checkBulletPlayerOverlap` (verbatim) → `plyHit = 1`.
  - skip entirely unless `plyState == ALIVE` (old behaviour).
- Player fire remains the old hitscan (`tracePlayerCannon` + `traceTurretCannon`).
- Bullets vs enemies: none (old game has none; do not invent).
- Enemy vs turret: none.
- `DEBUG_PLAYER_INVULNERABLE` stays as an assemble-time flag on the latch store.

**Any residual role for VIC collision?** No. `$d01f` (sprite/background) is also unsuitable: with the blank charset outside the aperture and multicolour terrain inside, background collision would need per-glyph semantics the level format does not have. If a later design wants sprite/terrain collision it should read the decoded row buffer in the scroller, not the VIC.

---

## 11. Wave/enemy migration design

### 11.1 What is content

- **Formations:** `attackStartXLo/Msb/Y`, `attackAddX/Y`, `attackInterval`, `attackEnemyCount` (only as a data guard; runtime size is `NORMAL_WAVE_SIZE=5` or the trigger's count), `attackSpriteStart`, four visual sets in `enemySpriteSequence`/`enemyColourSequence`.
- **Timing:** `WAVE_GAP=150`, per-attack `attackInterval` 15..18, trigger-overridden `waveTriggerInterval`, `SPAWN_TIMER` semantics (0 = spawn now; interval 0 = same-frame chain), pool-full retry without advancing the member cursor.
- **Movement:** the ingress/manoeuvre/egress fragment tables, `ease` one unit per frame, dive acceleration every 12 descending frames capped at 3, exit rules: right edge `X ≥ 344`, left edge borrow from 0, Y overflow either way, egress `$ff` coast preserves momentum (the "continue final direction" behaviour), stage completion via `0,0,0`.
- **Per-enemy offsets:** `WAVE_ADD_X_VALUE`/`WAVE_ADD_Y_VALUE` accumulated per member (top entries `addY=0`, side entries `addY` 7 or 9 to avoid a raster wall).
- **Curated pairs:** attacks 9..11 as reuse examples; the `DIR_*` entry/exit masks and the assemble-time join guard.
- **Director:** authored triggers (`waveTrigger*`) with rewind on stage wrap; `randomAttackMap` as the fallback when a level has no triggers; turret-pressure hold on wave *start* only (never truncates a wave).

### 11.2 Representation in the new game

[R] Keep the exact byte formats. Put them in `src/game/waves_data.asm` (attack catalogue + fragments + visual sets) and let `src/generated/levelN/stage_waves.asm` stay as the trigger source. No scripting VM: the three-table fragment chain **is** the script and it is already data-driven with an assemble-time validator.

The one representational change: `enemySpriteSequence` entries become art indices 0..3 (A..D) instead of `label/64`; the emit step maps art index → pointer through a 16-entry `artPtr` table that also holds explosion frames and the bullet. Spawn writes `objArt`, `objColBase`; hit/death write `objFlash`/`objArt`.

### 11.3 Admission interplay (new behaviour to accept or fix)

- [S] `attackStartY` is 38 or 58. At Y=38 the sprite is **not rendered** until Y ≥ 55, then appears whole. The old game showed it emerging (clip pool). Accept the pop-in for Slices C–G; revisit as E. Alternatively author top entries at Y=55 and let the fragment start one segment "earlier" in time. A design choice, not a defect.
- [S] `MAX_SPRITE_Y=226` cuts an exiting enemy at the bottom 20 lines earlier than the old 246 limit. Accept.
- [S] `MIN_REUSE_GAP=33`: a side-entry formation with `addY=7` and interval 15 places members ~30 px apart in Y at full speed... members share a slot only every sixth accepted sprite, so this is fine for five-enemy waves. [U] Two overlapping waves plus bullets (10–13 sprites) can produce `statRejMargin`/`statRejUnsafe` rejections that drop a sprite for a frame. Measure in Slice G; do not pre-tune.

### 11.4 Scene text and the menu

Not waves, but the same data question: menu/game-over/initials text must be rendered into **both** pages via the row renderer or drawn once into a page while scrolling is held. [R] Give the scroller a `sceneRowRender` vector (`renderRow` currently ends in `jmp renderBackgroundRow`; make that an indirect jump through a two-byte game-owned vector). Terrain scene = stage decoder; menu scene = text rows; scrolling held via a `scrollHold` flag that behaves like `pinFine` (keeps publishing an unchanged record).

---

## 12. Scroller/stage boundary

### 12.1 What gameplay needs from the scroller

| Need | Old source | New API (R) |
|---|---|---|
| World row at the top of the aperture, 16-bit | `SCROLL_ROW/_HI` | `worldRowLo/Hi` (exists) — read-only to game code |
| Presented fine phase for screen-Y projection | `RASTER_DISPLAY_FINE` | `scrollFine` (exists) |
| Screen Y of a world row | `positionBackgroundTurrets`: `Y = rel*8 + 64 + fine` where `rel` is rows below `SCROLL_ROW` and matrix row 1 was the first terrain row | a `rowScreenY(rel)` helper owned by the game, of the form `base + fine + rel*8`. The base constant is **[U] to be measured** for the new geometry (matrix row 0 now carries terrain and is revealed through the fixed raster-55 split), not derived: place a marker glyph on a known world row and read the raster it lands on at each fine phase |
| Coarse-step event | `BG_COARSE_PENDING` | a `coarseStepped` flag set by `scrollTick` for one frame, or compare `worldRow` to last frame |
| Stage wrap event | `WAVE_TRIGGER_REWIND`/`TURRET_STREAM_REWIND` set in `prepareBackgroundCoarse` | `stageWrapped` flag set by `scrollTick` when `worldRow` passes the level bound |
| Level height | `STAGE_LOGICAL_ROWS` | same constant, consumed by `scrollTick` wrap and by the row renderer |
| Scroll speed | `SCROLL_FRAME_DIVIDER=2` | a divider in `scrollTick` (skip the `dec scrollFine` on odd frames; still publish) |
| Direction | decrementing `SCROLL_ROW` | **decision 1** |
| Row content | `decodeStageCharacterRow` → `BG_INCOMING_ROW[40]` → `copyIncomingRowToScreen` → `installTurretRow` | `renderRow` calls the game's `sceneRowRender` with `regenWorldLo/Hi` and `scrPtr` set; the game decodes into the row and overlays turret glyphs |
| Palette / MCM | `initBackground` writes `$d016`, `$d021-$d023`, colour RAM | boot, once, from `stage_config.asm` constants |

Game systems never touch `$d011`, `$d016` after boot, `$d018`, `frame*`, `dispPage`, `regenPage`, or `PTR_A/B`.

### 12.2 Turret presentation under page double-buffering

- Glyph install: in the row renderer (back page only). Correct by construction after the next flip.
- Dead-turret terrain restore: the back page regenerates from world rows and `TURRET_HEALTH==0` skips the install, so restoration happens at the next flip (≤ 16 frames at divider 2). Cover the gap with a 12-frame logical explosion object at the turret's screen position (reuses the enemy death art). No displayed-page poke.
- Hit flash: colour RAM only, 4 cells, applied from the idle spin inside a raster window where those cells' row is not being fetched (same shape as `hudUpdate`'s refusal, `$d012` outside `[rowRaster-1, rowRaster+8]`). This is the single justified exception to "colour RAM is written once": it is not paged, the write is four bytes, and a torn cell is one 8-px square for one frame. Record the window in a comment with the measurement that justifies it.
- `TURRET_Y` derivation must be re-measured for the new aperture (§12.1).

### 12.3 Runtime level data contract (what the exporter must eventually target)

```
stage_config.asm    STAGE_METATILE_ROWS, SCROLL_FRAME_DIVIDER, TERRAIN_* palette, TERRAIN_GLYPH_COUNT   (unchanged)
stage_test.asm      metatileDefs[N*16], stageMetatileRows[rows*10]                                       (unchanged)
stage_charset.asm   terrainGlyphs[count*8]  -> copied at boot to GAME_CHARSET + 96*8                      (base address changes)
stage_waves.asm     waveTrigger{RowLo,RowHi,AttackId,Count,Sprite,Interval}[N], sorted in SCROLL ORDER   (direction-dependent)
stage_turrets.asm   turretCols/Rows[N], sorted in scroll order, ≥2 rows apart                            (direction-dependent)
```

Direction is the only ABI-visible change, and only if decision 1 keeps the old direction (then nothing changes) or not (then the sort order and the trigger compare flip). Settle decision 1, then freeze this.

### 12.4 Charset placement (Slice H prerequisite)

[S] Bank 0 today: `$0400` A, `$0810-$0fff` main, `$1000` builder, `$1300` ring code, `$1400` HUD code, `$1800` fixtures, `$1a00` scroller, `$1c00` motion, `$1e00` sorter, `$2000-$23ff` sprites, `$2400-$27ff` ring tables, `$2800` B, `$2c00-$2fff` executor, `$3200-$357f` HUD bitmaps, `$3800-$3fff` blank charset. [R] After retiring P5: move `HUD_SPRITES` to `$2400` (pointers `$90..$9d`, still disjoint from `$80..$8f`), place the game charset at `$3000-$37ff` (`CB=%110`, so `D018_A`/`D018_B` real values become `$1c`/`$ac`), terrain codes 96..255 at `$3300-$37ff`, text glyphs 1..26 and 48..57 copied from ROM into codes 0..95. The executor's guard `* > HUD_SPRITES` then needs a new bound of `$3000`. Verify `clearCharset` still zeroes `$3800-$3fff` (unchanged) and re-run `make test-engine-full` because `$d018` values change.

---

## 13. HUD integration

[S] The new HUD is complete and correct for the four fields. Interface:

| Game value | Old symbol | New sink | When |
|---|---|---|---|
| Lives | `PLAYER_LIVES` (3 at start, dec in `updatePlayerState`) | `hudLives`, then `hudDirty |= HUD_DIRTY_LIVES` | on change only |
| Heat | `WEAPON_HEAT_LO/HI` 0..300 | `hudHeatLo/Hi`; dirty only when `hudHeatPixels` result differs from `hudHeatPix` (the demo already shows this pattern in `hudDemoTick`) | every frame heat moves |
| Overheat flash | `HEAT_FLASH_*` alternating `hudProofColour` 2/0 every 8 frames | one byte each into `hudCol+1`, `hudCol+2` (read by `exHud` per frame; a single byte store is atomic against it). Add `hudSetHeatAlarm(A)` to `hud.asm` so game code never touches the table directly | while `WEAPON_OVERHEATED` |
| Score | 24-bit `SCORE_*` + `awardKillScore` (+100) | `hudScore[6]` is canonical; `ldx #3 / jsr hudScoreBump` for +100. Add a saturation guard (all nines → no-op) to fix the wrap | on kill |
| Upgrade | none | `hudUpgrade = 0` at game start | once |

Timing: `hudFeed` runs in the per-frame block (sets values and dirty bits only); `hudUpdate` in the spin draws. The old game's "digits lag by up to seven frames" disappears.

Retire `hudDemoTick` in Slice B (it is the only other writer of `hud*` values).

---

## 14. Performance qualification strategy

**Instrumentation to add in Slice A** (engine style: min/max and saturating counters, read by a test, shown on no HUD):

- `gameEndLineMin/Max`: `$d012`+RST8 sampled at the end of the per-frame block (after `scrollTick`). The number that matters is how far before raster 250 the main thread finished; the old `updateCycleDebug` approximated the same thing with a 50-frame minimum.
- `gameOverrun`: saturating count of frames where `frameCounter` advanced by ≥2 between ticks (the main thread missed a frame).
- Existing engine counters to read at every checkpoint: `publishSkip` (frame-record skips: the deferred-issue signal), `schedBuildDefer`, `statLate`/`maxLateRun`, `statOverflow`, `statRejUnsafe`, `statRejMargin`, `statRejRange` (expected non-zero), `sortWork` max, `hudUpdDeferred`, `hudUpdWrapped` (must be 0), `frameEntryLine` (must be 250), `edgeLate` (0).

**Ladder.** Gameplay sprites = accepted HW2..HW7 entries; the player is not counted.

| Scene | Sprites | Built by | Batch density | Measure |
|---|---|---|---|---|
| L6 | 6 | one 5-wave + 1 bullet | 1 batch (all in batch 0) | baseline main-thread cost, `gameEndLineMax` |
| L8 | 8 | one 5-wave + 3 bullets | 1–2 reuse batches | first reuse; `statRejMargin` should be 0 |
| L10 | 10 | two overlapping 5-waves (trigger rows 8 apart) | 3–4 | `publishSkip` must stay 0 at divider 2 |
| L12 | 12 | two 5-waves + 2 bullets | 4–6 | `maxLateRun` 0; visual smoothness by eye, non-warp |
| L14 | 14 | two 5-waves + 3 bullets + 1 turret shot | 6–8 | `schedBuildDefer` rate; `sortWork` |
| L16 | 16 | three 5-waves + 1 bullet (stress trigger table) | 8–10 | the production ceiling. If `publishSkip` > 0 here, this is where the deferred issue gets its realistic reproduction |

Each scene is a **level file** (`src/generated/probe-LN/stage_waves.asm` with triggers only), not a fixture, so it runs through the real spawner and the real paths. Add `tests/test_game.py` mirroring `test_engine.py`: select the probe level by poking a `levelIndex` byte, `free_run` 20 s non-warp, read the counters. Manual acceptance is still a human watching L12 and L16 at normal speed.

**Checkpoints by slice:** A (0 sprites: main-thread floor with player only), C (1), E (L6, L8), G (L10..L16), H (L12 + terrain decoder + turrets: the decoder's cost lands in `regenTick`'s 5 rows/frame; measure `gameEndLineMax` with and without it).

Do not touch `ROWS_PER_TICK`, `REUSE_LEAD`, or the publication path until L12 shows a problem with a number attached.

---

## 15. Ordered migration slices

Each slice is one Opus task. "Rollback boundary" = the git state to return to if the slice's acceptance fails.

### Slice A — production main loop + player on HW0/HW1

- **Behaviour:** joystick-moved player ship (two hires layers), bounds `X 23..321`, `Y 55..226`, scrolling diagnostic background continues, HUD live but static.
- **Old reference:** `updatePlayer` 2348-2416, `PLAYER_START_X/Y`, `playerLayer0/1` concept, `PLAYER_LAYER_COL_0/1`.
- **New modules:** `src/game/main_game.asm` (frame loop), `src/game/player.asm`, renderer player block (§9), `Makefile` `VICE_OPTS` joystick port 2, `tests/test_game.py` skeleton.
- **Class:** B (movement), C (presentation), engine change (renderer player block).
- **Contracts touched:** schedule buffer layout (add player block), `exHud` and `exHandoff` `$d010/$d015` composition, `test_engine.py` pointer-store count 2→3.
- **Measure:** `make test` green, `hudExitMax < 17`, `handoffExitMax < 53`, `frameEntryLine == 250`, `gameEndLineMax` recorded.
- **Manual:** ship moves smoothly at 1 px/frame in all directions, stops at bounds, no flicker at the bottom bound, both layers co-located at all X including X > 255.
- **Rollback:** commit `3f7c3d3`.
- **Not yet:** fire, heat, enemies, score, states, terrain, direction flip, multicolour.

### Slice A′ — scroll direction decision (engine-only, may precede or follow A)

- **Behaviour:** terrain moves down the screen; world row decrements; divider 2.
- **Old reference:** `updateBackgroundScroll` 6627, `STAGE_START_ROW`, bottom-origin comment 764-782.
- **New modules:** `scroll.asm` only.
- **Class:** B semantics, engine change.
- **Measure:** `make test-engine-full`; all eight fine phases, top split at 55/54, `scrollLate=0`, `publishSkip=0` on RING-FAST.
- **Manual:** 60 s non-warp watch of the diagnostic rows for seams at every coarse step.
- **Rollback:** the slice's own commit.

### Slice B — fire, heat, HUD feed

- **Behaviour:** hold fire → muzzle flash 3 frames, cooldown 8, heat +2/−3, lock at 300, unlock at 150, gauge and flash on the HUD; score/lives/upgrade fed; `hudDemoTick` retired; `hudScoreBump` saturation fix.
- **Old reference:** `updatePlayerFire` 2418 (cadence half only), `updatePlayerCombatEffects` 2690, `updateWeaponHeat` 9964, `refreshHeatGaugeIfDirty` flash state machine 10053-10100 (logic only), `resetWeaponHeat` 9905 (state half).
- **New modules:** `src/game/weapon.asm`, `src/game/hud_feed.asm`, `hud.asm` (`hudSetHeatAlarm`, bump guard).
- **Class:** A (heat accumulator), B (feed), C (flash).
- **Contracts touched:** none.
- **Measure:** heat timings 150/50/100 frames exact via a monitor test (re-derive `vice_weapon_heat_timing.py`); `hudUpdWrapped == 0`.
- **Manual:** gauge fills over 3 s, flashes red/black at 8-frame half period when locked, fire resumes as the gauge passes half.
- **Rollback:** Slice A commit.
- **Not yet:** anything to shoot at.

### Slice C — one enemy: pool, emit, lifecycle, movement

- **Behaviour:** one enemy spawned on a key/trigger, follows attack 0 (top → dive → turn-left → exit upper-left), rendered through the mux, despawns on exit; parked-Y emit; `sortReset` at game start.
- **Old reference:** `OBJECT_*` layout, `findFreeObject`, `spawnEnemy`, `moveEnemyPath` family, fragment tables, `startRandomWave` seeded to attack 0.
- **New modules:** `src/game/objects.asm`, `src/game/enemy_path.asm`, `src/game/waves_data.asm`, `src/game/emit.asm`; `motion.asm`'s `motionTick` bypassed (`fixtureMoves=0` path) and later retired with the fixtures.
- **Class:** A (paths), B (pool/spawn), engine: none.
- **Contracts touched:** `logCount` fixed at 16; `statRejRange` accepted as non-zero.
- **Measure:** `gameEndLineMax` with 1 sprite; `sortWork` max; `statOverflow == 0`.
- **Manual:** enemy pops in at Y=55, follows the curve, eases through turns, accelerates on the dive, leaves the screen; no sprite left behind.
- **Rollback:** Slice B commit.
- **Not yet:** collision, damage, waves, bullets.

### Slice D — software collision, damage, enemy death

- **Behaviour:** hitscan cannons damage enemies (6 HP), hit flash white→yellow→base over 4 frames, death 12 frames over 3 explosion arts, kill awards +100; player hit by enemy body → `plyHit` latch.
- **Old reference:** `tracePlayerCannon` 2480, `damageEnemy` 2550, `updateEnemyHitEffects` 2715, `checkEnemyPlayerOverlap` 4534, `capturePlayerCollision` scan body (minus `$d01e`).
- **New modules:** `src/game/collision.asm`, `src/game/damage.asm`.
- **Class:** A (boxes, hitscan), B (damage/death), D (`$d01e`).
- **Measure:** collision scan cost at 16 pool entries (trace `collideTick`), `gameEndLineMax`.
- **Manual:** two cannon rays hit independently (0/1/2 HP per volley by alignment), explosion colours 7/8/2, score increments once per kill.
- **Not yet:** player death.

### Slice E — one complete wave + enemy bullets

- **Behaviour:** `updateSpawner` with `NORMAL_WAVE_SIZE=5`, random director (`randomAttackMap`, CIA seed), `WAVE_GAP=150`, enemy fire (cap 3, interval 42, aimed slope), bullet vs player box, shooter budget.
- **Old reference:** `updateSpawner`, `startRandomWave`, `updateEnemyFire`, `spawnEnemyBulletAt`, `chooseEnemyBulletSlope`, `moveEnemyBullet`, `checkBulletPlayerOverlap`, encounter policy 7270-7438 (turret pressure forced 0).
- **New modules:** `src/game/waves.asm`, `src/game/bullets.asm`, `src/game/policy.asm`.
- **Class:** A.
- **Measure:** **first ladder points L6 and L8**; `statRejMargin`, `statRejUnsafe`, `publishSkip`, `maxLateRun`.
- **Manual:** five enemies in formation with the authored spacing, two distinct shooters max, bullets travel straight/±1/±2.
- **Not yet:** authored triggers, turrets, player death.

### Slice F — player death, respawn, lives, game over transition

- **Behaviour:** `plyHit` → explosion 4×5 frames → lives−1 → respawn at start with 100 frames of 4/4 blink and no collision → `GAME_OVER` state flag at 0 lives (no screen yet); heat reset on death.
- **Old reference:** `updatePlayerState` 4634-4785.
- **New modules:** `player.asm` state machine; `hud_feed` lives.
- **Class:** B.
- **Measure:** none new; confirm `schedPlyEnable` toggling produces no `$d015` glitch (watch `hudExitMax`).
- **Manual:** blink is 4 on/4 off, enemies pass through during blink, ship reappears solid at the end.

### Slice G — full wave tables, authored triggers, performance ladder

- **Behaviour:** all 12 attacks selectable, `stage_waves.asm` triggers driven by `worldRow` with rewind on wrap, probe levels L10..L16.
- **Old reference:** `updateWaveTriggers`, `startAuthoredWave`, `waveTrig*` tables, level1 `stage_waves.asm` (53 triggers).
- **New modules:** `src/game/triggers.asm`, `src/generated/probe-L*/`, `tests/test_game.py` ladder.
- **Class:** A.
- **Contracts touched:** scroller exposes `stageWrapped`.
- **Measure:** the whole ladder; this is the slice that decides whether the deferred publication issue needs work.
- **Manual:** 2-minute non-warp play of L12 and L16 looking for jerk and for the background artefact reported on RING-SLOW.

### Slice H — terrain, charset relocation, turrets

- **Behaviour:** metatile terrain from level1 data, multicolour text mode, turrets stream/fire/take damage/die, restore via regeneration, hit flash via bounded colour-RAM writes.
- **Old reference:** `decodeStageCharacterRow`, `initBackground` palette part, `background_turrets.asm`, `stage_turrets.asm`, `stage_charset.asm`.
- **New modules:** `src/game/stage.asm` (row renderer), `src/game/turrets.asm`, engine: `HUD_SPRITES → $2400`, `GAME_CHARSET=$3000`, `D018_*` constants, executor guard, boot palette.
- **Class:** B (decoder, turret logic), C (turret presentation), engine change (charset placement).
- **Contracts touched:** `$d018` values, `HUD_PTR_*`, memory map, colour-RAM exception rule.
- **Measure:** `make test-engine-full` after the `$d018` change; `regenTick` cost with the decoder (5 rows × decoder ≈ 5 × 1,400 = 7,000 cycles: **this is the largest single main-thread cost in the game and must be measured before turrets are added**); L12 re-run.
- **Manual:** terrain seamless across coarse steps and page flips, turret glyphs correct at both aperture edges, dead turret reverts within one coarse step, flash cells never tear visibly.
- **Not yet:** menu.

### Slice I — game states: MENU → GAME → GAME OVER → MENU

- **Behaviour:** attract title page, fire to start, game over hold 180 frames, high-score qualify/insert/initials, back to menu; scene row renderer vector; scroll hold in menu.
- **Old reference:** `mainLoop`, `attractMenu`, `gameOverScreen`, `scoreQualifies`, `insertHiscore`, `enterInitialsScreen`, `drawInitialsScreen`, `seedHiscoreTable`, `formatHiscorePage`.
- **New modules:** `src/game/states.asm`, `src/game/text.asm`, scroller `sceneRowRender` + `scrollHold`.
- **Class:** B (logic), C (drawing), D (KERNAL).
- **Contracts touched:** scroller gains two hooks; the renderer's IRQ chain runs in every state.
- **Manual:** full loop three times without a stray sprite or a wrong page.

### Slice J (E-class backlog, in this order when wanted)

Multicolour enemies (renderer extension with per-batch `$d01c` and `$d025/$d026` at handoff, measured), enemy emergence clip bitmaps, health bar as shared per-HP art, starfield, upgrades, audio.

---

## 16. Exact recommended first Opus implementation task

**Objective.** Turn `6502-shmup` from a fixture app into a game loop with a player ship on HW0/HW1, without changing any raster phase line, admission rule or page/pointer rule.

**Old behaviour to reference.** `c64Shooter/src/main.asm` `updatePlayer` (2348-2416): joystick port 2 active-low bits 0..3, 1 px/frame, `X` 9-bit with limits 23 and 256+65, `Y` limits `GAMEPLAY_SPRITE_MIN_Y=55` and (now) `MAX_SPRITE_Y=226`; `PLAYER_START_X=160`, `PLAYER_START_Y=220`; two co-located hires layers (`PLAYER_LAYER_COUNT=2`, colours 14 and 7) from the `experimental-three-layer-player` design.

**New modules/interfaces to create.**

1. `src/game/player.asm`: player record (`plyX`, `plyXHi`, `plyY`, `plyArtBase`, `plyArtOverlay`, `plyColBase`, `plyColOverlay`, `plyVisible`), `playerInit`, `playerTick` (joystick + bounds), `playerEmit` (record → the schedule's player block). No VIC access.
2. `src/game/main_game.asm`: `gameFrame` called from `mainLoop` in place of the fixture per-frame block: `playerTick`, `playerEmit`, `sortTick`, `buildSchedule`, `publishSchedule`, `regenTick`, `scrollTick`; plus `gameEndLineMin/Max` and `gameOverrun` diagnostics.
3. `src/renderer.asm`: player block in the schedule buffers (`schedPly*[2]`, adopted with the rest at 250); `buildSchedule` copies it from the player record and initialises `bs_enable`/`bs_d010` from `schedPlyEnable`/`schedPlyD010`; `exHud` programs HW0/HW1 (X, Y, colour, pointer through a patched `plPtrStore`) and writes `$d010`/`$d015` as `HUD_* | schedPly*`; `exHandoff`'s `$d015` store ORs `schedPlyEnable`. `exFrame` also patches `plPtrStore+2` from the frame record.
4. `src/sprites.asm`: two production-shaped hires player bitmaps (hull, highlight; disjoint pixels) at indices 0 and 1 of the existing block, replacing diagnostic numerals 0 and 1. Keep the remaining numerals for now.
5. `Makefile`: `VICE_OPTS` gains a joystick on port 2 (`-joydev2 <keyset or numpad>`), drops `-joydev2 0`; keep `-joydev1 0`. Document why in the comment block.
6. `tests/test_engine.py`: pointer-store count 2 → 3; add `schedPly*` to the admitted-Y check (player Y must be within 55..226).
7. `tests/test_game.py`: launches, pokes `plyY` to 55 and 226 and `plyX` to 23 and 321, free-runs 4 s each, asserts `frameEntryLine==250`, `hudExitMax<17`, `handoffExitMax<53`, `edgeLate==0`, `hudUpdWrapped==0`, `gameOverrun==0`.

**Fixtures/diagnostics to retire or bypass.** Bypass, do not delete yet: `readNextFixture`/`readJumpP3/P4/P5` (they write `$dc00` and conflict with the joystick; guard them behind a `FIXTURE_KEYS=false` constant), `hudDemoTick` (leave running this slice; retired in B), `motionTick`/`republish` (not called by `gameFrame`), `rebuild` (called once at boot for fixture 0 so the mux still shows the numerals as a visual reference). `HUD_VISIBLE` stays false.

**Acceptance criteria.**

- `make test` passes with the three amended checks.
- `make test-game` passes.
- `make test-engine-full` is **not** required (no phase line, admission value, aperture or page rule changed) — state that explicitly in the report.
- Source-level: `grep -n 'sta \$d0' src/game/*.asm` returns nothing.
- The schedule with the player block still fits `$c000-$c2ff`.

**Timing measurements to record in the slice report.**

- `hudExitMax` before/after (expect +~40 cycles, still ≤ 16).
- `handoffExitMax` unchanged.
- `gameEndLineMax` on the boot fixture with the player: the main-thread floor for the ladder.
- `buildSchedule` cost delta from the player copy (trace `buildSchedule`→`rts` on fixture 0).

**Manual test.** `make run`. Ship visible at (160, 220) on top of the numerals fixture. Move to every edge; hold at each corner for 10 s; cross X=255/256 both ways ten times watching for a 256-px jump; sit at Y=226 for 20 s watching the bottom aperture edge for a torn row (the `MAX_SPRITE_Y` argument). Watch 60 s at rest for any HUD disturbance. Nothing is done until a human has done this at normal speed.

---

## 17. Risks / unknowns requiring runtime proof

1. **[U] Scroll direction flip** changes which fine phases coincide with badlines during the top split. `exTop`'s YSCROLL=7 special case is phase-symmetric in principle; prove it with `topSplitMin/Max` across all eight phases after the flip.
2. **[U] `exHud` growth** with HW0/HW1 programming: `hudExitMax` must remain below the HUD's first fetch line (17).
3. **[U] Screen-Y projection of a world row** for turrets under the new aperture geometry (row 0 top at raster 55 at fine 7, and 48+fine otherwise?). Measure with a marker glyph; do not derive.
4. **[U] `regenTick` + metatile decoder cost** (≈ 7,000 cycles/frame at 5 rows) against the 16-sprite ladder. If it fails, `ROWS_PER_TICK=3` at divider 2 is the documented lever (coarse step every 16 frames needs only 25/16 ≈ 1.6 rows/frame).
5. **[U] Reuse rejections in overlapping waves** (`statRejMargin/Unsafe` > 0 at L10+): a rejected sprite vanishes for a frame. Whether that is visible depends on how often it happens; measure before designing a formation constraint.
6. **[U] Deferred publication issue** at L12–L16 with real motion: this is the intended reproduction. Until it is measured there, do not touch the publication path.
7. **[U] Colour-RAM turret flash window**: the exact raster band in which a given row's colour cells are not being fetched, and whether a 4-cell tear is visible. Measure; if visible, drop the flash to a glyph-variant rendered only on the back page (one-flip latency).
8. **[U] Multicolour enemies** would add a per-batch `$d01c` store to the batch executor (≈ +8 cycles per batch inside `REUSE_LEAD`) and `$d025/$d026` to the handoff. `REUSE_LEAD=12` has ~90 cycles of measured headroom on a six-entry batch. Probably fine; must be measured, not assumed.
9. **[U] Charset at `$3000`** requires `D018` real values `$1c`/`$ac`; the frame-record self-check in `frameDiagnostics` compares against `frameD018B` and masks bit 0, so it should be unaffected, but `make test-engine-full` is mandatory after the change.
10. **[U] Joystick in VICE** with `-default`: confirm which `-joydev2` value maps the host keys without touching `$dc01` rows the game does not read (the game reads no keyboard after Slice A).
11. **[S, low risk]** Free zero page: the new engine uses `$fb-$fe`; the game may take `$02-$8f` freely because the KERNAL is banked out, but must not touch `$fb-$fe`.

---

## 18. Final go/no-go assessment

**GO.**

The old repository answers "what game did we build" clearly and, once the renderer, scroller and HUD presentation code is set aside, in about 3,000 lines of behaviour that read and write plain arrays. Its wave content is well-structured data with assemble-time validation and is worth carrying across unchanged. Its player, weapon, heat, bullet, turret and encounter logic are small, deterministic and already frame-based.

The new repository answers "how must the machine now be driven" with a contract the old game never had. The migration fits that contract with exactly two engine changes that are unavoidable (player block in the schedule; scroll direction/divider) and two that are scheduled later behind measurements (charset placement for terrain; multicolour if the art demands it). Everything else is game code living outside VIC bank 0, feeding logical arrays and HUD values.

The thing most likely to go wrong is not architecture but sequencing: porting the terrain and turrets before the sprite ladder has been measured would put the two largest main-thread costs on the table at once with no way to attribute a hitch. The slice order above keeps them apart. Start with Slice A as specified in section 16.
