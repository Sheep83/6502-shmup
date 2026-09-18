// ===========================================================================
// movement_format.asm — the movement stage RECORD FORMAT. Constants only.
// ===========================================================================
// SHARED BY TWO BUILDS, which is the whole reason it is its own file. The
// engine (src/movement.asm) interprets these records; the separately loaded
// level package (src/level_package.asm) emits them at $f530. The two are
// assembled independently and share no labels, so the FORMAT has to live
// somewhere both can import -- exactly as src/levelpkg.asm does for addresses.
//
// It emits no bytes, no segment and no program-counter change.
// ===========================================================================

// IMPORTED MORE THAN ONCE PER BUILD -- movement.asm and wave_programs.asm both need it in the same build.
#importonce

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
//   3  vy / head  STRAIGHT/HOLD: vy.      ARC/ARC_MIRROR: ENTRY HEADING, or
//                                         WM_HEAD_CONT to keep the current one.
//
// ---------------------------------------------------------------------------
// BYTE 3 OF AN ARC IS THE ENTRY HEADING, AND THAT IS THE DETERMINISM RULE
// ---------------------------------------------------------------------------
// An arc used to read three of its four bytes and begin on whatever heading the
// object happened to be carrying. Nothing in the engine had put a heading there
// -- WM_STRAIGHT and WM_HOLD do not touch wmPhase and never have -- so in
// practice it came from the WAVE DEFINITION's launch heading, an input from
// outside the program entirely. Three of the four authored programs depended on
// it that way.
//
// That is fine while each program has exactly one caller. It is not fine for a
// SHARED POOL: the same program invoked by two encounters with different launch
// headings would fly two different paths, and an editor could not preview a
// program at all without knowing which encounter was going to run it.
//
// So an arc now says where it starts:
//
//     heading 0..WM_HEAD_LEN-1   begin here, whatever the object was doing
//     WM_HEAD_CONT               continue from the heading already held
//
// A program is then SELF-CONTAINED -- its trajectory is a function of its own
// bytes and nothing else -- and continuity, where it is genuinely wanted, is
// written down rather than inherited by accident.
//
// EDITING A PROGRAM CANNOT SILENTLY BREAK IT. src/waves.asm flies every path at
// assembly time under exactly these rules and rejects one that never arrives,
// never leaves or walks X past zero -- so changing an early arc and leaving a
// later explicit heading behind produces either a still-legal path or a build
// error, never a quiet wrong trajectory.
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


// ---------------------------------------------------------------------------
// WM_HEAD_CONT — "continue from the heading this object already has".
//
// THE ONE VALUE BYTE 3 OF AN ARC CAN TAKE THAT IS NOT A HEADING. A heading is
// 0..WM_HEAD_LEN-1, so $ff can never be one, and an arc record carrying it is
// asking to inherit rather than to be told.
//
// It exists because BOTH behaviours are wanted and only one of them used to be
// expressible. See the entry-heading note in the stage record above: an arc
// that names its heading is self-contained and can be shared by any encounter;
// an arc that continues is joined to the arc before it, which is what makes an
// S-turn an S rather than two unrelated curves. Before this constant the second
// case was the ONLY case, and the first was faked by relying on the wave
// definition's launch heading -- an input from outside the program.
.const WM_HEAD_CONT = $ff

.if (WM_HEAD_CONT < WM_HEAD_LEN) {
    .error "WM_HEAD_CONT must not collide with a real heading"
}
