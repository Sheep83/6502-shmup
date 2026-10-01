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
.const SPECIES_SQUARE    = 2 * ENEMY_ANIM_STEPS     // the Square
.const SPECIES_COUNT     = 3

// SQUARE IS 16 FOR THE SAME REASON DROPPER IS 8, and its value was not free to
// choose. A species value IS its row offset in the animation table, so the row
// index times ENEMY_ANIM_STEPS is the only arithmetic `species ORA step` can
// survive. Ring and Dropper keep 0 and 8; the third row begins at 16.

// --- which side a Dropper flies in from -------------------------------------
// AUTHORED, NOT RANDOM, and carried on the trigger list beside the species it
// belongs to. The two sides are the same routine with two constants; there is
// no mirrored copy of anything. See src/dropper.asm.
.const DROP_SIDE_LEFT  = 0
.const DROP_SIDE_RIGHT = 1

// --- ...or whether it flies a MOVEMENT PROGRAM instead ----------------------
// THE TRIGGER'S TENTH COLUMN, and the sentinel is what keeps the old flight
// the default. A Dropper trigger either says "the hard-coded three-pass
// flight", which is what every level authored before this column existed
// means, or it names a movement program for MEMBER 0 -- the Dropper itself --
// and that program is flown by the ordinary movement engine.
//
// EMITTED AS A BYTE OFFSET, exactly like a wave definition's tenth byte: the
// package carries `progAt.get(index)` and the runtime stores it straight into
// wmStage. So the value here shares its number space with the movement pool,
// and the sentinel has to be a number no program can ever start at.
//
// $FF IS PROVABLY SAFE, AND THE PROOF IS ASSERTED IN src/waves.asm. Every
// program ends in a four-byte WM_EXIT record inside a pool of LEVELPKG_MOVE_MAX
// bytes, so the highest offset a program can START at is MOVE_MAX -
// WM_STAGE_SIZE. That is 252 for a 256-byte pool, which leaves 253, 254 and 255
// unreachable by construction rather than by convention. The assertion fails
// the build if the pool or the record size ever changes enough to make that
// untrue, which is the only way this could quietly become an aliasing bug.
//
// THE PROOF IS NOT HERE BECAUSE IT COULD NOT BE. This file declares vocabulary
// and imports nothing, and KickAssembler resolves constants in IMPORT order --
// so a `.if` here naming LEVELPKG_MOVE_MAX and WM_STAGE_SIZE fails with
// "reference to not yet defined symbol" rather than with anything useful. It
// lives beside the other movement-pool proofs instead.
//
// WHY NOT A SEPARATE FLAG COLUMN. A flag plus an offset is two columns and two
// ways to say the same thing, and it admits the state "legacy, but here is a
// program anyway" that nothing could interpret. One column with one
// unreachable value has no such state.
.const TRIG_DROP_LEGACY = $ff

// --- how THIS APPEARANCE of a wave is coloured ------------------------------
// A TRIGGER FIELD, NOT A DEFINITION FIELD, and that distinction is the whole
// point of it. A wave definition is reusable formation vocabulary -- how many
// enemies, how far apart, along which path -- and the same `sweep` should be
// able to arrive cyan at one row, yellow at another and mixed at a third
// without being cloned. Colour is a property of the OCCURRENCE, so it lives on
// the trigger beside the species and the fire mask, which are occurrence
// properties for exactly the same reason.
//
// ONE BYTE, TWO FIELDS:
//     bits 0-3   the C64 colour every member wears when the mode is fixed
//     bit  4     set = each enemy picks its own eligible colour AT SPAWN
//     bits 5-7   unused; src/waves.asm refuses an authored byte that sets them
//
// THE COLOUR IS KEPT WHEN THE MODE IS RANDOM. It stays in the low nibble so
// that switching a trigger to random and back returns the colour the author
// chose, rather than losing it. The runtime simply does not read it.
.const TRIG_COL_MASK   = $0f
.const TRIG_COL_RANDOM = $10

// --- how THIS APPEARANCE of a wave attacks ----------------------------------
// A TRIGGER FIELD, for the same reason the colour is one. A wave definition is
// reusable formation vocabulary -- how many enemies, how far apart, along which
// path -- and the same `sweep` should be able to arrive silent at one row,
// firing straight down at another and aimed at a third without being cloned.
// How a formation ATTACKS is a property of the encounter, not of the shape.
//
// It used to live in bits 4-5 of the wave definition's colour byte, which made
// every occurrence of one definition attack identically.
//
// THREE AUTHORITIES DECIDE WHETHER A GIVEN ENEMY SHOOTS, and they are separate
// on purpose -- see waveSpawnMember in src/waves.asm:
//
//   trigFire      WHICH members of this appearance may shoot (a bitmask over
//                 member index). Already a trigger field, and unchanged.
//   the species   whether this ENEMY CAN shoot at all, and its own default
//                 mode. src/enemy.asm's enemyFireModeTab; the species always
//                 wins a refusal.
//   trigFireMode  HOW the ones that do shoot aim. This field.
//
// "No firing at all" needs no value here: it is an empty trigFire mask, which
// is how it has always been expressed and is still the only way to say it.
.const TRIG_FIRE_DOWN  = 0      // the species' own default -- straight down
.const TRIG_FIRE_AIMED = 1      // sampled at the instant of firing, never again
.const TRIG_FIRE_MAX   = TRIG_FIRE_AIMED

// --- how FAST this appearance crosses the playfield -------------------------
// A TRIGGER FIELD, and the third of the occurrence properties after colour and
// firing. A wave definition is the SHAPE of a path; how quickly an enemy walks
// that shape is a property of the encounter. The same `sweep` should be able to
// make a lazy formation pass at one row and a fast attack run at another
// without being cloned.
//
// A NUMERATOR OVER FOUR, and the four is not arbitrary: the engine already
// works in QUARTER PIXELS per frame (see WM_ARC_SPEED below and wmVX in
// src/movement.asm), so a quarter-scale multiplier divides by a shift.
//
//     scaled = (|v| * TRIG_SPEED) >> 2, with the sign of v put back
//
// FOUR IS A BIT-EXACT NO-OP. (v * 4) >> 2 == v for every v, with no rounding
// at all, so a level that does not touch this field moves exactly as it always
// did -- not approximately, identically.
//
// TRUNCATION IS TOWARD ZERO, not floor, and that is a symmetry property rather
// than an accident: +5 and -5 must scale to exactly opposite velocities or an
// ARC and its ARC_MIRROR would trace different curves. Taking the magnitude,
// scaling, and re-applying the sign is what guarantees it. An arithmetic shift
// of the signed product would give -8 where +5 gives +7.
//
// NO SLOWER THAN 1x IN THIS PASS. The 64-entry heading table exists at
// magnitude WM_ARC_SPEED because that radius is where 64 lattice directions are
// distinguishable; scaling an arc DOWN collapses neighbouring headings onto the
// same velocity and a smooth curve becomes visibly polygonal. Slower formations
// are better authored as a wider turn radius, which costs nothing and is
// already expressible.
.const TRIG_SPEED_SHIFT = 2                     // the /4
.const TRIG_SPEED_1X    = 4                     // the default
// WRITTEN OUT RATHER THAN SHIFTED, and the guard is why it is still honest:
// tools/level_editor/asm_decl.py reads these declarations to keep the editor
// and the engine agreeing about what a 6 means, and its small expression
// grammar has no shift operator. A literal both sides can read beats a
// derivation only one of them can.
.if (TRIG_SPEED_1X != 1 << TRIG_SPEED_SHIFT) {
    .error "TRIG_SPEED_1X must be the identity for a shift of TRIG_SPEED_SHIFT"
}
.const TRIG_SPEED_125X  = 5
.const TRIG_SPEED_150X  = 6
.const TRIG_SPEED_175X  = 7
.const TRIG_SPEED_2X    = 8
.const TRIG_SPEED_MIN   = TRIG_SPEED_1X
.const TRIG_SPEED_MAX   = TRIG_SPEED_2X
