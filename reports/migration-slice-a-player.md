# Migration Slice A — production loop + player on HW0/HW1

12 September 2026 · PAL C64 · KickAssembler 5.25 · VICE 3.10 `x64sc`

`6502-shmup` boots into a game. The qualification fixtures are off the startup
path, a two-layer player ship occupies the two reserved hardware sprites, and it
gets there through a published block that the frame transaction adopts with
everything else. No game code writes a VIC register.

**Automated: green.** `make test` — both probes — passes. **Manual: not yet
assessed.** Section 21 is the test a human has to run.

---

## 1. Old player source used as behaviour reference

Read in full from `c64Shooter/src/main.asm` before any of this was written.

| Old source | Line | What was taken |
|---|---|---|
| `updatePlayer` | 2348-2416 | the movement itself: joystick port 2, **one pixel per frame per axis**, no acceleration and no momentum. There is no velocity state anywhere in that routine, so none was invented here. |
| `updatePlayer` X limits | 2380-2416 | refuse left at X=23, refuse right at X=321. Kept as values. |
| `PLAYER_START_X` / `_Y` | ~966 | 160 / 220. Kept. |
| `playerSprite` | 5413-5435 | the ship **art**, 21 rows of 3 multicolour bytes, converted at assembly time — see §8. |
| `PLAYER_COLOUR_NORMAL` | ~975 | 14, light blue. Kept as the hull colour. |
| `setupSprites` `$D026 = $0f` | 2276 | light grey, the colour the ship's highlight pixels indexed. Kept as the overlay colour. |
| `PLAYER_LAYER_COUNT = 2`, `playerLayer0/1` | 9828-9842 | the **idea** of two co-located hires layers, from the `experimental-three-layer-player` work, and its stated property that no pixel is set in more than one layer. None of its code. |
| `GAMEPLAY_SPRITE_MIN_Y` | ~640 | 55. Same value the new engine independently arrived at as `MIN_SPRITE_Y`. |
| `STICK_2 = $dc00`, bit assignments | `variables.asm` 19 | joystick port 2, active low, bits 0-4 = up/down/left/right/fire. |

Archaeology note worth recording: the task brief allowed for acceleration or
momentum "where implemented". It is not implemented. `updatePlayer` is a
sequence of `dec`/`inc` guarded by joystick bits, and the only per-frame player
state in the old build is fire cadence and muzzle/explosion/blink timers. The
feel to preserve is therefore direct 1 px/frame movement, and that is what this
slice implements.

## 2. Old implementation deliberately rejected

- **`PLAYER_MAX_Y = 237`** (~972). It relied on the old open lower border
  displaying sprites below the aperture. Replaced by 226 — see §9.
- **The multicolour player.** `playerSprite` uses `$D025`/`$D026`, which
  `exHud` and `exHandoff` make unreachable by forcing `$d01c = 0`. Converted to
  hires rather than carried across; see §8.
- **`OBJECT_X`/`OBJECT_Y[0]`** — the player living in the generic object pool.
  It now has its own record and is not in the pool at all.
- **`OBJECT_SPRITE`/`OBJECT_COLOUR` as a state machine.** The old muzzle flash,
  respawn blink and explosion wrote a bitmap pointer and a colour straight into
  the shared object arrays. Presentation is now a block (§4).
- **`PLAYER_HW_MASK`** (5324) and the code in `renderSprites`,
  `hudBorderHandoff` and `extendRasterPlanMasks` that rebuilt it every frame.
  The old player had no fixed slot and the mask chased it; the answer is now
  permanently HW0 and HW1.
- **`playerLayerEmit` / `playerLayerSnapshot` / `playerLayerAssign` /
  `playerLayerModeInitial` / `playerLayerAudit`** and the `SORTED_LAYER_MASK`
  nibble packed into the sorted list. The whole reason that machinery existed
  was to push the player through a mux it no longer goes through.
- **`setupSprites`** (2268) — a main-thread routine writing `$d015`, `$d01c`,
  `$d025`, `$d026`, `$d017`, `$d01d`, `$d01b` directly.

## 3. New logical player state

`src/player.asm`, segment `$c520 "player state"` (outside VIC bank 0, with
everything else the main thread owns). Deliberately small: there is no velocity
because the behaviour being preserved has none, and no lives/explosion/blink
state because the systems that use those arrive with the slices that add them.

```
plyX, plyXHi     9-bit screen X
plyY             screen Y
plyVisible       0 hides the ship without moving it -- respawn blink and the
                 post-death hold will both need it
plyDirty         1 = the presentation changed; this frame must rebuild
joyState         live joystick sample, ACTIVE LOW
joyHold          non-zero: readInput leaves joyState alone (see §21 and below)
```

`joyHold` is test scaffolding of the same kind, and for the same reason, as
`fixtureIndex` being pokeable and `pinFine` holding the scroll phase: `AGENTS.md`
forbids sending simulated keyboard input to the emulated machine, and an
automated run detaches both joystick devices, so there is otherwise no way for a
test to move the ship. It costs eleven cycles a frame in production.

## 4. The published player presentation block

Ten bytes, one contiguous array, in `src/player.asm`:

```
plyPresX0  plyPresY0  plyPresPtr0  plyPresCol0      HW0, the hull
plyPresX1  plyPresY1  plyPresPtr1  plyPresCol1      HW1, the trim overlay
plyPresEnable    $d015 bits 0/1 ONLY
plyPresD010      $d010 bits 0/1 ONLY
```

It describes what the two slots must look like and says nothing about why. The
renderer copies the whole block and never reads `plyX`, `plyVisible` or
`joyState`.

It is one array on purpose. `playerEmit` builds it and then compares it against
`plyPub`, the copy the builder last consumed; any difference sets `plyDirty`.
A later slice can change a pointer, a colour or the enable mask without having
to remember to set a flag, because **the block is the contract and the block is
what is compared**.

The two layers are co-located **by construction**: both X values and both Y
values are written from the same `plyX`/`plyY` in the same pass, so they cannot
drift apart by a frame the way two independently scheduled sprites could. That
is the one property the old three-layer experiment went to real trouble to
guarantee, and here it is free.

## 5. Publication and adoption

The player rides in the schedule it is not part of.

```
playerTick      joyState -> plyX / plyXHi / plyY, clamped          main thread
playerEmit      logical state -> plyPres (+ plyDirty)              main thread
buildSchedule   plyPres -> schedPly*[schedNext]                    main thread
publishSchedule schedPending = 1                                   one byte
exFrame         swaps CURRENT <-> NEXT at raster 250               frame IRQ
exHud           programs HW0/HW1 from the ADOPTED copy             raster 4
```

New arrays in `renderer.asm`'s `$c000 "schedule buffers"` segment, `[buffer]`
indexed exactly like the rest of the schedule: `schedPlyX0/Y0/Ptr0/Col0`,
`schedPlyX1/Y1/Ptr1/Col1`, `schedPlyEnable`, `schedPlyD010`. Twenty bytes; the
segment grew from `$c000-$c289` to `$c000-$c29d`.

The copy happens inside `buildSchedule`, **after** the existing withdrawal of a
pending publication and before anything else, for exactly the reason that
withdrawal exists: `schedNext` is the buffer the frame IRQ promotes, and only
`buildSchedule` may write it. `publishSchedule` is unchanged — one byte.

**Immutability of CURRENT** is structural, not a convention. Every one of the
ten stores is `sta schedPly…,x` with `X` loaded from `schedNext`; there is no
instruction anywhere in the program that can reach the adopted copy.
`tests/test_slice_a.py` checks this at source level (all ten stores indexed, `X`
loaded from `schedNext`, `schedCurrent` absent from the copy block, and no other
module containing `sta schedPly` at all).

**Rebuild is conditional.** `gameFrame` runs `sortTick` / `buildSchedule` /
`publishSchedule` only when `plyDirty | fixtureMoves` is non-zero. A frame in
which nothing moved has an identical schedule to the one already adopted, so
rebuilding it would be several thousand cycles spent reproducing bytes CURRENT
already holds. The picture is unaffected, including across a page flip, because
the pointer destination is patched per frame by `exFrame` and is not baked into
the schedule. This also keeps the **static** regression fixtures costing exactly
what they always cost.

## 6. Where HW0/HW1 are programmed

**`exHud`, raster 4**, immediately after the HUD's own slot loop and before the
`$d010`/`$d015` writes.

Raster 4 was chosen over the raster-40 handoff and the reason is margin.
`exHandoff` exits as late as raster 51 against `TOP_ARM_LINE = 53` — two lines,
the tightest margin in the engine. `exHud` enters at 4 and exited at raster 10
before this slice, against the HUD's own first sprite fetch at line 17. Sixty-
eight cycles of player programming belongs in the phase with a line to spare,
not the one without. Measured after the change: `hudExitMax` = 11, still six
lines clear.

Programming there has a second consequence worth stating: the player is
programmed **once per frame and then left alone**. No batch, no phase and no
main-thread routine touches `$d000-$d003`, `$d027/$d028` or the two pointer
entries again before the next raster 4. Its presentation is immutable for the
displayed frame in the strongest sense — not merely unmodified, but unreachable.
The test checks this directly by comparing the registers at raster 243 against
the block adopted at raster 250 of the previous frame.

`exHandoff` needed **no** change for the player beyond the zero-batch case in
§7, so the engine's tightest timing margin is untouched: `handoffExitMax` is 51
on RING-SLOW before and after.

## 7. `$d010` / `$d015` / mode composition rules

The rule: **every full-byte value is composed by whoever builds it, and written
once. No read-modify-write anywhere.**

**`$d015` and `$d010` — the player's bits are the SEED, not a later merge.**
`buildSchedule` starts `bs_enable` and `bs_d010` from `plyPresEnable` and
`plyPresD010` instead of from zero. The acceptance pass only ever touches bits
2..7 (`bitMask` is indexed by a slot, and slots are 2..7), so the two seeded
bits survive by construction and appear in:

- `schedEnable`, which `exHandoff` writes to `$d015` after batch 0;
- `bs_d010cum[]`, and therefore **every** `batchD010`, which each batch writes
  to `$d010`.

The executor needed no change at all for this. It already writes complete
values; those values now carry the player.

`exHud` composes the other side in a register: `lda schedPlyD010,x / ora
#HUD_D010 / sta $d010` and `lda schedPlyEnable,x / ora #HUD_ENABLE / sta $d015`,
with the enable written **last**, after every slot it names is programmed — the
same ordering discipline the handoff already followed.

**The zero-batch path was a real bug and is fixed.** `exHandoff` used to do
`lda schedBatches,x / bne exBatch / sta $d015` — writing zero, on the grounds
that there was nothing to enable. With a player there always is, and until
enemies exist that path runs on **every frame**. It now writes `schedEnable`.

**Mode registers.** The player needs `$d017`, `$d01c`, `$d01b` and `$d01d` to
have bits 0 and 1 clear: no Y expand, hires, in front of the playfield, no X
expand. Every value both phases write already satisfies that — `$d017`/`$d01c`
are written as `$00` outright, and `HUD_D01B` / `HUD_D01D` happen to have those
bits clear. "Happens to" is not a contract, so `renderer.asm` now **asserts** it
at assembly time:

```
HUD_D01B & PLAYER_SLOT_MASK == 0     the HUD would push the player behind the playfield
HUD_D01D & PLAYER_SLOT_MASK == 0     the HUD would X-expand the player
HUD_ENABLE & PLAYER_SLOT_MASK == 0   the HUD names a player slot
HUD_D010  & PLAYER_SLOT_MASK == 0    the HUD names a player slot
MUX_FIRST_SLOT >= 2                  the mux has been given a reserved slot
PLAYER_MIN_Y == MIN_SPRITE_Y         the two Y ranges have drifted apart
PLAYER_MAX_Y == MAX_SPRITE_Y
```

This is the scalable part. When blink and death arrive they change
`plyPresEnable` and nothing else; when multicolour enemies arrive, `$d01c` stops
being a constant zero and the assertion above is what will fail loudly.

**Pointers.** Four instructions now write a sprite pointer table — the batch
executor's, the HUD's, and the player's two (`plPtr0Store`, `plPtr1Store`) —
and `exFrame` patches all four high bytes from the same frame record in the same
place. `PTR_A+1` and `PTR_B+1` share the low byte `$f9` exactly as `PTR_A`/
`PTR_B` share `$f8`, so one patched byte selects the page for both. Two
unindexed stores were chosen over a loop deliberately: it is sixteen straight-
line instructions at the quietest raster in the frame, with no scratch and
nothing to get wrong. `tests/test_engine.py` was tightened from "exactly two"
to "exactly four, all in the renderer, all patched from one place", and its
regex now matches an unindexed `sta PTR_A+1` so a future writer cannot hide by
dropping the `,x`.

## 8. Player bitmap allocation and the art conversion

`PLAYER_SPRITES = HUD_SPRITES_END` = `$3580`, two 64-byte blocks, pointers
`$d6`/`$d7`. Derived from the HUD's pool rather than hardcoded, so a HUD that
grows takes the player with it instead of silently overlapping. Pointer values
are disjoint from the gameplay pool (`$80..$8f`) and the HUD's (`$c8..$d5`), so
a test can always tell which subsystem a pointer came from. Guarded at assembly
time for alignment, for overlap with the HUD pool and the gameplay pool, and for
running into the blank charset at `$3800`.

The old ship is a **multicolour** bitmap and this engine has no multicolour.
Rather than redraw it by eye, the original 63 bytes are kept verbatim in
`player.asm` and split into two hires layers by a rule stated once, in code:

```
multicolour pair 10        -> LAYER 0, the hull   (its per-sprite colour, 14)
multicolour pairs 01 and 11 -> LAYER 1, the trim  ($D025/$D026 detail, 15)
pair 00                    -> transparent in both
```

A multicolour pixel is two hires pixels wide at the same bit position, so the
split preserves the shape exactly — same 24x21 cell, same silhouette, same
proportions — and the two layers are disjoint by construction, so neither
punches a hole in the other. Verified from the assembled binary: 220 hull bits,
64 trim bits, **zero overlap**.

```
HW0  hull, colour 14              HW1  trim, colour 15
..........####..........          ........................
........########........          ........................
........##....##........          ..........####..........
......####....####......          ..........####..........
....######....######....          ..........####..........
..########....########..          ..........####..........
##########....##########          ..........####..........
..########....########..          ..........####..........
..####################..          ........................
....######....######....          ..........####..........
......####....####......          ........................
........................          ......####....####......
```
*(abridged: 12 of the 21 rows)*

The visible result is a light-blue hull with a continuous light-grey stripe from
the nose, down the fuselage, out through two exhaust flames. **The exhausts
exist only on the overlay**, so a frame that lost HW1 is obvious at a glance
rather than subtly wrong — the same diagnostic property the old experiment's
placeholder layers advertised, obtained from the real art.

One visual cost, stated plainly: two layers carry two colours, so the old
dark-grey (`$D025`) fuselage core and the light-grey (`$D026`) spine merge into
one light-grey stripe. The silhouette — the thing a player recognises — is
exact.

## 9. Player bounds

```
X   23 .. 321      the old game's limits, unchanged
Y   55 .. 226      MIN_SPRITE_Y .. MAX_SPRITE_Y, adopted unchanged
```

X is unchanged because the side borders are not opened (only the vertical one
is), so the 24-pixel ship slides under the border edge exactly as it used to.

Y deserves the longer note. The mux range is not obviously the right range for
HW0/HW1: they are outside the multiplexer so `MIN_REUSE_GAP` does not apply, and
their DMA is fetched in cycles 57..62 of the **previous** line rather than 0..9
of their own, so the bottom aperture split's margin is a different calculation
entirely. A wider range is probably available. **This slice does not take it,
because it has no measurement that would justify it** — 55..226 is already 171
pixels of travel, more than the old game's 182 minus the 11 it spent below the
aperture. `renderer.asm` asserts the two ranges still agree, so the day someone
widens one they are told to widen or re-derive the other.

What *is* load-bearing at 55: sprite Y is compared against the low byte of the
raster, so Y=55 matches again at raster 311. `exFrame` clears `$d015` at 250 and
`exHud` does not set it until raster 4, so that compare passes with nothing
enabled. A player allowed above 55 would start eating into that guarantee.

The bounds are applied as a **total clamp after the moves**, not as the old
pre-move refusal. Same behaviour at the edges, and no sequence of writes to
`plyX`/`plyY` — by a later system or by a test poking the machine — can leave
the ship outside the range the renderer is promised. The X clamp tests the sign
bit first, because a step left from X=0 leaves `plyXHi = $ff`, which as an
unsigned 16-bit number is far *above* the maximum and would clamp to the right
edge: the ship teleporting across the screen for one frame.

## 10. Input and movement

`readInput` is the only `$dc00` read in the game and it never writes it. Port A
of CIA1 is the keyboard column drive as well as joystick 2; nothing in this
program drives `$dc01` (port B is left an input), so no key can pull a column
low and be mistaken for a stick direction.

`playerTick` applies one pixel per axis per frame from the active-low bits, then
clamps. Diagonals move one pixel on each axis, as they did. Fire is sampled into
`joyState` and **nothing consumes it** — the test asserts `JOY_FIRE` appears
exactly once in the source, on its own `.const` line.

## 11. Production main loop

```
mainLoop:
    hudUpdate                    idle spin: HUD bitmaps, inside their raster window
    [fixtureKeyPoll]             debug builds only
    frameCounter != lastFrameSeen ?
        count a missed frame if it advanced by more than one
        gameFrame

gameFrame:
    [hudTick]                    the displayed page, before scrollTick may change it
    readInput                    $dc00 -> joyState
    playerTick                   joyState -> plyX / plyXHi / plyY
    playerEmit                   -> plyPres, and plyDirty if it changed
    hudDemoTick                  SLICE B REPLACES THIS
    motionTick                   only when a fixture is armed
    if plyDirty | fixtureMoves:
        sortTick / buildSchedule / publishSchedule
    regenTick
    scrollTick
    gameSpan                     the frame-cost instrument
```

The shape is deliberate: input, player, *weapons*, *enemies*, *collision*,
*waves*, *HUD feed*, then emit, then the three engine calls. Each system still
to come has one obvious place. The three engine calls are in the order
`ENGINE_CONTRACT.md` §1 fixes and that `main.asm`'s own frame-ownership note
explains — `hudTick` writes the page on screen right now, `regenTick` rebuilds
the page nothing is displaying, and `scrollTick` is the only thing that may
change which page that is.

`gameInit` replaces the boot-time `jsr rebuild`: `clearMotion`, `logCount = 0`,
`sortReset`, `playerInit`, `playerEmit`, then one build and publish so frame 0
already has a player.

## 12. How the fixtures are separated from startup

`FIXTURE_KEYS = false` in `src/main.asm`. That single constant guards the call
to `fixtureKeyPoll`, which is where `readNextFixture` and its three siblings now
live. Those routines **write `$dc00`** to drive a keyboard column, and `$dc00`
is the register the stick is read from; leaving them in the loop would have the
input system and the fixture selector taking turns owning the same port.

Nothing is deleted. `fixtures.asm`, the P3/P4/P5 tables, `loadFixture`,
`rebuild` and `republish` are all still assembled and still reachable, because
`make test` selects fixtures the way it always has — poking `fixtureIndex` and
calling `rebuild` through the monitor, which needs no keyboard at all. The
routine itself is assembled in both builds on purpose: guarding the definition
too would give the debug and production builds different layouts, and the whole
value of keeping the fixtures is that selecting one measures the *same binary* a
human is playing.

A fixture cannot mutate player or game state: `loadFixture` touches the logical
sprite arrays and motion state, and `gameInit` is the only writer of the player
record at startup. A fixture that *is* armed still moves and rebuilds every
frame exactly as before, which is why the regression numbers below are
comparable at all.

## 13. Zero-enemy behaviour

This is the configuration the game actually runs in until Slice C, and it is
tested first rather than last. Measured at the production boot:

```
logCount 0    schedEntries 0    schedBatches 0    statAccepted 0
schedEnable $03                 the player and nothing else
pointers $d6 / $d7              on whichever page is displayed
```

`exHandoff` takes its no-batches path on every frame and now writes
`schedEnable` there rather than zero (§7). `exTop` is armed explicitly on that
path, as it always was, so the aperture still opens. `handoffExitMax` is now
instrumented on that path too — it previously read zero in production, leaving
the margin to the top split unmeasured in the only configuration that matters.
It reads 41, twelve lines clear of `TOP_ARM_LINE`.

## 14. Timing measurements

New instruments in `src/main.asm`, in the engine's own style (min/max and
saturating counts, because a wrapping counter reads zero after a long run and
looks clean):

- **`gameSpanMax`** — worst main-thread span in raster lines measured from the
  frame transaction at 250. Stated as an elapsed span, not a raw `$d012`,
  because the game frame straddles the frame boundary; and it reads `$d011` bit
  7 first, because `$d012` alone calls raster 260 "4".
- **`gameSpanOver`** — frames whose span exceeded 255 lines (the span is then a
  floor).
- **`gameOverrun`** — displayed frames the main thread did not prepare a frame
  for.

### Static cost of the change

| Site | Added | Where |
|---|---|---|
| `exHud` player block | 17 instructions, 68 cycles | raster 4 |
| `exHud` composition | 2 × `ora`, 8 cycles | raster 4 |
| `buildSchedule` copy + seed | ~110 cycles | main thread, only on a rebuild |
| `exHandoff` zero-batch | ~18 cycles | raster 40, 0-sprite frames only |
| raster executor size | +77 bytes (`$3005` → `$3052`) | 429 bytes of headroom to `$3200` |
| schedule buffers | +20 bytes (`$c289` → `$c29d`) | 98 bytes of headroom to `$c300` |

### Measured — production, 0 gameplay sprites

```
main-thread span         78 raster lines  (~4,914 cycles of 19,656 -- 25%)
frames over 255 lines     0
missed frames             0
publishSkip               0
hudExitMax               11   (HUD's first fetch is line 17)
handoffExitMax           41   (TOP_ARM_LINE is 53)
frameEntryLine          250   flipLine 250..250
topSplit           [54, 55]   botSplit [248, 248]   edgeLate 0
scrollLate                0   statPageMismatch 0   statPtrMismatch 0
hudUpdWrapped             0
```

### Measured — A/B against the pre-slice baseline

Built from `HEAD` in a throwaway `git worktree`, measured by the same script
against both binaries, RING-SLOW selected in both, **non-warp** because
`publishSkip` is a saturating byte that pegs at 255 under warp and measures
nothing.

| metric | baseline (HEAD) | current |
|---|---|---|
| frames sampled | 613 | 402 |
| `publishSkip` | 26 (**4.2 %**) | 18 (**4.5 %**) |
| `scrollLate` | 0 | 0 |
| `edgeLate` | 0 | 0 |
| `hudExitMax` | 10 | **11** |
| `handoffExitMax` | 51 | **51** |
| `gameOverrun` | *(no counter)* | 23 of 402 (5.7 %) |

**The player did not materially worsen the engine's timing.** RING-SLOW's
publication skip rate moves by 0.3 percentage points. `exHud` grew by one raster
line, which is the 76 cycles above, and it is still six lines clear of the HUD's
first fetch. The handoff — the tightest margin in the engine — is unchanged to
the raster.

The frame counts differ between the two runs because `-console` VICE does not
throttle to 50 Hz with no display to sync to; both builds were measured
identically, so the rates are comparable even though neither is a PAL-time rate.

RING-SLOW's own numbers under warp saturate every counter (`gameSpanMax` 255,
`gameOverrun` 255, `publishSkip` 255). That is the workload
`ENGINE_CONTRACT.md` §10 names as a known deferred performance issue, and
`test_slice_a.py` deliberately **reports without asserting** there: asserting a
budget on RING-SLOW would be asserting that a documented open issue is closed.

## 15. Page and pointer proof

`exFrame` patches four pointer-store high bytes from the one frame record, at
the same instant it decides `$d018`. Measured over ten stops at raster 243
spanning both pages (7 on page B, 3 on page A): the **displayed** page's table
held `$d6`/`$d7` on every one of them, and the engine's own `statPageMismatch`
and `statPtrMismatch` self-checks read zero. `flipLineMin`/`Max` are both 250.

Because `exHud` rewrites the pointers from CURRENT every frame through a
per-frame-patched store, a page flip needs no republish to carry the player
across — the same mechanism that already carries the HUD.

## 16. HUD coexistence proof

The HUD is untouched and still in demonstration mode. At raster 40, with the
HUD's values fully live:

```
$d015 = $ff   = HUD_ENABLE ($fc) | player ($03)
$d010 = $80   = HUD_D010   ($80) | player ($00 at X < 256, $03 above)
```

`hudUpdWrapped` is zero and `hudUpdStartMin` ≥ 56 on every fixture, so no HUD
bitmap write reached the VIC's fetch window. `hudEntryMin`/`Max` are both 4.
Every live HUD pointer is still inside `$c8..$d5` and collides with neither the
gameplay pool nor the player's.

**Y+256 ghost:** checked directly by stopping at `exHud`'s entry — raster 4,
after the ghost compare at 311 has gone by and before this phase writes
anything. `$d015` reads `$00`. Nothing is enabled anywhere between the frame
transaction and the HUD phase, and the player's Y floor of 55 keeps it that way
by construction.

## 17. Aperture regression

`topSplitMin/Max` = `[54, 55]` and `botSplitMin/Max` = `[248, 248]` across all
five fixtures and the production boot, with `edgeLate` = 0 and `scrollLate` = 0.
Unchanged.

One harness note that matters for anyone reading an earlier log: an intermediate
run of this slice's test reported `topSplit [55, 55]`, which would mean the
YSCROLL=7 frames had stopped splitting on 54. It was a **monitor
desynchronisation**, not an engine change — an isolated re-measurement and every
subsequent run read `[54, 55]`. See §20.

## 18. Retained regression result

```
make test    ->  ALL PASS  (tests/test_engine.py + tests/test_slice_a.py)
```

`tests/test_engine.py` runs its five-fixture sweep with the first row now being
the **production boot** rather than fixture 0 — "the engine still holds every
invariant with an empty mux" is the state the game actually runs in, so it is
tested first. Its single-writer checks were tightened, not weakened: four
pointer-writing instructions instead of two, all four patch sites, and
`player.asm` added to the list of modules that must write no VIC register.

`make test-engine-full` was **not** run, and that is a decision rather than an
omission: no raster line, admission value, aperture constant or page rule
changed in this slice. The phase schedule is checked across five fixtures by the
probe above, which is the coverage the change actually needs. If the renderer's
phases are touched again, the full ladder is the gate.

## 19. Known deferred issues

- **Scroll direction (Slice A′).** Untouched here, as instructed. The new
  scroller counts `scrollFine` **down** 7..0 and **increments** `worldRow`, so
  terrain moves up; the old game increments its fine scroll and decrements
  `SCROLL_ROW`, so terrain moves down and the authored level is walked
  bottom-to-top from `STAGE_START_ROW = STAGE_LOGICAL_ROWS - 23`. **Nothing in
  this slice assumes either direction** — the player is in screen space, has no
  world row, and never reads `worldRow`, `scrollFine` or `dispPage`. Slice A′
  will need to revisit `exTop`'s YSCROLL=7 special case across all eight phases,
  and the descending sort order of the authored wave-trigger and turret tables.
- **Sorter stale-ID prerequisite (before Slice C).** `sortTick` restates
  `sortedCount = logCount` every frame but only `sortReset` re-permutes
  `sortedIDs`. If a dynamic enemy pool shrinks `logCount`, the sorted prefix can
  name an ID that no longer exists and the builder will schedule it. Not
  triggered here — `logCount` is 0 and constant — and the audit's recommendation
  stands: a fixed-size pool with inactive entries **parked** at Y=0 (rejected by
  admission and counted in `statRejRange`, which is not a fault) keeps
  `sortedIDs` a permutation of 0..N-1 forever and keeps logical IDs stable for
  the life of a slot. **This must be settled before enemies arrive.**
- **RING-SLOW / RING-SHIFT judder** remains deferred per `ENGINE_CONTRACT.md`
  §10, and this slice's A/B confirms it was not made materially worse. The new
  `gameOverrun` counter gives it a more direct measurement than `publishSkip`
  ever did: 5.7 % of frames missed on RING-SLOW, 0 % in production.
- **Player Y range** could probably be wider than the mux's 55..226 (§9). Needs
  a measurement, not an argument.
- **Multicolour** for enemies would make `$d01c` stop being a constant zero and
  would need `$d025`/`$d026` in the handoff contract. The assertions in §7 are
  what will fail loudly on that day.

## 20. VICE and disk cleanup

Every automated launch was `-console`, direct, never `open -a`, never focused,
with both joystick devices detached. Each run owned exactly the PIDs it launched
and reaped them on success, failure and interrupt — including two runs that were
deliberately interrupted mid-flight, where the `try/finally` reaped VICE
correctly. `pgrep -fl x64sc` is clean; no manual VICE session was touched.

The throwaway baseline `git worktree` was removed; `git worktree list` shows
only the repository. All transient output went to `/tmp` and was deleted.

```
build/   76K     main.sym  main.vs  shmup.prg     (three files, no per-run dirs)
.        1.7M
```

Two harness lessons were paid for during this slice and are recorded in
`tests/test_slice_a.py`'s own header, because they will bite the next slice
otherwise:

1. **Sample at a phase, not at "wherever the monitor halted."** Under warp VICE
   stops on a frame boundary, so a first draft took fourteen samples and every
   one landed in the vertical blank — the entire mid-display state went
   unobserved while the test reported nothing wrong.
2. **Read in bulk and verify the stop.** A dozen monitor commands per sample
   desynchronised the monitor badly enough that a *verified* fixture selection
   read back as an empty schedule, and `mon.cmd("x")` returning on a prompt echo
   let samples be taken from a still-running machine. `at_phase` now clears all
   checkpoints, sets one, and throws away any sample whose raster is not the
   phase's own line. The `[55, 55]` top-split reading in §17 was this.

Also worth recording as a plain VIC-II fact that cost an hour: **`$d027-$d02e`
are four-bit registers and read back with the top nibble set**, so colour 14
reads as `$fe`. A test comparing the raw byte against the published colour fails
on a machine doing exactly the right thing.

## 21. Manual test — please run this

```sh
make run              # numpad drives the stick
make run JOY2=4       # ...or the first real joystick/gamepad
```

`JOY2` selects the host device for control port 2. A MacBook keyboard has no
numpad, so a laptop without a controller wants `JOY2=4` with something plugged
in. **If the ship does not move, change this first** — the C64 side cannot tell
"no stick" from "no device".

Expected on startup: scrolling terrain, the live top-border HUD, the player ship
at centre-bottom, and **no synthetic enemy fixture**.

Please check, at normal speed and without warp:

1. the stick moves the ship in all eight directions, one pixel per frame;
2. the movement feels like the old game's — direct, no glide, no acceleration;
3. both layers stay locked: the grey centre stripe and the two exhaust flames
   never separate from the blue hull, at any speed or direction;
4. crossing X=255/256 is clean in both directions — no 256-pixel jump, no
   one-frame flicker. Slide slowly across the middle of the screen ten times;
5. no player flicker anywhere, including while held against each bound for
   twenty seconds;
6. no HUD corruption: the heat bar, score, lives and status behave as they did;
7. no gameplay handoff corruption — nothing appears in the top border below the
   HUD;
8. no page-flip glitch: watch for a one-frame wrong-bitmap on the ship, which
   would appear roughly six times a second;
9. no ghost ship in the lower border;
10. the terrain aperture is as smooth as it was before this slice;
11. the ship is stable with zero enemies for a long run — leave it for two
    minutes;
12. driving into a bound and back out cannot corrupt the sprite — hold each
    corner, then move away, repeatedly.

Please do not treat this slice as accepted until you have watched item 3 and
item 5 for a while. **Do not begin scroll direction, weapons, enemies, collision
or waves until you have accepted Slice A.**

---

## Files

```
new       src/player.asm              state, input, movement, presentation block, art
new       tests/test_slice_a.py       the game path: boot, player, composition
modified  src/renderer.asm            player block, publication, exHud, handoff, assertions
modified  src/main.asm                production loop, gameInit, fixture guard, instruments
modified  tests/test_engine.py        four pointer stores; production boot as the first row
modified  Makefile                    JOY2, the test-slice-a target, make test runs both
modified  README.md                   it boots into the game now
```

Not committed, per `AGENTS.md`.
