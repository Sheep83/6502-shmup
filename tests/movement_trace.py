#!/usr/bin/env python3
"""TEST-ONLY FIXTURE RECORDER — authoritative 6502 movement state, per frame.

NOT A TEST AND NOT PART OF `make test`. It proves nothing by itself: it runs
the REAL engine's REAL movement code and writes down what that code does, so
that tools/level_editor/test_movement_sim_engine.py can hold the Python
simulator to it.

NOTHING IS ADDED TO THE ENGINE. There is no diagnostic build, no test hook and
no production source change. The recorder drives the shipped routines through
the monitor:

    * the machine is STOPPED at a breakpoint for the whole session, so the
      game's own frame loop never runs and never touches what is being
      measured;
    * one pool slot is set up by hand and left with logActive = 0, so
      objectUpdateAll would ignore it even if the loop did run;
    * wmEnterStage and then wmTick are CALLED, once per recorded frame, by
      harness.call -- both are self-contained per constraint #4: they read the
      slot's own state and the stage table and nothing else;
    * the slot's authoritative state is dumped after every call.

WHY NOT WATCH A REAL WAVE INSTEAD. Two of Level 1's four triggers are DROPPER
appearances, and src/dropper.asm takes a Dropper off its wave's authored path
the instant it spawns -- so the `s` and `loop` programs are never flown by the
running game at all. Driving the interpreter directly is the only way to
ground all four production programs, and it also reaches the cases no authored
content contains (an ARC_MIRROR wrapping down past heading 0).

The complementary fixture -- spawn timing, formation offsets and the despawn
rules, watched in the free-running production loop with nothing called by
hand -- is tests/wave_formation_trace.py.

    python3 tests/movement_trace.py [out.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, poke, set_bp, call,  # noqa: E402
                     LAUNCHED_PIDS)

sym = symbols(SYM)

MAX_OBJECTS = 16
SLOT = 15                       # the pool allocates low-first, so the top slot
                                # is the one a live game is least likely to want
PORT = 6571

WM_BLOCK = sym["wmMode"]        # wmMode..wmAccY, nine arrays of MAX_OBJECTS
WM_FIELDS = ("mode", "stage", "phase", "timer", "steps", "vx", "vy",
             "acc_x", "acc_y")
POS_BASE = sym["logY"]          # logY, then logX, then logXHi

# Where a SYNTHETIC program may be written. The level package's movement pool
# is 52 bytes of authored records at LEVELPKG_MOVE ($f532); the wave
# definitions do not begin until $f632, so the bytes between are read by
# nothing. wmStage is one byte, so any offset 0..255 is reachable.
SYNTH_OFFSET = 64


def _s8(b):
    return b - 256 if b & 0x80 else b


class Recorder:
    def __init__(self, mon):
        self.mon = mon

    def read_state(self):
        """One slot's complete authoritative state, in two dumps.

        The movement arrays are contiguous by construction (src/movement.asm
        guards its block to end before the wave state at $77c0) and logY/logX/
        logXHi are neighbours, so this is two monitor round trips rather than
        twelve.
        """
        wm = rd(self.mon, WM_BLOCK, MAX_OBJECTS * len(WM_FIELDS))
        pos = rd(self.mon, POS_BASE, 0x50)
        out = {n: wm[i * MAX_OBJECTS + SLOT] for i, n in enumerate(WM_FIELDS)}
        out["vx"] = _s8(out["vx"])
        out["vy"] = _s8(out["vy"])
        out["y"] = pos[SLOT]
        out["x"] = pos[0x20 + SLOT] | (pos[0x40 + SLOT] << 8)
        return out

    def arm(self, *, stage_offset, x, y, heading):
        """Set the slot up exactly as waveSpawnMember does, then call the same
        wmEnterStage it calls. Every movement field is written, including the
        ones the engine relies on objectZeroSlot having cleared: a recorder
        that inherited a previous case's timer would measure the wrong path."""
        poke(self.mon, sym["logActive"] + SLOT, 0)   # invisible to the loop
        poke(self.mon, sym["objType"] + SLOT, 0)
        poke(self.mon, sym["logX"] + SLOT, x & 0xFF)
        poke(self.mon, sym["logXHi"] + SLOT, (x >> 8) & 0xFF)
        poke(self.mon, sym["logY"] + SLOT, y & 0xFF)
        for i, name in enumerate(WM_FIELDS):
            poke(self.mon, WM_BLOCK + i * MAX_OBJECTS + SLOT, 0)
        poke(self.mon, sym["wmPhase"] + SLOT, heading)      # launch heading
        poke(self.mon, sym["wmStage"] + SLOT, stage_offset)
        call(self.mon, sym, "wmEnterStage", x=SLOT)

    def fly(self, frames):
        out = [self.read_state()]
        for _ in range(1, frames):
            call(self.mon, sym, "wmTick", x=SLOT)
            out.append(self.read_state())
        return out

    def write_program(self, offset, records):
        """Poke a synthetic program into the unused tail of the movement pool."""
        for i, rec in enumerate(records):
            for b in range(4):
                poke(self.mon, sym["waveStageTable"] + offset + 4 * i + b,
                     rec[b] & 0xFF)

    def read_program_bytes(self, offset, count):
        return rd(self.mon, sym["waveStageTable"] + offset, count)


# --- the cases ------------------------------------------------------------
# The four production programs are flown from their OWN wave definition's
# member-0 start position and launch heading, so each trace is directly
# comparable to a simulated member. The offsets are the authored pool's, and
# the recorder reads the bytes back out of the machine and stores them in the
# fixture -- so a fixture can never describe a program the engine did not
# actually have loaded.
PRODUCTION = [
    # name,      stage offset, start x, start y, launch heading, frames
    ("sweep",    0,   0,  64,  0, 200),
    ("s",        12,  90, 30, 12, 200),
    ("linger",   24, 120, 30, 10, 230),
    ("loop",     40,  70, 30,  8, 320),
]

WM_STRAIGHT, WM_ARC, WM_ARC_MIRROR, WM_EXIT, WM_HOLD = 0, 1, 2, 3, 4
CONT = 0xFF

# What the authored content does NOT contain, and therefore what the
# production traces cannot prove.
SYNTHETIC = [
    # An ARC_MIRROR stepping DOWN past heading 0 and wrapping to 63. Level 1's
    # only mirrored arc starts at heading 12 and turns 12 steps, so it stops
    # exactly ON zero and never crosses it.
    ("mirror_wrap_down", [(WM_ARC_MIRROR, 20, 2, 4), (WM_EXIT, 0, 0, 0)],
     200, 100, 0, 120),
    # An ARC wrapping UP past 63 to 0 from a heading very close to the wrap,
    # which `loop` reaches only after 56 steps of travel.
    ("arc_wrap_up", [(WM_ARC, 12, 3, 60), (WM_EXIT, 0, 0, 0)],
     200, 100, 0, 120),
    # An EXPLICIT entry heading that CONTRADICTS the heading the object is
    # already carrying -- the case the record format exists for. A straight
    # leg first, so the arc is entered from a stage that never touches wmPhase.
    ("explicit_after_straight",
     [(WM_STRAIGHT, 20, 6, 0), (WM_ARC, 16, 4, 48), (WM_EXIT, 0, 0, 0)],
     100, 120, 30, 140),
    # CONT twice in a row, so the second arc inherits a heading the first arc
    # produced rather than one the wave launched with.
    ("cont_chain",
     [(WM_ARC, 8, 3, 20), (WM_ARC_MIRROR, 8, 3, CONT), (WM_ARC, 8, 3, CONT),
      (WM_EXIT, 0, 0, 0)],
     150, 100, 0, 140),
    # A HOLD with zero velocity on both axes: the loiter, which must not move
    # at all and must still hand on when its timer runs out.
    ("hold_still",
     [(WM_STRAIGHT, 10, 4, 4), (WM_HOLD, 30, 0, 0), (WM_ARC, 8, 4, 16),
      (WM_EXIT, 0, 0, 0)],
     150, 100, 0, 110),
    # A NEGATIVE velocity on both axes, to exercise the arithmetic shift and
    # the nine-bit borrow that a positive-only trace never touches.
    ("negative_velocity",
     [(WM_STRAIGHT, 60, -7, -3), (WM_EXIT, 0, 0, 0)],
     300, 200, 0, 80),
]


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "tools/level_editor/fixtures/movement_engine_trace.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    v = None
    fixture = {"source": "6502 engine via VICE monitor, wmEnterStage + wmTick",
               "slot": SLOT, "cases": []}
    try:
        v = Vice(PORT, PRG)
        mon = v.mon
        # STOP THE MACHINE AND LEAVE IT STOPPED. Everything below is a called
        # routine; the game's own frame loop never advances again, so nothing
        # can race the slot being measured.
        bp = set_bp(mon, sym["gameFrame"])
        mon.cmd("x")
        mon.cmd(f"delete {bp}")

        rec = Recorder(mon)

        # The heading table, read out of the running machine. It is generated
        # at assembly time from cos/sin, so this is the one place its actual
        # bytes can be compared with the simulator's copy.
        hx = rd(mon, sym["wmHeadVX"], 64)
        hy = rd(mon, sym["wmHeadVY"], 64)
        fixture["head_vx"] = [_s8(b) for b in hx]
        fixture["head_vy"] = [_s8(b) for b in hy]

        for name, off, x, y, head, frames in PRODUCTION:
            print(f"  [trace] production {name} ({frames} frames)", flush=True)
            n = 4 * (len(rd(mon, sym["waveStageTable"] + off, 4)) // 4)
            rec.arm(stage_offset=off, x=x, y=y, heading=head)
            trace = rec.fly(frames)
            fixture["cases"].append({
                "name": name, "kind": "production", "stage_offset": off,
                "start_x": x, "start_y": y, "heading": head,
                "program_bytes": rec.read_program_bytes(off, 16),
                "frames": trace})

        for name, records, x, y, head, frames in SYNTHETIC:
            print(f"  [trace] synthetic {name} ({frames} frames)", flush=True)
            rec.write_program(SYNTH_OFFSET, records)
            rec.arm(stage_offset=SYNTH_OFFSET, x=x, y=y, heading=head)
            trace = rec.fly(frames)
            fixture["cases"].append({
                "name": name, "kind": "synthetic", "stage_offset": SYNTH_OFFSET,
                "start_x": x, "start_y": y, "heading": head,
                "records": [list(r) for r in records],
                "program_bytes": rec.read_program_bytes(
                    SYNTH_OFFSET, 4 * len(records)),
                "frames": trace})
    finally:
        if v:
            v.close()

    out_path.write_text(json.dumps(fixture, indent=1) + "\n")
    print(f"\n  wrote {out_path} "
          f"({len(fixture['cases'])} cases, "
          f"{sum(len(c['frames']) for c in fixture['cases'])} frames)")
    print(f"  launched and reaped: {LAUNCHED_PIDS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
