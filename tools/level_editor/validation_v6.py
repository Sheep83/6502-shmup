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
import re

import contract_v2 as C
# IMPORTED LAZILY INSIDE THE RULE, not here: movement_semantic imports
# movement_sim, and the validator must stay importable by anything that
# only wants to check a project's shape.
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


# AN AUTHORED ID BECOMES AN ASSEMBLER LABEL. A wave definition called "loop x 5"
# is a perfectly good name and an impossible symbol: the exporter would have to
# emit `.const WAVE_DEF_LOOP X 5`, which does not assemble. The rule was already
# enforced at export time, which meant an author could name a definition, work on
# it, and only discover the problem when the whole package refused to write. It
# is a validation rule now, so the panel and the rename dialog say so first.
SYMBOL_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _check_id(r, kind, code, ident, path):
    """Every id that becomes an assembler symbol must survive becoming one."""
    if not ident:
        r.error(f"{code}.no_id", f"a {kind} needs an id", path)
        return False
    if not SYMBOL_ID.match(ident):
        r.error(f"{code}.bad_id",
                f"{kind} id {ident!r} cannot become an assembler symbol. Use "
                f"lower-case letters, digits and underscores, starting with a "
                f"letter -- for example loop_x5, sweep_right, dive2",
                path)
        return False
    return True


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
        if not _check_id(r, "movement program", "movement", prog.id, path):
            pass
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

    # ---- an unfinished draft is not a shippable program (Phase 6B.1) -----
    # THE STRICT HALF OF THE DRAFT/PRODUCTION SPLIT. The editor lets an author
    # build a program a segment at a time, and the preview flies whatever
    # prefix compiles -- which is what makes progressive authoring possible.
    # This is where that tolerance stops: a semantic program must compile IN
    # FULL to be saved or exported.
    #
    # ASKED OF THE SEGMENTS, NOT THE RECORDS, and that distinction is
    # load-bearing. A draft's stored records are the compiled PREFIX, so a
    # malformed segment is simply absent from them -- checking records alone
    # would call the program clean and then Save would quietly ship it with
    # the author's unfinished work dropped on the floor.
    for prog in p.movement_programs:
        if not prog.segments:
            continue
        heading = next((d.heading for d in p.wave_definitions
                        if d.movement_program == prog.id), 0)
        try:
            import movement_semantic
            movement_semantic.compile_segments(prog.segments, heading)
        except Exception as exc:                # noqa: BLE001
            r.error("movement.unfinished",
                    f"movement program {prog.id!r} is not finished: {exc}",
                    f"movementPrograms[{prog.id}].segments")

    # ---- trajectory continuity (Phase 6B) --------------------------------
    # A WARNING, NOT AN ERROR: the engine runs a kinked path perfectly well
    # and `linger` has shipped with one since before this rule existed, so
    # erroring would condemn working content. But an instantaneous direction
    # change is almost never what an author meant, and it is invisible in the
    # records -- it only shows up when the path is flown.
    #
    # WHY IT HAPPENS: WM_STRAIGHT and WM_HOLD write a velocity and never touch
    # wmPhase (src/movement_format.asm says so), so a leg that does not travel
    # along the stored heading leaves the two disagreeing -- and an arc
    # entering on "CONT" then snaps to the stale heading. Programs authored as
    # SEMANTIC SEGMENTS cannot do this; raw records can.
    _launch = {}
    for d in p.wave_definitions:
        _launch.setdefault(d.movement_program, d.heading)
    for prog in p.movement_programs:
        if not prog.stages or prog.stages[-1].kind != "EXIT":
            continue                    # already an error above; do not fly it
        try:
            import movement_semantic
            breaks = movement_semantic.continuity_breaks(
                prog.stages, _launch.get(prog.id, 0))
        except Exception:               # noqa: BLE001 -- never block validation
            continue
        for b in breaks:
            # TWO SHAPES, AND THEY WANT DIFFERENT ADVICE. An arc that snapped
            # is the stale-wmPhase case and has a one-byte fix; a straight or
            # hold that snapped is simply pointing somewhere else, and only
            # the author knows whether that was meant.
            if b["to_kind"] in C.ARC_KINDS:
                fix = (f"the arc continued from the stored heading "
                       f"{b['stored_heading']}, which is not the way it was "
                       f"travelling (heading {b['travel_heading']}) -- a "
                       f"straight or a hold sets a velocity without updating "
                       f"the heading. Entering it on heading "
                       f"{b['travel_heading']} instead would make it "
                       f"continuous.")
            else:
                fix = (f"it was travelling {b['was']} and this stage sets "
                       f"{b['now']}, which points elsewhere. Authoring the "
                       f"program as semantic segments would keep it "
                       f"continuous.")
            r.warn("movement.discontinuity",
                   f"program {prog.id!r} changes direction by "
                   f"{b['degrees']:.0f} degrees at stage {b['stage']} "
                   f"({b['from_kind']} -> {b['to_kind']}): {fix}",
                   f"movementPrograms[{prog.id}].stages[{b['stage']}]")

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
        if not _check_id(r, "wave definition", "wavedef", d.id, path):
            pass
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
            # EVERY MEMBER MUST BE BORN OUT OF SIGHT, which src/waves.asm proves
            # at assembly time -- so without this the first sign of a bad spawn
            # was KickAssembler refusing the whole build, long after the field
            # that caused it. Checked per member because xStep/yStep walk the
            # later ones somewhere the first one never goes.
            for m in range(d.count):
                mx = d.start_x + d.x_step * m
                my = d.start_y + d.y_step * m
                if not (0 <= mx <= C.MAX_SPAWN_X and 0 <= my <= C.MAX_SPAWN_Y):
                    continue            # reported by the range checks below
                if not C.spawn_is_hidden(mx, my):
                    r.error("wavedef.spawn_visible",
                            f"wave {d.id!r} member {m} spawns at ({mx},{my}), "
                            f"partially inside the visible playfield: a sprite "
                            f"covers x..x+{C.SPRITE_LAST_COLUMN} and y..y+"
                            f"{C.SPRITE_HEIGHT - 1}, and the playfield is columns "
                            f"{C.DISPLAY_X_FIRST}..{C.DISPLAY_X_LAST} from raster "
                            f"{C.APERTURE_TOP_RASTER}. Move it above the aperture "
                            f"(y <= {C.APERTURE_TOP_RASTER - C.SPRITE_HEIGHT}), "
                            f"off the left (x = 0) or off the right "
                            f"(x > {C.DISPLAY_X_LAST})",
                            f"{path}.member[{m}]")
                    break               # one report per definition is enough
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
    # CONSECUTIVE TRIGGERS MAY SHARE A SPECIES. This used to be an error because
    # src/waves.asm asserted the alternation at assembly time; that assertion was
    # about Level 1's content, not about runtime safety, and it has been removed.
    # A second Dropper arriving while one is alive is substituted with a Ring by
    # the engine and still flies its authored path -- proved on the machine by
    # tests/test_species_order.py -- so any order is legal to author.
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
