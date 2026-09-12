// ===========================================================================
// weapon.asm — the player's guns: fire cadence, heat, overheat, and the shot
// event a future collision system will consume.
// ===========================================================================
// NOT ONE VIC REGISTER IS WRITTEN FROM THIS FILE, and not one byte of HUD
// bitmap RAM either. The ownership line is the same one src/hud.asm and
// src/player.asm already draw:
//
//     gameplay   owns weapon state          <- here
//     the HUD    owns presentation          src/hud.asm
//     the renderer owns VIC writes          src/renderer.asm
//
//     joystick fire -> weaponTick -> heat -> weaponHudFeed -> hudHeatLo/Hi
//                                   `-> shot event -> Slice D's collision
//
// ---------------------------------------------------------------------------
// WHAT THE OLD GAME ACTUALLY DID
// ---------------------------------------------------------------------------
// Read out of c64Shooter/src/main.asm before any of this was written. The
// routines are updatePlayerFire (2418), updatePlayerCombatEffects (2690),
// updateWeaponHeat (9964) and refreshHeatGaugeIfDirty (10039); the constants
// are at 941-947 and 991-994.
//
//   FIRE IS LEVEL-TRIGGERED, NOT EDGE-TRIGGERED. updatePlayerFire tests the
//   joystick bit with no press/release history at all, so holding the button
//   fires a volley every cadence period for as long as it is held.
//
//   THE CADENCE IS EIGHT FRAMES. A volley arms PLAYER_FIRE_COOLDOWN_TIMER to
//   PLAYER_FIRE_COOLDOWN = 8; updatePlayerCombatEffects decrements it once per
//   frame and updatePlayerFire refuses while it is non-zero, so the next volley
//   lands exactly eight frames later.
//
//   BOTH CANNONS FIRE TOGETHER. One volley traces the left ray and then the
//   right ray, in the same call, in the same frame. They are not alternated.
//   Each resolves independently against its own nearest target, which is how a
//   volley could deal nothing, one hit or two.
//
//   THE PLAYER'S WEAPON IS TRUE HITSCAN. tracePlayerCannon walks the logical
//   object list and returns a target; no projectile object is ever allocated
//   for it. (Enemy bullets ARE objects, but that is the enemies' weapon.)
//
//   HEAT IS PER FRAME, NOT PER SHOT. updateWeaponHeat adds HEAT_RISE_PER_FRAME
//   whenever the cadence timer is non-zero -- and the old file says why in as
//   many words: "'The weapon is firing' is defined as
//   PLAYER_FIRE_COOLDOWN_TIMER != 0. That timer is only ever armed by a
//   SUCCESSFUL volley, so heat tracks actual firing rather than the button."
//   Held fire keeps the timer non-zero on every frame, so held fire is +2 every
//   frame: 150 frames, three seconds, from cold to overheated.
//
//   COOLING NEVER OVERLAPS RISING. The accumulator is strictly either/or:
//   locked -> cooling, not firing -> cooling, otherwise rising.
//
//   THE LOCK IS A LATCH WITH TWO DIFFERENT THRESHOLDS. It sets when heat
//   reaches HEAT_MAX and clears when heat falls back to HEAT_REENABLE, which is
//   half of it -- so an overheat costs a full second before the gun works again
//   and two before it is cold. While locked, updatePlayerFire returns before it
//   arms the cadence, so a held button generates no heat at all during the
//   lockout and cannot extend it.
//
//   NO UPGRADE MACHINERY EXISTED. The constants were centralised "so a later
//   upgrade screen can change capacity, cooling rate or sustained-fire duration
//   without touching the fire code. No upgrade machinery is built now." That is
//   still true here.
//
// DELIBERATELY NOT TAKEN:
//   * tracePlayerCannon / hitCannonTarget / damageEnemy. There are no enemies
//     yet, and the ray test belongs with the object pool it walks (Slice D).
//     What survives is the EVENT: where the rays are, and when.
//   * the gate on PLAYER_STATE == ALIVE. There is no player state machine yet;
//     Slice F adds one, and adds one branch at the top of weaponFire.
//   * every line of the old HUD gauge: composeHeatGauge, publishHeatBuffer,
//     the double-buffered bitmaps and the hudProofPtr publication. src/hud.asm
//     already does all of that, correctly, and this file only sets values.
// ===========================================================================

// --- the numbers, all from c64Shooter/src/main.asm:941-947 -----------------
//
//   0 -> HEAT_MAX      at +2/frame  = 150 frames = 3.0 s of continuous fire
//   HEAT_MAX -> 150    at -3/frame  =  50 frames = 1.0 s to re-enable firing
//   HEAT_MAX -> 0      at -3/frame  = 100 frames = 2.0 s to fully cool
.const WPN_HEAT_MAX      = 300      // 16-bit: above a byte on purpose
.const WPN_HEAT_REENABLE = 150      // firing permitted again at/below this
.const WPN_HEAT_RISE     = 2        // per frame while a volley owns the cadence
.const WPN_HEAT_FALL     = 3        // per frame otherwise
.const WPN_FIRE_PERIOD   = 8        // frames between held-fire volleys
.const WPN_FLASH_PERIOD  = 8        // frames per flash half-cycle while locked
.const WPN_RAYS          = 2        // hitscan rays a volley produces

.if (WPN_HEAT_REENABLE >= WPN_HEAT_MAX) { .error "the weapon would unlock at the ceiling" }
.if (WPN_HEAT_MAX + WPN_HEAT_RISE > 65535) { .error "heat could wrap sixteen bits" }

// ===========================================================================
// State. MAIN THREAD ONLY, outside VIC bank 0 with everything else it owns.
// ===========================================================================
* = $c570 "weapon state"

// --- the weapon -------------------------------------------------------------
wpnHeatLo:    .byte 0               // 0..WPN_HEAT_MAX, sixteen bits
wpnHeatHi:    .byte 0
wpnOverheated: .byte 0              // 1 = locked out until heat falls to
                                    // WPN_HEAT_REENABLE
wpnCooldown:  .byte 0               // frames until the next volley may fire.
                                    // NON-ZERO IS THE DEFINITION OF "firing",
                                    // and therefore of what heats the gun.
wpnFlashTimer: .byte 0              // gauge alarm flash, while locked
wpnFlashPhase: .byte 0              // 0 = not flashing, 1 = bright, 2 = dark.
                                    // Three states rather than a bare toggle so
                                    // "is it flashing at all" cannot be confused
                                    // with "which half are we in" -- that
                                    // confusion is what lets a dec run on a zero
                                    // timer and wrap it to 255.

// --- the shot event ---------------------------------------------------------
// THE CONTRACT SLICE D WILL CONSUME.
//
// shotFired is true for exactly the frame a volley resolves: weaponTick clears
// it at the top of every frame and sets it only on a legal shot. A consumer
// running after weaponTick in the same frame sees it; nothing has to remember
// to clear it, and nothing has to look at the joystick to know a shot happened.
//
// The rays are an array with a count rather than two named pairs, because
// "this volley produced these rays" is what a hitscan test actually needs to
// walk, and because the old game's two-cannon volley is a fact about the
// weapon rather than about the mechanism. It is not an upgrade system: there
// is one weapon and it has two barrels.
shotFired:    .byte 0               // 1 = a volley resolved THIS frame
shotRays:     .byte 0               // valid entries in shotX* below
shotXLo:      .fill WPN_RAYS, 0     // ray origin X, nine bits
shotXHi:      .fill WPN_RAYS, 0
shotY:        .byte 0               // shared origin Y: both rays leave the ship
                                    // at the same height and travel up

weaponStateEnd:
.if (weaponStateEnd > $c600) { .error "the weapon state has grown into the P3 fixture data at $c600" }

// ===========================================================================
// Code. MAIN THREAD ONLY, and outside VIC bank 0 beside the player and the
// scroller -- see the note at the top of src/scroll.asm.
// ===========================================================================
* = $4600 "weapon code"

// ---------------------------------------------------------------------------
// weaponInit — cold, unlocked, nothing in flight.
// ---------------------------------------------------------------------------
weaponInit:
    lda #0
    ldx #weaponStateEnd - wpnHeatLo - 1
!clear:
    sta wpnHeatLo,x                     // X counts down to 0 inclusive, so the
    dex                                 // first byte is covered by the loop
    bpl !clear-
    rts

// ---------------------------------------------------------------------------
// weaponTick — one frame of weapon. MAIN THREAD.
//
// The three steps run in the order the old game ran them across its frame, and
// the order is load-bearing:
//
//   1. timers down     (old updatePlayerCombatEffects, before the fire test)
//   2. try to fire     (old updatePlayerFire)
//   3. heat            (old updateWeaponHeat, after the fire test)
//
// Step 3 after step 2 is what makes a volley heat the gun on its OWN frame.
// Step 2 reading a latch that step 3 set LAST frame is what stops a ghost
// volley escaping on the frame the gun overheats -- the old file spells that
// cross-frame relationship out, and putting both steps in one routine keeps it
// rather than losing it.
// ---------------------------------------------------------------------------
weaponTick:
    lda wpnCooldown                     // 1. the cadence, and the muzzle flash
    beq !noCd+
    dec wpnCooldown
!noCd:
    lda plyMuzzle
    beq !noMuzzle+
    dec plyMuzzle
!noMuzzle:

    lda #0
    sta shotFired                       // true for one frame only, and only
                                        // because weaponFire says so

    jsr weaponFire                      // 2.
    // fall through to the accumulator  // 3.

// ---------------------------------------------------------------------------
// weaponHeat — the accumulator. Strictly either/or: rising or cooling, never
// both, which is what makes the three timings above exact rather than
// approximate.
// ---------------------------------------------------------------------------
weaponHeat:
    lda wpnHeatLo                       // cold and not firing: nothing any
    ora wpnHeatHi                       // branch below could change
    bne !active+
    lda wpnCooldown
    beq !done+
!active:
    lda wpnOverheated
    bne weaponCool                      // locked: always cooling
    lda wpnCooldown
    beq weaponCool                      // not firing: cooling

    lda wpnHeatLo                       // heat += WPN_HEAT_RISE, clamped
    clc
    adc #WPN_HEAT_RISE
    sta wpnHeatLo
    lda wpnHeatHi
    adc #0
    sta wpnHeatHi
    // Ceiling test. WPN_HEAT_MAX is 300, so its high byte is 1: heat below 256
    // cannot have reached it, and that is most of a three-second burst -- so
    // the cheap exit comes first.
    lda wpnHeatHi
    beq !done+
    lda wpnHeatLo
    cmp #<WPN_HEAT_MAX
    bcc !done+
    lda #<WPN_HEAT_MAX                  // saturate exactly at the ceiling and
    sta wpnHeatLo                       // latch the lockout
    lda #>WPN_HEAT_MAX
    sta wpnHeatHi
    lda #1
    sta wpnOverheated
!done:
    rts

weaponCool:
    lda wpnHeatLo
    ora wpnHeatHi
    beq !clamped+                       // already fully cold
    lda wpnHeatLo                       // heat -= WPN_HEAT_FALL, clamped at 0
    sec
    sbc #WPN_HEAT_FALL
    sta wpnHeatLo
    lda wpnHeatHi
    sbc #0
    sta wpnHeatHi
    bpl !checkUnlock+                   // the SIGN of the high byte is the test:
    lda #0                              // 1 - 3 leaves $ff there, and treating
    sta wpnHeatLo                       // that as a large positive number is how
    sta wpnHeatHi                       // a gauge ends up full at zero heat
!checkUnlock:
    lda wpnOverheated
    beq !clamped+
    // Still locked: unlock at or below WPN_HEAT_REENABLE. Compared against
    // REENABLE+1 so the unlock happens ON the frame heat reaches 150 rather
    // than the frame after, which is what makes the lockout exactly 50 frames.
    lda wpnHeatLo
    cmp #<(WPN_HEAT_REENABLE + 1)
    lda wpnHeatHi
    sbc #>(WPN_HEAT_REENABLE + 1)
    bcs !clamped+
    lda #0
    sta wpnOverheated                   // firing available again, gauge still
!clamped:                               // about half full
    rts

// ---------------------------------------------------------------------------
// weaponFire — resolve a volley if one is legal this frame.
//
// The three refusals, in the old game's order. The lockout comes FIRST and
// returns before the cadence is armed, which is the whole reason a held button
// cannot extend an overheat: no cadence means no heat.
// ---------------------------------------------------------------------------
weaponFire:
    // SLICE F ADDS THE PLAYER-STATE GATE HERE. c64Shooter's updatePlayerFire
    // opens with `PLAYER_STATE == ALIVE`, so an exploding or respawning ship
    // cannot shoot. There is no player state machine yet; this is where its
    // one branch goes.
    lda wpnOverheated
    bne !refuse+
    lda wpnCooldown
    bne !refuse+
    lda joyState                        // ACTIVE LOW, and LEVEL-triggered: the
    and #JOY_FIRE                       // old game reads the bit with no press
    bne !refuse+                        // history, so holding fire keeps firing
                                        // at the cadence

    lda #WPN_FIRE_PERIOD                // arm the cadence before resolving
    sta wpnCooldown                     // anything: this is what heats the gun
    lda #PLAYER_MUZZLE_TIME
    sta plyMuzzle                       // the player decides what that looks
                                        // like; see playerEmit

    // ---- the shot event -------------------------------------------------
    // Both rays leave the ship on the same frame, at the same Y, one per
    // cannon. Nothing consumes them yet and that is fine: the event expires
    // unused at the next weaponTick.
    lda plyY
    sta shotY
    lda plyX
    clc
    adc #PLAYER_CANNON_L
    sta shotXLo + 0
    lda plyXHi
    adc #0
    sta shotXHi + 0
    lda plyX
    clc
    adc #PLAYER_CANNON_R
    sta shotXLo + 1
    lda plyXHi
    adc #0
    sta shotXHi + 1
    lda #WPN_RAYS
    sta shotRays
    lda #1
    sta shotFired
!refuse:
    rts

// ---------------------------------------------------------------------------
// weaponHudFeed — logical heat into the HUD's logical heat. MAIN THREAD.
//
// This is the whole of the gameplay-to-HUD boundary for this slice: two bytes
// of value, one dirty bit, and a colour. No bitmap is touched here; hudUpdate
// draws, from the idle spin, inside the raster window it refuses to leave.
//
// The dirty bit is set only when the DRAWN PIXEL COUNT would change, not when
// the value changes. 300 units map onto 48 pixels, so the bar needs redrawing
// roughly every sixth unit; setting it every frame would make hudUpdate do real
// work on frames where the picture is identical. That is the HUD's own cost
// model and hudDemoTick already used it -- this keeps it.
// ---------------------------------------------------------------------------
weaponHudFeed:
    lda wpnHeatLo
    sta hudHeatLo
    lda wpnHeatHi
    sta hudHeatHi
    jsr hudHeatPixels                   // 0..HUD_HEAT_PIXELS for that value
    cmp hudHeatPix
    beq !sameBar+
    lda hudDirty
    ora #HUD_DIRTY_HEAT
    sta hudDirty
!sameBar:

    // ---- the lockout, made visible --------------------------------------
    // The gauge alternates red and black while the weapon is locked. It is the
    // only feedback that says "this is why you cannot shoot" rather than "the
    // bar is full", and it costs one byte through hudSetHeatColour.
    lda wpnOverheated
    beq !solid+
    lda wpnFlashPhase
    bne !running+
    lda #1                              // first locked frame: start bright
    sta wpnFlashPhase
    lda #WPN_FLASH_PERIOD
    sta wpnFlashTimer
    lda #HUD_HEAT_COL_ALARM
    jmp !setCol+
!running:
    dec wpnFlashTimer
    bne !done+
    lda #WPN_FLASH_PERIOD
    sta wpnFlashTimer
    lda wpnFlashPhase
    eor #3                              // 1 <-> 2
    sta wpnFlashPhase
    cmp #1
    beq !bright+
    lda #HUD_HEAT_COL_BLANK
    jmp !setCol+
!bright:
    lda #HUD_HEAT_COL_ALARM
    jmp !setCol+

!solid:
    lda wpnFlashPhase                   // not locked: restore the normal colour
    beq !done+                          // ONCE, on the frame the flash stops,
    lda #0                              // not on every frame afterwards
    sta wpnFlashPhase
    sta wpnFlashTimer
    lda #HUD_HEAT_COL_NORMAL
!setCol:
    jsr hudSetHeatColour
!done:
    rts

// ---------------------------------------------------------------------------
// SEGMENT GROWTH GUARD. Stated because an unbounded explicit `* =` segment is
// how the previous project found its overlaps at run time instead of at build
// time -- and how this one found its scroller overflow in Slice A'.
// ---------------------------------------------------------------------------
.if (* > $4800) {
    .error "the weapon code has outgrown its $4600 segment"
}
