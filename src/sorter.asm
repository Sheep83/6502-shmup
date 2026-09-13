// ===========================================================================
// sorter.asm — P4 dynamic Y sorter
// ===========================================================================
// MAIN THREAD ONLY. The raster executor never reads one byte of this file.
//
//     motionTick     logical sprites get their final X/Y for this frame
//     sortTick       <- here: order logical IDs by Y
//     buildSchedule  consumes the ORDERED ID list, applies the i-6 reuse rule
//     publishSchedule one byte
//     frame IRQ      adopts CURRENT
//     executor       consumes CURRENT only
//
// Nothing is sorted after admission. Nothing re-decides admission after
// sorting. The executor is never told that anything was reordered.
//
// THREE IDENTITIES, KEPT SEPARATE
//   logical sprite ID   stable for the life of a fixture; indexes logY/logX/...
//   sorted position     where that sprite currently sits in Y order
//   accepted index      its position in the schedule, which sets its physical
//                       slot (MUX_FIRST_SLOT + accepted mod 6) and its
//                       same-slot predecessor (accepted - 6)
//
// A sprite moves between sorted positions freely without changing identity.
// The logical arrays are therefore NEVER physically reordered: they stay keyed
// by logical ID, and sortedIDs is a permutation of IDs laid over the top. Array
// position is never identity.
//
// ---------------------------------------------------------------------------
// THE COMPARATOR IS A TOTAL ORDER, AND THAT IS THE WHOLE ARGUMENT
// ---------------------------------------------------------------------------
//     a before b  <=>  logY[a] < logY[b]
//                 or  (logY[a] == logY[b] and a < b)
//
// Logical IDs are unique, so no two elements ever compare equal: the order is
// TOTAL, and a totally ordered set has exactly ONE ascending arrangement.
//
// That single fact is what makes a PERSISTENT sort safe here. The array this
// routine starts from is last frame's answer, but the array it finishes with is
// the unique correct order for THIS frame's Y values no matter what it started
// from. Persistence therefore affects only how much WORK is done, never the
// result -- which is exactly the property the equal-Y policy demands, and it is
// tested by scrambling sortedIDs behind the engine's back and checking it
// converges to the same list.
//
// Had the tie-break been omitted, equal-Y sprites would compare equal, the
// order would be a partial one, and the output would depend on the incoming
// arrangement -- i.e. on last frame's accident. P2 relies on merged batches,
// which are precisely groups of equal-Y sprites, so that would have been a real
// bug and not a theoretical one.
//
// ---------------------------------------------------------------------------
// WHY INSERTION SORT, PERSISTENTLY
// ---------------------------------------------------------------------------
// Measured alternatives are in docs/p4-dynamic-y-sorter.md. The short version:
//
//   * sprites move a few rasters per frame, so the list handed to this routine
//     is the correct order or within a couple of adjacent swaps of it. Insertion
//     sort costs O(N + inversions), which for that input is one comparison per
//     element and nothing else;
//   * a distribution/bucket sort over the 256 possible Y values pays a fixed
//     clear-and-walk cost EVERY frame regardless of how few sprites moved. With
//     the main thread already the scarce resource after P3, a fixed multi-
//     thousand-cycle floor is the wrong shape;
//   * selection sort is O(N^2) always: predictable and always expensive.
//
// The price is an O(N^2) worst case when the incoming order is far from
// correct, which happens on exactly one event -- loading a fixture whose
// logical storage order is deliberately scrambled. That cost is measured and
// reported rather than assumed away.
//
// sortWork counts shifts, so the cost of any frame is visible after the fact:
// sortWork == 0 means the list was already in order on entry, which is also the
// engine's own statement that nothing needed reordering.
// ===========================================================================

// ===========================================================================
// Sorter state.
// ===========================================================================
// In the logical-sprite-state segment, with the arrays it indexes, outside VIC
// bank 0 with everything else the main thread owns.
* = $c3b0 "sorter state"

// The output contract: sortedIDs[0 .. sortedCount-1] are logical sprite IDs,
// each appearing exactly once, with logY[sortedIDs[i]] <= logY[sortedIDs[i+1]].
sortedIDs:   .fill MAX_LOGICAL, 0
sortedCount: .byte 0

// MEMBERSHIP. sortedIDs[0 .. sortedCount-1] holds exactly the logical IDs whose
// logActive is 1 -- no more and no less. P4 had no such concept: every logical
// sprite was sorted, sortedCount was always logCount, and membership was the
// implicit prefix "ID < logCount". Slice C replaced that prefix with an explicit
// bit, because a dynamic pool frees slots out of the middle and a prefix cannot
// describe that. See sortRebuild for the failure the prefix model produced.
//
// VISIBILITY is still a separate question and still has no implementation:
// every ACTIVE sprite is offered to the builder, and the builder alone decides
// what is renderable. If culling is ever added it belongs between the update and
// the sort, and only sortRebuild changes.

// Diagnostics. Main thread only; none of this is on the executor's path.
sortWork:    .byte 0, 0                 // shifts performed this frame, 16-bit.
                                        // 0 = the list arrived already ordered.
sortFault:   .byte 0                    // saturating. Non-zero is a failure.

// Locals.
st_i:     .byte 0                       // outer index: the element being placed
st_key:   .byte 0                       // its logical ID
st_keyY:  .byte 0                       // its Y, held so the inner loop need
                                        // not re-read it through two indexes

// ---------------------------------------------------------------------------
// sortDirty — MEMBERSHIP has changed since the last rebuild.
//
// Set by objectActivate and objectFree, and by sortReset for a fixture load.
// It is NOT set when an object merely MOVES: a move changes the ORDER, which
// the persistent insertion sort handles for free, and rebuilding for that
// would throw away the whole reason the sort is persistent.
// ---------------------------------------------------------------------------
sortDirty: .byte 0

* = $1e00 "sorter"

// ===========================================================================
// sortReset — start a fixture from the identity permutation.
// ===========================================================================
// Called by the fixture loader. Without it a newly loaded fixture would inherit
// the previous fixture's permutation, which may name IDs that no longer exist:
// sortedIDs must always be a permutation of 0..sortedCount-1, and the loader is
// the only place that can guarantee it.
//
// The identity permutation is deliberately NOT "already sorted". A P4 fixture
// whose logical storage order is scrambled starts maximally out of order on
// purpose, and the first sortTick is what proves the sorter and not the
// fixture table.
sortReset:
    lda logCount
    sta sortedCount
    ldx #0
!loop:
    txa
    sta sortedIDs,x
    // MEMBERSHIP FOR A FIXTURE IS THE PREFIX "ID < logCount", and this is the
    // one place that is still true. Writing it into logActive rather than
    // leaving it implicit is what lets the sorter ask ONE question about
    // membership regardless of whether a fixture or the object pool populated
    // the arrays.
    cpx logCount
    lda #0                              // A = (X < logCount), written plainly:
    bcs !store+                         // a BIT-skip would save one byte here
    lda #1                              // and cost every future reader a pause
!store:
    sta logActive,x
    inx
    cpx #MAX_LOGICAL
    bcc !loop-
    lda #0
    sta sortFault
    sta sortWork
    sta sortWork + 1
    sta sortDirty                       // sortedIDs above IS the rebuild: the
    rts                                 // identity permutation over an active
                                        // prefix is exactly what sortRebuild
                                        // would produce for it

// ===========================================================================
// sortRebuild — make sortedIDs name exactly the active logical IDs.
// ===========================================================================
// THE BUG THIS EXISTS TO KILL, stated exactly, because it was reproduced on
// the running machine before it was fixed:
//
//   sortedIDs is a permutation of ALL logical IDs and sortedCount is a WINDOW
//   over its front. sortTick used to set that window from logCount every frame
//   while sorting only what the window already contained. Order and membership
//   are different things, and resizing a window does not change what is inside
//   it.
//
//   Four objects at Y 200/100/150/120 sort to sortedIDs = [1,3,2,0]. Object 3
//   despawns, so the population is three. The window shrinks to three and the
//   builder now walks [1,3,2]:
//
//       ID 3 is DESPAWNED and still rendered -- a ghost;
//       ID 0 is ALIVE and outside the window -- it vanishes.
//
//   One despawn, both failure modes, no fault counter raised anywhere. That is
//   measured output, not a hypothesis: /tmp/prove_stale.py reproduced it.
//
// THE FIX IS TO REBUILD THE CONTENTS, not to resize a window. Active IDs are
// compacted to the front in ascending order and sortedCount is the count of
// them -- so an ID that is not active cannot be in the window at all, and an
// ID that is active cannot be outside it. The property is now structural
// rather than something a caller must maintain.
//
// The inactive IDs are appended behind the window rather than abandoned, which
// keeps sortedIDs a permutation of 0..MAX_LOGICAL-1 at all times. The sort
// never looks past sortedCount, so this costs nothing it needs -- but a
// permutation is far easier to assert about from a test than an array with
// arbitrary residue in its tail, and P4's tests already assert exactly that.
//
// Cost: two passes over MAX_LOGICAL, on membership-change frames only. A frame
// in which objects merely move does not come here at all, which is what
// preserves the persistent sort's whole reason for existing.
// ===========================================================================
sortRebuild:
    ldx #0                              // X = source ID
    ldy #0                              // Y = write cursor, front of sortedIDs
!active:
    lda logActive,x
    beq !skip+
    txa
    sta sortedIDs,y
    iny
!skip:
    inx
    cpx #MAX_LOGICAL
    bne !active-

    sty sortedCount                     // THE window is the count of actives

    ldx #0                              // second pass: the inactive tail, so
!inactive:                              // sortedIDs stays a permutation
    lda logActive,x
    bne !skipInactive+
    txa
    sta sortedIDs,y
    iny
!skipInactive:
    inx
    cpx #MAX_LOGICAL
    bne !inactive-
    rts

// ===========================================================================
// sortTick — order sortedIDs by (Y, logical ID). MAIN THREAD ONLY.
// ===========================================================================
sortTick:
    lda #0
    sta sortWork
    sta sortWork + 1

    // MEMBERSHIP FIRST, ORDER SECOND.
    //
    // This used to read `lda logCount / sta sortedCount`, and that single line
    // was the stale-ID bug: it resized the window over sortedIDs without
    // rebuilding its CONTENTS, so a shrink left despawned IDs inside the window
    // and pushed live ones out of it. See sortRebuild.
    lda sortDirty
    beq !ordered+
    jsr sortRebuild
    lda #0
    sta sortDirty
!ordered:

    lda sortedCount
    cmp #2
    bcs st_go
    rts                                 // 0 or 1 elements are already ordered

st_go:
    lda #1
    sta st_i

st_outer:
    lda st_i
    cmp sortedCount
    bcs st_done

    ldy st_i
    lda sortedIDs,y
    sta st_key                          // the ID being placed
    tax
    lda logY,x
    sta st_keyY                         // and its Y

    dey                                 // j = i - 1

st_inner:
    // Does the element at j belong BEFORE the key? Compare (Y, ID) as one
    // lexicographic key, high part first.
    lda sortedIDs,y
    tax
    lda logY,x
    cmp st_keyY
    bcc st_place                        // Y[j] <  keyY: key belongs after j
    bne st_shift                        // Y[j] >  keyY: j must move up
    // Equal Y: the tie-break decides, and it is what makes the order total.
    cpx st_key
    bcc st_place                        // ID[j] < key: key belongs after j
                                        // ID[j] > key: j must move up.
                                        // Equal is impossible -- IDs are unique.

st_shift:
    lda sortedIDs,y
    iny
    sta sortedIDs,y                     // sortedIDs[j+1] = sortedIDs[j]
    dey
    inc sortWork
    bne !counted+
    inc sortWork + 1
!counted:
    dey                                 // j = j - 1
    bpl st_inner
    ldy #$ff                            // ran off the front: place at index 0

st_place:
    iny
    lda st_key
    sta sortedIDs,y

    inc st_i
    jmp st_outer

st_done:
    // The only integrity condition the engine can check for free. Everything
    // else the contract promises -- no duplicate, no missing ID, adjacent pairs
    // ordered, the tie rule obeyed -- is structural: this routine only ever
    // MOVES entries that were already in the array, so it cannot invent or lose
    // an ID, and it terminates with the array ordered by construction. Paying
    // O(N) every frame to re-check a property the algorithm guarantees would
    // spend main-thread budget -- the scarce resource after P3 -- on
    // reassurance. tests/test_p4.py reads sortedIDs and verifies all of it
    // exhaustively instead, which costs the engine nothing.
    // sortedCount came from logActive; logCount came from the alloc/free calls.
    // They are two independent representations of the same fact, so comparing
    // them is a real integrity check rather than a tautology -- it catches a
    // spawner that set a membership bit without going through objectActivate.
    lda sortedCount
    cmp logCount
    beq !ok+
    lda sortFault
    cmp #$ff
    beq !ok+
    inc sortFault
!ok:
    rts
