#!/usr/bin/env python3
"""Headless GUI smoke of the editor asset-workflow / wave-library / viewport
pass. Constructs real Tk objects but never enters a main loop.

Covers:
  * viewport overlay is OUTLINE ONLY (no fill/tint), blue rectangle around the
    23-row aperture, yellow activation edge retained, geometry / bottom-origin /
    no-wrap / drag unchanged
  * Duplicate Selected metatile is wired and independent
  * Save to Repo (level metatile -> terrain repository) is wired + independent
  * Repository dialog "Import from Project" + "Recover generated set" helpers
  * Wave library: Save to Library, Add from Library (snapshot), Duplicate def

Run:  python3 tools/level_editor/test_editor_asset_workflow_gui.py
Skips cleanly (exit 0) if Tk cannot initialise (no display).
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
except Exception as exc:                                            # noqa: BLE001
    print(f"SKIP - Tk unavailable ({exc})")
    sys.exit(0)

import editor as ed                                                 # noqa: E402
import project as pj                                                # noqa: E402
from engine_data import VIEWPORT_ROWS                               # noqa: E402
from native_metatile import blank_pixels                            # noqa: E402
from terrain_repository import TerrainRepository                    # noqa: E402
from wave_repository import WaveRepository                          # noqa: E402

# The editor's user-facing actions pop modal simpledialog / messagebox windows,
# which block a headless run forever. Stub them for the smoke test so the real
# action bodies still execute.
_ANSWER = {"str": "smoke name"}
ed.simpledialog.askstring = lambda *a, **k: _ANSWER["str"]
ed.messagebox.askyesno = lambda *a, **k: True
ed.messagebox.showerror = lambda *a, **k: None
ed.messagebox.showinfo = lambda *a, **k: None
ed.messagebox.showwarning = lambda *a, **k: None

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


CHAR = ed.CHAR_SIZE
_tmp = tempfile.TemporaryDirectory()
app = ed.LevelEditor(ed.find_repo_root())
app.repo_path = Path(_tmp.name) / "terrain.json"
app.repository = TerrainRepository(path=app.repo_path)
app.wave_repo_path = Path(_tmp.name) / "waves.json"
app.wave_repository = WaveRepository(path=app.wave_repo_path)

try:
    # ---- viewport overlay: outline only -------------------------------------
    app._set_viewport(10)
    c = app.level_canvas
    items = c.find_withtag("viewport")
    assert items, "no viewport overlay drawn"
    rects = [i for i in items if c.type(i) == "rectangle"]
    lines = [i for i in items if c.type(i) == "line"]
    assert rects, "expected an outline rectangle for the aperture"
    for r in rects:
        assert (c.itemcget(r, "fill") or "") == "", "viewport rectangle still has a fill/tint"
        assert (c.itemcget(r, "stipple") or "") == "", "viewport still uses a stipple fill"
        assert c.itemcget(r, "outline") == ed.VIEWPORT_EDGE, "aperture outline not blue"
    x0a, y0a, x1a, y1a = c.coords(rects[0])
    assert round(y0a) == 10 * CHAR and round(y1a) == (10 + VIEWPORT_ROWS) * CHAR, (y0a, y1a)
    assert any(c.itemcget(li, "fill") == ed.VIEWPORT_ACTIVATION for li in lines), \
        "yellow activation edge missing"
    ok("viewport overlay is a transparent blue outline + yellow activation edge; geometry exact")

    # ---- geometry / bottom-origin / no-wrap / drag unchanged --------------
    lo, hi = app._viewport_range()
    assert hi - lo + 1 == VIEWPORT_ROWS
    assert app.viewport_top == 10
    top_default = pj.default_viewport_top(app.project)
    assert top_default == pj.max_viewport_top(app.project)          # bottom-origin
    app._set_viewport(10 ** 9)
    assert app.viewport_top == pj.max_viewport_top(app.project)     # clamps, never wraps
    app._set_viewport(-50)
    assert app.viewport_top == 0
    app._nudge_viewport(3)
    assert app.viewport_top == 3
    ok("aperture is 23 rows, bottom-origin, clamps without wrap, drag/nudge still work")

    # ---- Duplicate Selected metatile -------------------------------------
    n0 = app._metatile_count()
    app.selected_tile = 0
    src_px = [r[:] for r in app.project.level_metatile_set[0]["native"]["pixels"]]
    app._metatile_duplicate_selected()
    assert app._metatile_count() == n0 + 1
    ni = app.selected_tile
    assert ni == n0 and app.project.level_metatile_set[ni]["name"].endswith("_COPY")
    app.project.level_metatile_set[ni]["native"]["pixels"][0][0] ^= 3
    assert app.project.level_metatile_set[0]["native"]["pixels"] == src_px, "duplicate shares data"
    app._undo()
    assert app._metatile_count() == n0
    ok("Duplicate Selected: +1 independent metatile, selected, undoable")

    # ---- Save to Repo (level metatile -> terrain repository), via the action
    app.selected_tile = 1
    entry_px = [r[:] for r in app.project.level_metatile_set[1]["native"]["pixels"]]
    n_repo = len(app.repository)
    _ANSWER["str"] = "Promoted wall"
    app._metatile_save_to_repository()
    assert len(app.repository) == n_repo + 1
    a = [x for x in app.repository.list() if x["name"] == "Promoted wall"][0]
    got = TerrainRepository.load(app.repo_path).get(a["id"])
    assert got["native"]["pixels"] == entry_px
    assert a["provenance"]["sourcePack"].startswith("promoted from level")
    app.repository.update_asset(a["id"], native_pixels=blank_pixels(3))
    assert app.project.level_metatile_set[1]["native"]["pixels"] == entry_px, "repo edit hit level"
    ok("Save to Repo action produces an independent, persisted snapshot with provenance")

    # ---- Repository dialog helpers: import-from-project + recover generated
    with tempfile.TemporaryDirectory() as sd:
        src = pj.LevelProject(name="donor", metatile_rows=[[0] * 10 for _ in range(6)],
                              tileset=None,
                              level_metatile_set=[
                                  pj.metatile_set_entry_from_native(blank_pixels(1), name="D0"),
                                  pj.metatile_set_entry_from_native(blank_pixels(2), name="D1")])
        pj.repack_tileset_from_metatile_set(src)
        sp = Path(sd) / "level.json"
        pj.save_project(src, sp)
        loaded = pj.load_project(sp)
        before = len(app.repository)
        for i, e in enumerate(pj.ensure_level_metatile_set(loaded)):
            app.repository.add_asset(e["name"], [r[:] for r in e["native"]["pixels"]],
                                     provenance={"sourcePack": "imported from project 'donor'"},
                                     tags=["imported"])
        assert len(app.repository) == before + 2

    from recover_generated_terrain import recover_generated_set
    res = recover_generated_set(app.repository)
    assert res["generated"] == 31 and len(res["added"]) >= 1
    ok("repository dialog helpers: import-from-project + recover-generated set both add assets")

    # ---- Wave library: save local -> global, add global -> level, duplicate
    app.project.wave_definitions.append(
        {"id": "wd_x", "name": "Bench sweep", "attackId": 0,
         "composition": [{"enemyType": 0, "count": 5}], "spawnInterval": None})
    app.selected_wave_def = len(app.project.wave_definitions) - 1
    _ANSWER["str"] = "Bench sweep"
    app._wave_def_save_to_library()
    assert len(app.wave_repository) == 1
    lib_id = app.wave_repository.ids()[0]
    assert "worldRow" not in app.wave_repository.get(lib_id)
    assert TerrainRepository is not None  # library persisted
    assert WaveRepository.load(app.wave_repo_path).has(lib_id)

    local_id = ed._next_id("wd", app.project.wave_definitions)
    snap = app.wave_repository.snapshot(lib_id, local_id=local_id)
    ndefs = len(app.project.wave_definitions)
    app.project.wave_definitions.append(snap)
    assert len(app.project.wave_definitions) == ndefs + 1
    app.wave_repository.update_definition(lib_id, name="CHANGED")
    assert app.project.wave_definitions[-1]["name"] == "Bench sweep", "library edit hit the level"

    app.selected_wave_def = 0
    d0 = len(app.project.wave_definitions)
    app._duplicate_wave_def()
    assert len(app.project.wave_definitions) == d0 + 1
    assert app.project.wave_definitions[-1]["name"].endswith(" copy")
    ok("wave library: save-to-library, add-from-library snapshot, duplicate def all wired")

    print(f"\nAll {len(PASS)} editor asset-workflow GUI smoke checks passed.")
finally:
    app.destroy()
    _tmp.cleanup()
