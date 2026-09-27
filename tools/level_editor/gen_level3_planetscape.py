#!/usr/bin/env python3
"""Build the Level 3 planetscape project: tileset, metatile vocabulary, showcase.

Writes tools/level_editor/levels/level3/level.v6.json, which the ordinary
exporter then turns into src/level3/*.asm exactly as for levels 1 and 2. No
engine change, no new format, no runtime composition: every piece of every
multi-metatile crater is authored here as its own metatile, cut from ONE canvas
so the seams line up by construction rather than by luck.

    python3 tools/level_editor/gen_level3_planetscape.py
"""
from __future__ import annotations

import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from native_metatile import NATIVE_W as W, NATIVE_H as H, pack_metatiles  # noqa
from engine_data import TERRAIN_GLYPH_BASE                                # noqa
import level3_planetscape as art                                         # noqa

MAP_COLS = 10

# ---------------------------------------------------------------------------
# THE PALETTE, and every value is a decision about light rather than colour.
#
#   $D021 = 8  ORANGE      the regolith. Medium, dominant, quiet.
#   $D022 = 15 LIGHT GREY  sunlit: west faces, crater rims, boulder caps.
#   $D023 = 9  BROWN       shade: east faces, inner walls, cast shadow.
#   cRAM  = 0  BLACK       the deepest pits only. cRAM gives the low three bits
#                          so only 0..7 are reachable at all, and of those black
#                          is the one that reads as a HOLE instead of a stain.
#
# Luminance runs black < brown < orange < light grey, which is monotonic, so the
# four tones stack into relief instead of fighting. It is also, deliberately,
# the ramp src/turrets.asm draws its dome against: pair 1 lit, pair 2 shadow,
# pair 0 the background that must never touch the body's outline. Level 1 obeys
# that and level 2 inverts it; this obeys it, so the shared turret lands on the
# pad already correctly lit.
#
# Warm where it counts and grey where it counts: orange dust and brown shade
# make it a planet, light grey keeps the lit edges reading as ROCK rather than
# as more dust. Nothing here is a second hue for its own sake.
# Key names are the v6 project's own, checked against
# levels/level1/level.v6.json rather than assumed.
PALETTE = {"background": 8, "multicolour1": 15,
           "multicolour2": 9, "character": 0}


def _mt(name, cv):
    return (name, cv)


def build_tiles():
    """The vocabulary, in the order the glyph packer will see it."""
    tiles = []

    # ---- 1. FILLER ---------------------------------------------------------
    # Mostly nothing, on purpose. Quiet ground is what makes the craters read;
    # a surface textured everywhere has no features, only noise. `plain` costs
    # exactly ONE glyph and carries most of the stage.
    tiles.append(_mt("ground_plain", art.canvas()))

    cv = art.canvas(); art.pebbles(cv, 3, seed=21)
    tiles.append(_mt("ground_grit_a", cv))

    # A SECOND variant, and the reason is the scroll rather than the still.
    # One grit tile repeated down a column of a scrolling stage beats out a
    # visible period; two seeds at different densities break it. Four glyphs.
    cv = art.canvas(); art.pebbles(cv, 4, seed=63)
    tiles.append(_mt("ground_grit_b", cv))



    # ---- 2. CRATERS --------------------------------------------------------
    # Small: self contained, two seeds so a field of them is not a stamp.
    cv = art.canvas()
    art.crater(cv, 8, 16, 5.4, seed=2)
    tiles.append(_mt("crater_small", cv))

    # Medium: 2x2. Drawn on one 32x64 canvas and cut, so the rim is continuous
    # across all four joins.
    cv = art.canvas(2, 2)
    art.crater(cv, 16, 32, 10.5, deep_floor=True, seed=4)
    for name, g in zip(("crater_med_NW", "crater_med_NE",
                        "crater_med_SW", "crater_med_SE"),
                       art.slice_metatiles(cv, 2, 2)):
        tiles.append(_mt(name, g))

    # Large: 3x3, one 48x96 canvas. This is the level's centrepiece.
    cv = art.canvas(3, 3)
    art.crater(cv, 24, 48, 15.0, deep_floor=True, seed=5)
    names = ("crater_big_NW", "crater_big_N", "crater_big_NE",
             "crater_big_W",  "crater_big_C", "crater_big_E",
             "crater_big_SW", "crater_big_S", "crater_big_SE")
    for name, g in zip(names, art.slice_metatiles(cv, 3, 3)):
        tiles.append(_mt(name, g))

    # ---- 3. BOULDERS ------------------------------------------------------
    # NO DEBRIS BAKED INTO THE ROCK TILES. Both boulders used to carry a
    # sprinkle of their own; stripping it saved 3 glyphs, and it is the same
    # argument as the crater ejecta below -- scatter that is welded to a feature
    # tile repeats wherever that feature is placed, where scatter in the grit
    # tiles is the level designer's to put down.
    cv = art.canvas(); art.boulder(cv, 6, 20, 2.6, seed=31)
    tiles.append(_mt("rock_small", cv))

    # The big one. At game scale rock_small is a pebble -- correct for what it
    # is, but a surface of nothing but pebbles has no sense of scale. This one
    # is large enough to read as an obstacle the ship flies over, and it is
    # what the halved crater wobble paid for.
    cv = art.canvas(); art.boulder(cv, 8, 17, 4.6, seed=41)
    tiles.append(_mt("rock_med", cv))



    # ---- 4. SURFACE ACCENTS ------------------------------------------------
    # CUT BY THE GLYPH BUDGET, NOT BY CHOICE. The namespace is 128 glyphs and
    # the three crater scales plus the pad and the ground spend 124 of them. The
    # brief's own priority order is ground, craters, platform, boulders, accents,
    # so the accents went first and the boulders down to one. The drawing
    # primitives for cracks, ridges, pits and debris fields are all still in
    # level3_planetscape.py and each costs about 5 glyphs, so any of them can be
    # traded back in against something else -- the report gives the per-piece
    # prices. Dropping the 3x3 crater alone would free 59 and buy every accent
    # and four more boulders; that is a decision about what the level is FOR.


    # ---- 5. TURRET PLATFORM ------------------------------------------------
    # THE CENTRE 2x2 BELONGS TO THE TURRET, NOT TO THIS ART. src/turrets.asm
    # writes its four body glyphs at metatileRow*4+1, metatileCol*4+1 -- the
    # middle four character cells -- so anything drawn there is overwritten the
    # moment a turret is placed. All the platform's construction therefore lives
    # in the outer ring, and the middle is left as a plain machined floor so an
    # EMPTY pad still looks deliberate.
    tiles.append(_mt("turret_pad", _pad()))
    return tiles


def _pad():
    """A machined deck, set proud of the regolith.

    DRAWN AS A SLAB, NOT AS AN OUTLINE. The first version filled the deck with
    MED -- the regolith tone -- and drew only a lip around it, and rendered back
    out at game scale it read as an empty picture frame lying on the ground:
    there was no tonal difference between the platform and the dirt it sat on,
    so there was no platform. The deck is DRK now, which makes it an object,
    and the two cues that put it ON the surface rather than in it are a LIT lip
    along the sunward north-west edges and a DEEP cast shadow thrown onto the
    regolith to the south and east. Same sun as every rock in the level.

    THE CENTRE 2x2 BELONGS TO THE TURRET, NOT TO THIS ART. src/turrets.asm
    writes its four body glyphs at metatileRow*4+1, metatileCol*4+1 -- native
    pixels x 4..11, y 8..23 -- so anything drawn there is overwritten the moment
    a turret is placed. Every detail below is therefore outside that box: the
    bolt heads sit at y 5 and y 25, clear of it whatever their column, and the
    deck beneath the turret is left flat so an EMPTY pad still looks deliberate.
    """
    cv = art.canvas()
    L, R, T, B = 1, 13, 3, 28                  # the slab, in native pixels
    for y in range(T, B + 1):
        for x in range(L, R + 1):
            art.put(cv, x, y, art.DRK)
    # the raised lip: the low north-west sun catches the north and west edges
    for x in range(L, R + 1):
        art.put(cv, x, T, art.LIT)
        art.put(cv, x, T + 1, art.LIT)
    for y in range(T, B + 1):
        art.put(cv, L, y, art.LIT)
        art.put(cv, L + 1, y, art.LIT)
    # chamfered north-west corner, so it is built rather than stamped
    for d in range(3):
        art.put(cv, L + d, T + (2 - d), art.LIT)
    # the cast shadow, on the dirt, south and east -- offset away from the sun
    for x in range(L + 2, R + 3):
        art.put(cv, x, B + 1, art.DEEP)
        art.put(cv, x, B + 2, art.DEEP)
    for y in range(T + 2, B + 3):
        art.put(cv, R + 1, y, art.DEEP)
        art.put(cv, R + 2, y, art.DEEP)
    # four bolt heads: lit crown, shadow under. Engineering, cheaply.
    # y 6 and y 25, not y 5: at y 5 the bolt's lit crown touched the lit lip
    # above it and merged, leaving only its shadow -- the bolts read as
    # notches chopped out of the rim. One pixel of deck between them fixes it.
    for bx in (4, 10):
        for by in (6, 25):
            for dx in (0, 1):
                art.put(cv, bx + dx, by, art.LIT)
                art.put(cv, bx + dx, by + 1, art.DEEP)
    return cv


# ---------------------------------------------------------------------------
# THE SHOWCASE. Not a level: a display case. Each feature gets quiet ground
# around it so its silhouette and its joins can be judged, and the multi-piece
# craters are laid out as the single structures they are.
# ---------------------------------------------------------------------------
def build_map(by_name):
    """A display case, not a level.

    The first version left a screen of empty ground around every feature. That
    is the right instinct for a playable stage and the wrong one for a showcase:
    rendered out at game scale it was four small rings adrift in an orange
    field, and it answered none of the questions the art has to answer. This
    one deliberately puts the awkward cases next to each other -- the same 2x2
    crater twice on one screen, the two filler variants side by side, the small
    boulder against the medium one, an occupied pad and an empty one -- because
    repetition, seams and stamping only show up when things repeat.
    """
    g, ga, gb = (by_name["ground_plain"], by_name["ground_grit_a"],
                 by_name["ground_grit_b"])
    cs, rs, rm = (by_name["crater_small"], by_name["rock_small"],
                  by_name["rock_med"])
    pad = by_name["turret_pad"]
    rows = [[g] * MAP_COLS for _ in range(36)]

    med = [[by_name["crater_med_NW"], by_name["crater_med_NE"]],
           [by_name["crater_med_SW"], by_name["crater_med_SE"]]]
    big = [[by_name["crater_big_NW"], by_name["crater_big_N"], by_name["crater_big_NE"]],
           [by_name["crater_big_W"],  by_name["crater_big_C"], by_name["crater_big_E"]],
           [by_name["crater_big_SW"], by_name["crater_big_S"], by_name["crater_big_SE"]]]

    def stamp(r, c, block):
        for j, line in enumerate(block):
            for i, v in enumerate(line):
                rows[r + j][c + i] = v

    def at(r, cells):
        for c, v in cells:
            rows[r][c] = v

    # 0-1  quiet lead-in: the plain surface, on its own, first
    at(2,  [(0, ga), (1, gb), (3, ga), (4, gb), (6, ga), (7, gb), (9, ga)])
    at(4,  [(1, cs), (4, cs), (8, cs), (2, gb), (6, ga)])
    stamp(6, 1, med); stamp(6, 6, med)      # the same 2x2 twice, one screen
    at(8,  [(0, ga), (4, gb), (9, ga)])
    stamp(10, 3, big)                        # the centrepiece
    at(11, [(0, rm), (9, rs)])               # boulders either side, for scale
    at(13, [(2, ga), (7, gb)])
    at(14, [(1, rs), (3, rm), (5, rs), (7, rm), (9, rs)])   # the boulder line-up
    at(16, [(2, pad), (7, pad)])             # one gets a turret, one does not
    at(18, [(0, gb), (3, ga), (5, gb), (8, ga)])
    stamp(19, 6, big)                        # the 3x3 again, elsewhere
    at(20, [(1, rm), (3, cs)])
    at(22, [(2, ga), (5, gb), (9, ga)])
    stamp(23, 3, med)
    at(23, [(0, gb), (1, rs), (6, rm), (8, ga)])
    at(25, [(0, ga), (2, cs), (4, gb), (7, rs), (9, gb)])
    # 26-29  the dense field: where scrolling shimmer and repetition show up
    at(26, [(1, gb), (3, rs), (5, ga), (6, cs), (9, rm)])
    at(27, [(0, cs), (4, ga), (8, gb)])
    at(28, [(2, rm), (5, gb), (7, cs), (9, ga)])
    at(29, [(1, ga), (3, gb), (6, rs), (8, rm)])
    at(30, [(0, cs), (2, cs), (5, cs), (7, cs), (9, cs)])   # one scale, repeated
    at(31, [(1, ga), (4, gb), (6, ga), (8, gb)])
    at(32, [(5, pad), (1, rm), (8, ga)])
    # 34-35 quiet tail
    return rows


def main():
    tiles = build_tiles()
    by_name = {name: i for i, (name, _) in enumerate(tiles)}
    packed = pack_metatiles([g for _, g in tiles])
    glyphs = packed["glyphs"]
    rows = build_map(by_name)

    world_rows = len(rows) * 4
    project = {
        "formatVersion": 6,
        "name": "level3",
        "stage": {"metatileRows": len(rows), "metatileCols": MAP_COLS,
                  "noSpawnRow": max(0, world_rows - 50)},
        "palette": dict(PALETTE),
        "glyphs": {"count": len(glyphs), "bitmaps": glyphs},
        "metatileDefs": packed["metatileDefs"],
        "map": rows,
        # One turret, on the pad, so the platform can be judged with its
        # occupant present. Row/col are METATILE coordinates.
        # TWO turrets, on two pads at different stage rows, leaving the third
        # pad bare so the platform can be judged occupied and empty on the same
        # pass. Two rows rather than one because a single turret that fails to
        # appear cannot distinguish "wrong row" from "no turrets at all".
        # Row/col are METATILE coordinates, found from the map rather than
        # written out twice and left to drift.
        # ONE PER METATILE ROW IS A HARD EXPORTER RULE, not a style choice:
        # turretAtMetaRow holds a single index per row, and the exporter refuses
        # a second (turret.duplicate_row). The showcase deliberately puts two
        # pads on row 16, so only the first of those can be occupied -- which
        # suits us, because the other is the bare pad we want to look at.
        "turrets": [{"metatileRow": r, "metatileCol": c}
                    for r, c in _pads_one_per_row(rows, by_name["turret_pad"])],
        # NO ENCOUNTERS. This is a terrain showcase, not a playable level:
        # nothing should fly at the camera while the ground is being judged.
        "triggers": [],
        "levelMetatileSet": [
            {"name": name,
             "native": {"width": W, "height": H,
                        "pixels": ["".join(str(v) for v in r) for r in grid]},
             "source": None}
            for name, grid in tiles],
    }

    out = HERE / "levels" / "level3" / "level.v6.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(project, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")

    print(f"  wrote {out}")
    print(f"  metatiles   {len(tiles):3d} / 64")
    print(f"  glyphs      {len(glyphs):3d} / 128  "
          f"(codes {TERRAIN_GLYPH_BASE}..{TERRAIN_GLYPH_BASE + len(glyphs) - 1})")
    print(f"  map         {len(rows)} metatile rows x {MAP_COLS} "
          f"= {world_rows} world rows")
    unused = [n for n, i in by_name.items() if not any(i in r for r in rows)]
    print(f"  not placed  {', '.join(unused) if unused else '(none)'}")
    return 0


def _pads_one_per_row(rows, pad_id):
    """The first pad cell of each metatile row that has one."""
    out = []
    for r, line in enumerate(rows):
        if pad_id in line:
            out.append((r, line.index(pad_id)))
    return out


if __name__ == "__main__":
    sys.exit(main())
