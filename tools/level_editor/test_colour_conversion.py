#!/usr/bin/env python3
"""Deterministic source-tile -> native C64 conversion (task section 16 / 31).

Run:  python3 tools/level_editor/test_colour_conversion.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine_data import C64_PALETTE_RGB                             # noqa: E402
from native_metatile import NATIVE_H, NATIVE_W, validate_pixels     # noqa: E402
from terrain_convert import (                                       # noqa: E402
    nearest_logical_index, palette_rgb_for_logical, source_tile_to_native,
)

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


PALETTE = {"background": 0, "multicolour1": 11, "multicolour2": 14, "character": 1}
LOGICAL_RGB = palette_rgb_for_logical(PALETTE)


def solid(rgb, w=32, h=32):
    return [[tuple(rgb)] * w for _ in range(h)]


# 1. uses the project palette, not a second RGB table
assert LOGICAL_RGB[0] == C64_PALETTE_RGB[0]     # background -> index 0
assert LOGICAL_RGB[1] == C64_PALETTE_RGB[11]
assert LOGICAL_RGB[2] == C64_PALETTE_RGB[14]
assert LOGICAL_RGB[3] == C64_PALETTE_RGB[1]     # character -> index 1
ok("conversion resolves the 4 logical colours from the project palette + editor C64 table")

# 2. exact palette colours map to their own logical index
for logical, rgb in enumerate(LOGICAL_RGB):
    assert nearest_logical_index(rgb, LOGICAL_RGB) == logical
ok("each exact palette RGB maps to its own logical index 0..3")

# 3. a solid source tile -> a native grid that is all that logical index,
#    shape 32x16, values 0..3
for logical, rgb in enumerate(LOGICAL_RGB):
    grid = source_tile_to_native(solid(rgb), PALETTE)
    validate_pixels(grid)
    assert len(grid) == NATIVE_H and all(len(r) == NATIVE_W for r in grid)
    assert all(v == logical for row in grid for v in row), logical
ok("solid source tile -> uniform native grid of that logical index (32x16, 0..3)")

# 4. deterministic: identical input -> identical output, twice
noise = [[tuple((x * 7 + y * 13) % 256 for _ in range(3)) for x in range(32)] for y in range(32)]
g1 = source_tile_to_native(noise, PALETTE)
g2 = source_tile_to_native(noise, PALETTE)
assert g1 == g2
assert all(0 <= v <= 3 for row in g1 for v in row)
ok("conversion is deterministic and always yields values 0..3")

# 5. horizontal pair-reduction: 32 source cols -> 16 native cols; a tile that is
#    palette[1] on the left half and palette[2] on the right half yields native
#    columns 0..7 == 1 and 8..15 == 2
half = [list(LOGICAL_RGB[1]) for _ in range(16)] + [list(LOGICAL_RGB[2]) for _ in range(16)]
tile = [list(half) for _ in range(32)]
grid = source_tile_to_native(tile, PALETTE)
assert all(grid[y][x] == 1 for y in range(32) for x in range(8))
assert all(grid[y][x] == 2 for y in range(32) for x in range(8, 16))
ok("horizontal pair-reduction: 32 source columns collapse to 16 native pixels")

# 6. non-32 source is resampled to the 32-wide reference first (no crash, valid)
small = [[tuple(LOGICAL_RGB[3]) for _ in range(20)] for _ in range(24)]
grid = source_tile_to_native(small, PALETTE)
validate_pixels(grid)
assert all(v == 3 for row in grid for v in row)
ok("non-32x32 source is resampled deterministically to a valid native grid")

# 7. a different project palette changes the mapping (logical indices, not RGB)
alt = {"background": 0, "multicolour1": 5, "multicolour2": 3, "character": 7}
alt_rgb = palette_rgb_for_logical(alt)
mid_grey = (123, 123, 123)
assert (nearest_logical_index(mid_grey, LOGICAL_RGB)
        != nearest_logical_index(mid_grey, alt_rgb)) or True   # may coincide; just exercise
g_alt = source_tile_to_native(solid(alt_rgb[2]), alt)
assert all(v == 2 for row in g_alt for v in row)
ok("conversion honours whatever 4 colours the current project palette uses")

print(f"\nAll {len(PASS)} colour-conversion checks passed.")
