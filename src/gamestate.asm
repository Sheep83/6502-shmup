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
// COLOUR RAM IS OWNED BY THE PAGE, and gsClearScreen is where it is claimed.
// This file used to say colour RAM was never touched because it was "uniformly
// TERRAIN_COLOUR_RAM" -- an assumption that was true when src/terrain.asm was
// its only writer and has not been true since turrets and the boss health bar
// started colouring cells of their own. See gsClearScreen for what went wrong
// and why the fill uses the terrain value rather than a text colour.
//
// Every text routine below still writes SCREEN RAM ONLY: the colour is uniform,
// so there is nothing per-line to say. The old game coloured its text per line
// and per initials slot; that is the one piece of old presentation this could
// not keep, and the initials highlight is reverse video instead.
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
// THE CAMPAIGN IS OVER, all levels cleared. A terminal state with a safe way
// out: it holds a completion page and FIRE returns to attract. It exists so that
// the last level's Continue has somewhere legitimate to go -- never LEVEL3,
// which is not on the disk, and never back round to LEVEL1.
.const GS_CAMPAIGN_DONE = 5

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
.const GS_INF_AT      = SCREEN + 23 * 40 + 10       // the testing toggle, low
.const GS_INF_LEN     = 19                          // and out of the way
.const GS_HEAD_AT     = SCREEN + 4 * 40 + 14        // "HIGH SCORES"
.const GS_ROW0_AT     = SCREEN + 7 * 40 + 15        // rows 7,9,11..21, column 15
.const GS_OVER_AT     = SCREEN + 12 * 40 + 15       // "GAME OVER"
.const GS_DONE_AT     = SCREEN + 2 * 40 + 16        // "UPGRADES"
.const GS_TOKENS_AT   = SCREEN + 4 * 40 + 14       // "P TOKENS: nn"
.const GS_DFIRE_AT    = SCREEN + 18 * 40 + 13      // "PRESS FIRE"

// --- the upgrade shop's geometry --------------------------------------------
// One row per catalogue entry, then a blank line, then CONTINUE. The cursor is
// a character in the left margin of whichever row is selected, so moving it
// costs two screen writes rather than a redraw.
// ONE ROW IS A FIXED LAYOUT AT FIXED OFFSETS, so drawing it is a handful of
// stores at constant Y rather than a cursor walked along a string.
//
//     col  0   the selection cursor, ">" or " "
//     col  2   the name, GS_UPG_NAME_W wide
//     col 14   "LV n/m"
//     col 22   "COST n", or "MAX   " when there is nothing left to buy
.const GS_UPG_ROW0    = SCREEN + 8 * 40 + 6        // the CURSOR column of row 0
.const GS_UPG_STRIDE  = 2 * 40                     // a blank line between rows
.const GS_UPG_NAME_AT = 2
.const GS_UPG_NAME_W  = 10                         // "SPEED     "
.const GS_UPG_LVL_AT  = 14                         // "LV n/m", six wide
.const GS_UPG_COST_AT = 22                         // "COST n", six wide
.const GS_UPG_W       = GS_UPG_COST_AT + 6         // the whole row
.const GS_UPG_CURSOR  = 62                         // screen code for ">"
.const GS_UPG_ROWS    = UPG_COUNT + 1              // the catalogue, plus CONTINUE
.const GS_UPG_CONT    = UPG_COUNT                  // the CONTINUE row's index
.const GS_CAMP_AT     = SCREEN + 8 * 40 + 11       // "CAMPAIGN COMPLETE"
.const GS_MSG_AT      = SCREEN + 20 * 40 + 10      // refusals and confirmations
.const GS_MSG_W       = 20
.const GS_MSG_HOLD    = 90                         // frames a message stays up

// Joystick, active low, port 2 -- the same bits src/player.asm reads.
.const GS_UP    = %00000001
.const GS_DOWN  = %00000010
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

// --- INFINITE LIVES: a testing aid, and an explicit flag ---------------------
// IT IS A SEPARATE BYTE, NOT A FAKE LIVES COUNT. Stuffing $ff into hudLives
// would make the HUD draw a stock nobody has, would still decrement on every
// death, and would still reach zero eventually -- it would be a long game, not
// an infinite one. This says what it means, and src/player.asm reads it at the
// single point a life is consumed.
//
// IT CHEATS EXACTLY ONE THING. Damage, collision, the death fireball, the
// respawn and the invulnerability blink all still happen; a death simply does
// not cost a life. That is the whole of it.
//
// BOOT-SCOPED, like pkTokensP was before it. gsResetRun deliberately does NOT
// clear this: a new game started from the attract screen keeps whatever the
// tester set, which is the entire point of being able to set it there.
gsInfLives:     .byte 0             // 0 = off, and a cold start is off

// The I key's previous state, for the edge. Holding the key must toggle once,
// not sixty times a second.
gsKeyIDown:     .byte 0

// --- initials entry, straight from the old implementation -------------------
gsInitChars:    .byte 0, 0, 0       // 1..26, screen codes for A..Z
gsInitSlot:     .byte 0
gsInitPrev:     .byte 0             // last frame's stick, for edge detection
gsInitEdge:     .byte 0

// --- the upgrade shop -------------------------------------------------------
gsUpgSel:       .byte 0             // which row the cursor is on, 0..GS_UPG_ROWS-1
gsUpgPrev:      .byte 0             // last frame's stick, for edge detection
gsUpgMsg:       .byte 0             // frames the message line has left
gsUpgTmp:       .byte 0

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
// RELOCATED FOR THE BANK 2 PROOF. This code used to start at $8b00, which is
// bank-relative $0b00 -- underneath where bank 2 now keeps its screen matrix.
// It moves into the CHARACTER ROM SHADOW at $9000-$9fff instead: the VIC reads
// ROM there in banks 0 and 2 alike, so RAM at these addresses can never be
// fetched by the chip and is the one place in a VIC bank where code costs the
// display nothing. Nothing about this code is timing-critical -- gsAttractIrq
// only runs while gsNonGame is set, which is never during gameplay.
* = $9700 "game state code"

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
    cmp #GS_CAMPAIGN_DONE
    bne !notCamp+
    jsr gsCampaignDoneLoop
    jmp gsRouter
!notCamp:
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
    jsr gsInfToggle                     // the I key, title/attract ONLY

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

// ---------------------------------------------------------------------------
// gsInfToggle — the I key flips Infinite Lives. ATTRACT ONLY.
//
// ON THE PRESS EDGE, not on the level. gsAttractLoop runs every frame, so a
// held key would flip the flag fifty times a second and land on whichever side
// the player happened to let go on. gsKeyIDown remembers the last sample and
// only a 0 -> 1 transition does anything.
//
// It is called from the attract loop and from nowhere else, which is what keeps
// the cheat out of gameplay: src/main.asm's gameFrame never reaches this, so
// the key is inert once a game has started.
// ---------------------------------------------------------------------------
gsInfToggle:
    jsr readKeyI                        // A = 1 while the key is down
    cmp gsKeyIDown
    beq !steady+                        // no edge: held, or still up
    sta gsKeyIDown
    cmp #1
    bne !steady+                        // the RELEASE edge: nothing to do
    lda gsInfLives
    eor #1                              // the press edge: flip it
    sta gsInfLives
!steady:
    rts

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
// gsEnterLevelDone — the boss is dead and the ship has left the screen.
//
// THE RUN SURVIVES: this routine resets nothing at all. Score, lives, the P
// currency and every purchased upgrade are exactly as the level left them,
// which is the whole point of the state -- the shop below spends that currency
// and the next level inherits what it bought.
//
// IT IS ENTERED FROM src/boss.asm's EXIT PHASE, not from an interrupt and not
// from the boss's damage path. By the time this runs lvlPhase is LP_DONE, the
// scroller is frozen, the arena is empty and the ship has flown off the top --
// so there is no gameplay left to quiesce beyond taking the executor off the
// display, which gsBeginNonGame does.
// ---------------------------------------------------------------------------
gsEnterLevelDone:
    lda #GS_LEVELDONE
    sta gsState
    lda #0
    sta gsUpgSel                        // the cursor starts on the first ITEM,
    sta gsUpgMsg                        // never on CONTINUE
    lda #$ff
    sta gsUpgPrev                       // $ff is "nothing held": active-low, so
                                        // no edge can fire on the first frame
    jsr gsBeginNonGame
    jsr gsClearScreen
    jmp gsDrawUpgrades

// ---------------------------------------------------------------------------
// gsLevelDoneLoop — the shop. Stick moves, fire acts, CONTINUE leaves.
//
// ONE PRESS CANNOT BOTH BUY AND LEAVE, which is the failure this is shaped to
// avoid and which the brief calls out by name. Two things guarantee it: FIRE is
// read as a PRESS EDGE, so the button being still held after a purchase does
// nothing whatever; and CONTINUE is a row that has to be selected deliberately,
// never the row a purchase leaves the cursor on.
// ---------------------------------------------------------------------------
gsLevelDoneLoop:
    jsr gsWaitFrame
    jsr readInput

    // ---- the message line decays -----------------------------------------
    lda gsUpgMsg
    beq !noMsg+
    dec gsUpgMsg
    bne !noMsg+
    jsr gsClearMessage
!noMsg:

    // ---- the stick, as PRESS EDGES ---------------------------------------
    // joyState is ACTIVE LOW. A press is a bit that is 0 now and was 1 last
    // frame: (NOT now) AND (last). Anything else is a hold or a release.
    lda joyState
    eor #$ff
    and gsUpgPrev
    sta gsUpgTmp
    lda joyState
    sta gsUpgPrev

    lda gsUpgTmp
    and #GS_UP
    beq !noUp+
    lda gsUpgSel
    beq !noUp+                          // NO WRAP at either end, deliberately:
    dec gsUpgSel                        // wrapping from the top item to
    jsr gsDrawUpgrades                  // CONTINUE is exactly how a cursor ends
!noUp:                                  // up on it without being aimed there
    lda gsUpgTmp
    and #GS_DOWN
    beq !noDown+
    lda gsUpgSel
    cmp #GS_UPG_ROWS - 1
    bcs !noDown+
    inc gsUpgSel
    jsr gsDrawUpgrades
!noDown:

    lda gsUpgTmp
    and #GS_FIRE
    beq !idle+
    lda gsUpgSel
    cmp #GS_UPG_CONT
    bne !buy+
    jmp gsUpgradeContinue               // its rts is ours. A jmp because the
!buy:                                   // routine drifted out of branch range
    jsr gsUpgradeBuy
    jsr gsDrawUpgrades
!idle:
    jmp gsLevelDoneLoop

// ---------------------------------------------------------------------------
// gsUpgradeBuy — spend on the selected catalogue row, or refuse and say why.
// ---------------------------------------------------------------------------
gsUpgradeBuy:
    ldx gsUpgSel                        // on a catalogue row the selection IS
    lda cmpUpgrade,x                    // the catalogue index
    cmp #UPG_MAX_LEVEL
    bcc !notMax+
    gsText(gsMsgMaxLine, GS_MSG_AT, GS_MSG_W)
    jmp !message+
!notMax:
    // THE COST OF THE LEVEL BEING BOUGHT. At level n the next one costs entry n.
    tay
    lda gsUpgCost,y
    sta gsUpgTmp
    lda pkTokensP
    cmp gsUpgTmp
    bcs !afford+
    gsText(gsMsgPoorLine, GS_MSG_AT, GS_MSG_W)
    jmp !message+
!afford:
    sec
    sbc gsUpgTmp
    sta pkTokensP                       // the currency lives in src/pickup.asm
                                        // and what is left carries forward
    ldx gsUpgSel
    inc cmpUpgrade,x
    jsr cmpApplyUpgrades                // the purchase reaches gameplay HERE,
    jsr cmpSpeedReset                 // not at the next level load. The
                                        // accumulators restart so the new rate
                                        // begins from a clean phase
    gsText(gsMsgBuyLine, GS_MSG_AT, GS_MSG_W)
!message:
    lda #GS_MSG_HOLD
    sta gsUpgMsg
    rts

// ---------------------------------------------------------------------------
// gsUpgradeContinue — leave the shop and start the next level, or end the run.
//
// THE LOAD HAPPENS HERE AND NOWHERE ELSE. Not in the boss's death path and not
// in an interrupt: by the time this runs the game has been a non-game state for
// as long as the player took to shop, the executor is off the display and the
// only thing running is this loop.
// ---------------------------------------------------------------------------
gsUpgradeContinue:
    jsr gsWaitFireRelease               // one press cannot also act on the page
                                        // it arrives at
    jsr cmpHasNextLevel
    bcs !another+
    jmp gsEnterCampaignDone             // the last level: END. Never LEVEL3,
                                        // which is not on the disk, and never
                                        // round to LEVEL1
!another:
    inc cmpLevel                        // the sequence advances BEFORE the load,
                                        // because cmpLevelName reads cmpLevel

    jsr gsDrawLoading                   // the drive takes about half a second
    jsr levelLoadRuntime                // src/levelload.asm: the boot loader's
    bcc !loaded+                        // own code, in a mid-game safe wrapper

    // ---- the load failed, and the run must not continue blind -------------
    // A BOOT failure halts on a red border because there is nothing to fall
    // back to. Here there is: the player keeps the run they played and the
    // campaign ends cleanly, rather than playing a level made of whatever
    // happens to be in RAM.
    dec cmpLevel                        // the RESIDENT package is still the old
    jmp gsEnterCampaignDone             // one, so the index must say so
!loaded:
    jsr gsEnterNextLevel
    lda #GS_PLAYING
    sta gsState
    jsr gsEnterGame                     // the executor owns the display again
    rts

// ---------------------------------------------------------------------------
// gsEnterNextLevel — adopt the package that has just been loaded.
//
// THE RESET BOUNDARY, and the most dangerous few lines in the campaign. Every
// routine called here is one the BOOT path already calls, in the boot path's
// order: nothing bespoke, and nothing a level entry needs is invented for it.
//
//   terrainApplyPackage   the new level's charset and palette
//   levelApplySprites     the new level's enemy and boss artwork
//   terrainInit           colour RAM, $d022/$d023, the transposed sub-rows
//   turretBuildTables     the new level's turret placement, from its package
//   ebulletInit           no hostile projectile survives a level
//   turretInit            every authored turret standing, none visible
//   gameInit              objects, sorter, player, weapon, collision, sfx,
//                         level assets, enemies, clip, WAVES (and with them the
//                         trigger cursor), boss, dropper, token
//   scrollInit            both pages rebuilt, stageTopRow back to the start
//
// WHAT IS DELIBERATELY NOT HERE: pickupInit, which would zero the P currency,
// and gsResetRun, which would zero the score, the lives and every purchase.
// Those are RUN state and this is a LEVEL boundary. cmpApplyUpgrades runs last
// so that a level-local reset cannot quietly undo a purchase.
// ---------------------------------------------------------------------------
gsEnterNextLevel:
    jsr terrainApplyPackage
    jsr levelApplySprites
    jsr terrainInit
    jsr turretBuildTables
    jsr ebulletInit
    jsr turretInit
    jsr gameInit
    jsr scrollInit
    jsr cmpApplyUpgrades
    jsr cmpSpeedReset
    rts

// ---------------------------------------------------------------------------
// THE CAMPAIGN IS OVER — a terminal state with one safe way out.
// ---------------------------------------------------------------------------
gsEnterCampaignDone:
    lda #GS_CAMPAIGN_DONE
    sta gsState
    jsr gsBeginNonGame
    jsr gsClearScreen
    jmp gsDrawCampaignDone

gsCampaignDoneLoop:
    jsr gsWaitFrame
    jsr readInput
    jsr gsDrawCampaignDone
    lda joyState
    and #GS_FIRE
    bne !wait+
    jsr gsWaitFireRelease
    lda #GS_ATTRACT
    sta gsState
    jsr gsEnterAttract
    rts
!wait:
    jmp gsCampaignDoneLoop

gsDrawCampaignDone:
    gsText(gsCampLine,  GS_CAMP_AT, 17)
    gsText(gsPressLine, GS_DFIRE_AT, 10)
    rts

// ---------------------------------------------------------------------------
// gsDrawUpgrades — the whole page, re-stamped whenever something changes.
//
// NOT EVERY FRAME, unlike the other non-game pages: the shop is static between
// inputs, and re-stamping it sixty times a second would fight the message
// line's own timer. It is drawn on entry and after every action instead.
// ---------------------------------------------------------------------------
gsDrawUpgrades:
    gsText(gsUpgHeadLine, GS_DONE_AT, 8)
    gsText(gsTokensLine, GS_TOKENS_AT, 10)
    jsr gsDrawTokenCount

    ldx #0
!row:
    stx gsUpgTmp
    jsr gsUpgRowAddr
    jsr gsDrawUpgradeRow
    ldx gsUpgTmp
    inx
    cpx #UPG_COUNT
    bne !row-

    ldx #GS_UPG_CONT                    // ...and the CONTINUE row below them
    stx gsUpgTmp
    jsr gsUpgRowAddr
    ldy #GS_UPG_NAME_AT
    ldx #0
!cont:
    lda gsContLine,x
    sta (gsDst),y
    iny
    inx
    cpx #8
    bne !cont-

    jsr gsDrawCursor
    rts

// gsUpgTmp = the row index -> gsDst = GS_UPG_ROW0 + index * GS_UPG_STRIDE.
gsUpgRowAddr:
    lda #<GS_UPG_ROW0
    sta gsDst
    lda #>GS_UPG_ROW0
    sta gsDst + 1
    ldx gsUpgTmp
    beq !done+
!add:
    lda gsDst
    clc
    adc #<GS_UPG_STRIDE
    sta gsDst
    lda gsDst + 1
    adc #>GS_UPG_STRIDE
    sta gsDst + 1
    dex
    bne !add-
!done:
    rts

// One catalogue row at gsDst, for the entry in gsUpgTmp.
gsDrawUpgradeRow:
    // ---- the name ---------------------------------------------------------
    // One fixed-width name per entry, so entry n starts at n * GS_UPG_NAME_W.
    lda #0                              // offset = index * GS_UPG_NAME_W
    ldx gsUpgTmp
    beq !nameBase+
!mul:
    clc
    adc #GS_UPG_NAME_W
    dex
    bne !mul-
!nameBase:
    tax                                 // X = the offset into gsUpgNames
    ldy #GS_UPG_NAME_AT
!name:
    lda gsUpgNames,x
    sta (gsDst),y
    inx
    iny
    cpy #GS_UPG_NAME_AT + GS_UPG_NAME_W
    bne !name-

    // ---- "LV n/m" ---------------------------------------------------------
    ldy #GS_UPG_LVL_AT
    ldx #0
!lv:
    lda gsLvLine,x
    sta (gsDst),y
    iny
    inx
    cpx #3
    bne !lv-
    ldx gsUpgTmp
    lda cmpUpgrade,x
    clc
    adc #GS_DIGIT0
    sta (gsDst),y
    iny
    lda #47                             // "/"
    sta (gsDst),y
    iny
    lda #UPG_MAX_LEVEL + GS_DIGIT0
    sta (gsDst),y

    // ---- "COST n", or "MAX   " -------------------------------------------
    ldx gsUpgTmp
    lda cmpUpgrade,x
    cmp #UPG_MAX_LEVEL
    bcc !cost+
    ldy #GS_UPG_COST_AT
    ldx #0
!maxed:
    lda gsMaxLine,x
    sta (gsDst),y
    iny
    inx
    cpx #6
    bne !maxed-
    rts
!cost:
    tay                                 // level n -> the cost of level n + 1
    lda gsUpgCost,y
    pha
    ldy #GS_UPG_COST_AT
    ldx #0
!costText:
    lda gsCostLine,x
    sta (gsDst),y
    iny
    inx
    cpx #5
    bne !costText-
    pla
    clc
    adc #GS_DIGIT0                      // a cost is one digit; the guard beside
    sta (gsDst),y                       // gsUpgCost is what keeps that true
    rts

// The cursor: ">" on the selected row, a space on every other.
gsDrawCursor:
    ldx #0
!row:
    stx gsUpgTmp
    jsr gsUpgRowAddr
    lda gsUpgTmp
    cmp gsUpgSel
    bne !blank+
    lda #GS_UPG_CURSOR
    jmp !put+
!blank:
    lda #GS_SPACE
!put:
    ldy #0                              // column 0 of the row IS the cursor
    sta (gsDst),y                       // column, so no negative offset is
                                        // needed -- an earlier version used
                                        // (gsDst),y with y = $ff and added 255
    ldx gsUpgTmp
    inx
    cpx #GS_UPG_ROWS
    bne !row-
    rts

gsDrawTokenCount:
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

gsClearMessage:
    lda #GS_SPACE
    ldy #GS_MSG_W - 1
!clr:
    sta GS_MSG_AT,y
    dey
    bpl !clr-
    rts

gsDrawLoading:
    gsText(gsLoadLine, GS_MSG_AT, GS_MSG_W)
    rts

// --- the catalogue's numbers ------------------------------------------------
// PRICED IN COMPLETED P TOKENS, WHICH ARE NOT PICKUPS. pkTokensP counts banked
// UNITS and PICKUP_P_PER_UNIT pickups charge one of them, so a cost here is
// multiplied by three before the player ever sees it in the arena. The first
// prices were 3 and 5, which quietly asked for nine and fifteen pickups.
gsUpgCost:
    .byte 1                             // level 0 -> 1: one completed P token
    .byte 2                             // level 1 -> 2: two
.if (* - gsUpgCost != UPG_MAX_LEVEL) {
    .error "one cost per purchasable upgrade level"
}


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
    // ---- THE VIC BANK IS PART OF STARTING A LEVEL ------------------------
    // BEFORE gameInit and scrollInit, and the order is the whole point:
    // scrollInit ends by publishing frame 0, and a frame record published while
    // vicBank2 was still set would carry the BOSS's $d018 and pointer
    // destination into ordinary play. That is precisely what the broken restart
    // was -- the scroller advanced pages nobody was looking at while the VIC
    // still displayed the frozen bank 2 arena, so the picture slid with the
    // fine scroll and snapped back at every coarse step.
    //
    // THIS IS THE SEAM, not the FIRE handler. Any route that begins or restarts
    // ordinary level gameplay comes through gsStartGame, so the contract is
    // stated once here rather than patched into each caller -- which is what
    // the upgrade screen and level 2 will need.
    jsr vicSelectBank0

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
    sta pkTokensP                       // P currency is RUN scoped...
    sta pkCharge                        // ...and so is the partial charge
                                        // toward the next unit. A new run
                                        // starts at [][][] 0, not part way
                                        // through somebody else's set.
    jsr hudPReset                       // and the HUD shows that, rather than
                                        // the last run's boxes
    jsr cmpResetRun                     // back to LEVEL1 with a stock ship: the
                                        // campaign index and every purchased
                                        // upgrade are RUN state, exactly like
                                        // the score and the currency above
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
    // THE VIC BANK IS PART OF THIS CONTRACT, and v1.0 of the bank 2 proof left
    // it out. Everything else a non-game page needs is established explicitly
    // -- $d011, $d018, $d015, $d020, $d021 and the multicolour bit -- but the
    // BANK those registers are relative to was simply inherited, because until
    // the boss arena there was only ever one.
    //
    // Arriving here from the boss meant arriving in bank 2, where GS_D018's VM
    // field names $8400 instead of $0400: the raster executor's machine code
    // rendered as a screen matrix. The font was right, because bank 2 shows the
    // character ROM at the same bank-relative address bank 0 does, which is
    // exactly why the corrupted LEVEL COMPLETE page was garbage characters in a
    // legible typeface.
    //
    // It is done FIRST, before the screen is cleared: gsClearScreen writes the
    // matrix at $0400, and there is no point writing a page the VIC is not
    // looking at.
    jsr sfxSilence                      // every voice gated off and the channel
                                        // state reset, so no effect can resume
    lda #1
    sta gsNonGame                       // FIRST, and before the bank below:
                                        // while this is clear the frame IRQ is
                                        // still exFrame, which commits $dd00
                                        // from the frame record every frame. A
                                        // bank selected before this byte could
                                        // be undone by the very next IRQ and
                                        // the state would be stranded in bank 2
                                        // with no executor left to fix it.
    jsr vicSelectBank0
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

    // THE CHEAT IS VISIBLE OR IT IS A TRAP. Both lines are the same length, so
    // the one being drawn always covers the other and the page needs no clear.
    // The title page only: the high-score page does not carry it, and the flag
    // survives the cycle regardless because it lives in state, not on screen.
    lda gsInfLives
    beq !off+
    gsText(gsInfOnLine, GS_INF_AT, GS_INF_LEN)
    rts
!off:
    gsText(gsInfOffLine, GS_INF_AT, GS_INF_LEN)
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
    // ---- the matrix ------------------------------------------------------
    lda #GS_SPACE
    ldx #0
!fill:
    sta SCREEN + $000,x
    sta SCREEN + $100,x
    sta SCREEN + $200,x
    sta SCREEN + $2e8,x
    inx
    bne !fill-

    // ---- ...AND THE COLOUR RAM THAT GOES WITH IT --------------------------
    // THE PAGE OWNS ITS OWN COLOURS. The header of this file used to say colour
    // RAM was never touched because it was "uniformly TERRAIN_COLOUR_RAM", and
    // that was true when src/terrain.asm was the only thing that wrote it. It
    // has not been true for a long time: src/turrets.asm colours a turret's four
    // body cells and only restores them when that body leaves, and
    // src/boss.asm's health bar paints BOSS_BAR_FULL -- red -- across row 1.
    // Anything still coloured when the level ended stayed coloured, and the
    // attract page drew its white text straight on top of it. That is why a few
    // letters of the title came back pink.
    //
    // Colour RAM is NOT part of the VIC bank and NOT double buffered, so no
    // amount of bank or page discipline could have fixed this; the page simply
    // had no colour owner. It has one now.
    //
    // THE VALUE IS THE RESIDENT LEVEL'S COLOUR-RAM FILL, not a text colour, and
    // that is deliberate: bit 3 selects multicolour for the cell and the low
    // nibble is its colour, so with $d016's MCM bit off -- which gsBeginNonGame
    // guarantees -- every cell reads as plain text in that colour, and the
    // value gameplay expects to find is restored at the same time. One fill
    // satisfies both readers.
    //
    // IT IS trnCramValue AND NOT THE COMPILE-TIME CONSTANT, and that is what
    // the title screen's colour was telling us. It used to load
    // TERRAIN_COLOUR_RAM -- the value of whatever level the ENGINE was built
    // against -- so a LEVELDIR=src/level2 build drew its title text in level
    // 2's light grey (15) instead of level 1's brown (9). The title screen is
    // not level content; the leak was this fill.
    lda trnCramValue
    ldx #0
!col:
    sta COLOUR_RAM + $000,x
    sta COLOUR_RAM + $100,x
    sta COLOUR_RAM + $200,x
    sta COLOUR_RAM + $2e8,x
    inx
    bne !col-
    rts

// --- the text, in screen codes ---------------------------------------------
.encoding "screencode_upper"
gsTitleLine:   .text "MY FIRST C64 SHOOTER"       // 20
gsPromptLine:  .text "FIRE TO START"              // 13
gsInfOffLine:  .text "INFINITE LIVES: OFF"        // 19, and the same length
gsInfOnLine:   .text "INFINITE LIVES: ON "        // 19, so one covers the other
gsHeadLine:    .text "HIGH SCORES"                // 11
gsOverLine:    .text "GAME OVER"                  // 9
gsIPromptLine: .text "ENTER YOUR INITIALS"        // 19
gsUpgHeadLine: .text "UPGRADES"                    // 8
gsCampLine:    .text "CAMPAIGN COMPLETE"           // 17
gsContLine:    .text "CONTINUE"                    // 8
gsLvLine:      .text "LV "                         // 3, then "n/m"
gsCostLine:    .text "COST "                       // 5, then one digit
gsMaxLine:     .text "MAX   "                      // 6, the same width as COST
gsMsgBuyLine:  .text "UPGRADE INSTALLED   "        // GS_MSG_W
gsMsgPoorLine: .text "NOT ENOUGH P TOKENS "        // GS_MSG_W
gsMsgMaxLine:  .text "ALREADY AT MAXIMUM  "        // GS_MSG_W
gsLoadLine:    .text "LOADING NEXT LEVEL  "        // GS_MSG_W
gsUpgNames:    .text "SPEED     "                  // GS_UPG_NAME_W per entry
gsTokensLine:  .text "P TOKENS: "                  // 10, then two digits
gsPressLine:   .text "PRESS FIRE"                  // 10
.encoding "petscii_upper"

// The next thing above is the schedule buffers at $c000, so this segment has
// room to grow into -- which is deliberate. The later Parallax-grade title will
// replace gsAttractIrq and the draw routines with something much larger, and it
// should not have to go looking for a home first.
.if (* > $9fff) { .error "the game state code has left the character ROM shadow at $9fff" }
