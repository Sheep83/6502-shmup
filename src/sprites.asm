// ===========================================================================
// sprites.asm — sixteen deliberately diagnostic sprite bitmaps
// ===========================================================================
// Each bitmap is a hollow rectangle (so X/Y placement and slot reuse are
// visible as an outline) containing a large hexadecimal numeral 0..F.
//
// The numeral is the LOGICAL sprite index. If logical sprite 11 ever renders
// with logical sprite 5's pointer, the screen shows two "5"s and no "B" — an
// error a human spots instantly. That is the entire design goal here; these
// are not meant to be attractive.
// ===========================================================================

.const SPRITE_BLOCK      = $2000                    // VIC bank 0, 64-byte aligned
.const SPRITE_PTR_FIRST  = SPRITE_BLOCK / 64        // $80
.const SPRITE_COUNT      = 16

.if ((SPRITE_BLOCK & 63) != 0) { .error "sprite block must be 64-byte aligned" }
.if (SPRITE_BLOCK + SPRITE_COUNT * 64 > $4000) { .error "sprite bitmaps leave VIC bank 0" }

// 4x5 hex font, one nibble per row, bit 3 = leftmost pixel.
.var hexFont = List()
.eval hexFont.add(List().add($f,$9,$9,$9,$f))      // 0
.eval hexFont.add(List().add($2,$6,$2,$2,$7))      // 1
.eval hexFont.add(List().add($f,$1,$f,$8,$f))      // 2
.eval hexFont.add(List().add($f,$1,$7,$1,$f))      // 3
.eval hexFont.add(List().add($9,$9,$f,$1,$1))      // 4
.eval hexFont.add(List().add($f,$8,$f,$1,$f))      // 5
.eval hexFont.add(List().add($f,$8,$f,$9,$f))      // 6
.eval hexFont.add(List().add($f,$1,$2,$4,$4))      // 7
.eval hexFont.add(List().add($f,$9,$f,$9,$f))      // 8
.eval hexFont.add(List().add($f,$9,$f,$1,$f))      // 9
.eval hexFont.add(List().add($6,$9,$f,$9,$9))      // A
.eval hexFont.add(List().add($e,$9,$e,$9,$e))      // B
.eval hexFont.add(List().add($7,$8,$8,$8,$7))      // C
.eval hexFont.add(List().add($e,$9,$9,$9,$e))      // D
.eval hexFont.add(List().add($f,$8,$e,$8,$f))      // E
.eval hexFont.add(List().add($f,$8,$e,$8,$8))      // F

// Expand a 4-pixel font row to 16 pixels (each pixel 4x wide).
.function exp4(n) {
    .var g = 0
    .for (var i = 0; i < 4; i++) {
        .if (((n >> (3 - i)) & 1) != 0) { .eval g = g | ($f << (12 - 4 * i)) }
    }
    .return g
}

// Byte b (0..2) of sprite row r for glyph d.
// Layout: row 0 and row 20 are solid edges; rows 1..19 carry the left/right
// edge pixels; the glyph occupies x 4..19 on rows 3..17 (3x vertical scale).
.function spriteByte(d, r, b) {
    .if (r == 0 || r == 20) { .return $ff }
    .var v = 0
    .if (b == 0) { .eval v = v | $80 }                 // left edge
    .if (b == 2) { .eval v = v | $01 }                 // right edge
    .if (r >= 3 && r <= 17) {
        .var g = exp4(hexFont.get(d).get((r - 3) / 3))
        .if (b == 0) { .eval v = v | ((g >> 12) & $0f) }
        .if (b == 1) { .eval v = v | ((g >> 4) & $ff) }
        .if (b == 2) { .eval v = v | ((g << 4) & $f0) }
    }
    .return v
}

* = SPRITE_BLOCK "diagnostic sprites"
spriteBitmaps:
.for (var d = 0; d < SPRITE_COUNT; d++) {
    .for (var r = 0; r < 21; r++) {
        .byte spriteByte(d, r, 0), spriteByte(d, r, 1), spriteByte(d, r, 2)
    }
    .byte $00                                          // 64th padding byte
}
spriteBitmapsEnd:

.if (spriteBitmapsEnd - spriteBitmaps != SPRITE_COUNT * 64) {
    .error "sprite bitmaps must be exactly SPRITE_COUNT x 64 bytes"
}
