#!/usr/bin/env python3
"""Enemy firing v1 — authored, deterministic, straight down, one shared cap.

What this proves
----------------
* CAPABILITY IS THE SPECIES': enemyFireModeTab is one row per species, read at
  spawn, and a species whose row says NONE cannot be authored into firing;
* OPPORTUNITY IS THE ENCOUNTER'S: the authored fire mask is a bit per MEMBER
  INDEX, and member n of a wave gets the licence if and only if bit n is set --
  driven here through the real waveSpawnMember, once per member;
* A LIVE ELIGIBLE ENEMY FIRES, through the real frame loop, from the bottom
  centre of its own logical box, straight down, at the projectile system's own
  speed -- and a DYING one and a FREE SLOT do not;
* ONE CAP, SHARED: turret bolts and enemy bolts are the same three. With three
  in the air the enemy attempt fails cleanly, is counted as blocked, plays NO
  sound, and nothing is left corrupt or stalled;
* NO QUEUE: a blocked opportunity is lost, not retried on the next frame;
* THE EXISTING DAMAGE PATH IS UNTOUCHED: an enemy bolt on the ship is a player
  hit, through ebulletPlayerTick and playerTakeHit as before;
* THE SOUND FOLLOWS THE PROJECTILE: SFX_ESHOT on voice 2 on a successful spawn
  and on nothing else;
* HEALTH: with the firing tick in the frame, ordinary play leaves the
  catastrophic engine diagnostics at zero.

What this does NOT prove
------------------------
Whether the shots are FAIR. Visibility, cadence, combined turret-plus-enemy
pressure and the spit's timbre are manual-VICE questions and are not automated.

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
EBULLET_MAX   = 3               # src/ebullet.asm: the shared cap
EBULLET_VY    = 3
SPECIES_RING  = 0               # src/enemy.asm: a species IS its anim row
ENEMY_FIRE_DOWN = 1
ENEMY_MUZZLE_X = 8              # src/waves.asm
ENEMY_MUZZLE_Y = 18
WAVE_FIRE_PERIOD = 48
FIRE_Y        = 100             # inside ENEMY_FIRE_MIN_Y..MAX_Y
WAVE_DEF_SWEEP = 0
SFX_ESHOT     = 4
CH_KILL       = 1               # voice 2 carries the enemy shot
AUTHORED_MASKS = [0b0101, 0b0010, 0b0101, 0b0000]   # sweep, s-turn, linger, loop
PORT = 6672


def pool(mon, sym):
    """The 16-slot active map."""
    return rd(mon, sym["logActive"], MAX_OBJECTS)


def arrange_target(mon, sym, slot, y=FIRE_Y):
    """Make an EXISTING live enemy the ONLY enemy on screen that may fire.

    EVERY OTHER LICENCE IS REVOKED FIRST, in one monitor write, and that is what
    makes the scenarios below say anything at all. The firing tick scans the
    whole pool, so with several licensed enemies in the air "no shot happened"
    and "this particular enemy did not shoot" are different claims -- and the
    weaker one passes even when the feature is broken. Leaving exactly one
    candidate collapses the two.
    """
    poke(mon, sym["logY"] + slot, y)
    poke(mon, sym["logX"] + slot, 150)          # mid-screen: clear of every
    poke(mon, sym["logXHi"] + slot, 0)          # side despawn edge
    # AND THE TURRETS ARE STOOD DOWN FOR THE FRAME. They share the projectile
    # cap and fire from their own tick, three instructions before this one, so a
    # turret bolt launched into the same frame makes "a projectile appeared"
    # ambiguous and can take the last cap slot out from under the enemy.
    # turretFireTick returns immediately on a zero visible mask, and
    # turretAimTick rebuilds that mask from geometry on the very next frame, so
    # nothing is left disabled.
    poke(mon, sym["trtVisibleMask"], 0)
    mon.cmd(f"> {sym['enyFire']:04x} " + " ".join(["00"] * MAX_OBJECTS))
    poke(mon, sym["enyFire"] + slot, ENEMY_FIRE_DOWN)
    poke(mon, sym["objHP"] + slot, 4)
    poke(mon, sym["plyInvuln"], 0)
    poke(mon, sym["plyY"], 200)
    poke(mon, sym["wvFireCursor"], slot)


def fresh_enemy(mon, sym, mask=ENEMY_FIRE_DOWN, member=0):
    """Spawn ONE enemy through the real waveSpawnMember and return its slot.

    WHY NOT JUST USE AN ENEMY THAT IS ALREADY FLYING. The obvious pick -- the
    lowest live slot -- is the WORST pick: the pool allocates low-first, so the
    lowest slot holds the OLDEST enemy on screen, the one furthest along its
    path and likeliest to cross a despawn edge on the very next frame. When it
    does, objectZeroSlot clears its firing licence with the rest of the slot and
    the scenario silently has no candidate at all -- which looks exactly like
    the feature being broken. A freshly spawned enemy is at the start of its
    path and cannot leave inside one frame.
    """
    poke(mon, sym["wvDef"], WAVE_DEF_SWEEP)
    poke(mon, sym["wvFire"], mask)
    poke(mon, sym["wvSpecies"], SPECIES_RING)
    poke(mon, sym["wvIndex"], member)
    before = pool(mon, sym)
    call(mon, sym, "waveSpawnMember", x=0)
    after = pool(mon, sym)
    born = [i for i in range(MAX_OBJECTS) if after[i] and not before[i]]
    return born[0] if len(born) == 1 else None


def retire_enemy(mon, sym, slot):
    """End one enemy's life through the production enemyDespawn.

    THE POOL IS SIXTEEN SLOTS AND THIS FILE SPAWNS INTO IT REPEATEDLY. Probe
    enemies parked mid-screen do not leave by themselves inside a test, so
    without this they accumulate on top of whatever the director is flying,
    the pool fills, and the NEXT thing that needs a slot is a projectile --
    objectAlloc refuses it, and a scenario about firing fails for reasons that
    have nothing to do with firing. Cleaning up after each probe is what keeps
    every later check attributable.
    """
    if slot is not None:
        call(mon, sym, "enemyDespawn", x=slot)


def clear_sky(mon, sym):
    """Retire every hostile projectile, through the projectile system's own
    ebulletRetire, and return the pool to an empty-air state.

    WHY EVERY SCENARIO BELOW NEEDS THIS. waveFireTick refuses to fire at an
    INVULNERABLE ship, and ebulletPlayerTick runs earlier in the same gameFrame
    than waveFireTick does. So a bolt left over from a previous scenario can hit
    the player -- these scenarios deliberately zero plyInvuln -- and the hit
    then suppresses the very opportunity under test, one frame later. That is a
    genuine race in the FIXTURE, not in the game: it makes "no shot happened"
    mean two completely different things on two different runs.
    """
    for slot in range(MAX_OBJECTS):
        if rd1(mon, sym["logActive"] + slot) and \
           rd1(mon, sym["objType"] + slot) == 2:
            call(mon, sym, "ebulletRetire", x=slot)


def frame_top(mon, sym):
    """Advance to the top of the next gameFrame.

    CALLED TWICE PER SCENARIO, AND THE TWO CALLS MEAN DIFFERENT THINGS. From an
    arbitrary stop -- after harness.call() hijacked the PC, say -- the first one
    ALIGNS: it runs to the start of a frame, having executed none of that
    frame's work. Pokes made there are therefore consumed by the frame that
    follows. The second one RUNS that frame to completion and stops at the top
    of the next.

    Getting this wrong is silent: arrange, stop AT the top of a frame, and read
    back -- and nothing has happened yet, because the frame has not run.
    """
    set_bp(mon, sym["gameFrame"])
    mon.cmd("x")
    mon.cmd("delete")


def main():
    sym = symbols(SYM)
    v = None
    try:
        v = Vice(PORT, PRG, warp=True)
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        mon.cmd("x")

        # --- 1. health, FIRST, on a machine nothing has interfered with ------
        # THE CATASTROPHIC ONES: a frame missed, the scroller late, or the
        # renderer disagreeing with itself about a page or a pointer. Each is a
        # fault with no benign reading.
        CATASTROPHIC = ("gameOverrun", "scrollLate",
                        "statPageMismatch", "statPtrMismatch")
        # schedBuildDefer is NOT one of them and is deliberately not asserted
        # alongside them at the end. src/renderer.asm documents it as a guard
        # that fires "whenever the frame IRQ lands between buildSchedule and
        # publishSchedule... measured at over a tenth of all builds under load"
        # -- it counts the guard WORKING, not a fault. It is checked at zero in
        # the pristine run below, where the load is an ordinary encounter's, and
        # reported as a number afterwards, where this file has deliberately
        # stuffed the pool far past anything the authored content produces.
        HEALTH = CATASTROPHIC + ("schedBuildDefer",)
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], 0xef)        # trigger held
        for name in HEALTH:
            poke(mon, sym[name], 0)
        mon.cmd("delete")
        ran = free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        check("the health run really ran, non-stop, with the trigger held", ran)
        for name in HEALTH:
            val = rd1(mon, sym[name])
            check(f"{name} is zero with waveFireTick in the frame", val == 0,
                  str(val))
        print(f"  info enemy shots fired during the health run: "
              f"{rd1(mon, sym['wvShots'])}, blocked by the cap: "
              f"{rd1(mon, sym['wvShotBlocked'])}")

        # --- 2. capability is declared by the SPECIES ------------------------
        modes = rd(mon, sym["enemyFireModeTab"], 2)
        check("every species declares a firing mode explicitly, one row each",
              modes == [ENEMY_FIRE_DOWN, ENEMY_FIRE_DOWN], str(modes))

        # --- 3. opportunity is declared by the ENCOUNTER ---------------------
        masks = rd(mon, sym["waveTrigFire"], 4)
        check("the authored trigger list carries a fire mask per appearance",
              masks == AUTHORED_MASKS,
              f"{[bin(m) for m in masks]} vs {[bin(m) for m in AUTHORED_MASKS]}")
        check("...and one authored appearance fires nothing at all",
              0 in masks, str(masks))

        # THE MASK, DRIVEN THROUGH THE REAL SPAWNER, once per member index. An
        # instance is armed by hand with the sweep's definition and a known
        # mask; waveSpawnMember then does exactly what the director does.
        poke(mon, sym["wvDef"], WAVE_DEF_SWEEP)
        poke(mon, sym["wvFire"], 0b0101)
        poke(mon, sym["wvSpecies"], SPECIES_RING)
        granted = []
        for member in range(4):
            poke(mon, sym["wvIndex"], member)
            before = pool(mon, sym)
            call(mon, sym, "waveSpawnMember", x=0)
            after = pool(mon, sym)
            born = [i for i in range(MAX_OBJECTS) if after[i] and not before[i]]
            if len(born) != 1:
                granted.append(None)
                continue
            granted.append(rd1(mon, sym["enyFire"] + born[0]))
            retire_enemy(mon, sym, born[0])         # give the slot straight back
        check("member n fires if and only if the authored mask says bit n",
              granted == [ENEMY_FIRE_DOWN, 0, ENEMY_FIRE_DOWN, 0],
              f"members 0..3 got {granted} from mask {bin(0b0101)}")

        # THE SPECIES CAN VETO IT. Both level-1 species fire, so the row is
        # patched to NONE in RAM for one spawn: an appearance authored to fire,
        # made of a species that cannot, must produce no licence.
        poke(mon, sym["enemyFireModeTab"], 0)
        poke(mon, sym["wvIndex"], 0)                # a member the mask grants
        before = pool(mon, sym)
        call(mon, sym, "waveSpawnMember", x=0)
        after = pool(mon, sym)
        born = [i for i in range(MAX_OBJECTS) if after[i] and not before[i]]
        vetoed = rd1(mon, sym["enyFire"] + born[0]) if len(born) == 1 else None
        retire_enemy(mon, sym, born[0] if len(born) == 1 else None)
        poke(mon, sym["enemyFireModeTab"], ENEMY_FIRE_DOWN)     # put it back
        check("a species that cannot fire is not granted a licence by the "
              "encounter", vetoed == 0, str(vetoed))

        # --- 4. a live eligible enemy fires, through the real frame loop -----
        slot = fresh_enemy(mon, sym)
        check("a fresh licensed enemy was spawned to fire", slot is not None,
              str(slot))
        clear_sky(mon, sym)                         # empty air: see the helper
        frame_top(mon, sym)                         # align, THEN arrange
        arrange_target(mon, sym, slot)
        poke(mon, sym["sfxChId"] + CH_KILL, 0)
        shots0, fired0 = rd1(mon, sym["wvShots"]), rd1(mon, sym["ebFired"])
        before = pool(mon, sym)
        poke(mon, sym["wvFirePhase"], 1)            # the opportunity is now
        frame_top(mon, sym)                         # ...and run that frame

        # THE ENEMY'S BOX IS READ AFTER THE FRAME, not before it. objectUpdateAll
        # moves every enemy at the top of gameFrame and waveFireTick fires from
        # where it ENDED UP, so the pre-frame position is the wrong number to
        # compare a muzzle against. Nothing moves an enemy after the firing tick,
        # so the post-frame box is exactly what the muzzle was computed from.
        check("the firing enemy survived the frame it fired in",
              rd1(mon, sym["logActive"] + slot) == 1
              and rd1(mon, sym["objType"] + slot) == TYPE_ENEMY,
              f"slot {slot}")
        ex, exh, ey = (rd1(mon, sym["logX"] + slot),
                       rd1(mon, sym["logXHi"] + slot),
                       rd1(mon, sym["logY"] + slot))

        check("the opportunity produced an ENEMY shot, counted once -- the "
              "director's own counter moved, not just the projectile system's",
              rd1(mon, sym["wvShots"]) == shots0 + 1
              and rd1(mon, sym["ebFired"]) == fired0 + 1,
              f"wvShots {shots0}->{rd1(mon, sym['wvShots'])}, "
              f"ebFired {fired0}->{rd1(mon, sym['ebFired'])}")
        # THE BOLT IS IDENTIFIED BY WHAT IT IS, not by which slot changed
        # occupancy. A slot freed this frame -- a token despawning, an enemy
        # leaving -- can be reallocated to the bolt within the same frame, so
        # the slot's active flag reads 1 both before and after and a
        # new-arrivals diff misses it entirely. The sky was cleared and the
        # turrets stood down above, so exactly one hostile bolt should exist.
        bolts = [i for i, a in enumerate(pool(mon, sym)) if a
                 and rd1(mon, sym["objType"] + i) == 2]
        check("exactly one hostile bolt is in the air, and it is the enemy's",
              len(bolts) == 1, str(bolts))
        b = bolts[0]
        bx, bxh, by = (rd1(mon, sym["logX"] + b), rd1(mon, sym["logXHi"] + b),
                       rd1(mon, sym["logY"] + b))
        check("the bolt leaves the bottom centre of the enemy's logical box",
              (bxh << 8 | bx) == ((exh << 8 | ex) + ENEMY_MUZZLE_X)
              and by == ey + ENEMY_MUZZLE_Y,
              f"enemy ({exh << 8 | ex},{ey}) -> bolt ({bxh << 8 | bx},{by})")
        check("it is a hostile projectile on the shared machinery",
              rd1(mon, sym["objType"] + b) == 2, str(rd1(mon, sym["objType"] + b)))
        check("it falls STRAIGHT down at the projectile system's own speed",
              rd1(mon, sym["objVX"] + b) == 0
              and rd1(mon, sym["objVY"] + b) == EBULLET_VY,
              f"vx {rd1(mon, sym['objVX'] + b)}, vy {rd1(mon, sym['objVY'] + b)}")
        check("the enemy-shot SFX plays on voice 2, on the successful spawn",
              rd1(mon, sym["sfxChId"] + CH_KILL) == SFX_ESHOT,
              str(rd1(mon, sym["sfxChId"] + CH_KILL)))

        # THE FLIGHT IS MEASURED AGAINST FRAMES THAT DEMONSTRABLY ELAPSED. A
        # bare "x" to a breakpoint is not a promise that exactly one frame ran
        # -- the machine can be stalled or the monitor slow -- and an exact
        # "+3 after one frame" assertion turns that into a mystery failure.
        # frameCounter says how many frames really passed; the bolt must have
        # fallen EBULLET_VY for each of them.
        f0 = rd1(mon, sym["frameCounter"])
        frame_top(mon, sym)
        elapsed = (rd1(mon, sym["frameCounter"]) - f0) & 0xff
        check("...and it flies straight down through the existing projectile "
              "path, EBULLET_VY per frame",
              elapsed >= 1
              and rd1(mon, sym["logY"] + b) == by + EBULLET_VY * elapsed,
              f"{by} -> {rd1(mon, sym['logY'] + b)} over {elapsed} frame(s)")

        retire_enemy(mon, sym, slot)                # done with the firer

        # --- 5. the ineligible: dying, and a slot nobody owns ----------------
        slot = fresh_enemy(mon, sym)
        clear_sky(mon, sym)
        frame_top(mon, sym)
        arrange_target(mon, sym, slot)
        poke(mon, sym["objHP"] + slot, 0)           # killed this frame: dying
        poke(mon, sym["objTimer"] + slot, 12)       # ...with its death running
        shots0 = rd1(mon, sym["wvShots"])
        poke(mon, sym["wvFirePhase"], 1)
        frame_top(mon, sym)
        check("a DYING enemy does not fire",
              rd1(mon, sym["wvShots"]) == shots0, str(rd1(mon, sym["wvShots"])))

        retire_enemy(mon, sym, slot)

        free = [i for i, a in enumerate(pool(mon, sym)) if not a]
        check("there is a free slot to forge a stale licence on", bool(free))
        ghost = free[0]
        mon.cmd(f"> {sym['enyFire']:04x} " + " ".join(["00"] * MAX_OBJECTS))
        poke(mon, sym["enyFire"] + ghost, ENEMY_FIRE_DOWN)
        poke(mon, sym["logY"] + ghost, FIRE_Y)
        poke(mon, sym["objType"] + ghost, TYPE_ENEMY)
        poke(mon, sym["objHP"] + ghost, 4)
        poke(mon, sym["wvFireCursor"], ghost)
        shots0 = rd1(mon, sym["wvShots"])
        call(mon, sym, "waveFireTick")              # direct: the sorter never
        call(mon, sym, "waveFireTick")              # sees this slot at all
        check("an INACTIVE slot carrying a licence cannot fire",
              rd1(mon, sym["wvShots"]) == shots0, str(rd1(mon, sym["wvShots"])))
        poke(mon, sym["enyFire"] + ghost, 0)
        poke(mon, sym["objType"] + ghost, 0)
        poke(mon, sym["objHP"] + ghost, 0)

        # --- 6. ONE cap for turrets and enemies alike ------------------------
        slot = fresh_enemy(mon, sym)
        check("a fresh licensed enemy was spawned to test the cap with",
              slot is not None, str(slot))

        # Fill the air with TURRET bolts, through the turrets' own entry point.
        # High and to one side, so none of them can reach the ship -- and from a
        # KNOWN empty sky, so the count below is exactly these three.
        clear_sky(mon, sym)
        poke(mon, sym["ebSpawnXLo"], 40)
        poke(mon, sym["ebSpawnXHi"], 0)
        poke(mon, sym["ebSpawnY"], 60)
        for _ in range(EBULLET_MAX):
            if rd1(mon, sym["ebCount"]) >= EBULLET_MAX:
                break
            call(mon, sym, "ebulletSpawn")
        check(f"the shared cap is full at {EBULLET_MAX}",
              rd1(mon, sym["ebCount"]) == EBULLET_MAX,
              str(rd1(mon, sym["ebCount"])))

        frame_top(mon, sym)                         # re-align after the calls
        arrange_target(mon, sym, slot)
        poke(mon, sym["sfxChId"] + CH_KILL, 0)
        shots0 = rd1(mon, sym["wvShots"])
        blocked0 = rd1(mon, sym["wvShotBlocked"])
        refused0 = rd1(mon, sym["ebRefused"])
        poke(mon, sym["wvFirePhase"], 1)
        frame_top(mon, sym)
        check("the pool itself had room, so the cap is what refused the shot",
              rd1(mon, sym["logCount"]) < MAX_OBJECTS,
              f"{rd1(mon, sym['logCount'])} of {MAX_OBJECTS} slots live")
        check("the enemy's attempt is refused by the cap, cleanly",
              rd1(mon, sym["wvShots"]) == shots0
              and rd1(mon, sym["wvShotBlocked"]) == blocked0 + 1
              and rd1(mon, sym["ebRefused"]) == refused0 + 1,
              f"shots {shots0}, blocked {blocked0}->"
              f"{rd1(mon, sym['wvShotBlocked'])}, "
              f"refused {refused0}->{rd1(mon, sym['ebRefused'])}")
        check("...the cap did not overflow and the pool was not corrupted",
              rd1(mon, sym["ebCount"]) == EBULLET_MAX
              and rd1(mon, sym["objAllocFail"]) == 0,
              f"ebCount {rd1(mon, sym['ebCount'])}, "
              f"allocFail {rd1(mon, sym['objAllocFail'])}")
        check("a refused shot plays NO sound",
              rd1(mon, sym["sfxChId"] + CH_KILL) == 0,
              str(rd1(mon, sym["sfxChId"] + CH_KILL)))

        # NO DEFERRED QUEUE: the lost opportunity is not retried next frame,
        # and the period was reloaded in full.
        phase = rd1(mon, sym["wvFirePhase"])
        shots0 = rd1(mon, sym["wvShots"])
        frame_top(mon, sym)
        check("the blocked opportunity is LOST, not queued for the next frame",
              rd1(mon, sym["wvShots"]) == shots0
              and phase >= WAVE_FIRE_PERIOD - 1,
              f"phase reloaded to {phase}, shots {shots0}->"
              f"{rd1(mon, sym['wvShots'])}")

        # --- 7. an enemy bolt hurts the player, by the existing path ---------
        bolts = [i for i, a in enumerate(pool(mon, sym)) if a
                 and rd1(mon, sym["objType"] + i) == 2]
        check("there are bolts in the air to land one", bool(bolts), str(bolts))
        bolt = bolts[0]
        frame_top(mon, sym)                         # align before arranging
        px = rd(mon, sym["plyX"], 2)
        poke(mon, sym["logX"] + bolt, px[0])
        poke(mon, sym["logXHi"] + bolt, px[1])
        poke(mon, sym["logY"] + bolt, rd1(mon, sym["plyY"]))
        poke(mon, sym["plyInvuln"], 0)
        # ...and the craft must be ALIVE to be hit: a dying one ignores bolts
        # now, deliberately. See reports/player-death-fireball-collision.md.
        for f in ("plyDead", "plyBoomFrame", "plyBoomTimer", "plyFatal"):
            poke(mon, sym[f], 0)
        poke(mon, sym["plyVisible"], 1)
        poke(mon, sym["hudLives"], 200)

        hits0 = rd1(mon, sym["plyHits"])
        frame_top(mon, sym)
        check("a hostile bolt on the ship is a player hit, unchanged path",
              rd1(mon, sym["plyHits"]) == hits0 + 1,
              f"plyHits {hits0}->{rd1(mon, sym['plyHits'])}")

        # --- 8. the encounter carries on regardless --------------------------
        spawned0 = rd1(mon, sym["wvSpawned"])
        started0 = rd1(mon, sym["wvStarted"])
        # NO HEALTH ASSERTION HERE, DELIBERATELY. Everything above has hijacked
        # the program counter with harness.call() a dozen times, abandoning that
        # many gameFrames part-done, and has stuffed and emptied the pool by
        # hand. src/../tests/test_sfx.py records the consequence for this
        # harness: after that, the main-thread span and the publication
        # handshake "describe the debugger rather than the game" -- gameOverrun
        # and schedBuildDefer both drift, and an assertion on them here would be
        # a claim about the monitor. THE CATASTROPHIC GATE IS THE PRISTINE
        # FIVE-SECOND RUN AT THE TOP OF THIS FILE, before anything was touched.
        # What is asked here is only the behavioural question: is the encounter
        # director still running the level after all of that?
        mon.cmd("delete")
        free_run(mon, sym["frameCounter"], 4)
        mon.cmd("delete")
        check("the director keeps spawning after all of that",
              rd1(mon, sym["wvSpawned"]) != spawned0
              or rd1(mon, sym["wvStarted"]) != started0,
              f"spawned {spawned0}->{rd1(mon, sym['wvSpawned'])}, "
              f"started {started0}->{rd1(mon, sym['wvStarted'])}")
        print("  info post-abuse diagnostics, FOR INFORMATION ONLY: "
              + ", ".join(f"{n} {rd1(mon, sym[n])}" for n in HEALTH)
              + f", {rd1(mon, sym['logCount'])} of {MAX_OBJECTS} slots live")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
