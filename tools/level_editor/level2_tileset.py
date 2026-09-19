"""Deliberately crude PLANET-SURFACE terrain tileset for Level 2 (editor-only).

Level 2 is an editor/export proof: it is never imported by gameplay. Its tileset
uses the same C64 global-multicolour terrain constraints as Level 1 (48 8-byte
glyphs on char codes 160.., 16 metatile defs of 4x4 glyph codes) but a visibly
different silhouette vocabulary: rocky/cratered ground, rough cliffs, simple
strata, pits/craters and sparse alien pods rather than Level 1's riveted hull.

Multicolour bit pairs per pixel: 0 = $D021 background, 1 = $D022, 2 = $D023,
3 = character colour (cRAM). Level 2's palette (in level.json) pairs these as a
dusky planet: background dark, 1 = ochre rock, 2 = pale dust, 3 = bright rim.
"""

from engine_data import TERRAIN_GLYPH_BASE          # output base (96 since fmt v5)

_AUTHOR_BASE = 160         # arbitrary key base for the _def() vocabulary below
GLYPH_COUNT = 48
METATILE_DEF_COUNT = 16


def _row(a, b, c, d):
    return ((a & 3) << 6) | ((b & 3) << 4) | ((c & 3) << 2) | (d & 3)


def _g(rows):
    assert len(rows) == 8
    return [_row(*r) for r in rows]


# ---- glyph vocabulary (index == code - 160) --------------------------------
# Only the shapes that matter are drawn; trailing slots are flat background so
# the glyph budget stays a multiple of 8 without inventing filler art.
_GLYPHS = {}


def _def(code, rows):
    _GLYPHS[code] = _g(rows)


# 160 rocky ground fill (speckled 1/2)
_def(160, [(1, 2, 1, 2), (2, 1, 2, 1), (1, 2, 1, 2), (2, 1, 2, 1),
           (1, 2, 1, 2), (2, 1, 2, 1), (1, 2, 1, 2), (2, 1, 2, 1)])
# 161 gravel (fine 1 speckle over background)
_def(161, [(1, 0, 0, 1), (0, 0, 1, 0), (0, 1, 0, 0), (1, 0, 0, 1),
           (0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 1), (0, 0, 1, 0)])
# 162 pale dust drift (2 speckle)
_def(162, [(0, 2, 0, 0), (2, 0, 0, 2), (0, 0, 2, 0), (0, 2, 0, 0),
           (2, 0, 0, 2), (0, 0, 2, 0), (0, 2, 0, 2), (2, 0, 2, 0)])
# 163 small rock (bright core)
_def(163, [(0, 0, 0, 0), (0, 1, 1, 0), (1, 3, 3, 1), (1, 3, 3, 1),
           (0, 1, 1, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)])

# 164-167 crater rim TL / TR / BL / BR (bright arc, hollow inside)
_def(164, [(1, 1, 1, 2), (1, 3, 3, 3), (1, 3, 0, 0), (2, 3, 0, 0),
           (2, 3, 0, 0), (2, 3, 0, 0), (2, 3, 0, 0), (2, 3, 0, 0)])
_def(165, [(2, 1, 1, 1), (3, 3, 3, 1), (0, 0, 3, 1), (0, 0, 3, 2),
           (0, 0, 3, 2), (0, 0, 3, 2), (0, 0, 3, 2), (0, 0, 3, 2)])
_def(166, [(2, 3, 0, 0), (2, 3, 0, 0), (2, 3, 0, 0), (2, 3, 0, 0),
           (1, 3, 0, 0), (1, 3, 3, 3), (1, 1, 3, 2), (1, 1, 1, 2)])
_def(167, [(0, 0, 3, 2), (0, 0, 3, 2), (0, 0, 3, 2), (0, 0, 3, 2),
           (0, 0, 3, 1), (3, 3, 3, 1), (2, 3, 1, 1), (2, 1, 1, 1)])
# 168 crater floor (dark, faint dust)
_def(168, [(0, 0, 0, 0), (0, 0, 2, 0), (0, 0, 0, 0), (0, 2, 0, 0),
           (0, 0, 0, 0), (0, 0, 0, 2), (0, 0, 0, 0), (0, 0, 0, 0)])

# 169 cliff face fill (solid ochre with vertical grain)
_def(169, [(1, 1, 2, 1), (1, 1, 2, 1), (1, 2, 1, 1), (1, 2, 1, 1),
           (1, 1, 2, 1), (1, 1, 2, 1), (1, 2, 1, 1), (1, 2, 1, 1)])
# 170 cliff edge left (bright lip, background to the left)
_def(170, [(0, 3, 1, 1), (0, 3, 1, 1), (0, 3, 1, 2), (0, 3, 1, 1),
           (0, 3, 1, 1), (0, 3, 1, 2), (0, 3, 1, 1), (0, 3, 1, 1)])
# 171 cliff edge right
_def(171, [(1, 1, 3, 0), (1, 1, 3, 0), (2, 1, 3, 0), (1, 1, 3, 0),
           (1, 1, 3, 0), (2, 1, 3, 0), (1, 1, 3, 0), (1, 1, 3, 0)])
# 172 cliff top ridge (bright cap over face)
_def(172, [(3, 3, 3, 3), (2, 2, 2, 2), (1, 1, 2, 1), (1, 1, 2, 1),
           (1, 2, 1, 1), (1, 1, 2, 1), (1, 2, 1, 1), (1, 1, 2, 1)])
# 173 cliff top-left corner
_def(173, [(0, 3, 3, 3), (0, 3, 2, 2), (0, 3, 1, 1), (0, 3, 1, 2),
           (0, 3, 1, 1), (0, 3, 1, 1), (0, 3, 1, 2), (0, 3, 1, 1)])
# 174 cliff top-right corner
_def(174, [(3, 3, 3, 0), (2, 2, 3, 0), (1, 1, 3, 0), (2, 1, 3, 0),
           (1, 1, 3, 0), (1, 1, 3, 0), (2, 1, 3, 0), (1, 1, 3, 0)])
# 175 talus / scree slope (diagonal rubble)
_def(175, [(1, 0, 0, 0), (2, 1, 0, 0), (1, 2, 1, 0), (2, 1, 2, 1),
           (1, 2, 1, 2), (2, 1, 2, 1), (1, 2, 1, 2), (2, 1, 2, 1)])

# 176-179 strata bands (stacked horizontal layers)
_def(176, [(1, 1, 1, 1), (1, 1, 1, 1), (2, 2, 2, 2), (2, 2, 2, 2),
           (1, 1, 1, 1), (1, 1, 1, 1), (3, 3, 3, 3), (1, 1, 1, 1)])
_def(177, [(2, 2, 2, 2), (1, 1, 1, 1), (1, 1, 1, 1), (3, 3, 3, 3),
           (2, 2, 2, 2), (2, 2, 2, 2), (1, 1, 1, 1), (1, 1, 1, 1)])
_def(178, [(1, 1, 1, 1), (3, 3, 3, 3), (1, 1, 1, 1), (1, 1, 1, 1),
           (2, 2, 2, 2), (1, 1, 1, 1), (1, 1, 1, 1), (2, 2, 2, 2)])
_def(179, [(3, 3, 3, 3), (2, 2, 2, 2), (2, 2, 2, 2), (1, 1, 1, 1),
           (1, 1, 1, 1), (2, 2, 2, 2), (1, 1, 1, 1), (3, 3, 3, 3)])

# 180 pit lip (top edge: fill above, void below)
_def(180, [(1, 2, 1, 2), (2, 1, 2, 1), (1, 1, 1, 1), (3, 3, 3, 3),
           (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0)])
# 181 pit void (pure background)
_def(181, [(0, 0, 0, 0)] * 8)
# 182 pit wall left
_def(182, [(1, 3, 0, 0), (1, 3, 0, 0), (1, 3, 0, 0), (1, 3, 0, 0),
           (1, 3, 0, 0), (1, 3, 0, 0), (1, 3, 0, 0), (1, 3, 0, 0)])
# 183 pit wall right
_def(183, [(0, 0, 3, 1), (0, 0, 3, 1), (0, 0, 3, 1), (0, 0, 3, 1),
           (0, 0, 3, 1), (0, 0, 3, 1), (0, 0, 3, 1), (0, 0, 3, 1)])
# 184 pit floor (dark with rubble)
_def(184, [(0, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1), (0, 0, 0, 0),
           (1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 0), (2, 1, 2, 1)])

# 185-188 alien pod TL / TR / BL / BR (bulbous body + bright spine)
_def(185, [(0, 0, 0, 3), (0, 0, 3, 1), (0, 3, 1, 1), (0, 3, 1, 2),
           (3, 1, 2, 1), (3, 1, 1, 1), (3, 1, 2, 1), (3, 1, 1, 1)])
_def(186, [(3, 0, 0, 0), (1, 3, 0, 0), (1, 1, 3, 0), (2, 1, 3, 0),
           (1, 2, 1, 3), (1, 1, 1, 3), (1, 2, 1, 3), (1, 1, 1, 3)])
_def(187, [(3, 1, 2, 1), (3, 1, 1, 1), (0, 3, 1, 1), (0, 3, 1, 2),
           (0, 0, 3, 1), (0, 0, 3, 1), (0, 0, 0, 3), (0, 0, 0, 0)])
_def(188, [(1, 2, 1, 3), (1, 1, 1, 3), (1, 1, 3, 0), (2, 1, 3, 0),
           (1, 3, 0, 0), (1, 3, 0, 0), (3, 0, 0, 0), (0, 0, 0, 0)])
# 189 pod stem / root
_def(189, [(0, 3, 3, 0), (0, 1, 1, 0), (0, 1, 1, 0), (0, 3, 1, 0),
           (0, 1, 3, 0), (0, 1, 1, 0), (1, 1, 1, 1), (2, 1, 2, 1)])

# 190 ridge spike left-leaning
_def(190, [(0, 0, 0, 3), (0, 0, 3, 1), (0, 0, 3, 1), (0, 3, 1, 1),
           (0, 3, 1, 1), (3, 1, 1, 2), (3, 1, 2, 1), (1, 1, 1, 1)])
# 191 ridge spike right-leaning
_def(191, [(3, 0, 0, 0), (1, 3, 0, 0), (1, 3, 0, 0), (1, 1, 3, 0),
           (1, 1, 3, 0), (2, 1, 1, 3), (1, 2, 1, 3), (1, 1, 1, 1)])
# 192 vertical crack in ground
_def(192, [(1, 2, 0, 1), (2, 1, 0, 2), (1, 2, 0, 1), (2, 1, 0, 1),
           (1, 2, 0, 2), (2, 1, 0, 1), (1, 2, 0, 1), (2, 1, 0, 2)])
# 193 horizontal crack
_def(193, [(1, 2, 1, 2), (2, 1, 2, 1), (0, 0, 0, 0), (0, 0, 0, 0),
           (1, 2, 1, 2), (2, 1, 2, 1), (1, 2, 1, 2), (2, 1, 2, 1)])
# 194 vent (dark shaft with bright glow)
_def(194, [(1, 3, 3, 1), (1, 0, 0, 1), (2, 0, 0, 2), (1, 0, 0, 1),
           (2, 0, 0, 2), (1, 0, 0, 1), (1, 3, 3, 1), (1, 1, 1, 1)])
# 195 vent plume (rising dust)
_def(195, [(0, 2, 2, 0), (0, 0, 2, 0), (0, 2, 0, 0), (0, 0, 2, 0),
           (0, 2, 2, 0), (0, 0, 0, 0), (2, 0, 0, 2), (0, 0, 0, 0)])

# 196-199 large crater rim outer (used with 164-167 inner)
_def(196, [(0, 0, 1, 1), (0, 1, 2, 3), (1, 2, 3, 0), (1, 3, 0, 0),
           (2, 3, 0, 0), (2, 3, 0, 0), (1, 3, 0, 0), (1, 3, 0, 0)])
_def(197, [(1, 1, 0, 0), (3, 2, 1, 0), (0, 3, 2, 1), (0, 0, 3, 1),
           (0, 0, 3, 2), (0, 0, 3, 2), (0, 0, 3, 1), (0, 0, 3, 1)])
_def(198, [(1, 3, 0, 0), (1, 3, 0, 0), (2, 3, 0, 0), (1, 3, 2, 0),
           (1, 2, 3, 1), (0, 1, 2, 3), (0, 0, 1, 1), (0, 0, 0, 0)])
_def(199, [(0, 0, 3, 1), (0, 0, 3, 1), (0, 0, 3, 2), (0, 2, 3, 1),
           (1, 3, 2, 1), (3, 2, 1, 0), (1, 1, 0, 0), (0, 0, 0, 0)])

# 200-207 leftover slots: flat rocky ground variants (keeps count = 48, no
# invented detail). 200 mid, 201 lighter, 202 darker, 203 dune, rest plain.
_def(200, [(1, 1, 2, 1), (2, 1, 1, 2), (1, 2, 1, 1), (1, 1, 2, 1),
           (2, 1, 1, 2), (1, 2, 1, 1), (1, 1, 2, 1), (2, 1, 1, 2)])
_def(201, [(2, 1, 2, 2), (1, 2, 2, 1), (2, 2, 1, 2), (2, 1, 2, 2),
           (1, 2, 2, 1), (2, 2, 1, 2), (2, 1, 2, 2), (1, 2, 2, 1)])
_def(202, [(1, 0, 1, 1), (0, 1, 1, 0), (1, 1, 0, 1), (1, 0, 1, 1),
           (0, 1, 1, 0), (1, 1, 0, 1), (1, 0, 1, 1), (0, 1, 1, 0)])
_def(203, [(0, 1, 2, 2), (1, 2, 2, 1), (2, 2, 1, 0), (2, 1, 0, 0),
           (1, 2, 2, 1), (2, 2, 1, 2), (2, 1, 2, 2), (1, 2, 2, 1)])
for _c in range(204, 208):
    _def(_c, [(1, 2, 1, 2), (2, 1, 2, 1)] * 4)


def glyphs():
    """List of 48 8-byte glyph bitmaps for codes 160..207."""
    return [list(_GLYPHS[_AUTHOR_BASE + i]) for i in range(GLYPH_COUNT)]


# ---- metatile defs: 16 x (4x4 glyph codes), row-major within the 4x4 ---------
G = TERRAIN_GLYPH_BASE
_M = [
    # M0 plain rocky ground
    [G + 0, G + 40, G + 0, G + 2, G + 0, G + 1, G + 0, G + 40, G + 2, G + 0, G + 1, G + 0, G + 0, G + 42, G + 0, G + 43],
    # M1 gravel flat
    [G + 1, G + 1, G + 1, G + 1, G + 1, G + 2, G + 1, G + 1, G + 1, G + 1, G + 2, G + 1, G + 1, G + 1, G + 1, G + 1],
    # M2 cliff top edge (ridge across the top)
    [G + 13, G + 12, G + 12, G + 14, G + 10, G + 9, G + 9, G + 11, G + 10, G + 9, G + 9, G + 11, G + 10, G + 9, G + 9, G + 11],
    # M3 cliff face fill
    [G + 10, G + 9, G + 9, G + 11, G + 10, G + 9, G + 9, G + 11, G + 10, G + 9, G + 9, G + 11, G + 10, G + 15, G + 15, G + 11],
    # M4 crater (big rim + inner + floor)
    [G + 36, G + 4, G + 5, G + 37, G + 4, G + 8, G + 8, G + 5, G + 6, G + 8, G + 8, G + 7, G + 38, G + 6, G + 7, G + 39],
    # M5 crater floor / basin
    [G + 8, G + 8, G + 8, G + 8, G + 8, G + 2, G + 8, G + 8, G + 8, G + 8, G + 2, G + 8, G + 8, G + 8, G + 8, G + 8],
    # M6 strata layered
    [G + 16, G + 17, G + 16, G + 17, G + 18, G + 19, G + 18, G + 19, G + 16, G + 17, G + 16, G + 17, G + 18, G + 19, G + 18, G + 19],
    # M7 pit (lip + walls + void + floor)
    [G + 20, G + 20, G + 20, G + 20, G + 22, G + 21, G + 21, G + 23, G + 22, G + 21, G + 21, G + 23, G + 24, G + 24, G + 24, G + 24],
    # M8 alien pod cluster
    [G + 0, G + 25, G + 26, G + 0, G + 25, G + 27, G + 28, G + 26, G + 0, G + 27, G + 28, G + 0, G + 29, G + 0, G + 29, G + 0],
    # M9 ridge / spires
    [G + 30, G + 0, G + 0, G + 31, G + 0, G + 30, G + 31, G + 0, G + 0, G + 30, G + 31, G + 0, G + 15, G + 0, G + 0, G + 15],
    # M10 vent field
    [G + 0, G + 35, G + 0, G + 35, G + 34, G + 0, G + 34, G + 0, G + 0, G + 35, G + 0, G + 0, G + 34, G + 0, G + 34, G + 0],
    # M11 cracked ground
    [G + 0, G + 32, G + 0, G + 0, G + 33, G + 33, G + 33, G + 33, G + 0, G + 32, G + 0, G + 0, G + 0, G + 32, G + 0, G + 0],
    # M12 scree slope
    [G + 15, G + 0, G + 0, G + 0, G + 15, G + 15, G + 0, G + 0, G + 15, G + 15, G + 15, G + 0, G + 15, G + 15, G + 15, G + 15],
    # M13 dust drift
    [G + 2, G + 2, G + 41, G + 2, G + 2, G + 43, G + 2, G + 2, G + 41, G + 2, G + 2, G + 2, G + 2, G + 2, G + 43, G + 2],
    # M14 crater rim only (partial, right side)
    [G + 0, G + 0, G + 36, G + 4, G + 0, G + 36, G + 4, G + 8, G + 36, G + 4, G + 8, G + 8, G + 4, G + 8, G + 8, G + 8],
    # M15 cliff base with talus
    [G + 10, G + 9, G + 9, G + 11, G + 10, G + 9, G + 15, G + 11, G + 10, G + 15, G + 15, G + 11, G + 15, G + 15, G + 15, G + 15],
]


def metatile_defs():
    return [list(m) for m in _M]


def tileset():
    return {
        "glyphCount": GLYPH_COUNT,
        "glyphs": glyphs(),
        "metatileDefs": metatile_defs(),
    }


if __name__ == "__main__":
    ts = tileset()
    assert len(ts["glyphs"]) == GLYPH_COUNT
    assert all(len(g) == 8 for g in ts["glyphs"])
    assert len(ts["metatileDefs"]) == METATILE_DEF_COUNT
    assert all(len(m) == 16 for m in ts["metatileDefs"])
    codes = {c for m in ts["metatileDefs"] for c in m}
    assert min(codes) >= TERRAIN_GLYPH_BASE and max(codes) < TERRAIN_GLYPH_BASE + GLYPH_COUNT, sorted(codes)
    print(f"level2 tileset OK: {GLYPH_COUNT} glyphs, {METATILE_DEF_COUNT} metatile defs, "
          f"codes {min(codes)}..{max(codes)}")
