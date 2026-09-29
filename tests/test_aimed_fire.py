#!/usr/bin/env python3
"""Aimed enemy fire, proved on the machine.

    python3 tests/test_aimed_fire.py

NO LEVEL IS MODIFIED. The wave definition table is package data in RAM, so the
firing-mode bits of each definition's colour byte are poked before anything
spawns -- the technique tests/test_species_order.py uses for the species column.
Nothing on disk is touched.

WHAT IS BEING ASKED:

    * does an AIMED wave produce a bolt with a horizontal velocity, and a DOWN
      wave still produce one with none?
    * does the bolt lean the right way?
    * is it AIMED and not HOMING -- does moving the ship after launch leave the
      trajectory alone?
    * are the three available speeds close enough that a diagonal does not
      visibly outrun a vertical?
    * do Ring, Dropper and Square all reach the same path?

FOUR EMULATOR LAUNCHES, NOT ELEVEN, and one bulk read per sample rather than
seven. logActive, objType, objVX and objVY are neighbours by construction, so
one `m` covers all four; and a bolt's velocity is fixed at launch, so sampling
every third frame still catches every bolt with the values it was born with.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     step_n, check, report, LAUNCHED_PIDS)
import campaign_data as CD                                           # noqa: E402

sym = symbols(SYM)

MAX_OBJECTS = 16
TYPE_EBULLET = 2                 # src/objects.asm; 3 is TYPE_PICKUP
PORT = 6601
FRAMES = 1100      # enemy shots are sparse: ~5 in 900 frames
SAMPLE_EVERY = 2

# HOW A WAVE FIRES IS A TRIGGER FIELD. It used to be bits 4-5 of the wave
# DEFINITION's byte 7, and this file forced the mode by poking that byte; byte 7
# is now reserved and zero, and the mode lives in the trigger list's own
# trigFireMode column (src/encounter_format.asm). Poking the old place stopped
# doing anything, which is exactly what this note exists to stop happening
# silently again.
# THE LIVE TRIGGER COUNT, READ FROM src/levelpkg.asm RATHER THAN RESTATED.
# A `WAVE_DEFS = 7` used to sit here too; nothing referenced it and it was one
# re-authoring away from being a lie, so it is gone.
TRIG_FIRE_DOWN, TRIG_FIRE_AIMED = 0, 1
LEVELPKG_TRIGN = CD.TRIGN_ADDR

# SPECIES BY SLOT, NOT BY ARTWORK. A level chooses which identity each of the
# engine's three enemy slots wears; the ROW OFFSET is the engine's and does not
# change. Naming the slots keeps this file out of the roster's business.
SPECIES = {f"slot{i}": i * CD.C.ENEMY_ANIM_STEPS
           for i in range(CD.C.ENEMY_SLOTS)}
EXPECTED_VY = {0: 3, 1: 3, 2: 2}        # src/ebullet.asm ebulletAimVY

# ---------------------------------------------------------------------------
# THE AIM LAW, DERIVED FROM src/ebullet.asm, replacing "bolts lean left".
#
# "Pin the ship far left, every bolt must lean left" is not a property of the
# engine: it is a property of WHERE THE LEVEL HAPPENS TO PUT ENEMIES. Level 1
# was re-authored, an enemy now spawns near the left edge, and the run duly
# produced a perfectly correct vx of 0 -- the shooter was directly above the
# ship -- and the check failed.
#
# So the check is the actual contract instead: the horizontal step is the
# QUANTISED DISTANCE from the bolt to the ship, whichever side it is on. That
# holds for every enemy at every position, needs no assumption about the
# authored formation, and is strictly stronger than the leaning test -- it
# pins the two thresholds and the sign rather than just the sign.
# ---------------------------------------------------------------------------
def _eb_const(name):
    src = (ROOT / "src" / "ebullet.asm").read_text(encoding="utf-8")
    import re
    return int(re.search(rf"^\s*\.const\s+{name}\s*=\s*(\d+)", src, re.M).group(1))


EBULLET_VX_MAX = _eb_const("EBULLET_VX_MAX")
AIM_NEAR = _eb_const("EBULLET_AIM_NEAR")
AIM_MID = _eb_const("EBULLET_AIM_MID")


def aim_vx(delta):
    """ebulletAim, in Python. `delta` = playerX - bulletX, nine bits signed."""
    if delta > 255:                     # further than the low byte can carry
        return EBULLET_VX_MAX
    if delta < -256:
        return -EBULLET_VX_MAX
    mag = abs(delta)
    slope = 0 if mag < AIM_NEAR else 1 if mag < AIM_MID else EBULLET_VX_MAX
    return -slope if delta < 0 else slope

# One dump covers all four fields.
BLK_BASE = sym["logActive"]
BLK_SPAN = sym["objVY"] + MAX_OBJECTS - BLK_BASE


def signed(b):
    return b - 256 if b > 127 else b


def set_mode(mon, aimed):
    """Put every AUTHORED APPEARANCE into one firing mode.

    Only the live entries: the columns are padded to the package's slot count
    and the director never reads past LEVELPKG_TRIGN.
    """
    mode = TRIG_FIRE_AIMED if aimed else TRIG_FIRE_DOWN
    for t in range(rd1(mon, LEVELPKG_TRIGN)):
        poke(mon, sym["waveTrigFireMode"] + t, mode)


def run(*, aimed, player_x=None, species=None, move_to=None):
    """Returns {slot: (vx, vy, delta)} for every bolt at its first sighting.

    `delta` is playerX - bulletX AT THAT MOMENT, which is what ebulletAim was
    given, so the quantised slope can be checked exactly instead of by its sign.
    """
    v = None
    seen, moved = {}, [False]
    after, moved_at = {}, [set()]
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_mode(mon, aimed)
        if species:
            # CYCLED OVER THE LIVE TRIGGERS, however many the level authors --
            # a fixed-length list here silently covered only the first few once
            # the level grew, or wrote past the live entries once it shrank.
            for i in range(rd1(mon, LEVELPKG_TRIGN)):
                poke(mon, sym["waveTrigSpecies"] + i,
                     SPECIES[species[i % len(species)]])
        if player_x is not None:
            poke(mon, sym["plyX"], player_x & 0xFF)
            poke(mon, sym["plyXHi"], (player_x >> 8) & 1)

        n = [0]

        def sample():
            n[0] += 1
            if n[0] % SAMPLE_EVERY:
                return None
            blk = rd(mon, BLK_BASE, BLK_SPAN)

            def f(name):
                o = sym[name] - BLK_BASE
                return blk[o:o + MAX_OBJECTS]

            act, typ = f("logActive"), f("objType")
            vx, vy = f("objVX"), f("objVY")
            for s in range(MAX_OBJECTS):
                if act[s] and typ[s] == TYPE_EBULLET and s not in seen:
                    # THE GEOMETRY ebulletAim SAW, read at the first sighting:
                    # the bolt's own X (it launches at the shooter) and the
                    # ship's. Both nine bit.
                    bx = (rd1(mon, sym["logX"] + s)
                          | (rd1(mon, sym["logXHi"] + s) << 8))
                    px = rd1(mon, sym["plyX"]) | (rd1(mon, sym["plyXHi"]) << 8)
                    seen[s] = (signed(vx[s]), vy[s], px - bx)
                    if move_to is not None and not moved[0]:
                        # THE SHIP RUNS, after a bolt is already in flight.
                        poke(mon, sym["plyX"], move_to & 0xFF)
                        poke(mon, sym["plyXHi"], (move_to >> 8) & 1)
                        moved[0] = True
                        moved_at[0] = set(seen)
                # WHILE IT IS STILL ALIVE, not at the end of the run -- a bolt
                # lives a few dozen frames and the run is eleven hundred, so
                # sampling once at the end finds an empty pool.
                #
                # AND ONLY WHILE IT IS THE SAME BOLT. The pool reuses slots: the
                # bolt that was in flight when the ship moved dies, and the next
                # shot -- correctly aimed at the ship's NEW position -- is handed
                # the same slot. Comparing those two reads "the bolt turned
                # round", which is the opposite of what happened. So a slot that
                # goes inactive stops being tracked.
                if not act[s] or typ[s] != TYPE_EBULLET:
                    moved_at[0].discard(s)
                elif moved[0] and s in moved_at[0]:
                    after[s] = signed(vx[s])
            return None

        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], FRAMES, sample)

        return seen, after, moved[0]
    finally:
        if v:
            v.close()


def main():
    # ---- 1. the existing mode is untouched --------------------------------
    down, _, _ = run(aimed=False)
    check("DOWN: bolts were produced", bool(down), f"{len(down)} seen")
    check("DOWN: every bolt falls straight -- no horizontal velocity",
          all(vx == 0 for vx, _vy, _d in down.values()),
          str(sorted({vx for vx, _vy, _d in down.values()})))
    check("DOWN: every bolt keeps the plain vertical step",
          all(vy == 3 for _vx, vy, _d in down.values()),
          str(sorted({vy for _vx, vy, _d in down.values()})))

    # ---- 2 and 3. aimed, the ship pinned to each edge in turn -------------
    # TESTED BY THE LAW, NOT BY THE LEVEL. See aim_vx above: what is asserted
    # is that the slope matches the distance the engine measured, which is true
    # of every shooter wherever the author put it. Sampling is every
    # SAMPLE_EVERY frames, so a bolt may already have taken a step or two by
    # its first sighting; the tolerance is exactly that much drift and no more.
    DRIFT = SAMPLE_EVERY * EBULLET_VX_MAX

    def law_holds(vx, delta):
        return any(vx == aim_vx(delta + d) for d in range(-DRIFT, DRIFT + 1))

    left, _, _ = run(aimed=True, player_x=32)
    wrong = [(vx, d) for vx, _vy, d in left.values() if not law_holds(vx, d)]
    check("AIMED, ship far LEFT: every bolt's slope is the quantised distance "
          "to the ship",
          bool(left) and not wrong,
          f"{len(left)} bolts; (vx, playerX-boltX) "
          f"{sorted((vx, d) for vx, _vy, d in left.values())}"
          + (f"; WRONG {wrong}" if wrong else ""))
    check("...and with the ship at the left edge none of them leans RIGHT of a "
          "shooter that is to the ship's right",
          all(vx <= 0 for vx, _vy, d in left.values() if d < -AIM_NEAR),
          str(sorted((vx, d) for vx, _vy, d in left.values())))

    right, _, _ = run(aimed=True, player_x=300)
    wrong = [(vx, d) for vx, _vy, d in right.values() if not law_holds(vx, d)]
    check("AIMED, ship far RIGHT: every bolt's slope is the quantised distance "
          "to the ship",
          bool(right) and not wrong,
          f"{len(right)} bolts; (vx, playerX-boltX) "
          f"{sorted((vx, d) for vx, _vy, d in right.values())}"
          + (f"; WRONG {wrong}" if wrong else ""))
    check("...and a shooter to the ship's left is never shot away from it",
          all(vx >= 0 for vx, _vy, d in right.values() if d > AIM_NEAR),
          str(sorted((vx, d) for vx, _vy, d in right.values())))

    # BOTH SIGNS MUST ACTUALLY HAVE BEEN OBSERVED, or the law above could be
    # satisfied by a stream of zeroes. The two runs pin the ship 268 pixels
    # apart, so between them some shooter is well to either side whatever the
    # level looks like.
    every = list(left.values()) + list(right.values())
    check("aimed fire was observed leaning BOTH ways across the two runs",
          any(vx < 0 for vx, _vy, _d in every)
          and any(vx > 0 for vx, _vy, _d in every),
          str(sorted({vx for vx, _vy, _d in every})))

    # ---- the arc, and its speeds ------------------------------------------
    both = dict(left)
    both.update({(k + 100): v for k, v in right.items()})
    vxs = sorted({vx for vx, _vy, _d in both.values()})
    check("AIMED: every horizontal velocity is inside the quantised arc",
          all(abs(vx) <= EBULLET_VX_MAX for vx in vxs), str(vxs))
    # TWO CHECKS USED TO LIVE HERE AND BOTH WERE FALSE CONFIDENCE.
    #
    # The first asserted that each slope "carries its matched vertical step" by
    # reading the STORED objVY. The second computed the shot's speed as
    # sqrt(vx^2 + vy^2) from those same stored bytes and required the arc to be
    # normalised within 10%. Between them they certified a speed the projectile
    # did not fly: ebulletTick consumed objVX for the horizontal step and a
    # CONSTANT for the vertical, so the steepest slope stored 2 and moved 3 --
    # and both checks passed throughout, because every byte they read was
    # correct. They pass identically on the fixed and the unfixed engine.
    #
    # The 10% gate had a second defect of its own: the authored table [3,3,2]
    # spreads 11.7% by construction, so it could never hold once all three
    # buckets were observed together -- it survived by not always seeing them.
    #
    # Both claims are now made from MEASURED DISPLACEMENT in
    # tests/test_aimed_velocity.py, which fails on the bug these could not see.
    # What stays in this file is the coverage that file does not have: that the
    # bolt leans toward the ship, that it is not homing, that FIRE_DOWN is
    # straight, and that all three species reach the aimed path.
    pairs = {(abs(vx), vy) for vx, vy, _d in both.values()}
    print(f"  info (vx,vy) pairs observed: {sorted(pairs)} "
          f"-- speed is asserted from motion in test_aimed_velocity.py")

    # ---- 4. not homing, and every enemy slot, in one session --------------
    # EVERY SLOT THE ENGINE HAS, whatever artwork this level has put in them:
    # the point is that no behavioural species is excluded from the aimed path,
    # and the slot row offsets are the engine's while the identities are the
    # level's. Each authored trigger is forced onto a slot in turn.
    mixed = [f"slot{i}" for i in range(CD.C.ENEMY_SLOTS)]
    seen, after, moved = run(aimed=True, player_x=32, species=mixed, move_to=300)
    check("AIMED: the ship was moved while a bolt was in flight",
          moved and bool(after), f"{len(after)} bolt(s) still alive afterwards")
    check("AIMED IS NOT HOMING: no bolt changed course after launch",
          all(after[s] == seen[s][0] for s in after),
          str({s: (seen[s][0], after[s]) for s in after
               if after[s] != seen[s][0]}) or "none changed")
    check("every enemy slot reaches the aimed path -- the slope obeys the law "
          "for all of them",
          bool(seen) and all(law_holds(vx, d) for vx, _vy, d in seen.values()),
          f"{len(seen)} bolt(s) from a mixed-slot stage, "
          f"(vx, playerX-boltX) "
          f"{sorted((vx, d) for vx, _vy, d in seen.values())}")

    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
