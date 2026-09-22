#!/usr/bin/env python3
"""Phase 4: the complete engine <-> editor round trip closes.

    canonical v6 project -> exporter -> generated ASM -> importer -> v6 model

must be a FIXED POINT, and the generated ASM must build the pre-Phase-4 binaries
byte for byte. This file proves the loop; test_v6_export.py proves the binaries.

Also proves the capacity refusals the package layout depends on -- an oversized
movement pool, a 27th wave definition, a 181st trigger, a trigger at the no-spawn
row -- because the exporter writes production source and must never emit a level
the assembler would reject or, worse, one it would accept and truncate.

ONE PRODUCTION COPY. src/level1/ owns the encounter source; src/ owns only the
shared vocabulary. KickAssembler resolves an #import against the importing file's
own directory before any -libdir, so a stray src/wave_programs.asm would shadow
the level-owned one silently -- asserted here.

Run:  python3 tools/level_editor/test_v6_phase4_roundtrip.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                                    # noqa: E402
import export_v6                                                           # noqa: E402
import import_engine_v6 as I                                               # noqa: E402
from project_v6 import (MovementProgram, MovementStage, ProjectV6,         # noqa: E402
                        Trigger, WaveDefinition)
from validation_v6 import validate                                         # noqa: E402

PASS = []
SRC = REPO / "src"
LEVEL = SRC / "level1"
CANONICAL = HERE / "levels" / "level1" / "level.v6.json"


def ok(m, extra=""):
    PASS.append(m)
    print(f"  ok   {m}{' -- ' + extra if extra else ''}")


def eq(label, got, want):
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")
    ok(label, str(got) if not isinstance(got, (list, dict)) else "")


# ---------------------------------------------------------------------------
print("=== ownership: exactly one production copy ===")
for name in export_v6.ENCOUNTER_NAMES:
    assert (LEVEL / name).is_file(), f"src/level1/{name} missing"
    assert not (SRC / name).exists(), \
        f"src/{name} still exists and would SHADOW the level-owned copy"
ok("the encounter source is level-owned and src/ holds no shadowing copy")
for name in ("movement_format.asm", "encounter_format.asm"):
    assert (SRC / name).is_file() and not (LEVEL / name).exists(), name
ok("the shared format vocabulary is engine-owned and not duplicated per level")
eq("generated file count", len(export_v6.GENERATED_NAMES), 6)

# ---------------------------------------------------------------------------
print("\n=== the canonical project ===")
project = ProjectV6.load(CANONICAL)
result = validate(project)
# ERRORS BLOCK AN EXPORT; WARNINGS DO NOT. This used to demand zero of both,
# which made an advisory note about an authored level -- an unused metatile, a
# generous quiet zone -- fail the round-trip proof. Warnings are printed so they
# stay visible.
if not result.ok:
    raise AssertionError(f"the canonical project has errors:\n{result}")
ok("levels/level1/level.v6.json validates with no errors",
   f"{len(result.warnings)} advisory warning(s)")
for _w in result.warnings:
    print(f"       note: {_w}")

doc = json.loads(CANONICAL.read_text(encoding="utf-8"))
eq("movement programs", len(project.movement_programs), len(doc["movementPrograms"]))
eq("wave definitions", len(project.wave_definitions), len(doc["waveDefinitions"]))
eq("triggers", len(project.triggers), len(doc["triggers"]))
eq("trigger rows", [t.world_progress for t in project.triggers],
   [d["worldProgress"] for d in doc["triggers"]])
eq("stage rows", project.stage.metatile_rows, doc["stage"]["metatileRows"])
eq("noSpawnRow", project.stage.no_spawn_row, doc["stage"]["noSpawnRow"])
eq("turrets", len(project.turrets), len(doc["turrets"]))
assert doc["formatVersion"] == 6
for banned in ("progAt", "byteOffset", "offset", "rowLo", "rowHi"):
    assert banned not in CANONICAL.read_text(encoding="utf-8"), banned
ok("the project stores no derived physical offsets or column names")
eq("a definition references its program by id",
   doc["waveDefinitions"][0]["movementProgram"], "sweep")

# ---------------------------------------------------------------------------
print("\n=== export -> import -> export is a fixed point ===")
tmp = tempfile.TemporaryDirectory()
A = Path(tmp.name) / "a"
B = Path(tmp.name) / "b"
export_v6.export_level(project, A, level_name="level1", carry_enemies_from=LEVEL)

back = ProjectV6.load(CANONICAL)
back.movement_programs, back.wave_definitions, back.triggers = [], [], []
I.import_encounters(back, SRC, level_dir=A)
eq("re-imported movement programs", [p.id for p in back.movement_programs],
   [p.id for p in project.movement_programs])
# THE ENGINE RECORDS ARE THE FIXED POINT, not the authored form. A level
# package carries four-byte stage records and nothing else, so a semantic
# program re-imported from generated ASM comes back RAW -- its `segments` are
# editor-side authoring data that the C64 never sees. Comparing whole dicts
# made this test fail the moment a program was authored semantically, for a
# difference that is the design rather than a fault.
assert ([p.id for p in back.movement_programs]
        == [p.id for p in project.movement_programs])
assert ([[s.to_dict() for s in p.stages] for p in back.movement_programs]
        == [[s.to_dict() for s in p.stages] for p in project.movement_programs]), \
    "the engine records did not survive export -> import"
assert not any(p.is_semantic for p in back.movement_programs), \
    "the importer invented authoring data the package does not carry"
assert json.dumps(back.to_dict()["waveDefinitions"]) == \
       json.dumps(project.to_dict()["waveDefinitions"])
assert json.dumps(back.to_dict()["triggers"]) == \
       json.dumps(project.to_dict()["triggers"])
ok("generated ASM -> importer reproduces every engine record exactly")

export_v6.export_level(back, B, level_name="level1", carry_enemies_from=LEVEL)
for name in export_v6.GENERATED_NAMES:
    if (A / name).read_bytes() != (B / name).read_bytes():
        raise AssertionError(f"{name} is not a byte fixed point")
ok("...and re-exporting reproduces BYTE-IDENTICAL ASM, all six files")

# the production files are themselves that fixed point
for name in export_v6.GENERATED_NAMES:
    if (A / name).read_bytes() != (LEVEL / name).read_bytes():
        raise AssertionError(f"src/level1/{name} is not what the exporter produces")
ok("the committed src/level1/ files ARE the exporter's output, byte for byte")

# JSON fixed point
text = CANONICAL.read_text(encoding="utf-8")
assert ProjectV6.from_json(text).to_json() == text
ok("v6 JSON save -> load -> save is a fixed point", f"{len(text)} bytes")

# ---------------------------------------------------------------------------
print("\n=== the generated encounter representation ===")
progs_text = (LEVEL / "wave_programs.asm").read_text()
enc_text = (LEVEL / "wave_encounters.asm").read_text()

for needed in ("#importonce", '#import "movement_format.asm"', ".var progs = List()",
               ".var progAt = List()", ".var progBytes = 0", ".for (var p = 0"):
    assert needed in progs_text, needed
ok("wave_programs.asm declares progs, progAt and progBytes as the engine expects")
eq("PROG_* constants", [f"PROG_{p.id.upper()}" for p in project.movement_programs],
   [l.split()[1] for l in progs_text.splitlines() if l.startswith(".const PROG_")])
assert "WM_HEAD_CONT" in progs_text
ok("the CONT sentinel is emitted symbolically, not as $ff")
assert f".if (progBytes > {C.LEVELPKG_MOVE_MAX})" in progs_text
ok("the one-byte-cursor guard is carried into the generated file")

for needed in ("#importonce", '#import "encounter_format.asm"',
               '#import "wave_programs.asm"', ".const WAVEDEF_SIZE = 10",
               ".var waveDefs = List()", ".var trigRow", ".var trigDef",
               ".var trigSpecies", ".var trigSide", ".var trigFire",
               ".const WAVE_TRIGGERS"):
    assert needed in enc_text, needed
ok("wave_encounters.asm declares all six trigger columns and the definitions")
assert "SPECIES_RING" in enc_text and "DROP_SIDE_RIGHT" in enc_text
ok("species and sides are emitted symbolically")
assert "%00000101" in enc_text
ok("fire masks are emitted as binary literals over member index")
assert f".const WAVE_TRIGGERS          = {len(doc['triggers'])}" in enc_text
ok("WAVE_TRIGGERS is the LIVE count, not the 180-slot capacity")
assert "trigRowLo" not in enc_text and "interleav" not in enc_text.lower()
ok("no seven-byte interleaved record was introduced")

# ---------------------------------------------------------------------------
print("\n=== capacity and boundary refusals ===")
def refuse(label, code, mutate):
    p = ProjectV6.load(CANONICAL)
    mutate(p)
    r = validate(p)
    assert code in [i.code for i in r.errors], \
        f"{label}: expected {code}, got {[i.code for i in r.errors]}"
    try:
        export_v6.export_level(p, Path(tmp.name) / "never", level_name="x")
        raise AssertionError(f"{label}: export was NOT refused")
    except export_v6.ExportRefused:
        pass
    ok(label, code)


def big_pool(p):
    p.movement_programs = [MovementProgram(f"p{i}", [
        MovementStage("STRAIGHT", frames=1, vx=1, vy=1), MovementStage("EXIT")])
        for i in range(33)]
    for d in p.wave_definitions:
        d.movement_program = "p0"


refuse("a movement pool over 256 bytes is refused", "movement.pool_overflow", big_pool)
refuse("a 27th wave definition is refused", "wavedef.too_many",
       lambda p: p.wave_definitions.extend(
           WaveDefinition(id=f"x{i}", count=1, interval=1, start_x=0, start_y=0,
                          colour=1, heading=0, movement_program="sweep")
           for i in range(23)))
refuse("a 181st trigger is refused", "trigger.too_many",
       lambda p: p.triggers.extend(
           Trigger(200 + i, "sweep", "RING" if i % 2 else "DROPPER", [0])
           for i in range(177)))
# DERIVED FROM THE PROJECT, NOT FROM A REMEMBERED ROW NUMBER. These test the
# noSpawn boundary RULE, so they have to move a trigger to wherever that
# boundary currently is -- pinning it to 340 made them a test of one level's
# content, and once the authored level grew they started failing for the wrong
# reason (the moved trigger landed out of order and tripped a different rule
# first). Moving the LAST trigger keeps the list sorted so the rule under test
# is the one that fires.
refuse("a trigger AT noSpawnRow is refused", "trigger.at_or_after_no_spawn",
       lambda p: setattr(p.triggers[-1], "world_progress",
                         p.stage.no_spawn_row))
refuse("a trigger after noSpawnRow is refused", "trigger.at_or_after_no_spawn",
       lambda p: setattr(p.triggers[-1], "world_progress",
                         p.stage.no_spawn_row + 1))
refuse("descending trigger rows are refused", "trigger.unsorted",
       lambda p: setattr(p.triggers[-1], "world_progress",
                         max(0, p.triggers[0].world_progress - 1)))
refuse("a dangling movement-program reference is refused",
       "wavedef.dangling_program",
       lambda p: setattr(p.wave_definitions[0], "movement_program", "nope"))
refuse("a program that does not end in EXIT is refused", "movement.no_exit",
       lambda p: p.movement_programs[0].stages.__setitem__(
           -1, MovementStage("STRAIGHT", frames=5, vx=1, vy=1)))

# an id that cannot become an assembler symbol
p = ProjectV6.load(CANONICAL)
p.movement_programs[0].id = "Not A Symbol"
for d in p.wave_definitions:
    if d.movement_program == "sweep":
        d.movement_program = "Not A Symbol"
try:
    export_v6.render_wave_programs(p, "level1")
    raise AssertionError("a non-symbol id was accepted")
except export_v6.ExportRefused as exc:
    assert "assembler symbol" in str(exc)
ok("an id that cannot become an assembler symbol is refused", "export.bad_id")

# ---------------------------------------------------------------------------
print("\n=== an empty-encounter project exports legally, inventing nothing ===")
empty = ProjectV6.load(CANONICAL)
empty.movement_programs, empty.wave_definitions, empty.triggers = [], [], []
assert validate(empty).ok
E = Path(tmp.name) / "empty"
export_v6.export_level(empty, E, level_name="level1", carry_enemies_from=LEVEL)
et = (E / "wave_encounters.asm").read_text()
assert ".const WAVE_TRIGGERS          = 0" in et
assert ".const WAVE_DEFS              = 0" in et
assert ".eval progs.add" not in (E / "wave_programs.asm").read_text()
ok("a level with no encounters is legal and emits empty pools")

print(f"\nAll {len(PASS)} Phase 4 round-trip checks passed.")
