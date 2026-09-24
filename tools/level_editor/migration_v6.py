"""v1..v5 -> v6 project migration, with a loud account of what it dropped.

THE PIPELINE IS DELIBERATELY NOT A REWRITE OF THE LEGACY RULES:

    old JSON -> project.project_from_dict()  -> LevelProject (v5-equivalent)
                                             -> ProjectV6

project.py already knows how to normalise every older version -- the pre-v5
terrain glyph rebase from base 160 to base 96, deriving a native metatile set for
v1..v3 files, the turret cap history. Re-implementing any of that here would give
two answers to the same question, so the legacy loader stays the only one.

WHY THE ENCOUNTER DATA IS DISCARDED RATHER THAN CONVERTED, which is the part of
this module that most looks like a bug and is not:

  * v5 wave definitions are `attackId` 0..11 into a CURATED CATALOGUE that
    supplied formation, pattern, ingress and egress. That catalogue no longer
    exists in the engine in any form.
  * v5 `enemyType` 0..3 does not map onto the two species the engine now has.
  * nothing in v5 supplies startX/startY, xStep/yStep, launch heading, a movement
    program, a fire mask or a Dropper side -- the six-column trigger contract's
    own fields.

Anything this module invented for those would be CONTENT, not migration. So the
old encounters are dropped, every dropped item is counted in the notices, and the
authoritative Level 1 encounters get imported from the engine in Phase 3.

The old trigger POSITIONS are still worth something, so they are converted into
the engine's coordinate domain and reported as suggestions. They are NOT live
triggers and are not written into the v6 file.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path

import contract_v2 as C
import project as legacy
from project_v6 import (FORMAT_VERSION, MovementProgram, Palette, ProjectV6,
                        ProjectV6Error, Stage, Turret, WaveDefinition)


@dataclass(frozen=True)
class Notice:
    code: str
    message: str
    detail: dict = field(default_factory=dict)

    def __str__(self):
        return f"[{self.code}] {self.message}"


@dataclass
class MigrationResult:
    project: ProjectV6
    from_version: int
    to_version: int = FORMAT_VERSION
    notices: list = field(default_factory=list)
    # Old trigger rows converted into worldProgress. MIGRATION METADATA ONLY --
    # never written to the v6 file, never a live trigger. See legacy_trigger_progress.
    legacy_trigger_positions: list = field(default_factory=list)

    def note(self, code, message, **detail):
        self.notices.append(Notice(code, message, detail))

    def codes(self):
        return [n.code for n in self.notices]

    def report(self):
        """A stable, human-readable summary. No timestamps, no paths."""
        lines = [f"Migrated formatVersion {self.from_version} -> {self.to_version}"]
        lines += [f"  {n}" for n in self.notices]
        if self.legacy_trigger_positions:
            lines.append(f"  Converted legacy trigger positions "
                         f"({len(self.legacy_trigger_positions)}), for reference only:")
            for e in self.legacy_trigger_positions:
                lines.append(f"    stage row {e['oldWorldRow']:>5} -> worldProgress "
                             f"{e['worldProgress']:>5}  "
                             f"{'legal' if e['legal'] else 'OUT OF RANGE'}  "
                             f"({e['waveDef']})")
        return "\n".join(lines)


def legacy_trigger_progress(old_world_row, playable_progress):
    """v5 stage row -> engine worldProgress.

    THE TWO DOMAINS RUN IN OPPOSITE DIRECTIONS. v5 authored the stage row sitting
    at the top of the aperture, counting DOWN as play advanced; the engine counts
    worldProgress UP from zero. src/scroll.asm's invariant is

        stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS

    and with STAGE_START_ROW == STAGE_FINAL_VIEW_PROGRESS == playable_progress
    that rearranges to exactly this.
    """
    return playable_progress - old_world_row


def migrate_to_v6(data):
    """Migrate a parsed project dict of any supported version to v6."""
    if not isinstance(data, dict):
        raise ProjectV6Error("a project must be a JSON object")
    from_version = data.get("formatVersion")

    if from_version == FORMAT_VERSION:
        result = MigrationResult(project=ProjectV6.from_dict(data),
                                 from_version=FORMAT_VERSION)
        result.note("migration.none", "already formatVersion 6; nothing to migrate")
        return result

    # --- the legacy pipeline does every pre-v6 normalisation ---------------
    old = legacy.project_from_dict(data)
    result = MigrationResult(project=None, from_version=from_version)
    result.note("migration.version",
                f"formatVersion {from_version} -> {FORMAT_VERSION}",
                fromVersion=from_version, toVersion=FORMAT_VERSION)

    rows = len(old.metatile_rows)
    no_spawn = C.default_no_spawn_row(rows)
    playable = C.playable_progress(rows)

    tileset = old.tileset or {}
    glyphs = [list(g) for g in (tileset.get("glyphs") or [])]
    defs = [list(d) for d in (tileset.get("metatileDefs") or [])]

    turrets = [Turret(int(o["metatileRow"]), int(o["metatileCol"]))
               for o in old.objects
               if isinstance(o, dict) and o.get("type") == legacy.OBJECT_TYPE_TURRET]

    project = ProjectV6(
        name=old.name,
        stage=Stage(metatile_rows=rows, no_spawn_row=no_spawn),
        palette=Palette(background=old.palette["background"],
                        multicolour1=old.palette["multicolour1"],
                        multicolour2=old.palette["multicolour2"],
                        character=old.palette["character"]),
        glyphs=glyphs,
        metatile_defs=defs,
        level_metatile_set=old.canonical_metatile_set(serialised=True),
        map_rows=old.clone_rows(),
        turrets=turrets,
        # EMPTY BY DESIGN. Level 1's authoritative encounters come from the
        # engine in Phase 3, not from a v5 file that cannot describe them.
        movement_programs=[],
        wave_definitions=[],
        triggers=[],
    )
    result.project = project

    # --- what survived ------------------------------------------------------
    result.note("migration.terrain",
                f"kept {rows} x {C.METATILES_PER_ROW} terrain, {len(defs)} metatile "
                f"definitions and {len(glyphs)} glyphs",
                metatileRows=rows, metatileDefs=len(defs), glyphs=len(glyphs))
    result.note("migration.turrets", f"kept {len(turrets)} turret(s)",
                turrets=len(turrets))

    # --- what was dropped, and why ------------------------------------------
    result.note("migration.dropped_scroll_frame_divider",
                f"dropped scrollFrameDivider ({old.scroll_frame_divider}): the engine "
                f"scrolls 1 px/frame unconditionally and no source reads this value",
                value=old.scroll_frame_divider)
    if old.metatile_metadata:
        result.note("migration.dropped_metatile_metadata",
                    f"dropped metatileMetadata ({len(old.metatile_metadata)} "
                    f"entries): undocumented, with no consumer",
                    entries=len(old.metatile_metadata))
    else:
        result.note("migration.dropped_metatile_metadata",
                    "dropped metatileMetadata (empty): undocumented, with no consumer",
                    entries=0)

    n_defs, n_trigs = len(old.wave_definitions), len(old.wave_triggers)
    result.note("migration.dropped_wave_definitions",
                f"DISCARDED {n_defs} old wave definition(s): they are attack-catalogue "
                f"records (attackId/enemyType/composition) and the curated catalogue "
                f"they index no longer exists in the engine",
                count=n_defs)
    result.note("migration.dropped_wave_triggers",
                f"DISCARDED {n_trigs} old wave trigger(s): the engine's trigger is six "
                f"columns (worldProgress, definition, species, fire mask, Dropper "
                f"side) and a v5 trigger supplies only a row and a definition",
                count=n_trigs)
    if n_defs or n_trigs:
        result.note("migration.encounters_not_mappable",
                    "the old attack catalogue cannot be mapped safely onto the "
                    "current engine contract: nothing in v5 supplies spawn X/Y, the "
                    "per-member fan, a launch heading, a movement program, a fire "
                    "mask or a Dropper side. Inventing them would be authoring, not "
                    "migration -- so movementPrograms, waveDefinitions and triggers "
                    "are empty and Level 1's real encounters are imported from the "
                    "engine in Phase 3")
    result.note("migration.no_spawn_row",
                f"assigned noSpawnRow {no_spawn} (stage reaches {playable}; quiet "
                f"zone {playable - no_spawn} coarse rows)",
                noSpawnRow=no_spawn, playableProgress=playable,
                quietZoneRows=playable - no_spawn)

    # --- the old positions, converted, as reference only --------------------
    positions = []
    for t in old.wave_triggers:
        old_row = int(t.get("worldRow", 0))
        wp = legacy_trigger_progress(old_row, playable)
        positions.append({
            "oldWorldRow": old_row,
            "worldProgress": wp,
            "waveDef": str(t.get("waveDef", "")),
            "legal": 0 <= wp < no_spawn,
        })
    # Deterministic: the engine's own order, ties broken by the old row.
    positions.sort(key=lambda e: (e["worldProgress"], e["oldWorldRow"]))
    result.legacy_trigger_positions = positions
    if positions:
        legal = sum(1 for e in positions if e["legal"])
        result.note("migration.legacy_trigger_positions",
                    f"converted {len(positions)} old trigger row(s) into worldProgress "
                    f"as SUGGESTIONS ({legal} land inside the new legal range). They "
                    f"are migration metadata and are NOT written to the v6 project",
                    count=len(positions), legal=legal)
    return result


def load_any(path, library_path=None, attach=True):
    """Load a project of any supported version, migrating if necessary.

    A MIGRATED LEVEL DOCUMENT NO LONGER CARRIES ITS OWN MOVEMENT PROGRAMS OR
    WAVE DEFINITIONS -- they are shared, and live in the encounter library. So
    a document that has none of its own is given the shared ones here, which is
    what lets every consumer downstream (exporter, validator, simulator,
    preview) keep reading project.movement_programs without knowing anything
    changed. A document that still carries its own is left exactly as it is.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    result = migrate_to_v6(raw)
    if attach:
        import encounter_library
        encounter_library.attach_if_absent(result.project, raw, library_path)
    return result
