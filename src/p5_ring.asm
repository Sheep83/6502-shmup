// ===========================================================================
// p5_ring.asm — P5 rotating-ring motion
// ===========================================================================
// MAIN THREAD ONLY. The raster executor never reads one byte of this file.
//
// P5 changes nothing about the renderer. It is a new source of logical X/Y and
// nothing else; the order downstream is exactly P3's and P4's and is not
// negotiable:
//
//     ringTick        moves logical X/Y on the orbit      <- here
//     sortTick        orders logical IDs by (Y, ID)
//     buildSchedule   builds NEXT under the qualified rules
//     publishSchedule one byte
//     frame IRQ       adopts CURRENT
//     executor        consumes CURRENT only
//
// There is deliberately NO ring renderer, no phase-to-slot shortcut and no
// special case anywhere below this file. A hardware slot is still earned by
// being accepted at some sorted position, and the sorter still has to discover
// the order from Y alone. If the ring were allowed to hand the builder an order
// it already knew, P5 would prove nothing that P4 had not.
//
// WHY THE MOTION IS A TABLE READ AND NOT ARITHMETIC
// P5 exists to measure the SORTER and the BUILDER under continuous reordering.
// Motion that cost real time would show up in those measurements as if the
// renderer were expensive. So the orbit is precomputed in src/p5_tables.asm as
// absolute screen coordinates, and the per-sprite cost here is an index add and
// three table reads -- about 30 cycles, 500 for all sixteen.
//
// PHASE IS 16-BIT FIXED POINT, 8 FRACTIONAL BITS
// The table index is the high byte. phaseVel = $0100 is therefore exactly one
// table step per frame, and $0800 is eight. Sub-step velocities are possible
// but are NOT used: at $0040 the index only changes every fourth frame and the
// sprites visibly stutter, which is worse for a manual test than it is slow.
//
// EVERY SPRITE IS ALWAYS ADMITTED
// Sixteen phases evenly spaced round the orbit bunch in Y at the top and bottom
// where cos(phase) ~ 0, but the reuse rule spans six sorted positions and a
// six-position span always crosses the whole cluster. Measured minimum of
// sorted_y[k+6] - sorted_y[k] over the full period is 43, against a
// MIN_REUSE_GAP of 33. So a sprite that is missing on screen is ALWAYS a fault
// and never the builder being correct -- which is what makes P5 watchable.
// See tests/p5_model.py, which asserts this over every frame of every mode.
// ===========================================================================

* = $c506 "p5 ring state"

// 16-bit fixed-point phase accumulators. Reset by loadRingFixture, advanced by
// ringTick, and read by nothing else.
ringPhase:    .byte 0, 0                // lo, hi. hi = table index.
ringPhaseVel: .byte 0, 0
ringShift:    .byte 0, 0                // RING-SHIFT sweep accumulator
ringShiftVel: .byte 0, 0                // zero = no sweep
ringActive:   .byte 0                   // 1 = motionTick must run the orbit

// Qualification counters. Cheap enough to afford, and they prove something the
// model cannot: that the ENGINE's X really crossed 255 in both directions,
// rather than the model believing it did. Everything else P5 counts -- reorder
// frames, predecessor churn, batch-shape churn -- is a pure function of the
// frame number and is counted exactly, for free, in tests/p5_model.py over the
// whole soak rather than approximately here at the cost of the thing being
// measured.
ringX255Up:   .byte 0, 0                // logical X crossings <256 -> >=256
ringX255Down: .byte 0, 0                // and back
ringOrbits:   .byte 0, 0                // phase index wrapped through zero

// ringTick locals.
rt_dy:   .byte 0                        // this frame's sweep offset, signed
rt_idx:  .byte 0                        // phase index of the sprite in hand

// RELOCATED out of VIC bank 0. The legality-window batch merge grew the
// schedule builder five bytes past the $1000..$12ff hole it has always had, and
// this is qualification-fixture code called only from motionTick and the
// fixture loader -- main thread, never the executor -- so it belongs outside
// bank 0 with the player, the scroller, the weapon, the pool and collision.
// The alternative was shaving five bytes off a routine this task had just
// rewritten, which is the worse trade.
* = $4e00 "p5 ring"

// ===========================================================================
// loadRingFixture — install a ring mode. fx_src points at the 4-byte record.
// ===========================================================================
// Record: phaseVelLo, phaseVelHi, shiftVelLo, shiftVelHi.
//
// The orbit geometry is NOT in the record. All three modes share one orbit by
// design -- RING-FAST must differ from RING-SLOW in nothing but phase velocity,
// or a difference in behaviour could not be attributed to the churn. logCount
// is fixed at P5_N_RING for the same reason.
//
// Position for frame 0 is established here by calling ringTick's body with a
// zeroed accumulator, so that "RING-SLOW, motion frame 0" names exactly one set
// of coordinates and a test can assert them before a single frame has run.
// ===========================================================================
loadRingFixture:
    lda #P5_N_RING
    sta logCount

    ldy #0
    lda (fx_src),y
    sta ringPhaseVel
    iny
    lda (fx_src),y
    sta ringPhaseVel + 1
    iny
    lda (fx_src),y
    sta ringShiftVel
    iny
    lda (fx_src),y
    sta ringShiftVel + 1

    lda #0
    sta ringPhase
    sta ringPhase + 1
    sta ringShift
    sta ringShift + 1
    sta ringOrbits
    sta ringOrbits + 1

    // Pointer and colour from the LOGICAL index, exactly as every other fixture
    // loader does it, so "the sprite showing 7 is in sprite 3's colour" remains
    // the diagnostic. With exactly sixteen sprites and sixteen bitmaps there is
    // no wrap: all sixteen numerals and all sixteen colours are distinct, which
    // is what lets a human name the sprite that misbehaved.
    ldx #0
!loop:
    txa
    and #(SPRITE_COUNT - 1)
    clc
    adc #SPRITE_PTR_FIRST
    sta logPtr,x
    lda fxColour,x
    sta logCol,x
    inx
    cpx #P5_N_RING
    bcc !loop-

    lda #1
    sta ringActive
    sta fixtureMoves                    // the main loop rebuilds every frame

    jsr ringPlace                       // frame 0 positions, before any tick

    // The crossing census is zeroed AFTER the initial placement, not before.
    //
    // ringPlace compares each sprite's new X-MSB against logXHi to decide
    // whether it crossed 255. On the very first placement logXHi still holds
    // whatever the previous fixture left -- zero on a cold machine -- so the
    // five sprites that START on the far side of 255 would each be counted as
    // an upward crossing that never happened. Measured: engine 416 up against
    // the model's 411, in every mode, every time.
    //
    // Placement is not motion. The census counts crossings the ORBIT caused,
    // so it starts from the frame-0 positions rather than from an empty array.
    lda #0
    sta ringX255Up
    sta ringX255Up + 1
    sta ringX255Down
    sta ringX255Down + 1

    jmp sortReset                       // sortedIDs must be a permutation of
                                        // 0..logCount-1 for THIS fixture

// ===========================================================================
// ringTick — advance the orbit one frame, then place every sprite.
// Called from motionTick when ringActive. MAIN THREAD ONLY.
// ===========================================================================
ringTick:
    inc motionFrame
    bne !noCarry+
    inc motionFrame + 1
!noCarry:

    lda ringPhase                       // phase += phaseVel, 16-bit
    clc
    adc ringPhaseVel
    sta ringPhase
    lda ringPhase + 1
    adc ringPhaseVel + 1
    sta ringPhase + 1
    bcc !noOrbit+                       // the index wrapped: one whole orbit
    inc ringOrbits
    bne !noOrbit+
    inc ringOrbits + 1
!noOrbit:

    lda ringShift                       // sweep += shiftVel, 16-bit. Zero
    clc                                 // velocity simply never moves it.
    adc ringShiftVel
    sta ringShift
    lda ringShift + 1
    adc ringShiftVel + 1
    sta ringShift + 1
    // fall through

// ===========================================================================
// ringPlace — write logical X/Y for every sprite from the current phase.
// Split out so loadRingFixture can establish frame 0 without advancing time.
// ===========================================================================
ringPlace:
    ldx ringShift + 1                   // this frame's vertical sweep offset
    lda ringShiftTab,x
    sta rt_dy

    ldx #0                              // logical sprite index
rp_loop:
    cpx logCount
    bcs rp_done

    // phase index = ring index + 16 * logical index, modulo the table.
    // The multiply is four shifts because P5_PHASE_STEP is 16; the .if below
    // refuses to assemble if that ever stops being true.
    txa
    asl
    asl
    asl
    asl
    clc
    adc ringPhase + 1
    sta rt_idx
    tay

    // ---- X, and the $D010 crossing census ---------------------------------
    lda ringXHi,y
    cmp logXHi,x                        // same side of 255 as last frame?
    beq !sameSide+
    cmp #0
    beq !wentDown+
    inc ringX255Up                      // 0 -> 1
    bne !sameSide+
    inc ringX255Up + 1
    jmp !sameSide+
!wentDown:
    inc ringX255Down                    // 1 -> 0
    bne !sameSide+
    inc ringX255Down + 1
!sameSide:
    lda ringXHi,y
    sta logXHi,x
    lda ringXLo,y
    sta logX,x

    // ---- Y, plus the sweep and the P2 vertical offset ----------------------
    // ringY is absolute and the sweep is signed two's complement, so this is a
    // plain 8-bit add. It cannot wrap: the generator refuses to assemble a
    // table whose extremes leave the visible band.
    lda ringY,y
    clc
    adc rt_dy
    clc
    adc fixtureYOffset
    sta logY,x

    inx
    jmp rp_loop
rp_done:
    rts

.if (P5_PHASE_STEP != 16) {
    .error "ringPlace multiplies the logical index by P5_PHASE_STEP with four ASLs"
}
