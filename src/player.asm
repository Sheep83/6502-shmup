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
// THE SHIP IS ONE MULTICOLOUR SPRITE on HW0, with the muzzle flash a second
// multicolour sprite on HW1. Multicolour is the artwork's native mode -- three
// colours in twelve double-width pixels -- and is now what EVERY gameplay
// sprite uses; the player is no longer special in that respect. What the two
// reserved slots still buy is a second sprite's worth of art co-located with
// the first, which is how the flash can be drawn at the guns without costing a
// mux slot.
//
// MOVEMENT IS ONE PIXEL PER FRAME PER AXIS, read from joystick port 2, with no
// acceleration and no momentum -- there is no velocity state in this file, by
// design.
// ===========================================================================

// --- the two reserved hardware slots ---------------------------------------
// Bit per slot, for $d015 and $d010. The renderer composes this into the
// complete values it writes; nothing here touches a register.
.const PLAYER_SLOT_MASK = %00000011                 // HW0 | HW1
.const PLAYER_HW0_BIT   = %00000001                // the craft alone: HW1 is
                                                   // only enabled while the
                                                   // muzzle flash is running

// --- bitmaps ----------------------------------------------------------------
// SIX 64-byte blocks in the reclaimed $2000 VIC0 run: five banking frames and
// one blank. The run is free capacity the bank surgery left behind, it is
// 64-byte aligned at its start, and it is nowhere near the HUD pool, the
// enemy art or the clip scratch -- so the pointers ($80..$85) are also
// unmistakably the player's when read out of a debugger.
//
// FIVE FRAMES, HARD LEFT TO HARD RIGHT, IN BANK ORDER. Keeping them adjacent
// and ordered is what lets playerEmit turn a signed lean into a pointer with
// one add and no table.
.const PLAYER_SPRITES   = $2000
.const PLAYER_ENGINE_FRAMES = 3                     // flame full, small, out
.const PLAYER_BANK_FRAMES   = 5                     // hard left .. hard right
.const PLAYER_BLOCKS    = PLAYER_BANK_FRAMES * PLAYER_ENGINE_FRAMES + 1
.const PLAYER_SPRITES_END = PLAYER_SPRITES + PLAYER_BLOCKS * 64   // $2400
.const PLAYER_PTR_FIRST = PLAYER_SPRITES / 64       // $80
// BANK-MAJOR: pointer = FIRST + bank * PLAYER_ENGINE_FRAMES + engine, with
// bank 0..4 running hard left to hard right. Laying the grid out this way is
// what lets playerEmit turn a signed lean and an engine phase into a pointer
// with a shift and two adds.
.const PLAYER_PTR_NEUTRAL = PLAYER_PTR_FIRST + 2 * PLAYER_ENGINE_FRAMES
// HW1 DRAWS NOTHING, and points at 64 bytes of zero to do it. The craft is a
// single multicolour sprite -- see the art note below -- so the second
// reserved slot has no content of its own for the first time. It is kept
// ENABLED and co-located rather than switched off, because every existing
// invariant that mentions the player names both slots: PLAYER_SLOT_MASK, the
// $d015 composition, the $d010 pair and the renderer's reservation. Leaving
// the pair intact keeps this a presentation change and nothing else, and
// leaves HW1 free for a muzzle-flash or detail overlay later.
.const PLAYER_PTR_BLANK = PLAYER_PTR_FIRST + PLAYER_BLOCKS - 1

// --- the muzzle flash, on HW1 ------------------------------------------------
// FIVE blocks in the next free run above the ship's, one per banking attitude:
// the supplied artwork leans its streak with the craft, so the flash is chosen
// by the SAME bank index the hull is and needs no per-bank transformation of
// its own. There is deliberately no engine/animation axis here -- the flash is
// two frames long and both use one bitmap.
.const PLAYER_FLASH_SPRITES = PLAYER_SPRITES_END        // $2400
.const PLAYER_FLASH_FRAMES  = PLAYER_BANK_FRAMES        // 5, one per attitude
.const PLAYER_FLASH_END     = PLAYER_FLASH_SPRITES + PLAYER_FLASH_FRAMES * 64
.const PLAYER_PTR_FLASH     = PLAYER_FLASH_SPRITES / 64 // $90

.if ((PLAYER_FLASH_SPRITES & 63) != 0) { .error "the muzzle flash blocks must be 64-byte aligned" }
.if (PLAYER_FLASH_SPRITES < PLAYER_SPRITES_END) { .error "the muzzle flash overlaps the ship's own frames" }
.if (PLAYER_FLASH_END > SCREEN_B) { .error "the muzzle flash runs past the free $2000 run into screen page B" }

.if ((PLAYER_SPRITES & 63) != 0) { .error "the player sprite block must be 64-byte aligned" }
.if (PLAYER_SPRITES_END > SCREEN_B) { .error "player bitmaps run past the free $2000 run into screen page B" }
.if (PLAYER_PTR_FIRST < HUD_PTR_FIRST + HUD_BLOCKS && PLAYER_PTR_FIRST + PLAYER_BLOCKS > HUD_PTR_FIRST) {
    .error "player and HUD sprite pointers overlap"
}

// --- colours ----------------------------------------------------------------
// THE CRAFT IS ONE MULTICOLOUR SPRITE, so it carries three colours at once:
// two shared registers and its own. That is the artwork's native mode rather
// than a choice -- see the art note below.
//
// TWO OF THOSE THREE ARE NOT THE PLAYER'S. $d025 and $d026 are one register
// each for the whole machine, and every gameplay sprite is multicolour now, so
// the craft shares its outline and its highlight with enemies and hostile
// projectiles alike. They are SPR_MC_DARK / SPR_MC_LIGHT in src/main.asm and
// are written once there; this file neither owns nor sets them.
//
// What the craft keeps for itself is pair 10, its own $d027 -- the hull.
.const PLAYER_COL_SHIP   = 14                       // $d027, per sprite: the
                                                    // light-blue hull
.const PLAYER_COL_BLANK  = 0                        // HW1 draws nothing

// THE HULL NO LONGER REDDENS WHEN THE GUN FIRES. It used to: firing swapped
// $d027 to red for PLAYER_MUZZLE_TIME frames, so the whole craft changed colour
// on every shot. With the supplied muzzle-flash artwork now drawn at the guns
// on HW1, that hull-wide tint was reading as the ship being hit rather than
// firing, and it has been removed at the author's request. The gun flashes;
// the craft does not.
//
// plyMuzzle, PLAYER_MUZZLE_TIME and the weapon's write to them went with it --
// nothing else read that timer, so leaving it would have left a counter ticking
// down for no reader. The flash on HW1 runs off shotFired and plyFlash and is
// entirely separate; see below.

// --- the muzzle flash's colour ----------------------------------------------
// The flash artwork uses only bit pairs 10 and 11: pair 11 is the shared WHITE
// ($d026, SPR_MC_LIGHT) -- the white-hot core -- and pair 10 is HW1's OWN
// colour ($d028), which nothing else reads. So the flash is a write to one
// private register, and the shared pair that the craft, the enemies and the
// projectiles all depend on is never touched.
//
// Pair 01 ($d025, the shared outline) does not appear in the artwork at all;
// asserted against the real bytes in tests/test_player_ship.py rather than
// taken on trust.
//
// ONE COLOUR, HELD FOR BOTH FRAMES. An earlier version pulsed orange then red
// across the two frames. The supplied bold artwork draws its own hot core in
// the shared white and asks for a flat red underneath it, so the pulse is gone
// and $d028 holds red for the whole flash. This is HW1's private register: the
// craft's own $d027 is not touched by firing at all any more.
.const PLAYER_COL_FLASH   = 2                       // red, both frames
// --- the death fireball's timing -------------------------------------------
// SIX PAL FRAMES PER ART FRAME, eight art frames: 48 frames, 0.96 s of
// explosion. The hold is a separate counter from the frame index rather than
// one countdown divided by six, because a divide by six on a 6502 costs more
// than the byte it would save -- and because "which frame" and "how long it
// has been up" are two different facts that a later tuning pass will want to
// change independently.
.const PLAYER_BOOM_HOLD   = 6                      // PAL frames per art frame

// --- the death fireball's blocks --------------------------------------------
// Declared HERE, with the ship's and the muzzle's, because a sprite's address
// is player presentation and KickAssembler resolves .const strictly in import
// order -- player.asm is parsed long before the artwork file that fills them.
// The bytes, the palette note and the overlap guard against the token bitmap
// live in src/player_boom_art.asm.
//
// $25c0 is the free run between the collectible token's bitmap and screen page
// B: resident player art, sitting with the ship at $2000 and the muzzle at
// $2400 rather than in the level enemy window a level package owns.
.const PLAYER_BOOM_SPRITES = $25c0
.const PLAYER_BOOM_FRAMES  = 8
.const PLAYER_BOOM_END     = PLAYER_BOOM_SPRITES + PLAYER_BOOM_FRAMES * 64
.const PLAYER_PTR_BOOM     = PLAYER_BOOM_SPRITES / 64       // $97
.const PLAYER_COL_BOOM     = 2                              // red, in HW0's own
                                                            // $d027 while it burns
.if ((PLAYER_BOOM_SPRITES & 63) != 0) {
    .error "the fireball blocks must be 64-byte aligned"
}
.if (PLAYER_BOOM_SPRITES < PLAYER_FLASH_END) {
    .error "the fireball overlaps the muzzle flash frames"
}
.if (PLAYER_BOOM_END > SCREEN_B) {
    .error "the fireball runs past the free $2000 run into screen page B"
}

.const PLAYER_FLASH_TIME  = 2                       // visible PAL frames

// How far above the craft HW1 sits. The supplied artwork is drawn for this
// offset and no other: each frame carries TWO flares whose stems end exactly
// one row above a wing-gun barrel of the matching banked craft, measured with
// this lift applied. Change it and the flares leave the guns.
.const PLAYER_FLASH_Y_LIFT = 7

// --- $d01c: the two bits the player owns -------------------------------------
// Bit per sprite, 1 = multicolour. BOTH of the player's slots: HW0 carries the
// craft and HW1 the muzzle flash, and both are authored multicolour.
//
// THIS IS THE PLAYER'S HALF OF $d01c AND NOT THE WHOLE REGISTER. Bits 2..7
// belong to slots the HUD and the gameplay mux time-share, and those two
// owners want different resolutions -- so the renderer composes the complete
// value per raster phase, from this constant plus the mux mask. See
// D01C_HUD_PHASE / D01C_GAMEPLAY in src/renderer.asm; the guard below is what
// keeps this file from reaching past its own two bits into that decision.
//
// HW1's bit is set permanently rather than toggled with the flash: a DISABLED
// sprite's mode is not read by anything, so there is nothing to switch off and
// no frame on which the two could disagree.
.const PLAYER_D01C = %00000011
.if ((PLAYER_D01C & ~PLAYER_SLOT_MASK) != 0) {
    .error "only the player's own reserved slots may be switched to multicolour"
}

// --- banking ----------------------------------------------------------------
// A signed lean, -PLAYER_BANK_MAX (hard left) to +PLAYER_BANK_MAX (hard
// right), which indexes the five frames directly.
//
// WHY A LEAN COUNTER AND NOT THE STICK DIRECTLY. There is no horizontal
// velocity in this game to bank from -- movement is one pixel per frame per
// axis with no acceleration and no momentum (see playerTick), so the stick is
// the only horizontal signal that exists. Reading it straight would snap the
// craft between hard left and hard right on the frame the stick moved, and
// would flicker on a diagonal. The counter walks one stage every
// PLAYER_BANK_RATE frames instead, so the ship rolls into and out of a turn,
// and a stick centred for one frame does not reset it -- which is the
// momentum the movement model does not have, supplied by the presentation
// rather than faked into the physics.
// UNSIGNED 0..4, not a signed lean around zero. Hard left is 0, level flight
// is 2, hard right is 4 -- which is also the frame's row in the bank-major
// grid, so playerEmit multiplies it by three and adds the engine phase with no
// sign handling and no temporary.
.const PLAYER_BANK_LEFT    = 0
.const PLAYER_BANK_NEUTRAL = 2
.const PLAYER_BANK_RIGHT   = PLAYER_BANK_FRAMES - 1     // 4
.const PLAYER_BANK_RATE    = 5                          // frames per stage

// --- the engine flame -------------------------------------------------------
// The three cells of a band differ ONLY in their bottom two rows -- the
// exhaust full, small, then out -- so they are an animation to cycle rather
// than more bank stages. Four frames a step gives a ~12 frame loop, which
// reads as a flicker rather than a strobe and is nowhere near the PAL frame
// rate the brief asked this to stay away from.
.const PLAYER_ENGINE_RATE = 4                       // frames per flame step

// --- the cannons ------------------------------------------------------------
// Horizontal ray offsets from the player's sprite X. They are not arbitrary:
// the firing bitmap's muzzle pixels sit at exactly these two columns, which is
// how the art and the hitscan stay agreed about where the guns are.
.const PLAYER_CANNON_L  = 4
.const PLAYER_CANNON_R  = 19

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

// The muzzle flash sits PLAYER_FLASH_Y_LIFT lines above the craft, and
// playerEmit subtracts without a borrow check. This is what makes that safe.
.if (PLAYER_MIN_Y < PLAYER_FLASH_Y_LIFT) {
    .error "the player can fly high enough that the muzzle flash Y would borrow"
}

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
// $c519 AND NOT $c520. The enemy state above ends at $c518 -- it shrank when
// src/waves.asm took over spawning and left its cursor and timer behind -- so
// six bytes sat unused between the two blocks. The banking and engine state
// this slice adds spends two of them.
//
// PINNED, NOT DERIVED. It would be tidier-looking to write `* = enyStateEnd`
// and never think about it again, and that is exactly the pattern that moved
// the enemy BITMAP across VIC bank 0 when the player's art moved (see
// src/enemy.asm). The guard below is what keeps the two honest instead.
* = $c51a "player state"

// --- logical state ----------------------------------------------------------
// Deliberately small: position, the two timers that change how the ship looks,
// and a hit tally. There is no velocity because the movement model has none.
plyX:        .byte <PLAYER_START_X       // 9-bit screen X, low byte
plyXHi:      .byte >PLAYER_START_X       // ...and bit 8
plyY:        .byte PLAYER_START_Y
plyVisible:  .byte 1                     // 0 hides the ship without changing its
                                         // position: the shape respawn blink and
                                         // the post-death hold will both need

// --- banking presentation ---------------------------------------------------
// Signed, -PLAYER_BANK_MAX..+PLAYER_BANK_MAX. Presentation only: nothing in
// the movement, collision or weapon path reads either byte, which is what
// makes this a change to how the ship LOOKS and not to how it flies.
plyBank:     .byte PLAYER_BANK_NEUTRAL   // 0..4, hard left .. hard right
plyBankTimer:.byte 0                     // frames until the lean may step
plyEngine:   .byte 0                     // engine flame phase, 0..2
plyEngineTimer: .byte 0                  // frames until the flame may step

// The muzzle flash's whole state: visible frames remaining, PLAYER_FLASH_TIME
// down to 0. Presentation only -- nothing in the weapon, collision or movement
// path reads it, and the weapon does not know it exists.
plyFlash:    .byte 0

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

// THE LAST LIFE HAS BEEN LOST and the death presentation is running. The
// lifecycle is NOT entered on the collision frame: the hit that empties the
// stock sets this, the ordinary invulnerability blink plays out as the fatal
// presentation, and playerFatalTick hands over only when it finishes. That is
// the old game's shape -- it too held its explosion before GAME OVER -- and it
// is why the player's own death behaviour did not have to change at all.
plyFatal:    .byte 0

// plyExit -- "the level has been won and the player no longer has agency" --
// lives in src/boss.asm's state block, not here. The player's own block is
// full to its $c540 ceiling, and the byte belongs to the level's ending in any
// case: boss.asm sets it, clears it and flies the ship out with it. This file
// only ever READS it, in playerTick and playerTakeHit.

// ---------------------------------------------------------------------------
// THE DEATH PHASE. Non-zero from the instant the craft is killed until its
// explosion has finished burning, and it is the one byte that answers "is the
// player dead RIGHT NOW" for everything that has to care:
//
//   playerTick     stops reading the stick, so a corpse cannot be steered
//   weaponFire     refuses the volley, so there is no hitscan, no shotFired,
//                  no player-fire SFX and therefore no muzzle flash either
//   playerEmit     draws the fireball on HW0 instead of the ship
//   ebulletPlayerTick / playerBodyTick
//                  ignore a player who is already dying
//
// IT IS SET FOR EVERY DEATH, not only the last one. The old behaviour -- a
// fully controllable ship flying about inside its own death animation, and
// still firing -- came from there being no such state at all: the only thing a
// hit did was start an invulnerability blink.
plyDead:     .byte 0

// Which fireball frame is on screen, 0..PLAYER_BOOM_FRAMES-1, and how many PAL
// frames it has been there. plyBoomFrame reaching PLAYER_BOOM_FRAMES is what
// ENDS the explosion -- it is never wrapped, so the animation cannot loop.
plyBoomFrame: .byte 0
plyBoomTimer: .byte 0

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
// The ship: fifteen multicolour frames, straight from the sprite sheet.
// ===========================================================================
// WHAT THE ARTWORK IS, established from the pixels rather than assumed:
//
//   * THREE COLOURS PLUS TRANSPARENT -- a black outline, a medium-blue hull
//     and white highlights -- in cells twelve pixels wide. A hires sprite
//     carries ONE colour, so no pair of overlaid hires sprites can express
//     three; twelve pixels and three colours is exactly one C64 MULTICOLOUR
//     sprite (12 double-width pixels = 24 screen px). Multicolour is the
//     artwork's native mode and ONE sprite is its native composition, which is
//     why the craft stopped being two hires layers.
//
//     THOSE ARE THE SHEET'S COLOURS, NOT THE SCREEN'S. The outline pixels are
//     black IN THE PNG and select bit pair 01, which the VIC draws in the
//     shared $d025 -- SPR_MC_DARK, dark grey. Only the hull's pair 10 is this
//     sprite's own ($d027 = PLAYER_COL_SHIP). Read the sheet's black as "the
//     shading index", not as a colour that reaches the display.
//   * THE SHEET'S ROWS ARE BANKING. The neutral band is mirror-symmetric to
//     the pixel; the other two lean progressively LEFT -- in both, the right
//     wingtip rides high while the left drops. The sheet draws one direction,
//     so the right-hand banks are horizontal mirrors.
//   * THE SHEET'S COLUMNS ARE THE ENGINE. The three cells of a band differ
//     only in their bottom two rows: the exhaust flame full, small, then out.
//
// Five bank states times three engine frames is fifteen blocks, plus one
// blank for HW1.
//
// READ BY PALETTE INDEX, NOT RGB. The sheet has TWO black entries -- index 0,
// the opaque black these outlines are drawn in, and index 255, the
// transparency key, which is also (0,0,0). Opening it as RGB merges the two
// and turns every outline pixel into background.
//
// The bytes live in src/player_art.asm, generated by tools/gen_player_ship.py
// straight from the PNG and verified against it pixel for pixel. The assembler
// reads the generated file; the build runs no converter and the game has no
// runtime dependency on one.
* = PLAYER_SPRITES "player bitmaps"
playerBitmaps:
#import "generated_sprites/player_art.asm"

// The blank sixteenth of the allocation: HW1's bitmap, and the block a real
// muzzle-flash overlay would occupy if one is ever drawn for this ship.
playerBlankBitmap:
    .fill 64, 0

playerBitmapsEnd:
.if (playerBitmapsEnd - playerBitmaps != PLAYER_BLOCKS * 64) {
    .error "player bitmaps must be exactly PLAYER_BLOCKS x 64 bytes"
}

// ---------------------------------------------------------------------------
// The muzzle flash: five supplied multicolour sprites, one per banking
// attitude, in the same bank order as the craft's own frames.
//
// src/player_muzzle_flash.asm is SUPPLIED ARTWORK and is checked in exactly as
// delivered -- no tool generates it and nothing here rewrites it. Its own
// header documents the pixel semantics this file relies on: pair 10 is HW1's
// private colour and pair 11 the player's shared white, and pair 01 is never
// used, so lighting the flash cannot disturb the shared shade the craft's
// outline depends on.
// ---------------------------------------------------------------------------
* = PLAYER_FLASH_SPRITES "player muzzle flash"
playerFlashBitmaps:
#import "generated_sprites/player_muzzle_flash.asm"
playerFlashBitmapsEnd:
.if (playerFlashBitmapsEnd - playerFlashBitmaps != PLAYER_FLASH_FRAMES * 64) {
    .error "the muzzle flash must be exactly PLAYER_FLASH_FRAMES x 64 bytes"
}
.if (playerFlashBitmaps != PLAYER_PTR_FLASH * 64) {
    .error "the muzzle flash is not where PLAYER_PTR_FLASH points"
}
.if (playerBlankBitmap != PLAYER_PTR_BLANK * 64) {
    .error "the blank block is not where PLAYER_PTR_BLANK points"
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
    jsr cmpSpeedReset                   // no part-earned pixel survives a death,
                                        // a respawn or a new level
    lda #0
    sta plyFatal                        // a new game never starts mid-death
    sta plyDead                         // ...nor mid-explosion
    sta plyBoomFrame
    sta plyBoomTimer
    lda #1
    sta plyVisible                      // ...nor invisible, which is how the
                                        // last death left HW0
    lda #0
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
    sta plyBankTimer
    sta plyEngine                       // flame at full
    sta plyEngineTimer
    sta plyFlash                        // no shot, no flash
    lda #PLAYER_BANK_NEUTRAL            // level flight
    sta plyBank

    // $d025/$d026 are NOT written here. They are shared by every multicolour
    // sprite in the game, so they belong to no subsystem and are set once in
    // src/main.asm's entry beside the other whole-machine sprite state.
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
// readInput — sample joystick port 2.
//
// Port A of CIA1 is the keyboard column drive AND joystick 2; reading it
// returns the pin states. Nothing in this program drives $dc01 (port B is left
// as an input), so no key can pull a column low and be mistaken for a stick
// direction.
//
// IT IS NO LONGER THE ONLY $dc00 ACCESS. readKeyI below drives a column to scan
// one key on the attract screen, and it is the reason the guarantee above still
// holds: it restores $dc00 to "no column selected" in the instruction after the
// row read, so this routine can never sample a driven column. See its note.
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
// readKeyI — is the I key held down? Exit: A = 1 if it is, 0 if not.
// X clobbered.
//
// THE ONLY KEYBOARD READ IN THE GAME, and it lives here because this file
// already owns CIA 1 and the note above is the one that has to stay true.
//
// Port A is the keyboard's COLUMN DRIVE and joystick 2 at the same time, which
// is the whole hazard: a column left driven low reads back as a stick
// direction or as FIRE. KEY_I_COL has bit 4 clear, so leaving it in place would
// look exactly like the trigger being pulled. $dc00 is therefore restored to
// "no column selected" in the instruction after the row read and BEFORE
// anything branches -- there is no path out of here that leaves it driven.
//
// Port B stays an input, which is what readInput's note relies on; nothing here
// writes $dc01 or either data-direction register.
// ---------------------------------------------------------------------------
.const KEY_I_COL = %11101111        // drive PA4 low: the column holding I
.const KEY_I_ROW = %00000010        // ...and read PB1, which is the I key

readKeyI:
    lda #KEY_I_COL
    sta $dc00
    lda $dc01                       // the row bits, active LOW
    ldx #$ff
    stx $dc00                       // every column off again, at once
    and #KEY_I_ROW
    beq !down+
    lda #0                          // bit still high: not pressed
    rts
!down:
    lda #1
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
    lda plyExit                         // the level is won: nothing can hurt it
    bne !done+
    lda plyInvuln
    bne !done+
    lda plyDead                         // already dying: the explosion is the
    bne !done+                          // consequence and it is already running

    // THE HIGHEST-PRIORITY SOUND IN THE GAME, and it cannot stutter. This
    // routine is already the single point at which damage MEANS something, and
    // the plyInvuln guard three lines above it -- which exists for the
    // collision rule, not for the sound -- means the next hundred frames of
    // blinking, and every projectile that passes through the ship during them,
    // reach !done and make no sound at all. One hit, one wail.
    lda #SFX_HURT
    jsr sfxRequest                      // src/sfx.asm; preserves X and Y

    lda plyHits                         // saturating: that the ship was hit is
    cmp #$ff                            // the event; the exact count past 255
    beq !lives+                         // is not
    inc plyHits

    // ---- the stock ------------------------------------------------------
    // LIVES GET A REAL OWNER HERE. src/hud.asm's placeholder used to cycle
    // hudLives on a timer and its own note demanded that whatever came to own
    // the value REPLACE that block rather than run beside it; this is that
    // owner, and the demo lives are gone. One writer, one truth.
!lives:
    // INFINITE LIVES IS A TESTING TOGGLE, AND IT CHEATS EXACTLY ONE THING.
    // Everything above this point has already happened -- the hit was real, the
    // sound is playing, plyHits counted it -- and everything below still
    // happens: the craft is destroyed, the fireball runs, the respawn and its
    // invulnerability follow. The only difference is that the stock is not
    // touched and the death can never be the last one.
    //
    // The terminal guard is skipped with it. A stock of zero with the cheat on
    // is not a terminal state, it is just a number nobody is spending.
    lda gsInfLives
    bne !noCost+

    lda hudLives
    beq !done+                          // already terminal: the fatal window is
                                        // running and a stray hit changes
                                        // nothing
    dec hudLives
    lda hudDirty
    ora #HUD_DIRTY_LIVES
    sta hudDirty
!noCost:
    // ---- the craft dies -------------------------------------------------
    // THE INVULNERABILITY WINDOW IS NO LONGER STARTED HERE. It used to be the
    // whole of "being hit": a hundred frames of blinking on an intact ship.
    // The ship is now destroyed, the fireball is the presentation, and the
    // invulnerability belongs to the RESPAWN at the other end of it -- which
    // is where playerDeathTick starts it.
    lda #1
    sta plyDead
    lda #0
    sta plyBoomFrame                    // the explosion starts at its first
    sta plyBoomTimer                    // frame, however it was reached
    sta plyFlash                        // AND THE MUZZLE GOES OUT. A shot
                                        // resolved on the frame of the killing
                                        // blow would otherwise leave HW1 lit
                                        // over the wreckage for two frames.
    lda #1
    sta plyVisible                      // solid for the whole explosion; the
                                        // blink belongs to the respawn

    lda gsInfLives
    bne !done+                          // ...and with the cheat on there is no
                                        // such thing as the last one
    lda hudLives
    bne !done+
    lda #1
    sta plyFatal                        // the last one. The explosion runs in
                                        // full either way; only where it ENDS
                                        // differs.
!done:
    rts

// ---------------------------------------------------------------------------
// playerDeathTick — one frame of dying. Called from playerTick INSTEAD OF the
// movement block, which is what makes a dead craft uncontrollable.
//
// Six frames per art frame, eight art frames, and then one of two endings that
// differ only in where they leave the player -- never in what was shown.
// ---------------------------------------------------------------------------
playerDeathTick:
    inc plyBoomTimer
    lda plyBoomTimer
    cmp #PLAYER_BOOM_HOLD
    bcc !burning+                       // this art frame still has time to run

    lda #0
    sta plyBoomTimer
    inc plyBoomFrame
    lda plyBoomFrame
    cmp #PLAYER_BOOM_FRAMES
    bcc !burning+                       // ...and so does the explosion

    // ---- the fire is out -------------------------------------------------
    lda #0
    sta plyDead                         // controls come back -- or do not, if
                                        // this was the last life
    sta plyBoomFrame
    sta plyBoomTimer

    lda plyFatal
    bne !gone+

    // RESPAWN, through the behaviour that was already here: the craft
    // reappears where it died and is briefly invulnerable, and playerInvulnTick
    // blinks it for the whole window. That blink is the RESPAWN's, and it is
    // the one piece of the old death presentation worth keeping.
    lda #1
    sta plyVisible
    lda #PLAYER_INVULN_TIME
    sta plyInvuln
    rts

!gone:
    lda #0
    sta plyVisible                      // HW0 off and it stays off: there is no
    rts                                 // respawn, and playerFatalTick hands
                                        // the lifecycle over from here

!burning:
    lda #1
    sta plyVisible                      // solid, never blinking, while it burns
    rts

// ---------------------------------------------------------------------------
// playerFatalTick — hand the lifecycle over when the last life's presentation
// has finished. MAIN THREAD, once per frame from gameFrame.
//
// FIVE CYCLES unless the player is actually dying for the last time. The test
// is plyFatal AND a finished blink, so the transition happens on the frame the
// current engine's own death behaviour ends -- not on the collision frame, and
// not on a timer of its own invention.
// ---------------------------------------------------------------------------
playerFatalTick:
    lda plyFatal
    bne !dying+
    rts
!dying:
    lda plyDead
    beq !over+
    rts                                 // the fireball is still burning
!over:
    lda #0
    sta plyFatal                        // once, and only once
    jmp gsEnterGameOver                 // src/gamestate.asm; its rts is ours

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

playerStepX:
    lda joyState
    and #JOY_LEFT
    bne !notLeft+
    lda plyX                            // 9-bit decrement; the clamp the caller
    bne !decLo+                         // runs is what catches a borrow past
    dec plyXHi                          // zero
!decLo:
    dec plyX
    rts
!notLeft:
    lda joyState
    and #JOY_RIGHT
    bne !stillX+
    inc plyX
    bne !noCarry+
    inc plyXHi
!noCarry:
!stillX:
    rts

playerStepY:
    lda joyState
    and #JOY_UP
    bne !notUp+
    dec plyY
    rts
!notUp:
    lda joyState
    and #JOY_DOWN
    bne !stillY+
    inc plyY
!stillY:
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
// playerBankTick — one frame of the banking lean. PRESENTATION ONLY.
//
// Walks plyBank one stage towards where the stick is pointing, no faster than
// one stage every PLAYER_BANK_RATE frames. It reads joyState and writes
// plyBank and its timer, and nothing else: no position, no velocity, no
// clamp, no weapon. Removing this routine would change how the ship looks and
// nothing about how it flies.
//
// THE DEAD-BAND IS THE TIMER, not a threshold. There is no horizontal velocity
// to compare against zero -- the stick is either held or it is not -- so the
// twitch this has to avoid is the stick being centred for a frame or two
// during a direction change or on a diagonal. A lean that takes five frames
// to move one stage simply does not notice that, and rolls back out over the
// same five frames per stage when the stick really is released.
// ---------------------------------------------------------------------------
playerBankTick:
    // ---- the engine flame, on its own clock -------------------------------
    // Independent of the lean: the exhaust flickers whether or not the craft
    // is turning, so the two cadences do not share a timer.
    lda plyEngineTimer
    beq !flameStep+
    dec plyEngineTimer
    jmp !flameDone+
!flameStep:
    lda #PLAYER_ENGINE_RATE - 1
    sta plyEngineTimer
    ldx plyEngine
    inx
    cpx #PLAYER_ENGINE_FRAMES
    bcc !flameStore+
    ldx #0
!flameStore:
    stx plyEngine
!flameDone:

    lda plyBankTimer                    // not yet time to move a stage
    beq !due+
    dec plyBankTimer
    rts
!due:
    // ---- where does the stick want the ship to be leaning? ----------------
    // Active low, so a CLEAR bit is a held direction. Left wins a
    // simultaneous left+right, which the hardware allows and a worn stick
    // produces: the alternative is a frame of level flight in the middle of a
    // turn.
    ldx #PLAYER_BANK_NEUTRAL
    lda joyState
    and #JOY_LEFT
    bne !notLeft+
    ldx #PLAYER_BANK_LEFT
    jmp !haveTarget+
!notLeft:
    lda joyState
    and #JOY_RIGHT
    bne !haveTarget+
    ldx #PLAYER_BANK_RIGHT
!haveTarget:

    // ---- one stage towards it --------------------------------------------
    // Unsigned, so the direction is a plain carry test.
    cpx plyBank
    beq !settled+                       // already there: leave the timer at
                                        // zero so the next change is immediate
    lda #PLAYER_BANK_RATE
    sta plyBankTimer
    bcc !stepDown+                      // target < current
    inc plyBank
    rts
!stepDown:
    dec plyBank
!settled:
    rts

// ---------------------------------------------------------------------------
playerTick:
    // DEAD CRAFT, NO CONTROLS. The whole movement block below is skipped, so
    // the stick cannot move it, the lean cannot change and the position is
    // frozen exactly where it was destroyed. weaponFire refuses separately, so
    // the trigger is dead too.
    lda plyDead
    beq !notDead+
    jmp playerDeathTick                 // its rts is ours
!notDead:
    lda plyExit                         // the victory launch flies the ship;
    beq !alive+                         // the stick does not
    rts
!alive:
    jsr playerInvulnTick
    jsr playerBankTick                  // presentation only; reads joyState,
                                        // writes plyBank, touches no position

    lda plyX                            // remember the position we came in with,
    sta pt_x                            // so the dirty test below is exact
    lda plyXHi
    sta pt_xhi
    lda plyY
    sta pt_y

    // ---- ONE PIXEL PER HELD AXIS, THEN THE SUB-PIXEL REMAINDER ------------
    // The base step is untouched and unconditional: a stock ship moves exactly
    // one pixel a frame per axis, which is the movement model the engine has
    // always had and which tests/test_production.py asserts to the pixel.
    //
    // An upgraded ship accumulates a FRACTION per axis and takes a second step
    // on that axis when the fraction carries. See playerFracStep for why this
    // replaced a global frame-counter mask, and for what it can and cannot fix.
    jsr playerStepX
    ldx #0
    jsr cmpSpeedFracStep
    bcc !noExtraX+
    jsr playerStepX                     // the earned pixel, this axis only
!noExtraX:

    jsr playerStepY
    ldx #1
    jsr cmpSpeedFracStep
    bcc !noExtraY+
    jsr playerStepY
!noExtraY:

    jsr playerClampX                    // AFTER BOTH STEPS, so a boosted frame
    jsr playerClampY                    // cannot walk through the clamp

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
    // HW1 SITS SEVEN LINES ABOVE THE CRAFT. The flash artwork draws its two
    // flares low in its own block so that, lifted by this much, each one lands
    // on a wing-gun barrel of the craft underneath -- the registration is the
    // artwork's, and this offset is the half of it that lives in code.
    // plyY can never be below PLAYER_MIN_Y, so the subtraction cannot borrow --
    // asserted at assembly time rather than guarded at run time.
    sec
    sbc #PLAYER_FLASH_Y_LIFT
    sta plyPresY1
    // THE MUZZLE FLASH IS A PRESENTATION CHOICE, MADE HERE.
    //
    // The weapon announces shotFired and knows nothing else about how a shot
    // looks. Turning that into a lit sprite goes out through the block the
    // renderer already publishes, so firing costs no new slot and no renderer
    // change -- and the block compare at the bottom of this routine notices it
    // without being told.
    // ---- HW0: which banking frame, and in which colour --------------------
    // THE POINTER COMES FROM THE LEAN, THE COLOUR FROM THE MUZZLE, and the two
    // are independent by construction. The five frames are adjacent and in
    // bank order, so a signed lean of -2..+2 becomes a pointer with one add.
    // frame = FIRST + bank * ENGINE_FRAMES + engine, and ENGINE_FRAMES is 3,
    // so the multiply is one shift and one add of the value itself.
    // THE FIREBALL TAKES HW0 OUTRIGHT while the craft is dying. The ship's
    // silhouette is gone on the very first frame of death -- there is no
    // intact hull to be seen tinting or blinking, because the pointer no
    // longer names one.
    lda plyDead
    beq !hull+

    lda plyBoomFrame                    // 0..PLAYER_BOOM_FRAMES-1
    cmp #PLAYER_BOOM_FRAMES
    bcc !boomOk+
    lda #PLAYER_BOOM_FRAMES - 1         // belt and braces: the animation is
!boomOk:                                // ended by plyDead, never by wrapping
    clc
    adc #PLAYER_PTR_BOOM
    sta plyPresPtr0
    lda #PLAYER_COL_BOOM                // red, in HW0's OWN $d027. No shared
    sta plyPresCol0                     // colour moves; see player_boom_art.asm
    jmp !hw0Done+

!hull:
    lda plyBank                         // 0..4
    asl                                 // 2n
    clc
    adc plyBank                         // 3n
    clc
    adc plyEngine
    clc
    adc #PLAYER_PTR_FIRST
    sta plyPresPtr0

    // THE HULL COLOUR IS NOW CONSTANT. Firing used to redden it; it does not
    // any more, and the craft's only colour changes are the ones taking a hit
    // causes. The muzzle flash is HW1's business alone, below.
    lda #PLAYER_COL_SHIP
    sta plyPresCol0
!hw0Done:

    // ---- HW1: the muzzle flash --------------------------------------------
    // THE TRIGGER IS shotFired, AND THAT IS THE POINT. It is set by weaponFire
    // only on a shot the weapon actually ACCEPTED -- past the overheat test,
    // past the cooldown, with the cadence already armed -- and weaponTick
    // clears it at the top of every frame. playerEmit runs after weaponTick in
    // gameFrame, so it sees this frame's event and no other.
    //
    // Reading the fire BUTTON here instead would flash every frame the trigger
    // was held, at sixty a second, for shots the weapon refused. The weapon's
    // cadence, heat and lockout are untouched by any of this: nothing below
    // writes one byte the weapon owns.
    lda shotFired
    beq !noNewShot+
    lda #PLAYER_FLASH_TIME
    sta plyFlash
!noNewShot:

    lda plyFlash
    beq !dark+

    // ONE COLOUR FOR THE WHOLE FLASH. The count still decides WHETHER HW1 is
    // lit, but no longer what colour it is: the artwork carries its own bright
    // core in the shared white, so $d028 just holds red underneath it for both
    // frames. No branch on the count, and the same bitmap for both frames.
    lda #PLAYER_COL_FLASH
    sta plyPresCol1

    // The flash leans with the craft: one frame per banking attitude, in the
    // same bank order as the hull, so the bank index selects both.
    lda plyBank                         // 0..4
    clc
    adc #PLAYER_PTR_FLASH
    sta plyPresPtr1

    jmp !hw1Done+

!dark:
    // No flash: HW1 points at the blank block and is switched off below. The
    // pointer is still written so the published block is a pure function of
    // the state, never a leftover from the last shot.
    lda #PLAYER_PTR_BLANK
    sta plyPresPtr1
    lda #PLAYER_COL_BLANK
    sta plyPresCol1
!hw1Done:

    // $d010. Both layers share one X, so their two bits always agree -- but
    // both are written from the same test rather than one being copied from the
    // other, so an overlay that ever gains an X offset changes one line here.
    lda #0
    ldy plyXHi
    beq !noMsb+
    lda #PLAYER_SLOT_MASK
!noMsb:
    sta plyPresD010

    // $d015. HW0 whenever the craft is visible; HW1 ONLY while the flash is
    // running, so an idle player costs no second sprite and nothing is ever
    // enabled over the blank block.
    //
    // The invulnerability blink still gates BOTH, because it gates this test:
    // a blinking ship that kept flashing would be the one frame where the
    // player is invisible and their gun is not.
    lda #0
    ldy plyVisible
    beq !hidden+
    lda #PLAYER_HW0_BIT
    ldy plyFlash                        // the count for the frame JUST emitted
    beq !hidden+
    lda #PLAYER_SLOT_MASK
!hidden:
    sta plyPresEnable

    // ...AND ONLY NOW IS THE FRAME SPENT. The count is decremented after the
    // enable above has read it, not when the pointer and colour were chosen:
    // doing it there emitted the red frame and then disabled the sprite for
    // it in the same pass, so the sting was one frame long and the second
    // never appeared.
    lda plyFlash
    beq !flashSpent+
    dec plyFlash
!flashSpent:

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
.if (* > $4340) {
    .error "the player code has run into the scroller at $4340"
}
