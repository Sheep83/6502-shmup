// ===========================================================================
// scroll.asm — P1 deterministic vertical scroller
// ===========================================================================
// The smallest scroller that genuinely exercises C64 vertical scrolling:
// every fine-scroll phase, a coarse row step, and a real screen-page flip.
// It is a diagnostic surface, not artwork.
//
// SHAPE
//   main thread          decides the NEXT frame and writes a frame record
//       |                (fine scroll, $d018, pointer-table destination, page)
//       v
//   framePending = 1     one byte, exactly like schedPending
//       v
//   frame IRQ            adopts the record ONCE, in the lower border, and is
//                        the only thing that writes $d011/$d018/the pointer
//                        destination. See exFrame in renderer.asm.
//
// The executor never asks the scroller anything. Everything it needs for the
// whole displayed frame was latched at the frame boundary.
//
// GEOMETRY
// Page P displays world rows [worldRow .. worldRow+24]. The fine scroll counts
// DOWN 7..0, moving the playfield up one pixel per frame. On the 0 -> 7 wrap
// the content must jump up one whole row, so worldRow advances and we flip to
// the other page, which has been prepared with world rows [worldRow+1 .. +25].
// Coarse step and page flip are therefore the SAME event, once every 8 frames.
//
// WHY THE BACK PAGE IS REGENERATED, NOT COPIED
// Every row is written from its own world row number, so a stale row, a
// duplicated row or a one-row jump cannot survive: the row prints its own
// identity. A copy-and-shift would reproduce whatever was already wrong.
// ===========================================================================

.const ROWS_PER_TICK = 5                // 25 rows over the 8 frames between
                                        // coarse steps, with margin. Spread on
                                        // purpose: a single 25-row burst is
                                        // ~12,000 cycles of the 19,656 in a
                                        // frame, which leaves no room for
                                        // anything else the main thread grows.
                                        //
                                        // STILL FIVE. P3 flagged this as spare
                                        // headroom -- 25/8 = 3.125 rows a frame,
                                        // so four would do -- and said not to
                                        // spend it without evidence.
                                        //
                                        // P4 thought it had evidence: adding the
                                        // sorter produced publication skips. Four
                                        // rows was applied and the scroller
                                        // requalified. Then the evidence fell
                                        // apart twice over. Most of the skips
                                        // were the TEST HARNESS hijacking the PC
                                        // mid-frame to select a fixture; on a
                                        // fresh machine left to run, the
                                        // 12-sprite crossing fixture does 20,000+
                                        // frames clean at FIVE rows. And the one
                                        // fixture that really did fault -- 26
                                        // sprites re-sorted and rebuilt every
                                        // frame -- faulted at four rows too
                                        // (62 skips in 19,601 frames), because
                                        // its problem is main-thread cost, not
                                        // back-page regeneration.
                                        //
                                        // So the lever was reverted. The headroom
                                        // is real and still available; P4 simply
                                        // has no measurement that needs it, and a
                                        // qualified scroller is not worth
                                        // changing on evidence that dissolved.

* = $1a00 "scroller"

// --- scroll state. MAIN THREAD ONLY. The executor never reads any of this. --
scrollFine:   .byte 0                   // current YSCROLL, counts 7..0
worldRowLo:   .byte 0                   // world row shown at screen row 0
worldRowHi:   .byte 0
dispPage:     .byte 0                   // 0 = A, 1 = B. The page to display NEXT.
regenPage:    .byte 0                   // page currently being rebuilt
regenPageHi:  .byte 0                   // its high byte ($04 or $28)
regenRow:     .byte 0                   // next screen row to rebuild (25 = idle)
regenWorldLo: .byte 0                   // world row of regen screen row 0
rrWorld:      .byte 0                   // scratch: world row of the row in hand
hudPageHi:    .byte 0                   // high byte of the page the HUD writes to

// The world row each PAGE's matrix row 0 was regenerated with, indexed by page.
// This is the off-screen successor to the on-screen page letter: from it a test
// can predict the world row of every row of whichever page is displayed, and
// check all 25 rather than checking that one character agrees with itself.
// Written wherever regenWorldLo is, so the two cannot drift.
pageWorldLo:  .byte 0, 0

// --- diagnostics read by tests ---------------------------------------------
coarseCount:  .byte 0, 0                // coarse row steps (16-bit, lo/hi)
finePhase:    .fill 16, 0               // frames spent at each YSCROLL value,
                                        // 16-bit per phase (lo,hi). An 8-bit
                                        // counter wraps after 256 frames per
                                        // phase, which is ~34 seconds -- far
                                        // shorter than a stress run, and it
                                        // silently under-reports coverage.
scrollLate:   .byte 0                   // coarse step arrived with the back
                                        // page unfinished: a real fault
publishSkip:  .byte 0                   // publication found the previous one
                                        // still unadopted: a real fault

// --- P2 pinned fine phase: a DIAGNOSTIC MODE, not a second scroller --------
// For automated qualification only. With pinFine non-zero the fine scroll is
// HELD at pinFineValue instead of counting down, so the same sprite geometry
// can be measured against each of the eight badline alignments in turn.
//
// Holding the phase necessarily suspends the coarse step and the page flip:
// they ARE the fine-scroll wrap (see GEOMETRY above), so there is nothing left
// to trigger them. That is the whole reason natural scrolling has to be
// restored and the geometry re-proven across real coarse steps and page flips
// before any phase result is believed.
//
// Nothing else changes. publishFrame still builds and hands over the frame
// record exactly as it always does, so $d011 carries the pinned phase through
// the ordinary published channel and the executor cannot tell the difference.
// A test therefore verifies the phase from $d011 on the running machine, never
// from this variable.
pinFine:      .byte 0                   // 0 = natural scrolling, 1 = held
pinFineValue: .byte 0                   // the YSCROLL to hold, 0..7

// ===========================================================================
// scrollInit — both pages built, page A displayed, frame 0 published.
// ===========================================================================
scrollInit:
    lda #7
    sta scrollFine
    lda #0
    sta worldRowLo
    sta worldRowHi
    sta dispPage                        // page A displays world rows 0..24

    lda #0
    sta regenPage
    lda #>SCREEN_A
    sta regenPageHi
    lda #0
    sta regenWorldLo
    sta pageWorldLo                     // page A: world rows 0..24
    jsr regenAll

    lda #1
    sta regenPage                       // page B holds world rows 1..25, ready
    lda #>SCREEN_B                      // for the first coarse step
    sta regenPageHi
    lda #1
    sta regenWorldLo
    sta pageWorldLo + 1
    jsr regenAll

    lda #SCREEN_ROWS
    sta regenRow                        // idle until the first coarse step
    jsr publishFrame
    rts

regenAll:
    lda #0
    sta regenRow
!loop:
    jsr renderRow
    inc regenRow
    lda regenRow
    cmp #SCREEN_ROWS
    bcc !loop-
    rts

// ===========================================================================
// scrollTick — one call per displayed frame. Advances the scroll and publishes
// the frame record the NEXT frame IRQ will adopt.
// ===========================================================================
scrollTick:
    lda pinFine                         // P2 diagnostic mode: hold the phase
    beq !natural+
    lda pinFineValue
    and #7
    sta scrollFine
    jmp scrollPublish
!natural:
    dec scrollFine
    bpl scrollPublish

// ---- coarse step: advance the world, flip the page ------------------------
    lda #7
    sta scrollFine

    lda regenRow                        // the page we are about to display was
    cmp #SCREEN_ROWS                    // not finished. Never expected; counted
    bcs !ready+                         // rather than hidden. Saturates.
    lda scrollLate
    cmp #$ff
    beq !ready+
    inc scrollLate
!ready:
    inc worldRowLo
    bne !nohi+
    inc worldRowHi
!nohi:
    lda dispPage
    eor #1
    sta dispPage                        // flip to the page prepared last time
    eor #1
    sta regenPage                       // the page we just left is now the back

    lda regenPage
    bne !pb+
    lda #>SCREEN_A
    jmp !ps+
!pb:
    lda #>SCREEN_B
!ps:
    sta regenPageHi

    // The page just flipped TO already holds world rows worldRowLo..+24: it was
    // regenerated with exactly that value during the last cycle. Stamp it now,
    // while that is a statement about content rather than intent.
    //
    // NOT the back page, which was the first attempt. pageWorldLo[back] would
    // then be the row the page is ABOUT to be regenerated with, and for the one
    // frame between the software flip and the IRQ adopting it at raster 250 the
    // still-displayed page carried a stamp two coarse steps ahead of its own
    // content. The invariant that matters is the narrow one: pageWorldLo[p] is
    // correct whenever p is the page being displayed.
    ldx dispPage
    lda worldRowLo
    sta pageWorldLo,x

    lda worldRowLo                      // the back page gets the row after the
    clc                                 // one now on screen
    adc #1
    sta regenWorldLo
    lda #0
    sta regenRow                        // start rebuilding it next frame

    inc coarseCount
    bne scrollPublish
    inc coarseCount+1

scrollPublish:
    lda scrollFine
    asl                                 // two bytes per phase
    tax
    inc finePhase,x
    bne !counted+
    inc finePhase + 1,x
!counted:
    // fall through

// ===========================================================================
// publishFrame — write the NEXT frame record and hand it over with one byte.
// Double buffered for the same reason the schedule is: the frame IRQ must
// never see a half-updated set where $d018 says one page and the pointer
// destination says the other.
// ===========================================================================
publishFrame:
    lda framePending
    beq !free+
    lda publishSkip                     // previous record not adopted yet
    cmp #$ff
    beq !skipped+
    inc publishSkip
!skipped:
    rts
!free:
    ldx frameNext
    lda #D011_BASE
    ora scrollFine
    sta frameD011,x
    lda dispPage
    sta framePage,x
    bne !pageB+
    lda #D018_A
    sta frameD018,x
    lda #D018_A_BLANK
    sta frameD018B,x
    lda #>PTR_A
    sta framePtrHi,x
    jmp !armed+
!pageB:
    lda #D018_B
    sta frameD018,x
    lda #D018_B_BLANK
    sta frameD018B,x
    lda #>PTR_B
    sta framePtrHi,x
!armed:
    lda #1
    sta framePending                    // the handover. One byte, atomic.
    rts

// ===========================================================================
// regenTick — rebuild a few rows of the back page, once per frame.
// ===========================================================================
regenTick:
    lda regenRow
    cmp #SCREEN_ROWS
    bcs !done+
    ldy #ROWS_PER_TICK
!loop:
    tya
    pha
    jsr renderRow
    pla
    tay
    inc regenRow
    lda regenRow
    cmp #SCREEN_ROWS
    bcs !done+
    dey
    bne !loop-
!done:
    rts

// ===========================================================================
// renderRow — rebuild screen row `regenRow` of the back page.
// HUD rows are drawn by the HUD code so the page is COMPLETE when it flips;
// otherwise the newly displayed page would show background where the status
// lines belong for one frame out of every eight.
// ===========================================================================
renderRow:
    ldx regenRow
    lda rowLo,x
    sta scrPtr
    lda rowHi,x
    clc
    adc regenPageHi
    sta scrPtr + 1

    // EVERY ROW IS TERRAIN NOW.
    //
    // Rows 0 and 24 used to be forced blank by renderGuardRow to hide the
    // coarse seam, and rows 1, 2 and 20-23 used to be reserved for the
    // diagnostic HUD. Both reservations are gone: the aperture is clipped by
    // the blank character set at fixed rasters 55 and 248 (see BLANK_CHARSET
    // in main.asm), so the slack rows carry ordinary world content and are
    // simply revealed one pixel at a time. There is deliberately no second
    // masking mechanism left anywhere -- if a row looks blank on screen it is
    // because the charset clipped it, and for no other reason.
    jmp renderBackgroundRow

// ---------------------------------------------------------------------------
// renderBackgroundRow — the diagnostic pattern for one world row.
//
//   cols 0-1   world row number, low byte, in hex   <- row identity
//   cols 2-4   space
//
// COLUMN 3 USED TO BE THE PAGE LETTER, 'A' or 'B', and it is gone from the
// screen. Every row carries it, so at every page flip all 23 visible rows
// changed one character at once -- a whole column blinking 6.25 times a second,
// in the middle of the picture a human is being asked to judge for smoothness.
// The A/B forensic measured it as 88 of the 96 lines that differ across a
// flip: the largest single visual event on screen, and pure scaffolding.
//
// The observability is not lost, it is moved off the display: pageWorldLo
// records the world row each page's row 0 was regenerated with, which is a
// STRONGER statement than the letter ever was. The letter said only "these
// rows came from the same pass"; pageWorldLo lets a test predict the exact
// world row of every row of the displayed page and check all 25.
//   cols 5-39  solid bar every 4th world row, blank otherwise
//   col  6+(W and 31)   a '*' marker, so each row is distinguishable even
//                       inside a run of blank rows
//
// A duplicated row, a stale row, a skipped row or a torn page flip all show up
// immediately: the hex column must count by one, every row on screen must
// carry the SAME page letter, and the marker must walk a clean diagonal.
// ---------------------------------------------------------------------------
renderBackgroundRow:
    txa                                 // X still = regenRow
    clc
    adc regenWorldLo
    sta rrWorld

    and #3
    bne !blank+
    lda #$a0                            // reverse space: a solid bar
    jmp !fill+
!blank:
    lda #$20
!fill:
    ldy #39
!f:
    sta (scrPtr),y
    dey
    cpy #4
    bne !f-

    lda rrWorld                         // the walking marker
    and #31
    clc
    adc #6
    tay
    lda #42                             // '*'
    sta (scrPtr),y

    lda rrWorld                         // row identity in hex
    lsr
    lsr
    lsr
    lsr
    tax
    lda hexDigit,x
    ldy #0
    sta (scrPtr),y
    lda rrWorld
    and #$0f
    tax
    lda hexDigit,x
    ldy #1
    sta (scrPtr),y

    lda #$20
    ldy #2
    sta (scrPtr),y
    ldy #3                              // was the page letter; see pageWorldLo
    sta (scrPtr),y
    ldy #4
    sta (scrPtr),y
    rts

// --- the playfield aperture -------------------------------------------------
//
// There is no code here any more, and that is the point.
//
// The aperture used to be a CONTENT mask: renderGuardRow filled matrix rows 0
// and 24 with spaces. It did hide the coarse seam, and it was measured to do
// so -- but it moved the visible top edge to raster 56 + YSCROLL, so the edge
// climbed seven pixels over seven frames and then jumped back a whole
// character row when the world stepped. That 6.25 Hz pop is the artefact the
// MAXCAP A/B forensic isolated (reports/maxcap-top-sprite-band-glitch-ab.md):
// 88 of its 96 differing lines were the page letter below, and the remaining
// 7-8 were exactly this, at rasters 56..63.
//
// Clipping is now the VIC's own g-access, through a blank character set
// selected at fixed rasters 55 and 248. The boundary cannot move, because it
// is a raster and not a row.

// ---------------------------------------------------------------------------
// SEGMENT GROWTH GUARD.
//
// KickAssembler places explicit `* =` segments exactly where told and does not
// complain when one grows into the next -- it simply overwrites, silently, and
// the failure looks like corrupted code rather than a build error. The P5
// forensic measured only FIVE bytes of headroom between the scroller and the
// motion segment at $1c00, which is well inside the range a single added
// routine consumes. Stated and enforced rather than left to luck.
// ---------------------------------------------------------------------------
.if (* > $1c00) {
    .error "the scroller segment has grown into 'motion' at $1c00"
}

// ---------------------------------------------------------------------------
// Screen row byte offsets, so a row address is one add and never a multiply.
//
// MOVED OUT of the $1a00 scroller segment, which had five bytes of headroom
// left. These are read with absolute,X indexing, so where they live is
// immaterial; the code that needs the room is not.
// ---------------------------------------------------------------------------
* = $cf00 "screen row table"
rowLo: .fill SCREEN_ROWS, <(i * 40)
rowHi: .fill SCREEN_ROWS, >(i * 40)
