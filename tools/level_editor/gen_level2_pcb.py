#!/usr/bin/env python3
"""EXPERIMENTAL Level 2 terrain: a printed circuit board, as a construction kit.

It writes one `level.v6.json` -- a valid formatVersion 6 project the editor can
open and paint with. Canonical Level 1 (levels/level1/, src/level1/) is never
read for content and never written.

THIS SCRIPT IS NO LONGER THE SOURCE OF TRUTH. levels/level2/level.v6.json was
promoted to the real Level 2 and is authored in the editor now, so regenerating
over it would throw away every edit made since. The generator refuses to write
to that path without --force and writes elsewhere by default. It is kept because
it documents how the PCB vocabulary was constructed, and because the
edge-contract checks it runs are still the clearest statement of the tile
contract.

    python3 tools/level_editor/gen_level2_pcb.py --out=/tmp/pcb
    python3 tools/level_editor/gen_level2_pcb.py --palette=blue --out=/tmp/pcb-blue


THE FOUR COLOURS ARE THE WHOLE PALETTE
--------------------------------------
Terrain colour RAM is written once at init and never again (src/terrain.asm), so
a level has exactly four colours for its entire surface and every terrain cell is
multicolour. The logical indices below are fixed by the VIC; the C64 colours they
are bound to are the only choice this file gets to make.

    0  G  substrate      $d021 = 5   GREEN        bare solder-mask board
    1  K  dark           $d022 = 0   BLACK        IC bodies, drill holes, shadow
    2  S  metal          $d023 = 15  LIGHT GREY   traces, solder, silkscreen
    3  Y  gold           cRAM  = 7   YELLOW       pads, vias, test points, pins

Substrate is the BACKGROUND, so a blank board cell costs one all-zero glyph and
the quiet parts of the map are free. Character colour is restricted to 0..7 by
the engine (bit 3 forces multicolour), and yellow is 7, so the gold is reachable.


ASPECT RATIO, WHICH DRIVES EVERY STROKE WIDTH
---------------------------------------------
A multicolour pixel is TWO screen pixels wide and ONE tall. So:

    a 2-px-wide vertical stroke   = 4 screen px across
    a 4-px-tall horizontal stroke = 4 screen px down

Those are the same apparent thickness. Every trace here is 2 native px wide when
vertical and 4 native rows tall when horizontal, and every round pad is twice as
tall as it is wide in native units so that it comes out circular on screen.


THE EDGE CONTRACT
-----------------
Composability is the point, so connection positions are fixed once, for the whole
kit, and no tile is drawn by eye.

A metatile is 16 native px across and 32 down. Traces may cross an edge ONLY in
these lanes, named in native coordinates:

    vertical lanes (cross the TOP and BOTTOM edges)
        VL  x 3..4      VC  x 7..8      VR  x 11..12
    horizontal lanes (cross the LEFT and RIGHT edges)
        HT  y 6..9      HC  y 14..17    HB  y 22..25

In SCREEN pixels those are the quarter, half and three-quarter points of the
metatile in both axes, and each lane set is its own mirror image (x -> 15-x maps
VL<->VR and fixes VC; y -> 31-y maps HT<->HB and fixes HC). Metatiles tile the
screen on exact 4-character boundaries, so a trace leaving one tile in lane VC
meets lane VC of its neighbour with no possible misalignment -- alignment is a
property of the lane table, not of the artwork.

VC and HC are the PRIMARY lanes and carry almost everything. VL/VR exist for
parallel buses; HT/HB exist for buses and for IC pin rows.

IC PINS SIT ON HT AND HB, never on HC. Two pins per metatile edge at a 16-row
pitch, which is the same pitch across a tile seam as within a tile, so a chip
body stacks to any height with evenly spaced legs. A horizontal trace arriving on
HC therefore does not hit a pin directly; FAN_R / FAN_L split HC into HT+HB for
exactly that reason, and BUS_H2 carries the pair.

Power traces are twice as thick and use their own centred lanes (VP / HP). They
are deliberately NOT interoperable with signal lanes: a power rail joins a signal
net through a pad, not by butting against it.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from native_metatile import NATIVE_W, NATIVE_H, pack_metatiles   # noqa: E402
from engine_data import TERRAIN_GLYPH_BASE                       # noqa: E402

W, H = NATIVE_W, NATIVE_H           # 16 x 32

G, K, S, Y = 0, 1, 2, 3             # logical indices; see module docstring

# THE SUBSTRATE COLOUR IS THE ONE REAL JUDGEMENT CALL IN THIS FILE.
#
# The brief asked for a green board, and C64 colour 5 is the only green that is
# not the pastel 13, so "green" is settled. But measured out of a real x64sc
# frame, colour 5 is (98, 213, 50) -- a vivid GRASS green, not the dark olive of
# solder mask, and large quiet areas of it read as a field rather than a board.
#
# The usual C64 answer is to dither it darker against black, and that does not
# work here: a multicolour pixel is TWO screen pixels wide, which is half the
# width of a trace, so the coarsest possible dither is as heavy as the artwork
# it sits behind. Every variant was rendered against the measured colours -- 1
# in 8, 1 in 4, 1 in 2, checkerboard, row stripes, column stripes -- and they
# read as corduroy or as scanlines, and the column stripes compete directly with
# the vertical traces that are the most important thing on the board. A
# checkerboard also could not be used even if it looked right: the stage scrolls
# one pixel per frame, so any pattern that varies down the screen alternates at
# every fixed screen point and flickers.
#
# So the substrate is FLAT, and "blue" is offered as a second palette because
# colour 6 reads more convincingly as a circuit board than colour 5 does. Green
# remains the default because green is what was asked for.
PALETTES = {
    "green": {"background": 5, "multicolour1": 0, "multicolour2": 15,
              "character": 7},
    "blue": {"background": 6, "multicolour1": 0, "multicolour2": 15,
             "character": 7},
}
PALETTE = PALETTES["green"]

# ---- the edge contract, as data -------------------------------------------
VL, VC, VR = (3, 4), (7, 8), (11, 12)
HT, HC, HB = (6, 9), (14, 17), (22, 25)
VP, HP = (6, 9), (12, 19)           # power rails: 8 screen px in both axes

MAP_COLS = 10


# ---------------------------------------------------------------------------
# a very small pixel DSL
# ---------------------------------------------------------------------------
def blank(v=G):
    return [[v] * W for _ in range(H)]


def box(g, x0, y0, x1, y1, v):
    """Inclusive rectangle, clipped to the tile."""
    for y in range(max(0, y0), min(H - 1, y1) + 1):
        row = g[y]
        for x in range(max(0, x0), min(W - 1, x1) + 1):
            row[x] = v


def vseg(g, lane, y0, y1, v=S):
    box(g, lane[0], y0, lane[1], y1, v)


def hseg(g, lane, x0, x1, v=S):
    box(g, x0, lane[0], x1, lane[1], v)


def ellipse(g, cx, cy, rx, ry, v):
    """Filled ellipse on half-pixel centres, so an even diameter is symmetric.

    rx/ry are in NATIVE units; pass ry = 2*rx for a circle on screen.
    """
    for y in range(H):
        for x in range(W):
            dx = (x + 0.5 - cx) / rx
            dy = (y + 0.5 - cy) / ry
            if dx * dx + dy * dy <= 1.0:
                g[y][x] = v


def pad(g, cx, cy, v=Y, rx=2.0, ry=4.0):
    """A round solder pad: 4 native px across, 8 down -> 8x8 screen px."""
    ellipse(g, cx, cy, rx, ry, v)


def via(g, cx, cy, rx=2.5, ry=5.0):
    """A plated through-hole: GOLD annulus, black drill.

    The annulus was silver in the first draft and it did not work: silver is
    also the trace colour, so on the traces where vias actually belong the ring
    vanished and all that was left was the black drill -- which at this size
    renders as a small cross. Gold is the only one of the four colours that
    separates a via from the trace it interrupts.
    """
    ellipse(g, cx, cy, rx, ry, Y)
    ellipse(g, cx, cy, rx / 2.0, ry / 2.0, K)


# THE GLYPH ECONOMY, and it is the reason this kit fits at all.
#
# A character cell is 4 native px across and 8 down -- which is EXACTLY the size
# of a round solder pad at this scale. A pad drawn on a character boundary is
# therefore one glyph, and the same one however many times it appears; the first
# draft of this file drew pads at arbitrary centres and needed 187 glyphs for 54
# metatiles against a namespace of 128. Char-aligning the pad, via, test point
# and every component body brought that to well under budget with no loss of
# artwork -- the four-pad cluster and the four-via field each cost ONE glyph.
#
# Detail that sits ON a trace is the deliberate exception: a via has to be
# centred on the lane it interrupts, the lanes are centred on the metatile, and
# the metatile centre is a character boundary. Those pay two to four glyphs
# each, knowingly, because a via nudged sideways to save a glyph would break the
# edge contract that the rest of the kit is built on.
CHAR_W, CHAR_H = 4, 8


def _char_centre(cc, cr):
    return cc * CHAR_W + CHAR_W / 2.0, cr * CHAR_H + CHAR_H / 2.0


def cpad(g, cc, cr, v=Y, rx=2.0, ry=4.0):
    """A round pad filling character cell (cc, cr). One glyph, always."""
    cx, cy = _char_centre(cc, cr)
    ellipse(g, cx, cy, rx, ry, v)


def cvia(g, cc, cr, rx=2.0, ry=4.0):
    """A plated through-hole filling character cell (cc, cr). One glyph."""
    cx, cy = _char_centre(cc, cr)
    ellipse(g, cx, cy, rx, ry, Y)
    ellipse(g, cx, cy, rx / 2.0, ry / 2.0, K)


# A pad that fills its character cell exactly reaches the cell's edge, which on
# an outer cell is the METATILE's edge -- so a free-standing pad cluster would
# put metal on an edge in no lane at all and meet bare board in its neighbour.
# The free-standing detail tiles therefore use a slightly inset pad, which costs
# one extra glyph and keeps every scattered pad legal wherever it is placed.
FREE_RX, FREE_RY = 1.5, 3.5


def ctest(g, cc, cr, v=Y):
    """A SQUARE test point in character cell (cc, cr), with a stub. One glyph."""
    x0, y0 = cc * CHAR_W, cr * CHAR_H
    box(g, x0, y0 + 1, x0 + 3, y0 + 6, v)
    box(g, x0 + 1, y0 + 7, x0 + 2, y0 + 7, S)


def mirror_x(g):
    return [list(reversed(row)) for row in g]


def mirror_y(g):
    return [list(row) for row in reversed(g)]


# ---------------------------------------------------------------------------
# the tile vocabulary
# ---------------------------------------------------------------------------
TILES = []                           # [(name, grid)] -- index is the metatile ID
BY_NAME = {}


def tile(name, grid):
    if name in BY_NAME:
        raise SystemExit(f"duplicate metatile name {name!r}")
    BY_NAME[name] = len(TILES)
    TILES.append((name, grid))
    return grid


def build_tiles():
    # -- substrate: the quiet majority of the board ------------------------
    # BOARD must be metatile 0 and must be genuinely empty. It is the
    # breathing room, and it is also the cheapest tile in the set: sixteen
    # references to a single all-zero glyph.
    tile("BOARD", blank())

    g = blank()                      # a barely-there silkscreen speck
    box(g, 12, 2, 14, 2, S)
    box(g, 13, 3, 13, 6, S)
    box(g, 1, 19, 3, 19, S)
    tile("BOARD_SPECK", g)

    # Silkscreen: a dashed component outline. Deliberately confined to two
    # character rows -- a fuller reference designator was drawn first and cost
    # eight glyphs, which is a DIP's worth of budget for decoration.
    g = blank()
    for x0 in (2, 6, 10):
        box(g, x0, 12, x0 + 2, 12, S)
        box(g, x0, 19, x0 + 2, 19, S)
    box(g, 2, 12, 2, 19, S)
    box(g, 13, 12, 13, 19, S)
    tile("SILK_MARK", g)

    g = blank()                      # a board mounting hole, on chars c1..c2/r1..r2
    ellipse(g, 8.0, 16.0, 4.0, 8.0, S)
    ellipse(g, 8.0, 16.0, 2.2, 4.4, K)
    tile("MOUNT_HOLE", g)

    # -- signal traces: the core of the kit --------------------------------
    g = blank(); vseg(g, VC, 0, 31);                     tile("TRACE_V", g)
    g = blank(); hseg(g, HC, 0, 15);                     tile("TRACE_H", g)

    # Corners. Each is one vertical run to the elbow plus one horizontal run
    # from it, so the elbow block is exactly the lane intersection and the two
    # arms are guaranteed to be the same weight.
    g = blank(); vseg(g, VC, 0, HC[1]); hseg(g, HC, VC[0], 15)
    tile("TRACE_NE", g)
    tile("TRACE_NW", mirror_x(BY_GRID("TRACE_NE")))
    tile("TRACE_SE", mirror_y(BY_GRID("TRACE_NE")))
    tile("TRACE_SW", mirror_x(BY_GRID("TRACE_SE")))

    # Tees and the crossroads.
    g = blank(); vseg(g, VC, 0, 31); hseg(g, HC, VC[0], 15)
    tile("TRACE_TE", g)
    tile("TRACE_TW", mirror_x(BY_GRID("TRACE_TE")))
    g = blank(); hseg(g, HC, 0, 15); vseg(g, VC, 0, HC[1])
    tile("TRACE_TN", g)
    tile("TRACE_TS", mirror_y(BY_GRID("TRACE_TN")))
    g = blank(); vseg(g, VC, 0, 31); hseg(g, HC, 0, 15)
    tile("TRACE_X", g)

    # Detail ON a through trace, so it can be dropped anywhere in a run. These
    # are the deliberate glyph-economy exception: centred on the lane, which is
    # centred on the metatile, which is a character boundary.
    g = blank(); vseg(g, VC, 0, 31); via(g, 7.5, 15.5)
    tile("TRACE_V_VIA", g)
    g = blank(); hseg(g, HC, 0, 15); via(g, 7.5, 15.5)
    tile("TRACE_H_VIA", g)

    # Terminations: a run that stops in a pad rather than at an edge.
    g = blank(); vseg(g, VC, 0, 17); pad(g, 7.5, 20.0, rx=2.5, ry=5.0)
    tile("TRACE_END_N", g)
    tile("TRACE_END_S", mirror_y(BY_GRID("TRACE_END_N")))
    # THERE IS NO HORIZONTAL TERMINATION TILE. A dead-ending horizontal run cost
    # ten glyphs for something a real board rarely has -- a horizontal trace
    # turns at a corner far more often than it simply stops -- so horizontal
    # runs in this kit always end at a corner, a tee or a component.

    # -- buses -------------------------------------------------------------
    g = blank(); vseg(g, VL, 0, 31); vseg(g, VC, 0, 31); vseg(g, VR, 0, 31)
    tile("BUS_V3", g)
    # ONE via, on the centre lane. Three staggered vias were drawn first and
    # cost seven glyphs against a namespace of 128; one costs four and the bus
    # still reads as a bus that has been broken out somewhere along its run.
    g = blank(); vseg(g, VL, 0, 31); vseg(g, VC, 0, 31); vseg(g, VR, 0, 31)
    via(g, 7.5, 15.5, rx=1.75, ry=3.5)
    tile("BUS_V3_VIA", g)

    # A BUS HAS TO BE ABLE TO STOP. Three pads side by side would touch -- the
    # lanes are only four native pixels apart -- so the three lanes break off at
    # different heights and each ends in its own pad. That is also how a real
    # bus is broken out, and it costs nothing extra to be right about it.
    g = blank()
    for lane, cx, end in ((VL, 3.5, 5), (VC, 7.5, 13), (VR, 11.5, 21)):
        vseg(g, lane, 0, end)
        pad(g, cx, end + 3.0, rx=2.0, ry=4.0)
    tile("BUS_V3_END_N", g)
    tile("BUS_V3_END_S", mirror_y(BY_GRID("BUS_V3_END_N")))
    g = blank(); hseg(g, HT, 0, 15); hseg(g, HB, 0, 15)
    tile("BUS_H2", g)

    # HC in on the left, HT+HB out on the right: the only legal way to reach
    # an IC pin row from a centre-lane trace.
    g = blank()
    hseg(g, HC, 0, VC[1])
    box(g, VC[0], HT[0], VC[1], HB[1], S)
    hseg(g, HT, VC[0], 15); hseg(g, HB, VC[0], 15)
    tile("FAN_R", g)
    tile("FAN_L", mirror_x(BY_GRID("FAN_R")))

    # -- power rails -------------------------------------------------------
    g = blank(); vseg(g, VP, 0, 31); tile("POWER_V", g)
    g = blank(); hseg(g, HP, 0, 15); tile("POWER_H", g)
    g = blank(); vseg(g, VP, 0, HP[1]); hseg(g, HP, VP[0], 15)
    tile("POWER_NE", g)
    tile("POWER_SE", mirror_y(BY_GRID("POWER_NE")))
    g = blank(); vseg(g, VP, 0, 31); pad(g, 7.5, 15.5, rx=2.5, ry=5.0)
    tile("POWER_V_PAD", g)

    # -- the DIP: end caps + a repeatable body, two metatiles wide ---------
    # Body fills x4..15 on the left half and x0..11 on the right, so the two
    # halves meet with no seam. Legs are on HT and HB and reach the outer edge,
    # so a BUS_H2 butted against the chip lands on them exactly.
    def dip_left(top=False, bot=False, pin1=False):
        g = blank()
        y0, y1 = (4 if top else 0), (27 if bot else 31)
        box(g, 4, y0, 15, y1, K)
        if top:
            box(g, 4, y0, 15, y0 + 1, S)         # silkscreen body outline
        if bot:
            box(g, 4, y1 - 1, 15, y1, S)
        # EVERY tile of the chip carries BOTH legs, end caps included. The first
        # version dropped the leg nearest each cap so the package would not have
        # a pin flush with its end, and that made the three tiles disagree about
        # which lanes they use -- which in turn meant a bus could not simply run
        # down beside the chip and feed every pin. Uniform legs cost one row of
        # realism and buy the composability the kit exists for. The pitch is 16
        # rows everywhere, inside a tile and across every seam.
        hseg(g, HT, 0, 4)
        hseg(g, HB, 0, 4)
        if pin1:
            cpad(g, 1, 1)                        # pin-1 marker, char-aligned
        return g

    # A DIP carries EXACTLY ONE pin-1 marker, so the right-hand halves are
    # mirrors of a marker-less left half rather than of the tile that has it.
    # Mirroring the marker too is the obvious version of this code and it is
    # wrong: it produces a chip that is keyed at both ends.
    tile("DIP_TOP_L", dip_left(top=True, pin1=True))
    tile("DIP_MID_L", dip_left())
    tile("DIP_BOT_L", dip_left(bot=True))
    tile("DIP_TOP_R", mirror_x(dip_left(top=True)))
    tile("DIP_MID_R", mirror_x(BY_GRID("DIP_MID_L")))
    tile("DIP_BOT_R", mirror_x(BY_GRID("DIP_BOT_L")))

    # -- a single-tile SMD package ----------------------------------------
    # Deliberately built from the DIP's own body and leg geometry so that all
    # four of its edge characters are glyphs the DIP already paid for: only the
    # two end caps are new. Same pin lanes, so it drops into the same routing.
    g = blank()
    box(g, 4, 2, 11, 29, K)
    box(g, 4, 2, 11, 3, S)
    box(g, 4, 28, 11, 29, S)
    hseg(g, HT, 0, 4); hseg(g, HB, 0, 4)
    hseg(g, HT, 11, 15); hseg(g, HB, 11, 15)
    tile("SMD_IC", g)

    # -- passives ----------------------------------------------------------
    # Every body is confined to characters c1..c2, so leads fall in c0/c3 where
    # they reuse the plain TRACE_V / TRACE_H glyphs exactly.
    # A COMPONENT BODY NEEDS A DARK OUTLINE. The first draft drew the resistor
    # body in silver, which is also the lead colour, so the body dissolved into
    # its own leads and only the colour bands were visible. Every body here is
    # therefore ringed in black before it is filled.
    g = blank()                                   # axial resistor, vertical
    vseg(g, VC, 0, 7); vseg(g, VC, 24, 31)
    ellipse(g, 8.0, 16.0, 4.0, 8.0, K)
    ellipse(g, 8.0, 16.0, 3.0, 6.5, S)
    box(g, 5, 11, 10, 12, K)
    box(g, 5, 15, 10, 16, Y)
    box(g, 5, 19, 10, 20, K)
    tile("RES_V", g)

    g = blank()                                   # axial resistor, horizontal
    hseg(g, HC, 0, 3); hseg(g, HC, 12, 15)
    ellipse(g, 8.0, 16.0, 4.0, 6.5, K)
    ellipse(g, 8.0, 16.0, 3.0, 5.0, S)
    box(g, 6, 12, 6, 19, K)
    box(g, 7, 12, 8, 19, Y)
    box(g, 9, 12, 9, 19, K)
    tile("RES_H", g)

    g = blank()                                   # electrolytic can
    vseg(g, VC, 0, 7); vseg(g, VC, 24, 31)
    ellipse(g, 8.0, 16.0, 4.0, 11.0, S)
    ellipse(g, 8.0, 16.0, 3.0, 9.0, K)
    for y in range(H):                            # the polarity stripe is a
        for x in range(W):                        # STRIPE, not half the can
            if g[y][x] == K and x <= 6:
                g[y][x] = Y
    tile("CAP_ELEC", g)

    # INLINE on a normal vertical trace, exactly like the resistor. The first
    # version straddled a two-lane bus, which was prettier and unusable: that
    # bus had no terminator tile, so there was no legal way to start or stop the
    # run the capacitor sat on. Composability beat the nicer drawing.
    g = blank()                                   # ceramic decoupling capacitor
    vseg(g, VC, 0, 9); vseg(g, VC, 22, 31)
    ellipse(g, 8.0, 16.0, 4.0, 6.5, S)
    ellipse(g, 8.0, 16.0, 3.0, 5.0, Y)
    tile("CAP_CER", g)

    # -- connectors --------------------------------------------------------
    # The shroud runs the full width so its two side characters are constant
    # down the strip, and the gold pins are char-aligned: the whole repeatable
    # body is four glyphs. Pins sit on character rows 0 and 2, an 8-row gap
    # within a tile and the same 8-row gap across a tile seam.
    # The shroud walls sit at x1 and x14, INSIDE the tile, not on its edges: a
    # silver wall on the tile edge butts straight against bare board when the
    # strip ends sideways. Keeping them inboard costs nothing -- those two
    # character columns are still constant down the whole tile, so still one
    # glyph each.
    def header(top=False, bot=False):
        g = blank()
        y0, y1 = (3 if top else 0), (28 if bot else 31)
        box(g, 1, y0, 14, y1, K)
        box(g, 1, y0, 1, y1, S)
        box(g, 14, y0, 14, y1, S)
        for cc in (1, 2):
            for cr in (0, 2):
                cpad(g, cc, cr)
        if top:
            box(g, 0, 0, 15, y0 - 1, G)           # re-clear above the end cap
            box(g, 1, y0, 14, y0, S)
        if bot:
            box(g, 0, y1 + 1, 15, 31, G)
            box(g, 1, y1, 14, y1, S)
        return g

    tile("HEADER", header())
    tile("HEADER_N", header(top=True))
    tile("HEADER_S", header(bot=True))

    g = blank()                                   # gold edge fingers
    box(g, 0, 0, 15, 3, S)
    for cc in range(4):
        box(g, cc * 4, 4, cc * 4 + 2, 31, Y)
    tile("EDGE_FINGERS", g)

    # -- pads, vias and test points, as standalone detail ------------------
    # One glyph each, however many are on the tile.
    g = blank()
    for cc, cr in ((1, 0), (2, 1), (0, 2), (2, 3)):
        cpad(g, cc, cr, rx=FREE_RX, ry=FREE_RY)
    tile("PAD_CLUSTER", g)

    g = blank()
    for cc, cr in ((0, 0), (2, 1), (1, 2), (3, 3)):
        cvia(g, cc, cr, rx=FREE_RX, ry=FREE_RY)
    tile("VIA_FIELD", g)

    g = blank()
    ctest(g, 1, 1); ctest(g, 2, 2)
    tile("TESTPT_PAIR", g)


def BY_GRID(name):
    return TILES[BY_NAME[name]][1]


# ---------------------------------------------------------------------------
# the showcase map
# ---------------------------------------------------------------------------
# One letter per metatile, ten per row. Authored TOP-DOWN in the order the
# player meets it: row 0 is world row 0, the start of the stage.
LEGEND = {
    ".": "BOARD",        ",": "BOARD_SPECK",  "'": "SILK_MARK",   "o": "MOUNT_HOLE",
    "|": "TRACE_V",      "-": "TRACE_H",
    "r": "TRACE_NE",     "q": "TRACE_NW",     "b": "TRACE_SE",    "d": "TRACE_SW",
    "]": "TRACE_TE",     "[": "TRACE_TW",     "T": "TRACE_TN",    "t": "TRACE_TS",
    "+": "TRACE_X",
    "v": "TRACE_V_VIA",  "h": "TRACE_H_VIA",
    "^": "TRACE_END_N",  "u": "TRACE_END_S",
    "<": "TRACE_END_W",  ">": "TRACE_END_E",
    "B": "BUS_V3",       "V": "BUS_V3_VIA",   "=": "BUS_H2",
    "Y": "BUS_V3_END_N", "L": "BUS_V3_END_S",
    ")": "FAN_R",        "(": "FAN_L",
    "P": "POWER_V",      "H": "POWER_H",
    "1": "POWER_NE",     "3": "POWER_SE",     "@": "POWER_V_PAD",
    "A": "DIP_TOP_L",    "a": "DIP_TOP_R",
    "M": "DIP_MID_L",    "m": "DIP_MID_R",
    "Z": "DIP_BOT_L",    "z": "DIP_BOT_R",
    "S": "SMD_IC",
    "R": "RES_V",        "e": "RES_H",        "C": "CAP_ELEC",    "c": "CAP_CER",
    "J": "HEADER",       "N": "HEADER_N",     "U": "HEADER_S",
    "F": "EDGE_FINGERS",
    "*": "PAD_CLUSTER",  ":": "VIA_FIELD",    "x": "TESTPT_PAIR",
}

SHOWCASE = """
..........
.u.u..u.u.
.|.|..|.|.
.v.|..|.v.
.|.v..v.|.
.]-+--+-[.
.|.|..|.|.
,|.|..|.|,
.|.v..v.|.
.|.|..|.|.
.]-+-h+-[.
.|.|..|.|.
.|.|,.|.|.
.v.|..|.v.
.|.|..|.|.
.|bq..rd|.
.||....||.
.||.,..||.
.|])Aa([|.
.||.Mm.||.
.|])Mm([|.
.||.Mm.||.
.|])Mm([|.
.||.Mm.||.
.||.Zz.||.
.||....||.
.|v.'..v|.
.||....||.
.|rd..bq|.
.|.|..|.|.
.|.|,.|.|.
.|.|L.|.|.
.|.|B.|.|.
.v.|B.|.v.
.|.|B.|.|.
.|.vB.v.|.
.|.|V.|.|.
.|.|B.|.|.
.v.|B.|.v.
.|.|B.|.|.
.|.|Y.|.|.
.|.|..|.|.
.]-+--+-[.
.|.|..|.|.
.|.|,.|.|.
.v.|..|.v.
.|.|..|.|.
.^.^..^.^.
..........
.3HHHHHHHH
.P..o..,..
.P........
.@...:....
.P..,...'.
.P........
.P.*...o..
.1HHHHHHHH
..........
....,.....
.u.u..u.u.
.|.|..|.|.
.R.|..|.C.
.|.v..v.|.
.|.|..|.|.
.]-+-e+-[.
.|.|..|.|.
.c.|,.|.R.
.|.|..|.|.
.v.|..|.v.
.|.C..c.|.
.|.|..|.|.
.]-+--+-[.
.|.|..|.|.
.^.|..|.^.
...|..|...
..'|..|.,.
...|..|...
.u.|..|.u.
.|.|..|.|.
.]-+--+-[.
.|.|..|.|.
.|.|,.|.|.
.v.|..|.v.
.]-+--T-[.
.|.|....|.
.|.])=S.|.
.|.|....|.
.|.|..u.|.
.|.|,.|.|.
.v.|..|.v.
.|.|..|.|.
.]-+--+-[.
.|.N..|.|.
.|.J..|.|.
.|.J,.|.|.
.|.J..|.|.
.|.J..|.|.
.|.U..|.|.
.|....|.|.
.v.:..v.|.
.|....|.|.
.^.,..^.^.
..........
..x....,..
..........
.u.u.u.u..
.|.|.|.|..
.]-+-+-[..
.|.|.|.|..
.v.|.v.|..
.|.v.|.v..
.]-+-+-[..
.|.|.|.|..
.|.|,|.|..
.v.|.v.|..
.|.|.|.|..
.^.|.^.|..
...|...|..
..,^..o^..
..........
.u......u.
.|..o...|.
.v......v.
.|...,..|.
.]--t---[.
.|..|...|.
.|..v.*.|.
.v..|...v.
.|..^...|.
.^......^.
..........
....'.....
..........
FFFFFFFFFF
..........
..,....,..
....x.....
..........
"""


# ---------------------------------------------------------------------------
# the edge contract, checked by machine
# ---------------------------------------------------------------------------
# "Do not eyeball every tile independently." These two checks are what makes
# that possible. The first says every tile obeys the lane table; the second says
# every join the showcase map actually paints is electrically sensible.
METAL = (S, Y)

H_LANES = (HT, HC, HB, HP)          # may cross the LEFT and RIGHT edges
V_LANES = (VL, VC, VR, VP)          # may cross the TOP and BOTTOM edges


def _rows_of(grid, x):
    return frozenset(y for y in range(H) if grid[y][x] in METAL)


def _cols_of(grid, y):
    return frozenset(x for x in range(W) if grid[y][x] in METAL)


def _in_lanes(values, lanes):
    """`values` is exactly a union of WHOLE lane spans.

    Widest lane first, because the power lanes contain the signal lanes: VP is
    columns 6..9 and VC is 7..8, so a plain vertical trace must be matched
    against VC and a power rail against VP, and testing VP first against a
    signal trace would wrongly reject it.
    """
    remaining = set(values)
    for lo, hi in sorted(lanes, key=lambda l: l[0] - l[1]):
        span = set(range(lo, hi + 1))
        if span <= remaining:
            remaining -= span
    return not remaining


# THE SECOND KIND OF EDGE, and it is not a fault.
#
# Lanes are for CONDUCTORS. Some tiles instead join by BODY: the left half of a
# DIP meets its right half along a continuous black package, a header shroud
# runs on down the strip, and a bank of edge fingers is an areal pattern that
# repeats every four native pixels and so continues across a tile boundary by
# construction. Those edges carry metal that is deliberately not in any lane,
# and they are exempted BY NAME rather than by weakening the rule for
# everything -- the leg edges of the very same chip tiles are still checked, and
# they are the joins that matter most.
#
# The outer edges of a chip carry the third kind of edge: PIN TERMINALS. A pin
# is allowed to end in bare board -- real boards are full of pins that connect
# to nothing -- whereas a trace that stops dead is a hole in the artwork. So pin
# edges are exempt from the continuity requirement while still being on the
# standard HT/HB lanes, which is what lets a bus feed them when one is there.
LANE_EXEMPT = {}                 # edges that are body, not conductor
for _n in ("DIP_TOP_L", "DIP_MID_L", "DIP_BOT_L"):
    LANE_EXEMPT[_n] = {"right"}
for _n in ("DIP_TOP_R", "DIP_MID_R", "DIP_BOT_R"):
    LANE_EXEMPT[_n] = {"left"}
for _n in ("HEADER", "HEADER_N", "HEADER_S", "EDGE_FINGERS"):
    LANE_EXEMPT[_n] = {"left", "right", "top", "bottom"}

JOIN_EXEMPT = dict(LANE_EXEMPT)  # + pin terminals, which may end in bare board
for _n in ("DIP_TOP_L", "DIP_MID_L", "DIP_BOT_L"):
    JOIN_EXEMPT[_n] = {"right", "left"}
for _n in ("DIP_TOP_R", "DIP_MID_R", "DIP_BOT_R"):
    JOIN_EXEMPT[_n] = {"left", "right"}
JOIN_EXEMPT["SMD_IC"] = {"left", "right"}


def _lane_exempt(name, edge):
    return edge in LANE_EXEMPT.get(name, ())


def _join_exempt(name, edge):
    return edge in JOIN_EXEMPT.get(name, ())


def check_lane_discipline():
    """No tile may put metal on an edge anywhere but in a declared lane."""
    bad = []
    for name, g in TILES:
        for edge, values, lanes in (
                ("left", _rows_of(g, 0), H_LANES),
                ("right", _rows_of(g, W - 1), H_LANES),
                ("top", _cols_of(g, 0), V_LANES),
                ("bottom", _cols_of(g, H - 1), V_LANES)):
            if _lane_exempt(name, edge):
                continue
            if values and not _in_lanes(values, lanes):
                bad.append(f"{name}: {edge} edge metal {sorted(values)} "
                           f"is not a whole declared lane")
    return bad


def check_map_continuity(rows):
    """Every trace leaving a metatile must be met by one entering its neighbour.

    A mismatch is a visible break in the artwork -- a trace that stops dead in
    bare board, or two traces that half-overlap -- and is reported with the map
    coordinate so it can be fixed in the showcase rather than argued about.
    """
    grids = [g for _, g in TILES]
    names = [n for n, _ in TILES]
    bad = []
    for r, row in enumerate(rows):
        for c, mid in enumerate(row):
            if c + 1 < len(row):
                nb = row[c + 1]
                if not (_join_exempt(names[mid], "right")
                        or _join_exempt(names[nb], "left")):
                    ra, rb = _rows_of(grids[mid], W - 1), _rows_of(grids[nb], 0)
                    if ra != rb:
                        bad.append(f"r{r} c{c} {names[mid]}|{names[nb]}: "
                                   f"right {sorted(ra)} vs left {sorted(rb)}")
            if r + 1 < len(rows):
                nb = rows[r + 1][c]
                if not (_join_exempt(names[mid], "bottom")
                        or _join_exempt(names[nb], "top")):
                    ca, cb = _cols_of(grids[mid], H - 1), _cols_of(grids[nb], 0)
                    if ca != cb:
                        bad.append(f"r{r} c{c} {names[mid]}/{names[nb]}: "
                                   f"bottom {sorted(ca)} vs top {sorted(cb)}")
    return bad


def build_map():
    rows = []
    for line in SHOWCASE.strip("\n").splitlines():
        line = line.rstrip()
        if not line:
            continue
        if len(line) != MAP_COLS:
            raise SystemExit(f"map row {len(rows)} is {len(line)} wide, not {MAP_COLS}: {line!r}")
        row = []
        for ch in line:
            name = LEGEND.get(ch)
            if name is None:
                raise SystemExit(f"map row {len(rows)}: no legend entry for {ch!r}")
            if name not in BY_NAME:
                raise SystemExit(f"legend {ch!r} names unknown metatile {name!r}")
            row.append(BY_NAME[name])
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
def main():
    palette_name, out_dir, force = "green", None, False
    for arg in sys.argv[1:]:
        if arg.startswith("--palette="):
            palette_name = arg.split("=", 1)[1]
        elif arg.startswith("--out="):
            out_dir = arg.split("=", 1)[1]
        elif arg == "--force":
            force = True
        else:
            raise SystemExit(f"unknown argument {arg!r}")
    if palette_name not in PALETTES:
        raise SystemExit(f"--palette must be one of {sorted(PALETTES)}")

    build_tiles()
    rows = build_map()

    lane_faults = check_lane_discipline()
    for f in lane_faults:
        print(f"  LANE FAULT  {f}")
    joins = check_map_continuity(rows)
    for f in joins[:40]:
        print(f"  OPEN JOIN   {f}")
    if len(joins) > 40:
        print(f"  ... and {len(joins) - 40} more open joins")

    packed = pack_metatiles([g for _, g in TILES])
    glyph_count = packed["glyphCount"]
    # The exporter requires a multiple of eight (export_v6.py), so the charset
    # is padded with blank glyphs rather than the tile set being padded with art
    # nobody asked for.
    padded = list(packed["glyphs"])
    while len(padded) % 8:
        padded.append([0] * 8)

    # Encounters are carried from Level 1 VERBATIM and are not part of this
    # experiment: the point is to fly the real ship past real sprites over the
    # new terrain and judge readability. Triggers past the end of this shorter
    # stage are dropped rather than moved.
    l1 = json.loads((HERE / "levels" / "level1" / "level.v6.json").read_text())
    metatile_rows = len(rows)
    world_rows = metatile_rows * 4
    triggers = [copy.deepcopy(t) for t in l1["triggers"]
                if t["worldProgress"] < world_rows - 120]

    suffix = "" if palette_name == "green" else f"-{palette_name}"
    project = {
        "formatVersion": 6,
        "name": f"level2pcb{suffix}",
        "stage": {"metatileRows": metatile_rows,
                  "metatileCols": MAP_COLS,
                  "noSpawnRow": world_rows - 200},
        "palette": dict(PALETTES[palette_name]),
        "glyphs": {"count": len(padded), "bitmaps": padded},
        "metatileDefs": packed["metatileDefs"],
        "map": rows,
        "turrets": [],
        "movementPrograms": copy.deepcopy(l1["movementPrograms"]),
        "waveDefinitions": copy.deepcopy(l1["waveDefinitions"]),
        "triggers": triggers,
        "levelMetatileSet": [
            {"name": name,
             "native": {"width": W, "height": H,
                        "pixels": ["".join(str(v) for v in r) for r in grid]},
             "source": None}
            for name, grid in TILES],
    }

    # THIS SCRIPT IS NO LONGER THE SOURCE OF TRUTH. levels/level2/ was promoted
    # to the real Level 2 and is authored in the editor now, so regenerating
    # over it would discard every edit made since -- the same ownership trap
    # build_levels.py describes for Level 1. Default output is a scratch
    # directory; the authoritative path needs --force and a good reason.
    out = ((Path(out_dir) if out_dir
            else HERE / "levels" / f"_pcb_regen{suffix}") / "level.v6.json")
    if out.resolve() == (HERE / "levels" / "level2" / "level.v6.json").resolve() \
            and not force:
        raise SystemExit(
            f"refusing to overwrite {out}:\n"
            f"  that is the authoritative Level 2 project, authored in the editor.\n"
            f"  Pass --force only if you really mean to discard edits made since\n"
            f"  the PCB prototype was promoted.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(project, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")

    print(f"  wrote {out}")
    print(f"  metatiles   {len(TILES):3d} / 64")
    print(f"  glyphs      {glyph_count:3d} unique  -> {len(padded)} emitted / 128"
          f"  (codes {TERRAIN_GLYPH_BASE}..{TERRAIN_GLYPH_BASE + len(padded) - 1})")
    print(f"  map         {metatile_rows} rows x {MAP_COLS} = {world_rows} world rows")
    print(f"  triggers    {len(triggers)} carried from level 1")
    unused = sorted(n for n, i in BY_NAME.items()
                    if not any(i in r for r in rows))
    if unused:
        print(f"  NOT PLACED  {', '.join(unused)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
