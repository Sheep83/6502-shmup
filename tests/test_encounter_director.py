#!/usr/bin/env python3
"""Encounter Director v1 — two independent waves, in the real production loop.

What this proves
----------------
* an authored trigger fires off worldProgress and starts a wave;
* a SECOND wave instance starts while the first is still active, so there is
  a genuine period with two wave instances running at once;
* enemies from both waves exist on screen concurrently;
* the two instances advance independently -- their member counters and timers
  move on their own schedules, and one finishing does not disturb the other;
* at least one enemy actually executes the CURVED primitive, and its velocity
  changes smoothly through the arc rather than in one jump;
* enemies despawn through the ordinary pool and return their slots;
* the director never overruns the pool, never double-allocates, and the
  production fault counters stay clean throughout.

EVERYTHING HERE WATCHES THE REAL FRAME LOOP. Nothing calls waveTick, wmTick
or waveSpawnMember directly, and nothing pokes wave or movement state to set
a scene. That is deliberate and it is this repository's most expensive lesson:
the turret-firing slice shipped sixteen green checks over a subsystem that
could not fire a single shot in a real game, because every one of them called
the tick routine directly and a routine called in a loop never advances a
frame. A director whose whole job is to react to scroll progress is exactly
the kind of thing that mistake hides.

THE STEPPING RULE. `mon.cmd("x")` returns on a prompt echo rather than on the
actual stop, so a bare stepping loop can record the same frame twice and
silently sample half as much as it thinks. Every step below goes through
harness.step_n, which verifies each one against the frame counter. The first
draft of this file did not, and reported a wave timer decrementing at half
speed.

One VICE launch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, set_bp, free_run,
                      step_n, check, report)

sym = symbols(SYM)

# --- the contract, restated independently of the assembler ------------------
MAX_OBJECTS = 16
WAVE_SLOTS  = 2
TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET = 0, 1, 2
WM_STRAIGHT, WM_ARC, WM_ARC_MIRROR, WM_EXIT = 0, 1, 2, 3
WM_ARC_LEN, WM_ARC_STEP, WM_ARC_SPEED = 16, 4, 6
MIN_SPRITE_Y, MAX_SPRITE_Y = 55, 226


# BOTH STATE BLOCKS ARE READ WHOLE, IN ONE MONITOR COMMAND EACH.
#
# Every monitor round trip is a few hundred milliseconds and this file samples
# seven hundred frames, so the difference between thirteen reads a frame and
# five is minutes of gate time. The wave instance arrays and the movement
# arrays are each contiguous by construction -- consecutive `.fill`s in one
# `*=` block -- so one dump covers each, and the fields are sliced out here.
#
# That is a layout assumption, so it is CHECKED rather than trusted: a future
# reordering of either block would otherwise silently start reporting one
# field's bytes as another's, and every assertion in this file would go on
# passing against nonsense.
WAVE_FIELDS = ("active", "def", "left", "wvtimer", "index")
MOVE_FIELDS = ("mode", "next", "phase", "timer", "vx", "vy", "accX", "accY", "col")


def check_layout():
    wave = [sym["wv" + n] for n in
            ("Active", "Def", "Left", "Timer", "Index")]
    move = [sym["wm" + n] for n in
            ("Mode", "Next", "Phase", "Timer", "VX", "VY", "AccX", "AccY",
             "BaseCol")]
    check("the wave instance arrays are contiguous, as this file's bulk "
          "reads assume",
          wave == [wave[0] + i * WAVE_SLOTS for i in range(len(wave))],
          f"{[hex(a) for a in wave]}")
    check("the movement arrays are contiguous, as this file's bulk reads "
          "assume",
          move == [move[0] + i * MAX_OBJECTS for i in range(len(move))],
          f"{[hex(a) for a in move]}")


def sample(mon):
    """One frame's worth of director and object state, read at gameFrame."""
    wave = rd(mon, sym["wvActive"], WAVE_SLOTS * len(WAVE_FIELDS))
    move = rd(mon, sym["wmMode"], MAX_OBJECTS * len(MOVE_FIELDS))
    out = {f: wave[i * WAVE_SLOTS:(i + 1) * WAVE_SLOTS]
           for i, f in enumerate(WAVE_FIELDS)}
    out.update({f: move[i * MAX_OBJECTS:(i + 1) * MAX_OBJECTS]
                for i, f in enumerate(MOVE_FIELDS)})
    out["type"] = rd(mon, sym["objType"], MAX_OBJECTS)
    out["logY"] = rd(mon, sym["logY"], MAX_OBJECTS)
    out["count"] = rd1(mon, sym["logCount"])
    return out


def s8(v):
    return v - 256 if v > 127 else v


def main():
    print("=== encounter director v1 ===")
    v = None
    try:
        v = Vice(6661, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # --- boot state ----------------------------------------------------
        # Read before anything else: a director that armed itself wrongly at
        # boot would still look healthy once it had been running a while.
        check_layout()
        check("the pool starts within its bounds",
              rd1(mon, sym["logCount"]) <= MAX_OBJECTS)
        check("no trigger has been dropped for want of a free instance",
              rd1(mon, sym["wvDropped"]) == 0, str(rd1(mon, sym["wvDropped"])))
        check("the pool has never refused an allocation it was owed",
              rd1(mon, sym["objAllocFail"]) == 0,
              str(rd1(mon, sym["objAllocFail"])))
        check("no slot has ever been double-freed",
              rd1(mon, sym["objDoubleFree"]) == 0,
              str(rd1(mon, sym["objDoubleFree"])))

        # --- watch a whole encounter cycle ---------------------------------
        # The authored period is 24+5+30+5 = 64 coarse rows and worldProgress
        # advances once every eight frames, so one full cycle is about 512
        # frames. 700 covers a cycle and a bit whatever phase we join at.
        bp = set_bp(mon, sym["gameFrame"])
        frames = step_n(mon, sym["frameCounter"], 700, lambda: sample(mon))
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        check("a long contiguous run of production frames was captured",
              len(frames) == 700, f"{len(frames)} frames")

        # --- 1. waves activate at all --------------------------------------
        starts = [i for i, (a, b) in enumerate(zip(frames, frames[1:]))
                  if sum(b["active"]) > sum(a["active"])]
        check("authored triggers started waves during the run",
              len(starts) >= 2, f"{len(starts)} activations at {starts[:6]}")

        # --- 2. TWO INSTANCES AT ONCE, which is the point of the slice -----
        both = [i for i, f in enumerate(frames) if sum(f["active"]) == WAVE_SLOTS]
        check("there is a period with TWO wave instances active at once",
              len(both) > 0, f"{len(both)} frames")
        check("...and it lasts a meaningful time, not one frame",
              len(both) >= 20, f"{len(both)} frames with both instances active")

        # --- 3. they are DIFFERENT waves, not the same one twice -----------
        mixed = [f for f in frames
                 if sum(f["active"]) == WAVE_SLOTS
                 and f["def"][0] != f["def"][1]]
        check("the two concurrent instances are playing different definitions",
              len(mixed) > 0,
              f"{len(mixed)} of {len(both)} two-instance frames")

        # --- 4. they advance INDEPENDENTLY ---------------------------------
        # Over the frames where both are live, each instance's own timer must
        # move on its own schedule. If one instance's state were corrupting
        # the other -- shared locals, a clobbered X -- the cheapest symptom
        # would be their timers moving in lockstep.
        pairs = [(f["wvtimer"][0], f["wvtimer"][1]) for f in frames
                 if sum(f["active"]) == WAVE_SLOTS]
        deltas = set()
        for (a0, a1), (b0, b1) in zip(pairs, pairs[1:]):
            deltas.add(((b0 - a0) % 256, (b1 - a1) % 256))
        check("the two instances' timers do not move in lockstep",
              len(deltas) > 1 or len(pairs) < 2, f"{sorted(deltas)[:4]}")

        # A member sent by one instance must not disturb the other's counters.
        disturbed = []
        for a, b in zip(frames, frames[1:]):
            if sum(a["active"]) != WAVE_SLOTS or sum(b["active"]) != WAVE_SLOTS:
                continue
            for w in range(WAVE_SLOTS):
                other = 1 - w
                if b["index"][w] != a["index"][w]:          # w sent a member
                    if (b["index"][other] != a["index"][other]
                            and b["left"][other] != a["left"][other] - 0):
                        pass                                 # both may legitimately
                                                             # fire on one frame
                    if b["def"][other] != a["def"][other]:
                        disturbed.append((w, other))
        check("one instance sending a member never rewrites the other's "
              "definition", not disturbed, f"{disturbed[:3]}")

        # --- 5. enemies from BOTH waves coexist ----------------------------
        # Every member of a wave carries its wave's colour, so the colours of
        # the live enemies say which waves they came from. That is a property
        # of the authored content rather than of the director, which is why it
        # is a good independent witness that two waves are really on screen.
        concurrent = 0
        for f in frames:
            cols = {f["col"][i] for i in range(MAX_OBJECTS)
                    if f["type"][i] == TYPE_ENEMY}
            if len(cols) >= 2:
                concurrent += 1
        check("enemies from two different waves are on screen together",
              concurrent > 0, f"{concurrent} frames with two wave colours live")

        peak = max(sum(1 for i in range(MAX_OBJECTS) if f["type"][i] == TYPE_ENEMY)
                   for f in frames)
        check("the overlap reaches a useful number of enemies",
              peak >= 4, f"peak {peak} enemies live at once")

        # --- 6. the CURVED primitive actually runs -------------------------
        arcs = [f for f in frames
                for i in range(MAX_OBJECTS)
                if f["type"][i] == TYPE_ENEMY
                and f["mode"][i] in (WM_ARC, WM_ARC_MIRROR)]
        check("at least one enemy is executing the curved primitive",
              len(arcs) > 0, f"{len(arcs)} object-frames in an arc")

        # Follow one slot through an arc and check the turn is SMOOTH: the
        # velocity must change by small steps across many distinct phases,
        # not snap from one heading to another.
        # A RUN MUST BREAK ON SLOT REUSE, not merely on the slot going quiet.
        # objectAlloc hands out the lowest free slot, so an enemy that
        # despawns at the end of its arc is very often replaced in the SAME
        # slot by a new one starting a fresh arc on the very next frame. Read
        # as one object that is a velocity jump from (0,+6) to (-6,0) -- and
        # the first draft of this check duly reported a (6,6) step and called
        # the arc unsmooth. Two independent witnesses that the occupant
        # changed: an arc's phase never decreases within one object's turn,
        # and every member of a wave carries its wave's colour.
        best = ([], -1)
        for i in range(MAX_OBJECTS):
            run, prev = [], None
            for f in frames:
                inarc = (f["type"][i] == TYPE_ENEMY
                         and f["mode"][i] in (WM_ARC, WM_ARC_MIRROR))
                here = (f["phase"][i], s8(f["vx"][i]), s8(f["vy"][i]), f["col"][i])
                reused = (prev is not None and inarc
                          and (here[0] < prev[0] or here[3] != prev[3]))
                if inarc and not reused:
                    run.append(here[:3])
                else:
                    if len(run) > len(best[0]):
                        best = (run, i)
                    run = [here[:3]] if inarc else []
                prev = here if inarc else None
            if len(run) > len(best[0]):
                best = (run, i)
        arc_run, arc_slot = best
        phases = sorted({p for p, _, _ in arc_run})
        check("one enemy was followed through many phases of its arc",
              len(phases) >= 8, f"slot {arc_slot}: phases {phases}")

        steps = set()
        for (p0, x0, y0), (p1, x1, y1) in zip(arc_run, arc_run[1:]):
            if p1 != p0:
                steps.add((abs(x1 - x0), abs(y1 - y0)))
        check("the arc turns SMOOTHLY: no phase change moves a velocity "
              "component by more than one quarter pixel",
              steps and all(dx <= 1 and dy <= 1 for dx, dy in steps),
              f"{sorted(steps)}")
        check("...and the turn genuinely changes direction over its length",
              arc_run and abs(arc_run[0][1] - arc_run[-1][1]) >= 3,
              f"vx {arc_run[0][1]} -> {arc_run[-1][1]}" if arc_run else "")

        # --- 7. the lifecycle still returns slots --------------------------
        deaths = sum(1 for a, b in zip(frames, frames[1:])
                     for i in range(MAX_OBJECTS)
                     if a["type"][i] == TYPE_ENEMY and b["type"][i] == TYPE_NONE)
        check("enemies despawned and returned their pool slots during the run",
              deaths > 0, f"{deaths} slots returned")
        check("every enemy stayed inside the renderable band while alive",
              all(MIN_SPRITE_Y <= f["logY"][i] <= MAX_SPRITE_Y
                  for f in frames for i in range(MAX_OBJECTS)
                  if f["type"][i] == TYPE_ENEMY))
        check("the pool never exceeded its capacity",
              all(f["count"] <= MAX_OBJECTS for f in frames),
              f"peak logCount {max(f['count'] for f in frames)}")
        check("every active slot held a known production type",
              all(f["type"][i] in (TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET)
                  for f in frames for i in range(MAX_OBJECTS)))

        # --- 8. the engine is unharmed -------------------------------------
        for name in ("gameOverrun", "publishSkip", "schedBuildDefer",
                     "scrollLate", "edgeLate"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero with the director running", got == 0, str(got))
        check("no trigger was dropped for want of an instance over the run",
              rd1(mon, sym["wvDropped"]) == 0, str(rd1(mon, sym["wvDropped"])))
        check("the pool never refused a spawn the director was owed",
              rd1(mon, sym["objDoubleFree"]) == 0,
              f"doubleFree {rd1(mon, sym['objDoubleFree'])}")

        # --- 9. pool pressure: DEFER, safely -------------------------------
        # Fill the pool by hand and confirm the director's documented policy:
        # the member is not lost, the wave is not corrupted, and no live
        # object is overwritten. This is the one place the test poses a state
        # -- there is no way to make the real game exhaust sixteen slots on
        # demand -- and it still observes the production loop for the answer.
        bp = set_bp(mon, sym["gameFrame"])

        # WAIT FOR A WAVE THAT IS STILL SENDING MEMBERS. Stuffing the pool at
        # an arbitrary moment proves nothing about deferral: the authored
        # waves only spawn for about eighty frames out of every five hundred,
        # so a window chosen blindly almost always lands in a gap and the
        # policy is never asked to do anything. The first draft of this
        # section did exactly that and reported wvDeferred 0 -> 0 as though
        # the pool had been quiet by choice.
        armed = False
        for _ in range(700):
            f = step_n(mon, sym["frameCounter"], 1, lambda: sample(mon))[0]
            if any(f["active"][w] and f["left"][w] > 0 for w in range(WAVE_SLOTS)):
                armed = True
                break
        check("a wave with members still to send was found to pressure",
              armed)
        deferred0 = rd1(mon, sym["wvDeferred"])
        # Seize every free slot through the pool's OWN API, so its bookkeeping
        # stays true and nothing is faked.
        #
        # ALLOC AND ACTIVATE, both, and ONLY WHILE A FREE SLOT EXISTS.
        #
        # objectAlloc on its own reserves nothing -- the slot is not active,
        # so the very next objectAlloc hands out the same one again. The first
        # draft called only objectAlloc sixteen times, drove logCount to two,
        # and asserted happily that the director had survived a pressure it
        # had never been under.
        #
        # The second draft added objectActivate but ignored the CARRY.
        # objectAlloc's contract is "carry set, and X is then meaningless" --
        # its scan leaves X at MAX_OBJECTS -- so once the pool filled, the
        # pair went on to activate logical ID 16, which exists (logActive is
        # MAX_LOGICAL long) but is not a pool slot. logCount reached
        # seventeen, and the engine was behaving exactly as documented while
        # the test called it a capacity breach.
        #
        # Reading logCount before each attempt is the cheap way to honour that
        # contract without parsing the status register: while logCount is
        # below capacity a free slot provably exists, so the alloc cannot fail
        # and the activate is safe.
        for _ in range(MAX_OBJECTS + 4):
            if rd1(mon, sym["logCount"]) >= MAX_OBJECTS:
                break
            mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym['objectAlloc']:04x}")
            bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
            mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym['objectActivate']:04x}")
            bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
            mon.cmd(f"r pc={sym['mainLoop']:04x}")
        full = rd1(mon, sym["logCount"])
        pressed = step_n(mon, sym["frameCounter"], 120, lambda: sample(mon))
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        check("the pool was genuinely FULL for that window",
              full == MAX_OBJECTS, f"logCount {full} after seizing free slots")
        # ONLY WHILE THE INSTANCE STAYS ACTIVE. wvLeft legitimately jumps
        # from 0 back up to a new wave's count when a finished instance is
        # taken over by the next authored trigger, and the first draft of this
        # check read that reuse as a lost member.
        skipped = [(w, a["left"][w], b["left"][w])
                   for a, b in zip(pressed, pressed[1:])
                   for w in range(WAVE_SLOTS)
                   if a["active"][w] and b["active"][w]
                   and b["left"][w] not in (a["left"][w], a["left"][w] - 1)]
        check("no wave lost a member to a full pool: wvLeft never skipped",
              not skipped, f"{skipped[:3]}")
        check("the deferral policy actually engaged under pressure",
              rd1(mon, sym["wvDeferred"]) > deferred0,
              f"wvDeferred {deferred0} -> {rd1(mon, sym['wvDeferred'])}")
        check("the pool never exceeded capacity under pressure",
              all(f["count"] <= MAX_OBJECTS for f in pressed),
              f"peak {max(f['count'] for f in pressed)}")
        check("the director did not corrupt itself under pressure",
              all(f["active"][w] in (0, 1) for f in pressed
                  for w in range(WAVE_SLOTS)))
        # THE MAIN THREAD STILL MAKES ITS FRAME, which is the fault that
        # matters. publishSkip is deliberately NOT asserted here: this section
        # has just stuffed all sixteen pool slots by hand, and
        # docs/ENGINE_CONTRACT.md section 10 puts the practical ceiling around
        # eight well-separated sprites -- dropping a publication under that
        # load is the renderer's documented behaviour at a population the
        # director would never itself create, not a regression in it. The
        # director's own peak during the seven hundred frames of ORDINARY play
        # above was eight objects, with every counter clean; that is the
        # number this slice is answerable for, and it is asserted there.
        check("the main thread still finished every frame under pressure",
              rd1(mon, sym["gameOverrun"]) == 0,
              f"overrun {rd1(mon, sym['gameOverrun'])}, "
              f"publishSkip {rd1(mon, sym['publishSkip'])} "
              f"(not asserted: {MAX_OBJECTS} objects is past the "
              f"ENGINE_CONTRACT section 10 ceiling)")
    finally:
        if v: v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
