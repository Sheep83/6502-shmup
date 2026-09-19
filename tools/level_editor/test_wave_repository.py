#!/usr/bin/env python3
"""Global Wave Definition Repository (task section 7).

  * save a level-local definition to the global library
  * add a global definition into another level (snapshot / copy semantics)
  * snapshot independence BOTH directions
  * rename / delete of a global definition never alters existing level copies
  * duplicate a global definition
  * deterministic persistence, no timestamps; survives reload
  * NO worldRow (trigger placement) is ever stored globally

Run:  python3 tools/level_editor/test_wave_repository.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from project import (                                               # noqa: E402
    LevelProject, validate_project,
)
from wave_repository import (                                       # noqa: E402
    SCHEMA_VERSION, WaveRepository, WaveRepositoryError,
)

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


LOCAL_DEF = {
    "id": "wd_local_1", "name": "Alpha sweep", "attackId": 0,
    "composition": [{"enemyType": 0, "count": 5}], "spawnInterval": None,
}


def a_level(name, defs=None, triggers=None):
    return LevelProject(
        name=name, metatile_rows=[[0] * 10 for _ in range(30)], tileset=None,
        level_metatile_set=None,
        wave_definitions=[dict(d) for d in (defs or [])],
        wave_triggers=[dict(t) for t in (triggers or [])],
    )


with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "wave_repository" / "repository.json"

    # 1. save a level-local definition to the global library (no worldRow leaks)
    repo = WaveRepository(path=path)
    lib_def = repo.add_from_level_definition(LOCAL_DEF, name="Alpha sweep", tags=["intro"])
    assert lib_def["id"].startswith("wave_")
    assert "worldRow" not in lib_def and "id" in lib_def
    repo.save()
    blob = repo.dumps()
    assert "worldRow" not in blob
    ok("save-to-library stores only the reusable 'what'; no trigger worldRow")

    # 2. add the global definition into a DIFFERENT level as a local snapshot
    other = a_level("level2")
    snap = repo.snapshot(lib_def["id"], local_id="wd1")
    other.wave_definitions.append(snap)
    other.wave_triggers.append({"id": "wt1", "worldRow": 40, "waveDef": "wd1"})
    assert validate_project(other) == []
    assert other.wave_definitions[0]["id"] == "wd1"           # fresh level-local id
    assert "worldRow" not in other.wave_definitions[0]
    ok("add-from-library copies a self-contained local definition; trigger refs resolve")

    # 3. snapshot independence BOTH directions
    repo.update_definition(lib_def["id"], name="RENAMED", attack_id=5)
    assert other.wave_definitions[0]["name"] == "Alpha sweep"   # library edit did not touch level
    assert other.wave_definitions[0]["attackId"] == 0
    other.wave_definitions[0]["name"] = "level-edited"
    assert repo.get(lib_def["id"])["name"] == "RENAMED"         # level edit did not touch library
    ok("snapshot independence: global edit <-> local edit never cross")

    # 4. delete a global definition -> existing level copies survive
    repo.remove(lib_def["id"])
    repo.save()
    assert not repo.has(lib_def["id"])
    assert validate_project(other) == []
    assert other.wave_definitions[0]["name"] == "level-edited"
    ok("deleting the library definition leaves the level's local copy intact and valid")

    # 5. duplicate a global definition
    base = repo.add_definition("Bravo", 3, [{"enemyType": 2, "count": 6}], spawn_interval=14)
    dup = repo.add_definition(base["name"] + " copy", base["attackId"],
                              base["composition"], spawn_interval=base["spawnInterval"])
    assert dup["id"] != base["id"]
    assert dup["composition"] == base["composition"] and dup["spawnInterval"] == 14
    dup2 = repo.update_definition(dup["id"], name="Bravo variant")
    assert repo.get(base["id"])["name"] == "Bravo"              # duplicate is independent
    ok("a duplicated library definition is an independent asset")

    # 6. deterministic persistence, reload
    repo.save()
    b1 = repo.dumps()
    r2 = WaveRepository.load(path)
    assert r2.dumps() == b1
    assert "time" not in b1.lower() and "date" not in b1.lower()
    data = json.loads(b1)
    assert data["schemaVersion"] == SCHEMA_VERSION
    assert [x["id"] for x in data["definitions"]] == sorted(x["id"] for x in data["definitions"])
    ok("library persists deterministically (sorted, no timestamps) and survives reload")

    # 7. malformed globals rejected
    try:
        WaveRepository(definitions=[{"id": "wave_0001", "name": "x", "attackId": 0,
                                     "composition": [{"enemyType": 0, "count": 1}], "worldRow": 12}])
        raise AssertionError("accepted a worldRow in a global definition")
    except WaveRepositoryError:
        pass
    try:
        repo.add_definition("bad", 99, [{"enemyType": 0, "count": 1}])
        raise AssertionError("accepted an out-of-range attackId")
    except WaveRepositoryError:
        pass
    ok("global definitions with worldRow / invalid attackId are rejected")

print(f"\nAll {len(PASS)} wave-repository checks passed.")
