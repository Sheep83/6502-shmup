import sys
from pathlib import Path
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
# THE SLOT COUNT FOLLOWS THE COLUMN COUNT, exactly as src/levelpkg.asm derives
# it: floor(the encounter reservation left over / the number of columns). The
# seventh and eighth columns -- this appearance's colour and its firing mode --
# took the ceiling from 180 to 135, which is still more than ten times the
# longest authored level.
LEVELPKG_TRIG_COLS = 8
LEVELPKG_TRIG_SLOTS = 1082 // LEVELPKG_TRIG_COLS                   # 135

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
    "SQUARE": 2 * ENEMY_ANIM_STEPS,     # 16
}
# Human-facing labels. The editor shows these; the package carries SPECIES.
SPECIES_LABELS = {"RING": "Ring", "DROPPER": "Dropper", "SQUARE": "Square"}
DROPPER_SIDES = {"LEFT": 0, "RIGHT": 1}

# --- how an APPEARANCE attacks, src/encounter_format.asm --------------------
# A TRIGGER FIELD, NOT A DEFINITION FIELD, for the same reason the colour is
# one. The same reusable `sweep` should be able to arrive silent at one row,
# firing straight down at another and aimed at a third without being cloned.
#
# DOWN is what every wave did before aimed fire existed and is the default, so
# no authored level changes meaning by being loaded. AIMED samples the ship's
# position at the instant of firing and never looks again -- the shot can be
# dodged.
#
# "NO FIRING" IS NOT A MODE HERE. It is an empty fireMask, which is how it has
# always been said and is still the only way to say it: the mask decides WHICH
# members shoot, the species decides whether it CAN, and this decides HOW.
FIRE_MODES = {"DOWN": 0, "AIMED": 1}
FIRE_MODE_LABELS = {"DOWN": "Straight down", "AIMED": "Aimed at player"}

# --- how an APPEARANCE is coloured, src/encounter_format.asm -----------------
# A TRIGGER FIELD, NOT A DEFINITION FIELD. A wave definition is reusable
# formation vocabulary -- how many enemies, how far apart, along which path --
# and the same `sweep` must be usable cyan at one row, yellow at another and
# mixed at a third without being cloned. Colour is a property of the OCCURRENCE,
# so it sits on the trigger beside the species and the fire mask, which are
# occurrence properties for exactly the same reason.
#
# FIXED: every member of that appearance wears the trigger's `colour`.
# RANDOM: each enemy picks its own eligible colour once, as it spawns, from the
# colours the resident level leaves safe -- everything except black, the two
# shared sprite multicolours ($d025/$d026) and the terrain's charset colour. The
# player's colour is deliberately still eligible.
#
# ONE BYTE IN THE PACKAGE: bits 0-3 the colour, bit 4 the random flag. The
# colour is kept in both modes, so switching a trigger to random and back
# returns the colour the author chose.
COLOUR_MODES = {"FIXED": 0, "RANDOM": 1}
COLOUR_MODE_LABELS = {"FIXED": "Fixed colour",
                      "RANDOM": "Random per enemy"}
TRIG_COL_MASK = 0x0F
TRIG_COL_RANDOM = 0x10

# The colour a trigger gets when nothing says otherwise -- an older project
# whose wave definition named no colour either. 1 is WaveDefinition's own
# historical default.
DEFAULT_TRIGGER_COLOUR = 1

# THE ENEMY SPRITE WINDOW, and the slot every level's species are loaded into.
#
# A slot is a block index counted from the start of the engine's enemy sprite
# window (src/main.asm defines where the window is; src/level_assets.asm loads
# into it). Each species occupies ENEMY_FRAMES consecutive blocks, so the
# default packing is simply "species in order, four blocks each" -- which is
# what src/level1/stage_enemies.asm has always said by hand.
#
# These live here because a level package is not buildable without them and a
# freshly exported level directory has no hand-authored file to inherit them
# from. A level that genuinely needs a different packing overrides it by keeping
# its own stage_enemies.asm, which the exporter never overwrites.
# THE ORDER IS THE WINDOW ORDER, not the species numbering. A level's chosen
# artwork is packed in this order, each entry taking exactly its own frame
# count, so the window holds only what the level uses.
SPECIES_ORDER = ("RING", "DROPPER", "SQUARE")   # src/encounter_format.asm

# --- THE ENEMY ARTWORK ROSTER ----------------------------------------------
# A ROSTER ENTRY IS ARTWORK, NOT A SPECIES. The engine has three behavioural
# species; a level chooses which sequence each of them WEARS. Frame counts run
# 1..8 and a species owns exactly its artwork's frame count -- there is no
# ENEMY_FRAMES any more, because there is no single answer.
#
# The roster itself lives in tools/sprite_export/import_spd.py, beside the
# SpritePad source it is cut from, and is imported here rather than copied: a
# second list of frame counts is exactly the kind of duplicate that goes stale.
_SPRITE_TOOLS = Path(__file__).resolve().parent.parent / "sprite_export"
if str(_SPRITE_TOOLS) not in sys.path:
    sys.path.insert(0, str(_SPRITE_TOOLS))
import import_spd as _spd                                          # noqa: E402

ENEMY_ROSTER = tuple((r.name, r.label, r.frames) for r in _spd.ENEMY_ROSTER)
ROSTER_FRAMES = {r.name: r.frames for r in _spd.ENEMY_ROSTER}
ROSTER_LABELS = {r.name: r.label for r in _spd.ENEMY_ROSTER}
ROSTER_SOURCE = {r.name: (r.slots[0], r.slots[-1]) for r in _spd.ENEMY_ROSTER}

# THE ONE AUTHORITATIVE BUDGET. src/main.asm LEVEL_SPRITE_BLOCKS, and the same
# number src/levelpkg.asm sizes LEVELPKG_SPR with. Imported, never retyped.
LEVEL_SPRITE_BLOCKS = _spd.LEVEL_SPRITE_BLOCKS          # 20

# --- A LEVEL'S THREE ENEMY IDENTITIES ---------------------------------------
# ORDERED, because the order IS the engine's species row offset: slot 0 is row
# 0, slot 1 is row 8, slot 2 is row 16. A trigger names an IDENTITY and the
# exporter resolves it to whichever of this level's slots holds it.
#
# The engine still has three enemy slots per level. What changed is that a slot
# is no longer one of three fixed legacy species -- it holds any identity from
# the roster, and the identity carries its own artwork, frame count and
# behaviour. "Space Whisk" is an enemy; it is not a Sonic Ring wearing a
# costume.
ENEMY_SLOTS = len(SPECIES_ORDER)        # 3, unchanged in this task

# What a level gets when it says nothing. Ring 3 is the successor to the Sonic
# Ring artwork the current SpritePad project retired, so a level written before
# identities existed keeps meaning what it meant.
DEFAULT_ENEMY_IDENTITIES = ["RING_3", "DROPPER", "SQUARE"]

# The legacy trigger species names, in slot order, for migrating old projects.
LEGACY_SPECIES_ORDER = ("RING", "DROPPER", "SQUARE")


def level_identities(project):
    """The three identity names this level holds, in slot order."""
    got = list(getattr(project, "enemy_slots", None) or [])
    out = []
    for i in range(ENEMY_SLOTS):
        name = got[i] if i < len(got) else None
        out.append(name if name in ROSTER_FRAMES else DEFAULT_ENEMY_IDENTITIES[i])
    return out


def identity_row(identity, identities):
    """The engine species row offset holding `identity`, or None if absent."""
    if identity in identities:
        return identities.index(identity) * ENEMY_ANIM_STEPS
    return None


BEHAVIOUR_PLAIN = _spd.BEHAVIOUR_PLAIN
BEHAVIOUR_DROPPER = _spd.BEHAVIOUR_DROPPER
ROSTER_BEHAVIOUR = {r.name: r.behaviour for r in _spd.ENEMY_ROSTER}


def identity_behaviour(name):
    """PLAIN or DROPPER. Behaviour belongs to the identity, not to a slot."""
    return ROSTER_BEHAVIOUR.get(name, BEHAVIOUR_PLAIN)


def identity_label(name):
    return ROSTER_LABELS.get(name, name)


def enemy_slot_cost(identities):
    """Blocks the three chosen identities consume."""
    total = 0
    for name in identities:
        if name not in ROSTER_FRAMES:
            raise ValueError(f"{name!r} is not in the enemy roster")
        total += ROSTER_FRAMES[name]
    return total


def enemy_slot_problems(identities):
    """Human-readable reasons a level's identity selection is invalid."""
    out = [f"{n!r} is not in the enemy roster"
           for n in identities if n not in ROSTER_FRAMES]
    if out:
        return out
    if len(identities) != ENEMY_SLOTS:
        return [f"a level holds {ENEMY_SLOTS} enemy identities; got {len(identities)}"]
    cost = enemy_slot_cost(identities)
    if cost > LEVEL_SPRITE_BLOCKS:
        out.append("enemy sprite budget exceeded: "
                   + " + ".join(f"{ROSTER_LABELS[n]} {ROSTER_FRAMES[n]}"
                                for n in identities)
                   + f" = {cost}, and the window holds {LEVEL_SPRITE_BLOCKS}")
    return out


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
