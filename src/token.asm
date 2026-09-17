// ===========================================================================
// token.asm — the token encounter: the P, and the three enemies guarding it
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is written from this file and no
// hardware sprite is named in it. Everything here moves LOGICAL coordinates of
// ordinary pool objects; the sorter, the builder and the multiplexer draw the
// result without knowing an encounter is running.
//
// WHAT THIS IS. Destroying the level's one Dropper drops a P token at the spot
// it died, and the enemies already on screen stop flying their authored paths
// and reorganise into exactly three defenders around it. Kill the defenders or
// take the token and the encounter ends; the survivors leave and the authored
// stage resumes.
//
//     Dropper destroyed
//       -> token spawned at the captured death position
//       -> live enemies reassigned: three become GUARDS, the surplus EGRESS
//       -> a deficit is made up by rapid reinforcement
//       -> guards converge, then orbit the descending token
//       -> token collected or lost off the bottom
//       -> reinforcement stops, survivors egress, normal waves resume
//
// WHAT IT IS NOT. There is no formation AI, no steering behaviour, no
// pathfinding and no per-enemy personality. A guard walks toward one point on a
// rotating ring and stops when it gets there. That is the whole movement model,
// and it is deliberately the cheapest thing that reads as "those three are
// defending that pickup".
//
// ---------------------------------------------------------------------------
// WHY A ROLE BYTE AND NOT A DERIVED STATE
// ---------------------------------------------------------------------------
// enyRole is one byte per POOL SLOT, and it is the only thing that says an
// enemy has left its authored path. It is never inferred from species, sprite
// pointer, colour, wave, movement mode or pool index -- every one of which is
// shared, authored, or rewritten by gameplay. A guard is a guard because this
// byte says so, and objectZeroSlot clears it with the rest of the slot so a
// recycled slot cannot inherit a role from its previous occupant.
//
// THE ROLE ALSO CARRIES THE STATION. ROLE_GUARD + 0, +1 and +2 are the three
// posts around the ring, so "is this enemy a guard" and "which post is it" are
// one load and one compare rather than two bytes that could disagree.
// ===========================================================================

// ROLE_NORMAL / ROLE_EGRESS / ROLE_GUARD are declared in src/objects.asm,
// beside TYPE_*, because src/enemy.asm compares against ROLE_GUARD and is
// imported long before this file. The pool declares per-slot meanings; this
// file is the only thing that ever writes one other than ROLE_NORMAL.
.const TK_GUARDS     = 3        // posts around the ring; the encounter's target

// --- the ring the guards walk ------------------------------------------------
// TWENTY-FOUR PHASES BECAUSE THREE DIVIDES IT. The posts sit a third of the
// ring apart, so each post is exactly TK_ORBIT_SPAN phases from the next and
// the offsets come out of one table with no arithmetic beyond an add.
//
// v2 USED TWELVE, AND TWELVE IS WHY IT READ AS A TRIANGLE. A guard walked to a
// vertex, arrived, and waited there for half the hold; all three did it on the
// same frame, so the eye saw one rigid shape teleporting between poses rather
// than three things going round. Halving the arc per phase halves the size of
// every direction change, and the cadence below removes the waiting.
//
// The ring is WIDER THAN IT IS TALL (46 by 30) on purpose: the token descends
// through a 193-raster aperture and the player approaches from below, so a
// circular ring would spend its vertical extent hiding the token behind a guard
// exactly when the player is lining up on it. A flattened ring keeps the
// approach open and still reads as an orbit.
//
// v2.1 WIDENED IT from 30 by 20, which sat close enough to the token that the
// three guards read as decoration on it rather than as a patrol around it.
.const TK_ORBIT_STEPS = 24
.const TK_ORBIT_SPAN  = TK_ORBIT_STEPS / TK_GUARDS      // 8 phases between posts
.const TK_RADIUS_X    = 46
.const TK_RADIUS_Y    = 30

// ONE PHASE EVERY TK_ORBIT_HOLD FRAMES, AND THE NUMBER IS MATCHED TO THE STEP
// RATE RATHER THAN CHOSEN BY EYE. The two failure modes sit either side of it:
//
//   hold too SHORT   the target outruns the guard, which never arrives and
//                    trails the ring as a lagging comma
//   hold too LONG    the guard arrives early and then sits still until the
//                    phase turns, which is the v2 triangle
//
// The ring's circumference is about 241 px, so a phase is 241/24 = 10.1 px of
// arc, and its steepest quarter demands 12.0 px on one axis. A guard closes
// TK_STEP px per axis per frame:
//
//     4 frames x 3 px = 12 px of travel for 10.1 px of typical demand
//
// -- which is the matched case: the guard is moving on very nearly every frame
// and is never more than a fraction of a step behind. A full revolution is 96
// frames, 1.92 s of PAL.
//
// IT MUST BE A POWER OF TWO. tokenGuardMove derives a guard's phase from the
// free-running frame counter by shifting, which is what buys the per-guard
// stagger below for nothing; a hold that was not a power of two would need a
// division there.
.const TK_ORBIT_HOLD  = 4
.if (TK_ORBIT_HOLD != 4) {
    .error "TK_ORBIT_HOLD is shifted by two in tokenGuardMove; change both together"
}

// The whole cycle, as a frame count: one revolution of the ring. tkOrbit counts
// frames through this and wraps, so a phase is a shift of it rather than a
// second counter that could disagree with the first.
.const TK_ORBIT_PERIOD = TK_ORBIT_STEPS * TK_ORBIT_HOLD     // 96 frames
.if (TK_ORBIT_PERIOD > 255) {
    .error "the orbit period no longer fits in the single byte tkOrbit"
}
.if (TK_ORBIT_SPAN != 8) {
    .error "tokenGuardMove multiplies the post by TK_ORBIT_SPAN with three ASLs"
}

// HOW FAST A GUARD CLOSES. Three pixels a frame converges the width of the
// playfield in about a second, which is what "reorganise quickly" has to mean
// for the transition to read as deliberate rather than as drift. It is also the
// snap threshold: inside three pixels the guard is placed exactly on its post,
// which is what stops it oscillating either side of a target it can never land
// on.
.const TK_STEP        = 3

// THE RING IS CLAMPED INTO THE PLAYFIELD. A token near either edge would put a
// post outside the nine-bit X world entirely -- and logX is UNSIGNED, so a post
// at -6 would not be off-screen, it would be at 250 on the far side. The clamp
// is on the TARGET rather than on the guard, so a guard whose post is clamped
// simply stacks against the edge with the others still spread.
.const TK_X_MIN       = 28
.const TK_X_MAX       = 330

// HOW OFTEN A MISSING GUARD IS REPLACED. Short, because the encounter is only
// interesting while it is three against one; long enough that a player killing
// guards faster than this cannot drive an unbounded spawn loop. One attempt per
// expiry, never a retry loop inside a frame: if the pool is busy the attempt is
// simply lost and the timer starts again.
.const TK_REINFORCE_FRAMES = 24

// Where a reinforcement enters. Above the aperture, so it FADES IN through the
// top edge the way every authored wave member does rather than appearing in
// view -- the guard movement then pulls it down to its post, which is what
// makes an arrival read as "another one is coming to defend it".
.const TK_SPAWN_Y     = 30

// ---------------------------------------------------------------------------
// HOW THE DISMISSED LEAVE, AND WHY THERE ARE TWO ANSWERS
// ---------------------------------------------------------------------------
// Both are WM_EXIT, which src/movement.asm documents as terminal and KEEPS
// whatever velocity it was given -- it has no direction of its own, so the
// direction is entirely the velocity below. src/enemy.asm's ordinary despawn
// rules retire both: a dismissed enemy is not deleted, it leaves, and it stays
// killable and collidable the whole way.
//
// DOWN, at the START of an encounter. The surplus is dismissed the instant the
// Dropper dies, when the player is still wherever they shot it from -- usually
// below and clear. Downward is the shortest way off a screen whose contents are
// already descending, and it reads as the formation being stood down.
.const TK_EGRESS_VY   = 24              // quarter pixels: 6 px a frame

// UP, at the END of one, AND THIS IS A SAFETY RULE RATHER THAN A LOOK. To
// collect the token the player has just flown INTO the middle of the ring, so
// at the moment the encounter ends the three survivors are arranged around the
// ship. Sending them down from there drives all three through the player as
// their reward -- v2 did exactly that, and it is the one thing manual play
// called unfair. They leave upward instead, away from the ship, across the
// airspace the player has just vacated.
//
// FASTER THAN THE DOWNWARD EGRESS, because this one is cleanup: the encounter
// is over, the reward is banked, and the screen should be given back promptly.
// Eight pixels a frame clears mid-aperture in about fifteen frames.
.const TK_EGRESS_UP_VY = 32             // quarter pixels: 8 px a frame, negated
                                        // at the point of use

// The colour a reinforcement wears. A guard that arrived mid-encounter is the
// same kind of thing as one that was reassigned, so it takes an ordinary wave
// colour rather than a special one -- the encounter is told by the FORMATION,
// not by a palette the player has to learn.
.const TK_GUARD_COL   = 10              // light red, as the sweep wave wears

// ===========================================================================
// State. MAIN THREAD ONLY, in the free run between the level asset state that
// ends at $c401 and the pickup state at $c4c0.
// ===========================================================================
// ONE BYTE LOWER THAN IT WAS, and deliberately so. The dropper flight state
// begins at $c462, immediately after this block, so there is no room to grow
// upward -- but there are sixty-two free bytes below. Starting here keeps every
// EXISTING field at exactly the offset from tkActive it already had, which is
// what the focused proofs read the block by.
* = $c43f "token encounter state"

// HOW MANY DEFENDERS THIS ENCOUNTER HAS EVER ENLISTED, and the whole of the
// attrition rule. The complement is assembled ONCE -- promoted from live
// enemies, topped up by reinforcement if there were not enough -- and once
// TK_GUARDS of them have been created the encounter is CLOSED. A defender the
// player destroys after that is simply gone.
//
// IT COUNTS CREATIONS, NOT OCCUPANCY, and that distinction is the point.
// tokenFreePost answers "is a post empty right now", which cannot tell the
// difference between a post never filled and a post whose guard has just been
// shot; gating on it is what made a kill summon a replacement. A creation count
// can only ever go up, so the initial fill can still run asynchronously over
// several frames and can never reopen -- not even if the player kills a
// defender while the group is still being assembled.
tkEnlisted:   .byte 0

tkActive:     .byte 0       // 1 = a token encounter is running
tkSlot:       .byte 0       // pool slot of the live P

// THE RING'S CLOCK, IN FRAMES, NOT IN PHASES. It free-runs 0..TK_ORBIT_PERIOD-1
// and each guard derives its own phase from it by adding its own offset and
// shifting -- which is what staggers the three of them onto different frames
// for nothing. v2 held a phase index and a separate countdown to the next
// phase; two bytes that had to agree, and which by construction turned all
// three guards on the same frame.
tkOrbit:      .byte 0
tkReinforce:  .byte 0       // frames until the next replacement attempt

// THE ONE-DROPPER RULE, AND IT IS ONE BYTE. A second live Dropper would mean a
// second token and a second encounter, so the spawner asks this before it
// commits a Dropper and src/enemy.asm clears it when one dies or leaves. It is
// a LIVENESS flag rather than a count because the answer the spawner needs is
// "is there one already", and a count that drifted would fail open.
tkDropperLive: .byte 0

// The token's position, cached once a frame. Guards move during
// objectUpdateAll and tokenTick runs after it, so every guard in a frame reads
// the SAME token position -- one that is a frame old, which is both stable and
// free. Chasing a position that moved mid-walk would make the ring wobble by
// the token's own step.
tkTokXLo:     .byte 0
tkTokXHi:     .byte 0
tkTokY:       .byte 0

// tokenGuardMove's working set: the post it is walking to, and the delta.
tkTgtXLo:     .byte 0
tkTgtXHi:     .byte 0
tkTgtY:       .byte 0
tkTmp:        .byte 0
tkSaveX:      .byte 0

// --- diagnostics, saturating -------------------------------------------------
tkStarted:    .byte 0       // encounters begun
tkEnded:      .byte 0       // encounters finished
tkReinforced: .byte 0       // replacement guards that reached the world
tkDenied:     .byte 0       // replacements the pool refused
tkEgressed:   .byte 0       // enemies dismissed to leave

// PER-OBJECT ROLE. See the header: this is the only thing that says an enemy
// has left its authored path, and objectZeroSlot clears it.
enyRole:      .fill MAX_OBJECTS, 0

tokenStateEnd:
.if (tokenStateEnd > $c4c0) {
    .error "the token encounter state has grown into the pickup state at $c4c0"
}

// ===========================================================================
// Code. MAIN THREAD ONLY. In the free run above main, which ends at $529f, and
// below the terrain map data at $5800.
//
// NOT in the 238-byte gap left between the pickup code and main at $5000, where
// this file was first placed: the encounter turned out to be 800 bytes, and a
// segment that only fits while it is small is a segment that will be moved
// again. $5400 leaves main 352 bytes of growth beneath it and the encounter 224
// above, and the guards at both ends are hard errors rather than comments.
// ===========================================================================
* = $5400 "token encounter"

// ---------------------------------------------------------------------------
// tokenInit — no encounter, no roles, no Dropper. Cold start only.
// ---------------------------------------------------------------------------
tokenInit:
    lda #0
    sta tkEnlisted
    sta tkActive
    sta tkDropperLive
    sta tkOrbit
    sta tkReinforce
    sta tkStarted
    sta tkEnded
    sta tkReinforced
    sta tkDenied
    sta tkEgressed
    ldx #MAX_OBJECTS - 1
!clear:
    sta enyRole,x
    dex
    bpl !clear-
    rts

// ---------------------------------------------------------------------------
// tokenDropperDied — THE ONE ENTRY POINT FOR THE WHOLE MECHANIC.
// Entry: A/X/Y free; the dying Dropper's position has ALREADY been captured
//        into pkSpawnXLo/Hi/pkSpawnY and its pool slot has ALREADY been freed.
//
// THE SLOT IS FREED FIRST, AND THAT IS THE ALLOCATION POLICY. A token that the
// pool refused would be a reward the player earned and did not get, so rather
// than a deferred-spawn queue the order of operations guarantees the capacity:
// the Dropper's own slot is released before the token asks for one, so there is
// always at least one free slot at this instant. The token cannot be refused by
// a pool that was full a moment ago, because the object that just died was in
// it. src/enemy.asm's enemyDeathTick is what enforces the order.
//
// It is still written to cope if pickupSpawn somehow refuses -- the encounter
// simply does not start, which is the safe direction.
// ---------------------------------------------------------------------------
tokenDropperDied:
    lda tkActive
    bne !done+                          // an encounter is already running: the
                                        // one-Dropper rule should have made
                                        // this impossible, and a second token
                                        // is the one outcome worth refusing

    lda #PICKUP_P
    jsr pickupSpawn                     // carry set = refused; X = slot if not
    bcs !done+

    stx tkSlot                          // the token this encounter is about
    lda logX,x
    sta tkTokXLo
    lda logXHi,x
    sta tkTokXHi
    lda logY,x
    sta tkTokY

    lda #1
    sta tkActive
    lda #0
    sta tkEnlisted                      // a new encounter enlists a new group
    sta tkOrbit                         // every encounter starts the ring at
                                        // the same place, so the transition is
                                        // reproducible when it is watched
    lda #1                              // THE FIRST DEFICIT IS FILLED AT ONCE,
    sta tkReinforce                     // not TK_REINFORCE_FRAMES later. The
                                        // interval paces REPLACEMENTS during a
                                        // fight; the transition itself has to
                                        // look decisive, and a screen that was
                                        // nearly empty when the Dropper died
                                        // would otherwise stand undefended for
                                        // half a second at the exact moment the
                                        // player is looking at it.

    lda tkStarted
    cmp #$ff
    beq !noCount+
    inc tkStarted
!noCount:

    // ---- the authored encounter stands down -------------------------------
    // Any wave instance still sending members is CANCELLED rather than left to
    // run. It would otherwise keep spawning ordinary enemies into an encounter
    // that is supposed to be exactly three defenders, and the director's own
    // drop semantics already allow a wave to be lost -- waveStartNext drops one
    // whenever both instances are busy. The trigger cursor and worldProgress
    // are NOT touched, so the authored stage keeps its place and resumes.
    ldx #WAVE_SLOTS - 1
!cancel:
    lda #0
    sta wvActive,x
    sta wvLeft,x
    dex
    bpl !cancel-

    jsr tokenAssignRoles
!done:
    rts

// ---------------------------------------------------------------------------
// tokenAssignRoles — every live ordinary enemy becomes a guard or leaves.
//
// ONE PASS, SLOT ORDER, DETERMINISTIC. The first TK_GUARDS enemies the walk
// meets take the posts and everything after is dismissed, which satisfies all
// three transition cases without any of them being a special case:
//
//     fewer than three   every survivor is posted; tokenTick's reinforcement
//                        makes up the deficit, and the ones already posted
//                        start moving on this frame rather than waiting
//     exactly three      all three are posted and nothing is dismissed
//     more than three    three are posted, the surplus is told to leave
//
// Slot order is an arbitrary but STABLE choice, which is what the brief asks
// for in v1: the same population always produces the same assignment, so the
// transition is reproducible when it is watched.
//
// A DYING ENEMY IS NOT ELIGIBLE. objHP zero means it is already running its
// death animation and its slot is about to go back; posting it would create a
// guard that vanishes a few frames later and an immediate reinforcement.
// ---------------------------------------------------------------------------
tokenAssignRoles:
    lda #ROLE_GUARD
    sta tkTmp                           // the next post to hand out
    ldx #0
!scan:
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !next+
    lda objHP,x
    beq !next+                          // already dying

    lda tkTmp
    cmp #ROLE_GUARD + TK_GUARDS
    bcs !surplus+

    sta enyRole,x                       // post it
    inc tkTmp
    inc tkEnlisted                      // ...and it counts toward the one
                                        // complement this encounter gets
    jsr tokenSilence
    jsr tokenHalt                       // ...and it stops being a thing with a
                                        // heading. See tokenHalt.
    jmp !next+

!surplus:
    jsr tokenDismiss

!next:
    inx
    cpx #MAX_OBJECTS
    bne !scan-
    rts

// ---------------------------------------------------------------------------
// tokenSilence — an enemy that has left its authored path stops shooting.
// Entry/exit: X = slot, preserved.
//
// WAVE-AUTHORED FIRING IS RESOLVED AGAINST WAVE MOVEMENT. src/waves.asm decides
// at spawn whether a member fires, from the authored mask for the appearance
// and the species' capability -- and it does so knowing the path that member
// will fly. A guard is no longer on that path: it hovers around a token near
// the player instead of crossing the aperture once, so the same permission
// would produce a completely different volume of fire from the same authored
// byte.
//
// So the permission is withdrawn when the role changes. This is a decision
// about the encounter, not about firing: src/ebullet.asm and the firing tick
// are untouched, no protector-specific pattern exists, and an enemy that
// returns to no role would simply have no permission rather than a wrong one.
// ---------------------------------------------------------------------------
tokenSilence:
    lda #ENEMY_FIRE_NONE
    sta enyFire,x
    rts

// ---------------------------------------------------------------------------
// tokenHalt — this enemy's authored velocity is no longer its own.
// Entry/exit: X = slot, preserved.
//
// A GUARD'S POSITION IS WRITTEN DIRECTLY by tokenGuardMove, which replaces
// wmTick entirely -- so its wmVX/wmVY are never updated again and sit frozen at
// whatever heading the wave happened to leave behind. That matters because they
// are not dead bytes: src/enemy.asm's despawn rules read them to tell an enemy
// ARRIVING through a border from one LEAVING through it. A guard walking a ring
// near the left edge while carrying a stale leftward wmVX would be retired
// mid-patrol, and with v2.1's top rule the same is true of a stale upward wmVY
// -- which the taller ring now makes reachable.
//
// So the velocity is zeroed at the moment the role is taken. A stationary
// velocity is the truth about a guard: it is not travelling anywhere, it is
// being placed.
// ---------------------------------------------------------------------------
tokenHalt:
    lda #0
    sta wmVX,x
    sta wmVY,x
    sta wmAccX,x
    sta wmAccY,x
    rts

// ---------------------------------------------------------------------------
// tokenDismiss / tokenDismissUp — send this enemy away.
// Entry/exit: X = slot, preserved.
//
// NOT A DELETION. The object keeps its slot, its health, its art and its
// collision; all that changes is that it is now flying a terminal WM_EXIT and
// will be retired by the ordinary despawn rule when it reaches an edge. The
// player sees it leave, and can still shoot it on the way out.
//
// TWO ENTRY POINTS, ONE BODY, AND THE ONLY DIFFERENCE IS A SIGNED BYTE.
// WM_EXIT has no direction of its own -- src/movement.asm keeps whatever
// velocity it inherits -- and wmVY is signed there, integrated by the same
// arithmetic shift as wmVX. So "leave upward" needs no new movement mode, no
// new role and no new interpreter state: it is a negative number.
//
//   tokenDismiss     DOWN, for the surplus stood down at the START of an
//                    encounter, where the player is usually below and clear
//   tokenDismissUp   UP, for the survivors at the END of one, where the player
//                    is standing in the middle of the ring having just taken
//                    the token. See the constants for why that is a safety
//                    rule rather than a preference.
// ---------------------------------------------------------------------------
tokenDismissUp:
    lda #256 - TK_EGRESS_UP_VY          // two's complement: upward
    jmp tokenDismissAt

tokenDismiss:
    lda #TK_EGRESS_VY
    // falls through

tokenDismissAt:
    sta wmVY,x                          // consume A at once: the two entries
                                        // need no scratch byte, and tkTmp is
                                        // NOT free here -- tokenAssignRoles is
                                        // holding the next post in it while it
                                        // calls this
    lda #ROLE_EGRESS
    sta enyRole,x
    jsr tokenSilence
    lda #WM_EXIT
    sta wmMode,x
    lda #0
    sta wmVX,x
    sta wmAccX,x
    sta wmAccY,x
    lda tkEgressed
    cmp #$ff
    beq !done+
    inc tkEgressed
!done:
    rts

// ---------------------------------------------------------------------------
// tokenTick — one frame of the encounter. MAIN THREAD, after objectUpdateAll.
//
// AFTER the objects have moved, so the token position cached here is the one
// the guards will walk toward next frame, and so a token collected or despawned
// this frame ends the encounter on the frame it happened rather than a frame
// late.
// ---------------------------------------------------------------------------
tokenTick:
    // THE LEVEL IS ENDING. Every system that can put something new into the
    // arena tests this for itself rather than being switched off from
    // elsewhere, so each one stops in its own terms and nothing has to keep a
    // list of what to suppress. See src/boss.asm.
    // no new token encounter may start once the level is ending
    lda lvlPhase
    beq !playing+
    rts
!playing:
    lda tkActive
    bne !running+
    rts
!running:

    // ---- is the token still there? ----------------------------------------
    // Collected or fallen off the bottom both free the slot, and both end the
    // encounter. The type is checked as well as the membership bit because the
    // slot may already have been handed to something else.
    ldx tkSlot
    lda logActive,x
    beq tokenEnd
    lda objType,x
    cmp #TYPE_PICKUP
    bne tokenEnd

    // ---- cache where it is, for next frame's guards -----------------------
    lda logX,x
    sta tkTokXLo
    lda logXHi,x
    sta tkTokXHi
    lda logY,x
    sta tkTokY

    // ---- turn the ring ----------------------------------------------------
    // ONE COUNTER, COUNTING FRAMES. It advances every frame and wraps at the
    // period; which PHASE that is, is each guard's own business, computed in
    // tokenGuardMove from this plus its own offset. Nothing here knows the
    // guards are staggered and nothing here has to.
    inc tkOrbit
    lda tkOrbit
    cmp #TK_ORBIT_PERIOD
    bcc !noWrap+
    lda #0
    sta tkOrbit
!noWrap:

    // ---- ASSEMBLE THE COMPLEMENT, ONCE ------------------------------------
    // THE DEFENCE IS ATTRITIONAL. This used to read "keep three posts filled",
    // and that is precisely what was wrong with it: a post emptied by the
    // player was indistinguishable from a post never filled, so shooting a
    // defender summoned another one and the formation could not be broken down.
    //
    // The gate is a creation count, not an occupancy scan. Until TK_GUARDS
    // defenders have been ENLISTED the encounter is still assembling its group
    // and may still reinforce; from the moment the third is created this branch
    // is taken for the rest of the encounter and nothing can reopen it.
    //
    //     3 defenders -> kill one -> 2 -> kill one -> 1 -> kill one -> 0
    //
    // ONE ATTEMPT PER EXPIRY, never a loop: a pool that is momentarily full
    // costs one attempt and the timer starts again, which is what bounds the
    // assembly. tokenFreePost still chooses WHICH post an initial defender
    // fills, so the group is assembled as deterministically as it ever was.
    lda tkEnlisted
    cmp #TK_GUARDS
    bcs !noReinforce+                   // the complement is closed
    dec tkReinforce
    bne !noReinforce+
    lda #TK_REINFORCE_FRAMES
    sta tkReinforce
    jsr tokenFreePost
    bcs !noReinforce+                   // every post filled right now
    jsr tokenReinforce
!noReinforce:
    rts

// ---------------------------------------------------------------------------
// tokenEnd — the token is gone. Stand the guards down and give the stage back.
//
// SURVIVORS LEAVE, THEY DO NOT VANISH. Every guard is dismissed into a rapid
// terminal exit, so the screen empties the way it filled: visibly, and with the
// objects still killable on the way out.
//
// UPWARD, WHICH IS THE ONE THING v2 GOT WRONG. Collecting the token means
// flying into the middle of the ring, so at this instant the three survivors
// are arranged AROUND the ship. v2 sent them down the screen from there, which
// drove all three straight through the player as the reward for collecting --
// the one thing manual play called unfair. They leave the other way, into the
// airspace the player has just left.
//
// The surplus dismissed at the START of an encounter still leaves downward and
// is deliberately unchanged: that happens the moment the Dropper dies, with the
// player still below and clear. See tokenDismiss.
// ---------------------------------------------------------------------------
tokenEnd:
    lda #0
    sta tkActive

    ldx #0
!scan:
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !next+
    lda enyRole,x
    cmp #ROLE_GUARD
    bcc !next+                          // normal or already leaving
    jsr tokenDismissUp
!next:
    inx
    cpx #MAX_OBJECTS
    bne !scan-

    lda tkEnded
    cmp #$ff
    beq !done+
    inc tkEnded
!done:
    rts

// ---------------------------------------------------------------------------
// tokenFreePost — the lowest post with no live guard on it.
// Exit: carry CLEAR and A = the role value for that post; carry SET if all
//       TK_GUARDS posts are filled. X and Y clobbered.
// ---------------------------------------------------------------------------
tokenFreePost:
    lda #0
    sta tkTmp                           // bit per filled post
    ldx #0
!scan:
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !next+
    lda enyRole,x
    sec
    sbc #ROLE_GUARD
    bcc !next+                          // normal or egressing
    cmp #TK_GUARDS
    bcs !next+
    tay
    lda tkTmp
    ora tokenPostBit,y
    sta tkTmp
!next:
    inx
    cpx #MAX_OBJECTS
    bne !scan-

    ldy #0
!post:
    lda tkTmp
    and tokenPostBit,y
    beq !found+
    iny
    cpy #TK_GUARDS
    bne !post-
    sec                                 // every post filled
    rts
!found:
    tya
    clc
    adc #ROLE_GUARD
    clc
    rts

tokenPostBit: .byte 1, 2, 4
.if (TK_GUARDS > 3) { .error "tokenPostBit is one bit a post" }

// ---------------------------------------------------------------------------
// tokenReinforce — one replacement guard, entering from above.
// Entry: A = the role value of the post to fill.
//
// AN ORDINARY ENEMY IN EVERY RESPECT except that it is born already posted: the
// same pool slot, the same species art, the same health, the same collision and
// the same despawn rules. It is never a Dropper -- a reinforcement that dropped
// a second token would turn one encounter into an unbounded chain.
// ---------------------------------------------------------------------------
tokenReinforce:
    sta tkTmp                           // the post, across objectAlloc
    jsr objectAlloc
    bcc !got+
    lda tkDenied                        // the pool was busy: lose the attempt
    cmp #$ff                            // and let the timer come round again
    beq !refused+
    inc tkDenied
!refused:
    rts

!got:
    // ---- where it comes in ------------------------------------------------
    // At the token's column and above the aperture, so it descends into view
    // and then converges on its post.
    lda tkTokXLo
    sta logX,x
    lda tkTokXHi
    sta logXHi,x
    lda #TK_SPAWN_Y
    sta logY,x

    // ---- an ordinary Ring -------------------------------------------------
    lda #SPECIES_RING
    sta enySpecies,x
    jsr enemyAnimPtr                    // A = this frame's frame, X preserved
    sta logPtr,x
    lda #TK_GUARD_COL
    sta logCol,x
    sta wmBaseCol,x                     // what a hit flash returns to

    lda #ENEMY_MAX_HP
    sta objHP,x
    lda #0
    sta objTimer,x
    lda #TYPE_ENEMY
    sta objType,x

    lda tkTmp
    sta enyRole,x                       // born posted
    jsr tokenSilence

    jsr objectActivate

    inc tkEnlisted                      // it is one of the complement now, and
                                        // the count is what closes the group
    lda tkReinforced
    cmp #$ff
    beq !done+
    inc tkReinforced
!done:
    rts

// ---------------------------------------------------------------------------
// tokenGuardMove — one frame of one guard's walk. Entry/exit: X = slot.
//
// REPLACES wmTick FOR THIS ENEMY, which is the whole of "detached from its
// authored path": src/enemy.asm calls this instead, so no movement program
// runs, no stage advances and nothing in src/movement.asm has to know roles
// exist. The wave that made this enemy had already let go of it -- an instance
// is freed when its last member is SENT, not when its members die -- so there
// is no ownership to unwind here, only a movement source to change.
//
// Walk toward the post, snap when inside one step. Both axes independently,
// which makes the approach a diagonal and the arrival exact.
// ---------------------------------------------------------------------------
tokenGuardMove:
    stx tkSaveX

    // ---- which phase of the ring is this guard's post? --------------------
    // TWO OFFSETS, AND THEY DO DIFFERENT JOBS.
    //
    //   the STATION, post * TK_ORBIT_SPAN, spaces the three guards a third of
    //   the ring apart and never changes. This is the deterministic
    //   distribution v2 had and v2.1 keeps: three defenders around the token,
    //   not three that drift into a bunch.
    //
    //   the STAGGER, post frames added to the ring's clock BEFORE the shift,
    //   moves the FRAME each guard turns over on. With a hold of four and
    //   three guards, post 0 turns on frames 0, 4, 8..., post 1 on 3, 7, 11...
    //   and post 2 on 2, 6, 10... -- so no two of them ever change direction
    //   on the same frame. That is the other half of un-sticking the triangle,
    //   and it costs one add because the clock is already in frames.
    lda enyRole,x
    sec
    sbc #ROLE_GUARD                     // p = 0..TK_GUARDS-1
    tay                                 // ...kept, both offsets need it

    clc
    adc tkOrbit                         // the stagger: + p frames
    cmp #TK_ORBIT_PERIOD
    bcc !noWrap+
    sbc #TK_ORBIT_PERIOD                // carry is set: a clean subtract
!noWrap:
    lsr
    lsr                                 // / TK_ORBIT_HOLD -> 0..STEPS-1
    sta tkTmp

    tya                                 // the station: + p * TK_ORBIT_SPAN
    asl
    asl
    asl                                 // * 8
    clc
    adc tkTmp
    cmp #TK_ORBIT_STEPS                 // p*8 <= 16 and phase <= 23, so the sum
    bcc !phase+                         // is at most 39: one subtract is enough
    sbc #TK_ORBIT_STEPS                 // carry is set: a clean subtract
!phase:
    tay

    // ---- the post, as a nine-bit X and an eight-bit Y ---------------------
    lda tkTokXLo
    clc
    adc tokenOrbXLo,y
    sta tkTgtXLo
    lda tkTokXHi
    adc tokenOrbXHi,y                   // the offset's sign extension
    sta tkTgtXHi

    lda tkTokY
    clc
    adc tokenOrbY,y
    sta tkTgtY

    // ---- keep the post inside the playfield -------------------------------
    // Signed compare against the two bounds. A post pushed outside would put
    // the guard at an unsigned X on the far side of the screen.
    lda tkTgtXHi
    bmi !clampLow+                      // negative: certainly below the floor
    bne !checkHigh+                      // >= 256: certainly above the floor
    lda tkTgtXLo
    cmp #TK_X_MIN
    bcs !checkHigh+
!clampLow:
    lda #<TK_X_MIN
    sta tkTgtXLo
    lda #>TK_X_MIN
    sta tkTgtXHi
    jmp !clamped+
!checkHigh:
    lda tkTgtXHi
    cmp #>TK_X_MAX
    bcc !clamped+
    bne !clampHigh+
    lda tkTgtXLo
    cmp #<TK_X_MAX + 1
    bcc !clamped+
!clampHigh:
    lda #<TK_X_MAX
    sta tkTgtXLo
    lda #>TK_X_MAX
    sta tkTgtXHi
!clamped:

    // ---- walk X -----------------------------------------------------------
    // d = target - current, nine bits signed.
    ldx tkSaveX
    lda tkTgtXLo
    sec
    sbc logX,x
    sta tkTmp
    lda tkTgtXHi
    sbc logXHi,x
    bmi !xLeft+

    // d >= 0: right, or already there
    ora tkTmp
    beq !xDone+                         // exactly on the post
    lda tkTgtXHi
    sbc logXHi,x                        // recompute the high byte (A was ORed)
    bne !stepRight+                     // 256 or more away
    lda tkTmp
    cmp #TK_STEP
    bcc !snapX+                         // inside one step: land on it
!stepRight:
    lda logX,x
    clc
    adc #TK_STEP
    sta logX,x
    bcc !xDone+
    inc logXHi,x
    jmp !xDone+

!xLeft:
    // d < 0: left. |d| < TK_STEP only when the high byte is $ff and the low
    // byte is within TK_STEP of wrapping.
    cmp #$ff
    bne !stepLeft+
    lda tkTmp
    cmp #256 - TK_STEP
    bcc !stepLeft+
!snapX:
    lda tkTgtXLo
    sta logX,x
    lda tkTgtXHi
    sta logXHi,x
    jmp !xDone+
!stepLeft:
    lda logX,x
    sec
    sbc #TK_STEP
    sta logX,x
    bcs !xDone+
    dec logXHi,x
!xDone:

    // ---- walk Y -----------------------------------------------------------
    lda tkTgtY
    sec
    sbc logY,x
    beq !yDone+
    bmi !yUp+
    cmp #TK_STEP
    bcc !snapY+
    lda logY,x
    clc
    adc #TK_STEP
    sta logY,x
    jmp !yDone+
!yUp:
    cmp #256 - TK_STEP
    bcs !snapY+
    lda logY,x
    sec
    sbc #TK_STEP
    sta logY,x
    jmp !yDone+
!snapY:
    lda tkTgtY
    sta logY,x
!yDone:
    rts

// ---------------------------------------------------------------------------
// The ring, as twelve offsets from the token. Signed; the X offset carries its
// own sign-extension byte so the nine-bit add above needs no branch.
// ---------------------------------------------------------------------------
tokenOrbXLo:
.for (var k = 0; k < TK_ORBIT_STEPS; k++) {
    .byte <round(TK_RADIUS_X * cos(2 * PI * k / TK_ORBIT_STEPS))
}
tokenOrbXHi:
.for (var k = 0; k < TK_ORBIT_STEPS; k++) {
    .byte (round(TK_RADIUS_X * cos(2 * PI * k / TK_ORBIT_STEPS)) < 0) ? $ff : $00
}
tokenOrbY:
.for (var k = 0; k < TK_ORBIT_STEPS; k++) {
    .byte <round(TK_RADIUS_Y * sin(2 * PI * k / TK_ORBIT_STEPS))
}
tokenOrbEnd:
.if (tokenOrbEnd - tokenOrbXLo != 3 * TK_ORBIT_STEPS) {
    .error "the orbit table is not three bytes a phase"
}
.if (mod(TK_ORBIT_STEPS, TK_GUARDS) != 0) {
    .error "the posts must divide the ring evenly or they would not stay spread"
}

.if (* > $5800) { .error "the token encounter code has run into the terrain map at $5800" }
