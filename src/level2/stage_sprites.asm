// ==========================================================================
// stage_sprites.asm — this level's claim on the SPRITE artwork
// ==========================================================================
// WHAT THIS IS. The enemy sprite window and the boss cells are level-owned
// artwork: the package carries the bytes and levelApplySprites copies them into
// LEVEL_SPRITES and BOSS_SPRITES at level init. This file names which generated
// blocks fill the window, in WINDOW ORDER -- slot 0 first, contiguously.
//
// IT IS A MANIFEST, NOT ARTWORK. Every block comes from src/generated_sprites/,
// which tools/sprite_export/import_spd.py produces from
// assets/sprites/19656-sprites.spd. SPRITEPAD REMAINS THE AUTHORITY; this file
// only says which of its output this level ships, and changes nothing about how
// the artwork is authored or generated.
//
// THE ORDER MUST MATCH stage_enemies.asm, which says which slot each species
// occupies. src/level_package.asm checks the two against each other rather than
// trusting them to agree.
//
// REUSING ANOTHER LEVEL'S ARTWORK IS NORMAL AND FREE. src/level2/stage_sprites.asm
// is this file verbatim: level 2 flies the same three species, so it ships the
// same bytes. Nothing requires a level to have artwork of its own.
// ==========================================================================
#importonce

#import "generated_sprites/enemy_art.asm"           // slots 0-3   LVL_SLOT_RING
#import "generated_sprites/enemy_dropper_art.asm"   // slots 4-7   LVL_SLOT_DROPPER
#import "generated_sprites/enemy_square_art.asm"    // slots 8-11  LVL_SLOT_SQUARE
