#!/usr/bin/env python3
"""Phase 6A: the FORMATION against the engine's own production loop.

test_movement_sim_engine.py grounds one object's movement by calling wmTick
directly. That proves the interpreter and nothing around it. This file proves
the part that only exists when the whole game is running:

    * WHICH FRAME each member is spawned on;
    * WHERE each member is placed -- the nine-bit X fan-out and the eight-bit
      Y one;
    * that a member does not move on its spawn frame;
    * WHICH FRAME src/enemy.asm frees it on.

The fixture is recorded by tests/wave_formation_trace.py, which boots the game
to worldProgress 0 and only watches. Nothing is called by hand, so the timing
is the director's own. Re-record after any change to src/waves.asm,
src/enemy.asm or the authored encounters:

    python3 tests/wave_formation_trace.py

ONLY THE RING WAVES ARE COMPARED. The other two authored triggers are DROPPER
appearances, and src/dropper.asm replaces the movement the wave just armed --
so those enemies are identified, counted and then deliberately left alone.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import migration_v6                                         # noqa: E402
import movement_sim as ms                                   # noqa: E402

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures/wave_formation_trace.json"
CANON = HERE / "levels/level1/level.v6.json"

PASS, FAIL = [], []


def ok(m, x=""):
    PASS.append(m)
    print(f"ok  - {m}" + (f"  [{x}]" if x else ""))


def check(m, c, x=""):
    if c:
        ok(m, x)
    else:
        FAIL.append(m)
        print(f"FAIL- {m}" + (f"  [{x}]" if x else ""))


def lives(frames):
    """Reconstruct each enemy's life from the per-frame slot dumps.

    A slot going from absent to present is a spawn; going from present to
    absent is a despawn. The pool reuses slots, so identity is (slot, the
    frame it appeared) rather than the slot alone.
    """
    out, open_ = [], {}
    prev = {}
    for f, snap in enumerate(frames):
        here = {int(k): v for k, v in snap["enemies"].items()}
        for slot, st in here.items():
            if slot not in prev:
                open_[slot] = {"slot": slot, "spawn": f, "states": []}
        for slot in list(open_):
            if slot in here:
                open_[slot]["states"].append(here[slot])
            else:
                open_[slot]["despawn"] = f
                out.append(open_.pop(slot))
        prev = here
    for rec in open_.values():
        rec["despawn"] = None
        out.append(rec)
    out.sort(key=lambda r: (r["spawn"], r["slot"]))
    return out


def main():
    if not FIXTURE.exists():
        print(f"FAIL- the formation fixture is missing: {FIXTURE}")
        print("      record it with: python3 tests/wave_formation_trace.py")
        return 1
    fx = json.loads(FIXTURE.read_text())
    frames = fx["frames"]
    proj = migration_v6.load_any(CANON).project
    waves = {w.id: w for w in proj.wave_definitions}

    all_lives = lives(frames)
    check("the recorded run contains enemy spawns at all",
          len(all_lives) > 0, f"{len(all_lives)} enemies")

    # ---- attribute each spawn using the DIRECTOR'S OWN instance state ----
    # wvIndex is the next member an instance will send, so an instance whose
    # wvIndex stepped between two frames spawned exactly that member of the
    # definition in its wvDef. Matching that way rather than by position is
    # deliberate: POSITION IS THE THING BEING PROVED, and a matcher keyed on
    # it could only ever agree with itself. It also identifies the Dropper
    # members, which src/dropper.asm moves the instant they are launched and
    # which a position matcher therefore could not place at all.
    order = [w.id for w in proj.wave_definitions]
    spawn_events = []
    for f in range(1, len(frames)):
        prev, here = frames[f - 1], frames[f]
        for i in range(len(here["wvIndex"])):
            # THE MEMBER SENT IS wvIndex - 1, and reading it that way rather
            # than as a delta is what makes this survive a RE-ARM. waveTick
            # starts a new wave and then runs the instances in the same frame,
            # so an instance that finished one wave at wvIndex 4 can be armed
            # for the next (wvIndex reset to 0) and send its member 0 (wvIndex
            # 1) all within one frame: the value jumps 4 -> 1 and a delta test
            # sees nothing. It is also not gated on wvActive, because
            # waveRunInstance clears the instance on the very frame it sends
            # the LAST member.
            armed = (here["wvActive"][i]
                     and (not prev["wvActive"][i]
                          or here["wvDef"][i] != prev["wvDef"][i]))
            if here["wvIndex"][i] > 0 and (
                    here["wvIndex"][i] != prev["wvIndex"][i] or armed):
                spawn_events.append((f, order[here["wvDef"][i]],
                                     here["wvIndex"][i] - 1))
    check("the director's instance state accounts for every enemy spawned",
          len(spawn_events) == len(all_lives),
          f"{len(spawn_events)} director spawns, {len(all_lives)} enemies")

    by_frame = {}
    for rec in all_lives:
        by_frame.setdefault(rec["spawn"], []).append(rec)
    claimed = {}
    for f, wid, m in spawn_events:
        pool = by_frame.get(f) or by_frame.get(f + 1) or []
        if pool:
            claimed[(wid, m)] = pool.pop(0)
    check("every director spawn is matched to an enemy that appeared",
          len(claimed) == len(spawn_events),
          f"{len(claimed)} of {len(spawn_events)}")

    trig_species = {t.wave_definition: t.species for t in proj.triggers}
    ring_waves = [wid for wid in waves if trig_species.get(wid) == "RING"]
    # NAMED WAVES USED TO BE LISTED HERE. The check is that the recording's RING
    # waves are exactly the project's RING waves -- which is what the sentence
    # always said and what a level may change at will.
    expected_ring = sorted(wid for wid, sp in trig_species.items() if sp == "RING")
    check("the RING waves in the recording are the ones the project says",
          sorted(ring_waves) == expected_ring,
          f"{sorted(ring_waves)} vs {expected_ring}")

    print()
    print("  wave    member  spawn frame           placement          "
          "life (frames)")
    mismatches = 0
    for wid in sorted(ring_waves):
        w = waves[wid]
        sim = ms.simulate_wave(proj, w)
        members = [m for m in range(w.count) if (wid, m) in claimed]
        check(f"{wid}: the engine spawned all {w.count} authored members",
              len(members) == w.count, f"{len(members)} seen")
        if not members or (wid, 0) not in claimed:
            continue
        base = claimed[(wid, 0)]["spawn"]
        for m in members:
            rec = claimed[(wid, m)]
            want_gap = sim.spawn_frames[m] - sim.spawn_frames[0]
            got_gap = rec["spawn"] - base
            lo, hi, y = ms.member_start(w, m)
            got = (rec["states"][0]["x"], rec["states"][0]["y"])
            want = (lo | (hi << 8), y)
            life = len(rec["states"])
            sim_life = len(sim.paths[m])
            good = got == want and got_gap == want_gap
            mismatches += 0 if good else 1
            print(f"  {wid:<8s}{m:4d}  {rec['spawn']:5d} (+{got_gap:3d}, "
                  f"want +{want_gap:3d})   engine {str(got):<11s} "
                  f"sim {str(want):<11s}  engine {life:3d} sim {sim_life:3d}")

        check(f"{wid}: every member is placed exactly where the simulator "
              f"puts it",
              all((claimed[(wid, m)]["states"][0]["x"],
                   claimed[(wid, m)]["states"][0]["y"])
                  == (lambda t: (t[0] | (t[1] << 8), t[2]))(ms.member_start(w, m))
                  for m in members))
        check(f"{wid}: the spawn interval is the authored {w.interval} frames",
              all(claimed[(wid, m)]["spawn"] - base
                  == sim.spawn_frames[m] - sim.spawn_frames[0]
                  for m in members),
              str([claimed[(wid, m)]["spawn"] - base for m in members]))

        # A member must NOT have moved on the frame it appeared: waveTick runs
        # after objectUpdateAll, so its first wmTick is a frame away.
        check(f"{wid}: no member moves on the frame it spawns",
              all(claimed[(wid, m)]["states"][0]["x"]
                  == (lambda t: t[0] | (t[1] << 8))(ms.member_start(w, m))
                  for m in members))

        # ---- the whole flight, frame by frame ---------------------------
        for m in members:
            rec = claimed[(wid, m)]
            eng = rec["states"]
            mine = sim.paths[m]
            n = min(len(eng), len(mine))
            bad = [i for i in range(n)
                   if (eng[i]["x"], eng[i]["y"], eng[i]["phase"])
                   != (mine[i].x, mine[i].y, mine[i].heading)]
            mismatches += len(bad)
            check(f"{wid} member {m}: {n} frames of flight match the engine "
                  f"exactly",
                  not bad,
                  "" if not bad else
                  f"first at frame {bad[0]}: engine "
                  f"{(eng[bad[0]]['x'], eng[bad[0]]['y'], eng[bad[0]]['phase'])} "
                  f"sim {(mine[bad[0]].x, mine[bad[0]].y, mine[bad[0]].heading)}")
            check(f"{wid} member {m}: the engine freed it on the frame the "
                  f"simulator does",
                  len(eng) == len(mine),
                  f"engine {len(eng)} frames, simulator {len(mine)}")

    # ---- the Dropper members are identified and left alone ---------------
    drop_waves = [wid for wid in waves if trig_species.get(wid) == "DROPPER"]
    seen_drop = sum(1 for (wid, _m) in claimed if wid in drop_waves)
    check("Dropper members are recognised by their authored start position "
          "and deliberately not compared",
          seen_drop > 0, f"{seen_drop} Dropper-wave members seen, 0 compared")

    print()
    check("ZERO formation mismatches against the production loop",
          mismatches == 0, str(mismatches))

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILURE(S):")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print(f"All {len(PASS)} formation-equivalence checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
