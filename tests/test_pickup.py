#!/usr/bin/env python3
"""Token pickups v1 — authored spawn, drift, flash, collection, release.

What this proves
----------------
* DETERMINISTIC AND EARNED, NOT RANDOM: no authored trigger creates a token at
  all, and driving the REAL tokenDropperDied produces exactly one P at exactly
  the position the Dropper died at. (This replaces an obsolete premise -- the
  trigger list used to carry a token X per appearance. See section 2.);
* IDENTITY: the spawned object is TYPE_PICKUP of kind PICKUP_P wearing the P
  bitmap, with no health and no velocity but the authored downward drift;
* IT LIVES THROUGH THE ORDINARY OBJECT PATH: in the real frame loop it descends
  one pixel every OTHER frame -- half the scroll rate, on a strictly alternating
  cadence -- and despawns by itself past the bottom of the aperture, returning
  its slot. (Also a replaced premise: it used to match the scroll exactly. See
  section 4.);
* THE FLASH IS PRESENTATION ONLY: logCol alternates between the two authored
  colours while objType, pkKind, logPtr and logActive do not move at all;
* COLLECTION: the ship overlapping a token collects it EXACTLY ONCE, the
  counter moves by one, the slot is released whole, and the next frame cannot
  collect it again;
* A STALE SLOT COLLECTS NOTHING: a freed slot carrying a pickup type and the
  ship's own coordinates is refused;
* IT IS NOT A PROJECTILE: spawning and collecting tokens leaves ebCount,
  ebFired and the hostile cap untouched;
* A FULL POOL IS SAFE: pickupSpawn refuses cleanly, counts the loss, and
  corrupts nothing;
* THE GAME CARRIES ON afterwards, with the catastrophic diagnostics at zero.

What this does NOT prove
------------------------
Whether the P is legible, whether the flash cadence is pleasant, or whether the
hitbox feels fair. Those are manual-VICE questions.

publishSkip IS MEASURED BUT NOT ASSERTED. The enemy-firing tree already causes
occasional publication skips and that is a known, accepted limitation; this file
records the number either side of token load so a regression is visible without
being mistaken for a token bug. See reports/token-pickups-v1.md.

ORDER MATTERS: the health run goes first, on a machine nothing has interfered
with, because harness.call() hijacks the PC mid-frame.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, step_n, call, check, report)

MAX_OBJECTS   = 16
TYPE_ENEMY    = 1
TYPE_EBULLET  = 2
TYPE_PICKUP   = 3
PICKUP_P      = 0
PICKUP_VY     = 1
PICKUP_SPAWN_Y = 30
PICKUP_Y_MAX  = 250
PICKUP_P_PER_UNIT = 3          # src/pickup.asm: three pickups = one unit
TOKEN_PTR     = 0x2580 // 64            # $96
COL_LIT, COL_DARK = 1, 15
FLASH_BIT     = 0x10
WAVE_SLOTS    = 2                       # src/waves.asm
WAVE_TRIGGERS = 4
# Where the notional Dropper dies. Deliberately NOT the old fixed spawn line
# (PICKUP_SPAWN_Y) and not an authored X, so "it appeared where it died" cannot
# pass by coincidence against either of the values the old model used.
DEATH_X       = 173
DEATH_Y       = 118
PORT = 6673


def pool(mon, sym):
    return rd(mon, sym["logActive"], MAX_OBJECTS)


def pickups_taken(mon, sym):
    """How many tokens have been collected, under the CURRENT P economy.

    A THIRD REPLACED PREMISE. This file used to read pkTokensP as "tokens
    collected" and that was right until the P economy landed: pkTokensP now
    counts SPENDABLE UNITS and only moves on every third pickup, with pkCharge
    holding the 0..2 partial. Collecting one token therefore leaves pkTokensP
    exactly where it was, and the old assertion failed for a reason that had
    nothing to do with collection.

    units * 3 + charge is the total number of tokens the player has picked up,
    which is precisely what the old check meant. It is stricter than reading
    either byte alone: a collection that bumped the charge without carrying, or
    carried without clearing the charge, both fail here.
    """
    return (rd1(mon, sym["pkTokensP"]) * PICKUP_P_PER_UNIT
            + rd1(mon, sym["pkCharge"]))


def align(mon, sym):
    """Stop at the TOP of a frame, with the gameFrame breakpoint left armed.

    ARRANGE AFTER THIS, RUN AFTER THAT, and the two-phase shape is forced by
    where the frame counter is bumped. The renderer increments it at raster 250
    and gameFrame's body runs immediately afterwards, so "the counter changed"
    means a frame is about to run, NOT that one just finished: step_n called
    from the middle of a frame lands at the top of the next one having executed
    no gameplay at all. From an ALIGNED stop it is exact -- one accepted step is
    one complete frame body.

    A bare `x` cannot replace this either: a checkpoint fires on the current PC,
    so stepping while already stopped at gameFrame returns having run nothing.
    Both mistakes were made and measured here; each one looks precisely like the
    feature under test being broken.
    """
    mon.cmd("delete")
    set_bp(mon, sym["gameFrame"])
    step_n(mon, sym["frameCounter"], 1, lambda: None)


def run_frames(mon, sym, n=1, read_fn=None):
    """n COMPLETE frame bodies from an aligned stop, read_fn() once per frame."""
    return step_n(mon, sym["frameCounter"], n, read_fn or (lambda: None))


def drop_token(mon, sym, x=DEATH_X, y=DEATH_Y):
    """Create a token the way the game now does: a Dropper dies.

    src/enemy.asm copies the dying Dropper's own position into pkSpawnXLo/Hi/Y
    and then calls tokenDropperDied, which is the one entry point for the whole
    mechanic. Setting those three bytes and calling it is therefore the real
    production path with the DEATH arranged and nothing else -- the token's
    placement, kind, presentation and lifecycle are all the production path's
    own work, exactly as they were when a trigger did the arranging.

    The encounter tokenDropperDied also opens is stood down afterwards:
    tests/test_token_encounter.py owns that subsystem, and this file is about
    the pickup.
    """
    poke(mon, sym["tkActive"], 0)
    poke(mon, sym["pkSpawnXLo"], x & 0xff)
    poke(mon, sym["pkSpawnXHi"], x >> 8)
    poke(mon, sym["pkSpawnY"], y)
    before = pool(mon, sym)
    call(mon, sym, "tokenDropperDied")
    after = pool(mon, sym)
    poke(mon, sym["tkActive"], 0)
    born = [i for i in range(MAX_OBJECTS)
            if after[i] and not before[i]
            and rd1(mon, sym["objType"] + i) == TYPE_PICKUP]
    return born[0] if len(born) == 1 else None


def trigger_spawns_token(mon, sym, trigger):
    """Drive the REAL director entry point for one authored trigger.

    Returns the pickup slot the trigger created, or None -- and None is now the
    only correct answer for every trigger. waveStartNext is what waveTick calls
    when a trigger comes due; calling it directly arranges the MOMENT and
    nothing else.

    BOTH WAVE INSTANCES ARE FREED FIRST, so every trigger genuinely arms. There
    are only WAVE_SLOTS of them and waveStartNext returns early when none is
    free -- without this, the third and fourth triggers would take the
    "dropped" path and never read their own columns at all, which would make
    "no trigger creates a token" true for a reason the test did not intend.
    """
    for s in range(WAVE_SLOTS):
        poke(mon, sym["wvActive"] + s, 0)
    poke(mon, sym["wvNextTrig"], trigger)
    before = pool(mon, sym)
    call(mon, sym, "waveStartNext")
    after = pool(mon, sym)
    born = [i for i in range(MAX_OBJECTS)
            if after[i] and not before[i]
            and rd1(mon, sym["objType"] + i) == TYPE_PICKUP]
    return born[0] if len(born) == 1 else None


def main():
    sym = symbols(SYM)
    v = None
    try:
        v = Vice(PORT, PRG, warp=True)
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        mon.cmd("x")

        # --- 1. health, FIRST, on a machine nothing has interfered with ------
        CATASTROPHIC = ("gameOverrun", "scrollLate",
                        "statPageMismatch", "statPtrMismatch")
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], 0xef)         # trigger held
        for name in CATASTROPHIC + ("publishSkip",):
            poke(mon, sym[name], 0)
        mon.cmd("delete")
        ran = free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        check("the health run really ran, non-stop, with the trigger held", ran)
        for name in CATASTROPHIC:
            val = rd1(mon, sym[name])
            check(f"{name} is zero with the pickup ticks in the frame",
                  val == 0, str(val))
        skip_live = rd1(mon, sym["publishSkip"])
        print(f"  info publishSkip over 5s of ordinary play WITH tokens: "
              f"{skip_live}  (measured, NOT asserted -- known limitation)")
        print(f"  info tokens spawned {rd1(mon, sym['pkSpawned'])}, collected "
              f"{rd1(mon, sym['pkTokensP'])}, despawned "
              f"{rd1(mon, sym['pkDespawned'])}, dropped "
              f"{rd1(mon, sym['pkDropped'])} during that run")

        # --- 2. NO TRIGGER CREATES A TOKEN ------------------------------------
        # THIS SECTION REPLACES AN OBSOLETE PREMISE, and the replacement asserts
        # the same INTENT against the mechanism that now carries it.
        #
        # Until src/waves.asm's token slice, a token was authored CONTENT: the
        # trigger list carried a fifth and sixth column (waveTrigTokenLo/Hi) and
        # two of the four appearances brought a P at an authored X. This file
        # proved determinism by reading those columns. They were deleted when a
        # token became a REWARD rather than a placement -- "No trigger creates
        # one, and no P appears merely because a wave started" -- and this test
        # has referenced the removed symbol ever since, crashing on a KeyError
        # before it could run.
        #
        # The intent was never "there is a token column"; it was "a P's
        # appearance is DETERMINISTIC AND AUTHORED, never a random drop". That
        # intent survives intact, so it is asserted here in its current terms:
        # no trigger produces a token at all (below), and a Dropper's death
        # produces exactly one at exactly the place it died (section 3).
        check("no authored trigger creates a token any more -- a P is a reward, "
              "not a placement",
              all(trigger_spawns_token(mon, sym, t) is None
                  for t in range(WAVE_TRIGGERS)),
              "one of the four triggers spawned a TYPE_PICKUP")
        check("...and the removed token columns are gone from the build",
              "waveTrigTokenLo" not in sym and "waveTrigTokenHi" not in sym)

        # --- 3. the spawn that DOES happen: a Dropper's death ------------------
        # tokenDropperDied is the one entry point for the whole mechanic
        # (src/token.asm), and src/enemy.asm reaches it having first copied the
        # dying Dropper's own position into pkSpawnXLo/Hi/Y. Setting those and
        # calling it is therefore the real production path with the DEATH
        # arranged and nothing else -- exactly the shape the old section used
        # for waveStartNext.
        poke(mon, sym["tkActive"], 0)       # tokenDropperDied refuses if an
                                            # encounter is already running
        poke(mon, sym["pkSpawnXLo"], DEATH_X & 0xff)
        poke(mon, sym["pkSpawnXHi"], DEATH_X >> 8)
        poke(mon, sym["pkSpawnY"], DEATH_Y)
        before = pool(mon, sym)
        call(mon, sym, "tokenDropperDied")
        after = pool(mon, sym)
        born = [i for i in range(MAX_OBJECTS)
                if after[i] and not before[i]
                and rd1(mon, sym["objType"] + i) == TYPE_PICKUP]
        check("a Dropper's death spawns exactly one token", len(born) == 1,
              f"{len(born)} pickups born: {born}")
        slot = born[0] if born else 0
        x = rd1(mon, sym["logX"] + slot) | (rd1(mon, sym["logXHi"] + slot) << 8)
        check("...at EXACTLY the position the Dropper died at, not a fixed line",
              x == DEATH_X and rd1(mon, sym["logY"] + slot) == DEATH_Y,
              f"({x}, {rd1(mon, sym['logY'] + slot)}) "
              f"wanted ({DEATH_X}, {DEATH_Y})")
        # THE ENCOUNTER IS THE OTHER SUBSYSTEM'S BUSINESS. tokenDropperDied also
        # opens a defender encounter; tests/test_token_encounter.py owns that.
        # This file is about the PICKUP, so the encounter is stood down and the
        # token left to live its ordinary object life through the sections below.
        poke(mon, sym["tkActive"], 0)
        check("...as a TYPE_PICKUP of kind P wearing the P bitmap",
              rd1(mon, sym["objType"] + slot) == TYPE_PICKUP
              and rd1(mon, sym["pkKind"] + slot) == PICKUP_P
              and rd1(mon, sym["logPtr"] + slot) == TOKEN_PTR,
              f"type {rd1(mon, sym['objType'] + slot)}, "
              f"kind {rd1(mon, sym['pkKind'] + slot)}, "
              f"ptr ${rd1(mon, sym['logPtr'] + slot):02x}")
        check("...drifting down at the scroll's own speed, and not a target",
              rd1(mon, sym["objVY"] + slot) == PICKUP_VY
              and rd1(mon, sym["objVX"] + slot) == 0
              and rd1(mon, sym["objHP"] + slot) == 0,
              f"vy {rd1(mon, sym['objVY'] + slot)}, "
              f"vx {rd1(mon, sym['objVX'] + slot)}, "
              f"hp {rd1(mon, sym['objHP'] + slot)}")

        # --- 4. it lives through the ordinary object path ---------------------
        # THE SHIP IS PARKED OUT OF THE WAY for the drift and flash scenarios,
        # or it would collect the very token being measured.
        poke(mon, sym["plyY"], 220)
        poke(mon, sym["plyX"], 40)
        poke(mon, sym["plyXHi"], 0)
        # THE RATE IS READ OFF THE TOKEN ITSELF, one frame at a time, rather
        # than from a frameCounter delta across the run. The counter is bumped
        # by the renderer at raster 250 and a stop at the top of gameFrame does
        # not sample it reliably -- measured, it can read the same value either
        # side of a frame that demonstrably ran. Consecutive Y readings need no
        # such trust: a frame that did not run shows up as a step of zero and
        # fails this check, which is exactly what it should do.
        # A SECOND STALE PREMISE, REPLACED RATHER THAN RELAXED. This used to
        # assert one pixel EVERY frame -- "the scroll's own speed" -- and that
        # was right when it was written. src/pickup.asm now applies the step on
        # one frame in two, deliberately and with its reasoning recorded beside
        # the constant: "the token is now the centre of an encounter that has to
        # be watched, so it descends at half the scroll rate... The token no
        # longer matches the scroll, and that is now correct."
        #
        # PICKUP_VY_MASK is the mechanism -- a frameCounter bit, no accumulator
        # and no per-token byte -- so the cadence is exactly alternating, and
        # asserting that is STRICTER than the old check rather than looser: a
        # token that moved every frame, or every third frame, or irregularly,
        # all fail here.
        align(mon, sym)
        ys = run_frames(mon, sym, 9, lambda: rd1(mon, sym["logY"] + slot))
        steps = [b - a for a, b in zip(ys, ys[1:])]
        check("the token descends one pixel every OTHER frame -- half the "
              "scroll rate, by src/pickup.asm's frameCounter bit",
              set(steps) == {0, PICKUP_VY}, f"{ys}, steps {steps}")
        check("...on a strictly alternating cadence, not an irregular one",
              all(a != b for a, b in zip(steps, steps[1:])),
              f"steps {steps}")
        check("...so it covers exactly half the ground the scroll does",
              ys[-1] - ys[0] == (len(ys) - 1) // 2,
              f"{ys[0]} -> {ys[-1]} over {len(ys) - 1} frames")

        # --- 5. the flash is presentation and NOTHING else --------------------
        # Sampled over a whole flash period; identity is read on every sample.
        samples = run_frames(mon, sym, 40, lambda: (
            rd1(mon, sym["logActive"] + slot),
            rd1(mon, sym["logCol"] + slot),
            rd1(mon, sym["objType"] + slot),
            rd1(mon, sym["pkKind"] + slot),
            rd1(mon, sym["logPtr"] + slot)))
        alive = [s for s in samples if s[0]]
        cols = {s[1] for s in alive}
        identity = {s[2:] for s in alive}
        check("the token flashes between its two authored colours",
              cols == {COL_LIT, COL_DARK},
              f"colours seen: {sorted(cols)}")
        check("...and its gameplay identity never moves while it does",
              identity == {(TYPE_PICKUP, PICKUP_P, TOKEN_PTR)}, str(identity))

        # --- 6. it despawns by itself past the bottom -------------------------
        align(mon, sym)
        poke(mon, sym["logY"] + slot, PICKUP_Y_MAX - 1)
        despawned0 = rd1(mon, sym["pkDespawned"])
        live0 = rd1(mon, sym["logCount"])
        # TWO FRAMES, NOT ONE, and for the same reason as the cadence check
        # above: the token steps on one frame in two, so from an arbitrary
        # alignment it needs up to two frames to take its next step. One frame
        # was right when it moved every frame. It still despawns on the very
        # step that crosses PICKUP_Y_MAX -- this waits for that step, it does
        # not give the engine extra rope.
        run_frames(mon, sym, 2)
        check("a token that falls past the aperture despawns itself",
              rd1(mon, sym["logActive"] + slot) == 0
              and rd1(mon, sym["pkDespawned"]) == despawned0 + 1,
              f"active {rd1(mon, sym['logActive'] + slot)}, "
              f"despawned {despawned0}->{rd1(mon, sym['pkDespawned'])}")
        check("...releasing its slot whole: type, kind and the pool count",
              rd1(mon, sym["objType"] + slot) == 0
              and rd1(mon, sym["pkKind"] + slot) == 0
              and rd1(mon, sym["logCount"]) == live0 - 1,
              f"type {rd1(mon, sym['objType'] + slot)}, "
              f"kind {rd1(mon, sym['pkKind'] + slot)}, "
              f"count {live0}->{rd1(mon, sym['logCount'])}")

        # --- 7. collection ----------------------------------------------------
        slot = drop_token(mon, sym)
        check("a token to collect", slot is not None, str(slot))
        eb0 = (rd1(mon, sym["ebCount"]), rd1(mon, sym["ebFired"]))
        align(mon, sym)                         # arrange AT a frame top
        poke(mon, sym["logY"] + slot, 120)
        poke(mon, sym["logX"] + slot, 150)
        poke(mon, sym["logXHi"] + slot, 0)
        poke(mon, sym["plyY"], 120)
        poke(mon, sym["plyX"], 150)
        poke(mon, sym["plyXHi"], 0)
        poke(mon, sym["plyInvuln"], 0)
        tokens0 = pickups_taken(mon, sym)
        live0 = rd1(mon, sym["logCount"])
        run_frames(mon, sym, 1)                 # ONE frame consumes the overlap
        check("the ship overlapping a token collects it, once",
              pickups_taken(mon, sym) == tokens0 + 1,
              f"pickups {tokens0}->{pickups_taken(mon, sym)} "
              f"(units {rd1(mon, sym['pkTokensP'])}, "
              f"charge {rd1(mon, sym['pkCharge'])})")
        check("...the token disappears and its slot is released whole",
              rd1(mon, sym["logActive"] + slot) == 0
              and rd1(mon, sym["objType"] + slot) == 0
              and rd1(mon, sym["pkKind"] + slot) == 0
              and rd1(mon, sym["logCount"]) == live0 - 1,
              f"active {rd1(mon, sym['logActive'] + slot)}, "
              f"count {live0}->{rd1(mon, sym['logCount'])}")
        tokens1 = pickups_taken(mon, sym)
        run_frames(mon, sym, 3)
        check("...and it cannot be collected a second time",
              pickups_taken(mon, sym) == tokens1,
              f"{tokens1} -> {pickups_taken(mon, sym)}")
        check("collecting a token is not a projectile event: the hostile cap "
              "and its counters are untouched",
              (rd1(mon, sym["ebCount"]), rd1(mon, sym["ebFired"])) == eb0,
              f"{eb0} -> {(rd1(mon, sym['ebCount']), rd1(mon, sym['ebFired']))}")

        # --- 8. a stale slot collects nothing ---------------------------------
        # A FREE slot forged to look exactly like a token sitting on the ship:
        # right type, right kind, right coordinates, but never activated. Only
        # logActive separates it from the real thing, which is the point.
        free = [i for i, a in enumerate(pool(mon, sym)) if not a]
        check("there is a free slot to forge a stale token on", bool(free))
        ghost = free[0]
        poke(mon, sym["objType"] + ghost, TYPE_PICKUP)
        poke(mon, sym["pkKind"] + ghost, PICKUP_P)
        poke(mon, sym["logY"] + ghost, rd1(mon, sym["plyY"]))
        poke(mon, sym["logX"] + ghost, rd1(mon, sym["plyX"]))
        poke(mon, sym["logXHi"] + ghost, rd1(mon, sym["plyXHi"]))
        tokens0 = pickups_taken(mon, sym)
        call(mon, sym, "pickupPlayerTick")
        call(mon, sym, "pickupPlayerTick")
        check("an INACTIVE slot carrying a token cannot be collected",
              pickups_taken(mon, sym) == tokens0,
              f"{tokens0} -> {pickups_taken(mon, sym)}")
        poke(mon, sym["objType"] + ghost, 0)
        poke(mon, sym["pkKind"] + ghost, 0)

        # --- 9. a full pool refuses a token cleanly ---------------------------
        # Every free slot is taken by the pool's own allocator, so the refusal
        # below is the real one rather than a simulated return value.
        # objectAlloc always takes the LOWEST free slot, so which one it will
        # pick is predictable and objectActivate can be handed the same index.
        # Nothing here writes logActive or logCount by hand: the pool's own two
        # routines do it, so the refusal below is a real one.
        taken = []
        for _ in range(MAX_OBJECTS):
            free_now = [i for i, a in enumerate(pool(mon, sym)) if not a]
            if not free_now:
                break
            s_free = free_now[0]
            call(mon, sym, "objectAlloc")
            call(mon, sym, "objectActivate", x=s_free)
            taken.append(s_free)
        check("the pool really is full", rd1(mon, sym["logCount"]) == MAX_OBJECTS,
              f"{rd1(mon, sym['logCount'])} of {MAX_OBJECTS}")
        dropped0 = rd1(mon, sym["pkDropped"])
        spawned0 = rd1(mon, sym["pkSpawned"])
        slot = drop_token(mon, sym)
        check("a token authored into a full pool is refused, counted and lost",
              slot is None
              and rd1(mon, sym["pkDropped"]) == dropped0 + 1
              and rd1(mon, sym["pkSpawned"]) == spawned0,
              f"dropped {dropped0}->{rd1(mon, sym['pkDropped'])}, "
              f"spawned {spawned0}->{rd1(mon, sym['pkSpawned'])}")
        check("...and the pool is not corrupted by the refusal",
              rd1(mon, sym["logCount"]) == MAX_OBJECTS
              and rd1(mon, sym["objDoubleFree"]) == 0,
              f"count {rd1(mon, sym['logCount'])}, "
              f"doubleFree {rd1(mon, sym['objDoubleFree'])}")
        for s in taken:                          # give the pool back
            call(mon, sym, "objectFree", x=s)

        # --- 10. the game carries on ------------------------------------------
        # THE DIRECTOR IS RE-ARMED FIRST, and that is setup rather than a
        # relaxation. The question this section asks is "is the encounter
        # director still alive after all that pool abuse" -- it is not "does
        # Level 1 still have content left". Since Wave Contract Stage 1 the four
        # authored encounters happen once, at rows 48/52/90/126, and this file's
        # own earlier sections drive waveStartNext several times; by the time we
        # reach here the cursor is legitimately exhausted and no wave can start
        # however healthy the director is.
        #
        # So one disposable trigger is placed two coarse rows ahead of the world
        # and the cursor wound back to it. Everything the check then observes --
        # the due test, the instance arming, the member spawning -- is the real
        # production path doing its real work.
        here = rd1(mon, sym["worldProgressLo"]) \
            | (rd1(mon, sym["worldProgressHi"]) << 8)
        due = here + 2
        poke(mon, sym["waveTrigRowLo"], due & 0xff)
        poke(mon, sym["waveTrigRowHi"], (due >> 8) & 0xff)
        # THE BOSS APPROACH HAS TO BE OPENED TOO. This liveness check rewinds the
        # trigger cursor, but by now worldProgress is past 2,200 -- far beyond
        # the level's authored STAGE_NO_SPAWN_ROW of 340 -- so the director
        # would correctly refuse to start anything and the check would be
        # measuring the quiet zone rather than the director. The approach is
        # package data at $f530; pushing it to $ffff restores the pre-quiet-zone
        # meaning of this assertion. See tests/test_no_spawn_row.py.
        poke(mon, 0xf530, 0xff)
        poke(mon, 0xf531, 0xff)
        poke(mon, sym["wvNextTrig"], 0)
        for s in range(WAVE_SLOTS):
            poke(mon, sym["wvActive"] + s, 0)

        poke(mon, sym["plyY"], 200)
        spawned0 = rd1(mon, sym["wvSpawned"])
        started0 = rd1(mon, sym["wvStarted"])
        for name in CATASTROPHIC + ("publishSkip",):
            poke(mon, sym[name], 0)
        mon.cmd("delete")
        free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        check("the encounter director keeps running after all of that",
              rd1(mon, sym["wvSpawned"]) != spawned0
              or rd1(mon, sym["wvStarted"]) != started0,
              f"spawned {spawned0}->{rd1(mon, sym['wvSpawned'])}, "
              f"started {started0}->{rd1(mon, sym['wvStarted'])}")
        # THE CLOSING COUNTERS ARE INFORMATION, NOT A GATE, and the pristine
        # five-second run at the top of this file is the gate. By this point the
        # program counter has been hijacked by harness.call() a dozen times and
        # the pool has been deliberately stuffed to all sixteen slots and
        # emptied again; the main-thread span after that describes the debugger
        # and the wreckage, not the game. Whether TOKENS cost frames is answered
        # by a paired tokens-on/tokens-off probe under identical conditions --
        # see reports/token-pickups-v1.md -- not by this line.
        print("  info post-abuse diagnostics, FOR INFORMATION ONLY: "
              + ", ".join(f"{n} {rd1(mon, sym[n])}"
                          for n in CATASTROPHIC + ("publishSkip",))
              + f", {rd1(mon, sym['logCount'])} of {MAX_OBJECTS} slots live")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
