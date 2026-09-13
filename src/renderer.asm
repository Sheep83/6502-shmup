// ===========================================================================
// renderer.asm — P0 sprite multiplexer
// ===========================================================================
// THE ONE SUBSYSTEM THAT OWNS GAMEPLAY SPRITE VIC STATE.
//
// Nothing outside this file writes $D000-$D010, $D015, $D01C, $D027-$D02E or
// the sprite pointer table during the display. That is the whole point.
//
// Shape:
//     logical sprites (pre-sorted by Y in P0)
//         -> buildSchedule (main thread)  writes the NEXT buffer
//         -> publishSchedule              sets a one-byte pending flag
//         -> frame IRQ swaps CURRENT      once, at a frame boundary
//         -> executor consumes CURRENT    immutable for the whole frame
//
// The architectural test: if the main thread stopped dead immediately after
// publishSchedule, the executor would still render the whole frame correctly.
// It reads nothing but the CURRENT schedule.
//
// P1 adds a SECOND published record with the same shape and the same handover
// rule — the frame record: fine scroll, $d018, the sprite-pointer-table
// destination and the page id. Both records are adopted at ONE point, exFrame,
// in the lower border. After that the executor is still reading nothing but
// immutable per-frame state; it never asks the scroller which page is live.
// ===========================================================================

// --- physical sprite pool ---------------------------------------------------
// Hardware sprites 0 and 1 are RESERVED (player base + overlay in the eventual
// game) and are simply disabled in P0. The gameplay mux pool is 2..7.
.const MUX_FIRST_SLOT = 2
.const MUX_SLOTS      = 6
.const MUX_LAST_SLOT  = MUX_FIRST_SLOT + MUX_SLOTS - 1     // 7

// --- what the player's two reserved slots require of everybody else ---------
// HW0/HW1 are programmed once per frame by exHud and then left alone, so the
// MODE registers the other phases write must leave the player's bits in the
// state it needs. They already do -- every one of the values below has bits 0
// and 1 clear -- but that is currently true by accident of what the HUD wanted,
// and a future HUD that X-expanded its lives counter differently, or put its
// sprites in front of the playfield, would silently take the player with it.
//
// So it is asserted rather than relied upon. What the player needs:
//   $d017 = 0 in bits 0/1   no Y expand      (both phases write $00 outright)
//   $d01c = 0 in bits 0/1   hires            (both phases write $00 outright)
//   $d01d = 0 in bits 0/1   no X expand      HUD_D01D, and $00 at the handoff
//   $d01b = 0 in bits 0/1   in front of the  HUD_D01B, and $00 at the handoff
//                           playfield
// and that nobody else claims the slots at all:
//   $d015, $d010            HUD_ENABLE / HUD_D010 must not name them
//   the mux                 MUX_FIRST_SLOT must start above them
.if ((HUD_D01B & PLAYER_SLOT_MASK) != 0) { .error "the HUD's $d01b would push the player behind the playfield" }
.if ((HUD_D01D & PLAYER_SLOT_MASK) != 0) { .error "the HUD's $d01d would X-expand the player" }
.if ((HUD_ENABLE & PLAYER_SLOT_MASK) != 0) { .error "the HUD's $d015 names a player slot" }
.if ((HUD_D010 & PLAYER_SLOT_MASK) != 0) { .error "the HUD's $d010 names a player slot" }
.if (MUX_FIRST_SLOT < 2) { .error "the gameplay mux has been given a slot reserved for the player" }

// --- the reuse rule ---------------------------------------------------------
// A VIC sprite with Y = n occupies rasters n .. n+20 (21 lines). The physical
// slot is therefore free from raster n+21.
//
// Accepted entry i reuses the slot of accepted entry i-6 (round robin over six
// slots). Its batch fires REUSE_LEAD lines before its own Y, so the reprogram
// lands at raster (Y_i - REUSE_LEAD) and we need:
//
//     Y_i - REUSE_LEAD  >=  Y_(i-6) + SPRITE_HEIGHT
//     Y_i - Y_(i-6)     >=  SPRITE_HEIGHT + REUSE_LEAD  =  MIN_REUSE_GAP
//
// REUSE_LEAD is MEASURED, not assumed. tests/test_p0.py traces the executor and
// reports its real cost; the first draft of this file guessed 3 lines and the
// test rejected it. Measured on the P0 fixtures:
//
//     single-entry mid-screen batch   277 cycles   (4.4 raster lines)
//     six-entry batch                 666 cycles  (10.6 raster lines)
//
// The executor itself is ~90 cycles of 6502; the rest is VIC cycle theft
// (badline plus sprite DMA on a line with six sprites active). That is exactly
// why this number has to be measured on hardware timing rather than counted
// from a listing.
//
// The builder may merge up to MUX_SLOTS entries into one batch (it happens when
// several accepted sprites share a Y), so the lead must cover the SIX-entry
// case even though the P0 fixtures only produce one-entry batches mid-screen.
// 12 lines = 756 cycles gives 666 plus ~90 cycles of headroom.
//
// NOTE this is deliberately NOT "21 is a magic number". 21 is the hardware
// sprite height; REUSE_LEAD is OUR safety margin and is the only tunable here.
.const SPRITE_HEIGHT   = 21
.const REUSE_LEAD      = 12
.const MIN_REUSE_GAP   = SPRITE_HEIGHT + REUSE_LEAD        // 33

// --- PRODUCTION GAMEPLAY Y BOUNDS -------------------------------------------
// The vertical border is held open so a HUD can eventually live in it, and an
// open border clips NOTHING: the blank charset clips characters, and there is
// no equivalent for sprites. Three separate consequences make a Y range part
// of the contract rather than a nicety.
//
// MIN 55. Below the aperture a gameplay sprite is simply loose in the border,
// on top of the HUD's territory and across the handoff and top-split phases.
// It also risks the 8-bit Y compare: the VIC matches Y against the low byte of
// the raster, so Y <= 55 matches a second time at Y+256 on PAL lines 256..311.
// $d015 is zero across that whole span (see exFrame), so no ghost can appear
// today -- but a HUD that enables slots early would resurrect it, and 55 makes
// the hazard unreachable instead of merely unreached.
//
// MAX 226. A sprite at Y=226 displays its last line at 246, and its data is
// fetched no later than line 246. The bottom aperture split has to land its
// $d018 store inside cycles 0..14 of line 248, and sprite DMA owns cycles 0..9
// of a line for HW3..HW7. 226 is the largest Y that leaves lines 247 and 248
// free of sprite DMA, which is exactly what that split's margin is made of.
//
// A sprite outside the range is REJECTED at admission and counted, never
// clamped. Clamping would move a sprite the caller placed deliberately and
// make the model and the machine disagree about where it is; rejection is a
// decision the model can reproduce exactly.
.const MIN_SPRITE_Y    = 55
.const MAX_SPRITE_Y    = 226

// The player is outside the mux and could in principle be given a wider range:
// its DMA is fetched in cycles 57..62 of the PREVIOUS line rather than 0..9 of
// its own, so the bottom split's margin is a different calculation, and
// MIN_REUSE_GAP does not apply to it at all. src/player.asm deliberately does
// NOT take that room, because this slice has no measurement that would justify
// it. Asserted here, where both pairs are visible, so the day somebody widens
// one they are told to widen or re-derive the other.
.if (PLAYER_MIN_Y != MIN_SPRITE_Y) { .error "the player's Y floor no longer matches the mux admission floor" }
.if (PLAYER_MAX_Y != MAX_SPRITE_Y) { .error "the player's Y ceiling no longer matches the mux admission ceiling" }

// --- capacities -------------------------------------------------------------
// MAX_LOGICAL is deliberately LARGER than MAX_SCHED. P2 left the builder
// silently stopping at the schedule cap, and noted that as something to fix
// before moving geometry could change accepted counts. A cap that cannot be
// exceeded cannot be tested, so the logical input pool is bigger than the
// schedule it feeds: a fixture can now offer more sprites than the schedule can
// hold, and the overflow path is exercised rather than argued about.
//
// MAX_SCHED is NOT raised to avoid the fault. See statOverflow.
.const MAX_LOGICAL = 32
.const MAX_SCHED   = 24
.const MAX_BATCH   = 24

// The frame IRQ sits in the lower border, so batch 0 (the first up-to-six
// sprites) is programmed before the raster reaches the top of the display —
// the classic "set up the initial sprites in vblank" arrangement.
.const FRAME_IRQ_LINE = 250

// The vertical border is opened every frame so a HUD phase can own hardware
// sprites above the playfield. See exBottom, which also closes the aperture.
.const BORDER_OPEN_LINE = 243

// WHERE THE HUD IS PROGRAMMED, and the reason it is not raster 250.
//
// Sprite Y is compared against the LOW BYTE of the raster, so the HUD's Y=16
// matches a second time at raster 272 -- inside the lower vertical blank, which
// the open vertical border displays. exFrame clears $d015 at raster 250, so
// that compare passes with nothing enabled and no ghost can be fetched; the HUD
// is then programmed at raster 4, after the ghost opportunity has gone by, and
// re-enabled there. Programming it at 250 instead would put a valid Y in place
// before the compare and hand the ghost everything it needs.
//
// 4 is otherwise the quietest line in the frame: it is far below the badline
// range (48..247) so it can never be stalled, and $d015 is still zero when it
// runs, so there is no sprite DMA either. The phase has fourteen lines before
// the HUD's own first fetch at line 17.
.const HUD_IRQ_LINE     = 4

// THE HUD -> GAMEPLAY OWNERSHIP TRANSFER, and where batch 0 now runs.
//
// 40 is chosen, not assumed, and three things make it quiet:
//   * it is outside the badline range 48..247, so it can NEVER be a badline;
//   * $d015 is zero from raster 250 until this phase writes it, so there is no
//     sprite DMA anywhere in the vertical blank OR in the top border -- the
//     handoff is the one phase in the frame guaranteed to run at full speed;
//   * it leaves twelve lines before TOP_ARM_LINE and fifteen before the first
//     legal sprite Y, against a six-entry batch 0 costing about five.
// Measured margins are in the slice report.
.const HANDOFF_LINE     = 40

// Where the TOP aperture split arms.
//
// 53, not 52. The handoff exits at raster 51 in the worst case measured across
// every fixture, so 52 left exactly one raster of margin -- and the handoff is
// the phase most likely to grow, because the HUD's own register restores will
// eventually be added to it. 53 gives two, and still leaves the poll running
// well before its target: exactly one of lines 48..55 is a badline, and at
// YSCROLL=5 (the only phase where line 53 is one) the target is 55, two lines
// further on, which the poll reaches with the whole of line 54 in hand.
.const TOP_ARM_LINE     = 53

// ===========================================================================
// Schedule storage — two buffers, outside VIC bank 0 so it can never be
// mistaken for graphics data.
// ===========================================================================
* = $c000 "schedule buffers"

// per-entry arrays, [buffer][entry]
schedY:      .fill 2 * MAX_SCHED, 0     // sprite Y
schedX:      .fill 2 * MAX_SCHED, 0     // sprite X low byte
schedXHi:    .fill 2 * MAX_SCHED, 0     // sprite X bit 8 (0 or 1). P3: carried
                                        // per ENTRY so the builder can compute
                                        // the complete $D010 for every batch.
                                        // P0-P2 were all X < 256 and this was
                                        // hardcoded to clear.
schedPtr:    .fill 2 * MAX_SCHED, 0     // sprite pointer value
schedCol:    .fill 2 * MAX_SCHED, 0     // sprite colour
schedSlot:   .fill 2 * MAX_SCHED, 0     // hardware slot 2..7 (explicit: inspectable)
schedSlot2:  .fill 2 * MAX_SCHED, 0     // slot*2, the $D000/$D001 index (no IRQ arithmetic)
schedId:     .fill 2 * MAX_SCHED, 0     // P4: the LOGICAL SPRITE ID this entry
                                        // is. Once a sorter exists, accepted
                                        // index is a position and not an
                                        // identity: the same sprite can be
                                        // entry 3 this frame and entry 8 the
                                        // next. Recorded so a test can ask
                                        // "which sprite is entry i's same-slot
                                        // predecessor" and get an identity
                                        // back rather than an array offset.
                                        // The executor never reads it.

// per-batch arrays, [buffer][batch]
batchLine:   .fill 2 * MAX_BATCH, 0     // raster line this batch fires on
batchFirst:  .fill 2 * MAX_BATCH, 0     // first entry index
batchCount:  .fill 2 * MAX_BATCH, 0     // entry count
batchD010:   .fill 2 * MAX_BATCH, 0     // COMPLETE $D010 value after this batch

// per-buffer scalars
schedBatches:  .byte 0, 0               // number of batches in the buffer
schedEnable:   .byte 0, 0               // complete $D015 value for the frame
schedEntries:  .byte 0, 0               // accepted entry count

// --- the PLAYER block, [buffer] ---------------------------------------------
// HW0 and HW1 are reserved for the player (contract §2) and are NOT in the mux,
// so they have no schedule entry, no slot and no batch. They still have to be
// PUBLISHED, though, or the main thread would be programming VIC registers
// behind the executor's back -- which is the one thing this architecture exists
// to prevent. So the player rides in the schedule it is not part of: the
// builder copies src/player.asm's presentation block in here, publishSchedule
// hands it over with the same byte, exFrame adopts it at raster 250 with
// everything else, and exHud programs the two slots from the ADOPTED copy.
//
// The two enable/MSB bytes name ONLY bits 0 and 1. They are composed into the
// complete $d015 and $d010 values the renderer writes; see bs_enable / bs_d010
// below, and exHud.
schedPlyX0:     .byte 0, 0              // HW0 X low byte
schedPlyY0:     .byte 0, 0
schedPlyPtr0:   .byte 0, 0
schedPlyCol0:   .byte 0, 0
schedPlyX1:     .byte 0, 0              // HW1 X low byte
schedPlyY1:     .byte 0, 0
schedPlyPtr1:   .byte 0, 0
schedPlyCol1:   .byte 0, 0
schedPlyEnable: .byte 0, 0              // $d015 bits 0/1 only
schedPlyD010:   .byte 0, 0              // $d010 bits 0/1 only

// --- publication state ------------------------------------------------------
schedCurrent:  .byte 0                  // buffer the EXECUTOR reads
schedNext:     .byte 1                  // buffer the BUILDER writes
schedPending:  .byte 0                  // 1 = swap at the next frame IRQ

// THE FRAME IRQ MUST NOT PROMOTE A BUFFER THAT IS BEING WRITTEN.
//
// The double buffer was always meant to guarantee this and did not. The
// builder latches its destination from schedNext ONCE, at entry, and then
// writes that buffer for several thousand cycles; the frame IRQ swaps
// schedCurrent and schedNext whenever schedPending is set. So a build that
// STARTS while a publication is still pending has its destination promoted to
// CURRENT underneath it, and the executor renders a half-written schedule.
//
// That is not hypothetical. Measured on RING-SLOW, 11.7% of builds begin with
// schedPending already set -- it happens whenever the frame IRQ lands between
// buildSchedule and publishSchedule, because the publication then misses that
// frame's swap and is still pending when the next pass starts building.
//
// A fixture that rebuilds every frame survives it: the next frame overwrites
// the damage. MAXCAP does not rebuild -- it is static and publishes exactly
// once -- so a schedule corrupted during its activation stays corrupted for as
// long as the fixture is displayed. Forcing the condition reproduced a CURRENT
// with schedEntries = 0 while the build itself completed correctly.
//
// Deferring the swap costs at most one frame of latency and cannot starve:
// the build occupies well under a whole frame, so raster 250 eventually falls
// outside it. schedBuildDefer counts the deferrals so the cost is visible
// rather than silent.
schedBuildDefer:  .byte 0               // saturating: builds that began with a
                                        // publication still pending

// WHICH PHASE THE NEXT RASTER EVENT IS.
//
// Four now, where P1 had two and the border work made three. Every arm sets it
// and every phase is entered from exactly one value, so it cannot latch stuck
// the way a lock can: exBottom always hands back to PH_FRAME.
//
//   PH_BATCH     *  a mid-screen mux batch (curBatch says which)
//   PH_FRAME   250  adopt the frame + schedule records. Nothing else.
//   PH_HUD       4  program HW2-HW7 as the static top-border HUD
//   PH_HANDOFF  40  take HW2-HW7 back for gameplay and run batch 0
//   PH_TOP      53  poll to 55 (54 at YSCROLL=7) and switch to the REAL charset
//   PH_BOTTOM  243  hold the border open, poll to 248, switch to BLANK
//
// PH_BATCH IS ZERO, and that is a timing decision rather than a tidy one.
// Batches are much the commonest phase -- MAXCAP runs nineteen a frame against
// four structural ones -- and they are the only phase with a hard deadline:
// REUSE_LEAD gives a mid-screen batch twelve raster lines to reprogram a slot
// before the beam reaches the sprite it is reprogramming. Making the batch the
// zero case lets the dispatch reach it in `lda / bne / jmp`, the same eight
// cycles the two-phase executor used, instead of paying a compare per phase
// added. The structural phases absorb the cost instead; they have whole rasters
// of margin and no deadline of their own.
exPhase:          .byte 0

.const PH_BATCH   = 0
.const PH_FRAME   = 1
.const PH_HANDOFF = 2
.const PH_TOP     = 3
.const PH_BOTTOM  = 4
.const PH_HUD     = 5

// --- aperture split instrumentation ----------------------------------------
// The raster the split write actually landed on, min and max over the whole
// run. Both must read their split line and nothing else: a structural phase
// that drifts by even one line tears a character row, and this is the cheapest
// statement that it never did. Deliberately NOT a "was it late" flag -- a flag
// says it happened, a min/max says it never happened.
// The raster the HUD phase entered on, and the raster it finished on. The
// second is the one the margin to the HUD's first sprite fetch is made of.
hudEntryMin:      .byte $ff
hudEntryMax:      .byte 0
hudExitMax:       .byte 0

// The raster the handoff actually entered on. Must read HANDOFF_LINE and
// nothing else: it owns the transfer of HW2-HW7 from the HUD to gameplay, and
// a transfer that drifts is a transfer that overlaps somebody's DMA.
handoffEntryMin:  .byte $ff
handoffEntryMax:  .byte 0
// The raster at which the handoff FINISHED -- batch 0 programmed, $d015 set.
// This is the number the margin to the top aperture split is made of, and it
// is measured rather than derived from a trace: the monitor's trace log
// truncates under a dense fixture and then mis-pairs entries, which inflates
// exactly this figure.
handoffExitMax:   .byte 0

topSplitMin:      .byte $ff               // 55 normally, 54 at YSCROLL=7:
topSplitMax:      .byte 0                 // see exTop for why the phase differs
topTarget:        .byte 0                 // the line THIS frame's split aimed at
topLanded:        .byte 0                 // the line the $d018 half of the top
                                          // split ACTUALLY landed on. Only the
                                          // YSCROLL=7 path needs it: there the
                                          // two halves of the split are a line
                                          // apart, so by the time $d021 has
                                          // been written the beam has moved on
                                          // and $d012 no longer answers the
                                          // question the measurement asks.
botSplitMin:      .byte $ff
botSplitMax:      .byte 0
// A split phase entered so late that its poll would have to wrap a whole frame.
// Saturating; must stay 0. The poll is skipped in that case rather than hanging
// inside the handler with I set.
edgeLate:         .byte 0

// ===========================================================================
// The P1 frame record — the second published channel.
// ===========================================================================
// Double buffered for exactly the reason the schedule is: the frame IRQ must
// never observe a half-updated set in which $d018 names one page and the
// pointer destination names the other. That single-frame inconsistency is the
// historical bug class this whole checkpoint exists to rule out.
frameD011:    .byte 0, 0                // complete $d011 (D011_BASE | yscroll)
frameD018:    .byte 0, 0                // complete $d018, REAL charset
frameD018B:   .byte 0, 0                // the same page with the BLANK charset.
                                        // Precomputed rather than masked at run
                                        // time: both aperture splits are inside
                                        // a few-cycle window and neither can
                                        // afford an AND/ORA, and a record that
                                        // carries both values cannot disagree
                                        // with itself about which page it means.
framePtrHi:   .byte 0, 0                // high byte of the sprite pointer table
framePage:    .byte 0, 0                // 0 = page A, 1 = page B
frameCurrent: .byte 0                   // record the EXECUTOR reads
frameNext:    .byte 1                   // record the MAIN THREAD writes
framePending: .byte 0                   // 1 = adopt at the next frame IRQ

// --- P1 frame diagnostics (written by the frame IRQ, read by tests) --------
frameCounter:   .byte 0, 0              // displayed frames, 16-bit lo/hi. Also
                                        // the main thread's frame tick.
curPage:        .byte 0                 // page adopted for this frame
prevPage:       .byte 0
flipCount:      .byte 0, 0
lastFlipLine:   .byte 0                 // raster at which $d018 last changed.
                                        // Must always be FRAME_IRQ_LINE.
flipLineMin:    .byte $ff               // min/max raster over EVERY flip of the
flipLineMax:    .byte 0                 // whole run. Proving the last flip was
                                        // at 250 proves one flip; proving the
                                        // min and the max are both 250 proves
                                        // all of them, over millions of frames,
                                        // which no sampled stepping can do.
pageAFrames:    .byte 0, 0
pageBFrames:    .byte 0, 0
transAB:        .byte 0, 0
transBA:        .byte 0, 0
// Fault counters SATURATE at $ff. A wrapping 8-bit fault counter can read zero
// after a long run and look clean; this one cannot. Any non-zero value is a
// failure, so the exact count past 255 is not interesting.
statPageMismatch: .byte 0               // $d018 read back != the published value
statPtrMismatch:  .byte 0               // pointer destination != the page $d018
                                        // is actually displaying
frameEntryLine: .byte 0                 // raster at frame-IRQ ENTRY
batchCounter:   .byte 0, 0, 0           // raster batches executed, 24-bit.
                                        // Incremented AFTER the sprite writes,
                                        // so it delays no register programming.
                                        // 16 bits wrapped after ~7,300 frames
                                        // of the nine-batch fixture and the
                                        // stress report understated by 4x.
statLate:       .byte 0                 // exLate taken: a batch was chased
lateRun:        .byte 0                 // consecutive late batches this frame
maxLateRun:     .byte 0                 // worst such run seen

// --- diagnostic counters (read by tests; never read by the executor) --------
statAccepted:  .byte 0
statRejUnsafe: .byte 0                  // gap < SPRITE_HEIGHT: genuinely impossible
statRejMargin: .byte 0                  // SPRITE_HEIGHT <= gap < MIN_REUSE_GAP
statReuse:     .byte 0                  // number of slot-reuse events
statBatches:   .byte 0
// P2. The largest MID-SCREEN batch this schedule contains (batch 0, the frame
// batch, is excluded: it is always min(6, accepted) and says nothing about
// merged reuse). This is what REUSE_LEAD is sized for, and until P2 no fixture
// ever made it greater than 1.
statMaxBatch:  .byte 0
// P3 fault counters. Saturating, like the page/pointer counters: any non-zero
// value is a failure of the CALLER's geometry, not of the renderer, and the
// exact count past 255 is not interesting.
statOverflow:      .byte 0              // logical sprites that could not be
                                        // scheduled because MAX_SCHED was full
statRejRange:      .byte 0              // logical sprites refused because their Y
                                        // is outside MIN_SPRITE_Y..MAX_SPRITE_Y.
                                        // Saturating. NOT a fault: it is the
                                        // production contract being enforced,
                                        // and the qualification fixtures that
                                        // trip it do so deliberately.
statBatchOverflow: .byte 0              // batches that did not fit MAX_BATCH

// --- executor working state -------------------------------------------------
curBatch:      .byte 0
curBase:       .byte 0                  // schedCurrent * MAX_SCHED
curBatchBase:  .byte 0                  // schedCurrent * MAX_BATCH

// ===========================================================================
// buildSchedule — MAIN THREAD ONLY. Writes the NEXT buffer.
// ===========================================================================
// Input: logical sprite arrays (see fixtures.asm), pre-sorted by ascending Y.
//        logCount = number of logical sprites.
// Output: a complete schedule in buffer schedNext, plus the stat counters.
//
// Every decision — acceptance, physical slot, batch line, $D010, $D015 — is
// made HERE. The executor makes none.
// ===========================================================================
* = $1000 "schedule builder"

buildSchedule:
    // WITHDRAW ANY PENDING PUBLICATION BEFORE WRITING schedNext.
    //
    // This build is about to write schedNext for several thousand cycles, and
    // schedNext is exactly the buffer the frame IRQ promotes to CURRENT when
    // schedPending is set. A build that starts with a publication still
    // pending therefore has its destination promoted underneath it, and the
    // executor renders a half-written schedule.
    //
    // Measured before this: 11.7% of RING-SLOW builds began in that state. It
    // happens whenever the frame IRQ lands between buildSchedule and
    // publishSchedule, because the publication then misses that frame's swap
    // and is still waiting when the next pass starts building.
    //
    // Clearing it here loses nothing. The schedule being withdrawn is the one
    // sitting in schedNext -- the very buffer this build is overwriting -- so
    // it was already superseded. publishSchedule re-sets the flag once the
    // buffer is complete, and the next frame boundary adopts it.
    //
    // A FLAG SAYING "A BUILD IS IN PROGRESS" WAS TRIED FIRST AND IS WORSE. It
    // is a lock released only on the normal exit, so a build abandoned part way
    // leaves it set and the frame IRQ never swaps again: CURRENT freezes on the
    // previous fixture permanently. This form has no such state -- an abandoned
    // build simply leaves schedPending clear, CURRENT keeps the last complete
    // schedule, and the next successful build repairs everything.
    lda schedPending
    beq !notPending+
    lda #0
    sta schedPending
    lda schedBuildDefer                 // saturating: how often the race state
    cmp #$ff                            // actually arises, so the guard cannot
    beq !notPending+                    // quietly become dead code
    inc schedBuildDefer
!notPending:

    lda #0
    sta statAccepted
    sta statRejUnsafe
    sta statRejMargin
    sta statReuse
    sta statBatches
    sta statOverflow
    sta statRejRange
    sta statBatchOverflow

    ldx schedNext                       // entry base for this buffer
    lda #0
    cpx #0
    beq !baseDone+
    lda #MAX_SCHED
!baseDone:
    sta bs_base

    // ---- the player block, copied into the buffer being built -----------
    // Ten bytes, straight across, from the main thread's presentation record.
    // It happens HERE, after the pending publication has been withdrawn above,
    // for exactly the reason that withdrawal exists: schedNext is the buffer
    // the frame IRQ promotes, and only this routine may write it.
    ldx schedNext
    lda plyPresX0
    sta schedPlyX0,x
    lda plyPresY0
    sta schedPlyY0,x
    lda plyPresPtr0
    sta schedPlyPtr0,x
    lda plyPresCol0
    sta schedPlyCol0,x
    lda plyPresX1
    sta schedPlyX1,x
    lda plyPresY1
    sta schedPlyY1,x
    lda plyPresPtr1
    sta schedPlyPtr1,x
    lda plyPresCol1
    sta schedPlyCol1,x
    lda plyPresEnable
    sta schedPlyEnable,x
    lda plyPresD010
    sta schedPlyD010,x

    lda #0
    sta bs_pos                          // position in the SORTED list
    sta bs_acc                          // accepted count
    sta bs_slotcycle                    // round-robin cursor: MUST reset per build,
                                        // or a rebuild inherits the previous frame's
                                        // slot phase and the schedule stops matching
                                        // the documented "accepted mod 6" rule.

    // THE PLAYER'S BITS ARE THE SEED, NOT A LATER MERGE.
    //
    // bs_enable and bs_d010 accumulate the complete $d015 and $d010 for this
    // frame during the acceptance pass, and every batch's $d010 is a snapshot
    // of the running value (bs_d010cum). Starting both from the player's two
    // bits therefore puts HW0/HW1 into EVERY complete value the executor ever
    // writes -- schedEnable, and every batchD010 -- without the executor
    // knowing the player exists, and without a single read-modify-write.
    //
    // The acceptance pass only ever touches bits 2..7 (bitMask is indexed by a
    // slot, and slots are MUX_FIRST_SLOT..MUX_LAST_SLOT), so the two seeded bits
    // survive it by construction.
    lda plyPresEnable
    sta bs_enable
    lda plyPresD010
    sta bs_d010

// ---- acceptance pass -------------------------------------------------------
// P4: the scan walks SORTED POSITIONS and dereferences each to a logical ID.
// It used to walk logical storage order directly, which was only correct while
// every fixture happened to be stored pre-sorted by Y -- P0's deliberate
// simplification. The acceptance rule below is unchanged and still compares
// against accepted entry i-6; what changed is that the order those accepted
// entries arrive in is now decided by the sorter rather than by the order
// someone typed the fixture table in.
bs_loop:
    lda bs_pos
    cmp sortedCount
    bcc !more+
    jmp bs_accepted_done
!more:

    ldy bs_pos
    lda sortedIDs,y
    sta bs_id                           // the logical sprite under consideration
    tay
    lda logY,y
    sta bs_y

    // PRODUCTION Y BOUNDS, CHECKED BEFORE EVERYTHING ELSE.
    //
    // This is a property of the sprite alone -- not of how full the schedule
    // is, not of what its predecessor is doing -- so it is decided first and
    // the outcome is unambiguous. Checking it after the capacity test would
    // make a sprite's verdict depend on how many sprites happened to precede
    // it, and the independent model would have to reproduce that accident.
    lda bs_y
    cmp #MIN_SPRITE_Y
    bcc !reject+
    cmp #MAX_SPRITE_Y + 1
    bcc !inRange+                       // both arms go through one local jmp:
!reject:                                // bs_outOfRange is 157 bytes away, past
    jmp bs_outOfRange                   // what a relative branch can reach
!inRange:

    // P3: schedule capacity is a HARD limit and is checked FIRST, before the
    // reuse rule, so the outcome is unambiguous: a sprite that does not fit is
    // counted as an overflow and nothing else. Deciding "rejected for spacing"
    // about a sprite there was no room for would be a lie, and the independent
    // model would have to reproduce the lie.
    //
    // The scan CONTINUES rather than stopping, so statOverflow reports how many
    // sprites were dropped, not merely that some were. Nothing is written to
    // the schedule arrays past MAX_SCHED, which is the memory-safety property
    // that matters.
    lda bs_acc
    cmp #MAX_SCHED
    bcc !room+
    lda statOverflow
    cmp #$ff
    beq !counted+
    inc statOverflow
!counted:
    jmp bs_next
!room:

    lda bs_acc
    cmp #MUX_SLOTS
    bcc bs_accept                       // first six always fit: no slot to reuse

    // Reuse test against the entry that currently owns this physical slot:
    // accepted index (acc - MUX_SLOTS).  <-- SIX, not eight.
    sec
    lda bs_acc
    sbc #MUX_SLOTS
    clc
    adc bs_base
    tay
    lda bs_y
    sec
    sbc schedY,y                        // gap = thisY - ownerY
    bcc bs_unsafe                       // negative: list not sorted / impossible
    cmp #MIN_REUSE_GAP
    bcs bs_accept
    cmp #SPRITE_HEIGHT
    bcs bs_margin                       // 21..23: legal on hardware, inside OUR margin
bs_outOfRange:
    lda statRejRange                    // saturating: the count matters, the
    cmp #$ff                            // exact value past 255 does not
    beq !saturated+
    inc statRejRange
!saturated:
    jmp bs_next

bs_unsafe:
    inc statRejUnsafe                   // < 21: the two sprites genuinely overlap
    jmp bs_next
bs_margin:
    inc statRejMargin
    jmp bs_next

bs_accept:
    // physical slot = MUX_FIRST_SLOT + (accepted mod MUX_SLOTS)
    lda bs_acc
    cmp #MUX_SLOTS
    bcc !noWrap+
    inc statReuse
!noWrap:
    ldx bs_slotcycle
    lda bs_acc
    clc
    adc bs_base
    tay                                 // Y = schedule entry index (buffer-based)

    txa
    clc
    adc #MUX_FIRST_SLOT
    sta bs_slot                         // kept: the accumulators below index
    sta schedSlot,y                     // by slot, not by entry
    asl
    sta schedSlot2,y

    lda bs_y
    sta schedY,y
    lda bs_id
    sta schedId,y                       // P4: remember WHICH sprite this is
    ldx bs_id
    lda logX,x
    sta schedX,y
    lda logXHi,x
    sta schedXHi,y                      // P3: bit 8 of X, per entry

    // ---- $D010 and the enable mask, accumulated HERE --------------------
    // Both used to be separate full walks over the accepted entries after the
    // acceptance pass finished. Every value they needed -- the slot and the X
    // MSB -- is already in hand at this point, so walking the entries a second
    // and third time was paying to rediscover it.
    //
    // P4 measured what that cost on a twelve-sprite frame: the enable pass 659
    // cycles and the $D010 pass 1058, against 2532 for the acceptance pass
    // itself. Folding both in is the main-thread saving that matters, because
    // after P4 the main thread is the constraint, not the raster executor.
    //
    // The running $D010 is ALSO recorded per entry, in bs_d010cum. A batch's
    // complete value is the running value after its LAST entry, so the batch
    // pass can read it straight out instead of re-accumulating -- see bs_dLoop.
    // The flags here are still the ones LDA logXHi set: STA does not touch them.
    bne !msbSet+
    ldx bs_slot
    lda bs_d010
    and bitMaskInv,x                    // X < 256: this slot's bit is 0
    jmp !msbDone+
!msbSet:
    ldx bs_slot
    lda bs_d010
    ora bitMask,x                       // X >= 256: this slot's bit is 1
!msbDone:
    sta bs_d010
    ldx bs_acc
    sta bs_d010cum,x                    // the complete value AFTER this entry
    ldx bs_slot
    lda bs_enable
    ora bitMask,x
    sta bs_enable

    ldx bs_id                           // restore: the stores below need it
    lda logPtr,x
    sta schedPtr,y
    lda logCol,x
    sta schedCol,y

    inc bs_slotcycle
    lda bs_slotcycle
    cmp #MUX_SLOTS
    bcc !cycleOk+
    lda #0
    sta bs_slotcycle
!cycleOk:
    inc bs_acc

bs_next:
    inc bs_pos
    jmp bs_loop

bs_accepted_done:
    lda bs_acc
    sta statAccepted
    ldx schedNext
    sta schedEntries,x

// ---- enable mask ----------------------------------------------------------
// Accumulated during the acceptance pass; nothing to walk here.
bs_enDone:
    ldx schedNext
    lda bs_enable
    sta schedEnable,x

// ---- batch pass ------------------------------------------------------------
// Batch 0 = the first up-to-MUX_SLOTS entries, programmed by the frame IRQ.
// After that, entries are grouped by their LEGAL PROGRAMMING WINDOW.
//
// ---------------------------------------------------------------------------
// THE WINDOW, AND WHY IT WAS ALREADY SITTING HERE UNUSED
// ---------------------------------------------------------------------------
// The acceptance rule at the top of this file is written as one inequality:
//
//     Y_i - REUSE_LEAD  >=  Y_(i-6) + SPRITE_HEIGHT
//
// Read it as two endpoints rather than one test and it IS a window. Accepted
// entry i may legally be programmed at any raster in
//
//     earliest_i = Y_(i-6) + SPRITE_HEIGHT   the raster its predecessor's
//                                            slot falls free -- a sprite with
//                                            Y = n occupies n .. n+20
//     latest_i   = Y_i - REUSE_LEAD          the last raster that still leaves
//                                            the measured lead before the VIC
//                                            fetches this sprite
//
// and acceptance is exactly the statement that the window is non-empty. The
// builder used to take `latest_i` for every entry and then merge two entries
// only if those two numbers happened to be EQUAL. At the minimum accepted gap
// of 33 the window is one raster wide and that is all there is; at a gap of 60
// it is 27 rasters wide, and every one of those rasters was being thrown away.
//
// Sixteen sprites ten rasters apart therefore cost ELEVEN raster interrupts,
// where the same sixteen in four rows cost four. The sprites were never the
// problem; the batch count was.
//
// ---------------------------------------------------------------------------
// THE GROUPING RULE
// ---------------------------------------------------------------------------
// Batches address a CONTIGUOUS run of accepted entries -- batchFirst plus
// batchCount is the whole representation, and the executor walks it as a run --
// so grouping can only ever join neighbours. Within that constraint:
//
//     open a batch at entry j, on line L = latest_j
//     absorb entry k while  earliest_k <= L
//     close when it will not fit, or at MUX_SLOTS entries
//
// L is the LARGEST line the batch may use, because the batch line must be
// <= latest_m for every member and the accepted list is sorted by Y, so
// latest_j is the smallest of those. Choosing the largest legal line is also
// what admits the most followers, since their constraint is earliest_k <= L.
//
// WHY ONE LINE TESTED AGAINST EVERY MEMBER, AND NOT PAIRWISE OVERLAP. Windows
// that overlap in pairs need not share a common raster: [0,10], [5,15], [12,20]
// overlap pairwise around the chain but have no line in all three. Testing each
// candidate against the single chosen L makes the common intersection the only
// thing that can ever be true, so that shape cannot be mis-grouped. It is in
// tests/test_p2.py under the name the model gives it.
//
// WHY THE DEADLINES ARE UNCHANGED. The leader keeps exactly the line it had
// before, so the critical path P2 measured -- batch line to the leader's own
// fetch -- is the same number against the same 756-cycle budget, and the leader
// has the smallest Y in the batch so it is the binding one. Every follower is
// moved EARLIER than the line it used to get, which can only increase its own
// lead, and is checked against its predecessor's last displayed raster before
// it is allowed to move at all. Nothing is programmed later than it was, and
// nothing is programmed before its slot is free.
//
// WHY A BATCH CANNOT EXCEED SIX. Entry j+6's predecessor is entry j itself, so
// earliest_(j+6) = Y_j + SPRITE_HEIGHT, while the batch line is Y_j -
// REUSE_LEAD. The first is always the larger, so entry j+6 can never join a
// batch that entry j leads. The explicit cap below is therefore provably
// unreachable -- it is kept because "one update per hardware slot" is the
// executor's contract and a contract that is only implied by arithmetic
// elsewhere is one nobody checks.
    ldx schedNext
    lda #0
    cpx #0
    beq !bbDone+
    lda #MAX_BATCH
!bbDone:
    sta bs_bbase

    lda #0
    sta bs_nb                           // batch count

    lda bs_acc
    bne !haveEntries+
    jmp bs_batchDone                    // out of line: the overflow reporting
!haveEntries:                           // below pushed bs_batchDone out of
                                        // branch range

    // Batch 0's line is the HANDOFF, not the frame transaction. It is the only
    // batch whose line is not derived from a sprite Y, and moving it is the
    // whole of this slice's change to the schedule: same accepted entries, same
    // slots, same batch membership, one different number in one field.
    ldy bs_bbase
    lda #HANDOFF_LINE
    sta batchLine,y
    lda #0
    sta batchFirst,y
    lda bs_acc
    cmp #MUX_SLOTS
    bcc !small+
    lda #MUX_SLOTS
!small:
    sta batchCount,y
    sta bs_i                            // next entry to place
    inc bs_nb

// ---- open a new mid-screen batch, led by entry bs_i ------------------------
// Reached only with bs_i < bs_acc. Batch 0 is never extended by this loop: the
// handoff owns it, its line is not derived from a sprite Y at all, and the
// first mid-screen entry always starts a fresh record here.
bs_bLoop:
    lda bs_i
    cmp bs_acc
    bcs bs_batchDone

    lda bs_nb
    cmp #MAX_BATCH
    bcs bs_batchOverflow                // out of batch slots: report it
    clc
    adc bs_bbase
    sta bs_bcur                         // this batch's record, for the absorb
    tay                                 // loop, which needs it in X for INC

    clc
    lda bs_i
    adc bs_base
    tax
    lda schedY,x
    sec
    sbc #REUSE_LEAD                     // L = latest_j, the leader's own line:
    sta bs_line                         // the same raster it received before
    sta batchLine,y
    lda bs_i
    sta batchFirst,y
    lda #1
    sta batchCount,y
    inc bs_nb
    inc bs_i

// ---- absorb the following entries while L is legal for each of them --------
bs_absorb:
    lda bs_i
    cmp bs_acc
    bcs bs_batchDone

    // ONE UPDATE PER HARDWARE SLOT. Provably unreachable (see the note above);
    // kept because it is the executor's contract rather than a derived fact.
    // INC has no absolute,Y mode, so the batch record is indexed with X here.
    ldx bs_bcur
    lda batchCount,x
    cmp #MUX_SLOTS
    bcs bs_bLoop

    // earliest_k = Y of the entry that owns this slot now, plus the 21 rasters
    // it occupies. Predecessor = accepted index - MUX_SLOTS, which exists for
    // every entry this loop sees: bs_i started at MUX_SLOTS.
    sec
    lda bs_i
    sbc #MUX_SLOTS
    clc
    adc bs_base
    tay
    lda schedY,y
    clc
    adc #SPRITE_HEIGHT
    bcs bs_bLoop                        // carried past 255: cannot be <= L.
                                        // MAX_SPRITE_Y + SPRITE_HEIGHT is 247
                                        // so this cannot fire today -- it is
                                        // here so that raising MAX_SPRITE_Y
                                        // cannot silently wrap into a false
                                        // "the slot is already free"
    cmp bs_line
    bcc !joins+                         // earliest_k <  L
    bne bs_bLoop                        // earliest_k >  L: close the batch
!joins:                                 // earliest_k == L: still legal
    ldx bs_bcur
    inc batchCount,x
    inc bs_i
    jmp bs_absorb

bs_batchOverflow:
    // Unreachable while MAX_SCHED is 24 (batch 0 holds six, so at most 19
    // batches can exist), but counted rather than assumed: the same silent
    // truncation on the entry path was a real gap P2 flagged.
    lda statBatchOverflow
    cmp #$ff
    beq bs_batchDone
    inc statBatchOverflow

bs_batchDone:
    lda bs_nb
    sta statBatches
    ldx schedNext
    sta schedBatches,x

// ---- widest MID-SCREEN batch (P2) -----------------------------------------
// Batch 0 is skipped on purpose: see statMaxBatch.
    lda #0
    sta statMaxBatch
    lda #1
    sta bs_b
bs_mbLoop:
    lda bs_b
    cmp bs_nb
    bcs bs_mbDone
    clc
    adc bs_bbase
    tay
    lda batchCount,y
    cmp statMaxBatch
    bcc !notBigger+
    sta statMaxBatch
!notBigger:
    inc bs_b
    jmp bs_mbLoop
bs_mbDone:

// ---- the COMPLETE $D010 after each batch ----------------------------------
// One store per batch in the executor, no read-modify-write, no shared-register
// race. The VALUE is no longer accumulated here: bs_d010cum already holds the
// complete register contents after every accepted entry, so a batch's value is
// simply the one belonging to its LAST entry. What used to be a walk over every
// entry of every batch is now one lookup per batch.
//
// P3 made this real -- up to P2 every fixture was X < 256, so it only ever
// cleared bits. It sets a bit for an entry whose X >= 256 and clears it for one
// below, which is what makes physical slot reuse safe across an MSB change: the
// slot's bit is rewritten from the NEW owner every time, so a stale bit from the
// previous logical owner cannot survive.
    lda #0
    sta bs_b
bs_dLoop:
    lda bs_b
    cmp bs_nb
    bcs bs_dDone
    clc
    adc bs_bbase
    tay
    lda batchFirst,y
    clc
    adc batchCount,y
    sec
    sbc #1
    tax                                 // X = last accepted entry of this batch
    lda bs_d010cum,x
    sta batchD010,y
    inc bs_b
    jmp bs_dLoop
bs_dDone:
    rts

// ===========================================================================
// publishSchedule — the ONLY handover point. One byte, atomic.
// ===========================================================================
publishSchedule:
    lda #1
    sta schedPending
    rts

// --- builder locals (main thread only; the executor never touches these) ----
bs_base:      .byte 0
bs_bbase:     .byte 0
bs_pos:       .byte 0                  // sorted-list position being scanned
bs_id:        .byte 0                  // the logical ID it dereferences to
bs_acc:       .byte 0
bs_i:         .byte 0
bs_n:         .byte 0
bs_b:         .byte 0
bs_nb:        .byte 0
bs_y:         .byte 0
bs_line:      .byte 0                  // the open batch's chosen raster
bs_bcur:      .byte 0                  // the open batch's record index
bs_enable:    .byte 0
bs_d010:      .byte 0
bs_slot:      .byte 0                  // P4: the slot just assigned, so the
                                       // enable/$D010 accumulators can index by
                                       // it without re-reading schedSlot
// The complete $D010 after each accepted entry, indexed by ACCEPTED index.
// Builder scratch: written and read within one build, so it needs no double
// buffering.
bs_d010cum:   .fill MAX_SCHED, 0
bs_slotcycle: .byte 0

bitMask:      .byte $01,$02,$04,$08,$10,$20,$40,$80
bitMaskInv:   .byte $fe,$fd,$fb,$f7,$ef,$df,$bf,$7f

// ===========================================================================
// The executor. Consumes CURRENT only.
// ===========================================================================
// MOVED from $1500. The two aperture split phases and their instrumentation
// grew the executor past $1800, where the fixture tables live, and
// KickAssembler caught the overlap. $2c00 is the documented free region
// between screen page B and the blank charset (see the memory map in
// main.asm) and leaves 3 KB of room. Nothing ever points the VIC at it: it is
// code, and sprite pointers only ever hold $80..$8f.
* = $2c00 "raster executor"

irqHandler:
    pha
    txa
    pha
    tya
    pha
    lda #$01
    sta $d019                           // acknowledge the raster IRQ

    // Four phases share this entry. Every far target goes through an absolute
    // jmp: the old `bne exBatch` was already three bytes past a relative
    // branch's reach with three phases, and KickAssembler was right to refuse
    // it. Ordered by frequency -- batches are much the commonest.
    // ORDER MATTERS, AND NOT FOR SPEED. Every compare adds five cycles before
    // the handler can read $d012, and interrupt entry already costs up to 14
    // plus 19 of prologue -- so a phase far enough down this chain samples its
    // own entry raster on the NEXT line. That is a measurement artefact rather
    // than a late interrupt, but it makes the instrumentation ambiguous, and
    // "the handoff entered at 40 or 41" is not a statement worth having.
    //
    // So the two phases whose entry raster is asserted EXACTLY come first, and
    // the two that open with a raster poll come last: a poll absorbs entry
    // jitter by construction, which is what it is there for. PH_HUD was last
    // and measured [4, 5]; second, it measures [4, 4].
    lda exPhase
    bne !structural+                    // PH_BATCH is 0: the hot path is three
    jmp exBatch                         // instructions and eight cycles
!structural:
    cmp #PH_HANDOFF
    bne !notHandoff+
    jmp exHandoff
!notHandoff:
    cmp #PH_HUD
    bne !notHud+
    jmp exHud
!notHud:
    cmp #PH_FRAME
    bne !notFrame+
    jmp exFrame
!notFrame:
    cmp #PH_TOP
    bne !bottom+
    jmp exTop
!bottom:
    jmp exBottom                        // PH_BOTTOM: polls to 248 anyway

// ---- frame boundary: ONE transaction, then run batch 0 --------------------
// Everything that decides what this displayed frame IS happens here and only
// here: screen page, fine scroll, pointer-table destination, sprite schedule.
// Nothing downstream re-decides any of it, and no batch consults the scroller.
exFrame:
    lda $d012
    sta frameEntryLine                  // sampled at ENTRY: the diagnostics at
                                        // the end of this handler run ~2 raster
                                        // lines later, which would make a
                                        // frame-boundary flip look mid-frame
    lda framePending
    beq !noFrameSwap+
    lda #0
    sta framePending
    lda frameCurrent                    // swap CURRENT <-> NEXT
    ldx frameNext
    stx frameCurrent
    sta frameNext
!noFrameSwap:
    ldx frameCurrent
    lda frameD011,x
    sta $d011                           // fine scroll; RSEL=0, DEN=1, RST8=0
    lda frameD018B,x                    // the newly adopted page, BLANK charset
exSetD018:
    sta $d018                           // THE page decision for the whole frame.
                                        // Raster 250 is below the aperture, so
                                        // the charset half is blank here and
                                        // exTop switches it to real at line 55.
                                        // The VM half is decided ONLY here, by
                                        // this instruction; exTop and exBottom
                                        // both reload it from the same record
                                        // and can never name a different page.
    lda framePtrHi,x
    sta exPtrStore + 2                  // THE pointer-table destination, decided
    sta huPtrStore + 2                  // ONCE per frame from the frame record
    sta plPtr0Store + 2                 // and patched into every instruction
    sta plPtr1Store + 2                 // that writes a pointer -- the batch
                                        // executor's, the HUD's and the
                                        // player's two. Four stores,
                                        // one source, one decision: neither
                                        // phase can choose a page, and they
                                        // cannot disagree about which one was
                                        // adopted. PTR_A and PTR_B share the
                                        // low byte $f8, so a single byte selects
                                        // the destination.
    lda framePage,x
    sta curPage

    lda #0
    sta lateRun                         // maxLateRun is per-frame

    jsr frameDiagnostics

    lda schedPending
    beq !noSwap+
    lda #0
    sta schedPending
    lda schedCurrent                    // swap CURRENT <-> NEXT
    ldx schedNext
    stx schedCurrent
    sta schedNext
!noSwap:
    // cache the buffer bases once per frame
    lda #0
    ldx schedCurrent
    beq !zero+
    lda #MAX_SCHED
!zero:
    sta curBase
    lda #0
    cpx #0
    beq !zero2+
    lda #MAX_BATCH
!zero2:
    sta curBatchBase

    // NOTHING IS ENABLED ACROSS THE VERTICAL BLANK.
    //
    // Raster 250 is now adoption and nothing else: no sprite register is
    // programmed here and batch 0 has moved to the handoff at raster 40. The
    // slots are disabled on the way out for two reasons that will both matter
    // when the HUD arrives -- a HUD that owns HW2-HW7 must not inherit last
    // frame's gameplay geometry, and an enabled slot whose Y is still last
    // frame's would fetch during the blank. It also makes the 8-bit Y-compare
    // ghost at Y+256 (PAL lines 256..311) structurally impossible rather than
    // merely avoided by the Y bound.
    lda #0
    sta $d015

    ldx #PH_HUD
    stx exPhase
    lda #HUD_IRQ_LINE
    jmp exArm

// ===========================================================================
// exHud — the static top-border HUD owns HW2-HW7.
// ===========================================================================
// THE HUD'S ONLY WRITER, and the mirror image of the handoff below: it takes
// the six multiplexed slots, and forty rasters later the handoff takes them
// back. Both write every register the other might have dirtied, unconditionally
// and in full, so neither inherits anything.
//
// HW0 and HW1 are untouched here and stay reserved for the player base and
// overlay. The HUD's $d015 names HW2..HW7 and nothing else, so enabling the HUD
// cannot switch on a slot it does not own.
//
// WHAT THIS PHASE MAY NOT DO is set $d017. Y expansion doubles a sprite's
// height and its DMA span, so a Y-expanded HUD at Y=18 would fetch until line
// 59 -- through the raster-40 handoff and into the aperture. It is written to
// zero here, explicitly, rather than left alone.
//
// $d025/$d026 are not written because they cannot be read: $d01c is forced to
// zero, so every HUD sprite is hires. The HUD deliberately DOES dirty $d01b and
// $d01d (see hud.asm), which is what makes the handoff's restoration a real
// test rather than a vacuous one -- if the handoff forgot either register,
// gameplay would inherit "behind graphics" and a double-width sprite.
//
// Pointers go through huPtrStore, whose operand high byte exFrame patched from
// the SAME frame record that decided $d018. The HUD therefore writes into the
// page actually being displayed, and a page flip cannot leave it writing the
// one that is not.
exHud:
    lda $d012
    cmp hudEntryMax
    bcc !notMax+
    sta hudEntryMax
!notMax:
    cmp hudEntryMin
    bcs !notMin+
    sta hudEntryMin
!notMin:

    // Six slots, HW2..HW7, from the tables in hud.asm. Y indexes the VIC
    // register file (slot or slot*2), X walks the tables.
    ldx #HUD_SPRITE_COUNT - 1
!slot:
    ldy hudSlot2,x
    lda hudXLo,x
    sta $d000,y
    lda hudYPos,x
    sta $d001,y
    ldy hudSlot,x
    lda hudCol,x
    sta $d027,y
    lda hudPtrLive,x                    // RAM, not a constant table: lives and
                                        // upgrade "render" by writing one byte
                                        // of it, and a single byte cannot be
                                        // read half-written
huPtrStore:
    sta PTR_A,y                         // high byte patched once per frame by
                                        // exFrame, from the adopted page
    dex
    bpl !slot-

    // ---- HW0 and HW1: the player, from the ADOPTED block ------------------
    //
    // WHY HERE AND NOT AT THE HANDOFF. Raster 4 is the quietest line in the
    // frame -- far below the badline range, and $d015 is still zero so there is
    // no sprite DMA anywhere -- and it has fourteen lines in hand before the
    // HUD's own first fetch at line 17. The handoff at raster 40 has TWO: it
    // exits as late as raster 51 against TOP_ARM_LINE 53, and that margin is
    // the tightest in the engine. Sixty-eight cycles of player programming
    // belongs in the phase that has a line to spare, not the one that does not.
    //
    // It is also programmed ONCE per frame and then left alone: no batch, no
    // phase and no main-thread routine touches $d000-$d003, $d027/$d028 or the
    // two pointer table entries again before the next raster 4. The player's
    // presentation is therefore immutable for the whole displayed frame in the
    // strongest sense -- not merely unmodified, but unreachable.
    ldx schedCurrent
    lda schedPlyX0,x
    sta $d000
    lda schedPlyY0,x
    sta $d001
    lda schedPlyCol0,x
    sta $d027
    lda schedPlyPtr0,x
plPtr0Store:
    sta PTR_A + 0                       // high byte patched by exFrame, from the
                                        // same frame record that chose $d018
    lda schedPlyX1,x
    sta $d002
    lda schedPlyY1,x
    sta $d003
    lda schedPlyCol1,x
    sta $d028
    lda schedPlyPtr1,x
plPtr1Store:
    sta PTR_A + 1                       // PTR_A+1 and PTR_B+1 share the low byte
                                        // $f9, exactly as PTR_A/PTR_B share $f8

    lda schedPlyD010,x                  // complete value, one store, no RMW:
    ora #HUD_D010                       // the HUD's bit 7 and the player's bits
    sta $d010                           // 0/1, composed in a register
    lda #$00
    sta $d017                           // NEVER non-zero: see above
    sta $d01c                           // hires, so $d025/$d026 are unreachable
    lda #HUD_D01B
    sta $d01b
    lda #HUD_D01D
    sta $d01d

    // Enabled LAST, once every slot it names is fully programmed. The HUD's
    // sprites are not fetched until line 18 either way, but the ordering is the
    // same rule the handoff follows and is worth keeping identical in both.
    lda schedPlyEnable,x
    ora #HUD_ENABLE
    sta $d015

    lda $d012                           // where the HUD finished: the margin to
    cmp hudExitMax                      // its own first fetch at line 18
    bcc !notExit+
    sta hudExitMax
!notExit:

    ldx #PH_HANDOFF
    stx exPhase
    lda #HANDOFF_LINE
    jmp exArm

// ===========================================================================
// exHandoff — the HUD -> gameplay ownership transfer, and batch 0.
// ===========================================================================
// THE SOLE OWNER-TRANSFER POINT. Written as though its predecessor were a HUD
// that had been free to dirty every shared register, because that is exactly
// what it will be: the HUD phase goes in the top border above this line, and
// nothing about this code should have to change when it does.
//
// The rule that makes a handoff safe is that it writes every register whose
// previous owner might have touched it, UNCONDITIONALLY. Nothing is inherited
// and nothing is written only "if it looks wrong" -- that class of assumption
// produced the P4 flicker and the FIX 16 corruption.
//
// Per-slot state (X, Y, colour, pointer, and the complete $d010) is batch 0's
// job and is executed below by the ordinary batch executor, so there is one
// code path for programming a slot and not two. The registers below are the
// GLOBAL sprite modes, which no batch writes.
//
// $d025/$d026, the shared multicolour registers, are deliberately NOT written.
// $d01c is forced to 0 here, so every gameplay sprite is hires and cannot read
// them; they are unreachable rather than merely unused. If gameplay ever
// enables multicolour for a slot, they join this list on the same day.
//
// $d015 is NOT written here either -- it is written after batch 0 has finished
// programming the slots (see the arming tail). Enabling a slot before its Y is
// correct would let the VIC fetch one line from last frame's geometry.
exHandoff:
    lda $d012
    cmp handoffEntryMax
    bcc !notMax+
    sta handoffEntryMax
!notMax:
    cmp handoffEntryMin
    bcs !notMin+
    sta handoffEntryMin
!notMin:

    lda #$00
    sta $d017                           // no Y expand: the reuse rule sizes a
                                        // slot's lifetime at 21 lines
    sta $d01b                           // sprites in front of the playfield
    sta $d01c                           // all gameplay sprites hires
    sta $d01d                           // no X expand: X is a 9-bit position

    lda #0
    sta curBatch                        // batch 0 is THIS phase's to run, and
                                        // saying so costs four cycles and
                                        // removes a cross-phase assumption

    // A schedule with no accepted sprites still has to hand the frame on.
    // Falling into the batch executor would take the no-more-batches exit
    // straight to the bottom phase and skip the top aperture split entirely,
    // which would leave the blank charset selected for the whole frame -- a
    // black screen. Arm the split explicitly instead.
    ldx schedCurrent
    lda schedBatches,x
    bne exBatch                         // the normal case: run batch 0
    lda schedEnable,x                   // NO GAMEPLAY SPRITES. Not "nothing to
    sta $d015                           // enable": schedEnable still carries the
                                        // player's two bits, and writing zero
                                        // here would switch the player off for
                                        // every frame the mux pool is empty --
                                        // which, until enemies arrive, is every
                                        // frame there is.

    lda $d012                           // AND THE HANDOFF IS COMPLETE HERE.
    cmp handoffExitMax                  // Without this the production path --
    bcc !notMax+                        // which takes this exit on every frame
    sta handoffExitMax                  // until enemies exist -- would leave
!notMax:                                // handoffExitMax reading zero, and the
                                        // margin to the top split unmeasured in
                                        // the only configuration the game
                                        // actually runs in.
    ldx #PH_TOP
    stx exPhase
    lda #TOP_ARM_LINE
    jmp exArm

// ---- batch executor --------------------------------------------------------
exBatch:
    lda curBatch
    ldx schedCurrent
    cmp schedBatches,x
    bcc exBatchRun                      // more batches this frame
    jmp exEndFrame                      // Inverted, and out of line, purely
                                        // because the P2 batch-size histogram
                                        // pushed exEndFrame out of branch
                                        // range. Costs the common path one
                                        // cycle per batch (a taken bcc rather
                                        // than an untaken bcs) and the rare
                                        // end-of-frame path three.
exBatchRun:

    clc
    adc curBatchBase
    tay
    lda batchFirst,y
    sta ex_i
    lda batchCount,y
    sta ex_n
    sta ex_n0                           // P2: kept for the executed-size
                                        // histogram; ex_n is destroyed below
    lda batchD010,y
    sta ex_d010

exEntry:
    lda ex_n
    beq exEntriesDone
    clc
    lda ex_i
    adc curBase
    tay

    ldx schedSlot2,y                    // precomputed slot*2
    lda schedY,y
    sta $d001,x                         // Y FIRST: it is the only timing-critical write
    lda schedX,y
    sta $d000,x
    ldx schedSlot,y
    lda schedCol,y
    sta $d027,x
    lda schedPtr,y
exPtrStore:
    sta PTR_A,x                         // P1: the operand HIGH BYTE is patched
                                        // once per frame by exFrame. PTR_A and
                                        // PTR_B share the low byte ($f8), so a
                                        // single byte selects the destination
                                        // and a batch can never choose one.

    inc ex_i
    dec ex_n
    jmp exEntry

exEntriesDone:
    lda ex_d010
    sta $d010                           // complete value, one store, no RMW

// P2 TIMING PROBE. A label, nothing else: it costs zero cycles and generates
// no code, and it marks the instant every VIC register this batch owns has
// been written -- the Y values, X values, colours, pointers and $d010.
//
// THIS is the instant the reuse deadline applies to. Everything below is
// bookkeeping and re-arming; the beam does not care about any of it. Measuring
// the whole handler (irqHandler -> exDone) and calling that the batch cost
// overstates it, and that overstatement grows every time a diagnostic counter
// is added. tests/test_p2.py traces this point and exDone separately and
// reports both, so the margin against REUSE_LEAD is stated against the write
// that actually has to beat the raster.
exWritesDone:

    inc curBatch
    inc batchCounter
    bne !counted+
    inc batchCounter + 1
    bne !counted+
    inc batchCounter + 2
!counted:

    // P2: record the size of the batch just EXECUTED. curBatch has already
    // been incremented, so the batch that just ran was curBatch-1; a value of
    // 1 here means that was batch 0, the frame batch, which is excluded.
    lda curBatch
    cmp #1
    beq !noHist+
    lda ex_n0
    asl                                 // two bytes per size
    tax
    inc batchSizeHist,x
    bne !noHist+
    inc batchSizeHist + 1,x
!noHist:

// ---- arm the next event ----------------------------------------------------
    // Batch 0 has just run (curBatch is 1): the next structural event is the
    // TOP aperture split, not batch 1. It has to come first -- it is at raster
    // 52/55 and every mid-screen batch line is far below it, because the reuse
    // rule puts accepted entry 6 at least MIN_REUSE_GAP below entry 0.
    lda curBatch
    cmp #1
    bne exArmNextBatch

    // Batch 0 has just programmed HW2..HW7, so the slots may now be enabled.
    // THIS is the handoff's final act and the instant gameplay owns the mux.
    // After batch 0, never before it: an enable ahead of the Y write would let
    // the VIC fetch a line from the previous frame's geometry.
    ldx schedCurrent
    lda schedEnable,x
    sta $d015                           // one writer, once per frame

    lda $d012                           // the handoff is complete HERE
    cmp handoffExitMax
    bcc !notMax+
    sta handoffExitMax
!notMax:

    ldx #PH_TOP
    stx exPhase
    lda #TOP_ARM_LINE
    jmp exArm

exArmNextBatch:
    ldx schedCurrent
    cmp schedBatches,x
    bcc !more+
    jmp exArmBottom                     // out of relative branch range
!more:
    clc
    adc curBatchBase
    tay
    ldx #PH_BATCH
    stx exPhase
    lda batchLine,y
    jmp exArm

// ===========================================================================
// exBottom — hold the vertical border open, then close the aperture at 248.
// ===========================================================================
// Two jobs, one poll.
//
// 1. THE BORDER. The vertical border flip-flop is only ever set by the RSEL
//    comparison in cycle 63 of line 247 (RSEL=0) or 251 (RSEL=1). Arrive with
//    RSEL=0, switch to 1 before 247 so that check looks for 251 and misses,
//    then back to 0 before 251 so that check looks for 247, which has gone.
//    The flip-flop is never set, so the border never closes -- which is what
//    the future top-border HUD needs. UNCHANGED mechanism; the arming line is
//    still 243, because 246 was tried during the border work and measured NOT
//    to open reliably.
//
// 2. THE APERTURE. At line 248 the charset switches to blank, so the terrain
//    ends at 247 and everything below is $d021. The write must beat line 248's
//    first g-access in cycle 15. Line 248 can never be a badline (the range is
//    48..247), so the only thing that can steal cycles 0..9 is sprite DMA for
//    slots 3..7, which needs a sprite still active there -- Y >= 228. No
//    fixture has one; a MAX_SPRITE_Y admission rule belongs to the handoff
//    slice, and botSplitMin/Max below is what would catch it meanwhile.
//
// BOTH $d011 writes take the COMPLETE byte from the CURRENT frame record.
// The old code did `lda $d011 / ora #$08 / sta $d011`, and bit 7 of a $d011
// READ is raster bit 8 while bit 7 of a WRITE is the raster-compare high bit:
// a read-modify-write above raster 255 arms compare line 250+256 and the frame
// IRQ never fires again. It happened to be harmless at 243. It is not a thing
// to leave in place.
exBottom:
    ldx frameCurrent
    lda frameD011,x
    ora #$08                            // RSEL=1: the close at 247 misses
    sta $d011

    // THE VALUE IS LOADED BEFORE THE POLL, and between detecting the line and
    // storing it there is nothing but the untaken branch. That is the whole
    // trick and it is worth stating: the first draft loaded $d018's value
    // after the poll, which put `jmp`, `ldx` and `lda abs,x` -- 13 cycles --
    // in front of the store, and the top split measured as landing on raster
    // 56 instead of 55. Detection lands in cycles 0..6, `bne` not taken costs
    // 2 and `sta abs` writes on its 4th cycle, so the write lands in cycles
    // 6..12, comfortably before the line's first g-access in cycle 15.
    lda frameD018B,x                    // blank charset, same page
    ldx #BORDER_D021                    // and the open border's own background,
                                        // loaded before the poll for the same
                                        // reason the charset is. X stops being
                                        // frameCurrent here and is reloaded
                                        // after the split.

    // Never spin a whole frame with I set. Entered at 243 this cannot fire;
    // if a chain ever pushed the phase past 248 it would, and a hang inside
    // the handler is the one failure that looks like a dead machine.
    ldy $d012
    cpy #BOT_SPLIT_LINE
    bcs !split+
    ldy #BOT_SPLIT_LINE
!wait:
    cpy $d012                           // 7-cycle loop
    bne !wait-
!split:
    sta $d018
    stx $d021                           // THE BOTTOM HALF OF THE BLACK BORDER.
                                        // Everything from here to the end of
                                        // the frame is idle or blank-charset
                                        // and therefore bit pair 00. The store
                                        // is SECOND because its deadline is
                                        // later: $d018 must beat the line's
                                        // first g-access in cycle 15, while
                                        // $d021 only has to beat the first
                                        // visible playfield pixel, which the
                                        // main border flip-flop uncovers in
                                        // cycle 17. Detection lands in cycles
                                        // 0..6, so $d018 writes in 6..12 and
                                        // this writes in 10..16. Measured, and
                                        // recorded beside the constant it
                                        // justifies, in the migration report.

    ldx frameCurrent                    // X carried the colour through the
                                        // split; the frame record needs it back
    lda frameD011,x                     // RSEL=0: the close at 251 misses too
    sta $d011

    lda $d012                           // where the split ACTUALLY landed
    cmp #BOT_SPLIT_LINE
    beq !onTime+
    ldy edgeLate
    cpy #$ff
    beq !onTime+
    inc edgeLate
!onTime:
    cmp botSplitMax
    bcc !notMax+
    sta botSplitMax
!notMax:
    cmp botSplitMin
    bcs !notMin+
    sta botSplitMin
!notMin:

    ldx #PH_FRAME
    stx exPhase
    lda #FRAME_IRQ_LINE                 // now the frame transaction, at 250
    jmp exArm

// ===========================================================================
// exTop — open the aperture at 248's mirror: the real charset from line 55.
// ===========================================================================
// Armed at TOP_ARM_LINE so the poll is already running before line 55 whatever
// the fine scroll is. Exactly one of lines 48..55 is a badline -- the one with
// raster & 7 == YSCROLL -- and on it the CPU is stalled from cycle 12 to 54.
// Arming at 52 means that stall can cost at most the arm line itself: the
// handler still reaches the poll with more than a line in hand, and the poll
// simply rides through any later stall and resumes.
//
// The store lands in cycles 6..12 of line 55, before the first g-access in
// cycle 15. Sprite DMA for slots 3..7 owns cycles 0..9 of a line, but only for
// a sprite already active there, i.e. Y <= 54; MAXCAP's Y=50 sprite is in slot
// 2, which is fetched at the END of line 54 instead, and every other fixture
// starts at Y >= 55. topSplitMin/Max is the standing proof.
//
// When YSCROLL = 7 none of this matters -- row 0 begins AT 55 and lines 48..54
// are idle, which the VIC renders from $3fff regardless of the charset -- but
// the same code runs for every phase because a special case here would be one
// more thing to get wrong for no measurable saving.
exTop:
    ldx frameCurrent

    // WHICH LINE TO SPLIT ON DEPENDS ON THE FINE SCROLL, and this is the one
    // place in the aperture where that is true.
    //
    // At YSCROLL = 7 line 55 is itself a badline: the CPU is stalled from its
    // cycle 12 to 54. The poll then has only cycles 0..11 to detect the line
    // and store, and sprite DMA -- hardware sprites 0..2 are fetched in cycles
    // 57..62 of the PREVIOUS line -- can push its first sample past 12. The
    // store then waits out the whole badline and lands around cycle 61, after
    // every g-access, so raster 55 renders from the BLANK charset: one missing
    // terrain line, one frame, roughly 1% of frames. Measured, not feared --
    // with $d015 forced to 0 and every IRQ and batch otherwise identical the
    // same build never missed once in 8,158 frames, and with DMA back on it
    // missed 72 in 7,150.
    //
    // At YSCROLL = 7, though, the split does not need line 55 at all: the first
    // badline of the frame IS 55, so lines 48..54 are in IDLE state and the VIC
    // renders them from $3fff whatever the charset says. Splitting on 54 is
    // therefore invisible, and line 54 is never a badline at this phase -- so
    // instead of a dozen cycles the store has a whole line of slack.
    //
    // For every other phase line 55 is not a badline and the poll keeps its
    // full window; the only remaining hazard is a sprite in HW3..HW7 already
    // active at line 55 (Y <= 54), which would own cycles 0..9. No fixture has
    // one -- MAXCAP's Y=50 entry is in HW2, fetched at the end of line 54 --
    // and the MIN_SPRITE_Y admission rule in the handoff slice removes the
    // possibility by construction. edgeLate is what would catch it meanwhile.
    //
    // ---------------------------------------------------------------------
    // AND $D021 SPLITS HERE TOO, BUT NOT ALWAYS ON THE SAME LINE.
    //
    // The open border is black because $d021 is black, and the playfield is
    // the level's colour because $d021 is that colour -- so the top edge of
    // the black border is wherever $d021 changes, and that is raster 55 for
    // EVERY fine-scroll phase. It has to be: a boundary that moved with
    // YSCROLL would climb seven pixels and jump back, which is precisely the
    // 6.25 Hz edge pop the guard rows were removed to kill.
    //
    // At every phase but 7 the two stores are one line apart from nothing --
    // both belong on 55 -- and they go out back to back, $d018 first because
    // its deadline (the g-access in cycle 15) is earlier than $d021's (the
    // first visible playfield pixel, cycle 17).
    //
    // At YSCROLL = 7 they genuinely separate. $d018 splits on 54 to dodge the
    // badline, and it can: lines 48..54 are IDLE at that phase and the VIC
    // renders them from $3fff whatever the charset says. $D021 CANNOT FOLLOW
    // IT THERE. Idle lines are drawn in $d021, so a background store on 54
    // would paint line 54 grey at one phase in eight and black at the other
    // seven -- the flicker, moved from the charset to the colour. So the
    // background gets its own short poll to 55 on that path alone, which lands
    // it in cycles 6..12 with the whole of line 54 in hand beforehand.
    //
    // The two paths are written out rather than merged because the merge point
    // is inside the deadline: a single `cpy/beq` to pick between them after the
    // charset store costs five cycles, and five cycles is the entire margin.
    lda frameD011,x
    and #$07
    cmp #$07
    beq exTopPhase7

    // ---- YSCROLL 0..6: charset and background both land on line 55 --------
    ldy #TOP_SPLIT_LINE
    sty topTarget
    lda frameD018,x                     // REAL charset, the page exFrame chose.
                                        // Loaded BEFORE the poll: see exBottom.
    ldx #APERTURE_D021                  // the playfield background, likewise
    cpy $d012                           // already there, or already past it?
    beq !split+
    bcc !split+
!wait:
    cpy $d012
    bne !wait-
!split:
    sta $d018                           // writes in cycles 6..12
    stx $d021                           // writes in cycles 10..16
    lda $d012                           // the beam has not left the split line
    jmp exTopLanded

    // ---- YSCROLL 7: charset on 54, background on 55 -----------------------
exTopPhase7:
    ldy #TOP_SPLIT_LINE - 1
    sty topTarget
    lda frameD018,x
    cpy $d012
    beq !split+
    bcc !split+
!wait:
    cpy $d012
    bne !wait-
!split:
    sta $d018                           // line 54 is idle at this phase: this
                                        // store has a whole line of slack, and
                                        // nothing it selects is displayed here
    lda $d012                           // record the landing NOW, before the
    sta topLanded                       // second poll moves the beam to 55
    ldx #APERTURE_D021
    ldy #TOP_SPLIT_LINE
    cpy $d012                           // NEVER SPIN A WHOLE FRAME WITH I SET:
    beq !at55+                          // if 55 has already gone, store at once
    bcc !at55+
!wait55:
    cpy $d012
    bne !wait55-
!at55:
    stx $d021
    lda topLanded

exTopLanded:
    cmp topTarget
    beq !onTime+
    ldy edgeLate
    cpy #$ff
    beq !onTime+
    inc edgeLate
!onTime:
    cmp topSplitMax
    bcc !notMax+
    sta topSplitMax
!notMax:
    cmp topSplitMin
    bcs !notMin+
    sta topSplitMin
!notMin:

    // Hand on to the mux. curBatch is 1 -- batch 0 ran at 250 -- so this arms
    // the first MID-SCREEN batch, or the bottom split if there is none.
    lda curBatch
    ldx schedCurrent
    cmp schedBatches,x
    bcs exArmBottom
    clc
    adc curBatchBase
    tay
    ldx #PH_BATCH
    stx exPhase
    lda batchLine,y
    jmp exArm

exArmBottom:
    lda #0
    sta curBatch
    ldx #PH_BOTTOM
    stx exPhase
    lda #BORDER_OPEN_LINE
    jmp exArm

exEndFrame:
    jmp exArmBottom                     // out of branch range from exBatch

exArm:
    // Acknowledge BEFORE arming, not only at entry.
    //
    // The handler acknowledges $d019 once, on the way in. Everything armed
    // after that point can raise a raster IRQ while this handler is STILL
    // RUNNING -- a batch costs about five raster lines, and MAXCAP's batches
    // are armed six lines apart, so the beam routinely crosses a freshly
    // armed line before the rti. That latch is never acknowledged, so the rti
    // re-enters the handler immediately.
    //
    // Mid-frame that is merely a batch running a line late. At the END of the
    // frame it is destructive: exArmFrame has already set curBatch to 0, so
    // the spurious re-entry runs exFrame -- $d011, $d018, the pointer-table
    // destination, $d015 and batch 0 -- at raster 182 instead of 250, in the
    // middle of the visible display. Slots 2..7 are reprogrammed with the
    // sprites at the TOP of the frame, whose Y values the beam passed long
    // ago, so they never appear; exLate then chases every batch whose line is
    // behind the beam, and that frame loses every sprite above it.
    //
    // Measured on FIXTURE 16 before this fix: a raster IRQ was still latched
    // at the rti on 68.4% of handler exits, the frame IRQ was entered at
    // raster 182/183 on 1% of frames, and maxLateRun reached 13 -- exactly
    // the thirteen sprites missing from a corrupted frame. The control
    // fixture, whose two batches are far apart, never latched once in 500.
    //
    // Acknowledging here discards anything latched earlier in this handler.
    // It cannot discard a legitimate one: if the beam crossed the armed line
    // before this store the cmp below sees it and chases the batch now, and
    // if it crosses after, the VIC latches again and the rti services it.
    // X holds schedCurrent, which is dead from here on, so A survives to be
    // stored and compared.
    //
    // The acknowledge happens BEFORE the arm, which is what makes it safe.
    // $d012 still holds the line this handler was entered for, and the beam is
    // already past it, so nothing can latch between the two stores. Every
    // latch after the arm is a genuine crossing of the NEW line and is left
    // alone for the rti to service.
    ldx #$01
    stx $d019
    sta $d012

    // Late-IRQ recovery, the historical pattern: if the beam is already at or
    // past the line we just armed, the IRQ would not fire until the next frame.
    // Run the batch immediately instead.
    //
    // EQUALITY COUNTS AS LATE. The VIC raises a raster IRQ when the counter
    // BECOMES equal to $d012, at the start of the line; writing $d012 with the
    // line the beam is already on therefore raises nothing, ever. Treating
    // equal as on-time drops that batch for the whole frame -- silently, with
    // statLate reading zero, because nothing was chased and nothing complained.
    cmp $d012
    bcc exLate
    beq exLate
    jmp exDone
exLate:
    // STRUCTURAL PHASES ARE NOT CHASED -- with one exception that is the
    // difference between a blemish and a black screen.
    //
    // Running the frame transaction early is FIX 16 and must never happen, and
    // the handoff arms a line the beam has already passed on purpose (40, from
    // raster ~254), so for those the late path correctly does nothing and the
    // VIC raises the interrupt on the next frame's line.
    //
    // THE TOP SPLIT IS DIFFERENT. It is armed by the handoff, which finishes
    // only a couple of rasters earlier; if it were ever armed late the
    // interrupt would not fire at all this frame, the aperture would never
    // switch to the real charset, and the ENTIRE screen would stay blank for a
    // frame. Running it immediately instead costs at worst a few blank
    // characters on line 55 -- exTop's own guard stores at once when the line
    // has gone -- and edgeLate records that it happened.
    lda exPhase
    beq !chaseBatch+                    // PH_BATCH = 0
    cmp #PH_TOP
    beq !lateTop+
    jmp exDone
!lateTop:
    jmp exTop
!chaseBatch:
    lda statLate
    cmp #$ff
    beq !saturated+
    inc statLate
!saturated:
    inc lateRun
    lda lateRun
    cmp maxLateRun
    bcc !noRecord+
    sta maxLateRun
!noRecord:
    jmp exBatch

exDone:
    pla
    tay
    pla
    tax
    pla
    rti

ex_i:    .byte 0
ex_n:    .byte 0
ex_n0:   .byte 0                        // P2: the batch's entry count, SAVED,
                                        // because ex_n is counted down to zero
                                        // by the entry loop
ex_d010: .byte 0

// P2 — proof of what the executor ACTUALLY ran, not what the builder planned.
// Sixteen bits per size, indexed by entry count 0..MUX_SLOTS, counting
// MID-SCREEN batches only. A schedule containing a six-entry batch proves
// nothing on its own; this counts the times one was really executed, over
// millions of frames rather than over a sampled trace.
//
// Updated with the other per-batch bookkeeping AFTER exEntriesDone, so it
// cannot delay a single sprite register write. The deadline that matters is
// "every sprite Y written before the beam reaches Yc", and exEntriesDone is
// exactly that instant -- which is why the timing harness traces it as its own
// point rather than using the handler's total cost.
batchSizeHist: .fill 2 * (MUX_SLOTS + 1), 0

// The executor must not grow into the HUD sprite bitmaps at $3200, and through
// them into the blank charset at $3800. The VIC really does fetch from both, so
// code spilling into either would be DISPLAYED -- as sprites in the first case
// and as characters in the second.
//
// THE GUARD IS AT THE END OF THE SEGMENT, NOT HERE. It used to sit at this
// point, which is before frameDiagnostics and installRenderer -- roughly 200
// bytes of the segment it was guarding. The measured end of the executor is
// only about 500 bytes below $3200, so that is not a rounding error. See the
// bottom of this file.

// ===========================================================================
// frameDiagnostics — frame IRQ only, and deliberately not on the critical path
// of any mid-screen batch.
//
// The frame batch fires at raster 250 and its sprites are not displayed until
// raster 55 of the NEXT frame: about 117 raster lines, ~7,370 cycles. THAT is
// the deadline that applies here. REUSE_LEAD sizes mid-screen slot reuse and
// nothing else; P0 conflated the two because it only ever measured one batch.
// tests/test_p1.py asserts them separately and reports both.
// ===========================================================================
frameDiagnostics:
    inc frameCounter
    bne !noCarry+
    inc frameCounter + 1
!noCarry:

    // Frames actually displayed per page — the proof that both matrices live.
    lda curPage
    bne !countB+
    inc pageAFrames
    bne !pageDone+
    inc pageAFrames + 1
    jmp !pageDone+
!countB:
    inc pageBFrames
    bne !pageDone+
    inc pageBFrames + 1
!pageDone:

    // Flip detection. True one frame in eight, so the extra work is amortised.
    lda curPage
    cmp prevPage
    beq !noFlip+
    sta prevPage
    inc flipCount
    bne !flipCounted+
    inc flipCount + 1
!flipCounted:
    lda frameEntryLine
    sta lastFlipLine                    // must always read FRAME_IRQ_LINE: a
                                        // page flip is a frame-boundary event
                                        // or it is a bug
    cmp flipLineMax
    bcc !notMax+
    sta flipLineMax
!notMax:
    cmp flipLineMin
    bcs !notMin+
    sta flipLineMin
!notMin:
    lda curPage
    beq !toA+
    inc transAB
    bne !noFlip+
    inc transAB + 1
    jmp !noFlip+
!toA:
    inc transBA
    bne !noFlip+
    inc transBA + 1
!noFlip:

    // Self-check 1: did $d018 actually take the value we published?
    ldx frameCurrent
    lda $d018
    eor frameD018B,x                    // exFrame writes the BLANK value; the
                                        // real one appears only after exTop
    and #$fe                            // $d018 bit 0 is unused and reads back
                                        // as 1 whatever we wrote; measured, not
                                        // assumed -- it made this very check
                                        // fire on every single frame
    beq !pageOk+
    lda statPageMismatch
    cmp #$ff
    beq !pageOk+
    inc statPageMismatch
!pageOk:

    // Self-check 2: does the pointer destination belong to the page $d018 is
    // ACTUALLY displaying? Derived from the register rather than from our own
    // intention, so it cannot agree with itself by construction.
    lda $d018
    and #$f0
    cmp #(D018_A & $f0)
    bne !expectB+
    lda #>PTR_A
    jmp !comparePtr+
!expectB:
    lda #>PTR_B
!comparePtr:
    cmp exPtrStore + 2
    beq !ptrOk+
    lda statPtrMismatch
    cmp #$ff
    beq !ptrOk+
    inc statPtrMismatch
!ptrOk:
    rts

// ===========================================================================
// installRenderer — set up the IRQ chain. Called once from main.
// ===========================================================================
installRenderer:
    sei
    lda #$7f
    sta $dc0d                           // no CIA timer IRQs
    lda $dc0d
    lda #$35
    sta $01                             // KERNAL out: our vector at $fffe
    lda #<irqHandler
    sta $fffe
    lda #>irqHandler
    sta $ffff
    lda #$01
    sta $d01a                           // enable raster IRQ
    lda #$01
    sta $d019
    lda $d011
    and #$7f
    sta $d011                           // raster compare high bit = 0
    lda #FRAME_IRQ_LINE
    sta $d012
    lda #0
    sta curBatch
    lda #PH_FRAME                       // EXPLICIT: zero is PH_BATCH now, and
    sta exPhase                         // booting into the batch executor with
                                        // no schedule would be a fine way to
                                        // spend an afternoon. The first IRQ is
                                        // the frame transaction, which arms the
                                        // handoff.
    lda #0
    sta $d015                           // sprites off until the first frame IRQ
    cli
    rts

// ---------------------------------------------------------------------------
// SEGMENT GROWTH GUARD -- see the note above frameDiagnostics. This is the real
// end of the raster executor, and therefore the only place the check means
// anything.
// ---------------------------------------------------------------------------
.if (* > HUD_SPRITES) {
    .error "the raster executor has grown into the HUD sprite bitmaps"
}
