# Importing the expanded SpritePad artwork set

**Date:** 2026-09-28
**Source:** `~/Desktop/19656-sprites_v2.spd` → `assets/sprites/19656-sprites.spd`
**Engine changes:** none. **Gameplay changes:** none.
**Committed or pushed:** no. **No destructive git operation was used.**

---

## 0. The short version

The expanded set imported cleanly and **the memory map did not move by one
byte**. That is not luck: this engine does not store sprites as one flat run of
64-byte slots, so the question the brief framed — full `$00`–`$6C` contiguous
versus a compact 88-slot set — turns out not to be the question. The engine
already streams enemy artwork per level, and the importer only ever emits
artwork that has a runtime home. **46 of the project's 110 blocks have one.**
The other 64, including every range you marked disposable, cost nothing at all
because they are simply never named.

Two things could not be delivered and are reported rather than bluffed:

1. **`ring_3` cannot show all eight frames.** `ENEMY_FRAMES = 4` is engine-wide
   and guarded in five files plus the level editor. The Ring ships four of the
   eight — every *second* frame, so a complete rotation rather than a quarter of
   one. Raising it is architectural.
2. **The old Sonic Ring artwork is gone from the project**, so the Ring species
   had to be pointed at something new. That was a judgement call and it is the
   one decision in here I would like you to confirm.

---

## 1. Sprite source

| | |
|---|---|
| supplied file | `~/Desktop/19656-sprites_v2.spd`, 7,066 bytes |
| destination | `assets/sprites/19656-sprites.spd` (previous file snapshotted first) |
| format | SpritePad **version byte 5** — the previous project was version 1 |
| sprites | **110**, indices `$00`–`$6D` |
| all multicolour | **yes** — every one of the 110 metadata bytes has bit 7 set |
| shared colours | background 0, `$d025` = 11 dark grey, `$d026` = 1 white — exactly the engine's own |
| animations | 1 record: first 104 (`$68`), last 108 (`$6C`), speed 4 |
| blank slots | exactly two: `$0F` and `$6D` |

### The format was new, and the reader had to be taught it

The repo's parser is deliberately strict and rejected the file outright:
`unsupported SpritePad version byte 5`. The v5 layout is not documented in the
repo, so it was **derived from the file** and the derivation is written into
`spd_reader.py` rather than left as folklore:

* the previous project's sprite 0 bitmap occurs at offset **20**, which fixes the
  body start exactly — it is the same picture;
* 20 is the only candidate body offset at which *every* 64th trailing byte has
  bit 7 set, which also yields exactly **110** whole blocks;
* the 6 bytes left over read `68 00 6c 00 04 00` — three little-endian words,
  104, 108, 4. `$68`–`$6C` is precisely the five-frame "spinny rotatey thing",
  so the trailer is one 6-byte **animation** record;
* the word at offset 16 is 1, the number of such records;
* the word at offset 5 is 110, the sprite count, stored **plain** here where v1
  stores it minus one;
* offsets 13, 14, 15 are 0, 11, 1 — background and the two shared multicolours.

So **`len == 20 + 64*sprites + 6*animations`**, and that identity is checked
before any offset is trusted, exactly as the v1 path checks its own. A future v5
file carrying something this does not predict fails loudly instead of being
half-read. Version 1 is still accepted unchanged.

---

## 2. Memory audit

**Active gameplay VIC bank: bank 0, `$0000`–`$3FFF`.** Screen RAM is double
buffered at `SCREEN_A = $0400` and `SCREEN_B = $2800`. The level's terrain
charset is at `$0800`–`$0FFF`; a second, all-zero charset at `$3800`–`$3FFF`
does the aperture clipping and supplies the VIC idle byte at `$3FFF`.

```
  $0000-$03ff   1024 B   zero page, stack, system
  $0400-$07ff   1024 B   SCREEN_A
  $0800-$0fff   2048 B   terrain charset (level-owned)
  $1000-$1fff   4096 B   character ROM image the VIC sees in this bank
  $2000-$23ff   1024 B   player bitmaps, 16 blocks (15 art + the HW1 blank)
  $2400-$253f    320 B   player muzzle flash, 5 blocks
  $2540-$257f     64 B   FREE                                   <-- 1 block
  $2580-$25bf     64 B   token bitmap, 1 block
  $25c0-$27bf    512 B   player fireball, 8 blocks
  $27c0-$27ff     64 B   FREE                                   <-- 1 block
  $2800-$2bff   1024 B   SCREEN_B
  $2c00-$30ff   1280 B   LEVEL ENEMY SPRITE WINDOW, 20 blocks
  $3100-$31ff    256 B   clip scratch
  $3200-$357f    896 B   HUD bitmaps, 14 blocks (hires; not in the .spd)
  $3580-$367f    256 B   boss cells, 4 blocks (filled from the level package)
  $3680-$36bf     64 B   clip scratch
  $36c0-$36ff     64 B   projectile bitmap, 1 block
  $3700-$37ff    256 B   clip scratch
  $3800-$3fff   2048 B   blank charset / VIC idle byte
```

### The engine does **not** assume sprite data is contiguous

This is the finding that reframes the whole task. `import_spd.py` says so in its
own docstring: the sprites "do not live in one run", they are pinned at nine
separate addresses, several of them owned by the module that imports them
(`src/player.asm` sets `* = PLAYER_SPRITES` and then imports the art). The
importer emits **one include per import point** for exactly that reason.

### There is already a bank/overlay strategy, and it is per level

`LEVEL_SPRITES = $2c00`, `LEVEL_SPRITE_BLOCKS = 20`, ending at `$3100`. Enemy
artwork is **not** resident in the binary at all: it travels in the level
package and `levelApplySprites` copies it into that window at level init. A
level package says which *slot* of the window each species occupies and
`levelSlotAddr()` resolves it. So enemy art is already streamed, and different
levels can ship different art into the same 20 blocks.

### Pointers

`LEVEL_PTR_FIRST = $2c00/64 = $b0`; the window's 20 blocks are pointers
`$b0`–`$c3`. Player art starts at pointer `$80`, muzzle flash `$90`, HUD `$c8`.
The highest imported block is the projectile at `$36c0` → pointer **`$db`**,
comfortably inside the byte a VIC sprite pointer is. A guard already asserts
`LEVEL_PTR_FIRST + LEVEL_SPRITE_BLOCKS <= 256`.

### Free space, before and after

| | blocks | bytes |
|---|---:|---:|
| free in bank 0 (two gaps, `$2540` and `$27c0`) | 2 | 128 |
| free in the per-level enemy window | 8 | 512 |
| **total free** | **10** | **640** |

**Before and after are identical.** The import emits the same 46 blocks into
the same addresses as the previous project did; not one region moved, grew or
shrank, and the two free gaps are still free.

### Hard limits found

| Limit | Value | Where |
|---|---|---|
| terrain/sprite bank | `$0000`–`$3fff` | `src/main.asm` |
| enemy window size | `LEVEL_SPRITE_BLOCKS = 20`, flush at `$3100` | `src/main.asm`, guarded against the clip scratch |
| frames per species | **`ENEMY_FRAMES = 4`** | `src/enemy.asm`, guarded in `level_assets.asm` ×6 and `level_package.asm` |
| species | **`SPECIES_COUNT = 3`** | `src/encounter_format.asm`, guarded in `enemy.asm` |
| animation steps | `ENEMY_ANIM_STEPS = 8`, must be a power of two | `src/encounter_format.asm` |
| level descriptor row | `LEVEL_DESC_ROW_STRIDE = 4`, must be ≥ `SPECIES_COUNT` | `src/level_assets.asm` |
| player run | 16 blocks; muzzle flash must not pass `SCREEN_B` | `src/player.asm` |
| importer slot count | now 110, refuses any other | `tools/sprite_export/import_spd.py` |

### Could the full set be resident?

No, and it does not need to be.

| | blocks | bytes |
|---|---:|---:|
| full `$00`–`$6C` resident | 109 | 6,976 |
| compact set omitting the disposable ranges | 88 | 5,632 |
| **actually free today** | **10** | **640** |
| **actually required** | **46** | **2,944** |

Both of the brief's candidate layouts overrun the bank by thousands of bytes.
Neither is needed: the artwork that has a runtime home is 46 blocks and it
already fits, because the engine streams enemy art per level rather than keeping
a library resident.

---

## 3. Import

**Runtime import is neither "full contiguous" nor "compacted".** There is no
compaction step because there is nothing to compact — the importer emits only
what is named in one table, and the disposable ranges are simply not named. They
cost zero bytes by construction rather than by being stripped.

### The mapping, which lives in exactly one place

`GROUPS` in `tools/sprite_export/import_spd.py`. Each entry now carries an
explicit tuple of SpritePad indices instead of a first/count pair, because one
group is not a contiguous range.

| Generated file | Runtime label | SpritePad source | Blocks |
|---|---|---|---:|
| `player_art.asm` | `player_art_frames` | `$00`–`$0E` | 15 |
| `player_muzzle_flash.asm` | `playerFlashBitmaps` | `$10`–`$14` | 5 |
| `token_art.asm` | `tokenBitmap` | **`$53`** | 1 |
| `player_boom_art.asm` | `playerBoomArt` | `$16`–`$1D` | 8 |
| `enemy_art.asm` | `sonicRingFrames` | **`$60, $62, $64, $66`** | 4 |
| `enemy_dropper_art.asm` | `orbitalDropperFrames` | `$1E`–`$21` | 4 |
| `enemy_square_art.asm` | `squareFrames` | `$27`–`$2A` | 4 |
| `boss_art.asm` | `bossArt` | `$22`–`$25` | 4 |
| `ebullet_art.asm` | `ebulletBitmap` | `$26` | 1 |
| | | **total** | **46** |

Every generated file names its source indices in its own banner, so a block can
be traced back to the index you drew it at without reading the importer.

### Omitted from runtime — 64 blocks, 4,096 bytes never spent

`$0F`, `$15`, `$2B`–`$33`, `$37`–`$3A`, `$4A`–`$4F` (your disposable list, 21
slots), plus `$34`–`$36`, `$3B`–`$3D`, `$3E`–`$40`, `$41`–`$43`, `$44`–`$49`,
`$50`–`$52`, `$54`–`$59`, `$5A`–`$5F`, `$61`/`$63`/`$65`/`$67`, `$68`–`$6C`,
`$6D`. All retained in the `.spd` as artwork authority.

### Importer changes

* `spd_reader.py` — SpritePad v5 support, with the derivation recorded.
* `import_spd.py` — `EXPECTED_SLOTS` 48 → 110; blank slots `(15, 47)` →
  `($0F, $6D)`; `GROUPS` retargeted and given explicit slot tuples; a new
  `RUNTIME_SYMBOL` / `SLOTS_OF_SYMBOL` pair so the source-index → runtime-label
  mapping exists once; the blank/hires/empty guards now cover **every** emitted
  block rather than only the Square's four.
* `verify_sprites.py` — its `SLOT_OF_GROUP` dictionary of literal slot numbers
  **deleted** and derived from `import_spd` instead. It was a second copy of the
  mapping, it went stale in this reorganisation, and the test guarding it
  compared the stale dictionary against an equally stale literal list, so the
  two agreed with each other and proved nothing.
* `test_spd_pipeline.py` — offsets derived from the parsed version rather than a
  hard-coded `9`; new byte-for-byte slot-mapping proofs (§6).

Generated output stays deterministic: same `.spd` in, same files out, stamped
with the SHA-256 (`b1d8ef40fc68…`), and `make build` still fails loudly on a
stale tree.

---

## 4. Animation

**Representation.** A species value *is* its row offset into an animation table:
`SPECIES_RING = 0`, `SPECIES_DROPPER = 8`, `SPECIES_SQUARE = 16`, so frame
lookup is a single `species ORA step`. `ENEMY_ANIM_STEPS = 8` steps per species,
and the step table maps each step onto one of the species' **`ENEMY_FRAMES = 4`**
bitmap blocks.

So there are two different ceilings and only one of them is 8:

* the **sequence** is 8 steps — no problem for any sequence you supplied;
* the **distinct bitmaps** a species owns is **4**, and that is the real limit.

**The 8-frame `ring_3` is therefore NOT fully addressable.** Four of its eight
frames reach the screen. This is reported, not worked around:

* `ENEMY_FRAMES` is a single global constant consumed by six guards in
  `src/level_assets.asm`, a further guard in `src/level_package.asm` (which
  hard-codes the literal `4`), the per-level slot claims in each
  `stage_enemies.asm`, the window manifest in each `stage_sprites.asm`, and the
  level editor's exporter that emits both of those;
* making it per-species means a variable slot claim in the package format and a
  change to the editor, in at least six files across two tools.

That is architectural, not a bounded extension, so per your instruction I stopped
and am reporting it. **The window would hold it**: an 8-block Ring plus a
4-block Dropper and a 4-block Square is 16 of 20 blocks. The cost is the format
and the editor, not the memory.

Frame counts against what the runtime can host today:

| Sequence | Frames | Hosted |
|---|---:|---|
| Dropper `$1E`–`$21` | 4 | **yes, all 4** |
| boss `$22`–`$25` | 4 | **yes, all 4** (boss art is not frame-limited by `ENEMY_FRAMES`) |
| Square `$27`–`$2A` | 4 | **yes, all 4** |
| `ring_3` `$60`–`$67` | 8 | 4 of 8 |
| modded Alleykat A/B, unmodified Alleykat, `ring_1`, `ring_2`, `spinner`, Hades A/B, space mine, spinny thing, space whisk, spinny rotatey | 2–6 | **none** — no free species slot |

The player ship (15), muzzle flash (5) and death fireball (8) are unaffected:
they have their own special handling and their own fixed runs, and all of their
frames are imported exactly as before.

---

## 5. Compatibility

### What changed visually, and why

The artwork was **reorganised**, not merely extended. Established by matching the
previous project's bitmaps into the new file rather than by trusting a
description:

| Role | old slots | new slots | Bytes |
|---|---|---|---|
| player ship | 0–14 | `$00`–`$0E` | 9 frames identical, **6 redrawn** (3,4,5,9,10,11) |
| HW1 blank | 15 | `$0F` | still blank |
| muzzle flash | 16–20 | `$10`–`$14` | identical |
| player fireball | 22–29 | `$16`–`$1D` | identical |
| boss | 38–41 | `$22`–`$25` | identical |
| hostile projectile | 42 | `$26` | identical |
| token | 21 | **gone** → `$53` | **new art**: the shaded power-up |
| Orbital Dropper | 34–37 | `$1E`–`$21` | **redrawn** |
| Square | 43–46 | `$27`–`$2A` | **redrawn** |
| Sonic Ring | 30–33 | **gone** | **replaced** — see below |

So expect to see: a new shaded power-up token, a redrawn Dropper, a redrawn
Square, six redrawn ship frames, and a different Ring. Everything else is
byte-identical to what shipped before.

### The one decision I made for you

**The old four-frame Sonic Ring artwork is not in the new project at all**, and
the map has no four-frame ring to replace it. The candidates are `ring_1` (3
frames), `ring_2` (3) and `ring_3` (8).

I pointed `SPECIES_RING` at **`ring_3`, sampling `$60, $62, $64, $66`**.
Rationale, from looking at the art: `ring_3` is a green torus with a white
highlight travelling once around the rim in eight steps — it is the rotation the
Sonic Ring was. Taking every second frame gives a **complete** rotation at half
the smoothness, which is exactly what the old north/east/south/west was. Taking
the first four would have shown a quarter turn and then snapped back.

`ring_1` and `ring_2` are 3-frame pulses, not rotations, and would have needed a
frame invented to reach four.

**This is the item to confirm.** If you would rather the Ring were `ring_1`,
`ring_2`, or a different sample of `ring_3`, it is one line in `GROUPS`.

### Disposable ranges

* **`$0F`** — confirmed blank in the file, and it is *not* merely accidental:
  `src/player.asm` emits `playerBlankBitmap` as the 16th block of the player run
  and the importer asserts the `.spd`'s `$0F` is blank so the two cannot
  disagree. It consumes no imported block. Keep it empty.
* **`$15`** — obsolete power-up, not imported. `$53` is the token the game draws.
* **`$2B`–`$33`** Alleykat explosion, **`$37`–`$3A`** unmodified Alleykat,
  **`$4A`–`$4F`** Hades reference art — none imported, all retained in the `.spd`.
* Proved mechanically: all 21 disposable slots consume **zero** runtime blocks.

### Colour metadata

Untouched, and deliberately so. The importer reads only the 63 bitmap bytes plus
the multicolour bit; the per-sprite colour nibble is used **only** to refuse a
hires sprite. Runtime colour is unchanged: the three enemy species take the
**trigger's authored colour** in `$d027+n` (commit `5afc5d1` made triggers own
colour and fire mode), and the shared `$d025`/`$d026` are engine-wide 11 and 1 —
which is exactly what the new project carries, so a drawing in Spritemate
matches the game.

---

## 6. Validation

### Build

`make build` — **succeeds**. Every sprite region reported at its previous
address: `$2000-$23ff` player, `$2400-$253f` muzzle, `$2580-$25bf` token,
`$25c0-$27bf` fireball, `$36c0-$36ff` projectile. Boss cells and the enemy
window are filled from the level package (`$e7d0-$eccf` window, `$ecd0-$edcf`
boss). The assembler's own overlap guards — muzzle flash vs `SCREEN_B`, window
vs clip scratch, 64-byte alignment, pointer representability — all pass, which
is the overlap check.

### `make smoke` — **PASS**

```
CAMPAIGN LOOP: PASS      ATTRACT -> PLAYING -> shop -> level 2 -> GAME OVER -> front
Frames observed: 4048
  gameOverrun 0   scrollLate 0   edgeLate 0   statOverflow 0   statPageMismatch 0
  statPtrMismatch 0   objDoubleFree 0   objAllocFail 0   clipPoolFull 0
  publishSkip 0   schedBuildDefer 0   statLate 0
ENGINE HEALTH: PASS      ROUTINE REGRESSION: PASS
```

### Importer proofs — 40 checks, 0 failures

New, and these are the ones the brief asked for:

```
ok  every emitted 64-byte block equals its SpritePad slot, byte for byte
       -- 46 blocks verified
ok  every named index either resolves to one runtime block or to none
       $00->player_art_frames[0]    $0E->player_art_frames[14]
       $10->playerFlashBitmaps[0]   $1E->orbitalDropperFrames[0]
       $26->ebulletBitmap[0]        $27->squareFrames[0]
       $34->not resident            $3E->not resident
       $44->not resident            $50->not resident
       $53->tokenBitmap[0]          $5A->not resident
       $60->sonicRingFrames[0]      $6C->not resident
ok  no disposable slot consumes a runtime block -- 21 slots confirmed non-resident
```

The six "not resident" answers are correct, not failures: `$34`, `$3E`, `$44`,
`$50`, `$5A` and `$6C` are sequences with no species slot to live in.

The block-equality proof re-parses the generated assembler back into 64-byte
blocks and compares them with the `.spd` — it does not ask the generator whether
it generated correctly.

### Highest sprite and pointer

Highest imported block: the projectile at `$36c0`, pointer `$db`. Highest block
the VIC can be pointed at in this layout: the window's last, `$30c0` → `$c3`,
and the HUD's at `$c8`–`$d5`. All within one byte; the existing
`LEVEL_PTR_FIRST + LEVEL_SPRITE_BLOCKS <= 256` guard still passes.

### Visible VICE proof

Captured through `tests/harness.py` (exact PIDs, `-console`, no window, no focus
stolen), frame-accurate stepping, four points in level 1.

* The **player ship** draws correctly with the redrawn frames.
* The **Ring** appears as a column of four enemies at different animation steps,
  each a torus with the white highlight in a different place — the `ring_3`
  sampling animating correctly — and each in a **different wave-authored colour**
  (red, purple, grey, blue), confirming pair 10 still reaches `$d027+n`.
* The **player fireball** plays on death.
* No corrupted blocks, no misaligned art, nothing pointing at the wrong bitmap.

### Git and hygiene

* Working tree at start: **clean** (your previous session's work is committed at
  `d5fc70d` and `5afc5d1`). The previous `.spd` and manifest were snapshotted to
  the session scratchpad before anything was written.
* **No `git checkout`, `restore`, `reset`, `stash` or `clean` was used at any
  point.** The only git commands run were `status`, `log` and `show`, all
  read-only.
* VICE: every instance launched through the harness with its exact PID recorded
  and reaped; no `pkill`/`killall`; `pgrep -x x64sc` reports none remaining; the
  user's own VICE was never touched.
* Nothing committed, nothing pushed.

---

## 7. Unrelated problems found, not fixed

1. **`verify_sprites.py` / `sprite_source.py` cannot run — pre-existing.** They
   read sprite bytes back out of `build/main.prg` to prove the built program
   equals the `.spd`, but the enemy and boss art moved into the *level package*
   at commit `8795c39`, so `sonicRingFrames` is now in `level_package.sym` at
   `$e7d0` and not in `main.sym` at all. `sprite_source.py` was last touched at
   `cb3c194`, **before** that move, so this has been broken since well before
   this task. Fixing it means teaching the readback tool about the level package,
   which is a real piece of work and out of scope. I updated its group table to
   stop duplicating the slot mapping, but did not attempt to make it run.
2. **`assets/sprites/19656-sprites.json` is now stale.** It is a generated
   manifest produced by `verify_sprites.py`, so it could not be refreshed while
   that tool cannot run. Nothing reads it at build time — the README already says
   it is documentation, not data — but it now describes the previous artwork.
3. **`$6D` exists.** The project has 110 slots, one past the `$00`–`$6C` your map
   describes. It is blank, and is treated exactly as slot 47 was before: asserted
   blank, never imported.

---

## 8. Files

**Changed**
- `assets/sprites/19656-sprites.spd` — the new artwork authority
- `assets/sprites/README.md` — the slot table, the v1/v5 format table, the mapping rules
- `tools/sprite_export/spd_reader.py` — SpritePad v5
- `tools/sprite_export/import_spd.py` — slot map, explicit slot tuples, single-source mapping, wider guards
- `tools/sprite_export/verify_sprites.py` — duplicate mapping removed
- `tools/sprite_export/test_spd_pipeline.py` — format-derived offsets, new proofs
- `src/generated_sprites/*.asm` — regenerated (10 files)

**Added**
- `reports/sprite-set-v2-import.md`

**Untouched:** the engine, the renderer, the multiplexer, the scroller, the
raster code, collision, waves, triggers, enemy behaviour, level data, and all
sprite *artwork* — nothing was redrawn.
