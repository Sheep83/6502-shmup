#!/usr/bin/env python3
"""Deleting an unused metatile from a level's metatile set (objective 2).

Removing metatile `k` must:
  * be refused if any map cell still references `k`;
  * otherwise drop set entry `k`, shift later entries down by one, and
    decrement every map cell whose ID was > k, so the painted map is
    logically/visually identical;
  * touch nothing else (turrets store grid positions, waves store world rows -
    never scenery metatile IDs).

Run:  python3 tools/level_editor/test_metatile_delete.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from native_metatile import blank_pixels                            # noqa: E402
from ka_export import export_level                                  # noqa: E402
from engine_data import load_engine_data                            # noqa: E402
from project import (                                               # noqa: E402
    LevelProject, MetatileInUseError, metatile_id_usage,
    metatile_set_entry_from_native, project_from_dict, remove_metatile,
    repack_tileset_from_metatile_set, save_project, validate_project,
)

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


def _native(seed):
    """A metatile whose 16 cells encode `seed` (distinct art per metatile)."""
    g = blank_pixels(0)
    for cell in range(16):
        cr, cc = divmod(cell, 4)
        v = ((seed + cell) % 3) + 1
        for i in range(4):
            g[cr * 8][cc * 4 + i] = v if (i + cell) % 2 else 0
    return g


def _project(n_metatiles, rows):
    """rows: list of 10-int metatile-ID rows."""
    p = LevelProject(
        name="del", metatile_rows=[list(r) for r in rows],
        palette={"background": 0, "multicolour1": 11, "multicolour2": 14, "character": 1},
        scroll_frame_divider=2,
        level_metatile_set=[metatile_set_entry_from_native(_native(k), name=f"M{k}")
                            for k in range(n_metatiles)],
    )
    repack_tileset_from_metatile_set(p)
    return p


def _map_render(p):
    """A base-independent fingerprint of what each map cell draws: the native
    pixels of the metatile it points at."""
    s = p.level_metatile_set
    return [[tuple(map(tuple, s[c]["native"]["pixels"])) for c in row]
            for row in p.metatile_rows]


# --- 1. delete the END (highest) unused metatile ---------------------------
p = _project(8, [[0, 1, 2, 3, 0, 1, 2, 3, 0, 1] for _ in range(6)])   # uses 0..3
render_before = _map_render(p)
names_before = [e["name"] for e in p.level_metatile_set]
removed = remove_metatile(p, 7)
assert removed["name"] == "M7"
assert [e["name"] for e in p.level_metatile_set] == names_before[:7]
assert p.metatile_rows == [[0, 1, 2, 3, 0, 1, 2, 3, 0, 1] for _ in range(6)]  # unchanged (no cell > 7)
assert _map_render(p) == render_before
repack_tileset_from_metatile_set(p)
assert validate_project(p) == []
ok("delete END unused metatile: entry dropped, map unchanged")

# --- 2. delete a MIDDLE unused metatile -> higher IDs renumber -------------
p = _project(8, [[0, 2, 4, 6, 7, 5, 3, 1, 0, 2] for _ in range(5)])   # uses 0..7 except... uses all
# repaint so metatile 3 becomes unused, keep 0,1,2,4,5,6,7 in use
p.metatile_rows = [[0, 1, 2, 4, 5, 6, 7, 2, 1, 0] for _ in range(5)]
assert metatile_id_usage(p).get(3, 0) == 0
render_before = _map_render(p)
names_before = [e["name"] for e in p.level_metatile_set]
remove_metatile(p, 3)
assert [e["name"] for e in p.level_metatile_set] == names_before[:3] + names_before[4:]  # M3 gone
# every cell that was > 3 is now one lower; <= 3 unchanged (3 itself was unused)
assert p.metatile_rows == [[0, 1, 2, 3, 4, 5, 6, 2, 1, 0] for _ in range(5)]
assert _map_render(p) == render_before, "visible map changed after middle delete"
repack_tileset_from_metatile_set(p)
assert validate_project(p) == []
ok("delete MIDDLE unused metatile: IDs > k renumber down, rendered map identical")

# --- 3. delete the metatile IMMEDIATELY BELOW the highest used ID ----------
p = _project(6, [[5, 5, 5, 5, 5, 5, 5, 5, 5, 5] for _ in range(4)])   # only 5 is used
render_before = _map_render(p)
assert metatile_id_usage(p) == {5: 40}
remove_metatile(p, 4)                     # 4 is unused, sits just below used 5
assert len(p.level_metatile_set) == 5
assert p.metatile_rows == [[4] * 10 for _ in range(4)]     # 5 -> 4
assert _map_render(p) == render_before
repack_tileset_from_metatile_set(p)
assert validate_project(p) == []
ok("delete unused metatile just below the highest USED id: map renumbers, unchanged")

# --- 4. a metatile the map still uses is REFUSED --------------------------
p = _project(6, [[0, 1, 2, 3, 4, 5, 0, 1, 2, 3] for _ in range(3)])
raised = False
try:
    remove_metatile(p, 2)
except MetatileInUseError as exc:
    raised = True
    assert "used by" in str(exc) and "Repaint" in str(exc)
assert raised, "remove_metatile deleted a metatile the map references"
assert len(p.level_metatile_set) == 6 and metatile_id_usage(p).get(2, 0) == 6
ok("delete a USED metatile is refused with a clear message; nothing changed")

# --- 5. turrets / wave triggers are untouched ---------------------------
p = _project(8, [[0, 1, 2, 4, 5, 6, 7, 0, 1, 2] for _ in range(20)])
p.objects = [{"type": "turret", "metatileRow": 3, "metatileCol": 6},
             {"type": "turret", "metatileRow": 11, "metatileCol": 2}]
p.wave_definitions = [{"id": "w", "name": "w", "attackId": 0,
                       "composition": [{"enemyType": 0, "count": 3}], "spawnInterval": None}]
p.wave_triggers = [{"id": "t1", "worldRow": 40, "waveDef": "w"}]
obj_before = [dict(o) for o in p.objects]
trig_before = [dict(t) for t in p.wave_triggers]
remove_metatile(p, 3)                     # 3 is unused
assert p.objects == obj_before, "turret data changed by a metatile delete"
assert p.wave_triggers == trig_before, "wave trigger data changed by a metatile delete"
ok("metatile delete leaves turret grid positions and wave-trigger world rows untouched")

# --- 6. save / reload / export deterministic after a delete --------------
p = _project(10, [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9] for _ in range(8)])
p.metatile_rows = [[0, 1, 2, 4, 5, 6, 7, 8, 9, 0] for _ in range(8)]   # 3 unused
remove_metatile(p, 3)
repack_tileset_from_metatile_set(p)
eng = load_engine_data(HERE.parent.parent)
with tempfile.TemporaryDirectory() as d:
    a, b = Path(d) / "a.json", Path(d) / "b.json"
    save_project(p, a)
    p2 = project_from_dict(json.loads(a.read_text()))
    save_project(p2, b)
    assert a.read_text() == b.read_text(), "save after delete is not deterministic"
    g1, g2 = Path(d) / "g1", Path(d) / "g2"
    export_level(p2, g1, engine_data=eng)
    export_level(project_from_dict(json.loads(b.read_text())), g2, engine_data=eng)
    for fn in ("stage_map.asm", "stage_charset.asm", "stage_config.asm"):
        assert (g1 / fn).read_text() == (g2 / fn).read_text(), f"{fn} export not deterministic"
ok("save / reload / export are deterministic after a metatile delete")

# --- 7. cannot delete the last remaining metatile ----------------------
p = _project(1, [[0] * 10 for _ in range(3)])
raised = False
try:
    remove_metatile(p, 0)
except Exception:
    raised = True
assert raised and len(p.level_metatile_set) == 1
ok("deleting the last remaining metatile is refused")

print(f"\nAll {len(PASS)} metatile-delete checks passed.")
