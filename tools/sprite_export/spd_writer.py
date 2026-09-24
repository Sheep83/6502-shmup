#!/usr/bin/env python3
"""Write SpritePad 2.0 (.spd).

THE FORMAT, established from Spritemate's own source rather than guessed --
Spritemate is the editor these files are being produced for, and its writer is
the thing that defines what it will read back. src/js/Save.ts carries the
layout as a comment and then emits exactly it:

    // bytes 00,01,02 = "SPD"
    // byte 03 = version number of spritepad
    // byte 04 = number of sprites
    // byte 05 = number of animations
    // byte 06 = color transparent
    // byte 07 = color multicolor 1
    // byte 08 = color multicolor 2
    // byte 09 = start of sprite data
    // byte 73 = 0-3 color, 4 overlay, 7 multicolor/singlecolor
    // bytes xx = "00", "00", "01", "00" added at the end of file

    data.push(83, 80, 68);                              // "SPD"
    data.push(1, this.savedata.sprites.length - 1, 0);  // version, count-1, anims
    ...
    data.push(0, 0, 1, 0);   // SpritePad animation info (currently unused)

and src/js/Load.ts reads it back with `start_of_sprite_data = 6`,
`number_of_sprites = file[4] + 1`, the three shared colours at 6/7/8, sprite n's
bitmap at 9 + 64n and its metadata byte at 9 + 64n + 63.

VERIFIED AGAINST REAL FILES. The three .spd files shipped in spritemate's
examples/ directory all satisfy

    len == 9 + 64 * sprites + 4 + animations * 4

exactly (Antiriad 162 sprites / 26 animations / 10485 bytes, Armalyte 122 / 16 /
7885, Io 103 / 18 / 6677), which is what pins the trailing section down: a
four-byte preamble plus four bytes per animation. We write zero animations, so
the tail is the four bytes Spritemate itself writes.

1.8 vs 2.0: the old format has NO "SPD" magic at all -- it is three colour bytes
followed by N 64-byte blocks, and the count is inferred as (len - 3) / 64.
Spritemate distinguishes them with `file.startsWith("SPD")`. 2.0 is written here
because it carries an explicit count and version, and Spritemate reads both.
"""
from __future__ import annotations

MAGIC = b"SPD"
VERSION = 1                     # SpritePad 2.0
HEADER_LEN = 6                  # magic(3) + version + count-1 + animations
COLOURS_LEN = 3                 # transparent, multicolour 1, multicolour 2
DATA_START = HEADER_LEN + COLOURS_LEN       # 9
BLOCK = 64
BITMAP = 63
ANIMATION_TAIL = bytes((0, 0, 1, 0))
MAX_SPRITES = 256               # count is one byte, stored as count - 1


class SpdWriteError(ValueError):
    """Refused rather than emitting a file that cannot mean what was asked."""


def _check_colour(value, what):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 15:
        raise SpdWriteError(f"{what} must be a C64 colour 0..15; got {value!r}")


def metadata_byte(multicolour, colour, overlay=False):
    """bit 7 multicolour, bit 4 overlay, bits 0-3 the sprite's own colour."""
    _check_colour(colour, "sprite colour")
    return (0x80 if multicolour else 0) | (0x10 if overlay else 0) | (colour & 0x0F)


def build(sprites, *, background, multicolour1, multicolour2):
    """Serialise to bytes.

    `sprites` is any sequence of objects carrying .bitmap (63 bytes),
    .multicolour and .colour -- the extractor's Sprite satisfies it, and so does
    anything a test builds by hand.
    """
    if not sprites:
        raise SpdWriteError("a SpritePad file needs at least one sprite")
    if len(sprites) > MAX_SPRITES:
        raise SpdWriteError(
            f"{len(sprites)} sprites; the count is one byte so at most "
            f"{MAX_SPRITES} fit in a SpritePad 2.0 file")
    for name, v in (("background", background), ("multicolour1", multicolour1),
                    ("multicolour2", multicolour2)):
        _check_colour(v, name)

    out = bytearray()
    out += MAGIC
    out.append(VERSION)
    out.append(len(sprites) - 1)        # STORED MINUS ONE; 0 means one sprite
    out.append(0)                       # animations: none
    out += bytes((background, multicolour1, multicolour2))

    for i, s in enumerate(sprites):
        bitmap = bytes(s.bitmap)
        if len(bitmap) != BITMAP:
            raise SpdWriteError(
                f"sprite {i} has {len(bitmap)} bitmap bytes, not {BITMAP}")
        out += bitmap
        out.append(metadata_byte(bool(s.multicolour), int(s.colour),
                                 bool(getattr(s, "overlay", False))))

    out += ANIMATION_TAIL
    expected = DATA_START + BLOCK * len(sprites) + len(ANIMATION_TAIL)
    if len(out) != expected:
        raise SpdWriteError(
            f"internal: produced {len(out)} bytes, expected {expected}")
    return bytes(out)
