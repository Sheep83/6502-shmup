"""Read current 19656 terrain glyph, metatile, palette, stage, and encounter data from assembly."""
from dataclasses import dataclass, field
from pathlib import Path
import re

METATILE_NAMES = (
    "PLATE", "R_FILL", "R_T", "R_B", "R_L", "R_R", "R_TL", "R_TR",
    "R_BL", "R_BR", "CHAN_V", "CHAN_H", "RECESS", "GRILLE", "MACH", "STEP",
)

# The ONE editor C64 colour table (index 0..15 -> approximate RGB). The stage
# editor renders previews with it and the Terrain Asset Workshop converts source
# artwork against the 4 project-palette entries picked out of it. Project data
# always stores colour *indices*, never RGB. Kept here so non-GUI modules
# (colour conversion, tests) can use it without importing the Tkinter editor.
C64_PALETTE_RGB = (
    (0x00, 0x00, 0x00), (0xff, 0xff, 0xff), (0x81, 0x33, 0x38), (0x75, 0xce, 0xc8),
    (0x8e, 0x3c, 0x97), (0x56, 0xac, 0x4d), (0x2e, 0x2c, 0x9b), (0xed, 0xf1, 0x71),
    (0x8e, 0x50, 0x29), (0x55, 0x38, 0x00), (0xc4, 0x6c, 0x71), (0x4a, 0x4a, 0x4a),
    (0x7b, 0x7b, 0x7b), (0xa9, 0xff, 0x9f), (0x70, 0x6d, 0xeb), (0xb2, 0xb2, 0xb2),
)
C64_PALETTE_HEX = tuple("#%02x%02x%02x" % rgb for rgb in C64_PALETTE_RGB)

METATILE_W = 4
METATILE_H = 4
METATILES_PER_ROW = 10
# Per-level metatile-definition table. It is variable length now (1..64 entries,
# no padding); the engine derives METATILE_DEF_COUNT = STAGE_METATILE_COUNT from
# the generated stage_config.asm. METATILE_CAPACITY is the hard ceiling a level
# package may hold; the editor's live metatile-set selector is bounded by it.
METATILE_CAPACITY = 64
# Back-compat alias: some call sites still say METATILE_DEF_COUNT meaning "the
# built-in / baseline count". It equals len(METATILE_NAMES) and is only the
# *default* set size for a fresh project, never a hard limit.
METATILE_DEF_COUNT = 16
# Terrain glyph namespace. Expanded 160/64 -> 96/128: the charset audit found
# screen codes 55..95 unused in every game state, so the HUD private glyphs moved
# 128 -> 64 and terrain now owns codes 96..223 (bitmaps $3B00..$3EFF, exactly
# half the $3800 charset). Metatile-def glyph code = TERRAIN_GLYPH_BASE + index.
# Pre-v5 project tilesets stored codes at base 160 and are remapped on load.
TERRAIN_GLYPH_BASE = 96
TERRAIN_GLYPH_NAMESPACE = 128
TERRAIN_GLYPH_BASE_LEGACY = 160        # base used by formatVersion <= 4 tilesets
# Safe maximum stage height. Recalculated from the real assembled layout for the
# 64-metatile worst case: metatileDefs+stageMetatileRows occupy $6600..$8800
# ($2200 = 8704 bytes); a full 64-entry def table is 1024 bytes, leaving
# (8704 - 1024) / 10 = 768 whole 10-byte rows. The engine's own label-based
# `.if (STAGE_TEST_END > $8800) .error` remains exact for smaller def tables
# (a 16-metatile level could reach 844); the editor deliberately uses the
# uniform worst case so the bound never depends on the tileset size.
ENGINE_MAX_STAGE_ROWS = 768

# The terrain aperture the player actually sees: 40 chars wide, 23 logical rows
# tall (matrix row 0 is the fixed hires HUD, matrix rows 1..23 are terrain, row
# 24 never reaches the RSEL=0 aperture). Bottom-origin: gameplay boots with
# SCROLL_ROW = STAGE_LOGICAL_ROWS - VIEWPORT_ROWS.
VIEWPORT_COLS = METATILES_PER_ROW * METATILE_W        # 40
VIEWPORT_ROWS = 23

# Turret runtime pool. Every live turret shares ONE 4-code body glyph set
# (codes 226..229), so concurrent capacity is NOT bounded by glyph codes - only
# by the per-slot state array (TURRET_POOL = 8, well above the ~7 turrets a
# 23-row aperture can hold and the 5 that can be combat-visible). The authored
# count is unbounded up to MAX_AUTHORED_TURRETS (8-bit streaming cursor); the
# engine streams authored turrets in/out of the pool as they cross the
# activation window. See src/background_turrets.asm.
TURRET_POOL = 8
MAX_AUTHORED_TURRETS = 255

# Curated enemy attacks. The editor references these by catalogue name/ID; it
# never re-implements formation/pattern/ingress/egress logic.
ATTACK_COUNT = 12
ENEMY_TYPE_COUNT = 4        # attackSpriteStart picks one of four sprite/colour sets

# Project defaults are design choices, not immutable engine truths.
DEFAULT_PALETTE = {
    "background": 0,
    "multicolour1": 12,
    "multicolour2": 15,
    "character": 1,
}
DEFAULT_SCROLL_FRAME_DIVIDER = 2


# Level-owned build inputs. EACH LEVEL OWNS A DIRECTORY UNDER src/, and for the
# production level that is src/level1/ -- the Makefile's own LEVELDIR default.
#
# THIS USED TO SAY src/generated/<level>/ AND A stage_test.asm, and neither has
# existed for some time; every path-dependent editor test failed on it. The map
# file is stage_map.asm, and the Makefile splits it on four labels into the two
# halves the level package emits at different addresses.
GENERATED_DIR_REL = "src"
LEVEL1_DIR_NAME = "level1"
GENERATED_CONFIG_NAME = "stage_config.asm"
GENERATED_CHARSET_NAME = "stage_charset.asm"
GENERATED_STAGE_NAME = "stage_map.asm"
GENERATED_TURRETS_NAME = "stage_turrets.asm"
# stage_enemies.asm is level-owned but hand-authored: it names the enemy sprite
# window slots and is not editor-generated (Contract v2 Phase 2).
LEVEL_ENEMIES_NAME = "stage_enemies.asm"
# THERE IS NO stage_waves.asm ANY MORE. Encounter data ships as bytes in the
# level package, authored in src/wave_programs.asm and src/wave_encounters.asm.
# Phase 3 moves it into the editor; nothing may generate this file.

# Turret body sits centred in its 4x4 metatile; world char = metatile*4 + 1.
TURRET_BODY_CHAR_OFFSET = 1


@dataclass
class EngineData:
    glyphs: dict[int, list[int]]
    metatiles: list[list[int]]
    stage_rows: list[list[int]]
    glyph_count: int
    source_stage_rows: int
    source_palette: dict[str, int]
    source_scroll_frame_divider: int
    source_colour_ram: int
    source_turrets: list[dict]
    attack_catalogue: list[tuple] = field(default_factory=list)   # [(name, id), ...]
    attack_intervals: list[int] = field(default_factory=list)     # attackInterval table
    attack_sprite_start: list[int] = field(default_factory=list)  # attackSpriteStart table


def _strip_comment(line):
    return line.split("//", 1)[0].strip()


def _parse_byte_values(line):
    line = _strip_comment(line)
    if ".byte" not in line:
        return []
    payload = line.split(".byte", 1)[1]
    values = []
    for token in payload.split(","):
        token = token.strip()
        if not token:
            continue
        base = 16 if token.startswith("$") else 10
        values.append(int(token[1:] if base == 16 else token, base))
    return values


def _read_table(path, start_label, end_label):
    values = []
    inside = False
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped == f"{start_label}:":
            inside = True
            continue
        if inside and stripped == f"{end_label}:":
            break
        if inside:
            values.extend(_parse_byte_values(raw_line))
    if not inside:
        raise ValueError(f"Could not find {start_label}: in {path}")
    return values


def _parse_const_int(text, name, default=None):
    pattern = rf"^\s*\.const\s+{re.escape(name)}\s*=\s*([^/\r\n]+)"
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        if default is not None:
            return default
        raise ValueError(f"Could not find .const {name}")
    expression = match.group(1).strip()
    if expression.startswith("$"):
        return int(expression[1:], 16)
    if re.fullmatch(r"\d+", expression):
        return int(expression)
    # Handle the current colour-RAM form: 8 | 1.
    parts = [part.strip() for part in expression.split("|")]
    if len(parts) > 1 and all(re.fullmatch(r"\d+", part) for part in parts):
        value = 0
        for part in parts:
            value |= int(part)
        return value
    raise ValueError(f"Unsupported numeric expression for {name}: {expression}")


def _parse_generated_config(path):
    """Parse the constants-only generated stage_config.asm.

    Ownership after the engine integration: stage height, terrain palette and
    scroll speed live here, NOT in main.asm. TERRAIN_COLOUR_RAM must derive from
    TERRAIN_CHARACTER_COLOUR (the fourth palette value is a named constant, not a
    hidden literal); this validates that.
    """
    text = Path(path).read_text(encoding="utf-8")
    rows = _parse_const_int(text, "STAGE_METATILE_ROWS")
    # SCROLL_FRAME_DIVIDER IS GONE FROM GENERATED CONFIGS and the engine never
    # read it: the scroll is 1 px/frame unconditionally. A hand-written config
    # from before Contract v2 may still carry one, so it is read when present and
    # defaulted otherwise -- this value now feeds nothing but the legacy v5 model.
    divider = _parse_const_int(text, "SCROLL_FRAME_DIVIDER",
                               default=DEFAULT_SCROLL_FRAME_DIVIDER)
    background = _parse_const_int(text, "TERRAIN_BACKGROUND_COLOUR")
    mc1 = _parse_const_int(text, "TERRAIN_MC_COLOUR_1")
    mc2 = _parse_const_int(text, "TERRAIN_MC_COLOUR_2")
    character = _parse_const_int(text, "TERRAIN_CHARACTER_COLOUR")

    cram_match = re.search(
        r"^\s*\.const\s+TERRAIN_COLOUR_RAM\s*=\s*([^/\r\n]+)", text, flags=re.MULTILINE
    )
    if not cram_match:
        raise ValueError(f"{path}: missing .const TERRAIN_COLOUR_RAM")
    cram_expr = cram_match.group(1).strip()
    expected_expr = "8 | TERRAIN_CHARACTER_COLOUR"
    if cram_expr != expected_expr:
        # Also accept the fully-resolved literal form, but require it to agree.
        try:
            cram_value = _parse_const_int(text, "TERRAIN_COLOUR_RAM")
        except ValueError:
            cram_value = None
        if cram_value != (8 | character):
            raise ValueError(
                f"{path}: TERRAIN_COLOUR_RAM must be '{expected_expr}' "
                f"(8 | TERRAIN_CHARACTER_COLOUR); got '{cram_expr}'"
            )
    colour_ram = 8 | character

    if not 0 <= character <= 7:
        raise ValueError(f"{path}: TERRAIN_CHARACTER_COLOUR must be 0..7; got {character}")
    for name, value in (("TERRAIN_BACKGROUND_COLOUR", background),
                        ("TERRAIN_MC_COLOUR_1", mc1),
                        ("TERRAIN_MC_COLOUR_2", mc2)):
        if not 0 <= value <= 15:
            raise ValueError(f"{path}: {name} must be 0..15; got {value}")

    palette = {
        "background": background,
        "multicolour1": mc1,
        "multicolour2": mc2,
        "character": character,
    }
    return rows, divider, palette, colour_ram


def _parse_ka_list(text, name):
    """Parse `.var <name> = List().add(1, 2, 3)` or `.var <name> = List()` -> [ints]."""
    match = re.search(
        rf"\.var\s+{re.escape(name)}\s*=\s*List\(\)(?:\.add\(([^)]*)\))?", text
    )
    if not match:
        raise ValueError(f"Could not find .var {name} = List()...")
    body = (match.group(1) or "").strip()
    if not body:
        return []
    return [int(tok.strip()) for tok in body.split(",") if tok.strip()]


def _parse_generated_turrets(path):
    """Parse the generated turret PLACEMENT file into metatile-grid objects."""
    if not Path(path).exists():
        return []
    text = Path(path).read_text(encoding="utf-8")
    try:
        count = _parse_const_int(text, "TURRET_TOTAL")
    except ValueError:
        count = _parse_const_int(text, "TURRET_COUNT")   # pre-streaming-pool files
    cols = _parse_ka_list(text, "turretCols")
    rows = _parse_ka_list(text, "turretRows")
    if not (count == len(cols) == len(rows)):
        raise ValueError(
            f"{path}: TURRET_TOTAL={count} but turretCols has {len(cols)} and turretRows has {len(rows)}"
        )
    turrets = []
    for world_col, world_row in zip(cols, rows):
        if (world_col - TURRET_BODY_CHAR_OFFSET) % 4 or (world_row - TURRET_BODY_CHAR_OFFSET) % 4:
            raise ValueError(
                f"{path}: turret at char ({world_col},{world_row}) is not on a metatile-cell "
                f"centre (col%4==1, row%4==1); editor placement uses the metatile grid"
            )
        turrets.append({
            "type": "turret",
            "metatileRow": (world_row - TURRET_BODY_CHAR_OFFSET) // 4,
            "metatileCol": (world_col - TURRET_BODY_CHAR_OFFSET) // 4,
        })
    return turrets


def _parse_attack_catalogue(main_text):
    """Extract the curated-attack catalogue (name -> id) and the attackInterval /
    attackSpriteStart tables from main.asm.

    Names come from the `.const ATTACK_* = <id>` block; the two data tables are
    read so the wave exporter can supply per-attack defaults without duplicating
    them in Python."""
    catalogue = []
    for match in re.finditer(
        r"^\s*\.const\s+(ATTACK_[A-Z0-9_]+)\s*=\s*(\d+)", main_text, flags=re.MULTILINE
    ):
        name, value = match.group(1), int(match.group(2))
        if name in ("ATTACK_COUNT",):
            continue
        catalogue.append((name, value))
    catalogue.sort(key=lambda pair: pair[1])

    def _list_after_label(label):
        match = re.search(
            rf"\.var\s+{label}\s*=\s*List\(\)\.add\(([^)]*)\)", main_text
        )
        if match:
            return [int(t.strip()) for t in match.group(1).split(",") if t.strip()]
        return None

    intervals = _list_after_label("attackIntervalData") or []
    sprite_start = _list_after_label("attackSpriteStartData") or []
    return catalogue, intervals, sprite_start


def _read_byte_table_from_text(text, label):
    """Read a `label:` .byte table terminated by a blank line / next label."""
    values = []
    inside = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped == f"{label}:":
            inside = True
            continue
        if inside:
            if stripped.endswith(":") and ".byte" not in stripped:
                break
            got = _parse_byte_values(raw)
            if not got and stripped and ".byte" not in stripped and not stripped.startswith("//"):
                break
            values.extend(got)
    return values


def load_engine_data(repo_root):
    repo_root = Path(repo_root)
    main_asm = repo_root / "src" / "main.asm"
    generated = repo_root / GENERATED_DIR_REL
    level1 = generated / LEVEL1_DIR_NAME

    # Prefer the per-level layout; fall back to the flat layout during migration.
    def _pick(name):
        new = level1 / name
        old = generated / name
        return new if new.exists() else old

    config_asm = _pick(GENERATED_CONFIG_NAME)
    charset_asm = _pick(GENERATED_CHARSET_NAME)
    stage_asm = _pick(GENERATED_STAGE_NAME)
    turrets_asm = _pick(GENERATED_TURRETS_NAME)
    main_text = main_asm.read_text(encoding="utf-8")

    if not config_asm.exists():
        raise ValueError(
            f"Generated level config not found: {config_asm}. "
            f"Export a project with tools/level_editor first."
        )
    (source_stage_rows, source_scroll_divider,
     source_palette, source_colour_ram) = _parse_generated_config(config_asm)

    # Terrain glyph count is level-owned and declared in stage_config.asm; the
    # bitmaps live in the per-level stage_charset.asm. Fall back to the
    # (soon-to-be-removed) hand-authored block in main.asm during migration, and
    # ultimately just count the bytes.
    config_text = config_asm.read_text(encoding="utf-8")
    if charset_asm.exists():
        glyph_bytes = _read_table(charset_asm, "terrainGlyphs", "terrainGlyphsEnd")
    else:
        glyph_bytes = _read_table(main_asm, "terrainGlyphs", "terrainGlyphsEnd")
    glyph_count = None
    for text in (config_text, charset_asm.read_text(encoding="utf-8") if charset_asm.exists() else "", main_text):
        try:
            glyph_count = _parse_const_int(text, "TERRAIN_GLYPH_COUNT")
            break
        except ValueError:
            continue
    if glyph_count is None:
        glyph_count = len(glyph_bytes) // 8

    if not 1 <= glyph_count <= TERRAIN_GLYPH_NAMESPACE or glyph_count % 8:
        raise ValueError(
            f"TERRAIN_GLYPH_COUNT must be 1..{TERRAIN_GLYPH_NAMESPACE} and a multiple of 8; got {glyph_count}"
        )

    expected_glyph_bytes = glyph_count * 8
    if len(glyph_bytes) != expected_glyph_bytes:
        raise ValueError(f"Expected {expected_glyph_bytes} terrain glyph bytes, got {len(glyph_bytes)}")

    metatile_bytes_raw = _read_table(stage_asm, "metatileDefs", "METATILE_DEFS_END")
    # Generated files built before the 96/128 namespace expansion stored glyph
    # codes at base 160. Detect the actual base from the def bytes and remap to
    # the current TERRAIN_GLYPH_BASE so a stale generated tree still loads.
    _emitted_base = min(metatile_bytes_raw) if metatile_bytes_raw else TERRAIN_GLYPH_BASE
    if _emitted_base in (TERRAIN_GLYPH_BASE, TERRAIN_GLYPH_BASE_LEGACY):
        _shift = TERRAIN_GLYPH_BASE - _emitted_base
    else:
        _shift = 0
    metatile_bytes = [c + _shift for c in metatile_bytes_raw]
    glyphs = {
        TERRAIN_GLYPH_BASE + i: glyph_bytes[i * 8:(i + 1) * 8]
        for i in range(glyph_count)
    }
    bytes_per_def = METATILE_W * METATILE_H
    # The def table is variable length now. Prefer the level-owned
    # STAGE_METATILE_COUNT; fall back to the byte count for pre-const files.
    try:
        metatile_count = _parse_const_int(config_text, "STAGE_METATILE_COUNT")
    except ValueError:
        metatile_count = len(metatile_bytes) // bytes_per_def
    if not 1 <= metatile_count <= METATILE_CAPACITY:
        raise ValueError(f"STAGE_METATILE_COUNT must be 1..{METATILE_CAPACITY}; got {metatile_count}")
    expected_metatile_bytes = metatile_count * bytes_per_def
    if len(metatile_bytes) != expected_metatile_bytes:
        raise ValueError(f"Expected {expected_metatile_bytes} metatile bytes, got {len(metatile_bytes)}")
    metatiles = [
        metatile_bytes[i * bytes_per_def:(i + 1) * bytes_per_def]
        for i in range(metatile_count)
    ]
    valid_codes = set(glyphs)
    invalid_codes = sorted({code for code in metatile_bytes if code not in valid_codes})
    if invalid_codes:
        raise ValueError(f"Metatile definitions reference unavailable terrain glyphs: {invalid_codes}")

    stage_bytes = _read_table(stage_asm, "stageMetatileRows", "STAGE_METATILE_ROWS_END")
    if len(stage_bytes) % METATILES_PER_ROW:
        raise ValueError(
            f"Stage table contains {len(stage_bytes)} bytes, not a whole number of {METATILES_PER_ROW}-byte rows"
        )
    parsed_stage_rows = len(stage_bytes) // METATILES_PER_ROW
    if parsed_stage_rows != source_stage_rows:
        raise ValueError(
            f"STAGE_METATILE_ROWS says {source_stage_rows}, but stage table contains {parsed_stage_rows} rows"
        )
    if any(tile_id >= metatile_count for tile_id in stage_bytes):
        raise ValueError(f"Stage contains a metatile ID outside 0..{metatile_count - 1}")
    stage_rows = [
        stage_bytes[i * METATILES_PER_ROW:(i + 1) * METATILES_PER_ROW]
        for i in range(parsed_stage_rows)
    ]

    catalogue, intervals, sprite_start = _parse_attack_catalogue(main_text)
    if not intervals:
        intervals = _read_byte_table_from_text(main_text, "attackInterval")
    if not sprite_start:
        # attackSpriteStart is materialised from a List(); read the .fill target.
        sprite_start = _read_byte_table_from_text(main_text, "attackSpriteStart")

    return EngineData(
        glyphs=glyphs,
        metatiles=metatiles,
        stage_rows=stage_rows,
        glyph_count=glyph_count,
        source_stage_rows=source_stage_rows,
        source_palette=source_palette,
        source_scroll_frame_divider=source_scroll_divider,
        source_colour_ram=source_colour_ram,
        source_turrets=_parse_generated_turrets(turrets_asm),
        attack_catalogue=catalogue,
        attack_intervals=intervals,
        attack_sprite_start=sprite_start,
    )
