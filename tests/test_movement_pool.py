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
TRIG     = 0xf736       # the parallel trigger columns

# ---------------------------------------------------------------------------
# THE LAYOUT IS DERIVED, NOT WRITTEN DOWN. Every number below used to be a
# literal, and every one of them went stale: TRIG_SLOTS said 180 through three
# column additions that moved it to 154, then 135, then 120, and the column
# list still named six when the package had nine. A frozen copy of a derived
# number is a test that reports the wrong thing with total confidence.
#
# So the geometry comes from src/levelpkg.asm and the authored content from the
# generated level, read through the editor's own declaration parser -- the same
# one the exporter uses. If the engine and this test can ever disagree about
# where a column is, it is because the engine moved it, which is the only thing
# worth being told.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(ROOT / "tools" / "level_editor"))
import asm_decl                                                  # noqa: E402
import contract_v2 as C                                          # noqa: E402

TRIG_SLOTS = C.LEVELPKG_TRIG_SLOTS
TRIG_COLS = ("rowLo", "rowHi", "def", "species", "fire", "side",
             "colour", "fireMode", "speed")
assert len(TRIG_COLS) == C.LEVELPKG_TRIG_COLS, (
    f"this test names {len(TRIG_COLS)} trigger columns and src/levelpkg.asm "
    f"declares {C.LEVELPKG_TRIG_COLS}")
WAVEDEF_SIZE = C.LEVELPKG_WAVEDEF_SIZE

# The authored content, from the level the engine was actually built against.
_LVL = ROOT / "src" / "level1"
_enc = asm_decl.parse_files(
    [ROOT / "src" / n for n in ("movement_format.asm", "encounter_format.asm")]
    + [_LVL / "wave_programs.asm", _LVL / "wave_encounters.asm"])
WAVE_DEFS = _enc.const("WAVE_DEFS")
WAVE_TRIGGERS = _enc.const("WAVE_TRIGGERS")
TRIG_ROWS = list(_enc.list_("trigRow"))
TRIG_SPECIES = list(_enc.list_("trigSpecies"))
TRIG_FIRE = list(_enc.list_("trigFire"))
TRIG_SIDE = list(_enc.list_("trigSide"))
TRIG_SPEED = list(_enc.list_("trigSpeed"))
WM_STRAIGHT, WM_ARC, WM_ARC_MIRROR, WM_EXIT, WM_HOLD = 0, 1, 2, 3, 4
WM_HEAD_CONT, HEAD_LEN = 0xff, 64
STAGE = 4
SLOT = 0

# THE POOL'S SHAPE, DERIVED FROM THE LEVEL IT WAS BUILT FROM. `progs` is a list
# of programs, each a list of four-byte records; the package lays them end to
# end and a definition's field 9 -- a program INDEX in the source -- is emitted
# as that program's BYTE OFFSET. Both used to be frozen here as [0, 12, 24, 40]
# and a 52-byte read, which were the right answers for the four programs that
# existed at the time and silently the wrong ones for the six that exist now.
_PROGS = _enc.list_("progs")
_PROG_OFFSETS = []
_acc = 0
for _prog in _PROGS:
    _PROG_OFFSETS.append(_acc)
    _acc += len(_prog) * STAGE
POOL_BYTES = _acc
PROG_AT = [_PROG_OFFSETS[d[9]] for d in _enc.list_("waveDefs")]


def records(mon):
    raw = rd(mon, POOL, POOL_BYTES)
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
            label = "waveTrig" + n[0].upper() + n[1:]
            check(f"{label} resolves to its package column",
                  sym.get(label) == want, f"${want:04x}")
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
        check("...and so did the authored movement speeds",
              list(cols["speed"]) == TRIG_SPEED, f"{list(cols['speed'])}")

        # ---- THE CAPACITY, DERIVED AT BOTH ENDS ---------------------------
        # The engine reserves LEVELPKG_TRIG_MAX bytes and cuts them into
        # LEVELPKG_TRIG_COLS columns; the editor refuses to author more
        # triggers than that yields. Neither number is written down twice, and
        # this is where they are checked against each other.
        check("the trigger columns tile the package's reservation exactly",
              TRIG_SLOTS * len(TRIG_COLS) <= C.LEVELPKG_TRIG_RESERVATION
              and (TRIG_SLOTS + 1) * len(TRIG_COLS) > C.LEVELPKG_TRIG_RESERVATION,
              f"{len(TRIG_COLS)} x {TRIG_SLOTS} = "
              f"{len(TRIG_COLS) * TRIG_SLOTS} of "
              f"{C.LEVELPKG_TRIG_RESERVATION} bytes")
        check("the editor's authoring ceiling is that same slot count",
              C.MAX_TRIGGERS == TRIG_SLOTS, str(C.MAX_TRIGGERS))
        check("...and this level fits inside it",
              WAVE_TRIGGERS <= TRIG_SLOTS,
              f"{WAVE_TRIGGERS} of {TRIG_SLOTS} slots used")
        check("the whole trigger list stays below the package signature",
              TRIG + len(TRIG_COLS) * TRIG_SLOTS <= 0xfb70,
              f"ends at ${TRIG + len(TRIG_COLS) * TRIG_SLOTS:04x}, "
              f"signature at $fb70")

        # ---- the cross-reference the whole package rests on ----------------
        # Field 9 of a definition is a BYTE OFFSET into the movement pool. If it
        # did not land on a record boundary the interpreter would read a stage
        # record straddling two others.
        offs = [wd_live[d * WAVEDEF_SIZE + 9] for d in range(WAVE_DEFS)]
        # THE POOL'S OWN SIZE IS THE BOUND, not a frozen byte count: the pool
        # grows whenever a program is added, and "< 52" was the length it
        # happened to have when four programs existed.
        pool_bytes = len(records(mon)) * STAGE
        check("every definition's movement-program offset lands on a record "
              "boundary inside the pool",
              all(o % STAGE == 0 and o < pool_bytes for o in offs),
              f"{offs}, pool is {pool_bytes} bytes")
        check("the definitions name the offsets the generated level declares",
              offs == PROG_AT, f"{offs} vs {PROG_AT}")

        recs = records(mon)
        check("the pool is a whole number of four-byte stage records",
              len(recs) * STAGE == POOL_BYTES, f"{len(recs)} records")
        check("every program start offset resolves to a record boundary",
              all(o % STAGE == 0 and o < POOL_BYTES for o in PROG_AT),
              f"{PROG_AT} in {POOL_BYTES} bytes")
        # THE PRIMITIVE EACH PROGRAM OPENS WITH, read from the level rather
        # than remembered: this froze as four kinds and the level now has six
        # programs behind seven definitions.
        kinds = [recs[o // STAGE][0] for o in PROG_AT]
        want_kinds = [_PROGS[d[9]][0][0] for d in _enc.list_("waveDefs")]
        check("each definition's program starts with the primitive the level "
              "declares", kinds == want_kinds, f"{kinds} vs {want_kinds}")

        headvx = rd(mon, sym["wmHeadVX"], HEAD_LEN)
        headvy = rd(mon, sym["wmHeadVY"], HEAD_LEN)

        # ---- ARC entry is determined by the record, not by history -------
        arcs = [(i, r) for i, r in enumerate(recs)
                if r[0] in (WM_ARC, WM_ARC_MIRROR)]
        want_arcs = sum(1 for prog in _PROGS for r in prog
                        if r[0] in (WM_ARC, WM_ARC_MIRROR))
        check("the pool contains every arc stage the level declares",
              len(arcs) == want_arcs, f"{len(arcs)} of {want_arcs}")

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
