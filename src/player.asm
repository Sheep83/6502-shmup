// ===========================================================================
// player.asm — the player ship: logical state, input, and the presentation
// block the renderer publishes on its behalf.
// ===========================================================================
// NOT ONE VIC REGISTER IS WRITTEN FROM THIS FILE.
//
// The division of labour is the same one src/hud.asm already established, and
// for the same reason: one subsystem owns sprite VIC state and that subsystem
// is src/renderer.asm. What lives here is the player's LOGICAL state, the
// input that moves it, and a bounded PRESENTATION BLOCK describing what HW0
// and HW1 should look like. The renderer copies that block into the schedule it
// is already double-buffering, publishes it with the same one byte, adopts it
// at raster 250 with everything else, and programs the two slots from the
// adopted copy in exHud.
//
//     input          $dc00 -> joyState
//     playerTick     joyState -> plyX / plyXHi / plyY, clamped
//     playerEmit     logical state -> plyPres (+ plyDirty when it changed)
//     buildSchedule  plyPres -> schedPly*[schedNext]            (renderer)
//     publishSchedule one byte                                  (renderer)
//     exFrame        adopts it with the rest of the frame        (renderer)
//     exHud          programs HW0/HW1 from the ADOPTED copy      (renderer)
//
// So the player obeys the same rule as everything else on screen: if the main
// thread stopped dead immediately after publication, the frame would still
// render correctly, because exHud reads the immutable CURRENT block and nothing
// else.
//
// HW0/HW1 ARE NOT IN THE MUX. docs/ENGINE_CONTRACT.md §2 reserves them, and the
// point of this slice is to honour that literally: the player never enters
// logY/logX, is never sorted, never occupies a schedule entry and never
// competes for a slot. MUX_FIRST_SLOT stays 2 and MAX_SCHED stays 24.
//
// ---------------------------------------------------------------------------
// WHAT WAS TAKEN FROM THE OLD GAME, AND WHAT WAS NOT
// ---------------------------------------------------------------------------
// Behaviour reference: c64Shooter/src/main.asm.
//
//   updatePlayer (2348-2416)   the movement: ONE pixel per frame per axis,
//                              read from joystick port 2, no acceleration and
//                              no momentum. The old routine was read in full
//                              before this was written -- there is no velocity
//                              state in it, and none is invented here.
//   PLAYER_START_X/Y (~966)    160 / 220, kept.
//   X bounds (2380-2416)       the old code refused to move left at X=23 and
//                              right at X=321. Kept as values; the test is now
//                              a total clamp rather than a pre-move refusal.
//   playerSprite (5413)        the ship ART, converted at assembly time -- see
//                              the bitmap section below.
//   PLAYER_COLOUR_NORMAL = 14  the hull colour, kept.
//   $D026 = $0f (setupSprites) the light-grey highlight colour, kept as the
//                              overlay colour.
//   PLAYER_LAYER_COUNT = 2     the two-co-located-hires-layers idea, from the
//                              experimental-three-layer-player work. The IDEA
//                              is kept; none of its code is.
//
// Deliberately NOT taken:
//   * PLAYER_MAX_Y = 237. It relied on the old open lower border showing
//     sprites below the aperture. See PLAYER_MAX_Y below.
//   * the multicolour player ($D025/$D026 shared registers). The contract
//     forces $d01c = 0 on both sides of the handoff, so every sprite is hires.
//   * OBJECT_X/OBJECT_Y[0]: the player no longer lives in the object pool.
//   * OBJECT_SPRITE/OBJECT_COLOUR as a state machine (the old muzzle flash and
//     respawn blink wrote them directly). Presentation is a block here.
//   * PLAYER_HW_MASK, the old "which hardware slot is the player in this
//     frame" mask. The answer is now permanently HW0 and HW1.
// ===========================================================================

// --- the two reserved hardware slots ---------------------------------------
// Bit per slot, for $d015 and $d010. The renderer composes this into the
// complete values it writes; nothing here touches a register.
.const PLAYER_SLOT_MASK = %00000011                 // HW0 | HW1

// --- bitmaps ----------------------------------------------------------------
// Immediately after the HUD's pool and derived from it, so a HUD that grows
// takes the player with it instead of silently overlapping. Pointers $d6/$d7:
// disjoint from the gameplay pool ($80..$8f) and from the HUD's ($c8..$d5), so
// a test can always tell which subsystem a pointer came from.
.const PLAYER_SPRITES   = HUD_SPRITES_END           // $3580
.const PLAYER_BLOCKS    = 3
.const PLAYER_BASE_BMP  = PLAYER_SPRITES + 0 * 64
.const PLAYER_TRIM_BMP  = PLAYER_SPRITES + 1 * 64
.const PLAYER_FIRE_BMP  = PLAYER_SPRITES + 2 * 64
.const PLAYER_SPRITES_END = PLAYER_SPRITES + PLAYER_BLOCKS * 64   // $3640
.const PLAYER_PTR_FIRST = PLAYER_SPRITES / 64       // $d6
.const PLAYER_PTR_BASE  = PLAYER_PTR_FIRST + 0
.const PLAYER_PTR_TRIM  = PLAYER_PTR_FIRST + 1
// The muzzle flash is a HULL-ONLY change: the old firing bitmap differs from the
// resting one on rows 0-2 and nowhere else, and every differing pixel is a hull
// pixel. So the overlay keeps PLAYER_PTR_TRIM and only the base pointer moves,
// which costs ONE extra 64-byte block rather than two.
.const PLAYER_PTR_FIRE  = PLAYER_PTR_FIRST + 2

.if ((PLAYER_SPRITES & 63) != 0) { .error "the player sprite block must be 64-byte aligned" }
.if (PLAYER_SPRITES < HUD_SPRITES_END) { .error "player bitmaps overlap the HUD bitmap pool" }
.if (PLAYER_SPRITES + PLAYER_BLOCKS * 64 > BLANK_CHARSET) {
    .error "player bitmaps run into the blank charset at $3800"
}
.if (PLAYER_PTR_FIRST < HUD_PTR_FIRST + HUD_BLOCKS && PLAYER_PTR_FIRST + PLAYER_BLOCKS > HUD_PTR_FIRST) {
    .error "player and HUD sprite pointers overlap"
}

// --- colours ----------------------------------------------------------------
// 14 is the old PLAYER_COLOUR_NORMAL; 15 is the old $D026 the highlight pixels
// indexed. Two layers carry two colours, so the old dark-grey ($D025) fuselage
// core and the light-grey ($D026) spine merge into ONE light-grey stripe. That
// is the whole visual cost of hires, and it is a deliberate trade: the
// SILHOUETTE is preserved exactly, which is what a player recognises.
.const PLAYER_COL_BASE  = 14                        // light blue hull
.const PLAYER_COL_TRIM  = 15                        // light grey centre stripe
                                                    // and exhaust
// The hull flashes red for the muzzle window, exactly as the old game's
// PLAYER_COLOUR_MUZZLE did. The trim keeps its colour: the old ship had ONE
// per-sprite colour to flash and this one has two, so flashing both would be
// inventing a look rather than preserving one.
.const PLAYER_COL_MUZZLE = 2                        // red

// --- the cannons ------------------------------------------------------------
// Horizontal ray offsets from the player's sprite X, from c64Shooter's
// PLAYER_LEFT_CANNON_X / PLAYER_RIGHT_CANNON_X. They are not arbitrary: the
// firing bitmap's muzzle pixels sit at exactly these two columns, which is how
// the art and the hitscan stay agreed about where the guns are.
.const PLAYER_CANNON_L  = 4
.const PLAYER_CANNON_R  = 19
.const PLAYER_MUZZLE_TIME = 3                       // frames the flash is held

// --- taking a hit -----------------------------------------------------------
// PLAYER_RESPAWN_TIME, from the old game's constant at main.asm:930:
// "Invulnerable blinking frames after repositioning." The old ship reached
// that state through explode -> lose a life -> reposition; this slice has
// neither lives nor an explosion, so it keeps the WINDOW and not the journey.
//
// WHAT IS DELIBERATELY NOT HERE. No PLAYER_STATE machine, no explosion frames,
// no life counter, no game over. The old game's updatePlayerState is a
// four-state machine driving four explosion bitmaps, a lives HUD and a
// terminal state, and none of that is needed to make a turret projectile
// damage the player -- which is what this slice is. A hit costs the player
// their invulnerability window and raises a counted event; the slice that adds
// lives reads plyHits and decides what it means. That is the extension point,
// and it is one byte.
.const PLAYER_INVULN_TIME = 100                     // frames, the old value
.const PLAYER_BLINK_MASK  = %00000100               // toggle every 4 frames

// --- geometry ---------------------------------------------------------------
// Y. The mux admission range, adopted UNCHANGED for HW0/HW1.
//
// It is not obviously the right range for these two slots: they are outside the
// multiplexer, so MIN_REUSE_GAP does not apply to them, and their DMA is
// fetched in cycles 57..62 of the PREVIOUS line rather than 0..9 of their own,
// so the bottom aperture split's margin argument is a different calculation.
// A wider range is therefore probably available -- and this slice does not have
// the measurement that would justify it, so it does not take it. 55..226 is
// already 171 pixels of travel, more than the old game's 182 minus the 11 it
// spent below the aperture.
//
// What IS load-bearing at 55: sprite Y is compared against the low byte of the
// raster, so Y=55 matches again at raster 311. exFrame clears $d015 at 250 and
// exHud does not set it until raster 4, so that compare passes with nothing
// enabled. A player allowed above 55 would start eating into that guarantee.
// Stated as literals rather than aliased to MIN_SPRITE_Y / MAX_SPRITE_Y, which
// live in renderer.asm and are not defined yet at this point in the import
// order. renderer.asm asserts the two pairs agree, which is the better place
// for it anyway: sharing the range is a DECISION, and a decision deserves a
// check rather than an alias that hides it.
.const PLAYER_MIN_Y     = 55
.const PLAYER_MAX_Y     = 226

// X. The old game's limits, unchanged: the 24-pixel ship just touches the left
// and right side borders, which are NOT opened (only the vertical border is),
// so it slides under the border edge rather than past it.
.const PLAYER_MIN_X     = 23
.const PLAYER_MAX_X     = 321
.const PLAYER_START_X   = 160
.const PLAYER_START_Y   = 220

.if (PLAYER_START_Y < PLAYER_MIN_Y || PLAYER_START_Y > PLAYER_MAX_Y) {
    .error "the player start Y is outside its own bounds"
}
.if (PLAYER_MAX_X > 511) { .error "player X must fit nine bits" }

// --- joystick port 2, CIA1 $dc00, ACTIVE LOW --------------------------------
.const JOY_UP    = %00000001
.const JOY_DOWN  = %00000010
.const JOY_LEFT  = %00000100
.const JOY_RIGHT = %00001000
.const JOY_FIRE  = %00010000
.const JOY_MASK  = %00011111

// ===========================================================================
// State. Outside VIC bank 0, with everything else the main thread owns.
// ===========================================================================
* = $c520 "player state"

// --- logical state ----------------------------------------------------------
// Deliberately small. There is no velocity because the behaviour being
// preserved has none, and no explosion/blink/lives state because this slice
// does not have those systems yet -- they arrive with the code that uses them.
plyX:        .byte <PLAYER_START_X       // 9-bit screen X, low byte
plyXHi:      .byte >PLAYER_START_X       // ...and bit 8
plyY:        .byte PLAYER_START_Y
plyVisible:  .byte 1                     // 0 hides the ship without changing its
                                         // position: the shape respawn blink and
                                         // the post-death hold will both need

// Frames of muzzle flash left. Written by src/weapon.asm when a volley
// resolves, counted down there too, and read by playerEmit below -- the ship's
// ART is player presentation, so the weapon says "I fired" and the player
// decides what that looks like.
plyMuzzle:   .byte 0

// Frames of invulnerability left. NON-ZERO IS THE WHOLE OF "cannot be hit":
// src/ebullet.asm refuses to test a projectile against the ship while this is
// set, so a single collision cannot be re-applied on the frames that follow
// it, and neither can any other projectile in flight.
//
// It starts at ZERO and nothing but a hit makes it non-zero. That matters more
// than it looks: while it runs the ship blinks, and a blink is a presentation
// change, and a presentation change republishes the schedule. A player who
// booted invulnerable would rebuild every fourth frame for two seconds without
// touching the stick, which is exactly the property tests/test_slice_a.py
// exists to protect.
plyInvuln:   .byte 0

// Hits taken, saturating. THE EVENT A LIVES SYSTEM WILL CONSUME, and the only
// thing this slice publishes about damage. Nothing reads it yet.
plyHits:     .byte 0

// 1 = the presentation block changed since the builder last consumed it, so
// this frame must rebuild and republish. Cleared by the game frame that acts on
// it. With a stationary player and no fixture, NOTHING is rebuilt and the
// adopted CURRENT block simply keeps being read -- which is exactly the
// property the static regression fixtures rely on.
plyDirty:    .byte 1                     // start dirty: the boot build publishes

// --- input ------------------------------------------------------------------
// The live joystick sample, active low, as read from $dc00.
joyState:    .byte JOY_MASK              // all lines high = nothing pressed

// Non-zero: readInput leaves joyState alone, so a test can drive the player
// without simulating keyboard or joystick input at the host. The same
// affordance, and the same reason, as `fixtureIndex` being pokeable and
// `pinFine` holding the scroll phase: an automated run must be able to reach a
// state a human reaches with their hands.
joyHold:     .byte 0

// --- the presentation block -------------------------------------------------
// What HW0 and HW1 must look like, and NOTHING about why. The renderer copies
// this whole block; it never reads plyX, plyVisible or joyState.
//
// It is ONE CONTIGUOUS ARRAY on purpose: playerEmit compares the freshly built
// block against the copy the builder last took, so a later slice can change a
// pointer, a colour or the enable mask without having to remember to set a
// dirty flag. The block is the contract, and the block is what is compared.
plyPres:
plyPresX0:     .byte 0                   // HW0 X low byte
plyPresY0:     .byte 0
plyPresPtr0:   .byte 0
plyPresCol0:   .byte 0
plyPresX1:     .byte 0                   // HW1 X low byte
plyPresY1:     .byte 0
plyPresPtr1:   .byte 0
plyPresCol1:   .byte 0
plyPresEnable: .byte 0                   // $d015 bits 0/1 ONLY
plyPresD010:   .byte 0                   // $d010 bits 0/1 ONLY
plyPresEnd:
.const PLY_PRES_BYTES = 10
.if (plyPresEnd - plyPres != PLY_PRES_BYTES) {
    .error "PLY_PRES_BYTES does not match the presentation block"
}

// The copy the builder last consumed. Compared, never published.
plyPub:      .fill PLY_PRES_BYTES, 0

playerStateEnd:
// $c540, NOT $c600. The P3 fixture data does begin at $c600, but src/scroll.asm
// puts the scroll state at $c540 and it is this block that would reach it
// first -- so the old guard was checking a boundary eighty bytes past the one
// that actually binds. Found while adding two bytes here, with four left.
.if (playerStateEnd > $c540) { .error "the player state has grown into the scroll state at $c540" }

// ===========================================================================
// The ship, converted from the old game's multicolour art at assembly time.
// ===========================================================================
// c64Shooter/src/main.asm `playerSprite` is a MULTICOLOUR bitmap and this
// engine has no multicolour: $d01c is forced to zero by exHud and again by
// exHandoff, so every sprite is hires. Rather than redraw the ship by eye, the
// original bytes are kept verbatim below and split into two hires layers by a
// rule stated once, here, in code:
//
//     multicolour pair 10  -> LAYER 0, the hull        (its per-sprite colour)
//     multicolour pairs 01 and 11 -> LAYER 1, the trim ($D025 / $D026 detail)
//     pair 00 -> transparent in both
//
// A multicolour pixel is two hires pixels wide and sits at the same bit
// position, so the split preserves the SHAPE exactly -- same 24x21 cell, same
// silhouette, same proportions. The two layers are disjoint by construction
// (each pair goes to exactly one of them), which is what lets them be drawn as
// two co-located sprites without either punching a hole in the other.
//
// The visible result: a light-blue hull with a continuous light-grey stripe
// from the nose, down the fuselage, out through the two exhaust flames. The
// exhausts are the two rows that exist ONLY on the overlay, so a frame that
// lost HW1 is obvious at a glance rather than subtly wrong.
.var playerMC = List()
.eval playerMC.add($00,$28,$00,  $00,$28,$00,  $00,$aa,$00,  $00,$be,$00)
.eval playerMC.add($02,$be,$80,  $02,$be,$80,  $0a,$be,$a0,  $0a,$96,$a0)
.eval playerMC.add($2a,$96,$a8,  $2a,$96,$a8,  $aa,$96,$aa,  $aa,$96,$aa)
.eval playerMC.add($2a,$96,$a8,  $2a,$aa,$a8,  $0a,$96,$a0,  $0a,$96,$a0)
.eval playerMC.add($0a,$82,$a0,  $02,$82,$80,  $02,$82,$80,  $03,$c3,$c0)
.eval playerMC.add($03,$c3,$c0)

.if (playerMC.size() != 21 * 3) { .error "the player source bitmap must be 21 rows of 3 bytes" }

// c64Shooter's playerFireSprite, also verbatim. It differs from the resting
// ship on rows 0, 1 and 2 only -- four muzzle blocks at the nose, two per
// cannon -- and every differing pixel is multicolour pair 10, the hull. That is
// why only the hull layer is emitted from it below.
.var playerFireMC = List()
.eval playerFireMC.add($08,$28,$20,  $02,$28,$80,  $08,$aa,$20,  $00,$be,$00)
.eval playerFireMC.add($02,$be,$80,  $02,$be,$80,  $0a,$be,$a0,  $0a,$96,$a0)
.eval playerFireMC.add($2a,$96,$a8,  $2a,$96,$a8,  $aa,$96,$aa,  $aa,$96,$aa)
.eval playerFireMC.add($2a,$96,$a8,  $2a,$aa,$a8,  $0a,$96,$a0,  $0a,$96,$a0)
.eval playerFireMC.add($0a,$82,$a0,  $02,$82,$80,  $02,$82,$80,  $03,$c3,$c0)
.eval playerFireMC.add($03,$c3,$c0)

.if (playerFireMC.size() != 21 * 3) { .error "the firing source bitmap must be 21 rows of 3 bytes" }

// Which multicolour pair values a layer keeps, as a bit per pair value.
.const PLY_SEL_HULL = (1 << 2)                      // pair 10
.const PLY_SEL_TRIM = (1 << 1) | (1 << 3)           // pairs 01 and 11

// One multicolour byte (four pairs) to one hires byte, keeping only the pairs
// `sel` names and expanding each kept pair to both of its pixels.
.function plyLayerByte(b, sel) {
    .var v = 0
    .for (var p = 0; p < 4; p++) {
        .var sh = 6 - 2 * p
        .var pair = (b >> sh) & 3
        .if (pair != 0 && ((sel >> pair) & 1) != 0) { .eval v = v | (3 << sh) }
    }
    .return v
}

// One emitter, three blocks: resting hull, trim, firing hull. The trim block
// serves both the resting and the firing ship because the two source bitmaps
// have identical trim pixels -- asserted below rather than assumed.
.var plyBlocks = List()
.eval plyBlocks.add(List().add(0, PLY_SEL_HULL))    // $d6  resting hull
.eval plyBlocks.add(List().add(0, PLY_SEL_TRIM))    // $d7  trim, shared
.eval plyBlocks.add(List().add(1, PLY_SEL_HULL))    // $d8  firing hull

.for (var r = 0; r < 21 * 3; r++) {
    .if (plyLayerByte(playerMC.get(r), PLY_SEL_TRIM)
         != plyLayerByte(playerFireMC.get(r), PLY_SEL_TRIM)) {
        .error "the firing bitmap changes a TRIM pixel, so it needs its own trim block"
    }
}

* = PLAYER_SPRITES "player bitmaps"
playerBitmaps:
.for (var b = 0; b < PLAYER_BLOCKS; b++) {
    .var src = plyBlocks.get(b).get(0)
    .var sel = plyBlocks.get(b).get(1)
    .for (var r = 0; r < 21; r++) {
        .for (var c = 0; c < 3; c++) {
            .var byte = (src == 0) ? playerMC.get(r * 3 + c) : playerFireMC.get(r * 3 + c)
            .byte plyLayerByte(byte, sel)
        }
    }
    .byte $00                                       // 64th padding byte
}
playerBitmapsEnd:
.if (playerBitmapsEnd - playerBitmaps != PLAYER_BLOCKS * 64) {
    .error "player bitmaps must be exactly PLAYER_BLOCKS x 64 bytes"
}

// ===========================================================================
// Code. MAIN THREAD ONLY. Never called from an interrupt.
// ===========================================================================
// ===========================================================================
// Code. MAIN THREAD ONLY, and therefore OUTSIDE VIC BANK 0.
// ===========================================================================
// $4000 is plain RAM under the $01 = $35 the renderer installs, and the VIC --
// locked to bank 0, $0000-$3fff -- cannot reach it at all.
//
// That is the point. Bank 0 is 16 KB and every byte of it is contended: two
// screen pages, the sprite bitmaps, the HUD's pool, the player's, the blank
// charset, and a real character set when terrain arrives. None of this routine
// is ever fetched by the VIC, so spending bank-0 space on it would be paying
// the scarcest resource in the machine for nothing. The engine already draws
// this line for its STATE (every array lives at $c000 and above); this is the
// same line drawn for main-thread CODE, and the game systems that follow --
// weapons, enemies, waves, collision -- belong on this side of it too.
//
// $4000-$bfff is otherwise untouched, and the PRG already spans $0801-$cfda, so
// this costs nothing on disk either.
// ===========================================================================
* = $4000 "player code"

// ---------------------------------------------------------------------------
// playerInit — the ship at its start position, visible, and dirty.
// ---------------------------------------------------------------------------
playerInit:
    lda #<PLAYER_START_X
    sta plyX
    lda #>PLAYER_START_X
    sta plyXHi
    lda #PLAYER_START_Y
    sta plyY
    lda #1
    sta plyVisible
    sta plyDirty
    lda #0
    sta plyMuzzle
    lda #JOY_MASK
    sta joyState                        // nothing pressed until the first read
    lda #0
    sta joyHold
    ldx #PLY_PRES_BYTES - 1
!clear:
    sta plyPub,x                        // no published block yet, so the first
    dex                                 // emit is guaranteed to report a change
    bpl !clear-
    rts

// ---------------------------------------------------------------------------
// readInput — sample joystick port 2. THE ONLY $dc00 READ IN THE GAME.
//
// Port A of CIA1 is the keyboard column drive AND joystick 2; reading it
// returns the pin states. Nothing in this program drives $dc01 (port B is left
// as an input), so no key can pull a column low and be mistaken for a stick
// direction. The fixture-select key scan DOES write $dc00, which is why it is
// behind FIXTURE_KEYS and not in the production path.
// ---------------------------------------------------------------------------
readInput:
    lda joyHold
    bne !held+
    lda $dc00
    and #JOY_MASK
    sta joyState
!held:
    rts

// ---------------------------------------------------------------------------
// playerTick — one frame of movement. joyState in, plyX/plyXHi/plyY out.
//
// ONE PIXEL PER FRAME PER AXIS, which is what the old game did: c64Shooter's
// updatePlayer has a `dec`/`inc` per direction and no velocity state anywhere.
// Diagonals therefore move one pixel on each axis, exactly as they did.
//
// The bounds are applied as a TOTAL CLAMP after the moves rather than as the
// old pre-move refusal. Same behaviour at the edges, and it also means no
// sequence of writes to plyX/plyY -- by a later system, or by a test poking the
// machine -- can leave the ship outside the range the renderer is promised.
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// playerTakeHit — what being hit MEANS. Called by src/ebullet.asm when a
// projectile's box overlaps the ship's.
//
// The projectile file owns the geometry and the player owns the consequence,
// which is the same division src/collision.asm and src/turrets.asm already
// use for the shot going the other way.
//
// IDEMPOTENT WITHIN A WINDOW. The caller already refuses to test anything
// while plyInvuln is set, so this cannot normally be re-entered -- and it
// checks anyway, because "one projectile cannot damage the player twice" is
// the property, not "the caller is careful".
// ---------------------------------------------------------------------------
playerTakeHit:
    lda plyInvuln
    bne !done+
    lda #PLAYER_INVULN_TIME
    sta plyInvuln
    lda plyHits                         // saturating: that the ship was hit is
    cmp #$ff                            // the event; the exact count past 255
    beq !done+                          // is not
    inc plyHits
!done:
    rts

// ---------------------------------------------------------------------------
// playerInvulnTick — run the invulnerability window down, and blink while it
// runs. Called first thing in playerTick.
//
// EIGHT CYCLES WHEN THE SHIP IS NOT INVULNERABLE, which is almost always.
//
// The blink is the whole of the feedback, and it is deliberately the cheapest
// feedback that exists: plyVisible already drives plyPresEnable, so the ship
// disappearing and reappearing costs nothing the presentation block did not
// already do. It republishes on each toggle -- every fourth frame for two
// seconds -- which is the same republication a moving ship causes anyway.
// ---------------------------------------------------------------------------
playerInvulnTick:
    lda plyInvuln
    bne !running+
    rts
!running:
    dec plyInvuln
    lda plyInvuln
    beq !solid+                         // the window just ended: solid again
    and #PLAYER_BLINK_MASK
    bne !solid+
    lda #0                              // four frames dark, four frames lit
    sta plyVisible
    rts
!solid:
    lda #1
    sta plyVisible
    rts

playerTick:
    jsr playerInvulnTick

    lda plyX                            // remember the position we came in with,
    sta pt_x                            // so the dirty test below is exact
    lda plyXHi
    sta pt_xhi
    lda plyY
    sta pt_y

    lda joyState
    and #JOY_UP
    bne !notUp+
    dec plyY
!notUp:
    lda joyState
    and #JOY_DOWN
    bne !notDown+
    inc plyY
!notDown:

    lda joyState
    and #JOY_LEFT
    bne !notLeft+
    lda plyX                            // 9-bit decrement; the clamp below is
    bne !decLo+                         // what catches a borrow past zero
    dec plyXHi
!decLo:
    dec plyX
!notLeft:
    lda joyState
    and #JOY_RIGHT
    bne !notRight+
    inc plyX
    bne !notRight+
    inc plyXHi
!notRight:

    jsr playerClampX
    jsr playerClampY

    lda plyX                            // did anything actually move?
    cmp pt_x
    bne !moved+
    lda plyXHi
    cmp pt_xhi
    bne !moved+
    lda plyY
    cmp pt_y
    beq !done+
!moved:
    lda #1
    sta plyDirty
!done:
    rts

// X clamped to PLAYER_MIN_X..PLAYER_MAX_X as a 16-bit value.
//
// THE SIGN TEST COMES FIRST AND IS WHAT MAKES THE CLAMP TOTAL. A step left from
// X=0 leaves plyXHi = $ff, which as an unsigned 16-bit number is far ABOVE the
// maximum and would clamp to the RIGHT edge -- the ship teleporting across the
// screen for one frame. Testing bit 7 first sends that case to the low bound
// where it belongs.
playerClampX:
    lda plyXHi
    bmi !low+                           // $80..$ff: underflowed past zero
    cmp #>PLAYER_MIN_X
    bcc !low+
    bne !hiCheck+
    lda plyX
    cmp #<PLAYER_MIN_X
    bcc !low+
!hiCheck:
    lda plyXHi
    cmp #>PLAYER_MAX_X
    bcc !done+
    bne !high+
    lda plyX
    cmp #<PLAYER_MAX_X + 1
    bcc !done+
!high:
    lda #<PLAYER_MAX_X
    sta plyX
    lda #>PLAYER_MAX_X
    sta plyXHi
    rts
!low:
    lda #<PLAYER_MIN_X
    sta plyX
    lda #>PLAYER_MIN_X
    sta plyXHi
!done:
    rts

playerClampY:
    lda plyY
    cmp #PLAYER_MIN_Y
    bcs !notLow+
    lda #PLAYER_MIN_Y
    sta plyY
    rts
!notLow:
    cmp #PLAYER_MAX_Y + 1
    bcc !done+
    lda #PLAYER_MAX_Y
    sta plyY
!done:
    rts

// ---------------------------------------------------------------------------
// playerEmit — logical state to the presentation block, and the dirty test.
//
// The two layers are CO-LOCATED BY CONSTRUCTION: both X values and both Y
// values are written from the same plyX/plyY in the same pass, so they cannot
// drift apart by one frame the way two independently scheduled sprites could.
// That was the one property the old three-layer experiment went to some trouble
// to guarantee, and here it is free.
// ---------------------------------------------------------------------------
playerEmit:
    lda plyX
    sta plyPresX0
    sta plyPresX1
    lda plyY
    sta plyPresY0
    sta plyPresY1
    // THE MUZZLE FLASH IS A PRESENTATION CHOICE, MADE HERE.
    //
    // The weapon sets plyMuzzle and knows nothing else about how a shot looks.
    // Swapping the base pointer and the hull colour for those frames goes out
    // through the block the renderer already publishes, so firing costs no new
    // sprite, no new slot and not one line of renderer change -- and the block
    // compare at the bottom of this routine notices the change by itself, which
    // is exactly the property it was written for in Slice A.
    ldx #PLAYER_PTR_BASE
    ldy #PLAYER_COL_BASE
    lda plyMuzzle
    beq !resting+
    ldx #PLAYER_PTR_FIRE
    ldy #PLAYER_COL_MUZZLE
!resting:
    stx plyPresPtr0
    sty plyPresCol0
    lda #PLAYER_PTR_TRIM
    sta plyPresPtr1
    lda #PLAYER_COL_TRIM
    sta plyPresCol1

    // $d010. Both layers share one X, so their two bits always agree -- but
    // both are written from the same test rather than one being copied from the
    // other, so an overlay that ever gains an X offset changes one line here.
    lda #0
    ldy plyXHi
    beq !noMsb+
    lda #PLAYER_SLOT_MASK
!noMsb:
    sta plyPresD010

    lda #0
    ldy plyVisible
    beq !hidden+
    lda #PLAYER_SLOT_MASK
!hidden:
    sta plyPresEnable

    // ---- did the block change? ------------------------------------------
    ldx #PLY_PRES_BYTES - 1
!same:
    lda plyPres,x
    cmp plyPub,x
    bne !changed+
    dex
    bpl !same-
    rts                                 // identical: nothing to rebuild
!changed:
    ldx #PLY_PRES_BYTES - 1
!copy:
    lda plyPres,x
    sta plyPub,x
    dex
    bpl !copy-
    lda #1
    sta plyDirty
    rts

// playerTick locals. Main thread only.
pt_x:     .byte 0
pt_xhi:   .byte 0
pt_y:     .byte 0

// ---------------------------------------------------------------------------
// SEGMENT GROWTH GUARD. Nothing is allocated above this yet, so the bound is a
// generous one -- but it is stated, because an unbounded segment in a file that
// uses explicit `* =` placement is how the previous project discovered its
// overlaps at run time instead of at build time.
// ---------------------------------------------------------------------------
.if (* > $4400) {
    .error "the player code has outgrown its $4000 segment"
}
