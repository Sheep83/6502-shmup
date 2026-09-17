// ===========================================================================
// boss.asm — the end of a level: final arena, boss, victory, scripted exit
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is written from this file. The boss
// is drawn by the ordinary logical renderer through four ordinary pool
// objects, the player leaves through its own existing HW0 presentation, and
// the scroller freezes itself.
//
//     LP_LEVEL     normal play, watching worldProgress
//        v         the authored stage has been traversed exactly once
//     LP_CLEARING  scroll frozen, no new encounters, the arena empties
//        v         nothing hostile left (or the deadline expired)
//     LP_BOSS      one static boss, 50 HP, no weapons
//        v         HP reaches zero
//     LP_VICTORY   100 frames of nothing, with the player's agency removed
//        v
//     LP_EXIT      the ship accelerates off the top under its own SFX
//        v         it clears the aperture
//     -> gsEnterLevelDone, the LEVEL COMPLETE lifecycle state
//
// ---------------------------------------------------------------------------
// ONE ENTITY, FOUR RENDER PIECES
// ---------------------------------------------------------------------------
// The boss is ONE logical thing: one position, one HP byte, one death. The
// four sprite cells are pool objects of TYPE_BOSS carrying nothing but a
// pointer, a colour and a position -- they have no health, no movement, no
// despawn rule and no tick. Nothing in the engine treats them as enemies:
// traceRay and playerBodyTick both filter on TYPE_ENEMY, objectUpdateAll's
// dispatch chain falls through TYPE_BOSS to the next slot, and the boss's own
// damage comes in through a single test in collisionTick.
//
// THAT IS WHAT MAKES A RAY THAT CROSSES A SEAM COUNT ONCE. The cells are not
// targets at all, so there is nothing for a ray to hit twice; the hit test is
// against ONE rectangle, and collisionTick already gives each ray exactly one
// damage call.
// ===========================================================================

// --- the phases -------------------------------------------------------------
.const LP_LEVEL    = 0
.const LP_CLEARING = 1
.const LP_BOSS     = 2
.const LP_VICTORY  = 3
.const LP_EXIT     = 4
.const LP_DONE     = 5              // handed over; nothing here runs again

// --- the boss ---------------------------------------------------------------
.const BOSS_CELLS   = 4
.const BOSS_HP_FULL = 50            // the brief's number, and the pacing knob:
                                    // the twin cannon lands two hits a volley
                                    // every WPN_FIRE_PERIOD frames, so this is
                                    // about four seconds of sustained fire

// Where it sits in the frozen arena. High enough to leave the player the whole
// lower playfield to move in, and inside the hitscan band so every shot that
// looks like it should reach it does.
.const BOSS_X       = 136           // nine-bit; the composed body is 48 wide,
                                    // so this centres it on the 24..343 window
.const BOSS_Y       = 74

// The composed body, and the hitbox. ONE rectangle for the whole boss rather
// than four cell boxes: the cells are a picture, and a picture should not be
// able to disagree with a hitbox. Exposed for tuning by eye.
.const BOSS_BOX_W   = 48            // two cells across
.const BOSS_BOX_H   = 42            // two cells down
.const BOSS_HIT_INSET = 4           // pixels in from each side: a shot that
                                    // clips the very edge of the armour should
                                    // miss, the same forgiveness the player's
                                    // own body box gets

// --- where the four cells live ----------------------------------------------
// $3580 is the four-block run the Ring vacated when the enemy sprite window
// became one contiguous region. It is the ONLY contiguous four-block run left
// in the bank outside that window, and the window belongs to a level package.
// Declared here, with the boss's other constants, because .const resolves in
// import order and src/boss_art.asm is parsed after this file.
.const BOSS_SPRITES     = $3580
.const BOSS_SPRITES_END = BOSS_SPRITES + BOSS_CELLS * 64
.const BOSS_PTR         = BOSS_SPRITES / 64         // $d6 .. $d9

.const BOSS_COL       = 4           // purple: the reactor colour
.const BOSS_COL_HIT   = 1           // white: the whole machine lights up
.const BOSS_FLASH_TIME = 3          // frames

// --- the arena clear --------------------------------------------------------
// A DEADLINE, NOT A HOPE. The clear ends when the arena is genuinely empty, or
// when this many frames have passed -- whichever comes first -- and the
// deadline path FORCES what is left out rather than waiting. An encounter that
// could stall here (a Dropper still flying its pattern, a protector mid-role,
// a bolt that will never leave) must not be able to hold the level open.
.const ARENA_CLEAR_DEADLINE = 200   // four seconds at 50 Hz

// --- victory and exit -------------------------------------------------------
.const VICTORY_PAUSE = 100          // PAL frames, ~2 s. Deliberately empty:
                                    // this is the space a real boss explosion
                                    // will be built into.

// THE EXIT IS ACCELERATED, NOT A TELEPORT. Velocity is carried in EIGHTHS of a
// pixel per frame so the launch starts visibly slow and is genuinely fast by
// the time it leaves: distance after n frames is n*n/16 pixels, so the ~190
// pixels from the ship's usual station to off the top take about 55 frames,
// a little over a second.
.const EXIT_ACCEL   = 1             // eighths of a pixel, per frame, per frame
.const EXIT_VMAX    = 64            // 8 pixels a frame: past this it is a blur
.const EXIT_GONE_Y  = MIN_SPRITE_Y - SPRITE_HEIGHT      // 34: wholly above the
                                                        // aperture

// --- the health bar ---------------------------------------------------------
// COLOUR RAM, ON THE FROZEN ARENA, and it is cheap precisely because the arena
// is frozen: nothing flips pages, nothing scrolls, and colour RAM is not
// double buffered, so a row written here stays written. There is no font in
// the playfield charset and the HUD's six sprite slots are all spoken for, so
// a row of recoloured terrain cells is the one bar this engine can draw
// without raster work or a new HUD component.
//
// Bit 3 is kept SET in both values: that is the per-cell multicolour bit the
// terrain needs, so only the cell's colour changes and the artwork does not
// switch rendering mode underneath the bar.
.const BOSS_BAR_ROW   = 1
.const BOSS_BAR_COL   = 8
.const BOSS_BAR_CELLS = 25          // BOSS_HP_FULL / 2, so one cell is 2 HP
.const BOSS_BAR_AT    = COLOUR_RAM + BOSS_BAR_ROW * 40 + BOSS_BAR_COL
.const BOSS_BAR_FULL  = 8 | 2       // multicolour cell, red
.const BOSS_BAR_EMPTY = TERRAIN_COLOUR_RAM

.if (BOSS_BAR_CELLS * 2 != BOSS_HP_FULL) {
    .error "the boss bar does not divide the boss's health evenly"
}

// ===========================================================================
// State
// ===========================================================================
* = $c760 "boss state"

lvlPhase:      .byte LP_LEVEL
bossHP:        .byte 0
bossFlash:     .byte 0              // frames of hit colour remaining
bossBarDrawn:  .byte 0              // cells currently lit, so the bar is
                                    // redrawn only when it changes
lvlTimer:      .byte 0              // arena-clear deadline / victory pause
// THE LEVEL HAS BEEN WON and the player no longer has agency. Set the instant
// the boss dies -- not when the launch starts -- because victory is confirmed
// at that moment and everything still available to the player from there is
// nonsense: firing into an empty arena, or dying to a bolt that outlived the
// boss. src/player.asm's playerTick and playerTakeHit and src/weapon.asm's
// weaponFire all READ it; only this file writes it. It lives here rather than
// with the player because the player's own state block is full to its ceiling
// and because the byte belongs to the level's ending.
plyExit:       .byte 0

exitVel:       .byte 0              // eighths of a pixel per frame
exitAcc:       .byte 0              // sub-pixel remainder, 0..7
bossTmp:       .byte 0
bossSlots:     .fill BOSS_CELLS, 0  // the pool slots the four cells occupy

// --- diagnostics ------------------------------------------------------------
bossHits:      .byte 0              // rays that landed, saturating
lvlForced:     .byte 0              // 1 = the arena clear hit its deadline

bossStateEnd:
.if (bossStateEnd > $c7a0) { .error "the boss state has outgrown its block" }

// ===========================================================================
// Code
// ===========================================================================
* = $9400 "boss code"

// ---------------------------------------------------------------------------
// bossInit — a new LEVEL starts here. Called from gameInit, so a new game and
// (later) a new level both get a clean slate.
//
// IT DOES NOT TOUCH RUN STATE. Score, lives and the P currency belong to the
// RUN and are reset by src/gamestate.asm's gsResetRun; everything here is
// level-scoped and dies with the level.
// ---------------------------------------------------------------------------
bossInit:
    lda #LP_LEVEL
    sta lvlPhase
    lda #0
    sta bossHP
    sta bossFlash
    sta bossBarDrawn
    sta lvlTimer
    sta exitVel
    sta exitAcc
    sta bossHits
    sta lvlForced
    sta plyExit                         // a new level never starts mid-victory
    ldx #BOSS_CELLS - 1
!slot:
    sta bossSlots,x
    dex
    bpl !slot-
    // ...and the arena gets its own colours back, in case the last game ended
    // with the health bar still painted across it.
    jmp bossClearBar

// ---------------------------------------------------------------------------
// bossTick — one frame of the level's ending. MAIN THREAD, once per frame,
// from gameFrame after the encounter director has had its turn.
//
// FIVE CYCLES DURING ORDINARY PLAY until the stage runs out: a load, a compare
// and a branch into the watch, which is itself a load and a branch.
// ---------------------------------------------------------------------------
bossTick:
    lda lvlPhase
    bne !notLevel+
    jmp bossWatchStage
!notLevel:
    cmp #LP_CLEARING
    bne !notClear+
    jmp bossClearTick
!notClear:
    cmp #LP_BOSS
    bne !notBoss+
    jmp bossFightTick
!notBoss:
    cmp #LP_VICTORY
    bne !notVictory+
    jmp bossVictoryTick
!notVictory:
    cmp #LP_EXIT
    bne !done+
    jmp bossExitTick
!done:
    rts

// ---------------------------------------------------------------------------
// bossWatchStage — has the authored stage been traversed exactly once?
//
// THE SCROLLER ANSWERS THIS, NOT A TIMER. src/scroll.asm freezes itself the
// moment worldProgress reaches STAGE_FINAL_VIEW_PROGRESS -- a number derived
// from the level's own authored height and the viewport, not a constant typed
// here -- and sets stageComplete. This routine only has to notice.
// ---------------------------------------------------------------------------
bossWatchStage:
    lda stageComplete
    bne !ending+
    rts
!ending:
    lda #LP_CLEARING
    sta lvlPhase
    jsr vicMirrorScreen                 // ARM the bank 2 screen mirror. The
                                        // scroll froze on the step that set
                                        // stageComplete, so the matrix is final
                                        // from this instruction onwards and
                                        // bossClearTick can walk it across a
                                        // slice at a time. See src/vicbank.asm.
    lda #ARENA_CLEAR_DEADLINE
    sta lvlTimer
    rts

// ---------------------------------------------------------------------------
// bossClearTick — empty the arena before the boss arrives.
//
// No new waves, no new special encounters and no hostile fire can start once
// lvlPhase has left LP_LEVEL: those systems test it themselves rather than
// being switched off from here, so each one stops in its own terms.
//
// What remains is whatever was already in flight. It is given
// ARENA_CLEAR_DEADLINE frames to LEAVE THE WAY IT NORMALLY WOULD -- enemies
// fly their authored egress, bolts run off the bottom -- because content
// leaving under its own rules looks like the level ending rather than like the
// game being switched off. When the deadline expires whatever is left is
// removed outright, so nothing can hold the level open.
// ---------------------------------------------------------------------------
bossClearTick:
    // BANK 2'S HUD IS BROUGHT UP TO DATE BEFORE THE SWITCH, not after it. The
    // clearing phase is at least long enough to walk the whole block across a
    // slice at a time, so the frame bank 2 is selected the mirror already shows
    // the heat and score the player was last looking at. See src/vicbank.asm.
    jsr vicMirrorTick

    jsr bossArenaBusy
    beq !clean+                         // nothing hostile is left

    lda lvlTimer
    beq !force+
    dec lvlTimer
    rts

!force:
    lda #1
    sta lvlForced                       // visible, rather than a silent stall
    jsr bossPurgeArena
!clean:
    jmp bossSpawn

// ---------------------------------------------------------------------------
// bossArenaBusy — Z set when no enemy and no hostile bolt is left alive.
// Clobbers A and X.
// ---------------------------------------------------------------------------
bossArenaBusy:
    ldx #0
!slot:
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    beq !busy+
    cmp #TYPE_EBULLET
    beq !busy+
!next:
    inx
    cpx #MAX_OBJECTS
    bne !slot-
    lda #0                              // Z set: the arena is clean
    rts
!busy:
    lda #1                              // Z clear
    rts

// ---------------------------------------------------------------------------
// bossPurgeArena — remove every enemy and hostile bolt still present, through
// the routines that own each one's lifecycle rather than by clearing bytes.
// ---------------------------------------------------------------------------
bossPurgeArena:
    ldx #0
!slot:
    stx bossTmp
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !notEnemy+
    jsr enemyDespawn                    // the only place an enemy's slot is
    jmp !next+                          // released; X preserved
!notEnemy:
    cmp #TYPE_EBULLET
    bne !next+
    jsr ebulletRetire                   // ...and the only place a bolt is
!next:
    ldx bossTmp
    inx
    cpx #MAX_OBJECTS
    bne !slot-
    rts

// ---------------------------------------------------------------------------
// bossSpawn — four render cells, one boss.
//
// The cells are allocated from the ordinary pool and activated the ordinary
// way, so the sorter, the builder and the multiplexer draw them without
// knowing what they are. If the pool cannot give four slots the boss simply
// arrives with fewer pieces rather than not at all: the arena has just been
// emptied, so it never should, and a level that could not start its boss would
// be worse than one that looks wrong for a moment.
// ---------------------------------------------------------------------------
bossSpawn:
    // =======================================================================
    // THE BANK SWITCH. THIS IS THE PHASE BOUNDARY, AND IT IS THE SAFEST ONE.
    // =======================================================================
    // Everything the VIC will fetch from bank 2 is already correct by the time
    // this runs:
    //
    //   the sprite art, the blank charset and the terrain charset were copied
    //   at boot and never change;
    //   the HUD has been mirrored slice by slice through the whole clearing
    //   phase;
    //   the screen matrix is frozen -- the final coarse step has happened, the
    //   fine phase is pinned at zero and scrollTick returns at its first
    //   instruction -- so the one kilobyte copied here is the last complete
    //   authored screenful, and nothing will ever write it again.
    //
    // It also happens BEFORE the cells are allocated, so the first frame that
    // has a boss in it is already a bank 2 frame: there is no frame in which
    // the arena is half switched.
    //
    // NO RASTER CLEVERNESS. The bank changes from the main thread between
    // frames, the picture on both sides of it is the same picture, and the
    // executor adopts the new $d018 and pointer destination through the frame
    // record it already adopts every frame.
    jsr vicMirrorFinish                 // normally nothing: the clearing phase
                                        // has already walked the matrix across
    jsr vicSelectBank2

    lda #BOSS_HP_FULL
    sta bossHP
    lda #0
    sta bossFlash
    lda #$ff
    sta bossBarDrawn                    // force the first bar draw

    ldx #0
!cell:
    stx bossTmp
    jsr objectAlloc                     // X = the slot, or carry set
    bcs !noSlot+

    lda bossTmp
    lsr                                 // cell >> 1 = the row, 0 or 1
    beq !topRow+
    lda #BOSS_Y + 21
    jmp !haveY+
!topRow:
    lda #BOSS_Y
!haveY:
    sta logY,x

    lda bossTmp
    and #1                              // cell & 1 = the column
    beq !leftCol+
    lda #<(BOSS_X + 24)
    sta logX,x
    lda #>(BOSS_X + 24)
    jmp !haveX+
!leftCol:
    lda #<BOSS_X
    sta logX,x
    lda #>BOSS_X
!haveX:
    sta logXHi,x

    lda bossTmp
    clc
    adc #BOSS_PTR                       // the four cells are adjacent blocks
    sta logPtr,x
    lda #BOSS_COL
    sta logCol,x

    lda #TYPE_BOSS                      // NOT an enemy: nothing that hunts
    sta objType,x                       // TYPE_ENEMY will ever see these
    lda #0
    sta objHP,x                         // no health of their own -- the boss's
    sta objTimer,x                      // HP is one byte, and it is not here
    sta objVX,x
    sta objVY,x

    jsr objectActivate

    ldy bossTmp                         // remember the slot, to recolour and
    txa                                 // free it later
    sta bossSlots,y

!noSlot:
    ldx bossTmp
    inx
    cpx #BOSS_CELLS
    bne !cell-

    lda #LP_BOSS
    sta lvlPhase
    jmp bossDrawBar

// ---------------------------------------------------------------------------
// bossFightTick — the boss is alive. It does not move, does not fire and does
// not animate; all this does is run the hit flash down and notice death.
// ---------------------------------------------------------------------------
bossFightTick:
    lda bossFlash
    beq !noFlash+
    dec bossFlash
    bne !noFlash+
    lda #BOSS_COL                       // the flash expired: back to its own
    jsr bossSetColour                   // colour
!noFlash:

    lda bossHP
    beq !dead+
    rts

// ---- the boss dies --------------------------------------------------------
// IMMEDIATELY NON-DAMAGEABLE, and the pieces go at once. There is no boss
// death animation in this slice on purpose: the victory pause below is the
// space one will be built into, and filling it now with a placeholder would
// make that harder rather than easier.
!dead:
    jsr bossFreeCells
    jsr bossClearBar
    lda #LP_VICTORY
    sta lvlPhase
    lda #VICTORY_PAUSE
    sta lvlTimer

    // THE PLAYER'S AGENCY ENDS HERE, not when the exit starts. Victory is
    // confirmed, so there is nothing useful left to do and plenty of nonsense
    // available: firing into an empty arena, or dying to a bolt that outlived
    // the boss. plyExit disables the stick, the trigger and all damage.
    lda #1
    sta plyExit
    jmp bossPurgeArena                  // no stale hazard survives the boss

// ---------------------------------------------------------------------------
// bossVictoryTick — VICTORY_PAUSE frames of deliberate nothing, then launch.
// ---------------------------------------------------------------------------
bossVictoryTick:
    dec lvlTimer
    bne !hold+

    lda #LP_EXIT
    sta lvlPhase
    lda #0
    sta exitVel                         // the launch starts from a standstill
    sta exitAcc
    lda #SFX_LAUNCH
    jsr sfxRequest                      // src/sfx.asm, voice 3
!hold:
    rts

// ---------------------------------------------------------------------------
// bossExitTick — the ship accelerates off the top of the screen.
//
// Velocity is in eighths of a pixel and the remainder is carried between
// frames, so the motion is smooth from the first frame rather than stepping
// whole pixels once it is fast enough to show them.
// ---------------------------------------------------------------------------
bossExitTick:
    lda exitVel                         // accelerate, to a ceiling
    clc
    adc #EXIT_ACCEL
    cmp #EXIT_VMAX
    bcc !vel+
    lda #EXIT_VMAX
!vel:
    sta exitVel

    clc                                 // the eighths, plus what was left over
    adc exitAcc
    sta bossTmp
    and #7
    sta exitAcc                         // the new remainder
    lda bossTmp
    lsr
    lsr
    lsr                                 // whole pixels to travel this frame
    sta bossTmp

    lda plyY
    sec
    sbc bossTmp
    bcc !gone+                          // borrowed past zero: certainly clear
    cmp #EXIT_GONE_Y
    bcc !gone+
    sta plyY
    rts

// ---- clear of the aperture ------------------------------------------------
!gone:
    lda #0
    sta plyVisible                      // HW0 off, explicitly: the ship has
                                        // LEFT, and letting it drift on into
                                        // the open upper border as a stray
                                        // sprite is not the same thing
    jsr sfxSilence                      // the launch stops when the ship does
    lda #LP_DONE
    sta lvlPhase
    jmp gsEnterLevelDone                // src/gamestate.asm; its rts is ours

// ===========================================================================
// DAMAGE
// ===========================================================================
// ---------------------------------------------------------------------------
// bossRayHit — one player ray, tested against the boss's single box.
//
// Called from collisionTick ONLY when traceRay found nothing else in the way,
// so an ordinary enemy or a turret between the player and the boss still
// absorbs the shot exactly as it would absorb any other.
//
// Entry: csRayLo/csRayHi = the ray's nine-bit X.
// ---------------------------------------------------------------------------
bossRayHit:
    lda lvlPhase                        // only during the fight
    cmp #LP_BOSS
    bne !miss+
    lda bossHP
    beq !miss+                          // a dead boss cannot be hit again

    // ---- the ray's X against the body, nine bits ------------------------
    lda csRayLo
    sec
    sbc #<(BOSS_X + BOSS_HIT_INSET)
    sta bossTmp
    lda csRayHi
    sbc #>(BOSS_X + BOSS_HIT_INSET)
    bne !miss+                          // left of the body, or far right of it
    lda bossTmp
    cmp #BOSS_BOX_W - 2 * BOSS_HIT_INSET
    bcs !miss+

    // ---- the body is above the player and inside the hitscan band --------
    lda #BOSS_Y + BOSS_BOX_H
    cmp plyY
    bcs !miss+                          // the ship is inside or above the boss

    // ---- the hit -----------------------------------------------------------
    lda bossHits
    cmp #$ff
    beq !counted+
    inc bossHits
!counted:
    lda bossHP
    sec
    sbc #SHOT_DAMAGE                    // the same damage every other target
    bcs !alive+                         // takes from one ray
    lda #0
!alive:
    sta bossHP

    lda #BOSS_FLASH_TIME
    sta bossFlash
    lda #BOSS_COL_HIT
    jsr bossSetColour
    jmp bossDrawBar
!miss:
    rts

// ---------------------------------------------------------------------------
// bossSetColour — A = colour, written to all four cells. The whole machine
// lights up as one, because it is one.
// ---------------------------------------------------------------------------
bossSetColour:
    sta bossTmp
    ldx #BOSS_CELLS - 1
!cell:
    ldy bossSlots,x
    lda logActive,y
    beq !skip+
    lda bossTmp
    sta logCol,y
!skip:
    dex
    bpl !cell-
    rts

// ---------------------------------------------------------------------------
// bossFreeCells — the four render pieces leave the pool the ordinary way.
// ---------------------------------------------------------------------------
bossFreeCells:
    ldx #BOSS_CELLS - 1
!cell:
    stx bossTmp
    ldy bossSlots,x
    lda logActive,y
    beq !skip+
    tya
    tax
    jsr objectFree
!skip:
    ldx bossTmp
    dex
    bpl !cell-
    rts

// ===========================================================================
// THE HEALTH BAR
// ===========================================================================
// ---------------------------------------------------------------------------
// bossDrawBar — one cell per two HP, redrawn only when the count changes.
// ---------------------------------------------------------------------------
bossDrawBar:
    lda bossHP
    lsr                                 // cells lit = HP / 2
    cmp bossBarDrawn
    beq !same+
    sta bossBarDrawn

    ldx #0
!cell:
    cpx bossBarDrawn
    bcc !lit+
    lda #BOSS_BAR_EMPTY
    jmp !put+
!lit:
    lda #BOSS_BAR_FULL
!put:
    sta BOSS_BAR_AT,x
    inx
    cpx #BOSS_BAR_CELLS
    bne !cell-
!same:
    rts

// ---------------------------------------------------------------------------
// bossClearBar — the terrain gets its own colour back. Called on boss death
// and again when the level ends, so nothing is left painted on the arena.
// ---------------------------------------------------------------------------
bossClearBar:
    lda #0
    sta bossBarDrawn
    ldx #0
    lda #BOSS_BAR_EMPTY
!cell:
    sta BOSS_BAR_AT,x
    inx
    cpx #BOSS_BAR_CELLS
    bne !cell-
    rts

.if (* > $9800) { .error "the boss code has outgrown its $9400 segment" }
