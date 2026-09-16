# Player death fireball + enemy body collision

**Date:** 2026-09-16
**Starting HEAD:** `d5566b08ab5cdfeadf8c03e885cf7fdd299e500e` — *Powerup Token mechanic added*, unchanged. **Nothing committed or pushed.**
**Starting working tree:** the uncommitted state-machine work from the previous task, all preserved.

**Files changed**

| file | why |
|---|---|
| **`src/player_boom_art.asm`** *(new)* | the eight fireball frames |
| `src/player.asm` | the death phase, its timing, the respawn, the fireball on HW0, control suppression |
| `src/collision.asm` | `playerBodyTick` and the body hitbox constants |
| `src/weapon.asm` | a dead craft cannot fire |
| `src/ebullet.asm` | bolts pass through a dying craft |
| `src/main.asm` | the art import and the `playerBodyTick` call |
| `src/pickup.asm` | segment moved one page; see §6 |
| `Makefile`, `tests/test_player_death.py` *(new)* | the focused proof |
| `tests/test_production.py`, `test_player_ship.py`, `test_enemy_fire.py` | assertions that described the **old** death contract; see §9 |

---

## 1. Control and fire suppression

One byte, `plyDead`, set the instant the craft is destroyed — **on every death, not only the last one**. The old behaviour (a fully controllable, still-firing ship inside its own death animation) existed because there was no death state at all: a hit only started an invulnerability blink.

| what stops | where | how |
|---|---|---|
| movement | `playerTick` | `plyDead` jumps straight to `playerDeathTick`, skipping the whole movement block — the stick cannot move it and the lean cannot change |
| firing, hitscan, `shotFired`, player-fire SFX | `weaponFire` | one branch at the top. Everything a volley causes is downstream of it, so refusing once refuses all of it |
| muzzle HW1 | `playerTakeHit` | `plyFlash` is zeroed on the killing frame, so a shot resolved on that frame cannot leave HW1 lit over the wreck |
| incoming bolts | `ebulletPlayerTick` | a dying craft is not a target |
| ramming | `playerBodyTick` | same rule |

Proven with the stick **and trigger held for the whole death**: position frozen, `shotFired` never set, HW1 never enabled.

## 2. Body collision

`playerBodyTick` in `src/collision.asm`, called from `gameFrame` immediately after `ebulletPlayerTick` — every enemy has moved, so the boxes compared are this frame's. **Software collision in logical coordinates; `$d01e` is not read here or anywhere in this engine** (the mux time-shares HW2..HW7, so a collision bit names a slot, and a slot is not an object).

**Eligibility**, all read from state the engine already keeps — no new flags:

- `logActive` — a freed or despawning slot fails first;
- `objType == TYPE_ENEMY` — bolts, tokens and background turrets are other types;
- `objHP != 0` — zero is this engine's own "dying", the same byte `enemyTick` tests to run a death animation instead of a flight path.

Protectors and the Dropper are ordinary `TYPE_ENEMY` objects and are therefore included **by construction** — neither is named anywhere in the code.

**Hitboxes** — a deliberately forgiving player box, stated as an inset rectangle with the four compare bounds derived from it so tuning is four numbers:

```asm
PLAYER_BODY_INSET_X = 6     PLAYER_BODY_W = 12      // 12 of the ship's 24 wide
PLAYER_BODY_INSET_Y = 5     PLAYER_BODY_H = 12      // 12 of its 21 tall
BODY_HIT_LEFT = 18   BODY_HIT_RIGHT = 18   BODY_HIT_UP = 16   BODY_HIT_DOWN = 17
```

The enemy keeps its full 24×21 cell. One common box for every species: all three are the same cell and no current data carries a cheaper per-species extent, so a per-species table would be a framework holding one repeated number.

**The existing damage path is reused.** `playerBodyTick` decides geometry and nothing else; it tail-calls `playerTakeHit`, so being rammed and being shot are the same event to the life count, the hurt SFX, the invulnerability rule and the explosion. **The enemy is not destroyed by contact** — nothing in this game's semantics says a collision damages the thing collided with.

## 3. The fireball

**Eight frames, six PAL frames each — 48 frames, 0.96 s.** The hold is a separate counter from the frame index rather than one countdown divided by six: a divide by six costs more than the byte it saves, and "which frame" and "how long it has been up" are two facts a tuning pass will want independently.

`plyBoomFrame` reaching `PLAYER_BOOM_FRAMES` is what **ends** the explosion — it is never wrapped, so **it cannot loop**. Proven: the index only ever advances, every one of the eight frames appears, and each inner frame is held exactly six.

The ship silhouette is gone on the **first** frame of death: `playerEmit` takes the fireball branch before the banking-frame arithmetic, so HW0 never names a hull block while dying.

### Storage

**`$25c0-$27bf`, eight 64-byte blocks, pointers `$97-$9e`** — the free run between the collectible token's bitmap and screen page B. Resident player presentation, sitting with the ship at `$2000` and the muzzle at `$2400`, **not** in the level enemy window a level package owns and replaces. Nothing else in the bank moved. Guards: 64-byte alignment, no overlap with the muzzle flash below, no overlap with the token bitmap, and not past `SCREEN_B`.

### Multicolour mapping

| code | source | in the fireball |
|---|---|---|
| `%00` | transparent | **the holes** — terrain shows through, which is what makes the late frames read as breaking apart rather than turning black |
| `%01` | `$d025` shared, dark grey | smoke and cooling embers, last two frames only |
| `%10` | **`$d027`, HW0's own** | **red** (`PLAYER_COL_BOOM = 2`) while burning |
| `%11` | `$d026` shared, white | the core |

**No global palette change was needed.** HW0's private colour is *already* swapped per state — the hull is light blue, the muzzle flash is red — so the fireball simply asks for red while it burns. No enemy, Dropper, token or muzzle colour is touched.

The eight frames grow from an off-centre spark to a ragged peak and then come apart: holes open in the core, the ring breaks into fragments, and it gutters out. Every frame is asymmetric and no frame is a scaled copy of another — verified structurally as eight *distinct*, non-empty blocks.

## 4. Ordinary vs terminal death

```
killed  ->  plyDead, controls and fire off, muzzle out, life deducted
        ->  the same 48-frame fireball on HW0
        ->  lives remain : plyVisible back on, plyInvuln = 100, respawn blink
            no lives     : HW0 hidden, and playerFatalTick hands over
```

Both deaths run the **identical** explosion; only the destination differs. Terminal death **stays in GAME** for the whole explosion — `playerFatalTick` now waits on `plyDead` rather than on the old blink — and only then enters the existing GAME OVER path. The GAME OVER hold itself was not touched, so terminal death is now *explosion → remaining aftermath → GAME OVER*, which is what you asked to judge by hand.

## 5. Respawn invulnerability preserved

The old **death blink** is gone; the **respawn blink** is intact and is now unambiguous. `playerTakeHit` no longer raises `plyInvuln` — the invulnerability moved to the far end of the explosion, where `playerDeathTick` sets `PLAYER_INVULN_TIME` on respawn and `playerInvulnTick` blinks it exactly as before. Proven: after the fire goes out the craft returns wearing a ship frame in the ship's colour, with `plyInvuln == 100`, and `plyVisible` genuinely alternates.

While it burns the craft is **solid, never blinking** — so the explosion cannot be confused with invulnerability.

## 6. Memory

| segment | before | after | delta |
|---|---|---|---|
| **player fireball** *(new)* | — | `$25c0-$27bf` **512 B** | **+512** |
| player code | `$4000-$4265` 614 B | `$4000-$42ee` **751 B** | +137 |
| collision | `$4c00-$4cea` 235 B | `$4c00-$4d46` **327 B** | +92 |
| weapon code | `$4600-$474e` 335 B | `$4600-$4753` **340 B** | +5 |
| projectile code | `$7500-$76ac` 429 B | `$7500-$76b2` **435 B** | +6 |
| main | — | +3 B (one `jsr`) | +3 |
| player state | `$c51a-$c53b` 34 B | `$c51a-$c53f` **38 B** | +4 |
| **total** | | | **+759 B** |

**PRG unchanged at 51,164 bytes.**

**`src/pickup.asm`'s code segment moved `$4d00` → `$4e00`.** Collision grew past `$4d00` and the linker refused the overlap; pickup does not care where it sits and its own guard says so. Nothing else moved.

**Headroom:** the fireball leaves one free block (`$27c0-$27ff`) before screen page B; collision has 186 B to pickup; **player state is now full** — `$c53f` is the last byte before the scroll state at `$c540`, so the next per-player byte needs a new home.

## 7. SFX

Untouched. `playerTakeHit` still requests `SFX_HURT` on the killing blow and nothing else changed — no new explosion sound, and the gun, enemy shot, destruction, Dropper ping and token chime are all as they were.

## 8. Build and focused proof

Build clean. **`tests/test_player_death.py`: ALL PASS** — eight distinct 64-byte frames at `$97` inside the free run with the unused 64th byte zero; a dead craft that cannot be steered or fired with stick and trigger held, and never lights HW1; the fireball on HW0 in red, every frame shown, six frames each, index never going backwards; respawn wearing the ship again in the ship's colour with a blinking invulnerability window; ramming a **live** enemy damaging the player through `playerTakeHit` while a **dying** enemy, a hostile bolt and a collectible token do not; an invulnerable craft immune to bodies; the enemy not destroyed by contact; terminal death running the same explosion, staying in GAME throughout, hiding HW0 and then reaching GAME OVER.

**Short smoke** (in that file): `gameOverrun`, `scrollLate`, `statPageMismatch`, `statPtrMismatch` all **zero**.

`test_lifecycle` (the restored state machine) is **ALL PASS**, so lives, high scores and the outer loop are intact.

## 9. Full suite, and what is left red

| suite | result |
|---|---|
| `test_boot`, `test_turret_regression`, `test_lifecycle`, **`test_player_death`** | **ALL PASS** |
| `test_player_ship` | `publishSkip` only |
| `test_production` | `publishSkip`, plus one movement interval — below |
| `test_encounter_director`, `test_level_assets` | `publishSkip`, `schedBuildDefer 1` |
| `test_enemy_fire` | `schedBuildDefer` |
| `test_sfx`, `test_pickup` | stale — below |

**`publishSkip` was not investigated**, as instructed.

**Three tests asserted the OLD death contract and were updated**, because this task deliberately replaced it — a hit used to raise `plyInvuln` on an intact ship and now destroys the craft:

- `test_production`: "playerTakeHit raises invulnerability" → now asserts it **destroys the craft and counts the hit**, and the respawn that follows is invulnerable;
- `test_player_ship`: its muzzle-flash captures now start from a living craft;
- `test_enemy_fire`: its bolt-on-the-ship case likewise.

**A genuine new intermittency, reported rather than hidden:** the craft can now be dead for ~1 second at a time, so any probe that samples a *live* ship over a window can catch a death. `test_production`'s movement sample still shows one zero-pixel interval in some runs — the frame a bolt killed the craft. Reviving before the window (done) narrows it but cannot close it, because the window is live. Closing it properly would mean a no-damage test hook in production code, which I did not add unasked. **This is a consequence of the intended change, not a defect in it.**

**Stale, from commits that predate this task** (I modified none of `sfx.asm`, `waves.asm`, `token.asm` or `dropper.asm`): `test_sfx` does not know about the Dropper's sonar ping (effect 6 from `$7aee`) or the 10-byte SFX state, and `test_pickup` still looks for `waveTrigTokenLo`, which `src/token.asm` replaced. **Recorded, not fixed.**

`schedBuildDefer` (1–20) is the load counter the renderer documents as benign — it counts the publication guard *working*. The catastrophic four are zero in every clean measurement.

## 10. VICE and disk hygiene

`pgrep -fl x64sc` **before: nothing. After: nothing.** Every launch used `-console` and `+saveres`, never `-default`, no joystick-disable or global-detach override, no focus theft; each run owned and reaped its exact PID, and no broad `pkill` was used. The three probe scripts live in the session scratchpad; no logs or captures were left in `/tmp`; `build/` holds only its three fixed artifacts.

```
du -sh build/     92K
du -sh .          6.4M
```

## 11. For manual VICE — what only you can judge

1. **Does it read as a fireball?** Violence of the ignition, the expansion, and whether frames 6–8 genuinely break up rather than just shrink.
2. **Red / white / negative space.** The holes are transparent, so terrain shows through them — does that help or muddle it over busy ground?
3. **Timing.** Six frames each, 0.96 s total. Too slow, too fast, or right?
4. **Fragment disappearance.** Does frame 8 gutter out, or vanish abruptly?
5. **The silhouette.** Confirm the ship is gone *instantly* — no intact hull visible on the first frame of death.
6. **Body-collision fairness.** The player box is 12×12 inside a 24×21 ship. Does ramming feel fair, or too generous/harsh? Four constants in `src/collision.asm`.
7. **Death feel.** Controls cut dead the moment you are hit — confirm that reads as death rather than as a hang.
8. **The remaining final-death pause.** Explosion, then aftermath, then GAME OVER. **You asked to judge this by hand once the explosion existed** — it is deliberately untuned.
9. **Respawn.** The blink after an ordinary death should read as invulnerability, clearly distinct from the explosion.
