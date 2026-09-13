# Migration Slice C — Dynamic Logical Object Pool + the First Real Enemy

**Repository:** `6502-shmup`
**Reference:** `shooter_test` (the old game; the task named it `c64Shooter`)
**Date:** 2026-09-13
**Scope:** a bounded dynamic object pool, the stale sorted-ID fix that had to
come first, and one genuine migrated enemy proving the lifecycle end to end.
**Status:** automated GREEN. **Manual acceptance is the user's to declare, and
this report does not declare it.**

A claim marked **observed** was read out of a source file or off a running
machine. A claim marked **decision** is something this slice chose.

> **Note on the reference repo.** The task gave the old game's path as
> `/Users/brianmorrice/Dev/C64 ASM/c64Shooter`. No such directory exists. The old
> source is at `/Users/brianmorrice/Dev/C64 ASM/shooter_test`, and it is
> byte-identical to the `c64Shooter-main.zip` used for the original audit, so
> every line reference in this report and in the earlier reports still resolves.

---

## 1. What was inspected in the old game

Read out of `shooter_test/src/main.asm` before any Slice C code was written.

| Old routine / table | Line | What it governs |
|---|---|---|
| `findFreeObject` | 4842 | bounded linear allocation, carry set on failure |
| `spawnEnemy` | 4860 | field-by-field initialisation, then activation |
| `OBJECT_*` array block | 5176 | the structure-of-arrays pool layout |
| `moveEnemyPath` | 3055 | per-frame velocity application |
| the bullet release path | 3040 | bounds-test despawn and the double-release guard |
| `updateEnemyPath` release | 3169 | "return this logical object to the free pool" |
| `ingressFragments` | 5918 | the movement vectors, including the simplest one |
| `enemySpriteA` | 5561 | the enemy bitmap |
| `enemyColourSequence` | 5808 | the per-member colours |
| `countActiveEnemies` | 7413 | the active-count utility and its peak tracking |

`MAX_OBJECTS` is 16 at line 551 and `TYPE_ENEMY` is 2 at line 572.

---

## 2. Reusable behaviour and data recovered

**Observed.** Six things were worth taking, and all six are in the new code.

1. **Structure of arrays, indexed by slot.** `OBJECT_X,x` / `OBJECT_Y,x` and so
   on: one indexed load per field, no record stride, no multiply. Kept exactly.
2. **`OBJECT_ACTIVE` is the membership bit**, and a zero there is what returns a
   slot to the pool. Kept, as `logActive`.
3. **Allocation is a bounded linear scan** returning carry set on failure. Kept.
4. **"Mark object active only after every field is initialised."** The old file
   says this twice, at 4922 and 2971. This is why allocation and activation are
   two separate calls in the new pool rather than one.
5. **"Reused slots must not inherit velocity from a previous enemy."** The old
   spawn path hand-zeroes five named fields for this reason.
6. **"Defensive guard against an accidental double release"** (3050). Kept, and
   given a counter so a double free is visible rather than merely survivable.

The enemy's own data recovered: the bitmap, the colour sequence, the straight
dive vector, and the whole-pixel velocity representation.

---

## 3. Old renderer and VIC coupling explicitly rejected

**Decision.** None of the following crossed over.

- **The segmented path machine.** `OBJECT_PATH_STEP`, `OBJECT_STAGE`,
  `OBJECT_MANOEUVRE_STEP`, `OBJECT_EGRESS_STEP`, `OBJECT_TARGET_VEL_*`,
  `OBJECT_ACCEL_TIMER`, `setFragmentPointer` and `easeVelocityTowardTarget`.
  That system *is* the wave migration, and it belongs with the slice that brings
  waves.
- **The damage model.** `OBJECT_HEALTH`, `OBJECT_HIT_TIMER`,
  `OBJECT_DEATH_TIMER`, `OBJECT_BASE_SPRITE` and `OBJECT_BASE_COLOUR`. Nothing
  can shoot an enemy until Slice D, and `OBJECT_BASE_*` exist only to restore a
  colour after an impact flash.
- **Slot 0 reserved for the player.** In this engine the player is not in the
  pool at all: it owns HW0 and HW1 outright and never enters the mux. Slot 0 is
  an ordinary pool slot here.
- **The multicolour art path.** This engine forces `$d01c` to zero, so the old
  bitmap is converted to hires at assembly time rather than at run time.
- **Every form of adaptive slot assignment.** Gameplay does not know that
  hardware sprites exist, and the test suite checks that the words never appear.

---

## 4. The new object-pool layout

**Decision.** `src/objects.asm`, state at `$c580`, code at `$4800`.

| Symbol | Size | Meaning |
|---|---|---|
| `logActive` | `MAX_LOGICAL` (32) | **the** membership bit, and the sorter's only source of truth |
| `objType` | `MAX_OBJECTS` (16) | `TYPE_NONE` = 0, `TYPE_ENEMY` = 1 |
| `objVX` | 16 | signed whole pixels per frame |
| `objVY` | 16 | signed whole pixels per frame |
| `objPeak` | 1 | high-water mark of the active count |
| `objAllocFail` | 1 | allocations refused because the pool was full |
| `objDoubleFree` | 1 | frees of an already-free slot |

Position, pointer and colour are **not** in this table. They live in
`logY`/`logX`/`logXHi`/`logPtr`/`logCol`, which are the presentation view the
sorter and builder already consume. An object's update writes them; that *is*
the render submission.

`logActive` is `MAX_LOGICAL` long rather than `MAX_OBJECTS` long because the
sorter must be able to ask the membership question about any logical ID a
qualification fixture might name, and the P0-P5 fixtures populate all thirty-two.

**Fields deliberately not added:** no `timer`, no `behaviourState`, no `flags`.
The first enemy needs none of them, and the task asked for no speculative
fields. A spawn cadence is a property of the spawner, not of an object.

---

## 5. Allocation and free API

**Decision.** Five calls, all bounded, no heap, no free list.

```
objectInit       every slot free, logCount zero, the sorter marked dirty
objectAlloc      -> carry clear and X = a fully ZEROED free slot
                 -> carry set and the pool untouched if full
objectActivate   slot X joins the active set (idempotent)
objectFree       slot X returns to the pool (idempotent, counted)
objectUpdateAll  one frame of every active object
```

**Allocation and activation are two calls, and that is the old game's rule.**
`objectAlloc` hands back an inactive slot; the caller fills every field; only
then does `objectActivate` make it visible. A half-built object can therefore
never be named by `sortedIDs`, not even for one frame.

**`objectAlloc` zeroes the whole slot**, gameplay fields and presentation
together. The old game hand-zeroed five named fields to stop a reused slot
inheriting a previous enemy's velocity. Naming fields is how such a list goes
stale the first time somebody adds a sixth, so the new code clears the slot
whole.

**Both mutations are idempotent.** Activating an active slot does not
double-count it; freeing a free slot is a counted no-op rather than a
corruption, and `logCount` has an explicit underflow guard.

---

## 6. The active-count and membership model

**Decision.** Two independent representations, deliberately kept separate so
they can be cross-checked:

- `logActive[id]` — **which** logical IDs exist. Written only by
  `objectActivate`, `objectFree` and `sortReset`.
- `logCount` — **how many**. Incremented and decremented by the same routines.

The sorter rebuilds `sortedCount` from `logActive` and then compares it to
`logCount`, raising `sortFault` if they disagree. Because the two values arrive
by different routes, that comparison is a real integrity check rather than a
tautology: it catches a future spawner that sets a membership bit without going
through the API.

Fixtures keep the old prefix model, and `sortReset` is now the one place that is
still true: it writes `logActive[i] = (i < logCount)`. Every existing fixture
therefore behaves exactly as it did.

Production and fixtures are **mutually exclusive populations**. A production boot
loads no fixture; a fixture run spawns no object. Nothing can enforce that at
assembly time because it is a property of which routine the frame calls, so it
is stated in the source and checked by the suite.

---

## 7. The stale sorted-ID bug, exactly

**Observed, and reproduced on the running machine before anything was changed.**

`sortedIDs` is a permutation of **all** logical IDs, and `sortedCount` is a
**window** over its front. The old `sortTick` opened with:

```asm
lda logCount
sta sortedCount
```

and then insertion-sorted only what the window already contained. Order and
membership are different things, and **resizing a window does not change what is
inside it**.

The active set was the implicit prefix `ID < logCount`. That is exactly the
assumption a dynamic pool breaks, because a pool frees slots out of the middle.

Four objects at Y 200, 100, 150, 120 sort to `[1, 3, 2, 0]`. Object 3 despawns,
so the population is three. Measured output from `/tmp/prove_stale.py` against
the unfixed build:

```
logCount 4 -> sortedCount 4, sortedIDs [1, 3, 2, 0]
  Y order: [100, 120, 150, 200]   (ascending, correct)

logCount 3 -> sortedCount 3, sortedIDs [1, 3, 2, 0]
  window considered by buildSchedule: [1, 3, 2]
  STALE ids in the window (>= logCount): [3]
  ACTIVE ids missing from the window:    [0]
```

**One despawn produced both failure modes at once:**

- **ID 3 is despawned and still rendered.** A ghost enemy, drawn from freed
  gameplay state.
- **ID 0 is alive and outside the window.** A live enemy that vanishes.

No fault counter anywhere in the engine rose. The schedule was internally
consistent; it was simply about the wrong set of objects.

---

## 8. The fix

**Decision.** Rebuild the **contents**, never resize a window.

A new `sortRebuild` compacts the active IDs to the front of `sortedIDs` in
ascending order and sets `sortedCount` to how many there were. An ID that is not
active therefore cannot be in the window at all, and an ID that is active cannot
be outside it. The property is **structural** rather than something a caller has
to maintain.

`sortTick` now runs the rebuild only when membership actually changed:

```asm
lda sortDirty
beq !ordered+
jsr sortRebuild
lda #0
sta sortDirty
!ordered:
```

`sortDirty` is set by `objectActivate`, `objectFree` and `sortReset`. **It is not
set when an object merely moves.** A move changes the order, which the persistent
insertion sort already handles for free, so the persistent sort keeps its entire
reason for existing. Only membership-change frames pay for a rebuild, and that
cost is two bounded passes over 32 entries.

The inactive IDs are appended behind the window rather than abandoned, so
`sortedIDs` stays a permutation of `0..MAX_LOGICAL-1` at all times. The sort
never looks past `sortedCount`, so this costs nothing it needs — but P4's
retained tests already assert the permutation property, and a test can say far
more about a permutation than about an array with arbitrary residue in its tail.

**Why this layer.** The alternatives were a compact active-ID list maintained by
the pool, or forcing a full rebuild every frame. The first duplicates
`logActive` and gives two things to keep in step; the second throws away the
persistent sort. This is the smallest change that makes the invariant impossible
to violate from outside.

---

## 9. Sorter invariants, and how each is checked

All ten hold, and each is a named check in `tests/test_slice_c.py`.

| # | Invariant | How it is proven |
|---|---|---|
| 1 | active IDs only | every window entry has `logActive` set |
| 2 | each active object appears at most once | sorted window equals the live set |
| 3 | no inactive object appears | the same check, from the other side |
| 4 | Y order is deterministic | the window's Y values are ascending |
| 5 | equal-Y order is deterministic | four objects forced to one Y sort by logical ID, identically on consecutive frames |
| 6 | shrinking cannot leave stale IDs | three objects freed out of an eight-object window |
| 7 | growing inserts correctly | the population is grown one object at a time and re-checked |
| 8 | 0 → 1 → 0 is safe | counts and membership checked at all three points |
| 9 | slot reuse does not confuse the sort | a freed slot is respawned and must take its new position |
| 10 | not tied to fixture population | the pool populates through its own API, never through `sortReset` |

`sortFault` stayed zero throughout every one of these.

---

## 10. The chosen first enemy

**Decision, following the old game's simplest case.** The straight diver, which
is the first entry in the old ingress table:

```asm
ingressTopStraightShort:
    .byte 48,  0,  2     // duration 48 frames, vx 0, vy 2
```

"Straight dive from common top entry Y", in the old file's own words.

There is **one type**, `TYPE_ENEMY`, and the trajectory is supplied at spawn.
That is also what the old game did: one type, many fragments. It is why a
diagonal variant needs no second type.

| Property | Value | Source |
|---|---|---|
| Descent | 2 pixels per frame | old ingress fragment |
| Bitmap | `enemySpriteA`, flattened to hires | old line 5561 |
| Colours | 2, 6, 10, 7 | old `enemyColourSequence` |
| Spawn Y | 55, the first renderable line | this engine's `MIN_SPRITE_Y` |
| Pointer | `$d9` (`$3640`) | the last free block of VIC bank 0 |

**The art.** The old sprite was multicolour and this engine forces every
hardware sprite to hires, so each two-bit pair becomes two lit pixels if it was
any of the three colours and two blank pixels if it was background. That is a
silhouette, not a recolour: the shape is kept and the internal shading is lost.
It is the honest conversion for a one-layer sprite. The player affords two
layers because it owns two reserved hardware sprites; a mux enemy owns one.

---

## 11. Movement, world semantics and despawn

**Decision: the enemy is screen-space, and that is stated rather than assumed.**

`logY` is a raster line, not a stage row. The enemy does not read the scroller,
does not read `worldProgress`, and does not move with the terrain. The suite
checks that `enemy.asm` names no scroller symbol at all.

This is what the old game did — its enemies were screen-space objects with
velocities, and only the *decision to spawn* came from wave state — and it is
what keeps the boundary compatible with the wave migration. A wave system asks
`worldProgress` **when** to spawn, then hands the object a screen position and a
vector. Nothing in `enemy.asm` has to change for that to work, which is the test
of whether the boundary was drawn in the right place.

**Direction follows Slice A′.** The terrain moves down and the player flies up,
so an enemy that approaches the player comes from the top of the aperture and
descends. `vy` is positive for that reason and no other.

**One despawn rule:** `logY` past `MAX_SPRITE_Y`. Nothing else in the file frees
a slot.

That rule is only a *guarantee* of termination if every enemy descends, so the
spawn table is proven at assembly time: a non-positive `vy` refuses to build,
and so does a spawn X outside the nine-bit world. An enemy that could hold a
pool slot for ever is a build error rather than a run-time surprise.

Measured: spawn at Y 55, descent of exactly 2 per frame, despawn 80 frames later
from Y 225.

---

## 12. The presentation and render boundary

**Decision.** The flow is unchanged from the engine's own contract:

```
logical active objects        objectUpdateAll writes logY/logX/logXHi/logPtr/logCol
        |
presentation values           the logical arrays ARE the presentation view
        |
active sorted logical IDs     sortTick, from logActive
        |
NEXT schedule                 buildSchedule, applying admission
        |
atomic publication            one byte
        |
CURRENT schedule              immutable for the frame
        |
IRQ executor  ->  HW2-HW7
```

**Gameplay owns "active". The renderer owns "renderable this frame."** An object
the builder rejects for Y range, for capacity or for reuse spacing is still
perfectly alive; it simply is not drawn. The suite checks both halves of that
sentence: a pool object poked above the band is absent from the schedule *and*
still present in the sorted window.

Verified at source level, per file: `objects.asm` and `enemy.asm` contain no
store to any `$d0xx` register, no load from one, no write to either sprite
pointer table, and no occurrence of `MUX_FIRST_SLOT`, `MUX_SLOTS`, `schedSlot` or
`bitMask`. Gameplay cannot name a hardware sprite even by accident.

---

## 13. Publication safety across a despawn

**This was the proof that mattered most, and it passes.**

With five enemies alive and a schedule adopted, the test reads the whole CURRENT
buffer, frees an object that CURRENT names **without running a frame**, and reads
CURRENT again. It is byte-identical, and it still names the freed object.

That is the correct outcome. CURRENT is immutable for the frame by contract, the
executor is reading it, and gameplay freeing its own state must not reach into
it. The freed enemy is drawn for the remainder of the frame it was already
committed to — from the schedule's own copy of its position, not from the pool —
and disappears at the next publication.

On the following frame, NEXT no longer contains it and neither does the sorted
window.

**Nothing in the despawn path touches a VIC register, and nothing needs to.** The
sprite is not "turned off": the next schedule simply does not contain it, and
`$d015` is composed from the schedule rather than edited. That is the whole point
of the boundary, and it is why a despawn is safe at any point in the frame.

---

## 14. Pointer and page handling

Verified over ten consecutive frames with four enemies alive:

- every scheduled enemy entry carries the enemy bitmap pointer `$d9`;
- both screen pages were adopted during the run;
- `statPtrMismatch` and `statPageMismatch` stayed zero throughout.

**A note on how this is measured, because the first attempt got it wrong.** The
sprite pointer table is *time-shared*: the HUD owns HW2-HW7 for rasters 4 to 40
and leaves its own pointers (`$c8`..`$d5`) in it, and the mux overwrites them per
batch further down the frame. A main-thread breakpoint lands at an arbitrary
raster, so reading the table there returns whichever owner happened to hold it.
The first version of this check duly "found" a HUD pointer in a gameplay slot and
called it a bug. The check now reads the pointer through the schedule, where it
has one unambiguous value, and relies on `statPtrMismatch` — which the engine
evaluates from inside, every frame — for the destination.

---

## 15. Automated test results

`tests/test_slice_c.py` is new: **93 checks** in nine sections, running in about
35 seconds. It is in `make test` and has its own `make test-slice-c`.

The full gate is green: `test_engine`, `test_slice_a`, `test_slice_a_prime`,
`test_slice_b` and `test_slice_c` together report **341 successful checks in
7m08s**, with no failures anywhere.

Selected measured results:

- **Lifecycle.** Allocation is bounded at 16; the seventeenth is refused, counted
  in `objAllocFail`, and changes no other object. A freed slot is cleared, is the
  one reused, and comes back at Y 55 with nothing inherited. A double free leaves
  the count correct and increments `objDoubleFree`.
- **Membership.** Despawning the **first**, **middle** and **last** sorted object
  each removes it from NEXT on the next frame. Freeing three objects out of an
  eight-object window leaves no stale ID, drops no live object, keeps
  `sortedIDs` a permutation and raises no fault.
- **Equal Y.** Four objects forced to Y 120 sort by logical ID, identically on
  consecutive frames.
- **Empty.** Zero active objects build a valid empty schedule with no overflow.
- **Enemy.** Spawns at 55 with the old spawn X and colour, descends exactly 2 a
  frame, despawns after 80 frames from Y 225, leaves nothing in the schedule.
- **Both X-MSB crossings** occur in ordinary play and the schedule agrees with
  the logical X on every frame: 248 → 256 rightward, 296 → 255 leftward.
- **Firing still emits a shot event with enemies present, and the enemies do not
  react to it.** Collision is Slice D.

### Two probe bugs, and one stale premise in the earlier probes

Recorded because each produced a plausible false result.

1. **A raster-sensitive read of a time-shared table.** Described in section 14.
2. **A weapon check shorter than the fire cadence.** Heat rises while the
   cooldown timer is non-zero, which is Slice B's definition of "firing" and has
   nothing to do with the button. Sampling four frames after release measured the
   tail of the volley and called it a cooling failure.
3. **Slices A, A′ and B assumed production had no gameplay sprites.** That was
   true when they were written and this slice made it false. Their checks now say
   what they always meant: the Slice A probe switches the spawner off and asks
   for an empty mux explicitly, and the Slice A′ and B checks assert "no fixture
   is loaded" rather than "the logical pool is empty". All three are green again.

   This is the honest shape of a migration slice. Three probes broke, none of
   them because the engine got worse, and every break was a premise that had
   quietly become false. Finding them is the point of keeping the earlier probes
   in the gate.

A fourth would-be failure was a self-matching regex: a check that no test writes
a VICE config file matched its own source, which names the file in order to hash
it. It now looks for write operations, not mentions.

---

## 16. Production population ladder

Measured over a 30-frame window at each population, with the population topped up
as objects descend out of the world, so the load is real rather than a frozen
pose. Span is main-thread raster lines after the frame transaction; the PAL frame
is 312 lines and 19,656 cycles.

| Enemies | Span (lines) | ≈ cycles | Accepted | Batches | Overflow | Sort work | Record skips | Sched skips | Overruns |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 90 | 5,670 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 1 | 109 | 6,867 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| 4 | 140 | 8,820 | 4 | 1 | 0 | 0 | 0 | 0 | 0 |
| 8 | 168 | 10,584 | 6 | 1 | 0 | 0 | 0 | 0 | 0 |
| 12 | 185 | 11,655 | 6 | 1 | 0 | 0 | 0 | 0 | 0 |
| 16 | 202 | 12,726 | 6 | 1 | 0 | 0 | 0 | 0 | 0 |

**Reading this honestly.** The cost is well inside the frame at every population
and grows smoothly, which is the useful result. But three columns say the load is
not yet the one that matters:

- **Accepted saturates at 6.** Objects spawned one per frame end up about two
  rasters apart, and the reuse rule needs 33. So beyond six enemies the extra
  ones are admitted to the pool and refused by the builder. The pool is being
  exercised; the *mux* is not.
- **Batches stay at 1** for the same reason: six sprites close together are one
  batch.
- **Sort work is zero** everywhere. Objects descend in lockstep at the same
  velocity, so their relative order never changes and the persistent sort has
  nothing to do — which is the sort behaving exactly as designed, and also the
  easiest possible input for it.

This is first useful production-shaped data, not a qualification. Real waves will
spread enemies in Y and give them different velocities, and that is the load that
will produce multiple batches, genuine slot reuse and non-zero sort work.

`gameOverrun`, `gameSpanOver`, `publishSkip` and `schedBuildDefer` were zero at
every rung. Per the task, RING-SLOW and RING-SHIFT were not touched.

---

## 17. Frame and schedule publication data

| Measure | Result |
|---|---|
| Frame transaction entry | raster 250, every sample |
| Frame-record publication skips | 0 over a free run with enemies live |
| Schedule publications withdrawn mid-build | 0 |
| `statPageMismatch` / `statPtrMismatch` | 0 |
| `statLate` (executor chasing a batch) | 0 |
| `statBatchOverflow` | 0 |
| Admission accounting | accepted + overflow + every reject = the sorted window, exactly |

**The record-skip figure is measured on a free run, not across breakpoints.**
Every stop in the suite parks the machine mid-frame and resumes it somewhere
else, so the main thread can legitimately miss a boundary it would never miss
running normally. An earlier draft counted one such artefact as an engine fault.
Counting the instrument as the thing it measures is how a healthy engine gets
reported as broken.

### A finding: reject attribution is wrong, and it is not Slice C's

While checking that the reject counters still add up, the builder was found to
**file a genuinely overlapping sprite under the wrong counter**. Measured, with
seven objects all comfortably inside the Y band:

| Gap to same-slot predecessor | Counter that moved | Correct? |
|---|---|---|
| 12 (a real overlap, below `SPRITE_HEIGHT`) | `statRejRange` | **no** — nothing was out of Y range |
| 25 (legal on hardware, inside our margin) | `statRejMargin` | yes |
| 40 (clear) | accepted | yes |

The margin test falls through into the label the Y-bounds test jumps to, so gaps
of 0..20 are counted as out-of-range rejects. `statRejUnsafe` is reachable only
on a *negative* gap, which the sorted invariant makes impossible, so it is dead
code.

**Admission itself is correct** — the sprite is rejected either way and nothing
unsafe is ever drawn. Only the attribution is wrong. This is in P3/P4-qualified
code, predates this slice, and changing the counters' meaning could invalidate
their retained tests, so Slice C **measures it, states it, and leaves it**. The
current behaviour is now pinned by a named check so it cannot drift silently.

It matters because Slice C is the first slice where those counters are used to
reason about production populations, and section 16's `rejR` column is not what
its name suggests.

---

## 18. Player, weapon and HUD regressions

All measured with four enemies alive, so they are regressions under the new load
rather than in isolation.

| Check | Result |
|---|---|
| Player movement | one pixel per frame, 160 → 154 over six frames |
| Player slots | both reserved bits published; `$d015` reads `$03` at raster 243 |
| No pool object on a player slot | every scheduled slot ≥ 2 |
| Weapon heat | rises while firing, falls when released |
| HUD heat feed | still exactly the weapon's value |
| `$d017` | zero |
| `$d01c` | zero — every sprite still hires |
| Frame transaction | raster 250 |
| Aperture and page publication | clean over a free run |

The full gate — `test_engine`, `test_slice_a`, `test_slice_a_prime`,
`test_slice_b`, `test_slice_c` — passes.

---

## 19. VICE input-configuration hygiene

**The standing rule is satisfied, and now proven by the suite rather than
asserted.**

Automated runs launch with input settings as **per-process command-line
arguments only**:

```
x64sc -console -default +saveres -pal +sound \
      -joydev1 0 -joydev2 0 +keyset -remotemonitor ...
```

- `+saveres` means resources are **never written back** on exit. Nothing a test
  changes can reach the user's stored settings.
- `-default` keeps the process off those settings in the first place.
- `-joydev1 0 -joydev2 0 +keyset` detach the joystick devices and the keysets for
  **that process**, which is what stops a test stealing host keys. No global
  setting is altered.

Four automated checks enforce this: the three flags are present in the launch
arguments, and no test performs a write operation to anything matching a VICE
config or input file.

In addition the suite **hashes the user's `vicerc` before the run and re-hashes
it after**, and fails if it changed. One config file was found and watched; it is
unchanged.

### Follow-up: `make run` could destroy those settings, and did

A manual regression after this slice reported that fire had stopped working while
movement still did. The weapon code was exonerated by measurement — the whole
path from `$dc00` through `readInput`, `weaponFire`, the heat accumulator and the
HUD gauge was exercised and is correct — and the cause was found in the project's
own manual launch options.

`make run` passed **`-default`**, which means "ignore the user's vicerc". Combined
with any save it does not merely ignore the file, it overwrites it. Measured on a
throwaway config under `/tmp`:

| Flags | Result |
|---|---|
| no `-default`, `-saveres` | `KeySet1Fire` and all four directions survive |
| `-default`, `-saveres` | `KeySet1Fire`, all four directions and `JoyDevice2` **all destroyed** |
| `-default`, `+saveres` | config untouched |

The automated suites are the third row and were never the hazard. The manual
target was the first two: it opens a real window, and a window can save from its
own menu whatever the command line said. `-default` has been removed from
`VICE_OPTS`; the automated suites keep it, paired with `+saveres`.

The same line also passed `+keyset` while offering `JOY2=2` for keyset A —
selecting a control method and then switching it off. Keysets are now enabled
exactly when `JOY2` selects one.

**And the binding itself:** `KeySet1Fire` drives CIA1 `$DC00` bit 4, the only
fire line the hardware has. `KeySet1Fire2` and `Fire3` are extra buttons on
multi-button host controllers and reach no C64 register. A config with four
directions and only `Fire2` moves the ship and never shoots, which is
indistinguishable from a firmware bug until somebody reads the file. The suite
now raises this as an **advisory** — printed loudly, repeated in the summary, and
deliberately not failing the gate, because the gate judges the repository and not
the developer's emulator settings.

No temporary VICE config persisted: the one used for the measurement above was
created under `/tmp` and removed.

---

## 20. VICE process and disk cleanup

**Processes.** Every automated run launches `x64sc` with `-console` under a
retained PID and reaps it in a `try/finally`. Each run printed its own
`launched and reaped` line, and a post-run check reports **vice clear**. No broad
`pkill` was issued, no manual VICE was signalled, and no `open -a` was used.

One self-inflicted incident is worth recording: a second Slice A run was started
while the first was still alive, and it **refused to start** because the port was
already served — `refusing to attach to a VICE this suite did not launch`. The
first run then reaped its own emulator normally. The guard did exactly its job.

**Disk.** Transient probes, logs and captures were written under `/tmp`.

| Measure | Size |
|---|---|
| `du -sh build/` | **76K** — `main.sym`, `main.vs`, `shmup.prg`, and nothing else |
| `du -sh .` | **2.3M** |

---

## 21. Known deferred work

Nothing here is a defect in this slice.

- **Player hitscan collision.** Slice D. The shot event is still emitted every
  volley and still expires unconsumed.
- **The wave and formation system.** The old segmented path machine, which is
  what the deliberately-tiny spawn table is *not*.
- **Reject attribution** (section 17). A pre-existing diagnostic bug, measured
  and pinned, not fixed.
- **A mux-shaped performance load.** Section 16 exercises the pool but saturates
  the builder at six accepted sprites; real waves are what will produce multiple
  batches and genuine reuse.
- **Entering from off-screen.** The renderer will not accept Y below 55, so an
  enemy cannot slide in from above the aperture; it appears at the top line. A
  wave system that wants a slide-in needs the admission rule revisited, not the
  enemy.
- **RING-SLOW and RING-SHIFT judder**, untouched and unaffected.
- **The screen-Y projection constant** in the world contract still needs
  measuring against real terrain.
- **Enemy bullets, turrets, death and respawn, lives, upgrades, score, level
  triggers, audio and editor integration.** None started.

---

## 22. Manual test instructions

**Fifteen checks. Please run these yourself at normal speed.** This report does
not declare manual GREEN.

Joystick in port 2.

| # | Action | Expected |
|---|---|---|
| 1 | Boot and fly around | Player moves and fires exactly as it did before |
| 2 | Watch the heat gauge while firing | Fills, alarms and drains as it did in Slice B |
| 3 | Watch the top of the screen | An enemy appears at the top of the playfield, not above it |
| 4 | Follow one enemy down | Smooth, even descent, no jitter and no stepping |
| 5 | Watch several enemies at once | No flicker on any of them |
| 6 | Look closely at an enemy's shape | Solid silhouette, no torn or corrupted rows |
| 7 | Watch an enemy on the right-hand side | It crosses the middle of the screen without jumping or wrapping |
| 8 | Watch an enemy reach the bottom | It leaves cleanly; nothing is left behind |
| 9 | Keep watching for a minute | Enemies keep coming; the flow does not stop |
| 10 | Look for a ghost after a despawn | No enemy ever freezes or lingers |
| 11 | Watch the spot where an enemy vanished | No flash of an old position when a new enemy appears |
| 12 | Watch the HUD throughout | Score, lives, upgrade and the gauge are all stable |
| 13 | Watch the scrolling terrain | Smooth, and the aperture edges stay clean |
| 14 | Fire straight at an enemy | Nothing happens to it. **This is correct** — collision is Slice D |
| 15 | Wait for a gap with no enemies | The screen is completely clean; the player is unaffected |

The two failure modes this slice exists to prevent are checks 10 and 11: a ghost
that outlives its despawn, and a reused slot flashing at its previous owner's
position. If you see either, the most useful thing to note is whether it happened
as one enemy left or as the next one arrived.

---

*Slice C is complete and automatically green. Player-vs-enemy collision and the
full wave migration have not been started, and will not be, until Slice C is
manually accepted.*
