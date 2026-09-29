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

**SpritePad, version byte 1 or 5.** The current project is **version 5**, which
Spritemate writes now; version 1 (SpritePad 2.0) is still accepted. The SPRITE
BLOCK is identical in both — 63 bitmap bytes then one metadata byte (bit 7
multicolour, bit 4 overlay, bits 0–3 colour) — and only the header and trailer
differ:

| | v1 | v5 |
|---|---|---|
| body starts at | 9 | 20 |
| sprite count | byte 4, stored minus one | word at 5, stored plain |
| shared colours | bytes 6, 7, 8 | bytes 13, 14, 15 |
| animations | byte 5, 4 bytes each | word at 16, 6 bytes each |
| total length | `9 + 64n + 4 + 4a` | `20 + 64n + 6a` |

`tools/sprite_export/spd_reader.py` parses both strictly, checks the length
identity before trusting any offset, and writes down how the v5 offsets were
derived from the file itself.

## Slots — 110 of them, `$00`–`$6D`

The project is the **artwork authority for the whole set**, and most of it has no
runtime home. Only the ranges marked **wired** below are imported; everything
else exists to be drawn, referred to by index, and promoted later.

| Slots | Frames | Contents | |
|---|---:|---|---|
| `$00`–`$0E` | 15 | player ship — 5 attitudes × 3 engine frames, bank-major | **wired** |
| `$0F` | 1 | **deliberately blank** — the block HW1 draws; keep it empty | reserved |
| `$10`–`$14` | 5 | muzzle flash, one per attitude | **wired** |
| `$15` | 1 | old power-up — obsolete, superseded by `$53` | — |
| `$16`–`$1D` | 8 | player death fireball | **wired** |
| `$1E`–`$21` | 4 | Orbital Dropper | **wired** |
| `$22`–`$25` | 4 | placeholder boss | **wired** |
| `$26` | 1 | hostile projectile | **wired** |
| `$27`–`$2A` | 4 | Square | **wired** |
| `$2B`–`$33` | 9 | old Alleykat explosion | — |
| `$34`–`$36` | 3 | modded Alleykat A | — |
| `$37`–`$3A` | 4 | unmodified Alleykat (reference) | — |
| `$3B`–`$3D` | 3 | modded Alleykat B | — |
| `$3E`–`$40` | 3 | `ring_1` | — |
| `$41`–`$43` | 3 | `ring_2` | — |
| `$44`–`$49` | 6 | `spinner` | — |
| `$4A`–`$4B` | 2 | Hades A (reference) | — |
| `$4C`–`$4F` | 4 | Hades B (reference) | — |
| `$50`–`$52` | 3 | space mine | — |
| `$53` | 1 | shaded power-up — the token the game draws | **wired** |
| `$54`–`$59` | 6 | spinny thing | — |
| `$5A`–`$5F` | 6 | space whisk | — |
| `$60`–`$67` | 8 | `ring_3` — 8-step rotation | **wired, 4 of 8** |
| `$68`–`$6C` | 5 | spinny rotatey thing | — |
| `$6D` | 1 | unused trailing slot | reserved |

**The mapping lives in exactly one place**: the `GROUPS` table in
`tools/sprite_export/import_spd.py`. Each entry lists the SpritePad indices it
emits, in order, and every generated file names those indices in its own banner.
Nothing renumbers anything anywhere else.

Two entries are not a plain range, and both are deliberate:

* the **token** comes from `$53`, not from `$15`. `$15` is the retired power-up;
* the **Ring** comes from `$60, $62, $64, $66` — every *second* frame of
  `ring_3`. A species gets `ENEMY_FRAMES = 4` blocks and `ring_3` is an 8-step
  rotation, so sampling alternate frames shows a complete turn where the first
  four would show a quarter turn and snap back.

**Adding a species is not just artwork.** The engine has `SPECIES_COUNT = 3` and
`ENEMY_FRAMES = 4`, both guarded, and a level's enemy window is 20 blocks of
which 12 are claimed. Promoting any of the unwired sequences above needs engine
work, not an importer change — see `/reports/sprite-set-v2-import.md`.

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
