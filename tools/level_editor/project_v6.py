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
    """A named path, in one or both of two forms.

    `stages` IS ALWAYS THE TRUTH THE ENGINE RUNS. The exporter, the validator
    and the faithful simulator read it and nothing else, so nothing downstream
    of this class had to learn a new idea in Phase 6B.

    `segments` is OPTIONAL and is what the designer actually wrote (Phase 6B,
    tools/level_editor/movement_semantic.py). When it is present it is the
    SOURCE and `stages` is its deterministic compilation, rewritten on every
    semantic edit; when it is absent the program is RAW and its records are
    left exactly as they were found. That is what lets a project mix the two
    and what keeps a project authored before Phase 6B byte-identical:
    `to_dict` emits the key only when there is something to emit.

    THE SEGMENTS ARE THE ASSET; THE STAGES ARE A CACHE. A movement program is
    meant to be reusable across stages, and its semantic form is what would
    travel. The records are the compilation of it against ONE launch heading,
    which is a per-use resolution rather than a property of the program -- so
    when programs become a project-level encounter library, `segments` is what
    moves and `stages` is what the exporter regenerates for each stage that
    references it. Nothing here assumes a program belongs to one stage.
    """
    id: str
    stages: list = field(default_factory=list)
    segments: list = field(default_factory=list)

    @property
    def record_count(self):
        return len(self.stages)

    @property
    def byte_length(self):
        return len(self.stages) * C.WM_STAGE_SIZE

    @property
    def is_semantic(self):
        return bool(self.segments)

    def to_dict(self):
        d = {"id": self.id, "stages": [s.to_dict() for s in self.stages]}
        if self.segments:
            d["segments"] = [s.to_dict() for s in self.segments]
        return d

    @staticmethod
    def from_dict(raw, path):
        if not isinstance(raw, dict):
            raise ProjectV6Error(f"{path} must be an object")
        stages = raw.get("stages") or []
        if not isinstance(stages, list):
            raise ProjectV6Error(f"{path}.stages must be a list")
        segments = raw.get("segments") or []
        if not isinstance(segments, list):
            raise ProjectV6Error(f"{path}.segments must be a list")
        # IMPORTED LAZILY. movement_semantic imports movement_sim, which
        # imports this module; the authored-data model must not depend on the
        # simulator to be loadable.
        from movement_semantic import Segment
        return MovementProgram(
            id=str(raw.get("id", "")),
            stages=[MovementStage.from_dict(s, f"{path}.stages[{i}]")
                    for i, s in enumerate(stages)],
            segments=[Segment.from_dict(s, f"{path}.segments[{i}]")
                      for i, s in enumerate(segments)],
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
    heading: int = 0
    movement_program: str = ""

    # ---- NOT AUTHORING DATA. Migration input only. -----------------------
    # A DEFINITION NO LONGER OWNS A COLOUR OR A FIRING MODE. It used to own the
    # colour, the Fixed/Random mode and how its enemies aimed, which made the
    # same reusable formation identically coloured and identically armed
    # everywhere it was used; all three now live on the TRIGGER. These fields
    # exist so that opening a project written before those moves can carry the
    # author's choices onto the triggers that reference it -- see
    # resolve_trigger_encounter_fields -- and for nothing else.
    #
    # THEY ARE NOT EMITTED BY to_dict, which is what removes the obsolete
    # ownership from disk the first time a migrated project is saved. Because
    # to_dict drops them, a to_dict/from_dict copy would drop them too, so the
    # library copies definitions with `copy()` below instead.
    legacy_colour: int = None
    legacy_colour_mode: str = None
    legacy_fire_mode: str = None

    def copy(self):
        """A real copy, migration fields included.

        The library used to duplicate definitions by round-tripping them
        through to_dict, which is exactly the thing that cannot carry a field
        to_dict deliberately omits.
        """
        return replace(self)

    def to_dict(self):
        return {"id": self.id, "count": self.count, "interval": self.interval,
                "startX": self.start_x, "startY": self.start_y,
                "xStep": self.x_step, "yStep": self.y_step,
                "heading": self.heading,
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
            y_step=_int_or_zero(raw.get("yStep")),
            x_step=_int_or_zero(raw.get("xStep")),
            heading=_int_or_zero(raw.get("heading")),
            movement_program=str(raw.get("movementProgram", "")),
            # READ, NEVER WRITTEN BACK. Whatever colour or firing ownership this
            # file still carries is picked up here so the triggers can inherit
            # it, and is gone from the document the next time it is saved.
            legacy_fire_mode=(str(raw["fireMode"])
                              if "fireMode" in raw else None),
            legacy_colour=(_int_or_zero(raw["colour"])
                           if "colour" in raw else None),
            legacy_colour_mode=(str(raw["colourMode"])
                                if "colourMode" in raw else None),
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
    # A ROSTER IDENTITY, not one of the three legacy species names. Ring 3 is
    # the successor to the Sonic Ring artwork, so a trigger built with no
    # species still means what it used to mean.
    species: str = "RING_3"
    fire_mask: list = field(default_factory=list)
    dropper_side: str = "LEFT"

    # ---- how THIS appearance is coloured ---------------------------------
    # OWNED HERE, NOT BY THE DEFINITION. Two triggers may play the same
    # reusable `sweep` and arrive cyan, yellow and mixed; changing one must not
    # touch the others. See contract_v2.COLOUR_MODES.
    #
    # None MEANS "NOT AUTHORED YET", not "black". A project written before
    # colour moved here says nothing about it, and the answer has to come from
    # the wave definition it references -- which is not visible from inside a
    # single trigger. resolve_trigger_encounter_fields fills them in once the
    # document and its vocabulary are both loaded; until then the resolved_*
    # properties below stand in, so nothing downstream ever sees a None.
    colour: int = None
    colour_mode: str = None

    # ---- ...and how it attacks -------------------------------------------
    # OWNED HERE TOO, and by the same argument: the same `sweep` should be
    # usable silent at one row and aimed at another. `fire_mask` beside it says
    # WHICH members shoot; this says HOW the ones that do aim. None means "not
    # authored yet", exactly as above.
    fire_mode: str = None

    @property
    def resolved_colour(self):
        return C.DEFAULT_TRIGGER_COLOUR if self.colour is None else self.colour

    @property
    def resolved_colour_mode(self):
        return "FIXED" if self.colour_mode is None else self.colour_mode

    @property
    def resolved_fire_mode(self):
        return "DOWN" if self.fire_mode is None else self.fire_mode

    @property
    def fire_bits(self):
        bits = 0
        for m in self.fire_mask:
            if isinstance(m, int) and 0 <= m < 8:
                bits |= 1 << m
        return bits

    def to_dict(self):
        # THE RESOLVED VALUES, always concrete. Saving a document is the point
        # at which the migration becomes permanent: whatever the trigger
        # inherited from its definition is written here as the trigger's own.
        return {"worldProgress": self.world_progress,
                "waveDefinition": self.wave_definition,
                "species": self.species,
                "fireMask": list(self.fire_mask),
                "dropperSide": self.dropper_side,
                "colour": self.resolved_colour,
                "colourMode": self.resolved_colour_mode,
                "fireMode": self.resolved_fire_mode}

    @staticmethod
    def from_dict(raw, path, slots=None):
        if not isinstance(raw, dict):
            raise ProjectV6Error(f"{path} must be an object")
        slots = slots or list(C.DEFAULT_ENEMY_IDENTITIES)
        return Trigger(
            world_progress=_int_or_zero(raw.get("worldProgress")),
            wave_definition=str(raw.get("waveDefinition", "")),
            species=_trigger_identity(raw.get("species", "RING"), slots),
            fire_mask=_fire_mask(raw.get("fireMask")),
            dropper_side=str(raw.get("dropperSide", "LEFT")),
            # ABSENT MEANS "ASK THE DEFINITION", not "use a default". The two
            # are different: a pre-migration project really does have an
            # authored colour, it is just recorded in the wrong place.
            colour=(_int_or_zero(raw["colour"]) if "colour" in raw else None),
            colour_mode=(str(raw["colourMode"])
                         if "colourMode" in raw else None),
            fire_mode=(str(raw["fireMode"]) if "fireMode" in raw else None),
        )


def resolve_trigger_encounter_fields(project):
    """Give every trigger its own colour and firing mode, inheriting once.

    THE ONE-WAY MOVE FROM DEFINITION OWNERSHIP TO TRIGGER OWNERSHIP, and the
    only place it happens. A project written before the move records colour,
    Fixed/Random and the firing mode on the wave definition; a trigger that
    says nothing about them therefore means "whatever my definition said", and
    this copies those answers onto it. Afterwards, changing one trigger cannot
    affect another using the same definition, because they no longer share a
    value.

    IT IS DELIBERATELY NOT A RESET TO DEFAULTS. A definition currently set to
    Random, or to AIMED, migrates its triggers to Random and to AIMED.
    Migration preserves what was authored; it does not have an opinion about
    it. That matters here: Level 1 was left with most definitions on Random
    after the colour visual test, and `sweep` has been AIMED since aimed fire
    was added.

    THE FIRE MASK IS NOT TOUCHED. It was already a trigger field and already
    says which members shoot; only HOW they aim is arriving.

    IDEMPOTENT, and it has to be: it runs on every load path, and a document
    may be loaded before its vocabulary is attached and again afterwards. A
    trigger that already has a value is never overwritten.

    IT DOES NOTHING WHEN THERE IS NO VOCABULARY TO ASK. The controller loads a
    document first and installs the shared library second, so resolving against
    an empty definition list would answer every question with the default
    before the real answer had arrived. Returns the triggers it resolved.
    """
    by_id = {d.id: d for d in project.wave_definitions}
    if not by_id:
        return []
    done = []
    for t in project.triggers:
        if (t.colour is not None and t.colour_mode is not None
                and t.fire_mode is not None):
            continue
        source = by_id.get(t.wave_definition)
        if source is None:
            continue            # dangling; validation reports it by name
        if t.colour is None:
            t.colour = (C.DEFAULT_TRIGGER_COLOUR if source.legacy_colour is None
                        else source.legacy_colour)
        if t.colour_mode is None:
            t.colour_mode = (source.legacy_colour_mode
                             if source.legacy_colour_mode in C.COLOUR_MODES
                             else "FIXED")
        if t.fire_mode is None:
            t.fire_mode = (source.legacy_fire_mode
                           if source.legacy_fire_mode in C.FIRE_MODES
                           else "DOWN")
        done.append(t)
    return done


# The name this was called while colour was the only field that had moved.
# Kept so an external caller does not break on the rename.
resolve_trigger_colours = resolve_trigger_encounter_fields


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
def _trigger_identity(value, slots):
    """A trigger's enemy, as an IDENTITY name.

    Old projects name one of the three legacy species -- RING, DROPPER, SQUARE.
    Those were never really three enemies; they were three SLOTS. So a legacy
    name migrates to whichever identity this level put in that slot, which is
    exactly what the level was already drawing. Nothing changes on screen; the
    trigger simply now says what it always meant.
    """
    name = str(value)
    if name in C.LEGACY_SPECIES_ORDER:
        return slots[C.LEGACY_SPECIES_ORDER.index(name)]
    return name


def _enemy_slots_from(data):
    """This level's three identities, from whichever schema the file uses.

    THREE GENERATIONS, ALL READ WITHOUT GUESSING:
      * `enemySlots`  -- the current list, in slot order;
      * `enemyArt`    -- the interim {legacySpecies: rosterName} map, which the
                         variable-frame pass wrote;
      * neither       -- a project older than both, which meant Ring, Dropper
                         and Square; Ring 3 is the successor to the Sonic Ring
                         artwork the SpritePad project retired.
    """
    slots = data.get("enemySlots")
    if isinstance(slots, list) and slots:
        out = [str(x) for x in slots[:C.ENEMY_SLOTS]]
    else:
        art = data.get("enemyArt") or {}
        out = [str(art.get(sp, C.DEFAULT_ENEMY_IDENTITIES[i]))
               for i, sp in enumerate(C.LEGACY_SPECIES_ORDER)]
    while len(out) < C.ENEMY_SLOTS:
        out.append(C.DEFAULT_ENEMY_IDENTITIES[len(out)])
    return out


@dataclass
class ProjectV6:
    name: str = "level"
    stage: Stage = None
    palette: Palette = field(default_factory=Palette)
    glyphs: list = field(default_factory=list)          # list of 8-byte lists
    metatile_defs: list = field(default_factory=list)   # list of 16-code lists
    level_metatile_set: object = None                   # opaque native source
    map_rows: list = field(default_factory=list)        # rows x 10 metatile IDs
    # TRUE once the shared library has been installed onto this project. It is
    # what stops a save writing the vocabulary back into the level file: a
    # document that was given the shared set has no business persisting a
    # second copy of it. Not serialised -- it describes where the in-memory
    # lists came from, not anything about the document on disk.
    shared_vocabulary: bool = field(default=False, compare=False, repr=False)
    # The vocabulary exactly as the library handed it over, or None. save()
    # compares against it to tell "nothing to lose" from "about to lose work".
    attached_vocabulary: object = field(default=None, compare=False, repr=False)
    # THE THREE ENEMY IDENTITIES THIS LEVEL HOLDS, in slot order. Slot 0 is
    # the engine's species row 0, slot 1 is row 8, slot 2 is row 16. A trigger
    # names one of these identities and the exporter resolves it to its row.
    # An identity owns its own artwork, frame count and behaviour, so a level
    # picks three real enemies rather than three costumes for legacy species.
    enemy_slots: list = field(default_factory=list)
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
            "enemySlots": C.level_identities(self),
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

    # THE TWO SHARED KEYS. A level document no longer persists these: they
    # belong to tools/level_editor/encounter_library.v6.json, which is the one
    # authoritative copy. They stay in to_dict() because that is the IN-MEMORY
    # document -- undo snapshots and the dirty marker are taken from it, and a
    # movement-program edit has to be undoable and has to mark the document
    # dirty like any other.
    SHARED_KEYS = ("movementPrograms", "waveDefinitions")

    def to_level_dict(self):
        """What actually goes in levels/<name>/level.v6.json."""
        data = self.to_dict()
        for key in self.SHARED_KEYS:
            data.pop(key, None)
        return data

    def to_json(self):
        """Deterministic text: stable order, 2-space indent, LF, trailing newline."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def to_level_json(self):
        return json.dumps(self.to_level_dict(), indent=2, ensure_ascii=False) + "\n"

    def save(self, path):
        """Write the level document.

        SYMMETRICAL WITH load(). If this project was handed the shared
        vocabulary it does not write it back -- otherwise load/save would put
        the library's contents into the level file, and a second load/save
        would then treat them as the document's own. That asymmetry showed up
        immediately as save() no longer being idempotent on disk.
        """
        text = self.to_level_json() if self.shared_vocabulary else self.to_json()
        Path(path).write_text(text, encoding="utf-8", newline="\n")

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

        _slots = _enemy_slots_from(data)
        project = ProjectV6(
            name=str(data.get("name", "level")),
            stage=stage,
            palette=palette,
            enemy_slots=_slots,
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
            triggers=[Trigger.from_dict(t, f"triggers[{i}]", _slots)
                      for i, t in enumerate(data.get("triggers") or [])],
        )
        project.declared_metatile_cols = stage_cols
        return project

    @staticmethod
    def from_json(text):
        return ProjectV6.from_dict(json.loads(text))

    @staticmethod
    def load(path, library_path=None):
        """A level document plus the shared vocabulary its triggers name.

        See encounter_library.attach_if_absent: a document carrying its own
        programs and definitions is left alone, and one that has none -- which
        is every level since the library migration -- is given the shared set.
        The import is late because encounter_library imports this module.
        """
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        project = ProjectV6.from_dict(raw)
        import encounter_library
        return encounter_library.attach_if_absent(project, raw, library_path)

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
