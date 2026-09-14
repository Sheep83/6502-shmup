// ===========================================================================
// sorter.asm — orders the active logical sprites by Y for the schedule builder
// ===========================================================================
// MAIN THREAD ONLY. The raster executor never reads one byte of this file.
// sortTick runs between the gameplay update and buildSchedule, which consumes
// the ordered ID list and applies the i-6 reuse rule. Nothing is sorted after
// admission, nothing re-decides admission after sorting, and the executor is
// never told that anything was reordered.
//
// THREE IDENTITIES, KEPT SEPARATE
//   logical sprite ID   stable for the life of the object; indexes logY/logX/...
//   sorted position     where that sprite currently sits in Y order
//   accepted index      its position in the schedule, which sets its physical
//                       slot (MUX_FIRST_SLOT + accepted mod 6) and its
//                       same-slot predecessor (accepted - 6)
//
// A sprite moves between sorted positions freely without changing identity, so
// the logical arrays are NEVER physically reordered: they stay keyed by logical
// ID and sortedIDs is a permutation of IDs laid over the top. Array position is
// never identity.
//
// THE COMPARATOR IS A TOTAL ORDER, which is what licenses the persistent sort:
//
//     a before b  <=>  logY[a] < logY[b]
//                 or  (logY[a] == logY[b] and a < b)
//
// Logical IDs are unique, so no two elements ever compare equal; a totally
// ordered set has exactly ONE ascending arrangement. This routine starts from
// last frame's answer but finishes with the unique correct order for THIS
// frame's Y values whatever it started from, so persistence affects how much
// WORK is done and never the result. Drop the ID tie-break and equal-Y sprites
// compare equal, the order becomes partial, and the output starts depending on
// last frame's accident -- which matters because equal-Y sprites are exactly
// what the builder merges into a batch.
//
// INSERTION SORT, because sprites move a few rasters per frame: the incoming
// list is already correct or within a couple of adjacent swaps of it, and
// insertion sort costs O(N + inversions) -- one comparison per element on that
// input. A distribution sort over the 256 Y values would pay a fixed
// clear-and-walk cost every frame however little moved, and the main thread is
// the scarce resource. The price is an O(N^2) worst case on an input far from
// order, which ordinary play does not produce.
//
// sortWork counts shifts, so a frame's cost is visible after the fact;
// sortWork == 0 means the list arrived already in order.
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
// logActive is 1 -- no more and no less. Membership is an explicit bit and not
// the prefix "ID < logCount", because the object pool frees slots out of the
// middle and a prefix cannot describe that. See sortRebuild.
//
// VISIBILITY is a separate question with no implementation here: every ACTIVE
// sprite is offered to the builder, and the builder alone decides what is
// renderable. Culling, if ever added, belongs between the update and the sort,
// and only sortRebuild would change.

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
// Set by objectActivate, objectFree and sortReset. It is NOT set when an object
// merely MOVES: a move changes the ORDER, which the persistent insertion sort
// handles for free, and rebuilding for that would throw away the whole reason
// the sort is persistent.
// ---------------------------------------------------------------------------
sortDirty: .byte 0

* = $1e00 "sorter"

// ===========================================================================
// sortReset — put sortedIDs into the identity permutation. Boot only.
// ===========================================================================
// sortedIDs must always be a permutation of 0..MAX_LOGICAL-1, never an array
// with arbitrary residue, so it needs one definite starting state; logActive is
// seeded from logCount here so that afterwards the sorter asks exactly one
// question about membership. gameInit calls this after objectInit, when the
// pool is empty and the active prefix is therefore empty too.
sortReset:
    lda logCount
    sta sortedCount
    ldx #0
!loop:
    txa
    sta sortedIDs,x
    // The one place membership is the prefix "ID < logCount". Writing it into
    // logActive rather than leaving it implicit is what lets everything after
    // boot ask a single question about membership.
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
// ORDER AND MEMBERSHIP ARE DIFFERENT THINGS, and this routine is what keeps
// them so. sortedCount is a window over the front of sortedIDs, and merely
// resizing that window does not change what is inside it. Four objects at Y
// 200/100/150/120 sort to sortedIDs = [1,3,2,0]; if object 3 despawns and the
// window is simply shrunk to three, the builder walks [1,3,2], so ID 3 is
// despawned and still drawn while ID 0 is alive and outside the window --
// a ghost and a disappearance from one despawn, with no fault raised anywhere.
//
// So the CONTENTS are rebuilt: active IDs compacted to the front in ascending
// order, sortedCount the count of them. An inactive ID then cannot be inside
// the window and an active one cannot be outside it, structurally, rather than
// by a rule callers must remember.
//
// The inactive IDs are appended behind the window rather than abandoned, so
// sortedIDs remains a permutation of 0..MAX_LOGICAL-1 at all times. The sort
// never looks past sortedCount, so the second pass buys the sort nothing; it
// buys a state that can be asserted about cheaply from outside.
//
// Cost: two passes over MAX_LOGICAL, on membership-change frames only. A frame
// in which objects merely move never comes here, which is what preserves the
// persistent sort's reason for existing.
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

    // MEMBERSHIP FIRST, ORDER SECOND. sortedCount must never be set from
    // logCount directly: that resizes the window without rebuilding its
    // contents. See sortRebuild.
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
    // The only integrity condition worth paying for at runtime. The rest of the
    // contract -- no duplicate, no missing ID, adjacent pairs ordered, the tie
    // rule obeyed -- is structural: this routine only MOVES entries already in
    // the array, so it cannot invent or lose an ID, and it terminates ordered
    // by construction. Re-checking that every frame would spend main-thread
    // budget on reassurance.
    //
    // This check is not a tautology: sortedCount comes from logActive and
    // logCount from the alloc/free calls, two independent representations of
    // the same fact. A disagreement means a spawner set a membership bit
    // without going through objectActivate.
    lda sortedCount
    cmp logCount
    beq !ok+
    lda sortFault
    cmp #$ff
    beq !ok+
    inc sortFault
!ok:
    rts
