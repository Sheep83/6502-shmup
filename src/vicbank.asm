// ===========================================================================
// vicbank.asm — which 16 KB the VIC is looking at, and what lives there
// ===========================================================================
// MAIN THREAD ONLY. This file writes exactly one hardware register outside the
// copies it makes -- $dd00, the CIA 2 port that selects the VIC's bank -- and
// it is the only file in the game that writes it at all.
//
// WHY THIS EXISTS. Level 1 was built in VIC bank 0 and every VIC-visible asset
// ended up there because that is where the machine happens to point at power
// on. Nothing ever SELECTED bank 0; it was simply never changed. That is an
// assumption rather than a decision, and a boss with its own artwork will not
// fit alongside a level's in one 16 KB window. This file turns the assumption
// into a choice, and proves the choice works by making the existing boss arena
// run in bank 2 with nothing about it looking different.
//
// IT IS NOT A BANK MANAGER. There are two banks, two routines and one flag.
// Nothing here allocates, tracks, reference-counts or schedules anything, and
// the day a real boss needs different artwork it edits the copy list below.
//
// ---------------------------------------------------------------------------
// THE ONE RULE THAT MAKES THIS CHEAP
// ---------------------------------------------------------------------------
// A sprite pointer and the CB/VM fields of $d018 are BANK-RELATIVE: they name
// an offset inside whichever 16 KB the VIC is looking at. So if a thing lives
// at the same offset in both banks, every number the renderer computes for it
// is already correct in both -- no mapping table, no bank test in the mux, no
// change to the schedule.
//
// Every sprite in this game therefore keeps its bank-relative address, and the
// bank-2 copy of the sprite region sits at exactly bank-0 address + $8000.
// **Not one sprite pointer value changes when the bank does.**
//
// Two things could NOT keep their offsets, because CPU code already occupies
// those addresses in bank 2 -- the screen matrix and the terrain charset. They
// move, and the entire cost of that is three constants consumed by
// publishFrame. See the layout below.
// ===========================================================================

// --- the CIA 2 port ---------------------------------------------------------
// Bits 0-1 select the bank, INVERTED: %11 is bank 0. Bits 2-7 are the serial
// bus, the RS-232 lines and the VIC's own /VA14-15 direction -- none of them
// ours, all of them live. A careless `lda #1 / sta $dd00` would drop the
// serial ATN and DATA lines on the floor, which is why every write here is a
// read-modify-write that touches two bits and preserves six.
.const CIA2_PRA      = $dd00
.const CIA2_DDRA     = $dd02
.const VIC_BANK_MASK = %00000011        // the two bits that are ours
.const VIC_BANK_KEEP = %11111100        // ...and the six that are not, which
                                        // every write below preserves
.const VIC_BANK_0    = %00000011        // $0000-$3fff  (inverted: 3 = bank 0)
.const VIC_BANK_2    = %00000001        // $8000-$bfff  (inverted: 1 = bank 2)

// The two bank-select lines must be OUTPUTS or the VIC follows whatever the
// port floats to. The KERNAL sets this at reset and this game banks the KERNAL
// out, so it is asserted here rather than inherited: the bits are forced to
// output without disturbing the other six directions.
.const VIC_BANK_DDR  = %00000011

// ===========================================================================
// THE BANK 2 LAYOUT
// ===========================================================================
// Bank 2 is CPU $8000-$bfff. Three things already live in it and they STAY
// there, because the VIC never fetches from where they are:
//
//   $8000-$8116  the clipped-sprite renderer   (bank-relative $0000-$0116)
//   $8600-$8a9f  THE RASTER EXECUTOR           (bank-relative $0600-$0a9f)
//   $9000-$9fff  the character ROM's window -- the VIC sees ROM here in banks
//                0 and 2 alike, so RAM at these addresses can never be
//                fetched and is the ideal home for code. The boss phase
//                machine and the game-state code both live there.
//
// THE RASTER EXECUTOR IS DELIBERATELY NOT MOVED. It is the most
// timing-sensitive code in the project, its placement is justified by
// measurement, and relocating it would change which of its branches cross a
// page boundary. The bank-2 layout is chosen AROUND it instead: nothing the
// VIC fetches is placed at bank-relative $0600-$0a9f.
//
// What the VIC fetches in bank 2:
//
//   $8c00-$8fff  SCREEN MATRIX, sprite pointers at $8ff8-$8fff
//                bank-relative $0c00 -- moved, because bank-relative $0400
//                (bank 0's screen) is underneath the raster executor
//   $a000-$a7ff  player bitmaps, muzzle flash, token, fireball   (rel $2000)
//   $a800-$afff  TERRAIN CHARSET
//                bank-relative $2800 -- moved, because bank-relative $0800
//                (bank 0's charset) is underneath the raster executor and the
//                game-state code. It lands on the space bank 0 gives to screen
//                page B and the level enemy window, neither of which the boss
//                arena uses: the scroll is frozen and the arena is empty.
//   $b100-$b7ff  clip scratch, HUD bitmaps, the boss cells, the projectile
//                                                              (rel $3100)
//   $b800-$bfff  BLANK CHARSET, and the VIC's idle byte at $bfff
//                bank-relative $3800, exactly as in bank 0 -- so the aperture's
//                blank-charset $d018 value does not change at all
//
// EVERY SPRITE BLOCK ABOVE IS AT ITS BANK-0 ADDRESS + $8000, so every sprite
// pointer in the game is already right. Only the screen and the terrain
// charset moved, and only $d018 and the pointer-table destination notice.
// ===========================================================================
// --- how the dynamic parts are walked across --------------------------------
// A SLICE A FRAME, not a block a frame. The screen matrix crosses once during
// the clearing phase and the HUD keeps crossing for as long as bank 2 is up;
// both go VB_SLICE bytes at a time so neither can put a spike in a frame the
// schedule builder is also trying to finish.
.const VB_SLICE         = 128
.const VB_SCREEN_SLICES = $400 / VB_SLICE
.const VB_HUD_SLICES    = (HUD_BLOCKS * 64) / VB_SLICE
.if (VB_HUD_SLICES * VB_SLICE != HUD_BLOCKS * 64) {
    .error "the HUD bitmap block is not a whole number of mirror slices"
}

// vicMirrorHud pins the heat gauge to a whole-slice copy every frame, which is
// only correct while the gauge is exactly slice 0 of the HUD block: blocks 0
// and 1, bytes 0..VB_SLICE-1. Reorder the HUD and this fails the build rather
// than silently going back to publishing the bar every seventh frame.
.if (HUD_HEAT_L != HUD_SPRITES || HUD_HEAT_R - HUD_HEAT_L != 64 || VB_SLICE != 128) {
    .error "the heat gauge is no longer exactly slice 0 -- revisit vicMirrorHud's pin"
}

// --- the assertions that make the layout a fact rather than a comment -------
.if ((VB2_SCREEN & $3ff) != 0)   { .error "the bank 2 screen matrix must be 1 KB aligned" }
.if ((VB2_CHARSET & $7ff) != 0)  { .error "the bank 2 terrain charset must be 2 KB aligned" }
.if ((VB2_BLANK & $7ff) != 0)    { .error "the bank 2 blank charset must be 2 KB aligned" }
.if ((VB2_BLANK + $800) != $c000) {
    .error "the blank charset must end at $bfff: that byte is the VIC's idle fetch"
}
// The character ROM shadow. In banks 0 and 2 the VIC reads ROM at bank-relative
// $1000-$1fff whatever the RAM there holds, so nothing fetchable may live in it.
.if ((VB2_SCREEN - VB2_BASE) >= $1000 && (VB2_SCREEN - VB2_BASE) < $2000) {
    .error "the bank 2 screen matrix is inside the character ROM shadow"
}
.if ((VB2_CHARSET - VB2_BASE) >= $1000 && (VB2_CHARSET - VB2_BASE) < $2000) {
    .error "the bank 2 terrain charset is inside the character ROM shadow"
}
// ...AND IT MUST NOT COLLIDE WITH THE CODE THAT STAYS PUT. Checked against the
// executor's REAL end label rather than against a round number, so the day it
// grows past $8c00 this is a build error and not a corrupted arena.
.if (VB2_SCREEN < rasterExecutorEnd) {
    .error "the bank 2 screen matrix overlaps the raster executor"
}
.if (VB2_SCREEN + $400 > $9000) {
    .error "the bank 2 screen matrix runs into the character ROM shadow at $9000"
}

// The mirror is what keeps every sprite pointer valid, so its offset is
// checked rather than trusted.
.if (VB2_SPRITES - VB2_BASE != $2000) {
    .error "the bank 2 sprite mirror is not at its bank 0 offset: pointers would move"
}

// ===========================================================================
// State. MAIN THREAD ONLY.
// ===========================================================================
* = $c60a "vic bank state"

// WHICH BANK IS SELECTED, as a flag rather than as a register read. $dd00 is
// readable, but a flag says what the GAME intends and a register says what the
// hardware happens to hold; publishFrame needs the first. Zero is bank 0, which
// is what a cold start leaves it as.
vicBank2:     .byte 0

// The HUD mirror cursor: which 128-byte slice of the HUD bitmaps is copied on
// this frame. See vicMirrorTick.
vicMirrorAt:  .byte 0

// The screen mirror's own cursor, and the page it is reading from. Separate
// from the HUD's because the screen crosses ONCE and the HUD crosses for ever.
vicScreenAt:   .byte 0
vicScreenPage: .byte 0

// EVERYTHING BANK 2 NEEDS HAS CROSSED: the frozen screen matrix once, and the
// HUD block at least once in full. Armed low by vicMirrorScreen and raised by
// the wrap at the end of a complete HUD pass, so it means "a whole picture, not
// most of one". src/boss.asm holds the bank switch until it is set.
vicMirrorDone: .byte 0

// The displayed frame the live mirror last copied a slice on. The main loop's
// idle spin runs thousands of times a frame and the mirror must run ONCE, so
// the frame number is the gate rather than a countdown.
vicMirrorFrame: .byte 0

// Live slices actually copied while bank 2 was up. Saturating.
//
// THE INSTRUMENT IS "IS THE FEED ALIVE", not "was it ever deferred". The first
// draft counted refusals, which the idle spin produces in their hundreds per
// frame whenever gameFrame happens to end below raster 56 -- it saturated
// before the boss had finished arriving and said nothing about anything. This
// advances once per displayed frame in bank 2 and not at all in bank 0, which
// is the property the regression test can hold on to.
vicMirrorRuns: .byte 0

// --- the block copy's working set ------------------------------------------
vbPages:      .byte 0
vbClipHi:     .byte 0
vbTmp:        .byte 0

// --- diagnostics, saturating -----------------------------------------------
vicSwitches:  .byte 0                   // bank selections performed

vicBankStateEnd:
.if (vicBankStateEnd > $c620) {
    .error "the vic bank state has grown past its ceiling"
}

// ===========================================================================
// Code. MAIN THREAD ONLY. In the free run between the turret tables and the
// turret state.
// ===========================================================================
* = $6980 "vic bank"

// ---------------------------------------------------------------------------
// vicBankInit — assert the bank-select lines and choose bank 0 explicitly.
// Cold start only, before any display.
//
// THE POINT OF THIS ROUTINE IS THAT IT EXISTS. Bank 0 used to be chosen by not
// choosing: the game inherited whatever the reset left behind. One line here
// turns that into a decision, and it is also the line that makes the return
// path real -- a future level init calls vicSelectBank0 and gets a defined
// machine rather than a lucky one.
// ---------------------------------------------------------------------------
vicBankInit:
    lda CIA2_DDRA
    ora #VIC_BANK_DDR                   // the two select lines are OUTPUTS.
    sta CIA2_DDRA                       // Only these two bits are forced; the
                                        // other six directions are the serial
                                        // bus's and stay as they were.
    lda #0
    sta vicBank2
    sta vicMirrorAt
    sta vicSwitches
    sta vicScreenPage
    sta vicMirrorDone
    sta vicMirrorFrame
    sta vicMirrorRuns
    lda #VB_SCREEN_SLICES               // no screen mirror is pending: the
    sta vicScreenAt                     // clearing phase arms it
    // falls through: a cold start is in bank 0, said out loud

// ---------------------------------------------------------------------------
// vicSelectBank0 — point the VIC at $0000-$3fff, NOW. THE RETURN PATH.
// Entry/exit: A clobbered; X and Y preserved.
//
// This one does write $dd00, and it is the right thing for the seams that call
// it. Both of them -- gsBeginNonGame and gsStartGame -- run while gsNonGame is
// set, so the gameplay executor is not adopting frame records at all and there
// is nothing to synchronise with; the display they are establishing is the
// plain text screen, which gsAttractIrq re-stamps every frame.
//
// It sets the flag as well, so the first frame record published after it --
// scrollInit's frame 0, on a restart -- already carries bank 0. That ordering
// is what stops ordinary gameplay inheriting the boss's presentation.
// ---------------------------------------------------------------------------
vicSelectBank0:
    lda #0
    jsr vicClipRebase                   // clip writes go back to bank 0
    lda CIA2_PRA
    and #VIC_BANK_KEEP                  // clear OUR two bits, keep the six
    ora #VIC_BANK_0                     // that belong to the serial bus
    sta CIA2_PRA
    lda #0
    sta vicBank2
    jmp vicCountSwitch

// ---------------------------------------------------------------------------
// vicSelectBank2 — ASK for bank 2. The VIC changes at the next frame IRQ.
// Entry/exit: A clobbered; X and Y preserved.
//
// IT DOES NOT WRITE $dd00, AND THAT IS THE v1.1 FIX. A bank and the $d018 that
// interprets it are one presentation decision; v1.0 made half of it here, from
// the main thread at an arbitrary raster line, and the other half at raster 250
// where the frame record is adopted. In between, the VIC fetched bank 2 through
// bank 0's VM and CB fields -- the screen matrix landed on the raster
// executor's own code -- for the rest of a visible frame. That was the flicker.
//
// So this sets the INTENT. publishFrame folds it into the next frame record
// (doing the read-modify-write that preserves CIA 2's other six bits) and
// exFrame commits the bank and the $d018 together in the lower border. The clip
// rebase happens here, immediately, because the scratch it redirects is filled
// for the schedule that will be ADOPTED on the same frame IRQ.
//
// ONLY FOR GAMEPLAY. A non-game state has no frame record and no exFrame -- the
// IRQ is gsAttractIrq -- so those seams use vicSelectBank0, which writes the
// register itself.
// ---------------------------------------------------------------------------
vicSelectBank2:
    lda #>VB2_BASE
    jsr vicClipRebase                   // clip writes follow the VIC
    lda #1
    sta vicBank2                        // ...and the COMMIT is the frame IRQ's.
                                        // See the note above: $dd00 is not
                                        // written here at all.
    // falls through

vicCountSwitch:
    lda vicSwitches
    cmp #$ff
    beq !done+
    inc vicSwitches
!done:
    rts

// ---------------------------------------------------------------------------
// vicMirrorStatic — put bank 2's unchanging VIC-visible assets in place.
// Cold start, once, while the screen is still off.
//
// TWO BLOCK COPIES AND NOTHING ELSE. The sprite region and the blank charset
// are a straight mirror at +$8000, which is what keeps every sprite pointer
// valid; the terrain charset then lands on top of the part of that mirror the
// boss arena does not use. Doing it at boot rather than at the transition costs
// nothing anybody can see and keeps the transition down to a single kilobyte.
//
// It must run AFTER clearCharset, which writes the blank charset this copies.
// ---------------------------------------------------------------------------
vicMirrorStatic:
    // $2000-$3fff -> $a000-$bfff. Sprites, the clip scratch pages, the HUD,
    // the boss cells and the blank charset, all at bank 0's own offsets.
    lda #32                             // pages
    ldx #$20
    ldy #>VB2_SPRITES
    jsr vicCopyPages

    // $0800-$0fff -> $a800-$afff. The terrain charset, over the mirror of
    // screen page B and the head of the level enemy window -- neither of which
    // the frozen, empty arena fetches.
    lda #8
    ldx #$08
    ldy #>VB2_CHARSET
    jmp vicCopyPages

// ---------------------------------------------------------------------------
// vicMirrorScreen — copy the page that is on screen RIGHT NOW into bank 2.
// Clobbers A, X, Y.
//
// The arena is frozen before this runs: scrollTick has returned at its first
// instruction since the final coarse step, so the matrix this copies is the
// last complete authored screenful and nothing will write it again. That is
// why one copy is enough and why the terrain survives the switch unchanged --
// bank 2 is not rebuilding the view, it is holding a photograph of it.
// ---------------------------------------------------------------------------
vicMirrorScreen:
    lda dispPage
    bne !pageB+
    lda #>SCREEN_A
    jmp !set+
!pageB:
    lda #>SCREEN_B
!set:
    sta vicScreenPage
    lda #0
    sta vicScreenAt
    sta vicMirrorAt                     // THE HUD PASS STARTS HERE TOO. The
                                        // cursor is free-running, so arming the
                                        // screen without arming this would
                                        // declare the block complete part of a
                                        // pass early -- see vicMirrorDone.
    sta vicMirrorDone
    rts

// ---------------------------------------------------------------------------
// vicMirrorFinish — make sure the whole picture has finished crossing.
// Clobbers A, X, Y.
//
// THE SAFETY NET, AND IT SHOULD NEVER DO ANYTHING. src/boss.asm holds the bank
// switch until vicMirrorDone is set, so by the time this runs both the screen
// matrix and the HUD block have already crossed a slice a frame. It stays
// because a spawn path that reached bank 2 some other way must not be able to
// select it over a half-copied picture.
//
// BOUNDED BY CONSTRUCTION: every vicMirrorTick advances one of the two cursors,
// and the HUD cursor raises vicMirrorDone when it wraps, so this cannot run
// more than VB_SCREEN_SLICES + VB_HUD_SLICES times.
//
// It used to wait on the SCREEN cursor alone, which is the half of the picture
// that crosses once -- so a clearing phase too short to walk the HUD across
// left the arena displaying the HUD the machine booted with.
// ---------------------------------------------------------------------------
vicMirrorFinish:
    lda vicMirrorDone
    bne !done+
    jsr vicMirrorTick
    jmp vicMirrorFinish
!done:
    rts

// ---------------------------------------------------------------------------
// vicMirrorLive — keep bank 2's HUD current for AS LONG AS BANK 2 IS UP.
// MAIN THREAD, from the main loop's idle spin. Clobbers A and X.
//
// THE MIRROR IS A FEED, NOT A PHOTOGRAPH, and this is the routine that makes
// that true. vicMirrorTick used to be called from bossClearTick and nowhere
// else, so the block stopped crossing at the instant the bank changed and the
// whole boss fight displayed whatever the HUD had held one frame before it.
// The score, the heat bar and the P economy all kept working perfectly in bank
// 0 and none of it could be seen.
//
// FIVE CYCLES AND AN RTS IN BANK 0, which is all of ordinary play: the VIC is
// reading the originals then, and there is nothing to mirror.
//
// TWO GATES, AND BOTH ARE LOAD-BEARING:
//
//   the frame gate   the idle spin runs thousands of times a frame. One slice
//                    per DISPLAYED frame is the cadence src/vicbank.asm's own
//                    reasoning chose -- a few hundred cycles, and the whole
//                    block current again within VB_HUD_SLICES frames.
//
//   the raster gate  THESE ARE THE BYTES THE VIC FETCHES ON RASTERS 16..37.
//                    src/hud.asm refuses to write the bank 0 originals outside
//                    56..200 for exactly that reason, and the bank 2 copies are
//                    the same bytes seen through a different bank. Copying them
//                    across the fetch would tear a digit. The spin gets many
//                    passes per frame, so a refusal costs microseconds.
// ---------------------------------------------------------------------------
vicMirrorLive:
    lda vicBank2
    beq !idle+                          // bank 0: the VIC reads the originals

    lda frameCounter
    cmp vicMirrorFrame
    beq !idle+                          // this frame's slice is already across

    ldx $d012
    cpx #HUD_SAFE_LO
    bcc !idle+                          // REFUSED, not delayed: the spin comes
    cpx #HUD_SAFE_HI                    // back around in microseconds and the
    bcs !idle+                          // frame gate above is still open

    sta vicMirrorFrame                  // A still holds frameCounter
    ldx vicMirrorRuns
    cpx #$ff
    beq vicMirrorHud
    inc vicMirrorRuns
    jmp vicMirrorHud
!idle:
    rts

// ---------------------------------------------------------------------------
// vicMirrorTick — keep bank 2's HUD bitmaps in step, one slice a frame.
// Clobbers A, X, Y.
//
// THE HUD IS THE ONE VIC-VISIBLE THING STILL BEING WRITTEN during the arena.
// The screen matrix is frozen, the charsets are static, the sprite art is
// static, the boss cells never animate and the health bar is colour RAM, which
// is not in any bank. src/hud.asm keeps rendering heat and score into its
// bank-0 bitmaps exactly as it always has, and this walks that block across
// into bank 2 a slice at a time.
//
// A SLICE, NOT THE BLOCK. Copying all 896 bytes every frame would cost about
// 9,000 cycles for a bar that moves a pixel; copying VB_SLICE bytes costs a few
// hundred and the whole block is current again within seven frames. The HUD is
// a gauge, not an instrument -- a seventh of a second of lag on a heat bar is
// not visible, and nothing else in the block changes during a boss fight at
// all.
//
// It runs from LP_CLEARING, a phase BEFORE the switch, so by the time bank 2 is
// selected the mirror is already current and the HUD does not flicker back to
// whatever it held at boot.
// ---------------------------------------------------------------------------
vicMirrorTick:
    // ---- the frozen screen goes first, once ------------------------------
    // It is a photograph, not a feed: once all VB_SCREEN_SLICES have crossed
    // there is nothing left to track, because scrollTick has not written the
    // matrix since the final coarse step and never will again.
    lda vicScreenAt
    cmp #VB_SCREEN_SLICES
    bcs vicMirrorHud

    // Two VB_SLICE slices to a page, so the slice index splits into a page
    // offset and a half. The source page walks from whichever bank 0 page is
    // frozen on screen; the destination walks from the bank 2 matrix, which is
    // at a DIFFERENT bank-relative address -- so this is not a +$8000 mirror
    // and the two pages are computed separately.
    lda vicScreenAt
    lsr                                 // page offset 0..3
    sta vbTmp
    clc
    adc vicScreenPage
    sta vbCopySrc + 2
    lda vbTmp
    clc
    adc #>VB2_SCREEN
    sta vbCopyDst + 2

    lda vicScreenAt
    and #1                              // which half of the page
    beq !lowHalf+
    lda #VB_SLICE
    jmp !off+
!lowHalf:
    lda #0
!off:
    sta vbCopySrc + 1
    sta vbCopyDst + 1

    inc vicScreenAt
    jmp vicMirrorSlice

vicMirrorHud:
    // ---- THE HEAT GAUGE CROSSES EVERY FRAME, AHEAD OF THE ROTATION ------
    //
    // THE ROUND ROBIN IS A PUBLICATION RATE, AND FOR ONE BLOCK IT WAS TOO SLOW.
    // The reasoning below this routine says a seventh of a second of lag on a
    // heat bar is not visible, and that is true -- but LAG is not the thing the
    // player sees. QUANTISATION is. The bar moves one pixel every ~3 frames
    // while firing and every ~2 while cooling, so publishing it every 7 frames
    // does not show a smooth bar a seventh of a second late: it shows the bar
    // standing still for six frames and then jumping the 2 or 3 pixels that
    // accumulated. MEASURED over 23 boss frames with fire held: the bank 0
    // bitmap hud.asm draws changed 8 times, the bank 2 copy the VIC actually
    // fetches changed 3 -- one of those a 3-pixel step. The heat STATE was
    // identical in LP_LEVEL and LP_BOSS throughout (+2 on 39 frames of 39), so
    // nothing was wrong with the heat system; the gauge was simply being
    // published at a seventh of the rate at which it changes.
    //
    // It is the only block in the HUD that animates continuously. The score,
    // the lives and the P economy change a few times a fight, and for those the
    // original reasoning holds exactly -- they keep taking turns.
    //
    // HUD_HEAT_L and HUD_HEAT_R are blocks 0 and 1, which is bytes 0..127 of
    // the block: the heat gauge IS slice 0, whole and alone, so pinning it is
    // one more VB_SLICE copy and no new cursor. The guard at the top of this
    // file fails the build if that stops being true.
    //
    // COST: ~1,800 cycles per displayed frame, paid from the idle spin (see
    // vicMirrorLive) and only while bank 2 is up. In bank 0 the VIC reads the
    // originals and this routine is never reached.
    lda #<HUD_HEAT_L
    sta vbCopySrc + 1
    lda #>HUD_HEAT_L
    sta vbCopySrc + 2
    lda #<(HUD_HEAT_L + VB2_BASE)
    sta vbCopyDst + 1
    lda #>(HUD_HEAT_L + VB2_BASE)
    sta vbCopyDst + 2
    jsr vicMirrorSlice

    // ---- ...and the block as a whole still takes its turn ----------------
    // The rotation is untouched: it still walks 0..VB_HUD_SLICES-1 and still
    // raises vicMirrorDone on the wrap, so the pre-warm handshake in
    // src/boss.asm means exactly what it did. Slice 0 comes round once every
    // seven frames and is copied a second time that frame, which is 1,800
    // wasted cycles a seventh of the time and not worth a cursor to dodge.
    //
    // THE SLICE'S BYTE OFFSET IS n * 128, AND IT IS SIXTEEN BITS.
    //
    // This read `asl` for the low byte, which is n * 2 -- the right answer only
    // for n = 0. Every other slice copied from a couple of bytes past the page
    // it belonged to and stopped short of the next one, so the block was walked
    // with three 130-byte holes in it that no cursor ever revisited. MEASURED:
    // 506 of 896 bytes crossed per pass, and the two holes that mattered sat
    // exactly over the score sprites and P charge blocks 0 and 1. That is why
    // the boss arena's score read 000000 -- the boot image, never once
    // overwritten -- rather than freezing at the score the player had.
    //
    // n * 128 is n shifted left seven, which is a shift RIGHT by one with the
    // bytes swapped: the high byte is n >> 1 and the whole low byte is the bit
    // that fell out of it.
    lda vicMirrorAt
    lsr                                 // n >> 1 IS the high byte...
    tay
    lda #0
    ror                                 // ...and carry -> bit 7 is the low one:
    tax                                 // $00 for an even slice, $80 for an odd

    txa
    clc
    adc #<HUD_SPRITES
    sta vbCopySrc + 1
    tya
    adc #>HUD_SPRITES
    sta vbCopySrc + 2

    txa
    clc
    adc #<(HUD_SPRITES + VB2_BASE)
    sta vbCopyDst + 1
    tya
    adc #>(HUD_SPRITES + VB2_BASE)
    sta vbCopyDst + 2

    inc vicMirrorAt
    lda vicMirrorAt
    cmp #VB_HUD_SLICES
    bcc vicMirrorSlice
    lda #0
    sta vicMirrorAt                     // ...and a WHOLE pass has now crossed,
    lda #1                              // which is the thing the bank switch
    sta vicMirrorDone                   // waits on. See src/boss.asm.

vicMirrorSlice:
    ldy #VB_SLICE - 1
!byte:
vbCopySrc:
    lda $ffff,y
vbCopyDst:
    sta $ffff,y
    dey
    bpl !byte-
    rts

// ---------------------------------------------------------------------------
// vicClipRebase — point the clipped-sprite scratch writes at the live bank.
// Entry: A = the high byte to add to every block address ($00 or $80).
// Clobbers A, X, Y.
//
// THE ONE PLACE A CPU WRITE HAD TO FOLLOW THE VIC. Everything else the arena
// fetches is either static (copied once) or the HUD (mirrored a slice a frame),
// but clipped sprites are rebuilt into scratch blocks EVERY FRAME and have to
// be right on the frame they are built. src/clip.asm writes them through
// clipBlkHi, a table of high bytes, so rebasing the whole pool is twelve adds
// done once per bank change rather than a bank test per sprite.
//
// clipBlkPtr -- the SPRITE POINTER for each block -- is deliberately not
// touched: it is bank-relative, the blocks keep their bank-0 offsets, and the
// number the schedule carries is already correct in both banks.
//
// It is an ABSOLUTE rebase, not a toggle: the table is rebuilt from the
// assembler's own list every time, so calling it twice cannot drift.
// ---------------------------------------------------------------------------
vicClipRebase:
    sta vbClipHi
    ldx #0
!blk:
    lda vicClipBaseHi,x
    clc
    adc vbClipHi
    sta clipBlkHi,x
    inx
    cpx #2 * CLIP_POOL_SLOTS
    bne !blk-
    rts

// The assembler's own copy of the bank-0 high bytes, so the rebase above has a
// truth to add to rather than a previous answer to adjust.
vicClipBaseHi:
.for (var i = 0; i < clipBlocks.size(); i++) { .byte >clipBlocks.get(i) }

// ---------------------------------------------------------------------------
// vicCopyPages — A = whole pages, X = source page, Y = destination page.
// Clobbers A, X, Y.
//
// Self-modified rather than indirect because there is no zero page to spare
// here and this runs a handful of times in a level, not in a loop anybody
// measures.
// ---------------------------------------------------------------------------
vicCopyPages:
    sta vbPages
    stx vbSrc + 2
    sty vbDst + 2
!page:
    ldy #0
!byte:
vbSrc:
    lda $ff00,y
vbDst:
    sta $ff00,y
    iny
    bne !byte-
    inc vbSrc + 2
    inc vbDst + 2
    dec vbPages
    bne !page-
    rts

.if (* > $6c00) { .error "the vic bank code has run into the terrain state at $6c00" }
