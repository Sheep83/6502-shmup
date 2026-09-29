#!/usr/bin/env python3
"""STAGE_NO_SPAWN_ROW: the authored boss approach.

The contract under test
-----------------------
    An ordinary authored encounter that has not STARTED before
    worldProgress reaches STAGE_NO_SPAWN_ROW must never start.

Everything here drives worldProgress deliberately rather than waiting for it,
and every case holds stageHold so the stage cannot END during the window --
otherwise lvlPhase would leave LP_LEVEL and the pre-existing end-of-level gate
would suppress the wave instead of the one being tested.

THE SCHEDULE IS SYNTHETIC AND THE THRESHOLD IS THE LEVEL'S OWN.

The gate is a comparison between worldProgress and a package byte. It has
nothing to say about how many encounters a level authors or where they sit, so
the cases below install ONE disposable trigger at a low row (tests/synth.py,
package RAM only) and drive the world around the threshold. Before that change
this file restated Level 1's schedule as `WAVE_TRIGGERS = 4` and
`TRIG_ROWS = [48, 52, 90, 126]`; the level was re-authored to five triggers and
three checks failed reporting a cursor of 5, which was the correct answer.

What is still read from the real level is the threshold itself and the authored
rows -- not to freeze them, but to prove the EXPORTER put every row below the
threshold, which is a genuine safety invariant over whatever is authored.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (level_const, PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     step_n, call, check, report)
import campaign_data as CD                                       # noqa: E402
import synth                                                     # noqa: E402

PORT = 6715
# READ FROM THE LEVEL, NOT RESTATED. This was 340 with a comment pointing at
# the file that actually defines it; the level was re-authored to 725 and the
# test failed seven checks about an engine that was behaving correctly.
NO_SPAWN = level_const("STAGE_NO_SPAWN_ROW")    # src/level1/stage_config.asm
NOSPAWN_ADDR = CD.NOSPAWN_ADDR  # the stage header in the LOADED package
LP_LEVEL = 0

# THE SYNTHETIC SCHEDULE. One trigger, at a row far below any plausible
# threshold, so "a trigger is due" is true whenever the world is above it -- and
# the cursor's terminal value is therefore 1, derived from the count this file
# installed rather than from what Level 1 happens to author.
SYN_TRIGGERS = 1
SYN_ROW = 8


def w16(mon, sym, n):
    b = rd(mon, sym[n + "Lo"], 2)
    return b[0] | (b[1] << 8)


def arm(mon, sym, world, cursor=0):
    """Put the director at `cursor` with the world at `world`, stage held open.

    waveInit FIRST, every time. Cases leave live wave instances behind, and a
    trigger that finds both WAVE_SLOTS busy is DROPPED rather than started --
    which looks exactly like suppression and would let a later case pass for
    entirely the wrong reason.
    """
    call(mon, sym, "waveInit")
    poke(mon, sym["stageHold"], 1)          # the stage must not END during a case
    poke(mon, sym["lvlPhase"], LP_LEVEL)
    poke(mon, sym["tkActive"], 0)
    poke(mon, sym["wvNextTrig"], cursor)
    poke(mon, sym["wvStarted"], 0)
    poke(mon, sym["worldProgressLo"], world & 0xff)
    poke(mon, sym["worldProgressHi"], world >> 8)


def run(mon, sym, n=12):
    step_n(mon, sym["frameCounter"], n, lambda: None)
    return rd1(mon, sym["wvStarted"]), rd1(mon, sym["wvNextTrig"])


def run_held(mon, sym, n):
    """Step n frames with the token hold asserted on every one of them.

    tkActive is ENGINE-OWNED: tokenTick ends an encounter it cannot find, so a
    single poke survives exactly one frame. gameFrame calls waveTick BEFORE
    tokenTick, so re-asserting it immediately before each step is what the
    director actually sees -- and is the only way to hold it from outside.
    """
    for _ in range(n):
        poke(mon, sym["tkActive"], 1)
        step_n(mon, sym["frameCounter"], 1, lambda: None)
    return rd1(mon, sym["wvStarted"]), rd1(mon, sym["wvNextTrig"])


def main():
    sym = symbols(SYM)
    v = Vice(PORT, PRG, boot="exact")
    try:
        mon = v.mon
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], 0xff)
        mon.cmd("delete")
        set_bp(mon, sym["gameFrame"])

        check(f"the threshold is above 255, so the 16-bit compare is exercised",
              NO_SPAWN > 255, f"STAGE_NO_SPAWN_ROW = {NO_SPAWN} (${NO_SPAWN:04x})")
        live = rd1(mon, NOSPAWN_ADDR) | (rd1(mon, NOSPAWN_ADDR + 1) << 8)
        check("the threshold is RUNTIME PACKAGE DATA at $f530, not a compiled-in "
              "immediate -- so a level ships its own and a test can move it",
              live == NO_SPAWN, f"package says {live}, stage_config says {NO_SPAWN}")

        # ---- THE INVARIANT OVER THE REAL AUTHORED SCHEDULE ----------------
        # Not "the rows are 48, 52, 90 and 126" -- that is content. What must
        # hold for ANY authoring is that the exporter put every live row STRICTLY
        # below the threshold, because a row at or beyond it could never start
        # and would be an encounter the author wrote and the engine silently ate.
        # src/waves.asm refuses to assemble one; this is the same claim measured
        # on the package that actually shipped.
        n_live = rd1(mon, CD.TRIGN_ADDR)
        lo = rd(mon, sym["waveTrigRowLo"], max(n_live, 1))
        hi = rd(mon, sym["waveTrigRowHi"], max(n_live, 1))
        authored = [lo[i] | (hi[i] << 8) for i in range(n_live)]
        check("EVERY authored trigger row is below the threshold -- no authored "
              "encounter is unreachable",
              all(r < NO_SPAWN for r in authored),
              f"{n_live} rows {authored}, threshold {NO_SPAWN}")
        check("...and they are non-decreasing, as a forward-only cursor requires",
              all(b >= a for a, b in zip(authored, authored[1:])), str(authored))

        # ---- THE SYNTHETIC SCHEDULE THE CASES BELOW USE -------------------
        pkg = synth.Package(mon, sym)
        pkg.only_trigger(row=SYN_ROW,
                         definition=rd1(mon, sym["waveTrigDef"] + 0))
        pkg.set_no_spawn_row(NO_SPAWN)          # only_trigger opened it; put it back
        check("one disposable trigger is installed, well below the threshold",
              rd1(mon, CD.TRIGN_ADDR) == SYN_TRIGGERS
              and (rd1(mon, sym["waveTrigRowLo"])
                   | (rd1(mon, sym["waveTrigRowHi"]) << 8)) == SYN_ROW,
              f"{rd1(mon, CD.TRIGN_ADDR)} trigger(s) at row {SYN_ROW}, "
              f"threshold still {rd1(mon, NOSPAWN_ADDR) | (rd1(mon, NOSPAWN_ADDR + 1) << 8)}")

        # ---- BOUNDARY ----------------------------------------------------
        arm(mon, sym, NO_SPAWN - 1)
        started, cursor = run(mon, sym)
        check("one row BEFORE the threshold, an authored trigger still starts",
              started > 0, f"wvStarted={started}, cursor={cursor}")

        arm(mon, sym, NO_SPAWN)
        started, cursor = run(mon, sym)
        check("EXACTLY AT the threshold, no authored trigger starts",
              started == 0, f"wvStarted={started}")
        check("...and the cursor is left terminally exhausted",
              cursor == SYN_TRIGGERS, f"wvNextTrig={cursor}")

        arm(mon, sym, NO_SPAWN + 30)
        started, cursor = run(mon, sym)
        check("BEYOND the threshold, no authored trigger starts",
              started == 0, f"wvStarted={started}")

        # THE HIGH BYTE MUST GENUINELY DISCRIMINATE. The probe is the largest
        # world position whose high byte is zero, and it is below the threshold
        # because the threshold is above 255 (checked above) -- so a compare that
        # dropped the high byte would suppress here and must not.
        arm(mon, sym, 255)
        started, _ = run(mon, sym)
        check(f"row 255 is below a {NO_SPAWN} threshold: the high byte is not "
              f"ignored", started > 0, f"wvStarted={started}")

        # ---- EXHAUSTION IS TERMINAL --------------------------------------
        arm(mon, sym, NO_SPAWN)
        run(mon, sym, 8)
        poke(mon, sym["worldProgressLo"], 100)   # wind the world BACK below it
        poke(mon, sym["worldProgressHi"], 0)
        started, cursor = run(mon, sym, 40)
        check("a suppressed schedule never reopens, even if the world is wound back",
              started == 0 and cursor == SYN_TRIGGERS,
              f"wvStarted={started}, cursor={cursor}")

        # ---- TOKEN HOLD ---------------------------------------------------
        # due before the threshold, held by a token encounter, world crosses the
        # threshold, hold released -> it must NOT start.
        arm(mon, sym, NO_SPAWN - 2)
        held_started, _ = run_held(mon, sym, 10)
        check("a trigger due before the threshold is HELD by a token encounter",
              held_started == 0, f"wvStarted={held_started}")
        poke(mon, sym["worldProgressLo"], NO_SPAWN & 0xff)
        poke(mon, sym["worldProgressHi"], NO_SPAWN >> 8)
        run_held(mon, sym, 6)                    # the world crosses, still held
        poke(mon, sym["tkActive"], 0)            # the encounter ends
        started, cursor = run(mon, sym, 30)
        check("...and once the world crossed the threshold while it was held, "
              "releasing the hold does NOT start it",
              started == 0 and cursor == SYN_TRIGGERS,
              f"wvStarted={started}, cursor={cursor}")

        # the same sequence WITHOUT crossing the threshold must still fire, or
        # the check above would pass for the wrong reason
        arm(mon, sym, NO_SPAWN - 2)
        run_held(mon, sym, 10)
        poke(mon, sym["tkActive"], 0)
        started, _ = run(mon, sym, 20)
        check("...while the same held trigger released BELOW the threshold does start",
              started > 0, f"wvStarted={started}")

        # ---- ACTIVE ENCOUNTER CONTINUITY ----------------------------------
        # a wave that started before the threshold must go on sending members
        arm(mon, sym, SYN_ROW)
        poke(mon, sym["wvSpawned"], 0)
        run(mon, sym, 6)
        active_before = [rd1(mon, sym["wvActive"] + i) for i in range(2)]
        spawned_at_cross = rd1(mon, sym["wvSpawned"])
        poke(mon, sym["worldProgressLo"], NO_SPAWN & 0xff)
        poke(mon, sym["worldProgressHi"], NO_SPAWN >> 8)
        step_n(mon, sym["frameCounter"], 60, lambda: None)
        spawned_after = rd1(mon, sym["wvSpawned"])
        check("a wave already running when the threshold is crossed keeps "
              "sending its members",
              any(active_before) and spawned_after > spawned_at_cross,
              f"active={active_before}, spawned {spawned_at_cross} -> {spawned_after}")
        check("...and no NEW wave started while it finished",
              rd1(mon, sym["wvStarted"]) == 1, f"wvStarted={rd1(mon, sym['wvStarted'])}")
    finally:
        v.close()
    return report("STAGE_NO_SPAWN_ROW boss approach")


if __name__ == "__main__":
    sys.exit(main())
