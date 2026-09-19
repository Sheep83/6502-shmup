#!/usr/bin/env python3
"""Author the Level 1 five-enemy rebalance into levels/level1/level.json.

This is the AUTHOR-TIME step. It runs once (or whenever the schedule is
deliberately re-rolled), bakes its randomised choices into explicit wave
definitions and triggers, and writes level.json. From then on level.json is the
canonical source and `build_levels.py` regenerates the ASM from it
deterministically -- there is no randomness left in the build path and none at
all at runtime.

What it changes, starting from the CURRENT live level (recovered from the
generated ASM by import_generated_level.py so nothing else drifts):

  * every six-enemy wave is removed; the level is rescheduled as recurring
    five-enemy waves for its whole playable length;
  * wave starts are spaced at 120 frames (see WAVE INTERVAL below);
  * each wave draws an (attack, enemyType) pair from the engine's existing
    curated vocabulary -- 12 attacks x 4 enemy types -- instead of repeating one
    formation;
  * the upper two turrets of the four-turret cluster are removed.

Everything else -- stage height, palette, scroll divider, tileset, metatile map
and the other six turrets -- is carried through untouched.

WAVE INTERVAL
-------------
Authored triggers fire on TERRAIN POSITION, not on a frame counter: a trigger
fires when SCROLL_ROW descends to its worldRow. The conversion is fixed by the
engine: one logical row = 8 fine steps x SCROLL_FRAME_DIVIDER frames. Level 1
has SCROLL_FRAME_DIVIDER = 2, so

    1 logical row = 16 frames        120 frames = 7.5 logical rows

7.5 is not an integer, so a uniform row gap cannot express exactly 120 frames.
The schedule therefore ALTERNATES 8-row and 7-row gaps (128 / 112 frames), which
averages exactly 7.5 rows = exactly 120 frames per wave and never deviates by
more than 8 frames from the target. This is the closest the row-triggered
authoring model can represent, and it is deliberate rather than approximate.

    python3 tools/level_editor/author_level1_five_enemy.py
    python3 tools/level_editor/author_level1_five_enemy.py --dry-run
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
REPO = HERE.parent.parent

from engine_data import ATTACK_COUNT, ENEMY_TYPE_COUNT              # noqa: E402
from import_generated_level import import_level                     # noqa: E402
from project import save_project, stage_logical_rows                # noqa: E402

SEED = 19656                    # fixed: the schedule is reproducible byte-for-byte
WAVE_SIZE = 5
TARGET_FRAMES = 120
FINE_STEPS_PER_ROW = 8

# The four-turret cluster, as world rows. The stage is bottom-origin and
# SCROLL_ROW descends, and screen position increases with logical row, so within
# the cluster the SMALLER world rows are the ones that appear at the TOP of the
# screen. Removing 321 and 329 removes the upper two and leaves 337 and 345.
CLUSTER_WORLD_ROWS = (321, 329, 337, 345)
REMOVE_WORLD_ROWS = (321, 329)

FIRST_TRIGGER_ROW = 390         # just below STAGE_START_ROW so the first wave
                                # arrives shortly after the level begins


def build_schedule(logical_rows, divider):
    frames_per_row = FINE_STEPS_PER_ROW * divider
    rows, gaps, row = [FIRST_TRIGGER_ROW], [], FIRST_TRIGGER_ROW
    big = True
    # 7.5 rows on average: alternate 8 and 7.
    while True:
        gap = 8 if big else 7
        big = not big
        if row - gap < 0:
            break
        row -= gap
        rows.append(row)
        gaps.append(gap)
    mean_rows = (rows[0] - rows[-1]) / len(gaps)
    return rows, gaps, frames_per_row, mean_rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()

    project = import_level("level1")
    slr = stage_logical_rows(project)
    before_turrets = len(project.objects)
    before_triggers = len(project.wave_triggers)

    # ---- Goal 2: drop the upper two turrets of the four-turret cluster ------
    kept = []
    removed = []
    for o in project.objects:
        world_row = o["metatileRow"] * 4 + 1
        if o.get("type") == "turret" and world_row in REMOVE_WORLD_ROWS:
            removed.append((world_row, o["metatileCol"] * 4 + 1))
        else:
            kept.append(o)
    project.objects = kept

    # ---- Goal 1: recurring random five-enemy waves at 120-frame spacing -----
    rows, gaps, frames_per_row, mean_rows = build_schedule(slr, project.scroll_frame_divider)
    rng = random.Random(a.seed)
    defs, triggers, by_key = [], [], {}
    for i, row in enumerate(rows):
        attack_id = rng.randrange(ATTACK_COUNT)
        enemy_type = rng.randrange(ENEMY_TYPE_COUNT)
        key = (attack_id, enemy_type)
        if key not in by_key:
            did = f"wd_a{attack_id:02d}_e{enemy_type}_x{WAVE_SIZE}"
            by_key[key] = did
            defs.append({
                "id": did,
                "name": f"Attack {attack_id} / type {enemy_type} x{WAVE_SIZE}",
                "attackId": attack_id,
                "composition": [{"enemyType": enemy_type, "count": WAVE_SIZE}],
                # null -> the engine's own per-attack default member interval,
                # which keeps the wave inside the curated vocabulary.
                "spawnInterval": None,
            })
        triggers.append({"id": f"wt_{i:03d}", "worldRow": row, "waveDef": by_key[key]})
    defs.sort(key=lambda d: d["id"])
    project.wave_definitions = defs
    project.wave_triggers = triggers

    print(f"stage: {project.height} metatile rows ({slr} logical), "
          f"SCROLL_FRAME_DIVIDER={project.scroll_frame_divider} "
          f"-> {frames_per_row} frames per logical row")
    print(f"turrets: {before_turrets} -> {len(project.objects)}  "
          f"(removed world rows {[r for r, _ in removed]})")
    print(f"waves:   {before_triggers} -> {len(triggers)} triggers, "
          f"{len(defs)} definitions, every wave size {WAVE_SIZE}")
    print(f"spacing: rows {rows[0]}..{rows[-1]}, gaps alternating "
          f"{sorted(set(gaps))} rows, mean {mean_rows:.3f} rows "
          f"= {mean_rows * frames_per_row:.1f} frames (target {TARGET_FRAMES})")
    print(f"vocabulary used: {len(by_key)} distinct (attack, enemyType) pairs "
          f"out of {ATTACK_COUNT * ENEMY_TYPE_COUNT}")

    if a.dry_run:
        print("(dry run: level.json not written)")
        return 0
    out = HERE / "levels" / "level1" / "level.json"
    save_project(project, out)
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
