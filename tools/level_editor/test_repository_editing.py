#!/usr/bin/env python3
"""Repository Asset Editing (task section 9).

The Terrain Asset Repository is a genuine reusable graphics library: a stored
asset can be opened in the native tile editor and saved back.

  * paint (pixel update) + rename write back to the SAME asset id
  * mirror / flip are ordinary pixel edits and round-trip
  * deterministic serialisation after an edit
  * editing a repository asset never mutates a level snapshot previously copied
    from it (independent snapshots)

Run:  python3 tools/level_editor/test_repository_editing.py
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from native_metatile import blank_pixels                            # noqa: E402
from project import (                                               # noqa: E402
    LevelProject, metatile_set_entry_from_native,
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


def mirror_h(px):
    return [list(reversed(r)) for r in px]


def flip_v(px):
    return [r[:] for r in reversed(px)]


with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "repository.json"
    repo = TerrainRepository(path=path)
    aid = repo.add_asset("Rock face", a_grid(1), provenance={"sourcePack": "hand"},
                         notes="v1", tags=["rock"])["id"]

    # a level takes an independent snapshot of the asset BEFORE it is edited
    proj = LevelProject(name="L", metatile_rows=[[0] * 10 for _ in range(6)], tileset=None,
                        level_metatile_set=[])
    snap = repo.snapshot(aid)
    proj.level_metatile_set.append(metatile_set_entry_from_native(
        snap["pixels"], name=snap["name"],
        source={"repositoryAssetId": aid, "provenance": snap["provenance"]}))
    level_pixels_before = [r[:] for r in proj.level_metatile_set[0]["native"]["pixels"]]

    # 1. paint + rename write back to the SAME id
    edited = mirror_h(a_grid(1))
    repo.update_asset(aid, name="Rock face (mirrored)", native_pixels=edited)
    repo.save()
    got = TerrainRepository.load(path).get(aid)
    assert got["id"] == aid, "asset id changed on edit"
    assert got["name"] == "Rock face (mirrored)"
    assert got["native"]["pixels"] == edited
    assert got["provenance"] == {"sourcePack": "hand"}, "provenance dropped"
    ok("edit + rename write back to the same asset id; provenance preserved")

    # 2. mirror then flip round-trips as ordinary pixel edits
    repo.update_asset(aid, native_pixels=flip_v(edited))
    repo.update_asset(aid, native_pixels=mirror_h(flip_v(edited)))
    repo.update_asset(aid, native_pixels=flip_v(mirror_h(flip_v(edited))))
    repo.update_asset(aid, native_pixels=edited)
    assert repo.get(aid)["native"]["pixels"] == edited
    ok("mirror / flip edits are ordinary pixel writes and round-trip")

    # 3. deterministic serialisation after edits
    blob = repo.dumps()
    repo.save()
    assert TerrainRepository.load(path).dumps() == blob
    assert "time" not in blob.lower() and "date" not in blob.lower()
    ok("repository still serialises deterministically after edits")

    # 4. the level snapshot copied earlier is UNCHANGED by the repo edits
    assert proj.level_metatile_set[0]["native"]["pixels"] == level_pixels_before
    assert level_pixels_before == a_grid(1)
    ok("editing the repository asset does not mutate a level snapshot taken from it")

print(f"\nAll {len(PASS)} repository-editing checks passed.")
