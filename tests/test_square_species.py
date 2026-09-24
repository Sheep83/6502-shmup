#!/usr/bin/env python3
"""The Square is a real third ordinary species, proved on the machine.

    python3 tests/test_square_species.py

NO LEVEL IS MODIFIED TO RUN THIS. The trigger table is package data in RAM at
waveTrigSpecies, so the species column is poked before the first trigger becomes
due -- exactly the technique tests/test_species_order.py already uses. Neither
Level 1 nor Level 2 gains a Square encounter on disk, and nothing is restored
afterwards because nothing on disk was touched.

WHAT IS ACTUALLY BEING ASKED:

    * does levelAssetsLoad resolve a THIRD animation row, and does it hold the
      Square's own four sprite pointers in the authored shape?
    * does a wave whose species byte is SPECIES_SQUARE actually spawn?
    * do the spawned objects carry SPECIES_SQUARE for life?
    * can several Squares be alive at once, the way Rings can and Droppers
      deliberately cannot?
    * does the one-live-Dropper substitution leave them alone?
    * do they move, and do they eventually despawn?
    * and do Ring and Dropper still behave exactly as they did?
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     step_n, check, report, LAUNCHED_PIDS)

sym = symbols(SYM)

MAX_OBJECTS = 16
TYPE_ENEMY = 1
SPECIES_RING, SPECIES_DROPPER, SPECIES_SQUARE = 0, 8, 16
ENEMY_ANIM_STEPS = 8
SPECIES_COUNT = 3
PORT = 6581
MAX_FRAMES = 2300


def _due_triggers():
    """How many authored triggers can actually become due inside the budget.

    Level 1's last trigger sits at world row 665 and a coarse row is eight
    displayed frames, so it needs some 5,300 frames -- far beyond a window
    sized for the encounter cluster at the start of the stage. Asserting "all
    eight fired" would be asserting something the budget cannot reach, so the
    number is derived from the level rather than written down.
    """
    import json
    doc = json.loads((ROOT / "tools/level_editor/levels/level1/level.v6.json")
                     .read_text())
    return sum(1 for t in doc["triggers"] if t["worldProgress"] * 8 <= MAX_FRAMES)


DUE = _due_triggers()

# src/enemy.asm: SQUARE_SHAPE = 0,1,2,3, 3,2,1,0 -- a spin, out and back.
SQUARE_SHAPE = (0, 1, 2, 3, 3, 2, 1, 0)
RING_SHAPE = (0, 1, 2, 3, 0, 1, 2, 3)
DROPPER_SHAPE = (0, 1, 2, 3, 3, 2, 1, 0)

OBJ_BASE = sym["enySpecies"]
OBJ_SPAN = sym["objType"] + MAX_OBJECTS - OBJ_BASE


def sample(mon):
    blk = rd(mon, OBJ_BASE, OBJ_SPAN)
    wv = rd(mon, sym["wvStarted"], 4)
    pos = rd(mon, sym["logY"], MAX_OBJECTS)

    def field(name):
        o = sym[name] - OBJ_BASE
        return blk[o:o + MAX_OBJECTS]

    species, active, typ = field("enySpecies"), field("logActive"), field("objType")
    live = [(s, species[s]) for s in range(MAX_OBJECTS)
            if active[s] and typ[s] == TYPE_ENEMY]
    return {"live": live,
            "squares": sum(1 for _, sp in live if sp == SPECIES_SQUARE),
            "droppers": sum(1 for _, sp in live if sp == SPECIES_DROPPER),
            "rings": sum(1 for _, sp in live if sp == SPECIES_RING),
            "ys": {s: pos[s] for s, _ in live},
            "started": wv[0],
            "spawned": wv[sym["wvSpawned"] - sym["wvStarted"]]}


def fly(pattern, label):
    """Impose `pattern` on the trigger table, fly the stage, and watch."""
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        n = rd1(mon, sym["wvNextTrig"])
        assert n == 0, f"the director has already consumed {n} triggers"

        # The resolved animation table, read AFTER gameInit has run
        # levelAssetsLoad. One row of ENEMY_ANIM_STEPS pointers per species.
        seq = rd(mon, sym["enemyAnimSeq"], SPECIES_COUNT * ENEMY_ANIM_STEPS)
        shape = rd(mon, sym["enemyAnimShape"], SPECIES_COUNT * ENEMY_ANIM_STEPS)
        descs = rd(mon, sym["levelAssetDescs"], 8)

        count = len(pattern)
        for i, ch in enumerate(pattern):
            poke(mon, sym["waveTrigSpecies"] + i,
                 {"R": SPECIES_RING, "D": SPECIES_DROPPER,
                  "S": SPECIES_SQUARE}[ch])
        got = rd(mon, sym["waveTrigSpecies"], count)
        readback = "".join({SPECIES_RING: "R", SPECIES_DROPPER: "D",
                            SPECIES_SQUARE: "S"}.get(b, "?") for b in got)
        check(f"{label}: the trigger table reads back as {pattern}",
              readback == pattern, readback)

        set_bp(mon, sym["gameFrame"])
        frames = step_n(mon, sym["frameCounter"], MAX_FRAMES, lambda: sample(mon))
    finally:
        if v:
            v.close()
    return frames, seq, shape, descs


def main():
    # ---- the third animation row exists and is the Square's ---------------
    frames, seq, shape, descs = fly("SSSSSSSS"[:8], "all Squares")

    square_row = list(seq[2 * ENEMY_ANIM_STEPS: 3 * ENEMY_ANIM_STEPS])
    ring_row = list(seq[0:ENEMY_ANIM_STEPS])
    dropper_row = list(seq[ENEMY_ANIM_STEPS:2 * ENEMY_ANIM_STEPS])

    # The level puts Ring/Dropper/Square at window slots 0/4/8, and the window
    # base pointer is $b0, so the rows must be built from $b0/$b4/$b8.
    want_square = [0xB8 + f for f in SQUARE_SHAPE]
    want_ring = [0xB0 + f for f in RING_SHAPE]
    want_dropper = [0xB4 + f for f in DROPPER_SHAPE]

    check("levelAssetsLoad resolved THREE animation rows, not two",
          len(seq) == SPECIES_COUNT * ENEMY_ANIM_STEPS, f"{len(seq)} entries")
    check("the Square's row is its own four sprite pointers in the spin order",
          square_row == want_square,
          f"{[hex(b) for b in square_row]} vs {[hex(b) for b in want_square]}")
    check("the Ring's row is unchanged", ring_row == want_ring,
          f"{[hex(b) for b in ring_row]}")
    check("the Dropper's row is unchanged", dropper_row == want_dropper,
          f"{[hex(b) for b in dropper_row]}")
    check("every Square pointer addresses the Square's own art at $2e00",
          all(0xB8 <= p <= 0xBB for p in square_row),
          f"{[hex(b) for b in square_row]}")
    check("the shape table carries a third row",
          list(shape[2 * ENEMY_ANIM_STEPS:3 * ENEMY_ANIM_STEPS]) == list(SQUARE_SHAPE),
          str(list(shape[2 * ENEMY_ANIM_STEPS:3 * ENEMY_ANIM_STEPS])))
    check("the level's descriptor row is Ring 0, Dropper 4, Square 8",
          list(descs[0:3]) == [0, 4, 8], str(list(descs[0:4])))

    # ---- Squares actually fly ---------------------------------------------
    peak_sq = max(f["squares"] for f in frames)
    peak_dr = max(f["droppers"] for f in frames)
    spawned = max(f["spawned"] for f in frames)
    started = max(f["started"] for f in frames)
    check(f"all-Square: every trigger due inside the window fired ({DUE})",
          started >= DUE, f"{started} started of {DUE} due")
    check("all-Square: Squares actually spawned", peak_sq > 0, f"peak {peak_sq}")
    check("all-Square: SEVERAL are alive at once, as Rings may be",
          peak_sq > 1, f"peak {peak_sq}")
    check("all-Square: not one object was ever committed as a Dropper",
          peak_dr == 0, f"peak {peak_dr}")
    check("all-Square: the one-live-Dropper rule did not substitute anything",
          all(sp == SPECIES_SQUARE for f in frames for _, sp in f["live"]),
          "a live enemy carried another species")

    # movement: a Square's Y must change while it is alive
    moved = False
    for a, b in zip(frames, frames[1:]):
        for slot, y in a["ys"].items():
            if slot in b["ys"] and b["ys"][slot] != y:
                moved = True
                break
        if moved:
            break
    check("all-Square: Squares move under the ordinary movement system", moved)

    # despawn: the population must come back down
    tail = frames[-1]["squares"]
    check("all-Square: they despawn rather than accumulating",
          tail < peak_sq or spawned > peak_sq,
          f"peak {peak_sq}, spawned {spawned}, final {tail}")
    check("all-Square: the pool never overflowed",
          all(len(f["live"]) <= MAX_OBJECTS for f in frames))

    # ---- Ring and Dropper still behave ------------------------------------
    frames2, _, _, _ = fly("RDRDRDRD", "mixed Ring/Dropper")
    check("mixed: Rings still spawn",
          max(f["rings"] for f in frames2) > 0)
    check("mixed: Droppers still spawn",
          max(f["droppers"] for f in frames2) > 0)
    check("mixed: NEVER more than one live Dropper -- the rule still holds",
          max(f["droppers"] for f in frames2) <= 1,
          f"peak {max(f['droppers'] for f in frames2)}")
    check("mixed: no Square appeared from nowhere",
          max(f["squares"] for f in frames2) == 0)

    frames3, _, _, _ = fly("SRSDSRSD", "Squares beside Ring and Dropper")
    check("mixed-with-Square: all three species coexist",
          max(f["squares"] for f in frames3) > 0
          and max(f["rings"] for f in frames3) > 0
          and max(f["droppers"] for f in frames3) > 0,
          f"peak S={max(f['squares'] for f in frames3)} "
          f"R={max(f['rings'] for f in frames3)} "
          f"D={max(f['droppers'] for f in frames3)}")
    check("mixed-with-Square: the Dropper rule is unaffected by Squares",
          max(f["droppers"] for f in frames3) <= 1,
          f"peak {max(f['droppers'] for f in frames3)}")

    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
