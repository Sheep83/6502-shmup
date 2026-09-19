#!/usr/bin/env python3
"""Regression tests for the editor-only gameplay-viewport overlay coordinate model.

The overlay mirrors the real C64 terrain aperture: 40 chars wide, VIEWPORT_ROWS
(23) logical rows tall (matrix row 0 is the fixed HUD; row 24 never reaches the
RSEL=0 aperture). Bottom-origin: the default view is the last 23 logical rows -
matrix row 23 shows the authored last row at boot. The overlay never wraps and
is always clamped inside the level.

Run:  python3 tools/level_editor/test_viewport_model.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine_data import METATILE_H, VIEWPORT_COLS, VIEWPORT_ROWS           # noqa: E402
from project import (                                                      # noqa: E402
    LevelProject, clamp_viewport_top, default_viewport_top, max_viewport_top,
    stage_logical_rows, viewport_logical_range, viewport_metatile_range,
)

PASS = []


def ok(m):
    PASS.append(m)
    print(f"ok  - {m}")


def prj(rows):
    return LevelProject(name="v", metatile_rows=[[0] * 10 for _ in range(rows)])


assert (VIEWPORT_COLS, VIEWPORT_ROWS) == (40, 23)
ok("aperture geometry: 40 cols x 23 logical rows (fixed HUD row + off-screen row excluded)")

p100 = prj(100)                       # 400 logical rows
assert stage_logical_rows(p100) == 400
assert max_viewport_top(p100) == 400 - 23 == 377
assert default_viewport_top(p100) == 377         # bottom-origin boot view
lo, hi = viewport_logical_range(default_viewport_top(p100))
assert (lo, hi) == (377, 399)                     # shows the authored LAST rows -> gameplay start
ok("bottom-origin default: view = logical rows [SLR-23 .. SLR-1] = [377..399]")

# clamp: never outside [0, SLR-23], never wraps
assert clamp_viewport_top(-10, p100) == 0
assert clamp_viewport_top(999, p100) == 377
assert clamp_viewport_top(200, p100) == 200
lo, hi = viewport_logical_range(377)
assert hi < stage_logical_rows(p100)             # no wrap past the end
ok("viewport top clamped to [0, SLR-23]; range never wraps past the level end")

# metatile-row mapping: logical row L -> metatile row L // METATILE_H
first_mt, last_mt = viewport_metatile_range(200)
assert first_mt == 200 // METATILE_H == 50
assert last_mt == (200 + 22) // METATILE_H == 55
ok("viewport maps to metatile rows [top//4 .. (top+22)//4] for turret/object overlap")

# a tiny level: the whole stage fits in one screen, top pinned at 0
tiny = prj(6)                                     # 24 logical rows
assert max_viewport_top(tiny) == max(0, 24 - 23) == 1
assert clamp_viewport_top(5, tiny) == 1
ok("tiny level (24 logical rows): viewport top clamped to 0..1, still valid")

# level shrink: an out-of-range top is pulled back in
big = prj(300)                                    # 1200 logical rows
top = default_viewport_top(big)                   # 1177
small = prj(40)                                   # 160 logical rows
assert clamp_viewport_top(top, small) == 160 - 23 == 137
ok("switching to a shorter level re-clamps the viewport top into range")

print(f"\nAll {len(PASS)} viewport-model checks passed.")
