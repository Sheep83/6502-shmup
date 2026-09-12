#!/usr/bin/env python3
"""Emit src/p5_tables.asm from the geometry declared in tests/p5_model.py.

Same arrangement as the P3/P4 generators. The ring tables are the one thing the
engine and the model MUST agree on byte for byte -- every P5 expectation is a
table lookup -- so they are generated from the model rather than written twice.
KickAssembler can compute sin() at assembly time, but its rounding is Java's and
Python's round() is banker's rounding; generating removes the question entirely.

Usage:  python3 tools/gen_p5_tables.py          # rewrite src/p5_tables.asm
        python3 tools/gen_p5_tables.py --check  # fail if it is out of date
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import p5_model as P

OUT = ROOT / "src/p5_tables.asm"
HEADER = f"""// ===========================================================================
// p5_tables.asm — GENERATED. Do not edit by hand.
// ===========================================================================
// Regenerate with:   python3 tools/gen_p5_tables.py
// Source of truth:   tests/p5_model.py
// Verify in CI with: python3 tools/gen_p5_tables.py --check
//
// The orbit, precomputed. ringTick does no arithmetic beyond an index add and
// three table reads per sprite: no multiply, no trig, no fixed-point scaling at
// run time. Sixteen sprites cost about 500 cycles a frame, which is why P5 can
// afford to move every sprite every frame and still measure the sorter and the
// builder rather than the motion.
//
// The X tables hold the ABSOLUTE screen X, not an offset from a centre, so the
// per-sprite work is a load and a store rather than a 16-bit add. Same for Y.
//
//   geometry    X = {P.CENTRE_X} + {P.RADIUS_X}*cos(2*pi*k/256)   -> {min(P.RING_X)}..{max(P.RING_X)}
//               Y = {P.CENTRE_Y} + {P.RADIUS_Y}*sin(2*pi*k/256)   -> {min(P.RING_Y)}..{max(P.RING_Y)}
//   sweep       triangle, {min(P.RING_SHIFT):+d}..{max(P.RING_SHIFT):+d} rasters, uniform in raster offset
//
// Placed at $2400: the 1K hole between the diagnostic sprite bitmaps ($2000-
// $23ff) and screen page B ($2800). It is inside VIC bank 0 but nothing ever
// points the VIC at it -- sprite pointers only ever hold $80..$8f -- so it is
// ordinary RAM that happens to be cheap to address.
// ===========================================================================
"""


def emit_bytes(name, values, comment):
    out = [f"// {comment}", f"{name}:"]
    for i in range(0, len(values), 16):
        row = ", ".join(f"{v & 0xff}" for v in values[i:i + 16])
        out.append(f"        .byte {row}")
    return "\n".join(out)


def render():
    xs, ys, sh = P.RING_X, P.RING_Y, P.RING_SHIFT
    parts = [HEADER, '* = $2400 "p5 ring tables"', ""]
    parts.append(emit_bytes("ringXLo", [x & 0xff for x in xs],
                            "absolute sprite X, low byte, by phase index"))
    parts.append("")
    parts.append(emit_bytes("ringXHi", [x >> 8 for x in xs],
                            "absolute sprite X, bit 8 -- the $D010 source"))
    parts.append("")
    parts.append(emit_bytes("ringY", ys,
                            "absolute sprite Y by phase index"))
    parts.append("")
    parts.append(emit_bytes("ringShiftTab", sh,
                            "RING-SHIFT vertical sweep, signed, two's complement"))
    parts.append("")
    parts.append(f".const P5_TABLE_BASE  = $2400")
    parts.append(f".const P5_TABLE_BYTES = {4 * P.TABLE}")
    parts.append(f".const P5_N_RING     = {P.N_RING}")
    parts.append(f".const P5_PHASE_STEP = {P.PHASE_STEP}   "
                 f"// per-sprite phase offset, 256/{P.N_RING}")
    parts.append("")
    parts.append("// OWNERSHIP OF $2400-$27FF, STATED AND ENFORCED.")
    parts.append("//")
    parts.append("// These tables sit in the 1K hole between the sprite bitmap pool")
    parts.append("// ($2000-$23FF) and screen page B ($2800), inside VIC bank 0. That is")
    parts.append("// cheap and legal, and it is also the single most dangerous place in")
    parts.append("// the map: a sprite pointer one block past the pool ($90) resolves to")
    parts.append("// $2400, and a smooth coordinate ramp rendered as a sprite is exactly")
    parts.append("// the horizontal-stripe garbage that a pointer fault looks like.")
    parts.append("//")
    parts.append("// So the rule is asserted rather than assumed, in both directions.")
    parts.append("// tests/sprite_identity.py enforces the other half at run time: every")
    parts.append("// accepted sprite must resolve to its OWN block, byte for byte.")
    parts.append(".if (P5_TABLE_BASE < spriteBitmapsEnd) {")
    parts.append('    .error "P5 ring tables overlap the sprite bitmap pool"')
    parts.append("}")
    parts.append(".if (P5_TABLE_BASE + P5_TABLE_BYTES > SCREEN_B) {")
    parts.append('    .error "P5 ring tables overlap screen page B"')
    parts.append("}")
    parts.append("")
    parts.append("// Assembly-time restatement of what the model asserts, so a")
    parts.append("// regenerated table that left the visible band cannot be built.")
    parts.append(f".if ({min(ys) + min(sh)} < 50)  {{ .error \"P5 orbit leaves the top of the visible band\" }}")
    parts.append(f".if ({max(ys) + max(sh)} > 229) {{ .error \"P5 orbit leaves the bottom of the visible band\" }}")
    parts.append("")
    return "\n".join(parts)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        cur = OUT.read_text() if OUT.exists() else ""
        if cur != text:
            print(f"{OUT} is out of date; run python3 tools/gen_p5_tables.py")
            sys.exit(1)
        print(f"{OUT.name} matches tests/p5_model.py")
    else:
        OUT.write_text(text)
        print(f"wrote {OUT} ({len(text)} bytes)")
