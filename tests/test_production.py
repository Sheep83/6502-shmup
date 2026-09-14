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
TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET = 0, 1, 2
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
        # TYPE_ENEMY and TYPE_EBULLET are legitimate; TYPE_NONE in an active
        # slot, or anything outside that pair, is pool corruption.
        bad = []
        for s in samples:
            for i in range(32):
                if i < MAX_OBJECTS and s["logActive"][i] and \
                        s["objType"][i] not in (TYPE_ENEMY, TYPE_EBULLET):
                    bad.append((i, s["objType"][i]))
        check("every active pool slot holds a known production type "
              "(enemy or hostile projectile)", not bad, f"{bad[:5]}")
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
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], 0xff & ~JOY_RIGHT)
        x0 = rd(mon, sym["plyX"], 2)
        bp = set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 5, lambda: None)
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        x1 = rd(mon, sym["plyX"], 2)
        poke(mon, sym["joyHold"], 0)
        dx = (x1[0] | x1[1] << 8) - (x0[0] | x0[1] << 8)
        check("the player actually moves under real input",
              dx == 5, f"{x0} -> {x1} (dx {dx})")

        # playerTakeHit is a self-contained state routine -- it sets plyInvuln
        # and increments plyHits and nothing else, with no dependency on frame
        # cadence -- so calling it directly (constraint #4's carve-out) is
        # legitimate here, unlike turretFireTick in test_turret_regression.py.
        hits0 = rd1(mon, sym["plyHits"])
        call(mon, sym, "playerTakeHit")
        invuln = rd1(mon, sym["plyInvuln"])
        hits1 = rd1(mon, sym["plyHits"])
        check("playerTakeHit raises invulnerability and the hit counter",
              invuln > 0 and hits1 == hits0 + 1, f"invuln {invuln} hits {hits1}")

        # Watch the whole invulnerability window run down. plyPresEnable must
        # ALWAYS be a legal value (0 or the full mask -- never a stray bit),
        # and blinking (0 while plyInvuln is counting down) is legitimate, not
        # "the player disappeared".
        bp = set_bp(mon, sym["gameFrame"])
        presence = step_n(mon, sym["frameCounter"], invuln + 10, lambda: (
            rd1(mon, sym["plyInvuln"]), rd1(mon, sym["plyPresEnable"])))
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        illegal = [(i, p) for i, p in presence
                   if p not in (0, PLAYER_SLOT_MASK)]
        check("plyPresEnable is always 0 or both reserved slots -- "
              "never a stray bit", not illegal, f"{illegal[:3]}")
        blinked = any(p == 0 for i, p in presence if i > 0)
        check("the player actually blinked while invulnerable "
              "(dark frames are the feature, not a fault)", blinked)
        final_invuln, final_pres = presence[-1]
        check("invulnerability expired and the ship ended up SOLID",
              final_invuln == 0 and final_pres == PLAYER_SLOT_MASK,
              f"invuln {final_invuln} pres {final_pres}")

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
