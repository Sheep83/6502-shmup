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
// THE SIGNATURE, emitted LAST and highest, so that finding it proves the WHOLE
// file arrived rather than merely its first sector.
// ---------------------------------------------------------------------------
* = LEVELPKG_SIG "level signature"
    .byte LEVELPKG_SIG_0, LEVELPKG_SIG_1, LEVELPKG_SIG_2, LEVELPKG_SIG_3
levelSigEnd:

.if (levelSigEnd > LEVELPKG_TOP + 1) {
    .error "the level package runs past $fff9 into the hardware vectors"
}
