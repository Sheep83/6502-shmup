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

    * DROPPER / token / protector choreography. src/dropper.asm takes a
      Dropper off its wave's path immediately after wmEnterStage, so an
      ordinary-wave simulation of one would be a fiction. simulate_wave()
      refuses rather than draws it.
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

SPRITE_HEIGHT = 21          # src/renderer.asm
MIN_SPRITE_Y = 55           # src/renderer.asm: first admitted sprite Y
MAX_SPRITE_Y = 226          # src/renderer.asm: last admitted sprite Y
APERTURE_TOP_RASTER = 55    # src/main.asm TOP_SPLIT_LINE
APERTURE_BOT_RASTER = 247   # src/enemy.asm derives ENEMY_CLEAR_Y from it

ENEMY_CLEAR_X_LEFT = 4                      # src/enemy.asm
ENEMY_CLEAR_X_RIGHT = 344                   # src/enemy.asm
ENEMY_CLEAR_X_RIGHT_LO = ENEMY_CLEAR_X_RIGHT - 256      # 88
ENEMY_HIDDEN_Y = APERTURE_TOP_RASTER - SPRITE_HEIGHT    # 34
ENEMY_CLEAR_Y = APERTURE_BOT_RASTER + 1                 # 248
ENEMY_CLEAR_Y_TOP = ENEMY_HIDDEN_Y + 1                  # 35

# The horizontal display window, in the same nine-bit X the objects use.
# src/waves.asm's spawn proof uses exactly these numbers ("columns 24..343").
DISPLAY_X_FIRST = 24
DISPLAY_X_LAST = 343

SIM_FRAME_BUDGET = 900      # src/waves.asm: frames before a path is stuck

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
                 "acc_x", "acc_y", "log_x", "log_x_hi", "log_y", "gone")

    def __init__(self):
        self.mode = self.stage = self.phase = self.timer = self.steps = 0
        self.vx = self.vy = self.acc_x = self.acc_y = 0
        self.log_x = self.log_x_hi = self.log_y = 0
        self.gone = False

    @property
    def x9(self):
        return self.log_x | (self.log_x_hi << 8)


def _load_heading(obj):
    """wmLoadHeading: velocity <- the table at this object's heading.

    No mirroring or negation -- the table already holds every direction, which
    is why WM_ARC_MIRROR differs from WM_ARC only in which way it steps.
    """
    obj.vx = HEAD_VX[obj.phase]
    obj.vy = HEAD_VY[obj.phase]


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


def simulate_member(wave, stages, member, max_frames):
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


def simulate_wave(project, wave, *, max_frames=None):
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

    paths, exited = [], []
    for m in range(wave.count):
        life, went = simulate_member(wave, stages, m,
                                     budget - spawn_frames[m])
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


def simulate_trigger(project, index):
    """trigger -> wave definition -> movement program, on the LIVE project.

    Refuses a Dropper rather than drawing one: src/waves.asm calls
    dropperLaunch immediately after wmEnterStage, which overwrites the mode,
    velocity and timer the wave just armed, so the member never flies the
    authored path at all. See src/dropper.asm.
    """
    if not 0 <= index < len(project.triggers):
        raise SimulationError("no trigger selected")
    trig = project.triggers[index]
    if trig.species == "DROPPER":
        raise SimulationError(
            "DROPPER triggers are not previewed in this phase.\n\n"
            "A Dropper is taken off its wave's authored path the instant it "
            "spawns -- src/dropper.asm installs its own three-pass flight over "
            "the top of the aperture -- so an ordinary-wave preview would show "
            "a trajectory the engine never flies.")
    return simulate_wave(project, wave_by_id(project, trig.wave_definition))


def preview_program(project, program, *, heading=0, start=(160, 40),
                    max_frames=None):
    """One movement program on its own, with no wave around it.

    For previewing from the Movement programs tab, where there is no formation
    and no launch heading. A SYNTHETIC wave definition is built rather than a
    second simulation path, so what is drawn is the same interpreter that
    draws everything else.
    """
    fake = project_v6.WaveDefinition(
        id=f"({program.id})", count=1, interval=1,
        start_x=start[0], start_y=start[1], x_step=0, y_step=0,
        colour=1, heading=heading, movement_program=program.id)
    return simulate_wave(project, fake, max_frames=max_frames)
