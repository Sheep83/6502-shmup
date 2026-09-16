// ===========================================================================
// hud.asm — the live top-border HUD: state, bitmaps and bounded renderers.
// ===========================================================================
// NOT ONE VIC REGISTER IS WRITTEN FROM THIS FILE.
//
// One subsystem owns sprite VIC state and that subsystem is src/renderer.asm.
// The HUD time-shares HW2-HW7 with the gameplay multiplexer, so the code that
// programs the VIC -- exHud -- lives there, beside the handoff that takes those
// slots back. What lives here is the logical HUD state, the bitmap pool, and
// the main-thread routines that draw into it.
//
//     main thread   decides what the HUD says and draws it into bitmap RAM
//     exHud         points the VIC at bitmaps that are already finished
//
// exHud formats nothing, converts nothing and draws nothing. It costs the same
// whether the score is 000000 or 999990.
// ===========================================================================

// --- logical layout ---------------------------------------------------------
//   HW2  lives          precomputed bitmap per value, selected by POINTER
//   HW3  heat, left     rendered
//   HW4  heat, right    rendered   (adjacent to HW3: one continuous 48px bar)
//   HW5  score, left    rendered   digits 0-2
//   HW6  score, right   rendered   digits 3-5  (adjacent to HW5)
//   HW7  upgrade        precomputed bitmap per value, selected by POINTER
.const HUD_SPRITE_COUNT = 6
.const HUD_LIVES_MAX    = 5                 // hard cap; see hudLivesByte
.const HUD_UPGRADE_MAX  = 3                 // states 0..3
.const HUD_HEAT_MAX     = 300
.const HUD_HEAT_PIXELS  = 48                // 24 + 24, HW3 and HW4 side by side

// --- bitmap pool ------------------------------------------------------------
// $3200-$357f, below the player's bitmaps and above screen page B. The pointer
// values $c8..$d5 are DELIBERATELY DISJOINT from every gameplay pointer: the
// handoff at raster 40 overwrites each HUD pointer with a gameplay one, and if
// the two pools could share a value, a correct overwrite and a missing one
// would be indistinguishable from outside.
//
// Four bitmaps are DRAWN at run time and ten are precomputed at assembly time.
// Lives has six possible values and upgrade four, so for those two components
// the pointer IS the update -- no drawing at all.
.const HUD_SPRITES      = $3200
.const HUD_HEAT_L       = HUD_SPRITES + 0 * 64      // ptr $c8
.const HUD_HEAT_R       = HUD_SPRITES + 1 * 64      // ptr $c9
.const HUD_SCORE_L      = HUD_SPRITES + 2 * 64      // ptr $ca
.const HUD_SCORE_R      = HUD_SPRITES + 3 * 64      // ptr $cb
.const HUD_LIVES_0      = HUD_SPRITES + 4 * 64      // ptr $cc .. $d1
.const HUD_UPGRADE_0    = HUD_SPRITES + 10 * 64     // ptr $d2 .. $d5
.const HUD_BLOCKS       = 14
.const HUD_SPRITES_END  = HUD_SPRITES + HUD_BLOCKS * 64
.const HUD_PTR_FIRST    = HUD_SPRITES / 64          // $c8
.const HUD_PTR_HEAT_L   = HUD_PTR_FIRST + 0
.const HUD_PTR_HEAT_R   = HUD_PTR_FIRST + 1
.const HUD_PTR_SCORE_L  = HUD_PTR_FIRST + 2
.const HUD_PTR_SCORE_R  = HUD_PTR_FIRST + 3
.const HUD_PTR_LIVES_0  = HUD_PTR_FIRST + 4
.const HUD_PTR_UPGRADE_0 = HUD_PTR_FIRST + 10

.if ((HUD_SPRITES & 63) != 0) { .error "the HUD sprite block must be 64-byte aligned" }
.if (HUD_SPRITES_END > BLANK_CHARSET) { .error "HUD bitmaps run into the blank charset at $3800" }
.if (HUD_SPRITES < SCREEN_B + $400) { .error "HUD bitmaps overlap screen page B" }

// --- placement --------------------------------------------------------------
// Y=16. A VIC sprite at Y=n is displayed on rasters n+1..n+21, so Y=16 gives
// 17..37 and the raster-40 handoff has a clear line in hand. Y=18 would span
// 19..39 and leave none.
.const HUD_Y            = 16

// X. The two gauge halves are ADJACENT so each pair reads as one object: heat
// spans 96..143 as a continuous 48-pixel bar, score spans 176..223 as six
// digits. HW7 sits past X=255, which keeps the HUD's $d010 non-zero so that a
// handoff failing to rewrite it is visible rather than silent.
.const HUD_D010         = %10000000                 // HW7 only
.const HUD_ENABLE       = %11111100                 // HW2..HW7, and nothing else

// Mode registers the HUD sets, and which the handoff must therefore restore.
// $d017 is deliberately NOT among them: Y expansion doubles a sprite's height
// AND its DMA span, and a Y-expanded HUD at Y=16 would fetch until line 58 --
// through the handoff and into the aperture.
.const HUD_D01B         = %11111100                 // all six behind graphics
.const HUD_D01D         = %00000100                 // HW2 (lives) X-expanded

// --- dirty flags ------------------------------------------------------------
// One bit per component. hudUpdate does nothing at all when the byte is zero,
// which is the common case -- each component changes on its own slow cadence.
.const HUD_DIRTY_LIVES   = %00000001
.const HUD_DIRTY_HEAT    = %00000010
.const HUD_DIRTY_SCORE   = %00000100
.const HUD_DIRTY_UPGRADE = %00001000

// --- the safe window for writing HUD bitmap RAM -----------------------------
// THE VIC READS THESE BITMAPS ON RASTERS 16..37, AND NOWHERE ELSE.
//
// The HUD is displayed on 17..37; sprite data for display line L is fetched in
// cycles 0..9 of line L for HW3..HW7 and in cycles 57..62 of line L-1 for HW2,
// so the fetch window is lines 16..37 inclusive. $d015 has no HUD bit set
// outside rasters ~10..51 either, so there is no other opportunity.
//
// hudUpdate therefore refuses to start unless the raster is inside
// HUD_SAFE_LO..HUD_SAFE_HI, and the work it then does is bounded by
// construction -- every renderer below is straight-line or a counted loop, with
// no data-dependent iteration. Starting at 199 in the worst case, the whole
// update plus every interrupt that can preempt it finishes far short of the
// next frame's raster 16. It is a REFUSAL, not a margin: hudUpdWrapped counts
// any update that took long enough for the raster to wrap, and must read zero.
//
// 56 is chosen to be past the handoff (40..51) and the top split (53..55); 200
// leaves fifty rasters before the frame transaction.
.const HUD_SAFE_LO      = 56
.const HUD_SAFE_HI      = 200

// ===========================================================================
// State and tables. Outside VIC bank 0: the VIC never looks at any of this.
// ===========================================================================
* = $c960 "hud state"

// --- logical state, independent of which hardware slot displays it ----------
hudLives:      .byte HUD_LIVES_MAX
hudUpgrade:    .byte 0
hudHeatLo:     .byte 0                      // 0..HUD_HEAT_MAX, 16-bit
hudHeatHi:     .byte 0
hudScore:      .fill 6, 0                   // one digit per byte, most significant first
hudDirty:      .byte 0

// The pointer the VIC is actually given, one per slot, index 0..5 = HW2..HW7.
// Lives and upgrade "render" by writing ONE byte of this table, which is atomic
// against the interrupt that reads it -- exHud reads each entry once.
hudPtrLive:    .byte HUD_PTR_LIVES_0 + HUD_LIVES_MAX, HUD_PTR_HEAT_L, HUD_PTR_HEAT_R
               .byte HUD_PTR_SCORE_L, HUD_PTR_SCORE_R, HUD_PTR_UPGRADE_0

// The pixel count last drawn into the bar. Heat changes every frame while it
// ramps, but 300 logical units map onto 48 pixels, so the BITMAP only changes
// every sixth unit; comparing against this is what keeps the average cost down.
hudHeatPix:    .byte $ff                    // $ff = "nothing drawn yet"

// --- instrumentation --------------------------------------------------------
hudUpdStartMin: .byte $ff                   // raster at which an update began
hudUpdStartMax: .byte 0
hudUpdEndMax:   .byte 0
hudUpdWrapped:  .byte 0                     // updates during which the raster
                                            // wrapped: must be 0, saturating
hudUpdRuns:     .byte 0, 0                  // updates actually performed, 16-bit
hudUpdDeferred: .byte 0, 0                  // updates refused by the window

// --- the heat gauge's three colours ----------------------------------------
// The gauge is the only HUD component whose colour carries meaning: gameplay
// flashes it while the weapon is locked out, which is the one piece of feedback
// that says "this is WHY you cannot shoot" rather than "the bar is full".
// Game code reaches it through hudSetHeatColour and never touches the table.
.const HUD_HEAT_COL_NORMAL = $07                    // yellow, at rest
.const HUD_HEAT_COL_ALARM  = $02                    // red    } alternated while
.const HUD_HEAT_COL_BLANK  = $00                    // black  } locked out

// --- per-slot VIC placement, read by exHud ---------------------------------
hudSlot:   .byte 2, 3, 4, 5, 6, 7
hudSlot2:  .byte 4, 6, 8, 10, 12, 14
hudXLo:    .byte 32, 96, 120, 176, 200, <280
hudYPos:   .fill HUD_SPRITE_COUNT, HUD_Y
//         lives   heat L  heat R  score L score R upgrade
hudCol:    .byte $01, HUD_HEAT_COL_NORMAL, HUD_HEAT_COL_NORMAL, $0d, $0d, $0a

// --- heat: logical value to filled pixels, with no division ----------------
// heat 0..300 -> index 0..75 by two shifts -> pixels 0..48 by one lookup.
// Every pixel value is reachable and the map saturates by construction.
heatPix:   .fill 76, round(i * HUD_HEAT_PIXELS / 75)

// n*3, so a pixel count can index the three-byte rows of barFill.
barOfs:    .fill 25, i * 3

hudStateEnd:
.if (hudStateEnd > $ca00) { .error "the HUD state has grown past its $ca00 ceiling" }

// ===========================================================================
// Glyphs and fill patterns. Also outside bank 0.
// ===========================================================================
* = $cf40 "hud glyphs"

// Eight rows per digit, one byte per row: a digit is exactly one byte column of
// a sprite, so rendering one is eight plain stores and no shifting at all. That
// is the whole reason the font is 8 pixels wide.
digitGlyph:
    .byte $7c,$c6,$ce,$d6,$e6,$c6,$7c,$00       // 0
    .byte $30,$70,$30,$30,$30,$30,$fc,$00       // 1
    .byte $78,$cc,$0c,$38,$60,$cc,$fc,$00       // 2
    .byte $78,$cc,$0c,$38,$0c,$cc,$78,$00       // 3
    .byte $1c,$3c,$6c,$cc,$fe,$0c,$1e,$00       // 4
    .byte $fc,$c0,$f8,$0c,$0c,$cc,$78,$00       // 5
    .byte $38,$60,$c0,$f8,$cc,$cc,$78,$00       // 6
    .byte $fc,$cc,$0c,$18,$30,$30,$30,$00       // 7
    .byte $78,$cc,$cc,$78,$cc,$cc,$78,$00       // 8
    .byte $78,$cc,$cc,$7c,$0c,$18,$70,$00       // 9

// A bar filled n pixels from the left, as the three bytes of one sprite row.
barFill:
.for (var n = 0; n <= 24; n++) {
    .var v = 0
    .for (var i = 0; i < n; i++) { .eval v = v | ($800000 >> i) }
    .byte (v >> 16) & $ff, (v >> 8) & $ff, v & $ff
}
hudGlyphsEnd:
.if (hudGlyphsEnd > $d000) { .error "the HUD glyphs have run into the VIC registers" }

// ===========================================================================
// Bitmap generators, evaluated by KickAssembler.
// ===========================================================================
.const HUD_SCORE_ROW0 = 6                       // digits on sprite rows 6..13
.const HUD_HEAT_ROW0  = 6                       // bar on sprite rows 6..14
.const HUD_HEAT_ROWS  = 9

// A small diamond, four pixels wide and five tall, repeated once per life at a
// five-pixel pitch. The count is CAPPED: livesByte is only ever called with
// 0..HUD_LIVES_MAX, and five glyphs at pitch five end at pixel 23 of 24.
.var shipRow = List().add($4, $e, $e, $e, $4)

.function livesByte(n, r, b) {
    .if (r < 8 || r > 12) { .return 0 }
    .var v = 0
    .for (var i = 0; i < n; i++) {
        .eval v = v | (shipRow.get(r - 8) << (20 - i * 5))
    }
    .return (v >> (16 - b * 8)) & $ff
}

// Upgrade state n shows n+1 filled blocks: unmistakably different at a glance,
// and four states is the whole range.
.function upgradeByte(n, r, b) {
    .if (r < 7 || r > 13) { .return 0 }
    .var v = 0
    .for (var i = 0; i <= n; i++) {
        .eval v = v | ($3f << (18 - i * 6))
    }
    .return (v >> (16 - b * 8)) & $ff
}

* = HUD_SPRITES "hud bitmaps"
hudBitmaps:
    .fill 64, 0                                 // heat left   -- drawn at run time
    .fill 64, 0                                 // heat right  -- drawn at run time
    .fill 64, 0                                 // score left  -- drawn at run time
    .fill 64, 0                                 // score right -- drawn at run time
.for (var n = 0; n <= HUD_LIVES_MAX; n++) {     // lives 0..5, precomputed
    .for (var r = 0; r < 21; r++) {
        .byte livesByte(n, r, 0), livesByte(n, r, 1), livesByte(n, r, 2)
    }
    .byte $00
}
.for (var n = 0; n <= HUD_UPGRADE_MAX; n++) {   // upgrade 0..3, precomputed
    .for (var r = 0; r < 21; r++) {
        .byte upgradeByte(n, r, 0), upgradeByte(n, r, 1), upgradeByte(n, r, 2)
    }
    .byte $00
}
hudBitmapsEnd:
.if (hudBitmapsEnd - hudBitmaps != HUD_BLOCKS * 64) {
    .error "HUD bitmaps must be exactly HUD_BLOCKS x 64 bytes"
}

// ===========================================================================
// Main-thread code. Never called from an interrupt.
// ===========================================================================
* = $1400 "hud code"

// ---------------------------------------------------------------------------
// hudInit — draw every run-time bitmap once, so nothing is blank at boot.
// ---------------------------------------------------------------------------
hudInit:
    lda #HUD_DIRTY_LIVES | HUD_DIRTY_HEAT | HUD_DIRTY_SCORE | HUD_DIRTY_UPGRADE
    sta hudDirty
    lda #$ff
    sta hudHeatPix                      // force the bar to be drawn
    jsr hudRenderLives
    jsr hudRenderUpgrade
    jsr hudHeatFrame                    // static, drawn once
    jsr hudRenderHeat
    jsr hudRenderScore
    lda #0
    sta hudDirty
    rts

// ---------------------------------------------------------------------------
// hudUpdate — MAIN THREAD. Rebuild whatever is dirty, inside the safe window.
//
// Called from the main loop's idle spin rather than from the once-per-frame
// block, and the difference matters. The per-frame block runs immediately after
// the frame transaction, so it reaches this point at around raster 10 -- inside
// the window where the VIC is fetching HUD sprite data. The spin covers the
// rest of the frame, so a deferred update finds its slot within a few hundred
// microseconds.
// ---------------------------------------------------------------------------
hudUpdate:
    lda hudDirty
    bne !work+
    rts                                 // the common case: five cycles
!work:
    // THE REFUSAL. $d012 is the low byte of the raster, but readings of 56..199
    // are unambiguous: the wrapped range 256..311 reads back as 0..55.
    lda $d012
    cmp #HUD_SAFE_LO
    bcc hudDefer
    cmp #HUD_SAFE_HI
    bcs hudDefer

    sta hu_start
    cmp hudUpdStartMax
    bcc !notMax+
    sta hudUpdStartMax
!notMax:
    cmp hudUpdStartMin
    bcs !notMin+
    sta hudUpdStartMin
!notMin:

hudUpdWork:                             // traced: the cost of a real update is
                                        // measured between here and hudUpdEnd
    lda hudDirty
    and #HUD_DIRTY_LIVES
    beq !noLives+
    jsr hudRenderLives
!noLives:
    lda hudDirty
    and #HUD_DIRTY_UPGRADE
    beq !noUpg+
    jsr hudRenderUpgrade
!noUpg:
    lda hudDirty
    and #HUD_DIRTY_HEAT
    beq !noHeat+
    jsr hudRenderHeat
!noHeat:
    lda hudDirty
    and #HUD_DIRTY_SCORE
    beq !noScore+
    jsr hudRenderScore
!noScore:
    lda #0
    sta hudDirty                        // every component is now drawn

    inc hudUpdRuns
    bne !counted+
    inc hudUpdRuns + 1
!counted:
    // DID IT LEAVE THE FRAME? The update is bounded, so the raster must still
    // be ahead of where it started. If it is not, the update ran past raster
    // 311 into the next frame and therefore crossed 16..37 -- the one thing
    // this window exists to prevent, counted rather than assumed away.
    //
    // $d012 IS THE LOW BYTE OF A NINE-BIT COUNTER, and bit 7 of a $d011 READ is
    // the ninth. Comparing the low byte alone calls raster 260 "4" and scores a
    // perfectly ordinary update as a wrap, so RST8 must be read first or this
    // counter means nothing.
    lda $d012
    cmp hudUpdEndMax
    bcc !notEnd+
    sta hudUpdEndMax
!notEnd:
    lda $d011
    and #$80
    bne !noWrap+                        // raster >= 256: still ahead of a start
                                        // that is always 56..199, so no wrap
    lda $d012
    cmp hu_start
    bcs !noWrap+
    lda hudUpdWrapped
    cmp #$ff
    beq !noWrap+
    inc hudUpdWrapped
!noWrap:
hudUpdEnd:
    rts

hudDefer:
    inc hudUpdDeferred
    bne !done+
    inc hudUpdDeferred + 1
!done:
    rts

hu_start:  .byte 0

// ---------------------------------------------------------------------------
// hudRenderLives / hudRenderUpgrade — the pointer IS the update.
//
// Six lives values and four upgrade states, each with its own bitmap built at
// assembly time, so there is nothing to draw. One byte of hudPtrLive changes,
// and a single byte store cannot be seen half-written by the interrupt that
// reads it. These two components are therefore atomic whatever the raster is
// doing; they go through the window only because they share hudUpdate with the
// two that are not.
// ---------------------------------------------------------------------------
hudRenderLives:
    lda hudLives
    cmp #HUD_LIVES_MAX + 1
    bcc !ok+
    lda #HUD_LIVES_MAX                  // CAP: an out-of-range value selects a
!ok:                                    // real bitmap, never one past the table
    clc
    adc #HUD_PTR_LIVES_0
    sta hudPtrLive + 0                  // HW2
    rts

hudRenderUpgrade:
    lda hudUpgrade
    cmp #HUD_UPGRADE_MAX + 1
    bcc !ok+
    lda #HUD_UPGRADE_MAX
!ok:
    clc
    adc #HUD_PTR_UPGRADE_0
    sta hudPtrLive + 5                  // HW7
    rts

// ---------------------------------------------------------------------------
// hudSetHeatColour — A = the colour both halves of the gauge should be.
//
// Two single-byte stores into the table exHud reads, which is the same
// mechanism, and the same atomicity argument, as hudRenderLives writing one
// byte of hudPtrLive: a byte store cannot be observed half-written by the
// interrupt that reads it. No sei, no bitmap, no VIC register.
//
// It exists so that gameplay has somewhere to say "the gauge should look
// alarmed" without reaching into a table it does not own.
// ---------------------------------------------------------------------------
hudSetHeatColour:
    sta hudCol + 1                      // HW3, heat left
    sta hudCol + 2                      // HW4, heat right
    rts

// ---------------------------------------------------------------------------
// hudHeatPixels — logical heat to filled pixels. No division, no loop.
// Saturating at both ends by construction: the index is clamped to the table.
// Returns A = 0..48.
// ---------------------------------------------------------------------------
hudHeatPixels:
    lda hudHeatHi
    sta hh_hi
    lda hudHeatLo
    sta hh_lo
    lsr hh_hi
    ror hh_lo                           // >> 1
    lsr hh_hi
    ror hh_lo                           // >> 2, so 0..300 becomes 0..75
    lda hh_hi
    bne !over+                          // anything above 1023 is nonsense input
    lda hh_lo
    cmp #76
    bcc !inRange+
!over:
    lda #75                             // saturate rather than index off the end
!inRange:
    tax
    lda heatPix,x
    rts

// ---------------------------------------------------------------------------
// hudRenderHeat — the 48-pixel bar across HW3 and HW4.
// Counted loops only; the cost does not depend on the value.
// ---------------------------------------------------------------------------
hudRenderHeat:
    jsr hudHeatPixels
    sta hudHeatPix                      // remember what is actually drawn
    cmp #25
    bcc !small+
    sec
    sbc #24
    sta hh_right                        // left half full, right takes the rest
    lda #24
    sta hh_left
    jmp !have+
!small:
    sta hh_left
    lda #0
    sta hh_right
!have:
    ldx hh_left
    lda barOfs,x
    tax
    jsr hudBarBytes
    ldy #HUD_HEAT_ROW0 * 3
    ldx #HUD_HEAT_ROWS
!rowL:
    lda hh_b0
    sta HUD_HEAT_L,y
    iny
    lda hh_b1
    sta HUD_HEAT_L,y
    iny
    lda hh_b2
    sta HUD_HEAT_L,y
    iny
    dex
    bne !rowL-

    ldx hh_right
    lda barOfs,x
    tax
    jsr hudBarBytes
    ldy #HUD_HEAT_ROW0 * 3
    ldx #HUD_HEAT_ROWS
!rowR:
    lda hh_b0
    sta HUD_HEAT_R,y
    iny
    lda hh_b1
    sta HUD_HEAT_R,y
    iny
    lda hh_b2
    sta HUD_HEAT_R,y
    iny
    dex
    bne !rowR-
    rts

// ---------------------------------------------------------------------------
// hudHeatFrame — the gauge outline, drawn ONCE at init and never again.
//
// Without it an empty bar is an empty sprite and the gauge has no visible
// extent, which makes "heat is at zero" and "the HUD is broken" look the same.
// The rows above and below the fill are outside the range hudRenderHeat
// touches, so they survive every redraw for free.
// ---------------------------------------------------------------------------
hudHeatFrame:
    lda #$ff
    sta HUD_HEAT_L + (HUD_HEAT_ROW0 - 1) * 3 + 0
    sta HUD_HEAT_L + (HUD_HEAT_ROW0 - 1) * 3 + 1
    sta HUD_HEAT_L + (HUD_HEAT_ROW0 - 1) * 3 + 2
    sta HUD_HEAT_L + (HUD_HEAT_ROW0 + HUD_HEAT_ROWS) * 3 + 0
    sta HUD_HEAT_L + (HUD_HEAT_ROW0 + HUD_HEAT_ROWS) * 3 + 1
    sta HUD_HEAT_L + (HUD_HEAT_ROW0 + HUD_HEAT_ROWS) * 3 + 2
    sta HUD_HEAT_R + (HUD_HEAT_ROW0 - 1) * 3 + 0
    sta HUD_HEAT_R + (HUD_HEAT_ROW0 - 1) * 3 + 1
    sta HUD_HEAT_R + (HUD_HEAT_ROW0 - 1) * 3 + 2
    sta HUD_HEAT_R + (HUD_HEAT_ROW0 + HUD_HEAT_ROWS) * 3 + 0
    sta HUD_HEAT_R + (HUD_HEAT_ROW0 + HUD_HEAT_ROWS) * 3 + 1
    sta HUD_HEAT_R + (HUD_HEAT_ROW0 + HUD_HEAT_ROWS) * 3 + 2
    rts

hudBarBytes:                            // X = offset into barFill
    lda barFill + 0,x
    sta hh_b0
    lda barFill + 1,x
    sta hh_b1
    lda barFill + 2,x
    sta hh_b2
    rts

hh_lo:    .byte 0
hh_hi:    .byte 0
hh_left:  .byte 0
hh_right: .byte 0
hh_b0:    .byte 0
hh_b1:    .byte 0
hh_b2:    .byte 0

// ---------------------------------------------------------------------------
// hudRenderScore — six fixed-width digits, leading zeros always shown.
//
// Fully unrolled: each digit is one byte column of a sprite, so drawing one is
// eight loads and eight stores with no shifting. Straight-line code, identical
// cost for every possible score, and nothing that can loop on data.
// ---------------------------------------------------------------------------
hudRenderScore:
.for (var c = 0; c < 6; c++) {
    .var spr = (c < 3) ? HUD_SCORE_L : HUD_SCORE_R
    .var col = c - (c < 3 ? 0 : 3)
    lda hudScore + c
    asl
    asl
    asl                                 // digit * 8 = its row 0 in digitGlyph
    tax
    .for (var r = 0; r < 8; r++) {
        lda digitGlyph + r, x
        sta spr + (HUD_SCORE_ROW0 + r) * 3 + col
    }
}
    rts

// ---------------------------------------------------------------------------
// hudScoreBump — add one at digit position X, carrying left. At most six
// iterations, and it stops rather than wrapping past the top digit.
// ---------------------------------------------------------------------------
hudScoreBump:
!carry:
    inc hudScore,x
    lda hudScore,x
    cmp #10
    bcc !done+
    lda #0
    sta hudScore,x
    dex
    bpl !carry-
!done:
    lda hudDirty
    ora #HUD_DIRTY_SCORE
    sta hudDirty
    rts

// ---------------------------------------------------------------------------
// hudDemoTick — MAIN THREAD, once per displayed frame.
//
// A deterministic placeholder for the three components no game system feeds
// yet. The cadences are deliberately DIFFERENT and mostly slow: components
// changing together every frame would let a tear or a slot-ownership mistake
// hide inside the motion.
//
//   score     +10 every 8 frames                              (~1.6 per second)
//   upgrade   next state every 192 frames, 0 -> 3 -> 0        (~3.8s)
//
// LIVES ARE NO LONGER HERE: src/player.asm owns hudLives. See below.
//
// HEAT IS NOT DRIVEN HERE. src/weapon.asm feeds hudHeatLo/Hi from the real
// weapon through weaponHudFeed. Whatever comes to own score, lives or upgrade
// must likewise REPLACE the block below rather than run alongside it: two
// writers of one logical value is how a HUD starts disagreeing with the game
// it is describing.
// ---------------------------------------------------------------------------
hudDemoTick:
    inc hudDemoFrame
    bne !noHi+
    inc hudDemoFrame + 1
!noHi:

    // ---- score: +10 every 8 frames ---------------------------------------
    lda hudDemoFrame
    and #7
    bne !noScore+
    ldx #4                              // the tens digit
    jsr hudScoreBump
!noScore:

    // ---- lives: NOT DRIVEN HERE ANY MORE ---------------------------------
    // src/player.asm's playerTakeHit owns hudLives now, and the note above
    // required exactly that: whatever comes to own a value REPLACES this block
    // rather than running alongside it. The placeholder that cycled 5 -> 0 -> 5
    // on a 128-frame timer is gone, because two writers of one logical value is
    // how a HUD starts disagreeing with the game it is describing.

    // ---- upgrade: next state every 192 frames ----------------------------
    inc hudDemoUpgTick
    lda hudDemoUpgTick
    cmp #192
    bcc !noUpg+
    lda #0
    sta hudDemoUpgTick
    inc hudUpgrade
    lda hudUpgrade
    cmp #HUD_UPGRADE_MAX + 1
    bcc !upgOk+
    lda #0
    sta hudUpgrade
!upgOk:
    lda hudDirty
    ora #HUD_DIRTY_UPGRADE
    sta hudDirty
!noUpg:
    rts

hudDemoFrame:   .byte 0, 0
hudDemoUpgTick: .byte 0

.if (* > $1800) { .error "the HUD code has grown past its $1800 ceiling" }
