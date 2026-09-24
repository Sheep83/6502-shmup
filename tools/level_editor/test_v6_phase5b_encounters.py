#!/usr/bin/env python3
"""Phase 5B: encounter authoring on the v6 model.

NO TKINTER. Every operation the encounter workspace performs is a method on
`controller_v6`, so the authoring guarantees -- ordering, reference safety,
capacity, round-trip identity -- are provable without a display. The widget
layer is covered by test_encounters_gui.py against real Tk.

What this proves
----------------
* trigger add / edit / duplicate / delete, and deterministic STABLE ordering
  by worldProgress;
* species and Dropper side are symbolic, and a non-Dropper returns to the
  canonical neutral side rather than carrying a stale RIGHT;
* fire masks are member indices, preserved exactly, never silently trimmed --
  an impossible member is reported and removed only on an explicit call;
* noSpawnRow is editable and its boundary is enforced by the validator, not by
  a second rule set here;
* wave-definition and movement-program CRUD, with rename updating every
  reference atomically and referenced deletes refused by name;
* stage kind switching re-initialises predictably and keeps no stale payload;
* "CONT" is an authored value, never the magic 255;
* EXIT stays terminal;
* stage reorder;
* capacity counters;
* THE CANONICAL PROJECT IS UNCHANGED by a no-op, and every controlled encounter
  edit returns to byte-identical JSON *and* byte-identical generated ASM when
  it is reversed.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract_v2 as C
import export_v6
import project_v6
from controller_v6 import ControllerError, EditorController

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CANON = HERE / "levels" / "level1" / "level.v6.json"
PROD = REPO / "src" / "level1"
CANON_BYTES = CANON.read_bytes()

PASS, FAIL = [], []


def ok(m, x=""):
    PASS.append(m)
    print(f"ok  - {m}" + (f"  [{x}]" if x else ""))


def check(m, c, x=""):
    if c:
        ok(m, x)
    else:
        FAIL.append(m)
        print(f"FAIL- {m}" + (f"  [{x}]" if x else ""))


def fresh():
    return EditorController.canonical(HERE)


def codes(controller):
    return {i.code for i in controller.validate().errors}


def asm_matches(controller):
    """Export to scratch and compare all six files with the committed ASM."""
    with tempfile.TemporaryDirectory() as d:
        controller.export(d, carry_enemies_from=PROD)
        return [n for n in export_v6.GENERATED_NAMES
                if (PROD / n).read_bytes() == (Path(d) / n).read_bytes()]


def roundtrip(controller):
    """save -> load -> the bytes that were written.

    THROUGH A DISPOSABLE SHARED LIBRARY. Movement programs and wave definitions
    are shared assets now: they are not written into the level file, so a round
    trip that expects an edit to one of them to survive has to give the
    controller somewhere to put it. A temporary library is that somewhere --
    the production one must never be written by a test.
    """
    import shutil
    import encounter_library
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "level.v6.json"
        lib = Path(d) / "encounter_library.v6.json"
        if encounter_library.LIBRARY_PATH.is_file():
            shutil.copy(encounter_library.LIBRARY_PATH, lib)
        controller.library = encounter_library.EncounterLibrary.load_or_empty(lib)
        controller.library_path = lib
        controller.save(p)
        return (p.read_bytes(), EditorController.load(p, library_path=lib),
                lib.read_bytes() if lib.is_file() else b"")


# ===========================================================================
# 1. What the canonical project carries
# ===========================================================================
# THE CANONICAL PROJECT IS AUTHORED CONTENT. These checks used to name Level 1's
# four triggers and their exact rows, species, masks and sides -- so editing the
# level failed the file that exists to protect editing it. The controller's job
# is to surface what the FILE holds, so the expectation is read from the file.
c = fresh()
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

_disk = _with_shared(json.loads(CANON.read_text(encoding="utf-8")))
_dt = _disk["triggers"]
check("the controller surfaces the canonical triggers exactly as stored",
      [t.world_progress for t in c.project.triggers] == [d["worldProgress"] for d in _dt],
      str([t.world_progress for t in c.project.triggers]))
check("...with their authored species",
      [t.species for t in c.project.triggers] == [d["species"] for d in _dt])
check("...fire masks as member indices",
      [t.fire_mask for t in c.project.triggers] == [d["fireMask"] for d in _dt])
check("...and their Dropper sides",
      [t.dropper_side for t in c.project.triggers] == [d["dropperSide"] for d in _dt])
check("capacity reports triggers, waves, records and bytes against the caps",
      c.capacity() == {"triggers": (len(_dt), 180),
                       # shared now: counted from the library, not the level
                       "waveDefinitions": (
                           len(json.loads((HERE / "encounter_library.v6.json")
                                          .read_text())["waveDefinitions"]), 26),
                       "movementRecords": (c.project.movement_records, 64),
                       "movementBytes": (c.project.movement_bytes, 256)},
      str(c.capacity()))
_q = c.quiet_zone()
_playable = _disk["stage"]["metatileRows"] * 4 - 25
check("the quiet zone is derived from the 1 px/frame contract",
      (_q["noSpawnRow"] == _disk["stage"]["noSpawnRow"]
       and _q["playableProgress"] == _playable
       and _q["rows"] == _playable - _q["noSpawnRow"]
       and abs(_q["seconds"] - _q["rows"] * 8 / 50) < 1e-9), str(_q))
check("the project validates clean before any edit", c.validate().ok)

# ===========================================================================
# 2. Trigger CRUD and ordering
# ===========================================================================
# CRUD IS TESTED RELATIVE TO WHATEVER THE LEVEL HOLDS: append past the last row,
# move it between the first two, delete it, and expect the original list back.
c = fresh()
_rows0 = [t.world_progress for t in c.project.triggers]
_wave = c.project.wave_definitions[0].id
i = c.add_trigger(world_progress=_rows0[-1] + 40, wave_definition=_wave,
                  species="RING")
check("add_trigger inserts and returns its sorted index", i == len(_rows0),
      f"index {i}, rows {[t.world_progress for t in c.project.triggers]}")
_between = (_rows0[0] + _rows0[1]) // 2
i = c.update_trigger(i, world_progress=_between)
check("moving a trigger re-sorts and returns the new index",
      i == 1 and [t.world_progress for t in c.project.triggers]
      == sorted(_rows0 + [_between]), f"index {i}")
c.delete_trigger(i)
check("delete_trigger removes exactly it",
      [t.world_progress for t in c.project.triggers] == _rows0)

# stable ordering for ties -- two triggers on one row is how a mixed-species
# moment is authored, and re-saving must not shuffle them
c2 = fresh()
a = c2.add_trigger(world_progress=90, wave_definition="s", species="DROPPER")
b = c2.add_trigger(world_progress=90, wave_definition="loop", species="RING")
order = [(t.world_progress, t.wave_definition) for t in c2.project.triggers]
c2.sort_triggers()
check("equal worldProgress keeps a stable, deterministic order",
      order == [(t.world_progress, t.wave_definition) for t in c2.project.triggers],
      str([w for _, w in order]))
check("...and the validator permits equal rows (only a DECREASE is an error)",
      "trigger.unsorted" not in codes(c2))

c3 = fresh()
_src = fresh().project.triggers[0]
j = c3.duplicate_trigger(0)
check("duplicate_trigger copies the whole trigger one row later",
      (c3.project.triggers[j].world_progress == _src.world_progress + 1
       and c3.project.triggers[j].wave_definition == _src.wave_definition
       and c3.project.triggers[j].fire_mask == _src.fire_mask
       and c3.project.triggers[j].species == _src.species
       and c3.project.triggers[j].dropper_side == _src.dropper_side),
      f"index {j}")

# ===========================================================================
# 3. Species, side and the fire mask
# ===========================================================================
c = fresh()
# SYMBOLIC IS THE CLAIM, not the census. This asserted the exact set
# {"RING", "DROPPER"} and so failed the moment a third species was authored --
# which is a fact about the game's content, not about the contract this file
# tests. What matters is that a species is a NAME the project stores, that the
# two established ones are still there, and that each maps to a whole animation
# row. tools/sprite_export/test_spd_pipeline.py owns the roll-call.
check("species are symbolic", all(isinstance(k, str) for k in C.SPECIES)
      and {"RING", "DROPPER"} <= set(C.SPECIES), str(sorted(C.SPECIES)))
check("...and every species value is a whole animation row",
      all(v % C.ENEMY_ANIM_STEPS == 0 for v in C.SPECIES.values()),
      str(C.SPECIES))
check("sides are symbolic", set(C.DROPPER_SIDES) == {"LEFT", "RIGHT"})
c.update_trigger(3, species="RING")
check("switching a DROPPER to RING returns the side to the canonical neutral",
      c.project.triggers[3].dropper_side == "LEFT",
      c.project.triggers[3].dropper_side)
check("...so no stale RIGHT is left to warn for ever",
      "trigger.side_ignored" not in {i.code for i in c.validate().warnings}
      or c.project.triggers[3].dropper_side == "LEFT")

c = fresh()
c.update_trigger(0, fire_mask=[1, 3])
check("a fire mask is edited as member indices",
      c.project.triggers[0].fire_mask == [1, 3])
raw, back, _lib = roundtrip(c)
check("...and survives save/reload exactly",
      back.project.triggers[0].fire_mask == [1, 3])

# an impossible member is REPORTED, not silently dropped
c = fresh()
c.update_trigger(0, fire_mask=[0, 2, 3])         # 'sweep' sends 4: all legal
c.update_trigger(0, wave_definition="s")         # 's' sends only 3
check("pointing a trigger at a smaller wave does not silently trim the mask",
      c.project.triggers[0].fire_mask == [0, 2, 3])
check("...the impossible member is reported",
      c.impossible_fire_members(0) == [3], str(c.impossible_fire_members(0)))
check("...and the validator errors rather than the editor guessing",
      "trigger.fire_member_absent" in codes(c))
dropped = c.trim_fire_mask(0)
check("...and the explicit trim removes only those members",
      dropped == [3] and c.project.triggers[0].fire_mask == [0, 2])

# ===========================================================================
# 4. noSpawnRow
# ===========================================================================
c = fresh()
c.set_no_spawn_row(200)
check("noSpawnRow is editable", c.project.stage.no_spawn_row == 200)
check("...and the quiet zone follows it",
      (c.quiet_zone()["rows"] == _playable - 200
       and abs(c.quiet_zone()["seconds"] - (_playable - 200) * 8 / 50) < 1e-9),
      str(c.quiet_zone()))
c.set_no_spawn_row(_disk["triggers"][-1]["worldProgress"] - 1)   # strands the last
check("a noSpawnRow that strands a trigger is a validation error, not a refusal",
      "trigger.at_or_after_no_spawn" in codes(c))
c.set_no_spawn_row(_disk["stage"]["noSpawnRow"])
check("...and putting it back clears the error", c.validate().ok)

# ===========================================================================
# 5. Wave definitions: CRUD, rename, reference safety
# ===========================================================================
c = fresh()
n = c.add_wave_definition()
check("add_wave_definition creates one with a unique id",
      len(c.project.wave_definitions) == len(_disk["waveDefinitions"]) + 1
      and c.project.wave_definitions[n].id not in
      {d["id"] for d in _disk["waveDefinitions"]},
      c.project.wave_definitions[n].id)
try:
    c.add_wave_definition(ident="sweep")
    check("a duplicate wave id is refused", False, "allowed")
except ControllerError as e:
    check("a duplicate wave id is refused", "already exists" in str(e))

moved = c.rename_wave_definition(0, "sweep_v2")
check("renaming a wave updates every trigger that names it",
      moved == 1 and c.project.triggers[0].wave_definition == "sweep_v2",
      f"{moved} reference(s)")
check("...and leaves no dangling reference", "trigger.dangling_definition" not in codes(c))
c.rename_wave_definition(0, "sweep")

try:
    c.delete_wave_definition(0)
    check("deleting a referenced wave is refused", False, "allowed")
except ControllerError as e:
    check("deleting a referenced wave is refused, naming the users",
          "trigger(s)" in str(e), str(e)[:64])
c.delete_wave_definition(n)
check("...but an unreferenced one deletes",
      len(c.project.wave_definitions) == len(_disk["waveDefinitions"]))

c = fresh()
k = c.duplicate_wave_definition(0)
check("duplicating a wave copies its fields under a new id",
      (c.project.wave_definitions[k].id == "sweep_copy"
       and c.project.wave_definitions[k].count == c.project.wave_definitions[0].count
       and c.project.wave_definitions[k].movement_program ==
           c.project.wave_definitions[0].movement_program))
c.update_wave_definition(0, count=6)
check("a wave field edit applies", c.project.wave_definitions[0].count == 6)
try:
    c.update_wave_definition(0, id="nope")
    check("changing an id through update is refused", False, "allowed")
except ControllerError:
    ok("changing an id through update is refused (rename is the safe path)")

# ===========================================================================
# 6. Movement programs and stages
# ===========================================================================
c = fresh()
p = c.add_movement_program()
check("a new movement program starts as a bare EXIT",
      [s.kind for s in c.project.movement_programs[p].stages] == ["EXIT"])
check("...which is a legal program on its own",
      "movement.no_exit" not in codes(c) and "movement.empty" not in codes(c))

at = c.add_stage(p, "STRAIGHT")
check("adding a stage puts it BEFORE the terminal EXIT",
      [s.kind for s in c.project.movement_programs[p].stages] == ["STRAIGHT", "EXIT"],
      f"inserted at {at}")
check("...and EXIT stays terminal", "movement.after_exit" not in codes(c))

c.set_stage_kind(p, 0, "ARC")
st = c.project.movement_programs[p].stages[0]
check("switching a stage kind re-initialises it predictably",
      st.kind == "ARC" and st.steps >= 1 and st.frames_per_step >= 1
      and st.entry_heading == 0,
      f"steps {st.steps}, f/step {st.frames_per_step}, entry {st.entry_heading}")
check("...with a real entry heading, never None (the stale-wmPhase bug)",
      "movement.missing_entry_heading" not in codes(c))

c.update_stage(p, 0, entry_heading="CONT")
check("CONT is an authored value, not the magic 255",
      c.project.movement_programs[p].stages[0].entry_heading == "CONT")
raw, back, _lib = roundtrip(c)
check("...and survives save/reload as the string CONT",
      back.project.movement_programs[p].stages[0].entry_heading == "CONT")
check("...and 255 appears nowhere in the saved JSON for it",
      '"entryHeading": 255' not in raw.decode())

c.set_stage_kind(p, 0, "STRAIGHT")
st = c.project.movement_programs[p].stages[0]
check("switching kind again keeps no stale payload from the old one",
      st.kind == "STRAIGHT" and st.entry_heading is None and st.steps == 0,
      f"entry {st.entry_heading}, steps {st.steps}")

c.add_stage(p, "HOLD")
before = [s.kind for s in c.project.movement_programs[p].stages]
new_i = c.move_stage(p, 0, 1)
check("stages reorder",
      [s.kind for s in c.project.movement_programs[p].stages] != before and new_i == 1,
      str([s.kind for s in c.project.movement_programs[p].stages]))
c.delete_stage(p, 0)
check("a stage deletes", len(c.project.movement_programs[p].stages) == 2)

moved = c.rename_movement_program(0, "sweep_v2")
check("renaming a program updates every wave definition that names it",
      moved == 1 and c.project.wave_definitions[0].movement_program == "sweep_v2")
check("...and leaves no dangling reference", "wavedef.dangling_program" not in codes(c))
c.rename_movement_program(0, "sweep")
try:
    c.delete_movement_program(0)
    check("deleting a referenced program is refused", False, "allowed")
except ControllerError as e:
    check("deleting a referenced program is refused, naming the users",
          "wave definition(s)" in str(e), str(e)[:64])
c.delete_movement_program(p)
# BACK TO WHAT THE PROJECT STARTED WITH, not to a remembered four. The
# authored level has gained programs since this was written, and the claim
# under test is that deleting the one just added removes exactly it.
check("...but an unreferenced one deletes",
      len(c.project.movement_programs) == len(_disk["movementPrograms"]),
      f'{len(c.project.movement_programs)} vs {len(_disk["movementPrograms"])}')

# ===========================================================================
# 7. THE NO-OP PROOF, repeated for this phase
# ===========================================================================
c = fresh()
raw, _, _ = roundtrip(c)
check("open + save with NO encounter edits is byte-identical JSON",
      raw == CANON_BYTES, f"{len(raw)} vs {len(CANON_BYTES)} bytes")
check("...and the six generated files are byte-identical",
      asm_matches(c) == list(export_v6.GENERATED_NAMES),
      f"{len(asm_matches(c))}/6")

# ===========================================================================
# 8. Controlled encounter edits: change, save, reload, verify, restore
# ===========================================================================
import encounter_library as _EL
LIB_BYTES = (_EL.LIBRARY_PATH.read_bytes()
             if _EL.LIBRARY_PATH.is_file() else b"")


def edit_cycle(name, mutate, verify, restore):
    """One controlled edit, proved to persist and then to reverse exactly."""
    c = fresh()
    mutate(c)
    raw, back, lib_after = roundtrip(c)
    check(f"{name}: the edit survives save/reload", verify(back), "")
    # AN EDIT PERSISTS SOMEWHERE, and which file depends on what was edited.
    # Triggers and the no-spawn row are level-specific and change the level
    # JSON; movement programs and wave definitions are SHARED and change the
    # encounter library instead, leaving the level file untouched. Asserting
    # only "the level JSON changed" would now fail for exactly the edits the
    # sharing was introduced for.
    check(f"{name}: the edit really reached a persisted file",
          raw != CANON_BYTES or lib_after != LIB_BYTES,
          "level JSON" if raw != CANON_BYTES else "encounter library")
    restore(back)
    raw2, _, _ = roundtrip(back)
    check(f"{name}: restoring returns byte-identical canonical JSON",
          raw2 == CANON_BYTES)
    check(f"{name}: ...and byte-identical generated ASM",
          asm_matches(back) == list(export_v6.GENERATED_NAMES))


_rows_disk = [d["worldProgress"] for d in _disk["triggers"]]
_moved = sorted(_rows_disk[:2] + [_rows_disk[1] + 1] + _rows_disk[3:])
edit_cycle(
    "trigger move",
    lambda c: c.update_trigger(2, world_progress=_rows_disk[1] + 1),
    lambda c: [t.world_progress for t in c.project.triggers] == _moved,
    lambda c: c.update_trigger(2, world_progress=_rows_disk[2]))

_ns = _disk["stage"]["noSpawnRow"]
edit_cycle(
    "noSpawn change",
    lambda c: c.set_no_spawn_row(_ns - 40),
    lambda c: c.project.stage.no_spawn_row == _ns - 40,
    lambda c: c.set_no_spawn_row(_ns))

edit_cycle(
    "wave definition field",
    lambda c: c.update_wave_definition(2, interval=30),
    lambda c: (c.project.wave_definitions[2].interval == 30
               # references must be untouched by a field edit
               and [t.wave_definition for t in c.project.triggers]
               == [d["waveDefinition"] for d in _disk["triggers"]]),
    lambda c: c.update_wave_definition(2, interval=26))

_orig_steps = fresh().project.movement_programs[1].stages[0].steps
edit_cycle(
    "movement stage field",
    lambda c: c.update_stage(1, 0, steps=14),
    lambda c: (c.project.movement_programs[1].stages[0].steps == 14
               and [d.movement_program for d in c.project.wave_definitions]
               == [d["movementProgram"] for d in _disk["waveDefinitions"]]),
    lambda c: c.update_stage(1, 0, steps=_orig_steps))

# ...and the canonical file on disk was never touched by any of it
check("the canonical project on disk is untouched throughout",
      CANON.read_bytes() == CANON_BYTES)

# ===========================================================================
print()
if FAIL:
    print(f"{len(FAIL)} FAILURE(S):")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {len(PASS)} Phase 5B encounter-authoring checks passed.")
