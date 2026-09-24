// ============================================================================
// level1/stage_enemies.asm — level 1's claim on the enemy sprite window
//
// CONSTANTS-ONLY level include. Emits no bytes, no memory segment, no
// program-counter change. Imported very early, beside stage_config.asm, so
// every level-owned constant exists before the engine code that consumes them.
//
// Ownership: these values belong to the LEVEL PACKAGE, not to the engine. They
// say which slot of the engine's enemy sprite window each species' frames were
// loaded into. A slot is a block index counted from the start of the window, so
// nothing here knows or cares where the window actually is -- see the window
// constants in src/main.asm and the loader in src/level_assets.asm.
//
// A species' IDENTITY is engine-resident and never appears here; only its
// physical placement, which is exactly the thing that changes per level.
// ============================================================================
.const LVL_SLOT_RING     = 0             // the Sonic Ring's four frames
.const LVL_SLOT_DROPPER  = 4             // the Orbital Dropper's four frames
.const LVL_SLOT_SQUARE   = 8             // the Square's four frames
