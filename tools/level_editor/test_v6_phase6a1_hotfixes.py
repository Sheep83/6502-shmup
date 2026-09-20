#!/usr/bin/env python3
"""Phase 6A.1: the hotfixes that came out of the first real authoring session.

Each section guards one thing that actually went wrong while a level was being
built, and each names the cause rather than the symptom:

  1. selecting a DROPPER trigger widened the encounter workspace until the
     controls were off-screen -- one label without a wraplength;
  2. the top-most turret could not be deleted -- `selected_turret or -1` turned
     index 0 into -1, and index 0 is always the top-most turret;
  3. a wave definition named "loop x 5" passed the editor and was refused by the
     exporter -- the assembler-symbol rule was not part of validation;
  4. Export leaked ExportRefused as a Tk traceback, and could in principle have
     half-written a package;
  5. a spawn inside the playfield reached KickAssembler -- the validator did not
     carry src/waves.asm's hidden-left/right/above rule;
  6. Save warned about a vertical wrap seam on a stage that has a real end;
  7. consecutive same-species triggers were rejected on the strength of an
     assembly-time assertion that was about content, not safety.

NOTHING HERE TOUCHES THE CANONICAL PROJECT. Every destructive case works on a
copy loaded into memory or written to a temporary directory.

Run with an interpreter that has Tk:  python3 test_v6_phase6a1_hotfixes.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                              # noqa: E402
import export_v6                                                     # noqa: E402
from project_v6 import ProjectV6, Trigger                            # noqa: E402
from validation_v6 import validate                                   # noqa: E402

CANON = HERE / "levels" / "level1" / "level.v6.json"
PASS, FAIL = [], []


def ok(m, x=""):
    PASS.append(m)
    print(f"ok  - {m}" + (f"  [{x}]" if x else ""))


def check(m, c, x=""):
    (ok if c else _fail)(m, x)


def _fail(m, x=""):
    FAIL.append(m)
    print(f"FAIL- {m}" + (f"  [{x}]" if x else ""))


def codes(p):
    return [i.code for i in validate(p).errors]


def fresh():
    return ProjectV6.load(CANON)


# ===========================================================================
print("=== 3 + 5. validation catches what only the exporter used to ===")
# ---------------------------------------------------------------------------
p = fresh()
p.wave_definitions[0].id = "loop x 5"
check("a wave id with spaces is a VALIDATION error, not an export surprise",
      "wavedef.bad_id" in codes(p))
for bad in ("5loop", "Loop", "loop-x5", "", "loop.x5"):
    q = fresh()
    q.movement_programs[0].id = bad
    check(f"movement program id {bad!r} is rejected",
          any(c.endswith("bad_id") or c.endswith("no_id") for c in codes(q)))
for good in ("loop_x5", "sweep_right", "dive2", "a"):
    q = fresh()
    old = q.wave_definitions[0].id
    q.wave_definitions[0].id = good
    for t in q.triggers:
        if t.wave_definition == old:
            t.wave_definition = good
    check(f"wave id {good!r} is accepted",
          not [c for c in codes(q) if c.endswith("bad_id")])

# ---- the engine's own spawn rule, at its exact boundaries -----------------
# src/waves.asm: hiddenAbove = y+SPRITE_HEIGHT-1 < APERTURE_TOP_RASTER
#                hiddenLeft  = x+23 < 24 ;  hiddenRight = x > 343
TOP = C.APERTURE_TOP_RASTER - C.SPRITE_HEIGHT        # 34: last hidden y
for x, y, legal, why in (
        (0, 64, True, "hidden behind the left border"),
        (1, 64, False, "one pixel of the sprite is visible"),
        (C.DISPLAY_X_LAST, 64, False, "the last visible column"),
        (C.DISPLAY_X_LAST + 1, 64, True, "clear of the right edge"),
        (90, TOP, True, "the last fully hidden row above the aperture"),
        (90, TOP + 1, False, "one raster into the aperture"),
):
    q = fresh()
    q.wave_definitions[0].start_x, q.wave_definitions[0].start_y = x, y
    q.wave_definitions[0].x_step = q.wave_definitions[0].y_step = 0
    bad = "wavedef.spawn_visible" in codes(q)
    check(f"spawn ({x},{y}) {'accepted' if legal else 'rejected'}: {why}",
          bad != legal)
ok("the boundaries match src/waves.asm exactly: x 343/344, y 34/35")

# a LATER member walked into view by xStep is caught too
q = fresh()
q.wave_definitions[0].start_x, q.wave_definitions[0].start_y = 0, 64
q.wave_definitions[0].x_step, q.wave_definitions[0].count = 40, 4
check("a member that xStep walks into the playfield is caught",
      "wavedef.spawn_visible" in codes(q))
msg = [str(i) for i in validate(q).errors if i.code == "wavedef.spawn_visible"][0]
check("...and the message names the wave, the member and the coordinate",
      "member" in msg and "spawns at" in msg, msg[:80])

# ===========================================================================
print("\n=== 4. export refuses without touching the destination ===")
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    export_v6.export_level(fresh(), d, level_name="level1",
                           carry_enemies_from=REPO / "src" / "level1")
    good = {f.name: f.read_bytes() for f in sorted(d.glob("*.asm"))}
    check("a good export writes the whole package", len(good) >= 6, str(len(good)))
    for label, mutate in (
            ("a bad wave id", lambda q: setattr(q.wave_definitions[0], "id", "loop x 5")),
            ("a dangling program", lambda q: setattr(q.wave_definitions[0],
                                                     "movement_program", "nope")),
            ("a trigger at noSpawnRow", lambda q: setattr(
                q.triggers[0], "world_progress", q.stage.no_spawn_row)),
            ("a spawn inside the playfield", lambda q: (
                setattr(q.wave_definitions[0], "start_x", 200),
                setattr(q.wave_definitions[0], "start_y", 64))),
    ):
        q = fresh()
        mutate(q)
        try:
            export_v6.export_level(q, d, level_name="level1")
            _fail(f"{label} was NOT refused")
        except export_v6.ExportRefused:
            after = {f.name: f.read_bytes() for f in sorted(d.glob("*.asm"))}
            check(f"{label} is refused and the package is untouched",
                  after == good and not list(d.glob("*.tmp")))

# ===========================================================================
print("\n=== 6. the vertical-wrap seam warning is gone ===")
# ---------------------------------------------------------------------------
import project as legacy                                             # noqa: E402
check("wrap_seam_warning is retired and always returns None",
      legacy.wrap_seam_warning(None) is None)
ed_src = (HERE / "editor.py").read_text(encoding="utf-8")
check("the save path no longer calls it",
      "wrap_seam_warning" not in ed_src)
# a project whose first and last rows differ wildly still validates and exports
q = fresh()
q.map_rows[0] = [0] * 10
q.map_rows[-1] = [min(len(q.metatile_defs) - 1, 7)] * 10
check("a level whose first and last rows differ validates clean",
      validate(q).ok, str(codes(q)))
with tempfile.TemporaryDirectory() as td:
    export_v6.export_level(q, td, level_name="level1")
    ok("...and exports without a wrap warning or error")

# ===========================================================================
print("\n=== 7. any species order is authorable ===")
# ---------------------------------------------------------------------------
wave = fresh().wave_definitions[0].id
for seq in (["RING", "RING"], ["RING", "RING", "RING"],
            ["DROPPER", "DROPPER"],
            ["RING", "DROPPER", "DROPPER", "RING"],
            ["DROPPER", "DROPPER", "DROPPER", "DROPPER"]):
    q = fresh()
    q.triggers = [Trigger(10 * (i + 1), wave, s, []) for i, s in enumerate(seq)]
    check("-".join(seq) + " is accepted", validate(q).ok, str(codes(q)))
src = (REPO / "src" / "waves.asm").read_text(encoding="utf-8")
check("the engine no longer asserts the alternation",
      "two consecutive authored waves use the same enemy species" not in src)
v_src = (HERE / "validation_v6.py").read_text(encoding="utf-8")
check("...and neither does the validator", "trigger.repeated_species" not in v_src)

# Add Trigger's default is deterministic, Duplicate still inherits
from controller_v6 import EditorController                           # noqa: E402
c = EditorController.canonical(HERE)
check("Add Trigger defaults to RING whatever precedes it",
      c.suggested_species() == "RING" and c.suggested_species(1) == "RING")
_before = len(c.project.triggers)
i = c.add_trigger(world_progress=c.project.triggers[-1].world_progress + 5)
t = c.project.triggers[i]
check("...a new trigger is RING, unarmed and side LEFT",
      t.species == "RING" and t.fire_mask == [] and t.dropper_side == "LEFT",
      f"{t.species}, mask {t.fire_mask}, side {t.dropper_side}")
check("...and it references a real wave definition",
      t.wave_definition in {d.id for d in c.project.wave_definitions})
c2 = EditorController.canonical(HERE)
src_t = c2.project.triggers[1]
j = c2.duplicate_trigger(1)
dup = c2.project.triggers[j]
check("Duplicate still inherits the selected trigger's species and fields",
      (dup.species == src_t.species and dup.fire_mask == src_t.fire_mask
       and dup.dropper_side == src_t.dropper_side
       and dup.wave_definition == src_t.wave_definition),
      f"{dup.species}")

# ===========================================================================
print("\n=== 1 + 2. the widget layer, against real Tk ===")
# ---------------------------------------------------------------------------
try:
    import tkinter as tk
    _r = tk.Tk()
    _r.destroy()
except Exception as exc:                                             # noqa: BLE001
    print(f"SKIP - Tk unavailable ({exc})")
else:
    import editor as ed                                              # noqa: E402
    ed.messagebox.showerror = lambda *a, **k: None
    ed.messagebox.showinfo = lambda *a, **k: None

    class _Ev:
        def __init__(self, x, y):
            self.x, self.y = x, y

    tmp = tempfile.TemporaryDirectory()
    disp = Path(tmp.name) / "disposable.v6.json"
    doc = json.loads(CANON.read_text(encoding="utf-8"))
    rows = doc["stage"]["metatileRows"]
    # first/bottom legal, middle, near-top and the TOP-MOST legal turret row,
    # including one inside the boss quiet zone (low rows are near the boss --
    # play starts at the bottom of the map).
    TURRET_ROWS = [0, 1, 2, rows // 2, rows - 1]
    doc["turrets"] = [{"metatileRow": r, "metatileCol": 3} for r in TURRET_ROWS]
    disp.write_text(json.dumps(doc, indent=2) + "\n")

    app = ed.LevelEditor(ed.find_repo_root())
    app.withdraw()
    app._adopt_project(EditorController.load(disp), disp)
    app.edit_mode.set("turret")
    app.update()
    MP = ed.METATILE_PIXELS

    # ---- 2. every legal turret row is selectable AND deletable -------------
    playable = rows * 4 - 25
    for r in TURRET_ROWS:
        idx = app._turret_index_at(r, 3)
        app._turret_click(_Ev(3 * MP + MP // 2, r * MP + MP // 2))
        app.update_idletasks()
        state = str(app.delete_turret_button.cget("state"))
        n0 = app._turret_count()
        app._delete_selected_turret()
        n1 = app._turret_count()
        # the world row this turret is crossed at, in worldProgress terms
        wp = playable - (r * 4 + 1)
        zone = " (inside the no-spawn zone)" if wp >= doc["stage"]["noSpawnRow"] else ""
        check(f"turret at metatile row {r} selects, enables Delete and deletes{zone}",
              idx is not None and state == "normal" and n1 == n0 - 1,
              f"index {idx}, button {state}, {n0}->{n1}")
    ok("index 0 -- always the top-most turret -- is no longer undeletable")

    # ---- 1. species selection must not move the furniture ------------------
    app._adopt_project(EditorController.load(CANON), CANON)
    app._open_encounters()
    w = app._encounters
    w.withdraw()
    w.geometry("1200x760")
    w.update()
    species = [t.species for t in w.controller.project.triggers]
    if "RING" in species and "DROPPER" in species:
        ring, drop = species.index("RING"), species.index("DROPPER")

        def geom():
            w.update_idletasks()
            return (w.preview.winfo_reqwidth(), w.winfo_reqwidth())

        def pick(i):
            w.trig_tree.selection_set(str(i))
            w._trigger_selected()
            w.update_idletasks()

        pick(ring)
        base = geom()
        sizes = []
        for idx in (drop, ring, drop, ring, drop):
            pick(idx)
            sizes.append(geom())
        check("repeated RING <-> DROPPER leaves the workspace geometry identical",
              all(s == base for s in sizes), f"{base} vs {set(sizes)}")
        pick(drop)
        detail = w.preview.detail.get()
        check("the DROPPER explanation is a single summary line in the strip",
              "\n" not in detail and len(detail) < 120, repr(detail[:70]))
        check("...and the full reason is still shown on the canvas",
              bool(w.preview.error) and "\n" in w.preview.error)
    else:
        ok("SKIP: the canonical level has no RING/DROPPER pair to switch between")
    app.destroy()

print()
if FAIL:
    print(f"{len(FAIL)} FAILURE(S):")
    for m in FAIL:
        print(f"  - {m}")
    sys.exit(1)
print(f"All {len(PASS)} Phase 6A.1 hotfix checks passed.")
