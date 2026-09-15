# Blue player ship integration and banking animation

**Repository:** `/Volumes/SSD/dev/C64/6502-shmup`
**Sheet:** `src/mnt/data/Shooter_SpriteSheet_C64(1).png`

---

## Status

The player is now the blue interceptor from the sheet, drawn as **one
multicolour sprite on HW0**, banking left/neutral/right with a **cycling engine
flame**.

| | |
|---|---|
| focused proof | **ALL PASS** — `tests/test_player_ship.py` |
| production gate | **ALL PASS** — 5 suites, 95 checks, exit 0 |
| VICE | 5 launched, 5 reaped, `pgrep -fl x64sc` clear |
| health counters | `gameOverrun`, `publishSkip`, `schedBuildDefer`, `scrollLate`, `edgeLate`, `statPageMismatch`, `statPtrMismatch` all **0** |
| movement / collision / weapon / director / terrain | **untouched** |
| **manual visual judgement** | **yours** — §9. This report does not claim it looks or feels right |

---

## 1. Phase 1 — and a correction

The brief expected *"crisp hires directional/banking variants … may use two
overlaid sprites"*, flagged as an observation to verify. It does not hold.

**I also got the ship wrong on the first pass, and the reason is worth
recording**, because it is the kind of mistake that reads as finished work.

### The palette trap

The sheet is a palette (mode `P`) image whose palette contains **two black
entries**:

| index | RGB | meaning |
|---|---|---|
| 0 | `(0,0,0)` | **opaque black — the outline colour the art is drawn with** |
| 255 | `(0,0,0)` | the **transparency key** |

Opening it with `.convert("RGB")` merges the two. Every black outline pixel
then looks like background. Under that reading the region at x39–76 appeared to
be sparse debris — I classified it as "explosion / particle frames" and moved
on — and the only ship-like cells left were the blue craft at x129–165, which
genuinely have no black outline. So I integrated a real ship from the sheet; it
was simply not the one intended.

The correction came from your screenshot: it showed a **dark grey background
distinct from black**, which is only possible if black is a real colour and the
transparent index is being rendered separately. The tool now reads **palette
indices**, never RGB, and refuses any index outside the expected four.

### What the artwork actually is

The craft is the **blue interceptor at x39–76, rows 0–49** — a clean 3×3 grid
of 12×16 cells on a uniform pitch, unlike the rest of the sheet:

| | |
|---|---|
| **rows** | **banking.** Band A (rows 0–15) is mirror-symmetric **to the pixel** (mismatch 0/94); bands B and C lean progressively |
| **columns** | **the engine.** The three cells of a band differ **only in their bottom two rows** — flame full, small, out |
| colours | **black outline + medium blue hull + white highlight** — exactly 3 + transparent |

**Lean direction:** in both banked bands the **right wingtip rides high** (x8,
upper rows) while the **left drops** (x0–1, lower rows) — a left roll. So bands
B/C are bank-left and the right-hand frames are their mirrors. The centroid is
useless here (+0.13, −0.12, non-monotonic) because the craft *rotates* rather
than translating, which is itself confirmation that these are banks and not
sideways-shifted copies.

### Hires or multicolour

Three substantial colours in a 12 px cell. A hires sprite carries **one**
colour; two overlaid carry two, not three — sprites do not blend, the
higher-priority one simply wins. **The two-hires-layer reading cannot reproduce
this artwork.**

Twelve pixels with three colours is exactly **one C64 multicolour sprite**: 12
double-width pixels = 24 screen px, pairs 01/10/11 plus transparent. Checks
that could have falsified it and did not: the art is not 24 px with doubled
pixels (118/104 pair mismatches on both alignments), and the sibling sheets
(256×128, 188×65) have the same ~12 px cell width, so it is not a halved
conversion of a wider master.

**Palette note:** the colours are NES values — `(0,120,248)`, `(252,252,252)` —
not C64 entries, so they map to nearest C64 pens.

### Composition

**One layer.** Five bank states × three engine frames = **15 frames**, plus one
blank block for HW1.

---

## 2. What was built

### Sprite data — 16 blocks at `$2000`, pointers `$80`–`$8f`

Bank-major, `frame = bank * 3 + engine`:

| pointer | address | frame |
|---|---|---|
| `$80`–`$82` | `$2000` | bank **hard left**, engine 0/1/2 |
| `$83`–`$85` | `$20c0` | bank left |
| `$86`–`$88` | `$2180` | **neutral** |
| `$89`–`$8b` | `$2240` | bank right |
| `$8c`–`$8e` | `$2300` | bank **hard right** |
| `$8f` | `$23c0` | blank — HW1's bitmap |

16 of 52 free blocks, 64-byte aligned, inside a run the map already marked
free, proved disjoint from every other region the VIC reads. Bank-major
ordering is what lets a bank index and an engine phase become a pointer with a
shift and two adds — no table.

### Colours

| register | value | role |
|---|---|---|
| `$d027` (HW0) | 14 light blue | per-sprite: the hull |
| `$d025` shared | 0 black | pair 01 — the outline |
| `$d026` shared | 1 white | pair 11 — highlights |
| muzzle flash | 2 red | replaces `$d027` for the flash window |

`$d025/$d026` are global, the player is the only multicolour sprite, so they
are **static** — written once in `playerInit`. The renderer's own comment had
reserved them for exactly this: *"If gameplay ever enables multicolour for a
slot, they join this list on the same day."*

### `$d01c`

`PLAYER_D01C = %00000001` — HW0 multicolour, **every HUD and gameplay slot
still hires**. Written in **both** raster phases, because the craft is drawn
through the HUD phase *and* the gameplay phase; a mode that changed at the
handoff would show as the ship switching resolution part-way down the screen.
An assembly-time guard refuses any value setting a bit outside
`PLAYER_SLOT_MASK`, so the mux cannot be switched to multicolour by accident.

### HW1

The craft is one sprite, so HW1 has no bitmap for the first time. It is kept
**enabled, co-located and blank** rather than switched off, because every
invariant naming the player names both slots — `PLAYER_SLOT_MASK`, the `$d015`
composition, the `$d010` pair, the renderer's reservation, and the production
suite's `plyPresEnable ∈ {0, 0b11}`. It stays free for a muzzle-flash or detail
overlay later.

### Banking signal — there is no horizontal velocity

`player.asm` states it outright: *"ONE PIXEL PER FRAME PER AXIS with no
velocity state"*, *"no acceleration and no momentum"*. The brief preferred real
velocity "because momentum should naturally keep the craft banked" — it does
not exist, so the stick is the only horizontal signal there is.

`playerBankTick` walks an **unsigned** bank index (0 = hard left, 2 = level,
4 = hard right — which is also the frame's row in the grid) **one stage every 5
frames** toward where the stick points:

- full lean in ≈10 frames (0.2 s), and back out over the same
- **the dead-band is the timer, not a threshold** — a stick centred for a frame
  or two during a direction change is simply not noticed
- left wins a simultaneous left+right, which a worn stick produces

### Engine flame

Cycles 0→1→2 **every 4 frames** on its own clock, independent of the lean: the
exhaust flickers whether or not the craft is turning, so the two cadences do
not share a timer. ~12-frame loop — a flicker, not a strobe.

`playerBankTick` reads `joyState` and writes `plyBank`, `plyBankTimer`,
`plyEngine`, `plyEngineTimer`. **Nothing else** — no position, no velocity, no
clamp, no weapon. Deleting it would change how the ship looks and nothing about
how it flies.

### Precedence

Orthogonal by construction, which makes precedence a property rather than a
rule to remember:

| state | what it chooses |
|---|---|
| banking + engine | the **pointer** |
| muzzle flash | the **colour** |
| invulnerability blink | the **enable** |

Banking cannot override the flash or the blink because it does not write either
byte. All combinations are asserted.

---

## 3. The conversion tool

`tools/gen_player_ship.py` reads the PNG **by palette index**, extracts the
nine source cells, mirrors six, maps to multicolour bit pairs, and emits
`src/player_art.asm` (15 frames).

- **No build or runtime dependency** — the assembler reads the checked-in
  `.asm`; `make build` runs no Python. `--check` fails if the file has drifted
  from the PNG, and the focused test runs it every pass.
- **Registration:** every cell is the same 12-wide box, so the artist's own
  placement inside it is used unchanged — x offset 0 for all fifteen, 16 rows
  centred in 21. No centroid guessing; that would only move frames the sheet
  already lines up. (The earlier, wrong ship had ragged 10–12 px cells and
  *did* need centroid alignment — a good sign in hindsight that it was not the
  intended grid.)
- **Verification:** lit-pair counts match the source census exactly
  (87/84/83, 99/95/93, 100/96/94), mirrors verified pixel-exact against their
  originals on the machine, and engine frames verified to differ only below
  row 14.

---

## 4. Files changed

| file | change |
|---|---|
| `src/player.asm` | allocation, multicolour colours, `PLAYER_D01C`, bank + engine state and tick, `playerEmit` frame arithmetic, `$d025/$d026` at init, old two-layer split removed, state block moved to `$c51a` |
| `src/renderer.asm` | `$d01c` written as `PLAYER_D01C` in `exHud` and `exHandoff` (2 cycles each); three stale comments corrected |
| `src/enemy.asm` | **`ENEMY_SPRITES` pinned to `$3640`**; state guard renamed to the new boundary |
| `src/scroll.asm` | segment moved `$4200` → `$4300` (address only; code untouched) |
| `src/main.asm` | VIC0 memory map comment |
| `Makefile` | `test-player-ship`, added to `make test` |
| `tests/test_production.py` | movement check made deterministic — see §5 |
| `src/player_art.asm`, `tools/gen_player_ship.py`, `tests/test_player_ship.py` | **new** |

### Two pre-existing defects this task exposed

**1. A derived address that moved an unrelated asset.** `ENEMY_SPRITES` was
`PLAYER_SPRITES_END` — self-maintaining while the player sat below it, and it
silently dragged the enemy bitmap from `$3640` to `$2180` the moment the
player's art moved. The build was clean and nothing complained. Now pinned with
its own guard. An address that follows an unrelated asset around is not a
memory map.

**2. The scroller moved one page, and why that was the right call.** Fifteen
frames' worth of pointer arithmetic and presentation state pushed the player
code 13 bytes past its 512-byte home at `$4000`. Contorting the code to fit an
arbitrary boundary was the wrong trade; so was parking the player module in an
odd corner. The scroller's load address is arbitrary, nothing outside the file
names it, it is position-independent and sits well outside VIC bank 0, so it
moved to `$4300` — **its code is unchanged** and it still has 240 bytes of
slack before the weapon. The brief's "do not move unrelated memory" is in the
VIC-memory section and concerns screen pages, charsets and sprite assets; none
of those moved.

Untouched: movement, input, collision, hitbox, invulnerability timing, weapon,
encounter director, terrain, raster splits, HUD ownership, the gameplay mux,
runtime vertical clipping.

### Memory

```
$2000-$23ff  player bitmaps (16 x 64)      $3640-$367f  enemy bitmap (pinned)
$4000-$420c  player code                   $4300-$4510  scroller
$c51a-$c53b  player state                  $c517-$c519  enemy state
```

---

## 5. Qualification

### Focused proof — `tests/test_player_ship.py`, ALL PASS

One VICE. Banking and the flame depend on frame cadence, so they are watched
through the **real frame loop**; precedence calls `playerEmit` directly because
it is pure presentation with no cadence of its own.

Proves: the art still matches the PNG; 16 blocks aligned, in range, disjoint;
all 15 frames resident; **engine frames differ only in the exhaust rows, never
the hull**; **left banks are exact horizontal mirrors of the right**; `$d01c`
correct and identical however the frame is sampled; both shared registers
correct; the lean reaches hard left and hard right through its intermediate
stage, one stage at a time, and rolls back; the pointer always names the
current bank **and** engine frame; both cadences are *held* for several frames;
and flash/blink/banking precedence in all combinations.

### Four measurement defects found in my own tests, and fixed

Recorded because each one passed or failed for the wrong reason first:

1. **`$d025/$d026` read `$fe/$f1`.** That is **correct hardware** — VIC colour
   registers implement four bits and read back with the top four set. Now
   masked, which is reading the register properly rather than loosening the
   check.
2. **The cadence check passed vacuously.** It counted transitions, found one
   inside the window, and compared an empty list. Rewritten to measure how long
   each frame is *held*.
3. **Truncation at both ends.** A run clipped by the capture start reads short.
   The bank check drops its truncated **last** run; the engine list excludes
   the last by construction and so drops its truncated **first**. Stated
   explicitly in both places rather than left as a coincidence.
4. **`test_production.py`'s movement check was flaky — and pre-existing.** It
   read `x0` at an arbitrary stop and `x1` at a `gameFrame` entry, bracketing
   four or five `playerTick` runs at random: the **same build** measured
   `dx 5` then `dx 4`. A 60-frame probe proved movement is exactly 1 px/frame
   and `joyHold` holds throughout, so this was never the game. Fixed twice:
   first by sampling both ends at the same point in the frame, then — when a
   rarer `(1 frame, 0 px)` interval appeared — by making each sample
   **coherent**, reading the frame counter either side of `plyX` and retrying
   if they differ. `step_n` guarantees *distinct* frames, not *consecutive*
   ones, and `x` returns on a prompt echo, so an incoherent pair can report
   `plyX` from before a move with the frame number from after it. The check is
   now stricter than before (it asserts the 1 px/frame rate on every interval)
   and stable 4/4.

### Production gate — `make test`, ALL PASS

**5 suites, 95 checks, exit 0. 5 VICE launched, 5 reaped, `pgrep` clear.**

```
test_boot.py                ALL PASS
test_production.py          ALL PASS
test_turret_regression.py   ALL PASS
test_encounter_director.py  ALL PASS
test_player_ship.py         ALL PASS
```

**Why the full gate rather than a smoke test**, since the brief asks the choice
to be explained: this writes `$d01c` — a **global** VIC register — in both
raster phases, which the HUD and the gameplay multiplexer both live under. It
also moved the player state block, moved a segment, and changed a constant
another module derived from. That is shared state by any reading, and the
focused test alone would not catch a HUD or mux regression.

**Renderer health:** every counter zero in both the focused run and the gate.
No page/pointer mismatch, no publication skip, no missed frame, no late split.
The two extra `lda #imm` (2 cycles each) land in `exHud` at raster 4 and
`exHandoff` at raster 40, both with ample margin.

**Gate wall-clock 9:19 is environmental.** CPU was 105.7 s user + 13.5 s system
at **21% utilisation** — almost entirely idle on VICE monitor round-trips, the
same variance documented in `reports/production-test-suite-rewrite.md` §5.
Nothing here adds per-frame work beyond one `jsr` whose common path is a
compare and a `dec`.

---

## 6. Deliberate omissions

- **The muzzle-flash bitmap is gone**; the flash is the colour change alone.
  The old ship had a second bitmap with muzzle blocks at the nose. With fifteen
  banking/engine frames that would mean fifteen more blocks of muzzle art the
  sheet does not contain and this task may not invent. Flashing the per-sprite
  colour reddens the **hull** while the black outline and white highlights
  hold. `$23c0` is where a real overlay goes when there is art for one.
- **The first, wrong ship** (blue band-B craft at x129–165) is fully removed —
  no leftover blocks, pointers or colours.
- **No enemy or orb art touched**; no palette-swap variants integrated.

---

## 7. Disk

```
du -sh build/   ->   84K
du -sh .        ->   4.3M
```

No per-run artefacts under `build/`; transient logs and probes lived in `/tmp`
and are deleted.

---

## 8. Git

```
 M Makefile
 M src/enemy.asm
 M src/main.asm
 M src/player.asm
 M src/renderer.asm
 M src/scroll.asm
 M tests/test_production.py
?? reports/player-blue-ship-integration.md
?? src/mnt/
?? src/player_art.asm
?? tests/test_player_ship.py
?? tools/
```

**Nothing was committed, pushed or staged.**

`src/mnt/` is the sprite sheet, untracked and **already present before this
task** — it mirrors the `/mnt/data/` path in the brief, neither of whose paths
(nor the brief's repo path) exist on this machine; it is byte-identical to the
copy in `~/Desktop/The Game Creator's Pack/Graphic Pack/`. Left as found. The
tool's source path therefore points at an untracked file — worth committing the
sheet if the tool is to stay reproducible. `tools/` is untracked because the
directory did not exist before.

---

## 9. Manual visual qualification — yours

**Automated tests cannot decide whether the banking looks and feels right, and
this report does not claim it does.**

```sh
cd /Volumes/SSD/dev/C64/6502-shmup
make run
```

| # | Look for | Expected |
|---|---|---|
| 1 | **the ship** | the blue interceptor: black outline, blue hull, white highlights, nose bar at the top |
| 2 | **the engine** | the exhaust flame pulsing continuously at the base, even when flying straight |
| 3 | **hold left / right** | rolls into the bank over ~10 frames through one intermediate frame, not a snap |
| 4 | **release** | rolls back out through the same intermediate frame to level |
| 5 | **the direction is right** | banking LEFT when you move left. If it looks inverted, that is one constant — say so and I will swap the frame order |
| 6 | **cadence** | deliberate; waggling the stick should not flicker the ship |
| 7 | **diagonals** | up-left banks left and stays banked |
| 8 | **registration** | the craft does not jump sideways as it changes frame |
| 9 | **firing** | the hull flashes red; the ship stays on its banked frame and keeps animating |
| 10 | **taking a hit** | the blink still blinks, and the ship returns solid on the right frame |
| 11 | **screen edges** | the 9-bit X crossing is unchanged — no wrap or tear |
| 12 | **enemies, turrets, HUD, terrain** | unchanged, and still hires |
| 13 | **a minute of play** | no flicker or corruption attributable to the new sprite |

Checks 3, 5, 6 and 8 are the ones most likely to need tuning.
`PLAYER_BANK_RATE` (lean) and `PLAYER_ENGINE_RATE` (flame) in
`src/player.asm` are the two numbers — lower is snappier. **Check 5 is worth a
deliberate look:** the sheet draws only one bank direction and I read it as a
left roll from the wingtip geometry; if it reads inverted in motion that is a
one-line change in the tool's `BANK_ORDER`.

---

## 10. Hygiene

- `pgrep -fl x64sc` checked before each automated session; clear after the gate.
- Every emulator `-console`, owned by exact PID, reaped on every exit path. No
  broad `pkill`, no `open -a`, no window, no focus theft.
- No `-default`; `+saveres` retained; no joystick-disable overrides; no
  persistent VICE setting touched.
- Background tasks awaited by notification, not polled.

---

*The sheet's palette carries black twice — once as an outline colour and once
as the transparency key — and reading it as RGB merges them, which is how the
intended ship came to look like debris and a different craft got integrated
instead. Read by index, the artwork is a clean 3×3 of banking against engine
animation in exactly three colours: one multicolour sprite, fifteen frames, and
the one `$d01c` bit the renderer had already reserved for the day this
happened.*
