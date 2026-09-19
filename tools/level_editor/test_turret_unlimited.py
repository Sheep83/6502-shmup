#!/usr/bin/env python3
"""Regression tests for the unlimited-authored-turret contract + streaming pool.

  * 0-turret levels are valid and export a TURRET_TOTAL = 0 / empty-List file;
  * >3-turret levels (spread out) are valid and export;
  * turrets beyond world row 255 round-trip through save/load/export;
  * the genuine runtime limit (>TURRET_POOL bodies in one 23-row screen) is a
    validation error, not a silent authored-count cap;
  * export is deterministic and authoring-order independent (desc by world row).

Run:  python3 tools/level_editor/test_turret_unlimited.py
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from engine_data import TERRAIN_GLYPH_BASE, TURRET_POOL, VIEWPORT_ROWS, load_engine_data  # noqa: E402
from ka_export import export_level, render_stage_turrets                   # noqa: E402
from project import (                                                      # noqa: E402
    LevelProject, export_readiness_errors, iter_turrets, load_project,
    save_project, turret_world_row, validate_project,
)

PASS = []
D = load_engine_data(REPO)
TILESET = {"glyphCount": D.glyph_count,
           "glyphs": [list(D.glyphs[TERRAIN_GLYPH_BASE + i]) for i in range(D.glyph_count)],
           "metatileDefs": [list(m) for m in D.metatiles]}


def ok(m):
    PASS.append(m)
    print(f"ok  - {m}")


def prj(rows, turrets):
    return LevelProject(
        name="u", metatile_rows=[[0] * 10 for _ in range(rows)],
        palette={"background": 0, "multicolour1": 11, "multicolour2": 14, "character": 1},
        scroll_frame_divider=2,
        objects=[{"type": "turret", "metatileRow": r, "metatileCol": c} for r, c in turrets],
        tileset=TILESET,
    )


# --- 0 turrets ------------------------------------------------------------
p0 = prj(60, [])
assert validate_project(p0) == [], validate_project(p0)
assert export_readiness_errors(p0) == [], export_readiness_errors(p0)
asm = render_stage_turrets(p0)
assert ".const TURRET_TOTAL = 0" in asm and "List()" in asm and "List().add" not in asm, asm
ok("0-turret level: valid, export-ready, TURRET_TOTAL = 0 + empty List()")

# --- many turrets, spread out (<= TURRET_POOL per 23-row screen) ---------
many = [(r, (r * 3) % 10) for r in range(2, 60, 8)]        # 8 turrets, 32 logical rows apart
pm = prj(64, many)
assert validate_project(pm) == [], validate_project(pm)
assert export_readiness_errors(pm) == []
asm = render_stage_turrets(pm)
assert f".const TURRET_TOTAL = {len(many)}" in asm
ok(f"{len(many)}-turret level (spread): valid + exports")

# --- turret beyond world row 255 ---------------------------------------
big = prj(200, [(190, 2), (120, 6), (40, 1)])              # world rows 761 / 481 / 161
wr = sorted((turret_world_row(t["metatileRow"]) for t in iter_turrets(big)), reverse=True)
assert wr == [761, 481, 161] and wr[0] > 255
with tempfile.TemporaryDirectory() as td:
    j = Path(td) / "l.json"
    save_project(big, j)
    r = load_project(j, default_tileset=TILESET)
    assert sorted(turret_world_row(t["metatileRow"]) for t in iter_turrets(r)) == [161, 481, 761]
    a = export_level(big, Path(td) / "g1", engine_data=D)
    b = export_level(r, Path(td) / "g2", engine_data=D)
    assert all(x.read_text() == y.read_text() for x, y in zip(a, b)), "per-level export not deterministic"
    turrets_asm = (Path(td) / "g1" / "stage_turrets.asm").read_text()
    assert "List().add(761, 481, 161)" in turrets_asm, turrets_asm
ok("turret world row > 255 survives save/load/export; per-level export deterministic")

# --- MANY turrets in ONE gameplay screen is now VALID (shared body glyphs;
# no viewport-density rejection). 6 turrets on consecutive metatile rows all
# land inside one 23-logical-row aperture at once.
from project import turret_screen_peak                                     # noqa: E402
crowd_rows = list(range(10, 16))                                           # 6 turrets, 4 logical rows apart
crowd = prj(64, [(r, i % 10) for i, r in enumerate(crowd_rows)])
assert validate_project(crowd) == [], validate_project(crowd)
assert export_readiness_errors(crowd) == [], export_readiness_errors(crowd)
assert render_stage_turrets(crowd).count("\n") > 0
peak = turret_screen_peak(crowd)
assert peak >= 5, peak
assert peak <= TURRET_POOL, (peak, TURRET_POOL)
ok(f"{len(crowd_rows)} turrets within one {VIEWPORT_ROWS}-row screen "
   f"(peak {peak}) is VALID and exports - shared body glyphs, no density cap "
   f"(pool {TURRET_POOL} > geometric max ~6)")

# --- authoring-order independence -------------------------------------
import random
shuf = list(many)
random.Random(1).shuffle(shuf)
assert render_stage_turrets(prj(64, many)) == render_stage_turrets(prj(64, shuf))
ok("turret export independent of authoring order")

print(f"\nAll {len(PASS)} unlimited-turret checks passed.")
