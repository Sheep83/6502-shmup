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
// QUARTER-PIXEL VELOCITY, WITH A PER-OBJECT REMAINDER
// ---------------------------------------------------------------------------
// Whole pixels a frame cannot express a curve: the slowest non-zero speed
// would be fifty pixels a second, and a turn made of steps that size is a
// staircase. So velocities are in QUARTER pixels and each object carries its
// own remainder:
//
//     sum   = accumulator + velocity        (velocity in quarter pixels)
//     delta = sum >> 2                      (arithmetic: floor, for negatives)
//     acc   = sum & 3                       (0..3, the remainder carried on)
//
// Exact floor division, no drift, a handful of cycles, and a speed granularity
// of 12.5 pixels a second.
//
// THE SIGN HANDLING IS THE WHOLE TRICK. For sum = -5, an ARITHMETIC shift right
// by two gives -2 (floor(-1.25) = -2, not -1), and -5 AND 3 = 3, and
// -2*4 + 3 = -5: the remainder stays positive and the division floors, which is
// what a position accumulator needs. A logical shift, or "negate, shift,
// negate", would drift a pixel every four frames in one direction only and
// every curve would visibly sag.
//
// ---------------------------------------------------------------------------
// COMPOSABLE STAGES OVER A HEADING TABLE
// ---------------------------------------------------------------------------
// An object carries WHICH DIRECTION IT IS FACING (wmPhase, an index into a
// table of WM_HEAD_LEN headings around the whole circle at constant speed),
// not how far through a particular turn it is. An arc stage therefore means
// "rotate the heading N steps", clockwise (WM_ARC) or anticlockwise
// (WM_ARC_MIRROR), and a turn leaves the object on its FINAL heading -- which
// is what lets stages compose instead of each one snapping back to a fixed
// start direction:
//
//     quarter turn   ARC 16
//     half turn      ARC 32
//     loop           ARC 64 (and 76 is a loop that leaves on a new heading)
//     S-turn         ARC n -> ARC_MIRROR m
//     hook and glide ARC n -> STRAIGHT -> ARC m
//
// WHAT THIS IS NOT. Not a bytecode VM, not a spline evaluator, not a script
// interpreter, and not target-seeking. A stage record is four bytes read with
// indexed loads, the interpreter is one compare ladder, and the vocabulary is
// five primitives. Everything interesting comes from the ORDER the content
// puts them in, which costs no 6502 cycles at all.
// ===========================================================================

// --- the primitives ---------------------------------------------------------
.const WM_STRAIGHT   = 0        // constant velocity for wmTimer frames
.const WM_ARC        = 1        // rotate the heading CLOCKWISE, one step per
                                // stage-authored frame count
.const WM_ARC_MIRROR = 2        // ...ANTICLOCKWISE: the same turn, handed
.const WM_EXIT       = 3        // constant velocity, until the despawn rule
.const WM_HOLD       = 4        // a bounded linger: an authored (usually slow
                                // or zero) velocity for wmTimer frames. Same
                                // mechanics as WM_STRAIGHT, kept distinct so
                                // that "this enemy is deliberately loitering"
                                // is visible in the state rather than inferred
                                // from a small number.
.const WM_MODES      = 5

// --- the stage record -------------------------------------------------------
// Four bytes, and the third and fourth mean different things to different
// primitives because an arc has no use for a velocity and a straight leg has
// no use for a step length. The FORMAT lives here, beside the interpreter that
// executes it; the BYTES live in src/waves.asm, beside the rest of the
// authored content.
//
//   0  kind       WM_*
//   1  arg        STRAIGHT/HOLD: frames.  ARC/ARC_MIRROR: heading steps.
//   2  vx / step  STRAIGHT/HOLD: vx.      ARC/ARC_MIRROR: frames per step.
//   3  vy         STRAIGHT/HOLD: vy.      ARC/ARC_MIRROR: unused.
//
// WM_EXIT reads none of them: it is terminal and it KEEPS whatever velocity
// the stage before it left behind, which is what makes ARC -> EXIT continuous.
//
// FRAMES PER STEP IS THE TURN RADIUS, and it is per stage rather than global
// for one byte that was going spare. The heading sweeps a full circle in
// WM_HEAD_LEN steps whatever happens, so a step held for f frames travels
// WM_ARC_SPEED*f/4 pixels and the circle it is walking round has radius
// WM_ARC_SPEED*f*WM_HEAD_LEN/(8*PI) -- 61 pixels at f=4, 31 at f=2. A wide
// sweeping hook and a tight snap loop are therefore the same primitive with a
// different byte, not two primitives.
.const WM_STAGE_SIZE = 4

// --- the heading table ------------------------------------------------------
// WM_HEAD_LEN directions at a constant speed of WM_ARC_SPEED quarter pixels a
// frame (1.5 px/frame, 75 px/second), measured CLOCKWISE FROM EAST in screen
// coordinates -- +x right, +y DOWN, so clockwise is right, down, left, up.
//
//     heading  0   east   (+6,  0)
//     heading 16   south  ( 0, +6)
//     heading 32   west   (-6,  0)
//     heading 48   north  ( 0, -6)
//
// Sixty-four so that the wrap is AND #63 rather than a compare and a fixup,
// and so that a quarter turn is sixteen steps of WM_ARC_STEP frames: 64 frames.
//
// GENERATED, NOT HAND-WRITTEN: nobody verifies the sixty-fourth cosine by eye,
// so a typo in a literal table would be invisible. The assembly-time proofs
// below therefore check not the arithmetic but the PROPERTIES the movement code
// depends on -- the quadrant anchors, the smoothness, and that no heading
// stands still.
.const WM_HEAD_LEN  = 64
.const WM_HEAD_MASK = WM_HEAD_LEN - 1
.const WM_ARC_STEP  = 4         // default frames per heading step
.const WM_ARC_SPEED = 6         // quarter pixels per frame
.const WM_QUARTER   = WM_HEAD_LEN / 4

.var headVX = List()
.var headVY = List()
.for (var i = 0; i < WM_HEAD_LEN; i++) {
    .var a = 2 * PI * i / WM_HEAD_LEN
    .eval headVX.add(round(WM_ARC_SPEED * cos(a)))
    .eval headVY.add(round(WM_ARC_SPEED * sin(a)))
}

// THE QUADRANT ANCHORS. Every authored heading in src/waves.asm is reasoned
// about in these terms, and the arithmetic that produced the table is only
// worth having if they came out exactly.
.if (headVX.get(0) != WM_ARC_SPEED || headVY.get(0) != 0) {
    .error "heading 0 is not due east at full speed"
}
.if (headVX.get(WM_QUARTER) != 0 || headVY.get(WM_QUARTER) != WM_ARC_SPEED) {
    .error "heading WM_HEAD_LEN/4 is not due south at full speed"
}
.if (headVX.get(2 * WM_QUARTER) != -WM_ARC_SPEED || headVY.get(2 * WM_QUARTER) != 0) {
    .error "heading WM_HEAD_LEN/2 is not due west at full speed"
}
.if (headVX.get(3 * WM_QUARTER) != 0 || headVY.get(3 * WM_QUARTER) != -WM_ARC_SPEED) {
    .error "heading 3*WM_HEAD_LEN/4 is not due north at full speed"
}

// SMOOTHNESS, which is the property the whole quarter-pixel exercise exists to
// buy. One heading step may change a velocity component by at most one quarter
// pixel a frame (12.5 px/s), which is well under what reads as a direction
// change; two would be a visible kink in every turn in the game. Checked round
// the WRAP as well, because a loop of more than WM_HEAD_LEN steps crosses it.
.for (var i = 0; i < WM_HEAD_LEN; i++) {
    .var j = mod(i + 1, WM_HEAD_LEN)
    .if (abs(headVX.get(j) - headVX.get(i)) > 1) {
        .error "a heading step moves vx by more than one quarter pixel"
    }
    .if (abs(headVY.get(j) - headVY.get(i)) > 1) {
        .error "a heading step moves vy by more than one quarter pixel"
    }
    // A heading with no velocity at all would be an enemy that stops dead
    // mid-turn and, if it were the last one, never despawned.
    .if (headVX.get(i) == 0 && headVY.get(i) == 0) {
        .error "a heading has zero velocity"
    }
}

// THE WRAP GUARD'S SPEED HALF. src/enemy.asm frees an enemy whose nine-bit X
// has fallen below ENEMY_CLEAR_X_LEFT, which is what keeps the coordinate
// positive and stops a borrow into logXHi putting the sprite back on screen
// 256 pixels to the right. That check runs once a frame, so it only works if
// one frame's movement cannot carry an enemy clean over the window. It is
// asserted HERE rather than there because this is the file that decides how
// fast anything moves.
.if (ENEMY_CLEAR_X_LEFT * 4 < WM_ARC_SPEED) {
    .error "an enemy can cross the left clearance window in one frame and wrap"
}

// ===========================================================================
// State. MAIN THREAD ONLY. One entry per pool slot.
// ===========================================================================
// Per-OBJECT arrays that live apart from the pool's own only because
// src/objects.asm's block at $c580 runs up against the collision state at
// $c5f3. Indexed by the same slot number and cleared by the same
// objectZeroSlot, so they are subject to the same invariant: A REUSED SLOT
// INHERITS NOTHING.
* = $7700 "movement state"

wmMode:    .fill MAX_OBJECTS, 0     // WM_*: which primitive is running
wmStage:   .fill MAX_OBJECTS, 0     // BYTE offset of the current stage record
                                    // in waveStageTable: a cursor into the
                                    // authored path this object is walking
wmPhase:   .fill MAX_OBJECTS, 0     // HEADING, 0..WM_HEAD_LEN-1: which way the
                                    // object faces, NOT progress through a
                                    // turn. That is what lets turns compose.
wmTimer:   .fill MAX_OBJECTS, 0     // frames left in this stage (straight,
                                    // hold) or in this heading step (arcs)
wmSteps:   .fill MAX_OBJECTS, 0     // heading steps left in this arc stage
wmVX:      .fill MAX_OBJECTS, 0     // signed, QUARTER pixels per frame
wmVY:      .fill MAX_OBJECTS, 0     // signed, QUARTER pixels per frame
wmAccX:    .fill MAX_OBJECTS, 0     // sub-pixel remainder, 0..3
wmAccY:    .fill MAX_OBJECTS, 0     // sub-pixel remainder, 0..3
wmBaseCol: .fill MAX_OBJECTS, 0     // the colour a hit flash returns to

movementStateEnd:
.if (movementStateEnd > $77c0) {
    .error "the movement state has grown into the wave state at $77c0"
}

// ===========================================================================
* = $7800 "movement"

// ---------------------------------------------------------------------------
// wmClearSlot — every movement field of slot X. Entry/exit: X = slot.
//
// Called by objectZeroSlot, so a slot handed out by objectAlloc carries no
// trace of its previous occupant's trajectory. Exhaustive on purpose: clearing
// only the fields that seem to matter is how such a list goes stale.
// ---------------------------------------------------------------------------
wmClearSlot:
    lda #0
    sta wmMode,x
    sta wmStage,x
    sta wmPhase,x
    sta wmTimer,x
    sta wmSteps,x
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
    cmp #WM_ARC
    beq wmArcStep
    cmp #WM_ARC_MIRROR
    beq wmArcStep
    cmp #WM_EXIT
    beq wmNoStep                        // terminal: constant velocity until
                                        // the despawn rule
    jmp wmTimedStep                     // WM_STRAIGHT or WM_HOLD
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
// wmTimedStep — count a straight leg or a linger out. X = slot, preserved.
//
// WM_STRAIGHT and WM_HOLD are the same mechanism and deliberately share it:
// the only difference between flying somewhere and loitering is the velocity
// the content chose, and a second copy of "decrement a timer" would be two
// places to fix the day the timer grows a second byte.
//
// A zero timer means "run for ever". Authored stages never use it -- an
// unbounded stage that is not WM_EXIT could never reach the despawn rule, and
// src/waves.asm rejects one at assembly time -- but it is what a freshly
// zeroed slot holds, so a slot that is somehow ticked before its wave has
// configured it sits still rather than running off the end of the stage table.
// ---------------------------------------------------------------------------
wmTimedStep:
    lda wmTimer,x
    beq wmNoStep                        // unbounded
    dec wmTimer,x
    bne wmNoStep
    jmp wmEnterNext

// ---------------------------------------------------------------------------
// wmArcStep — one frame of a turn. X = slot, preserved.
//
// Hold the current heading for the stage's own frame count, then rotate one
// step: clockwise for WM_ARC, anticlockwise for WM_ARC_MIRROR. The stage ends
// when it has spent all of its steps, and the object LEAVES ON ITS FINAL
// HEADING -- so an EXIT after a turn carries the direction the turn finished
// in, and a second arc after it continues from there rather than restarting.
//
// AND #WM_HEAD_MASK IS THE WHOLE OF "LOOPS WORK". A turn of more than a full
// circle simply wraps the heading and keeps going; there is no loop primitive,
// no orbit centre and no angle accumulator, because a heading that wraps is
// already all of those things.
// ---------------------------------------------------------------------------
wmArcStep:
    dec wmTimer,x
    bne !done+                          // still holding this heading

    ldy wmMode,x
    cpy #WM_ARC_MIRROR
    beq !ccw+
    lda wmPhase,x
    clc
    adc #1
    jmp !store+
!ccw:
    lda wmPhase,x
    sec
    sbc #1
!store:
    and #WM_HEAD_MASK
    sta wmPhase,x
    jsr wmLoadHeading

    ldy wmStage,x                       // this stage's own step length: the
    lda waveStageTable + 2,y            // turn radius, per stage
    sta wmTimer,x

    dec wmSteps,x
    beq !advance+
!done:
    rts
!advance:
    jmp wmEnterNext

// ---------------------------------------------------------------------------
// wmLoadHeading — velocity <- the heading table at this object's heading.
// X = slot, preserved.
//
// No mirroring or negation: the table already contains every direction, so
// WM_ARC_MIRROR differs from WM_ARC in which way it STEPS and nothing else.
// ---------------------------------------------------------------------------
wmLoadHeading:
    ldy wmPhase,x
    lda wmHeadVX,y
    sta wmVX,x
    lda wmHeadVY,y
    sta wmVY,x
    rts

// ---------------------------------------------------------------------------
// wmEnterNext — this stage is finished; take up the next record. X = slot.
// ---------------------------------------------------------------------------
wmEnterNext:
    lda wmStage,x
    clc
    adc #WM_STAGE_SIZE
    sta wmStage,x
    // falls through

// ---------------------------------------------------------------------------
// wmEnterStage — begin the stage record wmStage,x already names. X = slot.
//
// Also the SPAWN path: src/waves.asm points a new enemy at its pattern's first
// record, sets its launch heading, and calls straight in here. One routine
// starts a path and continues it, so a pattern's first stage cannot behave
// differently from the same stage in the middle of a pattern.
//
// THE VELOCITY IS NOT RESET FOR WM_EXIT, and that is what makes ARC -> EXIT
// continuous: there is no frame on which an object's speed jumps because a
// mode byte changed. WM_STRAIGHT and WM_HOLD do set one, because a leg that
// could not choose its own speed could not be a linger.
// ---------------------------------------------------------------------------
wmEnterStage:
    ldy wmStage,x
    lda waveStageTable + 0,y
    sta wmMode,x

    cmp #WM_EXIT
    beq !exit+
    cmp #WM_ARC
    beq !arc+
    cmp #WM_ARC_MIRROR
    beq !arc+

    // WM_STRAIGHT / WM_HOLD: an authored velocity for an authored time.
    lda waveStageTable + 1,y
    sta wmTimer,x
    lda waveStageTable + 2,y
    sta wmVX,x
    lda waveStageTable + 3,y
    sta wmVY,x
    rts

!arc:
    // Take the heading's velocity IMMEDIATELY rather than after one step, so
    // that a turn entered from a straight leg starts turning on the next frame
    // instead of flying on for a step length first.
    lda waveStageTable + 1,y
    sta wmSteps,x
    lda waveStageTable + 2,y
    sta wmTimer,x
    jmp wmLoadHeading

!exit:
    lda #0
    sta wmTimer,x                       // unbounded: the despawn rule ends it
    rts

// ---------------------------------------------------------------------------
// The heading table, as bytes. Masked to eight bits because half of it is
// negative and .byte wants what the 6502 will read.
// ---------------------------------------------------------------------------
wmHeadVX:
.for (var i = 0; i < WM_HEAD_LEN; i++) { .byte headVX.get(i) & $ff }
wmHeadVY:
.for (var i = 0; i < WM_HEAD_LEN; i++) { .byte headVY.get(i) & $ff }
wmHeadEnd:
.if (wmHeadEnd - wmHeadVX != 2 * WM_HEAD_LEN) {
    .error "the heading table is not two bytes per heading"
}

.if (* > $7c00) { .error "the movement code has outgrown its $7800 segment" }
