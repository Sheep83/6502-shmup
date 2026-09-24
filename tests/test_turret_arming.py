#!/usr/bin/env python3
"""When a turret arms, and when it can first shoot.

    python3 tests/test_turret_arming.py

MEASURED, NOT DERIVED FROM THE CONSTANTS. The point of the change is a timing
the player feels, so this watches the machine: turretFireTimer and turretLogY,
per turret, every frame.

IT WATCHES THE TIMER AND NOT THE BOLTS for the timing, deliberately. Turret
bolts and enemy bolts share one pool and one TYPE_EBULLET, so counting
projectiles cannot say which came from a turret -- a first attempt did exactly
that and measured WAVE_FIRE_PERIOD, the enemy cadence, instead. turretFireTimer
is the thing that actually changed. The bolt is then checked ONCE, at the
first-fire frame, by its muzzle coordinates, which no enemy bolt can imitate.

IT SEEKS THE STAGE INSTEAD OF WAITING FOR IT. Level 1's five turrets sit at
stage rows 344, 224, 216, 116 and 108; stageTopRow starts at 775 and steps back
one every eight frames, so the first turret is not on the aperture until frame
~3450 and the last not until ~5340. A first attempt ran 2400 frames and reported
zero arrivals because there was nothing there yet. So this pokes stageTopRow --
which turretWorldTick's documented fallback path exists for, in those words --
and reaches the turrets in a couple of hundred frames.

AND THEN PROVES THE SEEK DID NOT FABRICATE IT. The last run pokes nothing at
all: it scrolls the real stage to turret 0 and checks the same two numbers.

WHAT WAS WRONG. turretAimTick arms the clock on the frame a turret's whole body
first fits inside the aperture -- logY 54. It used to load the full
TURRET_FIRE_INTERVAL there, so the first opportunity arrived 100 frames later,
and the stage scrolls one pixel a frame: the turret was at logY 154, the middle
of the screen. The player's instinct on seeing a turret is to climb and engage
it, so by then the ship was usually just underneath and the first shot went off
point-blank at a position it had only just taken.

The fix separates the FIRST delay from the REPEAT interval, so the first
opportunity lands as the turret reaches TURRET_FIRE_MIN_Y -- the top of the
window where a shot is legal at all -- instead of 66 pixels past it.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, poke, set_bp,  # noqa: E402
                     step_n, read16, check, report, LAUNCHED_PIDS)

sym = symbols(SYM)

# TURRET_TOTAL IS THE LEVEL'S AUTHORED TURRET COUNT, not a constant -- Level 1
# has five. Assuming eight made every array read run past its own end into the
# neighbouring one, which is how turretLogY came back as zero.
TURRET_TOTAL = sym["turretVisible"] - sym["turretLogY"]
PORT = 6603

# src/turrets.asm. The expectations are re-derived from these rather than
# written as row numbers that would go stale the moment they are tuned.
APERTURE_TOP_RASTER = 55
TURRET_ARM_Y = APERTURE_TOP_RASTER - 1                          # 54
TURRET_FIRE_MIN_Y = 88
TURRET_FIRE_MAX_Y = 201
TURRET_FIRE_INTERVAL = 100
TURRET_FIRST_FIRE_DELAY = TURRET_FIRE_MIN_Y - TURRET_ARM_Y      # 34
OLD_FIRST_FIRE_Y = TURRET_ARM_Y + TURRET_FIRE_INTERVAL          # 154
TURRET_MUZZLE_X = 4
TURRET_MUZZLE_Y = 12

MAX_OBJECTS = 16
TYPE_EBULLET = 2                 # src/objects.asm; 3 is TYPE_PICKUP

# turretLogY, turretVisible and turretFireTimer are neighbours by construction,
# so one dump covers all three -- and one dump per frame is what makes a
# per-frame sample affordable.
TRT_BASE = min(sym["turretLogY"], sym["turretVisible"], sym["turretFireTimer"])
TRT_SPAN = max(sym["turretLogY"], sym["turretVisible"],
               sym["turretFireTimer"]) + TURRET_TOTAL - TRT_BASE
# logActive and objType are in src/objects.asm; logX and logY are in
# src/motion.asm, a different segment, so the muzzle read is four small dumps
# rather than one block. It only happens on a shot frame.
OBJ_FIELDS = ("logActive", "objType", "logX", "logY")


class Pass:
    """One turret's single visit to the aperture, as observed."""

    def __init__(self, turret):
        self.turret = turret
        self.arm_y = None           # logY on the frame the clock was armed
        self.armed_with = None      # what the clock read that frame
        self.fire_ys = []           # logY each time the clock reached a shot
        self.reloads = []           # the value loaded after each shot
        self.timeline = []          # (logY, timer), for the monotonicity check


def warp_ahead(mon, frames, *, coarse=0.25, fine=0.05):
    """Free-run `frames` further on, then leave the machine halted.

    STEPPING THERE IS NOT AN OPTION. A monitor round trip per frame runs at
    about eight frames a second, so the 3,450 frames the stage needs to reach
    its first turret unaided would take seven and a half minutes. Free-running
    manages eight hundred. The cost is that `x` overshoots by whatever a slice
    happens to cover, so the slices shrink as the target approaches and the
    caller gets back the count actually covered rather than a promise.

    RELATIVE, NOT ABSOLUTE. frameCounter is already past five and a half
    thousand when boot="exact" hands the machine over -- that is the cost of
    loading from the d64 -- so an absolute target of 3,328 was already in the
    past and the warp returned without running a single frame. worldProgress was
    0 the whole time, which is how it showed up.

    THE BREAKPOINT MUST NOT BE ARMED YET or `x` stops on the very next frame.
    """
    base = read16(mon, sym["frameCounter"])
    while True:
        done = read16(mon, sym["frameCounter"]) - base
        left = frames - done
        if left <= 0:
            return done
        mon.cmd("x")
        time.sleep(coarse if left > 400 else fine)


def watch(v, frames, *, seek=None, warp=None, want_bolts=False):
    """Run `frames` frames and return the passes seen, keyed by (turret, n)."""
    mon = v.mon
    if warp is not None:
        warp_ahead(mon, warp)
    set_bp(mon, sym["gameFrame"])
    if seek is not None:
        # A FEW FRAMES FIRST, so the scroller and the turret shadow are both in
        # their steady state before the row is moved under them.
        step_n(mon, sym["frameCounter"], 8, lambda: None)
        poke(mon, sym["stageTopRowLo"], seek & 0xFF)
        poke(mon, sym["stageTopRowHi"], (seek >> 8) & 0xFF)
    # THE SHIP IS PUT WHERE A TURRET IS ALLOWED TO SHOOT AT IT. The fire path
    # also demands plyY > logY + TURRET_FIRE_LEAD and no invulnerability; those
    # are pre-existing gates this change does not touch, and leaving the ship
    # wherever the boot happened to put it would test them instead of the timer.
    poke(mon, sym["plyY"], 220)
    poke(mon, sym["plyInvuln"], 0)

    passes, open_pass, bolts = {}, {}, []
    prev = {}

    def sample():
        blk = rd(mon, TRT_BASE, TRT_SPAN)

        def g(name):
            o = sym[name] - TRT_BASE
            return blk[o:o + TURRET_TOTAL]

        ly, vis, tm = g("turretLogY"), g("turretVisible"), g("turretFireTimer")
        for t in range(TURRET_TOTAL):
            was_vis, was_tm = prev.get(t, (0, 0))
            if vis[t] and not was_vis:
                # ARMED. A fresh pass, and the count of these per turret is what
                # answers "did a coarse step manufacture a second arming".
                n = sum(1 for (tt, _) in passes if tt == t)
                p = Pass(t)
                p.arm_y, p.armed_with = ly[t], tm[t]
                passes[(t, n)] = p
                open_pass[t] = p
            if not vis[t]:
                open_pass.pop(t, None)
            p = open_pass.get(t)
            if p is not None:
                p.timeline.append((ly[t], tm[t]))
                # THE SHOT FRAME IS THE RELOAD FRAME. turretFireTick tests the
                # timer for zero and reloads before it tests the geometry, so
                # the frame the clock jumps from 0 back up is exactly the frame
                # the turret took its opportunity.
                if was_tm == 0 and tm[t] > 0 and was_vis:
                    # THE BOLT IS ONLY CHECKED FOR THE FIRST SHOT. A later shot
                    # in the same pass is subject to gates this change does not
                    # touch -- the ship has to be TURRET_FIRE_LEAD below, the
                    # arena population has to be under TURRET_FIRE_MAX_POP --
                    # and one of them refusing is correct behaviour, not a
                    # failure of the arming timing.
                    if want_bolts and not p.fire_ys:
                        bolts.append((t, ly[t], read_bolts(mon)))
                    p.fire_ys.append(ly[t])
                    p.reloads.append(tm[t])
            prev[t] = (vis[t], tm[t])
        return None

    step_n(mon, sym["frameCounter"], frames, sample)
    return passes, bolts


def read_bolts(mon):
    f = {n: rd(mon, sym[n], MAX_OBJECTS) for n in OBJ_FIELDS}
    return [(f["logX"][s], f["logY"][s]) for s in range(MAX_OBJECTS)
            if f["logActive"][s] and f["objType"][s] == TYPE_EBULLET]


def main():
    # Level 1's authored turrets, read off the machine rather than assumed.
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        meta = list(rd(v.mon, sym["turretMetaRow"], TURRET_TOTAL))
        xlo = list(rd(v.mon, sym["turretXLo"], TURRET_TOTAL))
    finally:
        if v:
            v.close()
    stage_rows = [m * 4 for m in meta]                  # METATILE_H = 4

    # ---- 1. the seeded pass: two turrets, in a couple of hundred frames ----
    # Four stage rows above turrets 1 and 2 (stage rows 224 and 216), so both
    # walk onto the aperture from above exactly as they would unaided, and both
    # are on it together -- which is also the multiple-turret check.
    target = sorted(stage_rows, reverse=True)[1]
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        passes, bolts = watch(v, 300, seek=target + 4, want_bolts=True)
    finally:
        if v:
            v.close()

    check("turrets were seen arriving on the aperture", bool(passes),
          f"{len(passes)} arrival(s): {sorted(passes)}")
    check("a turret arms as its whole body enters the aperture",
          all(p.arm_y == TURRET_ARM_Y for p in passes.values()),
          f"arm logY {sorted({p.arm_y for p in passes.values()})}, "
          f"expected {TURRET_ARM_Y}")

    # THE CLOCK IS READ AFTER turretFireTick HAS ALREADY DECREMENTED IT ONCE:
    # turretAimTick arms it and turretFireTick runs later in the same frame, so
    # the sample shows the loaded value minus one.
    check("the clock is armed with the FIRST-FIRE delay, not the full interval",
          all(p.armed_with == TURRET_FIRST_FIRE_DELAY - 1
              for p in passes.values()),
          f"observed {sorted({p.armed_with for p in passes.values()})} "
          f"(loaded {TURRET_FIRST_FIRE_DELAY}), "
          f"interval would be {TURRET_FIRE_INTERVAL}")

    fired = {k: p for k, p in passes.items() if p.fire_ys}
    check("the clock ran down and the turret took its opportunity",
          bool(fired), f"{len(fired)} of {len(passes)} pass(es) reached a shot")

    firsts = sorted(p.fire_ys[0] for p in fired.values())
    check("the FIRST opportunity lands EXACTLY at the top of the legal window",
          bool(firsts) and all(y == TURRET_FIRE_MIN_Y for y in firsts),
          f"first opportunity at logY {firsts}, TURRET_FIRE_MIN_Y "
          f"{TURRET_FIRE_MIN_Y}")
    check("...far earlier than the old behaviour could manage",
          bool(firsts) and max(firsts) < OLD_FIRST_FIRE_Y,
          f"{firsts} vs logY {OLD_FIRST_FIRE_Y} before the change")
    # NOT ONE PIXEL EARLY EITHER, and this is the reason the delay is derived
    # rather than picked: turretFireTick reloads the full interval BEFORE it
    # tests the Y window, so an opportunity that arrives at logY 87 is not
    # merely early, it is thrown away and the real first shot slips to 188.
    check("...and never before shots become legal at all",
          bool(firsts) and min(firsts) >= TURRET_FIRE_MIN_Y,
          f"earliest {min(firsts) if firsts else None} >= {TURRET_FIRE_MIN_Y}")

    # ---- 2. repeats are untouched -----------------------------------------
    repeats = [r for p in passes.values() for r in p.reloads]
    check("every shot reloads the FULL interval, first one included",
          bool(repeats) and all(r == TURRET_FIRE_INTERVAL for r in repeats),
          f"reloads {sorted(set(repeats))}, interval {TURRET_FIRE_INTERVAL}")
    # A FRAME MORE THAN THE INTERVAL, AND THAT IS PRE-EXISTING. turretAimTick
    # arms the clock and turretFireTick decrements it later the same frame, so
    # an arming of 34 spends 34 frames. The reload happens inside turretFireTick
    # on the path that does NOT then decrement, so a reload of 100 spends 101.
    # Nothing in this change touched either path; it is recorded here so the
    # gap being 101 rather than 100 reads as measured rather than as a bug.
    gaps = [b - a for p in fired.values() for a, b in zip(p.fire_ys, p.fire_ys[1:])]
    check("a second opportunity, when the pass is long enough, is an "
          "interval later",
          all(g == TURRET_FIRE_INTERVAL + 1 for g in gaps) if gaps else True,
          f"gaps between opportunities {sorted(set(gaps))} "
          f"(interval {TURRET_FIRE_INTERVAL} + the reload frame)" if gaps
          else "no pass was long enough for a second -- nothing to contradict")

    # ---- 3. no duplicate and no missed arming across the fine phases -------
    # A turret's pass spans ~180 frames, so it crosses every one of the eight
    # fine-scroll phases and some twenty coarse steps. turretWorldTick blanks
    # turretVisible on a coarse step, and blanking it unconditionally would
    # manufacture a fresh 0 -> 1 transition -- a re-arm -- once every eight
    # frames. So: exactly one arming per turret, and a clock that only ever
    # counts down between arming and firing.
    per_turret = {}
    for (t, _), p in passes.items():
        per_turret.setdefault(t, []).append(p)
    check("each turret arms exactly ONCE per pass, across every fine phase",
          all(len(v_) == 1 for v_ in per_turret.values()),
          f"armings per turret { {t: len(v_) for t, v_ in per_turret.items()} }")

    def monotone(p):
        # UP TO BUT NOT INCLUDING THE SHOT FRAME. That frame is where the clock
        # legitimately jumps from 0 back to the full interval, and including it
        # makes the approach look reset when it was fired.
        seg = [tm for ly, tm in p.timeline if ly < p.fire_ys[0]] \
            if p.fire_ys else [tm for _, tm in p.timeline]
        return len(seg) > 1 and all(b == a - 1 for a, b in zip(seg, seg[1:]))

    check("the clock counts down one a frame and is never reset mid-approach",
          all(monotone(p) for p in passes.values()),
          "; ".join(f"t{p.turret}: {len(p.timeline)} frames watched"
                    for p in passes.values()))
    check("more than one turret was exercised, and neither disturbed the other",
          len(per_turret) > 1, f"turrets {sorted(per_turret)}")

    # ---- 4. the projectile origin is still on the aperture -----------------
    # THE BOLT IS IDENTIFIED BY ITS MUZZLE, not by being the only thing in the
    # pool. turretFireTick launches from turretXLo + 4, turretLogY + 12, and an
    # enemy bolt cannot be at a turret's column and the turret's row at the
    # exact frame that turret's clock reloaded.
    origins = []
    for t, ly, pool in bolts:
        want = ((xlo[t] + TURRET_MUZZLE_X) & 0xFF, (ly + TURRET_MUZZLE_Y) & 0xFF)
        origins.append((t, want, want in pool, pool))
    check("the first shot really is emitted, from the turret's own muzzle",
          bool(origins) and all(ok for _, _, ok, _ in origins),
          "; ".join(f"t{t} expected {w} pool {p}" for t, w, ok, p in origins)
          or "no shot frame was sampled")
    check("the muzzle is inside the aperture, not off the top of it",
          all(TURRET_FIRE_MIN_Y + TURRET_MUZZLE_Y <= w[1]
              <= TURRET_FIRE_MAX_Y + TURRET_MUZZLE_Y for _, w, _, _ in origins)
          if origins else False,
          f"muzzle Y {[w[1] for _, w, _, _ in origins]}, aperture rows "
          f"{TURRET_FIRE_MIN_Y}..{TURRET_FIRE_MAX_Y}")

    # ---- 5. THE SAME NUMBERS WITH NOTHING POKED ----------------------------
    # The stage is left to scroll to turret 0 on its own. This is the check that
    # the seek above measured the real mechanism and not an artefact of moving
    # stageTopRow by hand.
    # stageTopRow starts at 775 and steps back one every eight frames, so the
    # highest-numbered turret row is the FIRST one reached.
    first_row = max(stage_rows)
    nat_frame = (775 - first_row) * 8               # ~3448 for Level 1
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        # Free-run to within a couple of hundred frames, then step through the
        # arrival and far enough past it for the clock to run out.
        nat, _ = watch(v, 260, warp=nat_frame - 120)
    finally:
        if v:
            v.close()

    check("with NOTHING POKED, the stage scrolls to a turret on its own",
          bool(nat), f"turret(s) {sorted({t for t, _ in nat})} arrived "
                     f"unaided around frame {nat_frame}")
    check("...and it arms at the same logY, with the same first-fire delay",
          bool(nat) and all(p.arm_y == TURRET_ARM_Y
                            and p.armed_with == TURRET_FIRST_FIRE_DELAY - 1
                            for p in nat.values()),
          f"arm logY {sorted({p.arm_y for p in nat.values()})}, "
          f"clock {sorted({p.armed_with for p in nat.values()})}")
    nat_firsts = sorted(p.fire_ys[0] for p in nat.values() if p.fire_ys)
    check("...and its first opportunity is the same logY too",
          bool(nat_firsts) and all(y == TURRET_FIRE_MIN_Y for y in nat_firsts),
          f"first opportunity at logY {nat_firsts}")

    print(f"\n  Level 1 turrets: metatile rows {meta} -> stage rows "
          f"{stage_rows}")
    print(f"  seeded stageTopRow to {target + 4}; sampled every frame")
    for k in sorted(passes):
        p = passes[k]
        print(f"    turret {p.turret}: armed at logY {p.arm_y} with "
              f"{p.armed_with + 1}, shot at logY {p.fire_ys}, "
              f"reloads {p.reloads}")
    print(f"  unaided: turret(s) {sorted({t for t, _ in nat})} at frame "
          f"~{nat_frame}, armed logY "
          f"{sorted({p.arm_y for p in nat.values()})}, first shot "
          f"{nat_firsts}")
    print(f"  new: arm at logY {TURRET_ARM_Y} + {TURRET_FIRST_FIRE_DELAY} "
          f"frames -> first opportunity logY "
          f"{TURRET_ARM_Y + TURRET_FIRST_FIRE_DELAY} "
          f"(= TURRET_FIRE_MIN_Y {TURRET_FIRE_MIN_Y})")
    print(f"  old: arm at logY {TURRET_ARM_Y} + {TURRET_FIRE_INTERVAL} frames "
          f"-> first opportunity logY {OLD_FIRST_FIRE_Y}, and the Y window "
          f"passed it 66 pixels earlier")
    print(f"  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
