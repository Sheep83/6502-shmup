"""Import the authoritative engine encounter data into the v6 editor model.

THE DIRECTION OF TRUTH IN PHASE 3 IS ENGINE -> EDITOR. src/wave_programs.asm and
src/wave_encounters.asm are the authoritative source of Level 1's movement
programs, wave definitions and absolute triggers; Phase 1's migration deliberately
left those three lists EMPTY because a v5 project could not describe them. This
module fills them in from the engine, losslessly, so that Phase 4 can later make
the editor the source.

WHAT THIS MODULE IS NOT. It does not write assembler. The `reference_encode_*`
functions at the bottom exist ONLY to prove the import lost nothing -- they
produce the package BYTES the engine already emits, so a test can compare them
against the authoritative build. They are not an exporter, they emit no ASM, and
nothing here writes into src/.

PARSING IS SOMEBODY ELSE'S JOB: asm_decl.py reads the small authored-declaration
subset and knows nothing about encounters. This module knows about encounters and
nothing about assembler syntax.

WIDTHS ARE CHECKED ON THE WAY IN. Python integers are unbounded and the engine's
are not, so every imported value is range-checked against the width the package
actually stores it in -- a signed byte for a velocity, nine bits for a spawn X,
sixteen for a trigger row. An authored value that could not survive the round trip
is an error here rather than a surprise in the emitted bytes.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re

import contract_v2 as C
from asm_decl import AsmSyntaxError, parse_files
from project_v6 import MovementProgram, MovementStage, Trigger, WaveDefinition

# The authored files this importer reads, in the order they must be read: the
# format vocabularies first, because the content files name their constants.
FORMAT_FILES = ("movement_format.asm", "encounter_format.asm")
CONTENT_FILES = ("wave_programs.asm", "wave_encounters.asm")
# Where the level-owned half lives, relative to src/. See read_engine_source.
DEFAULT_LEVEL_DIR = "level1"


class EncounterImportError(ValueError):
    """Authoritative source that cannot be represented by the v6 contract."""


@dataclass
class ImportResult:
    movement_programs: list = field(default_factory=list)
    wave_definitions: list = field(default_factory=list)
    triggers: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    source_files: list = field(default_factory=list)

    def note(self, text):
        self.notes.append(text)

    def report(self):
        return "\n".join([f"Imported from {', '.join(self.source_files)}"]
                         + [f"  {n}" for n in self.notes])


# ---------------------------------------------------------------------------
# width checks
# ---------------------------------------------------------------------------
def _u8(value, what):
    if not isinstance(value, int) or not (0 <= value <= 255):
        raise EncounterImportError(f"{what} does not fit an unsigned byte: {value!r}")
    return value


def _s8(value, what):
    """A signed byte. The package emits `value & $ff`, so only -128..127 survives."""
    if not isinstance(value, int) or not (-128 <= value <= 127):
        raise EncounterImportError(f"{what} does not fit a signed byte: {value!r}")
    return value


def _heading(value, what):
    """A LAUNCH heading, which has no continuation sentinel.

    src/waves.asm build-errors on `def.get(8) < 0 || >= WM_HEAD_LEN`, so $ff is
    simply illegal here -- unlike byte 3 of an ARC, where it means WM_HEAD_CONT.
    Accepting it because it fits a byte would import a level the engine refuses.
    """
    if not isinstance(value, int) or not (0 <= value < C.WM_HEAD_LEN):
        raise EncounterImportError(
            f"{what} is not a launch heading 0..{C.WM_HEAD_LEN - 1}: {value!r}")
    return value


def _u16(value, what):
    if not isinstance(value, int) or not (0 <= value <= 0xFFFF):
        raise EncounterImportError(f"{what} does not fit sixteen bits: {value!r}")
    return value


def _symbol_map(consts, prefix):
    """{value: NAME} for every NAME the source defines with `prefix`.

    The trailing underscore in the prefix matters: WAVE_DEF_ must not match the
    count constant WAVE_DEFS.
    """
    out = {}
    for name, value in consts.items():
        if name.startswith(prefix) and len(name) > len(prefix):
            if value in out:
                raise EncounterImportError(
                    f"{prefix}* symbols {out[value]} and {name} share the value "
                    f"{value}; an imported id would be ambiguous")
            out[value] = name
    return out


def _id_from_symbol(name, prefix):
    """PROG_SWEEP -> 'sweep'. The engine's own name, minus its namespace prefix."""
    return name[len(prefix):].lower()


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def read_engine_source(src_dir, level_dir=None):
    """Read the format vocabulary and the authored content.

    THE TWO HALVES LIVE IN DIFFERENT PLACES SINCE PHASE 4. movement_format.asm
    and encounter_format.asm are ENGINE-owned and stay in src/; wave_programs.asm
    and wave_encounters.asm are LEVEL-owned and live in the level's own directory.
    `level_dir` defaults to src/level1, the production level and the Makefile's
    own LEVELDIR default. Passing src_dir alone still works for a tree where both
    halves sit together.
    """
    src_dir = Path(src_dir)
    if level_dir is None:
        candidate = src_dir / DEFAULT_LEVEL_DIR
        level_dir = candidate if (candidate / CONTENT_FILES[0]).is_file() else src_dir
    level_dir = Path(level_dir)
    paths = ([src_dir / n for n in FORMAT_FILES]
             + [level_dir / n for n in CONTENT_FILES])
    try:
        return parse_files(paths), [p.name for p in paths]
    except AsmSyntaxError as exc:
        raise EncounterImportError(str(exc)) from exc


def import_movement_programs(src):
    """`progs` + the PROG_* constants -> v6 MovementPrograms."""
    progs = src.list_("progs")
    names = _symbol_map(src.consts, "PROG_")
    if len(names) != len(progs):
        raise EncounterImportError(
            f"the source declares {len(progs)} movement programs but "
            f"{len(names)} PROG_* symbol(s); every program needs exactly one name")

    kind_of = {v: k for k, v in C.MOVEMENT_KINDS.items()}
    out = []
    for index, prog in enumerate(progs):
        if index not in names:
            raise EncounterImportError(f"no PROG_* symbol names program index {index}")
        pid = _id_from_symbol(names[index], "PROG_")
        if not isinstance(prog, list) or not prog:
            raise EncounterImportError(f"program {pid!r} has no stages")
        stages = []
        for s, rec in enumerate(prog):
            what = f"program {pid!r} stage {s}"
            if not isinstance(rec, list) or len(rec) != C.WM_STAGE_SIZE:
                raise EncounterImportError(
                    f"{what} is not {C.WM_STAGE_SIZE} values: {rec!r}")
            opcode, arg, b2, b3 = rec
            if opcode not in kind_of:
                raise EncounterImportError(
                    f"{what} names movement opcode {opcode!r}, which is not one of "
                    f"{sorted(C.MOVEMENT_KINDS.values())}")
            kind = kind_of[opcode]
            if kind in C.TIMED_KINDS:
                stages.append(MovementStage(
                    kind, frames=_u8(arg, f"{what} frames"),
                    vx=_s8(b2, f"{what} vx"), vy=_s8(b3, f"{what} vy")))
            elif kind in C.ARC_KINDS:
                # $ff IS THE ONE VALUE BYTE 3 CAN TAKE THAT IS NOT A HEADING.
                if b3 == C.WM_HEAD_CONT:
                    heading = "CONT"
                elif 0 <= b3 < C.WM_HEAD_LEN:
                    heading = b3
                else:
                    raise EncounterImportError(
                        f"{what} entry heading {b3!r} is neither a heading "
                        f"0..{C.WM_HEAD_LEN - 1} nor WM_HEAD_CONT (${C.WM_HEAD_CONT:02x})")
                stages.append(MovementStage(
                    kind, steps=_u8(arg, f"{what} steps"),
                    frames_per_step=_u8(b2, f"{what} frames per step"),
                    entry_heading=heading))
            else:                                   # EXIT reads none of its bytes
                stages.append(MovementStage(kind))
        out.append(MovementProgram(pid, stages))
    return out


def import_wave_definitions(src, programs):
    """`waveDefs` + the WAVE_DEF_* constants -> v6 WaveDefinitions.

    BYTE 9 IS AUTHORED AS A PROGRAM INDEX and emitted by src/level_package.asm as
    that program's byte OFFSET (`progAt.get(def.get(9))`). The editor stores the
    program's ID and the offset is derived, which is what stops an offset
    disagreeing with the records it points at.
    """
    defs = src.list_("waveDefs")
    declared = src.const("WAVE_DEFS")
    if len(defs) != declared:
        raise EncounterImportError(
            f"WAVE_DEFS is {declared} but waveDefs holds {len(defs)} definition(s)")
    names = _symbol_map(src.consts, "WAVE_DEF_")
    if len(names) != len(defs):
        raise EncounterImportError(
            f"the source declares {len(defs)} wave definitions but {len(names)} "
            f"WAVE_DEF_* symbol(s)")

    out = []
    for index, d in enumerate(defs):
        if index not in names:
            raise EncounterImportError(f"no WAVE_DEF_* symbol names definition {index}")
        did = _id_from_symbol(names[index], "WAVE_DEF_")
        if not isinstance(d, list) or len(d) != C.WAVEDEF_SIZE:
            raise EncounterImportError(
                f"wave definition {did!r} is not {C.WAVEDEF_SIZE} fields: {d!r}")
        what = f"wave definition {did!r}"
        x_lo, x_hi = _u8(d[2], f"{what} startX low"), _u8(d[3], f"{what} startX high")
        start_x = x_lo | (x_hi << 8)
        if start_x > C.MAX_SPAWN_X:
            raise EncounterImportError(
                f"{what} startX {start_x} exceeds the nine-bit X world")
        prog_index = d[9]
        if not isinstance(prog_index, int) or not (0 <= prog_index < len(programs)):
            raise EncounterImportError(
                f"{what} names movement program index {prog_index!r}, but the source "
                f"declares {len(programs)}")
        out.append(WaveDefinition(
            id=did,
            count=_u8(d[0], f"{what} count"),
            interval=_u8(d[1], f"{what} interval"),
            start_x=start_x,
            start_y=_u8(d[4], f"{what} startY"),
            x_step=_s8(d[5], f"{what} xStep"),
            y_step=_s8(d[6], f"{what} yStep"),
            # BYTE 7 IS THE FIRING MODE NOW; colour moved to the trigger.
            # This importer has never separated the packed fields of byte 7 --
            # a pre-existing limitation, untouched here -- so the value is
            # simply not carried onto the definition any more.
            heading=_heading(d[8], f"{what} launch heading"),
            movement_program=programs[prog_index].id))
    return out


def import_triggers(src, definitions, identities=None):
    """Every authored column -> v6 Triggers, live entries only.

    THE COLUMN LIST IS CHECKED against src/levelpkg.asm at the end, because it
    went stale silently: trigSpeed was added to the package, the exporter and the
    engine, and this reader went on ignoring it -- so a re-import of a level
    authored at 1.50x came back at 1.00x with nothing said. Two rowLo/rowHi
    halves make one column, hence the +1.
    """
    live = src.const("WAVE_TRIGGERS")
    columns = {name: src.list_(name) for name in
               ("trigRow", "trigDef", "trigSpecies", "trigFire", "trigSide",
                "trigColour", "trigFireMode", "trigSpeed")}
    if len(columns) + 1 != C.LEVELPKG_TRIG_COLS:
        raise EncounterImportError(
            f"this reader consumes {len(columns) + 1} trigger columns and "
            f"src/levelpkg.asm declares {C.LEVELPKG_TRIG_COLS}; a column has "
            f"been added to the package and not to the importer")
    lengths = {n: len(v) for n, v in columns.items()}
    if len(set(lengths.values())) != 1:
        raise EncounterImportError(
            f"the trigger columns are not all the same length: {lengths}")
    authored = next(iter(lengths.values()))
    if live > authored:
        raise EncounterImportError(
            f"WAVE_TRIGGERS is {live} but the columns hold only {authored} entries")

    # THE ENGINE'S SPECIES VALUE IS A SLOT, NOT AN ENEMY. Which identity sits in
    # a slot is recorded in the level's stage_enemies.asm, which this reader does
    # not consume -- it reads the encounter tables.
    #
    # SO THE CALLER SUPPLIES THE SLOTS when it knows them. import_encounters has
    # the target project and therefore its `enemySlots`, and passing them is what
    # makes export -> import -> export a real fixed point: without them a slot
    # came back as the DEFAULT identity for that position, so a level holding
    # Space Whisk re-imported as "SQUARE" and then re-exported as species row 0,
    # silently changing which enemy the trigger sends. Falling back to the
    # defaults is what a level that never chose otherwise carries.
    _ids = list(identities or C.DEFAULT_ENEMY_IDENTITIES)
    species_of = {i * C.ENEMY_ANIM_STEPS: _ids[i] if i < len(_ids)
                  else C.DEFAULT_ENEMY_IDENTITIES[i]
                  for i in range(C.ENEMY_SLOTS)}
    side_of = {v: k for k, v in C.DROPPER_SIDES.items()}
    fire_of = {v: k for k, v in C.FIRE_MODES.items()}
    out = []
    for i in range(live):                # LIVE ENTRIES ONLY -- see note below
        what = f"trigger {i}"
        row = _u16(columns["trigRow"][i], f"{what} worldProgress")
        d_index = columns["trigDef"][i]
        if not isinstance(d_index, int) or not (0 <= d_index < len(definitions)):
            raise EncounterImportError(
                f"{what} names wave definition index {d_index!r}, but the source "
                f"declares {len(definitions)}")
        sp = columns["trigSpecies"][i]
        if sp not in species_of:
            raise EncounterImportError(
                f"{what} names enemy slot {sp!r}, which is not one of "
                f"{sorted(species_of)}")
        side = columns["trigSide"][i]
        if side not in side_of:
            raise EncounterImportError(
                f"{what} names Dropper side {side!r}, which is not one of "
                f"{sorted(C.DROPPER_SIDES.items())}")
        mask = _u8(columns["trigFire"][i], f"{what} fire mask")
        # THE TWO ENCOUNTER COLUMNS. Colour and firing mode moved here from the
        # wave definition; a trigger imported without them would come back
        # silently defaulted rather than as authored.
        colour = _u8(columns["trigColour"][i], f"{what} colour")
        fmode = columns["trigFireMode"][i]
        if fmode not in fire_of:
            raise EncounterImportError(
                f"{what} names firing mode {fmode!r}, which is not one of "
                f"{sorted(C.FIRE_MODES.items())}")
        speed = columns["trigSpeed"][i]
        if not isinstance(speed, int) or not (
                C.TRIG_SPEED_MIN <= speed <= C.TRIG_SPEED_MAX):
            raise EncounterImportError(
                f"{what} names movement speed {speed!r}, which is not one of "
                f"{sorted(C.SPEED_CHOICES)}")
        out.append(Trigger(
            world_progress=row,
            wave_definition=definitions[d_index].id,
            species=species_of[sp],
            fire_mask=[m for m in range(8) if mask & (1 << m)],
            dropper_side=side_of[side],
            colour=colour & C.TRIG_COL_MASK,
            colour_mode=("RANDOM" if colour & C.TRIG_COL_RANDOM else "FIXED"),
            fire_mode=fire_of[fmode],
            speed=speed))
    return out, authored


# ---------------------------------------------------------------------------
# the import
# ---------------------------------------------------------------------------
def read_encounters(src_dir, level_dir=None, identities=None):
    """Read the authoritative encounter data. Does not touch any project.

    `identities` are the three enemy identities the destination level holds, so a
    species SLOT can be spelled back as the enemy that is actually in it.
    """
    src, names = read_engine_source(src_dir, level_dir)
    result = ImportResult(source_files=names)
    result.movement_programs = import_movement_programs(src)
    result.wave_definitions = import_wave_definitions(src, result.movement_programs)
    result.triggers, authored = import_triggers(src, result.wave_definitions,
                                                identities=identities)

    records = sum(len(p.stages) for p in result.movement_programs)
    result.note(f"{len(result.movement_programs)} movement program(s): "
                f"{', '.join(p.id for p in result.movement_programs)}")
    result.note(f"{records} movement records = {records * C.WM_STAGE_SIZE} pool bytes")
    result.note(f"{len(result.wave_definitions)} wave definition(s): "
                f"{', '.join(d.id for d in result.wave_definitions)}")
    result.note(f"{len(result.triggers)} live trigger(s) of {authored} authored "
                f"column entries; rows "
                f"{[t.world_progress for t in result.triggers]}")
    if src.skipped_blocks:
        result.note("control-flow blocks skipped by the reader (not interpreted): "
                    + ", ".join(f"{f}:{l} {k}" for f, l, k in src.skipped_blocks))
    return result


def import_encounters(project, src_dir, *, level_dir=None, replace=False):
    """Overlay the engine's encounters onto a v6 project, in place.

    REFUSES TO OVERWRITE SILENTLY. A project that already carries encounters is
    left untouched unless `replace=True` is passed, because the whole point of
    Phase 3 is that the engine is the source of truth exactly once -- after which
    the editor's copy is the thing being edited.

    Terrain, palette, glyphs, metatiles, the map, turrets, the stage dimensions
    and noSpawnRow are NOT touched.
    """
    existing = (project.movement_programs or project.wave_definitions
                or project.triggers)
    if existing and not replace:
        raise EncounterImportError(
            f"the project already carries encounters "
            f"({len(project.movement_programs)} program(s), "
            f"{len(project.wave_definitions)} definition(s), "
            f"{len(project.triggers)} trigger(s)). Pass replace=True to overwrite "
            f"them from the engine source.")

    result = read_encounters(src_dir, level_dir,
                             identities=C.level_identities(project))
    project.movement_programs = result.movement_programs
    project.wave_definitions = result.wave_definitions
    project.triggers = result.triggers
    if existing:
        result.note("replaced the project's existing encounter lists")
    return result


# ===========================================================================
# REFERENCE ENCODERS -- VERIFICATION ONLY, NOT AN EXPORTER
# ===========================================================================
# These produce the package BYTES the engine already emits from the same authored
# data, so a test can prove the import round-trips. They write no files and emit
# no assembler. Phase 4 owns the real exporter; if you are reading this because
# you want one, it does not live here.
# ===========================================================================
def program_offsets(programs):
    """Byte offset of each program's first record, keyed by id.

    The same arithmetic as `progAt` in src/wave_programs.asm: cumulative
    WM_STAGE_SIZE * stages. It is COMPUTED rather than parsed because the engine
    computes it inside a `.for` loop, which asm_decl deliberately does not run.
    """
    out, at = {}, 0
    for p in programs:
        out[p.id] = at
        at += len(p.stages) * C.WM_STAGE_SIZE
    return out


def reference_encode_movement_pool(programs):
    out = bytearray()
    for p in programs:
        for st in p.stages:
            opcode = C.MOVEMENT_KINDS[st.kind]
            if st.kind in C.TIMED_KINDS:
                out += bytes((opcode, st.frames, st.vx & 0xFF, st.vy & 0xFF))
            elif st.kind in C.ARC_KINDS:
                head = C.WM_HEAD_CONT if st.entry_heading == "CONT" else st.entry_heading
                out += bytes((opcode, st.steps, st.frames_per_step, head & 0xFF))
            else:
                out += bytes((opcode, 0, 0, 0))     # EXIT reads none of them
    return bytes(out)


def reference_encode_wave_definitions(definitions, programs):
    offsets = program_offsets(programs)
    out = bytearray()
    for d in definitions:
        out += bytes((
            d.count & 0xFF, d.interval & 0xFF,
            d.start_x & 0xFF, (d.start_x >> 8) & 0xFF,
            d.start_y & 0xFF,
            d.x_step & 0xFF, d.y_step & 0xFF,
            0,                          # byte 7: reserved, always zero
            d.heading & 0xFF,
            offsets[d.movement_program] & 0xFF))
    return bytes(out)


def _species_row(name, identities):
    """The engine species row for an identity name OR a legacy species name."""
    if name in C.LEGACY_SPECIES_ORDER:
        return C.LEGACY_SPECIES_ORDER.index(name) * C.ENEMY_ANIM_STEPS
    row = C.identity_row(name, identities)
    if row is None:
        raise EncounterImportError(
            f"{name!r} is in none of this level's slots {list(identities)} and "
            f"is not a legacy species name either")
    return row


def reference_encode_trigger_columns(triggers, definitions, slots=None,
                                    identities=None):
    """Every parallel column, padded to `slots` as src/level_package.asm emits it.

    ONE COLUMN PER FIELD, AND THE COUNT IS CHECKED against src/levelpkg.asm at
    the end: this function said "the six parallel columns" and emitted eight,
    and after the movement-speed column landed it emitted eight of nine. The
    package was 1,080 bytes and the reference encoding 960, so a byte-for-byte
    comparison against build/level1.prg could not even be attempted.

    `identities` is the level's own three enemy identities. It defaulted to
    C.DEFAULT_ENEMY_IDENTITIES, which resolves any identity the level has
    actually chosen -- Space Whisk, say -- to None and then to row 0, silently
    encoding the wrong species. Callers that have the project should pass them.
    """
    slots = C.MAX_TRIGGERS if slots is None else slots
    index_of = {d.id: i for i, d in enumerate(definitions)}
    n = len(triggers)
    _ids = list(identities or C.DEFAULT_ENEMY_IDENTITIES)
    cols = [
        [t.world_progress & 0xFF for t in triggers],
        [(t.world_progress >> 8) & 0xFF for t in triggers],
        [index_of[t.wave_definition] for t in triggers],
        # identity -> the slot this level put it in. A LEGACY SPECIES NAME is
        # accepted too: read_encounters maps a slot row back to the default
        # identity for that slot, because it reads the encounter tables and not
        # stage_enemies.asm, so an imported trigger can legitimately still be
        # spelled "SQUARE" where the project says "SPACE_WHISK". Both must encode
        # to the same row, or a re-encoding comparison fails on a spelling.
        [_species_row(t.species, _ids) for t in triggers],
        [t.fire_bits for t in triggers],
        [C.DROPPER_SIDES[t.dropper_side] for t in triggers],
        # THE SEVENTH COLUMN: this appearance's colour and colour mode.
        [(t.resolved_colour & C.MAX_COLOUR)
         | (C.TRIG_COL_RANDOM if t.resolved_colour_mode == "RANDOM" else 0)
         for t in triggers],
        # ...AND THE EIGHTH: how it attacks.
        [C.FIRE_MODES[t.resolved_fire_mode] for t in triggers],
        # ...AND THE NINTH: how fast it crosses the playfield.
        [t.resolved_speed for t in triggers],
    ]
    if len(cols) != C.LEVELPKG_TRIG_COLS:
        raise AssertionError(
            f"the reference encoder emits {len(cols)} trigger columns and "
            f"src/levelpkg.asm reserves room for {C.LEVELPKG_TRIG_COLS}")
    # THE PADDING IS PER COLUMN. Every column pads with zero except the speed,
    # which pads with TRIG_SPEED_1X -- a zero there would be a multiplier of
    # nothing. src/level_package.asm says the same thing beside the same column.
    pad = [0] * (len(cols) - 1) + [C.TRIG_SPEED_1X]
    return bytes(b for col, fill in zip(cols, pad)
                 for b in (col + [fill] * (slots - n)))
