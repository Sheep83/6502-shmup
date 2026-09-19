#!/usr/bin/env python3
"""Save Selected Level Metatile to Terrain Repository (task section 3).

  * exact native 16x32 pixel snapshot
  * repository copy and level copy independent BOTH directions
  * provenance recorded (promoted-from-level)
  * duplicate name handling: a new, independent id - never a silent overwrite
  * deterministic repository serialisation, no timestamps
  * existing repository assets preserved

Run:  python3 tools/level_editor/test_metatile_save_to_repository.py
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from native_metatile import blank_pixels                            # noqa: E402
from project import (                                               # noqa: E402
    LevelProject, metatile_set_entry_from_native,
    repack_tileset_from_metatile_set,
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


def promote(repo, project, index, name=None):
    """Mirror LevelEditor._metatile_save_to_repository at the model layer."""
    entry = project.level_metatile_set[index]
    default = entry.get("name") or f"M{index}"
    prov = {"sourcePack": f"promoted from level '{project.name}' metatile {index} ({default})"}
    return repo.add_asset(name or default, [r[:] for r in entry["native"]["pixels"]],
                          provenance=prov, tags=["from-level"])


def make_project():
    p = LevelProject(
        name="lvlA", metatile_rows=[[0] * 10 for _ in range(6)], tileset=None,
        level_metatile_set=[
            metatile_set_entry_from_native(a_grid(1), name="WALL"),
            metatile_set_entry_from_native(a_grid(2), name="DECK"),
        ],
    )
    repack_tileset_from_metatile_set(p)
    return p


# 1. exact pixel snapshot + provenance
with tempfile.TemporaryDirectory() as d:
    repo = TerrainRepository(path=Path(d) / "repository.json")
    repo.add_asset("pre-existing", a_grid(9), tags=["keep"])
    proj = make_project()
    asset = promote(repo, proj, 0, name="Hull wall")
    assert asset["native"]["pixels"] == a_grid(1)
    assert asset["provenance"]["sourcePack"].startswith("promoted from level 'lvlA'")
    assert "from-level" in asset["tags"]
    ok("promotes an exact 16x32 snapshot with promoted-from-level provenance")

    # 2. independence both directions
    repo.update_asset(asset["id"], native_pixels=a_grid(50))
    assert proj.level_metatile_set[0]["native"]["pixels"] == a_grid(1), "repo edit hit the level"
    proj.level_metatile_set[0]["native"]["pixels"][0][0] = 3
    assert repo.get(asset["id"])["native"]["pixels"] == a_grid(50), "level edit hit the repo"
    ok("repository copy and level copy are independent in both directions")

    # 3. duplicate name -> a NEW independent id, never an overwrite
    proj2 = make_project()
    again = promote(repo, proj2, 1, name="Hull wall")
    assert again["id"] != asset["id"]
    assert repo.has(asset["id"]) and repo.has(again["id"])
    assert again["native"]["pixels"] == a_grid(2)
    ok("a name clash creates a new independent asset id - no silent overwrite")

    # 4. deterministic serialisation, no timestamps, existing asset preserved
    blob1 = repo.dumps()
    repo.save()
    reloaded = TerrainRepository.load(repo.path)
    assert reloaded.dumps() == blob1
    assert "time" not in blob1.lower() and "date" not in blob1.lower()
    assert reloaded.get([a["id"] for a in reloaded.list() if a["name"] == "pre-existing"][0])[
        "native"]["pixels"] == a_grid(9)
    ok("deterministic serialisation (no timestamps); pre-existing repository asset preserved")

print(f"\nAll {len(PASS)} save-to-repository checks passed.")
