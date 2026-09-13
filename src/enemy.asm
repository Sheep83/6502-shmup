// ===========================================================================
// enemy.asm — the first production enemy: the straight diver
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is written from this file, and the
// word "slot" never appears in it in the hardware sense. An enemy knows its
// logical position and its velocity; whether it is drawn, and through which
// hardware sprite, is entirely the renderer's business.
//
// ---------------------------------------------------------------------------
// WHAT THE OLD GAME ACTUALLY DID
// ---------------------------------------------------------------------------
// Read out of shooter_test/src/main.asm. The relevant pieces are the ingress
// fragment table (5918), spawnEnemy (4860), moveEnemyPath (3055) and the art
// and colour tables at 5561 and 5808.
//
//   THE SIMPLEST ENEMY IS A STRAIGHT DIVE. The first ingress fragment in the
//   old table is ingressTopStraightShort:
//
//       .byte 48,  0,  2     // duration 48 frames, vx 0, vy 2
//
//   "Straight dive from common top entry Y", in the old file's own words. Two
//   pixels per frame downward, no horizontal component. That is the whole
//   behaviour, and it is the one this slice migrates.
//
//   VELOCITIES ARE WHOLE PIXELS PER FRAME. There is no sub-pixel accumulator
//   anywhere in the old movement code: moveEnemyPath adds OBJECT_VEL_Y to
//   OBJECT_Y directly. Kept, because inventing a fractional representation here
//   would silently change every speed the old content was authored against.
//
//   VELOCITY IS SUPPLIED AT SPAWN, NOT BAKED INTO THE TYPE. One TYPE_ENEMY,
//   many trajectories. Kept exactly: the spawn table below carries (vx, vy) per
//   entry, which is why a diagonal entry needs no new type.
//
//   REMOVAL IS A BOUNDS TEST. The old bullet path frees the moment Y passes the
//   bottom of the screen (3040). Kept as the single despawn rule.
//
// DELIBERATELY NOT TAKEN:
//   * the segmented ingress/manoeuvre/egress path machine, easeVelocityToward-
//     Target, and the whole fragment table. That IS the wave system, and it is
//     the next slice's subject rather than this one's.
//   * OBJECT_HEALTH and the impact flash. Nothing can shoot an enemy yet: the
//     Slice B shot event is still emitted every volley and still expires
//     unconsumed, exactly as it did before this file existed.
//   * the multicolour art path. This engine forces $d01c to zero -- every
//     hardware sprite is hires -- so the old bitmap is converted at ASSEMBLY
//     time, below, rather than at run time.
//
// ---------------------------------------------------------------------------
// WORLD SEMANTICS: THIS ENEMY IS SCREEN-SPACE, AND THAT IS A DECISION
// ---------------------------------------------------------------------------
// logY is a raster line, not a stage row. The enemy does not read the scroller,
// does not read worldProgress, and does not move with the terrain.
//
// That is what the old game did -- its enemies were screen-space objects with
// velocities, and only the DECISION TO SPAWN came from wave state -- and it is
// what keeps this compatible with the wave migration: a wave system asks
// worldProgress when to spawn, then hands the object a screen position and a
// vector. Nothing in this file has to change for that to work, which is the
// test of whether the boundary was drawn in the right place.
//
// The scroll direction settled in Slice A' is why vy is POSITIVE. The terrain
// moves down and the player flies up, so an enemy that approaches the player
// comes from the top of the aperture and descends. See docs/ENGINE_CONTRACT.md
// section 8a.
// ===========================================================================

// --- the numbers, from shooter_test/src/main.asm:5921 and 991-994 ----------
.const ENEMY_MAX_HP      = 6        // ENEMY_START_HEALTH, main.asm:995. TYPE
                                   // data: every enemy of this type starts
                                   // here, so no per-object maximum is stored
.const ENEMY_VY          = 2        // the old ingressTopStraightShort dive
.const ENEMY_SPAWN_PERIOD = 48      // frames between spawns; see the note below

// The enemy bitmap goes in the last free 64-byte block of VIC bank 0, between
// the player's art and the blank charset the aperture depends on.
.const ENEMY_SPRITES     = PLAYER_SPRITES_END
.const ENEMY_PTR         = ENEMY_SPRITES / 64
.if ((ENEMY_SPRITES & 63) != 0) { .error "the enemy bitmap must be 64-byte aligned" }

// The renderer's production Y band, restated as literals rather than aliased.
// Sharing a bound is a DECISION and a decision deserves a check, which is why
// these are asserted against the renderer's own constants below rather than
// quietly importing them -- the same rule src/player.asm follows.
.const ENEMY_SPAWN_Y     = 55       // MIN_SPRITE_Y: the first renderable line
.const ENEMY_DESPAWN_Y   = 226      // MAX_SPRITE_Y: the last renderable line

.if (ENEMY_SPAWN_Y != MIN_SPRITE_Y) {
    .error "the enemy spawns outside the renderer's production Y band"
}
.if (ENEMY_DESPAWN_Y != MAX_SPRITE_Y) {
    .error "the enemy despawn line no longer matches the renderer's Y band"
}

// ===========================================================================
// The spawn table. Four entries, cycled.
// ===========================================================================
// This is NOT a wave system and is not the seed of one. It exists so that the
// lifecycle -- allocate, activate, update, sort, render, despawn, REUSE the
// slot -- runs continuously on a normal boot without a debug key, because a
// lifecycle that only runs when a test pokes it is a lifecycle nobody has
// watched.
//
// Two of the four entries deliberately cross the 255/256 horizontal boundary
// during flight, one in each direction, so that the nine-bit X path and the
// $d010 composition are exercised by ordinary play rather than only by a test.
//
// The table is built as an ASSEMBLER list and then emitted, rather than written
// straight out as .byte rows, so that the proof below can read it. A proof that
// cannot see the data it is about is not a proof.
//
//                            xLo  xHi  vx  vy    colour (old set 0)
.var enySpawns = List()
.eval enySpawns.add(List().add( 72,  0,  0, ENEMY_VY,  2))   // dive, left of centre
.eval enySpawns.add(List().add(160,  0,  0, ENEMY_VY,  6))   // dive, centre
.eval enySpawns.add(List().add(248,  0,  1, ENEMY_VY, 10))   // drifts RIGHT across X=256
.eval enySpawns.add(List().add( 40,  1, -1, ENEMY_VY,  7))   // from X=296, drifts LEFT across it

.const ENEMY_SPAWN_ENTRIES = 4
.if (enySpawns.size() != ENEMY_SPAWN_ENTRIES) { .error "spawn entry count disagrees with the table" }

// TERMINATION PROOF. The single despawn rule is "Y has passed the bottom of the
// band", so an enemy with vy <= 0 would never despawn and would hold its pool
// slot for ever. Rather than defend against that at run time, refuse to
// assemble it.
//
// The spawn X is proven to start inside the nine-bit world too, so that a
// mistyped entry cannot put an enemy somewhere the renderer will silently
// refuse to draw for its whole life.
.for (var e = 0; e < ENEMY_SPAWN_ENTRIES; e++) {
    .if (enySpawns.get(e).get(3) <= 0) {
        .error "a spawn entry has a non-descending vy, so that enemy could never despawn"
    }
    .var x9 = enySpawns.get(e).get(0) + 256 * enySpawns.get(e).get(1)
    .if (x9 < 0 || x9 > 343) {
        .error "a spawn entry starts outside the nine-bit horizontal range"
    }
}

// ===========================================================================
// Art. The old multicolour bitmap, flattened to hires at assembly time.
// ===========================================================================
// The engine forces $d01c to zero: every hardware sprite is hires, including
// the mux slots. The old enemy was multicolour, so each two-bit pair becomes
// two hires pixels if it was set to ANY of the three colours and two blank
// pixels if it was background.
//
// That is a silhouette, not a recolour: the old art's internal shading is lost
// and the shape is kept. It is the honest conversion for a one-layer sprite --
// the player affords two layers because it owns two reserved hardware sprites,
// and a mux enemy owns one.

// One multicolour byte to one hires byte: every non-background pair lit.
.function enemyHires(b) {
    .var v = 0
    .for (var p = 0; p < 4; p++) {
        .var sh = 6 - 2 * p
        .if (((b >> sh) & 3) != 0) { .eval v = v | (3 << sh) }
    }
    .return v
}

.var enemyMC = List()
.eval enemyMC.add($00,$28,$00)
.eval enemyMC.add($00,$aa,$00)
.eval enemyMC.add($00,$be,$00)
.eval enemyMC.add($02,$be,$80)
.eval enemyMC.add($02,$7d,$80)
.eval enemyMC.add($0a,$7d,$a0)
.eval enemyMC.add($29,$69,$68)
.eval enemyMC.add($a5,$aa,$5a)
.eval enemyMC.add($96,$be,$96)
.eval enemyMC.add($06,$ff,$90)
.eval enemyMC.add($06,$eb,$90)
.eval enemyMC.add($06,$aa,$90)
.eval enemyMC.add($01,$aa,$40)
.eval enemyMC.add($01,$69,$40)
.eval enemyMC.add($00,$69,$00)
.eval enemyMC.add($00,$7d,$00)
.eval enemyMC.add($01,$41,$40)
.eval enemyMC.add($05,$00,$50)
.eval enemyMC.add($14,$00,$14)
.eval enemyMC.add($00,$00,$00)
.eval enemyMC.add($00,$00,$00)

.if (enemyMC.size() != 21 * 3) { .error "the enemy bitmap must be 21 rows of 3 bytes" }

* = ENEMY_SPRITES "enemy bitmap"
enemyBitmap:
.for (var r = 0; r < 21; r++) {
    .for (var c = 0; c < 3; c++) {
        .byte enemyHires(enemyMC.get(r * 3 + c))
    }
}
    .byte $00                           // 64th padding byte
enemyBitmapEnd:
.if (enemyBitmapEnd - enemyBitmap != 64) { .error "the enemy bitmap must be exactly 64 bytes" }
.if (enemyBitmapEnd > BLANK_CHARSET) { .error "the enemy bitmap has run into the blank charset" }

//        xLo  xHi   vx   vy
enemySpawnTable:
.for (var e = 0; e < ENEMY_SPAWN_ENTRIES; e++) {
    .byte enySpawns.get(e).get(0), enySpawns.get(e).get(1)
    .byte enySpawns.get(e).get(2), enySpawns.get(e).get(3)
}
enemySpawnTableEnd:
.if (enemySpawnTableEnd - enemySpawnTable != ENEMY_SPAWN_ENTRIES * 4) {
    .error "the spawn table must be exactly four bytes per entry"
}

// The old game's first visual set colours, one per spawn entry.
// shooter_test/src/main.asm:5809.
enemyColours:
.for (var e = 0; e < ENEMY_SPAWN_ENTRIES; e++) {
    .byte enySpawns.get(e).get(4)
}
enemyColoursEnd:
.if (enemyColoursEnd - enemyColours != ENEMY_SPAWN_ENTRIES) {
    .error "there must be exactly one enemy colour per spawn entry"
}

// ===========================================================================
// State.
// ===========================================================================
// Moved out of $c5e0 in Slice D so the object pool's per-object arrays can grow
// contiguously. Six bytes in the hole between the P5 ring's state and the
// player's, rather than a second gap further up the page.
* = $c517 "enemy state"
enySpawnTimer: .byte 0                  // frames until the next spawn attempt
enySpawnNext:  .byte 0                  // which spawn entry is next, 0..N-1
enySpawned:    .byte 0, 0               // 16-bit, saturating: total spawned
enyDespawned:  .byte 0, 0               // 16-bit, saturating: total despawned
enyStateEnd:
.if (enyStateEnd > $c520) { .error "the enemy state has grown into the player state at $c520" }

* = $4900 "enemy code"

// ---------------------------------------------------------------------------
// enemyInit — no enemies, and the first spawn one period away.
// ---------------------------------------------------------------------------
enemyInit:
    lda #ENEMY_SPAWN_PERIOD
    sta enySpawnTimer
    lda #0
    sta enySpawnNext
    sta enySpawned
    sta enySpawned + 1
    sta enyDespawned
    sta enyDespawned + 1
    rts

// ---------------------------------------------------------------------------
// enemySpawnTick — the cadence. MAIN THREAD, once per frame.
//
// A spawn that the pool refuses is NOT retried on the next frame: the timer is
// reloaded either way. A full pool means the screen is already as busy as this
// slice allows, and retrying every frame would turn a transient full pool into
// a burst the moment one slot frees.
// ---------------------------------------------------------------------------
enemySpawnTick:
    dec enySpawnTimer
    bne !done+
    lda #ENEMY_SPAWN_PERIOD
    sta enySpawnTimer
    jsr enemySpawn
!done:
    rts

// ---------------------------------------------------------------------------
// enemySpawn — one enemy from the next spawn-table entry.
//
// Returns: carry clear if one was spawned, carry set if the pool was full.
// The entry cursor advances ONLY on success, so a refused spawn does not skip
// a formation member -- the old game advanced WAVE_SPRITE_INDEX "only after a
// successful allocation/spawn" for the same reason (4894).
// ---------------------------------------------------------------------------
enemySpawn:
    jsr objectAlloc                     // X = a zeroed free slot, or carry set
    bcc !got+
    rts                                 // pool full; carry still set
!got:
    // Y indexes the spawn table: entry * 4.
    lda enySpawnNext
    asl
    asl
    tay

    lda enemySpawnTable + 0,y
    sta logX,x
    lda enemySpawnTable + 1,y
    sta logXHi,x
    lda enemySpawnTable + 2,y
    sta objVX,x
    lda enemySpawnTable + 3,y
    sta objVY,x

    lda #ENEMY_SPAWN_Y
    sta logY,x
    lda #ENEMY_PTR
    sta logPtr,x

    // The colour is indexed by ENTRY, not by slot: the same trajectory always
    // arrives in the same colour, which is what makes a wrong one obvious.
    tya
    lsr
    lsr
    tay
    lda enemyColours,y
    sta logCol,x

    lda #ENEMY_MAX_HP                   // type data, not per-object storage:
    sta objHP,x                         // every enemy of this type starts here
    lda #TYPE_ENEMY
    sta objType,x

    // EVERY FIELD IS NOW SET, so the object may join the active set. Not one
    // instruction earlier: this is the old game's rule at 4922, and here it is
    // load-bearing because logActive is exactly what the sorter reads.
    jsr objectActivate

    inc enySpawnNext
    lda enySpawnNext
    cmp #ENEMY_SPAWN_ENTRIES
    bcc !wrapped+
    lda #0
    sta enySpawnNext
!wrapped:

    inc enySpawned                      // 16-bit, saturating at $ffff
    bne !counted+
    inc enySpawned + 1
    bne !counted+
    lda #$ff
    sta enySpawned
    sta enySpawned + 1
!counted:
    clc
    rts

// ---------------------------------------------------------------------------
// enemyTick — one frame of ONE enemy. MAIN THREAD.
// Entry/exit: X = the object's slot, PRESERVED across the free.
// ---------------------------------------------------------------------------
enemyTick:
    // ---- dying enemies run their death out and do not move ----------------
    // "A dying enemy remains renderable but no longer follows its path"
    // -- shooter_test/src/main.asm:2331. Kept: an explosion that keeps flying
    // reads as a live enemy the player cannot kill.
    lda objHP,x
    bne !alive+
    jmp enemyDeathTick
!alive:

    // ---- the hit flash, if one is running ---------------------------------
    lda objTimer,x
    beq !noFlash+
    jsr enemyFlashTick
!noFlash:

    // ---- vertical: whole pixels, as the old game ---------------------------
    lda logY,x
    clc
    adc objVY,x
    sta logY,x

    // THE SINGLE DESPAWN RULE. Past the bottom of the renderable band, the
    // enemy is gone. Nothing else in this file frees a slot.
    //
    // The test is unsigned and the band ends well below 255, so a descending
    // enemy always reaches it: the assembly-time check on the spawn table
    // guarantees vy is positive, which is what makes that a proof rather than
    // an expectation.
    cmp #ENEMY_DESPAWN_Y + 1
    bcc !alive+
    jmp enemyDespawn
!alive:

    // ---- horizontal: nine bits, signed velocity ---------------------------
    lda objVX,x
    beq !done+                          // the common case: a straight dive
    bmi !left+

    clc                                 // moving right
    adc logX,x
    sta logX,x
    bcc !done+
    inc logXHi,x                        // crossed 255 -> 256 going right
    rts

!left:
    clc                                 // moving left: A is negative, so the
    adc logX,x                          // sign extension is $ff in the high
    sta logX,x                          // byte and a CLEAR carry is the borrow
    bcs !done+
    dec logXHi,x                        // crossed 256 -> 255 going left
!done:
    rts

// ---------------------------------------------------------------------------
// enemyFlashTick — one frame of the hit flash. Entry/exit: X = slot, preserved.
//
// The colour ladder is the old updateEnemyHitEffects (2770-2790) exactly: the
// timer is decremented FIRST and the remaining value chooses the colour, so a
// four-frame flash shows white, white, white, yellow and then restores.
// ---------------------------------------------------------------------------
enemyFlashTick:
    dec objTimer,x
    lda objTimer,x
    cmp #2
    bcs !white+
    cmp #1
    beq !yellow+
    jsr enemyBaseColour                 // expired: back to the spawn colour
    rts
!white:
    lda #HIT_COL_WHITE
    sta logCol,x
    rts
!yellow:
    lda #HIT_COL_YELLOW
    sta logCol,x
    rts

// ---------------------------------------------------------------------------
// enemyDeathTick — one frame of dying. Entry/exit: X = slot, preserved.
//
// Reached only with objHP zero. The timer runs DEATH_TIME frames and the slot
// is freed on the frame it reaches zero -- which is the single place in the
// game an enemy is released, so publication safety has one path to reason
// about rather than two.
//
// The old game swapped in three explosion bitmaps here. This slice keeps the
// TIMING and the COLOUR PROGRESSION and leaves the art alone: migrating
// playerExplosion1/2/3 is a graphics job, and the graphics slice is next. The
// enemy therefore dies as a bounded yellow-orange-red flash of its own shape.
// ---------------------------------------------------------------------------
enemyDeathTick:
    dec objTimer,x
    beq !release+

    lda objTimer,x                      // the old frame thresholds, 2733-2757
    cmp #8
    bcs !blast1+
    cmp #4
    bcs !blast2+
    lda #DEATH_COL_3
    sta logCol,x
    rts
!blast2:
    lda #DEATH_COL_2
    sta logCol,x
    rts
!blast1:
    lda #DEATH_COL_1
    sta logCol,x
    rts

!release:
    // The death animation is over. This is a NORMAL despawn: the same call, the
    // same membership update, the same guarantee that CURRENT is not touched.
    jmp enemyDespawn

// ---------------------------------------------------------------------------
// enemyBaseColour — the spawn colour for the slot's trajectory.
// Entry/exit: X = slot, preserved.
//
// The old game stored OBJECT_BASE_COLOUR per object so an impact flash could be
// undone. Here the colour is a property of the spawn ENTRY, and the entry that
// produced this enemy is recoverable from its velocity pair, so the base colour
// is looked up rather than stored. One byte of table beats sixteen of state.
// ---------------------------------------------------------------------------
enemyBaseColour:
    ldy #ENEMY_SPAWN_ENTRIES - 1
!find:
    lda objVX,x
    cmp enemySpawnTable + 2,y
    bne !nextEntry+
    lda logXHi,x
    cmp enemySpawnTable + 1,y
    beq !found+
!nextEntry:
    dey
    dey
    dey
    dey
    bpl !find-
    ldy #0                              // no match: the first entry's colour is
!found:                                 // a defined answer rather than a stale
    tya                                 // one
    lsr
    lsr
    tay
    lda enemyColours,y
    sta logCol,x
    rts

// ---------------------------------------------------------------------------
// enemyDespawn — this enemy's life ends. Entry/exit: X = slot, preserved.
//
// There is nothing to undo in the renderer. The sprite this object was drawn
// through is not "turned off": the next schedule the builder produces simply
// does not contain it, and $d015 is composed from that schedule rather than
// edited. That is the whole point of the boundary.
// ---------------------------------------------------------------------------
enemyDespawn:
    jsr objectFree

    inc enyDespawned                    // 16-bit, saturating at $ffff
    bne !counted+
    inc enyDespawned + 1
    bne !counted+
    lda #$ff
    sta enyDespawned
    sta enyDespawned + 1
!counted:
    rts

.if (* > $4c00) { .error "the enemy code has outgrown its $4900 segment" }
