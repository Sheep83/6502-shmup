// ===========================================================================
// enemy.asm — the enemy: its art, its lifecycle, its damage and its death
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is written from this file, and the
// word "slot" never appears in it in the hardware sense. An enemy knows its
// logical position and its velocity; whether it is drawn, and through which
// hardware sprite, is entirely the renderer's business.
//
// One TYPE_ENEMY with many trajectories: an enemy's path is handed to it at
// spawn by src/waves.asm and run by src/movement.asm, so a new flight pattern
// never needs a new type. What lives here is what makes an enemy an ENEMY --
// the art, the six HP, the hit flash, the death animation, the lifecycle
// bounds and the pool discipline -- and none of it cares who created it.
//
// AN ENEMY IS SCREEN-SPACE, deliberately. logY is a raster line, not a stage
// row: the enemy never reads the scroller or worldProgress and does not move
// with the terrain. The wave system asks worldProgress WHEN to spawn and then
// hands the object a screen position and a vector; that is the whole coupling.
//
// vy is POSITIVE for an approaching enemy because the terrain scrolls down and
// the player flies up, so an attacker enters at the top of the aperture and
// descends. See docs/ENGINE_CONTRACT.md section 8a.
// ===========================================================================

.const ENEMY_MAX_HP      = 6        // TYPE data: every enemy starts here, so
                                   // no per-object maximum is stored

// The enemy bitmap, in the run between the HUD/player pool and the blank
// charset the aperture depends on.
//
// PINNED, NOT DERIVED. It used to be PLAYER_SPRITES_END, which was true and
// self-maintaining for as long as the player sat immediately below it -- and
// silently dragged this bitmap across the bank the day the player's art moved
// to the reclaimed $2000 run. An address that follows an unrelated asset
// around is not a memory map, so this one states where it is.
.const ENEMY_SPRITES     = $3640
.const ENEMY_PTR         = ENEMY_SPRITES / 64       // $d9
.if ((ENEMY_SPRITES & 63) != 0) { .error "the enemy bitmap must be 64-byte aligned" }
.if (ENEMY_SPRITES + 64 > BLANK_CHARSET) { .error "the enemy bitmap runs into the blank charset" }

// ===========================================================================
// LIFECYCLE BOUNDS — WHERE AN ENEMY MAY EXIST, NOT WHERE IT MAY BE SEEN
// ===========================================================================
// WHERE AN ENEMY MAY EXIST IS A WIDER QUESTION THAN WHERE IT MAY BE SEEN, and
// these bounds answer the first. They are DERIVED from the aperture and the
// sprite's size, never borrowed from the renderer's admission band.
//
// THE ANCHOR. logY is the VIC sprite Y: the raster line of the sprite's TOP
// row, so a sprite covers logY .. logY + SPRITE_HEIGHT - 1. logX is the VIC
// sprite X, nine bits across logX/logXHi, covering logX .. logX + 23; the
// visible display window runs from sprite X 24 to 343.
//
// THE APERTURE is rasters APERTURE_TOP_RASTER..APERTURE_BOT_RASTER (55..247),
// the terrain playfield between the two raster splits.
//
// DO NOT COLLAPSE THE TWO. MAX_SPRITE_Y (226) is where an enemy stops being
// DRAWN -- the builder's band means "the whole sprite is inside the aperture"
// and rejects rather than clips. Despawning there would kill the object at the
// instant it went invisible, and the mirror of that mistake at the top makes
// enemies materialise a third of the way down the screen instead of arriving
// through an edge. An enemy is alive and moving for as long as any part of it
// could still matter; the renderer independently decides whether it can be
// drawn this frame, and that separation is what lets one fly in off-screen.
.const ENEMY_HIDDEN_Y = APERTURE_TOP_RASTER - SPRITE_HEIGHT   // 34
                                    // the LAST Y at which a sprite is still
                                    // entirely above the aperture. Spawn here
                                    // or above and nothing is on screen yet.
.const ENEMY_CLEAR_Y  = APERTURE_BOT_RASTER + 1               // 248
                                    // the FIRST Y at which the sprite's top is
                                    // past the bottom of the aperture, so
                                    // nothing of it remains inside.

// SIDE CLEARANCE. The renderer admits on Y ALONE -- there is no X test in the
// builder -- so a sprite that is half off the left or right edge is scheduled
// normally and the VIC clips it in hardware. Side crossings therefore look
// exactly right without anything being added to the renderer, and these bounds
// exist to free the object once the hardware has finished clipping it.
//
// THE LEFT BOUND IS ALSO A WRAP GUARD, and that is the load-bearing half.
// logX/logXHi are UNSIGNED: the builder reads `lda logXHi / bne msbSet`, so any
// non-zero high byte sets the X MSB. An enemy allowed to walk past zero would
// borrow logXHi down to $ff and reappear 256 pixels to the RIGHT -- a sprite
// teleporting across the screen, not a sprite leaving it. Freeing at
// ENEMY_CLEAR_X_LEFT keeps the coordinate positive at all times, so nothing
// below needs to represent a negative X and no renderer special case is
// required.
.const ENEMY_CLEAR_X_LEFT  = 4      // 9-bit X below this: the sprite covers
                                    // 0..27 at most, of which only columns
                                    // 24..27 are inside the display window --
                                    // a four-pixel sliver, and the last safe
                                    // moment to free before the borrow.
.const ENEMY_CLEAR_X_RIGHT = 344    // first 9-bit X entirely past the display
                                    // window's last column (343)
.const ENEMY_CLEAR_X_RIGHT_LO = ENEMY_CLEAR_X_RIGHT - 256     // 88

// The bounds are DERIVED above, so what is checked here is that the things
// they were derived FROM still mean what this file thinks they mean.
.if (ENEMY_HIDDEN_Y + SPRITE_HEIGHT != MIN_SPRITE_Y) {
    .error "the hidden-above line no longer sits one sprite above the aperture"
}
.if (ENEMY_CLEAR_Y <= MAX_SPRITE_Y) {
    .error "the clear-below line is inside the renderer's admission band"
}
.if (ENEMY_CLEAR_Y > 255) {
    .error "the clear-below line does not fit the eight bits logY has"
}
.if (ENEMY_CLEAR_X_RIGHT_LO < 0 || ENEMY_CLEAR_X_RIGHT_LO > 255) {
    .error "the right clearance does not split into a high byte of exactly one"
}
// The matching speed check -- that one frame's movement cannot step OVER the
// left clearance window and reach a negative X unseen -- lives in
// src/movement.asm, because WM_ARC_SPEED is defined there and KickAssembler
// resolves constants strictly in import order.

// ===========================================================================
// Art. Authored as multicolour, flattened to hires at ASSEMBLY time.
// ===========================================================================
// The engine forces $d01c to zero, so every hardware sprite is hires including
// the mux slots. Each two-bit pair of the source becomes two lit pixels if it
// named any of the three colours and two blank pixels if it was background.
//
// That is a silhouette, not a recolour: the shading is lost and the shape is
// kept. It is the honest conversion for a one-layer sprite -- the player
// affords two layers because it owns two reserved hardware sprites, and a mux
// enemy owns one.

// One multicolour byte to one hires byte: every non-background pair lit.
.function enemyHires(b) {
    .var v = 0
    .for (var p = 0; p < 4; p++) {
        .var sh = 6 - 2 * p
        .if (((b >> sh) & 3) != 0) { .eval v = v | (3 << sh) }
    }
    .return v
}

.var enemyMC = List()
.eval enemyMC.add($00,$28,$00)
.eval enemyMC.add($00,$aa,$00)
.eval enemyMC.add($00,$be,$00)
.eval enemyMC.add($02,$be,$80)
.eval enemyMC.add($02,$7d,$80)
.eval enemyMC.add($0a,$7d,$a0)
.eval enemyMC.add($29,$69,$68)
.eval enemyMC.add($a5,$aa,$5a)
.eval enemyMC.add($96,$be,$96)
.eval enemyMC.add($06,$ff,$90)
.eval enemyMC.add($06,$eb,$90)
.eval enemyMC.add($06,$aa,$90)
.eval enemyMC.add($01,$aa,$40)
.eval enemyMC.add($01,$69,$40)
.eval enemyMC.add($00,$69,$00)
.eval enemyMC.add($00,$7d,$00)
.eval enemyMC.add($01,$41,$40)
.eval enemyMC.add($05,$00,$50)
.eval enemyMC.add($14,$00,$14)
.eval enemyMC.add($00,$00,$00)
.eval enemyMC.add($00,$00,$00)

.if (enemyMC.size() != 21 * 3) { .error "the enemy bitmap must be 21 rows of 3 bytes" }

* = ENEMY_SPRITES "enemy bitmap"
enemyBitmap:
.for (var r = 0; r < 21; r++) {
    .for (var c = 0; c < 3; c++) {
        .byte enemyHires(enemyMC.get(r * 3 + c))
    }
}
    .byte $00                           // 64th padding byte
enemyBitmapEnd:
.if (enemyBitmapEnd - enemyBitmap != 64) { .error "the enemy bitmap must be exactly 64 bytes" }
.if (enemyBitmapEnd > BLANK_CHARSET) { .error "the enemy bitmap has run into the blank charset" }

// ===========================================================================
// State. MAIN THREAD ONLY, three bytes in a hole below the player's state.
// ===========================================================================
* = $c517 "enemy state"
enyDespawned:  .byte 0, 0               // 16-bit, saturating: total despawned.
                                        // enemyDespawn is the ONLY place an
                                        // enemy's slot is released, so this
                                        // counts every enemy life that ended
enyScratch:    .byte 0                  // enemyTick's one spare byte: the clip
                                        // arithmetic needs logY back after the
                                        // compare that classified it
enyStateEnd:
.if (enyStateEnd > $c51a) { .error "the enemy state has grown into the player state at $c51a" }

* = $4900 "enemy code"

// ---------------------------------------------------------------------------
// enemyInit — clear the despawn tally. The pool itself is objectInit's job.
// ---------------------------------------------------------------------------
enemyInit:
    lda #0
    sta enyDespawned
    sta enyDespawned + 1
    rts

// ---------------------------------------------------------------------------
// enemyTick — one frame of ONE enemy. MAIN THREAD.
// Entry/exit: X = the object's slot, PRESERVED across the free.
// ---------------------------------------------------------------------------
enemyTick:
    // ---- dying enemies run their death out and do not move ----------------
    // A dying enemy stays renderable but stops following its path: an explosion
    // that keeps flying reads as a live enemy the player cannot kill.
    lda objHP,x
    bne !alive+
    jmp enemyDeathTick
!alive:

    // ---- the hit flash, if one is running ---------------------------------
    lda objTimer,x
    beq !noFlash+
    jsr enemyFlashTick
!noFlash:

    // ---- WHERE IT IS THIS FRAME -------------------------------------------
    // All movement lives in src/movement.asm: the enemy runs whichever
    // primitive its wave handed it, at quarter-pixel resolution, and this file
    // does not know whether that is a straight vector or a phase of an arc.
    // Two enemies from two waves can be at different points of different
    // primitives in one call to objectUpdateAll -- the property the encounter
    // director is built on.
    jsr wmTick

    // THE DESPAWN RULES: HAS THE SPRITE LEFT THE APERTURE ALTOGETHER?
    //
    // Three edges, and the enemy survives all of them until nothing of it
    // could still be inside. It is deliberately NOT the renderer's admission
    // band: an enemy above the aperture during its approach, or being clipped
    // by a side border on its way out, is alive and moving and simply not
    // drawn this frame. See the lifecycle bounds at the top of this file.
    //
    // TERMINATION IS PROVED, NOT HOPED: src/waves.asm flies every authored
    // pattern at assembly time and rejects one that never reaches an edge.
    //
    // THE SIDE TESTS ASK WHICH WAY THE ENEMY IS GOING, and they must. Position
    // alone cannot tell ARRIVING from LEAVING: the echelon sweep spawns at X=0
    // precisely so that it slides in through the left border, and a rule that
    // freed anything behind a border would kill it on its first frame. An enemy
    // behind a border on its way IN is alive; the same enemy behind the same
    // border on its way OUT is gone.
    lda logXHi,x
    beq !checkLeft+

    // High byte set, so X is 256..511: the only way out is the right edge.
    lda logX,x
    cmp #ENEMY_CLEAR_X_RIGHT_LO
    bcc !checkBottom+
    lda wmVX,x
    beq !checkBottom+                   // parked behind the border: not gone
    bmi !checkBottom+                   // coming back in
    jmp !gone+

!checkLeft:
    lda logX,x
    cmp #ENEMY_CLEAR_X_LEFT
    bcs !checkBottom+
    lda wmVX,x
    bmi !gone+                          // still travelling left: it has left

!checkBottom:
    lda logY,x
    cmp #ENEMY_CLEAR_Y
    bcc !alive+
!gone:
    jmp enemyDespawn
!alive:
    // falls through to the presentation clip

// ---------------------------------------------------------------------------
// HOW MUCH OF THIS ENEMY IS OUTSIDE THE APERTURE — presentation only.
//
// logY is NOT touched. This writes one annotation, logClip, which the schedule
// builder turns into a clamped Y and a row-shifted bitmap (src/clip.asm); the
// enemy goes on moving, colliding and dying by its true coordinate.
//
//   logY <  MIN_SPRITE_Y   c = MIN_SPRITE_Y - logY, positive: rows above
//   logY >  MAX_SPRITE_Y   c = MAX_SPRITE_Y - logY, negative: rows below
//   otherwise              0
//
// A count of SPRITE_HEIGHT or more means nothing of the sprite is inside the
// aperture at all. Those are left at zero DELIBERATELY: logY is then outside
// the admission band, so the builder's ordinary Y test refuses the entry and a
// fully invisible enemy costs no scratch block, no mux slot and no schedule
// entry -- while remaining perfectly alive.
    lda logY,x
    cmp #MIN_SPRITE_Y
    bcc !above+
    cmp #MAX_SPRITE_Y + 1
    bcs !below+
    lda #0                              // wholly inside: present as authored
    beq !store+                         // (always taken)

!above:
    sta enyScratch                      // logY, still in A
    lda #MIN_SPRITE_Y
    sec
    sbc enyScratch                      // 1..SPRITE_HEIGHT-1 while any is seen
    cmp #SPRITE_HEIGHT
    bcc !store+
    lda #0                              // entirely above: let admission cull it
    beq !store+

!below:
    sec
    sbc #MAX_SPRITE_Y                   // 1..SPRITE_HEIGHT-1, as a magnitude
    cmp #SPRITE_HEIGHT
    bcs !hidden+
    eor #$ff                            // negate: rows BELOW are negative
    clc
    adc #1
    bne !store+                         // (never zero: the magnitude was not)
!hidden:
    lda #0

!store:
    sta logClip,x
    rts

// ---------------------------------------------------------------------------
// enemyFlashTick — one frame of the hit flash. Entry/exit: X = slot, preserved.
//
// The timer is decremented FIRST and the remaining value chooses the colour,
// so a four-frame flash shows white, white, white, yellow and then restores.
// ---------------------------------------------------------------------------
enemyFlashTick:
    dec objTimer,x
    lda objTimer,x
    cmp #2
    bcs !white+
    cmp #1
    beq !yellow+
    jsr enemyBaseColour                 // expired: back to the spawn colour
    rts
!white:
    lda #HIT_COL_WHITE
    sta logCol,x
    rts
!yellow:
    lda #HIT_COL_YELLOW
    sta logCol,x
    rts

// ---------------------------------------------------------------------------
// enemyDeathTick — one frame of dying. Entry/exit: X = slot, preserved.
//
// Reached only with objHP zero. The timer runs DEATH_TIME frames and the slot
// is freed on the frame it reaches zero -- routed through enemyDespawn, so an
// enemy is released from exactly one place however it died.
//
// The explosion is a colour progression over the enemy's own shape rather than
// a bitmap swap: a bounded yellow-orange-red flash, costing no extra art.
// ---------------------------------------------------------------------------
enemyDeathTick:
    dec objTimer,x
    beq !release+

    lda objTimer,x                      // three equal thirds of DEATH_TIME
    cmp #8
    bcs !blast1+
    cmp #4
    bcs !blast2+
    lda #DEATH_COL_3
    sta logCol,x
    rts
!blast2:
    lda #DEATH_COL_2
    sta logCol,x
    rts
!blast1:
    lda #DEATH_COL_1
    sta logCol,x
    rts

!release:
    // The death animation is over. A NORMAL despawn: the same call, the same
    // membership update, the same guarantee that CURRENT is not touched.
    jmp enemyDespawn

// ---------------------------------------------------------------------------
// enemyBaseColour — the colour a hit flash returns to.
// Entry/exit: X = slot, preserved.
//
// The colour is STORED at spawn, in wmBaseCol, rather than derived from the
// enemy's velocity or wave: a composed path turns every few frames, so by the
// time an enemy is hit nothing about its current motion identifies it.
// ---------------------------------------------------------------------------
enemyBaseColour:
    lda wmBaseCol,x
    sta logCol,x
    rts

// ---------------------------------------------------------------------------
// enemyDespawn — this enemy's life ends. Entry/exit: X = slot, preserved.
//
// There is nothing to undo in the renderer. The sprite this object was drawn
// through is not "turned off": the next schedule the builder produces simply
// does not contain it, and $d015 is composed from that schedule rather than
// edited. That is the whole point of the boundary.
// ---------------------------------------------------------------------------
enemyDespawn:
    jsr objectFree

    inc enyDespawned                    // 16-bit, saturating at $ffff
    bne !counted+
    inc enyDespawned + 1
    bne !counted+
    lda #$ff
    sta enyDespawned
    sta enyDespawned + 1
!counted:
    rts

.if (* > $4c00) { .error "the enemy code has outgrown its $4900 segment" }
