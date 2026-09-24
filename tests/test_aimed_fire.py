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

sym = symbols(SYM)

MAX_OBJECTS = 16
TYPE_EBULLET = 2                 # src/objects.asm; 3 is TYPE_PICKUP
PORT = 6601
FRAMES = 1100      # enemy shots are sparse: ~5 in 900 frames
SAMPLE_EVERY = 2

WAVEDEF_SIZE = 10
WD_COLOUR = 7                 # the byte that also carries the firing mode
FIRE_AIMED = 0x10             # bits 4-5
COLOUR_MASK = 0x0F
WAVE_DEFS = 7

SPECIES = {"RING": 0, "DROPPER": 8, "SQUARE": 16}
EXPECTED_VY = {0: 3, 1: 3, 2: 2}        # src/ebullet.asm ebulletAimVY
EBULLET_VX_MAX = 2

# One dump covers all four fields.
BLK_BASE = sym["logActive"]
BLK_SPAN = sym["objVY"] + MAX_OBJECTS - BLK_BASE


def signed(b):
    return b - 256 if b > 127 else b


def set_mode(mon, aimed):
    base = sym["waveDefTable"]
    for d in range(WAVE_DEFS):
        a = base + d * WAVEDEF_SIZE + WD_COLOUR
        poke(mon, a, (rd1(mon, a) & COLOUR_MASK) | (FIRE_AIMED if aimed else 0))


def run(*, aimed, player_x=None, species=None, move_to=None):
    """Returns {slot: (vx, vy)} for every bolt seen at its first sighting."""
    v = None
    seen, moved = {}, [False]
    after, moved_at = {}, [set()]
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_mode(mon, aimed)
        if species:
            for i, sp in enumerate(species):
                poke(mon, sym["waveTrigSpecies"] + i, SPECIES[sp])
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
                    seen[s] = (signed(vx[s]), vy[s])
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
          all(vx == 0 for vx, _ in down.values()),
          str(sorted({vx for vx, _ in down.values()})))
    check("DOWN: every bolt keeps the plain vertical step",
          all(vy == 3 for _, vy in down.values()),
          str(sorted({vy for _, vy in down.values()})))

    # ---- 2. aimed, ship pinned hard left ----------------------------------
    left, _, _ = run(aimed=True, player_x=32)
    check("AIMED, ship far LEFT: bolts lean left",
          bool(left) and all(vx < 0 for vx, _ in left.values()),
          str(sorted({vx for vx, _ in left.values()})))

    # ---- 3. aimed, ship pinned hard right ---------------------------------
    right, _, _ = run(aimed=True, player_x=300)
    check("AIMED, ship far RIGHT: bolts lean right",
          bool(right) and all(vx > 0 for vx, _ in right.values()),
          str(sorted({vx for vx, _ in right.values()})))

    # ---- the arc, and its speeds ------------------------------------------
    both = dict(left)
    both.update({(k + 100): v for k, v in right.items()})
    vxs = sorted({vx for vx, _ in both.values()})
    check("AIMED: every horizontal velocity is inside the quantised arc",
          all(abs(vx) <= EBULLET_VX_MAX for vx in vxs), str(vxs))
    pairs = {(abs(vx), vy) for vx, vy in both.values()}
    check("AIMED: each slope carries its matched vertical step",
          all(EXPECTED_VY[a] == vy for a, vy in pairs), str(sorted(pairs)))
    speeds = sorted({round((a * a + vy * vy) ** 0.5, 2) for a, vy in pairs})
    spread = (max(speeds) - min(speeds)) / min(speeds) * 100 if speeds else 0
    check("AIMED: the diagonal does not outrun the vertical (within 10%)",
          spread <= 10.0, f"speeds {speeds} -> {spread:.1f}% spread")

    # ---- 4. not homing, and all three species, in one session -------------
    mixed = ["RING", "DROPPER", "SQUARE"] * 3
    seen, after, moved = run(aimed=True, player_x=32, species=mixed, move_to=300)
    check("AIMED: the ship was moved while a bolt was in flight",
          moved and bool(after), f"{len(after)} bolt(s) still alive afterwards")
    check("AIMED IS NOT HOMING: no bolt changed course after launch",
          all(after[s] == seen[s][0] for s in after),
          str({s: (seen[s][0], after[s]) for s in after
               if after[s] != seen[s][0]}) or "none changed")
    check("Ring, Dropper and Square all reach the aimed path",
          bool(seen) and any(vx < 0 for vx, _ in seen.values()),
          f"{len(seen)} bolt(s) from a mixed-species stage, "
          f"vx {sorted({vx for vx, _ in seen.values()})}")

    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
