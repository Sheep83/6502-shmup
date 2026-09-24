# Gameplay sprites — `19656-sprites.spd` is the source of truth

**Edit the sprites here, not in `src/`.** `19656-sprites.spd` is the
authoritative artwork for every editable gameplay sprite in the game. The
assembler files under `src/generated_sprites/` are produced from it and are
overwritten on every regeneration — never hand-edit them.

## The workflow

```
1. open assets/sprites/19656-sprites.spd in Spritemate   (https://spritemate.com)
2. draw, save back over the same file
3. make sprites        regenerate src/generated_sprites/
4. make run            build and play
```

`make build` (and therefore `make run` and `make test`) **validates** that the
generated tree came from the current `.spd` and fails loudly if it did not:

```
  sprite art: generated from a different .spd
  The generated sprite art is STALE.
  Run:  make sprites
```

So saving in Spritemate and forgetting step 3 cannot quietly ship the previous
artwork. The build does not regenerate by itself on purpose — the same reason
`tools/level_editor/export_level.py` gives for level data: a build that can
change the program's content is a build whose output nobody reviewed.

## Format

**SpritePad 2.0.** Signature `SPD`, version byte 1, sprite count stored minus
one, then three shared colours and N 64-byte blocks of 63 bitmap bytes plus one
metadata byte (bit 7 multicolour, bit 4 overlay, bits 0–3 colour). Spritemate
reads and writes exactly this; `tools/sprite_export/spd_reader.py` parses it
strictly and documents the evidence.

## Slots

| Slots | Contents |
|---|---|
| 0–14 | player ship — 5 banking attitudes × 3 engine frames, bank-major |
| 15 | **deliberately blank** — the block HW1 draws; keep it empty |
| 16–20 | muzzle flash, one per attitude |
| 21 | collectible token |
| 22–29 | player death fireball, 8 frames |
| 30–33 | Sonic Ring — north, east, south, west |
| 34–37 | Orbital Dropper — wide, front-right, front, front-left |
| 38–41 | boss, 4 cells |
| 42 | hostile projectile |
| 43–46 | **Square** — the third ordinary enemy species, 4 spin frames |
| 47 | unused trailing slot; left alone by the importer |

**Slots 0–42 keep their roles and their order.** The engine addresses sprites by
VIC pointer, so inserting, deleting or reordering a slot would silently
repoint something. The importer refuses a `.spd` whose slot count has changed
rather than guessing which sprite became which.

To add another species, append four more frames and extend the group table in
`tools/sprite_export/import_spd.py` — the same way the Square was added.

## HUD sprites are not here, on purpose

`hudBitmaps` (`$3200`, 14 blocks) stays under its existing authority. Four of
its blocks are `.fill 64, 0` framebuffers the CPU draws into every frame, and
the other ten are emitted by assembler functions (`livesByte`, `pchargeByte`)
inside `.for` loops, so a pixel edited in an editor could not survive a build.
They are also the game's only hires sprites.

## Colour: three different things

| | What it is | Where it lives |
|---|---|---|
| **Bitmap payload** | the 63 bytes; the picture itself | the `.spd`, authoritative |
| **SPD editing colour** | what Spritemate shows you while drawing | the `.spd`, reaches nothing at run time |
| **Runtime colour** | what the engine writes to `$d027+n` | the engine, or the wave |

For **all three enemy species** the runtime colour is the **wave's authored
colour**, so one set of frames appears in as many colours as there are waves
using it. Changing a sprite's colour in Spritemate changes only your canvas.

The two shared multicolours are fixed engine-wide: `$d025` = 11 dark grey
(bit-pair 01) and `$d026` = 1 white (bit-pair 11). Keep them as they are in the
`.spd` or your drawing will not match what the game shows.

## Tools

| File | Role |
|---|---|
| `tools/sprite_export/import_spd.py` | **`.spd` → `src/generated_sprites/`**, plus `--check` |
| `tools/sprite_export/spd_reader.py` | strict SpritePad 2.0 parser |
| `tools/sprite_export/verify_sprites.py` | proves the built program equals the `.spd`; refreshes the manifest |
| `tools/sprite_export/sprite_source.py` | reads sprite bytes back out of the built PRG |
| `tools/sprite_export/contact_sheet.py` | optional visual diagnostic (needs Pillow) |
| `tools/sprite_export/test_spd_pipeline.py` | the pipeline's tests |

`19656-sprites.json` is a generated manifest — names, roles, addresses, sprite
pointers and the runtime-colour notes SpritePad has nowhere to put. It is
documentation, not data; nothing reads it at build time.
