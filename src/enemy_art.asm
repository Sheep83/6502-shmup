// ===========================================================================
// enemy_art.asm — the Sonic Ring: four multicolour frames of one enemy
// ===========================================================================
// SUPPLIED ARTWORK, checked in exactly as delivered. No tool generates it and
// nothing in the engine rewrites it; only the comment syntax was changed from
// `;` to KickAssembler's `//`, and not one data byte was touched.
//
// Four 64-byte frames in rotation order, each 63 bitmap bytes plus the pad
// byte the VIC never fetches:
//
//     sonicRing_north -> sonicRing_east -> sonicRing_south -> sonicRing_west
//
// THE SILHOUETTE IS IDENTICAL IN ALL FOUR. Only a four-pixel white specular
// highlight moves, travelling clockwise around the rim -- top, right, bottom,
// left. That is what makes the cycle read as ONE object spinning rather than
// as four different sprites being swapped, and it is why the frames may be
// shown in any phase without the shape appearing to jump.
//
// Its pixel semantics are already the engine's canonical ones, so the bytes
// reach the VIC meaning what the artist drew (see the palette note in
// src/main.asm):
//
//     %00  transparent
//     %01  $d025, SPR_MC_DARK   -- shared dark grey: the ring's structure
//     %10  $d027+n              -- THIS enemy's own colour: the rim accent,
//                                  which is how a wave's authored colour still
//                                  reaches the screen
//     %11  $d026, SPR_MC_LIGHT  -- shared white: the rotating specular
//
// The caller sets the segment and owns the addresses; this file emits bytes
// and nothing else.
// ===========================================================================

sonicRingFrames:
sonicRing_north:
    .byte $01,$F5,$40,$05,$D5,$50,$16,$75
    .byte $94,$1A,$55,$A4,$59,$00,$65,$64
    .byte $00,$19,$64,$00,$19,$64,$00,$19
    .byte $64,$00,$19,$64,$00,$19,$64,$00
    .byte $19,$64,$00,$19,$64,$00,$19,$64
    .byte $00,$19,$64,$00,$19,$59,$00,$65
    .byte $1A,$55,$A4,$16,$AA,$94,$05,$AA
    .byte $50,$01,$55,$40,$00,$55,$00,$00

sonicRing_east:
    .byte $01,$55,$40,$05,$AA,$50,$16,$AA
    .byte $94,$1A,$55,$A4,$59,$00,$65,$64
    .byte $00,$19,$64,$00,$19,$64,$00,$19
    .byte $64,$00,$1F,$64,$00,$17,$64,$00
    .byte $1D,$64,$00,$15,$64,$00,$15,$64
    .byte $00,$19,$64,$00,$19,$59,$00,$65
    .byte $1A,$55,$A4,$16,$AA,$94,$05,$AA
    .byte $50,$01,$55,$40,$00,$55,$00,$00

sonicRing_south:
    .byte $01,$55,$40,$05,$AA,$50,$16,$AA
    .byte $94,$1A,$55,$A4,$59,$00,$65,$64
    .byte $00,$19,$64,$00,$19,$64,$00,$19
    .byte $64,$00,$19,$64,$00,$19,$64,$00
    .byte $19,$64,$00,$19,$64,$00,$19,$64
    .byte $00,$19,$64,$00,$19,$59,$00,$65
    .byte $1A,$55,$A4,$16,$55,$94,$05,$5D
    .byte $50,$01,$5F,$40,$00,$5D,$00,$00

sonicRing_west:
    .byte $01,$55,$40,$05,$AA,$50,$16,$AA
    .byte $94,$1A,$55,$A4,$59,$00,$65,$64
    .byte $00,$19,$64,$00,$19,$64,$00,$19
    .byte $54,$00,$19,$54,$00,$19,$74,$00
    .byte $19,$D4,$00,$19,$F4,$00,$19,$64
    .byte $00,$19,$64,$00,$19,$59,$00,$65
    .byte $1A,$55,$A4,$16,$AA,$94,$05,$AA
    .byte $50,$01,$55,$40,$00,$55,$00,$00
sonicRingFramesEnd:
