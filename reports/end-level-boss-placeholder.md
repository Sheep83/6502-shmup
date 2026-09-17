# End-of-level boss phase, player exit and LEVEL COMPLETE

**Date:** 2026-09-17
**Starting HEAD:** `ab8db0d` — *Game lifecycle restored, player death added*, unchanged. **Nothing committed or pushed.**
**Starting working tree:** clean.

**Files changed** — two new, twelve modified:

| file | why |
|---|---|
| **`src/boss.asm`** *(new)* | the whole level-ending phase machine |
| **`src/boss_art.asm`** *(new)* | the four boss cells |
| `src/scroll.asm` | the derived boundary, the freeze, the `stageHold` diagnostic |
| `src/collision.asm` | one ray → one boss hit |
| `src/player.asm` | reads `plyExit`: no steering, no damage |
| `src/weapon.asm` | no firing once the level is won |
| `src/waves.asm`, `src/token.asm`, `src/turrets.asm` | nothing new enters a closing arena |
| `src/objects.asm` | `TYPE_BOSS` |
| `src/sfx.asm` | `SFX_LAUNCH` on voice 3 |
| `src/gamestate.asm` | the `GS_LEVELDONE` state and its page |
| `src/main.asm` | imports, `bossInit`, `bossTick` |
| `Makefile`, `tests/test_boss.py` *(new)* | the focused proof |
| `tests/harness.py`, `tests/test_level_assets.py` | see §11 |

---

## 1. Stage geometry, and the derived boundary

```
STAGE_METATILE_ROWS = 105        (src/level1/stage_config.asm, the level editor's)
METATILE_H          = 4          (src/terrain.asm)
STAGE_ROWS          = 420
SCREEN_ROWS         = 25
STAGE_START_ROW     = STAGE_ROWS - SCREEN_ROWS = 395
```

`stageTopRow` starts at `STAGE_START_ROW` and walks **down** one per coarse
step; `worldProgress` walks up. At `worldProgress == 395`, `stageTopRow == 0`
and the page shows stage rows 0..24 — **the top of the authored map and the last
complete screenful there is**. One more step takes `stageTopRow` to −1, the
invariant's modulo folds it to 419, and the level wraps to its own beginning.

```asm
.const STAGE_FINAL_VIEW_PROGRESS = STAGE_START_ROW
```

**Derived, not typed:** it is the authored height less the viewport. A longer
level moves it with no line changing.

## 2. The freeze

The check sits **immediately after** `worldProgress` is incremented in the
coarse step, so the step that *arrives* at the final view completes — its page
flip is what puts that view on screen — and the next one never starts. Checking
before the step would stop a row early and show the second-to-last screenful.

`scrollTick` then returns at its first instruction, so **neither the coarse row
nor the fine phase moves again**: the last step left `scrollFine` at zero with
the authored top row exactly at matrix row 0. Letting the fine phase run on
would slide the terrain down by up to seven pixels and expose the strip above a
row that has nothing above it.

Proven: `worldProgress` stops at exactly 395, `stageTopRow` is 0, and over 40
further frames neither it nor `scrollFine` moves.

## 3. Arena-clear policy

Every system that can put something new into the arena **tests `lvlPhase`
itself** rather than being switched off from elsewhere — `waveTick`,
`waveFireTick`, `tokenTick`, `turretFireTick` — so each stops in its own terms
and nothing keeps a list of what to suppress.

What is already in flight gets `ARENA_CLEAR_DEADLINE = 200` frames to **leave
the way it normally would**: enemies fly their authored egress, bolts run off
the bottom. Content leaving under its own rules reads as the level ending rather
than as the game being switched off.

**It cannot deadlock.** When the deadline expires, whatever is left is removed
outright through the routines that own each lifecycle — `enemyDespawn` and
`ebulletRetire` — and `lvlForced` records that it happened. A Dropper still
flying its pattern, a protector mid-role or a bolt that will never leave cannot
hold the level open. Proven with a hostile deliberately parked and inert.

## 4. Boss lifecycle

```
LP_LEVEL → LP_CLEARING → LP_BOSS → LP_VICTORY → LP_EXIT → LP_DONE
```

One byte, `lvlPhase`. `bossTick` costs ~15 cycles during ordinary play: a
compare, a branch, and a load of `stageComplete`.

`bossInit` is **level-scoped** and runs from `gameInit`. It resets the phase, the
boss, `plyExit` and the arena's colours — and touches no run state.

## 5. One entity, four render cells

The boss is **one** logical thing: one position, one `bossHP`, one death. The
four cells are pool objects of `TYPE_BOSS` carrying a pointer, a colour and a
position — no health, no movement, no despawn rule, no tick.

Nothing treats them as enemies: `traceRay` and `playerBodyTick` filter on
`TYPE_ENEMY`, and `objectUpdateAll`'s dispatch chain falls straight through
`TYPE_BOSS` to the next slot. **No mux redesign, no schedule change, no clipping
change** — they are drawn by the ordinary pipeline.

| | |
|---|---|
| art | `$3580-$367f`, four 64-byte cells, pointers **`$d6-$d9`** |
| position | `BOSS_X = 136`, `BOSS_Y = 74`; cells at (x, x+24) × (y, y+21) |
| composed | 48 × 42 pixels, upper-middle of the frozen arena |
| palette | `%00` transparent · `%01` `$d025` dark grey structure · `%10` per-cell `$d027` = `BOSS_COL` 4 (purple) · `%11` `$d026` white core |

The picture was drawn as **one** 24 × 42 image and cut into four, with the
bright core deliberately spanning **both** joins — a seam nothing crosses is a
seam the eye finds. Nothing global moved: the two shared registers already held
dark grey and white.

`$3580` is the four-block run the Ring vacated; it is the only contiguous
four-block run left outside the level enemy window, which belongs to a level
package.

## 6. 50 HP and the hitscan

`BOSS_HP_FULL = 50`. The hitbox is **one rectangle** — 48 × 42 inset by
`BOSS_HIT_INSET = 4` — because the cells are a picture and a picture should not
be able to disagree with a hitbox.

`collisionTick` already gives each ray exactly one damage call. The boss is
tested **only when `traceRay` found nothing else in the way**, so an enemy or
turret between player and boss still absorbs the shot. Because the cells are not
targets at all, **a ray crossing a seam has nothing to hit twice** — proven by
firing a ray straight down the seam at `BOSS_X + 24` and watching HP fall by
exactly one. Damage is `SHOT_DAMAGE`, the same as every other target takes, so
the twin cannon's two rays do two points a volley: ~25 volleys, about four
seconds of sustained fire.

**Feedback.** A hit sets `BOSS_COL_HIT` (white) on all four cells for
`BOSS_FLASH_TIME = 3` frames — the whole machine lights up, because it is one —
then returns to purple.

**Health bar:** 25 cells of colour RAM on row 1, one cell per 2 HP, redrawn only
when the count changes. Cheap precisely because the arena is frozen: nothing
flips pages and colour RAM is not double buffered, so a row written stays
written. Bit 3 is kept set in both values so the cell stays multicolour and the
terrain does not switch rendering mode under the bar. **The HUD was not
touched** — all six of its sprite slots are spoken for, and there is no font in
the playfield charset.

## 7. Boss death and the victory pause

At 0 HP the boss is immediately non-damageable (`bossRayHit` returns on a zero
HP), the four cells are freed through `objectFree`, the bar is cleared, and
`VICTORY_PAUSE = 100` frames begin. There is deliberately **no** death
animation: that pause is the space one will be built into.

`plyExit` is set **at boss death**, not at launch — victory is confirmed at that
moment and everything still available to the player is nonsense. It disables the
stick (`playerTick`), the trigger (`weaponFire`) and all damage
(`playerTakeHit`). Stale hostiles are purged on the same frame.

## 8. The scripted exit

Velocity in **eighths of a pixel**, so the launch starts visibly slow and is
genuinely fast by the time it leaves:

```
EXIT_ACCEL = 1   (eighth of a pixel per frame, per frame)
EXIT_VMAX  = 64  (8 px/frame)
EXIT_GONE_Y = MIN_SPRITE_Y - SPRITE_HEIGHT = 34
```

Distance after *n* frames is *n*²/16 px, so the ~190 px from the ship's station
to off the top take about 55 frames. Measured: velocity climbs from 1 to well
past 8 eighths, Y is monotonically upward, and the stick and trigger are ignored
throughout.

On clearing the aperture, `plyVisible` is set to 0 **explicitly** — the ship has
*left*, and letting it drift on into the open upper border as a stray sprite is
not the same thing — the launch SFX is silenced, and `gsEnterLevelDone` is
called.

## 9. Launch SFX

`SFX_LAUNCH` (id 7) on **voice 3**, a **sawtooth** climbing 180 Hz → 2100 Hz
over 60 frames on a curve weighted to start slowly and then run away — the same
shape as the acceleration it describes.

Voice 3 because it is the quiet one: it carries only the player-damage wail, an
effect that cannot happen during a victory since `plyExit` makes the ship
invulnerable before the sound starts. Voices 1 and 2 would have been cut by the
gun and by world effects.

**The long DECAY is the sustain.** `AD = $1c` (attack 8 ms, decay 3000 ms) with
**sustain zero**, so the module's safety invariant — every effect decays to
silence on its own, and a gate left high on a sustain-zero voice is silent —
holds exactly as before. No existing effect was altered.

## 10. LEVEL COMPLETE, and the run

`GS_LEVELDONE` is a genuine lifecycle state in the existing cmp/beq router, not
a detour inside the game loop. It reuses the non-game IRQ seam, so gameplay,
mux and SFX are all off the display. The page reads:

```
LEVEL COMPLETE
P TOKENS: nn
PRESS FIRE
```

with the count taken straight from `pkTokensP`.

**`gsEnterLevelDone` resets nothing at all** — score, lives and P currency are
exactly as the level left them, which is the point of the state. Proven: lives,
P and score all intact on arrival (the score is *not reset*; the HUD's own
cadence keeps ticking during the exit).

**FIRE returns to attract — temporary, and it says so in the source.** Starting
level 2 would need level loading and a level-scoped reset that do not exist yet.

## 11. Two test-infrastructure changes I caused

- **`tests/harness.py`**: the level is finite now, and in warp a five-second
  probe covers all 395 coarse rows — so every pre-existing test that free-ran
  for a while ended up measuring the frozen boss arena. `scroll.asm` gained
  **`stageHold`**, a diagnostic switch beside the existing `pinFine`, which makes
  the stage endless exactly as it used to be; the harness sets it for every
  legacy test, and `test_boss.py` clears it. This restored `test_production`,
  `test_turret_regression`, `test_encounter_director`, `test_player_ship`,
  `test_sfx` and `test_enemy_fire` from wholesale failure.
- **`tests/test_level_assets.py`**: it asserted `$3580` was still all zeros as
  proof the Ring migration completed. The boss now lives there, which does not
  resurrect the Ring, so the check was restated to ask what it always meant —
  *the Ring's artwork is not resident at its former pinned home*.

## 12. Memory

| segment | before | after | delta |
|---|---|---|---|
| **boss cells** *(new)* | — | `$3580-$367f` **256 B** | **+256** |
| **boss code** *(new)* | — | `$9400-$967c` **637 B** | **+637** |
| **boss state** *(new)* | — | `$c760-$c76e` **15 B** | **+15** |
| game state code | `$8b00-$8fa3` 1,188 B | `$8b00-$9058` **1,369 B** | +181 |
| sfx | `$1780-$1949` 458 B | `$1780-$1a03` **644 B** | +186 |
| scroller | `$4300-$4510` 529 B | `$4300-$4535` **566 B** | +37 |
| scroll state | `$c540-$c56b` 44 B | `$c540-$c56d` **46 B** | +2 |
| waves | `$7c00-$7f1e` 799 B | `$7c00-$7f4a` **843 B** | +44 |
| turret code, token, collision, player, weapon, objects, main | | | +~90 |
| **total** | | | **≈ +1,448 B** |

**PRG unchanged at 51,164 bytes.** `plyExit` lives in the boss's state block
because the player's own block is full to its `$c540` ceiling — and because the
byte belongs to the level's ending.

## 13. Build, focused proof, smoke

Build clean. **`tests/test_boss.py`: ALL PASS** — the derived boundary; the
freeze on the last full screen with `stageTopRow == 0` and no wrap; no new wave
member, enemy shot or bolt once the level is ending; an arena clear that
completes even with a hostile that refuses to leave; exactly four `TYPE_BOSS`
cells at the four adjacent pointers composed 2×2 from one position, none of them
damageable in its own right and none moving or firing; 50 HP; a seam ray
counting once; a second ray taking a second point; a ray beside the body
missing; the flash covering all four cells and expiring; the bar following the
damage; immediate non-damageability at 0 HP; the cells gone; the 100-frame
pause with the ship stationary; an accelerating exit with stick and trigger
ignored; HW0 hidden and voice 3 silent on clearing the top; and LEVEL COMPLETE
with lives, score and P intact.

**Short smoke** (in that file, before anything is posed): `gameOverrun`,
`scrollLate`, `statPageMismatch`, `statPtrMismatch` all **zero**.

`test_boot`, `test_turret_regression`, `test_lifecycle`, `test_player_death` are
**ALL PASS**.

## 14. Unrelated failures — recorded, not fixed

- **`publishSkip` / `schedBuildDefer`** in `production`, `encounter_director`,
  `player_ship`, `level_assets`, `sfx`, `enemy_fire` — the known limitation.
  **Not investigated**, as instructed.
- **`test_sfx`**: the 10-byte SFX state, the Dropper's sonar ping (effect 6 from
  `$7aee`) and a `(2, 'pickup')` hook. From the user's own token/Dropper commits;
  I modified none of `token.asm`'s or `dropper.asm`'s SFX.
- **`test_pickup`**: `KeyError: 'waveTrigTokenLo'` — the authored column it tests
  was replaced by `src/token.asm` in the user's commits.
- **`test_production`** movement and **`test_player_ship`** banking/pointer
  captures: intermittent, and the cause is the one reported last task — the ship
  can now die mid-capture, so a probe that assumes continuous flight is a
  lottery. In this run `test_player_ship` caught the ship wearing a fireball
  frame (`$97`) with its bank frozen. **Not new to this task.**

## 15. VICE and disk hygiene

`pgrep -fl x64sc` **before: nothing. After: nothing.** `-console` and `+saveres`
throughout, never `-default`, no joystick-disable or global-detach override, no
focus theft; every run owned and reaped its exact PID; no broad `pkill`. The two
generator scripts live in the session scratchpad; nothing was left in `/tmp`;
`build/` holds only its three fixed artifacts.

```
du -sh build/     96K
du -sh .          6.8M
```

## 16. Manual judgement

1. **The terrain freeze.** Does it stop on a clean, complete screen — no blank
   strip at the top, no half-row, no wrap?
2. **The arena clear.** Does the emptying feel natural, or does the boss arrive
   too soon / after an awkward wait?
3. **Boss scale and composition.** 48 × 42. Does it read as one machine, or can
   you see it as four sprites? Check the joins, especially through the core.
4. **Hitbox feel.** 48 × 42 inset by 4. Fair?
5. **50 HP pacing** — about four seconds of sustained fire. Too long, too short?
6. **The health bar.** A red row of terrain cells on row 1. Legible as a bar, or
   does it just look like recoloured ground?
7. **The 2-second victory pause.** Too long now that it is empty?
8. **Acceleration feel** — noticeable launch, then a strong departure.
9. **The engine sound.** A rising sawtooth over ~1.2 s. Engine-like, or a siren?
   Does it stop cleanly as the ship leaves?
10. **LEVEL COMPLETE.** Clean transition, no stale sprites or raster artefacts.

## 17. Seams for the next task

- **`GS_LEVELDONE` is where the upgrade screen goes.** It already owns the
  non-game display and silence; replace `gsDrawLevelDone` and the FIRE
  destination. Everything else in the router stays.
- **`bossInit` is the level-scoped reset** and already runs from `gameInit`. A
  next-level transition should call it *without* `gsResetRun` — that is the
  run-vs-level split this task first made concrete.
- **What a next level must also reset:** `scrollInit` (world progress, both
  pages, `stageComplete`), the wave/director cursor, the token encounter and
  Dropper liveness. None of that may go through new-game init.
- **`pkTokensP` survives into `GS_LEVELDONE`** and is displayed there; P spending
  belongs in the same screen.
- **`stageHold`** is a diagnostic only — do not let game code write it.
- The boss is one entity with a seam for a real one: `bossFightTick` is where
  movement, weapons and phases will go, and none of that needs the render path
  to change.
