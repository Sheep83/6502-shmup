#!/usr/bin/env python3
"""regenTick rebuilds the back page by COPYING, and these are the ways that breaks.

    python3 tests/test_regen_page_shift.py

A coarse scroll step moves the world by exactly one character row, so the page
being rebuilt is the displayed one shifted down a row:

    backRow[r] == frontRow[r - 1]      for r = 1 .. SCREEN_ROWS-1

src/scroll.asm exploits that: only row 0 is decoded from the metatile map, and
the other twenty-four are copied out of the other page. That is worth about 1,800
cycles a frame, and it moves the worst measured frame of the stripped stress
encounter from 20,036 cycles -- past the 19,656 a PAL frame has -- to 17,446.

WHAT THIS FILE IS FOR. The equality above is now true BY CONSTRUCTION, so
asserting it would prove nothing at all. What can still go wrong is the copy
carrying content that should have changed, and these are the two cases where the
screen is not simply the previous screen shifted:

  1. A TURRET DESTROYED MID-CYCLE. The overlay is not a function of the metatile
     map alone -- it depends on turretAlive, which changes in time. If the repair
     in src/turrets.asm did not reach both pages, the copy would hand the corpse
     back and forth between them, descending one row per coarse step, for ever.
     That is the failure this optimisation risks, so it is the one pinned here.

  2. THE STAGE FOLD. regenTopRow counts down and folds 0 -> STAGE_ROWS-1, so the
     window's SOURCE jumps from one end of the map to the other while the screen
     still moves by a single row.

NO FROZEN CAMPAIGN BYTES. Both checks are self-referential: the turret case
asserts an absence, and the fold case compares the stage against ITSELF one lap
later, using the engine's own stageHold diagnostic to keep scrolling. Re-authoring
level 1 cannot make this file wrong.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     check, check_all, report, stage_geometry, LAUNCHED_PIDS)

sym = symbols(SYM)
PORT = 6793
COLS, ROWS, TURRETS = 40, 25, 8
_, STAGE_ROWS, _ = stage_geometry()       # from the engine, not a copy here
PAGE_HI = {0x04: 0x28, 0x28: 0x04}
J_FIRE = 0xEF


def asm_const(name, path="src/turrets.asm"):
    """The value of a `.const NAME = n` in an engine source file."""
    txt = (ROOT / path).read_text(encoding="utf-8")
    m = re.search(rf"^\s*\.const\s+{re.escape(name)}\s*=\s*(\d+)", txt, re.M)
    if not m:
        raise SystemExit(f"{name} not found in {path}")
    return int(m.group(1))


# THE BODY'S CHARACTER CODES, FROM THE ENGINE'S OWN CONSTANTS. turretOverlayRow
# writes TURRET_GLYPH_BASE..+SPAN-1 and nothing else, and src/turrets.asm:63
# asserts at build time that the range starts ABOVE every terrain glyph -- so a
# cell holding one of these codes is a turret body and can be nothing else.
#
# This is deliberately NOT derived by watching which characters disappear when a
# turret dies. An earlier version of this file did exactly that, and the result
# was circular: it used the repair to identify the body and then checked that the
# repair had removed the body, so withholding the repair made the test pass by
# finding no body to look for. The negative control caught it.
GLYPH_BASE = asm_const("TURRET_GLYPH_BASE")
GLYPH_SPAN = asm_const("TURRET_GLYPH_SPAN")
BODY = set(range(GLYPH_BASE, GLYPH_BASE + GLYPH_SPAN))
BODY_W = asm_const("LEVELPKG_TRT_BODY_W", "src/levelpkg.asm")


def rtop(mon):
    return rd1(mon, sym["regenTopRowLo"]) | (rd1(mon, sym["regenTopRowHi"]) << 8)


def page(mon, hi):
    return [list(rd(mon, (hi << 8) + r * COLS, COLS)) for r in range(ROWS)]


def complete(mon):
    """True when the back page has been fully rebuilt and not yet flipped."""
    return rd1(mon, sym["regenRow"]) >= ROWS


# ---------------------------------------------------------------------------
# 1. A TURRET DESTROYED PART WAY THROUGH A REGENERATION CYCLE
# ---------------------------------------------------------------------------
def turret_kill(mon, kill_phase, laps=14):
    """Destroy a visible turret at regenRow == kill_phase; watch for a corpse.

    The kill is driven exactly as turretDamage's !destroy path does it
    (src/turrets.asm:1593) INCLUDING the trtDeadPending bit at line 1617, which
    is what the page repair waits on. Omitting that bit leaves the pages never
    repaired and produces a corpse in ANY build, copying or decoding; the
    negative control for this test is precisely that omission, and it must fail.

    Returns, per coarse step, how many body cells each page holds and how many
    turrets are still standing. A standing turret accounts for TURRET_GLYPH_SPAN
    cells per page, so the arithmetic below is exact rather than approximate.
    """
    killed = None
    saw_body_alive = 0
    sightings = []
    dead_cols = set()
    rival = []
    for _ in range(9000):
        mon.cmd("x")
        if killed is None:
            vis = rd1(mon, sym["trtVisibleMask"])
            if not vis or rd1(mon, sym["regenRow"]) != kill_phase:
                continue
            alive = rd(mon, sym["turretAlive"], TURRETS)
            idx = next((i for i in range(TURRETS)
                        if alive[i] and (vis >> i) & 1), None)
            if idx is None:
                continue
            # The body IS on screen before the kill: otherwise a test that counts
            # body cells afterwards proves nothing.
            ph = rd1(mon, sym["regenPageHi"])
            saw_body_alive = sum(1 for row in page(mon, PAGE_HI[ph])
                                 for c in row if c in BODY)
            poke(mon, sym["turretHealth"] + idx, 0)
            poke(mon, sym["turretHitTimer"] + idx, 0)
            poke(mon, sym["turretAlive"] + idx, 0)
            poke(mon, sym["trtRepaint"], (rd1(mon, sym["trtRepaint"]) + 1) & 0xFF)
            poke(mon, sym["trtKills"], (rd1(mon, sym["trtKills"]) + 1) & 0xFF)
            poke(mon, sym["trtDeadPending"],
                 rd1(mon, sym["trtDeadPending"]) | (1 << idx))
            killed = idx
            # ITS OWN COLUMNS ARE THE SIGNATURE. Counting body cells against the
            # number of turrets still alive is useless -- seven can be alive with
            # only one anywhere near the aperture -- so the question asked below
            # is the precise one: does THIS turret's body still appear in THIS
            # turret's columns after it has been destroyed?
            cols = rd(mon, sym["turretCol"], TURRETS)
            dead_cols = set(range(cols[idx], cols[idx] + BODY_W))
            rival = [j for j in range(TURRETS)
                     if j != idx and alive[j]
                     and set(range(cols[j], cols[j] + BODY_W)) & dead_cols]
            continue

        if not complete(mon):
            continue
        here = rtop(mon)
        if sightings and sightings[-1]["rtop"] == here:
            continue
        ph = rd1(mon, sym["regenPageHi"])
        standing = sum(rd(mon, sym["turretAlive"], TURRETS))
        cells = {}
        for which, hi in (("back", ph), ("front", PAGE_HI[ph])):
            cells[which] = [(r, c) for r, row in enumerate(page(mon, hi))
                            for c, ch in enumerate(row) if ch in BODY]
        sightings.append({"rtop": here, "standing": standing,
                          "back": [x for x in cells["back"]
                                   if x[1] in dead_cols],
                          "front": [x for x in cells["front"]
                                    if x[1] in dead_cols],
                          "any_back": len(cells["back"]),
                          "any_front": len(cells["front"])})
        if len(sightings) >= laps:
            break
    return killed, saw_body_alive, sightings, dead_cols, rival


# ---------------------------------------------------------------------------
# 2. THE STAGE FOLD
# ---------------------------------------------------------------------------
def fold_laps(mon, near=3):
    """Pages either side of the fold, on two successive laps of the stage.

    The stage repeats every STAGE_ROWS rows, so the same world row must produce
    the same page a lap later. That makes the stage its own reference, and it is
    the fold itself -- 0 -> STAGE_ROWS-1 -- that the two laps straddle.
    """
    # Rows on BOTH sides of the fold, and THREE lap buckets rather than two.
    # With two, the rows just after the fold are only ever seen once -- they land
    # in the second bucket and there is no third to compare them with -- so the
    # half of the fold that actually jumps goes unchecked. The third bucket needs
    # only the first few coarse steps of a lap, not a whole one.
    want = [r for r in range(near, -1, -1)] + \
           [STAGE_ROWS - 1 - i for i in range(near)]
    laps = [{}, {}, {}]
    lap = 0
    last = None
    for _ in range(80000):
        mon.cmd("x")
        r = rtop(mon)
        if last is not None and r > last + 100:
            lap += 1                     # the fold: a new lap of the stage
        last = r
        if lap >= len(laps):
            break
        if r not in want or r in laps[lap] or not complete(mon):
            continue
        laps[lap][r] = (rd1(mon, sym["regenPageHi"]),
                        page(mon, rd1(mon, sym["regenPageHi"])))
        if lap == 2 and len([x for x in want if x in laps[2]]) >= near:
            break
    return want, laps


# ---------------------------------------------------------------------------
# THE SELF-MODIFIED ADDRESSES, CHECKED STATICALLY
# ---------------------------------------------------------------------------
# DELIBERATELY AN IMPLEMENTATION CHECK -- the only one in this file, and it is
# here because this particular mistake has already been made. The copy is
# unrolled, so it carries four `lda abs,y` / `sta abs,y` pairs whose operands the
# setup patches at run time: sixteen bytes. An intermediate version of the
# routine patched two of eight operands and left the other six reading and
# writing $ffff.
#
# The runtime sections below would catch that too, because the pages would be
# garbage -- but this catches it in milliseconds and names the operand that was
# missed, and it is exactly what a future fifth unrolled pair would reintroduce
# without anyone noticing.
#
# Decoded out of the BUILT BINARY rather than parsed from the source, so it sees
# what the assembler actually emitted.
def patch_sites():
    raw = (ROOT / "build" / "shmup.prg").read_bytes()
    load = raw[0] | (raw[1] << 8)
    start, stop = sym["copyRowsFromFront"], sym["rgLastByte"]
    code = raw[start - load + 2: stop - load + 2]
    # Only the opcodes this routine uses. Anything else means it has been
    # restructured, and then this check wants revisiting rather than trusting.
    OPS = {0xAE: 3, 0xAD: 3, 0xBD: 3, 0x8D: 3, 0x18: 1, 0x6D: 3, 0x7D: 3,
           0xCA: 1, 0x49: 2, 0xBC: 3, 0xB9: 3, 0x99: 3, 0x88: 1, 0xC0: 2,
           0xD0: 2, 0x60: 1}
    operands, stores, pairs, unknown = [], [], 0, None
    i, pc = 0, start
    while i < len(code):
        op = code[i]
        if op not in OPS:
            unknown = (pc, op)
            break
        if op in (0xB9, 0x99):              # lda abs,y / sta abs,y: a copy
            operands += [pc + 1, pc + 2]
            pairs += op == 0xB9
        if op == 0x8D:                      # sta abs: a patch
            stores.append(code[i + 2] << 8 | code[i + 1])
        i += OPS[op]
        pc += OPS[op]
    return sorted(operands), sorted(stores), pairs, unknown



def main():
    operands, stores, pairs, unknown = patch_sites()
    print("=== the copy's self-modified addresses, decoded from the binary ===")
    check("the routine decodes cleanly, so this check is reading real code",
          unknown is None,
          "every opcode recognised" if unknown is None else
          f"unknown opcode ${unknown[1]:02x} at ${unknown[0]:04x} -- the routine "
          f"has been restructured and this check needs revisiting")
    check("the copy is unrolled, so there is more than one operand to patch",
          pairs > 1, f"{pairs} lda/sta pairs, {len(operands)} operand bytes")
    check("EVERY operand byte of EVERY unrolled copy is written by the setup -- "
          "the mistake that leaves an unrolled copy addressing $ffff",
          operands == stores and bool(operands),
          f"{len(stores)} stores cover all {len(operands)} operand bytes"
          if operands == stores else
          f"unpatched {[hex(a) for a in sorted(set(operands) - set(stores))]}, "
          f"stray {[hex(a) for a in sorted(set(stores) - set(operands))]}")

    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["publishFrame"])

        # --- 1. the turret corpse -------------------------------------------
        print("=== a turret destroyed part way through a regeneration cycle ===")
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], J_FIRE)
        idx, alive_cells, sightings, dead_cols, rival = turret_kill(
            mon, kill_phase=12)
        check("a visible turret was found and destroyed mid-cycle",
              idx is not None, f"turret {idx}")
        check("the body was ON SCREEN before the kill, so counting body cells "
              "afterwards means something",
              alive_cells >= GLYPH_SPAN,
              f"{alive_cells} cells holding glyphs {sorted(BODY)} while standing")
        check("the cycle was then followed for several coarse steps",
              len(sightings) >= 8, f"{len(sightings)} coarse steps")
        check("no OTHER standing turret shares the dead one's columns, so a "
              "body glyph there can only be the corpse",
              not rival, f"columns {sorted(dead_cols)}; "
                         f"rivals {rival if rival else 'none'}")
        # A CORPSE DESCENDS ONE ROW PER COARSE STEP AND NEVER LEAVES. That is
        # what a copying regenTick risks: the two pages hand the body back and
        # forth, each handing it on one row lower, for ever.
        check_all("THE DEAD TURRET'S COLUMNS HOLD NO BODY GLYPH IN EITHER PAGE, "
                  "and keep holding none -- the failure a copying regenTick risks",
                  sightings,
                  lambda s: not s["back"] and not s["front"],
                  what="coarse steps",
                  detail=lambda items, bad:
                      f"{len(items)} coarse steps; columns {sorted(dead_cols)} "
                      f"clear in both pages throughout"
                      if not bad else
                      f"corpse at world row {bad[0]['rtop']}: back cells "
                      f"{bad[0]['back']} front cells {bad[0]['front']} "
                      f"(descending one row per step)")

        # --- 2. the fold ----------------------------------------------------
        print("\n=== the stage fold, with the stage as its own reference ===")
        poke(mon, sym["joyState"], 0xFF)
        poke(mon, sym["joyHold"], 0)
        poke(mon, sym["stageHold"], 1)          # the engine's endless stage
        want, laps = fold_laps(mon)
        # Every row seen on two CONSECUTIVE laps, which covers the rows before
        # the fold (laps 0 and 1) and the rows after it (laps 1 and 2).
        pairs = [(r, i) for r in want for i in (0, 1)
                 if r in laps[i] and r in laps[i + 1]]
        both = [r for r, _ in pairs]
        check("the stage was driven through the fold and round again, with "
              "rows compared on BOTH sides of it",
              len(both) >= 5 and any(r >= STAGE_ROWS - 4 for r in both)
              and any(r <= 3 for r in both),
              f"world rows compared: {both}")
        check_all("every page either side of the fold is IDENTICAL a lap later",
                  pairs,
                  lambda ri: laps[ri[1]][ri[0]][1] == laps[ri[1] + 1][ri[0]][1],
                  what="world rows",
                  detail=lambda items, bad:
                      f"{len(items)} world rows, all {ROWS} screen rows equal "
                      f"a lap later: {both}" if not bad else
                      f"world row {bad[0][0]} (laps {bad[0][1]}/{bad[0][1]+1}): "
                      f"screen rows differing "
                      f"{[i for i in range(ROWS) if laps[bad[0][1]][bad[0][0]][1][i] != laps[bad[0][1]+1][bad[0][0]][1][i]]}")
        check_all("and lands on the same page of the double buffer",
                  pairs,
                  lambda ri: laps[ri[1]][ri[0]][0] == laps[ri[1] + 1][ri[0]][0],
                  what="world rows",
                  detail=lambda items, bad:
                      f"{len(items)} world rows on the same page both laps"
                      if not bad else
                      f"world row {bad[0][0]}: "
                      f"{laps[bad[0][1]][bad[0][0]][0]:#04x} then "
                      f"{laps[bad[0][1]+1][bad[0][0]][0]:#04x}")
        mon.cmd("delete")
    finally:
        if v:
            v.close()
    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
