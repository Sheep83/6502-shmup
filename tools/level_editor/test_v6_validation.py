#!/usr/bin/env python3
"""v6 model validation against the current engine contract (Contract v2, Phase 1).

Every ERROR asserted here corresponds to something `src/` refuses to assemble or
the 6502 cannot address. Each check names the STABLE CODE rather than matching
English, so the messages can be reworded without breaking the suite.

Also covers the boundary cases the contract turns on:
  * worldProgress 255 / 256 -- the trigger row is genuinely sixteen bits;
  * a trigger AT noSpawnRow -- the director's gate is `>=`, so the row itself
    is forbidden and only `<` may start;
  * the maximum legal stage height, 440 metatile rows;
  * a stage too short to afford the 55-row quiet zone.

Run:  python3 tools/level_editor/test_v6_validation.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import contract_v2 as C                                             # noqa: E402
from project_v6 import (                                            # noqa: E402
    MovementProgram, MovementStage, Palette, ProjectV6, Stage, Trigger, Turret,
    WaveDefinition,
)
from validation_v6 import validate                                  # noqa: E402

PASS = []


def ok(label, extra=""):
    PASS.append(label)
    print(f"  ok   {label}{' -- ' + extra if extra else ''}")


def build(rows=105, no_spawn=340, defs=1, glyphs=1):
    """A minimal project that validates with no errors and no warnings."""
    return ProjectV6(
        name="fixture",
        stage=Stage(metatile_rows=rows, no_spawn_row=no_spawn),
        palette=Palette(background=0, multicolour1=12, multicolour2=15, character=1),
        glyphs=[[0] * 8 for _ in range(glyphs)],
        metatile_defs=[[C.TERRAIN_GLYPH_BASE] * 16 for _ in range(defs)],
        map_rows=[[0] * 10 for _ in range(rows)],
        turrets=[],
        movement_programs=[MovementProgram("run", [
            MovementStage("STRAIGHT", frames=30, vx=6, vy=0),
            MovementStage("ARC", steps=16, frames_per_step=4, entry_heading=0),
            MovementStage("EXIT"),
        ])],
        wave_definitions=[WaveDefinition(id="w", count=4, interval=22, start_x=0,
                                         start_y=64, x_step=0, y_step=20,
                                         colour=10, heading=0,
                                         movement_program="run")],
        triggers=[Trigger(world_progress=48, wave_definition="w", species="RING",
                          fire_mask=[0, 2], dropper_side="LEFT")],
    )


def expect_clean(p, label):
    r = validate(p)
    if not r.ok or r.warnings:
        raise AssertionError(f"{label}: expected clean, got\n{r}")
    ok(label)


def expect_error(p, code, label):
    r = validate(p)
    if code not in [i.code for i in r.errors]:
        raise AssertionError(
            f"{label}: expected error {code!r}, got errors "
            f"{[i.code for i in r.errors]} warnings {[i.code for i in r.warnings]}")
    ok(label, code)


def expect_warning(p, code, label):
    r = validate(p)
    if code not in [i.code for i in r.warnings]:
        raise AssertionError(
            f"{label}: expected warning {code!r}, got {[i.code for i in r.warnings]}")
    if not r.ok:
        raise AssertionError(f"{label}: expected no errors, got {r.errors}")
    ok(label, code)


print("=== the baseline fixture ===")
expect_clean(build(), "a minimal project validates with no errors and no warnings")

# ---------------------------------------------------------------------------
print("\n=== terrain limits ===")
p = build(); p.declared_metatile_cols = 12
expect_error(p, "stage.width", "a stage width other than 10 is rejected")

expect_error(build(rows=C.MIN_METATILE_ROWS - 1), "stage.rows",
             f"fewer than {C.MIN_METATILE_ROWS} metatile rows is rejected")
expect_error(build(rows=C.MAX_METATILE_ROWS + 1), "stage.rows",
             f"more than {C.MAX_METATILE_ROWS} metatile rows is rejected")

p = build(defs=C.MAX_METATILE_DEFS + 1)
expect_error(p, "metatile.too_many", "more than 64 metatile definitions is rejected")

p = build(glyphs=C.MAX_TERRAIN_GLYPHS + 1)
expect_error(p, "glyph.too_many",
             "more than 130 terrain glyphs is rejected (turret glyphs sit at 226)")

p = build(); p.glyphs[0] = [0] * 7
expect_error(p, "glyph.size", "a glyph that is not exactly 8 bytes is rejected")
p = build(); p.glyphs[0] = [0, 0, 0, 0, 0, 0, 0, 999]
expect_error(p, "glyph.byte", "a glyph byte outside 0..255 is rejected")

p = build(); p.metatile_defs[0] = [C.TERRAIN_GLYPH_BASE] * 15
expect_error(p, "metatile.size", "a metatile definition of other than 16 codes fails")
p = build(); p.metatile_defs[0][0] = 300
expect_error(p, "metatile.glyph_code",
             "a metatile naming a code outside the level's namespace fails")

p = build(); p.palette.character = 8
expect_error(p, "palette.character",
             "a character colour above 7 is rejected: 8|c forces multicolour")
p = build(); p.palette.background = 16
expect_error(p, "palette.colour", "a colour index above 15 is rejected")

p = build(); p.map_rows[3] = [0] * 9
expect_error(p, "map.row_width", "a map row that is not 10 wide is rejected")
p = build(); p.map_rows[3][2] = 7
expect_error(p, "map.cell", "a map cell naming an undefined metatile is rejected")
p = build(); p.map_rows.pop()
expect_error(p, "map.row_count", "a map shorter than the declared stage is rejected")

# ---------------------------------------------------------------------------
print("\n=== turrets (Contract v2 temporary limits) ===")
p = build()
p.turrets = [Turret(r, 3) for r in range(C.MAX_TURRETS)]
expect_clean(p, f"{C.MAX_TURRETS} turrets on distinct rows validate")
p = build()
p.turrets = [Turret(r, 3) for r in range(C.MAX_TURRETS + 1)]
expect_error(p, "turret.too_many",
             "a ninth turret is rejected: trtDeadPending is one bit a turret")
p = build(); p.turrets = [Turret(5, 2), Turret(5, 7)]
expect_error(p, "turret.duplicate_row",
             "two turrets on one metatile row are rejected")
p = build(); p.turrets = [Turret(999, 3)]
expect_error(p, "turret.row_range", "a turret outside the stage is rejected")
p = build(); p.turrets = [Turret(5, 10)]
expect_error(p, "turret.col_range", "a turret column above 9 is rejected")

# ---------------------------------------------------------------------------
print("\n=== movement programs ===")
p = build(); p.movement_programs[0].stages[-1] = MovementStage("STRAIGHT", frames=5)
expect_error(p, "movement.no_exit", "a program not ending in EXIT is rejected")
p = build()
p.movement_programs[0].stages.insert(0, MovementStage("EXIT"))
expect_error(p, "movement.after_exit", "a stage after EXIT is rejected")
p = build(); p.movement_programs[0].stages[0].kind = "WARP"
expect_error(p, "movement.kind", "an unknown movement opcode is rejected")
p = build(); p.movement_programs[0].stages[0].frames = 0
expect_error(p, "movement.frames", "a zero-length STRAIGHT stage is rejected")
p = build(); p.movement_programs[0].stages[0].vx = C.MAX_ABS_VX + 1
expect_error(p, "movement.velocity",
             "a leg faster than the once-a-frame wrap guard is rejected")
p = build(); p.movement_programs[0].stages[1].entry_heading = None
expect_error(p, "movement.missing_entry_heading",
             "an ARC with no entry heading is rejected (the stale-wmPhase bug)")
p = build(); p.movement_programs[0].stages[1].entry_heading = 64
expect_error(p, "movement.entry_heading", "an ARC entry heading of 64 is rejected")
p = build(); p.movement_programs[0].stages[1].frames_per_step = 0
expect_error(p, "movement.frames_per_step",
             "an ARC with no frames per step is rejected")
p = build(); p.movement_programs[0].stages[1].steps = 0
expect_error(p, "movement.steps", "an ARC with no heading steps is rejected")

# "CONT" on the FIRST arc warns rather than errors: it deliberately inherits.
p = build(); p.movement_programs[0].stages[1].entry_heading = "CONT"
expect_warning(p, "movement.leading_cont",
               "\"CONT\" on a program's first arc warns, and does not error")

# Pool ceilings. 65 records is both >64 records and >256 bytes.
p = build()
p.movement_programs = [MovementProgram(f"p{i}", [
    MovementStage("STRAIGHT", frames=1, vx=1, vy=1), MovementStage("EXIT")])
    for i in range(33)]
p.wave_definitions[0].movement_program = "p0"
r = validate(p)
codes = [i.code for i in r.errors]
if "movement.too_many_records" not in codes or "movement.pool_overflow" not in codes:
    raise AssertionError(f"expected both pool ceilings, got {codes}")
ok("66 records trips BOTH the 64-record and the 256-byte ceiling",
   f"{p.movement_records} records / {p.movement_bytes} bytes")

p = build()
p.movement_programs = [MovementProgram(f"p{i}", [
    MovementStage("STRAIGHT", frames=1, vx=1, vy=1), MovementStage("EXIT")])
    for i in range(32)]
p.wave_definitions[0].movement_program = "p0"
r = validate(p)
if not r.ok:
    raise AssertionError(f"exactly 64 records should fit:\n{r}")
ok("exactly 64 records / 256 bytes is accepted",
   f"{p.movement_records} records / {p.movement_bytes} bytes")

# ---------------------------------------------------------------------------
print("\n=== wave definitions ===")
p = build()
p.movement_programs = [MovementProgram("run", p.movement_programs[0].stages)]
p.wave_definitions = [WaveDefinition(id=f"w{i}", count=1, interval=1, start_x=0,
                                     start_y=0, colour=1, heading=0,
                                     movement_program="run")
                      for i in range(C.MAX_WAVE_DEFINITIONS + 1)]
p.triggers = [Trigger(10, "w0", "RING", [0])]
expect_error(p, "wavedef.too_many",
             "more than 26 wave definitions is rejected (def*10 in one byte)")

p = build(); p.wave_definitions[0].movement_program = "nope"
expect_error(p, "wavedef.dangling_program",
             "a wave definition naming a missing movement program is rejected")
p = build(); p.wave_definitions[0].count = 0
expect_error(p, "wavedef.count", "a wave that sends no enemies is rejected")
p = build(); p.wave_definitions[0].interval = 0
expect_error(p, "wavedef.interval", "a zero spawn interval is rejected")
p = build(); p.wave_definitions[0].start_x = 512
expect_error(p, "wavedef.start_x", "a spawn X of 512 is rejected (nine-bit world)")
p = build(); p.wave_definitions[0].start_y = 256
expect_error(p, "wavedef.start_y", "a spawn Y of 256 is rejected (logY is 8 bits)")
p = build(); p.wave_definitions[0].heading = 64
expect_error(p, "wavedef.heading", "a launch heading of 64 is rejected")
p = build(); p.wave_definitions[0].colour = 16
expect_error(p, "wavedef.colour", "a colour of 16 is rejected")
p = build(); p.wave_definitions[0].x_step = 200
expect_error(p, "wavedef.x_step", "an xStep that walks a member off the world fails")

# ---------------------------------------------------------------------------
print("\n=== triggers ===")
p = build(); p.triggers[0].wave_definition = "nope"
expect_error(p, "trigger.dangling_definition",
             "a trigger naming a missing wave definition is rejected")
p = build(); p.triggers[0].species = "SQUID"
expect_error(p, "trigger.species", "an unknown species is rejected")
p = build(); p.triggers[0].dropper_side = "UP"
expect_error(p, "trigger.side", "an unknown Dropper side is rejected")
p = build(); p.triggers[0].fire_mask = [4]
expect_error(p, "trigger.fire_member_absent",
             "a fire bit naming a member the wave never sends is rejected")
p = build(); p.triggers[0].fire_mask = [9]
expect_error(p, "trigger.fire_width",
             "a fire mask member above 7 is rejected: the mask is one byte")
p = build(); p.triggers[0].fire_mask = ["x"]
expect_error(p, "trigger.fire_member", "a non-integer fire mask member is rejected")

p = build()
p.triggers = [Trigger(10, "w", "RING", [0]), Trigger(5, "w", "DROPPER", [0])]
expect_error(p, "trigger.unsorted", "trigger rows going backwards are rejected")
p = build()
p.triggers = [Trigger(10, "w", "RING", [0]), Trigger(20, "w", "RING", [0])]
expect_error(p, "trigger.repeated_species",
             "two consecutive waves of the same species are rejected")

p = build()
p.triggers = [Trigger(i * 2, "w", "RING" if i % 2 == 0 else "DROPPER", [0])
              for i in range(C.MAX_TRIGGERS + 1)]
expect_error(p, "trigger.too_many", "more than 180 triggers is rejected")

# ---------------------------------------------------------------------------
print("\n=== boundary semantics ===")
# THE GATE IS `>=`, SO THE THRESHOLD ROW ITSELF IS FORBIDDEN.
p = build(); p.triggers[0].world_progress = 340
expect_error(p, "trigger.at_or_after_no_spawn",
             "a trigger exactly AT noSpawnRow is rejected")
p = build(); p.triggers[0].world_progress = 341
expect_error(p, "trigger.at_or_after_no_spawn",
             "a trigger after noSpawnRow is rejected")
p = build(); p.triggers[0].world_progress = 339
expect_clean(p, "a trigger one row before noSpawnRow is accepted")

# The row is genuinely sixteen bits: 255 -> 256 must not be a cliff.
p = build(); p.triggers[0].world_progress = 255
expect_clean(p, "worldProgress 255 is accepted")
p = build(); p.triggers[0].world_progress = 256
expect_clean(p, "worldProgress 256 is accepted -- the row is not one byte")
p = build()
p.triggers = [Trigger(255, "w", "RING", [0]), Trigger(256, "w", "DROPPER", [0])]
expect_clean(p, "255 then 256 is a legal non-decreasing pair across the page break")

p = build(); p.triggers[0].world_progress = 396
expect_error(p, "trigger.past_stage",
             "a trigger past the last row the stage reaches is rejected")

# noSpawnRow itself.
p = build(no_spawn=395)
expect_error(p, "no_spawn.zero_zone",
             "noSpawnRow equal to the stage end leaves no quiet zone")
p = build(no_spawn=396)
expect_error(p, "no_spawn.past_end", "noSpawnRow beyond the stage end is rejected")
p = build(no_spawn=0)
expect_error(p, "no_spawn.range", "noSpawnRow of 0 would suppress the whole stage")

# The maximum legal stage.
p = build(rows=C.MAX_METATILE_ROWS,
          no_spawn=C.default_no_spawn_row(C.MAX_METATILE_ROWS))
r = validate(p)
if not r.ok:
    raise AssertionError(f"the maximum legal stage should validate:\n{r}")
ok(f"the maximum stage of {C.MAX_METATILE_ROWS} rows validates",
   f"playable {p.stage.playable_progress}, "
   f"{p.stage.terrain_seconds / 60:.1f} min")

# The short-stage fallback: `playable - 55` is non-positive, so the midpoint runs.
short = C.MIN_METATILE_ROWS
ns = C.default_no_spawn_row(short)
playable = C.playable_progress(short)
if not (1 <= ns < playable):
    raise AssertionError(f"short-stage fallback is illegal: {ns} of {playable}")
ok(f"the shortest legal stage ({short} rows) gets a legal noSpawnRow",
   f"playable {playable}, noSpawnRow {ns}")
p = build(rows=short, no_spawn=ns)
p.triggers[0].world_progress = 0
r = validate(p)
if not r.ok:
    raise AssertionError(f"the shortest legal stage should validate:\n{r}")
ok("...and a short stage with that fallback validates")

# The fallback is a pure function of height -- migrating twice cannot differ.
if any(C.default_no_spawn_row(n) != C.default_no_spawn_row(n)
       for n in range(C.MIN_METATILE_ROWS, 200)):
    raise AssertionError("default_no_spawn_row is not deterministic")
for n in range(C.MIN_METATILE_ROWS, C.MAX_METATILE_ROWS + 1):
    v = C.default_no_spawn_row(n)
    if not (1 <= v <= C.playable_progress(n)):
        raise AssertionError(f"illegal default noSpawnRow {v} for {n} rows")
ok("every legal stage height yields a legal default noSpawnRow",
   f"{C.MIN_METATILE_ROWS}..{C.MAX_METATILE_ROWS} rows checked")

print(f"\nAll {len(PASS)} validation checks passed.")
