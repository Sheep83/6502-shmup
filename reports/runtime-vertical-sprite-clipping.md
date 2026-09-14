# Runtime vertical sprite clipping, into schedule-owned scratch

Enemies now cross the top and bottom aperture edges a row at a time instead of
appearing and vanishing whole. The clipped bitmap is generated at runtime into
a scratch block that belongs to the schedule generation that named it.

**MANUAL VISUAL QUALIFICATION PENDING** — see the last section.

## Scratch-pool sizing: the proof, and the budget taken against it

The six questions, answered from `renderer.asm:621-652` rather than assumed.

**1–2. Yes, and yes.** A hardware slot is reused vertically within a frame
(`2 + (i mod 6)`), and two clipped entries sharing a slot at different raster
positions need different bitmap contents while both are referenced by the same
CURRENT schedule. Sharing a block between them is impossible without a
mid-frame rewrite, which is forbidden.

**3. No — the edges are geometrically disjoint but not mutually exclusive.** An
enemy is top-straddling (true `logY` 35..54) or bottom-straddling (227..246),
never both; but a schedule can hold both kinds at once.

**4–5. The `i mod 6` mapping caps each EDGE at six, and a legal schedule can
reach twelve.** Every top-clipped entry presents at `MIN_SPRITE_Y` and every
bottom-clipped one at `MAX_SPRITE_Y`, so within an edge they all carry the same
schedule Y. The first `MUX_SLOTS` accepted entries fit with no slot to reuse;
the seventh compares against the entry six places back, finds a gap of zero,
and is refused as unsafe. Both edges can be busy simultaneously — the schedule
`[6× Y=55][6× Y=226]` is legal, because entry 6 reuses entry 0's slot with a
gap of 171 — so **the structural worst case is twelve**, not six.

**6.** Sharing would be sound only for identical source pointer *and* identical
clip amount. Not implemented: in the worst case every clipper has a different
clip amount, so it removes nothing from the ceiling.

**The budget taken.** Twelve blocks double-buffered is 1536 B against the 832 B
VIC bank 0 can give without relocating a major structure. `CLIP_POOL_SLOTS` is
therefore **six, shared across both edges**, double-buffered as **12 blocks =
768 B**, with an explicit overflow path rather than a silent one. This was
raised and approved before implementation.

## Memory

**768 B reserved, in twelve 64-byte blocks:**

| pool | blocks |
|---|---|
| 0 | `$0340 $0380 $03c0 $3100 $3140 $3180` |
| 1 | `$31c0 $3680 $3700 $3740 $3780 $37c0` |

- **`$0340-$03ff` (3 blocks)** is the new reservation — the tail of the
  cassette buffer and the unused bytes above it. The engine banks the KERNAL
  out and takes the hardware vector at `$fffe` directly (`renderer.asm:2040`),
  and nothing in `src/` references `$0300-$03ff`. Deliberately **not emitted**
  into the PRG: the file starts at `$0801` and reaching down would drag screen
  page A and the stack into it. Every block is fully written before it is ever
  pointed at, so there is nothing to initialise.
- **The other nine** came from gaps the map already had — four in the raster
  executor's headroom, one above the enemy bitmap, four above the projectile.
  These **are** emitted, so the assembler maps them and a future segment
  growing into one is a build error, not a corrupted sprite.

No structure was relocated. Remaining VIC bank 0 headroom: **`$30c0-$30ff`
plus `$3094-$30bf` = 108 B**, all of it the raster executor's growth room
(the executor ends at `$3093`). Code is `$8000-$8116` (outside bank 0); state
is `$c3d8-$c3f7`, the gap between the sorter and motion blocks.

## Ownership and the swap

There is no new swap. The pool is indexed by **`schedNext`** — the same byte the
schedule buffers use — and the block's pointer is stored in `schedPtr`, so the
bitmap is part of the immutable plan exactly like the entry's Y or slot. When
`exFrame` promotes that schedule, the block travels with it and the main thread
moves to the other pool. Mainline writes pool[`schedNext`]; the IRQ presents
pool[`schedCurrent`]. There is never a moment when both look at one block, so
no handover, no raster-progress test, no "safe to overwrite now" window.

## Logical vs presentation

`logY` is never written by any of this. One annotation is added per logical
sprite — `logClip`, signed: positive = rows above the top edge, negative = rows
below the bottom, zero = present as authored. `enemyTick` writes it every frame;
`objectZeroSlot` clears it so a reused slot inherits nothing; it is zero for
projectiles and for every qualification fixture, which therefore see no change.

Movement, collision, paths, lifecycle and diagnostics all continue to read the
true `logY`.

## Row mapping — exact at 1 row

With `t` the true `logY` and `c` the clip count:

- **Top** (`t = MIN_SPRITE_Y - c`): held at `MIN_SPRITE_Y`; block row `r` is
  filled from source row `r + c`, whose true raster is `t + r + c =
  MIN_SPRITE_Y + r`. Block rows `21-c .. 20` blanked.
- **Bottom** (`t = MAX_SPRITE_Y + c`): held at `MAX_SPRITE_Y`; block row `r` is
  filled from source row `r - c`, whose true raster is `t + r - c =
  MAX_SPRITE_Y + r`. Block rows `0 .. c-1` blanked.

Both are exact at every straddle position — verified independently across all
40 positions, and end-to-end against the machine's own bytes in the focused
proof. There is no rounding anywhere; the 2-row granularity of the abandoned
static plan existed only to bound storage.

## Source provenance

`clipMakeScratch` reads the **canonical render pointer** (`logPtr`) and derives
the source address as `ptr * 64`. It does not know about `enemyMC`. A future
animation frame or a second species changes `logPtr` and clipping follows it
unchanged — which is the point: **pool size is independent of species ×
animation frames × layers.** Adding art costs art memory only.

## Scheduler integration

Three touch points in the builder, no structural change:

1. **The clamp, immediately after `lda logY,y`** — before the production Y
   bounds, the reuse gap and the batch line, so every test reasons about the Y
   the VIC will actually be programmed with. The sort is still by true `logY`
   and stays correct: clamping is monotonic, so ascending true order is
   ascending presented order, with boundary ties the reuse rule already refuses.
2. **A capacity check at the top of `bs_accept`**, before any of the entry's
   state is committed.
3. **The pointer store**, which calls `clipMakeScratch` for a clipped entry.

Fully invisible enemies (`|c| >= SPRITE_HEIGHT`) are left with `logClip = 0`, so
their out-of-band `logY` meets the builder's existing admission test and they
are culled — no block, no slot, no entry, while remaining alive. Culling is the
rule that was already there.

## Overflow

If a clipped entry finds no free block, it is **not scheduled that frame** and
`clipPoolFull` increments (saturating). `bs_acc` is untouched, no slot is
consumed, and the enemy's logical life continues unchanged. A sprite that is by
definition half outside the aperture is the least visible thing that could be
dropped. Observed peak in production: **1 block of 6**.

## Cycles

~16 cycles per visible byte and ~12 per blanked byte over 63 bytes, plus ~60
setup: **≈950–1050 cycles per clipped sprite per frame**, worst case ~1.6 raster
lines. Typical load is one or two clippers. Not optimised further — `gameOverrun`
is zero in every run below.

## Results

**Focused proof — `make test-clip-scratch` (new, NON-default): ALL PASS, 69 s.**
287 frames; clip amounts seen `-20 -18 -17 -15 -14 -12 -11 -9 -8 -6 -5 -3 -2 13
15 16 17 18 20`.

- 6 top-edge and 39 bottom-edge clipped entries verified
- **every scratch bitmap matched the canonical art — read out of the machine —
  shifted by exactly the right rows, off-aperture rows blank**
- every clipped entry scheduled at the boundary, never at the enemy's true Y
- every scratch pointer in CURRENT named a block of **CURRENT's** pool
- true `logY` kept advancing while presented Y was clamped
- clipping walked one row at a time, never jumping or reversing
- no entry for a fully-outside enemy; pool peak 1 of 6; `clipPoolFull` 0
- `gameOverrun` `publishSkip` `schedBuildDefer` `scrollLate` `edgeLate`
  `statOverflow` `statPageMismatch` `statPtrMismatch` all **0**

**`make test` (one run, 4:13): ALL PASS** — boot, production, turret regression,
encounter director. All health counters zero; no page/pointer fault; schedule
never overflowed.

## Unchanged

No HUD, raster, split, multiplexer, sorter-order, batching or slot-reuse change.
`$d01b` and `$d015` untouched. Six gameplay mux slots, player on HW0/HW1, open
vertical border, border HUD, immutable CURRENT, complete NEXT and the atomic
swap all as they were. Horizontal clipping untouched. Collision untouched.
Encounter spacing and movement patterns untouched. No health bars added.

## Hygiene

```text
$ du -sh build/   88K     build/
$ du -sh .        4.5M    .
```
No VICE process remains (all reaped, `rc=-15`); harness unmodified (`+saveres`,
no `-default`, no joystick overrides); no `/tmp` artifacts.

```text
$ git status --short
 M Makefile
 M src/enemy.asm
 M src/main.asm
 M src/movement.asm
 M src/objects.asm
 M src/renderer.asm
 M src/waves.asm
 M tests/test_encounter_director.py
?? reports/encounter-director-v1.1-flight-paths.md
?? reports/enemy-ingress-egress-spacing.md
?? reports/fable-vertical-sprite-clipping-review.md
?? reports/vertical-sprite-edge-clipping-investigation.md
?? src/clip.asm
?? tests/test_clip_scratch.py
?? tests/test_flight_paths.py
?? tests/test_ingress_egress.py

$ git diff --stat
 Makefile                         |  31 +-
 src/enemy.asm                    | 189 ++++++++++--
 src/main.asm                     |   6 +
 src/movement.asm                 | 399 +++++++++++++++++--------
 src/objects.asm                  |   8 +
 src/renderer.asm                 |  82 ++++++
 src/waves.asm                    | 617 +++++++++++++++++++++++++++++++--------
 tests/test_encounter_director.py |  76 ++++-
 8 files changed, 1141 insertions(+), 267 deletions(-)
```

**This task's changes** are `src/clip.asm` (new), `src/renderer.asm`,
`src/objects.asm`, `src/main.asm`, the `enemyTick` clip block in
`src/enemy.asm`, `tests/test_clip_scratch.py` (new) and one Makefile target.
`src/movement.asm`, `src/waves.asm`, `tests/test_encounter_director.py` and the
other reports/tests are the earlier ingress/egress and flight-path slices, still
uncommitted. No commit, no push, no `.vscode/settings.json` change.

## MANUAL VISUAL QUALIFICATION PENDING

`make run`, then judge:

- enemies emerge smoothly through the top edge, a row at a time;
- bottom-diving enemies disappear smoothly through the bottom edge;
- 1-row clipping reads as continuous, with no stepping;
- no bitmap tearing or corruption, and no frame where a clipped bitmap visibly
  belongs to a different enemy;
- no visible pause while the presented Y is clamped at a boundary;
- transition to and from the canonical sprite is clean;
- side clipping unchanged and still smooth;
- HUD completely unchanged, no corruption;
- no sprite flicker, skips or hitches;
- bottom-diving attack paths intact and encounter spacing as approved.
