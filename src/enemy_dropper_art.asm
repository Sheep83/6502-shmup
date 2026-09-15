// ===========================================================================
// enemy_dropper_art.asm — the Orbital Dropper: four multicolour frames
// ===========================================================================
// SUPPLIED ARTWORK, checked in with its data bytes exactly as delivered. Two
// things about the FILE changed and nothing about the picture: the comment
// syntax, `;` to KickAssembler's `//`, and the removal of a `.align $40` that
// the caller's pinned-and-asserted segment address makes redundant. Not one
// data byte was touched.
//
//     %00  transparent
//     %01  $d025, SPR_MC_DARK   -- shared dark grey: INTERNAL SHADE ONLY
//     %10  $d027+n              -- THIS enemy's own colour: THE ORB ITSELF,
//                                  and the satellites
//     %11  $d026, SPR_MC_LIGHT  -- shared white: the specular, and the
//                                  satellite core
//
// THE ORB IS DRAWN IN THE SPRITE'S PRIVATE COLOUR, which is the whole point of
// this revision and worth stating plainly because it inverts what the first
// version did. That one spent pair 01 on the entire orb body and left pair 10
// for four satellite pixels -- so every Dropper on screen was the same shared
// dark grey whatever its wave had authored, and dark grey is also the terrain's
// own $d023. It read as a heavy grey lump that sank into the background.
//
// Now roughly seventy of the lit pixels are pair 10. The authored wave colour
// therefore carries the object, the enemy is as legible as the Sonic Ring, and
// two waves of Droppers in different colours are actually distinguishable.
//
// NO OUTLINE IS SPENT ON THE SILHOUETTE. Transparency defines the edge, so the
// dozen pair-01 pixels that remain are free to do the only job they are good
// at: a shadow down the lower right, which is what makes a flat disc read as a
// sphere. That is also why this artwork does not depend on the shared dark
// being any particular colour -- it is shading under a lit body, not an ink
// line around one.
//
// THE FOUR FRAMES. The orb is identical in all of them; only the satellites
// move:
//
//     0  wide         TWO satellites, out at the far left and right edges --
//                     the widest apparent separation, seen side-on. This is
//                     the only frame whose silhouette is wider than the orb.
//     1  front-right  ONE satellite crossing the orb, right of centre
//     2  front        ...at centre
//     3  front-left   ...left of centre
//
// A satellite in front of the orb is a white pixel pair against the body
// colour; out at the rim it is white with the body colour beside it. The
// supplied header notes that REVERSE PLAYBACK completes the apparent orbit,
// which is why the engine walks these as a ping-pong rather than wrapping 3
// back to 0 -- see the sequence table in src/enemy.asm.
//
// The caller sets the segment and owns the addresses; this file emits bytes
// and nothing else.
// ===========================================================================

orbitalDropperFrames:
orbitalDropper_0_wide:
    .byte $00,$00,$00,$00,$00,$00,$00,$00
    .byte $00,$00,$BE,$00,$02,$FE,$80,$0B
    .byte $FF,$A0,$0B,$FF,$A0,$0A,$FF,$A0
    .byte $0A,$BE,$60,$8A,$AA,$62,$EA,$AA
    .byte $6B,$8A,$AA,$62,$0A,$A9,$60,$0A
    .byte $A9,$60,$0A,$A5,$A0,$02,$A6,$80
    .byte $00,$9A,$00,$00,$28,$00,$00,$00
    .byte $00,$00,$00,$00,$00,$00,$00,$00

orbitalDropper_1_front_right:
    .byte $00,$00,$00,$00,$00,$00,$00,$00
    .byte $00,$00,$BE,$00,$02,$FE,$80,$0B
    .byte $FF,$A0,$0B,$FF,$A0,$0A,$FF,$A0
    .byte $0A,$BE,$60,$0A,$AA,$60,$0A,$AA
    .byte $E0,$0A,$AA,$60,$0A,$A9,$60,$0A
    .byte $A9,$60,$0A,$A5,$A0,$02,$A6,$80
    .byte $00,$9A,$00,$00,$28,$00,$00,$00
    .byte $00,$00,$00,$00,$00,$00,$00,$00

orbitalDropper_2_front:
    .byte $00,$00,$00,$00,$00,$00,$00,$00
    .byte $00,$00,$BE,$00,$02,$FE,$80,$0B
    .byte $FF,$A0,$0B,$FF,$A0,$0A,$FF,$A0
    .byte $0A,$BE,$60,$0A,$AA,$60,$0A,$AE
    .byte $60,$0A,$AA,$60,$0A,$A9,$60,$0A
    .byte $A9,$60,$0A,$A5,$A0,$02,$A6,$80
    .byte $00,$9A,$00,$00,$28,$00,$00,$00
    .byte $00,$00,$00,$00,$00,$00,$00,$00

orbitalDropper_3_front_left:
    .byte $00,$00,$00,$00,$00,$00,$00,$00
    .byte $00,$00,$BE,$00,$02,$FE,$80,$0B
    .byte $FF,$A0,$0B,$FF,$A0,$0A,$FF,$A0
    .byte $0A,$BE,$60,$0A,$AA,$60,$0B,$AA
    .byte $60,$0A,$AA,$60,$0A,$A9,$60,$0A
    .byte $A9,$60,$0A,$A5,$A0,$02,$A6,$80
    .byte $00,$9A,$00,$00,$28,$00,$00,$00
    .byte $00,$00,$00,$00,$00,$00,$00,$00
orbitalDropperFramesEnd:
