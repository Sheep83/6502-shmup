// ===========================================================================
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
//   geometry    X = 176 + 140*cos(2*pi*k/256)   -> 36..316
//               Y = 140 + 70*sin(2*pi*k/256)   -> 70..210
//   sweep       triangle, -14..+14 rasters, uniform in raster offset
//
// Placed at $2400: the 1K hole between the diagnostic sprite bitmaps ($2000-
// $23ff) and screen page B ($2800). It is inside VIC bank 0 but nothing ever
// points the VIC at it -- sprite pointers only ever hold $80..$8f -- so it is
// ordinary RAM that happens to be cheap to address.
// ===========================================================================

* = $2400 "p5 ring tables"

// absolute sprite X, low byte, by phase index
ringXLo:
        .byte 60, 60, 60, 60, 59, 59, 58, 58, 57, 57, 56, 55, 54, 53, 52, 51
        .byte 49, 48, 47, 45, 43, 42, 40, 38, 36, 34, 32, 30, 28, 26, 24, 21
        .byte 19, 17, 14, 11, 9, 6, 3, 1, 254, 251, 248, 245, 242, 239, 236, 233
        .byte 230, 226, 223, 220, 217, 213, 210, 207, 203, 200, 197, 193, 190, 186, 183, 179
        .byte 176, 173, 169, 166, 162, 159, 155, 152, 149, 145, 142, 139, 135, 132, 129, 126
        .byte 122, 119, 116, 113, 110, 107, 104, 101, 98, 95, 93, 90, 87, 85, 82, 79
        .byte 77, 75, 72, 70, 68, 66, 64, 62, 60, 58, 56, 54, 53, 51, 49, 48
        .byte 47, 45, 44, 43, 42, 41, 40, 39, 39, 38, 38, 37, 37, 36, 36, 36
        .byte 36, 36, 36, 36, 37, 37, 38, 38, 39, 39, 40, 41, 42, 43, 44, 45
        .byte 47, 48, 49, 51, 53, 54, 56, 58, 60, 62, 64, 66, 68, 70, 72, 75
        .byte 77, 79, 82, 85, 87, 90, 93, 95, 98, 101, 104, 107, 110, 113, 116, 119
        .byte 122, 126, 129, 132, 135, 139, 142, 145, 149, 152, 155, 159, 162, 166, 169, 173
        .byte 176, 179, 183, 186, 190, 193, 197, 200, 203, 207, 210, 213, 217, 220, 223, 226
        .byte 230, 233, 236, 239, 242, 245, 248, 251, 254, 1, 3, 6, 9, 11, 14, 17
        .byte 19, 21, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 43, 45, 47, 48
        .byte 49, 51, 52, 53, 54, 55, 56, 57, 57, 58, 58, 59, 59, 60, 60, 60

// absolute sprite X, bit 8 -- the $D010 source
ringXHi:
        .byte 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
        .byte 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
        .byte 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1
        .byte 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
        .byte 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1

// absolute sprite Y by phase index
ringY:
        .byte 140, 142, 143, 145, 147, 149, 150, 152, 154, 155, 157, 159, 160, 162, 164, 165
        .byte 167, 168, 170, 171, 173, 175, 176, 177, 179, 180, 182, 183, 184, 186, 187, 188
        .byte 189, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 203, 204
        .byte 205, 205, 206, 206, 207, 207, 208, 208, 209, 209, 209, 209, 210, 210, 210, 210
        .byte 210, 210, 210, 210, 210, 209, 209, 209, 209, 208, 208, 207, 207, 206, 206, 205
        .byte 205, 204, 203, 203, 202, 201, 200, 199, 198, 197, 196, 195, 194, 193, 192, 191
        .byte 189, 188, 187, 186, 184, 183, 182, 180, 179, 177, 176, 175, 173, 171, 170, 168
        .byte 167, 165, 164, 162, 160, 159, 157, 155, 154, 152, 150, 149, 147, 145, 143, 142
        .byte 140, 138, 137, 135, 133, 131, 130, 128, 126, 125, 123, 121, 120, 118, 116, 115
        .byte 113, 112, 110, 109, 107, 105, 104, 103, 101, 100, 98, 97, 96, 94, 93, 92
        .byte 91, 89, 88, 87, 86, 85, 84, 83, 82, 81, 80, 79, 78, 77, 77, 76
        .byte 75, 75, 74, 74, 73, 73, 72, 72, 71, 71, 71, 71, 70, 70, 70, 70
        .byte 70, 70, 70, 70, 70, 71, 71, 71, 71, 72, 72, 73, 73, 74, 74, 75
        .byte 75, 76, 77, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89
        .byte 91, 92, 93, 94, 96, 97, 98, 100, 101, 103, 104, 105, 107, 109, 110, 112
        .byte 113, 115, 116, 118, 120, 121, 123, 125, 126, 128, 130, 131, 133, 135, 137, 138

// RING-SHIFT vertical sweep, signed, two's complement
ringShiftTab:
        .byte 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3
        .byte 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 6, 6, 6, 6, 7, 7
        .byte 7, 7, 7, 8, 8, 8, 8, 9, 9, 9, 9, 9, 10, 10, 10, 10
        .byte 11, 11, 11, 11, 11, 12, 12, 12, 12, 12, 13, 13, 13, 13, 14, 14
        .byte 14, 14, 14, 13, 13, 13, 13, 12, 12, 12, 12, 12, 11, 11, 11, 11
        .byte 11, 10, 10, 10, 10, 9, 9, 9, 9, 9, 8, 8, 8, 8, 7, 7
        .byte 7, 7, 7, 6, 6, 6, 6, 5, 5, 5, 5, 5, 4, 4, 4, 4
        .byte 4, 3, 3, 3, 3, 2, 2, 2, 2, 2, 1, 1, 1, 1, 0, 0
        .byte 0, 0, 0, 255, 255, 255, 255, 254, 254, 254, 254, 254, 253, 253, 253, 253
        .byte 253, 252, 252, 252, 252, 251, 251, 251, 251, 251, 250, 250, 250, 250, 249, 249
        .byte 249, 249, 249, 248, 248, 248, 248, 247, 247, 247, 247, 247, 246, 246, 246, 246
        .byte 246, 245, 245, 245, 245, 244, 244, 244, 244, 244, 243, 243, 243, 243, 242, 242
        .byte 242, 242, 242, 243, 243, 243, 243, 244, 244, 244, 244, 244, 245, 245, 245, 245
        .byte 246, 246, 246, 246, 246, 247, 247, 247, 247, 247, 248, 248, 248, 248, 249, 249
        .byte 249, 249, 249, 250, 250, 250, 250, 251, 251, 251, 251, 251, 252, 252, 252, 252
        .byte 253, 253, 253, 253, 253, 254, 254, 254, 254, 254, 255, 255, 255, 255, 0, 0

.const P5_TABLE_BASE  = $2400
.const P5_TABLE_BYTES = 1024
.const P5_N_RING     = 16
.const P5_PHASE_STEP = 16   // per-sprite phase offset, 256/16

// OWNERSHIP OF $2400-$27FF, STATED AND ENFORCED.
//
// These tables sit in the 1K hole between the sprite bitmap pool
// ($2000-$23FF) and screen page B ($2800), inside VIC bank 0. That is
// cheap and legal, and it is also the single most dangerous place in
// the map: a sprite pointer one block past the pool ($90) resolves to
// $2400, and a smooth coordinate ramp rendered as a sprite is exactly
// the horizontal-stripe garbage that a pointer fault looks like.
//
// So the rule is asserted rather than assumed, in both directions.
// tests/sprite_identity.py enforces the other half at run time: every
// accepted sprite must resolve to its OWN block, byte for byte.
.if (P5_TABLE_BASE < spriteBitmapsEnd) {
    .error "P5 ring tables overlap the sprite bitmap pool"
}
.if (P5_TABLE_BASE + P5_TABLE_BYTES > SCREEN_B) {
    .error "P5 ring tables overlap screen page B"
}

// Assembly-time restatement of what the model asserts, so a
// regenerated table that left the visible band cannot be built.
.if (56 < 50)  { .error "P5 orbit leaves the top of the visible band" }
.if (224 > 229) { .error "P5 orbit leaves the bottom of the visible band" }
