#!/usr/bin/env python3
"""Production smoke — does ordinary play stay healthy, end to end.

One VICE session proves several closely related things about the ACTUAL
production loop, under ORDINARY conditions (the real enemy spawner and real
turrets running, nothing posed or faked), rather than one migration slice at a
time against synthetic fixtures. Constraint #4: cadence/lifecycle/publication
behaviour is watched on a free-running or per-frame-stepped machine, never
inferred from a single direct call.

What this proves
-----------------
B. production health   -- gameOverrun, publishSkip, schedBuildDefer,
                           scrollLate and edgeLate all stay at zero over a
                           representative stretch of ordinary play.
C. scroll continuity    -- worldProgress only increases and stageTopRow tracks
                           it by the documented relation
                           (STAGE_START_ROW - worldProgress) mod STAGE_ROWS on
                           every sampled frame, so a stuck, reversed or
                           corrupted scroll cannot hide.
D. object lifecycle     -- the pool cycles (spawns AND despawns happen), every
                           active slot names a KNOWN production type (an enemy
                           bullet is an ordinary object now, not a special
                           case), and live membership never exceeds the pool.
E. player / collision   -- the player moves under real input, and a hit
                           (delivered through the production playerTakeHit --
                           a self-contained state routine, not a cadence-
                           dependent one) leaves plyPresEnable always a legal
                           value and eventually SOLID again. Blinking is not
                           "the player disappeared".
G. renderer sanity      -- under ordinary load, the adopted schedule stays
                           inside its allocated size, every admitted sprite Y
                           is inside the production band, and the two
                           page/pointer coherence counters never move. This is
                           NOT a re-certification of the legality-window
                           arithmetic (see make test-renderer-full for that);
                           it only asks "is anything obviously wrong".

What this does NOT prove
-------------------------
Anything visual. It does not replay the historical migration ladder (Slices
A/A'/B/C/D, the terrain/turret archaeology, or the exhaustive batch-window
sweep) -- see the `legacy-tests-retired` tag for that, and
`make test-engine-full` / `make test-renderer-full` for the two pieces of it
still considered worth keeping on demand.

One VICE launch.
"""
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                      free_run, step_n, call, check, report)

sym = symbols(SYM)

# --- the contract, restated independently of the assembler ------------------
MAX_OBJECTS   = 16
MAX_SCHED     = 24
MIN_SPRITE_Y, MAX_SPRITE_Y = 55, 226
STAGE_ROWS       = 420                  # src/terrain.asm TERRAIN_STAGE_ROWS
SCREEN_ROWS      = 25
STAGE_START_ROW  = STAGE_ROWS - SCREEN_ROWS
TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET, TYPE_PICKUP = 0, 1, 2, 3
PLAYER_SLOT_MASK = 0b00000011


def frames(mon, bp_addr, n):
    """n DISTINCT frames at a per-frame breakpoint, one dict of raw reads per
    frame. gameFrame runs exactly once per displayed frame -- see
    src/main.asm -- so this is real per-frame sampling, not a guess at
    monitor timing. Uses step_n (see harness.py) rather than a bare
    `for _ in range(n): mon.cmd("x")` loop, which cannot tell a genuine step
    from a stalled/duplicate monitor reply."""
    def one():
        return {
            "world": rd(mon, sym["worldProgressLo"], 2),
            "top":   rd(mon, sym["stageTopRowLo"], 2),
            "logCount": rd1(mon, sym["logCount"]),
            "logActive": rd(mon, sym["logActive"], 32),
            "objType":   rd(mon, sym["objType"], MAX_OBJECTS),
        }
    out = step_n(mon, sym["frameCounter"], n, one)
    return out


def main():
    print("=== production smoke ===")
    v = None
    try:
        v = Vice(6651, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")

        # --- B: production health, over a representative stretch -----------
        print("\n--- B. production health ---")
        for name in ("gameOverrun", "publishSkip", "schedBuildDefer",
                     "scrollLate", "edgeLate"):
            poke(mon, sym[name], 0)
        ok = free_run(mon, sym["frameCounter"], 10)
        check("the machine free-ran the full health window", ok)
        for name in ("gameOverrun", "publishSkip", "schedBuildDefer",
                     "scrollLate", "edgeLate"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero over 10s of ordinary play", got == 0,
                  str(got))

        # --- per-frame sample, feeding C, D and part of G -------------------
        # gameFrame is the once-per-frame call site (main.asm), so a
        # breakpoint there samples exactly one instant per displayed frame --
        # not a guess at monitor round-trip timing.
        bp = set_bp(mon, sym["gameFrame"])
        samples = frames(mon, bp, 150)
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        # --- C: scroll / terrain continuity ---------------------------------
        print("\n--- C. scroll / terrain continuity ---")
        worlds = [s["world"][0] | (s["world"][1] << 8) for s in samples]
        tops   = [s["top"][0]   | (s["top"][1] << 8)   for s in samples]
        check("worldProgress only ever increases",
              all(b >= a for a, b in zip(worlds, worlds[1:])),
              f"min delta {min(b - a for a, b in zip(worlds, worlds[1:]))}")
        check("worldProgress genuinely advanced over the sample window",
              worlds[-1] > worlds[0], f"{worlds[0]} -> {worlds[-1]}")
        mismatches = [(w, t) for w, t in zip(worlds, tops)
                      if t != (STAGE_START_ROW - w) % STAGE_ROWS]
        check("stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS "
              "on every sampled frame", not mismatches,
              f"{mismatches[:3]} of {len(samples)} samples")

        # --- D: object lifecycle --------------------------------------------
        print("\n--- D. object lifecycle ---")
        counts = [s["logCount"] for s in samples]
        check("live object count never exceeds the pool",
              all(0 <= c <= MAX_OBJECTS for c in counts),
              f"{min(counts)}..{max(counts)}")
        check("the pool actually cycled during ordinary play "
              "(not frozen at one population)",
              len(set(counts)) > 1, f"{sorted(set(counts))}")
        # Every ACTIVE slot must carry a type this engine knows about. An
        # enemy bullet is an ordinary object now (not a special case), so both
        # TYPE_ENEMY, TYPE_EBULLET and TYPE_PICKUP are legitimate; TYPE_NONE in an active
        # slot, or anything outside that pair, is pool corruption.
        bad = []
        for s in samples:
            for i in range(32):
                if i < MAX_OBJECTS and s["logActive"][i] and \
                        s["objType"][i] not in (TYPE_ENEMY, TYPE_EBULLET,
                                                TYPE_PICKUP):
                    bad.append((i, s["objType"][i]))
        check("every active pool slot holds a known production type "
              "(enemy, hostile projectile or pickup)", not bad, f"{bad[:5]}")
        active_counts = [sum(s["logActive"][:MAX_OBJECTS]) for s in samples]
        mism = [(a, c) for a, c in zip(active_counts, counts) if a != c]
        check("logCount agrees with the number of active slots on every "
              "sampled frame", not mism, f"{mism[:3]}")

        # --- E: player / collision -------------------------------------------
        print("\n--- E. player / collision ---")
        # A FIXED small number of frames, not a wall-clock free-run: the
        # player starts at X=160 (PLAYER_START_X) and moves one pixel a frame,
        # so a warp-speed free-run risks reaching the clamp boundary and
        # reporting "did not move" for a player that is actually clamped, not
        # broken. Stepping five frames at the once-per-frame breakpoint is
        # both deterministic and immune to host warp speed.
        JOY_RIGHT = 0b00001000           # active-low CIA convention, see
                                          # src/player.asm's JOY_RIGHT test
        # BOTH ENDS SAMPLED AT THE SAME POINT IN THE FRAME. The first draft read
        # x0 wherever the machine happened to be stopped and x1 at a gameFrame
        # entry, so the two bracketed either four or five playerTick runs
        # depending on whether the starting stop was before or after that
        # frame's movement -- the same build measured dx 5 and then dx 4 on
        # consecutive runs. Sampling x0 at a gameFrame entry too makes the
        # interval exactly the number of frames stepped.
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], 0xff & ~JOY_RIGHT)
        # MEASURED AGAINST THE FRAME COUNTER, not against the number of steps
        # requested. step_n guarantees DISTINCT frames, not CONSECUTIVE ones --
        # under load the monitor can miss a stop, and an earlier draft that
        # asserted "one pixel per step" duly failed with a delta of 0 and then
        # of 2 on a machine whose movement was provably exactly one pixel a
        # frame throughout. Carrying the frame number makes the interval
        # self-describing and the assertion exact either way.
        # A COHERENT SAMPLE, or none. frameCounter and plyX are two separate
        # monitor commands, and `x` returns on a prompt echo rather than on the
        # actual stop -- so on a machine that did not really halt, the pair can
        # straddle a frame boundary and report plyX from before a move with the
        # frame number from after it. That reads as a frame in which the player
        # did not move, and it is the harness, not the game: the same build
        # steps sixty frames with dx equal to the frames elapsed every time.
        # Reading the frame number either side of plyX detects the straddle.
        def coherent(tries=6):
            for _ in range(tries):
                f0 = rd(mon, sym["frameCounter"], 2)
                x = rd(mon, sym["plyX"], 2)
                f1 = rd(mon, sym["frameCounter"], 2)
                if f0 == f1:
                    return (f0, x)
            return (f0, x)                  # give up; the check will show it

        # A DEAD CRAFT DOES NOT STEER, by design -- see
        # reports/player-death-fireball-collision.md -- so this sample starts
        # from one that is alive. Without it a hostile bolt landing just before
        # the window turns "does the player move" into a coin toss.
        for f in ("plyDead", "plyBoomFrame", "plyBoomTimer", "plyFatal"):
            poke(mon, sym[f], 0)
        poke(mon, sym["plyVisible"], 1)
        poke(mon, sym["hudLives"], 200)

        bp = set_bp(mon, sym["gameFrame"])
        xs = step_n(mon, sym["frameCounter"], 6, coherent)
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        poke(mon, sym["joyHold"], 0)
        fr = lambda s: s[0][0] | s[0][1] << 8
        px = lambda s: s[1][0] | s[1][1] << 8
        dframes = (fr(xs[-1]) - fr(xs[0])) & 0xffff
        dx = px(xs[-1]) - px(xs[0])
        check("the player actually moves under real input",
              dx > 0, f"x {px(xs[0])} -> {px(xs[-1])} over {dframes} frames")
        check("...at exactly one pixel per frame, the movement model's rate",
              dx == dframes, f"moved {dx} px in {dframes} frames")
        offenders = [(((fr(b) - fr(a)) & 0xffff), px(b) - px(a))
                     for a, b in zip(xs, xs[1:])
                     if px(b) - px(a) != ((fr(b) - fr(a)) & 0xffff)]
        check("...on every single sampled interval", not offenders,
              f"(frames, px) mismatches: {offenders}")

        # playerTakeHit is a self-contained state routine with no dependency on
        # frame cadence, so calling it directly (constraint #4's carve-out) is
        # legitimate here, unlike turretFireTick in test_turret_regression.py.
        #
        # WHAT IT DOES CHANGED. It used to raise plyInvuln and nothing else: a
        # hit was a hundred frames of blinking on an intact ship. It now
        # DESTROYS the craft -- plyDead, a one-shot fireball, and the
        # invulnerability moved to the respawn at the far end of it. The hit
        # counter is unchanged, and the invulnerability is asserted below where
        # it now happens. See reports/player-death-fireball-collision.md.
        for f in ("plyDead", "plyBoomFrame", "plyBoomTimer", "plyFatal",
                  "plyInvuln"):
            poke(mon, sym[f], 0)
        poke(mon, sym["hudLives"], 5)
        hits0 = rd1(mon, sym["plyHits"])
        call(mon, sym, "playerTakeHit")
        hits1 = rd1(mon, sym["plyHits"])
        check("playerTakeHit destroys the craft and counts the hit",
              rd1(mon, sym["plyDead"]) == 1 and hits1 == hits0 + 1,
              f"dead {rd1(mon, sym['plyDead'])} hits {hits1}")

        # Run the fireball out, so the window watched below is the RESPAWN's
        # invulnerability -- which is the thing this section is really about.
        # step_n needs a breakpoint armed, and the sampling above deleted them.
        poke(mon, sym["plyBoomFrame"], 7)
        poke(mon, sym["plyBoomTimer"], 5)
        bp = set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 3, lambda: None)
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        invuln = rd1(mon, sym["plyInvuln"])
        check("...and the respawn that follows is invulnerable",
              invuln > 0, f"invuln {invuln}")

        # Watch the whole invulnerability window run down. plyPresEnable must
        # ALWAYS be a legal value (0 or the full mask -- never a stray bit),
        # and blinking (0 while plyInvuln is counting down) is legitimate, not
        # "the player disappeared".
        bp = set_bp(mon, sym["gameFrame"])
        presence = step_n(mon, sym["frameCounter"], invuln + 10, lambda: (
            rd1(mon, sym["plyInvuln"]), rd1(mon, sym["plyPresEnable"])))
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        # HW1 IS NO LONGER ALWAYS ON. It carries the muzzle flash now and is
        # enabled only for the two frames after an accepted shot, so the legal
        # values are "nothing", "the craft" and "the craft plus its flash".
        # What must never appear is a bit outside the player's own two slots:
        # that would mean the player had reached into the gameplay mux.
        illegal = [(i, p) for i, p in presence
                   if p & ~PLAYER_SLOT_MASK & 0xff]
        check("plyPresEnable never sets a bit outside the player's two slots",
              not illegal, f"{illegal[:3]}")
        # HW1 is an OVERLAY on the craft, so it can never be the only slot lit:
        # any non-zero enable must include HW0. That is what makes "the player
        # is hidden" a single test rather than two that could disagree.
        orphan = [(i, bin(p)) for i, p in presence if p and not p & 0b1]
        check("HW1 is never enabled without the craft it overlays",
              not orphan, f"{orphan[:3]}")
        blinked = any(p == 0 for i, p in presence if i > 0)
        check("the player actually blinked while invulnerable "
              "(dark frames are the feature, not a fault)", blinked)
        # SOLID NOW MEANS THE CRAFT'S OWN SLOT, not both. HW1 stopped being a
        # permanently-enabled second layer when it became the muzzle flash: it
        # is lit only for the two frames after an accepted shot, so a ship at
        # rest ends the blink with HW0 alone.
        final_invuln, final_pres = presence[-1]
        check("invulnerability expired and the ship ended up SOLID",
              final_invuln == 0 and final_pres & 0b1,
              f"invuln {final_invuln} pres {bin(final_pres)}")

        # --- G: renderer sanity, under this same ordinary load --------------
        print("\n--- G. renderer sanity (ordinary load, not re-certification) ---")
        cur = rd1(mon, sym["schedCurrent"])
        check("schedCurrent names one of the two real buffers", cur in (0, 1),
              str(cur))
        n = rd1(mon, sym["schedEntries"] + cur)
        check("the adopted schedule fits its allocated size",
              0 <= n <= MAX_SCHED, str(n))
        if n:
            ys = rd(mon, sym["schedY"] + cur * MAX_SCHED, n)
            check("every admitted sprite Y is inside the production band",
                  all(MIN_SPRITE_Y <= y <= MAX_SPRITE_Y for y in ys),
                  f"{min(ys)}..{max(ys)}")
        pgmis = rd1(mon, sym["statPageMismatch"])
        ptrmis = rd1(mon, sym["statPtrMismatch"])
        check("no page/pointer coherence fault under ordinary load",
              pgmis == 0 and ptrmis == 0, f"page {pgmis} ptr {ptrmis}")
        ovf = rd1(mon, sym["statOverflow"])
        check("the schedule never overflowed under ordinary load",
              ovf == 0, str(ovf))
    finally:
        if v: v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
