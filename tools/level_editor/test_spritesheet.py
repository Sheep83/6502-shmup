#!/usr/bin/env python3
"""Source-spritesheet slicing (task section 13 / 31).

Run:  python3 tools/level_editor/test_spritesheet.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from spritesheet import slice_sheet                                 # noqa: E402

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


FIXTURE = HERE / "testdata" / "synthetic_tileset.png"
if not FIXTURE.exists():
    subprocess.run([sys.executable, str(HERE / "make_test_spritesheet.py")], check=True)


# 1. 32x32 slicing: expected rows/cols and tile count
sheet = slice_sheet(FIXTURE, 32, 32)
assert (sheet.cols_count, sheet.rows_count) == (12, 10), (sheet.cols_count, sheet.rows_count)
assert sheet.tile_count == 120
assert sheet.warnings == []
ok("32x32 slicing: 12x10 = 120 tiles, no warnings")

# 2. a selected tile's pixels are correct (top-left flat tile is RAMP[0])
tile0 = sheet.tile(0)
assert len(tile0) == 32 and all(len(r) == 32 for r in tile0)
assert tile0[0][0] == (16, 16, 24), tile0[0][0]
# flat tile -> every pixel identical
assert all(px == (16, 16, 24) for row in tile0 for px in row)
# tile at grid (1,0) is index 1 -> horizontal stripes: row 0 vs row 4 differ
tile1 = sheet.tile_rc(1, 0)
assert tile1[0][0] != tile1[4][0]
assert sheet.tile_coords(13) == (1, 1)
ok("selected tile pixels + grid<->index mapping correct")

# 3. configurable tile size
sheet16 = slice_sheet(FIXTURE, 16, 16)
assert (sheet16.cols_count, sheet16.rows_count) == (24, 20)
assert sheet16.tile_count == 480
ok("configurable tile size: 16x16 -> 24x20 tiles")

# 4. non-divisible sizes are WARNED, not silently cropped
sheet_odd = slice_sheet(FIXTURE, 30, 30)          # 384/30 = 12 r12 ; 320/30 = 10 r20
assert sheet_odd.cols_count == 12 and sheet_odd.rows_count == 10
assert any("not a multiple of tile width" in w for w in sheet_odd.warnings)
assert any("not a multiple of tile height" in w for w in sheet_odd.warnings)
# every emitted tile is still full size (no short/cropped tiles)
last = sheet_odd.tile(sheet_odd.tile_count - 1)
assert len(last) == 30 and all(len(r) == 30 for r in last)
ok("non-divisible tile size: leftover strip warned, emitted tiles never cropped")

# 5. a tile larger than the image is a clean error, not a crash
raised = False
try:
    slice_sheet(FIXTURE, 4096, 4096)
except ValueError:
    raised = True
assert raised
ok("tile larger than the sheet raises a clean ValueError")

# 6. out-of-range tile access rejected
try:
    sheet.tile(120)
    raise AssertionError("accepted out-of-range tile index")
except IndexError:
    pass
ok("out-of-range tile index rejected")

print(f"\nAll {len(PASS)} spritesheet checks passed.")
