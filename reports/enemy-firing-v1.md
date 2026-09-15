# Enemy firing v1 — authored, deterministic, straight down

**Date:** 2026-09-15
**Starting HEAD:** `0aff357023403e8d03175290a3ac0abbe6b0e1f6` — *Memory reconfigured for bank switch and multiload* (unchanged: **nothing committed, nothing pushed**)

> ## ⚠ Read §13 first
> Four existing suites that assert `publishSkip == 0` now **fail**. A source-level
> A/B on the same probe measured **1 with enemy firing authored off, 7 with it
> on**, so this is attributable to this feature and is **not** a pre-existing
> flake. `gameOverrun`, `scrollLate`, `statPageMismatch` and `statPtrMismatch`
> are zero everywhere. **This work is not GREEN.** Details, evidence and the
> limits of what I established are in §13.

**Starting working tree** — the uncommitted SFX work, all preserved:

```
 M Makefile   M src/collision.asm   M src/main.asm   M src/player.asm
 M src/turrets.asm   M src/weapon.asm
?? reports/sfx-v1.1-three-voice.md   ?? reports/sfx-v1.md
?? src/sfx.asm   ?? tests/test_sfx.py
```

**Final working tree** — nothing reset, stashed, cleaned or committed:

```
 M Makefile          M src/collision.asm   M src/ebullet.asm   M src/enemy.asm
 M src/main.asm      M src/objects.asm     M src/player.asm    M src/turrets.asm
 M src/waves.asm     M src/weapon.asm
?? reports/enemy-firing-v1.md   ?? reports/sfx-v1.1-three-voice.md
?? reports/sfx-v1.md   ?? src/sfx.asm
?? tests/test_enemy_fire.py   ?? tests/test_sfx.py
```

```
 src/ebullet.asm |  56 ++++-      src/enemy.asm  |  64 +++++      src/objects.asm |   5 +
 src/waves.asm   | 290 +++++++++  src/main.asm   |  48 ++++       Makefile        |  35 +++
```

`src/collision.asm`, `src/player.asm`, `src/turrets.asm` and `src/weapon.asm`
carry **only** the earlier SFX hooks; this task did not touch them.

---

## 1. The machinery that already existed, and was reused

| thing | where | reused how |
|---|---|---|
| hostile projectile object | `src/ebullet.asm` — an ordinary pool object, `TYPE_EBULLET`, one shared multicolour bitmap | unchanged |
| the global cap of 3 | `EBULLET_MAX`, held as a counter `ebCount`, not a pool scan | unchanged, and now genuinely shared |
| spawn | `ebulletSpawn` — cap test → `objectAlloc` → position/presentation/gameplay → `ebulletAim` → `objectActivate` | **one new entry point**, see §6 |
| flight and despawn | `ebulletTick` / `ebulletRetire` via `objectUpdateAll` | unchanged |
| player damage | `ebulletPlayerTick` → `playerTakeHit`, software collision in logical coordinates, `plyInvuln` authoritative | unchanged |
| the firing pattern to copy | `turretFireTick` — timer reloads *before* the eligibility tests, geometry band, lead over the player, refusal is not an error | followed deliberately |

The turret path was the model for the whole design: **decide, then ask; a
refusal costs the opportunity, not a retry.**

## 2. Species firing capability

Declared explicitly, in one table, read from the species byte:

```asm
.const ENEMY_FIRE_NONE = 0          // this species never fires
.const ENEMY_FIRE_DOWN = 1          // one bolt, straight down

enemyFireModeTab:                   // indexed by species >> ENEMY_ANIM_SHIFT
    .byte ENEMY_FIRE_DOWN           // SPECIES_RING
    .byte ENEMY_FIRE_DOWN           // SPECIES_DROPPER
```

A species value *is* its row in the animation table (0 and 8, not 0 and 1), so
the shift that turns a row back into an index is the one `enemyAnimPtr`'s
composition already implies. Nothing is inferred from a sprite pointer, a
colour, a wave, a movement program, a pool slot or an animation frame.

It stores a **mode, not a flag**, so a later species that fires *differently* is
a different value rather than a redesign. Both level-1 species fire the same
shot, because v1 has one firing mode and giving one enemy an exclusive on it
would be content, not architecture. `ENEMY_FIRE_NONE` is proven to work (§12).

Until now `src/enemy.asm` said a species had "no second BEHAVIOUR to hang off
one". This is that behaviour arriving, and it went where that note predicted.

## 3. Encounter-authored firing: a member mask

The trigger list already had three parallel authored columns. Firing is a
**fourth**, and the representation is a **bitmask over member index**:

```asm
.var trigDelta   = List().add(48, 4, 38, 36)
.var trigDef     = List().add(WAVE_DEF_SWEEP, WAVE_DEF_S, WAVE_DEF_LINGER, WAVE_DEF_LOOP)
.var trigSpecies = List().add(SPECIES_RING, SPECIES_DROPPER, SPECIES_RING, SPECIES_DROPPER)
.var trigFire    = List().add(%00000101,     %00000010,      %00000101,     %00000000)
```

Bit *n* set means member *n* of that appearance may shoot. The director already
counts members as it sends them (`wvIndex`), so the mask is read against
progression it already runs — **no new clock anywhere**, per-wave or per-enemy.

**Why a mask and not a rate.** A rate per member would make firing density a
function of *population*: a four-strong wave would be twice as dangerous as a
two-strong one without anyone authoring that, and a formation flying as a rank
would put four bolts on one raster — the "same-Y projectile wall" to be avoided.
A mask says *which silhouettes on screen are the dangerous ones*, which is a
thing a player can learn.

**Assembly-time guard:** a fire bit naming a member the wave never sends is
rejected at build time — invisible in play, and the definition knows its own
member count.

**Density ceiling — one opportunity at a time, for the whole screen.**
`WAVE_FIRE_PERIOD = 48` frames (~0.96 s). On an opportunity the pool is scanned
**round-robin** from `wvFireCursor` and exactly **one** eligible enemy fires.
Consequences: no two enemy bolts can ever leave on the same frame; the rate is a
property of the level rather than of how many enemies happen to be alive; and
the cursor advancing past whoever was picked stops the lowest pool slot — which
is systematically the *oldest* enemy, nearest to leaving — taking every shot.

**A missed opportunity is lost, never queued.** Nobody eligible, or the cap
refuses: nothing is remembered, and the next opportunity is a full period later.

## 4. Where firing authority lives, and why on the object

Resolved **once, at spawn**, into a per-object byte `enyFire` (16 bytes at
`$c4e0`): the encounter's mask bit AND the species' mode, both must say yes.

This is on the object rather than read through the wave because **a wave
instance is freed the moment its last member is *sent***, not when its enemies
die — `waveRunInstance` says so explicitly. An enemy spends almost its entire
life with no instance behind it. Authority held on the instance would evaporate
seconds before the enemy left the screen; authority read *through* the instance
slot would be answered by whatever unrelated wave was armed there next. This is
the same argument `enySpecies` already makes, and it is sharper here.

`objectZeroSlot` clears `enyFire` with the rest of the slot, so a slot freed by
a firing enemy cannot hand the licence to its successor — least of all to a
hostile projectile.

## 5. Eligibility, in `waveFireTick`

In order, every one a `beq`/`bcc` away from rejection:

1. `enyFire` non-zero — the authored licence;
2. `logActive` — an object at all;
3. `objType == TYPE_ENEMY` — belt and braces behind (1);
4. `objHP != 0` — **not dying**. Health reaches zero the moment the player kills
   it, and the twelve frames of explosion that follow are not a firing position;
5. `ENEMY_FIRE_MIN_Y (70) <= logY < ENEMY_FIRE_MAX_Y (170)` — 70 is the first
   line on which the *whole* 21-tall sprite is inside the aperture (which starts
   at 55), so nothing fires from a body the player can only half see; below 170
   a straight-down shot is unreactable and the enemy is about to leave anyway;
6. `logY + ENEMY_FIRE_LEAD (24) < plyY` — the bolt falls, so the ship must be
   below and not right on top of it. The same lead the turrets use;
7. `plyInvuln == 0` — an invulnerable ship is not shot at; the bolt would pass
   through it and would deny a turret a real shot.

Placed in `gameFrame` immediately after `turretFireTick`, for that routine's own
two reasons: an enemy killed this frame has already had its health taken to zero
by `collisionTick` and cannot also shoot, and a projectile spawned now is
rendered where it was launched rather than moved before it has been seen.

## 6. Origin, and the spawn-path refactor

**Logical coordinates only.** No VIC register and no mux slot is read:

```
muzzleX = logX + 8     (24-wide enemy, 8-wide bolt: centred)
muzzleY = logY + 18    (out of the belly of a 21-tall sprite)
```

The projectile system gained **one entry point**, not a second spawn routine:

```asm
ebulletSpawnDown:            // a moving enemy's shot, STRAIGHT DOWN
    lda #0
    sta ebSpawnAim
    jmp ebulletSpawnBody
ebulletSpawn:                // the turrets' shot, AIMED (unchanged name/behaviour)
    lda #1
    sta ebSpawnAim
ebulletSpawnBody:
    ...                      // cap, objectAlloc, position, presentation, gameplay
    lda ebSpawnAim           // the ONE thing the two entries differ on
    beq !straight+
    jsr ebulletAim
    ...
```

`ebSpawnAim` is written by the entry points, never by callers: a fourth request
byte for a caller to forget is a silent wrong-direction bug, while two named
entries cannot be called wrongly. No object-pool allocation logic is duplicated.

**The shot is not aimed, and that is a gameplay decision.** A moving enemy is
already harder to read than a fixed turret — it arrives from off-screen, it is
on a curve, and there may be three of it. Straight down means the enemy's own
position *tells* the player where the danger will be, which makes the formation
the threat rather than the projectile.

## 7. The shared cap

One cap, one counter, no quotas and no reservation:

```
2 turret bolts + an enemy attempt  -> the third spawns
3 bolts + any attempt              -> clean refusal
```

Measured, not asserted: the sky was filled to three through the **turrets' own**
`ebulletSpawn`, then an eligible enemy was given an opportunity —
`wvShotBlocked 0→1`, `ebRefused 0→1`, `wvShots` unmoved, `ebCount` still 3,
`objAllocFail` 0, and the pool had spare slots so it was the *cap* that refused.

Ordering in `gameFrame` is a gameplay fact, stated in the source: with three
bolts already up, the **second** caller is refused, and turrets — stationary,
telegraphed, on screen for a third of the level — are the fairer thing to let
through.

## 8. SFX

`SFX_ESHOT` (id 4) on **voice 2**, beside enemy destruction, no allocation or
mixing architecture added — the module's existing rule (whichever asked last
plays) is the whole arbitration. An enemy shot and an enemy exploding are both
world events of 100–280 ms, and the collision case is an enemy firing at the
instant another dies, which the explosion should own anyway.

A **pulse** spit: 12.5% duty, 1800 → 1200 → 800 Hz over 3 frames, attack 0 into
a 72 ms decay, 5 frames end to end (~100 ms). Pulse is the one waveform nothing
else uses — the player's report is noise and the hurt wail is sawtooth — so it
is maximally distinct from both. This restored `sfxPWHiTab` and the `SID_PW_HI`
write that v1.1 had retired when the player's shot stopped being a pulse.

**It follows the projectile, not the opportunity:** requested in `waveFireShot`
only after `ebulletSpawnDown` returns carry-clear. A refused shot is silent,
because a sound with nothing on screen behind it is a lie about the game state.
Proven both ways (§12).

## 9. Level 1 proof content

| trigger | wave | members | mask | who fires |
|---|---|---|---|---|
| 0 | echelon sweep | 4 | `%0101` | members 0 and 2, alternating along the echelon |
| 1 | S-turn | 3 | `%0010` | the middle one only |
| 2 | linger and break | 3 | `%0101` | two of three — the formation that *hangs* mid-screen earns the most shots |
| 3 | loop | 3 | `%0000` | **none** — the showpiece manoeuvre is the breathing room |

Nothing else about the level changed: no wave definition, no flight path, no
trigger delta, no species column. The encounter philosophy is intact — mostly
one formation at a time, one deliberate sweep/S-turn overlap, and a silent
formation in every cycle. A non-firing appearance is also the case the whole
representation has to support, so it is authored rather than hypothetical.

## 10. Memory — exact ranges and cost

| segment | before | after | delta |
|---|---|---|---|
| `enemy firing` (new) | — | `$c4e0-$c4ef` **16 B** | **+16** |
| waves code | `$7c00-$7e20` 545 B | `$7c00-$7efa` **763 B** | **+218** |
| wave state | `$77c0-$77d2` 19 B | `$77c0-$77d8` **25 B** | **+6** |
| projectile code | `$7500-$7692` 403 B | `$7500-$76ac` **429 B** | **+26** |
| projectile state | `$6e80-$6e88` 9 B | `$6e80-$6e89` **10 B** | **+1** |
| sfx code | `$1780-$18e1` 354 B | `$1780-$18fb` **380 B** | **+26** |
| enemy code | 258 B † | `$4900-$4a03` **260 B** | **+2** |
| object pool code | 209 B † | `$4800-$48d3` **212 B** | **+3** |
| main | 657 B † | `$5000-$5293` **660 B** | **+3** |
| **total** | | | **+301 B** |

† measured ranges are from the linked map; these three baselines are *derived*
from the source diff (a 2-byte table, one `sta abs,x`, one `jsr`) because I did
not record their pre-task ranges. Every other row is measured both sides.

**PRG unchanged at 51,164 bytes** — every segment is fixed-position.

**Headroom after the change:** waves code 262 B to its `$8000` ceiling;
projectile code 84 B to `$7700`; wave state 40 B to `$7800`; sfx 1,284 B to
`$1e00`; `enyFire` exactly fills `$c4e0-$c4ef` up to the animation table.

**No VIC-visible or level-replaceable capacity was consumed.** `enyFire` sits in
the module-state region of bank 3; all code is resident and CPU-side; no sprite
block, character or enemy-art window byte was touched.

**Per-frame cost, counted instruction by instruction** (PAL budget 19,656): an
ordinary frame is `dec`/`beq`/`rts` plus the `jsr` — **20 cycles**. An
opportunity frame is at most ~450 (a 16-slot walk plus the shot), once every 48
frames, so the amortised cost is **~29 cycles a frame, 0.15% of the budget**.

## 11. What I did *not* do

No RNG, no aiming, no prediction, no spreads, no bullet patterns, no second
projectile type, no queue, no per-enemy or per-wave timer, no dynamic
difficulty, no cap increase, and no renderer, multiplexer or raster change.

## 12. Focused proof — `tests/test_enemy_fire.py`, ALL PASS

One VICE launch. Registered in the Makefile as `make test-enemy-fire` and in the
default `test` target.

| required | result |
|---|---|
| explicit species firing capability | `enemyFireModeTab` reads `[1, 1]`, one row per species |
| deterministic authored opportunity | the four authored masks read back exactly; through the **real `waveSpawnMember`**, members 0..3 of mask `%0101` got licences `[1, 0, 1, 0]` |
| a species may veto it | the RING row patched to `NONE` in RAM: an appearance authored to fire produced **no** licence |
| eligible live enemy can spawn | through the **real frame loop**: `wvShots +1` *and* `ebFired +1` |
| dead/inactive cannot | a **dying** enemy (`objHP` 0) fired nothing; a stale licence forged on a **free slot** fired nothing |
| expected logical origin | enemy box `(62,99)` → bolt `(70,117)` = `+8 / +18`, read *after* the frame because the enemy moves before the firing tick runs |
| downward movement through the existing path | `objVX 0`, `objVY 3`, and `EBULLET_VY` per frame actually elapsed |
| turret/enemy shared cap = 3 | filled via the turrets' own entry; cap held at 3 |
| clean cap-full failure | `wvShotBlocked +1`, `ebRefused +1`, `wvShots` unmoved, `ebCount` 3, `objAllocFail` 0, pool had room |
| no deferred queue | the lost opportunity was not retried next frame; period reloaded to 48 |
| existing player damage path | a bolt on the ship → `plyHits +1` through `ebulletPlayerTick`/`playerTakeHit` |
| SFX on successful spawn | voice 2 carries `SFX_ESHOT` |
| no false SFX on failure | after the refused shot, voice 2 stayed silent |
| encounter continues | `wvStarted 68→98`, spawning throughout |
| short smoke, catastrophic zero | pristine 5 s of held-fire play: `gameOverrun`, `scrollLate`, `statPageMismatch`, `statPtrMismatch` all **0** — with 69–72 enemy shots fired in that window |

### Three fixture races I had to fix, recorded because they cost real time

Every one of these failed *as if the feature were broken*:

1. **Stopping at a frame top is not running a frame.** A single breakpoint stop
   at `gameFrame` executes *none* of that frame. Arranging state and reading
   back showed nothing had happened. Fixed by aligning first, then running.
2. **"No shot happened" ≠ "this enemy did not shoot."** With several licensed
   enemies in the air, the dying-enemy scenario passed on a shot fired by
   somebody else. Every scenario now revokes all other licences, stands the
   turrets down for the frame, and checks the **director's own** counter rather
   than only the projectile system's.
3. **The pool filling looked exactly like the cap refusing.** Probe enemies
   parked mid-screen accumulate, `objectAlloc` then refuses the *bolt*, and the
   scenario fails for reasons unrelated to firing. Probe enemies are now handed
   back through `enemyDespawn`, and the cap test asserts the pool had room.

**Proportionality, honestly:** 465 lines, of which **289 are executable**
against ~153 lines of added 6502 instructions and data. That is **larger than
the gameplay change**, which the brief asked me to avoid. It is driven by the
fourteen mandated proof points and the isolation each needs; I judged cutting
checks worse than the overage, but it is over the line and I am flagging it
rather than hiding it.

## 13. ⚠ The smoke gate — NOT GREEN, and it is this feature

`make test` **aborts** at `test_production`. Running every suite individually,
once, on the final binary:

| suite | result |
|---|---|
| `test_boot` | ALL PASS |
| `test_production` | **FAIL** — `publishSkip is zero over 10s of ordinary play` — **7** |
| `test_turret_regression` | ALL PASS |
| `test_encounter_director` | **FAIL** — `publishSkip is zero with the director running` — **14** |
| `test_player_ship` | **FAIL** — `publishSkip is zero over six seconds of play` — **7** |
| `test_level_assets` | **FAIL** — `publishSkip is zero after the round trip` — **21** |
| `test_sfx` | ALL PASS |
| `test_enemy_fire` | ALL PASS |

**This is not one of the pre-existing flakes I was warned about**, and I did not
assume either way. Evidence:

* `make test` passed **in full, twice**, earlier in this same session — all four
  of these suites included — before enemy firing existed.
* A **source-level A/B** on the identical probe: authoring `trigFire` to all
  zeros (firing off, everything else byte-identical) gives `publishSkip` **1**;
  the shipped masks give **7**.

`publishSkip` lives in `src/scroll.asm` and is labelled there as *"publication
found the previous one still unadopted: a real fault"* — the frame record is not
adopted and the display holds a frame. It is **not** in the benign category that
`schedBuildDefer` occupies.

**What I could not establish.** My first hypothesis was bolt density, so I
halved the firing rate (`WAVE_FIRE_PERIOD` 48 → 96) and measured again: it came
back **9**, not lower. So it is *not* simply how many bolts are alive, and the
mechanism is unexplained. Resolving it properly needs the repeated-run
statistical work this brief explicitly rules out, so **I stopped there** and
restored the gameplay-motivated period of 48.

**What I did not do:** I did not modify any of those four tests, did not touch
the renderer, mux or raster, and did not start optimisation work. All four
remain failing in the tree exactly as found.

**Scale, for fairness:** these probes run under **warp**, so a 10-second probe
covers thousands of emulated frames — 7 events is well under 1% of frames, not a
continuous stutter. Whether it is *visible* is precisely a manual-VICE question,
and it is the first thing to look for (§16).

**No unrelated failures were observed.** The flakes the brief warned about
(player movement, pool/population assertions in `test_production`) did not fire
in any run.

## 14. VICE hygiene

`pgrep -fl x64sc` **before: nothing. After: nothing.** Every launch used
`-console` and `+saveres`, never `-default`, launched directly with no focus
theft and no joystick-disable or global-detach override. Each run owned and
reaped its own PID — the harness prints `launched and reaped` per run and every
run in this task did so, including the two scratch probes, which used their own
ports (6680/6681/6683). No broad `pkill`; no manual VICE session existed. No
temporary logs or captures were left in `/tmp`; the two probe scripts and the
A/B source copy lived in the session scratchpad and the copy has been deleted.
No per-run build artifacts.

```
du -sh build/     84K        (shmup.prg, main.sym, main.vs only)
du -sh .          5.2M
```

## 15. Genuine limitations

1. **The `publishSkip` regression of §13 is unexplained and unfixed.** It is the
   one thing standing between this and a clean gate.
2. **One firing mode, one direction.** No aiming, spread or pattern — by design,
   but it means every enemy shot looks alike.
3. **The rate ceiling is global, not per formation.** Which appearances fire is
   authored; *how often any of them does* is one constant. A per-formation rate
   would need a per-enemy clock, which the brief ruled out for v1.
4. **The mask is 8 bits**, so a wave of more than 8 members could not address
   its later members. Current waves send 3–4; the assembler rejects a bit that
   names a member the wave never sends.
5. **Two species, identical capability.** `ENEMY_FIRE_NONE` is proven to work
   but is not exercised by shipped content — only by the test's RAM patch.
6. **The focused test is larger than the production change** (§12).

## 16. What to play and listen for

1. **The scroll, first and hardest.** §13 says the frame record is occasionally
   not adopted. Watch the terrain scroll during heavy moments — two formations
   plus turret fire — for any hitch, tear or momentary freeze. **If you see
   nothing, that materially changes what to do about §13; if you do see it, that
   is the bug to chase next.**
2. **Are the shots visible and fair?** They fall at 3 px/frame from mid-screen.
   Can you see one leave, read where it will be, and move?
3. **Is the cadence right?** ~1 opportunity a second, one bolt at a time. Too
   sparse to feel threatened, or too dense to breathe? `WAVE_FIRE_PERIOD` in
   `src/waves.asm` is the single knob.
4. **Combined pressure.** Turrets plus enemies share three bolts. Does the cap
   make turrets feel starved during a firing formation?
5. **Can you tell who is shooting?** Members 0 and 2 of the sweep fire; the loop
   never does. Is that legible, or does it just feel random?
6. **The spit, on voice 2.** Short, thin, electronic — distinct from your own
   heavy report and from the destruction crunch? It shares a voice with the
   crunch, so listen for an enemy firing as another dies.
7. **Flicker.** Bolts spawn mid-screen among enemies, which is new work for the
   multiplexer on those rasters.

## 17. Recommended next step

**Decide about §13 from what you see**, before token pickups. If the scroll is
visibly clean, the honest resolution may be that `publishSkip`'s zero assertion
is too strict for a world with this much hostile traffic — but that is a call
about an engine invariant and it is yours, not mine, and it should be made
deliberately rather than by editing four tests until they are quiet. If it is
visibly dirty, the mechanism needs finding before any more content goes in.

Then **token pickups**, as planned.
