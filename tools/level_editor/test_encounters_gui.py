#!/usr/bin/env python3
"""Phase 5B, widget layer: the encounter workspace against real Tk.

The model operations are proved headlessly in test_v6_phase5b_encounters.py.
What can only be proved with widgets is that the workspace is WIRED to them:
that an encounter edit marks the document dirty and joins the same undo stack as
a terrain edit, that merely looking at something does not, and that the two
windows stay in step.

Run with an interpreter that has a working Tk (see the Phase 5A report):
    /usr/local/bin/python3 test_encounters_gui.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import tkinter as tk
    _r = tk.Tk()
    _r.destroy()
except Exception as exc:                                        # noqa: BLE001
    print(f"SKIP - Tk unavailable ({exc})")
    sys.exit(0)

import editor as ed                                             # noqa: E402

ed.messagebox.showerror = lambda *a, **k: None
ed.messagebox.showinfo = lambda *a, **k: None
_ANSWER = {"str": None}
ed.simpledialog.askstring = lambda *a, **k: _ANSWER["str"]
ed.messagebox.askyesno = lambda *a, **k: True
import encounters_ui                                            # noqa: E402
encounters_ui.messagebox.showerror = lambda *a, **k: None
encounters_ui.messagebox.askyesno = lambda *a, **k: True
encounters_ui.simpledialog.askstring = lambda *a, **k: _ANSWER["str"]

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


app = ed.LevelEditor(ed.find_repo_root())
app.withdraw()
app._open_encounters()
w = app._encounters
w.withdraw()
app.update()

try:
    # =====================================================================
    # the workspace is over the SAME controller as the terrain window
    # =====================================================================
    check("the workspace shares the host's controller",
          w.controller is app.controller)
    check("the document opens clean", not app._is_dirty())

    # ---- navigation must not dirty anything ---------------------------
    w.sel_trigger = 2
    w._refresh_trigger_detail()
    w.sel_wave = 1
    w._refresh_wave_detail()
    w.sel_prog = 2
    w._refresh_stages()
    w.refresh()
    check("selecting triggers, waves and programs does NOT mark the project dirty",
          not app._is_dirty())

    # =====================================================================
    # every encounter edit is dirty + undoable, like a terrain edit
    # =====================================================================
    def cycle(name, do, changed, undo_back):
        depth = len(app.undo_stack)
        before = app.controller.to_json()
        do()
        check(f"{name} marks the project dirty", app._is_dirty())
        check(f"{name} pushes exactly one undo step",
              len(app.undo_stack) == depth + 1,
              f"{depth} -> {len(app.undo_stack)}")
        check(f"{name} really changed the model", changed())
        app._undo()
        check(f"{name} undo restores the whole project",
              app.controller.to_json() == before)
        check(f"{name} redo re-applies it",
              (app._redo(), changed())[1])
        app._undo()
        check(f"{name} is back to the starting document",
              app.controller.to_json() == before and undo_back())

    cycle("trigger add",
          lambda: w._trigger_add(),
          lambda: len(app.controller.project.triggers) == 5,
          lambda: len(app.controller.project.triggers) == 4)

    w.sel_trigger = 0
    w._refresh_trigger_detail()
    cycle("trigger edit",
          lambda: (w.t_prog.delete(0, "end"), w.t_prog.insert(0, "30"),
                   w._trigger_apply()),
          lambda: app.controller.project.triggers[0].world_progress == 30,
          lambda: app.controller.project.triggers[0].world_progress == 48)

    w.sel_trigger = 1
    w._refresh_trigger_detail()
    cycle("trigger delete",
          lambda: w._trigger_delete(),
          lambda: len(app.controller.project.triggers) == 3,
          lambda: len(app.controller.project.triggers) == 4)

    cycle("noSpawn change",
          lambda: (w.no_spawn_var.set("300"), w._apply_no_spawn()),
          lambda: app.controller.project.stage.no_spawn_row == 300,
          lambda: app.controller.project.stage.no_spawn_row == 340)

    w.sel_wave = 2
    w._refresh_wave_detail()
    cycle("wave definition field edit",
          lambda: (w.w_fields["interval"].delete(0, "end"),
                   w.w_fields["interval"].insert(0, "31"), w._wave_apply()),
          lambda: app.controller.project.wave_definitions[2].interval == 31,
          lambda: app.controller.project.wave_definitions[2].interval == 26)

    w.sel_prog, w.sel_stage = 1, 0
    w._refresh_stages()
    w._refresh_stage_detail()
    cycle("movement stage edit",
          lambda: (w.s_fields["steps"].delete(0, "end"),
                   w.s_fields["steps"].insert(0, "19"), w._stage_apply()),
          lambda: app.controller.project.movement_programs[1].stages[0].steps == 19,
          lambda: app.controller.project.movement_programs[1].stages[0].steps == 12)

    w.sel_prog, w.sel_stage = 2, 0
    w._refresh_stages()
    cycle("movement stage reorder",
          lambda: w._stage_move(1),
          lambda: [s.kind for s in app.controller.project.movement_programs[2].stages]
                  == ["HOLD", "STRAIGHT", "ARC", "EXIT"],
          lambda: [s.kind for s in app.controller.project.movement_programs[2].stages]
                  == ["STRAIGHT", "HOLD", "ARC", "EXIT"])

    # =====================================================================
    # the fire-mask checkboxes drive the real mask
    # =====================================================================
    w.sel_trigger = 0
    w._refresh_trigger_detail()
    check("the fire boxes match the referenced wave's member count",
          len(w._fire_vars) == 4, f"{len(w._fire_vars)} boxes")
    check("...and reflect the authored mask",
          [m for m, v in w._fire_vars if v.get()] == [0, 2])
    before = app.controller.to_json()
    dict(w._fire_vars)[1].set(1)
    w._fire_changed()
    check("ticking a member writes it into the trigger",
          app.controller.project.triggers[0].fire_mask == [0, 1, 2],
          str(app.controller.project.triggers[0].fire_mask))
    app._undo()
    check("...and it is undoable", app.controller.to_json() == before)

    # =====================================================================
    # a rename from the workspace updates references and is one undo step
    # =====================================================================
    w.sel_prog = 0
    w._refresh_programs()
    _ANSWER["str"] = "sweep_renamed"
    depth = len(app.undo_stack)
    before = app.controller.to_json()
    w._prog_rename()
    check("renaming a program from the workspace updates the wave definition",
          app.controller.project.wave_definitions[0].movement_program == "sweep_renamed",
          app.controller.project.wave_definitions[0].movement_program)
    check("...as a single undo step", len(app.undo_stack) == depth + 1)
    app._undo()
    check("...and undo restores both the id and the reference",
          app.controller.to_json() == before)
    _ANSWER["str"] = None

    # =====================================================================
    # save / reopen reproduces the same workspace
    # =====================================================================
    check("the document is clean again after all those undos", not app._is_dirty())
    with tempfile.TemporaryDirectory() as d:
        tgt = Path(d) / "level.v6.json"
        ed.filedialog.asksaveasfilename = lambda *a, **k: str(tgt)
        app._save_project_as()
        check("Save As from a workspace session writes the canonical bytes",
              tgt.read_bytes() ==
              (Path(ed.__file__).parent / "levels/level1/level.v6.json").read_bytes())
        ed.filedialog.askopenfilename = lambda *a, **k: str(tgt)
        app._open_level()
        check("reopening follows the workspace onto the new document",
              w.controller is app.controller)
        rows = [w.trig_tree.item(i, "values") for i in w.trig_tree.get_children()]
        check("...and it shows the same four triggers",
              [int(r[0]) for r in rows] == [48, 52, 90, 126], str(rows))

    # =====================================================================
    # validation feedback is the validator's, not a second rule set
    # =====================================================================
    w.no_spawn_var.set("40")
    w._apply_no_spawn()                       # strands every trigger
    msgs = [w.issues.item(i, "values") for i in w.issues.get_children()]
    check("an invalid noSpawn shows validator ERRORs in the panel",
          any(m[0] == "ERROR" and "noSpawnRow" in m[2] for m in msgs),
          str(msgs[:1]))
    check("...and export is blocked while they stand",
          not app.controller.validate().ok)
    app._undo()
    check("...and undo clears them", app.controller.validate().ok)

finally:
    if w.winfo_exists():
        w.destroy()
    app.destroy()

print()
if FAIL:
    print(f"{len(FAIL)} FAILURE(S):")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {len(PASS)} encounter-workspace GUI checks passed.")
