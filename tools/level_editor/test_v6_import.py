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
LEVEL1_JSON = HERE / "fixtures" / "legacy_v5" / "level1" / "level.json"
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
# THE DOCUMENT THE EDITOR LOADS IS THE LEVEL PLUS THE SHARED LIBRARY.
# Movement programs and wave definitions were lifted out of every level file
# into encounter_library.v6.json, so a test that wants "what the editor has"
# has to read both. Merging them here keeps every assertion below meaning what
# it always meant, rather than scattering the change over twenty index sites.
def _with_shared(_doc):
    import json as _j
    _lib = _j.loads((HERE / "encounter_library.v6.json").read_text(encoding="utf-8"))
    return {**_doc, "movementPrograms": _lib["movementPrograms"],
            "waveDefinitions": _lib["waveDefinitions"]}

CANON = _with_shared(json.loads((HERE / "levels" / "level1" / "level.v6.json")
                   .read_text(encoding="utf-8")))

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
# SPECIES: COMPARED AS ENGINE ROWS, NOT AS NAMES.
#
# The importer reads the GENERATED ASSEMBLY, which carries a species ROW OFFSET
# (SPECIES_RING / SPECIES_DROPPER / SPECIES_SQUARE) and cannot know which roster
# identity the level put in that slot. The project carries the IDENTITY. So the
# two spell the same enemy differently -- the importer says "SQUARE" where the
# project says "SPACE_WHISK" -- and comparing the strings failed while the
# import was byte-perfect (the re-encoding below proves it).
#
# What the import must preserve is the row, which is what the package carries.
# THE IDENTITIES OF THE CANONICAL PROJECT, which is where the identity spelling
# comes from. (LEVEL1_JSON is the frozen legacy-v5 fixture and predates
# identities entirely, so it would resolve SPACE_WHISK to None.)
_identities = [n for n in (CANON.get("enemySlots")
                          or C.DEFAULT_ENEMY_IDENTITIES)]


def _row_of(name):
    """The engine row a species name resolves to, legacy name or identity."""
    if name in C.LEGACY_SPECIES_ORDER:
        return C.LEGACY_SPECIES_ORDER.index(name) * C.ENEMY_ANIM_STEPS
    return C.identity_row(name, _identities)


eq("species sequence, as the ENGINE ROWS both spellings resolve to",
   [_row_of(t.species) for t in trigs],
   [_row_of(d["species"]) for d in _ct])
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
_POOL_BASE = 0xF530 + C.LEVELPKG_STAGE_MAX
_DEF_BASE = _POOL_BASE + C.LEVELPKG_MOVE_MAX
eq("re-encoded movement pool bytes", len(pool), _records * C.WM_STAGE_SIZE)
assert pool == region(_POOL_BASE, _POOL_BASE + len(pool) - 1), "movement pool differs"
ok(f"*** all {len(pool)} movement pool bytes are IDENTICAL to "
   f"build/level1.prg ***")

wd = I.reference_encode_wave_definitions(defs, progs)
eq("re-encoded wave definition bytes", len(wd),
   len(CANON["waveDefinitions"]) * C.WAVEDEF_SIZE)
assert wd == region(_DEF_BASE, _DEF_BASE + len(wd) - 1), "wave definitions differ"
ok(f"*** all {len(wd)} wave definition bytes are IDENTICAL ***")

tc = I.reference_encode_trigger_columns(trigs, defs,
                                        identities=_identities)
eq("re-encoded trigger column bytes", len(tc), C.MAX_TRIGGERS * C.LEVELPKG_TRIG_COLS)
# THE REGION IS DERIVED from the reservation: slots x columns, based where
# src/levelpkg.asm puts it. `0xF736` and `0xFB6D` were transcribed, and the
# second of them moves every time a column is added.
_TRIG_BASE = _DEF_BASE + C.LEVELPKG_WAVEDEF_MAX
_TRIG_BYTES = C.MAX_TRIGGERS * C.LEVELPKG_TRIG_COLS
auth_tc = region(_TRIG_BASE, _TRIG_BASE + _TRIG_BYTES - 1)
assert tc == auth_tc, "trigger columns differ"
ok(f"*** all {_TRIG_BYTES} trigger column bytes are IDENTICAL, padding "
   f"included ***")

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
# NO ERRORS, AND NO WARNING OF A KIND THIS FILE CANNOT ACCOUNT FOR.
#
# The exact warning SET used to be frozen here -- two named discontinuities in
# `linger`, by program id and stage index. Both of those are still true, but the
# set also picks up a `wavedef.unused` for every shared wave definition the
# current level does not happen to point a trigger at, and that is authoring:
# the shared library holds the vocabulary for two levels, so an unreferenced
# definition is expected and moves about as either level is authored.
#
# So the claim is by KIND. No errors at all, and every warning is one of the two
# advisory kinds an import can legitimately raise about authored shape. A
# structural warning -- a dangling reference, a budget, a range -- would still
# fail here, which is what this check is for.
# The Dropper advisories are this category too: a project imported from an
# engine authored under the Dropper+escort model legitimately carries a fire
# mask and a multi-member definition on its Dropper triggers, both of which
# are now inert rather than wrong. See validation_v6._validate_triggers.
_ADVISORY = {"movement.discontinuity", "wavedef.unused",
             "trigger.dropper_fire_mask_ignored",
             "trigger.dropper_definition_count"}
_unexpected = [(i.code, i.path) for i in v.warnings if i.code not in _ADVISORY]
if not v.ok or _unexpected:
    raise AssertionError(f"the populated project does not validate cleanly:\n{v}")
_kinds = sorted({i.code for i in v.warnings})
ok("the populated project validates with no errors, and every warning is an "
   f"advisory about authored shape ({', '.join(_kinds) or 'none'})")
# THE DISCONTINUITY RULE STILL FIRES ON THE IMPORTED PROGRAMS, or the check
# above would be satisfied by a validator that had quietly stopped looking.
assert any(i.code == "movement.discontinuity" for i in v.warnings), \
    "the imported movement programs raised no continuity warning at all"
ok("...and the continuity rule did run over the imported programs",
   f"{sum(1 for i in v.warnings if i.code == 'movement.discontinuity')} finding(s)")

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
# STORED SEMANTICALLY, whatever the values happen to be. These were three
# literals -- species "RING_3" at index 0, side "RIGHT" at index 3, fire mask
# [0, 2] at index 0 -- and every one of them is a reading of Level 1. What the
# JSON must show is that each field is a NAME or a MEMBER LIST rather than the
# physical byte the package carries.
_t0 = doc["triggers"][0]
assert isinstance(_t0["species"], str) and not _t0["species"].isdigit()
assert all(t["dropperSide"] in C.DROPPER_SIDES for t in doc["triggers"])
assert all(isinstance(t["fireMask"], list)
           and all(isinstance(m, int) for m in t["fireMask"])
           for t in doc["triggers"])
assert all(t["fireMode"] in C.FIRE_MODES for t in doc["triggers"])
assert all(t["colourMode"] in C.COLOUR_MODES for t in doc["triggers"])
assert all(t["speed"] in C.SPEED_CHOICES for t in doc["triggers"])
ok("triggers are stored as semantic objects, not as the package's nine physical "
   "columns",
   f"species {_t0['species']!r}, side {_t0['dropperSide']!r}, "
   f"mask {_t0['fireMask']}, mode {_t0['fireMode']!r}, speed {_t0['speed']}")
# AND THE SPEED COLUMN SURVIVES THE ROUND TRIP. It did not: import_triggers
# ignored trigSpeed entirely, so a level authored at 1.50x re-imported at 1.00x
# without a word. The engine's own column is the expectation.
_asm_speed = list(parse_files(
    [SRC / n for n in I.FORMAT_FILES]
    + [SRC / I.DEFAULT_LEVEL_DIR / n for n in I.CONTENT_FILES]).list_("trigSpeed"))
eq("...and every trigger's authored movement speed survived the import",
   [t["speed"] for t in doc["triggers"]], _asm_speed)

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

# ---------------------------------------------------------------------------
# THE CORRUPTION FIXTURES ARE STRUCTURAL, NOT LITERAL.
#
# They used to name authored values: `WM_STRAIGHT, 34, 6, 0`, `WAVE_DEF_SWEEP`,
# `SPECIES_RING`, `.const PROG_LOOP = 3`, `PROG_SWEEP)`. Every one of those is a
# reading of Level 1 as it stood, and `sub()` asserts its pattern matched -- so
# re-authoring the level did not weaken these proofs, it stopped them running
# at all, with an AssertionError from the fixture rather than a result.
#
# The helpers below say WHERE rather than WHAT: the first stage record of a kind,
# the first entry of a named column, the last PROG_* constant. The corruption is
# identical and the fixture survives any authoring.
# ---------------------------------------------------------------------------
def first_record(text, kind):
    """(whole match, the record's four fields) for the first `kind` record."""
    m = re.search(rf"\.add\(List\(\)\.add\({kind}, *(-?\w+), *(-?\w+), *(-?\w+)\)\)",
                  text)
    assert m, f"no {kind} record in the generated movement pool"
    return m


def break_record(text, kind, new_body, what):
    """Replace the first `kind` record's whole `.add(...)` body."""
    m = first_record(text, kind)
    return sub(text, re.escape(m.group(0)),
               f".add(List().add({new_body}))", what)


def first_column_entry(text, column):
    """The first argument of `.var <column> = List().add(...)`."""
    m = re.search(rf"(\.var\s+{column}\s*=\s*List\(\)\.add\()([^,)]+)", text)
    assert m, f"no {column} column in the generated encounter list"
    return m


def break_column(text, column, value, what):
    """Replace the first entry of a named trigger column."""
    m = first_column_entry(text, column)
    return sub(text, re.escape(m.group(0)), m.group(1) + str(value), what)


def last_prog_const(text):
    """(name, value) of the LAST `.const PROG_* = n`, which always exists."""
    all_ = re.findall(r"\.const\s+(PROG_\w+)\s*=\s*(\d+)", text)
    assert all_, "no PROG_* constants in the generated movement pool"
    return all_[-1][0], int(all_[-1][1])

_LAST_PROG, _LAST_PROG_N = last_prog_const(progs_src)

_S = first_record(progs_src, "WM_STRAIGHT")
rejects("an unknown movement opcode", "opcode",
        **{"wave_programs.asm": break_record(
            progs_src, "WM_STRAIGHT",
            f"9, {_S.group(1)}, {_S.group(2)}, {_S.group(3)}",
            "first STRAIGHT record")})
rejects("a stage that is not four values", "4 values",
        **{"wave_programs.asm": break_record(
            progs_src, "WM_STRAIGHT",
            f"WM_STRAIGHT, {_S.group(1)}, {_S.group(2)}",
            "first STRAIGHT record")})
rejects("a missing PROG_* mapping", "PROG_",
        **{"wave_programs.asm": sub(
            progs_src, rf"\.const\s+{_LAST_PROG}\s*=\s*{_LAST_PROG_N}", "",
            f"{_LAST_PROG} const")})
rejects("a duplicate PROG_* value", "ambiguous",
        **{"wave_programs.asm": sub(
            progs_src, rf"(\.const\s+{_LAST_PROG}\s*=\s*){_LAST_PROG_N}",
            r"\g<1>0", f"{_LAST_PROG} value")})
rejects("a definition naming a program that does not exist", "movement program index",
        **{"wave_encounters.asm": sub(enc_src, r"PROG_\w+\)", "9)",
                                      "first definition's program reference")})
rejects("a trigger naming a definition that does not exist", "wave definition index",
        **{"wave_encounters.asm": break_column(enc_src, "trigDef", 99,
                                               "trigDef first entry")})
rejects("an unknown species constant", "enemy slot",
        **{"wave_encounters.asm": break_column(enc_src, "trigSpecies", 3,
                                               "trigSpecies first entry")})
rejects("an unknown Dropper side", "side",
        **{"wave_encounters.asm": break_column(enc_src, "trigSide", 7,
                                               "trigSide first entry")})
# AND THE COLUMN THE IMPORTER USED TO IGNORE. A speed outside the engine's five
# choices must be refused, not quietly clamped or dropped.
rejects("a movement speed the engine does not define", "movement speed",
        **{"wave_encounters.asm": break_column(enc_src, "trigSpeed", 99,
                                               "trigSpeed first entry")})
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
# The launch heading is a definition's PENULTIMATE field, the one just before
# its PROG_* reference. $ff is legal on an ARC's entry heading and illegal here.
rejects("$ff where a launch heading is structurally required", "heading",
        **{"wave_encounters.asm": sub(
            enc_src, r"(-?\d+),(\s*(?://[^\n]*)?\n\s*)(PROG_\w+\))",
            r"255,\g<2>\g<3>", "first definition's launch heading")})
_A = first_record(progs_src, "WM_ARC")
rejects("an unknown identifier", "unknown identifier",
        **{"wave_programs.asm": break_record(
            progs_src, "WM_ARC",
            f"WM_ARC, WM_NOPE, {_A.group(2)}, {_A.group(3)}",
            "first ARC record")})
rejects("an expression outside the supported subset", "unsupported character",
        **{"wave_encounters.asm": sub(
            enc_src, r"(\.var\s+trigRow\s*=\s*List\(\)\.add\()(\d+)",
            r"\g<1>\g<2> << 1", "trigRow first entry")})
rejects("a duplicate declaration", "already defined",
        **{"wave_encounters.asm": enc_src + "\n.const WAVE_TRIGGERS = 1\n"})
rejects("a velocity too large for the signed byte it is emitted in", "signed byte",
        **{"wave_programs.asm": break_record(
            progs_src, "WM_STRAIGHT",
            f"WM_STRAIGHT, {_S.group(1)}, 200, {_S.group(3)}",
            "first STRAIGHT record")})
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
