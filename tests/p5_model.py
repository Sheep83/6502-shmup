#!/usr/bin/env python3
"""The P5 independent model: sixteen sprites orbiting one ring.

P5 is the integration torture proof. Everything below is stated from the
GEOMETRY -- never read back from the 6502 -- so that `tests/test_p5.py` has
something genuinely independent to compare the running machine against.

WHY A RING, AND WHY SIXTEEN EVENLY PHASE-SPACED SPRITES

A ring is the cheapest shape that forces every property P0-P4 proved separately
to happen at once, continuously, and forever:

  continuous X and Y motion        every sprite moves on every frame
  continuous Y-order churn         phases are evenly spaced, so sprites
                                   permanently overtake one another
  equal-Y ties                     rounding puts pairs on exactly the same
                                   raster constantly -- 240 tie pairs per orbit
  X=255 crossings both ways        the orbit is wider than 256 pixels
  slot-ownership churn             every one of HW2..HW7 is owned by all
                                   sixteen logical sprites within one orbit
  predecessor churn                134 distinct (sprite, i-6 predecessor) pairs
  batch-shape churn                batch count moves between 6, 7 and 11

THE ONE GEOMETRIC FACT THAT MAKES IT SAFE TO WATCH

Sixteen points evenly spaced in PHASE are not evenly spaced in Y: they bunch at
the top and bottom of the orbit where cos(phase) ~ 0. The obvious worry is that
the bunching starves the reuse rule -- accepted entry i must clear entry i-6 by
MIN_REUSE_GAP -- and sprites start being legitimately REJECTED. A human watching
would see a sprite vanish and report corruption that was never there.

It does not happen, and the reason is worth writing down: bunching tightens
ADJACENT sorted pairs, but the reuse rule spans SIX positions, and a six-position
span always crosses the whole cluster. Measured over the full period with
RY = 70, the minimum of sorted_y[k+6] - sorted_y[k] is 43, against a
MIN_REUSE_GAP of 33.

So all sixteen sprites are admitted on every frame of every mode. That is what
makes P5 a legitimate manual test: a missing sprite is ALWAYS a fault, and the
human never has to decide whether a disappearance was the builder being correct.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_model as M

N_RING = 16                     # logical sprites on the orbit

# Geometry. Chosen against the visible window and the reuse rule, not for looks.
#   X 36..316   wider than 256, so X=255 is crossed twice per orbit per sprite
#   Y 70..210   plus the RING-SHIFT sweep of +/-14 gives 56..224, and the
#               visible sprite band is 50..229
CENTRE_X, RADIUS_X = 176, 140
CENTRE_Y, RADIUS_Y = 140, 70
SHIFT_AMP = 14

TABLE = 256                     # phase resolution, one byte
PHASE_STEP = TABLE // N_RING     # 16: the per-sprite phase offset


def _round(x):
    """Java's Math.round, which is what KickAssembler would use.

    Python's round() is banker's rounding and would disagree with the generated
    table on every exact .5 -- a silent one-pixel divergence between the model
    and the engine, in a test whose whole job is to notice one-pixel
    divergences. Stated once, here, and used by the generator too.
    """
    return math.floor(x + 0.5)


def ring_x_table():
    """Absolute X per phase index. cos, so phase 0 is the right of the orbit."""
    return [CENTRE_X + _round(RADIUS_X * math.cos(2 * math.pi * k / TABLE))
            for k in range(TABLE)]


def ring_y_table():
    """Absolute Y per phase index."""
    return [CENTRE_Y + _round(RADIUS_Y * math.sin(2 * math.pi * k / TABLE))
            for k in range(TABLE)]


def ring_shift_table():
    """RING-SHIFT's vertical sweep: a TRIANGLE, deliberately not a sine.

    The point of the sweep is to move the batches through every raster (and so
    every badline) relationship. A sine lingers at its extremes and hurries
    through the middle, which would sample some raster offsets far more than
    others. A triangle sweeps uniformly, which is what a sweep is for.

    PHASED SO THAT INDEX 0 IS ZERO, which is not cosmetic. RING-SLOW and
    RING-FAST have no sweep at all, so their accumulator sits at index 0
    forever; if the table began at -SHIFT_AMP they would silently orbit
    fourteen rasters above RING-SHIFT's centre and the three modes would no
    longer share one geometry -- which is the whole basis for attributing any
    difference between them to phase velocity. Starting at zero means a zero
    velocity gives a zero offset, and ringPlace needs no special case.

        index    0      64      128     192     256
        value    0     +AMP      0     -AMP      0
    """
    def tri(s):
        if s <= 64:
            return s / 64.0
        if s <= 192:
            return (128 - s) / 64.0
        return (s - 256) / 64.0
    return [_round(SHIFT_AMP * tri(s)) for s in range(TABLE)]


RING_X = ring_x_table()
RING_Y = ring_y_table()
RING_SHIFT = ring_shift_table()


# Colour per logical index, from fxColour in src/fixtures.asm.
#
# SIXTEEN sprites, FIFTEEN colours. Black is the background, so a C64 has only
# fifteen usable sprite colours and one of them must be shared -- logical 11 and
# 15 are both medium grey. That is a hardware limit, not an oversight, and it is
# why the NUMERAL is the identity in this fixture and the colour is only
# corroboration: the sixteen bitmaps really are distinct, the colours cannot be.
FX_COLOUR = [1, 7, 13, 3, 5, 14, 10, 15, 2, 8, 4, 12, 9, 11, 6, 12]


class RingMode:
    """One P5 fixture: the same orbit, at a phase velocity, with or without sweep.

    phase_vel and shift_vel are 16-bit fixed point, 8 fractional bits, added to
    a 16-bit accumulator every frame. The table index is the high byte, so
    phase_vel = 0x0100 is exactly one table step per frame.
    """

    def __init__(self, index, name, phase_vel, shift_vel, note=""):
        self.index = index
        self.name = name
        self.phase_vel = phase_vel
        self.shift_vel = shift_vel
        self.note = note

    @property
    def orbit_frames(self):
        return TABLE * 256 // self.phase_vel

    @property
    def period(self):
        """Frames until the WHOLE fixture state repeats exactly."""
        def cycle(v):
            return 65536 // math.gcd(65536, v) if v else 1
        a, b = cycle(self.phase_vel), cycle(self.shift_vel)
        return a * b // math.gcd(a, b)

    def phase_index(self, frame):
        return ((frame * self.phase_vel) >> 8) & 0xff

    def shift(self, frame):
        if not self.shift_vel:
            return 0
        return RING_SHIFT[((frame * self.shift_vel) >> 8) & 0xff]

    def positions(self, frame):
        """(xs, ys) for logical sprites 0..15 on this frame. Closed form."""
        base = self.phase_index(frame)
        dy = self.shift(frame)
        idx = [(base + PHASE_STEP * i) & 0xff for i in range(N_RING)]
        return ([RING_X[k] for k in idx], [RING_Y[k] + dy for k in idx])

    def sorted_ids(self, frame):
        return M.sorted_order(self.positions(frame)[1])

    def build(self, frame):
        xs, ys = self.positions(frame)
        return M.build(ys, 0, xs, order=M.sorted_order(ys))


# Fixture indices continue the ladder: P0 0-4, P2 5-15, P3 16-23, P4 24-30.
P5_FIRST = 31
MODES = {
    31: RingMode(31, "RING-SLOW",  0x0100, 0x0000,
                 "one table step per frame: smooth, watchable, 5.1s per orbit"),
    32: RingMode(32, "RING-FAST",  0x0800, 0x0000,
                 "eight steps per frame: maximum sorter and admission churn"),
    33: RingMode(33, "RING-SHIFT", 0x0100, 0x0010,
                 "slow orbit swept vertically +/-14 rasters, for the badline sweep"),
}
FIXTURE_COUNT = P5_FIRST + len(MODES)


def census(mode, frames=None):
    """Everything P5 claims about a mode, counted from the geometry alone."""
    frames = frames or mode.period
    c = dict(frames=frames, accepted=set(), batches=set(), shapes=set(),
             reorders=0, tie_pairs=0, x255_up=0, x255_down=0, max_y_step=0,
             min_gap=99, min_spacing=99, mid_rasters=set(), pred_pairs=set(),
             slot_owners={s: set() for s in range(M.MUX_FIRST_SLOT,
                                                  M.MUX_FIRST_SLOT + M.MUX_SLOTS)},
             msb_states={s: set() for s in range(M.MUX_FIRST_SLOT,
                                                 M.MUX_FIRST_SLOT + M.MUX_SLOTS)})
    prev_order = prev_hi = prev_ys = None
    for f in range(frames):
        xs, ys = mode.positions(f)
        hi = [1 if x >= 256 else 0 for x in xs]
        if prev_hi is not None:
            c["x255_up"] += sum(1 for a, b in zip(prev_hi, hi) if a == 0 and b == 1)
            c["x255_down"] += sum(1 for a, b in zip(prev_hi, hi) if a == 1 and b == 0)
        if prev_ys is not None:
            c["max_y_step"] = max(c["max_y_step"],
                                  max(abs(a - b) for a, b in zip(ys, prev_ys)))
        prev_hi, prev_ys = hi, ys
        order = M.sorted_order(ys)
        if prev_order is not None and order != prev_order:
            c["reorders"] += 1
        prev_order = order
        c["tie_pairs"] += sum(1 for i in range(len(order) - 1)
                              if ys[order[i]] == ys[order[i + 1]])
        sy = sorted(ys)
        for k in range(len(sy) - M.MUX_SLOTS):
            c["min_gap"] = min(c["min_gap"], sy[k + M.MUX_SLOTS] - sy[k])
        s = M.build(ys, 0, xs, order=order)
        c["accepted"].add(s["accepted"])
        c["batches"].add(s["n_batches"])
        c["shapes"].add((s["n_batches"], tuple(b["count"] for b in s["batches"])))
        mid = [b["line"] for b in s["batches"][1:]]
        c["mid_rasters"].update(mid)
        for a, b in zip(mid, mid[1:]):
            c["min_spacing"] = min(c["min_spacing"], b - a)
        for e in s["entries"]:
            c["slot_owners"][e["slot"]].add(e["id"])
            c["msb_states"][e["slot"]].add(e["xhi"])
            if e["pred_id"] is not None:
                c["pred_pairs"].add((e["id"], e["pred_id"]))
    return c


def audit():
    """Invariants P5 asserts about every mode, from geometry alone."""
    bad = []
    for idx, mode in sorted(MODES.items()):
        c = census(mode)
        if c["accepted"] != {N_RING}:
            bad.append(f"{mode.name}: accepted varies {sorted(c['accepted'])} -- a "
                       f"human would see a sprite legitimately vanish")
        if c["min_gap"] < M.MIN_REUSE_GAP:
            bad.append(f"{mode.name}: min gap {c['min_gap']} < {M.MIN_REUSE_GAP}")
        if c["x255_up"] == 0 or c["x255_down"] == 0:
            bad.append(f"{mode.name}: no X=255 crossing in both directions")
        if c["tie_pairs"] == 0:
            bad.append(f"{mode.name}: never produces an equal-Y tie")
        for s, owners in c["slot_owners"].items():
            if len(owners) < 2:
                bad.append(f"{mode.name}: slot {s} only ever owned by {owners}")
        lo = min(min(ys) for ys in (mode.positions(f)[1] for f in range(mode.period)))
        hi = max(max(ys) for ys in (mode.positions(f)[1] for f in range(mode.period)))
        if lo < 50 or hi > 229:
            bad.append(f"{mode.name}: Y {lo}..{hi} leaves the visible band 50..229")
    return bad


if __name__ == "__main__":
    bad = audit()
    print("audit:", "clean" if not bad else "\n  ".join([""] + bad))
    for idx, mode in sorted(MODES.items()):
        c = census(mode)
        print(f"\n{idx} (${idx:02x}) {mode.name}: {mode.note}")
        print(f"   orbit {mode.orbit_frames}f ({mode.orbit_frames/50:.1f}s), "
              f"exact period {mode.period}f")
        print(f"   accepted {sorted(c['accepted'])}  batches {sorted(c['batches'])}  "
              f"shapes {len(c['shapes'])}  min gap {c['min_gap']}")
        print(f"   reorders {c['reorders']}/{c['frames']}  tie pairs {c['tie_pairs']}  "
              f"max Y step {c['max_y_step']}")
        print(f"   X255 up {c['x255_up']} down {c['x255_down']}  "
              f"mid-batch rasters {len(c['mid_rasters'])}  min spacing {c['min_spacing']}")
        print(f"   slot owners {({s: len(v) for s, v in c['slot_owners'].items()})}  "
              f"predecessor pairs {len(c['pred_pairs'])}")
    sys.exit(1 if bad else 0)
