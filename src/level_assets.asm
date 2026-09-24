// ===========================================================================
// 6502-shmup — level_assets: turning a level's window claims into pointers
// ===========================================================================
// THE PROBLEM THIS SOLVES. Eight levels' worth of enemy artwork cannot be
// resident at once in a 16 KB VIC bank. Before this file, each species named
// its own permanent address -- the Ring "was" $3580/$d6 and the Dropper "was"
// $2c00/$b0 -- so a species' IDENTITY and its physical HOME were one fact. A
// second level could not reuse those blocks without the engine disagreeing
// with itself about what lived there.
//
// THE MODEL. One contiguous aligned run of VIC bank 0 is the LEVEL ENEMY
// SPRITE WINDOW (declared with the rest of the memory map in src/main.asm,
// because the map is engine property). The ENGINE owns the window; a LEVEL
// owns its contents. A level package says, in data, which SLOT of the window
// each species' frames were loaded into, and levelAssetsLoad turns those
// claims into the pointer table the animation already reads.
//
//   resident   the window's address and size          (engine memory map)
//              a species' identity                    (SPECIES_RING, ...)
//              a species' animation SHAPE             (enemyAnimShape)
//
//   per level  which slot a species was loaded into   (levelAssetDescs)
//              and, once there is a loader, the bytes in those blocks
//
// Gameplay code is unchanged and never learns an address: enemyAnimPtr asks
// for a species' current frame exactly as it did before.
//
// NO FRAMEWORK. A byte table and one loop. There is no asset manager, no
// vtable and no per-species record, because the only thing that actually
// varies per level is where a species' blocks landed -- so that is the only
// thing the descriptor carries.
// ===========================================================================

// --- the packages ----------------------------------------------------------
// One row of SPECIES_COUNT slot indices per package.
//
// LEVEL B IS A TEST PACKAGE AND NOTHING ELSE. It exists to prove the pointer
// table is genuinely rebuilt from data rather than baked at assembly time, so
// it deliberately disagrees with level 1 about BOTH species: a different slot
// each, and the two species in the OPPOSITE ORDER within the window. A package
// that merely shifted both by a constant could pass while the loader ignored
// the descriptor entirely.
//
// It carries no artwork. Proving the address contract does not need a second
// set of drawings, and inventing enemy art is not this task's job. Level 1's
// own claims live with level 1, in level1/stage_enemies.asm.
.const LEVEL_PACKAGE_1      = 0             // Ring + Dropper, the real level
.const LEVEL_PACKAGE_B      = 1             // the replacement proof
.const LEVEL_PACKAGE_COUNT  = 2

.const LB_SLOT_RING         = 12            // $2f00, pointer $bc
.const LB_SLOT_DROPPER      = 8             // $2e00, pointer $b8
// Package B disagrees about the Square too, which is the point of it: the
// level packs Ring/Dropper/Square at 0/4/8 and this package puts them at
// 12/8/16, so no species keeps its address and the loader cannot pass by
// accident. Slot 16 holds no art -- package B has never carried any -- and it
// does not need to: what is being proved is the pointer arithmetic.
.const LB_SLOT_SQUARE       = 16            // $3000, pointer $c0

// THE ROW IS PADDED TO A POWER OF TWO so the loop below can still turn a
// package index into a row base with a shift rather than a multiply. It used to
// be exactly SPECIES_COUNT wide, which worked only while that was 2; a third
// species made the count odd, and padding the stride is a great deal cheaper
// than a multiply on the path that builds the table.
.const LEVEL_DESC_ROW_STRIDE = 4
.const LEVEL_DESC_ROW_SHIFT = 2
.if ((1 << LEVEL_DESC_ROW_SHIFT) != LEVEL_DESC_ROW_STRIDE) {
    .error "LEVEL_DESC_ROW_SHIFT no longer matches LEVEL_DESC_ROW_STRIDE"
}
.if (LEVEL_DESC_ROW_STRIDE < SPECIES_COUNT) {
    .error "the descriptor row is narrower than the number of species"
}

levelAssetDescs:
    // one row per package, LEVEL_DESC_ROW_STRIDE wide, SPECIES_COUNT used
    .byte LVL_SLOT_RING, LVL_SLOT_DROPPER, LVL_SLOT_SQUARE, 0   // LEVEL_PACKAGE_1
    .byte LB_SLOT_RING,  LB_SLOT_DROPPER,  LB_SLOT_SQUARE,  0   // LEVEL_PACKAGE_B
levelAssetDescsEnd:

.if (levelAssetDescsEnd - levelAssetDescs != LEVEL_PACKAGE_COUNT * LEVEL_DESC_ROW_STRIDE) {
    .error "the descriptor table is not one row of LEVEL_DESC_ROW_STRIDE slots per package"
}

// Every slot any package claims must hold a whole species inside the window.
// Named one by one rather than looped: there are four, and a guard that names
// the constant it is protecting is worth more than a clever loop.
.if (LVL_SLOT_RING    + ENEMY_FRAMES > LEVEL_SPRITE_BLOCKS) { .error "the level's Ring slot runs past the enemy sprite window" }
.if (LVL_SLOT_DROPPER + ENEMY_FRAMES > LEVEL_SPRITE_BLOCKS) { .error "the level's Dropper slot runs past the enemy sprite window" }
.if (LB_SLOT_RING    + ENEMY_FRAMES > LEVEL_SPRITE_BLOCKS) { .error "level B's Ring slot runs past the enemy sprite window" }
.if (LB_SLOT_DROPPER + ENEMY_FRAMES > LEVEL_SPRITE_BLOCKS) { .error "level B's Dropper slot runs past the enemy sprite window" }
.if (LVL_SLOT_SQUARE + ENEMY_FRAMES > LEVEL_SPRITE_BLOCKS) { .error "the level's Square slot runs past the enemy sprite window" }
.if (LB_SLOT_SQUARE  + ENEMY_FRAMES > LEVEL_SPRITE_BLOCKS) { .error "level B's Square slot runs past the enemy sprite window" }

// A package's two species must not be loaded on top of each other. This is the
// check that would catch a hand-edited descriptor, which is how a level package
// will be authored until there is a tool that emits one.
.if (LVL_SLOT_RING < LVL_SLOT_DROPPER + ENEMY_FRAMES && LVL_SLOT_DROPPER < LVL_SLOT_RING + ENEMY_FRAMES) {
    .error "the level loads two species into overlapping window slots"
}
.if (LVL_SLOT_RING < LVL_SLOT_SQUARE + ENEMY_FRAMES && LVL_SLOT_SQUARE < LVL_SLOT_RING + ENEMY_FRAMES) {
    .error "the level loads the Ring and the Square into overlapping window slots"
}
.if (LVL_SLOT_DROPPER < LVL_SLOT_SQUARE + ENEMY_FRAMES && LVL_SLOT_SQUARE < LVL_SLOT_DROPPER + ENEMY_FRAMES) {
    .error "the level loads the Dropper and the Square into overlapping window slots"
}
.if (LB_SLOT_RING < LB_SLOT_DROPPER + ENEMY_FRAMES && LB_SLOT_DROPPER < LB_SLOT_RING + ENEMY_FRAMES) {
    .error "level B loads two species into overlapping window slots"
}

// --- state -----------------------------------------------------------------
// CPU-ONLY, so it lives outside VIC bank 0 with every other module's state.
// $c400 is the free run between the clip state ($c3d8-$c3f7) and the enemy
// species array ($c500).
* = $c400 "level asset state"
lvlPackage:     .byte 0         // which package levelAssetsLoad last resolved.
                                // Diagnostic and test-visible. No gameplay code
                                // reads it, and none may: gameplay must not
                                // branch on which level is loaded
lvlDescBase:    .byte 0         // the loader's row offset into the descriptor
                                // table -- one byte of scratch rather than a
                                // second index register
levelAssetStateEnd:
.if (levelAssetStateEnd > $c500) {
    .error "the level asset state has grown into the enemy species array at $c500"
}

// $4b00: the enemy code now runs to $4a01 and collision begins at $4c00.
* = $4b00 "level assets"

// ---------------------------------------------------------------------------
// levelAssetsLoad — resolve a package's slot claims into the animation table.
// Entry: X = package index (LEVEL_PACKAGE_1 or LEVEL_PACKAGE_B).
// Exit:  enemyAnimSeq holds a sprite POINTER for every species and every step.
//        A, X, Y clobbered.
//
// THIS IS THE WHOLE INDIRECTION. enemyAnimSeq used to be a table of constants
// assembled from ENEMY_PTR_FIRST and DROPPER_PTR_FIRST. It is now RAM, built
// here from two separately owned things:
//
//     the SHAPE   enemyAnimShape  -- frame indices; resident species behaviour
//     the SLOT    levelAssetDescs -- where this level put that species' frames
//
//     pointer = window base + slot + frame index
//
// A species owns exactly one run of ENEMY_ANIM_STEPS consecutive entries, so
// an entry index's high bits ARE its species. That is the same arithmetic
// enemyAnimPtr already relies on, used here in reverse, which is why no third
// table is needed to say which entry belongs to whom.
//
// CALLED ONCE PER LEVEL, from gameInit. Nothing per-frame calls it, so it is
// written to be read rather than to be fast.
// ---------------------------------------------------------------------------
levelAssetsLoad:
    stx lvlPackage
    txa
    .for (var i = 0; i < LEVEL_DESC_ROW_SHIFT; i++) {
        asl                             // * SPECIES_COUNT: this package's row
    }
    sta lvlDescBase

    ldy #0                              // Y = entry index, 0 .. rows*steps-1
!entry:
    tya
    .for (var i = 0; i < ENEMY_ANIM_STEPS_SHIFT; i++) {
        lsr                             // / ENEMY_ANIM_STEPS: the entry's
    }                                   // species
    clc
    adc lvlDescBase
    tax                                 // X = this species' descriptor entry
    lda levelAssetDescs,x               // the slot the level loaded it into
    clc
    adc #LEVEL_PTR_FIRST                // -> that slot's sprite pointer
    clc
    adc enemyAnimShape,y                // + the frame this step wants
    sta enemyAnimSeq,y
    iny
    cpy #SPECIES_COUNT * ENEMY_ANIM_STEPS
    bne !entry-
    rts
