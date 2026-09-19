#!/usr/bin/env python3
"""Install the generated native bas-relief sci-fi terrain set into Level 1.

Deterministic and re-runnable. It:
  * loads tools/level_editor/levels/level1/level.json (the authored package);
  * REPLACES its levelMetatileSet with native_terrain_tiles.metatiles()
    (the pre-workshop 16 METATILE_NAMES "riveted hull" tiles were the baseline
    test vocabulary - the new set is a purpose-built superset covering the same
    concepts plus vents / conduits / hazard / pit / core);
  * remaps every painted map cell old-id -> new-id via REMAP so the scrolling
    stage stays structurally coherent;
  * lays a small DEMO PATCH (3 adjacent rows near the far end, currently blank,
    no turrets or wave triggers nearby) so VICE shows many new tiles together;
  * leaves turrets, wave definitions/triggers, palette, height and scroll
    divider untouched;
  * repacks the tileset, saves level.json (fmt v5) and re-exports
    src/generated/level1/ through the normal pipeline.

    python3 tools/level_editor/install_level1_terrain.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import native_terrain_tiles as ntt                                  # noqa: E402
from engine_data import load_engine_data                            # noqa: E402
from ka_export import export_level                                  # noqa: E402
from project import (                                               # noqa: E402
    load_project, metatile_set_entry_from_native, repack_tileset_from_metatile_set,
    save_project, validate_project,
)

L1_JSON = HERE / "levels" / "level1" / "level.json"
GEN = REPO / "src" / "generated" / "level1"

NEW_NAMES = ntt.names()
IDX = {n: i for i, n in enumerate(NEW_NAMES)}

# old 16 METATILE_NAMES  ->  new tile name (both bas-relief metal vocabularies)
REMAP_NAME = {
    0: "DECK_PLAIN",     1: "DECK_RIVET",     2: "WALL_TOP",       3: "WALL_BOTTOM",
    4: "WALL_LEFT",      5: "WALL_RIGHT",     6: "CORNER_TL",      7: "PLATE_RAISED",
    8: "PLATE_RECESSED", 9: "CORNER_BR",     10: "CONDUIT_V",     11: "CONDUIT_H",
    12: "PLATE_RECESSED", 13: "GRILLE_BANK", 14: "MACHINE_A",     15: "SEAM_HORIZ",
}
REMAP = {old: IDX[name] for old, name in REMAP_NAME.items()}

# 3 x 10 demo layout by tile name (near the far/top end - rows 2..4 are blank
# in the committed map and carry no turret or wave trigger).
DEMO_ROWS = {
    2: ["DECK_PLAIN", "PLATE_RAISED", "PLATE_RECESSED", "ARMOUR_PLATE", "HATCH",
        "SEAM_HORIZ", "SEAM_VERT", "VENT_BANK", "GRILLE_BANK", "CORE"],
    3: ["WALL_LEFT", "RIB_FIELD", "MACHINE_A", "MACHINE_B", "CONDUIT_H",
        "CONDUIT_V", "CONDUIT_BEND", "HAZARD_BAND", "BRACE_X", "WALL_RIGHT"],
    4: ["DECK_RIVET", "DECK_SCUFFED", "DECK_PANEL", "SEAM_CROSS", "CORNER_TL",
        "PIT_MOUTH", "GAP", "DAMAGED", "WALL_TOP", "WALL_BOTTOM"],
}


def main():
    project = load_project(L1_JSON)
    old_count = len(project.level_metatile_set)

    project.level_metatile_set = [
        metatile_set_entry_from_native(px, name=name, source={"generator": "native_terrain_tiles"})
        for name, px in ntt.metatiles()
    ]

    # remap the painted map (any old id not in REMAP -> DECK_PLAIN)
    deck = IDX["DECK_PLAIN"]
    project.metatile_rows = [[REMAP.get(c, deck) for c in row] for row in project.metatile_rows]

    # demo patch
    for r, tile_names in DEMO_ROWS.items():
        assert r < project.height, f"demo row {r} out of range"
        project.metatile_rows[r] = [IDX[n] for n in tile_names]

    repack_tileset_from_metatile_set(project)
    errs = validate_project(project)
    if errs:
        raise SystemExit("level 1 invalid after install:\n" + "\n".join(errs))

    n_mt = len(project.level_metatile_set)
    n_gl = project.tileset["glyphCount"]
    save_project(project, L1_JSON)
    engine = load_engine_data(REPO)
    paths = export_level(project, GEN, engine_data=engine)

    used = sorted({c for row in project.metatile_rows for c in row})
    print(f"Level 1 terrain installed: {old_count} -> {n_mt} metatiles, "
          f"{n_gl} packed terrain glyphs (budget 128).")
    print(f"  map now uses metatile ids {used[0]}..{used[-1]} "
          f"({len(used)} distinct); {len(project.objects)} turrets, "
          f"{len(project.wave_triggers)} wave triggers (unchanged).")
    print("  demo patch: rows " + ", ".join(map(str, DEMO_ROWS)) + " (31 tiles side by side).")
    for p in paths:
        print(f"  wrote {p.relative_to(REPO)}")


if __name__ == "__main__":
    main()
