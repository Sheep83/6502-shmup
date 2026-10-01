"""movement_sim.py — the 6502 movement interpreter, restated in Python.

THE ENGINE IS AUTHORITATIVE AND THIS FILE IS THE COPY. Every routine below
names the assembly it mirrors, and where the two could differ the assembly's
behaviour is what is reproduced -- byte wrap, arithmetic shift, nine-bit carry
and all. A preview that is merely plausible is worse than no preview, because
an author would trust it.

WHAT IS MODELLED (src/movement.asm, src/waves.asm, src/enemy.asm):

    wmApplyVelocity   quarter-pixel integration on both axes
    wmTick            move first, then advance the primitive
    wmTimedStep       WM_STRAIGHT and WM_HOLD
    wmArcStep         WM_ARC and WM_ARC_MIRROR, and the heading wrap
    wmEnterStage      including the entry heading and WM_HEAD_CONT
    wmEnterNext       the stage cursor
    waveSpawnMember   the formation fan-out, in nine-bit X and eight-bit Y
    waveRunInstance   the spawn interval
    enemyTick         the four despawn rules, direction tests included

WHAT IS NOT MODELLED, deliberately:

    * TOKEN / protector choreography. What a Dropper's death sets off is a
      lifecycle state machine, not movement, and nothing here models it.
      (The Dropper's own flight IS modelled -- both the legacy trajectory and
      an authored movement program; see simulate_dropper.)
    * Pool pressure. src/waves.asm DEFERS a member when objectAlloc refuses,
      which stretches a wave by however many frames the pool was busy. The
      pool is shared with hostile projectiles, so that is a property of the
      whole running game rather than of the authored encounter. Simulated as
      an always-free pool, which is the authored intent.
    * Collision, player interaction, firing, animation and colour.

NO FLOATING POINT REACHES SIMULATED STATE. The heading table is derived once
with the same expression the assembler uses (src/movement.asm builds it from
cos/sin at assembly time) and rounded the same way; from then on every value
is an integer and every operation is the 6502's.
"""
import math
from dataclasses import dataclass, replace
from pathlib import Path as _Path
from typing import Optional

import contract_v2 as C
import project_v6


class SimulationError(Exception):
    """This encounter cannot be simulated, and why.

    Raised rather than guessed. Phase 5B lets an author hold an invalid
    project while editing, so the preview's job on invalid input is to say
    what is wrong -- never to clamp a value into range and draw the result,
    which would show a path the engine will not fly.
    """


# ===========================================================================
# Engine constants that are NOT part of the authored data contract
# ===========================================================================
# contract_v2 carries what authored data names. These are lifecycle and
# geometry facts owned by the engine, quoted here with their source so the
# next person can check them rather than trust them.

WM_ARC_SPEED = 6            # src/movement_format.asm: quarter pixels a frame
WM_HEAD_MASK = C.WM_HEAD_LEN - 1

# SHARED WITH THE VALIDATOR, not copied: contract_v2 owns the geometry that
# src/waves.asm's spawn proof uses, so the simulator and the validator cannot
# drift apart about where the screen starts or how tall a sprite is.
SPRITE_HEIGHT = C.SPRITE_HEIGHT             # src/renderer.asm
MIN_SPRITE_Y = 55           # src/renderer.asm: first admitted sprite Y
MAX_SPRITE_Y = 226          # src/renderer.asm: last admitted sprite Y
APERTURE_TOP_RASTER = C.APERTURE_TOP_RASTER  # src/main.asm TOP_SPLIT_LINE
APERTURE_BOT_RASTER = 247   # src/enemy.asm derives ENEMY_CLEAR_Y from it

ENEMY_CLEAR_X_LEFT = 4                      # src/enemy.asm
ENEMY_CLEAR_X_RIGHT = 344                   # src/enemy.asm
ENEMY_CLEAR_X_RIGHT_LO = ENEMY_CLEAR_X_RIGHT - 256      # 88
ENEMY_HIDDEN_Y = APERTURE_TOP_RASTER - SPRITE_HEIGHT    # 34
ENEMY_CLEAR_Y = APERTURE_BOT_RASTER + 1                 # 248
ENEMY_CLEAR_Y_TOP = ENEMY_HIDDEN_Y + 1                  # 35

# The horizontal display window, in the same nine-bit X the objects use.
# src/waves.asm's spawn proof uses exactly these numbers ("columns 24..343").
DISPLAY_X_FIRST = C.DISPLAY_X_FIRST
DISPLAY_X_LAST = C.DISPLAY_X_LAST

SIM_FRAME_BUDGET = 900      # src/waves.asm: frames before a path is stuck

# ---------------------------------------------------------------------------
# THE LEGACY DROPPER FLIGHT, READ FROM src/dropper.asm RATHER THAN RETYPED.
#
# The hard-coded trajectory is now one of two things a Dropper trigger can
# select, so the preview has to be able to draw it -- and drawing it means
# knowing the entry edges, the turning points, the crossing speed and the weave.
# Every one of those is a `.const` in src/dropper.asm, and every one of them has
# been tuned at least once.
#
# SO THEY ARE PARSED, NOT COPIED. contract_v2's convention for engine constants
# is a literal beside a source comment, which is fine for numbers nobody moves
# (a sprite is 21 rasters tall). These are gameplay tuning values, and a preview
# quietly drawing last month's amplitude is exactly the kind of wrong a preview
# must not be. asm_decl is the same reader the importer uses.
# ---------------------------------------------------------------------------
import asm_decl as _asm_decl                                        # noqa: E402

_REPO = _Path(__file__).resolve().parent.parent.parent
_DROP = _asm_decl.parse_files([_REPO / "src" / "dropper.asm"])

DROP_ENTRY_LEFT = _DROP.const("DROP_ENTRY_LEFT")
DROP_ENTRY_RIGHT = _DROP.const("DROP_ENTRY_RIGHT")
DROP_X_LEFT = _DROP.const("DROP_X_LEFT")
DROP_X_RIGHT = _DROP.const("DROP_X_RIGHT")
DROP_PASSES = _DROP.const("DROP_PASSES")
DROP_VX = _DROP.const("DROP_VX")
DROP_CENTRE_Y = _DROP.const("DROP_CENTRE_Y")
DROP_AMPLITUDE = _DROP.const("DROP_AMPLITUDE")
DROP_PHASES = _DROP.const("DROP_PHASES")
DROP_PHASE_HOLD = _DROP.const("DROP_PHASE_HOLD")


def _drop_weave():
    """src/dropper.asm's dropperWeave, built with the same expression.

    `<round(DROP_AMPLITUDE * sin(2 * PI * k / DROP_PHASES))`, as signed bytes.
    Python's round() is banker's rounding and KickAssembler's is not, so the
    half-up form is written out.
    """
    out = []
    for k in range(DROP_PHASES):
        v = DROP_AMPLITUDE * math.sin(2 * math.pi * k / DROP_PHASES)
        out.append(math.floor(v + 0.5) if v >= 0 else -math.floor(-v + 0.5))
    return tuple(out)


DROP_WEAVE = _drop_weave()

MODE_NAMES = {C.WM_STRAIGHT: "STRAIGHT", C.WM_ARC: "ARC",
              C.WM_ARC_MIRROR: "ARC_MIRROR", C.WM_EXIT: "EXIT",
              C.WM_HOLD: "HOLD"}


def _heading_table():
    """The velocity table src/movement.asm generates at assembly time.

    KickAssembler's round() is Java's Math.round -- half away from zero for
    positives and half toward positive infinity for negatives, i.e.
    floor(v + 0.5). Python's own round() is banker's rounding and would be a
    different table the day a value landed exactly on .5, so the expression is
    written out rather than delegated.

    Floating point appears HERE and nowhere else: the result is a table of
    integers, and every later use of it is integer arithmetic.
    """
    vx, vy = [], []
    for i in range(C.WM_HEAD_LEN):
        a = 2 * math.pi * i / C.WM_HEAD_LEN
        vx.append(math.floor(WM_ARC_SPEED * math.cos(a) + 0.5))
        vy.append(math.floor(WM_ARC_SPEED * math.sin(a) + 0.5))
    return tuple(vx), tuple(vy)


HEAD_VX, HEAD_VY = _heading_table()

# The properties src/movement.asm asserts about its own table, restated so a
# broken copy fails here rather than in a preview nobody double-checks.
assert HEAD_VX[0] == WM_ARC_SPEED and HEAD_VY[0] == 0
assert HEAD_VX[C.WM_HEAD_LEN // 4] == 0 and HEAD_VY[C.WM_HEAD_LEN // 4] == WM_ARC_SPEED
assert HEAD_VX[C.WM_HEAD_LEN // 2] == -WM_ARC_SPEED and HEAD_VY[C.WM_HEAD_LEN // 2] == 0
assert all(HEAD_VX[i] or HEAD_VY[i] for i in range(C.WM_HEAD_LEN))


# ===========================================================================
# The 6502's arithmetic, exactly
# ===========================================================================

def s8(b):
    """A byte read as a signed two's-complement value."""
    b &= 0xFF
    return b - 256 if b & 0x80 else b


def acc_step(acc, v):
    """wmApplyVelocity's per-axis half. Returns (whole pixels, new remainder).

        lda wmAccX,x / clc / adc wmVX,x     sum, IN ONE BYTE, carry discarded
        and #3                              remainder, always 0..3
        cmp #$80 / ror / cmp #$80 / ror     ARITHMETIC shift right by two

    The sign handling is the whole trick and src/movement.asm says why: for
    sum = -5 the arithmetic shift gives -2 (floor, not truncation) and -5 & 3
    is 3, so -2*4 + 3 = -5. The remainder stays positive and the division
    floors, which is what a position accumulator needs; a logical shift would
    drift one pixel every four frames in one direction and every curve in the
    game would visibly sag.

    Python's >> on a negative int is already an arithmetic shift with floor
    semantics, so `s8(total) >> 2` is the same two RORs.
    """
    total = (acc + (v & 0xFF)) & 0xFF       # clc/adc: the carry out is dropped
    return s8(total) >> 2, total & 3


def add_x9(lo, hi, delta):
    """Nine-bit X plus a signed delta, with the engine's carry/borrow dance.

    Mirrors both wmApplyVelocity's X half and waveSpawnMember's fan-out loop,
    which are the same five instructions: add, remember the sign, and move the
    high byte only when the low byte actually crossed.
    """
    if delta == 0:                          # beq wmXDone
        return lo, hi
    total = lo + (delta & 0xFF)
    new_lo = total & 0xFF
    carry = total > 0xFF
    if delta < 0:                           # bmi wmXLeft
        if not carry:                       # a CLEAR carry is the borrow
            hi = (hi - 1) & 0xFF
    elif carry:
        hi = (hi + 1) & 0xFF
    return new_lo, hi


def add_y8(y, delta):
    """Eight bits, and it wraps. src/movement.asm adds with no high byte at
    all, so logY 250 + 10 is 4 -- which the despawn rule then reads."""
    return (y + (delta & 0xFF)) & 0xFF


# ===========================================================================
# One object's movement state — the fields src/movement.asm keeps per slot
# ===========================================================================

class _Obj:
    """wmMode/wmStage/wmPhase/wmTimer/wmSteps/wmVX/wmVY/wmAccX/wmAccY plus the
    logical position, under the engine's own names.

    wmStage IS A BYTE OFFSET IN THE ENGINE and a record index here. The two
    are the same cursor: wmEnterNext advances it by exactly WM_STAGE_SIZE and
    nothing else ever writes it, so index n and offset n*4 step together. The
    index is used because this module takes semantic v6 objects rather than a
    packed table, and a byte offset would be an exporter concern leaking into
    a simulator.
    """

    __slots__ = ("mode", "stage", "phase", "timer", "steps", "vx", "vy",
                 "acc_x", "acc_y", "log_x", "log_x_hi", "log_y", "gone",
                 "speed")

    def __init__(self):
        self.mode = self.stage = self.phase = self.timer = self.steps = 0
        self.vx = self.vy = self.acc_x = self.acc_y = 0
        self.log_x = self.log_x_hi = self.log_y = 0
        self.gone = False
        # wmSpeed. Cleared to 1x rather than to zero, exactly as wmClearSlot
        # does it: a zero multiplier is not a harmless default.
        self.speed = C.TRIG_SPEED_1X

    @property
    def x9(self):
        return self.log_x | (self.log_x_hi << 8)


def _apply_speed(obj):
    """wmApplySpeed: scale the velocity just written by this object's speed.

    THE SAME TWO COLD POINTS THE ENGINE USES -- after the heading table is read
    and after a STRAIGHT/HOLD record is taken up -- so the preview and the 6502
    scale the same values at the same moments. WM_EXIT is covered by doing
    nothing here, because it does not rewrite the velocity and therefore
    inherits whatever was last scaled.
    """
    if obj.speed == C.TRIG_SPEED_1X:
        return                          # bit-exact no-op, as on the machine
    obj.vx = C.scale_velocity(obj.vx, obj.speed)
    obj.vy = C.scale_velocity(obj.vy, obj.speed)


def _load_heading(obj):
    """wmLoadHeading: velocity <- the table at this object's heading.

    No mirroring or negation -- the table already holds every direction, which
    is why WM_ARC_MIRROR differs from WM_ARC only in which way it steps.
    """
    obj.vx = HEAD_VX[obj.phase]
    obj.vy = HEAD_VY[obj.phase]
    _apply_speed(obj)


def _enter_stage(obj, stages):
    """wmEnterStage. Also the SPAWN path, exactly as in the engine: waves.asm
    points a new enemy at record 0 and calls straight in here, so a program's
    first stage cannot behave differently from the same stage in the middle.
    """
    if obj.stage >= len(stages):
        # src/waves.asm rejects a program that does not end in WM_EXIT at
        # assembly time, so the engine can only reach this by walking off a
        # table -- which is precisely what must not be simulated as anything.
        raise SimulationError(
            "the movement program runs past its last stage: it does not end "
            "in EXIT")
    rec = stages[obj.stage]
    mode = C.MOVEMENT_KINDS.get(rec.kind)
    if mode is None:
        raise SimulationError(f"unknown movement stage kind {rec.kind!r}")
    obj.mode = mode

    if mode == C.WM_EXIT:
        # THE VELOCITY IS NOT RESET, and that is what makes ARC -> EXIT
        # continuous: no frame on which speed jumps because a mode byte
        # changed.
        obj.timer = 0                       # unbounded: the despawn rule ends it
        return

    if mode in (C.WM_ARC, C.WM_ARC_MIRROR):
        obj.steps = rec.steps & 0xFF
        obj.timer = rec.frames_per_step & 0xFF
        # BYTE 3 IS THE ENTRY HEADING, or the continue sentinel. Taking the
        # heading's velocity IMMEDIATELY rather than after one step is what
        # makes a turn entered from a straight leg start turning next frame.
        head = rec.entry_heading
        if not (isinstance(head, str) and head == "CONT"):
            if not isinstance(head, int) or not 0 <= head < C.WM_HEAD_LEN:
                raise SimulationError(
                    f"stage {obj.stage}: entry heading {head!r} is neither a "
                    f"heading 0..{C.WM_HEAD_LEN - 1} nor CONT")
            obj.phase = head
        _load_heading(obj)
        return

    # WM_STRAIGHT / WM_HOLD: an authored velocity for an authored time.
    obj.timer = rec.frames & 0xFF
    obj.vx = s8(rec.vx)
    obj.vy = s8(rec.vy)
    _apply_speed(obj)


def _apply_velocity(obj):
    """wmApplyVelocity, both axes."""
    dx, obj.acc_x = acc_step(obj.acc_x, obj.vx)
    obj.log_x, obj.log_x_hi = add_x9(obj.log_x, obj.log_x_hi, dx)
    dy, obj.acc_y = acc_step(obj.acc_y, obj.vy)
    obj.log_y = add_y8(obj.log_y, dy)


def _tick(obj, stages):
    """wmTick: POSITION FIRST, then the primitive advances.

    That order is a decision src/movement.asm spells out -- an object spawned
    with a velocity already set moves by exactly that velocity on its first
    frame, and a phase change takes effect on the frame AFTER the one that
    requested it. Advance-then-move would silently skip the first phase of
    every arc.
    """
    _apply_velocity(obj)

    if obj.mode in (C.WM_ARC, C.WM_ARC_MIRROR):
        # wmArcStep. Note there is NO zero test before the dec: an arc's timer
        # is always armed by wmEnterStage.
        obj.timer = (obj.timer - 1) & 0xFF
        if obj.timer != 0:
            return                          # still holding this heading
        step = 1 if obj.mode == C.WM_ARC else -1
        obj.phase = (obj.phase + step) & WM_HEAD_MASK    # AND #WM_HEAD_MASK is
        _load_heading(obj)                               # the whole of "loops work"
        obj.timer = stages[obj.stage].frames_per_step & 0xFF
        obj.steps = (obj.steps - 1) & 0xFF
        if obj.steps == 0:
            _enter_next(obj, stages)
        return

    if obj.mode == C.WM_EXIT:
        return                              # terminal: constant velocity

    # wmTimedStep: WM_STRAIGHT and WM_HOLD share one mechanism.
    if obj.timer == 0:
        return                              # a zero timer means "run for ever"
    obj.timer = (obj.timer - 1) & 0xFF
    if obj.timer == 0:
        _enter_next(obj, stages)


def _enter_next(obj, stages):
    """wmEnterNext: this stage is finished; take up the next record."""
    obj.stage += 1
    _enter_stage(obj, stages)


def _despawned(obj):
    """src/enemy.asm's despawn rules, in enemyTick's own order.

    Read AFTER wmTick, on the post-move position and the post-advance
    velocity, because that is when enemyTick reads them -- which is what
    decides the exact frame an EXIT ends on.

    A sprite behind a border counts as gone only if it is still TRAVELLING
    that way, which is what lets a pattern enter through one. Every wave in
    the game spawns above the aperture and flies down through the top line, so
    position alone would free every enemy at birth.
    """
    if obj.log_x_hi != 0:
        if obj.log_x >= ENEMY_CLEAR_X_RIGHT_LO:
            if obj.vx > 0:                  # beq/bmi both fall through
                return True
    else:
        if obj.log_x < ENEMY_CLEAR_X_LEFT:
            if obj.vx < 0:                  # still travelling left
                return True

    if obj.log_y >= ENEMY_CLEAR_Y:
        return True                         # below the bottom: gone either way
    if obj.log_y >= ENEMY_CLEAR_Y_TOP:
        return False                        # inside the band: the common case
    return obj.vy < 0                       # above: gone only if still climbing


# ===========================================================================
# The public, GUI-independent result types
# ===========================================================================

@dataclass(frozen=True)
class MemberFrame:
    """One member's authoritative state at the end of one frame.

    Immutable, and every field is an integer the engine actually holds. `x` is
    the nine-bit logical X and `y` the eight-bit logical Y -- the same numbers
    src/movement.asm writes into logX/logXHi/logY.
    """
    frame: int
    member: int
    spawned: bool
    active: bool
    exited: bool
    x: int
    y: int
    stage_index: int
    stage_kind: str
    heading: int
    vx: int
    vy: int
    acc_x: int
    acc_y: int
    timer: int = 0
    steps: int = 0

    @property
    def visible(self):
        """Whether the renderer would admit it AND it is inside the display
        window horizontally. src/renderer.asm admits on Y ALONE, so this is
        deliberately two separate facts; src/waves.asm's own spawn proof uses
        exactly this test."""
        return (MIN_SPRITE_Y <= self.y <= MAX_SPRITE_Y
                and self.x + 23 >= DISPLAY_X_FIRST and self.x <= DISPLAY_X_LAST)


@dataclass(frozen=True)
class WaveSimulation:
    """A complete ordinary wave, frame by frame.

    `frames[f]` is the tuple of MemberFrame for frame f -- one entry per
    member that has spawned and not yet despawned. `paths[m]` is member m's
    complete history, which is what a trajectory is drawn from.
    """
    wave_id: str
    program_id: str
    count: int
    interval: int
    frames: tuple
    paths: tuple
    spawn_frames: tuple
    all_exited: bool
    frame_count: int

    def at(self, frame):
        if not self.frames:
            return ()
        return self.frames[max(0, min(frame, len(self.frames) - 1))]


# ===========================================================================
# Simulating one member
# ===========================================================================

def member_start(wave, member):
    """waveSpawnMember's placement: startX + index*xStep in nine bits,
    startY + index*yStep in eight.

    A REPEATED ADD, not a multiply, because that is what the engine does and
    the two differ: the Y add wraps at 256 every time round the loop, so a
    large yStep does not accumulate into a ninth bit that never existed.
    """
    lo, hi = wave.start_x & 0xFF, (wave.start_x >> 8) & 0xFF
    y = wave.start_y & 0xFF
    for _ in range(member):
        lo, hi = add_x9(lo, hi, s8(wave.x_step))
        y = add_y8(y, s8(wave.y_step))
    return lo, hi, y


def simulate_member(wave, stages, member, max_frames,
                    speed=C.TRIG_SPEED_1X):
    """One member's whole life, from its spawn frame to its despawn.

    Returns (list of per-frame snapshots, exited). Frame numbers are relative
    to the member's own spawn: index 0 is the spawn frame itself, on which the
    member exists at its start position and HAS NOT MOVED -- src/waves.asm
    spawns from waveTick, which gameFrame runs AFTER objectUpdateAll, so a new
    enemy's first wmTick is a frame away.
    """
    obj = _Obj()
    obj.log_x, obj.log_x_hi, obj.log_y = member_start(wave, member)
    if not 0 <= wave.heading < C.WM_HEAD_LEN:
        raise SimulationError(
            f"launch heading {wave.heading} is not a heading "
            f"0..{C.WM_HEAD_LEN - 1}")
    obj.phase = wave.heading                # waveSpawnMember: launch heading
    obj.stage = 0
    obj.acc_x = obj.acc_y = 0
    # BEFORE THE FIRST STAGE IS ENTERED, exactly as waveSpawnMember does it:
    # _enter_stage scales the velocity it writes, so the speed has to be on
    # the object first or the opening leg would fly at 1x.
    obj.speed = speed
    _enter_stage(obj, stages)

    out = [_snap(obj, 0, member, stages)]
    for f in range(1, max_frames):
        _tick(obj, stages)
        if _despawned(obj):
            # THE FREEING FRAME IS NOT A FRAME OF LIFE. enemyTick moves the
            # object and then applies the despawn rules in the same call, so a
            # freed object never reaches the renderer on that frame -- it is
            # already out of the active set by the time the schedule is built.
            # The path therefore ends on the last frame it was still alive,
            # which is what the production-loop fixture records.
            return out, True
        out.append(_snap(obj, f, member, stages))
    return out, False


def simulate_legacy_dropper(side, max_frames):
    """src/dropper.asm's hard-coded flight, frame by frame. Returns (path, exited).

    THE SMALLEST REPRESENTATION THAT IS ACTUALLY TRUE. The alternative offered
    itself: draw member 0 on the escorts' wave definition and be done. That
    would be a lie the author could act on -- the legacy Dropper enters from a
    screen edge, holds one height, crosses three times and leaves the way it
    came, and none of that resembles a formation path. This is thirty lines and
    it is correct.

    THE WEAVE IS NOT A MOVEMENT PROGRAM AND CANNOT BE ONE. dropperFly writes
    logY OUTRIGHT from a table every frame; wmVY is held at zero deliberately,
    because src/enemy.asm's top despawn edge reads it. So member 0's Y here does
    not come from the integrator at all, which is exactly why this is a separate
    function rather than a synthetic stage list.

    IT IGNORES TRIGGER SPEED, and that is the engine's behaviour rather than an
    omission: dropperFly calls wmApplyVelocity and never wmApplySpeed, so wmVX
    stays at DROP_VX whatever the trigger asked for. The preview showing a legacy
    Dropper unchanged as the author drags the speed control is the truth.

    THE DESPAWN RULES ARE src/enemy.asm's ORDINARY ONES. dropperFly does not
    free anything; it flies on past the turning point once the passes are spent
    and the side edge collects it, which is why wmVX is left pointing outward.
    """
    obj = _Obj()
    obj.log_y = DROP_CENTRE_Y                   # = centre + weave[0]
    obj.vy = 0
    if side == "RIGHT":
        obj.log_x = DROP_ENTRY_RIGHT & 0xFF
        obj.log_x_hi = (DROP_ENTRY_RIGHT >> 8) & 0xFF
        obj.vx = -DROP_VX
    else:
        obj.log_x = DROP_ENTRY_LEFT & 0xFF
        obj.log_x_hi = (DROP_ENTRY_LEFT >> 8) & 0xFF
        obj.vx = DROP_VX

    passes_left = DROP_PASSES
    phase = 0
    hold = DROP_PHASE_HOLD

    def snap(frame):
        return MemberFrame(
            frame=frame, member=0, spawned=True, active=True, exited=False,
            x=obj.log_x + 256 * obj.log_x_hi, y=obj.log_y,
            # NOT A STAGE, AND SAID SO. A legacy Dropper is running no movement
            # program at all, so a stage index would be an invention; the kind
            # names the flight instead, which is what the panel shows.
            stage_index=-1, stage_kind="DROPPER", heading=0,
            vx=obj.vx, vy=0, acc_x=obj.acc_x, acc_y=0)

    out = [snap(0)]
    for f in range(1, max_frames):
        # dropperFly: the ordinary integrator for X, then the weave for Y.
        _apply_velocity(obj)

        hold -= 1
        if hold == 0:
            hold = DROP_PHASE_HOLD
            phase = (phase + 1) % DROP_PHASES
        obj.log_y = (DROP_CENTRE_Y + DROP_WEAVE[phase]) & 0xFF

        # HAS IT REACHED THE FAR SIDE? Skipped entirely once the last pass is
        # spent -- the Dropper is then past the turning point and getting
        # further past it, so a test that still ran would turn it round on every
        # frame. src/dropper.asm says the same in its own words.
        if passes_left:
            x9 = obj.log_x + 256 * obj.log_x_hi
            turning = (x9 >= DROP_X_RIGHT) if obj.vx > 0 else (x9 <= DROP_X_LEFT)
            if turning:
                passes_left -= 1
                if passes_left:
                    obj.vx = -obj.vx
                    obj.acc_x = 0           # start the turn on a whole pixel

        if _despawned(obj):
            return out, True
        out.append(snap(f))
    return out, False


def trace_program(stages, *, x, y, heading, frames):
    """Fly a program with NO lifecycle rules at all: wmEnterStage, then wmTick.

    THE MOVEMENT SEMANTICS ON THEIR OWN, which is what the engine fixture
    records. src/enemy.asm's despawn rules are a separate authority applied by
    enemyTick after wmTick, so proving them together would leave a movement
    mismatch and a lifecycle mismatch indistinguishable. simulate_member()
    layers the lifecycle back on top of exactly this.
    """
    obj = _Obj()
    obj.log_x, obj.log_x_hi = x & 0xFF, (x >> 8) & 0xFF
    obj.log_y = y & 0xFF
    obj.phase = heading
    obj.stage = 0
    _enter_stage(obj, stages)
    out = [_snap(obj, 0, 0, stages)]
    for f in range(1, frames):
        _tick(obj, stages)
        out.append(_snap(obj, f, 0, stages))
    return out


def _snap(obj, frame, member, stages):
    kind = stages[obj.stage].kind if obj.stage < len(stages) else "EXIT"
    return MemberFrame(
        frame=frame, member=member, spawned=True, active=not obj.gone,
        exited=obj.gone, x=obj.x9, y=obj.log_y, stage_index=obj.stage,
        stage_kind=kind, heading=obj.phase, vx=obj.vx, vy=obj.vy,
        acc_x=obj.acc_x, acc_y=obj.acc_y, timer=obj.timer, steps=obj.steps)


# ===========================================================================
# Simulating a whole formation
# ===========================================================================

def resolve_program(project, wave):
    """wave definition -> movement program, or a reason it cannot be found."""
    for prog in project.movement_programs:
        if prog.id == wave.movement_program:
            return prog
    raise SimulationError(
        f"wave {wave.id!r} names movement program "
        f"{wave.movement_program!r}, which does not exist")


def simulate_wave(project, wave, *, max_frames=None, stages=None,
                  speed=C.TRIG_SPEED_1X, member0=None):
    """A complete ordinary wave over its whole useful life.

    Frame 0 is the frame the trigger became due, and MEMBER 0 IS SENT ON IT.

    That is worth spelling out because src/waves.asm's own comment beside the
    arming code says "the first member goes out next frame" -- which is what
    wvTimer = 1 means on its own, but not what happens. waveTick calls
    waveStartNext FIRST and only then walks the instances, so the instance it
    just armed is run in the same frame: the timer is decremented to zero
    immediately and the member goes out. Verified against the production loop
    in tools/level_editor/test_formation_sim_engine.py.

    Member k therefore appears on frame k*interval.

    MEMBERS DO NOT START TOGETHER and each initialises its own movement state
    independently: wmClearSlot wipes every field on allocation, and the launch
    heading and first stage are installed per member. Nothing is shared.
    """
    if wave.count < 1:
        raise SimulationError(f"wave {wave.id!r} sends no enemies (count 0)")
    if wave.interval < 1:
        raise SimulationError(
            f"wave {wave.id!r} has an interval of 0, which would send the "
            f"whole formation in one frame")

    prog = resolve_program(project, wave)
    # `stages` OVERRIDES what the program has stored, and exists for exactly
    # one caller: previewing a SEMANTIC program from a heading no wave uses.
    # Those stored records were compiled against the launch heading of the
    # waves that use it, so a straight leg's velocity is baked in -- flying
    # them from some other heading would show a path the engine never flies.
    # The caller compiles the segments afresh and passes the result. Nothing
    # is written back: a preview must not edit the asset it is previewing.
    if stages is None:
        stages = prog.stages
    if not stages:
        raise SimulationError(f"movement program {prog.id!r} has no stages")
    if stages[-1].kind != "EXIT":
        raise SimulationError(
            f"movement program {prog.id!r} does not end in EXIT and would run "
            f"off the end of the stage table")
    for i, st in enumerate(stages[:-1]):
        if st.kind == "EXIT":
            raise SimulationError(
                f"movement program {prog.id!r}: EXIT is terminal and cannot be "
                f"followed by another stage (stage {i})")
        if st.kind in C.ARC_KINDS:
            if st.steps < 1:
                raise SimulationError(
                    f"movement program {prog.id!r}: stage {i} turns 0 steps and "
                    f"would never advance")
            if st.frames_per_step < 1:
                raise SimulationError(
                    f"movement program {prog.id!r}: stage {i} has 0 frames per "
                    f"step and would turn infinitely fast")
        elif st.frames < 1:
            raise SimulationError(
                f"movement program {prog.id!r}: stage {i} lasts 0 frames and "
                f"would never advance")

    spawn_frames = tuple(m * wave.interval for m in range(wave.count))
    budget = max_frames or (spawn_frames[-1] + SIM_FRAME_BUDGET + 1)

    # MEMBER 0 MAY BE SOMEBODY ELSE'S BUSINESS, and only member 0. A Dropper
    # trigger's member 0 flies either the legacy trajectory or its own movement
    # program, while members 1..N-1 are ordinary escorts on this definition --
    # so the override is one callable for one member and the rest of this
    # routine does not know it happened. THE ESCORTS ARE NOT TOUCHED: their
    # indices, their spawn frames and their per-member offsets are the ones the
    # definition gives them, and the member-0 "hole" is not closed or
    # renumbered. See src/waves.asm's spawn seam.
    paths, exited = [], []
    for m in range(wave.count):
        if m == 0 and member0 is not None:
            life, went = member0(budget - spawn_frames[0])
        else:
            life, went = simulate_member(wave, stages, m,
                                         budget - spawn_frames[m], speed)
        paths.append(tuple(life))
        exited.append(went)

    total = max(spawn_frames[m] + len(paths[m]) for m in range(wave.count))
    frames = []
    for f in range(total):
        here = []
        for m in range(wave.count):
            i = f - spawn_frames[m]
            if 0 <= i < len(paths[m]):
                here.append(replace(paths[m][i], frame=f))
        frames.append(tuple(here))

    return WaveSimulation(
        wave_id=wave.id, program_id=prog.id, count=wave.count,
        interval=wave.interval, frames=tuple(frames),
        paths=tuple(tuple(replace(s, frame=spawn_frames[m] + s.frame)
                          for s in paths[m]) for m in range(wave.count)),
        spawn_frames=spawn_frames, all_exited=all(exited),
        frame_count=total)


# ===========================================================================
# Resolving what the author selected
# ===========================================================================

def wave_by_id(project, wave_id):
    for w in project.wave_definitions:
        if w.id == wave_id:
            return w
    raise SimulationError(f"wave definition {wave_id!r} does not exist")


def program_by_id(project, program_id):
    for prog in project.movement_programs:
        if prog.id == program_id:
            return prog
    raise SimulationError(
        f"movement program {program_id!r} does not exist")


def trigger_is_dropper(trig):
    """Does this trigger's enemy carry the token-dropping behaviour?

    BY BEHAVIOUR, NOT BY NAME. This used to compare against the literal
    "DROPPER", which meant a roster identity carrying BEHAVIOUR_DROPPER under
    any other name was previewed as an ordinary wave -- a picture the engine
    does not fly. validation_v6 has always asked the behaviour; asking the same
    authority is what makes the preview and the validator agree.
    """
    return C.identity_behaviour(trig.species) == C.BEHAVIOUR_DROPPER


def simulate_trigger(project, index, *, stages=None, max_frames=None):
    """trigger -> what it actually sends, on the LIVE project.

    TWO KINDS OF TRIGGER, AND THEY ARE NOW GENUINELY SEPARATE THINGS:

      * an ORDINARY trigger sends its wave definition's formation -- count
        members at interval frames apart, each on the definition's program;
      * a DROPPER trigger sends EXACTLY ONE OBJECT, the Dropper, flying either
        src/dropper.asm's hard-coded trajectory or the movement program the
        trigger named for it.

    A DROPPER TRIGGER'S DEFINITION IS ITS PLACEMENT, NOT ITS FORMATION. The
    count, interval and per-member steps are inert: src/waves.asm arms the
    instance with wvLeft = 1 whatever the definition says, so what remains of
    the definition is a start position and a launch heading. That is exactly
    what one object needs, which is why no parallel structure was invented for
    it -- see reports/simplify-dropper-single-object-trigger.md.

    NO PHANTOM ESCORTS. This used to draw member 0 as the Dropper and members
    1..N-1 as escorts from the same trigger. There is no such encounter any
    more: an author who wants company for a Dropper writes a second, ordinary
    trigger a row away, and that trigger previews independently as its own wave.

    `stages` OVERRIDES THE DEFINITION'S PROGRAM, for previewing a semantic
    program compiled from a heading no wave uses. It has no effect on a Dropper,
    whose path is its own.
    """
    if not 0 <= index < len(project.triggers):
        raise SimulationError("no trigger selected")
    trig = project.triggers[index]
    wave = wave_by_id(project, trig.wave_definition)

    if not trigger_is_dropper(trig):
        # THE TRIGGER'S OWN SPEED, which is the whole point of previewing a
        # trigger rather than its wave: the same definition shown from two
        # triggers must travel at each one's authored pace.
        return simulate_wave(project, wave, stages=stages,
                             max_frames=max_frames, speed=trig.resolved_speed)

    return simulate_dropper(project, trig, wave, max_frames=max_frames)


def simulate_dropper(project, trig, wave, *, max_frames=None):
    """One Dropper, from a Dropper trigger. Always exactly one path.

    THE DEFINITION IS READ FOR PLACEMENT AND HEADING ONLY, and `count` is
    forced to one here for the same reason src/waves.asm forces wvLeft to one:
    a definition may be shared with an ordinary trigger that really does send
    six, and neither the runtime nor this simulator may let that leak into the
    Dropper.
    """
    placed = replace(wave, count=1, interval=1)

    if trig.dropper_is_legacy:
        # THE LEGACY TRAJECTORY IGNORES THE PLACEMENT ENTIRELY: dropperLaunch
        # overrides logX/logY from the entry side, so the definition's start
        # position does not reach it. Drawing it from the definition would show
        # a path the engine never flies.
        side = trig.dropper_side
        return simulate_wave(project, placed, max_frames=max_frames,
                             speed=trig.resolved_speed,
                             member0=lambda budget:
                                 simulate_legacy_dropper(side, budget))

    dprog = program_by_id(project, trig.dropper_program)
    if not dprog.stages:
        raise SimulationError(
            f"Dropper movement program {dprog.id!r} has no stages")
    speed = trig.resolved_speed
    return simulate_wave(project, placed, max_frames=max_frames, speed=speed,
                         member0=lambda budget: simulate_member(
                             placed, dprog.stages, 0, budget, speed))


def preview_program(project, program, *, heading=0, start=(160, 40),
                    max_frames=None, stages=None):
    """One movement program on its own, with no wave around it.

    For previewing from the Movement programs tab, where there is no formation
    and no launch heading. A SYNTHETIC wave definition is built rather than a
    second simulation path, so what is drawn is the same interpreter that
    draws everything else.
    """
    fake = project_v6.WaveDefinition(
        id=f"({program.id})", count=1, interval=1,
        start_x=start[0], start_y=start[1], x_step=0, y_step=0,
        heading=heading, movement_program=program.id)
    return simulate_wave(project, fake, max_frames=max_frames, stages=stages)
