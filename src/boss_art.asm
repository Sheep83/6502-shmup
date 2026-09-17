// ===========================================================================
// boss_art.asm — the placeholder end-of-level boss, four multicolour cells
// ===========================================================================
// ONE PICTURE, CUT INTO FOUR. The boss was drawn as a single 24 x 42
// multicolour image and split into four 12 x 21 sprite cells laid out 2 x 2:
//
//     +--------+--------+      cell 0   cell 1        48 x 42 screen pixels
//     | cell 0 | cell 1 |      cell 2   cell 3        unexpanded
//     +--------+--------+
//     | cell 2 | cell 3 |      The joins run through the middle of the core
//     +--------+--------+      DELIBERATELY: a seam that nothing crosses is a
//                              seam the eye finds, so the brightest feature in
//                              the picture is the one that spans both.
//
// THE CELLS ARE VISUAL PIECES OF ONE ENTITY. They are not four enemies: the
// boss has one position, one HP counter and one death, all in src/boss.asm.
// Nothing here is addressable as a target.
//
// ---------------------------------------------------------------------------
// PALETTE
// ---------------------------------------------------------------------------
//   %00  TRANSPARENT   the sky around the hull and between the legs
//   %01  $d025         SPR_MC_DARK, dark grey -- the armoured structure, and
//                      the shared colour every gameplay sprite already uses
//   %10  $d027 per cell  THE BOSS'S OWN COLOUR. All four cells carry the same
//                      value (BOSS_COL), so the reactor reads as one object;
//                      it is also the register the hit flash moves, which is
//                      why a hit lights the WHOLE boss rather than a corner
//   %11  $d026         SPR_MC_LIGHT, white -- the core and the hull highlights
//
// Nothing global moves: the two shared registers already hold dark grey and
// white, and the private one is per-sprite by construction.
//
// ---------------------------------------------------------------------------
// WHERE IT LIVES
// ---------------------------------------------------------------------------
// $3580-$367f, four 64-byte blocks, pointers $d6-$d9. That is the four-block
// run the Ring vacated when the enemy window became one contiguous region --
// the only contiguous four-block run in the bank outside the level enemy
// window, which belongs to a level package and must not be squatted on.
//
// tests/test_level_assets.py asserted that run was still all zeros, as proof
// the Ring migration had completed. It is now occupied by engine-owned boss
// art, so that assertion was restated to check what it actually meant: that
// the RING's artwork is not there. See the report.
// ===========================================================================

.if ((BOSS_SPRITES & 63) != 0) {
    .error "the boss cells must be 64-byte aligned"
}
.if (BOSS_SPRITES < HUD_SPRITES_END) {
    .error "the boss cells overlap the HUD's sprite bitmaps"
}
.if (BOSS_SPRITES_END > $3680) {
    .error "the boss cells have run into the clip scratch at $3680"
}

* = BOSS_SPRITES "boss cells"
bossArt:
// --- cell 0: top left ------------------------------------
bossCell0:
    .byte $00,$55,$00               //     kkkk    
    .byte $01,$55,$40               //    kkkkkk   
    .byte $05,$7d,$50               //   kkkWWkkk  
    .byte $05,$7d,$54               //   kkkWWkkkk 
    .byte $05,$55,$55               //   kkkkkkkkkk
    .byte $15,$55,$55               //  kkkkkkkkkkk
    .byte $15,$55,$55               //  kkkkkkkkkkk
    .byte $55,$55,$55               // kkkkkkkkkkkk
    .byte $57,$d5,$55               // kkkWWkkkkkkk
    .byte $57,$d5,$55               // kkkWWkkkkkkk
    .byte $55,$55,$55               // kkkkkkkkkkkk
    .byte $55,$55,$aa               // kkkkkkkkBBBB
    .byte $55,$56,$aa               // kkkkkkkBBBBB
    .byte $55,$5a,$aa               // kkkkkkBBBBBB
    .byte $55,$6a,$af               // kkkkkBBBBBWW
    .byte $55,$aa,$bf               // kkkkBBBBBWWW
    .byte $55,$aa,$ff               // kkkkBBBBWWWW
    .byte $56,$aa,$ff               // kkkBBBBBWWWW
    .byte $56,$ab,$ff               // kkkBBBBWWWWW
    .byte $56,$ab,$ff               // kkkBBBBWWWWW
    .byte $56,$ab,$ff               // kkkBBBBWWWWW
    .byte $00                       // the 64th byte, never fetched
// --- cell 1: top right -----------------------------------
bossCell1:
    .byte $00,$55,$00               //     kkkk    
    .byte $01,$55,$40               //    kkkkkk   
    .byte $05,$7d,$50               //   kkkWWkkk  
    .byte $15,$7d,$50               //  kkkkWWkkk  
    .byte $55,$55,$50               // kkkkkkkkkk  
    .byte $55,$55,$54               // kkkkkkkkkkk 
    .byte $55,$55,$54               // kkkkkkkkkkk 
    .byte $55,$55,$55               // kkkkkkkkkkkk
    .byte $55,$57,$d5               // kkkkkkkWWkkk
    .byte $55,$57,$d5               // kkkkkkkWWkkk
    .byte $55,$55,$55               // kkkkkkkkkkkk
    .byte $aa,$55,$55               // BBBBkkkkkkkk
    .byte $aa,$95,$55               // BBBBBkkkkkkk
    .byte $aa,$a5,$55               // BBBBBBkkkkkk
    .byte $fa,$a9,$55               // WWBBBBBkkkkk
    .byte $fe,$aa,$55               // WWWBBBBBkkkk
    .byte $ff,$aa,$55               // WWWWBBBBkkkk
    .byte $ff,$aa,$95               // WWWWBBBBBkkk
    .byte $ff,$ea,$95               // WWWWWBBBBkkk
    .byte $ff,$ea,$95               // WWWWWBBBBkkk
    .byte $ff,$ea,$95               // WWWWWBBBBkkk
    .byte $00                       // the 64th byte, never fetched
// --- cell 2: bottom left ---------------------------------
bossCell2:
    .byte $56,$ab,$ff               // kkkBBBBWWWWW
    .byte $56,$ab,$ff               // kkkBBBBWWWWW
    .byte $56,$aa,$ff               // kkkBBBBBWWWW
    .byte $55,$aa,$ff               // kkkkBBBBWWWW
    .byte $55,$aa,$bf               // kkkkBBBBBWWW
    .byte $55,$6a,$af               // kkkkkBBBBBWW
    .byte $55,$5a,$aa               // kkkkkkBBBBBB
    .byte $55,$56,$aa               // kkkkkkkBBBBB
    .byte $55,$55,$aa               // kkkkkkkkBBBB
    .byte $55,$55,$55               // kkkkkkkkkkkk
    .byte $57,$d5,$55               // kkkWWkkkkkkk
    .byte $57,$d5,$55               // kkkWWkkkkkkk
    .byte $55,$55,$55               // kkkkkkkkkkkk
    .byte $15,$55,$55               //  kkkkkkkkkkk
    .byte $15,$55,$55               //  kkkkkkkkkkk
    .byte $05,$55,$50               //   kkkkkkkk  
    .byte $05,$55,$40               //   kkkkkkk   
    .byte $05,$f5,$40               //   kkWWkkk   
    .byte $05,$f5,$00               //   kkWWkk    
    .byte $01,$54,$00               //    kkkk     
    .byte $01,$50,$00               //    kkk      
    .byte $00                       // the 64th byte, never fetched
// --- cell 3: bottom right --------------------------------
bossCell3:
    .byte $ff,$ea,$95               // WWWWWBBBBkkk
    .byte $ff,$ea,$95               // WWWWWBBBBkkk
    .byte $ff,$aa,$95               // WWWWBBBBBkkk
    .byte $ff,$aa,$55               // WWWWBBBBkkkk
    .byte $fe,$aa,$55               // WWWBBBBBkkkk
    .byte $fa,$a9,$55               // WWBBBBBkkkkk
    .byte $aa,$a5,$55               // BBBBBBkkkkkk
    .byte $aa,$95,$55               // BBBBBkkkkkkk
    .byte $aa,$55,$55               // BBBBkkkkkkkk
    .byte $55,$55,$55               // kkkkkkkkkkkk
    .byte $55,$57,$d5               // kkkkkkkWWkkk
    .byte $55,$57,$d5               // kkkkkkkWWkkk
    .byte $55,$55,$55               // kkkkkkkkkkkk
    .byte $55,$55,$54               // kkkkkkkkkkk 
    .byte $55,$55,$54               // kkkkkkkkkkk 
    .byte $05,$55,$50               //   kkkkkkkk  
    .byte $01,$55,$50               //    kkkkkkk  
    .byte $01,$5f,$50               //    kkkWWkk  
    .byte $00,$5f,$50               //     kkWWkk  
    .byte $00,$15,$40               //      kkkk   
    .byte $00,$05,$40               //       kkk   
    .byte $00                       // the 64th byte, never fetched
bossArtEnd:

.if (bossArtEnd - bossArt != BOSS_CELLS * 64) {
    .error "the boss art is not exactly BOSS_CELLS 64-byte blocks"
}
.if (bossCell1 - bossCell0 != 64) {
    .error "the boss cells are not adjacent: the pointer walk assumes they are"
}
