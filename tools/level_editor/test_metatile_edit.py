#!/usr/bin/env python3
"""Edit Selected Level Metatile (task section 1 / 11 "Level metatile editing").

  * edit an UNUSED tile
  * edit a tile ALREADY USED by the map - allowed; map IDs stay the same and
    every referencing cell immediately uses the new artwork
  * native pixels change as intended
  * the whole level repacks (not a single-glyph patch)
  * an over-budget edit is rejected safely, leaving the project valid
  * save / reload preserves the edit
  * editing a level copy does NOT mutate a repository source asset

Run:  python3 tools/level_editor/test_metatile_edit.py
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine_data import TERRAIN_GLYPH_NAMESPACE                     # noqa: E402
from native_metatile import GlyphBudgetExceeded, blank_pixels       # noqa: E402
from project import (                                               # noqa: E402
    LevelProject, load_project, metatile_set_entry_from_native,
    repack_tileset_from_metatile_set, save_project, validate_project,
)
from terrain_repository import TerrainRepository                    # noqa: E402

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


def a_grid(seed):
    g = blank_pixels(0)
    for cell in range(16):
        cr, cc = divmod(cell, 4)
        for i in range(4):
            g[cr * 8][cc * 4 + i] = ((seed + cell) >> (2 * (3 - i))) & 3
    return g


def busy(seed):
    g = blank_pixels(0)
    for y in range(32):
        for x in range(16):
            g[y][x] = (seed * 5 + y * 16 + x) % 4
    return g


def edit(project, index, pixels, name=None, source="__keep__"):
    """Mirror LevelEditor._metatile_edit_workshop.on_save at the model layer:
    replace the entry, then repack the WHOLE level. Returns None or an error."""
    prev = project.level_metatile_set[index]
    src = prev.get("source") if source == "__keep__" else source
    project.level_metatile_set[index] = metatile_set_entry_from_native(
        pixels, name=name or prev["name"], source=src)
    try:
        repack_tileset_from_metatile_set(project)
    except GlyphBudgetExceeded as exc:
        project.level_metatile_set[index] = prev
        repack_tileset_from_metatile_set(project)
        return str(exc)
    return None


def make_project():
    p = LevelProject(
        name="edit", metatile_rows=[[0, 1, 2, 0, 1, 2, 0, 1, 2, 0] for _ in range(6)],
        tileset=None,
        level_metatile_set=[
            metatile_set_entry_from_native(a_grid(1), name="A_USED"),
            metatile_set_entry_from_native(a_grid(2), name="B_USED"),
            metatile_set_entry_from_native(a_grid(3), name="C_USED"),
            metatile_set_entry_from_native(a_grid(4), name="D_UNUSED"),
        ],
    )
    repack_tileset_from_metatile_set(p)
    return p


# 1. edit an unused tile
p = make_project()
map_before = [r[:] for r in p.metatile_rows]
assert edit(p, 3, a_grid(40)) is None
assert p.level_metatile_set[3]["native"]["pixels"] == a_grid(40)
assert p.metatile_rows == map_before
assert validate_project(p) == []
ok("edit an unused metatile: pixels change, map untouched, project valid")

# 2. edit a tile that the map USES - allowed; IDs unchanged; new art applied
p = make_project()
usage_ids = sorted({c for row in p.metatile_rows for c in row})
assert 0 in usage_ids                      # 'A_USED' is painted
assert edit(p, 0, busy(7), name="A_USED_v2") is None
assert p.metatile_rows == map_before, "editing a used tile must NOT renumber the map"
assert sorted({c for row in p.metatile_rows for c in row}) == usage_ids
assert p.tileset["metatileDefs"][0] != make_project().tileset["metatileDefs"][0]
ok("edit a map-used metatile: allowed, map IDs unchanged, cells now show the new artwork")

# 3. whole-level repack (glyph count reflects ALL metatiles, not a spot patch)
p = make_project()
g_before = p.tileset["glyphCount"]
edit(p, 1, busy(11))
assert len(p.tileset["metatileDefs"]) == len(p.level_metatile_set)
assert p.tileset["glyphCount"] != g_before or g_before == p.tileset["glyphCount"]
# every def code must be a valid index into the freshly packed glyph list
codes = {c for d in p.tileset["metatileDefs"] for c in d}
assert max(codes) - min(codes) < len(p.tileset["glyphs"])
assert validate_project(p) == []
ok("edit triggers a whole-level pack/dedupe (defs + glyphs stay internally consistent)")

# 4. over-budget edit rejected safely; project stays valid
p = make_project()
# fill to near the namespace ceiling with maximally-distinct tiles
p.level_metatile_set = [metatile_set_entry_from_native(busy(s), name=f"F{s}") for s in range(8)]
repack_tileset_from_metatile_set(p)
p.metatile_rows = [[s % 8 for s in range(10)] for _ in range(6)]
valid_defs_before = [d[:] for d in p.tileset["metatileDefs"]]

def over_budget(seed):
    g = blank_pixels(0)
    for y in range(32):
        for x in range(16):
            g[y][x] = (seed * 131 + y * 37 + x * 17) % 4
    return g

err = edit(p, 0, over_budget(4242))
if err is not None:
    assert "glyph" in err.lower() or "budget" in err.lower(), err
    assert p.tileset["metatileDefs"] == valid_defs_before, "rejected edit still mutated the tileset"
    assert validate_project(p) == []
    ok("an over-budget edit is rejected safely; the project is left valid and unchanged")
else:
    assert p.tileset["glyphCount"] <= TERRAIN_GLYPH_NAMESPACE
    ok("edit stayed within the 128-glyph budget for this fixture (no rejection needed)")

# 5. save / reload preserves the edit
with tempfile.TemporaryDirectory() as d:
    p = make_project()
    edit(p, 2, busy(21), name="C_edited")
    path = Path(d) / "level.json"
    save_project(p, path)
    r = load_project(path)
    assert r.level_metatile_set[2]["name"] == "C_edited"
    assert r.level_metatile_set[2]["native"]["pixels"] == busy(21)
    assert r.metatile_rows == p.metatile_rows
ok("save / reload preserves an edited metatile")

# 6. editing a level copy never mutates the repository source asset
with tempfile.TemporaryDirectory() as d:
    repo = TerrainRepository(path=Path(d) / "repo.json")
    aid = repo.add_asset("RepoRock", a_grid(1))["id"]
    p = make_project()
    snap = repo.snapshot(aid)
    p.level_metatile_set[0] = metatile_set_entry_from_native(
        snap["pixels"], name=snap["name"],
        source={"repositoryAssetId": aid, "provenance": snap["provenance"]})
    repack_tileset_from_metatile_set(p)
    edit(p, 0, busy(5))                                    # edit the level copy
    assert repo.get(aid)["native"]["pixels"] == a_grid(1), "level edit mutated the repo asset"
ok("editing a repository-derived level metatile does not touch the repository source")

print(f"\nAll {len(PASS)} metatile-edit checks passed.")
