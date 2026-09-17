// ===========================================================================
// gamestate.asm — the outer lifecycle, restored from the old shooter
// ===========================================================================
// ATTRACT -> GAME -> GAME OVER -> (INITIALS) -> ATTRACT
//
// THIS IS A MIGRATION, NOT A DESIGN. Every state, constant, timer and input
// rule below comes from the old c64Shooter main.asm, which already solved this
// and which the user was happy with. Where the current engine made the old
// implementation impossible the BEHAVIOUR was kept and the implementation
// changed; nothing was re-invented merely because it could be done differently.
//
// The old shape, preserved exactly: four states dispatched by a cmp/beq router
// in which each handler owns its own per-frame loop and returns when the state
// changes. No scene framework, no callback table, no event bus -- the old code
// did not need one and neither does this.
//
// ---------------------------------------------------------------------------
// DISPLAY OWNERSHIP, AND THE SEAM FOR A LATER EXTRAVAGANT TITLE
// ---------------------------------------------------------------------------
// The current engine's raster executor owns the IRQ and consumes a published
// sprite schedule every frame. A non-game state must not be drawn by it, so
// gsNonGame is one byte the IRQ tests before anything else: non-zero routes to
// gsAttractIrq, a stub that programs a plain text display, disables every
// sprite, advances the frame counter and returns. It never looks at a schedule,
// a batch, a phase chain or a page.
//
// That is the whole seam. A later task wanting eight sprites, its own raster
// program and a Parallax-grade title replaces gsAttractIrq and the draw
// routines below WITHOUT touching the router, the states, the timers, the input
// rules or the high-score system.
//
// Registers the stub owns while a non-game state is up, and how gameplay takes
// each one back:
//
//   $d011  a plain 25-row text mode. GAMEPLAY REWRITES IT every frame from
//          frameD011 in exFrame, so it restores itself.
//   $d018  screen $0400 plus the CHARACTER ROM at $1000, which is where the VIC
//          sees it in this bank -- so attract text uses the stock font and this
//          engine needs no font of its own. The aperture splits rewrite $d018
//          twice a frame.
//   $d015  held at zero, so no gameplay or HUD sprite can leak into attract.
//          The batch executor rewrites it from the schedule.
//   $d020/$d021  black, as the old menu was. The aperture splits own $d021.
//   $d016  MULTICOLOUR OFF. This one does NOT restore itself: src/terrain.asm
//          sets the MCM bit once at boot and nothing rewrites it per frame, so
//          gsEnterGame puts it back explicitly.
//
// COLOUR RAM IS NEVER TOUCHED, and that is what makes the return to gameplay
// free. It is uniformly TERRAIN_COLOUR_RAM (9 = multicolour-cell | white); with
// MCM off the cell simply reads as white, so every text routine below writes
// SCREEN RAM ONLY. The old game coloured its text per line and per initials
// slot; that is the one piece of old presentation this could not keep, and the
// initials highlight is reverse video instead. See the report.
// ===========================================================================

// --- the states, in the old order and with the old values -------------------
.const GS_ATTRACT  = 0
.const GS_PLAYING  = 1
.const GS_GAMEOVER = 2
.const GS_INITIALS = 3
// LEVEL COMPLETE. A genuine lifecycle state rather than a detour inside the
// game loop: gameplay has stopped, the executor is off the display and the RUN
// is still alive -- score, lives and the P currency are all intact and waiting
// for the upgrade screen that will replace this screen's FIRE destination.
.const GS_LEVELDONE = 4

// --- the old timers, unchanged ----------------------------------------------
.const GS_ATTRACT_CYCLE = 250       // ~5 PAL seconds per attract page
.const GS_OVER_HOLD     = 180       // ~3.6 s on GAME OVER before the table

.const GS_PAGE_TITLE  = 0
.const GS_PAGE_SCORES = 1

// --- the old high-score table shape -----------------------------------------
// Eight entries, three initials, and a score the old table carried as 24 bits
// and rendered as six decimal digits. THE DIGITS ARE NOW THE STORAGE: the
// current HUD keeps the live score as six bytes, one digit each, most
// significant first (hudScore), so storing entries the same way makes
// qualification a digit compare and removes the old binary-to-decimal render
// entirely. Same table size, same display, same ordering rule.
.const HS_COUNT   = 8
.const HS_DIGITS  = 6
.const HS_NAMELEN = 3
.const HS_ROW_W   = HS_NAMELEN + 2 + HS_DIGITS      // "III  DDDDDD", 11 wide

// --- screen geometry, lifted from the old constants -------------------------
.const SCREEN         = $0400
.const GS_TITLE_AT    = SCREEN + 6 * 40 + 10        // "MY FIRST C64 SHOOTER"
.const GS_PROMPT_AT   = SCREEN + 20 * 40 + 13       // "FIRE TO START"
.const GS_HEAD_AT     = SCREEN + 4 * 40 + 14        // "HIGH SCORES"
.const GS_ROW0_AT     = SCREEN + 7 * 40 + 15        // rows 7,9,11..21, column 15
.const GS_OVER_AT     = SCREEN + 12 * 40 + 15       // "GAME OVER"
.const GS_DONE_AT     = SCREEN + 8 * 40 + 13        // "LEVEL COMPLETE"
.const GS_TOKENS_AT   = SCREEN + 12 * 40 + 14      // "P TOKENS: nn"
.const GS_DFIRE_AT    = SCREEN + 18 * 40 + 13      // "PRESS FIRE"
.const GS_IPROMPT_AT  = SCREEN + 10 * 40 + 10      // "ENTER YOUR INITIALS"
.const GS_ISLOTS_AT   = SCREEN + 14 * 40 + 18       // three letters, cols 18/20/22

// --- the non-game display ---------------------------------------------------
.const GS_D011  = $1b               // DEN=1, RSEL=1 (25 rows), YSCROLL=3
.const GS_D018  = $14               // VM = $0400, CB = %010 = the character ROM
.const GS_SPACE = 32                // screen code
.const GS_REVERSE = $80             // reverse video: the initials highlight
.const GS_DIGIT0 = 48               // screen code for '0'

// Joystick port 2, active low, as the old code read it.
.const GS_FIRE  = %00010000

// --- zero page --------------------------------------------------------------
// Indirect indexed addressing REQUIRES a zero-page pointer, and the text blits
// below need two at once. src/main.asm documents $fd/$fe as scrPtr and
// src/terrain.asm takes $f7/$f8 as trSrc; these are the next free pairs, and
// the asserts keep that statement true rather than merely believed.
.const gsSrc = $fb                  // 16-bit, $fb/$fc
.const gsDst = $f9                  // 16-bit, $f9/$fa
.if (gsSrc == scrPtr || gsDst == scrPtr) { .error "the game-state pointers collide with scrPtr" }
.if (gsSrc == trSrc  || gsDst == trSrc)  { .error "the game-state pointers collide with trSrc" }
.if (gsSrc == gsDst) { .error "the two game-state pointers are the same pair" }

// ===========================================================================
// State
// ===========================================================================
* = $c700 "game state"

gsState:        .byte GS_ATTRACT
gsNonGame:      .byte 1             // THE IRQ SEAM. Boot begins in attract, so
                                    // the very first interrupt must already
                                    // take the stub path.
gsAttractPage:  .byte 0
gsAttractTimer: .byte 0
gsOverTimer:    .byte 0

// --- initials entry, straight from the old implementation -------------------
gsInitChars:    .byte 0, 0, 0       // 1..26, screen codes for A..Z
gsInitSlot:     .byte 0
gsInitPrev:     .byte 0             // last frame's stick, for edge detection
gsInitEdge:     .byte 0

gsRank:         .byte 0             // insertion index from gsScoreQualifies
gsSeed:         .byte 0
gsTmp:          .byte 0
gsTmp2:         .byte 0
gsRow:          .byte 0             // gsDrawScores' entry cursor
// --- diagnostics ------------------------------------------------------------
gsGames:        .byte 0             // games started this session, saturating
gsQualified:    .byte 0             // runs that made the table, saturating

// --- the table: session-persistent, and the ONLY thing that is --------------
hsDigits:       .fill HS_COUNT * HS_DIGITS, 0
hsName:         .fill HS_COUNT * HS_NAMELEN, 0

gameStateEnd:
.if (gameStateEnd > $c960) { .error "the game state has grown into the HUD state at $c960" }

// ===========================================================================
// Code
// ===========================================================================
* = $8b00 "game state code"

// ---------------------------------------------------------------------------
// gsBoot — called once from entry, after the renderer owns the IRQ.
// Seeds the table and enters attract, exactly as the old init did.
// ---------------------------------------------------------------------------
gsBoot:
    jsr gsSeedTable
    lda #GS_ATTRACT
    sta gsState
    jsr gsEnterAttract
    // falls into the router, which never returns

// ---------------------------------------------------------------------------
// gsRouter — the old mainLoop, unchanged in shape.
// ---------------------------------------------------------------------------
gsRouter:
    lda gsState
    cmp #GS_PLAYING
    bne !notPlaying+
    jsr gamePlayLoop                    // src/main.asm: the real engine
    jmp gsRouter
!notPlaying:
    cmp #GS_GAMEOVER
    bne !notOver+
    jsr gsGameOverLoop
    jmp gsRouter
!notOver:
    cmp #GS_LEVELDONE
    bne !notDone+
    jsr gsLevelDoneLoop
    jmp gsRouter
!notDone:
    cmp #GS_INITIALS
    bne !attract+
    jsr gsInitialsLoop
    jmp gsRouter
!attract:
    jsr gsAttractLoop
    jmp gsRouter

// ---------------------------------------------------------------------------
// gsWaitFrame — one displayed frame, whichever IRQ path is running.
//
// The attract stub advances frameCounter exactly as exFrame does, so non-game
// states pace themselves on the same byte the gameplay loop does and there is
// only one notion of "a frame" in the program.
// ---------------------------------------------------------------------------
gsWaitFrame:
    lda frameCounter
    cmp lastFrameSeen
    beq gsWaitFrame
    sta lastFrameSeen
    rts

// ---------------------------------------------------------------------------
// gsWaitFireRelease — the old waitFireRelease, and the old reason for it.
//
// Called at THREE points, all lifted from the old flow: after fire starts a
// game, on entering initials, and after the initials commit. Each stops one
// press being read again by the state it just entered -- the mechanism the old
// game already used against exactly the cascade this lifecycle invites.
// ---------------------------------------------------------------------------
gsWaitFireRelease:
    jsr gsWaitFrame
    jsr readInput                       // the stub IRQ does not run gameFrame,
                                        // so nothing else samples the stick
    lda joyState
    and #GS_FIRE
    beq gsWaitFireRelease               // bit clear = still held
    rts

// ===========================================================================
// ATTRACT
// ===========================================================================
gsEnterAttract:
    jsr gsBeginNonGame
    lda #GS_PAGE_TITLE                  // always come back to the title first
    sta gsAttractPage
    lda #GS_ATTRACT_CYCLE
    sta gsAttractTimer
    jmp gsDrawTitle

// ---------------------------------------------------------------------------
// gsAttractLoop — the old attractMenu: flip between the title and the table
// every GS_ATTRACT_CYCLE frames; fire on either page starts a game.
// ---------------------------------------------------------------------------
gsAttractLoop:
    jsr gsWaitFrame
    jsr readInput

    lda gsAttractPage                   // re-stamp the current page every frame,
    bne !scoresNow+                     // exactly as the old attractMenu did
    jsr gsDrawTitle
    jmp !stamped+
!scoresNow:
    jsr gsDrawScores
!stamped:

    dec gsAttractTimer
    bne !checkFire+
    lda #GS_ATTRACT_CYCLE               // time to flip pages
    sta gsAttractTimer
    lda gsAttractPage
    eor #1
    sta gsAttractPage
    jsr gsClearScreen                   // wipe the outgoing page's text
    lda gsAttractPage
    bne !scores+
    jsr gsDrawTitle
    jmp !checkFire+
!scores:
    jsr gsDrawScores

!checkFire:
    lda joyState
    and #GS_FIRE
    bne !noFire+
    jsr gsWaitFireRelease               // don't let this press also reach the
    jsr gsStartGame                     // game's first frame
    rts                                 // back to the router, now PLAYING
!noFire:
    jmp gsAttractLoop

// ===========================================================================
// GAME OVER
// ===========================================================================
// ---------------------------------------------------------------------------
// gsEnterGameOver — called by the terminal-death transition in src/player.asm,
// once the current engine's own death presentation has finished.
// ---------------------------------------------------------------------------
gsEnterGameOver:
    lda #GS_GAMEOVER
    sta gsState
    lda #GS_OVER_HOLD
    sta gsOverTimer
    jsr gsBeginNonGame
    jmp gsDrawGameOver

// ---------------------------------------------------------------------------
// gsGameOverLoop — the old gameOverScreen. Hold, then qualify: a score that
// beats the table goes to initials, otherwise straight back to attract.
//
// NO FIRE TEST, deliberately, exactly as the old one had none: the hold is a
// timer the player cannot skip, which is also what stops the press that killed
// them cascading into the next state.
// ---------------------------------------------------------------------------
gsGameOverLoop:
    jsr gsWaitFrame
    jsr gsDrawGameOver                  // RE-STAMPED EVERY FRAME, as the old
                                        // gameOverScreen did. The old reason
                                        // was that the starfield drifted behind
                                        // the words; the reason it still earns
                                        // its place is that a state entered
                                        // from inside a game frame cannot be
                                        // sure what repainted the screen after
                                        // it, and a text page that redraws
                                        // itself is immune to all of it.
    dec gsOverTimer
    bne !hold+

    jsr gsScoreQualifies                // carry set = this run makes the table
    bcc !toAttract+
    lda gsQualified
    cmp #$ff
    beq !enter+
    inc gsQualified
!enter:
    lda #GS_INITIALS
    sta gsState
    jsr gsEnterInitials
    rts
!toAttract:
    lda #GS_ATTRACT
    sta gsState
    jsr gsEnterAttract
    rts
!hold:
    jmp gsGameOverLoop

// ---------------------------------------------------------------------------
// gsScoreQualifies — the old scoreQualifies, adapted to digit storage.
//
// Compares the finished run's hudScore against the descending table, most
// significant digit first; carry set with gsRank = the insertion index.
// AN EQUAL SCORE DOES NOT DISPLACE AN EXISTING ENTRY -- the old rule, kept.
// ---------------------------------------------------------------------------
gsScoreQualifies:
    lda #0
    sta gsRank
!entry:
    lda gsRank
    jsr gsMul6
    sta gsTmp                           // gsTmp = this entry's digit offset
    ldy #0
!digit:
    ldx gsTmp
    lda hudScore,y
    cmp hsDigits,x
    bcc !next+                          // ours is smaller: below this entry
    bne !here+                          // ours is larger: insert here
    inc gsTmp                           // equal digit: look at the next one
    iny
    cpy #HS_DIGITS
    bne !digit-
    jmp !next+                          // all six equal: does not displace
!here:
    sec
    rts
!next:
    inc gsRank
    lda gsRank
    cmp #HS_COUNT
    bne !entry-
    clc                                 // beat nothing, not even the lowest
    rts

// A = entry index -> A = index * 6. Six is 4 + 2, so this is two shifts and an
// add rather than a multiply.
gsMul6:
    asl                                 // *2
    sta gsTmp2
    asl                                 // *4
    clc
    adc gsTmp2                          // *6
    rts

// A = entry index -> A = index * 3.
gsMul3:
    sta gsTmp2
    asl                                 // *2
    clc
    adc gsTmp2                          // *3
    rts

// ===========================================================================
// LEVEL COMPLETE
// ===========================================================================
// ---------------------------------------------------------------------------
// gsEnterLevelDone — called by src/boss.asm when the ship has left the top of
// the screen. THE RUN SURVIVES: this routine resets nothing at all. Score,
// lives and the P currency are exactly as the level left them, which is the
// whole point of the state -- the upgrade screen that replaces this one spends
// that currency.
// ---------------------------------------------------------------------------
gsEnterLevelDone:
    lda #GS_LEVELDONE
    sta gsState
    jsr gsBeginNonGame
    jmp gsDrawLevelDone

// ---------------------------------------------------------------------------
// gsLevelDoneLoop — hold the screen until FIRE, then go back to attract.
//
// THE DESTINATION IS TEMPORARY AND SAYS SO. Starting level 2 would mean level
// loading and a level-scoped reset that do not exist yet, so pressing FIRE
// returns to the attract loop -- an existing, harmless endpoint. The NEXT task
// replaces this with the upgrade screen and then the next level.
// ---------------------------------------------------------------------------
gsLevelDoneLoop:
    jsr gsWaitFrame
    jsr readInput
    jsr gsDrawLevelDone                 // re-stamped every frame, as every
                                        // other non-game page is
    lda joyState
    and #GS_FIRE
    bne !wait+
    jsr gsWaitFireRelease               // the old gate: one press cannot also
                                        // start the game it returns to
    lda #GS_ATTRACT
    sta gsState
    jsr gsEnterAttract
    rts
!wait:
    jmp gsLevelDoneLoop

// ---------------------------------------------------------------------------
// gsDrawLevelDone — the functional placeholder: what happened, what you are
// carrying, and what to press.
// ---------------------------------------------------------------------------
gsDrawLevelDone:
    gsText(gsDoneLine, GS_DONE_AT, 14)
    gsText(gsTokensLine, GS_TOKENS_AT, 10)
    gsText(gsPressLine, GS_DFIRE_AT, 10)

    // the P count, as two digits, straight from the run's own counter
    lda pkTokensP
    ldx #0
!tens:
    cmp #10
    bcc !units+
    sec
    sbc #10
    inx
    jmp !tens-
!units:
    pha
    txa
    clc
    adc #GS_DIGIT0
    sta GS_TOKENS_AT + 10
    pla
    clc
    adc #GS_DIGIT0
    sta GS_TOKENS_AT + 11
    rts

// ===========================================================================
// INITIALS
// ===========================================================================
gsEnterInitials:
    jsr gsBeginNonGame
    lda #1                              // every slot starts on "A"
    sta gsInitChars + 0
    sta gsInitChars + 1
    sta gsInitChars + 2
    lda #0
    sta gsInitSlot                      // leftmost slot selected
    jsr readInput
    lda joyState
    sta gsInitPrev                      // seed edge detection with the stick
                                        // exactly as it is right now
    jsr gsWaitFireRelease               // ignore fire still held from GAME OVER
    jmp gsDrawInitials

// ---------------------------------------------------------------------------
// gsInitialsLoop — the old enterInitialsScreen, edge detection included.
//
// Up/down change the highlighted letter (wrapping Z->A and A->Z), left/right
// choose which letter, fire commits. EVERY DIRECTION IS EDGE TRIGGERED so a
// held stick does not race through the alphabet -- the old rule, and the old
// two-line implementation: edge = (~current) AND previous.
// ---------------------------------------------------------------------------
gsInitialsLoop:
    jsr gsWaitFrame
    jsr readInput

    lda joyState
    sta gsTmp
    eor #$ff                            // bit set = pressed now (active low)
    and gsInitPrev                      // ...and released last frame
    sta gsInitEdge
    lda gsTmp
    sta gsInitPrev

    lda gsInitEdge
    and #%00000001                      // up
    bne !up+
    lda gsInitEdge
    and #%00000010                      // down
    bne !down+
    lda gsInitEdge
    and #%00000100                      // left
    bne !left+
    lda gsInitEdge
    and #%00001000                      // right
    bne !right+
    lda gsInitEdge
    and #GS_FIRE
    bne !commit+
    jmp gsInitialsLoop

!up:
    ldx gsInitSlot                      // next letter, wrapping Z -> A
    lda gsInitChars,x
    cmp #26
    bcc !bumpUp+
    lda #0
!bumpUp:
    clc
    adc #1
    sta gsInitChars,x
    jsr gsDrawInitials
    jmp gsInitialsLoop

!down:
    ldx gsInitSlot                      // previous letter, wrapping A -> Z
    lda gsInitChars,x
    cmp #2
    bcs !bumpDown+
    lda #27
!bumpDown:
    sec
    sbc #1
    sta gsInitChars,x
    jsr gsDrawInitials
    jmp gsInitialsLoop

!left:
    lda gsInitSlot
    beq !redraw+
    dec gsInitSlot
!redraw:
    jsr gsDrawInitials
    jmp gsInitialsLoop

!right:
    lda gsInitSlot
    cmp #2
    bcs !redraw-
    inc gsInitSlot
    jsr gsDrawInitials
    jmp gsInitialsLoop

!commit:
    jsr gsInsertScore

    // The old commit showed the updated table IMMEDIATELY and handed the player
    // back to attract already on the scores page, rather than making them wait
    // out a title cycle to see their own entry.
    jsr gsClearScreen
    lda #GS_PAGE_SCORES
    sta gsAttractPage
    lda #GS_ATTRACT_CYCLE
    sta gsAttractTimer
    jsr gsDrawScores
    lda #GS_ATTRACT
    sta gsState
    jsr gsWaitFireRelease               // don't let the commit press start a game
    rts

// ---------------------------------------------------------------------------
// gsInsertScore — the old insertHiscore: shift every entry below the insertion
// point down one slot, dropping the last, then write the new one in.
//
// Because the table is two flat arrays, "shift the tail down one entry" is a
// backwards byte copy of one entry's width -- done once for the digits and
// once for the names, both walking downwards so a slot is read before it is
// overwritten.
// ---------------------------------------------------------------------------
gsInsertScore:
    // ---- digits ----------------------------------------------------------
    lda gsRank
    jsr gsMul6
    clc
    adc #HS_DIGITS
    sta gsTmp                           // first byte index that must be written
    ldy #HS_COUNT * HS_DIGITS - 1
!dshift:
    cpy gsTmp
    bcc !dDone+
    tya
    sec
    sbc #HS_DIGITS
    tax
    lda hsDigits,x
    sta hsDigits,y
    dey
    cpy #$ff
    bne !dshift-
!dDone:

    // ---- names -----------------------------------------------------------
    lda gsRank
    jsr gsMul3
    clc
    adc #HS_NAMELEN
    sta gsTmp
    ldy #HS_COUNT * HS_NAMELEN - 1
!nshift:
    cpy gsTmp
    bcc !nDone+
    tya
    sec
    sbc #HS_NAMELEN
    tax
    lda hsName,x
    sta hsName,y
    dey
    cpy #$ff
    bne !nshift-
!nDone:

    // ---- the new entry ---------------------------------------------------
    lda gsRank
    jsr gsMul6
    tax
    ldy #0
!putDigits:
    lda hudScore,y
    sta hsDigits,x
    inx
    iny
    cpy #HS_DIGITS
    bne !putDigits-

    lda gsRank
    jsr gsMul3
    tax
    ldy #0
!putName:
    lda gsInitChars,y
    sta hsName,x
    inx
    iny
    cpy #HS_NAMELEN
    bne !putName-
    rts

// ---------------------------------------------------------------------------
// gsSeedTable — the old seedHiscoreTable: eight entries of three pseudo-random
// initials, every score equal, so the table is already descending as the insert
// logic requires. Called ONCE, at boot: this is the session-persistent state.
// ---------------------------------------------------------------------------
gsSeedTable:
    lda $dc04                           // CIA1 timer low: a changing byte is a
    sta gsSeed                          // fine seed for throwaway names

    ldx #0                              // X walks hsName byte by byte
!name:
    jsr gsRandomLetter
    sta hsName,x
    inx
    cpx #HS_COUNT * HS_NAMELEN
    bne !name-

    ldx #0                              // every seeded score is 000100
!score:
    lda #0
    sta hsDigits,x
    inx
    cpx #HS_COUNT * HS_DIGITS
    bne !score-
    ldx #3                              // the hundreds digit of each entry
!hundreds:
    lda #1
    sta hsDigits,x
    txa
    clc
    adc #HS_DIGITS
    tax
    cpx #HS_COUNT * HS_DIGITS
    bcc !hundreds-
    rts

// A = a pseudo-random screen code in 1..26 (A..Z). The old nextRandomLetter:
// quality is irrelevant for placeholder names.
gsRandomLetter:
    lda gsSeed
    asl
    eor gsSeed
    eor $dc04                           // a byte that changes every scanline
    sta gsSeed
    and #%00011111                      // 0..31
    cmp #26
    bcc !inRange+
    sec
    sbc #26                             // 0..25
!inRange:
    clc
    adc #1                              // 1..26
    rts

// ===========================================================================
// STARTING A GAME
// ===========================================================================
// ---------------------------------------------------------------------------
// gsStartGame — the old startGame, with the RESET WORK REPLACED WHOLESALE by
// the current engine's own subsystem inits. The old routine cleared object
// slots and player fields by hand; this engine has gameInit for exactly that
// and doing it any other way would be two writers of one truth.
//
// ORDER: run-scoped values first, then the engine's own reset, then the pages,
// and the display handed back LAST -- so the first gameplay IRQ finds a
// schedule that gameInit has already published.
// ---------------------------------------------------------------------------
gsStartGame:
    lda gsGames                         // counted FIRST, because a game is being
    cmp #$ff                            // started from this instruction on: a
    beq !counted+                       // diagnostic that only becomes true
    inc gsGames                         // after the work is a diagnostic that
!counted:                               // cannot describe the work
    jsr gsResetRun
    jsr gameInit                        // objects, sorter, player, weapon,
                                        // collision, sfx, level assets, enemy,
                                        // clip, waves, dropper, token
    jsr hudInit                         // every HUD bitmap and its dirty flags
    jsr scrollInit                      // both pages, worldProgress, frame 0
    jsr gsEnterGame                     // the executor owns the display again

    // THE TRANSITION IS NOT A GAMEPLAY FRAME. gameInit, hudInit and scrollInit
    // rebuild both terrain pages and republish everything in one main-thread
    // pass, which takes longer than a frame and so costs exactly one
    // gameOverrun -- a real miss, but of the frame that STARTS the game rather
    // than of one the game was running. gameInit already zeroes these; it runs
    // before the two heavy calls above, so they are zeroed again here, at the
    // last instant before the loop begins counting what it is actually meant to
    // measure.
    lda #0
    sta gameOverrun
    sta gameSpanMax
    sta gameSpanOver
    lda frameCounter                    // ...and the loop starts from THIS
    sta lastFrameSeen                   // frame. Zeroing it would make the very
                                        // first comparison a delta of a hundred
                                        // frames and count the whole boot as an
                                        // overrun.

    lda #GS_PLAYING
    sta gsState
    rts

// ---------------------------------------------------------------------------
// gsResetRun — the values that belong to ONE RUN and must not survive into the
// next: score, lives and the token currency.
//
// The engine's subsystem inits own everything else. These three are here
// because nothing else owns them: hudScore and hudLives were fed by the HUD's
// own placeholder and pkTokensP was deliberately left boot-scoped by
// src/pickup.asm until something could say what a restart means. This routine
// is that answer -- a new game starts at zero on all three.
// ---------------------------------------------------------------------------
gsResetRun:
    ldx #5
    lda #0
!score:
    sta hudScore,x
    dex
    bpl !score-

    lda #HUD_LIVES_MAX
    sta hudLives
    lda #0
    sta pkTokensP                       // P currency is RUN scoped
    lda hudDirty
    ora #HUD_DIRTY_LIVES | HUD_DIRTY_SCORE
    sta hudDirty
    rts

// ---------------------------------------------------------------------------
// gsEnterGame / gsBeginNonGame — the two sides of display and audio ownership.
// ---------------------------------------------------------------------------
gsEnterGame:
    lda $d016
    ora #%00010000                      // multicolour text back on: the terrain
    sta $d016                           // needs it and nothing rewrites it
    lda #0
    sta gsNonGame                       // from the next IRQ the executor owns
    rts                                 // the display again

gsBeginNonGame:
    jsr sfxSilence                      // every voice gated off and the channel
                                        // state reset, so no effect can resume
    lda #1
    sta gsNonGame
    lda $d016
    and #%11101111                      // MULTICOLOUR OFF: the text is hires
    sta $d016
    jmp gsClearScreen

// ===========================================================================
// THE ATTRACT IRQ STUB — the seam, and the whole of it
// ===========================================================================
// Reached from irqHandler when gsNonGame is set, after the acknowledge and the
// register save. It touches no schedule, no batch and no phase chain.
// ---------------------------------------------------------------------------
gsAttractIrq:
    lda #GS_D011
    sta $d011
    lda #GS_D018
    sta $d018
    lda #0
    sta $d015                           // no sprite of any kind
    sta $d020
    sta $d021                           // the old menu's black

    inc frameCounter                    // the non-game states pace on this too
    bne !noHi+
    inc frameCounter + 1
!noHi:
    lda #FRAME_IRQ_LINE
    sta $d012
    lda #PH_FRAME                       // park the executor at the frame
    sta exPhase                         // transaction, so gameplay re-enters in
                                        // a defined phase rather than mid-chain
    pla
    tay
    pla
    tax
    pla
    rti

// ===========================================================================
// DRAWING — screen RAM only. See the colour-RAM note in the header.
// ===========================================================================
// gsDrawText — blit X screen codes from (gsSrcLo) to (gsDstLo).
gsDrawText:
    ldy #0
!copy:
    lda (gsSrc),y
    sta (gsDst),y
    iny
    dex
    bne !copy-
    rts

// Set up gsSrcLo/gsDstLo from immediate addresses. Used by the four pages.
.macro gsText(src, dst, len) {
    lda #<src
    sta gsSrc
    lda #>src
    sta gsSrc + 1
    lda #<dst
    sta gsDst
    lda #>dst
    sta gsDst + 1
    ldx #len
    jsr gsDrawText
}

gsDrawTitle:
    gsText(gsTitleLine, GS_TITLE_AT, 20)
    gsText(gsPromptLine, GS_PROMPT_AT, 13)
    rts

gsDrawGameOver:
    gsText(gsOverLine, GS_OVER_AT, 9)
    rts

// ---------------------------------------------------------------------------
// gsDrawScores — the heading and eight rows of "III  DDDDDD", on rows 7, 9,
// 11 .. 21 at column 15, exactly where the old table sat.
//
// Rendered straight to the screen from the table rather than through the old
// pre-formatted page buffer: with the score already stored as digits there is
// nothing to format, so the buffer would be a copy of the table that could
// disagree with it.
// ---------------------------------------------------------------------------
gsDrawScores:
    gsText(gsHeadLine, GS_HEAD_AT, 11)

    lda #0
    sta gsRow
!row:
    // destination = GS_ROW0_AT + row * 80 (two screen rows apart)
    lda gsRow
    asl                                 // row * 2: the table is interleaved
    tax
    lda gsRowAddr,x
    sta gsDst
    lda gsRowAddr + 1,x
    sta gsDst + 1

    // three initials
    lda gsRow
    jsr gsMul3
    tax
    ldy #0
!name:
    lda hsName,x
    sta (gsDst),y
    inx
    iny
    cpy #HS_NAMELEN
    bne !name-

    lda #GS_SPACE                       // two spaces between name and score
    sta (gsDst),y
    iny
    sta (gsDst),y
    iny

    // six digits, as screen codes
    sty gsTmp
    lda gsRow
    jsr gsMul6
    tax
    ldy gsTmp
!digit:
    lda hsDigits,x
    clc
    adc #GS_DIGIT0
    sta (gsDst),y
    inx
    iny
    cpy #HS_ROW_W
    bne !digit-

    inc gsRow
    lda gsRow
    cmp #HS_COUNT
    bne !row-
    rts

// The eight row addresses, lo/hi interleaved, computed rather than authored:
// a hand-typed address table is a list of numbers that is right until somebody
// moves a row.
gsRowAddr:
.for (var i = 0; i < HS_COUNT; i++) {
    .byte <(GS_ROW0_AT + i * 80), >(GS_ROW0_AT + i * 80)
}

// ---------------------------------------------------------------------------
// gsDrawInitials — the prompt and the three letters, the selected one in
// REVERSE VIDEO.
//
// The old game highlighted the selected slot in yellow against white. Colour
// RAM belongs to the terrain here (see the header), so the highlight is the
// reverse-video bit instead: a screen-RAM-only mechanism that says the same
// thing at a glance.
// ---------------------------------------------------------------------------
gsDrawInitials:
    gsText(gsIPromptLine, GS_IPROMPT_AT, 19)

    ldx #0
!slot:
    lda gsInitChars,x
    cpx gsInitSlot
    bne !plain+
    ora #GS_REVERSE                     // the selected letter
!plain:
    sta gsTmp
    txa
    asl                                 // slots are two columns apart
    tay
    lda gsTmp
    sta GS_ISLOTS_AT,y
    inx
    cpx #3
    bne !slot-
    rts

// ---------------------------------------------------------------------------
// gsClearScreen — 1000 cells of space. The sprite pointers at $07f8 are NOT
// touched: they belong to the renderer's published schedule.
// ---------------------------------------------------------------------------
gsClearScreen:
    lda #GS_SPACE
    ldx #0
!fill:
    sta SCREEN + $000,x
    sta SCREEN + $100,x
    sta SCREEN + $200,x
    sta SCREEN + $2e8,x
    inx
    bne !fill-
    rts

// --- the text, in screen codes ---------------------------------------------
.encoding "screencode_upper"
gsTitleLine:   .text "MY FIRST C64 SHOOTER"       // 20
gsPromptLine:  .text "FIRE TO START"              // 13
gsHeadLine:    .text "HIGH SCORES"                // 11
gsOverLine:    .text "GAME OVER"                  // 9
gsIPromptLine: .text "ENTER YOUR INITIALS"        // 19
gsDoneLine:    .text "LEVEL COMPLETE"              // 14
gsTokensLine:  .text "P TOKENS: "                  // 10, then two digits
gsPressLine:   .text "PRESS FIRE"                  // 10
.encoding "petscii_upper"

// The next thing above is the schedule buffers at $c000, so this segment has
// room to grow into -- which is deliberate. The later Parallax-grade title will
// replace gsAttractIrq and the draw routines with something much larger, and it
// should not have to go looking for a home first.
.if (* > $c000) { .error "the game state code has run into the schedule buffers at $c000" }
