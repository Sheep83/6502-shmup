// ===========================================================================
// player_art_tall.asm — vertically stretched player multicolour sprites
// ===========================================================================
// Experimental replacement for player_art.asm.
//
// The supplied artwork occupies 16 authored rows in Claude's original
// extraction. This version expands those 16 rows to all 21 VIC sprite rows
// by deterministic nearest-neighbour row replication. Horizontal bitmap
// data and all 2-bit multicolour pixel values are unchanged.
//
// 15 frames, bank-major:
//     index = bank * 3 + engine
//     bank 0..4 = hard left .. hard right
//     engine 0..2 = flame full, small, out
//
// Source-row mapping (0..15 -> 21 output rows):
//     0, 1, 1, 2, 3, 4, 4, 5, 6, 7, 8, 8, 9, 10, 11, 11, 12, 13, 14, 14, 15
// ===========================================================================
player_art_frames:
// --- bankL2/engine0
    .byte $00, $30, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $c0
    .byte $00, $b8, $c0
    .byte $00, $a8, $80
    .byte $00, $af, $80
    .byte $0c, $bd, $c0
    .byte $08, $ee, $ac
    .byte $08, $ee, $ac
    .byte $0b, $ed, $ac
    .byte $0d, $75, $ab
    .byte $0a, $de, $eb
    .byte $0a, $de, $eb
    .byte $09, $ee, $00
    .byte $39, $54, $00
    .byte $2e, $b8, $00
    .byte $2e, $b8, $00
    .byte $e0, $20, $00
    .byte $00

// --- bankL2/engine1
    .byte $00, $30, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $c0
    .byte $00, $b8, $c0
    .byte $00, $a8, $80
    .byte $00, $af, $80
    .byte $0c, $bd, $c0
    .byte $08, $ee, $ac
    .byte $08, $ee, $ac
    .byte $0b, $ed, $ac
    .byte $0d, $75, $ab
    .byte $0a, $de, $eb
    .byte $0a, $de, $eb
    .byte $09, $ee, $00
    .byte $39, $54, $00
    .byte $2e, $20, $00
    .byte $2e, $20, $00
    .byte $e0, $00, $00
    .byte $00

// --- bankL2/engine2
    .byte $00, $30, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $00
    .byte $00, $b8, $c0
    .byte $00, $b8, $c0
    .byte $00, $a8, $80
    .byte $00, $af, $80
    .byte $0c, $bd, $c0
    .byte $08, $ee, $ac
    .byte $08, $ee, $ac
    .byte $0b, $ed, $ac
    .byte $0d, $75, $ab
    .byte $0a, $de, $eb
    .byte $0a, $de, $eb
    .byte $09, $ee, $00
    .byte $39, $54, $00
    .byte $2e, $00, $00
    .byte $2e, $00, $00
    .byte $e0, $00, $00
    .byte $00

// --- bankL1/engine0
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $ae, $00
    .byte $00, $ae, $00
    .byte $00, $aa, $30
    .byte $00, $eb, $20
    .byte $0c, $ff, $e0
    .byte $08, $eb, $70
    .byte $08, $eb, $70
    .byte $0b, $eb, $ac
    .byte $0d, $7d, $6c
    .byte $0a, $d7, $6b
    .byte $0a, $d7, $6b
    .byte $39, $eb, $bb
    .byte $29, $55, $80
    .byte $ee, $be, $00
    .byte $ee, $be, $00
    .byte $00, $28, $00
    .byte $00

// --- bankL1/engine1
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $ae, $00
    .byte $00, $ae, $00
    .byte $00, $aa, $30
    .byte $00, $eb, $20
    .byte $0c, $ff, $e0
    .byte $08, $eb, $70
    .byte $08, $eb, $70
    .byte $0b, $eb, $ac
    .byte $0d, $7d, $6c
    .byte $0a, $d7, $6b
    .byte $0a, $d7, $6b
    .byte $39, $eb, $bb
    .byte $29, $55, $80
    .byte $ee, $28, $00
    .byte $ee, $28, $00
    .byte $00, $00, $00
    .byte $00

// --- bankL1/engine2
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $ae, $00
    .byte $00, $ae, $00
    .byte $00, $aa, $30
    .byte $00, $eb, $20
    .byte $0c, $ff, $e0
    .byte $08, $eb, $70
    .byte $08, $eb, $70
    .byte $0b, $eb, $ac
    .byte $0d, $7d, $6c
    .byte $0a, $d7, $6b
    .byte $0a, $d7, $6b
    .byte $39, $eb, $bb
    .byte $29, $55, $80
    .byte $ee, $00, $00
    .byte $ee, $00, $00
    .byte $00, $00, $00
    .byte $00

// --- neutral/engine0
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $aa, $00
    .byte $0c, $eb, $30
    .byte $08, $ff, $20
    .byte $0b, $eb, $e0
    .byte $0b, $eb, $e0
    .byte $0d, $eb, $70
    .byte $3a, $7d, $ac
    .byte $39, $d7, $6c
    .byte $39, $d7, $6c
    .byte $e9, $eb, $6b
    .byte $ee, $55, $bb
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $28, $00
    .byte $00

// --- neutral/engine1
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $aa, $00
    .byte $0c, $eb, $30
    .byte $08, $ff, $20
    .byte $0b, $eb, $e0
    .byte $0b, $eb, $e0
    .byte $0d, $eb, $70
    .byte $3a, $7d, $ac
    .byte $39, $d7, $6c
    .byte $39, $d7, $6c
    .byte $e9, $eb, $6b
    .byte $ee, $55, $bb
    .byte $00, $28, $00
    .byte $00, $28, $00
    .byte $00, $00, $00
    .byte $00

// --- neutral/engine2
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $aa, $00
    .byte $0c, $eb, $30
    .byte $08, $ff, $20
    .byte $0b, $eb, $e0
    .byte $0b, $eb, $e0
    .byte $0d, $eb, $70
    .byte $3a, $7d, $ac
    .byte $39, $d7, $6c
    .byte $39, $d7, $6c
    .byte $e9, $eb, $6b
    .byte $ee, $55, $bb
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00

// --- bankR1/engine0
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $ba, $00
    .byte $00, $ba, $00
    .byte $0c, $aa, $00
    .byte $08, $eb, $00
    .byte $0b, $ff, $30
    .byte $0d, $eb, $20
    .byte $0d, $eb, $20
    .byte $3a, $eb, $e0
    .byte $39, $7d, $70
    .byte $e9, $d7, $a0
    .byte $e9, $d7, $a0
    .byte $ee, $eb, $6c
    .byte $02, $55, $68
    .byte $00, $be, $bb
    .byte $00, $be, $bb
    .byte $00, $28, $00
    .byte $00

// --- bankR1/engine1
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $ba, $00
    .byte $00, $ba, $00
    .byte $0c, $aa, $00
    .byte $08, $eb, $00
    .byte $0b, $ff, $30
    .byte $0d, $eb, $20
    .byte $0d, $eb, $20
    .byte $3a, $eb, $e0
    .byte $39, $7d, $70
    .byte $e9, $d7, $a0
    .byte $e9, $d7, $a0
    .byte $ee, $eb, $6c
    .byte $02, $55, $68
    .byte $00, $28, $bb
    .byte $00, $28, $bb
    .byte $00, $00, $00
    .byte $00

// --- bankR1/engine2
    .byte $00, $3c, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $be, $00
    .byte $00, $ba, $00
    .byte $00, $ba, $00
    .byte $0c, $aa, $00
    .byte $08, $eb, $00
    .byte $0b, $ff, $30
    .byte $0d, $eb, $20
    .byte $0d, $eb, $20
    .byte $3a, $eb, $e0
    .byte $39, $7d, $70
    .byte $e9, $d7, $a0
    .byte $e9, $d7, $a0
    .byte $ee, $eb, $6c
    .byte $02, $55, $68
    .byte $00, $00, $bb
    .byte $00, $00, $bb
    .byte $00, $00, $00
    .byte $00

// --- bankR2/engine0
    .byte $00, $0c, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $03, $2e, $00
    .byte $03, $2e, $00
    .byte $02, $2a, $00
    .byte $02, $fa, $00
    .byte $03, $7e, $30
    .byte $3a, $bb, $20
    .byte $3a, $bb, $20
    .byte $3a, $7b, $e0
    .byte $ea, $5d, $70
    .byte $eb, $b7, $a0
    .byte $eb, $b7, $a0
    .byte $00, $bb, $60
    .byte $00, $15, $6c
    .byte $00, $2e, $b8
    .byte $00, $2e, $b8
    .byte $00, $08, $0b
    .byte $00

// --- bankR2/engine1
    .byte $00, $0c, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $03, $2e, $00
    .byte $03, $2e, $00
    .byte $02, $2a, $00
    .byte $02, $fa, $00
    .byte $03, $7e, $30
    .byte $3a, $bb, $20
    .byte $3a, $bb, $20
    .byte $3a, $7b, $e0
    .byte $ea, $5d, $70
    .byte $eb, $b7, $a0
    .byte $eb, $b7, $a0
    .byte $00, $bb, $60
    .byte $00, $15, $6c
    .byte $00, $08, $b8
    .byte $00, $08, $b8
    .byte $00, $00, $0b
    .byte $00

// --- bankR2/engine2
    .byte $00, $0c, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $00, $2e, $00
    .byte $03, $2e, $00
    .byte $03, $2e, $00
    .byte $02, $2a, $00
    .byte $02, $fa, $00
    .byte $03, $7e, $30
    .byte $3a, $bb, $20
    .byte $3a, $bb, $20
    .byte $3a, $7b, $e0
    .byte $ea, $5d, $70
    .byte $eb, $b7, $a0
    .byte $eb, $b7, $a0
    .byte $00, $bb, $60
    .byte $00, $15, $6c
    .byte $00, $00, $b8
    .byte $00, $00, $b8
    .byte $00, $00, $0b
    .byte $00

