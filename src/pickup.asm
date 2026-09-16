// ===========================================================================
// pickup.asm — collectible tokens: the art, the lifecycle and the collection
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is read or written from this file and
// $d01e is never consulted. A token is an ORDINARY LOGICAL OBJECT -- it is
// allocated from src/objects.asm's pool, it writes logY/logX/logXHi/logPtr/
// logCol like everything else, and the sorter, the builder and the mux draw it
// without knowing it is collectible. There is no reserved hardware sprite and
// no pickup-shaped hole in the renderer.
//
//     waveStartNext    an authored trigger says a token appears, and where
//     pickupSpawn      <- here: one token, if the pool allows
//     objectUpdateAll  -> pickupTick: the drift, the flash and the despawn
//     pickupPlayerTick <- here: the token meets the ship
//     pickupCollect    -> the kind's effect, and the slot goes back
//
// ---------------------------------------------------------------------------
// ONE KIND TODAY, AND THE SEAM FOR THE NEXT ONE
// ---------------------------------------------------------------------------
// v1 authors exactly one kind, PICKUP_P. What makes a second kind cheap is not
// a framework, it is that the three things a kind can differ in are already
// looked up rather than hard-coded:
//
//     pkPtrTab      which bitmap it wears
//     pkColTab      the two colours it flashes between
//     pickupCollect what collecting it DOES
//
// Everything else -- allocation, placement, drift, despawn, the overlap test,
// the slot release -- is common and is written once. A second kind is a row in
// two tables and an arm in one branch; it is not a new object lifecycle.
//
// THERE IS DELIBERATELY NO INVENTORY, no power-up tree, no rarity, no drop
// table and no RNG. The P token does not grant a weapon upgrade yet: it
// increments a counter, and that counter is the hook the upgrade system will
// hang off when there is one to hang.
// ===========================================================================

// --- the kinds --------------------------------------------------------------
// A kind is an index into every table in this file. PICKUP_P is 0 because a
// kind is a table row rather than an identity that has to survive a zeroed
// slot -- objType is what says "this slot is a pickup at all", exactly as
// enySpecies relies on objType to mean anything. See src/enemy.asm, which
// makes the same choice for the same reason.
.const PICKUP_P      = 0
.const PICKUP_KINDS  = 1

// --- drift and lifetime -----------------------------------------------------
// ONE PIXEL A FRAME, DOWNWARD, BECAUSE THAT IS THE SCROLL. src/scroll.asm's
// coarse step advances scrollFine once per frame -- "content moves DOWN one
// pixel" -- so a token descending at exactly one pixel a frame is CARRIED BY
// THE WORLD rather than flying through it. It is the only speed that makes a
// collectible look like it is lying on the terrain, and it costs one add.
//
// There is deliberately no drift, no magnetism, no bob and no homing: a token
// that moves with the ground is a thing the player steers into, which is the
// whole of the interaction v1 wants.
.const PICKUP_VY     = 1

// ...APPLIED ON ONE FRAME IN TWO. See the note in pickupTick: the token is now
// the centre of an encounter that has to be watched, so it descends at half
// the scroll rate. A mask rather than a counter, so it costs no state and
// every token on screen moves on the same frames.
.const PICKUP_VY_MASK = %00000001

// Where a token is authored to appear, above the aperture. The whole 21-line
// sprite is above raster 55 at this Y, so a token FADES IN through the top
// edge exactly as the enemy waves do rather than materialising in view.
.const PICKUP_SPAWN_Y = 30

// ...and where it gives up. Past the bottom of the renderable band there is
// nothing left to collect and nothing left to see, so the slot goes back.
// Chosen to match the projectile's own EBULLET_Y_MAX: both are "below the
// aperture and no longer anybody's business".
.const PICKUP_Y_MAX  = 250

// --- the flash --------------------------------------------------------------
// PRESENTATION ONLY, AND DERIVED, NOT TIMED. The phase is a bit of the
// renderer's own frameCounter, so there is no per-token timer byte, no
// per-token state to reset on spawn, and every token on screen flashes in
// step -- which reads as "these are the same kind of thing" rather than as
// several independent blinking objects.
//
// Bit 4 gives sixteen frames lit and sixteen dark: a 1.6 Hz pulse, slow enough
// to read as deliberate attention-getting rather than as a fault, and far
// slower than the player's four-frame invulnerability blink so the two can
// never be confused.
//
// IT CANNOT AFFECT GAMEPLAY. The flash writes logCol and nothing else: not
// logPtr, not objType, not pkKind, not logY. Collision, lifetime and identity
// are read from bytes this code never touches.
.const PICKUP_FLASH_BIT = %00010000

// --- the collection box -----------------------------------------------------
// BOTH SPRITES ARE 24 WIDE AND 21 TALL, so the overlap window is the ship's box
// grown by the token's size on the two leading edges -- the same construction
// src/ebullet.asm uses for the projectile, with the projectile's 8x8 replaced
// by the token's full cell.
//
// IT IS EXACTLY THE TWO SPRITES TOUCHING, deliberately, with no generosity
// added. A pickup box larger than the art collects tokens the player can see
// they missed, which feels arbitrary; one smaller refuses tokens they can see
// they hit, which feels broken. If manual play says it wants to be kinder,
// these four numbers are where that decision goes and it is one byte each.
.const PICKUP_HIT_LEFT  = 24            // tokenX may be up to 23 left of plyX
.const PICKUP_HIT_RIGHT = 24            // ...and up to 23 right of it
.const PICKUP_HIT_UP    = 21            // tokenY may be up to 20 above plyY
.const PICKUP_HIT_DOWN  = 21            // ...and up to 20 below it

// ===========================================================================
// THE PLACEHOLDER ART — a flashing capital P
// ===========================================================================
// $2580 is in the free run between the player's muzzle flash and screen page
// B, which src/main.asm's bank map names as eleven free blocks. It is where a
// token BELONGS rather than merely where it fits: this run already holds the
// engine's own permanent sprite art -- the ship at $2000 and its muzzle flash
// at $2400 -- and a token is engine-owned content that every level has, not
// level-replaceable artwork. It is NOT the enemy sprite window.
//
// NOT $3580, though that run is equally free and equally documented. The four
// blocks there are the Ring's former pinned home, and tests/test_level_assets.py
// asserts the whole 256 bytes are still zero as proof that the migration to one
// contiguous enemy window was genuinely completed. That assertion is worth more
// than the block is: putting a token in it would have cost a real invariant to
// save a memory lookup, so the token went somewhere nothing is proving anything
// about.
//
// PLACEHOLDER, AND SAYING SO IS THE POINT. This slice exists to establish the
// lifecycle, not the artwork. What the art has to do is be unmistakably a P at
// speed, over terrain, at any of its flash colours -- and nothing more.
//
// MULTICOLOUR, because every gameplay sprite in this game is: src/renderer.asm
// hands HW2..HW7 to the mux with the multicolour bits set, so a hires bitmap
// here would be drawn as double-width garbage. Twelve pixel-pairs across:
//
//     pair 01  SPR_MC_DARK   the badge the letter sits on
//     pair 10  logCol        THE LETTER -- this is the pair that flashes
//     pair 11  SPR_MC_LIGHT  unused here
//
// THE LETTER FLASHES AND THE BADGE DOES NOT, which is what keeps it legible.
// A glyph drawn straight onto the playfield would lose its edge against the
// terrain's greys at whichever flash colour happened to be closest to them;
// a constant dark badge behind it means the P is read against the SAME
// background on every frame, and the colour change is pure signal.
.const TOKEN_SPRITE  = $2580
.const TOKEN_PTR     = TOKEN_SPRITE / 64        // $96

.if ((TOKEN_SPRITE & 63) != 0) {
    .error "the token bitmap must be 64-byte aligned"
}
.if (TOKEN_SPRITE < PLAYER_FLASH_END) {
    .error "the token bitmap overlaps the player's muzzle flash frames"
}
.if (TOKEN_SPRITE + 64 > SCREEN_B) {
    .error "the token bitmap has run into screen page B"
}

* = TOKEN_SPRITE "token bitmap"
tokenBitmap:
    .byte $15,$55,$54               //  ssssssssss
    .byte $55,$55,$55               // ssssssssssss
    .byte $55,$55,$55               // ssssssssssss
    .byte $5a,$aa,$95               // ssPPPPPPPsss
    .byte $5a,$aa,$a5               // ssPPPPPPPPss
    .byte $5a,$55,$a5               // ssPPssssPPss
    .byte $5a,$55,$a5               // ssPPssssPPss
    .byte $5a,$55,$a5               // ssPPssssPPss
    .byte $5a,$55,$a5               // ssPPssssPPss
    .byte $5a,$aa,$a5               // ssPPPPPPPPss
    .byte $5a,$aa,$95               // ssPPPPPPPsss
    .byte $5a,$55,$55               // ssPPssssssss
    .byte $5a,$55,$55               // ssPPssssssss
    .byte $5a,$55,$55               // ssPPssssssss
    .byte $5a,$55,$55               // ssPPssssssss
    .byte $5a,$55,$55               // ssPPssssssss
    .byte $5a,$55,$55               // ssPPssssssss
    .byte $5a,$55,$55               // ssPPssssssss
    .byte $55,$55,$55               // ssssssssssss
    .byte $55,$55,$55               // ssssssssssss
    .byte $15,$55,$54               //  ssssssssss
    .byte $00                       // the 64th byte the VIC never fetches
tokenBitmapEnd:

.if (tokenBitmapEnd - tokenBitmap != 64) {
    .error "the token bitmap must be exactly 64 bytes"
}

// ===========================================================================
// State. MAIN THREAD ONLY. Outside VIC bank 0, in the free run between the
// level asset state that ends at $c401 and the enemy firing array at $c4e0.
// ===========================================================================
* = $c4c0 "pickup state"

// THE COUNTER THIS WHOLE SLICE EXISTS TO MOVE. Saturating, like every other
// counter in this engine: that the player has collected P tokens is the fact,
// and the exact count past 255 is not one this game will ever need.
//
// IT IS PERSISTENT GAMEPLAY STATE, not a diagnostic. pickupInit clears it at
// COLD START only -- see the note there -- so it survives everything a session
// does short of a reboot, and it is the hook the weapon-upgrade system will
// read when there is one. Nothing in this file acts on its value.
pkTokensP:   .byte 0

// --- diagnostics, saturating ------------------------------------------------
pkSpawned:   .byte 0                    // tokens that reached the world
pkDropped:   .byte 0                    // authored tokens the pool refused
pkDespawned: .byte 0                    // tokens that fell past the aperture

// pickupPlayerTick's scratch: the slot being tested, across the jsr that
// collects it. The nine-bit horizontal compare needs its own byte too.
pkSlot:      .byte 0
pkTmp:       .byte 0

// The spawn request: an authored caller fills these two bytes and calls
// pickupSpawn with the kind in A. Y is NOT a parameter -- every token enters
// from PICKUP_SPAWN_Y, above the aperture -- because a token authored to
// appear mid-screen would materialise in front of the player.
pkSpawnXLo:  .byte 0
pkSpawnXHi:  .byte 0

// ...AND Y IS A PARAMETER NOW. It was a constant while tokens were authored on
// the trigger list and every one entered from above the aperture. A token is
// now dropped by a destroyed Dropper and must appear WHERE IT DIED, so the
// caller says where. src/token.asm is the only caller.
pkSpawnY:    .byte 0

// PER-OBJECT KIND, one byte per POOL SLOT, written at spawn and then never
// again for that token's life. It is on the OBJECT rather than looked up from
// anything else for the same reason enySpecies is: a slot outlives the thing
// that authored it, and objectZeroSlot clears this with the rest of the slot
// so a reused slot cannot inherit the previous occupant's kind.
pkKind:      .fill MAX_OBJECTS, 0

pickupStateEnd:
.if (pickupStateEnd > $c4e0) {
    .error "the pickup state has grown into the enemy firing array at $c4e0"
}

// ===========================================================================
// Code. MAIN THREAD ONLY. In the free run between the collision code that
// ends at $4cea and main at $5000.
// ===========================================================================
* = $4d00 "pickup code"

// ---------------------------------------------------------------------------
// pickupInit — no tokens collected, no history. Called ONCE, from entry.
//
// COLD START ONLY, AND DELIBERATELY NOT FROM gameInit. Every other subsystem's
// init is safe to re-enter on a restart because it describes the WORLD -- no
// enemies, no projectiles, no waves running. pkTokensP describes the PLAYER,
// and the day there is a restart or a game-over it is a decision for that day
// whether collected tokens survive it. Putting this in gameInit would answer
// that question silently, by accident, in the direction nobody chose.
//
// The live tokens themselves need no teardown here: they are ordinary pool
// objects and objectInit's slot clear takes them with everything else.
// ---------------------------------------------------------------------------
pickupInit:
    lda #0
    sta pkTokensP
    sta pkSpawned
    sta pkDropped
    sta pkDespawned
    rts

// ---------------------------------------------------------------------------
// pickupSpawn — one token of kind A at nine-bit X in pkSpawnXLo/Hi.
//
// Entry: A = the kind, pkSpawnXLo/pkSpawnXHi = where.
// Exit:  carry CLEAR and X = the slot on success; carry SET and nothing
//        changed if the pool refused.
//
// A REFUSED TOKEN IS LOST, NOT QUEUED, and that is the same policy the two
// firing systems already use. A deferred token would arrive detached from the
// authored moment that asked for it -- drifting down over terrain it was not
// authored against, possibly in the middle of the next formation -- which is
// exactly the non-determinism that makes authored content impossible to tune.
// src/waves.asm makes this argument for dropped triggers and it is the same
// argument here. pkDropped counts it so the loss is visible rather than silent.
//
// IT CANNOT STARVE ANYTHING. A token competes for the same sixteen pool slots
// as everything else, and it is the LAST caller in the frame to ask -- the
// waves, the turrets and the enemies have all already had their turn. A full
// pool therefore costs a token rather than an enemy or a bolt, which is the
// right way round: a missed collectible is a missed bonus, a missed enemy is a
// hole in the authored encounter.
//
// ALLOCATE, FILL, THEN ACTIVATE -- the pool's own contract. Between the two
// calls the slot is not yet named by sortedIDs, so a half-built token can
// never reach a schedule.
// ---------------------------------------------------------------------------
pickupSpawn:
    sta pkTmp                           // the kind, while X is needed for the
                                        // slot and Y for the tables
    jsr objectAlloc                     // carry set = the pool is full
    bcc !got+

    lda pkDropped                       // saturating: that it happened matters
    cmp #$ff
    beq !refused+
    inc pkDropped
!refused:
    sec
    rts

!got:
    // ---- position ---------------------------------------------------------
    lda pkSpawnXLo
    sta logX,x
    lda pkSpawnXHi
    sta logXHi,x
    lda pkSpawnY                        // the CALLER's Y: a token now appears
    sta logY,x                          // where its Dropper died, not at a
                                        // fixed line above the aperture

    // ---- identity ---------------------------------------------------------
    lda pkTmp
    sta pkKind,x
    tay                                 // Y indexes the per-kind tables

    // ---- presentation -----------------------------------------------------
    lda pkPtrTab,y
    sta logPtr,x
    lda pkColTab,y                      // the LIT colour, so a token that is
    sta logCol,x                        // spawned and drawn before its first
                                        // pickupTick is never drawn colourless

    // ---- gameplay ---------------------------------------------------------
    lda #TYPE_PICKUP
    sta objType,x
    lda #PICKUP_VY
    sta objVY,x
    lda #0
    sta objVX,x                         // straight down, and no sideways drift
    sta objHP,x                         // A TOKEN IS NOT A TARGET. traceRay
    sta objTimer,x                      // filters on TYPE_ENEMY, so the
                                        // player's cannon cannot shoot its own
                                        // pickups down, and applyDamage can
                                        // never see this slot

    jsr objectActivate                  // now it may be sorted and drawn

    lda pkSpawned
    cmp #$ff
    beq !counted+
    inc pkSpawned
!counted:
    clc
    rts

// ---------------------------------------------------------------------------
// pickupTick — one frame of one token. X = the slot, preserved.
// Called from objectUpdateAll, which already knows the slot is active and
// already knows its type.
//
// The flash first and unconditionally, then the drift. Both are cheap and
// neither looks at anything outside this slot.
// ---------------------------------------------------------------------------
pickupTick:
    // ---- the flash: PRESENTATION ONLY -------------------------------------
    // The colour table is two entries per kind, lit then dark, so the phase
    // bit is the low bit of the index and the kind is the high part. With one
    // kind that is an add; with four it is still an add.
    ldy pkKind,x
    tya
    asl                                 // kind * 2
    sta pkTmp
    lda frameCounter
    and #PICKUP_FLASH_BIT
    beq !lit+
    inc pkTmp                           // ...the dark half of the pair
!lit:
    ldy pkTmp
    lda pkColTab,y
    sta logCol,x                        // and NOTHING else. See the header.

    // ---- the drift, ON EVERY OTHER FRAME ----------------------------------
    // PROVISIONAL, AND HALF THE SPEED IT WAS. One pixel a frame matched the
    // scroll exactly, which was right when a token was scenery to steer into.
    // A token is now the prize at the centre of a three-enemy encounter, and
    // at the old rate it crossed the aperture in under four seconds -- barely
    // time for the reinforcement and egress to be seen at all, let alone
    // judged.
    //
    // A FRAME-COUNTER BIT, NOT A FRACTIONAL VELOCITY. The token moves on even
    // frames and holds on odd ones: one pixel every two frames, deterministic,
    // no accumulator, no per-token byte and no sub-pixel machinery. The token
    // no longer matches the scroll, and that is now correct -- it should read
    // as an object hanging in the encounter rather than as part of the ground.
    //
    // THIS IS NOT FINAL BALANCE. It exists so the mechanic can be watched; the
    // rate lives here, in one bit, for exactly that reason.
    lda frameCounter
    and #PICKUP_VY_MASK
    bne !held+

    lda logY,x
    clc
    adc #PICKUP_VY
    bcs pickupDespawn                   // wrapped: certainly below the screen
    sta logY,x
    cmp #PICKUP_Y_MAX
    bcs pickupDespawn
!held:

    // ---- how much of it is outside the aperture ---------------------------
    // THE TOKEN IS CLIPPED BY THE SAME RULE AND THE SAME SCRATCH AS AN ENEMY,
    // and this one call is the whole of it. src/enemy.asm's logClipAnnotate
    // writes logClip from logY; the schedule builder turns that into a clamped
    // physical Y and a row-shifted copy in the CURRENT/NEXT scratch pool, and
    // src/clip.asm renders it from whatever logPtr names -- which for a token
    // is the token's own bitmap.
    //
    // NOTHING TOKEN-SPECIFIC EXISTS ANYWHERE IN THAT PATH. The builder and the
    // clipper never asked what type an entry was; a token simply never wrote
    // the annotation, so it was admitted whole or not at all and fell off the
    // bottom edge in one step. This is an eligibility fix, not a clipping
    // change.
    jmp logClipAnnotate                 // X preserved; its rts is ours

// ---------------------------------------------------------------------------
// pickupDespawn — this token's life ends uncollected. X = slot, preserved.
//
// THE ONE PLACE A TOKEN LEAVES THE WORLD WITHOUT BEING COLLECTED, and it is
// the same objectFree every other object retires through: the slot is zeroed
// whole -- pkKind included -- logCount comes down and the sorter is told. There
// is nothing to undo in the renderer, because nothing was ever reserved in it.
// ---------------------------------------------------------------------------
pickupDespawn:
    jsr objectFree
    lda pkDespawned
    cmp #$ff
    beq !done+
    inc pkDespawned
!done:
    rts

// ---------------------------------------------------------------------------
// pickupPlayerTick — the tokens meet the ship. MAIN THREAD.
//
// SOFTWARE COLLISION, IN LOGICAL COORDINATES, and the reason is the one
// src/ebullet.asm and src/collision.asm both give: the mux time-shares
// HW2..HW7, so a VIC collision bit names a SLOT and a slot is not an object.
// $d01e is not read here or anywhere else in this engine.
//
// ---------------------------------------------------------------------------
// AN INVULNERABLE PLAYER *DOES* COLLECT TOKENS, AND THAT IS A DECISION
// ---------------------------------------------------------------------------
// ebulletPlayerTick refuses to test anything while plyInvuln is set, and it is
// RIGHT to: a bolt should pass through a ship that cannot be hurt. Inheriting
// that here by copying the routine would have been wrong, so this routine does
// not have the test at all.
//
// plyInvuln in this engine is a DAMAGE-IMMUNITY WINDOW, not a death or a
// respawn: there is no death state, no lives system and no respawn -- the ship
// is flying, controllable and on screen for every one of those hundred frames,
// blinking. Refusing pickups during it would punish the player twice for being
// hit, and would create a dead zone in which a token visibly passes through
// the ship and is not collected, which reads as a bug rather than a rule.
//
// If a real death/respawn state arrives later, THAT is the state that should
// refuse collection, and it should refuse it by not running this routine at
// all rather than by adding a second meaning to plyInvuln.
//
// THE COST IS A POOL WALK, and it is not gated on a counter the way
// ebulletPlayerTick gates on ebCount. A token count byte would be a second
// thing to keep in step with the pool for no benefit: the walk is sixteen
// iterations of a load and a compare, most of which fail on the first
// instruction, and it runs once a frame.
// ---------------------------------------------------------------------------
pickupPlayerTick:
    ldx #0
!slot:
    lda logActive,x
    beq !next+                          // A STALE SLOT COLLECTS NOTHING. The
                                        // pool clears objType when it frees a
                                        // slot, so a freed token fails the type
                                        // test below as well -- this is the
                                        // first of two independent refusals
    lda objType,x
    cmp #TYPE_PICKUP
    bne !next+

    // ---- vertical overlap -------------------------------------------------
    // tokenY - plyY must lie in -(PICKUP_HIT_UP-1) .. PICKUP_HIT_DOWN-1.
    // Biasing by the upper reach turns that into ONE unsigned compare.
    lda logY,x
    sec
    sbc plyY
    clc
    adc #PICKUP_HIT_UP - 1
    cmp #PICKUP_HIT_UP - 1 + PICKUP_HIT_DOWN
    bcs !next+

    // ---- horizontal overlap, nine bits ------------------------------------
    lda logX,x
    sec
    sbc plyX
    sta pkTmp
    lda logXHi,x
    sbc plyXHi
    beq !tokenRight+
    cmp #$ff
    bne !next+                          // more than 255 pixels apart

    lda pkTmp                           // the token is left of the ship
    clc
    adc #PICKUP_HIT_LEFT - 1
    bcc !next+                          // further left than the box reaches
    jmp !collect+

!tokenRight:
    lda pkTmp
    cmp #PICKUP_HIT_RIGHT
    bcs !next+

!collect:
    stx pkSlot
    jsr pickupCollect                   // the kind's effect, then the slot back
    ldx pkSlot

!next:
    inx
    cpx #MAX_OBJECTS
    bne !slot-
    rts                                 // EVERY SLOT IS VISITED, unlike
                                        // ebulletPlayerTick which stops at the
                                        // first hit. That routine stops because
                                        // the ship becomes invulnerable and the
                                        // rest would be refused anyway; nothing
                                        // here changes after a collection, so
                                        // two tokens overlapping the ship on
                                        // one frame are both collected

// ---------------------------------------------------------------------------
// pickupCollect — this token has been picked up. X = the slot.
//
// EXACTLY ONCE, BY CONSTRUCTION. The slot is freed before this returns, so the
// scan that called it cannot see the token again on this frame -- logActive is
// already zero by the time the loop advances -- and no later frame can either.
// One token, one increment, and the property does not depend on the caller
// being careful.
//
// THE KIND SEAM. A cmp chain rather than a jump table, which is the same
// choice src/objects.asm makes for its own type dispatch and for the same
// stated reason: with one kind -- or two, or three -- a table costs more than
// it saves. The day a fourth kind arrives, this becomes a table and the call
// site does not change.
// ---------------------------------------------------------------------------
pickupCollect:
    lda pkKind,x
    cmp #PICKUP_P
    bne !unknown+

    // ---- the P token's effect --------------------------------------------
    // IT DOES NOT GRANT A POWER-UP, and that is this slice's scope rather than
    // an omission: the counter is the proof that collection happened and the
    // hook the upgrade system will read. Inventing a weapon upgrade here would
    // be inventing the thing the next slice exists to design.
    lda pkTokensP
    cmp #$ff
    beq !sound+
    inc pkTokensP
!sound:
    lda #SFX_TOKEN
    jsr sfxRequest                      // src/sfx.asm; preserves X and Y

!unknown:
    // A kind with no arm above is still RELEASED, deliberately. Leaving the
    // slot allocated would turn an authoring mistake into a leaked pool slot
    // and a token that sits on the ship for ever.
    jmp objectFree                      // X preserved; its rts is ours

// ===========================================================================
// THE PER-KIND TABLES
// ===========================================================================
// Indexed by kind. One row each today; the seam is that they are ROWS.
// ---------------------------------------------------------------------------
pkPtrTab:                               // which bitmap the kind wears
    .byte TOKEN_PTR                     // PICKUP_P

// TWO ENTRIES PER KIND: the lit colour then the dark one, in the order the
// flash phase indexes them. White to light grey is a pulse in BRIGHTNESS
// rather than in hue -- the letter never changes what it looks like, only how
// hard it is lit, which is what keeps a P a P at every point in the cycle. A
// hue flip would have read as two different tokens alternating.
.const PICKUP_P_COL_LIT  = 1            // white
.const PICKUP_P_COL_DARK = 15           // light grey

pkColTab:
    .byte PICKUP_P_COL_LIT, PICKUP_P_COL_DARK       // PICKUP_P

.if (pkColTab - pkPtrTab != PICKUP_KINDS) {
    .error "the pickup pointer table is not one entry per kind"
}
.if (* - pkColTab != 2 * PICKUP_KINDS) {
    .error "the pickup colour table is not two entries per kind"
}

.if (* > $5000) { .error "the pickup code has run into main at $5000" }
