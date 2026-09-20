"""Engine ↔ Editor Contract v2 — the numbers, verified against engine source.

EVERY CONSTANT HERE WAS READ OUT OF `src/` AND THE SOURCE IS NAMED BESIDE IT.
That is the whole point of the file: the editor's previous engine_data.py drifted
badly from the engine (it still believed terrain was assembled into the engine PRG
at $6600-$8800, and that 255 turrets were streamed through a pool of 8), and the
drift was invisible because nothing said where a number had come from.

So: one module, no Tkinter, no I/O, no project knowledge. If a limit changes in the
engine it changes in exactly one place here, and the citation says where to look.

See /reports/level-editor-contract-v2-specification.md for the full audit.
"""

# ---------------------------------------------------------------------------
# Terrain geometry — src/terrain.asm, src/main.asm
# ---------------------------------------------------------------------------
METATILE_W = 4                  # src/terrain.asm  METATILE_W
METATILE_H = 4                  # src/terrain.asm  METATILE_H
METATILES_PER_ROW = 10          # src/terrain.asm  METATILES_PER_ROW
SCREEN_COLS = 40                # src/main.asm     SCREEN_COLS
SCREEN_ROWS = 25                # src/main.asm     SCREEN_ROWS

# ---------------------------------------------------------------------------
# The level package — src/levelpkg.asm
# ---------------------------------------------------------------------------
LEVELPKG_BASE = 0xE000
LEVELPKG_TOP = 0xFFF9
LEVELPKG_MAP_MAX = 4400         # 440 rows * 10
LEVELPKG_DEFS_MAX = 1024        # 64 defs * 16
LEVELPKG_MOVE_MAX = 256         # wmStage is ONE BYTE -- the hardware ceiling
LEVELPKG_WAVEDEF_SLOTS = 26     # waveDefBase forms def*10 in one byte
LEVELPKG_TRIG_SLOTS = 180       # floor(1082 / 6 columns)
LEVELPKG_TRIG_COLS = 6

# Stage height. The binding limit is the map budget, not the turret tables
# (src/turrets.asm allows 512 metatile rows / 2047 logical).
MAX_METATILE_ROWS = LEVELPKG_MAP_MAX // METATILES_PER_ROW          # 440
# src/scroll.asm: `.if (STAGE_ROWS < SCREEN_ROWS + 1) .error` -> 26 logical rows.
MIN_METATILE_ROWS = -(-(SCREEN_ROWS + 1) // METATILE_H)            # ceil(26/4) = 7

MAX_METATILE_DEFS = LEVELPKG_DEFS_MAX // 16                        # 64
METATILE_DEF_CELLS = METATILE_W * METATILE_H                       # 16

# ---------------------------------------------------------------------------
# Glyphs — src/terrain.asm, src/turrets.asm
# ---------------------------------------------------------------------------
TERRAIN_GLYPH_BASE = 96         # src/terrain.asm  TERRAIN_GLYPH_BASE
TURRET_GLYPH_BASE = 226         # src/turrets.asm  TURRET_GLYPH_BASE
GLYPH_BYTES = 8
# THE BINDING CEILING IS THE TURRET GLYPHS, NOT THE CHARACTER SET. The namespace
# guard in terrain.asm only says base+count <= 256 (160), but turrets.asm asserts
# `TURRET_GLYPH_BASE < TERRAIN_GLYPH_BASE + TERRAIN_GLYPH_COUNT` is an error --
# so terrain may not reach code 226.
MAX_TERRAIN_GLYPHS = TURRET_GLYPH_BASE - TERRAIN_GLYPH_BASE        # 130

# ---------------------------------------------------------------------------
# Colour — src/terrain.asm
# ---------------------------------------------------------------------------
# TERRAIN_COLOUR_RAM = 8 | TERRAIN_CHARACTER_COLOUR forces the multicolour bit,
# so only the low three bits of the character colour survive: 8..15 alias 0..7.
MAX_COLOUR = 15
MAX_CHARACTER_COLOUR = 7

# ---------------------------------------------------------------------------
# Turrets — src/turrets.asm
# ---------------------------------------------------------------------------
# *** CONTRACT v2 TEMPORARY LIMITS ***  Both are scheduled to be lifted.
#   trtDeadPending is ONE BYTE, one bit per turret:
#       `.if (TURRET_TOTAL > 8) .error "trtDeadPending is one bit a turret"`
#   turretAtMetaRow stores ONE index per metatile row:
#       `.error "two authored turrets share a metatile row"`
MAX_TURRETS = 8
TURRETS_PER_METATILE_ROW = 1
TURRET_ROW_PHASE = 1            # authored rows are 1 (mod METATILE_H)
TURRET_BODY_W = 2               # characters
TURRET_BODY_H = 2

# ---------------------------------------------------------------------------
# Movement records — src/movement_format.asm
# ---------------------------------------------------------------------------
WM_STAGE_SIZE = 4
WM_STRAIGHT = 0
WM_ARC = 1                      # clockwise
WM_ARC_MIRROR = 2               # anticlockwise
WM_EXIT = 3
WM_HOLD = 4
WM_HEAD_LEN = 64                # headings 0..63, clockwise from EAST, +y down
WM_HEAD_CONT = 0xFF             # "continue from the heading already held"

MOVEMENT_KINDS = {
    "STRAIGHT": WM_STRAIGHT,
    "ARC": WM_ARC,
    "ARC_MIRROR": WM_ARC_MIRROR,
    "EXIT": WM_EXIT,
    "HOLD": WM_HOLD,
}
ARC_KINDS = ("ARC", "ARC_MIRROR")
TIMED_KINDS = ("STRAIGHT", "HOLD")

MAX_MOVEMENT_RECORDS = LEVELPKG_MOVE_MAX // WM_STAGE_SIZE          # 64

# src/enemy.asm ENEMY_CLEAR_X_LEFT = 4. src/waves.asm rejects a straight/hold leg
# whose |vx| exceeds ENEMY_CLEAR_X_LEFT * 4, because the once-a-frame wrap guard
# would be stepped over.
ENEMY_CLEAR_X_LEFT = 4
MAX_ABS_VX = ENEMY_CLEAR_X_LEFT * WM_STAGE_SIZE                    # 16

# ---------------------------------------------------------------------------
# Wave definitions — src/wave_encounters.asm, src/waves.asm
# ---------------------------------------------------------------------------
WAVEDEF_SIZE = 10
MAX_WAVE_DEFINITIONS = LEVELPKG_WAVEDEF_SLOTS                      # 26
MAX_SPAWN_X = 511               # nine-bit X world
MAX_SPAWN_Y = 255               # logY is eight bits
# WAVE_SLOTS = 2 concurrent instances (src/waves.asm). Not a hard authoring limit
# -- a third simultaneous trigger is DROPPED and counted -- so it warns.
WAVE_SLOTS = 2

# ---------------------------------------------------------------------------
# Where a wave member may be born — src/waves.asm's spawn proof
# ---------------------------------------------------------------------------
# A MEMBER MUST BE ENTIRELY OUT OF SIGHT WHEN IT IS CREATED, or it pops into
# existence inside the playfield. src/waves.asm states it as three alternatives
# and errors if none holds:
#
#     hiddenAbove = (y0 + SPRITE_HEIGHT - 1) < APERTURE_TOP_RASTER
#     hiddenLeft  = (x0 + 23) < 24
#     hiddenRight = x0 > 343
#
# The sprite covers x0..x0+23 and y0..y0+20; the visible playfield is columns
# 24..343 of rasters 55..247. The 23 and the 24 are literals in waves.asm rather
# than named constants, so they are named here rather than re-derived.
#
# THERE IS NO "HIDDEN BELOW". A member born beneath the aperture would never
# enter it -- the playfield scrolls down past the player, enemies arrive from
# above or through a side -- so the engine does not offer that escape and
# neither does this.
SPRITE_HEIGHT = 21                  # src/renderer.asm
APERTURE_TOP_RASTER = 55            # src/main.asm TOP_SPLIT_LINE
SPRITE_LAST_COLUMN = 23             # a sprite covers x0..x0+23
DISPLAY_X_FIRST = 24                # first visible column
DISPLAY_X_LAST = 343                # last visible column


def spawn_hiding(x0, y0):
    """(hidden_above, hidden_left, hidden_right) for a member born at (x0, y0).

    Mirrors src/waves.asm exactly. A member is legal when ANY of the three is
    true; `any(spawn_hiding(x, y))` is the whole contract.
    """
    return (
        (y0 + SPRITE_HEIGHT - 1) < APERTURE_TOP_RASTER,
        (x0 + SPRITE_LAST_COLUMN) < DISPLAY_X_FIRST,
        x0 > DISPLAY_X_LAST,
    )


def spawn_is_hidden(x0, y0):
    return any(spawn_hiding(x0, y0))


# ---------------------------------------------------------------------------
# Species and sides — src/encounter_format.asm
# ---------------------------------------------------------------------------
# A SPECIES VALUE IS ITS ANIMATION ROW OFFSET, NOT AN INDEX (frame lookup is
# `species ORA step`), so validation is by MEMBERSHIP and never by range.
ENEMY_ANIM_STEPS = 8
SPECIES = {
    "RING": 0 * ENEMY_ANIM_STEPS,       # 0
    "DROPPER": 1 * ENEMY_ANIM_STEPS,    # 8
}
DROPPER_SIDES = {"LEFT": 0, "RIGHT": 1}

# ---------------------------------------------------------------------------
# Triggers and the boss approach — src/waves.asm, src/levelpkg.asm
# ---------------------------------------------------------------------------
MAX_TRIGGERS = LEVELPKG_TRIG_SLOTS                                 # 180
MAX_WORLD_PROGRESS = 0xFFFF     # the row is two bytes, compared 16-bit

# The quiet zone the authored level 1 uses, and the default this editor offers.
# 55 is DERIVED: the longest authored wave footprint in level 1 is 48 coarse rows,
# and the zone must exceed the worst footprint or a wave started on the last legal
# row could still be on screen when the stage ends. tools/gen_proof420.py scales
# the same rule as `stage_end - 55`.
DEFAULT_QUIET_ZONE_ROWS = 55

# ---------------------------------------------------------------------------
# Scroll and timing — src/scroll.asm
# ---------------------------------------------------------------------------
# 1 px/frame unconditionally (gameFrame calls scrollTick once, which does
# `inc scrollFine`), and a coarse row every 8 pixels. SCROLL_FRAME_DIVIDER is NOT
# here: it was generated into stage_config.asm and read by nothing in the engine.
FRAMES_PER_COARSE_ROW = METATILE_H * 2      # 8 pixels per logical row
PAL_FPS = 50


# ---------------------------------------------------------------------------
# Derived stage geometry. Derived, never stored -- see the report's rule that a
# fact lives in exactly one place.
# ---------------------------------------------------------------------------
def logical_rows(metatile_rows):
    """Logical character rows in the authored map."""
    return metatile_rows * METATILE_H


def playable_progress(metatile_rows):
    """STAGE_FINAL_VIEW_PROGRESS: the last worldProgress the stage reaches.

    src/scroll.asm: STAGE_START_ROW = STAGE_ROWS - SCREEN_ROWS, and
    STAGE_FINAL_VIEW_PROGRESS = STAGE_START_ROW. The final screenful is already
    on display when the stage ends, which is why the viewport is subtracted.
    """
    return logical_rows(metatile_rows) - SCREEN_ROWS


def playable_frames(metatile_rows):
    return playable_progress(metatile_rows) * FRAMES_PER_COARSE_ROW


def terrain_seconds(metatile_rows):
    return playable_frames(metatile_rows) / PAL_FPS


def turret_world_row(metatile_row):
    """src/turrets.asm: authored rows are metatileRow * METATILE_H + 1."""
    return metatile_row * METATILE_H + TURRET_ROW_PHASE


def turret_world_col(metatile_col):
    return metatile_col * METATILE_W + TURRET_ROW_PHASE


def default_no_spawn_row(metatile_rows):
    """The quiet zone this editor offers for a stage of this height.

    A SHORT STAGE CANNOT AFFORD 55 ROWS, and the engine's rules are strict:
    1 <= noSpawnRow <= playableProgress, and every trigger must be strictly
    below it. `playable - 55` goes non-positive at 84 metatile rows and negative
    below that, so the fallback is deterministic rather than clamped by accident:

        prefer   playable - DEFAULT_QUIET_ZONE_ROWS
        else     the midpoint, max(1, playable // 2)

    The midpoint keeps a real zone on any legal stage (playable >= 3 at the
    7-row minimum) and is a pure function of the height, so migrating the same
    project twice cannot produce two different levels.
    """
    playable = playable_progress(metatile_rows)
    preferred = playable - DEFAULT_QUIET_ZONE_ROWS
    if preferred >= 1:
        return preferred
    return max(1, playable // 2)
