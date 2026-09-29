#!/usr/bin/env python3
"""The VISIBLE Encounter preview must fly a trigger at that trigger's speed.

WHY THIS FILE EXISTS, given tools/level_editor/test_trigger_speed.py already
has a section called "preview parity". That section called
`movement_sim.simulate_wave(..., speed=n)` directly and proved the simulator
scales correctly -- which it does, and always did. The bug was one layer above
it: PreviewPanel re-flies a wave only when its cache signature changes, and the
signature did not include the trigger's speed, so the path drawn on the canvas
was whatever had been flown first. Every assertion in that section passed while
the editor showed the wrong picture.

So this file drives the REAL PreviewPanel, through the REAL Encounter
workspace, by selecting triggers the way a user does, and reads the simulation
the canvas is actually drawn from (`panel.sim`). A duplicate helper cannot make
these assertions pass while the screen stays wrong.

THE DISCRIMINATING ASSERTION is not "the path changed". A preview that merely
ran the same loop faster -- constant radius, fewer frames -- would also change.
Runtime scales LINEAR VELOCITY and leaves the turn rate alone, so the loop gets
WIDER as well as shorter. The test requires both, because only the pair
distinguishes the intended behaviour from the plausible wrong one.

NEEDS A WORKING TK. Run it with an interpreter that has one:

    /usr/local/bin/python3 tools/level_editor/test_preview_trigger_speed.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract_v2 as C                                          # noqa: E402
import project_v6                                                # noqa: E402

HERE = Path(__file__).resolve().parent
CANON = HERE / "levels" / "level1" / "level.v6.json"
LIB = HERE / "encounter_library.v6.json"
CANON_BYTES = CANON.read_bytes()
LIB_BYTES = LIB.read_bytes()

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


try:
    import tkinter as tk
    _r = tk.Tk()
    _r.destroy()
except Exception as exc:                                        # noqa: BLE001
    print(f"SKIP- this test needs a working Tk ({exc})")
    sys.exit(0)

import editor as ed                                              # noqa: E402
ed.messagebox.showerror = lambda *a, **k: None
ed.messagebox.showinfo = lambda *a, **k: None
ed.messagebox.askyesno = lambda *a, **k: True
import encounters_ui                                             # noqa: E402
encounters_ui.messagebox.showerror = lambda *a, **k: None

app = ed.LevelEditor(ed.find_repo_root())
app.withdraw()                          # NEVER STEAL FOCUS
app._open_encounters()
w = app._encounters
w.withdraw()
app.update()
panel = w.preview


def select(i):
    """Select a trigger THROUGH THE TREE, as a user does.

    Assigning w.sel_trigger directly does not survive the next app.update():
    a pending <<TreeviewSelect>> re-derives it and overwrites the assignment.
    """
    w.trig_tree.selection_set(str(i))
    w._trigger_selected()
    app.update()


def geometry(i, speed):
    """Set trigger i to `speed`, select it, and measure THE DRAWN path.

    Reads panel.sim -- the very object _draw_paths iterates -- so nothing here
    can agree with itself while the canvas disagrees.
    """
    w.controller.update_trigger(i, speed=speed)
    select(i)
    if panel.sim is None:
        return None
    path = panel.sim.paths[0]
    xs = [s.x for s in path]
    ys = [s.y for s in path]
    return {"frames": len(path),
            "width": max(xs) - min(xs),
            "height": max(ys) - min(ys),
            "start": (path[0].x, path[0].y),
            "first_step": (path[1].x - path[0].x, path[1].y - path[0].y)
            if len(path) > 1 else (0, 0)}


try:
    # =====================================================================
    # THE SPECIMEN IS BUILT, NOT BORROWED FROM THE AUTHORED LEVEL
    # =====================================================================
    # The first version hunted the level for two ordinary triggers sharing one
    # wave definition. That worked, and then it did not: the shared definition it
    # found was `linger`, whose program loiters -- STRAIGHT, then a HOLD drifting
    # at (0, 1), then an arc. Scaling a hold that slow does almost nothing to the
    # geometry, and the widths came out 70, 51, 44, 53, 66 across the five
    # speeds. Seven checks failed, and the preview was drawing exactly what the
    # runtime would fly. The premise "the loop gets steadily wider" is true of a
    # program whose arc follows a brisk straight leg, and that is a property of
    # the PROGRAM, not of the engine.
    #
    # So the program, the wave and the two triggers are this file's own, added to
    # the project IN MEMORY. The panel reads the live project, so the real
    # PreviewPanel still flies them through the real workspace -- which is the
    # whole point of this file -- and the byte comparison at the end proves
    # nothing was saved.
    proj = w.controller.project
    SPEC_PROG, SPEC_WAVE = "_spec_prog", "_spec_wave"
    proj.movement_programs.append(project_v6.MovementProgram(SPEC_PROG, [
        # EAST, THEN A QUARTER TURN TO SOUTH, THEN OUT THROUGH THE BOTTOM.
        #
        # The shape is chosen so the measurement means what it says:
        #
        #   the straight leg runs EAST, so all of it counts toward the WIDTH and
        #   its length scales exactly with the speed;
        #   the arc is a QUARTER turn, whose horizontal extent is its radius --
        #   and the radius is WM_ARC_SPEED x framesPerStep x headings / 8pi, so
        #   it scales with the speed while the turn RATE does not;
        #   the arc ends pointing SOUTH so the EXIT leaves through the BOTTOM.
        #
        # That last detail is not decoration. A first attempt turned a full
        # circle and exited EAST, so the width was dominated by the run to the
        # right border -- the same distance at every speed -- and the widening
        # vanished into it. A second turned too far and left the aperture before
        # the arc closed, truncating the 2.00x path so it came out NARROWER (78
        # against 93) while the engine was behaving perfectly. The geometry below
        # stays inside the 320x200 field at 2.00x with room to spare.
        project_v6.MovementStage("STRAIGHT", frames=20, vx=6, vy=0),
        project_v6.MovementStage("ARC", steps=16, frames_per_step=2,
                                 entry_heading=0),
        project_v6.MovementStage("EXIT"),
    ]))
    proj.wave_definitions.append(project_v6.WaveDefinition(
        id=SPEC_WAVE, count=2, interval=16, start_x=40, start_y=40,
        x_step=20, y_step=0, heading=0, movement_program=SPEC_PROG))
    ordinary = next(t.species for t in proj.triggers if t.species != "DROPPER")
    rows = sorted(t.world_progress for t in proj.triggers)
    proj.triggers.append(project_v6.Trigger(
        world_progress=min(rows[-1] + 10, proj.stage.no_spawn_row - 2),
        wave_definition=SPEC_WAVE, species=ordinary, fire_mask=[],
        dropper_side="LEFT"))
    proj.triggers.append(project_v6.Trigger(
        world_progress=min(rows[-1] + 20, proj.stage.no_spawn_row - 1),
        wave_definition=SPEC_WAVE, species=ordinary, fire_mask=[],
        dropper_side="LEFT"))
    w._refresh_triggers()
    app.update()
    trigs = proj.triggers
    A, B = len(trigs) - 2, len(trigs) - 1
    defn = SPEC_WAVE
    check(f"two ordinary triggers share the definition {defn!r}",
          trigs[A].wave_definition == trigs[B].wave_definition == defn
          and trigs[A].species != "DROPPER" and trigs[B].species != "DROPPER",
          f"rows {trigs[A].world_progress} and {trigs[B].world_progress}, "
          f"species {trigs[A].species}")

    prog = next(p for p in proj.movement_programs
                if p.id == next(d for d in proj.wave_definitions
                                if d.id == defn).movement_program)
    turning = [s for s in prog.stages if s.kind in C.ARC_KINDS]
    check(f"...and its program {prog.id!r} actually turns",
          bool(turning),
          f"{len(turning)} arc stage(s), "
          f"{sum(s.steps for s in turning)} heading steps")
    check("...after a straight leg brisk enough for the arc's radius to show",
          any(s.kind == "STRAIGHT" and max(abs(s.vx), abs(s.vy)) >= 4
              for s in prog.stages),
          "; ".join(f"{s.kind}({s.vx},{s.vy})" for s in prog.stages
                    if s.kind in ("STRAIGHT", "HOLD")))

    # =====================================================================
    # THE REGRESSION: geometry must change with speed
    # =====================================================================
    print("\n=== the drawn path, per speed ===")
    g = {}
    for n in C.SPEED_CHOICES:
        g[n] = geometry(A, n)
        check(f"{C.SPEED_LABELS[n]}: the preview produced a path",
              g[n] is not None)
        if g[n]:
            print(f"       {C.SPEED_LABELS[n]}: {g[n]['frames']:>4} frames, "
                  f"width {g[n]['width']:>4}, height {g[n]['height']:>4}")

    base, top = g[C.TRIG_SPEED_1X], g[max(C.SPEED_CHOICES)]

    # THE BUG ITSELF. Before the fix every one of these was identical.
    check("2.00x DRAWS A DIFFERENT PATH FROM 1.00x -- the bug this test exists "
          "for", (base["width"], base["frames"]) != (top["width"], top["frames"]),
          f"1.00x w={base['width']} f={base['frames']}, "
          f"2.00x w={top['width']} f={top['frames']}")

    check("the loop is WIDER at 2.00x, not merely faster",
          top["width"] > base["width"] * 1.6,
          f"{base['width']} -> {top['width']} "
          f"({top['width'] / base['width']:.2f}x)")
    check("...and about twice as wide, as linear scaling with an unchanged "
          "turn rate implies",
          1.8 <= top["width"] / base["width"] <= 2.2,
          f"{top['width'] / base['width']:.2f}x")

    # THE DISCRIMINATOR. A constant-radius loop run faster would take fewer
    # frames and keep its width; this must do BOTH.
    check("2.00x also COMPLETES SOONER -- linear speed, same angular rate",
          top["frames"] < base["frames"],
          f"{base['frames']} -> {top['frames']} frames")
    check("...so it is NOT a time-compressed constant-radius loop",
          top["frames"] < base["frames"] and top["width"] > base["width"] * 1.6,
          "fewer frames AND a wider arc: both, which only linear scaling gives")

    check("1.50x is visibly intermediate",
          base["width"] < g[6]["width"] < top["width"],
          f"{base['width']} < {g[6]['width']} < {top['width']}")
    widths = [g[n]["width"] for n in C.SPEED_CHOICES]
    check("all five speeds widen monotonically",
          all(a <= b for a, b in zip(widths, widths[1:])),
          "; ".join(f"{C.SPEED_LABELS[n]}={g[n]['width']}"
                    for n in C.SPEED_CHOICES))
    frames = [g[n]["frames"] for n in C.SPEED_CHOICES]
    check("...and complete monotonically sooner",
          all(a >= b for a, b in zip(frames, frames[1:])),
          "; ".join(f"{C.SPEED_LABELS[n]}={g[n]['frames']}"
                    for n in C.SPEED_CHOICES))

    # =====================================================================
    # what must NOT have changed
    # =====================================================================
    print("\n=== what speed must leave alone ===")
    check("every speed starts the member at the SAME authored position",
          len({g[n]["start"] for n in C.SPEED_CHOICES}) == 1,
          str(base["start"]))
    # THE INITIAL HEADING, read off the first step rather than trusted: the
    # direction of travel must be the same at every speed, only its magnitude
    # differs. Compared as a ratio because the components themselves scale.
    def bearing(step):
        dx, dy = step
        return (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)

    check("...and travelling in the SAME initial direction",
          len({bearing(g[n]["first_step"]) for n in C.SPEED_CHOICES}) == 1,
          "; ".join(f"{C.SPEED_LABELS[n]}={g[n]['first_step']}"
                    for n in C.SPEED_CHOICES))
    check("the shared wave definition still has no speed of its own",
          not hasattr(next(d for d in w.controller.project.wave_definitions
                           if d.id == defn), "speed"))

    # =====================================================================
    # two triggers, one definition, two previews
    # =====================================================================
    print("\n=== the same definition, two triggers, two previews ===")
    w.controller.update_trigger(A, speed=C.TRIG_SPEED_1X)
    w.controller.update_trigger(B, speed=max(C.SPEED_CHOICES))
    ga = geometry(A, C.TRIG_SPEED_1X)
    gb = geometry(B, max(C.SPEED_CHOICES))
    check("selecting trigger A previews its own 1.00x geometry",
          ga["width"] == base["width"], f"width {ga['width']}")
    check("SELECTING TRIGGER B PREVIEWS A WIDER PATH, from the SAME definition",
          gb["width"] > ga["width"] * 1.6,
          f"A {ga['width']} vs B {gb['width']}")
    # SWITCHING BACK is the case the cache got wrong, so it is asserted in
    # both directions rather than once.
    again = geometry(A, C.TRIG_SPEED_1X)
    check("...and switching back to A returns to A's geometry",
          again["width"] == ga["width"], f"{again['width']}")
    check("...with one shared wave definition throughout",
          len([d for d in w.controller.project.wave_definitions
               if d.id == defn]) == 1)

    # =====================================================================
    # the workspace is still usable
    # =====================================================================
    print("\n=== the workspace still works ===")
    for tab in range(3):
        w.tabs.select(tab)
        app.update()
    check("all three tabs still select cleanly", True)
    check("the wave-definition pane still populates", bool(w.wave_list.size()))
    check("the movement-program pane still populates", bool(w.prog_list.size()))
    w.destroy()
    app.update()
    app._open_encounters()
    w2 = app._encounters
    w2.withdraw()
    app.update()
    check("the Encounter window closes and reopens without a traceback",
          w2.winfo_exists() and hasattr(w2, "preview"))
    w2.destroy()
    app.update()
finally:
    try:
        app.destroy()
    except Exception:                                           # noqa: BLE001
        pass

print("\n=== the committed sources are untouched ===")
check("the canonical level 1 document is byte-identical",
      CANON.read_bytes() == CANON_BYTES)
check("the shared encounter library is byte-identical",
      LIB.read_bytes() == LIB_BYTES)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for m in FAIL:
    print(f"  FAILED: {m}")
sys.exit(1 if FAIL else 0)
