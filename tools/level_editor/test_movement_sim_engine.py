#!/usr/bin/env python3
"""Phase 6A's acceptance test: the Python simulator against the REAL 6502.

THE ONLY TEST HERE THAT CAN FAIL FOR AN INTERESTING REASON. Everything else
in this phase is Python checking Python, which can only ever prove that the
simulator agrees with the assumptions that were written into it. This file
compares it, field by field and frame by frame, with state recorded from the
engine's own wmEnterStage and wmTick running on a real 6502.

The fixture is produced by tests/movement_trace.py, which drives the shipped
routines through the VICE monitor and adds nothing to the engine. Re-record it
after ANY change to src/movement.asm or to the authored programs:

    python3 tests/movement_trace.py

EVERY AUTHORITATIVE FIELD IS COMPARED, not just the position: the mode, the
stage cursor, the heading, both timers, both velocities and both sub-pixel
remainders. A simulator that happened to land on the right pixel by a
different route would be wrong the moment the author edited a stage, and the
remainders are exactly where such a route would show.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract_v2 as C                                     # noqa: E402
import migration_v6                                         # noqa: E402
import movement_sim as ms                                   # noqa: E402
import project_v6                                           # noqa: E402

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures/movement_engine_trace.json"
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


MODE_OF = {v: k for k, v in C.MOVEMENT_KINDS.items()}
BYTE_KIND = {0: "STRAIGHT", 1: "ARC", 2: "ARC_MIRROR", 3: "EXIT", 4: "HOLD"}


def stages_from_bytes(raw, count):
    """The fixture's own program bytes -> v6 stages.

    THE BYTES ARE READ BACK OUT OF THE MACHINE by the recorder, so a case can
    never describe a program the engine did not actually have loaded. Rebuilding
    the semantic stages from them rather than from the editor project is what
    makes the synthetic cases -- which exist nowhere in the project -- testable
    by the same path as the production ones.
    """
    out = []
    for i in range(count):
        kind_b, arg, b2, b3 = raw[4 * i: 4 * i + 4]
        kind = BYTE_KIND[kind_b]
        if kind == "EXIT":
            out.append(project_v6.MovementStage(kind="EXIT"))
        elif kind in C.ARC_KINDS:
            head = "CONT" if b3 == C.WM_HEAD_CONT else b3
            out.append(project_v6.MovementStage(
                kind=kind, steps=arg, frames_per_step=b2, entry_heading=head))
        else:
            out.append(project_v6.MovementStage(
                kind=kind, frames=arg, vx=ms.s8(b2), vy=ms.s8(b3)))
    return out


def program_length(raw):
    """How many records before and including the first EXIT."""
    for i in range(len(raw) // 4):
        if raw[4 * i] == C.WM_EXIT:
            return i + 1
    return len(raw) // 4


def compare(case):
    """One case: returns a dict of per-field mismatch counts."""
    raw = case["program_bytes"]
    stages = stages_from_bytes(raw, program_length(raw))
    engine = case["frames"]
    mine = ms.trace_program(stages, x=case["start_x"], y=case["start_y"],
                            heading=case["heading"], frames=len(engine))
    # sim field -> the name the engine dump uses for the same thing
    FIELDS = {"x": "x", "y": "y", "mode": "mode", "stage": "stage",
              "heading": "phase", "timer": "timer", "steps": "steps",
              "vx": "vx", "vy": "vy", "acc_x": "acc_x", "acc_y": "acc_y"}
    counts = {k: 0 for k in FIELDS}
    first = None
    for f, (e, m) in enumerate(zip(engine, mine)):
        got = {"x": m.x, "y": m.y, "mode": C.MOVEMENT_KINDS[m.stage_kind],
               # wmStage is a BYTE OFFSET in the engine and a record index in
               # the simulator; this is the one place the two are reconciled.
               "stage": m.stage_index * C.WM_STAGE_SIZE + case["stage_offset"],
               "heading": m.heading, "timer": m.timer, "steps": m.steps,
               "vx": m.vx, "vy": m.vy, "acc_x": m.acc_x, "acc_y": m.acc_y}
        for k, engine_name in FIELDS.items():
            if got[k] != e[engine_name]:
                counts[k] += 1
                if first is None:
                    first = (f, k, e[engine_name], got[k])
    return counts, first, len(engine)


def main():
    if not FIXTURE.exists():
        print(f"FAIL- the engine fixture is missing: {FIXTURE}")
        print("      record it with: python3 tests/movement_trace.py")
        return 1
    fx = json.loads(FIXTURE.read_text())

    # ---- the heading table, against the bytes in the running machine -----
    check("the simulator's heading table is the engine's, VX",
          list(ms.HEAD_VX) == fx["head_vx"])
    check("the simulator's heading table is the engine's, VY",
          list(ms.HEAD_VY) == fx["head_vy"])

    # ---- the authored programs the fixture flew are the project's --------
    proj = migration_v6.load_any(CANON).project
    by_id = {p.id: p for p in proj.movement_programs}
    for case in fx["cases"]:
        if case["kind"] != "production":
            continue
        raw = case["program_bytes"]
        rebuilt = stages_from_bytes(raw, program_length(raw))
        authored = by_id[case["name"]].stages
        check(f"the engine's loaded {case['name']!r} program is the project's",
              [s.to_dict() for s in rebuilt] == [s.to_dict() for s in authored],
              f"{[s.to_dict() for s in rebuilt]}")

    # ---- the comparison --------------------------------------------------
    print()
    print("  case                      kind        frames   "
          "X   Y  mode stage head timr step  vx  vy accX accY")
    total = 0
    for case in fx["cases"]:
        counts, first, n = compare(case)
        total += sum(counts.values())
        print(f"  {case['name']:<24s}  {case['kind']:<10s} {n:6d} "
              f"{counts['x']:4d}{counts['y']:4d}{counts['mode']:6d}"
              f"{counts['stage']:6d}{counts['heading']:5d}"
              f"{counts['timer']:5d}{counts['steps']:5d}"
              f"{counts['vx']:4d}{counts['vy']:4d}{counts['acc_x']:5d}"
              f"{counts['acc_y']:5d}")
        check(f"{case['name']}: zero mismatches against the engine over "
              f"{n} frames",
              sum(counts.values()) == 0,
              "" if first is None else
              f"first at frame {first[0]}: {first[1]} engine={first[2]} sim={first[3]}")
    print()
    check("ZERO authoritative mismatches across every case", total == 0,
          f"{total}")

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILURE(S):")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print(f"All {len(PASS)} engine-equivalence checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
