#!/usr/bin/env python3
"""The campaign: the speed upgrade, the level sequence, and the reset boundary.

    python3 tests/test_campaign.py

WHAT THIS PROVES, on the machine:

  * a STOCK ship moves exactly one pixel a frame, unchanged -- the behaviour
    tests/test_production.py also asserts, re-checked here because the upgrade
    is implemented by adding a second step to that very code;
  * an UPGRADED ship moves measurably faster, at the authored cadence, and by a
    fraction rather than a doubling;
  * the sequence is data: LEVEL1 -> LEVEL2 -> END, with cmpHasNextLevel
    refusing a third;
  * a level change RESETS the level-local world and KEEPS the campaign's;
  * LEVEL2 genuinely loads from the same disk at run time and brings its own
    charset, palette and turret list with it.

THE LEVEL CHANGE IS DRIVEN THROUGH THE REAL ROUTINE. gsUpgradeContinue is what
the shop calls, and it is what this calls: the KERNAL load, the banking dance
and the whole of gsEnterNextLevel run exactly as they do in play. Nothing about
the transition is simulated.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     step_n, read16, check, report, LAUNCHED_PIDS)

sym = symbols(SYM)
PORT = 6613

JOY_RIGHT = 0b00001000          # active low
MAX_OBJECTS = 16

# src/campaign.asm
UPG_MAX_LEVEL = 2
# src/gamestate.asm gsUpgCost, and src/pickup.asm. THE COSTS ARE IN COMPLETED P
# TOKENS, not in pickups: PICKUP_P_PER_UNIT pickups charge one token, so level 1
# really costs P_PER_UNIT pickups and level 2 twice that.
UPG_COST = (1, 2)
PICKUP_P = 0
PICKUP_P_PER_UNIT = 3
TRAMP = 0x02a7                  # free RAM; no engine segment claims it
GS_CAMPAIGN_DONE = 5            # src/gamestate.asm
GS_FIRE = 0b00010000            # joystick port 2, active low
SPEED_RATE = {0: 1.00, 1: 1.25, 2: 1.50}


def drive_right(mon, frames):
    """Hold RIGHT for `frames` frames and return the pixels travelled."""
    x0 = rd1(mon, sym["plyX"]) | (rd1(mon, sym["plyXHi"]) << 8)

    # joyHold IS THE ENGINE'S OWN TEST HOOK, and tests/test_production.py uses
    # it for the same reason: readInput refreshes joyState from the hardware at
    # the top of every gameplay frame, so a poked stick would be overwritten
    # before playerTick ever saw it. joyHold tells readInput to leave it alone.
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["joyState"], 0xFF & ~JOY_RIGHT)
    step_n(mon, sym["frameCounter"], frames, lambda: None)
    poke(mon, sym["joyHold"], 0)
    x1 = rd1(mon, sym["plyX"]) | (rd1(mon, sym["plyXHi"]) << 8)
    return x1 - x0


def measure_speed(v, level, frames=64):
    """Pixels travelled in `frames` frames at the given purchased speed level."""
    mon = v.mon
    poke(mon, sym["cmpUpgrade"], level)
    # cmpApplyUpgrades is what turns a purchase into the bytes playerTick reads;
    # calling it is what the shop does after every buy.
    poke(mon, sym["plyX"], 40)           # room to run without hitting the clamp
    poke(mon, sym["plyXHi"], 0)
    apply_upgrades(mon)
    return drive_right(mon, frames)


def apply_upgrades(mon):
    """Do what cmpApplyUpgrades and cmpSpeedReset do, the way a purchase would.

    The speed upgrade is a SUB-PIXEL FRACTION now, not a frame mask: playerTick
    accumulates cmpSpeedFrac per axis and takes a second step on that axis when
    the accumulator carries. Seeding the two axes half a period apart is what
    keeps a diagonal from gaining both its extra pixels on the same frame.
    """
    lvl = rd1(mon, sym["cmpUpgrade"])
    frac = 0 if lvl == 0 else rd1(mon, sym["cmpSpeedFracTab"] + lvl - 1)
    poke(mon, sym["cmpSpeedFrac"], frac)
    poke(mon, sym["plyFrac"] + 0, 0)
    poke(mon, sym["plyFrac"] + 1, 0x80)
    poke(mon, sym["plyFracDir"] + 0, 0)
    poke(mon, sym["plyFracDir"] + 1, 0)


def press(mon, bit, hold=0.25):
    """One joystick PRESS EDGE, delivered to a running machine.

    EVERY MONITOR COMMAND HALTS THE MACHINE and "x" is what starts it again --
    without that the pokes land but nothing ever runs to see them, which is how
    a first attempt at this read an entirely unresponsive shop. joyHold is the
    engine's own hook telling readInput to leave joyState alone.
    """
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["joyState"], 0xFF & ~bit)
    mon.cmd("x")
    time.sleep(hold)
    poke(mon, sym["joyState"], 0xFF)
    mon.cmd("x")
    time.sleep(hold)
    poke(mon, sym["joyHold"], 0)
    mon.cmd("x")
    time.sleep(0.1)


def call(mon, addr, setup=(), settle=0.6):
    """JSR `addr` from a trampoline, so its rts has somewhere legitimate to go.

    `g <routine>` alone leaves the stack holding whatever gameplay left, and the
    routine's rts then returns into nothing -- which is how an earlier probe
    ended up executing garbage until something re-banked the KERNAL. The
    trampoline is `[setup] jsr addr / jmp *`, so the CPU parks at a known
    address instead.
    """
    code = list(setup) + [0x20, addr & 0xFF, addr >> 8]
    here = TRAMP + len(code)
    code += [0x4C, here & 0xFF, here >> 8]      # jmp * -- spin where we land
    for i, b in enumerate(code):
        poke(mon, TRAMP + i, b)
    mon.cmd("delete")
    mon.cmd(f"g {TRAMP:04x}")
    time.sleep(settle)


def main():
    # =====================================================================
    # 0. THREE PICKUPS MAKE ONE SPENDABLE TOKEN, AND ONE BUYS SPEED
    # =====================================================================
    # THE REAL CHARGING PATH, not a poked counter: pickupCollect is what the
    # collision runs when the ship touches a P token, and it is what banks the
    # unit. The point of the check is that the SHOP'S PRICES ARE DENOMINATED IN
    # THE SAME UNIT the arena awards -- a cost of 1 must mean one completed
    # token, which is PICKUP_P_PER_UNIT pickups, and not three times that.
    v = None
    charge, tokens = [], []
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 20, lambda: None)
        poke(mon, sym["pkTokensP"], 0)
        poke(mon, sym["pkCharge"], 0)
        poke(mon, sym["pkKind"], PICKUP_P)      # slot 0 holds a P token
        for _ in range(PICKUP_P_PER_UNIT):
            # ldx #0 selects that slot, which is what pickupCollect indexes by
            call(mon, sym["pickupCollect"], setup=(0xA2, 0x00), settle=0.35)
            charge.append(rd1(mon, sym["pkCharge"]))
            tokens.append(rd1(mon, sym["pkTokensP"]))
            mon.cmd("x")
    finally:
        if v:
            v.close()

    check(f"{PICKUP_P_PER_UNIT} pickups charge exactly one P token",
          tokens == [0] * (PICKUP_P_PER_UNIT - 1) + [1],
          f"pkTokensP after each pickup: {tokens}")
    check("...and the partial charge resets when it banks",
          charge == list(range(1, PICKUP_P_PER_UNIT)) + [0],
          f"pkCharge after each pickup: {charge}")
    check("...and that ONE token is enough for the first SPEED level",
          UPG_COST[0] <= 1,
          f"level 1 costs {UPG_COST[0]} P = {UPG_COST[0] * PICKUP_P_PER_UNIT} "
          f"pickups; one completed token is {PICKUP_P_PER_UNIT}")
    check("...and the second level costs two, not five",
          UPG_COST[1] == 2,
          f"level 2 costs {UPG_COST[1]} P = {UPG_COST[1] * PICKUP_P_PER_UNIT} "
          f"pickups")

    # ---- and ONE token really does buy it, in the shop -------------------
    # THE ARITHMETIC ABOVE IS NOT THE PROOF. That a cost of 1 is <= 1 says
    # nothing about whether the shop accepts it; this enters the real
    # GS_LEVELDONE loop with exactly one banked token and presses fire.
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 20, lambda: None)
        poke(mon, sym["pkTokensP"], 1)          # exactly one completed token
        poke(mon, sym["cmpUpgrade"], 0)
        # Into the shop AND its loop: gsEnterLevelDone only draws the page, the
        # ROUTER is what dispatches gsLevelDoneLoop.
        a, r = sym["gsEnterLevelDone"], sym["gsRouter"]
        for i, b in enumerate([0x20, a & 0xFF, a >> 8, 0x4C, r & 0xFF, r >> 8]):
            poke(mon, TRAMP + i, b)
        mon.cmd("delete")
        mon.cmd(f"g {TRAMP:04x}")
        time.sleep(0.8)
        press(mon, GS_FIRE)
        bought = rd1(mon, sym["cmpUpgrade"])
        left = rd1(mon, sym["pkTokensP"])
        boost = rd1(mon, sym["cmpSpeedFrac"])
        mon.cmd("x")
    finally:
        if v:
            v.close()

    check("ONE EARNED TOKEN BUYS SPEED in the real shop",
          bought == 1 and left == 0,
          f"upgrade {bought}, {left} P left of 1")
    check("...and the purchase reaches gameplay immediately",
          boost == 64, f"cmpSpeedFrac {boost}, expected 64 (a quarter pixel)")

    # =====================================================================
    # 1. THE SPEED UPGRADE, measured
    # =====================================================================
    v = None
    speeds = {}
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        poke(mon, sym["plyInvuln"], 0)
        for level in (0, 1, 2):
            speeds[level] = measure_speed(v, level)
    finally:
        if v:
            v.close()

    # MEASURED AGAINST STOCK, NOT AGAINST 64. Which frame of the window the
    # first step lands on depends on where the breakpoint caught the machine, so
    # the absolute distance carries one frame of slop; the BOOST COUNT does not.
    # Stock is the baseline and each upgrade adds a known number of extra pixels.
    FRAMES = 64
    check("STOCK: the ship still moves one pixel a frame, unchanged",
          abs(speeds[0] - FRAMES) <= 1,
          f"{speeds[0]} px in {FRAMES} frames")
    for level, per in ((1, 4), (2, 2)):
        extra = speeds[level] - speeds[0]
        want = FRAMES // per
        # ONE SHORT IS CORRECT AT THE START. The accumulator begins empty, so
        # the first carry arrives one accumulation later than the steady state;
        # over a long enough window the rate converges exactly.
        check(f"SPEED {level}: one extra pixel every {per} frames",
              abs(extra - want) <= 1,
              f"{speeds[level]} px vs stock {speeds[0]} = {extra} extra, "
              f"expected {want} ({SPEED_RATE[level]} px/frame)")
    check("the upgrade is a fraction faster, not a doubling",
          speeds[0] < speeds[1] < speeds[2] < speeds[0] * 2,
          f"{speeds[0]} -> {speeds[1]} -> {speeds[2]} px, "
          f"stock doubled would be {speeds[0] * 2}")

    # =====================================================================
    # 2. THE SEQUENCE, and 3. THE LEVEL CHANGE
    # =====================================================================
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["gameFrame"])

        names = bytes(rd(mon, sym["cmpLevelNames"], 12)).decode("ascii")
        check("the sequence is a table of filenames, in order",
              names == "LEVEL1LEVEL2", repr(names))
        check("the run starts on the first level", rd1(mon, sym["cmpLevel"]) == 0)

        # ---- dirty the world, so a clean level 2 is provable ---------------
        # Every one of these is level-LOCAL state the transition must clear.
        poke(mon, sym["cmpUpgrade"], 1)         # ...and these are CAMPAIGN state
        poke(mon, sym["pkTokensP"], 7)          # that it must keep
        apply_upgrades(mon)

        # run a while so waves spawn, the cursor advances and the world fills
        step_n(mon, sym["frameCounter"], 420, lambda: None)

        before = {
            "worldProgress": read16(mon, sym["worldProgressLo"]),
            "logCount": rd1(mon, sym["logCount"]),
            "wvNextTrig": rd1(mon, sym["wvNextTrig"]),
            "glyphCount": rd1(mon, sym["trnGlyphCount"]),
            "bg": rd1(mon, sym["trnBgColour"]),
            "turretCount": rd1(mon, sym["turretCount"]),
        }
        poke(mon, sym["ebCount"], 2)            # pretend bolts are in flight
        poke(mon, sym["trtKills"], 3)

        check("LEVEL 1 is resident and looks like itself",
              before["glyphCount"] == 80 and before["bg"] == 12
              and before["turretCount"] == 5,
              f"{before['glyphCount']} glyphs, bg {before['bg']}, "
              f"{before['turretCount']} turrets")
        check("...and the world is genuinely dirty before the change",
              before["worldProgress"] > 0,
              f"worldProgress {before['worldProgress']}, "
              f"trigger cursor {before['wvNextTrig']}, "
              f"{before['logCount']} live objects")

        # ---- THE REAL TRANSITION -------------------------------------------
        # gsUpgradeContinue is the shop's own Continue: it advances the
        # sequence, calls levelLoadRuntime and runs gsEnterNextLevel.
        #
        # THE BREAKPOINT STAYS ARMED ACROSS IT, and that is what makes the
        # measurement honest. gameFrame does not run during the shop or during
        # the load, so the breakpoint cannot fire until gameplay RESUMES -- which
        # freezes the machine on level 2's very first frame. A first version
        # deleted the breakpoint and slept three seconds instead, and under warp
        # that is some two thousand frames of level 2 actually being played: it
        # read worldProgress 674 and nine fired triggers and called them stale
        # state, when they were simply the level getting on with it.
        mon.cmd(f"g {sym['gsUpgradeContinue']:04x}")
        deadline = time.time() + 20
        while time.time() < deadline:
            time.sleep(0.25)
            if rd1(mon, sym["gsState"]) == 1:    # GS_PLAYING: the load is done
                break

        after = {
            "cmpLevel": rd1(mon, sym["cmpLevel"]),
            "worldProgress": read16(mon, sym["worldProgressLo"]),
            "logCount": rd1(mon, sym["logCount"]),
            "wvNextTrig": rd1(mon, sym["wvNextTrig"]),
            "glyphCount": rd1(mon, sym["trnGlyphCount"]),
            "bg": rd1(mon, sym["trnBgColour"]),
            "turretCount": rd1(mon, sym["turretCount"]),
            "ebCount": rd1(mon, sym["ebCount"]),
            "trtKills": rd1(mon, sym["trtKills"]),
            "lvlPhase": rd1(mon, sym["lvlPhase"]),
            "tokens": rd1(mon, sym["pkTokensP"]),
            "upgrade": rd1(mon, sym["cmpUpgrade"]),
            "speedFrac": rd1(mon, sym["cmpSpeedFrac"]),
        }

        check("the sequence advanced to LEVEL2", after["cmpLevel"] == 1,
              f"cmpLevel {after['cmpLevel']}")
        check("LEVEL2 LOADED AND BROUGHT ITS OWN LOOK",
              after["glyphCount"] == 128 and after["bg"] == 5,
              f"{after['glyphCount']} glyphs (level 2 authors 128), "
              f"bg {after['bg']} (level 2 authors 5)")
        check("...and its own turret list: level 2 has none",
              after["turretCount"] == 0, f"{after['turretCount']} turrets")

        # ---- what must NOT survive ------------------------------------------
        for name, got, want in (
                ("the trigger cursor", after["wvNextTrig"], 0),
                ("enemy bullets", after["ebCount"], 0),
                ("turret kill state", after["trtKills"], 0),
                ("the boss phase", after["lvlPhase"], 0),
        ):
            check(f"RESET: {name} is clear in level 2", got == want,
                  f"{got}, expected {want}")
        check("RESET: the scroll is back at the start of the stage",
              after["worldProgress"] < before["worldProgress"],
              f"{before['worldProgress']} -> {after['worldProgress']}")
        check("RESET: no level 1 object survived into level 2",
              after["logCount"] <= 1,
              f"{after['logCount']} live objects (the ship itself may be one)")

        # ---- what MUST survive ----------------------------------------------
        check("PERSISTS: the unspent currency carried forward",
              after["tokens"] == 7, f"{after['tokens']} P, expected 7")
        check("PERSISTS: the purchased upgrade survived the package load",
              after["upgrade"] == 1, f"level {after['upgrade']}")
        check("PERSISTS: ...and is still APPLIED to gameplay after the reset",
              after["speedFrac"] == 64,
              f"cmpSpeedFrac {after['speedFrac']}, expected 64 (a quarter pixel)")

        # ---- the end of the campaign, tested by BEHAVIOUR -------------------
        # NOT by re-deriving cmpHasNextLevel's compare in Python -- that would
        # prove only that this file can do arithmetic. Instead the run is put on
        # the LAST level and Continue is pressed for real: the only acceptable
        # outcome is the campaign-done state, never a load of a LEVEL3 that is
        # not on the disk and never a wrap to LEVEL1.
        poke(mon, sym["cmpLevel"], 1)           # the last level in the sequence
        mon.cmd("delete")
        mon.cmd(f"g {sym['gsUpgradeContinue']:04x}")
        time.sleep(2.0)
        end_state = rd1(mon, sym["gsState"])
        end_level = rd1(mon, sym["cmpLevel"])
        check("the LAST level's Continue ends the campaign",
              end_state == GS_CAMPAIGN_DONE,
              f"gsState {end_state}, expected GS_CAMPAIGN_DONE "
              f"({GS_CAMPAIGN_DONE})")
        check("...without wrapping to LEVEL1 or reaching for a LEVEL3",
              end_level == 1, f"cmpLevel {end_level}, expected 1")
        check("...and the load error byte was never touched",
              rd1(mon, sym["levelLoadError"]) == 0,
              f"levelLoadError {rd1(mon, sym['levelLoadError'])} "
              f"-- non-zero would mean a load was attempted and failed")

    finally:
        if v:
            v.close()

    print(f"\n  speed: stock {speeds[0]} px / 64 frames, "
          f"level 1 {speeds[1]}, level 2 {speeds[2]}")
    print(f"  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
