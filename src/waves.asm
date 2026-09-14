// ===========================================================================
// waves.asm — the encounter director, v1
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
// ---------------------------------------------------------------------------
// WHAT THIS REPLACES, AND WHY IT IS A REPLACEMENT RATHER THAN A LAYER
// ---------------------------------------------------------------------------
// src/enemy.asm carried a four-entry spawn table cycled on a 48-frame timer.
// Its own comment said what it was for: "This is NOT a wave system and is not
// the seed of one. It exists so that the lifecycle runs continuously on a
// normal boot." It did that job and this file takes it over whole -- the
// timer, the cursor, the table and the colours are gone rather than wrapped,
// because a spawner that still runs underneath a director is a second author
// of the same screen and the two would fight over the pool.
//
// What is NOT replaced: enemies remain ordinary TYPE_ENEMY objects with the
// same art, the same six HP, the same hit flash, the same death animation and
// the same single vertical despawn rule. The player's hitscan, the turrets
// and the hostile projectiles do not know this file exists.
//
// ---------------------------------------------------------------------------
// THE SHAPE OF v1, AND WHAT IS DELIBERATELY ABSENT
// ---------------------------------------------------------------------------
// Two concurrent wave instances, a fixed authored trigger list, two wave
// definitions and three movement primitives. No random selection, no
// difficulty curve, no population budget, no formation AI, no upgrade
// carriers, no escorts, no boss logic, no enemy firing, no procedural
// generation. Those are later slices and every one of them is easier to add
// to a small thing that works than to a large thing that nearly does.
//
// WAVE_SLOTS is a compile-time constant and raising it costs exactly one
// constant: every loop below is bounded by it, nothing is unrolled, and no
// state is shared between instances.
// ===========================================================================

// --- how many waves may run at once ----------------------------------------
// Two is the point of the slice. The arrays, the loops and the free-instance
// scan are all written against the constant, so three costs five bytes of
// state and no code at all.
.const WAVE_SLOTS = 2

// --- the authored wave definitions ------------------------------------------
// Twelve bytes each, and the record is deliberately flat: the director reads
// it with one indexed load per field and never copies it anywhere.
//
//   0  count      how many enemies this wave sends
//   1  interval   frames between one member and the next
//   2  startXLo   nine-bit spawn X...
//   3  startXHi
//   4  startY     spawn line, inside the renderer's production band
//   5  xStep      signed, added to X per member, so a wave fans rather than
//                 forming a single-file queue
//   6  colour     every member of a wave shares one, so which wave an enemy
//                 belongs to is visible on screen
//   7  mode       the movement primitive it launches with
//   8  vx         quarter pixels per frame, signed
//   9  vy         quarter pixels per frame, signed
//  10  timer      frames in the launch primitive (WM_STRAIGHT), or the phase
//                 length when launching straight into an arc
//  11  next       the primitive to take up when the launch one finishes
.const WAVEDEF_SIZE = 12

// ---------------------------------------------------------------------------
// DEFINITION 0 — "left sweep". Enters top-left travelling RIGHT along the top
// of the aperture, holds that line long enough to be worth shooting at, then
// turns down through the arc and leaves.
//
// vx = +6 quarter pixels is 1.5 px/frame, and the launch velocity is exactly
// the arc's phase-0 velocity (+WM_ARC_SPEED, 0) so that the turn begins with
// no discontinuity at all -- see wmEnterNext.
// ---------------------------------------------------------------------------
.var defLeftSweep = List().add(
    4,                  // count
    28,                 // interval
    48, 0,              // startX = 48
    60,                 // startY
    14,                 // xStep: members fan to the right
    10,                 // colour: light red
    WM_STRAIGHT,        // mode
    WM_ARC_SPEED, 0,    // vx, vy -- the arc's own phase-0 velocity
    40,                 // timer: 40 frames of level flight first
    WM_ARC)             // then turn down

// ---------------------------------------------------------------------------
// DEFINITION 1 — "right hook". Enters top-right and turns down IMMEDIATELY,
// mirrored, so it crosses the left sweep's path rather than trailing it.
//
// It launches straight into WM_ARC_MIRROR: mode is the arc itself, timer is
// the phase length, and next is WM_EXIT.
// ---------------------------------------------------------------------------
.var defRightHook = List().add(
    3,                  // count
    20,                 // interval
    290 - 256, 1,       // startX = 290
    72,                 // startY
    -14,                // xStep: members fan to the left
    3,                  // colour: cyan
    WM_ARC_MIRROR,      // mode
    -WM_ARC_SPEED, 0,   // vx, vy -- phase 0, mirrored
    WM_ARC_STEP,        // timer: one phase
    WM_EXIT)            // then straight on out

.var waveDefs = List().add(defLeftSweep).add(defRightHook)
.const WAVE_DEFS = 2
.const WAVE_DEF_LEFT  = 0
.const WAVE_DEF_RIGHT = 1

.if (waveDefs.size() != WAVE_DEFS) { .error "wave definition count disagrees with the table" }

// ASSEMBLY-TIME PROOFS over the authored content. Every one of these is a
// mistake that would produce an enemy nobody can see, or one that never
// leaves and holds a pool slot for the rest of the session.
.for (var d = 0; d < WAVE_DEFS; d++) {
    .var def = waveDefs.get(d)
    .if (def.size() != WAVEDEF_SIZE) { .error "a wave definition is not WAVEDEF_SIZE bytes" }
    .if (def.get(0) < 1) { .error "a wave definition sends no enemies" }
    .if (def.get(1) < 1) { .error "a wave interval of zero would spawn the whole wave in one frame" }

    // The first member, and the last, must both start inside the nine-bit
    // world AND inside the renderer's production Y band. The last matters
    // because xStep walks the spawn point across the screen.
    .var x0 = def.get(2) + 256 * def.get(3)
    .var xN = x0 + def.get(5) * (def.get(0) - 1)
    .if (x0 < 0 || x0 > 343) { .error "a wave's first member spawns outside the nine-bit X range" }
    .if (xN < 0 || xN > 343) { .error "a wave's last member spawns outside the nine-bit X range" }
    .if (def.get(4) < MIN_SPRITE_Y || def.get(4) > MAX_SPRITE_Y) {
        .error "a wave spawns outside the renderer's production Y band"
    }
    .if (def.get(7) >= WM_MODES) { .error "a wave names a movement primitive that does not exist" }
    .if (def.get(11) >= WM_MODES) { .error "a wave names a follow-on primitive that does not exist" }

    // TERMINATION. The single despawn rule is vertical, so every authored
    // path must end descending. A launch primitive that is bounded (a timer)
    // hands over to `next`, and both arcs end descending by movement.asm's
    // own proof -- so the only way to author a permanent resident is to
    // launch WM_STRAIGHT or WM_EXIT with a non-positive vy and nothing to
    // follow it.
    .if (def.get(7) == WM_STRAIGHT || def.get(7) == WM_EXIT) {
        .if (def.get(10) == 0 && def.get(9) <= 0) {
            .error "a wave launches on an unbounded non-descending vector and could never despawn"
        }
        .if ((def.get(11) == WM_STRAIGHT || def.get(11) == WM_EXIT) && def.get(9) <= 0) {
            .error "a wave's follow-on vector never descends and could never despawn"
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
// FIVE COARSE ROWS BETWEEN LEFT AND RIGHT, AND THE NUMBER IS LOAD-BEARING.
// worldProgress advances once every eight frames, so five rows is forty
// frames. A wave INSTANCE is active for exactly as long as it is still
// sending members -- LEFT sends four at twenty-eight frame intervals, so it
// occupies its instance for about eighty-four frames -- and RIGHT therefore
// arrives with LEFT still less than half way through its own spawning. That
// is what puts two instances in flight at once rather than merely two groups
// of enemies on screen.
//
// It was authored at ten rows first, which is eighty frames, and the two
// waves then queued politely one after another: the first instance had
// finished spawning a few frames before the second was triggered, and the
// director never held two at once. The enemies still overlapped -- they
// outlive their wave by seconds -- which is exactly the kind of nearly-right
// that a test looking only at the screen would have passed.
.var trigDelta = List().add(24, 5, 30, 5)
.var trigDef   = List().add(WAVE_DEF_LEFT, WAVE_DEF_RIGHT, WAVE_DEF_LEFT, WAVE_DEF_RIGHT)
.const WAVE_TRIGGERS = 4

.if (trigDelta.size() != WAVE_TRIGGERS || trigDef.size() != WAVE_TRIGGERS) {
    .error "the trigger list is not WAVE_TRIGGERS entries on both axes"
}
.for (var t = 0; t < WAVE_TRIGGERS; t++) {
    .if (trigDelta.get(t) < 1) {
        .error "a trigger delta of zero would fire every frame for ever"
    }
    .if (trigDef.get(t) >= WAVE_DEFS) { .error "a trigger names a wave definition that does not exist" }
}

// ===========================================================================
// State. MAIN THREAD ONLY.
// ===========================================================================
* = $77a0 "wave state"

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

waveStateEnd:
.if (waveStateEnd > $7800) { .error "the wave state has grown into the movement code at $7800" }
.if (movementStateEnd > $77a0) {
    .error "the movement state has grown into this block"
}

// ===========================================================================
* = $7a00 "waves"

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
    dex
    bpl !slot-

    sta wvNextTrig
    sta wvStarted
    sta wvDropped
    sta wvDeferred
    sta wvSpawned

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

    // The fan-out is a repeated add rather than a multiply: wvIndex is at most
    // the member count, which is small, and a multiply here would be three
    // times the code for a loop that runs twice.
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
    bcc !fanNext+
    inc logXHi,x
    jmp !fanNext+
!fanLeft:
    bcs !fanNext+
    dec logXHi,x
!fanNext:
    dec wvCount
    bne !fan-
!placed:

    ldy wvDefBase
    lda waveDefTable + 4,y
    sta logY,x

    // ---- presentation ------------------------------------------------------
    lda #ENEMY_PTR
    sta logPtr,x
    lda waveDefTable + 6,y
    sta logCol,x
    sta wmBaseCol,x                     // what a hit flash returns to

    // ---- movement ----------------------------------------------------------
    lda waveDefTable + 7,y
    sta wmMode,x
    lda waveDefTable + 8,y
    sta wmVX,x
    lda waveDefTable + 9,y
    sta wmVY,x
    lda waveDefTable + 10,y
    sta wmTimer,x
    lda waveDefTable + 11,y
    sta wmNext,x
    lda #0
    sta wmPhase,x
    sta wmAccX,x                        // objectAlloc zeroed these; setting
    sta wmAccY,x                        // them again is two bytes for a
                                        // guarantee that does not depend on
                                        // another file's promise

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
// WAVEDEF_SIZE is twelve, so this is a shift-and-add rather than a multiply:
// n*12 = n*8 + n*4. Two definitions make the table twenty-four bytes and the
// arithmetic could have been a lookup, but the lookup would need an entry per
// definition and this needs none.
// ---------------------------------------------------------------------------
waveDefBase:
    lda wvDef,x
    asl                                 // n*2
    asl                                 // n*4
    sta wvScratch
    asl                                 // n*8
    clc
    adc wvScratch                       // n*12
    tay
    rts

// ---------------------------------------------------------------------------
// Locals. Main thread only, and not per-instance: every routine that uses
// them runs to completion inside one call.
// ---------------------------------------------------------------------------
wvInst:     .byte 0                     // the wave instance, while X is a slot
wvDefBase:  .byte 0                     // its definition's table offset
wvCount:    .byte 0                     // fan-out repeat counter
wvScratch:  .byte 0                     // waveDefBase's partial product

// ---------------------------------------------------------------------------
// The authored content, as bytes.
// ---------------------------------------------------------------------------
waveDefTable:
.for (var d = 0; d < WAVE_DEFS; d++) {
    .var def = waveDefs.get(d)
    .for (var f = 0; f < WAVEDEF_SIZE; f++) { .byte def.get(f) }
}
waveDefTableEnd:
.if (waveDefTableEnd - waveDefTable != WAVE_DEFS * WAVEDEF_SIZE) {
    .error "the wave definition table is not WAVEDEF_SIZE bytes per definition"
}

waveTrigDelta:
.for (var t = 0; t < WAVE_TRIGGERS; t++) { .byte trigDelta.get(t) }
waveTrigDef:
.for (var t = 0; t < WAVE_TRIGGERS; t++) { .byte trigDef.get(t) }
waveTrigEnd:
.if (waveTrigEnd - waveTrigDelta != 2 * WAVE_TRIGGERS) {
    .error "the trigger table is not two bytes per trigger"
}

.if (* > $7c00) { .error "the wave code has outgrown its $7a00 segment" }
