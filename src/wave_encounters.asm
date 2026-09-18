// ===========================================================================
// wave_encounters.asm — THE AUTHORED ENCOUNTER SCHEDULE, as data
// ===========================================================================
// CONSTANTS AND .var DATA ONLY. It emits no bytes and moves no program counter:
// it builds the wave-definition and absolute-trigger lists, and whoever imports
// it decides what to do with them.
//
// TWO BUILDS IMPORT IT, which is why it is its own file:
//
//   src/waves.asm          validates it -- the structural checks, the flight
//                          simulation of every member of every wave, and the
//                          Stage 1 trigger ordering rules -- and declares the
//                          package addresses the director reads from.
//   src/level_package.asm  emits the bytes into the separately loaded level
//                          package, which is where the running engine actually
//                          reads them.
//
// THE ENGINE PRG NO LONGER CONTAINS THESE BYTES. Wave definitions and triggers
// are level content and now ship in the level file beside the terrain, the
// metatile definitions and the movement programs.
//
// WHAT IS DELIBERATELY NOT HERE: anything the ENGINE owns. The Dropper's flight,
// the P-token, the protector conscription and the boss lifecycle are engine
// state machines that a level does not author; the only thing a level says about
// the Dropper is which trigger carries it and which side it enters from.
//
// The level editor will eventually generate this file. Until it does it is
// authored here -- the arrangement the architecture review recommended: the
// runtime authoritative bytes move first, the exporter follows.
// ===========================================================================

// IMPORTED MORE THAN ONCE PER BUILD.
#importonce

#import "encounter_format.asm"          // SPECIES_*, DROP_SIDE_*
#import "wave_programs.asm"             // PROG_*, and the movement pool offsets

// --- the authored wave definitions ------------------------------------------
// Ten bytes each, and the record is deliberately flat: the director reads it
// with one indexed load per field and never copies it anywhere.
//
//   0  count      how many enemies this wave sends
//   1  interval   frames between one member and the next
//   2  startXLo   nine-bit spawn X...
//   3  startXHi
//   4  startY     spawn line, inside the renderer's production band
//   5  xStep      signed, added to X per member
//   6  yStep      signed, added to Y per member
//   7  colour     every member of a wave shares one, so which wave an enemy
//                 belongs to is visible on screen
//   8  heading    launch heading, 0..WM_HEAD_LEN-1
//   9  program    byte offset of its first stage record
//
// YSTEP IS THE MUX-FRIENDLINESS FIELD. Fanning members along X alone lets a
// four-strong wave enter as a RANK on one raster line and stay that way for as
// long as its launch leg is level -- four logical sprites competing for one
// reuse window, the geometry the multiplexer finds hardest. Fanning Y turns the
// entry into an ECHELON: members arrive on distinct lines, spread further as
// their paths diverge, and reach the exit at different times.
//
// It is not always the right tool, though: see the top-entering waves below,
// which fan vertically through the INTERVAL instead, because a yStep would push
// their later members into view rather than letting them arrive through the
// edge.
.const WAVEDEF_SIZE = 10

// --- 0: "echelon sweep" -----------------------------------------------------
// Four across the top-left, each 20 lines below and 16 pixels right of the one
// before, all running east and turning down together. The stagger is what
// makes it an echelon rather than a rank: the members are 20 lines apart at
// entry -- a sprite is 21 tall -- and the quarter turn preserves that spacing
// all the way to the exit.
.var defSweep = List().add(
    4, 22,              // count, interval
    0, 0,               // startX = 0: the sprite covers columns 0..23 and the
                        // display window starts at 24, so it is ENTIRELY
                        // behind the left border and slides into view through
                        // it. This is the one edge the hardware clips for us.
    64,                 // startY: inside the aperture, because this pattern
                        // arrives from the SIDE rather than from above
    0, 20,              // xStep 0, yStep +20: every member enters at the same
                        // point on the border and the INTERVAL spaces them
                        // along X as they fly east -- 33 pixels per member --
                        // while yStep stacks them into an echelon. Fanning X
                        // at spawn would have put the later members on screen
                        // before they had entered.
    10,                 // colour: light red
    0,                  // heading: due east, straight through the border
    PROG_SWEEP)

// --- 1: "S-turn" ------------------------------------------------------------
// Three entering steep from ABOVE the aperture and weaving right then away
// left. startY 30 puts the whole 21-line sprite above raster 55 with four
// lines to spare, and the launch heading descends at a pixel and a half a
// frame, so it is in view about seventeen frames later.
.var defSTurn = List().add(
    3, 26,
    90, 0,              // startX = 90
    30,                 // startY: hidden above the aperture
    28, 0,              // xStep +28, yStep 0: the Y separation comes from the
                        // interval instead. Every member descends, so 26
                        // frames of head start IS vertical spacing -- and a
                        // positive yStep would have pushed the later members
                        // down into view before they had entered.
    3,                  // colour: cyan
    12,                 // heading: steep down-right
    PROG_S)

// --- 2: "linger and break" --------------------------------------------------
// Three running in from above on a shallow diagonal and hanging in the middle
// third. The interval gives the members about 32 lines of separation by the
// time they park, which is more than a sprite is tall -- and parking is
// exactly when that matters.
.var defLinger = List().add(
    3, 26,
    120, 0,             // startX = 120
    30,                 // startY: hidden above the aperture
    36, 0,              // xStep +36, yStep 0: as above, the descent plus the
                        // interval is the vertical fan
    7,                  // colour: yellow
    10,                 // heading: down-right, shallow
    PROG_LINGER)

// --- 3: "loop" --------------------------------------------------------------
// Three loops, widely spaced in time (34 frames) as well as in space, because
// three simultaneous circles in one place would be a knot rather than a
// manoeuvre. The dive stage in PROG_LOOP is what brings them in from hiding.
.var defLoop = List().add(
    3, 34,
    70, 0,              // startX = 70
    30,                 // startY: hidden above the aperture
    50, 0,              // xStep +50: the circles are 62 pixels across, so they
                        // need most of that between them to read as three
                        // separate manoeuvres. yStep 0: the dive plus the
                        // interval separates them vertically.
    13,                 // colour: light green
    8,                  // heading: down-right, so the dive carries it into
                        // view and the circle hangs below and left of where
                        // the loop starts
    PROG_LOOP)

.var waveDefs = List().add(defSweep).add(defSTurn).add(defLinger).add(defLoop)
.const WAVE_DEFS     = 4
.const WAVE_DEF_SWEEP  = 0
.const WAVE_DEF_S      = 1
.const WAVE_DEF_LINGER = 2
.const WAVE_DEF_LOOP   = 3

.if (waveDefs.size() != WAVE_DEFS) { .error "wave definition count disagrees with the table" }

// ---------------------------------------------------------------------------
// THE AUTHORED TRIGGER LIST, in ABSOLUTE sixteen-bit worldProgress rows.
//
// worldProgress is the scroller's own "coarse rows travelled since the stage
// start", it only ever increases, and it advances once every eight frames --
// so it is the natural clock for encounters tied to how far through the level
// the player actually is, rather than to how long the machine has been on.
//
// ABSOLUTE ROWS, AND THE LIST DOES NOT REPEAT.
//
//     A trigger names one absolute sixteen-bit world row. Once consumed it
//     never becomes due again unless another authored trigger explicitly
//     exists at another row.
//
// This replaces a delta column that the director accumulated into a running
// target and a cursor that WRAPPED, so the four authored moments recurred every
// 126 rows for the whole stage -- thirteen times over Level 1, and fifty-two
// times over the 420-row proof. That repetition was an artefact of the
// encoding, not a decision anybody made: nothing could be placed at row 900
// without also placing it at row 774 and row 1026.
//
// WHY THIS IS ALSO CHEAPER. A delta schedule has to MAINTAIN its target -- a
// sixteen-bit add with a carry chain on every trigger, plus two bytes of state
// holding a number that is a function of authored data. An absolute row is read
// straight out of the table the cursor already indexes: the compare is the same
// compare, and waveAdvanceCursor becomes an `inc`. See waveTick.
//
// THE ROWS ARE SPACED BY WAVE FOOTPRINT, NOT INSTANCE LIFETIME, and that
// distinction is what gives the game its pacing. An INSTANCE is held only until
// its last member is sent -- 1 + (count-1)*interval frames, about eight coarse
// rows for every wave here -- but its ENEMIES stay alive for far longer.
// Spacing on instance lifetime would run every formation into the next one
// continuously, with never a moment of one pattern alone on screen.
//
// So the gap to the next row is the wave's whole footprint: the span it spends
// spawning plus the lifetime of its last member to leave.
//
//     sweep   66 +  177 = 243 frames = 30 rows
//     s-turn  52 +  200 = 252 frames = 32 rows
//     linger  52 +  206 = 258 frames = 32 rows
//     loop    68 +  317 = 385 frames = 48 rows
//
// Each formation has cleared the aperture before the next arrives: pattern,
// empty sky, pattern.
//
// ONE DELIBERATE OVERLAP: rows 48 and 52 are four rows apart, which is shorter
// than the sweep's occupancy and therefore puts two INSTANCES in flight at
// once. They are the right pair for it -- the sweep enters through the LEFT
// BORDER at a fixed height and the S-turn comes down from ABOVE on the other
// side of the screen, so the two formations are separated in entry point,
// direction and Y for the whole time they share the aperture. That is an
// overlap the multiplexer is never asked to work for.
//
// THESE FOUR ROWS ARE THE ONES THE DELTA SCHEDULE ACTUALLY PRODUCED for its
// first cycle, measured on the running machine rather than read off the
// arithmetic: waveInit armed the first trigger at delta[0] = 48, and
// waveAdvanceCursor then added the delta of the trigger it had just moved ON
// TO. So 48, 48+4, 52+38, 90+36. Level 1 is spatially unchanged.
//
// After row 126 the stage is deliberately QUIET: Level 1 runs to row 395 and
// the remaining 269 rows carry no authored encounter. That is the migration
// being visible rather than a gap to fill in this task.
.var trigRow   = List().add(48, 52, 90, 126)
.var trigDef   = List().add(WAVE_DEF_SWEEP, WAVE_DEF_S, WAVE_DEF_LINGER, WAVE_DEF_LOOP)

// WHICH ENEMY THE WAVE IS MADE OF, and it is an AUTHORED COLUMN rather than
// arithmetic on the cursor. Every member of one wave is the same species; the
// next authored wave is the other one.
//
// A third parallel column rather than `cursor AND 1` because the alternation is
// CONTENT, not a rule. Written down, it can be read at a glance, it survives
// someone inserting a fifth trigger (which `AND 1` would silently invert for
// every wave after it), and the day a particular pattern should always be
// Droppers it is one byte here rather than a special case in the director.
.var trigSpecies = List().add(SPECIES_RING, SPECIES_DROPPER,
                              SPECIES_RING, SPECIES_DROPPER)

// WHICH SIDE A DROPPER FLIES IN FROM. Read only when the species above is
// SPECIES_DROPPER; a Ring wave carries whatever is written here and ignores it,
// the same way a wave that does not shoot still carries a fire mask.
//
// A COLUMN AND NOT A RULE, for the same reason trigSpecies is one. "Alternate
// the sides" would be arithmetic on the cursor that silently inverts for every
// trigger after an inserted fifth; written down, the side a particular
// appearance comes in on is content somebody chose, it reads at a glance, and
// the mirrored appearance is one byte rather than a second code path.
//
// THE TWO SIDES ARE THE SAME ROUTINE. src/dropper.asm branches on this once, at
// launch, to pick an entry X and the sign of a velocity; everything after that
// -- the weave, the three passes, the reversals, the escape -- is direction
// agnostic. Level 1 exercises both.
.var trigSide = List().add(DROP_SIDE_LEFT, DROP_SIDE_LEFT,
                           DROP_SIDE_LEFT, DROP_SIDE_RIGHT)

// WHICH MEMBERS OF THIS APPEARANCE MAY SHOOT — a bitmask over MEMBER INDEX,
// bit 0 the first member sent, and zero for a formation that does not shoot
// at all.
//
// THE MASK IS THE WHOLE OF THE AUTHORED FIRING CONTROL, and it is a mask over
// the progression the director ALREADY RUNS rather than a new clock. wvIndex
// counts members as they are sent; member n consults bit n; the answer is
// copied onto the enemy and never revisited. There is no per-wave firing
// timer, no per-enemy countdown and nothing for a wave to keep ticking after
// it has gone.
//
// WHY A MASK AND NOT A RATE. Firing density in this game must be a property of
// CONTENT, not of population -- an encoding that gave every member a rate
// would make a four-strong wave twice as dangerous as a two-strong one for
// free, and would put four bolts in the air on the same raster when a
// formation flies as a rank. A mask says WHICH SILHOUETTES ON SCREEN ARE THE
// DANGEROUS ONES, which is a thing the player can learn, and the global
// opportunity cadence below says how often any of them gets to prove it.
//
// LEVEL 1, AND THE PACING IS DELIBERATE:
//
//     sweep   %0101   two of four, alternating along the echelon
//     s-turn  %0010   the middle one only
//     linger  %0101   two of three -- the pattern that HANGS in the middle of
//                     the screen is the one that earns the most shots
//     loop    %0000   NONE. The showpiece manoeuvre is the breathing room, and
//                     a formation that cannot shoot is the case the whole
//                     representation has to support.
.var trigFire  = List().add(%00000101, %00000010, %00000101, %00000000)

// WHERE A COLLECTIBLE TOKEN APPEARS WITH THIS WAVE — a nine-bit X, or zero for
// an appearance that brings no token.
//
// THE DIRECTOR ALREADY OWNS THE ONLY CLOCK THIS NEEDS. worldProgress and the
// trigger cursor are the level's authored progression; a token is one more
// thing an authored moment can bring, so it is a fifth COLUMN rather than a
// fifth subsystem. There is no token timer, no drop table, no rarity roll and
// no RNG anywhere in it -- the same token appears at the same X at the same
// point of every cycle, which is what makes it something a player can learn
// and a test can assert.
//
// ZERO MEANS NONE, and it is a legal X only in the sense that nothing can be
// authored at the extreme left edge of the border; the visible playfield
// starts at 24, so no real token is ever placed there.
//
// TWO OF FOUR, AND SPREAD ACROSS THE CYCLE. The deltas put trigger 1 at row 52
// and trigger 3 at row 126 of a 126-row cycle, so the tokens are 74 rows apart
// one way and 52 the other -- a token roughly every eight seconds, which is
// enough to collect several in an ordinary run without the level becoming a
// token gallery. Their lifetimes cannot overlap: a token is on screen for
// about 220 frames and the closest two authored moments are 416 apart.
//
//     trigger 1  X=220  with the S-turn, which enters at X=90: the token sits
//                       well right of the formation rather than inside it
//     trigger 3  X=150  with the loop, the one formation that does not shoot,
//                       so there is a calm pass in which to go and get it
// THE TOKEN COLUMN IS GONE, and its removal is the point of this slice. A
// token used to be authored content an appearance could bring; it is now a
// REWARD for destroying the level's one Dropper, dropped where that Dropper
// died. No trigger creates one, and no P appears merely because a wave started.
// See src/token.asm.
.const WAVE_TRIGGERS = 4
