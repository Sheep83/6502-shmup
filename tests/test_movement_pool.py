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
POOL     = 0xf532       # movement programs
WAVEDEF  = 0xf632       # wave definitions, 10 bytes each
TRIG     = 0xf736       # six parallel trigger columns
TRIG_SLOTS = 180        # each column is this wide, whatever the level authors
TRIG_COLS  = ("rowLo", "rowHi", "def", "species", "fire", "side")
WAVEDEF_SIZE = 10
WAVE_DEFS, WAVE_TRIGGERS = 4, 4
TRIG_ROWS = [48, 52, 90, 126]                 # Stage 1: absolute, no wrap
SPECIES_RING, SPECIES_DROPPER = 0, 8
TRIG_SPECIES = [SPECIES_RING, SPECIES_DROPPER, SPECIES_RING, SPECIES_DROPPER]
TRIG_FIRE = [0b0101, 0b0010, 0b0101, 0b0000]
TRIG_SIDE = [0, 0, 0, 1]                      # LEFT, LEFT, LEFT, RIGHT
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

        # ---- the wave definitions live in the package too ----------------
        wd_live = rd(mon, WAVEDEF, WAVE_DEFS * WAVEDEF_SIZE)
        wd_want = list(pk[2 + WAVEDEF - base: 2 + WAVEDEF - base + WAVE_DEFS * WAVEDEF_SIZE])
        check("the wave definitions in RAM at $f630 match the built level package",
              wd_live == wd_want,
              f"{sum(1 for a, b in zip(wd_live, wd_want) if a != b)} mismatches")
        check("waveDefTable resolves into the level package, not the engine PRG",
              sym.get("waveDefTable") == WAVEDEF, f"${sym.get('waveDefTable', 0):04x}")
        check("the engine PRG carries no second copy of the wave definitions",
              bytes(wd_want) not in prg, "a duplicate is still in the engine binary")

        # ---- and so does the absolute trigger list ------------------------
        cols = {n: rd(mon, TRIG + i * TRIG_SLOTS, WAVE_TRIGGERS)
                for i, n in enumerate(TRIG_COLS)}
        for i, n in enumerate(TRIG_COLS):
            want = TRIG + i * TRIG_SLOTS
            check(f"waveTrig{n[0].upper()}{n[1:]} resolves to its package column",
                  sym.get({"rowLo": "waveTrigRowLo", "rowHi": "waveTrigRowHi",
                           "def": "waveTrigDef", "species": "waveTrigSpecies",
                           "fire": "waveTrigFire", "side": "waveTrigSide"}[n]) == want,
                  f"${want:04x}")
        rows = [lo | (hi << 8) for lo, hi in zip(cols["rowLo"], cols["rowHi"])]
        check("the authored trigger rows are ABSOLUTE and 16-bit in the package",
              rows == TRIG_ROWS, f"{rows}")
        check("every trigger names a definition that exists",
              all(d < WAVE_DEFS for d in cols["def"]), f"{list(cols['def'])}")
        check("the authored species survived the move", list(cols["species"]) == TRIG_SPECIES,
              f"{list(cols['species'])}")
        check("the authored fire masks survived the move", list(cols["fire"]) == TRIG_FIRE,
              f"{list(cols['fire'])}")
        check("the authored Dropper sides survived the move", list(cols["side"]) == TRIG_SIDE,
              f"{list(cols['side'])}")

        # ---- the cross-reference the whole package rests on ----------------
        # Field 9 of a definition is a BYTE OFFSET into the movement pool. If it
        # did not land on a record boundary the interpreter would read a stage
        # record straddling two others.
        offs = [wd_live[d * WAVEDEF_SIZE + 9] for d in range(WAVE_DEFS)]
        check("every definition's movement-program offset lands on a record boundary",
              all(o % STAGE == 0 and o < 52 for o in offs), f"{offs}")
        check("the definitions still name the programs they always did",
              offs == PROG_AT, f"{offs} vs {PROG_AT}")

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
    return report("level-package encounter data + deterministic ARC entry")


if __name__ == "__main__":
    sys.exit(main())
