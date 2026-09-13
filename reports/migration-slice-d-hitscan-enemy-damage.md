# Migration Slice D — Hitscan Collision, Enemy Damage, Enemy Death

**Repository:** `6502-shmup`
**Reference:** `shooter_test` (the task named it `c64Shooter`; that path does not
exist, and `shooter_test` is byte-identical to the archive the original audit used)
**Date:** 2026-09-13
**Scope:** logical hitscan from the player's weapon to the migrated enemy, damage,
bounded hit feedback, a bounded death state, and safe removal through the Slice C
lifecycle.
**Status:** automated GREEN. **Manual acceptance is the user's to declare, and this
report does not declare it.**

A claim marked **observed** was read out of a source file or off a running machine.
A claim marked **decision** is something this slice chose.

---

## 1. What was inspected in the old game

Read out of `shooter_test/src/main.asm` before any Slice D code was written.

| Old routine / constant | Line | What it governs |
|---|---|---|
| `updatePlayerFire` | 2418 | builds each cannon's 9-bit X, traces, damages |
| `tracePlayerCannon` | 2480 | the hitscan itself: eligibility, hitbox, nearest |
| `damageEnemy` | 2550 | one HP per hit, underflow refusal, death entry |
| `updateEnemyHitEffects` | 2714 | the flash ladder, the death frames, the free |
| `updateEnemyHealthSprite` | 2578 | per-enemy private health-bar bitmap |
| `awardKillScore` | 4160 | score on death |
| `capturePlayerCollision` | 4468 | the only `$d01e` use, and not the weapon's |
| `ENEMY_START_HEALTH = 6` | 995 | "Three centred dual-cannon volleys" |
| `ENEMY_HIT_FLASH_TIME = 4` | 996 | "Short white/yellow impact flash" |
| `ENEMY_DEATH_TIME = 12` | 997 | "Total frames before the logical enemy slot is released" |
| `GAMEPLAY_SPRITE_MIN_Y = 55` | 561 | the lowest hittable line at RSEL=0 |
| `PLAYER_LEFT/RIGHT_CANNON_X = 4 / 19` | 993-994 | already migrated in Slice B |

---

## 2. Recovered hitscan geometry

**Observed.** The fifteen questions, answered from the source.

1. **One cannon lane or both?** Both. `updatePlayerFire` builds the left cannon's
   X, traces, damages, then does the same for the right, in the same frame.
2. **What X range counted as a hit?** The full 24-pixel sprite width. The trace
   computes `rayX - enemyX` as a 9-bit subtraction, rejects any non-zero high
   byte, and accepts a low byte below 24. The old comment: *"Valid horizontal
   intersection is enemyX .. enemyX+23."*
3. **A vertical ray upward?** Yes. *"Hitscan only travels upward from the
   player's current position."*
4. **Nearest enemy only?** Yes, per cannon. The old comment on the call site is
   explicit: *"Closest eligible enemy or world turret, one target per cannon."*
5. **Could one shot damage multiple enemies?** Yes — one per cannon, so up to
   two per volley. And both can land on the **same** enemy when it straddles
   both lanes, which is how a centred enemy loses two HP per volley.
6. **Was enemy Y ordering relevant?** Yes. It is the entire selection rule.
7. **Were hitboxes narrower than the graphic?** **No.** The box is the full
   sprite width. This was checked rather than assumed, because a narrower box is
   the usual convention and would have been the wrong guess.
8. **Exact dimensions and offsets?** Width 24, offset 0 from `OBJECT_X`. No
   vertical extent at all: the ray tests a single line of eligibility, not a box.
9. **Damage per legal shot?** One HP. `damageEnemy` is a single `dec`.
10. **Enemy HP?** Six.
11. **Invulnerability or hit cooldown?** None. The only refusal is
    `OBJECT_HEALTH == 0`: *"Already dead/dying: never underflow health."*
12. **Visual feedback on hit?** A four-frame colour flash: white while the timer
    is 2 or more, yellow at 1, then the formation colour restored.
13. **What happened on death?** The hit timer was cleared, a 12-frame death timer
    started, and the sprite became an explosion bitmap with a
    yellow → orange → red colour progression.
14. **Score awarded immediately on death?** No — `awardKillScore` is called when
    the death **animation finishes**, at slot release, *"exactly once before
    releasing its slot."*
15. **Did death delay the free?** Yes, by the full 12 frames. The slot stays
    active and renderable throughout.

---

## 3. Target selection

**Observed, and reproduced exactly.**

- **Eligibility** has two halves: the enemy must be at or below
  `GAMEPLAY_SPRITE_MIN_Y` (55) — *"Off-screen ingress is not a hittable
  target"* — and **strictly above** the player.
- **Nearest means greatest Y.** The player is below and fires upward, so the
  eligible enemy with the largest Y is the closest.
- **The tie goes to the higher pool slot.** The old test is
  `cmp HITSCAN_TARGET_Y / bcc !next`, which continues scanning on a strictly
  smaller Y and **replaces** the incumbent on an equal one. The scan runs low
  slot to high, so among equal-Y enemies the highest index wins.

That tie rule is reproduced deliberately rather than improved on. It is stable,
it is deterministic, it is what the old game shipped, and a named test pins it in
both directions. It does depend on pool slot — which the task flagged as
acceptable only if explicit, so it is stated here and tested rather than left to
be discovered.

---

## 4. Hitbox

| Property | Value | Source |
|---|---|---|
| Width | 24 pixels | `tracePlayerCannon`, `cmp #24` |
| X offset | 0, relative to the enemy's own X | the subtraction is against `OBJECT_X` |
| Vertical extent | none — eligibility is a line test, not a box | the Y test compares against the ship, not a range |

Held as **type-level constants** (`HITBOX_W`, `HITBOX_X_OFF`), not per-object
fields. One enemy type needs one box; a second type can add a table when it
arrives, and not before.

---

## 5. Health and damage

**Decision, with the old values.**

| Symbol | Value | Origin |
|---|---|---|
| `ENEMY_MAX_HP` | 6 | `ENEMY_START_HEALTH` |
| `SHOT_DAMAGE` | 1 | one `dec` per cannon hit |
| `HIT_FLASH_TIME` | 4 | `ENEMY_HIT_FLASH_TIME` |
| `DEATH_TIME` | 12 | `ENEMY_DEATH_TIME` |

Maximum HP is **type data**, applied at spawn. No per-object maximum is stored,
because every enemy of this type starts at the same value and a second copy is a
second thing to keep in step.

Two per-object arrays were added, and they carry three states between them:

```
objHP > 0,  objTimer == 0    alive
objHP > 0,  objTimer  > 0    alive, running the hit flash
objHP == 0, objTimer  > 0    DYING; the timer is the death animation
objHP == 0, objTimer == 0    cannot exist while active
```

**Zero HP is the death flag.** The old game carried a separate
`OBJECT_DEATH_TIMER` beside `OBJECT_HIT_TIMER`, but the two could never both run:
`damageEnemy` clears the hit timer when it begins a death, and refuses to act on
an already-zero health, so a dying enemy can never take a second hit. Deriving the
state from health rather than storing it again removes the possibility of the two
disagreeing. The impossible fourth row is asserted never to occur.

No armour, no resistance, no damage types.

---

## 6. The old VIC collision behaviour, explicitly rejected

**Observed.** The old game did read `$d01e`. `capturePlayerCollision` calls it
*"the cheap hardware broad phase"* and uses it to decide whether the **player's
own body** touched an enemy.

That is a different system, and it is a later slice. The old game's **player
weapon** was already pure logical hitscan with no VIC involvement at all, and
that is what this slice migrates.

`$d01e` and `$d01f` are not read anywhere in this slice, and the suite checks the
source of all three gameplay files for them. The reason is structural rather than
stylistic: the mux deliberately time-shares HW2..HW7, so one physical sprite draws
several logical objects within a frame and an object's slot changes between
frames. A VIC collision bit names a slot, and a slot is not an object. Asking the
hardware "which enemy was hit" has no correct answer in this engine.

Two further rejections:

- **`updateEnemyHealthSprite`.** The old game gave each damaged enemy a private
  64-byte sprite copy with a health bar burned into its bottom two rows, built by
  self-modifying code that patches its own source and destination operands. It
  costs a bitmap per live enemy, it is a rendering feature, and it belongs with
  the graphics slice if at all.
- **`traceTurretCannon`.** The old trace extended target selection to world
  turrets. There are none yet.

---

## 7. The new logical collision contract

**Decision.** `src/collision.asm`, state at `$c5f3`, code at `$4c00`.

```
weaponTick       emits the shot event: shotFired, shotRays, shotXLo/Hi[], shotY
objectUpdateAll  every object takes its movement
collisionTick    for each ray: traceRay -> applyDamage
enemyTick        next frame: flash ladder, death ladder, and the free
```

`traceRay` returns carry clear and X = the target's slot, or carry set on a miss.
It is O(`MAX_OBJECTS`) with no early exit — sixteen slots, a few hundred cycles,
measured rather than assumed. A spatial structure over sixteen objects would cost
more to maintain than it could ever save.

**The cannon X comes from the Slice B shot event and is never recomputed.**
`collision.asm` contains no reference to `plyX` and no sprite register. Each ray
is tested from its own logical origin, so the two cannons genuinely differ.

**The filter is object type, not "any active object":**

```asm
lda logActive,x   beq !next+
lda objType,x     cmp #TYPE_ENEMY   bne !next+
lda objHP,x       beq !next+          // already dying: not a target again
```

The pool will later hold pickups and enemy bullets, and a filter meaning
"everything alive" would silently start shooting them down. The `objHP` test also
stops a dying enemy shadowing a live one behind it.

---

## 8. Temporal model

**Decision, and it is a decision rather than an incidental call order.**

Collision runs **after all movement**. Everything it reads is end-of-frame state
for the same frame: `playerTick` moved the ship, `weaponTick` built the ray
origins from that new position, and `objectUpdateAll` has just moved every enemy.
Nothing compares a this-frame coordinate against a last-frame one in either
direction.

Running it before `objectUpdateAll` would have been equally consistent and worse:
an enemy would be tested where it was when the trigger was pulled and drawn a
pixel or two further on. That is the kind of one-frame disagreement that is
invisible in a test and infuriating in play.

**One visible consequence, named so it is not later mistaken for a bug:** an enemy
that left the world on this frame was already freed by `objectUpdateAll`, so a
shot fired on that frame misses it. That is a definite answer rather than a race,
and it is a named test.

---

## 9. Hit feedback

**Decision, reproducing the old ladder exactly.** `applyDamage` sets the timer to
4 and the logical colour to white. `enemyFlashTick` then decrements first and lets
the remaining value choose:

| Timer after decrement | Colour |
|---|---|
| 2 or more | white (1) |
| 1 | yellow (7) |
| 0 | the spawn colour, restored once |

Measured on the machine: `(3, white) (2, white) (1, yellow) (0, base)` — three
white frames counting the hit itself, then one yellow, then restored.

**Gameplay writes `logCol`, a logical value.** It never touches `$d027-$d02e`, it
never names a hardware slot, and nothing raster-side is mutated. The renderer
copies the logical colour into the schedule and the executor writes the register,
exactly as it does for position.

**The base colour is looked up, not stored.** The old game kept
`OBJECT_BASE_COLOUR` per object so a flash could be undone. Here the colour is a
property of the spawn entry, and the entry is recoverable from the object's
velocity and high X byte, so `enemyBaseColour` reads it back from the spawn table.
One table beats sixteen bytes of duplicated state.

---

## 10. Death and the free

**Decision.** Zero HP is the death state. The timer is reloaded to 12 and the
colour follows the old progression:

| Timer remaining | Colour |
|---|---|
| 8 or more | yellow (7) |
| 4 to 7 | orange (8) |
| below 4 | red (2) |

Measured: `7 7 7 7 8 8 8 8 2 2 2`, then the slot is released on the frame the
timer reaches zero — 12 frames exactly.

A dying enemy **stops moving**. The old file says why at line 2331: *"A dying
enemy remains renderable but no longer follows its path."* An explosion that keeps
flying reads as a live enemy the player cannot kill.

**The old explosion bitmaps were deliberately not migrated.** `playerExplosion1/2/3`
are art, and the next planned slice is the level and background graphics
migration. This slice keeps the **timing and the colour progression**, which are
the architecturally load-bearing parts, and dies as a bounded yellow-orange-red
flash of the enemy's own shape. The art is a one-line change when the graphics
slice brings it across.

**There is exactly one place an enemy slot is released** — `enemyDespawn`, calling
`objectFree`. Death routes through it rather than freeing separately, so
publication safety has one path to reason about rather than two.

---

## 11. Score

**Not migrated, as instructed.** The old `awardKillScore` was called at slot
release. What a future score system needs is the fact and the type, so that is
what is published:

```
csKills      kills resolved THIS frame, cleared at the top of every collisionTick
csKillType   the type of the most recent kill
csKillsLo/Hi a running total, 16-bit
```

Nothing consumes it. The HUD score is untouched and still on its demo value.

---

## 12. Publication safety on a kill

**Proven, and this was the check that mattered most.**

With an enemy killed and present in the adopted CURRENT schedule, the test reads
the whole CURRENT buffer, frees the object outright **without running a frame**,
and reads CURRENT again. Identifiers, positions and colours are all byte-identical.

That is the correct outcome. CURRENT is immutable for its frame by contract, the
executor is reading it, and gameplay freeing its own state must not reach into it.
The killed enemy is drawn for the remainder of the frame it was already committed
to, from the schedule's own copy, and disappears at the next publication.

On the following frame NEXT no longer contains it, and neither does the sorted
window.

Nothing in the death path touches a VIC register. The sprite is not turned off:
the next schedule simply does not contain it.

---

## 13. Sorter membership after a kill

Measured after riding a full death out:

- the killed slot is absent from the sorted window;
- every remaining window entry is active;
- `sortedIDs` is still a permutation of all 32 logical IDs;
- with nothing alive, `logCount`, `sortedCount` and the accepted count are all
  zero and the schedule is valid and empty.

---

## 14. Pool reuse after a kill

The killed slot is allocated again on the next spawn and comes back clean: HP back
at 6, timer zero, the enemy pointer `$d9` restored. No slot is ever active with
zero HP and a stopped timer — the impossible state.

This is Slice C's `objectAlloc` whole-slot zeroing doing its job, now with two
more fields to forget. The reason that routine clears the slot whole rather than
by name is exactly this: Slice D added `objHP` and `objTimer`, and a hand-written
list of fields to reset would have gone stale on the spot.

---

## 15. Multi-enemy target selection

| Case | Result |
|---|---|
| Two in one lane at different Y | the nearer takes both cannons, the farther is untouched |
| ...with the pool slots allocated the other way round | same answer, so it is not pool order by accident |
| Equal Y | the higher slot wins, identically on a repeat |
| Inactive slot nearer than a live one | ignored, and does not shadow the live one |
| Non-enemy type nearer than a live enemy | ignored |
| One enemy straddling both lanes | takes two HP from one volley |
| Enemy outside both lanes | untouched |
| Enemy leaving the world on the shot's frame | a clean miss, by the temporal model |

Each is a named check.

---

## 16. Collision cost against population

**Measured on a free run**, and each population run **twice** — with
`collisionTick` switched to an immediate `RTS` and with it live — so the cost is
attributed rather than merely observed.

| Enemies (spread 10 rasters) | Span, collision OFF | Span, collision ON | Collision's cost | Frames missed |
|---:|---:|---:|---:|---:|
| 1 | 139 | 133 | — | 0 |
| 4 | 167 | 171 | 4 | 0 |
| 8 | 220 | 235 | 15 | 0 |
| 12 | 255 (saturated) | 255 (saturated) | — | yes, **both** |
| 16 | 255 (saturated) | 255 (saturated) | — | yes, **both** |

Collision's own contribution is **4 to 15 raster lines** at the populations the
engine sustains, for a volley that runs the scan twice over sixteen slots. The
O(N) scan is entirely appropriate and no spatial partitioning was built.

### A finding: the engine saturates at around eight well-separated sprites

At 12 and 16 the main thread overruns the frame — **and it does so with collision
switched off**. This is not Slice D.

The cause is sprite *packing*, not count. Slice C's ladder spawned enemies one per
frame into a descending column two rasters apart, which the reuse rule collapses
into a single batch. Slice D spread them ten rasters apart, which produces up to
eleven batches, and the schedule build cost rises with it.

So the practical ceiling for well-separated gameplay sprites is around **eight**,
not the sixteen Slice C's ladder suggested. Nothing has been optimised — the task
forbids it and section 10 of the engine contract already owns this ground — but
the number is recorded, and the engine contract now carries the table, because a
wave designer needs to know the budget is about spacing rather than headcount.

The suite raises this as an **advisory** rather than a failure: it is a
pre-existing engine limit that this slice happened to measure, and failing the
slice that found it would be the wrong signal.

---

## 17. Frame and schedule publication

| Measure | Result |
|---|---|
| Frame transaction entry | raster 250, every sample |
| Frame-record publication skips | 0 at every sustained population |
| Schedule publications withdrawn mid-build | 0 at every sustained population |
| `statPageMismatch` / `statPtrMismatch` | 0 |
| Schedule overflow | 0 at every population |
| Player slots | both reserved bits still published |

At 12 and 16 the record-skip counter does move, with collision off as well as on,
which is the same pre-existing saturation described above.

---

## 18. Player, weapon, HUD and scroller regressions

| Check | Result |
|---|---|
| Player movement | one pixel per frame, 160 → 154 over six frames |
| Weapon heat | rises while firing, falls when released |
| HUD heat feed | still exactly the weapon's value |
| World progress | still only increases; the map row still steps back |
| Aperture and page publication | clean over a free run |
| Frame transaction | raster 250 |
| `$d017` / `$d01c` | both zero |

The full gate — `test_engine`, `test_slice_a`, `test_slice_a_prime`,
`test_slice_b`, `test_slice_c`, `test_slice_d` — reports **420 successful checks
in 8m54s**, with no failures. `tests/test_slice_d.py` contributes 73 of them and
has its own `make test-slice-d`.

### Three earlier probes broke, and none of them because the engine got worse

Recorded because each was a premise that had quietly become false, and because
two of them looked exactly like regressions.

1. **A `$d015` sample taken at the wrong raster.** Slice B read the register
   after a single `mon.cmd("x")` at `exBottom` without checking where the
   machine actually stopped. That call returns on a prompt echo, so the read
   sometimes came from raster 0 — inside the ghost window, where `$d015` is
   *correctly* `$00`. It reads precisely like the player having vanished. The
   read now verifies its own raster before believing itself. This is the fourth
   time this project has been bitten by that echo.
2. **A timing comparison whose three samples saw three different worlds.** Slice
   B measures idle, moving and firing spans and attributes the difference to the
   weapon. With enemies spawning and dying underneath, it produced a *moving*
   frame cheaper than an idle one. All three samples now run against an emptied
   pool. The bound was also widened and renamed, because a firing frame now
   genuinely resolves the hitscan too: twenty raster lines for the volley and
   both sixteen-slot cannon scans.
3. **A bulk read indexed by a computed offset.** Slice C read the pool's three
   counters at `3 * MAX_OBJECTS` from `objType`, silently assuming three
   per-object arrays. Slice D inserted `objHP` and `objTimer` ahead of them, so
   the "double free" counter became a live enemy's health and the probe reported
   six double frees on a pool that had had one. The counters are now read by
   symbol, which cannot drift when the next slice adds a field.

---

## 19. VICE input-configuration hygiene

Automated runs launch with input settings as per-process command-line arguments
only, and `+saveres` means resources are never written back:

```
x64sc -console -default +saveres -pal +sound \
      -joydev1 0 -joydev2 0 +keyset -remotemonitor ...
```

The suite hashes the user's `vicerc` before the run and re-hashes it after, and
fails if it changed. It is unchanged.

It also checks the **manual** launch options, because those were the real hazard
found after Slice C: `make run` no longer passes `-default`, which combined with
any save overwrites the user's bindings with factory defaults. That check is
retained here.

No temporary VICE configuration was needed, so none was created.

The keyset advisory added after Slice C is also retained and currently passes:
`KeySet1Fire` is present.

---

## 20. Process and disk cleanup

Every automated run launches `x64sc` with `-console` under a retained PID and
reaps it in a `try/finally`; each run printed its own `launched and reaped` line,
and a post-run check reports **vice clear**. No broad `pkill`, no manual VICE
signalled, no `open -a`.

Transient probes and logs were written under `/tmp`.

| Measure | Size |
|---|---|
| `du -sh build/` | **80K** — `main.sym`, `main.vs`, `shmup.prg`, and nothing else |
| `du -sh .` | **2.6M** |

---

## 21. Known deferred work

- **Player damage and death.** The old `capturePlayerCollision` and its `$d01e`
  broad phase are the next collision system, not this one.
- **The explosion bitmaps.** `playerExplosion1/2/3`, deliberately left for the
  graphics slice that comes next.
- **Score.** A kill event is published and nothing consumes it.
- **The enemy health bar.** The old per-enemy private sprite copy, rejected.
- **The wave and formation system**, enemy bullets, turrets, lives, upgrades,
  level triggers, audio, editor ABI, bosses. None started.
- **The eight-sprite practical ceiling** in section 16, and the RING-SLOW /
  RING-SHIFT judder from section 10 of the engine contract.
- **Reject attribution** — the Slice C finding that an overlapping sprite is filed
  under the Y-range counter. Still measured, pinned and unfixed.

---

## 22. Manual test instructions

**Fourteen checks. Please run these yourself at normal speed.** This report does
not declare manual GREEN.

Joystick in port 2. If the ship moves but never shoots, that is the `KeySet1Fire`
binding rather than the game — see section 19.

| # | Action | Expected |
|---|---|---|
| 1 | Watch an enemy without firing | Moves down smoothly, exactly as before |
| 2 | Line up under an enemy and fire | The hit visibly registers |
| 3 | Watch the enemy at the moment of a hit | It flashes white then yellow, then returns to its own colour |
| 4 | Keep firing at one centred enemy | It dies on the third volley |
| 5 | Watch the moment it dies | A brief yellow, orange, red flash, then it is gone |
| 6 | Watch the space where it died | No ghost, no leftover sprite, no flicker |
| 7 | Wait for the next enemy to appear | It arrives at full health in its own colour, not the dead one's |
| 8 | Fire at empty sky | Nothing happens anywhere on screen |
| 9 | Move and fire at the same time | Both work; no stutter and no missed hits |
| 10 | Fire while overheating | The gun stops, and stops damaging enemies too |
| 11 | Watch the HUD throughout | Score, lives, upgrade and the heat gauge all stable |
| 12 | Watch the scrolling terrain | Smooth, aperture edges clean |
| 13 | Fire with several enemies on screen at once | Hits land on the nearest one in each cannon's lane |
| 14 | Fire at an enemy near the left or right screen edge | Works the same; no wrap and no corruption |

Check 13 is the one that matters most: it is the proof that collision uses logical
identity rather than a hardware sprite slot. If the wrong enemy ever takes a hit,
note how many were on screen and roughly where they were.

---

*Slice D is complete and automatically green. Full wave and director work has not
been started, and will not be, until Slice D is manually accepted. The next
planned slice is the isolated old level and background graphics migration.*
