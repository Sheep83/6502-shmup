#!/usr/bin/env python3
"""v5 -> v6 migration of the authoritative Level 1 project (Contract v2, Phase 1).

  * the version becomes 6;
  * every terrain fact survives: 105x10 map, palette, 72 glyphs, 34 metatile defs;
  * all 8 turrets survive with their coordinates;
  * scrollFrameDivider is gone from the v6 output;
  * noSpawnRow is 340 -- the value the engine actually ships;
  * movementPrograms / waveDefinitions / triggers are EMPTY after migration;
  * the 33 old wave definitions and 53 old triggers are reported as discarded;
  * the converted legacy trigger positions are deterministic and non-live;
  * migration of the same source twice is byte-identical in both directions.

Run:  python3 tools/level_editor/test_v6_migration.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                             # noqa: E402
from migration_v6 import (                                          # noqa: E402
    legacy_trigger_progress, load_any, migrate_to_v6,
)
from project_v6 import FORMAT_VERSION, ProjectV6                    # noqa: E402
from validation_v6 import validate                                  # noqa: E402

PASS = []
LEVEL1 = HERE / "fixtures" / "legacy_v5" / "level1" / "level.json"


def ok(label):
    PASS.append(label)
    print(f"  ok   {label}")


def eq(label, got, want):
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")
    ok(f"{label} -- {got!r}" if not isinstance(got, (list, dict)) else label)


# ---------------------------------------------------------------------------
print("=== v5 -> v6 migration: Level 1 ===")
raw = json.loads(LEVEL1.read_text(encoding="utf-8"))
eq("the fixture really is formatVersion 5", raw["formatVersion"], 5)

result = load_any(LEVEL1)
p = result.project

eq("migrated from version", result.from_version, 5)
eq("migrated to version", result.to_version, FORMAT_VERSION)
eq("v6 JSON declares formatVersion 6", p.to_dict()["formatVersion"], 6)

# ---- terrain ---------------------------------------------------------------
eq("stage height survives", p.stage.metatile_rows, 105)
eq("map row count survives", len(p.map_rows), 105)
eq("map row width survives", {len(r) for r in p.map_rows}, {10})
if p.map_rows != raw["metatileRows"]:
    raise AssertionError("map cells changed during migration")
ok("every one of the 1050 map cells is unchanged")

eq("palette background", p.palette.background, raw["palette"]["background"])
eq("palette multicolour1", p.palette.multicolour1, raw["palette"]["multicolour1"])
eq("palette multicolour2", p.palette.multicolour2, raw["palette"]["multicolour2"])
eq("palette character", p.palette.character, raw["palette"]["character"])

eq("glyph count survives", len(p.glyphs), 72)
if p.glyphs != raw["tileset"]["glyphs"]:
    raise AssertionError("glyph bitmaps changed during migration")
ok("all 72 glyph bitmaps are byte-for-byte unchanged")
eq("every glyph is 8 bytes", {len(g) for g in p.glyphs}, {8})

eq("metatile definition count survives", len(p.metatile_defs), 34)
if p.metatile_defs != raw["tileset"]["metatileDefs"]:
    raise AssertionError("metatile definitions changed during migration")
ok("all 34 metatile definitions are unchanged")
eq("every definition is 16 codes", {len(d) for d in p.metatile_defs}, {16})
eq("the native metatile set is carried through",
   len(p.level_metatile_set), len(raw["levelMetatileSet"]))

# ---- turrets ---------------------------------------------------------------
eq("turret count survives", len(p.turrets), 8)
old_turrets = sorted((o["metatileRow"], o["metatileCol"]) for o in raw["objects"]
                     if o.get("type") == "turret")
new_turrets = sorted((t.metatile_row, t.metatile_col) for t in p.turrets)
eq("turret coordinates survive exactly", new_turrets, old_turrets)
# The engine derivation, cross-checked against src/level1/stage_turrets.asm.
eq("derived turret world rows match the engine's authored list",
   sorted((t.world_row for t in p.turrets), reverse=True),
   [345, 337, 225, 217, 117, 109, 25, 5])
eq("derived turret world cols match the engine's authored list",
   [t.world_col for t in sorted(p.turrets,
                                key=lambda t: -t.world_row)],
   [17, 25, 29, 9, 25, 13, 25, 13])

# ---- what was dropped ------------------------------------------------------
doc = p.to_dict()
for gone in ("width", "height", "scrollFrameDivider", "metatileMetadata",
             "objects", "tileset", "waveTriggers"):
    if gone in doc:
        raise AssertionError(f"v6 output still carries {gone!r}")
ok("v6 output carries no width/height/scrollFrameDivider/metatileMetadata")
if "scrollFrameDivider" in p.to_json():
    raise AssertionError("scrollFrameDivider survived into the JSON text")
ok("the string 'scrollFrameDivider' does not appear anywhere in the v6 JSON")

# ---- the boss approach -----------------------------------------------------
eq("noSpawnRow is the engine's own value", p.stage.no_spawn_row, 340)
eq("derived playable progress", p.stage.playable_progress, 395)
eq("derived logical rows", p.stage.logical_rows, 420)
eq("derived quiet zone", p.stage.playable_progress - p.stage.no_spawn_row, 55)
eq("derived terrain duration (s)", round(p.stage.terrain_seconds, 1), 63.2)

# ---- encounters are empty and the discard is loud --------------------------
eq("movement programs are empty", p.movement_programs, [])
eq("wave definitions are empty", p.wave_definitions, [])
eq("live triggers are empty", p.triggers, [])

codes = result.codes()
for required in ("migration.version",
                 "migration.dropped_scroll_frame_divider",
                 "migration.dropped_wave_definitions",
                 "migration.dropped_wave_triggers",
                 "migration.encounters_not_mappable",
                 "migration.no_spawn_row"):
    if required not in codes:
        raise AssertionError(f"migration notice {required!r} missing; got {codes}")
ok("every required migration notice is present")

by_code = {n.code: n for n in result.notices}
eq("the 33 old wave definitions are reported discarded",
   by_code["migration.dropped_wave_definitions"].detail["count"], 33)
eq("the 53 old triggers are reported discarded",
   by_code["migration.dropped_wave_triggers"].detail["count"], 53)
eq("the dropped scrollFrameDivider value is reported",
   by_code["migration.dropped_scroll_frame_divider"].detail["value"], 2)
eq("the assigned noSpawnRow is reported",
   by_code["migration.no_spawn_row"].detail["noSpawnRow"], 340)

# ---- legacy positions are reference data, not triggers ---------------------
eq("all 53 old trigger rows are converted", len(result.legacy_trigger_positions), 53)
first = result.legacy_trigger_positions[0]
eq("the converted rows are sorted ascending by worldProgress",
   [e["worldProgress"] for e in result.legacy_trigger_positions],
   sorted(e["worldProgress"] for e in result.legacy_trigger_positions))
# 390 was the FIRST v5 row and is the EARLIEST moment in play: the domains are
# mirror images. This is the conversion the whole migration turns on.
eq("v5 stage row 390 converts to worldProgress 5",
   legacy_trigger_progress(390, 395), 5)
eq("v5 stage row 0 converts to the stage end", legacy_trigger_progress(0, 395), 395)
eq("the earliest converted position", first["worldProgress"], 5)
if any(e["worldProgress"] >= 340 and e["legal"] for e in result.legacy_trigger_positions):
    raise AssertionError("a position at/after noSpawnRow was marked legal")
ok("converted positions at or beyond noSpawnRow are marked illegal, not hidden")
if "legacyTriggerPositions" in p.to_json() or "oldWorldRow" in p.to_json():
    raise AssertionError("legacy positions leaked into the v6 project file")
ok("the converted positions are NOT written into the v6 project")

# ---- the migrated project is actually valid --------------------------------
v = validate(p)
if not v.ok:
    raise AssertionError(f"migrated Level 1 does not validate:\n{v}")
eq("migrated Level 1 validates with no errors", len(v.errors), 0)
eq("...and no warnings", len(v.warnings), 0)

# ---- determinism -----------------------------------------------------------
again = load_any(LEVEL1)
if again.project.to_json() != p.to_json():
    raise AssertionError("migrating the same source twice gave different JSON")
ok("migrating the same source twice is byte-identical")
if again.report() != result.report():
    raise AssertionError("migration notices are not deterministic")
ok("the migration report is byte-identical across runs")
if again.legacy_trigger_positions != result.legacy_trigger_positions:
    raise AssertionError("converted legacy positions are not deterministic")
ok("the converted legacy positions are deterministic")

# ---- already-v6 input is a no-op ------------------------------------------
v6_again = migrate_to_v6(json.loads(p.to_json()))
eq("re-migrating a v6 project is a no-op", v6_again.from_version, 6)
if v6_again.project.to_json() != p.to_json():
    raise AssertionError("re-migrating a v6 project changed it")
ok("re-migrating a v6 project leaves it byte-identical")

print(f"\nAll {len(PASS)} migration checks passed.")
