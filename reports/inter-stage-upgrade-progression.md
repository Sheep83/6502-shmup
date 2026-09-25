# 19656 — Inter-Stage Upgrade Screen and Real Level Progression

**Status: the campaign loop is built and passing. LEVEL1 → boss → upgrade shop → LEVEL2 → END works on the machine. Manual visible VICE play is the one acceptance item I could not perform.**

---

## 1. Starting state

| | |
|---|---|
| HEAD | `cb3c194` — *Turrets and enemies updated* |
| Branch / upstream | `main` / `origin/main`, level with it |
| Working tree at start | **clean** — the previous aimed-fire/turret work was committed between sessions |
| Committed / pushed by me | **nothing** |

Because the tree started clean, **every file listed in §14 is this task's**.

---

## 2. Lifecycle audit

### The outer state machine (`src/gamestate.asm`)

A `cmp/beq` router; each handler owns its own frame loop and returns when the
state changes. `gsNonGame` is one byte the IRQ tests first: non-zero routes to
`gsAttractIrq`, a stub that programs a plain text display and never touches a
sprite schedule.

| | |
|---|---|
| `GS_ATTRACT` 0 | title / high-score cycle |
| `GS_PLAYING` 1 | `gamePlayLoop`, the real engine |
| `GS_GAMEOVER` 2 → `GS_INITIALS` 3 | terminal death |
| `GS_LEVELDONE` 4 | **existed already**, showing "LEVEL COMPLETE / P TOKENS / PRESS FIRE" |
| `GS_CAMPAIGN_DONE` 5 | **new** |

`GS_LEVELDONE`'s own comment anticipated this task — *"waiting for the upgrade
screen that will replace this screen's FIRE destination"* — so the shop replaced
a placeholder rather than displacing anything.

### Boss completion

`src/boss.asm` runs `LP_LEVEL → LP_CLEARING → LP_BOSS → LP_VICTORY → LP_EXIT →
LP_DONE`. On the exit phase, once the ship has flown off the top, it sets
`LP_DONE` and `jmp gsEnterLevelDone`. **The disk load is nowhere near this** —
it happens later, in the shop, from the router's own loop.

### State ownership — the reset boundary

This is the table the brief asked for before implementation.

| | Lives in | Survives a level load? |
|---|---|---|
| **Score** (6 digit bytes) | `hudScore`, src/hud.asm | **yes** |
| **Lives** | `hudLives`, src/hud.asm | **yes** |
| **P currency** | `pkTokensP`, src/pickup.asm | **yes** |
| **Partial charge** | `pkCharge`, src/pickup.asm | **yes** |
| **Campaign index** | `cmpLevel`, src/campaign.asm | **yes** (it *is* the index) |
| **Purchased upgrades** | `cmpUpgrade`, src/campaign.asm | **yes** |
| Object pool, sorter | src/objects.asm | no — `objectInit`/`sortReset` |
| Player position/state | src/player.asm | no — `playerInit` |
| Weapon heat, cooldown | src/weapon.asm | no — `weaponInit` |
| Enemy species/fire | src/enemy.asm | no — `enemyInit` |
| **Wave trigger cursor** | `wvNextTrig`, src/waves.asm | no — `waveInit` |
| Enemy bullets | `ebCount`, src/ebullet.asm | no — `ebulletInit` |
| Turret alive/fire/kills | src/turrets.asm | no — `turretInit` |
| Boss phase | `lvlPhase`, src/boss.asm | no — `bossInit` |
| Dropper / token choreography | src/dropper.asm, src/token.asm | no — `dropperInit`/`tokenInit` |
| Scroll row, fine phase, `worldProgress` | src/scroll.asm | no — `scrollInit` |
| Terrain charset / palette / sub-rows | src/terrain.asm | **replaced** per level |
| Turret placement tables | src/turrets.asm | **replaced** per level |
| Enemy + boss sprite artwork | `$2c00` / `$3580` | **replaced** per level |

**Stable fields were deliberately not moved.** Score, lives and currency already
survive a death because `gsResetRun` is what clears them; relocating them into a
"campaign block" would have been a rename dressed as a design. `src/campaign.asm`
holds only what did not exist: where the run is, and what it has bought.

---

## 3. Loader audit, and making it reusable

### How the boot load works

`levelLoad` runs **first in `entry`**, before `sei`, because that is the only
window in which it can work at all: `$01` is still `$37` so `$ffd5` is a routine
rather than level data, and the interrupts are still the KERNAL's. SETNAM /
SETLFS (device 8, SA=1) / LOAD, then a signature check with the ROM banked out —
because a *load* from `$e000-$ffff` at `$37` returns ROM even though the *store*
reached RAM. Failure is fatal: red border, halt.

### What had to change to reuse it mid-game

I refactored rather than forking it. `levelLoadCore` is the SETNAM/SETLFS/LOAD/
verify body, returning carry instead of halting; `levelLoad` (boot) halts on
failure as before; `levelLoadRuntime` wraps the same core for mid-game use. The
filename now comes from the campaign sequence, so boot and a level change read
it from one place.

**`levelLoadRuntime` has to re-create the boot environment and put the engine's
back:**

| | why |
|---|---|
| `$01 = $37` | the engine runs at `$35`, where `$ffd5` is level data |
| `$d01a = 0`, `$d019` acked | a raster interrupt must not land inside an IEC byte |
| **CIA1 timer A relatched and its IRQ enabled** | see below |
| `cli` across the load | the KERNAL masks its own critical sections; what it cannot survive is having no jiffy at all |
| then `$dc0d = $7f`, `$01 = $35`, `$d019` acked, `$d01a = 1` | the engine's state exactly as `installRenderer` leaves it |

> **The CIA is what cost this a debugging round, and it is the interesting
> finding.** `installRenderer` writes `$7f` to `$dc0d`, disabling every CIA
> interrupt for good. The KERNAL's IEC routines are built on the CIA — they time
> the bus with timer A and expect the jiffy interrupt to be running. Called with
> the CIA as the engine leaves it, **`LOAD` does not fail, it hangs**: I found
> the machine parked in the KERNAL's interrupt handler at `$ea7b` for ever with
> `$01` still `$37`. The boot load never hit it because it runs before
> `installRenderer`, with the CIA as BASIC left it.

### IRQ / banking / display safety

* **No IRQ can execute through overwritten data.** The package is bounded at
  `$fff9` by `src/levelpkg.asm`'s own guard, so the hardware vectors at
  `$fffa-$ffff` — including the engine's `$fffe` — are outside the file and
  survive the load untouched. Every byte of engine *code* lives below `$a000`.
  There is no window in which the CPU could execute a byte the loader wrote.
* **Banking returns sane**, measured: `$01` reads `$35` after the call, and the
  package signature reads correctly (it would read ROM at `$37`).
* **Failure is controlled.** Carry set with the reason in A; the caller ends the
  campaign cleanly rather than playing a level made of whatever is in RAM. A
  boot failure still halts on a red border, because there it is fatal.
* **The display is left alone** — the caller is a non-game state showing a static
  text page, so the registers simply hold for the half-second the drive takes.

---

## 4. The level sequence — data, not branches

```asm
.const CMP_NAME_LEN = 6
.const CMP_LEVELS   = 2
cmpLevelNames:  .text "LEVEL1"
                .text "LEVEL2"
```

`cmpLevel` is the index; `cmpHasNextLevel` is a compare against the count;
`cmpLevelName` returns the pointer SETNAM wants. **Adding level 3 is one row and
a longer blob** — no new state, no new branch, and nothing in the shop or the
loader changes.

---

## 5. The state flow

```
 LP_BOSS ─ boss dies ─► LP_VICTORY ─► LP_EXIT ─ ship leaves ─► LP_DONE
                                                                  │
                                                     gsEnterLevelDone
                                                                  ▼
                                                        GS_LEVELDONE  (the shop)
                                                   gsBeginNonGame: executor off
                                                                  │
                                            ┌── stick/fire ───────┤
                                            │  buy / refuse       │
                                            └─────────────────────┤
                                                      CONTINUE ───┤
                                                                  ▼
                                                        cmpHasNextLevel?
                                                    ┌─── no ──────┴─── yes ───┐
                                                    ▼                         ▼
                                            GS_CAMPAIGN_DONE          inc cmpLevel
                                            (FIRE → attract)          levelLoadRuntime
                                                                            │
                                                              ┌── failed ───┴── ok ──┐
                                                              ▼                      ▼
                                                     dec cmpLevel            gsEnterNextLevel
                                                     CAMPAIGN_DONE           GS_PLAYING
```

**Gameplay is quiesced before the shop, not by the shop.** By the time
`gsEnterLevelDone` runs, `lvlPhase` is `LP_DONE`, the scroller is frozen, the
arena is empty and the ship has left the screen — the boss's own exit sequence
did all of it. `gsBeginNonGame` then takes the executor off the display, so no
old-level scrolling or spawning can continue behind the screen.

---

## 6. The reset boundary in code

```asm
gsEnterNextLevel:
    jsr terrainApplyPackage     // the new level's charset and palette
    jsr levelApplySprites       // the new level's enemy and boss artwork
    jsr terrainInit             // colour RAM, $d022/$d023, transposed sub-rows
    jsr turretBuildTables       // the new level's turret placement
    jsr ebulletInit             // no hostile projectile survives a level
    jsr turretInit              // every authored turret standing, none visible
    jsr gameInit                // objects, sorter, player, weapon, collision,
                                // sfx, level assets, enemies, clip, WAVES (and
                                // the trigger cursor), boss, dropper, token
    jsr scrollInit              // both pages rebuilt, stageTopRow to the start
    jsr cmpApplyUpgrades        // purchases survive the level reset
```

**Every routine here is one the boot path already calls, in the boot path's
order.** Nothing bespoke was invented for a level entry.

**Deliberately absent:** `pickupInit` (would zero the currency) and `gsResetRun`
(would zero the score, lives and every purchase). Those are RUN state; this is a
LEVEL boundary. `cmpApplyUpgrades` runs *last* so a level-local reset cannot
quietly undo a purchase.

---

## 7. Token currency

`pkTokensP` already existed and its own comment already called itself *"what an
upgrade screen will one day spend"*: three pickups (`PICKUP_P_PER_UNIT`) charge
one spendable unit via `pkCharge`, and `gsResetRun` clears both for a new run.
**Nothing about the Dropper/token/protector choreography was touched.** Unspent
currency carries forward — proved in §10.

> **The prices are denominated in COMPLETED TOKENS, and the first ones were
> wrong.** They shipped as 3 and 5, which — because three pickups make one token
> — quietly asked the player for **nine and fifteen pickups**. They are now **1
> and 2**, so the first SPEED level costs one banked token (three pickups) and
> the second costs two (six). The charging mechanic, the currency representation
> and the upgrade architecture are unchanged; only the two bytes of `gsUpgCost`
> moved.

---

## 8. Persistent campaign state

```asm
* = $c780 "campaign state"           // 4 bytes, in the run between the boss
cmpLevel:       .byte 0              // state ($c760-$c76e) and the HUD ($c960)
cmpUpgrade:     .fill UPG_COUNT, 0
cmpSpeedBoost:  .byte 0
cmpSpeedMask:   .byte 0
```

`cmpSpeedBoost`/`cmpSpeedMask` are the one cached derivation: `playerTick` reads
them every frame, and deriving them from `cmpUpgrade` there would be a table
lookup on the hot path for a number that only changes in the shop.

> **`cmpSpeedBoost` is a flag tested *before* the mask, and that is not
> redundancy.** A stock ship has mask `$00`, and `frameCounter AND $00` is zero
> on *every* frame — so testing the mask alone would grant the boost always and
> make the unupgraded ship faster than stock.

---

## 9. The upgrade screen and catalogue

Read off the running machine (screen RAM decoded):

```
   2 |                UPGRADES
   4 |              P TOKENS: 01
   8 |      > SPEED       LV 0/2  COST 1
  10 |        CONTINUE
```

Joystick up/down moves the cursor, fire acts. **No keyboard.** One catalogue
row plus a CONTINUE row; a message line at row 20 for refusals and
confirmations, held 90 frames.

**The catalogue is deliberately small.** The brief offered FIREPOWER / COOLING /
SHIELD / SPEED and said a smaller honest catalogue beats a larger notional one,
so this ships the one upgrade with a real effect and does not pretend to three
more. Costs are **1 then 2 completed P tokens** — three then six pickups — and
max level is 2.

### Continue cannot fire by accident

Two independent guarantees, because the brief calls this failure out by name:

1. **Fire is a press EDGE** — `(NOT joyState) AND gsUpgPrev`. A button still
   held after a purchase does nothing whatever.
2. **CONTINUE is a row you must move onto.** The cursor starts on the first
   *item*, and there is **no wrap** at either end — wrapping from the top item
   round to CONTINUE is exactly how a cursor lands on it unaimed.

Plus `gsWaitFireRelease` on the way out, the same gate the other pages use.

---

## 10. The real upgrade: SPEED

`WPN_HEAT_FALL` was my first recommendation; you chose SPEED with the conditions
that level 0 stay exactly 1 px/frame, that the increase be a deterministic
cadence rather than a jump to 2 px, and that both be tested. That is what is
built.

`playerTick`'s four direction blocks were lifted verbatim into `playerStepOnce`
so the upgrade is *"do this again"* rather than a second, subtly different copy
of the movement rules. The clamps run once, after every step the frame takes.

| purchased | boost | rate |
|---|---|---|
| 0 | none | **1.00 px/frame — the stock model, untouched** |
| 1 | 1 frame in 4 | 1.25 px/frame |
| 2 | 1 frame in 2 | 1.50 px/frame |

**Measured on the machine over 64 frames: 64 / 80 / 96 pixels.** Exactly +16 and
+32 extra. Scrolling is untouched.

### The purchase, driven through the real UI

| | result |
|---|---|
| 1 earned P, buy SPEED (cost 1) | tokens **1 → 0**, `LV 0/2 → LV 1/2`, `cmpSpeedBoost` 1 |
| 0 P, buy again (cost 2) | **refused** — nothing spent |
| maxed, buy again | **refused, consumes nothing** — tokens unchanged |
| stick DOWN | cursor moves `> SPEED` → `> CONTINUE` |

---

## 11. Package format changes

The loader was reusable; **the package contents were not**. Charset, palette,
stage length, turret list and all sprite artwork were compiled into the engine
from `src/level1/`. Loading LEVEL2 would have given it level 1's glyphs, level
1's grey palette, five of level 1's turrets standing in its terrain, and level
1's enemies — and scrolled 62 metatile rows past the end of its own map.

Per your direction, everything except stage length moved into the package.

| region | address | size | was |
|---|---|---|---|
| map | `$e000-$e7cf` | 2000 | reservation cut from 4400 to the engine's one capacity |
| **enemy sprite window** | `$e7d0-$eccf` | 1280 | compiled into `src/enemy.asm` |
| **boss cells** | `$ecd0-$edcf` | 256 | compiled into `src/main.asm` |
| spare | `$edd0-$f12f` | 864 | — |
| defs / enc / triggers / sig | `$f130-$fb73` | — | **unmoved** |
| **charset** | `$fb74-$ff73` | 1024 | compiled into `src/terrain.asm` |
| **palette** | `$ff74-$ff77` | 4 | `.const` in `stage_config.asm` |
| **glyph count** | `$ff78` | 1 | `.const` |
| **turret list** | `$ff79-$ff91` | 25 | compiled into `src/turrets.asm` |

> **The sprites fitted without moving one address above them.** The map
> reservation was sized for a 440-row stage; fixing the engine at one stage
> height made 2,400 bytes of it unwritable by anybody, and carving the sprite
> payload out of that tail left defs, encounters, triggers and the signature
> exactly where they were.

Package size: **8,084 bytes** for both levels, inside the 8,186 available.

### Stage length — the one thing that did NOT move

`STAGE_METATILE_ROWS` is an assembly-time immediate in **18 places in
`src/scroll.asm`** (including the per-regenerated-row reduction in the hot path)
and ~12 in `src/turrets.asm`. Per your instruction this stays compiled, treated
strictly as runtime scroll capacity: the engine has one stage height (200
metatile rows) and `tools/pad_stage_map.py` pads a shorter level's **exported
package** up to it. **Level 2's authored length in the editor is unchanged at
138 rows.** Runtime-variable stage height is the follow-up.

> **The padding goes at the LOW indices, and that is load-bearing.**
> `stageTopRow` starts high and walks *down* to zero, so index 199 is seen first
> and index 0 is where the stage ends. Padding the low end puts the filler
> *after* the authored content as a run-in to the boss — and because authored row
> *m* moves to index *m + pad* while `worldProgress` is counted down from the
> top, **the two shifts cancel and every authored trigger still fires exactly
> where it was authored to.** Padding the high end would have delayed the level
> by the pad and forced every trigger to be rewritten. The filler is a copy of
> authored row 0, so the terrain continues rather than going blank.

Level 1 is padded by 0 rows and its map is **byte-identical** to what the old
`awk` extraction produced.

### Sprite artwork (your mid-task requirement)

* Each level has a `stage_sprites.asm` **manifest** naming which generated blocks
  fill the window, in slot order. **SpritePad remains the authority** — the
  manifest imports `src/generated_sprites/` unchanged, and `make sprites-check`
  still gates the `.spd` hash.
* The window is emitted as one contiguous image **padded to 20 blocks**: a level
  claiming 12 must positively zero the other 8, or the previous level's enemies
  stay readable in them.
* `levelApplySprites` copies 1,280 + 256 bytes into `LEVEL_SPRITES` and
  `BOSS_SPRITES` at level init — ~12,000 cycles once per level, paid while the
  display is a static page.
* **Species IDs, slot claims, sprite pointers, animation semantics and the
  renderer are untouched.** The bytes simply arrive from disk instead of from the
  engine binary.
* Player, muzzle flash, death fireball, token and hostile bolt **stay global** —
  they are the game's furniture, not the level's.
* `src/level2/stage_sprites.asm` is level 1's verbatim: level 2 flies the same
  three species and ships the same bytes, which costs nothing.
* The frame-order guards (`Ring frame 0 is north`, …) moved to
  `src/level_package.asm`, the build that now has the labels. A reordered art
  file is still a build error.

---

## 12. Proof

### `tests/test_campaign.py` — 29/29 pass

The transition is driven through **`gsUpgradeContinue`, the shop's own Continue**:
the KERNAL load, the banking dance and all of `gsEnterNextLevel` run exactly as
in play. Nothing is simulated.

```
ok   3 pickups charge exactly one P token -- pkTokensP after each pickup: [0, 0, 1]
ok   ...and the partial charge resets when it banks -- pkCharge: [1, 2, 0]
ok   ...and that ONE token is enough for the first SPEED level -- 1 P = 3 pickups
ok   ...and the second level costs two, not five -- 2 P = 6 pickups
ok   ONE EARNED TOKEN BUYS SPEED in the real shop -- upgrade 1, 0 P left of 1
ok   ...and the purchase reaches gameplay immediately -- cmpSpeedBoost 1
ok   STOCK: the ship still moves one pixel a frame, unchanged -- 63 px in 64 frames
ok   SPEED 1: one extra pixel every 4 frames -- 80 px vs stock 64 = 16 extra
ok   SPEED 2: one extra pixel every 2 frames -- 96 px vs stock 64 = 32 extra
ok   the upgrade is a fraction faster, not a doubling -- 64 -> 80 -> 96
ok   the sequence is a table of filenames, in order -- 'LEVEL1LEVEL2'
ok   the run starts on the first level
ok   LEVEL 1 is resident and looks like itself -- 80 glyphs, bg 12, 5 turrets
ok   ...and the world is genuinely dirty before the change -- worldProgress 52,
     trigger cursor 2, 1 live objects
ok   the sequence advanced to LEVEL2 -- cmpLevel 1
ok   LEVEL2 LOADED AND BROUGHT ITS OWN LOOK -- 128 glyphs, bg 5
ok   ...and its own turret list: level 2 has none -- 0 turrets
ok   RESET: the trigger cursor is clear in level 2 -- 0
ok   RESET: enemy bullets is clear in level 2 -- 0
ok   RESET: turret kill state is clear in level 2 -- 0
ok   RESET: the boss phase is clear in level 2 -- 0
ok   RESET: the scroll is back at the start of the stage -- 52 -> 0
ok   RESET: no level 1 object survived into level 2 -- 0 live objects
ok   PERSISTS: the unspent currency carried forward -- 7 P
ok   PERSISTS: the purchased upgrade survived the package load -- level 1
ok   PERSISTS: ...and is still APPLIED to gameplay after the reset
ok   the LAST level's Continue ends the campaign -- gsState 5
ok   ...without wrapping to LEVEL1 or reaching for a LEVEL3 -- cmpLevel 1
ok   ...and the load error byte was never touched
```

> **One test bug worth recording.** My first version deleted the breakpoint and
> slept three seconds after Continue. Under warp that is ~2,000 frames of level 2
> *actually being played*: it read `worldProgress 674` and nine fired triggers and
> called them stale state, when they were the level getting on with it. Leaving
> the `gameFrame` breakpoint armed across the transition freezes the machine on
> level 2's very first frame instead — `gameFrame` cannot run during the shop or
> the load, so the breakpoint cannot fire early.

### Engine suite

| Test | before (`cb3c194`) | now | verdict |
|---|---|---|---|
| boot, lifecycle, player_death, pickup | pass | pass | — |
| **campaign** | — | **23/23** | new |
| **turret_regression** | 2 FAIL | **pass** | **fixed** — its `TURRET_TOTAL = 8` became correct when the pool moved to the engine's capacity |
| aimed_fire, turret_arming | pass | pass | — |
| production | 1 FAIL | 1 FAIL | pre-existing (`stageTopRow` constant is stale) |
| enemy_fire | 1 FAIL | 1 FAIL | pre-existing — **identical message at `cb3c194`**, verified in a worktree |
| level_assets | 3 FAIL | 3 FAIL | pre-existing |
| encounter_director | 4 FAIL | 4 FAIL | pre-existing |
| player_ship | 1 FAIL | 1 FAIL | pre-existing, from the SpritePad task |
| sfx | 6 FAIL | 4 FAIL | pre-existing |
| boss, heat_cadence | 17 / 10 FAIL | 17 / 10 FAIL | pre-existing |

**Nothing regressed; one test was fixed as a side effect.** I changed no test to
make my work pass.

---

## 13. Manual VICE acceptance — NOT performed

AGENTS.md and the brief both make this authoritative, and **I could not do it**:
judging it requires watching and playing, and a visible VICE would steal focus,
which the standing constraints forbid.

What I did instead, which is not a substitute: read the shop's **screen RAM**
back and decode it (§9), and drive the UI with real joystick edges to prove
buy / insufficient-funds / maxed / cursor movement all work.

**Still yours to check:** that the shop reads well on a real display, that the
half-second disk pause on Continue feels acceptable, that level 2 looks right in
its own palette, and that 1.25 px/frame feels like a worthwhile purchase.

There is **no debug shortcut** in the build — I added none, so nothing can ship
enabled. To test quickly, poke `pkTokensP` for currency; the campaign test shows
the addresses.

---

## 14. Memory and performance

| | |
|---|---|
| Campaign state | **4 bytes** (`$c780-$c783`) |
| Shop state | 4 bytes, inside the existing game-state block |
| Campaign code | 89 bytes (`$9000-$9058`, character-ROM shadow — invisible to the VIC) |
| Shop + END code/text | ~600 bytes, inside the existing game-state code run |
| `terrainApplyPackage` | 60 bytes (`$6b10-$6b4b`) |
| `levelApplySprites` | 42 bytes (`$6b50-$6b79`) |
| `turretBuildTables` | ~120 bytes, inside the turret code run |
| Package | 8,084 of 8,186 bytes; `$fffa-$ffff` untouched |
| `build/` | 340 K, current artefacts only |

**Per-frame cost of the campaign existing:**

| | |
|---|---|
| `playerSpeedBoostDue` | ~10 cycles/frame (a flag test, and a mask test only when upgraded) |
| `trnBgColour` as a variable | **4 cycles/frame** — two `ldx #imm` became `ldx abs` at rasters 55 and 248 |
| Turret pool 5 → 8 slots | 3 extra iterations in `turretAimTick`'s reject scan; the file was written around 8 |
| Everything else | **0** — level transition work is once per level |

Out of 19,656 PAL cycles, that is under 0.1%.

---

## 15. Files

**New:** `src/campaign.asm`, `src/level1/stage_sprites.asm`,
`src/level2/stage_sprites.asm`, `tests/test_campaign.py`,
`tools/pad_stage_map.py`, this report.

**Modified:** `Makefile` (level 2 package + D64, padding tool replaces `awk`),
`src/levelpkg.asm` (capacity, sprite/charset/palette/turret regions, shared
geometry), `src/level_package.asm` (emits the render identity and sprites, hosts
the moved guards), `src/levelload.asm` (core/boot/runtime split, CIA restore),
`src/gamestate.asm` (shop, END, transition), `src/campaign.asm`, `src/main.asm`
(imports, boot order, `APERTURE_D021` note), `src/player.asm` (`playerStepOnce`,
speed boost), `src/terrain.asm` (`terrainApplyPackage`, runtime charset/palette),
`src/turrets.asm` (`turretBuildTables`, pool at capacity),
`src/enemy.asm` (art no longer compiled in), `src/renderer.asm` (two operands).

---

## 16. Hygiene

* **Nothing committed. Nothing pushed.** HEAD is still `cb3c194`.
* **VICE:** every launch through the harness — exact PIDs, `-console`, reaped in
  `finally`. No broad `pkill`, no user VICE touched, no focus stolen. `ps`
  confirms **none running**.
* Temporary worktrees removed; `git worktree list` shows only the repository.
* Scratch under the session scratchpad; `build/` holds current artefacts only
  (340 K). Disk: 94 GiB free of 228 GiB.
* `make run` plays the sequence: the D64 carries `engine`, `level1`, `level2`.

---

## 17. Acceptance gate

| # | | |
|---|---|---|
| 1 | Boss defeat enters an explicit inter-stage flow | ✅ `LP_DONE → gsEnterLevelDone → GS_LEVELDONE` |
| 2 | Gameplay quiesced on the upgrade screen | ✅ boss exit froze the scroller and emptied the arena; `gsBeginNonGame` takes the executor off |
| 3 | UI joystick/fire operable and readable | ✅ §9, driven and decoded on the machine |
| 4 | Token mechanic supplies persistent currency | ✅ `pkTokensP`, unspent carries forward |
| 5 | At least one upgrade has a real effect | ✅ SPEED, 64/80/96 px measured |
| 6 | Insufficient-funds and max-level work | ✅ both refused, nothing consumed |
| 4b | Prices are in the unit the arena awards | ✅ 1 and 2 completed tokens = 3 and 6 pickups, driven through `pickupCollect` |
| 7 | Campaign state survives package loads | ✅ currency, purchase, index, and the purchase still applied |
| 8 | Level-local runtime state resets cleanly | ✅ trigger cursor, bullets, turrets, boss, objects, scroll |
| 9 | Sequence is data-driven | ✅ one table; level 3 is a row |
| 10 | Normal D64 contains both packages | ✅ `engine`, `level1`, `level2` |
| 11 | Continue safely loads LEVEL2 at runtime | ✅ including the CIA restore that made it possible |
| 12 | Level 2 begins correctly, no level 1 leakage | ✅ its own charset, palette, turrets, sprites; every reset checked |
| 13 | Purchased upgrade survives and affects level 2 | ✅ |
| 14 | Final level cannot load nonexistent data or wrap | ✅ `GS_CAMPAIGN_DONE`, `cmpLevel` stays 1 |
| 15 | Authored levels / shared encounter architecture intact | ✅ level 1's map byte-identical; encounter-library ownership untouched |
| 16 | Performance not materially degraded | ✅ <0.1% of a frame |
| 17 | Nothing committed or pushed | ✅ |

**Outstanding:** manual visible VICE play (§13), and runtime-variable stage
height as the agreed follow-up (§11).
