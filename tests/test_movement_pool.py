#!/usr/bin/env python3
"""Wave Contract Stage 2: deterministic ARC entry, and the externalised pool.

What this proves
----------------
* an ARC entered after STRAIGHT, after HOLD, or after another ARC begins on the
  heading its own record names -- never on whatever the object happened to carry;
* a deliberately corrupted wmPhase cannot alter that transition;
* WM_HEAD_CONT is the one value that DOES inherit, and does so exactly;
* WM_ARC_MIRROR obeys the same rule and turns the other way;
* the movement pool the engine reads is the one in the loaded level package at
  $f530 -- the engine PRG carries no copy;
* every program start offset still resolves to the record it named before.

Manual VICE remains authoritative for how any of it LOOKS.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, call, check, report)

PORT = 6711
POOL = 0xf530
WM_STRAIGHT, WM_ARC, WM_ARC_MIRROR, WM_EXIT, WM_HOLD = 0, 1, 2, 3, 4
WM_HEAD_CONT, HEAD_LEN = 0xff, 64
STAGE = 4
SLOT = 0
# src/wave_programs.asm: SWEEP, S-TURN, LINGER, LOOP
PROG_AT = [0, 12, 24, 40]


def records(mon):
    raw = rd(mon, POOL, 52)
    return [list(raw[i * STAGE:(i + 1) * STAGE]) for i in range(len(raw) // STAGE)]


def enter(mon, sym, byte_offset, seed_phase):
    """Put slot SLOT on the record at byte_offset with wmPhase = seed_phase,
    then run the engine's own stage-entry routine and read the result back."""
    poke(mon, sym["wmStage"] + SLOT, byte_offset)
    poke(mon, sym["wmPhase"] + SLOT, seed_phase)
    call(mon, sym, "wmEnterStage", x=SLOT)
    return (rd1(mon, sym["wmPhase"] + SLOT),
            rd1(mon, sym["wmVX"] + SLOT),
            rd1(mon, sym["wmVY"] + SLOT))


def main():
    sym = symbols(SYM)
    v = Vice(PORT, PRG)
    try:
        mon = v.mon
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], 0xff)

        # ---- the pool really is the package's ----------------------------
        pk = (ROOT / "build/level1.prg").read_bytes()
        base = pk[0] | (pk[1] << 8)
        want = list(pk[2 + POOL - base: 2 + POOL - base + 52])
        live = rd(mon, POOL, 52)
        check("the movement pool in RAM at $f530 matches the built level package byte for byte",
              live == want, f"{sum(1 for a, b in zip(live, want) if a != b)} mismatches")

        check("waveStageTable resolves into the level package, not the engine PRG",
              sym.get("waveStageTable") == POOL,
              f"${sym.get('waveStageTable', 0):04x}")

        prg = (ROOT / "build/shmup.prg").read_bytes()
        dup = bytes(want) in prg
        check("the engine PRG carries no second copy of the pool",
              not dup,
              "a duplicate of the 52 pool bytes is still in the engine binary"
              if dup else "absent from the engine binary, as intended")

        recs = records(mon)
        check("the pool is a whole number of four-byte stage records",
              len(recs) * STAGE == 52, f"{len(recs)} records")
        check("every program start offset resolves to a record boundary",
              all(o % STAGE == 0 and o < 52 for o in PROG_AT), f"{PROG_AT}")
        kinds = [recs[o // STAGE][0] for o in PROG_AT]
        check("each program still starts with the primitive it always did",
              kinds == [WM_STRAIGHT, WM_ARC_MIRROR, WM_STRAIGHT, WM_STRAIGHT],
              f"{kinds}")

        headvx = rd(mon, sym["wmHeadVX"], HEAD_LEN)
        headvy = rd(mon, sym["wmHeadVY"], HEAD_LEN)

        # ---- ARC entry is determined by the record, not by history -------
        arcs = [(i, r) for i, r in enumerate(recs)
                if r[0] in (WM_ARC, WM_ARC_MIRROR)]
        check("the pool contains the expected arc stages", len(arcs) == 5, f"{len(arcs)}")

        explicit = [(i, r) for i, r in arcs if r[3] != WM_HEAD_CONT]
        cont = [(i, r) for i, r in arcs if r[3] == WM_HEAD_CONT]
        check("exactly one arc asks to CONTINUE, and it is the S-turn's join",
              len(cont) == 1 and cont[0][0] == 4, f"{[i for i, _ in cont]}")

        bad = []
        for idx, rec in explicit:
            want_h = rec[3]
            # seed with three deliberately wrong phases, including the value a
            # stale earlier arc would most plausibly have left behind
            for seed in (0, (want_h + 17) % HEAD_LEN, (want_h + 33) % HEAD_LEN):
                ph, vx, vy = enter(mon, sym, idx * STAGE, seed)
                if (ph, vx, vy) != (want_h, headvx[want_h], headvy[want_h]):
                    bad.append((idx, seed, ph, vx, vy, want_h))
        check("an ARC with an explicit heading ignores wmPhase entirely "
              f"({len(explicit)} arcs x 3 corrupted seeds)",
              not bad, f"{len(bad)} wrong: {bad[:3]}")

        # the three arcs above are reached after STRAIGHT, after HOLD and as a
        # program's first stage -- name them so a failure says which
        after = {1: "after STRAIGHT (SWEEP)", 8: "after HOLD (LINGER)",
                 11: "after STRAIGHT (LOOP)", 3: "as first stage (S-TURN, MIRROR)"}
        for idx, label in after.items():
            rec = recs[idx]
            if rec[3] == WM_HEAD_CONT:
                continue
            ph, vx, vy = enter(mon, sym, idx * STAGE, (rec[3] + 9) % HEAD_LEN)
            check(f"ARC entry {label} is deterministic",
                  (ph, vx, vy) == (rec[3], headvx[rec[3]], headvy[rec[3]]),
                  f"phase {ph} vel ({vx},{vy}), wanted {rec[3]}")

        # ---- WM_HEAD_CONT is the one value that inherits -----------------
        ci, crec = cont[0]
        seen = []
        for seed in (0, 12, 40):
            ph, vx, vy = enter(mon, sym, ci * STAGE, seed)
            seen.append((seed, ph, vx, vy))
        check("WM_HEAD_CONT continues from whatever heading the object holds",
              all(ph == seed and vx == headvx[seed] and vy == headvy[seed]
                  for seed, ph, vx, vy in seen), f"{seen}")
        check("...and it is therefore the ONLY arc whose entry depends on history",
              len(cont) == 1, f"{len(cont)} continue-arcs")

        # ---- the mirror turns the other way ------------------------------
        mi, mrec = next((i, r) for i, r in arcs if r[0] == WM_ARC_MIRROR)
        poke(mon, sym["wmStage"] + SLOT, mi * STAGE)
        poke(mon, sym["wmPhase"] + SLOT, 55)
        call(mon, sym, "wmEnterStage", x=SLOT)
        start = rd1(mon, sym["wmPhase"] + SLOT)
        poke(mon, sym["wmTimer"] + SLOT, 1)
        call(mon, sym, "wmArcStep", x=SLOT)
        after_mirror = rd1(mon, sym["wmPhase"] + SLOT)
        check("WM_ARC_MIRROR starts on its named heading and steps ANTICLOCKWISE",
              start == mrec[3] and after_mirror == (mrec[3] - 1) % HEAD_LEN,
              f"entered {start} (want {mrec[3]}), stepped to {after_mirror}")

        ai, arec = next((i, r) for i, r in arcs
                        if r[0] == WM_ARC and r[3] != WM_HEAD_CONT)
        poke(mon, sym["wmStage"] + SLOT, ai * STAGE)
        poke(mon, sym["wmPhase"] + SLOT, 55)
        call(mon, sym, "wmEnterStage", x=SLOT)
        poke(mon, sym["wmTimer"] + SLOT, 1)
        call(mon, sym, "wmArcStep", x=SLOT)
        after_arc = rd1(mon, sym["wmPhase"] + SLOT)
        check("WM_ARC steps CLOCKWISE from the same explicit contract",
              after_arc == (arec[3] + 1) % HEAD_LEN,
              f"stepped to {after_arc}, wanted {(arec[3] + 1) % HEAD_LEN}")
    finally:
        v.close()
    return report("movement pool + deterministic ARC entry")


if __name__ == "__main__":
    sys.exit(main())
