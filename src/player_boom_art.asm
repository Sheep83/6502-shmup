// ===========================================================================
// player_boom_art.asm — the player's death fireball, eight multicolour frames
// ===========================================================================
// ORIGINAL ARTWORK, drawn for this engine. Eight 24x21 multicolour blocks that
// replace the ship's own silhouette on HW0 the instant the craft dies, so the
// explosion costs NO mux slot, NO schedule entry and no renderer change: it is
// the player's existing sprite wearing a different pointer for forty-eight
// frames.
//
// ---------------------------------------------------------------------------
// THE PALETTE, AND WHY IT NEEDED NO GLOBAL CHANGE
// ---------------------------------------------------------------------------
// A multicolour sprite has four codes and this engine already spends three of
// them game-wide. The fireball is drawn in exactly those, plus transparency:
//
//   %00  TRANSPARENT   the holes. Terrain shows straight through them, which
//                      is what makes the later frames read as a shape breaking
//                      apart rather than as a shape turning black.
//   %01  $d025         SPR_MC_DARK, dark grey -- shared with every gameplay
//                      sprite. Used only in the last two frames, as the smoke
//                      and the cooling embers.
//   %10  $d027 (HW0)   THIS SPRITE'S OWN REGISTER, and the whole reason the
//                      palette did not have to move: HW0's private colour is
//                      already swapped per state -- the hull is light blue,
//                      the muzzle flash is red -- so the fireball simply asks
//                      for red (PLAYER_COL_BOOM) while it burns. No enemy, no
//                      Dropper and no muzzle colour is touched.
//   %11  $d026         SPR_MC_LIGHT, white -- shared, and already white. The
//                      core is drawn in the colour the chip was already
//                      holding.
//
// So: RED from the sprite's own register, WHITE from the shared pair, and
// HOLES from transparency. Nothing global moved.
//
// ---------------------------------------------------------------------------
// THE SEQUENCE
// ---------------------------------------------------------------------------
// Authored to expand and then COME APART, never to pulse: frames 0-4 grow from
// an off-centre spark to a ragged peak, and 5-7 open holes in the core, break
// the ring into fragments and gutter out. Every frame is deliberately
// asymmetric -- these are not eight concentric circles, and no frame is a
// scaled copy of another.
//
//   0  a small violent ignition flash, off-centre
//   1  a compact white-hot burst
//   2  rapidly expanding, already irregular
//   3  large and ragged
//   4  the peak: a white core inside red lobes
//   5  the core collapsing, holes opening, fragments separating
//   6  sparse red and white fragments with the first grey embers
//   7  final scattered remnants, guttering out
//
// ---------------------------------------------------------------------------
// WHERE IT LIVES
// ---------------------------------------------------------------------------
// $25c0-$27bf, eight 64-byte blocks, pointers $97-$9e. That is the free run
// between the token bitmap and screen page B, and it is the right home rather
// than merely a vacant one: this is RESIDENT PLAYER PRESENTATION, so it sits
// with the ship at $2000 and the muzzle flash at $2400 rather than in the
// level enemy window, which a level package owns and replaces.
//
// Nothing else in the bank moved to make room.
// ===========================================================================

// The addresses, the pointer and the colour are declared in src/player.asm,
// beside the ship's own and the muzzle flash's: a sprite's address is player
// presentation, and .const resolves in import order. Only the overlap guard
// that needs a symbol from ANOTHER module can live here, where both are known.
.if (PLAYER_BOOM_SPRITES < TOKEN_SPRITE + 64) {
    .error "the fireball overlaps the collectible token's bitmap"
}

* = PLAYER_BOOM_SPRITES "player fireball"
playerBoomArt:
// --- frame 0: ignition flash --------------------------------
playerBoomFrame0:
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$20,$00               //      R      
    .byte $00,$b8,$00               //     RWR     
    .byte $02,$fe,$00               //    RWWWR    
    .byte $00,$be,$00               //     RWWR    
    .byte $00,$28,$00               //      RR     
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00                       // the 64th byte, never fetched
// --- frame 1: white-hot burst -------------------------------
playerBoomFrame1:
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$08,$00               //       R     
    .byte $00,$be,$00               //     RWWR    
    .byte $02,$ff,$80               //    RWWWWR   
    .byte $0b,$ff,$80               //   RWWWWWR   
    .byte $02,$ff,$e0               //    RWWWWWR  
    .byte $02,$ff,$80               //    RWWWWR   
    .byte $00,$be,$00               //     RWWR    
    .byte $00,$28,$00               //      RR     
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00                       // the 64th byte, never fetched
// --- frame 2: expanding fireball ----------------------------
playerBoomFrame2:
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$20,$00               //      R      
    .byte $00,$ae,$00               //     RRWR    
    .byte $02,$ff,$a0               //    RWWWWRR  
    .byte $0b,$ff,$e0               //   RWWWWWWR  
    .byte $2b,$ff,$f8               //  RRWWWWWWWR 
    .byte $2f,$ff,$f8               //  RWWWWWWWWR 
    .byte $2f,$ff,$e0               //  RWWWWWWWR  
    .byte $0b,$ff,$e0               //   RWWWWWWR  
    .byte $0a,$ff,$80               //   RRWWWWR   
    .byte $02,$fe,$80               //    RWWWRR   
    .byte $00,$a8,$00               //     RRR     
    .byte $00,$20,$00               //      R      
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00                       // the 64th byte, never fetched
// --- frame 3: large ragged fireball -------------------------
playerBoomFrame3:
    .byte $00,$00,$00               //             
    .byte $00,$80,$00               //     R       
    .byte $02,$b2,$00               //    RRW R    
    .byte $0b,$fe,$80               //   RWWWWRR   
    .byte $2f,$ff,$e0               //  RWWWWWWWR  
    .byte $af,$ff,$f8               // RRWWWWWWWWR 
    .byte $2f,$ff,$fa               //  RWWWWWWWWRR
    .byte $bf,$ff,$fe               // RWWWWWWWWWWR
    .byte $2f,$ff,$f8               //  RWWWWWWWWR 
    .byte $af,$ff,$fe               // RRWWWWWWWWWR
    .byte $2f,$ff,$f8               //  RWWWWWWWWR 
    .byte $0b,$ff,$f8               //   RWWWWWWWR 
    .byte $2b,$ff,$e0               //  RRWWWWWWR  
    .byte $0b,$ff,$80               //   RWWWWWR   
    .byte $02,$be,$80               //    RRWWRR   
    .byte $00,$b8,$00               //     RWR     
    .byte $00,$20,$00               //      R      
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00                       // the 64th byte, never fetched
// --- frame 4: peak: core and lobes --------------------------
playerBoomFrame4:
    .byte $02,$00,$00               //    R        
    .byte $0a,$c2,$00               //   RRW  R    
    .byte $2f,$ea,$e0               //  RWWWRRRWR  
    .byte $af,$ff,$f8               // RRWWWWWWWWR 
    .byte $bf,$ff,$fa               // RWWWWWWWWWRR
    .byte $bf,$ff,$fe               // RWWWWWWWWWWR
    .byte $af,$ff,$fe               // RRWWWWWWWWWR
    .byte $bf,$ff,$fe               // RWWWWWWWWWWR
    .byte $bf,$ff,$fe               // RWWWWWWWWWWR
    .byte $af,$ff,$fe               // RRWWWWWWWWWR
    .byte $bf,$ff,$fe               // RWWWWWWWWWWR
    .byte $bf,$ff,$fa               // RWWWWWWWWWRR
    .byte $af,$ff,$f8               // RRWWWWWWWWR 
    .byte $2f,$ff,$e0               //  RWWWWWWWR  
    .byte $2b,$ff,$a0               //  RRWWWWWRR  
    .byte $0b,$fe,$00               //   RWWWWR    
    .byte $02,$ba,$00               //    RRWRR    
    .byte $00,$88,$00               //     R R     
    .byte $00,$08,$00               //       R     
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00                       // the 64th byte, never fetched
// --- frame 5: collapsing, holes open ------------------------
playerBoomFrame5:
    .byte $08,$00,$80               //   R     R   
    .byte $22,$02,$80               //  R R   RR   
    .byte $8b,$8b,$82               // R RWR RWR  R
    .byte $2f,$2f,$28               //  RWW RWW RR 
    .byte $8f,$3f,$32               // R WW WWW W R
    .byte $2c,$bc,$b0               //  RW RWW RW  
    .byte $83,$cf,$08               // R  WW WW  R 
    .byte $2c,$f3,$c8               //  RW WW WW R 
    .byte $83,$c3,$0a               // R  WW  W  RR
    .byte $2c,$f3,$c8               //  RW WW WW R 
    .byte $83,$3c,$c8               // R  W WW W R 
    .byte $23,$c3,$c8               //  R WW  WW R 
    .byte $83,$3c,$20               // R  W WW  R  
    .byte $28,$f2,$80               //  RR WW RR   
    .byte $08,$f2,$00               //   R WW R    
    .byte $02,$88,$00               //    RR R     
    .byte $08,$20,$20               //   R  R   R  
    .byte $20,$08,$00               //  R    R     
    .byte $00,$08,$00               //       R     
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00                       // the 64th byte, never fetched
// --- frame 6: fragments and embers --------------------------
playerBoomFrame6:
    .byte $08,$00,$20               //   R      R  
    .byte $00,$00,$00               //             
    .byte $80,$c0,$c2               // R   W   W  R
    .byte $04,$01,$00               //   k    k    
    .byte $20,$cc,$08               //  R  W W   R 
    .byte $00,$00,$00               //             
    .byte $80,$4c,$02               // R   k W    R
    .byte $0c,$00,$30               //   W      W  
    .byte $00,$00,$00               //             
    .byte $20,$c1,$08               //  R  W  k  R 
    .byte $00,$00,$00               //             
    .byte $80,$30,$08               // R    W    R 
    .byte $04,$00,$c0               //   k     W   
    .byte $20,$00,$20               //  R       R  
    .byte $00,$00,$00               //             
    .byte $0c,$04,$00               //   W   k     
    .byte $20,$00,$80               //  R      R   
    .byte $00,$00,$00               //             
    .byte $00,$82,$00               //     R  R    
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00                       // the 64th byte, never fetched
// --- frame 7: final remnants --------------------------------
playerBoomFrame7:
    .byte $10,$00,$20               //  k       R  
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $08,$01,$00               //   R    k    
    .byte $00,$00,$00               //             
    .byte $00,$10,$00               //      k      
    .byte $00,$00,$00               //             
    .byte $10,$00,$20               //  k       R  
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $01,$00,$80               //    k    R   
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $20,$00,$10               //  R       k  
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$04,$00               //       k     
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00,$00,$00               //             
    .byte $00                       // the 64th byte, never fetched
playerBoomArtEnd:

.if (playerBoomArtEnd - playerBoomArt != PLAYER_BOOM_FRAMES * 64) {
    .error "the fireball is not exactly PLAYER_BOOM_FRAMES 64-byte blocks"
}
.if (playerBoomFrame1 - playerBoomFrame0 != 64) {
    .error "the fireball frames are not adjacent: the pointer walk assumes they are"
}
