// ===========================================================================
// encounter_format.asm — the VOCABULARY a level's encounter data speaks
// ===========================================================================
// CONSTANTS ONLY. No bytes, no segment, no program-counter change.
//
// SHARED BY TWO BUILDS, which is the whole reason it exists as a file. The
// engine interprets these values; the separately loaded level package emits
// authored bytes that ARE these values. The two are assembled independently and
// share no labels, so anything a level's data names has to live somewhere both
// can import -- exactly as src/movement_format.asm does for movement records
// and src/levelpkg.asm does for addresses.
//
// It holds only what AUTHORED DATA needs to name. The behaviour behind each
// value stays where it always was: src/enemy.asm owns what a species IS,
// src/dropper.asm owns what a side DOES.
// ===========================================================================

// IMPORTED MORE THAN ONCE PER BUILD -- enemy.asm, dropper.asm and the encounter
// data all need it in the engine build.
#importonce

// --- the animation step count, named first ----------------------------------
// A species' value is DERIVED from it (see below), so it has to exist before
// the species do. The cadence itself is documented in src/enemy.asm beside
// ENEMY_ANIM_SHIFT, which is where the animation actually happens.
.const ENEMY_ANIM_STEPS  = 8        // steps in a full animation sequence

// --- the species ------------------------------------------------------------
// A SPECIES VALUE IS ITS ANIMATION ROW OFFSET, NOT AN INDEX, and that is worth
// restating here because a level package emits these numbers directly. Frame
// lookup is `species ORA step`, so a row offset makes that a single ORA straight
// out of memory where a 0/1 species would need a shift or a branch on the
// hottest per-enemy path there is.
//
// Everything else treats them as opaque identities -- compare against the
// CONSTANT, never against a literal. src/waves.asm validates an authored species
// by MEMBERSHIP rather than by range for exactly this reason: "less than the
// count" would be wrong.
.const SPECIES_RING      = 0 * ENEMY_ANIM_STEPS     // the Sonic Ring
.const SPECIES_DROPPER   = 1 * ENEMY_ANIM_STEPS     // the Orbital Dropper
.const SPECIES_COUNT     = 2

// --- which side a Dropper flies in from -------------------------------------
// AUTHORED, NOT RANDOM, and carried on the trigger list beside the species it
// belongs to. The two sides are the same routine with two constants; there is
// no mirrored copy of anything. See src/dropper.asm.
.const DROP_SIDE_LEFT  = 0
.const DROP_SIDE_RIGHT = 1
