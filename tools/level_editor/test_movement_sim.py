#!/usr/bin/env python3
"""Phase 6A, simulation core: the primitives, the compositions, the refusals.

THIS FILE CANNOT PROVE THE SIMULATOR IS RIGHT. It is Python checking Python,
so it can only prove the simulator does what this file believes the engine
does. What settles that question is test_movement_sim_engine.py, which
compares the same code with state recorded off a real 6502.

What this file IS for: the cases an engine trace covers only incidentally --
the arithmetic helpers on their own, the refusals, determinism, and the
formation geometry -- and keeping the whole thing honest at headless speed
when nobody wants to boot an emulator.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract_v2 as C                                     # noqa: E402
import migration_v6                                         # noqa: E402
import movement_sim as ms                                   # noqa: E402
import project_v6                                           # noqa: E402

CANON = Path(__file__).resolve().parent / "levels/level1/level.v6.json"

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


def S(kind, **kw):
    return project_v6.MovementStage(kind=kind, **kw)


EXIT = S("EXIT")


def prog(*stages):
    return list(stages)


def fly(stages, *, x=100, y=100, heading=0, frames=40):
    return ms.trace_program(stages, x=x, y=y, heading=heading, frames=frames)


# =======================================================================
# 1. the fixed-point and signed helpers
# =======================================================================
check("s8 reads the top bit as a sign", ms.s8(0xFF) == -1 and ms.s8(0x80) == -128
      and ms.s8(0x7F) == 127 and ms.s8(0) == 0)

# The worked example src/movement.asm gives for why the shift must be
# arithmetic: sum = -5 must floor to -2 and leave a POSITIVE remainder of 3.
d, a = ms.acc_step(3, -8)
check("acc_step floors a negative sum instead of truncating it",
      (d, a) == (-2, 3), f"sum -5 -> delta {d}, acc {a}")
check("...and -2*4 + 3 is exactly the -5 it started from", -2 * 4 + 3 == -5)

check("a quarter-pixel velocity moves one pixel every four frames",
      [ms.acc_step(a, 1)[0] for a in (0, 1, 2, 3)] == [0, 0, 0, 1])
check("...and the remainder walks 1,2,3,0",
      [ms.acc_step(a, 1)[1] for a in (0, 1, 2, 3)] == [1, 2, 3, 0])

# The engine adds in ONE BYTE and throws the carry away. acc is 0..3 and every
# authored velocity is small, so this never bites in practice -- but a
# simulator that used Python's unbounded ints would diverge the day it did.
check("acc_step adds in a single byte, as clc/adc does",
      ms.acc_step(3, 0xFF & -1) == ms.acc_step(3, -1) == (0, 2))

acc, total = 0, 0
for _ in range(200):
    d, acc = ms.acc_step(acc, 6)
    total += d
check("quarter-pixel accumulation does not drift over 200 frames",
      total == 200 * 6 // 4, f"{total} px for 200 frames at 6 quarter-pixels")

acc, total = 0, 0
for _ in range(200):
    d, acc = ms.acc_step(acc, -6)
    total += d
check("...and does not drift downwards either", total == -300, str(total))

check("add_x9 carries into the high byte going right",
      ms.add_x9(0xFF, 0, 1) == (0x00, 1))
check("add_x9 borrows out of the high byte going left",
      ms.add_x9(0x00, 1, -1) == (0xFF, 0))
check("add_x9 leaves the high byte alone when the low byte does not cross",
      ms.add_x9(0x10, 1, 5) == (0x15, 1))
check("add_y8 wraps at 256, because logY is eight bits and has no more",
      ms.add_y8(250, 10) == 4 and ms.add_y8(2, -10) == 248)

check("the heading table is due east at 0 and due south at a quarter turn",
      (ms.HEAD_VX[0], ms.HEAD_VY[0]) == (6, 0)
      and (ms.HEAD_VX[16], ms.HEAD_VY[16]) == (0, 6))
check("no heading in the table stands still",
      all(ms.HEAD_VX[i] or ms.HEAD_VY[i] for i in range(64)))
check("one heading step never moves a velocity by more than a quarter pixel",
      all(abs(ms.HEAD_VX[(i + 1) % 64] - ms.HEAD_VX[i]) <= 1
          and abs(ms.HEAD_VY[(i + 1) % 64] - ms.HEAD_VY[i]) <= 1
          for i in range(64)))


# =======================================================================
# 2. STRAIGHT
# =======================================================================
t = fly(prog(S("STRAIGHT", frames=10, vx=8, vy=0), EXIT), frames=14)
check("STRAIGHT moves on its FIRST frame, not after one",
      t[1].x == 102, f"x {t[0].x} -> {t[1].x}")
check("STRAIGHT at 8 quarter-pixels covers two pixels a frame",
      [s.x for s in t[:5]] == [100, 102, 104, 106, 108])
check("a STRAIGHT of 10 frames hands on at exactly frame 10",
      t[9].stage_kind == "STRAIGHT" and t[10].stage_kind == "EXIT",
      f"f9 {t[9].stage_kind}, f10 {t[10].stage_kind}")
check("...and the stage cursor moved exactly one record",
      t[10].stage_index == 1)

t = fly(prog(S("STRAIGHT", frames=8, vx=-6, vy=-2), EXIT), frames=12)
check("a NEGATIVE straight velocity walks both axes backwards",
      t[8].x < 100 and t[8].y < 100, f"({t[8].x},{t[8].y})")
check("...by exactly floor(v*n/4)", t[8].x == 100 + (-6 * 8) // 4
      and t[8].y == 100 + (-2 * 8) // 4, f"({t[8].x},{t[8].y})")


# =======================================================================
# 3. HOLD
# =======================================================================
t = fly(prog(S("HOLD", frames=12, vx=0, vy=0), EXIT), frames=16)
check("a HOLD with no velocity does not move at all",
      all(s.x == 100 and s.y == 100 for s in t))
check("...and still hands on when its timer runs out",
      t[11].stage_kind == "HOLD" and t[12].stage_kind == "EXIT")
check("HOLD and STRAIGHT are the same mechanism with a different name",
      [s.x for s in fly(prog(S("HOLD", frames=9, vx=5, vy=0), EXIT), frames=10)]
      == [s.x for s in fly(prog(S("STRAIGHT", frames=9, vx=5, vy=0), EXIT),
                           frames=10)])


# =======================================================================
# 4. ARC, ARC_MIRROR, and the heading
# =======================================================================
t = fly(prog(S("ARC", steps=4, frames_per_step=3, entry_heading=0), EXIT),
        frames=16)
check("an ARC takes its entry heading's velocity IMMEDIATELY",
      t[0].vx == 6 and t[0].vy == 0)
check("...and holds it for frames_per_step frames before rotating",
      [s.heading for s in t[:7]] == [0, 0, 0, 1, 1, 1, 2],
      str([s.heading for s in t[:7]]))
check("an ARC of 4 steps at 3 frames each lasts exactly 12 frames",
      t[11].stage_kind == "ARC" and t[12].stage_kind == "EXIT")
check("...and leaves on the heading AFTER its last step, which EXIT inherits",
      t[12].heading == 4 and (t[12].vx, t[12].vy) == (ms.HEAD_VX[4], ms.HEAD_VY[4]),
      f"heading {t[12].heading}")

t = fly(prog(S("ARC_MIRROR", steps=4, frames_per_step=3, entry_heading=10), EXIT),
        frames=16)
check("ARC_MIRROR rotates the other way",
      [s.heading for s in t[:7]] == [10, 10, 10, 9, 9, 9, 8],
      str([s.heading for s in t[:7]]))
check("...and is otherwise the same primitive", t[12].heading == 6)

t = fly(prog(S("ARC", steps=8, frames_per_step=1, entry_heading=60), EXIT),
        frames=12)
# Eight steps of one frame each, so the last rotation (to 4) is also the frame
# the stage ends on -- and EXIT then keeps that heading, which is why the
# sequence stops climbing rather than running to 5.
check("an ARC wraps 63 -> 0 rather than running off the table",
      [s.heading for s in t[:10]] == [60, 61, 62, 63, 0, 1, 2, 3, 4, 4],
      str([s.heading for s in t[:10]]))

t = fly(prog(S("ARC_MIRROR", steps=8, frames_per_step=1, entry_heading=3), EXIT),
        frames=12)
check("an ARC_MIRROR wraps 0 -> 63 going the other way",
      [s.heading for s in t[:10]] == [3, 2, 1, 0, 63, 62, 61, 60, 59, 59],
      str([s.heading for s in t[:10]]))

t = fly(prog(S("ARC", steps=76, frames_per_step=2, entry_heading=8), EXIT),
        frames=200)
check("a turn of more than a full circle simply keeps going (the loop)",
      len({s.heading for s in t[:152]}) == 64,
      f"{len({s.heading for s in t[:152]})} distinct headings")


# =======================================================================
# 5. entry heading: explicit vs CONT
# =======================================================================
t = fly(prog(S("STRAIGHT", frames=4, vx=6, vy=0),
             S("ARC", steps=4, frames_per_step=2, entry_heading=48), EXIT),
        frames=16, heading=0)
check("an EXPLICIT entry heading overrides whatever the object was carrying",
      t[4].heading == 48, f"heading {t[4].heading}")
check("...and the velocity changes with it on the same frame",
      (t[4].vx, t[4].vy) == (ms.HEAD_VX[48], ms.HEAD_VY[48]))

t = fly(prog(S("ARC", steps=4, frames_per_step=2, entry_heading=20),
             S("ARC_MIRROR", steps=4, frames_per_step=2, entry_heading="CONT"),
             EXIT), frames=20)
check("CONT continues from the heading the previous stage finished on",
      t[8].heading == 24, f"heading {t[8].heading}")
check("...and then turns back the other way, which is what makes an S an S",
      [s.heading for s in t[8:15]] == [24, 24, 23, 23, 22, 22, 21],
      str([s.heading for s in t[8:15]]))

check("a launch heading reaches an arc that asks to CONT",
      fly(prog(S("ARC", steps=2, frames_per_step=2, entry_heading="CONT"), EXIT),
          heading=33, frames=4)[0].heading == 33)


# =======================================================================
# 6. EXIT
# =======================================================================
t = fly(prog(S("ARC", steps=4, frames_per_step=2, entry_heading=16), EXIT),
        frames=30)
vx, vy = t[8].vx, t[8].vy
check("EXIT keeps the velocity the stage before it left behind",
      all((s.vx, s.vy) == (vx, vy) for s in t[8:]))
check("...so ARC -> EXIT has no frame on which the speed jumps",
      (t[7].vx, t[7].vy) != (0, 0) and t[8].stage_kind == "EXIT")
check("EXIT never advances the stage cursor again",
      all(s.stage_index == 1 for s in t[8:]))


# =======================================================================
# 7. multi-stage continuity, and the canonical S-turn
# =======================================================================
proj = migration_v6.load_any(CANON).project
progs = {p.id: p for p in proj.movement_programs}
waves = {w.id: w for w in proj.wave_definitions}

check("the canonical project still has four movement programs",
      len(proj.movement_programs) == 4)
check("...13 stage records in 52 bytes",
      sum(len(p.stages) for p in proj.movement_programs) == 13
      and sum(len(p.stages) for p in proj.movement_programs) * C.WM_STAGE_SIZE == 52)
offs, n = [], 0
for p in proj.movement_programs:
    offs.append(n)
    n += len(p.stages) * C.WM_STAGE_SIZE
check("...at start offsets 0, 12, 24, 40", offs == [0, 12, 24, 40], str(offs))

s_stages = progs["s"].stages
check("the canonical S-turn is ARC_MIRROR then an ARC that CONTinues",
      s_stages[0].kind == "ARC_MIRROR" and s_stages[1].kind == "ARC"
      and s_stages[1].entry_heading == "CONT")
t = fly(s_stages, x=90, y=30, heading=12, frames=140)
check("the S-turn's first arc starts on its OWN explicit heading, not the "
      "wave's launch heading", t[0].heading == 12)
# 12 steps of 3 frames is 36 frames, and the twelfth rotation lands on 0 on
# frame 36 -- the same frame the stage hands on.
check("...turns anticlockwise 12 steps to heading 0",
      t[35].heading == 1 and t[36].heading == 0,
      f"f35 {t[35].heading} f36 {t[36].heading}")
check("...and the CONT arc then curves the OTHER way from exactly there",
      t[36].stage_kind == "ARC" and t[37].heading == 0 and t[39].heading == 1,
      f"f37 {t[37].heading} f39 {t[39].heading}")
turns = [s.heading for s in t[:96]]
check("...so curvature reverses exactly once, at the CONT",
      turns[:36] == sorted(turns[:36], reverse=True)
      and turns[36:96] == sorted(turns[36:96]))


# =======================================================================
# 8. the formation: fan-out, interval, independence
# =======================================================================
sweep = waves["sweep"]
sim = ms.simulate_wave(proj, sweep)
check("every member of a wave is simulated",
      sim.count == len(sim.paths) == sweep.count)
# waveTick arms the instance and then runs it in the SAME frame, so member 0
# goes out on the trigger's own frame -- not on the frame after, which is what
# wvTimer = 1 looks like in isolation. See the note in simulate_wave.
check("member 0 goes out on the frame the trigger became due",
      sim.spawn_frames[0] == 0)
check("and the rest follow at the authored interval",
      sim.spawn_frames == tuple(m * sweep.interval
                                for m in range(sweep.count)),
      str(sim.spawn_frames))
starts = [ms.member_start(sweep, m) for m in range(sweep.count)]
check("the Y fan-out is startY + index*yStep",
      [y for _, _, y in starts] == [64, 84, 104, 124], str(starts))
check("...and with xStep 0 every member shares a column",
      {lo | (hi << 8) for lo, hi, _ in starts} == {0})

check("a member does NOT move on the frame it spawns",
      sim.paths[0][0].x == 0 and sim.paths[0][0].y == 64
      and sim.paths[0][1].x != 0)

check("members do not share movement state: each starts its own program",
      all(p[0].stage_index == 0 and p[0].heading == sweep.heading
          for p in sim.paths))
check("...and each walks the whole program independently",
      all(p[-1].stage_kind == "EXIT" for p in sim.paths))

# A nine-bit fan-out that crosses 256, which the authored content never does.
wide = project_v6.WaveDefinition(id="wide", count=4, interval=5, start_x=200,
                                 start_y=30, x_step=40, y_step=0, colour=1,
                                 heading=0, movement_program="sweep")
check("the fan-out carries into the ninth bit of X",
      [ms.member_start(wide, m)[0] | (ms.member_start(wide, m)[1] << 8)
       for m in range(4)] == [200, 240, 280, 320])
narrow = project_v6.WaveDefinition(id="narrow", count=3, interval=5,
                                   start_x=20, start_y=30, x_step=-30,
                                   y_step=0, colour=1, heading=0,
                                   movement_program="sweep")
check("...and borrows out of it going the other way",
      [ms.member_start(narrow, m)[0] for m in range(3)] == [20, 246, 216],
      str([ms.member_start(narrow, m) for m in range(3)]))


# =======================================================================
# 9. lifetime and the despawn rules
# =======================================================================
for wid in ("sweep", "s", "linger", "loop"):
    sim = ms.simulate_wave(proj, waves[wid])
    check(f"every member of {wid!r} reaches a despawn edge", sim.all_exited,
          f"{sim.frame_count} frames")
    check(f"...and {wid!r} is visible inside the aperture at some point",
          any(s.visible for p in sim.paths for s in p))

t = fly(prog(S("STRAIGHT", frames=200, vx=0, vy=6), EXIT), y=200, frames=100)
gone = next(i for i, s in enumerate(t) if s.y >= ms.ENEMY_CLEAR_Y)
check("the bottom despawn line is 248 and needs no direction test",
      t[gone].y == 248, f"frame {gone}, y {t[gone].y}")

# THE TOP RULE ASKS THE DIRECTION, and that is what lets a wave fly in from
# above instead of being freed at birth. `linger` spawns at y=30, which is
# above ENEMY_CLEAR_Y_TOP (35), and descends through it.
def _obj(x=100, hi=0, y=100, vx=0, vy=0):
    o = ms._Obj()
    o.log_x, o.log_x_hi, o.log_y, o.vx, o.vy = x, hi, y, vx, vy
    return o


sim = ms.simulate_wave(proj, waves["linger"])
check("a wave spawns ABOVE the aperture and is not freed at birth",
      sim.paths[0][0].y < ms.ENEMY_CLEAR_Y_TOP and sim.paths[0][1].active,
      f"y {sim.paths[0][0].y}")
check("an enemy above the aperture but descending is NOT despawned",
      not ms._despawned(_obj(y=10, vy=6)))
check("...and one above it still climbing IS", ms._despawned(_obj(y=10, vy=-6)))
check("...and one parked there with no vertical velocity is not",
      not ms._despawned(_obj(y=10, vy=0)))


check("the left rule frees an object only while it is still going left",
      ms._despawned(_obj(x=2, vx=-4)) and not ms._despawned(_obj(x=2, vx=4)))
check("the right rule frees an object only while it is still going right",
      ms._despawned(_obj(x=100, hi=1, vx=4))
      and not ms._despawned(_obj(x=100, hi=1, vx=-4)))
check("...and a sprite parked behind the right border is NOT gone",
      not ms._despawned(_obj(x=100, hi=1, vx=0)))


# =======================================================================
# 10. determinism
# =======================================================================
a = ms.simulate_wave(proj, waves["loop"])
b = ms.simulate_wave(proj, waves["loop"])
check("simulating the same wave twice gives identical frames",
      [tuple(f) for f in a.frames] == [tuple(f) for f in b.frames])
check("...and identical paths", a.paths == b.paths)


# =======================================================================
# 11. invalid input is refused, never guessed
# =======================================================================
def refuses(label, fn, fragment):
    try:
        fn()
    except ms.SimulationError as exc:
        check(label, fragment in str(exc), str(exc)[:70])
    else:
        check(label, False, "no SimulationError raised")


bad = project_v6.WaveDefinition(id="bad", count=2, interval=10, start_x=10,
                                start_y=10, x_step=0, y_step=0, colour=1,
                                heading=0, movement_program="nope")
refuses("a wave naming a movement program that does not exist is refused",
        lambda: ms.simulate_wave(proj, bad), "does not exist")

bad2 = project_v6.WaveDefinition(id="b2", count=0, interval=10, start_x=10,
                                 start_y=10, x_step=0, y_step=0, colour=1,
                                 heading=0, movement_program="sweep")
refuses("a wave that sends no enemies is refused",
        lambda: ms.simulate_wave(proj, bad2), "sends no enemies")

bad3 = project_v6.WaveDefinition(id="b3", count=2, interval=0, start_x=10,
                                 start_y=10, x_step=0, y_step=0, colour=1,
                                 heading=0, movement_program="sweep")
refuses("an interval of zero is refused",
        lambda: ms.simulate_wave(proj, bad3), "interval of 0")

bad4 = project_v6.WaveDefinition(id="b4", count=1, interval=5, start_x=10,
                                 start_y=10, x_step=0, y_step=0, colour=1,
                                 heading=99, movement_program="sweep")
refuses("a launch heading outside 0..63 is refused",
        lambda: ms.simulate_wave(proj, bad4), "not a heading")


class _P:
    def __init__(self, stages):
        self.movement_programs = [project_v6.MovementProgram(
            id="p", stages=stages)]
        self.wave_definitions = []
        self.triggers = []


W = project_v6.WaveDefinition(id="w", count=1, interval=5, start_x=10,
                              start_y=10, x_step=0, y_step=0, colour=1,
                              heading=0, movement_program="p")
refuses("a program that does not end in EXIT is refused",
        lambda: ms.simulate_wave(_P([S("STRAIGHT", frames=5, vx=1, vy=0)]), W),
        "does not end in EXIT")
refuses("a stage after EXIT is refused",
        lambda: ms.simulate_wave(_P([EXIT, S("STRAIGHT", frames=5, vx=1, vy=0),
                                     EXIT]), W),
        "terminal")
refuses("a zero-length stage is refused",
        lambda: ms.simulate_wave(_P([S("STRAIGHT", frames=0, vx=1, vy=0), EXIT]),
                                 W),
        "0 frames")
refuses("an arc of zero steps is refused",
        lambda: ms.simulate_wave(_P([S("ARC", steps=0, frames_per_step=4,
                                       entry_heading=0), EXIT]), W),
        "0 steps")
refuses("an arc with no frames per step is refused",
        lambda: ms.simulate_wave(_P([S("ARC", steps=4, frames_per_step=0,
                                       entry_heading=0), EXIT]), W),
        "0 frames per step")
refuses("an arc entry heading outside 0..63 is refused",
        lambda: ms.simulate_wave(_P([S("ARC", steps=4, frames_per_step=4,
                                       entry_heading=200), EXIT]), W),
        "neither a heading")
refuses("an empty program is refused",
        lambda: ms.simulate_wave(_P([]), W), "no stages")


# =======================================================================
# 12. trigger resolution, and the Dropper refusal
# =======================================================================
ring = [i for i, t in enumerate(proj.triggers) if t.species == "RING"]
drop = [i for i, t in enumerate(proj.triggers) if t.species == "DROPPER"]
# ONE OF EACH IS WHAT THIS SECTION NEEDS. It used to require exactly two of
# each, which is a fact about how Level 1 happened to be authored rather than
# anything the simulator depends on.
check("the canonical level has both RING and DROPPER triggers",
      len(ring) >= 1 and len(drop) >= 1,
      f"{len(ring)} RING, {len(drop)} DROPPER")
sim = ms.simulate_trigger(proj, ring[0])
check("a RING trigger resolves through its wave to its movement program",
      sim.wave_id == proj.triggers[ring[0]].wave_definition
      and sim.program_id == waves[sim.wave_id].movement_program,
      f"{sim.wave_id} -> {sim.program_id}")
refuses("a DROPPER trigger is REFUSED rather than drawn as an ordinary wave",
        lambda: ms.simulate_trigger(proj, drop[0]), "not previewed")
refuses("...and says why", lambda: ms.simulate_trigger(proj, drop[0]),
        "taken off its wave's authored path")
refuses("no trigger selected is refused cleanly",
        lambda: ms.simulate_trigger(proj, 99), "no trigger selected")


# =======================================================================
# 13. previewing a bare movement program
# =======================================================================
p = ms.preview_program(proj, progs["loop"], heading=8, start=(70, 30))
check("a movement program can be previewed with no wave around it",
      p.count == 1 and p.program_id == "loop")
check("...and it is the same interpreter, so it matches the wave's member 0",
      [(s.x, s.y) for s in p.paths[0]]
      == [(s.x, s.y) for s in ms.simulate_wave(proj, waves["loop"]).paths[0]])


print()
if FAIL:
    print(f"{len(FAIL)} FAILURE(S):")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {len(PASS)} movement-simulation checks passed.")
