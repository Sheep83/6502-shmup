#!/usr/bin/env python3
"""Phase 6B: composable semantic movement — the model, the compiler, the proofs.

TWO KINDS OF CHECK LIVE HERE AND THEY ARE NOT EQUALLY STRONG.

The first kind asks whether the compiler emits the records this file expects.
That is Python checking Python and it can only ever prove the compiler agrees
with its author.

The second kind flies both versions through movement_sim -- the Phase 6A
interpreter, proved frame-for-frame against a real 6502 -- and asks whether the
PATHS agree. Continuity, the relative turns, the launch-heading independence
and the mirror are all settled that way, because they are claims about
behaviour rather than about bytes.
"""
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract_v2 as C                                     # noqa: E402
import migration_v6                                         # noqa: E402
import movement_semantic as sem                             # noqa: E402
import movement_sim as ms                                   # noqa: E402
import project_v6                                           # noqa: E402
from controller_v6 import EditorController, ControllerError  # noqa: E402
from validation_v6 import validate                          # noqa: E402

HERE = Path(__file__).resolve().parent
CANON = HERE / "levels/level1/level.v6.json"

PASS, FAIL = [], []


def ok(m, x=""):
    PASS.append(m)
    print(f"ok  - {m}" + (f"  [{x}]" if x else ""))


def check(m, c, x=""):
    if c:
        ok(m, x)
    else:
        FAIL.append(m)
        print(f"FAIL- {m}" + (f"  [{x}]" if x else ""))


def refuses(label, fn, fragment, exc=sem.CompileError):
    try:
        fn()
    except exc as e:
        check(label, fragment in str(e), str(e)[:80])
    else:
        check(label, False, "nothing was raised")


S = sem.Segment
EXIT = S(kind="EXIT")


def straight(f=20):
    return S(kind="STRAIGHT", frames=f)


def turn(d, steps=16, rate=sem.DEFAULT_RATE):
    return S(kind="TURN", direction=d, steps=steps, rate=rate)


def fly(segments, heading, *, x=250, y=100, frames=200):
    return ms.trace_program(sem.compile_segments(segments, heading),
                            x=x, y=y, heading=heading, frames=frames)


# =======================================================================
# 1. the segment model
# =======================================================================
check("a segment round-trips through its dict form",
      all(sem.Segment.from_dict(s.to_dict(), "p") == s
          for s in (straight(30), turn("LEFT", 8), turn("RIGHT", 32, 2),
                    S(kind="HOLD", frames=40),
                    S(kind="HOLD", frames=40, drift=2), EXIT)))
check("a segment carries ONLY the fields its kind uses",
      straight(30).to_dict() == {"kind": "STRAIGHT", "frames": 30}
      and turn("LEFT", 8).to_dict() == {"kind": "TURN", "direction": "LEFT",
                                        "steps": 8, "rate": 4}
      and EXIT.to_dict() == {"kind": "EXIT"})
check("a hold with no drift does not write drift keys at all",
      S(kind="HOLD", frames=9).to_dict() == {"kind": "HOLD", "frames": 9})
check("...and one with drift does",
      S(kind="HOLD", frames=9, drift=2).to_dict()
      == {"kind": "HOLD", "frames": 9, "drift": 2})
check("segments are immutable, so an undo snapshot cannot be aliased",
      isinstance(straight(1), tuple) is False
      and getattr(sem.Segment, "__hash__", None) is not None)

check("45, 90 and 180 degrees are 8, 16 and 32 heading steps",
      [sem.steps_for_degrees(d)[0] for d in (45, 90, 180, 360)] == [8, 16, 32, 64])
check("...and every preset is an exact number of steps",
      all(sem.steps_for_degrees(d)[1] and n == sem.steps_for_degrees(d)[0]
          for d, n in sem.TURN_PRESETS))
check("a step is 5.625 degrees, so a turn is presented in degrees",
      sem.degrees(8) == "45" and sem.degrees(12) == "67.5")


# =======================================================================
# 2. compilation: each kind becomes the right record
# =======================================================================
st = sem.compile_segments([straight(34), EXIT], 0)
check("STRAIGHT compiles to WM_STRAIGHT at the CURRENT heading's velocity",
      st[0].to_dict() == {"kind": "STRAIGHT", "frames": 34,
                          "vx": ms.HEAD_VX[0], "vy": ms.HEAD_VY[0]})
st = sem.compile_segments([straight(34), EXIT], 16)
check("...so the same segment from a different heading gets the right one",
      (st[0].vx, st[0].vy) == (ms.HEAD_VX[16], ms.HEAD_VY[16]), f"{st[0].to_dict()}")

st = sem.compile_segments([turn("RIGHT", 16), EXIT], 0)
check("TURN RIGHT compiles to WM_ARC", st[0].kind == "ARC")
st = sem.compile_segments([turn("LEFT", 16), EXIT], 0)
check("TURN LEFT compiles to WM_ARC_MIRROR", st[0].kind == "ARC_MIRROR")
check("EVERY compiled turn uses CONT, never an absolute heading -- which is "
      "the whole of 'continuity is the default'",
      all(s.entry_heading == "CONT"
          for s in sem.compile_segments(
              [turn("RIGHT"), straight(5), turn("LEFT", 8), EXIT], 20)
          if s.kind in C.ARC_KINDS))

st = sem.compile_segments([S(kind="HOLD", frames=48, drift=2), turn("RIGHT", 4),
                           EXIT], 16)
check("HOLD compiles to WM_HOLD drifting ALONG the heading it holds",
      st[0].to_dict() == {"kind": "HOLD", "frames": 48,
                          "vx": sem.velocity_at(16, 2)[0],
                          "vy": sem.velocity_at(16, 2)[1]},
      str(st[0].to_dict()))
check("EXIT compiles to a bare WM_EXIT",
      sem.compile_segments([straight(4), EXIT], 0)[-1].to_dict() == {"kind": "EXIT"})

check("compilation is deterministic",
      [s.to_dict() for s in sem.compile_segments(
          [straight(7), turn("LEFT", 9, 3), S(kind="HOLD", frames=5, drift=4),
           turn("RIGHT", 3), EXIT], 21)]
      == [s.to_dict() for s in sem.compile_segments(
          [straight(7), turn("LEFT", 9, 3), S(kind="HOLD", frames=5, drift=4),
           turn("RIGHT", 3), EXIT], 21)])

check("a program of turns only is heading-INdependent and reusable",
      not sem.heading_dependent([turn("LEFT", 8), turn("RIGHT", 8), EXIT]))
check("...and one containing a STRAIGHT is not, because the velocity is "
      "baked into the record",
      sem.heading_dependent([straight(5), EXIT]))


# =======================================================================
# 3. the refusals -- never patched around
# =======================================================================
refuses("a program that does not end in EXIT is refused",
        lambda: sem.compile_segments([straight(5)], 0), "must end with EXIT")
refuses("a segment after EXIT is refused",
        lambda: sem.compile_segments([EXIT, straight(5), EXIT], 0), "terminal")
refuses("an empty program is refused",
        lambda: sem.compile_segments([], 0), "at least an EXIT")
refuses("a zero-frame STRAIGHT is refused",
        lambda: sem.compile_segments([straight(0), EXIT], 0), "frames must be")
refuses("a zero-step TURN is refused",
        lambda: sem.compile_segments([turn("RIGHT", 0), EXIT], 0), "steps must be")
refuses("a zero-rate TURN is refused",
        lambda: sem.compile_segments([turn("RIGHT", 8, 0), EXIT], 0), "rate must be")
refuses("a count that will not fit one authored byte is refused",
        lambda: sem.compile_segments([straight(300), EXIT], 0), "frames must be")
refuses("a drift faster than an arc's own speed is refused",
        lambda: sem.compile_segments(
            [S(kind="HOLD", frames=5, drift=40), EXIT], 0), "drift must be")
refuses("a launch heading outside 0..63 is refused",
        lambda: sem.compile_segments([straight(5), EXIT], 99), "not a heading")

# THE ONE THAT MATTERS MOST, because the engine would accept it and the object
# would hold a pool slot for the rest of the level.
refuses("a HOLD with no drift immediately before EXIT is refused",
        lambda: sem.compile_segments([S(kind="HOLD", frames=30), EXIT], 0),
        "would inherit no velocity")
check("...but a HOLD with a drift before EXIT is fine",
      len(sem.compile_segments([S(kind="HOLD", frames=30, drift=2), EXIT], 0)) == 2)
check("...and so is a HOLD followed by a turn",
      len(sem.compile_segments(
          [S(kind="HOLD", frames=30), turn("RIGHT", 4), EXIT], 0)) == 3)


# =======================================================================
# 4. CONTINUITY, proved by flying it
# =======================================================================
# Segment N+1 must start from the state segment N actually produced, not from
# anything restated by the author.
segs = [straight(20), turn("RIGHT", 16), straight(20), turn("LEFT", 8), EXIT]
t = fly(segs, 0, frames=200)
bounds = []
cur = -1
for f in t:
    if f.stage_index != cur:
        cur = f.stage_index
        bounds.append(f.frame)
check("each segment hands on to the next at the frame its own length ends",
      bounds[:5] == [0, 20, 20 + 16 * 4, 20 + 16 * 4 + 20,
                     20 + 16 * 4 + 20 + 8 * 4],
      str(bounds[:5]))
# THE HEADING EACH SEGMENT HANDS ON. A turn's LAST rotation lands on the very
# frame it hands over (Phase 6A established this against the real 6502), so the
# continuity claim is "segment N+1 starts on the heading segment N produced",
# not "the heading does not change across the boundary" -- it changes there
# precisely because that frame is the turn's last step.
check("a STRAIGHT hands on the heading it was given, unchanged",
      t[bounds[1]].heading == t[bounds[1] - 1].heading == 0)
check("a TURN RIGHT 90 hands on exactly launch + 16 steps",
      t[bounds[2]].heading == 16, str(t[bounds[2]].heading))
check("the STRAIGHT after it inherits that heading rather than restating one",
      t[bounds[3]].heading == 16
      and (t[bounds[2]].vx, t[bounds[2]].vy) == (ms.HEAD_VX[16], ms.HEAD_VY[16]),
      f"({t[bounds[2]].vx}, {t[bounds[2]].vy})")
check("a TURN LEFT 45 after that hands on 16 - 8 = 8",
      t[bounds[4]].heading == 8, str(t[bounds[4]].heading))
# Continuity of POSITION is asked on the eight-bit ring logY actually lives on:
# this trace flies past the bottom of the world and 255 -> 0 is the engine's
# own wrap, not a discontinuity in the path.
check("no segment boundary makes the object jump position",
      all(abs(b.x - a.x) <= 2 and min((b.y - a.y) % 256, (a.y - b.y) % 256) <= 2
          for a, b in zip(t, t[1:])))


# =======================================================================
# 4b. TRAJECTORY CONTINUITY — the invariant, asserted on the TANGENT
# =======================================================================
# THE THING THAT WENT WRONG AND WHY THIS SECTION EXISTS. The first version of
# this phase asserted that a turn INHERITED THE STORED HEADING, which it
# always did -- and a visible 45-degree kink still appeared, because
# WM_STRAIGHT writes a velocity and never touches wmPhase. WM_HEAD_CONT was
# faithfully inheriting a heading that had gone stale against the direction of
# travel. So the assertion below is about the TANGENT, measured on the flown
# path, and it would have caught that bug where a heading assertion could not.
#
#     end tangent of segment N == start tangent of segment N+1
#
# to within the arc's own per-step rotation, because that is the granularity
# the engine turns in and demanding more would flag every arc in the game.

check("the continuity tolerance is one heading step, the arc's own quantum",
      11.0 < sem._MIN_QUANTUM < 13.0, f"{sem._MIN_QUANTUM:.2f} deg")


def continuous(label, segs, headings=range(64), show=True):
    worst, where, at = 0.0, None, None
    ran = 0
    for h in headings:
        try:
            st = sem.compile_segments(segs, h)
        except sem.CompileError:
            continue                        # refused, so it never reaches a path
        ran += 1
        for b in sem.continuity_breaks(st, h):
            if b["degrees"] > worst:
                worst, where, at = b["degrees"], b, h
    if show:
        check(f"{label}: no kink at any segment boundary, {ran} launch headings",
              where is None,
              "" if where is None else
              f"{worst:.1f} deg at {where['from_kind']}->{where['to_kind']}, "
              f"launch {at}")
    return where is None


HOLD = lambda f=20, d=0: S(kind="HOLD", frames=f, drift=d)

continuous("STRAIGHT -> TURN", [straight(20), turn("RIGHT", 16), EXIT])
continuous("STRAIGHT -> TURN LEFT", [straight(20), turn("LEFT", 16), EXIT])
continuous("TURN -> STRAIGHT -> TURN",
           [turn("LEFT", 8), straight(20), turn("RIGHT", 16), EXIT])
continuous("STRAIGHT -> TURN -> STRAIGHT",
           [straight(12), turn("RIGHT", 32), straight(12), EXIT])
continuous("HOLD (still) -> TURN", [straight(10), HOLD(), turn("RIGHT", 16), EXIT])
continuous("HOLD (drifting) -> TURN",
           [straight(10), HOLD(20, 2), turn("RIGHT", 16), EXIT])
continuous("HOLD (drifting) -> STRAIGHT",
           [straight(10), HOLD(20, 4), straight(10), EXIT])
continuous("TURN -> HOLD -> TURN",
           [turn("RIGHT", 12), HOLD(10, 2), turn("LEFT", 20), EXIT])
continuous("S-curve", [straight(10)] + sem.macro_s_curve("LEFT") + [EXIT])
continuous("zigzag", [straight(10)] + sem.macro_zigzag("RIGHT") + [EXIT])
continuous("loop", [straight(10)] + sem.macro_loop("RIGHT") + [EXIT])
continuous("every kind at once",
           [straight(10), turn("LEFT", 12), HOLD(15, 2), turn("RIGHT", 20, 2),
            straight(8), HOLD(10), turn("LEFT", 32), EXIT])

# EVERY TURN ANGLE, BOTH WAYS, EVERY RADIUS -- the combination the report was
# about, swept rather than sampled.
bad = []
for _deg, steps in sem.TURN_PRESETS:
    for d in ("LEFT", "RIGHT"):
        for rate in (1, 2, 4, 6, 8):
            if not continuous("", [straight(15), turn(d, steps, rate),
                                   straight(15), EXIT],
                              headings=(0, 5, 14, 27, 37, 48, 63), show=False):
                bad.append((steps, d, rate))
check("STRAIGHT -> TURN -> STRAIGHT is continuous for every preset angle, "
      "both directions, five radii, seven launch headings", not bad,
      str(bad[:4]))

# RANDOMISED, because a handwritten list only covers what its author thought of.
import random                                               # noqa: E402
random.seed(20260921)


def _rnd():
    k = random.choice(("STRAIGHT", "TURN", "HOLD"))
    if k == "STRAIGHT":
        return straight(random.randint(1, 40))
    if k == "TURN":
        return turn(random.choice(("LEFT", "RIGHT")), random.randint(1, 70),
                    random.randint(1, 8))
    return HOLD(random.randint(1, 40), random.randint(0, 6))


ran = refused = 0
kinks = []
for _ in range(2500):
    segs = [_rnd() for _ in range(random.randint(1, 6))] + [EXIT]
    h = random.randrange(64)
    try:
        st = sem.compile_segments(segs, h)
    except sem.CompileError:
        refused += 1
        continue
    ran += 1
    kinks += sem.continuity_breaks(st, h)
check(f"2500 randomly generated semantic programs at random launch headings "
      f"produce no kink anywhere", not kinks,
      f"{ran} compiled, {refused} refused, {len(kinks)} kinks")

# AND THE CASE FROM THE BUG REPORT, in raw records, which must still kink --
# the semantic vocabulary is what guarantees continuity, not the engine.
dive_raw = [project_v6.MovementStage(kind="STRAIGHT", frames=20, vx=4, vy=4),
            project_v6.MovementStage(kind="ARC", steps=40, frames_per_step=4,
                                     entry_heading="CONT"),
            project_v6.MovementStage(kind="EXIT")]
breaks = sem.continuity_breaks(dive_raw, 0)
check("a RAW program can still kink -- the reported 'dive' case is detected, "
      "not hidden",
      len(breaks) == 1 and 44 < breaks[0]["degrees"] < 46,
      f"{breaks[0]['degrees']:.1f} deg" if breaks else "no break found")
check("...and the diagnosis names the divergence: travelling one way, stored "
      "heading pointing another",
      breaks[0]["travel_heading"] == 8 and breaks[0]["stored_heading"] == 0,
      f"travel ~{breaks[0]['travel_heading']}, stored {breaks[0]['stored_heading']}")
dive_fixed = list(dive_raw)
dive_fixed[1] = project_v6.MovementStage(kind="ARC", steps=40, frames_per_step=4,
                                         entry_heading=8)
check("...and entering that arc on the heading it is ACTUALLY travelling makes "
      "it continuous, with no engine change",
      not sem.continuity_breaks(dive_fixed, 0))
check("nearest_heading finds that heading from the velocity alone",
      sem.nearest_heading(4, 4) == 8 and sem.nearest_heading(6, 0) == 0
      and sem.nearest_heading(0, 0) is None)

# The runtime limitation, stated as a test so it cannot quietly change.
check("a drift is only faithful to its heading at speeds the integer velocity "
      "can carry: 1 and 3 fail on some headings, 2/4/5/6 hold everywhere",
      [len(sem.faithful_drifts(h)) for h in range(64)].count(6) < 64
      and all(sem.drift_is_faithful(h, d) for h in range(64) for d in (2, 4, 5, 6)),
      f"drift 1 works on {sum(sem.drift_is_faithful(h,1) for h in range(64))}/64 "
      f"headings, drift 3 on {sum(sem.drift_is_faithful(h,3) for h in range(64))}/64")
refuses("...and an unfaithful drift is REFUSED with the remedy named, never "
        "rounded into a kink",
        lambda: sem.compile_segments([straight(5), HOLD(10, 1),
                                      turn("RIGHT", 8), EXIT], 37),
        "does not point along the heading")


# =======================================================================
# 4c. compass names, and one program launched two ways
# =======================================================================
check("the eight compass points map onto exact headings",
      dict(sem.COMPASS) == {"Right": 0, "Down-Right": 8, "Down": 16,
                            "Down-Left": 24, "Left": 32, "Up-Left": 40,
                            "Up": 48, "Up-Right": 56})
check("...and they mean what they say in the ENGINE's own table: Right is +x, "
      "Down is +y (screen coordinates, y downward)",
      (ms.HEAD_VX[0], ms.HEAD_VY[0]) == (6, 0)
      and (ms.HEAD_VX[16], ms.HEAD_VY[16]) == (0, 6)
      and (ms.HEAD_VX[32], ms.HEAD_VY[32]) == (-6, 0)
      and (ms.HEAD_VX[48], ms.HEAD_VY[48]) == (0, -6))
check("a heading is named for a human and still carries its exact value",
      sem.heading_name(16) == "Down (16)" and sem.heading_name(0) == "Right (0)")
check("...and an off-point heading is shown as the number it is, not rounded "
      "to a compass point",
      sem.heading_name(12) == "12" and sem.heading_label(12) == "12")
check("every compass point round-trips name -> heading -> name",
      all(sem.heading_label(h) == n for n, h in sem.COMPASS))

# THE CASE FROM THE REQUEST: one reusable program, two launch directions.
two_ways = [straight(30), turn("RIGHT", sem.QUARTER_TURN), straight(30), EXIT]
paths = {}
for name in ("Right", "Down"):
    h = sem.COMPASS_HEADING[name]
    st = sem.compile_segments(two_ways, h)
    paths[name] = (st, ms.trace_program(st, x=200, y=90, heading=h, frames=200))
    check(f"launched {name}: the program compiles and is continuous at BOTH "
          f"segment boundaries", not sem.continuity_breaks(st, h))

r_st, r_t = paths["Right"]
d_st, d_t = paths["Down"]
check("launched Right, the straights fly +x then +y (the quarter turn took it "
      "from Right to Down)",
      [(s.vx, s.vy) for s in r_st if s.kind == "STRAIGHT"] == [(6, 0), (0, 6)],
      str([(s.vx, s.vy) for s in r_st if s.kind == "STRAIGHT"]))
check("launched Down, the SAME segments fly +y then -x (Down to Left)",
      [(s.vx, s.vy) for s in d_st if s.kind == "STRAIGHT"] == [(0, 6), (-6, 0)],
      str([(s.vx, s.vy) for s in d_st if s.kind == "STRAIGHT"]))
check("...so the second path is the first rotated by exactly a quarter turn",
      all((g.heading - f.heading) % C.WM_HEAD_LEN == sem.QUARTER_TURN
          for f, g in zip(r_t, d_t)))
check("...with identical stage timing, because only the entry state differed",
      [f.stage_index for f in r_t] == [g.stage_index for g in d_t])
check("and the author never wrote a direction into a STRAIGHT: it carries a "
      "duration and nothing else",
      all(s.to_dict() == {"kind": "STRAIGHT", "frames": 30}
          for s in two_ways if s.kind == "STRAIGHT"))

# Launching from all eight points keeps the shape and just turns it.
shapes = {}
for name, h in sem.COMPASS:
    st = sem.compile_segments(two_ways, h)
    t = ms.trace_program(st, x=250, y=120, heading=h, frames=200)
    shapes[name] = [f.stage_index for f in t]
    if sem.continuity_breaks(st, h):
        check(f"launched {name} is continuous", False)
        break
else:
    ok("the same program is continuous launched from all eight compass points")
check("...and flies the same shape from each, only rotated",
      len({tuple(v) for v in shapes.values()}) == 1)


# =======================================================================
# 4d. STRAIGHT: Continue, or an explicit direction  (Phase 6B.1)
# =======================================================================
import compass_ui as cu                                     # noqa: E402

check("a STRAIGHT is Continue by default, and says so",
      straight(20).heading is None
      and straight(20).to_dict() == {"kind": "STRAIGHT", "frames": 20})
check("...so a program written before this existed loads unchanged, as "
      "Continue",
      sem.Segment.from_dict({"kind": "STRAIGHT", "frames": 20}, "p").heading
      is None)
check("an explicit direction is stored, and only then",
      S("STRAIGHT", frames=20, heading=16).to_dict()
      == {"kind": "STRAIGHT", "frames": 20, "heading": 16})
check("...and round-trips",
      sem.Segment.from_dict({"kind": "STRAIGHT", "frames": 20, "heading": 16},
                            "p").heading == 16)

# 1. Continue inherits.
for launch in (0, 9, 16, 33, 55):
    st = sem.compile_segments([straight(20), EXIT], launch)
    if (st[0].vx, st[0].vy) != (ms.HEAD_VX[launch], ms.HEAD_VY[launch]):
        check(f"Continue inherits the launch direction ({launch})", False)
        break
else:
    ok("STRAIGHT [Continue] inherits the incoming direction, from every "
       "launch heading tried")

# 2. An explicit direction establishes exactly that heading.
bad = []
for h in range(C.WM_HEAD_LEN):
    st = sem.compile_segments([S("STRAIGHT", frames=10, heading=h), EXIT], 0)
    if (st[0].vx, st[0].vy) != (ms.HEAD_VX[h], ms.HEAD_VY[h]):
        bad.append(h)
check("an explicit STRAIGHT direction establishes exactly that engine "
      "heading, for all 64", not bad, str(bad[:5]))
check("...whatever the launch heading was",
      all(sem.compile_segments([S("STRAIGHT", frames=10, heading=16), EXIT],
                               L)[0].to_dict()
          == {"kind": "STRAIGHT", "frames": 10, "vx": 0, "vy": 6}
          for L in range(0, 64, 7)))

# 3. STRAIGHT down -> quarter turn -> STRAIGHT Continue: continuous except at
#    the deliberate establishment.
for d, sign in (("LEFT", -1), ("RIGHT", 1)):
    segs = [S("STRAIGHT", frames=20, heading=16), turn(d, sem.QUARTER_TURN),
            straight(20), EXIT]
    st = sem.compile_segments(segs, 0)
    intent = sem.intentional_breaks(segs)
    check(f"STRAIGHT down -> QUARTER {d} -> STRAIGHT Continue is continuous "
          f"apart from the direction it deliberately sets",
          not sem.continuity_breaks(st, 0, intentional=intent),
          str(sem.continuity_breaks(st, 0, intentional=intent))[:80])
    check(f"...and the {d} quarter turn really goes that way from Down",
          sem.final_heading(segs, 0)
          == (16 + sign * sem.QUARTER_TURN) % C.WM_HEAD_LEN)
    check("...with the intentional break declared, not hidden",
          intent == frozenset({0}))
# AN EXPLICIT DIRECTION ON THE FIRST SEGMENT IS NOT A BREAK AT ALL -- there is
# no preceding trajectory for it to break from, it simply starts that way.
check("an explicit direction on the FIRST segment introduces no discontinuity, "
      "because there is nothing before it",
      not sem.continuity_breaks(
          sem.compile_segments([S("STRAIGHT", frames=20, heading=16),
                                turn("LEFT", 16), straight(20), EXIT], 0), 0))
# MID-PROGRAM IT IS A REAL ONE, and it is skipped because it was ASKED for.
_mid = [straight(20), S("STRAIGHT", frames=20, heading=32), EXIT]
check("a mid-program explicit direction is a genuine change of trajectory",
      len(sem.continuity_breaks(sem.compile_segments(_mid, 0), 0)) == 1,
      str([(b["stage"], round(b["degrees"]))
           for b in sem.continuity_breaks(sem.compile_segments(_mid, 0), 0)]))
check("...reported as intentional rather than as a fault",
      sem.intentional_breaks(_mid) == frozenset({1})
      and not sem.continuity_breaks(sem.compile_segments(_mid, 0), 0,
                                    intentional=sem.intentional_breaks(_mid)))

# 4. A relative program still rotates with the launch heading.
rel = [straight(20), turn("RIGHT", sem.QUARTER_TURN), straight(20), EXIT]
check("a program whose first STRAIGHT is Continue stays relative...",
      sem.heading_dependent(rel) and not sem.is_self_directing(rel))
base = fly(rel, 0, frames=200)
check("...and rotates with the wave's launch heading",
      all(all((g.heading - f.heading) % C.WM_HEAD_LEN == h
              for f, g in zip(base, fly(rel, h, frames=200)))
          for h in (8, 16, 40)))
selfdir = [S("STRAIGHT", frames=20, heading=16), turn("RIGHT", 16), EXIT]
check("...while one that sets its own direction is self-directing and no "
      "longer depends on the launch",
      sem.is_self_directing(selfdir) and not sem.heading_dependent(selfdir))
check("...flying the identical path from every launch heading",
      len({tuple((f.x, f.y) for f in fly(selfdir, h, frames=150))
           for h in range(0, 64, 5)}) == 1)

# 5 & 6. The compass: deterministic quantisation, everywhere.
check("every compass point maps to its exact engine heading",
      all(cu.heading_from_point(math.cos(2 * math.pi * h / 64) * 40,
                                math.sin(2 * math.pi * h / 64) * 40) == h
          for _n, h in sem.COMPASS))
check("...and so does every one of the 64 headings",
      all(cu.heading_from_point(math.cos(2 * math.pi * h / 64) * 40,
                                math.sin(2 * math.pi * h / 64) * 40) == h
          for h in range(64)))
_step = 2 * math.pi / 64
check("dragging anywhere inside a heading's cell resolves to that heading, "
      "at every one of the 64 boundaries",
      all(cu.heading_from_point(math.cos((h + off) * _step) * 40,
                                math.sin((h + off) * _step) * 40) == h
          for h in range(64) for off in (-0.45, -0.2, 0.0, 0.2, 0.45)))
check("...and the radius the pointer is at makes no difference",
      all(cu.heading_from_point(math.cos(19 * _step) * r,
                                math.sin(19 * _step) * r) == 19
          for r in (5, 20, 50, 200)))
check("dead centre asks for no direction rather than guessing one",
      cu.heading_from_point(0, 0) is None)
check("shift-snap lands on one of the eight named points, always",
      {cu.snap_to_point(h) for h in range(64)}
      == {h for _n, h in sem.COMPASS})

# 7 & 8. Handedness and radius.
for start in (0, 16, 37, 58):
    for name, steps in sem.NAMED_TURNS:
        for d, sign in (("LEFT", -1), ("RIGHT", 1)):
            got = sem.final_heading([turn(d, steps)], start)
            if got != (start + sign * steps) % C.WM_HEAD_LEN:
                check(f"{name} {d} from {start}", False, str(got))
                break
        else:
            continue
        break
    else:
        continue
    break
else:
    ok("Quarter, Half and Loop turn the right way from every representative "
       "heading, both handednesses")
bad = []
for _label, radius in sem.RATE_PRESETS:
    for d in ("LEFT", "RIGHT"):
        segs = [straight(10), turn(d, sem.QUARTER_TURN, radius), straight(10),
                EXIT]
        for h in (0, 21, 48):
            if sem.continuity_breaks(sem.compile_segments(segs, h), h):
                bad.append((_label, d, h))
check("every radius preset keeps the path continuous", not bad, str(bad[:3]))
check("...and radius maps deterministically to the engine's frames-per-step",
      [r for _n, r in sem.RATE_PRESETS] == [2, 4, 6])


# =======================================================================
# 4e. Drafts: preview tolerance, production strictness  (Phase 6B.1)
# =======================================================================
prog_a = [S("STRAIGHT", frames=20, heading=16)]
prog_b = prog_a + [turn("RIGHT", sem.QUARTER_TURN)]
prog_c = prog_b + [straight(20)]
prog_d = prog_c + [EXIT]

for label, segs, used, complete in (("A", prog_a, 1, False),
                                    ("A+B", prog_b, 2, False),
                                    ("A+B+C", prog_c, 3, False),
                                    ("A+B+C+EXIT", prog_d, 4, True)):
    d = sem.compile_draft(segs, 0)
    check(f"draft {label}: the whole authored prefix previews",
          d.used == used and d.complete is complete,
          f"used {d.used}/{len(segs)}, complete {d.complete}")
check("an incomplete draft is terminated for the simulator but NOT for the "
      "project",
      sem.compile_draft(prog_c, 0).stages[-1].kind == "EXIT"
      and len(sem.compile_draft(prog_c, 0).authored_stages) == 3)
check("...and each step previews strictly more than the last",
      [sem.compile_draft(p, 0).frames for p in (prog_a, prog_b, prog_c)]
      == sorted({sem.compile_draft(p, 0).frames
                 for p in (prog_a, prog_b, prog_c)}))
check("a finished program runs to the despawn rule instead of a frame cap",
      sem.compile_draft(prog_d, 0).frames is None)

broken = prog_a + [turn("RIGHT", 0), straight(20)]
d = sem.compile_draft(broken, 0)
check("a malformed later segment still renders the valid prefix",
      d.used == 1 and len(d.authored_stages) == 1, f"used {d.used}")
check("...and says which segment stopped it, and why",
      d.stopped_at == 1 and "steps must be" in (d.reason or ""),
      f"stopped_at {d.stopped_at}: {(d.reason or '')[:50]}")
check("nothing is auto-added: an unfinished draft has no EXIT segment",
      not any(g.kind == "EXIT" for g in prog_c))

_P2 = migration_v6.load_any(CANON).project
_c2 = EditorController(_P2)
_j = _c2.add_movement_program("draft_probe")
for label, segs, should_pass in (("A", prog_a, False), ("A+B", prog_b, False),
                                 ("A+B+C", prog_c, False),
                                 ("A+B+C+EXIT", prog_d, True),
                                 ("malformed", broken, False)):
    _P2.movement_programs[_j].segments = list(segs)
    _c2._recompile(_P2.movement_programs[_j])
    res = validate(_P2)
    check(f"production validation of draft {label}: "
          f"{'accepted' if should_pass else 'REFUSED'}",
          res.ok is should_pass,
          "" if res.ok is should_pass else
          str([i.code for i in res.errors][:2]))
check("the refusal names the program and the reason",
      any(i.code == "movement.unfinished" and "draft_probe" in i.message
          for i in validate(_P2).errors)
      if not validate(_P2).ok else True)
_P2.movement_programs[_j].segments = list(prog_d)
_c2._recompile(_P2.movement_programs[_j])
check("adding EXIT makes the same draft production-valid immediately",
      validate(_P2).ok)


# =======================================================================
# 5. relative turns: the angle, from any launch heading
# =======================================================================
for deg, steps in sem.TURN_PRESETS:
    for start in (0, 5, 17, 40, 63):
        for d, sign in (("RIGHT", 1), ("LEFT", -1)):
            t = fly([turn(d, steps), straight(4), EXIT], start, frames=steps * 4 + 20)
            want = (start + sign * steps) % C.WM_HEAD_LEN
            got = next(f.heading for f in t if f.stage_index == 1)
            if got != want:
                check(f"TURN {d} {deg} from heading {start}", False,
                      f"want {want}, got {got}")
                break
    else:
        continue
    break
else:
    ok("every preset turn, both ways, from five launch headings, ends on "
       "exactly the heading the angle says  [60 flights]")

check("a 360-degree turn is one record and comes back to where it started",
      len(sem.compile_segments([turn("RIGHT", 64), straight(4), EXIT], 9)) == 3
      and next(f.heading for f in fly([turn("RIGHT", 64), straight(4), EXIT], 9,
                                      frames=64 * 4 + 20) if f.stage_index == 1) == 9)

check("an author never restates a heading: no compiled arc names one",
      not any(isinstance(s.entry_heading, int)
              for s in sem.compile_segments(
                  [turn("RIGHT", 16), turn("LEFT", 32), turn("RIGHT", 8), EXIT], 7)))


# =======================================================================
# 6. the same program, launched differently
# =======================================================================
prog = [straight(20), turn("RIGHT", 16), straight(15), turn("LEFT", 8), EXIT]
base = fly(prog, 0, frames=160)
for h in (8, 16, 32, 50):
    t = fly(prog, h, frames=160)
    check(f"launched on heading {h} the path is the SAME manoeuvre, rotated",
          [f.stage_index for f in t] == [f.stage_index for f in base]
          and all((f.heading - g.heading) % C.WM_HEAD_LEN == h
                  for f, g in zip(t, base)))


# =======================================================================
# 7. macros
# =======================================================================
sc = sem.macro_s_curve("LEFT", 16)
check("an S-curve is two opposite turns", [s.direction for s in sc] == ["LEFT", "RIGHT"])
t = fly(sc + [straight(4), EXIT], 16, frames=160)
turns = [(f.frame, 1 if (b.heading - f.heading) % 64 < 32 else -1)
         for f, b in zip(t, t[1:]) if b.heading != f.heading]
flips = [i for i in range(1, len(turns)) if turns[i][1] != turns[i - 1][1]]
check("...and flown, its curvature reverses exactly once", len(flips) == 1)
check("...returning to the heading it started on", t[-1].heading == 16,
      str(t[-1].heading))

# ---- the named pieces are ANGLES of the one turn, not separate kinds -----
check("quarter, half and full are 90, 180 and 360 degrees",
      [sem.degrees(n) for _n, n in
       [(a, b) for a, b in sem.NAMED_TURNS]] == ["90", "180", "360"])
check("...and all three are the SAME segment kind, differing by a number",
      len({S(kind="TURN", direction="RIGHT", steps=n).kind
           for _label, n in sem.NAMED_TURNS}) == 1)
for label, steps in sem.NAMED_TURNS:
    for radius in (2, 4, 6):
        seg = S(kind="TURN", direction="RIGHT", steps=steps, rate=radius)
        st2 = sem.compile_segments([seg, straight(4), EXIT], 0)
        if not (len(st2) == 3 and st2[0].steps == steps
                and st2[0].frames_per_step == radius):
            check(f"{label} at radius {radius}", False, str(st2[0].to_dict()))
            break
    else:
        continue
    break
else:
    ok("every named turn takes a free radius and stays one record  "
       "[quarter/half/full x tight/normal/wide]")
check("radius really changes the size of the turn, not its angle",
      (lambda a, b: a[-1].heading == b[-1].heading
       and max(f.x for f in a) != max(f.x for f in b))(
          fly([turn("RIGHT", 16, 2), straight(2), EXIT], 0, frames=90),
          fly([turn("RIGHT", 16, 6), straight(2), EXIT], 0, frames=140)))

# ---- zigzag ----------------------------------------------------------
zz = sem.macro_zigzag("RIGHT", swing=8, repeats=2)
check("a zigzag is built from the same turn primitive and nothing else",
      all(s.kind == "TURN" for s in zz))
check("...costing 2*repeats + 1 records, which is visible before it is paid",
      len(zz) == 5 and sem.cost(zz + [straight(4), EXIT], 0)[0] == 7,
      f"{len(zz)} segments")
for start in (0, 11, 40):
    z = fly(zz + [straight(4), EXIT], start, frames=400)
    check(f"a zigzag launched on heading {start} returns to that heading",
          z[-1].heading == start, str(z[-1].heading))
z = fly(zz + [straight(4), EXIT], 16, frames=400)
swings = [1 if (b.heading - f.heading) % 64 < 32 else -1
          for f, b in zip(z, z[1:]) if b.heading != f.heading]
check("...and it really weaves: the turn direction alternates",
      len([i for i in range(1, len(swings)) if swings[i] != swings[i - 1]]) == 4,
      f"{len([i for i in range(1, len(swings)) if swings[i] != swings[i-1]])} reversals")
check("a zigzag with more repeats costs proportionally more",
      len(sem.macro_zigzag(repeats=4)) == 9)
refuses("a zigzag with no crossings is refused",
        lambda: sem.macro_zigzag(repeats=0), "at least one")

lp = sem.macro_loop("RIGHT")
check("a loop is ONE record: a heading that wraps is already a loop",
      len(lp) == 1 and len(sem.compile_segments(lp + [straight(4), EXIT], 0)) == 3)
t = fly(lp + [straight(4), EXIT], 0, frames=64 * 2 + 30)
check("...and flying it visits every heading in the circle",
      len({f.heading for f in t}) == 64, f"{len({f.heading for f in t})}")
check("every named macro expands into core segments only",
      all(s.kind in sem.KINDS for name in sem.MACROS for s in sem.MACROS[name]()))


# =======================================================================
# 8. mirroring
# =======================================================================
check("mirroring swaps the hand of every turn and leaves the rest alone",
      [s.to_dict() for s in sem.mirror_segments(prog)]
      == [s.to_dict() for s in [straight(20), turn("LEFT", 16), straight(15),
                                turn("RIGHT", 8), EXIT]])
check("mirroring is an involution",
      sem.mirror_segments(sem.mirror_segments(prog)) == list(prog))
check("a hold needs NO mirror transform: its drift is a speed along the "
      "heading, which reflects with the heading for free",
      sem.mirror_segments([S(kind="HOLD", frames=5, drift=3)])[0]
      == S(kind="HOLD", frames=5, drift=3))
check("the mirrored launch heading reflects about the vertical axis",
      [sem.mirror_heading(h) for h in (0, 16, 32, 48, 8)] == [32, 16, 0, 48, 24])
check("...and mirroring the heading is an involution too",
      all(sem.mirror_heading(sem.mirror_heading(h)) == h for h in range(64)))

# THE PROOF, over every launch heading there is.
bad_head = bad_vel = 0
sums = set()
for h in range(64):
    mh = sem.mirror_heading(h)
    a = fly(prog, h, frames=140)
    b = fly(sem.mirror_segments(prog), mh, frames=140)
    for f, g in zip(a, b):
        if g.heading != sem.mirror_heading(f.heading):
            bad_head += 1
        if (g.vx, g.vy) != (-f.vx, f.vy):
            bad_vel += 1
        sums.add((f.x - 250) + (g.x - 250))
check("mirrored, the heading is exactly reflected on EVERY frame of all 64 "
      "launch headings", bad_head == 0)
check("...and so is the velocity", bad_vel == 0)
check("...and the position is the true reflection rounded to the pixel grid, "
      "never further", sums <= {0, -1}, f"offsets seen: {sorted(sums)}")


# =======================================================================
# 9. cost accounting
# =======================================================================
segs = [straight(10), turn("RIGHT", 16), straight(10), turn("LEFT", 8),
        S(kind="HOLD", frames=20, drift=2), turn("RIGHT", 64), EXIT]
records, byts = sem.cost(segs, 0)
check("cost is reported in records and bytes",
      (records, byts) == (7, 28), f"{records} records, {byts} bytes")
check("a macro's expansion is counted, not hidden",
      sem.cost(sem.macro_s_curve("LEFT") + [straight(4), EXIT], 0)[0] == 4)


# =======================================================================
# 10. the project: raw, semantic, and the two together
# =======================================================================
proj = migration_v6.load_any(CANON).project
raw_bytes = CANON.read_bytes()
c = EditorController(proj)

# THE CANONICAL PROJECT IS AUTHORED CONTENT AND WILL KEEP CHANGING. It once
# held only raw programs; it now holds semantic ones too, because the feature
# shipped and the author used it. What matters here is the RULE -- a raw
# program writes no segments key, a semantic one does -- not the census.
_semantic_ids_before = {p.id for p in proj.movement_programs if p.is_semantic}
_raw = [p for p in proj.movement_programs if not p.is_semantic]
check("the canonical project still contains raw programs to exercise",
      _raw, f"{len(_raw)} raw of {len(proj.movement_programs)}")
check("...and a raw program writes no segments key at all",
      all("segments" not in p.to_dict() for p in _raw))
check("...while every semantic one does",
      all("segments" in p.to_dict()
          for p in proj.movement_programs if p.is_semantic))
# to_level_json(): raw_bytes is the LEVEL file, which carries triggers and
# terrain. The shared vocabulary this section is exercising lives in the
# encounter library and is attached in memory, so it is deliberately not part
# of what the level file has to reproduce.
check("opening and saving the canonical project changes nothing",
      c.to_level_json().encode() == raw_bytes)

# ---- lifting ---------------------------------------------------------
lifted = {}
for i, p in enumerate(list(proj.movement_programs)):
    segs2, why, same_bytes = c.preview_make_semantic(i)
    lifted[p.id] = (segs2, why, same_bytes)

# THREE OF THE FOUR LIFT. The fourth is the interesting one and it is a
# CORRECT refusal rather than a shortfall: `linger` holds with an absolute
# drift of (0, 1) while travelling on heading 10, which is a genuine
# 31-degree kink either side of the hold (see the continuity section above).
# A semantic HOLD drifts ALONG its heading and therefore cannot express that,
# so lifting it would change the path -- and the rule has always been that a
# program which cannot be said exactly stays raw.
for wid in ("sweep", "s", "loop"):
    check(f"the authored program {wid!r} can be said in semantic segments",
          lifted[wid][0] is not None, lifted[wid][1] or "")
check("'linger' is REFUSED, because its hold kinks the path and a continuous "
      "vocabulary must not pretend otherwise",
      lifted["linger"][0] is None
      and "not along the heading" in (lifted["linger"][1] or ""),
      (lifted["linger"][1] or "")[:90])
check("...and it stays perfectly usable as a raw program",
      not proj.movement_programs[2].is_semantic
      and len(proj.movement_programs[2].stages) == 4)
check("...and lifting is judged on the PATH, so it reports honestly that the "
      "compiled bytes change",
      all(not lifted[w][2] for w in ("sweep", "s", "loop")))
check("the lifted 'sweep' is exactly the sentence the brief asks for",
      [s.describe() for s in lifted["sweep"][0]]
      == ["STRAIGHT Continue 34f", "QUARTER RIGHT", "EXIT"],
      str([s.describe() for s in lifted["sweep"][0]]))

before = [s.to_dict() for s in proj.movement_programs[0].stages]
c.make_semantic(0)
check("converting a program makes it semantic", proj.movement_programs[0].is_semantic)
check("...and its records still fly the identical path",
      sem.trajectories_match(
          [project_v6.MovementStage.from_dict(d, "p") for d in before],
          proj.movement_programs[0].stages, 0))
# THE PROGRAMS THAT WERE RAW BEFORE THE CONVERSION ARE STILL RAW. Phrased
# against the set captured earlier rather than "all of them", because the
# authored project legitimately contains semantic programs of its own now.
check("...while every other program is left exactly as it was",
      all(q.is_semantic == (q.id in _semantic_ids_before)
          for q in proj.movement_programs[1:]))
check("a semantic and a raw program coexist in one project",
      validate(proj).ok, str([i.message for i in validate(proj).errors][:2]))
refuses("converting an already-semantic program is refused",
        lambda: c.make_semantic(0), "already", ControllerError)
refuses("editing a RAW program's segments is refused, with the remedy named",
        lambda: c.add_segment(1, "STRAIGHT"), "raw program", ControllerError)

# ---- back to raw -----------------------------------------------------
kept = [s.to_dict() for s in proj.movement_programs[0].stages]
c.make_raw(0)
check("dropping back to raw keeps the compiled records as they stand",
      [s.to_dict() for s in proj.movement_programs[0].stages] == kept)
check("...and discards the segments rather than hiding them",
      not proj.movement_programs[0].is_semantic
      and "segments" not in proj.movement_programs[0].to_dict())


# =======================================================================
# 11. persistence
# =======================================================================
c.make_semantic(0)
c.make_semantic(1)
saved = c.to_json()
check("a semantic program writes its segments",
      '"segments"' in saved)
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "s.v6.json"
    p.write_text(saved)
    again = migration_v6.load_any(p).project
    check("segments survive save and reopen",
          [s.to_dict() for s in again.movement_programs[0].segments]
          == [s.to_dict() for s in proj.movement_programs[0].segments])
    check("...and so does which programs are raw",
          [q.is_semantic for q in again.movement_programs]
          == [q.is_semantic for q in proj.movement_programs])
    check("...and reopening then saving is byte-identical (no hidden state)",
          EditorController(again).to_json() == saved)
    check("the reopened project's stages still equal a fresh compilation of "
          "its segments",
          all(sem.compile_segments(
                  q.segments,
                  sem.resolve_launch_heading(again, q.id, q.segments)[0])
              == q.stages
              for q in again.movement_programs if q.is_semantic))

check("the file is still formatVersion 6 -- segments are an additive key that "
      "an older reader simply ignores, and `stages` still carries the truth",
      json.loads(saved)["formatVersion"] == project_v6.FORMAT_VERSION)


# =======================================================================
# 12. overflow is caught by the EXISTING rule set, before export
# =======================================================================
big = EditorController(migration_v6.load_any(CANON).project)
j = big.add_movement_program("fat")
big.start_semantic(j)
for _ in range(70):
    big.add_segment(j, "TURN", at=1)
res = validate(big.project)
check("a semantic program that overflows the runtime pool is an ERROR",
      not res.ok and any(i.code.startswith("movement.") for i in res.errors),
      str([i.code for i in res.errors][:3]))
check("...named as the pool ceiling, by the one rule set that already counted "
      "records", any("movement" in i.code and
                     ("record" in i.message or "pool" in i.message)
                     for i in res.errors))
check("the pool limits are unchanged at 64 records / 256 bytes",
      (C.MAX_MOVEMENT_RECORDS, C.LEVELPKG_MOVE_MAX) == (64, 256))


# =======================================================================
# 13. the launch heading a program compiles against
# =======================================================================
p2 = migration_v6.load_any(CANON).project
c2 = EditorController(p2)
i_sweep = [q.id for q in p2.movement_programs].index("sweep")
h, note = c2.program_launch_heading(i_sweep)
check("a program used by one wave compiles for that wave's launch heading",
      h == 0 and note is None, f"{h}, {note}")
# point a second wave with a DIFFERENT heading at the same program
p2.wave_definitions[1].movement_program = "sweep"
c2.make_semantic(i_sweep)
h, note = c2.program_launch_heading(i_sweep)
check("a heading-dependent program used from two headings says so plainly",
      note is not None and "STRAIGHT" in note, (note or "")[:70])
p2.movement_programs[i_sweep].segments = [turn("RIGHT", 16), EXIT]
c2._recompile(p2.movement_programs[i_sweep])
h, note = c2.program_launch_heading(i_sweep)
check("...and one made only of relative segments does not, because it "
      "genuinely compiles the same for both", note is None, str(note))


# =======================================================================
# 13b. the reuse story: one program, many entry states
# =======================================================================
# The compiler is a pure function of (segments, launch heading) and knows
# nothing about stages, which is what lets a movement program become a
# project-level library asset later without this code changing.
# A still hold, so the program is heading-free: a DRIFTING hold would be
# refused on some headings after a turn (the integer velocity cannot carry
# every direction slowly), which is a different property being tested above.
shared = [turn("RIGHT", 16), S(kind="HOLD", frames=10),
          turn("LEFT", 8), EXIT]
check("a program of relative segments only is heading-FREE",
      not sem.heading_dependent(shared))
_first = [s.to_dict() for s in sem.compile_segments(shared, 0)]
check("...so the SAME BYTES serve every one of the 64 launch headings",
      all([s.to_dict() for s in sem.compile_segments(shared, h)] == _first
          for h in range(64)))
check("...and flown from different headings it is the same manoeuvre rotated",
      all(all((f.heading - g.heading) % 64 == h
              for f, g in zip(fly(shared, h, frames=140),
                              fly(shared, 0, frames=140)))
          for h in (7, 19, 44)))
check("resolve_for_headings takes bare headings, not a stage",
      sem.resolve_for_headings([12])[0] == 12
      and sem.resolve_for_headings([])[0] == 0)
check("...and reports a conflict only when the program is heading-DEPENDENT",
      sem.resolve_for_headings([0, 12], shared)[1] is None
      and sem.resolve_for_headings([0, 12], [straight(5), EXIT])[1] is not None)
check("a heading-dependent program compiles differently per heading, which is "
      "why the records are a per-use cache and the segments are the asset",
      sem.compile_segments([straight(5), EXIT], 0)[0].to_dict()
      != sem.compile_segments([straight(5), EXIT], 16)[0].to_dict())

# ---- EDITING A WAVE CAN INVALIDATE A PROGRAM --------------------------
# The records are compiled against the launch heading of the waves that use
# the program, so a change to a WAVE has to recompile the PROGRAM. Without
# this the editor shows a straight leg going one way and the engine flies it
# another -- found by the Phase 6B manual proof, not by reading.
p3 = migration_v6.load_any(CANON).project
c3 = EditorController(p3)
ip = c3.add_movement_program("resync_demo")
c3.start_semantic(ip)                       # STRAIGHT + EXIT, heading-dependent
check("a program with no wave compiles for heading 0",
      p3.movement_programs[ip].stages[0].to_dict()
      == {"kind": "STRAIGHT", "frames": 30, "vx": ms.HEAD_VX[0],
          "vy": ms.HEAD_VY[0]})
iw = c3.add_wave_definition("resync_wave")
c3.update_wave_definition(iw, heading=16, movement_program="resync_demo")
check("pointing a wave at it recompiles its records for that launch heading",
      p3.movement_programs[ip].stages[0].to_dict()
      == {"kind": "STRAIGHT", "frames": 30, "vx": ms.HEAD_VX[16],
          "vy": ms.HEAD_VY[16]},
      str(p3.movement_programs[ip].stages[0].to_dict()))
c3.update_wave_definition(iw, heading=40)
check("...and changing that wave's heading recompiles them again",
      (p3.movement_programs[ip].stages[0].vx,
       p3.movement_programs[ip].stages[0].vy)
      == (ms.HEAD_VX[40], ms.HEAD_VY[40]))
raw_before = [s.to_dict() for s in p3.movement_programs[0].stages]
c3.update_wave_definition(iw, heading=3)
check("...while RAW programs are never touched by a resync",
      [s.to_dict() for s in p3.movement_programs[0].stages] == raw_before)
p3.movement_programs[ip].segments = [turn("RIGHT", 16), EXIT]
c3._recompile(p3.movement_programs[ip])
stable = [s.to_dict() for s in p3.movement_programs[ip].stages]
c3.update_wave_definition(iw, heading=55)
check("...so its records do not change when the launch heading does",
      [s.to_dict() for s in p3.movement_programs[ip].stages] == stable)


# =======================================================================
# 14. canonical preservation, end to end
# =======================================================================
fresh = EditorController(migration_v6.load_any(CANON).project)
# to_level_json(), NOT to_json(). The in-memory document holds the shared
# movement programs and wave definitions -- load_any attaches them from
# encounter_library.v6.json -- while the LEVEL FILE holds triggers and terrain
# and no vocabulary at all. The fixed point being asserted is the level file's.
check("no-op open/save of the canonical project is byte-identical",
      fresh.to_level_json().encode() == raw_bytes)
import export_v6                                            # noqa: E402
REF = HERE.parent.parent / "src/level1"
with tempfile.TemporaryDirectory() as d:
    out = Path(d)
    export_v6.export_level(fresh.project, out, level_name="level1",
                           validate_first=True, carry_enemies_from=REF)
    import filecmp
    names = sorted(f.name for f in out.glob("*.asm"))
    same = [n for n in names if filecmp.cmp(out / n, REF / n, shallow=False)]
    check("no-op export reproduces every generated file byte-for-byte",
          same == names, f"{len(same)}/{len(names)}")
    check("...including the movement programs",
          "wave_programs.asm" in same)


print()
if FAIL:
    print(f"{len(FAIL)} FAILURE(S):")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {len(PASS)} semantic-movement checks passed.")
