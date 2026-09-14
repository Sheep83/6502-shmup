// ===========================================================================
// enemy.asm — the first production enemy: the straight diver
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is written from this file, and the
// word "slot" never appears in it in the hardware sense. An enemy knows its
// logical position and its velocity; whether it is drawn, and through which
// hardware sprite, is entirely the renderer's business.
//
// ---------------------------------------------------------------------------
// WHAT THE OLD GAME ACTUALLY DID
// ---------------------------------------------------------------------------
// Read out of shooter_test/src/main.asm. The relevant pieces are the ingress
// fragment table (5918), spawnEnemy (4860), moveEnemyPath (3055) and the art
// and colour tables at 5561 and 5808.
//
//   THE SIMPLEST ENEMY IS A STRAIGHT DIVE. The first ingress fragment in the
//   old table is ingressTopStraightShort:
//
//       .byte 48,  0,  2     // duration 48 frames, vx 0, vy 2
//
//   "Straight dive from common top entry Y", in the old file's own words. Two
//   pixels per frame downward, no horizontal component. That is the whole
//   behaviour, and it is the one this slice migrates.
//
//   VELOCITIES ARE WHOLE PIXELS PER FRAME. There is no sub-pixel accumulator
//   anywhere in the old movement code: moveEnemyPath adds OBJECT_VEL_Y to
//   OBJECT_Y directly. Kept, because inventing a fractional representation here
//   would silently change every speed the old content was authored against.
//
//   VELOCITY IS SUPPLIED AT SPAWN, NOT BAKED INTO THE TYPE. One TYPE_ENEMY,
//   many trajectories. Kept exactly: the spawn table below carries (vx, vy) per
//   entry, which is why a diagonal entry needs no new type.
//
//   REMOVAL IS A BOUNDS TEST. The old bullet path frees the moment Y passes the
//   bottom of the screen (3040). Kept as the single despawn rule.
//
// DELIBERATELY NOT TAKEN:
//   * the segmented ingress/manoeuvre/egress path machine, easeVelocityToward-
//     Target, and the whole fragment table. That IS the wave system, and it is
//     the next slice's subject rather than this one's.
//   * OBJECT_HEALTH and the impact flash. Nothing can shoot an enemy yet: the
//     Slice B shot event is still emitted every volley and still expires
//     unconsumed, exactly as it did before this file existed.
//   * the multicolour art path. This engine forces $d01c to zero -- every
//     hardware sprite is hires -- so the old bitmap is converted at ASSEMBLY
//     time, below, rather than at run time.
//
// ---------------------------------------------------------------------------
// WORLD SEMANTICS: THIS ENEMY IS SCREEN-SPACE, AND THAT IS A DECISION
// ---------------------------------------------------------------------------
// logY is a raster line, not a stage row. The enemy does not read the scroller,
// does not read worldProgress, and does not move with the terrain.
//
// That is what the old game did -- its enemies were screen-space objects with
// velocities, and only the DECISION TO SPAWN came from wave state -- and it is
// what keeps this compatible with the wave migration: a wave system asks
// worldProgress when to spawn, then hands the object a screen position and a
// vector. Nothing in this file has to change for that to work, which is the
// test of whether the boundary was drawn in the right place.
//
// The scroll direction settled in Slice A' is why vy is POSITIVE. The terrain
// moves down and the player flies up, so an enemy that approaches the player
// comes from the top of the aperture and descends. See docs/ENGINE_CONTRACT.md
// section 8a.
// ===========================================================================

// --- the numbers, from shooter_test/src/main.asm:5921 and 991-994 ----------
.const ENEMY_MAX_HP      = 6        // ENEMY_START_HEALTH, main.asm:995. TYPE
                                   // data: every enemy of this type starts
                                   // here, so no per-object maximum is stored

// The enemy bitmap goes in the last free 64-byte block of VIC bank 0, between
// the player's art and the blank charset the aperture depends on.
.const ENEMY_SPRITES     = PLAYER_SPRITES_END
.const ENEMY_PTR         = ENEMY_SPRITES / 64
.if ((ENEMY_SPRITES & 63) != 0) { .error "the enemy bitmap must be 64-byte aligned" }

// ===========================================================================
// LIFECYCLE BOUNDS — WHERE AN ENEMY MAY EXIST, NOT WHERE IT MAY BE SEEN
// ===========================================================================
// These are DERIVED from the aperture and the sprite's own size, because the
// two are different questions and v1.1 answered them with one number.
//
// THE ANCHOR. logY is the VIC sprite Y: the raster line of the sprite's TOP
// row. A sprite therefore covers logY .. logY + SPRITE_HEIGHT - 1. logX is the
// VIC sprite X, nine bits across logX/logXHi, and the sprite covers
// logX .. logX + 23; the visible display window starts at sprite X 24 and ends
// at 343.
//
// THE APERTURE is rasters APERTURE_TOP_RASTER..APERTURE_BOT_RASTER (55..247),
// the terrain playfield between the two raster splits.
//
// WHAT WENT WRONG IN v1.1. It despawned at 226 -- MAX_SPRITE_Y, the renderer's
// ADMISSION ceiling -- and treated that as the edge of the world. But the
// renderer's band is "the whole sprite is inside the aperture": it REJECTS a
// sprite outside it rather than clipping it, so 226 is where an enemy stops
// being DRAWN, not where it has left. Using it as the despawn line meant the
// object died at the instant it went invisible, and the authored spawn lines
// (56..132) put the other end of the same mistake well inside the playfield:
// enemies materialised a third of the way down the screen instead of arriving
// through an edge.
//
// SO THE LIFECYCLE IS NOW WIDER THAN THE VISIBILITY, on purpose. An enemy is
// alive and moving for as long as any part of it could still matter, and the
// renderer independently decides whether it can be drawn this frame. That
// separation is what lets an enemy fly in from off-screen.
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
// THE SPAWN TABLE IS GONE, AND THAT IS THIS SLICE'S POINT
// ===========================================================================
// There used to be four spawn entries here, cycled on a 48-frame timer, and
// the comment above them said exactly what they were: "This is NOT a wave
// system and is not the seed of one. It exists so that the lifecycle runs
// continuously on a normal boot." It did that job for three slices.
//
// src/waves.asm is the wave system, and it took the whole job over rather
// than wrapping it. A spawner still running underneath a director would be a
// second author of the same screen, and the two would fight over a pool that
// is already shared with hostile projectiles.
//
// WHAT MOVED, AND WHERE TO LOOK FOR IT:
//
//   the cadence            -> waveRunInstance's per-instance timer
//   which enemy is next    -> wvIndex, per wave instance
//   the spawn positions    -> the authored wave definitions in waves.asm
//   the colours            -> the same, one per wave rather than per entry
//   the velocities         -> the movement primitives in src/movement.asm
//   "carry set = pool full" -> unchanged, and still the allocation contract
//
// WHAT DID NOT MOVE: everything below. The art, the six HP, the hit flash,
// the death animation, the single vertical despawn rule and the pool
// discipline are what make this an ENEMY, and none of them cares who decided
// to create it. The player's hitscan, the turrets and the projectiles do not
// know src/waves.asm exists.

// ===========================================================================
// Art. The old multicolour bitmap, flattened to hires at assembly time.
// ===========================================================================
// The engine forces $d01c to zero: every hardware sprite is hires, including
// the mux slots. The old enemy was multicolour, so each two-bit pair becomes
// two hires pixels if it was set to ANY of the three colours and two blank
// pixels if it was background.
//
// That is a silhouette, not a recolour: the old art's internal shading is lost
// and the shape is kept. It is the honest conversion for a one-layer sprite --
// the player affords two layers because it owns two reserved hardware sprites,
// and a mux enemy owns one.

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
// State.
// ===========================================================================
// Moved out of $c5e0 in Slice D so the object pool's per-object arrays can grow
// contiguously. Six bytes in the hole between the P5 ring's state and the
// player's, rather than a second gap further up the page.
* = $c517 "enemy state"
// The spawn cursor and its timer left with the spawn table: src/waves.asm
// owns when an enemy is created. What stays is the count of enemies that
// reached the end of their own lives, which is this file's business and
// nobody else's -- enemyDespawn is still the ONLY place a slot is released.
enyDespawned:  .byte 0, 0               // 16-bit, saturating: total despawned
enyScratch:    .byte 0                  // enemyTick's one spare byte: the clip
                                        // arithmetic needs logY back after the
                                        // compare that classified it
enyStateEnd:
.if (enyStateEnd > $c520) { .error "the enemy state has grown into the player state at $c520" }

* = $4900 "enemy code"

// ---------------------------------------------------------------------------
// enemyInit — no enemies, and the first spawn one period away.
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
    // "A dying enemy remains renderable but no longer follows its path"
    // -- shooter_test/src/main.asm:2331. Kept: an explosion that keeps flying
    // reads as a live enemy the player cannot kill.
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
    // The whole of movement now lives in src/movement.asm: the enemy runs
    // whichever primitive its wave handed it, at quarter-pixel resolution,
    // and this file does not know or care whether that is a straight vector
    // or a phase of an arc. Two enemies from two different waves can be at
    // completely different points of completely different primitives in the
    // same call to objectUpdateAll, which is the property the encounter
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
    // TERMINATION still holds, and it is still proved rather than hoped:
    // src/waves.asm flies every authored pattern at assembly time and rejects
    // one that does not reach one of these three edges.
    //
    // THE SIDE TESTS ASK WHICH WAY THE ENEMY IS GOING, and they have to.
    // Position alone cannot tell ARRIVING from LEAVING: the echelon sweep
    // spawns at X=0 precisely so that it slides in through the left border,
    // and a rule that freed anything behind that border would kill it on its
    // first frame -- which is exactly what the first draft of this did. An
    // enemy behind a border on its way IN is alive; the same enemy behind the
    // same border on its way OUT is gone.
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
// the production band, so the builder's existing admission test refuses the
// entry, and a fully invisible enemy costs no scratch block, no mux slot and
// no schedule entry -- while remaining perfectly alive. Culling is the rule
// that was already there, not a new one.
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
// The colour ladder is the old updateEnemyHitEffects (2770-2790) exactly: the
// timer is decremented FIRST and the remaining value chooses the colour, so a
// four-frame flash shows white, white, white, yellow and then restores.
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
// is freed on the frame it reaches zero -- which is the single place in the
// game an enemy is released, so publication safety has one path to reason
// about rather than two.
//
// The old game swapped in three explosion bitmaps here. This slice keeps the
// TIMING and the COLOUR PROGRESSION and leaves the art alone: migrating
// playerExplosion1/2/3 is a graphics job, and the graphics slice is next. The
// enemy therefore dies as a bounded yellow-orange-red flash of its own shape.
// ---------------------------------------------------------------------------
enemyDeathTick:
    dec objTimer,x
    beq !release+

    lda objTimer,x                      // the old frame thresholds, 2733-2757
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
    // The death animation is over. This is a NORMAL despawn: the same call, the
    // same membership update, the same guarantee that CURRENT is not touched.
    jmp enemyDespawn

// ---------------------------------------------------------------------------
// enemyBaseColour — the colour a hit flash returns to.
// Entry/exit: X = slot, preserved.
//
// This used to DERIVE the answer, searching the spawn table for the entry
// whose velocity pair matched the object's -- one byte of table instead of
// sixteen of state, which was a good trade while a velocity pair identified a
// trajectory for life.
//
// It does not any more. An enemy's velocity now changes every few frames as
// it turns, so by the time it is hit its velocity says nothing about where it
// came from. The colour is therefore STORED, once, at spawn: src/waves.asm
// writes wmBaseCol beside the movement state it is already writing, and the
// derivation is gone rather than patched.
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
