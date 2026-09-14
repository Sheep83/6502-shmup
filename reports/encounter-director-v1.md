# Encounter Director v1

**Repository:** `/Volumes/SSD/dev/C64/6502-shmup`
**Model:** Opus 5

---

## Status

**The production game now runs two independent enemy waves concurrently**,
each following reusable movement primitives, triggered deterministically off
stage progress, spawning through the ordinary object pool, and drawn by a
renderer that knows nothing about any of it.

| | |
|---|---|
| focused proof | **ALL PASS** — `tests/test_encounter_director.py` |
| regression gate | **ALL PASS** — 4 suites, 72 checks, 0 failures, exit 0 |
| VICE | 4 launched, 4 reaped, `pgrep -fl x64sc` clear |
| production frame health | `gameOverrun`, `publishSkip`, `schedBuildDefer`, `scrollLate`, `edgeLate` all **0** |
| renderer/raster/sorter/scroll | **untouched** |
| manual visual qualification | **the user's to declare** — §9. This report does not declare it |

Measured in seven hundred frames of ordinary play: **80 consecutive frames
with two wave instances active**, **452 frames with enemies of two different
waves on screen together**, a **peak of 7 live enemies**, a full 16-phase arc
traversal, and 19 pool slots returned through the normal lifecycle.

---

## 1. What was there before

`src/enemy.asm` carried a four-entry spawn table cycled on a 48-frame timer.
Its own comment was explicit about what it was:

> *"This is NOT a wave system and is not the seed of one. It exists so that the
> lifecycle runs continuously on a normal boot."*

It did that job for three slices. The inspection also found:

| question | answer as it stood |
|---|---|
| how enemies spawn | `enemySpawnTick` → `enemySpawn`, one table entry per fire, cursor advancing only on success |
| wave timing/state | none — a single global countdown |
| movement | `objVX`/`objVY` added to position every frame, in **whole pixels** |
| generic pool fields | `objType`, `objVX`, `objVY`, `objHP`, `objTimer` + the logical presentation; `objTimer` already dual-purposed for hit flash and death |
| despawn | a single vertical bounds test in `enemyTick`; `objectFree` is the only release path |
| where in `gameFrame` | `objectUpdateAll` early, `enemySpawnTick` late, after the hitscan |
| trigger clock | `worldProgress` — "coarse rows travelled since the stage start", only ever increases, advances once per 8 frames |
| worth retaining? | the *lifecycle discipline* — yes, entirely. The spawn table — no |

**It was replaced rather than wrapped.** A spawner still running underneath a
director would be a second author of the same screen, and the two would fight
over a pool that is already shared with turret projectiles.

## 2. Architecture

```
worldProgress ──► waveTick ──► wave instances ──► objectAlloc ──► the pool
   (scroll)       (director)     (2, fixed)         + primitive      │
                                                                     ▼
                                                              objectUpdateAll
                                                                → enemyTick
                                                                → wmTick
                                                                     │
                                                                     ▼
                                                       sorter → builder → mux
```

Two new files, both main-thread, neither containing the word "sprite" in the
hardware sense:

**`src/movement.asm`** — `$7700` state, `$7800` code (259 bytes). Nine
per-object arrays and three primitives.

**`src/waves.asm`** — `$77a0` state, `$7a00` code (458 bytes). The director,
two wave instances, two wave definitions, the authored trigger list.

### The renderer boundary is intact

Neither file writes a VIC register, names a hardware sprite, touches a raster
batch, consults the schedule, or knows that `$d015` exists. They create and
move ordinary logical objects; the renderer presents whatever is alive,
exactly as it already does for enemies and turret projectiles. The focused
proof and the existing production smoke both assert the pool invariants that
would break first if that were violated.

## 3. Movement primitives

The old model could not express a curve, and the reason is worth stating
because it drove the design: **whole pixels per frame**. The slowest non-zero
speed is one pixel a frame — fifty pixels a second — so a turn built from
whole-pixel velocities changes direction in fifty-pixel-per-second steps. That
is a staircase.

So movement carries a **quarter-pixel velocity with a per-object remainder**:

```
sum   = accumulator + velocity      (velocity in quarter pixels)
delta = sum >> 2                    (ARITHMETIC shift: floors, for negatives)
acc   = sum & 3                     (0..3, carried to the next frame)
```

Exact floor division, no drift, a handful of cycles, and a speed granularity of
12.5 px/s. The sign handling is the whole trick: for `sum = -5`, an arithmetic
shift right by two gives `-2` (floor(−1.25), not −1) and `-5 AND 3 = 3`, and
`-2*4 + 3 = -5`. A logical shift, or "negate-shift-negate", would drift a pixel
every four frames in one direction only and the curve would visibly sag.

| primitive | behaviour |
|---|---|
| `WM_STRAIGHT` | constant velocity for `wmTimer` frames (0 = unbounded), then hands over to `wmNext` |
| `WM_ARC` | 16 phases × 4 frames = 64 frames, turning a velocity vector through 90° at a constant 1.5 px/frame |
| `WM_ARC_MIRROR` | the same turn, handed — `vx` negated, `vy` untouched |
| `WM_EXIT` | constant velocity until the despawn rule |

The arc is a written-out table of `round(6·cos t), round(6·sin t)` rather than a
generated one, so the table a human reads is the table the 6502 executes — and
so the assembly-time proofs are about the real bytes. **Velocity is not reset
on a mode change**, which is what makes STRAIGHT→ARC and ARC→EXIT continuous:
no frame exists on which speed jumps because a mode byte changed.

### Per-enemy state (9 arrays × 16 slots = 144 bytes)

`wmMode`, `wmNext`, `wmPhase`, `wmTimer`, `wmVX`, `wmVY`, `wmAccX`, `wmAccY`,
`wmBaseCol`.

They live at `$7700` rather than beside the pool's own arrays because
`src/objects.asm`'s block at `$c580` runs up against the collision state at
`$c5f3` with nothing to spare. They are indexed by the same slot number and
**cleared by the same `objectZeroSlot`** — that call is in `objects.asm`, not
in `movement.asm`, because "a reused slot inherits nothing" is the *pool's*
invariant, and a pool that delegates it to its users has stopped guaranteeing
anything.

`wmBaseCol` replaced a derivation. `enemyBaseColour` used to recover the hit
flash's restore colour by searching the spawn table for the entry whose
velocity matched — a good trade while a velocity pair identified a trajectory
for life. It does not any more: an enemy's velocity now changes every few
frames as it turns. Stored once at spawn, derivation deleted rather than
patched.

### Termination is proved, not hoped

The single vertical despawn rule still suffices now that enemies curve, and
that is checked at assembly time in two places: `movement.asm` asserts every
arc phase is non-ascending and the last descends strictly; `waves.asm` asserts
no authored wave can launch on an unbounded non-descending vector. Every path
this engine can currently express ends with `vy > 0`.

## 4. The director

### Wave instances — `WAVE_SLOTS = 2`

Structure-of-arrays, like the pool: `wvActive`, `wvDef`, `wvLeft`, `wvTimer`,
`wvIndex`. **Nothing is shared between instances**, which is what lets one
stall on a full pool while the other keeps sending. Raising the limit costs one
constant — every loop is bounded by it, nothing is unrolled.

Per-enemy state is deliberately *not* duplicated into the instance: once a
member is spawned the wave has no further interest in it, and an enemy outlives
its wave by seconds.

### Authored triggers, in `worldProgress` deltas

```
+24 LEFT   +5 RIGHT   +30 LEFT   +5 RIGHT   → wraps
```

**Deltas rather than absolute thresholds**, which is what makes the sequence
repeat for free: the cursor wraps to zero and keeps adding to a monotonically
increasing target, so the whole pattern recurs every 64 coarse rows (≈10.2 s)
with no second table, base offset or special case. Convenient for manual
qualification, which was the brief's ask.

The director holds a cursor and the `worldProgress` at which it fires, so the
per-frame cost is **one 16-bit compare plus a walk of two instances** — it does
not grow with the length of the authored stage.

### The five coarse rows between LEFT and RIGHT are load-bearing

This is the one place the first implementation was wrong, and it is worth
recording because the automated proof is what caught it.

A wave *instance* is active for exactly as long as it is still sending members.
LEFT sends 4 at 28-frame intervals, so it holds its instance ~84 frames. The
gap was authored at **10** coarse rows = 80 frames — and the two waves then
queued politely one after the other, the first instance finishing a few frames
before the second was triggered. The director never held two at once.

The *enemies* still overlapped, because they outlive their wave by seconds. So
the screen looked right. A test that watched only the screen would have passed
it. At **5** rows = 40 frames, RIGHT arrives with LEFT less than half way
through its own spawning:

```
instance overlap window = 84 - 40 = 44 frames  (measured: 80 frames)
```

Measured higher than the arithmetic because deferred spawns stretch a wave —
which is the policy below working as intended.

### Pool pressure: **defer**

The pool is shared with hostile projectiles, so a wave can find it full through
no fault of the encounter design — three turret bolts in the air is an ordinary
state of the world. A member that cannot be allocated **keeps its place**:
`wvLeft` is not decremented, `wvIndex` is not advanced, the timer is set to one
frame, and the same member is tried again next frame. The wave stretches; it
never loses a member and never overwrites a live object. `wvDeferred` counts it.

The alternative — skipping the member — would make the encounter quietly
different every time the pool happened to be busy, which is exactly the
non-determinism that makes authored content impossible to tune.

A **trigger** that finds both instances busy is *dropped*, not queued, and that
asymmetry is deliberate: queueing would let a stall push the authored stage out
of alignment with the terrain it was authored against, and an encounter that
arrives two hundred rows late is worse than one that does not arrive.
`wvDropped` counts it; it was **0** across the whole proof.

## 5. The authored demonstration

| | LEFT SWEEP (def 0) | RIGHT HOOK (def 1) |
|---|---|---|
| members | 4, every 28 frames | 3, every 20 frames |
| enters | X=48, Y=60, fanning right | X=290, Y=72, fanning left |
| colour | light red (10) | cyan (3) |
| path | 40 frames level flight → 90° arc down → exit | immediate mirrored arc → exit |
| on screen | ≈3.5 s per member | ≈2.6 s per member |

They cross rather than trail: LEFT sweeps left-to-right along the top and then
turns down through the arc; RIGHT enters from the opposite corner already
turning. Each member carries its wave's colour, so which wave an enemy belongs
to is visible — which is also what lets the proof use colour as an independent
witness that two waves are really on screen.

## 6. Combat is unchanged

Enemies produced by the director are ordinary `TYPE_ENEMY` objects. The art,
the six HP, the hit flash ladder, the death animation, the single vertical
despawn rule and `objectFree` as the only release path are all exactly as they
were. `src/collision.asm`, `src/turrets.asm`, `src/ebullet.asm` and
`src/player.asm` were not modified at all — the player's hitscan, turret
firing, hostile projectiles and player damage/invulnerability do not know
`src/waves.asm` exists. No enemy firing was added.

## 7. Files changed

```
 Makefile        |  14 +++
 src/ebullet.asm |  12 ++-
 src/enemy.asm   | 276 ++++++-------------------------------------
 src/main.asm    |  21 ++++-
 src/objects.asm |   8 +-
 5 files changed, 104 insertions(+), 227 deletions(-)
 + src/movement.asm, src/waves.asm, tests/test_encounter_director.py  (new)
```

`src/enemy.asm` is **227 lines shorter**: the spawn table, colour table, spawn
cursor, spawn timer, `enemySpawn`, `enemySpawnTick` and the velocity-search
colour derivation all left. `src/ebullet.asm`'s change is one memory guard that
named `enemyColoursEnd`, a table that no longer exists; it now names
`enemyBitmapEnd`, which is what actually sits below it. `src/objects.asm`'s is
the `wmClearSlot` call. `src/main.asm`'s is two imports, `waveInit`, and
`enemySpawnTick` → `waveTick` at the same call site.

**No renderer, raster, sorter or scroll file was touched.**

### Memory

```
$7700-$778f  movement state     $7800-$7903  movement code
$77a0-$77b0  wave state         $7a00-$7bca  wave code
$4900-$4986  enemy code (was $4900-$4a4c)
$c517-$c518  enemy state (was $c517-$c51c)
```

## 8. Testing

### Focused proof — `tests/test_encounter_director.py`, ALL PASS

Everything watches the **real frame loop**. Nothing calls `waveTick`, `wmTick`
or `waveSpawnMember` directly, and nothing pokes wave or movement state to set
a scene — for the reason this repository learned expensively one slice ago,
where sixteen green checks covered a turret subsystem that could not fire a
shot in a real game because every one of them called the tick routine directly
and a routine called in a loop never advances a frame. A director whose entire
job is reacting to scroll progress is exactly what that mistake hides.

Proved, over 700 contiguous production frames:

| # | check | measured |
|---|---|---|
| 1 | authored triggers start waves | 4 activations |
| 2 | **two wave instances active at once** | **80 frames** |
| 3 | ...and they are different definitions | 80 of 80 |
| 4 | the instances advance independently | timers never in lockstep; neither rewrites the other |
| 5 | enemies from both waves coexist | 452 frames with two wave colours live; **peak 7 enemies** |
| 6 | the curved primitive runs | 2584 object-frames in an arc; one enemy followed through all 16 phases |
| 6b | **the arc turns smoothly** | no phase change moves a velocity component by more than one quarter pixel — steps were only (0,0), (0,1), (1,0) |
| 7 | slots return through the pool | 19 despawns; `logCount` peak 8, never over capacity |
| 8 | **deferral engages under a full pool** | pool forced to 16; `wvDeferred` 0 → 144; no member lost, no corruption |
| 9 | engine unharmed | all five fault counters 0 |

### Four bugs found, and where they were

Worth separating, because only one was in the engine:

1. **The authored gap (engine/content).** 10 coarse rows produced zero
   instance overlap. Fixed to 5. §4.
2. **Arc-run tracking across slot reuse (test).** `objectAlloc` hands out the
   lowest free slot, so an enemy despawning at phase 15 (vx 0, vy +6) is often
   replaced in the *same slot* next frame by one starting a fresh arc
   (vx −6, vy 0). Read as one object, that is a (6,6) velocity jump, and the
   first draft duly called the arc unsmooth. Runs now break on slot reuse,
   witnessed by phase going backwards or the wave colour changing.
3. **`wvLeft` continuity (test).** `wvLeft` legitimately jumps from 0 back up
   to a new count when a finished instance is taken over by the next trigger.
   Now only checked while the instance stays active.
4. **The pressure section tested nothing, twice (test).** First draft called
   `objectAlloc` 16 times without `objectActivate` — which reserves nothing, so
   the same slot came back each time and `logCount` reached 2 while the check
   passed. Second draft added the activate but **ignored the carry**:
   `objectAlloc`'s contract is "carry set, and X is then meaningless" (its scan
   leaves X at `MAX_OBJECTS`), so once full it went on to activate logical ID
   16 — which exists, `logActive` being `MAX_LOGICAL` long, but is not a pool
   slot. `logCount` hit 17 and the test called it a capacity breach while the
   engine was behaving exactly as documented. Now it reads `logCount` before
   each attempt, so a free slot provably exists and the allocation cannot fail.

A fifth, avoided by construction: the 120-frame pressure window first landed in
a gap when no wave was mid-spawn, so nothing was deferred and `wvDeferred` read
0 → 0. It now waits for a wave with members still to send before applying
pressure.

### Regression gate — one `make test`, ALL PASS

```
test_boot.py               ALL PASS
test_production.py         ALL PASS
test_turret_regression.py  ALL PASS
test_encounter_director.py ALL PASS
```

**4 suites, 72 checks, 0 failures, exit 0.** 4 VICE instances launched, 4
reaped, `pgrep -fl x64sc` clear afterwards. No historical P0–P5, A/A′/B/C/D or
batch-window suite was run — this slice changed no engine invariant that would
warrant them.

### Gate wall-clock: 6:30, over the ~5 minute guidance — investigated

The brief requires investigating rather than waiting, so:

- **The build is not it**: 0.4 s.
- **CPU is not it**: 85.6 s user + 17.0 s system at 26% — the gate is
  overwhelmingly *waiting*, on VICE monitor round-trips.
- **My test was half of it.** The first gate ran **8:32** with
  `test_encounter_director.py` reading thirteen separate memory ranges per
  frame across 700 frames — roughly 9,100 round trips. The wave-instance
  arrays and the movement arrays are each contiguous by construction, so they
  now come back in **one dump each**: 13 reads per frame became 5, and the
  suite went **5:45 → 3:02**. The contiguity is asserted rather than assumed,
  so a future reordering of either block cannot silently start reporting one
  field's bytes as another's.
- **The residue is the pre-existing session variance** this repository already
  documented in `reports/production-test-suite-rewrite.md` §5: the same three
  older suites measured 167 s in a clean session and materially more later in
  a long one, with CPU time flat throughout. The three inherited suites plus
  my 3:02 account for the 6:30.

Further reduction would mean sampling less often than every frame, and the
smoothness and activation-transition checks need per-frame resolution. The
authored cycle is 512 frames, so 700 is close to the minimum that reliably
spans one whatever phase the run joins at.

## 9. Manual visual qualification — please run this

**Automated tests cannot decide whether the paths look good. This report does
not declare visual GREEN.**

```sh
cd /Volumes/SSD/dev/C64/6502-shmup
make run
```

Comes up on keyset A, port 2, with your own bindings and save-on-exit enabled.
The first wave arrives about four seconds in, and **the whole pattern repeats
every ten seconds**, so nothing needs waiting for.

| # | Look for | Expected |
|---|---|---|
| 1 | **two visibly independent waves overlap** | light-red group sweeping in from the top-left while a cyan group enters top-right — both on screen together, on different paths, not one formation twice |
| 2 | **the curve is smooth** | the turn from horizontal to vertical reads as an arc, not as a few abrupt direction changes |
| 3 | **enemies stay long enough to engage** | roughly 3 seconds on screen; time to line one up and shoot it, not a dive-through |
| 4 | the fan | members of a wave spread out rather than flying single-file |
| 5 | **no hitch** | movement does not stutter, including on the frames a wave is spawning |
| 6 | **destruction during both waves** | shoot members of the red group and the cyan group; three volleys kill, hit flash then death flash, and the slot is reused |
| 7 | turrets and projectiles | still pulse, still fire yellow bolts, still destructible in three hits |
| 8 | player damage | a bolt still costs you the two-second invulnerability blink, and the ship ends solid |
| 9 | terrain and HUD | scrolling, black border and HUD unchanged |
| 10 | **no sprite corruption or flicker** | attributable to this change — some enemies may legitimately not be drawn when many share a raster band, which is the renderer's documented admission behaviour, not corruption |

Checks 1, 2 and 10 are what this slice could most plausibly have got wrong.

## 10. What v1 deliberately is not

No random selection, no difficulty curve, no population budget, no formation
AI, no upgrade carriers, no escorts, no drops, no boss logic, no enemy firing,
no procedural generation, and no loop/orbit/S-curve/Bezier/spline vocabulary.
Three primitives, two definitions, two instances, one authored list.

The extension points are where you would expect them: `WAVE_SLOTS` is one
constant; a new primitive is a mode number and a case in `wmTick`; a new wave
is twelve bytes; a new encounter is two bytes in the trigger list.

## 11. Hygiene

- `pgrep -fl x64sc` checked before every automated session and clear after the
  final gate; every emulator launched with `-console` under a retained PID and
  reaped by that exact PID; no broad `pkill`, no window, no stolen focus.
- No joystick, keyset or controller preference created or modified.
  `~/.config/vice/vicerc` unchanged: `3510a90f…`, before and after.
- `make run`'s manual context untouched — `-saveres`, port 2 = keyset A,
  keysets on, port 1 attached, no `-default`.
- All transient probes and logs lived under `/tmp` and were deleted.

```
du -sh build/   ->   88K     main.sym, main.vs, shmup.prg
du -sh .        ->   3.9M
```

## 12. Git

```
 M Makefile
 M src/ebullet.asm
 M src/enemy.asm
 M src/main.asm
 M src/objects.asm
?? .vscode/settings.json
?? src/movement.asm
?? src/waves.asm
?? tests/test_encounter_director.py
```

```
 Makefile        |  14 +++
 src/ebullet.asm |  12 ++-
 src/enemy.asm   | 276 ++++++--------------------------------
 src/main.asm    |  21 ++++-
 src/objects.asm |   8 +-
 5 files changed, 104 insertions(+), 227 deletions(-)
```

`.vscode/settings.json` is an editor-generated file present before this task
and not touched by it.

**No commits, no pushes.**

---

*Two waves, two instances, three primitives and a quarter-pixel accumulator.
The director asks worldProgress one question a frame, the waves know nothing
about each other, the enemies know nothing about the waves, and the renderer
knows nothing about any of it.*
