#!/usr/bin/env python3
"""DEPRECATED (Contract v2). Recover a v5 level.json FROM its generated includes.

    *** THIS IS NOT THE ENCOUNTER IMPORTER. ***

    For engine-authored ENCOUNTER data -- movement programs, wave definitions
    and absolute triggers -- use tools/level_editor/import_engine_v6.py, which
    reads src/wave_programs.asm and src/wave_encounters.asm into the v6 model.

WHY THIS FILE IS DEPRECATED RATHER THAN REFACTORED. Its job is unrelated to the
one above: it inverts the v5 `ka_export` to rebuild a v5 `level.json` from
generated TERRAIN/config/turret assembler, at a time when the committed ASM had
drifted ahead of every authored source. It reads `stage_test.asm` and
`stage_waves.asm` from `src/generated/<level>/`; the directory and both filenames
have since been retired, and no encounter data is generated at all any more, so
the tool cannot work as written. Refactoring it onto the current layout would
produce a SECOND authoritative import path for terrain that Phase 2 already
round-trips byte-for-byte from the v6 model -- which is exactly the duplication
Contract v2 exists to remove.

It is left in place, unused and unreferenced by any test, as history.


The generated ASM under ``src/generated/<level>/`` is normally derived output,
but Level 1's includes had drifted ahead of every authored source in the repo:
the committed ASM carried 105 metatile rows, 34 metatile defs, 72 glyphs, its own
palette, 10 turrets and 16 wave triggers, while ``levels/level1/level.json`` (and
the hard-coded reconstruction in ``build_levels.py``) still described a 100-row,
9-turret, 5-trigger level with a different palette. Regenerating would have
silently thrown the live level away.

This tool inverts ``ka_export`` exactly, so the recovered project re-exports
byte-for-byte identical ASM. That round-trip is the correctness proof, and it is
checked by ``--verify``.

    python3 tools/level_editor/import_generated_level.py level1
    python3 tools/level_editor/import_generated_level.py level1 --verify

Ownership after recovery is the intended one: level.json is the editable
canonical source, generated ASM is derived build input.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

REPO = HERE.parent.parent

from engine_data import TERRAIN_GLYPH_BASE, load_engine_data       # noqa: E402
from ka_export import export_level                                 # noqa: E402
from project import LevelProject, save_project                     # noqa: E402


def _const(text, name, cast=int):
    m = re.search(rf"^\s*\.const\s+{re.escape(name)}\s*=\s*(-?\d+)", text, re.M)
    if not m:
        raise SystemExit(f"constant {name} not found")
    return cast(m.group(1))


def _byte_rows(text, start_label, end_label):
    rows, inside = [], False
    for line in text.splitlines():
        s = line.strip()
        if s == f"{start_label}:":
            inside = True
            continue
        if inside and s == f"{end_label}:":
            break
        if not inside:
            continue
        payload = s.split("//", 1)[0]
        if ".byte" not in payload:
            continue
        rows.append([int(t) for t in payload.split(".byte", 1)[1].split(",") if t.strip()])
    if not inside:
        raise SystemExit(f"could not find {start_label}: in source")
    return rows


def _list_var(text, name):
    m = re.search(rf"^\s*\.var\s+{re.escape(name)}\s*=\s*List\(\)(.*)$", text, re.M)
    if not m:
        raise SystemExit(f"list {name} not found")
    body = m.group(1).strip()
    if not body.startswith(".add("):
        return []
    inner = body[len(".add("):].rstrip()
    inner = inner[:-1] if inner.endswith(")") else inner
    return [int(t) for t in inner.split(",") if t.strip()]


def import_level(name, generated_root=None):
    gen = Path(generated_root or (REPO / "src" / "generated")) / name
    cfg = (gen / "stage_config.asm").read_text(encoding="utf-8")
    charset = (gen / "stage_charset.asm").read_text(encoding="utf-8")
    stage = (gen / "stage_test.asm").read_text(encoding="utf-8")
    turrets = (gen / "stage_turrets.asm").read_text(encoding="utf-8")
    waves = (gen / "stage_waves.asm").read_text(encoding="utf-8")

    height = _const(cfg, "STAGE_METATILE_ROWS")
    divider = _const(cfg, "SCROLL_FRAME_DIVIDER")
    palette = {
        "background": _const(cfg, "TERRAIN_BACKGROUND_COLOUR"),
        "multicolour1": _const(cfg, "TERRAIN_MC_COLOUR_1"),
        "multicolour2": _const(cfg, "TERRAIN_MC_COLOUR_2"),
        "character": _const(cfg, "TERRAIN_CHARACTER_COLOUR"),
    }
    glyph_count = _const(cfg, "TERRAIN_GLYPH_COUNT")

    glyphs = _byte_rows(charset, "terrainGlyphs", "terrainGlyphsEnd")
    if len(glyphs) != glyph_count:
        raise SystemExit(f"{name}: {len(glyphs)} glyphs but TERRAIN_GLYPH_COUNT={glyph_count}")

    defs = _byte_rows(stage, "metatileDefs", "METATILE_DEFS_END")
    rows = _byte_rows(stage, "stageMetatileRows", "STAGE_METATILE_ROWS_END")
    if len(rows) != height:
        raise SystemExit(f"{name}: {len(rows)} rows but STAGE_METATILE_ROWS={height}")

    t_cols = _list_var(turrets, "turretCols")
    t_rows = _list_var(turrets, "turretRows")
    objects = [
        {"type": "turret", "metatileRow": (wr - 1) // 4, "metatileCol": (wc - 1) // 4}
        for wr, wc in zip(t_rows, t_cols)
    ]

    # Wave triggers are recovered as one definition per DISTINCT resolved
    # (attackId, count, enemyType, interval) tuple, which is exactly the
    # information ka_export._resolve_triggers consumes. Definition ids are
    # derived from that tuple so the recovery is deterministic.
    w_rows_lo = _list_var(waves, "waveTriggerRowLo")
    w_rows_hi = _list_var(waves, "waveTriggerRowHi")
    w_attack = _list_var(waves, "waveTriggerAttackId")
    w_count = _list_var(waves, "waveTriggerCount")
    w_sprite = _list_var(waves, "waveTriggerSprite")
    w_interval = _list_var(waves, "waveTriggerInterval")
    wave_defs, wave_triggers, seen = [], [], {}
    for i, (lo, hi) in enumerate(zip(w_rows_lo, w_rows_hi)):
        key = (w_attack[i], w_count[i], w_sprite[i] // 8, w_interval[i])
        if key not in seen:
            did = f"wd_a{key[0]}_n{key[1]}_e{key[2]}_i{key[3]}"
            seen[key] = did
            wave_defs.append({
                "id": did,
                "name": f"Attack {key[0]} x{key[1]}",
                "attackId": key[0],
                "composition": [{"enemyType": key[2], "count": key[1]}],
                "spawnInterval": key[3],
            })
        wave_triggers.append({
            "id": f"wt_{i:03d}",
            "worldRow": lo + 256 * hi,
            "waveDef": seen[key],
        })

    return LevelProject(
        name=name,
        metatile_rows=rows,
        palette=palette,
        scroll_frame_divider=divider,
        objects=objects,
        metatile_metadata={},
        tileset={
            "glyphCount": glyph_count,
            "glyphs": [list(g) for g in glyphs],
            "metatileDefs": [list(d) for d in defs],
        },
        wave_definitions=wave_defs,
        wave_triggers=wave_triggers,
    )


def verify_roundtrip(project, generated_root=None):
    """Re-export the recovered project into a scratch dir and compare against the
    real generated includes. Byte-identical output proves the import inverted the
    export exactly."""
    import tempfile

    gen = Path(generated_root or (REPO / "src" / "generated")) / project.name
    engine = load_engine_data(REPO)
    with tempfile.TemporaryDirectory() as tmp:
        paths = export_level(project, Path(tmp), engine_data=engine)
        diffs = []
        for p in paths:
            original = gen / p.name
            if not original.exists():
                diffs.append(f"{p.name}: no original to compare")
                continue
            if original.read_text(encoding="utf-8") != p.read_text(encoding="utf-8"):
                diffs.append(f"{p.name}: DIFFERS")
    return diffs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("level", nargs="?", default="level1")
    ap.add_argument("--verify", action="store_true",
                    help="only check that re-export reproduces the generated ASM")
    ap.add_argument("--out", default=None, help="level.json path (default: levels/<level>/level.json)")
    a = ap.parse_args()

    project = import_level(a.level)
    print(f"{a.level}: {project.height} metatile rows, "
          f"{len(project.tileset['metatileDefs'])} metatile defs, "
          f"{len(project.tileset['glyphs'])} glyphs, "
          f"{len(project.objects)} turrets, "
          f"{len(project.wave_triggers)} wave triggers, "
          f"{len(project.wave_definitions)} wave definitions")

    diffs = verify_roundtrip(project)
    if diffs:
        print("ROUND-TRIP MISMATCH:")
        for d in diffs:
            print("  ", d)
        return 1
    print("round-trip: re-export is byte-identical to the generated ASM")

    if not a.verify:
        out = Path(a.out) if a.out else (HERE / "levels" / a.level / "level.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        save_project(project, out)
        print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
