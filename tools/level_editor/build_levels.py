#!/usr/bin/env python3
"""Deterministically (re)build the two authored level packages and their
generated engine includes.

    tools/level_editor/levels/level1/level.json  -> src/generated/level1/*.asm
    tools/level_editor/levels/level2/level.json  -> src/generated/level2/*.asm

Gameplay imports src/generated/level1/ only. Level 2 is an editor/export proof:
its includes are generated and committed but never #import-ed by main.asm.

Run from anywhere:  python3 tools/level_editor/build_levels.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from engine_data import load_engine_data                        # noqa: E402
from ka_export import export_level                             # noqa: E402
from project import LevelProject, load_project, save_project   # noqa: E402
import level2_tileset                                          # noqa: E402

LEVELS_DIR = HERE / "levels"
GENERATED = REPO / "src" / "generated"

# ---------------------------------------------------------------------------
# Level 1 - the level gameplay consumes.
#
# OWNERSHIP: levels/level1/level.json is the CANONICAL, EDITABLE source and this
# script only exports it. It used to be the other way round: build_level1()
# reconstructed the level from hard-coded Python constants plus the git-committed
# stage_test.asm, and re-running this script would have silently replaced the
# live level with that stale reconstruction. By the time it was noticed the two
# had diverged badly -- the reconstruction described a 100-row, 9-turret,
# 5-trigger level with a different palette, while the generated ASM the game
# actually builds carried 105 rows, 34 metatile defs, 72 glyphs, 10 turrets and
# 16 wave triggers.
#
# The live level was recovered into level.json by
# tools/level_editor/import_generated_level.py (which inverts ka_export exactly
# and verifies the round-trip), then re-authored by
# tools/level_editor/author_level1_five_enemy.py. Nothing here reconstructs
# terrain, palette, turrets or waves any more.
# ---------------------------------------------------------------------------
L1_NAME = "level1"


def build_level1(engine):
    """Load Level 1 from its canonical JSON. No reconstruction, no defaults."""
    json_path = LEVELS_DIR / L1_NAME / "level.json"
    if not json_path.exists():
        raise SystemExit(
            f"{json_path} is missing. Level 1 is JSON-owned; recover it with\n"
            f"    python3 tools/level_editor/import_generated_level.py level1"
        )
    return load_project(json_path)


# ---------------------------------------------------------------------------
# Level 2 - planet surface. Editor/export proof only; never imported by
# gameplay. Crude, visibly distinct tileset (level2_tileset.py) + a hand-shaped
# 64-row planet map.
# ---------------------------------------------------------------------------
L2_NAME = "level2"
L2_PALETTE = {"background": 0, "multicolour1": 9, "multicolour2": 8, "character": 1}
L2_DIVIDER = 2
L2_ROWS = 64
L2_TURRETS = [(50, 2), (18, 7)]     # world rows 201 / 73
L2_WAVE_DEFS = [
    {"id": "wd_crater_rush", "name": "Crater rush", "attackId": 2,
     "composition": [{"enemyType": 1, "count": 6}], "spawnInterval": None},
    {"id": "wd_ridge_dive", "name": "Ridge dive", "attackId": 8,
     "composition": [{"enemyType": 3, "count": 5}], "spawnInterval": 16},
]
L2_WAVE_TRIGGERS = [
    {"id": "wt_p_top", "worldRow": 236, "waveDef": "wd_crater_rush"},
    {"id": "wt_p_low", "worldRow": 120, "waveDef": "wd_ridge_dive"},
]


def build_level2():
    # A deterministic planet profile: mostly plain rocky ground with recognisable
    # feature bands. Rows 0 and last kept plain for a clean vertical wrap seam.
    P, GRAVEL, DUST = 0, 1, 13
    CLIFF_TOP, CLIFF_FACE, CLIFF_BASE = 2, 3, 15
    CRATER, CRATER_FLOOR, CRATER_RIM = 4, 5, 14
    STRATA, PIT, PODS, RIDGE, VENTS, CRACKS, SCREE = 6, 7, 8, 9, 10, 11, 12

    feature_rows = {
        3: STRATA, 4: STRATA, 5: STRATA,
        9: CLIFF_TOP, 10: CLIFF_FACE, 11: CLIFF_FACE, 12: CLIFF_BASE,
        16: CRATER_RIM, 17: CRATER, 18: CRATER, 19: CRATER_FLOOR, 20: CRATER_RIM,
        25: RIDGE, 26: RIDGE,
        30: PODS, 31: PODS,
        35: VENTS, 36: VENTS,
        40: PIT, 41: PIT, 42: PIT,
        46: STRATA, 47: STRATA,
        51: CLIFF_TOP, 52: CLIFF_FACE, 53: CLIFF_BASE,
        56: CRACKS, 57: SCREE,
        60: DUST, 61: GRAVEL,
    }
    rows = []
    for i in range(L2_ROWS):
        if i in (0, L2_ROWS - 1):
            rows.append([P] * 10)
            continue
        base = feature_rows.get(i, P)
        row = [base] * 10
        # scatter a couple of contrast tiles so bands are not perfectly flat
        if base == P:
            row[(i * 3) % 10] = GRAVEL
            row[(i * 7) % 10] = DUST
        rows.append(row)
    for mrow, mcol in L2_TURRETS:
        rows[mrow][mcol] = CLIFF_BASE

    return LevelProject(
        name=L2_NAME,
        metatile_rows=rows,
        palette=dict(L2_PALETTE),
        scroll_frame_divider=L2_DIVIDER,
        objects=[{"type": "turret", "metatileRow": mr, "metatileCol": mc}
                 for mr, mc in L2_TURRETS],
        metatile_metadata={},
        tileset=level2_tileset.tileset(),
        wave_definitions=[dict(d) for d in L2_WAVE_DEFS],
        wave_triggers=[dict(t) for t in L2_WAVE_TRIGGERS],
    )


def _emit(project, engine):
    pkg_dir = LEVELS_DIR / project.name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    json_path = pkg_dir / "level.json"
    save_project(project, json_path)
    out_dir = GENERATED / project.name
    paths = export_level(project, out_dir, engine_data=engine)
    print(f"{project.name}: {json_path.relative_to(REPO)}")
    for p in paths:
        print(f"          {p.relative_to(REPO)}")
    print(f"          {project.height} metatile rows ({project.height * 4} logical), "
          f"{len(project.objects)} turrets, {len(project.wave_triggers)} wave triggers")


def main():
    engine = load_engine_data(REPO)
    _emit(build_level1(engine), engine)
    _emit(build_level2(), engine)


if __name__ == "__main__":
    main()
