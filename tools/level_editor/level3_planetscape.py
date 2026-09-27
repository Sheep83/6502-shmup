"""Level 3 terrain vocabulary: the surface of a bombarded world.

THE WHOLE IDEA IN ONE LINE: it is not a colourful place, it is a lit place.

Four tones, one light. Everything in this file -- craters, boulders, ridges, the
turret pad -- is drawn with the sun low on the LEFT, so every raised thing
catches light on its west face and throws shade to its east, and every hollow
does the exact opposite. Get that backwards anywhere and the surface stops
reading as relief and becomes wallpaper.

    pixel 0  $D021  MEDIUM   the regolith. The quiet majority of the screen.
    pixel 1  $D022  LIGHT    sunlit rims, west faces, the tops of things.
    pixel 2  $D023  DARK     shade: east faces, crater floors, cast shadow.
    pixel 3  cRAM   DEEPEST  the black of a deep pit. Used sparingly, on
                             purpose -- it is the only tone that can look like
                             a hole rather than a stain.

WHY 0 IS THE MIDDLE OF THE RAMP AND NOT THE DARKEST. src/turrets.asm draws the
shared turret dome assuming exactly this: pair 1 is its lit side, pair 2 its
shadow crescent and rim, and pair 0 is "the stage background, so it only works
enclosed" -- never on the body's outline. Level 1 honours that ramp and level 2
inverts it, which is why the turret reads as metal on one and as a mistake on
the other. Level 3 honours it, and gets a correctly lit dome for nothing.

GEOMETRY. A metatile is 16 native pixels across and 32 rows down, and a native
pixel is TWICE AS WIDE as it is tall. So a circle on the glass is an ellipse
here: ry = 2 * rx, always. Draw a crater with equal radii and you get an egg.
"""
from __future__ import annotations

import math

from native_metatile import NATIVE_W as W, NATIVE_H as H   # 16, 32

MED, LIT, DRK, DEEP = 0, 1, 2, 3

# The sun. Low, west, a little above the horizon -- shade falls east and
# slightly south, which is what makes the surface look like a surface.
LIGHT_X, LIGHT_Y = -1.0, -0.45


# ---------------------------------------------------------------------------
# canvas helpers. A canvas is rows of ints; multi-metatile features are drawn
# on ONE wide canvas and sliced afterwards, which is the only way the seams
# between the pieces of a big crater can actually line up.
# ---------------------------------------------------------------------------
def canvas(cols=1, rows=1, fill=MED):
    return [[fill] * (W * cols) for _ in range(H * rows)]


def slice_metatiles(cv, cols, rows):
    """Cut a multi-metatile canvas into per-metatile grids, reading order."""
    out = []
    for mr in range(rows):
        for mc in range(cols):
            out.append([row[mc * W:(mc + 1) * W]
                        for row in cv[mr * H:(mr + 1) * H]])
    return out


def put(cv, x, y, v):
    if 0 <= y < len(cv) and 0 <= x < len(cv[0]):
        cv[y][x] = v


def _ell(x, y, cx, cy, rx, ry):
    """Normalised radius of (x,y) on an ellipse centred (cx,cy). <1 is inside."""
    dx, dy = (x - cx) / max(rx, 1e-6), (y - cy) / max(ry, 1e-6)
    return math.hypot(dx, dy)


# ---------------------------------------------------------------------------
# THE CRATER. One routine, because every crater in the level is the same idea
# at a different size, and four hand-drawn craters would disagree about where
# the sun is.
#
# A crater is FOUR nested things, outside in:
#   * an ejecta blush, a few stray lit pixels outside the rim;
#   * the RIM, lit on the sun side and dark on the far side -- this is what
#     makes it read as raised rather than painted on;
#   * the INNER WALL, which reverses: shadowed on the sun side because the
#     sun cannot reach down the near wall, lit on the far side where it can;
#   * the FLOOR, dark, with the deepest tone only in the biggest craters.
#
# That reversal between rim and inner wall is the entire trick of a crater. A
# ring of light with a dark middle is a doughnut; light outside and shade
# immediately inside on the SAME side is a hole.
# ---------------------------------------------------------------------------
def crater(cv, cx, cy, rx, *, deep_floor=False, wobble=0.035, seed=1):
    """A bowl. `rx` is the NATIVE horizontal radius; the vertical one follows.

    WOBBLE IS PRICED, NOT CHOSEN. A per-angle radius jitter is what stops the
    rim looking like a vector circle, but every cell the wobbly edge crosses is
    a glyph unique to that spot. Measured on this vocabulary: 0.07 on both the
    2x2 and the 3x3 costs 7 glyphs more than 0.035, which is a whole extra
    boulder plus a filler variant. Half the jitter still breaks the curve up at
    the size these are drawn; the 7 glyphs bought more of the surface.
    """
    ry = rx * 2.0                       # native pixels are 2:1
    rng = _rng(seed)
    # per-angle radius wobble so the rim is geological, not vector
    bumps = [1.0 + wobble * (rng() - 0.5) * 2 for _ in range(16)]

    def r_at(ang):
        f = (ang / (2 * math.pi)) * len(bumps)
        i = int(f) % len(bumps)
        j = (i + 1) % len(bumps)
        t = f - int(f)
        return bumps[i] * (1 - t) + bumps[j] * t

    x0, x1 = int(cx - rx - 3), int(cx + rx + 4)
    y0, y1 = int(cy - ry - 5), int(cy + ry + 6)
    for y in range(y0, y1):
        for x in range(x0, x1):
            ang = math.atan2((y - cy) / 2.0, (x - cx)) % (2 * math.pi)
            k = _ell(x, y, cx, cy, rx * r_at(ang), ry * r_at(ang))
            # which side of the crater is this, relative to the sun?
            nx, ny = (x - cx), (y - cy) / 2.0
            n = math.hypot(nx, ny) or 1.0
            facing = (nx / n) * LIGHT_X + (ny / n) * LIGHT_Y   # +1 sunward

            if k > 1.34:
                continue
            # NO EJECTA SPECKLE, and dropping it was both a budget decision and
            # an art one. Random lit pixels outside the rim turned every plain
            # cell around a crater into a unique glyph -- 16 of them across the
            # vocabulary, measured -- and they are precisely the salt-and-pepper
            # noise that shimmers when the stage scrolls. Ejecta now lives where
            # it belongs: in the separately placed grit tiles, under the level
            # designer's control.
            if k > 1.12:
                continue
            # BROAD BANDS, NOT A TRACED OUTLINE, and the ORDER of the tones
            # is the whole trick. On a CRT a broad area of light against a
            # broad area of shade reads as relief at a glance, while a
            # one-pixel traced curve reads as a scratch and shimmers when it
            # scrolls. And a character cell that falls ENTIRELY inside one band
            # is a single reused glyph, where a cell crossed by a thin curve is
            # unique to that spot.
            #
            # WHY THE FLOOR IS *MED* AND NOT DARK -- this was measured, by
            # rendering the exported charset back out and looking at it. With a
            # DRK floor the anti-sun inner wall (also DRK) and the floor merged
            # into one undifferentiated dark mass with no boundary between
            # them, and the crater stopped reading as a bowl: with the sunward
            # rim lit right across the north cap, the whole top half read as a
            # bright MOUND. The bowl only appears when consecutive bands step
            # in tone. Reading west to east across the middle of a crater the
            # eye must cross five real steps:
            #
            #   ground  LIT rim | DEEP wall | DRK floor | MED floor | LIT wall | DRK rim  ground
            #           raised,   in its     shadow the   open to     the sun-   raised,
            #           sunward   own rim's   west rim     the sun     facing     facing
            #                     shadow      casts                    crescent   away
            #
            # That is also the physics of a low sun: the lip on the sun side
            # shades its own inner wall and throws a crescent of shadow across
            # the near floor, while the FAR inner wall is the brightest thing
            # in the feature. It is the single most recognisable signature a
            # crater has, and it costs nothing extra to be correct about.
            #
            # THE ARCS ARE DELIBERATELY UNDER A HALF-CIRCLE EACH, and that is
            # the difference between a bowl and a washer. Drawn first with the
            # lit rim spanning `facing > -0.12` -- 194 degrees, over half the
            # circumference -- the lit OUTER rim on the near side ran round the
            # poles and joined the lit INNER wall on the far side, closing the
            # grey into an unbroken annulus. A complete bright ring is a torus
            # lying on the ground; it is not a hole. Rendering the exported
            # charset back out to a PNG in the real palette is what showed it.
            #
            # At +/-0.15 each lit arc is about 160 degrees, and between them
            # sit two wedges where the light merely GRAZES the surface and both
            # bands go dark. Those two breaks -- at the north-east and the
            # south-west, perpendicular to the sun -- are what stop the ring
            # closing, and they leave two opposed crescents, which is the
            # signature every real crater photographed at low sun has.
            if k > 0.82:                                   # THE RIM, raised
                put(cv, x, y, LIT if facing > 0.15 else DRK)
                continue
            if k > 0.60:                                   # THE INNER WALL
                # the far wall catches the sun; the near wall is in the shadow
                # of the very lip that is lit, so it is the DEEPEST tone here.
                if facing < -0.15:
                    put(cv, x, y, LIT)
                elif deep_floor and facing > 0.40:
                    put(cv, x, y, DEEP)
                else:
                    put(cv, x, y, DRK)
                continue
            # THE FLOOR. Flat within each half on purpose, which is a glyph
            # budget decision as much as an artistic one: a cell of uniform
            # floor costs ONE glyph however often it appears, and a crater
            # floor genuinely is flat. The near half carries the rim's cast
            # shadow; the far half is open regolith, the same tone as the
            # surrounding ground, which is exactly how a shallow crater looks
            # from above -- the RING is the feature, not a hole in the screen.
            near = facing > 0.34 and math.hypot(nx, ny) > rx * 0.16
            put(cv, x, y, DRK if near else MED)


# ---------------------------------------------------------------------------
# THE BOULDER. A rock sitting ON the ground, which means it needs three things
# a crater does not: a lit cap, a dark east flank, and a cast shadow lying on
# the dirt beside it. Without the cast shadow it is a stain; with it, it is an
# object standing up.
# ---------------------------------------------------------------------------
def boulder(cv, cx, cy, rx, *, seed=3, cap=True):
    ry = rx * 1.7
    rng = _rng(seed)
    for y in range(int(cy - ry - 1), int(cy + ry + 2)):
        for x in range(int(cx - rx - 1), int(cx + rx + 2)):
            k = _ell(x, y, cx, cy, rx * (1 + 0.10 * (rng() - 0.5)), ry)
            if k > 1.0:
                continue
            nx, ny = (x - cx), (y - cy) / 2.0
            n = math.hypot(nx, ny) or 1.0
            facing = (nx / n) * LIGHT_X + (ny / n) * LIGHT_Y
            if k > 0.80:
                put(cv, x, y, LIT if facing > 0.0 else DRK)
            else:
                put(cv, x, y, LIT if (cap and facing > 0.45) else DRK)
    # cast shadow: east and a little south, hugging the base
    for y in range(int(cy), int(cy + ry + 2)):
        span = int(rx * (1.0 - (y - cy) / (ry * 2.2)))
        for x in range(int(cx + rx * 0.35), int(cx + rx * 0.35) + max(0, span)):
            if _ell(x, y, cx, cy, rx, ry) > 0.95:
                put(cv, x, y, DRK)


def _rng(seed):
    """Tiny deterministic PRNG -- the tileset must be byte-identical each run."""
    s = [seed * 1103515245 + 12345]

    def nxt():
        s[0] = (s[0] * 1103515245 + 12345) & 0x7FFFFFFF
        return (s[0] >> 8) / 8388608.0
    return nxt


# ---------------------------------------------------------------------------
# small accents
# ---------------------------------------------------------------------------
def pebbles(cv, n, *, seed=7, x0=0, y0=0, x1=None, y1=None):
    """Scattered grit: a lit pixel with a dark one east of it. Clustered, not
    sprinkled -- uniform speckle is the noise the brief forbids."""
    rng = _rng(seed)
    x1 = (x1 if x1 is not None else len(cv[0]) - 1)
    y1 = (y1 if y1 is not None else len(cv) - 1)
    for _ in range(n):
        cxp = x0 + int(rng() * (x1 - x0))
        cyp = y0 + int(rng() * (y1 - y0))
        # THREE SHAPES, NOT ONE. Every pebble used to be the same LIT pixel
        # with a DRK one east of it, and a native pixel is twice as wide as it
        # is tall, so that mark is FOUR screen pixels wide and one tall -- a
        # dash. Clusters of identical dashes were the streaky diagonal texture
        # that made the filler read as a repeated stamp at game scale. The
        # lighting was never wrong; the silhouette was.
        for _ in range(1 + int(rng() * 3)):            # a little cluster
            x = cxp + int((rng() - 0.5) * 7)
            y = cyp + int((rng() - 0.5) * 9)
            kind = rng()
            if kind < 0.42:            # a stone lying in its own shade
                put(cv, x, y, DRK)
            elif kind < 0.80:          # a lit crown, shadow east
                put(cv, x, y, LIT)
                put(cv, x + 1, y, DRK)
            else:                      # two rows tall: reads as a rock, not a mark
                put(cv, x, y, LIT)
                put(cv, x + 1, y, DRK)
                put(cv, x, y + 1, DRK)
                put(cv, x + 1, y + 1, DRK)


def crack(cv, x, y, length, *, seed=11, drift=0.55):
    """A fissure: dark, one pixel wide, with a lit lip on its sunward edge."""
    rng = _rng(seed)
    fx = float(x)
    for i in range(length):
        yy = y + i
        fx += (rng() - 0.5) * drift
        put(cv, int(fx), yy, DRK)
        if i % 3:
            put(cv, int(fx) - 1, yy, LIT)


def ridge(cv, x0, y, x1, *, seed=13):
    """A low scarp: lit along the top, dark immediately below it."""
    rng = _rng(seed)
    yy = float(y)
    for x in range(x0, x1):
        yy += (rng() - 0.5) * 0.7
        put(cv, x, int(yy), LIT)
        put(cv, x, int(yy) + 1, DRK)
        if rng() < 0.4:
            put(cv, x, int(yy) + 2, DRK)


def pit(cv, cx, cy, rx, *, seed=17):
    """A shallow scoop: no raised rim, just shade with a lit far lip."""
    ry = rx * 2.0
    for y in range(int(cy - ry - 1), int(cy + ry + 2)):
        for x in range(int(cx - rx - 1), int(cx + rx + 2)):
            k = _ell(x, y, cx, cy, rx, ry)
            if k > 1.0:
                continue
            nx, ny = (x - cx), (y - cy) / 2.0
            n = math.hypot(nx, ny) or 1.0
            facing = (nx / n) * LIGHT_X + (ny / n) * LIGHT_Y
            put(cv, x, y, LIT if (k > 0.72 and facing < -0.35) else DRK)
