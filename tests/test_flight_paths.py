#!/usr/bin/env python3
"""Encounter Director v1.1 — the composable movement vocabulary, in the real
production loop.

NOT PART OF `make test`, and that is the point. The permanent regression
(tests/test_encounter_director.py) proves the ARCHITECTURE -- that an enemy
walks an authored stage list at all -- in about twenty seconds, because it can
see that happen on whichever wave it lands in. Proving the VOCABULARY means
waiting for four specific patterns to come round on a ten-second authored
cycle, which is a minute of gate time to re-prove content that only changes
when somebody edits it deliberately. So it lives here, behind
`make test-flight-paths`, and the fast gate stays fast.

What this proves, watching the REAL frame loop the whole time -- nothing calls
wmTick, wmEnterStage or waveSpawnMember directly:

* enemies advance from one authored stage to the next;
* at least one enemy walks a THREE-stage path end to end;
* an arc and a MIRRORED arc run on the SAME enemy -- the S-turn is composed
  out of the two handed arcs rather than implemented as a curve of its own;
* an enemy HOLDS (WM_HOLD), and the hold ends by itself and hands on;
* repeated arc steps carry one enemy through most of a circle, which is the
  loop pattern and the thing a fixed quarter-turn arc could not express;
* enemies still despawn and return their pool slots;
* two DIFFERENT patterns are in flight at once;
* the production health counters stay clean.

THE PATTERNS ARE ARRANGED, NOT WAITED FOR -- which is the repair this file used
to describe and not perform. Its own note said so:

    "Every claim here is about an ENGINE capability [...] but it is measured by
    WATCHING AUTHORED LEVEL 1 and hoping the content exercises each primitive
    inside the window. That is coverage by luck. [...] The proper repair is to
    arrange each primitive deliberately."

Level 1 was then re-authored, four of its wave definitions stopped being
referenced by any trigger, and the luck ran out: HOLD and ARC_MIRROR never ran,
and four checks reported "0 of N" about an engine that was behaving perfectly.

So the schedule is now SYNTHETIC (tests/synth.py): one program that walks
STRAIGHT -> HOLD -> ARC -> ARC_MIRROR -> EXIT, and a second, different one
beside it, installed into the spare room the level package reserves. Package RAM
only; no authored file is touched. The frame loop is still the real one --
nothing calls wmTick, wmEnterStage or waveSpawnMember directly -- so what is
measured is unchanged; only the certainty that the case occurs is new.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import PRG, SYM, symbols, Vice, rd, rd1, set_bp, free_run, step_n, check, report
import campaign_data as CD                                       # noqa: E402
import synth                                                     # noqa: E402

sym = symbols(SYM)

MAX_OBJECTS = 16
WAVE_SLOTS = 2
TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET = 0, 1, 2
WM_STRAIGHT, WM_ARC, WM_ARC_MIRROR, WM_EXIT, WM_HOLD = 0, 1, 2, 3, 4
NAMES = {WM_STRAIGHT: "STRAIGHT", WM_ARC: "ARC", WM_ARC_MIRROR: "ARC_MIRROR",
         WM_EXIT: "EXIT", WM_HOLD: "HOLD"}

LOOP_HEADINGS_WANTED = 40   # of 64: comfortably more than the half circle a
                            # single quarter-turn primitive could ever reach
CHAIN_WANTED = 2            # two transitions = a three-stage path

# THE SYNTHETIC SPECIMEN. Five stages, so every primitive in the vocabulary runs
# on ONE enemy -- which is also what makes "the S-turn is composed" and "a hold
# ends and hands on" observable rather than hoped for.
#
# The velocities are small enough for the despawn guards at 1.00x (ENEMY_CLEAR_X_LEFT
# allows 4 px a frame, i.e. 16 quarter pixels) and the two arcs together turn
# through half a circle, ending pointing down-right so the EXIT leaves through
# the bottom and the slot comes back.
# THE TWO ROWS ARE CLOSE TOGETHER ON PURPOSE. "Two different patterns in flight
# at once" needs both wave instances live in the same frame, and one coarse row is
# eight displayed frames -- rows 8 and 16 were sixty-four frames apart and the
# first instance had finished before the second began, so the check read 0 frames.
SYN_ROW_A, SYN_ROW_B = 8, 12
SYN_COUNT, SYN_INTERVAL = 3, 20

# The window no longer has to wait for an authored cycle to come round: both
# synthetic rows are due within the first few coarse rows of the run.
MAX_FRAMES = 900


# ONE READ FOR THE WHOLE DIRECTOR, and it is worth the arithmetic. This file
# watches five hundred frames rather than the permanent regression's eighty,
# so a monitor round trip per frame is most of its runtime: four reads a frame
# took six and a half minutes and two takes half of that. The movement state
# and the wave state are neighbours by construction -- movement.asm's block
# starts at wmMode and is guarded to end before waves.asm's, which starts at
# wvActive -- so one dump spans both and every field is sliced out of it. That
# is a layout assumption, so check_layout() below CHECKS it rather than
# trusting it.
BLOCK = sym["wvDef"] + 2 * WAVE_SLOTS - sym["wmMode"]


def check_layout():
    for n, off in (("wmStage", 1), ("wmPhase", 2), ("wmBaseCol", 9)):
        check(f"{n} sits where this file's bulk read expects it",
              sym[n] == sym["wmMode"] + off * MAX_OBJECTS,
              f"{n}={sym[n]:04x} wmMode={sym['wmMode']:04x}")
    check("the wave state follows the movement state closely enough for one "
          "dump to cover both",
          sym["wvActive"] > sym["wmMode"] and BLOCK <= 256
          and sym["wvDef"] == sym["wvActive"] + WAVE_SLOTS,
          f"wmMode={sym['wmMode']:04x} wvActive={sym['wvActive']:04x} "
          f"span={BLOCK}")


def sample(mon):
    """One frame of everything this file judges, in two monitor reads."""
    b = rd(mon, sym["wmMode"], BLOCK)
    typ = rd(mon, sym["objType"], MAX_OBJECTS)

    def f(name, n=MAX_OBJECTS):
        o = sym[name] - sym["wmMode"]
        return b[o:o + n]

    return (f("wvActive", WAVE_SLOTS), f("wvDef", WAVE_SLOTS),
            f("wmMode"), f("wmStage"), f("wmPhase"), f("wmBaseCol"), typ)


def main():
    print("=== encounter director v1.1: composable flight paths ===")
    v = None
    try:
        # boot="exact" AND NO WARM-UP WARP. This file needs live ordinary
        # enemies in its sampling window, and since Wave Contract Stage 1 they
        # exist only around the four authored encounters at coarse rows 48, 52,
        # 90 and 126 -- Level 1 is deliberately quiet afterwards. The fast boot
        # arrives at row ~107 (measured 107..395) and the two-second warp that
        # used to follow is a further ~220 rows, so the window landed in the
        # quiet stretch and the enemies it asserts about did not exist.
        # It used to work by accident: waves repeated every 126 rows for ever.
        # From row 0 this file's own frame budget covers all four encounters.
        v = Vice(6662, PRG, warp=True, boot="exact")
        mon = v.mon
        mon.cmd("delete")

        check_layout()

        # ---- THE SYNTHETIC SCHEDULE ------------------------------------
        pkg = synth.Package(mon, sym)
        # THE FIRST ARC IS LONG ENOUGH TO BE A LOOP, AND TIGHT ENOUGH TO STAY
        # INSIDE THE APERTURE.
        #
        # The claim it serves is that repeated arc steps carry ONE enemy through
        # most of a circle -- something a fixed quarter-turn primitive could never
        # do -- so it has to sweep more than LOOP_HEADINGS_WANTED of the 64
        # headings. Two twelve-step arcs of opposite hand retraced each other and
        # reached 13, so the first arc was lengthened to 44 steps; at two frames
        # a step that is a 62-pixel circle, and the enemy wandered out of the
        # left edge and was despawned before it ever reached the MIRROR stage, so
        # "both handednesses on one enemy" read 0.
        #
        # ONE FRAME PER STEP halves the radius to about 15 pixels and halves the
        # time, so the whole five-stage path -- straight, hold, loop, counter-turn,
        # exit -- completes well inside the aperture and well inside the window.
        five = pkg.install_program([
            [synth.WM_STRAIGHT, 20, 4, 2],
            [synth.WM_HOLD, 20, 0, 1],
            [synth.WM_ARC, 44, 1, 8],
            [synth.WM_ARC_MIRROR, 12, 1, synth.WM_HEAD_CONT],
            [synth.WM_EXIT, 0, 0, 0],
        ])
        other = pkg.straight_then_exit(2, 5)        # a visibly different pattern
        def_a = pkg.install_definition(count=SYN_COUNT, interval=SYN_INTERVAL,
                                       start_x=90, start_y=40, x_step=30,
                                       y_step=0, heading=8, program=five)
        def_b = pkg.install_definition(count=SYN_COUNT, interval=SYN_INTERVAL,
                                       start_x=200, start_y=40, x_step=20,
                                       y_step=0, heading=16, program=other)
        pkg.write_trigger(0, row=SYN_ROW_A, definition=def_a,
                          species=synth.SLOT_ROW[0], fire=0, side=0, colour=1,
                          fire_mode=0, speed=CD.C.TRIG_SPEED_1X)
        pkg.write_trigger(1, row=SYN_ROW_B, definition=def_b,
                          species=synth.SLOT_ROW[0], fire=0, side=0, colour=7,
                          fire_mode=0, speed=CD.C.TRIG_SPEED_1X)
        pkg.set_trigger_count(2)
        pkg.open_the_approach()
        pkg.rewind_cursor()
        check("two synthetic patterns are installed, one walking every "
              "primitive in the vocabulary",
              rd1(mon, CD.TRIGN_ADDR) == 2
              and rd1(mon, sym["waveTrigDef"] + 0) != rd1(mon, sym["waveTrigDef"] + 1),
              f"definitions {def_a} (5 stages) and {def_b} (STRAIGHT+EXIT) at "
              f"rows {SYN_ROW_A} and {SYN_ROW_B}")

        bp = set_bp(mon, sym["gameFrame"])

        # Per live occupant (broken on slot reuse, which shows up as a colour
        # change or as the type going away), what it has done so far.
        live = {}           # slot -> dict(col, chain, modes, headings, mirror_then_arc)
        modes_seen = set()
        chain_best = 0
        head_best = 0
        s_compose = 0       # enemies that ran BOTH arc handednesses
        hold_ended = 0      # holds that advanced to a following stage
        despawns = 0
        both_diff = 0
        seen_frames = 0
        prev = None

        for _ in range(MAX_FRAMES):
            active, wdef, mode, stage, phase, col, typ = step_n(
                mon, sym["frameCounter"], 1, lambda: sample(mon))[0]
            seen_frames += 1

            if sum(active) == WAVE_SLOTS and wdef[0] != wdef[1]:
                both_diff += 1

            for i in range(MAX_OBJECTS):
                if typ[i] != TYPE_ENEMY:
                    live.pop(i, None)
                    continue
                o = live.get(i)
                if o is None or o["col"] != col[i]:
                    o = {"col": col[i], "chain": 0, "modes": set(),
                         "headings": set(), "arcs": []}
                    live[i] = o
                o["modes"].add(mode[i])
                modes_seen.add(mode[i])
                if mode[i] in (WM_ARC, WM_ARC_MIRROR):
                    o["headings"].add(phase[i])
                    head_best = max(head_best, len(o["headings"]))

                if prev is not None and prev[6][i] == TYPE_ENEMY and prev[5][i] == col[i]:
                    if stage[i] != prev[3][i]:
                        o["chain"] += 1
                        chain_best = max(chain_best, o["chain"])
                        # An arc handed on to its opposite: the S-turn's join.
                        if prev[2][i] in (WM_ARC, WM_ARC_MIRROR):
                            o["arcs"].append(prev[2][i])
                        if (WM_ARC in o["arcs"] and WM_ARC_MIRROR in o["arcs"]
                                and not o.get("sflagged")):
                            o["sflagged"] = True
                            s_compose += 1
                        # A hold that ended of its own accord and handed on.
                        if prev[2][i] == WM_HOLD and mode[i] != WM_HOLD:
                            hold_ended += 1
                elif prev is not None and prev[6][i] == TYPE_ENEMY:
                    pass

            if prev is not None:
                for i in range(MAX_OBJECTS):
                    if prev[6][i] == TYPE_ENEMY and typ[i] == TYPE_NONE:
                        despawns += 1
            prev = (active, wdef, mode, stage, phase, col, typ)

            if (chain_best >= CHAIN_WANTED and s_compose > 0 and hold_ended > 0
                    and head_best >= LOOP_HEADINGS_WANTED and despawns > 0
                    and both_diff > 0
                    and len(modes_seen) == CD.fmt("WM_MODES")):
                break

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        print(f"  .... watched {seen_frames} production frames")

        # ============================================================
        # WHAT THIS FILE CAN AND CANNOT TELL YOU -- read before believing a
        # failure below.
        #
        # Every claim here is about an ENGINE capability -- the movement
        # vocabulary -- but it is measured by WATCHING AUTHORED LEVEL 1 and
        # hoping the content exercises each primitive inside the window. That is
        # coverage by luck, and the audit classified it as such
        # (reports/test-suite-audit-and-purge.md).
        #
        # A failure below therefore has TWO possible meanings and the messages
        # are written to tell them apart:
        #
        #   "0 of N" / "best 0" ... the authored content never produced the case
        #                           in this window. The engine is not implicated.
        #   a WRONG value         ... the primitive ran and misbehaved. That is
        #                           an engine finding.
        #
        # The proper repair is to arrange each primitive deliberately -- poke a
        # movement program, run it, observe the headings -- so the test stops
        # depending on what Level 1 happens to contain. That is a real piece of
        # work against the wm* state machine and is NOT done here; lengthening
        # the window until probability makes it green would be worse than
        # leaving it honest. See the phase-2 report's remaining-limitations
        # section.
        # ============================================================
        check("every movement primitive ran, including the hold",
              len(modes_seen) == CD.fmt("WM_MODES"),
              " ".join(sorted(NAMES.get(m, str(m)) for m in modes_seen)))
        check("enemies advanced from one authored stage to the next, and one "
              "walked a three-stage path end to end",
              chain_best >= CHAIN_WANTED,
              f"best {chain_best} stage transitions on one enemy")
        check("an arc and a MIRRORED arc ran on the SAME enemy: the S-turn is "
              "composed, not a curve engine",
              s_compose > 0, f"{s_compose} enemies ran both handednesses")
        check("a linger ended by itself and handed on to the next stage",
              hold_ended > 0, f"{hold_ended} holds advanced")
        check("repeated arc steps carried one enemy through most of a circle, "
              "which a fixed quarter turn could not do",
              head_best >= LOOP_HEADINGS_WANTED,
              f"{head_best} of 64 distinct headings on one enemy")
        check("enemies still despawn and return their pool slots",
              despawns > 0, f"{despawns} slots returned")
        check("two DIFFERENT patterns were in flight at once",
              both_diff > 0, f"{both_diff} frames")

        for name in ("gameOverrun", "scrollLate", "edgeLate"):
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
