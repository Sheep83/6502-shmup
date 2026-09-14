// ===========================================================================
// motion.asm — the logical sprite state the schedule builder reads
// ===========================================================================
// MAIN THREAD ONLY. Enemies, hostile projectiles and the clipping layer write
// these arrays; sortTick orders them by Y and buildSchedule turns them into a
// frame's schedule. Nothing here is read after publication, and nothing here
// runs inside an interrupt.
// ===========================================================================

// OUTSIDE VIC BANK 0, and deliberately so: the VIC can address only
// $0000-$3fff, so state kept above that can never be fetched as graphics data
// however badly a sprite pointer is corrupted.
* = $c300 "logical sprite state"

logCount:       .byte 0                 // logical sprites currently active
logY:           .fill MAX_LOGICAL, 0    // VIC sprite Y: the sprite's TOP raster
logX:           .fill MAX_LOGICAL, 0    // X low byte...
logXHi:         .fill MAX_LOGICAL, 0    // ...and bit 8, 0 or 1: the $d010 source
logPtr:         .fill MAX_LOGICAL, 0    // sprite pointer, i.e. bitmap address / 64
logCol:         .fill MAX_LOGICAL, 0    // sprite colour, $d027..$d02e
