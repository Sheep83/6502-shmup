"""The v6 level-project model: Engine ↔ Editor Contract v2.

NO TKINTER, NO GUI, NO ASSEMBLER. This module is the data model and its JSON
form, and nothing else, so that it can be unit-tested without a display and
reused by the Phase 2 exporter without dragging the editor in behind it.

WHAT CHANGED FROM v5, AND WHY IT IS A NEW VERSION RATHER THAN A FIELD OR TWO.
v5 described an engine that no longer exists. Terrain was assembled into the
engine PRG; it is now a separately loaded package at $e000. Encounters were a
curated "attack catalogue" of twelve ids; they are now movement programs, ten-byte
wave definitions and six-column absolute triggers. And v5's trigger rows ran in
the OPPOSITE DIRECTION to the engine's: it authored a stage row counting down,
the engine consumes worldProgress counting up. Those are not adjustments.

ONE AUTHORITATIVE VALUE PER FACT. Row counts, byte budgets and durations are
DERIVED (see contract_v2) and never stored, so a project cannot carry three
copies of its own height and disagree with itself. In particular v5's `width`,
`height` and `scrollFrameDivider` do not survive into v6 output:
`scrollFrameDivider` was read by nothing in the engine at all.

See /reports/level-editor-contract-v2-specification.md §14.
"""
from dataclasses import dataclass, field, replace
import json
from pathlib import Path

import contract_v2 as C

FORMAT_VERSION = 6


class ProjectV6Error(ValueError):
    """Malformed input that cannot even be loaded into the model.

    DELIBERATELY RARE. The model is meant to load projects that are WRONG so the
    editor can show a user what is wrong with them; contract breaches are
    validation errors, not exceptions. This is only for input whose SHAPE makes a
    model impossible -- a map that is not a list, a stage that is not an object.
    """


# ===========================================================================
# Movement
# ===========================================================================
@dataclass
class MovementStage:
    """One four-byte movement record, in human-readable form.

    The three shapes carry different payloads because the engine's bytes 2 and 3
    mean different things to different primitives -- an arc has no use for a
    velocity and a straight leg has no use for a step length:

        STRAIGHT / HOLD   frames, vx, vy          (vx/vy are QUARTER pixels/frame)
        ARC / ARC_MIRROR  steps, frames_per_step, entry_heading
        EXIT              nothing
    """
    kind: str
    frames: int = 0
    vx: int = 0
    vy: int = 0
    steps: int = 0
    frames_per_step: int = C.WM_STAGE_SIZE
    entry_heading: object = None        # int 0..63, or the string "CONT"

    def to_dict(self):
        if self.kind in C.TIMED_KINDS:
            return {"kind": self.kind, "frames": self.frames,
                    "vx": self.vx, "vy": self.vy}
        if self.kind in C.ARC_KINDS:
            return {"kind": self.kind, "steps": self.steps,
                    "framesPerStep": self.frames_per_step,
                    "entryHeading": self.entry_heading}
        return {"kind": self.kind}

    @staticmethod
    def from_dict(raw, path):
        if not isinstance(raw, dict):
            raise ProjectV6Error(f"{path} must be an object")
        kind = raw.get("kind")
        return MovementStage(
            kind=kind if isinstance(kind, str) else str(kind),
            frames=_int_or_zero(raw.get("frames")),
            vx=_int_or_zero(raw.get("vx")),
            vy=_int_or_zero(raw.get("vy")),
            steps=_int_or_zero(raw.get("steps")),
            # The DEFAULT MATTERS: WM_ARC_STEP is 4 in the engine, and a stage
            # authored without one is a wide sweep rather than an error.
            frames_per_step=_int_or_zero(raw.get("framesPerStep"), C.WM_STAGE_SIZE),
            # NOT DEFAULTED. A missing arc entry heading is exactly the old
            # stale-wmPhase bug -- the arc silently inheriting the wave's launch
            # heading -- so it stays None and validation rejects it by name.
            entry_heading=raw.get("entryHeading", None),
        )


@dataclass
class MovementProgram:
    id: str
    stages: list = field(default_factory=list)

    @property
    def record_count(self):
        return len(self.stages)

    @property
    def byte_length(self):
        return len(self.stages) * C.WM_STAGE_SIZE

    def to_dict(self):
        return {"id": self.id, "stages": [s.to_dict() for s in self.stages]}

    @staticmethod
    def from_dict(raw, path):
        if not isinstance(raw, dict):
            raise ProjectV6Error(f"{path} must be an object")
        stages = raw.get("stages") or []
        if not isinstance(stages, list):
            raise ProjectV6Error(f"{path}.stages must be a list")
        return MovementProgram(
            id=str(raw.get("id", "")),
            stages=[MovementStage.from_dict(s, f"{path}.stages[{i}]")
                    for i, s in enumerate(stages)],
        )


# ===========================================================================
# Wave definitions
# ===========================================================================
@dataclass
class WaveDefinition:
    """A reusable template, matching the engine's ten-byte record field for field.

    REUSABLE IS THE POINT. Several triggers may name the same definition; the
    things that vary between appearances -- species, fire mask, Dropper side --
    live on the TRIGGER, not here. Level 1 happens to use one definition per
    trigger, but that is content rather than a rule.

    `movement_program` is an ID here and a BYTE OFFSET in the package. The
    exporter resolves it, which is what stops an offset disagreeing with the
    records it points at.
    """
    id: str
    count: int = 1
    interval: int = 1
    start_x: int = 0
    start_y: int = 0
    x_step: int = 0
    y_step: int = 0
    colour: int = 1
    heading: int = 0
    movement_program: str = ""

    def to_dict(self):
        return {"id": self.id, "count": self.count, "interval": self.interval,
                "startX": self.start_x, "startY": self.start_y,
                "xStep": self.x_step, "yStep": self.y_step,
                "colour": self.colour, "heading": self.heading,
                "movementProgram": self.movement_program}

    @staticmethod
    def from_dict(raw, path):
        if not isinstance(raw, dict):
            raise ProjectV6Error(f"{path} must be an object")
        return WaveDefinition(
            id=str(raw.get("id", "")),
            count=_int_or_zero(raw.get("count")),
            interval=_int_or_zero(raw.get("interval")),
            start_x=_int_or_zero(raw.get("startX")),
            start_y=_int_or_zero(raw.get("startY")),
            x_step=_int_or_zero(raw.get("xStep")),
            y_step=_int_or_zero(raw.get("yStep")),
            colour=_int_or_zero(raw.get("colour")),
            heading=_int_or_zero(raw.get("heading")),
            movement_program=str(raw.get("movementProgram", "")),
        )


# ===========================================================================
# Triggers
# ===========================================================================
@dataclass
class Trigger:
    """One authored moment: six engine columns, in words rather than numbers.

    `world_progress` IS worldProgress -- coarse rows travelled since the stage
    started, counting UP from zero, sixteen bits. It is NOT a map row. v5 stored
    a map row counting down and the two are mirror images of each other; see
    migration_v6.legacy_trigger_progress.

    `fire_mask` is a list of MEMBER INDICES rather than a bitmask integer, because
    "members 0 and 2 shoot" is what an author means and %00000101 is what the
    machine wants. Loading accepts either.
    """
    world_progress: int
    wave_definition: str
    species: str = "RING"
    fire_mask: list = field(default_factory=list)
    dropper_side: str = "LEFT"

    @property
    def fire_bits(self):
        bits = 0
        for m in self.fire_mask:
            if isinstance(m, int) and 0 <= m < 8:
                bits |= 1 << m
        return bits

    def to_dict(self):
        return {"worldProgress": self.world_progress,
                "waveDefinition": self.wave_definition,
                "species": self.species,
                "fireMask": list(self.fire_mask),
                "dropperSide": self.dropper_side}

    @staticmethod
    def from_dict(raw, path):
        if not isinstance(raw, dict):
            raise ProjectV6Error(f"{path} must be an object")
        return Trigger(
            world_progress=_int_or_zero(raw.get("worldProgress")),
            wave_definition=str(raw.get("waveDefinition", "")),
            species=str(raw.get("species", "RING")),
            fire_mask=_fire_mask(raw.get("fireMask")),
            dropper_side=str(raw.get("dropperSide", "LEFT")),
        )


def _fire_mask(raw):
    """Accept a member-index list or a legacy integer bitmask; store the list."""
    if raw is None:
        return []
    if isinstance(raw, bool):
        return []
    if isinstance(raw, int):
        return [m for m in range(8) if raw & (1 << m)]
    if isinstance(raw, list):
        out = []
        for m in raw:
            if isinstance(m, bool) or not isinstance(m, int):
                out.append(m)                   # kept, so validation can name it
            elif m not in out:
                out.append(m)
        return sorted(out, key=lambda v: (not isinstance(v, int), v
                                          if isinstance(v, int) else str(v)))
    return []


# ===========================================================================
# Stage, palette, turret
# ===========================================================================
@dataclass
class Stage:
    """Height and the boss approach. Width is FIXED and therefore not stored.

    `METATILES_PER_ROW * METATILE_W == SCREEN_COLS` is an engine build guard, so
    10 is not a project setting; it is emitted on save for readability and
    checked on load.
    """
    metatile_rows: int
    no_spawn_row: int

    @property
    def metatile_cols(self):
        return C.METATILES_PER_ROW

    @property
    def logical_rows(self):
        return C.logical_rows(self.metatile_rows)

    @property
    def playable_progress(self):
        return C.playable_progress(self.metatile_rows)

    @property
    def playable_frames(self):
        return C.playable_frames(self.metatile_rows)

    @property
    def terrain_seconds(self):
        return C.terrain_seconds(self.metatile_rows)

    def to_dict(self):
        return {"metatileRows": self.metatile_rows,
                "metatileCols": C.METATILES_PER_ROW,
                "noSpawnRow": self.no_spawn_row}


@dataclass
class Palette:
    background: int = 0
    multicolour1: int = 12
    multicolour2: int = 15
    character: int = 1

    def to_dict(self):
        return {"background": self.background,
                "multicolour1": self.multicolour1,
                "multicolour2": self.multicolour2,
                "character": self.character}


@dataclass
class Turret:
    """Editor-space placement. The engine's world row/col are DERIVED."""
    metatile_row: int
    metatile_col: int

    @property
    def world_row(self):
        return C.turret_world_row(self.metatile_row)

    @property
    def world_col(self):
        return C.turret_world_col(self.metatile_col)

    def to_dict(self):
        return {"metatileRow": self.metatile_row,
                "metatileCol": self.metatile_col}


# ===========================================================================
# The project
# ===========================================================================
@dataclass
class ProjectV6:
    name: str = "level"
    stage: Stage = None
    palette: Palette = field(default_factory=Palette)
    glyphs: list = field(default_factory=list)          # list of 8-byte lists
    metatile_defs: list = field(default_factory=list)   # list of 16-code lists
    level_metatile_set: object = None                   # opaque native source
    map_rows: list = field(default_factory=list)        # rows x 10 metatile IDs
    turrets: list = field(default_factory=list)
    movement_programs: list = field(default_factory=list)
    wave_definitions: list = field(default_factory=list)
    triggers: list = field(default_factory=list)

    # ---- derived movement-pool geometry --------------------------------
    @property
    def movement_records(self):
        return sum(p.record_count for p in self.movement_programs)

    @property
    def movement_bytes(self):
        return self.movement_records * C.WM_STAGE_SIZE

    def movement_offsets(self):
        """Byte offset of each program's first record, keyed by ID.

        Computed, never authored: a hand-maintained offset is a number that is
        right until somebody inserts a stage. Mirrors `progAt` in
        src/wave_programs.asm.
        """
        out, at = {}, 0
        for p in self.movement_programs:
            out[p.id] = at
            at += p.byte_length
        return out

    # ---- JSON ----------------------------------------------------------
    def to_dict(self):
        """Canonical v6 dictionary. FIELD ORDER IS PART OF THE CONTRACT."""
        data = {
            "formatVersion": FORMAT_VERSION,
            "name": self.name,
            "stage": self.stage.to_dict(),
            "palette": self.palette.to_dict(),
            "glyphs": {"count": len(self.glyphs),
                       "bitmaps": [list(g) for g in self.glyphs]},
            "metatileDefs": [list(d) for d in self.metatile_defs],
            "map": [list(r) for r in self.map_rows],
            # Turrets are canonicalised by position so that two projects with the
            # same placements save identically whatever order they were drawn in.
            "turrets": [t.to_dict() for t in sorted(
                self.turrets, key=lambda t: (t.metatile_row, t.metatile_col))],
            "movementPrograms": [p.to_dict() for p in self.movement_programs],
            "waveDefinitions": [d.to_dict() for d in self.wave_definitions],
            # TRIGGERS ARE NOT SORTED HERE. The engine requires non-decreasing
            # rows and a violation is a VALIDATION ERROR the author must see --
            # quietly sorting on save would hide it and make the rule untestable.
            "triggers": [t.to_dict() for t in self.triggers],
        }
        if self.level_metatile_set is not None:
            data["levelMetatileSet"] = self.level_metatile_set
        return data

    def to_json(self):
        """Deterministic text: stable order, 2-space indent, LF, trailing newline."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def save(self, path):
        Path(path).write_text(self.to_json(), encoding="utf-8", newline="\n")

    @staticmethod
    def from_dict(data):
        if not isinstance(data, dict):
            raise ProjectV6Error("a project must be a JSON object")
        version = data.get("formatVersion")
        if version != FORMAT_VERSION:
            raise ProjectV6Error(
                f"ProjectV6.from_dict expects formatVersion {FORMAT_VERSION}; "
                f"got {version!r}. Use migration_v6.load_any() for older files.")

        raw_stage = data.get("stage")
        if not isinstance(raw_stage, dict):
            raise ProjectV6Error("stage must be an object")
        stage = Stage(metatile_rows=_int_or_zero(raw_stage.get("metatileRows")),
                      no_spawn_row=_int_or_zero(raw_stage.get("noSpawnRow")))
        # metatileCols is echoed for readability; it is fixed by the engine, so a
        # disagreement is recorded as a validation error rather than honoured.
        stage_cols = raw_stage.get("metatileCols", C.METATILES_PER_ROW)

        raw_pal = data.get("palette") or {}
        if not isinstance(raw_pal, dict):
            raise ProjectV6Error("palette must be an object")
        palette = Palette(background=_int_or_zero(raw_pal.get("background")),
                          multicolour1=_int_or_zero(raw_pal.get("multicolour1")),
                          multicolour2=_int_or_zero(raw_pal.get("multicolour2")),
                          character=_int_or_zero(raw_pal.get("character")))

        raw_glyphs = data.get("glyphs") or {}
        bitmaps = raw_glyphs.get("bitmaps") if isinstance(raw_glyphs, dict) else None
        glyphs = [list(g) if isinstance(g, list) else g for g in (bitmaps or [])]

        defs = data.get("metatileDefs") or []
        rows = data.get("map") or []
        if not isinstance(defs, list) or not isinstance(rows, list):
            raise ProjectV6Error("metatileDefs and map must be lists")

        turrets = []
        for i, t in enumerate(data.get("turrets") or []):
            if not isinstance(t, dict):
                raise ProjectV6Error(f"turrets[{i}] must be an object")
            turrets.append(Turret(_int_or_zero(t.get("metatileRow")),
                                  _int_or_zero(t.get("metatileCol"))))

        project = ProjectV6(
            name=str(data.get("name", "level")),
            stage=stage,
            palette=palette,
            glyphs=glyphs,
            metatile_defs=[list(d) if isinstance(d, list) else d for d in defs],
            level_metatile_set=data.get("levelMetatileSet"),
            map_rows=[list(r) if isinstance(r, list) else r for r in rows],
            turrets=turrets,
            movement_programs=[
                MovementProgram.from_dict(p, f"movementPrograms[{i}]")
                for i, p in enumerate(data.get("movementPrograms") or [])],
            wave_definitions=[
                WaveDefinition.from_dict(d, f"waveDefinitions[{i}]")
                for i, d in enumerate(data.get("waveDefinitions") or [])],
            triggers=[Trigger.from_dict(t, f"triggers[{i}]")
                      for i, t in enumerate(data.get("triggers") or [])],
        )
        project.declared_metatile_cols = stage_cols
        return project

    @staticmethod
    def from_json(text):
        return ProjectV6.from_dict(json.loads(text))

    @staticmethod
    def load(path):
        return ProjectV6.from_json(Path(path).read_text(encoding="utf-8"))

    def copy(self):
        return ProjectV6.from_dict(json.loads(json.dumps(self.to_dict())))


def _int_or_zero(value, default=0):
    """Coerce for the MODEL only; range and type faults are validation's job.

    A bool is not an int here: JSON `true` in a numeric field is an authoring
    mistake worth reporting, not a 1 to be quietly accepted.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value
