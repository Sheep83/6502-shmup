#!/usr/bin/env python3
"""Turret bodies: a shaded metal dome with one small pulsing lamp.

    python3 tools/turret_art/turret_candidates.py reports/turret-art

B2 IS NOW THE PRODUCTION BODY. Brian chose candidate B in the second pass and
then the B2 mounting plate in the third, and src/turrets.asm carries those bytes.
This tool remains the place the body is DESIGNED: it generates every candidate
from the shading model, renders the previews, and -- see verify_installed() --
checks that what is in src/turrets.asm is still exactly what it generates. If
the body is ever edited by hand, that check is what will say so.

It still WRITES nothing. Installing a candidate means pasting the printed bytes
into src/turrets.asm deliberately.

THE BRIEF THIS SET IS DRAWN TO. Static appearance first: a convincing top-down
metallic dome built from highlight and shadow. Animation is cut back to the
smallest centred element that is technically possible -- a lamp in the middle of
the dome -- rather than spread across vents or the whole body.

THE CONSTRAINTS, read out of src/turrets.asm and src/level1/stage_config.asm
rather than assumed:

    TURRET_GLYPH_BASE  226      four codes, 226..229
    TURRET_GLYPH_SPAN  4        TL, TR, BL, BR -- ONE shared body for every
                                turret on the level
    body               2 x 2 characters = 16 x 16 screen pixels
    multicolour        so 8 logical pixels across, 16 rows down; a logical
                       pixel is TWO screen pixels wide and ONE tall

    bit pair 00  ->  $d021  TERRAIN_BACKGROUND_COLOUR  12  medium grey
    bit pair 01  ->  $d022  TERRAIN_MC_COLOUR_1        15  light grey
    bit pair 10  ->  $d023  TERRAIN_MC_COLOUR_2        11  dark grey
    bit pair 11  ->  COLOUR RAM, low three bits, and colour RAM is what pulses

THREE GREYS, NOT TWO, AND THAT IS THE WHOLE REASON THIS CAN BE A DOME.
$d023/$d021/$d022 are 11/12/15 -- dark, medium, light grey -- an evenly spaced
ramp. Medium grey is also the stage background, so bit pair 00 inside the body
would be a hole if the body had no outline; ENCLOSED BY A CLOSED DARK RIM it
reads as the mid-tone of the metal instead. Every candidate below relies on
that, which is why each one's rim is checked for closure before it is drawn.

THE LAMP. turretPaintTick walks a single global phase through turretPulseTable
(1, 2, 7, 2 -- white, red, yellow, red) every TURRET_PULSE_INTERVAL frames,
ORs in $08 to keep the multicolour selector, and writes it to all four cells of
every turret. So:

  * the pulse cannot light one corner of a cell and not another -- but WITHIN a
    cell, bit pair 11 pulses and the other three do not;
  * all four cells always carry the SAME value, so a lamp sitting on the point
    where the four cells meet is seamless -- which is exactly where the centre
    of the body is;
  * only colours 0..7 are reachable, because bit pair 11 takes the low three
    bits of colour RAM.

EVERY PHASE OF THAT TABLE IS BRIGHT, and for a small indicator lamp that is
right: it reads as a lamp blinking white-red-yellow-red rather than as
something switching on and off. No pulse-table change is proposed this time.

THE SMALLEST CENTRED LAMP IS 2 x 2 LOGICAL PIXELS. The body is 8 logical pixels
across, so the centre falls between columns 3 and 4; it is 16 rows down, so the
centre falls between rows 7 and 8. One logical pixel cannot be centred -- it
would sit to one side -- so 2 x 2 is the floor, and on screen that is 4 pixels
wide by 2 tall. Candidates differ in how much STATIC housing is drawn around
that lamp, never in how much of the body animates.

    .  bit pair 00   $d021, medium grey -- the mid-tone, and the ground
    d  bit pair 01   $d022, light grey  -- the lit side
    D  bit pair 10   $d023, dark grey   -- the rim and the shaded side
    C  bit pair 11   colour RAM         -- the lamp, and the ONLY thing that moves
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PAIR = {".": 0, "d": 1, "D": 2, "C": 3}
INK = {v: k for k, v in PAIR.items()}

# VICE's own rendering of the C64 palette, sampled from an x64sc capture.
RGB = {0: (0, 0, 0), 1: (255, 255, 255), 2: (129, 51, 56), 5: (98, 213, 50),
       7: (255, 255, 70), 11: (74, 74, 74), 12: (120, 120, 120),
       15: (205, 205, 205), 8: (133, 76, 20), 9: (83, 57, 0)}

# Level 1's stage palette, from src/level1/stage_config.asm.
L1 = {"bg": 12, "mc1": 15, "mc2": 11}
# The pulse, from src/turrets.asm turretPulseTable (the low three bits of each).
PULSE = (1, 2, 7, 2)

W, H = 8, 16                    # logical pixels across, rows down
ASPECT = 2                      # a logical pixel is this many screen pixels wide


def body_px(zoom):
    """Width in output pixels of one body drawn at `zoom`."""
    return W * ASPECT * zoom


# ---------------------------------------------------------------------------
# The shading model
# ---------------------------------------------------------------------------
# DRAWN BY A MODEL RATHER THAN BY HAND, because the thing being drawn is a
# sphere and the eye is unforgiving about where a highlight sits on one. The
# model is: an ellipse in LOGICAL space that is a circle on SCREEN, lit from a
# point up and to the left, quantised to the three greys available, with the
# outermost ring of the silhouette forced dark so the body always has a closed
# outline against a background of its own mid-tone.
#
# Every number below was tuned by looking at the native-size sheet. At eight
# logical pixels across there is no substitute for that.

def dome(*, light=(2.2, 4.4), bands=(6.2, 7.8), rim=True,
         collar=None, lamp=(2, 2), flat_top=0.0,
         plate=None, plate_cut=12.0):
    """A shaded hemisphere as a 16 x 8 grid of ink characters, plus its mask.

    light     the specular point, in logical coordinates
    bands     distances (in SCREEN pixels) at which light -> mid -> dark
    rim       force the outermost ring of the silhouette to dark
    collar    None, or a (inner, outer) screen-pixel radius for a dark ring
              around the lamp -- the static housing it sits in
    lamp      (cols, rows) of the centred pulsing lamp; the smallest CENTRED
              lamp is (2, 2) because the centre falls between pixels
    flat_top  shrink the vertical radius by this much, for a squatter body
    plate     None, "dark", or "lit" -- a mounting plate UNDER the dome, drawn
              only in pixels the dome does not use
    plate_cut chamfer threshold in SCREEN pixels: a plate pixel is cut when its
              taxicab distance from the centre exceeds this. Small values
              chamfer hard (octagon), large values cut nothing (square).
              Ignored unless `plate` is set.

    THE PLATE CANNOT MAKE THE BODY BIGGER, because the body already fills its
    two-by-two character footprint. The dome reaches columns 0 and 7 across
    rows 4..11, so the only pixels it leaves free are the FOUR CORNERS -- about
    five usable pixels each once the octagon's corners are cut. That is
    genuinely enough: a plate seen from directly above is mostly hidden by the
    dome sitting on it, and the corners are exactly where it would show.

    THE DOME IS MOSTLY LIGHT GREY, and that is a consequence of the palette
    rather than a style choice. The mid-tone IS the stage background, so a
    dome shaded the obvious way -- light highlight, mid body, dark shadow --
    loses its entire shaded side into the ground and reads as a bright smear
    with no bottom. A first pass did exactly that. So the body is light grey,
    the mid-tone is a THIN transition band, and dark is spent on the rim and a
    shadow crescent at the lower right, which is also where the rim is. That
    keeps a closed silhouette and still reads as a lit sphere.
    """
    cx, cy = (W - 1) / 2.0, (H - 1) / 2.0
    rx, ry = W / 2.0, H / 2.0 - flat_top

    def inside(c, r, shrink=0.0):
        return (((c - cx) / (rx - shrink)) ** 2
                + ((r - cy) / (ry - shrink)) ** 2) <= 1.0

    def lit(c, r):
        """Distance from the specular point, in isotropic SCREEN pixels."""
        dx = (c - light[0]) * ASPECT
        dy = r - light[1]
        return (dx * dx + dy * dy) ** 0.5

    grid = []
    for r in range(H):
        row = []
        for c in range(W):
            if not inside(c, r):
                row.append(".")
                continue
            d = lit(c, r)
            row.append("d" if d < bands[0] else "." if d < bands[1] else "D")
        grid.append(row)

    # ---- the closed dark outline -----------------------------------------
    # A body pixel with a non-body neighbour is the edge. It MUST be dark:
    # the mid-tone is the background colour, so a mid-tone pixel on the
    # boundary is a gap in the silhouette rather than a shade of the metal.
    if rim:
        edge = []
        for r in range(H):
            for c in range(W):
                if not inside(c, r):
                    continue
                for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (c + dc, r + dr)
                    if not (0 <= n[0] < W and 0 <= n[1] < H) or not inside(*n):
                        edge.append((c, r))
                        break
        for c, r in edge:
            grid[r][c] = "D"

    # ---- the static housing, and then the lamp inside it -------------------
    # THE COLLAR IS STATIC. It is machined metal, not animation: the only thing
    # that ever changes colour is the lamp written after it.
    #
    # ONE RING IS ALL THERE IS ROOM FOR. A second concentric ring further out
    # -- a mounting flange, which is what the reference photographs have -- was
    # tried and abandoned: the body is eight logical pixels across, so a flange
    # inside the rim consumes most of the lit side and the dome comes out as a
    # stack of stripes rather than a sphere. With three greys and a 16 px
    # footprint, a gradient and two rings cannot coexist.
    if collar:
        for r in range(H):
            for c in range(W):
                if not inside(c, r):
                    continue
                dx = (c - cx) * ASPECT
                dy = r - cy
                d = (dx * dx + dy * dy) ** 0.5
                if collar[0] <= d <= collar[1]:
                    grid[r][c] = "D"

    # ---- the mounting plate, in the corners the dome does not use ----------
    # DRAWN ONLY WHERE THE DOME IS NOT, so the dome and its centre are bit-for-
    # bit what they were without it. It never uses the mid-tone: a plate pixel
    # is by definition on the outer boundary, and mid-tone there is the ground
    # showing through rather than a shade of metal.
    # A TAXICAB DISTANCE, WHICH IS WHAT MAKES AN OCTAGON. Cutting the corners
    # with a box test only shaves a single pixel off each and the plate still
    # reads as a rectangle; a diagonal chamfer is what gives the plate a
    # recognisably eight-sided outline in the handful of pixels available.
    plate_px = set()
    if plate:
        for r in range(H):
            for c in range(W):
                if inside(c, r):
                    continue
                if abs(c - cx) * ASPECT + abs(r - cy) > plate_cut:
                    continue                    # the chamfered corner
                plate_px.add((c, r))
                # "lit" shades the plate with the SAME light as the dome, so
                # the two agree about where the sun is; "dark" keeps the whole
                # plate in the dome's shadow, which reads flatter and lower.
                grid[r][c] = "D" if plate == "dark" or lit(c, r) >= bands[0] \
                    else "d"

    lc, lr = lamp
    c0, r0 = (W - lc) // 2, (H - lr) // 2
    for r in range(r0, r0 + lr):
        for c in range(c0, c0 + lc):
            grid[r][c] = "C"

    mask = {(c, r) for r in range(H) for c in range(W) if inside(c, r)}
    return ["".join(row) for row in grid], mask | plate_px


# ---------------------------------------------------------------------------
# The candidates. Same concept throughout -- a metal dome with one small lamp.
# They differ ONLY in how the static metal is finished.
# ---------------------------------------------------------------------------
B_DOME = dict(collar=(2.3, 3.6))        # the chosen body, and the ONLY body

CANDIDATES_V2 = {
    # The chosen candidate exactly as it was, for reference.
    "B   dome, no plate  (chosen)": dome(**B_DOME),

    # OCTAGONAL plate, shaded by the same light as the dome: the corner up and
    # to the left catches the light, the rest sits in the dome's shadow. Reads
    # as a machined plate the dome is bolted to.
    "B1  octagonal plate, lit  (rejected)": dome(**B_DOME, plate="lit"),

    # The same octagon, but the whole plate held in shadow. Lower-profile and
    # flatter -- the plate reads as a shadow the dome casts rather than as a
    # second lit surface, which keeps ALL the attention on the dome.
    "B2  octagonal plate, shadowed": dome(**B_DOME, plate="dark"),

    # SQUARE plate: no corners cut at all, so the body fills its entire 16 x 16
    # footprint. The heaviest and most industrial of the three, and the only one
    # whose silhouette is a rectangle rather than a shaped object.
    "B3  square plate, shadowed": dome(**B_DOME, plate="dark",
                                       plate_cut=99.0),
}

CANDIDATES = {
    # The plain hemisphere: a smooth highlight-to-shadow gradient and nothing
    # else competing with it. The lamp is the minimum 2 x 2 and sits directly
    # on the metal, so the dome reads as one machined piece.
    "A  smooth dome": dome(),

    # The same dome with a dark collar machined around the lamp. The collar is
    # STATIC -- it is the housing, not part of the animation -- and its job is
    # to stop the lamp reading as a stray bright pixel on a grey field.
    "B  dome, recessed lamp housing": dome(collar=(2.3, 3.6)),

    # The hardest read of the three: the mid-tone band is closed up entirely,
    # so the dome is light metal and dark shadow with nothing between them. It
    # loses the softness of A and B and gains a terminator you cannot miss at
    # 1:1 -- the most graphic, least photographic of the set, and the one that
    # survives best over busy terrain.
    "C  hard two-tone dome": dome(bands=(6.9, 6.9), collar=(2.3, 3.6)),
}

# The lamp is the ONE animated element, and its size is the one judgement the
# constraints do not make for us. These two are rendered side by side on the
# same body so the trade-off can be seen rather than argued.
#
#   2 x 2 logical = 4 x 2 SCREEN pixels -- the smallest CENTRED lamp possible
#   2 x 4 logical = 4 x 4 SCREEN pixels -- the smallest centred SQUARE one
#
# A logical pixel is two screen pixels wide and one tall, so the minimum lamp
# is a wide flat slot rather than a dot. Four rows makes it square on screen at
# the cost of doubling the animated area -- from 4 pixels of 128 to 8.
LAMP_SIZES = {
    "2 x 2 logical  (4 x 2 screen)  -- the minimum": dome(collar=(2.3, 3.6)),
    "2 x 4 logical  (4 x 4 screen)  -- square on screen":
        dome(collar=(2.3, 4.6), lamp=(2, 4)),
}

# THE BODY B2 REPLACED, kept so the sheets can show a before and after. It spent
# 66 of its 128 pixels on bit pair 11, so the whole dome strobed with the pulse,
# and it had no closed outline at all -- check_rim reports twenty leaks on it.
PREVIOUS = [
    "........", "........", "..CCCC..", ".CCCCCC.",
    "CCCCCCCC", "CCCCCCCC", "CCCCCCCC", "CCCCCCCC",
    "CCCCCCCC", "CCCCCCCC", "CCCCCCCC", "dddddddd",
    "dddddddd", ".dddddd.", "...DD...", "...DD...",
]

# Which candidate src/turrets.asm is expected to be carrying.
INSTALLED = "B2  octagonal plate, shadowed"


def validate(rows, name):
    if len(rows) != H:
        raise SystemExit(f"{name}: {len(rows)} rows, need {H}")
    for i, r in enumerate(rows):
        if len(r) != W:
            raise SystemExit(f"{name}: row {i} is {len(r)} wide, need {W}")
        for ch in r:
            if ch not in PAIR:
                raise SystemExit(f"{name}: row {i} has {ch!r}; use . d D C")
    return rows


def check_rim(rows, mask=None):
    """The mid-tone IS the background, so a body must have a closed outline.

    Reports any pixel INSIDE the intended silhouette that is drawn mid-tone or
    lamp and touches the OUTSIDE of that silhouette. Such a pixel is a hole in
    the outline, not a shade of the metal, and at native size the ground eats
    into the body there.

    IT NEEDS THE SILHOUETTE, NOT THE PIXELS. A first version inferred the body
    from "every pixel that is not mid-tone", which makes every legitimate
    interior mid-tone region look like a hole and reported ten leaks on a body
    that had none. Mid-tone is load-bearing here; it cannot also be the marker
    for "outside".
    """
    if mask is None:                    # the production body, which has no model
        mask = {(c, r) for r in range(H) for c in range(W) if rows[r][c] != "."}
    leaks = []
    for (c, r) in sorted(mask):
        # DARK **AND LIGHT** BOTH CLOSE THE OUTLINE. Only bit pair 00 is the
        # ground colour; light grey on the boundary is low contrast but it is
        # still a different colour, not a hole. An earlier version flagged it,
        # which made a legitimately lit plate edge look like a defect.
        if rows[r][c] in ("D", "d"):
            continue
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c + dc, r + dr)
            if not (0 <= n[0] < W and 0 <= n[1] < H) or n not in mask:
                leaks.append((c, r))
                break
    return leaks


def verify_installed(asm=None):
    """Is src/turrets.asm still carrying exactly the candidate named INSTALLED?

    THE BODY IS GENERATED, SO IT CAN DRIFT. The bytes in the engine were pasted
    from this tool; if either side is edited alone they stop agreeing and the
    ASCII drawn beside them in src/turrets.asm becomes a lie. This decodes the
    four glyphs straight out of the source and compares.

    Returns (ok, message). Never raises on a missing file -- the tool has to
    keep working when run from somewhere else.
    """
    path = Path(asm) if asm else (
        Path(__file__).resolve().parents[2] / "src" / "turrets.asm")
    if not path.is_file():
        return None, f"{path} not found; skipped"
    src = path.read_text()
    try:
        blk = src.split("turretGlyphs:")[1].split("turretGlyphsEnd:")[0]
    except IndexError:
        return False, "turretGlyphs / turretGlyphsEnd not found in the source"
    found = {lbl: [int(x, 16) for x in re.findall(r"\$([0-9a-f]{2})", body)]
             for body, _code, lbl in
             re.findall(r"\.byte ([^/]+)//\s*(\d+)\s+(\w+)", blk)}
    if sorted(found) != ["BL", "BR", "TL", "TR"]:
        return False, f"expected TL/TR/BL/BR, found {sorted(found)}"

    grid = [["?"] * W for _ in range(H)]
    for lbl, (c0, r0) in (("TL", (0, 0)), ("TR", (4, 0)),
                          ("BL", (0, 8)), ("BR", (4, 8))):
        for i, byte in enumerate(found[lbl]):
            for j in range(4):
                grid[r0 + i][c0 + j] = INK[(byte >> (6 - 2 * j)) & 3]
    decoded = ["".join(r) for r in grid]

    want = CANDIDATES_V2[INSTALLED][0]
    if decoded == want:
        return True, f"src/turrets.asm carries '{INSTALLED}' exactly"
    diff = [i for i, (a, b) in enumerate(zip(decoded, want)) if a != b]
    return False, (f"src/turrets.asm does NOT match '{INSTALLED}'; "
                   f"rows differing: {diff}")


def lamp_cells(rows):
    """Which of the four character cells the pulsing lamp touches."""
    names = {(0, 0): "TL", (1, 0): "TR", (0, 1): "BL", (1, 1): "BR"}
    hit = set()
    for r in range(H):
        for c in range(W):
            if rows[r][c] == "C":
                hit.add(names[(c // 4, r // 8)])
    return sorted(hit)


def glyphs(rows):
    """16x8 logical pixels -> the four 8-byte glyphs, TL TR BL BR."""
    out = []
    for r0 in (0, 8):                       # top half, bottom half
        for c0 in (0, 4):                   # left char, right char
            g = []
            for r in range(r0, r0 + 8):
                b = 0
                for c in range(c0, c0 + 4):
                    b = (b << 2) | PAIR[rows[r][c]]
                g.append(b)
            out.append(g)
    # TL TR BL BR is the order src/turrets.asm assembles them in
    return [out[0], out[1], out[2], out[3]]


def colours(cram):
    return {0: RGB[L1["bg"]], 1: RGB[L1["mc1"]], 2: RGB[L1["mc2"]], 3: RGB[cram]}


def raster(rows, cram, zoom=1):
    """Logical pixels -> RGB rows at true 2:1 aspect."""
    pal = colours(cram)
    out = []
    for r in rows:
        line = []
        for ch in r:
            line += [pal[PAIR[ch]]] * (2 * zoom)     # a logical px is 2 wide
        for _ in range(zoom):
            out.append(line)
    return out


def paste(img, grid, ox, oy):
    px = img.load()
    for y, line in enumerate(grid):
        for x, rgb in enumerate(line):
            px[ox + x, oy + y] = rgb


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: turret_candidates.py <out dir>")
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("Pillow is needed for the previews")

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    # (name, rows, silhouette mask or None)
    entries = [("PREVIOUS body (replaced by B2)", PREVIOUS, None)]
    entries += [(n, rows, mask) for n, (rows, mask) in CANDIDATES_V2.items()]
    for name, rows, _ in entries:
        validate(rows, name)

    pad, gap, lab = 14, 12, 18
    BG = RGB[L1["bg"]]

    # ---- sheet 1: THE STATIC LOOK, which is what is being judged ----------
    # Big, on the real ground colour, with no pulse variation to distract --
    # every body at the same single phase. Static appearance takes priority, so
    # it gets the sheet of its own.
    Z = 10
    Wp, Hp = body_px(Z), H * Z
    img = Image.new("RGB", (pad + len(entries) * (Wp + gap * 3),
                            pad * 2 + Hp + 26), BG)
    dr = ImageDraw.Draw(img)
    for i, (name, rows_, _m) in enumerate(entries):
        ox = pad + i * (Wp + gap * 3)
        paste(img, raster(rows_, PULSE[0], Z), ox, pad)
        dr.text((ox, pad + Hp + 6), name, fill=(25, 25, 25))
    img.save(out / "turret-static.png")

    # ---- sheet 2: native size, and a small multiple -----------------------
    # THE ONLY SHEET THAT CAN SETTLE A SHAPE. Everything looks plausible at 10x;
    # at 1:1 a one-pixel mistake in a highlight is the difference between a dome
    # and a smudge.
    img2 = Image.new("RGB", (pad + len(entries) * (body_px(8) + gap), pad * 2 + H * 8 + 46), BG)
    dr2 = ImageDraw.Draw(img2)
    for i, (name, rows_, _m) in enumerate(entries):
        ox = pad + i * (body_px(8) + gap)
        paste(img2, raster(rows_, PULSE[0], 8), ox, pad)
        for k in range(3):                      # a row of them, as on a stage
            paste(img2, raster(rows_, PULSE[0], 1),
                  ox + k * (body_px(1) + 6), pad + H * 8 + 8)
        dr2.text((ox, pad + H * 8 + 28), name.split()[0], fill=(25, 25, 25))
    img2.save(out / "turret-native.png")

    # ---- sheet 3: the lamp through the pulse ------------------------------
    Z3 = 7
    W3, H3 = body_px(Z3), H * Z3
    # ON THE GROUND COLOUR, not on a dark sheet. The mid-tone IS $d021, so a
    # body shown against anything else misrepresents its own silhouette -- the
    # first version of this sheet used a dark backing and made every candidate
    # look better enclosed than it really is.
    img3 = Image.new("RGB", (pad + len(PULSE) * (W3 + gap),
                             pad + len(entries) * (H3 + gap + lab)), BG)
    dr3 = ImageDraw.Draw(img3)
    for row, (name, rows_, _m) in enumerate(entries):
        oy = pad + row * (H3 + gap + lab)
        dr3.text((pad, oy - 11), name, fill=(20, 20, 20))
        for col, cram in enumerate(PULSE):
            ox = pad + col * (W3 + gap)
            paste(img3, raster(rows_, cram, Z3), ox, oy)
            dr3.text((ox, oy + H3 + 2), f"phase {col}: cRAM {cram}",
                     fill=(45, 45, 45))
    img3.save(out / "turret-pulse.png")

    # ---- sheet 4: how big the ONE animated element should be --------------
    # Same body, same everything, two lamp sizes -- at 10x and at 1:1, because
    # this is a decision that only 1:1 can settle.
    Z4 = 10
    W4, H4 = body_px(Z4), H * Z4
    sizes = list(LAMP_SIZES.items())
    img4 = Image.new("RGB", (pad + len(sizes) * (W4 + gap * 4), pad * 2 + H4 + 54), BG)
    dr4 = ImageDraw.Draw(img4)
    for i, (label, (rows_, _m)) in enumerate(sizes):
        ox = pad + i * (W4 + gap * 4)
        paste(img4, raster(rows_, PULSE[0], Z4), ox, pad)
        for k, cram in enumerate(PULSE):        # 1:1, right through the pulse
            paste(img4, raster(rows_, cram, 1), ox + k * (body_px(1) + 6),
                  pad + H4 + 8)
        dr4.text((ox, pad + H4 + 30), label, fill=(25, 25, 25))
    img4.save(out / "turret-lamp-size.png")

    # ---- the bytes, and the checks ----------------------------------------
    print(f"  wrote 4 preview sheets to {out}")
    for name, rows_, mask in entries:
        g = glyphs(rows_)
        cram = sum(r.count("C") for r in rows_)
        leaks = check_rim(rows_, mask)
        print(f"\n  {name}")
        print(f"    {cram}/128 pixels pulse   lamp spans cells "
              f"{','.join(lamp_cells(rows_)) or '-'}")
        print(f"    silhouette {'CLOSED' if not leaks else f'LEAKS at {leaks}'}")
        for r in rows_:
            print(f"      |{r}|")
        for lbl, code, bytes_ in zip(("TL", "TR", "BL", "BR"), range(226, 230), g):
            print(f"    .byte " + ",".join(f"${b:02x}" for b in bytes_)
                  + f"   // {code}  {lbl}")
    ok, msg = verify_installed()
    tag = "SKIP" if ok is None else ("ok  " if ok else "FAIL")
    print(f"\n  [{tag}] {msg}")
    return 0 if ok is not False else 1


if __name__ == "__main__":
    sys.exit(main())
