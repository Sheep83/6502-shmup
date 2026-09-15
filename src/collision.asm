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
// The gameplay mux time-shares HW2..HW7: the same physical sprite draws
// different logical objects on different rasters of one frame, and an object
// can occupy a different slot every frame. A VIC collision bit therefore names
// a SLOT, and a slot is not an object -- so asking $d01e "which enemy did the
// player hit" has no correct answer in this engine. Every decision below is
// made in logical space instead.
//
// THE SELECTION RULES, which tests pin and which content depends on:
//   * BOTH CANNONS TRACE INDEPENDENTLY in the same frame -- one target per
//     cannon. A volley deals nothing, one hit or two, and both can land on the
//     SAME enemy when it straddles both lanes.
//   * THE RAY IS A VERTICAL UPWARD HITSCAN. No projectile object is allocated.
//   * THE HITBOX IS THE FULL SPRITE WIDTH, 24 pixels, not a narrower core.
//   * ELIGIBILITY IS TWO-HALVED: the enemy must be at or below HITSCAN_MIN_Y,
//     so one still arriving from off-screen cannot be shot, and strictly above
//     the ship, since the ray travels upward.
//   * NEAREST WINS AND NEAREST MEANS GREATEST Y, the player firing from below.
//   * A TIE GOES TO THE HIGHER SLOT among enemies, and to the ENEMY between an
//     enemy and a turret. See traceRay for how the second falls out of order.
// ===========================================================================

.const HITBOX_W        = 24         // hit iff enemyX <= rayX <= enemyX+23
.const HITBOX_X_OFF    = 0          // the box starts at logX itself
.const SHOT_DAMAGE     = 1          // per cannon hit; enemies start at 6 HP
.const HIT_FLASH_TIME  = 4          // frames of flash on a survivable hit
.const DEATH_TIME      = 12         // frames of explosion before the slot frees

// ---------------------------------------------------------------------------
// THE HIT FLASH, AND WHY IT IS PURPLE
// ---------------------------------------------------------------------------
// The flash writes logCol, which is the enemy's $d027 -- multicolour PAIR 10,
// the body. It is the only one of the enemy's three colours that is per-sprite;
// pair 01 and pair 11 are the shared SPR_MC_DARK/SPR_MC_LIGHT and belong to
// every sprite on screen at once, so a flash CANNOT touch them. Whatever is
// chosen here has to read as an impact while the dark-grey shading and the
// white highlights stay exactly where they were.
//
// It used to be WHITE, which worked only while the enemy was hires: one colour
// for the whole sprite meant white turned the entire thing white. In
// multicolour that same write recolours the body to a white the highlights are
// ALREADY drawn in, so the two merge, the shape loses its internal definition,
// and the flash reads as the enemy smearing rather than being hit.
//
// So the colour was chosen by elimination against everything else on screen:
//
//     dark grey, white    pinned as the shared pair -- unavailable
//     cyan, yellow,       the four authored wave colours: an enemy would
//     light red,          flash to the colour it already is, which for that
//     light green         wave is no flash at all
//     yellow, orange, red the death ramp below -- a survivable hit must never
//                         look like the start of an explosion
//     grey, light grey,   the terrain's own three colours: the enemy would
//     dark grey           flash INTO the background (and it is the shared
//                         shading besides)
//     light blue          the player's hull
//     black, blue, brown  too dark or too muddy to read as a flash at all
//
// That leaves purple and green, and green is one step from the light-green
// wave -- those enemies would barely register a hit. PURPLE is the only hue
// that appears nowhere else in the game, which is exactly what a damage signal
// wants: nothing on screen can be mistaken for it, whatever the enemy's own
// colour happens to be.
.const HIT_COL_FLASH   = 4          // purple: see above

// The death ramp, walked by enemyDeathTick. Warm and descending -- a hot
// initial blast cooling through orange to a red breakup -- which is what keeps
// it distinguishable from the single cold flash above.
.const DEATH_COL_1     = 7          // yellow initial blast
.const DEATH_COL_2     = 8          // orange middle blast
.const DEATH_COL_3     = 2          // red final breakup

// WHAT KIND OF THING A RAY HIT. The pool is not the only hittable thing:
// src/turrets.asm's authored background turrets are hittable too and are NOT
// objects -- no pool slot, no logical sprite, no type field. So a ray's winner
// is a pair, an index and a kind, and applyDamage dispatches on the kind. Kind
// is a separate byte rather than a flag bit in csTarget so that csTarget stays
// usable as an index without masking on every read.
.const CS_KIND_ENEMY   = 0
.const CS_KIND_TURRET  = 1

// The lowest hittable line. It equals MIN_SPRITE_Y, but sharing the number is a
// DECISION about gameplay reach rather than a dependency on the renderer's Y
// band, so it is checked rather than aliased -- as in src/player.asm.
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

// --- the kill event --------------------------------------------------------
// The only coupling between combat and any future score system: the fact and
// the type, published for one frame and cleared at the top of every
// collisionTick exactly as the shot event is. Nothing consumes it yet.
csKills:     .byte 0                // kills resolved this frame
csKillType:  .byte 0                // type of the most recent kill

// --- diagnostics -----------------------------------------------------------
csHitsLo:    .byte 0                // total rays that connected, 16-bit
csHitsHi:    .byte 0
csKillsLo:   .byte 0                // total enemies killed, 16-bit
csKillsHi:   .byte 0

collisionStateEnd:
.if (collisionStateEnd > $c600) { .error "the collision state has grown past its $c600 ceiling" }

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
//   frame misses it. A definite answer, not a race.
// ---------------------------------------------------------------------------
collisionTick:
    lda #0
    sta csKills                         // the kill event is true for one frame

    lda shotFired                       // set by weaponTick for exactly the one
    bne !shot+                          // frame a volley resolved
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
// Entry: csRayLo/csRayHi = the ray's nine-bit X, shotY = the ship's line.
// Exit:  carry clear and X = the target's index, csTargetKind saying which
//        pool it indexes; carry set on a miss.
//
// O(MAX_OBJECTS) with no early exit -- a few hundred cycles over sixteen slots.
// A spatial structure over sixteen objects would cost more to maintain than it
// could save.
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
    // TYPE, not "any active object". The pool also holds hostile projectiles,
    // and a filter meaning "everything alive" would let the player shoot them
    // down.
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !next+
    lda objHP,x
    beq !next+                          // already dying: not a target again.
                                        // Refusing it HERE rather than in
                                        // applyDamage also stops a dying enemy
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
    sta csTargetY                       // EQUAL replaces, and the scan runs low
    stx csTarget                        // slot to high, so the highest slot
                                        // index wins a tie
!next:
    inx
    cpx #MAX_OBJECTS
    bne !scan-

    // ---- and now the world's own targets ---------------------------------
    // THE ORDER IS THE TIE-BREAK, not an implementation detail. Turrets EXTEND
    // the same nearest-Y competition rather than run a second one, and a turret
    // must beat the incumbent STRICTLY where an enemy replaces an equal one.
    // So: one winner per ray, greatest Y wins, ENEMY WINS A TIE. With no turret
    // in the ray's path this call either rejects every turret and returns, or
    // replaces an incumbent it strictly beat -- it can never weaken the result.
    //
    // src/turrets.asm owns the turret half (its geometry, its sixteen-pixel
    // hitbox, its visibility gate) and works on the three scan variables above.
    // This file keeps the rule and the dispatch.
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
// applyDamage — one cannon's worth of damage to the target traceRay chose.
// Entry/exit: X = the target's index, preserved; csTargetKind selects the pool.
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
    beq !done+                          // already dying: never underflow health
    sec
    sbc #SHOT_DAMAGE
    sta objHP,x
    beq !death+

    // ---- a survivable hit: start the flash -------------------------------
    lda #HIT_FLASH_TIME
    sta objTimer,x
    lda #HIT_COL_FLASH
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
