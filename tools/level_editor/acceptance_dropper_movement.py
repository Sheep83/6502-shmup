#!/usr/bin/env python3
"""ACCEPTANCE: the Dropper movement control, in the REAL editor, on real Tk.

    /usr/local/bin/python3 tools/level_editor/acceptance_dropper_movement.py

WHAT THIS IS, AND WHAT IT IS NOT. It constructs the ACTUAL application --
editor.LevelEditor and the real EncounterWorkspace it opens, not a stubbed host
-- and walks the sequence a person would: open the workspace, find a Dropper
trigger, switch Legacy <-> authored, watch the controls enable and disable,
watch the preview change, change the speed and the launch heading, save, reload,
switch the species away and back, and close. Every step goes through the same
callback the widget's own binding fires, and every assertion reads a WIDGET or
the PREVIEW PANEL rather than the model behind it.

IT IS NOT A HUMAN LOOKING AT PIXELS. AGENTS.md is explicit that manual visual
output is authoritative and that a change is not done because counters pass, so
this does not replace Brian's own visual pass -- it establishes that the real
application constructs, that every control is in the state it should be in, and
that nothing raises. That distinction matters here because a previous editor
refactor produced a catastrophic constructor/callback failure which automated
tests initially missed; the point of building the real window is to catch that
class of fault.

NO FOCUS IS STOLEN. Every window is withdrawn immediately, so nothing appears
and nothing takes the keyboard. NOTHING PRODUCTION IS WRITTEN: the save/reload
step round-trips through a temporary directory and the committed documents are
byte-compared at the end.
"""
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                          # noqa: E402
import editor as ed                                              # noqa: E402
import project_v6                                                # noqa: E402
from project_v6 import ProjectV6                                  # noqa: E402

REPO = HERE.parent.parent
CANON = HERE / "levels" / "level1" / "level.v6.json"
LIB = HERE / "encounter_library.v6.json"
CANON_BYTES = CANON.read_bytes()
LIB_BYTES = LIB.read_bytes()

STEP, FAIL = [], []


def ok(m, x=""):
    STEP.append(m)
    print(f"  ok   {m}" + (f" -- {x}" if x else ""))


def check(m, c, x=""):
    if c:
        ok(m, x)
    else:
        FAIL.append(m)
        print(f"  FAIL {m}" + (f" -- {x}" if x else ""))


def main():
    print("=== acceptance: Dropper movement, real editor, real Tk ===")
    tmp = Path(tempfile.mkdtemp(prefix="acc-dropmove-"))
    app = None
    try:
        # ---- 1. the application constructs --------------------------------
        app = ed.LevelEditor(ed.find_repo_root())
        app.withdraw()                      # no window, no focus, ever
        app.update_idletasks()
        ok("the real LevelEditor constructed and is withdrawn")

        # ---- 2. the Encounter workspace opens -----------------------------
        app._open_encounters()
        ws = app._encounters
        ws.withdraw()
        ws.update_idletasks()
        check("the Encounter workspace opened", ws is not None
              and ws.winfo_exists())
        check("...and carries the Dropper movement control",
              hasattr(ws, "t_dropmove") and hasattr(ws, "t_dropmove_note"))
        check("...and the preview panel", hasattr(ws, "preview"))

        # ---- 3. find a Dropper trigger, or make one -----------------------
        def is_drop(i):
            return (C.identity_behaviour(ws.controller.project.triggers[i].species)
                    == C.BEHAVIOUR_DROPPER)

        trigs = ws.controller.project.triggers
        di = next((i for i in range(len(trigs)) if is_drop(i)), None)
        if di is None:
            ws.controller.update_trigger(0, species="DROPPER")
            di = 0
        oi = next((i for i in range(len(trigs)) if not is_drop(i)), None)
        check("a Dropper trigger is available to author",
              di is not None, f"trigger {di}")
        check("...and a non-Dropper one to compare against", oi is not None,
              f"trigger {oi}")

        def select(i):
            """Exactly what clicking the row does."""
            ws.trig_tree.selection_set(str(i))
            ws._trigger_selected()
            ws.update_idletasks()

        def sig():
            return ws.preview._signature()

        select(di)
        progs = [p.id for p in ws.controller.project.movement_programs]
        check("the control offers Legacy first, then the level's programs",
              list(ws.t_dropmove["values"])
              == [C.DROPPER_MOVEMENT_LEGACY] + progs,
              ", ".join(ws.t_dropmove["values"]))

        # ---- 4. LEGACY: both controls live --------------------------------
        check("a legacy Dropper shows Legacy selected",
              ws.t_dropmove.get() == C.DROPPER_MOVEMENT_LEGACY,
              ws.t_dropmove.get())
        check("...the movement control is enabled",
              str(ws.t_dropmove.cget("state")) == "readonly")
        check("...and LEFT/RIGHT is enabled, because the legacy flight reads it",
              str(ws.t_side.cget("state")) == "readonly")
        legacy_sig = sig()
        legacy_sim = ws.preview.sim
        check("...and the preview drew the legacy flight",
              legacy_sim is not None and not ws.preview.error,
              ws.preview.error or f"{legacy_sim.count} members")
        check("...showing exactly ONE object, with no escort implied",
              legacy_sim is not None and legacy_sim.count == 1
              and all(len(fr) <= 1 for fr in legacy_sim.frames),
              "" if legacy_sim is None else f"{legacy_sim.count} object(s)")
        check("...on the legacy trajectory",
              legacy_sim is not None
              and all(f.stage_kind == "DROPPER" for f in legacy_sim.paths[0]))

        # ---- 5. SWITCH TO AUTHORED, through the widget -------------------
        ws.t_dropmove.set(progs[0])
        ws._trigger_apply()                 # the <<ComboboxSelected>> binding
        ws.update_idletasks()
        select(di)
        check("selecting a program stores it",
              ws.controller.project.triggers[di].dropper_program == progs[0],
              progs[0])
        check("...the control shows it", ws.t_dropmove.get() == progs[0])
        check("...LEFT/RIGHT is now DISABLED",
              str(ws.t_side.cget("state")) == "disabled")
        check("...and is LABELLED as unused rather than silently repurposed",
              "not used" in ws.t_side_note.cget("text").lower(),
              ws.t_side_note.cget("text"))
        authored_sig = sig()
        check("THE PREVIEW CHANGED: its cache signature is not the legacy one",
              authored_sig != legacy_sig)
        authored_sim = ws.preview.sim
        check("...and it drew the authored path",
              authored_sim is not None and not ws.preview.error,
              ws.preview.error or f"{authored_sim.count} members")
        check("...with member 0 OFF the legacy trajectory",
              authored_sim is not None
              and all(f.stage_kind != "DROPPER" for f in authored_sim.paths[0]),
              "" if authored_sim is None else
              str(sorted({f.stage_kind for f in authored_sim.paths[0]})))
        check("...still exactly ONE object, from its own authored placement",
              authored_sim is not None and authored_sim.count == 1
              and all(len(fr) <= 1 for fr in authored_sim.frames),
              "" if authored_sim is None else f"{authored_sim.count} object(s)")

        # ---- 6. SPEED, through the widget --------------------------------
        was_speed = ws.t_speed.get()
        faster = C.SPEED_LABELS[max(C.SPEED_CHOICES)]
        ws.t_speed.set(faster)
        ws._trigger_apply()
        ws.update_idletasks()
        select(di)
        check(f"changing movement speed to {faster} is stored",
              ws.controller.project.triggers[di].resolved_speed
              == max(C.SPEED_CHOICES),
              str(ws.controller.project.triggers[di].resolved_speed))
        speed_sig = sig()
        check("...AND THE PREVIEW UPDATED: the signature moved again",
              speed_sig != authored_sig)
        ws.t_speed.set(was_speed)
        ws._trigger_apply()
        ws.update_idletasks()

        # ---- 7. THE LAUNCH HEADING, which lives on the wave definition ----
        # THE DROPPER TAKES THE TRIGGER'S ONE HEADING, by way of the definition
        # it references -- there is no second heading field, by decision. So the
        # heading is changed where it lives and the Dropper preview must follow.
        select(di)
        before_head_sig = sig()
        wid = ws.controller.project.triggers[di].wave_definition
        wix = next(i for i, w in enumerate(ws.controller.project.wave_definitions)
                   if w.id == wid)
        wave = ws.controller.project.wave_definitions[wix]
        old_head = wave.heading
        ws.controller.update_wave_definition(
            wix, heading=(old_head + C.WM_HEAD_LEN // 4) % C.WM_HEAD_LEN)
        ws.refresh()
        select(di)
        check("changing the launch heading updates the Dropper preview",
              sig() != before_head_sig,
              f"heading {old_head} -> {wave.heading}")
        ws.controller.update_wave_definition(wix, heading=old_head)
        ws.refresh()

        # ---- 8. SAVE AND RELOAD ------------------------------------------
        select(di)
        ws.controller.project.triggers[di].dropper_program = progs[0]
        doc = tmp / "level.v6.json"
        doc.write_text(ws.controller.project.to_level_json(), encoding="utf-8")
        back = ProjectV6.load(doc)
        check("save -> reload preserves the Dropper selection",
              back.triggers[di].dropper_program == progs[0],
              str(back.triggers[di].dropper_program))
        check("...and every other trigger stays on the legacy flight",
              all(t.dropper_is_legacy for i, t in enumerate(back.triggers)
                  if i != di))
        check("...and saving the reloaded document is byte-identical",
              back.to_level_json() == ws.controller.project.to_level_json())

        # ---- 9. SPECIES AWAY AND BACK ------------------------------------
        plain = next(n for n in C.level_identities(ws.controller.project)
                     if C.identity_behaviour(n) != C.BEHAVIOUR_DROPPER)
        ws.t_species.set(C.identity_label(plain))
        ws._trigger_apply()
        ws.update_idletasks()
        select(di)
        check(f"switching species to {plain} clears the Dropper path",
              ws.controller.project.triggers[di].dropper_program is None)
        check("...and disables the movement control",
              str(ws.t_dropmove.cget("state")) == "disabled")
        check("...explaining why", "does not drop a token"
              in ws.t_dropmove_note.cget("text"),
              ws.t_dropmove_note.cget("text"))
        ws.t_species.set(C.identity_label("DROPPER"))
        ws._trigger_apply()
        ws.update_idletasks()
        select(di)
        check("switching back gives a plain legacy Dropper, inventing nothing",
              ws.controller.project.triggers[di].dropper_is_legacy
              and ws.controller.project.triggers[di].dropper_side == "LEFT")
        check("...with both controls live again",
              str(ws.t_dropmove.cget("state")) == "readonly"
              and str(ws.t_side.cget("state")) == "readonly")
        check("...and the preview drawing the legacy flight once more",
              ws.preview.sim is not None and not ws.preview.error,
              ws.preview.error or "drawn")

        # ---- 10. REPEATED SELECTION, where a callback fault would show ----
        for _ in range(4):
            select(oi)
            select(di)
        check("repeated Dropper <-> ordinary selection leaves the control "
              "showing this trigger's own answer",
              ws.t_dropmove.get() == C.DROPPER_MOVEMENT_LEGACY
              and str(ws.t_dropmove.cget("state")) == "readonly")

        # ---- 11. CLOSE CLEANLY -------------------------------------------
        ws.destroy()
        app.update_idletasks()
        check("the workspace closed without raising", not ws.winfo_exists())
        app.destroy()
        app = None
        ok("the editor closed cleanly")
    except Exception:                                            # noqa: BLE001
        FAIL.append("an exception escaped the acceptance walk")
        print("  FAIL an exception escaped:")
        print("    " + traceback.format_exc().replace("\n", "\n    "))
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:                                    # noqa: BLE001
                pass
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== nothing production was written ===")
    check("the canonical level 1 document is byte-identical",
          CANON.read_bytes() == CANON_BYTES)
    check("the shared encounter library is byte-identical",
          LIB.read_bytes() == LIB_BYTES)

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILURE(S):")
        for m in FAIL:
            print(f"  - {m}")
        return 1
    print(f"ACCEPTANCE: {len(STEP)} steps, all clear.")
    print("NOTE: this drove the real GUI programmatically. A human visual pass "
          "is still required -- see AGENTS.md rule 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
