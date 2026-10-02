#!/usr/bin/env python3
"""THE AUTHORED TURRET COLUMN AND ITS SPRITE X MUST AGREE, at every legal column.

A turret's authored column is derived into TWO representations and they have
different consumers:

    turretCol            the DRAWING path -- turretOverlayRow writes the body's
                         character cells at this column, and turretPaintTick
                         paints its colour there
    turretXLo/turretXHi  COMBAT and the BOLT -- traceTurretRay tests the
                         player's nine-bit hitscan ray against this, and
                         turretFireTick launches the hostile bolt from it

If they disagree, a turret is drawn in one place and fought in another: it
appears perfectly, absorbs no damage where it is, and fires from somewhere
else on the display. That is what src/turrets.asm's turretBuildTables did for
every column from 32 up, because three bare `asl`s dropped the carry that IS
the ninth bit of 8 * col -- see the note beside the derivation. Level 1 and
level 3 author no column above 29 and never showed it; level 2 authors four
turrets at column 33 and all four were inert.

WHY THIS SWEEPS THE RANGE INSTEAD OF CHECKING A LEVEL. The fault was invisible
in the only content that existed, so asserting today's level 2 would not have
caught it and asserting tomorrow's will not catch the next one. Campaign
content is authored and mutable; what is NOT mutable is that every column the
package build is willing to emit must derive a correct sprite X. So this pokes
one package slot across the WHOLE supported column range and rebuilds the
tables, and asserts nothing whatever about any level's turret count, positions
or layout.

It runs on whatever level the boot loads, because the invariant is not a
property of a level.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd1, poke, set_bp,  # noqa: E402
                     step_n, call, LAUNCHED_PIDS)

sym = symbols(SYM)

# src/levelpkg.asm. The package's turret columns start here and the engine's
# own authoring guard refuses col + TRT_BODY_W > SCREEN_COLS.
LEVELPKG_TRTCOL = 0xFF7A
LEVELPKG_TRTN = 0xFF79
SCREEN_COLS, TRT_BODY_W = 40, 2
MAX_COL = SCREEN_COLS - TRT_BODY_W          # 38
# src/turrets.asm: the body's left edge in sprite X.
X_ORIGIN, CHAR_W = 24, 8

fails = []


def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def main():
    v = Vice(6766, PRG, warp=True, start_game=True, boot="fast")
    mon = v.mon
    try:
        mon.cmd("del")
        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 3, lambda: None)

        # THE PACKAGE LIVES UNDER THE KERNAL and turretBuildTables reads it
        # there, so both this test's pokes and that call need $e000-$ffff to be
        # RAM. The engine already runs that way -- src/main.asm banks the KERNAL
        # out before installRenderer -- and this asserts it rather than assuming
        # it, because every read below would silently return ROM otherwise.
        check("the engine runs with the KERNAL banked out, so the resident "
              "package is readable", rd1(mon, 0x01) == 0x35,
              f"$01 = ${rd1(mon, 0x01):02x}")
        trtn = rd1(mon, LEVELPKG_TRTN)
        check("the resident package declares at least one turret slot to drive",
              trtn >= 1, f"LEVELPKG_TRTN = {trtn}")
        if fails:
            return

        saved = rd1(mon, LEVELPKG_TRTCOL)

        # ---- the sweep -----------------------------------------------------
        # Slot 0 is the vehicle; the column is the variable. Every legal column
        # is checked, not a sample, because the fault was a single dropped bit
        # that only appears once 8 * col crosses 256.
        bad, crossing = [], []
        for col in range(MAX_COL + 1):
            poke(mon, LEVELPKG_TRTCOL, col)
            call(mon, sym, "turretBuildTables")
            got_col = rd1(mon, sym["turretCol"])
            lo = rd1(mon, sym["turretXLo"])
            hi = rd1(mon, sym["turretXHi"])
            got_x = lo | (hi << 8)
            want_x = X_ORIGIN + CHAR_W * col
            if got_col != col or got_x != want_x:
                bad.append((col, got_col, want_x, got_x))
            if 28 <= col <= 34:
                crossing.append((col, want_x, got_x))

        check(f"every legal authored column 0..{MAX_COL} derives sprite X = "
              f"{X_ORIGIN} + {CHAR_W} * col",
              not bad,
              "" if not bad else
              "; ".join(f"col {c}: want X {wx}, got {gx}"
                        f"{'' if gc == c else f' (turretCol {gc})'}"
                        for c, gc, wx, gx in bad[:6])
              + (f" ... and {len(bad) - 6} more" if len(bad) > 6 else ""))

        # THE BOUNDARY, PRINTED WHETHER IT PASSES OR NOT. 8 * 32 is 256, so
        # this is where the ninth bit first has to come from the multiply rather
        # than from the + 24, and it is the exact step the old code got wrong.
        print("       the 256-pixel boundary, where the ninth bit changes hands:")
        for col, want_x, got_x in crossing:
            print(f"         col {col:2d}  want X {want_x:3d}  got {got_x:3d}  "
                  f"{'ok' if want_x == got_x else 'WRONG'}")

        # ---- the two representations describe the same cell -----------------
        # Stated as its own assertion because it is the property the two
        # consumers actually depend on: the drawing path and the combat path
        # must be talking about one turret.
        mism = []
        for col in (0, 1, 17, 21, 29, 31, 32, 33, 37, MAX_COL):
            poke(mon, LEVELPKG_TRTCOL, col)
            call(mon, sym, "turretBuildTables")
            drawn = rd1(mon, sym["turretCol"])
            fought = rd1(mon, sym["turretXLo"]) | (rd1(mon, sym["turretXHi"]) << 8)
            if X_ORIGIN + CHAR_W * drawn != fought:
                mism.append((col, drawn, fought))
        check("the column the body is DRAWN at and the X it is FOUGHT at are "
              "the same cell", not mism,
              "; ".join(f"col {c}: drawn at {d} (X {X_ORIGIN + CHAR_W * d}), "
                        f"fought at X {f}" for c, d, f in mism[:6]))

        # ---- the ninth bit is a bit, not a byte ----------------------------
        # turretXHi feeds $d010 through one bit per sprite and ebSpawnXHi the
        # same way, so a derived X must fit the nine bits a VIC sprite has.
        wide = []
        for col in range(MAX_COL + 1):
            poke(mon, LEVELPKG_TRTCOL, col)
            call(mon, sym, "turretBuildTables")
            hi = rd1(mon, sym["turretXHi"])
            if hi > 1:
                wide.append((col, hi))
        check("no legal column derives an X wider than the nine bits a VIC "
              "sprite position has", not wide,
              "; ".join(f"col {c}: turretXHi = {h}" for c, h in wide[:6]))

        poke(mon, LEVELPKG_TRTCOL, saved)
        call(mon, sym, "turretBuildTables")
        check("the package slot this test borrowed was put back",
              rd1(mon, sym["turretCol"]) == saved,
              f"col {rd1(mon, sym['turretCol'])}, was {saved}")
    finally:
        mon.cmd("del")
        v.close()

    print(f"\n  VICE launched and reaped: {LAUNCHED_PIDS}")
    print("\n" + (f"=== {len(fails)} FAILURES: " + "; ".join(fails) + " ==="
                  if fails else "=== ALL PASS ==="))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    print("=== authored turret column -> sprite X ===")
    main()
