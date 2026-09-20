#!/usr/bin/env python3
"""Phase 3: the authoritative engine encounters import into v6 without loss.

THE CENTRAL PROOF IS A ROUND TRIP THROUGH THE MODEL:

    src/wave_programs.asm + src/wave_encounters.asm
        -> asm_decl (bounded reader)
        -> v6 MovementProgram / WaveDefinition / Trigger
        -> reference re-encoding
        -> compared BYTE FOR BYTE against the authoritative build/level1.prg

If the model could not hold something the engine authored, the re-encoded bytes
would differ. Nothing about the comparison depends on the importer's own opinion
of what it read.

Also covers: live triggers only (the columns are zero-padded to 180 and the
padding must not become four-hundred-odd empty encounters), signed and sentinel
conversion, the refusal to overwrite an existing project's encounters, and the
parser failing loudly on source it does not support.

Run:  python3 tools/level_editor/test_v6_import.py
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                                    # noqa: E402
import import_engine_v6 as I                                               # noqa: E402
from asm_decl import AsmSyntaxError, parse_files                           # noqa: E402
from migration_v6 import load_any                                          # noqa: E402
from project_v6 import ProjectV6                                           # noqa: E402
from validation_v6 import validate                                         # noqa: E402

PASS = []
SRC = REPO / "src"
LEVEL1_JSON = HERE / "levels" / "level1" / "level.json"
PRG = REPO / "build" / "level1.prg"


def ok(m, extra=""):
    PASS.append(m)
    print(f"  ok   {m}{' -- ' + extra if extra else ''}")


def eq(label, got, want):
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")
    ok(label, str(got) if not isinstance(got, (list, dict)) else "")


def region(lo, hi):
    prg = PRG.read_bytes()
    base = prg[0] | (prg[1] << 8)
    return prg[2 + lo - base: 2 + hi - base + 1]


# ---------------------------------------------------------------------------
print("=== import the authoritative encounters ===")
r = I.read_encounters(SRC)
progs, defs, trigs = r.movement_programs, r.wave_definitions, r.triggers

# THE EXPECTATION IS THE CANONICAL PROJECT, not Level 1's numbers as they stood
# when this file was written. Importing the ASM and comparing it against the JSON
# is a REAL cross-check -- the exporter wrote one from the other, and if either
# side drifted they would stop agreeing -- and it lets the level be authored.
CANON = json.loads((HERE / "levels" / "level1" / "level.v6.json")
                   .read_text(encoding="utf-8"))

eq("movement programs", len(progs), len(CANON["movementPrograms"]))
eq("movement program ids (from the engine's PROG_* symbols)",
   [p.id for p in progs], [m["id"] for m in CANON["movementPrograms"]])
eq("stages per program", [len(p.stages) for p in progs],
   [len(m["stages"]) for m in CANON["movementPrograms"]])
_records = sum(len(m["stages"]) for m in CANON["movementPrograms"])
eq("total movement records", sum(len(p.stages) for p in progs), _records)
eq("total movement pool bytes",
   sum(len(p.stages) for p in progs) * C.WM_STAGE_SIZE,
   _records * C.WM_STAGE_SIZE)
_off, _at = [], 0
for m in CANON["movementPrograms"]:
    _off.append(_at)
    _at += len(m["stages"]) * C.WM_STAGE_SIZE
eq("program byte offsets", list(I.program_offsets(progs).values()), _off)

# ---- every stage field, program by program --------------------------------
def shape(p):
    out = []
    for s in p.stages:
        if s.kind in C.TIMED_KINDS:
            out.append((s.kind, s.frames, s.vx, s.vy))
        elif s.kind in C.ARC_KINDS:
            out.append((s.kind, s.steps, s.frames_per_step, s.entry_heading))
        else:
            out.append((s.kind,))
    return out


for _i, _m in enumerate(CANON["movementPrograms"]):
    eq(f"{_m['id']} stages match the project", shape(progs[_i]),
       [tuple(v for v in (
            (s["kind"], s.get("frames"), s.get("vx"), s.get("vy"))
            if s["kind"] in C.TIMED_KINDS else
            (s["kind"], s.get("steps"), s.get("framesPerStep"), s.get("entryHeading"))
            if s["kind"] in C.ARC_KINDS else (s["kind"],)))
        for s in _m["stages"]])

ok("WM_HEAD_CONT ($ff) became the symbolic \"CONT\" on the S-turn's joining arc")
assert progs[1].stages[0].entry_heading == 12
ok("...and the arc BEFORE it kept its explicit entry heading 12")
for p in progs:
    assert p.stages[-1].kind == "EXIT", p.id
ok("every program terminates in EXIT")

# ---- wave definitions -----------------------------------------------------
eq("wave definitions", len(defs), len(CANON["waveDefinitions"]))
eq("wave definition ids (from WAVE_DEF_* symbols)",
   [d.id for d in defs], [d["id"] for d in CANON["waveDefinitions"]])
for _i, _d in enumerate(CANON["waveDefinitions"]):
    eq(f"{_d['id']} definition matches the project", defs[_i].to_dict(), _d)
ok("every definition resolves its program by ID, not by byte offset")

# ---- triggers -------------------------------------------------------------
_ct = CANON["triggers"]
eq("live triggers", len(trigs), len(_ct))
eq("trigger rows", [t.world_progress for t in trigs],
   [d["worldProgress"] for d in _ct])
eq("species sequence", [t.species for t in trigs], [d["species"] for d in _ct])
eq("definition references", [t.wave_definition for t in trigs],
   [d["waveDefinition"] for d in _ct])
eq("fire masks as member indices", [t.fire_mask for t in trigs],
   [d["fireMask"] for d in _ct])
eq("Dropper sides", [t.dropper_side for t in trigs],
   [d["dropperSide"] for d in _ct])
dropper_sides = [t.dropper_side for t in trigs if t.species == "DROPPER"]
eq("...and every Dropper's side is the one the project authored", dropper_sides,
   [d["dropperSide"] for d in _ct if d["species"] == "DROPPER"])

# THE COLUMNS ARE PADDED TO 180 AND THE PADDING IS NOT CONTENT. A zero row, a
# zero definition index and a zero species are all individually legal values, so
# only WAVE_TRIGGERS distinguishes a live entry from the tail.
eq("only WAVE_TRIGGERS live entries were imported", len(trigs), len(_ct))
assert len(trigs) < C.MAX_TRIGGERS
ok(f"the {C.MAX_TRIGGERS}-slot zero padding was not imported as encounters")

# ---------------------------------------------------------------------------
print("\n=== the reference re-encoding matches the authoritative package ===")
pool = I.reference_encode_movement_pool(progs)
# THE REGION BASES ARE FIXED BY src/levelpkg.asm; the LENGTHS follow the content.
_POOL_BASE, _DEF_BASE = 0xF532, 0xF632
eq("re-encoded movement pool bytes", len(pool), _records * C.WM_STAGE_SIZE)
assert pool == region(_POOL_BASE, _POOL_BASE + len(pool) - 1), "movement pool differs"
ok("*** all 52 movement pool bytes are IDENTICAL to build/level1.prg ***")

wd = I.reference_encode_wave_definitions(defs, progs)
eq("re-encoded wave definition bytes", len(wd),
   len(CANON["waveDefinitions"]) * C.WAVEDEF_SIZE)
assert wd == region(_DEF_BASE, _DEF_BASE + len(wd) - 1), "wave definitions differ"
ok("*** all 40 wave definition bytes are IDENTICAL ***")

tc = I.reference_encode_trigger_columns(trigs, defs)
eq("re-encoded trigger column bytes", len(tc), C.MAX_TRIGGERS * C.LEVELPKG_TRIG_COLS)
auth_tc = region(0xF736, 0xFB6D)
assert tc == auth_tc, "trigger columns differ"
ok("*** all 1080 trigger column bytes are IDENTICAL, padding included ***")

# field by field, so a failure says which column
slots = C.MAX_TRIGGERS
for i, name in enumerate(("rowLo", "rowHi", "def", "species", "fire", "side")):
    a = auth_tc[i * slots: i * slots + len(trigs)]
    b = tc[i * slots: i * slots + len(trigs)]
    assert a == b, name
    ok(f"column {name} live entries identical", str(list(b)))
for i in range(6):
    tail = auth_tc[i * slots + len(trigs): (i + 1) * slots]
    assert set(tail) == {0}, i
ok("every column's tail is zero in the authoritative package, as the importer assumed")

# fire mask: v6 semantics -> engine byte
eq("fire mask member indices re-encode to the engine bytes",
   [t.fire_bits for t in trigs],
   [sum(1 << m for m in d["fireMask"]) for d in _ct])

# ---------------------------------------------------------------------------
print("\n=== overlay onto the Level 1 project ===")
project = load_any(LEVEL1_JSON).project
KEYS = ("stage", "palette", "glyphs", "metatileDefs", "map", "turrets",
        "levelMetatileSet", "name")
before = {k: json.dumps(project.to_dict().get(k)) for k in KEYS}
assert project.movement_programs == [] and project.wave_definitions == [] \
    and project.triggers == []
ok("the migrated project starts with empty encounter lists, as Phase 1 left it")

I.import_encounters(project, SRC)
after = {k: json.dumps(project.to_dict().get(k)) for k in KEYS}
for k in KEYS:
    assert before[k] == after[k], f"{k} changed during encounter import"
ok("terrain, palette, glyphs, metatiles, map, turrets, stage and noSpawnRow "
   "are byte-identical after import")
# THE MIGRATED v5 PROJECT, not the canonical v6 one -- its terrain is whatever
# levels/level1/level.json holds, and the point here is that encounter import
# leaves all of it alone.
_V5 = json.loads(LEVEL1_JSON.read_text(encoding="utf-8"))
eq("stage rows still", project.stage.metatile_rows, len(_V5["metatileRows"]))
eq("noSpawnRow still", project.stage.no_spawn_row,
   C.default_no_spawn_row(len(_V5["metatileRows"])))
eq("turrets still", len(project.turrets),
   len([o for o in _V5["objects"] if o.get("type") == "turret"]))

v = validate(project)
if not v.ok or v.warnings:
    raise AssertionError(f"the populated project does not validate cleanly:\n{v}")
ok("the populated project validates with no errors and no warnings")

# refuses to overwrite silently
try:
    I.import_encounters(project, SRC)
    raise AssertionError("a second import should have been refused")
except I.EncounterImportError as exc:
    assert "replace=True" in str(exc)
ok("a second import is REFUSED rather than silently overwriting")
I.import_encounters(project, SRC, replace=True)
eq("...and replace=True is accepted", len(project.triggers), len(_ct))

# ---------------------------------------------------------------------------
print("\n=== determinism ===")
a = project.to_json()
second = load_any(LEVEL1_JSON).project
I.import_encounters(second, SRC)
assert second.to_json() == a, "importing twice gave different JSON"
ok("importing twice from identical source is byte-identical", f"{len(a)} bytes")
assert ProjectV6.from_json(a).to_json() == a
ok("save -> load -> save is a fixed point with encounters present")
for banned in (str(REPO), "/Users/", "wave_programs.asm", "progAt", "byteOffset"):
    assert banned not in a, banned
ok("no engine paths, source filenames or derived byte offsets leak into the JSON")
doc = json.loads(a)
assert "movementProgram" in doc["waveDefinitions"][0]
assert isinstance(doc["waveDefinitions"][0]["movementProgram"], str)
ok("a definition stores a program ID, not an offset")
assert doc["triggers"][0]["species"] == "RING"
assert doc["triggers"][3]["dropperSide"] == "RIGHT"
assert doc["triggers"][0]["fireMask"] == [0, 2]
ok("triggers are stored as semantic objects, not six physical columns")

# ---------------------------------------------------------------------------
print("\n=== malformed source fails loudly ===")
# The two halves live apart since Phase 4: the format vocabulary is engine-owned
# in src/, the authored content is level-owned in src/level1/. The scratch copies
# below put them in ONE directory, which read_engine_source still accepts.
LEVEL = SRC / I.DEFAULT_LEVEL_DIR
BASE = {n: (SRC / n).read_text(encoding="utf-8") for n in I.FORMAT_FILES}
BASE.update({n: (LEVEL / n).read_text(encoding="utf-8") for n in I.CONTENT_FILES})


def with_source(**overrides):
    """A scratch src/ whose named files are replaced, everything else authentic."""
    d = Path(tempfile.mkdtemp())
    for name, text in BASE.items():
        (d / name).write_text(overrides.get(name, text), encoding="utf-8")
    return d


def sub(text, pattern, repl, what):
    """A fixture edit that MUST match, so a formatting change breaks the fixture
    loudly instead of silently testing nothing."""
    new_text, n = re.subn(pattern, repl, text, count=1)
    assert n == 1, f"fixture pattern never matched ({what}): {pattern}"
    return new_text


def rejects(label, expect, **overrides):
    d = with_source(**overrides)
    try:
        I.read_encounters(d)
    except (I.EncounterImportError, AsmSyntaxError) as exc:
        assert expect.lower() in str(exc).lower(), f"{label}: message was {exc}"
        ok(label, str(exc).splitlines()[0][:70])
        return
    finally:
        shutil.rmtree(d, ignore_errors=True)
    raise AssertionError(f"{label}: import was accepted")


progs_src = BASE["wave_programs.asm"]
enc_src = BASE["wave_encounters.asm"]

rejects("an unknown movement opcode", "opcode",
        **{"wave_programs.asm": sub(progs_src, r"WM_STRAIGHT, 34, 6, 0", "9, 34, 6, 0",
                                    "sweep straight")})
rejects("a stage that is not four values", "4 values",
        **{"wave_programs.asm": sub(progs_src, r"WM_STRAIGHT, 34, 6, 0\)\)",
                                    "WM_STRAIGHT, 34, 6))", "sweep straight")})
rejects("a missing PROG_* mapping", "PROG_",
        **{"wave_programs.asm": sub(progs_src, r"\.const\s+PROG_LOOP\s*=\s*3", "",
                                    "PROG_LOOP const")})
rejects("a duplicate PROG_* value", "ambiguous",
        **{"wave_programs.asm": sub(progs_src, r"(\.const\s+PROG_LOOP\s*=\s*)3",
                                    r"\g<1>0", "PROG_LOOP value")})
rejects("a definition naming a program that does not exist", "movement program index",
        **{"wave_encounters.asm": sub(enc_src, r"PROG_LOOP\)", "9)",
                                      "loop definition program ref")})
rejects("a trigger naming a definition that does not exist", "wave definition index",
        **{"wave_encounters.asm": sub(enc_src, r"\.add\(WAVE_DEF_SWEEP,", ".add(9,",
                                      "trigDef first entry")})
rejects("an unknown species constant", "species",
        **{"wave_encounters.asm": sub(enc_src,
            r"(\.var\s+trigSpecies\s*=\s*List\(\)\.add\()SPECIES_RING,", r"\g<1>3,",
            "trigSpecies first entry")})
rejects("an unknown Dropper side", "side",
        **{"wave_encounters.asm": sub(enc_src,
            r"(\.var\s+trigSide\s*=\s*List\(\)\.add\()DROP_SIDE_LEFT,", r"\g<1>7,",
            "trigSide first entry")})
rejects("mismatched trigger column lengths", "same length",
        # DROP THE LAST ROW, whatever the level authors, so the columns disagree.
        **{"wave_encounters.asm": sub(
            enc_src, r"(\.var\s+trigRow\s*=\s*List\(\)\.add\([^)]*), *\d+\)",
            r"\g<1>)", "trigRow last entry")})
rejects("a WAVE_TRIGGERS count beyond the authored rows", "only",
        **{"wave_encounters.asm": sub(enc_src, r"(\.const\s+WAVE_TRIGGERS\s*=\s*)\d+",
                                      r"\g<1>99", "WAVE_TRIGGERS")})
rejects("WAVE_DEFS disagreeing with the definition list", "WAVE_DEFS",
        **{"wave_encounters.asm": sub(enc_src, r"(\.const\s+WAVE_DEFS\s*=\s*)(\d+)",
                                      lambda m: m.group(1) + str(int(m.group(2)) - 1),
                                      "WAVE_DEFS")})
# The sweep definition's launch heading is its penultimate field, the 0 just
# before PROG_SWEEP. $ff is legal on an ARC's entry heading and illegal here.
rejects("$ff where a launch heading is structurally required", "heading",
        **{"wave_encounters.asm": sub(enc_src, r"0,(\s*(?://[^\n]*)?\n\s*)PROG_SWEEP\)",
                                      r"255,\g<1>PROG_SWEEP)", "sweep launch heading")})
rejects("an unknown identifier", "unknown identifier",
        **{"wave_programs.asm": sub(progs_src, r"WM_ARC, 16, 4, 0", "WM_ARC, WM_NOPE, 4, 0",
                                    "sweep arc")})
rejects("an expression outside the supported subset", "unsupported character",
        **{"wave_encounters.asm": sub(
            enc_src, r"(\.var\s+trigRow\s*=\s*List\(\)\.add\()(\d+)",
            r"\g<1>\g<2> << 1", "trigRow first entry")})
rejects("a duplicate declaration", "already defined",
        **{"wave_encounters.asm": enc_src + "\n.const WAVE_TRIGGERS = 5\n"})
rejects("a velocity too large for the signed byte it is emitted in", "signed byte",
        **{"wave_programs.asm": sub(progs_src, r"WM_STRAIGHT, 34, 6, 0",
                                    "WM_STRAIGHT, 34, 200, 0", "sweep straight")})
rejects("a trigger row beyond sixteen bits", "sixteen bits",
        **{"wave_encounters.asm": sub(
            enc_src, r"(\.var\s+trigRow\s*=\s*List\(\)\.add\([^)]*), *\d+\)",
            r"\g<1>, 70000)", "trigRow last entry")})

# the reader refuses unsupported .eval forms outright
d = with_source(**{"wave_programs.asm": progs_src + "\n.eval progs = 3\n"})
try:
    parse_files([d / n for n in I.FORMAT_FILES + I.CONTENT_FILES])
    raise AssertionError("unsupported .eval form accepted")
except AsmSyntaxError as exc:
    assert "NAME.add" in str(exc)
    ok("an unsupported .eval form is rejected", str(exc).splitlines()[0][:60])
finally:
    shutil.rmtree(d, ignore_errors=True)

print(f"\nAll {len(PASS)} import checks passed.")
