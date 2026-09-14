// ===========================================================================
// 6502-shmup — main: boot, the once-per-frame main thread, and the fixture
// selection that still drives the qualified engine baseline.
// ===========================================================================
// PAL Commodore 64. 19,656 cycles per frame. Legal NMOS 6502/6510 only.
// KickAssembler 5.25.
//
// P0 proved: a prepared logical sprite set is displayed deterministically
// through six hardware mux slots from a complete immutable schedule.
//
// P1 proves ONE thing more:
//   that stays true while a real vertically scrolling, double-buffered
//   playfield runs underneath it — every fine-scroll phase, repeated coarse
//   steps, repeated screen-page flips, and exactly ONE sprite-pointer-table
//   destination per displayed frame, always the one $d018 is showing.
//
// Still no player, no sorter, no collision, no AI, no HUD raster split, no
// border opening. All five P0 fixtures remain independently runnable.
//
// Controls: SPACE cycles the fixture. VICE must be launched with the joystick
// devices detached or a keyset will swallow the key — see readNextFixture and
// VICE_OPTS in the Makefile. The fixture index is also pokeable at
// `fixtureIndex` so automated tests can select one without keyboard input.
// ===========================================================================

// --- VIC bank 0 memory map --------------------------------------------------
//   $0400-$07ff   screen page A          sprite pointers $07f8-$07ff
//   $0800-$0fff   THE TERRAIN CHARACTER SET, the window $d018 selects for the
//                 playfield. $0b00-$0d3f is the level's 72 terrain glyphs
//                 (codes 96..167) and $0f10-$0f2f the four static turret body
//                 glyphs (codes 226..229). Everything else in the window is
//                 zero-filled by the PRG and renders as $d021. See
//                 src/terrain.asm and src/turrets.asm.
//   $1000-$1fff   our code               VIC sees the CHARACTER ROM here, so
//                                        code living there is invisible to it.
//                                        This is the stock C64 arrangement,
//                                        not a trick.
//   $2000-$23ff   sprite bitmaps (16 x 64)
//   $2800-$2bff   screen page B          sprite pointers $2bf8-$2bff
//   $2c00-$2fff   raster executor code (moved from $1500; it outgrew the hole
//                 below the fixture tables when the aperture phases were added)
//   $3000-$31ff   free (headroom for the raster executor above)
//   $3200-$357f   HUD sprite bitmaps (14 x 64), pointers $c8-$d5
//   $3580-$35ff   player bitmaps (2 x 64), pointers $d6-$d7
//   $3600-$37ff   free
//   $3800-$3fff   BLANK character set, all zeros; also supplies the VIC idle
//                 byte at $3fff. Cleared by clearCharset, never by luck.
//   $4000-...     MAIN-THREAD CODE, outside bank 0 by design: src/player.asm
//                 at $4000 and src/scroll.asm at $4200. Neither is ever fetched
//                 by the VIC, so neither competes for the 16 KB above -- which
//                 is about to be wanted for a character set and a terrain
//                 tileset. Weapons, enemies and waves belong here too.
//                 $1a00-$1bff is free again because the scroller left it.
//   $c000-...     schedule + frame records, OUTSIDE bank 0 by design

// ---------------------------------------------------------------------------
// THE LEVEL PACKAGE'S CONSTANTS, IMPORTED FIRST.
//
// stage_config.asm emits no bytes, no segment and no program-counter change --
// it is a constants-only include, and its own generated header says it is
// "imported very early so every level-owned constant exists before the engine
// constants/code that consume them". It used to be imported from inside
// src/terrain.asm, which was early enough while terrain was the only consumer.
//
// It is not any more. APERTURE_D021 below is a RENDERER constant derived from
// the level's authored background colour, and KickAssembler resolves `.const`
// strictly in order: renderer.asm is imported before terrain.asm, so the value
// has to exist up here or the raster splits cannot name it. Honouring the
// package's own documented contract is the fix; restating 12 in a second place
// would have been the bug.
// ---------------------------------------------------------------------------
#import "level1/stage_config.asm"

.const SCREEN_A       = $0400
.const SCREEN_B       = $2800
.const PTR_A          = SCREEN_A + $3f8
.const PTR_B          = SCREEN_B + $3f8
// CB = $0800, the TERRAIN charset. It was $1000, the character ROM, for as
// long as the playfield was a diagnostic pattern drawn out of PETSCII. The
// terrain slice replaces that with the old game's authored tileset, which is
// RAM the VIC must be able to see -- and the ROM image at $1000 is exactly
// what it is not. See the charset-window note in src/terrain.asm for why
// $0800 is the slot that was free.
.const D018_A         = $12             // VM = $0400, CB = $0800 (terrain)
.const D018_B         = $a2             // VM = $2800, CB = $0800

// ---------------------------------------------------------------------------
// THE BLANK CHARACTER SET — the playfield aperture.
//
// 2 KB of zeros. Every glyph in it renders as $d021, so selecting it makes a
// display line blank whatever the screen matrix holds behind it. Two $d018
// writes per frame therefore clip the scrolling playfield at FIXED rasters:
// blank above line 55, real charset from 55, blank again from 248.
//
// That is what makes the aperture pixel-smooth. The previous technique blanked
// matrix rows 0 and 24, which fixed the coarse seam but moved the visible top
// edge to 56 + YSCROLL: the edge climbed seven pixels and then jumped back a
// whole character row at every coarse step, 6.25 times a second. With the
// charset doing the clipping, rows 0 and 24 carry ordinary terrain and the
// boundary does not move at all -- row 0 is simply revealed one pixel at a
// time from raster 55 downwards.
//
// It also supplies the VIC's IDLE byte. Outside the display window the VIC
// fetches $3fff and renders it in $d021; the vertical border is held open, so
// those lines are visible. $3fff is the last byte of this charset, so zeroing
// the charset zeroes the idle byte by construction. Power-on RAM is NOT zero
// on real hardware -- clearCharset writes it, and nothing relies on the
// emulator being kind.
//
// CB = %111 selects $3800; the real charset stays at CB = %010 ($1000, the
// character ROM the VIC sees in this bank). Only bits 3-1 of $d018 differ
// between the four values below; the VM bits still name the page.
.const BLANK_CHARSET  = $3800
.const D018_A_BLANK   = $1e             // VM = $0400, CB = $3800
.const D018_B_BLANK   = $ae             // VM = $2800, CB = $3800

.if (BLANK_CHARSET != $3800) { .error "CB = %111 is $3800 and nothing else" }
.if ((D018_A & $f0) != (D018_A_BLANK & $f0)) { .error "page A VM bits differ between charsets" }
.if ((D018_B & $f0) != (D018_B_BLANK & $f0)) { .error "page B VM bits differ between charsets" }
.if (SCREEN_B + $400 > BLANK_CHARSET) { .error "screen page B overlaps the blank charset" }
.if (BLANK_CHARSET + $800 > $4000)    { .error "blank charset leaves VIC bank 0" }

// The two fixed aperture boundaries, in rasters. Terrain is visible on
// TOP_SPLIT_LINE .. BOT_SPLIT_LINE-1 inclusive: 55..247, 193 lines.
//
// 248 rather than 247 for the bottom: the split write has to beat the line's
// first g-access at cycle 15, and line 247 is a badline when YSCROLL = 7 (the
// CPU is stalled from cycle 12) while 248 is outside the badline range 48..247
// entirely and can never be one. 55 for the top: it is the first line of the
// display window, so the boundary sits exactly where the hardware used to clip
// before the border was opened.
.const TOP_SPLIT_LINE = 55
.const BOT_SPLIT_LINE = 248

// The same two boundaries stated as the rasters the PLAYFIELD occupies, which
// is what a game system asking "is this thing fully on screen" needs. The
// split lines are where the charset CHANGES; these are the first and last
// raster that shows terrain. Derived, so the two can never drift.
.const APERTURE_TOP_RASTER = TOP_SPLIT_LINE          // 55, first terrain line
.const APERTURE_BOT_RASTER = BOT_SPLIT_LINE - 1      // 247, last terrain line

// ---------------------------------------------------------------------------
// $D021 IS APERTURE STATE, NOT BOOT STATE.
//
// The vertical border is held OPEN all frame, so nothing above raster 55 or
// below raster 247 is ever painted in $d020. Rasters 0..47 and 248..311 are
// VIC IDLE lines -- it fetches $3fff and renders it -- and rasters 48..54 are
// real matrix lines rendered through the BLANK charset. All three cases come
// out as bit pair 00, which in multicolour text mode is $d021 and nothing
// else. So the open top and bottom border are exactly "$d021, whatever it is".
//
// The terrain slice authored $d021 = 12 once, at init, because 12 is the
// level's bit-pair-00 colour -- and the open border went grey with it. There
// is no second register to separate the two: the playfield's background and
// the border's background are THE SAME BIT PAIR OF THE SAME REGISTER, and the
// only thing that can tell them apart is WHERE THE BEAM IS.
//
// So $d021 now rides the aperture, switched by the same two raster splits that
// already switch $d018, from the same frame record's phase. Two stores a
// frame, eight cycles, no main-thread involvement and no new phase.
//
//     raster  55   exTop      $d021 = APERTURE_D021   (the level's colour)
//     raster 248   exBottom   $d021 = BORDER_D021     (black)
//
// APERTURE_D021 is DERIVED from the level package rather than restated, for
// the same reason STAGE_ROWS is: a level that authors a different background
// must not be able to disagree with the raster that displays it.
.const APERTURE_D021  = TERRAIN_BACKGROUND_COLOUR
.const BORDER_D021    = 0               // the open top/bottom border. BLACK.

// $D011 without the fine scroll: DEN=1, RSEL=0, RST8=0.
// RSEL=0 (24 rows) is deliberate. Scrolling 25 matrix rows through a 24-row
// window hides the 8 pixels of scroll slack in the border. In 25-row mode the
// same slack is displayed as an idle strip, which is exactly the kind of
// meaningless artefact that makes a human distrust a manual acceptance run.
.const D011_BASE      = $10

.const COLOUR_RAM     = $d800
.const SCREEN_ROWS    = 25
.const SCREEN_COLS    = 40

// ---------------------------------------------------------------------------
// HUD_VISIBLE — the visual qualification switch.
//
// The diagnostic rows below live INSIDE the scrolling matrix, so they ride the
// fine scroll and wobble by up to 8 pixels every frame. That is harmless, and
// it is documented in reports/border-handoff-scroll-mask.md §2 — but it makes
// the screen impossible to judge by eye: a human watching for scroll hitches
// sees six horizontal bars jumping up and down and cannot separate them from
// the playfield underneath.
//
// With this false, rows 1, 2 and 20-23 render ordinary world content like every
// other row, so the aperture between the two blank guard rows contains nothing
// but scrolling terrain. Nothing else changes: hudTick is simply not called,
// regeneration stops reserving those six rows, and the HUD drawing code is
// still assembled and still correct. Set it true to get the diagnostics back.
//
// The fixture controls are untouched — SPACE, M, S and R still select, and
// fixtureIndex is still the live selection; it is just no longer printed.
// ---------------------------------------------------------------------------
.const HUD_VISIBLE    = false

// ---------------------------------------------------------------------------
// FIXTURE_KEYS — the qualification fixtures' keyboard selection.
//
// FALSE in a production build, and that is the whole of what "the fixtures are
// no longer the startup path" means mechanically. The fixtures themselves are
// NOT deleted: fixtures.asm, the P3/P4/P5 tables and `rebuild` are all still
// assembled and still reachable, because `make test` selects them the way it
// always has -- by poking `fixtureIndex` and calling `rebuild` through the
// monitor, which needs no keyboard at all.
//
// What the guard removes from the production path is the SCAN, and the scan is
// the part that matters: readNextFixture and its three siblings WRITE $dc00 to
// drive a keyboard column, and $dc00 is the register the joystick is read from.
// Leaving them in the loop would have the input system and the fixture selector
// taking turns owning the same port.
//
// Set it true for a debug build and SPACE/M/S/R work exactly as they did.

// HUD rows. With RSEL=0 rows 1..23 are always fully visible whatever the fine
// scroll is; rows 0 and 24 are the slack and may be clipped.
.const HUD_ROW_STATS  = 1
.const HUD_ROW_SCROLL = 2
// Row 22, NOT row 3. The P2 fixtures put six leader sprites at Y 60-65, which
// is exactly screen rows 1-4, and sprites are in front of characters: on the
// torture fixture the P2 readout was sitting underneath the very sprites it
// exists to describe. Rows 18-22 are below the lowest sprite any P2 fixture
// places (T6X3 reaches Y 194), so row 22 is readable on every fixture.
.const HUD_ROW_COUNT  = 2               // rows in hudRowList; hudTick draws one
                                        // per frame, round robin.
                                        //
                                        // FIVE, not six. P4 first gave the
                                        // sorter its own row. Round robin made
                                        // that free per frame -- but every HUD
                                        // row must ALSO be stamped into the back
                                        // page as it regenerates, and that cost
                                        // lands on one frame, which is the frame
                                        // that sets the worst-case preparation
                                        // span. It pushed P3's heaviest fixture
                                        // from ~68% of a frame to ~88% and made
                                        // it skip publications. The sorter's own
                                        // diagnostics moved onto the P3 row
                                        // instead, where there were spare
                                        // columns.
// Column 30: the bottom bar's text now runs to column 29 ("...M=P3 KEY"), so
// the live key-down block sits just past it.
.const FIXLINE_LEN    = 30              // columns of text on the bottom bar
.const KEY_COL        = 30

// Indirect indexed addressing REQUIRES a zero-page pointer. $fb/$fc belong to
// loadFixture; $fd/$fe are the other free pair on an unexpanded C64.
.const scrPtr         = $fd

BasicUpstart2(entry)

// Imported first so their constants resolve in KickAssembler's first parse.
// Each module owns its own segment, so import order does not affect layout.
#import "hud.asm"                       // AFTER renderer.asm, which defines
                                        // spriteByte(); BEFORE renderer.asm,
                                        // whose exHud phase uses its constants
#import "player.asm"                    // AFTER hud.asm, whose bitmap pool it
                                        // sits on top of; BEFORE renderer.asm,
                                        // whose exHud phase programs HW0/HW1
                                        // and whose ownership assertions are
                                        // written against PLAYER_SLOT_MASK
#import "weapon.asm"                    // AFTER player.asm, whose cannon offsets
                                        // and muzzle timer it uses, and after
                                        // hud.asm, whose logical heat it feeds
#import "renderer.asm"
#import "motion.asm"
#import "sorter.asm"
#import "objects.asm"                   // AFTER renderer.asm (MAX_LOGICAL) and
                                        // motion.asm, whose logical arrays are
                                        // the pool's presentation view
#import "collision.asm"                 // AFTER objects.asm (TYPE_ENEMY,
                                        // MAX_OBJECTS) and BEFORE enemy.asm,
                                        // which uses its hit/death colours:
                                        // KickAssembler resolves labels late
                                        // but constants strictly in order
#import "enemy.asm"                     // AFTER objects.asm and collision.asm
#import "clip.asm"                      // AFTER renderer.asm (CLIP_POOL_SLOTS,
                                        // MIN/MAX_SPRITE_Y, MAX_LOGICAL) and
                                        // motion.asm (logPtr). Its labels are
                                        // reached from the schedule builder,
                                        // which KickAssembler resolves late.
#import "terrain.asm"                   // BEFORE scroll.asm, which derives
                                        // STAGE_ROWS from TERRAIN_STAGE_ROWS.
                                        // Its own references the other way --
                                        // rrStageLo/Hi in the row decoder --
                                        // are LABELS, and KickAssembler
                                        // resolves those late; only constants
                                        // are strictly ordered.
#import "ebullet.asm"                   // AFTER objects.asm (TYPE_EBULLET, the
                                        // pool API) and enemy.asm (its bitmap
                                        // and tables decide where the
                                        // projectile's own 64 bytes fit);
                                        // BEFORE turrets.asm, which fires it
#import "turrets.asm"                   // AFTER terrain.asm, whose glyph
                                        // namespace, charset window, metatile
                                        // geometry and derived stage height it
                                        // is guarded against; BEFORE
                                        // scroll.asm, whose renderBackgroundRow
                                        // composes the overlay onto the row
                                        // terrain has just decoded
#import "scroll.asm"
#import "movement.asm"                  // AFTER objects.asm (MAX_OBJECTS) and
                                        // renderer.asm (the production Y band
                                        // its arc is proven against)
#import "waves.asm"                     // AFTER movement.asm (the WM_*
                                        // primitives and arc geometry its
                                        // authored content names), enemy.asm
                                        // (ENEMY_PTR, ENEMY_MAX_HP) and
                                        // scroll.asm (worldProgress, the clock
                                        // its triggers are authored against)

// OUTSIDE VIC BANK 0, with the player, the scroller, the weapon, the object
// pool, the enemy and collision. This segment was at $0810 while $0800-$0fff
// had no other claim on it; the terrain charset needs that window, and every
// byte in this file is main-thread code or main-thread data -- entry,
// mainLoop, gameFrame, gameInit and the diagnostic HUD, with no interrupt
// handler anywhere in it -- so it belongs out here and always did.
* = $5000 "main"

entry:
    sei
    lda #$0b
    sta $d011                           // screen off while we set up
    lda #$00
    sta $d020
    sta $d021
    sta $d01c                           // all sprites hires
    sta $d017                           // no Y expand
    sta $d01d                           // no X expand
    sta $d01b                           // sprites in front

    jsr clearCharset                    // MUST precede any display: it is both
                                        // the aperture mask and the idle byte
    jsr terrainInit                     // colour RAM, $d021/$d022/$d023, the
                                        // multicolour bit, and the transposed
                                        // metatile tables. Replaces initColour:
                                        // terrain owns the playfield's colour
                                        // now, and owning it in one place is
                                        // what stops the two disagreeing.
    jsr ebulletInit                     // no hostile projectiles at boot
    jsr turretInit                      // mark the authored turrets alive.
                                        // BEFORE scrollInit: that builds both
                                        // pages through renderRow, and a turret
                                        // inside the boot aperture has to be
                                        // composed into them.

    lda #0
    sta keyDown
    sta lastFrameSeen

    jsr gameInit                        // production state: no gameplay sprites,
                                        // the player at its start position, and
                                        // the first schedule published
    jsr hudInit                         // draw every HUD bitmap once
    jsr scrollInit                      // build both pages, publish frame 0
    jsr installRenderer                 // renderer owns the IRQ chain from here
    cli

// ---------------------------------------------------------------------------
// The main loop runs once per DISPLAYED frame, paced by the renderer's own
// frame counter. Order matters and is the whole of P1's frame ownership:
//
//   1. hudTick     writes the page that is on screen RIGHT NOW. dispPage still
//                  names it, because scrollTick has not run yet this frame.
//   2. regenTick   rebuilds the BACK page, which nothing is displaying.
//   3. scrollTick  advances the scroll and publishes the record the NEXT frame
//                  IRQ will adopt. Only here can dispPage change.
//
// So no main-thread write ever lands on the page the VIC is fetching, and the
// page decision is made at exactly one point per frame.
// ---------------------------------------------------------------------------
mainLoop:
    // HUD bitmap preparation lives in the SPIN, not in the once-per-frame block
    // below. That block runs immediately after the frame transaction and
    // reaches this point at around raster 10, which is inside the window where
    // the VIC fetches HUD sprite data; the spin covers the rest of the frame.
    // hudUpdate refuses to run outside its safe raster band and simply tries
    // again on the next pass, which is a fraction of a millisecond later.
    jsr hudUpdate


    lda frameCounter
    cmp lastFrameSeen
    beq mainLoop                        // same displayed frame: nothing to do

    // DID THE MAIN THREAD MISS A FRAME? The counter advances by one per
    // displayed frame, so a step of two or more means a whole frame went by
    // without the game preparing one. The picture does not break -- CURRENT is
    // still adopted and still complete -- but the game ran at half rate for a
    // frame, and that is the number a performance ladder needs. Saturating: any
    // non-zero value is a finding, and the exact count past 255 is not.
    // The low byte alone is enough for a delta of one against two or more.
    pha
    sec
    sbc lastFrameSeen
    cmp #2
    bcc !onTime+
    ldx gameOverrun
    cpx #$ff
    beq !onTime+
    inc gameOverrun
!onTime:
    pla
    sta lastFrameSeen
    jsr gameFrame
    jmp mainLoop

// ---------------------------------------------------------------------------
// gameFrame — ONE displayed frame of game, in the order the engine requires.
//
// This is the production loop, and it is deliberately shaped so the systems
// still to come have exactly one obvious place each:
//
//     input        <- here
//     player       <- here
//     weapons         Slice B
//     enemies         Slice C
//     collision       Slice D
//     waves           Slice E/G
//     HUD feed        Slice B (hudDemoTick is the placeholder it replaces)
//     ----------------------------------------------------------------
//     emit         logical state -> the renderer's inputs
//     sort / build / publish      the engine, untouched
//     regen / scroll              the engine, untouched
//
// The three engine calls at the bottom are in the order docs/ENGINE_CONTRACT.md
// §1 fixes and the order src/main.asm's frame-ownership note explains: hudTick
// writes the page that is on screen RIGHT NOW, regenTick rebuilds the page
// nothing is displaying, and scrollTick is the only thing that may change which
// page that is. Nothing above them touches a page at all.
// ---------------------------------------------------------------------------
gameFrame:
    // FIRST, AND THE POSITION IS THE WHOLE POINT.
    //
    // The main loop is paced by the frame counter, which the renderer
    // increments in exFrame at raster 250 -- so this instruction runs in the
    // LOWER BORDER, below the playfield, with the entire next picture's matrix
    // fetch still ahead of it. Every row of both screen pages can be written
    // freely here and nowhere later is that unconditionally true: by
    // collisionTick the beam is forty to eighty lines further on, and how much
    // further moves with the frame's load.
    //
    // So a destroyed turret FLAGS itself when the hitscan resolves and its
    // characters are repaired here, at most one frame later. On an ordinary
    // frame this costs one load and one branch.
    jsr turretRestoreTick

.if (HUD_VISIBLE) {
    jsr hudTick                         // the displayed page, before scrollTick
}                                       // can change which page that is

    jsr readInput                       // $dc00 -> joyState
    jsr playerTick                      // joyState -> plyX / plyXHi / plyY
    jsr weaponTick                      // cadence, heat, overheat, shot event
    jsr weaponHudFeed                   // real heat -> the HUD's logical heat

    // AFTER weaponTick, and that ordering is the muzzle flash. weaponTick sets
    // plyMuzzle when a volley resolves and playerEmit turns it into a pointer
    // and a colour, so a shot fired this frame is published this frame rather
    // than one frame late.
    jsr playerEmit                      // -> plyPres, and plyDirty if it changed

    // ---- the logical object pool -----------------------------------------
    // Every active object moves, and may remove itself. objectUpdateAll runs
    // BEFORE enemySpawnTick so that an enemy spawned this frame is rendered at
    // exactly its spawn position for one frame rather than being moved before
    // it has ever been seen.
    //
    // Neither call knows that hardware sprites exist. They write logY/logX/
    // logXHi/logPtr/logCol -- the presentation view -- and membership; the
    // sorter and the builder below decide the rest.
    jsr objectUpdateAll

    // ---- the player's hitscan --------------------------------------------
    // THE TEMPORAL MODEL, AND IT IS A DECISION RATHER THAN A CALL ORDER.
    //
    // Collision runs AFTER all movement, so the rays and their targets are
    // both END-OF-FRAME state for the SAME frame. playerTick moved the ship,
    // weaponTick built the ray origins from that new position, and
    // objectUpdateAll has just moved every enemy. Nothing here compares a
    // this-frame coordinate against a last-frame one in either direction.
    //
    // Running it BEFORE objectUpdateAll would have been equally consistent,
    // and worse: an enemy would be tested where it was when the trigger was
    // pulled and drawn a pixel or two further on, which is the kind of
    // one-frame disagreement that is invisible in a test and infuriating in
    // play.
    //
    // One visible consequence, named so it is not mistaken for a bug: an enemy
    // that left the world this frame was already freed above, so a shot fired
    // on that frame misses it.
    // The turrets' world -> screen derivation, and it belongs HERE: after all
    // movement and before the hitscan, which is exactly where the old game put
    // positionBackgroundTurrets. scrollTick runs at the END of this routine, so
    // stageTopRow and scrollFine still describe the picture on screen.
    jsr turretWorldTick

    jsr collisionTick

    // ...and the projectiles already in the air meet the ship. Same temporal
    // model as collisionTick: everything has moved, so the bolt and the hull
    // are both end-of-frame state for the same frame. A load and a branch
    // unless something is actually in flight.
    jsr ebulletPlayerTick

    // AFTER collisionTick, so a hit lands its flash on the same frame the shot
    // resolved. Colour RAM only -- the VIC latches a row's colour once per
    // badline and holds it for the whole character, so a mid-frame write is a
    // one-frame granularity rather than a tear. The destroyed body's
    // CHARACTERS are a different matter and wait for turretRestoreTick above.
    jsr turretPaintTick

    // The turrets shoot back. AFTER collisionTick, so a turret the player just
    // destroyed does not also fire; beside enemySpawnTick, so a projectile
    // born this frame is drawn where it was launched rather than moved first.
    // Five cycles unless a turret is actually on the aperture.
    jsr turretFireTick

    // THE ENCOUNTER DIRECTOR, and it sits exactly where the spawner it
    // replaces did: after every object has moved and after the hitscan, so an
    // enemy created this frame is drawn where it was created rather than moved
    // before it has ever been seen. One sixteen-bit compare against the next
    // authored trigger plus a walk of two wave instances, whatever the stage
    // is doing.
    jsr waveTick

    jsr hudDemoTick                     // score, lives and upgrade only: their
                                        // systems do not exist yet. Heat left
                                        // this routine in Slice B and is fed
                                        // above from the real weapon.

    // ---- rebuild and publish, but only when something changed ------------
    //
    // A frame in which neither the player nor a fixture moved has an identical
    // schedule to the one already adopted, so building it again would be a few
    // thousand cycles spent reproducing the bytes CURRENT already holds. The
    // executor keeps reading that immutable copy, and exHud keeps programming
    // HW0/HW1 from it, so the picture is unchanged -- including across a page
    // flip, because the pointer destination is patched per frame by exFrame and
    // not baked into the schedule.
    //
    // This is also what keeps the STATIC regression fixtures costing what they
    // have always cost: MAXCAP is thirty logical sprites and rebuilding it
    // every frame is a measurable load that P4 specifically measured skips
    // against. With no joystick attached the player never moves, so a fixture
    // run is byte-for-byte the frame it always was.
    // WHAT MAKES THE SCHEDULE STALE, all four sources.
    //
    //   plyDirty     the player's published block changed
    //   logCount     at least one object is alive, and every object moves
    //   sortDirty    membership changed THIS frame
    //
    // sortDirty is not redundant with logCount: the frame on which the LAST
    // enemy despawns leaves logCount zero, and that is precisely the frame
    // whose schedule must be rebuilt to stop drawing it. Dropping that term
    // would leave the final enemy of every group frozen on screen until the
    // player next moved.
    lda plyDirty
    ora logCount
    ora sortDirty
    beq !noPublish+
    lda #0
    sta plyDirty
    jsr sortTick                        // order by Y BEFORE admission
    jsr buildSchedule                   // complete NEXT, player block included
    jsr publishSchedule                 // one byte
!noPublish:

    jsr regenTick
    jsr scrollTick
    // fall through to the span measurement

// ---------------------------------------------------------------------------
// gameSpan — how far into the frame the main thread finished, in raster lines
// measured from the frame transaction at raster 250.
//
// This is the headroom number the performance ladder is built on, and it is
// stated as an elapsed span rather than a raw raster because the game frame
// STRADDLES the frame boundary: it starts just after raster 250 and finishes
// somewhere in the low rasters of the next displayed frame, so a bare $d012
// reading counts backwards.
//
//     raster 250..255  ->  elapsed 0..5      (RST8 clear, $d012 >= 250)
//     raster 256..311  ->  elapsed 6..61     (RST8 set)
//     raster 0..193    ->  elapsed 62..255   (RST8 clear)
//     raster 194..249  ->  elapsed > 255     saturate, and COUNT it
//
// $d012 IS THE LOW BYTE OF A NINE-BIT COUNTER and bit 7 of a $d011 READ is the
// ninth. Reading the low byte alone would call raster 260 "4" and score a frame
// that finished comfortably as one that finished before it started; hudUpdate's
// own wrap check was written twice for exactly that reason.
// ---------------------------------------------------------------------------
gameSpan:
    lda $d011
    and #$80
    bne !high+
    lda $d012
    cmp #250
    bcs !justAfter+                     // 250..255: barely started
    cmp #194
    bcs !over+                          // 194..249: past a whole frame's worth
    clc
    adc #62
    jmp !store+
!justAfter:
    sec
    sbc #250
    jmp !store+
!high:
    lda $d012
    clc
    adc #6
!store:
    cmp gameSpanMax
    bcc !done+
    sta gameSpanMax
!done:
    rts
!over:
    lda #$ff
    sta gameSpanMax                     // saturating, like every fault counter
    lda gameSpanOver                    // here: the value is a floor, not a
    cmp #$ff                            // measurement, and the count says so
    beq !done-
    inc gameSpanOver
    rts

// ---------------------------------------------------------------------------
// gameInit — the production starting state, before the renderer owns the IRQ.
//
// NO GAMEPLAY SPRITES. logCount is zero, so the sorter has nothing to order,
// the builder accepts nothing, schedBatches is zero and the handoff takes its
// no-batches path. The player is not in that pool and never will be, so it
// displays perfectly well through a frame in which the mux does nothing at all
// -- which, until enemies arrive, is every frame.
// ---------------------------------------------------------------------------
gameInit:
    jsr objectInit                      // every pool slot free, logCount zero,
                                        // and the sorter told that membership
                                        // changed
    jsr sortReset                       // sortedIDs must be a permutation of
                                        // 0..MAX_LOGICAL-1 whose active prefix
                                        // is empty
    jsr playerInit
    jsr weaponInit
    jsr collisionInit
    jsr enemyInit
    jsr clipInit                        // no sprite clipped, no scratch taken
    jsr waveInit                        // no wave running, the first authored
                                        // trigger one delta of worldProgress
                                        // away. AFTER objectInit, whose empty
                                        // pool it assumes
    jsr playerEmit
    jsr sortTick
    jsr buildSchedule
    jsr publishSchedule
    lda #0
    sta plyDirty                        // the build above IS the first
    sta gameSpanMax                     // publication; nothing is outstanding
    sta gameSpanOver
    sta gameOverrun
    rts

// ---------------------------------------------------------------------------
// Colour RAM is written ONCE and never again.
//
// There is only one colour RAM and it cannot be double buffered, so anything
// that changed it per coarse step would tear across a page flip with no way to
// publish it atomically. Keeping it fixed removes that problem entirely: the
// characters scroll through a stationary colour field.
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// clearCharset — 2 KB of zeros at $3800, written once.
//
// Done at run time rather than as a .fill segment on purpose: a segment would
// put 2 KB of zeros in the PRG and, worse, force KickAssembler to emit the
// whole $2800-$37ff gap with it, zeroing screen page B at load for no reason.
// A twenty-byte loop states the intent and cannot be confused with data.
// ---------------------------------------------------------------------------
clearCharset:
    lda #0
    ldx #0
!fill:
    sta BLANK_CHARSET + $000,x
    sta BLANK_CHARSET + $100,x
    sta BLANK_CHARSET + $200,x
    sta BLANK_CHARSET + $300,x
    sta BLANK_CHARSET + $400,x
    sta BLANK_CHARSET + $500,x
    sta BLANK_CHARSET + $600,x
    sta BLANK_CHARSET + $700,x          // $3fff, the idle byte, is in here
    inx
    bne !fill-
    rts

initColour:
    ldx #0
!bg:
    lda #$0f                            // light grey playfield
    sta COLOUR_RAM,x
    sta COLOUR_RAM + $100,x
    sta COLOUR_RAM + $200,x
    sta COLOUR_RAM + $2e8,x
    inx
    bne !bg-

.if (HUD_VISIBLE) {
    // Six white rows across an otherwise uniform light-grey field. With the HUD
    // off they must NOT be written: a white band sitting still while grey
    // terrain scrolls through it is the same visual contamination the row
    // content was removed to get rid of.
    ldx #0
!hud:
    lda #$01                            // white HUD rows
    sta COLOUR_RAM + (HUD_ROW_STATS * 40),x
    sta COLOUR_RAM + (HUD_ROW_SCROLL * 40),x
    inx
    cpx #40
    bne !hud-
}
    rts

// ===========================================================================
// HUD — three fixed screen rows, drawn into whichever page the caller names.
// One code path, used both for the live update on the displayed page and for
// stamping a back page as it is rebuilt.
//
// The HUD sits INSIDE the scrolling matrix, so it rides the fine scroll and
// wobbles by up to 8 pixels. Holding it still needs a mid-screen $d011 write,
// which is a raster split — that is P8, and P1 deliberately does not have one.
// ===========================================================================
// ONE row per frame, round robin, not all five.
//
// P3 measured this. Drawing all five diagnostic rows every frame cost enough
// main-thread time that the integrated moving fixture's per-frame preparation
// reached 74.6% of a PAL frame, and passes began straddling the frame
// boundary: publishFrame then found the previous record still unadopted and
// counted a publication skip, which a human sees as a one-frame scroll
// stutter. 70 skips in 20,000 frames -- rare, real, and entirely avoidable.
//
// The HUD is a diagnostic surface, not gameplay. Every row still updates ten
// times a second, which is faster than a human reads, and the cost drops to a
// fifth. Nothing else about the frame changes: the row content, the page it is
// written to, and the stamping of HUD rows into a regenerating back page are
// all exactly as before.
hudTick:
    lda dispPage
    bne !pageB+
    lda #>SCREEN_A
    jmp !go+
!pageB:
    lda #>SCREEN_B
!go:
    sta hudPageHi

    ldx hudCursor
    lda hudRowList,x
    tax
    jsr hudRowAt

    inc hudCursor
    lda hudCursor
    cmp #HUD_ROW_COUNT
    bcc !wrapped+
    lda #0
    sta hudCursor
!wrapped:
    rts

hudRowList:  .byte HUD_ROW_STATS, HUD_ROW_SCROLL
hudCursor:   .byte 0

// X = screen row. Points scrPtr at that row of the hudPageHi page, then draws.
hudRowAt:
    lda rowLo,x
    sta scrPtr
    lda rowHi,x
    clc
    adc hudPageHi
    sta scrPtr + 1
    // fall through

// X = screen row, scrPtr = start of that row. Called from renderRow too.
// Five HUD rows now, and the row bodies between them are long, so every arm
// of this dispatch is an absolute jump rather than a relative branch. Written
// once in this shape instead of discovering the range limit one row at a time.
drawHudRow:
    cpx #HUD_ROW_STATS
    bne !notStats+
    jmp drawStatsRow
!notStats:
    jmp drawScrollRow

// "FIX nn  ACC nn  REU nn  MRG nn  UNS nn"
drawStatsRow:
    ldy #0
!label:
    lda labelText,y
    beq !values+
    sta (scrPtr),y
    iny
    jmp !label-
!values:
    lda statAccepted
    ldy #4
    jsr putHexY
    lda statReuse
    ldy #12
    jsr putHexY
    lda statRejMargin
    ldy #20
    jsr putHexY
    lda statRejUnsafe
    ldy #28
    jsr putHexY
    rts

// "SCR f  ROW rrrr  PG A  CRS cccc" — the scroller stated on screen, so a
// human can read fine phase, STAGE row, displayed page and coarse-step count
// without a monitor. The stage row counts DOWN as play advances; worldProgress
// is the counter that counts up, and CRS tracks it exactly.
drawScrollRow:
    ldy #0
!template:
    lda scrollLabelText,y
    sta (scrPtr),y
    iny
    cpy #40
    bne !template-

    lda scrollFine
    clc
    adc #$30
    ldy #4
    sta (scrPtr),y

    lda stageTopRowHi
    ldy #11
    jsr putHexY
    lda stageTopRowLo
    ldy #13
    jsr putHexY

    lda dispPage
    clc
    adc #1                              // screen code 1 = 'A', 2 = 'B'
    ldy #20
    sta (scrPtr),y

    lda coarseCount + 1
    ldy #27
    jsr putHexY
    lda coarseCount
    ldy #29
    jsr putHexY
    rts

// "MOV n  MFRM nnnn  OVF nn  SRT nn  FLT nn" — what P3 and P4 added, on ONE
// row, and nothing that is already on another.
//
// MOV  1 when this fixture has trajectories, so the main loop is re-running
//      motion and rebuilding the whole schedule every frame. 0 is a static
//      P0/P1/P2 fixture, untouched between fixture changes.
// MFRM frames of MOTION, which is what a trajectory is indexed by. On a moving
//      fixture it must advance continuously; if it stops while the playfield
//      keeps scrolling, the main thread has stopped preparing frames.
// OVF  logical sprites that did not fit MAX_SCHED. Must read 00 on every
//      fixture except MAXCAP, which exists to make it read 06.
// SRT  sorted count -- how many logical IDs the sorter handed the builder.
//      Must equal LOG on row 22: P4 has no visibility filtering, so every
//      logical sprite is offered.
// FLT  sorter fault, saturating. Must ALWAYS read 00.
//
// BOV (batch overflow) was dropped from the display to make room. It is
// structurally unreachable while MAX_SCHED is 24 -- batch 0 holds six, so at
// most nineteen batches can exist -- and every suite asserts it is zero. The
// sorter's shift counter sortWork is likewise a timing diagnostic the tests
// read directly rather than something a human watches.
// "RING ORB nnnn  UP nnnn  DN nnnn  FEL nn" — the P5 orbit census.
//
// ORB counts completed orbits: the phase accumulator's high byte wrapping
// through zero. On a ring fixture it must climb steadily; if it stops while the
// scroller keeps moving, motion has died and everything below it is measuring
// a still picture.
//
// UP and DN count logical X crossings of 255 in each direction, counted by the
// ENGINE rather than predicted by the model. They must both climb, and on a
// closed orbit they must stay within one of each other -- every sprite that
// goes out must come back. A model can believe X crossed 255; this is the
// machine saying it did.
//
// FEL is frameEntryLine, and it is the one number on this screen that must
// never change. The frame transaction is armed for raster 250 and must execute
// there; $FA is correct and anything else means the handler was re-entered
// mid-display, which is the FIX 16 fault. A human can watch this single field
// and know the invariant still holds.
// A = value, Y = column. Writes two hex digits at (scrPtr),y and y+1.
putHexY:
    pha
    lsr
    lsr
    lsr
    lsr
    tax
    lda hexDigit,x
    sta (scrPtr),y
    iny
    pla
    and #$0f
    tax
    lda hexDigit,x
    sta (scrPtr),y
    rts

hexDigit:  .byte $30,$31,$32,$33,$34,$35,$36,$37,$38,$39,$01,$02,$03,$04,$05,$06

// --- screen-code text -------------------------------------------------------
// Five 8-column fields: label in cols 0..2, value in cols 4..5 of each field,
// so a value can never overwrite a label.
// FIX = fixture, ACC = accepted, REU = reuse events,
// MRG = rejected inside our safety margin, UNS = rejected as physically unsafe.
labelText: .byte   1,  3,  3, 32, 32, 32, 32, 32                    // "ACC     "
           .byte  18,  5, 21, 32, 32, 32, 32, 32                    // "REU     "
           .byte  13, 18,  7, 32, 32, 32, 32, 32                    // "MRG     "
           .byte  21, 14, 19, 32, 32, 32, 32, 32, 0                 // "UNS     "

// "SCR    ROW       PG    CRS" with gaps for the values, exactly 40 columns.
// value columns: 4 = fine, 11..14 = world row, 20 = page, 27..30 = coarse
scrollLabelText:
           .byte  19,  3, 18, 32, 32, 32, 32                        // "SCR    "  0..6
           .byte  18, 15, 23, 32                                    // "ROW "     7..10
           .byte  32, 32, 32, 32, 32, 32                            //            11..16
           .byte  16,  7, 32                                        // "PG "      17..19
           .byte  32, 32, 32                                        //            20..22
           .byte   3, 18, 19, 32                                    // "CRS "     23..26
           .byte  32, 32, 32, 32                                    //            27..30
           .byte  32, 32, 32, 32, 32, 32, 32, 32, 32                //            31..39

// "FIXTURE n  SPACE = NEXT   KEY" — column 8 is the digit and column KEY_COL
// (29) is the live key-down block, so neither is in this string.
// "FIXTURE nn  SPACE=NEXT  M=P3  KEY #". Two digits now: there are 24 fixtures.
keyDown:       .byte 0
lastFrameSeen: .byte 0

// --- production frame diagnostics -------------------------------------------
// Read by tests/test_slice_a.py; never read by the engine. Min/max and
// saturating counts, in the style the rest of the engine already uses, because
// a wrapping counter can read zero after a long run and look clean.
gameSpanMax:   .byte 0                  // worst main-thread span, raster lines
                                        // after the frame transaction
gameSpanOver:  .byte 0                  // frames whose span exceeded 255 lines:
                                        // the span above is then a floor
gameOverrun:   .byte 0                  // displayed frames the main thread did
                                        // not prepare a frame for. MUST read 0.
