#!/usr/bin/env python3
"""Headless regression tests for editor turret placement + bottom-origin data.

Plain assert script (no pytest), matching the repo's tools/check_*.py style.
Run:  python3 tools/level_editor/test_turret_integration.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from engine_data import TERRAIN_GLYPH_BASE, TURRET_POOL, load_engine_data  # noqa: E402
from ka_export import render_stage_turrets, export_project               # noqa: E402
from project import (                                                    # noqa: E402
    MAX_TURRETS, LevelProject, export_readiness_errors, iter_turrets,
    load_project, project_from_dict, save_project,
    turret_world_col, turret_world_row, validate_project,
)

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


def fail(msg):
    print(f"FAIL - {msg}")
    sys.exit(1)


def _baseline_tileset():
    d = load_engine_data(REPO)
    return {"glyphCount": d.glyph_count,
            "glyphs": [list(d.glyphs[TERRAIN_GLYPH_BASE + i]) for i in range(d.glyph_count)],
            "metatileDefs": [list(m) for m in d.metatiles]}


def _project(rows=100, turrets=((30, 3), (70, 7), (89, 4)), **kw):
    return LevelProject(
        name=kw.get("name", "t"),
        metatile_rows=[[0] * 10 for _ in range(rows)],
        palette={"background": 0, "multicolour1": 11, "multicolour2": 14, "character": 1},
        scroll_frame_divider=2,
        objects=[{"type": "turret", "metatileRow": r, "metatileCol": c} for r, c in turrets],
        tileset=_baseline_tileset(),
    )


# 1. coordinate model: metatile grid -> world char row/col = idx*4 + 1
assert turret_world_row(0) == 1 and turret_world_row(89) == 357
assert turret_world_col(0) == 1 and turret_world_col(7) == 29
ok("coordinate model: world = metatile_index * 4 + 1")

# 2. widened vertical coordinate - no 8-bit limit; export sorts DESCENDING by row
big = _project(rows=768, turrets=((0, 0), (200, 5), (700, 9)))
assert validate_project(big) == [], validate_project(big)
rows = sorted((turret_world_row(t["metatileRow"]) for t in iter_turrets(big)), reverse=True)
assert rows == [2801, 801, 1] and max(rows) > 255
asm = render_stage_turrets(big)
assert "turretRows = List().add(2801, 801, 1)" in asm, asm
assert ".const TURRET_TOTAL = 3" in asm
ok("widened turret vertical coordinate: world rows up to 2801 (>255), 16-bit, desc-sorted")

# 3. JSON persistence: save -> reload -> identical, and deterministic bytes
p = _project()
with tempfile.TemporaryDirectory() as d:
    a, b = Path(d) / "a.json", Path(d) / "b.json"
    save_project(p, a)
    p2 = load_project(a)
    assert p.canonical_objects() == p2.canonical_objects()
    save_project(p2, b)
    assert a.read_text() == b.read_text(), "save is not deterministic"
    data = json.loads(a.read_text())
    assert data["objects"] == [
        {"type": "turret", "metatileRow": 30, "metatileCol": 3},
        {"type": "turret", "metatileRow": 70, "metatileCol": 7},
        {"type": "turret", "metatileRow": 89, "metatileCol": 4},
    ], data["objects"]
ok("turret JSON persistence: save/reload exact + byte-deterministic")

# 4. export is deterministic and INDEPENDENT of authoring order
p_shuffled = _project(turrets=((89, 4), (30, 3), (70, 7)))
assert render_stage_turrets(p) == render_stage_turrets(p_shuffled), "export depends on order"
assert render_stage_turrets(p).splitlines()[-3:] == [
    ".const TURRET_TOTAL = 3",
    ".var turretCols = List().add(17, 29, 13)",   # world cols in desc-row order
    ".var turretRows = List().add(357, 281, 121)",
]
ok("turret ASM export: deterministic + authoring-order-independent (desc by world row)")

# 5. backward compat: V2 file with no/empty 'objects' still loads (tileset migrated)
legacy = {
    "formatVersion": 2, "name": "legacy", "width": 10, "height": 30,
    "scrollFrameDivider": 2,
    "palette": {"background": 0, "multicolour1": 11, "multicolour2": 14, "character": 1},
    "metatileRows": [[0] * 10 for _ in range(30)],
}
lp = project_from_dict(legacy, default_tileset=_baseline_tileset())
assert lp.objects == []
assert lp.tileset is not None
assert validate_project(lp) == []                     # structurally fine
assert export_readiness_errors(lp) == []              # 0 turrets is now export-ready
legacy_v1 = dict(legacy, formatVersion=1)
legacy_v1.pop("palette"); legacy_v1.pop("scrollFrameDivider")
assert project_from_dict(legacy_v1, default_tileset=_baseline_tileset()).objects == []
ok("backward compat: V1/V2 levels with absent/empty 'objects' load (tileset migrated)")

# 6. impossible placements rejected
dup = _project(turrets=((5, 3), (5, 7)))
assert any("distinct metatile row" in e for e in validate_project(dup))
bad_type = _project()
bad_type.objects.append({"type": "boss", "metatileRow": 1, "metatileCol": 1})
assert any("not supported" in e for e in validate_project(bad_type))
oob = _project(turrets=((30, 3), (70, 7), (500, 4)))   # row 500 > height 100
assert any("metatileRow" in e for e in validate_project(oob))
ok("impossible placements rejected (dup row / bad type / out of range)")

# 7. round-trip through the real generated file the engine consumes
d = load_engine_data(REPO)
gen_project = LevelProject(
    name="from-generated", metatile_rows=[r[:] for r in d.stage_rows],
    palette=dict(d.source_palette), scroll_frame_divider=d.source_scroll_frame_divider,
    objects=[dict(t) for t in d.source_turrets], tileset=_baseline_tileset(),
)
assert validate_project(gen_project) == [], validate_project(gen_project)
assert export_readiness_errors(gen_project) == []
turret_rows = [turret_world_row(t["metatileRow"]) for t in iter_turrets(gen_project)]
assert any(r > 255 for r in turret_rows), turret_rows
ok(f"engine_data reads generated placement: {len(d.source_turrets)} turrets, "
   f"world rows {sorted(turret_rows)} (has >255)")

# 8. export_project (legacy 3-file) still writes exactly the config/stage/turret files
with tempfile.TemporaryDirectory() as td:
    paths = export_project(_project(), d.metatiles, td)
    names = sorted(p.name for p in paths)
    assert names == ["stage_config.asm", "stage_map.asm", "stage_turrets.asm"], names
ok("export_project writes stage_config.asm + stage_map.asm + stage_turrets.asm")

print(f"\nAll {len(PASS)} turret-integration checks passed. (TURRET_POOL={TURRET_POOL}, MAX_TURRETS={MAX_TURRETS})")
