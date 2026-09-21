#!/usr/bin/env python3
"""Phase 6B, widget layer: authoring movement as segments, against real Tk.

The compiler and the transforms are proved headlessly in
test_movement_semantic.py, and the trajectories they produce are proved
against a real 6502 by the Phase 6A suites. What can only be proved with
widgets is that the editor is WIRED to them: that a program can be built as a
sentence without touching a heading, that the raw records stay reachable, that
cost is on screen before it is paid, and that none of it disturbs a project
the author did not edit.

NOTHING HERE WRITES TO THE CANONICAL PROJECT. Every destructive case runs
against the in-memory document and is undone, or against a temporary copy.

Run with an interpreter that has a working Tk (see the Phase 5A report):
    /usr/local/bin/python3 test_semantic_gui.py
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
import movement_semantic as sem                                 # noqa: E402

ed.messagebox.showerror = lambda *a, **k: None
ed.messagebox.showinfo = lambda *a, **k: None
_ANSWER = {"yes": True, "str": None}
ed.messagebox.askyesno = lambda *a, **k: _ANSWER["yes"]
ed.simpledialog.askstring = lambda *a, **k: _ANSWER["str"]
import encounters_ui                                            # noqa: E402
encounters_ui.messagebox.showerror = lambda *a, **k: None
encounters_ui.messagebox.showinfo = lambda *a, **k: None
encounters_ui.messagebox.askyesno = lambda *a, **k: _ANSWER["yes"]
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

CANON_JSON = app.controller.to_json()


def progs():
    return app.controller.project.movement_programs


def pick(index):
    w.tabs.select(2)
    w.prog_list.selection_clear(0, "end")
    w.prog_list.selection_set(index)
    w._prog_selected()
    app.update()


def shown(widget):
    """Whether a widget is currently gridded.

    NOT winfo_ismapped(): these windows are withdrawn so nothing is ever
    mapped, and grid_remove() is what the editor actually uses to choose a
    view. An empty grid_info() is a removed widget.
    """
    return bool(widget.grid_info())


def seg_rows():
    return [w.seg_tree.item(i, "values") for i in w.seg_tree.get_children()]


try:
    # =====================================================================
    # 1. a raw program is raw, says so, and keeps its records
    # =====================================================================
    pick(0)
    check("a project authored before Phase 6B opens with RAW programs",
          not progs()[0].is_semantic
          and "raw engine records" in w.prog_mode_text.get(),
          w.prog_mode_text.get())
    check("...its pool cost is on screen without converting anything",
          "engine records" in w.prog_cost_text.get()
          and "project pool" in w.prog_cost_text.get(), w.prog_cost_text.get())
    check("...the raw record editor is the view it gets",
          shown(w.raw_view) and not shown(w.sem_view))
    check("...Mirror and the raw toggle are offered only for semantic programs",
          "disabled" in w.prog_mirror_btn.state()
          and "disabled" in w.prog_raw_btn.state())
    check("merely looking at a program does not dirty the document",
          not app._is_dirty())

    # =====================================================================
    # 2. converting is opt-in, previewed, and path-preserving
    # =====================================================================
    before_stages = [s.to_dict() for s in progs()[0].stages]
    segs, why, same_bytes = app.controller.preview_make_semantic(0)
    check("the editor can say in advance what a conversion would produce",
          [s.describe() for s in segs]
          == ["STRAIGHT Continue 34f", "QUARTER RIGHT", "EXIT"],
          str([s.describe() for s in segs]))
    check("...and that it changes the compiled bytes, not the flight",
          not same_bytes)
    depth = len(app.undo_stack)
    w._prog_make_semantic()
    app.update()
    check("converting makes the program semantic", progs()[0].is_semantic)
    check("...as exactly one undo step", len(app.undo_stack) == depth + 1)
    check("...and the records still fly the identical path",
          sem.trajectories_match(
              [ed.project_v6.MovementStage.from_dict(d, "p")
               for d in before_stages], progs()[0].stages, 0))

    rows = seg_rows()
    check("the program now reads as a sentence",
          [r[1] for r in rows]
          == ["STRAIGHT Continue 34f", "QUARTER RIGHT", "EXIT"],
          str([r[1] for r in rows]))
    check("...and every row states the state it INHERITS, as a readout",
          "heading 0" in rows[0][2] and "to heading 16" in rows[1][2],
          str(rows[1][2]))
    check("the cost line shows segments AND the records they expand to",
          "→" in w.prog_cost_text.get(), w.prog_cost_text.get())

    # =====================================================================
    # 3. the author never meets a heading index
    # =====================================================================
    w.seg_tree.selection_set("1")
    w._seg_selected()
    app.update()
    check("a turn offers direction, angle and radius",
          w.g_dir.get() == "RIGHT" and "Quarter turn" in w.g_angle.get()
          and w.g_radius.get() == "normal",
          f"{w.g_dir.get()} | {w.g_angle.get()} | {w.g_radius.get()}")
    check("...and the named pieces are the first choices offered",
          [c.split(" (")[0] for c in w.g_angle.cget("values")][:3]
          == ["Quarter turn", "Half turn", "Full loop"],
          str(w.g_angle.cget("values")[:3]))
    check("...with a free radius",
          list(w.g_radius.cget("values"))[:3] == ["tight", "normal", "wide"])
    check("NO entry heading control appears in the semantic view",
          not any("heading" in str(ch.cget("text")).lower()
                  for ch in w.g_turn.winfo_children()
                  if ch.winfo_class() == "TLabel" and "5.625" not in str(ch.cget("text"))))
    w.seg_tree.selection_set("0")
    w._seg_selected()
    app.update()
    check("a straight offers only a duration",
          shown(w.g_straight) and not shown(w.g_turn))

    # =====================================================================
    # 4. building a path: the brief's own sentence
    # =====================================================================
    _ANSWER["str"] = "demo6b"
    j = app.controller.add_movement_program("demo6b")
    app.controller.start_semantic(j)
    app._push_undo(app._project_state())
    w.refresh()
    pick(j)
    check("a new program starts as segments that already fly",
          progs()[j].is_semantic and len(progs()[j].segments) == 2)
    w.sel_segment = 0
    w._seg_add("after")
    app.update()
    w.sel_segment = 1
    w.g_kind.set("TURN")
    w._seg_kind_changed()
    app.update()
    w.sel_segment = 1
    w._seg_selected()
    w.g_angle.set("Quarter turn (90°)")
    w._seg_angle_changed()
    app.update()
    w.sel_segment = 1
    w._seg_add("after")
    app.update()
    built = [s.describe() for s in progs()[j].segments]
    check("a path can be built entirely from the semantic controls",
          built == ["STRAIGHT Continue 30f", "QUARTER RIGHT",
                    "STRAIGHT Continue 30f", "EXIT"],
          str(built))
    check("...and the compiled straight AFTER the turn gets the turned "
          "heading's velocity, which the author never supplied",
          (progs()[j].stages[2].vx, progs()[j].stages[2].vy) == (0, 6),
          str(progs()[j].stages[2].to_dict()))
    check("...and every compiled arc continues rather than naming a heading",
          all(s.entry_heading == "CONT" for s in progs()[j].stages
              if s.kind in ("ARC", "ARC_MIRROR")))

    # =====================================================================
    # 5. macros expand where the cost is visible
    # =====================================================================
    n_before = len(progs()[j].segments)
    r_before = len(progs()[j].stages)
    w.macro_box.set("Zigzag right")
    w.sel_segment = 0
    w._macro_insert()
    app.update()
    check("inserting a manoeuvre expands it into ordinary segments",
          all(s.kind in sem.KINDS for s in progs()[j].segments)
          and len(progs()[j].segments) == n_before + 5,
          f"{n_before} -> {len(progs()[j].segments)}")
    check("...and the record cost it just spent is on screen",
          f"{len(progs()[j].stages)} engine records" in w.prog_cost_text.get(),
          w.prog_cost_text.get())
    check("...which is more than it was", len(progs()[j].stages) > r_before)
    app._undo()
    app.update()
    check("a macro insertion is one undo step",
          len(progs()[j].segments) == n_before)

    # =====================================================================
    # 6. mirroring, and the launch state it does NOT touch
    # =====================================================================
    dirs_before = [s.direction for s in progs()[j].segments if s.kind == "TURN"]
    waves_before = [d.to_dict() for d in app.controller.project.wave_definitions]
    w._prog_mirror()
    app.update()
    dirs_after = [s.direction for s in progs()[j].segments if s.kind == "TURN"]
    check("Mirror movement flips every turn",
          all(a != b for a, b in zip(dirs_before, dirs_after)) and dirs_before,
          f"{dirs_before} -> {dirs_after}")
    check("...and does NOT silently rewrite any wave definition's launch state",
          [d.to_dict() for d in app.controller.project.wave_definitions]
          == waves_before)
    w._prog_mirror()
    app.update()
    check("...and mirroring twice returns the original",
          [s.direction for s in progs()[j].segments if s.kind == "TURN"]
          == dirs_before)

    # =====================================================================
    # 7. the raw view stays reachable
    # =====================================================================
    pick(0)
    w._prog_toggle_raw()
    app.update()
    check("a semantic program's four-byte records can still be inspected",
          w.show_raw and shown(w.raw_view)
          and len(w.stage_tree.get_children()) == len(progs()[0].stages))
    check("...and the raw view shows the CONT the compiler emitted",
          any("CONT" in str(w.stage_tree.item(i, "values"))
              for i in w.stage_tree.get_children()))
    clean = app._is_dirty()
    w._prog_toggle_raw()
    app.update()
    check("switching view is a view, not an edit",
          not w.show_raw and app._is_dirty() == clean)

    # =====================================================================
    # 8. live preview follows unsaved semantic edits
    # =====================================================================
    pick(j)
    check("selecting a semantic program previews it", w.preview.sim is not None)
    path_before = [(f.x, f.y) for f in w.preview.sim.paths[0]]
    w.sel_segment = 0
    w._seg_selected()
    encounters_ui._put(w.g_fields["frames"], 60)
    w._seg_apply()
    app.update()
    check("editing a segment re-simulates the preview immediately",
          [(f.x, f.y) for f in w.preview.sim.paths[0]] != path_before)
    app._undo()
    app.update()
    check("...and undo restores the previewed path",
          [(f.x, f.y) for f in w.preview.sim.paths[0]] == path_before)

    # =====================================================================
    # 9. a bad edit is refused, and refusing leaves the program intact
    # =====================================================================
    pick(j)
    good = [s.to_dict() for s in progs()[j].segments]
    good_stages = [s.to_dict() for s in progs()[j].stages]
    w.sel_segment = 0
    w._seg_selected()
    w.g_kind.set("HOLD")
    w._seg_kind_changed()
    app.update()
    # a HOLD with no drift immediately before EXIT cannot compile; the
    # controller must refuse and leave both halves consistent
    for i in range(len(progs()[j].segments) - 1, 0, -1):
        if progs()[j].segments[i].kind != "EXIT":
            w.sel_segment = i
            w._seg_delete()
            app.update()
    # PHASE 6B.1 CHANGED THIS DELIBERATELY. An edit that leaves the program
    # incomplete is now ACCEPTED as a draft -- refusing it made progressive
    # authoring impossible -- so segments and stages legitimately differ in
    # length. The invariant that replaces "all or nothing" is that the stored
    # records are always exactly the compiled prefix of the segments, so the
    # two can never disagree about what they do describe.
    _d = app.controller.program_draft(j)
    check("a draft's stored records are exactly the compiled prefix of its "
          "segments",
          [x.to_dict() for x in progs()[j].stages]
          == [x.to_dict() for x in _d.authored_stages],
          f"{len(progs()[j].segments)} segments, {len(progs()[j].stages)} stages")
    check("...and an unfinished draft cannot be saved",
          not app.controller.validate().ok)
    while app.undo_stack and progs()[j].segments != [
            sem.Segment.from_dict(d, "p") for d in good]:
        app._undo()
    app.update()
    check("...and undo gets back to the working program",
          [s.to_dict() for s in progs()[j].segments] == good
          and [s.to_dict() for s in progs()[j].stages] == good_stages)

    # =====================================================================
    # 9b. the preview launch heading — authoring context, not project data
    # =====================================================================
    pick(j)
    p = w.preview
    check("the preview-heading control appears for a movement program",
          bool(p.launch_row.winfo_manager()))
    check("...offering the eight compass points, plus deferring to the wave",
          list(p.launch_box.cget("values"))
          == ["from wave"] + [n for n, _h in sem.COMPASS],
          str(p.launch_box.cget("values")))
    check("...and defaulting to the wave's own heading rather than overriding it",
          p.launch_box.get() == "from wave" and p.preview_heading is None)
    check("the header names the heading in words, not a bare number",
          "preview heading: Right (0)" in p.headline.get(), p.headline.get())

    asset_before = [s.to_dict() for s in progs()[j].segments]
    stages_before = [s.to_dict() for s in progs()[j].stages]
    json_before = app.controller.to_json()
    dirty_before, undo_before = app._is_dirty(), len(app.undo_stack)
    right_path = [(f.x, f.y) for f in p.sim.paths[0]]

    p.launch_box.set("Down")
    p._launch_picked()
    app.update()
    check("choosing Down re-previews immediately",
          [(f.x, f.y) for f in p.sim.paths[0]] != right_path)
    check("...and says so in words", "preview heading: Down (16)" in p.headline.get(),
          p.headline.get())
    check("...flying the SAME segments from the new entry state",
          [s.to_dict() for s in progs()[j].segments] == asset_before)
    check("THE ASSET IS UNTOUCHED: segments, compiled records, document and "
          "undo stack all unchanged",
          [s.to_dict() for s in progs()[j].stages] == stages_before
          and app.controller.to_json() == json_before
          and app._is_dirty() == dirty_before
          and len(app.undo_stack) == undo_before)
    p.launch_box.set("from wave")
    p._launch_picked()
    app.update()
    check("...and going back to 'from wave' restores the original preview",
          [(f.x, f.y) for f in p.sim.paths[0]] == right_path)

    w.tabs.select(0)
    app.update()
    check("the control is hidden where a real launch heading already exists "
          "(a trigger carries its wave's)",
          not p.launch_row.winfo_manager())

    # =====================================================================
    # 9c. compass terminology on the wave definition
    # =====================================================================
    w.tabs.select(1)
    w.wave_list.selection_clear(0, "end")
    w.wave_list.selection_set(0)
    w._wave_selected()
    app.update()
    d0 = app.controller.project.wave_definitions[0]
    check("a wave definition names its launch heading in compass terms",
          sem.heading_label(d0.heading) in w.w_head_text.get(),
          w.w_head_text.get())
    check("...and the dial shows that heading",
          w.w_compass.heading == d0.heading,
          f"dial {w.w_compass.heading}, wave {d0.heading}")
    off = [i for i, d in enumerate(app.controller.project.wave_definitions)
           if d.heading not in sem.HEADING_COMPASS]
    if off:
        w.wave_list.selection_clear(0, "end")
        w.wave_list.selection_set(off[0])
        w._wave_selected()
        app.update()
        h = app.controller.project.wave_definitions[off[0]].heading
        check(f"...and an off-point heading ({h}) keeps its EXACT value, placed "
              f"between the two points it lies between",
              str(h) in w.w_head_text.get() and "between" in w.w_head_text.get()
              and w.w_fields["heading"].get() == str(h),
              w.w_head_text.get())
    idx = off[0] if off else 0
    w.wave_list.selection_clear(0, "end")
    w.wave_list.selection_set(idx)
    w._wave_selected()
    app.update()
    was = app.controller.project.wave_definitions[idx].heading
    depth = len(app.undo_stack)
    # The launch direction now uses the same draggable dial as an explicit
    # STRAIGHT direction, so this drags it rather than picking from a list.
    w.w_compass.set_heading(sem.COMPASS_HEADING["Down"], notify=True)
    app.update()
    check("choosing a compass point on a wave sets the exact engine heading",
          app.controller.project.wave_definitions[idx].heading == 16,
          str(app.controller.project.wave_definitions[idx].heading))
    check("...as one undoable edit -- a wave's heading IS project data, unlike "
          "the preview's",
          len(app.undo_stack) == depth + 1)
    app._undo()
    app.update()
    check("...and undo restores it",
          app.controller.project.wave_definitions[idx].heading == was)

    # =====================================================================
    # 10. persistence, and the canonical project untouched
    # =====================================================================
    with tempfile.TemporaryDirectory() as d:
        tgt = Path(d) / "demo.v6.json"
        ed.filedialog.asksaveasfilename = lambda *a, **k: str(tgt)
        app._save_project_as()
        ed.filedialog.askopenfilename = lambda *a, **k: str(tgt)
        app._open_level()
        app.update()
        reopened = [p.id for p in progs() if p.is_semantic]
        check("semantic programs survive save and reopen",
              "demo6b" in reopened and "sweep" in reopened, str(reopened))
        w.tabs.select(2)
        w.prog_list.selection_clear(0, "end")
        w.prog_list.selection_set([p.id for p in progs()].index("demo6b"))
        w._prog_selected()
        app.update()
        check("...and the reopened program still reads as the same sentence",
              [r[1] for r in seg_rows()]
              == [s.describe() for s in progs()[
                  [p.id for p in progs()].index("demo6b")].segments])
        check("...with the preview working on it", w.preview.sim is not None)

    # the canonical document was reopened over; reload it and check it is intact
    ed.filedialog.askopenfilename = lambda *a, **k: str(
        Path(ed.__file__).parent / "levels/level1/level.v6.json")
    app._open_level()
    app.update()
    check("the canonical project on disk is untouched by all of the above",
          app.controller.to_json() == CANON_JSON)
    check("...and its programs are all still RAW",
          not any(p.is_semantic for p in progs()))
    check("...and the document is clean", not app._is_dirty())

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
print(f"All {len(PASS)} semantic-movement GUI checks passed.")
