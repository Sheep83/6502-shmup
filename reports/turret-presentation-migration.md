# Terrain Border Fix + Static Turret Presentation Migration

**Repository:** `/Volumes/SSD/dev/C64/6502-shmup` (Mac mini)
**Reference:** `~/Desktop/c64Shooter-main.zip`, read directly out of the
archive — nothing was extracted and nothing was left behind.
**Date:** 2026-09-13
**Status:** automated GREEN. **Manual visual qualification is the user's to
declare, and this report does not declare it.**

Two things were done: the open top and bottom border are black without the
authored terrain changing, and the old game's static background-character
turrets are placed and composed onto the new world contract. No turret firing,
bullets, collision, damage, waves, editor ABI or enemy edge clipping — see §13.

---

## 1. The black border: root cause and fix

### Root cause

The vertical border is held **open** all frame, so the VIC paints `$d020`
nowhere above or below the playfield. What it paints instead is:

| rasters | what the VIC is doing | what comes out |
|---|---|---|
| 0..47 | **idle**: no badline range, fetches `$3fff` | bit pair 00 |
| 48..54 | real matrix lines through the **blank** charset | bit pair 00 |
| 55..247 | real matrix lines through the **terrain** charset | the terrain |
| 248..311 | idle again (and blank charset for YSCROLL=7's row 24) | bit pair 00 |

In multicolour text mode bit pair 00 is `$d021` and nothing else. **The open
border's background and the playfield's background are the same bit pair of the
same register.** The terrain slice set `$d021` once at init to the level's
authored `TERRAIN_BACKGROUND_COLOUR = 12`, which is correct for the playfield —
and turned the open border medium grey with it. Its own §5 predicted exactly
that and flagged it.

So there was never a "force `$d021` black" option that also kept the terrain:
one write at init cannot be right for two regions that share a register. **The
only thing that can separate them is where the beam is.**

### The fix

`$d021` becomes **aperture state**, switched by the two raster splits that
already switch `$d018`, out of the same frame record. No new phase, no new
interrupt, no main-thread involvement, two stores a frame.

```
raster  55   exTop      $d018 -> terrain charset,  $d021 = APERTURE_D021 (12)
raster 248   exBottom   $d018 -> blank charset,    $d021 = BORDER_D021   (0)
```

`APERTURE_D021` is **derived**, not restated: `= TERRAIN_BACKGROUND_COLOUR`,
from `src/level1/stage_config.asm`. A level that authors a different background
cannot disagree with the raster that displays it. `src/terrain.asm` still owns
the *value* and no longer writes the *register* — the same division
`src/hud.asm` lives by, and a test now asserts terrain writes no `$d021`.

### The deadline, and why the store order is what it is

Both stores go out at the split, **`$d018` first**, because its deadline is
earlier: `$d018` must beat the line's first g-access in cycle 15, while `$d021`
only has to beat the first visible playfield pixel, which the main border
flip-flop uncovers in cycle 17.

The poll loop is seven cycles and `63 mod 7 == 0`, so detection lands in cycles
0..6 of the target line. `bne` not taken costs 2 and `sta abs` writes on its
fourth cycle, so:

```
sta $d018    writes in cycles  6..12    deadline 15
stx $d021    writes in cycles 10..16    deadline 17
```

Both values are loaded into A and X **before** the poll — the colour is a
register, not an immediate, precisely so no `lda #` lands between the two
stores. `edgeLate`, `topSplitMin/Max` and `botSplitMin/Max` measured
54..55 / 248..248 / 0 over free runs, unchanged from baseline.

### The YSCROLL = 7 case, which is the whole of the difficulty

`$d018` deliberately splits on line **54** at that one phase, to dodge the
badline on 55 — and it may, because 48..54 are *idle* at YSCROLL=7 and the VIC
renders them from `$3fff` whatever the charset says.

**`$d021` cannot follow it there.** Idle lines are drawn in `$d021`, so a
background store on line 54 would paint line 54 the playfield colour at one
phase in eight and black at the other seven: a one-pixel band flickering at
6.25 Hz, which is the identical artefact the blank guard rows were removed to
kill. The boundary has to be a raster, not a row.

So `exTop` is now two explicit paths:

| YSCROLL | `$d018` | `$d021` |
|---|---|---|
| 0..6 | line 55 | line 55, immediately after it |
| 7 | line 54 | **its own short poll to line 55** |

They are written out rather than merged because the merge point is inside the
deadline: a `cpy/beq` to choose between them after the charset store costs five
cycles, and five cycles is the entire margin. The YSCROLL=7 path is the *safer*
of the two — it reaches line 55 with the whole of line 54 in hand, so its store
lands in cycles 6..12, and writes are not stalled by the badline anyway. It
also keeps the "never spin a whole frame with I set" guard: if 55 has already
gone, it stores at once instead of polling.

`topLanded` was added (one byte) so the split measurement still reports the
line the **charset** store landed on at that phase, where the beam has moved on
by the time the background store happens.

### No main-thread VIC race

`$d021` is written by `src/renderer.asm` and by nothing else. `terrainInit` no
longer writes it; `entry` writes it once before the display is on. Asserted by
source scan and by raster-sampled reads on the running machine.

---

## 2. The old turret data: authoritative sources

Everything below was read out of `~/Desktop/c64Shooter-main.zip`.

| what | where |
|---|---|
| **placement** (count, rows, columns) | `src/generated/level1/stage_turrets.asm` |
| **behaviour, glyph codes, body art** | `src/background_turrets.asm` |
| the world rule | `stage_turrets.asm`'s own generated header |
| the 2x2 cell layout | `installTurretRow`, `background_turrets.asm:437` |
| the body bitmaps | `turretArt` style `TURRET_STATIC_STYLE`, same file |

`stage_turrets.asm` is copied into `src/level1/` **byte for byte**, like the
other three files of the level package, and a test asserts that against the
archive on every run. It emits no bytes at all — `TURRET_TOTAL` plus two
assembler lists.

The previous slice's note that placement is "separate from the terrain map,
reportedly around eight positions in row/column lists" **is correct, and was
re-verified from source rather than trusted.**

---

## 3. Exact count and positions

```
TURRET_TOTAL = 8
turretCols   =  17,  25,  29,   9,  25,  13,  25,  13
turretRows   = 345, 337, 225, 217, 117, 109,  25,   5
```

The editor's own rule, quoted from the generated header:

```
world row = metatileRow * 4 + 1     world col = metatileCol * 4 + 1
```

Every authored row is `≡ 1 (mod 4)` and every authored column is `≡ 1 (mod 4)`;
both are checked in the test and **guarded at assembly time**, because the row
renderer's fast rejection depends on the row rule. Derived metatile rows:

| turret | world row | metatile row | column |
|---:|---:|---:|---:|
| 0 | 345 | 86 | 17 |
| 1 | 337 | 84 | 25 |
| 2 | 225 | 56 | 29 |
| 3 | 217 | 54 | 9 |
| 4 | 117 | 29 | 25 |
| 5 | 109 | 27 | 13 |
| 6 | 25 | 6 | 25 |
| 7 | 5 | 1 | 13 |

The rows are sorted **descending** and at least two apart, which is the old
engine's own placement guard; here the gaps are 8, 112, 8, 100, 8, 84, 20. No
two turrets share a metatile row.

Play starts at the authored **bottom** of the map (`STAGE_START_ROW = 395`), so
turret 0 at row 345 is the first to appear and turret 7 at row 5 the last.

---

## 4. Graphics and colour, recovered

### The body

A turret is a **2x2 block of background characters**, one shared body set for
every turret whatever the count:

```
world row R    col C -> 226 (TL)    col C+1 -> 227 (TR)
world row R+1  col C -> 228 (BL)    col C+1 -> 229 (BR)
```

read out of the old `installTurretRow`, which writes `TURRET_GLYPH_BASE` and
`+1` on the authored row and `+2` and `+3` on the row after it.

The codes **226..229 are kept from the old game**, for the same reason the
terrain glyph base 96 was: a migrated constant that can be diffed against its
source is worth more than a tidier one that cannot. They are outside the
terrain namespace (96..167) by a wide margin, guarded at build time.

The 32 bytes of bitmap are `turretArt` style **4**, the down-facing body — the
one the old shared-glyph renderer used. They are 2-bit multicolour against the
stage palette: the dome is mostly bit pair **11** (colour RAM), the shading is
**01** (`$d022`) and the barrel stub at the bottom centre is **10** (`$d023`).
A test compares them byte for byte against the archive.

### Display / animation frames

The old game has **seven** `turretArt` templates. Six are aiming variants and a
hit flash, retained in that repo "for the functional tests and possible future
use"; the shared-glyph renderer used **style 4 alone** and published it once.
So **the turret body has no glyph animation at all** — the only thing that ever
changed was colour RAM.

### Colour behaviour — recovered, and deliberately not migrated

The old turret's four colour-RAM cells are **pulsed**:

```
turretPulseTable: .byte 1, 2, 7, 2      // white, red, yellow, red
TURRET_PULSE_INTERVAL = 8               // gameplay frames per step
TURRET_HIT_CRAM       = 10 | 8          // light red, while hit-flashing
```
each value OR'd with `$08` to keep the multicolour selector bit, applied by
`pulseTurretColour` to the four cells of every visible, alive turret, with the
vacated cells returned to `TERRAIN_COLOUR_RAM` whenever the body's matrix row
changes.

**This slice holds that pulse at phase 0 and does not animate it.** Phase 0 is
`1 | 8 = 9`, which is exactly `TERRAIN_COLOUR_RAM` — so a turret here renders
*identically to the old turret on the first step of its cycle*, and colour RAM
stays the single level-global value written once at init, untouched.

Why it was not migrated: the pulse is not a lookup, it is a live system. It
needs each visible turret's **current matrix row and column**, tracked every
frame against the *displayed* page's `stageTopRow`, with a restore pass for
cells the body has vacated at each coarse step — per-slot state (`TURRET_CRAM_
ROW`, `TURRET_PAINT_ROW`), a one-frame phase relationship with the page flip
the IRQ adopts at raster 250, and the same machinery the hit flash and the
destruction restore are built on. That is the gameplay-adjacent system this
task says not to build yet, and the brief's "minimal runtime state only" and
"do not build gameplay systems yet" both point at leaving it out.

**It is the one visible difference from the old game in this slice, and it is
called out again in the manual checklist (§14).** It is a small, self-contained
follow-up once destruction exists, because the restore pass it needs is the
same one destruction needs.

### The old visibility logic, for the record

The old engine streamed the authored list through a pool of 8 live glyph slots:
admitted when `SCROLL_ROW` descended to `turretAuthRow + TURRET_STREAM_MARGIN`
(3 coarse rows of lead), evicted when the body left a 25-row keep window,
re-armed from the start when the stage wrapped. `TURRET_VISIBLE` was a separate
**combat** predicate (whole 16-pixel body inside Y 72..231), not a drawing one.

**None of that is migrated, and none of it is needed.** A streaming pool exists
to decide *which* turrets have glyph slots; here every turret's cells are a
pure function of the stage row being generated, so there is nothing to stream,
nothing to admit, nothing to evict and no cursor to rewind at the stage wrap.

---

## 5. Mapping onto `worldProgress` and the stage rows

**The existing terrain/world contract is used unchanged. No second scroll
coordinate system was created.**

```
authored turret world row R, col C
        |
        |  R and R+1 are stage character rows, exactly like terrain rows
        v
renderBackgroundRow reduces (regenTopRow + regenRow) mod STAGE_ROWS
        |
        v
renderTerrainRow    40 terrain codes for that stage row
turretOverlayRow    replaces 0 or 2 of them
        |
        v
the hidden page, published by the frame record as it always was
```

The overlay never asks where the turret is on screen; it asks whether *this*
stage row carries a body half. `worldProgress` / `stageTopRow` therefore need
no new consumer at all — the scroller already decides which stage row each
generated row is, and the answer is the same on both pages.

For the record, the relation a later gameplay system will use is the contract's
own, applied to a turret:

```
stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS
matrix row  == (stage row - stageTopRow) mod STAGE_ROWS      0..24 = on screen
```

Turret 0 (row 345) enters at matrix row 0 at `worldProgress = 50` and reaches
matrix row 24 twenty-four coarse steps later. Checked in the test.

### The fast rejection, which the editor's rule makes free

A turret body occupies sub-rows **1 and 2** of a single metatile row and can
never straddle a metatile boundary, because every authored row is
`metatileRow * 4 + 1`. So:

```
sub-row 0 or 3  ->  no turret is possible. HALF the generated rows leave in
                    fifteen cycles without touching a table.
sub-row 1 or 2  ->  one lookup, indexed by metatile row.
```

The rule is **guarded, not assumed**: a level that authors a row somewhere else
fails the build rather than silently dropping a turret.

---

## 6. The hidden-page overlay design

```
renderRow
  jsr renderTerrainRow     40 codes, from the map. Knows nothing about turrets.
  jmp turretOverlayRow     0 or 2 of them replaced.
```

Composition happens **during hidden-page generation**, so a page is coherent
before it is ever published, and nothing patches the visible screen from
gameplay code. `scrollInit` builds both pages through the same `renderRow`, so
a turret inside the boot aperture is composed into the very first frame.

`turretOverlayRow` writes **two** cells, never four: a body spans two stage
rows, and each row is generated on its own call.

`turretAtMetaRow` is one byte per metatile row of the stage — the turret that
lives there, or `TURRET_NONE = $ff` — built by the assembler from the authored
list. The run time never walks the list at all, and the inner path does not
depend on the turret **count**:

```
lda rrStageLo / and #3 / sec / sbc #1 / cmp #2 / bcs out    sub-row 0 or 3
lda rrStageHi / lsr / lda rrStageLo / ror / lsr / tax       metatileRow
lda turretAtMetaRow,x / bmi out / tax                       which turret
lda turretAlive,x / beq out                                 alive?
ldy turretCol,x / <TL or BL> / sta (scrPtr),y / adc #1 / iny / sta (scrPtr),y
```

**The table replaced a linear scan on measured evidence**, not on taste — see
§10. It costs `STAGE_METATILE_ROWS` bytes (105 for level 1) outside VIC bank 0,
which is the same trade `src/terrain.asm` already makes twice for the
transposed sub-row tables and the metatile-ID cache.

### A build-time trap worth recording

The first version built the table with a `.function` that compared
`turretRows.get(t) / METATILE_H == m`. **KickAssembler's `/` is floating
point**: `345 / 4` is `86.25`, never equal to any `m`, so the table came out
entirely `TURRET_NONE` — a silently empty table, a build with no errors and
eight invisible turrets. The value survived being emitted by `.fill` only
because `.fill` truncates to a byte on the way out, which is why the companion
`turretMetaRow` table looked right while the lookup did not. Every division of
an authored row in `src/turrets.asm` is now `floor()`ed explicitly, **including
the ones inside the guards** — the "no two turrets share a metatile row" guard
had the same bug and would have passed rows 5 and 6 as distinct.

---

## 7. The underlying-terrain restoration contract

**The authored terrain is never modified, and turrets are never baked into it.**

```
base terrain  +  turret overlay  =  generated page

alive -> terrain + turret
dead  -> terrain only
```

One byte per turret, `turretAlive`, is the whole of "put the terrain back".
Because the overlay is applied *on top of* a freshly decoded row, clearing the
byte makes the next regeneration of either page produce the underlying terrain
with **nothing to repair**: no cached ground codes, no second copy of the map,
no state that can go stale. The old engine needed `turretGroundCodes`, a
four-code cache per slot filled at admission time, precisely because its turret
cells were poked into a live screen it could not regenerate.

A future destruction system adds only the *immediate* half: clear the byte,
then poke that turret's four cells of the **displayed** page once, at a safe
point in the frame, with the codes `renderTerrainRow` would have written. Those
codes are recoverable at any time because the decode is a pure function of the
stage row.

**Nothing in this slice ever clears a byte.** `turretInit` sets all eight and
they stay set. The contract is the deliverable, not a gameplay system. The test
proves it works by poking one byte to zero and watching the terrain come back,
then poking it to one and watching the body come back.

---

## 8. Production files changed

| file | change |
|---|---|
| `src/turrets.asm` | **new** — glyph codes, body bitmaps, the metatile-row lookup, `turretAlive`, `turretInit`, `turretOverlayRow` |
| `src/level1/stage_turrets.asm` | **new**, copied verbatim from the archive |
| `src/renderer.asm` | `exTop` split into the two `$d021` paths; `exBottom` writes `$d021`; new `topLanded` byte |
| `src/main.asm` | `stage_config.asm` imported first; `APERTURE_D021` / `BORDER_D021`; `turretInit` in `entry`; `turrets.asm` imported; bank-0 map comment refreshed |
| `src/terrain.asm` | stops writing `$d021` and stops importing `stage_config.asm` (both moved to `main.asm`) |
| `src/scroll.asm` | `renderBackgroundRow` composes the overlay after the terrain |
| `docs/ENGINE_CONTRACT.md` | §4 and §8 for the aperture background, §9 for `$d021`'s new owner, new §8c for the world overlay |
| `Makefile` | `test-turrets`, and `test_turrets.py` in `make test` |

Memory added: `$0f10-$0f2f` body bitmaps (inside the terrain charset window,
the only turret bytes the VIC ever reads), `$6d00-$6d78` tables,
`$6e00-$6e08` state, `$6e40-$6e86` code — all three outside VIC bank 0, all
three with growth guards.

---

## 9. Focused tests

**`tests/test_turrets.py`** — new, in `make test`, with `make test-turrets`.
Seven sections, 114 checks, one VICE launched and reaped:

- the authored placement file is **byte-identical** to the archive's; the body
  bitmaps are byte-identical to `turretArt` style 4; the glyph base, span and
  style are read *out of the old engine* rather than remembered; the 2x2 code
  layout is read out of the old `installTurretRow`;
- the count and every row and column match the old reference; the editor's
  `metatileRow*4+1` / `metatileCol*4+1` rules hold; bodies fit the stage and
  the 40 columns; sub-rows are only ever 1 and 2; no two turrets share a
  metatile row; the old repo's own descending-and-2-apart rule holds;
- world row → generated cell: TL/TR on `R`, BL/BR on `R+1`, nothing on `R-1`
  or `R+2`; exactly 16 of the 420 stage rows carry a body, each writing exactly
  two cells; the `worldProgress` → `stageTopRow` → matrix-row walk for a real
  turret, including the steps either side of the aperture;
- the glyph codes clear the terrain namespace, the bitmaps sit inside the
  charset window and clear the terrain bitmaps, and every turret symbol except
  the bitmaps lives outside VIC bank 0;
- **zero sprite/object resources**: `src/turrets.asm` writes no VIC register
  and does not *name* one, touches no colour RAM, and mentions none of
  `objectAlloc/Activate/Free`, `logActive`, `logCount`, `logY/X/Ptr/Col`,
  `sortedIDs`, `schedule`, `batch`, `HW_`, `MUX_`, `SPRITE`, `spritePtr`; the
  overlay is called from `renderBackgroundRow` and from nowhere else; and on
  the running machine **no sprite pointer on either page resolves into the
  turret bitmaps**;
- on the 6502: the derived tables match the authored lists; the body bitmaps
  are resident; three turrets across the map compose the right two cells in the
  right columns and leave the other 38 untouched; the rows either side are pure
  terrain; **page A and page B compose identically**; clearing one alive byte
  regenerates pure terrain while every other turret is unaffected, and setting
  it brings the body straight back; colour RAM is still the level's single
  value everywhere; the only non-terrain codes on either page are the four
  body codes;
- **the black border, sampled by raster**: `$d021` read at the entry of
  `exHud` (4), `exHandoff` (40), `exTop` (53), `exBottom` (243) and `exFrame`
  (250) — black, black, black, **12**, black. Plus that the background store
  follows the charset store at both splits and that the YSCROLL=7 path has its
  own poll to 55.

The engine's own instrumentation (`topSplitMin/Max`, `botSplitMin/Max`,
`edgeLate`, `gameOverrun`, `publishSkip`, `scrollLate`) is read **first, on a
clean machine**, before the row harness runs. That ordering is not cosmetic:
the harness hijacks the PC into `renderRow` about thirty times and leaves
`regenRow` mid-page, which is exactly the interference that makes a scroller
report a late back page. Reading those counters afterwards produced
`publishSkip 1 / scrollLate 1` on the first draft of this test, and they were
an artefact of the test, not of the change — the same trap the terrain slice
and P4 both paid for.

**`tests/turret_model.py`** — new. The authored placement parsed from the level
package and the overlay restated independently, shared by `test_turrets.py` and
`test_slice_a_prime.py`.

**`tests/old_repo.py`** — new. Reads the old repo **out of the zip**, with no
extraction and nothing to clean up.

**`tests/test_terrain.py`** — updated:
- its provenance section pointed at `/Users/brianmorrice/Dev/C64 ASM/
  shooter_test`, **which does not exist on this machine**, so it was reporting
  one "the reference checkout is present" failure and checking nothing. It now
  reads the archive and really does compare the three level files byte for
  byte;
- `$d021` was read at an arbitrary monitor stop, which is meaningless now that
  it is aperture state; it is sampled by raster instead, at `exTop` (black) and
  `exBottom` (the level's background);
- the ownership check now asserts terrain writes only `$d016/$d022/$d023` and
  **no** `$d021`;
- "both pages hold only terrain glyph codes" now admits the four turret body
  codes, which are legal page content.

**`tests/test_slice_a_prime.py`** — updated: its row identity compares all
forty codes of every row against the level model, so the rows carrying a turret
body needed the overlay in the expectation. It now composes
`turret_model.apply()` over the terrain model — strictly stronger than before,
since it checks the turret cells too.

---

## 10. Performance

Cycle-exact, VICE monitor CPU stopwatch between PC-verified breakpoints.
"min" is the pure figure — a sample with no raster IRQ inside it; median and
max include whatever interrupts landed.

### `renderRow`: one stage row into the back page

| stage row | what | min | med | max |
|---|---|---:|---:|---:|
| 200 | sub-row 0, no turret | **942** | 1,028 | 1,695 |
| 201 | sub-row 1, no turret in this metatile row | **968** | 1,075 | 1,786 |
| 202 | sub-row 2, no turret in this metatile row | **968** | 1,099 | 1,798 |
| 203 | sub-row 3, no turret | **942** | 1,033 | 1,751 |
| 116 | sub-row 0, turret's metatile row | **942** | 1,047 | 1,938 |
| 117 | sub-row 1, **turret top half** | **1,006** | 1,135 | 1,838 |
| 118 | sub-row 2, **turret bottom half** | **1,008** | 1,137 | 1,825 |
| 119 | sub-row 3, turret's metatile row | **942** | 1,043 | 1,764 |

So the overlay costs **15 cycles** on half of all rows (sub-rows 0 and 3),
**26 cycles** on a sub-row 1 or 2 with no turret, and **64 cycles** on a row
that actually carries a body half.

**The lookup table was chosen on this measurement.** With the first version's
eight-entry linear scan the same rows measured **1,048** instead of 968 — 106
cycles on every second generated row, about 210 a frame. The table cut that to
26 and made the inner path independent of the turret count, for 105 bytes
outside bank 0 and shorter code.

### `regenTick`: one working frame, `ROWS_PER_TICK = 4`

| | min | med | max |
|---|---:|---:|---:|
| four rows, no turret in any of them | **4,328** | 4,505 | 5,759 |
| four rows, **both halves of a turret body** | **4,443** | 4,861 | 5,939 |
| idle tick (page already finished) | 15 | 15 | 431 |

**The worst terrain+turret regeneration frame costs 115 cycles more than the
same four rows without a turret** — 0.6% of a PAL frame's 19,656 — and a tick
can carry at most two body halves, because a body occupies sub-rows 1 and 2 of
one metatile row.

`turretInit` costs **89 cycles**, once at boot.

### Main-thread health, production free runs

Same harness, same 20-second warp run, **no PC hijacking of any kind**:

| build | frames | gameSpanMax | spanOver | gameOverrun | publishSkip | scrollLate | edgeLate |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline (`3afded9`) | 31,690 | 152 | 0 | **0** | **0** | **0** | **0** |
| this slice, run 1 | 31,517 | 156 | 0 | **0** | **0** | **0** | **0** |
| this slice, run 2 | 35,141 | 156 | 0 | **0** | **0** | **0** | **0** |

Worst main-thread span goes from **152 to 156 raster lines** of the PAL frame's
312 — four lines, about 250 cycles, which is the overlay on a turret-carrying
tick. `gameOverrun`, `publishSkip`, `scrollLate` and `edgeLate` are **zero on
both builds**, and the aperture splits still land on 54..55 and 248..248.

One number is recorded because it was wrong and is worth not repeating: the
first measurement of this slice reported `gameOverrun 1`. It was taken at the
end of the cycle-measurement script, after ~130 PC hijacks into `renderRow` and
`regenTick`. Re-measured on a clean machine it is zero, twice, and the baseline
measured the same way is zero too. **Mux-capacity studies were not re-run**, as
instructed.

---

## 11. `make test`

**ALL PASS — 630 checks, nine suites, zero failures.**

```
test_engine  test_slice_a  test_slice_a_prime  test_slice_b
test_slice_c  test_slice_d  test_terrain  test_turrets  test_batch_window --fast
```

Nine VICE instances launched and nine reaped; `pgrep -fl x64sc` clear
afterwards. 114 of the 630 checks are the new turret/border suite.

Two figures from inside the gate corroborate §10 on a path that is not this
slice's own harness:

- `test_slice_a`: **main-thread span, production: 114 lines, 0 missed frames,
  0 publishSkip**;
- `test_slice_a_prime`: both aperture splits still `[54, 55]` and
  `[248, 248]`, no split ever late, the scroller never found its back page
  unfinished.

Per the task's budget, **P0–P5, `test-engine-full` and `test-renderer-full`
were not run.** Nothing here invalidates one of those qualified invariants: the
executor, the publication model, the slot mapping and the batch geometry are
untouched; the aperture still switches the same two charset windows at the same
two rasters with the page bits preserved, and the only thing added inside a
phase is one four-cycle store on each side.

---

## 12. Pre-existing issues

**The documented `test_slice_d` population-12 ladder flake did not fire.** The
suite passed, and its standing ADVISORY printed as it always does — populations
[12, 16] overrun the frame *with collision switched off*, a pre-existing
main-thread limit that `docs/ENGINE_CONTRACT.md` §10 already owns. No rerun was
needed.

`test_slice_a`'s RING-SLOW observation also printed as it always does — 255
lines, 158 missed frames, 148 publishSkip on that fixture — and is the same
known deferred performance issue in §10. It is reported, deliberately not
asserted, and the production path in the same run is 114 lines with zero of
both.

**A pre-existing test defect was found and fixed**, and it is worth separating
from the flake: `test_terrain.py`'s provenance section pointed at a checkout
path that does not exist on this machine, so "the level package is the authored
original" had not actually been checked since development moved here. It is now
checked against `~/Desktop/c64Shooter-main.zip` and passes.

The known whole-sprite enemy pop at the gameplay Y bounds is **untouched**, as
instructed, and is not a regression from this slice.

---

## 13. What was NOT migrated

Explicitly, and by instruction:

- **turret firing** — no `TURRET_FIRE_INTERVAL`, no `TURRET_SHOTS_FIRED`, no
  shot emission of any kind;
- **turret bullets** — none;
- **turret collision** — `traceTurretCannon` was not migrated; the player's
  hitscan cannot see a turret and `src/collision.asm` is untouched;
- **turret damage and death** — no `TURRET_HEALTH`, no `TURRET_HIT_TIMER`, no
  hit flash, no destruction, no `turretDestroyedBits`. `turretAlive` exists and
  **nothing ever clears it**;
- **the colour pulse** — recovered and documented in §4, held at phase 0;
- **waves** — `stage_waves.asm` was not copied;
- **the editor ABI** — unchanged;
- **enemy edge clipping** — untouched.

`src/turrets.asm` consumes **no** HW0/HW1, no HW2–HW7, no logical sprite pool
slot, no mux batch and no sprite bitmap storage, and the sprite renderer has no
knowledge that turrets exist. Asserted by source scan and on the machine.

---

## 14. Manual visual checklist

**Please run this yourself. This report does not declare visual GREEN.**

```sh
cd /Volumes/SSD/dev/C64/6502-shmup
make run JOY2=<your device>      # JOY2=1 numpad (default), 4 = a real stick
```

| # | Look for | Expected |
|---|---|---|
| 1 | **the open top border** | **BLACK** behind the HUD sprites, not grey |
| 2 | **the open bottom border** | **BLACK**, all the way down |
| 3 | the edge between border and terrain | a clean horizontal line that does **not** move, breathe or flicker as the terrain scrolls — it is raster 55 at every fine-scroll phase |
| 4 | terrain colours | otherwise **unchanged**: grey ground, white, light grey, highlight |
| 5 | the HUD | unchanged — lives, heat gauge, score, status, over black now |
| 6 | smooth terrain | no seam, no tear, no hitch at coarse steps or page flips |
| 7 | **turret graphics** | a domed 16x16 emplacement with a short barrel stub pointing **down**, drawn in the terrain's own palette |
| 8 | **turret positions** | where the old game put them. Eight in the level; the first appears about 50 coarse rows in |
| 9 | turrets entering and leaving | they enter at the **top** and scroll down with the terrain at exactly its speed — never sliding, lagging or jittering against it |
| 10 | around a turret row | no seam, no corruption, no stray character either side of the body |
| 11 | the two halves of a body | joined — no gap or shear between the top and bottom rows as it crosses the aperture edges |
| 12 | player and enemies | stable; firing, heat and deaths unchanged |
| 13 | a full minute of play | no new periodic hitch |

**One difference from the old game you should expect to see, and it is
deliberate:** the old turret's dome **pulsed** white → red → yellow → red.
Here it is held at the first step of that cycle — white — because the pulse is
a live per-frame colour-RAM system entangled with the hit flash and
destruction, which this slice is explicitly not building (§4). If you want the
pulse back before turret combat exists, say so: it is a small, self-contained
follow-up.

The already-known whole-sprite enemy pop at the Y bounds is **not** a
regression here.

---

## 15. VICE / input / process hygiene

- `pgrep -fl x64sc` was run before every automated session and before every
  measurement run; all reported clear, and no manually opened VICE existed at
  any point.
- Every emulator was launched by a harness with `-console` under a **retained
  PID** and reaped by that exact PID. Every run printed its own
  `launched and reaped` line.
- **No `pkill` was used at any point**, no process was terminated by name
  matching, and no manual VICE was ever signalled.
- **No `open -a`.** No automated run opened a window or took keyboard focus.
- No joystick, keyset or controller preference was created or modified;
  nothing was written to the user's VICE configuration. The automated launches
  keep the qualified `-default +saveres` pairing with both control ports
  detached.
- The old repo was read **directly out of the zip**. Nothing was extracted
  under `/tmp` by the tests, and the one exploratory extraction made while
  reading the archive was removed.
- Transient measurement scripts lived in the session scratchpad, outside the
  repository, and are not part of it.

---

## 16. Disk

```
du -sh build/   ->   80K     main.sym, main.vs, shmup.prg, nothing else
du -sh .        ->   2.8M
```

No per-run artifacts accumulate under `build/`; the build writes fixed outputs.

---

*The open border is black, the authored terrain is unchanged, and the old
game's eight static turrets are composed into the generated page from the
authored placement layer, as background characters, with the terrain underneath
recoverable and not one sprite or mux resource spent. Firing, bullets,
collision, damage and waves are not started.*
