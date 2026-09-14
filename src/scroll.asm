// ===========================================================================
// scroll.asm — the vertical scroller: fine scroll, coarse step, page flip
// ===========================================================================
// MAIN THREAD ONLY. It decides what the next frame looks like and regenerates
// the back screen page; the raster executor writes the registers.
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
// GEOMETRY AND DIRECTION
//
// THE PLAYFIELD SCROLLS DOWNWARD. The player flies UP through the stage, the
// terrain moves DOWN past them, and new terrain enters at the TOP. Every piece
// of authored content -- wave trigger rows, turret rows, the editor's
// top-to-bottom row order -- is written against that direction.
//
// Page P displays stage rows [stageTopRow .. stageTopRow+24], one row per
// matrix row, top to bottom. The fine scroll counts UP 0..7, moving the
// playfield down one pixel per frame: matrix row r occupies rasters
// 48 + YSCROLL + 8r .. +7, so a larger YSCROLL is further down the screen.
//
// On the 7 -> 0 wrap the content must jump DOWN one whole row to stay
// continuous, so stageTopRow steps BACK by one and we flip to the other page,
// which has been prepared with stage rows [stageTopRow-1 .. +23]. Coarse step
// and page flip are therefore the SAME event, once every 8 frames.
//
//     fine   0 1 2 3 4 5 6 7 | 0 1 2 ...      content moves down 1px per step
//     top    T T T T T T T T | T-1 ...        one row back per wrap
//
// ---------------------------------------------------------------------------
// TWO COUNTERS, AND WHY
// ---------------------------------------------------------------------------
// stageTopRow   WHICH ROW OF THE MAP is at matrix row 0. It DECREASES, because
//               the map is authored top-to-bottom and play starts at its
//               bottom. Scroller-owned; the row renderer is its only consumer.
//
// worldProgress HOW FAR THROUGH THE STAGE we are, in coarse rows. It INCREASES
//               from zero, always. This is the one game systems read.
//
// They are two names for one event, maintained side by side at the coarse step,
// and the invariant between them is exact:
//
//     stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS
//
// Keeping both costs ten instructions once every eight frames and means no
// other subsystem has to encode "forward means subtract" -- a mistake that
// would otherwise be copied into waves, turrets, triggers and stage completion
// one at a time.
//
// WHY THE BACK PAGE IS REGENERATED, NOT COPIED
// Every row is written from its own world row number, so a stale row, a
// duplicated row or a one-row jump cannot survive: the row prints its own
// identity. A copy-and-shift would reproduce whatever was already wrong.
// ===========================================================================

// ---------------------------------------------------------------------------
// THE STAGE, DERIVED FROM THE LEVEL rather than restated here.
// src/level1/stage_config.asm authors STAGE_METATILE_ROWS and the metatiles are
// four character rows tall; the guard in src/terrain.asm fails the build if a
// future level disagrees with the scroller that walks it.
//
// PLAY STARTS AT THE BOTTOM OF THE MAP. The editor stores rows top-to-bottom in
// visual order and the authored BOTTOM is the beginning of play, so the first
// page shows the last SCREEN_ROWS rows with no wrap in it and stageTopRow then
// walks down to 0 over the whole stage.
.const STAGE_ROWS      = TERRAIN_STAGE_ROWS
.const STAGE_START_ROW = STAGE_ROWS - SCREEN_ROWS

.if (STAGE_ROWS < SCREEN_ROWS + 1) { .error "a stage must be taller than one screen" }
.if (STAGE_START_ROW < 0)          { .error "STAGE_START_ROW is negative" }


// Back-page regeneration is SPREAD, not burst: 25 rows in one go would be
// ~12,000 cycles of the 19,656 in a frame, leaving nothing for anything else
// the main thread does. Four rows a frame finishes 25 rows in seven of the
// eight frames between coarse steps -- one frame of margin -- at a peak of
// ~4,630 cycles. A row of real metatile decoding costs about 1,158 cycles, so
// raising this raises the PEAK, and the peak is what collides with a dense
// sprite frame. scrollLate is the counter that says whether the margin holds.
.const ROWS_PER_TICK = 4

// ---------------------------------------------------------------------------
// ONE FRAME IN EIGHT IS IDLE HERE, AND SOMETHING ELSE NOW RELIES ON IT.
//
// regenTick rebuilds the back page at ROWS_PER_TICK rows a frame and stops when
// regenRow reaches SCREEN_ROWS, so it finishes in ceil(25/4) = 7 of the 8
// frames between coarse steps and the eighth does nothing at all. The fine
// scroll counts UP and wraps 7 -> 0 at the coarse step, so that idle frame is
// the one on which scrollFine reads 7.
//
// src/turrets.asm derives the NEXT coarse step's page geometry on exactly that
// frame (TURRET_PREPARE_FINE), which keeps that work off the frame where this
// routine restarts the page. If ROWS_PER_TICK ever drops far enough that
// regeneration fills all eight frames, the quiet frame is gone and the turret
// preparation has nowhere to go -- a build error here rather than a silent
// performance regression there.
.if (floor((SCREEN_ROWS + ROWS_PER_TICK - 1) / ROWS_PER_TICK) >= 8) {
    .error "regeneration now fills every frame: TURRET_PREPARE_FINE has no idle frame to run on"
}
.if (TURRET_PREPARE_FINE != 7) {
    .error "the idle frame is the one before the coarse step, which is fine scroll 7"
}

// ===========================================================================
// Scroll state. MAIN THREAD ONLY, and OUTSIDE VIC BANK 0 with everything else
// the main thread owns.
// ===========================================================================
// The VIC never reads a byte of it, so it lives above $c000 with the schedule,
// the logical sprites, the sorter, the HUD's state and the player's.
* = $c540 "scroll state"


// --- scroll state. MAIN THREAD ONLY. The executor never reads any of this. --
scrollFine:      .byte 0                // current YSCROLL, counts UP 0..7
stageTopRowLo:   .byte 0                // the STAGE row at matrix row 0; steps
stageTopRowHi:   .byte 0                // BACK one per coarse step
worldProgressLo: .byte 0                // coarse rows travelled since the stage
worldProgressHi: .byte 0                // start; only ever INCREASES
stageLoopsLo:    .byte 0                // times the map has wrapped end-to-end
stageLoopsHi:    .byte 0                // (see "end of stage" below)
dispPage:     .byte 0                   // 0 = A, 1 = B. The page to display NEXT.
regenPage:    .byte 0                   // page currently being rebuilt
regenPageHi:  .byte 0                   // its high byte ($04 or $28)
regenRow:     .byte 0                   // next screen row to rebuild (25 = idle)
regenTopRowLo: .byte 0                  // stage row of the BACK page's row 0
regenTopRowHi: .byte 0
rrStageLo:    .byte 0                   // scratch: stage row of the row in hand
rrStageHi:    .byte 0
rbLo:         .byte 0                   // rowBack's argument and result
rbHi:         .byte 0
hudPageHi:    .byte 0                   // high byte of the page the HUD writes to

// The stage row each PAGE's matrix row 0 was regenerated with, indexed by page.
// This is the off-screen successor to the on-screen page letter: from it a test
// can predict the stage row of every row of whichever page is displayed, and
// check all 25 rather than checking that one character agrees with itself.
// Written wherever regenTopRow is, so the two cannot drift.
pageTopRowLo: .byte 0, 0
pageTopRowHi: .byte 0, 0

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

// --- pinned fine phase: a DIAGNOSTIC MODE, not a second scroller -----------
// With pinFine non-zero the fine scroll is HELD at pinFineValue instead of
// advancing, so the same sprite geometry can be measured against each of the
// eight badline alignments in turn.
//
// Holding the phase necessarily suspends the coarse step and the page flip:
// they ARE the fine-scroll wrap (see GEOMETRY above), so nothing is left to
// trigger them. Any result obtained under a pinned phase therefore has to be
// re-proven under natural scrolling across real coarse steps and page flips.
//
// Nothing else changes: publishFrame still builds and hands over the frame
// record as always, so $d011 carries the pinned phase through the ordinary
// published channel and the executor cannot tell the difference.
pinFine:      .byte 0                   // 0 = natural scrolling, 1 = held
pinFineValue: .byte 0                   // the YSCROLL to hold, 0..7

scrollStateEnd:
.if (scrollStateEnd > $c600) { .error "the scroll state has grown past its $c600 ceiling" }

// ===========================================================================
// Code. MAIN THREAD ONLY -- the executor never calls one routine in this file
// -- and therefore OUTSIDE VIC BANK 0, beside src/player.asm.
// ===========================================================================
// It lived at $1a00 in a 512-byte hole. Sixteen-bit stage-row arithmetic and
// the modulo wrap pushed it to 586, and the choice was to shave 74 bytes off
// arithmetic that has to be right, or to stop paying bank-0 rent for code the
// VIC cannot see.
//
// Bank 0 is 16 KB and every byte is contended: two screen pages, the sprite
// bitmaps, the HUD's pool, the player's, the blank charset, and a real
// character set plus a terrain tileset when the stage data arrives. Moving this
// module out does not merely make room for the arithmetic, it HANDS BACK the
// whole $1a00-$1bff hole to the subsystem that will actually need VIC-visible
// space. The state moved out for the same reason a few lines above.
* = $4200 "scroller"

// ===========================================================================
// scrollInit — both pages built, page A displayed, frame 0 published.
// ===========================================================================
scrollInit:
    lda #0
    sta scrollFine                      // counts UP from here
    sta worldProgressLo                 // nothing travelled yet
    sta worldProgressHi
    lda #<STAGE_START_ROW               // the BOTTOM of the authored map
    sta stageTopRowLo
    lda #>STAGE_START_ROW
    sta stageTopRowHi
    lda #0
    sta dispPage                        // page A shows [START .. START+24]

    sta regenPage
    lda #>SCREEN_A
    sta regenPageHi
    lda stageTopRowLo
    sta regenTopRowLo
    sta pageTopRowLo
    lda stageTopRowHi
    sta regenTopRowHi
    sta pageTopRowHi
    jsr regenAll

    lda #1
    sta regenPage                       // page B holds [START-1 .. START+23]:
    lda #>SCREEN_B                      // the rows the FIRST coarse step will
    sta regenPageHi                     // reveal, one further back in the map
    lda stageTopRowLo
    sta rbLo
    lda stageTopRowHi
    sta rbHi
    jsr rowBack
    lda rbLo
    sta regenTopRowLo
    sta pageTopRowLo + 1
    lda rbHi
    sta regenTopRowHi
    sta pageTopRowHi + 1
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
// rowBack — step a stage row BACK by one, wrapping 0 -> STAGE_ROWS-1.
// ===========================================================================
// In: rbLo/rbHi. Out: the same pair, one row earlier in the map.
//
// The wrap is written as "fold 0 up to STAGE_ROWS, then subtract" rather than
// "subtract, then fix up a borrow", because the second form has to recognise
// $ffff as a special case and the first cannot go wrong: the value is only ever
// zero or positive on entry, and the fold happens before any arithmetic.
//
// END OF STAGE IS NOT DECIDED HERE. At stage row 0 the window steps back to
// STAGE_ROWS-1 and the stage plays again from its authored bottom; for 25
// coarse steps either side of that the displayed window straddles the join, so
// the map's top rows sit above its bottom rows and there is a content seam.
//
// That is a looping DEMONSTRATION stage's behaviour. A finite stage ends by
// comparing worldProgress -- which never wraps -- against the stage length, and
// what a finished stage DOES is a game-state decision, not a scroller one.
// stageLoops exists so the wrap is observable rather than invisible while that
// decision is open.
//
// What must NOT happen is an unsigned underflow quietly becoming the contract.
// It cannot here: the fold below is explicit and the value is reduced on every
// path.
rowBack:
    lda rbLo
    ora rbHi
    bne !noWrap+
    lda #<STAGE_ROWS
    sta rbLo
    lda #>STAGE_ROWS
    sta rbHi
!noWrap:
    lda rbLo
    sec
    sbc #1
    sta rbLo
    lda rbHi
    sbc #0
    sta rbHi
    rts

// ===========================================================================
// scrollTick — one call per displayed frame. Advances the scroll and publishes
// the frame record the NEXT frame IRQ will adopt.
// ===========================================================================
scrollTick:
    lda pinFine                         // diagnostic mode: hold the phase
    beq !natural+
    lda pinFineValue
    and #7
    sta scrollFine
    jmp scrollPublish
!natural:
    inc scrollFine                      // content moves DOWN one pixel
    lda scrollFine
    cmp #8
    bcs !coarse+                        // INVERTED, and the common path takes
    jmp scrollPublish                   // the absolute jmp: the coarse block
!coarse:                                // below outgrew a relative branch when
                                        // it gained sixteen-bit row arithmetic,
                                        // and the renderer's rule applies here
                                        // too -- a far target goes through a
                                        // jmp rather than being rearranged
                                        // until it happens to fit.

// ---- coarse step: step BACK through the stage, flip the page --------------
    lda #0
    sta scrollFine                      // 7 -> 0 moves the content up seven
                                        // pixels; the row step below moves it
                                        // down eight. Net: one pixel down, the
                                        // same as every other frame.

    lda regenRow                        // the page we are about to display was
    cmp #SCREEN_ROWS                    // not finished. Never expected; counted
    bcs !ready+                         // rather than hidden. Saturates.
    lda scrollLate
    cmp #$ff
    beq !ready+
    inc scrollLate
!ready:
    // THE STAGE ROW STEPS BACK; THE PROGRESS COUNTER STEPS FORWARD.
    // Two names for one event -- see the note at the top of this file.
    //
    // Count the wrap BEFORE it happens, while "the row is zero" is still a
    // fact rather than something to be inferred from a value that has already
    // moved. rowBack is called twice per coarse step -- once for the displayed
    // row and once for the row the back page is built with -- so counting
    // inside rowBack would count every loop twice, one coarse step apart.
    lda stageTopRowLo
    ora stageTopRowHi
    bne !noLoop+
    inc stageLoopsLo
    bne !noLoop+
    inc stageLoopsHi
!noLoop:
    lda stageTopRowLo
    sta rbLo
    lda stageTopRowHi
    sta rbHi
    jsr rowBack
    lda rbLo
    sta stageTopRowLo
    lda rbHi
    sta stageTopRowHi

    inc worldProgressLo
    bne !nohi+
    inc worldProgressHi
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

    // The page just flipped TO already holds stage rows stageTopRow..+24: it
    // was regenerated with exactly that value during the last cycle. Stamp it
    // now, while that is a statement about content rather than intent.
    //
    // STAMP THE DISPLAYED PAGE, NEVER THE BACK ONE. pageTopRow[back] would be
    // the row that page is ABOUT to be regenerated with, so for the one frame
    // between the software flip and the IRQ adopting it at raster 250 the
    // still-displayed page would carry a stamp two coarse steps ahead of its
    // own content. The invariant is the narrow one: pageTopRow[p] is correct
    // whenever p is the page being displayed.
    ldx dispPage
    lda stageTopRowLo
    sta pageTopRowLo,x
    lda stageTopRowHi
    sta pageTopRowHi,x

    // The back page gets the row BEFORE the one now on screen: it is the row
    // the NEXT coarse step will reveal at the top. rbLo/rbHi still hold the
    // stage row just adopted, so one more step back is all it takes.
    jsr rowBack
    lda rbLo
    sta regenTopRowLo
    lda rbHi
    sta regenTopRowHi
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
scrollPublishFallsInto:
    // FALL THROUGH INTO publishFrame. There is no jsr and no jmp here: the
    // adjacency IS the call, and the assertion after publishFrame's body is
    // what keeps it true.
    //
    // ANYTHING INSERTED BETWEEN THESE TWO LABELS BREAKS THE SCREEN SILENTLY.
    // publishFrame would stop being reached while every main-thread counter --
    // the fine phase, the coarse steps, the stage rows, the back page -- went
    // on looking perfectly healthy. The only thing that stops is the one byte
    // that carries the frame to the display, and the picture simply holds still.

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

.if (publishFrame != scrollPublishFallsInto) {
    .error "scrollPublish no longer falls through into publishFrame"
}

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

    // EVERY ROW IS TERRAIN, INCLUDING 0 AND 24.
    //
    // Neither the coarse seam nor the diagnostic rows are masked by blanking
    // content: the aperture is clipped by the blank character set at fixed
    // rasters 55 and 248 (see BLANK_CHARSET in main.asm), so the slack rows
    // carry ordinary world content and are revealed one pixel at a time. There
    // is deliberately no second masking mechanism anywhere -- if a row looks
    // blank on screen it is because the charset clipped it, and for no other
    // reason.
    jmp renderBackgroundRow

// ---------------------------------------------------------------------------
// renderBackgroundRow — one screen row of the back page, from its stage row.
//
// Nothing about the row's IDENTITY is drawn into it. pageTopRow records the
// stage row each page's row 0 was regenerated with, which is a stronger
// statement than any on-screen marker: it lets the exact stage row of all 25
// rows of a page be predicted and checked, off the display, where it cannot
// blink at whoever is judging the picture for smoothness.
// ---------------------------------------------------------------------------
renderBackgroundRow:
    // rrStage = (regenTopRow + regenRow) mod STAGE_ROWS, sixteen bits.
    //
    // regenTopRow is already reduced to 0..STAGE_ROWS-1 and regenRow is 0..24,
    // so the sum is below STAGE_ROWS + 25 and ONE conditional subtract reduces
    // it. A general modulo here would be repeated subtraction on a path that
    // runs five times a frame.
    lda regenTopRowLo
    clc
    adc regenRow
    sta rrStageLo
    lda regenTopRowHi
    adc #0
    sta rrStageHi
    cmp #>STAGE_ROWS
    bcc !reduced+
    bne !wrap+
    lda rrStageLo
    cmp #<STAGE_ROWS
    bcc !reduced+
!wrap:
    lda rrStageLo
    sec
    sbc #<STAGE_ROWS
    sta rrStageLo
    lda rrStageHi
    sbc #>STAGE_ROWS
    sta rrStageHi
!reduced:

    // ---- the real terrain -------------------------------------------------
    // rrStage is now a stage CHARACTER row in the authored level, reduced mod
    // STAGE_ROWS above. src/terrain.asm turns it into forty character codes
    // from the metatile map; nothing about the schedule that got us here has
    // changed, and this routine still writes exactly one row per call.
    //
    // THEN THE TURRET OVERLAY, ON THE SAME ROW, BEFORE THE PAGE IS PUBLISHED.
    // Turrets are background characters and are composed HERE, during
    // hidden-page generation, rather than poked into the visible screen from
    // gameplay code later: a page is then coherent the moment it flips, and
    // "base terrain + turret overlay = generated page" is a statement about how
    // the page was built rather than a convention to be maintained. The
    // authored terrain underneath is never modified -- see src/turrets.asm for
    // the restoration contract that rests on exactly that.
    jsr renderTerrainRow
    jmp turretOverlayRow


// --- the playfield aperture -------------------------------------------------
//
// NO ROW IS MASKED HERE, deliberately. Hiding the coarse seam by blanking
// matrix rows 0 and 24 would put the visible top edge at raster 56 + YSCROLL,
// so it would climb seven pixels over seven frames and snap back a character
// row on the coarse step -- a 6.25 Hz pop along the top of the playfield.
//
// Clipping is the VIC's own g-access instead, through a blank character set
// selected at fixed rasters 55 and 248. The boundary cannot move, because it
// is a raster and not a row.

// ---------------------------------------------------------------------------
// SEGMENT GROWTH GUARD. KickAssembler places explicit `* =` segments exactly
// where told and does not complain when one grows into the next -- it simply
// overwrites, and the failure looks like corrupted code rather than a build
// error.
// ---------------------------------------------------------------------------
.if (* > $4600) {
    .error "the scroller has outgrown its $4200 segment"
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
