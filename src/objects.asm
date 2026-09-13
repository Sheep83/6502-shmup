// ===========================================================================
// objects.asm — the production logical object pool
// ===========================================================================
// MAIN THREAD ONLY. The raster executor never reads one byte of this file.
//
// This is the gameplay side of the engine's oldest boundary:
//
//     objectUpdateAll   gameplay decides where its objects ARE
//     (presentation)    and writes logY/logX/logXHi/logPtr/logCol
//     sortTick          orders the ACTIVE logical IDs by Y
//     buildSchedule     decides which of them are RENDERABLE this frame
//     publishSchedule   one byte
//     executor          consumes CURRENT only
//
// GAMEPLAY OWNS "ACTIVE". THE RENDERER OWNS "RENDERABLE THIS FRAME".
// Nothing in this file knows that hardware sprites exist. There is no slot
// number here, no $d015 bit, no pointer table, no raster. An object that the
// builder rejects for Y range, for capacity or for reuse spacing is still
// perfectly alive; it simply is not drawn this frame.
//
// ---------------------------------------------------------------------------
// WHAT WAS RECOVERED FROM THE OLD GAME
// ---------------------------------------------------------------------------
// Read out of shooter_test/src/main.asm before this file was written:
// findFreeObject (4842), spawnEnemy (4860), the OBJECT_* array block (5176)
// and the release paths at 3047 and 3169.
//
//   STRUCTURE OF ARRAYS, INDEXED BY SLOT. OBJECT_X,x / OBJECT_Y,x / ... with
//   MAX_OBJECTS = 16. One indexed load per field, no record stride, no
//   multiply. That layout is kept exactly.
//
//   OBJECT_ACTIVE IS THE MEMBERSHIP BIT and a zero there is what returns a slot
//   to the pool. Kept, as logActive.
//
//   ALLOCATION IS A BOUNDED LINEAR SCAN returning carry set on failure. Kept.
//
//   "Mark object active only after every field is initialised." The old game
//   says this twice, at 4922 and 2971, and it is why alloc and activate are
//   two calls here rather than one.
//
//   "Reused slots must not inherit velocity from a previous enemy." The old
//   spawn path hand-zeroes five fields for exactly this reason. Rather than
//   trust a future spawner to remember the list, objectAlloc zeroes the WHOLE
//   slot -- gameplay fields and presentation alike -- before it hands it out.
//
//   "Defensive guard against an accidental double release" (3050). Kept, and
//   given a counter so a double free is visible rather than merely survivable.
//
// DELIBERATELY NOT TAKEN:
//   * OBJECT_HEALTH / OBJECT_HIT_TIMER / OBJECT_DEATH_TIMER — there is no
//     damage model until Slice D.
//   * OBJECT_PATH_STEP / STAGE / MANOEUVRE / EGRESS / TARGET_VEL / ACCEL_TIMER
//     — the segmented path system is the wave migration, not this slice.
//   * OBJECT_BASE_SPRITE / OBJECT_BASE_COLOUR — they exist only to restore a
//     colour after an impact flash, which is Slice D.
//   * slot 0 reserved for the player. In THIS engine the player is not in the
//     pool at all: it owns HW0/HW1 outright and never enters the mux. Slot 0
//     is therefore an ordinary slot here.
// ===========================================================================

// The old game's pool size, kept. Sixteen is also the top of the performance
// ladder this slice measures, and comfortably under MAX_SCHED.
.const MAX_OBJECTS = 16

.if (MAX_OBJECTS > MAX_LOGICAL) {
    .error "the object pool cannot be larger than the logical sprite arrays"
}

// Object types. TYPE_NONE is 0 so a zeroed slot is typeless by construction.
.const TYPE_NONE     = 0
.const TYPE_ENEMY    = 1

// ===========================================================================
// State. MAIN THREAD ONLY.
// ===========================================================================
* = $c580 "object pool state"

// ---------------------------------------------------------------------------
// logActive — THE membership bit, and the sorter's only source of truth about
// which logical IDs exist.
//
// It is MAX_LOGICAL long rather than MAX_OBJECTS long because the sorter must
// be able to ask the question about any logical ID a fixture might name, and
// the P0-P5 qualification fixtures populate all thirty-two.
//
//     production  uses logical IDs 0..MAX_OBJECTS-1 through this pool
//     fixtures    use logical IDs 0..logCount-1 through sortReset
//
// The two populations are mutually exclusive: a production boot loads no
// fixture and a fixture run spawns no object. Nothing enforces that at
// assembly time because nothing can -- it is a property of which routine the
// frame calls -- so it is stated here and checked by the test suite.
// ---------------------------------------------------------------------------
logActive:   .fill MAX_LOGICAL, 0

// Per-object gameplay state. NOT presentation: logY/logX/logXHi/logPtr/logCol
// in src/motion.asm are the presentation view, and they are written by the
// object's own update.
objType:     .fill MAX_OBJECTS, 0
objVX:       .fill MAX_OBJECTS, 0        // signed, whole pixels per frame
objVY:       .fill MAX_OBJECTS, 0        // signed, whole pixels per frame

// Diagnostics. Saturating where a count could run away.
objPeak:     .byte 0                     // high-water mark of logCount
objAllocFail: .byte 0                    // allocations refused: the pool was full
objDoubleFree: .byte 0                   // frees of an already-free slot

objectStateEnd:
.if (objectStateEnd > $c600) { .error "the object pool state has grown into the P3 fixture data at $c600" }

// ===========================================================================
// Code. MAIN THREAD ONLY, outside VIC bank 0 with the player, the scroller and
// the weapon.
// ===========================================================================
* = $4800 "object pool"

// ---------------------------------------------------------------------------
// objectInit — an empty pool. Every slot free, nothing to sort.
// ---------------------------------------------------------------------------
objectInit:
    lda #0
    ldx #MAX_LOGICAL - 1
!clearActive:
    sta logActive,x
    dex
    bpl !clearActive-

    ldx #MAX_OBJECTS - 1
!clearSlot:
    jsr objectZeroSlot
    dex
    bpl !clearSlot-

    lda #0
    sta logCount                        // the active count, and the sorter
    sta objPeak                         // cross-checks it against membership
    sta objAllocFail
    sta objDoubleFree
    lda #1
    sta sortDirty                       // an empty pool is still a MEMBERSHIP
    rts                                 // change the sorter has not seen

// ---------------------------------------------------------------------------
// objectZeroSlot — every field of slot X, gameplay and presentation together.
//
// The old game zeroed five named fields on spawn so that a reused slot could
// not inherit a previous enemy's velocity. Naming fields is how that list goes
// stale the first time someone adds a sixth, so this clears the slot whole.
// Entry/exit: X = slot, preserved.
// ---------------------------------------------------------------------------
objectZeroSlot:
    lda #0
    sta objType,x
    sta objVX,x
    sta objVY,x
    sta logY,x
    sta logX,x
    sta logXHi,x
    sta logPtr,x
    sta logCol,x
    rts

// ---------------------------------------------------------------------------
// objectAlloc — reserve a free slot WITHOUT activating it.
//
// Returns: carry clear and X = the slot, fully zeroed and ready to fill;
//          carry set and the pool untouched if every slot is in use.
//
// The slot is NOT yet active and NOT yet visible to the sorter. That is the
// old game's rule -- "mark object active only after every field is
// initialised" -- expressed as two calls, so that a half-built object cannot
// be named by sortedIDs even for one frame.
// ---------------------------------------------------------------------------
objectAlloc:
    ldx #0
!scan:
    lda logActive,x
    beq !found+
    inx
    cpx #MAX_OBJECTS
    bne !scan-

    lda objAllocFail                    // saturating: that it happened matters,
    cmp #$ff                            // the exact count past 255 does not
    beq !full+
    inc objAllocFail
!full:
    sec                                 // pool full; X is meaningless
    rts

!found:
    jsr objectZeroSlot                  // a reused slot inherits NOTHING
    clc
    rts

// ---------------------------------------------------------------------------
// objectActivate — slot X joins the active set.
//
// This is the only routine that can GROW membership, and it is therefore one
// of exactly two places that mark the sorter dirty.
// Entry/exit: X = slot, preserved.
// ---------------------------------------------------------------------------
objectActivate:
    lda logActive,x
    bne !already+                       // idempotent: activating an active slot
                                        // must not double-count it
    lda #1
    sta logActive,x
    inc logCount
    lda #1
    sta sortDirty

    lda logCount                        // high-water mark, for the ladder
    cmp objPeak
    bcc !already+
    sta objPeak
!already:
    rts

// ---------------------------------------------------------------------------
// objectFree — return slot X to the pool.
//
// The presentation is cleared as well as the membership bit. Nothing downstream
// requires that -- an inactive ID can no longer reach sortedIDs at all, which
// is the real fix -- but a freed slot that still holds last frame's Y is a
// booby trap for the next person to read the arrays in a debugger, and zeroing
// it costs eight stores on an event that happens a couple of times a second.
//
// NO VIC REGISTER IS TOUCHED, and none needs to be. The sprite this object was
// being drawn through is disabled by the next schedule the builder produces,
// because that schedule simply does not contain it.
// Entry/exit: X = slot, preserved.
// ---------------------------------------------------------------------------
objectFree:
    lda logActive,x
    bne !live+
    lda objDoubleFree                   // the old game's "defensive guard
    cmp #$ff                            // against an accidental double
    beq !done+                          // release", made visible
    inc objDoubleFree
!done:
    rts                                 // NOT an error: freeing a free slot is
                                        // a no-op, never a corruption
!live:
    lda #0
    sta logActive,x
    jsr objectZeroSlot
    lda logCount
    beq !noCount+                       // cannot underflow, ever
    dec logCount
!noCount:
    lda #1
    sta sortDirty
    rts

// ---------------------------------------------------------------------------
// objectUpdateAll — one frame of every active object. MAIN THREAD.
//
// Dispatch is a type test rather than a jump table: there is one type. A table
// arrives with the second type, and not before.
// ---------------------------------------------------------------------------
objectUpdateAll:
    ldx #0
!loop:
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !next+
    jsr enemyTick                       // may free slot X; X is preserved
!next:
    inx
    cpx #MAX_OBJECTS
    bne !loop-
    rts
