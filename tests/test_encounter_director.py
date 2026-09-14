#!/usr/bin/env python3
"""Encounter Director v1 — compact production-loop regression.

Encounter Director v1 has been visually qualified in VICE (two player sprite
layers, seven enemies, an enemy projectile, two background turrets, no
skips/hitches/raster instability). The exhaustive implementation-time
qualification harness that proved that is retired; this file is the small
permanent regression that stays behind to guard the feature going forward.

What this proves, watching the REAL production loop the whole time:
* an authored trigger starts a wave;
* a second wave instance runs concurrently with the first;
* enemies from both wave definitions are on screen together;
* at least one enemy progresses through several distinct phases of the
  curved (arc) movement primitive;
* an enemy despawns and returns its slot through the ordinary pool;
* the production health counters stay clean throughout.

Nothing here calls waveTick, wmTick or waveSpawnMember directly, and nothing
pokes wave or movement state to stage a scene -- the turret-firing slice's
false-GREEN (sixteen checks that all called the tick routine directly, over
code that could not fire a shot in a real game) is why. Every step goes
through harness.step_n, which verifies the frame counter actually advanced
instead of trusting a monitor prompt echo, for the same reason.

Sampling stops as soon as every behaviour above has been witnessed, rather
than always walking a fixed number of frames -- see MAX_FRAMES below.

One VICE launch.
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
WM_ARC, WM_ARC_MIRROR = 1, 2
ARC_PHASES_WANTED = 4      # "several", not all 16 -- enough to prove the
                           # primitive is actually running, not proof of the
                           # authored table (that was implementation-time work)
BOTH_ACTIVE_STREAK = 5     # a real overlap window, not one flickering frame

# A full authored cycle is 24+5+30+5 = 64 coarse rows at one row per eight
# frames, ~512 frames. This is slack for whichever phase of the cycle we
# happen to join at, not a target frame count -- the loop below exits the
# moment every behaviour has been observed, usually well before this.
MAX_FRAMES = 650


def check_layout():
    """The reads below assume two field pairs are laid out contiguously by
    the assembler (consecutive .fills in one *= block). That is checked, not
    trusted, so a future reordering fails loudly instead of quietly reading
    one field's bytes as another's."""
    check("wvActive/wvDef are contiguous, as this file's bulk read assumes",
          sym["wvDef"] == sym["wvActive"] + WAVE_SLOTS,
          f"wvActive={sym['wvActive']:04x} wvDef={sym['wvDef']:04x}")
    check("wmMode/wmNext/wmPhase are contiguous, as this file's bulk read "
          "assumes",
          sym["wmNext"] == sym["wmMode"] + MAX_OBJECTS
          and sym["wmPhase"] == sym["wmMode"] + 2 * MAX_OBJECTS,
          f"wmMode={sym['wmMode']:04x} wmNext={sym['wmNext']:04x} "
          f"wmPhase={sym['wmPhase']:04x}")


def sample(mon):
    """The few state bytes needed to judge one frame: wave active+def,
    movement mode+phase, per-object colour and type. Four small monitor
    reads, no more."""
    wave = rd(mon, sym["wvActive"], 2 * WAVE_SLOTS)
    move = rd(mon, sym["wmMode"], 3 * MAX_OBJECTS)
    col = rd(mon, sym["wmBaseCol"], MAX_OBJECTS)
    typ = rd(mon, sym["objType"], MAX_OBJECTS)
    active, wdef = wave[:WAVE_SLOTS], wave[WAVE_SLOTS:]
    mode, phase = move[0:MAX_OBJECTS], move[2 * MAX_OBJECTS:3 * MAX_OBJECTS]
    return active, wdef, mode, phase, col, typ


def main():
    print("=== encounter director v1 (slim) ===")
    v = None
    try:
        v = Vice(6661, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        check_layout()

        # --- boot state: cheap, permanent production safeguards ------------
        check("the pool starts within its bounds",
              rd1(mon, sym["logCount"]) <= MAX_OBJECTS)
        check("no trigger has been dropped for want of a free instance",
              rd1(mon, sym["wvDropped"]) == 0)
        check("the pool has never refused an allocation it was owed",
              rd1(mon, sym["objAllocFail"]) == 0)
        check("no slot has ever been double-freed",
              rd1(mon, sym["objDoubleFree"]) == 0)

        # --- watch the real production loop until every required behaviour -
        # --- has been witnessed, then stop ----------------------------------
        bp = set_bp(mon, sym["gameFrame"])

        any_start = False
        both_streak = 0
        both_confirmed = False
        coexist_confirmed = False
        despawn_confirmed = False
        arc_best = 0
        arc_runs = {}       # slot -> {"col": c, "phases": [seen, in order]}
        prev_active = None
        prev_type = None
        seen_frames = 0

        for _ in range(MAX_FRAMES):
            active, wdef, mode, phase, col, typ = step_n(
                mon, sym["frameCounter"], 1, lambda: sample(mon))[0]
            seen_frames += 1

            if any(t not in (TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET) for t in typ):
                check("every active slot holds a known production type",
                      False, f"{typ}")
                break

            if prev_active is not None and sum(active) > sum(prev_active):
                any_start = True

            if sum(active) == WAVE_SLOTS:
                both_streak += 1
                if both_streak >= BOTH_ACTIVE_STREAK:
                    both_confirmed = True
                if wdef[0] != wdef[1]:
                    cols = {col[i] for i in range(MAX_OBJECTS)
                            if typ[i] == TYPE_ENEMY}
                    if len(cols) >= 2:
                        coexist_confirmed = True
            else:
                both_streak = 0

            for i in range(MAX_OBJECTS):
                inarc = typ[i] == TYPE_ENEMY and mode[i] in (WM_ARC, WM_ARC_MIRROR)
                if not inarc:
                    arc_runs.pop(i, None)
                    continue
                run = arc_runs.get(i)
                # A run breaks on slot reuse (a new occupant, seen as a colour
                # change or the phase going backwards), not merely on the
                # phase repeating -- objectAlloc reissues the lowest free
                # slot, so a despawn is very often followed by a fresh arc in
                # the very same slot on the next frame.
                if run and run["col"] == col[i] and phase[i] >= run["phases"][-1]:
                    if phase[i] != run["phases"][-1]:
                        run["phases"].append(phase[i])
                else:
                    run = {"col": col[i], "phases": [phase[i]]}
                    arc_runs[i] = run
                arc_best = max(arc_best, len(set(run["phases"])))

            if prev_type is not None:
                for i in range(MAX_OBJECTS):
                    if prev_type[i] == TYPE_ENEMY and typ[i] == TYPE_NONE:
                        despawn_confirmed = True

            prev_active, prev_type = active, typ

            if (any_start and both_confirmed and coexist_confirmed
                    and arc_best >= ARC_PHASES_WANTED and despawn_confirmed):
                break

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        check("an authored trigger started a wave during the run", any_start)
        check("two wave instances were active concurrently for a real span",
              both_confirmed, f"longest streak {both_streak}, "
              f"{seen_frames} frames watched")
        check("enemies from two different wave definitions were on screen "
              "together", coexist_confirmed)
        check("at least one enemy progressed through several distinct "
              "phases of the curved primitive",
              arc_best >= ARC_PHASES_WANTED, f"best run {arc_best} phases")
        check("an enemy despawned and returned its pool slot", despawn_confirmed)

        # --- the engine is unharmed ------------------------------------------
        for name in ("gameOverrun", "publishSkip", "schedBuildDefer",
                     "scrollLate", "edgeLate"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero with the director running", got == 0, str(got))
        check("no trigger was dropped for want of an instance over the run",
              rd1(mon, sym["wvDropped"]) == 0)
        check("no slot was double-freed over the run",
              rd1(mon, sym["objDoubleFree"]) == 0)
        check("the pool never refused an allocation it was owed over the run",
              rd1(mon, sym["objAllocFail"]) == 0)
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
