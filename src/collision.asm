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

// THE TWIN-RAY SCAN RESOLVES EXACTLY TWO RAYS IN ONE POOL WALK, so the weapon
// had better still fire two. This is a build error rather than a runtime
// branch: a third ray is a weapon-design change, and whoever makes it should be
// told here, by name, instead of discovering that the third ray never hits
// anything. See collideTwinRays.
.if (WPN_RAYS != 2) {
    .error "collision.asm resolves exactly two hitscan rays in one pass; WPN_RAYS is no longer 2 -- see collideTwinRays"
}

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
// ===========================================================================
// THE PLAYER'S BODY BOX — ramming an enemy
// ===========================================================================
// SOFTWARE COLLISION IN LOGICAL COORDINATES, and $d01e is not read here or
// anywhere else in this engine. The mux time-shares HW2..HW7, so a VIC
// collision bit names a hardware SLOT and a slot is not an object: it would
// answer "something touched the player" without ever saying what, and for part
// of every frame it would be answering about the HUD.
//
// A SLIGHTLY FORGIVING PLAYER BOX. Both sprites are 24x21, but ramming is
// judged on a box INSET inside the craft rather than on its full cell: at full
// size the player collects a hit from an enemy whose transparent corner merely
// passed over a wingtip, which reads as being killed by nothing. The inset is
// stated as a rectangle inside the ship and the four compare bounds are
// DERIVED from it, so tuning is these four numbers and nothing else.
//
//     enemy box    the full 24x21 cell, at logX/logY
//     player box   PLAYER_BODY_W x PLAYER_BODY_H, inset by
//                  PLAYER_BODY_INSET_X/Y inside the craft's own cell
//
// There is deliberately ONE enemy box for every species. The Ring, the
// Dropper and the protectors are all the same 24x21 cell and none of the
// current data carries a cheaper per-species extent, so a per-species hitbox
// table would be a framework holding one repeated number.
.const PLAYER_BODY_INSET_X = 6      // pixels in from each side of the craft
.const PLAYER_BODY_INSET_Y = 5      // ...and down from its top
.const PLAYER_BODY_W       = 12     // so the box is 12 of the ship's 24 wide
.const PLAYER_BODY_H       = 12     // ...and 12 of its 21 tall

// The four bounds the overlap test actually uses, as (enemyX - plyX) and
// (enemyY - plyY) windows. Derived, never typed twice.
.const BODY_HIT_LEFT  = HITBOX_W - PLAYER_BODY_INSET_X          // 18
.const BODY_HIT_RIGHT = PLAYER_BODY_INSET_X + PLAYER_BODY_W     // 18
.const BODY_HIT_UP    = SPRITE_HEIGHT - PLAYER_BODY_INSET_Y     // 16
.const BODY_HIT_DOWN  = PLAYER_BODY_INSET_Y + PLAYER_BODY_H     // 17

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
// MOVED FROM $c5f3, WHERE IT NO LONGER FITS. That run is thirteen bytes between
// the object pool below and the SFX state above, and the twin-ray scan needs two
// more for the second ray's candidate. $c616 is the free run above the vic bank
// state and below the game state -- 234 bytes, where this block's fourteen are
// comfortable. Nothing reads these by address; every consumer uses the symbol.
* = $c616 "collision state"

// --- the scan's working set ------------------------------------------------
csRayLo:     .byte 0                // the ray being traced, nine bits
csRayHi:     .byte 0
csTarget:    .byte 0                // slot of the best candidate, or $ff
csTargetY:   .byte 0                // its Y; greatest Y wins
csTargetKind: .byte 0               // CS_KIND_ENEMY or CS_KIND_TURRET. Which
                                    // pool csTarget indexes, and nothing else.
csTmp:       .byte 0                // the nine-bit delta's low byte

// --- the SECOND ray's candidate, for the one-pass twin-ray scan ------------
// The weapon fires two rays and the pool walk is the expensive part of
// resolving them, so traceBothRays walks it ONCE and keeps a candidate for each
// ray. The FIRST ray uses csTarget/csTargetY above, which is also what
// traceTurretRay and applyDamage already read, so the resolution half of the
// routine did not have to change at all.
//
// NO csRay2Lo/Hi. The two ray coordinates are already in the shot event that
// src/weapon.asm publishes, so traceBothRays reads shotXLo/shotXHi directly;
// copying them into locals first cost four stores and two bytes of state to
// reach the same absolute addressing mode.
//
// NO csTarget2Kind. Turrets are resolved per ray by traceTurretRay AFTER the
// pool walk, against whichever candidate that ray ended up with, so the kind
// only ever has to exist for the ray being resolved right now.
csTarget2:   .byte 0                // the second ray's best enemy, or $ff
csTarget2Y:  .byte 0

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
.if (collisionStateEnd > $c700) { .error "the collision state has grown past its $c700 ceiling" }

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

    // A VOLLEY IS EXACTLY TWO RAYS, and that is asserted at the top of this
    // file rather than branched on here. The general "loop over shotRays"
    // version this replaced was a runtime fallback for a case the weapon
    // cannot produce -- dead code carrying its own risk of silently doing the
    // wrong thing. A build error is a better guard than an untested path.
    // falls through to collideTwinRays

// ---------------------------------------------------------------------------
// collideTwinRays — the two-ray volley, one pool walk.
//
// THE SEQUENTIAL RULE IS THE WHOLE DIFFICULTY, and it is preserved exactly.
// The old code ran `traceRay` then `applyDamage` per ray, so the LEFT ray's
// damage was already in objHP when the RIGHT ray scanned. That is observable:
// a one-HP enemy standing in both rays dies to the left ray, and the right ray
// then takes whatever was BEHIND it rather than hitting the corpse twice.
// tests/test_hitscan_twin_ray.py pins that case.
//
// A single pass collects both candidates BEFORE any damage, so it cannot see
// that by itself. The resolution: ray 0's damage can only ever make ray 1's
// candidate INELIGIBLE -- it cannot move an enemy, change a Y, or make a new
// one eligible -- so the only divergence is "ray 1's candidate just died". That
// is detected in three instructions and handled by running the ORIGINAL
// single-ray scan for ray 1, which by construction then produces exactly what
// the old code produced.
//
// So the fast path is the common case and the rare case falls back to the slow
// path that was always correct. Nothing approximates anything.
// ---------------------------------------------------------------------------
collideTwinRays:
    jsr traceBothRays                   // one walk; both candidates

    // ---- ray 0 ------------------------------------------------------------
    // csTarget/csTargetY are already ray 0's. traceTurretRay works on
    // csRayLo/Hi, so the ray coordinate is published for it here.
    lda shotXLo + 0
    sta csRayLo
    lda shotXHi + 0
    sta csRayHi
    lda #CS_KIND_ENEMY
    sta csTargetKind
    jsr traceTurretRay                  // turrets extend the same competition
    jsr csResolve                       // damage it, or let the ray reach the boss

    // ---- ray 1 ------------------------------------------------------------
    lda shotXLo + 1
    sta csRayLo
    lda shotXHi + 1
    sta csRayHi

    // DID RAY 0 KILL WHAT RAY 1 WANTED? That is the only way one pass can
    // differ from two, because ray 0's damage cannot move an enemy, change a Y
    // or make a new one eligible -- it can only take ray 1's candidate away.
    lda csTarget2
    cmp #$ff
    beq !fast+                          // ray 1 found nothing: nothing to spoil
    tax
    lda objHP,x
    bne !fast+                          // still alive: the candidate stands

    // THE RARE PATH, and it is the OLD path. Ray 1 must re-choose from what is
    // left, which is exactly what the original per-ray scan does -- so run it
    // rather than approximate it. Reached only when a volley kills an enemy
    // standing in both lanes.
    jsr traceRay                        // turrets included; leaves csTarget
    jmp csResolve

!fast:
    lda csTarget2
    sta csTarget
    lda csTarget2Y
    sta csTargetY
    lda #CS_KIND_ENEMY
    sta csTargetKind
    jsr traceTurretRay
    // falls through

// ---------------------------------------------------------------------------
// csResolve — spend one ray on whatever won it. Entry: csTarget/csTargetKind.
//
// ONE PLACE, because the three callers above differ only in how they chose the
// target, never in what spending it means: a winner takes damage, and a ray
// that found nothing ordinary in its path is allowed to reach the boss.
// ---------------------------------------------------------------------------
csResolve:
    ldx csTarget
    cpx #$ff
    beq !boss+
    jmp applyDamage                     // X = the chosen target; its rts is ours
!boss:
    // NOTHING ORDINARY WAS IN THE WAY, so the ray may reach the boss. One ray
    // reaches one target, which is why a ray crossing a seam between the
    // boss's four render cells cannot count twice: the cells are not targets,
    // and this is one test against one rectangle. See src/boss.asm.
    jmp bossRayHit

// ---------------------------------------------------------------------------
// playerBodyTick — the craft meets an enemy's body. MAIN THREAD, once a frame.
//
// WHAT COUNTS AS A BODY, and every one of these is read from the state the
// engine already keeps rather than from a flag invented for this:
//
//   logActive   the slot holds an object at all -- a freed or despawning slot
//               is inactive and fails here first
//   objType     TYPE_ENEMY. Hostile projectiles, collectible tokens and the
//               background turrets are other types and are never bodies
//   objHP       NON-ZERO. Zero is this engine's own "dying": it is what
//               enemyTick tests to run the death animation instead of the
//               flight path, so an enemy already exploding cannot also ram
//
// Protectors and the Dropper are ordinary TYPE_ENEMY objects and are therefore
// included by construction, exactly as the brief wants -- no special case
// names either of them.
//
// THE DAMAGE PATH IS THE EXISTING ONE. This routine decides GEOMETRY and
// nothing else; playerTakeHit owns what being hit means, which is why the
// invulnerability rule, the hurt SFX, the life and the explosion all behave
// identically whether the player was shot or rammed. Nothing here destroys the
// enemy: nothing in this game's semantics says a collision damages the thing
// collided with, and inventing that would be a balance change.
//
// ONE HIT PER FRAME. The scan returns as soon as it damages the player, like
// ebulletPlayerTick and for the same reason: the player is dead or
// invulnerable from that instant, so every later slot would be refused anyway.
// ---------------------------------------------------------------------------
playerBodyTick:
    lda plyDead                         // a corpse cannot be rammed
    bne !done+
    lda plyInvuln                       // ...and neither can a ship that is
    bne !done+                          // already immune

    ldx #0
!slot:
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !next+
    lda objHP,x
    beq !next+                          // dying: not a body any more

    // ---- vertical overlap -------------------------------------------------
    // enemyY - plyY must lie in -(BODY_HIT_UP-1) .. BODY_HIT_DOWN-1. Biasing
    // by the upper reach turns that into ONE unsigned compare.
    lda logY,x
    sec
    sbc plyY
    clc
    adc #BODY_HIT_UP - 1
    cmp #BODY_HIT_UP - 1 + BODY_HIT_DOWN
    bcs !next+

    // ---- horizontal overlap, nine bits ------------------------------------
    lda logX,x
    sec
    sbc plyX
    sta csTmp
    lda logXHi,x
    sbc plyXHi
    beq !enemyRight+
    cmp #$ff
    bne !next+                          // more than 255 pixels apart

    lda csTmp                           // the enemy is left of the craft
    clc
    adc #BODY_HIT_LEFT - 1
    bcc !next+
    jmp !ram+

!enemyRight:
    lda csTmp
    cmp #BODY_HIT_RIGHT
    bcs !next+

!ram:
    jmp playerTakeHit                   // src/player.asm owns the consequence;
                                        // its rts is ours

!next:
    inx
    cpx #MAX_OBJECTS
    bne !slot-
!done:
    rts

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
// ---------------------------------------------------------------------------
// traceBothRays — ONE walk of the object pool, a candidate for EACH ray.
// Entry: the shot event (shotXLo/shotXHi, shotY) as src/weapon.asm left it.
// Exit:  csTarget/csTargetY   = ray 0's best enemy (or $ff)
//        csTarget2/csTarget2Y = ray 1's best enemy (or $ff)
//        X and A clobbered. Turrets are NOT considered here.
//
// WHY THIS EXISTS. traceRay walks all sixteen slots, and resolving two rays ran
// it twice: every slot's logActive, objType, objHP and both halves of the Y
// test were paid for TWICE to answer a question about X that differs only in
// the ray coordinate. Measured at 56 cycles per occupied slot per ray; doing
// the eligibility once and only the X test twice costs about 89 for the pair
// instead of about 130, and an empty slot 13 instead of 26.
//
// WHAT IS IDENTICAL TO traceRay, deliberately and line for line: the type and
// liveness filter, both halves of the Y band, the nine-bit X delta against
// HITBOX_W, and `greatest Y wins, an EQUAL Y replaces` so a tie still goes to
// the highest slot index. The two rays keep entirely separate candidates, so
// neither can shadow the other.
//
// WHAT IS NOT DONE HERE: turrets, and damage. Both are the caller's, and that
// is what lets the sequential rule survive -- see collisionTick.
// ---------------------------------------------------------------------------
traceBothRays:
    lda #$ff
    sta csTarget
    sta csTarget2
    lda #0
    sta csTargetY
    sta csTarget2Y

    ldx #0
!scan:
    // ---- eligibility, ONCE for both rays ---------------------------------
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !next+
    lda objHP,x
    beq !next+                          // already dying: not a target again
    lda logY,x
    cmp #HITSCAN_MIN_Y
    bcc !next+                          // above the band: still arriving
    cmp shotY
    bcs !next+                          // at or below the ship: behind the ray

    // ---- ray 0's X -------------------------------------------------------
    lda shotXLo + 0
    sec
    sbc logX,x
    sta csTmp
    lda shotXHi + 0
    sbc logXHi,x
    bne !ray1+                          // negative, or 256+: cannot be inside
    lda csTmp
    cmp #HITBOX_W
    bcs !ray1+
    lda logY,x
    cmp csTargetY
    bcc !ray1+                          // strictly farther: keep the incumbent
    sta csTargetY
    stx csTarget

!ray1:
    // ---- ray 1's X, against the SAME object -------------------------------
    lda shotXLo + 1
    sec
    sbc logX,x
    sta csTmp
    lda shotXHi + 1
    sbc logXHi,x
    bne !next+
    lda csTmp
    cmp #HITBOX_W
    bcs !next+
    lda logY,x
    cmp csTarget2Y
    bcc !next+
    sta csTarget2Y
    stx csTarget2

!next:
    inx
    cpx #MAX_OBJECTS
    bne !scan-
    rts

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
    bne !soundIt+
    inc csKillsHi

    // ONCE PER DEATH, NOT ONCE PER DYING FRAME. This arm is reached only on
    // the transition to zero health -- the `beq !death+` above -- and the
    // `lda objHP,x / beq !done+` at the top refuses to re-enter it, so the
    // twelve frames of explosion that follow are silent. Requesting the sound
    // from enemyDeathTick instead, where the explosion visibly runs, would
    // restart it on every one of those frames.
!soundIt:
    lda #SFX_KILL
    jsr sfxRequest                      // src/sfx.asm; preserves X, which this
                                        // routine's own contract promises its
                                        // caller

!counted:
    inc csHitsLo
    bne !done+
    inc csHitsHi
!done:
    rts

.if (* > $4e00) { .error "the collision code has outgrown its $4c00 segment by " + toIntString(* - $4e00) + " bytes" }
