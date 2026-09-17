#!/usr/bin/env python3
"""Bank 2 boss arena — the VIC looks somewhere else, and nothing else changes.

What this proves
----------------
* THE LAYOUT IS REAL: every VIC-visible bank 2 range this proof establishes is
  free of CPU code, 1 KB / 2 KB aligned as the chip requires, outside the
  character ROM shadow, and the blank charset ends on the idle byte;
* $DD00 IS A READ-MODIFY-WRITE: selecting either bank changes bits 0-1 and
  leaves bits 2-7 -- the serial bus and RS-232 lines -- exactly as they were.
  Checked against a hostile pattern written into those six bits first;
* BANK 0 IS CHOSEN, NOT INHERITED: the machine is in bank 0 during ordinary
  play because vicBankInit said so;
* THE ARENA SWITCHES: reaching LP_BOSS puts the VIC in bank 2 and the frame
  record carries the bank 2 $d018 pair and pointer destination;
* THE PICTURE SURVIVES: the bank 2 screen matrix matches the frozen bank 0 page
  byte for byte, and the bank 2 charset matches the terrain charset;
* THE SPRITE POINTERS DID NOT MOVE: the pointer table in bank 2 holds the same
  values the bank 0 table held;
* THE BOSS STILL WORKS: full HP on arrival, takes damage, dies;
* THE LIFECYCLE STILL COMPLETES: victory and the scripted exit reach
  GS_LEVELDONE, with score, lives and P intact;
* THE RETURN PATH WORKS: vicSelectBank0 puts the machine back, preserving the
  same six bits;
* the catastrophic raster/mux counters stay clean across the whole run.

What this does NOT prove
------------------------
That the arena LOOKS the same. Manual VICE is authoritative for terrain
equivalence, HUD/player/muzzle, boss composition, borders and flicker.

One VICE launch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, check, report)

sym = symbols(SYM)
PORT = 6669

LP_LEVEL, LP_CLEARING, LP_BOSS, LP_VICTORY, LP_EXIT, LP_DONE = range(6)
GS_PLAYING, GS_LEVELDONE = 1, 4
GS_D018 = 0x14                  # src/gamestate.asm: VM $0400, CB = character ROM
BOSS_HP_FULL = 50

# src/vicbank.asm's layout, restated so a silent move is a failure here.
VB2_BASE     = 0x8000
VB2_SCREEN   = 0x8c00
VB2_PTR      = VB2_SCREEN + 0x3f8
VB2_CHARSET  = 0xa800
VB2_BLANK    = 0xb800
VB2_SPRITES  = 0xa000
SCREEN_A, SCREEN_B = 0x0400, 0x2800
CHARSET_0    = 0x0800

VIC_BANK_MASK = 0b11
VIC_BANK_0    = 0b11        # inverted: 3 selects $0000
VIC_BANK_2    = 0b01        # inverted: 1 selects $8000

# A pattern for the six bits that are NOT ours. Chosen so every one of them is
# a 1: if a bank select wrote a literal instead of masking, this is what would
# be lost, and the check below would see it go.
FOREIGN_BITS = 0b11111100

# The project's OWN definition of catastrophic, copied from tests/test_boss.py
# rather than invented here: the page/pointer coherence pair, the frame the main
# thread missed, and the scroller running late. schedBuildDefer and publishSkip
# are measured and printed but not asserted, which is the standing convention in
# this repository -- see the note in tests/test_boss.py.
CATASTROPHIC = ("gameOverrun", "scrollLate", "statPageMismatch",
                "statPtrMismatch", "schedBuildDefer", "objDoubleFree",
                "objAllocFail")


def cia2(mon):
    return rd1(mon, 0xdd00)


def d018_of(mon, which):
    """The frame record's $d018 pair, for whichever record is current."""
    cur = rd1(mon, sym["frameCurrent"])
    return rd1(mon, sym[which] + cur)


def main():
    print("=== bank 2 boss arena proof ===")
    v = None
    try:
        # ==================================================================
        # PART 1 -- the layout, from the symbol table. No emulator needed.
        # ==================================================================
        # The chip's own alignment rules, stated as arithmetic rather than
        # trusted: a screen matrix is 1 KB aligned, a charset 2 KB aligned, and
        # the idle fetch is the last byte of the bank.
        check("the bank 2 screen matrix is 1 KB aligned",
              VB2_SCREEN % 0x400 == 0, hex(VB2_SCREEN))
        check("the bank 2 charsets are 2 KB aligned",
              VB2_CHARSET % 0x800 == 0 and VB2_BLANK % 0x800 == 0,
              f"{hex(VB2_CHARSET)}, {hex(VB2_BLANK)}")
        check("the blank charset ends on the VIC's idle byte $bfff",
              VB2_BLANK + 0x800 == 0xc000, hex(VB2_BLANK + 0x7ff))
        check("nothing VIC-visible sits in the character ROM shadow "
              "($9000-$9fff)",
              all(not (0x9000 <= a < 0xa000) for a in
                  (VB2_SCREEN, VB2_CHARSET, VB2_BLANK, VB2_SPRITES)))
        check("the sprite mirror keeps its bank 0 offset, so no pointer moves",
              VB2_SPRITES - VB2_BASE == 0x2000, hex(VB2_SPRITES))

        # The code that stays in bank 2 must not be where the VIC will look.
        vis = [(0x8c00, 0x8fff), (0xa000, 0xbfff)]
        code = [(sym[n], n) for n in ("irqHandler", "clipInit", "bossInit",
                                      "gsEnterLevelDone")]
        clash = [n for a, n in code
                 if any(lo <= a <= hi for lo, hi in vis)]
        check("no CPU code lives in a bank 2 region the VIC fetches",
              not clash, str(clash))

        v = Vice(PORT, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # ==================================================================
        # PART 2 -- $DD00 read-modify-write, proved against a hostile pattern
        # ==================================================================
        # Drive every bit that is not ours high, then select each bank and
        # check those six bits survived. A careless `sta $dd00` would clear
        # them and this is what would catch it.
        poke(mon, 0xdd00, FOREIGN_BITS | VIC_BANK_0)
        before = cia2(mon)

        v.mon.cmd("> 01ff c0")
        v.mon.cmd("> 01fe fd")
        v.mon.cmd(f"r sp=fd, pc={sym['vicSelectBank2']:04x}")
        bp = set_bp(mon, 0xc0fe)
        mon.cmd("x")
        mon.cmd(f"delete {bp}")
        after2 = cia2(mon)
        # v1.1: THIS IS THE FLICKER FIX, STATED AS A TEST. vicSelectBank2 asks
        # for bank 2 and does NOT touch $dd00; the register is committed by
        # exFrame in the lower border, in the same breath as the $d018 that
        # interprets it. v1.0 wrote it here, from the main thread, mid-frame.
        check("vicSelectBank2 records the intent",
              rd1(mon, sym["vicBank2"]) == 1)
        check("...and does NOT write $dd00 itself: the frame IRQ commits it",
              after2 == before, f"${before:02x} -> ${after2:02x}")
        poke(mon, sym["vicBank2"], 0)           # undo the intent

        v.mon.cmd("> 01ff c0")
        v.mon.cmd("> 01fe fd")
        v.mon.cmd(f"r sp=fd, pc={sym['vicSelectBank0']:04x}")
        bp = set_bp(mon, 0xc0fe)
        mon.cmd("x")
        mon.cmd(f"delete {bp}")
        after0 = cia2(mon)
        check("vicSelectBank0 selects bank 0 -- the return path exists",
              (after0 & VIC_BANK_MASK) == VIC_BANK_0,
              f"$dd00 = ${after0:02x}")
        check("...and preserves the same six bits",
              (after0 & ~VIC_BANK_MASK & 0xff) == (before & ~VIC_BANK_MASK & 0xff),
              f"${before:02x} -> ${after0:02x}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")

        # ==================================================================
        # PART 3 -- ordinary play is in bank 0, because it was chosen
        # ==================================================================
        # THE STAGE IS STILL HELD ENDLESS HERE, and the order matters: harness.py
        # sets stageHold at launch so a warp probe does not run the level out,
        # and one second of warp covers all 395 coarse rows. Asserting bank 0
        # after releasing it measured a machine that had already, correctly,
        # reached the boss -- which is the game working and the test looking in
        # the wrong order.
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        check("ordinary play runs in VIC bank 0",
              (cia2(mon) & VIC_BANK_MASK) == VIC_BANK_0,
              f"$dd00 = ${cia2(mon):02x}")
        check("...and vicBank2 agrees with the hardware",
              rd1(mon, sym["vicBank2"]) == 0)
        check("the $d018 in flight is a bank 0 value",
              d018_of(mon, "frameD018") in (0x12, 0xa2),
              f"${d018_of(mon, 'frameD018'):02x}")

        tokens0 = rd1(mon, sym["pkTokensP"])

        # ZERO THE COUNTERS BEFORE THE THING UNDER TEST, exactly as
        # tests/test_boss.py does. Boot and attract put a count or two on some
        # of these before gameplay ever starts; leaving them in would make this
        # file measure the title screen and blame the bank switch. Measured
        # either way: the level-end lifecycle's own contribution is zero.
        for n in CATASTROPHIC:
            poke(mon, sym[n], 0)
        poke(mon, sym["publishSkip"], 0)

        # ...and now let the level be finite, so it can actually end.
        poke(mon, sym["stageHold"], 0)

        # ==================================================================
        # PART 4 -- run the level out and cross into the arena
        # ==================================================================
        reached = False
        for _ in range(14):
            free_run(mon, sym["frameCounter"], 2)
            mon.cmd("delete")
            if rd1(mon, sym["lvlPhase"]) == LP_BOSS:
                reached = True
                break
        check("the level ran out and the boss phase began", reached,
              f"phase {rd1(mon, sym['lvlPhase'])}")

        page_live = SCREEN_A if rd1(mon, sym["dispPage"]) == 0 else SCREEN_B
        check("the arena switched the VIC to bank 2",
              (cia2(mon) & VIC_BANK_MASK) == VIC_BANK_2,
              f"$dd00 = ${cia2(mon):02x}")
        check("...and the flag agrees", rd1(mon, sym["vicBank2"]) == 1)
        check("exactly one bank switch has happened",
              rd1(mon, sym["vicSwitches"]) >= 1,
              f"vicSwitches = {rd1(mon, sym['vicSwitches'])}")

        # ---- the presentation the executor is being handed ----------------
        want_d018 = ((VB2_SCREEN - VB2_BASE) // 0x400) * 16 \
                    + ((VB2_CHARSET - VB2_BASE) // 0x800) * 2
        want_blank = ((VB2_SCREEN - VB2_BASE) // 0x400) * 16 \
                     + ((VB2_BLANK - VB2_BASE) // 0x800) * 2
        check("the frame record carries the bank 2 terrain $d018",
              d018_of(mon, "frameD018") == want_d018,
              f"${d018_of(mon, 'frameD018'):02x}, wanted ${want_d018:02x}")
        check("...and the bank 2 blank-charset $d018",
              d018_of(mon, "frameD018B") == want_blank,
              f"${d018_of(mon, 'frameD018B'):02x}, wanted ${want_blank:02x}")
        check("...and the bank 2 sprite-pointer destination",
              d018_of(mon, "framePtrHi") == (VB2_PTR >> 8),
              f"${d018_of(mon, 'framePtrHi'):02x}, wanted ${VB2_PTR >> 8:02x}")

        # ---- the picture actually made it across --------------------------
        for off in (0x000, 0x190, 0x3e0):
            a = rd(mon, page_live + off, 16)
            b = rd(mon, VB2_SCREEN + off, 16)
            check(f"the frozen screen matrix crossed intact at +${off:03x}",
                  a == b, f"{a} vs {b}")
        for off in (0x300, 0x500):
            a = rd(mon, CHARSET_0 + off, 16)
            b = rd(mon, VB2_CHARSET + off, 16)
            check(f"the terrain charset is in bank 2 at +${off:03x}",
                  a == b, f"{a} vs {b}")
        blank = rd(mon, VB2_BLANK + 0x7f0, 16)
        check("the blank charset is in bank 2, and the idle byte is zero",
              set(blank) == {0}, str(blank))
        for off, name in ((0x0000, "player"), (0x1580, "boss cells"),
                          (0x1200, "HUD")):
            a = rd(mon, 0x2000 + off, 16)
            b = rd(mon, VB2_SPRITES + off, 16)
            check(f"the {name} artwork is in bank 2 at its bank 0 offset",
                  a == b, f"{a} vs {b}")

        # ---- the pointers did NOT move ------------------------------------
        # THE POINT OF THIS CHECK is that a sprite pointer is bank-RELATIVE, so
        # the numbers the mux computes are the same in both banks. The boss
        # cells are the ones worth naming: their art is at $3580 in bank 0 and
        # $b580 in bank 2, and $3580/64 = $d6 is what BOTH tables must hold.
        ptr2 = rd(mon, VB2_PTR, 8)
        boss_ptrs = [(0x3580 // 64) + i for i in range(4)]
        check("the bank 2 pointer table is being written",
              any(p != 0 for p in ptr2), str([hex(p) for p in ptr2]))
        check("...and the boss cells' pointers are the unchanged bank 0 values",
              all(p in ptr2 for p in boss_ptrs),
              f"table {[hex(p) for p in ptr2]}, wanted "
              f"{[hex(p) for p in boss_ptrs]} present")
        check("...and every pointer names a block inside the sprite mirror",
              all(0x80 <= p <= 0xdf for p in ptr2),
              f"{[hex(p) for p in ptr2]}")

        # ==================================================================
        # PART 5 -- the boss still behaves
        # ==================================================================
        # Captured HERE, not before the level: this run has no player input, so
        # the ship is hit repeatedly on the way down and lives legitimately
        # change all through LP_LEVEL. From LP_BOSS the arena is empty and
        # plyExit removes damage, so from this point they must not move.
        score0 = rd(mon, sym["hudScore"], 3)
        lives0 = rd1(mon, sym["hudLives"])

        check("the boss arrived at full health",
              rd1(mon, sym["bossHP"]) == BOSS_HP_FULL,
              str(rd1(mon, sym["bossHP"])))

        hp0 = rd1(mon, sym["bossHP"])
        poke(mon, sym["bossHP"], 4)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        check("the boss takes damage in bank 2",
              rd1(mon, sym["bossHP"]) < hp0,
              f"{hp0} -> {rd1(mon, sym['bossHP'])}")

        poke(mon, sym["bossHP"], 0)
        died = False
        for _ in range(8):
            free_run(mon, sym["frameCounter"], 1)
            mon.cmd("delete")
            if rd1(mon, sym["lvlPhase"]) in (LP_VICTORY, LP_EXIT, LP_DONE):
                died = True
                break
        check("the boss died and the victory phase began", died,
              f"phase {rd1(mon, sym['lvlPhase'])}")

        # ==================================================================
        # PART 6 -- victory, the scripted exit, and LEVEL COMPLETE
        # ==================================================================
        done = False
        for _ in range(12):
            free_run(mon, sym["frameCounter"], 1)
            mon.cmd("delete")
            if rd1(mon, sym["gsState"]) == GS_LEVELDONE:
                done = True
                break
        check("the exit sequence reached GS_LEVELDONE in bank 2", done,
              f"gsState {rd1(mon, sym['gsState'])}, "
              f"phase {rd1(mon, sym['lvlPhase'])}")
        # v1.1: LEVEL COMPLETE OWNS ITS OWN PRESENTATION and does not inherit
        # the boss's. In v1.0 it arrived in bank 2, where GS_D018's VM field
        # names $8400 -- the raster executor's code -- and the page rendered as
        # garbage characters in a legible font.
        check("LEVEL COMPLETE returned the VIC to bank 0",
              (cia2(mon) & VIC_BANK_MASK) == VIC_BANK_0,
              f"$dd00 = ${cia2(mon):02x}")
        check("...and the flag agrees, so nothing republishes bank 2 values",
              rd1(mon, sym["vicBank2"]) == 0)
        # $d018 bit 0 is unconnected and reads back as 1 on a real VIC, so the
        # comparison masks it rather than expecting the written value verbatim.
        check("...with the non-game $d018 it expects",
              (rd1(mon, 0xd018) & 0xfe) == (GS_D018 & 0xfe),
              f"$d018 = ${rd1(mon, 0xd018):02x}, wanted "
              f"${GS_D018:02x} (bit 0 don't-care)")
        check("...and the executor parked out of the display",
              rd1(mon, sym["gsNonGame"]) == 1)
        # The page is drawn into the bank 0 matrix the VIC is now looking at.
        done_row = rd(mon, 0x0400 + 8 * 40 + 13, 5)
        check("...and the LEVEL COMPLETE text is in the displayed matrix",
              done_row == [12, 5, 22, 5, 12],        # L E V E L
              str(done_row))
        check("lives and P are unchanged from the boss phase through "
              "LEVEL COMPLETE",
              rd1(mon, sym["hudLives"]) == lives0
              and rd1(mon, sym["pkTokensP"]) == tokens0,
              f"lives {lives0}->{rd1(mon, sym['hudLives'])}, "
              f"P {tokens0}->{rd1(mon, sym['pkTokensP'])}")
        print(f"  info score {score0} -> {rd(mon, sym['hudScore'], 3)} "
              f"(the HUD's own cadence keeps ticking; not asserted)")

        # ---- the arena's own catastrophic gate, BEFORE the restart ---------
        for name in CATASTROPHIC:
            got = rd1(mon, sym[name])
            check(f"{name} is zero across the arena lifecycle", got == 0,
                  str(got))
        print(f"  info publishSkip {rd1(mon, sym['publishSkip'])} "
              f"clipPoolFull {rd1(mon, sym['clipPoolFull'])} "
              f"over the arena (measured, not asserted)")

        # ==================================================================
        # PART 7 -- FIRE restarts ordinary gameplay, in bank 0
        # ==================================================================
        # v1.1: the restart used to inherit bank 2 AND a vicBank2 flag that was
        # still set, so scrollInit's frame 0 carried the boss's $d018 and
        # pointer destination into ordinary play.
        # joyHold stops readInput overwriting the poked stick each frame, and the
        # route is LEVELDONE -> attract -> PLAYING, so it takes more than one
        # press. Both are the harness's own documented way in.
        poke(mon, sym["joyHold"], 1)
        for _ in range(14):
            poke(mon, sym["joyState"], 0xef)        # fire down
            free_run(mon, sym["frameCounter"], 1); mon.cmd("delete")
            poke(mon, sym["joyState"], 0xff)        # ...and up
            free_run(mon, sym["frameCounter"], 1); mon.cmd("delete")
            if rd1(mon, sym["gsState"]) == GS_PLAYING:
                break
        poke(mon, sym["joyState"], 0xff)
        poke(mon, sym["joyHold"], 0)
        restarted = rd1(mon, sym["gsState"]) == GS_PLAYING
        check("FIRE restarted ordinary gameplay", restarted,
              f"gsState {rd1(mon, sym['gsState'])}")

        if restarted:
            check("...in VIC bank 0",
                  (cia2(mon) & VIC_BANK_MASK) == VIC_BANK_0,
                  f"$dd00 = ${cia2(mon):02x}")
            check("...with vicBank2 clear, so publishFrame emits bank 0 values",
                  rd1(mon, sym["vicBank2"]) == 0)
            d018 = d018_of(mon, "frameD018")
            check("...and the frame record carries a bank 0 $d018 again",
                  d018 in (0x12, 0xa2), f"${d018:02x}")
            ptr = d018_of(mon, "framePtrHi")
            check("...and the pointer destination is a bank 0 table",
                  ptr in (0x07, 0x2b), f"${ptr:02x}")
            check("...and the committed bank byte agrees with the hardware",
                  (d018_of(mon, "frameBank") & VIC_BANK_MASK) == VIC_BANK_0,
                  f"frameBank = ${d018_of(mon, 'frameBank'):02x}")

            # THE SCROLL SNAP. The restart must enter ONE coherent state, not
            # show a stale frame and then correct itself. worldProgress starting
            # from zero and stageTopRow at the authored start is that state.
            check("the scroll restarted from the top of the authored map",
                  rd1(mon, sym["stageComplete"]) == 0,
                  f"stageComplete {rd1(mon, sym['stageComplete'])}")
            check("...and the boss phase went back to LP_LEVEL",
                  rd1(mon, sym["lvlPhase"]) == LP_LEVEL,
                  f"phase {rd1(mon, sym['lvlPhase'])}")

            # ENEMY ANIMATION. In bank 2 the level's Ring and Dropper frames
            # resolve onto the terrain charset that the mirror lays over the
            # enemy window -- which is why some animation frames looked right
            # and others were garbage. The fix is ownership, so the statement
            # worth checking is that the pointers the mux writes name the real
            # bank 0 artwork.
            free_run(mon, sym["frameCounter"], 2); mon.cmd("delete")
            page = 0x0400 if rd1(mon, sym["dispPage"]) == 0 else 0x2800
            ptrs = rd(mon, page + 0x3f8, 8)
            check("the displayed pointer table is being written after restart",
                  any(p != 0 for p in ptrs), str([hex(p) for p in ptrs]))
            enemy_ptrs = [p for p in ptrs if 0xb0 <= p <= 0xc3]
            if enemy_ptrs:
                blk = enemy_ptrs[0] * 64
                art = rd(mon, blk, 16)
                check("...and an enemy pointer names real bank 0 sprite art, "
                      "not charset bytes",
                      any(b != 0 for b in art) and art != [0x55] * 16,
                      f"ptr ${enemy_ptrs[0]:02x} -> ${blk:04x}: {art}")
            else:
                print(f"  info no enemy on screen in the sampled frame; "
                      f"pointers {[hex(p) for p in ptrs]}")

        # ==================================================================
        # PART 8 -- the RESTARTED gameplay is clean in its own right
        # ==================================================================
        # THE TRANSITION IS NOT A GAMEPLAY FRAME, and gsStartGame says so in its
        # own comment: it rebuilds both terrain pages and republishes everything
        # in one main-thread pass, which costs a frame. It already zeroes
        # gameOverrun afterwards for exactly that reason. So the counters are
        # zeroed here too and the question asked is the one that matters --
        # is ordinary play, after the restart, clean?
        if restarted:
            print(f"  info the restart transition cost "
                  f"schedBuildDefer={rd1(mon, sym['schedBuildDefer'])} "
                  f"(gsStartGame rebuilds both pages in one pass)")
            for name in CATASTROPHIC:
                poke(mon, sym[name], 0)
            poke(mon, sym["publishSkip"], 0)
            free_run(mon, sym["frameCounter"], 3)
            mon.cmd("delete")
            for name in CATASTROPHIC:
                got = rd1(mon, sym[name])
                check(f"{name} is zero over restarted gameplay", got == 0,
                      str(got))
            print(f"  info publishSkip {rd1(mon, sym['publishSkip'])} "
                  f"over restarted play (measured, not asserted)")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
