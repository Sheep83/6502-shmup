#!/usr/bin/env python3
"""The authored turret placement, and the overlay the page generator composes.

An independent restatement of src/turrets.asm's arithmetic, parsed from the
same authored file the assembler reads. It is shared by tests/test_turrets.py
(which proves the 6502 agrees with it) and tests/test_slice_a_prime.py (whose
"every row of the displayed page holds the stage row it should" check has to
expect turret cells now that they are part of a generated page).

The rules, from src/level1/stage_turrets.asm's own generated header and from
the old repo's installTurretRow:

    world row R   , col C  ->  TL = 226   col C+1  ->  TR = 227
    world row R+1 , col C  ->  BL = 228   col C+1  ->  BR = 229
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEMENT = ROOT / "src" / "level1" / "stage_turrets.asm"

GLYPH_BASE = 226
GLYPH_SPAN = 4
BODY_W = BODY_H = 2
METATILE_H = 4
ROW_PHASE = 1                       # authored rows are metatileRow * 4 + 1


def _list(txt, name):
    m = re.search(rf"\.var\s+{name}\s*=\s*List\(\)\.add\(([^)]*)\)", txt)
    if not m:
        raise RuntimeError(f"{name} not found in {PLACEMENT}")
    return [int(v.strip()) for v in m.group(1).split(",") if v.strip()]


def authored():
    """(total, cols, rows) exactly as the level editor emitted them."""
    txt = PLACEMENT.read_text()
    m = re.search(r"\.const\s+TURRET_TOTAL\s*=\s*(\d+)", txt)
    total = int(m.group(1))
    return total, _list(txt, "turretCols"), _list(txt, "turretRows")


def cells(stage_row):
    """[(column, character code), ...] the overlay writes into `stage_row`.

    Empty for the vast majority of rows; two entries for a row that carries
    the top or the bottom half of a live turret body.
    """
    _, cols, rows = authored()
    out = []
    for col, row in zip(cols, rows):
        for half in range(BODY_H):
            if stage_row == row + half:
                code = GLYPH_BASE + half * BODY_W
                out += [(col, code), (col + 1, code + 1)]
    return out


def apply(codes, stage_row, alive=None):
    """Terrain codes for one stage row, with the turret overlay on top."""
    _, cols, rows = authored()
    out = list(codes)
    for i, (col, row) in enumerate(zip(cols, rows)):
        if alive is not None and not alive[i]:
            continue
        for half in range(BODY_H):
            if stage_row == row + half:
                code = GLYPH_BASE + half * BODY_W
                out[col] = code
                out[col + 1] = code + 1
    return out


def body_rows():
    """{stage row: (turret index, half)} for every row a body occupies."""
    _, cols, rows = authored()
    return {row + half: (i, half)
            for i, row in enumerate(rows) for half in range(BODY_H)}
