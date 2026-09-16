// ===========================================================================
// objects.asm — the logical object pool: enemies and hostile projectiles
// ===========================================================================
// MAIN THREAD ONLY. The raster executor never reads one byte of this file.
//
// Structure of arrays indexed by slot, so every field is one indexed load with
// no record stride and no multiply. objectUpdateAll runs each live object,
// which writes its own presentation into logY/logX/logXHi/logPtr/logCol;
// sortTick then orders the active IDs and buildSchedule decides which of them
// are renderable.
//
// GAMEPLAY OWNS "ACTIVE". THE RENDERER OWNS "RENDERABLE THIS FRAME".
// Nothing here knows hardware sprites exist -- no slot number, no $d015 bit,
// no pointer table, no raster. An object the builder rejects for Y range, for
// capacity or for reuse spacing is still perfectly alive; it is simply not
// drawn this frame.
//
// TWO INVARIANTS THIS POOL OWNS, both easy to break from outside:
//   * A SLOT IS ACTIVATED ONLY AFTER EVERY FIELD IS SET. That is why alloc and
//     activate are two calls: a half-built object must never be reachable
//     through sortedIDs, not even for one frame.
//   * A REUSED SLOT INHERITS NOTHING. objectZeroSlot clears the slot whole
//     rather than a named list of fields, so adding a field cannot quietly
//     leave it carrying the previous occupant's value.
//
// The player is not in this pool and never will be: it owns HW0/HW1 outright
// and never enters the mux, so slot 0 is an ordinary slot.
// ===========================================================================

// Sixteen slots: comfortably under MAX_SCHED, and more than the authored
// content puts on screen at once.
.const MAX_OBJECTS = 16

.if (MAX_OBJECTS > MAX_LOGICAL) {
    .error "the object pool cannot be larger than the logical sprite arrays"
}

// Object types. TYPE_NONE is 0 so a zeroed slot is typeless by construction.
.const TYPE_NONE     = 0
.const TYPE_ENEMY    = 1
// A HOSTILE PROJECTILE: an ordinary pool object with an ordinary logical
// presentation. The type is what keeps it out of things meant for enemies --
// src/collision.asm's traceRay filters on TYPE_ENEMY, so the player's weapon
// cannot shoot incoming bullets down.
.const TYPE_EBULLET  = 2
// A COLLECTIBLE TOKEN: an ordinary pool object with an ordinary logical
// presentation, and the type is what keeps it out of everything meant for the
// other two -- traceRay filters on TYPE_ENEMY so the player's cannon cannot
// shoot its own pickups down, and ebulletPlayerTick filters on TYPE_EBULLET so
// a token can never be mistaken for something that hurts. See src/pickup.asm.
.const TYPE_PICKUP   = 3

// --- what an ENEMY object is currently doing with itself ---------------------
// A second per-slot identity beside the type, and it lives HERE rather than in
// src/token.asm for one reason of import order: src/enemy.asm has to compare
// against ROLE_GUARD, and it is imported long before the token encounter that
// owns the behaviour. The pool is where per-slot meanings are declared, so this
// is where a per-slot meaning belongs.
//
// ROLE_NORMAL is 0 so a zeroed slot is on its authored path by construction,
// exactly as TYPE_NONE makes one typeless. The three guard posts are
// CONSECUTIVE from ROLE_GUARD, so "is this a guard" and "which post" are one
// compare and one subtract rather than two bytes that could disagree.
//
// Only src/token.asm ever writes a value other than ROLE_NORMAL; see the note
// at the top of that file for why the role is stored and never inferred.
.const ROLE_NORMAL   = 0    // flying the path its wave authored
.const ROLE_EGRESS   = 1    // dismissed from an encounter: leaving under WM_EXIT
.const ROLE_GUARD    = 2    // ...and +1, +2: the three posts around a token

// ===========================================================================
// State. MAIN THREAD ONLY.
// ===========================================================================
* = $c580 "object pool state"

// ---------------------------------------------------------------------------
// logActive — THE membership bit, and the sorter's only source of truth about
// which logical IDs exist. The pool issues IDs 0..MAX_OBJECTS-1; the array is
// MAX_LOGICAL long so that the sorter, which walks the whole logical ID space,
// reads a defined answer for every ID.
// ---------------------------------------------------------------------------
logActive:   .fill MAX_LOGICAL, 0

// Per-object gameplay state. NOT presentation: logY/logX/logXHi/logPtr/logCol
// in src/motion.asm are the presentation view, and they are written by the
// object's own update.
objType:     .fill MAX_OBJECTS, 0
objVX:       .fill MAX_OBJECTS, 0        // signed, whole pixels per frame
objVY:       .fill MAX_OBJECTS, 0        // signed, whole pixels per frame

// ---------------------------------------------------------------------------
// COMBAT. Two arrays carry four states, and the rule that makes that safe is
// written here rather than inferred at each use site:
//
//     objHP > 0,  objTimer == 0    alive, undamaged this moment
//     objHP > 0,  objTimer  > 0    alive, running the HIT FLASH
//     objHP == 0, objTimer  > 0    DYING; the timer is the death animation
//     objHP == 0, objTimer == 0    cannot exist while active -- the frame that
//                                  brings the death timer to zero frees the slot
//
// HP ZERO IS THE DEATH FLAG: one timer serves both the hit flash and the death
// animation, because the two can never run at once. damageEnemy clears the hit
// timer when it begins a death and returns early on already-zero health, so a
// dying enemy cannot take a second hit. Deriving "dying" from health instead of
// storing it separately removes any chance of the two disagreeing.
objHP:       .fill MAX_OBJECTS, 0        // 0 = dying. See the table above.
objTimer:    .fill MAX_OBJECTS, 0        // hit flash while alive, death when not

// Diagnostics. Saturating where a count could run away.
objPeak:     .byte 0                     // high-water mark of logCount
objAllocFail: .byte 0                    // allocations refused: the pool was full
objDoubleFree: .byte 0                   // frees of an already-free slot

objectStateEnd:
.if (objectStateEnd > $c600) { .error "the object pool state has grown past its $c600 ceiling" }

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
// objectZeroSlot — clear every field of slot X, gameplay and presentation.
//
// Deliberately exhaustive rather than a list of the fields that matter: a named
// list goes stale the first time someone adds a field, and "a reused slot
// inherits nothing" is the invariant the whole pool rests on.
// Entry/exit: X = slot, preserved. Clobbers A.
// ---------------------------------------------------------------------------
objectZeroSlot:
    lda #0
    sta objType,x
    sta objVX,x
    sta objVY,x
    sta objHP,x                         // a reused slot must not inherit the
    sta objTimer,x                      // previous occupant's health or flash
    sta logY,x
    sta logX,x
    sta logXHi,x
    sta logPtr,x
    sta logCol,x
    sta logClip,x                       // ...NOR ITS VERTICAL CLIPPING: a slot
                                        // inherited from an enemy halfway
                                        // through the bottom edge would
                                        // otherwise hand its successor a
                                        // clamped Y and a scratch bitmap on its
                                        // first frame, before enemyTick ran.
    sta pkKind,x                        // ...NOR WHAT KIND OF PICKUP IT WAS. A
                                        // slot freed by a token and handed to
                                        // another one must not inherit the
                                        // previous kind's effect on collection
    sta enyFire,x                       // ...NOR PERMISSION TO SHOOT. A slot
                                        // freed by an enemy the encounter
                                        // authored to fire must not hand that
                                        // licence to whatever lands in it next,
                                        // least of all to a hostile projectile
    sta enySpecies,x                    // ...NOR WHICH ENEMY IT WAS. A slot
                                        // freed by a Dropper and handed to a
                                        // Ring would otherwise animate through
                                        // the Dropper's frames until its
                                        // spawner overwrote this -- and a
                                        // future species with BEHAVIOUR
                                        // attached would inherit that too.
    sta enyRole,x                       // ...NOR WHAT IT WAS DOING. A slot
                                        // freed by a token guard and handed to
                                        // a wave member would otherwise have
                                        // the new enemy walk to a ring post
                                        // instead of flying its authored path,
                                        // and would count toward the three the
                                        // encounter is trying to maintain.
    // ...NOR ITS TRAJECTORY. src/movement.asm's per-object arrays are indexed
    // by this same slot and merely live elsewhere in memory, this block having
    // run up against the collision state at $c5f3. The clearing belongs HERE:
    // a pool that delegates "inherits nothing" to its users has stopped
    // guaranteeing it.
    jmp wmClearSlot                     // X preserved; its rts is ours

// ---------------------------------------------------------------------------
// objectAlloc — reserve a free slot WITHOUT activating it.
//
// Returns: carry clear and X = the slot, fully zeroed and ready to fill;
//          carry set and the pool untouched if every slot is in use.
//
// The slot is NOT yet active and NOT yet visible to the sorter: the caller
// fills it and then calls objectActivate, so a half-built object cannot be
// named by sortedIDs even for one frame.
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

    lda logCount                        // high-water mark, a diagnostic
    cmp objPeak
    bcc !already+
    sta objPeak
!already:
    rts

// ---------------------------------------------------------------------------
// objectFree — return slot X to the pool.
//
// The presentation is cleared as well as the membership bit. Nothing
// downstream requires it -- an inactive ID cannot reach sortedIDs at all --
// but a freed slot still holding last frame's Y is a trap for anyone reading
// the arrays in a debugger, and the stores cost nothing on an event that
// happens a couple of times a second.
//
// NO VIC REGISTER IS TOUCHED, and none needs to be. The sprite this object was
// being drawn through is disabled by the next schedule the builder produces,
// because that schedule simply does not contain it.
// Entry/exit: X = slot, preserved.
// ---------------------------------------------------------------------------
objectFree:
    lda logActive,x
    bne !live+
    lda objDoubleFree                   // a double release is survivable, but
    cmp #$ff                            // it means a caller lost track of a
    beq !done+                          // slot, so make it visible
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
// Dispatch is a chain of type tests rather than a jump table: with three types
// a table would still cost more than it saves. Every tick routine may free X and
// both preserve it.
// ---------------------------------------------------------------------------
objectUpdateAll:
    ldx #0
!loop:
    lda logActive,x
    beq !next+
    lda objType,x
    cmp #TYPE_ENEMY
    bne !notEnemy+
    jsr enemyTick                       // may free slot X; X is preserved
    jmp !next+
!notEnemy:
    cmp #TYPE_EBULLET
    bne !notEbullet+
    jsr ebulletTick                     // may free slot X; X is preserved
    jmp !next+

!notEbullet:
    cmp #TYPE_PICKUP                    // the only other thing in the pool, and
    bne !next+                          // an inactive slot never gets this far
    jsr pickupTick                      // may free slot X; X is preserved
!next:
    inx
    cpx #MAX_OBJECTS
    bne !loop-
    rts
