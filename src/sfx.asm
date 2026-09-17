// ===========================================================================
// 6502-shmup — sfx: the sound-effects subsystem, v1.1
// ===========================================================================
// THREE SOUNDS, AND NOW ONE VOICE EACH. The plumbing is v1's and has not moved:
//
//     gameplay event  ->  sfxRequest  ->  sfxTick (once per frame)  ->  SID
//
// A gameplay system says WHAT HAPPENED and never what the SID should do. It
// does not own a voice, it does not keep an audio timer, and nothing in this
// engine has a per-object sound update. Every sound in the game is two bytes
// of state per voice, advanced once per PAL frame from src/main.asm's
// gameFrame.
//
// ---------------------------------------------------------------------------
// WHAT CHANGED IN v1.1, AND WHY
// ---------------------------------------------------------------------------
// v1 put all three effects on voice 3 and reserved voices 1 and 2 for music.
// THERE IS NO IN-LEVEL MUSIC AND THERE IS NOT GOING TO BE: music, if it comes,
// is for menus, transitions and end-of-level screens — presentation states in
// which the game is not being played. So during gameplay the whole chip is
// available for effects, and holding two thirds of it back for a thing that by
// definition never coexists with gameplay bought nothing and cost a great
// deal: with one voice, a shot fired as an enemy exploded cut the explosion
// off, which does not sound like priority arbitration, it sounds like a bug.
//
//     voice 1   $d400-$d406   FREQUENT/LIGHT.    player fire.
//     voice 2   $d407-$d40d   ENEMY/WORLD.       enemy and turret destruction.
//     voice 3   $d40e-$d414   HIGH-IMPACT/PLAYER. the ship taking damage.
//
// The mapping is FUNCTIONAL, not dynamic. There is no allocator, no mixer and
// no queue: an effect's voice is a constant looked up from its id, decided
// here, at author time, because we know what these three sounds are and what
// they have to be able to overlap with. Enemy fire, when it arrives, joins
// voice 2 with the rest of the world; a pickup chime joins voice 1 with the
// other light traffic.
//
// GLOBAL PRIORITY IS GONE, and its removal is the point rather than a tidy-up.
// v1's sfxPri existed for exactly one reason — three effects competing for one
// voice — and with the competition gone a priority byte would be a rule that
// can never fire, read by a compare that can never fail. What remains is the
// only arbitration that was ever doing real work: A REQUEST RESTARTS ITS OWN
// VOICE. Held fire retriggers the report on voice 1, two enemies dying in
// consecutive frames retrigger the crunch on voice 2, and neither can touch
// the other's voice at all. Nothing is rejected, so nothing counts rejections.
//
// Voice 3 keeps the player-damage sound partly because it was already there
// and partly because voice 3 is the one the hardware treats differently — it
// is the voice that can be cut from the output on its own ($d418 bit 7) — and
// the ship being hit is the sound that would want that switch first.
//
// ---------------------------------------------------------------------------
// SID REGISTER OWNERSHIP
// ---------------------------------------------------------------------------
//   $d400-$d414   voices 1, 2 and 3.  OWNED BY THIS FILE, written on a request
//                                     and on every frame an effect on that
//                                     voice is playing, and at no other time.
//                                     A voice with nothing playing is written
//                                     to zero once, when its effect ends, and
//                                     then left alone.
//   $d418         volume.   Claimed ONCE, by sfxInit, at boot. Master volume
//                           is SID-wide and there is no sound at all without
//                           it, so somebody must set it; nothing here writes
//                           it again. A menu music driver that wants to fade
//                           the whole chip takes this register over and this
//                           file does not have to change.
//   $d415-$d417   filter.   Written ONCE, to zero, by sfxInit at boot and
//                           never again — a cold-start "the chip is in a known
//                           state" action, not ownership. No effect here is
//                           filtered, and nothing routes a voice through the
//                           filter ($d417's low three bits stay clear), so the
//                           cutoff and resonance the boot clear leaves behind
//                           are inaudible rather than merely unused.
//
// The SID is write-only, so "what is the chip doing" cannot be read back. The
// discipline that replaces reading it is that exactly one routine writes each
// register and the state that decides those writes lives in RAM below.
//
// THE PER-VOICE REGISTER LAYOUT IS WHAT MAKES THIS CHEAP. The three voices are
// identical seven-register blocks at $d400, $d407 and $d40e, so a voice is an
// OFFSET (0, 7 or 14) in an index register and every SID write in this file is
// one absolute,Y store. Nothing is written three times over, and adding the
// second and third voice cost the code almost nothing.
//
// ---------------------------------------------------------------------------
// WHY A STUCK TONE IS NOT POSSIBLE — ON ANY OF THE THREE VOICES
// ---------------------------------------------------------------------------
//   1. EVERY EFFECT HAS SUSTAIN ZERO. The envelope decays to silence on its
//      own, whatever the rest of this file does. A gate left high on a
//      sustain-zero voice is silent, not a held note. This is the property
//      that makes the subsystem safe rather than merely careful.
//   2. sfxTick gates a voice off at the end of its effect and then clears that
//      voice's control register entirely on the frame after.
//   3. sfxSilence clears ALL THREE voices unconditionally, and gameInit calls
//      it — so any restart, death or return-to-menu re-silences the chip
//      without knowing this file exists.
// ===========================================================================

// --- the chip ---------------------------------------------------------------
// The register names are VOICE-RELATIVE: each is the register of voice 1, and
// every access in this file indexes it with the voice offset in Y. There is no
// such thing here as "voice 2's control register" — there is the control
// register, and the voice you are talking to.
.const SID            = $d400
.const SID_FREQ_LO    = SID + 0
.const SID_FREQ_HI    = SID + 1
.const SID_PW_LO      = SID + 2
.const SID_PW_HI      = SID + 3
.const SID_CTRL       = SID + 4
.const SID_AD         = SID + 5
.const SID_SR         = SID + 6
.const SID_VOICE_LEN  = 7
.const SID_VOLUME     = SID + $18
.const SID_LAST       = SID + $18       // the highest register the chip has

// Master volume, and the only SID-wide value this subsystem ever chooses.
// Bits 0-3 are the volume; bits 4-7 are filter mode and the voice-3-off
// switch, all of which must stay clear or voice 3 disappears.
.const SFX_VOLUME     = $0f

// Waveform select bits, for readability at the tables below.
.const SID_GATE       = %00000001
.const SID_GATE_OFF   = %11111110       // the mask that drops the gate and
                                        // leaves the waveform selected
.const SID_PULSE      = %01000000
.const SID_SAW        = %00100000
.const SID_NOISE      = %10000000
.const SID_TRI        = %00010000
// NOISE IS NEVER COMBINED WITH ANOTHER WAVEFORM. On real hardware selecting
// noise together with a second waveform empties the noise shift register and
// the voice goes quiet until the register is re-seeded, which on a 6581 means
// a reset. Every control byte in this file selects exactly one waveform bit.

// --- the effects ------------------------------------------------------------
// An id is an index into every effect table in this file, so SFX_NONE must be
// zero: "no effect" is then the same byte as "this channel is idle" and the
// idle test in sfxTick is one load and one branch.
.const SFX_NONE       = 0
.const SFX_FIRE       = 1               // the player's cannon
.const SFX_KILL       = 2               // an enemy or a turret destroyed
.const SFX_HURT       = 3               // the player takes damage
.const SFX_ESHOT      = 4               // a moving enemy fires
.const SFX_TOKEN      = 5               // the player collects a token
.const SFX_PING       = 6               // the Orbital Dropper's sonar locator
.const SFX_LAUNCH     = 7               // the victory exit: the ship leaving
.const SFX_LAUNCH_LEN = 60              // frames, and so sweep entries: 1.2 s,
                                        // about how long the exit itself takes.
                                        // Declared here rather than beside the
                                        // other sweep bases because sfxLenTab
                                        // names it and .const resolves in order.
.const SFX_COUNT      = 8

// --- the channels -----------------------------------------------------------
// One per SID voice, and the channel index is the voice number less one. An
// effect's channel is a constant of the effect, not a decision made at request
// time; see sfxVoiceTab.
.const SFX_CH_FIRE    = 0               // voice 1: frequent/light
.const SFX_CH_KILL    = 1               // voice 2: enemy/world
.const SFX_CH_HURT    = 2               // voice 3: high-impact/player
.const SFX_CHANNELS   = 3

// ===========================================================================
// State. MAIN THREAD ONLY. Nine bytes, outside VIC bank 0 with every other
// module's state, in the free run between the collision state that ends at
// $c5fe and the HUD state at $c960.
//
// THE CHANNEL STATE IS TWO PARALLEL THREE-BYTE ARRAYS rather than three
// structs, because every routine here walks the channels with an index and
// `lda sfxChId,x` is the whole of the walk.
// ===========================================================================
* = $c600 "sfx state"

// The effect playing on each voice, or SFX_NONE. Three bytes, three voices,
// and no relationship between them: this array IS the whole of the mixing
// policy, and its three entries are independent by construction.
sfxChId:     .byte 0, 0, 0

// How far into its effect each voice is, in frames: the index of the sweep
// entry sfxTick will play on THIS frame. It runs 0..len-1 through the sweep,
// then len (gate off, the envelope releases), then len+1 (the voice is cleared
// and the effect ends). So an effect occupies len + 2 frames.
sfxChFrame:  .byte 0, 0, 0

// The channel sfxTick is currently advancing, parked for the few instructions
// in which BOTH index registers are spoken for — the sweep step needs one for
// the sweep entry and one for the voice's register offset, and the channel
// index has nowhere else to be. Written and read inside sfxTick only.
sfxCurCh:    .byte 0

// --- diagnostics, saturating like every other counter in this engine --------
// It is how a test, or a person at the monitor, distinguishes "the hook never
// fired" from "the hook fired and the sound was wrong".
sfxRequests: .byte 0

// ...AND THE REJECTION COUNTER IS BACK. It was removed when global priority
// was: with a voice per effect nothing could be refused and the byte was
// provably always zero. The Dropper's sonar ping reintroduces exactly one way
// for a request to be turned away -- a routine voice-2 effect arriving during
// the ping's four frames -- so this counts those, and a test can tell that the
// ping was genuinely protected rather than merely lucky.
sfxRefused:  .byte 0

// The requested id, parked here for the length of sfxRequest. It is here and
// not on the stack because the caller's X has to be saved BEFORE the id can be
// moved into X, and reading a pushed byte back off the stack to get around
// that is three lines of pointer arithmetic standing in for one store.
sfxReqId:    .byte 0

sfxStateEnd:
.if (sfxStateEnd > $c610) { .error "the sfx state has grown past its $c610 ceiling" }

// ===========================================================================
// Code. MAIN THREAD ONLY.
//
// $1000-$1fff is the region the VIC sees the CHARACTER ROM in, so RAM there is
// invisible to it and is the correct home for resident CPU-only code — the
// schedule builder, the HUD code and the sorter already live in it. This lands
// in the free run between the HUD code, which ends at $1768, and the sorter at
// $1e00.
//
// IT IS RESIDENT AND IT IS NOT VIC CAPACITY. Nothing here is level-replaceable
// and nothing here costs a sprite block or a character. It also survives the
// planned boss VIC-bank switch untouched: $1000-$1fff is plain RAM to the CPU
// whichever bank the VIC is looking at.
// ===========================================================================
* = $1780 "sfx"

// ---------------------------------------------------------------------------
// sfxInit — the cold start. Called ONCE, from entry, before the renderer owns
// the IRQ.
//
// Every one of the SID's 25 registers is written to a known value. This is the
// only place this subsystem touches anything outside the three voices, and it
// is a boot-time action rather than a per-frame one: power-on SID state is not
// defined, a previously running program's state certainly is not, and an
// engine that zeroes its VIC idle byte by construction rather than by luck
// should not leave the sound chip to chance either.
//
// THE ORDER MATTERS SLIGHTLY: volume is written after the clear, or the clear
// would put it back to zero and the machine would be silent for good.
// ---------------------------------------------------------------------------
sfxInit:
    lda #0
    ldx #SID_LAST - SID                 // 24, counting down to 0 inclusive
!clear:
    sta SID,x
    dex
    bpl !clear-

    lda #SFX_VOLUME
    sta SID_VOLUME

    lda #0
    sta sfxRequests
    sta sfxRefused
    // fall through: the voices' own silence, and the state that describes it

// ---------------------------------------------------------------------------
// sfxSilence — all three voices off and nothing playing. THE THREE SFX VOICES
// ONLY: $d415-$d418 are not touched, so a restart cannot undo the master
// volume, and a future menu-music driver's filter setup survives a return to
// gameplay.
//
// Called by gameInit, so every start and every future restart, death or
// return-to-menu leaves the chip deterministic without that code having to
// know what a voice is. The loop runs over the channel array rather than over
// three literal addresses: adding a fourth effect to an existing voice must
// not be able to leave a fourth thing un-silenced.
// ---------------------------------------------------------------------------
sfxSilence:
    lda #0
    ldx #SFX_CHANNELS - 1
!chan:
    ldy sfxVoiceBase,x
    sta SID_CTRL,y                      // gate low and no waveform selected
    sta sfxChId,x
    sta sfxChFrame,x
    dex
    bpl !chan-
    rts

// ---------------------------------------------------------------------------
// sfxRequest — "this happened". A = the effect id. MAIN THREAD.
//
// X AND Y ARE PRESERVED, and the contract is deliberate rather than
// incidental: every hook site in this game is in the middle of a loop over a
// pool slot or a turret index — applyDamage documents "X = the target,
// preserved" in its own header — and a sound request that quietly ate X would
// be a corruption bug in the system that made the noise, not in this file.
// Twenty-two cycles of push and pull, on an event that happens a few times a
// second at most, buys a two-instruction insertion that cannot break its host.
// A is NOT preserved: every caller passes the id in it and wants nothing back.
//
// THERE IS NO ACCEPT TEST. A request goes to its effect's own voice and starts
// it, whatever that voice was doing, and it cannot reach the other two. The
// only thing it can interrupt is ITSELF — held fire restarting the report,
// which is what makes held fire sound like repeated shots, and a second enemy
// dying restarting the crunch, which is what makes the second death audible.
// Nothing is queued and nothing is refused: a queue would make a 100 ms report
// arrive after the thing that delayed it, which is worse than not hearing it.
//
// WHAT IS WRITTEN HERE AND WHAT IS LEFT TO sfxTick. This routine writes the
// envelope and ZEROES THE CONTROL REGISTER; the waveform, the gate and the
// opening frequency are sfxTick's, on this same frame. That split is not an
// arbitrary one:
//
//   * the envelope generator retriggers on the RISING EDGE of the gate bit and
//     on nothing else, so a still-decaying effect that is re-requested must see
//     its gate go low before it goes high again or the new sound inherits the
//     old one's envelope and fades instead of striking. The zero written here
//     IS that falling edge;
//   * every request in the game is made before sfxTick runs — gameFrame calls
//     weaponTick, collisionTick and ebulletPlayerTick above it — so frame 0 of
//     the effect is programmed onto the chip microseconds later, on the frame
//     the event happened, by the same code that programs frame 1;
//   * and it means the gate is raised in exactly ONE place in this file
//     instead of two that have to be kept saying the same thing.
//
// DETERMINISTIC WITHIN A FRAME. Two requests for the same effect in one frame
// leave the later one playing from frame 0; requests for different effects do
// not interact at all.
// ---------------------------------------------------------------------------
sfxRequest:
    sta sfxReqId                        // the id, before X is needed for it
    txa
    pha
    tya
    pha
    ldx sfxReqId                        // X indexes the effect tables

    lda sfxVoiceTab,x
    tay                                 // Y = the effect's channel, 0..2

    // ---- IS THE VOICE PROTECTED RIGHT NOW? --------------------------------
    // Exactly one sound in this game is protected, and it is protected from
    // exactly one class of thing, so this is a RULE and deliberately not a
    // ranking. The requirement the Dropper ping imposes is:
    //
    //     the ping outranks a routine voice-2 effect...  ping > eshot, token
    //     ...but a destruction outranks the ping...      kill >= ping
    //     ...and those two are still peers as before     kill == eshot
    //
    // which no single priority NUMBER can express -- give kill a rank above
    // the ping and an enemy shot stops being audible during a destruction,
    // which is behaviour nobody asked to change. So the test names the one
    // protected sound instead of ranking all six.
    //
    // THE PING DOES NOT RESERVE VOICE 2. This looks at what is PLAYING, and
    // sfxChannel returns the voice to SFX_NONE the moment an effect finishes
    // -- so between pings, which is most of the time, the first instruction
    // below falls straight through and voice 2 behaves exactly as it always
    // did. A Dropper overhead costs the world its enemy sounds for four
    // frames in forty-eight.
    //
    // AND A DESTRUCTION IS NEVER MASKED. The one moment the ping must give way
    // is the Dropper's own death: that is the feedback that ends the encounter
    // it was announcing, and hearing the locator survive the thing it was
    // locating would be absurd. SFX_KILL is let through.
    lda sfxChId,y
    cmp #SFX_PING
    bne !accept+                        // nothing else is ever protected
    lda sfxReqId
    cmp #SFX_PING
    beq !accept+                        // a ping may retrigger a ping
    cmp #SFX_KILL
    beq !accept+                        // ...and a destruction ends one

    lda sfxRefused                      // saturating: that a sound was held
    cmp #$ff                            // off is worth being able to see
    beq !out+
    inc sfxRefused
    jmp !out+                           // X and Y are restored there

!accept:
    txa
    sta sfxChId,y
    lda #0
    sta sfxChFrame,y

    lda sfxVoiceBase,y
    tay                                 // Y = that voice's register offset.
                                        // X is still the id: from here the
                                        // effect tables are read with X and
                                        // the chip is written with Y.
    lda #0
    sta SID_CTRL,y                      // GATE LOW. See the header: this is
                                        // the falling edge that makes sfxTick's
                                        // frame 0 a genuine retrigger.
    lda sfxADTab,x
    sta SID_AD,y
    lda sfxSRTab,x
    sta SID_SR,y

    lda sfxPWHiTab,x
    sta SID_PW_HI,y                     // ONLY the enemy shot selects pulse, so
                                        // only it reads this; the other three
                                        // write a defined zero rather than
                                        // inherit the last effect's duty. The
                                        // low byte is never written at all --
                                        // sfxInit zeroed it and duty is twelve
                                        // bits of which four are worth an
                                        // effect's time.

    lda sfxRequests                     // saturating: that sound was asked for
    cmp #$ff                            // is the fact; the exact count past
    beq !out+                           // 255 is not
    inc sfxRequests
!out:
    pla
    tay
    pla
    tax
    rts

// ---------------------------------------------------------------------------
// sfxTick — one frame of sound, for all three voices. MAIN THREAD, once per
// displayed frame.
//
// THE COST IS PER PLAYING VOICE, and counted rather than guessed. A silent
// voice is a load, a branch and the loop's own three instructions — 14 cycles
// — so the quiet frame that most frames are costs 55 including the jsr from
// gameFrame. A voice in its sweep costs 92, the most expensive of the three
// phases, so the worst frame this game can currently produce — fire, a
// destruction and the ship being hit all sounding at once — is about 290
// cycles. Against a PAL budget of 19,656 that is 1.5%, and it is the entire
// recurring cost of sound in this game: there is no sequencer, no note list
// and no per-object audio work of any kind.
//
// v1 was 12 cycles idle on its single voice. The extra 43 buys two more voices
// and is spent on the two `beq`s that find them silent.
//
// The channels are advanced in order 0, 1, 2 and NOTHING IS SHARED BETWEEN
// THEM: each iteration reads and writes only its own two state bytes and its
// own seven SID registers, so the order is a fact about the code rather than
// about the sound.
// ---------------------------------------------------------------------------
sfxTick:
    ldx #0
!chan:
    lda sfxChId,x
    beq !next+                          // this voice is idle: nothing to do,
                                        // and nothing written to the chip
    jsr sfxChannel
!next:
    inx
    cpx #SFX_CHANNELS
    bcc !chan-
    rts

// ---------------------------------------------------------------------------
// sfxChannel — advance ONE voice by one frame. X = the channel, A = the effect
// playing on it, which sfxTick has already established is not SFX_NONE.
//
// The frame counter walks an effect through three phases:
//
//     0 .. len-1   the sweep: one frequency AND one control byte per frame
//                  from the effect's slice of the sweep tables. All three
//                  effects currently hold one gated waveform for the length of
//                  their sweep, so that byte is the same every frame and the
//                  chip treats the rewrite as no change at all; it is per-frame
//                  because that is where the gate lives, in ONE place, and an
//                  effect that wants to move its gate mid-flight moves it in
//                  data rather than in code
//     len          gate low. The envelope enters release; the waveform is left
//                  selected so the release is heard rather than chopped
//     len+1        the control register is cleared outright and the voice goes
//                  back to idle
// ---------------------------------------------------------------------------
sfxChannel:
    tay                                 // Y = the effect id, for its tables
    lda sfxChFrame,x
    cmp sfxLenTab,y
    bcc !sweep+
    bne !finish+

    // ---- frame len: release -----------------------------------------------
    lda sfxCtrlTab,y                    // the effect's waveform, gate dropped
    and #SID_GATE_OFF
    ldy sfxVoiceBase,x
    sta SID_CTRL,y
    inc sfxChFrame,x
    rts

    // ---- frame len+1: done ------------------------------------------------
    // The voice is left with no waveform and no gate, which is the state
    // sfxInit put it in at boot. Nothing decays from here and nothing sounds.
!finish:
    lda #0
    sta sfxChId,x
    sta sfxChFrame,x                    // sfxRequest would reset this anyway.
                                        // It is cleared here so that IDLE IS
                                        // ONE STATE and not two -- "nothing
                                        // playing, frame index left wherever
                                        // the last effect stopped" is the kind
                                        // of half-swept state that makes a
                                        // reader wonder which of two bytes to
                                        // believe
    ldy sfxVoiceBase,x
    sta SID_CTRL,y
    rts

    // ---- frames 0..len-1: the sweep ---------------------------------------
    // BOTH INDEX REGISTERS ARE SPOKEN FOR HERE — the sweep entry indexes three
    // tables and the voice offset indexes three SID registers — so the channel
    // index is parked in sfxCurCh for the eight instructions in between. A is
    // the frame index on the way in.
!sweep:
    stx sfxCurCh
    clc
    adc sfxBaseTab,y                    // + the effect's slice of the one
                                        // shared sweep table
    ldy sfxVoiceBase,x                  // Y = this voice's register offset
    tax                                 // X = the sweep entry
    lda sfxSweepLo,x
    sta SID_FREQ_LO,y
    lda sfxSweepHi,x
    sta SID_FREQ_HI,y
    lda sfxSweepCtrl,x
    sta SID_CTRL,y
    ldx sfxCurCh
    inc sfxChFrame,x
    rts

// ===========================================================================
// THE VOICE MAP
// ===========================================================================
// Two tables and no logic. An effect's voice is a constant of the effect, so
// "which voice is free" is a question this subsystem never asks and never has
// to answer consistently twice.
// ---------------------------------------------------------------------------
sfxVoiceTab:                            // by effect id: the channel it owns
    .byte 0                             // SFX_NONE, never read
    .byte SFX_CH_FIRE                   // player fire      -> voice 1
    .byte SFX_CH_KILL                   // enemy/turret     -> voice 2
    .byte SFX_CH_HURT                   // the ship is hit  -> voice 3
    .byte SFX_CH_KILL                   // an enemy fires   -> voice 2
    .byte SFX_CH_KILL                   // a token collected-> voice 2
    .byte SFX_CH_KILL                   // the Dropper ping -> voice 2
    .byte SFX_CH_HURT                   // the victory launch-> voice 3.
                                        // VOICE 3 BECAUSE IT IS THE QUIET ONE.
                                        // The launch runs for over a second,
                                        // which is longer than anything else on
                                        // the chip, and voice 3 carries only
                                        // the player-damage wail -- an effect
                                        // that cannot happen during a victory,
                                        // since plyExit makes the ship
                                        // invulnerable before the sound starts.
                                        // Voices 1 and 2 would have been cut by
                                        // the gun and by world effects, neither
                                        // of which is silent by construction.
                                        //
                                        // THREE EFFECTS ON ONE VOICE, and the
                                        // arbitration is the one this module
                                        // already has: whichever asked last
                                        // plays. A destruction, an enemy shot
                                        // and a token are all WORLD events of
                                        // 100-280 ms, and the collisions
                                        // between them are moments where the
                                        // later event is the one worth hearing.
                                        //
                                        // THE TOKEN IS NOT ON VOICE 1, though
                                        // this module's own v1.1 note predicted
                                        // "a pickup chime joins voice 1 with
                                        // the other light traffic". Measured
                                        // against the game that now exists,
                                        // that would be inaudible: held fire
                                        // retriggers voice 1 every eight frames
                                        // and the report itself occupies five
                                        // of them, so a chime started there is
                                        // cut off within three frames whenever
                                        // the player is shooting -- which is
                                        // almost always. Voice 3 was rejected
                                        // for the opposite reason: it would
                                        // work, but it would cut the
                                        // player-damage wail, and losing the
                                        // one sound that says YOU HAVE BEEN HIT
                                        // to a bonus chime is the worst trade
                                        // available. Voice 2 loses only an
                                        // occasional enemy noise, which is the
                                        // cheapest thing on the chip to lose.

sfxVoiceBase:                           // by channel: the SID register offset
    .byte 0 * SID_VOICE_LEN             // $d400
    .byte 1 * SID_VOICE_LEN             // $d407
    .byte 2 * SID_VOICE_LEN             // $d40e

// ===========================================================================
// THE THREE EFFECTS
// ===========================================================================
// Each is four numbers and a slice of the sweep tables. There is no instrument
// format here and there is deliberately no way to author a fourth effect
// without editing this file — three hand-written sounds do not need a
// language, and a language is what this would have to become to be worth
// having.
//
// EVERY EFFECT HAS SUSTAIN ZERO, so its envelope falls to silence by itself
// and its DECAY, not the frame count, is what the ear hears as the length. The
// sweep length is chosen to run out at about the same time as the decay: a
// sweep much longer than its decay is frames spent moving an inaudible
// oscillator, and one much shorter cuts the sound off mid-fall.
//
// Tables are indexed by effect id, so entry 0 is SFX_NONE and is never read.
// ---------------------------------------------------------------------------
// PLAYER FIRE — ONE HEAVY BALLISTIC REPORT, 3 frames of sweep, ~100 ms.
//
//   ONE VOLLEY IS ONE REPORT, and that is the whole rule. v1 fired a pulse
//   chirp, which was a laser; the first pass at v1.1 fired a three-round burst
//   inside the effect, which was a second rhythm competing with the one the
//   game already has. THE GAME'S RHYTHM IS WPN_FIRE_PERIOD. Held fire is a
//   volley every eight frames, and a machine gun is what that cadence already
//   sounds like when each volley is a single hard report. Synthesising a
//   rat-tat-tat on top of it made a tap on the trigger produce three rounds,
//   which is a gun the player is not holding.
//
//   SO THE GATE IS RAISED ONCE. Three frames of noise under one envelope:
//
//       frame 0   gate high   the crack — noise at $2600, struck, not swelled
//       frame 1   gate high   the body  — $1900
//       frame 2   gate high   the thud  — $1000
//       frame 3   (len)       release
//       frame 4   (len+1)     the voice is put away
//
//   THE WEIGHT IS IN THE FALL. The noise oscillator drops through more than an
//   octave in 60 ms, which the ear hears as a report COLLAPSING — the shape a
//   heavy round has and a click does not. It is the same gesture the
//   destruction crunch makes, at a fifth of the length and starting an octave
//   and a half lower, which is what keeps a shot from sounding like a small
//   explosion.
//
//   ATTACK 0 INTO A 72 ms DECAY, GATED FOR 60. The envelope is well down by the
//   time the gate drops and the 6 ms release finishes it, so the report ends by
//   itself rather than being chopped, and there is NO TAIL to run into the next
//   volley.
//
//   IT TERMINATES WITH ROOM TO SPARE. 3 + 2 = 5 frames against a legal volley
//   every 8 leaves THREE clear frames of silence before another shot is even
//   possible. A retrigger arriving early — the trigger tapped again out of
//   phase — restarts the report cleanly on voice 1, because sfxRequest drops
//   the gate before sfxChannel raises it. One trigger tap, one report.
//
// ENEMY DESTRUCTION — a noise burst, 12 frames of sweep, ~280 ms. UNCHANGED
// from v1 in every number; it has moved from voice 3 to voice 2 and nothing
// else about it is different.
//
//   NOISE, sweeping from bright down to a low rumble: a crunch that collapses.
//   It is nearly three times the length of a shot and carries a 240 ms decay,
//   so a destruction and the shot that caused it now sound TOGETHER, on two
//   voices, which is the whole reason for this revision.
//
// PLAYER HIT — a sawtooth wail, 30 frames of sweep, ~640 ms. UNCHANGED from v1
// in every number; it stays on voice 3.
//
//   THE ONE SOUND THAT IS NOT NOISE, because being obviously different from an
//   enemy exploding matters more than anything else about it. A SAWTOOTH
//   falling 600 Hz to 64 Hz over six-tenths of a second, under a 750 ms decay,
//   is the ship's systems dying: it is the longest sound in the game by a
//   factor of two, it descends through three and a half octaves into a buzz,
//   and there is nothing else in the mix it can be confused with. It cannot
//   stack — plyInvuln refuses a second hit for 100 frames, which is three
//   times this effect's length — and it can no longer be interrupted by the
//   player's own gun, which on one voice it could be.
// ===========================================================================
sfxCtrlTab:                             // the effect's waveform, read on the
    .byte 0                             // release frame. The per-frame control
    .byte SID_NOISE | SID_GATE          // bytes live in sfxSweepCtrl below;
    .byte SID_NOISE | SID_GATE          // this is the one the gate is dropped
    .byte SID_SAW   | SID_GATE          // from when the sweep runs out
    .byte SID_PULSE | SID_GATE          // the enemy shot, and the only pulse
    .byte SID_TRI   | SID_GATE          // the token chime, and the only triangle
    .byte SID_PULSE | SID_GATE          // the sonar ping: pulse, but at a duty
                                        // nothing else uses -- see sfxPWHiTab
    .byte SID_SAW   | SID_GATE          // the victory launch: a sawtooth is an
                                        // ENGINE -- every harmonic present, and
                                        // the one waveform that still reads as
                                        // thrust while it climbs

sfxADTab:                               // attack 0 throughout: every one of
    .byte 0                             // these strikes rather than swells
    .byte $03                           // decay 3 -> 72 ms, one hard report
    .byte $07                           // decay 7 -> 240 ms
    .byte $09                           // decay 9 -> 750 ms
    .byte $03                           // decay 3 -> 72 ms: a spit, not a note
    .byte $05                           // decay 5 -> 168 ms: a chime may ring
    .byte $06                           // decay 6 -> 204 ms: the ping RINGS,
                                        // which is the whole character of it.
                                        // The gate is only held for 80 ms; the
                                        // rest of what the ear hears is this
                                        // envelope falling away

sfxSRTab:                               // SUSTAIN ZERO, ALWAYS. See above.
    .byte 0
    .byte $00                           // release 0 -> 6 ms: no tail
    .byte $00
    .byte $00
    .byte $00
    .byte $00
    .byte $00
    .byte $00                           // the launch too: its length comes from
                                        // a long DECAY, never from sustain

// PULSE DUTY, high four bits of twelve, and only the enemy shot reads it. The
// low byte is the zero sfxInit wrote at boot and nothing changes it: duty is
// twelve bits and only the top four are worth an effect's time.
sfxPWHiTab:
    .byte 0
    .byte 0                             // noise: unused
    .byte 0                             // noise: unused
    .byte 0                             // sawtooth: unused
    .byte $02                           // 12.5% of a nibble -- thin, hard and
                                        // buzzy, which is what makes it read as
                                        // machinery rather than as a tone
    .byte 0                             // triangle: unused
    .byte $08                           // 50% -- a hollow square, and the one
                                        // duty in this game that is not the
                                        // enemy shot's thin $02. Pure enough to
                                        // read as a locator tone, hard enough
                                        // not to be mistaken for the token's
                                        // triangle chime on the same voice
    .byte 0                             // sawtooth: unused

sfxLenTab:                              // sweep entries, and so frames
    .byte 0, 3, 12, 30, 3, 6, 4, SFX_LAUNCH_LEN

// Where each effect's slice of the shared sweep table starts. Stated before
// the table that names them: KickAssembler resolves .const strictly in order.
.const SFX_FIRE_SWEEP  = 0
.const SFX_KILL_SWEEP  = 3
.const SFX_HURT_SWEEP  = 15
.const SFX_ESHOT_SWEEP = 45
.const SFX_TOKEN_SWEEP = 48
.const SFX_PING_SWEEP  = 54
.const SFX_LAUNCH_SWEEP = 58

.const SFX_SWEEP_LEN   = 118

sfxBaseTab:                             // first sweep entry, by id
    .byte 0, SFX_FIRE_SWEEP, SFX_KILL_SWEEP, SFX_HURT_SWEEP, SFX_ESHOT_SWEEP
    .byte SFX_TOKEN_SWEEP, SFX_PING_SWEEP, SFX_LAUNCH_SWEEP

// ---------------------------------------------------------------------------
// THE SHARED SWEEP TABLES. Three effects' per-frame data laid end to end, each
// named by its base offset above, so sfxChannel indexes with a single add
// instead of choosing between three sets of tables.
//
// Frequencies are SID register units for PAL: register = Hz * 16777216 /
// 985248, i.e. Hz * 17.028. NTSC would want a different table and this game is
// PAL. The noise ramps are written as raw register values rather than as
// frequencies because noise has no pitch — the number sets how fast the shift
// register is clocked, which the ear hears as brightness.
//
// sfxSweepCtrl IS THE PER-FRAME CONTROL BYTE, and it is the only place in this
// file where the gate moves mid-effect. For the two effects that hold one
// note the entries are identical all the way down, and writing the same
// control byte again is not an edge and not a retrigger — the chip sees no
// change. No effect moves its gate mid-sweep today — the fire report is struck
// once and held — so every entry below is its effect's gated waveform, and the
// column exists so that an effect which DOES want to restrike can say so here
// without sfxChannel learning a special case.
// ---------------------------------------------------------------------------
sfxSweepLo:
    // fire: one report, held gated while its noise pitch collapses
    .byte $00, $00, $00
    // kill: noise, bright down to a rumble
    .byte $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00
    // hurt: 600 Hz down to 64 Hz
    .byte $e9, $ea, $eb, $ec, $ee, $ef, $f0, $13, $47, $9e
    .byte $05, $7d, $07, $a1, $5e, $2b, $0a, $f9, $0b, $2d
    .byte $61, $a6, $fb, $51, $b8, $30, $a7, $30, $b9, $42
    // enemy shot: 1800, 1200, 800 Hz -- a fast downward spit
    .byte $bb, $d2, $37
    // token: 800, 1000, 1300, 1600, 2000, 2400 Hz -- a RISING chime. Every
    // other effect in this game falls; a reward is the one thing that should
    // go up, and the direction alone tells the player it was good news.
    .byte $37, $84, $79, $6d, $09, $a4
    // ping: 2100, 2040, 1980, 1925 Hz -- a SETTLE, not a sweep. Four frames
    // across barely a whole tone, which the ear hears as one pitch with a
    // slight give in it: the give is what stops a pure square reading as a
    // test tone and makes it read as a locator.
    .byte $b0, $b2, $b4, $0c
    // launch: the curve is weighted so it starts slowly and then runs
    // away -- the same shape as the acceleration it describes
    .byte $f9, $19, $61, $c8, $4a, $e5, $98, $61, $40, $32
    .byte $39, $52, $7e, $bc, $0b, $6c, $de, $60, $f2, $94
    .byte $46, $08, $d9, $b8, $a7, $a4, $b0, $ca, $f2, $28
    .byte $6c, $bd, $1c, $89, $03, $8a, $1e, $bf, $6d, $28
    .byte $ef, $c3, $a3, $90, $89, $8f, $a0, $bd, $e7, $1c
    .byte $5d, $aa, $03, $67, $d6, $51, $d8, $6a, $07, $b0

sfxSweepHi:
    .byte $26, $19, $10
    .byte $42, $3a, $32, $2b, $24, $1e, $19, $14, $10, $0c, $09, $06
    .byte $27, $25, $23, $21, $1f, $1d, $1b, $1a, $18, $16
    .byte $15, $13, $12, $10, $0f, $0e, $0d, $0b, $0b, $0a
    .byte $09, $08, $07, $07, $06, $06, $05, $05, $04, $04
    .byte $77, $4f, $35
    .byte $35, $42, $56, $6a, $85, $9f
    .byte $8b, $87, $83, $80
    // launch: 180 Hz climbing to 2100 Hz over sixty frames
    .byte $0b, $0c, $0c, $0c, $0d, $0d, $0e, $0f, $10, $11
    .byte $12, $13, $14, $15, $17, $18, $19, $1b, $1c, $1e
    .byte $20, $22, $23, $25, $27, $29, $2b, $2d, $2f, $32
    .byte $34, $36, $39, $3b, $3e, $40, $43, $45, $48, $4b
    .byte $4d, $50, $53, $56, $59, $5c, $5f, $62, $65, $69
    .byte $6c, $6f, $73, $76, $79, $7d, $80, $84, $88, $8b

sfxSweepCtrl:
    // fire: struck once, and held for the length of the sweep
    .byte SID_NOISE | SID_GATE, SID_NOISE | SID_GATE, SID_NOISE | SID_GATE
    // kill: one gated noise burst held across the whole sweep
    .byte SID_NOISE | SID_GATE, SID_NOISE | SID_GATE, SID_NOISE | SID_GATE
    .byte SID_NOISE | SID_GATE, SID_NOISE | SID_GATE, SID_NOISE | SID_GATE
    .byte SID_NOISE | SID_GATE, SID_NOISE | SID_GATE, SID_NOISE | SID_GATE
    .byte SID_NOISE | SID_GATE, SID_NOISE | SID_GATE, SID_NOISE | SID_GATE
    // hurt: one gated sawtooth held across the whole sweep
    .fill 30, SID_SAW | SID_GATE
    // enemy shot: one gated pulse, struck once and held
    .fill 3, SID_PULSE | SID_GATE
    // token: one gated triangle, struck once and held while the pitch climbs
    .fill 6, SID_TRI | SID_GATE
    // ping: one gated pulse, struck once. Short on purpose -- the sound is
    // mostly its own decay, and the silence after it is half the cue
    .fill 4, SID_PULSE | SID_GATE
    // launch: one gated sawtooth, held while the pitch climbs
    .fill 60, SID_SAW | SID_GATE

// --- the tables must agree with each other, and the assembler can say so ----
.if (sfxSweepHi - sfxSweepLo != SFX_SWEEP_LEN)   { .error "the sweep low-byte table is not SFX_SWEEP_LEN entries" }
.if (sfxSweepCtrl - sfxSweepHi != SFX_SWEEP_LEN) { .error "the sweep high-byte table is not SFX_SWEEP_LEN entries" }
.if (* - sfxSweepCtrl != SFX_SWEEP_LEN)          { .error "the sweep control table is not SFX_SWEEP_LEN entries" }
.if (SFX_FIRE_SWEEP + 3  != SFX_KILL_SWEEP)      { .error "the fire sweep does not end where the kill sweep begins" }
.if (SFX_KILL_SWEEP + 12 != SFX_HURT_SWEEP)      { .error "the kill sweep does not end where the hurt sweep begins" }
.if (SFX_HURT_SWEEP + 30 != SFX_ESHOT_SWEEP)     { .error "the hurt sweep does not end where the enemy-shot sweep begins" }
.if (SFX_ESHOT_SWEEP + 3 != SFX_TOKEN_SWEEP)     { .error "the enemy-shot sweep does not end where the token sweep begins" }
.if (SFX_TOKEN_SWEEP + 6 != SFX_PING_SWEEP)      { .error "the token sweep does not end where the ping sweep begins" }
.if (SFX_PING_SWEEP + 4 != SFX_LAUNCH_SWEEP)     { .error "the ping sweep does not end where the launch sweep begins" }
.if (SFX_LAUNCH_SWEEP + SFX_LAUNCH_LEN != SFX_SWEEP_LEN) { .error "the launch sweep does not end where the table does" }

.if (* > $1e00) { .error "the sfx module has run into the sorter at $1e00" }
