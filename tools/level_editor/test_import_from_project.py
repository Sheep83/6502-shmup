#!/usr/bin/env python3
"""Import Metatiles from Another Project into the Terrain Repository
(task section 4).

  * V4 and V5 projects, via the existing migration/loading code
  * used AND unused source metatiles (presence in levelMetatileSet is enough)
  * subset selection and "select all"
  * malformed / unsupported file -> clear error, repository untouched
  * duplicate names handled safely (new independent ids)
  * the source project file is never modified

Run:  python3 tools/level_editor/test_import_from_project.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine_data import TERRAIN_GLYPH_BASE, TERRAIN_GLYPH_BASE_LEGACY  # noqa: E402
from native_metatile import blank_pixels                            # noqa: E402
from project import (                                               # noqa: E402
    LevelProject, ProjectValidationError, ensure_level_metatile_set,
    load_project, metatile_set_entry_from_native,
    repack_tileset_from_metatile_set, save_project,
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


def import_selected(repo, src_project, indices):
    """Mirror LevelEditor._import_project_metatiles_dialog at the model layer."""
    entries = ensure_level_metatile_set(src_project)
    added = []
    for i in indices:
        e = entries[i]
        prov = {"sourcePack": f"imported from project '{src_project.name}' "
                              f"metatile {i} ({e.get('name') or f'M{i}'})"}
        added.append(repo.add_asset(e.get("name") or f"M{i}",
                                    [r[:] for r in e["native"]["pixels"]],
                                    provenance=prov, tags=["imported"])["id"])
    return added


def build_v5(path, name):
    p = LevelProject(
        name=name, metatile_rows=[[0, 1, 0, 1, 0, 1, 0, 1, 0, 1] for _ in range(6)],
        tileset=None,
        level_metatile_set=[
            metatile_set_entry_from_native(a_grid(1), name="USED_A"),
            metatile_set_entry_from_native(a_grid(2), name="USED_B"),
            metatile_set_entry_from_native(a_grid(3), name="UNUSED_C"),  # not on the map
        ],
    )
    repack_tileset_from_metatile_set(p)
    save_project(p, path)
    return p


with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    v5_path = d / "v5.json"
    build_v5(v5_path, "v5src")

    # a V4 fixture: same shape, formatVersion 4, tileset glyph codes at base 160
    v4_dict = json.loads(v5_path.read_text())
    v4_dict["formatVersion"] = 4
    v4_dict["name"] = "v4src"
    shift = TERRAIN_GLYPH_BASE_LEGACY - TERRAIN_GLYPH_BASE
    v4_dict["tileset"]["metatileDefs"] = [[c + shift for c in row]
                                          for row in v4_dict["tileset"]["metatileDefs"]]
    v4_path = d / "v4.json"
    v4_path.write_text(json.dumps(v4_dict, indent=2))

    # 1. V5 import - subset selection (used + unused), source untouched
    repo = TerrainRepository(path=d / "repository.json")
    repo.add_asset("keep-me", a_grid(99))
    src5 = load_project(v5_path)
    src5_bytes = v5_path.read_bytes()
    ids = import_selected(repo, src5, [0, 2])            # one used, one unused
    assert len(ids) == 2 and len(repo) == 3
    imported = {repo.get(i)["name"] for i in ids}
    assert imported == {"USED_A", "UNUSED_C"}
    assert repo.get(ids[0])["native"]["pixels"] == a_grid(1)
    assert repo.get(ids[1])["native"]["pixels"] == a_grid(3)
    assert v5_path.read_bytes() == src5_bytes, "source project file was modified"
    assert repo.has([a["id"] for a in repo.list() if a["name"] == "keep-me"][0])
    ok("V5 import: subset of used + unused metatiles; source untouched; existing asset kept")

    # 2. V4 import - via the same migration/loading code; native pixels exact
    src4 = load_project(v4_path)
    all_ids = import_selected(repo, src4, list(range(len(src4.level_metatile_set))))  # "select all"
    assert len(all_ids) == 3
    assert repo.get(all_ids[0])["native"]["pixels"] == a_grid(1)
    ok("V4 import: loaded through the normal migration path; select-all imports every metatile")

    # 3. duplicate names -> new independent ids, no overwrite
    before = set(repo.ids())
    dupe_ids = import_selected(repo, src5, [0])          # 'USED_A' again
    assert set(dupe_ids).isdisjoint(before)
    assert sum(1 for a in repo.list() if a["name"] == "USED_A") >= 2
    ok("duplicate names on import create new independent asset ids")

    # 4. malformed / unsupported file -> error, repository unchanged
    bad = d / "bad.json"
    bad.write_text('{"formatVersion": 99, "name": "x", "width": 10, "height": 1, "metatileRows": [[0,0,0,0,0,0,0,0,0,0]]}')
    snapshot = repo.dumps()
    try:
        load_project(bad)
        raise AssertionError("accepted an unsupported formatVersion")
    except ProjectValidationError:
        pass
    assert repo.dumps() == snapshot, "repository changed despite a failed import"
    ok("unsupported project file rejected cleanly; repository left unchanged")

print(f"\nAll {len(PASS)} import-from-project checks passed.")
