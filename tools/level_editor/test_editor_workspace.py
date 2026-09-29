#!/usr/bin/env python3
"""Real Tk construction coverage for the editor's Encounter workspace.

WHY THIS FILE EXISTS. The enemy-identity pass shipped with a full green suite
and an editor that could not open its Encounter window: `_build()` reached for
`self.project`, which an EncounterWorkspace has never had, so construction
aborted after the Triggers tab. Wave Definitions and Moves were never built,
every later callback met a missing widget, and the window could not even be
closed because `_close()` used a preview that construction never reached.

Every test that existed called helpers in isolation. None of them ever asked
Tk to build the window, so none of them could have caught it. This one does:
it constructs the real EncounterWorkspace over real Level 1 data and then uses
it. If the same class of mistake returns, this fails.

NO FOCUS IS STOLEN. The root is withdrawn before anything is mapped, so the
widgets are genuinely created by Tk but nothing appears on screen and the
desktop keeps its focus. If no display is available the file says so and exits
0 rather than reporting a pass it did not earn.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PASS, FAIL = [], []


def check(label, ok, detail=""):
    (PASS if ok else FAIL).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f" -- {detail}" if detail else ""))


try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
except Exception as exc:                                   # noqa: BLE001
    print(f"  SKIP: no usable display ({type(exc).__name__}: {exc})")
    print("  0 passed, 0 failed (skipped)")
    raise SystemExit(0)

import contract_v2 as C                                     # noqa: E402
import encounters_ui                                        # noqa: E402
from controller_v6 import EditorController                  # noqa: E402

LEVEL1 = HERE / "levels" / "level1" / "level.v6.json"


class _Host(tk.Toplevel):
    """The little the workspace actually uses from the main editor window."""

    def __init__(self, master, controller):
        super().__init__(master)
        self.withdraw()
        self.controller = controller
        self.project = controller.view          # the editor holds the VIEW
        self._encounters = None

    # the workspace calls back into these after an edit
    def _push_undo(self, before):
        pass

    def _update_document_ui(self):
        pass

    def _draw_level(self):
        pass


# ===========================================================================
# 1. The view layer really can hold an identity selection
# ===========================================================================
ctrl = EditorController.load(LEVEL1)
view = ctrl.view

check("the editor holds a V5View, which is what the regression tripped over",
      type(view).__name__ == "V5View")
try:
    view.enemy_slots = ["RING_3", "SPACE_WHISK", "SPINNER"]
    _set_ok, _why = True, ""
except Exception as exc:                                    # noqa: BLE001
    _set_ok, _why = False, f"{type(exc).__name__}: {exc}"
check("enemy identities can be set THROUGH THE VIEW", _set_ok, _why)
check("...and read back from the view",
      list(view.enemy_slots) == ["RING_3", "SPACE_WHISK", "SPINNER"],
      str(list(view.enemy_slots)))
check("...and reach the underlying ProjectV6",
      C.level_identities(ctrl.project) == ["RING_3", "SPACE_WHISK", "SPINNER"],
      str(C.level_identities(ctrl.project)))
check("a short or unknown selection is normalised, not stored raw",
      (setattr(view, "enemy_slots", ["RING_3"]) or
       len(list(view.enemy_slots)) == C.ENEMY_SLOTS),
      str(list(view.enemy_slots)))

# put a known three back for the workspace tests
view.enemy_slots = ["RING_3", "SPACE_WHISK", "SPINNER"]

# ===========================================================================
# 2. The workspace constructs COMPLETELY
# ===========================================================================
host = _Host(_root, ctrl)
ws = None
try:
    ws = encounters_ui.EncounterWorkspace(host)
    ws.withdraw()
    _built, _why = True, ""
except Exception:                                           # noqa: BLE001
    _built, _why = False, traceback.format_exc().strip().splitlines()[-1]
check("EncounterWorkspace constructs without raising", _built, _why)

if ws is not None:
    # The three authoring areas. Checking a WIDGET from each, not a tab label:
    # the regression left the notebook itself present and the tabs missing.
    check("the Triggers controls exist", hasattr(ws, "t_species"))
    check("the Wave Definitions controls exist", hasattr(ws, "wave_list"))
    check("the Moves controls exist", hasattr(ws, "prog_list"))
    check("all three notebook tabs are present",
          len(ws.tabs.tabs()) >= 3, f"{len(ws.tabs.tabs())} tabs")
    check("the preview _close() depends on exists", hasattr(ws, "preview"))
    check("the workspace never grew a bogus `project` attribute",
          not hasattr(ws, "project"))

    # ---- the trigger enemy selector offers THIS level's identities --------
    labels = list(ws.t_species.cget("values"))
    want = [C.identity_label(n) for n in C.level_identities(ctrl.project)]
    check("the trigger enemy selector lists the level's own identities",
          labels == want, f"{labels} vs {want}")
    check("...by human-readable name, not a legacy species",
          "Space Whisk" in labels and "Sonic Ring" not in labels, str(labels))

    # ---- selecting a trigger refreshes its detail without raising ---------
    try:
        if ctrl.project.triggers:
            ws.sel_trigger = 0
            ws._refresh_trigger_detail()
        _sel_ok, _why = True, ""
    except Exception:                                       # noqa: BLE001
        _sel_ok, _why = False, traceback.format_exc().strip().splitlines()[-1]
    check("selecting a trigger refreshes its detail", _sel_ok, _why)

    # ---- a full refresh, and tab switching --------------------------------
    try:
        ws.refresh()
        for tab in ws.tabs.tabs():
            ws.tabs.select(tab)
            ws.update_idletasks()
        _ref_ok, _why = True, ""
    except Exception:                                       # noqa: BLE001
        _ref_ok, _why = False, traceback.format_exc().strip().splitlines()[-1]
    check("refresh and switching every tab raise nothing", _ref_ok, _why)

    # ---- changing the level's identities re-offers the trigger choices ----
    try:
        view.enemy_slots = ["RING_1", "DROPPER", "SQUARE"]
        ws.refresh_identities()
        _new = list(ws.t_species.cget("values"))
        _id_ok = _new == [C.identity_label(n)
                          for n in C.level_identities(ctrl.project)]
        _why = str(_new)
    except Exception:                                       # noqa: BLE001
        _id_ok, _why = False, traceback.format_exc().strip().splitlines()[-1]
    check("changing the level's enemies re-offers the trigger choices",
          _id_ok, _why)

    # ---- close, cleanly, through the real handler -------------------------
    try:
        ws._close()
        _close_ok, _why = True, ""
    except Exception:                                       # noqa: BLE001
        _close_ok, _why = False, traceback.format_exc().strip().splitlines()[-1]
    check("the workspace closes through its own WM handler", _close_ok, _why)
    check("...and tells the host it is gone", host._encounters is None)

    # ---- and can be reopened ---------------------------------------------
    try:
        ws2 = encounters_ui.EncounterWorkspace(host)
        ws2.withdraw()
        _re_ok = hasattr(ws2, "wave_list") and hasattr(ws2, "prog_list")
        ws2._close()
        _why = ""
    except Exception:                                       # noqa: BLE001
        _re_ok, _why = False, traceback.format_exc().strip().splitlines()[-1]
    check("it can be reopened and closed again", _re_ok, _why)

# ===========================================================================
# 3. A failed construction must not leave a live window behind
# ===========================================================================
_orig = encounters_ui.EncounterWorkspace._build_programs
def _boom(self, nb):
    raise RuntimeError("simulated construction failure")
encounters_ui.EncounterWorkspace._build_programs = _boom
try:
    encounters_ui.EncounterWorkspace(host)
    _raised = False
except RuntimeError:
    _raised = True
except Exception:                                           # noqa: BLE001
    _raised = False
finally:
    encounters_ui.EncounterWorkspace._build_programs = _orig
check("a construction failure propagates rather than leaving a half window",
      _raised)
check("...and the host was not left pointing at a dead workspace",
      host._encounters is None)

# ===========================================================================
# 4. Round trip: change identities -> save -> reload -> export
# ===========================================================================
import json, tempfile                                        # noqa: E402
import encounter_library, export_v6                          # noqa: E402

with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "level.v6.json"
    c2 = EditorController.load(LEVEL1, library_path=encounter_library.LIBRARY_PATH)
    c2.view.enemy_slots = ["RING_3", "SPACE_WHISK", "SPINNER"]
    for t in c2.project.triggers:                # keep triggers exportable
        t.species = "RING_3"
    c2.save(p)
    back = EditorController.load(p, library_path=encounter_library.LIBRARY_PATH)
    check("identities survive save and reload",
          C.level_identities(back.project) == ["RING_3", "SPACE_WHISK", "SPINNER"],
          str(C.level_identities(back.project)))
    check("the saved JSON carries them",
          json.loads(p.read_text())["enemySlots"]
          == ["RING_3", "SPACE_WHISK", "SPINNER"])
    text = export_v6.render_stage_enemies(back.project, "roundtrip")
    check("and the level exports with them",
          "Space Whisk" in text and "Spinner" in text and "Ring 3" in text)
    check("...costing 8 + 6 + 6 = 20 of 20, the exact boundary",
          "LVL_SPR_BLOCKS = 20" in text,
          [l for l in text.splitlines() if "LVL_SPR_BLOCKS" in l][0].strip())

# over budget is refused by the exporter, whatever the UI did
c3 = EditorController.load(LEVEL1)
c3.view.enemy_slots = ["RING_3", "RING_3", "SPINNY_ROT"]        # 8 + 8 + 5
try:
    export_v6.render_stage_enemies(c3.project, "over")
    _ref = False
except export_v6.ExportRefused:
    _ref = True
check("8 + 8 + 5 = 21 is refused by the exporter", _ref)
check("...and the editor can climb back under budget from there",
      (setattr(c3.view, "enemy_slots", ["RING_3", "SQUARE", "SPINNY_ROT"]) or
       not C.enemy_slot_problems(C.level_identities(c3.project))),
      f"{C.enemy_slot_cost(C.level_identities(c3.project))} / "
      f"{C.LEVEL_SPRITE_BLOCKS}")

# ===========================================================================
# 5. THE EDITOR ITSELF STARTS, and its identity callback works
# ===========================================================================
# `python3 editor.py` is the thing that has to work. Constructing the real
# LevelEditor is the only check that covers the widgets it builds at start-up,
# including the enemy identity row whose callback raised on the V5View.
# ONE ROOT AT A TIME. LevelEditor is itself a Tk root, and two live roots in
# one interpreter give "image pyimage1 doesn't exist" the moment either builds
# an image. The workspace tests above are finished with ours, so it goes first.
_root.destroy()

import editor as _E                                          # noqa: E402

_app = None
try:
    _app = _E.LevelEditor(_E.find_repo_root())
    _app.withdraw()
    _start_ok, _why = True, ""
except Exception:                                            # noqa: BLE001
    _start_ok, _why = False, traceback.format_exc().strip().splitlines()[-1]
check("the editor itself constructs, as `python3 editor.py` does", _start_ok, _why)

if _app is not None:
    check("the level enemy row offers the whole roster",
          len(_app._art_choices) == len(C.ROSTER_FRAMES),
          f"{len(_app._art_choices)} choices")
    check("the sprite budget is shown",
          "/" in _app.enemy_budget_text.get(), _app.enemy_budget_text.get())

    # the exact callback that raised on V5View
    def _pick(i, name):
        _app.enemy_art_vars[i].set(f"{C.ROSTER_LABELS[name]}  "
                                   f"({C.ROSTER_FRAMES[name]})")
    try:
        _pick(0, "RING_3"); _pick(1, "SPACE_WHISK"); _pick(2, "SQUARE")
        _app._apply_enemy_art()                     # 8 + 6 + 4 = 18
        _cb_ok, _why = True, ""
    except Exception:                                        # noqa: BLE001
        _cb_ok, _why = False, traceback.format_exc().strip().splitlines()[-1]
    check("changing a level enemy through the real callback raises nothing",
          _cb_ok, _why)
    check("...8 + 6 + 4 = 18 and the budget says so",
          _app.enemy_budget_text.get().endswith("18 / 20"),
          _app.enemy_budget_text.get())

    _pick(2, "SPACE_WHISK"); _app._apply_enemy_art()          # 8 + 6 + 6 = 20
    check("...8 + 6 + 6 = 20 is accepted and shown as exactly full",
          _app.enemy_budget_text.get().endswith("20 / 20"),
          _app.enemy_budget_text.get())

    _pick(1, "RING_3"); _pick(2, "SPINNY_ROT"); _app._apply_enemy_art()
    check("...8 + 8 + 5 = 21 is shown as over budget",
          "OVER BUDGET" in _app.enemy_budget_text.get(),
          _app.enemy_budget_text.get())

    _pick(1, "SQUARE"); _app._apply_enemy_art()               # back under
    check("...and another slot can bring it back under budget",
          "OVER BUDGET" not in _app.enemy_budget_text.get(),
          _app.enemy_budget_text.get())

    # Encounters through the editor's own menu path, then closed
    try:
        _app._open_encounters()
        _w = _app._encounters
        _open_ok = (len(_w.tabs.tabs()) >= 3 and hasattr(_w, "t_species")
                    and hasattr(_w, "wave_list") and hasattr(_w, "prog_list"))
        _w._close()
        _open_ok = _open_ok and _app._encounters is None
        _why = ""
    except Exception:                                        # noqa: BLE001
        _open_ok, _why = False, traceback.format_exc().strip().splitlines()[-1]
    check("Encounters opens and closes through the editor's own menu path",
          _open_ok, _why)
    try:
        _app.destroy()
    except tk.TclError:
        pass

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for f in FAIL:
    print(f"  FAILED: {f}")
raise SystemExit(1 if FAIL else 0)
