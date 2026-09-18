// ===========================================================================
// wave_programs.asm — THE MOVEMENT PROGRAM POOL, as authored data
// ===========================================================================
// CONSTANTS AND .var DATA ONLY. It emits no bytes and moves no program counter:
// it builds the `progs` list, and whoever imports it decides what to do with it.
//
// TWO BUILDS IMPORT IT, and that is why it is its own file:
//
//   src/waves.asm            computes each program's byte offset and FLIES every
//                            path at assembly time, proving termination, arrival
//                            and the entry headings below.
//   src/level_package.asm    emits the bytes into the separately loaded level
//                            package at $f530, which is where the running engine
//                            actually reads them from.
//
// THE ENGINE PRG NO LONGER CONTAINS THESE BYTES. The pool is level content and
// it now ships in the level file, beside the terrain and the metatile
// definitions. Nothing here knows the address; src/levelpkg.asm owns that.
//
// The level editor will eventually generate this file. Until it does, it is
// authored here -- which is exactly the arrangement the architecture review
// recommended for this stage: the runtime authoritative bytes move first, the
// exporter follows.
// ===========================================================================

// IMPORTED MORE THAN ONCE PER BUILD -- waves.asm imports it, and so may anything else that needs the pool.
#importonce
#import "movement_format.asm"

// ===========================================================================
// THE STAGE PROGRAMS — the flight paths, as sequences of movement stages
// ===========================================================================
// src/movement.asm owns the four-byte stage record format and the interpreter
// that runs it; these are the bytes. A pattern is a short list of stages ended
// by WM_EXIT, and the interesting shapes come from the ORDER rather than from
// any stage being clever:
//
//     kind             arg                 byte 2              byte 3
//     WM_STRAIGHT      frames              vx                  vy
//     WM_HOLD          frames              vx                  vy
//     WM_ARC           heading steps       frames per step     entry heading
//     WM_ARC_MIRROR    heading steps       frames per step     (or WM_HEAD_CONT)
//     WM_EXIT          --                  --                  --
//
// HEADINGS, because every one of these is authored in them: the heading table
// runs clockwise from east in WM_HEAD_LEN steps, so with +y DOWN --
//
//     0 east (+6,0)   8 down-right (+4,+4)   16 south (0,+6)
//    24 down-left (-4,+4)                    32 west (-6,0)
//
// and a quarter turn is WM_QUARTER = 16 steps. WM_ARC increases the heading
// (clockwise: east -> south -> west), WM_ARC_MIRROR decreases it.
//
// FRAMES PER STEP IS THE TURN RADIUS: 4 gives a wide 61-pixel sweep, 2 a tight
// 31-pixel snap. It is what lets one arc primitive be both a lazy hook and a
// dogfight loop.
.var progs = List()

// --- 0: ECHELON SWEEP -------------------------------------------------------
// Level flight east, a quarter turn, then away down. The straight leg's
// velocity is heading 0's own (+6,0), so the turn begins with no
// discontinuity at all.
.eval progs.add(List()
    .add(List().add(WM_STRAIGHT, 34, 6, 0))     // run in along the top
    .add(List().add(WM_ARC, WM_QUARTER, 4, 0))      // wide quarter turn to south,
                                                    // entered due east
    .add(List().add(WM_EXIT, 0, 0, 0)))

// --- 1: S-TURN --------------------------------------------------------------
// COMPOSED, NOT A CURVE ENGINE: one arc anticlockwise and one clockwise, and
// the S is the join between them. Launched steep (heading 12), the first arc
// unwinds it to level east and the second rolls it over past south to
// down-left, so the silhouette is a bulge right followed by a sweep away left.
//
// The heading never leaves 0..20, so vy is never negative and the path never
// climbs -- which is why this one needs no special pleading about the top of
// the aperture.
.eval progs.add(List()
    .add(List().add(WM_ARC_MIRROR, 12, 3, 12))     // steep -> level: bulge right
    .add(List().add(WM_ARC, 20, 3, WM_HEAD_CONT))  // level -> down-left: JOINED to
                                                    // the arc above -- this is the S
    .add(List().add(WM_EXIT, 0, 0, 0)))

// --- 2: LINGER AND BREAK ----------------------------------------------------
// Runs in on a diagonal, nearly stops for about a second in the middle of the
// screen, then accelerates away through a turn.
//
// THE HOLD IS (0,+1), NOT (0,0). A dead stop reads as a bug -- a sprite frozen
// mid-screen looks like something has hung -- while a quarter pixel a frame is
// visibly deliberate drift, and it keeps the object descending so that even a
// hold is making progress toward the despawn rule.
//
// The velocity jump from the hold's (0,+1) to the arc's full (+3,+5) is the
// POINT of the pattern rather than a discontinuity to apologise for: the enemy
// hangs, then breaks away.
.eval progs.add(List()
    .add(List().add(WM_STRAIGHT, 28, 3, 5))     // run in, down-right
    .add(List().add(WM_HOLD, 48, 0, 1))         // hang there, drifting
    .add(List().add(WM_ARC, 12, 4, 10))            // break away down-left, resuming
                                                    // the heading it flew in on
    .add(List().add(WM_EXIT, 0, 0, 0)))

// --- 3: LOOP ----------------------------------------------------------------
// A FULL CIRCLE AND A BIT: 76 heading steps is 64 for the loop plus 12 to
// leave on a steep descent instead of back on the entry heading. Two frames a
// step makes it tight (about a 31-pixel radius) and quick enough to read as a
// manoeuvre rather than a drift.
//
// THE DIVE IN FRONT OF IT IS THE INGRESS STAGE, and it is needed: a loop
// launched due east on the spawn line never descends into view, because level
// flight from off-screen stays off-screen. Rather than give the loop a special
// entrance it gets a stage, which is what a composable stage system is for.
// Forty frames of (+4,+4) carry it into view and the loop then starts from a
// diagonal heading, tilting the circle without changing what it is.
//
// The circle's centre sits ninety degrees clockwise of the entry heading, so a
// descending-diagonal entry hangs it down and left of the entry point and it
// clears the top of the aperture. The flight proof below checks that.
.eval progs.add(List()
    .add(List().add(WM_STRAIGHT, 40, 4, 4))        // dive in from above
    .add(List().add(WM_ARC, 76, 2, 8))             // loop, and keep turning
    .add(List().add(WM_EXIT, 0, 0, 0)))

.const PROG_SWEEP  = 0
.const PROG_S      = 1
.const PROG_LINGER = 2
.const PROG_LOOP   = 3

// Byte offsets of each program's first record, computed rather than authored:
// a hand-maintained offset is a number that is right until somebody inserts a
// stage.
.var progAt = List()
.var progBytes = 0
.for (var p = 0; p < progs.size(); p++) {
    .eval progAt.add(progBytes)
    .eval progBytes = progBytes + WM_STAGE_SIZE * progs.get(p).size()
}
// ONE BYTE OF CURSOR, AND THAT IS THE WHOLE CEILING. Every object carries its
// position in this pool in wmStage, a single byte, and the interpreter indexes
// the pool with it. Sixty-four stage records is the hard limit until that state
// widens -- src/levelpkg.asm restates it as LEVELPKG_MOVE_MAX, and the package
// build checks the bytes it actually emits against the same number.
.if (progBytes > 256) {
    .error "the stage table has outgrown the one-byte cursor in wmStage"
}
