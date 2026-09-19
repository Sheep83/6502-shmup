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

// THE MOVEMENT PROGRAM POOL is authored in src/wave_programs.asm and emitted
// into the level package, not into this binary. It is imported here because
// this file computes the program offsets and flies every path at assembly time.
#import "wave_programs.asm"


// THE AUTHORED ENCOUNTER SCHEDULE -- the wave definitions and the absolute
// trigger list -- lives in src/wave_encounters.asm and is emitted into the level
// package, not into this binary. It is imported here because this file owns the
// proofs over it and the addresses the director reads it from.
#import "wave_encounters.asm"


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
            // BYTE 3 IS A HEADING OR IT IS THE CONTINUE SENTINEL, and nothing
            // else. A value between WM_HEAD_LEN and WM_HEAD_CONT would index
            // off the end of the heading table at run time.
            .if (rec.get(3) != WM_HEAD_CONT && (rec.get(3) < 0 || rec.get(3) >= WM_HEAD_LEN)) {
                .error "an arc's entry heading is neither a heading nor WM_HEAD_CONT"
            }
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
            // AN ARC NAMES THE HEADING IT STARTS ON, or asks to continue from
            // the one already held. The simulation has to honour that or it
            // would be proving a path the engine does not fly; see the record
            // format in src/movement_format.asm.
            .if (isArc && rec.get(3) != WM_HEAD_CONT) {
                .eval head = rec.get(3)
            }
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
                    // src/enemy.asm's four rules, direction and all: a
                    // sprite behind a border counts as gone only if it
                    // is still traveling that way, which is what lets a
                    // pattern ENTER through one. The TOP rule is the newest
                    // and is the one every pattern here crosses on its way in
                    // -- which is exactly why it asks the direction.
                    .if (px < 0) { .eval wrapped = true }
                    .if ((px < ENEMY_CLEAR_X_LEFT && vx < 0)
                         || (px >= ENEMY_CLEAR_X_RIGHT && vx > 0)
                         || (py < ENEMY_CLEAR_Y_TOP && vy < 0)
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


.if (trigRow.size() != WAVE_TRIGGERS || trigDef.size() != WAVE_TRIGGERS
     || trigSpecies.size() != WAVE_TRIGGERS || trigFire.size() != WAVE_TRIGGERS
     || trigSide.size() != WAVE_TRIGGERS) {
    .error "the trigger list is not WAVE_TRIGGERS entries on every axis"
}
// THE CURSOR ONLY EVER WALKS FORWARD, so the rows must not go backwards. A
// trigger authored before the one in front of it could never become due -- the
// director would already have passed it by the time the cursor arrived -- and
// it would be invisible in play rather than a build failure.
//
// NON-DECREASING, NOT STRICTLY ASCENDING: two triggers at the SAME row are
// legal and meaningful. waveStartNext consumes one trigger per tick, so a pair
// sharing a row arms on consecutive frames -- which is how a mixed-species or
// mixed-formation appearance is authored without any per-member machinery. No
// code is needed for it; it falls out of a forward-only cursor.
.for (var t = 1; t < WAVE_TRIGGERS; t++) {
    .if (trigRow.get(t) < trigRow.get(t - 1)) {
        .error "the authored trigger rows are not in non-decreasing order"
    }
}
.for (var t = 0; t < WAVE_TRIGGERS; t++) {
    // The row is emitted as two bytes and compared against a sixteen-bit
    // worldProgress, so this is the real limit of the representation rather
    // than a policy.
    .if (trigRow.get(t) < 0 || trigRow.get(t) > $ffff) {
        .error "a trigger row does not fit the sixteen-bit world"
    }
    // AN AUTHORED ROW AT OR BEYOND THE BOSS APPROACH IS A CONTRADICTION.
    //
    // This note used to say that a row past the stage's own end was legitimate
    // -- a way to park an encounter. STAGE_NO_SPAWN_ROW replaces that: the
    // level now states where authoring stops, so a trigger on the far side of
    // it is not parked, it is dead data occupying one of the package's trigger
    // slots and describing an encounter the player can never meet.
    //
    // The RUNTIME still suppresses it robustly whatever the data says -- see
    // the gate in waveTick, which has to survive malformed external data -- but
    // a level that ASKS for one has contradicted itself, and saying so here is
    // cheaper than wondering later why an authored encounter never appeared.
    // This is the rule the eventual exporter should enforce as well.
    .if (trigRow.get(t) >= STAGE_NO_SPAWN_ROW) {
        .error "an authored trigger row is at or beyond STAGE_NO_SPAWN_ROW and could never start"
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
// ===========================================================================
// THE BOSS APPROACH
// ===========================================================================
// STAGE_NO_SPAWN_ROW is authored in the level's own stage_config.asm, beside
// the stage height that STAGE_FINAL_VIEW_PROGRESS is derived from, so the two
// cannot drift apart. These are the proofs that the value means something.
.if (STAGE_NO_SPAWN_ROW < 0 || STAGE_NO_SPAWN_ROW > $ffff) {
    .error "STAGE_NO_SPAWN_ROW must fit the sixteen bits worldProgress carries"
}
.if (STAGE_NO_SPAWN_ROW > STAGE_FINAL_VIEW_PROGRESS) {
    .error "STAGE_NO_SPAWN_ROW is beyond the last row the stage reaches: the quiet zone could never begin"
}
.if (STAGE_NO_SPAWN_ROW < 1) {
    .error "STAGE_NO_SPAWN_ROW at row zero would suppress the entire stage"
}

// THE ALTERNATION ITSELF IS CHECKED. This is the assertion that makes "every
// other wave is a Dropper" a property of the build rather than of someone
// having counted carefully.
//
// IT NO LONGER WRAPS. The list used to repeat for ever, so the last entry's
// neighbour really was the first and the check had to close the circle. With
// absolute rows the list ends, trigger 3 has no successor, and comparing it
// against trigger 0 would be asserting about an adjacency that never happens.
.for (var t = 1; t < WAVE_TRIGGERS; t++) {
    .if (trigSpecies.get(t) == trigSpecies.get(t - 1)) {
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
wvSide:    .fill WAVE_SLOTS, 0      // the entry side a Dropper in this wave
                                    // flies in from, latched with the species
                                    // below and for the same reason
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
// ONE BYTE, AND IT IS THE WHOLE SCHEDULE STATE. The cursor indexes the authored
// trigger list; the row that cursor fires at is read from the table, not kept
// here. WAVE_TRIGGERS -- one past the last trigger -- is the EXHAUSTED state,
// and it is reached by the ordinary `inc` rather than by a flag or a sentinel
// row. Nothing wraps it, and nothing can: the only `inc` is in waveStartNext,
// which the exhausted test above it has already refused to reach.
//
// The pair of bytes that used to live here -- wvNextAtLo/Hi, the running sum of
// the deltas -- is gone with the deltas.
wvNextTrig:  .byte 0                // cursor, 0..WAVE_TRIGGERS inclusive

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
// waveInit — no waves running, and the cursor on the first authored trigger.
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

    // THE CURSOR IS THE WHOLE ARMING, and it was zeroed with the rest of the
    // state above. There is no target to seed: trigger 0 becomes due when
    // worldProgress reaches the row trigger 0 names.
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
    // THE LEVEL IS ENDING. Every system that can put something new into the
    // arena tests this for itself rather than being switched off from
    // elsewhere, so each one stops in its own terms and nothing has to keep a
    // list of what to suppress. See src/boss.asm.
    // the authored encounter list is finished with: no trigger may start a
// wave once the stage has run out
    lda lvlPhase
    beq !playing+
    rts
!playing:
    // ---- is there an authored trigger left at all? ------------------------
    // THE CURSOR IS THE TERMINATION. WAVE_TRIGGERS is one past the last entry,
    // so this is both the bounds check on the indexed loads below and the
    // "schedule exhausted" test, and it costs three instructions. A stage that
    // runs for thousands of rows past its last authored moment takes this
    // branch every frame and does nothing, which is exactly right.
    ldy wvNextTrig
    cpy #WAVE_TRIGGERS
    bcs !noTrigger+

    // ---- THE BOSS APPROACH: has authoring stopped? ------------------------
    // Once worldProgress reaches STAGE_NO_SPAWN_ROW no ordinary authored
    // encounter may BEGIN, which is what makes the run-in to the boss a
    // deterministic clearance instead of whatever happened to be left alive.
    //
    // THE CURSOR IS EXHAUSTED, NOT MERELY SKIPPED, and that is the whole design.
    // Writing WAVE_TRIGGERS into it makes the suppression terminal: the bounds
    // test above takes over from the next frame on, so nothing is reconsidered,
    // nothing can be released later by the token hold below, and there is no
    // backlog for the boss transition to trip over. It also means this sixteen-
    // bit compare is paid only while triggers remain -- one frame after the
    // threshold the stage is back to three instructions a frame.
    //
    // IT SUPPRESSES A HELD TRIGGER TOO, deliberately, because it sits ABOVE the
    // tkActive hold. A trigger that came due before the threshold but was still
    // waiting on a token encounter when the world crossed it has not started,
    // and the authoring contract is that nothing which has not started may
    // begin at or beyond the row. Already-running waves are untouched: this
    // gate is only ever reached on the way to STARTING one.
    lda worldProgressHi
    cmp waveNoSpawnHi
    bcc !mayStart+
    bne !quiet+
    lda worldProgressLo
    cmp waveNoSpawnLo
    bcc !mayStart+
!quiet:
    lda #WAVE_TRIGGERS                  // terminal: the schedule is over
    sta wvNextTrig
    jmp !noTrigger+
!mayStart:

    // ---- has the world reached the row that trigger names? ----------------
    // A GENUINE SIXTEEN-BIT COMPARE: high bytes first, and the low bytes are
    // only consulted when the high bytes are equal. worldProgress reaches 1,655
    // on the 420-row proof stage, so the high byte is not decoration.
    //
    // The test is `>=`, not `==`, and that is load-bearing in two places. It is
    // what lets a trigger held through a token encounter stay due instead of
    // being missed by a row (see below), and it is what makes a row the stage
    // never reaches simply never fire rather than fire late.
    lda worldProgressHi
    cmp waveTrigRowHi,y
    bcc !noTrigger+
    bne !due+
    lda worldProgressLo
    cmp waveTrigRowLo,y
    bcc !noTrigger+
!due:
    // ---- ...and is the stage allowed to run right now? --------------------
    // A TOKEN ENCOUNTER PAUSES THE DIRECTOR, IT DOES NOT SKIP IT. The encounter
    // is meant to be three defenders and one token, and an authored wave
    // arriving into the middle of it would be four enemies the transition never
    // agreed to. But the trigger list is AUTHORED PROGRESSION -- a stage the
    // player is supposed to see -- so it is held rather than lost.
    //
    // THE HOLD IS NOW NOTHING AT ALL, AND THAT IS THE POINT. The delta schedule
    // had to walk its running target forward to worldProgress every held frame,
    // because the target was runtime state that would otherwise fall behind and
    // the trigger would be missed. An authored row cannot fall behind: it is a
    // constant, worldProgress only increases, and the compare above is `>=`. A
    // trigger that came due during an encounter is STILL due when the encounter
    // ends, without one byte being written to remember it.
    //
    // The cursor does not move, worldProgress is untouched, and the frame the
    // encounter ends the held trigger fires.
    //
    // ONE TRIGGER PER TICK, so an encounter long enough to outlast two authored
    // rows releases them on consecutive frames rather than together. That is the
    // existing `drop, don't queue late` policy doing its job -- if the second
    // finds both instances busy it is dropped and counted in wvDropped, which is
    // the honest outcome. It is not a backlog and it cannot compound: the cursor
    // only ever moves forward.
    //
    // This is deliberately the whole seam. Nothing else in the director knows
    // encounters exist, and removing token.asm would leave one dead branch.
    lda tkActive
    bne !noTrigger+
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
    // A TOKEN IS NO LONGER AUTHORED HERE. It used to be a column on the trigger
    // list -- an appearance could simply bring one -- and that is exactly the
    // semantics this slice replaces: a token is now a REWARD, dropped by a
    // destroyed Dropper at the place it died, and nothing else in the game
    // creates one. See src/token.asm and the death hook in src/enemy.asm.

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
    lda waveTrigSide,y                  // ...and the Dropper's entry side, which
    sta wvSide,x                        // is meaningless for a Ring wave and
                                        // latched anyway: one unconditional
                                        // copy beats a branch that has to know
                                        // what a species is

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
// waveAdvanceCursor — step to the next authored trigger. One instruction.
//
// THE LIST NO LONGER WRAPS, and this is where that used to happen. The cursor
// walked back to zero at WAVE_TRIGGERS and the next delta was added to a
// running target, so the four authored moments recurred for as long as the
// stage scrolled -- thirteen times over Level 1. Now the cursor simply counts
// past the last trigger and waveTick refuses to index beyond it.
//
// THERE IS NOTHING TO COMPUTE. The row the next trigger fires at is authored
// data; the director reads it where it lies.
//
// IT CANNOT RUN AWAY. The only path here is through waveStartNext, and waveTick
// refuses to call that once the cursor has reached WAVE_TRIGGERS -- so the
// cursor stops on exactly that value and no clamp is needed to hold it there.
// ---------------------------------------------------------------------------
waveAdvanceCursor:
    inc wvNextTrig
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
    // THE LEVEL IS ENDING. Every system that can put something new into the
    // arena tests this for itself rather than being switched off from
    // elsewhere, so each one stops in its own terms and nothing has to keep a
    // list of what to suppress. See src/boss.asm.
    // no enemy may open fire during the arena clear or the boss fight
    lda lvlPhase
    beq !playing+
    rts
!playing:
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

    // ONE LIVE DROPPER, EVER, AND THIS IS THE WHOLE RULE. A Dropper's death is
    // what drops the token, so two of them alive at once would mean two tokens
    // and two overlapping encounters. The check is made HERE, at the single
    // instruction that commits a species to an object, rather than at the
    // trigger or at the instance: this is the last moment before the enemy
    // exists and the only place the answer can be wrong.
    //
    // A REFUSED DROPPER STILL FLIES. It is substituted with a Ring rather than
    // dropped, because the authored wave's shape, count and timing are the
    // content -- silently spawning one fewer member would quietly rewrite an
    // encounter the level author wrote, where a different enemy on the same
    // path keeps it.
    cmp #SPECIES_DROPPER
    bne !species+
    ldy tkDropperLive
    beq !claim+
    lda #SPECIES_RING                   // one is already out there
    jmp !species+
!claim:
    ldy #1
    sty tkDropperLive                   // this one is now THE Dropper;
                                        // src/enemy.asm clears it when this
                                        // object dies or leaves
!species:
    sta enySpecies,x

    ldy wvInst

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

    // ---- ...AND A DROPPER IS THEN TAKEN OFF THAT PATH ---------------------
    // AFTER wmEnterStage, not before, and the order is the whole of it: the
    // stage the wave just armed writes wmMode, wmVX, wmVY and wmTimer, so a
    // flight installed above would be overwritten a dozen instructions later.
    // Arm the member like any other and then take it over, which also means
    // there is never a half-configured object -- it is a complete wave member
    // right up to the instant it becomes a complete Dropper.
    //
    // WHY A DROPPER DOES NOT FLY ITS WAVE'S PATH. Its death is the only death
    // in the game that is worth something, so WHERE it dies is a gameplay fact:
    // killed low, the P it drops has no room for the encounter it starts. A
    // formation path authored for Rings cannot promise that. See src/dropper.asm.
    lda enySpecies,x
    cmp #SPECIES_DROPPER
    bne !ordinary+
    ldy wvInst
    lda wvSide,y                        // the side this appearance authored
    jsr dropperLaunch                   // X preserved
!ordinary:

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
// THE MOVEMENT POOL IS NOT IN THIS BINARY. It lives in the separately loaded
// level package at LEVELPKG_MOVE, emitted by src/level_package.asm from the same
// src/wave_programs.asm this file imports. What stays here is the ADDRESS the
// interpreter reads and the offsets the wave definitions name.
//
// src/movement.asm indexes it as `lda waveStageTable + n,y` -- absolute,Y, which
// costs the same four cycles wherever the table lives, so the move is free.
.label waveStageTable = LEVELPKG_MOVE

.if (progBytes > LEVELPKG_MOVE_MAX) {
    .error "the movement pool has outgrown its level-package budget"
}

// THE WAVE DEFINITIONS ARE NOT IN THIS BINARY. Like the movement pool before
// them they live in the separately loaded level package, emitted by
// src/level_package.asm from the same src/wave_encounters.asm this file
// imports. What stays here is the ADDRESS the director reads.
//
// waveDefBase forms Y = def * WAVEDEF_SIZE and every field is then
// `lda waveDefTable + n,y` -- absolute,Y, four cycles wherever the table lives,
// so the move costs nothing.
.label waveDefTable = LEVELPKG_WAVEDEF

.if (WAVE_DEFS * WAVEDEF_SIZE > LEVELPKG_WAVEDEF_MAX) {
    .error "the wave definitions have outgrown their level-package budget"
}
.if ((WAVE_DEFS - 1) * WAVEDEF_SIZE > 255) {
    .error "waveDefBase forms def * WAVEDEF_SIZE in one byte: too many definitions"
}

// PARALLEL COLUMNS, and the row is two of them. Split lo/hi rather than
// interleaved so the director's compare is two `absolute,Y` loads against the
// cursor it already holds in Y -- no record stride, and no multiply.
// THE TRIGGER LIST IS NOT IN THIS BINARY EITHER, and for the same reason. Six
// parallel columns, each one byte per trigger, each read `lda waveTrigX,y` with
// the SAME cursor -- so the columns are addresses rather than data here.
//
// PARALLEL, NOT INTERLEAVED, DELIBERATELY. One cursor serves all six columns at
// four cycles a field; an interleaved six-byte record would need that cursor
// multiplied by six on every read for no gain in what can be stored.
// THE BOSS APPROACH, read from the package rather than compiled in. Two bytes
// of the stage header; see src/levelpkg.asm for why it is data and not a
// constant.
.label waveNoSpawnLo   = LEVELPKG_NOSPAWN + 0
.label waveNoSpawnHi   = LEVELPKG_NOSPAWN + 1

.label waveTrigRowLo   = LEVELPKG_TRIG + 0 * LEVELPKG_TRIG_SLOTS
.label waveTrigRowHi   = LEVELPKG_TRIG + 1 * LEVELPKG_TRIG_SLOTS
.label waveTrigDef     = LEVELPKG_TRIG + 2 * LEVELPKG_TRIG_SLOTS
.label waveTrigSpecies = LEVELPKG_TRIG + 3 * LEVELPKG_TRIG_SLOTS
.label waveTrigFire    = LEVELPKG_TRIG + 4 * LEVELPKG_TRIG_SLOTS
.label waveTrigSide    = LEVELPKG_TRIG + 5 * LEVELPKG_TRIG_SLOTS

.if (WAVE_TRIGGERS > LEVELPKG_TRIG_SLOTS) {
    .error "more authored triggers than the level package reserves room for"
}

.if (* > $8000) { .error "the wave code has outgrown its $7c00 segment" }
