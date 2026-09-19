#!/usr/bin/env python3
"""Phase 6A, widget layer: the preview panel against real Tk.

The simulation is proved elsewhere -- against the engine in
test_movement_sim_engine.py and test_formation_sim_engine.py. What can only be
proved with widgets is that the panel is WIRED to it: that a selection
resolves the authored chain, that the transport controls address precomputed
frames, that an authored edit is picked up without saving anything, and --
the one that matters most for an authoring tool -- that LOOKING AT A PREVIEW
NEVER CHANGES THE PROJECT.

Run with an interpreter that has a working Tk (see the Phase 5A report):
    /usr/local/bin/python3 test_preview_gui.py
"""
import sys
import time
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
ed.messagebox.askyesno = lambda *a, **k: True
import encounters_ui                                            # noqa: E402
import movement_sim as ms                                       # noqa: E402
encounters_ui.messagebox.showerror = lambda *a, **k: None
encounters_ui.messagebox.askyesno = lambda *a, **k: True

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
p = w.preview

RING = [i for i, t in enumerate(app.controller.project.triggers)
        if t.species == "RING"]
DROP = [i for i, t in enumerate(app.controller.project.triggers)
        if t.species == "DROPPER"]


def select_trigger(i):
    w.tabs.select(0)
    w.trig_tree.selection_set(str(i))
    app.update()


try:
    # =====================================================================
    # selection resolves the authored chain
    # =====================================================================
    check("the workspace has a preview panel", p is not None)
    select_trigger(RING[0])
    t = app.controller.project.triggers[RING[0]]
    check("selecting a RING trigger produces a simulation", p.sim is not None)
    check("...resolved trigger -> wave -> program",
          p.sim.wave_id == t.wave_definition
          and p.sim.program_id == next(
              d.movement_program for d in app.controller.project.wave_definitions
              if d.id == t.wave_definition),
          f"{p.sim.wave_id} -> {p.sim.program_id}")
    check("...and the headline names the whole chain",
          "wave" in p.headline.get() and "program" in p.headline.get(),
          p.headline.get())
    check("...with one path per authored member",
          len(p.sim.paths) == p.sim.count)
    check("the panel does NOT start playing on a selection change",
          not p.playing)
    check("...and the canvas actually drew the paths",
          len(p.canvas.find_withtag("path")) > 0,
          f"{len(p.canvas.find_withtag('path'))} path items")
    check("...and the visible playfield is drawn",
          len(p.canvas.find_withtag("field")) >= 4)

    # =====================================================================
    # the Dropper limitation is stated, not faked
    # =====================================================================
    select_trigger(DROP[0])
    check("a DROPPER trigger produces NO ordinary-wave preview", p.sim is None)
    check("...and says so plainly",
          p.error and "not previewed in this phase" in p.error)
    check("...and explains why, naming the engine behaviour",
          p.error and "dropper.asm" in p.error)
    check("...with the headline marking it unavailable rather than blank",
          p.headline.get() == "preview unavailable", p.headline.get())
    check("...and nothing is drawn as if it were a path",
          not p.canvas.find_withtag("path")
          and not p.canvas.find_withtag("marker"))
    check("...but the reason is shown on the canvas",
          len(p.canvas.find_withtag("why")) == 1)

    # =====================================================================
    # transport
    # =====================================================================
    select_trigger(RING[1])
    last = p._last()
    check("the frame count is the simulated one",
          last == p.sim.frame_count - 1, f"{last + 1} frames")

    p.step(1)
    p.step(1)
    check("stepping forward advances exactly one frame at a time",
          p.frame == 2, str(p.frame))
    p.step(-1)
    check("stepping back is exact, not re-integrated", p.frame == 1)
    at1 = {f.member: (f.x, f.y) for f in p.sim.at(1)}
    p.step(50)
    p.step(-50)
    check("...so a round trip returns the identical frame state",
          {f.member: (f.x, f.y) for f in p.sim.at(p.frame)} == at1
          and p.frame == 1)

    p.step(-99)
    check("stepping back past the start clamps at 0", p.frame == 0)
    for _ in range(3):
        p.step(10_000)
    check("stepping past the end clamps at the last frame", p.frame == last)

    p.scrub.set(last // 2)
    app.update()
    check("scrubbing selects a precomputed frame", p.frame == last // 2,
          str(p.frame))
    check("...and the frame readout follows",
          p.frame_text.get() == f"frame {p.frame} / {last}", p.frame_text.get())

    p.restart()
    check("restart returns to frame 0", p.frame == 0)

    check("play sets the playing state and relabels the button",
          (p.play(), p.playing and p.play_btn.cget("text") == "Pause")[1])
    app.update()
    check("pause clears it and cancels the pending frame job",
          (p.pause(), not p.playing and p._job is None
           and p.play_btn.cget("text") == "Play")[1])
    check("toggle_play flips it", (p.toggle_play(), p.playing)[1])
    p.toggle_play()
    check("...and back", not p.playing)

    # PLAYBACK REALLY ADVANCES FRAMES. after() callbacks only fire once real
    # time has passed and the event loop is pumped, so this waits for both
    # rather than spinning update() and concluding nothing happened.
    p.restart()
    p.speed.set("4x")
    p.play()
    deadline = time.time() + 3.0
    while p.frame == 0 and time.time() < deadline:
        app.update()
        time.sleep(0.01)
    advanced = p.frame
    p.pause()
    check("playing advances the frame", advanced > 0, f"reached frame {advanced}")
    check("the speed selector offers the documented rates",
          list(p.speed_box.cget("values")) == ["0.25x", "0.5x", "1x", "2x", "4x"])
    p.speed.set("1x")

    # =====================================================================
    # the paths toggle and the member selector
    # =====================================================================
    p.show_paths.set(False)
    p.redraw()
    check("turning paths off removes them", not p.canvas.find_withtag("path"))
    p.show_paths.set(True)
    p.redraw()
    check("...and turning them back on restores them",
          len(p.canvas.find_withtag("path")) > 0)

    check("the member selector lists every member",
          list(p.member_box.cget("values"))
          == [str(i) for i in range(p.sim.count)])
    p.scrub.set(1)
    app.update()
    p.member_box.set("1")
    p._member_picked()
    check("selecting a member shows its own diagnostics",
          "member 1" in p.diag.get() or "X " in p.diag.get(), p.diag.get())

    # =====================================================================
    # diagnostics report the authoritative state
    # =====================================================================
    p.member_box.set("0")
    p._member_picked()
    p.scrub.set(30)
    app.update()
    f0 = next(f for f in p.sim.at(30) if f.member == 0)
    check("the diagnostics show the simulator's own X/Y",
          f"X {f0.x}" in p.diag.get() and f"Y {f0.y}" in p.diag.get(),
          p.diag.get())
    check("...the stage index and kind",
          f"stage {f0.stage_index} {f0.stage_kind}" in p.diag.get())
    check("...the heading", f"heading {f0.heading}" in p.diag.get())
    check("...and a developer line with the sub-pixel state",
          f"sub-pixel {f0.acc_x}/{f0.acc_y}" in p.detail.get(), p.detail.get())
    check("no assembler address appears anywhere in the readout",
          "$" not in p.diag.get() and "$" not in p.detail.get())

    # =====================================================================
    # LIVE editing: the preview follows unsaved changes
    # =====================================================================
    check("the document is still clean after ALL of that preview use",
          not app._is_dirty())

    before_len = p.sim.frame_count
    wave_id = p.sim.wave_id
    wi = next(i for i, d in enumerate(app.controller.project.wave_definitions)
              if d.id == wave_id)
    w.tabs.select(1)
    w.wave_list.selection_clear(0, "end")
    w.wave_list.selection_set(wi)
    w._wave_selected()
    app.update()
    check("selecting the wave previews the same wave", p.sim.wave_id == wave_id)
    n_before = p.sim.count
    w.w_fields["count"].delete(0, "end")
    w.w_fields["count"].insert(0, str(n_before + 1))
    w._wave_apply()
    app.update()
    check("editing the member count re-simulates immediately",
          p.sim is not None and p.sim.count == n_before + 1,
          f"{n_before} -> {p.sim.count}")
    check("...and the edit itself IS dirty, as an authored edit should be",
          app._is_dirty())
    app._undo()
    app.update()
    check("undo restores the preview too", p.sim.count == n_before)

    # a movement-program edit must reach the preview as well
    prog_id = p.sim.program_id
    pi = next(i for i, x in enumerate(app.controller.project.movement_programs)
              if x.id == prog_id)
    w.tabs.select(2)
    w.prog_list.selection_clear(0, "end")
    w.prog_list.selection_set(pi)
    w._prog_selected()
    app.update()
    check("selecting a movement program previews it on its own",
          p.sim is not None and p.sim.program_id == prog_id, p.headline.get())
    check("...and says whose launch context it borrowed",
          "borrowed from wave" in p.headline.get()
          or "launch heading" in p.headline.get(), p.headline.get())
    before = [(f.x, f.y) for f in p.sim.paths[0]]
    w.sel_stage = 0
    w._refresh_stage_detail()
    st = app.controller.project.movement_programs[pi].stages[0]
    if st.kind in ("STRAIGHT", "HOLD"):
        w.s_fields["frames"].delete(0, "end")
        w.s_fields["frames"].insert(0, str(st.frames + 7))
    else:
        w.s_fields["steps"].delete(0, "end")
        w.s_fields["steps"].insert(0, str(st.steps + 3))
    w._stage_apply()
    app.update()
    after = [(f.x, f.y) for f in p.sim.paths[0]]
    check("editing a movement STAGE changes the previewed trajectory",
          after != before, f"{len(before)} -> {len(after)} frames")
    app._undo()
    app.update()
    check("...and undo puts the trajectory back",
          [(f.x, f.y) for f in p.sim.paths[0]] == before)
    check("the document is clean again", not app._is_dirty())

    # =====================================================================
    # invalid authored state fails gracefully
    # =====================================================================
    w.tabs.select(1)
    w.wave_list.selection_clear(0, "end")
    w.wave_list.selection_set(wi)
    w._wave_selected()
    app.update()
    w.w_fields["interval"].delete(0, "end")
    w.w_fields["interval"].insert(0, "0")
    w._wave_apply()
    app.update()
    check("an invalid interval does not crash the preview", p.sim is None)
    check("...it says concisely why it cannot simulate",
          p.error and "interval" in p.error, p.error)
    check("...and does NOT silently clamp it to something legal",
          app.controller.project.wave_definitions[wi].interval == 0)
    check("...while the validator reports it as an error too",
          not app.controller.validate().ok)
    app._undo()
    app.update()
    check("undo makes the preview work again", p.sim is not None)

    # a dangling movement-program reference
    w.w_prog.set("no such program")
    w._wave_apply()
    app.update()
    check("a dangling movement-program reference is refused, not guessed",
          p.sim is None and "does not exist" in (p.error or ""), p.error)
    app._undo()
    app.update()
    check("...and recovers on undo", p.sim is not None)

    # deleting the trigger under a trigger preview
    select_trigger(RING[0])
    check("back on a trigger preview", p.sim is not None)
    w._trigger_delete()
    app.update()
    check("deleting the previewed trigger does not crash the panel",
          w.winfo_exists() and p.winfo_exists())
    app._undo()
    app.update()
    check("...and undo brings it back", not app._is_dirty())

    # =====================================================================
    # the headline promise: previewing is read-only
    # =====================================================================
    state = app.controller.to_json()
    depth = len(app.undo_stack)
    select_trigger(RING[0])
    p.play()
    app.update()
    p.pause()
    p.step(5)
    p.scrub.set(40)
    app.update()
    p.restart()
    p.show_paths.set(False)
    p.redraw()
    p.show_paths.set(True)
    p.redraw()
    w.tabs.select(2)
    app.update()
    w.tabs.select(0)
    app.update()
    check("after playing, pausing, stepping, scrubbing, restarting, toggling "
          "and re-selecting, the project is byte-for-byte unchanged",
          app.controller.to_json() == state)
    check("...and not one undo step was pushed",
          len(app.undo_stack) == depth, f"{depth} -> {len(app.undo_stack)}")
    check("...and the document is not dirty", not app._is_dirty())

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
print(f"All {len(PASS)} preview GUI checks passed.")
