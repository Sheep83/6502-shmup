#!/usr/bin/env python3
"""Emit src/p3_fixtures.asm from the trajectories declared in tests/p3_model.py.

WHY THIS IS GENERATED
The P3 fixtures are ~100 eleven-byte records. Transcribing those into `.byte`
lines by hand is the sort of task that silently produces a fixture which is not
the fixture anyone designed, and the failure would look like a renderer bug.

WHAT IS AND IS NOT INDEPENDENT
The fixture INPUTS (initial position and trajectory) have one source of truth,
here. That is not a loss of test independence, because the thing under test is
the BUILDER: tests/p2_model.py derives the expected schedule -- acceptance,
rejection reason, slot, predecessor, gap, batch membership, complete $D010 --
from the documented rules, with no knowledge of what the 6502 produced. What
this generator removes is transcription error in the inputs, not the
independence of the expected outputs.

The inputs are checked on their own terms too: p3_model.audit() asserts, for
every frame of every fixture, that Y order still ascends, that no entry was
admitted below MIN_REUSE_GAP, and that every trajectory stays a full velocity
step clear of its type's limits. The generated file repeats that last check as
an assembler `.if`, so a hand edit to the .asm is caught at build time.

Usage:  python3 tools/gen_p3_fixtures.py        # rewrite src/p3_fixtures.asm
        python3 tools/gen_p3_fixtures.py --check  # fail if it is out of date
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import p3_model as P

OUT = ROOT / "src/p3_fixtures.asm"
HEADER = """// ===========================================================================
// p3_fixtures.asm — GENERATED. Do not edit by hand.
// ===========================================================================
// Regenerate with:   python3 tools/gen_p3_fixtures.py
// Source of truth:   tests/p3_model.py
// Verify in CI with: python3 tools/gen_p3_fixtures.py --check
//
// One record per logical sprite, eleven bytes, in the order motionTick and the
// P3 loader expect:
//
//     0  Y            initial raster
//     1  X low        initial X, low 8 bits
//     2  X high       initial X, bit 8 (0 or 1)
//     3  X velocity   signed, added each frame; 0 means static in X
//     4  X min low    5  X min high
//     6  X max low    7  X max high
//     8  Y velocity   signed; 0 means static in Y
//     9  Y min       10  Y max
//
// The p3s macro enforces at ASSEMBLY TIME that every bound stays a full
// velocity step clear of 0 and of the axis maximum, because motionTick does
// plain 8-bit and 16-bit arithmetic with no overflow handling and would
// otherwise wrap and clamp to the wrong end. See src/motion.asm.
// ===========================================================================

// Record field count and layout, named once so the loader cannot disagree.
.const P3_REC_BYTES = 11

.macro p3s(y, x, xv, xmin, xmax, yv, ymin, ymax) {
    .if (ymin < abs(yv))        { .error "p3s: Y min within one step of 0" }
    .if (ymax + abs(yv) > 255)  { .error "p3s: Y max within one step of 255" }
    .if (xmin < abs(xv))        { .error "p3s: X min within one step of 0" }
    .if (xmax + abs(xv) > 511)  { .error "p3s: X max within one step of 511" }
    .if (y < ymin || y > ymax)  { .error "p3s: initial Y outside its bounds" }
    .if (x < xmin || x > xmax)  { .error "p3s: initial X outside its bounds" }
    .byte y, <x, >x, xv, <xmin, >xmin, <xmax, >xmax, yv, ymin, ymax
}

* = $c600 "p3 fixture data"
"""


def emit():
    out = [HEADER]
    consts = []
    for idx in sorted(P.FIXTURES):
        fx = P.FIXTURES[idx]
        consts.append(f".const P3F{idx}_N = {len(fx.sprites)}")
        out.append(f"\n// --- fixture {idx}: {fx.name} — {fx.note}")
        if fx.kind == P.FK_STATIC:
            out.append(f"//     static Y list, X/pointer/colour derived from the logical index")
            ys = ", ".join(str(s.Y.pos0) for s in fx.sprites)
            out.append(f"p3f{idx}:\n    .byte {ys}")
            continue
        out.append(f"//     {len(fx.sprites)} sprites, {P.MAX_LOGICAL}-sprite pool")
        out.append(f"p3f{idx}:")
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
            print(f"{OUT} is out of date; run tools/gen_p3_fixtures.py")
            sys.exit(1)
        print(f"{OUT.name} is up to date")
    else:
        OUT.write_text(text)
        print(f"wrote {OUT} ({len(text.splitlines())} lines)")
