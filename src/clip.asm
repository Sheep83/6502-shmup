// ===========================================================================
// clip.asm — runtime vertical sprite clipping, into schedule-owned scratch
// ===========================================================================
// MAIN THREAD ONLY. Nothing here runs in an IRQ, and nothing here writes a VIC
// register. It produces SPRITE BITMAP BYTES, and the only thing that ever
// reads them is the VIC, through a pointer the schedule builder wrote.
//
// ---------------------------------------------------------------------------
// THE PROBLEM, AND WHY IT IS NOT THE RENDERER'S
// ---------------------------------------------------------------------------
// The vertical border is held open so the HUD can live above the playfield, so
// the VIC clips NOTHING at the top and bottom aperture edges -- unlike the
// left and right, where the closed horizontal border clips sprites in hardware
// and always has. A gameplay sprite may therefore only be admitted when its
// whole 21-row body fits inside MIN_SPRITE_Y..MAX_SPRITE_Y, and an enemy
// crossing either vertical edge appears or vanishes whole.
//
// The fix is to keep the sprite's PHYSICAL Y inside that band and change its
// PIXELS instead: hold the sprite at the boundary and feed it a bitmap whose
// rows have been shifted so that every visible row lands on exactly the raster
// the enemy's true position says it should. The enemy's logical Y is not
// touched, so movement, collision, paths, lifecycle and diagnostics all go on
// reading the truth.
//
// ---------------------------------------------------------------------------
// WHY THE BITMAP IS SCHEDULE-OWNED STATE
// ---------------------------------------------------------------------------
// This is the whole safety argument and it is short.
//
// The renderer already double-buffers: the main thread builds schedNext while
// the IRQ executes schedCurrent, and exFrame swaps them atomically. A clipped
// sprite's bitmap is exactly as much a part of that frame's plan as its Y or
// its slot -- the VIC will be reading those 63 bytes for 21 rasters, some time
// after the build that produced them has finished.
//
// So the scratch pool is INDEXED BY schedNext, the same byte the schedule
// buffers are indexed by. The pointer the builder stores in schedPtr names a
// block in the pool the builder is allowed to write; when that schedule is
// promoted to CURRENT, the block travels with it and the main thread moves on
// to the OTHER pool. There is no handover, no raster-progress test and no
// "safe to overwrite now" window, because there is never a moment when the
// main thread and the VIC are looking at the same block.
//
// ---------------------------------------------------------------------------
// POOL SIZE, AND THE STRUCTURAL CEILING ABOVE IT
// ---------------------------------------------------------------------------
// The builder caps clipped entries per edge at MUX_SLOTS, and it does so by
// construction rather than by policy. Every top-clipped entry presents at
// MIN_SPRITE_Y and every bottom-clipped one at MAX_SPRITE_Y, so within an edge
// they are all at the SAME schedule Y: the first MUX_SLOTS accepted entries
// fit with no slot to reuse, and the next one compares against the entry six
// places back, finds a gap of zero, and is refused as unsafe. Six per edge,
// and the two edges are geometrically disjoint -- so a legal schedule can ask
// for TWELVE distinct clipped bitmaps.
//
// CLIP_POOL_SLOTS is SIX, not twelve, and that is a memory decision taken with
// its consequence understood: twelve blocks double-buffered is 1536 bytes and
// VIC bank 0 has 832 to give without relocating something major. Six covers
// every population the authored content can currently produce -- peak enemy
// count is seven, spread across the whole aperture -- and the overflow path is
// explicit rather than silent: see clipPoolFull.
// ===========================================================================

// --- the pool blocks --------------------------------------------------------
// Twelve 64-byte blocks, VIC-visible, laid out as two pools of
// CLIP_POOL_SLOTS. Flat index = page * CLIP_POOL_SLOTS + slot, so schedNext
// selects a pool with one compare.
//
// THREE OF THEM LIVE AT $0340. That is the tail of the cassette buffer and the
// unused bytes above it, and this engine can have them because it banks the
// KERNAL out and takes the hardware vector at $fffe directly (see exInstall) --
// no tape, no RS232, and nothing in src/ references $0300..$03ff at all. They
// are NOT emitted into the PRG: the file starts at $0801 and reaching down to
// $0340 would drag screen page A and the stack into it. Every block is fully
// written before it is ever pointed at, so there is nothing to initialise.
//
// The other nine sit in gaps the map already had: four in the raster
// executor's headroom, one above the enemy bitmap, four above the projectile.
// Those ARE emitted, so the assembler maps them and a future segment that
// grows into one is a build error rather than a corrupted sprite.
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
// logClip goes in the forty bytes between the sorter's state and the motion
// block. It is indexed by LOGICAL ID, not by pool slot, because that is what
// the builder has in hand -- and it must therefore be MAX_LOGICAL long, so
// that a qualification fixture driving a logical sprite the pool never issues
// still reads a defined zero.
* = $c3d8 "clip state"

// Per logical sprite: 0 = present normally. Otherwise the number of rows the
// sprite hangs outside the aperture, POSITIVE above the top edge and NEGATIVE
// below the bottom one. Written by src/enemy.asm every frame an enemy lives,
// cleared by objectZeroSlot so a reused slot inherits nothing, and zero for
// everything that is not an enemy.
logClip:    .fill MAX_LOGICAL, 0

clipStateEnd:
.if (clipStateEnd > $c400) { .error "the clip state has grown into the motion state at $c400" }

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
    sta clipBlankDst + 1
    lda clipBlkHi,x
    sta clipCopyDst + 2
    sta clipBlankDst + 2
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
    lda clipSrcHi
    adc #0
    sta clipSrcRead + 2
    lda clipVis
    sta clipBlankAt                     // blank the TAIL
    jmp !runs+

!bottom:
    // BOTTOM: source stays, destination += blank bytes, blanking is the HEAD
    lda clipSrcLo
    sta clipSrcRead + 1
    lda clipSrcHi
    sta clipSrcRead + 2
    lda clipCopyDst + 1
    clc
    adc clipBlank
    sta clipCopyDst + 1
    lda clipCopyDst + 2
    adc #0
    sta clipCopyDst + 2
    lda #0
    sta clipBlankAt

!runs:
    // ---- the visible rows -------------------------------------------------
    ldy #0
    ldx clipVis
    beq !blank+
!copy:
clipSrcRead:
    lda $ffff,y
clipCopyDst:
    sta $ffff,y
    iny
    dex
    bne !copy-

    // ---- and the rows that are outside the aperture -----------------------
!blank:
    ldx clipBlank
    beq !done+
    ldy clipBlankAt
    lda #0
!zero:
clipBlankDst:
    sta $ffff,y
    iny
    dex
    bne !zero-

!done:
    pla                                 // the scratch block's sprite pointer
    ldx clipSaveX
    ldy clipSaveY
    rts

clipBlankAt: .byte 0

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
