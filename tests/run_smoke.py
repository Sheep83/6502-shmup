#!/usr/bin/env python3
"""Routine regression smoke test — the small safety net for ordinary work.

WHAT THIS IS FOR, AND WHAT IT DELIBERATELY IS NOT.

The engine, multiplexer and scroller are mature. The 33-suite certification
battery in tests/ was built to establish their capacity and to diagnose them
while they were still moving; it takes the better part of an hour on a good day
and several hours on a bad one, and it does not need to re-prove the
multiplexer every time somebody redraws a spaceship.

So this answers four questions and stops:

    1. does it build and boot?
    2. does the campaign loop still turn?  ATTRACT -> PLAYING -> LEVELDONE
       (the shop) -> CONTINUE -> level 2 resident and PLAYING -> GAME OVER ->
       back to ATTRACT.
    3. what do the engine health counters say over a real gameplay window?
    4. has anything catastrophically broken?

Everything else -- feel, art, animation, encounter behaviour, collisions in
ordinary play, balance, presentation -- is established far better by five
minutes of actually playing the game, and that remains authoritative. See
docs/TESTING.md.

TRANSITIONS ARE DRIVEN, NOT WAITED FOR. Playing a level to its boss takes
minutes of emulated time and makes the check hostage to authored content. The
state machine's own entry points are called directly instead, which is what
makes this a structural check of the loop rather than a slow replay of it.

One VICE, owned by PID and reaped on every exit path, via the existing harness.
"""
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd1, read16, poke, call,  # noqa: E402
                     run_until, run_until_state, soak_frames,
                     LAUNCHED_PIDS)

PORT = 6790
GS_ATTRACT, GS_PLAYING, GS_GAMEOVER, GS_INITIALS, GS_LEVELDONE = 0, 1, 2, 3, 4
GS_UPG_CONT = 1                 # src/campaign.asm UPG_COUNT: the CONTINUE row

# The health window. Long enough to be a real stretch of play, short enough to
# keep this inside a routine-development timescale.
HEALTH_FRAMES = 3000

# ---------------------------------------------------------------------------
# COUNTERS THAT MUST BE ZERO, and the reason each one is fatal.
#
# These are the engine's own "something is structurally wrong" bytes. Every one
# of them means a frame was mishandled rather than merely costed.
FATAL = {
    "gameOverrun":      "the main thread missed a whole displayed frame",
    "scrollLate":       "a coarse scroll step arrived with the back page unfinished",
    "edgeLate":         "an aperture split landed on the wrong raster line",
    "statOverflow":     "the sprite schedule overflowed",
    "statPageMismatch": "a frame was drawn from the wrong screen page",
    "statPtrMismatch":  "a sprite pointer table disagreed with its page",
    "objDoubleFree":    "an object slot was freed twice",
    "objAllocFail":     "an object allocation failed",
    "clipPoolFull":     "the vertical clipping scratch pool was exhausted",
}

# ---------------------------------------------------------------------------
# COUNTERS THAT ARE REPORTED, NOT ASSERTED.
#
# publishSkip: a rare in-play publication miss is KNOWN, UNDERSTOOD AND
# PERMITTED. When a main-thread pass straddles raster 250 the engine drops one
# scroll update, recovers by itself and costs about one pixel. It was measured
# at roughly one event per 10,000-60,000 frames
# (reports/publish-skip-in-engine-capture.md). Failing on a non-zero value
# would make this runner a coin toss, and a coin toss is not a safety net.
#
# The threshold is deliberately coarse: at the measured rate a 3,000-frame
# window expects well under one event, so 1 is unremarkable and 5 would mean
# the rare thing has become a common thing. No false precision is claimed.
PUBLISH_SKIP_BUDGET = 5

# schedBuildDefer is a documented bounded cost ("cannot starve"), not a fault.
REPORTED = ["publishSkip", "schedBuildDefer", "statLate"]

results, notes = {}, []


def step(name, ok, detail=""):
    results[name] = bool(ok)
    print(f"{name}: {'PASS' if ok else 'FAIL'}" + (f"   {detail}" if detail else ""))
    return bool(ok)


def main():
    sym = symbols(SYM)
    v = None
    try:
        # ---- 1. BOOT ------------------------------------------------------
        # start_game=False: this runner drives the lifecycle itself, so the
        # attract state is observable instead of being behind the harness's
        # own boot.
        t0 = time.time()
        v = Vice(PORT, PRG, warp=True, start_game=False)
        mon = v.mon
        mon.cmd("r")
        at_attract = run_until_state(
            mon, sym["frameCounter"],
            lambda: rd1(mon, sym["gsState"]) == GS_ATTRACT, seconds=30)
        step("BOOT", at_attract,
             f"reached ATTRACT in {time.time() - t0:.0f}s, "
             f"frame {read16(mon, sym['frameCounter'])}")

        # ---- 2. CAMPAIGN LOOP --------------------------------------------
        ok = True

        # ATTRACT -> PLAYING, through the real input path.
        #
        # THE SAMPLE HAS TO BE FASTER THAN THE SHIP CAN DIE. hudLives cannot be
        # topped up until the game exists, and an unprotected parked ship in warp
        # loses all five inside a fraction of a second -- so PLAYING can begin
        # and end between two lazy samples. A 0.3s poll is ~600 frames and misses
        # it; this polls in ~0.03s slices and grants the stock the instant the
        # state is seen. (A six-press retry loop was tried first and was worse:
        # each extra press landed in GAME OVER and drove the lifecycle onward.)
        #
        # Reaching a POST-play state also counts as having entered the game --
        # that is the contract here, "the front screen can start a run" -- and it
        # is recorded distinctly so the output never claims more than it saw.
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], 0xef)                  # fire down...
        run_until_state(mon, sym["frameCounter"], lambda: False, seconds=0.2)
        poke(mon, sym["joyState"], 0xff)                  # ...and up: gate opens
        playing = run_until_state(
            mon, sym["frameCounter"],
            lambda: rd1(mon, sym["gsState"]) == GS_PLAYING,
            seconds=10, slice_s=0.03)
        if playing:
            poke(mon, sym["hudLives"], 250)               # at once, see above
            entered_note = "ok"
        else:
            # did it enter and run past PLAYING while we blinked?
            st = rd1(mon, sym["gsState"])
            playing = st in (GS_GAMEOVER, GS_INITIALS)
            entered_note = (f"ok (entered and ran on to gsState {st} before the "
                            f"first sample)" if playing else "FAILED")
            if playing:
                # put a runnable game back under the rest of the checks
                poke(mon, sym["hudLives"], 250)
                run_until_state(mon, sym["frameCounter"],
                                lambda: rd1(mon, sym["gsState"]) == GS_ATTRACT,
                                seconds=20)
                poke(mon, sym["joyState"], 0xef)
                run_until_state(mon, sym["frameCounter"], lambda: False, seconds=0.2)
                poke(mon, sym["joyState"], 0xff)
                run_until_state(
                    mon, sym["frameCounter"],
                    lambda: rd1(mon, sym["gsState"]) == GS_PLAYING,
                    seconds=10, slice_s=0.03)
                poke(mon, sym["hudLives"], 250)
        ok &= playing
        notes.append(f"  ATTRACT -> PLAYING      {entered_note}")
        poke(mon, sym["joyHold"], 0)

        level_before = rd1(mon, sym["cmpLevel"])
        pkg_before = rd1(mon, sym["lvlPackage"])
        nospawn_before = read16(mon, sym["waveNoSpawnLo"])

        # PLAYING -> LEVELDONE. Driven: reaching this by play means killing a
        # boss, which is minutes of emulated time and a content dependency.
        call(mon, sym, "gsEnterLevelDone")
        in_shop = rd1(mon, sym["gsState"]) == GS_LEVELDONE
        ok &= in_shop
        notes.append(f"  PLAYING -> LEVELDONE    {'ok' if in_shop else 'FAILED'}"
                     f"  (the upgrade shop)")

        # CONTINUE THROUGH THE REAL SHOP LOOP, NOT BY CALLING IT.
        #
        # gsUpgradeContinue does a genuine disk load and hands the display back
        # to the executor, so it is exactly what harness.call() documents itself
        # as being unfit for ("anything whose behaviour depends on frame cadence
        # belongs in a free-running production loop"). Calling it worked on one
        # run and left the machine with the frame counter frozen on the next --
        # a hang in a smoke test is worse than no smoke test.
        #
        # So the shop is driven the way a player drives it: put the cursor on
        # the CONTINUE row and give the loop a FIRE press EDGE. The loop reads
        # the edge itself and jmps to gsUpgradeContinue from inside the running
        # game, which is the only context that routine is built for.
        poke(mon, sym["gsUpgSel"], GS_UPG_CONT)
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], 0xff)            # nothing held...
        run_until_state(mon, sym["frameCounter"], lambda: False,
                        seconds=0.6)                # ...and gsUpgPrev records it
        poke(mon, sym["joyState"], 0xef)            # FIRE: a 1 -> 0 edge...
        run_until_state(mon, sym["frameCounter"], lambda: False, seconds=0.4)
        poke(mon, sym["joyState"], 0xff)            # ...AND LET GO.
        #
        # THE RELEASE IS NOT OPTIONAL. gsUpgradeContinue opens with
        # `jsr gsWaitFireRelease` -- deliberately, so one press cannot both buy
        # an upgrade and leave the shop. Holding FIRE down therefore parks the
        # campaign inside that wait for ever: the press is seen, the jump is
        # taken, and nothing else happens. That looked exactly like "CONTINUE
        # does not work" until the shop's own state was read back and showed
        # gsUpgPrev had recorded the press while gsState stayed on the shop.
        loaded_ok = run_until_state(
            mon, sym["frameCounter"],
            lambda: rd1(mon, sym["gsState"]) == GS_PLAYING, seconds=40)
        poke(mon, sym["joyHold"], 0)
        level_after = rd1(mon, sym["cmpLevel"])
        nospawn_after = read16(mon, sym["waveNoSpawnLo"])
        advanced = level_after == level_before + 1
        ok &= advanced
        notes.append(f"  CONTINUE advances       "
                     f"{'ok' if advanced else 'FAILED'}  "
                     f"cmpLevel {level_before} -> {level_after}")

        # The next level is genuinely resident: its package data differs. The
        # boss-approach row is authored per level (725 vs 352), so a change
        # proves a different package is in RAM rather than a flag being set.
        loaded = nospawn_after != nospawn_before
        ok &= loaded
        notes.append(f"  level 2 package loaded  {'ok' if loaded else 'FAILED'}  "
                     f"noSpawnRow {nospawn_before} -> {nospawn_after}")

        back_playing = loaded_ok
        ok &= back_playing
        notes.append(f"  level 2 -> PLAYING      "
                     f"{'ok' if back_playing else 'FAILED'}")

        # ---- 3. ENGINE HEALTH, on an UNINTERRUPTED window -----------------
        # Uninterrupted on purpose: stopping every frame resets the phase
        # relationship between the main thread and the raster IRQ and was
        # measured to hide exactly the timing faults this window is for.
        for n in list(FATAL) + REPORTED:
            poke(mon, sym[n], 0)
        frames = soak_frames(mon, sym["frameCounter"], HEALTH_FRAMES)
        health = {n: rd1(mon, sym[n]) for n in list(FATAL) + REPORTED}

        # ---- 4. the campaign closes the loop ------------------------------
        call(mon, sym, "gsEnterGameOver")
        over = rd1(mon, sym["gsState"]) in (GS_GAMEOVER, GS_INITIALS)
        ok &= over
        notes.append(f"  PLAYING -> GAME OVER    {'ok' if over else 'FAILED'}  "
                     f"gsState {rd1(mon, sym['gsState'])}")
        returned = run_until_state(
            mon, sym["frameCounter"],
            lambda: rd1(mon, sym["gsState"]) in (GS_ATTRACT, GS_INITIALS),
            seconds=25)
        ok &= returned
        notes.append(f"  returns to the front    "
                     f"{'ok' if returned else 'FAILED'}  "
                     f"gsState {rd1(mon, sym['gsState'])}")

        step("CAMPAIGN LOOP", ok)
        for n in notes:
            print(n)

        # ---- health verdict ----------------------------------------------
        print()
        print(f"Frames observed: {frames}")
        broke = []
        for n, why in FATAL.items():
            val = health[n]
            print(f"  {n:18} {val:3d}" + ("" if val == 0 else f"   <<< {why}"))
            if val:
                broke.append(f"{n}={val} ({why})")
        for n in REPORTED:
            val = health[n]
            extra = ""
            if n == "publishSkip":
                extra = (f"   (permitted: rare in-play miss, budget "
                         f"{PUBLISH_SKIP_BUDGET} per {HEALTH_FRAMES} frames)")
                if val > PUBLISH_SKIP_BUDGET:
                    broke.append(f"publishSkip={val} over {frames} frames, "
                                 f"budget {PUBLISH_SKIP_BUDGET}")
                    extra = f"   <<< ABOVE BUDGET {PUBLISH_SKIP_BUDGET}"
            elif n == "schedBuildDefer":
                extra = "   (a bounded cost, not a fault)"
            print(f"  {n:18} {val:3d}{extra}")
        step("ENGINE HEALTH", not broke,
             "" if not broke else "; ".join(broke))

    finally:
        if v:
            v.close()

    print()
    print(f"  VICE launched and reaped: {LAUNCHED_PIDS}")
    bad = [k for k, ok in results.items() if not ok]
    print()
    if bad:
        print(f"ROUTINE REGRESSION: FAIL  ({', '.join(bad)})")
        return 1
    print("ROUTINE REGRESSION: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
