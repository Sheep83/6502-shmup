// ===========================================================================
// clip.asm — renders vertically clipped sprite bitmaps into scratch blocks
// ===========================================================================
// MAIN THREAD ONLY. Writes no VIC register; it produces sprite bitmap bytes,
// and the only reader is the VIC, through a pointer the schedule builder
// published.
//
// WHY IT EXISTS. The vertical border is held open so the HUD can live above
// the playfield, so the VIC clips nothing at the top and bottom aperture edges
// -- unlike the left and right, where the closed horizontal border clips in
// hardware. A gameplay sprite is therefore admitted only when its whole 21-row
// body fits inside MIN_SPRITE_Y..MAX_SPRITE_Y. To let an enemy cross an edge
// smoothly, its PHYSICAL Y is pinned at the boundary and its PIXELS are
// shifted instead, so every visible row still lands on the raster the enemy's
// true position demands. Logical Y is never touched: movement, collision,
// paths, lifecycle and diagnostics all keep reading the truth.
//
// THE SAFETY INVARIANT. A clipped sprite's bitmap is part of a frame's plan
// exactly as its Y and slot are -- the VIC reads those 63 bytes for 21 rasters
// long after the build finished. So the scratch pool is INDEXED BY schedNext,
// the same byte the schedule buffers are. The builder may only write blocks in
// the pool it owns; on the atomic swap the block travels with its schedule and
// the main thread moves to the other pool. There is consequently no handover,
// no raster-progress test and no safe-to-overwrite window, because the main
// thread and the VIC are never looking at the same block.
//
// POOL SIZE. Per edge the builder caps clipped entries at MUX_SLOTS by
// construction: every top-clipped entry presents at MIN_SPRITE_Y and every
// bottom-clipped one at MAX_SPRITE_Y, so within an edge all share a schedule
// Y -- the first MUX_SLOTS fit with no slot to reuse, and the next compares
// against the entry six places back, finds a gap of zero and is refused as
// unsafe. The two edges are disjoint, so a legal schedule can demand TWELVE
// distinct bitmaps. CLIP_POOL_SLOTS is SIX: twelve double-buffered would cost
// 1536 bytes and VIC bank 0 has 832 spare without moving something major. Six
// covers every population the authored content produces, and overflow is
// explicit rather than silent -- the entry is dropped and clipPoolFull counts
// it.
// ===========================================================================

// --- the pool blocks --------------------------------------------------------
// Twelve 64-byte VIC-visible blocks, two pools of CLIP_POOL_SLOTS. Flat index
// = page * CLIP_POOL_SLOTS + slot, so schedNext selects a pool with one
// compare.
//
// Three live at $0340, the cassette buffer's tail: this engine banks the
// KERNAL out and takes the hardware vector at $fffe directly (see exInstall),
// so there is no tape or RS232 to collide with and nothing else in src/
// touches $0300-$03ff. They are NOT emitted into the PRG -- the file starts at
// $0801 and reaching down would drag screen page A and the stack in -- and
// they need no initialising because every block is written in full before it
// is ever pointed at.
//
// The other nine sit in existing gaps and ARE emitted, so the assembler maps
// them and a segment growing into one is a build error, not a corrupt sprite.
.var clipBlocks = List()
    .eval clipBlocks.add($0340, $0380, $03c0, $3100, $3140, $3180)   // pool 0
    .eval clipBlocks.add($31c0, $3680, $3700, $3740, $3780, $37c0)   // pool 1

.if (clipBlocks.size() != 2 * CLIP_POOL_SLOTS) {
    .error "the scratch pool is not two pools of CLIP_POOL_SLOTS blocks"
}
.for (var i = 0; i < clipBlocks.size(); i++) {
    .var a = clipBlocks.get(i)
    .if ((a & 63) != 0)   { .error "a scratch block is not 64-byte aligned" }
    .if (a + 64 > $4000)  { .error "a scratch block leaves VIC bank 0" }
    .for (var j = i + 1; j < clipBlocks.size(); j++) {
        .if (a == clipBlocks.get(j)) { .error "a scratch block is listed twice" }
    }
}

// ===========================================================================
// State. MAIN THREAD ONLY.
// ===========================================================================
// logClip sits directly above the sorter's state, in the forty bytes below the
// $c400 ceiling. It is indexed by LOGICAL ID, not by pool slot, because that is
// what the builder has in hand; it is therefore MAX_LOGICAL long, so every
// logical sprite reads a defined value whether or not it is ever clipped.
* = $c3d8 "clip state"

// Per logical sprite: 0 = present normally. Otherwise the number of rows the
// sprite hangs outside the aperture, POSITIVE above the top edge and NEGATIVE
// below the bottom one. Written by src/enemy.asm every frame an enemy lives,
// cleared by objectZeroSlot so a reused slot inherits nothing, and zero for
// everything that is not an enemy.
logClip:    .fill MAX_LOGICAL, 0

clipStateEnd:
.if (clipStateEnd > $c400) { .error "the clip state has grown past its $c400 ceiling" }

// ===========================================================================
* = $8000 "clip"

// --- the pool, as bytes ------------------------------------------------------
// Three parallel tables rather than arithmetic: the pointer is what the
// schedule wants, the address is what the copy wants, and deriving one from
// the other at 63-bytes-a-sprite rates would be paying twice for a number the
// assembler already knows.
clipBlkPtr:
.for (var i = 0; i < clipBlocks.size(); i++) { .byte clipBlocks.get(i) / 64 }
clipBlkLo:
.for (var i = 0; i < clipBlocks.size(); i++) { .byte <clipBlocks.get(i) }
clipBlkHi:
.for (var i = 0; i < clipBlocks.size(); i++) { .byte >clipBlocks.get(i) }

// --- locals ------------------------------------------------------------------
clipUsed:     .byte 0               // blocks taken from THIS build's pool
clipPoolFull: .byte 0               // saturating: clipped entries refused
clipSrcLo:    .byte 0
clipSrcHi:    .byte 0
clipSaveX:    .byte 0
clipSaveY:    .byte 0
clipVis:      .byte 0               // visible bytes  = (21 - rows) * 3
clipBlank:    .byte 0               // blanked bytes  = rows * 3

// ---------------------------------------------------------------------------
// clipInit — no clipping anywhere, no blocks taken, no overflows counted.
// ---------------------------------------------------------------------------
clipInit:
    lda #0
    sta clipUsed
    sta clipPoolFull
    ldx #MAX_LOGICAL - 1
!slot:
    sta logClip,x
    dex
    bpl !slot-
    rts

// ---------------------------------------------------------------------------
// clipBuildBegin — a new schedule is being built, so its pool is empty again.
// Called from the builder's own preamble, beside the stat counters it resets.
// ---------------------------------------------------------------------------
clipBuildBegin:
    lda #0
    sta clipUsed
    rts

// ---------------------------------------------------------------------------
// clipMakeScratch — render one clipped bitmap into the next free block.
//
// Entry: X = logical ID, logClip[X] non-zero, and the CALLER has already
//        checked that a block is free (see the builder's accept path).
// Exit:  A = the sprite pointer to publish. X and Y preserved.
//
// THE ROW MAPPING, which is the only arithmetic in this file that matters.
// Let t be the enemy's true logY and c the row count in logClip.
//
//   TOP, c > 0 and t = MIN_SPRITE_Y - c:
//     the sprite is held at MIN_SPRITE_Y, so block row r shows at raster
//     MIN_SPRITE_Y + r. Fill it from source row r + c, whose true raster is
//     t + r + c = MIN_SPRITE_Y + r. Exact. Source rows 0..c-1 are above the
//     aperture and are simply never read; block rows 21-c..20 are blanked.
//
//   BOTTOM, c < 0 and t = MAX_SPRITE_Y + |c|:
//     the sprite is held at MAX_SPRITE_Y, so block row r shows at raster
//     MAX_SPRITE_Y + r. Fill it from source row r - |c|, whose true raster is
//     t + r - |c| = MAX_SPRITE_Y + r. Exact. Block rows 0..|c|-1 are blanked
//     and source rows past the block's end are below the aperture.
//
// Both cases are the same shape -- copy one contiguous run of rows, blank the
// rest -- which is why there is one loop pair rather than two routines. At one
// row of granularity there is no rounding anywhere: every visible row lands on
// the raster the enemy's real position puts it on.
// ---------------------------------------------------------------------------
clipMakeScratch:
    stx clipSaveX
    sty clipSaveY

    // ---- where the canonical art is ---------------------------------------
    // From the render pointer, NOT from a hard-coded enemy bitmap: a future
    // animation frame or a second species changes logPtr and this follows it
    // without changing, which is the entire reason the pool is fixed-size.
    lda #0
    sta clipSrcLo
    lda logPtr,x
    sta clipSrcHi                       // ptr * 256
    lsr clipSrcHi
    ror clipSrcLo                       // ptr * 128
    lsr clipSrcHi
    ror clipSrcLo                       // ptr * 64: the block's address

    // ---- row counts -------------------------------------------------------
    lda logClip,x
    bpl !rows+
    eor #$ff                            // negative: |c|
    clc
    adc #1
!rows:
    sta clipBlank                       // c rows, for now
    // blank bytes = c * 3, visible bytes = 63 - that
    asl                                 // c*2
    clc
    adc clipBlank                       // c*3
    sta clipBlank
    lda #SPRITE_HEIGHT * 3
    sec
    sbc clipBlank
    sta clipVis

    // ---- which block, from the pool the BUILDER owns ----------------------
    ldx #0
    lda schedNext
    beq !pool0+
    ldx #CLIP_POOL_SLOTS
!pool0:
    txa
    clc
    adc clipUsed
    tax                                 // X = flat block index
    inc clipUsed

    lda clipBlkLo,x
    sta clipCopyDst + 1
    sta clipCopyDst2 + 1
    sta clipCopyDst3 + 1
    sta clipBlankDst + 1
    sta clipBlankDst2 + 1
    sta clipBlankDst3 + 1
    lda clipBlkHi,x
    sta clipCopyDst + 2
    sta clipCopyDst2 + 2
    sta clipCopyDst3 + 2
    sta clipBlankDst + 2
    sta clipBlankDst2 + 2
    sta clipBlankDst3 + 2
    lda clipBlkPtr,x
    pha                                 // the answer, while X is still needed

    // ---- aim the two runs -------------------------------------------------
    // TOP skips c rows of SOURCE; BOTTOM skips c rows of DESTINATION. The
    // copy always walks Y from zero, so only the bases differ.
    ldx clipSaveX
    lda logClip,x
    bmi !bottom+

    // TOP: source += blank bytes, destination stays, blanking follows the copy
    lda clipSrcLo
    clc
    adc clipBlank
    sta clipSrcRead + 1
    sta clipSrcRead2 + 1
    sta clipSrcRead3 + 1
    lda clipSrcHi
    adc #0
    sta clipSrcRead + 2
    sta clipSrcRead2 + 2
    sta clipSrcRead3 + 2
    // The blanked rows are the TAIL, so the blank run's base is the block plus
    // the visible bytes. Folding the offset into the ADDRESS rather than into
    // the starting index is what lets the blank loop count down to zero like
    // the copy loop does -- see the note at !runs.
    lda clipBlankDst + 1
    clc
    adc clipVis
    sta clipBlankDst + 1
    sta clipBlankDst2 + 1
    sta clipBlankDst3 + 1
    lda clipBlankDst + 2
    adc #0
    sta clipBlankDst + 2
    sta clipBlankDst2 + 2
    sta clipBlankDst3 + 2
    jmp !runs+

!bottom:
    // BOTTOM: source stays, destination += blank bytes, blanking is the HEAD
    lda clipSrcLo
    sta clipSrcRead + 1
    sta clipSrcRead2 + 1
    sta clipSrcRead3 + 1
    lda clipSrcHi
    sta clipSrcRead + 2
    sta clipSrcRead2 + 2
    sta clipSrcRead3 + 2
    lda clipCopyDst + 1
    clc
    adc clipBlank
    sta clipCopyDst + 1
    sta clipCopyDst2 + 1
    sta clipCopyDst3 + 1
    lda clipCopyDst + 2
    adc #0
    sta clipCopyDst + 2
    sta clipCopyDst2 + 2
    sta clipCopyDst3 + 2
    // the blanked rows are the HEAD, so the blank base is the block itself and
    // nothing needs adding

!runs:
    // ---- the two runs, ONE SPRITE ROW AT A TIME ---------------------------
    // THREE BYTES PER ITERATION BECAUSE EVERY COUNT HERE IS A MULTIPLE OF
    // THREE. Clipping is row-granular and a sprite row is three bytes, so
    // clipVis and clipBlank can only ever be 3n. Unrolling to the row pays the
    // loop's branch once per three bytes instead of once per byte.
    //
    // AND THE INDEX COUNTS DOWN. The old loops walked up with Y and counted
    // down a separate X -- `iny / dex / bne`, four cycles of bookkeeping a
    // byte. Counting Y down from count-1 to -1 and branching on BPL does both
    // jobs with one `dey`, which is why the second index register disappeared.
    //
    // Measured: the copy went 16 cycles a byte to 12, the blank 12 to 8.
    //
    // Both runs now start at index zero, which is why the TOP case folds its
    // tail offset into clipBlankDst above rather than into a starting index.
    ldy clipVis
    beq !blank+
    dey
!copy:
clipSrcRead:
    lda $ffff,y
clipCopyDst:
    sta $ffff,y
    dey
clipSrcRead2:
    lda $ffff,y
clipCopyDst2:
    sta $ffff,y
    dey
clipSrcRead3:
    lda $ffff,y
clipCopyDst3:
    sta $ffff,y
    dey
    bpl !copy-

!blank:
    ldy clipBlank
    beq !done+
    dey
    lda #0
!zero:
clipBlankDst:
    sta $ffff,y
    dey
clipBlankDst2:
    sta $ffff,y
    dey
clipBlankDst3:
    sta $ffff,y
    dey
    bpl !zero-

!done:
    pla                                 // the scratch block's sprite pointer
    ldx clipSaveX
    ldy clipSaveY
clipReturn:                             // named so a cycle probe has a symbol
    rts


clipCodeEnd:
.if (clipCodeEnd > $8200) { .error "the clip code has outgrown its $8000 segment" }

// ---------------------------------------------------------------------------
// The nine pool blocks that sit inside the PRG's span, reserved so that the
// assembler maps them and a segment growing into one is a build error. The
// three at $0340 are deliberately absent -- see the block list above.
// ---------------------------------------------------------------------------
.for (var i = 0; i < clipBlocks.size(); i++) {
    .var a = clipBlocks.get(i)
    .if (a >= $0801) {
        * = a "clip scratch"
        .fill 64, 0
    }
}
