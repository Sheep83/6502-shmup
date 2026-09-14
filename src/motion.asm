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

// ===========================================================================
// THE MOTION SYSTEM AND ITS FIXTURE STATE ARE GONE.
//
// What used to follow here was motionTick -- a bounded ping-pong trajectory
// per logical sprite -- together with its $c400 state block and the
// fixtureMoves/fixtureYOffset flags the main loop consulted. All of it existed
// to animate the P0-P5 qualification fixtures, and the ladder those fixtures
// certified has been retired. Git has them.
//
// The arrays ABOVE stay, and are the reason this file still exists: logY, logX,
// logXHi, logPtr and logCol are the schedule builder's input -- production
// enemies, projectiles and the clipping layer all write them every frame. They
// were only ever housed here because the fixture loader was their first
// author.
// ===========================================================================
