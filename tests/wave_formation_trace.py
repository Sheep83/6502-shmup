#!/usr/bin/env python3
"""TEST-ONLY FIXTURE RECORDER — a whole ordinary wave in the production loop.

NOT A TEST. The companion to tests/movement_trace.py, and deliberately the
opposite kind of evidence: nothing is called by hand here. The game boots to
worldProgress 0, the director arms its own triggers, waveSpawnMember places
its own formations and enemyTick applies its own despawn rules, and this file
only watches.

WHAT IT GROUNDS that the direct-drive fixture cannot:

    * the spawn INTERVAL and the frame the first member goes out on;
    * the formation FAN-OUT -- startX + index*xStep in nine bits and
      startY + index*yStep in eight;
    * that a new enemy does NOT move on the frame it is spawned (waveTick
      runs after objectUpdateAll, so its first wmTick is a frame away);
    * the exact frame src/enemy.asm's despawn rules free each member.

ONLY THE RING WAVES ARE USABLE. Level 1's other two triggers are DROPPER
appearances and src/dropper.asm takes those off the authored path
immediately, so they are recorded but marked, not compared.

The sample point is the breakpoint at gameFrame, which is the top of a frame
and therefore the settled END of the one before it -- after objectUpdateAll
moved everything and after waveTick spawned anything new. That is the same
instant tests/test_flight_paths.py samples.

    python3 tests/wave_formation_trace.py [out.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, set_bp, step_n,  # noqa: E402
                     LAUNCHED_PIDS)

sym = symbols(SYM)

MAX_OBJECTS = 16
WAVE_SLOTS = 2
TYPE_ENEMY = 1
PORT = 6573
MAX_FRAMES = 1150       # row 90 is ~720 frames in at eight frames a coarse
                        # row, and `linger` flies for ~260 more


def sample(mon):
    """One frame, in three dumps.

    The arrays are neighbours by construction, so each dump spans several of
    them and the fields are sliced out. A round trip per field would be four
    times the runtime for the same numbers.
    """
    # ONE DUMP FROM wmMode TO wvIndex. The movement arrays and the wave
    # instance state are neighbours by construction (src/movement.asm guards
    # its block to end before src/waves.asm's at $77c0), so the span reaches
    # wvIndex -- which is what says WHICH MEMBER an instance just sent, and is
    # therefore how a spawn is attributed to an authored member at all.
    wm = rd(mon, sym["wmMode"],
            sym["wvIndex"] + WAVE_SLOTS - sym["wmMode"])
    pos = rd(mon, sym["logY"], 0x50)
    obj = rd(mon, sym["logActive"], 0x60)

    def wmf(name):
        o = sym[name] - sym["wmMode"]
        return wm[o: o + MAX_OBJECTS]

    def wvf(name):
        o = sym[name] - sym["wmMode"]
        return wm[o: o + WAVE_SLOTS]

    def objf(name):
        o = sym[name] - sym["logActive"]
        return obj[o: o + MAX_OBJECTS]

    active, typ, hp = objf("logActive"), objf("objType"), objf("objHP")
    mode, stage, phase = wmf("wmMode"), wmf("wmStage"), wmf("wmPhase")
    enemies = {}
    for s in range(MAX_OBJECTS):
        if active[s] and typ[s] == TYPE_ENEMY:
            enemies[s] = {
                "x": pos[0x20 + s] | (pos[0x40 + s] << 8),
                "y": pos[s], "hp": hp[s], "mode": mode[s],
                "stage": stage[s], "phase": phase[s]}
    return {"enemies": enemies,
            "wvActive": wvf("wvActive"), "wvDef": wvf("wvDef"),
            "wvIndex": wvf("wvIndex"), "wvLeft": wvf("wvLeft"),
            "wvTimer": wvf("wvTimer")}


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "tools/level_editor/fixtures/wave_formation_trace.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    v = None
    try:
        # boot="exact" wakes at worldProgress 0, so all four authored triggers
        # are still ahead. A "fast" boot lands hundreds of rows in, where the
        # director is already exhausted and there is nothing to watch.
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        print(f"  [trace] stepping {MAX_FRAMES} frames", flush=True)
        frames = step_n(mon, sym["frameCounter"], MAX_FRAMES,
                        lambda: sample(mon))
    finally:
        if v:
            v.close()

    fixture = {"source": "6502 engine, free-running production loop, "
                         "sampled at the gameFrame breakpoint",
               "frames": frames}
    out_path.write_text(json.dumps(fixture, indent=1) + "\n")
    spawns = sum(1 for i in range(1, len(frames))
                 for s in frames[i]["enemies"]
                 if s not in frames[i - 1]["enemies"])
    print(f"\n  wrote {out_path} ({len(frames)} frames, {spawns} enemy spawns)")
    print(f"  launched and reaped: {LAUNCHED_PIDS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
