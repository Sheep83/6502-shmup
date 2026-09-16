# Token pickups v1 — the flashing `P`

**Date:** 2026-09-16
**Starting HEAD:** `9cc860f4d17c9f07eeeff19daa148f41fc2eb165` — *Enemies firing. Performance to be monitored, some frameskips*
**Starting working tree:** **clean.** The enemy-firing work had been committed; nothing was uncommitted, so nothing needed preserving. Nothing was reset, stashed or cleaned, and **nothing has been committed or pushed**.

> ## ⚠ Read §12 first
> The feature itself is correct and `tests/test_pickup.py` is **ALL PASS**. But a
> paired on/off measurement on one binary shows tokens raise `publishSkip` from
> **1.3 to 6.9 events per 1000 frames** — roughly **5×**, with non-overlapping
> ranges. The brief said to treat a clear material increase as significant and
> stop rather than normalise it, so I stopped: I have not tuned the content down
> to flatter the number, not touched the renderer, and not edited a single
> `publishSkip` assertion. `gameOverrun`, `scrollLate` and both page/pointer
> mismatch counters are **zero in every run of both arms**.

**Final working tree** — two new files, nine modified:

```
 M Makefile                         M src/main.asm      M src/objects.asm
 M src/sfx.asm                      M src/waves.asm
 M tests/test_encounter_director.py M tests/test_enemy_fire.py
 M tests/test_production.py         M tests/test_sfx.py
?? src/pickup.asm                   ?? tests/test_pickup.py
```

---

## 1. Files changed, and why

| file | why |
|---|---|
| **`src/pickup.asm`** *(new, 275 B code)* | the whole feature: art, state, spawn, tick, collect, despawn |
| `src/objects.asm` | `TYPE_PICKUP`, a third arm in `objectUpdateAll`'s dispatch, and `objectZeroSlot` clearing `pkKind` |
| `src/waves.asm` | the authored token column on the trigger list, and the spawn call at the top of `waveStartNext` |
| `src/main.asm` | bank-map documentation, the import, `pickupInit` at cold start, `pickupPlayerTick` in `gameFrame` |
| `src/sfx.asm` | `SFX_TOKEN`, a triangle chime on voice 2 |
| `Makefile` | `test-pickup` target, default-suite entry, and the documentation block the other tests have |
| `tests/test_production.py`, `tests/test_encounter_director.py` | their exhaustive "known object type" lists did not know `TYPE_PICKUP` exists |
| `tests/test_sfx.py` | the new `(SFX_TOKEN, pickup)` hook is legal, voice 2 now carries a third waveform, and the collision segment's upper bound was `$5000` — which the pickup code now sits inside |
| `tests/test_enemy_fire.py` | identified its bolt by "which slot became active", which breaks when a token frees a slot the bolt then reuses in the same frame |

**No `publishSkip` assertion was touched anywhere.** The test edits above are all
"this test's model of the world is missing a thing that now exists".

## 2. Architecture and lifecycle

A token is an **ordinary logical object**. It is allocated from the same
sixteen-slot pool, writes the same `logY/logX/logXHi/logPtr/logCol`, and the
sorter, builder and multiplexer draw it without knowing it is collectible. No
VIC register is written from `src/pickup.asm`, no hardware sprite is reserved,
and `$d01e` is never read.

```
waveStartNext    an authored trigger says a token appears, and where
pickupSpawn      one token, if the pool allows
objectUpdateAll  -> pickupTick: the flash, the drift, the self-despawn
pickupPlayerTick the token meets the ship
pickupCollect    -> the kind's effect, then the slot goes back
```

**One kind today, and the seam for the next one.** `PICKUP_P` is kind 0. What
makes a second kind cheap is that the three things a kind can differ in are
already looked up rather than hard-coded:

| | |
|---|---|
| `pkPtrTab` | which bitmap it wears |
| `pkColTab` | the two colours it flashes between |
| `pickupCollect` | what collecting it *does* |

Everything else — allocation, placement, drift, despawn, the overlap test, the
slot release — is common and written once. A second kind is a row in two tables
and an arm in one branch. There is deliberately **no inventory, no upgrade tree,
no rarity, no drop table and no RNG**, and the P token grants no power-up: it
moves a counter, which is the hook the upgrade system will read when it exists.

The kind lives in `pkKind`, one byte per pool slot, written at spawn and cleared
by `objectZeroSlot` — the same idiom `enySpecies` and `enyFire` already use, and
for the same reason: a slot outlives the thing that authored it.

## 3. Exact Level 1 proof authoring

A **fifth column on the existing trigger list** — a nine-bit X per appearance,
zero meaning "this appearance brings no token":

```asm
.var trigDelta   = List().add(48, 4, 38, 36)
.var trigDef     = List().add(WAVE_DEF_SWEEP, WAVE_DEF_S, WAVE_DEF_LINGER, WAVE_DEF_LOOP)
.var trigSpecies = List().add(SPECIES_RING, SPECIES_DROPPER, SPECIES_RING, SPECIES_DROPPER)
.var trigFire    = List().add(%00000101, %00000010, %00000101, %00000000)
.var trigToken   = List().add(0, 220, 0, 150)          // <- this slice
```

| trigger | at row | wave | token X |
|---|---|---|---|
| 0 | 48 | echelon sweep | none |
| 1 | 52 | S-turn (enters at X=90) | **220** — well right of the formation |
| 2 | 90 | linger and break | none |
| 3 | 126 | loop — the one formation that never shoots | **150** — a calm pass to go and get it |

**The director already owns the only clock this needs.** `worldProgress` and the
trigger cursor are the level's authored progression, so a token is one more
thing an authored moment can bring — a column, not a subsystem. No token timer,
no drop table, no RNG. Two tokens per ~1008-frame cycle, roughly one every eight
seconds.

The spawn sits at the **top of `waveStartNext`, before the instance scan**,
deliberately: if both wave instances are busy the wave is dropped, and a token
dropped with it would make the level quietly different whenever the director
happened to be behind. The two are independent content that share a trigger.

An assembly-time guard rejects a token authored outside the visible playfield
(24..319), since it would drift down behind a border and despawn unseen.

## 4. The placeholder art

**`$2580-$25bf`, 64 bytes, sprite pointer `$96`** — in the free run between the
player's muzzle flash and screen page B, where the engine's other permanent
sprite art already lives (ship `$2000`, muzzle flash `$2400`). A token is
engine-owned content every level has, not level-replaceable artwork, and it is
**not** in the enemy sprite window.

**It is deliberately not at `$3580`,** though that run is equally free and
equally documented. Those four blocks are the Ring's former pinned home and
`tests/test_level_assets.py` asserts all 256 bytes are still zero as proof the
migration to one contiguous enemy window was genuinely completed. I put a token
there first, saw that assertion fail, and **moved the token rather than weaken
the invariant** — the assertion is worth more than the block.

**Multicolour**, because every gameplay sprite in this game is: the renderer
hands HW2..HW7 to the mux with the multicolour bits set, so a hires bitmap would
draw as double-width garbage. Twelve pixel-pairs across:

- pair `01` → `SPR_MC_DARK`, a constant dark badge;
- pair `10` → `logCol`, **the letter — this is what flashes**;
- pair `11` → unused.

The letter flashes and the badge does not, which is what keeps it legible: a
glyph drawn straight onto the playfield would lose its edge against the terrain
greys at whichever flash colour was nearest them. The P is read against the same
background on every frame and the colour change is pure signal.

## 5. The flash

**Derived, not timed.** The phase is bit 4 of the renderer's own `frameCounter`,
so there is no per-token timer byte, no per-token state to reset at spawn, and
every token on screen flashes in step. Sixteen frames lit, sixteen dark — a
1.6 Hz pulse, far slower than the player's four-frame invulnerability blink so
the two cannot be confused.

Colours are **white (1) ↔ light grey (15)**: a pulse in *brightness*, not hue, so
the letter never changes what it looks like, only how hard it is lit. A hue flip
read as two different tokens alternating.

**It writes `logCol` and nothing else** — not `logPtr`, not `objType`, not
`pkKind`, not `logY`. The test samples 40 consecutive frames and asserts the
colour set is exactly `{1, 15}` while the `(type, kind, pointer)` triple is a
single constant value throughout.

## 6. Collision and collection semantics

Software collision in logical coordinates, modelled on `ebulletPlayerTick`, for
the reason that file and `src/collision.asm` both give: the mux time-shares
HW2..HW7, so a VIC collision bit names a *slot* and a slot is not an object.

Both sprites are 24×21, so the box is exactly the two sprites touching, with no
generosity added (`PICKUP_HIT_*` are four one-byte constants if manual play wants
it kinder). Vertical overlap is one biased unsigned compare; horizontal is the
same nine-bit construction the projectile uses.

**Collection is exactly once by construction:** the slot is freed before
`pickupCollect` returns, so the scan that called it cannot see the token again
on that frame and no later frame can either.

**No visibility gate, deliberately, and it is not an omission.** `PLAYER_MIN_Y`
and `PLAYER_MAX_Y` are 55 and 226 — exactly `MIN_SPRITE_Y`/`MAX_SPRITE_Y` — so
the ship is *always* inside the renderable band and a token overlapping it is
necessarily visible. A band test here could never fire; adding one would be dead
code pretending to be a rule.

### An invulnerable player DOES collect tokens

This is an explicit decision, not inherited behaviour. `ebulletPlayerTick`
refuses to test anything while `plyInvuln` is set and is right to — a bolt
should pass through a ship that cannot be hurt — so copying that routine would
have brought the wrong rule with it. `pickupPlayerTick` does not have the test
at all.

**There is no death, no lives system and no respawn in this engine.** `plyInvuln`
is a 100-frame damage-immunity window during which the ship is flying,
controllable, on screen and blinking. Refusing pickups during it would punish
the player twice for being hit and would create a dead zone in which a token
visibly passes through the ship uncollected — which reads as a bug, not a rule.

If a real death/respawn state arrives, *that* is the state that should refuse
collection, and it should refuse by not running this routine at all rather than
by giving `plyInvuln` a second meaning.

## 7. The counter

**`pkTokensP` at `$c4c0`,** one saturating byte. It is persistent *gameplay*
state, not a diagnostic, and it is cleared by `pickupInit` at **cold start
only** — deliberately **not** from `gameInit`. Every other subsystem's init is
safe to re-enter on a restart because it describes the world; this describes the
player, and whether collected tokens survive a future restart is a decision for
the day there is one. Putting it in `gameInit` would have answered that silently,
by accident, in a direction nobody chose.

Nothing in the file acts on its value. It is exposed to tests and the monitor as
an ordinary symbol; **the HUD was not touched**.

Alongside it: `pkSpawned`, `pkDropped`, `pkDespawned`, all saturating.

## 8. Allocation failure policy

`pickupSpawn` returns carry set, increments `pkDropped`, and the token is
**lost — not queued, not retried, not deferred**. This is the policy the two
firing systems already use, for the same reason `src/waves.asm` gives for dropped
triggers: a deferred token would arrive detached from the authored moment,
drifting over terrain it was not authored against, possibly inside the next
formation. That is exactly the non-determinism that makes authored content
impossible to tune.

**It cannot starve anything else.** A token competes for the same sixteen slots
as everything else and is the *last* caller in the frame to ask — the waves, the
turrets and the enemies have all had their turn. A full pool therefore costs a
token rather than an enemy or a bolt, which is the right way round: a missed
collectible is a missed bonus; a missed enemy is a hole in the authored
encounter.

## 9. Object pool and projectile cap

**Maximum additional live object demand from the proof content: exactly 1.**
A token lives from Y=30 to Y=250 at one pixel a frame — **220 frames**. The two
authored moments are 74 coarse rows apart one way (592 frames) and 52 the other
(416 frames), both comfortably longer than a token's life, so **two tokens can
never be alive simultaneously**.

**Measured: `pkDropped` was 0 in every run** — the 5-second health run, both arms
of the A/B probe and the concurrency probe.

**Tokens are not hostile projectiles and do not touch that machinery.**
`TYPE_PICKUP` is a distinct type; `ebCount`, `ebFired` and the cap of 3 are
never read or written by `src/pickup.asm`. The test records `(ebCount, ebFired)`
across a spawn *and* a collection and asserts both are unchanged. `traceRay`
filters on `TYPE_ENEMY`, so the player's own cannon cannot shoot its pickups
down, and a token carries `objHP = 0` so `applyDamage` can never see it.

## 10. Memory cost and headroom

| segment | before | after | delta |
|---|---|---|---|
| **token bitmap** *(new)* | — | `$2580-$25bf` **64 B** | **+64** |
| **pickup code** *(new)* | — | `$4d00-$4e12` **275 B** | **+275** |
| **pickup state** *(new)* | — | `$c4c0-$c4d7` **24 B** | **+24** |
| waves code | `$7c00-$7efa` 763 B | `$7c00-$7f1e` **799 B** | **+36** |
| sfx code | `$1780-$18fb` 380 B | `$1780-$1914` **405 B** | **+25** |
| object pool code | `$4800-$48d3` 212 B | `$4800-$48e0` **225 B** | **+13** |
| main | `$5000-$5293` 660 B | `$5000-$5299` **666 B** | **+6** |
| **total** | | | **+443 B** |

**PRG unchanged at 51,164 bytes** — every segment is fixed-position.

**Headroom after the change:** pickup code 493 B to its `$5000` ceiling; pickup
state **8 B** to the enemy-firing array at `$c4e0` (the tightest thing here, and
guarded); waves 225 B to `$8000`; sfx 1,259 B to `$1e00`; 9 free sprite blocks
left in the `$25c0-$27ff` run. **No VIC-visible, level-replaceable or enemy-window
capacity was consumed**, and `$3580-$367f` remains wholly empty.

**Per-frame cost, counted:** `pickupPlayerTick` walks all sixteen slots at 14
cycles for an inactive one — about **236 cycles on an empty pool, ~1.2% of the
19,656-cycle budget**. That is the honest number; it is not free, and it buys not
having a token counter to keep in step with the pool. `pickupTick` is ~50 cycles
per live token (flash plus drift), and there is at most one.

**Crucially, that per-frame cost is *not* what §12 measures.** The tokens-off arm
of the A/B still pays the full `pickupPlayerTick` walk and the extra dispatch
arm; the two arms differ only in whether tokens *exist*. The regression is
therefore attributable to the on-screen object — its sorter entry, its schedule
entry, its mux slot — and not to the code added to the frame.

## 11. SFX

`SFX_TOKEN` (id 5) on **voice 2**: a **triangle** — the one waveform nothing else
uses, since fire and destruction are noise, the enemy shot is pulse and the hurt
wail is sawtooth. A **rising** chime, 800→2400 Hz over 6 frames (~120 ms), attack
0 into a 168 ms decay. Every other effect in the game falls; a reward is the one
thing that should go up, and the direction alone says it was good news.

**It is not on voice 1, though this module's own v1.1 note predicted "a pickup
chime joins voice 1 with the other light traffic".** Measured against the game
that now exists, that would be inaudible: held fire retriggers voice 1 every
eight frames and the report occupies five of them, so a chime started there is
cut within three frames whenever the player is shooting — which is almost always.
**Voice 3 was rejected for the opposite reason:** it would work, but it would cut
the player-damage wail, and losing the one sound that says *you have been hit* to
a bonus chime is the worst trade available. Voice 2 loses only an occasional
enemy noise.

## 12. ⚠ `publishSkip`: a clear material increase, measured and not normalised

**The probe.** One binary, one runtime switch: `src/waves.asm` reads the authored
token column fresh at every trigger, so zeroing those eight bytes at boot
disables every future token without touching another instruction. Same code,
same level, same encounter schedule, same held-fire input. Arms alternated so
host drift is shared. 8 seconds each, three pairs.

| arm | publishSkip | frames | **skips per 1000 frames** |
|---|---|---|---|
| tokens **OFF** | 6, 7, 14 | ~7,000 each | **0.8, 1.0, 2.0** — mean **1.3** |
| tokens **ON** | 72, 102, 33 | 10.9k, 10.8k, 7.1k | **6.6, 9.5, 4.7** — mean **6.9** |

**Roughly 5×, and the ranges do not overlap** — the best ON run (4.7) is more
than twice the worst OFF run (2.0). This is not noise.

**Everything else stayed at zero in both arms:** `gameOverrun`, `scrollLate`,
`statPageMismatch`, `statPtrMismatch` — 0/0/0 across all six runs.

**For scale:** 6.9 per 1000 frames is **0.7% of frames**, and `publishSkip` means
one frame's record was not adopted — a single-frame scroll hitch, not a stall.
The accepted pre-token baseline was ~0.13%.

**The likely mechanism, stated as a hypothesis and not as a finding:** a token is
a large 24×21 sprite that descends the *entire* aperture at one pixel a frame, so
it is on screen for 220 consecutive frames and crosses the raster band of every
other object on the way. A slow, tall sprite is the hardest case for a
multiplexer's reuse windows. I did **not** investigate further, because doing so
means renderer/mux work that this brief rules out.

**What I did not do:** I did not reduce the authored token count, slow the spawn
rate or speed up the descent to flatten the number — that would be normalising
exactly what the brief said to stop on. I did not touch the renderer, the mux or
the raster code. I did not edit a single `publishSkip` assertion.

**The cheap levers, if you want them,** are all content rather than architecture:
one authored token per cycle instead of two (halves on-screen time), or a faster
descent (breaks "carried by the scroll"). Both are one-line changes in
`src/waves.asm` / `src/pickup.asm`.

## 13. Tests run, and exact results

Every suite, once, on the final binary:

| suite | result |
|---|---|
| `test_boot` | **ALL PASS** |
| `test_production` | FAIL — `publishSkip` 50 |
| `test_turret_regression` | **ALL PASS** |
| `test_encounter_director` | FAIL — `publishSkip` 110; plus two sampling failures, see below |
| `test_player_ship` | FAIL — `publishSkip` 53 |
| `test_level_assets` | FAIL — `publishSkip` 127 |
| `test_sfx` | FAIL — `publishSkip` 57; plus one intermittent, see below |
| `test_enemy_fire` | **ALL PASS** |
| **`test_pickup`** | **ALL PASS** |

`tests/test_pickup.py` proves, in order: the authored column reads back exactly;
a trigger with no token spawns none; a trigger with one spawns exactly one at the
authored X above the aperture, as `TYPE_PICKUP` kind `P` wearing pointer `$96`,
with `vy=1`, `vx=0`, `hp=0`; it descends exactly one pixel per frame through
`objectUpdateAll`; it flashes `{1,15}` while its `(type, kind, pointer)` never
moves; it despawns itself past the aperture and returns its slot whole; the ship
collects it once, the counter moves by one, the slot comes back, and three more
frames cannot collect it again; `(ebCount, ebFired)` are untouched throughout; an
inactive slot forged to look exactly like a token on the ship collects nothing; a
genuinely full pool refuses cleanly with `pkDropped +1`, `pkSpawned` unmoved and
no double-free; and the director keeps running afterwards.

### Two non-`publishSkip` failures, investigated rather than assumed

**`test_encounter_director`: "two wave instances active concurrently" and
"enemies from two wave definitions on screen together".** These looked like a
real regression in the authored overlap, so I measured it directly — sampling
`wvActive` every frame for 1400 frames, tokens on vs off, same binary:

```
tokens OFF: both-active  59 frames   waves started 5   dropped 0   deferred 0
tokens ON : both-active  68 frames   waves started 6   dropped 0   deferred 0
```

**The overlap is intact and if anything slightly more frequent with tokens.** The
test's own sampling loop advances with a bare breakpoint stop, which can return
without a frame having elapsed; under the increased load it covers fewer real
frames than it counts and misses the ~35-frame overlap window. I did not edit
that test — its sampling design is pre-existing and out of scope here.

**`test_sfx`: "idle is ONE state on all three" — intermittent.** That test builds
a quiet window by making the ship invulnerable and releasing the trigger, which
silences the gun and enemy firing. It does not silence *tokens*: collection is
deliberately not gated on `plyInvuln` (§6), so a token drifting onto the parked
ship plays a chime on voice 2 mid-window. This is my design decision interacting
with the test's assumption, it passed on two of three runs, and I left it alone
rather than quietly change either side. **You should decide** whether the quiet
window should park the ship clear of tokens.

## 14. VICE, process and build hygiene

`pgrep -fl x64sc` **before: nothing. After: nothing.** Every launch used
`-console` and `+saveres`, never `-default`, launched directly with no focus
theft and no joystick-disable override. Each run owned and reaped its exact PID —
the harness prints `launched and reaped` per run, and every run in this task did,
including the three scratch probes, which used their own ports (6690-6701). No
broad `pkill`/`killall`; no manual VICE session existed to endanger.

No temporary logs or captures were left in `/tmp`. The three probe scripts live
in the session scratchpad, not the repository. `build/` holds only the three
fixed artifacts it always holds — no per-run or per-test outputs:

```
du -sh build/     88K        (shmup.prg, main.sym, main.vs)
du -sh .          5.6M
```

## 15. Limitations and deferred work

1. **§12 is unexplained and unfixed** — the one thing standing between this and a
   clean result, and the reason to read this report before playing.
2. **The P grants no power-up.** By design; the counter is the hook.
3. **One kind, one flash cadence, one descent speed.** The seam exists; nothing
   exercises it, so the second kind will be the first real test of it.
4. **`pickupInit` is cold-start only**, so there is no answer yet to "do tokens
   survive a restart" — deliberately, because there is no restart.
5. **The art is a placeholder** and says so in the source.
6. **`pickupPlayerTick` walks all sixteen slots every frame** (~236 cycles, 1.2%
   of a frame) rather than gating on a live-token counter.
7. **Pickup state has 8 bytes of headroom** before the enemy-firing array; a
   second kind needing per-object state will want a new home.

## 16. Manual VICE checklist

1. **Where to expect them.** Two per ~20-second cycle: one arriving with the
   **S-turn** formation at the **right-hand side** (X≈220), one with the **loop**
   formation **mid-screen** (X≈150). The loop is the formation that never shoots,
   so that second token is a deliberately calm pass.
2. **Is it unmistakably a `P`?** It enters through the top edge and descends the
   full screen. Check it reads as a P over terrain at every point of its fall.
3. **Is the flash right?** White ↔ light grey, about 1.6 Hz. Restrained and
   readable, or too subtle / too busy? It should never be confusable with the
   ship's own faster invulnerability blink.
4. **Coexistence.** Watch a token descend through a formation while enemies are
   firing and turrets are active. Any sprite flicker, dropout or visible
   reordering when the token crosses other sprites' raster bands?
5. **Collection feel.** The hitbox is exactly the two sprites touching, with no
   generosity. Does it collect when you can see you hit it, and refuse when you
   can see you missed? Kinder is four one-byte constants.
6. **Clean disappearance.** On collection it should vanish instantly and
   completely — no half-frame ghost, no stuck sprite.
7. **Clean off-screen exit.** Let one fall past the bottom uncollected. It should
   leave without a flicker and without disturbing anything else.
8. **⚠ THE SCROLL, most of all.** This is the §12 question. Compare the
   background scroll while a token is on screen against a gap with no token.
   Look for single-frame hitches. **If the scroll looks clean to you, that
   materially changes what to do about §12; if it stutters noticeably when
   tokens are up, that is the bug to chase before more content goes in.**
9. **The chime.** A short rising triangle on collection. Distinct from your own
   gun, the enemy spit and the destruction crunch — all of which share voice 2
   with it except the gun. Listen for a collection that coincides with an enemy
   dying: one will cut the other.

## 17. Recommended next step

**Decide about §12 from what you see in the scroll**, before any more content.
The measurement says tokens cost about five times the publication headroom that
the accepted enemy-firing baseline did; whether that is visible is the thing
only you can settle. If it is invisible, the cost is affordable and the next
slice is what the P is *for* — the weapon-upgrade effect behind `pkTokensP`. If
it is visible, the mux's handling of a slow full-height sprite is the thing to
look at, and that is a renderer conversation this brief deliberately kept closed.
