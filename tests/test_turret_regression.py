#!/usr/bin/env python3
"""Turret firing regression -- the compact proof for the bug that cost hours.

Root cause (see the git history at/around the `legacy-tests-retired` tag,
commit "Complete turret firing and player damage" and its corrective follow-
up): turretWorldTick blanked EVERY turret's `turretVisible` flag at each
coarse scroll step, as a cheap reject-path optimisation. turretAimTick arms
the per-turret fire timer on the turretVisible 0->1 TRANSITION. So a turret
that never left the aperture still had its clock re-armed every eight frames,
and a hundred-frame firing interval never reached zero. No turret could ever
fire, in any real game, ever -- while sixteen firing checks that called
turretFireTick directly (never advancing a frame, so the coarse step this
depends on never happened) reported green.

This file exists so that mistake cannot silently return. It uses ONLY the
real production loop: no poked visibility, no poked timer, no hijacked PC for
the parts that matter. See constraint #4 -- this is exactly the class of bug a
direct-routine-call test cannot see.

What this proves
-----------------
* a turret that stays continuously visible across a real coarse scroll step
  has its fire timer fall by exactly one per frame -- the timer NEVER re-arms
  from a non-zero count (a reload FROM ZERO is the turret firing or being
  refused, which is the correct behaviour and the only permitted reset);
* the real game launches at least one hostile projectile with nothing poked;
* the projectile cap is honoured throughout.

What this does NOT re-prove
-----------------------------
The firing constants, aim quantisation, muzzle offset, hitbox geometry or
player-damage semantics -- those were exhaustively checked once (see the
`legacy-tests-retired` tag's tests/test_turret_firing.py) and are stable,
recovered-from-the-original-game values that do not need re-deriving on every
run. If they ever need re-verifying against the archive, that file is still
there in git history.

One VICE launch.
"""
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import PRG, SYM, symbols, Vice, rd, rd1, set_bp, free_run, check, report

sym = symbols(SYM)

TURRET_TOTAL = 8                # src/level1/stage_turrets.asm
TURRET_FIRE_INTERVAL = 100      # src/turrets.asm
EBULLET_MAX = 3                 # src/ebullet.asm


def main():
    print("=== turret firing regression ===")
    v = None
    try:
        v = Vice(6652, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")

        # --- seek a turret that has JUST arrived --------------------------
        # A turret whose timer is still near the full interval was armed
        # recently and has most of its ~176 visible frames still ahead, which
        # is what gives the sample below room to cross a coarse step while
        # that turret stays visible throughout.
        fresh = None
        for _ in range(40):
            vis = rd(mon, sym["turretVisible"], TURRET_TOTAL)
            tmr = rd(mon, sym["turretFireTimer"], TURRET_TOTAL)
            cand = [i for i in range(TURRET_TOTAL)
                    if vis[i] and tmr[i] >= TURRET_FIRE_INTERVAL - 12]
            if cand:
                fresh = cand[0]
                break
            free_run(mon, sym["frameCounter"], 0.25)
            mon.cmd("delete")
        check("a freshly arrived turret was found to watch", fresh is not None)

        # --- sample every frame at a fixed point, carrying the frame number --
        # NO SLEEPS: a settle-time sampler was tried during the corrective
        # task and was unreliable (too short: every frame read visible=0;
        # too long: worked on one run and not the next). Carrying the frame
        # counter and keeping only genuinely consecutive samples is the
        # method tests/test_slice_b.py's steps() established, and it is
        # immune to monitor/host timing.
        bp = set_bp(mon, sym["turretFireTick"])
        raw = []
        for _ in range(60):
            mon.cmd("x")
            f = rd(mon, sym["frameCounter"], 2)
            raw.append((
                f[0] | (f[1] << 8),
                rd(mon, sym["scrollFine"], 1)[0],
                rd(mon, sym["turretVisible"], TURRET_TOTAL),
                rd(mon, sym["turretFireTimer"], TURRET_TOTAL),
            ))
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        uniq = [r for i, r in enumerate(raw) if i == 0 or r[0] != raw[i - 1][0]]
        segs, cur = [], uniq[:1]
        for a, c in zip(uniq, uniq[1:]):
            if ((c[0] - a[0]) & 0xffff) == 1:
                cur.append(c)
            else:
                segs.append(cur); cur = [c]
        segs.append(cur)
        segs = [[(r[1], r[2], r[3]) for r in g] for g in segs if len(g) >= 2]
        best = max(segs, key=len) if segs else []
        check("a long contiguous run of production frames was captured",
              len(best) >= 30,
              f"{len(best)} longest of {len(raw)} samples in {len(segs)} segments")

        steps = sum(1 for seg in segs for a, b in zip(seg, seg[1:])
                    if b[0] < a[0])
        check("the sample window spans at least one real coarse scroll step",
              steps >= 1, f"{steps} steps across {len(segs)} segments")

        # --- THE ASSERTION: no turret's fire timer ever re-arms early ------
        # For every maximal run of frames in which a turret was continuously
        # visible, the timer must fall by exactly one per frame. The ONLY
        # permitted reset is from zero (the turret fired, or was refused, and
        # its interval restarted) -- that is the recovered rule. A reload
        # from a NON-ZERO count is exactly the regression this file exists
        # to catch.
        worst = None
        checked_runs = 0
        for t in range(TURRET_TOTAL):
            for seg in segs:
                run = []
                for f in seg + [None]:
                    if f is not None and f[1][t]:
                        run.append(f)
                        continue
                    if len(run) >= 10:
                        checked_runs += 1
                        for a, b in zip(run, run[1:]):
                            want = (TURRET_FIRE_INTERVAL if a[2][t] == 0
                                    else a[2][t] - 1)
                            if b[2][t] != want:
                                worst = (t, a[0], a[2][t], b[0], b[2][t])
                                break
                    run = []
        check("at least one turret stayed visible long enough to judge",
              checked_runs >= 1, f"{checked_runs} qualifying runs")
        check("a continuously visible turret's fire timer NEVER re-arms "
              "early -- this is the exact production regression",
              worst is None,
              "" if worst is None else
              f"turret {worst[0]}: fine {worst[1]} timer {worst[2]} -> "
              f"fine {worst[3]} timer {worst[4]}")

        # --- the real game fires, with nothing poked ------------------------
        # By now at least one turret's timer has been observed close to
        # expiry; a short additional free-run is enough to let it reach zero.
        f0 = rd1(mon, sym["ebFired"])
        cap_ok = True
        for _ in range(20):
            free_run(mon, sym["frameCounter"], 1)
            mon.cmd("delete")
            if rd1(mon, sym["ebCount"]) > EBULLET_MAX:
                cap_ok = False
            if rd1(mon, sym["ebFired"]) != f0:
                break
        f1 = rd1(mon, sym["ebFired"])
        check("the real game launches a hostile projectile, nothing poked",
              f1 != f0, f"ebFired {f0} -> {f1}")
        check("the projectile cap was honoured throughout", cap_ok)
    finally:
        if v: v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
