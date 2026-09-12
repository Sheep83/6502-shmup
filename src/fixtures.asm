// ===========================================================================
// fixtures.asm — deterministic P0 logical sprite sets
// ===========================================================================
// A fixture is just a list of Y values, pre-sorted ascending. P0 does no
// sorting on purpose: we are proving raster execution, not ordering.
//
// X, pointer and colour are derived from the LOGICAL index, so that a
// mis-assigned pointer or colour is immediately visible as "sprite showing
// numeral 7 is in sprite 3's colour" or "two sprites showing the same numeral".
//
// Expected results are stated per fixture and are asserted by tests/test_p0.py
// against an independent Python model of the builder.
// ===========================================================================

// Indirect indexed addressing REQUIRES a zero-page pointer. Putting fx_src in
// the $1800 segment silently assembled as (zp),y against an unrelated zero-page
// address and loadFixture read garbage. $fb/$fc are free on an unexpanded C64.
.const fx_src = $fb

* = $1800 "fixtures"

// P0 owns fixtures 0-4 and they are byte-for-byte unchanged: they are the P0/P1
// regression set and every earlier proof is stated against them.
// P2 appends 5-15. See docs/p2-static-y-matrix.md.
// P0 owns 0-4, P2 owns 5-15, P3 owns 16-23. Earlier fixtures are byte-for-byte
// unchanged: they are the regression set every earlier proof is stated against.
.const FIXTURE_COUNT    = 34
.const P2_FIRST_FIXTURE = 5
.const P3_FIRST_FIXTURE = 16
.const P4_FIRST_FIXTURE = 24
.const P5_FIRST_FIXTURE = 31

// Fixture kinds. A P0/P1/P2 fixture is a bare list of Y values with X, pointer
// and colour derived from the logical index; a P3 fixture is a record carrying
// a full initial position and a trajectory per sprite. Two loaders, chosen by
// this table, rather than one loader with a mode flag threaded through it.
.const FK_STATIC = 0
.const FK_MOTION = 1
// P5. A ring fixture carries no per-sprite record at all: all sixteen sprites
// share one orbit and differ only by a phase offset derived from the logical
// index. The record is four bytes of velocity, and the geometry lives in the
// generated tables.
.const FK_RING   = 2

// --- logical sprite input ---------------------------------------------------
// logCount / logY / logX / logXHi / logPtr / logCol and fixtureYOffset moved to
// src/motion.asm in P3, alongside the motion state that writes them: MAX_LOGICAL
// grew to 32, logXHi was added, and this segment had under 100 bytes spare.
// They are RAM state, not fixture constants, so they belong with the schedule
// buffers outside VIC bank 0 rather than in a table of fixture data.

// --- fixture Y tables -------------------------------------------------------
// F0: six sprites, comfortably spaced. No reuse at all.
//     expect: accepted 6, reuse 0, rejected 0, batches 1
fixture0: .byte 60, 90, 120, 150, 180, 210
fixture0End:

// F1: seven sprites. Entry 6 is the FIRST reuse and it reuses the slot of
//     entry 0 — the six-slot model. Under an eight-slot model no reuse would
//     occur here at all, which is exactly the bug this fixture guards against.
//     Y values are kept inside the visible window (~50..229): an earlier draft
//     put the seventh sprite at Y=240, in the lower border, so the one thing the
//     fixture exists to show was invisible.
//     expect: accepted 7, reuse 1, rejected 0, batches 2
fixture1: .byte 55, 82, 109, 136, 163, 190, 217
fixture1End:

// F2: fourteen sprites at a uniform 12-line pitch. Same-slot separation is
//     6 x 12 = 72, comfortably legal, so this exercises eight legal reuse
//     events and a nine-batch frame.
//     expect: accepted 14, reuse 8, rejected 0, batches 9
fixture2: .byte 55, 67, 79, 91, 103, 115, 127, 139, 151, 163, 175, 187, 199, 211
fixture2End:

// F3: eight sprites in a 2-line cluster. Entries 6 and 7 would have to share a
//     physical slot with entries 0 and 1 while those are still displaying:
//     PHYSICALLY IMPOSSIBLE. Must be rejected, and the six that fit must render
//     perfectly.
//     expect: accepted 6, reuse 0, rejUnsafe 2, rejMargin 0, batches 1
fixture3: .byte 60, 62, 64, 66, 68, 70, 72, 74
fixture3End:

// F4: the boundary fixture. Six sprites at Y 60..65, then four candidates whose
//     gap against the slot owner (entry 0, Y=60) straddles BOTH thresholds:
//       gap 20 -> UNSAFE            (< SPRITE_HEIGHT: the sprites truly overlap)
//       gap 21 -> CONSERVATIVE      (legal on hardware, inside our safety margin)
//       gap 32 -> CONSERVATIVE      (one line short of the margin)
//       gap 33 -> ACCEPTED          (== MIN_REUSE_GAP)
//     These Y values track MIN_REUSE_GAP; if REUSE_LEAD changes they must move.
//     expect: accepted 7, reuse 1, rejUnsafe 1, rejMargin 2, batches 2
fixture4: .byte 60, 61, 62, 63, 64, 65, 80, 81, 92, 93
fixture4End:

// ===========================================================================
// P2 fixtures — the static-Y stress matrix's permanent named cases.
// ===========================================================================
// GEOMETRY IS DERIVED FROM THE REUSE RULE, not chosen to look tidy.
//
// Accepted entry i reuses the slot of accepted entry i-6, so six sprites that
// all share one Y become a SIX-ENTRY MERGED BATCH only if every one of them
// clears its own predecessor by MIN_REUSE_GAP. The binding pair is the LAST
// of the six against the LAST of the leaders:
//
//     Yc - (Y0 + 5) >= MIN_REUSE_GAP   ->   Yc >= Y0 + 5 + 33  =  Y0 + 38
//
// With Y0 = 60 that is Yc = 98, and 98 is therefore two things at once: the
// smallest Yc that produces a six-entry merge, and the EXACT conservative
// boundary for the binding pair. One line lower and the batch is five entries,
// which is precisely what fixtures 6-10 step through.
//
// All six share a batch line of Yc - REUSE_LEAD = 86, which is what makes them
// merge; batch 0 still programmes entries 0-5 at raster 250.
.const P2_LEAD_Y = 60                   // first of the six leaders

// MEASURED, from the P2 vertical sweep, not chosen. Offset 8 puts the merged
// batch on raster 94 and is where the natural-scroll sweep recorded the largest
// critical path: 646 cycles to the last register write, 110 inside the budget.
// See reports/p2-static-y-stress-matrix-report.md.
.const P2_WORST_OFFSET = 8
.const P2_MERGE_Y = P2_LEAD_Y + 5 + MIN_REUSE_GAP   // 98

// F5: THE SIX-ENTRY MERGED BATCH. The case REUSE_LEAD has always been sized
//     for and which no P0/P1 fixture ever produced.
//     expect: accepted 12, reuse 6, rejected 0, batches 2, maxMidBatch 6
fixture5: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
          .byte P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y
fixture5End:

// F6-F10: the same geometry with 5, 4, 3, 2 and 1 sprites in the merged batch.
//     One controlled variable — batch size — so the timing table by batch size
//     compares like with like instead of comparing different screens.
fixture6: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
          .byte P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y
fixture6End:
fixture7: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
          .byte P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y
fixture7End:
fixture8: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
          .byte P2_MERGE_Y, P2_MERGE_Y, P2_MERGE_Y
fixture8End:
fixture9: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
          .byte P2_MERGE_Y, P2_MERGE_Y
fixture9End:
fixture10: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
           .byte P2_MERGE_Y
fixture10End:

// F11: the BATCH-MERGING boundary. Two entries one raster apart need two
//      different batch lines and must NOT merge. Same sprite count as F9,
//      three batches instead of two.
//      expect: accepted 8, batches 3, maxMidBatch 1
fixture11: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
           .byte P2_MERGE_Y, P2_MERGE_Y + 1
fixture11End:

// F12: the PHYSICAL boundary, stated exactly. Gap 20 is two sprites genuinely
//      overlapping in one hardware slot; gap 21 is physically possible on the
//      hardware and rejected only by OUR margin. Conflating those two is the
//      specific mistake this fixture exists to prevent.
//      expect: accepted 6, rejUnsafe 1 (gap 20), rejMargin 1 (gap 21)
fixture12: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
           .byte P2_LEAD_Y + SPRITE_HEIGHT - 1, P2_LEAD_Y + SPRITE_HEIGHT
fixture12End:

// F13: the CONSERVATIVE boundary, stated exactly. One short of MIN_REUSE_GAP
//      is rejected; exactly MIN_REUSE_GAP is accepted. These track the
//      constant: if REUSE_LEAD changes they move with it automatically.
//      expect: accepted 7, rejMargin 1 (gap 32), batches 2
fixture13: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
           .byte P2_LEAD_Y + MIN_REUSE_GAP - 1, P2_LEAD_Y + MIN_REUSE_GAP
fixture13End:

// F14: REPEATED merged reuse — three six-entry merged batches in one frame, at
//      exactly MAX_SCHED entries. Each group of six clears the group before it
//      by 38 lines, so every one of the 18 reuse events is legal and three
//      separate mid-screen batches each programme all six slots.
//      The hardest frame this renderer can be asked for under P2 rules.
//      expect: accepted 24, reuse 18, batches 4, maxMidBatch 6
.const P2_MERGE_Y2 = P2_MERGE_Y + 38
.const P2_MERGE_Y3 = P2_MERGE_Y2 + 38
fixture14: .byte P2_LEAD_Y, P2_LEAD_Y+1, P2_LEAD_Y+2, P2_LEAD_Y+3, P2_LEAD_Y+4, P2_LEAD_Y+5
           .byte P2_MERGE_Y,  P2_MERGE_Y,  P2_MERGE_Y,  P2_MERGE_Y,  P2_MERGE_Y,  P2_MERGE_Y
           .byte P2_MERGE_Y2, P2_MERGE_Y2, P2_MERGE_Y2, P2_MERGE_Y2, P2_MERGE_Y2, P2_MERGE_Y2
           .byte P2_MERGE_Y3, P2_MERGE_Y3, P2_MERGE_Y3, P2_MERGE_Y3, P2_MERGE_Y3, P2_MERGE_Y3
fixture14End:

// F15: THE WORST MEASURED LEGAL GEOMETRY.
//      Filled in from measurement, not from intuition: the Y offset and phase
//      that produced the smallest timing margin in the P2 sweep, frozen here as
//      literal Y values so the worst case is a permanent named regression
//      fixture rather than a sweep coordinate someone has to recompute.
//      See reports/p2-static-y-stress-matrix-report.md.
.const P2_WORST_Y = P2_LEAD_Y + P2_WORST_OFFSET
fixture15: .byte P2_WORST_Y, P2_WORST_Y+1, P2_WORST_Y+2, P2_WORST_Y+3, P2_WORST_Y+4, P2_WORST_Y+5
           .byte P2_WORST_Y+38, P2_WORST_Y+38, P2_WORST_Y+38
           .byte P2_WORST_Y+38, P2_WORST_Y+38, P2_WORST_Y+38
fixture15End:


// ===========================================================================
// P5 fixtures — the rotating-ring integration torture set.
// ===========================================================================
// Sixteen sprites, one orbit, evenly spaced in PHASE. Every mode uses the same
// geometry so that a behavioural difference between them can only be caused by
// the phase velocity or the vertical sweep, never by the shape.
//
// Record: phaseVelLo, phaseVelHi, shiftVelLo, shiftVelHi -- 16-bit fixed point
// with 8 fractional bits, added to an accumulator each frame. $0100 is exactly
// one table step per frame. See src/p5_ring.asm and tests/p5_model.py.
.const P5_REC_BYTES = 4

// F31 (RING-SLOW): one table step per frame: smooth, watchable, 5.1s per orbit
//      orbit 256 frames (5.1s), exact period 256 frames
//      expect: accepted 16 on EVERY frame, batches {6,7,11}
p5f31: .byte <$0100, >$0100, <$0000, >$0000
p5f31End:

// F32 (RING-FAST): eight steps per frame: maximum sorter and admission churn
//      orbit 32 frames (0.6s), exact period 32 frames
//      expect: accepted 16 on EVERY frame, batches {6,7}
p5f32: .byte <$0800, >$0800, <$0000, >$0000
p5f32End:

// F33 (RING-SHIFT): slow orbit swept vertically +/-14 rasters, for the badline sweep
//      orbit 256 frames (5.1s), exact period 4096 frames
//      expect: accepted 16 on EVERY frame, batches {6,7,11}
p5f33: .byte <$0100, >$0100, <$0010, >$0010
p5f33End:

// The per-fixture dispatch tables are DATA and live outside the $1800 code
// segment, which ran out of room when P4 added the sortReset call. They are
// read with absolute,X indexing, so their address is immaterial.
* = $ca00 "fixture dispatch"

fixtureLo:    .byte <fixture0, <fixture1, <fixture2, <fixture3, <fixture4
              .byte <fixture5, <fixture6, <fixture7, <fixture8, <fixture9
              .byte <fixture10, <fixture11, <fixture12, <fixture13, <fixture14, <fixture15
              .byte <p3f16, <p3f17, <p3f18, <p3f19, <p3f20, <p3f21, <p3f22, <p3f23
              .byte <p4f24, <p4f25, <p4f26, <p4f27, <p4f28, <p4f29, <p4f30
              .byte <p5f31, <p5f32, <p5f33
fixtureHi:    .byte >fixture0, >fixture1, >fixture2, >fixture3, >fixture4
              .byte >fixture5, >fixture6, >fixture7, >fixture8, >fixture9
              .byte >fixture10, >fixture11, >fixture12, >fixture13, >fixture14, >fixture15
              .byte >p3f16, >p3f17, >p3f18, >p3f19, >p3f20, >p3f21, >p3f22, >p3f23
              .byte >p4f24, >p4f25, >p4f26, >p4f27, >p4f28, >p4f29, >p4f30
              .byte >p5f31, >p5f32, >p5f33
fixtureLen:   .byte fixture0End - fixture0, fixture1End - fixture1, fixture2End - fixture2
              .byte fixture3End - fixture3, fixture4End - fixture4
              .byte fixture5End - fixture5, fixture6End - fixture6, fixture7End - fixture7
              .byte fixture8End - fixture8, fixture9End - fixture9, fixture10End - fixture10
              .byte fixture11End - fixture11, fixture12End - fixture12
              .byte fixture13End - fixture13, fixture14End - fixture14
              .byte fixture15End - fixture15
              // P3. The tables live in the generated src/p3_fixtures.asm; only
              // the dispatch lives here, so a fixture's identity is still one
              // row of one table.
              .byte P3F16_N, P3F17_N, P3F18_N, P3F19_N
              .byte P3F20_N, P3F21_N, P3F22_N, P3F23_N
              // P4. Every one is a motion record, including the ones whose
              // velocities are all zero -- see src/p4_fixtures.asm.
              .byte P4F24_N, P4F25_N, P4F26_N, P4F27_N
              .byte P4F28_N, P4F29_N, P4F30_N
              // P5. The length field is the RECORD size, not a sprite count:
              // a ring fixture's sprite count is fixed at P5_N_RING and is set
              // by loadRingFixture, not copied from here.
              .byte P5_REC_BYTES, P5_REC_BYTES, P5_REC_BYTES

// Which loader a fixture needs. P0/P1/P2 fixtures are bare Y lists with X,
// pointer and colour derived from the logical index; P3 motion fixtures carry a
// full initial position and trajectory per sprite. MAXCAP (22) is deliberately
// a STATIC fixture even though it is a P3 test: it exists to overflow the
// schedule, and giving it a trajectory would only make the overflow harder to
// reason about.
fixtureKind:  .byte FK_STATIC, FK_STATIC, FK_STATIC, FK_STATIC, FK_STATIC
              .byte FK_STATIC, FK_STATIC, FK_STATIC, FK_STATIC, FK_STATIC
              .byte FK_STATIC, FK_STATIC, FK_STATIC, FK_STATIC, FK_STATIC, FK_STATIC
              .byte FK_MOTION, FK_MOTION, FK_MOTION, FK_MOTION
              .byte FK_MOTION, FK_MOTION, FK_STATIC, FK_MOTION
              .byte FK_MOTION, FK_MOTION, FK_MOTION, FK_MOTION
              .byte FK_MOTION, FK_MOTION, FK_MOTION
              .byte FK_RING, FK_RING, FK_RING

* = $18d0 "fixtures code"

// Every fixture, not just the one that happened to be longest when the guard
// was written. F14 sits exactly ON the limit, so this is a live constraint.
// loadFixture wraps the bitmap index with AND, so SPRITE_COUNT must be a power
// of two or logical sprites past the wrap would point outside the bitmaps again.
.if ((SPRITE_COUNT & (SPRITE_COUNT - 1)) != 0) {
    .error "SPRITE_COUNT must be a power of two: loadFixture wraps with AND"
}

// The record table is walked with a 16-bit pointer (see loadMotionFixture), so
// there is no table-size limit any more -- only the logical pool.

// Every fixture must fit the logical pool. MAXCAP deliberately exceeds
// MAX_SCHED -- that is its whole purpose -- but never MAX_LOGICAL.
.if (P3F22_N > MAX_LOGICAL) { .error "MAXCAP exceeds MAX_LOGICAL" }
.if (P3F22_N <= MAX_SCHED)  { .error "MAXCAP must exceed MAX_SCHED or it tests nothing" }
.if (P4F30_N > MAX_LOGICAL) { .error "SORTCAP exceeds MAX_LOGICAL" }
.if (P4F30_N <= MAX_SCHED)  { .error "SORTCAP must exceed MAX_SCHED or it tests nothing" }

.if (fixture2End  - fixture2  > MAX_LOGICAL) { .error "fixture 2 exceeds MAX_LOGICAL" }
.if (fixture14End - fixture14 > MAX_LOGICAL) { .error "fixture 14 exceeds MAX_LOGICAL" }
.if (fixture15End - fixture15 > MAX_LOGICAL) { .error "fixture 15 exceeds MAX_LOGICAL" }

// ===========================================================================
// loadFixture — copy fixture A into the logical sprite arrays.
// Derives X / pointer / colour from the LOGICAL index so mis-assignment shows.
// ===========================================================================
loadFixture:
    tax
    stx fx_index
    lda fixtureLo,x
    sta fx_src
    lda fixtureHi,x
    sta fx_src + 1
    lda fixtureLen,x
    sta logCount

    // P3: never inherit a trajectory. Fixture selection is one SPACE press
    // away on a live machine, and a fixture that kept the previous fixture's
    // velocities would move in ways no model predicts.
    jsr clearMotion

    ldx fx_index
    lda fixtureKind,x
    beq fx_static
    cmp #FK_RING
    beq fx_ring
    jmp loadMotionFixture
fx_ring:
    jmp loadRingFixture

fx_static:
    ldy #0
    sty fx_col
fx_loop:
    cpy logCount
    bcs fx_done
fx_read:
    lda (fx_src),y
    clc
    adc fixtureYOffset                  // P2 vertical sweep. Zero for P0/P1.
    sta logY,y

    // X: seven columns, all < 256 so P0 needs no $D010 bits set.
    //
    // A running cursor, NOT `index AND 7`. The old form mapped logical 7 and
    // logical 8 to the same column, because (7 AND 7) was clamped to 0 and
    // (8 AND 7) is 0. With P0's fixtures those two sprites had different Y so
    // the collision was invisible; with a P2 fixture whose six sprites SHARE a
    // Y it would have drawn two of them exactly on top of each other and the
    // six-entry merged batch would have looked like five sprites to a human.
    // A true mod-7 cursor also makes F2's cascade repeat cleanly.
    ldx fx_col
    lda fxColumnX,x
    sta logX,y
    lda #0
    sta logXHi,y                        // every static fixture is X < 256
    inx
    cpx #7
    bcc !colOk+
    ldx #0
!colOk:
    stx fx_col

    // pointer: one numbered bitmap per LOGICAL sprite, WRAPPED at the number
    // of bitmaps that actually exist.
    //
    // There are SPRITE_COUNT (16) bitmaps but MAX_LOGICAL (24) logical sprites,
    // and fixture 14 uses all 24. Without this wrap, logical 16..23 point at
    // $2400..$25ff -- past spriteBitmapsEnd, into uninitialised RAM -- and the
    // last eight sprites display noise. Timing and the merged-batch proof are
    // unaffected, but a human doing manual acceptance would be looking at
    // garbage where a numeral belongs, which is exactly the kind of thing this
    // fixture set exists to make obvious.
    //
    // Numerals therefore repeat above 15 (logical 16 shows "0" again). Colour
    // already repeats the same way. Within any one batch the six sprites still
    // carry six different numerals, which is what the merged-batch check needs.
    tya
    and #(SPRITE_COUNT - 1)
    clc
    adc #SPRITE_PTR_FIRST
    sta logPtr,y

    // colour: 1..15, distinct for the first fifteen logical sprites
    tya
    tax
    lda fxColour,x
    sta logCol,y

    iny
    jmp fx_loop
fx_done:
    jmp sortReset                       // P4: sortedIDs must be a permutation
                                        // of 0..logCount-1 for THIS fixture

fx_col:     .byte 0                     // mod-7 column cursor, load-time only
// ===========================================================================
// loadMotionFixture — install a P3 record fixture.
// ===========================================================================
// fx_src already points at the record table and logCount is the sprite count.
// Records are P3_REC_BYTES apart and read with a single running offset, so the
// whole table must stay under 256 bytes: 23 sprites. MAXCAP needs 30 and is
// therefore a STATIC fixture, which it wants to be anyway. Guarded below.
//
// Pointer and colour still come from the LOGICAL index, exactly as for a static
// fixture, so the "sprite B is showing a 5" diagnostic works identically.
loadMotionFixture:
    ldx #0                              // logical sprite index
lm_loop:
    cpx logCount
    bcs lm_done

    ldy #0                              // 0: Y
    lda (fx_src),y
    clc
    adc fixtureYOffset                  // the P2 sweep translates the trajectory
    sta logY,x
    ldy #1                              // 1: X low
    lda (fx_src),y
    sta logX,x
    ldy #2                              // 2: X high
    lda (fx_src),y
    sta logXHi,x
    ldy #3                              // 3: X velocity
    lda (fx_src),y
    sta mvXVel,x
    ldy #4                              // 4: X min low
    lda (fx_src),y
    sta mvXMinLo,x
    ldy #5                              // 5: X min high
    lda (fx_src),y
    sta mvXMinHi,x
    ldy #6                              // 6: X max low
    lda (fx_src),y
    sta mvXMaxLo,x
    ldy #7                              // 7: X max high
    lda (fx_src),y
    sta mvXMaxHi,x
    ldy #8                              // 8: Y velocity
    lda (fx_src),y
    sta mvYVel,x
    ldy #9                              // 9: Y min
    lda (fx_src),y
    clc
    adc fixtureYOffset                  // bounds translate WITH the position,
    sta mvYMin,x                        // or the sweep would fight the clamp
    ldy #10                             // 10: Y max
    lda (fx_src),y
    clc
    adc fixtureYOffset
    sta mvYMax,x

    txa                                 // pointer: bitmap per logical index
    and #(SPRITE_COUNT - 1)
    clc
    adc #SPRITE_PTR_FIRST
    sta logPtr,x
    lda fxColour,x                      // colour: per logical index
    sta logCol,x

    // Advance the record pointer by one whole record, 16-bit.
    //
    // P3 walked the table with a single 8-bit running offset, which capped a
    // motion fixture at 23 sprites (23 x 11 = 253). P4 needs 30 -- SORTCAP has
    // to EXCEED MAX_SCHED to test the capacity fault under reordering, and 24
    // sprites is already past that cap. Advancing the pointer instead removes
    // the limit entirely and costs about as much as the `iny`s it replaces.
    lda fx_src
    clc
    adc #P3_REC_BYTES
    sta fx_src
    bcc !noCarry+
    inc fx_src + 1
!noCarry:

    inx
    jmp lm_loop

lm_done:
    lda #1
    sta fixtureMoves                    // the main loop must now rebuild every
                                        // frame; see mainLoop in main.asm
    jmp sortReset                       // P4: sortedIDs must be a permutation
                                        // of 0..logCount-1 for THIS fixture

fx_index:   .byte 0
fxColumnX:  .byte 30, 60, 90, 120, 150, 180, 210
// MAX_LOGICAL colours. 1..15 with black (0) never used, so a sprite is always
// visible against the black background; the sequence repeats above 15 for the
// same reason the numerals do -- there are only sixteen of each.
fxColour:   .byte 1,7,13,3,5,14,10,15,2,8,4,12,9,11,6,12
            .byte 1,7,13,3,5,14,10,15,2,8,4,12,9,11,6,12

// ---------------------------------------------------------------------------
// SEGMENT GROWTH GUARD -- see the note in src/scroll.asm. The fixture code
// segment runs from $18d0 to the scroller's base at $1a00.
// ---------------------------------------------------------------------------
.if (* > $1a00) {
    .error "the 'fixtures code' segment has grown into 'scroller' at $1a00"
}
