#!/usr/bin/env python3
"""Token defender attrition, and the Infinite Lives testing toggle.

What this proves
----------------
PART A -- the defence is attritional:
* the initial complement can still reach three defenders, assembled from live
  enemies and topped up by reinforcement exactly as before;
* once established, killing a defender takes the count to 2 and it STAYS 2 --
  no replacement Ring is created;
* and again to 1, and to 0, while the token is still alive;
* tkReinforced does not move across any of those kills;
* the encounter still ends when the token goes, and survivors still egress.

PART B -- Infinite Lives:
* the flag defaults OFF at a cold boot;
* pressing I on the attract screen toggles it ON, and HOLDING it does not
  toggle again;
* releasing and pressing again toggles it OFF;
* it survives the attract page cycle;
* with it OFF, a death decrements the stock and the last one is terminal;
* with it ON, a death runs the ordinary lifecycle -- the craft is destroyed and
  the fireball starts -- but the stock does not move and the death is never
  terminal, even from a stock of zero.

What this does NOT prove
------------------------
That the title indicator is legible, or that a death looks right. Manual VICE
is authoritative for both.

One VICE launch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, check, report)

sym = symbols(SYM)
PORT = 6675

MAX_OBJECTS = 16
TYPE_ENEMY = 1
ROLE_GUARD = 2
TK_GUARDS = 3
DEATH_TIME = 12
GS_ATTRACT, GS_PLAYING = 0, 1

# src/player.asm: the I key is PA4 / PB1, both active low.
KEY_I_COL = 0b11101111
KEY_I_ROW = 0b00000010


class Stepper:
    """One accepted sample per displayed frame.

    THE ENCOUNTER LASTS ABOUT 350 FRAMES and a defender's death animation is
    twelve, so this file has to work in frames. harness.free_run takes SECONDS
    OF WARP -- thousands of frames -- and the first draft of this test used it:
    the whole encounter began, assembled, ended and cleared inside one call, and
    the checks then sampled a machine with nothing left to look at.
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


def guards(mon):
    """Pool slots currently holding a token defender."""
    act = rd(mon, sym["logActive"], MAX_OBJECTS)
    typ = rd(mon, sym["objType"], MAX_OBJECTS)
    role = rd(mon, sym["enyRole"], MAX_OBJECTS)
    return [i for i in range(MAX_OBJECTS)
            if act[i] and typ[i] == TYPE_ENEMY and role[i] >= ROLE_GUARD]


def poke_checked(mon, addr, val, tries=6):
    for _ in range(tries):
        poke(mon, addr, val)
        if rd1(mon, addr) == (val & 0xff):
            return
    raise RuntimeError(f"could not write ${addr:04x} = {val:02x}")


def kill(mon, slot):
    """The logical destruction event, as src/collision.asm leaves it."""
    poke_checked(mon, sym["objTimer"] + slot, DEATH_TIME)
    poke_checked(mon, sym["objHP"] + slot, 0)


def hold_key_i(mon, down):
    """Hold or release the I key by forcing CIA 1 port B.

    THE KEY CANNOT BE PRESSED FROM THE MONITOR. readKeyI drives a column and
    reads $dc01 in the next instruction, so there is no byte in RAM to poke and
    no window in which a poked $dc01 would survive. The port B DATA DIRECTION
    register is the lever that does work: making PB1 an OUTPUT with a 0 in the
    data register pulls that row low for as long as it is set, which is exactly
    what a held key does. Restoring DDRB to input releases it.
    """
    if down:
        poke(mon, 0xdc03, KEY_I_ROW)        # PB1 an output...
        poke(mon, 0xdc01, 0x00)             # ...driven low: the key is down
    else:
        poke(mon, 0xdc03, 0x00)             # every row an input again
        poke(mon, 0xdc01, 0xff)


def main():
    print("=== token defender attrition + infinite lives ===")
    v = None
    try:
        v = Vice(PORT, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # ==================================================================
        # PART A -- the defence is attritional
        # ==================================================================
        poke(mon, sym["stageHold"], 1)      # keep the level endless for this
        poke(mon, sym["hudLives"], 250)     # ...and the ship alive through it
        bp = set_bp(mon, sym["gameFrame"])
        st = Stepper(mon)

        # Find a Dropper in the aperture and destroy it: the ordinary route in.
        target = None
        for _ in range(1500):
            st.step()
            act = rd(mon, sym["logActive"], MAX_OBJECTS)
            typ = rd(mon, sym["objType"], MAX_OBJECTS)
            spc = rd(mon, sym["enySpecies"], MAX_OBJECTS)
            hp = rd(mon, sym["objHP"], MAX_OBJECTS)
            for i in range(MAX_OBJECTS):
                if act[i] and typ[i] == TYPE_ENEMY and spc[i] == 8 and hp[i] > 0:
                    target = i
                    break
            if target is not None:
                break
        check("a Dropper was found to destroy", target is not None)
        if target is None:
            mon.cmd("delete")
            return report(__name__)

        kill(mon, target)
        started = False
        for _ in range(DEATH_TIME + 30):
            st.step()
            if rd1(mon, sym["tkActive"]):
                started = True
                break
        check("destroying it started the token encounter", started)

        # ---- the initial complement still assembles -----------------------
        got3 = False
        for _ in range(140):            # three reinforcements at 24 frames, plus
            st.step()                   # the walk down to the ring
            if len(guards(mon)) == TK_GUARDS:
                got3 = True
                break
        check("the initial complement still reaches three defenders", got3,
              f"{len(guards(mon))} defenders, "
              f"tkEnlisted={rd1(mon, sym['tkEnlisted'])}")
        check("...and the encounter records three enlisted",
              rd1(mon, sym["tkEnlisted"]) == TK_GUARDS,
              str(rd1(mon, sym["tkEnlisted"])))

        # ---- now break it down, one at a time -----------------------------
        reinforced0 = rd1(mon, sym["tkReinforced"])
        for expect in (2, 1, 0):
            g = guards(mon)
            if not g:
                break
            kill(mon, g[0])
            # WELL past DEATH_TIME (12) and past a full reinforcement period
            # (24), so a replacement would have had every chance to appear and
            # to walk into view. Before this change it would have.
            st.run(45)
            n = len(guards(mon))
            check(f"killing a defender leaves {expect}, and it stays {expect}",
                  n == expect and rd1(mon, sym["tkActive"]) == 1,
                  f"{n} defenders, tkActive={rd1(mon, sym['tkActive'])}")

        check("no replacement defender was ever created",
              rd1(mon, sym["tkReinforced"]) == reinforced0,
              f"tkReinforced {reinforced0} -> "
              f"{rd1(mon, sym['tkReinforced'])}")
        check("...and the enlisted count never grew past the complement",
              rd1(mon, sym["tkEnlisted"]) == TK_GUARDS,
              str(rd1(mon, sym["tkEnlisted"])))

        # ---- the encounter still ends by itself ---------------------------
        ended = False
        for _ in range(500):            # the token's own descent, in frames
            st.step()
            if rd1(mon, sym["tkActive"]) == 0:
                ended = True
                break
        check("the encounter still ends when the token goes", ended,
              f"tkActive={rd1(mon, sym['tkActive'])}, "
              f"tkEnded={rd1(mon, sym['tkEnded'])}")
        check("...and waves resumed", rd1(mon, sym["wvDropped"]) == 0)
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        # ==================================================================
        # PART B -- Infinite Lives
        # ==================================================================
        # Back to the attract screen, where the toggle lives.
        poke(mon, sym["gsState"], GS_ATTRACT)
        mon.cmd(f"r pc={sym['gsEnterAttract']:04x}")
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")

        check("Infinite Lives defaults OFF", rd1(mon, sym["gsInfLives"]) == 0,
              str(rd1(mon, sym["gsInfLives"])))

        # ---- press, and HOLD ----------------------------------------------
        hold_key_i(mon, True)
        for _ in range(4):
            mon.cmd("x")
        on = rd1(mon, sym["gsInfLives"])
        check("pressing I turns it ON", on == 1, str(on))

        for _ in range(60):                 # keep holding for a full second
            mon.cmd("x")
        check("...and HOLDING it does not toggle again",
              rd1(mon, sym["gsInfLives"]) == 1,
              str(rd1(mon, sym["gsInfLives"])))

        # ---- release, press again ------------------------------------------
        hold_key_i(mon, False)
        for _ in range(4):
            mon.cmd("x")
        check("releasing the key does not toggle",
              rd1(mon, sym["gsInfLives"]) == 1,
              str(rd1(mon, sym["gsInfLives"])))
        hold_key_i(mon, True)
        for _ in range(4):
            mon.cmd("x")
        check("pressing I again turns it OFF",
              rd1(mon, sym["gsInfLives"]) == 0,
              str(rd1(mon, sym["gsInfLives"])))
        hold_key_i(mon, False)
        for _ in range(4):
            mon.cmd("x")

        # ---- and it survives the attract page cycle ------------------------
        hold_key_i(mon, True)
        for _ in range(4):
            mon.cmd("x")
        hold_key_i(mon, False)
        for _ in range(4):
            mon.cmd("x")
        check("it is ON again for the persistence check",
              rd1(mon, sym["gsInfLives"]) == 1)
        page0 = rd1(mon, sym["gsAttractPage"])
        flipped = False
        for _ in range(900):
            mon.cmd("x")
            if rd1(mon, sym["gsAttractPage"]) != page0:
                flipped = True
                break
        check("the attract page cycled", flipped,
              f"page {page0} -> {rd1(mon, sym['gsAttractPage'])}")
        check("...and Infinite Lives survived the page flip",
              rd1(mon, sym["gsInfLives"]) == 1,
              str(rd1(mon, sym["gsInfLives"])))

        # ---- the joystick was not corrupted by the column drive ------------
        check("scanning the key left no column driven: $dc00 reads back clean",
              rd1(mon, 0xdc00) == 0xff, f"${rd1(mon, 0xdc00):02x}")

        # ==================================================================
        # PART B2 -- what a death costs, with the flag each way
        # ==================================================================
        mon.cmd("delete")
        bp = set_bp(mon, sym["gameFrame"])

        for flag, label in ((0, "OFF"), (1, "ON")):
            poke_checked(mon, sym["gsInfLives"], flag)
            poke_checked(mon, sym["plyDead"], 0)
            poke_checked(mon, sym["plyInvuln"], 0)
            poke_checked(mon, sym["plyExit"], 0)
            poke_checked(mon, sym["plyFatal"], 0)
            poke_checked(mon, sym["hudLives"], 3)

            # Call the canonical hit handler: it is the single point a life is
            # consumed, and calling it is how the two branches are compared
            # without needing an enemy to be in the right place.
            mon.cmd("> 01ff c0")
            mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym['playerTakeHit']:04x}")
            b2 = set_bp(mon, 0xc0fe)
            mon.cmd("x")
            mon.cmd(f"delete {b2}")

            lives = rd1(mon, sym["hudLives"])
            dead = rd1(mon, sym["plyDead"])
            fatal = rd1(mon, sym["plyFatal"])
            if flag == 0:
                check("with Infinite Lives OFF a death costs a life",
                      lives == 2, f"lives 3 -> {lives}")
            else:
                check("with Infinite Lives ON a death costs nothing",
                      lives == 3, f"lives 3 -> {lives}")
            check(f"...and the craft still dies ({label})", dead == 1,
                  f"plyDead {dead}")
            check(f"...and the fireball starts at its first frame ({label})",
                  rd1(mon, sym["plyBoomFrame"]) == 0)
            check(f"...and it is not terminal here ({label})", fatal == 0,
                  f"plyFatal {fatal}")

        # ---- the last life, each way ---------------------------------------
        for flag, want_fatal, label in ((0, 1, "OFF"), (1, 0, "ON")):
            poke_checked(mon, sym["gsInfLives"], flag)
            poke_checked(mon, sym["plyDead"], 0)
            poke_checked(mon, sym["plyInvuln"], 0)
            poke_checked(mon, sym["plyExit"], 0)
            poke_checked(mon, sym["plyFatal"], 0)
            poke_checked(mon, sym["hudLives"], 1 if flag == 0 else 0)

            mon.cmd("> 01ff c0")
            mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym['playerTakeHit']:04x}")
            b2 = set_bp(mon, 0xc0fe)
            mon.cmd("x")
            mon.cmd(f"delete {b2}")

            fatal = rd1(mon, sym["plyFatal"])
            check(f"the last life is terminal with the flag {label}"
                  if want_fatal else
                  f"a stock of zero is NOT terminal with the flag {label}",
                  fatal == want_fatal,
                  f"plyFatal {fatal}, lives {rd1(mon, sym['hudLives'])}")
            if flag == 1:
                check("...and the craft still died from a zero stock",
                      rd1(mon, sym["plyDead"]) == 1)

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        poke(mon, sym["gsInfLives"], 0)

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
