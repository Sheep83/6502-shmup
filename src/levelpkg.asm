// ===========================================================================
// levelpkg.asm — the LEVEL PACKAGE memory contract, shared by both builds
// ===========================================================================
// CONSTANTS ONLY. No segment, no bytes, no program-counter change. It is
// imported by the engine (src/main.asm) and by the package (src/level_package.asm)
// so that the two cannot disagree about where anything lives -- the engine
// reads these addresses, the package emits at them, and a mismatch is a build
// error in whichever of the two notices first rather than a black screen.
//
// WHY A SEPARATE FILE AT ALL. The package is a SEPARATELY LOADED ARTEFACT: it
// is assembled into its own PRG, written to the disk image as its own file and
// pulled in by the KERNAL at boot. The two builds therefore share no labels,
// only these numbers, and this is the one place they are written down.
//
// ---------------------------------------------------------------------------
// WHERE IT IS, AND WHY IT IS SAFE
// ---------------------------------------------------------------------------
// $e000-$fff9 is RAM underneath the KERNAL ROM. The engine runs with $01 = $35
// (see installRenderer in src/renderer.asm), which banks the KERNAL out, so
// this is ordinary read/write RAM for the whole of gameplay. The VIC never
// selects bank 3 ($c000-$ffff), so nothing here is ever fetched as graphics.
//
// It was proved EMPIRICALLY rather than assumed: reports/definitive-440-row-
// memory-audit.md filled the region with a pattern and found it untouched by
// twelve seconds of gameplay AND by the bank-2 boss transition.
//
// $fffa-$ffff IS NOT OURS. The hardware NMI, RESET and IRQ vectors live there
// and installRenderer writes $fffe itself. The package stops at $fff9 and the
// guard below is what keeps it there.
// ===========================================================================

// IMPORTED MORE THAN ONCE PER BUILD -- both the engine and the package build import it.
#importonce
.const LEVELPKG_BASE     = $e000
.const LEVELPKG_TOP      = $fff9        // last byte the package may occupy

// --- the three components, at the audited addresses -------------------------
//   map    440 rows x 10 metatiles, raw and contiguous
//   defs   up to 64 metatile definitions x 16 bytes
//   enc    RESERVED for the future editor-generated encounter package. Nothing
//          emits here yet; the reservation exists so that terrain growth cannot
//          quietly eat the space the wave contract is going to need.
.const LEVELPKG_MAP      = $e000
.const LEVELPKG_MAP_MAX  = 440 * 10     // 4400
.const LEVELPKG_DEFS     = $f130
.const LEVELPKG_DEFS_MAX = 64 * 16      // 1024
.const LEVELPKG_ENC      = $f530
.const LEVELPKG_ENC_MAX  = 1600

// --- the encounter package's first tenant: the movement program pool --------
// Stage 2 moves the movement programs out of the engine PRG and into the level
// file. They sit at the BASE of the encounter reservation; wave definitions and
// triggers will follow above them in later stages, inside the same 1,600-byte
// envelope.
//
// THE 256-BYTE CEILING IS NOT A BUDGET CHOICE, IT IS THE HARDWARE. Each object
// carries its cursor into this pool in wmStage, one byte, so a record beyond
// offset 255 could not be addressed at all -- and the engine reads the pool with
// `lda LEVELPKG_MOVE + n,y`, whose Y is that same byte. Raising it means
// widening per-object state, which is a later decision and not this one.
.const LEVELPKG_MOVE     = LEVELPKG_ENC
.const LEVELPKG_MOVE_MAX = 256

// --- the wave definitions, above the movement pool --------------------------
// Ten bytes each (WAVEDEF_SIZE): count, interval, startX lo/hi, startY, xStep,
// yStep, colour, launch heading, movement-program offset. The director reads
// them as `waveDefTable + n,y` with y = def * 10, so the whole table has to stay
// inside one byte of index: 25 definitions is the arithmetic ceiling and 32
// would already overflow it.
//
// THE BUDGET IS THE ADDRESSING CEILING, NOT A ROUND NUMBER. waveDefBase forms
// the index as def * 10 in a single byte, so the last reachable definition is
// 25 (250) and a twenty-seventh could be stored but never read. The table is
// therefore exactly 26 records -- every byte of it addressable -- and the 60
// bytes that a rounder 32-record table would have wasted go to the triggers,
// which have a real use for them.
.const LEVELPKG_WAVEDEF     = LEVELPKG_MOVE + LEVELPKG_MOVE_MAX     // $f630
.const LEVELPKG_WAVEDEF_SLOTS = 26
.const LEVELPKG_WAVEDEF_MAX = LEVELPKG_WAVEDEF_SLOTS * 10           // 260

// --- the absolute trigger list, above the definitions -----------------------
// SIX PARALLEL COLUMNS, not interleaved records: rowLo, rowHi, def, species,
// fire, side. The director indexes every one of them with the SAME cursor
// (`lda waveTrigDef,y` and so on), so parallel columns cost one `absolute,y`
// per field and nothing else. An interleaved record would need the cursor
// multiplied by six on every read -- strictly more work for the same data.
//
// Each column is one byte per trigger, so the whole list is six bytes a trigger
// and the cursor is a byte: 255 triggers is the addressing ceiling.
.const LEVELPKG_TRIG        = LEVELPKG_WAVEDEF + LEVELPKG_WAVEDEF_MAX   // $f734
.const LEVELPKG_TRIG_COLS   = 6
.const LEVELPKG_TRIG_MAX    = LEVELPKG_ENC_MAX - LEVELPKG_MOVE_MAX - LEVELPKG_WAVEDEF_MAX
.const LEVELPKG_TRIG_SLOTS  = floor(LEVELPKG_TRIG_MAX / LEVELPKG_TRIG_COLS)   // 180

// --- the signature ----------------------------------------------------------
// FOUR BYTES AT THE VERY TOP OF THE REGION, so that "did the package actually
// load?" is one comparison rather than an inference from whether the terrain
// looked right. The engine checks it after the KERNAL returns; a test reads it
// directly.
//
// It sits ABOVE the map rather than below it because $e000 is the map's own
// first byte and the map must stay contiguous from there -- the scroller
// indexes it as one flat array.
.const LEVELPKG_SIG      = $fb70        // in the spare/growth run
.const LEVELPKG_SIG_0    = $19
.const LEVELPKG_SIG_1    = $65
.const LEVELPKG_SIG_2    = $6c
.const LEVELPKG_SIG_3    = $70

// ===========================================================================
// THE LAYOUT GUARDS. Everything below is an assembly-time proof that the
// components fit, do not overlap, and cannot reach the hardware vectors.
// ===========================================================================
.if (LEVELPKG_MAP != LEVELPKG_BASE) {
    .error "the stage map must start at the base of the level package"
}
.if (LEVELPKG_MAP + LEVELPKG_MAP_MAX > LEVELPKG_DEFS) {
    .error "the 440-row map budget overlaps the metatile definition reservation"
}
.if (LEVELPKG_DEFS + LEVELPKG_DEFS_MAX > LEVELPKG_ENC) {
    .error "the metatile definition budget overlaps the encounter reservation"
}
.if (LEVELPKG_ENC + LEVELPKG_ENC_MAX > LEVELPKG_SIG) {
    .error "the encounter reservation overlaps the signature"
}
.if (LEVELPKG_MOVE != LEVELPKG_ENC) {
    .error "the movement pool must start at the base of the encounter reservation"
}
.if (LEVELPKG_MOVE_MAX > LEVELPKG_ENC_MAX) {
    .error "the movement pool budget exceeds the whole encounter reservation"
}
.if (LEVELPKG_MOVE_MAX > 256) {
    .error "wmStage is one byte: a movement pool over 256 bytes cannot be addressed"
}
.if (LEVELPKG_WAVEDEF != LEVELPKG_MOVE + LEVELPKG_MOVE_MAX) {
    .error "the wave definitions must follow the movement pool with no gap"
}
.if (LEVELPKG_TRIG != LEVELPKG_WAVEDEF + LEVELPKG_WAVEDEF_MAX) {
    .error "the trigger list must follow the wave definitions with no gap"
}
// THE THREE COMPONENTS MUST FILL THE RESERVATION AND NOT ONE BYTE MORE. The
// signature sits immediately above it, so an overrun would be silently eaten by
// the spare run and only show up as a corrupt signature at boot.
.if (LEVELPKG_MOVE_MAX + LEVELPKG_WAVEDEF_MAX + LEVELPKG_TRIG_MAX != LEVELPKG_ENC_MAX) {
    .error "the encounter components do not add up to the encounter reservation"
}
.if (LEVELPKG_TRIG + LEVELPKG_TRIG_MAX > LEVELPKG_SIG) {
    .error "the trigger list runs into the package signature"
}
.if (LEVELPKG_TRIG_SLOTS > 255) {
    .error "the trigger cursor is one byte: more than 255 triggers cannot be reached"
}
.if ((LEVELPKG_WAVEDEF_SLOTS - 1) * 10 > 255) {
    .error "waveDefBase forms def * WAVEDEF_SIZE in one byte: too many definitions"
}
.if (LEVELPKG_SIG + 4 > LEVELPKG_TOP + 1) {
    .error "the signature runs past the top of the level package"
}
.if (LEVELPKG_TOP >= $fffa) {
    .error "the level package reaches the hardware vectors at $fffa"
}
