#!/usr/bin/env python3
"""The HUD survives the boss transition: bank 2 is a FEED, not a photograph.

The bug this file exists for
----------------------------
The HUD's bitmaps live at $3200, in VIC bank 0. The boss arena switches the VIC
to bank 2, where the same sprite pointers resolve to $b200 -- a MIRROR of those
bitmaps that src/vicbank.asm walks across a slice a frame. Two defects made that
mirror stop describing the game:

  1. vicMirrorTick was called from bossClearTick and NOWHERE ELSE, so the block
     stopped crossing at the instant the bank changed. Everything the HUD drew
     for the rest of the level was drawn into bytes the VIC was no longer
     reading. The score froze, the heat bar froze -- while its overheat flash
     kept working, because colour is a VIC REGISTER and not bank data.

  2. vicMirrorHud computed the slice's byte offset with `asl`, which is n * 2
     where n * 128 was meant. Only slice 0 was right; the block was walked with
     three 130-byte holes in it, and two of them sat exactly over the score
     sprites and P charge blocks 0 and 1. MEASURED AT 506 OF 896 BYTES. That is
     why the score read 000000 -- the boot image, never once overwritten --
     rather than freezing at the score the player actually had.

What this proves
----------------
* the mirror tiles the HUD block EXACTLY: 896 of 896 bytes cross in one pass;
* the bank switch cannot happen over a half-copied picture -- vicMirrorDone is
  set at the instant bossSpawn runs;
* across boss entry the authoritative score, lives, pkTokensP and pkCharge are
  all preserved;
* the bank 2 bitmaps the VIC is actually reading MATCH the bank 0 originals for
  the score, the heat gauge and the live P charge block;
* a score change DURING the boss fight reaches bank 2;
* a heat change during the boss fight moves the bar and reaches bank 2;
* overheat flashing still operates during the boss fight;
* the boss itself still arrives at full health and still takes damage;
* no renderer/mux/raster diagnostic regresses, and the HUD's write window is
  still never violated.

What this does NOT prove
------------------------
That any of it LOOKS right. Manual VICE is authoritative -- see AGENTS.md.

One VICE launch.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, check, report)

sym = symbols(SYM)
PORT = 6683

LP_LEVEL, LP_CLEARING, LP_BOSS = 0, 1, 2
BOSS_HP_FULL = 50
VIC_BANK_MASK, VIC_BANK_2 = 0b11, 0b01

HUD_SPRITES = 0x3200
HUD_BYTES   = 14 * 64               # HUD_BLOCKS * 64
VB_SLICE    = 128
VB_HUD_SLICES = HUD_BYTES // VB_SLICE
MIRROR      = 0x8000                # VB2_BASE: bank 2 is bank 0 + $8000

HEAT_L, HEAT_R   = HUD_SPRITES + 0 * 64, HUD_SPRITES + 1 * 64
SCORE_L, SCORE_R = HUD_SPRITES + 2 * 64, HUD_SPRITES + 3 * 64

HUD_HEAT_COL_ALARM, HUD_HEAT_COL_BLANK = 0x02, 0x00
WPN_HEAT_MAX_ISH = 295              # comfortably inside the lockout

# The project's own definition of catastrophic, copied from test_bank2_arena.py
# rather than invented here.
CATASTROPHIC = ("gameOverrun", "scrollLate", "statPageMismatch",
                "statPtrMismatch", "objDoubleFree", "objAllocFail")


class Stepper:
    """One accepted sample per displayed frame, at an armed breakpoint.

    free_run takes SECONDS OF WARP, and a seven-frame mirror cycle is over
    before the first sample. THE MAIN LOOP'S IDLE SPIN RUNS BETWEEN THESE
    STOPS, which is where vicMirrorLive lives -- so stepping at gameFrame does
    let the mirror advance.
    """
    def __init__(self, mon):
        self.mon, self.last = mon, None

    def step(self, tries=8):
        for _ in range(tries):
            self.mon.cmd("x")
            f = rd(self.mon, sym["frameCounter"], 2)
            fc = f[0] | (f[1] << 8)
            if fc != self.last:
                self.last = fc
                return fc
        raise RuntimeError("the machine stopped advancing frames")

    def run(self, n):
        for _ in range(n):
            self.step()


def pc_of(reply):
    """The PC out of the monitor's own "(C:$xxxx)" prompt, or None.

    `mon.cmd("x")` RETURNS ON AN IDLE SOCKET AS WELL AS ON A STOP -- the trap
    harness.py documents -- so "the breakpoint fired" cannot be inferred from
    the call returning. The prompt carries the address it stopped at, and that
    is the only thing that answers the question.
    """
    m = re.search(r"\(C:\$([0-9a-fA-F]{4})\)", reply)
    return int(m.group(1), 16) if m else None


def run_to(mon, addr, tries=40):
    """Resume until the machine is genuinely stopped at `addr`."""
    for _ in range(tries):
        if pc_of(mon.cmd("x")) == addr:
            return True
        if pc_of(mon.cmd("r")) == addr:
            return True
    return False


def poke_checked(mon, addr, val, tries=6):
    for _ in range(tries):
        poke(mon, addr, val)
        if rd1(mon, addr) == (val & 0xff):
            return
    raise RuntimeError(f"could not write ${addr:04x} = {val:02x}")


def block(mon, addr, n=64):
    """n bytes, read in 16-byte-aligned chunks rd() can verify."""
    out = []
    while len(out) < n:
        out += rd(mon, addr + len(out), min(64, n - len(out)))
    return out[:n]


def both_banks(mon, addr, n=64):
    return block(mon, addr, n), block(mon, addr + MIRROR, n)


def converge(mon, stepper, addr, n, limit=30):
    """Step until the bank 2 copy of `addr` matches bank 0, or give up.

    Returns (matched, frames). The mirror is a lagging feed by design -- one
    slice per displayed frame, so a whole block is current again within
    VB_HUD_SLICES frames plus whatever the raster window deferred.
    """
    for i in range(limit):
        a, b = both_banks(mon, addr, n)
        if a == b:
            return True, i
        stepper.step()
    a, b = both_banks(mon, addr, n)
    return a == b, limit


def main():
    print("=== boss transition HUD regression ===")
    v = None
    try:
        v = Vice(PORT, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # ==================================================================
        # PART 1 -- ordinary play, and a HUD made deliberately distinctive
        # ==================================================================
        check("ordinary play is in VIC bank 0",
              rd1(mon, sym["vicBank2"]) == 0
              and (rd1(mon, 0xdd00) & VIC_BANK_MASK) != VIC_BANK_2,
              f"$dd00 = ${rd1(mon, 0xdd00):02x}")

        # A score with no repeated digit, so a stale sprite cannot accidentally
        # match a fresh one, and a P state whose digit is NOT in charge block 0
        # -- block 0 is the one the boot image happens to carry a digit in, and
        # a test that used it would pass against the very bug it is here for.
        for i, d in enumerate((1, 2, 3, 4, 5, 6)):
            poke_checked(mon, sym["hudScore"] + i, d)
        poke_checked(mon, sym["pkTokensP"], 7)
        poke_checked(mon, sym["pkCharge"], 2)
        poke_checked(mon, sym["hudPCharge"], 2)     # -> charge block 2
        poke_checked(mon, sym["hudPShown"], 7)
        poke_checked(mon, sym["hudDirty"], 0x0f)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")

        # CAPTURED AFTER THE FRAMES RAN, not from what was poked: hudDemoTick
        # still bumps the score every eight frames, so the poke is a way of
        # making the sprite distinctive rather than a value to assert on.
        score0 = rd(mon, sym["hudScore"], 6)
        lives0 = rd1(mon, sym["hudLives"])
        tokens0, charge0 = rd1(mon, sym["pkTokensP"]), rd1(mon, sym["pkCharge"])
        check("the score is a distinctive value, not the boot image",
              score0 != [0] * 6, str(score0))
        check("...and the P digit is stamped in a charge block the boot image "
              "left blank",
              rd1(mon, sym["hudPtrLive"] + 5) != (HUD_SPRITES // 64) + 10,
              f"pointer ${rd1(mon, sym['hudPtrLive'] + 5):02x}")

        for n in CATASTROPHIC:
            poke(mon, sym[n], 0)
        poke(mon, sym["hudUpdWrapped"], 0)
        poke(mon, sym["vicMirrorRuns"], 0)
        check("the live mirror does nothing at all in bank 0",
              rd1(mon, sym["vicMirrorRuns"]) == 0)

        # ==================================================================
        # PART 2 -- THE GATE: the bank cannot be selected over half a picture
        # ==================================================================
        # Read at the instruction that switches the bank, which is the only
        # place the question has a single answer.
        poke(mon, sym["stageHold"], 0)          # let the level be finite
        bp = set_bp(mon, sym["bossSpawn"])
        spawned = run_to(mon, sym["bossSpawn"])
        done_at_spawn = rd1(mon, sym["vicMirrorDone"])
        screen_at_spawn = rd1(mon, sym["vicScreenAt"])
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        check("bossSpawn was reached", spawned,
              f"phase {rd1(mon, sym['lvlPhase'])}")
        check("THE WHOLE PICTURE HAD CROSSED before the bank switch: "
              "vicMirrorDone is set at bossSpawn",
              done_at_spawn == 1, f"vicMirrorDone = {done_at_spawn}, "
              f"vicScreenAt = {screen_at_spawn}")

        # ==================================================================
        # PART 3 -- the boss phase, and what the VIC can actually see
        # ==================================================================
        stepper = Stepper(mon)
        set_bp(mon, sym["gameFrame"])
        reached = False
        for _ in range(40):
            stepper.step()
            if rd1(mon, sym["lvlPhase"]) == LP_BOSS:
                reached = True
                break
        check("the boss phase began", reached,
              f"phase {rd1(mon, sym['lvlPhase'])}")
        check("...in VIC bank 2",
              (rd1(mon, 0xdd00) & VIC_BANK_MASK) == VIC_BANK_2
              and rd1(mon, sym["vicBank2"]) == 1,
              f"$dd00 = ${rd1(mon, 0xdd00):02x}")
        check("the boss arrived at full health",
              rd1(mon, sym["bossHP"]) == BOSS_HP_FULL,
              str(rd1(mon, sym["bossHP"])))

        # ---- authoritative state survived the transition -------------------
        # hudDemoTick still drives the tens digit, so the top three are the
        # part of the number the transition must not have touched.
        score1 = rd(mon, sym["hudScore"], 6)
        check("the authoritative score is preserved across boss entry",
              score1[:3] == score0[:3] and score1 != [0] * 6,
              f"{score0} -> {score1}")
        # LIVES ARE CAPTURED HERE, NOT BEFORE THE LEVEL RAN OUT. This run has
        # no player input, so the parked ship is shot at all through LP_LEVEL
        # and lives change legitimately on the way to the arena -- the same
        # reason tests/test_bank2_arena.py samples them at this point. What the
        # transition must not do is RESET them, and from here the arena is
        # empty so they must not move at all.
        lives1 = rd1(mon, sym["hudLives"])
        check("lives were carried into the arena, not reset",
              0 < lives1 <= lives0, f"{lives0} -> {lives1}")
        check("...and the spendable P count and its partial charge",
              rd1(mon, sym["pkTokensP"]) == tokens0
              and rd1(mon, sym["pkCharge"]) == charge0,
              f"P {tokens0}->{rd1(mon, sym['pkTokensP'])}, "
              f"charge {charge0}->{rd1(mon, sym['pkCharge'])}")

        # ---- ...and the DISPLAY of it made the crossing --------------------
        # THIS IS THE WHOLE BUG. Bank 0 kept being drawn correctly all along;
        # the question was only ever whether the bytes the VIC now reads say
        # the same thing.
        for name, addr in (("score, left", SCORE_L), ("score, right", SCORE_R),
                           ("heat gauge, left", HEAT_L),
                           ("heat gauge, right", HEAT_R)):
            ok, frames = converge(mon, stepper, addr, 64)
            a, b = both_banks(mon, addr, 64)
            check(f"the bank 2 {name} sprite matches the bank 0 original", ok,
                  f"converged in {frames} frames"
                  if ok else f"bank0 {a[18:26]} vs bank2 {b[18:26]}")

        pblock = rd1(mon, sym["hudPtrLive"] + 5) * 64
        ok, frames = converge(mon, stepper, pblock, 64)
        a, b = both_banks(mon, pblock, 64)
        check("the bank 2 P charge block on the pointer matches bank 0 -- "
              "boxes AND the spendable digit", ok,
              f"block ${pblock:04x}, converged in {frames} frames"
              if ok else f"bank0 {a[23:32]} vs bank2 {b[23:32]}")
        digit = [a[7 * 3 + 2 + r * 3] for r in range(8)]
        check("...and that digit is actually drawn, not blank",
              any(x for x in digit), str([hex(x) for x in digit]))

        # ==================================================================
        # PART 4 -- the HUD is LIVE during the fight, not a still
        # ==================================================================
        # ---- the score keeps displaying its actual value -------------------
        before = block(mon, SCORE_R, 64)
        for i, d in enumerate((9, 8, 7, 6, 5, 4)):
            poke_checked(mon, sym["hudScore"] + i, d)
        poke_checked(mon, sym["hudDirty"], 0x04)    # HUD_DIRTY_SCORE
        stepper.run(2)
        after0 = block(mon, SCORE_R, 64)
        check("a score change during the boss fight redraws the bank 0 sprite",
              after0 != before)
        ok, frames = converge(mon, stepper, SCORE_R, 64)
        check("...and REACHES BANK 2, which is what the player sees", ok,
              f"converged in {frames} frames")
        check("...and it is the new score, not the old one",
              block(mon, SCORE_R + MIRROR, 64) != before)

        # ---- the heat gauge keeps following the weapon ---------------------
        pix0 = rd1(mon, sym["hudHeatPix"])
        bar0 = block(mon, HEAT_L, 64)
        for _ in range(4):
            poke_checked(mon, sym["wpnHeatLo"], WPN_HEAT_MAX_ISH & 0xff)
            poke_checked(mon, sym["wpnHeatHi"], WPN_HEAT_MAX_ISH >> 8)
            stepper.step()
        pix1 = rd1(mon, sym["hudHeatPix"])
        check("heat fed during the boss fight moves the gauge's fill",
              pix1 > pix0, f"{pix0} -> {pix1} pixels of {48}")
        check("...and the bank 0 bar bitmap was redrawn",
              block(mon, HEAT_L, 64) != bar0)
        # Hold the value steady so the lagging feed has something to converge
        # ON: a bar that moves every frame can never be caught by a mirror that
        # is deliberately a few frames behind it.
        for _ in range(VB_HUD_SLICES + 2):
            poke(mon, sym["wpnHeatLo"], WPN_HEAT_MAX_ISH & 0xff)
            poke(mon, sym["wpnHeatHi"], WPN_HEAT_MAX_ISH >> 8)
            stepper.step()
        a, b = both_banks(mon, HEAT_L, 64)
        check("...and the filled bar reached bank 2", a == b,
              f"bank0 {a[18:24]} vs bank2 {b[18:24]}")

        # ---- overheat flashing still operates ------------------------------
        # COLOUR IS A VIC REGISTER, NOT BANK DATA, which is exactly why this
        # kept working while the bar beside it froze -- the single most useful
        # piece of evidence in the whole diagnosis. It is asserted here so a
        # future "fix" cannot quietly route it through the bitmap instead.
        seen = set()
        for _ in range(48):
            poke(mon, sym["wpnOverheated"], 1)
            poke(mon, sym["wpnHeatLo"], WPN_HEAT_MAX_ISH & 0xff)
            poke(mon, sym["wpnHeatHi"], WPN_HEAT_MAX_ISH >> 8)
            stepper.step()
            seen.add(rd1(mon, sym["hudCol"] + 1))
        check("the overheat alarm still flashes during the boss fight",
              HUD_HEAT_COL_ALARM in seen and HUD_HEAT_COL_BLANK in seen,
              f"colours seen: {sorted(hex(c) for c in seen)}")
        check("...on both halves of the gauge together",
              rd1(mon, sym["hudCol"] + 1) == rd1(mon, sym["hudCol"] + 2),
              f"{rd1(mon, sym['hudCol'] + 1)} / {rd1(mon, sym['hudCol'] + 2)}")
        poke(mon, sym["wpnOverheated"], 0)

        # ---- the boss's own display is unaffected --------------------------
        # ITS HEALTH BAR IS COLOUR RAM, which is in no VIC bank at all -- so it
        # was never part of this bug and must still not be. bossDrawBar is
        # called from the damage path rather than from bossFightTick, so it is
        # driven directly here rather than by poking HP and waiting.
        mon.cmd("delete")
        poke_checked(mon, sym["bossHP"], 20)
        mon.cmd("> 01ff c0")
        mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={sym['bossDrawBar']:04x}")
        bb = set_bp(mon, 0xc0fe)
        mon.cmd("x")
        mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
        bar = [x & 0x0f for x in rd(mon, 0xd800 + 1 * 40 + 8, 25)]
        check("the boss health bar still tracks its HP, in colour RAM",
              rd1(mon, sym["bossBarDrawn"]) == 10
              and bar[:10] == [0x0a] * 10 and bar[10:] == [0x09] * 15,
              f"bossBarDrawn = {rd1(mon, sym['bossBarDrawn'])} for HP 20, "
              f"bar = {[hex(c) for c in bar]}")
        set_bp(mon, sym["gameFrame"])
        stepper.last = None
        hp0 = rd1(mon, sym["bossHP"])
        poke_checked(mon, sym["bossHP"], 4)
        stepper.run(3)
        check("the boss still takes damage in bank 2",
              rd1(mon, sym["bossHP"]) <= 4, f"{hp0} -> "
              f"{rd1(mon, sym['bossHP'])}")

        # ==================================================================
        # PART 5 -- nothing else regressed
        # ==================================================================
        mon.cmd("delete")
        for name in CATASTROPHIC:
            got = rd1(mon, sym[name])
            check(f"{name} is zero across the boss transition", got == 0,
                  str(got))
        check("the HUD's write window was never violated: hudUpdWrapped is zero",
              rd1(mon, sym["hudUpdWrapped"]) == 0,
              str(rd1(mon, sym["hudUpdWrapped"])))
        check("lives did not move during the boss fight itself",
              rd1(mon, sym["hudLives"]) == lives1,
              f"{lives1} -> {rd1(mon, sym['hudLives'])}")
        runs = rd1(mon, sym["vicMirrorRuns"])
        check("the live mirror ran throughout the boss fight", runs > 0,
              f"vicMirrorRuns = {runs} (saturating at 255)")
        print(f"  info publishSkip {rd1(mon, sym['publishSkip'])} "
              f"schedBuildDefer {rd1(mon, sym['schedBuildDefer'])} "
              f"(measured, not asserted)")

        # ==================================================================
        # PART 6 -- THE SLICE ARITHMETIC. Destructive, so it goes last.
        # ==================================================================
        # Fill the HUD block with a pattern that changes every sixteen bytes,
        # zero the mirror, and drive exactly one full cycle of the cursor by
        # hand. Every byte must have crossed: this is the check that fails at
        # 506 of 896 if the n * 128 offset is ever written as n * 2 again.
        mon.cmd("delete")
        for off in range(0, HUD_BYTES, 16):
            pat = " ".join([f"{(0x41 + (off // 16)) & 0xff:02x}"] * 16)
            mon.cmd(f"> {HUD_SPRITES + off:04x} {pat}")
            mon.cmd(f"> {HUD_SPRITES + MIRROR + off:04x} " + " ".join(["00"] * 16))
        poke(mon, sym["vicMirrorAt"], 0)
        poke(mon, sym["vicScreenAt"], 8)        # the screen has already crossed
        mon.cmd("> 01ff c0")
        for _ in range(VB_HUD_SLICES):
            mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym['vicMirrorHud']:04x}")
            bb = set_bp(mon, 0xc0fe)
            mon.cmd("x")
            mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")

        src, dst = [], []
        for off in range(0, HUD_BYTES, 64):
            src += rd(mon, HUD_SPRITES + off, 64)
            dst += rd(mon, HUD_SPRITES + MIRROR + off, 64)
        crossed = sum(1 for i in range(HUD_BYTES) if src[i] == dst[i])
        check(f"one cursor cycle crosses the WHOLE HUD block: "
              f"{crossed} of {HUD_BYTES} bytes",
              crossed == HUD_BYTES,
              f"{HUD_BYTES - crossed} bytes never copied")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
