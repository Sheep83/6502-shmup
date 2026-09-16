#!/usr/bin/env python3
"""Dropper Flight v1 — three upper-screen passes, and the sonar ping.

What this proves, watching the REAL production loop the whole time
------------------------------------------------------------------
* AUTHORED ENTRY SIDE: a Dropper enters from the side its trigger authored,
  and the mirrored appearance enters from the other side through the SAME
  routine -- same pass count, same weave, same code path;
* THE UPPER BAND: every frame of the flight sits inside the authored Y window,
  and the Dropper is seen both above and below its centreline;
* IT IS NOT FLYING A WAVE PATH: its logY is exactly centre + weave[phase] on
  every frame, its wmVY stays truthfully zero, and its wave stage never
  advances -- while ordinary Rings on screen are still running the movement
  interpreter normally;
* EXACTLY THREE TRAVERSALS: the pass counter walks 3 -> 2 -> 1 -> 0 and no
  further, with a direction reversal after the first two and NONE after the
  third;
* IT LEAVES BY THE OPPOSITE SIDE and is retired by the ordinary despawn rule;
* AN ESCAPE DROPS NOTHING: no token is created, and the one-Dropper flag is
  released so the next authored Dropper can fly;
* A DEATH STILL DROPS EXACTLY ONE P at the logical death position, and the
  protector encounter still starts;
* THE PING: it sounds only while a Dropper is alive, at the authored cadence,
  and stops dead when the Dropper does;
* VOICE 2 IS NOT RESERVED between pings -- a routine enemy effect requested in
  the silence takes the voice normally;
* ...but a routine effect requested WHILE the ping is sounding is refused;
* ...and a destruction is NOT refused, so the Dropper's own death is audible.

What this does NOT prove
------------------------
Whether the flight looks smooth, whether the ping sounds good, or whether the
cadence is pleasant. Those are manual-VICE questions and manual VICE is
authoritative for them.

WHAT THIS FILE STAGES, AND WHAT IT DOES NOT. Gameplay is staged exactly once,
the way src/collision.asm does it: objTimer to DEATH_TIME then objHP to zero,
which IS the logical destruction event. Everything downstream -- the species
test, the position capture, the token spawn -- is production code in the
production loop.

The SOUND checks additionally CALL sfxRequest directly, with a synthetic return
address, which is the one thing in this game that cannot be provoked on demand
from the outside: an enemy has to shoot, and whether one does during the four
frames of a ping is luck. sfxRequest is self-contained -- it reads its tables,
writes SID registers and returns -- which is exactly the kind of routine
harness.call documents as safe to call this way.

One VICE launch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, check, report)

sym = symbols(SYM)

MAX_OBJECTS = 16
MAX_LOGICAL = 32        # logY/logX/logXHi/logActive stride; see the v2.1 report
TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET, TYPE_PICKUP = 0, 1, 2, 3
SPECIES_RING, SPECIES_DROPPER = 0, 8
DEATH_TIME = 12

# --- src/dropper.asm's constants, restated ---------------------------------
DROP_CENTRE_Y = 88
DROP_AMPLITUDE = 16
DROP_PHASES = 32
DROP_PHASE_HOLD = 2
DROP_PASSES = 3
DROP_X_LEFT, DROP_X_RIGHT = 24, 320
DROP_ENTRY_LEFT, DROP_ENTRY_RIGHT = 0, 343
DROP_PING_PERIOD = 48
DROP_PING_FIRST = 8
DROP_SIDE_LEFT, DROP_SIDE_RIGHT = 0, 1

# --- src/sfx.asm's -----------------------------------------------------------
SFX_NONE, SFX_FIRE, SFX_KILL, SFX_HURT, SFX_ESHOT, SFX_TOKEN, SFX_PING = range(7)
SFX_CH_KILL = 1                 # voice 2
SFX_PING_FRAMES = 4 + 2         # sweep + release + clear

HUNT_FRAMES = 1400              # a full authored cycle is ~1000 frames
FLIGHT_FRAMES = 700             # three passes at 3 px/frame is ~600
PING_SPAN_WANTED = 3            # pings to time before believing the cadence


def sample(mon):
    """One frame's judgement, in six bulk reads."""
    pos = rd(mon, sym["logY"], 3 * MAX_LOGICAL)         # logY, logX, logXHi
    pool = rd(mon, sym["logActive"], 0x60 + MAX_OBJECTS)  # logActive..objTimer
    spec = rd(mon, sym["enySpecies"], MAX_OBJECTS)
    mv = rd(mon, sym["wmMode"], 0x60 + MAX_OBJECTS)     # wmMode..wmVY
    dr = rd(mon, sym["drPassLeft"], 7)                  # the whole flight state
    snd = rd(mon, sym["sfxChId"], 3)
    fc = rd(mon, sym["frameCounter"], 2)
    return {
        "frame": fc[0] | (fc[1] << 8),
        "logY": pos[0:MAX_OBJECTS],
        "logX": pos[MAX_LOGICAL:MAX_LOGICAL + MAX_OBJECTS],
        "logXHi": pos[2 * MAX_LOGICAL:2 * MAX_LOGICAL + MAX_OBJECTS],
        "active": pool[0:MAX_OBJECTS],
        "type": pool[0x20:0x20 + MAX_OBJECTS],
        "hp": pool[0x50:0x50 + MAX_OBJECTS],
        "timer": pool[0x60:0x60 + MAX_OBJECTS],
        "species": spec,
        "wmMode": mv[0x00:0x00 + MAX_OBJECTS],
        "wmStage": mv[0x10:0x10 + MAX_OBJECTS],
        "wmVX": mv[0x50:0x50 + MAX_OBJECTS],
        "wmVY": mv[0x60:0x60 + MAX_OBJECTS],
        "passLeft": dr[0], "phase": dr[1], "hold": dr[2], "ping": dr[3],
        "launched": dr[4], "escaped": dr[5], "pinged": dr[6],
        "voice2": snd[SFX_CH_KILL],
    }


def check_layout():
    """Every bulk read above assumes a contiguity. Prove them, don't trust them."""
    check("logY/logX/logXHi are contiguous at the LOGICAL stride",
          sym["logX"] == sym["logY"] + MAX_LOGICAL
          and sym["logXHi"] == sym["logY"] + 2 * MAX_LOGICAL)
    check("logActive/objType/objHP/objTimer sit where the bulk read assumes",
          sym["objType"] == sym["logActive"] + 0x20
          and sym["objHP"] == sym["logActive"] + 0x50
          and sym["objTimer"] == sym["logActive"] + 0x60)
    check("wmMode/wmStage/wmVX/wmVY sit where the bulk read assumes",
          sym["wmStage"] == sym["wmMode"] + 0x10
          and sym["wmVX"] == sym["wmMode"] + 0x50
          and sym["wmVY"] == sym["wmMode"] + 0x60)
    check("the dropper flight state is one contiguous block",
          sym["drPhase"] == sym["drPassLeft"] + 1
          and sym["drPinged"] == sym["drPassLeft"] + 6)


class Stepper:
    """One accepted sample per displayed frame, across the whole run.

    harness.step_n de-duplicates only within one call, so calling it with n=1
    in a loop accepts duplicated stops -- see the v2.1 report, where that cost
    a run. The frame is carried across steps here, and each sample is judged by
    its own frame counter, which sample() reads last.
    """
    def __init__(self, mon):
        self.mon, self.last = mon, None

    def step(self, tries=8):
        for _ in range(tries):
            self.mon.cmd("x")
            s = sample(self.mon)
            if s["frame"] != self.last:
                self.last = s["frame"]
                return s
        raise RuntimeError("the machine stopped advancing frames")


def poke_checked(mon, addr, val, tries=6):
    """Write a byte and prove it landed: `>` is the one monitor command with no
    reply to check, and a dropped write cost the v2 run an entire pass."""
    for _ in range(tries):
        poke(mon, addr, val)
        if rd1(mon, addr) == (val & 0xff):
            return
    raise RuntimeError(f"could not write ${addr:04x} = {val:02x}")


def kill(mon, slot):
    """The logical destruction event, exactly as src/collision.asm leaves it."""
    poke_checked(mon, sym["objTimer"] + slot, DEATH_TIME)
    poke_checked(mon, sym["objHP"] + slot, 0)


def request_sfx(mon, effect):
    """Call sfxRequest(A = effect) to completion, then resume the frame loop.

    The same synthetic-return trick harness.call uses; it passes X, and the
    effect id arrives in A, so the register is set here instead.
    """
    mon.cmd("> 01ff c0")
    mon.cmd("> 01fe fd")
    mon.cmd(f"r sp=fd, pc={sym['sfxRequest']:04x}, a={effect:02x}")
    bp = set_bp(mon, 0xc0fe)
    mon.cmd("x")
    mon.cmd(f"delete {bp}")
    mon.cmd(f"r pc={sym['mainLoop']:04x}")


def x_of(s, i):
    return s["logX"][i] | (s["logXHi"][i] << 8)


def sgn8(v):
    return (v - 256) if v > 127 else v


def droppers(s):
    return [i for i in range(MAX_OBJECTS)
            if s["active"][i] and s["type"][i] == TYPE_ENEMY
            and s["species"][i] == SPECIES_DROPPER]


def rings(s):
    return [i for i in range(MAX_OBJECTS)
            if s["active"][i] and s["type"][i] == TYPE_ENEMY
            and s["species"][i] == SPECIES_RING]


def pickups(s):
    return [i for i in range(MAX_OBJECTS)
            if s["active"][i] and s["type"][i] == TYPE_PICKUP]


def weave_table():
    """src/dropper.asm generates this with the assembler's own sin(); this is
    the same arithmetic, so a mismatch means the table is not what it says."""
    import math
    out = []
    for k in range(DROP_PHASES):
        v = round(DROP_AMPLITUDE * math.sin(2 * math.pi * k / DROP_PHASES))
        out.append(v)
    return out


WEAVE = weave_table()


def watch_flight(stepper, first, label):
    """Follow one Dropper from `first` to the frame it leaves the pool.

    Returns everything the checks below need, gathered in one pass.
    """
    slot = droppers(first)[0]
    r = {
        "entry_x": x_of(first, slot),
        "entry_dir": sgn8(first["wmVX"][slot]),
        "slot": slot,
        "ys": [], "xs": [], "passes": [first["passLeft"]],
        "reversals": [], "weave_ok": True, "vy_ok": True, "stage_ok": True,
        "stage0": first["wmStage"][slot],
        "exit_x": None, "exit_dir": None,
        "ping_frames": [], "voice2_idle": 0, "voice2_ping": 0, "samples": 0,
        "gone": False,
    }
    prev_dir = r["entry_dir"]
    prev_pinged = first["pinged"]
    for _ in range(FLIGHT_FRAMES):
        s = stepper.step()
        if slot not in droppers(s):
            r["gone"] = True
            r["end"] = s
            break
        r["samples"] += 1
        y, x = s["logY"][slot], x_of(s, slot)
        r["ys"].append(y)
        r["xs"].append(x)
        r["exit_x"], r["exit_dir"] = x, sgn8(s["wmVX"][slot])

        # the vertical is the table and nothing else
        if y != DROP_CENTRE_Y + WEAVE[s["phase"]]:
            r["weave_ok"] = False
        if s["wmVY"][slot] != 0:
            r["vy_ok"] = False
        if s["wmStage"][slot] != r["stage0"]:
            r["stage_ok"] = False        # a wave path would advance this

        if s["passLeft"] != r["passes"][-1]:
            r["passes"].append(s["passLeft"])
        d = sgn8(s["wmVX"][slot])
        if (d > 0) != (prev_dir > 0):
            r["reversals"].append((len(r["xs"]), prev_dir, d))
            prev_dir = d

        # the ping, and what voice 2 is doing between pings
        if s["pinged"] != prev_pinged:
            r["ping_frames"].append(s["frame"])
            prev_pinged = s["pinged"]
        if s["voice2"] == SFX_NONE:
            r["voice2_idle"] += 1
        elif s["voice2"] == SFX_PING:
            r["voice2_ping"] += 1
    print(f"  info {label}: slot {slot}, entered x={r['entry_x']} "
          f"dir={r['entry_dir']}, {r['samples']} frames, "
          f"passes {r['passes']}, {len(r['reversals'])} reversals, "
          f"exit x={r['exit_x']} dir={r['exit_dir']}")
    return r


def hunt_launch(stepper, label):
    """Step until a Dropper is LAUNCHED, not merely until one is on screen.

    The difference cost this file a run. The hunt used to stop at the first
    frame a Dropper existed, which on a machine that has already been warped
    for two seconds is almost always one already half way through its flight --
    so the entry X was mid-screen, the pass counter was down to its last, and
    no reversal was ever going to be seen. drLaunched changing is the only
    signal that says "this one is starting".

    src/main.asm runs objectUpdateAll BEFORE waveTick, so a Dropper launched on
    this frame has not moved yet: the sample returned is the object exactly as
    dropperLaunch left it.
    """
    was = rd1(stepper.mon, sym["drLaunched"])
    for _ in range(HUNT_FRAMES):
        s = stepper.step()
        if s["launched"] != was and droppers(s):
            return s
    check(f"a Dropper was launched during the run ({label})", False)
    return None


def main():
    print("=== dropper flight v1: three passes + sonar ping ===")
    v = None
    try:
        v = Vice(6665, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")
        check_layout()

        bp = set_bp(mon, sym["gameFrame"])
        stepper = Stepper(mon)

        # ==================================================================
        # PHASE 1 -- find a Dropper and watch its whole flight out
        # ==================================================================
        first = hunt_launch(stepper, "flight 1")
        check("an authored Dropper was launched during an ordinary run",
              first is not None)
        if first is None:
            mon.cmd("delete")
            return report(__name__)

        tokens_before = rd1(mon, sym["pkSpawned"])
        a = watch_flight(stepper, first, "flight 1")

        # ---- the entry was the authored one -------------------------------
        check("it entered from an authored side, at the authored X",
              a["entry_x"] in (DROP_ENTRY_LEFT, DROP_ENTRY_RIGHT),
              f"entry x={a['entry_x']}")
        entered_left = a["entry_x"] == DROP_ENTRY_LEFT
        check("...travelling INTO the playfield from that side",
              (a["entry_dir"] > 0) == entered_left,
              f"x={a['entry_x']} vx={a['entry_dir']}")

        # ---- the band, and the weave --------------------------------------
        lo, hi = min(a["ys"]), max(a["ys"])
        check("every frame of the flight is inside the authored Y band",
              lo >= DROP_CENTRE_Y - DROP_AMPLITUDE
              and hi <= DROP_CENTRE_Y + DROP_AMPLITUDE,
              f"logY {lo}..{hi}, band "
              f"{DROP_CENTRE_Y - DROP_AMPLITUDE}.."
              f"{DROP_CENTRE_Y + DROP_AMPLITUDE}")
        check("...and it is high in the aperture, not down in the player's "
              "airspace", hi <= DROP_CENTRE_Y + DROP_AMPLITUDE, f"lowest {hi}")
        check("it oscillates both above and below the centreline",
              lo < DROP_CENTRE_Y < hi, f"logY {lo}..{hi}")
        check("its logY is exactly centre + weave[phase] on every frame",
              a["weave_ok"])

        # ---- it is NOT flying a wave path ---------------------------------
        check("it carries no vertical velocity, so the edge rules read it "
              "truthfully", a["vy_ok"])
        check("its wave stage never advances: no movement program is running "
              "for it", a["stage_ok"])

        # ---- three passes, two reversals ----------------------------------
        check("the pass counter walks 3 -> 2 -> 1 -> 0 and stops",
              a["passes"] == [DROP_PASSES, 2, 1, 0], f"{a['passes']}")
        check("it reverses after the first two passes and not after the third",
              len(a["reversals"]) == DROP_PASSES - 1,
              f"{len(a['reversals'])} reversals at "
              f"{[r[0] for r in a['reversals']]}")
        check("each reversal genuinely flips the direction",
              all((r[1] > 0) != (r[2] > 0) for r in a["reversals"]))

        # ---- and it leaves by the other side ------------------------------
        check("it left the pool by itself: the ordinary despawn rule retired "
              "it", a["gone"])
        check("it escaped through the side OPPOSITE the one it entered",
              a["exit_dir"] is not None
              and (a["exit_dir"] > 0) == entered_left
              and (a["exit_x"] > DROP_X_RIGHT if entered_left
                   else a["exit_x"] < DROP_X_LEFT),
              f"entered {'left' if entered_left else 'right'}, last seen at "
              f"x={a['exit_x']} vx={a['exit_dir']}")
        check("an escape counted itself", a["end"]["escaped"] >= 1,
              f"drEscaped={a['end']['escaped']}")

        # ---- an escape is worth nothing -----------------------------------
        check("an escaped Dropper dropped no token",
              rd1(mon, sym["pkSpawned"]) == tokens_before
              and not pickups(a["end"]),
              f"pkSpawned {tokens_before} -> {rd1(mon, sym['pkSpawned'])}")
        check("...and released the one-Dropper claim on its way out",
              rd1(mon, sym["tkDropperLive"]) == 0)
        check("no encounter was started by an escape",
              rd1(mon, sym["tkActive"]) == 0)

        # ---- the ping stopped with it -------------------------------------
        pings = a["ping_frames"]
        gaps = [pings[k + 1] - pings[k] for k in range(len(pings) - 1)]
        check("it pinged repeatedly while it was alive",
              len(pings) >= PING_SPAN_WANTED, f"{len(pings)} pings")
        check("...at the authored cadence, every frame of it",
              gaps and set(gaps) == {DROP_PING_PERIOD},
              f"gaps between pings {sorted(set(gaps))}, wanted "
              f"{DROP_PING_PERIOD}")
        after = rd1(mon, sym["drPinged"])
        for _ in range(DROP_PING_PERIOD * 2):
            stepper.step()
        check("the ping stopped dead when the Dropper left: no trailing ping",
              rd1(mon, sym["drPinged"]) == after,
              f"drPinged {after} -> {rd1(mon, sym['drPinged'])}")

        # ---- voice 2 was not reserved between pings -----------------------
        busy_pct = 100.0 * a["voice2_ping"] / max(a["samples"], 1)
        check("voice 2 is NOT reserved between pings: the ping owns it only "
              "while it sounds",
              busy_pct <= 100.0 * (SFX_PING_FRAMES + 1) / DROP_PING_PERIOD,
              f"the ping held voice 2 on {a['voice2_ping']}/{a['samples']} "
              f"frames ({busy_pct:.1f}%)")
        check("...and voice 2 was genuinely idle for most of the flight",
              a["voice2_idle"] > a["samples"] // 2,
              f"idle on {a['voice2_idle']}/{a['samples']} frames")

        # ==================================================================
        # PHASE 2 -- the mirrored appearance, through the same routine
        # ==================================================================
        second = hunt_launch(stepper, "flight 2")
        check("a second authored Dropper was launched", second is not None)
        if second is None:
            mon.cmd("delete")
            return report(__name__)

        b_slot = droppers(second)[0]
        b_entry = x_of(second, b_slot)
        b_dir = sgn8(second["wmVX"][b_slot])
        entered_left_b = b_entry == DROP_ENTRY_LEFT
        print(f"  info flight 2: slot {b_slot}, entered x={b_entry} dir={b_dir}")
        check("the second Dropper entered from the OTHER authored side",
              b_entry in (DROP_ENTRY_LEFT, DROP_ENTRY_RIGHT)
              and entered_left_b != entered_left,
              f"first entered x={a['entry_x']}, second x={b_entry}")
        check("...through the same routine: same pass count, same centreline",
              second["passLeft"] == DROP_PASSES
              and second["logY"][b_slot] == DROP_CENTRE_Y,
              f"passLeft={second['passLeft']} "
              f"logY={second['logY'][b_slot]}")
        check("...travelling INTO the playfield from that side",
              (b_dir > 0) == entered_left_b, f"x={b_entry} vx={b_dir}")

        # ---- ordinary Rings are untouched by any of this ------------------
        ring_moved = False
        ring_seen = False
        prev = second
        for _ in range(120):
            s = stepper.step()
            for i in rings(s):
                ring_seen = True
                if i in rings(prev) and s["wmVY"][i] != 0:
                    ring_moved = True
            prev = s
        check("ordinary Rings still fly the movement interpreter, with real "
              "velocities", ring_seen and ring_moved)

        # ==================================================================
        # PHASE 3 -- voice 2 priority, provoked deterministically
        # ==================================================================
        # Wait for a ping to be sounding, then try to stomp it.
        refused_before = rd1(mon, sym["sfxRefused"])
        stomped = None
        for _ in range(DROP_PING_PERIOD * 3):
            s = stepper.step()
            if s["voice2"] == SFX_PING:
                request_sfx(mon, SFX_ESHOT)
                stomped = rd1(mon, sym["sfxChId"] + SFX_CH_KILL)
                break
        check("a routine voice-2 effect requested DURING the ping is refused",
              stomped == SFX_PING,
              f"voice 2 held {stomped} after an SFX_ESHOT request")
        check("...and the refusal is counted",
              rd1(mon, sym["sfxRefused"]) == refused_before + 1,
              f"sfxRefused {refused_before} -> "
              f"{rd1(mon, sym['sfxRefused'])}")

        # ...and a DESTRUCTION is not refused.
        took = None
        for _ in range(DROP_PING_PERIOD * 3):
            s = stepper.step()
            if s["voice2"] == SFX_PING:
                request_sfx(mon, SFX_KILL)
                took = rd1(mon, sym["sfxChId"] + SFX_CH_KILL)
                break
        check("a DESTRUCTION requested during the ping takes voice 2: the "
              "Dropper's own death is never masked", took == SFX_KILL,
              f"voice 2 held {took} after an SFX_KILL request")

        # ...and in the silence between pings, voice 2 is ordinary.
        idle_took = None
        for _ in range(DROP_PING_PERIOD * 3):
            s = stepper.step()
            if s["voice2"] == SFX_NONE:
                request_sfx(mon, SFX_ESHOT)
                idle_took = rd1(mon, sym["sfxChId"] + SFX_CH_KILL)
                break
        check("between pings voice 2 behaves exactly as it always did",
              idle_took == SFX_ESHOT,
              f"voice 2 held {idle_took} after an SFX_ESHOT request in the "
              f"silence")

        # ==================================================================
        # PHASE 4 -- destroying it still drops exactly one P, where it died
        # ==================================================================
        target, before = None, None
        for _ in range(FLIGHT_FRAMES):
            s = stepper.step()
            d = droppers(s)
            if d and s["hp"][d[0]] > 0:
                target, before = d[0], s
                break
        check("the Dropper is still there to be killed", target is not None)
        if target is None:
            mon.cmd("delete")
            return report(__name__)

        death_x, death_y = x_of(before, target), before["logY"][target]
        spawned_before = rd1(mon, sym["pkSpawned"])
        print(f"  info killing the Dropper in slot {target} at "
              f"({death_x},{death_y})")
        kill(mon, target)

        started = None
        for _ in range(DEATH_TIME + 30):
            s = stepper.step()
            if rd1(mon, sym["tkActive"]):
                started = s
                break
        check("destroying it started the encounter", started is not None)
        if started is not None:
            pk = pickups(started)
            check("exactly one token exists", len(pk) == 1, f"slots {pk}")
            check("exactly one token was spawned by that death",
                  rd1(mon, sym["pkSpawned"]) == (spawned_before + 1) & 0xff)
            if pk:
                check("the P appeared exactly where the Dropper died",
                      x_of(started, pk[0]) == death_x
                      and started["logY"][pk[0]] == death_y,
                      f"P at ({x_of(started, pk[0])},"
                      f"{started['logY'][pk[0]]}) vs death "
                      f"({death_x},{death_y})")
            check("the death released the one-Dropper claim",
                  rd1(mon, sym["tkDropperLive"]) == 0)

        # the ping must not outlive the Dropper
        after = rd1(mon, sym["drPinged"])
        for _ in range(DROP_PING_PERIOD * 2):
            stepper.step()
        check("a destroyed Dropper stops pinging immediately",
              rd1(mon, sym["drPinged"]) == after,
              f"drPinged {after} -> {rd1(mon, sym['drPinged'])}")

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        # ---- the engine is unharmed ---------------------------------------
        for name in ("gameOverrun", "schedBuildDefer", "scrollLate", "edgeLate",
                     "objDoubleFree", "objAllocFail", "wvDropped"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero over the whole run", got == 0, str(got))
        print(f"  info publishSkip {rd1(mon, sym['publishSkip'])} "
              f"(measured, not asserted)")
        print(f"  info drLaunched {rd1(mon, sym['drLaunched'])} "
              f"drEscaped {rd1(mon, sym['drEscaped'])} "
              f"drPinged {rd1(mon, sym['drPinged'])} "
              f"sfxRefused {rd1(mon, sym['sfxRefused'])}")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
