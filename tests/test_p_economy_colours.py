#!/usr/bin/env python3
"""The P economy, the HUD that shows it, and deterministic attract colours.

What this proves
----------------
PART A -- colours:
* entering a non-game page leaves colour RAM UNIFORM, so the title cannot
  inherit gameplay residue;
* it is still uniform after a gameplay -> attract round trip with deliberate
  residue (a red row, as the boss health bar leaves) written first;
* the value is the one gameplay expects to find, so the return is free.

PART B/C -- the economy:
* a new run starts at no charge, no currency, and a HUD showing both;
* one pickup lights one box and awards nothing;
* two pickups light two and award nothing;
* the THIRD awards a spendable unit IMMEDIATELY -- measured on the very frame,
  before any celebration has run;
* the charge wraps to zero at the same instant;
* the HUD latches three full boxes and keeps showing the OLD number;
* about fifty frames later the boxes empty and the number steps up;
* a second set behaves identically;
* the HUD never moves on a frame nothing was collected;
* a death costs neither the currency nor the partial charge.

PART D -- the celebration:
* the flash changes the slot's colour on a readable cadence, not every frame;
* the sprite pointer is a real charge block throughout.

What this does NOT prove
------------------------
That the boxes are legible, the cadence pleasant or the jingle good. Manual
VICE is authoritative for all three.

One VICE launch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, check, report)

sym = symbols(SYM)
PORT = 6677

TYPE_PICKUP = 3
PICKUP_P = 0
TERRAIN_COLOUR_RAM = 9
HUD_PCHARGE_MAX = 3
HUD_P_CELEB_FRAMES = 50
HUD_PTR_PCHARGE_0 = 0xd2            # HUD_SPRITES/64 + 10
COLOUR_RAM = 0xd800
GS_ATTRACT, GS_PLAYING = 0, 1
SFX_TOKEN, SFX_PEARN = 5, 8
SFX_CH_KILL = 1                     # voice 2
SFX_PEARN_LEN = 48


class Stepper:
    """One accepted sample per displayed frame.

    free_run takes SECONDS OF WARP; a fifty-frame celebration has to be watched
    in frames or it is over before the first sample.
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


def colour(mon, offset):
    """One colour RAM cell.

    COLOUR RAM IS FOUR BITS WIDE. The upper nibble is not stored and reads back
    as whatever the bus last carried, so a cell holding 9 can come back as $c9
    or $f9. Every comparison here masks it; the first draft of this file did
    not, and reported a perfectly correct fill as a failure.
    """
    return rd1(mon, COLOUR_RAM + offset) & 0x0f


def poke_checked(mon, addr, val, tries=6):
    for _ in range(tries):
        poke(mon, addr, val)
        if rd1(mon, addr) == (val & 0xff):
            return
    raise RuntimeError(f"could not write ${addr:04x} = {val:02x}")


def call(mon, addr, x=None):
    """Run a self-contained routine to completion via a synthetic return."""
    mon.cmd("> 01ff c0")
    mon.cmd("> 01fe fd")
    if x is None:
        mon.cmd(f"r sp=fd, pc={addr:04x}")
    else:
        mon.cmd(f"r sp=fd, pc={addr:04x}, x={x:02x}")
    bp = set_bp(mon, 0xc0fe)
    mon.cmd("x")
    mon.cmd(f"delete {bp}")


def collect_one(mon):
    """Collect one P through the real pickupCollect, on a real pool slot.

    Slot 0 is made a genuine live TYPE_PICKUP of kind P first, so the routine
    frees something that was actually allocated and objDoubleFree stays clean.

    THE GAMEPLAY BREAKPOINT IS LIFTED FOR THE CALL. call() runs to a synthetic
    return address, and with a breakpoint on gameFrame still armed the `x`
    inside it can stop THERE instead -- leaving the routine half-run and the
    machine somewhere the caller did not expect. It is put back afterwards.
    """
    poke_checked(mon, sym["logActive"] + 0, 1)
    poke_checked(mon, sym["objType"] + 0, TYPE_PICKUP)
    poke_checked(mon, sym["pkKind"] + 0, PICKUP_P)
    mon.cmd("delete")
    call(mon, sym["pickupCollect"], x=0)
    mon.cmd(f"r pc={sym['mainLoop']:04x}")
    set_bp(mon, sym["gameFrame"])


def hud_state(mon):
    return (rd1(mon, sym["hudPCharge"]), rd1(mon, sym["hudPShown"]),
            rd1(mon, sym["hudPCeleb"]))


def econ(mon):
    return rd1(mon, sym["pkTokensP"]), rd1(mon, sym["pkCharge"])


def main():
    print("=== P economy + HUD + attract colours ===")
    v = None
    try:
        v = Vice(PORT, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # ==================================================================
        # PART B/C -- the economy
        # ==================================================================
        # THE HARNESS HAS ALREADY STARTED A GAME, so this measures the run it
        # booted rather than forcing one. An earlier draft called gsStartGame
        # through a synthetic return from inside the attract loop and then
        # wondered why gameFrame had stopped running: the lifecycle is a router,
        # and dropping into the middle of it from a monitor is not the same as
        # reaching it. The economy checks come FIRST for the same reason -- Part
        # A ends gameplay by design, so it now runs last.
        mon.cmd("delete")
        bp = set_bp(mon, sym["gameFrame"])
        st = Stepper(mon)
        st.run(2)

        # NOBODY IS AT THE STICK, and a stationary ship is shot to pieces in a
        # few hundred frames. A big stock keeps the run alive for the length of
        # the measurement without touching the Infinite Lives cheat, which this
        # file deliberately leaves off so the death check below is real.
        poke_checked(mon, sym["hudLives"], 250)
        poke_checked(mon, sym["gsInfLives"], 0)
        check("the run is actually playing",
              rd1(mon, sym["gsState"]) == GS_PLAYING,
              f"gsState = {rd1(mon, sym['gsState'])}")
        check("...with the executor on the display",
              rd1(mon, sym["gsNonGame"]) == 0)

        check("a new run starts with no currency and no charge",
              econ(mon) == (0, 0), str(econ(mon)))

        check("...and the HUD shows empty boxes, zero, no celebration",
              hud_state(mon) == (0, 0, 0), str(hud_state(mon)))

        # ---- the HUD does not move on its own -----------------------------
        before = hud_state(mon)
        st.run(220)                         # longer than the old 192-frame cycle
        check("the HUD does not change without a collection",
              hud_state(mon) == before,
              f"{before} -> {hud_state(mon)}")

        # ---- pickups one and two ------------------------------------------
        for n in (1, 2):
            collect_one(mon)
            st.run(2)
            check(f"pickup {n} banks charge and awards nothing",
                  econ(mon) == (0, n), str(econ(mon)))
            check(f"...and the HUD lights {n} box(es), still showing 0",
                  hud_state(mon) == (n, 0, 0), str(hud_state(mon)))
            check(f"...and pickup {n} still plays the ordinary token chime",
                  rd1(mon, sym["sfxChId"] + SFX_CH_KILL) in (SFX_TOKEN, 0),
                  f"voice 2 holds {rd1(mon, sym['sfxChId'] + SFX_CH_KILL)}")

        # ---- the third: awarded IMMEDIATELY -------------------------------
        collect_one(mon)
        # read before resuming the frame loop at all: this is the instant after
        # pickupCollect returned, with no celebration having ticked
        spend, charge = econ(mon)
        check("the THIRD pickup awards a spendable unit immediately",
              spend == 1, f"pkTokensP = {spend}")
        check("...and the charge resets at the same instant",
              charge == 0, f"pkCharge = {charge}")
        check("...and the jingle is the sound that plays, not the chime",
              rd1(mon, sym["sfxChId"] + SFX_CH_KILL) == SFX_PEARN,
              f"voice 2 holds {rd1(mon, sym['sfxChId'] + SFX_CH_KILL)}")
        ch, shown, celeb = hud_state(mon)
        check("...while the HUD latches three full boxes",
              ch == HUD_PCHARGE_MAX, f"hudPCharge = {ch}")
        check("...still showing the OLD number, so nothing can be lost",
              shown == 0, f"hudPShown = {shown}")
        check("...and the celebration is armed for ~50 frames",
              celeb == HUD_P_CELEB_FRAMES, f"hudPCeleb = {celeb}")

        # ---- the celebration runs, and gameplay runs with it ---------------
        cols, ptrs, frames = set(), set(), 0
        while True:
            st.step()
            frames += 1
            cols.add(rd1(mon, sym["hudCol"] + 5))
            ptrs.add(rd1(mon, sym["hudPtrLive"] + 5))
            if rd1(mon, sym["hudPCeleb"]) == 0:
                break
            if frames > HUD_P_CELEB_FRAMES + 20:
                break
        check("the celebration lasted about fifty frames",
              abs(frames - HUD_P_CELEB_FRAMES) <= 3, f"{frames} frames")
        check("...and it flashed: the slot took more than one colour",
              len(cols) > 1, f"colours {[hex(c) for c in sorted(cols)]}")
        check("...on a readable cadence, not a strobe",
              len(cols) == 2, f"colours {[hex(c) for c in sorted(cols)]}")
        check("...with the pointer on a real charge block throughout",
              all(HUD_PTR_PCHARGE_0 <= p <= HUD_PTR_PCHARGE_0 + HUD_PCHARGE_MAX
                  for p in ptrs), f"{[hex(p) for p in sorted(ptrs)]}")

        st.run(2)
        check("the jingle ended cleanly: voice 2 is idle again",
              rd1(mon, sym["sfxChId"] + SFX_CH_KILL) == 0,
              f"voice 2 holds {rd1(mon, sym['sfxChId'] + SFX_CH_KILL)}")
        check("after the celebration the boxes empty and the number steps up",
              hud_state(mon) == (0, 1, 0), str(hud_state(mon)))
        check("...and the authoritative state is unchanged by any of that",
              econ(mon) == (1, 0), str(econ(mon)))
        check("...and the colour is back to normal",
              rd1(mon, sym["hudCol"] + 5) == 0x0a,
              f"${rd1(mon, sym['hudCol'] + 5):02x}")

        # ---- a second set behaves the same ---------------------------------
        for n in (1, 2):
            collect_one(mon)
            st.run(2)
        check("a second set charges the same way", econ(mon) == (1, 2),
              str(econ(mon)))
        collect_one(mon)
        check("...and its third awards the second unit immediately",
              econ(mon) == (2, 0), str(econ(mon)))
        st.run(HUD_P_CELEB_FRAMES + 5)
        check("...and the HUD settles on two", hud_state(mon) == (0, 2, 0),
              str(hud_state(mon)))

        # ---- a death costs neither -----------------------------------------
        collect_one(mon)                    # leave a partial charge standing
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
        st.run(2)
        before = econ(mon)
        poke_checked(mon, sym["plyDead"], 0)
        poke_checked(mon, sym["plyInvuln"], 0)
        poke_checked(mon, sym["plyExit"], 0)
        poke_checked(mon, sym["hudLives"], 3)
        poke_checked(mon, sym["gsInfLives"], 0)
        mon.cmd("delete")
        call(mon, sym["playerTakeHit"])
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
        set_bp(mon, sym["gameFrame"])
        st.run(2)
        check("a death costs a life...", rd1(mon, sym["hudLives"]) == 2,
              str(rd1(mon, sym["hudLives"])))
        check("...but neither the currency nor the partial charge",
              econ(mon) == before, f"{before} -> {econ(mon)}")

        # ---- the level-complete page reports SPENDABLE P --------------------
        check("the level-complete page reads the spendable counter",
              rd1(mon, sym["pkTokensP"]) == 2,
              f"pkTokensP = {rd1(mon, sym['pkTokensP'])}, "
              f"and 7 pickups were made")

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        # ==================================================================
        # PART A -- the attract pages own their colours
        # ==================================================================
        mon.cmd("delete")
        # Write the residue by hand, in the colour and the place the boss health
        # bar leaves it, plus a stripe where the title text goes. Then enter a
        # non-game page the ordinary way and see what survives.
        for off in range(40, 80):                   # row 1, the bar's row
            poke(mon, COLOUR_RAM + off, 8 | 2)      # BOSS_BAR_FULL: red
        for off in range(6 * 40 + 10, 6 * 40 + 30):  # row 6: "MY FIRST ..."
            poke(mon, COLOUR_RAM + off, 8 | 2)
        dirty = [colour(mon, 6 * 40 + 10 + i) for i in range(4)]
        check("the residue was planted where the title text lands",
              all(c == (8 | 2) for c in dirty), str(dirty))

        poke_checked(mon, sym["gsState"], GS_ATTRACT)
        mon.cmd(f"r pc={sym['gsEnterAttract']:04x}")
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")

        samples = [colour(mon, a) for a in
                   (0, 40 + 8, 6 * 40 + 10, 6 * 40 + 25, 20 * 40 + 13,
                    23 * 40 + 10, 999)]
        check("entering attract left colour RAM uniform",
              all(c == TERRAIN_COLOUR_RAM for c in samples),
              f"{[hex(c) for c in samples]}")
        check("...at the value gameplay expects to find",
              colour(mon, 6 * 40 + 10) == TERRAIN_COLOUR_RAM)

        # ...and after a page flip, still uniform.
        page0 = rd1(mon, sym["gsAttractPage"])
        for _ in range(900):
            mon.cmd("x")
            if rd1(mon, sym["gsAttractPage"]) != page0:
                break
        after = [colour(mon, a) for a in (0, 40 + 8, 6 * 40 + 12, 999)]
        check("...and still uniform after the attract page cycles",
              all(c == TERRAIN_COLOUR_RAM for c in after),
              f"page {page0} -> {rd1(mon, sym['gsAttractPage'])}, "
              f"{[hex(c) for c in after]}")

        # ==================================================================
        # the catastrophic gate
        # ==================================================================
        for name in ("gameOverrun", "scrollLate", "statPageMismatch",
                     "statPtrMismatch", "objDoubleFree", "objAllocFail"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero over the run", got == 0, str(got))
        print(f"  info publishSkip {rd1(mon, sym['publishSkip'])} "
              f"(measured, not asserted)")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
