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
* two DIFFERENT authored patterns are in flight at once;
* the production health counters stay clean.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import PRG, SYM, symbols, Vice, rd, rd1, set_bp, free_run, step_n, check, report

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

# Two authored cycles plus slack. The cycle is ~488 frames and every pattern
# appears once in it; the loop below stops as soon as all of the above has been
# seen, which in practice is well inside one.
MAX_FRAMES = 1300


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
        v = Vice(6662, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        check_layout()
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
                    and both_diff > 0 and len(modes_seen) == 5):
                break

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        print(f"  .... watched {seen_frames} production frames")
        check("every movement primitive ran, including the new linger",
              len(modes_seen) == 5,
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
        check("two DIFFERENT authored patterns were in flight at once",
              both_diff > 0, f"{both_diff} frames")

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
