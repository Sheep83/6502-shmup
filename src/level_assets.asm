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
// THE RESIDENT DESCRIPTOR TABLE IS GONE, and with it the whole idea that the
// ENGINE knows where a level put its artwork. It held one row of slot claims
// per package, assembled from the build-time level's stage_enemies.asm, and it
// was resolved ONCE at boot -- which quietly required every level in the
// campaign to use the same slot layout as the level the binary was built
// against. A level that chose different artwork, with different frame counts
// and therefore different slots, would have been drawn with the first level's
// pointers.
//
// A package now carries its own resolved table (LEVELPKG_ANIM) and
// levelAssetsLoad is called on every level load, so each level's choice is its
// own. See src/levelpkg.asm.

// --- state -----------------------------------------------------------------
// CPU-ONLY, so it lives outside VIC bank 0 with every other module's state.
// $c400 is the free run between the clip state ($c3d8-$c3f7) and the enemy
// species array ($c500).
* = $c400 "level asset state"
lvlPackage:     .byte 0         // which package levelAssetsLoad last resolved.
                                // Diagnostic and test-visible. No gameplay code
                                // reads it, and none may: gameplay must not
                                // branch on which level is loaded
lvlDescBase:    .byte 0         // (vestigial scratch; the descriptor table is gone)

// WHICH SLOT BEHAVES HOW, copied straight out of the loaded package. Both are
// SPECIES ROW OFFSETS, so the engine's Dropper tests stayed one `cmp` -- they
// compare against a byte instead of an assembled-in constant, which is the
// whole of what it took to stop every enemy identity having to pretend to be
// one of three legacy species.
lvlDropRow:     .byte $ff       // the token-dropping slot, or $ff for none
lvlPlainRow:    .byte 0         // a slot with ordinary behaviour
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
    // THE PACKAGE HAS ALREADY DONE THE ARITHMETIC. Every byte of the table is
    // a window-relative BLOCK, so all that is left is the window's own pointer
    // base. No species division, no descriptor row, no frame count: a species
    // wearing eight-frame artwork simply has eight different blocks in its row.
    ldy #LEVELPKG_ANIM_MAX - 1
!entry:
    lda LEVELPKG_ANIM,y
    clc
    adc #LEVEL_PTR_FIRST
    sta enemyAnimSeq,y
    dey
    bpl !entry-

    // The behaviour rows travel with the artwork, for the same reason: which
    // slot drops the token is a property of the identity the LEVEL chose.
    lda LEVELPKG_DROPROW
    sta lvlDropRow
    lda LEVELPKG_PLAINROW
    sta lvlPlainRow
    rts
