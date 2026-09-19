"""The GUI-independent controller: one live v6 project, and the operations on it.

NO TKINTER. Every guarantee Phase 5A has to make -- open/save byte identity,
preservation of encounter data the GUI cannot edit, export of the six generated
files -- is made here, so it can be proved headlessly instead of through a
window. `editor.py` owns widgets; this module owns the project.

-------------------------------------------------------------------------------
THE PRESERVATION RULE, AND HOW THIS MODULE KEEPS IT
-------------------------------------------------------------------------------
The project now carries movement programs, wave definitions, absolute triggers
and a no-spawn boundary that the Phase 5A GUI does not edit. The rule is:

    hold the project that was LOADED, mutate only what the user edits,
    and write the same object back out.

So the controller keeps the `ProjectV6` instance `migration_v6.load_any()`
returned and never rebuilds one from GUI-known fields. Unexposed data survives
because nothing ever takes it apart: `ProjectV6.to_dict()` emits every field it
holds, and the fields the GUI cannot reach are the ones it never touches.

That is the whole mechanism. There is no merge step, no field whitelist and no
"preserve these keys" list to forget to update when the model grows -- a new v6
field is preserved by default, which is the safe direction.

-------------------------------------------------------------------------------
WHY THERE IS A v5-SHAPED VIEW
-------------------------------------------------------------------------------
The terrain canvas, the metatile workshop, the glyph packer and the turret
overlay work, and the brief is explicit that they must keep working. They are
written against the v5 attribute surface (`project.tileset`, `project.height`,
`project.metatile_rows`, `project.objects`), and so are the helpers in
`project.py` that back them -- `repack_tileset_from_metatile_set`,
`remove_metatile`, `metatile_id_usage`, `iter_turrets` and the rest.

`V5View` gives those callers the names they expect over the LIVE v6 project.

IT HOLDS NO DATA. Every attribute is a property that reads or writes the
ProjectV6 underneath, and the lists it hands out ARE the project's own lists, so
an in-place mutation by an existing helper lands on the v6 model directly. It is
a view, not a copy, and there is no synchronisation step that could drift or be
forgotten. `controller.project` remains the single authoritative object.

Two v5 names survive only as inert compatibility:

    scroll_frame_divider   always 1, read-only. The engine scrolls 1 px/frame
                           unconditionally and reads no such value; v6 does not
                           store one. Assigning to it is ignored on purpose so
                           that a stale widget cannot write a fiction into a
                           project that has no field for it.
    metatile_metadata      always {}. v5 carried an undocumented map with no
                           consumer; migration drops it.
"""
from pathlib import Path

import contract_v2 as C
import export_v6
import migration_v6
import project_v6
import validation_v6
from project import (
    OBJECT_TYPE_TURRET,
    canonical_metatile_set_entry,
    pixels_to_rowstrings,
)

CANONICAL_LEVEL = ("levels", "level1", "level.v6.json")

# The six files the Phase 4 exporter writes. Restated here so the GUI can name
# them without importing the exporter's internals.
GENERATED_NAMES = export_v6.GENERATED_NAMES


class ControllerError(RuntimeError):
    """An operation the controller refused, with a message fit for a dialog."""


def _serialise_metatile_entry(entry):
    """One native metatile entry with its pixel rows back as row strings."""
    if not isinstance(entry, dict):
        return entry
    native = entry.get("native")
    if not isinstance(native, dict) or not isinstance(native.get("pixels"), list):
        return entry
    rows = native["pixels"]
    if rows and isinstance(rows[0], str):
        return entry                            # already serialised
    out = dict(entry)
    out["native"] = dict(native)
    out["native"]["pixels"] = pixels_to_rowstrings(rows)
    return out


# ===========================================================================
# The v5-shaped view
# ===========================================================================
class V5View:
    """v5 attribute names over a live ProjectV6. Holds no state of its own."""

    __slots__ = ("_p",)

    def __init__(self, project):
        object.__setattr__(self, "_p", project)

    # ---- identity ------------------------------------------------------
    @property
    def v6(self):
        return self._p

    @property
    def name(self):
        return self._p.name

    @name.setter
    def name(self, value):
        self._p.name = str(value)

    # ---- terrain -------------------------------------------------------
    @property
    def metatile_rows(self):
        """THE PROJECT'S OWN LIST. Painting mutates v6 state directly."""
        return self._p.map_rows

    @metatile_rows.setter
    def metatile_rows(self, rows):
        self._p.map_rows = [list(r) for r in rows]
        self._sync_stage_rows()

    @property
    def height(self):
        return len(self._p.map_rows)

    @property
    def width(self):
        return C.METATILES_PER_ROW

    def clone_rows(self):
        return [list(r) for r in self._p.map_rows]

    def _sync_stage_rows(self):
        """metatileRows is DERIVED FROM THE MAP, never a second opinion."""
        self._p.stage.metatile_rows = len(self._p.map_rows)

    # ---- graphics ------------------------------------------------------
    @property
    def tileset(self):
        """A dict wrapping the project's OWN glyph and definition lists.

        The dict is rebuilt per access; the lists inside it are not. Existing
        code does `tileset["metatileDefs"].append(...)`, which therefore lands on
        the v6 model; code that replaces the whole tileset goes through the
        setter below.
        """
        return {"glyphCount": len(self._p.glyphs),
                "glyphs": self._p.glyphs,
                "metatileDefs": self._p.metatile_defs}

    @tileset.setter
    def tileset(self, value):
        if not value:
            self._p.glyphs = []
            self._p.metatile_defs = []
            return
        self._p.glyphs = [list(g) for g in (value.get("glyphs") or [])]
        self._p.metatile_defs = [list(d) for d in (value.get("metatileDefs") or [])]

    @property
    def level_metatile_set(self):
        return self._p.level_metatile_set

    @level_metatile_set.setter
    def level_metatile_set(self, value):
        self._p.level_metatile_set = value

    def canonical_metatile_set(self, serialised=False):
        return self._p.level_metatile_set

    # ---- palette -------------------------------------------------------
    @property
    def palette(self):
        return self._p.palette.to_dict()

    @palette.setter
    def palette(self, value):
        pal = self._p.palette
        for key in ("background", "multicolour1", "multicolour2", "character"):
            if key in value:
                setattr(pal, key, int(value[key]))

    # ---- turrets -------------------------------------------------------
    @property
    def objects(self):
        """v5 turret dicts, rebuilt per access.

        DELIBERATELY NOT WRITE-THROUGH. A list of dicts cannot alias a list of
        dataclasses, so rather than pretend, the two in-place call sites in the
        editor go through `EditorController.add_turret` / `remove_turret` and
        every other use here is a read. The setter below covers wholesale
        replacement (undo).
        """
        return [{"type": OBJECT_TYPE_TURRET,
                 "metatileRow": t.metatile_row,
                 "metatileCol": t.metatile_col} for t in self._p.turrets]

    @objects.setter
    def objects(self, value):
        self._p.turrets = [
            project_v6.Turret(int(o.get("metatileRow", 0)),
                              int(o.get("metatileCol", 0)))
            for o in (value or []) if isinstance(o, dict)]

    def canonical_objects(self):
        return self.objects

    # ---- inert v5 names ------------------------------------------------
    @property
    def scroll_frame_divider(self):
        return 1

    @scroll_frame_divider.setter
    def scroll_frame_divider(self, value):
        return                      # deliberately ignored; see the module docstring

    @property
    def metatile_metadata(self):
        return {}

    @metatile_metadata.setter
    def metatile_metadata(self, value):
        return

    # ---- encounters: the v5 GUI must not reach them ---------------------
    # These names exist so that any stale caller fails LOUDLY rather than
    # silently editing a project whose encounters it cannot represent.
    @property
    def wave_definitions(self):
        raise ControllerError(
            "the v5 wave-definition surface is not available on a v6 project: "
            "encounters are movement programs, wave definitions and absolute "
            "triggers, and authoring them is Phase 5B")

    @property
    def wave_triggers(self):
        raise ControllerError(
            "the v5 wave-trigger surface is not available on a v6 project: "
            "a v6 trigger is six columns and a v5 trigger supplies two")


# ===========================================================================
# The controller
# ===========================================================================
class EditorController:
    """One live v6 project plus the operations the GUI performs on it."""

    def __init__(self, project, path=None, notices=(), from_version=project_v6.FORMAT_VERSION):
        self.path = Path(path) if path else None
        self.notices = list(notices)
        self.from_version = from_version
        self.adopt(project)

    # ---- the one place a project becomes THE document ------------------
    def adopt(self, project):
        """Install `project` as the live document, in the editor's own form.

        THE NATIVE METATILE SET HAS TWO FORMS and this is the seam between
        them. On disk each 16x32 tile is 32 row STRINGS ("0".."3"), which keeps
        a level.json a few kilobytes instead of about a megabyte; in memory the
        workshop, the glyph packer and the repository all expect 32 lists of 16
        ints. The v5 editor never met the difference because it seeded itself by
        parsing the generated assembler, which produces the in-memory form
        directly -- open a real project file and the strings arrive unconverted.

        Normalising here (and re-serialising in to_json) keeps both true at
        once: the GUI edits lists, the file keeps strings, and a no-op
        open/save is byte-identical.
        """
        lms = project.level_metatile_set
        if isinstance(lms, list):
            project.level_metatile_set = [
                canonical_metatile_set_entry(e, index=i) for i, e in enumerate(lms)]
        self.project = project
        self.view = V5View(project)
        return project

    # ---- construction ---------------------------------------------------
    @classmethod
    def load(cls, path):
        """Open any supported version through the Phase 1 migration path.

        v6 loads directly; v1..v5 migrate deterministically and their notices
        are kept so the GUI can tell the user what was discarded.
        """
        path = Path(path)
        result = migration_v6.load_any(path)
        return cls(result.project, path=path, notices=result.notices,
                   from_version=result.from_version)

    @classmethod
    def canonical_path(cls, editor_dir):
        return Path(editor_dir).joinpath(*CANONICAL_LEVEL)

    @classmethod
    def canonical(cls, editor_dir):
        """The canonical Level 1 v6 project -- the GUI's default document."""
        return cls.load(cls.canonical_path(editor_dir))

    @property
    def migrated(self):
        return self.from_version != project_v6.FORMAT_VERSION

    def migration_summary(self):
        """One short line per notice, for a dialog. Empty when nothing moved.

        A v6 file still produces one notice (`migration.none`), so "there are
        notices" is not "something happened to your project" -- opening the
        canonical level must not raise a dialog.
        """
        if not self.migrated:
            return ""
        return "\n".join(f"• {n.message}" for n in self.notices
                         if n.code != "migration.none")

    def discard_notices(self):
        """Only the notices that say DATA WAS LOST.

        These are the ones worth interrupting somebody for: a v5 project's
        attack-catalogue encounters cannot be carried onto the v6 contract and
        are deliberately dropped, and an author who is not told that will think
        the editor ate their level.
        """
        return [n for n in self.notices
                if n.code.startswith("migration.dropped_")
                or n.code == "migration.encounters_not_mappable"]

    # ---- persistence -----------------------------------------------------
    def to_dict(self):
        """The canonical dictionary, with the metatile set back in on-disk form."""
        data = self.project.to_dict()
        lms = data.get("levelMetatileSet")
        if isinstance(lms, list):
            data["levelMetatileSet"] = [_serialise_metatile_entry(e) for e in lms]
        return data

    def to_json(self):
        """Deterministic v6 text: stable order, 2-space indent, LF, one newline."""
        import json
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def restore_json(self, text):
        """Rebuild the document from a to_json() snapshot (undo/redo)."""
        return self.adopt(project_v6.ProjectV6.from_json(text))

    def save(self, path=None):
        """Write deterministic v6. Unexposed fields ride along untouched."""
        target = Path(path) if path else self.path
        if target is None:
            raise ControllerError("no path to save to")
        target.parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(self.to_json(), encoding="utf-8", newline="\n")
        self.path = target
        # A saved project is a v6 project whatever it arrived as, so the
        # migration notices no longer describe the file on disk.
        self.from_version = project_v6.FORMAT_VERSION
        self.notices = []
        return target

    # ---- validation ------------------------------------------------------
    def validate(self):
        return validation_v6.validate(self.project)

    def blocking_errors(self):
        return list(self.validate().errors)

    # ---- export ----------------------------------------------------------
    def export(self, dest_dir, *, level_name=None, carry_enemies_from=None):
        """Invoke the Phase 4 six-file exporter. Validation errors block it."""
        result = self.validate()
        if not result.ok:
            raise ControllerError(
                "export refused -- the project has "
                f"{len(result.errors)} validation error(s):\n"
                + "\n".join(f"• {i.message}" for i in result.errors[:12]))
        return export_v6.export_level(
            self.project, dest_dir,
            level_name=level_name or self.project.name,
            validate_first=False,               # already done, with a better message
            carry_enemies_from=carry_enemies_from)

    # ---- stage -----------------------------------------------------------
    @property
    def metatile_rows(self):
        return len(self.project.map_rows)

    @property
    def metatile_cols(self):
        return C.METATILES_PER_ROW

    @property
    def no_spawn_row(self):
        return self.project.stage.no_spawn_row

    def duration(self):
        """The current 1 px/frame contract. There is no scroll divider."""
        st = self.project.stage
        return {"logicalRows": st.logical_rows,
                "playableRows": st.playable_progress,
                "playableFrames": st.playable_frames,
                "seconds": st.terrain_seconds}

    def resize(self, rows):
        """Change the stage height, refusing a shrink that would destroy data.

        NOTHING IS SILENTLY DELETED. A shorter stage can strand a turret past
        the new end, push the no-spawn row beyond the stage, or leave a trigger
        with nowhere to happen -- so the unsafe cases are refused by name and
        the author decides, rather than the editor guessing.
        """
        rows = int(rows)
        if rows < C.MIN_METATILE_ROWS or rows > C.MAX_METATILE_ROWS:
            raise ControllerError(
                f"stage height must be between {C.MIN_METATILE_ROWS} and "
                f"{C.MAX_METATILE_ROWS} metatile rows; {rows} is outside that range")

        current = len(self.project.map_rows)
        if rows == current:
            return

        if rows < current:
            stranded = sorted(t.metatile_row for t in self.project.turrets
                              if t.metatile_row >= rows)
            if stranded:
                raise ControllerError(
                    f"cannot shrink to {rows} rows: "
                    f"{len(stranded)} turret(s) sit at or past it "
                    f"(metatile row{'s' if len(stranded) > 1 else ''} "
                    f"{', '.join(str(r) for r in stranded)}). "
                    "Move or delete them first.")
            playable = C.playable_progress(rows)
            if self.project.stage.no_spawn_row >= playable:
                raise ControllerError(
                    f"cannot shrink to {rows} rows: the stage would end at "
                    f"worldProgress {playable}, at or before the no-spawn row "
                    f"{self.project.stage.no_spawn_row}. "
                    "Lower noSpawnRow first.")
            late = [t for t in self.project.triggers
                    if t.world_progress >= playable]
            if late:
                raise ControllerError(
                    f"cannot shrink to {rows} rows: {len(late)} trigger(s) "
                    f"would fall at or past the new stage end "
                    f"(worldProgress {playable}).")

        blank = [0] * C.METATILES_PER_ROW
        if rows > current:
            self.project.map_rows.extend([list(blank) for _ in range(rows - current)])
        else:
            del self.project.map_rows[rows:]
        self.project.stage.metatile_rows = rows

    # ---- terrain ---------------------------------------------------------
    def cell(self, row, col):
        return self.project.map_rows[row][col]

    def set_cell(self, row, col, tile_id):
        """One map cell. Returns True when it actually changed."""
        if not (0 <= row < len(self.project.map_rows)):
            return False
        if not (0 <= col < C.METATILES_PER_ROW):
            return False
        if self.project.map_rows[row][col] == tile_id:
            return False
        self.project.map_rows[row][col] = tile_id
        return True

    # ---- turrets ---------------------------------------------------------
    @property
    def turrets(self):
        return self.project.turrets

    def turret_index_at(self, row, col=None):
        for i, t in enumerate(self.project.turrets):
            if t.metatile_row == row and (col is None or t.metatile_col == col):
                return i
        return None

    def add_turret(self, row, col):
        """Place one turret, enforcing the engine's current limits."""
        if not (0 <= row < len(self.project.map_rows)):
            raise ControllerError(f"metatile row {row} is outside the stage")
        if not (0 <= col < C.METATILES_PER_ROW):
            raise ControllerError(f"metatile column {col} is outside the stage")
        # THE ROW RULE IS REPORTED FIRST, deliberately. When a level is already
        # at the cap AND the clicked row is taken, "that row already has one" is
        # about where the pointer is and "you are at the cap" is about the level;
        # the first is what the author needs to hear.
        if self.turret_index_at(row) is not None:
            raise ControllerError(
                f"metatile row {row} already carries a turret "
                "(the engine allows one per row)")
        if len(self.project.turrets) >= C.MAX_TURRETS:
            raise ControllerError(
                f"this level already has the maximum of {C.MAX_TURRETS} turrets")
        self.project.turrets.append(project_v6.Turret(row, col))
        return len(self.project.turrets) - 1

    def remove_turret(self, index):
        if 0 <= index < len(self.project.turrets):
            del self.project.turrets[index]
            return True
        return False

    # ---- encounters: read only in Phase 5A -------------------------------
    def encounter_summary(self):
        """Counts only. Authoring is Phase 5B; this is here so the GUI can say
        what it is carrying rather than appear to have lost it."""
        p = self.project
        return {"movementPrograms": len(p.movement_programs),
                "waveDefinitions": len(p.wave_definitions),
                "triggers": len(p.triggers),
                "movementRecords": p.movement_records,
                "movementBytes": p.movement_bytes,
                "noSpawnRow": p.stage.no_spawn_row}

    def encounter_summary_text(self):
        s = self.encounter_summary()
        return (f"{s['movementPrograms']} programs · "
                f"{s['waveDefinitions']} wave defs · "
                f"{s['triggers']} triggers · "
                f"no-spawn {s['noSpawnRow']}")
