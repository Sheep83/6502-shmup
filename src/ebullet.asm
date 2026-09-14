// ===========================================================================
// ebullet.asm — hostile projectiles: the pool, the flight, and the player hit
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is read or written from this file,
// and $d01e is never consulted. A projectile is an ordinary logical object --
// it is allocated from src/objects.asm's pool, it writes logY/logX/logXHi/
// logPtr/logCol like everything else, and the sorter, the builder and the mux
// draw it without knowing it is hostile. There is no reserved hardware sprite
// and no projectile-shaped hole in the renderer.
//
//     turretFireTick   decides a turret shoots, and where from
//     ebulletSpawn     <- here: one projectile, if the cap allows
//     objectUpdateAll  -> ebulletTick: the flight and the despawn
//     ebulletPlayerTick<- here: the projectile meets the ship
//     playerTakeHit    the player decides what being hit means
//
// ---------------------------------------------------------------------------
// WHY THIS IS ITS OWN FILE
// ---------------------------------------------------------------------------
// Because it is not turret behaviour. The old game's turret fire and its enemy
// fire went through ONE spawn routine, one cap and one lifecycle -- "same cap,
// allocator, aim quantisation and projectile lifecycle", as the call site put
// it -- and enemy fire is a later slice. Keeping the projectile here means
// that slice adds a caller and nothing else.
//
// It is a pool and a lifecycle, not a framework. There is no component
// registry, no generic entity system and no dispatch table: three bullets, one
// type, four routines.
//
// ---------------------------------------------------------------------------
// WHAT CAME ACROSS, AND FROM WHERE
// ---------------------------------------------------------------------------
// Read out of ~/Desktop/c64Shooter-main.zip, src/main.asm:
// spawnEnemyBulletAt (2888), chooseEnemyBulletSlope (2975), moveEnemyBullet
// (3002), checkBulletPlayerOverlap, and the constants at 573-578.
//
//   MAX_ENEMY_BULLETS      3    a HARD GLOBAL cap, not per turret
//   ENEMY_BULLET_SPEED_Y   3    fixed, downward
//   ENEMY_BULLET_COLOUR    7    yellow
//   the aim                     X velocity quantised to -2..+2 from the
//                               horizontal distance to the player AT SPAWN;
//                               the trajectory is then immutable
//   the hitbox                  bulletX - playerX in -7..+23,
//                               bulletY - playerY in -7..+20
//
// DELIBERATELY NOT TAKEN: planCoarseBulletSuppression, the old renderer's
// machinery for dropping a projectile out of a batch that would obstruct a
// coarse copy. It is adaptive sprite scheduling of exactly the kind this
// engine replaced with the legality-window batch merge, and this projectile
// has no special standing with the renderer at all.
// ===========================================================================

// ---------------------------------------------------------------------------
// THE CAP, AND WHY IT IS STILL THREE
// ---------------------------------------------------------------------------
// The old game's number, kept, and it survives its own re-derivation here:
//
//   1. the old behaviour is three, globally, across every hostile source;
//   2. at most TWO turrets of level 1 are ever combat-visible at once (proved
//      by the model sweep in tests/test_turret_combat.py), and each reloads a
//      100-frame timer, so turrets alone cannot ask for more than two in
//      flight except while an earlier one is still falling;
//   3. the pool is MAX_OBJECTS = 16 and the schedule holds MAX_SCHED = 24, so
//      three is nowhere near either;
//   4. the frame budget is the real limit, and docs/ENGINE_CONTRACT.md §10
//      puts the practical ceiling at about eight well-separated sprites.
//      Three projectiles on top of a live enemy population is exactly the
//      pressure the firing gate below refuses to add.
//
// So three is not a number this slice invented and it is not a number it
// inherited without checking.
.const EBULLET_MAX      = 3
.const EBULLET_VY       = 3             // whole pixels a frame, downward
.const EBULLET_COL      = 7             // yellow
.const EBULLET_VX_MAX   = 2             // the steepest quantised slope

// The aim buckets, from chooseEnemyBulletSlope. They "intentionally favour
// smooth-looking trajectories over exact mathematical interception".
.const EBULLET_AIM_NEAR = 24            // closer than this: straight down
.const EBULLET_AIM_MID  = 72            // closer than this: one pixel a frame

// The player hitbox, from checkBulletPlayerOverlap. The ship is 24 wide and 21
// tall and the projectile is 8 by 8, so the overlap window is the ship's box
// grown by the bullet's size on the two leading edges.
.const EBULLET_HIT_LEFT = 8             // bulletX may be up to 7 left of plyX
.const EBULLET_HIT_RIGHT = 24           // ...and up to 23 right of it
.const EBULLET_HIT_UP   = 8             // bulletY may be up to 7 above plyY
.const EBULLET_HIT_DOWN = 21            // ...and up to 20 below it

// Horizontal despawn, from moveEnemyBullet's two edge tests.
.const EBULLET_X_MAX    = 345           // 9-bit; past the useful right edge
.const EBULLET_X_MIN    = 8             // a borrow out of the low byte

// Vertical despawn. The old rule was Y >= 250, and it is kept, but the
// COLLISION band is this engine's renderable one -- see ebulletPlayerTick.
.const EBULLET_Y_MAX    = 250

.if (EBULLET_MAX > MAX_OBJECTS) {
    .error "the projectile cap cannot exceed the object pool"
}

// ---------------------------------------------------------------------------
// The bitmap. One shared 8x8 dart, hires, from the old enemyBulletSprite.
// ---------------------------------------------------------------------------
// It goes after the enemy's bitmap rather than beside it, because a sprite
// pointer is an address divided by 64 and $36c0 is the next aligned slot.
// (It used to clear the enemy's spawn and colour TABLES too; those left with
// the spawner when src/waves.asm took the job over, and the guard below now
// names the bitmap, which is what actually sits below this address.)
.const EBULLET_SPRITE   = $36c0
.const EBULLET_PTR      = EBULLET_SPRITE / 64

.if ((EBULLET_SPRITE & 63) != 0) {
    .error "the projectile bitmap must be 64-byte aligned"
}
.if (EBULLET_SPRITE < enemyBitmapEnd) {
    .error "the projectile bitmap overlaps the enemy bitmap"
}
.if (EBULLET_SPRITE + 64 > BLANK_CHARSET) {
    .error "the projectile bitmap has run into the blank charset"
}

* = EBULLET_SPRITE "projectile bitmap"
ebulletBitmap:
    .byte $3c,$00,$00
    .byte $ff,$00,$00
    .byte $ff,$00,$00
    .byte $3c,$00,$00
    .byte $3c,$00,$00
    .byte $18,$00,$00
    .byte $18,$00,$00
    .byte $00,$00,$00
    .fill 39, $00
    .byte $00                           // the 64th byte the VIC never fetches
ebulletBitmapEnd:

.if (ebulletBitmapEnd - ebulletBitmap != 64) {
    .error "the projectile bitmap must be exactly 64 bytes"
}

// ===========================================================================
// State. MAIN THREAD ONLY.
// ===========================================================================
* = $6e80 "projectile state"

// THE CAP IS A COUNTER, NOT A SEARCH. Asking "how many are in flight" by
// walking sixteen pool slots would put a scan on every firing decision; this
// is one byte, raised by the spawn and lowered by the only two routines that
// can retire a projectile.
ebCount:     .byte 0                    // live projectiles, 0..EBULLET_MAX

// The spawn request. A caller fills these and calls ebulletSpawn, exactly as
// the old BULLET_SPAWN_X_LO/HI/Y did, so a later enemy-fire slice has the same
// three bytes to fill and nothing new to learn.
ebSpawnXLo:  .byte 0
ebSpawnXHi:  .byte 0
ebSpawnY:    .byte 0

// --- diagnostics, read by the tests and the report -------------------------
ebFired:     .byte 0                    // projectiles that reached the world
ebRefused:   .byte 0                    // spawns the cap or the pool refused
ebPlayerHits: .byte 0                   // projectiles that reached the ship

ebTmp:       .byte 0                    // the nine-bit delta's low byte
ebSlot:      .byte 0                    // the slot a scan is working on
ebulletStateEnd:

.if (ebulletStateEnd > $6f00) {
    .error "the projectile state has outgrown its $6e80 segment"
}

* = $7500 "projectile code"

// ---------------------------------------------------------------------------
// ebulletInit — no projectiles, no history. Called once from entry.
// ---------------------------------------------------------------------------
ebulletInit:
    lda #0
    sta ebCount
    sta ebFired
    sta ebRefused
    sta ebPlayerHits
    rts

// ---------------------------------------------------------------------------
// ebulletSpawn — one projectile at ebSpawnX/Y, aimed at the player.
//
// Exit: carry CLEAR and X = the slot on success; carry SET and nothing changed
//       if the cap or the pool refused.
//
// THE TRAJECTORY IS FIXED AT LAUNCH and never revised, which is the old
// behaviour and is also the cheap one: a projectile costs one add per axis per
// frame and never looks at the player again.
//
// ALLOCATE, FILL, THEN ACTIVATE -- the pool's own contract, and the reason it
// is two calls. Between them the slot is not yet named by sortedIDs, so a
// half-built projectile can never reach a schedule.
// ---------------------------------------------------------------------------
ebulletSpawn:
    lda ebCount
    cmp #EBULLET_MAX
    bcc !room+
!refuse:
    lda ebRefused                       // saturating: that it happened matters
    cmp #$ff
    beq !full+
    inc ebRefused
!full:
    sec
    rts
!room:
    jsr objectAlloc                     // carry set = the pool is full
    bcs !refuse-

    // ---- position ---------------------------------------------------------
    lda ebSpawnXLo
    sta logX,x
    lda ebSpawnXHi
    sta logXHi,x
    lda ebSpawnY
    sta logY,x

    // ---- presentation -----------------------------------------------------
    lda #EBULLET_PTR
    sta logPtr,x
    lda #EBULLET_COL
    sta logCol,x

    // ---- gameplay ---------------------------------------------------------
    lda #TYPE_EBULLET
    sta objType,x
    lda #EBULLET_VY
    sta objVY,x
    lda #0
    sta objHP,x                         // a projectile has no health and is not
    sta objTimer,x                      // a hitscan target: traceRay filters on
                                        // TYPE_ENEMY and never sees this slot

    jsr ebulletAim                      // -> objVX,x

    jsr objectActivate                  // now it may be sorted and drawn
    inc ebCount
    lda ebFired
    cmp #$ff
    beq !counted+
    inc ebFired
!counted:
    clc
    rts

// ---------------------------------------------------------------------------
// ebulletAim — the quantised slope, from chooseEnemyBulletSlope.
// In/out: X = the slot, preserved. Writes objVX,x.
//
// The old routine's own note: the thresholds "intentionally favour
// smooth-looking trajectories over exact mathematical interception. They
// correspond to nearby good aiming points". A projectile that always aimed
// perfectly would be unfair and would also look wrong, because every shot
// would converge on the same pixel.
// ---------------------------------------------------------------------------
ebulletAim:
    // delta = playerX - bulletX, nine bits and signed.
    lda plyX
    sec
    sbc logX,x
    sta ebTmp
    lda plyXHi
    sbc logXHi,x
    beq !right+                         // high byte 0: the player is to the
                                        // right, or within 255 pixels of it
    cmp #$ff
    beq !left+

    // Further than 255 pixels either way. The sign of the high byte is the
    // direction and the steepest slope is necessarily the nearest useful one.
    bmi !farLeft+
    lda #EBULLET_VX_MAX
    sta objVX,x
    rts
!farLeft:
    lda #0 - EBULLET_VX_MAX
    sta objVX,x
    rts

!right:
    lda ebTmp
    jsr ebulletSlope
    sta objVX,x
    rts

!left:
    lda ebTmp                           // two's complement low byte -> magnitude
    eor #$ff
    clc
    adc #1
    jsr ebulletSlope
    beq !store+                         // zero has no sign to flip
    eor #$ff
    clc
    adc #1
!store:
    sta objVX,x
    rts

// A = |horizontal distance|. Returns A = 0, 1 or 2.
ebulletSlope:
    cmp #EBULLET_AIM_NEAR
    bcc !straight+
    cmp #EBULLET_AIM_MID
    bcc !medium+
    lda #EBULLET_VX_MAX
    rts
!medium:
    lda #1
    rts
!straight:
    lda #0
    rts

// ---------------------------------------------------------------------------
// ebulletTick — one frame of one projectile. X = the slot, preserved.
// Called from objectUpdateAll, which already knows the slot is active and
// already knows its type.
//
// The despawn rules are the old moveEnemyBullet's: off either side, or at the
// bottom of the screen. Nothing else retires a projectile except a hit.
// ---------------------------------------------------------------------------
ebulletTick:
    // ---- horizontal: signed velocity into a nine-bit position -------------
    lda objVX,x
    beq !vertical+
    bmi !left+

    clc                                 // moving right
    adc logX,x
    sta logX,x
    bcc !checkRight+
    inc logXHi,x
!checkRight:
    lda logXHi,x                        // past EBULLET_X_MAX?
    cmp #>EBULLET_X_MAX
    bcc !vertical+
    bne ebulletRetire
    lda logX,x
    cmp #<EBULLET_X_MAX
    bcs ebulletRetire
    jmp !vertical+

!left:
    clc                                 // A is negative: a CLEAR carry is the
    adc logX,x                          // borrow out of the low byte
    sta logX,x
    bcs !checkLeft+
    lda logXHi,x
    beq ebulletRetire                   // borrowed past zero: off the left edge
    dec logXHi,x
!checkLeft:
    lda logXHi,x
    bne !vertical+
    lda logX,x
    cmp #EBULLET_X_MIN
    bcc ebulletRetire

!vertical:
    lda logY,x
    clc
    adc #EBULLET_VY
    bcs ebulletRetire                   // wrapped: definitely below the screen
    sta logY,x
    cmp #EBULLET_Y_MAX
    bcs ebulletRetire
    rts

// ---------------------------------------------------------------------------
// ebulletRetire — the ONE place a projectile leaves the world.
// X = the slot, preserved. Safe on a slot that is already free: objectFree
// counts that itself and ebCount is guarded against underflow.
// ---------------------------------------------------------------------------
ebulletRetire:
    jsr objectFree                      // despawn touches no VIC register: the
                                        // next schedule simply omits it
    lda ebCount
    beq !done+                          // the old game's own defensive guard
    dec ebCount                         // against an accidental double release
!done:
    rts

// ---------------------------------------------------------------------------
// ebulletPlayerTick — the projectiles meet the ship. MAIN THREAD.
//
// SOFTWARE COLLISION, IN LOGICAL COORDINATES. $d01e is not read here or
// anywhere else in this engine, and the reason is the same one
// src/collision.asm gives for the player's own weapon: the mux time-shares
// HW2..HW7, so a VIC collision bit names a SLOT and a slot is not an object.
// It would also be answering about the HUD's sprites for part of every frame.
//
// THE COST IS GATED ON ebCount. With no projectile in flight -- which is most
// of the game -- this routine is a load and a branch. Only when one exists
// does it walk the pool, and the pool is sixteen slots with at most three of
// them projectiles.
//
// ONLY INSIDE THE RENDERABLE BAND. A projectile whose Y the builder would
// reject is not drawn, and something the player cannot see must not kill them.
// The old game gated its scan the same way and said so: "Culled ingress cannot
// cause an invisible software collision." Its band was the old aperture's;
// this one is MIN_SPRITE_Y..MAX_SPRITE_Y, which is where THIS renderer admits.
// ---------------------------------------------------------------------------
ebulletPlayerTick:
    lda ebCount
    bne !scan+
    rts
!scan:
    lda plyInvuln                       // an invulnerable ship is not a target,
    beq !live+                          // and the projectile flies through it
    rts
!live:
    ldx #0
!slot:
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_EBULLET
    bne !next+

    // ---- is it where the player can see it? -------------------------------
    lda logY,x
    cmp #MIN_SPRITE_Y
    bcc !next+
    cmp #MAX_SPRITE_Y + 1
    bcs !next+

    // ---- vertical overlap -------------------------------------------------
    // bulletY - plyY must lie in -EBULLET_HIT_UP+1 .. EBULLET_HIT_DOWN-1.
    // Biasing by the upper reach turns that into ONE unsigned compare.
    sec
    sbc plyY
    clc
    adc #EBULLET_HIT_UP - 1
    cmp #EBULLET_HIT_UP - 1 + EBULLET_HIT_DOWN
    bcs !next+

    // ---- horizontal overlap, nine bits ------------------------------------
    lda logX,x
    sec
    sbc plyX
    sta ebTmp
    lda logXHi,x
    sbc plyXHi
    beq !bulletRight+
    cmp #$ff
    bne !next+                          // more than 255 pixels apart

    lda ebTmp                           // the bullet is left of the ship
    clc
    adc #EBULLET_HIT_LEFT - 1
    bcc !next+                          // further left than the box reaches
    jmp !hit+

!bulletRight:
    lda ebTmp
    cmp #EBULLET_HIT_RIGHT
    bcs !next+

!hit:
    stx ebSlot
    jsr playerTakeHit                   // the player owns what a hit MEANS
    ldx ebSlot
    jsr ebulletRetire                   // THE PROJECTILE IS CONSUMED. One
                                        // bullet cannot damage the ship twice:
                                        // it stops existing on the frame it
                                        // connects, before any second pass.
    lda ebPlayerHits
    cmp #$ff
    beq !done+
    inc ebPlayerHits
!done:
    rts                                 // one hit a frame is enough: the ship is
                                        // invulnerable from here anyway, so the
                                        // remaining projectiles would all be
                                        // refused by the gate at the top

!next:
    inx
    cpx #MAX_OBJECTS
    bne !slot-
    rts

.if (* > $7700) {
    .error "the projectile code has outgrown its $7500 segment"
}
