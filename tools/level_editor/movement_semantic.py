"""movement_semantic.py — authoring movement as continuous segments.

    spawn state -> segment -> inherited state -> segment -> ... -> exit

THE PROBLEM THIS SOLVES. The engine's stage records are excellent runtime
instructions and poor authoring ones. An arc names an ABSOLUTE entry heading
(0..63) and a straight leg names a signed quarter-pixel VELOCITY PAIR, so
writing "fly on, then turn right 90 degrees" by hand means looking up a heading
table, working out what the previous stage left behind, and restating it. That
arithmetic is the same every time, which is exactly what a compiler is for.

    STRAIGHT -> TURN RIGHT 90 -> STRAIGHT -> TURN LEFT 45 -> EXIT

CONTINUITY IS THE DEFAULT AND IT IS NOT A NEW MECHANISM. src/movement.asm
already carries heading, velocity and position from one record to the next; the
only reason an author ever restated them is that byte 3 of an arc could be an
absolute heading. Every turn this module emits uses WM_HEAD_CONT instead, so a
turn means "turn from wherever I am now" -- which makes a program a function of
its own segments and the launch state, reusable from any entry heading.

WHAT IS AUTHORED AND WHAT IS COMPILED are deliberately different things:

    Segment     what the designer wrote          persisted as `segments`
    Stage       what the 6502 executes           persisted as `stages`

`stages` stays the exporter's and the simulator's only input, so nothing
downstream of this file changed. A program with no `segments` is a RAW program
and is left exactly as it was found -- which is what keeps the canonical
project's bytes identical.

THE VOCABULARY IS FOUR KINDS AND IS MEANT TO STAY THAT WAY. Straight, Turn,
Hold, Exit. A quarter turn, a half turn and a full loop are ANGLES of the one
turn -- as is any other angle -- and radius is its other axis, so they are
presets rather than types. A sweep, an S-curve, a zigzag, a hook or a dive is
an ORDER of those pieces, so they are macros that expand on insertion (see
MACROS) rather than primitives. Anything that can be composed should be.

WHERE THIS CODE EXPECTS TO LIVE EVENTUALLY. A movement program is a REUSABLE
ASSET -- the same "sweep right" should serve Level 1, Level 2 and Level 3 --
so nothing in this module knows what a stage is. Compilation is a pure
function of (segments, launch heading); resolve_for_headings() takes a bare
list of headings; and the compiled records a project stores are a CACHE of one
resolution, not a property of the program. When the encounter library arrives,
the semantic program moves and this file does not change. See the Phase 6B
report for the remaining step.

NO ENGINE CHANGE WAS NEEDED. The whole vocabulary below compiles into the five
primitives that already exist; see the audit in the Phase 6B report.
"""
import math
from dataclasses import dataclass, replace

import contract_v2 as C
import movement_sim as ms
import project_v6

# A heading step is a sixty-fourth of the circle. Angles are PRESENTED in
# degrees and STORED in steps, because 5.625 is not an integer and a stored
# float would be a rounding argument waiting to happen.
STEPS_PER_TURN = C.WM_HEAD_LEN                  # 64
DEGREES_PER_STEP = 360.0 / STEPS_PER_TURN       # 5.625

# THE NAMED PIECES A DESIGNER BOLTS TOGETHER. They are angles of the ONE turn
# primitive, not separate kinds: a quarter turn and a full loop differ by a
# number, so making them different segment types would mean mirroring,
# compiling, costing and lifting each learning three things where one will do.
# Radius is the other axis and is free on all of them (see RATE_PRESETS).
QUARTER_TURN = STEPS_PER_TURN // 4              # 16 steps,  90 degrees
HALF_TURN = STEPS_PER_TURN // 2                 # 32 steps, 180 degrees
FULL_LOOP = STEPS_PER_TURN                      # 64 steps, 360 degrees

NAMED_TURNS = (("Quarter turn", QUARTER_TURN),
               ("Half turn", HALF_TURN),
               ("Full loop", FULL_LOOP))

# Every angle the editor offers in one click. The named three first, because
# they are the vocabulary; the rest are there because a turn is a number and
# refusing to let an author type 45 would be arbitrary.
TURN_PRESETS = ((45, 8), (90, QUARTER_TURN), (135, 24), (180, HALF_TURN),
                (270, 48), (360, FULL_LOOP))

# framesPerStep is the turn RADIUS, per stage (src/movement_format.asm: the
# heading sweeps a full circle in 64 steps whatever happens, so a step held for
# f frames walks a circle of radius WM_ARC_SPEED*f*64/(8*PI) -- 61 pixels at
# f=4, 31 at f=2). Named rather than left as a bare number.
RATE_PRESETS = (("tight", 2), ("normal", 4), ("wide", 6))
DEFAULT_RATE = C.WM_STAGE_SIZE                  # 4, the engine's WM_ARC_STEP

WM_ARC_SPEED_LOCAL = ms.WM_ARC_SPEED     # 6: the arcs' constant speed
MAX_DRIFT = WM_ARC_SPEED_LOCAL           # a hold never outruns a turn

KINDS = ("STRAIGHT", "TURN", "HOLD", "EXIT")
DIRECTIONS = ("LEFT", "RIGHT")

# ---------------------------------------------------------------------------
# Compass names for headings
# ---------------------------------------------------------------------------
# THE AUTHOR'S WORD FOR A HEADING. The engine counts 0..63 clockwise from east
# with +y DOWN (src/movement_format.asm names the four anchors), which is a
# perfectly good runtime representation and a poor thing to ask a designer to
# hold in their head. These are the eight points that land exactly on a
# heading -- a sixty-fourth circle divides by eight without remainder -- so
# every name here is an EXACT heading and not a rounding.
#
# SCREEN WORDS, NOT NAUTICAL ONES: "Down" rather than "South", because the
# author is looking at a screen where y grows downward and the thing they are
# describing is which way the sprite goes.
COMPASS = (("Right", 0), ("Down-Right", 8), ("Down", 16), ("Down-Left", 24),
           ("Left", 32), ("Up-Left", 40), ("Up", 48), ("Up-Right", 56))
COMPASS_HEADING = dict(COMPASS)
HEADING_COMPASS = {h: name for name, h in COMPASS}

# The same eight, as the glyph an author reads at a glance in a segment list.
COMPASS_ARROW = {0: "\u2192", 8: "\u2198", 16: "\u2193", 24: "\u2199",
                 32: "\u2190", 40: "\u2196", 48: "\u2191", 56: "\u2197"}


def heading_glyph(heading):
    """A heading as an arrow. Off-point headings show the nearest arrow and
    their exact value, so nothing is silently rounded away."""
    heading = int(heading) % C.WM_HEAD_LEN
    arrow = COMPASS_ARROW.get(heading)
    if arrow:
        return arrow
    return f"{COMPASS_ARROW[((heading + 4) // 8 * 8) % C.WM_HEAD_LEN]}({heading})"


def heading_name(heading):
    """A heading as a designer would say it: "Down (16)", "19" if it is between."""
    heading = int(heading) % C.WM_HEAD_LEN
    name = HEADING_COMPASS.get(heading)
    return f"{name} ({heading})" if name else str(heading)


def heading_label(heading):
    """Just the compass word, or the bare number for an off-point heading."""
    heading = int(heading) % C.WM_HEAD_LEN
    return HEADING_COMPASS.get(heading, str(heading))

# One authored byte each, so every count the compiler emits must fit one.
MAX_BYTE = 255


class CompileError(Exception):
    """This semantic program cannot be compiled, and why.

    Raised rather than patched around. A compiler that quietly inserted a
    record to make a program legal would be authoring on the designer's behalf,
    and the inserted record would appear in the cost accounting as if they had
    asked for it.
    """


def degrees(steps):
    """Steps as the angle a designer thinks in. Display only."""
    d = steps * DEGREES_PER_STEP
    return f"{d:g}"


def steps_for_degrees(deg):
    """The nearest whole number of heading steps, and whether it was exact."""
    exact = abs(deg / DEGREES_PER_STEP - round(deg / DEGREES_PER_STEP)) < 1e-9
    return int(round(deg / DEGREES_PER_STEP)), exact


# ===========================================================================
# The authored vocabulary
# ===========================================================================

@dataclass(frozen=True)
class Segment:
    """One authored move. Immutable: edits replace rather than mutate, so an
    undo snapshot can never be aliased to a live object.

    FIELDS ARE PER KIND, exactly as MovementStage does it, because a turn has
    no use for a frame count and a hold has no use for an angle:

        STRAIGHT   frames                    fly on along the current heading
        TURN       direction, steps, rate     turn RELATIVE to the current one
        HOLD       frames, drift               stay put, or creep ALONG the
                                               heading at `drift` quarter
                                               pixels a frame
        EXIT       --                         carry on out of the world

    DRIFT IS A SPEED, NOT A VECTOR, and that is a correctness property rather
    than a simplification. A free (vx, vy) drift is an ABSOLUTE direction
    sitting inside an otherwise relative vocabulary, so it can point away from
    the way the object is travelling -- which is exactly how the authored
    `linger` program acquired a 31-degree kink either side of its hold. A
    speed along the current heading cannot.
    """
    kind: str
    frames: int = 0
    direction: str = "RIGHT"
    steps: int = 0
    rate: int = DEFAULT_RATE
    drift: int = 0
    # STRAIGHT ONLY. None means CONTINUE -- fly on along whatever the segment
    # before produced, or the wave's launch direction when this is the first
    # segment. An integer is the author deliberately ESTABLISHING a direction,
    # which is an intentional change of trajectory rather than a continuity
    # fault; see intentional_breaks().
    heading: object = None

    # ---- persistence ---------------------------------------------------
    def to_dict(self):
        if self.kind == "STRAIGHT":
            d = {"kind": "STRAIGHT", "frames": self.frames}
            # OMITTED FOR CONTINUE, which is the default and by far the common
            # case -- so a program authored before this existed reads back
            # identically, and a relative program stays visibly relative.
            if self.heading is not None:
                d["heading"] = int(self.heading)
            return d
        if self.kind == "TURN":
            return {"kind": "TURN", "direction": self.direction,
                    "steps": self.steps, "rate": self.rate}
        if self.kind == "HOLD":
            d = {"kind": "HOLD", "frames": self.frames}
            # OMITTED WHEN ZERO, which is the overwhelmingly common case: a
            # drift of nothing is what "hold" means, and writing it out would
            # put a noise key in every hold in every project.
            if self.drift:
                d["drift"] = self.drift
            return d
        return {"kind": "EXIT"}

    @staticmethod
    def from_dict(raw, path):
        if not isinstance(raw, dict):
            raise project_v6.ProjectV6Error(f"{path} must be an object")
        kind = str(raw.get("kind", ""))
        if kind not in KINDS:
            raise project_v6.ProjectV6Error(
                f"{path}.kind must be one of {', '.join(KINDS)}, not {kind!r}")
        direction = str(raw.get("direction", "RIGHT"))
        if kind == "TURN" and direction not in DIRECTIONS:
            raise project_v6.ProjectV6Error(
                f"{path}.direction must be LEFT or RIGHT, not {direction!r}")
        return Segment(
            kind=kind,
            frames=_int(raw.get("frames")),
            direction=direction,
            steps=_int(raw.get("steps")),
            rate=_int(raw.get("rate"), DEFAULT_RATE),
            drift=_int(raw.get("drift")),
            # ABSENT MEANS CONTINUE. Backwards compatible by construction:
            # every STRAIGHT written before this key existed loads as Continue,
            # which is exactly what it meant.
            heading=(None if raw.get("heading") is None
                     else _int(raw.get("heading"))),
        )

    # ---- presentation --------------------------------------------------
    def describe(self):
        """The one-line form the editor shows. No engine units."""
        if self.kind == "STRAIGHT":
            way = ("Continue" if self.heading is None
                   else heading_glyph(self.heading))
            return f"STRAIGHT {way} {self.frames}f"
        if self.kind == "TURN":
            # NAMED WHERE IT HAS A NAME. "QUARTER RIGHT" is what the author
            # asked for; "TURN RIGHT 67.5" is what the arithmetic says, and is
            # shown only for an angle that has no name.
            named = {QUARTER_TURN: "QUARTER", HALF_TURN: "HALF",
                     FULL_LOOP: "LOOP"}.get(self.steps)
            head = (f"{named} {self.direction}" if named
                    else f"TURN {self.direction} {degrees(self.steps)}°")
            return head + ("" if self.rate == DEFAULT_RATE
                           else f" ({_rate_name(self.rate)})")
        if self.kind == "HOLD":
            drift = "" if not self.drift else f" drift {self.drift}"
            return f"HOLD {self.frames}f{drift}"
        return "EXIT"


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rate_name(rate):
    for name, r in RATE_PRESETS:
        if r == rate:
            return name
    return f"{rate}f/step"


# ===========================================================================
# Compilation: segments -> engine stage records
# ===========================================================================

def compile_segments(segments, launch_heading, *, allow_still_exit=False):
    """The one deterministic semantic -> runtime compiler.

    Returns a list of project_v6.MovementStage. Raises CompileError with a
    designer-readable reason rather than emitting something that would not fly.

    THE STATE IT CARRIES is exactly the state src/movement.asm carries:

        heading   wmPhase. STRAIGHT and HOLD do not touch it; a turn moves it
                  by its own step count; EXIT reads whatever is there.
        moving    whether the velocity the next record would INHERIT is
                  non-zero. Only WM_EXIT inherits a velocity, so this exists
                  solely to catch "hold still, then exit", which would sit off
                  the edge of the world for ever -- and which src/waves.asm
                  rejects at assembly time as "never reaches any despawn edge".
    """
    if not segments:
        raise CompileError("a movement program needs at least an EXIT")
    if not 0 <= launch_heading < C.WM_HEAD_LEN:
        raise CompileError(
            f"launch heading {launch_heading} is not a heading "
            f"0..{C.WM_HEAD_LEN - 1}")

    stages = []
    heading = launch_heading        # the way the object is actually travelling
    phase = launch_heading          # what the engine's wmPhase holds
    moving = False
    # THE DIRECTION THE OBJECT IS ACTUALLY TRAVELLING, which is not always the
    # heading the engine has stored. WM_STRAIGHT and WM_HOLD write a velocity
    # and never touch wmPhase, so a HOLD with a drift that does not point
    # along the held heading leaves the two disagreeing -- and an arc entering
    # on WM_HEAD_CONT would then snap to the stale heading. Tracking travel
    # separately is what lets the turn below notice and say where to begin.
    travel = None                   # (vx, vy), or None for "standing still"

    for i, seg in enumerate(segments):
        where = f"segment {i + 1} ({seg.kind})"
        last = i == len(segments) - 1
        if seg.kind != "EXIT" and last:
            raise CompileError(
                "a movement program must end with EXIT, or the engine would "
                "run off the end of the stage table")
        if seg.kind == "EXIT" and not last:
            raise CompileError(
                f"{where}: EXIT is terminal and cannot be followed by "
                f"anything")

        if seg.kind == "STRAIGHT":
            _need(seg.frames, 1, MAX_BYTE, where, "frames")
            # AN EXPLICIT DIRECTION ESTABLISHES A NEW HEADING. The author has
            # asked for a change of trajectory, so the break at this boundary
            # is INTENTIONAL -- intentional_breaks() lists it and the
            # continuity check skips it. CONTINUE (heading None) leaves the
            # heading alone and stays tangent-continuous, which is the default
            # and what keeps a program relative and reusable.
            if seg.heading is not None:
                h = int(seg.heading)
                if not 0 <= h < C.WM_HEAD_LEN:
                    raise CompileError(
                        f"{where}: direction {h} is not a heading "
                        f"0..{C.WM_HEAD_LEN - 1}")
                heading = h
            # THE VELOCITY IS THE CURRENT HEADING'S, taken from the same table
            # an arc would use, so a straight leg between two turns runs at
            # exactly the speed the turns do and the join is invisible.
            stages.append(project_v6.MovementStage(
                kind="STRAIGHT", frames=seg.frames,
                vx=ms.HEAD_VX[heading], vy=ms.HEAD_VY[heading]))
            moving = True
            travel = (ms.HEAD_VX[heading], ms.HEAD_VY[heading])

        elif seg.kind == "TURN":
            _need(seg.steps, 1, MAX_BYTE, where, "steps")
            _need(seg.rate, 1, MAX_BYTE, where, "rate")
            if seg.direction not in DIRECTIONS:
                raise CompileError(f"{where}: direction must be LEFT or RIGHT")
            # WM_HEAD_CONT WHENEVER IT IS TRUE, and an explicit heading when
            # it is not.
            #
            # An arc entering on CONT begins on wmPhase, so it is continuous
            # only while wmPhase still describes the way the object is
            # travelling. The engine lets those diverge: WM_STRAIGHT and
            # WM_HOLD write a velocity and NEVER touch wmPhase. That is the
            #45-degree kink the raw `dive` program showed -- and a STRAIGHT
            # with an explicit direction reintroduces it deliberately, because
            # it establishes a travel direction the engine's stored heading
            # knows nothing about.
            #
            # So the compiler tracks BOTH: `heading` is the way the object is
            # actually travelling, `phase` is what wmPhase holds at runtime.
            # They agree for a purely relative program, and CONT is emitted --
            # which is what keeps such a program reusable from any launch. When
            # an explicit direction has moved them apart, the arc names the
            # heading it is really on, which costs nothing and removes the
            # snap.
            entry = "CONT" if phase == heading else heading
            stages.append(project_v6.MovementStage(
                kind="ARC" if seg.direction == "RIGHT" else "ARC_MIRROR",
                steps=seg.steps, frames_per_step=seg.rate,
                entry_heading=entry))
            sign = 1 if seg.direction == "RIGHT" else -1
            heading = (heading + sign * seg.steps) % C.WM_HEAD_LEN
            moving = True
            # THE LAST VELOCITY THE ARC ACTUALLY APPLIED is one step short of
            # where it leaves wmPhase. wmArcStep performs its final rotation on
            # the very frame it hands over, so the velocity that rotation loads
            # is immediately overwritten by the next stage -- unless that stage
            # is WM_EXIT, which keeps it. So the incoming tangent a following
            # STRAIGHT or HOLD has to match is HEAD[heading - sign], not
            # HEAD[heading].
            last = (heading - sign) % C.WM_HEAD_LEN
            travel = (ms.HEAD_VX[last], ms.HEAD_VY[last])
            # An arc DOES move wmPhase, and leaves it exactly where the
            # compiler's own heading now is.
            phase = heading

        elif seg.kind == "HOLD":
            _need(seg.frames, 1, MAX_BYTE, where, "frames")
            _need(seg.drift, 0, MAX_DRIFT, where, "drift")
            # ALONG THE HEADING, always. The hold cannot point somewhere else,
            # so it cannot put a kink either side of itself -- PROVIDED the
            # slow vector still points that way once it is rounded to whole
            # quarter pixels, which at low speeds it may not (see
            # drift_is_faithful). Refused rather than rounded, because a drift
            # that quietly pointed 31 degrees off would be the very bug this
            # vocabulary exists to make impossible.
            vx, vy = velocity_at(heading, seg.drift) if seg.drift else (0, 0)
            # Checked against the tangent the object ACTUALLY arrives on, which
            # after a turn is one heading step short of wmPhase (see the TURN
            # branch). Checking against wmPhase instead would let a drift
            # rounding one way and an arc hand-off rounding the other stack up
            # into a visible kink.
            # TWO-SIDED, because a hold has two boundaries. The drift must
            # match the tangent it ARRIVES on and the one the next segment
            # RESUMES on (HEAD[heading], which is what a STRAIGHT after it
            # emits). Checking only the near side lets the drift's rounding
            # and the resume's rounding compound into a visible kink on the
            # far side, which is what a random sweep of 4000 programs found.
            resume = (ms.HEAD_VX[heading], ms.HEAD_VY[heading])
            incoming = travel or resume

            def _ok(v):
                return _within_quantum(incoming, v) and _within_quantum(resume, v)

            if seg.drift and not _ok((vx, vy)):
                better = [d for d in range(seg.drift + 1, MAX_DRIFT + 1)
                          if _ok(velocity_at(heading, d))]
                raise CompileError(
                    f"{where}: a drift of {seg.drift} on heading {heading} "
                    f"rounds to ({vx}, {vy}), which does not point along the "
                    f"heading -- the engine's velocities are whole quarter "
                    f"pixels, so a slow drift cannot carry every direction. "
                    + (f"Use a drift of {better[0]} or more, or none."
                       if better else "Use no drift here."))
            stages.append(project_v6.MovementStage(
                kind="HOLD", frames=seg.frames, vx=vx, vy=vy))
            moving = bool(vx or vy)
            # A hold with no drift is standing still: no direction of travel,
            # so the heading the object still holds is the only thing a
            # following turn can sensibly continue from.
            travel = (vx, vy) if moving else None

        else:                                   # EXIT
            if not moving and not allow_still_exit:
                raise CompileError(
                    "the EXIT would inherit no velocity, so the object would "
                    "never leave and would hold a pool slot for the rest of "
                    "the level. Put a STRAIGHT or a TURN before it, or give "
                    "the HOLD a drift.")
            stages.append(project_v6.MovementStage(kind="EXIT"))

    return stages


def _need(value, lo, hi, where, name):
    if not lo <= value <= hi:
        raise CompileError(f"{where}: {name} must be {lo}..{hi}, not {value}")


@dataclass(frozen=True)
class Draft:
    """A movement program as it stands MID-EDIT, which is not the same thing
    as a movement program that is ready to ship.

    An incomplete path is a perfectly good draft and a perfectly bad level:
    the author is still building it, and the preview should show what they
    have so far rather than go blank until a terminal EXIT appears. Production
    persistence stays strict -- `stages` here ends in a SYNTHETIC exit purely
    so the interpreter has a terminator to read, and `complete` says whether
    the author actually wrote one.

        stages        what to fly, always terminated
        complete      did the author supply the final EXIT?
        frames        stop the preview here (None = run to the despawn rule)
        used          how many authored segments made it in
        stopped_at    index of the first segment that would not compile
        reason        why it would not
        intentional   stage indices where a direction was deliberately set
    """
    stages: tuple
    complete: bool
    frames: object
    used: int
    stopped_at: object
    reason: object
    intentional: frozenset

    @property
    def authored_stages(self):
        """The records for what the author actually wrote.

        THE SYNTHETIC EXIT IS NOT ONE OF THEM. It exists so the interpreter
        has a terminator to read while previewing; storing it would tell the
        validator the program is finished when it is not, and Save would
        happily ship a path the author had not ended.
        """
        return list(self.stages) if self.complete else list(self.stages[:-1])


def segment_frames(seg):
    """How long one segment lasts. EXIT is unbounded and counts as nothing."""
    if seg.kind in ("STRAIGHT", "HOLD"):
        return max(0, int(seg.frames))
    if seg.kind == "TURN":
        return max(0, int(seg.steps)) * max(0, int(seg.rate))
    return 0


def compile_draft(segments, launch_heading):
    """Compile the LONGEST PREFIX the strict compiler will accept.

    DELIBERATELY BUILT ON compile_segments RATHER THAN BESIDE IT. A second
    compiler that tolerated more would be a second opinion about what the
    engine does, and the two would drift; this one only ever asks the real
    compiler whether a shorter program is acceptable. What the preview flies
    is therefore exactly what the exporter would emit for those segments.

    A synthetic EXIT terminates the prefix when the author has not written one
    -- the interpreter must have something to read at the end of the table --
    and `frames` truncates the flight at the end of the last authored segment,
    so the preview stops where the authored path stops instead of sailing on.
    """
    segments = list(segments)
    for k in range(len(segments), 0, -1):
        prefix = segments[:k]
        complete = prefix[-1].kind == "EXIT"
        probe = prefix if complete else prefix + [Segment(kind="EXIT")]
        try:
            stages = compile_segments(probe, launch_heading,
                                      allow_still_exit=not complete)
        except CompileError as exc:
            reason, stopped = str(exc), k - 1
            continue
        return Draft(stages=tuple(stages), complete=complete,
                     frames=None if complete
                     else sum(segment_frames(g) for g in prefix),
                     used=k,
                     stopped_at=None if k == len(segments) else k,
                     reason=None if k == len(segments) else
                     _why_not(segments, launch_heading, k),
                     intentional=intentional_breaks(prefix))
    return Draft(stages=(), complete=False, frames=0, used=0,
                 stopped_at=0 if segments else None,
                 reason=(_why_not(segments, launch_heading, 0) if segments
                         else "no segments yet"),
                 intentional=frozenset())


def _why_not(segments, launch_heading, k):
    """The reason segment k+1 could not be included, in the author's terms."""
    if k >= len(segments):
        return None
    probe = list(segments[:k + 1])
    if probe[-1].kind != "EXIT":
        probe = probe + [Segment(kind="EXIT")]
    try:
        compile_segments(probe, launch_heading, allow_still_exit=True)
    except CompileError as exc:
        return str(exc)
    return "this segment cannot be simulated from here"


def final_heading(segments, launch_heading):
    """Where a program leaves the object facing. Pure arithmetic, no compile."""
    h = launch_heading
    for seg in segments:
        if seg.kind == "TURN":
            step = seg.steps if seg.direction == "RIGHT" else -seg.steps
            h = (h + step) % C.WM_HEAD_LEN
        elif seg.kind == "STRAIGHT" and seg.heading is not None:
            # An explicit direction REPLACES the inherited one -- that is what
            # makes it explicit.
            h = int(seg.heading) % C.WM_HEAD_LEN
    return h


def heading_dependent(segments):
    """Whether this program compiles to different BYTES from a different
    launch heading.

    Only a CONTINUE straight does: src/movement.asm stores a straight leg's
    velocity in the record, so it has to be resolved at compile time. Turns,
    holds and exits are heading-relative, and a straight with an EXPLICIT
    direction resolves from its own byte -- so once one of those has run,
    everything after it is absolute and the program stops caring where it was
    launched. That is the difference between a RELATIVE, reusable asset and a
    deliberately SELF-DIRECTING one.
    """
    absolute = False
    for seg in segments:
        if seg.kind != "STRAIGHT":
            continue
        if seg.heading is not None:
            absolute = True
        elif not absolute:
            return True
    return False


def is_self_directing(segments):
    """Does this program establish its own direction rather than inherit one?"""
    for seg in segments:
        if seg.kind == "STRAIGHT":
            return seg.heading is not None
    return False


def intentional_breaks(segments):
    """Stage indices where the AUTHOR asked for a change of direction.

    A continuity check must skip these: an explicit STRAIGHT direction is the
    point of the feature, not a fault. The mapping is direct because this
    compiler emits exactly ONE RECORD PER SEGMENT -- asserted in the tests, so
    it cannot drift unnoticed.
    """
    return frozenset(i for i, seg in enumerate(segments)
                     if seg.kind == "STRAIGHT" and seg.heading is not None)


def cost(segments, launch_heading):
    """(records, bytes) this program will occupy in the runtime pool."""
    stages = compile_segments(segments, launch_heading)
    return len(stages), len(stages) * C.WM_STAGE_SIZE


# ===========================================================================
# Macros — expanded when inserted, never stored as a nested thing
# ===========================================================================
# WHY EXPANSION HAPPENS AT INSERT TIME. A stored macro would be a fifth kind
# that mirroring, compilation, costing and the raw view would each have to know
# about, and its expansion cost would be invisible until export. Expanding into
# core segments the moment it is added keeps the persisted vocabulary at four
# kinds, puts the cost on screen immediately (the brief's "never hide macro
# expansion cost"), and leaves the author free to tune either half afterwards
# -- which is what they want from an S-curve about half the time anyway.

def macro_s_curve(direction, steps=16, rate=DEFAULT_RATE):
    """Out and back: turn one way, then the same amount the other."""
    other = "LEFT" if direction == "RIGHT" else "RIGHT"
    return [Segment(kind="TURN", direction=direction, steps=steps, rate=rate),
            Segment(kind="TURN", direction=other, steps=steps, rate=rate)]


def macro_loop(direction, extra_steps=0, rate=2):
    """A full circle, and optionally a bit more so it leaves on a new heading.

    ONE RECORD, because a heading that wraps is already a loop -- there is no
    loop primitive in the engine and none is needed (src/movement.asm: "AND
    #WM_HEAD_MASK IS THE WHOLE OF 'LOOPS WORK'").
    """
    return [Segment(kind="TURN", direction=direction,
                    steps=FULL_LOOP + extra_steps, rate=rate)]


def macro_zigzag(direction="RIGHT", swing=8, rate=DEFAULT_RATE, repeats=2):
    """A weave about the heading it starts on.

    `swing` is the amplitude as an angle off the centre line and `rate` is the
    radius of each bend, so the two together are the width of the weave;
    `repeats` is how many times it crosses back.

    IT RETURNS TO THE HEADING IT STARTED ON, which is what makes it something
    an author can drop into the middle of a path without recalculating
    everything after it: half a swing out, then full swings alternating, then
    half a swing back.

    Costs 2*repeats + 1 records, which is the most expensive thing in the
    vocabulary -- so it is a macro, expanded where the cost is visible, rather
    than a primitive that hides an arbitrary number of records behind one row.
    """
    if repeats < 1:
        raise CompileError("a zigzag needs at least one crossing")
    other = "LEFT" if direction == "RIGHT" else "RIGHT"
    out = [Segment(kind="TURN", direction=direction, steps=swing, rate=rate)]
    here, away = other, direction
    for _ in range(2 * repeats - 1):
        out.append(Segment(kind="TURN", direction=here, steps=2 * swing,
                           rate=rate))
        here, away = away, here
    out.append(Segment(kind="TURN", direction=here, steps=swing, rate=rate))
    return out


# The one-click manoeuvres. EVERY ONE IS A COMPOSITION of the turn primitive:
# a sweep, an S-turn, a hook or a dive is an ORDER of pieces, not a new piece,
# which is the whole reason the vocabulary stays at four kinds.
MACROS = {
    "S-curve left": lambda: macro_s_curve("LEFT"),
    "S-curve right": lambda: macro_s_curve("RIGHT"),
    "Loop left": lambda: macro_loop("LEFT"),
    "Loop right": lambda: macro_loop("RIGHT"),
    "Zigzag left": lambda: macro_zigzag("LEFT"),
    "Zigzag right": lambda: macro_zigzag("RIGHT"),
}


# ===========================================================================
# Mirroring
# ===========================================================================
# A SCREEN-SPACE MIRROR IS TWO HALVES AND THEY LIVE IN DIFFERENT OBJECTS.
#
#   the MOVEMENT half   every turn changes hand: a reflection reverses the
#                       sense of rotation. That is mirror_segments(), and it is
#                       all this module owns.
#   the LAUNCH half     the entry heading reflects, h -> (32 - h) mod 64, and
#                       the spawn column reflects about the playfield. Those
#                       belong to the WAVE DEFINITION and are not rewritten
#                       here -- the editor states the requirement instead.
#
# Doing only the first and expecting a mirrored picture is the trap: a program
# mirrored but launched on the original heading is a DIFFERENT manoeuvre, not a
# reflected one. mirror_heading() exists so the caller can be explicit.

def mirror_heading(heading):
    """The heading reflected about the vertical axis.

    Headings run clockwise from east with +y down, so reflecting x maps
    angle t to pi - t, i.e. h -> 32 - h. Exact in the velocity table: it is
    checked at import that HEAD_VX[32-h] == -HEAD_VX[h] and
    HEAD_VY[32-h] == HEAD_VY[h] for every heading.
    """
    return (STEPS_PER_TURN // 2 - heading) % STEPS_PER_TURN


def mirror_segments(segments):
    """Left becomes right and right becomes left; everything else stands.

    NOT a swap of WM_ARC and WM_ARC_MIRROR in the compiled records. That would
    be wrong for any program holding an absolute entry heading, and it would
    say nothing about the launch state. This is a transform of what was
    AUTHORED, and because every compiled turn continues from the heading it
    inherits, the reflection is exact.

    An involution: mirroring twice returns the original segments.
    """
    out = []
    for seg in segments:
        if seg.kind == "TURN":
            out.append(replace(
                seg, direction="LEFT" if seg.direction == "RIGHT" else "RIGHT"))
        # A HOLD needs NO transform: its drift is a speed along whatever
        # heading the object holds, so it reflects with the heading for free.
        # That is the free gift of making drift relative.
        else:
            out.append(seg)
    return out


# ===========================================================================
# Continuity: the heading the engine STORES vs the direction it is TRAVELLING
# ===========================================================================
# THE ONE PLACE THE TWO CAN DIVERGE, and it is worth stating exactly because
# it is not obvious and it produced a visible bug:
#
#   WM_STRAIGHT and WM_HOLD write wmVX/wmVY and DO NOT TOUCH wmPhase.
#   (src/movement.asm wmEnterStage; src/movement_format.asm says so in words:
#   "WM_STRAIGHT and WM_HOLD do not touch wmPhase and never have".)
#
# So after a straight leg whose velocity is not the current heading's, the
# object is travelling one way and wmPhase still says another. WM_HEAD_CONT
# then faithfully inherits a STALE heading, and the arc snaps the velocity to
# it -- an instantaneous direction change nobody authored.
#
# THE COMPILER CANNOT HIT THIS, and that is by construction rather than by
# luck: it only ever emits a STRAIGHT whose velocity is HEAD_V*[heading] at
# the heading it is tracking, and only a TURN moves either. So stored heading
# and direction of travel are the same thing at every boundary it produces.
# The functions below exist to prove that, and to diagnose the RAW programs
# where it can and does happen.

def velocity_at(heading, speed=WM_ARC_SPEED_LOCAL):
    """The velocity for `heading` at `speed` quarter pixels a frame.

    Built with the SAME expression src/movement.asm uses for its own table --
    floor(v*cos + 0.5) -- so that speed = WM_ARC_SPEED reproduces the engine's
    entry exactly rather than approximately. A slower speed is that same
    direction, scaled and re-rounded, which is what a drifting hold needs.
    """
    a = 2 * math.pi * heading / C.WM_HEAD_LEN
    return (math.floor(speed * math.cos(a) + 0.5),
            math.floor(speed * math.sin(a) + 0.5))


def _within_quantum(a, b):
    """Are two velocities pointing the same way, to the arc's own precision?

    The tolerance is one heading step, because that is the granularity the
    engine already turns in: a difference smaller than the arc's own per-step
    rotation is not a kink anybody can see, and demanding exact equality would
    flag every arc in the game.
    """
    if a == (0, 0) or b == (0, 0):
        return False
    d = _angle_between(a, b)
    return d is not None and d <= _MIN_QUANTUM + 1e-9


def drift_is_faithful(heading, speed):
    """Does a drift at `speed` still point along `heading` once rounded?

    NOT ALWAYS, and this is a real property of the runtime representation
    rather than a rounding nicety. Velocities are whole quarter pixels, so the
    number of directions expressible at speed v is roughly the number of
    lattice points at that radius: at the arcs' own speed of 6 there are 64 of
    them, which is exactly why the heading table uses that magnitude. At speed
    1 there are four. A drift of 1 on a heading near a diagonal therefore
    rounds to an axis and points up to 31 degrees away from where the object
    is actually facing.

    The tolerance is the arc's own per-step quantum: a drift that deviates by
    less than one heading step is within the granularity the engine already
    moves in, and one that deviates by more is a visible kink.
    """
    got = velocity_at(heading, speed)
    if got == (0, 0):
        return False
    want = (ms.HEAD_VX[heading], ms.HEAD_VY[heading])
    d = _angle_between(want, got)
    return d is not None and d <= _MIN_QUANTUM + 1e-9


def faithful_drifts(heading):
    """Every drift speed that keeps its direction on this heading."""
    return [d for d in range(1, MAX_DRIFT + 1) if drift_is_faithful(heading, d)]


def nearest_heading(vx, vy):
    """The heading whose table entry points most nearly along (vx, vy).

    Exact when the velocity IS a table entry, which is the case that matters:
    it is what lets a raw arc be made continuous with the leg before it
    without changing anything else.

    Returns None for a standing-still velocity, which has no direction.
    """
    if not vx and not vy:
        return None
    best, best_dot = None, None
    length = math.hypot(vx, vy)
    for h in range(C.WM_HEAD_LEN):
        hx, hy = ms.HEAD_VX[h], ms.HEAD_VY[h]
        # cosine of the angle between, scaled -- comparing dot products over a
        # constant-speed table is comparing angles.
        dot = (vx * hx + vy * hy) / (length * math.hypot(hx, hy))
        if best_dot is None or dot > best_dot:
            best, best_dot = h, dot
    return best


def _angle_between(a, b):
    """Degrees between two velocity vectors, or None if either stands still."""
    if a == (0, 0) or b == (0, 0):
        return None
    d = math.degrees(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0]))
    return abs((d + 180) % 360 - 180)


CONTINUITY_FRAMES = 400         # long enough for every authored path to finish


def continuity_breaks(stages, launch_heading, frames=CONTINUITY_FRAMES,
                      intentional=frozenset()):
    """Every place a compiled program changes direction instantaneously.

    Returns a list of dicts: the stage index handed TO, the two kinds, the
    angle, and what the object was actually doing either side.

    THE BASELINE IS THE ARC'S OWN STEP, not zero. An arc rotates its heading
    one table step at a time and the table is integer-quantised, so a turn in
    progress changes direction by up to ~12 degrees between consecutive
    frames. A boundary change no larger than that is the turn continuing; a
    larger one is a snap. Comparing against zero would flag every arc in the
    game, which is how a continuity check becomes noise nobody reads.

    Asked of the FAITHFUL SIMULATOR rather than of the records, because the
    question is about the trajectory, not about what the bytes say.
    """
    t = ms.trace_program(stages, x=250, y=120, heading=launch_heading,
                         frames=frames)
    quantum = 0.0
    for a, b in zip(t, t[1:]):
        if b.stage_index == a.stage_index and a.stage_kind in C.ARC_KINDS:
            d = _angle_between((a.vx, a.vy), (b.vx, b.vy))
            if d is not None:
                quantum = max(quantum, d)
    # An arc that never gets to rotate (or a program with no arc at all) still
    # needs a tolerance, or integer velocities alone would read as breaks.
    quantum = max(quantum, _MIN_QUANTUM)

    out = []
    for a, b in zip(t, t[1:]):
        if b.stage_index == a.stage_index:
            continue
        d = _angle_between((a.vx, a.vy), (b.vx, b.vy))
        if d is None or d <= quantum + 1e-9:
            continue
        if b.stage_index in intentional:
            continue                    # the author asked for this one
        out.append({"stage": b.stage_index, "from_kind": a.stage_kind,
                    "to_kind": b.stage_kind, "degrees": d,
                    "was": (a.vx, a.vy), "now": (b.vx, b.vy),
                    "travel_heading": nearest_heading(a.vx, a.vy),
                    "stored_heading": b.heading})
    return out


# The widest single step the quantised heading table takes anywhere, so a
# program with no arc to measure still has an honest tolerance.
_MIN_QUANTUM = max(
    abs(((math.degrees(math.atan2(ms.HEAD_VY[(i + 1) % C.WM_HEAD_LEN],
                                  ms.HEAD_VX[(i + 1) % C.WM_HEAD_LEN])
          - math.atan2(ms.HEAD_VY[i], ms.HEAD_VX[i])) + 180) % 360) - 180)
    for i in range(C.WM_HEAD_LEN))


# THE COMPASS NAMES ARE TIED TO THE ENGINE'S OWN TABLE, not to a comment.
# "Right" must really be the heading whose velocity is +x, "Down" really +y,
# and so on -- checked here so a change to either side fails loudly instead of
# quietly mislabelling every direction in the editor.
assert ms.HEAD_VX[COMPASS_HEADING["Right"]] > 0 and ms.HEAD_VY[COMPASS_HEADING["Right"]] == 0
assert ms.HEAD_VY[COMPASS_HEADING["Down"]] > 0 and ms.HEAD_VX[COMPASS_HEADING["Down"]] == 0
assert ms.HEAD_VX[COMPASS_HEADING["Left"]] < 0 and ms.HEAD_VY[COMPASS_HEADING["Left"]] == 0
assert ms.HEAD_VY[COMPASS_HEADING["Up"]] < 0 and ms.HEAD_VX[COMPASS_HEADING["Up"]] == 0
assert ms.HEAD_VX[COMPASS_HEADING["Down-Right"]] > 0 and ms.HEAD_VY[COMPASS_HEADING["Down-Right"]] > 0
assert ms.HEAD_VX[COMPASS_HEADING["Up-Left"]] < 0 and ms.HEAD_VY[COMPASS_HEADING["Up-Left"]] < 0
assert len(COMPASS) == 8 and len(HEADING_COMPASS) == 8


# The symmetry mirror_heading() relies on, asserted rather than assumed.
assert all(ms.HEAD_VX[mirror_heading(h)] == -ms.HEAD_VX[h]
           for h in range(C.WM_HEAD_LEN))
assert all(ms.HEAD_VY[mirror_heading(h)] == ms.HEAD_VY[h]
           for h in range(C.WM_HEAD_LEN))


# ===========================================================================
# Lifting: engine records -> segments, only when it is LOSSLESS
# ===========================================================================

def _drift_speed_for(heading, vx, vy):
    """The drift speed that compiles to exactly (vx, vy) here, or None."""
    if (vx, vy) == (0, 0):
        return 0
    for d in range(1, MAX_DRIFT + 1):
        if velocity_at(heading, d) == (vx, vy):
            return d
    return None


def lift_stages(stages, launch_heading):
    """Recognise an existing raw program as semantic segments.

    Returns (segments, None) when the records can be expressed exactly, or
    (None, reason) when they cannot. NEVER returns an approximation: a lossy
    lift would silently rewrite authored content, and the whole point of
    keeping raw programs is that some of them cannot be said any other way.

    The two things that have to line up:

      * a STRAIGHT's velocity must be exactly the heading table's entry for
        the heading inherited at that point -- otherwise it is a leg at some
        other speed or direction, which no STRAIGHT segment can express;
      * an arc's entry heading must be CONT, or an absolute heading that
        HAPPENS to equal the inherited one. The second case is the interesting
        one: three of Level 1's four programs were authored before WM_HEAD_CONT
        existed and name a heading that is simply what the wave launches on.
    """
    if not stages:
        return None, "the program has no stages"
    if stages[-1].kind != "EXIT":
        return None, "the program does not end in EXIT"

    segs = []
    heading = launch_heading
    for i, st in enumerate(stages):
        where = f"stage {i}"
        if st.kind == "EXIT":
            if i != len(stages) - 1:
                return None, f"{where}: EXIT is not the last stage"
            segs.append(Segment(kind="EXIT"))

        elif st.kind == "STRAIGHT":
            if (st.vx, st.vy) != (ms.HEAD_VX[heading], ms.HEAD_VY[heading]):
                return None, (
                    f"{where}: velocity ({st.vx}, {st.vy}) is not the cruise "
                    f"velocity for the heading inherited there ({heading} -> "
                    f"{ms.HEAD_VX[heading]}, {ms.HEAD_VY[heading]}), so it "
                    f"cannot be said as “fly on”")
            segs.append(Segment(kind="STRAIGHT", frames=st.frames))

        elif st.kind == "HOLD":
            drift = _drift_speed_for(heading, st.vx, st.vy)
            if drift is None:
                return None, (
                    f"{where}: the hold drifts ({st.vx}, {st.vy}), which is "
                    f"not along the heading it is travelling on ({heading}). "
                    f"That is a deliberate kink, and a semantic HOLD -- whose "
                    f"drift follows the heading -- cannot say it.")
            segs.append(Segment(kind="HOLD", frames=st.frames, drift=drift))

        elif st.kind in C.ARC_KINDS:
            entry = st.entry_heading
            if entry != "CONT":
                if not isinstance(entry, int) or entry != heading:
                    return None, (
                        f"{where}: the arc starts on heading {entry}, but the "
                        f"object reaches it on heading {heading}. That is a "
                        f"deliberate jump, and a relative turn cannot say it.")
            direction = "RIGHT" if st.kind == "ARC" else "LEFT"
            segs.append(Segment(kind="TURN", direction=direction,
                                steps=st.steps, rate=st.frames_per_step))
            step = st.steps if direction == "RIGHT" else -st.steps
            heading = (heading + step) % C.WM_HEAD_LEN
        else:
            return None, f"{where}: unknown stage kind {st.kind!r}"

    return segs, None


# How long a lift check flies both versions before believing them equal. Every
# authored program in the project reaches EXIT and settles to a constant
# velocity well inside this, and EXIT never advances the cursor again, so a
# difference that has not appeared by now cannot appear later.
LIFT_PROOF_FRAMES = 400


def trajectories_match(a, b, launch_heading, frames=LIFT_PROOF_FRAMES):
    """Do two stage lists fly the SAME PATH? Asked of the faithful simulator.

    movement_sim is the Phase 6A interpreter, proved frame-for-frame against a
    real 6502, so this is the strongest answer available without booting one --
    and it compares every authoritative field, not just the pixel.

    The start position is arbitrary and central: movement evolution does not
    depend on where the object is, and a mid-world start keeps the nine-bit
    wrap out of a question that is not about wrapping.
    """
    start = dict(x=200, y=100, heading=launch_heading, frames=frames)
    return ms.trace_program(a, **start) == ms.trace_program(b, **start)


def lift_is_exact(stages, launch_heading):
    """Lift, recompile, and require THE SAME FLIGHT back.

    Returns (segments, reason, bytes_identical).

    THE CRITERION IS THE PATH, NOT THE BYTES, and the difference is the whole
    subtlety of lifting this project. Three of Level 1's four programs were
    authored before WM_HEAD_CONT existed, so their arcs name an ABSOLUTE entry
    heading which happens to be the one the object already carries. Compiling
    the lifted segments emits WM_HEAD_CONT instead, because that is what a
    relative turn means -- so byte 3 of those records changes from a heading to
    $ff even though wmEnterStage reaches an identical state either way (it
    stores a heading it already holds, versus skipping the store).

    Reporting bytes_identical separately lets the editor say exactly that: the
    path is provably the same, and the compiled bytes will change. An author
    can then decide, rather than discover it in a diff.
    """
    segs, why = lift_stages(stages, launch_heading)
    if segs is None:
        return None, why, False
    try:
        back = compile_segments(segs, launch_heading)
    except CompileError as exc:
        return None, f"the lifted segments do not compile: {exc}", False
    if not trajectories_match(stages, back, launch_heading):
        return None, ("the lifted segments would fly a different path, so the "
                      "program cannot be said in semantic terms"), False
    same_bytes = ([s.to_dict() for s in back]
                  == [s.to_dict() for s in stages])
    return segs, None, same_bytes


# ===========================================================================
# Resolving the launch heading a program compiles against
# ===========================================================================

# ===========================================================================
# Which launch heading a program's records are compiled against
# ===========================================================================
# DELIBERATELY NOT COUPLED TO A STAGE. resolve_for_headings() takes a list of
# headings and nothing else, so it works unchanged when movement programs
# become a project-level encounter library referenced by many stages: the
# caller gathers the headings from wherever the wave definitions live.
# resolve_launch_heading() is the thin convenience over a single project and
# is the only thing in this file that knows what a project looks like.
#
# WHY A PROGRAM HAS A HEADING AT ALL, given that turns are relative: a
# STRAIGHT's velocity is stored IN the record (src/movement.asm), so it has to
# be resolved at compile time. A program made only of turns, holds and exits is
# genuinely heading-free and compiles to identical bytes from anywhere -- which
# is exactly the property a shared library asset wants, and why
# heading_dependent() is worth surfacing in the editor.

def launch_headings_for(project, program_id):
    """Every launch heading this project actually uses the program from."""
    return sorted({w.heading for w in project.wave_definitions
                   if w.movement_program == program_id})


def resolve_for_headings(headings, segments=None):
    """(heading, note) from the set of launch headings a program is used on."""
    used = sorted(set(headings))
    if not used:
        return 0, ("no wave uses this program yet, so it is compiled for "
                   "launch heading 0")
    if len(used) == 1:
        return used[0], None
    if segments is not None and not heading_dependent(segments):
        # Every segment is relative, so all of them compile identically --
        # one program, many entry states, which is the reuse story working.
        return used[0], None
    return used[0], (
        f"this program is launched on headings {', '.join(map(str, used))}, "
        f"but it contains a STRAIGHT whose velocity is baked into the record. "
        f"It is compiled for heading {used[0]}; the other waves will fly it "
        f"with that leg pointing the wrong way. Split it into one program per "
        f"heading, or replace the STRAIGHT with a turn.")


def resolve_launch_heading(project, program_id, segments=None):
    """resolve_for_headings() over one project's wave definitions."""
    return resolve_for_headings(launch_headings_for(project, program_id),
                                segments)
