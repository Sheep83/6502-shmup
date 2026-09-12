// ===========================================================================
// motion.asm — P3 scripted motion
// ===========================================================================
// MAIN THREAD ONLY. The raster executor never reads one byte of this file.
//
// P3's whole claim is that moving sprites change nothing about the renderer:
// motion produces logical X/Y, the ALREADY QUALIFIED builder turns those into a
// complete NEXT schedule under the same acceptance rules, publication is still
// one byte, and the executor still consumes an immutable CURRENT. So the order
// is fixed and is the thing to protect:
//
//     motionTick      moves logical X/Y            <- here
//     buildSchedule   builds NEXT from those values
//     publishSchedule one byte
//     frame IRQ       adopts CURRENT
//     executor        consumes CURRENT only
//
// Nothing here runs inside an interrupt, and nothing here is consulted after
// publication. If motion stopped dead, the frame would still render.
//
// ONE PRIMITIVE, NOT A MOVEMENT ENGINE
// Every scripted trajectory in P3 is the same thing: a bounded ping-pong.
//
//     pos += vel
//     if pos >= max:  pos = max;  vel = -vel
//     if pos <= min:  pos = min;  vel = -vel
//
// vel = 0 is a static sprite, so one code path covers both and there is no
// per-sprite "kind" dispatch to get wrong. The sequence is an exact integer
// triangle wave, which means the test harness can state the expected position
// for frame N in closed form and compare it -- which is the point. A general
// movement system would be easier to write and impossible to audit.
//
// WHY THE ENDPOINT RULE IS >= AND <=, NOT > AND <
// With a strict comparison the bound is hit, not reversed, and then overshot
// and clamped on the following frame, so each endpoint appears TWICE:
//     32 33 34 34 33 32 31 31 ...
// Reversing on >= gives a clean triangle with each endpoint once:
//     32 33 34 33 32 31 32 ...
// Both are deterministic; the second is the one a human can check by eye on a
// diagnostic display, and the one the model states most simply.
//
// BOUNDS ARE A PRECONDITION, CHECKED AT ASSEMBLY TIME
// The arithmetic here is plain 8-bit (Y) and 16-bit (X) with no overflow
// handling, so a trajectory whose bound sits within one velocity step of 0 or
// of the type's maximum would wrap and clamp to the WRONG end. Rather than
// carry an unreachable guard in the engine -- the kind of
// unreachable-in-theory path this repository's own inventory blames for hiding
// real failures -- the p3s macro in fixtures.asm REFUSES TO ASSEMBLE such a
// fixture. The constraint is stated once, enforced at build time, and costs
// nothing at run time.
//
// Y ORDER IS A PRECONDITION, NOT A GUARANTEE
// The builder still requires logical sprites pre-sorted by ascending Y (P0's
// deliberate simplification). Nothing here enforces that. P3 fixtures move Y
// only in ways that cannot reorder -- rigid group translation, or bands that
// cannot overlap -- and tests/p3_model.py asserts the order held on every
// frame it checks. Trajectories that would cross in Y are P4's problem and are
// deliberately not "fixed" here.
// ===========================================================================

// ===========================================================================
// Logical sprite state — the builder's input.
// ===========================================================================
// Outside VIC bank 0, with the schedule buffers, for the same reason: it can
// never be mistaken for graphics data. It moved here from the fixtures segment
// in P3 because MAX_LOGICAL grew to 32 and logXHi was added, and the $1800
// segment had ~98 bytes of headroom left.
* = $c300 "logical sprite state"

logCount:       .byte 0
logY:           .fill MAX_LOGICAL, 0
logX:           .fill MAX_LOGICAL, 0    // X low byte
logXHi:         .fill MAX_LOGICAL, 0    // X bit 8, 0 or 1. P3: the $D010 source.
logPtr:         .fill MAX_LOGICAL, 0
logCol:         .fill MAX_LOGICAL, 0

// P2 vertical sweep. Added to every Y as a fixture is loaded, so one geometry
// can be walked down the screen a raster at a time. For a P3 motion fixture it
// is added to the Y BOUNDS as well, so the whole trajectory translates and the
// motion stays inside the shifted band.
fixtureYOffset: .byte 0

// 1 = this fixture moves, so the main loop must re-run motion and rebuild the
// schedule every frame. 0 = static, and the main loop leaves the renderer
// completely alone between fixture changes, exactly as in P0/P1/P2. This flag
// is why P3 adds no per-frame cost to the static regression fixtures.
fixtureMoves:   .byte 0

// ===========================================================================
// Motion state — one bounded ping-pong per logical sprite, per axis.
// ===========================================================================
* = $c400 "motion state"

mvXVel:    .fill MAX_LOGICAL, 0         // signed, added to X each frame
mvXMinLo:  .fill MAX_LOGICAL, 0
mvXMinHi:  .fill MAX_LOGICAL, 0
mvXMaxLo:  .fill MAX_LOGICAL, 0
mvXMaxHi:  .fill MAX_LOGICAL, 0
mvYVel:    .fill MAX_LOGICAL, 0         // signed, added to Y each frame
mvYMin:    .fill MAX_LOGICAL, 0
mvYMax:    .fill MAX_LOGICAL, 0

// Frames of MOTION, not frames of display: incremented once per motionTick, so
// a test can name the exact frame whose positions it is checking. 16 bits --
// an 8-bit counter wraps in 256 frames, about 5 seconds, which is shorter than
// any trajectory worth watching.
motionFrame: .byte 0, 0

// motionTick locals. Main thread only.
mt_v:     .byte 0                       // velocity in hand
mt_sx:    .byte 0                       // its sign extension, $00 or $ff
mt_nlo:   .byte 0                       // candidate position, low
mt_nhi:   .byte 0                       // candidate position, high

// ===========================================================================
* = $1c00 "motion"

// ===========================================================================
// clearMotion — every sprite static, every bound neutral.
// Called by the fixture loader before it installs a fixture, so a P3 fixture
// can never inherit a trajectory from the fixture selected before it. That is
// not theoretical: fixture selection is a SPACE press away on a live machine.
// ===========================================================================
clearMotion:
    // Motion frame restarts at zero with every fixture load, so "fixture 20,
    // motion frame 7" names exactly one set of positions and a test can assert
    // them. A counter that carried across a fixture change would make every
    // trajectory depend on how long the previous fixture had been watched.
    lda #0
    sta motionFrame
    sta motionFrame + 1

    ldx #MAX_LOGICAL - 1
!loop:
    sta mvXVel,x
    sta mvXMinLo,x
    sta mvXMinHi,x
    sta mvXMaxLo,x
    sta mvXMaxHi,x
    sta mvYVel,x
    sta mvYMin,x
    sta mvYMax,x
    dex
    bpl !loop-
    sta fixtureMoves
    // P5: a ring is a trajectory too, and inheriting one would be exactly the
    // failure clearMotion exists to prevent. A is still zero here.
    sta ringActive
    rts

// ===========================================================================
// motionTick — advance every logical sprite one frame. MAIN THREAD ONLY.
// ===========================================================================
motionTick:
    // P5. A ring fixture supplies logical X/Y from the orbit instead of from a
    // ping-pong; everything downstream is identical. One branch, taken once per
    // frame, so the P3/P4 fixtures pay a load and a branch and nothing else.
    lda ringActive
    beq !pingPong+
    jmp ringTick
!pingPong:

    inc motionFrame
    bne !noCarry+
    inc motionFrame + 1
!noCarry:

    ldx #0
mt_loop:
    cpx logCount
    bcc !more+
    jmp mt_done                         // out of line: the body is longer than
!more:                                  // a relative branch can reach

// ---- X: 16-bit ping-pong ---------------------------------------------------
    lda mvXVel,x
    beq mt_yAxis                        // static in X: leave X untouched
    sta mt_v
    bmi !negVel+
    lda #$00                            // sign extension of a positive velocity
    sta mt_sx
    jmp !signDone+
!negVel:
    lda #$ff
    sta mt_sx
!signDone:

    lda logX,x
    clc
    adc mt_v
    sta mt_nlo
    lda logXHi,x
    adc mt_sx
    sta mt_nhi

    // at or past max?
    lda mt_nhi
    cmp mvXMaxHi,x
    bcc mt_xCheckMin
    bne mt_xAtMax
    lda mt_nlo
    cmp mvXMaxLo,x
    bcc mt_xCheckMin
mt_xAtMax:
    lda mvXMaxLo,x
    sta mt_nlo
    lda mvXMaxHi,x
    sta mt_nhi
    jsr negXVel
    jmp mt_xStore

mt_xCheckMin:
    // at or below min?
    lda mt_nhi
    cmp mvXMinHi,x
    bcc mt_xAtMin
    bne mt_xStore
    lda mt_nlo
    cmp mvXMinLo,x
    beq mt_xAtMin
    bcs mt_xStore
mt_xAtMin:
    lda mvXMinLo,x
    sta mt_nlo
    lda mvXMinHi,x
    sta mt_nhi
    jsr negXVel

mt_xStore:
    lda mt_nlo
    sta logX,x
    lda mt_nhi
    sta logXHi,x

// ---- Y: 8-bit ping-pong ----------------------------------------------------
mt_yAxis:
    lda mvYVel,x
    beq mt_next                         // static in Y

    clc
    adc logY,x
    sta mt_nlo

    cmp mvYMax,x
    bcc mt_yCheckMin
    lda mvYMax,x                        // at or past max
    sta mt_nlo
    jsr negYVel
    jmp mt_yStore

mt_yCheckMin:
    lda mt_nlo
    cmp mvYMin,x
    beq mt_yAtMin
    bcs mt_yStore
mt_yAtMin:
    lda mvYMin,x
    sta mt_nlo
    jsr negYVel

mt_yStore:
    lda mt_nlo
    sta logY,x

mt_next:
    inx
    jmp mt_loop
mt_done:
    rts

// Two's complement negate, in place. X = logical sprite index.
negXVel:
    lda mvXVel,x
    eor #$ff
    clc
    adc #1
    sta mvXVel,x
    rts

negYVel:
    lda mvYVel,x
    eor #$ff
    clc
    adc #1
    sta mvYVel,x
    rts
