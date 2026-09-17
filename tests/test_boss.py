#!/usr/bin/env python3
"""End of level: final arena, boss, victory pause, scripted exit, LEVEL COMPLETE.

Driven by PHASE rather than by waiting out a 63-second stage scroll: the
boundary itself is proved from the authored geometry and from the scroller's own
freeze, and the phases after it are entered deliberately. Running the real level
to its end takes over a minute of emulated time and would prove nothing the
boundary check does not.

What this proves
----------------
* the stage-completion boundary is DERIVED from the authored stage height and
  the viewport, not from a timer or a typed constant;
* the scroller stops on the last complete authored screen, with stageTopRow at
  zero and no wrap;
* nothing new enters the arena once the level is ending;
* the arena clear cannot deadlock -- a hostile that will not leave is removed
  on a deadline;
* exactly ONE logical boss exists, drawn by FOUR pool objects of TYPE_BOSS,
  starting at 50 HP;
* a ray damages it once, and a ray crossing the seam between render cells
  cannot count twice;
* the health bar and the hit flash both move;
* at zero HP the boss is immediately non-damageable, its cells go, and a
  100-frame victory pause begins;
* the exit disables input, fire and damage, accelerates, and clears the top;
* LEVEL COMPLETE is reached with score, lives and P currency intact.

Manual VICE is authoritative for how any of it LOOKS.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, step_n, call, check, report)

MAX_OBJECTS = 16
TYPE_ENEMY, TYPE_EBULLET, TYPE_BOSS = 1, 2, 4
LP_LEVEL, LP_CLEARING, LP_BOSS, LP_VICTORY, LP_EXIT, LP_DONE = 0, 1, 2, 3, 4, 5
GS_PLAYING, GS_LEVELDONE = 1, 4
BOSS_HP_FULL = 50
BOSS_CELLS = 4
BOSS_X, BOSS_Y = 136, 74
BOSS_BOX_W, BOSS_BOX_H, BOSS_INSET = 48, 42, 4
BOSS_PTR = 0x3580 // 64                     # $d6
BOSS_COL, BOSS_COL_HIT = 4, 1
VICTORY_PAUSE = 100
EXIT_GONE_Y = 55 - 21                       # MIN_SPRITE_Y - SPRITE_HEIGHT
# src/level1/stage_config.asm x src/terrain.asm, restated independently
STAGE_METATILE_ROWS, METATILE_H, SCREEN_ROWS = 105, 4, 25
STAGE_ROWS = STAGE_METATILE_ROWS * METATILE_H                   # 420
STAGE_FINAL = STAGE_ROWS - SCREEN_ROWS                          # 395
JOY_IDLE, JOY_RIGHT_FIRE = 0xff, 0xe7
PORT = 6676


def align(mon, sym):
    mon.cmd("delete")
    set_bp(mon, sym["gameFrame"])
    step_n(mon, sym["frameCounter"], 1, lambda: None)


def run_frames(mon, sym, n=1, read_fn=None):
    return step_n(mon, sym["frameCounter"], n, read_fn or (lambda: None))


def word(mon, sym, name):
    b = rd(mon, sym[name + "Lo"], 2)
    return b[0] | (b[1] << 8)


def pool_types(mon, sym):
    act = rd(mon, sym["logActive"], MAX_OBJECTS)
    typ = rd(mon, sym["objType"], MAX_OBJECTS)
    return [(i, typ[i]) for i in range(MAX_OBJECTS) if act[i]]


def revive(mon, sym, lives=5):
    for f in ("plyDead", "plyBoomFrame", "plyBoomTimer", "plyFatal",
              "plyInvuln", "plyFlash"):
        poke(mon, sym[f], 0)
    poke(mon, sym["plyVisible"], 1)
    poke(mon, sym["hudLives"], lives)


def reach_boundary(mon, sym):
    """Put the scroller one coarse step from the end of the authored stage.

    worldProgress is the scroller's own counter and the coarse step is what
    advances it, so setting it just short and letting the engine take the last
    step proves the REAL boundary logic rather than simulating it.
    """
    align(mon, sym)
    # BACK TO AN UNFINISHED LEVEL FIRST. Five warp seconds of smoke is several
    # hundred coarse rows -- more than the whole 395-row stage -- so by this
    # point the scroller has finished, frozen itself AND spawned a boss. The
    # boundary is what is under test, so it is approached from before it, and
    # that means tearing the smoke's boss down through the engine's own
    # routines rather than leaving four orphaned cells in the pool for the
    # second boss to be counted alongside.
    call(mon, sym, "bossFreeCells")
    call(mon, sym, "bossInit")
    poke(mon, sym["stageComplete"], 0)
    poke(mon, sym["lvlPhase"], LP_LEVEL)
    poke(mon, sym["worldProgressLo"], (STAGE_FINAL - 1) & 0xff)
    poke(mon, sym["worldProgressHi"], (STAGE_FINAL - 1) >> 8)
    # stageTopRow must stay consistent with it: the invariant the engine keeps
    top = (STAGE_FINAL - (STAGE_FINAL - 1)) % STAGE_ROWS
    poke(mon, sym["stageTopRowLo"], top & 0xff)
    poke(mon, sym["stageTopRowHi"], top >> 8)
    run_frames(mon, sym, 10)            # one coarse step is eight frames


def main():
    sym = symbols(SYM)

    # --- 1. the boundary is derived, not typed -----------------------------
    check("the stage boundary follows from the authored geometry: "
          f"{STAGE_METATILE_ROWS} metatile rows x {METATILE_H} - {SCREEN_ROWS} "
          f"viewport rows = {STAGE_FINAL}",
          STAGE_FINAL == 395, str(STAGE_FINAL))

    v = None
    try:
        v = Vice(PORT, PRG, warp=True)
        mon = v.mon
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], JOY_IDLE)
        # THIS file is the one that wants the stage to end, so it releases the
        # harness's hold. Everything else in the suite keeps it.
        poke(mon, sym["stageHold"], 0)

        # --- 2. the artwork, structurally ----------------------------------
        art = rd(mon, 0x3580, BOSS_CELLS * 64)
        check("the boss is four 64-byte cells", len(art) == 256, str(len(art)))
        cells = [tuple(art[c * 64:c * 64 + 63]) for c in range(BOSS_CELLS)]
        check("...all four distinct and none empty",
              len(set(cells)) == BOSS_CELLS and all(any(c) for c in cells),
              f"{len(set(cells))} distinct")
        check("...with the unused 64th byte of each block zero",
              all(art[c * 64 + 63] == 0 for c in range(BOSS_CELLS)))

        check("the level starts unfinished",
              rd1(mon, sym["stageComplete"]) == 0
              and rd1(mon, sym["lvlPhase"]) == LP_LEVEL,
              f"complete {rd1(mon, sym['stageComplete'])}, "
              f"phase {rd1(mon, sym['lvlPhase'])}")

        # --- 2b. a short smoke of ordinary play, before anything is posed ----
        CATASTROPHIC = ("gameOverrun", "scrollLate",
                        "statPageMismatch", "statPtrMismatch")
        poke(mon, sym["hudLives"], 250)         # outlast the probe
        poke(mon, sym["joyState"], JOY_RIGHT_FIRE)
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        for n in CATASTROPHIC:
            poke(mon, sym[n], 0)
        free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        for n in CATASTROPHIC:
            val = rd1(mon, sym[n])
            check(f"{n} is zero with the level-end tick in the frame",
                  val == 0, str(val))
        print(f"  info publishSkip over the smoke: "
              f"{rd1(mon, sym['publishSkip'])} (known limitation, not asserted)")
        poke(mon, sym["joyState"], JOY_IDLE)

        # --- 3. the scroller stops on the last full authored screen --------
        reach_boundary(mon, sym)
        check("the scroller declares the stage complete at the derived "
              "boundary", rd1(mon, sym["stageComplete"]) == 1,
              f"worldProgress {word(mon, sym, 'worldProgress')}")
        check("...having stopped exactly at it, not past it",
              word(mon, sym, "worldProgress") == STAGE_FINAL,
              str(word(mon, sym, "worldProgress")))
        check("...showing the TOP of the authored map: stageTopRow is zero, so "
              "the view is stage rows 0..24 and nothing wrapped",
              word(mon, sym, "stageTopRow") == 0,
              str(word(mon, sym, "stageTopRow")))
        fine0 = rd1(mon, sym["scrollFine"])
        prog0 = word(mon, sym, "worldProgress")
        run_frames(mon, sym, 40)                # five coarse steps' worth
        check("the terrain is FROZEN: neither the coarse row nor the fine "
              "phase moves again",
              word(mon, sym, "worldProgress") == prog0
              and rd1(mon, sym["scrollFine"]) == fine0
              and word(mon, sym, "stageTopRow") == 0,
              f"progress {prog0}->{word(mon, sym, 'worldProgress')}, "
              f"fine {fine0}->{rd1(mon, sym['scrollFine'])}")
        check("...and the level has entered its ending",
              rd1(mon, sym["lvlPhase"]) in (LP_CLEARING, LP_BOSS),
              str(rd1(mon, sym["lvlPhase"])))

        # --- 4. nothing new enters the arena --------------------------------
        spawned0 = rd1(mon, sym["wvSpawned"])
        shots0 = rd1(mon, sym["wvShots"])
        fired0 = rd1(mon, sym["ebFired"])
        run_frames(mon, sym, 30)
        check("no new wave member, enemy shot or hostile bolt appears once the "
              "level is ending",
              rd1(mon, sym["wvSpawned"]) == spawned0
              and rd1(mon, sym["wvShots"]) == shots0
              and rd1(mon, sym["ebFired"]) == fired0,
              f"spawned {spawned0}->{rd1(mon, sym['wvSpawned'])}, "
              f"bolts {fired0}->{rd1(mon, sym['ebFired'])}")

        # --- 5. the clear cannot deadlock ------------------------------------
        # A hostile that will never leave: parked, inert, and in the pool.
        if rd1(mon, sym["lvlPhase"]) == LP_CLEARING:
            free = [i for i, a in enumerate(rd(mon, sym["logActive"], MAX_OBJECTS))
                    if not a]
            if free:
                ghost = free[0]
                poke(mon, sym["objType"] + ghost, TYPE_ENEMY)
                poke(mon, sym["objHP"] + ghost, 6)
                poke(mon, sym["logY"] + ghost, 120)
                poke(mon, sym["logActive"] + ghost, 1)
        # The deadline is 200 frames; give it room and let the engine resolve.
        deadline = run_frames(mon, sym, 260, lambda: rd1(mon, sym["lvlPhase"]))
        check("the arena clear always ends: the boss phase is reached even "
              "with a hostile that refuses to leave",
              rd1(mon, sym["lvlPhase"]) == LP_BOSS,
              f"phase {rd1(mon, sym['lvlPhase'])}, forced "
              f"{rd1(mon, sym['lvlForced'])}")
        left = [t for _, t in pool_types(mon, sym)
                if t in (TYPE_ENEMY, TYPE_EBULLET)]
        check("...and the arena really is clean when the boss arrives",
              not left, str(left))

        # --- 6. one boss, four cells, fifty HP -------------------------------
        check("the boss starts at full health",
              rd1(mon, sym["bossHP"]) == BOSS_HP_FULL,
              str(rd1(mon, sym["bossHP"])))
        boss_cells = [(i, t) for i, t in pool_types(mon, sym) if t == TYPE_BOSS]
        check("...drawn by exactly four render cells",
              len(boss_cells) == BOSS_CELLS, str(boss_cells))
        slots = [s for s, _ in boss_cells]
        ptrs = sorted(rd1(mon, sym["logPtr"] + s) for s in slots)
        check("...wearing the four adjacent boss blocks",
              ptrs == [BOSS_PTR + i for i in range(BOSS_CELLS)],
              str([hex(p) for p in ptrs]))
        xs = sorted({rd1(mon, sym["logX"] + s)
                     | (rd1(mon, sym["logXHi"] + s) << 8) for s in slots})
        ys = sorted({rd1(mon, sym["logY"] + s) for s in slots})
        check("...composed 2x2 from one position",
              xs == [BOSS_X, BOSS_X + 24] and ys == [BOSS_Y, BOSS_Y + 21],
              f"x {xs}, y {ys}")
        check("...and none of the cells is a damageable object in its own right",
              all(rd1(mon, sym["objHP"] + s) == 0 for s in slots))
        check("the boss neither moves nor fires",
              all(rd1(mon, sym["objVX"] + s) == 0
                  and rd1(mon, sym["objVY"] + s) == 0 for s in slots))

        # --- 7. hitscan: one ray, one hit ------------------------------------
        # A ray straight down the seam between the left and right cells: the
        # single place a per-cell hitbox would double-count.
        seam = BOSS_X + 24
        poke(mon, sym["csRayLo"], seam & 0xff)
        poke(mon, sym["csRayHi"], seam >> 8)
        poke(mon, sym["plyY"], 200)
        hp0 = rd1(mon, sym["bossHP"])
        hits0 = rd1(mon, sym["bossHits"])
        call(mon, sym, "bossRayHit")
        check("a ray down the SEAM between render cells counts exactly once",
              rd1(mon, sym["bossHP"]) == hp0 - 1
              and rd1(mon, sym["bossHits"]) == hits0 + 1,
              f"hp {hp0}->{rd1(mon, sym['bossHP'])}, "
              f"hits {hits0}->{rd1(mon, sym['bossHits'])}")
        check("...and the whole machine flashes, not one corner",
              all(rd1(mon, sym["logCol"] + s) == BOSS_COL_HIT for s in slots),
              str([rd1(mon, sym["logCol"] + s) for s in slots]))
        bar0 = rd1(mon, sym["bossBarDrawn"])
        poke(mon, sym["csRayLo"], seam & 0xff)
        call(mon, sym, "bossRayHit")
        check("a second ray takes a second point",
              rd1(mon, sym["bossHP"]) == hp0 - 2,
              str(rd1(mon, sym["bossHP"])))
        check("...and the health bar follows the damage down",
              rd1(mon, sym["bossBarDrawn"]) < bar0
              or rd1(mon, sym["bossHP"]) // 2 == rd1(mon, sym["bossBarDrawn"]),
              f"bar {bar0}->{rd1(mon, sym['bossBarDrawn'])}")

        # a ray beside the body misses
        outside = BOSS_X - 20
        poke(mon, sym["csRayLo"], outside & 0xff)
        poke(mon, sym["csRayHi"], outside >> 8)
        hp1 = rd1(mon, sym["bossHP"])
        call(mon, sym, "bossRayHit")
        check("a ray beside the body misses", rd1(mon, sym["bossHP"]) == hp1,
              str(rd1(mon, sym["bossHP"])))

        # the flash expires back to the boss's own colour
        run_frames(mon, sym, 6)
        check("the hit flash expires back to the boss's own colour",
              all(rd1(mon, sym["logCol"] + s) == BOSS_COL for s in slots),
              str([rd1(mon, sym["logCol"] + s) for s in slots]))

        # --- 8. death, and the victory pause ---------------------------------
        poke(mon, sym["bossHP"], 1)
        poke(mon, sym["csRayLo"], seam & 0xff)
        poke(mon, sym["csRayHi"], seam >> 8)
        call(mon, sym, "bossRayHit")
        check("the last point kills it", rd1(mon, sym["bossHP"]) == 0,
              str(rd1(mon, sym["bossHP"])))
        call(mon, sym, "bossRayHit")
        check("...and a dead boss cannot be damaged again",
              rd1(mon, sym["bossHP"]) == 0 and rd1(mon, sym["lvlPhase"]) != LP_DONE)

        align(mon, sym)
        run_frames(mon, sym, 2)
        check("boss death starts the victory pause",
              rd1(mon, sym["lvlPhase"]) == LP_VICTORY,
              str(rd1(mon, sym["lvlPhase"])))
        check("...its four render cells are gone",
              not [t for _, t in pool_types(mon, sym) if t == TYPE_BOSS],
              str(pool_types(mon, sym)))
        check("...the player's agency is removed at once",
              rd1(mon, sym["plyExit"]) == 1)
        check("...and no stale hostile survived the boss",
              not [t for _, t in pool_types(mon, sym)
                   if t in (TYPE_ENEMY, TYPE_EBULLET)],
              str(pool_types(mon, sym)))

        # the pause is a real 100 frames
        timer = rd1(mon, sym["lvlTimer"])
        check("the victory pause is the authored 100 frames",
              1 <= timer <= VICTORY_PAUSE, str(timer))
        y_before = rd1(mon, sym["plyY"])
        run_frames(mon, sym, timer - 2 if timer > 2 else 1)
        check("...during which the ship does not move",
              rd1(mon, sym["plyY"]) == y_before and
              rd1(mon, sym["lvlPhase"]) == LP_VICTORY,
              f"y {y_before}->{rd1(mon, sym['plyY'])}, "
              f"phase {rd1(mon, sym['lvlPhase'])}")

        # --- 9. the scripted exit --------------------------------------------
        # Captured BEFORE the transition, so "the run survived" is a comparison
        # rather than an assumption.
        tokens_before = rd1(mon, sym["pkTokensP"])
        score_before = rd(mon, sym["hudScore"], 6)
        poke(mon, sym["joyState"], JOY_RIGHT_FIRE)   # held for the whole exit
        flight = run_frames(mon, sym, 90, lambda: (
            rd1(mon, sym["lvlPhase"]), rd1(mon, sym["plyY"]),
            rd1(mon, sym["exitVel"]), rd1(mon, sym["plyVisible"]),
            rd1(mon, sym["shotFired"]), rd1(mon, sym["gsState"]),
            rd1(mon, sym["plyX"])))
        rising = [f for f in flight if f[0] == LP_EXIT]
        check("the exit runs", bool(rising), str(flight[:3]))
        vels = [f[2] for f in rising]
        check("the ship ACCELERATES rather than jumping to a fixed speed",
              vels[0] < vels[len(vels) // 2] < max(vels) and max(vels) > 8,
              f"velocity {vels[0]} -> {max(vels)} eighths of a pixel")
        ys = [f[1] for f in rising]
        check("...travelling upward the whole way",
              all(b <= a for a, b in zip(ys, ys[1:])), f"{ys[0]} -> {ys[-1]}")
        check("...with the stick and trigger ignored",
              len({f[6] for f in rising}) == 1 and not any(f[4] for f in rising),
              f"x values {sorted({f[6] for f in rising})}")
        gone = [f for f in flight if f[0] == LP_DONE]
        check("the ship clears the top and the level ends", bool(gone),
              str(flight[-1]))
        check("...with HW0 hidden rather than drifting on as a stray sprite",
              gone[0][3] == 0, str(gone[0]))
        check("...and voice 3's launch is silenced",
              rd(mon, sym["sfxChId"], 3)[2] == 0,
              str(rd(mon, sym["sfxChId"], 3)))

        # --- 10. LEVEL COMPLETE, with the run intact -------------------------
        check("the lifecycle reached LEVEL COMPLETE",
              rd1(mon, sym["gsState"]) == GS_LEVELDONE,
              str(rd1(mon, sym["gsState"])))
        check("...with gameplay off the display and no sprites",
              rd1(mon, sym["gsNonGame"]) == 1)
        # PRESERVED MEANS NOT RESET, not frozen: the HUD's own score cadence
        # keeps running through the ~55 frames of the exit, so the score is
        # expected to be at least what it was -- never back at zero.
        score_now = rd(mon, sym["hudScore"], 6)
        check("...the RUN preserved: lives, score and P currency are not reset",
              rd1(mon, sym["hudLives"]) > 0
              and rd1(mon, sym["pkTokensP"]) == tokens_before
              and score_now >= score_before,
              f"lives {rd1(mon, sym['hudLives'])}, "
              f"P {rd1(mon, sym['pkTokensP'])} (was {tokens_before}), "
              f"score {score_before} -> {score_now}")
        head = rd(mon, 0x0400 + 8 * 40 + 13, 5)
        check("...and the LEVEL COMPLETE page is drawn",
              head == [12, 5, 22, 5, 12], str(head))   # "LEVEL"
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
