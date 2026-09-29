#!/usr/bin/env python3
"""MINIMAL DETERMINISTIC v6 PROJECTS FOR EDITOR TESTS.

WHY
---
An editor test's subject is the EDITOR: the schema, the controller, the
validator, the exporter, the widgets. None of that has an opinion about Brian's
current Level 1, and a test that reaches for `project.triggers[0]` is one
re-authoring away from an IndexError or a false pass:

    test_preview_gui.py      select_trigger(RING[0])  -> IndexError, because
                             Level 1 no longer has a plain RING trigger
    test_encounters_gui.py   next(m for m in range(wave0.count)
                                  if m not in mask0)  -> StopIteration, because
                             the authored mask now covers every member
    test_encounter_library   simulate_trigger(project, 0) -> SimulationError,
                             because trigger 0 is now a Dropper
    test_v6_phase5b          "renaming a wave updates every trigger that names
                             it [0 references]" -- the wave it renamed is no
                             longer referenced

Every one of those is a test asking the level a question only a fixture should
be asked. So this module builds the arrangements, small and exact:

    tiny()          the smallest project that validates with no warnings
    shared_wave()   TWO triggers on ONE wave, differing in colour, mode, speed
    wide_wave()     a wave of WIDE_MEMBERS with a PARTIAL fire mask
    two_species()   one trigger per enemy identity slot
    at_capacity(n)  n triggers, for the capacity boundary

EVERY FIXTURE CARRIES TWO PROGRAMS AND TWO WAVES, ALL REFERENCED. An unused
movement program and an unreferenced wave definition are both validator WARNINGS,
so a fixture meant to be the baseline for "validates clean" cannot have either --
and one of the two programs has to TURN, because a path with no arc cannot show
whether speed widens it.

They are DETERMINISTIC -- no clock, no randomness, no repository lookups -- so a
golden taken over one of them is a golden over a fixed thing, which is the only
kind worth having. The real levels are still loaded by the tests that are ABOUT
the real levels (import fidelity, export byte layout, both-levels-validate), and
there the assertion is structural.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import contract_v2 as C                                              # noqa: E402
from project_v6 import (                                             # noqa: E402
    MovementProgram, MovementStage, Palette, ProjectV6, Stage, Trigger, Turret,
    WaveDefinition,
)

# The identity in each of the engine's enemy slots, for a fixture that says
# nothing about artwork. Slot 0 is the ordinary shooting enemy.
IDENTITIES = list(C.DEFAULT_ENEMY_IDENTITIES)
ORDINARY = IDENTITIES[0]

# A wave wide enough to have a PARTIAL mask with members on both sides of a gap.
# Six, because a six-member mask is the case the editor's fire-box row has to
# lay out and the one an authored wave happened to provide until it did not.
WIDE_MEMBERS = 6
WIDE_MASK = [0, 2, 5]            # a gap at 1, a gap at 3-4, and the last member

_ROWS = 105                      # a legal stage, comfortably above the quiet zone
_NO_SPAWN = 340


def _stage(rows=_ROWS, no_spawn=_NO_SPAWN):
    return Stage(metatile_rows=rows, no_spawn_row=no_spawn)


def _palette():
    return Palette(background=0, multicolour1=12, multicolour2=15, character=1)


def programs():
    """Two programs: one that turns, one that does not.

    THE TURNING ONE MATTERS for preview tests -- a path with no arc cannot show
    whether speed widens it -- and the straight one matters for anything that
    needs a velocity it can predict.
    """
    return [
        MovementProgram("turn", [
            MovementStage("STRAIGHT", frames=30, vx=6, vy=0),
            MovementStage("ARC", steps=16, frames_per_step=4, entry_heading=0),
            MovementStage("EXIT"),
        ]),
        MovementProgram("run", [
            MovementStage("STRAIGHT", frames=60, vx=6, vy=2),
            MovementStage("EXIT"),
        ]),
    ]


def _base(*, rows=_ROWS, no_spawn=_NO_SPAWN, defs=1, glyphs=1, turrets=(),
          wave_definitions=None, triggers=None):
    return ProjectV6(
        name="fixture",
        stage=_stage(rows, no_spawn),
        palette=_palette(),
        glyphs=[[0] * 8 for _ in range(glyphs)],
        metatile_defs=[[C.TERRAIN_GLYPH_BASE] * 16 for _ in range(defs)],
        map_rows=[[0] * 10 for _ in range(rows)],
        turrets=list(turrets),
        movement_programs=programs(),
        wave_definitions=list(wave_definitions or []),
        triggers=list(triggers or []),
    )


def wave(wid="w", *, count=4, program="turn", interval=22, start_x=0,
         start_y=64, x_step=0, y_step=20, heading=0):
    return WaveDefinition(id=wid, count=count, interval=interval,
                          start_x=start_x, start_y=start_y, x_step=x_step,
                          y_step=y_step, heading=heading,
                          movement_program=program)


def trigger(row, wid="w", *, species=None, fire_mask=(0,), side="LEFT",
            colour=None, colour_mode=None, fire_mode=None, speed=None):
    return Trigger(world_progress=row, wave_definition=wid,
                   species=species or ORDINARY, fire_mask=list(fire_mask),
                   dropper_side=side, colour=colour, colour_mode=colour_mode,
                   fire_mode=fire_mode, speed=speed)


# ---------------------------------------------------------------------------
# the fixtures
# ---------------------------------------------------------------------------
def tiny():
    """One program, one wave, one trigger. Validates with no errors, no warnings.

    BOTH PROGRAMS ARE REFERENCED. An unused movement program is a validator
    WARNING, and a fixture that is the baseline for "validates clean" has to be
    clean, so the second wave exists purely to name the second program.
    """
    return _base(wave_definitions=[wave(), wave("straight", program="run")],
                 triggers=[trigger(48), trigger(64, "straight")])


def shared_wave():
    """TWO TRIGGERS ON ONE WAVE, differing in every trigger-owned field.

    The arrangement the colour, firing-mode and speed ownership moves exist for,
    and the one no authored level is obliged to contain.
    """
    return _base(
        wave_definitions=[wave(), wave("straight", program="run")],
        triggers=[
            trigger(48, colour=1, colour_mode="FIXED", fire_mode="DOWN",
                    speed=C.TRIG_SPEED_1X),
            trigger(96, colour=7, colour_mode="RANDOM", fire_mode="AIMED",
                    fire_mask=[0, 1], speed=max(C.SPEED_CHOICES)),
            # a third trigger on the OTHER wave, so nothing is unreferenced and
            # "two triggers on one wave" is a real subset rather than the whole
            trigger(144, "straight"),
        ])


def wide_wave():
    """A wave of WIDE_MEMBERS with a PARTIAL fire mask, gaps included."""
    return _base(
        wave_definitions=[wave(count=WIDE_MEMBERS),
                          wave("straight", program="run")],
        triggers=[trigger(48, fire_mask=list(WIDE_MASK)),
                  trigger(64, "straight")])


def two_species():
    """One trigger per enemy identity slot, so "every species" needs no level."""
    return _base(
        wave_definitions=[wave(), wave("straight", program="run")],
        triggers=[trigger(48 + 40 * i, species=ident)
                  for i, ident in enumerate(IDENTITIES)]
        + [trigger(48 + 40 * len(IDENTITIES), "straight")])


def at_capacity(n=None):
    """`n` triggers on one wave -- n defaults to the DERIVED package ceiling.

    THE CEILING IS DERIVED, never a historical literal: C.MAX_TRIGGERS comes
    from src/levelpkg.asm's reservation divided by its column count, so this
    fixture moves when the engine's layout moves and at no other time.
    """
    n = C.MAX_TRIGGERS if n is None else n
    return _base(wave_definitions=[wave(), wave("straight", program="run")],
                 triggers=[trigger(min(48 + i, _NO_SPAWN - 1))
                           for i in range(n - 1)]
                 + [trigger(min(48 + n, _NO_SPAWN - 1), "straight")])


def with_turret(row=None, col=17):
    """One turret, on a row the engine's phase rule accepts."""
    if row is None:
        row = C.TURRET_ROW_PHASE if hasattr(C, "TURRET_ROW_PHASE") else 1
    return _base(turrets=[Turret(row=row, col=col)],
                 wave_definitions=[wave(), wave("straight", program="run")],
                 triggers=[trigger(48), trigger(64, "straight")])


ALL = {"tiny": tiny, "shared_wave": shared_wave, "wide_wave": wide_wave,
       "two_species": two_species, "at_capacity": at_capacity}


if __name__ == "__main__":
    from validation_v6 import validate
    for name, make in ALL.items():
        p = make()
        r = validate(p)
        print(f"{name:<12} {len(p.triggers):>3} trigger(s), "
              f"{len(p.wave_definitions)} wave(s): "
              f"{'clean' if r.ok and not r.warnings else r}")
    print(f"derived capacity: C.MAX_TRIGGERS = {C.MAX_TRIGGERS}")
