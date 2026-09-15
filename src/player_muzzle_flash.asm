// ===========================================================================
// player_muzzle_flash_twin_bold.asm — prominent twin-gun muzzle flashes
// ===========================================================================
// Five bank-specific 64-byte multicolour sprites. Same gun alignment and
// same HW1 placement as the corrected twin-gun version.
//
// 00 transparent
// 10 HW1 private colour ($D028) = RED for BOTH visible frames
// 11 existing shared bright/white colour = white-hot core
//
// IMPORTANT: remove the earlier orange->red colour pulse in integration code.
// Set $D028 to red for the full two-frame flash instead.
//
// HW1 X = player X; HW1 Y = player Y - 7.
// Five blocks only = 320 bytes; replaces prior flash data in place.
// ===========================================================================

player_muzzle_flash_frames:
// --- bankL2
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $80
    .byte $00, $00, $c0
    .byte $00, $02, $e0
    .byte $00, $02, $e0
    .byte $08, $02, $e0
    .byte $0c, $02, $e0
    .byte $2e, $02, $a0
    .byte $2e, $00, $00
    .byte $2e, $00, $00
    .byte $2e, $00, $00
    .byte $2a, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00

// --- bankL1
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $20
    .byte $00, $00, $30
    .byte $08, $00, $b8
    .byte $0c, $00, $b8
    .byte $2e, $00, $b8
    .byte $2e, $00, $b8
    .byte $2e, $00, $a8
    .byte $2e, $00, $00
    .byte $2a, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00

// --- neutral
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $08, $00, $20
    .byte $0c, $00, $30
    .byte $2e, $00, $b8
    .byte $2e, $00, $b8
    .byte $2e, $00, $b8
    .byte $2e, $00, $b8
    .byte $2a, $00, $a8
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00

// --- bankR1
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $08, $00, $00
    .byte $0c, $00, $00
    .byte $2e, $00, $20
    .byte $2e, $00, $30
    .byte $2e, $00, $b8
    .byte $2e, $00, $b8
    .byte $2a, $00, $b8
    .byte $00, $00, $b8
    .byte $00, $00, $a8
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00

// --- bankR2
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $02, $00, $00
    .byte $03, $00, $00
    .byte $0b, $80, $00
    .byte $0b, $80, $00
    .byte $0b, $80, $20
    .byte $0b, $80, $30
    .byte $0a, $80, $b8
    .byte $00, $00, $b8
    .byte $00, $00, $b8
    .byte $00, $00, $b8
    .byte $00, $00, $a8
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00, $00, $00
    .byte $00
