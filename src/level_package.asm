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

.if (levelMapEnd - LEVELPKG_MAP != STAGE_METATILE_ROWS * 10) {
    .error "the emitted stage map is not STAGE_METATILE_ROWS * 10 bytes"
}
.if (levelMapEnd - LEVELPKG_MAP > LEVELPKG_MAP_MAX) {
    .error "the stage map has outgrown the 440-row map budget"
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
