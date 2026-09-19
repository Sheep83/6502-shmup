#!/usr/bin/env python3
"""Native 16x32 multicolour metatile encoding + glyph deduplication.

Plain assert script (repo tools/check_*.py style).
Run:  python3 tools/level_editor/test_native_metatile.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine_data import TERRAIN_GLYPH_BASE as GB  # noqa: E402
from native_metatile import (                                       # noqa: E402
    CELLS_PER_METATILE, GLYPH_BYTES, NATIVE_H, NATIVE_W,
    GlyphBudgetExceeded, GlyphSet, NativeMetatileError,
    blank_pixels, glyphs_to_pixels, pack_metatiles, pixels_to_glyphs,
    validate_pixels,
)

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


def fail(msg):
    print(f"FAIL - {msg}")
    sys.exit(1)


# 1. grid shape: exactly 32 rows x 16 cols, values 0..3
g = blank_pixels(0)
assert len(g) == NATIVE_H == 32 and all(len(r) == NATIVE_W == 16 for r in g)
validate_pixels(g)
for bad, why in (
    ([[0] * 16] * 31, "31 rows"),
    ([[0] * 15] * 32, "15 cols"),
    ([[0] * 16] * 33, "33 rows"),
):
    try:
        validate_pixels(bad)
        fail(f"validate_pixels accepted {why}")
    except NativeMetatileError:
        pass
for val in (-1, 4, 5, 255, True):
    grid = blank_pixels(0)
    grid[7][9] = val
    try:
        validate_pixels(grid)
        fail(f"validate_pixels accepted pixel value {val!r}")
    except NativeMetatileError:
        pass
ok("native grid: 32x16 enforced; pixel values outside 0..3 rejected")

# 2. each 4x8 logical cell -> exactly 8 bytes; known bit-pair patterns
grid = blank_pixels(0)
# char (0,0) row 0 = pixels [1,2,3,0] -> (01 10 11 00) = 0b01101100 = 0x6C
grid[0][0], grid[0][1], grid[0][2], grid[0][3] = 1, 2, 3, 0
# char (3,3) last row all 3 -> 0b11111111 = 0xFF
for x in range(12, 16):
    grid[31][x] = 3
glyphs = pixels_to_glyphs(grid)
assert len(glyphs) == CELLS_PER_METATILE == 16
assert all(len(gl) == GLYPH_BYTES == 8 for gl in glyphs)
assert glyphs[0][0] == 0x6C, hex(glyphs[0][0])
assert glyphs[15][7] == 0xFF, hex(glyphs[15][7])
assert glyphs[15][0] == 0x00
# cell ordering is reading order: cell index = cr*4 + cc
grid2 = blank_pixels(0)
grid2[8][4] = 2                     # char (cr=1, cc=1), local (0,0)
g2 = pixels_to_glyphs(grid2)
assert g2[1 * 4 + 1][0] == (2 << 6), g2[5][0]
ok("decompose: 16 cells x 8 bytes, reading order, exact 2-bit-pair packing")

# 3. round-trip glyphs<->pixels is lossless
import random                                                       # noqa: E402
random.seed(19656)
rnd = [[random.randint(0, 3) for _ in range(16)] for _ in range(32)]
assert glyphs_to_pixels(pixels_to_glyphs(rnd)) == validate_pixels(rnd)
ok("glyphs_to_pixels(pixels_to_glyphs(x)) == x  (lossless)")

# 4. GlyphSet dedup: identical bitmaps share an index
gs = GlyphSet(capacity=64)
a = (1, 2, 3, 4, 5, 6, 7, 8)
b = (9, 9, 9, 9, 9, 9, 9, 9)
idx = gs.add_glyphs([a, b, a, b, a])
assert idx == [0, 1, 0, 1, 0], idx
assert len(gs) == 2
reuse, new = gs.cost([a, b, (0,) * 8])
assert (reuse, new) == (2, 1)
ok("GlyphSet: identical 8-byte glyphs deduplicate to one index")

# 5. repeated cells inside ONE metatile reuse an ID; repeated glyphs ACROSS
#    metatiles reuse IDs; unique count is correct
flat = blank_pixels(1)                         # all 16 cells identical
packed_flat = pack_metatiles([flat])
assert packed_flat["glyphCount"] == 1, packed_flat["glyphCount"]
assert packed_flat["metatileDefs"][0] == [GB] * 16

two_same = pack_metatiles([flat, flat])
assert two_same["glyphCount"] == 1
assert two_same["metatileDefs"] == [[GB] * 16, [GB] * 16]

half = blank_pixels(1)
for y in range(NATIVE_H):
    for x in range(8, 16):
        half[y][x] = 2                          # right two char columns differ
packed_half = pack_metatiles([flat, half])
# flat needs 1 glyph; half reuses it for its left 8 cells, 1 new for its right 8
assert packed_half["glyphCount"] == 2, packed_half["glyphCount"]
assert packed_half["metatileDefs"][1].count(GB) == 8
assert packed_half["metatileDefs"][1].count(GB + 1) == 8
ok("dedup: repeats within a metatile and across metatiles both reuse glyph IDs")

# 6. > capacity unique glyphs fails cleanly (no silent drop/alias)
def all_unique_metatile(base):
    """Every one of the 16 char cells gets a distinct glyph: cell k's top row
    encodes the full byte (base+k) in its four 2-bit pixels."""
    grid = blank_pixels(0)
    for cell in range(16):
        cr, cc = divmod(cell, 4)
        code = (base + cell) & 0xFF
        for i in range(4):
            grid[cr * 8][cc * 4 + i] = (code >> (2 * (3 - i))) & 3
    return grid

five = [all_unique_metatile(b) for b in range(0, 80, 16)]   # 80 distinct glyphs
# 4 of them (64 glyphs) pack fine:
assert pack_metatiles(five[:4], capacity=64)["glyphCount"] == 64
raised = False
try:
    pack_metatiles(five, capacity=64)                        # 80 > 64
except GlyphBudgetExceeded as exc:
    raised = True
    assert exc.capacity == 64 and exc.needed >= 1
assert raised, "pack_metatiles did not reject > 64 unique glyphs"
ok("budget: > 64 unique terrain glyphs raises GlyphBudgetExceeded (no silent alias)")

# 7. deterministic: same input -> byte-identical packing
p1 = pack_metatiles([half, flat, half])
p2 = pack_metatiles([half, flat, half])
assert p1 == p2
ok("pack_metatiles is deterministic")

print(f"\nAll {len(PASS)} native-metatile checks passed.")
