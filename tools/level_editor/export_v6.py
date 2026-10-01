"""Phase 2 exporter: a v6 project -> the four level-owned assembler includes.

WHAT THIS OWNS, AND WHAT IT DELIBERATELY DOES NOT.

    stage_config.asm    constants the engine compiles against
    stage_charset.asm   the terrain glyph bitmaps
    stage_map.asm       metatile definitions, then the map rows
    stage_turrets.asm   TURRET_TOTAL and the two coordinate lists
    wave_programs.asm   the movement program pool, as authored declarations
    wave_encounters.asm the wave definitions and the six trigger columns

A level directory needs a FIFTH file, stage_enemies.asm, which says which slot of
the engine's enemy sprite window each species was loaded into. It is not editor
content in this phase and is not generated here; export_level() copies it forward
when one exists beside the destination, and says so in the result.

ENCOUNTERS ARE EXPORTED SINCE PHASE 4, and the two files above are LEVEL-OWNED:
they live in the level's own directory beside the terrain, not in src/. That
matters more than it looks. KickAssembler resolves `#import "wave_programs.asm"`
against the IMPORTING FILE'S OWN DIRECTORY before it looks at any -libdir, so
while a copy existed in src/ the engine would silently keep using it and editing
the level-owned one would do nothing at all. Measured, not assumed: a deliberately
altered level-owned copy produced a byte-identical level1.prg until the src/ copies
were removed. There is therefore exactly one production copy of each.

A project whose encounter lists are EMPTY still exports both files -- empty pools
and a zero WAVE_TRIGGERS are legal -- so never export a project that has not had
its encounters imported unless you mean to ship a level with no waves.

WHY A NEW MODULE RATHER THAN A REWRITE OF ka_export.py. The old exporter targets
an architecture that no longer exists: src/generated/<level>/, a stage_test.asm
that is now stage_map.asm, a stage_waves.asm that must not exist at all, and a
SCROLL_FRAME_DIVIDER the engine never reads. Its trigger emission is built on the
attack catalogue. Editing it in place would leave both contracts half-present in
one file; it stays as it is and this module speaks only the current one.

DESTINATION IS ALWAYS EXPLICIT. Nothing here defaults to the repository, so a
test cannot overwrite the authoritative src/level1/ by omission.
"""
from pathlib import Path
import hashlib
import os
import re
import shutil

import contract_v2 as C
from validation_v6 import validate

CONFIG_NAME = "stage_config.asm"
CHARSET_NAME = "stage_charset.asm"
MAP_NAME = "stage_map.asm"
TURRETS_NAME = "stage_turrets.asm"
PROGRAMS_NAME = "wave_programs.asm"
ENCOUNTERS_NAME = "wave_encounters.asm"
# Level-owned: it names the enemy sprite-window slots. It USED to be purely
# hand-authored, which meant a fresh level directory silently came out without
# it and did not assemble -- src/main.asm imports it. It is now generated from
# the canonical default packing when the destination does not already have one,
# and never overwritten when it does, so a level that needs its own packing
# keeps it by simply having the file.
ENEMIES_NAME = "stage_enemies.asm"
SPRITES_NAME = "stage_sprites.asm"

TERRAIN_NAMES = (CONFIG_NAME, CHARSET_NAME, MAP_NAME, TURRETS_NAME)
ENCOUNTER_NAMES = (PROGRAMS_NAME, ENCOUNTERS_NAME)
GENERATED_NAMES = TERRAIN_NAMES + ENCOUNTER_NAMES
# EVERY file src/main.asm and src/level_package.asm need from a level directory.
# A package missing any one of these does not assemble, so the export refuses
# rather than leaving one behind.
REQUIRED_PACKAGE_NAMES = GENERATED_NAMES + (ENEMIES_NAME, SPRITES_NAME)


class ExportRefused(RuntimeError):
    """The project has validation errors, so nothing was written.

    REFUSING IS THE POINT. Every limit validation_v6 enforces is one the engine
    build would fail on anyway; emitting the files and letting KickAssembler find
    it moves the error a long way from the field that caused it.
    """
    def __init__(self, result):
        """Carries either a validation result or a plain reason.

        A refusal is not always about validation: the completeness gate at the
        end of export_level() refuses a package that came out short, and that
        has no ValidationResult to report. Both arrive at the same `except
        ExportRefused` in the editor, which is the point.
        """
        if isinstance(result, str):
            self.result = None
            super().__init__(result)
            return
        self.result = result
        super().__init__(f"export refused: {len(result.errors)} validation error(s)\n"
                         + "\n".join(f"  {i}" for i in result.errors))


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------
def _banner(level_name, *body):
    """The generated-file header. NOTHING VOLATILE: no timestamp, no path, no
    version string -- only the level's own name, so two exports of one project
    are byte-identical."""
    line = "// " + "=" * 74
    out = [line, "// AUTO-GENERATED by tools/level_editor. DO NOT EDIT BY HAND.",
           f"// Level: {level_name}", "//"]
    out += [f"// {t}" if t else "//" for t in body]
    out.append(line)
    return out


def _byte_line(values, comment=None, width=3):
    # THE SEPARATOR IS A BARE COMMA. Each value is right-aligned in `width`, so
    # its own leading space supplies the gap: "," + " 85" reads as ", 85". Using
    # ", " as well would double it and diverge from every level file in the tree.
    body = ",".join(f"{v:{width}d}" for v in values)
    line = f"    .byte {body}"
    if comment:
        line += f"   // {comment}"
    return line


def _text(lines):
    """LF endings, exactly one trailing newline."""
    return "\n".join(lines) + "\n"


def _metatile_name(project, index):
    entries = project.level_metatile_set
    if isinstance(entries, list) and index < len(entries):
        entry = entries[index]
        if isinstance(entry, dict) and entry.get("name"):
            return str(entry["name"])
    return f"M{index}"


# ---------------------------------------------------------------------------
# stage_config.asm
# ---------------------------------------------------------------------------
def render_stage_config(project, level_name):
    stage = project.stage
    playable = stage.playable_progress
    quiet = playable - stage.no_spawn_row
    pal = project.palette
    lines = _banner(
        level_name,
        "CONSTANTS-ONLY level-config include. Emits no bytes, no memory segment,",
        "no program-counter change. Imported very early so every level-owned",
        "constant exists before the engine constants/code that consume them.",
        "",
        "Ownership: these values belong to the level package, NOT to the engine.",
        "The engine derives STAGE_LOGICAL_ROWS = STAGE_METATILE_ROWS * METATILE_H",
        "and METATILE_DEF_COUNT = STAGE_METATILE_COUNT (the level's metatile-def",
        "table is variable length: STAGE_METATILE_COUNT * 16 bytes, 1..64).",
        "  TERRAIN_BACKGROUND_COLOUR -> $D021",
        "  TERRAIN_MC_COLOUR_1       -> $D022   (multicolour bit-pair 01)",
        "  TERRAIN_MC_COLOUR_2       -> $D023   (multicolour bit-pair 10)",
        "  TERRAIN_CHARACTER_COLOUR  -> colour RAM low 3 bits (bit-pair 11)",
        "TERRAIN_GLYPH_COUNT is level-owned too (the tileset lives in",
        "stage_charset.asm); it is declared here so the engine's early glyph-",
        "namespace guards resolve before the byte block is imported.",
    )
    lines += [
        f".const STAGE_METATILE_ROWS     = {stage.metatile_rows}",
        "",
        "// THE BOSS APPROACH. No ordinary authored encounter may START at or after",
        "// this world-progress row, which is what turns the run-in to the boss from",
        "// \"whatever happened to be left over\" into an authored, deterministic",
        "// clearance.",
        "//",
        "// SAME COORDINATE DOMAIN AS A TRIGGER ROW: coarse rows of worldProgress,",
        "// 16-bit, counted from the start of the stage. This stage's own last",
        f"// complete view is STAGE_METATILE_ROWS * {C.METATILE_H} - {C.SCREEN_ROWS} "
        f"= {playable}, so this",
        f"// leaves {quiet} rows of approach.",
        "//",
        "// IT FORBIDS, IT DOES NOT DESCRIBE. The value says where authoring STOPS,",
        "// not where the action happens to stop.",
        f".const STAGE_NO_SPAWN_ROW      = {stage.no_spawn_row}",
        f".const STAGE_METATILE_COUNT   = {len(project.metatile_defs)}",
        f".const TERRAIN_BACKGROUND_COLOUR = {pal.background}",
        f".const TERRAIN_MC_COLOUR_1     = {pal.multicolour1}",
        f".const TERRAIN_MC_COLOUR_2     = {pal.multicolour2}",
        f".const TERRAIN_CHARACTER_COLOUR = {pal.character}",
        ".const TERRAIN_COLOUR_RAM      = 8 | TERRAIN_CHARACTER_COLOUR",
        f".const TERRAIN_GLYPH_COUNT     = {len(project.glyphs)}",
    ]
    # SCROLL_FRAME_DIVIDER IS NOT EMITTED. It was generated into this file for
    # years and read by nothing in the engine: the scroll is 1 px/frame
    # unconditionally. See the Contract v2 audit, section 2.4.
    return _text(lines)


# ---------------------------------------------------------------------------
# stage_charset.asm
# ---------------------------------------------------------------------------
def render_stage_charset(project, level_name):
    """The terrain glyph bitmaps, and the labels src/terrain.asm imports.

    THE OLD HEADER WAS WRONG AND IS CORRECTED HERE. It claimed codes 96..223 at
    "$3B00-$3EFF, 128 slots" and that initBackground copied them to $3B00. The
    charset now lives in the $0800 window: src/terrain.asm sets
    TERRAIN_CHARSET = $0800 and TERRAIN_GLYPHS = $0800 + 96*8 = $0b00. The real
    ceiling is 130 glyphs, because src/turrets.asm errors if terrain reaches the
    turret glyphs at code 226 -- not the 128 the old comment implied.
    """
    count = len(project.glyphs)
    base = C.TERRAIN_GLYPH_BASE
    top = base + count - 1
    glyph_addr = 0x0800 + base * C.GLYPH_BYTES
    lines = _banner(
        level_name,
        "LEVEL-OWNED terrain glyph bitmaps - the swappable tileset unit.",
        f"This level authors {count} glyph(s) at character codes {base}..{top}.",
        "",
        f"The terrain charset window is $0800-$0FFF (src/terrain.asm,",
        f"TERRAIN_CHARSET), so these bitmaps resolve to "
        f"${glyph_addr:04X}-${glyph_addr + count * C.GLYPH_BYTES - 1:04X}",
        f"(TERRAIN_GLYPHS = TERRAIN_CHARSET + {base} * {C.GLYPH_BYTES}).",
        "",
        f"The ceiling is {C.MAX_TERRAIN_GLYPHS} glyphs: src/turrets.asm fails the",
        f"build if terrain reaches the turret glyph namespace at code "
        f"{C.TURRET_GLYPH_BASE}.",
        "",
        "src/terrain.asm imports this block at TERRAIN_GLYPHS and checks its own",
        "byte count against TERRAIN_GLYPH_COUNT, declared in stage_config.asm.",
    )
    lines.append("terrainGlyphs:")
    for i, glyph in enumerate(project.glyphs):
        lines.append(_byte_line(glyph, f"code {base + i}"))
    lines += [
        "terrainGlyphsEnd:",
        f".if (terrainGlyphsEnd - terrainGlyphs != TERRAIN_GLYPH_COUNT * "
        f"{C.GLYPH_BYTES}) {{",
        '    .error "terrainGlyphs data size does not match TERRAIN_GLYPH_COUNT * 8"',
        "}",
    ]
    return _text(lines)


# ---------------------------------------------------------------------------
# stage_map.asm
# ---------------------------------------------------------------------------
def render_stage_map(project, level_name):
    """Metatile definitions first, then the rows.

    THE FOUR LABELS ARE A BUILD CONTRACT, NOT DECORATION. The Makefile splits
    this one file into the two halves the package emits at different addresses:

        awk '/^metatileDefs:/,/^METATILE_DEFS_END:/'        -> stage_map_defs.asm
        awk '/^stageMetatileRows:/,/^STAGE_METATILE_ROWS_END:/' -> stage_map_rows.asm

    Each must sit at the START of its line and the order must not change.
    """
    rows = project.map_rows
    defs = project.metatile_defs
    lines = _banner(
        level_name,
        f"{len(rows)} metatile rows x {C.METATILES_PER_ROW} columns.",
        "Terrain colour is level-global; there is intentionally no per-cell "
        "colour table.",
        "",
        "metatileDefs is row-major 4x4: def[subRow * 4 + col] is a character code.",
        "The Makefile splits this file on the four labels below, so they must stay",
        "at the start of their lines and in this order.",
    )
    lines.append("metatileDefs:")
    for i, d in enumerate(defs):
        lines.append(_byte_line(d, f"M{i} {_metatile_name(project, i)}"))
    lines.append("METATILE_DEFS_END:")
    lines.append("")
    lines.append("stageMetatileRows:")
    for y, row in enumerate(rows):
        lines.append(_byte_line(row, f"row {y}"))
    lines.append("STAGE_METATILE_ROWS_END:")
    lines.append("// Size/memory guards remain engine-owned immediately after this "
                 "include.")
    return _text(lines)


# ---------------------------------------------------------------------------
# stage_turrets.asm
# ---------------------------------------------------------------------------
def turret_entries(project):
    """(world_row, world_col) pairs, DESCENDING by world row.

    Descending is the order gameplay's downward-scrolling stage crosses them,
    which is the order the engine's streaming cursor expects. Ties break by
    ascending column -- they cannot occur while one turret per metatile row is
    enforced, but the rule makes the output total rather than dependent on the
    order turrets happened to be drawn in.
    """
    entries = [(t.world_row, t.world_col) for t in project.turrets]
    entries.sort(key=lambda rc: (-rc[0], rc[1]))
    return entries


def render_stage_turrets(project, level_name):
    entries = turret_entries(project)
    lines = _banner(
        level_name,
        "Authored turret PLACEMENT layer. Constants + assembler lists only.",
        "PLACEMENT is editor-owned; BEHAVIOUR stays engine-owned "
        "(src/turrets.asm).",
        "",
        f"  world row = metatileRow * {C.METATILE_H} + {C.TURRET_ROW_PHASE}",
        f"  world col = metatileCol * {C.METATILE_W} + {C.TURRET_ROW_PHASE}",
        "",
        "Rows are 16-bit and sorted DESCENDING -- the order the downward-scrolling",
        "stage crosses them.",
        "",
        f"CONTRACT v2 TEMPORARY LIMITS: at most {C.MAX_TURRETS} turrets "
        f"(trtDeadPending is one",
        "byte, one bit per turret) and at most one per metatile row "
        "(turretAtMetaRow",
        "holds a single index). Both are scheduled to be lifted.",
    )
    cols = ", ".join(str(c) for _, c in entries)
    rws = ", ".join(str(r) for r, _ in entries)
    lines += [
        f".const TURRET_TOTAL = {len(entries)}",
        f".var turretCols = List()" + (f".add({cols})" if entries else ""),
        f".var turretRows = List()" + (f".add({rws})" if entries else ""),
    ]
    return _text(lines)


# ---------------------------------------------------------------------------
# encounter symbol names, derived from the semantic ids
# ---------------------------------------------------------------------------
_SYMBOL_OK = re.compile(r"^[a-z][a-z0-9_]*$")


def _check_symbol(kind, ident):
    """A v6 id has to survive becoming an assembler symbol.

    The importer derives ids from the engine's own PROG_*/WAVE_DEF_* names, so a
    round-tripped project always passes. A hand-edited JSON might not, and a bad
    id would produce source that does not assemble -- which is a worse error, a
    long way from its cause.
    """
    if not _SYMBOL_OK.match(ident or ""):
        raise ExportRefused(_OneError(
            f"{kind}.id",
            f"{kind} id {ident!r} cannot become an assembler symbol; ids must "
            f"match [a-z][a-z0-9_]*"))
    return ident


class _OneError:
    """Shim so _check_symbol can raise the same ExportRefused shape."""
    def __init__(self, path, message):
        from validation_v6 import Issue
        self.errors = [Issue("export.bad_id", message, path)]
        self.warnings = []
        self.ok = False


def prog_const(ident):
    return "PROG_" + ident.upper()


def wavedef_const(ident):
    return "WAVE_DEF_" + ident.upper()


def wavedef_var(ident):
    return "def" + "".join(part.capitalize() for part in ident.split("_"))


def wavedef_reserved_byte(_d):
    """Byte 7 of a wave definition: reserved, and always zero.

    IT USED TO BE THE COLOUR BYTE, then the colour plus the firing mode, then
    the firing mode alone. Every one of those was a property of the OCCURRENCE
    wearing the clothes of the reusable formation, and all of them now live on
    the trigger -- see trigger_colour_byte and trigger_fire_mode_byte below.

    The byte stays rather than the record shrinking: a definition is ten bytes
    because src/waves.asm forms def * 10 in a single byte, and dropping to nine
    would move the heading and program index for twenty-six bytes of package.
    src/waves.asm refuses to assemble a definition whose byte 7 is not zero.
    """
    return 0


def trigger_colour_byte(t):
    """The trigger's colour byte: bits 0-3 the colour, bit 4 the random flag.

    A FRESH FIELD WITH ONE MEANING, which is why it needs no cleverness. When
    colour lived on the definition it had to be smuggled into a byte that was
    already carrying the firing mode; a trigger column of its own has room to
    say what it means.

    THE COLOUR IS EMITTED IN BOTH MODES. A RANDOM trigger keeps the author's
    chosen colour in the low nibble so switching back to Fixed returns it; the
    runtime reads the nibble only when bit 4 is clear.
    """
    byte = t.resolved_colour & C.MAX_COLOUR
    if t.resolved_colour_mode == "RANDOM":
        byte |= C.TRIG_COL_RANDOM
    return byte


def trigger_fire_mode_byte(t):
    """The trigger's firing mode: TRIG_FIRE_DOWN or TRIG_FIRE_AIMED.

    A column of its own rather than a bit borrowed from a neighbour. trigFire
    is a full eight-bit mask over member index and has no spare bits; trigSide
    and trigSpecies have some, but neither is where a firing mode belongs and a
    species value is a row offset that grows as species are added.
    """
    return C.FIRE_MODES[t.resolved_fire_mode]


def trigger_fire_mode_expr(t):
    return f"TRIG_FIRE_{t.resolved_fire_mode}"


def trigger_speed_byte(t):
    """The trigger's movement speed: a numerator over four.

    A column of its own, like the colour and the firing mode beside it. There
    was no spare bit to borrow -- trigFire is a full eight-bit mask, and
    trigSpeed's own range needs four values of headroom for the five choices.
    """
    return t.resolved_speed


def trigger_speed_expr(t):
    """...as the generated source spells it, symbolically where it can."""
    named = {C.TRIG_SPEED_1X: "TRIG_SPEED_1X", 5: "TRIG_SPEED_125X",
             6: "TRIG_SPEED_150X", 7: "TRIG_SPEED_175X", 8: "TRIG_SPEED_2X"}
    return named.get(t.resolved_speed, str(t.resolved_speed))


def trigger_dropper_program_expr(project, t):
    """What member 0 of this Dropper trigger flies, as the generated source says it.

    THE SENTINEL OR A PROGRAM CONSTANT, and never a bare number: the generated
    file already names every movement program (`PROG_LOOP` and friends), so the
    trigger column reads as the author's selection rather than as a position in
    a list that shifts when a program is inserted.

    AN INDEX, NOT AN OFFSET. src/level_package.asm resolves it through progAt at
    package-emit time, exactly as it resolves a wave definition's tenth byte.
    Doing it here would bake a byte offset into the trigger list and make
    inserting a stage in an unrelated program silently repoint this one.

    A NON-DROPPER TRIGGER EMITS THE SENTINEL whatever its field says. The
    validator has already refused the combination (see
    validation_v6, trigger.dropper_program_ignored) so this is belt and braces
    rather than a policy -- but the engine also refuses it at assembly time, and
    emitting a stale field would turn an editor-level mistake into a build
    failure in a generated file nobody hand-edits.
    """
    if t.dropper_program is None:
        return "TRIG_DROP_LEGACY"
    if C.identity_behaviour(t.species) != C.BEHAVIOUR_DROPPER:
        return "TRIG_DROP_LEGACY"
    _check_symbol("movement program", t.dropper_program)
    return prog_const(t.dropper_program)


def trigger_colour_expr(t):
    """...as the generated source spells it, symbolically where it matters."""
    colour = t.resolved_colour & C.MAX_COLOUR
    if t.resolved_colour_mode == "RANDOM":
        return f"TRIG_COL_RANDOM + {colour}"
    return str(colour)


# ---------------------------------------------------------------------------
# wave_programs.asm
# ---------------------------------------------------------------------------
def render_wave_programs(project, level_name):
    """The movement program pool, as the authored declarations the engine reads.

    THE `.for` LOOP AT THE END IS NOT DECORATION. src/level_package.asm emits a
    wave definition's tenth byte as `progAt.get(def.get(9))` and src/waves.asm
    checks `progBytes`, so both must exist with exactly these names. The offsets
    are therefore computed by the ASSEMBLER from the pool it can see, not written
    out here -- an emitted offset could disagree with the records it points at,
    which is the one thing this arrangement is designed to make impossible.
    """
    progs = project.movement_programs
    for p in progs:
        _check_symbol("movement program", p.id)

    lines = _banner(
        level_name,
        "THE MOVEMENT PROGRAM POOL, as authored data. Constants and .var data",
        "only: this file emits no bytes and moves no program counter.",
        "",
        "Both builds import it -- src/waves.asm validates and flies every path at",
        "assembly time, and src/level_package.asm emits the records into the level",
        "package at LEVELPKG_MOVE. The record format is engine-owned and lives in",
        "src/movement_format.asm.",
        "",
        "    kind            arg             byte 2           byte 3",
        "    WM_STRAIGHT     frames          vx               vy",
        "    WM_HOLD         frames          vx               vy",
        "    WM_ARC          heading steps   frames per step  entry heading, or",
        "    WM_ARC_MIRROR   heading steps   frames per step  WM_HEAD_CONT",
        "    WM_EXIT         --              --               --",
        "",
        "Velocities are signed quarter-pixels per frame. Headings run clockwise",
        "from east in WM_HEAD_LEN steps, with +y DOWN.",
    )
    lines += ["#importonce", '#import "movement_format.asm"', "",
              ".var progs = List()"]

    for i, prog in enumerate(progs):
        lines += ["", f"// --- {i}: {prog.id.upper()} "
                      f"{'-' * max(0, 58 - len(prog.id))}",
                  ".eval progs.add(List()"]
        body = []
        for st in prog.stages:
            body.append(f"    .add(List().add({_stage_args(st)}))")
        lines += body[:-1] + [body[-1] + ")"]

    lines.append("")
    for i, prog in enumerate(progs):
        lines.append(f".const {prog_const(prog.id):<22} = {i}")

    lines += [
        "",
        "// Byte offsets of each program's first record, computed rather than",
        "// authored: a hand-maintained offset is a number that is right until",
        "// somebody inserts a stage.",
        ".var progAt = List()",
        ".var progBytes = 0",
        ".for (var p = 0; p < progs.size(); p++) {",
        "    .eval progAt.add(progBytes)",
        "    .eval progBytes = progBytes + WM_STAGE_SIZE * progs.get(p).size()",
        "}",
        "// ONE BYTE OF CURSOR, AND THAT IS THE WHOLE CEILING: every object carries",
        "// its position in this pool in wmStage.",
        f".if (progBytes > {C.LEVELPKG_MOVE_MAX}) {{",
        '    .error "the stage table has outgrown the one-byte cursor in wmStage"',
        "}",
    ]
    return _text(lines)


def _stage_args(st):
    """One record's four authored values, symbolic where the engine is."""
    kind = st.kind
    if kind in C.TIMED_KINDS:
        return f"WM_{kind}, {st.frames}, {st.vx}, {st.vy}"
    if kind in C.ARC_KINDS:
        head = ("WM_HEAD_CONT" if st.entry_heading == "CONT"
                else str(st.entry_heading))
        return f"WM_{kind}, {st.steps}, {st.frames_per_step}, {head}"
    return "WM_EXIT, 0, 0, 0"


# ---------------------------------------------------------------------------
# wave_encounters.asm
# ---------------------------------------------------------------------------
def render_wave_encounters(project, level_name):
    """The wave definitions and the six absolute-trigger columns.

    SIX PARALLEL COLUMNS, NOT INTERLEAVED RECORDS. The director indexes every one
    of them with the same cursor, so parallel columns cost one absolute,Y per
    field; an interleaved record would need the cursor multiplied by six on every
    read. src/level_package.asm pads each column out to LEVELPKG_TRIG_SLOTS when
    it emits them, so nothing here has to know the capacity.
    """
    defs = project.wave_definitions
    trigs = project.triggers
    for d in defs:
        _check_symbol("wave definition", d.id)
    index_of = {d.id: i for i, d in enumerate(defs)}

    lines = _banner(
        level_name,
        "THE AUTHORED ENCOUNTER SCHEDULE, as data. Constants and .var data only:",
        "this file emits no bytes and moves no program counter.",
        "",
        "Both builds import it -- src/waves.asm validates it and flies every member",
        "of every wave at assembly time, and src/level_package.asm emits the bytes",
        "into the level package. The vocabulary is engine-owned and lives in",
        "src/encounter_format.asm.",
        "",
        "WHAT IS DELIBERATELY NOT HERE: anything the engine owns. The Dropper's",
        "flight, the P-token, the protector conscription and the boss lifecycle are",
        "engine state machines a level does not author; the only thing a level says",
        "about the Dropper is which trigger carries it and which side it enters",
        "from.",
    )
    lines += ["#importonce", '#import "encounter_format.asm"',
              '#import "wave_programs.asm"', ""]

    lines += [
        "// --- the wave definitions -------------------------------------------",
        "// Ten bytes each, read by the director with one indexed load per field:",
        "//   0 count      how many enemies this wave sends",
        "//   1 interval   frames between one member and the next",
        "//   2 startXLo   nine-bit spawn X...",
        "//   3 startXHi",
        "//   4 startY     spawn line",
        "//   5 xStep      signed, added to X per member",
        "//   6 yStep      signed, added to Y per member",
        "//   7 reserved   always zero. Enemy colour and firing mode are",
        "//                TRIGGER fields, not definition fields",
        "//   8 heading    launch heading, 0..WM_HEAD_LEN-1",
        "//   9 program    a program INDEX here; src/level_package.asm emits it as",
        "//                that program's BYTE OFFSET via progAt",
        f".const WAVEDEF_SIZE = {C.WAVEDEF_SIZE}",
        "",
    ]
    for d in defs:
        rows = [
            (f"{d.count}, {d.interval},", "count, interval"),
            (f"{d.start_x & 0xFF}, {(d.start_x >> 8) & 0xFF},",
             f"startX = {d.start_x}, nine bits split low/high"),
            (f"{d.start_y},", "startY"),
            (f"{d.x_step}, {d.y_step},", "xStep, yStep -- signed, per member"),
            # THE COLOUR BYTE CARRIES THE FIRING MODE IN BITS 4-5. A wave
            # definition is ten bytes and src/waves.asm forms def * 10 in one
            # byte, so an eleventh byte would cap a level at 24 definitions.
            # Mode 0 (DOWN) leaves the byte exactly as it has always been
            # exported, which is what makes old packages still correct.
            # THE COMMENT ONLY MENTIONS THE MODE WHEN THERE IS ONE TO MENTION.
            # A DOWN definition packs to exactly the byte it always packed to,
            # so saying nothing keeps previously generated files byte-identical
            # and keeps the diff of a real change down to the lines that
            # actually changed.
            # BYTE 7 IS RESERVED. The colour and the firing mode that used to
            # share it belong to the trigger now -- see trigColour and
            # trigFireMode below.
            (f"{wavedef_reserved_byte(d)},", "reserved -- must be zero"),
            (f"{d.heading},", "launch heading"),
            (f"{prog_const(d.movement_program)})", "movement program INDEX"),
        ]
        lines.append(f".var {wavedef_var(d.id)} = List().add(")
        for value, comment in rows:
            lines.append(f"    {value:<26}// {comment}")
        lines.append("")

    chain = "".join(f".add({wavedef_var(d.id)})" for d in defs)
    lines += [
        f".var waveDefs = List(){chain}",
        f".const {'WAVE_DEFS':<22} = {len(defs)}",
    ]
    for i, d in enumerate(defs):
        lines.append(f".const {wavedef_const(d.id):<22} = {i}")
    lines += [
        '.if (waveDefs.size() != WAVE_DEFS) { .error "wave definition count '
        'disagrees with the table" }',
        "",
    ]

    lines += [
        "// --- the absolute trigger list --------------------------------------",
        "// ABSOLUTE SIXTEEN-BIT worldProgress ROWS, and the list does not repeat.",
        "// A trigger names one row; once consumed it never becomes due again. The",
        "// rows must be NON-DECREASING because the director's cursor only ever",
        "// walks forward, and every row must be below STAGE_NO_SPAWN_ROW.",
        _list_decl("trigRow", [str(t.world_progress) for t in trigs]),
        "",
        "// Which definition each appearance plays.",
        _list_decl("trigDef",
                   [wavedef_const(t.wave_definition) for t in trigs]),
        "",
        "// WHICH ENEMY THE WAVE IS MADE OF -- an authored column rather than",
        "// arithmetic on the cursor, so inserting a trigger cannot silently invert",
        "// every wave after it.",
        # A TRIGGER NAMES AN IDENTITY; THE PACKAGE CARRIES A SLOT. The engine's
        # species value is this level's enemy SLOT (row 0, 8 or 16), and which
        # identity sits in that slot is the level's own choice. Resolving it
        # here is what lets a trigger say "Space Whisk" instead of pretending
        # to be one of three legacy species.
        _list_decl("trigSpecies",
                   [f"SPECIES_{C.SPECIES_ORDER[_identity_slot(project, t.species)]}"
                    for t in trigs]),
        "",
        "// WHICH SIDE A DROPPER FLIES IN FROM. Read only when the species above is",
        "// SPECIES_DROPPER; a Ring wave carries whatever is written here and",
        "// ignores it.",
        _list_decl("trigSide", [f"DROP_SIDE_{t.dropper_side}" for t in trigs]),
        "",
        "// WHICH MEMBERS OF THIS APPEARANCE MAY SHOOT -- a bitmask over MEMBER",
        "// INDEX, bit 0 the first member sent, and zero for a formation that does",
        "// not shoot at all.",
        _list_decl("trigFire", [f"%{t.fire_bits:08b}" for t in trigs]),
        "",
        "// HOW THIS APPEARANCE IS COLOURED -- bits 0-3 the C64 colour every",
        "// member wears, bit 4 (TRIG_COL_RANDOM) set if each enemy instead picks",
        "// its own eligible colour once, at spawn. On the TRIGGER and not on the",
        "// definition, so the same reusable formation can arrive in a different",
        "// colour at every row it is used.",
        _list_decl("trigColour", [trigger_colour_expr(t) for t in trigs]),
        "",
        "// HOW THIS APPEARANCE ATTACKS -- TRIG_FIRE_DOWN or TRIG_FIRE_AIMED.",
        "// On the TRIGGER and not on the definition, so the same reusable",
        "// formation can arrive silent at one row and aimed at another. Read",
        "// only for the members trigFire admits, and only for a species that",
        "// can shoot at all.",
        _list_decl("trigFireMode", [trigger_fire_mode_expr(t) for t in trigs]),
        "",
        "// HOW FAST THIS APPEARANCE CROSSES THE PLAYFIELD -- a numerator over",
        "// four, TRIG_SPEED_1X being a bit-exact no-op. On the TRIGGER and not",
        "// on the definition, so one reusable path can be walked at several",
        "// paces. src/waves.asm flies every definition at every speed a trigger",
        "// here actually asks for.",
        _list_decl("trigSpeed", [trigger_speed_expr(t) for t in trigs]),
        "",
        "// WHAT THIS APPEARANCE'S DROPPER FLIES -- TRIG_DROP_LEGACY for the",
        "// hard-coded three-pass trajectory in src/dropper.asm, or a movement",
        "// program INDEX for a path the level authored for MEMBER 0. Read only",
        "// when the species above is SPECIES_DROPPER.",
        "//",
        "// AN INDEX HERE, A BYTE OFFSET IN THE PACKAGE: src/level_package.asm",
        "// emits it through progAt, exactly as it does a wave definition's tenth",
        "// byte. src/waves.asm flies every authored Dropper path at the speed the",
        "// trigger naming it asks for.",
        "//",
        "// THE ESCORTS ARE NOT AFFECTED. Members 1..N-1 of a Dropper wave fly the",
        "// wave definition above; this column reaches member 0 alone.",
        _list_decl("trigDropProg",
                   [trigger_dropper_program_expr(project, t) for t in trigs]),
        "",
        f".const {'WAVE_TRIGGERS':<22} = {len(trigs)}",
    ]
    return _text(lines)


def _list_decl(name, values):
    """`.var name = List().add(a, b, c)`, or an empty List() when there are none."""
    return f".var {name:<12} = List()" + (f".add({', '.join(values)})"
                                          if values else "")


# ---------------------------------------------------------------------------
# the export
# ---------------------------------------------------------------------------
def _enemy_identities(project):
    """This level's three enemy identities, in slot order, validated."""
    ids = C.level_identities(project)
    problems = C.enemy_slot_problems(ids)
    if problems:
        raise ExportRefused("; ".join(problems))
    return ids


def _identity_slot(project, identity):
    """Which of this level's three enemy slots holds `identity`."""
    ids = C.level_identities(project)
    if identity not in ids:
        raise ExportRefused(
            f"a trigger uses the enemy {C.identity_label(identity)!r}, which "
            f"this level does not carry. The level holds "
            + ", ".join(C.identity_label(i) for i in ids)
            + ". Either add it to the level's enemies or point the trigger at "
              "one it has.")
    return ids.index(identity)


def render_stage_enemies(project, level_name):
    """Which artwork this level's three species wear, and the animation table.

    GENERATED EVERY EXPORT, and that is a change. It used to be written once as
    a default and then left alone for ever, because it only said where three
    fixed four-block species sat and that never varied. It now encodes the
    level's CHOICE of artwork and the resolved animation table, so a hand-kept
    copy would silently ignore every change made in the editor.

    The table itself comes from tools/sprite_export/import_spd.py, which owns
    the roster, the frame counts and each sequence's animation steps. Nothing is
    recomputed here; a second implementation is a second thing to go stale.
    """
    ids = _enemy_identities(project)
    digest = hashlib.sha256(Path(C._spd.SPD).read_bytes()).hexdigest()
    text, _layout, _table = C._spd.level_enemies_asm(ids, digest, level_name)
    return text


def render_stage_sprites(project, level_name):
    """The manifest: which generated art files fill the window, in window order.

    ALSO GENERATED EVERY EXPORT, for the same reason and for one more: it must
    name exactly the artwork stage_enemies.asm claims, and the package build
    checks the two against each other. Keeping one by hand while generating the
    other is how they would disagree.
    """
    layout, _ = C._spd.level_sprite_plan(_enemy_identities(project))
    body = [
        "// The enemy sprite window is level-owned artwork: the package carries",
        "// the bytes and levelApplySprites copies them into LEVEL_SPRITES at",
        "// level init. This names which generated blocks fill the window, in",
        "// WINDOW ORDER -- slot 0 first, contiguously.",
        "//",
        "// IT IS A MANIFEST, NOT ARTWORK. Every block comes from",
        "// src/generated_sprites/, produced by tools/sprite_export/import_spd.py",
        "// from assets/sprites/19656-sprites.spd. SpritePad remains the",
        "// authority; this only says which of its output this level ships.",
        "//",
        "// ONLY THE CHOSEN ARTWORK IS SHIPPED. The roster has twelve sequences;",
        "// a level carries the three it uses, which is what keeps it inside the",
        f"// engine's {C.LEVEL_SPRITE_BLOCKS}-block window.",
        "",
        "#importonce",
        "",
    ]
    for r, b in layout:
        body.append(f'#import "generated_sprites/{r.filename}"'
                    + " " * max(1, 46 - len(r.filename))
                    + f"// slots {b}-{b + r.frames - 1}  {r.label}")
    return _text(_banner(level_name,
                         "this level's claim on the SPRITE artwork") + [""] + body)


def render_all(project, level_name):
    """All six generated files as {filename: text}. No I/O."""
    return {
        CONFIG_NAME: render_stage_config(project, level_name),
        CHARSET_NAME: render_stage_charset(project, level_name),
        MAP_NAME: render_stage_map(project, level_name),
        TURRETS_NAME: render_stage_turrets(project, level_name),
        PROGRAMS_NAME: render_wave_programs(project, level_name),
        ENCOUNTERS_NAME: render_wave_encounters(project, level_name),
    }


def export_level(project, dest_dir, *, level_name=None, validate_first=True,
                 carry_enemies_from=None):
    """Write the six generated includes into `dest_dir`.

    dest_dir             REQUIRED and explicit. Nothing defaults to the repo.
    level_name           defaults to the project's own name.
    validate_first       refuse to write anything if the project has errors.
    carry_enemies_from   optional directory holding a hand-authored
                         stage_enemies.asm to copy forward. It is level-owned but
                         NOT editor-generated in Phase 2, and a level directory is
                         not buildable without it.

    Returns {filename: Path} for everything written, including the carried file.
    """
    if validate_first:
        result = validate(project)
        if not result.ok:
            raise ExportRefused(result)

    level_name = level_name or project.name
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # RENDER EVERYTHING BEFORE WRITING ANYTHING. render_all() returns a complete
    # dict, so a refusal -- a bad id, a missing reference -- happens with the
    # destination untouched rather than three files into a six-file package.
    rendered = render_all(project, level_name)

    # THEN REPLACE, RATHER THAN OVERWRITE. Each file goes to a temporary beside
    # its target and is moved into place with os.replace, which is atomic on one
    # filesystem. A disk filling up halfway through cannot leave a level package
    # half old and half new -- a state that still assembles and is wrong, which
    # is the worst kind of failure this could have.
    written, temps = {}, []
    try:
        for name, text in rendered.items():
            tmp = dest / (name + ".tmp")
            tmp.write_text(text, encoding="utf-8", newline="\n")
            temps.append((tmp, dest / name))
        for tmp, target in temps:
            os.replace(tmp, target)
            written[target.name] = target
    except OSError:
        for tmp, _ in temps:                    # leave the destination as it was
            try:
                tmp.unlink()
            except OSError:
                pass
        raise

    # stage_enemies.asm: KEEP a hand-authored one, GENERATE one when there is
    # none. The old code only ever copied, and both callers pass the destination
    # itself as `carry_enemies_from` -- so on a fresh level directory the source
    # did not exist, the copy was skipped without a word, and the export handed
    # back a six-file package that src/main.asm cannot assemble.
    # stage_enemies.asm and stage_sprites.asm are GENERATED EVERY TIME now.
    # They used to be carried forward by hand because they only recorded a fixed
    # packing; they now encode which artwork this level chose, so carrying an old
    # one forward would discard the choice and ship the previous level's
    # animation table against this level's sprite window.
    for name, render in ((ENEMIES_NAME, render_stage_enemies),
                         (SPRITES_NAME, render_stage_sprites)):
        target = dest / name
        tmp = dest / (name + ".tmp")
        tmp.write_text(render(project, level_name), encoding="utf-8", newline="\n")
        os.replace(tmp, target)
        written[name] = target

    # AND THEN CHECK. An export that quietly produces an unbuildable directory
    # is worse than one that fails, because the failure surfaces later as an
    # assembler error in a file nobody edited.
    missing = [n for n in REQUIRED_PACKAGE_NAMES if not (dest / n).is_file()]
    if missing:
        raise ExportRefused(
            "export produced an incomplete level package -- missing "
            + ", ".join(missing)
            + f" in {dest}. The engine imports every one of "
            f"{len(REQUIRED_PACKAGE_NAMES)} files and will not assemble without them.")
    return written
