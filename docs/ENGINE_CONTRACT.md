# Engine contract

The rules game code must obey. Every number here was read out of `src/` when
this was written; if code and this document ever disagree, **the code is the
truth** and this document is the bug.

`tests/test_engine.py` restates the same numbers independently and checks them
against the running machine. Changing one means changing the contract, which is
a decision — not a test to adjust.

---

## 1. How game systems talk to the renderer

```
game logic  ->  logical sprite arrays  ->  sorter -> builder -> publication
                                                                     |
                                                        immutable CURRENT
                                                                     |
                                                           raster executor -> VIC
```

Game code writes **logical sprite state** (`logY`, `logX`, `logXHi`, `logPtr`,
`logCol`, `logCount`) and nothing else. It does not choose hardware slots, batch
lines, raster timing or `$d015`.

**No game system may mutate a published CURRENT schedule.** The architectural
test, inherited from the engine and still true: *if the main thread stopped dead
immediately after publication, the frame would still render correctly.* The
executor reads CURRENT and nothing else — not object state, not allocation
state, not a sorter.

Building and publishing is `sortTick` → `buildSchedule` → `publishSchedule`, in
that order, once per frame, from the main thread.

## 2. Hardware sprite slots

```
HW0        reserved — future player base
HW1        reserved — future player overlay
HW2-HW7    gameplay multiplex pool, time-shared with the top-border HUD
```

`MUX_FIRST_SLOT = 2`, `MUX_SLOTS = 6`. Accepted sprite *i* uses slot
`2 + (i mod 6)`, and its same-slot predecessor is accepted entry *i-6*.

## 3. Sprite admission rules

| rule | value | meaning |
|---|---|---|
| `MIN_SPRITE_Y` | **55** | below this a sprite is loose in the open border, over the HUD, and can ghost at Y+256 |
| `MAX_SPRITE_Y` | **226** | above this its DMA reaches the lines the bottom aperture split needs free |
| `SPRITE_HEIGHT` | 21 | hardware |
| `REUSE_LEAD` | 12 | rasters of lead a batch gets before its own sprite's Y — **measured, not chosen** |
| `MIN_REUSE_GAP` | 33 | `SPRITE_HEIGHT + REUSE_LEAD`; two sprites sharing a slot must be at least this far apart in Y |
| `MAX_LOGICAL` | 32 | logical pool |
| `MAX_SCHED` | 24 | schedule capacity; deliberately smaller than the pool so overflow is testable |

A sprite outside the Y range is **rejected and counted** (`statRejRange`), never
clamped. Clamping would move a sprite the caller placed deliberately.

**A VIC sprite at Y=n is displayed on rasters n+1 .. n+21**, not n .. n+20. That
off-by-one is why the HUD sits at Y=16 and not 18.

## 4. Raster phase schedule

Every phase is an interrupt; `exPhase` says which. `PH_BATCH` is 0 so the
dispatch reaches a mid-screen batch in eight cycles.

```
raster   4   exHud       program HW2-HW7 as the HUD, enable, arm 40
raster  40   exHandoff   restore gameplay sprite modes, run batch 0, enable
raster  53   exTop       poll to 55 (54 at YSCROLL=7), REAL charset + $d021
raster 68+   exBatch     mid-screen multiplex batches
raster 243   exBottom    hold the border open, poll to 248, blank charset + $d021
raster 250   exFrame     ADOPTION ONLY: frame record, schedule, page, $d015 = 0
```

**`frameEntryLine == 250` on every frame is the engine's oldest invariant.** It
is checked by every suite here. A frame transaction that runs anywhere else
rewrites `$d011`, `$d018`, the pointer destination and `$d015` in the middle of
the display.

Structural phases are **never chased** when late, with one exception: a late
`PH_TOP` runs immediately, because skipping it would leave the blank charset
selected for a whole frame — a black screen.

## 5. HUD ownership

The HUD owns **HW2-HW7 only** between rasters 4 and 40, and hands them back
completely. HW0/HW1 are never touched by either side.

`exHandoff` writes, unconditionally, every register the HUD might have dirtied:
`$d017`, `$d01b`, `$d01c`, `$d01d`, then batch 0 sets per-slot X/Y/colour/
pointer and the complete `$d010`, and `$d015` is written **last** — after the
slots are programmed, never before.

`$d017` is the one register the HUD may not use: Y expansion doubles a sprite's
DMA span, and a Y-expanded HUD at Y=16 would fetch until line 58 — through the
handoff and into the aperture.

`$d025`/`$d026` are unreachable rather than unused: `$d01c` is forced to zero on
both sides, so every sprite is hires. If gameplay ever enables multicolour, they
join the handoff contract that day.

**The Y+256 ghost.** Sprite Y is compared against the low byte of the raster, so
the HUD's Y=16 matches again at raster 272. `exFrame` clears `$d015` at raster
250 and nothing sets it until `exHud` at raster 4, so the ghost compare passes
with nothing enabled. **Never enable a sprite between rasters 250 and 4.**

## 6. HUD bitmap preparation

`exHud` points the VIC at bitmaps that are already finished. It formats nothing,
converts nothing and draws nothing, and costs 434 cycles whatever the HUD says.

Bitmap RAM is written by the **main thread**, and only inside a window where the
VIC cannot be reading it:

```
the VIC fetches HUD sprite data on rasters 16..37, and nowhere else
hudUpdate refuses to start outside rasters HUD_SAFE_LO=56 .. HUD_SAFE_HI=200
hudUpdWrapped counts any update that left the frame -- it must read zero
```

`hudUpdate` is called from the main loop's **idle spin**, not the once-per-frame
block: that block reaches the same point at about raster 10, inside the fetch
window, and would defer every frame.

Components mark themselves dirty (`HUD_DIRTY_LIVES/HEAT/SCORE/UPGRADE`). With
nothing dirty the whole update is `lda hudDirty / bne / rts` — eleven cycles.

Lives (0..5) and upgrade (0..3) have a precomputed bitmap per value, so changing
them writes **one byte** of `hudPtrLive`, which is atomic against the interrupt
that reads it.

## 7. Page and pointer ownership

Two screen matrices, `SCREEN_A = $0400` and `SCREEN_B = $2800`, with sprite
pointer tables at `$07f8` and `$2bf8`. They share the low byte `$f8`, so **one
patched byte** selects the destination.

`exFrame` patches both pointer-writing instructions — the batch executor's and
the HUD's — from the same frame record, at the same instant it decides `$d018`.
Two stores, one source, one decision.

**Only the currently adopted page's pointer table is ever written.** Never write
both "to be safe": that is how a page flip produces a one-frame mismatch.

## 8. Scroller and aperture

The vertical border is held **open** all frame (the flip-flop is made to miss
both close comparisons), so the HUD can live in the top border. An open border
clips nothing, so the playfield is clipped by a **blank character set** instead:

```
BLANK_CHARSET = $3800     2 KB of zeros; also supplies the VIC idle byte at $3fff
real charset  = $0800     the level's terrain tileset (src/terrain.asm)

$d018 values:  A real $12   A blank $1e
               B real $a2   B blank $ae

raster  55   exTop     blank -> real,  $d021 = APERTURE_D021
raster 248   exBottom  real  -> blank, $d021 = BORDER_D021
visible terrain = rasters 55..247, 193 lines
```

Matrix rows 0 and 24 carry ordinary terrain. There are **no blank guard rows**,
and reintroducing them would bring back the 6.25 Hz edge pop they caused.

**`$d021` is aperture state, not boot state.** An open vertical border paints
no `$d020` anywhere: rasters 0..47 and 248..311 are VIC *idle* lines rendered
from `$3fff`, and rasters 48..54 are real matrix lines rendered through the
blank charset. All three come out as bit pair 00 — which in multicolour text
mode is `$d021` and nothing else. The playfield's background and the open
border's background are therefore **the same bit pair of the same register**,
and the only thing that separates them is where the beam is. So the two
aperture splits write `$d021` alongside `$d018`, from the same frame record:
`BORDER_D021 = 0` below raster 55 and from 248, `APERTURE_D021` in between.
`APERTURE_D021` is *derived* from the level package's
`TERRAIN_BACKGROUND_COLOUR`, so a level cannot author a background the raster
disagrees with.

At YSCROLL 0..6 both stores land on line 55, `$d018` first because its deadline
(the g-access in cycle 15) is earlier than `$d021`'s (the first visible
playfield pixel, cycle 17). **At YSCROLL = 7 they separate**: `$d018` splits on
line 54 to dodge that phase's badline, and it may, because 48..54 are idle at
that phase and the VIC renders them from `$3fff` whatever the charset says.
`$d021` *cannot* follow it there — idle lines are drawn in `$d021`, so a
background store on 54 would paint one line grey at one phase in eight. The
background gets its own short poll to 55 on that path alone.

**The boundary is a raster and never a row.** A `$d021` boundary that moved
with YSCROLL would climb seven pixels and jump back, which is precisely the
6.25 Hz edge pop the guard rows were removed to kill.

The scroller publishes a **frame record** (fine scroll, `$d018`, pointer
destination, page) with the same atomic-publication discipline as the schedule;
the frame IRQ adopts it at raster 250 and the executor never asks the scroller
anything.

## 8a. The world contract

The rule game systems reason about the stage with. Everything here is
**read-only** to game code; only `src/scroll.asm` writes any of it.

**The playfield scrolls DOWNWARD.** The player flies *up* through the stage, the
terrain moves *down* past them, and new terrain enters at the **top**. This is
the original game's forward-play direction and every piece of authored content
is written against it.

```
matrix row r  shows stage row  stageTopRow + r        r = 0..24
fine scroll   counts UP 0..7   content moves down one pixel per step
coarse step   on the 7 -> 0 wrap: stageTopRow steps BACK one, the page flips
```

| value | width | meaning |
|---|---|---|
| `scrollFine` | 1 | current YSCROLL, 0..7, counting up |
| `stageTopRowLo/Hi` | 2 | the stage map row at **matrix row 0**. Decreases. |
| `worldProgressLo/Hi` | 2 | coarse rows travelled since the stage start. **Only ever increases.** This is the one to ask "how far through the level are we". |
| `stageLoopsLo/Hi` | 2 | times the map has wrapped end to end |
| `STAGE_ROWS` | — | the stage's height in character rows (420 for the demonstration stage; level-owned once a level package exists) |
| `STAGE_START_ROW` | — | `STAGE_ROWS - 25`: the first page shows the authored **bottom** of the map |

The two counters are two names for one event and the relationship between them
is exact on every frame:

```
stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS
```

**Use `worldProgress` for progression questions** — has a trigger row been
reached, how far through the stage are we, is the stage finished. Use
`stageTopRow` only to index the map. No game system should encode "forward means
subtract": that is the scroller's business and the reason the two names exist.

**Screen Y of a stage row** is `stageTopRow`-relative and needs `scrollFine`:
row `stageTopRow + n` occupies matrix row `n`, whose top pixel is at raster
`48 + scrollFine + 8n`. The exact constant a game system should use is **to be
measured, not derived** — the visible aperture starts at raster 55 and matrix
rows 0 and 24 are partly clipped.

**End of stage.** The demonstration stage **wraps**: at row 0 the window steps
back to `STAGE_ROWS-1` and the map plays again from its bottom, with a content
seam while the window straddles the join. A finite stage will end by comparing
`worldProgress` against the stage length, which is a game-state decision and is
deliberately not made here. `worldProgress` never wraps; nothing should ever
infer progression from an unsigned underflow of `stageTopRow`.

## 8b. The logical object pool and membership

Added in Slice C. `src/objects.asm` owns it; `src/sorter.asm` reads it.

**Gameplay owns "active". The renderer owns "renderable this frame."** An object
the builder rejects — for Y range, for schedule capacity, or for reuse spacing —
is still perfectly alive. It simply is not drawn this frame. Nothing in gameplay
may know that hardware sprites exist.

```
objectAlloc     -> a zeroed free slot, INACTIVE       carry set = pool full
objectActivate  -> the slot joins the active set      sets sortDirty
objectFree      -> the slot returns to the pool       sets sortDirty
objectUpdateAll -> one frame of every active object
```

| value | meaning |
|---|---|
| `logActive[id]` | **which** logical IDs exist. The sorter's only source of truth. |
| `logCount` | **how many**. Maintained independently, and cross-checked against `logActive` by `sortTick`; a disagreement raises `sortFault`. |
| `sortDirty` | membership changed. Set by activate, free and `sortReset` — **never** by an object merely moving. |

**Allocate and activate are two calls, deliberately.** The caller fills every
field between them, so a half-built object can never be named by `sortedIDs`.
`objectAlloc` zeroes the whole slot, so a reused slot inherits nothing.

**The sorter's membership rule.** `sortedIDs[0 .. sortedCount-1]` holds exactly
the IDs whose `logActive` is 1 — no more and no less. `sortRebuild` compacts the
active IDs to the front and sets the count from them, so an inactive ID cannot be
inside the window and an active one cannot be outside it. `sortedIDs` stays a
permutation of `0..MAX_LOGICAL-1` at all times.

Before Slice C, membership was the implicit prefix `ID < logCount` and `sortTick`
resized that window from `logCount` every frame without rebuilding its contents.
A shrink therefore left despawned IDs inside the window and pushed live ones out
of it — a ghost and a vanishing sprite from one despawn, with no fault raised.
**Never infer membership from a count.**

**Populations are mutually exclusive.** A production boot loads no fixture; a
fixture run spawns no object. `sortReset` is the one place the prefix model still
holds, and it exists to give fixtures their membership.

**Despawn touches no VIC register, and needs to.** The sprite is not turned off:
the next schedule simply does not contain it, and `$d015` is composed from the
schedule rather than edited. Freeing gameplay state cannot disturb an already
adopted CURRENT schedule, which stays immutable for its frame.

## 8c. World-placed background characters

Added by the turret-presentation slice. `src/turrets.asm` owns it.

**A generated page is base terrain plus a world overlay, and the authored
terrain is never modified.**

```
renderRow
  renderTerrainRow    40 character codes for one stage row, from the map
  turretOverlayRow    0 or 2 of them replaced, from the authored placement
```

Both run during **hidden-page generation**, so a page is coherent before it is
published. Nothing patches the visible screen from gameplay code, and there is
no second scroll coordinate system: the overlay is a pure function of the stage
row the terrain decoder was already given.

| rule | value |
|---|---|
| placement | `src/level1/stage_turrets.asm`, the level editor's own output |
| body | 2x2 background characters, codes 226..229 (TL, TR, BL, BR) |
| world row `R` | the top pair; `R+1` the bottom pair |
| world col `C` | the left cell; `C+1` the right cell |
| colour RAM | **untouched** — the level's single terrain colour, as everywhere |
| resources | no sprite, no logical object, no mux batch, no VIC register |

**The restoration contract.** Each authored turret has one `turretAlive` byte,
and it is the whole of "put the terrain back":

```
alive -> terrain + turret
dead  -> terrain only
```

Because the overlay is applied *on top of* a freshly decoded row, clearing the
byte makes the next regeneration of either page produce the underlying terrain
with nothing to repair — no cached ground codes, no second copy of the map, no
state that can go stale.

## 8d. Turret combat

Added by the turret combat slice. `src/turrets.asm` owns all of it; the only
thing `src/collision.asm` knows is that a ray's winner is an index **and a
kind**.

| rule | value | source |
|---|---|---|
| health | **3** | `TURRET_START_HEALTH` |
| damage | 1 HP per cannon hit | both rays trace independently |
| hitbox | `turretX .. turretX+15` — **the body, 16 pixels** | not the enemy scan's 24 |
| eligibility | alive, and the whole 16-pixel body inside rasters 55..247 | |
| arbitration | one winner per ray, greatest Y wins, **an enemy wins an exact tie** | turrets are traced after every enemy and must beat the incumbent strictly |
| pulse | white, red, yellow, red — one global phase, 8 frames a step | colour RAM only |
| hit flash | `10\|8` for 4 frames, overriding the pulse | colour RAM only |
| score | 100 on destruction, **documented and not wired** | no production score system exists yet |

**The world → screen mapping is the contract's own and there is no second
scroll counter.** A turret's authored top body row `R` is at matrix row
`(R - stageTopRow) mod STAGE_ROWS`, and

```
turretLogY = 47 + scrollFine + 8 * matrixRow
```

is the sprite Y a sprite would need to cover the body's top pixel row — which
is what lets the hitscan compare a background character against a sprite on one
scale without either side knowing what the other is made of. Derived each frame
from the **presented** origin, before the hitscan, because `scrollTick` runs at
the end of `gameFrame`.

**Drawing and combat are different questions with different answers.** A body
straddling an aperture edge is still drawn, so its colour must still be
painted; it is not hittable, because half of it is outside the aperture. The
old game gated colour on the combat predicate and turrets entering or leaving
rendered in flat terrain colour; `turretPaintRow` and `turretVisible` are
deliberately separate here.

**When each kind of write happens, and why.**

| write | when | why then |
|---|---|---|
| colour RAM | after `collisionTick` | the VIC latches a row's colour once per badline and holds it for the whole character, so a mid-frame write is one-frame granularity, never a tear — and a hit flashes on the frame it landed |
| screen RAM | the **first** thing `gameFrame` does | the main loop is paced by the frame counter, incremented in `exFrame` at raster 250, so this runs in the lower border with the whole next picture's matrix fetch ahead of it |

A kill therefore **flags** itself and the characters are repaired at the top of
the next frame — at most one frame later, at a point whose safety does not
depend on how busy the frame was.

**Both pages are repaired, and neither blindly.** The hidden page is rebuilt a
few rows at a time, so a turret killed now may already have been composed into
rows that are behind the regeneration cursor and will not be rewritten before
the flip; repairing only the displayed page would make the body reappear for a
whole coarse cycle. Each page is repaired against **its own** top row —
`stageTopRow` for the displayed one, `regenTopRow` for the one being rebuilt —
and back-page rows at or above `regenRow` are skipped because regeneration is
about to write them with `turretAlive` already clear.

**What is written is the authoritative decode.** The repair calls
`renderTerrainRow`, the same routine that builds every page row, with no
overlay on top. There is no cached-terrain table and there does not need to be:
the terrain is a pure function of the stage row, so it can always be recomputed
and can never be stale.

**One turret is repaired per frame**, and that is a measurement: one turret on
both pages costs 4,605–5,567 cycles, two measured 9,354–11,057, and the second
figure does not fit a PAL frame on top of a worst-case main thread. Two turrets
can only die together when one volley's two rays each land a last HP on a
different body. The second waits a frame.

## 9. Direct VIC access — who owns what

| register | owner | who may write it |
|---|---|---|
| `$d000-$d010`, `$d015`, `$d017`, `$d01b`, `$d01c`, `$d01d`, `$d027-$d02e` | the renderer | `src/renderer.asm` only |
| sprite pointer tables | the renderer | `exPtrStore` and `huPtrStore`, both in the renderer |
| `$d011`, `$d018`, `$d021` | the renderer's frame transaction and the two aperture splits | `src/renderer.asm` only |
| `$d016`, `$d022`, `$d023`, colour RAM | the playfield | `src/terrain.asm`, once at init |
| `$d020` | boot | `src/main.asm`, once |

`$d021` moved out of boot when the open border had to be black: see §8. The
playfield still **authors** the value — `APERTURE_D021` derives from
`src/level1/stage_config.asm` — and the renderer **writes the register**. That
is the same division `src/hud.asm` lives by, and the reason it exists is that
one write at init cannot be correct for two regions of the screen that share a
register.

**Game logic must not bypass these owners.** `src/hud.asm` is the model for how
a new subsystem participates: it owns HUD *data* and writes not one VIC
register; the code that touches the VIC lives in the renderer beside the handoff.

The previous project accumulated thirteen independent writers of `$d015` and
became unreasonable. Do not repeat that.

## 9a. Logical collision — the player's weapon

Added in Slice D. `src/collision.asm` owns it.

**The decision never touches hardware sprite identity, and `$d01e` is not read.**
The mux time-shares HW2..HW7: the same physical sprite draws different logical
objects on different rasters of one frame, and an object's slot changes between
frames. A VIC collision bit names a *slot*, and a slot is not an object, so
"which enemy did the player hit" has no correct answer there.

```
weaponTick       emits the shot event: two ray origins (9-bit X) and a Y
objectUpdateAll  every object takes its movement
collisionTick    the rays meet the objects; damage is applied to logical HP
enemyTick        next frame, turns damage into feedback, death and the free
```

**Temporal model.** Collision runs *after* all movement, so rays and targets are
both end-of-frame state for the same frame. One visible consequence: an enemy
that left the world this frame was already freed, so a shot fired that frame
misses it. That is a definite answer, not a race.

| rule | value |
|---|---|
| hitbox | `enemyX .. enemyX+23`, the full sprite width |
| eligibility | `logY >= 55` and `logY < shotY` (strictly above the ship) |
| nearest | greatest `logY` wins |
| tie | equal `logY` goes to the **higher pool slot** |
| damage | 1 HP per cannon hit; both cannons trace independently |
| filter | `objType == TYPE_ENEMY` and `objHP > 0`, never "any active object" |

**A ray's winner is an index AND a kind.** `src/turrets.asm`'s authored
background turrets are hittable and are *not* objects — no pool slot, no
logical sprite, no type field — so `traceRay` ends by calling `traceTurretRay`
to extend the same nearest-Y result, and `applyDamage` dispatches on
`csTargetKind`. Running the turrets **after** every enemy is not an
implementation detail: it is the tie-break, and it is the old game's. With no
turret in a ray's path the answer is bit-for-bit what §9a alone would give.
See §8d.

**Death is a state, not an immediate free.** Zero HP starts a bounded
`DEATH_TIME` countdown during which the object stays active and renderable;
the frame the timer reaches zero calls the same `objectFree` every despawn uses.
There is exactly one place an enemy slot is released, so publication safety has
one path to reason about.

## 10. Known deferred performance issue

**`RING-SLOW` and `RING-SHIFT` show visibly jerky motion and background glitching
under their 16-sprite moving workload.** Measured as frame-record publication
skips of roughly 12 % on those two modes; `RING-FAST`, `MAXCAP` and every
lighter fixture measure zero.

This is a **known deferred performance issue, not an engine correctness
failure**. A skipped frame record drops one frame of scroll — fine scroll, page,
pointer destination — and is adopted at the next raster 250. The *sprite*
schedule has no skip path and is never dropped, stale or corrupted by it.

It correlates with frame-record publication under high-batch moving workloads
and it is **not** caused by the HUD: measured with the HUD phase bypassed
entirely, and with the HUD demo stubbed out, the rate is unchanged.

**Do not optimise it opportunistically.** It is to be revisited with realistic
production scenes at roughly **6 / 8 / 10 / 12 / 14 / 16** gameplay sprites, so
the budget is measured against a real load rather than a torture fixture.

`FIX16 / MAXCAP` is an intentionally abusive stress ceiling — 30 logical sprites,
24 accepted, 19 batches — and is **not a production optimisation target**. Its
historical visual glitch has varied as the raster phases changed and may
currently be clean. Use it to detect *new* catastrophic corruption, nothing else.

### Measured again in Slice D: well-separated sprites are the heavier load

Slice C's ladder spawned enemies one per frame into a descending column two
rasters apart, which the reuse rule collapses into a **single batch**. Slice D
measured the same populations **spread ten rasters apart**, which produces up to
eleven batches, and the main thread saturates:

| enemies (spread) | main-thread span | frames missed |
|---:|---:|---:|
| 1 | 133 | 0 |
| 4 | 171 | 0 |
| 8 | 235 | 0 |
| 12 | 255 (saturated) | yes |
| 16 | 255 (saturated) | yes, with publication skips |

**This is not collision.** Switching `collisionTick` to an immediate `RTS` and
re-running gives the same overruns at 12 and 16, so the cost is the schedule
build and the batch count. Collision's own contribution is 4 to 15 raster lines
at the populations the engine sustains.

The practical ceiling for *well-separated* gameplay sprites is therefore around
**eight**, not sixteen. Packing matters more than count. Nothing here has been
optimised; it is recorded so a wave designer knows the shape of the budget.