#!/usr/bin/env python3
"""Author sparse surface detail into levels/level2/level.v6.json.

WHY THIS IS AN AUTHOR-TIME SCRIPT AND NOT A CHANGE TO gen_level2_pcb.py.
That generator says of itself, in its own footer, that it is "NO LONGER THE
SOURCE OF TRUTH": levels/level2/ was promoted to the real Level 2 and is
authored in the editor, so regenerating over it would discard every edit made
since. It is also, as of now, simply broken -- it raises KeyError on
l1["movementPrograms"], a key the v6 schema no longer has -- so regeneration is
not merely discouraged, it is impossible without repairing it first, which is
not this task. So this follows the pattern of author_level1_five_enemy.py: a
one-shot author-time pass that edits the canonical project and carries
everything else through untouched.

    python3 tools/level_editor/author_level2_surface_detail.py [--dry-run]

THE PROBLEM. BOARD -- the empty green metatile -- is 807 of the map's 1380
cells, 58% of the board. At gameplay scale those areas read as a flat field
rather than as a surface.

THE BUDGET, WHICH DECIDED THE WHOLE DESIGN. Terrain owns character codes
96..223 and TERRAIN_GLYPH_NAMESPACE is 128, so 128 is a hard structural cap,
not a soft one; the exporter additionally requires a multiple of eight. Level 2
emits 128 glyphs and looks full. It is not: only 121 are referenced, and codes
217..223 are seven copies of the blank glyph, emitted purely as padding to
reach the multiple of eight. So there are exactly SEVEN free glyph slots, and
they can be taken without touching one pixel of existing artwork.

Seven is enough because a mark that fits inside ONE character cell costs ONE
glyph however many times it is used, at any cell position, in any metatile. The
seven marks below are therefore reused across eight metatile variants.
"""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from native_metatile import NATIVE_W as W, NATIVE_H as H, pack_metatiles  # noqa

PROJECT = HERE / "levels" / "level2" / "level.v6.json"

G, K, S, Y = 0, 1, 2, 3          # substrate, black, light grey, gold
CELL_W, CELL_H = W // 4, H // 4  # 4 native px across, 8 rows down

# ---------------------------------------------------------------------------
# THE SEVEN MARKS. Each is a list of (x, y, tone) inside a single 4x8 cell.
#
# SCALE IS SET BY THE PIXEL, NOT BY TASTE. A multicolour pixel is two screen
# pixels wide and one tall, so:
#     1 x 1 native  = 2 x 1 screen  -- a fine grain, the faintest thing possible
#     1 x 2 native  = 2 x 2 screen  -- a square dot, the workhorse fleck
#     2 x 2 native  = 4 x 2 screen  -- already as wide as half a trace
# Nothing here is bigger than three native pixels. A trace is 2 native px wide
# and runs the full height of a tile; these cannot compete with that, which is
# the point.
#
# GOLD IS THE DEFAULT because on this board gold is exposed metal -- pads, vias,
# test points -- so a fleck of it reads as a speck of stray copper or a stray
# blob of solder, which is what a real board has. Grey and black appear once
# each and no more: grey matches the existing BOARD_SPECK's silkscreen idiom,
# and black is the only tone that can read as a hole rather than a mark.
# ---------------------------------------------------------------------------
MARKS = {
    "dot":     [(1, 3, Y), (1, 4, Y)],                  # square gold fleck
    "fine":    [(2, 6, Y)],                             # the faintest grain
    "grain":   [(1, 1, Y), (1, 2, Y), (2, 2, Y)],       # irregular 3px cluster
    "pair":    [(0, 2, Y), (3, 6, Y)],                  # two grains, far apart
    "splash":  [(2, 4, S), (2, 5, S)],                  # solder / silkscreen
    "nick":    [(1, 5, K)],                             # a mask nick: battle wear
    "scratch": [(0, 1, S), (1, 2, S), (1, 3, S)],       # a short scuff
}

# ---------------------------------------------------------------------------
# THE EIGHT VARIANTS, as (cellCol, cellRow, mark). Mostly blank on purpose:
# six of the eight carry a single mark in one of sixteen cells, and the other
# two carry two marks placed far apart. The cell positions are deliberately
# scattered rather than centred, so that a variant repeated elsewhere on the
# map does not show its own grid.
# ---------------------------------------------------------------------------
# The WEIGHT is the second number, and it is the difference between surface
# texture and a dirty board. Drawn uniformly at first, the two darkest variants
# came up an eighth of the time each -- about nine placements apiece -- and
# black against this green is the highest contrast on the board, so they read as
# specks of dirt rather than as wear. Gold now carries the work; grey is
# occasional; the black nick is rare by construction, landing three or four
# times in the whole stage, which is what "a very small number of battle scars"
# has to mean on a surface this size.
# TWO OR THREE MARKS PER VARIANT, NOT ONE, and that was measured rather than
# chosen. With a single mark per variant and one variant in eleven BOARD cells,
# a whole screen carried about five specks of one to three pixels: a before/
# after of the same frame differed by 106 pixels out of 69,120, and the board
# still read as a flat green field. The acceptance question is whether the flat
# field is broken up, and at that density it was not.
#
# Adding marks per variant is the cheap axis: a mark is one CHARACTER CELL, so
# the same seven bitmaps reused at other cells cost nothing at all. Spreading
# the same number of marked tiles more thickly also keeps far more tiles
# completely plain than simply marking more tiles would.
VARIANTS = {
    "BOARD_GRAIN_A": ([(1, 0, "dot"), (3, 2, "fine")],                    4),
    "BOARD_GRAIN_B": ([(0, 1, "fine"), (2, 3, "fine")],                   4),
    "BOARD_GRAIN_C": ([(0, 1, "grain"), (3, 3, "dot")],                   3),
    "BOARD_GRAIN_D": ([(2, 3, "pair"), (0, 0, "fine")],                   3),
    "BOARD_GRAIN_E": ([(1, 2, "splash"), (3, 0, "dot")],                  2),
    "BOARD_GRAIN_F": ([(2, 1, "dot"), (0, 3, "fine"), (3, 2, "grain")],   3),
    "BOARD_NICK":    ([(1, 1, "nick"), (3, 3, "fine")],                   1),
    "BOARD_SCUFF":   ([(2, 2, "scratch"), (0, 0, "dot")],                 1),
}


def grid_for(spec):
    g = [[G] * W for _ in range(H)]
    for cc, cr, mark in spec:
        for dx, dy, tone in MARKS[mark]:
            g[cr * CELL_H + dy][cc * CELL_W + dx] = tone
    return g


def _rng(seed):
    """A tiny LCG. Deterministic across Python versions, unlike random()."""
    state = [seed & 0xFFFFFFFF]

    def nxt():
        state[0] = (1103515245 * state[0] + 12345) & 0x7FFFFFFF
        return state[0] / 0x7FFFFFFF
    return nxt


def place(rows, board_id, weighted, seed=20250927, rate=0.16):
    """Scatter the variants over BOARD cells only, never two touching.

    NO REGULAR SPACING AND NO GRID. Candidates are drawn at random, and a cell
    is rejected if any of its eight neighbours already carries a mark -- so the
    marks stay isolated specks rather than forming clumps or lines. Everything
    else stays BOARD, which is what keeps the calm areas calm.
    """
    rng = _rng(seed)
    taken = set()
    placed = []
    for r, line in enumerate(rows):
        for c, v in enumerate(line):
            if v != board_id or rng() > rate:
                continue
            if any((r + dr, c + dc) in taken
                   for dr in (-1, 0, 1) for dc in (-1, 0, 1)):
                continue
            rows[r][c] = weighted[int(rng() * len(weighted)) % len(weighted)]
            taken.add((r, c))
            placed.append((r, c))
    return placed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    prj = json.loads(PROJECT.read_text())
    names = [t["name"] for t in prj["levelMetatileSet"]]
    if any(n in names for n in VARIANTS):
        raise SystemExit("surface detail is already authored into this project")

    tiles = [(t["name"],
              [[int(ch) for ch in row] for row in t["native"]["pixels"]])
             for t in prj["levelMetatileSet"]]
    before = len(pack_metatiles([g for _, g in tiles])["glyphs"])

    # APPENDED, NEVER INSERTED. The map holds metatile indices, so adding at
    # the end leaves every existing index -- and, because pack_metatiles walks
    # the tiles in order, every existing glyph code -- exactly where it was.
    for name, (spec, _w) in VARIANTS.items():
        tiles.append((name, grid_for(spec)))

    packed = pack_metatiles([g for _, g in tiles])
    glyphs = list(packed["glyphs"])
    unique = len(glyphs)
    while len(glyphs) % 8:
        glyphs.append([0] * 8)

    rows = [list(r) for r in prj["map"]]
    base = len(prj["levelMetatileSet"])
    weighted = [base + i
                for i, (_n, (_s, w)) in enumerate(VARIANTS.items())
                for _ in range(w)]
    placed = place(rows, names.index("BOARD"), weighted)

    board_cells = sum(r.count(names.index("BOARD")) for r in prj["map"])
    print(f"  glyphs      {before} -> {unique} unique, {len(glyphs)} emitted / 128")
    print(f"  metatiles   {len(prj['levelMetatileSet'])} -> {len(tiles)} / 64")
    print(f"  BOARD cells {board_cells}; variants placed {len(placed)} "
          f"({100.0 * len(placed) / board_cells:.1f}% of them)")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0

    prj["levelMetatileSet"] += [
        {"name": name,
         "native": {"width": W, "height": H,
                    "pixels": ["".join(str(v) for v in row) for row in grid]},
         "source": None}
        for name, grid in tiles[len(prj["levelMetatileSet"]):]]
    prj["glyphs"] = {"count": len(glyphs), "bitmaps": glyphs}
    prj["metatileDefs"] = packed["metatileDefs"]
    prj["map"] = rows
    PROJECT.write_text(json.dumps(prj, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8", newline="\n")
    print(f"  wrote {PROJECT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
