#!/usr/bin/env python3
"""Headless smoke of the editor's Terrain Asset Workshop wiring:
metatile-set selector 16 -> 64, native editor, VIC-II 2:1 aspect display,
mirror/flip transforms + undo, persistent PNG import session, repository
rename/delete. Constructs real Tk objects but never enters a main loop.

Run:  python3 tools/level_editor/test_editor_workshop_gui.py
Skips cleanly (exit 0) if Tk cannot initialise (no display).
"""
import subprocess
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
import workshop_ui as wu                                            # noqa: E402
import project as pj                                                # noqa: E402
from engine_data import METATILE_CAPACITY, TERRAIN_GLYPH_NAMESPACE  # noqa: E402
from native_metatile import NATIVE_H, NATIVE_W, blank_pixels        # noqa: E402
from terrain_repository import TerrainRepository                    # noqa: E402

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


class _Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y


FIX = HERE / "testdata" / "synthetic_tileset.png"
if not FIX.exists():
    subprocess.run([sys.executable, str(HERE / "make_test_spritesheet.py")], check=True)

_tmp = tempfile.TemporaryDirectory()
app = ed.LevelEditor(ed.find_repo_root())
# never touch the committed repository.json in a test
app.repo_path = Path(_tmp.name) / "repo.json"
app.repository = TerrainRepository(path=app.repo_path)
try:
    # 1. boots with the committed level metatile set + a live glyph budget
    start = app._metatile_count()
    assert 16 <= start <= 64
    assert "Terrain glyphs" in app.glyph_budget_text.get()
    ok(f"editor boots with {start} metatiles and a glyph budget readout ({app.glyph_budget_text.get()})")

    # 2. New blank metatile -> +1, selectable, undoable
    app._metatile_new_blank()
    assert app._metatile_count() == start + 1 and app.selected_tile == start
    app._undo(); assert app._metatile_count() == start
    app._redo(); assert app._metatile_count() == start + 1
    ok("New metatile grows the set by one and is undo/redo-safe")

    # 3. NativeMetatileEditor: 2:1 VIC-II aspect display + accurate hit-testing
    nme = wu.NativeMetatileEditor(
        app, app.project.palette, pixels=blank_pixels(0),
        cost_fn=lambda px: pj.metatile_set_glyph_cost(app.project, candidate_pixels=px))
    assert nme.zx == 2 * nme.zy, (nme.zx, nme.zy)
    assert int(nme.canvas.cget("width")) == NATIVE_W * nme.zx
    assert int(nme.canvas.cget("height")) == NATIVE_H * nme.zy
    # a 16x32 logical tile renders as an equivalent 32x32 physical square
    assert int(nme.canvas.cget("width")) == int(nme.canvas.cget("height"))
    # hit-test maps corners back to the right logical 16x32 cells
    assert nme._cell(_Ev(NATIVE_W * nme.zx - 2, 1)) == (15, 0)
    assert nme._cell(_Ev(1, NATIVE_H * nme.zy - 2)) == (0, 31)
    assert nme._cell(_Ev(nme.zx + 1, nme.zy + 1)) == (1, 1)
    ok("native editor renders logical pixels 2:1 (16x32 -> 32x32 square); edge hit-tests correct")

    # 4. painting still lands on the intended logical cell after aspect correction
    nme._paint_start(_Ev(3 * nme.zx + 2, 7 * nme.zy + 2))   # -> cell (3, 7)
    nme._commit()
    assert nme.get_pixels()[7][3] == nme.active.get()
    ok("click-paint after aspect correction writes the intended 16x32 cell")

    # 5. Mirror Horizontal / Flip Vertical: idempotent, single undoable edit
    import random
    random.seed(19656)
    g = [[random.randint(0, 3) for _ in range(NATIVE_W)] for _ in range(NATIVE_H)]
    nme.pixels = [r[:] for r in g]
    nme.mirror_horizontal()
    assert nme.get_pixels() == [list(reversed(r)) for r in g]
    nme.mirror_horizontal()
    assert nme.get_pixels() == g, "mirror twice != identity"
    nme.flip_vertical(); nme.flip_vertical()
    assert nme.get_pixels() == g, "flip twice != identity"
    nme.mirror_horizontal()
    nme.undo()
    assert nme.get_pixels() == g, "one undo does not fully restore a mirror"
    nme.redo()
    assert nme.get_pixels() == [list(reversed(r)) for r in g]
    ok("mirror/flip are idempotent x2 and each is exactly one undoable edit")

    # 6. Workshop save appends to the level set + repacks a valid tileset
    before_count = app._metatile_count()

    def on_save(name, px):
        pj.ensure_level_metatile_set(app.project)
        app.project.level_metatile_set.append(pj.metatile_set_entry_from_native(px, name=name))
        return None if app._repack_after_metatile_edit() else "budget"

    wd = wu.WorkshopDialog(app, app.project.palette, name="ws", pixels=blank_pixels(1),
                           on_save=on_save)
    wd._save_level()
    assert app._metatile_count() == before_count + 1
    _g = len(app.project.tileset["glyphs"])
    assert _g % 8 == 0 and 0 < _g <= TERRAIN_GLYPH_NAMESPACE
    ok("Workshop 'Save to level' appends + repacks a valid tileset")

    # 7. Persistent PNG import session: pick tile A -> Workshop -> Back to Source
    #    (dialog hidden, not destroyed, not re-read) -> pick tile B
    app._metatile_import_png()
    d = app._import_dialog
    assert d is not None and d.winfo_exists()
    d._path = str(FIX); d._reslice()
    assert d.sheet.tile_count == 120
    d._pick(10)                                             # opens Workshop, hides d
    assert d.state() == "withdrawn" and d.last_index == 10
    sheet_obj = d.sheet
    app._reopen_import_session()                            # "Back to Source"
    assert app._import_dialog is d and d.sheet is sheet_obj  # same object, no re-read
    assert d.state() != "withdrawn"
    d._pick(20)
    assert d.last_index == 20 and d.state() == "withdrawn"
    app._close_import_session()
    assert app._import_dialog is None
    ok("persistent import session: pick -> Workshop -> Back to Source -> pick again, no re-read")

    # 8. Repository rename/delete never mutate a level snapshot; persisted to disk
    app.repository.add_asset("repo-tile", blank_pixels(2),
                             provenance={"sourcePack": "test"})
    app.repository.save()
    aid = app.repository.list()[0]["id"]
    snap = app.repository.snapshot(aid)
    pj.ensure_level_metatile_set(app.project)
    app.project.level_metatile_set.append(pj.metatile_set_entry_from_native(
        snap["pixels"], name="from-repo",
        source={"repositoryAssetId": aid, "provenance": snap["provenance"]}))
    lvl_before = [r[:] for r in app.project.level_metatile_set[-1]["native"]["pixels"]]
    app.repository.update_asset(aid, name="renamed")        # rename: artwork/id unchanged
    app.repository.save()
    assert app.repository.get(aid)["name"] == "renamed"
    assert app.repository.get(aid)["native"]["pixels"] == snap["pixels"]
    assert app.project.level_metatile_set[-1]["native"]["pixels"] == lvl_before
    app.repository.remove(aid)                              # delete
    app.repository.save()
    assert not app.repository.has(aid)
    assert app.project.level_metatile_set[-1]["native"]["pixels"] == lvl_before
    assert not TerrainRepository.load(app.repo_path).has(aid)   # persisted
    ok("repository rename/delete: level snapshots untouched, changes persisted")

    # 9. capacity guard: cannot exceed 64 live metatiles
    pj.ensure_level_metatile_set(app.project)
    while app._metatile_count() < 64:
        app.project.level_metatile_set.append(
            pj.metatile_set_entry_from_native(blank_pixels(0), name=f"M{app._metatile_count()}"))
    app._repack_after_metatile_edit()
    n = app._metatile_count()
    app._metatile_new_blank()
    assert app._metatile_count() == n == 64
    ok("editor refuses to add a 65th live metatile")

    print(f"\nAll {len(PASS)} editor-workshop GUI smoke checks passed.")
finally:
    app.destroy()
    _tmp.cleanup()
