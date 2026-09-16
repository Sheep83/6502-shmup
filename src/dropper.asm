// ===========================================================================
// dropper.asm — the Orbital Dropper's own flight, and the ping that announces it
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is written from this file and no
// hardware sprite is named in it. It moves the LOGICAL coordinates of one
// ordinary pool object and asks src/sfx.asm for one sound.
//
// WHAT THIS IS, AND WHY IT IS NOT A WAVE. A Dropper is the only enemy in the
// game whose death is worth something: it drops the P, and the P starts the
// protector encounter (src/token.asm). That makes WHERE it dies a gameplay
// fact rather than a detail -- kill one at the bottom of the aperture and the
// encounter it starts has no room to be played. An authored wave path cannot
// promise that, because a wave is authored for a formation of Rings and the
// Dropper is riding it as a passenger.
//
// So the Dropper flies its own path, high up, and it is a SPECIES behaviour
// rather than a wave one:
//
//     enters horizontally from an authored side, high in the aperture
//       -> pass 1 across the screen, weaving
//       -> reverse
//       -> pass 2 back
//       -> reverse
//       -> pass 3 across
//       -> off the far side, and the ordinary despawn rule retires it
//
// THREE PASSES, AND THEN IT IS GONE. An enemy that circled for ever would
// stall the level; one that crossed once would be a coin flip. Three crossings
// of the top of the screen is long enough to notice it, track it and shoot it,
// and the exit side is the OPPOSITE of the entry side, which is what makes
// "it got away" legible rather than ambiguous.
//
// KILLING IT IS UNCHANGED. Nothing here touches the death path: src/enemy.asm
// still sees objHP reach zero, still runs the death animation, and still calls
// tokenDropperDied with the position captured before the slot is freed. This
// file only decides where the Dropper IS while it is alive.
//
// ---------------------------------------------------------------------------
// WHY THE FLIGHT STATE IS NOT PER-OBJECT
// ---------------------------------------------------------------------------
// There is never more than one live Dropper -- src/waves.asm enforces that at
// the single instruction that commits a species to an object, and src/token.asm
// holds the flag -- so the pass counter, the weave phase and the ping timer are
// module bytes rather than sixteen-entry arrays. That is a saving of forty-odd
// bytes and, more importantly, it is the truth: these describe THE Dropper, not
// "whichever objects happen to be Droppers".
//
// THE DIRECTION IS NOT STORED AT ALL. It is the sign of wmVX, which this file
// keeps truthful because src/enemy.asm's despawn rules read that byte to tell
// an enemy ARRIVING through a border from one LEAVING through it. A second
// direction byte would be a second thing that could disagree with the first,
// and v2.1 has already paid for that lesson once.
// ===========================================================================

// --- which side it comes in on ----------------------------------------------
// AUTHORED, NOT RANDOM, and carried on the trigger list beside the species it
// belongs to -- see trigSide in src/waves.asm. The two sides are the same
// routine with two constants; there is no mirrored copy of anything.
.const DROP_SIDE_LEFT  = 0
.const DROP_SIDE_RIGHT = 1

// Where it comes in. Both are outside the visible window (24..343) by enough
// that the VIC clips the sprite column by column as it arrives, so a Dropper
// SLIDES IN through the border exactly as the authored sweep wave does rather
// than appearing in mid-air.
.const DROP_ENTRY_LEFT  = 0
.const DROP_ENTRY_RIGHT = 343

// Where it turns round. These are the visible edges, not the despawn edges, so
// the whole reversal happens ON SCREEN -- a turn behind the border would read
// as a second Dropper arriving rather than as the same one coming back.
.const DROP_X_LEFT  = 24
.const DROP_X_RIGHT = 320

// HOW MANY CROSSINGS BEFORE IT LEAVES. Three is the odd number that makes the
// exit side the opposite of the entry side; two or four would send it back out
// of the border it came in through, which reads as a retreat rather than a
// fly-past.
.const DROP_PASSES = 3
.if (mod(DROP_PASSES, 2) != 1) {
    .error "an even pass count exits the side it entered: see the note above"
}

// HOW FAST IT CROSSES, in quarter pixels: three whole pixels a frame. A pass is
// about 296 px, so a crossing takes ~99 frames and the whole three-pass flight
// is around six seconds -- long enough to react to, short enough that ignoring
// it is a decision rather than a wait.
.const DROP_VX = 12

// --- the weave ---------------------------------------------------------------
// THE UPPER THIRD OF THE APERTURE, AND THAT IS THE WHOLE POINT OF THE PATH.
// The aperture runs 55..247; a centreline of 88 with an amplitude of 16 keeps
// the Dropper inside 72..104, so wherever it dies the P has at least 145 rows
// of descent left to be fought over. Killing it low was the problem this flight
// exists to remove.
.const DROP_CENTRE_Y = 88
.const DROP_AMPLITUDE = 16

// A TABLE, NOT A TRIGONOMETRIC FUNCTION. Thirty-two phases of a sine, one whole
// pixel each, held for two frames -- a 64-frame cycle, so roughly one and a half
// weaves per crossing. The largest step between adjacent phases is about three
// pixels, which at a two-frame hold is a pixel and a half a frame: slower than
// the horizontal travel, so the path reads as a shallow wave rather than a
// zigzag.
//
// THE PHASE IS NEVER RESET AFTER LAUNCH, which is what makes a reversal smooth:
// the Dropper turns round horizontally and carries on through the same weave it
// was already in, so there is no vertical jump at the moment it changes
// direction.
.const DROP_PHASES = 32
.const DROP_PHASE_HOLD = 2

// --- the sonar ping ----------------------------------------------------------
// HOW OFTEN IT ANNOUNCES ITSELF. Just under a second, which leaves about
// three-quarters of a second of silence between pings -- the sound is a
// LOCATOR, and a locator that never stops talking is a drone. See src/sfx.asm
// for the sound itself and for how it wins voice 2 without reserving it.
.const DROP_PING_PERIOD = 48

// The first one lands promptly rather than a full period in: at three pixels a
// frame the Dropper is meaningfully on screen within eight frames, and the ping
// is what tells the player to go looking for it.
.const DROP_PING_FIRST = 8

// ===========================================================================
// State. MAIN THREAD ONLY, in the free run between the token encounter state
// that ends at $c461 and the pickup state at $c4c0.
// ===========================================================================
* = $c462 "dropper flight state"

dropperState:
drPassLeft:  .byte 0      // crossings still to make; 0 = leaving for good
drPhase:     .byte 0      // index into the weave table, 0..DROP_PHASES-1
drHold:      .byte 0      // frames until the weave advances one phase
drPing:      .byte 0      // frames until the next sonar ping

// --- diagnostics, saturating -------------------------------------------------
drLaunched:  .byte 0      // Droppers given this flight
drEscaped:   .byte 0      // ...that completed three passes and left
drPinged:    .byte 0      // pings requested

dropperStateEnd:
.if (dropperStateEnd > $c4c0) {
    .error "the dropper flight state has grown into the pickup state at $c4c0"
}

// ===========================================================================
// Code. MAIN THREAD ONLY, in the free run between the movement interpreter
// that ends at $7998 and the wave director at $7c00 -- beside the two files it
// works with.
// ===========================================================================
* = $7a00 "dropper flight"

// ---------------------------------------------------------------------------
// dropperInit — no Dropper flying. Cold start only.
// ---------------------------------------------------------------------------
dropperInit:
    lda #0
    sta drPassLeft
    sta drPhase
    sta drHold
    sta drPing
    sta drLaunched
    sta drEscaped
    sta drPinged
    rts

// ---------------------------------------------------------------------------
// dropperLaunch — take this freshly spawned enemy off its authored path.
// Entry: A = DROP_SIDE_LEFT or DROP_SIDE_RIGHT, X = the object's pool slot.
// Exit:  X preserved.
//
// CALLED AFTER wmEnterStage, AND THE ORDER IS LOAD-BEARING. src/waves.asm arms
// every member's movement program from its wave definition, which writes
// wmMode, wmVX, wmVY and wmTimer; launching before that would have the wave
// overwrite this flight a dozen instructions later. So the Dropper is armed
// like any other member and then taken over, which also means there is no
// half-configured window: the object is complete either way.
//
// WHAT IS OVERRIDDEN, AND WHY EACH ONE. The position, because the authored
// wave placed it wherever its formation starts and this flight enters from a
// side. The velocity, because it is now this file's. And the firing
// permission -- see below.
// ---------------------------------------------------------------------------
dropperLaunch:
    tay                                 // the side, while A is needed

    lda #DROP_PASSES
    sta drPassLeft
    lda #0
    sta drPhase                         // phase 0 is the centreline, so the
                                        // Dropper enters level and starts
                                        // weaving from there
    lda #DROP_PHASE_HOLD
    sta drHold
    lda #DROP_PING_FIRST
    sta drPing

    // ---- height -----------------------------------------------------------
    lda #DROP_CENTRE_Y                  // = centre + weave[0], and weave[0] is
    sta logY,x                          // zero by construction

    // ---- NO VERTICAL VELOCITY, EVER ---------------------------------------
    // logY is written outright by dropperFly every frame, so wmVY plays no
    // part in where the Dropper is -- but it is NOT a spare byte. v2.1 gave
    // src/enemy.asm a top despawn edge that frees an enemy which is above the
    // aperture AND travelling up, and it reads exactly this byte to decide.
    // A Dropper carrying a stale upward velocity from the wave stage it was
    // armed with would be retired in mid-flight. Zero is the truth: it is not
    // going up or down, it is weaving about a fixed line.
    lda #0
    sta wmVY,x
    sta wmAccX,x
    sta wmAccY,x

    // ---- IT DOES NOT SHOOT -------------------------------------------------
    // The authored mask in src/waves.asm decides whether a member fires, and
    // it decides that knowing the path the member will fly -- a formation
    // crossing the aperture once, from which a downward bolt is a fair threat.
    // A Dropper is no longer on that path: it sits high up and crosses three
    // times, so the same authored byte would produce three times the fire from
    // a place the player cannot answer. The permission is withdrawn with the
    // path it was granted for, which is the same rule tokenSilence applies to
    // a protector.
    //
    // ITS CHALLENGE IS NOT ITS GUN. Finding it, tracking it and killing it
    // before it escapes is the fight; surviving the protectors afterwards is
    // the rest of it. src/ebullet.asm and the firing tick are untouched.
    lda #ENEMY_FIRE_NONE
    sta enyFire,x

    // ---- which way it is going, which is also where it starts -------------
    cpy #DROP_SIDE_RIGHT
    beq !fromRight+

    lda #<DROP_ENTRY_LEFT
    sta logX,x
    lda #>DROP_ENTRY_LEFT
    sta logXHi,x
    lda #DROP_VX                        // rightward
    sta wmVX,x
    jmp !armed+

!fromRight:
    lda #<DROP_ENTRY_RIGHT
    sta logX,x
    lda #>DROP_ENTRY_RIGHT
    sta logXHi,x
    lda #256 - DROP_VX                  // leftward, two's complement
    sta wmVX,x

!armed:
    lda drLaunched
    cmp #$ff
    beq !done+
    inc drLaunched
!done:
    rts

// ---------------------------------------------------------------------------
// dropperFly — one frame of the Dropper's flight.
// Entry/exit: X = the object's pool slot, preserved.
//
// REPLACES wmTick FOR THIS ENEMY. src/enemy.asm calls this instead, so no
// movement program runs and no stage advances -- but the HORIZONTAL half still
// goes through src/movement.asm's own integrator, because nine-bit signed
// quarter-pixel travel is exactly what that routine already does correctly and
// a second copy of it here would be a second thing to get wrong. Only the
// vertical is this file's, and it is a table lookup.
// ---------------------------------------------------------------------------
dropperFly:
    // ---- across: the ordinary integrator, on a truthful velocity ----------
    jsr wmApplyVelocity                 // X preserved. wmVY is zero, so this
                                        // moves X and leaves logY alone

    // ---- and the weave ----------------------------------------------------
    dec drHold
    bne !held+
    lda #DROP_PHASE_HOLD
    sta drHold
    inc drPhase
    lda drPhase
    cmp #DROP_PHASES
    bcc !held+
    lda #0
    sta drPhase
!held:
    ldy drPhase
    lda dropperWeave,y
    clc
    adc #DROP_CENTRE_Y                  // the offsets are signed; the centre
    sta logY,x                          // keeps the sum comfortably positive

    // ---- has it reached the far side? -------------------------------------
    // ONCE THE LAST PASS IS SPENT THIS TEST IS SKIPPED ENTIRELY, and it has to
    // be: the Dropper is then beyond the turning point and getting further
    // past it every frame, so a test that still ran would turn it round again
    // on every single one of them.
    lda drPassLeft
    beq dropperPing
    lda wmVX,x
    bmi !leftward+

    // rightward: is logX >= DROP_X_RIGHT?
    lda logXHi,x
    beq dropperPing                     // still under 256
    lda logX,x
    cmp #<DROP_X_RIGHT
    bcc dropperPing
    jmp !turn+

!leftward:
    // leftward: is logX <= DROP_X_LEFT?
    lda logXHi,x
    bne dropperPing                     // still over 255
    lda logX,x
    cmp #DROP_X_LEFT + 1
    bcs dropperPing

!turn:
    dec drPassLeft
    beq !escaping+                      // that was the third: fly on out and
                                        // let the ordinary despawn rule have
                                        // it. Nothing is reversed, nothing is
                                        // deleted, and wmVX still points the
                                        // way it is going -- which is what the
                                        // side despawn rule needs to agree
                                        // that it has LEFT rather than arrived
    lda #0
    sec
    sbc wmVX,x                          // reverse: negate the velocity
    sta wmVX,x
    lda #0
    sta wmAccX,x                        // drop the fractional remainder so the
                                        // turn starts from a whole pixel
    jmp dropperPing

!escaping:
    lda drEscaped
    cmp #$ff
    beq dropperPing
    inc drEscaped
    // falls through

// ---------------------------------------------------------------------------
// dropperPing — the sonar cue, once every DROP_PING_PERIOD frames.
// Entry/exit: X = the object's pool slot, preserved.
//
// DRIVEN FROM THE FLIGHT, WHICH IS WHAT MAKES IT STOP BY ITSELF. This runs
// only while a Dropper is alive and moving: src/enemy.asm sends a DYING enemy
// to enemyDeathTick before it ever reaches the movement call, and a despawned
// one no longer exists. So there is no "stop the ping" path to get wrong, no
// queued ping and no trailing one -- the sound stops because the thing making
// it stopped.
// ---------------------------------------------------------------------------
dropperPing:
    dec drPing
    bne !quiet+
    lda #DROP_PING_PERIOD
    sta drPing
    lda #SFX_PING
    jsr sfxRequest                      // X and Y preserved by contract
    lda drPinged
    cmp #$ff
    beq !quiet+
    inc drPinged
!quiet:
    rts

// ---------------------------------------------------------------------------
// The weave: DROP_PHASES signed offsets from the centreline, one sine.
// ---------------------------------------------------------------------------
dropperWeave:
.for (var k = 0; k < DROP_PHASES; k++) {
    .byte <round(DROP_AMPLITUDE * sin(2 * PI * k / DROP_PHASES))
}
dropperWeaveEnd:
.if (dropperWeaveEnd - dropperWeave != DROP_PHASES) {
    .error "the weave table is not one byte a phase"
}
.if (DROP_CENTRE_Y - DROP_AMPLITUDE < MIN_SPRITE_Y) {
    .error "the weave lifts the Dropper above the aperture, where it cannot be shot"
}
.if (DROP_CENTRE_Y + DROP_AMPLITUDE > MIN_SPRITE_Y + 64) {
    .error "the weave drops the Dropper out of the upper third of the aperture"
}

.if (* > $7c00) { .error "the dropper flight code has run into the wave director at $7c00" }
