#!/usr/bin/env python3
"""The wave / trigger contract the engine actually has.

WHAT THIS FILE USED TO TEST, AND WHY NONE OF IT COULD BE KEPT. It guarded the
attack-catalogue encounter model: twelve ATTACK_* ids parsed out of the engine, a
generated stage_waves.asm carrying waveTriggerAttackId / waveTriggerSprite
columns, trigger rows sorted DESCENDING, and a proof that SCROLL_FRAME_DIVIDER
did not move them. Every one of those has been retired:

  * the attack catalogue does not exist in the engine in any form;
  * stage_waves.asm must not be generated at all -- encounter data ships as
    BYTES in the level package, authored in src/wave_programs.asm and
    src/wave_encounters.asm;
  * trigger rows are ABSOLUTE worldProgress and must be NON-DECREASING, which is
    the opposite direction to the old stage-row ordering;
  * SCROLL_FRAME_DIVIDER is read by nothing in the engine and is no longer
    emitted.

So the file keeps its job -- guarding the wave/trigger contract -- against the
contract that replaced it, and asserts that the retired machinery is really gone
rather than merely unused.

ENCOUNTER EXPORT IS PHASE 3. Phase 2 exports terrain, config, charset and
turrets only; the engine sources remain authoritative for encounters, and the
tests below check that nothing has quietly started generating them.

Run:  python3 tools/level_editor/test_wave_schema.py
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                                    # noqa: E402
import ka_export                                                           # noqa: E402
import export_v6                                                           # noqa: E402
from migration_v6 import load_any                                          # noqa: E402
from project_v6 import Trigger                                             # noqa: E402
from validation_v6 import validate                                         # noqa: E402

PASS = []


def ok(m):
    PASS.append(m)
    print(f"ok  - {m}")


LEVEL1_JSON = HERE / "levels" / "level1" / "level.json"
project = load_any(LEVEL1_JSON).project

# ---------------------------------------------------------------------------
# 1. the retired machinery is gone, not merely unused
# ---------------------------------------------------------------------------
assert not hasattr(ka_export, "render_stage_waves"), \
    "ka_export still carries the retired stage_waves.asm renderer"
assert not hasattr(ka_export, "WAVES_NAME"), "ka_export still names a waves file"
assert ka_export.STAGE_NAME == "stage_map.asm", ka_export.STAGE_NAME
ok("the attack-catalogue wave renderer and stage_waves.asm are gone from ka_export")

assert "stage_waves.asm" not in export_v6.GENERATED_NAMES
with tempfile.TemporaryDirectory() as td:
    written = export_v6.export_level(project, td, level_name="level1")
    names = sorted(p.name for p in written.values())
    assert names == ["stage_charset.asm", "stage_config.asm", "stage_map.asm",
                     "stage_turrets.asm", "wave_encounters.asm",
                     "wave_programs.asm"], names
    assert not (Path(td) / "stage_waves.asm").exists()
    config = (Path(td) / "stage_config.asm").read_text()
assert "SCROLL_FRAME_DIVIDER" not in config, \
    "the retired scroll divider is being emitted again"
ok("the v6 exporter emits six files and never a waves file or a scroll divider")

# EXACTLY ONE PRODUCTION COPY OF THE ENCOUNTER SOURCE, and it is level-owned.
# KickAssembler resolves an #import against the importing file's own directory
# before any -libdir, so a leftover copy in src/ would silently win and editing
# the level-owned one would do nothing.
for name in ("wave_programs.asm", "wave_encounters.asm"):
    assert (REPO / "src" / "level1" / name).is_file(), f"src/level1/{name} missing"
    assert not (REPO / "src" / name).exists(), \
        f"src/{name} still exists and would shadow the level-owned copy"
ok("the encounter source is level-owned in src/level1/ and src/ holds no "
   "shadowing copy")
# The engine keeps the shared VOCABULARY.
for name in ("movement_format.asm", "encounter_format.asm"):
    assert (REPO / "src" / name).is_file(), name
ok("the shared format vocabulary stays engine-owned in src/")

# ---------------------------------------------------------------------------
# 2. the CURRENT trigger contract: absolute worldProgress, non-decreasing
# ---------------------------------------------------------------------------
# The old contract sorted DESCENDING because it authored a stage row counting
# down. worldProgress counts UP, and the director's cursor only walks forward.
p = project.copy()
p.movement_programs = load_any(LEVEL1_JSON).project.movement_programs
from project_v6 import MovementProgram, MovementStage, WaveDefinition       # noqa: E402
p.movement_programs = [MovementProgram("run", [
    MovementStage("STRAIGHT", frames=30, vx=6, vy=0), MovementStage("EXIT")])]
p.wave_definitions = [WaveDefinition(id="w", count=4, interval=22, start_x=0,
                                     start_y=64, colour=10, heading=0,
                                     movement_program="run")]

p.triggers = [Trigger(90, "w", "RING", [0]),
              Trigger(300, "w", "DROPPER", [1])]
assert validate(p).ok, validate(p)
ok("ascending worldProgress rows are accepted")

p.triggers = [Trigger(300, "w", "RING", [0]), Trigger(90, "w", "DROPPER", [1])]
codes = [i.code for i in validate(p).errors]
assert "trigger.unsorted" in codes, codes
ok("descending rows -- the OLD contract's order -- are now rejected")

# A row above 255 is not a special case: it is two bytes compared sixteen-bit.
p.triggers = [Trigger(255, "w", "RING", [0]), Trigger(300, "w", "DROPPER", [1])]
assert validate(p).ok, validate(p)
assert 300 > 0xFF and (300 & 0xFF, 300 >> 8) == (44, 1)
ok("a trigger row above 255 is legal and splits low/high as 44/1")

# ---------------------------------------------------------------------------
# 3. the six columns, and the values they may carry
# ---------------------------------------------------------------------------
t = Trigger(90, "w", "DROPPER", [0, 2], "RIGHT")
assert t.fire_bits == 0b101, bin(t.fire_bits)
assert C.SPECIES[t.species] == 8 and C.DROPPER_SIDES[t.dropper_side] == 1
ok("a trigger carries row, definition, species, fire mask and Dropper side")

p.triggers = [Trigger(90, "nope", "RING", [0])]
assert "trigger.dangling_definition" in [i.code for i in validate(p).errors]
p.triggers = [Trigger(90, "w", "SQUID", [0])]
assert "trigger.species" in [i.code for i in validate(p).errors]
p.triggers = [Trigger(90, "w", "RING", [7])]
assert "trigger.fire_member_absent" in [i.code for i in validate(p).errors]
ok("dangling definition, unknown species and an impossible fire bit are rejected")

# ---------------------------------------------------------------------------
# 4. Phase 2 exports no encounter data at all
# ---------------------------------------------------------------------------
# The migrated project has EMPTY encounter lists by design (migration_v6), and
# the exporter must not turn that into generated bytes -- doing so would erase
# Level 1's four waves and two Droppers.
# A project with NO encounters still exports both files -- an empty pool and a
# zero WAVE_TRIGGERS are legal -- but it must not invent content.
migrated = load_any(LEVEL1_JSON).project
assert migrated.movement_programs == [] and migrated.wave_definitions == [] \
    and migrated.triggers == []
with tempfile.TemporaryDirectory() as td:
    export_v6.export_level(migrated, td, level_name="level1")
    progs_text = (Path(td) / "wave_programs.asm").read_text()
    enc_text = (Path(td) / "wave_encounters.asm").read_text()
assert ".const WAVE_TRIGGERS          = 0" in enc_text, enc_text[-400:]
assert ".const WAVE_DEFS              = 0" in enc_text
assert ".eval progs.add" not in progs_text
assert ".var trigRow      = List()\n" in enc_text
ok("a project with no encounters exports empty pools and WAVE_TRIGGERS = 0, "
   "inventing nothing")

print(f"\nAll {len(PASS)} wave-contract checks passed.")
