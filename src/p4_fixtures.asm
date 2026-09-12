// ===========================================================================
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


// --- fixture 24: SORTSTATIC — scrambled static logical order
//     12 sprites  (velocities all zero: static)
p4f24:
    p3s(98, 40, 0, 40, 40, 0, 98, 98)
    p3s(61, 60, 0, 60, 60, 0, 61, 61)
    p3s(98, 90, 0, 90, 90, 0, 98, 98)
    p3s(60, 120, 0, 120, 120, 0, 60, 60)
    p3s(98, 140, 0, 140, 140, 0, 98, 98)
    p3s(64, 180, 0, 180, 180, 0, 64, 64)
    p3s(98, 210, 0, 210, 210, 0, 98, 98)
    p3s(62, 40, 0, 40, 40, 0, 62, 62)
    p3s(98, 264, 0, 264, 264, 0, 98, 98)
    p3s(63, 100, 0, 100, 100, 0, 63, 63)
    p3s(98, 300, 0, 300, 300, 0, 98, 98)
    p3s(65, 160, 0, 160, 160, 0, 65, 65)

// --- fixture 25: CROSS2 — two-sprite adjacent crossing
//     2 sprites
p4f25:
    p3s(90, 120, 0, 120, 120, 1, 90, 102)
    p3s(102, 200, 0, 200, 200, -1, 90, 102)

// --- fixture 26: CROSS6 — six interleaving over six reusers
//     12 sprites
p4f26:
    p3s(70, 40, 0, 40, 40, 1, 70, 120)
    p3s(80, 74, 0, 74, 74, -1, 70, 120)
    p3s(90, 108, 0, 108, 108, 1, 70, 120)
    p3s(100, 142, 0, 142, 142, -1, 70, 120)
    p3s(110, 176, 0, 176, 176, 1, 70, 120)
    p3s(120, 210, 0, 210, 210, -1, 70, 120)
    p3s(155, 30, 0, 30, 30, 0, 155, 155)
    p3s(155, 66, 0, 66, 66, 0, 155, 155)
    p3s(155, 102, 0, 102, 102, 0, 155, 155)
    p3s(155, 138, 0, 138, 138, 0, 155, 155)
    p3s(155, 174, 0, 174, 174, 0, 155, 155)
    p3s(155, 210, 0, 210, 210, 0, 155, 155)

// --- fixture 27: PREDCHANGE — crossing changes the i-6 predecessor
//     7 sprites
p4f27:
    p3s(60, 40, 0, 40, 40, 1, 60, 62)
    p3s(62, 90, 0, 90, 90, -1, 60, 62)
    p3s(70, 130, 0, 130, 130, 0, 70, 70)
    p3s(71, 160, 0, 160, 160, 0, 71, 71)
    p3s(72, 190, 0, 190, 190, 0, 72, 72)
    p3s(73, 220, 0, 220, 220, 0, 73, 73)
    p3s(98, 60, 0, 60, 60, 0, 98, 98)

// --- fixture 28: SORTSHAPE — crossing changes admission
//     12 sprites
p4f28:
    p3s(63, 40, 0, 40, 40, 0, 63, 63)
    p3s(64, 70, 0, 70, 70, 0, 64, 64)
    p3s(65, 100, 0, 100, 100, 0, 65, 65)
    p3s(66, 40, 0, 40, 40, 0, 66, 66)
    p3s(67, 70, 0, 70, 70, 0, 67, 67)
    p3s(60, 200, 0, 200, 200, 1, 60, 66)
    p3s(94, 160, 0, 160, 160, 0, 94, 94)
    p3s(130, 60, 0, 60, 60, 0, 130, 130)
    p3s(130, 264, 0, 264, 264, 0, 130, 130)
    p3s(130, 60, 0, 60, 60, 0, 130, 130)
    p3s(130, 264, 0, 264, 264, 0, 130, 130)
    p3s(130, 60, 0, 60, 60, 0, 130, 130)

// --- fixture 29: TIE6 — equal-Y tie, merged batch
//     12 sprites  (velocities all zero: static)
p4f29:
    p3s(98, 40, 0, 40, 40, 0, 98, 98)
    p3s(98, 264, 0, 264, 264, 0, 98, 98)
    p3s(98, 100, 0, 100, 100, 0, 98, 98)
    p3s(98, 300, 0, 300, 300, 0, 98, 98)
    p3s(98, 160, 0, 160, 160, 0, 98, 98)
    p3s(98, 336, 0, 336, 336, 0, 98, 98)
    p3s(60, 40, 0, 40, 40, 0, 60, 60)
    p3s(61, 74, 0, 74, 74, 0, 61, 61)
    p3s(62, 108, 0, 108, 108, 0, 62, 62)
    p3s(63, 142, 0, 142, 142, 0, 63, 63)
    p3s(64, 176, 0, 176, 176, 0, 64, 64)
    p3s(65, 210, 0, 210, 210, 0, 65, 65)

// --- fixture 30: SORTCAP — dynamic order at/over MAX_SCHED
//     26 sprites
p4f30:
    p3s(60, 30, 0, 30, 30, 0, 60, 60)
    p3s(60, 60, 0, 60, 60, 0, 60, 60)
    p3s(60, 90, 0, 90, 90, 0, 60, 60)
    p3s(60, 120, 0, 120, 120, 0, 60, 60)
    p3s(60, 150, 0, 150, 150, 0, 60, 60)
    p3s(60, 180, 0, 180, 180, 0, 60, 60)
    p3s(98, 30, 0, 30, 30, 0, 98, 98)
    p3s(98, 60, 0, 60, 60, 0, 98, 98)
    p3s(98, 90, 0, 90, 90, 0, 98, 98)
    p3s(98, 120, 0, 120, 120, 0, 98, 98)
    p3s(98, 150, 0, 150, 150, 0, 98, 98)
    p3s(98, 180, 0, 180, 180, 0, 98, 98)
    p3s(136, 30, 0, 30, 30, 0, 136, 136)
    p3s(136, 60, 0, 60, 60, 0, 136, 136)
    p3s(136, 90, 0, 90, 90, 0, 136, 136)
    p3s(136, 120, 0, 120, 120, 0, 136, 136)
    p3s(136, 150, 0, 150, 150, 0, 136, 136)
    p3s(136, 180, 0, 180, 180, 0, 136, 136)
    p3s(174, 30, 0, 30, 30, 0, 174, 174)
    p3s(174, 60, 0, 60, 60, 0, 174, 174)
    p3s(174, 90, 0, 90, 90, 0, 174, 174)
    p3s(174, 120, 0, 120, 120, 0, 174, 174)
    p3s(174, 150, 0, 150, 150, 0, 174, 174)
    p3s(174, 180, 0, 180, 180, 0, 174, 174)
    p3s(220, 100, 0, 100, 100, 4, 220, 228)
    p3s(228, 200, 0, 200, 200, -4, 220, 228)

// --- per-fixture sprite counts ---
.const P4F24_N = 12
.const P4F25_N = 2
.const P4F26_N = 12
.const P4F27_N = 7
.const P4F28_N = 12
.const P4F29_N = 12
.const P4F30_N = 26
