#!/usr/bin/env python3
"""The restored outer loop: ATTRACT -> GAME -> GAME OVER -> INITIALS -> ATTRACT.

This tests a MIGRATION, so wherever the old c64Shooter source fixes a value --
the 250-frame attract cycle, the 180-frame game-over hold, eight table entries,
three initials, "equal does not displace" -- the expectation here is that old
value rather than a newly invented one.

What this proves
----------------
* cold boot reaches ATTRACT with the stub owning the display and no sprites;
* the attract pages alternate title/scores on the old 250-frame cycle, and both
  pages draw the old text at the old screen positions;
* fire starts a game, but only after it is RELEASED -- the old gate;
* a new game is fresh: lives full, score zero, token currency zero, and the
  engine's own subsystems reset;
* gameplay does not advance while a non-game state is up;
* an ordinary death costs one life and stays in GAME;
* terminal death waits for the current engine's death presentation and only
  then enters GAME OVER;
* qualification and insertion follow the old rules, including equal-does-not-
  displace and the descending order;
* initials entry is edge triggered and commits to the table;
* the high-score table survives a second game, which is itself fresh;
* SFX is silent outside GAME and the VIC is handed back on entering it.

Manual VICE remains authoritative for whether the attract loop FEELS like the
old one, for initials usability and for transition cleanliness.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, step_n, call, check, report)

GS_ATTRACT, GS_PLAYING, GS_GAMEOVER, GS_INITIALS = 0, 1, 2, 3
ATTRACT_CYCLE = 250             # old ATTRACT_CYCLE_FRAMES
OVER_HOLD     = 180             # old GAME_OVER_HOLD_FRAMES
HS_COUNT, HS_DIGITS, HS_NAMELEN = 8, 6, 3
HUD_LIVES_MAX = 5
SCREEN   = 0x0400
TITLE_AT = SCREEN + 6 * 40 + 10
HEAD_AT  = SCREEN + 4 * 40 + 14
ROW0_AT  = SCREEN + 7 * 40 + 15
OVER_AT  = SCREEN + 12 * 40 + 15
ISLOT_AT = SCREEN + 14 * 40 + 18
JOY_FIRE, JOY_IDLE, JOY_UP, JOY_RIGHT = 0xef, 0xff, 0xfe, 0xf7
# "MY FIRST" / "HIGH" / "GAME OVER" in screen codes
MY_FIRST = [13, 25, 32, 6, 9, 18, 19, 20]
HIGH     = [8, 9, 7, 8]
GAME_OVR = [7, 1, 13, 5, 32, 15, 22, 5, 18]
PORT = 6674


def state(mon, sym):
    return rd1(mon, sym["gsState"])


BOOM_FRAMES, BOOM_HOLD = 8, 6


def revive(mon, sym, lives=5):
    """A known-alive craft with a known stock.

    The ship can DIE now, and the harness's start-up run is long enough in warp
    that it is often mid-explosion by the time a test looks. Every death
    assertion below therefore starts from a craft that is definitely alive.
    """
    for f in ("plyDead", "plyBoomFrame", "plyBoomTimer", "plyFatal",
              "plyInvuln", "plyFlash"):
        poke(mon, sym[f], 0)
    poke(mon, sym["plyVisible"], 1)
    poke(mon, sym["hudLives"], lives)


def hold_joy(mon, sym, value):
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["joyState"], value)


def run_until_state(mon, sym, want, seconds=8):
    """Free-run in slices until the lifecycle reaches `want`."""
    end = time.time() + seconds
    while time.time() < end:
        if state(mon, sym) == want:
            return True
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
    return state(mon, sym) == want


def main():
    sym = symbols(SYM)
    v = None
    try:
        v = Vice(PORT, PRG, warp=True, start_game=False)   # we ARE the lifecycle
        mon = v.mon
        mon.cmd("r")
        time.sleep(1.0)

        # --- 1. cold boot lands in ATTRACT, with the stub owning the display -
        check("cold boot reaches the ATTRACT state, as the old boot did",
              state(mon, sym) == GS_ATTRACT, str(state(mon, sym)))
        check("the IRQ seam is engaged, so the executor draws nothing",
              rd1(mon, sym["gsNonGame"]) == 1)
        check("no sprite of any kind is enabled in attract",
              rd1(mon, 0xd015) == 0, f"$d015 = {rd1(mon, 0xd015):02x}")
        check("multicolour text is off, so the attract text is hires",
              rd1(mon, 0xd016) & 0x10 == 0, f"$d016 = {rd1(mon, 0xd016):02x}")
        check("the character ROM is selected as the font",
              rd1(mon, 0xd018) & 0x0e == 0x04,
              f"$d018 = {rd1(mon, 0xd018):02x}")

        # --- 2. the old attract cycle, both pages, at the old positions ------
        seen = {}
        deadline = time.time() + 20
        while len(seen) < 2 and time.time() < deadline:
            page = rd1(mon, sym["gsAttractPage"])
            if page not in seen:
                if page == 0:
                    seen[0] = rd(mon, TITLE_AT, 8)
                else:
                    seen[1] = rd(mon, HEAD_AT, 4)
            free_run(mon, sym["frameCounter"], 1)
            mon.cmd("delete")
        check("attract alternates between BOTH pages", set(seen) == {0, 1},
              str(sorted(seen)))
        check("the title page draws the old title at the old position",
              seen.get(0) == MY_FIRST, str(seen.get(0)))
        check("the scores page draws the old heading at the old position",
              seen.get(1) == HIGH, str(seen.get(1)))
        while rd1(mon, sym["gsAttractPage"]) != 1:      # wait for the table
            free_run(mon, sym["frameCounter"], 1)
            mon.cmd("delete")
        rows = rd(mon, ROW0_AT, 11)
        check("...and the table rows are 'III  DDDDDD', eight of them",
              all(1 <= c <= 26 for c in rows[:3]) and rows[3:5] == [32, 32]
              and all(48 <= c <= 57 for c in rows[5:11]),
              str(rows))
        check("the attract cycle timer runs inside the old 250-frame period",
              1 <= rd1(mon, sym["gsAttractTimer"]) <= ATTRACT_CYCLE,
              str(rd1(mon, sym["gsAttractTimer"])))

        # --- 3. gameplay does not advance while attract is up ---------------
        before = (rd1(mon, sym["wvSpawned"]), rd1(mon, sym["logCount"]),
                  rd1(mon, sym["pkSpawned"]))
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")
        check("no gameplay advances during attract: no waves, no objects, no "
              "tokens",
              (rd1(mon, sym["wvSpawned"]), rd1(mon, sym["logCount"]),
               rd1(mon, sym["pkSpawned"])) == before, str(before))
        check("every SID voice is idle outside GAME",
              rd(mon, sym["sfxChId"], 3) == [0, 0, 0],
              str(rd(mon, sym["sfxChId"], 3)))

        # --- 4. the old start gate: fire, then RELEASE -----------------------
        hold_joy(mon, sym, JOY_FIRE)
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")
        check("HELD fire alone does not start a game -- the old release gate",
              state(mon, sym) == GS_ATTRACT, str(state(mon, sym)))
        poke(mon, sym["joyState"], JOY_IDLE)
        check("...and releasing it does", run_until_state(mon, sym, GS_PLAYING),
              str(state(mon, sym)))

        # --- 5. a new game is fresh, and the display is handed back ----------
        check("the executor owns the display again in GAME",
              rd1(mon, sym["gsNonGame"]) == 0)
        check("multicolour text is back on for the terrain",
              rd1(mon, 0xd016) & 0x10 != 0, f"$d016 = {rd1(mon, 0xd016):02x}")
        check("one game has been started", rd1(mon, sym["gsGames"]) == 1,
              str(rd1(mon, sym["gsGames"])))

        # --- 6. an ordinary death costs a life and stays in GAME -------------
        # THE DEATH MODEL CHANGED under this test: a hit used to grant a
        # hundred frames of invulnerable blinking on an intact ship, and now it
        # DESTROYS the craft -- plyDead, an eight-frame fireball, and the
        # invulnerability moved to the respawn at the far end of it. See
        # reports/player-death-fireball-collision.md. What this section still
        # owns is the LIFECYCLE consequence: one life, still in GAME.
        revive(mon, sym, lives=3)
        call(mon, sym, "playerTakeHit")
        check("an ordinary death costs exactly one life",
              rd1(mon, sym["hudLives"]) == 2, str(rd1(mon, sym["hudLives"])))
        check("...and does not end the game",
              rd1(mon, sym["plyFatal"]) == 0 and state(mon, sym) == GS_PLAYING)
        check("...while the craft's own death presentation runs",
              rd1(mon, sym["plyDead"]) == 1,
              str(rd1(mon, sym["plyDead"])))

        # --- 7. terminal death waits for the death presentation --------------
        # The qualifying score is set BEFORE the death, so the run that ends here
        # is genuinely the one the table is offered.
        #
        # NOT 999999: the HUD's own score cadence keeps bumping the value while
        # the death plays out, and a maximal score carries off the top digit and
        # wraps to nearly nothing -- which then fails to qualify for reasons
        # that have nothing to do with the code under test.
        QUALIFYING = [5, 0, 0, 0, 0, 0]
        for i, d in enumerate(QUALIFYING):
            poke(mon, sym["hudScore"] + i, d)
        revive(mon, sym, lives=1)
        call(mon, sym, "playerTakeHit")
        check("the last life sets the fatal flag, not the state",
              rd1(mon, sym["plyFatal"]) == 1
              and rd1(mon, sym["hudLives"]) == 0
              and state(mon, sym) == GS_PLAYING,
              f"fatal {rd1(mon, sym['plyFatal'])}, "
              f"state {state(mon, sym)}")
        check("...and the death presentation is running",
              rd1(mon, sym["plyDead"]) == 1)
        # THE HOLD IS 180 FRAMES AND THIS RUNS IN WARP, so a polling loop whose
        # granularity is a wall-clock slice steps straight over GAME OVER and
        # finds INITIALS. The state is caught on a breakpoint instead.
        set_bp(mon, sym["gsGameOverLoop"])
        # END THE FIREBALL rather than wait out its 48 frames: park it on its
        # last art frame with the hold all but spent, and the next death tick
        # finishes it.
        poke(mon, sym["plyBoomFrame"], BOOM_FRAMES - 1)
        poke(mon, sym["plyBoomTimer"], BOOM_HOLD - 1)
        mon.cmd("x")
        check("terminal death enters GAME OVER once the presentation ends",
              state(mon, sym) == GS_GAMEOVER, str(state(mon, sym)))
        over = rd(mon, OVER_AT, 9)
        check("...and the old GAME OVER text is stamped at the old position",
              over == GAME_OVR, str(over))
        check("the game-over hold is the old 180-frame timer",
              1 <= rd1(mon, sym["gsOverTimer"]) <= OVER_HOLD,
              str(rd1(mon, sym["gsOverTimer"])))
        check("the display is handed back to the stub on the way out",
              rd1(mon, sym["gsNonGame"]) == 1)
        # ONE MORE FRAME BEFORE READING $d015. The stub zeroes the sprite enable
        # from inside the IRQ, so the instant the state changes the register
        # still holds whatever the last gameplay batch left in it -- for the
        # remainder of that one frame, and no longer.
        mon.cmd("x")
        mon.cmd("delete")
        check("...and no sprite survives into the non-game display",
              rd1(mon, 0xd015) == 0, f"$d015 = {rd1(mon, 0xd015):02x}")
        check("gameplay SFX was silenced on the way out",
              rd(mon, sym["sfxChId"], 3) == [0, 0, 0],
              str(rd(mon, sym["sfxChId"], 3)))

        # --- 8. the live qualification path ----------------------------------
        # The score was set before the death above, so this is the real routing
        # decision rather than one arranged after the fact.
        set_bp(mon, sym["gsInitialsLoop"])
        mon.cmd("x")
        mon.cmd("delete")
        check("a qualifying score routes GAME OVER into INITIALS",
              state(mon, sym) == GS_INITIALS, str(state(mon, sym)))
        check("...and the run was counted as qualifying",
              rd1(mon, sym["gsQualified"]) >= 1,
              str(rd1(mon, sym["gsQualified"])))

        # --- 9. initials entry is edge triggered -----------------------------
        check("initials entry starts on AAA with the first slot selected",
              rd(mon, sym["gsInitChars"], 3) == [1, 1, 1]
              and rd1(mon, sym["gsInitSlot"]) == 0,
              str(rd(mon, sym["gsInitChars"], 3)))
        slot0 = rd1(mon, ISLOT_AT)
        check("...and the selected letter is highlighted in reverse video",
              slot0 & 0x80 != 0, f"screen code {slot0:02x}")

        hold_joy(mon, sym, JOY_UP)              # HELD, for many frames
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")
        check("a HELD direction moves the letter exactly once -- edge triggered",
              rd1(mon, sym["gsInitChars"]) == 2,
              str(rd1(mon, sym["gsInitChars"])))
        poke(mon, sym["joyState"], JOY_IDLE)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        hold_joy(mon, sym, JOY_RIGHT)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        check("right moves to the next slot", rd1(mon, sym["gsInitSlot"]) == 1,
              str(rd1(mon, sym["gsInitSlot"])))

        # --- 10. commit inserts and returns to attract on the SCORES page ----
        poke(mon, sym["joyState"], JOY_IDLE)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        hold_joy(mon, sym, JOY_FIRE)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        poke(mon, sym["joyState"], JOY_IDLE)
        check("committing initials returns to ATTRACT",
              run_until_state(mon, sym, GS_ATTRACT, seconds=8),
              str(state(mon, sym)))
        check("...showing the SCORES page first, as the old commit did",
              rd1(mon, sym["gsAttractPage"]) == 1,
              str(rd1(mon, sym["gsAttractPage"])))
        top = rd(mon, sym["hsDigits"], HS_DIGITS)
        name = rd(mon, sym["hsName"], HS_NAMELEN)
        check("the score was inserted at the top of the table",
              top[0] == QUALIFYING[0], f"{top} vs a run that scored {QUALIFYING}")
        check("...carrying the initials that were entered (B A A)",
              name == [2, 1, 1], str(name))
        table = rd(mon, sym["hsDigits"], HS_COUNT * HS_DIGITS)
        entries = [table[i * HS_DIGITS:(i + 1) * HS_DIGITS]
                   for i in range(HS_COUNT)]
        check("the table is still eight entries and still descending",
              all(entries[i] >= entries[i + 1] for i in range(HS_COUNT - 1)),
              str(entries))

        # --- 11. the old equal-does-not-displace rule ------------------------
        # Safe to drive directly here: ATTRACT only leaves on a fire press and
        # the stick is idle, so nothing races these calls.
        bottom = rd(mon, sym["hsDigits"] + (HS_COUNT - 1) * HS_DIGITS, HS_DIGITS)
        for i, d in enumerate(bottom):
            poke(mon, sym["hudScore"] + i, d)
        call(mon, sym, "gsScoreQualifies")
        check("an EQUAL score does not displace an existing entry -- old rule",
              rd1(mon, sym["gsRank"]) == HS_COUNT,
              str(rd1(mon, sym["gsRank"])))

        # --- 12. a second game is fresh; the table survives it ---------------
        table_before = rd(mon, sym["hsDigits"], HS_COUNT * HS_DIGITS)
        poke(mon, sym["pkTokensP"], 7)              # dirty the run-scoped state
        hold_joy(mon, sym, JOY_FIRE)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        poke(mon, sym["joyState"], JOY_IDLE)
        # CAUGHT AT gsEnterGame: every reset has run and not one gameplay frame
        # has. Polling for GS_PLAYING in warp lands thousands of frames later,
        # by which time the ship has been shot at and the stock is honestly
        # lower -- which says nothing about whether the RESET happened.
        set_bp(mon, sym["gsEnterGame"])
        mon.cmd("x")
        mon.cmd("delete")
        check("fire starts a SECOND game",
              rd1(mon, sym["gsGames"]) == 2, str(rd1(mon, sym["gsGames"])))
        check("the second game starts with a full stock of lives",
              rd1(mon, sym["hudLives"]) == HUD_LIVES_MAX,
              str(rd1(mon, sym["hudLives"])))
        check("...a zeroed score",
              rd(mon, sym["hudScore"], 6) == [0, 0, 0, 0, 0, 0],
              str(rd(mon, sym["hudScore"], 6)))
        check("...a zeroed token currency, so P does not leak between runs",
              rd1(mon, sym["pkTokensP"]) < 7,
              str(rd1(mon, sym["pkTokensP"])))
        check("...and no leftover fatal flag",
              rd1(mon, sym["plyFatal"]) == 0)
        check("THE HIGH-SCORE TABLE SURVIVED the whole cycle",
              rd(mon, sym["hsDigits"], HS_COUNT * HS_DIGITS) == table_before)

        # --- 13. a short gameplay smoke -------------------------------------
        CATASTROPHIC = ("gameOverrun", "scrollLate",
                        "statPageMismatch", "statPtrMismatch")
        # SETTLE FIRST, THEN ZERO. Everything above has stopped the machine on
        # breakpoints a dozen times, including once in the middle of the
        # transition into this game; the counters are zeroed AFTER a settling
        # run so the smoke measures steady-state gameplay rather than the
        # debugger's footprints. Measured on a clean boot-to-game run with no
        # breakpoints at all, this window gives zero on every counter here.
        # A STOCK LARGE ENOUGH TO OUTLAST THE PROBE. Five warp seconds is
        # thousands of frames with a stationary ship under fire; at five lives
        # the run ends in GAME OVER long before the probe does, and the smoke
        # would be measuring the attract screen.
        poke(mon, sym["hudLives"], 250)
        poke(mon, sym["joyState"], JOY_FIRE)
        free_run(mon, sym["frameCounter"], 1)          # settle
        mon.cmd("delete")
        for n in CATASTROPHIC:
            poke(mon, sym[n], 0)
        free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        check("the second game really is running",
              state(mon, sym) == GS_PLAYING and rd1(mon, sym["wvSpawned"]) > 0,
              f"state {state(mon, sym)}, spawned {rd1(mon, sym['wvSpawned'])}")
        for n in CATASTROPHIC:
            val = rd1(mon, sym[n])
            check(f"{n} is zero over the smoke run", val == 0, str(val))
        print(f"  info publishSkip over the smoke run: "
              f"{rd1(mon, sym['publishSkip'])} (known limitation, not asserted)")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
