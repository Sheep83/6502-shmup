// ===========================================================================
// weapon.asm — the player's guns: fire cadence, heat, overheat, shot event
// ===========================================================================
// NOT ONE VIC REGISTER IS WRITTEN FROM THIS FILE, and not one byte of HUD
// bitmap RAM either. The ownership line is the same one src/hud.asm and
// src/player.asm draw:
//
//     gameplay   owns weapon state          <- here
//     the HUD    owns presentation          src/hud.asm
//     the renderer owns VIC writes          src/renderer.asm
//
//     joystick fire -> weaponTick -> heat -> weaponHudFeed -> hudHeatLo/Hi
//                                   `-> shot event -> src/collision.asm
//
// THE BEHAVIOUR, in the terms the tests and the feel both depend on:
//
//   FIRE IS LEVEL-TRIGGERED. The joystick bit is read with no press/release
//   history, so a held button fires a volley every cadence period.
//
//   THE CADENCE IS WPN_FIRE_PERIOD FRAMES, enforced by refusing while
//   wpnCooldown is non-zero.
//
//   BOTH CANNONS FIRE TOGETHER, not alternately: one volley emits two rays in
//   the same frame at the same Y, and each resolves independently, so a volley
//   deals nothing, one hit or two.
//
//   THE PLAYER'S WEAPON IS HITSCAN. No projectile object is allocated for it.
//   (Hostile bullets ARE pool objects -- that is the enemies' weapon.)
//
//   HEAT IS PER FRAME, NOT PER SHOT. "Firing" is defined as wpnCooldown != 0,
//   and only a SUCCESSFUL volley arms that timer, so heat tracks actual firing
//   rather than the button.
//
//   COOLING NEVER OVERLAPS RISING. Strictly either/or: locked -> cooling, not
//   firing -> cooling, otherwise rising. That is what makes the timings below
//   exact rather than approximate.
//
//   THE LOCK IS A LATCH WITH TWO THRESHOLDS -- set at WPN_HEAT_MAX, cleared at
//   WPN_HEAT_REENABLE. While locked, weaponFire returns BEFORE arming the
//   cadence, so a held button produces no heat during a lockout and cannot
//   extend it.
// ===========================================================================

// The heat numbers, and the durations they define at 50 Hz:
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

// --- the shot event, which src/collision.asm consumes -----------------------
// shotFired is true for exactly the frame a volley resolves: weaponTick clears
// it at the top of every frame and sets it only on a legal shot. A consumer
// running after weaponTick in the same frame sees it; nothing has to remember
// to clear it, and nothing has to look at the joystick to know a shot fired.
//
// The rays are an array with a count rather than two named pairs, because
// walking "the rays this volley produced" is what the hitscan needs. It is not
// an upgrade system: there is one weapon and it has two barrels.
shotFired:    .byte 0               // 1 = a volley resolved THIS frame
shotRays:     .byte 0               // valid entries in shotX* below
shotXLo:      .fill WPN_RAYS, 0     // ray origin X, nine bits
shotXHi:      .fill WPN_RAYS, 0
shotY:        .byte 0               // shared origin Y: both rays leave the ship
                                    // at the same height and travel up

weaponStateEnd:
.if (weaponStateEnd > $c600) { .error "the weapon state has grown past its $c600 ceiling" }

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
// THE ORDER OF THE THREE STEPS IS LOAD-BEARING:
//
//   1. timers down
//   2. try to fire
//   3. heat
//
// Step 3 after step 2 is what makes a volley heat the gun on its OWN frame.
// Step 2 reading an overheat latch that step 3 set LAST frame is what stops a
// ghost volley escaping on the frame the gun overheats. Both steps live in one
// routine so that cross-frame relationship cannot be split apart.
// ---------------------------------------------------------------------------
weaponTick:
    lda wpnCooldown                     // 1. the cadence
    beq !noCd+
    dec wpnCooldown
!noCd:

    lda #0
    sta shotFired                       // true for one frame only, and only
                                        // because weaponFire says so

    jsr weaponFire                      // 2.
    // fall through to the accumulator  // 3.

// ---------------------------------------------------------------------------
// weaponHeat — the accumulator. Rising or cooling, never both.
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
// Three refusals, and the ORDER matters: the lockout is tested first and
// returns before the cadence is armed, which is why a held button cannot
// extend an overheat -- no cadence means no heat.
//
// A player-state gate ("only an alive ship may fire") belongs at the top of
// this routine if one is ever added.
// ---------------------------------------------------------------------------
weaponFire:
    lda wpnOverheated
    bne !refuse+
    lda wpnCooldown
    bne !refuse+
    lda joyState                        // ACTIVE LOW, and LEVEL-triggered: no
    and #JOY_FIRE                       // press history, so holding fire keeps
    bne !refuse+                        // firing at the cadence

    lda #WPN_FIRE_PERIOD                // arm the cadence before resolving
    sta wpnCooldown                     // anything: this is what heats the gun

    // ---- the shot event -------------------------------------------------
    // Both rays leave the ship on the same frame, at the same Y, one per
    // cannon. The event expires at the next weaponTick whether or not anything
    // read it.
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
// The whole of the gameplay-to-HUD boundary for the weapon: two bytes of
// value, one dirty bit, and a colour. No bitmap is touched here; hudUpdate
// draws, from the idle spin, inside the raster window it refuses to leave.
//
// The dirty bit is set only when the DRAWN PIXEL COUNT would change, not when
// the value changes. 300 units map onto 48 pixels, so the bar needs redrawing
// roughly every sixth unit, and setting the bit every frame would make
// hudUpdate do real work on frames where the picture is identical.
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
// SEGMENT GROWTH GUARD. Every explicit `* =` segment in this engine carries
// one: an unbounded segment turns an overlap into a run-time mystery instead
// of a build error.
// ---------------------------------------------------------------------------
.if (* > $4800) {
    .error "the weapon code has outgrown its $4600 segment"
}
