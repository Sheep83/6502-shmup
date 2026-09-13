# Turret Combat: Pulse, Player Hits, Damage, Destruction, Restore

**Repository:** `/Volumes/SSD/dev/C64/6502-shmup` (Mac mini)
**Reference:** `~/Desktop/c64Shooter-main.zip`
**Date:** 2026-09-13
**Status:** automated GREEN. The population-8 capacity that the first version of
this slice cost was **bought back, not re-bounded** — see §10a and §12.4.
**Manual visual qualification is the user's to declare, and this report does not
declare it.**

The static turrets are now destructible targets for the player's existing
hitscan: they pulse as the old game's did, they can be hit, hits flash,
repeated hits destroy them, and a destroyed turret's cells become the correct
underlying terrain on both pages and stay that way. **Turret firing and turret
bullets are not migrated** — see §13.

---

## 1. The old combat constants and semantics, recovered

Everything below was read out of `~/Desktop/c64Shooter-main.zip`,
`src/background_turrets.asm`, and every one of them is checked against that
archive by `tests/test_turret_combat.py` on every run rather than trusted here.

| what | value | old source |
|---|---|---|
| `TURRET_START_HEALTH` | **3** | `background_turrets.asm:41` |
| `TURRET_PULSE_LEN` | 4 | `:45` |
| `TURRET_PULSE_INTERVAL` | **8** gameplay frames | `:46` |
| `turretPulseTable` | **1, 2, 7, 2** — white, red, yellow, red | `:747` |
| `TURRET_HIT_CRAM` | **10 \| 8** = 18, light red | `:45` |
| `TURRET_HIT_FRAMES` | **4** frames | `:44` |
| player-shot hitbox | **16 pixels**, `turretX .. turretX+15` | `traceTurretCannon`, `cmp #16` |
| score on destruction | `SCORE_PER_KILL` = **100**, same as an enemy | `hitCannonTarget` → `awardKillScore` |

The three values the previous slice recorded — the pulse table, the interval
and the hit colour — were correct, and are now verified rather than remembered.
**Health was not among them and was recovered from source: 3, not 6.**

### The hitbox is the body, and is narrower than an enemy's

`traceTurretCannon` tests the nine-bit `rayX - turretX` and accepts a low byte
below **16**, where `tracePlayerCannon` accepts below **24**. So a turret's
hitbox is exactly its 2x2 character body and an enemy's is the full sprite
width. That difference is deliberate in the old game and is reproduced.

### The arbitration rule, and the tie

`tracePlayerCannon` scanned every enemy and then called `traceTurretCannon` to
**extend the same nearest-Y result** rather than run a second competition. The
turret test is `bcc` *and* `beq` to the reject path — a turret must beat the
incumbent **strictly** — where the enemy scan's own test replaces an equal
incumbent. Therefore:

```
one winner per ray
nearest wins, and nearest means GREATEST Y
AN ENEMY WINS AN EXACT TIE
```

The old file says so in its own words: *"Extend the existing nearest-Y hitscan
result; high-bit tags are pool slot IDs. An enemy wins an exact-origin tie."*

### Eligibility

`traceTurretCannon` required the slot admitted, `TURRET_HEALTH != 0`,
`TURRET_VISIBLE != 0`, and `TURRET_Y < OBJECT_Y` (strictly above the ship,
because the ray travels up). `TURRET_VISIBLE` was set by
`positionBackgroundTurrets` only while *"the full 16-pixel body is visible"* —
a **combat** predicate, explicitly distinct from whether the body is drawn.

There is no separate minimum-Y test as the enemy scan has: the visibility gate
already excludes anything not wholly on the playfield.

### Destruction

`hitCannonTarget` decrements health, refuses to underflow, and on reaching zero
goes **straight** to destruction — the killing hit does **not** set the flash
timer. It then marked the authored placement dead so it stayed dead across
evict/re-admit/stage loop, and awarded the kill score.

### What was recovered and deliberately NOT migrated

- **The slot-streaming pool.** `TURRET_POOL`, `TURRET_SLOT_AUTH`,
  `TURRET_STREAM_CURSOR`, admit/evict, `markTurretDestroyed`'s
  `turretDestroyedBits`, and `TURRET_STREAM_REWIND`. All of it existed to
  decide which turrets owned one of eight shared *glyph slots*. This engine has
  no such resource to hand out — a turret is composed into the page from its
  authored index — so every array here is indexed by the authored index
  directly. A turret cannot change identity, cannot be evicted mid-flash, and
  needs no bitmap to keep it dead across a re-admission that never happens.
- **`turretGroundCodes`.** The old engine cached the four terrain codes each
  body covered, at admission time, because it poked turret cells into a live
  screen it could not regenerate. Here the terrain is a pure function of the
  stage row — see §7.
- **`updateEnemyHealthSprite`'s turret equivalent.** There isn't one; turrets
  had no health bar.
- **The score itself.** See §14.

---

## 2. Runtime turret state added

Seven byte-arrays of eight and five globals. `turretAlive` is unchanged from
the presentation slice and is still the switch the whole restoration contract
turns on.

| state | width | meaning |
|---|---|---|
| `turretAlive` | 8 | 1 = standing. **THE** restoration switch |
| `turretHealth` | 8 | `TURRET_START_HEALTH` down to 0 |
| `turretHitTimer` | 8 | frames of hit flash remaining |
| `turretLogY` | 8 | derived: the sprite Y covering the body's top pixel row |
| `turretVisible` | 8 | derived: the whole body is inside the aperture. **Combat** gate |
| `turretPaintRow` | 8 | derived: first body row on the page, or `$ff`. **Presentation** gate |
| `turretPaintPair` | 8 | derived: is the second body row on the page too |
| `turretCramRow` | 8 | what colour RAM currently holds — the whole of "put the colour back" |
| `trtPulseTimer/Index/Colour` | 3 | **one** global pulse phase for every turret, as the old game had it |
| `trtDeadPending` | 1 | one bit a turret: destroyed, and the pages have not caught up |
| `trtKills` | 1 | turrets destroyed, for a future score system |

Plus two assembly-time tables the presentation slice did not need:
`turretRowLo/Hi` (the authored top body row, so combat can ask "where is turret
3" rather than "what is in stage row S"), and `turretXLo/Hi` — the body's left
edge in sprite X, **constant**, because the playfield scrolls vertically only.

**No generic entity framework, and nothing in the object pool.** Eight authored
turrets, eight-entry arrays, indexed directly.

---

## 3. Collision ordering and dual-cannon semantics

The brief's questions, answered explicitly:

| question | answer |
|---|---|
| does nearest target win? | **Yes** — greatest Y, across enemies and turrets together |
| enemies before turrets, or the reverse? | **Enemies first**, and that ordering *is* the tie-break |
| can one cannon ray hit one target only? | **Yes.** One winner per ray |
| can the two rays hit two different targets? | **Yes**, independently |
| can both rays damage the same turret in one volley? | **Yes** — 2 HP |

`traceRay` is unchanged up to the end of its enemy scan; it then calls
`traceTurretRay`, which can only *replace* an incumbent it beats strictly.
**With no turret in a ray's path the answer is bit-for-bit what Slice D gave.**
`applyDamage` gained a two-instruction dispatch on `csTargetKind`.

The cannons are 15 pixels apart (`PLAYER_CANNON_L = 4`, `_R = 19`) and the
turret body is 16 wide, so both rays are inside one turret only when the ship
is aligned to within a single pixel — rare, reachable, and exactly what the old
geometry produced. With 3 health that means a turret dies in **two volleys**
when the player is lined up and three otherwise.

**Slice D's enemy contract is untouched.** The enemy scan, its 24-pixel hitbox,
its `HITSCAN_MIN_Y` gate and its highest-slot-wins tie are all exactly as they
were, and every behavioural assertion in `test_slice_d.py` passes unaltered.
What changed in that file is its ladder's *reporting*, not any bound — §12.4.

---

## 4. World → screen hitbox derivation

**From the engine contract, with no second scroll counter.** `turretRelRow`
takes a page's top stage row as an argument and computes the contract's own
relation:

```
matrix row == (authored row - that page's top row) mod STAGE_ROWS
```

The caller supplies `stageTopRow` for the displayed page or `regenTopRow` for
the one being rebuilt. Both are the scroller's, read-only.

`turretWorldTick` runs **before** `collisionTick`, which is where the old game
put `positionBackgroundTurrets` (*"derive positions from the PRESENTED
origin/phase, after coarse finish and before the player's hitscan"*). That
costs nothing to arrange here: `scrollTick` runs at the *end* of `gameFrame`,
so `stageTopRow` and `scrollFine` describe the picture on screen for the whole
frame. Nothing is latched.

### The one scale

```
matrix row m occupies rasters  48 + scrollFine + 8m .. +7     (contract §8a)
a VIC sprite at Y = n covers   n+1 .. n+21                    (contract §3)

  =>   turretLogY = 47 + scrollFine + 8m
```

That is the sprite Y a sprite would need to cover the body's top pixel row, and
it exists so the hitscan can compare a background character against a sprite on
one scale without either side knowing what the other is made of. The old game's
`rel*8 + 64 + RASTER_DISPLAY_FINE` encodes an aperture this engine does not
have, so the constants were re-derived rather than copied.

### Visibility: the old rule, re-derived

*"Combat only while the full 16-pixel body is visible."* The aperture is
rasters 55..247, so with `top = 48 + fine + 8m`:

```
top >= 55        and        top + 15 <= 247
```

Which gives a hittable window of **22 or 23 matrix rows**, sliding down one row
as the fine scroll advances 0 → 7 (1..23 at fine 0, 0..22 at fine 7). 193
aperture rasters is 24.125 character rows, so how many whole 16-pixel bodies
fit depends on the phase; that is geometry, not a tolerance.

**Only a visible, living turret participates. Off-screen world objects are
never hittable**, and the test fires at one to prove it.

### Drawing is a different question

A body straddling an aperture edge is still **drawn** — `turretOverlayRow`
gates on the stage row alone — so its colour must still be painted. It is not
**hittable**, because half of it is outside the aperture. The old game gated
colour on the combat predicate, and a turret entering or leaving rendered in
flat terrain colour until its whole body was inside; that is what its
four-turret-cluster forensics chased down. `turretPaintRow` answers the drawing
question and `turretVisible` answers the combat one, and the test asserts that
the drawn window is strictly wider than the hittable one.

### The horizontal

`turretXLo/Hi = 24 + column * 8`, built by the assembler and constant — the
same formula as the old `turretAuthXLo`. The test is the nine-bit
`rayX - turretX` with a zero high byte and a low byte below 16.

---

## 5. Pulse implementation

**One global phase for every turret**, as the old game had it, so two turrets
on screen together pulse in step:

```
dec trtPulseTimer -> reload 8, step the index 0..3
trtPulseColour = turretPulseTable[index] | $08
```

`| $08` keeps the multicolour selector bit; the dome is bit pair 11, which is
the colour RAM nibble. `turretInit` sets the timer to 1 and the index to 0, so
the first colour a player ever sees is phase 1 (red) — exactly what
`initBackgroundTurrets` did.

### Colour RAM stays a one-value contract

`src/terrain.asm` fills colour RAM with one level-global value at init and
never touches it again, and **this slice does not change that**. The only cells
ever written afterwards are the 2x2 of a turret on screen, and they are written
back to `TERRAIN_COLOUR_RAM` the moment the body leaves them or dies. So there
is no per-cell colour map, no second copy and no ABI. The invariant is:

> every colour RAM cell is `TERRAIN_COLOUR_RAM`, except the cells named by
> `turretCramRow` for a turret that is alive and on the page

and `turretCramRow` is the whole of the bookkeeping that makes it true. Each
frame, `turretPaintTick` compares the turret's new target row against it; if
they differ it gives the old cells back to the terrain colour and stores the
new one, then paints. That is one byte per turret and it handles scrolling,
page flips, entering, leaving and dying with no special case for any of them:

- **follows the body while scrolling** — the target row is recomputed every
  frame from the displayed page's origin;
- **vacated cells restored** — the compare-and-give-back above;
- **newly visible cells get the current phase** — they are painted from
  `trtPulseColour` on the frame they first appear;
- **page flips leave nothing stale** — colour RAM is not per-page; it is
  indexed by matrix row, and the matrix row is what the compare tracks;
- **dead turrets stop pulsing** — a dead turret's target becomes "nowhere",
  which *is* the vacate path. Destruction needs no colour code of its own.

**The restore always writes both rows and the paint never does.** Giving the
terrain colour back to a cell that already holds it costs four cycles and
cannot be wrong; painting turret colour onto a terrain cell is visible. The two
disagree for exactly one coarse step as a body leaves the bottom edge, and the
asymmetry is what makes that step safe without tracking last frame's pair flag.

### Why colour may be written mid-frame

The VIC latches a row's colour RAM once, in that row's badline c-access, and
holds it for all eight raster lines. A write therefore either lands before that
row's badline and shows this frame, or after it and shows the next — **never
inside a character**. So `turretPaintTick` runs right after `collisionTick`,
and a hit flashes on the frame the shot resolved.

---

## 6. Hit-flash implementation

A survivable hit sets `turretHitTimer = TURRET_HIT_FRAMES` and nothing else;
`turretPaintTick` prefers `TURRET_HIT_CRAM` over `trtPulseColour` while the
timer is non-zero, and the timer decays one frame at a time. When it expires
the next paint uses the pulse colour again, at whatever phase the global
counter has reached — there is no second phase to resynchronise.

Because the flash is *only* a colour choice inside the ordinary paint, it can
never outlive its cells: the body scrolling away, dying, or leaving the
aperture all go through the same vacate path, and none of them cares whether
the turret was flashing.

**One deliberate deviation.** The old game decayed the hit timer only while the
turret was combat-visible, so a turret that scrolled off mid-flash froze its
timer and flashed again when it came back. Here it decays for any living
turret. A turret can only be *hit* while visible, so the only behaviour this
changes is that stale re-flash, and the cost is the same four cycles.

---

## 7. Destruction and displayed-page restoration

### The logical half is immediate

`turretDamage` clears `turretAlive`, clears the hit timer, counts the kill and
sets the turret's bit in `trtDeadPending`. Clearing the byte is the whole of
the gameplay state change and the whole of the restoration contract: **every
future page regeneration now omits the body**, because `turretOverlayRow` gates
on it.

### The pixels are repaired at a point whose safety is not a function of load

The main loop is paced by the frame counter, which the renderer increments in
`exFrame` at raster 250 — so `gameFrame`'s **first** instruction runs in the
lower border, below the playfield, with the whole of the next picture's matrix
fetch still ahead of it. Every row of both pages can be written freely there.
By `collisionTick`, forty to eighty raster lines later, that is no longer
unconditionally true, and how much later moves with the frame's load.

So a kill **flags** itself and `turretRestoreTick` repairs it at the top of the
next frame — **at most one frame, 20 ms**, which the brief explicitly permits
and which the old game reached the same way (its own revert ran from
`publishTurretGlyphs`, *"at frame start, beam still in the border"*).

On an ordinary frame the whole cost is `lda trtDeadPending / bne` — **12
cycles**.

### Both pages, and neither blindly

The hidden page is rebuilt a few rows at a time across the eight frames between
coarse steps, so a turret killed now may already have been composed into rows
the back page wrote long before — rows that are *behind* the regeneration
cursor and will not be rewritten before the page flips. Repairing only the
displayed page would make the body reappear for a whole coarse cycle at the
next flip.

So both are repaired, each against **its own** top row: `stageTopRow` for the
displayed page, `regenTopRow` for the one being rebuilt. And the back page is
repaired only up to `regenRow`: rows at or above it have not been written this
cycle and are about to be written with `turretAlive` already clear, so
repairing them is work whose result is immediately recomputed. At `regenRow` 0
that skips the back page entirely, and it halves the cost — 2,290 cycles
against 4,605 (§10).

### What is written is the authoritative decode

The repair calls **`renderTerrainRow`** — the same routine that builds every
page row — for the body's stage rows, with `scrPtr` pointed at the page and row
in question. It writes the forty terrain codes that row has always had, with no
turret overlay, because `turretOverlayRow` is not called.

**There is no `turretGroundCodes` here and there does not need to be.** The
terrain is a pure function of the stage row, so it can always be recomputed and
can never be stale. Re-rendering a whole row rather than four cells costs more
and is worth it: it is the engine's own tested decode, it needs no second
implementation of the metatile arithmetic, and no other turret can share those
rows — the build guard forbids two turrets in one metatile row.

### One turret a frame, and that is a measurement

Repairing one turret on both pages costs 4,605–5,567 cycles. Two in the same
frame measured **9,354–11,057**, which on top of a worst-case main thread of
about 9,800 does not fit in a PAL frame's 19,656 and would show up as a missed
frame. Two turrets can only die together when one volley's two rays each land
a last HP on a different body — rare, reachable, and not worth an overrun. The
second waits one more frame.

### The colour goes with the characters, not before them

A turret killed this frame still has its body on both pages until the repair
runs, so dropping its colour immediately would show the dome in flat terrain
colour for exactly one frame. `turretPaintTick` therefore keeps painting a dead
turret while its `trtDeadPending` bit is still set, and the body and its colour
disappear together. There is no intermediate state to see.

---

## 8. Production files changed

The presentation slice was committed as `c466b5f "Turrets added"` between the
two tasks, so everything below is a change on top of that commit. **Nothing in
this task was committed or pushed.**

| file | change |
|---|---|
| `src/turrets.asm` | the combat constants, `turretRowLo/Hi` and `turretXLo/Hi`, `turretPulseTable`, the combat state, `turretRelRow`, `turretWorldTick`, `turretPaintTick`, `paintTurretCells`, `traceTurretRay`, `turretDamage`, `turretRestoreTick`, `turretRepairPage`, `turretRepairRow`; `turretInit` extended. State moved $6e00, code moved $6f00 |
| `src/collision.asm` | `CS_KIND_ENEMY/TURRET` and `csTargetKind`; `traceRay` calls `traceTurretRay` after the enemy scan; `applyDamage` dispatches. **The enemy scan itself is untouched** |
| `src/main.asm` | `APERTURE_TOP_RASTER` / `APERTURE_BOT_RASTER`; `turretRestoreTick` first in `gameFrame`, `turretWorldTick` before `collisionTick`, `turretPaintTick` after it |
| `src/scroll.asm` | **comment and guards only, no code.** The build now fails if `ROWS_PER_TICK` ever changes so that regeneration fills all eight frames, because §10a's preparation depends on the one it leaves idle |
| `docs/ENGINE_CONTRACT.md` | new §8d (turret combat); §9a notes that a ray's winner is an index and a kind |
| `Makefile` | `test-turret-combat`, and `test_turret_combat.py` in `make test` |
| `tests/test_slice_b.py` | the firing-frame budget bound, 28 → 34 — see below |
| `tests/test_slice_c.py` | `statLate` added to the free-run counter reset (§12.3); `20c`'s zero-margin bound, re-evaluated after §10a and retained (§12.2) |
| `tests/test_slice_d.py` | the ladder prints `gameOverrun` and `gameSpanOver` separately instead of summed, and the sustainability predicate tests the fault (§12.4). **No population-8 bound was relaxed.** |

`src/terrain.asm`, `src/renderer.asm`, `src/enemy.asm`, `src/objects.asm`,
`src/weapon.asm` and `src/player.asm` are **unchanged by this slice**, and
`src/scroll.asm` gains no instruction — only the guard above.

### One existing test bound was raised, and it is worth stating why

`tests/test_slice_b.py` asserts that a *firing* frame costs a bounded amount
more than a *moving* one. That bound is not a correctness check; it is a budget
check whose scope has grown once already — Slice D widened it from "the volley"
to "the volley and both cannon scans" when it put the hitscan on that frame,
and said so in the comment. This slice widens it again for the same reason:
`traceRay` now ends by walking all eight authored turrets once per cannon, so a
firing frame carries two sixteen-slot object scans **and** two eight-turret
scans. Measured at **30** raster lines against the 26 the bound was set at; the
bound moved 28 → 34 with the attribution recorded next to it.

Nothing was weakened to make a change pass: the check still catches a hitscan
that started doing work per *frame* rather than per *volley*, which is what it
is for. `turretWorldTick` and `turretPaintTick` run on every frame, so they are
inside the "moving" span too and cancel out of this difference entirely — they
show up in §10's `gameSpanMax` instead, which is where per-frame cost belongs.

---

## 9. Focused tests

**`tests/test_turret_combat.py`** — new, in `make test`, with
`make test-turret-combat`. Four sections, one VICE launched and reaped.

**1. Every constant is the old engine's own**, read out of the archive: health,
the pulse table and interval, the flash colour and duration, the 16-pixel
hitbox out of `traceTurretCannon` itself, the alive-and-visible gates, the
strictly-nearer test that gives an enemy the tie, one-HP-and-never-underflow,
that the killing hit does *not* flash, and the score value out of the old
`main.asm`. Then that `src/turrets.asm` restates every one of them, and that
the hitbox is *derived* from the body rather than restated.

**2. World → screen**, against an independent model: the contract's own
relation; that a turret walks a contiguous run of matrix rows; that the
hittable window is 22–23 rows and never contains a row the aperture clips; that
the drawn window is strictly wider than the hittable one and contains it; that
**at most two turrets can be hittable or painted at once in level 1**; and the
body's sprite-X span.

**3. Ownership**: `turrets.asm` still writes no VIC register and does not name
one; never mentions `objectAlloc/Activate/Free`, `logActive`, `logCount`,
`logY`, `logPtr`, `sortedIDs`, `schedBatches`, `MUX_`, `spritePtr`, `$d015` or
`$d01e`; colour RAM is reached from exactly one routine; `collision.asm` still
reads no `$d01e`; the turret trace runs after the enemy scan; `applyDamage`
dispatches on the kind.

**4. The 6502**:
- the production counters, read **first, on a clean machine**;
- boot health 3 and alive on all eight, nothing destroyed, nothing owed;
- the pulse: index cycles 0,1,2,3 in order, holds each phase for exactly 8
  frames, and each phase paints the colour its own table entry names;
- `turretWorldTick` matches the model at six different origins and fine-scroll
  phases, for all four derived arrays at once;
- the hitbox: rays at `turretX+0` and `+15` hit, `-1` and `+16` miss;
- a survivable hit starts a 4-frame flash, the body's colour RAM holds the hit
  colour and not the pulse, and after it expires the pulse colour returns;
- an off-page turret cannot be hit; a destroyed one cannot be hit again; a ray
  whose origin is at the turret's own Y misses it;
- both cannons damage one turret in a single volley — 2 HP;
- **an exact Y tie goes to the enemy**, and one pixel farther away it goes to
  the turret;
- the lethal hit clears `turretAlive`, counts the kill, flags the repair, and
  the body is **still on the page until the repair runs**;
- after `turretRestoreTick` nothing is owed and **both pages hold the
  authoritative terrain for the body's rows, all forty columns**;
- **the whole of colour RAM** against a model image — terrain colour
  everywhere except the cells of a living on-page turret, at the colour that
  turret should be showing;
- every other turret is still alive at full health;
- a later regeneration still omits the dead turret.

**`tests/test_turrets.py`** and **`tests/test_terrain.py`** are unchanged and
still pass, which is the regression evidence for the presentation slice and the
terrain contract. Every behavioural assertion in **`tests/test_slice_d.py`**
passes unaltered, which is the regression evidence for enemy collision; only
its ladder's reporting changed, and §12.4 says exactly how and why.

### Two instruments that lied, recorded because the project keeps a list

1. **The pulse sampled by breakpoint.** Breakpointing `turretPaintTick` and
   counting stops reported a **16**-frame interval, then after keying samples
   to `frameCounter`, a **9**-frame phase. The machine was right both times:
   the remote monitor returns from `x` on a prompt echo rather than on the
   actual stop, so the number of stops per frame is one or two and not fixed.
   The pulse is now driven by calling `turretPaintTick` directly — one call is
   one frame, by construction — and reads exactly 8.
2. **"The painted cells are the ones that differ from terrain colour."** Pulse
   phase 0 is white `| 8` = **9**, which is *exactly* `TERRAIN_COLOUR_RAM`, so
   a painted cell is indistinguishable from an unpainted one at one phase in
   four. That check reported a turret missing that was being painted perfectly.
   It now compares the whole 1000-byte colour RAM against a full model image.

---

## 10. Performance

Cycle-exact, VICE monitor CPU stopwatch between PC-verified breakpoints, the
machine halted at both ends. "min" is the pure figure — a sample with no raster
IRQ inside it.

### Per-frame cost, and the four rounds of optimisation `make test` forced

The first working version cost **1,488 cycles on an idle frame and about 2,200
with two turrets on screen** — 24 to 35 raster lines of the PAL frame's 312, on
every frame. `tests/test_slice_c.py`'s sixteen-enemy ladder, which had been
clean, began overrunning the frame. §12 has the full account; this is where it
ended up.

| | min | med | max |
|---|---:|---:|---:|
| `turretWorldTick`, ordinary frame | **246** | 266 | 321 |
| `turretPaintTick`, nothing changed this frame | **39** | 39 | 315 |
| `turretPaintTick`, the coarse step that vacates **and** repaints | 864 | 976 | 1,131 |
| `turretRestoreTick`, nothing owed | **12** | 12 | 12 |

So an ordinary frame costs about **285 cycles**, four to five raster lines. The
expensive work is on the two frames §10a moves it between: the `scrollFine == 7`
preparation frame, which the scroller leaves idle, and the coarse step, which
now adopts rather than derives.

**What each round bought, on an ordinary frame:**

| | idle | two on screen |
|---|---:|---:|
| first working version | 1,488 | ~2,200 |
| + metatile-row scan instead of deriving all eight | 789 | 1,430 |
| + scan cursor kept in registers, not spilled per row | 619 | 1,390 |
| + page derivation cached on `stageTopRow`, colour repainted only on change | 270 | 369 |
| + **the coarse-step shadow** (§10a) | **~250** | **~290** |

Every round is the same idea in a different place: **the expensive answer
changes far less often than every frame.** `turretPaintRow` is a function of
`stageTopRow` alone; the pulse colour changes one frame in eight; and colour
RAM already holds what the frame wants unless a body moved, the pulse stepped
or something was hit. The scan itself reuses
`turretAtMetaRow`, the table the presentation slice already built for the page
generator, so "which turrets can the page reach" is eight indexed loads rather
than eight sixteen-bit modulo folds.

## 10a. Buying the population-8 margin back

The measurements in §12.4 said the cost was not really per-frame at all: it was
concentrated on ONE frame in eight, and that frame was the worst possible one.

**Why it landed there.** `stageTopRow` changes in `scrollTick` at the *end* of a
frame, so the first frame that can see the new value is also the frame on which
`regenTick` restarts the back page — four rows, about 4,500 cycles. The turret
derivation piled onto the heaviest frame in the cycle.

**The quiet frame.** `regenTick` rebuilds at `ROWS_PER_TICK` rows a frame and
stops at `SCREEN_ROWS`, so it finishes in `ceil(25/4) = 7` of the 8 frames
between coarse steps and **the eighth does nothing at all**. The fine scroll
counts up and wraps 7 → 0 *at* the coarse step, so that idle frame is exactly
the one on which `scrollFine` reads 7 — the frame immediately before the step.

**The shadow.** `turretDeriveShadow` now always writes `trtNextRow` /
`trtNextPair`, never the live arrays, and it runs on the `scrollFine == 7`
frame for the row the scroller is about to go to (`stageTopRow - 1`, computed
with `src/scroll.asm`'s own fold-then-subtract idiom). The coarse step itself
then copies sixteen bytes and does no arithmetic whatsoever.

**The fallback.** The shadow is only ever built for `stageTopRow - 1`. Anything
that moves the row another way — boot, a test poking the scroll state, any
future system that seeks through the stage — finds no matching shadow and
derives the page it actually asked for on the spot. It is the old cost on the
old frame, which is what a fallback should be: correct, and not free. There is
one derivation routine, used by both paths.

**The aim pass, and a spike that had to be undone.** `turretLogY` and
`turretVisible` are read by `traceTurretRay` and by nothing else, and that is
only reached on a frame that resolved a volley — so the pass was gated on
`shotFired`, removing 340 cycles from seven frames in eight.

**That was wrong, and the gate caught it.** It did not remove the cost, it
*concentrated* it on the eighth frame — and the weapon's cadence is eight
frames too, so the spike landed on the volley frame, every volley, in phase.
`tests/test_slice_b.py` steps the machine frame by frame to judge that cadence
and could no longer collect enough contiguous frames to do it: 16 where it
needs 18, twice in a row in the gate while passing standalone.

**A flat cost is worth more here than a smaller total.** The gate was removed
and the reject path made cheap instead: `turretVisible` and `turretLogY` are
cleared once per *coarse step*, where the page geometry is adopted, so a turret
that is not on the page costs the per-frame pass a load and a branch and
nothing else. The pass is unconditional again, `test_slice_b` collects 32
frames again, and nothing about the turret state is coupled to the weapon.

**Guarded, in the file that owns the constant.** `src/scroll.asm` now fails the
build if `ROWS_PER_TICK` ever drops far enough that regeneration fills all
eight frames, because the quiet frame this depends on would be gone. That guard
lives beside `ROWS_PER_TICK` rather than in `src/turrets.asm`, which is parsed
first.

| `turretWorldTick` path | min | med | max |
|---|---:|---:|---:|
| ordinary frame, page unchanged | **246** | 266 | 321 |
| the PREPARE frame (`scrollFine == 7`, regeneration idle) | 879 | 965 | 1,730 |
| the COARSE STEP, adopting a standing shadow | 591 | 633 | 677 |
| the FALLBACK, movement the preparation did not predict | 828 | 914 | 1,431 |

The expensive derivation now runs on the frame the scroller leaves idle, and
the coarse-step frame — the one that shares its budget with the page restart —
does a sixteen-byte copy instead.

**Two is the worst case, not an assumption:** the model sweeps every
worldProgress and every fine-scroll phase and finds at most two of level 1's
eight turrets simultaneously hittable or painted, because the authored pairs
are 84 to 112 rows apart.

### A player shot

| | min | med | max |
|---|---:|---:|---:|
| `collisionTick`, no volley this frame | 18 | 18 | 61 |
| `collisionTick`, a volley that misses everything | 1,151 | 1,280 | 1,874 |
| `collisionTick`, a volley that **hits a turret with both rays** | 1,281 | 1,410 | 2,196 |

So the turret half of the hitscan costs about **130 cycles** on a volley, on
top of an enemy scan that was already there.

### The destruction frame

| | min | med | max |
|---|---:|---:|---:|
| one turret owed, back page fully written (**worst**) | 4,605 | 5,056 | 5,567 |
| one turret owed, back page not started (`regenRow` 0) | 2,290 | 2,639 | 3,896 |
| **two** owed: one a frame, so the same cost | 4,583 | 4,728 | 5,410 |

Before the one-a-frame bound, two owed measured **9,354–11,057**. That is the
measurement the bound exists for.

### Main-thread health, clean production free runs

Same harness as the previous slices, 20-second warp runs, **no PC hijacking**:

| build | frames | gameSpanMax | spanOver | gameOverrun | publishSkip | scrollLate | edgeLate |
|---|---:|---:|---:|---:|---:|---:|---:|
| before both turret slices (`3afded9`) | 31,690 | 152 | 0 | 0 | 0 | 0 | 0 |
| static turret presentation | 31,517 | 156 | 0 | 0 | 0 | 0 | 0 |
| turret combat, before §10a | 34,468 | 189 | 0 | 0 | 0 | 0 | 0 |
| **turret combat, final** | 34,358 | **172** | **0** | **0** | **0** | **0** | **0** |

Worst ordinary frame goes from **156 to 172 raster lines** of the PAL frame's
312 — sixteen lines for the pulse, the page geometry and the hitscan's turret
half together, where the first working version cost 33. The aperture splits
still land on 54..55 and 248..248 and no edge is ever late.

**The tightest number here, stated plainly.** A free run never destroys a
turret, so 172 does not include the repair. The worst *possible* frame is the
worst ordinary frame plus the worst repair:

```
172 lines + 5,567 cycles (88 lines)  =  260 lines  =  16,380 of 19,656 cycles
```

That is **inside the frame** — no missed frame, `gameOverrun` cannot tick from
it — with about 3,300 cycles to spare. It is still past the 255-line saturation
of the `gameSpanMax` *diagnostic*, so a destruction frame coinciding with a
worst-case frame would show `gameSpanOver` without missing anything. That
distinction is now visible rather than hidden: §12.4 made the Slice D ladder
print the two counters separately for exactly this reason.

The lever if a later slice wants more headroom is to repair the two pages on
two different frames, tracked by page identity rather than by displayed/back
role — about fifteen instructions and two more bitmask bytes, and it halves the
spike. It is not needed now and so was not done.

**Mux-capacity qualification was not re-run**, as instructed, and no extra
turrets were manufactured: every measurement above uses the real authored
content.

---

## 11. `make test`

**ALL PASS — 726 checks, ten suites, zero failures.**

```
test_engine  test_slice_a  test_slice_a_prime  test_slice_b  test_slice_c
test_slice_d  test_terrain  test_turrets  test_turret_combat
test_batch_window --fast
```

Ten VICE instances launched and ten reaped; `pgrep -fl x64sc` clear afterwards.
123 of the 726 checks are the new turret-combat suite.

The Slice D ladder from that run, which is the acceptance measurement:

```
 enemies  collision   span  spanOver  overrun  recSkip  schedSkip
      1  OFF          168         0        0        0          0
      1  ON           205         0        0        0          0
      4  OFF          193         0        0        0          0
      4  ON           224         0        0        0          0
      8  OFF          240         0        0        0          0
      8  ON           255        14        0        0          0     <- ZERO
     12  OFF          255       255        0        0          0
     12  ON           255       255        0      102          0
     16  OFF          255       255      255      255        255
     16  ON           255       255      206      255        255
```

**Population 8, collision ON: `overrun` 0, `recSkip` 0, `schedSkip` 0.**

`test_slice_c`'s `20c` read 1 in this run, inside the `<= 4` bound retained for
the reasons in §12.2.

One earlier attempt at this gate failed and is recorded rather than discarded:
`test_slice_b`'s cadence check collected 16 contiguous frames where it needs
18, twice in a row. That was not a flake — it was the aim-pass spike described
in §10a, and removing the spike fixed it. The 26 checks that ran on those 16
frames all passed; the data was perfect, there was just not enough of it.

Per the task's budget, **P0–P5, `test-engine-full` and `test-renderer-full`
were not run.** Nothing here touches the executor, the publication model, the
slot mapping, the batch geometry or the aperture: `src/renderer.asm` is
unchanged by this slice, and the only new per-frame work is main-thread.

---

## 12. What `make test` caught, and three instruments that could not say
what they meant

This is the substantial part of the slice and it is recorded in full, because
three separate things turned out to be wrong and only one of them was the
turret code.

### 12.1 The regression that was mine

The first working version added ~1,488 cycles to every frame. `test_slice_c`
returned four failures: the population-16 ladder overran the frame, a
publication was withdrawn mid-build, a reused pool slot read Y 59 instead of
55, and the executor ran late. The pool and publication failures were
downstream of the main thread missing frames, not damage — one cause.

The fix was four rounds of optimisation, tabulated in §10, ending at 270–370
cycles a frame. Three clean `test_slice_c` runs followed.

**A bug was introduced during that work and the focused test caught it.**
Deriving `turretLogY` from `turretPaintRow` is correct only when both body rows
are on the page; for a body *entering*, `turretPaintRow` names its bottom row,
and the derived body sits a whole character too high. At fine scroll 7 that
lands on exactly raster 55 and reads as fully visible — a turret hittable
before it has finished arriving. `turretAimTick` now requires
`turretPaintPair`, and the model states that `turretLogY` and `turretVisible`
are combat quantities defined only for a body wholly on the page.

### 12.2 `20c` — a zero-margin assertion, measured as one

`test_slice_c`'s `20c` asserted `schedBuildDefer == 0`. That counter is the
renderer's **own protection working**: the frame IRQ landed between
`buildSchedule` and `publishSchedule`, so the pending publication — the very
buffer the next build is overwriting, already superseded — is withdrawn.
`src/renderer.asm` is explicit that this "costs at most one frame of latency and
cannot starve", and that the counter exists "so the cost is visible rather than
silent".

Measured directly, on that section, with this slice's per-frame calls **stubbed
out** and replaced by a delay loop that does nothing at all:

| added main-thread cost | runs reporting a deferral |
|---|---|
| +0 cycles | 0 of 2 |
| +220 cycles | 1 of 3 |
| +620 cycles | 2 of 3 |

So it is a continuous probability in the main thread's total cost, **not
attributable to turrets**, and no implementation of anything makes it reliably
zero again. The section is breakpoint-driven end to end, every stop parks the
machine mid-frame and resumes it elsewhere, and the counter is never reset
before the check — so it reports every coincidence since boot.

**The bound was changed from `== 0` to `<= 4`, with that table written into the
test.** The 11.7%-of-builds rate the renderer measured on RING-SLOW — hundreds
over a run like this — is what the check is really for and is still caught, and
the per-population ladder still asserts **zero** at every population and passes.

**RE-EVALUATED AFTER §10a, because the whole argument above rests on
main-thread cost and that cost then fell by a factor of six** — an ordinary
frame's turret work went from ~1,490 cycles to ~250. If the margin had come
back, this would have gone back to `== 0`. It did not: restored to `== 0` and
run **six times, it failed twice**. It is a genuine zero-margin,
breakpoint-sensitive assertion and not a consequence of anything this slice
added, so the small bound stays and the re-evaluation is recorded beside it.

### 12.3 `30b` — the test was measuring its own harness

`30b` asserts `statLate == 0` "over a free run". The block above it zeroes
`publishSkip`, `statPageMismatch` and `statPtrMismatch` first, with a comment
that says exactly why:

> *"Every stop in this file parks the machine mid-frame and resumes it somewhere
> else, so the main thread can legitimately miss a frame boundary that it would
> never miss running normally. Counting those as engine faults would make the
> suite's own instrument the thing it measures."*

**`statLate` was not in that list.** It was reading a counter accumulating since
boot, across every breakpoint, `call_x` and `clear_pool` in the file — precisely
the state that comment says must not be counted. It measured the harness, and
did so silently for as long as the harness stayed lucky; it began reporting 1
when this slice made the main thread longer and therefore changed where each of
that file's hundred-odd stops parks the machine. The engine was not late.

`statLate` is now in the reset list beside the other three. That is the check
being made to measure what it says it measures, not a bound being loosened.

### 12.4 The population-8 capacity, lost and bought back

The first version of this slice cost enough per frame to make
`test_slice_d`'s population-8 rung — the *well-separated* ladder, which
`docs/ENGINE_CONTRACT.md` §10 documents as the engine's practical ceiling —
stop being sustainable. That was proved by A/B on an identical tree with the
three per-frame turret calls stubbed out, and it was **not** accepted as a
reduced gameplay ceiling. §10a is what was done about it.

**And a second thing was wrong, in the instrument.** The ladder printed a single
`over` column that was `gameOverrun + gameSpanOver` **summed**. Those do not
mean the same thing:

| counter | meaning |
|---|---|
| `gameOverrun` | the main thread did not finish inside a 312-line frame. **A fault.** |
| `gameSpanOver` | the span passed 255 lines, so the 8-bit `gameSpanMax` is a floor. **A saturated diagnostic** — `src/main.asm` says exactly that where it increments it. |

The baseline at population 8 with collision on was **249** raster lines — six
under the counter's ceiling. So any addition at all pushed the span past 255
and lit `gameSpanOver`, and the summed column reported it as though frames were
being missed. They were not. The ladder now prints the two in separate columns,
and the assertions test the fault.

**The acceptance measurement, population 8, collision ON:**

| | span | spanOver | **gameOverrun** | **publishSkip** | **schedBuildDefer** |
|---|---:|---:|---:|---:|---:|
| before this slice | 249 | 0 | 0 | 0 | 0 |
| this slice, first version | 255 (floor) | — | *reported* 20-50, **summed** | 0 | 0 |
| **after §10a** | 255 (floor) | 20 | **0** | **0** | **0** |

**Zero missed frames and zero publication failures with collision on.** The
capacity is restored, not re-bounded: no population-8 assertion was relaxed.
`test_slice_d` passes in full.

What did change in that file is the *reporting* and one *predicate*, and both
are the same class as §12.3 — an instrument that could not say what it meant:

- the two counters are printed separately instead of summed;
- "sustainable" now means `gameOverrun == 0`, a fault, where it meant
  `gameOverrun + gameSpanOver == 0`;
- the population **set** the assertions run over is still chosen with both, so
  it is still exactly 1, 4 and 8. Without that, separating the counters would
  have quietly dragged 12 and 16 into assertions written for populations the
  engine comfortably sustains — 12 turns out to miss no frames at all while
  skipping ~100 publications, which is §10's known deferred issue and not this
  slice's business;
- the collision-cost delta is not asserted where the collision-on span
  saturated, because a difference measured against a floor is not a difference.
  It is reported instead.

The span at population 8 with collision on is genuinely higher than the 249 it
was: the engine finishes every frame and skips nothing, but the 8-bit
diagnostic can no longer express what the frame cost. That is stated rather than
hidden.

### Pre-existing issues

The documented `test_slice_d` population-12 flake is **not** what §12.4 is. The
suite's standing ADVISORY still prints — populations [12, 16] overrun the frame
*with collision switched off* — and §10 of the engine contract already owns it.

The known whole-sprite enemy pop at the gameplay Y bounds is **untouched**, as
instructed, and is not a regression here.

---

## 13. Turret firing and bullets were NOT migrated

Explicitly, and by instruction. None of the following exists in this repo:

- **turret firing** — no `TURRET_FIRE_INTERVAL`, no `TURRET_FIRE_TIMER`, no
  `TURRET_SHOTS_FIRED`, no `updateBackgroundTurrets` firing block;
- **turret shot emission** — no `spawnEnemyBulletAt`, no bullet spawn X/Y;
- **enemy or turret bullets** — none of any kind;
- **player damage from turrets** — the player cannot be hurt by one;
- **projectile sprite reservation** — no sprite, no pointer, no bitmap;
- **firing sound** — none;
- **aiming AI** — the body is the old static down-facing style 4 and never
  changes; the other six `turretArt` styles are not present.

`src/turrets.asm` still consumes **no** HW0/HW1, no HW2–HW7, no logical sprite
pool slot, no mux batch and no sprite bitmap storage, and the sprite renderer
still has no knowledge that turrets exist. Asserted by source scan and on the
machine.

Also not started: wave architecture, upgrades, enemy edge clipping, editor
work.

---

## 14. Score and rewards: documented, deferred

The old game awarded **`SCORE_PER_KILL` = 100** for a destroyed turret — the
same reward as an enemy — from `hitCannonTarget`'s `jmp awardKillScore`, once
per authored placement, **at the instant health reached zero** (not at the end
of a death animation; turrets have none).

**Not migrated**, and the reason is that this repo has no production score
system to hook into: `hudDemoTick` drives a demonstration counter, and
`src/collision.asm`'s `csKills`/`csKillType` event exists precisely so score can
be added later without touching collision. The value and the hook point are
recorded as `TURRET_SCORE_PER_KILL = 100` in `src/turrets.asm`, next to the
`inc trtKills` that marks the hook, so the future score slice has nothing to
rediscover.

`csKills` was deliberately **not** overloaded for turrets: it is typed by
`objType`, and a turret has no object slot and no type. `trtKills` is the
turret-side counter.

**No upgrade drops were added.**

---

## 15. Manual visual checklist

**Please run this yourself. This report does not declare visual GREEN.**

```sh
cd /Volumes/SSD/dev/C64/6502-shmup
make run JOY2=<your device>      # JOY2=1 numpad (default), 4 = a real stick
```

Fire is the stick's fire button. The first turret appears about 50 coarse rows
into the level; they come in pairs 8 rows apart, so you get two close together
and then a long gap.

| # | Look for | Expected |
|---|---|---|
| 1 | **the pulse** | the dome cycles white → red → yellow → red, about six times a second, and two turrets on screen pulse **in step** |
| 2 | the pulse while scrolling | the colour stays **glued to the body** as it moves down — no colour left behind above it, no uncoloured body |
| 3 | a turret entering at the top | its colour is right from the first row that appears, not flat terrain grey until it is fully on |
| 4 | **shooting one** | an obvious **light red** flash, clearly not one of the pulse colours |
| 5 | **how many hits** | three cannon hits. Lined up dead centre both barrels connect, so two volleys; off-centre, three |
| 6 | **destruction** | the body vanishes and the **correct terrain** is underneath it — the same plating as either side, not a hole, not a smear |
| 7 | leftover fragments | **none** — no half a turret, no stray character where the body was |
| 8 | stale colour squares | **none** — no red or yellow 2x2 block left anywhere after a kill |
| 9 | scrolling away and back | a dead turret **stays dead** across page flips, and after the level wraps |
| 10 | nearby terrain | the rows either side of the body are untouched |
| 11 | the other turret of a pair | unaffected by its neighbour's death |
| 12 | enemy hits and deaths | **exactly as before** — white flash, explosion, the same number of hits |
| 13 | shooting past a turret | an enemy in front of a turret takes the hit |
| 14 | HUD and the black border | unchanged |
| 15 | a full minute of play | no new hitch, including on the frames turrets die |

Check 6 is what this slice could most plausibly have got wrong, and check 15
is where the destruction frame's cost would show if it showed at all.

The already-known whole-sprite enemy pop at the Y bounds is **not** a
regression here.

---

## 16. VICE / input / process hygiene

- `pgrep -fl x64sc` was run before every automated session and before every
  measurement run, and every one reported clear, so nothing this task launched
  ever shared the machine with another emulator. That is a statement about the
  instants it was checked, not a claim that none ever ran — see the `vicerc`
  note below.
- Every emulator was launched by a harness with `-console` under a **retained
  PID** and reaped by that exact PID; every run printed its own
  `launched and reaped` line.
- **No `pkill`**, no termination by name matching, no manual VICE signalled.
- **No `open -a`.** No automated run opened a window or took keyboard focus.
- No joystick, keyset or controller preference was created or modified by
  anything in this task. The automated launches keep the qualified
  `-default +saveres` pairing with both control ports detached, and every one
  of them is `-console`, which opens no window at all.

- **`~/.config/vice/vicerc` changed three times during this session, and an
  earlier version of this report wrongly said it had not changed at all.** It
  began at 341 bytes dated 10 Sep and is now 364; its hash moved from the
  `a14857f3…` the terrain report recorded, to `c731f794…`, to `3510a90f…`.

  The successive deltas are **window and monitor geometry** — `Window0Xpos/
  Ypos/Width/Height`, `MonitorXPos/YPos/Width/Height`, `MonitorFont` — and, most
  recently, **`PauseOnSettings=1`**, which is the "pause the emulator while the
  settings dialog is open" option. That one is decisive: it is set from a
  windowed VICE's **settings dialog**, and a `-console` instance has no GUI, no
  settings dialog and no window geometry to write. `SaveResourcesOnExit=1` is
  set in the file, so such a session saves on exit.

  Every automated launch in this task used `-console` with `-default +saveres`,
  and `make run` — the only target that opens a window — was **not invoked**.
  `tests/test_slice_c.py` hashes the file before and after its own run and
  reported it unchanged in every gate run, so nothing changed it *while a suite
  was running*; the changes fall between suites.

  The reading this evidence supports is a **manual, windowed VICE session** —
  which is exactly what the previous slice's report asked the user to run for
  visual qualification. It is recorded as an inference from the content, not as
  a measurement, and this task does not claim to have ruled itself out.

  **The bindings the hygiene rule exists to protect are intact throughout:**
  `KeySet1North/East/South/West`, `KeySet1Fire=32` and `JoyDevice2=2` are all
  present and unchanged.

- The archive was extracted once, under `/tmp/oldshooter`, and removed
  afterwards; the test suites read the zip directly and extract nothing.
- Transient measurement scripts lived in the session scratchpad, outside the
  repository.

---

## 17. Disk

```
du -sh build/   ->   84K     main.sym, main.vs, shmup.prg, nothing else
du -sh .        ->   3.2M
```

No per-run artifacts accumulate under `build/`; the build writes fixed outputs.

---

*The old turrets now pulse, take fire, flash, and die; the terrain underneath
them comes back on both pages from the authoritative decode and stays back; the
enemy hitscan is bit-for-bit what it was; and not one sprite or mux resource is
spent on any of it. Turret firing and bullets are not started.*
