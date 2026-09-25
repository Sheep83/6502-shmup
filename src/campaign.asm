// ===========================================================================
// campaign.asm — what survives a level, and what comes next
// ===========================================================================
// THE RUN'S MEMORY. Everything in this file outlives a level package load; the
// whole point of it is to be the one place that does. A level's runtime state --
// objects, enemies, bullets, turrets, the boss, the wave cursor -- is reset by
// gameInit and its neighbours on every level entry, and none of it lives here.
//
//     LEVEL 1  ->  boss defeated  ->  UPGRADE screen  ->  LEVEL 2  ->  END
//
// ---------------------------------------------------------------------------
// WHAT IS HERE AND WHAT DELIBERATELY IS NOT
// ---------------------------------------------------------------------------
// STABLE FIELDS WERE NOT MOVED. The score already lives in src/hud.asm as six
// digit bytes, lives in the HUD state beside it, and the P currency in
// src/pickup.asm as pkTokensP -- each owned by the module that maintains it,
// each already surviving a death and a respawn because gsResetRun is what
// clears them. Relocating them into a "campaign block" would have been a
// rename dressed as a design: they would survive a level load exactly as well
// where they are, and every reader of them would have had to change.
//
// So this file holds only what did not exist before: WHERE THE RUN IS in the
// sequence, and WHAT IT HAS BOUGHT.
//
// ---------------------------------------------------------------------------
// THE SEQUENCE IS A TABLE, NOT A CHAIN OF TESTS
// ---------------------------------------------------------------------------
// `if level == 1 then load LEVEL2` scattered through the state machine is the
// thing this exists to avoid. One table holds the filenames in order; the index
// says where the run is; "is there another level" is a compare against the
// count. Adding level 3 is a row in the table and a longer name blob -- no new
// state, no new branch, and nothing in the upgrade screen or the loader changes.
// ===========================================================================

// --- the level sequence ------------------------------------------------------
// CBM FILENAMES, PETSCII, FIXED WIDTH. The drive matches a directory entry by
// the bytes it was given; c1541 wrote these names from the Makefile in upper
// case, and upper-case ASCII and PETSCII share $41-$5a, so the literals below
// match the entries exactly. Fixed width because a table of equal-length
// records is indexed by a shift rather than walked.
.const CMP_NAME_LEN = 6                 // "LEVEL1", "LEVEL2"
.const CMP_LEVELS   = 2

// --- the upgrade catalogue ---------------------------------------------------
// SMALL AND HONEST. The brief offered FIREPOWER / COOLING / SHIELD / SPEED and
// said a smaller real catalogue beats a larger notional one, so this ships the
// one upgrade that has a genuine, measurable effect on an existing tunable
// system and does not pretend to the other three.
//
// SPEED moves the ship. src/player.asm walks plyX/plyY by exactly one pixel a
// frame per axis; an upgrade grants an EXTRA pixel on a fixed subset of frames,
// so the base behaviour is untouched and the upgraded rate is a deterministic
// fraction rather than a doubling. See playerSpeedBoostDue.
.const UPG_SPEED    = 0
.const UPG_COUNT    = 1                 // the catalogue, entire
.const UPG_MAX_LEVEL = 2                // 0 = stock, 2 = fully upgraded

* = $c780 "campaign state"

// WHERE THE RUN IS. An index into cmpLevelNames, 0-based: 0 is LEVEL1. It is
// the only thing that says which package is resident.
cmpLevel:       .byte 0

// WHAT THE RUN HAS BOUGHT. One byte per catalogue entry, 0..UPG_MAX_LEVEL.
// Indexed by the UPG_ constants above.
cmpUpgrade:     .fill UPG_COUNT, 0

// THE ONE DERIVED VALUE THAT IS CACHED. playerTick reads it twice a frame --
// once per axis -- and deriving it from cmpUpgrade there would be a table
// lookup on the hot path for a number that changes only in the shop.
// cmpApplyUpgrades writes it, and is called on every level entry and after
// every purchase.
//
// IT IS A FRACTION OF A PIXEL IN 1/256ths, not a frame mask. Zero means stock:
// the accumulator can never carry, so the ship takes exactly one pixel a frame
// and the upgraded path costs it one `adc` and one untaken branch.
cmpSpeedFrac:   .byte 0                 // 0, 64 or 128 -- see cmpSpeedFracTab

// THE SUB-PIXEL ACCUMULATORS, one per axis, and the direction each was last
// moving in. Indexed 0 = X, 1 = Y by playerFracStep.
//
// THEY ARE THE PLAYER'S AND THEY LIVE HERE, for two reasons. The player state
// block at $c51a is exactly full -- four more bytes ran it into the scroll
// state at $c540 -- and this file is imported BEFORE src/player.asm, which is
// what lets src/player.asm name them at all. The POSITION itself is untouched:
// collision, the hitscan, pickups, the boss and the renderer all still read the
// integer plyX/plyXHi/plyY they always did, so not one consumer had to change.
plyFrac:        .byte 0, 0
plyFracDir:     .byte 0, 0

campaignStateEnd:
.if (campaignStateEnd > $c7c0) {
    .error "the campaign state has grown past its $c780 run"
}

// IN THE CHARACTER ROM SHADOW, like src/gamestate.asm and for its reason: the
// VIC reads ROM at $9000-$9fff in banks 0 and 2 alike, so RAM here can never be
// fetched as graphics and costs the display nothing. $9400 is the boss code and
// $9700 the game state; this is the run below both.
* = $9000 "campaign code"

// ---------------------------------------------------------------------------
// cmpResetRun — a NEW GAME. Called by gsResetRun, beside the score and lives.
// ---------------------------------------------------------------------------
cmpResetRun:
    lda #0
    sta cmpLevel
    ldx #UPG_COUNT - 1
!clear:
    sta cmpUpgrade,x
    dex
    bpl !clear-
    // falls into cmpApplyUpgrades: a fresh run is a stock ship

// ---------------------------------------------------------------------------
// cmpApplyUpgrades — turn the purchased levels into the values gameplay reads.
//
// CALLED AFTER EVERY PURCHASE AND ON EVERY LEVEL ENTRY. The second is what makes
// an upgrade survive a package load: nothing in the level-local reset can undo
// a purchase, because the purchase lives here and this re-derives from it.
// ---------------------------------------------------------------------------
cmpApplyUpgrades:
    ldx cmpUpgrade + UPG_SPEED
    beq !stock+
    lda cmpSpeedFracTab - 1,x           // level 1 -> entry 0
    sta cmpSpeedFrac
    rts
!stock:
    lda #0
    sta cmpSpeedFrac
    rts

// ---------------------------------------------------------------------------
// cmpSpeedReset — clear the sub-pixel state, out of phase between the axes.
//
// CALLED WHEREVER THE SHIP IS (RE)PLACED OR ITS SPEED CHANGES: playerInit, so a
// death and respawn never inherit a part-earned pixel, and beside
// cmpApplyUpgrades after a purchase or a level load.
//
// THE TWO AXES ARE SEEDED HALF A PERIOD APART. Both accumulate at the same
// rate, so seeded alike they carry on the same frame and a diagonal gains its
// extra pixel on X and Y together -- the two-pixel diagonal lurch the old
// frame-mask version had. $80 of separation interleaves them.
// ---------------------------------------------------------------------------
cmpSpeedReset:
    lda #0
    sta plyFrac + 0
    sta plyFracDir + 0
    sta plyFracDir + 1
    lda #$80
    sta plyFrac + 1
    rts

// A QUARTER AND A HALF OF A PIXEL, in 1/256ths, so the accumulator's carry is
// the whole test. The rates are unchanged from the measured ones:
//
//     level 0   frac 0     no carry, ever    1.00 px/frame  (stock, untouched)
//     level 1   frac 64    carries 1 in 4    1.25 px/frame
//     level 2   frac 128   carries 1 in 2    1.50 px/frame
//
// NOT 2 px EVERY FRAME. Doubling the rate would have been one branch, and it
// would also have doubled the distance the ship crosses between two reads of the
// stick -- a different game rather than a faster ship.
// Which stick bit means "negative" and "positive" on each axis, indexed the
// same way the accumulators are: 0 = X, 1 = Y.
// The stick bits are restated rather than imported: src/player.asm declares
// JOY_LEFT and friends and is parsed AFTER this file, so naming them here is a
// forward reference. The guard below is what keeps the two statements one
// statement -- it runs once src/player.asm has been parsed.
.const CMP_JOY_UP    = %00000001
.const CMP_JOY_DOWN  = %00000010
.const CMP_JOY_LEFT  = %00000100
.const CMP_JOY_RIGHT = %00001000
cmpFracNeg: .byte CMP_JOY_LEFT,  CMP_JOY_UP
cmpFracPos: .byte CMP_JOY_RIGHT, CMP_JOY_DOWN

cmpSpeedFracTab:
    .byte 64                            // level 1: a quarter of a pixel a frame
    .byte 128                           // level 2: a half
.if (* - cmpSpeedFracTab != UPG_MAX_LEVEL) {
    .error "the speed fraction table needs one entry per purchasable level"
}

// ---------------------------------------------------------------------------
// cmpSpeedFracStep — the SUB-PIXEL half of the speed upgrade, one axis.
//
// Entry: X = 0 for the X axis, 1 for the Y axis.
// Exit:  C set if this axis has earned an extra whole pixel this frame.
//
// ---------------------------------------------------------------------------
// WHY AN ACCUMULATOR, AND WHAT IT CAN AND CANNOT FIX
// ---------------------------------------------------------------------------
// The first implementation granted the extra pixel on `frameCounter AND mask`,
// a GLOBAL clock, and called the whole movement routine a second time. Three
// things were wrong with that, and only two of them are about smoothness:
//
//   * THE CADENCE DID NOT BELONG TO THE PLAYER. The boost landed on fixed
//     absolute frames, so whether a given press got one depended on when the
//     press happened. A short tap could be all boost or none.
//   * BOTH AXES BOOSTED TOGETHER. One global mask meant a diagonal gained its
//     extra pixel on X and on Y in the SAME frame -- a two-pixel diagonal
//     lurch. The two accumulators here are seeded out of phase, so the extra
//     pixels interleave instead.
//   * A REVERSAL INHERITED THE CREDIT. Three frames of right-hand motion left
//     the counter nearly full, so the first frame of the reversal jumped two
//     pixels the other way. The accumulator is cleared when an axis changes
//     direction or stops.
//
// WHAT IT CANNOT FIX, and it is worth being plain about: the rendered position
// is an integer pixel, so an average of 1.25 px/frame MUST be three frames of
// one pixel and one of two. No sub-pixel scheme changes that; what it changes
// is that the two-pixel frame is regular with respect to the player's own
// motion rather than to a free-running counter, and that the two axes do not
// take theirs at the same moment.
//
// STOCK IS EXACTLY ONE PIXEL A FRAME, bit for bit. cmpSpeedFrac is zero, the
// add cannot carry, and the branch is never taken -- the same instruction
// sequence the engine has always run, plus one add.
// ---------------------------------------------------------------------------
cmpSpeedFracStep:
    // THE AXIS'S DIRECTION, READ FROM THE STICK HERE rather than returned by
    // playerStepX/Y: the player CODE segment at $4000 is full and this one has
    // room, so the byte-counting went this way round. $ff one way, $01 the
    // other, $00 stationary -- the value only has to be COMPARABLE with last
    // frame's, not meaningful.
    lda joyState
    and cmpFracNeg,x                    // LEFT for X, UP for Y
    bne !notNeg+
    lda #$ff
    jmp !haveDir+
!notNeg:
    lda joyState
    and cmpFracPos,x                    // RIGHT for X, DOWN for Y
    bne !stopped+
    lda #$01
    jmp !haveDir+
!stopped:
    lda #0
!haveDir:
    cmp plyFracDir,x                    // same direction as last frame?
    beq !carryOn+
    sta plyFracDir,x                    // no: a reversal or a stop. The credit
    lda #0                              // earned going one way must not be
    sta plyFrac,x                       // spent lurching the other
    clc
    rts
!carryOn:
    cmp #0
    beq !idle+                          // not moving: nothing to accumulate
    lda plyFrac,x
    clc
    adc cmpSpeedFrac                    // 0, 64 or 128 of 256 -- see
    sta plyFrac,x                       // cmpSpeedFracTab below
    rts                                 // the add's carry IS the answer
!idle:
    clc
    rts

// IT LIVES HERE AND NOT IN src/player.asm because the player CODE segment at
// $4000 is full -- splitting the step per axis and adding this ran it into the
// scroller at $4340 -- and because this is the upgrade's logic sitting beside
// the upgrade's state. src/player.asm calls it; this file is imported first.

// ---------------------------------------------------------------------------
// cmpHasNextLevel — C set if another level follows the current one.
// ---------------------------------------------------------------------------
cmpHasNextLevel:
    lda cmpLevel
    cmp #CMP_LEVELS - 1
    bcc !yes+
    clc                                 // the last level: the campaign ends
    rts
!yes:
    sec
    rts

// ---------------------------------------------------------------------------
// cmpLevelName — point levelLoad at the CURRENT level's filename.
// Returns X/Y = the name pointer, A = its length, as SETNAM wants them.
// ---------------------------------------------------------------------------
cmpLevelName:
    lda cmpLevel
    asl                                 // n * 2
    sta cmpNameTmp
    asl                                 // n * 4
    clc
    adc cmpNameTmp                      // n * 6 = CMP_NAME_LEN
    clc
    adc #<cmpLevelNames
    tax
    lda #>cmpLevelNames
    adc #0
    tay
    lda #CMP_NAME_LEN
    rts

.if (CMP_NAME_LEN != 6) {
    .error "cmpLevelName forms n * 6 as n*4 + n*2; a different width needs different code"
}
cmpNameTmp: .byte 0                     // scratch for the multiply above

cmpLevelNames:
    .text "LEVEL1"
    .text "LEVEL2"
cmpLevelNamesEnd:

.if (cmpLevelNamesEnd - cmpLevelNames != CMP_LEVELS * CMP_NAME_LEN) {
    .error "the level name table is not CMP_LEVELS fixed-width names"
}
