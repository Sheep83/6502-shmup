#!/usr/bin/env python3
"""A DROPPER TRIGGER IS ONE DROPPER, on the machine.

    A DROPPER TRIGGER SPAWNS EXACTLY ONE OBJECT. It is the Dropper. It flies
    either the hard-coded three-pass trajectory in src/dropper.asm
    (TRIG_DROP_LEGACY, and what every level authored before that column existed
    means) or a MOVEMENT PROGRAM the trigger named for it, on the ordinary
    movement engine.

    AN ORDINARY TRIGGER SPAWNS AN ORDINARY WAVE. A Dropper with company is two
    independent Triggers a row apart, not one composite encounter.

WHAT THIS FILE REPLACED. There used to be a second file asserting a Dropper
Trigger was a composite: member 0 the Dropper, members 1..N-1 substituted with
lvlPlainRow to become "escorts", the interlock governing member 0 alone, and
fire-mask bit 0 carrying a special inert meaning. That encounter is gone, and so
is that file -- everything in it that was about the Dropper rather than about the
composite is here.

THE THREE CLAIMS THAT ARE EASY TO GET WRONG, and which this file exists for:

    * ONE OBJECT, WHATEVER THE DEFINITION SAYS. src/waves.asm arms a Dropper
      instance with wvLeft = 1 however many members the referenced definition
      nominally sends, because that definition is the Dropper's PLACEMENT -- a
      start position and a launch heading -- and not a formation.
    * NOTHING ELSE IS MANUFACTURED. No lvlPlainRow escort, and when the one-live
      interlock refuses a Dropper, no ordinary enemy in its place either: the
      moment simply produces nothing.
    * AN AUTHORED DROPPER IS NOT ON THE LEGACY TRAJECTORY. Not forced to a screen
      edge, not pinned to DROP_CENTRE_Y, not moved by dropperFly, and starting
      from its own authored placement.

THE DISCRIMINATOR IS wmStage AT ACTIVATION. src/waves.asm points wmStage at the
Dropper's own program BEFORE the single wmEnterStage call, while the legacy path
leaves wmStage on the definition's program -- dropperLaunch overrides position
and velocity and never touches the cursor. So the offset says which of the two
happened, at the instant the object exists.

EVERY COMPOSITION IS SYNTHETIC. These cases need exact placements, exact
velocities, exact headings, two speeds over one path and a deliberately
multi-member definition behind a Dropper; none of that is the campaign's
business. tests/synth.py installs them into the spare room the package reserves,
in RAM only -- no authored level is read for its content and none is written.

One VICE launch per section, each short, exact owned PIDs only.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools" / "level_editor"))
from harness import (PRG, SYM, symbols, Vice, rd1, poke, set_bp,   # noqa: E402
                     step_n, check, report, LAUNCHED_PIDS)
import campaign_data as CD                                          # noqa: E402
import synth                                                        # noqa: E402
import movement_sim as ms                                           # noqa: E402

sym = symbols(SYM)

PORT = 6752
MAX_OBJECTS, WAVE_SLOTS, TYPE_ENEMY = 16, 2, 1
REG_X = re.compile(r"^\.;[0-9a-f]{4}\s+[0-9a-f]{2}\s+([0-9a-f]{2})", re.M)

# ---- the engine's own vocabulary, read rather than retyped -----------------
TRIG_DROP_LEGACY = synth.TRIG_DROP_LEGACY
DROP_MODE_LEGACY, DROP_MODE_PROGRAM = 0, 1      # src/dropper.asm
DROP_SIDE_LEFT, DROP_SIDE_RIGHT = 0, 1
DROP_ENTRY_LEFT = ms.DROP_ENTRY_LEFT
DROP_ENTRY_RIGHT = ms.DROP_ENTRY_RIGHT
DROP_VX = ms.DROP_VX
DROP_CENTRE_Y = ms.DROP_CENTRE_Y
ENEMY_FIRE_NONE = 0                             # src/enemy.asm
DEATH_TIME = 12                                 # src/collision.asm
S1X = CD.C.TRIG_SPEED_1X
S15X, S2X = 6, 8

# ---- the synthetic specimen ------------------------------------------------
# TWO DISTINCT STRAIGHT VELOCITIES, so "which program is this object on?" is
# answerable from the velocity as well as from the stage cursor.
ESC_VX, ESC_VY = 6, 0           # the ordinary wave's leg
DRP_VX, DRP_VY = -5, 4          # the Dropper's own leg: a different direction
SYN_ROW = 8                     # boot="exact" arrives below coarse row 4
SYN_START_X, SYN_START_Y = 120, 60
SYN_X_STEP = 28
SYN_INTERVAL = 12
SYN_COLOUR = 5          # a fixed colour no level need own
SYN_ORD_ROW = SYN_ROW + 1   # the next timeline row: adjacent, not simultaneous


def s8(b):
    return b - 256 if b > 127 else b


def scale(v, n):
    """src/movement.asm wmScaleOne: magnitude, shift, sign back on."""
    mag = abs(v) * n >> 2
    return -mag if v < 0 else mag


def watch(mon, n, *, clear_flag_after=None, want=None):
    """Every enemy activation, with everything decided at spawn.

    wvIndex is read PRE-INCREMENT and is therefore the member index: waveTick
    bumps it only after waveSpawnMember returns (src/waves.asm, label `!sent:`).

    `want` STOPS AS SOON AS THE WAVE HAS FINISHED SENDING, and it is not an
    optimisation. Each `x` runs the machine on to the NEXT objectActivate, and
    once the last member is out the next one may be hundreds of frames away --
    or may never come at all. Over-running like that is how a one-member wave's
    Dropper was read after it had already flown off the bottom of the aperture:
    the sample said tkDropperLive = 0 and the flag was perfectly correct. Ask
    for exactly the members the definition sends.
    """
    out = []
    bp = set_bp(mon, sym["objectActivate"])
    for _ in range(n):
        if want is not None and len(out) >= want:
            break
        mon.cmd("x")
        m = REG_X.search(mon.cmd("registers"))
        if not m:
            continue
        slot = int(m.group(1), 16)
        if slot >= MAX_OBJECTS or rd1(mon, sym["objType"] + slot) != TYPE_ENEMY:
            continue
        inst = rd1(mon, sym["wvInst"])
        if inst >= WAVE_SLOTS:
            continue
        out.append({
            "slot": slot,
            "member": rd1(mon, sym["wvIndex"] + inst),
            "species": rd1(mon, sym["enySpecies"] + slot),
            "fire": rd1(mon, sym["enyFire"] + slot),
            "speed": rd1(mon, sym["wmSpeed"] + slot),
            "stage": rd1(mon, sym["wmStage"] + slot),
            "x": rd1(mon, sym["logX"] + slot)
                 | (rd1(mon, sym["logXHi"] + slot) << 8),
            "y": rd1(mon, sym["logY"] + slot),
            "vx": s8(rd1(mon, sym["wmVX"] + slot)),
            "vy": s8(rd1(mon, sym["wmVY"] + slot)),
            "colour": rd1(mon, sym["logCol"] + slot),
            "mode": rd1(mon, sym["drMode"]),
            "live": rd1(mon, sym["tkDropperLive"]),
        })
        if clear_flag_after is not None and out[-1]["member"] == clear_flag_after:
            # EXACTLY WHAT enemyDespawn DOES when the Dropper is shot or leaves.
            poke(mon, sym["tkDropperLive"], 0)
            out[-1]["flag_cleared"] = True
    mon.cmd(f"delete {bp}")
    return out


def install(mon, *, count, authored, side=DROP_SIDE_LEFT, speed=S1X,
            heading=0, mask=0, drop_records=None, esc_records=None):
    """One synthetic Dropper trigger. Returns (escort offset, dropper offset).

    `authored` chooses the tenth column: False installs TRIG_DROP_LEGACY and
    True installs the Dropper program's own pool offset. Both cases install BOTH
    programs, so the two runs differ in exactly one authored byte.
    """
    pkg = synth.Package(mon, sym)
    esc = (pkg.install_program(esc_records) if esc_records
           else pkg.straight_then_exit(ESC_VX, ESC_VY))
    drp = (pkg.install_program(drop_records) if drop_records
           else pkg.straight_then_exit(DRP_VX, DRP_VY))
    d = pkg.install_definition(count=count, interval=SYN_INTERVAL,
                               start_x=SYN_START_X, start_y=SYN_START_Y,
                               x_step=SYN_X_STEP, y_step=0, heading=heading,
                               program=esc)
    pkg.only_trigger(row=SYN_ROW, definition=d,
                     species=rd1(mon, sym["lvlDropRow"]),
                     fire=mask, side=side, colour=SYN_COLOUR, fire_mode=0,
                     speed=speed,
                     drop_prog=drp if authored else TRIG_DROP_LEGACY)
    return esc, drp


def install_pair(mon, *, count=4, speed=S1X):
    """A Dropper Trigger on row N and an ORDINARY wave Trigger on row N+1.

    TWO INDEPENDENT TRIGGERS, WHICH IS THE WHOLE AUTHORING MODEL NOW. They share
    one definition deliberately: the Dropper reads it as a placement (start
    position and heading) and the ordinary trigger reads it as a formation of
    `count` members, and neither reading may leak into the other. That is the
    strongest form of the test -- if the count could reach the Dropper, this is
    where it would.

    ADJACENT ROWS, NOT THE SAME ROW. At 1 px/frame the difference is
    imperceptible as encounter timing, and the existing forward-only cursor
    schedules them with no simultaneity machinery of any kind.
    """
    pkg = synth.Package(mon, sym)
    esc = pkg.straight_then_exit(ESC_VX, ESC_VY)
    drp = pkg.straight_then_exit(DRP_VX, DRP_VY)
    d = pkg.install_definition(count=count, interval=SYN_INTERVAL,
                               start_x=SYN_START_X, start_y=SYN_START_Y,
                               x_step=SYN_X_STEP, y_step=0, heading=0,
                               program=esc)
    pkg.write_trigger(0, row=SYN_ROW, definition=d,
                      species=rd1(mon, sym["lvlDropRow"]),
                      fire=0, side=DROP_SIDE_LEFT, colour=SYN_COLOUR,
                      fire_mode=0, speed=speed, drop_prog=drp)
    pkg.write_trigger(1, row=SYN_ORD_ROW, definition=d,
                      species=synth.SLOT_ROW[0],
                      fire=0, side=DROP_SIDE_LEFT, colour=SYN_COLOUR,
                      fire_mode=0, speed=speed, drop_prog=TRIG_DROP_LEGACY)
    pkg.set_trigger_count(2)
    pkg.open_the_approach()
    pkg.rewind_cursor()
    return esc, drp


def dump(rows, dr, pr, esc, drp, label):
    print(f"  info {label}   escort prog @{esc}, dropper prog @{drp}")
    # drMode IS MODULE STATE, not this object's: it describes whichever Dropper
    # is alive. Printed for context, never asserted per ordinary row.
    print("  info   mbr species          stg fire spd   x   y  vx vy drMd live")
    for r in rows:
        kind = ("DROPPER" if r["species"] == dr
                else "ordinary" if r["species"] == pr else f"row{r['species']}")
        note = "  <- flag cleared" if r.get("flag_cleared") else ""
        print(f"  info   {r['member']:>3} {r['species']:>3} {kind:<9} "
              f"{r['stage']:>3} {r['fire']:>4} {r['speed']:>3} {r['x']:>3} "
              f"{r['y']:>3} {r['vx']:>3} {r['vy']:>2} {r['mode']:>4} "
              f"{r['live']:>4}{note}")


def session(fn, samples, *, want=None, **kw):
    """One VICE, one synthetic Dropper wave, the activations it produced."""
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        dr = rd1(mon, sym["lvlDropRow"])
        pr = rd1(mon, sym["lvlPlainRow"])
        esc, drp = fn(mon)
        rows = watch(mon, samples, want=want, **kw)
        return rows, dr, pr, esc, drp, mon
    finally:
        if v:
            v.close()


def member0(rows):
    """The first member sent, which for a Dropper Trigger is the only one.

    KEPT AS A NAME RATHER THAN AS A CONCEPT. There is no member indexing inside a
    Dropper Trigger any more -- it sends one object -- so this is just "the one
    that came out", and for an ordinary wave it is the head of the formation.
    """
    for r in rows:
        if r["member"] == 0:
            return r
    return None


def poke_checked(mon, addr, val, tries=6):
    """Write and READ BACK. A bare `>` write is the one monitor command with no
    reply to check, and a dropped one here is silent -- see the note on kill()."""
    for _ in range(tries):
        poke(mon, addr, val & 0xFF)
        if rd1(mon, addr) == (val & 0xFF):
            return
    raise RuntimeError(f"could not write ${addr:04x} = {val & 0xFF:02x}")


def kill(mon, slot):
    """Stage the LOGICAL DESTRUCTION EVENT, exactly as src/collision.asm's
    damageEnemy leaves it: THE DEATH TIMER ARMED FIRST, then the health.

    THE ORDER IS THE WHOLE OF IT, and getting it wrong is silent. objHP == 0
    with objTimer == 0 is a state src/objects.asm documents as impossible, and
    src/enemy.asm's `dec objTimer,x` turns it into a 256-FRAME death animation --
    so the Dropper is still dying long after a couple of hundred frames, the
    interlock is still held, and the token has not been dropped. Every
    measurement afterwards then describes a machine that has not yet done the
    thing being measured. tests/test_token_encounter.py paid for this lesson
    once already and its kill() carries the same comment.
    """
    poke_checked(mon, sym["objTimer"] + slot, DEATH_TIME)
    poke_checked(mon, sym["objHP"] + slot, 0)


def advance(mon, frames):
    """Let the game run `frames` real frames, verified by the frame counter."""
    bp = set_bp(mon, sym["gameFrame"])
    step_n(mon, sym["frameCounter"], frames, lambda: None)
    mon.cmd(f"delete {bp}")


def fly(mon, slot, frames):
    """(x, y) each frame for one object, for as long as it stays active.

    THROUGH step_n AND ITS FRAME COUNTER, not a bare `x` loop: `mon.cmd("x")`
    returns on a prompt echo rather than on the actual stop, so a dropped reply
    can hand back a frame that never ran. harness.step_n verifies every step
    against frameCounter and retries a stall instead of recording it -- see its
    own comment. A sample after the object is freed is dropped rather than
    recorded, so the path ends on the last frame it was alive.
    """
    bp = set_bp(mon, sym["gameFrame"])

    def one():
        if not rd1(mon, sym["logActive"] + slot):
            return None
        return (rd1(mon, sym["logX"] + slot)
                | (rd1(mon, sym["logXHi"] + slot) << 8),
                rd1(mon, sym["logY"] + slot))

    got = step_n(mon, sym["frameCounter"], frames, one)
    mon.cmd(f"delete {bp}")
    out = []
    for s in got:
        if s is None:
            break
        out.append(s)
    return out


# ===========================================================================
# 1. ONE OBJECT, WHATEVER THE DEFINITION SAYS -- LEGACY
# ===========================================================================
# THE HEART OF THE SIMPLIFICATION, AND THE FIXTURE IS CHOSEN TO PROVE IT. The
# definition behind this Dropper sends FOUR members. Under the composite model
# that produced one Dropper and three lvlPlainRow escorts; it must now produce
# one object and nothing else, because a Dropper Trigger is one Dropper and the
# definition is only its placement.
print("\n=== 1. legacy: ONE Dropper from a four-member definition ===")
rows, dr, pr, esc, drp, _m = session(
    lambda m: install(m, count=4, authored=False, side=DROP_SIDE_LEFT), 10,
    want=1)
dump(rows, dr, pr, esc, drp, "definition sends 4, legacy, LEFT")
check("exactly ONE object is spawned, from a definition that sends four",
      len(rows) == 1, f"{len(rows)} activation(s)")
m0 = rows[0] if rows else None
check("...and it is the Dropper", m0 is not None and m0["species"] == dr,
      "" if m0 is None else f"species {m0['species']} vs dropRow {dr}")
check("...no lvlPlainRow escort was manufactured",
      not [r for r in rows if r["species"] == pr],
      f"plainRow {pr}; species seen {sorted({r['species'] for r in rows})}")
check("...and src/enemy.asm is told to use dropperFly",
      m0 is not None and m0["mode"] == DROP_MODE_LEGACY,
      "" if m0 is None else f"drMode {m0['mode']}")
check("...entering from the LEFT screen edge, as the legacy flight always has",
      m0 is not None and m0["x"] == DROP_ENTRY_LEFT != SYN_START_X,
      "" if m0 is None else f"x {m0['x']} (entry {DROP_ENTRY_LEFT})")
check("...on the weave centreline",
      m0 is not None and m0["y"] == DROP_CENTRE_Y,
      "" if m0 is None else f"y {m0['y']}")
check("...at the legacy crossing velocity",
      m0 is not None and (m0["vx"], m0["vy"]) == (DROP_VX, 0),
      "" if m0 is None else f"({m0['vx']}, {m0['vy']})")
check("...and it took the trigger's authored colour",
      m0 is not None and m0["colour"] == SYN_COLOUR,
      "" if m0 is None else f"logCol {m0['colour']} wanted {SYN_COLOUR}")
check("...and does not shoot", m0 is not None and m0["fire"] == ENEMY_FIRE_NONE,
      "" if m0 is None else f"enyFire {m0['fire']}")

# ===========================================================================
# 2. ONE OBJECT, WHATEVER THE DEFINITION SAYS -- AUTHORED
# ===========================================================================
print("\n=== 2. authored: ONE Dropper, on its own program and placement ===")
rows, dr, pr, esc, drp, _m = session(
    lambda m: install(m, count=4, authored=True, side=DROP_SIDE_LEFT), 10,
    want=1)
dump(rows, dr, pr, esc, drp, "definition sends 4, authored")
check("exactly ONE object is spawned", len(rows) == 1,
      f"{len(rows)} activation(s)")
m0 = rows[0] if rows else None
check("...and it is still the Dropper: the identity is not what changed",
      m0 is not None and m0["species"] == dr)
check("...no lvlPlainRow escort was manufactured",
      not [r for r in rows if r["species"] == pr])
check("...and src/enemy.asm is told to use wmTick",
      m0 is not None and m0["mode"] == DROP_MODE_PROGRAM,
      "" if m0 is None else f"drMode {m0['mode']}")
check("...armed from the DROPPER'S program, not the definition's",
      m0 is not None and m0["stage"] == drp != esc,
      "" if m0 is None else f"stage {m0['stage']}: dropper @{drp}, def @{esc}")
check("...at that program's opening velocity",
      m0 is not None and (m0["vx"], m0["vy"]) == (DRP_VX, DRP_VY),
      "" if m0 is None else f"({m0['vx']}, {m0['vy']}) wanted "
                            f"({DRP_VX}, {DRP_VY})")
# ITS OWN PLACEMENT: the definition's start position with no per-member step
# applied, because there is no second member for a step to apply to.
check("...starting at its OWN authored placement, not a screen edge",
      m0 is not None and (m0["x"], m0["y"]) == (SYN_START_X, SYN_START_Y),
      "" if m0 is None else f"({m0['x']}, {m0['y']}) wanted "
                            f"({SYN_START_X}, {SYN_START_Y}); legacy edges are "
                            f"{DROP_ENTRY_LEFT}/{DROP_ENTRY_RIGHT} at "
                            f"{DROP_CENTRE_Y}")
check("...and it is not the legacy trajectory in any respect",
      m0 is not None and m0["x"] not in (DROP_ENTRY_LEFT, DROP_ENTRY_RIGHT)
      and m0["y"] != DROP_CENTRE_Y and abs(m0["vx"]) != DROP_VX)
check("the Dropper still does not shoot: an authored path does not promote it "
      "to a normal firing enemy",
      m0 is not None and m0["fire"] == ENEMY_FIRE_NONE,
      "" if m0 is None else f"enyFire {m0['fire']}")

# ===========================================================================
# 3. IT ACTUALLY FLIES THE PROGRAM, FRAME BY FRAME
# ===========================================================================
# ARMED IS NOT FLOWN. Section 2 proves the object was set up from the right
# program; this proves src/enemy.asm then MOVES it with wmTick rather than with
# dropperFly -- a different thing, and the one the dispatch decides.
print("\n=== 3. wmTick moves it, not dropperFly ===")
v = None
try:
    v = Vice(PORT, PRG, boot="exact")
    mon = v.mon
    dr = rd1(mon, sym["lvlDropRow"])
    esc, drp = install(mon, count=1, authored=True)
    rows = watch(mon, 4, want=1)
    m0 = member0(rows)
    path = fly(mon, m0["slot"], 24) if m0 else []
    print(f"  info first frames: {path[:6]}")
    # Y IS EXACT AND IS THE STRONGER CLAIM. DRP_VY is 4 quarter pixels, which is
    # exactly one whole pixel a frame with no sub-pixel remainder ever -- a
    # property the legacy weave cannot satisfy at all, since dropperFly writes
    # logY outright from a table about a fixed centreline.
    k = len(path) - 1
    check("it descends exactly one pixel a frame, as a 4-quarter-pixel leg must",
          k >= 6 and all(y == path[0][1] + i for i, (_x, y) in enumerate(path)),
          f"ys {[y for _x, y in path[:8]]}")
    # X IS CHECKED AS A RATE, NOT AS A COORDINATE. DRP_VX is 5 quarter pixels --
    # a pixel and a quarter a frame -- so whole-pixel steps alternate 1,1,1,2 as
    # wmAccX carries, and WHICH frame carries depends on the sub-pixel remainder
    # at the instant sampling began. The bit-level agreement is established in
    # tools/level_editor/test_movement_sim_engine.py, not here.
    drift = path[0][0] - path[k][0]
    exact = abs(DRP_VX) * k / 4
    check("...and drifts left at the authored rate, to within the sub-pixel "
          "accumulator",
          k >= 6 and abs(drift - exact) <= 1,
          f"{drift} px over {k} frames, wanted {exact:.2f}")
    check("...which is DOWN-LEFT, where the legacy flight only ever goes "
          "sideways at a fixed height",
          k >= 7 and path[7][0] < path[0][0] and path[7][1] > path[0][1],
          f"{path[0]} -> {path[7] if k >= 7 else None}")
    # THE PING SURVIVES, because finding the Dropper is the fight and the cue
    # that makes it possible belongs to the ENEMY, not to the trajectory.
    advance(mon, 120)
    check("the sonar ping still runs under an authored path",
          rd1(mon, sym["drPinged"]) > 0, f"drPinged {rd1(mon, sym['drPinged'])}")
    check("...and the authored launch is counted as one",
          rd1(mon, sym["drProgrammed"]) > 0
          and rd1(mon, sym["drLaunched"]) > 0,
          f"drProgrammed {rd1(mon, sym['drProgrammed'])} of drLaunched "
          f"{rd1(mon, sym['drLaunched'])}")
finally:
    if v:
        v.close()

# ===========================================================================
# 4. A COUNT-1 DEFINITION GIVES THE SAME ANSWER
# ===========================================================================
# THE TIDY CASE, which is what an author writing a Dropper fresh would produce:
# a definition whose count is already one. It must be indistinguishable from the
# migrated four-member case above, because the count is not read either way.
print("\n=== 4. a count-1 placement: the same one Dropper ===")
rows, dr, pr, esc, drp, _m = session(
    lambda m: install(m, count=1, authored=True), 8, want=1)
dump(rows, dr, pr, esc, drp, "definition sends 1, authored")
check("exactly one object is sent", len(rows) == 1, f"{len(rows)} activations")
check("...it is the Dropper on its own program",
      rows and rows[0]["species"] == dr and rows[0]["stage"] == drp
      and rows[0]["mode"] == DROP_MODE_PROGRAM)
check("...at the same placement as the four-member definition gave",
      rows and (rows[0]["x"], rows[0]["y"]) == (SYN_START_X, SYN_START_Y),
      "" if not rows else f"({rows[0]['x']}, {rows[0]['y']})")

# ===========================================================================
# 5. ALREADY LIVE: NOTHING IS SPAWNED AT ALL
# ===========================================================================
# THE BEHAVIOUR THAT CHANGED, AND THE REASON IT CHANGED. Under the composite
# model a refused Dropper was SUBSTITUTED with the level's ordinary enemy,
# because the wave around it had an authored count and shape that losing a member
# would have rewritten. There is no wave around it now, so a refusal creates
# NOTHING: the authored encounter was "a Dropper here", and if one is already
# flying then this moment has nothing to say. Manufacturing an unrelated ordinary
# enemy would be inventing content the level never asked for.
print("\n=== 5. already live: no second Dropper, and no stand-in either ===")
v = None
try:
    v = Vice(PORT, PRG, boot="exact")
    mon = v.mon
    dr = rd1(mon, sym["lvlDropRow"])
    pr = rd1(mon, sym["lvlPlainRow"])
    esc, drp = install(mon, count=4, authored=True)
    poke(mon, sym["tkDropperLive"], 1)          # one is already out there
    before = rd1(mon, sym["wvSpawned"])
    refused_before = rd1(mon, sym["wvDropRefused"])
    advance(mon, 400)                            # well past the trigger's row
    spawned = rd1(mon, sym["wvSpawned"]) - before
    live = [i for i in range(MAX_OBJECTS)
            if rd1(mon, sym["logActive"] + i)
            and rd1(mon, sym["objType"] + i) == TYPE_ENEMY]
    species = sorted({rd1(mon, sym["enySpecies"] + i) for i in live})
    print(f"  info wvSpawned +{spawned}, live enemies {len(live)}, "
          f"species {species}, wvDropRefused "
          f"{rd1(mon, sym['wvDropRefused'])}")
    check("the refused Dropper created NOTHING", spawned == 0,
          f"wvSpawned advanced by {spawned}")
    check("...not one enemy is alive from it", not live, f"{len(live)} alive")
    check("...and specifically no lvlPlainRow stand-in",
          pr not in species, f"plainRow {pr}; species {species}")
    check("...and the refusal was counted rather than silent",
          rd1(mon, sym["wvDropRefused"]) > refused_before,
          f"wvDropRefused {refused_before} -> "
          f"{rd1(mon, sym['wvDropRefused'])}")
    check("...the instance retired instead of retrying for ever",
          rd1(mon, sym["wvActive"]) == 0 and rd1(mon, sym["wvActive"] + 1) == 0,
          f"wvActive {[rd1(mon, sym['wvActive'] + i) for i in range(WAVE_SLOTS)]}")
    check("gameOverrun is zero across the refusal",
          rd1(mon, sym["gameOverrun"]) == 0,
          f"gameOverrun {rd1(mon, sym['gameOverrun'])}")
finally:
    if v:
        v.close()

# ===========================================================================
# 5b. AN ORDINARY TRIGGER A ROW AWAY IS COMPLETELY INDEPENDENT
# ===========================================================================
# THIS IS HOW "A DROPPER WITH ESCORTS" IS AUTHORED NOW, and the proof that it
# needs no engine concept: two Triggers on adjacent rows, through the existing
# scheduler, with no pairing field and no simultaneous-trigger machinery. The
# Dropper sends one object; the ordinary trigger sends its whole formation.
print("\n=== 5b. a Dropper and an ordinary wave on adjacent rows ===")
rows, dr, pr, esc, drp, _m = session(
    lambda m: install_pair(m, count=4), 12, want=5)
dump(rows, dr, pr, esc, drp, "row N Dropper + row N+1 ordinary wave of 4")
drops = [r for r in rows if r["species"] == dr]
ords = [r for r in rows if r["species"] == pr]
check("the Dropper trigger sent exactly one Dropper", len(drops) == 1,
      f"{len(drops)} Dropper(s)")
check("...and the ordinary trigger sent its FULL authored wave",
      len(ords) == 4, f"{len(ords)} ordinary enemies of 4")
check("...both activated through the ordinary scheduler, a row apart",
      len(rows) == 5, f"{len(rows)} activations")
check("...the ordinary wave keeps its own formation offsets",
      [r["x"] for r in ords]
      == [SYN_START_X + SYN_X_STEP * i for i in range(4)],
      str([r["x"] for r in ords]))
check("...on its own program, which is not the Dropper's",
      all(r["stage"] == esc for r in ords) and drops[0]["stage"] == drp,
      f"ordinary @{sorted({r['stage'] for r in ords})}, Dropper @"
      f"{drops[0]['stage']}")
# THE SPECIES IS THE PER-OBJECT FACT, and it is the one to assert. drMode is
# MODULE state describing whichever Dropper is currently alive -- src/dropper.asm
# keeps it that way deliberately, because the interlock guarantees there is at
# most one -- so the value sampled beside an ordinary member is the DROPPER'S,
# not that member's. Asserting it per ordinary enemy would be asserting nothing.
check("...and not one ordinary member carries the Dropper identity",
      all(r["species"] != dr for r in ords),
      f"species {sorted({r['species'] for r in ords})} vs dropRow {dr}")

# ===========================================================================
# 6. THE TRIGGER'S SPEED SCALES AN AUTHORED DROPPER
# ===========================================================================
# THE TRIGGER'S SPEED REACHES THE DROPPER through the same instruction it
# reaches every other enemy by -- src/waves.asm writes wmSpeed before the single
# wmEnterStage call, so the opening leg is already scaled. A LEGACY Dropper is
# unaffected, because dropperFly calls wmApplyVelocity and never wmApplySpeed;
# that is checked in section 8b.
#
# THE INDEPENDENT ORDINARY WAVE IS SCALED BY ITS OWN TRIGGER, which is proved
# here at the same time: the pair fixture gives both triggers the same speed and
# they share one definition, so the Dropper's leg and the wave's leg must each
# scale from their OWN authored velocity.
print("\n=== 6. trigger speed reaches an authored Dropper ===")
for speed in (S1X, S15X, S2X):
    rows, dr, pr, esc, drp, _m = session(
        lambda m, sp=speed: install_pair(m, count=3, speed=sp), 10, want=4)
    drops = [r for r in rows if r["species"] == dr]
    ords = [r for r in rows if r["species"] == pr]
    want_d = (scale(DRP_VX, speed), scale(DRP_VY, speed))
    want_e = (scale(ESC_VX, speed), scale(ESC_VY, speed))
    label = f"{speed}/4"
    check(f"at {label} the authored Dropper's leg is scaled",
          len(drops) == 1 and (drops[0]["vx"], drops[0]["vy"]) == want_d,
          f"{[(r['vx'], r['vy']) for r in drops]} wanted {want_d}")
    check(f"...and wmSpeed is the trigger's own at {label}",
          len(drops) == 1 and drops[0]["speed"] == speed)
    check(f"...and the independent ordinary wave is scaled at {label} too",
          len(ords) == 3 and all((r["vx"], r["vy"]) == want_e for r in ords),
          f"{sorted({(r['vx'], r['vy']) for r in ords})} wanted {want_e}")

# ===========================================================================
# 7. AN ARC WIDENS AT SPEED, AND THAT IS THE INTENDED SEMANTICS
# ===========================================================================
# LINEAR VELOCITY SCALES; ANGULAR PROGRESSION DOES NOT. An arc advances one
# heading step every `frames_per_step` frames whatever the speed, while each
# frame's travel is multiplied -- so a faster loop is a WIDER loop. That is the
# engine's documented behaviour for every wave and is deliberately NOT corrected
# for an authored Dropper: the radius is a consequence the author can see in the
# preview and tune, not a bug to compensate.
print("\n=== 7. a faster authored loop is a WIDER loop ===")
ARC_STEPS, ARC_FPS = 48, 3
ARC_PROG = [[synth.WM_ARC, ARC_STEPS, ARC_FPS, synth.WM_HEAD_CONT],
            [synth.WM_EXIT, 0, 0, 0]]
ARC_FRAMES = ARC_STEPS * ARC_FPS // 2           # half a turn, at either speed
paths = {}
for speed in (S1X, S2X):
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        esc, drp = install(mon, count=1, authored=True, speed=speed,
                           heading=0, drop_records=ARC_PROG)
        rows = watch(mon, 4, want=1)
        m0 = member0(rows)
        paths[speed] = fly(mon, m0["slot"], ARC_FRAMES) if m0 else []
        print(f"  info {speed}/4: {len(paths[speed])} frames, "
              f"first {paths[speed][:2]}")
    finally:
        if v:
            v.close()

# OVER THE FRAMES BOTH RUNS SURVIVED, because a faster path also reaches a
# despawn edge sooner: comparing a 72-frame flight against a 40-frame one would
# measure how long each lived, not how wide each turned. The common prefix is
# the same number of frames of the same arc at two speeds, which is exactly the
# comparison the claim is about.
n = min(len(paths[S1X]), len(paths[S2X]))
check("both speeds produced a comparable stretch of flight", n >= 8,
      f"1x {len(paths[S1X])} frames, 2x {len(paths[S2X])}, comparing {n}")


def span(path):
    return (max(x for x, _y in path) - min(x for x, _y in path),
            max(y for _x, y in path) - min(y for _x, y in path))


spans = {sp: span(paths[sp][:n]) for sp in (S1X, S2X)}
print(f"  info over {n} frames: 1x span {spans[S1X]}, 2x span {spans[S2X]}")
check("the same arc, at 2x, sweeps a WIDER span in X",
      spans[S2X][0] > spans[S1X][0],
      f"1x {spans[S1X][0]} -> 2x {spans[S2X][0]}")
check("...and in Y: the turn rate is unchanged, so the radius grows",
      spans[S2X][1] > spans[S1X][1],
      f"1x {spans[S1X][1]} -> 2x {spans[S2X][1]}")

# ===========================================================================
# 8. LEFT/RIGHT IS THE LEGACY FLIGHT'S AND NOBODY ELSE'S
# ===========================================================================
# THE FIELD KEEPS THE MEANING IT HAS ALWAYS HAD, and gains no second one. It
# chooses the legacy entry edge; an authored path decides its own start, so the
# byte reaches nothing. The editor disables the control and says so rather than
# silently repurposing it.
print("\n=== 8. LEFT/RIGHT moves a legacy Dropper and no other ===")
legacy_x, authored_x = {}, {}
for side, name in ((DROP_SIDE_LEFT, "LEFT"), (DROP_SIDE_RIGHT, "RIGHT")):
    rows, dr, pr, esc, drp, _m = session(
        lambda m, sd=side: install(m, count=2, authored=False, side=sd), 8, want=1)
    m0 = member0(rows)
    legacy_x[name] = (m0["x"], m0["vx"]) if m0 else None
    rows, dr, pr, esc, drp, _m = session(
        lambda m, sd=side: install(m, count=2, authored=True, side=sd), 8, want=1)
    m0 = member0(rows)
    authored_x[name] = (m0["x"], m0["vx"]) if m0 else None
print(f"  info legacy   LEFT {legacy_x['LEFT']}  RIGHT {legacy_x['RIGHT']}")
print(f"  info authored LEFT {authored_x['LEFT']}  RIGHT {authored_x['RIGHT']}")
check("a LEGACY Dropper enters from the authored side",
      legacy_x["LEFT"] == (DROP_ENTRY_LEFT, DROP_VX)
      and legacy_x["RIGHT"] == (DROP_ENTRY_RIGHT, -DROP_VX))
check("an AUTHORED Dropper is identical either way: the side reaches nothing",
      authored_x["LEFT"] == authored_x["RIGHT"] is not None,
      f"{authored_x['LEFT']} vs {authored_x['RIGHT']}")
check("...and neither answer is a legacy entry edge",
      authored_x["LEFT"][0] not in (DROP_ENTRY_LEFT, DROP_ENTRY_RIGHT))

# THE LEGACY FLIGHT STILL IGNORES TRIGGER SPEED, which is the engine's existing
# behaviour and is preserved rather than tidied: dropperFly calls
# wmApplyVelocity and never wmApplySpeed.
print("\n=== 8b. legacy still ignores trigger speed ===")
legacy_v = {}
for speed in (S1X, S2X):
    rows, dr, pr, esc, drp, _m = session(
        lambda m, sp=speed: install(m, count=2, authored=False, speed=sp), 8, want=1)
    m0 = member0(rows)
    legacy_v[speed] = (m0["vx"], m0["speed"]) if m0 else None
check("a legacy Dropper crosses at DROP_VX at every trigger speed",
      legacy_v[S1X][0] == legacy_v[S2X][0] == DROP_VX,
      f"1x {legacy_v[S1X]} vs 2x {legacy_v[S2X]}")
check("...although it still CARRIES the trigger's speed on the object, which is "
      "what an authored path would be scaled by",
      legacy_v[S1X][1] == S1X and legacy_v[S2X][1] == S2X)

# ===========================================================================
# 9. THE LAUNCH HEADING REACHES AN AUTHORED DROPPER
# ===========================================================================
# THROUGH THE ORDINARY MACHINERY, and through the definition the trigger already
# references -- there is no second heading field and no second definition
# selector. An arc asking WM_HEAD_CONT inherits the wmPhase src/waves.asm wrote
# from the definition, exactly as it does for any wave member.
print("\n=== 9. the launch heading steers an authored Dropper ===")
HEAD_A, HEAD_B = 0, CD.WM_HEAD_LEN // 4         # east, and a quarter turn on
seen = {}
for head in (HEAD_A, HEAD_B):
    rows, dr, pr, esc, drp, _m = session(
        lambda m, h=head: install(m, count=1, authored=True, heading=h,
                                  drop_records=ARC_PROG), 6, want=1)
    m0 = member0(rows)
    seen[head] = (m0["vx"], m0["vy"]) if m0 else None
# ONE STEP IN, because wmEnterStage's arc branch takes the heading's velocity
# immediately: wmLoadHeading runs before the first frame, and wmArcStep has not
# advanced the phase yet at the instant of activation.
want = {h: (ms.HEAD_VX[h], ms.HEAD_VY[h]) for h in (HEAD_A, HEAD_B)}
print(f"  info heading {HEAD_A}: {seen[HEAD_A]} (table {want[HEAD_A]})")
print(f"  info heading {HEAD_B}: {seen[HEAD_B]} (table {want[HEAD_B]})")
check("two different launch headings give two different opening velocities",
      seen[HEAD_A] != seen[HEAD_B], f"{seen[HEAD_A]} vs {seen[HEAD_B]}")
check("...and each is the engine's own heading-table entry",
      seen[HEAD_A] == want[HEAD_A] and seen[HEAD_B] == want[HEAD_B])

# ===========================================================================
# 10. THE TOKEN LIFECYCLE IS INTRINSIC AND SURVIVES
# ===========================================================================
# THE DROPPER'S DEATH IS WHAT DROPS THE TOKEN, and that is a property of being
# the Dropper rather than of the path it was on. Killing an authored one must
# still start the encounter, and its despawn must still release the interlock.
print("\n=== 10. an authored Dropper still drops its token ===")
v = None
try:
    v = Vice(PORT, PRG, boot="exact")
    mon = v.mon
    dr = rd1(mon, sym["lvlDropRow"])
    esc, drp = install(mon, count=1, authored=True)
    rows = watch(mon, 4, want=1)
    m0 = member0(rows)
    check("the authored Dropper is alive and holds the interlock",
          m0 is not None and rd1(mon, sym["tkDropperLive"]) == 1,
          f"tkDropperLive {rd1(mon, sym['tkDropperLive'])}")
    before = rd1(mon, sym["tkStarted"])
    # KILLED WHERE IT IS, THROUGH THE ENGINE'S OWN DEATH PATH. The destruction
    # event is staged and the game takes it from there: enemyTick runs the death
    # animation and src/enemy.asm's `!release:` hook is what drops the token.
    # Writing the token counter directly would prove nothing about the hook.
    kill(mon, m0["slot"])
    advance(mon, DEATH_TIME * 4 + 60)
    check("...and once it is gone the interlock is released",
          rd1(mon, sym["tkDropperLive"]) == 0,
          f"tkDropperLive {rd1(mon, sym['tkDropperLive'])}")
    check("...having started the token encounter, exactly as a legacy one does",
          rd1(mon, sym["tkStarted"]) > before,
          f"tkStarted {before} -> {rd1(mon, sym['tkStarted'])}")
    check("gameOverrun is zero across the authored flight and its death",
          rd1(mon, sym["gameOverrun"]) == 0,
          f"gameOverrun {rd1(mon, sym['gameOverrun'])}")
finally:
    if v:
        v.close()

print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
report(__name__)
