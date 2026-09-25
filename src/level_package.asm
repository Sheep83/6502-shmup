// ===========================================================================
// level_package.asm — the SEPARATELY LOADED level package. Its own PRG.
// ===========================================================================
// Assembled on its own, NOT imported by src/main.asm. It produces
// build/level1.prg, whose load address is LEVELPKG_BASE, which the disk image
// carries as the file "LEVEL1", and which src/levelload.asm pulls in at boot.
//
// IT SHARES NO LABELS WITH THE ENGINE, only the addresses in src/levelpkg.asm.
// The engine declares stageMetatileRows and metatileDefs AT those addresses and
// reads them; this file emits the bytes there. Neither build can see the
// other's symbols, which is exactly why the contract is a constants-only file
// that both import.
//
// WHY THE LEVEL IS A FILE AND NOT A SEGMENT. $e000-$fff9 is RAM under the
// KERNAL and a single PRG cannot reach it: a contiguous file spanning
// $d000-$dfff would write into the I/O registers on the way past, because
// during loading $01 is still $37 and CHAREN routes those stores to the VIC,
// SID and CIAs rather than to RAM. Two files is not a workaround for that --
// it is also the shape a multi-level game wants and the artefact the level
// editor will eventually emit.
// ===========================================================================
#import "levelpkg.asm"                  // the addresses, shared with the engine
#import "stage_config.asm"       // STAGE_METATILE_ROWS / _COUNT

// ---------------------------------------------------------------------------
// THE STAGE MAP, raw and contiguous from the base of the package.
//
// build/stage_map_rows.asm is produced from the level editor's own
// src/level1/stage_map.asm at build time -- the generated file emits the
// definitions first and the rows second, and the audited contract puts the MAP
// at the base, so the two halves are separated mechanically rather than by
// hand. The bytes are not touched; see the `rows` recipe in the Makefile.
// ---------------------------------------------------------------------------
* = LEVELPKG_MAP "level map"
#import "stage_map_rows.asm"
levelMapEnd:

// THE CAPACITY, NOT THE AUTHORED LENGTH. build/stage_map_rows.asm is produced by
// tools/pad_stage_map.py, which pads a short level up to the engine's one stage
// height; see src/levelpkg.asm. A level authored at 138 rows still emits 200.
.if (levelMapEnd - LEVELPKG_MAP != LEVELPKG_STAGE_ROWS * 10) {
    .error "the emitted stage map is not LEVELPKG_STAGE_ROWS * 10 bytes"
}
.if (STAGE_METATILE_ROWS > LEVELPKG_STAGE_ROWS) {
    .error "this level authors more metatile rows than the engine's stage capacity"
}
.if (levelMapEnd - LEVELPKG_MAP > LEVELPKG_MAP_MAX) {
    .error "the stage map has outgrown the 440-row map budget"
}

// ---------------------------------------------------------------------------
// THE SPRITE PAYLOAD: the enemy window and the boss cells.
//
// These used to be compiled into the ENGINE -- `* = ENEMY_SPRITES` and friends
// in src/enemy.asm, `* = BOSS_SPRITES` in src/main.asm -- which made the
// resident level's enemies part of the engine binary and unchangeable at run
// time. They are level-owned artwork, so they travel with the level.
//
// THE WINDOW IS EMITTED AS ONE CONTIGUOUS IMAGE in slot order, padded to the
// engine's twenty blocks. The padding matters: a package is loaded over the
// previous level's bytes, so a level claiming twelve slots must positively zero
// the other eight rather than leave the last level's enemies readable in them.
// ---------------------------------------------------------------------------
#import "stage_enemies.asm"             // LVL_SLOT_*, the slot claims

* = LEVELPKG_SPR "level sprite window"
#import "stage_sprites.asm"
levelSprEnd:

.if (levelSprEnd - LEVELPKG_SPR > LEVELPKG_SPR_MAX) {
    .error "this level's sprite window exceeds the engine's twenty blocks"
}
.if (mod(levelSprEnd - LEVELPKG_SPR, 64) != 0) {
    .error "the sprite window is not a whole number of 64-byte blocks"
}
// THE SLOTS THE MANIFEST FILLS MUST BE THE SLOTS THE LEVEL CLAIMS. stage_enemies
// says where each species lives and stage_sprites supplies the bytes; checking
// them against each other is what stops a manifest edited in one file and not
// the other from shipping a Dropper where the engine expects a Ring.
.var sprBlocks = (levelSprEnd - LEVELPKG_SPR) / 64
.if (LVL_SLOT_RING + 4 > sprBlocks || LVL_SLOT_DROPPER + 4 > sprBlocks
     || LVL_SLOT_SQUARE + 4 > sprBlocks) {
    .error "stage_enemies claims a slot that stage_sprites does not fill"
}
.fill LEVELPKG_SPR_MAX - (levelSprEnd - LEVELPKG_SPR), 0    // unclaimed slots

// boss_art.asm PINS ITSELF with `* = BOSS_SPRITES`, which in the engine is the
// runtime address $3580. In this build that symbol does not exist, and the
// bytes belong at the package's own address -- so the package declares it. The
// generated file is imported UNCHANGED, which keeps SpritePad's output the one
// source of the artwork in both builds.
.const BOSS_SPRITES = LEVELPKG_BOSS

// No `* =` of our own: the import pins itself at the address declared above,
// and a second segment here would only add an empty one to the memory map.
#import "generated_sprites/boss_art.asm"
levelBossEnd:

.if (levelBossEnd - LEVELPKG_BOSS != LEVELPKG_BOSS_MAX) {
    .error "the boss artwork is not BOSS_CELLS blocks of 64 bytes"
}

// ---------------------------------------------------------------------------
// THE METATILE DEFINITIONS, at their own reserved address.
//
// Read ONCE, by trInit, which transposes them into the sub-row tables at $6400
// and never reads them again -- so they are cold data and their address costs
// nothing at run time.
// ---------------------------------------------------------------------------
* = LEVELPKG_DEFS "level metatile defs"
#import "stage_map_defs.asm"
levelDefsEnd:

.if (levelDefsEnd - LEVELPKG_DEFS != STAGE_METATILE_COUNT * 16) {
    .error "the emitted metatile definitions are not STAGE_METATILE_COUNT * 16 bytes"
}
.if (levelDefsEnd - LEVELPKG_DEFS > LEVELPKG_DEFS_MAX) {
    .error "the metatile definitions have outgrown their 64-definition budget"
}

// ---------------------------------------------------------------------------
// THE MOVEMENT PROGRAM POOL, at the base of the encounter reservation.
//
// THESE ARE THE AUTHORITATIVE BYTES. The engine holds no copy: src/waves.asm
// declares `waveStageTable` as a label at this address and src/movement.asm
// reads the records straight out of the loaded file, so what is emitted here is
// what the game actually flies.
//
// Both builds import src/wave_programs.asm, so the offsets the wave definitions
// name in the engine and the bytes emitted here are computed from one source.
// ---------------------------------------------------------------------------
#import "wave_programs.asm"

// ---------------------------------------------------------------------------
// THE STAGE HEADER: the boss approach, as runtime data.
//
// Two bytes, little-endian, in the same coarse-row domain as a trigger row.
// src/waves.asm compares worldProgress against these bytes, so a level changes
// its approach by shipping a different package -- no engine rebuild, and a test
// can move it to prove a boundary.
// ---------------------------------------------------------------------------
* = LEVELPKG_STAGE "level stage header"
levelStageStart:
    .byte <STAGE_NO_SPAWN_ROW, >STAGE_NO_SPAWN_ROW
levelStageEnd:

.if (levelStageEnd - levelStageStart != LEVELPKG_STAGE_MAX) {
    .error "the stage header is not LEVELPKG_STAGE_MAX bytes"
}
.if (STAGE_NO_SPAWN_ROW < 1 || STAGE_NO_SPAWN_ROW > $ffff) {
    .error "STAGE_NO_SPAWN_ROW must be a legal sixteen-bit world row"
}

* = LEVELPKG_MOVE "level movement pool"
levelMoveStart:
.for (var p = 0; p < progs.size(); p++) {
    .var prog = progs.get(p)
    .for (var s = 0; s < prog.size(); s++) {
        .var rec = prog.get(s)
        .byte rec.get(0), rec.get(1), rec.get(2) & $ff, rec.get(3) & $ff
    }
}
levelMoveEnd:

.if (levelMoveEnd - levelMoveStart != progBytes) {
    .error "the emitted movement pool is not WM_STAGE_SIZE bytes per record"
}
.if (mod(levelMoveEnd - levelMoveStart, WM_STAGE_SIZE) != 0) {
    .error "the movement pool is not a whole number of stage records"
}
.if (levelMoveEnd - levelMoveStart > LEVELPKG_MOVE_MAX) {
    .error "the emitted movement pool has outgrown its budget: wmStage is one byte"
}
.if (levelMoveEnd > LEVELPKG_ENC + LEVELPKG_ENC_MAX) {
    .error "the movement pool has run past the encounter reservation"
}

// ---------------------------------------------------------------------------
// THE WAVE DEFINITIONS, above the movement pool.
//
// Ten bytes each, in the order the director reads them. Field 9 is authored as
// a program INDEX and emitted as that program's BYTE OFFSET into the movement
// pool, so the 6502 never multiplies -- progAt comes from the same
// src/wave_programs.asm the pool above was emitted from, so an offset can never
// disagree with the records it points at.
// ---------------------------------------------------------------------------
#import "wave_encounters.asm"

* = LEVELPKG_WAVEDEF "level wave definitions"
levelDefsStart:
.for (var d = 0; d < WAVE_DEFS; d++) {
    .var def = waveDefs.get(d)
    .for (var f = 0; f < WAVEDEF_SIZE; f++) {
        .if (f == 9) { .byte progAt.get(def.get(f)) } else { .byte def.get(f) & $ff }
    }
}
levelDefsEnd2:

.if (levelDefsEnd2 - levelDefsStart != WAVE_DEFS * WAVEDEF_SIZE) {
    .error "the emitted wave definitions are not WAVEDEF_SIZE bytes per definition"
}
.if (levelDefsEnd2 - levelDefsStart > LEVELPKG_WAVEDEF_MAX) {
    .error "the emitted wave definitions have outgrown their package budget"
}

// ---------------------------------------------------------------------------
// THE ABSOLUTE TRIGGER LIST, above the definitions.
//
// SIX PARALLEL COLUMNS, each LEVELPKG_TRIG_SLOTS bytes long whatever this level
// authors, because the engine addresses them as fixed bases: a column that
// shrank with the trigger count would move every column above it and the
// engine's labels would point at the wrong data. The unused tail of each column
// is left at zero.
//
// THE ROWS ARE ABSOLUTE AND SIXTEEN-BIT -- Stage 1's contract -- split low and
// high so the due test is two compares against the cursor with no arithmetic.
// ---------------------------------------------------------------------------
* = LEVELPKG_TRIG "level wave triggers"
levelTrigStart:
.for (var t = 0; t < LEVELPKG_TRIG_SLOTS; t++) {
    .byte t < WAVE_TRIGGERS ? <trigRow.get(t) : 0
}
.for (var t = 0; t < LEVELPKG_TRIG_SLOTS; t++) {
    .byte t < WAVE_TRIGGERS ? >trigRow.get(t) : 0
}
.for (var t = 0; t < LEVELPKG_TRIG_SLOTS; t++) {
    .byte t < WAVE_TRIGGERS ? trigDef.get(t) : 0
}
.for (var t = 0; t < LEVELPKG_TRIG_SLOTS; t++) {
    .byte t < WAVE_TRIGGERS ? trigSpecies.get(t) : 0
}
.for (var t = 0; t < LEVELPKG_TRIG_SLOTS; t++) {
    .byte t < WAVE_TRIGGERS ? trigFire.get(t) : 0
}
.for (var t = 0; t < LEVELPKG_TRIG_SLOTS; t++) {
    .byte t < WAVE_TRIGGERS ? trigSide.get(t) : 0
}
levelTrigEnd:

.if (levelTrigEnd - levelTrigStart != LEVELPKG_TRIG_COLS * LEVELPKG_TRIG_SLOTS) {
    .error "the emitted trigger list is not LEVELPKG_TRIG_COLS columns of LEVELPKG_TRIG_SLOTS"
}
.if (levelTrigEnd > LEVELPKG_ENC + LEVELPKG_ENC_MAX) {
    .error "the trigger list has run past the encounter reservation"
}
.if (WAVE_TRIGGERS > LEVELPKG_TRIG_SLOTS) {
    .error "more authored triggers than the package reserves room for"
}

// ---------------------------------------------------------------------------
// THE SIGNATURE, emitted LAST and highest, so that finding it proves the WHOLE
// file arrived rather than merely its first sector.
// ---------------------------------------------------------------------------
* = LEVELPKG_SIG "level signature"
    .byte LEVELPKG_SIG_0, LEVELPKG_SIG_1, LEVELPKG_SIG_2, LEVELPKG_SIG_3
levelSigEnd:

.if (levelSigEnd > LEVELPKG_TOP + 1) {
    .error "the level package runs past $fff9 into the hardware vectors"
}

// ===========================================================================
// THE LEVEL'S RENDER IDENTITY — what the level LOOKS like, not what it DOES
// ===========================================================================
// These four things used to be compiled into the ENGINE from src/level1/, which
// was invisible while there was one level and wrong the moment there were two:
// level 2 would have been drawn with level 1's glyphs, level 1's colours and
// five of level 1's turrets standing in its terrain. See src/levelpkg.asm.
//
// Each is imported from the LEVEL's own directory, exactly as the map and the
// encounters are, so a level owns its appearance the way it owns its content.
// ---------------------------------------------------------------------------
#import "stage_turrets.asm"             // TURRET_TOTAL, turretCols, turretRows

* = LEVELPKG_CHARS "level charset"
#import "stage_charset.asm"             // terrainGlyphs / terrainGlyphsEnd
levelCharsEnd:

.if (terrainGlyphsEnd - terrainGlyphs != TERRAIN_GLYPH_COUNT * 8) {
    .error "the emitted charset is not TERRAIN_GLYPH_COUNT glyphs"
}
.if (levelCharsEnd - LEVELPKG_CHARS > LEVELPKG_CHARS_MAX) {
    .error "this level's charset exceeds the engine's 128-glyph window"
}

// THE PALETTE. Four bytes the engine pokes straight into $d021/$d022/$d023 and
// uses as the colour-RAM fill; see terrainApplyPackage in src/terrain.asm.
* = LEVELPKG_PAL "level palette"
    .byte TERRAIN_BACKGROUND_COLOUR     // $d021, bit pair 00
    .byte TERRAIN_MC_COLOUR_1           // $d022, bit pair 01
    .byte TERRAIN_MC_COLOUR_2           // $d023, bit pair 10
    .byte TERRAIN_COLOUR_RAM            // colour RAM, already carrying bit 3

* = LEVELPKG_GLYPHN "level glyph count"
    .byte TERRAIN_GLYPH_COUNT

// THE TURRETS, as three parallel columns padded to the engine's capacity. The
// engine reads turretCount first and never looks past it, but the unused slots
// are written anyway: a package is loaded over the previous level's bytes, so a
// short list that left the tail alone would leave the PREVIOUS level's turrets
// readable in it.
* = LEVELPKG_TRTN "level turret count"
    .byte TURRET_TOTAL
* = LEVELPKG_TRTCOL "level turret cols"
    .fill LEVELPKG_TRT_MAX, (i < TURRET_TOTAL) ? turretCols.get(i) : 0
* = LEVELPKG_TRTROWLO "level turret rows lo"
    .fill LEVELPKG_TRT_MAX, (i < TURRET_TOTAL) ? <turretRows.get(i) : 0
* = LEVELPKG_TRTROWHI "level turret rows hi"
    .fill LEVELPKG_TRT_MAX, (i < TURRET_TOTAL) ? >turretRows.get(i) : 0

* = LEVELPKG_TRIGN "level trigger count"
    .byte WAVE_TRIGGERS
levelAssetsEnd:

.if (WAVE_TRIGGERS > LEVELPKG_TRIG_SLOTS) {
    .error "more authored triggers than the package reserves room for"
}

// THE AUTHORING GUARDS, MOVED HERE WITH THE LIST. src/turrets.asm used to make
// these checks, because the list used to be compiled into the engine. It is now
// package data, so the checks belong to the build that emits it -- same checks,
// same lists, still a build error, still caught in the level that authored it.
.if (TURRET_TOTAL > LEVELPKG_TRT_MAX) {
    .error "this level authors more turrets than the engine's capacity"
}
.if (turretCols.size() != TURRET_TOTAL || turretRows.size() != TURRET_TOTAL) {
    .error "the authored turret lists do not match TURRET_TOTAL"
}
.for (var t = 0; t < TURRET_TOTAL; t++) {
    .if (mod(turretRows.get(t), LEVELPKG_METATILE_H) != LEVELPKG_TRT_ROW_PHASE) {
        .error "authored turret row is not metatileRow * METATILE_H + 1"
    }
    // AGAINST THE ENGINE'S CAPACITY, not this level's authored height: the map
    // is padded up to LEVELPKG_STAGE_ROWS and the turret lookup spans all of it.
    .if (turretRows.get(t) + LEVELPKG_TRT_BODY_H - 1 >= LEVELPKG_STAGE_ROWS * LEVELPKG_METATILE_H) {
        .error "an authored turret body runs off the bottom of the stage"
    }
    .if (turretCols.get(t) + LEVELPKG_TRT_BODY_W > LEVELPKG_SCREEN_COLS) {
        .error "an authored turret body runs off the right of the screen"
    }
    .for (var u = 0; u < t; u++) {
        .if (floor(turretRows.get(u) / LEVELPKG_METATILE_H)
             == floor(turretRows.get(t) / LEVELPKG_METATILE_H)) {
            .error "two authored turrets share a metatile row: turretAtMetaRow holds only one"
        }
    }
}
.if (levelAssetsEnd > LEVELPKG_TOP + 1) {
    .error "the render identity runs past $fff9 into the hardware vectors"
}
