"""Original native C64 bas-relief sci-fi terrain metatiles, authored directly in
the editor's canonical 16x32 logical-multicolour format (values 0..3) - no
external spritesheet, crop or palette-conversion step.

Design goals (see the task brief):
  * metallic industrial-panel / spacecraft-surface vocabulary in the broad
    1980s C64 tradition (Uridium / Paradroid / Parallax era) - NOT a copy of any
    specific tile from those games;
  * strong bas-relief: consistent top-left light, chunky 1-3 logical-pixel
    bands, no high-frequency dither mush;
  * built from a SMALL set of reusable 4x8 logical-cell components so the glyph
    deduplicator does real work (rich art, few unique character glyphs).

Lighting convention (four project palette roles):
  0  D021 background   - void / deep recess / gap between structures
  1  D022 mid          - the metal body / field of every panel
  2  D023 shadow       - bevels facing away from the light (bottom / right),
                         seam lines, recess interiors
  3  char highlight    - bevels facing the light (top / left), rivet gleam,
                         conduit crowns, hazard chevrons

Each logical pixel is physically DOUBLE WIDTH, so a 16x32 logical metatile reads
as a 32x32 physical tile; horizontal bands are therefore kept 1-2 logical px.
"""
from __future__ import annotations

from native_metatile import CHAR_H, CHAR_W, CHARS_PER_SIDE, validate_pixels

BG, MID, SHA, HI = 0, 1, 2, 3

# --------------------------------------------------------------------------
# Reusable 4x8 logical cells. Each is 8 rows of 4 pixels (top-left origin).
# --------------------------------------------------------------------------
_CELLS: dict[str, list[list[int]]] = {}


def _cell(name, rows):
    assert len(rows) == CHAR_H and all(len(r) == CHAR_W for r in rows), name
    _CELLS[name] = [list(r) for r in rows]


M = MID
_cell("PLATE", [[M, M, M, M]] * 8)

_cell("PLATE_RIVET", [                       # body with a lit rivet near the top-left
    [M, M, M, M], [M, HI, HI, M], [M, HI, SHA, M], [M, M, M, M],
    [M, M, M, M], [M, M, M, M], [M, M, M, M], [M, M, M, M]])

_cell("SCUFF", [                             # body with a couple of chunky scrapes
    [M, M, M, M], [M, SHA, SHA, M], [M, M, M, M], [M, M, M, M],
    [SHA, SHA, M, M], [M, M, M, M], [M, M, SHA, SHA], [M, M, M, M]])

_cell("EDGE_T", [                            # lit band along the top
    [HI, HI, HI, HI], [HI, HI, HI, HI], [M, M, M, M], [M, M, M, M],
    [M, M, M, M], [M, M, M, M], [M, M, M, M], [M, M, M, M]])

_cell("EDGE_B", [                            # shadow band along the bottom
    [M, M, M, M], [M, M, M, M], [M, M, M, M], [M, M, M, M],
    [M, M, M, M], [M, M, M, M], [SHA, SHA, SHA, SHA], [SHA, SHA, SHA, SHA]])

_cell("EDGE_L", [[HI, M, M, M]] * 8)         # lit column on the left
_cell("EDGE_R", [[M, M, M, SHA]] * 8)        # shadow column on the right

_cell("BEV_TL", [                            # raised corner: lit top + left
    [HI, HI, HI, HI], [HI, HI, HI, HI], [HI, M, M, M], [HI, M, M, M],
    [HI, M, M, M], [HI, M, M, M], [HI, M, M, M], [HI, M, M, M]])
_cell("BEV_TR", [
    [HI, HI, HI, HI], [HI, HI, HI, HI], [M, M, M, SHA], [M, M, M, SHA],
    [M, M, M, SHA], [M, M, M, SHA], [M, M, M, SHA], [M, M, M, SHA]])
_cell("BEV_BL", [
    [HI, M, M, M], [HI, M, M, M], [HI, M, M, M], [HI, M, M, M],
    [HI, M, M, M], [HI, M, M, M], [SHA, SHA, SHA, SHA], [SHA, SHA, SHA, SHA]])
_cell("BEV_BR", [
    [M, M, M, SHA], [M, M, M, SHA], [M, M, M, SHA], [M, M, M, SHA],
    [M, M, M, SHA], [M, M, M, SHA], [SHA, SHA, SHA, SHA], [SHA, SHA, SHA, SHA]])

_cell("REC_TL", [                            # recessed corner: shadow top + left
    [SHA, SHA, SHA, SHA], [SHA, SHA, SHA, SHA], [SHA, M, M, M], [SHA, M, M, M],
    [SHA, M, M, M], [SHA, M, M, M], [SHA, M, M, M], [SHA, M, M, M]])
_cell("REC_TR", [
    [SHA, SHA, SHA, SHA], [SHA, SHA, SHA, SHA], [M, M, M, HI], [M, M, M, HI],
    [M, M, M, HI], [M, M, M, HI], [M, M, M, HI], [M, M, M, HI]])
_cell("REC_BL", [
    [SHA, M, M, M], [SHA, M, M, M], [SHA, M, M, M], [SHA, M, M, M],
    [SHA, M, M, M], [SHA, M, M, M], [HI, HI, HI, HI], [HI, HI, HI, HI]])
_cell("REC_BR", [
    [M, M, M, HI], [M, M, M, HI], [M, M, M, HI], [M, M, M, HI],
    [M, M, M, HI], [M, M, M, HI], [HI, HI, HI, HI], [HI, HI, HI, HI]])

_cell("SEAM_H", [                            # horizontal seam through the middle
    [M, M, M, M], [M, M, M, M], [M, M, M, M], [HI, HI, HI, HI],
    [SHA, SHA, SHA, SHA], [M, M, M, M], [M, M, M, M], [M, M, M, M]])
_cell("SEAM_V", [[M, HI, SHA, M]] * 8)       # vertical seam through the middle

_cell("RIB", [[M, HI, SHA, M]] * 8)          # structural rib (same as SEAM_V, reused)
_CELLS["RIB"] = _CELLS["SEAM_V"]

_cell("RIB_WIDE", [                          # broad raised rib with rivet studs
    [M, HI, SHA, M], [M, HI, SHA, M], [M, HI, SHA, M], [M, HI, SHA, M],
    [HI, HI, SHA, SHA], [M, HI, SHA, M], [M, HI, SHA, M], [M, HI, SHA, M]])

_cell("VENT", [                              # louvred vent - stacked slats
    [SHA, SHA, SHA, SHA], [M, M, M, M], [HI, HI, HI, HI], [SHA, SHA, SHA, SHA],
    [M, M, M, M], [HI, HI, HI, HI], [SHA, SHA, SHA, SHA], [M, M, M, M]])

_cell("GRILLE", [                            # perforated grille - chunky 2-px holes
    [M, M, M, M], [SHA, BG, BG, SHA], [SHA, BG, BG, SHA], [M, M, M, M],
    [M, M, M, M], [SHA, BG, BG, SHA], [SHA, BG, BG, SHA], [M, M, M, M]])

_cell("CONDUIT_H", [                         # horizontal pipe (crown lit, belly dark)
    [BG, BG, BG, BG], [M, M, M, M], [HI, HI, HI, HI], [M, M, M, M],
    [M, M, M, M], [SHA, SHA, SHA, SHA], [M, M, M, M], [BG, BG, BG, BG]])
_cell("CONDUIT_V", [[BG, HI, SHA, BG]] * 8)  # vertical pipe

_cell("CONDUIT_BEND_TR", [                   # elbow: comes in from the left, exits up
    [BG, BG, BG, BG], [M, M, HI, M], [HI, HI, HI, SHA], [M, M, SHA, SHA],
    [M, M, HI, SHA], [SHA, SHA, HI, SHA], [M, M, HI, SHA], [BG, M, HI, SHA]])

_cell("HAZARD", [                            # warning chevrons (bright over void)
    [HI, BG, BG, HI], [BG, HI, HI, BG], [BG, BG, HI, HI], [HI, BG, BG, HI],
    [HI, HI, BG, BG], [BG, HI, HI, BG], [BG, BG, HI, HI], [HI, BG, BG, HI]])

_cell("BRACE_D", [                           # chunky raised diagonal brace, TL->BR
    [HI, HI, M, M], [HI, HI, M, M], [M, HI, HI, M], [M, HI, HI, M],
    [M, M, HI, HI], [M, M, HI, HI], [M, M, SHA, HI], [M, M, SHA, HI]])
_cell("BRACE_A", [                           # mirror, TR->BL
    [M, M, HI, HI], [M, M, HI, HI], [M, HI, HI, M], [M, HI, HI, M],
    [HI, HI, M, M], [HI, HI, M, M], [HI, SHA, M, M], [HI, SHA, M, M]])

_cell("PANEL_INNER", [                       # body with a faint inset frame
    [M, M, M, M], [M, SHA, SHA, M], [M, SHA, SHA, M], [M, M, M, M],
    [M, M, M, M], [M, HI, HI, M], [M, HI, HI, M], [M, M, M, M]])

_cell("VOID", [[BG, BG, BG, BG]] * 8)        # open gap / deep hole

_cell("PIT_WALL_L", [[BG, BG, HI, SHA]] * 8)   # left interior wall of a pit
_cell("PIT_WALL_R", [[SHA, HI, BG, BG]] * 8)   # right interior wall of a pit
_cell("PIT_LIP", [                              # rim: solid above, drop below
    [M, M, M, M], [M, M, M, M], [HI, HI, HI, HI], [SHA, SHA, SHA, SHA],
    [BG, BG, BG, BG], [BG, BG, BG, BG], [BG, BG, BG, BG], [BG, BG, BG, BG]])
_cell("PIT_FLOOR", [
    [BG, BG, BG, BG], [BG, BG, BG, BG], [BG, M, M, BG], [BG, M, M, BG],
    [BG, BG, BG, BG], [SHA, SHA, BG, BG], [SHA, SHA, M, M], [SHA, SHA, M, M]])

_cell("CORE_TL", [                           # bright landmark quadrant (glowing core)
    [BG, BG, SHA, SHA], [BG, SHA, HI, HI], [SHA, HI, HI, HI], [SHA, HI, HI, M],
    [SHA, HI, HI, M], [SHA, HI, M, M], [BG, SHA, M, M], [BG, BG, SHA, M]])
_cell("CORE_TR", [
    [SHA, SHA, BG, BG], [HI, HI, SHA, BG], [HI, HI, HI, SHA], [M, HI, HI, SHA],
    [M, HI, HI, SHA], [M, M, HI, SHA], [M, M, SHA, BG], [M, SHA, BG, BG]])
_cell("CORE_BL", [
    [BG, BG, SHA, M], [BG, SHA, M, M], [SHA, HI, M, M], [SHA, HI, HI, M],
    [SHA, HI, HI, M], [SHA, HI, HI, HI], [BG, SHA, HI, HI], [BG, BG, SHA, SHA]])
_cell("CORE_BR", [
    [M, SHA, BG, BG], [M, M, SHA, BG], [M, M, HI, SHA], [M, HI, HI, SHA],
    [M, HI, HI, SHA], [HI, HI, HI, SHA], [HI, HI, SHA, BG], [SHA, SHA, BG, BG]])


# --------------------------------------------------------------------------
# Metatiles: 4x4 arrangements of cells (row-major, reading order).
# --------------------------------------------------------------------------
def _mt(*cell_names):
    assert len(cell_names) == CHARS_PER_SIDE * CHARS_PER_SIDE
    grid = [[0] * (CHARS_PER_SIDE * CHAR_W) for _ in range(CHARS_PER_SIDE * CHAR_H)]
    for idx, cn in enumerate(cell_names):
        cr, cc = divmod(idx, CHARS_PER_SIDE)
        cell = _CELLS[cn]
        for y in range(CHAR_H):
            for x in range(CHAR_W):
                grid[cr * CHAR_H + y][cc * CHAR_W + x] = cell[y][x]
    return validate_pixels(grid)


def _rect(edge_tl, edge_t, edge_tr, edge_l, fill, edge_r, edge_bl, edge_b, edge_br):
    """A framed 4x4 panel: corners + edge runs + a 2x2 fill."""
    return _mt(edge_tl, edge_t, edge_t, edge_tr,
              edge_l, fill, fill, edge_r,
              edge_l, fill, fill, edge_r,
              edge_bl, edge_b, edge_b, edge_br)


_METATILES: list[tuple[str, list[list[int]]]] = [
    # --- plain / lightly detailed deck plating -------------------------------
    ("DECK_PLAIN",   _mt(*["PLATE"] * 16)),
    ("DECK_RIVET",   _mt("PLATE_RIVET", "PLATE", "PLATE", "PLATE_RIVET",
                         "PLATE", "PLATE", "PLATE", "PLATE",
                         "PLATE", "PLATE", "PLATE", "PLATE",
                         "PLATE_RIVET", "PLATE", "PLATE", "PLATE_RIVET")),
    ("DECK_SCUFFED", _mt("PLATE", "SCUFF", "PLATE", "PLATE",
                         "PLATE", "PLATE", "PLATE", "SCUFF",
                         "SCUFF", "PLATE", "PLATE", "PLATE",
                         "PLATE", "PLATE", "SCUFF", "PLATE")),
    ("DECK_PANEL",   _mt("PLATE", "PLATE", "PLATE", "PLATE",
                         "PLATE", "PANEL_INNER", "PANEL_INNER", "PLATE",
                         "PLATE", "PANEL_INNER", "PANEL_INNER", "PLATE",
                         "PLATE", "PLATE", "PLATE", "PLATE")),

    # --- raised / recessed armour panels ----------------------------------
    ("PLATE_RAISED",   _rect("BEV_TL", "EDGE_T", "BEV_TR",
                             "EDGE_L", "PLATE", "EDGE_R",
                             "BEV_BL", "EDGE_B", "BEV_BR")),
    ("PLATE_RECESSED", _rect("REC_TL", "EDGE_B", "REC_TR",
                             "EDGE_R", "PANEL_INNER", "EDGE_L",
                             "REC_BL", "EDGE_T", "REC_BR")),
    ("ARMOUR_PLATE",   _mt("BEV_TL", "EDGE_T", "EDGE_T", "BEV_TR",
                           "EDGE_L", "PLATE_RIVET", "PLATE_RIVET", "EDGE_R",
                           "EDGE_L", "PLATE_RIVET", "PLATE_RIVET", "EDGE_R",
                           "BEV_BL", "EDGE_B", "EDGE_B", "BEV_BR")),
    ("HATCH",          _mt("REC_TL", "EDGE_B", "EDGE_B", "REC_TR",
                           "EDGE_R", "SEAM_V", "SEAM_V", "EDGE_L",
                           "EDGE_R", "SEAM_V", "SEAM_V", "EDGE_L",
                           "REC_BL", "EDGE_T", "EDGE_T", "REC_BR")),

    # --- structural seams -----------------------------------------------
    ("SEAM_HORIZ",  _mt("PLATE", "PLATE", "PLATE", "PLATE",
                        "SEAM_H", "SEAM_H", "SEAM_H", "SEAM_H",
                        "PLATE", "PLATE", "PLATE", "PLATE",
                        "PLATE", "PLATE", "PLATE", "PLATE")),
    ("SEAM_VERT",   _mt("PLATE", "SEAM_V", "PLATE", "SEAM_V",
                        "PLATE", "SEAM_V", "PLATE", "SEAM_V",
                        "PLATE", "SEAM_V", "PLATE", "SEAM_V",
                        "PLATE", "SEAM_V", "PLATE", "SEAM_V")),
    ("SEAM_CROSS",  _mt("PLATE", "SEAM_V", "PLATE", "PLATE",
                        "SEAM_H", "SEAM_V", "SEAM_H", "SEAM_H",
                        "PLATE", "SEAM_V", "PLATE", "PLATE",
                        "PLATE", "SEAM_V", "PLATE", "PLATE")),

    # --- edges / walls ------------------------------------------------
    ("WALL_LEFT",   _mt("VOID", "BEV_TL", "EDGE_T", "PLATE",
                        "VOID", "EDGE_L", "PLATE", "PLATE",
                        "VOID", "EDGE_L", "PLATE", "PLATE",
                        "VOID", "BEV_BL", "EDGE_B", "PLATE")),
    ("WALL_RIGHT",  _mt("PLATE", "EDGE_T", "BEV_TR", "VOID",
                        "PLATE", "PLATE", "EDGE_R", "VOID",
                        "PLATE", "PLATE", "EDGE_R", "VOID",
                        "PLATE", "EDGE_B", "BEV_BR", "VOID")),
    ("WALL_TOP",    _mt("VOID", "VOID", "VOID", "VOID",
                        "BEV_TL", "EDGE_T", "EDGE_T", "BEV_TR",
                        "PLATE", "PLATE", "PLATE", "PLATE",
                        "PLATE", "PLATE", "PLATE", "PLATE")),
    ("WALL_BOTTOM", _mt("PLATE", "PLATE", "PLATE", "PLATE",
                        "PLATE", "PLATE", "PLATE", "PLATE",
                        "BEV_BL", "EDGE_B", "EDGE_B", "BEV_BR",
                        "VOID", "VOID", "VOID", "VOID")),
    ("CORNER_TL",   _mt("VOID", "VOID", "VOID", "VOID",
                        "VOID", "BEV_TL", "EDGE_T", "EDGE_T",
                        "VOID", "EDGE_L", "PLATE", "PLATE",
                        "VOID", "EDGE_L", "PLATE", "PLATE")),
    ("CORNER_BR",   _mt("PLATE", "PLATE", "EDGE_R", "VOID",
                        "PLATE", "PLATE", "EDGE_R", "VOID",
                        "EDGE_B", "EDGE_B", "BEV_BR", "VOID",
                        "VOID", "VOID", "VOID", "VOID")),

    # --- machinery: vents, grilles, ribs ---------------------------------
    ("VENT_BANK",   _mt(*["VENT"] * 16)),
    ("GRILLE_BANK", _mt(*["GRILLE"] * 16)),
    ("RIB_FIELD",   _mt("RIB_WIDE", "PLATE", "RIB_WIDE", "PLATE",
                        "RIB_WIDE", "PLATE", "RIB_WIDE", "PLATE",
                        "RIB_WIDE", "PLATE", "RIB_WIDE", "PLATE",
                        "RIB_WIDE", "PLATE", "RIB_WIDE", "PLATE")),
    ("MACHINE_A",   _mt("BEV_TL", "EDGE_T", "VENT", "BEV_TR",
                        "EDGE_L", "GRILLE", "VENT", "EDGE_R",
                        "EDGE_L", "RIB_WIDE", "PLATE_RIVET", "EDGE_R",
                        "BEV_BL", "EDGE_B", "EDGE_B", "BEV_BR")),
    ("MACHINE_B",   _mt("PLATE_RIVET", "SEAM_V", "VENT", "PLATE",
                        "SEAM_H", "SEAM_V", "GRILLE", "SEAM_H",
                        "PLATE", "SEAM_V", "RIB_WIDE", "PLATE_RIVET",
                        "PLATE", "SEAM_V", "PLATE", "PLATE")),

    # --- conduits ---------------------------------------------------
    ("CONDUIT_H",     _mt("PLATE", "PLATE", "PLATE", "PLATE",
                          "CONDUIT_H", "CONDUIT_H", "CONDUIT_H", "CONDUIT_H",
                          "CONDUIT_H", "CONDUIT_H", "CONDUIT_H", "CONDUIT_H",
                          "PLATE", "PLATE", "PLATE", "PLATE")),
    ("CONDUIT_V",     _mt("PLATE", "CONDUIT_V", "CONDUIT_V", "PLATE",
                          "PLATE", "CONDUIT_V", "CONDUIT_V", "PLATE",
                          "PLATE", "CONDUIT_V", "CONDUIT_V", "PLATE",
                          "PLATE", "CONDUIT_V", "CONDUIT_V", "PLATE")),
    ("CONDUIT_BEND",  _mt("PLATE", "CONDUIT_V", "CONDUIT_V", "PLATE",
                          "PLATE", "CONDUIT_V", "CONDUIT_V", "PLATE",
                          "CONDUIT_H", "CONDUIT_BEND_TR", "CONDUIT_V", "PLATE",
                          "CONDUIT_H", "CONDUIT_H", "PLATE", "PLATE")),

    # --- hazard / brace landmarks ------------------------------------
    ("HAZARD_BAND",   _mt("PLATE", "PLATE", "PLATE", "PLATE",
                          "EDGE_T", "EDGE_T", "EDGE_T", "EDGE_T",
                          "HAZARD", "HAZARD", "HAZARD", "HAZARD",
                          "EDGE_B", "EDGE_B", "EDGE_B", "EDGE_B")),
    ("BRACE_X",       _mt("BRACE_D", "PLATE", "PLATE", "BRACE_A",
                          "PLATE", "BRACE_D", "BRACE_A", "PLATE",
                          "PLATE", "BRACE_A", "BRACE_D", "PLATE",
                          "BRACE_A", "PLATE", "PLATE", "BRACE_D")),

    # --- open structure: pit / gap -------------------------------------
    ("PIT_MOUTH",   _mt("PLATE", "EDGE_B", "EDGE_B", "PLATE",
                        "PIT_WALL_L", "PIT_LIP", "PIT_LIP", "PIT_WALL_R",
                        "PIT_WALL_L", "VOID", "VOID", "PIT_WALL_R",
                        "PIT_WALL_L", "PIT_FLOOR", "PIT_FLOOR", "PIT_WALL_R")),
    ("GAP",         _mt("EDGE_R", "VOID", "VOID", "EDGE_L",
                        "EDGE_R", "VOID", "VOID", "EDGE_L",
                        "EDGE_R", "VOID", "VOID", "EDGE_L",
                        "EDGE_R", "VOID", "VOID", "EDGE_L")),

    # --- landmark: glowing reactor core -----------------------------
    ("CORE",        _mt("BEV_TL", "EDGE_T", "EDGE_T", "BEV_TR",
                        "EDGE_L", "CORE_TL", "CORE_TR", "EDGE_R",
                        "EDGE_L", "CORE_BL", "CORE_BR", "EDGE_R",
                        "BEV_BL", "EDGE_B", "EDGE_B", "BEV_BR")),
    ("DAMAGED",     _mt("PLATE", "SCUFF", "EDGE_R", "VOID",
                        "SCUFF", "PLATE_RIVET", "EDGE_R", "VOID",
                        "PLATE", "SCUFF", "PLATE", "SCUFF",
                        "SCUFF", "PLATE", "SCUFF", "PLATE")),
]


def metatiles():
    """[(name, native_pixels_16x32_0..3), ...] - deterministic order."""
    return [(name, [row[:] for row in px]) for name, px in _METATILES]


def names():
    return [name for name, _ in _METATILES]


# --------------------------------------------------------------------------
# Dev inspection: dedup stats + an ASCII contact sheet (no image deps).
# --------------------------------------------------------------------------
def dedup_stats():
    from native_metatile import pack_metatiles
    grids = [px for _, px in metatiles()]
    packed = pack_metatiles(grids)          # uses the real editor packer/deduper
    return len(grids), packed["glyphCount"], packed


def contact_sheet(cols=4):
    """Return a multi-line ASCII contact sheet. Each logical pixel is printed as
    TWO chars so the 2:1 VIC-II aspect reads correctly ( . : # for 0 1 2 3 )."""
    ramp = " .:#"
    tiles = metatiles()
    out = []
    for base in range(0, len(tiles), cols):
        chunk = tiles[base:base + cols]
        out.append("  ".join(f"{name:<32}" for name, _ in chunk))
        for y in range(32):
            line = []
            for _, px in chunk:
                line.append("".join(ramp[v] * 2 for v in px[y]))
            out.append("  ".join(line))
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    n, uniq, _ = dedup_stats()
    print(f"native terrain tiles: {n} metatiles -> {uniq} unique terrain glyphs after dedupe "
          f"(avg {uniq / n:.1f} glyph/metatile; naive would be {n * 16})")
    for nm, px in metatiles():
        v = {c for row in px for c in row}
        assert v <= {0, 1, 2, 3}, (nm, v)
        assert len(px) == 32 and all(len(r) == 16 for r in px), nm
    print("all metatiles valid 16x32, values 0..3")
    if "--sheet" in sys.argv:
        print()
        print(contact_sheet())
