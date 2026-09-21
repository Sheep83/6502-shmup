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

import dataclasses

import contract_v2 as C
import export_v6
import migration_v6
import movement_semantic
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

    # ---- encounters: counts -----------------------------------------------
    def encounter_summary(self):
        """The counts the encounter workspace's status strip reports."""
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

    # =======================================================================
    # ENCOUNTER AUTHORING (Phase 5B)
    # =======================================================================
    # Every operation below is a MODEL operation with no widget in it, so the
    # authoring guarantees -- ordering, reference safety, capacity -- are
    # provable without a display. `encounters_ui` drives these and draws them.
    #
    # NONE OF THEM VALIDATES. validation_v6 is the one rule set (the brief's
    # "do not invent a second"), so an operation that would produce an invalid
    # project still performs it and the workspace shows the validator's own
    # error. The exceptions are the STRUCTURAL refusals -- a duplicate id, a
    # delete that would strand a reference -- which are not opinions about
    # content but operations that cannot be expressed at all.

    def capacity(self):
        """Live capacity, for the status strip. Unused capacity is not a fault."""
        p = self.project
        return {
            "triggers": (len(p.triggers), C.MAX_TRIGGERS),
            "waveDefinitions": (len(p.wave_definitions), C.MAX_WAVE_DEFINITIONS),
            "movementRecords": (p.movement_records, C.MAX_MOVEMENT_RECORDS),
            "movementBytes": (p.movement_bytes, C.LEVELPKG_MOVE_MAX),
        }

    # ---- the stage's quiet zone -------------------------------------------
    def set_no_spawn_row(self, value):
        """The boundary past which no encounter may START.

        Not clamped and not second-guessed: a value that strands a trigger is a
        validation error the author must see, exactly as typing the same number
        into the JSON would be.
        """
        self.project.stage.no_spawn_row = int(value)

    def quiet_zone(self):
        """What the region after noSpawnRow costs, in the engine's own terms."""
        st = self.project.stage
        rows = max(0, st.playable_progress - st.no_spawn_row)
        return {"noSpawnRow": st.no_spawn_row,
                "playableProgress": st.playable_progress,
                "rows": rows,
                # 1 px/frame, 8 px to a coarse row, 50 Hz PAL.
                "seconds": round(rows * 8 / 50.0, 1)}

    # ---- triggers ----------------------------------------------------------
    def sort_triggers(self):
        """Non-decreasing by worldProgress, STABLY.

        The director's cursor only walks forward, so a trigger authored behind
        the one in front of it could never become due. Equal rows ARE legal --
        the validator only rejects a DECREASE -- and two triggers on one row is
        how a mixed-species moment is authored, so the sort must be stable or
        re-saving would shuffle them.
        """
        self.project.triggers.sort(key=lambda t: t.world_progress)

    def trigger_index_of(self, trigger):
        for i, t in enumerate(self.project.triggers):
            if t is trigger:
                return i
        return None

    def suggested_species(self, at_index=None):
        """The species a NEW trigger starts as. Always RING.

        IT USED TO ALTERNATE, because src/waves.asm asserted that consecutive
        authored waves differed and a new trigger that repeated the last one
        would not assemble. That assertion is gone -- it was about content, not
        safety -- so Add Trigger no longer guesses. A predictable default an
        author changes is better than a clever one they have to notice.

        RING is the plain case: it has no side, no token, no encounter behind it,
        and it is what a level is mostly made of. Duplicate is the operation that
        inherits the selected trigger's species.
        """
        return "RING"

    def add_trigger(self, world_progress=None, wave_definition=None,
                    species=None, fire_mask=None, dropper_side="LEFT"):
        """Author one moment. Returns its index after sorting."""
        if len(self.project.triggers) >= C.MAX_TRIGGERS:
            raise ControllerError(
                f"this level already has the maximum of {C.MAX_TRIGGERS} triggers")
        if wave_definition is None:
            if not self.project.wave_definitions:
                raise ControllerError(
                    "a trigger names a wave definition, and this project has "
                    "none yet -- create one first")
            wave_definition = self.project.wave_definitions[0].id
        if world_progress is None:
            world_progress = (self.project.triggers[-1].world_progress + 1
                              if self.project.triggers else 0)
        t = project_v6.Trigger(
            world_progress=int(world_progress),
            wave_definition=str(wave_definition),
            species=species or self.suggested_species(),
            fire_mask=list(fire_mask or []),
            dropper_side=dropper_side)
        self.project.triggers.append(t)
        self.sort_triggers()
        return self.trigger_index_of(t)

    def update_trigger(self, index, **fields):
        """Change named fields of one trigger. Returns its index after sorting.

        `species` and `dropperSide` are stored symbolically; `fireMask` is a
        list of member indices. Nothing is coerced -- an out-of-range value
        reaches the validator, which is what tells the author what is wrong.
        """
        t = self.project.triggers[index]
        if "world_progress" in fields:
            t.world_progress = int(fields["world_progress"])
        if "wave_definition" in fields:
            t.wave_definition = str(fields["wave_definition"])
        if "species" in fields:
            t.species = str(fields["species"])
            # A RING carries a side and ignores it; LEFT is the canonical
            # neutral the validator expects, so switching species away from
            # DROPPER returns the byte to it rather than leaving a stale RIGHT
            # that would warn for ever.
            if t.species != "DROPPER":
                t.dropper_side = "LEFT"
        if "dropper_side" in fields:
            t.dropper_side = str(fields["dropper_side"])
        if "fire_mask" in fields:
            t.fire_mask = sorted({int(m) for m in fields["fire_mask"]})
        self.sort_triggers()
        return self.trigger_index_of(t)

    def delete_trigger(self, index):
        if 0 <= index < len(self.project.triggers):
            del self.project.triggers[index]
            return True
        return False

    def duplicate_trigger(self, index):
        """Copy a trigger one row later, so the copy is visible and legal."""
        src = self.project.triggers[index]
        return self.add_trigger(
            world_progress=src.world_progress + 1,
            wave_definition=src.wave_definition,
            species=src.species,
            fire_mask=list(src.fire_mask),
            dropper_side=src.dropper_side)

    def trigger_members(self, index):
        """How many members the trigger's wave actually sends, or 0 if dangling."""
        t = self.project.triggers[index]
        for d in self.project.wave_definitions:
            if d.id == t.wave_definition:
                return d.count
        return 0

    def impossible_fire_members(self, index):
        """Fire-mask members the referenced wave does not send.

        Reported rather than removed: silently trimming is data loss, so the
        workspace shows this and offers an explicit cleanup the author confirms.
        """
        n = self.trigger_members(index)
        return [m for m in self.project.triggers[index].fire_mask if m >= n]

    def trim_fire_mask(self, index):
        """The explicit, confirmed cleanup for the above."""
        n = self.trigger_members(index)
        t = self.project.triggers[index]
        dropped = [m for m in t.fire_mask if m >= n]
        t.fire_mask = [m for m in t.fire_mask if m < n]
        return dropped

    # ---- wave definitions ---------------------------------------------------
    def wave_definition_index(self, ident):
        for i, d in enumerate(self.project.wave_definitions):
            if d.id == ident:
                return i
        return None

    def triggers_using_definition(self, ident):
        return [i for i, t in enumerate(self.project.triggers)
                if t.wave_definition == ident]

    def unique_id(self, base, existing):
        ident, n = base, 2
        taken = set(existing)
        while ident in taken:
            ident, n = f"{base}{n}", n + 1
        return ident

    def add_wave_definition(self, ident=None, **fields):
        if len(self.project.wave_definitions) >= C.MAX_WAVE_DEFINITIONS:
            raise ControllerError(
                f"this level already has the maximum of "
                f"{C.MAX_WAVE_DEFINITIONS} wave definitions")
        existing = [d.id for d in self.project.wave_definitions]
        ident = ident or self.unique_id("wave", existing)
        if ident in existing:
            raise ControllerError(f"a wave definition called {ident!r} already exists")
        prog = (fields.pop("movement_program", None)
                or (self.project.movement_programs[0].id
                    if self.project.movement_programs else ""))
        d = project_v6.WaveDefinition(id=ident, movement_program=prog, **fields)
        self.project.wave_definitions.append(d)
        self.resync_semantic_programs()
        return len(self.project.wave_definitions) - 1

    def update_wave_definition(self, index, **fields):
        d = self.project.wave_definitions[index]
        for key, value in fields.items():
            if key == "id":
                raise ControllerError("use rename_wave_definition to change an id")
            if not hasattr(d, key):
                raise ControllerError(f"a wave definition has no field {key!r}")
            setattr(d, key, str(value) if key == "movement_program" else int(value))
        self.resync_semantic_programs()
        return index

    def rename_wave_definition(self, index, new_id):
        """Rename, updating every trigger that names it -- atomically."""
        d = self.project.wave_definitions[index]
        new_id = str(new_id)
        if new_id == d.id:
            return 0
        if not new_id:
            raise ControllerError("a wave definition needs an id")
        if any(o.id == new_id for o in self.project.wave_definitions):
            raise ControllerError(f"a wave definition called {new_id!r} already exists")
        old, moved = d.id, 0
        for t in self.project.triggers:
            if t.wave_definition == old:
                t.wave_definition = new_id
                moved += 1
        d.id = new_id
        self.resync_semantic_programs()
        return moved

    def delete_wave_definition(self, index):
        """Refused while a trigger still names it."""
        d = self.project.wave_definitions[index]
        users = self.triggers_using_definition(d.id)
        if users:
            raise ControllerError(
                f"wave definition {d.id!r} is used by {len(users)} trigger(s) "
                f"(at worldProgress "
                f"{', '.join(str(self.project.triggers[i].world_progress) for i in users[:6])}"
                f"{'…' if len(users) > 6 else ''}). "
                "Point them at another definition or delete them first.")
        del self.project.wave_definitions[index]
        self.resync_semantic_programs()
        return True

    def duplicate_wave_definition(self, index):
        src = self.project.wave_definitions[index]
        ident = self.unique_id(f"{src.id}_copy",
                               [d.id for d in self.project.wave_definitions])
        # Built field by field rather than from to_dict(), which uses the JSON
        # names (startX, movementProgram) and not the dataclass's.
        clone = project_v6.WaveDefinition(
            id=ident, count=src.count, interval=src.interval,
            start_x=src.start_x, start_y=src.start_y, x_step=src.x_step,
            y_step=src.y_step, colour=src.colour, heading=src.heading,
            movement_program=src.movement_program)
        self.project.wave_definitions.append(clone)
        self.resync_semantic_programs()
        return len(self.project.wave_definitions) - 1

    # ---- movement programs --------------------------------------------------
    def movement_program_index(self, ident):
        for i, p in enumerate(self.project.movement_programs):
            if p.id == ident:
                return i
        return None

    def definitions_using_program(self, ident):
        return [i for i, d in enumerate(self.project.wave_definitions)
                if d.movement_program == ident]

    def add_movement_program(self, ident=None):
        """A new program starts as a bare EXIT: the one shape that is legal."""
        existing = [p.id for p in self.project.movement_programs]
        ident = ident or self.unique_id("prog", existing)
        if ident in existing:
            raise ControllerError(f"a movement program called {ident!r} already exists")
        prog = project_v6.MovementProgram(
            id=ident, stages=[project_v6.MovementStage(kind="EXIT")])
        self.project.movement_programs.append(prog)
        return len(self.project.movement_programs) - 1

    def rename_movement_program(self, index, new_id):
        """Rename, updating every wave definition that names it -- atomically."""
        prog = self.project.movement_programs[index]
        new_id = str(new_id)
        if new_id == prog.id:
            return 0
        if not new_id:
            raise ControllerError("a movement program needs an id")
        if any(o.id == new_id for o in self.project.movement_programs):
            raise ControllerError(f"a movement program called {new_id!r} already exists")
        old, moved = prog.id, 0
        for d in self.project.wave_definitions:
            if d.movement_program == old:
                d.movement_program = new_id
                moved += 1
        prog.id = new_id
        return moved

    def delete_movement_program(self, index):
        """Refused while a wave definition still names it."""
        prog = self.project.movement_programs[index]
        users = self.definitions_using_program(prog.id)
        if users:
            names = ", ".join(self.project.wave_definitions[i].id for i in users[:6])
            raise ControllerError(
                f"movement program {prog.id!r} is used by {len(users)} wave "
                f"definition(s) ({names}{'…' if len(users) > 6 else ''}). "
                "Point them at another program first.")
        del self.project.movement_programs[index]
        return True

    def duplicate_movement_program(self, index):
        src = self.project.movement_programs[index]
        ident = self.unique_id(f"{src.id}_copy",
                               [p.id for p in self.project.movement_programs])
        clone = project_v6.MovementProgram(
            id=ident,
            stages=[project_v6.MovementStage(**vars(st)) for st in src.stages])
        self.project.movement_programs.append(clone)
        return len(self.project.movement_programs) - 1

    # ---- movement stages ----------------------------------------------------
    @staticmethod
    def new_stage(kind):
        """A stage of `kind` with the fields that kind actually uses.

        PREDICTABLE INITIALISATION, and only the relevant fields: an ARC gets a
        real entry heading rather than None (which is the stale-wmPhase bug the
        model refuses to default), and a STRAIGHT gets a frame count that
        advances. Nothing carries a payload its opcode does not read.
        """
        if kind in C.TIMED_KINDS:
            return project_v6.MovementStage(kind=kind, frames=30, vx=0, vy=4)
        if kind in C.ARC_KINDS:
            return project_v6.MovementStage(kind=kind, steps=8,
                                            frames_per_step=C.WM_STAGE_SIZE,
                                            entry_heading=0)
        return project_v6.MovementStage(kind="EXIT")

    def add_stage(self, prog_index, kind="STRAIGHT", at=None):
        """Insert a stage. EXIT stays last, because it is terminal."""
        prog = self.project.movement_programs[prog_index]
        stage = self.new_stage(kind)
        if at is None:
            # Before the trailing EXIT when there is one, so the ordinary case
            # of "add another leg" does not produce an unreachable stage.
            at = len(prog.stages) - 1 if (prog.stages
                                          and prog.stages[-1].kind == "EXIT"
                                          and kind != "EXIT") else len(prog.stages)
        at = max(0, min(len(prog.stages), int(at)))
        prog.stages.insert(at, stage)
        return at

    def set_stage_kind(self, prog_index, stage_index, kind):
        """Change a stage's opcode, re-initialising it for the new one.

        THE OLD PAYLOAD IS NOT KEPT. An ARC's steps mean nothing to a STRAIGHT,
        and a hidden stale field that reappeared when the kind was switched back
        would be a change the author never made. Switching kind is an explicit
        act and it produces an explicit, predictable stage.
        """
        prog = self.project.movement_programs[prog_index]
        if prog.stages[stage_index].kind == kind:
            return False
        prog.stages[stage_index] = self.new_stage(kind)
        return True

    def update_stage(self, prog_index, stage_index, **fields):
        st = self.project.movement_programs[prog_index].stages[stage_index]
        for key, value in fields.items():
            if not hasattr(st, key):
                raise ControllerError(f"a movement stage has no field {key!r}")
            if key == "entry_heading":
                # "CONT" is a real authored choice, not the magic byte $ff the
                # exporter emits for it.
                st.entry_heading = value if value == "CONT" else int(value)
            elif key == "kind":
                raise ControllerError("use set_stage_kind to change a stage's kind")
            else:
                setattr(st, key, int(value))
        return stage_index

    def delete_stage(self, prog_index, stage_index):
        prog = self.project.movement_programs[prog_index]
        if len(prog.stages) <= 1:
            raise ControllerError(
                "a movement program needs at least one stage; delete the "
                "program instead")
        del prog.stages[stage_index]
        return True

    def move_stage(self, prog_index, stage_index, delta):
        """Reorder one stage. Returns its new index."""
        prog = self.project.movement_programs[prog_index]
        new = stage_index + int(delta)
        if not (0 <= new < len(prog.stages)) or new == stage_index:
            return stage_index
        st = prog.stages.pop(stage_index)
        prog.stages.insert(new, st)
        return new

    # =====================================================================
    # SEMANTIC MOVEMENT AUTHORING  (Phase 6B)
    # =====================================================================
    # A program is SEMANTIC when it carries segments and RAW when it does not.
    # Every operation here leaves `stages` equal to the deterministic
    # compilation of `segments`, because `stages` is what the exporter, the
    # validator and the simulator read -- so a semantic edit reaches the engine
    # by the same path a raw one always did, and nothing downstream changed.
    #
    # NONE OF THEM VALIDATES CAPACITY. validation_v6 is still the one rule set
    # and it already counts compiled records and bytes, so an edit that
    # overflows the pool performs and the workspace shows the validator's own
    # error -- the Phase 5B contract, unchanged.

    def program_continuity(self, prog_index):
        """Where this program's flown path changes direction instantaneously.

        Reported for RAW programs, which can do it; a semantic program cannot
        (see movement_semantic.compile_segments). Read from the faithful
        simulator, so it is a fact about the trajectory rather than about the
        bytes.
        """
        prog = self.project.movement_programs[prog_index]
        if not prog.stages or prog.stages[-1].kind != "EXIT":
            return []
        heading, _n = self.program_launch_heading(prog_index)
        try:
            return movement_semantic.continuity_breaks(prog.stages, heading)
        except Exception:                                   # noqa: BLE001
            return []

    def make_stage_continuous(self, prog_index, stage_index):
        """Enter a raw arc on the heading the object is ACTUALLY travelling.

        THE ONE-BYTE FIX for the stale-heading kink, and it needs no engine
        change: byte 3 of an arc is its entry heading, so naming the heading
        the previous leg was flying on removes the snap outright. Explicit and
        undoable -- the alternative, rewriting it silently, would be the
        editor authoring on the designer's behalf.
        """
        prog = self.project.movement_programs[prog_index]
        breaks = {b["stage"]: b for b in self.program_continuity(prog_index)}
        b = breaks.get(stage_index)
        if b is None:
            raise ControllerError(
                "that stage already continues smoothly from the one before it")
        stage = prog.stages[stage_index]
        if stage.kind not in C.ARC_KINDS:
            raise ControllerError(
                f"a {stage.kind} stage carries its own velocity, so there is no "
                f"entry heading to correct. Change its vx/vy, or author the "
                f"program as semantic segments.")
        if b["travel_heading"] is None:
            raise ControllerError(
                "the previous stage leaves the object standing still, so there "
                "is no direction of travel to continue from")
        stage.entry_heading = b["travel_heading"]
        return b["travel_heading"]

    def program_launch_heading(self, prog_index):
        """(heading, note) this program's records are compiled against."""
        prog = self.project.movement_programs[prog_index]
        return movement_semantic.resolve_launch_heading(
            self.project, prog.id, prog.segments or None)

    def _recompile(self, prog):
        """segments -> stages. The single place compilation is triggered.

        DRAFTS ARE ALLOWED HERE AND REFUSED AT THE DOOR. A program being built
        is routinely incomplete -- no terminal EXIT yet, or a segment whose
        numbers are still being typed -- and refusing the edit would make
        progressive authoring impossible. So the compiled prefix is stored and
        `validation_v6` decides whether the result may be SAVED or EXPORTED.
        The synthetic terminator the draft used for previewing is dropped, so
        an unfinished program still reads as unfinished to the validator.
        """
        heading, _note = movement_semantic.resolve_launch_heading(
            self.project, prog.id, prog.segments or None)
        draft = movement_semantic.compile_draft(prog.segments, heading)
        prog.stages = draft.authored_stages
        return draft

    def segment_incoming_heading(self, prog_index, index):
        """The direction the object is travelling as it REACHES this segment.

        What the dial shows before an author has chosen anything: turning
        "Set direction" on should not move the path, it should offer the
        direction already being flown as the starting point.
        """
        prog = self.project.movement_programs[prog_index]
        heading, _note = movement_semantic.resolve_launch_heading(
            self.project, prog.id, prog.segments or None)
        return movement_semantic.final_heading(prog.segments[:index], heading)

    def program_draft(self, prog_index):
        """How far this program currently compiles, and why it stops."""
        prog = self.project.movement_programs[prog_index]
        if not prog.is_semantic:
            return None
        heading, _note = movement_semantic.resolve_launch_heading(
            self.project, prog.id, prog.segments or None)
        return movement_semantic.compile_draft(prog.segments, heading)

    def program_cost(self, prog_index):
        """What this program costs the runtime pool, and what it was written as.

        THE POINT OF SHOWING BOTH is that macros and turns expand: seven
        segments are not seven records, and an author who cannot see the
        difference will meet it as an export failure instead.
        """
        prog = self.project.movement_programs[prog_index]
        return {"segments": len(prog.segments),
                "records": len(prog.stages),
                "bytes": len(prog.stages) * C.WM_STAGE_SIZE,
                "semantic": prog.is_semantic}

    def make_semantic(self, prog_index):
        """Convert a raw program to segments, ONLY if the path is unchanged.

        Returns a dict describing what happened. Refuses rather than
        approximates: some records cannot be said as relative segments, and
        those programs stay raw for ever, which is a supported state and not a
        failure.
        """
        prog = self.project.movement_programs[prog_index]
        if prog.is_semantic:
            raise ControllerError(
                f"{prog.id!r} is already a semantic program")
        heading, _note = movement_semantic.resolve_launch_heading(
            self.project, prog.id)
        segs, why, same_bytes = movement_semantic.lift_is_exact(
            prog.stages, heading)
        if segs is None:
            raise ControllerError(
                f"{prog.id!r} cannot be converted without changing it: {why}")
        prog.segments = segs
        self._recompile(prog)
        return {"heading": heading, "bytes_identical": same_bytes,
                "segments": len(segs)}

    def preview_make_semantic(self, prog_index):
        """What make_semantic WOULD do, without doing it.

        So the editor can put the consequence in front of the author -- in
        particular that the compiled bytes change even though the flight does
        not -- before anything is committed to the undo stack.
        """
        prog = self.project.movement_programs[prog_index]
        if prog.is_semantic:
            return None, "already semantic", False
        heading, _note = movement_semantic.resolve_launch_heading(
            self.project, prog.id)
        return movement_semantic.lift_is_exact(prog.stages, heading)

    def start_semantic(self, prog_index):
        """Begin a program as segments, discarding whatever records it had.

        FOR A PROGRAM THAT CANNOT BE LIFTED, and for a brand-new one. The seed
        is STRAIGHT then EXIT rather than a bare EXIT, because a bare EXIT
        inherits no velocity and so does not compile -- the engine would give
        the object a pool slot and no way to leave. Destructive and therefore
        explicit: make_semantic() is the non-destructive route and is tried
        first everywhere this is offered.
        """
        prog = self.project.movement_programs[prog_index]
        segs = [movement_semantic.Segment(kind="STRAIGHT", frames=30),
                movement_semantic.Segment(kind="EXIT")]
        return self._commit(prog, segs, 0)

    def make_raw(self, prog_index):
        """Drop back to raw records, keeping the compiled ones as they stand.

        THE SEGMENTS ARE DISCARDED, not hidden. A stale semantic program kept
        alongside hand-edited records is exactly the "hidden stale payload"
        Phase 5B refused: it would reappear and overwrite the records the
        moment anything recompiled.
        """
        prog = self.project.movement_programs[prog_index]
        if not prog.is_semantic:
            return False
        prog.segments = []
        return True

    @staticmethod
    def new_segment(kind):
        """A segment of `kind` with parameters that actually do something."""
        if kind == "STRAIGHT":
            return movement_semantic.Segment(kind="STRAIGHT", frames=30)
        if kind == "TURN":
            return movement_semantic.Segment(
                kind="TURN", direction="RIGHT", steps=16,
                rate=movement_semantic.DEFAULT_RATE)
        if kind == "HOLD":
            return movement_semantic.Segment(kind="HOLD", frames=30)
        return movement_semantic.Segment(kind="EXIT")

    def add_segment(self, prog_index, kind="STRAIGHT", at=None):
        """Insert one segment, keeping the terminal EXIT terminal."""
        prog = self._semantic(prog_index)
        segs = list(prog.segments)
        if at is None:
            at = (len(segs) - 1 if segs and segs[-1].kind == "EXIT"
                  and kind != "EXIT" else len(segs))
        at = max(0, min(len(segs), int(at)))
        segs.insert(at, self.new_segment(kind))
        return self._commit(prog, segs, at)

    def insert_macro(self, prog_index, name, at=None):
        """Expand a named manoeuvre into core segments, in place.

        EXPANDED NOW, NOT STORED. See movement_semantic.MACROS for why: the
        author sees the records it cost the moment it lands, and can then tune
        either half.
        """
        prog = self._semantic(prog_index)
        if name not in movement_semantic.MACROS:
            raise ControllerError(f"no movement macro named {name!r}")
        new = movement_semantic.MACROS[name]()
        segs = list(prog.segments)
        if at is None:
            at = (len(segs) - 1 if segs and segs[-1].kind == "EXIT"
                  else len(segs))
        at = max(0, min(len(segs), int(at)))
        segs[at:at] = new
        return self._commit(prog, segs, at)

    def set_segment_kind(self, prog_index, index, kind):
        """Change a segment's kind, re-initialising it. No stale payload."""
        prog = self._semantic(prog_index)
        if prog.segments[index].kind == kind:
            return index
        segs = list(prog.segments)
        segs[index] = self.new_segment(kind)
        return self._commit(prog, segs, index)

    def update_segment(self, prog_index, index, **fields):
        """Edit one segment's parameters. Segments are immutable, so this
        replaces rather than mutates."""
        prog = self._semantic(prog_index)
        seg = prog.segments[index]
        for key in fields:
            if not hasattr(seg, key):
                raise ControllerError(f"a movement segment has no field {key!r}")
            if key == "kind":
                raise ControllerError(
                    "use set_segment_kind to change a segment's kind")
        clean = {}
        for key, value in fields.items():
            if key == "direction":
                if value not in movement_semantic.DIRECTIONS:
                    raise ControllerError(
                        f"direction must be LEFT or RIGHT, not {value!r}")
                clean[key] = value
            elif key == "heading":
                # None IS A VALUE HERE, and the important one: it is Continue,
                # the default that keeps a program relative. Coercing it to an
                # integer would silently turn every straight into an explicit
                # direction and quietly destroy reusability.
                clean[key] = None if value is None else int(value)
            else:
                clean[key] = int(value)
        segs = list(prog.segments)
        segs[index] = dataclasses.replace(seg, **clean)
        return self._commit(prog, segs, index)

    def delete_segment(self, prog_index, index):
        prog = self._semantic(prog_index)
        if len(prog.segments) <= 1:
            raise ControllerError(
                "a movement program needs at least one segment; delete the "
                "program instead")
        segs = list(prog.segments)
        del segs[index]
        return self._commit(prog, segs, min(index, len(segs) - 1))

    def duplicate_segment(self, prog_index, index):
        prog = self._semantic(prog_index)
        segs = list(prog.segments)
        segs.insert(index + 1, segs[index])
        return self._commit(prog, segs, index + 1)

    def move_segment(self, prog_index, index, delta):
        prog = self._semantic(prog_index)
        new = index + int(delta)
        if not (0 <= new < len(prog.segments)) or new == index:
            return index
        segs = list(prog.segments)
        segs.insert(new, segs.pop(index))
        return self._commit(prog, segs, new)

    def mirror_program(self, prog_index):
        """Mirror the MOVEMENT. The launch state is the wave's business.

        Returns the launch heading a wave would need for this to read as a
        screen-space reflection, so the editor can say so explicitly rather
        than silently rewriting a wave definition the author did not select.
        """
        prog = self._semantic(prog_index)
        segs = movement_semantic.mirror_segments(prog.segments)
        heading, _note = movement_semantic.resolve_launch_heading(
            self.project, prog.id, segs)
        self._commit(prog, segs, 0)
        return {"mirrored_launch_heading":
                movement_semantic.mirror_heading(heading),
                "current_launch_heading": heading}

    def resync_semantic_programs(self):
        """Recompile every semantic program against its CURRENT launch heading.

        A STRAIGHT bakes its velocity into the record, so a semantic program's
        compiled records depend on the launch heading of the waves that use it
        -- which means editing a WAVE can invalidate a PROGRAM. Pointing a new
        wave at a program, or changing an existing wave's heading, would
        otherwise leave records compiled for the old heading: the editor would
        show a straight leg going one way and the engine would fly it another.

        Called after every wave-definition change. Cheap (a project holds a
        handful of programs), deterministic, and it only rewrites records that
        actually differ, so it cannot manufacture a spurious edit.

        Returns the ids whose records it had to change.
        """
        changed = []
        for prog in self.project.movement_programs:
            if not prog.is_semantic:
                continue                        # raw records are never touched
            heading, _note = movement_semantic.resolve_launch_heading(
                self.project, prog.id, prog.segments)
            try:
                fresh = movement_semantic.compile_segments(prog.segments, heading)
            except movement_semantic.CompileError:
                # An uncompilable program is already an error the validator
                # reports; leaving the last good records in place is better
                # than blanking them behind the author's back.
                continue
            if [s.to_dict() for s in fresh] != [s.to_dict() for s in prog.stages]:
                prog.stages = fresh
                changed.append(prog.id)
        return changed

    def _semantic(self, prog_index):
        prog = self.project.movement_programs[prog_index]
        if not prog.is_semantic:
            raise ControllerError(
                f"{prog.id!r} is a raw program: convert it to segments first, "
                f"or edit its records in the Advanced view")
        return prog

    def _commit(self, prog, segs, cursor):
        """Adopt new segments and recompile the records from them.

        NO LONGER ALL-OR-NOTHING, because "nothing" is the wrong answer while
        a program is being built: an author who has not yet added EXIT, or who
        is halfway through typing a step count, must still be able to make the
        edit and see it. `segments` stays the source of truth, `stages`
        becomes the compiled prefix, and the two cannot disagree because one
        is derived from the other every time.
        """
        prog.segments = segs
        self._recompile(prog)
        return cursor
