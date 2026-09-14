#!/usr/bin/env python3
"""Enemy ingress/egress lifecycle, in the real production loop.

NOT PART OF `make test`. It watches most of a 126-row authored cycle so that
every pattern arrives and leaves, which is a minute of gate time to re-prove
content that only changes when somebody edits it deliberately. The permanent
regression keeps proving the director; this proves the LIFECYCLE BOUNDS that
the ingress/egress correction introduced.

What this proves, watching the REAL frame loop -- nothing calls wmTick or
waveSpawnMember directly, and nothing pokes a position:

* enemies are ALIVE while entirely outside the visible playfield, which is the
  whole point: they exist before they can be seen;
* they then cross INTO the aperture under ordinary movement;
* they are NOT freed at the old premature cutoff -- an enemy is observed alive
  well below Y=226, which was impossible before;
* they are freed only once they have genuinely cleared an edge;
* both kinds of exit happen: through the bottom, and through a side;
* X never wraps, so no borrow into logXHi reappears a sprite on the far side;
* the production health counters stay clean.

JUDGED BY WHERE ENEMIES ARE SEEN ALIVE, NOT BY WHERE THEY DIED, and that is
deliberate. harness.step_n guarantees each sample is a DISTINCT frame, not a
CONSECUTIVE one, and the breakpoint sits before objectUpdateAll -- so the last
sample before a death is the position one move BEFORE the fatal one. The first
draft of this file judged deaths by that stale position and reported an enemy
freed at Y=247 as "freed while still inside", which was the probe being wrong
rather than the engine. Extremes of the live population have no such problem.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import PRG, SYM, symbols, Vice, rd, rd1, set_bp, free_run, step_n, check, report

sym = symbols(SYM)

MAX_OBJECTS = 16
MAX_LOGICAL = 32
TYPE_NONE, TYPE_ENEMY = 0, 1

# The aperture and the sprite, restated independently of the assembler so that
# this file disagrees loudly if either moves.
APERTURE_TOP, APERTURE_BOT = 55, 247
SPRITE_H, SPRITE_W = 21, 24
DISPLAY_LEFT, DISPLAY_RIGHT = 24, 343
CLEAR_Y = APERTURE_BOT + 1                  # 248
CLEAR_X_LEFT, CLEAR_X_RIGHT = 4, 344
OLD_CUTOFF = 226                            # v1.1 froze the world here

# One sample is a distinct frame but not necessarily the next one, and an
# enemy moves at most ~1.5px a frame, so a death is attributed to an edge if
# its last seen position was within a few frames' travel of it.
LAG = 10
# Comfortably past OLD_CUTOFF and still inside the aperture: a Y no enemy could
# ever have been seen alive at before this slice.
DEEP_Y = 236

MAX_FRAMES = 1150


def visible(x, y):
    """Is any part of the sprite inside the visible playfield?"""
    return (y + SPRITE_H - 1) >= APERTURE_TOP and y <= APERTURE_BOT \
        and (x + SPRITE_W - 1) >= DISPLAY_LEFT and x <= DISPLAY_RIGHT


MOVE_BLOCK = sym["wmBaseCol"] + MAX_OBJECTS - sym["wmMode"]


def s8(v):
    return v - 256 if v > 127 else v


def sample(mon):
    """Three monitor reads. logY/logX/logXHi are one contiguous block of
    MAX_LOGICAL-byte arrays, and wmVX/wmBaseCol are both inside the movement
    state block, so the whole of an object's position, velocity and identity
    is three dumps however many fields are wanted."""
    pos = rd(mon, sym["logY"], 3 * MAX_LOGICAL)
    typ = rd(mon, sym["objType"], MAX_OBJECTS)
    mv = rd(mon, sym["wmMode"], MOVE_BLOCK)
    y = pos[0:MAX_OBJECTS]
    xlo = pos[MAX_LOGICAL:MAX_LOGICAL + MAX_OBJECTS]
    xhi = pos[2 * MAX_LOGICAL:2 * MAX_LOGICAL + MAX_OBJECTS]
    vo = sym["wmVX"] - sym["wmMode"]
    co = sym["wmBaseCol"] - sym["wmMode"]
    return (typ, [xlo[i] | (xhi[i] << 8) for i in range(MAX_OBJECTS)], y,
            mv[co:co + MAX_OBJECTS], xhi,
            [s8(b) for b in mv[vo:vo + MAX_OBJECTS]])


def main():
    print("=== enemy ingress / egress lifecycle ===")
    v = None
    try:
        v = Vice(6667, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        check("logY/logX/logXHi are one contiguous block, as the bulk read "
              "assumes",
              sym["logX"] == sym["logY"] + MAX_LOGICAL
              and sym["logXHi"] == sym["logY"] + 2 * MAX_LOGICAL)

        bp = set_bp(mon, sym["gameFrame"])

        hidden_frames = 0       # object-frames alive and wholly unseen
        entered = 0             # first seen hidden, later seen in view
        born_in_view = []       # first seen already on screen, away from an edge
        max_y_alive = 0
        min_x_alive = 999
        over_clear = []         # seen alive past a clearance bound
        exits_bottom = exits_side = side_crossings = 0
        exits_bad = []
        wrapped = []
        colours = set()
        seen_frames = 0

        live = {}               # slot -> dict(col, saw, x, y)
        prev = None

        for _ in range(MAX_FRAMES):
            typ, xs, ys, col, xhi, vxs = step_n(
                mon, sym["frameCounter"], 1, lambda: sample(mon))[0]
            seen_frames += 1

            for i in range(MAX_OBJECTS):
                if typ[i] != TYPE_ENEMY:
                    continue
                x, y = xs[i], ys[i]
                if xhi[i] not in (0, 1):
                    wrapped.append((i, x, xhi[i]))
                colours.add(col[i])
                max_y_alive = max(max_y_alive, y)
                min_x_alive = min(min_x_alive, x)
                # DIRECTION MATTERS, exactly as it does in src/enemy.asm: a
                # sprite behind a side border on its way IN is alive on
                # purpose. The sweep enters at X=0 and would otherwise be
                # reported as a runaway on its first frame.
                if (y >= CLEAR_Y
                        or (x < CLEAR_X_LEFT and vxs[i] < 0)
                        or (x >= CLEAR_X_RIGHT and vxs[i] > 0)):
                    over_clear.append((col[i], x, y, vxs[i]))
                if x < DISPLAY_LEFT or x + SPRITE_W - 1 > DISPLAY_RIGHT:
                    side_crossings += 1

                o = live.get(i)
                if o is None or o["col"] != col[i]:
                    witnessed = prev is not None and prev[0][i] != TYPE_ENEMY
                    o = {"col": col[i], "saw": False}
                    live[i] = o
                    # ONLY A BIRTH THIS RUN ACTUALLY SAW. Enemies already in
                    # flight at the first sample -- the warm-up leaves several
                    # -- are first seen wherever they happen to be, and the
                    # first draft reported those mid-flight positions as
                    # enemies materialising in mid-air.
                    if witnessed and visible(x, y):
                        # Only a birth well away from every entry edge is
                        # unambiguous; a sampling gap can otherwise show a
                        # legitimate arrival a few pixels inside one.
                        if y > APERTURE_TOP + LAG * 2 and x > DISPLAY_LEFT + LAG * 2:
                            born_in_view.append((col[i], x, y))
                if visible(x, y):
                    if not o["saw"]:
                        entered += 1
                    o["saw"] = True
                else:
                    hidden_frames += 1
                o["x"], o["y"] = x, y

            if prev is not None:
                ptyp, pxs, pys, pcol = prev[0], prev[1], prev[2], prev[3]
                for i in range(MAX_OBJECTS):
                    if ptyp[i] == TYPE_ENEMY and typ[i] != TYPE_ENEMY:
                        x, y = pxs[i], pys[i]
                        if y >= CLEAR_Y - LAG:
                            exits_bottom += 1
                        elif x <= CLEAR_X_LEFT + LAG or x >= CLEAR_X_RIGHT - LAG:
                            exits_side += 1
                        else:
                            exits_bad.append((pcol[i], x, y))
                        live.pop(i, None)
            prev = (typ, xs, ys, col, xhi, vxs)

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        print(f"  .... watched {seen_frames} production frames, "
              f"{len(colours)} patterns, Y seen alive up to {max_y_alive}, "
              f"X down to {min_x_alive}")

        check("enemies are alive while wholly off screen: a logical life is "
              "wider than a visible one",
              hidden_frames > 0, f"{hidden_frames} object-frames unseen")
        check("...and they cross INTO the aperture under ordinary movement",
              entered > 0, f"{entered} enemies became visible")
        check("no enemy materialises inside the playfield away from an edge",
              not born_in_view, f"{born_in_view[:4]}")
        check("an enemy is seen ALIVE well past the old Y=226 cutoff, which "
              "that cutoff made impossible",
              max_y_alive >= DEEP_Y,
              f"deepest Y seen alive {max_y_alive}, old cutoff {OLD_CUTOFF}")
        check("no enemy is left alive past a clearance bound",
              not over_clear, f"{over_clear[:4]}")
        check("enemies leave through the BOTTOM, having cleared it",
              exits_bottom > 0, f"{exits_bottom} bottom exits")
        check("enemies cross a side border while alive, where the VIC clips "
              "them column by column",
              side_crossings > 0,
              f"{side_crossings} object-frames straddling a side border, "
              f"{exits_side} of them leaving that way")
        check("no enemy was freed away from any edge",
              not exits_bad, f"{exits_bad[:4]}")
        check("X never wrapped: logXHi stayed 0 or 1 for every live enemy",
              not wrapped, f"{wrapped[:4]}")
        check("all four authored patterns ran during the window",
              len(colours) == 4, f"colours {sorted(colours)}")

        for name in ("gameOverrun", "publishSkip", "schedBuildDefer",
                     "scrollLate", "edgeLate"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero over the run", got == 0, str(got))
        for name in ("wvDropped", "objAllocFail", "objDoubleFree"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero over the run", got == 0, str(got))
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
