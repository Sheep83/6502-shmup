#!/usr/bin/env python3
"""Recover the complete original GENERATED native terrain set into the Terrain
Asset Repository (task section 5).

  * the AUTHORITATIVE generator (native_terrain_tiles.py) is used - not a
    hand-reconstruction
  * the expected number of generated assets is recovered
  * native output is exact + deterministic (fingerprint match against the
    generator)
  * the user's existing repository assets are never lost or overwritten
  * a second run is idempotent (identical artwork already present -> skipped)

Run:  python3 tools/level_editor/test_generated_set_recovery.py
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import native_terrain_tiles as ntt                                  # noqa: E402
from native_metatile import blank_pixels, validate_pixels           # noqa: E402


def a_grid(seed):
    """A distinctive user-authored grid unlikely to collide with a generated tile."""
    g = blank_pixels(0)
    for y in range(32):
        for x in range(16):
            g[y][x] = ((seed * 13 + y * 7 + x * 3) % 4)
    return g
from recover_generated_terrain import recover_generated_set          # noqa: E402
from terrain_repository import TerrainRepository                    # noqa: E402

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


EXPECTED = len(ntt.names())          # the generator is the single source of truth
assert EXPECTED == 31, EXPECTED      # documented count of the generated set

with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "repository.json"

    # 1. recover into a repository that already holds user assets
    repo = TerrainRepository(path=path)
    user_ids = [repo.add_asset(f"user-{i}", a_grid(i + 1))["id"] for i in range(4)]
    user_pixels = {i: repo.get(i)["native"]["pixels"] for i in user_ids}

    res = recover_generated_set(repo)
    assert res["generated"] == EXPECTED
    assert len(res["added"]) == EXPECTED, (len(res["added"]), len(res["existing"]))
    assert len(repo) == 4 + EXPECTED
    # user assets untouched
    for i in user_ids:
        assert repo.get(i)["native"]["pixels"] == user_pixels[i]
    ok(f"recovered {EXPECTED} generated metatiles alongside {len(user_ids)} preserved user assets")

    # 2. every recovered asset is byte-exact vs the authoritative generator
    gen = {name: validate_pixels(px) for name, px in ntt.metatiles()}
    by_name = {}
    for a in repo.list():
        by_name.setdefault(a["name"], a)
    for name, px in gen.items():
        assert name in by_name, name
        assert by_name[name]["native"]["pixels"] == px, name
        assert "generated" in by_name[name]["tags"]
    ok("each recovered asset's native pixels match native_terrain_tiles.metatiles() exactly")

    # 3. deterministic serialisation, no timestamps
    repo.save()
    blob = repo.dumps()
    assert TerrainRepository.load(path).dumps() == blob
    assert "time" not in blob.lower() and "date" not in blob.lower()
    ok("recovered repository serialises deterministically with no timestamps")

    # 4. idempotent: a second recovery adds nothing (identical artwork present)
    res2 = recover_generated_set(repo)
    assert res2["added"] == []
    assert len(res2["existing"]) == EXPECTED
    assert len(repo) == 4 + EXPECTED
    ok("a second recovery is a no-op: identical generated assets are skipped, not duplicated")

    # 5. a partial repository (some generated tiles already present, some not)
    repo3 = TerrainRepository(path=Path(d) / "r3.json")
    first_five = ntt.metatiles()[:5]
    for name, px in first_five:
        repo3.add_asset(name, px, tags=["generated"])
    res3 = recover_generated_set(repo3)
    assert len(res3["added"]) == EXPECTED - 5
    assert len(res3["existing"]) == 5
    assert len(repo3) == EXPECTED
    ok("partial recovery only adds the missing generated metatiles")

print(f"\nAll {len(PASS)} generated-set-recovery checks passed.")
