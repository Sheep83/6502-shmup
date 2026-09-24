#!/usr/bin/env python3
"""The shared encounter vocabulary: Movement Programs and Wave Definitions.

WHAT MOVED AND WHY. Every level document used to carry its own copy of the
movement programs and wave definitions it referenced. That was invisible while
there was one level; the moment there were two it meant `up_n_over` existed
twice, and editing one copy silently left the other behind. Worse, File → New
Level built a project with all three encounter lists EMPTY, so a new level began
with no reusable wave tools at all and the only way to get them was to copy an
existing level.

So the vocabulary is shared and the placements are not:

    SHARED   movementPrograms, waveDefinitions   <- this file
    PER LEVEL triggers, noSpawnRow, terrain, palette, glyphs, metatiles,
             turrets, stage config                <- levels/<name>/level.v6.json

ONE PERSISTED COPY, NOT TWO KEPT IN STEP. A level document no longer writes the
two shared lists at all (ProjectV6.to_level_dict drops them), so there is
nothing to synchronise and no way for the copies to disagree -- because there is
only one.

IN MEMORY NOTHING MOVED. The library's programs and definitions are installed
onto the live ProjectV6 when a level is opened, so the controller, the
validator, the exporter, the simulator and the preview all go on reading
`project.movement_programs` and `project.wave_definitions` exactly as before.
That is deliberate: the ownership change is a persistence change, and spreading
it through every consumer would have been a rewrite rather than a fix.

The runtime is unaffected. Export still resolves a level's triggers against the
vocabulary and emits that level's own self-contained wave_programs.asm and
wave_encounters.asm; the C64 never learns that an editor library exists.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import project_v6
from project_v6 import MovementProgram, WaveDefinition

HERE = Path(__file__).resolve().parent
LIBRARY_PATH = HERE / "encounter_library.v6.json"

FORMAT_VERSION = project_v6.FORMAT_VERSION
KIND = "encounterLibrary"


class LibraryError(RuntimeError):
    """The library file is not what this module requires."""


class LibraryConflict(LibraryError):
    """Two different things claim the same id.

    Raised rather than resolved. A movement program called `loop` that means
    one thing in the library and another in a level being migrated is an
    authoring question, and guessing at it would quietly change how somebody's
    level flies.
    """

    def __init__(self, kind, ident, where):
        self.kind, self.ident, self.where = kind, ident, where
        super().__init__(
            f"{kind} '{ident}' in {where} differs from the one already in the "
            f"shared library. Reusable assets are shared by IDENTITY, so two "
            f"different definitions cannot both be '{ident}'. Rename one of "
            f"them and migrate again.")


@dataclass
class EncounterLibrary:
    """The reusable vocabulary. Ordered, because the export order is stable."""

    movement_programs: list = field(default_factory=list)
    wave_definitions: list = field(default_factory=list)
    path: object = None

    # ---- construction ---------------------------------------------------
    @staticmethod
    def empty():
        return EncounterLibrary()

    @staticmethod
    def from_project(project):
        """Lift whatever a level document happens to carry."""
        return EncounterLibrary(
            movement_programs=list(project.movement_programs),
            wave_definitions=list(project.wave_definitions))

    @staticmethod
    def from_dict(data, where="the encounter library"):
        if not isinstance(data, dict):
            raise LibraryError(f"{where} must be a JSON object")
        version = data.get("formatVersion")
        if version != FORMAT_VERSION:
            raise LibraryError(
                f"{where}: formatVersion {version!r}, expected {FORMAT_VERSION}")
        kind = data.get("kind")
        if kind != KIND:
            raise LibraryError(
                f"{where}: kind {kind!r}, expected {KIND!r}. A level document "
                f"is not an encounter library")
        return EncounterLibrary(
            movement_programs=[
                MovementProgram.from_dict(p, f"{where}.movementPrograms[{i}]")
                for i, p in enumerate(data.get("movementPrograms") or [])],
            wave_definitions=[
                WaveDefinition.from_dict(d, f"{where}.waveDefinitions[{i}]")
                for i, d in enumerate(data.get("waveDefinitions") or [])])

    @staticmethod
    def load(path=None):
        path = Path(path) if path else LIBRARY_PATH
        if not path.is_file():
            raise LibraryError(
                f"{path} is missing. The shared encounter library holds every "
                f"reusable movement program and wave definition; create it with\n"
                f"    python3 tools/level_editor/migrate_encounter_library.py")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise LibraryError(f"{path} is not valid JSON: {e}") from e
        lib = EncounterLibrary.from_dict(data, str(path))
        lib.path = path
        return lib

    @staticmethod
    def load_or_empty(path=None):
        """For callers that must keep working without a library on disk."""
        try:
            return EncounterLibrary.load(path)
        except LibraryError:
            lib = EncounterLibrary()
            lib.path = Path(path) if path else LIBRARY_PATH
            return lib

    # ---- persistence -----------------------------------------------------
    def to_dict(self):
        """FIELD ORDER IS PART OF THE CONTRACT, as it is for a level."""
        return {
            "formatVersion": FORMAT_VERSION,
            "kind": KIND,
            "movementPrograms": [p.to_dict() for p in self.movement_programs],
            "waveDefinitions": [d.to_dict() for d in self.wave_definitions],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def save(self, path=None):
        target = Path(path) if path else self.path
        if target is None:
            raise LibraryError("no path to save the encounter library to")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8", newline="\n")
        self.path = target
        return target

    # ---- the live document ----------------------------------------------
    def install_into(self, project):
        """Give `project` the shared vocabulary to work with, in memory.

        Copies, not the library's own objects: the controller edits these lists
        in place and undo restores whole documents over them, so sharing the
        instances would let an undo inside one level rewrite the library.
        `harvest_from` puts the edits back.
        """
        project.movement_programs = [
            MovementProgram.from_dict(p.to_dict(), "library")
            for p in self.movement_programs]
        project.wave_definitions = [
            WaveDefinition.from_dict(d.to_dict(), "library")
            for d in self.wave_definitions]
        project.shared_vocabulary = True
        return project

    def harvest_from(self, project):
        """Take the live document's vocabulary back as the library's own.

        The editor's Movement Program and Wave Definition panes edit the live
        project, so this is what makes those edits shared rather than local.
        Triggers are pointedly NOT harvested.
        """
        self.movement_programs = [
            MovementProgram.from_dict(p.to_dict(), "library")
            for p in project.movement_programs]
        self.wave_definitions = [
            WaveDefinition.from_dict(d.to_dict(), "library")
            for d in project.wave_definitions]
        return self

    # ---- migration -------------------------------------------------------
    def reconcile(self, project, where):
        """Fold a level's EMBEDDED reusable assets into this library.

        Returns a list of human-readable notices. Adds anything the library has
        not seen, accepts anything identical, and raises LibraryConflict on an
        id that means two different things. Nothing is ever discarded and
        nothing is ever silently overwritten -- those are the two ways a
        migration like this loses somebody's work.
        """
        notices = []
        for kind, incoming, existing in (
                ("movement program", project.movement_programs, self.movement_programs),
                ("wave definition", project.wave_definitions, self.wave_definitions)):
            by_id = {x.id: x for x in existing}
            for item in incoming:
                if item.id not in by_id:
                    existing.append(
                        type(item).from_dict(item.to_dict(), "library"))
                    by_id[item.id] = existing[-1]
                    notices.append(f"added {kind} '{item.id}' from {where}")
                elif by_id[item.id].to_dict() != item.to_dict():
                    raise LibraryConflict(kind, item.id, where)
        return notices

    # ---- reporting -------------------------------------------------------
    def summary(self):
        return (f"{len(self.movement_programs)} movement programs, "
                f"{len(self.wave_definitions)} wave definitions")

    def ids(self):
        return (sorted(p.id for p in self.movement_programs),
                sorted(d.id for d in self.wave_definitions))


def attach_if_absent(project, raw, library_path=None):
    """Give a freshly loaded level document the shared vocabulary.

    A LEVEL DOCUMENT ALONE IS NO LONGER A COMPLETE PROJECT. It carries triggers
    and terrain; the programs and definitions its triggers name live in the
    shared library. So every loader attaches them, and every consumer --
    exporter, validator, simulator, preview -- goes on reading
    `project.movement_programs` without knowing where they came from.

    A document that still carries its OWN vocabulary is left completely alone.
    That is what keeps legacy files, migration fixtures and synthetic test
    projects behaving exactly as they did: self-contained in, self-contained
    out. Only a document that has been through the migration -- and therefore
    has nothing of its own -- is given the shared set.

    Returns the project, whether or not anything was attached.
    """
    if not isinstance(raw, dict):
        return project
    # THE KEY'S PRESENCE, NOT ITS TRUTHINESS. A document that carries
    # "movementPrograms": [] is stating that it has none of its own -- a v5
    # project migrated forward, for instance -- and giving it the shared
    # vocabulary would be inventing content it never had. Only a document with
    # neither key has been through the library migration and wants the shared
    # set. Testing truthiness instead made an empty list look like a missing
    # one, and a migrated v5 fixture silently acquired six movement programs.
    if "movementPrograms" in raw or "waveDefinitions" in raw:
        return project                      # self-contained; not ours to touch
    lib = EncounterLibrary.load_or_empty(library_path)
    if lib.movement_programs or lib.wave_definitions:
        lib.install_into(project)
        # What was installed, so save() can tell an untouched vocabulary from an
        # edited one. A read-only attach that is never edited can be dropped on
        # save without losing anything; an edited one cannot.
        project.attached_vocabulary = vocabulary_digest(project)
    return project


def vocabulary_digest(project):
    return json.dumps(
        [[p.to_dict() for p in project.movement_programs],
         [d.to_dict() for d in project.wave_definitions]],
        sort_keys=True)

