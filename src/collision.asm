// ===========================================================================
// collision.asm — the player's hitscan, resolved entirely in logical space
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is read or written from this file.
//
//     weaponTick      emits the shot event: two ray origins and a Y
//     objectUpdateAll every object takes its frame's movement
//     collisionTick   <- here: the rays meet the objects
//     enemyTick       next frame, turns the damage into feedback and death
//
// ---------------------------------------------------------------------------
// THE RULE THAT SHAPES THIS WHOLE FILE
// ---------------------------------------------------------------------------
// NOTHING HERE MAY DEPEND ON HARDWARE SPRITE IDENTITY, and $d01e is not read.
//
// The gameplay mux deliberately time-shares HW2..HW7: the same physical sprite
// draws different logical objects on different rasters of the same frame, and
// a given object can occupy a different slot every frame. A VIC collision bit
// therefore names a SLOT, and a slot is not an object. Asking $d01e "which
// enemy did the player hit" has no correct answer in this engine.
//
// The old game did read $d01e -- capturePlayerCollision at
// shooter_test/src/main.asm:4468 calls it "the cheap hardware broad phase" --
// but ONLY for the player's own body hitting an enemy, which is a later slice.
// Its PLAYER WEAPON was already pure logical hitscan, and that is what this
// file migrates.
//
// ---------------------------------------------------------------------------
// WHAT THE OLD GAME ACTUALLY DID
// ---------------------------------------------------------------------------
// Read out of shooter_test/src/main.asm before this file was written:
// updatePlayerFire (2418), tracePlayerCannon (2480), damageEnemy (2550),
// updateEnemyHitEffects (2714) and the constants at 995-997 and 561.
//
//   BOTH CANNONS TRACE, INDEPENDENTLY, IN THE SAME FRAME. updatePlayerFire
//   builds the left cannon's 9-bit X, traces, damages; then does the same for
//   the right. The old comment is explicit: "one target per cannon". A volley
//   can therefore deal nothing, one hit, or two -- and both hits can land on
//   the SAME enemy when it straddles both lanes, which is how a centred enemy
//   takes two HP from one volley.
//
//   THE RAY IS VERTICAL AND UPWARD, AND IT IS A HITSCAN. No projectile object
//   is ever allocated. The scan walks the logical object list and returns an
//   index.
//
//   THE X TEST IS THE FULL SPRITE WIDTH. tracePlayerCannon computes
//   rayX - enemyX as a 9-bit subtraction, rejects a non-zero high byte, and
//   accepts a low byte below 24: "Valid horizontal intersection is
//   enemyX .. enemyX+23." The hitbox is NOT narrower than the graphic.
//
//   THE Y TEST HAS TWO HALVES. The enemy must be at or below
//   GAMEPLAY_SPRITE_MIN_Y (55) -- "Off-screen ingress is not a hittable
//   target" -- and STRICTLY ABOVE the player: `cmp OBJECT_Y / bcs !next`.
//
//   NEAREST WINS, AND NEAREST MEANS GREATEST Y. The player is below and fires
//   upward, so the eligible enemy with the largest Y is the closest one.
//
//   THE TIE IS RESOLVED BY SLOT ORDER, AND IT IS DELIBERATE-LOOKING. The test
//   is `cmp HITSCAN_TARGET_Y / bcc !next`, which keeps scanning on a strictly
//   smaller Y and REPLACES the incumbent on an equal one. Scanning runs from
//   low slot to high, so among enemies at the same Y the HIGHEST slot index
//   wins. That is reproduced exactly rather than improved on: it is stable,
//   it is what the old game shipped, and a test pins it.
//
//   DAMAGE IS ONE HP PER CANNON HIT, health starts at ENEMY_START_HEALTH = 6,
//   and damageEnemy refuses to act on an already-zero health: "Already
//   dead/dying: never underflow health."
//
// MIGRATED LATER, IN THE TURRET COMBAT SLICE:
//   * traceTurretCannon, as traceTurretRay in src/turrets.asm. The old trace
//     extended this same nearest-Y selection over the world's turrets, and
//     that is what the call at the end of traceRay now does. The enemy scan
//     above is untouched by it.
//   * updateEnemyHealthSprite. The old game gave each damaged enemy a PRIVATE
//     64-byte sprite copy with a health bar burned into its bottom two rows,
//     built by self-modifying code. That is a rendering feature, it costs a
//     bitmap per live enemy, and it belongs with the graphics slice if at all.
//   * awardKillScore. Score is deliberately decoupled here -- see the kill
//     event below.
// ===========================================================================

// --- the numbers, from shooter_test/src/main.asm ---------------------------
.const HITBOX_W        = 24         // tracePlayerCannon:2515, "enemyX .. enemyX+23"
.const HITBOX_X_OFF    = 0          // the old test is relative to OBJECT_X itself
.const SHOT_DAMAGE     = 1          // damageEnemy:2551, one dec per cannon hit
.const HIT_FLASH_TIME  = 4          // ENEMY_HIT_FLASH_TIME, main.asm:996
.const DEATH_TIME      = 12         // ENEMY_DEATH_TIME, main.asm:997

// Hit-flash colours, from updateEnemyHitEffects:2783-2790.
.const HIT_COL_WHITE   = 1
.const HIT_COL_YELLOW  = 7
// Death colours, from the three explosion frames at 2736-2757.
.const DEATH_COL_1     = 7          // yellow initial blast
.const DEATH_COL_2     = 8          // orange middle blast
.const DEATH_COL_3     = 2          // red final breakup

// WHAT KIND OF THING A RAY HIT. The pool is not the only thing a ray can
// intersect any more: src/turrets.asm's authored background turrets are
// hittable too, and they are NOT objects -- no pool slot, no logical sprite,
// no type field. So the winner of a ray is a pair, an index and a kind, and
// applyDamage dispatches on the kind. The old game packed the same decision
// into bit 7 of HITSCAN_TARGET; a separate byte keeps csTarget usable as an
// index without a mask on every read.
.const CS_KIND_ENEMY   = 0
.const CS_KIND_TURRET  = 1

// The lowest hittable line. The old game used GAMEPLAY_SPRITE_MIN_Y, which is
// 55 for RSEL=0 -- the same number this engine calls MIN_SPRITE_Y. Sharing it
// is a DECISION and gets a check rather than an alias, as in src/player.asm.
.const HITSCAN_MIN_Y   = 55
.if (HITSCAN_MIN_Y != MIN_SPRITE_Y) {
    .error "the hitscan's lowest hittable line no longer matches the renderer's Y band"
}
.if (HITBOX_W > 32) { .error "a hitbox wider than 32 breaks the single-byte delta test" }

// ===========================================================================
// State. MAIN THREAD ONLY.
// ===========================================================================
* = $c5f3 "collision state"

// --- the scan's working set ------------------------------------------------
csRayLo:     .byte 0                // the ray being traced, nine bits
csRayHi:     .byte 0
csTarget:    .byte 0                // slot of the best candidate, or $ff
csTargetY:   .byte 0                // its Y; greatest Y wins
csTargetKind: .byte 0               // CS_KIND_ENEMY or CS_KIND_TURRET. Which
                                    // pool csTarget indexes, and nothing else.
csTmp:       .byte 0                // the nine-bit delta's low byte

// --- the kill event, which is ALL the score coupling there is --------------
// Score is not migrated in this slice. What a future score system needs is the
// fact and the type, so that is what is published: a count of kills resolved
// THIS frame, cleared at the top of every collisionTick exactly as the shot
// event is, plus the type of the last one. Nothing consumes it yet.
csKills:     .byte 0                // kills resolved this frame
csKillType:  .byte 0                // type of the most recent kill

// --- diagnostics -----------------------------------------------------------
csHitsLo:    .byte 0                // total rays that connected, 16-bit
csHitsHi:    .byte 0
csKillsLo:   .byte 0                // total enemies killed, 16-bit
csKillsHi:   .byte 0

collisionStateEnd:
.if (collisionStateEnd > $c600) { .error "the collision state has grown into the P3 fixture data at $c600" }

// ===========================================================================
// Code. MAIN THREAD ONLY, outside VIC bank 0.
// ===========================================================================
* = $4c00 "collision"

collisionInit:
    lda #0
    ldx #collisionStateEnd - csRayLo - 1
!clear:
    sta csRayLo,x
    dex
    bpl !clear-
    rts

// ---------------------------------------------------------------------------
// collisionTick — resolve this frame's shot event. MAIN THREAD.
//
// THE TEMPORAL MODEL, STATED ONCE AND RELIED ON EVERYWHERE:
//
//   Everything this routine reads is END-OF-FRAME state for the SAME frame.
//   playerTick has moved the ship, weaponTick has built the ray origins from
//   that new position, and objectUpdateAll has moved every enemy. So a ray and
//   its targets are never one frame apart, in either direction.
//
//   The visible consequence is worth naming: an enemy that left the world on
//   this frame was already freed by objectUpdateAll, so a shot fired on that
//   frame misses it. That is a definite answer rather than a race, and it is
//   the case the suite calls "enemy despawns the same frame as the shot".
// ---------------------------------------------------------------------------
collisionTick:
    lda #0
    sta csKills                         // the kill event is true for one frame

    lda shotFired                       // Slice B's contract: true for exactly
    bne !shot+                          // the frame a volley resolved
    rts
!shot:

    ldx #0                              // X = ray index, 0..shotRays-1
!rayLoop:
    cpx shotRays
    bcc !trace+
    rts
!trace:
    lda shotXLo,x
    sta csRayLo
    lda shotXHi,x
    sta csRayHi
    txa
    pha                                 // traceRay walks X over the pool
    jsr traceRay
    bcs !miss+
    jsr applyDamage                     // X = the chosen target
!miss:
    pla
    tax
    inx
    jmp !rayLoop-

// ---------------------------------------------------------------------------
// traceRay — the nearest eligible enemy the ray at csRay intersects.
//
// Returns: carry clear and X = the target's slot; carry set on a miss.
//
// O(MAX_OBJECTS) with no early exit, which for a sixteen-slot pool is a few
// hundred cycles and is measured rather than assumed. A spatial structure over
// sixteen objects would cost more to maintain than it could ever save.
// ---------------------------------------------------------------------------
traceRay:
    lda #$ff
    sta csTarget                        // $ff = nothing has intersected yet
    lda #0
    sta csTargetY                       // greatest qualifying Y wins
    sta csTargetKind                    // CS_KIND_ENEMY is 0, so the enemy scan
                                        // below never has to set it; only a
                                        // turret that WINS changes it

    ldx #0
!scan:
    // ---- is this slot a damageable enemy? --------------------------------
    // TYPE, not "any active object". The pool will later hold pickups and
    // enemy bullets, and a filter that means "everything alive" would silently
    // start shooting them down.
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !next+
    lda objHP,x
    beq !next+                          // already dying: not a target again.
                                        // The old damageEnemy refused the same
                                        // case one level later; refusing it
                                        // here also stops a dying enemy
                                        // shadowing a live one behind it

    // ---- Y eligibility, both halves --------------------------------------
    lda logY,x
    cmp #HITSCAN_MIN_Y
    bcc !next+                          // above the band: still arriving
    cmp shotY
    bcs !next+                          // at or below the ship: the ray is
                                        // fired UPWARD, so this is behind it

    // ---- X: the nine-bit delta against the hitbox ------------------------
    lda csRayLo
    sec
    sbc logX,x
    sta csTmp
    lda csRayHi
    sbc logXHi,x
    bne !next+                          // negative, or 256 or more: neither can
                                        // lie inside a 24-pixel box
    lda csTmp
    cmp #HITBOX_W
    bcs !next+                          // hit iff enemyX <= rayX <= enemyX+23

    // ---- nearest wins, and a tie goes to the higher slot -----------------
    lda logY,x
    cmp csTargetY
    bcc !next+                          // strictly farther: keep the incumbent.
    sta csTargetY                       // EQUAL replaces, so the highest slot
    stx csTarget                        // index wins a tie -- the old game's
                                        // behaviour, reproduced deliberately
!next:
    inx
    cpx #MAX_OBJECTS
    bne !scan-

    // ---- and now the world's own targets ---------------------------------
    // THE ORDER IS THE OLD GAME'S AND IT DECIDES THE TIE. tracePlayerCannon
    // scanned every enemy and then called traceTurretCannon to EXTEND the same
    // nearest-Y result rather than run a second competition. A turret must beat
    // the incumbent STRICTLY, where an enemy replaces an equal one -- so:
    //
    //     one winner per ray, nearest (greatest Y) wins, ENEMY WINS A TIE.
    //
    // Running the turrets second is therefore not an implementation detail; it
    // is the tie-break. It also makes the effect on Slice D exactly nothing
    // when no turret is in the ray's path: this call either rejects every
    // turret and returns, or replaces an incumbent it strictly beat.
    //
    // src/turrets.asm owns the turret half -- its geometry, its sixteen-pixel
    // hitbox and its visibility gate are turret facts -- and works on the three
    // scan variables above. This file keeps the RULE and the dispatch.
    jsr traceTurretRay

    ldx csTarget
    cpx #$ff
    beq !miss+
    clc
    rts
!miss:
    sec
    rts

// ---------------------------------------------------------------------------
// applyDamage — one cannon's worth of damage to the enemy in slot X.
// Entry/exit: X = slot, preserved.
//
// This does not free anything and does not touch presentation beyond the
// logical colour. Death is a STATE the object enters; enemyTick runs it out
// and performs the free, so there is exactly one place a slot is released.
// ---------------------------------------------------------------------------
applyDamage:
    lda csTargetKind
    beq !enemy+
    jmp turretDamage                    // X = the turret. src/turrets.asm owns
                                        // its health, its flash and its
                                        // destruction, exactly as this file
                                        // owns the enemy's.
!enemy:
    lda objHP,x
    beq !done+                          // "Already dead/dying: never underflow
                                        // health" -- damageEnemy:2551
    sec
    sbc #SHOT_DAMAGE
    sta objHP,x
    beq !death+

    // ---- a survivable hit: start the flash -------------------------------
    lda #HIT_FLASH_TIME
    sta objTimer,x
    lda #HIT_COL_WHITE
    sta logCol,x                        // LOGICAL colour. The renderer copies
                                        // it into the schedule and the executor
                                        // writes $d027-$d02e; gameplay never
                                        // names a colour register
    jmp !counted+

!death:
    // HP is now zero, which IS the dying state. The timer changes meaning with
    // it, so it is reloaded here rather than left holding a stale flash.
    lda #DEATH_TIME
    sta objTimer,x
    lda #DEATH_COL_1
    sta logCol,x

    inc csKills                         // the logical kill event
    lda objType,x
    sta csKillType
    inc csKillsLo
    bne !counted+
    inc csKillsHi

!counted:
    inc csHitsLo
    bne !done+
    inc csHitsHi
!done:
    rts

.if (* > $4e00) { .error "the collision code has outgrown its $4c00 segment" }
