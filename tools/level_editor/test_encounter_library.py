#!/usr/bin/env python3
"""Shared encounter vocabulary, per-level placement.

    python3 tools/level_editor/test_encounter_library.py

THE OWNERSHIP CONTRACT, in one line: Movement Programs and Wave Definitions are
shared across every level and persisted once; triggers and noSpawnRow belong to
the level and nothing else may touch them.

MOST OF THIS FILE USES DISPOSABLE FIXTURES. Levels A and B are built here, share
one temporary library and deliberately disagree about their triggers, so the
isolation claims are proved without mutating anything Brian authors. The
production levels are read for the few claims that are genuinely about them --
that Level 1 still has its Square trigger, that Level 2 has not gained one --
and are never written.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                         # noqa: E402
import encounter_library                                        # noqa: E402
import project_v6                                               # noqa: E402
from encounter_library import (EncounterLibrary, LibraryConflict,  # noqa: E402
                               LibraryError)
from controller_v6 import EditorController                      # noqa: E402
from project_v6 import ProjectV6, Stage, Palette                # noqa: E402
from movement_sim import simulate_trigger                       # noqa: E402

PASS, FAIL = [], []
L1 = HERE / "levels" / "level1" / "level.v6.json"
L2 = HERE / "levels" / "level2" / "level.v6.json"
LIB = encounter_library.LIBRARY_PATH


def check(label, ok, extra=""):
    (PASS if ok else FAIL).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{' -- ' + extra if extra else ''}")


def raises(label, exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        check(label, True, type(e).__name__)
        return
    except Exception as e:                                      # noqa: BLE001
        check(label, False, f"raised {type(e).__name__}, wanted {exc.__name__}")
        return
    check(label, False, "no exception")


def blank_level(name, rows=40, bg=2):
    """A minimal valid level with NO encounter content of its own."""
    glyphs = [[0] * 8 for _ in range(8)]
    glyphs[1] = [0b01010101] * 8
    return ProjectV6(
        name=name,
        stage=Stage(metatile_rows=rows, no_spawn_row=C.default_no_spawn_row(rows)),
        palette=Palette(background=bg, multicolour1=1, multicolour2=15, character=1),
        glyphs=glyphs,
        metatile_defs=[[C.TERRAIN_GLYPH_BASE] * 16],
        map_rows=[[0] * C.METATILES_PER_ROW for _ in range(rows)],
        turrets=[], movement_programs=[], wave_definitions=[], triggers=[],
        level_metatile_set=None)


def fixture_library():
    """A two-program, two-definition vocabulary owing nothing to production."""
    src = EncounterLibrary.load(LIB)
    lib = EncounterLibrary(
        movement_programs=[project_v6.MovementProgram.from_dict(
            src.movement_programs[0].to_dict(), "fx")],
        wave_definitions=[project_v6.WaveDefinition.from_dict(
            src.wave_definitions[0].to_dict(), "fx")])
    lib.movement_programs[0].id = "glide"
    lib.wave_definitions[0].id = "pair"
    lib.wave_definitions[0].movement_program = "glide"
    return lib


# ---------------------------------------------------------------------------
# 1. the library itself
# ---------------------------------------------------------------------------
lib = EncounterLibrary.load(LIB)
check("the shared library exists and loads", True, lib.summary())
check("it carries programs and definitions and nothing else",
      set(json.loads(LIB.read_text())) == {"formatVersion", "kind",
                                           "movementPrograms", "waveDefinitions"},
      ", ".join(sorted(json.loads(LIB.read_text()))))
check("it declares itself an encounter library",
      json.loads(LIB.read_text())["kind"] == "encounterLibrary")
check("serialisation is deterministic",
      EncounterLibrary.load(LIB).to_json() == lib.to_json())
check("what is on disk is exactly what the model round-trips",
      LIB.read_text(encoding="utf-8") == lib.to_json())

raises("a level document is refused as a library", LibraryError,
       EncounterLibrary.from_dict, json.loads(L1.read_text()), "level1")
raises("a missing library is refused by load()", LibraryError,
       EncounterLibrary.load, HERE / "nope.v6.json")
check("...but load_or_empty gives callers an empty one",
      EncounterLibrary.load_or_empty(HERE / "nope.v6.json").summary()
      == "0 movement programs, 0 wave definitions")

# ---------------------------------------------------------------------------
# 2. the canonical level boundary
# ---------------------------------------------------------------------------
for path, label in ((L1, "level1"), (L2, "level2")):
    raw = json.loads(path.read_text())
    check(f"{label} no longer persists the shared vocabulary",
          "movementPrograms" not in raw and "waveDefinitions" not in raw,
          ", ".join(sorted(raw)))
    check(f"{label} still persists its own triggers and stage",
          "triggers" in raw and "noSpawnRow" in raw["stage"])

# ---------------------------------------------------------------------------
# 3. migration from embedded assets
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    fx = fixture_library()
    fx.save(d / "lib.v6.json")

    # a legacy document: the shared keys still in the level, plus a trigger
    legacy = blank_level("legacy")
    fx.install_into(legacy)
    legacy.triggers = [project_v6.Trigger(world_progress=12,
                                          wave_definition="pair",
                                          species="RING")]
    (d / "legacy").mkdir()
    (d / "legacy" / "level.v6.json").write_text(legacy.to_json(), encoding="utf-8")

    c = EditorController.load(d / "legacy" / "level.v6.json",
                              library_path=d / "lib.v6.json")
    check("a legacy document with embedded assets opens", True)
    check("...its embedded assets reconcile against the library, not duplicate it",
          len(c.library.movement_programs) == 1
          and len(c.library.wave_definitions) == 1,
          c.library.summary())
    check("...its trigger is kept and is NOT treated as shared",
          len(c.project.triggers) == 1 and not hasattr(c.library, "triggers"))

    # a UNIQUE embedded asset must be absorbed, never dropped
    uniq = blank_level("uniq")
    fx.install_into(uniq)
    extra = project_v6.MovementProgram.from_dict(
        fx.movement_programs[0].to_dict(), "x")
    extra.id = "only_here"
    uniq.movement_programs.append(extra)
    (d / "uniq").mkdir()
    (d / "uniq" / "level.v6.json").write_text(uniq.to_json(), encoding="utf-8")
    c2 = EditorController.load(d / "uniq" / "level.v6.json",
                               library_path=d / "lib.v6.json")
    check("a unique embedded program is absorbed, not discarded",
          "only_here" in c2.library.ids()[0], str(c2.library.ids()[0]))

    # a CONFLICTING embedded asset must stop the migration
    clash = blank_level("clash")
    fx.install_into(clash)
    clash.movement_programs[0].stages[0].frames += 7
    (d / "clash").mkdir()
    (d / "clash" / "level.v6.json").write_text(clash.to_json(), encoding="utf-8")
    raises("a conflicting embedded program is REFUSED, never overwritten",
           LibraryConflict, EditorController.load,
           d / "clash" / "level.v6.json", library_path=d / "lib.v6.json")

# ---------------------------------------------------------------------------
# 4. NEW LEVEL -- the central acceptance case
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    fx = fixture_library()
    fx.save(d / "lib.v6.json")

    # exactly what editor._seed_v6_project does: blank level, shared vocabulary
    fresh = blank_level("brand_new")
    fx.install_into(fresh)
    c = EditorController(fresh, library=fx, library_path=d / "lib.v6.json")

    check("NEW LEVEL: the trigger timeline is empty", c.project.triggers == [])
    check("NEW LEVEL: the shared Movement Programs are immediately available",
          [p.id for p in c.project.movement_programs] == ["glide"])
    check("NEW LEVEL: the shared Wave Definitions are immediately available",
          [x.id for x in c.project.wave_definitions] == ["pair"])
    check("NEW LEVEL: terrain and stage are blank/default",
          all(all(v == 0 for v in row) for row in c.project.map_rows)
          and c.project.turrets == [])

    # a new trigger can name a shared definition
    c.project.triggers.append(project_v6.Trigger(
        world_progress=30, wave_definition="pair", species="SQUARE"))
    check("NEW LEVEL: a trigger can reference a shared definition",
          c.validate().ok,
          "; ".join(str(e) for e in c.validate().errors[:2]))

    out = d / "brand_new" / "level.v6.json"
    c.save(out)
    raw = json.loads(out.read_text())
    check("NEW LEVEL: the saved file does NOT duplicate the library",
          "movementPrograms" not in raw and "waveDefinitions" not in raw,
          ", ".join(sorted(raw)))
    check("NEW LEVEL: the saved file DOES carry its trigger",
          len(raw["triggers"]) == 1
          and raw["triggers"][0]["waveDefinition"] == "pair")

    back = EditorController.load(out, library_path=d / "lib.v6.json")
    check("NEW LEVEL: reopening preserves the trigger",
          len(back.project.triggers) == 1
          and back.project.triggers[0].species == "SQUARE")
    check("NEW LEVEL: reopening resolves the shared definition again",
          [x.id for x in back.project.wave_definitions] == ["pair"])

    back.export(d / "gen", carry_enemies_from=d / "gen")
    enc = (d / "gen" / "wave_encounters.asm").read_text()
    prog = (d / "gen" / "wave_programs.asm").read_text()
    # ids become assembler symbols: 'glide' -> PROG_GLIDE, 'pair' -> WAVE_DEF_PAIR
    check("NEW LEVEL: export resolves the shared definition and program",
          "WAVE_DEF_PAIR" in enc and "PROG_GLIDE" in prog,
          "PROG_GLIDE" if "PROG_GLIDE" in prog else "program symbol missing")
    check("NEW LEVEL: its export is self-contained (its own two .asm files)",
          (d / "gen" / "wave_programs.asm").is_file()
          and (d / "gen" / "wave_encounters.asm").is_file())

# ---------------------------------------------------------------------------
# 5. CROSS-LEVEL ISOLATION -- disposable A and B over one library
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    libp = d / "lib.v6.json"
    fixture_library().save(libp)

    def make(name, triggers):
        p = blank_level(name)
        EncounterLibrary.load(libp).install_into(p)
        p.triggers = list(triggers)
        (d / name).mkdir(exist_ok=True)
        c = EditorController(p, library=EncounterLibrary.load(libp),
                             library_path=libp)
        c.save(d / name / "level.v6.json")
        return d / name / "level.v6.json"

    A = make("A", [project_v6.Trigger(world_progress=10, wave_definition="pair",
                                      species="SQUARE"),
                   project_v6.Trigger(world_progress=40, wave_definition="pair",
                                      species="RING")])
    B = make("B", [project_v6.Trigger(world_progress=25, wave_definition="pair",
                                      species="DROPPER")])

    ca = EditorController.load(A, library_path=libp)
    check("A shows only A's triggers",
          [(t.world_progress, t.species) for t in ca.project.triggers]
          == [(10, "SQUARE"), (40, "RING")])
    cb = EditorController.load(B, library_path=libp)
    check("B shows only B's triggers",
          [(t.world_progress, t.species) for t in cb.project.triggers]
          == [(25, "DROPPER")])
    check("B has no Square", "SQUARE" not in {t.species for t in cb.project.triggers})
    ca2 = EditorController.load(A, library_path=libp)
    check("switching back to A restores A's timeline exactly",
          [(t.world_progress, t.species) for t in ca2.project.triggers]
          == [(10, "SQUARE"), (40, "RING")])

    # editing A's triggers must not reach B
    ca2.project.triggers.append(project_v6.Trigger(
        world_progress=60, wave_definition="pair", species="RING"))
    ca2.save()
    check("a trigger added to A does not appear in B",
          len(EditorController.load(B, library_path=libp).project.triggers) == 1)

    # noSpawnRow is per level
    ca3 = EditorController.load(A, library_path=libp)
    ca3.project.stage.no_spawn_row = 99
    ca3.save()
    check("noSpawnRow is per level: changing A leaves B alone",
          EditorController.load(B, library_path=libp).project.stage.no_spawn_row
          != 99)

    # a SHARED edit must be visible from both
    ca4 = EditorController.load(A, library_path=libp)
    ca4.project.movement_programs[0].stages[0].frames += 3
    want = ca4.project.movement_programs[0].stages[0].frames
    ca4.save()
    cb2 = EditorController.load(B, library_path=libp)
    check("a shared Movement Program edit made in A is visible in B",
          cb2.project.movement_programs[0].stages[0].frames == want,
          f"{cb2.project.movement_programs[0].stages[0].frames} vs {want}")

    cb2.project.wave_definitions[0].count = 3
    cb2.save()
    check("a shared Wave Definition edit made in B is visible in A",
          EditorController.load(A, library_path=libp)
          .project.wave_definitions[0].count == 3)
    check("...and the shared edit is persisted in the library, not the level",
          "waveDefinitions" not in json.loads(B.read_text())
          and EncounterLibrary.load(libp).wave_definitions[0].count == 3)

    # exports carry their own triggers and resolve the shared vocabulary
    for path, name, n in ((A, "A", 3), (B, "B", 1)):
        c = EditorController.load(path, library_path=libp)
        c.export(d / f"gen{name}", carry_enemies_from=d / f"gen{name}")
        enc = (d / f"gen{name}" / "wave_encounters.asm").read_text()
        prog = (d / f"gen{name}" / "wave_programs.asm").read_text()
        row = next(l for l in enc.splitlines() if ".var trigDef" in l)
        placed = row.count("WAVE_DEF_")
        check(f"export {name} carries its own {n} trigger(s) and resolves the "
              f"shared program",
              placed == n and "WAVE_DEF_PAIR" in enc and "PROG_GLIDE" in prog,
              f"{placed} trigger(s) emitted")

# ---------------------------------------------------------------------------
# 6. production levels: read only, and unchanged
# ---------------------------------------------------------------------------
c1 = EditorController.load(L1, library_path=LIB)
c2 = EditorController.load(L2, library_path=LIB)
sq = [t for t in c1.project.triggers if t.species == "SQUARE"]
check("Level 1 still has Brian's Square trigger", len(sq) == 1,
      f"wp={sq[0].world_progress} def={sq[0].wave_definition}" if sq else "missing")
check("Level 1 still has all nine triggers", len(c1.project.triggers) == 9,
      str(len(c1.project.triggers)))
check("Level 1 keeps its own noSpawnRow", c1.project.stage.no_spawn_row == 725,
      str(c1.project.stage.no_spawn_row))
check("Level 2 has NOT gained a Square trigger",
      not any(t.species == "SQUARE" for t in c2.project.triggers),
      ", ".join(sorted({t.species for t in c2.project.triggers})))
check("Level 2 keeps its own seven triggers", len(c2.project.triggers) == 7)
check("Level 2 keeps its own noSpawnRow", c2.project.stage.no_spawn_row == 352,
      str(c2.project.stage.no_spawn_row))
check("the two levels differ in triggers but share the vocabulary",
      [t.world_progress for t in c1.project.triggers]
      != [t.world_progress for t in c2.project.triggers]
      and [p.id for p in c1.project.movement_programs]
      == [p.id for p in c2.project.movement_programs])
check("both production levels still validate", c1.validate().ok and c2.validate().ok)

# the preview gets the current level's triggers plus the shared vocabulary
sim = simulate_trigger(c1.project, 0)
check("the preview resolves a production trigger through the shared library",
      sim.count > 0 and sim.frame_count > 0,
      f"{sim.wave_id}/{sim.program_id}, {sim.count} members")
sq_index = next(i for i, t in enumerate(c1.project.triggers)
                if t.species == "SQUARE")
sqsim = simulate_trigger(c1.project, sq_index)
check("the preview simulates the Square trigger as an ordinary wave",
      sqsim.count > 0, f"{sqsim.wave_id}, {sqsim.count} members")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1)
