# Level Editor Contract v2 — Phase 2: deterministic terrain / config / turret exporter

**Date:** 2026-09-19
**HEAD at start:** `3718a45` *Boss hud bug fixed* — level with `origin/main`, 0 behind / 0 ahead.
**Working tree at start:** Phase 1's three untracked items, intact and preserved.
**Scope:** Phase 2 only — export `stage_config.asm`, `stage_charset.asm`, `stage_map.asm`, `stage_turrets.asm` from a v6 project, and prove the result against the authoritative Level 1. **No encounter export. No engine change.**
**Nothing committed. Nothing pushed.**

---

## 1. Headline result

**The whole of `build/level1.prg` is byte-identical**, and so is **`build/shmup.prg`**.

The current build was run with `LEVELDIR` pointed at a scratch directory containing only the four exported files (plus the hand-authored `stage_enemies.asm` carried forward), and both binaries came out bit for bit the same as the authoritative build. That is the preferred Phase 2 acceptance criterion, and it is met without qualification — there is no blocker to explain.

`shmup.prg` matters as much as `level1.prg` here: the glyph bitmaps and the turret tables are assembled into the **engine** PRG, not the level package, so package-region equality alone would not have covered them.

---

## 2. Phase 1 state preserved

Nothing from Phase 1 was reset, checked out over, or cleaned. HEAD is unchanged; the three untracked items are still untracked. All 136 Phase 1 checks were re-run before any edit and again at the end:

```
test_v6_migration.py       All 52 migration checks passed.
test_v6_validation.py      All 64 validation checks passed.
test_v6_roundtrip.py       All 20 round-trip checks passed.
```

The seven Phase 1 modules (`contract_v2.py`, `project_v6.py`, `validation_v6.py`, `migration_v6.py` and their three test files) are **unmodified** by this task.

---

## 3. Files

### New in Phase 2 — 2 files

| file | lines | role |
|---|---|---|
| `tools/level_editor/export_v6.py` | 341 | the v6 exporter |
| `tools/level_editor/test_v6_export.py` | 295 | 61 checks, including the build proof |

### Modified — 10 files, all Phase-1-restored originals

| file | change |
|---|---|
| `engine_data.py` | `src/generated` → `src`; `stage_test.asm` → `stage_map.asm`; removed `GENERATED_WAVES_NAME`; added `LEVEL_ENEMIES_NAME` |
| `editor.py` | `find_repo_root` probes `src/level1/stage_map.asm`; export dialog defaults to `src/<level>/` and says four files |
| `ka_export.py` | `STAGE_NAME` → `stage_map.asm`; **removed** `render_stage_waves` + `_resolve_triggers` + `WAVES_NAME`; `export_level` returns four paths |
| `acceptance_terrain_workshop.py` | 4 × `stage_test.asm` → `stage_map.asm` |
| `test_level_packages.py` | converted off `src/generated/level{1,2}` |
| `test_native_terrain_tiles.py` | converted; stale Level 1 content expectations corrected |
| `test_wave_schema.py` | rewritten against the current wave/trigger contract |
| `test_metatile_capacity.py`, `test_metatile_delete.py`, `test_turret_integration.py` | filename references |

### Unchanged

**No file under `src/`, no `Makefile`, no test under `tests/`.** `git status` confirms it: the only tree entries are the two Phase 1 reports, this report, and `tools/level_editor/`.

`tools/level_editor/` now holds **55 files** — 46 restored in Phase 1, 7 authored in Phase 1, 2 authored in Phase 2.

---

## 4. Exporter API and destination handling

```python
export_v6.export_level(project, dest_dir, *,
                       level_name=None,
                       validate_first=True,
                       carry_enemies_from=None) -> {filename: Path}

export_v6.render_all(project, level_name) -> {filename: text}   # no I/O
```

* **`dest_dir` is required and positional.** Nothing defaults to the repository, so a test cannot overwrite `src/level1/` by omission. Every proof in this task wrote to a `TemporaryDirectory`.
* **`validate_first=True` refuses to write anything** if the project has validation errors, raising `ExportRefused` carrying the `ValidationResult`. Every limit `validation_v6` enforces is one the engine build would fail on anyway; catching it here keeps the error next to the field that caused it.
* **`render_all` does no I/O at all**, so the generated text can be asserted on without a filesystem.
* **`carry_enemies_from`** copies a hand-authored `stage_enemies.asm` forward. That file is level-owned but *not* editor-generated — it names the enemy sprite-window slots — and a level directory is not buildable without it. Making the carry explicit is what let the scratch build work without inventing content.
* **`level_name`** defaults to the project's name, so nothing assumes `level1`.

---

## 5. The generated-file contract

### `stage_config.asm`
Emits `STAGE_METATILE_ROWS`, `STAGE_NO_SPAWN_ROW`, `STAGE_METATILE_COUNT`, `TERRAIN_BACKGROUND_COLOUR`, `TERRAIN_MC_COLOUR_1`, `TERRAIN_MC_COLOUR_2`, `TERRAIN_CHARACTER_COLOUR`, `TERRAIN_COLOUR_RAM`, `TERRAIN_GLYPH_COUNT`.

`STAGE_METATILE_COUNT` and `TERRAIN_GLYPH_COUNT` are **derived** from the model (`len(metatile_defs)`, `len(glyphs)`), never stored.

### `stage_charset.asm`
`terrainGlyphs:` … `terrainGlyphsEnd:` plus the self-checking `.if` guard, exactly the authored glyph count, eight bytes each, **no padding**.

### `stage_map.asm`
`metatileDefs:` … `METATILE_DEFS_END:` … `stageMetatileRows:` … `STAGE_METATILE_ROWS_END:`.

**The four labels are a build contract.** The Makefile splits this one file with two `awk` ranges into the halves the package emits at `$e000` and `$f130`:

```
awk '/^metatileDefs:/,/^METATILE_DEFS_END:/'            -> build/stage_map_defs.asm
awk '/^stageMetatileRows:/,/^STAGE_METATILE_ROWS_END:/' -> build/stage_map_rows.asm
```

Each must start its line, and the order is fixed. **`METATILE_DEFS_END:` was not in the task's list of expected labels** — the audit named three. Verifying against the Makefile rather than the brief is what caught it; without it the defs half would have swallowed the entire rows block.

### `stage_turrets.asm`
`TURRET_TOTAL`, `turretCols`, `turretRows`, sorted **descending by world row**, ties by ascending column.

### Numeric formatting
Values are right-aligned in three columns and joined by a **bare comma**: `",".join(f"{v:3d}")`. The leading space of `%3d` supplies the gap, so `","` renders as `", 85"`. My first attempt used `", "` and doubled it — the values were already correct, but every data line differed from the committed files. Fixing the separator made the data lines identical.

---

## 6. Stale assumptions removed

| assumption | corrected to |
|---|---|
| output at `src/generated/<level>/` | **`src/<level>/`** — the Makefile's own `LEVELDIR` default |
| map file `stage_test.asm` | **`stage_map.asm`** |
| a generated `stage_waves.asm` | **removed entirely** — the renderer and its resolver are deleted from `ka_export.py` |
| `SCROLL_FRAME_DIVIDER` emitted | **not emitted** |
| charset header "codes 96..223 … `$3B00-$3EFF`, 128 slots" | **`$0B00` in the `$0800` window**, ceiling **130** |
| `find_repo_root` probing `src/generated/level1/stage_test.asm` | `src/level1/stage_map.asm` |
| GUI export defaulting to `src/generated/<name>`, "5 .asm files" | `src/<name>`, "4 .asm files" |

Deleting the `stage_waves.asm` renderer rather than leaving it unused was deliberate: it emitted a file that **must not exist**, in the retired attack-catalogue dialect. Leaving it in place would have been a loaded gun. The *tests* were converted, not deleted — §8.

---

## 7. Semantic comparison against authoritative Level 1

Parsed values, not text diffs (headers and comments legitimately differ).

| artefact | result |
|---|---|
| `stage_config.asm` | every constant **equal**, except `SCROLL_FRAME_DIVIDER`, which is the one deliberately dropped |
| `stage_charset.asm` | **all 576 bytes identical** (72 glyphs × 8) |
| `stage_map.asm` defs | **all 544 bytes identical** (34 × 16) |
| `stage_map.asm` rows | **all 1050 bytes identical** (105 × 10) |
| `stage_turrets.asm` | `TURRET_TOTAL = 8`; rows `345, 337, 225, 217, 117, 109, 25, 5`; cols `17, 25, 29, 9, 25, 13, 25, 13` — **identical** |

Config values recovered: `STAGE_METATILE_ROWS = 105`, **`STAGE_NO_SPAWN_ROW = 340`**, `STAGE_METATILE_COUNT = 34`, `TERRAIN_GLYPH_COUNT = 72`, background 12, mc1 15, mc2 11, character 1, `TERRAIN_COLOUR_RAM = 8 | TERRAIN_CHARACTER_COLOUR`.

Derived and checked, never stored: playable progress **395**, terrain duration **63.2 s**.

**No mismatch was found**, so none of the three diagnoses the brief asked for was needed: the migration was not wrong, the exporter was not wrong, and the v5 fixture is genuinely the same terrain as current Level 1. The migrated project was not massaged in any way — it is the plain output of Phase 1's migration.

---

## 8. The nine stale tests

All nine are repaired. **Six were purely the stale path** and went green the moment `engine_data.py` and `editor.py` pointed at `src/level1/`. Three needed real conversion:

| test | before | after |
|---|---|---|
| `test_editor_asset_workflow_gui.py` | repo-root probe | **pass** (path fix) |
| `test_editor_workshop_gui.py` | repo-root probe | **pass** (path fix) |
| `test_metatile_capacity.py` | `src/generated/stage_config.asm` | **pass** (path + filename) |
| `test_metatile_delete.py` | same | **pass** (path + filename) |
| `test_turret_integration.py` | same | **pass** (path + filename) |
| `test_turret_unlimited.py` | same | **pass** (path fix) |
| `test_native_terrain_tiles.py` | asserted Level 1 *was* a synthetic generated set, with 9 turrets and 5 triggers | **converted**: asserts the native set is complete, self-consistent, unique-named, independent of Level 2's, and that Level 1 has its real **8** turrets |
| `test_level_packages.py` | read `src/generated/level{1,2}` out of the repo | **converted**: exports both project JSONs into scratch, keeps every independence assertion, and adds a guard that `src/generated/` must not reappear |
| `test_wave_schema.py` | the attack catalogue, `stage_waves.asm`, descending rows, `SCROLL_FRAME_DIVIDER` | **rewritten** against the contract that replaced it |

`test_wave_schema.py` could not be converted field by field because its entire subject was retired. It keeps its job — guarding the wave/trigger contract — and now asserts: the retired renderer is *gone* from `ka_export`, no waves file or scroll divider is ever emitted, the engine's `wave_programs.asm`/`wave_encounters.asm` remain authoritative, **ascending** `worldProgress` is accepted while **descending** (the old order) is rejected, a row above 255 is legal and splits 44/1, the six columns carry what they should, and a project with no encounters emits no encounter symbols anywhere.

Three further tests (`test_metatile_capacity`, `test_metatile_delete`, `test_turret_integration`) briefly broke as fallout from the `stage_test.asm` → `stage_map.asm` rename and were updated in the same pass.

---

## 9. Build proof

Method — the Makefile's own override, the same mechanism `make proof420` uses, so nothing here is a special testing path:

1. `make build LEVELDIR=src/level1` → capture authoritative `level1.prg` and `shmup.prg`.
2. Export the migrated v6 project into a scratch directory; carry `stage_enemies.asm` forward.
3. `make build LEVELDIR=<scratch>` → the build consumes the exported files.
4. Compare.
5. `make build` again in a `finally`, restoring `build/` to the authoritative artefact (verified).

### Package regions — editor-owned

| region | address | bytes | result |
|---|---|---|---|
| terrain map | `$E000-$E419` | 1050 | **IDENTICAL** |
| metatile defs | `$F130-$F34F` | 544 | **IDENTICAL** |
| stage header | `$F530-$F531` | 2 | **IDENTICAL**, encodes **340** |

### Package regions — authoritative encounters, not editor-exported

| region | address | bytes | result |
|---|---|---|---|
| movement pool | `$F532-$F565` | 52 | **unchanged** |
| wave definitions | `$F632-$F659` | 40 | **unchanged** |
| trigger columns | `$F736-$FB6D` | 1080 | **unchanged** |
| signature | `$FB70-$FB73` | 4 | **unchanged** |

### Whole files

```
level1.prg  7030 bytes  *** BYTE-IDENTICAL ***
shmup.prg                *** BYTE-IDENTICAL ***
```

---

## 10. The encounter package is untouched

`src/wave_programs.asm` and `src/wave_encounters.asm` are **unmodified** and remain the sole source of the movement pool, the wave definitions and the trigger columns.

The migrated v6 project has **empty** encounter lists by design (Phase 1 discarded the unmappable attack-catalogue data). The exporter therefore had to be prevented from turning that emptiness into generated bytes — doing so would have *erased* Level 1's four waves and two Droppers rather than exporting nothing. Two guards exist:

* `export_v6` has no encounter renderer at all, and `GENERATED_NAMES` is the four terrain/config/turret files;
* `test_wave_schema.py` exports the migrated project and asserts the strings `waveTrig`, `waveDef`, `trigRow`, `WAVE_TRIGGERS` and `progs` appear in **none** of the generated output.

The four encounter regions coming out unchanged in the build proof is the third, independent check.

---

## 11. Determinism

* exporting twice into different directories → **all four files byte-identical**;
* a project round-tripped through JSON exports **byte-identically**;
* LF endings, exactly one trailing newline, no absolute paths, no timestamps, no volatile identifiers;
* headers carry only the level's own name.

---

## 12. Test results

| suite | result |
|---|---|
| **all 25 editor tests** | **25 pass, 0 fail** |
| `test_v6_export.py` (new) | **61 checks** |
| `test_v6_migration.py` (Phase 1) | 52 checks, green |
| `test_v6_validation.py` (Phase 1) | 64 checks, green |
| `test_v6_roundtrip.py` (Phase 1) | 20 checks, green |
| the nine formerly-failing tests | **all nine pass** |

Baseline for comparison: Phase 1 ended at 15 pass / 9 fail. Phase 2 ends at **25 pass / 0 fail**.

The GUI still parses and imports; its export call site iterates the returned paths generically, so the four-path return needed no shim beyond the default-directory and title correction.

---

## 13. Deferred

* **Encounter import/export is Phase 3**, as scoped.
* **`import_generated_level.py` is stale and untested.** It reads `stage_test.asm` and `stage_waves.asm` from a generated directory. The second has ceased to exist, so the tool cannot work as written. No test covers it, and it is an *importer* — precisely what Phase 3 replaces with a real engine-data importer — so it was left alone rather than half-repaired into something that still could not do its job. **Flagged rather than fixed.**
* **No checked-in v6 Level 1 fixture was added.** The exporter tests migrate from the v5 source at run time, which keeps one authoritative terrain source rather than two and avoids a fixture that would falsely appear to carry encounters.
* **`build_levels.py`** still writes to a `GENERATED` directory constant; it is a v5-era batch script, not on the Phase 2 path, and its export calls now produce four files correctly.

---

## 14. Hygiene and repository status

* **Nothing committed. Nothing pushed.**
* `git status --short`:
  ```
  ?? reports/level-editor-contract-v2-specification.md    (audit, Phase 0)
  ?? reports/level-editor-v2-phase1-model-migration.md    (Phase 1)
  ?? reports/level-editor-v2-phase2-deterministic-exporter.md  (this report)
  ?? tools/level_editor/                                  (restored + Phase 1 + Phase 2)
  ```
* **No engine source, Makefile, package layout or `tests/` file was changed.** No scrolling, raster, multiplexer, renderer, terrain-runtime, turret-runtime, encounter-director or boss-lifecycle code was touched. The engine was never made to accept stale editor output — the exporter was made to reproduce the engine's data exactly.
* `build/` holds the **authoritative** artefact: the final `make build` ran with the default `LEVELDIR=src/level1` and `level1.prg` was verified byte-identical to the captured authoritative copy.
* **No VICE was launched.** This is a data-equivalence proof and needed none; `pgrep -x x64sc` was never non-empty.
* All exports and alternate builds went to a `TemporaryDirectory` or the session scratchpad. `__pycache__` was cleared.
* Disk: `build/` **344 KB** (current binary and symbols only, no per-run directories); session scratch **5.0 MB**, mostly the Phase 1 editor archive.

**Phase 3 was not begun.** No encounter importer, no movement-program or wave-definition or trigger exporter, no encounter GUI, no movement preview.
