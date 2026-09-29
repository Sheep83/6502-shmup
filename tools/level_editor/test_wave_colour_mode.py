#!/usr/bin/env python3
"""Enemy colour AND firing mode belong to the TRIGGER: the authoring path.

    Tkinter trigger UI -> project JSON -> exported wave_encounters.asm

WHAT THIS IS FOR. The runtime half is proved on the emulator in
tests/test_wave_colour_mode.py. This proves the half a human touches, and above
all the thing the ownership move exists for:

    TWO TRIGGERS PLAYING THE SAME REUSABLE WAVE DEFINITION CAN BE
    DIFFERENT COLOURS AND FIRE DIFFERENTLY, AND NEITHER CAN CHANGE
    THE OTHER.

It also proves that a wave definition no longer offers a colour at all, that a
project written while colour still lived on the definition migrates its
authored choice onto the triggers rather than resetting it, and that adding the
field changed nothing else.

NOTHING PRODUCTION IS WRITTEN. Every save and export goes to a temporary
directory, and the committed level documents and library are compared byte for
byte at the end to prove it.

THE WIDGET SECTION NEEDS A WORKING TK, which not every interpreter on a Mac has.
It is skipped with a notice rather than failed if Tk cannot start, exactly as
test_encounters_gui.py does -- run it with an interpreter that has one:

    /usr/local/bin/python3 tools/level_editor/test_wave_colour_mode.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asm_decl                                                  # noqa: E402
import contract_v2 as C                                          # noqa: E402
import export_v6                                                 # noqa: E402
import project_v6                                                # noqa: E402
from controller_v6 import EditorController                        # noqa: E402
from encounter_library import EncounterLibrary                    # noqa: E402
from project_v6 import Trigger, WaveDefinition                    # noqa: E402
from validation_v6 import validate                                # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CANON = HERE / "levels" / "level1" / "level.v6.json"
LIB = HERE / "encounter_library.v6.json"
PROD = REPO / "src" / "level1"

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


def trig_colours(path):
    """The trigColour column of a generated wave_encounters.asm."""
    src = asm_decl.parse_files(
        [REPO / "src" / n for n in ("movement_format.asm", "encounter_format.asm")]
        + [Path(path) / "wave_programs.asm", Path(path) / "wave_encounters.asm"])
    return src.list_("trigColour")


def trig_fire_modes(path):
    src = asm_decl.parse_files(
        [REPO / "src" / n for n in ("movement_format.asm", "encounter_format.asm")]
        + [Path(path) / "wave_programs.asm", Path(path) / "wave_encounters.asm"])
    return src.list_("trigFireMode")


def defs_of(path):
    src = asm_decl.parse_files(
        [REPO / "src" / n for n in ("movement_format.asm", "encounter_format.asm")]
        + [Path(path) / "wave_programs.asm", Path(path) / "wave_encounters.asm"])
    return {n: src.list_(n) for n in src.lists if n.startswith("def")}


CANON_BYTES = CANON.read_bytes()
LIB_BYTES = LIB.read_bytes()

# ===========================================================================
# 1. OWNERSHIP -- a definition has no colour any more
# ===========================================================================
print("\n=== a wave definition owns formation, not presentation ===")

d = WaveDefinition(id="w", count=3, movement_program="s")
check("a WaveDefinition exposes no colour field", not hasattr(d, "colour"))
check("...and no colour mode field", not hasattr(d, "colour_mode"))
check("...and NO FIRING MODE field", not hasattr(d, "fire_mode"))
check("...and serialises none of the three",
      not ({"colour", "colourMode", "fireMode"} & set(d.to_dict())),
      ", ".join(sorted(d.to_dict())))
check("...and what remains is formation only",
      set(d.to_dict()) == {"id", "count", "interval", "startX", "startY",
                           "xStep", "yStep", "heading", "movementProgram"},
      ", ".join(sorted(d.to_dict())))

t = Trigger(world_progress=10, wave_definition="w")
check("a Trigger owns the colour", hasattr(t, "colour"))
check("...and the colour mode", hasattr(t, "colour_mode"))
check("...and THE FIRING MODE", hasattr(t, "fire_mode"))
check("...and serialises all three",
      {"colour", "colourMode", "fireMode"} <= set(t.to_dict()),
      ", ".join(sorted(t.to_dict())))
check("...and still owns the fire MASK it always did", hasattr(t, "fire_mask"))

lib = EncounterLibrary.load(LIB)
on_disk = json.loads(LIB.read_text())["waveDefinitions"]
check("the committed shared library carries no definition colour or firing",
      not any({"colour", "colourMode", "fireMode"} & set(x) for x in on_disk),
      f"{len(on_disk)} definitions")

# ===========================================================================
# 2. MIGRATION -- a pre-move project keeps what its author chose
# ===========================================================================
print("\n=== migrating a project that still keeps colour on the definition ===")

legacy_defs = [
    {"id": "sweep", "count": 4, "interval": 22, "startX": 0, "startY": 64,
     "xStep": 0, "yStep": 20, "colour": 10, "heading": 0,
     "movementProgram": "p", "fireMode": "AIMED", "colourMode": "RANDOM"},
    {"id": "s", "count": 3, "interval": 26, "startX": 90, "startY": 30,
     "xStep": 28, "yStep": 0, "colour": 3, "heading": 12,
     "movementProgram": "p", "fireMode": "DOWN", "colourMode": "FIXED"},
    # AND ONE OLDER STILL: colour, but no colourMode at all -- a project from
    # before random colour existed.
    {"id": "old", "count": 2, "interval": 20, "startX": 40, "startY": 30,
     "xStep": 0, "yStep": 0, "colour": 6, "heading": 0, "movementProgram": "p"},
]
loaded = [WaveDefinition.from_dict(x, "legacy") for x in legacy_defs]
check("a legacy definition's colour is read as MIGRATION INPUT, not authoring",
      [x.legacy_colour for x in loaded] == [10, 3, 6],
      str([x.legacy_colour for x in loaded]))
check("...and so is its firing mode",
      [x.legacy_fire_mode for x in loaded] == ["AIMED", "DOWN", None],
      str([x.legacy_fire_mode for x in loaded]))
check("...and neither is written back out",
      not any({"colour", "fireMode"} & set(x.to_dict()) for x in loaded))


class _Doc:
    def __init__(self, defs, trigs):
        self.wave_definitions, self.triggers = defs, trigs


doc = _Doc(loaded, [
    Trigger(world_progress=20, wave_definition="sweep"),
    Trigger(world_progress=52, wave_definition="s"),
    Trigger(world_progress=90, wave_definition="old"),
    Trigger(world_progress=99, wave_definition="sweep"),
    Trigger(world_progress=120, wave_definition="nope"),
])
project_v6.resolve_trigger_colours(doc)
got = [(t.resolved_colour_mode, t.resolved_colour) for t in doc.triggers]
fires = [t.resolved_fire_mode for t in doc.triggers]
check("a trigger inherits its definition's AIMED -- not reset to DOWN",
      fires[0] == "AIMED", fires[0])
check("...and a DOWN definition's trigger stays DOWN", fires[1] == "DOWN")
check("a definition with no fireMode at all migrates as DOWN",
      fires[2] == "DOWN", fires[2])
check("two triggers on one definition each get their own firing copy",
      fires[0] == fires[3] == "AIMED")
check("a trigger inherits its definition's RANDOM -- NOT reset to Fixed",
      got[0] == ("RANDOM", 10), str(got[0]))
check("a trigger inherits its definition's FIXED colour",
      got[1] == ("FIXED", 3), str(got[1]))
check("a definition with a colour but no mode migrates as FIXED",
      got[2] == ("FIXED", 6), str(got[2]))
check("two triggers on the same definition each get their own copy",
      got[0] == got[3] and doc.triggers[0] is not doc.triggers[3])
check("a dangling reference is left for the validator, not guessed at",
      doc.triggers[4].colour is None)
check("...and still reads as a sane default downstream",
      (doc.triggers[4].resolved_colour_mode,
       doc.triggers[4].resolved_colour) == ("FIXED", C.DEFAULT_TRIGGER_COLOUR))

before = [(t.resolved_colour_mode, t.resolved_colour) for t in doc.triggers]
doc.triggers[0].colour_mode = "FIXED"
doc.triggers[0].colour = 2
project_v6.resolve_trigger_colours(doc)
check("resolving again never overwrites a trigger that already decided",
      (doc.triggers[0].colour_mode, doc.triggers[0].colour) == ("FIXED", 2))
check("...and leaves every other trigger exactly as it was",
      [(t.resolved_colour_mode, t.resolved_colour)
       for t in doc.triggers][1:] == before[1:])

# ---- the real thing: Brian's temporary all-Random Level 1 ------------------
print("\n=== the committed Level 1, migrated from the visual-test state ===")
ctl = EditorController.load(CANON, library_path=LIB)
rows = [(t.world_progress, t.wave_definition, t.resolved_colour_mode,
         t.resolved_colour) for t in ctl.project.triggers]
for r in rows:
    print(f"       row {r[0]:>4}  {r[1]:<10} {r[2]:<6} colour {r[3]}")
# THE PROPERTY, NOT THE SNAPSHOT. These three used to name the level's exact
# trigger count, the exact row of its one FIXED appearance and its exact
# colour -- all true when written, all false the moment the author edited the
# level, which is the whole point of the feature. What must hold for ever is
# that migration leaves every trigger with its own concrete, legal pair.
check("every trigger has a concrete colour of its own",
      bool(rows) and all(r[3] is not None for r in rows), f"{len(rows)} triggers")
check("...every one of them a legal C64 colour",
      all(0 <= r[3] <= C.MAX_COLOUR for r in rows),
      str(sorted({r[3] for r in rows})))
check("...and a mode the runtime knows",
      all(r[2] in C.COLOUR_MODES for r in rows),
      str(sorted({r[2] for r in rows})))
# EVERY TRIGGER ON A SHARED DEFINITION HAS ITS OWN PAIR -- which is the
# property. Their values are the author's business and are not frozen here.
_shared_ids = {i for i in (r[1] for r in rows)
               if sum(1 for r in rows if r[1] == i) > 1}
check("triggers that share a definition each carry their own colour pair",
      all(isinstance(r[3], int) and r[2] in C.COLOUR_MODES
          for r in rows if r[1] in _shared_ids),
      "; ".join(f"{r[1]}@{r[0]}={r[2]}({r[3]})"
                for r in rows if r[1] in _shared_ids) or "none shared")
check("both production levels still validate",
      all(validate(EditorController.load(
          HERE / "levels" / lv / "level.v6.json", library_path=LIB).project).ok
          for lv in ("level1", "level2")))

# ===========================================================================
# 3. THE ENCODING
# ===========================================================================
print("\n=== the trigger colour byte ===")


def byte_for(colour, mode):
    return export_v6.trigger_colour_byte(
        Trigger(world_progress=0, wave_definition="w",
                colour=colour, colour_mode=mode))


check("FIXED packs to exactly the colour",
      all(byte_for(c, "FIXED") == c for c in range(16)))
check("RANDOM sets bit 4 and keeps the colour in the low nibble",
      all(byte_for(c, "RANDOM") == c | 0x10 for c in range(16)))
check("no combination ever sets bits 5-7",
      all(byte_for(c, m) <= C.TRIG_COL_MASK + C.TRIG_COL_RANDOM
          for c in range(16) for m in C.COLOUR_MODES))
check("every combination is recoverable from the byte alone",
      all((lambda b: (b & 0x0F, bool(b & 0x10)))(byte_for(c, m))
          == (c, m == "RANDOM")
          for c in range(16) for m in C.COLOUR_MODES))
fmt = (REPO / "src" / "encounter_format.asm").read_text()
check("the editor's flag is the one src/encounter_format.asm names",
      f".const TRIG_COL_RANDOM = ${C.TRIG_COL_RANDOM:02x}" in fmt
      and f".const TRIG_COL_MASK   = ${C.TRIG_COL_MASK:02x}" in fmt)
# DERIVED, NOT FROZEN. This check used to name the column count and the slot
# count as literals, and went stale the very next time a column was added --
# which is the whole reason contract_v2 now computes both. It asserts the
# RELATIONSHIP instead, which stays true however many columns there are.
check("the editor's trigger capacity follows the engine's column count",
      C.MAX_TRIGGERS
      == C.LEVELPKG_TRIG_RESERVATION // C.LEVELPKG_TRIG_COLS,
      f"{C.LEVELPKG_TRIG_COLS} columns, {C.MAX_TRIGGERS} slots")
_fmt = (REPO / "src" / "encounter_format.asm").read_text()
check("...and the firing modes it emits are the ones the engine names",
      ".const TRIG_FIRE_DOWN  = 0" in _fmt and ".const TRIG_FIRE_AIMED = 1" in _fmt)
_waves = (REPO / "src" / "waves.asm").read_text()
check("the engine no longer names a definition firing field",
      "WAVEDEF_FIRE_BITS" not in _waves and "WAVEDEF_FIRE_AIMED" not in _waves)

waves_asm = (REPO / "src" / "waves.asm").read_text()
check("the engine no longer names a definition colour mask",
      "WAVEDEF_COLOUR_MASK" not in waves_asm and "WAVEDEF_COL_RANDOM" not in waves_asm)
check("...and the exporter no longer emits one",
      not hasattr(export_v6, "wavedef_colour_byte"))

# ---- validation -----------------------------------------------------------
print("\n=== the validator moved with the field ===")
v = EditorController.load(CANON, library_path=None)
v.project.triggers[0].colour_mode = "MAYBE"
codes = {i.code for i in validate(v.project).errors}
check("a colour mode that does not exist is refused on the TRIGGER",
      "trigger.colour_mode" in codes, ", ".join(sorted(c for c in codes if "colour" in c)))
v.project.triggers[0].colour_mode = "RANDOM"
v.project.triggers[0].colour = 99
codes = {i.code for i in validate(v.project).errors}
check("an out-of-range colour is refused even in RANDOM mode -- the low "
      "nibble is kept, so it still has to fit", "trigger.colour" in codes)
check("no wavedef colour rule survives",
      not any(c.startswith("wavedef.colour") for c in codes),
      ", ".join(sorted(c for c in codes if c.startswith("wavedef"))) or "none")

# ===========================================================================
# 4. THE WIDGETS
# ===========================================================================
print("\n=== the trigger UI ===")
gui = True
try:
    import tkinter as tk
    _r = tk.Tk()
    _r.destroy()
except Exception as exc:                                        # noqa: BLE001
    print(f"SKIP- the widget section needs a working Tk ({exc})")
    gui = False

if gui:
    import editor as ed
    ed.messagebox.showerror = lambda *a, **k: None
    ed.messagebox.showinfo = lambda *a, **k: None
    ed.messagebox.askyesno = lambda *a, **k: True
    import encounters_ui
    encounters_ui.messagebox.showerror = lambda *a, **k: None

    app = ed.LevelEditor(ed.find_repo_root())
    app.withdraw()                      # NEVER STEAL FOCUS
    app._open_encounters()
    w = app._encounters
    w.withdraw()
    app.update()

    def select(t):
        """Select a trigger THE WAY A USER DOES, through the tree.

        Assigning w.sel_trigger directly does not survive the next
        app.update(): the tree still has a pending <<TreeviewSelect>> from the
        last refresh, and its handler re-derives sel_trigger from the tree and
        overwrites the assignment. That cost an afternoon, so the helper
        exists rather than the habit.
        """
        i = w.controller.trigger_index_of(t)
        w.trig_tree.selection_set(str(i))
        w._trigger_selected()
        app.update()
        return i

    try:
        check("the wave-definition pane offers NO colour field",
              "colour" not in w.w_fields, ", ".join(sorted(w.w_fields)))
        check("...and no colour-mode control",
              not hasattr(w, "w_colmode"))
        check("the trigger pane offers a colour mode", hasattr(w, "t_colmode"))
        check("...and a fixed-colour entry", hasattr(w, "t_colour"))

        # ---- TWO TRIGGERS, ONE DEFINITION ---------------------------
        # TWO TRIGGERS ON THE *SAME* DEFINITION. "Each is shared" is not the
        # same claim and would have compared two different definitions.
        trigs = w.controller.project.triggers
        counts = {}
        for i, t in enumerate(trigs):
            counts.setdefault(t.wave_definition, []).append(i)
        defn, group = next((k, v) for k, v in counts.items() if len(v) > 1)
        a, b = group[0], group[1]
        check(f"two triggers share the definition {defn!r}",
              trigs[a].wave_definition == trigs[b].wave_definition,
              f"rows {trigs[a].world_progress} and {trigs[b].world_progress}")

        # CAPTURED BEFORE THE EDIT, from the trigger object that exists now.
        b_before = (trigs[b].colour_mode, trigs[b].colour)
        b_fire_before = trigs[b].resolved_fire_mode
        select(trigs[a])
        w.t_colmode.set(C.COLOUR_MODE_LABELS["FIXED"])
        w.t_colour.configure(state="normal")
        w.t_colour.delete(0, "end"); w.t_colour.insert(0, "3")
        w._trigger_apply()
        app.update()
        trigs = w.controller.project.triggers          # sort may have moved them
        ta = next(t for t in trigs if t.world_progress == rows[a][0])
        tb = next(t for t in trigs if t.world_progress == rows[b][0])
        check("trigger A is now Fixed cyan",
              (ta.colour_mode, ta.colour) == ("FIXED", 3),
              f"{ta.colour_mode} {ta.colour}")
        check("...AND TRIGGER B, ON THE SAME DEFINITION, IS UNTOUCHED",
              (tb.colour_mode, tb.colour) == b_before,
              f"{b_before} -> {(tb.colour_mode, tb.colour)}")
        check("...and the shared definition still has no colour to change",
              not hasattr(next(d for d in w.controller.project.wave_definitions
                               if d.id == defn), "colour"))

        # ---- AND THE SAME FOR FIRING ---------------------------------
        # The two triggers need a shooter each before a mode can matter.
        w._edit(w.controller.update_trigger,
                w.controller.trigger_index_of(ta), fire_mask=[0])
        w._edit(w.controller.update_trigger,
                w.controller.trigger_index_of(tb), fire_mask=[0])
        select(ta)
        w.t_firemode.set(C.FIRE_MODE_LABELS["AIMED"])
        w._trigger_apply()
        app.update()
        check("trigger A is now AIMED", ta.fire_mode == "AIMED", str(ta.fire_mode))
        check("...AND TRIGGER B, ON THE SAME DEFINITION, IS UNCHANGED",
              tb.resolved_fire_mode == b_fire_before,
              f"{b_fire_before} -> {tb.resolved_fire_mode}")
        check("...and the shared definition has no firing mode to change",
              not hasattr(next(d for d in w.controller.project.wave_definitions
                               if d.id == defn), "fire_mode"))
        select(ta)
        check("the trigger pane shows the mode it was given",
              w.t_firemode.get() == C.FIRE_MODE_LABELS["AIMED"])
        check("the edit marked the document dirty, like any other", app._is_dirty())

        # ---- Random greys the entry, and keeps its value -------------
        select(ta)
        check("a Fixed trigger's colour is editable",
              str(w.t_colour.cget("state")) == "normal")
        w.t_colmode.set(C.COLOUR_MODE_LABELS["RANDOM"])
        w._trigger_apply()
        app.update()
        check("choosing Random sets the trigger's mode", ta.colour_mode == "RANDOM")
        check("...greys the colour entry out",
              str(w.t_colour.cget("state")) == "disabled",
              str(w.t_colour.cget("state")))
        check("...and does NOT throw the chosen colour away", ta.colour == 3)

        # ---- the disabled-entry trap: the next trigger shows ITS colour
        select(tb)
        check("selecting another trigger after a Random one shows ITS colour",
              w.t_colour.get() == str(tb.resolved_colour),
              f"showed {w.t_colour.get()!r}, is {tb.resolved_colour}")

        # ---- and back to Fixed --------------------------------------
        select(ta)
        w.t_colmode.set(C.COLOUR_MODE_LABELS["FIXED"])
        w._trigger_apply()
        app.update()
        check("switching back to Fixed restores the stored colour",
              (ta.colour_mode, ta.colour) == ("FIXED", 3),
              f"{ta.colour_mode} {ta.colour}")
        check("...and re-enables the entry",
              str(w.t_colour.cget("state")) == "normal")
    finally:
        try:
            w.destroy()
        except Exception:                                       # noqa: BLE001
            pass
        app.destroy()

# ===========================================================================
# 5. SAVE -> RELOAD -> EXPORT, on a disposable copy
# ===========================================================================
print("\n=== the authoring round trip ===")
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    lvl_dir = tmp / "levels" / "level1"
    lvl_dir.mkdir(parents=True)
    shutil.copy2(CANON, lvl_dir / "level.v6.json")
    lib_path = tmp / "encounter_library.v6.json"
    shutil.copy2(LIB, lib_path)
    doc = lvl_dir / "level.v6.json"

    base = tmp / "export-base"
    changed = tmp / "export-changed"
    back = tmp / "export-back"

    ctl = EditorController.load(doc, library_path=lib_path)
    ctl.export(base, carry_enemies_from=PROD)
    base_cols = trig_colours(base)
    original = [(t.world_progress, t.resolved_colour_mode, t.resolved_colour)
                for t in ctl.project.triggers]
    orig_masks = [list(t.fire_mask) for t in ctl.project.triggers]
    orig_fires = [t.resolved_fire_mode for t in ctl.project.triggers]
    check("the exported column is one byte per trigger",
          len(base_cols) == len(ctl.project.triggers), str(len(base_cols)))
    check("...and every byte matches the model",
          base_cols == [export_v6.trigger_colour_byte(t)
                        for t in ctl.project.triggers])
    # WHATEVER THE AUTHOR CHOSE, CARRIED FAITHFULLY. The count of RANDOM
    # appearances is content, not contract, and freezing it made this fail the
    # first time the level was re-authored.
    check("...and each byte's random flag matches that trigger's mode",
          all(bool(b & C.TRIG_COL_RANDOM)
              == (t.resolved_colour_mode == "RANDOM")
              for b, t in zip(base_cols, ctl.project.triggers)),
          f"{sum(1 for b in base_cols if b & C.TRIG_COL_RANDOM)} random "
          f"of {len(base_cols)}")

    # ---- two sharers, changed independently, through the WHOLE path ----
    ids = [t.wave_definition for t in ctl.project.triggers]
    shared_id = next(i for i in ids if ids.count(i) > 1)
    idx = [i for i, t in enumerate(ctl.project.triggers)
           if t.wave_definition == shared_id]
    ctl.update_trigger(idx[0], colour_mode="FIXED", colour=3,
                       fire_mask=[0], fire_mode="AIMED")
    ctl.update_trigger(idx[1], colour_mode="FIXED", colour=7,
                       fire_mask=[0], fire_mode="DOWN")
    ctl.save()

    ctl2 = EditorController.load(doc, library_path=lib_path)
    got = [(t.world_progress, t.resolved_colour_mode, t.resolved_colour)
           for t in ctl2.project.triggers if t.wave_definition == shared_id]
    check(f"after save+reload, the {len(got)} triggers on {shared_id!r} differ",
          got[0][1:] == ("FIXED", 3) and got[1][1:] == ("FIXED", 7),
          str(got))
    fshared = [t.resolved_fire_mode for t in ctl2.project.triggers
               if t.wave_definition == shared_id]
    check("...AND SO DO THEIR FIRING MODES, from one shared definition",
          fshared[0] == "AIMED" and fshared[1] == "DOWN", str(fshared))
    check("...and the others are untouched",
          [(t.world_progress, t.resolved_colour_mode, t.resolved_colour)
           for t in ctl2.project.triggers if t.wave_definition != shared_id]
          == [r for r in original if r[0] not in {g[0] for g in got}])

    ctl2.export(changed, carry_enemies_from=PROD)
    cols = trig_colours(changed)
    check("the generated column carries the two different colours",
          cols[idx[0]] == 3 and cols[idx[1]] == 7,
          f"{cols[idx[0]]}, {cols[idx[1]]}")
    check("...from ONE shared definition, emitted once",
          len([n for n in defs_of(changed)]) == len(ctl2.project.wave_definitions))

    # ---- firing modes are undamaged ----------------------------------
    ddefs = defs_of(changed)
    check("EVERY definition's byte 7 is now reserved and zero",
          all(v[7] == 0 for v in ddefs.values()),
          str(sorted({v[7] for v in ddefs.values()})))
    fires = trig_fire_modes(changed)
    aimed_rows = [i for i, t in enumerate(ctl2.project.triggers)
                  if t.resolved_fire_mode == "AIMED"]
    check("the AIMED appearance exports AIMED in the TRIGGER column",
          bool(aimed_rows) and all(fires[i] == 1 for i in aimed_rows),
          f"rows {[ctl2.project.triggers[i].world_progress for i in aimed_rows]}")
    check("...and every other appearance exports DOWN",
          all(fires[i] == 0 for i in range(len(fires)) if i not in aimed_rows))
    check("the fire MASK column is untouched by the move",
          [t.fire_bits for t in ctl2.project.triggers]
          == [t.fire_bits for t in ctl.project.triggers])

    # ---- put it back, and nothing may have drifted --------------------
    for i, (_row, mode, colour) in zip(idx, [original[i] for i in idx]):
        ctl2.update_trigger(i, colour_mode=mode, colour=colour,
                            fire_mask=list(orig_masks[i]),
                            fire_mode=orig_fires[i])
    ctl2.save()
    ctl3 = EditorController.load(doc, library_path=lib_path)
    check("restoring both triggers returns the original model",
          [(t.world_progress, t.resolved_colour_mode, t.resolved_colour)
           for t in ctl3.project.triggers] == original)
    ctl3.export(back, carry_enemies_from=PROD)
    names = [n for n in export_v6.GENERATED_NAMES if (base / n).exists()]
    differing = [n for n in names
                 if (base / n).read_bytes() != (back / n).read_bytes()]
    check("EVERY generated file is byte-identical after the round trip",
          not differing, ", ".join(differing) or f"{len(names)} files compared")

    again = tmp / "export-again"
    ctl3.export(again, carry_enemies_from=PROD)
    check("exporting the same project twice is byte-identical",
          all((again / n).read_bytes() == (back / n).read_bytes() for n in names))

    # ---- and a saved document no longer needs the library to say colour
    saved = json.loads(doc.read_text())
    check("the saved document states every trigger's colour outright",
          all({"colour", "colourMode"} <= set(t) for t in saved["triggers"]))
    lib_saved = json.loads(lib_path.read_text())
    check("...and the saved library states none",
          not any({"colour", "colourMode"} & set(x)
                  for x in lib_saved["waveDefinitions"]))

# ===========================================================================
# 6. THE PRODUCTION FILES WERE NOT TOUCHED BY THIS TEST
# ===========================================================================
print("\n=== the committed sources are untouched ===")
check("the canonical level 1 document is byte-identical",
      CANON.read_bytes() == CANON_BYTES)
check("the shared encounter library is byte-identical",
      LIB.read_bytes() == LIB_BYTES)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for m in FAIL:
    print(f"  FAILED: {m}")
sys.exit(1 if FAIL else 0)
