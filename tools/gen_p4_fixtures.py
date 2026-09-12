#!/usr/bin/env python3
"""Emit src/p4_fixtures.asm from the trajectories declared in tests/p4_model.py.

Same arrangement, and the same reasoning, as tools/gen_p3_fixtures.py: the
fixture INPUTS have one source of truth so that ~130 eleven-byte records are not
transcribed by hand, while the expected OUTPUTS -- sorted order, admission,
predecessor identity, slots, batches, $D010 -- are still derived independently
from the documented rules by tests/p2_model.py.

The record layout and the p3s macro are defined in src/p3_fixtures.asm, which is
imported first; this file only adds tables.

Usage:  python3 tools/gen_p4_fixtures.py          # rewrite src/p4_fixtures.asm
        python3 tools/gen_p4_fixtures.py --check  # fail if it is out of date
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import p4_model as P

OUT = ROOT / "src/p4_fixtures.asm"
HEADER = """// ===========================================================================
// p4_fixtures.asm — GENERATED. Do not edit by hand.
// ===========================================================================
// Regenerate with:   python3 tools/gen_p4_fixtures.py
// Source of truth:   tests/p4_model.py
// Verify in CI with: python3 tools/gen_p4_fixtures.py --check
//
// Record layout and the p3s macro come from src/p3_fixtures.asm.
//
// Several of these fixtures are STATIC in position but still use motion
// records, because a P4 fixture needs a specific Y AND a specific X per
// logical ID -- a scrambled storage order is the whole point, and the static
// loader derives X from a column cursor and takes Y from a bare list, which
// cannot express that. Zero velocities give a static sprite through the same
// path. It also means the schedule is rebuilt every frame, so a fixture whose
// answer should never change has to keep producing the same answer.
// ===========================================================================

* = $cb00 "p4 fixture data"
"""


def emit():
    out = [HEADER]
    consts = []
    for idx in sorted(P.FIXTURES):
        fx = P.FIXTURES[idx]
        consts.append(f".const P4F{idx}_N = {len(fx.sprites)}")
        out.append(f"\n// --- fixture {idx}: {fx.name} — {fx.note}")
        out.append(f"//     {len(fx.sprites)} sprites"
                   f"{'  (velocities all zero: static)' if all(s.X.vel0 == 0 and s.Y.vel0 == 0 for s in fx.sprites) else ''}")
        out.append(f"p4f{idx}:")
        for s in fx.sprites:
            out.append(
                f"    p3s({s.Y.pos0}, {s.X.pos0}, {s.X.vel0}, {s.X.lo}, {s.X.hi}, "
                f"{s.Y.vel0}, {s.Y.lo}, {s.Y.hi})")
    out.append("\n// --- per-fixture sprite counts ---")
    out.extend(consts)
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    bad = P.audit()
    if bad:
        print("model audit FAILED:\n  " + "\n  ".join(bad))
        sys.exit(1)
    text = emit()
    if "--check" in sys.argv:
        cur = OUT.read_text() if OUT.exists() else ""
        if cur != text:
            print(f"{OUT} is out of date; run tools/gen_p4_fixtures.py")
            sys.exit(1)
        print(f"{OUT.name} is up to date")
    else:
        OUT.write_text(text)
        print(f"wrote {OUT} ({len(text.splitlines())} lines)")
