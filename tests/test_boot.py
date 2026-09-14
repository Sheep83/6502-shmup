#!/usr/bin/env python3
"""Boot smoke — the fastest possible "is the game alive" check.

What this proves
----------------
* the build artefacts exist (make build already ran; this checks it worked);
* the PRG autostarts into the real production loop, not a fixture or a halt;
* the frame counter is advancing under warp, so the main thread is not stuck
  in a fault, an infinite wait, or a crashed IRQ;
* gameOverrun is zero from the very first frames -- a machine that cannot even
  boot cleanly has no business running anything heavier.

What this does NOT prove
-------------------------
Anything about gameplay. See test_production.py and test_turret_regression.py
for that. This file exists to fail fast and cheaply when the build itself is
broken, before spending time on the rest of the gate.

One VICE launch, well under ten seconds of wall clock.
"""
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import PRG, SYM, symbols, Vice, rd1, free_run, check, report

def main():
    print("=== boot smoke ===")
    check("build/shmup.prg exists", PRG.is_file())
    check("build/main.vs exists", SYM.is_file())
    if not (PRG.is_file() and SYM.is_file()):
        return report(__name__)
    sym = symbols(SYM)

    v = None
    try:
        v = Vice(6650, PRG, warp=True)
        mon = v.mon
        f0 = rd1(mon, sym["frameCounter"]), rd1(mon, sym["frameCounter"] + 1)
        ok = free_run(mon, sym["frameCounter"], 2)
        check("the machine free-runs (frame counter genuinely advances)", ok)
        f1 = rd1(mon, sym["frameCounter"]), rd1(mon, sym["frameCounter"] + 1)
        moved = (f0[0] | f0[1] << 8) != (f1[0] | f1[1] << 8)
        check("the frame counter moved over two seconds of warp", moved,
              f"{f0} -> {f1}")
        overrun = rd1(mon, sym["gameOverrun"])
        check("gameOverrun is zero at boot", overrun == 0, str(overrun))
    finally:
        if v: v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
