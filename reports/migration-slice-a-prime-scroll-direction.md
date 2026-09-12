# Migration Slice A′ — scroll direction and the world contract

12 September 2026 · PAL C64 · KickAssembler 5.25 · VICE 3.10 `x64sc`

The playfield now scrolls **downward**, which is the original game's forward-play
direction, and the stage is addressed through a contract that says what
progression means before any gameplay system depends on it. The double-buffered
pages, the raster-250 frame transaction, the blank-charset aperture, the pointer
ownership rules, the HUD and the player are untouched.

**Automated: green.** `make test` — three probes — passes, and `tests/test_p1.py`,
the scroller's own qualification test, passes over 23,853 frames and eleven stage
wraps. **Manual: not yet assessed.** Section 19 is the test a human has to run.

Reference for the old game: `c64Shooter-main.zip`, unpacked outside both
repositories. It is not at `Dev/C64 ASM/c64Shooter` on this machine; the copy
used is byte-identical to the Desktop archive.

---

## 1. Exact old-game scroll direction

**Terrain moves DOWN the screen. The player flies UP through the level. New
terrain enters at the TOP.**

Three independent pieces of the old source agree.

`c64Shooter/src/main.asm:6627` `updateBackgroundScroll` **increments** the fine
scroll:

```asm
    lda SCROLL_FINE
    cmp #7
    beq !coarse+
    inc SCROLL_FINE
```

`docs/background-engine.md` states the consequence the hardware imposes:

> With a fixed YSCROL value, matrix row `r` begins at raster `48 + 8*r + YSCROL`.
> Thus **increasing YSCROL moves scenery down**. On `7 -> 0`, old row `r` must
> become row `r+1` […] Discard old row 24 and introduce one new row at row 0.

And `main.asm:6880` `bgUpperCopied`, at the coarse step, says it in words:

> New scenery enters **ABOVE** the previous top row: step the 16-bit logical
> stage position back one row.

## 2. Old stage-row progression semantics

`SCROLL_ROW` is 16-bit and **decrements** by one per coarse step
(`main.asm:6890-6899`, and again on the double-buffered flip path at 6759-6777):

```asm
    lda SCROLL_ROW
    sec
    sbc #1
    sta SCROLL_ROW
    lda SCROLL_ROW_HI
    sbc #0
    sta SCROLL_ROW_HI
```

The row mapping is `main.asm:6388` `renderStageRowToScreen`:

```
BG_LOGICAL_ROW = SCROLL_ROW + BG_DEST_ROW - 1
```

so matrix row **1** shows `SCROLL_ROW`, rows 1..23 are the terrain body, matrix
row 0 is the incoming overflow (`SCROLL_ROW - 1`) and row 24 the outgoing one.

**Forward play therefore means a decreasing map index.** That is the semantic
the whole content layer is written against.

## 3. Old level-map start and end convention

`main.asm:768-782`, verbatim:

> Bottom-origin startup. The editor stores rows top-to-bottom in visual order;
> for this upward-scrolling game the AUTHORED BOTTOM (highest logical rows) is
> the BEGINNING of gameplay. […] The existing coarse-scroll decrement then walks
> the viewport upward (`SCROLL_ROW--`) through the whole authored level to
> logical row 0, and only then wraps `0 -> STAGE_LOGICAL_ROWS-1`.

```asm
.const STAGE_START_ROW = STAGE_LOGICAL_ROWS - 23
```

- **Start** = the authored bottom, the highest row indices, no wrap in the first
  viewport.
- **End** = authored row 0, the visual top of the map.
- **After the end** the stage wraps and plays again, re-arming its content:
  `TURRET_STREAM_REWIND` and `WAVE_TRIGGER_REWIND` are both set at the wrap
  (`main.asm:6767`, `6889`).

## 4. Level-editor and export assumptions discovered

| Artefact | Assumption |
|---|---|
| `tools/level_editor` → `stage_test.asm` | rows stored **top-to-bottom in visual order**; index 0 is the visual top and is reached **last** in play |
| `stage_waves.asm` | `waveTriggerRow*` sorted **DESCENDING**, "the order the downward-scrolling `SCROLL_ROW` crosses them"; a trigger fires when its row reaches the top of the aperture (`SCROLL_ROW <= triggerRow`) |
| `stage_turrets.asm` | `turretRows` sorted **descending**, at least 2 rows apart; admitted when `SCROLL_ROW <= turretAuthRow + MARGIN` |
| `stage_config.asm` | `SCROLL_FRAME_DIVIDER = 2` is **level-owned**, not an engine constant |
| turret screen Y | `positionBackgroundTurrets`: `rel = (slotRow - SCROLL_ROW) mod SLR`, `Y = rel*8 + 64 + fine` |

Every one of these is written for a decreasing row index. Preserving the
direction is what keeps them portable **unchanged** — which is the whole reason
this slice happens before wave, turret and editor migration rather than after.

**One finding deliberately not acted on.** `SCROLL_FRAME_DIVIDER = 2` means the
old game scrolls one pixel every *two* frames; the new engine scrolls every
frame. That is a speed, not a direction or a traversal semantic, and it is
level-owned data in the old repo — so it arrives with the level package in
Slice H rather than being smuggled in here, where it would have muddied this
slice's before/after timing comparison for no benefit. Recorded so it is not
forgotten.

## 5. The chosen production world contract

Documented in `docs/ENGINE_CONTRACT.md` §8a, which is where game code will look
for it, and restated independently in `tests/test_slice_a_prime.py`.

```
The playfield scrolls DOWNWARD. New terrain enters at the TOP.

matrix row r  shows stage row  stageTopRow + r          r = 0..24
fine scroll   counts UP 0..7   content moves down one pixel per step
coarse step   on the 7 -> 0 wrap: stageTopRow steps BACK one, the page flips
```

**Two counters, because one variable cannot honestly mean both things.**

| value | meaning |
|---|---|
| `stageTopRow` (16) | which row of the **map** is at matrix row 0. **Decreases.** Scroller-owned; the row renderer is its only consumer. |
| `worldProgress` (16) | how far through the stage we are, in coarse rows. **Only ever increases.** This is the one game systems read. |
| `scrollFine` | 0..7, counting up |
| `stageLoops` (16) | times the map has wrapped end to end |
| `STAGE_ROWS` = 420 | the stage height. Level1's real height (105 metatile rows × 4), chosen over a power of two so the 16-bit arithmetic and the modulo wrap are genuinely exercised. |
| `STAGE_START_ROW` = 395 | `STAGE_ROWS - 25`: the first page is the authored bottom, `[395..419]`, with no wrap in it |

The relationship is exact and is checked on every frame of a trace rather than
trusted:

```
stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS
```

The point of paying ten instructions once every eight frames for the second
counter is that **no future subsystem has to encode "forward means subtract"**.
That is the mistake that would otherwise be copied into waves, turrets, triggers
and stage completion one at a time, and each copy would have to be right.

Screen-Y projection is documented but **not implemented**: the contract records
that matrix row `n`'s top pixel is at raster `48 + scrollFine + 8n` and that the
constant a game system should use must be **measured, not derived**, because the
aperture starts at 55 and rows 0 and 24 are partly clipped. Writing a helper now,
before any caller exists and before that measurement, would be inventing an API.

## 6. Variables and API introduced or renamed

| before | after | why |
|---|---|---|
| `worldRowLo/Hi` | `stageTopRowLo/Hi` | it now decreases; leaving the name would be exactly the overloading this slice removes |
| — | `worldProgressLo/Hi` | the game-facing progression value |
| — | `stageLoopsLo/Hi` | makes the wrap observable |
| `regenWorldLo` (8-bit) | `regenTopRowLo/Hi` (16-bit) | a 420-row stage does not fit a byte |
| `pageWorldLo[2]` | `pageTopRowLo[2]`, `pageTopRowHi[2]` | same, and 16-bit |
| `rrWorld` | `rrStageLo/Hi` | 16-bit, and it is a stage row |
| — | `rowBack`, `rbLo/rbHi` | one step-back-with-wrap, used twice per coarse step |
| — | `STAGE_ROWS`, `STAGE_START_ROW` | placeholders until a level package owns them |

Consumers updated: `src/main.asm`'s `drawScrollRow` diagnostic, `tests/test_p1.py`.

## 7. Fine-scroll sequence, before and after

```
before   7 6 5 4 3 2 1 0 | 7 6 5 ...     content moves UP one pixel per step
after    0 1 2 3 4 5 6 7 | 0 1 2 ...     content moves DOWN one pixel per step
```

Measured, 71 adjacent frames verified by frame number:

```
YSCROLL   [4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7, 0, ...]
```

`finePhase` over 5,373 production frames: `[671, 672, 672, 672, 672, 672, 672,
671]` — all eight phases, evenly.

One consequence worth naming: the frame immediately after a coarse step used to
be YSCROLL 7, and is now YSCROLL 0. `exTop`'s special case (split at 54 instead
of 55 when YSCROLL is 7, because line 55 is then itself a badline) keys off the
**value**, not the order, so it is unaffected — and §12 shows it still fires.

## 8. Coarse-row transition, before and after

| | before | after |
|---|---|---|
| trigger | fine `0 -> 7` | fine `7 -> 0` |
| world index | `worldRow` **+1** | `stageTopRow` **-1** (mod `STAGE_ROWS`), `worldProgress` **+1** |
| page | flips | flips (unchanged) |
| back page prepared with | `worldRow + 1` | `stageTopRow - 1` |
| newly revealed row appears at | matrix row **24** (bottom) | matrix row **0** (top) |

Measured over 71 adjacent frame pairs: world progress, the stage row and the
page each change on the `7 -> 0` wrap **and on no other pair**; progress steps
`+1`, the stage row steps `-1 mod 420`, and the stage row never advances forward
through the map on any pair.

Cadence, three independent runs: 8.01, 7.99 and 8.00 frames per coarse step.
`test_p1` over 23,853 frames: 2,982 coarse steps, 2,982 page flips (1,491 each
direction).

## 9. Hidden-page regeneration changes

`renderRow` now computes a **16-bit** stage row per matrix row:

```
rrStage = (regenTopRow + regenRow) mod STAGE_ROWS
```

reduced by **one conditional subtract**, not a general modulo: `regenTopRow` is
already reduced and `regenRow` is 0..24, so the sum is below `STAGE_ROWS + 25`.
A repeated-subtraction modulo on a path that runs five times a frame would have
been the wrong shape.

At the coarse step, `regenTopRow` is obtained by calling `rowBack` a second time
on the value it already holds — the stage row just adopted — so the back page is
built with the row the **next** coarse step will reveal at the top.

`scrollInit` seeds page A with `[395..419]` and page B with `[394..418]`, so the
first coarse step flips to a page that is already correct.

## 10. Page-flip proof

Sampled inside `exFrame` after adoption, with **the raster verified** so no
sample comes from a machine that was still running:

- four consecutive flips, each moving the window back by **exactly one** stage
  row: `[1, 1, 1, 1]`;
- on each, the newly displayed page's **top row identity on screen** equals the
  newly revealed stage row: `('0x632','0x632'), ('0x631','0x631'), ('0x630','0x630')`;
- `flipLineMin == flipLineMax == 250` over the whole run;
- `statPageMismatch` and `statPtrMismatch` both zero;
- `test_p1`: 2,982 flips, every one at raster 250, `pageTopRow` naming the stage
  row the displayed page really starts at.

## 11. Row continuity proof

At a verified stop:

- the **displayed** page holds stage rows `243..267`, in order, all 25 rows
  checked against their printed identity;
- no two adjacent rows of the displayed page are identical (a mirrored page
  would still hold the right *set* of rows; this catches the order);
- `regenTopRow == (stageTopRow - 1) mod STAGE_ROWS`;
- the **hidden** page already holds `242..266`, all 25 rows checked;
- `pageTopRow[displayed]` equals `stageTopRow`.

`test_p1`'s independent check — every displayed row prints its own stage row
number — passes across a 23,853-frame stress run that crosses **eleven** stage
wraps (`worldProgress` 4,571, `stageTopRow` 24; `(395 - 4571) mod 420 = 24` ✓).

## 12. Aperture proof

```
topSplitMin/Max    [54, 55]     54 on the YSCROLL=7 frames, 55 otherwise
botSplitMin/Max    [248, 248]
edgeLate           0            no split ever missed its own target line
```

Unchanged from before the slice, on the production configuration and on
MAXCAP, RING-SLOW and RING-SHIFT.

**One test expectation was deliberately changed, and it is worth the paragraph.**
`test_engine.py` required `topSplit == (54, 55)` exactly on every fixture. That
demands not only that each split lands on its own target but that a YSCROLL=7
frame was *displayed* during the window — which is a statement about the
fixture's frame-record health, not about the aperture. On RING-FAST it stopped
holding.

The measurement:

```
RING-FAST   finePhase 0..7  [606, 606, 606, 606, 605, 605, 605, 605]
            topSplit [55, 55]   edgeLate 0   publishSkip 255 (saturated)
```

Phase 7 is reached 605 times by the main thread and **never adopted**.
RING-FAST's main thread is over budget and drops frame records with a period of
two (`ENGINE_CONTRACT.md` §10), so the displayed phases are a subsample of the
eight — and reversing the direction reversed which subsample survives. Every
split it *did* display landed exactly on its target: `edgeLate` is zero.

So the check now asserts what it means — every split landed on one of the two
legal lines and `edgeLate` is zero — and asserts the exact `(54, 55)` pair on the
**production** configuration, where nothing is dropped and all eight phases must
appear. That is narrower where the claim was never guaranteed and *stronger*
where it is. A second check was added at the same time: the probe now verifies
that a fixture actually loaded, because a silently unselected fixture measures
an empty schedule and passes everything.

## 13. Player stability proof

The player is **screen-space** and has no world relationship at all: it never
reads `stageTopRow`, `worldProgress`, `scrollFine` or `dispPage`. No camera
follow was introduced and no movement code was touched.

Measured across an 8-second warp run spanning hundreds of coarse steps and page
flips: `plyX`/`plyY` unchanged at `(160, 220)`, and `$d015` read **at raster
243** carries `$03` — both reserved slots still enabled with zero gameplay
sprites. `tests/test_slice_a.py` continues to pass in full, including the
composition and page-flip pointer checks.

## 14. HUD stability proof

```
hudEntryMin/Max    [4, 4]
hudExitMax         11        the HUD's own first fetch is line 17
hudUpdWrapped      0
hudUpdStartMin     >= 56
handoffEntryMin/Max [40, 40]
handoffExitMax     41 production / 51 with a full mux   (TOP_ARM_LINE is 53)
```

Unchanged. The HUD was not touched by this slice.

## 15. Timing and cycle comparison

| | Slice A | Slice A′ | delta |
|---|---|---|---|
| main-thread span, production | 78 raster lines | **82** | +4 lines (~252 cycles) |
| as a share of the frame | 25 % | 26 % | +1 pt |
| `gameOverrun` (missed frames) | 0 | **0** | — |
| `gameSpanOver` | 0 | **0** | — |
| `publishSkip`, production | 0 | **0** | — |
| `scrollLate` | 0 | **0** | — |
| frames per coarse step | 8.00 | **8.01 / 7.99 / 8.00** | — |

The +4 lines is `regenTick`: five rows a frame, each gaining a 16-bit add and a
conditional subtract for the stage-row modulo — roughly 50 cycles a row, 250 a
frame. It is the arithmetic a 420-row stage requires, it is accounted for, and
it is the whole cost of the change.

`scrollTick` itself is within a few cycles of neutral: the fine-scroll compare
replaces a `bpl`, the coarse path trades `inc worldRow` for two `rowBack` calls
and a progress increment, and the common path pays two cycles for the inverted
branch (see §16).

## 16. Automated test changes

**New:** `tests/test_slice_a_prime.py`, added to `make test`, which is now three
probes. Its heart is one trace: stopping inside `exFrame` after adoption, on
consecutive frames, gives the displayed YSCROLL, the stage row, the progress
counter and the page **together**, so direction, cadence, progression and row
continuity are all statements about how those four move relative to each other
and no two checks can disagree about which frame they were looking at.

**Updated deliberately:**

- `tests/test_p1.py` — `worldRow == coarseCount` became `worldProgress ==
  coarseCount` **plus** `stageTopRow == (STAGE_START_ROW - worldProgress) mod
  STAGE_ROWS`. The old check was true only while the world row counted up from
  zero; the replacement checks both halves of what replaced it. Row identities
  and `pageTopRow` follow the rename and are now 16-bit.
- `tests/test_engine.py` — the top-split expectation, for the reason set out in
  §12, plus a new check that a fixture actually loaded.
- `docs/ENGINE_CONTRACT.md` — new §8a, the world contract.

**Two bugs the tests caught, both mine.**

1. **`rowBack` was written into the gap between `scrollPublish` and
   `publishFrame`.** That gap was a deliberate fall-through, so `scrollPublish`
   fell into `rowBack` instead and `publishFrame` was never called again after
   boot. Everything downstream still looked alive — the fine counter cycled,
   `finePhase` filled evenly, coarse steps counted, stage rows advanced, the back
   page regenerated — because all of that is main-thread bookkeeping. The only
   thing that stopped was the one byte that carries it to the screen, and the
   screen simply held still. An invisible adjacency was doing real work; it is
   now an assembly-time assertion:

   ```asm
   .if (publishFrame != scrollPublishFallsInto) {
       .error "scrollPublish no longer falls through into publishFrame"
   }
   ```

2. **A branch fell out of range.** The grown coarse block pushed
   `bcc scrollPublish` past 128 bytes. Inverted to `bcs` plus an absolute `jmp`,
   which is the rule `renderer.asm` already states for far targets.

**And one harness lesson, for the third time this project.** `mon.cmd("x")`
returns on a prompt echo rather than on the actual stop, so a sample can be read
from a machine that never stopped. It produced a YSCROLL sequence of
`3,3,4,5,6,0,0` on a machine advancing one pixel per frame perfectly, and before
that a `topSplit [55,55]` reading that was pure fiction. Every sampler in this
slice now **verifies where it stopped** — by raster, and by frame number — and
discards anything else. Slice A's `at_phase` learned the same thing about
rasters; this is the same rule applied to frames.

## 17. Finite-stage semantics, deferred

**What happens at row 0 today:** the window steps back to `STAGE_ROWS-1` and the
map plays again from its authored bottom. For 25 coarse steps either side of the
join the displayed window straddles it, so the map's top rows sit above its
bottom rows and there is a content seam. The original game did exactly this and
called it looping back to the start.

**Whether the demo data wraps:** yes, every 420 coarse steps — about 56 seconds
at one pixel per frame. `stageLoops` counts it, so the wrap is observable rather
than invisible, and the test asserts the counter against the closed form
`1 + (worldProgress - 1 - STAGE_START_ROW) // STAGE_ROWS`.

**How a finite stage should signal completion:** by comparing `worldProgress` —
which never wraps — against the stage length. That is a game-state decision
(something has to decide what a finished stage *does*) and is deliberately not
made here.

**What must not happen** is an unsigned underflow quietly becoming the contract.
It cannot: the wrap is an explicit fold performed before any subtraction, the
value is reduced on every path, and the modulo relationship between the two
counters is checked on every frame of a trace.

## 18. Known deferred issues, carried forward unchanged

- **Sorter stale-ID prerequisite** before a dynamic enemy pool. `sortTick`
  restates `sortedCount = logCount` every frame but only `sortReset`
  re-permutes `sortedIDs`; a shrinking pool can leave the sorted prefix naming
  an ID that no longer exists. Not triggered here — `logCount` is 0 and constant.
  **Must be settled before Slice C.**
- **RING-SLOW / RING-SHIFT judder** under the synthetic 16-sprite moving
  workload, per `ENGINE_CONTRACT.md` §10. Not optimised here. §12 records a new
  observation about it: the phases a starved fixture displays are a subsample,
  and which subsample depends on the skipping pattern.
- **Realistic 6/8/10/12/14/16-sprite qualification** waits for real scenes.
- **No enemy, wave, collision, turret or game-state migration** in this slice.
- **Level editor / export ABI** waits until the runtime stage data contract
  stabilises. This slice fixes the *direction* half of that contract; the data
  half arrives with Slice H.
- **`SCROLL_FRAME_DIVIDER = 2`** — the old game's scroll speed, level-owned data,
  deliberately not imported here (§4).
- **Screen-Y projection constant** for placing a stage row on screen: documented
  as to-be-measured, not derived.

## 19. Manual test — please run this

```sh
make run              # numpad drives the stick
make run JOY2=4       # ...or the first real joystick/gamepad
```

The background is a diagnostic pattern and it is the direction proof. Each row
prints its **stage row number** in hex at the left, there is a solid bar every
fourth row, and a `*` marker walks a diagonal. Read the numbers: they increase
as you look **down** the screen, and each individual row keeps its own number as
it travels.

Please check, at normal speed and without warp:

1. **the terrain moves DOWN the screen**, and new rows appear at the **top** —
   this is the whole slice;
2. the row numbers at the left count **downward** over time as new lower-numbered
   rows arrive from the top;
3. the `*` diagonal is not mirrored — it should lean the same way it always did,
   because only the motion reversed, not the row order;
4. no repeated or skipped strip at a coarse transition — watch the hex column
   for a number appearing twice or a number missing;
5. the top entry edge is pixel-smooth: a new row is revealed one pixel at a
   time, never popping in as a whole row;
6. the bottom exit edge is pixel-smooth in the same way;
7. page flips are invisible — they happen about six times a second, so watch a
   fixed point on screen for twenty seconds;
8. the player is stable and controllable, and does **not** drift with the
   background;
9. the HUD is unchanged and steady;
10. no new background flicker anywhere.

Worth a longer look: leave it running for **a minute** and watch the stage wrap.
At the join the map's top rows meet its bottom rows, so the hex numbers jump from
`00` to `1a3` (419) and the pattern discontinues for about 25 rows. **That is
expected** — it is the demonstration stage looping, exactly as the old game
looped — and it is the one visual event in this slice that is meant to look like
a seam.

Please do not treat this slice as accepted until you have watched items 1, 4 and
5. **Do not begin weapons, enemies, waves, collision, turrets, stage triggers or
editor integration until you have accepted Slice A′.**

## 20. VICE and disk cleanup

Every automated launch was `-console`, direct, never `open -a`, never focused,
with both joystick devices detached. Each run owned exactly the PIDs it launched
and reaped them on success, failure and interrupt. `pgrep -fl x64sc` is clean and
no manual VICE session was touched. All transient probes and logs went to `/tmp`
and were deleted; `git worktree list` shows only the repository.

```
build/   76K     main.sym  main.vs  shmup.prg     (three files, no per-run dirs)
.        1.8M
```

**Memory map changes.** The scroller outgrew its 512-byte hole at `$1a00` — the
16-bit stage-row arithmetic took it to 586 bytes — and the choice was to shave
74 bytes off arithmetic that has to be right, or to stop paying bank-0 rent for
code the VIC cannot see. It moved to `$4200`, beside the player, and its state
moved to `$c540` where every other module already keeps its state. Bank 0 is
16 KB and all of it is contended; this **hands back** `$1a00-$1bff` to the
subsystem that will actually need VIC-visible space, which is the character set
and terrain tileset arriving in Slice H.

```
$1a00-$1bff   FREE (was the scroller)
$4000-$4151   player code
$4200-$4449   scroller           guard at $4600
$c520-$c53a   player state
$c540-$c56b   scroll state       guard at $c600
```

---

## Files

```
modified  src/scroll.asm            direction, the two counters, 16-bit stage rows,
                                    rowBack, the fall-through assertion, relocation
modified  src/main.asm              memory map, the scroll diagnostic row
modified  docs/ENGINE_CONTRACT.md   §8a, the world contract
modified  tests/test_p1.py          direction-specific expectations, updated deliberately
modified  tests/test_engine.py      split expectation (§12) + fixture-loaded check
modified  Makefile                  test-slice-a-prime; make test runs three probes
modified  README.md                 it scrolls downward now
new       tests/test_slice_a_prime.py
```

Not committed, per `AGENTS.md`.
