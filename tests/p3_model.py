#!/usr/bin/env python3
"""The P3 independent model: scripted motion, and the P3 fixture set.

This states the trajectories a second time, from the rule rather than from the
6502, so that "the engine agrees with itself" is never mistaken for a proof.
The fixture tables in src/fixtures.asm are generated from THIS file by
tools/gen_p3_fixtures.py, and tests/test_p3.py then checks the running machine
against it -- so a hand edit to either side shows up as a disagreement rather
than as two copies of the same mistake.

The engine's motion primitive, restated:

    pos += vel
    if pos >= max:  pos = max;  vel = -vel
    if pos <= min:  pos = min;  vel = -vel

vel == 0 means the axis is untouched. Reversing on >= (not >) is what makes the
sequence a clean triangle with each endpoint appearing once.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_model as M

MAX_LOGICAL = 32
MAX_SCHED = M.MAX_SCHED
MIN_REUSE_GAP = M.MIN_REUSE_GAP
SPRITE_HEIGHT = M.SPRITE_HEIGHT
MUX_SLOTS = M.MUX_SLOTS

FK_STATIC, FK_MOTION = 0, 1


class Axis:
    """One bounded ping-pong axis."""

    def __init__(self, pos, vel=0, lo=None, hi=None):
        self.pos0 = pos
        self.vel0 = vel
        # A static axis still needs bounds the engine can store; it never reads
        # them because vel == 0 short-circuits first.
        self.lo = pos if lo is None else lo
        self.hi = pos if hi is None else hi
        self.pos = pos
        self.vel = vel

    def reset(self):
        self.pos, self.vel = self.pos0, self.vel0

    def step(self):
        if self.vel == 0:
            return self.pos
        n = self.pos + self.vel
        if n >= self.hi:
            n, self.vel = self.hi, -self.vel
        elif n <= self.lo:
            n, self.vel = self.lo, -self.vel
        self.pos = n
        return n

    def check(self, limit, what):
        """The precondition the p3s macro enforces at assembly time."""
        v = abs(self.vel0)
        assert 0 <= self.lo <= self.hi <= limit, f"{what}: bounds {self.lo}..{self.hi}"
        assert self.lo >= v, f"{what}: min {self.lo} within one step ({v}) of 0"
        assert self.hi + v <= limit, f"{what}: max {self.hi} within one step of {limit}"
        assert self.lo <= self.pos0 <= self.hi, f"{what}: start {self.pos0} outside bounds"


class Sprite:
    def __init__(self, y, x, yvel=0, ylo=None, yhi=None, xvel=0, xlo=None, xhi=None):
        self.Y = Axis(y, yvel, ylo, yhi)
        self.X = Axis(x, xvel, xlo, xhi)

    def reset(self):
        self.Y.reset(); self.X.reset()

    def step(self):
        # X first, then Y -- the order motionTick uses. It cannot matter (the
        # axes are independent) but the model states the engine's order rather
        # than a convenient one.
        self.X.step(); self.Y.step()

    def check(self, tag):
        self.Y.check(255, f"{tag} Y"); self.X.check(511, f"{tag} X")


class Fixture:
    def __init__(self, name, sprites, kind=FK_MOTION, note=""):
        self.name, self.sprites, self.kind, self.note = name, sprites, kind, note

    def reset(self):
        for s in self.sprites:
            s.reset()

    def step(self):
        for s in self.sprites:
            s.step()

    def ys(self):
        return [s.Y.pos for s in self.sprites]

    def xs(self):
        return [s.X.pos for s in self.sprites]

    def state(self):
        return list(zip(self.ys(), self.xs()))

    def build(self):
        return M.build(self.ys(), 0, self.xs())

    def frames(self, n):
        """Yield (motion_frame, ys, xs, schedule) for frames 0..n-1.

        Frame 0 is the loaded state BEFORE any motionTick, which is what the
        engine has after loadFixture and before the first main-loop pass.
        """
        self.reset()
        for f in range(n):
            if f:
                self.step()
            yield f, self.ys(), self.xs(), self.build()

    def check(self):
        """Static preconditions that must hold for every frame of the run."""
        for i, s in enumerate(self.sprites):
            s.check(f"{self.name}[{i}]")
        assert len(self.sprites) <= MAX_LOGICAL, f"{self.name}: too many sprites"


# ===========================================================================
# The P3 fixtures.
# ===========================================================================
# Geometry is derived from the rules P2 qualified, not chosen to look tidy:
#
#   * six leaders at Y0..Y0+5 with six reusers all sharing Yc merge into ONE
#     six-entry mid-screen batch when Yc >= Y0 + 5 + MIN_REUSE_GAP;
#   * a sprite at X >= 256 sets its slot's $D010 bit, one below clears it;
#   * Y order must stay ascending for every frame, because P3 has no sorter.
# loadFixture's column cursor, for STATIC fixtures only. Restated here because
# a static fixture's X is derived, not declared.
FX_COLUMN_X = [30, 60, 90, 120, 150, 180, 210]

LEAD_Y = 60
MERGE_Y = LEAD_Y + 5 + MIN_REUSE_GAP        # 98

# Six X positions that are unambiguously left/right of the 255/256 boundary and
# all comfortably on screen (a sprite is visible for roughly X 24..344).
X_LO = [40, 100, 160]
X_HI = [264, 300, 336]


def _msbflip():
    """Leaders and reusers on the same six slots, every slot's MSB inverted."""
    lead_x = [X_LO[0], X_HI[0], X_LO[1], X_HI[1], X_LO[2], X_HI[2]]
    reuse_x = [X_HI[0], X_LO[0], X_HI[1], X_LO[1], X_HI[2], X_LO[2]]
    s = [Sprite(LEAD_Y + i, lead_x[i]) for i in range(6)]
    s += [Sprite(MERGE_Y, reuse_x[i]) for i in range(6)]
    return s


def _x255():
    """Crossings of 255/256 on a slot whose other owner has a fixed MSB.

    Slot 2: a LEADER crosses, its reuser is fixed below 256.
    Slot 3: the leader is fixed above 256, its REUSER crosses.
    So both orders of (crossing, fixed) are covered on a reused slot.
    """
    s = [Sprite(LEAD_Y + 0, 230, xvel=+2, xlo=230, xhi=290),   # slot 2, crosses
         Sprite(LEAD_Y + 1, 300),                              # slot 3, MSB 1
         Sprite(LEAD_Y + 2, 60),
         Sprite(LEAD_Y + 3, 120),
         Sprite(LEAD_Y + 4, 180),
         Sprite(LEAD_Y + 5, 336)]
    s += [Sprite(MERGE_Y, 40),                                 # slot 2, MSB 0
          Sprite(MERGE_Y, 290, xvel=-2, xlo=230, xhi=290),     # slot 3, crosses
          Sprite(MERGE_Y, 100),
          Sprite(MERGE_Y, 264),
          Sprite(MERGE_Y, 160),
          Sprite(MERGE_Y, 300)]
    return s


def _ymove():
    """Legal moving-Y reuse: two RIGID groups, so Y order cannot change.

    Every leader shares one velocity and one relative phase, so the cluster
    translates as a body; likewise the reusers. Independent phases would let
    two leaders swap Y order, which P3 has no sorter for.
    """
    s = [Sprite(LEAD_Y + i, 40 + 34 * i, yvel=+1, ylo=LEAD_Y + i, yhi=LEAD_Y + 4 + i)
         for i in range(6)]
    s += [Sprite(105, 30 + 36 * i, yvel=+1, ylo=105, yhi=111) for i in range(6)]
    return s


def _gap33():
    """One candidate walking across the conservative admission threshold.

    Its predecessor is accepted entry 0, fixed at Y = LEAD_Y, so the reuse gap
    is exactly the candidate's Y minus LEAD_Y: 31, 32, 33, 34, 33, 32, ...
    which straddles MIN_REUSE_GAP (33) one raster at a time.
    """
    s = [Sprite(LEAD_Y + i, 40 + 34 * i) for i in range(6)]
    lo = LEAD_Y + MIN_REUSE_GAP - 2                     # gap 31
    hi = LEAD_Y + MIN_REUSE_GAP + 1                     # gap 34
    s += [Sprite(lo, 180, yvel=+1, ylo=lo, yhi=hi)]
    return s


def _shape():
    """Threshold crossing that RESHAPES the schedule around it.

    The candidate C sits between the leaders and a six-sprite merged group S.
    When C is admitted every S member's same-slot predecessor shifts by one, so
    S's last member is suddenly measured against C instead of against a leader
    -- and is rejected. Admitting one sprite therefore removes another, changes
    the batch count, changes the merged batch's width, and moves every S
    member onto a different physical slot, which changes $D010 too.
    """
    s = [Sprite(LEAD_Y + i, X_LO[i % 3]) for i in range(6)]
    lo = LEAD_Y + MIN_REUSE_GAP - 2                     # gap 31
    hi = LEAD_Y + MIN_REUSE_GAP + 1                     # gap 34
    s += [Sprite(lo, 180, yvel=+1, ylo=lo, yhi=hi)]
    # Alternating MSB, so a slot shift is also a $D010 change.
    s += [Sprite(120, X_HI[i % 3] if i % 2 else X_LO[i % 3]) for i in range(6)]
    return s


def _move6():
    """Baseline motion with no reuse at all: six sprites, six slots.

    One moves only in X, one only in Y, one diagonally, one is static, and the
    Y bands cannot overlap so ordering is safe by construction.
    """
    return [
        Sprite(60,  40, xvel=+2, xlo=40, xhi=200),                       # X only
        Sprite(85, 100, yvel=+1, ylo=85, yhi=105),                       # Y only
        Sprite(115, 60, xvel=+3, xlo=60, xhi=220,
               yvel=+1, ylo=115, yhi=135),                               # diagonal
        Sprite(150, 160),                                                # static
        Sprite(180, 250, xvel=-2, xlo=200, xhi=250),                     # X only
        Sprite(205, 220, yvel=+1, ylo=205, yhi=215),                     # Y only
    ]


def _motion12():
    """The integrated visual fixture: everything moving, six slots reused."""
    lx = [40, 90, 140, 190, 230, 300]
    rx = [300, 230, 200, 150, 100, 50]
    s = [Sprite(LEAD_Y + i, lx[i],
                xvel=(+2 if i % 2 == 0 else -2),
                xlo=(230 if i == 4 else max(30, lx[i] - 40)),
                xhi=(300 if i == 4 else lx[i] + 40),
                yvel=+1, ylo=LEAD_Y + i, yhi=LEAD_Y + 6 + i)
         for i in range(6)]
    s += [Sprite(110, rx[i],
                 xvel=(-2 if i % 2 == 0 else +2),
                 xlo=(230 if i == 0 else max(30, rx[i] - 40)),
                 xhi=(300 if i == 0 else rx[i] + 40),
                 yvel=+1, ylo=110, yhi=118)
          for i in range(6)]
    return s


# Fixture index -> Fixture. Indices continue the P0/P1/P2 numbering.
P3_FIRST = 16
FIXTURES = {
    16: Fixture("MOVE6",    _move6(),    note="baseline motion, no reuse"),
    17: Fixture("MSBFLIP6", _msbflip(),  note="six-slot reuse, every MSB inverted"),
    18: Fixture("X255",     _x255(),     note="moving crossings of 255/256"),
    19: Fixture("YMOVE",    _ymove(),    note="legal moving-Y reuse"),
    20: Fixture("GAP33",    _gap33(),    note="admission threshold crossing"),
    21: Fixture("SHAPE",    _shape(),    note="schedule shape mutation"),
    # MAXCAP is a STATIC fixture, so its X comes from loadFixture's seven-column
    # cursor, not from a record. The model has to derive it the same way or the
    # comparison fails on X while testing overflow -- which is exactly what it
    # did first time round.
    22: Fixture("MAXCAP",
                [Sprite(50 + 6 * i, FX_COLUMN_X[i % 7]) for i in range(30)],
                kind=FK_STATIC, note="MAX_SCHED overflow"),
    23: Fixture("MOTION12", _motion12(), note="integrated moving fixture"),
}
FIXTURE_COUNT = P3_FIRST + len(FIXTURES)


def y_order_ok(ys):
    return all(ys[i] <= ys[i + 1] for i in range(len(ys) - 1))


def audit(frames=240):
    """Every static precondition, plus every per-frame invariant P3 relies on."""
    problems = []
    for idx, fx in sorted(FIXTURES.items()):
        try:
            fx.check()
        except AssertionError as e:
            problems.append(f"{fx.name}: {e}")
            continue
        if fx.kind == FK_STATIC:
            continue
        for f, ys, xs, sched in fx.frames(frames):
            if not y_order_ok(ys):
                problems.append(f"{fx.name} frame {f}: Y order broken {ys}")
                break
            if sched["over_batch"]:
                problems.append(f"{fx.name} frame {f}: batch overflow")
                break
            for e in sched["entries"]:
                if e["gap"] is not None and e["gap"] < MIN_REUSE_GAP:
                    problems.append(
                        f"{fx.name} frame {f}: entry {e['acc']} accepted with gap {e['gap']}")
                    break
    return problems


if __name__ == "__main__":
    bad = audit()
    print("audit:", "clean" if not bad else "\n  ".join([""] + bad))
    for idx, fx in sorted(FIXTURES.items()):
        fx.reset()
        c = fx.build()
        shapes = set()
        if fx.kind == FK_MOTION:
            for f, ys, xs, s in fx.frames(120):
                shapes.add((s["accepted"], s["n_batches"], s["max_mid_batch"],
                            tuple(b["d010"] for b in s["batches"])))
        print(f"{idx:2d} {fx.name:<9s} n={len(fx.sprites):2d} acc={c['accepted']:2d} "
              f"ovf={c['overflow']} batches={c['n_batches']:2d} "
              f"maxMid={c['max_mid_batch']} d010={[hex(b['d010']) for b in c['batches']]} "
              f"distinct-shapes={len(shapes) if shapes else '-'}")
    sys.exit(1 if bad else 0)
