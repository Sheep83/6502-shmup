# Level Editor Contract v2 — Phase 1: project model, migration, validation

**Date:** 2026-09-19
**HEAD at start:** `3718a45` *Boss hud bug fixed* — level with `origin/main`, 0 behind / 0 ahead. Working tree carried one untracked file, `reports/level-editor-contract-v2-specification.md` (the Contract v2 audit from the previous task).
**Scope:** Phase 1 only — the v6 data model, v5→v6 migration and model-level validation. **No GUI work, no exporter, no engine change.**
**Nothing committed. Nothing pushed.**

---

## 1. Where the editor was, and what was restored

The audit found no editor in the repository. That was still true at the start of this task, and a search turned up **three** copies:

| copy | state |
|---|---|
| `tools/level_editor/` in this repo | **absent** |
| `~/Desktop/c64shooter-main.zip` (10 Sep 2026) | the audited snapshot |
| `/Volumes/SSD/dev/C64/shooter_test/tools/level_editor/` | a separate, older git repo (`032901e Weapon overheat added`) |

Before restoring anything I compared the two existing copies, because the brief is explicit that a newer editor must not be overwritten by an older snapshot:

```
$ diff -rq shooter_test/tools/level_editor  <snapshot>/tools/level_editor
Only in shooter_test/tools/level_editor: .DS_Store
Only in shooter_test/tools/level_editor: __pycache__
Only in shooter_test/tools/level_editor: projects
```

**Every Python file and every level fixture is byte-identical between them.** The only differences are a macOS metadata file, a Python bytecode cache, and an empty `projects/` directory. Neither copy is newer; there was nothing to lose either way. The snapshot the user named is therefore authoritative, and `shooter_test` was left untouched.

### Restored — 46 files, unmodified

`rsync` from the snapshot into `tools/level_editor/`, excluding `__pycache__` and `.DS_Store`:

* **41 Python modules** — `editor.py`, `project.py`, `ka_export.py`, `engine_data.py`, `workshop_ui.py`, `native_metatile.py`, `native_terrain_tiles.py`, `terrain_repository.py`, `wave_repository.py`, `spritesheet.py` and the 21 existing `test_*.py` files, plus the build/author helper scripts.
* **4 data files** — `levels/level1/level.json`, `levels/level2/level.json`, `terrain_repository/repository.json`, `wave_repository/repository.json`.
* **1 fixture** — `testdata/synthetic_tileset.png`.

Verified after copying:

```
$ diff -rq --exclude=__pycache__ <snapshot> tools/level_editor
(no output)
```

**No engine source, build output, report or `src/` file was taken from the archive.** The archive is a whole-repo snapshot from 10 Sep and its engine files are nine days stale; only `tools/level_editor/` was touched.

### Authored this task — 7 files

| file | lines | role |
|---|---|---|
| `contract_v2.py` | 210 | engine limits, each citing the `src/` file it was read from |
| `project_v6.py` | 478 | the v6 model and its deterministic JSON |
| `validation_v6.py` | 579 | the validation API |
| `migration_v6.py` | 224 | v1..v5 → v6 with structured notices |
| `test_v6_migration.py` | 188 | 52 checks |
| `test_v6_validation.py` | 334 | 64 checks |
| `test_v6_roundtrip.py` | 167 | 20 checks |

**No existing editor file was modified.** Not one line of `project.py`, `editor.py`, `ka_export.py` or `engine_data.py` changed — so no compatibility shim was needed and the GUI's imports are untouched.

---

## 2. Constants verified against engine source

Every limit in `contract_v2.py` was read out of `src/` in this task and carries its citation. Two are worth calling out because the audit could not close them:

* **`ENEMY_CLEAR_X_LEFT = 4`** (`src/enemy.asm:219`) — left unresolved by the audit. It bounds a straight/hold leg's velocity: `src/waves.asm` rejects `abs(vx) > ENEMY_CLEAR_X_LEFT * 4`, so the editor's ceiling is **16 quarter-pixels a frame**.
* **`SPECIES_DROPPER = 1 * ENEMY_ANIM_STEPS = 8`** — confirmed as an animation *row offset*, not an index, so validation is by membership.

| symbol | value | source |
|---|---|---|
| `METATILE_W/H`, `METATILES_PER_ROW` | 4, 4, 10 | `src/terrain.asm` |
| `SCREEN_ROWS`, `SCREEN_COLS` | 25, 40 | `src/main.asm` |
| `MAX_METATILE_ROWS` | **440** | `LEVELPKG_MAP_MAX 4400 / 10` |
| `MIN_METATILE_ROWS` | **7** | `STAGE_ROWS < SCREEN_ROWS + 1` errors |
| `MAX_METATILE_DEFS` | 64 | `LEVELPKG_DEFS_MAX / 16` |
| `MAX_TERRAIN_GLYPHS` | **130** | `TURRET_GLYPH_BASE 226 − TERRAIN_GLYPH_BASE 96` |
| `MAX_CHARACTER_COLOUR` | **7** | `TERRAIN_COLOUR_RAM = 8 \| colour` |
| `MAX_TURRETS` | **8** | `.if (TURRET_TOTAL > 8) .error` |
| `LEVELPKG_MOVE_MAX` / records | 256 / **64** | `wmStage` is one byte |
| `MAX_WAVE_DEFINITIONS` | **26** | `def * 10` in one byte |
| `MAX_TRIGGERS` | **180** | 1082 bytes ÷ 6 columns |
| `WM_*` opcodes, `WM_HEAD_CONT` | 0–4, `$ff` | `src/movement_format.asm` |
| `SPECIES`, `DROPPER_SIDES` | RING 0 / DROPPER 8, L 0 / R 1 | `src/encounter_format.asm` |
| `MAX_ABS_VX` | **16** | `ENEMY_CLEAR_X_LEFT * 4` |

**`SCROLL_FRAME_DIVIDER` is deliberately absent.** It is generated into `stage_config.asm` and read by nothing in the engine; the scroll is 1 px/frame unconditionally.

---

## 3. The v6 model

`project_v6.py`, no Tkinter, no I/O beyond `save`/`load`, so it is unit-testable without a display and reusable by the Phase 2 exporter.

```
ProjectV6
  name                str
  stage               Stage(metatile_rows, no_spawn_row)
  palette             Palette(background, multicolour1, multicolour2, character)
  glyphs              list[list[int]]        8 bytes each
  metatile_defs       list[list[int]]        16 character codes each
  level_metatile_set  opaque passthrough     the native authoring source
  map_rows            list[list[int]]        rows x 10 metatile IDs
  turrets             list[Turret(metatile_row, metatile_col)]
  movement_programs   list[MovementProgram(id, stages)]
  wave_definitions    list[WaveDefinition(...)]
  triggers            list[Trigger(...)]
```

**Derived, never stored** — the report's one-authoritative-value rule:
`stage.logical_rows`, `stage.playable_progress`, `stage.playable_frames`,
`stage.terrain_seconds`, `turret.world_row/world_col`,
`project.movement_records/movement_bytes/movement_offsets()`.

For Level 1 those come out at 420 logical rows, **395** playable progress, 3160 frames, **63.2 s**, and a 55-row quiet zone — matching the engine exactly.

### Shapes worth explaining

* **`MovementStage`** carries three payload shapes because the engine's bytes 2 and 3 mean different things per opcode: `STRAIGHT`/`HOLD` take `frames, vx, vy`; `ARC`/`ARC_MIRROR` take `steps, framesPerStep, entryHeading`; `EXIT` takes nothing.
* **`entryHeading` is never defaulted.** It loads as `None` when absent so validation can reject it by name. A silent default would be precisely the old stale-`wmPhase` bug, where an arc inherited the wave's launch heading.
* **`fireMask` is a list of member indices**, because "members 0 and 2 shoot" is what an author means and `%00000101` is what the machine wants. A legacy integer bitmask is accepted on load and normalised; `Trigger.fire_bits` produces the engine value.
* **`movementProgram` is an ID**, resolved to a byte offset by the exporter — which is what stops an offset disagreeing with the records it points at.
* **Triggers are not sorted on save.** The engine requires non-decreasing rows and a violation is a validation *error* the author must see; quietly sorting would hide it and make the rule untestable. Turrets *are* canonicalised by position, which hides nothing.

### Dropped from v6 output

`width`, `height`, `scrollFrameDivider`, `metatileMetadata`, `objects`, `tileset`, `waveDefinitions` (old shape), `waveTriggers`. A test asserts the string `scrollFrameDivider` appears nowhere in the JSON.

---

## 4. Validation API

`validation_v6.validate(project) -> ValidationResult`, with `errors`, `warnings` and `capacity`. Each `Issue` carries a **stable code**, a human message and a field path (`triggers[3].worldProgress`), so a GUI can attach it to a control and a test can assert without matching English.

**ERROR vs WARNING is the engine's line, not taste.** An ERROR is something `src/` refuses to assemble or the 6502 cannot address — a ninth turret, a 257th byte of movement pool, a trigger at the no-spawn row. A WARNING is legal data that is probably not intended — a quiet zone too short to clear the screen, a third simultaneous trigger the director will drop.

Capacity for migrated Level 1:

```
metatileRows (105, 440)      mapBytes (1050, 4400)     metatileDefs (34, 64)
glyphs (72, 130)             turrets (8, 8)            movementRecords (0, 64)
waveDefinitions (0, 26)      triggers (0, 180)
logicalRows 420  playableProgress 395  playableFrames 3160
terrainSeconds 63.2          quietZoneRows 55
```

The model loads projects that are wrong, so they can be inspected and shown; `ProjectV6Error` is raised only when the *shape* makes a model impossible.

---

## 5. v5 → v6 migration

A pipeline, not a rewrite:

```
old JSON -> project.project_from_dict()  ->  LevelProject  ->  ProjectV6
            (every pre-v6 normalisation)
```

`project.py` already knows the pre-v5 glyph rebase (160 → 96), the derived native metatile set for v1–v3 and the turret-cap history. Re-implementing any of it would give two answers to one question, so the legacy loader stays the only one. **No legacy path was modified.**

### Level 1 result

| | |
|---|---|
| version | 5 → **6** |
| terrain | 105 × 10, all 1050 cells unchanged |
| palette | unchanged |
| glyphs | 72, byte-for-byte unchanged |
| metatile defs | 34, unchanged |
| turrets | 8, coordinates unchanged |
| `noSpawnRow` | **340** |
| movement / wave defs / triggers | **empty** |

The derived turret world rows come out as `345, 337, 225, 217, 117, 109, 25, 5` and columns `17, 25, 29, 9, 25, 13, 25, 13` — exactly `src/level1/stage_turrets.asm`, asserted in the test.

`noSpawnRow` is **derived, not copied**: `playableProgress − 55`, where 55 is the quiet zone the engine's own comments derive from the longest authored wave footprint (48 coarse rows). For 105 rows that is `395 − 55 = 340`, which is the value the engine actually ships. The default was checked to be legal for **every** stage height from 7 to 440.

**Short-stage fallback.** `playable − 55` goes non-positive at 84 metatile rows, so the fallback is `max(1, playable // 2)` — a pure function of height, deterministic, and legal at the 7-row minimum (playable 3 → `noSpawnRow` 1). It is a midpoint rather than a clamp so a short stage still gets a real zone.

### The encounter discard, and why it is loud

The 33 old wave definitions and 53 old triggers are **discarded, not converted**. `attackId` 0..11 indexed a curated catalogue that supplied formation, pattern, ingress and egress and no longer exists; `enemyType` 0..3 does not map onto two species; and nothing in v5 supplies spawn X/Y, the per-member fan, a launch heading, a movement program, a fire mask or a Dropper side. Anything invented for those would be **authoring, not migration**.

Migration notices for Level 1, verbatim and deterministic:

```
Migrated formatVersion 5 -> 6
  [migration.version] formatVersion 5 -> 6
  [migration.terrain] kept 105 x 10 terrain, 34 metatile definitions and 72 glyphs
  [migration.turrets] kept 8 turret(s)
  [migration.dropped_scroll_frame_divider] dropped scrollFrameDivider (2): the engine
      scrolls 1 px/frame unconditionally and no source reads this value
  [migration.dropped_metatile_metadata] dropped metatileMetadata (empty): undocumented,
      with no consumer
  [migration.dropped_wave_definitions] DISCARDED 33 old wave definition(s): they are
      attack-catalogue records (attackId/enemyType/composition) and the curated
      catalogue they index no longer exists in the engine
  [migration.dropped_wave_triggers] DISCARDED 53 old wave trigger(s): the engine's
      trigger is six columns (worldProgress, definition, species, fire mask, Dropper
      side) and a v5 trigger supplies only a row and a definition
  [migration.encounters_not_mappable] the old attack catalogue cannot be mapped safely
      onto the current engine contract ... so movementPrograms, waveDefinitions and
      triggers are empty and Level 1's real encounters are imported from the engine
      in Phase 3
  [migration.no_spawn_row] assigned noSpawnRow 340 (stage reaches 395; quiet zone 55
      coarse rows)
  [migration.legacy_trigger_positions] converted 53 old trigger row(s) into
      worldProgress as SUGGESTIONS (45 land inside the new legal range). They are
      migration metadata and are NOT written to the v6 project
```

Each `Notice` also carries a machine-readable `detail` dict (`count`, `value`, `noSpawnRow`, …), asserted by the tests.

### Legacy trigger positions — reference only

Converted with

```python
worldProgress = playableProgress - oldWorldRow
```

which follows directly from `stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS`. The v5 domain counts **down** as play advances; the engine counts **up**. So v5's first row 390 is the *earliest* moment, `worldProgress = 5`, and v5 row 0 is the stage end at 395.

They live on `MigrationResult.legacy_trigger_positions`, sorted ascending with each entry flagged `legal` against the new `noSpawnRow` (45 of 53 are). A test asserts the strings `legacyTriggerPositions` and `oldWorldRow` appear **nowhere** in the v6 JSON — they are migration metadata and never live triggers.

---

## 6. Deterministic JSON

Stable key order (`formatVersion, name, stage, palette, glyphs, metatileDefs, map, turrets, movementPrograms, waveDefinitions, triggers`), 2-space indent, LF only, exactly one trailing newline, no timestamps, no absolute paths, symbolic enum names.

Proven:

* `save → load → save` byte-identical for Level 1 (**64,137 bytes**) and Level 2 (**33,510 bytes**);
* `save() → load() → save()` **on disk** byte-identical;
* migrating the same source twice produces identical JSON **and** identical notices **and** identical converted positions;
* re-migrating an already-v6 project is a no-op that leaves it byte-identical;
* an integer fire mask and its member-index form converge on the same JSON.

---

## 7. Tests

Three new files, **136 checks**, all passing.

| file | checks | covers |
|---|---|---|
| `test_v6_migration.py` | **52** | the full Level 1 v5→v6 migration |
| `test_v6_validation.py` | **64** | every limit and boundary |
| `test_v6_roundtrip.py` | **20** | determinism and the pre-v5 path |

Required failure cases, all asserted by stable code: width ≠ 10; < 7 rows; > 440 rows; > 64 metatile defs; > 130 glyphs; wrong glyph byte count; glyph byte out of range; character colour > 7; > 8 turrets; duplicate turret row; movement pool > 256 bytes **and** > 64 records; malformed movement stage; missing ARC entry heading; > 26 wave definitions; dangling movement-program reference; > 180 triggers; unsorted trigger rows; trigger **at** `noSpawnRow`; trigger **after** `noSpawnRow`; dangling wave-definition reference; invalid fire mask; invalid species; invalid side.

Boundary cases: `worldProgress` 255 and 256 both accepted (the row is genuinely 16-bit, not a byte), and 255→256 accepted as a non-decreasing pair; a trigger one row below `noSpawnRow` accepted while the row itself is rejected — the director's gate is `>=`; the maximum 440-row stage validates (playable 1735, 4.6 min); the 7-row minimum gets a legal fallback; and **every** height 7..440 was checked to yield a legal default.

Positive controls matter as much as the failures: exactly 8 turrets on distinct rows validates, and exactly 64 records / 256 bytes is **accepted** while 66 records trips both ceilings.

### Pre-v5 path

No pre-v5 fixture ships with the editor, so one was constructed by shifting Level 1's metatile defs back to the legacy glyph base 160 and setting `formatVersion 4` — which is exactly what a v4 file was, exercising the real `project.py` rebase rather than a stub. Codes 160..226 come back as 96..162, and **the v4 and v5 routes land on byte-identical v6 projects.**

### Existing editor tests — unchanged

| | baseline (restored, untouched) | after Phase 1 |
|---|---|---|
| pass | 12 | **15** (+3 new files) |
| fail | 9 | **9 — the identical set** |

The 9 failures are **pre-existing and unrelated**, recorded before I wrote any code. All are the stale-path staleness the audit documented:

* 7 fail with `Generated level config not found: …/src/generated/stage_config.asm`;
* 2 GUI tests fail with `Could not find repo root containing src/main.asm and src/generated/level1/stage_test.asm`.

The engine's files are `src/level1/stage_config.asm` and `src/level1/stage_map.asm`. **Fixing that is Phase 2** (`engine_data.py` and `ka_export.py` paths), explicitly out of scope here, so it was left alone rather than half-corrected.

No compatibility shim was needed: no existing module changed, so nothing the GUI imports moved.

---

## 8. Deferred validation, stated plainly

**The trajectory and visibility proofs are not implemented.** `src/waves.asm` flies every member of every definition at assembly time and rejects a path that never arrives, never leaves, is never visible, or walks X past zero — a quarter-pixel simulation of the whole movement interpreter, with `SIM_FRAME_BUDGET = 900` and `SIM_ENTER_BUDGET = 240`.

Half of that simulator would be worse than none: it would pass paths the engine rejects and reject paths it accepts, and an author would learn to distrust it. It stays an assembly-time proof until a preview simulator exists that can be checked against `src/waves.asm` (Contract v2 §7.5; phases 4 and 6). This is recorded in the module docstring beside the rules that *are* enforced.

**Nothing structural was weakened to compensate** — spawn ranges, the per-member fan, headings, colours, opcodes, the EXIT rule, both pool ceilings and every reference check are all enforced now. The one spawn rule not carried over is "every member spawns entirely off-screen", which needs the aperture geometry and belongs with the flight proof.

A second, smaller deferral: scalar fields are coerced to `int` on load, so a *string* in `metatileRows` is reported as an out-of-range value rather than a type error. The error is correct, just less specific. Composite fields — glyph bytes, map cells, metatile codes, entry headings, fire-mask members — keep their raw values and are type-checked properly.

---

## 9. Unresolved questions

1. **`level2/`** migrates cleanly (64 rows, `noSpawnRow` 176) but the engine builds only `LEVEL1`. Whether Contract v2 carries multi-level packaging is still undecided.
2. **Practical wave `count` ceiling.** The engine validates `count >= 1` with no upper bound; the fire mask addresses members 0..7. Counts above 8 warn rather than error, because nothing in source establishes a hard limit.
3. **`level_metatile_set` is carried through opaquely.** Phase 1 does not re-validate the native 32×32 representation — `native_metatile.py` owns that and the existing tests still cover it. If v6 becomes the only format, that validation should move into the v6 validator.
4. **`shooter_test/`** holds an identical editor under a different, older repo. Now that `tools/level_editor/` exists here, it is a stale duplicate; whether to retire it is the user's call and nothing was touched there.

---

## 10. Hygiene and repository status

* **Nothing committed. Nothing pushed.**
* `git status --short`:
  ```
  ?? reports/level-editor-contract-v2-specification.md   (previous task)
  ?? reports/level-editor-v2-phase1-model-migration.md   (this report)
  ?? tools/level_editor/                                 (restored + Phase 1)
  ```
* **No engine source, generated stage data, package layout, Makefile or test under `tests/` was touched.** No `src/` file was read from the archive.
* **No build and no VICE was run** — Phase 1 needs neither. `pgrep -x x64sc` was never non-empty.
* The archive was extracted to disposable scratch only.
* `__pycache__` generated by the test runs was removed; `tools/level_editor/` holds **53 files, 764 KB** (46 restored + 7 authored).
* Disk: `build/` **344 KB**, unchanged and untouched. Session scratch **5.0 MB**, almost all the extracted archive.

**Phase 2 was not begun.** No exporter targets `$e000`, `LEVEL1`, the Stage 3 encounter package, `wave_programs.asm` or `wave_encounters.asm`, and no claim of engine export compatibility is made. `ka_export.py` is exactly as restored.
