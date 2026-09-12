// ===========================================================================
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


// --- fixture 16: MOVE6 — baseline motion, no reuse
//     6 sprites, 32-sprite pool
p3f16:
    p3s(60, 40, 2, 40, 200, 0, 60, 60)
    p3s(85, 100, 0, 100, 100, 1, 85, 105)
    p3s(115, 60, 3, 60, 220, 1, 115, 135)
    p3s(150, 160, 0, 160, 160, 0, 150, 150)
    p3s(180, 250, -2, 200, 250, 0, 180, 180)
    p3s(205, 220, 0, 220, 220, 1, 205, 215)

// --- fixture 17: MSBFLIP6 — six-slot reuse, every MSB inverted
//     12 sprites, 32-sprite pool
p3f17:
    p3s(60, 40, 0, 40, 40, 0, 60, 60)
    p3s(61, 264, 0, 264, 264, 0, 61, 61)
    p3s(62, 100, 0, 100, 100, 0, 62, 62)
    p3s(63, 300, 0, 300, 300, 0, 63, 63)
    p3s(64, 160, 0, 160, 160, 0, 64, 64)
    p3s(65, 336, 0, 336, 336, 0, 65, 65)
    p3s(98, 264, 0, 264, 264, 0, 98, 98)
    p3s(98, 40, 0, 40, 40, 0, 98, 98)
    p3s(98, 300, 0, 300, 300, 0, 98, 98)
    p3s(98, 100, 0, 100, 100, 0, 98, 98)
    p3s(98, 336, 0, 336, 336, 0, 98, 98)
    p3s(98, 160, 0, 160, 160, 0, 98, 98)

// --- fixture 18: X255 — moving crossings of 255/256
//     12 sprites, 32-sprite pool
p3f18:
    p3s(60, 230, 2, 230, 290, 0, 60, 60)
    p3s(61, 300, 0, 300, 300, 0, 61, 61)
    p3s(62, 60, 0, 60, 60, 0, 62, 62)
    p3s(63, 120, 0, 120, 120, 0, 63, 63)
    p3s(64, 180, 0, 180, 180, 0, 64, 64)
    p3s(65, 336, 0, 336, 336, 0, 65, 65)
    p3s(98, 40, 0, 40, 40, 0, 98, 98)
    p3s(98, 290, -2, 230, 290, 0, 98, 98)
    p3s(98, 100, 0, 100, 100, 0, 98, 98)
    p3s(98, 264, 0, 264, 264, 0, 98, 98)
    p3s(98, 160, 0, 160, 160, 0, 98, 98)
    p3s(98, 300, 0, 300, 300, 0, 98, 98)

// --- fixture 19: YMOVE — legal moving-Y reuse
//     12 sprites, 32-sprite pool
p3f19:
    p3s(60, 40, 0, 40, 40, 1, 60, 64)
    p3s(61, 74, 0, 74, 74, 1, 61, 65)
    p3s(62, 108, 0, 108, 108, 1, 62, 66)
    p3s(63, 142, 0, 142, 142, 1, 63, 67)
    p3s(64, 176, 0, 176, 176, 1, 64, 68)
    p3s(65, 210, 0, 210, 210, 1, 65, 69)
    p3s(105, 30, 0, 30, 30, 1, 105, 111)
    p3s(105, 66, 0, 66, 66, 1, 105, 111)
    p3s(105, 102, 0, 102, 102, 1, 105, 111)
    p3s(105, 138, 0, 138, 138, 1, 105, 111)
    p3s(105, 174, 0, 174, 174, 1, 105, 111)
    p3s(105, 210, 0, 210, 210, 1, 105, 111)

// --- fixture 20: GAP33 — admission threshold crossing
//     7 sprites, 32-sprite pool
p3f20:
    p3s(60, 40, 0, 40, 40, 0, 60, 60)
    p3s(61, 74, 0, 74, 74, 0, 61, 61)
    p3s(62, 108, 0, 108, 108, 0, 62, 62)
    p3s(63, 142, 0, 142, 142, 0, 63, 63)
    p3s(64, 176, 0, 176, 176, 0, 64, 64)
    p3s(65, 210, 0, 210, 210, 0, 65, 65)
    p3s(91, 180, 0, 180, 180, 1, 91, 94)

// --- fixture 21: SHAPE — schedule shape mutation
//     13 sprites, 32-sprite pool
p3f21:
    p3s(60, 40, 0, 40, 40, 0, 60, 60)
    p3s(61, 100, 0, 100, 100, 0, 61, 61)
    p3s(62, 160, 0, 160, 160, 0, 62, 62)
    p3s(63, 40, 0, 40, 40, 0, 63, 63)
    p3s(64, 100, 0, 100, 100, 0, 64, 64)
    p3s(65, 160, 0, 160, 160, 0, 65, 65)
    p3s(91, 180, 0, 180, 180, 1, 91, 94)
    p3s(120, 40, 0, 40, 40, 0, 120, 120)
    p3s(120, 300, 0, 300, 300, 0, 120, 120)
    p3s(120, 160, 0, 160, 160, 0, 120, 120)
    p3s(120, 264, 0, 264, 264, 0, 120, 120)
    p3s(120, 100, 0, 100, 100, 0, 120, 120)
    p3s(120, 336, 0, 336, 336, 0, 120, 120)

// --- fixture 22: MAXCAP — MAX_SCHED overflow
//     static Y list, X/pointer/colour derived from the logical index
p3f22:
    .byte 50, 56, 62, 68, 74, 80, 86, 92, 98, 104, 110, 116, 122, 128, 134, 140, 146, 152, 158, 164, 170, 176, 182, 188, 194, 200, 206, 212, 218, 224

// --- fixture 23: MOTION12 — integrated moving fixture
//     12 sprites, 32-sprite pool
p3f23:
    p3s(60, 40, 2, 30, 80, 1, 60, 66)
    p3s(61, 90, -2, 50, 130, 1, 61, 67)
    p3s(62, 140, 2, 100, 180, 1, 62, 68)
    p3s(63, 190, -2, 150, 230, 1, 63, 69)
    p3s(64, 230, 2, 230, 300, 1, 64, 70)
    p3s(65, 300, -2, 260, 340, 1, 65, 71)
    p3s(110, 300, -2, 230, 300, 1, 110, 118)
    p3s(110, 230, 2, 190, 270, 1, 110, 118)
    p3s(110, 200, -2, 160, 240, 1, 110, 118)
    p3s(110, 150, 2, 110, 190, 1, 110, 118)
    p3s(110, 100, -2, 60, 140, 1, 110, 118)
    p3s(110, 50, 2, 30, 90, 1, 110, 118)

// --- per-fixture sprite counts ---
.const P3F16_N = 6
.const P3F17_N = 12
.const P3F18_N = 12
.const P3F19_N = 12
.const P3F20_N = 7
.const P3F21_N = 13
.const P3F22_N = 30
.const P3F23_N = 12
