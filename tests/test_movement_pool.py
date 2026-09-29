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
import synth                                                     # noqa: E402
import campaign_data as CD                                       # noqa: E402

# THE THREE BASE ADDRESSES, RESOLVED FROM src/levelpkg.asm RATHER THAN TYPED.
# They were `0xf532`, `0xf632` and `0xf736`; the wave-definition one is spelled
# `$f630` in a comment in levelpkg.asm itself, which is exactly how a
# transcribed address goes wrong.
POOL = CD.POOL_BASE             # movement programs
WAVEDEF = CD.WAVEDEF_BASE       # wave definitions, 10 bytes each
TRIG = CD.TRIG_BASE             # the parallel trigger columns

TRIG_SLOTS = C.LEVELPKG_TRIG_SLOTS
TRIG_COLS = ("rowLo", "rowHi", "def", "species", "fire", "side",
             "colour", "fireMode", "speed")
assert len(TRIG_COLS) == C.LEVELPKG_TRIG_COLS, (
    f"this test names {len(TRIG_COLS)} trigger columns and src/levelpkg.asm "
    f"declares {C.LEVELPKG_TRIG_COLS}")
WAVEDEF_SIZE = C.LEVELPKG_WAVEDEF_SIZE

# The authored content, from the level the engine was actually built against.
_LEVEL_NAME = "level1"
_LVL = ROOT / "src" / _LEVEL_NAME
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


def enter(mon, sym, byte_offset, seed_phase, speed=None):
    """Put slot SLOT on the record at byte_offset with wmPhase = seed_phase,
    then run the engine's own stage-entry routine and read the result back.

    THE SLOT'S SPEED IS PINNED. wmEnterStage ends `jmp wmApplySpeed`, so the
    velocity it leaves behind is the heading table's entry SCALED by whatever
    wmSpeed the slot carries -- and slot 0 carries whatever the live game last
    put there. Before this line, six checks here compared a scaled velocity
    against the raw table and failed reporting (9,0) where they wanted (6,0):
    heading 0 at 1.50x, which is correct behaviour. TRIG_SPEED_1X is bit-exact
    by construction, so pinning it is what makes the table comparison mean
    anything. The scaling itself is proved in tests/test_trigger_speed.py.
    """
    poke(mon, sym["wmSpeed"] + SLOT,
         C.TRIG_SPEED_1X if speed is None else speed)
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
        # THE WHOLE POOL, WHATEVER SIZE IT IS. This read was 52 bytes -- the
        # length the pool happened to have when four programs existed -- so it
        # compared the first thirteen records and ignored the rest.
        want = list(pk[2 + POOL - base: 2 + POOL - base + POOL_BYTES])
        live = rd(mon, POOL, POOL_BYTES)
        check(f"the movement pool in RAM at ${POOL:04x} matches the built level "
              f"package byte for byte, all {POOL_BYTES} of them",
              live == want,
              f"{sum(1 for a, b in zip(live, want) if a != b)} mismatches")

        check("waveStageTable resolves into the level package, not the engine PRG",
              sym.get("waveStageTable") == POOL,
              f"${sym.get('waveStageTable', 0):04x}")

        prg = (ROOT / "build/shmup.prg").read_bytes()
        dup = bytes(want) in prg
        check("the engine PRG carries no second copy of the pool",
              not dup,
              f"a duplicate of the {POOL_BYTES} pool bytes is still in the "
              f"engine binary" if dup
              else "absent from the engine binary, as intended")

        # ---- the wave definitions live in the package too ----------------
        wd_live = rd(mon, WAVEDEF, WAVE_DEFS * WAVEDEF_SIZE)
        wd_want = list(pk[2 + WAVEDEF - base: 2 + WAVEDEF - base + WAVE_DEFS * WAVEDEF_SIZE])
        check(f"the wave definitions in RAM at ${WAVEDEF:04x} match the built "
              f"level package",
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
              TRIG + len(TRIG_COLS) * TRIG_SLOTS <= CD.SIG_ADDR,
              f"ends at ${TRIG + len(TRIG_COLS) * TRIG_SLOTS:04x}, "
              f"signature at ${CD.SIG_ADDR:04x}")

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
        # HOW MANY ARCS CONTINUE IS AUTHORING. This said "exactly one, and it is
        # at record 4", which was true of the six programs that existed in
        # August and is not an engine property at all -- an author may write a
        # second S-turn, or none. What IS an engine property is the split: every
        # arc either names a heading in range or asks to inherit, and nothing
        # else is a legal byte 3.
        want_cont = sum(1 for prog in _PROGS for r in prog
                        if r[0] in (WM_ARC, WM_ARC_MIRROR) and r[3] == WM_HEAD_CONT)
        check("the pool's continue-arcs are the ones the level declares",
              len(cont) == want_cont,
              f"{len(cont)} at records {[i for i, _ in cont]}, level declares "
              f"{want_cont}")
        check("every arc's byte 3 is either a heading in range or WM_HEAD_CONT "
              "-- there is no third legal value",
              all(r[3] < HEAD_LEN or r[3] == WM_HEAD_CONT for _i, r in arcs),
              f"{len(arcs)} arcs, byte 3 values "
              f"{sorted({r[3] for _i, r in arcs})}")

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

        # ---- THE ENTRY CONTEXT, DERIVED FROM THE PROGRAMS ------------------
        # This was a hand-written map {1: "after STRAIGHT (SWEEP)", 8: "after
        # HOLD (LINGER)", 11: "after STRAIGHT (LOOP)", 3: "first stage"}: record
        # indices and program names from the level as it stood in August. The
        # CLAIM is that an arc's entry does not depend on what came before it, so
        # the interesting thing is the PREDECESSOR KIND, and the level's own
        # programs say which ones occur. If Brian adds a program with a new
        # context, this covers it automatically.
        KIND = {WM_STRAIGHT: "after STRAIGHT", WM_ARC: "after ARC",
                WM_ARC_MIRROR: "after ARC_MIRROR", WM_EXIT: "after EXIT",
                WM_HOLD: "after HOLD"}
        contexts = {}
        for pi, prog in enumerate(_PROGS):
            for j, rec in enumerate(prog):
                if rec[0] not in (WM_ARC, WM_ARC_MIRROR) or rec[3] == WM_HEAD_CONT:
                    continue
                label = ("as a program's first stage" if j == 0
                         else KIND.get(prog[j - 1][0], f"after kind {prog[j-1][0]}"))
                # the pool lays the programs end to end, so the record index is
                # the program's own offset plus the stage's position in it
                contexts.setdefault(label, _PROG_OFFSETS[pi] // STAGE + j)
        check("the level exercises more than one arc entry CONTEXT, so "
              "'independent of history' is worth asserting",
              len(contexts) > 1, "; ".join(sorted(contexts)))
        for label, idx in sorted(contexts.items()):
            rec = recs[idx]
            ph, vx, vy = enter(mon, sym, idx * STAGE, (rec[3] + 9) % HEAD_LEN)
            check(f"ARC entry {label} is deterministic",
                  (ph, vx, vy) == (rec[3], headvx[rec[3]], headvy[rec[3]]),
                  f"record {idx}: phase {ph} vel ({vx},{vy}), wanted {rec[3]}")

        # ---- THE PRIMITIVES THEMSELVES, ON SYNTHETIC RECORDS --------------
        # WM_HEAD_CONT, the clockwise step and the mirror's anticlockwise step
        # are ENGINE behaviour. They used to be tested on whichever authored
        # records happened to have the right shape -- `cont[0]`, and the first
        # WM_ARC_MIRROR in the pool -- so a level with no S-turn or no mirror
        # would have crashed this file with a StopIteration rather than told
        # anybody anything. The records are now built, in the spare room the
        # package reserves and the level does not use, so all three cases always
        # run and none of them depends on what is authored.
        pkg = synth.Package(mon, sym, _LEVEL_NAME)
        HEAD = 20                            # an arbitrary in-range heading
        syn = pkg.install_program([
            [WM_ARC, 16, 4, WM_HEAD_CONT],   # 0: inherits
            [WM_ARC, 16, 4, HEAD],           # 1: clockwise from HEAD
            [WM_ARC_MIRROR, 16, 4, HEAD],    # 2: anticlockwise from HEAD
        ])
        check("three synthetic arc records were installed past the authored pool",
              syn == POOL_BYTES, f"at pool offset {syn}, pool ends at {POOL_BYTES}")

        seen = []
        for seed in (0, 12, 40):
            ph, vx, vy = enter(mon, sym, syn + 0 * STAGE, seed)
            seen.append((seed, ph, vx, vy))
        check("WM_HEAD_CONT continues from whatever heading the object holds",
              all(ph == seed and vx == headvx[seed] and vy == headvy[seed]
                  for seed, ph, vx, vy in seen), f"{seen}")
        # ...AND IT IS THE ONLY VALUE THAT DOES. Asserted over the whole pool
        # rather than by counting today's S-turns: every arc with an explicit
        # heading was just shown to ignore wmPhase entirely.
        check("...and it is the ONLY byte 3 whose entry depends on history -- "
              "every explicit heading ignored wmPhase above",
              not bad and all(r[3] < HEAD_LEN or r[3] == WM_HEAD_CONT
                              for _i, r in arcs),
              f"{len(explicit)} explicit arcs, {len(cont)} continue-arcs")

        def step_once(offset, seed=55):
            entered = enter(mon, sym, offset, seed)[0]
            poke(mon, sym["wmTimer"] + SLOT, 1)
            call(mon, sym, "wmArcStep", x=SLOT)
            return entered, rd1(mon, sym["wmPhase"] + SLOT)

        start, moved = step_once(syn + 1 * STAGE)
        check("WM_ARC starts on its named heading and steps CLOCKWISE",
              start == HEAD and moved == (HEAD + 1) % HEAD_LEN,
              f"entered {start} (want {HEAD}), stepped to {moved}")
        start, moved = step_once(syn + 2 * STAGE)
        check("WM_ARC_MIRROR starts on the SAME named heading and steps "
              "ANTICLOCKWISE",
              start == HEAD and moved == (HEAD - 1) % HEAD_LEN,
              f"entered {start} (want {HEAD}), stepped to {moved}")
        # THE WRAP, at both ends, which no authored record need ever visit.
        for kind, off, at, want in ((WM_ARC, 1, HEAD_LEN - 1, 0),
                                    (WM_ARC_MIRROR, 2, 0, HEAD_LEN - 1)):
            edge = pkg.install_program([[kind, 16, 4, at]])
            _s, moved = step_once(edge)
            check(f"{'WM_ARC' if kind == WM_ARC else 'WM_ARC_MIRROR'} wraps "
                  f"{at} -> {want} rather than running off the table",
                  moved == want, f"stepped to {moved}")
    finally:
        v.close()
    return report("level-package encounter data + deterministic ARC entry")


if __name__ == "__main__":
    sys.exit(main())
