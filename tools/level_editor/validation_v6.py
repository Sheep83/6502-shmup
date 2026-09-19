"""Validation for the v6 project model, against the current engine contract.

A RESULT OBJECT, NOT A MODAL DIALOG. The previous editor raised and popped up as
it went, which meant the rules lived wherever a screen happened to need them and
could not be tested without a display. Everything here returns a structure:

    result.errors     breaches that must block an export
    result.warnings   legal, but the kind of thing an author wants told
    result.capacity   derived budgets, for gauges and for the report

Every issue carries a STABLE CODE so a GUI can attach it to a field and a test
can assert on it without matching English.

ERROR versus WARNING is the engine's own line, not taste. An ERROR is something
`src/` refuses to assemble or the hardware cannot address -- a ninth turret, a
271st byte of movement pool, a trigger at the no-spawn row. A WARNING is legal
data that is probably not what the author meant: a quiet zone too short to clear
the screen, a third simultaneous trigger that the director will drop.

DEFERRED ON PURPOSE: the trajectory and visibility proofs in src/waves.asm --
"does every member reach a despawn edge", "is it ever visible", "does it enter
within SIM_ENTER_BUDGET" -- are a quarter-pixel flight simulation of the whole
movement interpreter. Half of one would be worse than none: it would pass paths
the engine rejects and reject paths it accepts. They stay assembly-time proofs
until a preview simulator exists that can be checked against them (Contract v2
report §7.5, phases 4/6). Nothing structural is weakened to compensate.
"""
from dataclasses import dataclass, field

import contract_v2 as C
from project_v6 import ProjectV6


@dataclass(frozen=True)
class Issue:
    code: str           # stable, e.g. "turret.too_many"
    message: str        # human-readable
    path: str = ""      # e.g. "triggers[3].worldProgress"

    def __str__(self):
        return f"[{self.code}] {self.path + ': ' if self.path else ''}{self.message}"


@dataclass
class ValidationResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    capacity: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.errors

    def error(self, code, message, path=""):
        self.errors.append(Issue(code, message, path))

    def warn(self, code, message, path=""):
        self.warnings.append(Issue(code, message, path))

    def codes(self):
        return [i.code for i in self.errors + self.warnings]

    def __str__(self):
        lines = [f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"]
        lines += [f"  ERROR   {i}" for i in self.errors]
        lines += [f"  WARNING {i}" for i in self.warnings]
        return "\n".join(lines)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate(project):
    """Validate a ProjectV6. Deterministic: same project, same issues, same order."""
    r = ValidationResult()
    if not isinstance(project, ProjectV6):
        r.error("project.type", "not a ProjectV6")
        return r

    _validate_stage(project, r)
    _validate_palette(project, r)
    _validate_glyphs(project, r)
    _validate_metatiles(project, r)
    _validate_map(project, r)
    _validate_turrets(project, r)
    _validate_movement(project, r)
    _validate_wave_definitions(project, r)
    _validate_triggers(project, r)
    _capacity(project, r)
    return r


# ---------------------------------------------------------------------------
def _validate_stage(p, r):
    stage = p.stage
    if stage is None:
        r.error("stage.missing", "the project has no stage", "stage")
        return

    cols = getattr(p, "declared_metatile_cols", C.METATILES_PER_ROW)
    if cols != C.METATILES_PER_ROW:
        r.error("stage.width",
                f"stage width is fixed at {C.METATILES_PER_ROW} metatiles "
                f"(METATILES_PER_ROW * METATILE_W must tile the 40-column "
                f"screen exactly); got {cols}",
                "stage.metatileCols")

    rows = stage.metatile_rows
    if not (C.MIN_METATILE_ROWS <= rows <= C.MAX_METATILE_ROWS):
        r.error("stage.rows",
                f"metatileRows must be {C.MIN_METATILE_ROWS}..{C.MAX_METATILE_ROWS} "
                f"(the package reserves {C.LEVELPKG_MAP_MAX} bytes for the map, and "
                f"a stage must be taller than one screen); got {rows}",
                "stage.metatileRows")
        return                              # everything below derives from rows

    playable = stage.playable_progress
    ns = stage.no_spawn_row
    if not (1 <= ns <= C.MAX_WORLD_PROGRESS):
        r.error("no_spawn.range",
                f"noSpawnRow must be a legal sixteen-bit world row of at least 1 "
                f"(row zero would suppress the entire stage); got {ns}",
                "stage.noSpawnRow")
    elif ns > playable:
        r.error("no_spawn.past_end",
                f"noSpawnRow {ns} is beyond the last row the stage reaches "
                f"({playable}): the quiet zone could never begin",
                "stage.noSpawnRow")
    elif ns == playable:
        r.error("no_spawn.zero_zone",
                f"noSpawnRow {ns} equals the stage end, leaving no quiet zone at all",
                "stage.noSpawnRow")
    else:
        quiet = playable - ns
        if quiet < C.SCREEN_ROWS:
            r.warn("no_spawn.short_zone",
                   f"the quiet zone is {quiet} coarse rows "
                   f"({quiet * C.FRAMES_PER_COARSE_ROW / C.PAL_FPS:.1f} s). The "
                   f"longest authored wave in level 1 occupies 48 rows, so a zone "
                   f"this short may let a formation survive into the boss arena",
                   "stage.noSpawnRow")
        if quiet > playable * 2 // 5:
            r.warn("no_spawn.long_zone",
                   f"the quiet zone is {quiet} of {playable} rows -- more than two "
                   f"fifths of the stage carries no authored encounter",
                   "stage.noSpawnRow")


def _validate_palette(p, r):
    pal = p.palette
    for name in ("background", "multicolour1", "multicolour2"):
        v = getattr(pal, name)
        if not (0 <= v <= C.MAX_COLOUR):
            r.error("palette.colour",
                    f"{name} must be a C64 colour index 0..{C.MAX_COLOUR}; got {v}",
                    f"palette.{name}")
    ch = pal.character
    if not (0 <= ch <= C.MAX_CHARACTER_COLOUR):
        r.error("palette.character",
                f"character colour must be 0..{C.MAX_CHARACTER_COLOUR}: the engine "
                f"writes `8 | colour` into colour RAM to force multicolour, so only "
                f"the low three bits survive and 8..15 alias 0..7; got {ch}",
                "palette.character")


def _validate_glyphs(p, r):
    n = len(p.glyphs)
    if n < 1:
        r.error("glyph.none", "a level needs at least one terrain glyph", "glyphs")
    if n > C.MAX_TERRAIN_GLYPHS:
        r.error("glyph.too_many",
                f"at most {C.MAX_TERRAIN_GLYPHS} terrain glyphs: codes start at "
                f"{C.TERRAIN_GLYPH_BASE} and may not reach the turret glyphs at "
                f"{C.TURRET_GLYPH_BASE}; got {n}",
                "glyphs")
    for i, g in enumerate(p.glyphs):
        if not isinstance(g, list) or len(g) != C.GLYPH_BYTES:
            r.error("glyph.size",
                    f"a glyph is exactly {C.GLYPH_BYTES} bytes; got "
                    f"{len(g) if isinstance(g, list) else type(g).__name__}",
                    f"glyphs.bitmaps[{i}]")
            continue
        for b in g:
            if not _is_int(b) or not (0 <= b <= 255):
                r.error("glyph.byte", f"glyph byte out of range: {b!r}",
                        f"glyphs.bitmaps[{i}]")
                break


def _validate_metatiles(p, r):
    defs = p.metatile_defs
    n = len(defs)
    if n < 1:
        r.error("metatile.none", "a level needs at least one metatile definition",
                "metatileDefs")
    if n > C.MAX_METATILE_DEFS:
        r.error("metatile.too_many",
                f"at most {C.MAX_METATILE_DEFS} metatile definitions "
                f"({C.LEVELPKG_DEFS_MAX} package bytes / 16); got {n}",
                "metatileDefs")
    top = C.TERRAIN_GLYPH_BASE + len(p.glyphs) - 1
    for i, d in enumerate(defs):
        if not isinstance(d, list) or len(d) != C.METATILE_DEF_CELLS:
            r.error("metatile.size",
                    f"a metatile definition is exactly {C.METATILE_DEF_CELLS} "
                    f"character codes (4x4, row-major); got "
                    f"{len(d) if isinstance(d, list) else type(d).__name__}",
                    f"metatileDefs[{i}]")
            continue
        for code in d:
            if not _is_int(code) or not (C.TERRAIN_GLYPH_BASE <= code <= top):
                r.error("metatile.glyph_code",
                        f"metatile cell names character code {code!r}, outside the "
                        f"level's terrain namespace {C.TERRAIN_GLYPH_BASE}..{top}",
                        f"metatileDefs[{i}]")
                break
    used = {c for row in p.map_rows if isinstance(row, list) for c in row}
    for i in range(n):
        if i not in used:
            r.warn("metatile.unused",
                   f"metatile definition {i} is never placed on the map",
                   f"metatileDefs[{i}]")


def _validate_map(p, r):
    rows = p.map_rows
    if p.stage is not None and len(rows) != p.stage.metatile_rows:
        r.error("map.row_count",
                f"the map has {len(rows)} rows but the stage declares "
                f"{p.stage.metatile_rows}",
                "map")
    n_defs = len(p.metatile_defs)
    for y, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != C.METATILES_PER_ROW:
            r.error("map.row_width",
                    f"every map row holds exactly {C.METATILES_PER_ROW} metatile "
                    f"IDs; got {len(row) if isinstance(row, list) else type(row).__name__}",
                    f"map[{y}]")
            continue
        for x, cell in enumerate(row):
            if not _is_int(cell) or not (0 <= cell < n_defs):
                r.error("map.cell",
                        f"metatile ID {cell!r} does not resolve to one of the "
                        f"level's {n_defs} definitions",
                        f"map[{y}][{x}]")
                return          # one report is enough; a bad map is bad everywhere


def _validate_turrets(p, r):
    ts = p.turrets
    if len(ts) > C.MAX_TURRETS:
        r.error("turret.too_many",
                f"at most {C.MAX_TURRETS} turrets: trtDeadPending is ONE BYTE, one "
                f"bit per turret, and the engine build fails above it. (Contract v2 "
                f"temporary limit -- scheduled to be lifted.); got {len(ts)}",
                "turrets")
    seen = {}
    rows = p.stage.metatile_rows if p.stage else 0
    for i, t in enumerate(ts):
        if not (0 <= t.metatile_row < rows):
            r.error("turret.row_range",
                    f"turret metatileRow {t.metatile_row} is outside the stage "
                    f"(0..{rows - 1})", f"turrets[{i}].metatileRow")
        if not (0 <= t.metatile_col < C.METATILES_PER_ROW):
            r.error("turret.col_range",
                    f"turret metatileCol {t.metatile_col} is outside "
                    f"0..{C.METATILES_PER_ROW - 1}", f"turrets[{i}].metatileCol")
        else:
            # src/turrets.asm: turretCols[t] + TURRET_BODY_W > SCREEN_COLS errors.
            if t.world_col + C.TURRET_BODY_W > C.SCREEN_COLS:
                r.error("turret.body_off_right",
                        f"the turret body runs off the right of the screen "
                        f"(world column {t.world_col} + {C.TURRET_BODY_W} > "
                        f"{C.SCREEN_COLS})", f"turrets[{i}].metatileCol")
        if rows and 0 <= t.metatile_row < rows:
            # src/turrets.asm: body must not run off the bottom of the stage.
            if t.world_row + C.TURRET_BODY_H - 1 >= C.logical_rows(rows):
                r.error("turret.body_off_bottom",
                        f"the turret body runs off the bottom of the stage "
                        f"(world row {t.world_row} + {C.TURRET_BODY_H - 1} >= "
                        f"{C.logical_rows(rows)})", f"turrets[{i}].metatileRow")
        if t.metatile_row in seen:
            r.error("turret.duplicate_row",
                    f"metatile row {t.metatile_row} already carries the turret at "
                    f"index {seen[t.metatile_row]}: turretAtMetaRow holds only one "
                    f"per row. (Contract v2 temporary limit.)",
                    f"turrets[{i}].metatileRow")
        else:
            seen[t.metatile_row] = i


def _validate_movement(p, r):
    ids = set()
    for i, prog in enumerate(p.movement_programs):
        path = f"movementPrograms[{i}]"
        if not prog.id:
            r.error("movement.no_id", "a movement program needs an id", path)
        elif prog.id in ids:
            r.error("movement.duplicate_id",
                    f"duplicate movement program id {prog.id!r}", path)
        else:
            ids.add(prog.id)

        if not prog.stages:
            r.error("movement.empty", "a movement program has no stages", path)
            continue
        if prog.stages[-1].kind != "EXIT":
            r.error("movement.no_exit",
                    "a movement program must end in EXIT or it would run off the "
                    "table", f"{path}.stages[{len(prog.stages) - 1}]")
        for j, st in enumerate(prog.stages):
            spath = f"{path}.stages[{j}]"
            if st.kind not in C.MOVEMENT_KINDS:
                r.error("movement.kind",
                        f"unknown movement opcode {st.kind!r}; expected one of "
                        f"{', '.join(sorted(C.MOVEMENT_KINDS))}", spath)
                continue
            if st.kind == "EXIT" and j != len(prog.stages) - 1:
                r.error("movement.after_exit",
                        "EXIT is terminal and cannot be followed by another stage",
                        spath)
            if st.kind in C.TIMED_KINDS:
                if st.frames < 1:
                    r.error("movement.frames",
                            f"a {st.kind} stage of zero length would never advance",
                            f"{spath}.frames")
                for axis in ("vx", "vy"):
                    v = getattr(st, axis)
                    if abs(v) > C.MAX_ABS_VX:
                        r.error("movement.velocity",
                                f"|{axis}| {abs(v)} exceeds {C.MAX_ABS_VX} quarter "
                                f"pixels a frame: the once-a-frame wrap guard "
                                f"(ENEMY_CLEAR_X_LEFT) would be stepped over",
                                f"{spath}.{axis}")
            elif st.kind in C.ARC_KINDS:
                if st.steps < 1:
                    r.error("movement.steps",
                            "an arc with no heading steps would never advance",
                            f"{spath}.steps")
                if st.frames_per_step < 1:
                    r.error("movement.frames_per_step",
                            "an arc with no frames per step would turn infinitely "
                            "fast", f"{spath}.framesPerStep")
                h = st.entry_heading
                if h is None:
                    r.error("movement.missing_entry_heading",
                            "an arc must state its entry heading: 0..63, or \"CONT\" "
                            "to continue from the heading already held. Leaving it "
                            "out is the old stale-wmPhase bug, where an arc silently "
                            "inherited the wave definition's launch heading",
                            f"{spath}.entryHeading")
                elif h == "CONT":
                    if _first_arc_index(prog) == j:
                        r.warn("movement.leading_cont",
                               "the first arc of this program continues from the "
                               "heading the object already carries, so its path "
                               "depends on the wave definition that launches it and "
                               "it cannot be previewed on its own",
                               f"{spath}.entryHeading")
                elif not _is_int(h) or not (0 <= h < C.WM_HEAD_LEN):
                    r.error("movement.entry_heading",
                            f"an arc's entry heading is a heading 0..{C.WM_HEAD_LEN - 1} "
                            f"or \"CONT\"; got {h!r}", f"{spath}.entryHeading")

    records, pool = p.movement_records, p.movement_bytes
    if records > C.MAX_MOVEMENT_RECORDS:
        r.error("movement.too_many_records",
                f"at most {C.MAX_MOVEMENT_RECORDS} movement records: wmStage is one "
                f"byte; got {records}", "movementPrograms")
    if pool > C.LEVELPKG_MOVE_MAX:
        r.error("movement.pool_overflow",
                f"the movement pool is {pool} bytes, over the "
                f"{C.LEVELPKG_MOVE_MAX}-byte ceiling that wmStage can address",
                "movementPrograms")
    for pid, off in p.movement_offsets().items():
        if off % C.WM_STAGE_SIZE:
            r.error("movement.misaligned",
                    f"program {pid!r} starts at byte {off}, not a multiple of "
                    f"{C.WM_STAGE_SIZE}", "movementPrograms")

    used = {d.movement_program for d in p.wave_definitions}
    for prog in p.movement_programs:
        if prog.id and prog.id not in used:
            r.warn("movement.unused",
                   f"movement program {prog.id!r} is named by no wave definition",
                   "movementPrograms")


def _first_arc_index(prog):
    for j, st in enumerate(prog.stages):
        if st.kind in C.ARC_KINDS:
            return j
    return -1


def _validate_wave_definitions(p, r):
    if len(p.wave_definitions) > C.MAX_WAVE_DEFINITIONS:
        r.error("wavedef.too_many",
                f"at most {C.MAX_WAVE_DEFINITIONS} wave definitions: the director "
                f"forms `def * {C.WAVEDEF_SIZE}` in a single byte, so definition "
                f"{C.MAX_WAVE_DEFINITIONS} could be stored but never read; got "
                f"{len(p.wave_definitions)}", "waveDefinitions")
    prog_ids = {prog.id for prog in p.movement_programs}
    ids = set()
    for i, d in enumerate(p.wave_definitions):
        path = f"waveDefinitions[{i}]"
        if not d.id:
            r.error("wavedef.no_id", "a wave definition needs an id", path)
        elif d.id in ids:
            r.error("wavedef.duplicate_id",
                    f"duplicate wave definition id {d.id!r}", path)
        else:
            ids.add(d.id)
        if d.count < 1:
            r.error("wavedef.count", "a wave definition sends no enemies",
                    f"{path}.count")
        elif d.count > 8:
            r.warn("wavedef.large_count",
                   f"a wave of {d.count} members is larger than anything level 1 "
                   f"authors, and the fire mask addresses only members 0..7",
                   f"{path}.count")
        if d.interval < 1:
            r.error("wavedef.interval",
                    "an interval of zero would spawn the whole wave in one frame",
                    f"{path}.interval")
        if not (0 <= d.start_x <= C.MAX_SPAWN_X):
            r.error("wavedef.start_x",
                    f"startX must be inside the nine-bit X world 0..{C.MAX_SPAWN_X}; "
                    f"got {d.start_x}", f"{path}.startX")
        if not (0 <= d.start_y <= C.MAX_SPAWN_Y):
            r.error("wavedef.start_y",
                    f"startY must fit the eight bits logY carries 0..{C.MAX_SPAWN_Y}; "
                    f"got {d.start_y}", f"{path}.startY")
        if d.count >= 1:
            last_x = d.start_x + d.x_step * (d.count - 1)
            last_y = d.start_y + d.y_step * (d.count - 1)
            if not (0 <= last_x <= C.MAX_SPAWN_X):
                r.error("wavedef.x_step",
                        f"member {d.count - 1} spawns at X {last_x}, outside the "
                        f"nine-bit world", f"{path}.xStep")
            if not (0 <= last_y <= C.MAX_SPAWN_Y):
                r.error("wavedef.y_step",
                        f"member {d.count - 1} spawns at Y {last_y}, outside the "
                        f"eight bits logY carries", f"{path}.yStep")
        if not (0 <= d.colour <= C.MAX_COLOUR):
            r.error("wavedef.colour",
                    f"colour must be 0..{C.MAX_COLOUR}; got {d.colour}",
                    f"{path}.colour")
        if not (0 <= d.heading < C.WM_HEAD_LEN):
            r.error("wavedef.heading",
                    f"launch heading must be 0..{C.WM_HEAD_LEN - 1}; got {d.heading}",
                    f"{path}.heading")
        if d.movement_program not in prog_ids:
            r.error("wavedef.dangling_program",
                    f"names movement program {d.movement_program!r}, which does not "
                    f"exist", f"{path}.movementProgram")
    used = {t.wave_definition for t in p.triggers}
    for i, d in enumerate(p.wave_definitions):
        if d.id and d.id not in used:
            r.warn("wavedef.unused",
                   f"wave definition {d.id!r} is named by no trigger",
                   f"waveDefinitions[{i}]")


def _validate_triggers(p, r):
    ts = p.triggers
    if len(ts) > C.MAX_TRIGGERS:
        r.error("trigger.too_many",
                f"at most {C.MAX_TRIGGERS} triggers: the package reserves "
                f"{C.LEVELPKG_TRIG_COLS} parallel columns of {C.MAX_TRIGGERS}; got "
                f"{len(ts)}", "triggers")
    by_id = {d.id: d for d in p.wave_definitions}
    playable = p.stage.playable_progress if p.stage else 0
    ns = p.stage.no_spawn_row if p.stage else 0

    for i, t in enumerate(ts):
        path = f"triggers[{i}]"
        wp = t.world_progress
        if not (0 <= wp <= C.MAX_WORLD_PROGRESS):
            r.error("trigger.row_range",
                    f"worldProgress must fit sixteen bits 0..{C.MAX_WORLD_PROGRESS}; "
                    f"got {wp}", f"{path}.worldProgress")
        elif wp > playable:
            r.error("trigger.past_stage",
                    f"worldProgress {wp} is past the last row the stage reaches "
                    f"({playable}), so it could never fire",
                    f"{path}.worldProgress")
        elif wp >= ns:
            # `>=` SUPPRESSES in waveTick, so the threshold row itself is forbidden.
            r.error("trigger.at_or_after_no_spawn",
                    f"worldProgress {wp} is at or beyond noSpawnRow {ns} and could "
                    f"never start: the director's gate is `>=`",
                    f"{path}.worldProgress")

        if t.species not in C.SPECIES:
            r.error("trigger.species",
                    f"unknown species {t.species!r}; expected one of "
                    f"{', '.join(sorted(C.SPECIES))}", f"{path}.species")
        if t.dropper_side not in C.DROPPER_SIDES:
            r.error("trigger.side",
                    f"unknown Dropper side {t.dropper_side!r}; expected one of "
                    f"{', '.join(sorted(C.DROPPER_SIDES))}", f"{path}.dropperSide")

        d = by_id.get(t.wave_definition)
        if d is None:
            r.error("trigger.dangling_definition",
                    f"names wave definition {t.wave_definition!r}, which does not "
                    f"exist", f"{path}.waveDefinition")
        for m in t.fire_mask:
            if not _is_int(m) or m < 0:
                r.error("trigger.fire_member",
                        f"a fire mask holds member indices; got {m!r}",
                        f"{path}.fireMask")
            elif m > 7:
                r.error("trigger.fire_width",
                        f"the fire mask is one byte: member {m} cannot be addressed",
                        f"{path}.fireMask")
            elif d is not None and m >= d.count:
                r.error("trigger.fire_member_absent",
                        f"fire mask names member {m}, but wave definition "
                        f"{d.id!r} sends only {d.count}",
                        f"{path}.fireMask")

    rows = [t.world_progress for t in ts]
    for i in range(1, len(rows)):
        if rows[i] < rows[i - 1]:
            # THE CURSOR ONLY WALKS FORWARD. An out-of-order trigger could never
            # become due -- it would be invisible in play rather than a failure.
            r.error("trigger.unsorted",
                    f"trigger rows must be non-decreasing: {rows[i]} follows "
                    f"{rows[i - 1]}", f"triggers[{i}].worldProgress")
            break
    for i in range(1, len(ts)):
        if ts[i].species == ts[i - 1].species and ts[i].species in C.SPECIES:
            r.error("trigger.repeated_species",
                    f"two consecutive authored waves use the same species "
                    f"({ts[i].species}); the engine asserts the alternation",
                    f"triggers[{i}].species")
            break
    # WAVE_SLOTS instances run at once and a third arrival is DROPPED, not queued.
    for i in range(C.WAVE_SLOTS, len(ts)):
        window = rows[i] - rows[i - C.WAVE_SLOTS]
        if _is_int(window) and window <= 1:
            r.warn("trigger.crowded",
                   f"{C.WAVE_SLOTS + 1} triggers fall within {window} coarse row(s); "
                   f"the director runs {C.WAVE_SLOTS} instances and drops the rest",
                   f"triggers[{i}].worldProgress")
            break
    for i, t in enumerate(ts):
        if t.species == "RING" and t.dropper_side != "LEFT":
            r.warn("trigger.side_ignored",
                   "dropperSide is read only for a DROPPER wave; a RING wave "
                   "carries it and ignores it", f"triggers[{i}].dropperSide")


def _capacity(p, r):
    stage = p.stage
    rows = stage.metatile_rows if stage else 0
    r.capacity.update({
        "metatileRows": (rows, C.MAX_METATILE_ROWS),
        "mapBytes": (rows * C.METATILES_PER_ROW, C.LEVELPKG_MAP_MAX),
        "metatileDefs": (len(p.metatile_defs), C.MAX_METATILE_DEFS),
        "metatileDefBytes": (len(p.metatile_defs) * 16, C.LEVELPKG_DEFS_MAX),
        "glyphs": (len(p.glyphs), C.MAX_TERRAIN_GLYPHS),
        "turrets": (len(p.turrets), C.MAX_TURRETS),
        "movementRecords": (p.movement_records, C.MAX_MOVEMENT_RECORDS),
        "movementBytes": (p.movement_bytes, C.LEVELPKG_MOVE_MAX),
        "waveDefinitions": (len(p.wave_definitions), C.MAX_WAVE_DEFINITIONS),
        "triggers": (len(p.triggers), C.MAX_TRIGGERS),
    })
    if stage:
        r.capacity.update({
            "logicalRows": stage.logical_rows,
            "playableProgress": stage.playable_progress,
            "playableFrames": stage.playable_frames,
            "terrainSeconds": round(stage.terrain_seconds, 2),
            "quietZoneRows": stage.playable_progress - stage.no_spawn_row,
        })
