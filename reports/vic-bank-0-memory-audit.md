# VIC bank 0 memory audit

Audit only. **No code, data placement, layout or behaviour was changed.** Every
address below was taken from the live build map or from source; the accounting
closes exactly to 16384 bytes with nothing unattributed.

## 1. The complete map

| range | size | class | contents |
|---|---:|---|---|
| `$0000-$00ff` | 256 | SYSTEM | zero page |
| `$0100-$01ff` | 256 | SYSTEM | 6502 stack |
| `$0200-$033f` | 320 | SYSTEM | KERNAL/BASIC vectors and buffers |
| `$0340-$03ff` | 192 | **REQUIRED** | clip scratch, 3 blocks (ptr 13–15) |
| `$0400-$07ff` | 1024 | **REQUIRED** | screen page A (+ sprite ptrs `$07f8`) |
| `$0800-$0fff` | 2048 | **REQUIRED** | terrain charset window |
| `$1000-$1fff` | 4096 | **NOT VIC CAPACITY** | character ROM shadow |
| `$2000-$23ff` | 1024 | **RECLAIMABLE** | diagnostic sprites, 16 blocks |
| `$2400-$27ff` | 1024 | **RELOCATABLE** | p5 ring tables (CPU-only data) |
| `$2800-$2bff` | 1024 | **REQUIRED** | screen page B (+ ptrs `$2bf8`) |
| `$2c00-$3093` | 1172 | **RELOCATABLE** | raster executor (CPU-only code) |
| `$3094-$30ff` | 108 | FREE | executor headroom |
| `$3100-$31ff` | 256 | **REQUIRED** | clip scratch, 4 blocks |
| `$3200-$357f` | 896 | **REQUIRED** | HUD sprite bitmaps, 14 blocks |
| `$3580-$363f` | 192 | **REQUIRED** | player bitmaps, 3 blocks |
| `$3640-$367f` | 64 | **REQUIRED** | enemy bitmap, 1 block |
| `$3680-$36bf` | 64 | **REQUIRED** | clip scratch, 1 block |
| `$36c0-$36ff` | 64 | **REQUIRED** | projectile bitmap, 1 block |
| `$3700-$37ff` | 256 | **REQUIRED** | clip scratch, 4 blocks |
| `$3800-$3fff` | 2048 | **REQUIRED** | blank charset + idle byte `$3fff` |

**Totals:** REQUIRED 8128 · NOT VIC CAPACITY 4096 · RELOCATABLE 2196 ·
RECLAIMABLE 1024 · SYSTEM 832 · FREE **108**.

### The headline correction

**True free space in VIC bank 0 is 108 bytes**, not the ~640 B the earlier
clipping work started from — that figure was consumed by the twelve scratch
blocks. The only untouched hole is `$3094-$30ff`, and it is the raster
executor's documented growth room.

### `$1000-$1fff` is not capacity at all

The VIC reads the **character ROM** here in banks 0 and 2, so RAM at these
addresses is invisible to it. 4 KB of the nominal 16 KB can never hold screen,
charset or sprite data. Code living there (schedule builder, HUD code, fixtures,
motion, sorter) therefore costs **nothing** in VIC terms — it is the correct
home for CPU-only code and is already used that way.

Real VIC-addressable pool: 16384 − 4096 (ROM shadow) − 832 (system low RAM) =
**11456 B**, of which 8128 is committed.

## 2. Why each REQUIRED region is required

**Both screen pages.** Genuine double buffering — `dispPage` flips between A and
B every coarse step (`scroll.asm:443-445`), with the scroller regenerating the
off-screen page. Each also carries its sprite pointers in its last 8 bytes
(`$07f8`, `$2bf8`). Neither is removable; both must stay at 1 KB boundaries.

**Both charsets, and they do different jobs.**
- *Terrain charset* `$0800-$0fff` is the `$d018` window for the playfield.
  Glyph data occupies only `$0b00-$0d3f` (codes 96–167) and `$0f10-$0f2f`
  (codes 226–229) — 608 of 2048 bytes — but the window is 2 KB by hardware
  definition and every code that reaches screen memory reads from it.
- *Blank charset* `$3800-$3fff` is what the aperture splits switch to at rasters
  55 and 248 so terrain characters stop rendering outside the playfield, **and**
  it supplies the VIC's idle byte at `$3fff` (fetched on every idle line, which
  the open vertical border displays). It must be 2 KB of zeros; it cannot live
  at `$1000` because the VIC would read the ROM's real glyphs there.

**Sprite assets** (31 blocks, 1984 B): HUD 14, player 3, enemy 1, projectile 1,
clip scratch 12. All genuinely VIC-visible.

## 3. The charset-window holes are NOT reclaimable — and here is the evidence

Unused code ranges in the terrain window look like free space: codes 0–95
(`$0800-$0aff`), 168–225 (`$0d40-$0f0f`), 230–255 (`$0f30-$0fff`) — 1440 bytes.
The prior task ruled them out by policy. That policy is independently correct,
and the reason is stronger than "a future charset might grow":

`hudTick` is called every frame (`main.asm:477`) and stamps a diagnostic **text**
overlay into screen memory on rows 1, 2, 20, 21, 22, 23. Its labels use screen
codes 1–26 and 32 (`labelText`), and its values use `hexDigit` **OR `#$80`** —
reverse video — giving codes **129–134** (A–F) and **176–185** (0–9).

So live screen bytes reference codes scattered right across the window,
including 176–185 which sits inside the supposedly-free 168–225 range. Any sprite
bitmap placed there would be fetched as a character glyph and drawn as garbage.

**Incidental finding, flagged rather than acted on:** codes 129–134 fall *inside
the terrain glyph namespace* (96–167), so when a diagnostic value contains a hex
digit A–F the overlay indexes terrain glyphs 33–38 and would draw terrain tiles
where it means to draw letters. The other codes it writes are zero-filled and so
render blank, which is presumably why nothing has been noticed. This is a
latent presentation bug in a diagnostic surface, not a memory problem, and it is
outside this audit's remit — but it is the same fact that makes the window
unsafe to reclaim.

## 4. Occupants that do not need VIC visibility

**`$2c00-$3093` — raster executor, 1172 B, RELOCATABLE.** CPU-only code. The VIC
never fetches it. It is in bank 0 for historical reasons ("moved from `$1500`; it
outgrew the hole below the fixture tables"). With its adjacent 108 B headroom it
is a contiguous **1280 B / 20 blocks**.

**`$2400-$27ff` — p5 ring tables, 1024 B, RELOCATABLE.** CPU-only data, and the
source says so outright: *"It is inside VIC bank 0 but nothing ever points the
VIC at it — sprite pointers only ever hold `$80..$8f` — so it is ordinary RAM
that happens to be cheap to address."* **16 blocks**.

**`$2000-$23ff` — diagnostic sprites, 1024 B, RECLAIMABLE.** These *are*
VIC-visible sprite bitmaps (hollow rectangles with hex numerals for identifying
slot-reuse faults), but they serve the P0–P5 qualification fixtures only.
`FIXTURE_KEYS` is `false` and nothing selects a fixture in a production boot, so
in the shipped game they are dead weight. They remain live for the retained
`test-engine-full` / `test-renderer-full` targets, so this is a decision about
the archived ladder, not a free deletion. **16 blocks.**

**DEAD: none.** Every region has a current owner and a reason.

## 5. Alignment and padding

- The twelve clip blocks are 64-byte aligned by assertion; nine are emitted into
  the PRG purely so the assembler maps them and a future segment growing into one
  becomes a build error. They are always fully written before use, so those
  **576 bytes of zeros in the PRG file are avoidable** — a file-size note only,
  costing no RAM.
- `$3094-$30bf` (44 B) is a sub-block remnant: not 64-byte aligned, so unusable
  for sprite data even though it is free.
- `$0340-$03ff` is deliberately **not** emitted; the PRG starts at `$0801` and
  reaching lower would drag screen page A and the stack into the file.
- PRG spans `$0801-$cfda` (51162 bytes payload), so gaps inside VIC0 above
  `$0801` are zero-filled in the file regardless of whether they are named.

## 6. Documentation drift (reporting only, not fixed)

The map comment in `main.asm:26-54` no longer matches the binary:

- `$3000-$31ff` is described as free — `$3100-$31ff` is now clip scratch.
- `$3600-$37ff` is described as free — it now holds player/enemy/clip/projectile.
- player bitmaps are described as "2 x 64" at `$3580-$35ff` — they are **3
  blocks**, `$3580-$363f`.
- the enemy bitmap, the projectile bitmap and the entire `$0340-$03ff` clip pool
  are absent from the map.

## 7. Recommended future layout strategy

Sprite blocks do **not** need to be contiguous — each pointer names any 64-byte
block independently — so capacity and tidiness are separable goals.

### Step 1 — evict the CPU-only occupants (+36 blocks, 2.25 KB)

Move the raster executor and the p5 ring tables out of bank 0 (`$8000-$bfff` is
entirely free). Neither is ever fetched by the VIC, so **no VIC-visible
semantics change at all**: no `$d018` value moves, no screen or charset base
changes, no pointer arithmetic changes. This is the high-value, low-risk step.

Frees `$2400-$27ff` (16 blocks) and `$2c00-$30ff` (20 blocks).

*Caveat:* the executor is the most timing-critical code in the engine. Relocating
it is an address change, not a logic change, but it wants its own bounded task
and a raster re-measure (`edgeLate`, `topSplitMax`, `botSplitMax`).

### Step 2 — decide the diagnostic sprite set's future (+16 blocks, 1 KB)

Either retire it with the archived P-suite, or move it into the arena and accept
that tests share the space.

### Step 3 (optional, tidiness only) — one contiguous arena

Moving screen page B from `$2800` to `$2000` yields a single unbroken
`$2400-$37ff` = **5120 B / 80 blocks** arena. This buys *contiguity, not
capacity* — useful for indexing assets as `base/64 + index`. It touches the
`SCREEN_B`/`PTR_B`/`D018_B` constants and therefore the aperture splits, so it is
the step to take last, if at all.

### Resulting capacity

| scenario | sprite blocks available | spare after today's 31 |
|---|---:|---:|
| today | ~32 | 1 |
| + step 1 | 68 | 37 |
| + step 2 | **83** | **52** (3328 B) |

**83 blocks / 5312 B is the hard ceiling**, and it is arithmetic rather than
ambition: 11456 B of VIC-addressable pool minus 6 KB of screens and charsets.

That is comfortably "several KB of sustainable sprite-asset capacity". For scale,
52 spare blocks is thirteen four-frame animated enemy types, or fifty-two
single-frame shapes. The clip scratch stays fixed at 12 blocks however much art
is added — which was the point of choosing runtime clipping over pre-generated
variants.

### The standing rule worth adopting

> Nothing lives in VIC bank 0 unless the VIC reads it.

Applying it today recovers 2.25 KB immediately and 3.25 KB in total, and it is
the rule that would have prevented both current violations.

---

No files were modified, no tests were run, nothing was committed or pushed.
