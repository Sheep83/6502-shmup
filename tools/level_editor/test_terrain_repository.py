#!/usr/bin/env python3
"""Terrain Asset Repository: persistence, determinism, provenance, independence
from live C64 glyph IDs (task section 11 / 20 / 21 / 31).

Run:  python3 tools/level_editor/test_terrain_repository.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from native_metatile import blank_pixels, pixels_to_glyphs         # noqa: E402
from terrain_repository import (                                    # noqa: E402
    SCHEMA_VERSION, TerrainRepository, TerrainRepositoryError,
)

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


PROV = {
    "sourcePack": "Dithart's FREE Sci-fi Tileset v0.1",
    "sourceTileIndex": 42,
    "sourceCoords": [2, 5],
    "sourceTileSize": [32, 32],
    "licenceNote": "Derivative work; original pack not redistributed.",
    "localSourcePath": "/Users/someone/Desktop/tileset_for_free.png",
}

# 1. add + save + load round trip
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "terrain_repository" / "repository.json"
    repo = TerrainRepository(path=path)
    aid1 = repo.add_asset("Crater rim NW", a_grid(1), provenance=PROV,
                          notes="hand-tuned rim", tags=["crater", "rock"])["id"]
    aid2 = repo.add_asset("Ravine floor", a_grid(2))["id"]
    repo.save()
    assert path.exists()

    repo2 = TerrainRepository.load(path)
    assert len(repo2) == 2
    assert [a["id"] for a in repo2.list()] == sorted([aid1, aid2])
    got = repo2.get(aid1)
    assert got["name"] == "Crater rim NW"
    assert got["native"]["pixels"] == a_grid(1)
    assert got["native"]["width"] == 16 and got["native"]["height"] == 32
    assert got["provenance"] == {k: v for k, v in PROV.items()}  # all retained
    assert got["tags"] == ["crater", "rock"]
    assert got["notes"] == "hand-tuned rim"
ok("save/load round trip preserves native pixels, name, provenance, notes, tags")

# 2. deterministic serialisation: re-dumping an unchanged repo is byte-identical,
#    and there are NO volatile timestamps
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "repo.json"
    repo = TerrainRepository(path=path)
    repo.add_asset("B second", a_grid(9))
    repo.add_asset("A first", a_grid(8))
    blob1 = repo.dumps()
    repo.save()
    blob2 = TerrainRepository.load(path).dumps()
    assert blob1 == blob2, "re-dump not identical"
    assert "date" not in blob1.lower() and "time" not in blob1.lower()
    data = json.loads(blob1)
    assert data["schemaVersion"] == SCHEMA_VERSION
    assert [a["id"] for a in data["assets"]] == sorted(a["id"] for a in data["assets"])
ok("deterministic serialisation (sorted, no timestamps); schemaVersion present")

# 3. assets are independent of live C64 glyph IDs - the stored form has NO
#    char codes, only logical 0..3 pixels; codes are assigned at level pack time
with tempfile.TemporaryDirectory() as d:
    repo = TerrainRepository(path=Path(d) / "r.json")
    asset = repo.add_asset("Rock", a_grid(3))
    blob = repo.dumps()
    # no terrain-namespace char codes (160..223) leaked into the asset
    assert '"160"' not in blob and "160," not in blob.replace("sourceTileIndex", "")
    # the same asset decomposes to glyphs only when a level asks for it
    glyphs = pixels_to_glyphs(asset["native"]["pixels"])
    assert len(glyphs) == 16 and all(len(g) == 8 for g in glyphs)
ok("repository assets carry logical pixels only - never hard-coded live glyph IDs")

# 4. snapshot() is a standalone deep copy for embedding into a level
with tempfile.TemporaryDirectory() as d:
    repo = TerrainRepository(path=Path(d) / "r.json")
    asset = repo.add_asset("Snap me", a_grid(4), provenance={"sourcePack": "X"})
    snap = repo.snapshot(asset["id"])
    assert snap["repositoryAssetId"] == asset["id"]
    assert snap["pixels"] == a_grid(4)
    assert snap["provenance"] == {"sourcePack": "X"}
    # mutating the repo asset afterwards must NOT change the snapshot
    repo.update_asset(asset["id"], native_pixels=a_grid(99))
    assert snap["pixels"] == a_grid(4)
    repo.remove(asset["id"])
    assert snap["pixels"] == a_grid(4)         # still usable after the repo entry is gone
ok("snapshot() is a deep copy: later repo edit/delete cannot mutate a level's copy")

# 5. malformed documents are rejected
with tempfile.TemporaryDirectory() as d:
    bad = Path(d) / "bad.json"
    bad.write_text('{"schemaVersion": 999, "assets": []}')
    try:
        TerrainRepository.load(bad)
        raise AssertionError("accepted unknown schemaVersion")
    except TerrainRepositoryError:
        pass
    try:
        TerrainRepository(assets=[{"id": "nope", "name": "x", "native": {"pixels": blank_pixels(0)}}])
        raise AssertionError("accepted bad asset id")
    except TerrainRepositoryError:
        pass
ok("unknown schemaVersion / malformed asset id rejected cleanly")

# 6. auto id allocation is stable and gap-filling
with tempfile.TemporaryDirectory() as d:
    repo = TerrainRepository(path=Path(d) / "r.json")
    i1 = repo.add_asset("one", a_grid(1))["id"]
    i2 = repo.add_asset("two", a_grid(2))["id"]
    assert (i1, i2) == ("asset_0001", "asset_0002")
    repo.remove(i1)
    i3 = repo.add_asset("three", a_grid(3))["id"]
    assert i3 == "asset_0001", i3          # lowest free id reused
ok("asset ids are asset_NNNN, allocated lowest-free")

print(f"\nAll {len(PASS)} terrain-repository checks passed.")
