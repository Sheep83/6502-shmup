#!/usr/bin/env python3
"""Player death: no controls, a one-shot fireball, and enemy body collision.

What this proves
----------------
* a dead craft cannot be steered, cannot fire, and cannot leave HW1 lit;
* ramming a LIVE enemy damages a vulnerable player through the EXISTING
  playerTakeHit path -- and an invulnerable one, a dying enemy, a hostile
  projectile and a collectible token all fail to;
* ordinary death runs the whole eight-frame explosion and then respawns with
  the invulnerability blink intact;
* terminal death runs the SAME explosion, hides HW0 after the last frame, and
  then reaches the restored GAME OVER state;
* the explosion never loops;
* the artwork is structurally sound: eight 64-byte blocks at the expected
  pointers, inside the free run, using only legal multicolour codes.

WHETHER IT LOOKS LIKE A FIREBALL IS NOT TESTED HERE. That is a manual VICE
judgement and no amount of Python can make it.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, step_n, call, check, report)

MAX_OBJECTS = 16
TYPE_ENEMY, TYPE_EBULLET, TYPE_PICKUP = 1, 2, 3
BOOM_FRAMES, BOOM_HOLD = 8, 6
BOOM_BASE = 0x25c0
BOOM_PTR = BOOM_BASE // 64                      # $97
BOOM_COL = 2                                    # red, HW0's own $d027
SHIP_COL = 14
DEATH_LEN = BOOM_FRAMES * BOOM_HOLD             # 48 frames
INVULN = 100
GS_PLAYING, GS_GAMEOVER = 1, 2
JOY_IDLE, JOY_RIGHT_FIRE = 0xff, 0xe7
PORT = 6675


def align(mon, sym):
    mon.cmd("delete")
    set_bp(mon, sym["gameFrame"])
    step_n(mon, sym["frameCounter"], 1, lambda: None)


def run_frames(mon, sym, n=1, read_fn=None):
    return step_n(mon, sym["frameCounter"], n, read_fn or (lambda: None))


def revive(mon, sym, lives=5):
    """A known-alive craft. The harness's own start-up may have left one dying."""
    poke(mon, sym["plyDead"], 0)
    poke(mon, sym["plyBoomFrame"], 0)
    poke(mon, sym["plyBoomTimer"], 0)
    poke(mon, sym["plyFatal"], 0)
    poke(mon, sym["plyInvuln"], 0)
    poke(mon, sym["plyVisible"], 1)
    poke(mon, sym["plyFlash"], 0)
    poke(mon, sym["hudLives"], lives)
    poke(mon, sym["gsState"], GS_PLAYING)


def free_slot(mon, sym):
    act = rd(mon, sym["logActive"], MAX_OBJECTS)
    return [i for i, a in enumerate(act) if not a]


def put_body(mon, sym, slot, otype=TYPE_ENEMY, hp=4):
    """Place an object of the given type exactly on the ship."""
    poke(mon, sym["logX"] + slot, rd1(mon, sym["plyX"]))
    poke(mon, sym["logXHi"] + slot, rd1(mon, sym["plyXHi"]))
    poke(mon, sym["logY"] + slot, rd1(mon, sym["plyY"]))
    poke(mon, sym["objType"] + slot, otype)
    poke(mon, sym["objHP"] + slot, hp)
    poke(mon, sym["logActive"] + slot, 1)


def clear_slot(mon, sym, slot):
    for f in ("logActive", "objType", "objHP"):
        poke(mon, sym[f] + slot, 0)


def isolate(mon, sym):
    """Deactivate every pool slot and return the flags, to be restored after.

    WHY THE NEGATIVE CASES NEED THIS. The craft sits near the bottom of the
    aperture and real enemies descend through exactly that band before they
    despawn, so one of them is periodically overlapping the ship for real --
    measured, and it killed the player in three consecutive eligibility cases
    that were supposed to prove the forged body did NOT. With only the forged
    slot active, "the player was damaged" can mean one thing and one thing only.

    Safe because nothing between isolate() and restore() runs a frame: the
    routine under test is driven directly, so the sorter never sees the pool
    in this state.
    """
    saved = rd(mon, sym["logActive"], MAX_OBJECTS)
    for i in range(MAX_OBJECTS):
        poke(mon, sym["logActive"] + i, 0)
    return saved


def restore(mon, sym, saved):
    for i, a in enumerate(saved):
        poke(mon, sym["logActive"] + i, a)


def main():
    sym = symbols(SYM)

    # --- 1. the artwork, structurally ---------------------------------------
    check("the fireball is eight frames", BOOM_FRAMES == 8, str(BOOM_FRAMES))
    v = None
    try:
        v = Vice(PORT, PRG, warp=True)
        mon = v.mon

        art = rd(mon, BOOM_BASE, BOOM_FRAMES * 64)
        check("...occupying exactly eight 64-byte blocks",
              len(art) == 512, str(len(art)))
        check("...inside the free run below screen page B",
              BOOM_BASE >= 0x2580 + 64 and BOOM_BASE + 512 <= 0x2800,
              f"${BOOM_BASE:04x}-${BOOM_BASE + 511:04x}")
        check("...at the pointer the code uses", BOOM_PTR == 0x97,
              f"${BOOM_PTR:02x}")
        # every frame must differ from every other: eight distinct pictures
        frames = [tuple(art[f * 64:f * 64 + 63]) for f in range(BOOM_FRAMES)]
        check("...and all eight frames are distinct artwork",
              len(set(frames)) == BOOM_FRAMES, f"{len(set(frames))} distinct")
        check("...none of them empty", all(any(f) for f in frames))
        # the 64th byte of each block is never fetched and must stay zero
        check("...with the unused 64th byte of each block left at zero",
              all(art[f * 64 + 63] == 0 for f in range(BOOM_FRAMES)))

        # --- 2. a dead craft has no controls ---------------------------------
        align(mon, sym)
        revive(mon, sym)
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], JOY_IDLE)
        run_frames(mon, sym, 1)
        call(mon, sym, "playerTakeHit")
        align(mon, sym)
        check("the hit kills the craft outright",
              rd1(mon, sym["plyDead"]) == 1 and rd1(mon, sym["hudLives"]) == 4,
              f"dead {rd1(mon, sym['plyDead'])}, "
              f"lives {rd1(mon, sym['hudLives'])}")
        check("...and the muzzle is put out on the same frame",
              rd1(mon, sym["plyFlash"]) == 0)

        x0 = rd1(mon, sym["plyX"])
        y0 = rd1(mon, sym["plyY"])
        poke(mon, sym["joyState"], JOY_RIGHT_FIRE)     # held for the whole death
        seq = run_frames(mon, sym, DEATH_LEN - 2, lambda: (
            rd1(mon, sym["plyDead"]), rd1(mon, sym["plyBoomFrame"]),
            rd1(mon, sym["plyPresPtr0"]), rd1(mon, sym["plyPresCol0"]),
            rd1(mon, sym["plyPresEnable"]), rd1(mon, sym["plyX"]),
            rd1(mon, sym["plyY"]), rd1(mon, sym["shotFired"]),
            rd1(mon, sym["plyFlash"])))
        dying = [r for r in seq if r[0]]
        check("the craft does not move while it burns, with the stick held",
              all(r[5] == x0 and r[6] == y0 for r in dying),
              f"x {x0}->{ {r[5] for r in dying} }, y {y0}->{ {r[6] for r in dying} }")
        check("...does not fire, with the trigger held",
              not any(r[7] for r in dying))
        check("...and never lights HW1", not any(r[8] for r in dying)
              and all(r[4] in (0, 1) for r in dying),
              f"enable values seen: {sorted({r[4] for r in dying})}")

        # --- 3. the explosion itself -----------------------------------------
        ptrs = [r[2] for r in dying]
        check("HW0 wears the fireball, never a ship frame",
              all(BOOM_PTR <= p < BOOM_PTR + BOOM_FRAMES for p in ptrs),
              f"pointers seen: {sorted(set(ptrs))}")
        check("...in red, from HW0's own colour register",
              all(r[3] == BOOM_COL for r in dying),
              f"colours seen: {sorted({r[3] for r in dying})}")
        walk = [r[1] for r in dying]
        check("the frame index only ever advances -- the explosion cannot loop",
              all(b <= a + 1 for a, b in zip(walk, walk[1:]))
              and all(b >= a for a, b in zip(walk, walk[1:])),
              f"{sorted(set(walk))}")
        check("...and every one of the eight frames is shown",
              set(walk) == set(range(BOOM_FRAMES)), str(sorted(set(walk))))
        holds = {}
        for b in walk:
            holds[b] = holds.get(b, 0) + 1
        inner = [v for k, v in holds.items() if 0 < k < BOOM_FRAMES - 1]
        check(f"...each held for {BOOM_HOLD} frames",
              all(h == BOOM_HOLD for h in inner), str(sorted(holds.items())))

        # --- 4. ordinary death respawns, with the invulnerability blink -------
        tail = run_frames(mon, sym, 6, lambda: (
            rd1(mon, sym["plyDead"]), rd1(mon, sym["plyInvuln"]),
            rd1(mon, sym["plyPresPtr0"]), rd1(mon, sym["plyPresCol0"])))
        alive = [r for r in tail if not r[0]]
        check("the craft comes back when the fire goes out", bool(alive),
              str(tail))
        check("...wearing the ship again, in the ship's colour",
              alive[-1][2] < BOOM_PTR and alive[-1][3] == SHIP_COL,
              f"ptr ${alive[-1][2]:02x}, col {alive[-1][3]}")
        check("...and briefly invulnerable, so the respawn blink survives",
              alive[0][1] == INVULN, str(alive[0][1]))
        blink = run_frames(mon, sym, 12, lambda: rd1(mon, sym["plyVisible"]))
        check("...which really does blink", set(blink) == {0, 1}, str(blink))

        # --- 5. body collision ------------------------------------------------
        align(mon, sym)
        revive(mon, sym)
        poke(mon, sym["joyState"], JOY_IDLE)
        run_frames(mon, sym, 1)
        slots = free_slot(mon, sym)
        check("there is a free slot to place a body in", bool(slots), str(slots))
        slot = slots[0]

        # DRIVEN DIRECTLY, not through a whole frame. A full gameFrame also runs
        # ebulletPlayerTick, and a stationary ship under fire is killed by a
        # hostile bolt often enough that "the player died" would say nothing
        # about the body under test -- measured, all three negative cases failed
        # that way. playerBodyTick is the routine on trial, so it is the routine
        # that gets called.
        for otype, hp, name, should in (
                (TYPE_ENEMY, 4, "a LIVE enemy", True),
                (TYPE_ENEMY, 0, "a DYING enemy", False),
                (TYPE_EBULLET, 0, "a hostile projectile", False),
                (TYPE_PICKUP, 0, "a collectible token", False)):
            align(mon, sym)
            revive(mon, sym)
            saved = isolate(mon, sym)
            put_body(mon, sym, slot, otype, hp)
            lives0 = rd1(mon, sym["hudLives"])
            call(mon, sym, "playerBodyTick")
            hit = rd1(mon, sym["plyDead"]) == 1
            clear_slot(mon, sym, slot)
            restore(mon, sym, saved)
            check(f"{name} on the ship {'damages' if should else 'does NOT damage'}"
                  f" it", hit == should,
                  f"dead {rd1(mon, sym['plyDead'])}, lives {lives0}->"
                  f"{rd1(mon, sym['hudLives'])}")

        # the existing damage path: a ram costs a life and starts the SAME death
        align(mon, sym)
        revive(mon, sym, lives=3)
        saved = isolate(mon, sym)
        put_body(mon, sym, slot)
        call(mon, sym, "playerBodyTick")
        check("ramming goes through the existing damage path: a life, the "
              "fireball, no new state",
              rd1(mon, sym["hudLives"]) == 2 and rd1(mon, sym["plyDead"]) == 1
              and rd1(mon, sym["plyBoomFrame"]) == 0,
              f"lives {rd1(mon, sym['hudLives'])}, "
              f"dead {rd1(mon, sym['plyDead'])}")
        check("...and the enemy is NOT destroyed by the contact",
              rd1(mon, sym["objHP"] + slot) == 4,
              str(rd1(mon, sym["objHP"] + slot)))
        clear_slot(mon, sym, slot)
        restore(mon, sym, saved)

        # an invulnerable craft cannot be rammed
        align(mon, sym)
        revive(mon, sym)
        poke(mon, sym["plyInvuln"], 50)
        saved = isolate(mon, sym)
        put_body(mon, sym, slot)
        lives0 = rd1(mon, sym["hudLives"])
        call(mon, sym, "playerBodyTick")
        call(mon, sym, "playerBodyTick")
        check("an INVULNERABLE craft is not damaged by a body",
              rd1(mon, sym["plyDead"]) == 0
              and rd1(mon, sym["hudLives"]) == lives0,
              f"dead {rd1(mon, sym['plyDead'])}, lives {lives0}->"
              f"{rd1(mon, sym['hudLives'])}")
        clear_slot(mon, sym, slot)
        restore(mon, sym, saved)

        # --- 6. terminal death: same explosion, then GAME OVER ----------------
        align(mon, sym)
        revive(mon, sym, lives=1)
        poke(mon, sym["joyState"], JOY_IDLE)
        run_frames(mon, sym, 1)
        call(mon, sym, "playerTakeHit")
        align(mon, sym)
        check("the last life is fatal, but the state does not change yet",
              rd1(mon, sym["plyFatal"]) == 1 and rd1(mon, sym["plyDead"]) == 1
              and rd1(mon, sym["gsState"]) == GS_PLAYING,
              f"fatal {rd1(mon, sym['plyFatal'])}, "
              f"state {rd1(mon, sym['gsState'])}")
        fatal = run_frames(mon, sym, DEATH_LEN - 2, lambda: (
            rd1(mon, sym["plyDead"]), rd1(mon, sym["plyBoomFrame"]),
            rd1(mon, sym["plyPresPtr0"]), rd1(mon, sym["gsState"])))
        burning = [r for r in fatal if r[0]]
        check("the SAME explosion runs on the last life",
              set(r[1] for r in burning) == set(range(BOOM_FRAMES))
              and all(BOOM_PTR <= r[2] < BOOM_PTR + BOOM_FRAMES
                      for r in burning),
              f"frames {sorted(set(r[1] for r in burning))}")
        check("...and the lifecycle stays in GAME while it burns",
              all(r[3] == GS_PLAYING for r in burning))

        mon.cmd("delete")               # run_frames leaves the gameFrame
                                        # breakpoint armed; without this the
                                        # stop below is just the next frame
        set_bp(mon, sym["gsGameOverLoop"])
        mon.cmd("x")
        check("terminal death then reaches the restored GAME OVER state",
              rd1(mon, sym["gsState"]) == GS_GAMEOVER,
              str(rd1(mon, sym["gsState"])))
        check("...with HW0 hidden: no wreck is left on screen",
              rd1(mon, sym["plyVisible"]) == 0
              and rd1(mon, sym["plyPresEnable"]) == 0,
              f"visible {rd1(mon, sym['plyVisible'])}, "
              f"enable {rd1(mon, sym['plyPresEnable'])}")
        mon.cmd("delete")

        # --- 7. a short smoke -------------------------------------------------
        CATASTROPHIC = ("gameOverrun", "scrollLate",
                        "statPageMismatch", "statPtrMismatch")
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], JOY_IDLE)
        poke(mon, sym["gsState"], GS_PLAYING)
        align(mon, sym)
        revive(mon, sym, lives=250)
        poke(mon, sym["joyState"], JOY_RIGHT_FIRE)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        for n in CATASTROPHIC:
            poke(mon, sym[n], 0)
        free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        check("the game is still running after the smoke",
              rd1(mon, sym["gsState"]) == GS_PLAYING,
              str(rd1(mon, sym["gsState"])))
        for n in CATASTROPHIC:
            val = rd1(mon, sym[n])
            check(f"{n} is zero over the smoke run", val == 0, str(val))
        print(f"  info publishSkip over the smoke: "
              f"{rd1(mon, sym['publishSkip'])} (known limitation, not asserted)")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
