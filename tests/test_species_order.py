#!/usr/bin/env python3
"""Any order of authored species runs correctly. Proved on the machine.

WHY THIS FILE EXISTS. src/waves.asm used to assert at assembly time that no
two consecutive triggers shared a species, so that "every other wave is a
Dropper" was a property of the build. That described LEVEL 1'S CONTENT, not a
requirement of the engine -- and it only became visible as a fault when an
author wanted three Ring waves in a row and the whole package refused to
assemble. The assertion has been removed, and this is the evidence that
removing it was safe. Two source comments already cite this file by name:
tools/level_editor/validation_v6.py and tools/level_editor/test_v6_validation.py.

WHAT IS ACTUALLY AT RISK, and it is only one thing. A species is latched onto
the wave INSTANCE by waveStartNext and onto the OBJECT by waveSpawnMember, and
is never read relative to its neighbour -- so consecutive Rings cannot
interact at all. Consecutive DROPPERS can, because a Dropper's death is what
drops the token and two live at once would mean two tokens and two overlapping
encounters. The engine's answer is not an authoring rule but a runtime one:
"ONE LIVE DROPPER, EVER", enforced at the single instruction that commits a
species to an object, where a second Dropper is substituted with a Ring and
still flies its authored path.

So this file asks the machine three questions, for each species order:

    * does every authored trigger still fire?
    * do enemies actually spawn from them?
    * is more than one Dropper EVER alive at the same time?

THE ORDER IS IMPOSED ON THE RUNNING MACHINE, not by rebuilding a level. The
trigger table is package data in RAM at waveTrigSpecies, so the species column
is poked before the first trigger becomes due. That tests the RUNTIME claim --
which is the claim being made -- and it needs no second level package, no
engine change and no disturbance to the authored content on disk.

    python3 tests/test_species_order.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     step_n, check, report)

sym = symbols(SYM)

MAX_OBJECTS = 16
TYPE_ENEMY = 1
SPECIES_RING, SPECIES_DROPPER = 0, 8
PORT = 6577

# Long enough for the last authored trigger to become due and its wave to fly.
# The authored rows run to a few hundred coarse rows and a coarse row is eight
# displayed frames; the margin is for the flight after the last spawn.
MAX_FRAMES = 2300

# One dump covers enySpecies, logActive and objType -- they are neighbours by
# construction, so a frame costs two monitor round trips rather than four.
OBJ_BASE = sym["enySpecies"]
OBJ_SPAN = sym["objType"] + MAX_OBJECTS - OBJ_BASE


def species_letter(v):
    return "D" if v == SPECIES_DROPPER else "R"


def sample(mon):
    """Live enemies and their species, plus the director's own counters."""
    blk = rd(mon, OBJ_BASE, OBJ_SPAN)
    wv = rd(mon, sym["wvStarted"], 4)

    def field(name):
        o = sym[name] - OBJ_BASE
        return blk[o:o + MAX_OBJECTS]

    species, active, typ = field("enySpecies"), field("logActive"), field("objType")
    live = [species[s] for s in range(MAX_OBJECTS)
            if active[s] and typ[s] == TYPE_ENEMY]
    return {"droppers": sum(1 for s in live if s == SPECIES_DROPPER),
            "enemies": len(live),
            "started": wv[0],
            "spawned": wv[sym["wvSpawned"] - sym["wvStarted"]]}


def run_order(pattern, label):
    """Boot, impose `pattern` on the trigger table, fly the stage, and watch."""
    v = None
    try:
        # boot="exact" wakes at worldProgress 0, so every authored trigger is
        # still ahead and the species column can be rewritten before any of
        # them is read.
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon

        n = rd1(mon, sym["wvNextTrig"])
        assert n == 0, f"the director has already consumed {n} triggers"
        count = len(pattern)
        for i, ch in enumerate(pattern):
            poke(mon, sym["waveTrigSpecies"] + i,
                 SPECIES_DROPPER if ch == "D" else SPECIES_RING)
        got = "".join(species_letter(b) for b in
                      rd(mon, sym["waveTrigSpecies"], count))
        check(f"{label}: the trigger table reads back as {pattern}",
              got == pattern, got)

        set_bp(mon, sym["gameFrame"])
        frames = step_n(mon, sym["frameCounter"], MAX_FRAMES,
                        lambda: sample(mon))
    finally:
        if v:
            v.close()

    started = max(f["started"] for f in frames)
    spawned = max(f["spawned"] for f in frames)
    worst = max(f["droppers"] for f in frames)
    seen_enemies = max(f["enemies"] for f in frames)

    check(f"{label}: every authored trigger fired",
          started >= count, f"{started} of {count} started")
    check(f"{label}: enemies were actually created",
          spawned > 0 and seen_enemies > 0,
          f"{spawned} spawned, at most {seen_enemies} on screen at once")
    # THE ONE REAL CONSTRAINT, and the whole reason the alternation assertion
    # looked load-bearing. It is kept by the runtime, not by the authoring.
    check(f"{label}: never more than ONE Dropper alive at any sampled frame",
          worst <= 1, f"peak {worst}")
    return {"started": started, "spawned": spawned, "peak_droppers": worst,
            "peak_enemies": seen_enemies}


def main():
    # The authored trigger count, read from the level the repository actually
    # ships rather than assumed -- this file should not go stale the next time
    # the level grows.
    import json
    doc = json.loads((ROOT / "tools/level_editor/levels/level1/level.v6.json")
                     .read_text())
    count = len(doc["triggers"])
    authored = "".join("D" if t["species"] == "DROPPER" else "R"
                       for t in doc["triggers"])
    print(f"  the authored level has {count} triggers: {authored}")

    orders = (("R" * count, "all Rings"),
              ("D" * count, "all Droppers"),
              (authored, "as authored"))
    results = {}
    for pattern, label in orders:
        print(f"\n=== {label}: {pattern} ===", flush=True)
        results[label] = run_order(pattern, label)

    print()
    for label, r in results.items():
        print(f"  {label:16s} started {r['started']}  spawned {r['spawned']}  "
              f"peak enemies {r['peak_enemies']}  peak live Droppers "
              f"{r['peak_droppers']}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
