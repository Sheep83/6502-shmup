// ===========================================================================
// movement.asm — reusable enemy movement primitives
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is written from this file, and the
// word "slot" never appears in it in the hardware sense. This file answers
// exactly one question -- WHERE IS THIS OBJECT THIS FRAME -- and writes the
// answer into the ordinary logical presentation (logX/logXHi/logY). Whether
// the object is drawn, and through which hardware sprite, remains entirely
// the renderer's business.
//
// ---------------------------------------------------------------------------
// WHY THIS EXISTS AT ALL
// ---------------------------------------------------------------------------
// src/enemy.asm's first production enemy moved by adding objVX/objVY to its
// position every frame, in WHOLE PIXELS -- the old game's own model, recovered
// faithfully and correct for a straight dive. It cannot express a curve.
//
// Whole pixels per frame is the problem, not the adding. The slowest non-zero
// speed is one pixel a frame -- fifty pixels a second -- so a curve built from
// whole-pixel velocities can only turn in steps of that size, and a turn made
// of fifty-pixel-per-second steps is a staircase, not an arc.
//
// So this file adds a QUARTER-PIXEL velocity with a per-object remainder:
//
//     sum   = accumulator + velocity        (velocity in quarter pixels)
//     delta = sum >> 2                      (arithmetic: floor, for negatives)
//     acc   = sum & 3                       (0..3, the remainder carried on)
//
// which is exact floor division with no drift, costs a handful of cycles, and
// gives a speed granularity of 12.5 pixels a second. THE SIGN HANDLING IS THE
// WHOLE TRICK and it is worth stating why it is correct: for sum = -5,
// an arithmetic shift right by two gives -2 (floor(-1.25) = -2, not -1), and
// -5 AND 3 = 3, and -2*4 + 3 = -5. The remainder stays positive and the
// division floors, which is exactly what a position accumulator needs. A
// logical shift or a "negate, shift, negate" would drift by a pixel every
// four frames in one direction only, and the curve would visibly sag.
//
// ---------------------------------------------------------------------------
// WHAT THIS IS NOT
// ---------------------------------------------------------------------------
// It is not a movement virtual machine, a spline evaluator or a script
// interpreter. It is three primitives and a table. Loops, orbits, S-curves,
// Beziers and target-seeking are deliberately absent: the point of this slice
// is to prove that per-object independent movement state works at all, and a
// vocabulary big enough to be interesting is a later decision made with the
// architecture already standing.
// ===========================================================================

// --- the primitives ---------------------------------------------------------
.const WM_STRAIGHT   = 0        // constant velocity for wmTimer frames
.const WM_ARC        = 1        // the table below, phase-stepped
.const WM_ARC_MIRROR = 2        // ...with vx negated: the same turn, handed
.const WM_EXIT       = 3        // constant velocity, until the despawn rule
.const WM_MODES      = 4

// --- the arc ----------------------------------------------------------------
// Sixteen phases turning a velocity vector through ninety degrees, from
// "straight along X" to "straight down Y", at a constant speed of six quarter
// pixels a frame (1.5 px/frame, 75 px/second).
//
// The values are round(6*cos(t)), round(6*sin(t)) for t stepping 0..90 degrees
// in sixteen steps, written out rather than generated so that the table a
// human reads is the table the 6502 executes -- and so the assembly-time
// proofs below are about the real bytes.
//
// WM_ARC_STEP frames are spent on each phase, so the whole turn takes
// WM_ARC_LEN * WM_ARC_STEP = 64 frames, about 1.3 seconds. Within one phase
// the velocity is constant, so the path is sixteen straight segments -- but
// each junction changes a component by at most one quarter pixel a frame
// (12.5 px/s), which is well under what reads as a direction change.
.const WM_ARC_LEN   = 16
.const WM_ARC_STEP  = 4         // frames per phase
.const WM_ARC_SPEED = 6         // quarter pixels per frame

.var arcVX = List().add(6,6,6,6,5,5,5,4,4,4,3,2,2,1,1,0)
.var arcVY = List().add(0,1,1,2,2,3,4,4,4,5,5,5,6,6,6,6)

.if (arcVX.size() != WM_ARC_LEN || arcVY.size() != WM_ARC_LEN) {
    .error "the arc table must have WM_ARC_LEN entries on both axes"
}

// TERMINATION PROOF, and it is the reason the single vertical despawn rule in
// src/enemy.asm is still sufficient now that enemies can curve.
//
// An arc always ends in WM_EXIT carrying the arc's LAST velocity. If that
// velocity had vy <= 0 the enemy would fly up or sideways for ever and hold
// its pool slot until the heat death of the C64. So: the last phase must
// descend, and -- because an enemy may be destroyed mid-arc and because a
// wave definition may enter the arc at any phase -- every phase must be
// non-ascending, which also guarantees the turn never doubles back.
.if (arcVY.get(WM_ARC_LEN - 1) <= 0) {
    .error "the arc's last phase does not descend, so WM_EXIT could never despawn"
}
.for (var i = 0; i < WM_ARC_LEN; i++) {
    .if (arcVY.get(i) < 0) { .error "an arc phase ascends; the turn doubles back" }
    .if (arcVX.get(i) < 0) { .error "arc vx must be authored positive; WM_ARC_MIRROR negates it" }
    .if (i > 0) {
        .if (arcVY.get(i) < arcVY.get(i - 1)) { .error "arc vy is not monotonic" }
        .if (arcVX.get(i) > arcVX.get(i - 1)) { .error "arc vx is not monotonic" }
    }
}

// ===========================================================================
// State. MAIN THREAD ONLY. One entry per pool slot.
// ===========================================================================
// These are per-OBJECT arrays that happen not to live beside the pool's own:
// src/objects.asm's block at $c580 runs up against the collision state at
// $c5f3 with nothing to spare. Indexed by the same slot number, cleared by the
// same objectZeroSlot, and therefore subject to the same invariant -- A
// REUSED SLOT INHERITS NOTHING. That clearing is in objects.asm rather than
// here precisely because it is the POOL's invariant, not this file's.
* = $7700 "movement state"

wmMode:    .fill MAX_OBJECTS, 0     // WM_*: which primitive is running
wmNext:    .fill MAX_OBJECTS, 0     // WM_*: what to enter when it finishes
wmPhase:   .fill MAX_OBJECTS, 0     // arc phase, 0..WM_ARC_LEN-1
wmTimer:   .fill MAX_OBJECTS, 0     // frames left in this phase/primitive
wmVX:      .fill MAX_OBJECTS, 0     // signed, QUARTER pixels per frame
wmVY:      .fill MAX_OBJECTS, 0     // signed, QUARTER pixels per frame
wmAccX:    .fill MAX_OBJECTS, 0     // sub-pixel remainder, 0..3
wmAccY:    .fill MAX_OBJECTS, 0     // sub-pixel remainder, 0..3
wmBaseCol: .fill MAX_OBJECTS, 0     // the colour a hit flash returns to

movementStateEnd:
.if (movementStateEnd > $77a0) {
    .error "the movement state has grown into the wave state at $77a0"
}

// ===========================================================================
* = $7800 "movement"

// ---------------------------------------------------------------------------
// wmClearSlot — every movement field of slot X. Entry/exit: X = slot.
//
// Called by objectZeroSlot, so a slot handed out by objectAlloc carries no
// trace of its previous occupant's trajectory. The old game hand-zeroed five
// named fields at each spawn site and this repository already rejected that
// pattern once: naming fields is how the list goes stale the first time
// someone adds a tenth.
// ---------------------------------------------------------------------------
wmClearSlot:
    lda #0
    sta wmMode,x
    sta wmNext,x
    sta wmPhase,x
    sta wmTimer,x
    sta wmVX,x
    sta wmVY,x
    sta wmAccX,x
    sta wmAccY,x
    sta wmBaseCol,x
    rts

// ---------------------------------------------------------------------------
// wmTick — one frame of one object's movement. Entry/exit: X = slot.
//
// Position first, then the primitive advances. That order is a decision: an
// object spawned this frame with a velocity already set moves by exactly that
// velocity on its first frame, and a phase change takes effect on the frame
// AFTER the one that requested it. The alternative -- advance, then move --
// would silently skip the first phase of every arc.
// ---------------------------------------------------------------------------
wmTick:
    jsr wmApplyVelocity

    lda wmMode,x
    cmp #WM_STRAIGHT
    beq wmStraightStep
    cmp #WM_EXIT
    beq wmNoStep                        // constant velocity until the bounds
    jmp wmArcStep                       // WM_ARC or WM_ARC_MIRROR
wmNoStep:
    rts

// ---------------------------------------------------------------------------
// wmApplyVelocity — quarter-pixel integration, both axes. X = slot, preserved.
// ---------------------------------------------------------------------------
wmApplyVelocity:
    // ---- X: nine bits, signed quarter-pixel velocity ----------------------
    lda wmAccX,x
    clc
    adc wmVX,x
    tay                                 // Y = sum, kept for the shift
    and #3
    sta wmAccX,x                        // remainder stays 0..3, always positive
    tya
    cmp #$80                            // C = the sign bit...
    ror                                 // ...so ROR is an ARITHMETIC shift
    cmp #$80
    ror                                 // A = floor(sum / 4), signed
    beq wmXDone                         // the common case: no whole pixel yet

    tay                                 // Y = delta, to recover its sign below
    clc
    adc logX,x
    sta logX,x
    tya
    bmi wmXLeft
    bcc wmXDone
    inc logXHi,x                        // crossed 255 -> 256 going right
    jmp wmXDone
wmXLeft:
    bcs wmXDone                         // a CLEAR carry is the borrow
    dec logXHi,x                        // crossed 256 -> 255 going left
wmXDone:

    // ---- Y: eight bits. The despawn rule in enemy.asm reads the result ----
    lda wmAccY,x
    clc
    adc wmVY,x
    tay
    and #3
    sta wmAccY,x
    tya
    cmp #$80
    ror
    cmp #$80
    ror
    clc
    adc logY,x
    sta logY,x
    rts

// ---------------------------------------------------------------------------
// wmStraightStep — count the primitive out. X = slot, preserved.
//
// A zero timer means "run for ever", which is what makes WM_STRAIGHT usable
// as a plain unbounded vector as well as a timed leg. WM_EXIT is the same
// behaviour reached by a different route and is kept separate only because a
// test and a human reading the state both want to know which one an object is
// in.
// ---------------------------------------------------------------------------
wmStraightStep:
    lda wmTimer,x
    beq wmNoStep                        // unbounded
    dec wmTimer,x
    bne wmNoStep
    jmp wmEnterNext

// ---------------------------------------------------------------------------
// wmArcStep — hold each phase for WM_ARC_STEP frames, then take the next.
// X = slot, preserved.
// ---------------------------------------------------------------------------
wmArcStep:
    dec wmTimer,x
    beq !advance+
    rts
!advance:
    lda #WM_ARC_STEP
    sta wmTimer,x

    inc wmPhase,x
    lda wmPhase,x
    cmp #WM_ARC_LEN
    bcc wmLoadArcPhase                  // still turning
                                        // the turn is over: hold the last
    lda #WM_ARC_LEN - 1                 // velocity and leave on it
    sta wmPhase,x
    jmp wmEnterNext

// ---------------------------------------------------------------------------
// wmLoadArcPhase — velocity <- the arc table at this object's phase.
// X = slot, preserved. Mirrored variants negate vx and nothing else.
// ---------------------------------------------------------------------------
wmLoadArcPhase:
    ldy wmPhase,x
    lda wmArcVY,y
    sta wmVY,x                          // vy is never mirrored: both handed
                                        // versions of the turn descend
    lda wmArcVX,y
    ldy wmMode,x
    cpy #WM_ARC_MIRROR
    bne !store+
    eor #$ff                            // two's complement negate
    clc
    adc #1
!store:
    sta wmVX,x
    rts

// ---------------------------------------------------------------------------
// wmEnterNext — this primitive is finished; take up wmNext. X = slot.
//
// The velocity is NOT reset. Whatever the finishing primitive was carrying is
// what the next one starts with, which is what makes STRAIGHT -> ARC and
// ARC -> EXIT continuous: there is no frame on which the object's speed jumps
// because a mode byte changed.
// ---------------------------------------------------------------------------
wmEnterNext:
    lda wmNext,x
    sta wmMode,x

    cmp #WM_STRAIGHT
    beq !plain+
    cmp #WM_EXIT
    beq !plain+

    // Entering an arc: start at phase 0 and take its velocity immediately, so
    // the object does not spend one phase-length on whatever it was doing.
    lda #0
    sta wmPhase,x
    lda #WM_ARC_STEP
    sta wmTimer,x
    jmp wmLoadArcPhase

!plain:
    lda #0
    sta wmTimer,x                       // unbounded from here
    sta wmNext,x                        // and nothing further queued
    rts

// ---------------------------------------------------------------------------
// The arc, as bytes.
// ---------------------------------------------------------------------------
wmArcVX:
.for (var i = 0; i < WM_ARC_LEN; i++) { .byte arcVX.get(i) }
wmArcVY:
.for (var i = 0; i < WM_ARC_LEN; i++) { .byte arcVY.get(i) }
wmArcEnd:
.if (wmArcEnd - wmArcVX != 2 * WM_ARC_LEN) {
    .error "the arc table is not two bytes per phase"
}

.if (* > $7a00) { .error "the movement code has outgrown its $7800 segment" }
