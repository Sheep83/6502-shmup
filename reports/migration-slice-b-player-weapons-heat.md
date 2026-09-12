# Migration Slice B — Player Weapons, Heat, and a Live HUD Feed

**Repository:** `6502-shmup`
**Date:** 2026-09-12
**Scope:** the player's gun — fire cadence, heat accumulation, overheat lockout, a
logical shot event for a future collision system, muzzle feedback, and the real
heat value driving the existing 48-pixel HUD gauge.
**Status:** automated GREEN. **Manual acceptance is the user's to declare, and this
report does not declare it.**

Throughout, a claim marked **observed** was read out of a source file or off a
running machine. A claim marked **decision** is something this slice chose.

---

## 1. What was inspected in the old game

Everything below was read out of `c64Shooter-main/src/main.asm` before a line of
Slice B was written. Nothing was recalled from the earlier audit.

| Old routine | Line | What it governs |
|---|---|---|
| `updatePlayerFire` | 2418 | the fire test, the three refusals, both cannon rays |
| `updatePlayerCombatEffects` | 2690 | per-frame decrement of the cadence and muzzle timers |
| `updateWeaponHeat` | 9964 | the heat accumulator, the ceiling, the lockout latch |
| `refreshHeatGaugeIfDirty` | 10039 | heat to pixels, the alarm flash, the dirty test |
| `composeHeatGauge` | 10106 | the old gauge bitmap composition |
| `publishHeatBuffer` | 10157 | the old double-buffered gauge publication |
| `tracePlayerCannon` | — | the hitscan ray walk against the object list |

The constants were read from two blocks, `main.asm:941-947` and `main.asm:991-994`:

```
HEAT_MAX             = 300      HEAT_REENABLE        = 150
HEAT_RISE_PER_FRAME  = 2        HEAT_FALL_PER_FRAME  = 3
HEAT_FLASH_PERIOD    = 8        PLAYER_FIRE_COOLDOWN = 8
PLAYER_MUZZLE_TIME   = 3        PLAYER_COLOUR_NORMAL = 14
PLAYER_COLOUR_MUZZLE = 2        PLAYER_LEFT_CANNON_X = 4
                                PLAYER_RIGHT_CANNON_X = 19
```

Every one of those values is carried into this slice unchanged. The old file's own
comment block at `main.asm:935-937` states the three derived timings, and those are
the timings the automated probe now measures on the new implementation.

The old constants block opens with a note worth preserving verbatim, because it
describes an intent this slice also honours: the values were centralised "so a
later upgrade screen can change capacity, cooling rate or sustained-fire duration
without touching the fire code. No upgrade machinery is built now."

---

## 2. Recovered firing behaviour

**Observed, and all five points are load-bearing.**

1. **Fire is level-triggered, not edge-triggered.** `updatePlayerFire` tests the
   joystick bit with no press/release history whatsoever. Holding the button fires
   a volley every cadence period for as long as it is held. A tap and a hold differ
   only in how long the button stays down.
2. **The cadence is eight frames.** A successful volley arms the cooldown timer to
   8; the timer decrements once per frame; the fire test refuses while it is
   non-zero. The next volley therefore lands exactly eight frames later.
3. **Both cannons fire together.** One volley traces the left ray and then the
   right ray, in the same call, in the same frame. They are never alternated. Each
   resolved independently against its own nearest target, which is how a single
   volley could deal nothing, one hit, or two.
4. **The weapon is true hitscan.** `tracePlayerCannon` walked the logical object
   list and returned a target. No projectile object was ever allocated for the
   player's gun. (Enemy bullets *were* objects — but that is the enemies' weapon,
   not this one.)
5. **The refusals are ordered.** Lockout first, then cadence, then the button.
   The lockout returning *before* the cadence is armed is the entire reason a held
   button cannot extend an overheat.

---

## 3. Recovered heat, cooling and overheat behaviour

**Observed.**

- **Heat is per frame, not per shot.** `updateWeaponHeat` adds the rise whenever
  the cadence timer is non-zero. The old file defines the term explicitly: "'The
  weapon is firing' is defined as `PLAYER_FIRE_COOLDOWN_TIMER != 0`. That timer is
  only ever armed by a SUCCESSFUL volley, so heat tracks actual firing rather than
  the button." Held fire keeps the timer non-zero every frame, so held fire is +2
  every frame.
- **Cooling never overlaps rising.** The accumulator is strictly either/or:
  locked means cooling, not firing means cooling, otherwise rising. There is no
  frame on which both happen.
- **The lock is a latch with two different thresholds.** It sets at 300 and clears
  at 150. The asymmetry is the mechanic: an overheat costs a full second before the
  gun works again and two before the gauge is empty.
- **The unlock is inclusive.** The old code compares against `HEAT_REENABLE + 1`
  so the unlock happens *on* the frame heat reaches 150, not the frame after. That
  is what makes the lockout exactly 50 frames rather than 51.

The three derived timings, all three now measured on the new build:

| Transition | Rate | Frames | PAL seconds |
|---|---|---|---|
| 0 to 300 | +2/frame | 150 | 3.0 |
| 300 to 150 (firing re-enabled) | −3/frame | 50 | 1.0 |
| 300 to 0 (fully cold) | −3/frame | 100 | 2.0 |

---

## 4. What was deliberately not carried across

**Decision.** Four things were left behind, each for a stated reason.

- **`tracePlayerCannon`, `hitCannonTarget`, `damageEnemy`.** There are no enemies
  yet, and a ray test belongs with the object pool it walks. What survives is the
  *event*: where the rays are and when they happen. The walk arrives in Slice D.
- **The `PLAYER_STATE == ALIVE` gate.** The old fire routine opened with it. There
  is no player state machine yet. The comment at the top of `weaponFire` marks the
  exact line where Slice F's single branch goes.
- **Every line of the old HUD gauge.** `composeHeatGauge`, `publishHeatBuffer`,
  the double-buffered bitmap pair, the `hudProofPtr` publication and the `sei`/`cli`
  around the colour write. This engine's `src/hud.asm` already does all of that,
  correctly and under its own qualified raster window. Slice B sets values; it
  draws nothing.
- **Upgrade machinery.** None existed to copy, and none was invented.

One thing was deliberately carried across *as structure* rather than as code: the
old gauge's dirty test compared the **drawn width**, not the heat value, and
skipped all composition when the picture was identical. That cost model is
reproduced exactly in `weaponHudFeed`.

---

## 5. The new logical weapon state

**Decision.** Thirteen bytes at `$c570`, main thread only, outside VIC bank 0 with
everything else this migration owns. Declared in `src/weapon.asm`.

| Symbol | Bytes | Meaning |
|---|---|---|
| `wpnHeatLo` / `wpnHeatHi` | 2 | heat, 0..300, sixteen bits |
| `wpnOverheated` | 1 | 1 = locked out until heat falls to 150 |
| `wpnCooldown` | 1 | frames until the next volley may fire |
| `wpnFlashTimer` | 1 | alarm flash half-cycle countdown |
| `wpnFlashPhase` | 1 | 0 = not flashing, 1 = bright, 2 = dark |
| `shotFired` | 1 | 1 for exactly the frame a volley resolves |
| `shotRays` | 1 | valid entries in the ray arrays |
| `shotXLo` / `shotXHi` | 4 | ray origin X, nine bits, one pair per ray |
| `shotY` | 1 | shared origin Y for both rays |

`wpnCooldown` being non-zero is the definition of "the weapon is firing", and
therefore of what heats the gun. That is the old game's definition, kept.

`wpnFlashPhase` has three states rather than being a bare toggle. The old file
explains why in as many words, and the reason is worth repeating: a two-state
toggle cannot distinguish "is the flash running at all" from "which half are we
in", and that confusion is what lets a `dec` run on a zero timer, wrap it to 255,
and stall the flash for five seconds.

The segment carries a growth guard: the state must end before `$c600`, where the
P3 fixture data begins.

---

## 6. The shot-event contract

**Decision.** This is the interface Slice D's collision system will consume, and
it is designed so that neither side has to remember anything.

```
shotFired   1 for exactly the frame a volley resolves
shotRays    how many of the ray slots below are valid
shotXLo[]   ray origin X, nine bits, one entry per ray
shotXHi[]
shotY       shared origin Y; both rays leave the ship at the same height
```

Three properties make it safe:

- **`weaponTick` clears `shotFired` at the top of every frame** and sets it only on
  a legal shot. A consumer running after `weaponTick` in the same frame sees it.
  Nothing has to remember to clear it, and nothing has to look at the joystick to
  learn that a shot happened.
- **The rays are an array with a count**, not two named pairs. "This volley
  produced these rays" is what a hitscan test actually walks. This is not a
  disguised upgrade system: there is one weapon, and it has two barrels.
- **The event expires unused.** Nothing consumes it in this slice, and that is
  fine — it is overwritten at the next `weaponTick`.

---

## 7. Production update order

**Observed in `src/main.asm:333`.** The order inside `gameFrame`:

```
hudTick                 the displayed page, before scrollTick can change it
readInput               $dc00 -> joyState
playerTick              joyState -> plyX / plyXHi / plyY
weaponTick              cadence, heat, overheat, shot event
weaponHudFeed           real heat -> the HUD's logical heat
playerEmit              -> plyPres, and plyDirty if anything changed
hudDemoTick             score, lives, upgrade only
[motionTick]            qualification fixtures only
[sort / build / publish if dirty]
regenTick / scrollTick / gameSpan
```

Two orderings are load-bearing and both are asserted by the probe:

- **`weaponTick` after `playerTick`** so a volley's ray origins use this frame's
  ship position, not last frame's.
- **`playerEmit` after `weaponTick`** so the muzzle flash that `weaponTick` raised
  is published on its own frame rather than one frame late.

Inside `weaponTick` the internal order is also load-bearing, and reproduces the
order the old game ran across its frame: timers down, then try to fire, then heat.
Heat after the fire test is what makes a volley heat the gun on its own frame.
The fire test reading a latch that the accumulator set *last* frame is what stops a
ghost volley escaping on the frame the gun overheats. Keeping both steps in one
routine preserves that cross-frame relationship instead of losing it to a refactor.

---

## 8. Cannon behaviour

**Observed in the old game, reproduced exactly.** Both cannons fire on the same
frame, at the same Y, from a single volley. The X origins are the ship's X plus 4
and plus 19, computed in nine bits so a volley fired at the right-hand edge of the
screen carries correct high bits rather than wrapping.

Measured on the running machine with the ship parked at X 160: the two ray origins
read 164 and 179, and `shotY` equals `plyY` on the same frame.

The rays are recorded and then nothing walks them. That is the intended end state
for this slice.

---

## 9. Heat arithmetic

**Decision, following the old game.** Heat is a 16-bit little-endian pair because
the ceiling is 300 and a byte cannot hold it. Every path is bounded at both ends:

- **Rising** adds 2 with carry into the high byte, then tests the ceiling. The
  cheap exit comes first: 300 has a high byte of 1, so any heat below 256 cannot
  have reached the ceiling, and that covers most of a three-second burst. On
  reaching it, heat is **saturated to exactly 300** and the lockout latches.
- **Cooling** subtracts 3 with borrow, then tests **the sign of the high byte**.
  That test is the important one: 1 − 3 leaves `$ff` in the high byte, and treating
  that as a large positive number is precisely how a gauge ends up full at zero
  heat. On a negative result both bytes are forced to zero.
- **Assembly-time guards** reject a re-enable threshold at or above the ceiling,
  and reject a ceiling that could wrap sixteen bits.

Measured boundaries, all on the running machine:

| From | To | What it proves |
|---|---|---|
| 3 | 0 | exact landing on zero |
| 2 | 0 | clamped, not wrapped |
| 1 | 0 | clamped, not wrapped |
| 256 | 253 | borrow across the byte boundary |
| 255 | 252 | no borrow |
| 258 | 255 | borrow across the byte boundary |
| 600 | 300 | an out-of-range value clamps down to the ceiling |

---

## 10. The overheat state machine

**Observed and reproduced.** Two thresholds, one latch.

```
        heat reaches 300                 heat reaches 150
  RUN ────────────────────> LOCKED ────────────────────> RUN
   +2/frame while firing     −3/frame always, even
   −3/frame otherwise        with the button held
```

While locked: `weaponFire` returns before arming the cadence, so no shot event is
emitted, the cadence timer stays at zero, and **no heat is generated**. A held
button therefore cannot extend a lockout. Heat falls at the full rate throughout.

Measured: the lock latches on the exact frame heat reaches 300; heat saturates at
300 rather than passing it; across the lockout no shot event is emitted and the
cadence timer is zero on every frame; heat falls from 297 to 228 with fire held;
the lock clears *on* heat 150 and is still set at 151; firing resumes immediately
afterwards.

---

## 11. The HUD heat-feed path

**Decision.** The whole gameplay-to-HUD boundary for this slice is two bytes of
value, one dirty bit, and a colour:

```
wpnHeatLo/Hi ──> hudHeatLo/Hi ──> hudHeatPixels ──> compare to hudHeatPix
                                                     └─> HUD_DIRTY_HEAT
wpnOverheated ──> flash state machine ──> hudSetHeatColour ──> hudCol[1], hudCol[2]
```

`weaponHudFeed` writes no bitmap, touches no VIC register, and does not draw. The
HUD's own `hudUpdate` draws, from the idle spin, inside the raster window it
already refuses to leave (`HUD_SAFE_LO` 56 to `HUD_SAFE_HI` 200).

**The dirty bit is set only when the drawn pixel count would change**, not when the
value changes. 300 units map onto 48 pixels, so the bar needs redrawing roughly
every sixth unit. Setting the bit every frame would make the HUD do real work on
frames where the picture is byte-identical. This is the old game's cost model and
the HUD's own; it is preserved rather than reinvented.

The alarm flash writes the colour through `hudSetHeatColour`, which sets both
gauge halves (HW3 and HW4) from one accumulator. It is written **once** on the
frame the flash stops, not on every unlocked frame — the probe now checks that
one-shot property explicitly, having previously been fooled by a stale byte.

The demo heat ramp and its direction variable were removed from `hudDemoTick`.
Score, lives and upgrade remain on demo values, because those systems do not exist
yet.

---

## 12. Scaling 0..300 onto 0..48 pixels

**Observed in the old game and reproduced.** The old code's own comment states the
method: "width = table[heat >> 2], 0..48. A lookup, not a divide: the mapping is
heat * 48 / 300."

`hudHeatPixels` does exactly that. It shifts the 16-bit heat right twice, turning
0..300 into an index 0..75, rejects anything above 1023 as nonsense input,
saturates the index at 75 rather than indexing off the end of the table, and
returns the table entry. **No division, no loop, and no data-dependent path** — the
cost is identical at every heat value, which is what lets the HUD keep its bounded
cost model.

Measured properties of the resulting mapping:

| Property | Result |
|---|---|
| Endpoints | `tbl[0] = 0`, `tbl[75] = 48` |
| Monotonic | yes, no reversals |
| Linearity | within 0.48 px of the ideal line, worst case |
| Never exceeds the gauge | max 48 px |

Six exact spot checks confirmed the HUD's logical heat equals the weapon's at
heat 1, 75, 149, 150, 226 and 299.

The full bar is a genuinely one-frame event, and the probe had to be corrected to
see it: heat 300 latches the lockout and begins cooling on the very next frame.
The trace through the peak reads `heat [294, 296, 298, 300, 297, 294, ...]` against
`px [47, 47, 47, 48, 47, 47, ...]`.

---

## 13. Muzzle feedback

**Decision, and it costs no new sprite slot.** The old game flashed the player's
hull red for three frames on each volley. That is reproduced here without adding a
sprite, without touching the six-slot mux, and without any new publication path.

The player's art emitter gained a **third bitmap block** — a firing hull — bringing
the player's art to `$3580-$363f`. `playerEmit` selects between two pointer/colour
pairs depending on whether `plyMuzzle` is running:

| State | Pointer | Colour |
|---|---|---|
| Resting | `$d6` | 14, light blue |
| Firing | `$d8` | 2, red |

The overlay (trim) layer is unchanged between the two, and that is not a hope — it
is proved at assembly time. The art emitter walks all 63 bitmap rows and raises a
`.error` if the firing bitmap changes a single trim pixel, which would mean the
flash needed its own trim block and its own slot budget.

The flash reaches the screen through the **existing** Slice A publication path with
no new mechanism at all. The 10-byte presentation block was designed in Slice A so
that a later slice could change a pointer or a colour without remembering to set a
flag; Slice B is the slice that exercises it, and it worked as designed.

Measured on the running machine: resting frames publish `($d6, 14)` and flashing
frames publish `($d8, 2)`, on both player slots, with the trim pointer identical
across both. `plyMuzzle` counts 3, 2, 1, 0 and rests until the next volley.

---

## 14. Automated test results

**All four probes pass.** `make test` reports 247 successful checks in 6m22s, with
no failures anywhere. The Slice B probe contributes 83 of those across nine
sections.

| Probe | Result |
|---|---|
| `tests/test_engine.py` | ALL PASS |
| `tests/test_slice_a.py` | ALL PASS |
| `tests/test_slice_a_prime.py` | ALL PASS |
| `tests/test_slice_b.py` | ALL PASS — 83 checks |

The Slice B sections are: idle, firing, released, overheat, boundaries, HUD scale,
muzzle art, prior-slice regression, and a timing attribution.

Selected measured traces, all read off the running machine at a single verified
instant per frame:

- **Held fire.** `fired [1,0,0,0,0,0,0,0,1,...]` against
  `cooldown [8,7,6,5,4,3,2,1,8,...]` and `heat [2,4,6,...]` — a volley every eight
  frames, exactly.
- **Muzzle.** `muzzle [3,2,1,0,0,0,0,0,3,...]`, in step with the cadence.
- **Rays.** X 164 and 179 for a ship at X 160; `shotY == plyY`.
- **Cooling.** exactly −3 per frame when released; exactly +2 per frame when
  firing; never both on one frame.
- **Lockout.** latches at exactly 300; no shot events and zero cadence throughout;
  heat 297 falling to 228 with the button held; unlock exactly on 150, still locked
  at 151; gauge colour `$02` while locked, restored to `$07` on the unlock frame
  and not rewritten afterwards.
- **Movement independence.** the player still moves one pixel per frame, moving
  does not heat the gun, and moving while firing does both (X 159 to 144, heat 2 to
  32 over the same run).

### Three probe bugs found and fixed

Recorded because each one produced a *plausible* false result, and the pattern is
the same one this project has now been bitten by four times.

1. **Mismatched instants.** The first draft read weapon heat inside a stepped run
   and HUD heat after it, and reported the feed as thirteen frames out of date. It
   was not. Everything is now read in a single snapshot.
2. **A breakpoint one call too early.** Stopping at `playerEmit`'s entry sees the
   *previous* frame's presentation block, which made the muzzle flash look as
   though it was never published. The probe now stops at `hudDemoTick`, the first
   call after `playerEmit`, where the weapon, the HUD feed and the published block
   are all this frame's.
3. **A check passing on residue.** The gauge-colour restore was read several
   frames after the transition, so it was actually observing a byte left behind by
   an earlier section. It now watches the transition itself and asserts the
   one-shot property in both directions.

The probe's runtime was also cut from 10m15s to 1m58s by reducing monitor round
trips — three bulk reads per sample instead of six, and a single verified frame
step for the many checks that only need one frame. That took the whole gate from
10m15s to **6m22s**, which matters: a gate nobody wants to run is a gate that stops
being run. The check count did not drop; only the round trips did.

Reducing a trace to a single frame is exactly what exposed bug 3 above, so the
speed-up and the correctness fix came out of the same change.

---

## 15. Timing

**Measured on the running machine**, by breaking at named raster phases and
reading the span counters the engine already maintains.

| Condition | Main-thread span |
|---|---|
| Idle | 94 raster lines |
| Moving | 93 raster lines |
| Firing | 97 raster lines |

Roughly 6,111 cycles of the PAL frame's 19,656. `gameOverrun` 0, `gameSpanOver` 0,
`publishSkip` 0 in every condition.

The three-state measurement exists because an earlier draft asserted a guessed
bound of six lines and measured thirteen. The reason is that moving also
republishes the schedule, so idle-to-firing conflates two costs. Comparing
**firing against moving** attributes the weapon's own cost, and the probe asserts
that difference is within four lines. It measures 4.

---

## 16. HUD and raster regressions

**All clean**, re-measured on this build rather than assumed.

| Check | Result |
|---|---|
| Frame transaction entry | raster 250 |
| Top split | raster 54 or 55, `edgeLate` 0 |
| Bottom split | 248, 248 |
| HUD phase | enters 4, 4; exits 11 |
| Handoff phase | enters 40, 40; exits 41 |
| `$d015` at raster 243 | `$03` — both reserved player slots |
| `$d017` | never non-zero |
| Zero-page and pointer-table mismatches | none |

The HUD still owns HW2 to HW7 across rasters 4 to 40, still writes bitmap data only
from the idle spin inside its safe window, and the gauge colour is the only HUD
byte this slice writes.

---

## 17. Aperture and page regressions

**All clean.** The blank-charset aperture, the double-buffered pages and the
per-frame pointer patching are untouched by this slice, and the Slice A′ probe
confirms it end to end: the aperture opens and closes on the qualified rasters, the
adopted page's pointer table is the only one written, and the scroller's world
contract continues to advance.

The fall-through assertion added in Slice A′ — that `scrollPublish` still falls
directly into `publishFrame` — remains in place and still holds. That assertion
exists because of the most serious regression of this migration, and it is cheap
insurance on every build.

No weapon or HUD code writes a sprite register, a pointer table, border state,
`$d015`, or any raster state. That ownership line is stated at the top of
`src/weapon.asm` and enforced by the renderer's compile-time assertions.

---

## 18. Known deferred work

Nothing here is a defect in this slice. Each item is named so it is not
rediscovered later as a surprise.

- **The hitscan walk itself.** The rays are published and nothing consumes them.
  This is Slice D, and it is blocked behind the enemy object pool.
- **The sorter's stale-ID behaviour.** Still the stated prerequisite for a dynamic
  enemy pool in Slice C.
- **The player-state gate.** `weaponFire` has a marked insertion point for the one
  branch Slice F will add.
- **RING-SLOW and RING-SHIFT judder.** The roughly 12% frame-record publication
  skip under 16-sprite moving load, carried from the engine qualification's §10.
  Untouched and unaffected by this slice.
- **Realistic 6 to 16 sprite qualification** with real gameplay objects rather
  than synthetic ring fixtures.
- **The screen-Y projection constant** in the world contract still needs measuring
  against real terrain.
- **Terrain, turrets and the editor ABI.**
- **Upgrades.** Deliberately not pre-built. The constants are centralised so an
  upgrade screen can change them later without touching fire code, which is exactly
  where the old game left it.

---

## 19. VICE and disk hygiene

**VICE.** Every automated run launches `x64sc` with `-console` under a retained
PID, and reaps it explicitly on exit. The final Slice B run logged
`[vice] reaped pid 90285 (rc=-15)` and `launched and reaped: [90285]`. A post-run
process check reports **vice clear**. No broad `pkill` was issued at any point, no
manual VICE instance was signalled, and no `open -a` was used.

**Disk.** Transient logs and captures were written under `/tmp` and the session
scratchpad. No per-run artifacts accumulate under `build/`.

| Measure | Size |
|---|---|
| `du -sh build/` | **76K** — `main.sym`, `main.vs`, `shmup.prg`, and nothing else |
| `du -sh .` | **1.9M** |

Seven stale polling shells left behind by earlier turns of this session were also
found still running and terminated by explicit PID. They were neither emulators nor
tests: each was a wait loop whose own command line matched the pattern it was
waiting on, so it could never exit on its own.

---

## 20. Manual test instructions

**Fifteen checks. Please run these yourself.** This report does not and will not
declare manual GREEN — that judgement is yours.

Build and start the emulator normally, with a joystick in **port 2**.

| # | Action | Expected |
|---|---|---|
| 1 | Boot and leave the stick alone | Ship sits still, gauge empty, no flicker on any HUD element |
| 2 | Tap fire once | Hull flashes red briefly and returns to light blue; gauge nudges up by about one pixel |
| 3 | Tap fire repeatedly, fast | Flashes come no faster than roughly six per second; the gun ignores taps between volleys |
| 4 | Hold fire and count | Gauge fills smoothly and reaches full after about three seconds |
| 5 | Keep holding at full | Gauge turns red and flashes; the hull stops flashing entirely |
| 6 | Keep holding through the flash | Gauge keeps draining while red; holding the button does not keep it full |
| 7 | Keep holding until it unlocks | Firing resumes on its own, at about half a gauge, and the gauge returns to its normal colour |
| 8 | Release at half heat and wait | Gauge drains to empty in about two seconds and stays empty |
| 9 | Move left and right without firing | Ship moves smoothly; gauge stays empty |
| 10 | Move and fire together | Both work; no stutter, no dropped flashes, no tearing on the ship |
| 11 | Fire at the far left edge | Flash and movement both correct; no wrap or corruption |
| 12 | Fire at the far right edge | Same — this is the nine-bit X path |
| 13 | Fire at the top and bottom of the movement range | Ship stays whole; no sprite fragments at the aperture edges |
| 14 | Watch the scrolling terrain while firing continuously | Scroll stays smooth; no new judder introduced by firing |
| 15 | Watch the top-border HUD while overheating | Score, lives and upgrade are undisturbed; only the heat gauge changes colour |

If any of these looks wrong, the most useful thing to capture is **what the gauge
and the hull were doing at the same moment**, since almost every failure mode in
this slice shows up as those two disagreeing.

---

*Slice B is complete and automatically green. Enemy pools, collision, waves, enemy
bullets, turrets, death and respawn, upgrades and game-state work have not been
started, and will not be, until Slice B is manually accepted.*
