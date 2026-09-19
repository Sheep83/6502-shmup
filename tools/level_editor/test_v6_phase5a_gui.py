#!/usr/bin/env python3
"""Phase 5A: the GUI's model is genuinely v6, and it preserves what it cannot edit.

NO TKINTER. Everything here goes through `controller_v6`, which is the object the
GUI actually edits -- so these are not a parallel implementation of the editor's
behaviour, they are the editor's behaviour with the widgets taken off. The two
GUI files (test_editor_workshop_gui.py, test_editor_asset_workflow_gui.py) cover
the widget layer against real Tk.

What this proves
----------------
* the canonical Level 1 v6 project loads through the controller the GUI uses;
* OPEN + SAVE WITH NO EDITS IS BYTE-IDENTICAL -- the one result that decides
  whether unexposed data is safe;
* movement programs, wave definitions, triggers and noSpawnRow survive a load,
  a terrain edit, a turret edit, an undo snapshot and a save;
* saving is deterministic and idempotent;
* export invokes the Phase 4 six-file exporter and reproduces the committed
  production ASM byte for byte;
* a single terrain cell edit changes the map and NOTHING else;
* a single turret edit changes the turrets and NOTHING else;
* a v5 project still migrates through the same load path the GUI uses;
* the stage row range is the current 7..440, not the retired 768;
* duration uses the current 1 px/frame contract with no scroll divider;
* the turret limit and one-per-row rule are enforced;
* `scrollFrameDivider` is inert and absent from saved output;
* the v5 attack-catalogue surface cannot be reached from a v6 project.
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
V5_SOURCE = HERE / "levels" / "level1" / "level.json"
PRODUCTION_ASM = REPO / "src" / "level1"

PASS, FAIL = [], []


def ok(msg, extra=""):
    PASS.append(msg)
    print(f"ok  - {msg}" + (f"  [{extra}]" if extra else ""))


def check(msg, cond, extra=""):
    if cond:
        ok(msg, extra)
    else:
        FAIL.append(msg)
        print(f"FAIL- {msg}" + (f"  [{extra}]" if extra else ""))


def encounter_fingerprint(project):
    """Everything the Phase 5A GUI cannot edit, as comparable text."""
    return json.dumps({
        "movementPrograms": [p.to_dict() for p in project.movement_programs],
        "waveDefinitions": [d.to_dict() for d in project.wave_definitions],
        "triggers": [t.to_dict() for t in project.triggers],
        "noSpawnRow": project.stage.no_spawn_row,
    }, sort_keys=True)


def graphics_fingerprint(project):
    return json.dumps({"glyphs": project.glyphs,
                       "metatileDefs": project.metatile_defs,
                       "palette": project.palette.to_dict()}, sort_keys=True)


# ===========================================================================
# 1. The canonical project, through the controller the GUI uses
# ===========================================================================
CANON_BYTES = CANON.read_bytes()
c = EditorController.canonical(HERE)

check("the canonical v6 project loads through the GUI's controller",
      c.project.stage.metatile_rows == 105 and len(c.project.turrets) == 8,
      f"{c.metatile_rows} rows, {len(c.turrets)} turrets")
check("...as formatVersion 6, with no migration",
      not c.migrated and c.from_version == project_v6.FORMAT_VERSION)
check("...and the live model is a ProjectV6, not a v5 LevelProject",
      isinstance(c.project, project_v6.ProjectV6))
check("...with the expected content",
      (len(c.project.glyphs) == 72 and len(c.project.metatile_defs) == 34
       and c.metatile_cols == 10 and c.no_spawn_row == 340
       and len(c.project.movement_programs) == 4
       and len(c.project.wave_definitions) == 4
       and len(c.project.triggers) == 4),
      f"{len(c.project.glyphs)} glyphs, {len(c.project.metatile_defs)} defs, "
      f"noSpawn {c.no_spawn_row}")
check("...and it validates clean", c.validate().ok,
      f"{len(c.validate().errors)} errors")

# ===========================================================================
# 2. THE NO-OP ROUND TRIP -- the result the whole phase turns on
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    out = Path(d) / "level.v6.json"
    c.save(out)
    saved = out.read_bytes()
    check("open + save with NO edits is byte-identical JSON",
          saved == CANON_BYTES, f"{len(saved)} vs {len(CANON_BYTES)} bytes")

    # ...and again from the file that was just written: a fixed point, not luck.
    again = EditorController.load(out)
    out2 = Path(d) / "again.json"
    again.save(out2)
    check("...and saving the reloaded project is a fixed point",
          out2.read_bytes() == CANON_BYTES)

check("the saved JSON declares formatVersion 6",
      json.loads(c.to_json())["formatVersion"] == 6)
check("no timestamp or absolute path leaks into the saved JSON",
      "/Users/" not in c.to_json() and "T00:" not in c.to_json())
check("the deterministic text ends in exactly one LF newline",
      c.to_json().endswith("}\n") and not c.to_json().endswith("\n\n"))

# ===========================================================================
# 3. Unexposed data survives the edits the GUI CAN make
# ===========================================================================
enc0 = encounter_fingerprint(c.project)
gfx0 = graphics_fingerprint(c.project)

c2 = EditorController.canonical(HERE)
row, col = 40, 3
original = c2.cell(row, col)
replacement = (original + 1) % max(2, len(c2.project.metatile_defs))
c2.set_cell(row, col, replacement)

check("a terrain edit changes exactly one map cell",
      c2.cell(row, col) == replacement
      and sum(1 for r in range(c2.metatile_rows) for k in range(10)
              if c2.cell(r, k) != EditorController.canonical(HERE).cell(r, k)) == 1,
      f"({row},{col}) {original} -> {replacement}")
check("...and leaves every encounter untouched",
      encounter_fingerprint(c2.project) == enc0)
check("...and leaves noSpawnRow untouched", c2.no_spawn_row == 340)
check("...and leaves turrets untouched",
      [(t.metatile_row, t.metatile_col) for t in c2.turrets]
      == [(t.metatile_row, t.metatile_col) for t in c.turrets])
check("...and leaves palette, glyphs and metatile definitions untouched",
      graphics_fingerprint(c2.project) == gfx0)

# restoring the cell must return the project to the canonical bytes
c2.set_cell(row, col, original)
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "restored.json"
    c2.save(p)
    check("restoring the cell returns byte-identical canonical JSON",
          p.read_bytes() == CANON_BYTES)

# ---- turret isolation -----------------------------------------------------
# LEVEL 1 IS ALREADY AT THE EIGHT-TURRET CAP, so the legal edit the UI supports
# here is a REMOVAL -- placing a ninth is refused, and proving that is section 6.
c3 = EditorController.canonical(HERE)
map0 = json.dumps(c3.project.map_rows)
removed = (c3.turrets[2].metatile_row, c3.turrets[2].metatile_col)
c3.remove_turret(2)
check("a turret edit removes exactly one turret", len(c3.turrets) == 7,
      f"removed metatile row {removed[0]}, col {removed[1]}")
check("...and leaves every encounter untouched",
      encounter_fingerprint(c3.project) == enc0)
check("...and leaves noSpawnRow untouched", c3.no_spawn_row == 340)
check("...and leaves the terrain untouched",
      json.dumps(c3.project.map_rows) == map0)
check("...and leaves palette, glyphs and metatile definitions untouched",
      graphics_fingerprint(c3.project) == gfx0)
c3.add_turret(*removed)
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "restored.json"
    c3.save(p)
    check("putting it back returns byte-identical canonical JSON",
          p.read_bytes() == CANON_BYTES,
          "turrets are canonicalised by position, so order does not matter")

# ===========================================================================
# 4. Export: the Phase 4 six-file exporter, and byte-identical ASM
# ===========================================================================
check("the controller exports the six Phase 4 files, by name",
      tuple(export_v6.GENERATED_NAMES) ==
      ("stage_config.asm", "stage_charset.asm", "stage_map.asm",
       "stage_turrets.asm", "wave_programs.asm", "wave_encounters.asm"),
      str(export_v6.GENERATED_NAMES))
check("...and no obsolete exporter target survives",
      all(n not in export_v6.GENERATED_NAMES
          for n in ("stage_test.asm", "stage_waves.asm")))

with tempfile.TemporaryDirectory() as d:
    written = EditorController.canonical(HERE).export(
        d, carry_enemies_from=PRODUCTION_ASM)
    got = {k: Path(v) for k, v in written.items()}
    check("export wrote all six generated files",
          all(n in got and got[n].is_file() for n in export_v6.GENERATED_NAMES),
          f"{len(got)} files")
    identical, differing = 0, []
    for name in export_v6.GENERATED_NAMES:
        prod = PRODUCTION_ASM / name
        if prod.read_bytes() == got[name].read_bytes():
            identical += 1
        else:
            differing.append(name)
    check("every generated file is byte-identical to the committed production ASM",
          identical == len(export_v6.GENERATED_NAMES),
          f"{identical}/{len(export_v6.GENERATED_NAMES)} identical"
          + (f", differing: {differing}" if differing else ""))

# export is refused when the project is invalid
bad = EditorController.canonical(HERE)
bad.project.turrets.append(project_v6.Turret(0, 0))
bad.project.turrets.append(project_v6.Turret(1, 0))   # 10 turrets: over the cap
try:
    with tempfile.TemporaryDirectory() as d:
        bad.export(d)
    check("validation errors block export", False, "export was allowed")
except ControllerError as exc:
    check("validation errors block export, with a message",
          "validation error" in str(exc), str(exc).splitlines()[0][:60])

# ===========================================================================
# 5. Stage: the current limits and the current duration contract
# ===========================================================================
check("the legal stage range is the current 7..440",
      (C.MIN_METATILE_ROWS, C.MAX_METATILE_ROWS) == (7, 440),
      f"{C.MIN_METATILE_ROWS}..{C.MAX_METATILE_ROWS}")
check("...and the retired 768-row ceiling is gone",
      C.MAX_METATILE_ROWS != 768)

d105 = EditorController.canonical(HERE).duration()
check("duration uses the current 1 px/frame contract",
      d105 == {"logicalRows": 420, "playableRows": 395,
               "playableFrames": 3160, "seconds": 63.2}, str(d105))
check("...derived from metatileRows alone: rows*4, -25, *8, /50",
      (d105["logicalRows"] == 105 * 4
       and d105["playableRows"] == d105["logicalRows"] - 25
       and d105["playableFrames"] == d105["playableRows"] * 8
       and abs(d105["seconds"] - d105["playableFrames"] / 50) < 1e-9))

resizer = EditorController.canonical(HERE)
for bad_rows in (6, 441):
    try:
        resizer.resize(bad_rows)
        check(f"resize to {bad_rows} rows is refused", False, "allowed")
    except ControllerError:
        ok(f"resize to {bad_rows} rows is refused")

# growing is safe; shrinking past a turret is not
grower = EditorController.canonical(HERE)
grower.resize(120)
check("growing the stage adds blank rows and updates the derived height",
      grower.metatile_rows == 120 and grower.project.stage.metatile_rows == 120
      and all(v == 0 for v in grower.project.map_rows[119]))
try:
    grower.resize(10)          # turrets live far above row 10
    check("shrinking past a turret is refused", False, "allowed")
except ControllerError as exc:
    check("shrinking past a turret is refused, naming the turrets",
          "turret" in str(exc), str(exc)[:70])

# ===========================================================================
# 6. Turret limits
# ===========================================================================
t = EditorController.canonical(HERE)
check("the turret cap is the engine's 8", C.MAX_TURRETS == 8)
try:
    t.add_turret(t.turrets[0].metatile_row, 0)
    check("a second turret in one metatile row is refused", False, "allowed")
except ControllerError as exc:
    check("a second turret in one metatile row is refused", "one per row" in str(exc),
          str(exc)[:60])
free = [r for r in range(t.metatile_rows) if t.turret_index_at(r) is None]
try:
    t.add_turret(free[0], 0)    # Level 1 already has eight
    check("a ninth turret is refused", False, "allowed")
except ControllerError as exc:
    check("a ninth turret is refused", "maximum" in str(exc), str(exc)[:60])
t.remove_turret(0)
t.add_turret(free[0], 0)
check("...and one may be placed once room is made", len(t.turrets) == 8)
try:
    t.add_turret(free[1], 0)
    check("the cap is enforced again immediately", False, "allowed")
except ControllerError:
    ok("the cap is enforced again immediately")

# ===========================================================================
# 7. The retired v5 surfaces are inert
# ===========================================================================
check("scrollFrameDivider appears nowhere in saved v6 output",
      "scrollFrameDivider" not in c.to_json())
view = EditorController.canonical(HERE).view
view.scroll_frame_divider = 7                     # a stale widget writing a fiction
check("...and writing the v5 scroll divider is ignored",
      view.scroll_frame_divider == 1, str(view.scroll_frame_divider))
check("...and it still does not reach the saved JSON",
      "scrollFrameDivider" not in view.v6.to_json())
for attr in ("wave_definitions", "wave_triggers"):
    try:
        getattr(view, attr)
        check(f"the v5 {attr} surface is unreachable", False, "it was readable")
    except ControllerError:
        ok(f"the v5 {attr} surface is unreachable from a v6 project")
check("no attack-catalogue field survives into v6 output",
      not any(k in c.to_json() for k in ("attackId", "enemyType", "composition")))

# ===========================================================================
# 8. Historical compatibility: v5 -> GUI load path -> v6 -> save v6
# ===========================================================================
mig = EditorController.load(V5_SOURCE)
check("a v5 project still opens through the GUI's load path",
      mig.migrated and mig.from_version == 5, f"from v{mig.from_version}")
check("...and becomes a v6 model", isinstance(mig.project, project_v6.ProjectV6))
check("...keeping its terrain, glyphs, definitions and turrets",
      (mig.metatile_rows == 105 and len(mig.project.glyphs) == 72
       and len(mig.project.metatile_defs) == 34 and len(mig.project.turrets) == 8),
      f"{mig.metatile_rows} rows, {len(mig.project.turrets)} turrets")
check("...with a derived noSpawnRow", mig.no_spawn_row == 340)
check("...and the v5 encounters deliberately discarded",
      (len(mig.project.movement_programs) == 0
       and len(mig.project.wave_definitions) == 0
       and len(mig.project.triggers) == 0))
check("...and the migration says so, so the GUI can tell the author",
      any(n.code == "migration.dropped_wave_definitions" for n in mig.discard_notices())
      and mig.migration_summary() != "")
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "migrated.v6.json"
    mig.save(p)
    text = p.read_text()
    check("...and a migrated project saves as deterministic v6",
          json.loads(text)["formatVersion"] == 6 and text.endswith("}\n"))
    # metatileRows is NOT on this list: it is a legitimate v6 field
    # (stage.metatileRows). Only names v6 retired belong here.
    check("...with no v5-only field names left in it",
          not any(k in text for k in ("scrollFrameDivider", "attackId",
                                      "enemyType", "composition", "waveTriggers",
                                      "\"tileset\"", "\"objects\"")))
    reloaded = EditorController.load(p)
    p2 = Path(d) / "again.json"
    reloaded.save(p2)
    check("...and that file is itself a fixed point",
          p2.read_bytes() == p.read_bytes())

# ===========================================================================
print()
if FAIL:
    print(f"{len(FAIL)} FAILURE(S):")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {len(PASS)} Phase 5A GUI-model checks passed.")
