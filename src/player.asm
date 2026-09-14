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
// HW0/HW1 ARE NOT IN THE MUX. docs/ENGINE_CONTRACT.md §2 reserves them, and
// that is honoured literally: the player never enters logY/logX, is never
// sorted, never occupies a schedule entry and never competes for a slot.
// MUX_FIRST_SLOT stays 2 and MAX_SCHED stays 24.
//
// THE SHIP IS TWO CO-LOCATED HIRES SPRITES, a hull and a trim layer, because
// $d01c is forced to zero engine-wide and one hires sprite is one colour. Two
// reserved slots buy the second colour that the mux enemies cannot have.
//
// MOVEMENT IS ONE PIXEL PER FRAME PER AXIS, read from joystick port 2, with no
// acceleration and no momentum -- there is no velocity state in this file, by
// design.
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
// The muzzle flash is a HULL-ONLY change: the firing bitmap differs from the
// resting one on rows 0-2 and nowhere else, and every differing pixel is a hull
// pixel. So the trim layer keeps PLAYER_PTR_TRIM and only the base pointer
// moves, which costs ONE extra 64-byte block rather than two.
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
// Two hires layers carry two colours. The silhouette is what a player
// recognises and it is preserved exactly; the internal shading a multicolour
// ship would have had is not available at all with $d01c forced to zero.
.const PLAYER_COL_BASE  = 14                        // light blue hull
.const PLAYER_COL_TRIM  = 15                        // light grey centre stripe
                                                    // and exhaust
// The HULL flashes red for the muzzle window and the trim keeps its colour:
// flashing both layers reads as the whole ship changing colour rather than as
// a gun firing.
.const PLAYER_COL_MUZZLE = 2                        // red

// --- the cannons ------------------------------------------------------------
// Horizontal ray offsets from the player's sprite X. They are not arbitrary:
// the firing bitmap's muzzle pixels sit at exactly these two columns, which is
// how the art and the hitscan stay agreed about where the guns are.
.const PLAYER_CANNON_L  = 4
.const PLAYER_CANNON_R  = 19
.const PLAYER_MUZZLE_TIME = 3                       // frames the flash is held

// --- taking a hit -----------------------------------------------------------
// A hit costs the player an invulnerability window, during which the ship
// blinks and projectiles pass through it, and raises a counted event. There is
// no state machine, no explosion, no life counter and no game over: anything
// that adds lives reads plyHits and decides what a hit MEANS. That one byte is
// the extension point.
.const PLAYER_INVULN_TIME = 100                     // frames
.const PLAYER_BLINK_MASK  = %00000100               // toggle every 4 frames

// --- geometry ---------------------------------------------------------------
// Y. The same range the mux admits on, adopted for HW0/HW1 -- 171 pixels of
// travel. A wider range may well be available to these two slots, since they
// are outside the multiplexer (MIN_REUSE_GAP does not apply) and their DMA is
// fetched in cycles 57..62 of the PREVIOUS line rather than 0..9 of their own,
// which makes the bottom split's margin a different calculation. It is not
// taken without the measurement that would justify it.
//
// WHAT IS LOAD-BEARING AT 55: sprite Y is compared against the low byte of the
// raster, so Y=55 matches again at raster 311. exFrame clears $d015 at 250 and
// exHud does not set it until raster 4, so that second compare passes with
// nothing enabled. Allowing the player above 55 would eat into that guarantee.
//
// Stated as literals rather than aliased to MIN_SPRITE_Y / MAX_SPRITE_Y, which
// are not defined yet at this point in the import order. renderer.asm asserts
// the two pairs agree, which is the better place for it anyway: sharing a
// range is a DECISION and deserves a check rather than an alias that hides it.
.const PLAYER_MIN_Y     = 55
.const PLAYER_MAX_Y     = 226

// X. The 24-pixel ship just touches the left and right side borders, which are
// NOT opened (only the vertical border is), so it slides under the border edge
// rather than past it.
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
// Deliberately small: position, the two timers that change how the ship looks,
// and a hit tally. There is no velocity because the movement model has none.
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
// than it looks: while it runs the ship blinks, a blink is a presentation
// change, and a presentation change republishes the schedule. A ship that
// booted invulnerable would rebuild every fourth frame for two seconds without
// the stick being touched.
plyInvuln:   .byte 0

// Hits taken, saturating. The only thing published about damage, and the hook
// a lives system would read. Nothing reads it yet.
plyHits:     .byte 0

// 1 = the presentation block changed since the builder last consumed it, so
// this frame must rebuild and republish. Cleared by the game frame that acts
// on it. With a stationary ship and an empty pool NOTHING is rebuilt, and the
// adopted CURRENT block simply keeps being read.
plyDirty:    .byte 1                     // start dirty: the boot build publishes

// --- input ------------------------------------------------------------------
// The live joystick sample, active low, as read from $dc00.
joyState:    .byte JOY_MASK              // all lines high = nothing pressed

// Non-zero: readInput leaves joyState alone, so a test can drive the ship by
// poking joyState without simulating input at the host. An automated run must
// be able to reach a state a human reaches with their hands.
joyHold:     .byte 0

// --- the presentation block -------------------------------------------------
// What HW0 and HW1 must look like, and NOTHING about why. The renderer copies
// this whole block; it never reads plyX, plyVisible or joyState.
//
// It is ONE CONTIGUOUS ARRAY on purpose: playerEmit compares the freshly built
// block against the copy the builder last took, so changing a pointer, a
// colour or the enable mask raises the dirty flag by itself and nobody has to
// remember to. The block is the contract, and the block is what is compared.
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
.if (playerStateEnd > $c540) { .error "the player state has grown into the scroll state at $c540" }

// ===========================================================================
// The ship: multicolour source art, split into two hires layers at ASSEMBLY
// time.
// ===========================================================================
// $d01c is forced to zero by exHud and again by exHandoff, so every sprite is
// hires. The source bitmaps below are multicolour and are split by one rule:
//
//     multicolour pair 10          -> LAYER 0, the hull
//     multicolour pairs 01 and 11  -> LAYER 1, the trim
//     pair 00                      -> transparent in both
//
// A multicolour pixel is two hires pixels wide at the same bit position, so
// the split preserves the SHAPE exactly -- same 24x21 cell, same silhouette,
// same proportions. The two layers are disjoint by construction (each pair
// goes to exactly one), which is what lets them be drawn as two co-located
// sprites without either punching a hole in the other.
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

// The firing ship. It differs from the resting one on rows 0, 1 and 2 only --
// four muzzle blocks at the nose, two per cannon -- and every differing pixel
// is pair 10, the hull, which is why only a hull layer is emitted from it.
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
// Code. MAIN THREAD ONLY, never called from an interrupt, and therefore
// OUTSIDE VIC BANK 0.
// ===========================================================================
// $4000 is plain RAM under the $01 = $35 the renderer installs, and the VIC --
// locked to bank 0, $0000-$3fff -- cannot reach it at all.
//
// That is the rule the whole engine follows: NOTHING LIVES IN VIC BANK 0
// UNLESS THE VIC READS IT. Bank 0 is 16 KB and every byte is contended by two
// screen pages, the sprite bitmaps, the HUD's pool, the player's, the terrain
// charset window and the blank charset. Main-thread code and state are never
// fetched by the VIC, so they live above $4000 with the rest of the game
// systems.
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
// direction.
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

// ---------------------------------------------------------------------------
// playerTick — one frame of movement. joyState in, plyX/plyXHi/plyY out, and
// plyDirty raised if the ship actually moved.
//
// ONE PIXEL PER FRAME PER AXIS with no velocity state, so a diagonal moves one
// pixel on each axis.
//
// The bounds are applied as a TOTAL CLAMP after the moves rather than as a
// refusal before them, so no sequence of writes to plyX/plyY -- by another
// system, or by a test poking the machine -- can leave the ship outside the
// range the renderer is promised.
// ---------------------------------------------------------------------------
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
// drift apart by a frame the way two independently scheduled sprites could.
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
    // sprite, no new slot and no renderer change -- and the block compare at
    // the bottom of this routine notices it without being told.
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
// SEGMENT GROWTH GUARD. The bound is generous, since nothing is allocated
// immediately above -- but an explicit `* =` segment without one turns an
// overlap into a run-time mystery instead of a build error.
// ---------------------------------------------------------------------------
.if (* > $4400) {
    .error "the player code has outgrown its $4000 segment"
}
