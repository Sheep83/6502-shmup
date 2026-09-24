// ===========================================================================
// enemy.asm — the enemy: its art, its lifecycle, its damage and its death
// ===========================================================================
// MAIN THREAD ONLY. Not one VIC register is written from this file, and the
// word "slot" never appears in it in the hardware sense. An enemy knows its
// logical position and its velocity; whether it is drawn, and through which
// hardware sprite, is entirely the renderer's business.
//
// One TYPE_ENEMY with many trajectories: an enemy's path is handed to it at
// spawn by src/waves.asm and run by src/movement.asm, so a new flight pattern
// never needs a new type. What lives here is what makes an enemy an ENEMY --
// the art, the six HP, the hit flash, the death animation, the lifecycle
// bounds and the pool discipline -- and none of it cares who created it.
//
// AN ENEMY IS SCREEN-SPACE, deliberately. logY is a raster line, not a stage
// row: the enemy never reads the scroller or worldProgress and does not move
// with the terrain. The wave system asks worldProgress WHEN to spawn and then
// hands the object a screen position and a vector; that is the whole coupling.
//
// vy is POSITIVE for an approaching enemy because the terrain scrolls down and
// the player flies up, so an attacker enters at the top of the aperture and
// descends. See docs/ENGINE_CONTRACT.md section 8a.
// ===========================================================================

.const ENEMY_MAX_HP      = 6        // TYPE data: every enemy starts here, so
                                   // no per-object maximum is stored

// ===========================================================================
// ENEMY SPECIES — the one thing that distinguishes the two enemies
// ===========================================================================
// THE SPECIES VOCABULARY LIVES IN ITS OWN FILE, because a level package emits
// these values as authored bytes and the two builds share no labels. See
// src/encounter_format.asm for ENEMY_ANIM_STEPS and the SPECIES_* constants;
// what a species DOES is still this file's business.
#import "encounter_format.asm"

// There are two enemy PRESENTATIONS and, so far, exactly one enemy BEHAVIOUR.
// The species byte is what says which artwork an object wears, and it is a
// stored, explicit value rather than something inferred.
//
// NOTHING MAY DERIVE SPECIES FROM ANYTHING ELSE -- not the sprite pointer, not
// the colour, not the wave slot, not the position, not the movement mode, not
// the object index. Every one of those is either reused, authored per wave, or
// changed by gameplay, and a species read out of one of them would flip under
// a maintainer who had no reason to suspect it. The byte exists so that when
// the Dropper eventually grows behaviour of its own -- token drops -- there is
// something to branch on that was true at spawn and stays true.
//
// TWO VALUES, AND NO FRAMEWORK. There is no type table, no vtable, no
// per-species stat block, because there is no second BEHAVIOUR to hang off one
// yet. When there is, this constant is what it indexes.
//
// THE VALUE OF A SPECIES IS ITS ROW IN THE ANIMATION TABLE, which is why
// SPECIES_DROPPER is 8 and not 1. enemyAnimPtr runs once per enemy per frame
// and composes its table index as `step OR species`; a species that is already
// a row offset makes that a single ORA straight out of memory, where a 0/1
// species would need a shift or a branch on the hottest per-enemy path there
// is. Everything else treats these as opaque identities -- compare against the
// CONSTANT, never against a literal, and nothing has to know.

// --- what a species can DO: the first behaviour to hang off the identity ----
// Until now a species was purely cosmetic -- "a per-species stat block, because
// there is no second BEHAVIOUR to hang off one" said the note above, and enemy
// firing is that second behaviour arriving.
//
// CAPABILITY IS DECLARED HERE AND NOWHERE ELSE. It is a property of the
// SPECIES, looked up from the species byte, and it is never inferred from a
// sprite pointer, a colour, a wave, a movement program, a pool slot or an
// animation frame -- every one of which is either shared between species or
// changed by gameplay. A species whose entry is ENEMY_FIRE_NONE cannot fire
// however it is authored, which is the case this table exists to make
// possible: the encounter data may ask, and the species is what answers.
//
// BOTH LEVEL-1 SPECIES FIRE THE SAME STRAIGHT-DOWN SHOT, because v1 has one
// firing mode and giving one of the two enemies an exclusive on it would be
// content, not architecture. The table is what makes a THIRD species that
// cannot fire, or a later one that fires differently, a row rather than a
// redesign -- the mode is a value, not a flag.
.const ENEMY_FIRE_NONE   = 0                        // this species never fires
.const ENEMY_FIRE_DOWN   = 1                        // one bolt, straight down
.const ENEMY_FIRE_AIMED  = 2                        // one bolt, aimed at where
                                                    // the ship WAS when it was
                                                    // fired. Not homing: the
                                                    // trajectory is fixed at
                                                    // launch, so the shot can
                                                    // always be dodged. Same
                                                    // pool, cap, flight and
                                                    // collision as every other
                                                    // projectile -- the only
                                                    // difference is which
                                                    // ebullet entry point
                                                    // src/waves.asm calls

// The table itself is enemyFireModeTab, in the enemy CODE segment below --
// data belongs in a segment, and a .byte out here would be emitted at whatever
// address the previous file happened to leave the program counter on.

// --- where each species' frames live -----------------------------------------
// NOT PINNED ANY MORE, AND THAT IS THE POINT. These addresses used to be
// per-species constants -- the Ring "was" $3580 and the Dropper "was" $2c00 --
// which made a species' identity and its physical home the same fact and made
// a second level's artwork impossible to place. They are now derived from the
// SLOT of the engine's enemy sprite window that THIS level's package claims
// for each species. See src/level_assets.asm for the model, main.asm for the
// window, and level1/stage_enemies.asm for the claims themselves.
//
// These constants exist only to place level 1's compiled-in artwork and to
// assert it landed where its package said. NO RUNTIME CODE READS THEM. The
// animation resolves pointers through levelAssetsLoad, which reads the
// descriptor -- so a different package moves the art without touching a line
// of this file.
//
// FOUR CONSECUTIVE BLOCKS EACH, AND THE ORDER IS STILL LOAD-BEARING: the
// animation shape below is a list of frame INDICES added to a species' base,
// so a species' frames must be adjacent and in the authored order. The label
// assertions further down are what make reordering an art file a build error
// rather than a scrambled animation.
.const ENEMY_FRAMES      = 4                        // north, east, south, west
.const DROPPER_FRAMES    = 4                        // wide, f-right, f, f-left
.const SQUARE_FRAMES     = 4                        // full, turn, narrow, edge

.const ENEMY_SPRITES     = levelSlotAddr(LVL_SLOT_RING)
.const DROPPER_SPRITES   = levelSlotAddr(LVL_SLOT_DROPPER)
.const SQUARE_SPRITES    = levelSlotAddr(LVL_SLOT_SQUARE)

.if (ENEMY_FRAMES != DROPPER_FRAMES || ENEMY_FRAMES != SQUARE_FRAMES) {
    .error "a window slot holds ENEMY_FRAMES blocks: species of different frame counts need the descriptor to carry the count"
}
// The window guards in main.asm already prove the run is aligned, inside the
// bank and clear of screen page B and the clip scratch; level_assets.asm proves
// every package's slots fit inside it. What is left to check here is that the
// two species of THIS level do not overlap each other, which the descriptor
// guards also cover, and that the art really landed on its slot -- asserted
// against the art's own labels below.

// --- the animation cadence ---------------------------------------------------
// ENEMY_ANIM_SHIFT frames of hold per step, and ENEMY_ANIM_STEPS steps in the
// sequence a species walks -- so a full cycle is 64 displayed frames, 1.28 s of
// PAL. Fast enough to read as motion, slow enough not to flicker.
//
// A SHIFT RATHER THAN A TIMER, and that is what makes this cost no state at
// all: the phase is derived from the renderer's free-running frameCounter
// instead of being counted. See enemyAnimPtr.
.const ENEMY_ANIM_SHIFT  = 3                        // 1 << 3 = 8 frames a step

// EIGHT STEPS FOR A FOUR-FRAME ANIMATION, and the spare four are what let a
// species choose its own path through its frames. The Ring simply rotates
// twice; the Dropper ping-pongs. See ENEMY_ANIM_SEQ below.
//
// WHY EIGHT AND NOT SIX. The Dropper's natural ping-pong is six steps --
// 0,1,2,3,2,1 -- but six can never divide the 256-frame wrap of frameCounter's
// low byte, because 6 has a factor of 3 and 256 is a power of two. A six-step
// sequence would therefore jog by one step every 256 frames, for ever. Eight
// steps divides cleanly, and the two spare steps are spent DWELLING at the two
// turnarounds, which is what a satellite crossing a sphere actually does: it
// appears to slow and reverse at the extremes and to move fastest through the
// middle. The alternative -- six steps plus a byte of counter state and a
// once-per-frame tick -- buys strict uniformity of dwell at the cost of the
// stateless design, and looks worse rather than better.
.if (mod(256, ENEMY_ANIM_STEPS << ENEMY_ANIM_SHIFT) != 0) {
    .error "a frameCounter low-byte wrap would land mid-cycle and jog the animation"
}
.if ((ENEMY_ANIM_STEPS & (ENEMY_ANIM_STEPS - 1)) != 0) {
    .error "ENEMY_ANIM_STEPS must be a power of two: the phase is masked, not compared"
}
.if (SPECIES_COUNT != 3) {
    .error "the species values are animation row offsets: adding another means extending enemyAnimShape, enemyFireModeTab, the level descriptor rows and this check"
}

// levelAssetsLoad divides an entry index by ENEMY_ANIM_STEPS to recover the
// species that owns it. A shift, because the step count is already asserted a
// power of two just above.
.const ENEMY_ANIM_STEPS_SHIFT = 3
.if ((1 << ENEMY_ANIM_STEPS_SHIFT) != ENEMY_ANIM_STEPS) {
    .error "ENEMY_ANIM_STEPS_SHIFT no longer matches ENEMY_ANIM_STEPS"
}

// ===========================================================================
// LIFECYCLE BOUNDS — WHERE AN ENEMY MAY EXIST, NOT WHERE IT MAY BE SEEN
// ===========================================================================
// WHERE AN ENEMY MAY EXIST IS A WIDER QUESTION THAN WHERE IT MAY BE SEEN, and
// these bounds answer the first. They are DERIVED from the aperture and the
// sprite's size, never borrowed from the renderer's admission band.
//
// THE ANCHOR. logY is the VIC sprite Y: the raster line of the sprite's TOP
// row, so a sprite covers logY .. logY + SPRITE_HEIGHT - 1. logX is the VIC
// sprite X, nine bits across logX/logXHi, covering logX .. logX + 23; the
// visible display window runs from sprite X 24 to 343.
//
// THE APERTURE is rasters APERTURE_TOP_RASTER..APERTURE_BOT_RASTER (55..247),
// the terrain playfield between the two raster splits.
//
// DO NOT COLLAPSE THE TWO. MAX_SPRITE_Y (226) is where an enemy stops being
// DRAWN -- the builder's band means "the whole sprite is inside the aperture"
// and rejects rather than clips. Despawning there would kill the object at the
// instant it went invisible, and the mirror of that mistake at the top makes
// enemies materialise a third of the way down the screen instead of arriving
// through an edge. An enemy is alive and moving for as long as any part of it
// could still matter; the renderer independently decides whether it can be
// drawn this frame, and that separation is what lets one fly in off-screen.
.const ENEMY_HIDDEN_Y = APERTURE_TOP_RASTER - SPRITE_HEIGHT   // 34
                                    // the LAST Y at which a sprite is still
                                    // entirely above the aperture. Spawn here
                                    // or above and nothing is on screen yet.
.const ENEMY_CLEAR_Y  = APERTURE_BOT_RASTER + 1               // 248
                                    // the FIRST Y at which the sprite's top is
                                    // past the bottom of the aperture, so
                                    // nothing of it remains inside.
.const ENEMY_CLEAR_Y_TOP = ENEMY_HIDDEN_Y + 1                 // 35
                                    // ...and the mirror of it at the other
                                    // end: the first Y at which any part of the
                                    // sprite is still inside the aperture, so
                                    // BELOW this nothing of it remains. Used
                                    // only with a direction test -- every wave
                                    // spawns above this line and flies down
                                    // through it, so position alone would free
                                    // every enemy in the game at birth.

// SIDE CLEARANCE. The renderer admits on Y ALONE -- there is no X test in the
// builder -- so a sprite that is half off the left or right edge is scheduled
// normally and the VIC clips it in hardware. Side crossings therefore look
// exactly right without anything being added to the renderer, and these bounds
// exist to free the object once the hardware has finished clipping it.
//
// THE LEFT BOUND IS ALSO A WRAP GUARD, and that is the load-bearing half.
// logX/logXHi are UNSIGNED: the builder reads `lda logXHi / bne msbSet`, so any
// non-zero high byte sets the X MSB. An enemy allowed to walk past zero would
// borrow logXHi down to $ff and reappear 256 pixels to the RIGHT -- a sprite
// teleporting across the screen, not a sprite leaving it. Freeing at
// ENEMY_CLEAR_X_LEFT keeps the coordinate positive at all times, so nothing
// below needs to represent a negative X and no renderer special case is
// required.
.const ENEMY_CLEAR_X_LEFT  = 4      // 9-bit X below this: the sprite covers
                                    // 0..27 at most, of which only columns
                                    // 24..27 are inside the display window --
                                    // a four-pixel sliver, and the last safe
                                    // moment to free before the borrow.
.const ENEMY_CLEAR_X_RIGHT = 344    // first 9-bit X entirely past the display
                                    // window's last column (343)
.const ENEMY_CLEAR_X_RIGHT_LO = ENEMY_CLEAR_X_RIGHT - 256     // 88

// The bounds are DERIVED above, so what is checked here is that the things
// they were derived FROM still mean what this file thinks they mean.
.if (ENEMY_HIDDEN_Y + SPRITE_HEIGHT != MIN_SPRITE_Y) {
    .error "the hidden-above line no longer sits one sprite above the aperture"
}
.if (ENEMY_CLEAR_Y <= MAX_SPRITE_Y) {
    .error "the clear-below line is inside the renderer's admission band"
}
.if (ENEMY_CLEAR_Y > 255) {
    .error "the clear-below line does not fit the eight bits logY has"
}
.if (ENEMY_CLEAR_X_RIGHT_LO < 0 || ENEMY_CLEAR_X_RIGHT_LO > 255) {
    .error "the right clearance does not split into a high byte of exactly one"
}
// The matching speed check -- that one frame's movement cannot step OVER the
// left clearance window and reach a negative X unseen -- lives in
// src/movement.asm, because WM_ARC_SPEED is defined there and KickAssembler
// resolves constants strictly in import order.

// ===========================================================================
// Art. Authored multicolour, EMITTED AS AUTHORED.
// ===========================================================================
// The mux slots are multicolour from the handoff at raster 40 onwards (see
// D01C_GAMEPLAY in src/renderer.asm), so the bytes below reach the VIC meaning
// exactly what the artist drew:
//
//     pair 00   transparent
//     pair 01   $d025, SPR_MC_DARK   -- shared dark grey, the shading
//     pair 10   $d027+n              -- THIS enemy's own colour
//     pair 11   $d026, SPR_MC_LIGHT  -- shared white, the highlights
//
// PAIR 10 IS WHY EVERY ENEMY CAN STILL LOOK DIFFERENT, AND IT IS WHY A SECOND
// SPECIES COSTS THE COLOUR ARCHITECTURE NOTHING. It is the only one of the
// three that is per-sprite. On the Ring it draws the rim accent; on the
// Dropper it draws the satellites. Either way the authored wave colour in
// wmBaseCol reaches the screen through exactly the path it always did, and
// neither species needs a colour of its own. The animation changes which FRAME
// is shown; it never touches logCol.
//
// NOTHING ABOUT CLIPPING CHANGES, FOR EITHER SPECIES. src/clip.asm shifts whole
// ROWS of three bytes when an enemy straddles an aperture edge; it never looks
// inside a byte, and it takes its source address from logPtr. So it follows
// whichever species and whichever frame is live without knowing either exists.
// LEVEL 1'S ARTWORK IS COMPILED IN AT THE SLOTS LEVEL 1 CLAIMED. When there is
// a loader these two segments are what it writes instead; until then the PRG
// carries them, which is why the window's contents and the window's claims are
// asserted against each other rather than assumed to agree.
* = ENEMY_SPRITES "level1 ring frames"
#import "generated_sprites/enemy_art.asm"                 // sonicRingFrames, four 64-byte frames

* = DROPPER_SPRITES "level1 dropper frames"
#import "generated_sprites/enemy_dropper_art.asm"         // orbitalDropperFrames, four frames

* = SQUARE_SPRITES "level1 square frames"
#import "generated_sprites/enemy_square_art.asm"          // squareFrames, four frames

// The names the rest of the engine knew the Ring's art by, kept pointing at the
// same things they always meant: the first frame's bytes, and the address that
// art ends at. src/ebullet.asm places the projectile above enemyBitmapEnd.
.label enemyBitmap    = sonicRing_north
.label enemyBitmapEnd = sonicRingFramesEnd

.if (sonicRingFramesEnd - sonicRingFrames != ENEMY_FRAMES * 64) {
    .error "the Ring art is not ENEMY_FRAMES blocks of 64 bytes"
}
.if (orbitalDropperFramesEnd - orbitalDropperFrames != DROPPER_FRAMES * 64) {
    .error "the Dropper art is not DROPPER_FRAMES blocks of 64 bytes"
}
// THE FRAMES MUST BE ADJACENT AND IN THE AUTHORED ORDER, because the sequence
// tables below are written as "first + n" rather than as a list of addresses.
// Checked against the labels themselves so that reordering an art file is a
// build error rather than a scrambled animation.
.if (sonicRing_north != ENEMY_SPRITES + 0 * 64) { .error "Ring frame 0 is not north" }
.if (sonicRing_east  != ENEMY_SPRITES + 1 * 64) { .error "Ring frame 1 is not east"  }
.if (sonicRing_south != ENEMY_SPRITES + 2 * 64) { .error "Ring frame 2 is not south" }
.if (sonicRing_west  != ENEMY_SPRITES + 3 * 64) { .error "Ring frame 3 is not west"  }
.if (orbitalDropper_0_wide        != DROPPER_SPRITES + 0 * 64) { .error "Dropper frame 0 is not wide" }
.if (orbitalDropper_1_front_right != DROPPER_SPRITES + 1 * 64) { .error "Dropper frame 1 is not front-right" }
.if (orbitalDropper_2_front       != DROPPER_SPRITES + 2 * 64) { .error "Dropper frame 2 is not front" }
.if (orbitalDropper_3_front_left  != DROPPER_SPRITES + 3 * 64) { .error "Dropper frame 3 is not front-left" }
.if (squareFramesEnd - squareFrames != SQUARE_FRAMES * 64) {
    .error "the Square art is not SQUARE_FRAMES blocks of 64 bytes"
}
.if (square_0_full   != SQUARE_SPRITES + 0 * 64) { .error "Square frame 0 is not full" }
.if (square_1_turn   != SQUARE_SPRITES + 1 * 64) { .error "Square frame 1 is not turn" }
.if (square_2_narrow != SQUARE_SPRITES + 2 * 64) { .error "Square frame 2 is not narrow" }
.if (square_3_edge   != SQUARE_SPRITES + 3 * 64) { .error "Square frame 3 is not edge" }

// ===========================================================================
// PER-OBJECT SPECIES. MAIN THREAD ONLY.
// ===========================================================================
// One byte per POOL SLOT, written at spawn and then never again for that
// object's life. That is the whole of the type system, and the placement is
// what gives it the property that matters:
//
//     ONCE SPAWNED, AN ENEMY'S SPECIES IS STABLE FOR ITS LIFETIME.
//
// It is stored on the OBJECT and not looked up through the wave that made it,
// because wave INSTANCES are a pool of two slots that are recycled: an enemy
// routinely outlives the instance that spawned it, and that slot is then
// re-armed by a different authored wave. An enemy that asked "what species is
// my wave?" would change appearance mid-flight the moment the next trigger
// reused its slot. Copying the byte at spawn severs that link entirely.
//
// It lives in the hole between the clip state and the enemy state rather than
// in the object pool's own block, because that block ends at $c5f2 and the
// collision state begins at $c5f3 -- there is no room there for another
// sixteen-byte array, and growing into a neighbour is exactly the silent
// overwrite the segment guards exist to prevent.
//
// objectZeroSlot clears it with the rest of the slot, so a reused slot cannot
// inherit the previous occupant's species. That is the pool's invariant and
// this array is subject to it like every other per-object field.
// THE RESOLVED ANIMATION TABLE. RAM, not PRG: levelAssetsLoad fills it from the
// shape above and the current level's window claims, once, at gameInit. Until
// it runs this is zeros, which is why the call sits before anything can spawn.
//
// Read once per live enemy per frame by enemyAnimPtrBody, as an absolute,Y --
// exactly as it read the old constant table, so the hot path did not change.
// IT MOVED FOR THE THIRD SPECIES, and the segment guard is what made that a
// build failure rather than a silent overwrite. The table is one row of
// ENEMY_ANIM_STEPS per species, so a third species took it from 16 bytes to 24
// and its old home at $c4f0 had exactly 16 before the species array at $c500.
// It now lives in the hole between the level asset state ($c400, two bytes) and
// the token encounter state ($c43f), which is the right neighbourhood anyway:
// levelAssetsLoad is what fills it. $c4f0-$c4ff is now free.
* = $c410 "enemy animation table"
enemyAnimSeq:  .fill SPECIES_COUNT * ENEMY_ANIM_STEPS, 0
enemyAnimSeqEnd:
.if (enemyAnimSeqEnd > $c43f) {
    .error "the resolved animation table has grown into the token encounter state at $c43f"
}

* = $c4e0 "enemy firing"

// ===========================================================================
// PER-OBJECT FIRING AUTHORITY. MAIN THREAD ONLY.
// ===========================================================================
// One byte per POOL SLOT: non-zero means THIS enemy may take a shot, zero
// means it never will. Written once at spawn by src/waves.asm, which is the
// only thing that knows both halves of the answer -- the SPECIES can fire at
// all (enemyFireModeTab below) and this APPEARANCE was authored to (the
// trigger list's fire mask) -- and read only by the director's firing tick.
//
// IT IS ON THE OBJECT FOR THE SAME REASON enySpecies IS, and the reason is
// sharper here. A wave INSTANCE is freed the moment its last member is SENT,
// not when its enemies die -- see waveRunInstance -- so an enemy spends almost
// its whole life with no instance behind it. Authority that lived on the
// instance would evaporate seconds before the enemy left the screen, and
// authority read THROUGH the instance slot would be answered by whichever
// unrelated wave was armed there next.
//
// objectZeroSlot clears it with the rest of the slot, so a slot freed by a
// firing enemy and handed to a non-firing one cannot inherit the licence.
enyFire:       .fill MAX_OBJECTS, 0     // 0 = never fires
enyFireEnd:
.if (enyFireEnd > $c4f0) {
    .error "the enemy firing array has grown into the animation table at $c4f0"
}

* = $c500 "enemy species"
enySpecies:    .fill MAX_OBJECTS, 0     // one of the SPECIES_* row offsets
enySpeciesEnd:
.if (enySpeciesEnd > $c517) {
    .error "the enemy species array has grown into the enemy state at $c517"
}

// ===========================================================================
// State. MAIN THREAD ONLY, three bytes in a hole below the player's state.
// ===========================================================================
* = $c517 "enemy state"
enyDespawned:  .byte 0, 0               // 16-bit, saturating: total despawned.
                                        // enemyDespawn is the ONLY place an
                                        // enemy's slot is released, so this
                                        // counts every enemy life that ended
enyScratch:    .byte 0                  // enemyTick's one spare byte: the clip
                                        // arithmetic needs logY back after the
                                        // compare that classified it
enyStateEnd:
.if (enyStateEnd > $c51a) { .error "the enemy state has grown into the player state at $c51a" }

* = $4900 "enemy code"

// --- the species firing capability table ------------------------------------
// INDEXED BY SPECIES >> ENEMY_ANIM_SHIFT. A species value is its ROW in the
// animation table -- 0 and 8, not 0 and 1 -- so the shift that turns a row
// back into an index is the same one enemyAnimPtr's composition implies. Read
// ONCE PER SPAWN by src/waves.asm, never per frame.
enemyFireModeTab:
    .byte ENEMY_FIRE_DOWN                           // SPECIES_RING
    .byte ENEMY_FIRE_DOWN                           // SPECIES_DROPPER
    .byte ENEMY_FIRE_DOWN                           // SPECIES_SQUARE: the Ring's
                                                    // baseline, deliberately --
                                                    // Square is an ordinary
                                                    // species with no special
                                                    // capability of its own
.if (* - enemyFireModeTab != SPECIES_COUNT) {
    .error "the species firing table does not have one entry per species"
}

// ---------------------------------------------------------------------------
// enemyInit — clear the despawn tally. The pool itself is objectInit's job.
// ---------------------------------------------------------------------------
enemyInit:
    lda #0
    sta enyDespawned
    sta enyDespawned + 1
    rts

// ---------------------------------------------------------------------------
// THE ANIMATION SEQUENCES — one row of ENEMY_ANIM_STEPS pointers per species.
//
// A TABLE OF POINTERS, NOT OF FRAME INDICES, so the lookup IS the answer: the
// caller stores what it reads straight into logPtr with no arithmetic. It also
// means the two species need not agree about anything -- not their frame
// count, not their base address, not the path they take through their frames.
//
// THE RING ROTATES. Its four frames are a true rotation, so 3 follows 2 and 0
// follows 3 with no discontinuity; eight steps is simply two revolutions, and
// a full table cycle shows two complete spins.
//
// THE DROPPER PING-PONGS, and must. Its frames are not a rotation but a
// SWEEP: the satellite crosses from the right edge (frame 1) through centre
// (2) to the left (3), with frame 0 the opposite extreme where both satellites
// sit at the rim. Wrapping 3 straight back to 0 would jump the satellite from
// one side of the orb to the other in a single step -- a teleport. Playing the
// sequence back down again is what completes the apparent orbit, exactly as
// the artwork's own note says.
//
// THE DOUBLED ENDPOINTS ARE DELIBERATE. A strict ping-pong is six steps and
// six can never divide the 256-frame wrap (see the ENEMY_ANIM_STEPS note), so
// the two spare steps are spent holding each turnaround for one extra beat.
// That is also what the motion being depicted actually does: a satellite
// crossing a sphere appears to slow, stop and reverse at the edges while
// moving fastest through the middle. The dwell reads as the turn, not as a
// stall.
// ---------------------------------------------------------------------------
// THE SHAPE IS FRAME INDICES, NOT POINTERS, AND THAT IS THE CHANGE. This table
// used to hold absolute sprite pointers built from ENEMY_PTR_FIRST and
// DROPPER_PTR_FIRST, which pinned each species to one address for the life of
// the game. It now holds each species' frames as indices FROM ITS OWN BASE, so
// it describes only the path a species walks through its own artwork -- which
// is behaviour, is resident, and does not change when a level does.
//
// The addresses come from the level. levelAssetsLoad adds the base of whatever
// window slot the current package loaded a species into, and writes the result
// into enemyAnimSeq below. Same table for the reader, same one ORA in the hot
// path; the difference is that it is now RAM that a level fills in.
// Named as assembler lists so the rows can be CHECKED as well as emitted: a
// step that names a frame its species does not have would otherwise walk off
// the end of that species' slot and into whatever the level loaded next to it.
.var RING_SHAPE    = List().add(0, 1, 2, 3,  0, 1, 2, 3)   // rotate, twice
.var DROPPER_SHAPE = List().add(0, 1, 2, 3,  3, 2, 1, 0)   // out and back
// THE SQUARE SPINS, and a spin reverses: frames 0..3 narrow the silhouette from
// a full face to an edge-on bar, so running them out and back is one complete
// revolution rather than a jump from edge-on straight back to full face.
.var SQUARE_SHAPE  = List().add(0, 1, 2, 3,  3, 2, 1, 0)   // out and back

.for (var i = 0; i < RING_SHAPE.size(); i++) {
    .if (RING_SHAPE.get(i) >= ENEMY_FRAMES) {
        .error "a Ring animation step names a frame the Ring does not have"
    }
}
.for (var i = 0; i < DROPPER_SHAPE.size(); i++) {
    .if (DROPPER_SHAPE.get(i) >= DROPPER_FRAMES) {
        .error "a Dropper animation step names a frame the Dropper does not have"
    }
}
.for (var i = 0; i < SQUARE_SHAPE.size(); i++) {
    .if (SQUARE_SHAPE.get(i) >= SQUARE_FRAMES) {
        .error "a Square animation step names a frame the Square does not have"
    }
}
.if (RING_SHAPE.size() != ENEMY_ANIM_STEPS || DROPPER_SHAPE.size() != ENEMY_ANIM_STEPS
     || SQUARE_SHAPE.size() != ENEMY_ANIM_STEPS) {
    .error "an animation shape row is not ENEMY_ANIM_STEPS steps long"
}

enemyAnimShape:
    .fill RING_SHAPE.size(), RING_SHAPE.get(i)          // SPECIES_RING
    .fill DROPPER_SHAPE.size(), DROPPER_SHAPE.get(i)    // SPECIES_DROPPER
    .fill SQUARE_SHAPE.size(), SQUARE_SHAPE.get(i)      // SPECIES_SQUARE
enemyAnimShapeEnd:
.if (enemyAnimShapeEnd - enemyAnimShape != SPECIES_COUNT * ENEMY_ANIM_STEPS) {
    .error "the animation shape is not one row of ENEMY_ANIM_STEPS per species"
}

// ---------------------------------------------------------------------------
// enemyAnimPtr — the sprite pointer THIS enemy should be showing this frame.
// Entry: X = the object's pool slot.
// Exit:  A = the pointer. X preserved, Y clobbered, no memory written.
//
// ONE GLOBAL PHASE SHARED BY BOTH SPECIES, and it costs no state at all.
//
// The phase is DERIVED from the renderer's frameCounter rather than counted in
// a timer of this file's own. That is the whole trick: frameCounter already
// advances exactly once per displayed frame, in exFrame, so shifting it right
// by ENEMY_ANIM_SHIFT and masking to ENEMY_ANIM_STEPS gives a step that
// advances on a fixed cadence for free -- no byte of state, no per-frame
// decrement, and nothing that can drift out of step with the display if a
// frame is ever skipped. The assertion beside ENEMY_ANIM_STEPS is what allows
// reading only the LOW byte: 256 is a whole number of cycles, so the wrap is
// seamless.
//
// SPECIES SELECTS THE ROW, THE PHASE SELECTS THE COLUMN. Both species step
// together on the same beat; they differ only in what their row of the table
// says to show. That is why a second enemy cost no new timing machinery.
//
// LOCKSTEP IS A DECISION, not an accident. Every enemy of a species is at the
// same point of its animation, which reads as one mechanism rather than as
// clutter. Giving a species -- or an object -- its own phase later means
// replacing the derivation below with a stored byte, and no caller changes,
// because callers already ask a routine rather than compute it themselves.
// ---------------------------------------------------------------------------
// THE BODY IS A MACRO BECAUSE enemyTick CANNOT AFFORD THE CALL. This runs once
// per live enemy per displayed frame, and jsr plus rts is twelve cycles of pure
// overhead on top of a twenty-two cycle body -- more than a third of the cost,
// paid seven times a frame at peak population. The main thread routinely uses
// over 255 of a PAL frame's 312 raster lines, so that overhead is not free
// margin; it is margin the scroller's publication is already competing for.
//
// So the hot caller expands it inline and the rare one (waveSpawnMember, a few
// times a second) keeps the subroutine. One definition either way, which is the
// whole reason this is a macro rather than a copied block of instructions.
.macro enemyAnimPtrBody() {
    lda frameCounter                    // low byte only: see the wrap assertion
    .for (var i = 0; i < ENEMY_ANIM_SHIFT; i++) {
        lsr                             // /2 per shift: hold each step for
    }                                   // 1 << ENEMY_ANIM_SHIFT displayed frames
    and #ENEMY_ANIM_STEPS - 1           // a mask, not a compare: the step count
                                        // is asserted a power of two
    ora enySpecies,x                    // the species IS its row offset, and the
                                        // step is the low bits, so one ORA
                                        // composes the whole table index -- no
                                        // shift, no branch, no add
    tay
    lda enemyAnimSeq,y                  // the table holds POINTERS: this is the
}                                       // complete answer, not a frame number

enemyAnimPtr:
    enemyAnimPtrBody()
    rts

// ---------------------------------------------------------------------------
// enemyTick — one frame of ONE enemy. MAIN THREAD.
// Entry/exit: X = the object's slot, PRESERVED across the free.
// ---------------------------------------------------------------------------
enemyTick:
    // ---- the spin, and it is the FIRST thing so that it is unconditional ---
    // Every enemy gets this frame's phase written into its logPtr, alive or
    // dying. Presentation only: logPtr is the sprite POINTER, so this changes
    // which of the four frames the VIC fetches and nothing else. Movement,
    // collision, HP, firing and the despawn rules below never read it.
    //
    // A dying ring keeps spinning deliberately -- the death is a colour ramp
    // over the same silhouette, and freezing the rotation half way through it
    // would read as the animation having broken rather than the enemy having.
    enemyAnimPtrBody()                  // INLINE, not jsr: see the macro's note
    sta logPtr,x

    // ---- dying enemies run their death out and do not move ----------------
    // A dying enemy stays renderable but stops following its path: an explosion
    // that keeps flying reads as a live enemy the player cannot kill.
    lda objHP,x
    bne !alive+
    jmp enemyDeathTick
!alive:

    // ---- the hit flash, if one is running ---------------------------------
    lda objTimer,x
    beq !noFlash+
    jsr enemyFlashTick
!noFlash:

    // ---- WHERE IT IS THIS FRAME -------------------------------------------
    // All movement lives in src/movement.asm: the enemy runs whichever
    // primitive its wave handed it, at quarter-pixel resolution, and this file
    // does not know whether that is a straight vector or a phase of an arc.
    // Two enemies from two waves can be at different points of different
    // primitives in one call to objectUpdateAll -- the property the encounter
    // director is built on.
    // ...UNLESS THE TOKEN ENCOUNTER HAS TAKEN THIS ONE OVER. A guard is an
    // ordinary enemy in every respect except where it gets its position from:
    // src/token.asm walks it toward a post on the ring around the token
    // instead, and no movement program runs for it at all. That is the whole
    // of "detached from its authored path" -- one branch, here, and nothing in
    // src/movement.asm has to know roles exist.
    //
    // A DISMISSED enemy is NOT routed away: ROLE_EGRESS is flown by the
    // ordinary wmTick, because the encounter gave it a terminal WM_EXIT and
    // the movement interpreter already knows how to fly one of those.
    // ...OR UNLESS IT IS THE DROPPER, WHICH FLIES ITS OWN PATH. A Dropper is
    // checked FIRST and never reaches the role test, because a Dropper can
    // never be anything but ROLE_NORMAL: roles are handed out by the token
    // encounter, which only exists once a Dropper has died, and the
    // one-live-Dropper rule means there is no second one alive to be posted.
    // Testing species first costs the common case one load and one compare
    // and saves the Dropper both.
    lda enySpecies,x
    cmp #SPECIES_DROPPER
    beq !dropper+

    lda enyRole,x
    cmp #ROLE_GUARD
    bcc !authored+                      // ROLE_NORMAL or ROLE_EGRESS
    jsr tokenGuardMove
    jmp !moved+

!dropper:
    jsr dropperFly                      // src/dropper.asm: three passes across
    jmp !moved+                         // the top of the aperture, then out

!authored:
    jsr wmTick
!moved:

    // THE DESPAWN RULES: HAS THE SPRITE LEFT THE APERTURE ALTOGETHER?
    //
    // Three edges, and the enemy survives all of them until nothing of it
    // could still be inside. It is deliberately NOT the renderer's admission
    // band: an enemy above the aperture during its approach, or being clipped
    // by a side border on its way out, is alive and moving and simply not
    // drawn this frame. See the lifecycle bounds at the top of this file.
    //
    // TERMINATION IS PROVED, NOT HOPED: src/waves.asm flies every authored
    // pattern at assembly time and rejects one that never reaches an edge.
    //
    // THE SIDE TESTS ASK WHICH WAY THE ENEMY IS GOING, and they must. Position
    // alone cannot tell ARRIVING from LEAVING: the echelon sweep spawns at X=0
    // precisely so that it slides in through the left border, and a rule that
    // freed anything behind a border would kill it on its first frame. An enemy
    // behind a border on its way IN is alive; the same enemy behind the same
    // border on its way OUT is gone.
    lda logXHi,x
    beq !checkLeft+

    // High byte set, so X is 256..511: the only way out is the right edge.
    lda logX,x
    cmp #ENEMY_CLEAR_X_RIGHT_LO
    bcc !checkVertical+
    lda wmVX,x
    beq !checkVertical+                   // parked behind the border: not gone
    bmi !checkVertical+                   // coming back in
    jmp !gone+

!checkLeft:
    lda logX,x
    cmp #ENEMY_CLEAR_X_LEFT
    bcs !checkVertical+
    lda wmVX,x
    bmi !gone+                          // still travelling left: it has left

!checkVertical:
    // THE VERTICAL PAIR, AND THE TOP HALF ASKS WHICH WAY IT IS GOING for
    // exactly the reason the side tests do. Every authored wave spawns ABOVE
    // the aperture and flies down into it, so a rule that freed anything above
    // the top edge would kill every enemy in the game on its first frame. An
    // enemy above the aperture on its way IN is alive; the same enemy above the
    // same edge on its way OUT is gone.
    //
    // Nothing had ever left that way until v2.1, which is why this test is
    // newer than the other three: the token encounter dismisses its surviving
    // protectors UPWARD rather than down through the player who has just
    // collected the token (see src/token.asm). WM_EXIT carries them, wmVY is
    // signed, and this is the edge that retires them.
    lda logY,x
    cmp #ENEMY_CLEAR_Y
    bcs !gone+                          // below the bottom: gone either way
    cmp #ENEMY_CLEAR_Y_TOP
    bcs !alive+                         // inside the band: the common case, and
                                        // the only one that costs a compare
    lda wmVY,x
    bmi !gone+                          // still travelling up: it has left
    bpl !alive+                         // descending or parked: arriving
!gone:
    jmp enemyDespawn
!alive:
    // falls through to the presentation clip

// ---------------------------------------------------------------------------
// HOW MUCH OF THIS ENEMY IS OUTSIDE THE APERTURE — presentation only.
//
// logY is NOT touched. This writes one annotation, logClip, which the schedule
// builder turns into a clamped Y and a row-shifted bitmap (src/clip.asm); the
// enemy goes on moving, colliding and dying by its true coordinate.
//
//   logY <  MIN_SPRITE_Y   c = MIN_SPRITE_Y - logY, positive: rows above
//   logY >  MAX_SPRITE_Y   c = MAX_SPRITE_Y - logY, negative: rows below
//   otherwise              0
//
// A count of SPRITE_HEIGHT or more means nothing of the sprite is inside the
// aperture at all. Those are left at zero DELIBERATELY: logY is then outside
// the admission band, so the builder's ordinary Y test refuses the entry and a
// fully invisible enemy costs no scratch block, no mux slot and no schedule
// entry -- while remaining perfectly alive.
//
// IT IS SHARED, AND THE LABEL IS WHY. enemyTick falls straight into this, but
// src/pickup.asm calls it: a token is clipped by exactly the same rule and
// through exactly the same schedule-owned scratch, so it asks the routine that
// already knows the rule rather than carrying a second copy that could drift.
// Nothing in here is enemy-specific -- it reads logY and writes logClip.
// Entry/exit: X = the logical slot, preserved.
logClipAnnotate:
    lda logY,x
    cmp #MIN_SPRITE_Y
    bcc !above+
    cmp #MAX_SPRITE_Y + 1
    bcs !below+
    lda #0                              // wholly inside: present as authored
    beq !store+                         // (always taken)

!above:
    sta enyScratch                      // logY, still in A
    lda #MIN_SPRITE_Y
    sec
    sbc enyScratch                      // 1..SPRITE_HEIGHT-1 while any is seen
    cmp #SPRITE_HEIGHT
    bcc !store+
    lda #0                              // entirely above: let admission cull it
    beq !store+

!below:
    sec
    sbc #MAX_SPRITE_Y                   // 1..SPRITE_HEIGHT-1, as a magnitude
    cmp #SPRITE_HEIGHT
    bcs !hidden+
    eor #$ff                            // negate: rows BELOW are negative
    clc
    adc #1
    bne !store+                         // (never zero: the magnitude was not)
!hidden:
    lda #0

!store:
    sta logClip,x
    rts

// ---------------------------------------------------------------------------
// enemyFlashTick — one frame of the hit flash. Entry/exit: X = slot, preserved.
//
// ONE COLOUR HELD FOR THE WHOLE WINDOW, where this used to walk a two-stage
// white-then-yellow ladder. The ladder existed to read as a hot flash cooling
// back toward the body colour, which needed the flash to START at a brightness
// the body could cool FROM. HIT_COL_FLASH is a hue rather than a brightness --
// see the note in src/collision.asm -- so a second stage would only muddy the
// one frame it occupied. The timing is unchanged: HIT_FLASH_TIME is 4, the
// colour is held for three frames, and the fourth restores.
// ---------------------------------------------------------------------------
enemyFlashTick:
    dec objTimer,x                      // DEC sets Z on the result, so the
    beq !expired+                       // expiry test needs no reload
    lda #HIT_COL_FLASH
    sta logCol,x
    rts
!expired:
    jmp enemyBaseColour                 // back to the spawn colour; its rts
                                        // is ours, and X is preserved

// ---------------------------------------------------------------------------
// enemyDeathTick — one frame of dying. Entry/exit: X = slot, preserved.
//
// Reached only with objHP zero. The timer runs DEATH_TIME frames and the slot
// is freed on the frame it reaches zero -- routed through enemyDespawn, so an
// enemy is released from exactly one place however it died.
//
// The explosion is a colour progression over the enemy's own shape rather than
// a bitmap swap: a bounded yellow-orange-red flash, costing no extra art.
// ---------------------------------------------------------------------------
enemyDeathTick:
    dec objTimer,x
    beq !release+

    lda objTimer,x                      // three equal thirds of DEATH_TIME
    cmp #8
    bcs !blast1+
    cmp #4
    bcs !blast2+
    lda #DEATH_COL_3
    sta logCol,x
    rts
!blast2:
    lda #DEATH_COL_2
    sta logCol,x
    rts
!blast1:
    lda #DEATH_COL_1
    sta logCol,x
    rts

!release:
    // The death animation is over. A NORMAL despawn: the same call, the same
    // membership update, the same guarantee that CURRENT is not touched.
    //
    // ---------------------------------------------------------------------
    // ...EXCEPT THAT A DESTROYED DROPPER DROPS A TOKEN, AND THIS IS THE HOOK
    // ---------------------------------------------------------------------
    // THE LOGICAL DESTRUCTION EVENT AND NOTHING ELSE. This path is reached
    // only by an enemy whose health reached zero and whose death animation has
    // run out; an enemy that merely flew off an edge goes through the despawn
    // rules in enemyTick and never arrives here. So a Dropper the player let
    // escape drops nothing, which is the rule the reward depends on.
    //
    // Nothing here reads a sprite pointer, an animation frame, a colour or any
    // VIC state: the species byte is the identity and objHP reaching zero is
    // the event.
    //
    // THE ORDER IS THE ALLOCATION POLICY. The position is captured first
    // because objectFree zeroes the slot, and the slot is released BEFORE the
    // token is asked for -- which guarantees the pool has room for it. A
    // reward the player earned must not be lost to a full pool, and this costs
    // nothing: the object that just died was occupying exactly the slot the
    // token needs. No deferred queue, no retry, no dropped token.
    lda enySpecies,x
    cmp #SPECIES_DROPPER
    beq !dropper+
    jmp enemyDespawn

!dropper:
    lda logX,x
    sta pkSpawnXLo
    lda logXHi,x
    sta pkSpawnXHi
    lda logY,x
    sta pkSpawnY                        // the token appears where it died

    jsr enemyDespawn                    // frees the slot: capacity guaranteed
    txa                                 // objectUpdateAll requires X back, and
    pha                                 // the encounter clobbers it
    jsr tokenDropperDied
    pla
    tax
    rts

// ---------------------------------------------------------------------------
// enemyBaseColour — the colour a hit flash returns to.
// Entry/exit: X = slot, preserved.
//
// The colour is STORED at spawn, in wmBaseCol, rather than derived from the
// enemy's velocity or wave: a composed path turns every few frames, so by the
// time an enemy is hit nothing about its current motion identifies it.
// ---------------------------------------------------------------------------
enemyBaseColour:
    lda wmBaseCol,x
    sta logCol,x
    rts

// ---------------------------------------------------------------------------
// enemyDespawn — this enemy's life ends. Entry/exit: X = slot, preserved.
//
// There is nothing to undo in the renderer. The sprite this object was drawn
// through is not "turned off": the next schedule the builder produces simply
// does not contain it, and $d015 is composed from that schedule rather than
// edited. That is the whole point of the boundary.
// ---------------------------------------------------------------------------
enemyDespawn:
    // THE ONE PLACE A DROPPER'S LIVENESS IS RELEASED, and it is here rather
    // than on the death path because BOTH ways of leaving have to clear it: a
    // Dropper that was shot and one that simply flew off the bottom both stop
    // being the live Dropper. Reading the species before objectFree matters --
    // objectZeroSlot is about to erase it.
    lda enySpecies,x
    cmp #SPECIES_DROPPER
    bne !notDropper+
    lda #0
    sta tkDropperLive
!notDropper:

    jsr objectFree

    inc enyDespawned                    // 16-bit, saturating at $ffff
    bne !counted+
    inc enyDespawned + 1
    bne !counted+
    lda #$ff
    sta enyDespawned
    sta enyDespawned + 1
!counted:
    rts

.if (* > $4c00) { .error "the enemy code has outgrown its $4900 segment" }
