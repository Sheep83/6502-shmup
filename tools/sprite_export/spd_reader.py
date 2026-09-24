#!/usr/bin/env python3
"""Read SpritePad 2.0 (.spd) back, independently of the writer.

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
    if version != 1:
        raise SpdReadError(f"unsupported SpritePad version byte {version}")

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


def read(path):
    from pathlib import Path
    return parse(Path(path).read_bytes())
