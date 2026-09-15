// ===========================================================================
// waves.asm — the encounter director: authored triggers, waves, flight paths
// ===========================================================================
// MAIN THREAD ONLY. This file knows nothing about hardware sprites, raster
// batches, schedule publication, mux slot reuse or VIC register ownership,
// and if it ever needs to, the design has gone wrong. It creates ordinary
// logical objects through the ordinary pool and the renderer presents
// whatever is alive, exactly as it already does for turret projectiles.
//
//     worldProgress  -> the director's next authored trigger
//                    -> an active wave instance
//                    -> objectAlloc + the movement primitive it was authored
//                       with
//                    -> the ordinary object pool
//                    -> the existing renderer
//
// THIS FILE IS THE ONLY AUTHOR OF ENEMY SPAWNS. Nothing else may create a
// TYPE_ENEMY object: a second spawner running underneath the director would be
// a second author of the same screen and the two would fight over one pool.
//
// What it does NOT own: enemies are ordinary TYPE_ENEMY objects with their own
// art, HP, hit flash, death animation and despawn rules (src/enemy.asm), moved
// by the ordinary movement interpreter (src/movement.asm). The player's
// hitscan, the turrets and the hostile projectiles do not know this file
// exists.
//
// THE SHAPE: WAVE_SLOTS concurrent wave instances, a fixed authored trigger
// list, four wave definitions, and flight paths built by SEQUENCING movement
// stages rather than by adding a movement mode per shape. Loops, S-turns and
// lingers are ORDERINGS of the same five primitives, so the vocabulary stops
// growing as the content gets more interesting. There is deliberately no
// random selection, difficulty curve, population budget, formation AI, escort
// logic or procedural generation.
//
// ---------------------------------------------------------------------------
// TWO CONTENT RULES THAT ARE EASY TO BREAK FROM HERE
// ---------------------------------------------------------------------------
// MUX-FRIENDLY CHOREOGRAPHY IS THE CONTENT'S JOB, NOT THE RENDERER'S. Members
// must arrive on different raster lines and reach the bottom of the aperture at
// different times. A wave crossing the screen as a rank on ONE line asks six
// hardware sprites to cover four logical ones inside a single reuse window, and
// the honest fix is to author the wave differently rather than make the
// scheduler cleverer.
//
// EVERY MEMBER SPAWNS ENTIRELY OUTSIDE THE VISIBLE PLAYFIELD and flies in.
// Spawning inside the aperture makes enemies materialise in mid-air. Three
// patterns enter from above, where the renderer does not admit them until they
// cross raster 55; the sweep enters through the LEFT BORDER at X=0, where the
// VIC clips it column by column so the arrival is progressive.
//
// That interacts with how the Y fan is made. A positive yStep pushes the later
// members of a TOP-ENTERING wave down INTO view, so they appear on screen
// rather than arriving through the edge. The three top-entering patterns
// therefore use yStep 0 and let the DESCENT separate them -- every member is
// falling, so a 26-frame interval is itself 32 lines of separation by the time
// they are all in view. Only the sweep, which enters level through the side
// border, needs an authored yStep.
// ===========================================================================

// ===========================================================================
// ENEMY FIRING — the constants, and the one idea behind them
// ===========================================================================
// ONE OPPORTUNITY AT A TIME, FOR THE WHOLE SCREEN. The authored mask says
// WHICH enemies may shoot; this period says HOW OFTEN any of them gets to, and
// it is global rather than per enemy on purpose. Give every eligible enemy its
// own clock and the shot rate becomes a function of how many happen to be
// alive -- a four-strong formation fires twice as often as a two-strong one
// without anybody authoring that, and a wave flying as a rank puts four bolts
// on one raster. One opportunity per period, handed round the pool in turn,
// makes the rate a property of the LEVEL and the target a property of the
// FORMATION, and no two enemy bolts can ever leave on the same frame.
//
// A MISSED OPPORTUNITY IS LOST, NOT QUEUED. If the scan finds nobody eligible,
// or the shared projectile cap refuses the shot, nothing is remembered: the
// next opportunity is a full period later. A queue would fire a stale shot
// from an enemy that had since moved, died or left.
.const WAVE_FIRE_PERIOD  = 48       // frames between firing opportunities:
                                    // just under a second at 50 Hz

// WHERE AN ENEMY IS ALLOWED TO SHOOT FROM. The band is tighter than the
// renderer's admission band at both ends and each end is a fairness rule
// rather than a technical one:
//
//   MIN_Y  the sprite is 21 tall and the aperture starts at 55, so 70 is the
//          first line on which the WHOLE enemy is visible. A bolt from
//          something the player can only half see is a bolt from nowhere.
//   MAX_Y  below this the enemy is level with the player's own airspace and a
//          straight-down shot is unreactable -- and it is about to leave the
//          aperture anyway.
.const ENEMY_FIRE_MIN_Y  = 70
.const ENEMY_FIRE_MAX_Y  = 170      // exclusive
.const ENEMY_FIRE_LEAD   = 24       // the ship must be at least this far below
                                    // -- the same lead the turrets use, and for
                                    // the same reason: a bolt spawned on top of
                                    // the player cannot be dodged

// THE MUZZLE, in the enemy's own logical coordinates. An enemy sprite is 24
// wide and 21 tall and the bolt is 8 wide, so (24-8)/2 centres it and 18 puts
// it at the bottom edge -- the shot leaves the belly of the thing that fired
// it, which is what makes it read as having come FROM the enemy.
.const ENEMY_MUZZLE_X    = 8
.const ENEMY_MUZZLE_Y    = 18

// --- how many waves may run at once ----------------------------------------
// The arrays, the loops and the free-instance scan are all written against this
// constant, and no state is shared between instances, so raising it costs a few
// bytes of state and no code at all.
.const WAVE_SLOTS = 2

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
//     WM_ARC           heading steps       frames per step     --
//     WM_ARC_MIRROR    heading steps       frames per step     --
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
    .add(List().add(WM_ARC, WM_QUARTER, 4, 0))     // wide quarter turn to south
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
    .add(List().add(WM_ARC_MIRROR, 12, 3, 0))      // steep -> level: bulge right
    .add(List().add(WM_ARC, 20, 3, 0))             // level -> down-left: the turn back
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
    .add(List().add(WM_ARC, 12, 4, 0))             // break away down-left
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
    .add(List().add(WM_ARC, 76, 2, 0))             // loop, and keep turning
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
.if (progBytes > 256) {
    .error "the stage table has outgrown the one-byte cursor in wmStage"
}

// --- the authored wave definitions ------------------------------------------
// Ten bytes each, and the record is deliberately flat: the director reads it
// with one indexed load per field and never copies it anywhere.
//
//   0  count      how many enemies this wave sends
//   1  interval   frames between one member and the next
//   2  startXLo   nine-bit spawn X...
//   3  startXHi
//   4  startY     spawn line, inside the renderer's production band
//   5  xStep      signed, added to X per member
//   6  yStep      signed, added to Y per member
//   7  colour     every member of a wave shares one, so which wave an enemy
//                 belongs to is visible on screen
//   8  heading    launch heading, 0..WM_HEAD_LEN-1
//   9  program    byte offset of its first stage record
//
// YSTEP IS THE MUX-FRIENDLINESS FIELD. Fanning members along X alone lets a
// four-strong wave enter as a RANK on one raster line and stay that way for as
// long as its launch leg is level -- four logical sprites competing for one
// reuse window, the geometry the multiplexer finds hardest. Fanning Y turns the
// entry into an ECHELON: members arrive on distinct lines, spread further as
// their paths diverge, and reach the exit at different times.
//
// It is not always the right tool, though: see the top-entering waves below,
// which fan vertically through the INTERVAL instead, because a yStep would push
// their later members into view rather than letting them arrive through the
// edge.
.const WAVEDEF_SIZE = 10

// --- 0: "echelon sweep" -----------------------------------------------------
// Four across the top-left, each 20 lines below and 16 pixels right of the one
// before, all running east and turning down together. The stagger is what
// makes it an echelon rather than a rank: the members are 20 lines apart at
// entry -- a sprite is 21 tall -- and the quarter turn preserves that spacing
// all the way to the exit.
.var defSweep = List().add(
    4, 22,              // count, interval
    0, 0,               // startX = 0: the sprite covers columns 0..23 and the
                        // display window starts at 24, so it is ENTIRELY
                        // behind the left border and slides into view through
                        // it. This is the one edge the hardware clips for us.
    64,                 // startY: inside the aperture, because this pattern
                        // arrives from the SIDE rather than from above
    0, 20,              // xStep 0, yStep +20: every member enters at the same
                        // point on the border and the INTERVAL spaces them
                        // along X as they fly east -- 33 pixels per member --
                        // while yStep stacks them into an echelon. Fanning X
                        // at spawn would have put the later members on screen
                        // before they had entered.
    10,                 // colour: light red
    0,                  // heading: due east, straight through the border
    PROG_SWEEP)

// --- 1: "S-turn" ------------------------------------------------------------
// Three entering steep from ABOVE the aperture and weaving right then away
// left. startY 30 puts the whole 21-line sprite above raster 55 with four
// lines to spare, and the launch heading descends at a pixel and a half a
// frame, so it is in view about seventeen frames later.
.var defSTurn = List().add(
    3, 26,
    90, 0,              // startX = 90
    30,                 // startY: hidden above the aperture
    28, 0,              // xStep +28, yStep 0: the Y separation comes from the
                        // interval instead. Every member descends, so 26
                        // frames of head start IS vertical spacing -- and a
                        // positive yStep would have pushed the later members
                        // down into view before they had entered.
    3,                  // colour: cyan
    12,                 // heading: steep down-right
    PROG_S)

// --- 2: "linger and break" --------------------------------------------------
// Three running in from above on a shallow diagonal and hanging in the middle
// third. The interval gives the members about 32 lines of separation by the
// time they park, which is more than a sprite is tall -- and parking is
// exactly when that matters.
.var defLinger = List().add(
    3, 26,
    120, 0,             // startX = 120
    30,                 // startY: hidden above the aperture
    36, 0,              // xStep +36, yStep 0: as above, the descent plus the
                        // interval is the vertical fan
    7,                  // colour: yellow
    10,                 // heading: down-right, shallow
    PROG_LINGER)

// --- 3: "loop" --------------------------------------------------------------
// Three loops, widely spaced in time (34 frames) as well as in space, because
// three simultaneous circles in one place would be a knot rather than a
// manoeuvre. The dive stage in PROG_LOOP is what brings them in from hiding.
.var defLoop = List().add(
    3, 34,
    70, 0,              // startX = 70
    30,                 // startY: hidden above the aperture
    50, 0,              // xStep +50: the circles are 62 pixels across, so they
                        // need most of that between them to read as three
                        // separate manoeuvres. yStep 0: the dive plus the
                        // interval separates them vertically.
    13,                 // colour: light green
    8,                  // heading: down-right, so the dive carries it into
                        // view and the circle hangs below and left of where
                        // the loop starts
    PROG_LOOP)

.var waveDefs = List().add(defSweep).add(defSTurn).add(defLinger).add(defLoop)
.const WAVE_DEFS     = 4
.const WAVE_DEF_SWEEP  = 0
.const WAVE_DEF_S      = 1
.const WAVE_DEF_LINGER = 2
.const WAVE_DEF_LOOP   = 3

.if (waveDefs.size() != WAVE_DEFS) { .error "wave definition count disagrees with the table" }

// ===========================================================================
// ASSEMBLY-TIME PROOFS over the authored content
// ===========================================================================
// The cheap structural ones first, then the one that matters: FLYING EVERY
// PATTERN, for every member, through the REAL lifecycle rules.
//
// TERMINATION CANNOT BE PROVED BY INSPECTION HERE. A composed path may start
// off-screen, climb, level off, loop, reverse and leave by any of three edges,
// so whether it ever leaves at all is a property of the whole SEQUENCE and not
// of any stage in it.
//
// So the assembler integrates each path in quarter pixels -- the same
// arithmetic the 6502 does -- applying src/enemy.asm's three despawn rules
// frame by frame, and checks what a human cannot check by reading:
//
//   * IT LEAVES. Some edge is reached inside the frame budget; otherwise the
//     enemy holds a pool slot for the rest of the session.
//   * IT ARRIVES. The sprite actually becomes visible inside the aperture, and
//     reasonably soon. Since every pattern is authored to START off-screen, a
//     path that never crosses in is invisible content and an easy mistake.
//   * IT NEVER WRAPS. X stays positive for the whole flight, so no borrow can
//     put logXHi at $ff and reappear the sprite 256 pixels to the right.
//   * IT DOES NOT MATERIALISE IN VIEW. Every member is entirely outside the
//     visible playfield at spawn -- above it, or behind a side border.
//
// WHAT IS DELIBERATELY NO LONGER CHECKED: that the path stays inside the
// aperture. Bounded off-screen travel is now the POINT rather than a fault, so
// the validator distinguishes it from a runaway by asking whether the flight
// ends at an edge and whether it was ever on screen, instead of by fencing the
// coordinates in.
.const SIM_FRAME_BUDGET = 900        // frames before a path is called stuck
.const SIM_ENTER_BUDGET = 240        // frames a pattern may spend off-screen
                                     // before it has to have shown itself

.for (var d = 0; d < WAVE_DEFS; d++) {
    .var def = waveDefs.get(d)
    .if (def.size() != WAVEDEF_SIZE) { .error "a wave definition is not WAVEDEF_SIZE bytes" }
    .if (def.get(0) < 1) { .error "a wave definition sends no enemies" }
    .if (def.get(1) < 1) { .error "a wave interval of zero would spawn the whole wave in one frame" }
    .if (def.get(8) < 0 || def.get(8) >= WM_HEAD_LEN) { .error "a wave launches on a heading that does not exist" }
    .if (def.get(9) >= progs.size()) { .error "a wave names a stage program that does not exist" }

    .var prog = progs.get(def.get(9))
    .if (prog.get(prog.size() - 1).get(0) != WM_EXIT) {
        .error "a stage program does not end in WM_EXIT and would run off the table"
    }
    .for (var s = 0; s < prog.size() - 1; s++) {
        .var rec = prog.get(s)
        .if (rec.get(0) == WM_EXIT) { .error "WM_EXIT is terminal and cannot be followed by another stage" }
        .if (rec.get(1) < 1) { .error "a stage of zero length would never advance" }
        .if (rec.get(0) == WM_ARC || rec.get(0) == WM_ARC_MIRROR) {
            .if (rec.get(2) < 1) { .error "an arc stage with no frames per step would turn infinitely fast" }
        } else {
            // The wrap guard in src/enemy.asm runs once a frame, so no
            // authored leg may out-run its clearance window either.
            .if (abs(rec.get(2)) > ENEMY_CLEAR_X_LEFT * 4) {
                .error "a straight or hold leg moves in X fast enough to step over the left clearance window and wrap"
            }
        }
    }

    // ---- fly every member -------------------------------------------------
    .for (var m = 0; m < def.get(0); m++) {
        .var x0 = def.get(2) + 256 * def.get(3) + def.get(5) * m
        .var y0 = def.get(4) + def.get(6) * m

        // SPAWNED OUT OF SIGHT. The sprite covers x0..x0+23 and y0..y0+20, and
        // the visible playfield is columns 24..343 of rasters 55..247, so
        // "entirely outside" is one of these three.
        .var hiddenAbove = (y0 + SPRITE_HEIGHT - 1) < APERTURE_TOP_RASTER
        .var hiddenLeft  = (x0 + 23) < 24
        .var hiddenRight = x0 > 343
        .if (!hiddenAbove && !hiddenLeft && !hiddenRight) {
            .error "a wave member spawns where part of it is already on screen; it would pop into existence inside the playfield"
        }
        .if (x0 < 0 || x0 > 511) { .error "a wave member spawns outside the nine-bit X world" }
        .if (y0 < 0 || y0 > 255) { .error "a wave member spawns outside the eight bits logY has" }

        // ---- the flight, in quarter pixels --------------------------------
        .var x = x0 * 4
        .var y = y0 * 4
        .var head = def.get(8)
        .var vx = 0
        .var vy = 0
        .var frames = 0
        .var freed = false
        .var wrapped = false
        .var seen = false
        .var seenAt = 0

        .for (var s = 0; s < prog.size() && !freed && frames <= SIM_FRAME_BUDGET; s++) {
            .var rec = prog.get(s)
            .var isArc = (rec.get(0) == WM_ARC || rec.get(0) == WM_ARC_MIRROR)
            // An EXIT keeps the velocity it inherited and runs until an edge;
            // everything else has an authored length.
            .var outer = rec.get(0) == WM_EXIT ? SIM_FRAME_BUDGET : (isArc ? rec.get(1) : 1)
            .if (!isArc && rec.get(0) != WM_EXIT) {
                .eval vx = rec.get(2)
                .eval vy = rec.get(3)
            }
            .for (var k = 0; k < outer && !freed && frames <= SIM_FRAME_BUDGET; k++) {
                .if (isArc) {
                    .eval head = mod(head + (rec.get(0) == WM_ARC ? 1 : WM_HEAD_LEN - 1), WM_HEAD_LEN)
                    .eval vx = headVX.get(head)
                    .eval vy = headVY.get(head)
                }
                .var inner = isArc ? rec.get(2) : (rec.get(0) == WM_EXIT ? 1 : rec.get(1))
                .for (var f = 0; f < inner && !freed; f++) {
                    .eval x = x + vx
                    .eval y = y + vy
                    .eval frames = frames + 1
                    .var px = floor(x / 4)
                    .var py = floor(y / 4)
                    // src/enemy.asm's three rules, direction and all: a
                    // sprite behind a side border counts as gone only if it
                    // is still traveling that way, which is what lets a
                    // pattern ENTER through one.
                    .if (px < 0) { .eval wrapped = true }
                    .if ((px < ENEMY_CLEAR_X_LEFT && vx < 0)
                         || (px >= ENEMY_CLEAR_X_RIGHT && vx > 0)
                         || py >= ENEMY_CLEAR_Y) {
                        .eval freed = true
                    }
                    // Visible = admitted by the renderer AND inside the
                    // display window horizontally.
                    .if (!freed && py >= MIN_SPRITE_Y && py <= MAX_SPRITE_Y
                         && (px + 23) >= 24 && px <= 343) {
                        .if (!seen) { .eval seenAt = frames }
                        .eval seen = true
                    }
                }
            }
        }

        .if (wrapped) {
            .error "a pattern walks X past zero, where a borrow into logXHi reappears the sprite on the far side"
        }
        .if (!freed) {
            .error "a pattern never reaches any despawn edge inside SIM_FRAME_BUDGET frames"
        }
        .if (!seen) {
            .error "a pattern is never visible inside the aperture: it is authored entirely off-screen"
        }
        .if (seenAt > SIM_ENTER_BUDGET) {
            .error "a pattern spends longer than SIM_ENTER_BUDGET frames off-screen before entering view"
        }
    }
}

// ---------------------------------------------------------------------------
// THE AUTHORED TRIGGER LIST, in worldProgress DELTAS.
//
// worldProgress is the scroller's own "coarse rows travelled since the stage
// start", it only ever increases, and it advances once every eight frames --
// so it is the natural clock for encounters tied to how far through the level
// the player actually is, rather than to how long the machine has been on.
//
// DELTAS RATHER THAN ABSOLUTE THRESHOLDS, and that is what makes the sequence
// repeat for free: when the cursor runs off the end it wraps to zero and
// keeps adding, so the whole pattern recurs every (sum of deltas) coarse rows
// without a second table, a base offset or a special case. The period here is
// 24+5+30+5 = 64 coarse rows, about ten seconds, which is short enough to
// qualify by eye without waiting around.
//
// THE DELTAS ARE WAVE FOOTPRINTS, NOT INSTANCE LIFETIMES, and that distinction
// is what gives the game its pacing. An INSTANCE is held only until its last
// member is sent -- 1 + (count-1)*interval frames, about eight coarse rows for
// every wave here -- but its ENEMIES stay alive for far longer. Spacing on
// instance lifetime would therefore run every formation into the next one
// continuously, with never a moment of one pattern alone on screen.
//
// So each delta is the wave's whole footprint: the span it spends spawning plus
// the lifetime of its last member to leave.
//
//     sweep   66 +  177 = 243 frames = 30 rows
//     s-turn  52 +  200 = 252 frames = 32 rows
//     linger  52 +  206 = 258 frames = 32 rows
//     loop    68 +  317 = 385 frames = 48 rows
//
// Each formation has cleared the aperture before the next arrives: pattern,
// empty sky, pattern.
//
// ONE DELIBERATE OVERLAP: the four-row delta between the sweep and the S-turn,
// which is shorter than the sweep's occupancy and therefore puts two INSTANCES
// in flight at once. They are the right pair for it -- the sweep enters through
// the LEFT BORDER at a fixed height and the S-turn comes down from ABOVE on the
// other side of the screen, so the two formations are separated in entry point,
// direction and Y for the whole time they share the aperture. That is an
// overlap the multiplexer is never asked to work for.
//
// The period is 48+4+38+36 = 126 coarse rows, about twenty seconds.
.var trigDelta = List().add(48, 4, 38, 36)
.var trigDef   = List().add(WAVE_DEF_SWEEP, WAVE_DEF_S, WAVE_DEF_LINGER, WAVE_DEF_LOOP)

// WHICH ENEMY THE WAVE IS MADE OF, and it is an AUTHORED COLUMN rather than
// arithmetic on the cursor. Every member of one wave is the same species; the
// next authored wave is the other one.
//
// A third parallel column rather than `cursor AND 1` because the alternation is
// CONTENT, not a rule. Written down, it can be read at a glance, it survives
// someone inserting a fifth trigger (which `AND 1` would silently invert for
// every wave after it), and the day a particular pattern should always be
// Droppers it is one byte here rather than a special case in the director.
.var trigSpecies = List().add(SPECIES_RING, SPECIES_DROPPER,
                              SPECIES_RING, SPECIES_DROPPER)

// WHICH MEMBERS OF THIS APPEARANCE MAY SHOOT — a bitmask over MEMBER INDEX,
// bit 0 the first member sent, and zero for a formation that does not shoot
// at all.
//
// THE MASK IS THE WHOLE OF THE AUTHORED FIRING CONTROL, and it is a mask over
// the progression the director ALREADY RUNS rather than a new clock. wvIndex
// counts members as they are sent; member n consults bit n; the answer is
// copied onto the enemy and never revisited. There is no per-wave firing
// timer, no per-enemy countdown and nothing for a wave to keep ticking after
// it has gone.
//
// WHY A MASK AND NOT A RATE. Firing density in this game must be a property of
// CONTENT, not of population -- an encoding that gave every member a rate
// would make a four-strong wave twice as dangerous as a two-strong one for
// free, and would put four bolts in the air on the same raster when a
// formation flies as a rank. A mask says WHICH SILHOUETTES ON SCREEN ARE THE
// DANGEROUS ONES, which is a thing the player can learn, and the global
// opportunity cadence below says how often any of them gets to prove it.
//
// LEVEL 1, AND THE PACING IS DELIBERATE:
//
//     sweep   %0101   two of four, alternating along the echelon
//     s-turn  %0010   the middle one only
//     linger  %0101   two of three -- the pattern that HANGS in the middle of
//                     the screen is the one that earns the most shots
//     loop    %0000   NONE. The showpiece manoeuvre is the breathing room, and
//                     a formation that cannot shoot is the case the whole
//                     representation has to support.
.var trigFire  = List().add(%00000101, %00000010, %00000101, %00000000)
.const WAVE_TRIGGERS = 4

.if (trigDelta.size() != WAVE_TRIGGERS || trigDef.size() != WAVE_TRIGGERS
     || trigSpecies.size() != WAVE_TRIGGERS || trigFire.size() != WAVE_TRIGGERS) {
    .error "the trigger list is not WAVE_TRIGGERS entries on every axis"
}
.for (var t = 0; t < WAVE_TRIGGERS; t++) {
    .if (trigDelta.get(t) < 1) {
        .error "a trigger delta of zero would fire every frame for ever"
    }
    .if (trigDef.get(t) >= WAVE_DEFS) { .error "a trigger names a wave definition that does not exist" }
    // Membership, not a range: a species value is its animation ROW OFFSET
    // rather than a 0..n-1 index, so "less than the count" would be wrong.
    .if (trigSpecies.get(t) != SPECIES_RING && trigSpecies.get(t) != SPECIES_DROPPER) {
        .error "a trigger names a species that does not exist"
    }
    // A FIRE BIT THAT NAMES A MEMBER THE WAVE NEVER SENDS is an authoring
    // mistake that is invisible in play -- the shot simply never happens and
    // the formation reads as quieter than it was meant to be. The definition
    // knows how many members it sends, so the assembler can say so.
    .if ((trigFire.get(t) >> waveDefs.get(trigDef.get(t)).get(0)) != 0) {
        .error "a trigger's fire mask names a member this wave never sends"
    }
}
// THE ALTERNATION ITSELF IS CHECKED, including across the wrap -- the list
// repeats for ever, so the last entry's neighbour is the first. This is the
// assertion that makes "every other wave is a Dropper" a property of the build
// rather than of someone having counted carefully.
.for (var t = 0; t < WAVE_TRIGGERS; t++) {
    .if (trigSpecies.get(t) == trigSpecies.get(mod(t + 1, WAVE_TRIGGERS))) {
        .error "two consecutive authored waves use the same enemy species"
    }
}

// ===========================================================================
// State. MAIN THREAD ONLY.
// ===========================================================================
// Sixty-four bytes above the movement state, which the guards below keep from
// growing into it.
* = $77c0 "wave state"

// --- the active wave instances ----------------------------------------------
// Structure of arrays, indexed by instance, exactly like the object pool: one
// indexed load per field and no record stride. Nothing here is shared between
// instances, which is what lets one wave stall on a full pool while the other
// keeps spawning.
wvActive:  .fill WAVE_SLOTS, 0      // 1 = running
wvDef:     .fill WAVE_SLOTS, 0      // which definition it is playing
wvLeft:    .fill WAVE_SLOTS, 0      // members still to send
wvTimer:   .fill WAVE_SLOTS, 0      // frames until the next member
wvIndex:   .fill WAVE_SLOTS, 0      // members sent so far: drives xStep
wvFire:    .fill WAVE_SLOTS, 0      // the authored fire mask over member
                                    // index, latched with the species below
                                    // and read once per member as it is sent
wvSpecies: .fill WAVE_SLOTS, 0      // which enemy this instance is made of,
                                    // copied from the authored trigger column
                                    // when the wave was armed. Held per
                                    // INSTANCE rather than read from the
                                    // trigger cursor at spawn time because the
                                    // cursor has already moved on: a wave
                                    // sends its members over many frames, and
                                    // the next trigger may fire before the
                                    // last of them is out.

// --- the director ------------------------------------------------------------
wvNextTrig:  .byte 0                // cursor into the trigger list
wvNextAtLo:  .byte 0                // worldProgress at which it fires
wvNextAtHi:  .byte 0

// --- diagnostics -------------------------------------------------------------
// Saturating. These exist so a test can assert about the director's behaviour
// without single-stepping it, and so a human can tell "the pool was busy"
// from "the director is broken".
wvStarted:   .byte 0                // waves begun
wvDropped:   .byte 0                // triggers that found no free instance
wvDeferred:  .byte 0                // spawns postponed because the pool was full
wvSpawned:   .byte 0                // enemies actually created

// --- enemy firing -----------------------------------------------------------
// THREE BYTES FOR THE WHOLE SUBSYSTEM. There is no per-enemy clock and no
// per-wave clock: one countdown says when the NEXT opportunity is, and one
// cursor says where the round-robin resumes.
wvFirePhase: .byte 0                // frames until the next firing opportunity
wvFireCursor: .byte 0               // pool slot the next scan starts at

wvShots:     .byte 0                // saturating: bolts moving enemies fired
wvShotBlocked: .byte 0              // opportunities that FOUND an eligible
                                    // enemy and were refused by the shared cap.
                                    // Separate from "found nobody", because the
                                    // two say completely different things about
                                    // the content

waveStateEnd:
.if (waveStateEnd > $7800) { .error "the wave state has grown into the movement code at $7800" }
.if (movementStateEnd > $77c0) {
    .error "the movement state has grown into this block"
}

// ===========================================================================
// Code and authored tables. MAIN THREAD ONLY, outside VIC bank 0. The next
// thing above this file is the schedule buffers at $c000.
* = $7c00 "waves"

// ---------------------------------------------------------------------------
// waveInit — no waves running, the first trigger one delta away.
// ---------------------------------------------------------------------------
waveInit:
    lda #0
    ldx #WAVE_SLOTS - 1
!slot:
    sta wvActive,x
    sta wvDef,x
    sta wvLeft,x
    sta wvTimer,x
    sta wvIndex,x
    sta wvFire,x
    dex
    bpl !slot-

    sta wvNextTrig
    sta wvStarted
    sta wvDropped
    sta wvDeferred
    sta wvSpawned
    sta wvShots
    sta wvShotBlocked
    sta wvFireCursor

    // The first opportunity is a full period away, so a restart cannot begin
    // with a shot already in the air.
    lda #WAVE_FIRE_PERIOD
    sta wvFirePhase
    lda #0

    // The first trigger is the first delta from a standing start.
    lda waveTrigDelta
    sta wvNextAtLo
    lda #0
    sta wvNextAtHi
    rts

// ---------------------------------------------------------------------------
// waveTick — one frame of the director. MAIN THREAD, once per frame.
//
// Two pieces of work, both bounded and both tiny: ONE sixteen-bit compare
// against the next authored trigger, and a walk of WAVE_SLOTS instances. The
// trigger list is never scanned -- the director holds a cursor and the
// worldProgress at which that cursor fires -- so the per-frame cost does not
// grow with the length of the authored stage.
// ---------------------------------------------------------------------------
waveTick:
    // ---- has the world reached the next authored trigger? -----------------
    lda worldProgressHi
    cmp wvNextAtHi
    bcc !noTrigger+
    bne !fire+
    lda worldProgressLo
    cmp wvNextAtLo
    bcc !noTrigger+
!fire:
    jsr waveStartNext
!noTrigger:

    // ---- and every running wave sends its next member when due ------------
    ldx #WAVE_SLOTS - 1
!instance:
    lda wvActive,x
    beq !next+
    jsr waveRunInstance                 // X preserved
!next:
    dex
    bpl !instance-
    rts

// ---------------------------------------------------------------------------
// waveStartNext — the authored trigger has come due.
//
// Finds a free instance, arms it from the trigger's definition, and advances
// the cursor. THE CURSOR ADVANCES EITHER WAY: a trigger that finds both
// instances busy is DROPPED, not queued. Queueing would mean a stall could
// push the whole authored stage out of alignment with the terrain it was
// authored against, and an encounter that arrives two hundred rows late is
// worse than one that does not arrive.
// ---------------------------------------------------------------------------
waveStartNext:
    // ---- find a free instance --------------------------------------------
    ldx #WAVE_SLOTS - 1
!scan:
    lda wvActive,x
    beq !found+
    dex
    bpl !scan-

    lda wvDropped                       // none free: count it and move on
    cmp #$ff
    beq waveAdvanceCursor
    inc wvDropped
    jmp waveAdvanceCursor

!found:
    ldy wvNextTrig
    lda waveTrigDef,y
    sta wvDef,x
    lda waveTrigSpecies,y               // the authored species, latched onto the
    sta wvSpecies,x                     // INSTANCE now. The cursor advances at
                                        // the bottom of this routine, so this is
                                        // the last moment it still names the
                                        // wave being armed.
    lda waveTrigFire,y                  // ...and the fire mask with it, for the
    sta wvFire,x                        // same reason and at the same moment

    // The member count comes from the definition, so a wave that is armed is
    // armed completely: nothing below can leave it half-configured.
    jsr waveDefBase                     // Y = def * WAVEDEF_SIZE
    lda waveDefTable + 0,y
    sta wvLeft,x
    lda #1
    sta wvTimer,x                       // the first member goes out next frame
    lda #0
    sta wvIndex,x
    lda #1
    sta wvActive,x

    lda wvStarted
    cmp #$ff
    beq waveAdvanceCursor
    inc wvStarted
    // falls through

// ---------------------------------------------------------------------------
// waveAdvanceCursor — step to the next authored trigger and compute when it
// fires, as a sixteen-bit absolute worldProgress.
//
// The list WRAPS, which is the whole of "the sequence repeats": the deltas
// keep being added to a monotonically increasing target, so the pattern
// recurs for as long as the stage scrolls.
// ---------------------------------------------------------------------------
waveAdvanceCursor:
    inc wvNextTrig
    lda wvNextTrig
    cmp #WAVE_TRIGGERS
    bcc !armed+
    lda #0
    sta wvNextTrig
!armed:
    tay
    lda wvNextAtLo
    clc
    adc waveTrigDelta,y
    sta wvNextAtLo
    bcc !done+
    inc wvNextAtHi
!done:
    rts

// ---------------------------------------------------------------------------
// waveRunInstance — one frame of ONE active wave. Entry/exit: X = instance.
//
// POOL PRESSURE POLICY, AND IT IS DEFER RATHER THAN DROP.
//
// The pool is shared with hostile projectiles, so a wave can find it full
// through no fault of the encounter design -- three turret bolts in the air
// is an ordinary state of the world, not an error. A member that cannot be
// allocated therefore keeps its place: wvLeft is not decremented, wvIndex is
// not advanced, and the timer is set to one frame so the same member is tried
// again on the next. The wave stretches; it never loses a member and never
// overwrites a live object.
//
// The alternative -- skipping the member -- would make the encounter quietly
// different every time the pool happened to be busy, which is exactly the
// kind of non-determinism that makes authored content impossible to tune.
// ---------------------------------------------------------------------------
waveRunInstance:
    dec wvTimer,x
    beq !due+
    rts
!due:
    jsr waveSpawnMember                 // carry set = the pool refused
    bcc !sent+

    lda #1                              // DEFER: try the same member again
    sta wvTimer,x                       // next frame
    lda wvDeferred
    cmp #$ff
    beq !deferCounted+
    inc wvDeferred
!deferCounted:
    rts

!sent:
    inc wvIndex,x
    dec wvLeft,x
    beq !finished+

    jsr waveDefBase                     // Y = this wave's def * WAVEDEF_SIZE
    lda waveDefTable + 1,y              // interval
    sta wvTimer,x
    rts

!finished:
    lda #0                              // every member sent: the instance is
    sta wvActive,x                      // free for the next trigger. The
    rts                                 // enemies it made live on by
                                        // themselves -- nothing here owns them

// ===========================================================================
// ENEMY FIRING
// ===========================================================================
// ---------------------------------------------------------------------------
// waveFireTick — at most ONE enemy bolt leaves the screen. MAIN THREAD.
//
// WHERE THIS RUNS: late in gameFrame, beside turretFireTick and for the same
// two reasons, both of which are about correctness before cost. An enemy
// killed by the player this frame has already had collisionTick take its
// health to zero, so it cannot also shoot this frame; and a projectile spawned
// now is rendered where it was launched rather than moved before it has ever
// been seen.
//
// FOUR CYCLES ON AN ORDINARY FRAME. The period counter is decremented and the
// routine returns; the pool is not walked, no enemy is examined and nothing is
// read. One frame in WAVE_FIRE_PERIOD does the work below, and even that is a
// walk of sixteen bytes.
//
// THE SCAN IS ROUND-ROBIN, resuming at wvFireCursor, and that is what keeps
// the firing fair. Scanning from slot 0 every time would hand almost every
// shot to whichever eligible enemy happened to hold the lowest slot -- the
// pool allocates low-first, so that is systematically the OLDEST enemy on
// screen, the one furthest through its path and closest to leaving. The cursor
// advances past whoever was picked, so the licence rotates through the
// formation.
// ---------------------------------------------------------------------------
waveFireTick:
    dec wvFirePhase
    beq !opportunity+
    rts
!opportunity:
    lda #WAVE_FIRE_PERIOD               // RELOADED FIRST, exactly as
    sta wvFirePhase                     // turretFireTick reloads: an
                                        // opportunity that finds nobody costs a
                                        // whole period instead of retrying
                                        // every frame until it lands

    lda plyInvuln                       // an invulnerable ship is not shot at:
    beq !live+                          // the bolt would pass through it, and
    rts                                 // spending the cap on it would deny a
                                        // turret a real shot
!live:
    ldx wvFireCursor
    ldy #MAX_OBJECTS                    // every slot considered exactly once
!slot:
    lda enyFire,x                       // THE AUTHORED LICENCE, resolved at
    beq !next+                          // spawn: species AND encounter

    lda logActive,x                     // an object at all?
    beq !next+
    lda objType,x                       // ...an ENEMY? enyFire was cleared when
    cmp #TYPE_ENEMY                     // the slot was freed, so this is belt
    bne !next+                          // and braces -- and belts fail
    lda objHP,x
    beq !next+                          // DYING. Health reaches zero the moment
                                        // the player kills it and the twelve
                                        // frames of explosion that follow are
                                        // not a firing position

    lda logY,x                          // is it meaningfully on screen?
    cmp #ENEMY_FIRE_MIN_Y
    bcc !next+
    cmp #ENEMY_FIRE_MAX_Y
    bcs !next+

    clc                                 // the bolt falls: the ship has to be
    adc #ENEMY_FIRE_LEAD                // below, and not right on top of it
    cmp plyY
    bcs !next+

    jmp waveFireShot                    // out of branch range

!next:
    inx
    txa
    and #MAX_OBJECTS - 1                // sixteen slots: the wrap is a mask
    tax
    dey
    bne !slot-
    rts                                 // nobody eligible. The opportunity is
                                        // spent, and deliberately not saved

// ---------------------------------------------------------------------------
// waveFireShot — enemy X takes the shot. Falls out of waveFireTick's scan.
//
// THE CURSOR MOVES PAST THIS ENEMY WHETHER OR NOT THE BOLT EXISTS, and that is
// the anti-starvation rule: if the shared cap is full, the enemy that was
// picked does not get to be picked again next time in preference to everyone
// behind it.
// ---------------------------------------------------------------------------
waveFireShot:
    lda logX,x                          // LOGICAL COORDINATES, nine bits. No
    clc                                 // VIC register and no mux slot is read
    adc #ENEMY_MUZZLE_X                 // here or anywhere in this file: where
    sta ebSpawnXLo                      // the hardware happens to be drawing
    lda logXHi,x                        // this enemy is not where the enemy IS
    adc #0
    sta ebSpawnXHi
    lda logY,x
    clc
    adc #ENEMY_MUZZLE_Y
    sta ebSpawnY

    inx                                 // advance the round-robin past this
    txa                                 // enemy before anything can fail
    and #MAX_OBJECTS - 1
    sta wvFireCursor

    jsr ebulletSpawnDown                // THE SHARED PROJECTILE SYSTEM: the
                                        // same pool, the same cap of three, the
                                        // same flight and the same collision
                                        // the turrets have always used. Carry
                                        // set = the cap or the pool refused
    bcs !blocked+

    lda #SFX_ESHOT                      // THE SOUND FOLLOWS THE PROJECTILE, not
    jsr sfxRequest                      // the opportunity: a refused shot is
                                        // silent, because a sound with nothing
                                        // on screen behind it is a lie about
                                        // the state of the game

    lda wvShots
    cmp #$ff
    beq !done+
    inc wvShots
!done:
    rts

!blocked:
    lda wvShotBlocked
    cmp #$ff
    beq !counted+
    inc wvShotBlocked
!counted:
    rts

// ---------------------------------------------------------------------------
// waveSpawnMember — create one enemy for instance X.
//
// Entry: X = wave instance. Exit: X = wave instance, PRESERVED.
//        carry clear = spawned, carry set = the pool was full.
//
// The object index lives in wvSlot for the duration because X is the wave and
// the pool wants X to be the slot: two different things want the same
// register and the wave is the one the caller is holding.
// ---------------------------------------------------------------------------
waveSpawnMember:
    jsr waveDefBase                     // Y = def * WAVEDEF_SIZE
    sty wvDefBase                       // ...kept, objectAlloc clobbers nothing
                                        // but the arithmetic below needs it
    stx wvInst

    jsr objectAlloc                     // X = a zeroed free slot, or carry set
    bcc !got+
    jmp waveSpawnFull                   // the whole spawn body sits between
!got:                                   // here and there: out of branch range,
                                        // and a jmp is this repository's
                                        // documented answer to that

    // ---- position: startX + index * xStep, nine bits ----------------------
    ldy wvDefBase
    lda waveDefTable + 2,y
    sta logX,x
    lda waveDefTable + 3,y
    sta logXHi,x
    lda waveDefTable + 4,y
    sta logY,x

    // The fan-out is a repeated add rather than a multiply: wvIndex is at most
    // the member count, which is small, and a multiply here would be three
    // times the code for a loop that runs twice.
    //
    // BOTH AXES. The Y step is what turns a rank into an echelon, and it is the
    // cheap half: logY is eight bits, so it is one add with no carry to
    // propagate, against the nine-bit dance X has to do.
    ldy wvInst
    lda wvIndex,y
    beq !placed+
    sta wvCount
!fan:
    ldy wvDefBase
    lda waveDefTable + 5,y               // xStep, signed
    tay                                  // remember the sign
    clc
    adc logX,x
    sta logX,x
    tya
    bmi !fanLeft+
    bcc !fanY+
    inc logXHi,x
    jmp !fanY+
!fanLeft:
    bcs !fanY+
    dec logXHi,x
!fanY:
    ldy wvDefBase
    lda waveDefTable + 6,y               // yStep, signed
    clc
    adc logY,x
    sta logY,x

    dec wvCount
    bne !fan-
!placed:
    ldy wvDefBase

    // ---- presentation ------------------------------------------------------
    // SPECIES FIRST, because the frame depends on it. The instance's authored
    // species is COPIED onto the object here and never consulted again: from
    // this instruction on the enemy owns its own identity, and the instance
    // slot behind it may be freed and re-armed by a different authored wave
    // without touching it.
    ldy wvInst
    lda wvSpecies,y
    sta enySpecies,x

    // ---- may THIS ONE shoot? ----------------------------------------------
    // TWO INDEPENDENT AUTHORITIES, AND BOTH MUST SAY YES. The encounter says
    // whether this APPEARANCE fires -- bit `member index` of the authored mask
    // -- and the species says whether this ENEMY can fire at all. Neither can
    // override the other, and the answer is resolved HERE, once, rather than
    // being re-derived every frame by the firing tick.
    lda wvFire,y                        // Y is still the instance
    beq !noFire+                        // this formation does not shoot
    sta wvFireBit
    lda wvIndex,y                       // the member this is, 0-based
    tay
    lda wvFireBit
!shift:
    dey                                 // member 0 shifts nothing: dey goes
    bmi !tested+                        // negative and falls straight through
    lsr
    jmp !shift-
!tested:
    lsr                                 // the member's own bit -> carry
    bcc !noFire+

    lda enySpecies,x                    // THE SPECIES ANSWERS SECOND
    .for (var i = 0; i < ENEMY_ANIM_SHIFT; i++) { lsr }
    tay                                 // species row -> species index
    lda enemyFireModeTab,y
    beq !noFire+                        // a species that cannot fire, in a
                                        // wave authored to: the species wins
    sta enyFire,x                       // the MODE, not a bare flag: a later
    jmp !mayFire+                       // species fires differently by storing
!noFire:                                // a different value here
    lda #0
    sta enyFire,x
!mayFire:

    // THE ANIMATION'S CURRENT PHASE, not step 0. A new enemy is spawned by
    // waveTick AFTER objectUpdateAll has already run this frame, so its first
    // enemyTick is a frame away -- seed it with step 0 and it would show the
    // wrong frame for that one frame and then snap into phase with every other
    // enemy. Asking the same routine enemyTick asks means it is born in step.
    jsr enemyAnimPtr                    // A = this frame's pointer, X preserved
    sta logPtr,x
    ldy wvDefBase                       // enemyAnimPtr clobbers Y, so the wave
                                        // definition index is reloaded here
    lda waveDefTable + 7,y
    sta logCol,x
    sta wmBaseCol,x                     // what a hit flash returns to

    // ---- movement ----------------------------------------------------------
    // The launch heading and the first stage record, and then src/movement.asm
    // does the rest. wmEnterStage is the SAME routine that takes up every later
    // stage, so a pattern's first stage cannot behave differently from the same
    // stage in the middle of one -- which is why the mode, velocity and timer
    // are NOT set here by hand.
    lda waveDefTable + 8,y
    sta wmPhase,x                       // launch heading
    lda waveDefTable + 9,y
    sta wmStage,x                       // its pattern's first stage record
    lda #0
    sta wmAccX,x                        // objectAlloc zeroed these; setting
    sta wmAccY,x                        // them again is two bytes for a
                                        // guarantee that does not depend on
                                        // another file's promise
    jsr wmEnterStage                    // X preserved

    // ---- combat: an ordinary enemy, exactly as before ---------------------
    lda #ENEMY_MAX_HP
    sta objHP,x
    lda #TYPE_ENEMY
    sta objType,x

    // EVERY FIELD IS SET, so the object may now join the active set. Not one
    // instruction earlier: logActive is what the sorter reads.
    jsr objectActivate

    lda wvSpawned
    cmp #$ff
    beq !counted+
    inc wvSpawned
!counted:
    ldx wvInst
    clc
    rts

waveSpawnFull:
    ldx wvInst
    sec
    rts

// ---------------------------------------------------------------------------
// waveDefBase — Y = wvDef[X] * WAVEDEF_SIZE. Entry/exit: X preserved.
//
// WAVEDEF_SIZE is ten, so this is a shift-and-add rather than a multiply:
// n*10 = n*8 + n*2. Four definitions make the table forty bytes and the
// arithmetic could have been a lookup, but the lookup would need an entry per
// definition and this needs none.
// ---------------------------------------------------------------------------
waveDefBase:
    lda wvDef,x
    asl                                 // n*2
    sta wvScratch
    asl                                 // n*4
    asl                                 // n*8
    clc
    adc wvScratch                       // n*10
    tay
    rts

// ---------------------------------------------------------------------------
// Locals. Main thread only, and not per-instance: every routine that uses
// them runs to completion inside one call.
// ---------------------------------------------------------------------------
wvInst:     .byte 0                     // the wave instance, while X is a slot
wvDefBase:  .byte 0                     // its definition's table offset
wvCount:    .byte 0                     // fan-out repeat counter
wvFireBit:  .byte 0                     // the authored mask, while Y is re-aimed
                                        // at the member index that indexes it
wvScratch:  .byte 0                     // waveDefBase's partial product

// ---------------------------------------------------------------------------
// The authored content, as bytes.
//
// THE STAGE TABLE IS READ BY src/movement.asm, which is imported before this
// file: its interpreter indexes waveStageTable with the cursor each object
// carries. That direction is deliberate -- movement owns the FORMAT and the
// code that runs it, waves owns the BYTES -- and it works because
// KickAssembler resolves labels late even though it resolves constants in
// import order.
// ---------------------------------------------------------------------------
waveStageTable:
.for (var p = 0; p < progs.size(); p++) {
    .var prog = progs.get(p)
    .for (var s = 0; s < prog.size(); s++) {
        .var rec = prog.get(s)
        .byte rec.get(0), rec.get(1), rec.get(2) & $ff, rec.get(3) & $ff
    }
}
waveStageTableEnd:
.if (waveStageTableEnd - waveStageTable != progBytes) {
    .error "the stage table is not WM_STAGE_SIZE bytes per record"
}

waveDefTable:
.for (var d = 0; d < WAVE_DEFS; d++) {
    .var def = waveDefs.get(d)
    .for (var f = 0; f < WAVEDEF_SIZE; f++) {
        // Field 9 is authored as a program INDEX and stored as the byte offset
        // of that program's first record, so that the 6502 never multiplies.
        .if (f == 9) { .byte progAt.get(def.get(f)) } else { .byte def.get(f) & $ff }
    }
}
waveDefTableEnd:
.if (waveDefTableEnd - waveDefTable != WAVE_DEFS * WAVEDEF_SIZE) {
    .error "the wave definition table is not WAVEDEF_SIZE bytes per definition"
}

waveTrigDelta:
.for (var t = 0; t < WAVE_TRIGGERS; t++) { .byte trigDelta.get(t) }
waveTrigDef:
.for (var t = 0; t < WAVE_TRIGGERS; t++) { .byte trigDef.get(t) }
waveTrigSpecies:
.for (var t = 0; t < WAVE_TRIGGERS; t++) { .byte trigSpecies.get(t) }
waveTrigFire:
.for (var t = 0; t < WAVE_TRIGGERS; t++) { .byte trigFire.get(t) }
waveTrigEnd:
.if (waveTrigEnd - waveTrigDelta != 4 * WAVE_TRIGGERS) {
    .error "the trigger table is not four bytes per trigger"
}

.if (* > $8000) { .error "the wave code has outgrown its $7c00 segment" }
