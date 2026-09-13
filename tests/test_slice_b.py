#!/usr/bin/env python3
"""Slice B — the player's weapon: cadence, heat, overheat, and the HUD feed.

What this proves
----------------
* the recovered firing behaviour is the old game's: level-triggered, a volley
  every eight frames while held, both cannons together at X+4 and X+19;
* the shot event is emitted on exactly the frames a volley resolves, carries
  both rays, and is never emitted during a lockout;
* heat is the old game's accumulator to the unit -- +2 a frame while a volley
  owns the cadence, -3 otherwise, saturating at 300 and at 0, with the lockout
  latching at 300 and clearing ON the frame heat reaches 150;
* heat cannot wrap sixteen bits at either end;
* the HUD's 48-pixel gauge is driven by that heat and by nothing else;
* the player, the HUD, the aperture and the frame transaction are unchanged.

THE STEPPING RULE, AGAIN. `mon.cmd("x")` returns on a prompt echo rather than
on the actual stop, so a sample can be read from a machine that never stopped.
Slice A verified its samples by raster and Slice A' by frame number; the weapon
is main-thread state read at a main-thread breakpoint, so this file verifies by
frame number and analyses only the longest CONTIGUOUS run it actually got.

VICE process ownership: this script owns exactly the PID it launches and kills
it on success, failure and exception via try/finally.
"""
import sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import PRG, SYM, symbols, Vice, rd, set_bp, free_run, LAUNCHED_PIDS
from test_p2 import poke

sym = symbols(SYM)

# --- the contract, restated independently of the assembler ------------------
HEAT_MAX, HEAT_REENABLE = 300, 150
HEAT_RISE, HEAT_FALL = 2, 3
FIRE_PERIOD, MUZZLE_TIME, RAYS = 8, 3, 2
FLASH_PERIOD = 8
CANNON_L, CANNON_R = 4, 19
GAUGE_PIXELS = 48
JOY_IDLE, JOY_FIRE_BIT = 0b00011111, 0b00010000
JOY_FIRE = JOY_IDLE & ~JOY_FIRE_BIT                 # active low: fire held
FRAME_IRQ_LINE = 250
PLAYER_SLOT_MASK = 0b00000011
PTR_BASE, PTR_TRIM, PTR_FIRE = 0xd6, 0xd7, 0xd8
COL_BASE, COL_MUZZLE = 14, 2
HUD_HEAT_COL_NORMAL, HUD_HEAT_COL_ALARM, HUD_HEAT_COL_BLANK = 0x07, 0x02, 0x00

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


# ===========================================================================
def source_invariants():
    print("=== 1. weapon ownership (source level) ===")
    src = {p.name: p.read_text() for p in (ROOT / "src").glob("*.asm")}
    w = src["weapon.asm"]

    check("weapon.asm writes no VIC register",
          not re.search(r"^\s*sta\s+\$d0", w, re.M | re.I))
    check("weapon.asm writes no sprite pointer table",
          not re.search(r"^\s*sta\s+(?:PTR_[AB]|\$07f8|\$2bf8)", w, re.M | re.I))
    check("weapon.asm never reads the joystick port directly",
          not re.search(r"\$dc0[01]", w), "it consumes joyState")
    check("weapon.asm writes no HUD bitmap or pointer table",
          "HUD_SPRITES" not in w and "hudPtrLive" not in w)
    check("the gauge colour goes through the HUD's own setter",
          "jsr hudSetHeatColour" in w and "sta hudCol" not in w)

    # Heat had a demo writer and now has a gameplay one. TWO writers of one
    # logical value is how a HUD starts disagreeing with the game.
    writers = {n: len(re.findall(r"^\s*sta\s+hudHeat(?:Lo|Hi)", t, re.M))
               for n, t in src.items()}
    writers = {n: c for n, c in writers.items() if c}
    check("exactly one module writes the HUD's logical heat",
          writers == {"weapon.asm": 2}, f"{writers}")
    check("the HUD demo no longer ramps heat",
          "hudDemoHeatDir" not in src["hud.asm"])

    # Slice A asserted fire was defined and unused. It is used now, and by the
    # weapon only -- the input layer must not decide weapon timing.
    check("the player samples fire but does not act on it",
          "JOY_FIRE" in src["player.asm"]
          and len([l for l in src["player.asm"].splitlines()
                   if "JOY_FIRE" in l and not l.strip().startswith(("//", ".const"))]) == 0)
    check("the weapon is the only consumer of the fire bit",
          "and #JOY_FIRE" in w)


# ===========================================================================
WSTATE = ("wpnHeatLo", "wpnHeatHi", "wpnOverheated", "wpnCooldown",
          "wpnFlashTimer", "wpnFlashPhase", "shotFired", "shotRays")
WBASE = sym["wpnHeatLo"]
WSPAN = sym["shotY"] - WBASE + 1


def weapon(mon):
    """Weapon, player, published block and HUD heat, at ONE instant.

    All four in the same stopped moment on purpose. An earlier draft read the
    weapon inside a stepped run and the HUD heat after it, and reported that
    the feed was thirteen frames out of date -- which it was, because the two
    readings were thirteen frames apart.
    """
    # THREE commands, not six. The player's scalars and its published block are
    # contiguous, and so are the HUD's logical heat and its drawn pixel count,
    # so each group is one dump. Every monitor round trip is about a third of a
    # second and this routine runs thousands of times.
    w = rd(mon, WBASE, WSPAN)
    p = rd(mon, sym["plyX"], sym["plyPres"] - sym["plyX"] + 10)
    h = rd(mon, sym["hudHeatLo"], sym["hudHeatPix"] - sym["hudHeatLo"] + 1)
    pres = p[sym["plyPres"] - sym["plyX"]:]
    g = lambda n: w[sym[n] - WBASE]
    return {
        "heat": g("wpnHeatLo") | (g("wpnHeatHi") << 8),
        "locked": g("wpnOverheated"), "cd": g("wpnCooldown"),
        "flashPhase": g("wpnFlashPhase"),
        "fired": g("shotFired"), "rays": g("shotRays"),
        "shotX": [w[sym["shotXLo"] - WBASE + i] | (w[sym["shotXHi"] - WBASE + i] << 8)
                  for i in range(RAYS)],
        "shotY": g("shotY"),
        "plyX": p[0] | (p[1] << 8), "plyY": p[2], "muzzle": p[4],
        "hudHeat": h[0] | (h[1] << 8),
        "hudPix": h[sym["hudHeatPix"] - sym["hudHeatLo"]],
        "presPtr0": pres[2], "presCol0": pres[3], "presPtr1": pres[6],
    }


SPAWNER_BYTE = [None]

def quiet_mux(mon):
    """Switch the production spawner off and empty the pool.

    This file measures the WEAPON. Slice C gave production enemies that spawn on
    a timer and Slice D gave them a death state, so the number of live objects
    -- and therefore the cost of a frame and whether one is ever missed -- now
    varies underneath any measurement that does not say otherwise. Patched to
    RTS rather than delayed by its timer, because a timer poked to its maximum
    expires many times over inside one warp second.
    """
    if SPAWNER_BYTE[0] is None:
        SPAWNER_BYTE[0] = rd(mon, sym["enemySpawnTick"])[0]
    poke(mon, sym["enemySpawnTick"], 0x60)
    for i in range(16):
        mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={sym['objectFree']:04x}, x={i:02x}")
        bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
    mon.cmd("delete")


def busy_mux(mon):
    """Hand production back its enemies."""
    if SPAWNER_BYTE[0] is not None:
        poke(mon, sym["enemySpawnTick"], SPAWNER_BYTE[0])


def arm(mon, joy=JOY_IDLE, heat=0, locked=0, cd=0, phase=0):
    """Put the weapon in a named state and hold the stick there."""
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["joyState"], joy)
    poke(mon, sym["wpnHeatLo"], heat & 0xff)
    poke(mon, sym["wpnHeatHi"], heat >> 8)
    poke(mon, sym["wpnOverheated"], locked)
    poke(mon, sym["wpnCooldown"], cd)
    poke(mon, sym["wpnFlashPhase"], phase)


def steps(mon, n):
    """n game frames, as the longest CONTIGUOUS run, sampled where EVERYTHING
    this slice touches is already this frame's.

    hudDemoTick is the first call after playerEmit in gameFrame, so a stop at
    its entry sees the weapon ticked, the HUD fed AND the presentation block
    emitted -- all for the same frame. Stopping at playerEmit instead sees the
    block from the frame BEFORE, which is how an earlier draft concluded the
    muzzle flash was never published.
    """
    out = []
    mon.cmd("delete")
    b = set_bp(mon, sym["hudDemoTick"])
    for _ in range(n + 6):
        mon.cmd("x")
        f = rd(mon, sym["frameCounter"], 2)
        s = weapon(mon)
        s["frame"] = f[0] | (f[1] << 8)
        out.append(s)
    mon.cmd(f"delete {b}")
    mon.cmd("delete")
    uniq = [s for i, s in enumerate(out) if i == 0 or s["frame"] != out[i - 1]["frame"]]
    best, run = [], [uniq[0]] if uniq else []
    for a, c in zip(uniq, uniq[1:]):
        if ((c["frame"] - a["frame"]) & 0xffff) == 1:
            run.append(c)
        else:
            best, run = (run if len(run) > len(best) else best), [c]
    return run if len(run) > len(best) else best


def step1(mon, tries=6):
    """ONE game frame, verified. Most checks here poke a state and look at the
    very next frame; running a full contiguous trace for that is ten times the
    monitor traffic for one tenth of the information."""
    mon.cmd("delete")
    b = set_bp(mon, sym["hudDemoTick"])
    f0 = rd(mon, sym["frameCounter"], 2)
    prev = f0[0] | (f0[1] << 8)
    for _ in range(tries):
        mon.cmd("x")
        s = weapon(mon)
        f = rd(mon, sym["frameCounter"], 2)
        now = f[0] | (f[1] << 8)
        if ((now - prev) & 0xffff) == 1:
            mon.cmd(f"delete {b}")
            mon.cmd("delete")
            return s
        prev = now
    mon.cmd(f"delete {b}")
    mon.cmd("delete")
    check("a single frame step landed", False, "the counter never advanced by one")
    return s


# ===========================================================================
def idle(mon):
    print("\n=== 2. idle: a cold gun stays cold ===")
    arm(mon, JOY_IDLE)
    free_run(mon, sym["frameCounter"], 2)
    w = weapon(mon)
    check("heat stays at zero with the stick released", w["heat"] == 0, f"{w['heat']}")
    check("the weapon is not locked out", w["locked"] == 0)
    check("no shot event is pending", w["fired"] == 0)
    check("the HUD's logical heat agrees",
          (rd(mon, sym["hudHeatLo"])[0] | (rd(mon, sym["hudHeatLo"] + 1)[0] << 8)) == 0)
    check("the gauge is empty", rd(mon, sym["hudHeatPix"])[0] == 0,
          f"{rd(mon, sym['hudHeatPix'])[0]} px")
    check("the gauge is its resting colour",
          rd(mon, sym["hudCol"] + 1, 2) == [HUD_HEAT_COL_NORMAL] * 2)


def firing(mon):
    print("\n=== 3. held fire: cadence, rays and heat, frame by frame ===")
    quiet_mux(mon)                      # a long contiguous run needs a frame
                                        # the game is not also busy filling
    arm(mon, JOY_FIRE)
    t = steps(mon, 26)
    print(f"  {len(t)} contiguous frames")
    print(f"  fired    {[s['fired'] for s in t]}")
    print(f"  cooldown {[s['cd'] for s in t]}")
    print(f"  heat     {[s['heat'] for s in t]}")
    print(f"  muzzle   {[s['muzzle'] for s in t]}")
    check("enough contiguous frames to judge the cadence", len(t) >= 18, f"{len(t)}")

    shots = [i for i, s in enumerate(t) if s["fired"]]
    check("volleys were fired while the button was held", len(shots) >= 2, f"{len(shots)}")
    gaps = [b - a for a, b in zip(shots, shots[1:])]
    check(f"a volley every {FIRE_PERIOD} frames, no more and no less",
          bool(gaps) and all(g == FIRE_PERIOD for g in gaps), f"{gaps}")
    check("the shot event is true on the volley frame and false on every other",
          all((i in shots) == bool(s["fired"]) for i, s in enumerate(t)))

    # Heat is per FRAME while a volley owns the cadence, not per shot.
    rises = [b["heat"] - a["heat"] for a, b in zip(t, t[1:])
             if b["heat"] <= HEAT_MAX - HEAT_RISE]
    check(f"heat rises exactly {HEAT_RISE} per frame while firing",
          bool(rises) and all(r == HEAT_RISE for r in rises),
          f"{sorted(set(rises))}")
    check("the cadence timer is never zero while the button is held",
          all(s["cd"] != 0 for s in t), f"{[s['cd'] for s in t]}")

    # Both cannons, together, at the offsets the muzzle art is drawn at.
    for i in shots[:3]:
        s = t[i]
        ok = (s["rays"] == RAYS
              and s["shotX"][0] == s["plyX"] + CANNON_L
              and s["shotX"][1] == s["plyX"] + CANNON_R
              and s["shotY"] == s["plyY"])
        check(f"  frame {i}: two rays at X+{CANNON_L} and X+{CANNON_R}, Y = the ship's",
              ok, f"rays {s['rays']} X {s['shotX']} vs ply {s['plyX']} Y {s['shotY']}/{s['plyY']}")

    muz = [s["muzzle"] for s in t]
    check(f"the muzzle flash is held for {MUZZLE_TIME} frames after a volley",
          all(muz[i] == MUZZLE_TIME for i in shots)
          and all(muz[i + MUZZLE_TIME] == 0 for i in shots if i + MUZZLE_TIME < len(muz)),
          f"{muz[:12]}")


def released(mon):
    print("\n=== 4. released: cooling, and no cooling while firing ===")
    arm(mon, JOY_IDLE, heat=200, cd=0)
    t = steps(mon, 7)
    falls = [a["heat"] - b["heat"] for a, b in zip(t, t[1:])]
    check(f"heat falls exactly {HEAT_FALL} per frame with the stick released",
          bool(falls) and all(f == HEAT_FALL for f in falls), f"{sorted(set(falls))}")
    check("no shot event is emitted with the stick released",
          all(s["fired"] == 0 for s in t))
    # The accumulator is strictly either/or: it never both rises and falls.
    arm(mon, JOY_FIRE, heat=200, cd=0)
    t = steps(mon, 7)
    d = [b["heat"] - a["heat"] for a, b in zip(t, t[1:])]
    check("heat only ever rises while firing -- cooling does not overlap it",
          bool(d) and all(x == HEAT_RISE for x in d), f"{sorted(set(d))}")


def overheat(mon):
    print("\n=== 5. the lockout: thresholds, refusal and recovery ===")
    # Latches exactly at the ceiling, and saturates rather than passing it.
    arm(mon, JOY_FIRE, heat=HEAT_MAX - HEAT_RISE, cd=1)
    s = step1(mon)
    check(f"the lock latches on the frame heat reaches {HEAT_MAX}",
          s["heat"] == HEAT_MAX and s["locked"] == 1,
          f"heat {s['heat']} locked {s['locked']}")
    arm(mon, JOY_FIRE, heat=HEAT_MAX - 1, cd=1)
    s = step1(mon)
    check("heat saturates at the ceiling instead of passing it",
          s["heat"] == HEAT_MAX, f"{s['heat']}")

    # A held button cannot fire, and cannot keep the gun hot, during a lockout.
    arm(mon, JOY_FIRE, heat=HEAT_MAX, locked=1, cd=0)
    t = steps(mon, 8)
    check("NO shot event is emitted while locked out",
          all(s["fired"] == 0 for s in t), f"{[s['fired'] for s in t]}")
    check("a held button cannot re-arm the cadence during a lockout",
          all(s["cd"] == 0 for s in t), f"{[s['cd'] for s in t]}")
    check("heat falls during the lockout even with the button held",
          t[-1]["heat"] < t[0]["heat"], f"{t[0]['heat']} -> {t[-1]['heat']}")
    check("the gauge flashes while locked out", t[2]["flashPhase"] != 0,
          f"phase {t[2]['flashPhase']}")
    cols = rd(mon, sym["hudCol"] + 1, 2)
    check("both gauge halves carry the same alarm colour",
          cols[0] == cols[1] and cols[0] in (HUD_HEAT_COL_ALARM, HUD_HEAT_COL_BLANK),
          f"{[hex(c) for c in cols]}")

    # The unlock threshold, both sides of it. The old game compares against
    # REENABLE+1 so the unlock happens ON the frame heat reaches 150.
    arm(mon, JOY_IDLE, heat=HEAT_REENABLE + HEAT_FALL, locked=1, cd=0)
    s = step1(mon)
    check(f"the lock clears ON the frame heat reaches {HEAT_REENABLE}",
          s["heat"] == HEAT_REENABLE and s["locked"] == 0,
          f"heat {s['heat']} locked {s['locked']}")
    arm(mon, JOY_IDLE, heat=HEAT_REENABLE + HEAT_FALL + 1, locked=1, cd=0)
    s = step1(mon)
    check(f"and stays locked one unit above it",
          s["heat"] == HEAT_REENABLE + 1 and s["locked"] == 1,
          f"heat {s['heat']} locked {s['locked']}")

    # ...and firing resumes.
    arm(mon, JOY_FIRE, heat=HEAT_REENABLE, locked=0, cd=0)
    s = step1(mon)
    check("firing resumes once the lock has cleared", s["fired"] == 1)

    # The colour is restored ONCE, on the frame the flash stops -- so it has to
    # be watched ACROSS that frame. Reading the byte some frames later passes on
    # whatever the previous section happened to leave behind, which is the same
    # mismatched-instants mistake this file made twice already.
    arm(mon, JOY_IDLE, heat=HEAT_REENABLE + HEAT_FALL, locked=1, phase=1)
    poke(mon, sym["wpnFlashTimer"], FLASH_PERIOD)
    poke(mon, sym["hudCol"] + 1, HUD_HEAT_COL_ALARM)
    poke(mon, sym["hudCol"] + 2, HUD_HEAT_COL_ALARM)
    before = rd(mon, sym["hudCol"] + 1, 2)
    s = step1(mon)
    after = rd(mon, sym["hudCol"] + 1, 2)
    check("the gauge colour is restored ON the frame the lock clears",
          s["locked"] == 0 and before == [HUD_HEAT_COL_ALARM] * 2
          and after == [HUD_HEAT_COL_NORMAL] * 2,
          f"locked {s['locked']}, {[hex(c) for c in before]} ->"
          f" {[hex(c) for c in after]}")
    check("and the flash latch is cleared with it",
          s["flashPhase"] == 0, f"phase {s['flashPhase']}")

    # ...and it is NOT rewritten every frame afterwards: the restore is a
    # one-shot, so a frame later the byte is still normal and still untouched.
    poke(mon, sym["hudCol"] + 1, HUD_HEAT_COL_NORMAL)
    s = step1(mon)
    check("the restore does not run again on later unlocked frames",
          rd(mon, sym["hudCol"] + 1, 2) == [HUD_HEAT_COL_NORMAL] * 2,
          f"{[hex(c) for c in rd(mon, sym['hudCol'] + 1, 2)]}")


def boundaries(mon):
    print("\n=== 6. sixteen-bit boundaries: heat cannot wrap at either end ===")
    for start in (HEAT_FALL, HEAT_FALL - 1, 1, 256, 255, 258):
        arm(mon, JOY_IDLE, heat=start, cd=0)
        s = step1(mon)
        want = max(0, start - HEAT_FALL)
        check(f"  cooling from {start} -> {want}", s["heat"] == want,
              f"got {s['heat']}")
    # A poked-absurd value must clamp, not wrap: the ceiling test reads the high
    # byte first and a naive version would let 600 sail past 300.
    arm(mon, JOY_FIRE, heat=600, cd=1)
    s = step1(mon)
    check("  an out-of-range heat clamps down to the ceiling",
          s["heat"] == HEAT_MAX, f"{s['heat']}")


def hud_scale(mon):
    print("\n=== 7. the 48-pixel gauge is driven by real heat ===")
    # THE MAPPING, read out of the binary and checked as a mapping rather than
    # against a second copy of the implementation.
    d = (ROOT / "build/shmup.prg").read_bytes()
    load = d[0] | (d[1] << 8)
    tbl = list(d[2 + sym["heatPix"] - load: 2 + sym["heatPix"] - load + 76])
    check("the mapping starts empty and ends full",
          tbl[0] == 0 and tbl[75] == GAUGE_PIXELS, f"{tbl[0]}..{tbl[75]}")
    check("it never exceeds the gauge", max(tbl) <= GAUGE_PIXELS, f"max {max(tbl)}")
    check("it is monotonic", all(b >= a for a, b in zip(tbl, tbl[1:])))
    check("it is linear to within half a pixel",
          all(abs(v - i * GAUGE_PIXELS / 75) <= 0.5 for i, v in enumerate(tbl)),
          f"worst {max(abs(v - i * GAUGE_PIXELS / 75) for i, v in enumerate(tbl)):.2f}")

    # THE FEED, stepped one frame at a time. Only two heats are STABLE on a
    # running machine -- zero and the ceiling -- because the accumulator moves
    # every frame by design, so an intermediate value cannot be held still and
    # then read at leisure. What can be checked at any value is that the HUD's
    # logical heat IS the weapon's, exactly; composed with the mapping above,
    # that is the whole 0..300 -> 0..48 path.
    for heat in (1, 75, 149, 150, 226, 299):
        arm(mon, JOY_IDLE, heat=heat, cd=0)
        s = step1(mon)
        check(f"  the HUD's logical heat is the weapon's at {s['heat']}",
              s["heat"] == s["hudHeat"], f"hud {s['hudHeat']}")

    # THE ENDPOINTS, live, at the two heats that hold still.
    arm(mon, JOY_IDLE, heat=0, cd=0)
    free_run(mon, sym["frameCounter"], 1)
    check("  heat 0 leaves the gauge empty", rd(mon, sym["hudHeatPix"])[0] == 0,
          f"{rd(mon, sym['hudHeatPix'])[0]} px")
    # THE CEILING IS NOT A RESTING PLACE. Reaching 300 latches the lockout,
    # which immediately starts cooling, so held fire is a sawtooth and there is
    # no non-zero heat a free-running machine will sit at. The gauge is
    # therefore checked over a whole cycle: it must REACH full and must never
    # pass it.
    # THE FULL GAUGE IS A ONE-FRAME EVENT, and that is the mechanic rather than
    # a defect: heat reaches 300 on exactly one frame and the lockout it latches
    # starts cooling on the next, so the bar is full for one frame in every 125.
    # A coarse sampler will never land on it -- an earlier draft took 24 samples
    # across whole cycles and reported a worst fill of 47 px on a machine that
    # was filling correctly. Stepping through the peak is the only honest way to
    # see it.
    arm(mon, JOY_FIRE, heat=HEAT_MAX - 8, cd=1)
    t = steps(mon, 10)
    pix = [s["hudPix"] for s in t]
    print(f"  heat {[s['heat'] for s in t]}")
    print(f"  px   {pix}")
    check("  the gauge fills completely as heat crosses the ceiling",
          GAUGE_PIXELS in pix, f"{sorted(set(pix))}")
    check("  the drawn bar never exceeds the gauge", max(pix) <= GAUGE_PIXELS,
          f"max {max(pix)}")

    # ...and over whole cycles it moves through the range rather than sticking.
    arm(mon, JOY_FIRE, heat=0, cd=0)
    seen = []
    for _ in range(20):
        free_run(mon, sym["frameCounter"], 0.25, slice_s=0.25)
        seen.append(rd(mon, sym["hudHeatPix"])[0])
    check("  the gauge really does track the heat cycle",
          len(set(seen)) > 5 and max(seen) <= GAUGE_PIXELS, f"{sorted(set(seen))}")
    arm(mon, JOY_IDLE, heat=0, cd=0)


def unchanged(mon):
    print("\n=== 8. everything Slices A and A' established is unchanged ===")
    quiet_mux(mon)                      # BEFORE the idle sample, not between it
                                        # and the other two: three spans are only
                                        # comparable if all three saw one world
    arm(mon, JOY_IDLE, heat=0, cd=0)
    mon.cmd("delete")
    for n in ("hudEntryMin", "handoffEntryMin", "topSplitMin", "botSplitMin",
              "hudUpdStartMin"):
        mon.cmd(f"> {sym[n]:04x} ff")
        mon.cmd(f"> {sym[n] + 1:04x} 00")
    for n in ("hudExitMax", "handoffExitMax", "edgeLate", "hudUpdWrapped",
              "scrollLate", "statPageMismatch", "statPtrMismatch", "publishSkip",
              "gameOverrun", "gameSpanMax", "gameSpanOver"):
        mon.cmd(f"> {sym[n]:04x} 00")
    free_run(mon, sym["frameCounter"], 6)
    g = lambda n, k=1: rd(mon, sym[n], k)
    check("the frame transaction is still at raster 250",
          g("frameEntryLine")[0] == FRAME_IRQ_LINE, f"{g('frameEntryLine')[0]}")
    check("the aperture splits are still 54/55 and 248",
          tuple(g("topSplitMin", 2)) == (54, 55) and g("botSplitMin", 2) == [248, 248],
          f"{g('topSplitMin', 2)} {g('botSplitMin', 2)}")
    check("no split was ever late", g("edgeLate")[0] == 0)
    check("the HUD phase still enters at 4 and finishes before its own fetch",
          g("hudEntryMin", 2) == [4, 4] and g("hudExitMax")[0] < 17,
          f"enter {g('hudEntryMin', 2)} exit {g('hudExitMax')[0]}")
    check("the handoff still enters at 40 and finishes before the top split",
          g("handoffEntryMin", 2) == [40, 40] and 0 < g("handoffExitMax")[0] < 53,
          f"exit {g('handoffExitMax')[0]}")
    check("no HUD bitmap write reached the VIC's fetch window",
          g("hudUpdWrapped")[0] == 0 and g("hudUpdStartMin")[0] >= 56)
    check("ZERO page and pointer mismatches",
          g("statPageMismatch")[0] == 0 and g("statPtrMismatch")[0] == 0)
    check("the scroller is clean", g("scrollLate")[0] == 0 and g("publishSkip")[0] == 0)
    idle_span = g("gameSpanMax")[0]
    check("the main thread finishes inside the frame, idle",
          g("gameOverrun")[0] == 0 and g("gameSpanOver")[0] == 0 and idle_span < 250,
          f"span {idle_span}")

    # THREE STATES, so the cost can be ATTRIBUTED rather than guessed at.
    #
    # A player whose appearance changes has to be republished: playerEmit
    # notices the block changed, plyDirty is set, and the frame rebuilds and
    # publishes a schedule. MOVING does that on every frame; FIRING does it
    # twice per volley, when the muzzle flash starts and stops. So if the
    # weapon itself were expensive, firing would cost more than moving -- and
    # if the cost is republication, the two will sit together, well above idle.
    def span_of(label, joy):
        for n in ("gameOverrun", "gameSpanMax", "gameSpanOver", "publishSkip"):
            mon.cmd(f"> {sym[n]:04x} 00")
        arm(mon, joy, heat=0, cd=0)
        free_run(mon, sym["frameCounter"], 6)
        sp = g("gameSpanMax")[0]
        check(f"the main thread finishes inside the frame, {label}",
              g("gameOverrun")[0] == 0 and g("gameSpanOver")[0] == 0 and sp < 250,
              f"span {sp} overrun {g('gameOverrun')[0]} skips {g('publishSkip')[0]}")
        return sp

    # ALL THREE SAMPLES MUST SEE THE SAME WORLD. With enemies spawning and
    # dying underneath them, idle/moving/firing are three different populations
    # and their difference measures the game rather than the weapon -- which is
    # how an earlier run produced a "moving" frame cheaper than an idle one.
    move_span = span_of("moving", JOY_IDLE & ~0b00000100)
    fire_span = span_of("firing", JOY_FIRE)
    print(f"  ..  main-thread span: idle {idle_span}, moving {move_span}, "
          f"firing {fire_span} raster lines (~{fire_span * 63} cycles of 19656)")
    # SLICE D WIDENED WHAT "FIRING" MEANS. A firing frame now also resolves the
    # hitscan: collisionTick walks all sixteen pool slots once per cannon, with
    # no early exit, whether or not anything is there to hit. That work is real,
    # it is the point of that slice, and it lands on exactly the frames this
    # comparison calls "firing" -- so the bound covers weapon AND collision
    # rather than pretending the gun still fires into nothing.
    #
    # Measured with an empty pool: about twenty raster lines, some 1300 cycles,
    # for two sixteen-slot scans. tests/test_slice_d.py attributes the collision
    # half of it directly, by switching collisionTick off and re-measuring.
    #
    # AND THE TURRET COMBAT SLICE WIDENED IT AGAIN, for the same reason and in
    # the same way. traceRay now ends by calling traceTurretRay, which walks all
    # eight authored turrets once per cannon -- so a firing frame carries two
    # sixteen-slot object scans AND two eight-turret scans. Measured at 30
    # raster lines against the 26 this bound was set at, which is the ~250
    # cycles those two extra scans cost.
    #
    # THE BOUND IS RAISED, NOT REMOVED, and it is still the thing that would
    # catch a hitscan that started doing real work per frame rather than per
    # volley. Only the firing frame pays it: turretWorldTick and turretPaintTick
    # run on EVERY frame, so they are in `moving` as well and cancel out of this
    # difference entirely.
    weapon_and_collision = fire_span - move_span
    check("firing plus its hitscan costs a bounded amount over moving",
          weapon_and_collision <= 34,
          f"firing {fire_span} vs moving {move_span}: {weapon_and_collision} "
          f"raster lines for the volley, both cannon scans and both turret scans")
    check("and moving and idle sit close together, both being republication",
          abs(move_span - idle_span) <= 20,
          f"idle {idle_span} moving {move_span}")

    # The player is still the player. Stepped from a known position: a
    # free-run under warp is thousands of frames and simply parks the ship
    # against a bound, which says nothing about whether it moves.
    arm(mon, JOY_IDLE & ~0b00000100, heat=0, cd=0)          # left
    poke(mon, sym["plyX"], 160)
    poke(mon, sym["plyXHi"], 0)
    t = steps(mon, 8)
    span = len(t) - 1
    check("the player still moves one pixel per frame",
          t[-1]["plyX"] == t[0]["plyX"] - span,
          f"{t[0]['plyX']} -> {t[-1]['plyX']} over {span} frames")
    check("...and does not heat the gun by moving",
          all(s["heat"] == 0 for s in t), f"{[s['heat'] for s in t]}")

    arm(mon, JOY_IDLE & ~0b00000100 & ~JOY_FIRE_BIT, heat=0, cd=0)   # left + fire
    poke(mon, sym["plyX"], 160)
    poke(mon, sym["plyXHi"], 0)
    t = steps(mon, 10)
    span = len(t) - 1
    check("moving and firing at the same time does both",
          t[-1]["plyX"] == t[0]["plyX"] - span and t[-1]["heat"] > t[0]["heat"]
          and any(s["fired"] for s in t),
          f"X {t[0]['plyX']} -> {t[-1]['plyX']}, heat {t[0]['heat']} -> {t[-1]['heat']}")
    # VERIFY WHERE THE SAMPLE WAS TAKEN. `mon.cmd("x")` returns on a prompt
    # echo rather than on the stop, so a read can come from a machine that never
    # stopped -- and a $d015 read at raster 0 is legitimately $00, because the
    # frame transaction disables every sprite through the ghost window. That
    # reads exactly like the player having vanished. It is the same trap Slices
    # A and A' were bitten by, in the one place this file left unguarded.
    d015, raster = None, None
    b = set_bp(mon, sym["exBottom"])
    for _ in range(8):
        mon.cmd("x")
        raster = rd(mon, 0xd012)[0]
        if 243 <= raster <= 248:
            d015 = rd(mon, 0xd015)[0]
            break
    mon.cmd(f"delete {b}"); mon.cmd("delete")
    check("the $d015 sample was taken where gameplay owns the register",
          d015 is not None, f"last raster {raster}")
    if d015 is None:
        d015 = 0
    busy_mux(mon)
    check("the player is still enabled on both reserved slots",
          (d015 & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK, f"${d015:02x} at raster 243")
    # "No fixture" used to be the same statement as "logCount is zero", because
    # nothing else could put a logical sprite in the pool. Slice C's enemies can,
    # so the check now says what it always meant: no fixture is loaded, and
    # anything in the pool got there through the production object pool.
    live = [i for i in range(32) if rd(mon, sym["logActive"], 32)[i]]
    types = rd(mon, sym["objType"], 16)
    check("production startup still presents no fixture",
          rd(mon, sym["fixtureMoves"])[0] == 0
          and all(i < 16 and types[i] == 1 for i in live),
          f"fixtureMoves {rd(mon, sym['fixtureMoves'])[0]}, live {live}")


def muzzle_art(mon):
    print("\n=== 9. the muzzle flash goes out through the published block ===")
    arm(mon, JOY_FIRE, heat=0, cd=0)
    t = steps(mon, 11)
    flash = [s for s in t if s["muzzle"] != 0]
    rest = [s for s in t if s["muzzle"] == 0]
    check("both a flashing and a resting frame were sampled",
          bool(flash) and bool(rest), f"{len(flash)} flashing, {len(rest)} resting")
    check("resting publishes the resting hull in the hull colour",
          all((s["presPtr0"], s["presCol0"], s["presPtr1"])
              == (PTR_BASE, COL_BASE, PTR_TRIM) for s in rest),
          f"{[(hex(s['presPtr0']), s['presCol0']) for s in rest[:2]]}")
    check("flashing publishes the firing hull in red, with the trim unchanged",
          all((s["presPtr0"], s["presCol0"], s["presPtr1"])
              == (PTR_FIRE, COL_MUZZLE, PTR_TRIM) for s in flash),
          f"{[(hex(s['presPtr0']), s['presCol0']) for s in flash[:2]]}")
    check("the overlay pointer is the only thing the flash changes",
          all(s["presPtr1"] == PTR_TRIM for s in t))
    arm(mon, JOY_IDLE, heat=0, cd=0)


# ===========================================================================
if __name__ == "__main__":
    source_invariants()
    v = None
    try:
        v = Vice(6612, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        idle(mon)
        firing(mon)
        released(mon)
        overheat(mon)
        boundaries(mon)
        hud_scale(mon)
        muzzle_art(mon)
        unchanged(mon)
    finally:
        if v:
            v.close()
    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    print("\n=== ALL PASS ===" if not fails
          else f"\n=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
    sys.exit(1 if fails else 0)
