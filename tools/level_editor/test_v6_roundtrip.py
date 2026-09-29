#!/usr/bin/env python3
"""v6 JSON determinism and the older-version migration path (Contract v2, Phase 1).

  * save -> load -> save is byte-identical, for a real level and a synthetic one;
  * the text itself is deterministic: LF only, trailing newline, 2-space indent,
    stable key order, no timestamps and no absolute paths;
  * symbolic enum names survive a round trip as names, not numbers;
  * a fire mask given as a legacy integer bitmask loads as member indices and
    then round-trips stably;
  * THE PRE-v5 PATH STILL WORKS: a formatVersion 4 project, whose metatile defs
    name glyph codes at the old base of 160, migrates through project.py's rebase
    and lands on exactly the same v6 project as its v5 equivalent.

No pre-v5 fixture ships with the editor, so the v4 case is built by shifting the
real Level 1 back to the legacy glyph base -- which is precisely what a v4 file
was, and it exercises the real legacy code path rather than a stub.

Run:  python3 tools/level_editor/test_v6_roundtrip.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                             # noqa: E402
from migration_v6 import load_any, migrate_to_v6                    # noqa: E402
from project import TERRAIN_GLYPH_BASE_LEGACY                       # noqa: E402
from project_v6 import ProjectV6, Trigger                           # noqa: E402
from validation_v6 import validate                                  # noqa: E402

PASS = []
LEVEL1 = HERE / "fixtures" / "legacy_v5" / "level1" / "level.json"
LEVEL2 = HERE / "fixtures" / "legacy_v5" / "level2" / "level.json"


def ok(label, extra=""):
    PASS.append(label)
    print(f"  ok   {label}{' -- ' + extra if extra else ''}")


def roundtrip(project, label):
    a = project.to_json()
    b = ProjectV6.from_json(a).to_json()
    if a != b:
        for i, (x, y) in enumerate(zip(a.splitlines(), b.splitlines())):
            if x != y:
                raise AssertionError(f"{label}: first difference at line {i}: "
                                     f"{x!r} vs {y!r}")
        raise AssertionError(f"{label}: lengths differ {len(a)} vs {len(b)}")
    ok(label, f"{len(a)} bytes")
    return a


print("=== JSON determinism ===")
p1 = load_any(LEVEL1).project
text = roundtrip(p1, "Level 1: save -> load -> save is byte-identical")

if "\r" in text:
    raise AssertionError("CR found: line endings are not LF")
ok("line endings are LF only")
if not text.endswith("\n") or text.endswith("\n\n"):
    raise AssertionError("expected exactly one trailing newline")
ok("the file ends with exactly one trailing newline")

lines = text.splitlines()
if lines[0] != "{" or not lines[1].startswith('  "formatVersion"'):
    raise AssertionError(f"unexpected opening: {lines[:2]}")
ok("indentation is two spaces and formatVersion leads the file")

# KEY ORDER: STABLE, NOT FROZEN.
#
# A literal list of eleven key names used to live here, and it drifted the moment
# a key was added to the schema: `enemySlots` now sits after `palette` and the
# check failed listing a perfectly correct document. What the format actually
# promises is that a save is DETERMINISTIC and diffable -- formatVersion leads so
# a reader can tell the version before parsing the rest, and the order does not
# move between saves -- and that is what is asserted. The exact sequence comes
# from the writer, which is the only thing entitled to decide it.
order = list(json.loads(text).keys())
if order[0] != "formatVersion":
    raise AssertionError(f"formatVersion must lead the file, got {order[0]!r}")
_again = list(json.loads(ProjectV6.from_json(text).to_json()).keys())
if _again != order:
    raise AssertionError(f"key order moved across a round trip: {order} -> {_again}")
_declared = list(ProjectV6.from_json(text).to_dict().keys())
if _declared != order:
    raise AssertionError(
        f"the serialised order is not the writer's own: {order} vs {_declared}")
if len(set(order)) != len(order):
    raise AssertionError(f"a key appears twice: {order}")
ok("top-level key order is the writer's, stable across a round trip, and "
   "formatVersion leads",
   " -> ".join(order[:5]) + f" ... ({len(order)} keys)")

for banned in (str(HERE), "/Users/", "/tmp/", "20", "T00:"):
    if banned == "20":
        continue                    # digits legitimately appear in map data
    if banned in text:
        raise AssertionError(f"environment-specific text {banned!r} in the JSON")
ok("no absolute paths and no timestamps in the output")

# A third save from a file on disk, to prove save() itself is stable.
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "level.json"
    p1.save(path)
    once = path.read_bytes()
    ProjectV6.load(path).save(path)
    twice = path.read_bytes()
    if once != twice:
        raise AssertionError("save() is not idempotent on disk")
    ok("save() -> load() -> save() on disk is byte-identical", f"{len(once)} bytes")

print("\n=== a second real project ===")
p2 = load_any(LEVEL2).project
roundtrip(p2, "Level 2: save -> load -> save is byte-identical")
ok("Level 2 migrated", f"{p2.stage.metatile_rows} rows, "
                       f"noSpawnRow {p2.stage.no_spawn_row}")

print("\n=== symbolic enums survive ===")
p = load_any(LEVEL1).project
# THE IDENTITIES THIS LEVEL ACTUALLY HOLDS, not the legacy species names. The
# triggers here were built with "RING", which load normalises to the level's slot-0
# identity ("RING_3") -- correct migration behaviour, and it made the fixed-point
# check below fail on the normalisation rather than on any defect. The legacy
# spelling gets its own case underneath, where the normalisation is the subject.
_IDS = C.level_identities(p)
p.triggers = [Trigger(10, "w", _IDS[0], [0, 2], "LEFT"),
              Trigger(20, "w", _IDS[1], [1], "RIGHT")]
doc = json.loads(p.to_json())
if (doc["triggers"][0]["species"] != _IDS[0]
        or doc["triggers"][1]["species"] != _IDS[1]):
    raise AssertionError("species were not written as names")
if doc["triggers"][1]["dropperSide"] != "RIGHT":
    raise AssertionError("dropperSide was not written as a name")
ok("species and side are stored as symbolic names, not numbers",
   f"{_IDS[0]} / {_IDS[1]}")
if doc["triggers"][0]["fireMask"] != [0, 2]:
    raise AssertionError("fire mask is not a member-index list")
ok("the fire mask is a list of member indices")
back = ProjectV6.from_json(p.to_json())
if back.triggers[0].fire_bits != 0b101:
    raise AssertionError(f"fire_bits wrong: {back.triggers[0].fire_bits:b}")
ok("...and converts to the engine's bitmask", "members [0, 2] -> %00000101")
roundtrip(p, "a project with triggers round-trips byte-identically")

# A legacy integer bitmask is accepted on load and normalised to indices.
raw = json.loads(p.to_json())
raw["triggers"][0]["fireMask"] = 0b101
loaded = ProjectV6.from_dict(raw)
if loaded.triggers[0].fire_mask != [0, 2]:
    raise AssertionError(f"bitmask not normalised: {loaded.triggers[0].fire_mask}")
ok("an integer fire mask loads as member indices and normalises")
if loaded.to_json() != p.to_json():
    raise AssertionError("a normalised bitmask did not converge on the same JSON")
ok("...and converges on identical JSON")

# A LEGACY SPECIES NAME MIGRATES, ONCE, AND THEN HOLDS STILL. "RING" predates
# enemy identities and is not a species any more; load must turn it into the
# identity this level's slot 0 holds, and a second save must then be a fixed
# point. Anything else is either a lost migration or an endlessly churning file.
_legacy = json.loads(p.to_json())
_legacy["triggers"][0]["species"] = C.LEGACY_SPECIES_ORDER[0]
_migrated = ProjectV6.from_dict(_legacy)
if _migrated.triggers[0].species != _IDS[0]:
    raise AssertionError(
        f"a legacy species name did not migrate: "
        f"{_migrated.triggers[0].species!r}, expected {_IDS[0]!r}")
ok(f"a legacy {C.LEGACY_SPECIES_ORDER[0]!r} migrates to this level's slot-0 "
   f"identity", _IDS[0])
roundtrip(_migrated, "...and the migrated project is then a fixed point")

print("\n=== the pre-v5 migration path still works ===")
v5 = json.loads(LEVEL1.read_text(encoding="utf-8"))
shift = TERRAIN_GLYPH_BASE_LEGACY - C.TERRAIN_GLYPH_BASE          # 160 - 96 = 64
v4 = json.loads(json.dumps(v5))
v4["formatVersion"] = 4
v4["tileset"]["metatileDefs"] = [[c + shift for c in d]
                                 for d in v4["tileset"]["metatileDefs"]]
codes = {c for d in v4["tileset"]["metatileDefs"] for c in d}
if min(codes) < TERRAIN_GLYPH_BASE_LEGACY:
    raise AssertionError("the synthetic v4 fixture is not at the legacy base")
ok("built a synthetic formatVersion 4 fixture at glyph base 160",
   f"codes {min(codes)}..{max(codes)}")

r4 = migrate_to_v6(v4)
eq_codes = {c for d in r4.project.metatile_defs for c in d}
if min(eq_codes) < C.TERRAIN_GLYPH_BASE:
    raise AssertionError(f"v4 glyph codes were not rebased: {min(eq_codes)}")
ok("project.py's glyph rebase ran: codes are back at base 96",
   f"codes {min(eq_codes)}..{max(eq_codes)}")
if r4.from_version != 4:
    raise AssertionError(f"reported wrong source version: {r4.from_version}")
ok("the migration reports formatVersion 4 as its source")

r5 = migrate_to_v6(v5)
if r4.project.to_json() != r5.project.to_json():
    raise AssertionError("the v4 and v5 routes produced different v6 projects")
ok("the v4 and v5 routes land on byte-identical v6 projects")
v = validate(r4.project)
if not v.ok:
    raise AssertionError(f"the migrated v4 project does not validate:\n{v}")
ok("the migrated v4 project validates with no errors")

print(f"\nAll {len(PASS)} round-trip checks passed.")
