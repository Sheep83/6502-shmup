#!/usr/bin/env python3
"""Read SpritePad (.spd) back, independently of the writer.

Two container versions are understood: version byte 1 (SpritePad 2.0) and
version byte 5 (the format Spritemate writes now). The SPRITE BLOCK is identical
in both -- 63 bitmap bytes then one metadata byte -- so everything downstream of
this file is unchanged; only the header and the trailer differ.

THIS FILE DELIBERATELY IMPORTS NOTHING FROM spd_writer. Its offsets, its
constants and its length arithmetic are written out again from the format
description, so that "the file we wrote reads back correctly" is a real claim
rather than one serialiser agreeing with itself. If the two disagree, one of
them is wrong and the verification will say so -- which is the entire point.

The description it is written from is the same one spd_writer cites: the layout
comment and emitting code in spritemate's src/js/Save.ts, the parser in
src/js/Load.ts, and the three example .spd files in that repository, all of
which satisfy len == 9 + 64*sprites + 4 + 4*animations.

It parses strictly. Anything that does not match the format is an error rather
than a best guess, because a reader that shrugs cannot verify anything.
"""
from __future__ import annotations

from dataclasses import dataclass


class SpdReadError(ValueError):
    """The bytes are not a SpritePad 2.0 file."""


@dataclass(frozen=True)
class SpdSprite:
    index: int
    bitmap: bytes
    multicolour: bool
    overlay: bool
    colour: int
    metadata: int


@dataclass(frozen=True)
class SpdFile:
    version: int
    background: int
    multicolour1: int
    multicolour2: int
    animations: int
    sprites: tuple
    total_length: int


def parse(data):
    """Strict SpritePad 2.0 parse. Raises SpdReadError on anything unexpected."""
    if not isinstance(data, (bytes, bytearray)):
        raise SpdReadError("expected bytes")
    data = bytes(data)

    if len(data) < 10:
        raise SpdReadError(
            f"file is {len(data)} bytes; a SpritePad 2.0 file with one sprite "
            f"is at least 77")
    if data[0:3] != b"SPD":
        raise SpdReadError(
            f"missing the SPD signature: first three bytes are {data[0:3]!r}. "
            f"A SpritePad 1.8 file has no signature at all")

    version = data[3]
    if version not in (1, 5):
        raise SpdReadError(f"unsupported SpritePad version byte {version}")

    if version == 5:
        return _parse_v5(data)

    sprite_count = data[4] + 1          # stored minus one
    animations = data[5]
    background, mc1, mc2 = data[6], data[7], data[8]
    for label, value in (("background", background),
                         ("multicolour1", mc1), ("multicolour2", mc2)):
        if not 0 <= value <= 15:
            raise SpdReadError(f"{label} is {value}, not a C64 colour 0..15")

    # Length is fully determined, so check it before trusting any offset.
    body_start = 9
    body_end = body_start + 64 * sprite_count
    expected = body_end + 4 + 4 * animations
    if len(data) != expected:
        raise SpdReadError(
            f"length {len(data)} does not match the header: {sprite_count} "
            f"sprites and {animations} animations require exactly {expected} "
            f"bytes (9 + 64*{sprite_count} + 4 + 4*{animations})")

    sprites = []
    for i in range(sprite_count):
        block = data[body_start + 64 * i: body_start + 64 * (i + 1)]
        if len(block) != 64:
            raise SpdReadError(f"sprite {i} block is truncated")
        meta = block[63]
        sprites.append(SpdSprite(
            index=i,
            bitmap=block[:63],
            multicolour=bool(meta & 0x80),
            overlay=bool(meta & 0x10),
            colour=meta & 0x0F,
            metadata=meta,
        ))

    return SpdFile(version=version, background=background, multicolour1=mc1,
                   multicolour2=mc2, animations=animations,
                   sprites=tuple(sprites), total_length=len(data))


# ---------------------------------------------------------------------------
# VERSION 5, THE FORMAT SPRITEMATE WRITES NOW
# ---------------------------------------------------------------------------
# THE OFFSETS BELOW WERE DERIVED FROM THE FILE, NOT FROM A SPECIFICATION, and
# the derivation is written down here because a reader that guessed would be
# worthless for verification. Given 19656-sprites_v2.spd (7,066 bytes):
#
#   * the 63 bitmap bytes of the PREVIOUS project's sprite 0 occur at offset 20,
#     which fixes the body start exactly -- the artwork is the same picture;
#   * scanning every candidate body offset, 20 is the only one at which every
#     64th trailing byte has bit 7 set, i.e. at which every block's metadata byte
#     says "multicolour"; that gives 110 whole blocks;
#   * 7066 - 20 - 64*110 leaves a 6-byte trailer, and it reads
#     68 00 6c 00 04 00 -- three little-endian words, 104, 108 and 4. $68..$6C
#     is precisely the five-frame "spinny rotatey thing" range, so the trailer is
#     one 6-byte ANIMATION record: first, last, speed;
#   * the word at offset 16 is 1, which is the number of those records;
#   * the word at offset 5 is 110, the sprite count, stored PLAIN here rather
#     than minus one as version 1 stores it;
#   * offsets 13, 14, 15 are 0, 11 and 1 -- the background and the two shared
#     multicolours, which are exactly the engine's own $d025 = 11 dark grey and
#     $d026 = 1 white.
#
# So  len == 20 + 64*sprites + 6*animations,  and that identity is checked
# before any offset is trusted, exactly as the version 1 path checks its own.
# A future v5 file carrying something this does not predict will fail that
# check loudly instead of being half-read.
V5_BODY = 20
V5_ANIM_RECORD = 6


def _parse_v5(data):
    if len(data) < V5_BODY + 64:
        raise SpdReadError(
            f"file is {len(data)} bytes; a version 5 file with one sprite is "
            f"at least {V5_BODY + 64}")

    sprite_count = int.from_bytes(data[5:7], "little")
    animations = int.from_bytes(data[16:18], "little")
    background, mc1, mc2 = data[13], data[14], data[15]
    for label, value in (("background", background),
                         ("multicolour1", mc1), ("multicolour2", mc2)):
        if not 0 <= value <= 15:
            raise SpdReadError(f"{label} is {value}, not a C64 colour 0..15")
    if sprite_count < 1:
        raise SpdReadError("a version 5 file claims no sprites")

    expected = V5_BODY + 64 * sprite_count + V5_ANIM_RECORD * animations
    if len(data) != expected:
        raise SpdReadError(
            f"length {len(data)} does not match the header: {sprite_count} "
            f"sprites and {animations} animations require exactly {expected} "
            f"bytes (20 + 64*{sprite_count} + 6*{animations})")

    sprites = []
    for i in range(sprite_count):
        block = data[V5_BODY + 64 * i: V5_BODY + 64 * (i + 1)]
        meta = block[63]
        sprites.append(SpdSprite(
            index=i, bitmap=block[:63], multicolour=bool(meta & 0x80),
            overlay=bool(meta & 0x10), colour=meta & 0x0F, metadata=meta))

    return SpdFile(version=5, background=background, multicolour1=mc1,
                   multicolour2=mc2, animations=animations,
                   sprites=tuple(sprites), total_length=len(data))


def read(path):
    from pathlib import Path
    return parse(Path(path).read_bytes())
