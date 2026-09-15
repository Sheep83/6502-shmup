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

// The enemy's four animation frames, in the run between the HUD pool and the
// clip scratch block at $3680.
//
// PINNED, NOT DERIVED. It used to be PLAYER_SPRITES_END, which was true and
// self-maintaining for as long as the player sat immediately below it -- and
// silently dragged this bitmap across the bank the day the player's art moved
// to the reclaimed $2000 run. An address that follows an unrelated asset
// around is not a memory map, so this one states where it is.
//
// FOUR CONSECUTIVE BLOCKS, AND THE ORDER IS LOAD-BEARING. The animation adds a
// frame index to ENEMY_PTR_FIRST and stores the result straight into logPtr,
// so the frames must be adjacent and in rotation order -- see enemyAnimPtr.
// $3580 is the only run in the bank where four aligned blocks are free and
// contiguous: it is the three blocks the player's old hires layers vacated,
// plus the one the single placeholder bitmap used to occupy.
.const ENEMY_SPRITES     = $3580
.const ENEMY_FRAMES      = 4                        // north, east, south, west
.const ENEMY_PTR_FIRST   = ENEMY_SPRITES / 64       // $d6; frames are $d6..$d9
.if ((ENEMY_SPRITES & 63) != 0) { .error "the enemy frames must be 64-byte aligned" }
.if (ENEMY_SPRITES + ENEMY_FRAMES * 64 > BLANK_CHARSET) {
    .error "the enemy frames run into the blank charset"
}
.if (ENEMY_SPRITES < HUD_SPRITES_END) {
    .error "the enemy frames overlap the HUD bitmap pool"
}

// --- the animation cadence ---------------------------------------------------
// ENEMY_ANIM_SHIFT frames of hold per step, so a full rotation takes
// ENEMY_FRAMES << ENEMY_ANIM_SHIFT displayed frames -- 32 at these values,
// which is 0.64 s of PAL. Fast enough that the specular clearly travels round
// the rim, slow enough that it reads as a spin rather than a flicker.
//
// A SHIFT RATHER THAN A TIMER, and that is what makes this cost no state at
// all: the phase is derived from the renderer's free-running frameCounter
// instead of being counted. See enemyAnimPtr.
.const ENEMY_ANIM_SHIFT  = 3                        // 1 << 3 = 8 frames a step

// THE LOW BYTE OF frameCounter MUST CONTAIN A WHOLE NUMBER OF CYCLES, or the
// animation would stutter once every 256 frames when that byte wraps mid-step.
// 256 / 32 = 8 exactly here. This is the assertion that lets enemyAnimPtr read
// one byte and ignore the high one.
.if (mod(256, ENEMY_FRAMES << ENEMY_ANIM_SHIFT) != 0) {
    .error "a frameCounter low-byte wrap would land mid-cycle and stutter the spin"
}
.if ((ENEMY_FRAMES & (ENEMY_FRAMES - 1)) != 0) {
    .error "ENEMY_FRAMES must be a power of two: the phase is masked, not compared"
}

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
// Art. Authored multicolour, EMITTED AS AUTHORED.
// ===========================================================================
// The mux slots are multicolour from the handoff at raster 40 onwards (see
// D01C_GAMEPLAY in src/renderer.asm), so the bytes below reach the VIC meaning
// exactly what the artist drew:
//
//     pair 00   transparent
//     pair 01   $d025, SPR_MC_DARK   -- shared dark grey, the shading
//     pair 10   $d027+n              -- THIS enemy's own colour
//     pair 11   $d026, SPR_MC_LIGHT  -- shared white, the highlights
//
// PAIR 10 IS WHY EVERY ENEMY CAN STILL LOOK DIFFERENT. It is the only one of
// the three that is per-sprite, and the ring's rim accent is drawn in it, so
// wmBaseCol's authored wave colour still reaches the screen exactly as it did
// when the enemy was a single placeholder bitmap. The animation changes which
// FRAME is shown; it never touches logCol.
//
// NOTHING ABOUT CLIPPING CHANGES. src/clip.asm shifts whole ROWS of three
// bytes when an enemy straddles an aperture edge; it never looks inside a byte,
// so a multicolour row clips exactly as a hires one did. It takes its source
// from logPtr, so it follows the animation to whichever frame is live without
// knowing the enemy is animated at all.
* = ENEMY_SPRITES "enemy frames"
#import "enemy_art.asm"                 // sonicRingFrames, four 64-byte frames

// The names the rest of the engine knew this art by, kept pointing at the same
// things they always meant: the first frame's bytes, and the address the art
// ends at. src/ebullet.asm places the projectile above enemyBitmapEnd.
.label enemyBitmap    = sonicRing_north
.label enemyBitmapEnd = sonicRingFramesEnd

.if (sonicRingFramesEnd - sonicRingFrames != ENEMY_FRAMES * 64) {
    .error "the enemy art is not ENEMY_FRAMES blocks of 64 bytes"
}
// THE FRAMES MUST BE IN ROTATION ORDER AND ADJACENT, because enemyAnimPtr
// selects one by adding an index to ENEMY_PTR_FIRST rather than by looking up
// a table. Checked against the labels themselves so that reordering the art
// file is a build error rather than a scrambled spin.
.if (sonicRing_north != ENEMY_SPRITES + 0 * 64) { .error "frame 0 is not north" }
.if (sonicRing_east  != ENEMY_SPRITES + 1 * 64) { .error "frame 1 is not east"  }
.if (sonicRing_south != ENEMY_SPRITES + 2 * 64) { .error "frame 2 is not south" }
.if (sonicRing_west  != ENEMY_SPRITES + 3 * 64) { .error "frame 3 is not west"  }

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
// enemyAnimPtr — the sprite pointer every enemy should be showing THIS frame.
// Exit: A = the pointer. X and Y preserved, no memory written.
//
// ONE GLOBAL PHASE, NOT PER-OBJECT STATE, and it costs no state at all.
//
// The phase is DERIVED from the renderer's frameCounter rather than counted in
// a timer of this file's own. That is the whole trick: frameCounter already
// advances exactly once per displayed frame, in exFrame, so shifting it right
// by ENEMY_ANIM_SHIFT and masking to ENEMY_FRAMES gives a phase that steps on
// a fixed cadence for free -- no byte of state, no per-frame decrement, and
// nothing that can drift out of step with the display if a frame is ever
// skipped. The assertion beside ENEMY_ANIM_SHIFT is what allows reading only
// the LOW byte: 256 is a whole number of cycles, so the wrap is seamless.
//
// LOCKSTEP IS A DECISION, not an accident of the implementation. Every ring on
// screen spins in phase, which for a field of identical rings reads as one
// mechanism rather than as clutter. The moment an enemy type genuinely needs
// its own phase -- a second species, or a stagger -- this becomes a per-object
// byte and callers change not at all, because they already ask a routine
// rather than compute it themselves. That is the only reason this is a
// subroutine and not eight inline instructions.
// ---------------------------------------------------------------------------
enemyAnimPtr:
    lda frameCounter                    // low byte only: see the wrap assertion
    .for (var i = 0; i < ENEMY_ANIM_SHIFT; i++) {
        lsr                             // /2 per shift: hold each frame for
    }                                   // 1 << ENEMY_ANIM_SHIFT displayed frames
    and #ENEMY_FRAMES - 1               // a mask, not a compare: ENEMY_FRAMES
                                        // is asserted a power of two
    clc
    adc #ENEMY_PTR_FIRST                // the frames are adjacent and in
    rts                                 // rotation order, so this IS the lookup

// ---------------------------------------------------------------------------
// enemyTick — one frame of ONE enemy. MAIN THREAD.
// Entry/exit: X = the object's slot, PRESERVED across the free.
// ---------------------------------------------------------------------------
enemyTick:
    // ---- the spin, and it is the FIRST thing so that it is unconditional ---
    // Every enemy gets this frame's phase written into its logPtr, alive or
    // dying. Presentation only: logPtr is the sprite POINTER, so this changes
    // which of the four frames the VIC fetches and nothing else. Movement,
    // collision, HP, firing and the despawn rules below never read it.
    //
    // A dying ring keeps spinning deliberately -- the death is a colour ramp
    // over the same silhouette, and freezing the rotation half way through it
    // would read as the animation having broken rather than the enemy having.
    jsr enemyAnimPtr
    sta logPtr,x

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
// ONE COLOUR HELD FOR THE WHOLE WINDOW, where this used to walk a two-stage
// white-then-yellow ladder. The ladder existed to read as a hot flash cooling
// back toward the body colour, which needed the flash to START at a brightness
// the body could cool FROM. HIT_COL_FLASH is a hue rather than a brightness --
// see the note in src/collision.asm -- so a second stage would only muddy the
// one frame it occupied. The timing is unchanged: HIT_FLASH_TIME is 4, the
// colour is held for three frames, and the fourth restores.
// ---------------------------------------------------------------------------
enemyFlashTick:
    dec objTimer,x                      // DEC sets Z on the result, so the
    beq !expired+                       // expiry test needs no reload
    lda #HIT_COL_FLASH
    sta logCol,x
    rts
!expired:
    jmp enemyBaseColour                 // back to the spawn colour; its rts
                                        // is ours, and X is preserved

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
