# Level Editor Contract v2 — Phase 4: encounter exporter and the complete round trip

**Date:** 2026-09-19
**HEAD at start:** `3718a45` *Boss hud bug fixed* — level with `origin/main`, 0 behind / 0 ahead.
**Working tree at start:** the Phase 1–3 editor work and four reports, untracked and intact.
**Scope:** Phase 4 — production encounter export, level ownership, build integration, round-trip proof. **No GUI, no preview.**
**Nothing committed. Nothing pushed.**

---

## 1. Headline result

The loop closes.

```
src/level1/*.asm  ->  importer  ->  v6 project  ->  exporter  ->  src/level1/*.asm
                                        |
                                    the build
                                        v
              level1.prg  08ff4116…  BYTE-IDENTICAL to the pre-Phase-4 baseline
              shmup.prg   e726d430…  BYTE-IDENTICAL to the pre-Phase-4 baseline
```

`levels/level1/level.v6.json` now represents the **complete** authored Level 1 — terrain, config, charset, map, metatile definitions, turrets, movement programs, wave definitions, absolute triggers and the no-spawn boundary — and regenerating the whole level from it reproduces both binaries exactly.

---

## 2. Baseline

Captured before any change, from a clean `make build` at HEAD:

| artefact | bytes | SHA-256 |
|---|---|---|
| `build/level1.prg` | 7,030 | `08ff411658468c2c9cab3cc942c752c6d8361787a0a4d3af401f28b5713d5828` |
| `build/shmup.prg` | 51,164 | `e726d430c5e9a5aeba9fe687d53f431d23a536a1df1ad99aa24531d3dd411918` |

Both hashes are unchanged at the end of the phase.

---

## 3. The finding that shaped the whole design

**KickAssembler resolves `#import "x.asm"` against the importing file's own directory before it looks at any `-libdir`.**

Measured, not assumed. I put a deliberately altered `wave_encounters.asm` (trigger row 48 → 49) into a scratch `LEVELDIR` and rebuilt:

```
IDENTICAL -> the libdir copy was IGNORED; src/ wins
```

So while `src/wave_programs.asm` and `src/wave_encounters.asm` existed, a level-owned copy was **inert**: the engine kept using the src/ ones and editing the level-owned files did nothing at all. That is worse than duplicate authority — it is duplicate authority where the wrong copy silently wins.

Two consequences, both load-bearing:

1. the move had to be a **real move** (`git rm` of the src/ copies), not a copy;
2. once moved, the level-owned files could no longer reach the engine-owned vocabulary they import, so the build needed `-libdir $(ROOT)/src`.

---

## 4. Files

### Moved (deleted from `src/`, regenerated under `src/level1/`)

| from | to |
|---|---|
| `src/wave_programs.asm` *(deleted, staged)* | `src/level1/wave_programs.asm` *(new, generated)* |
| `src/wave_encounters.asm` *(deleted, staged)* | `src/level1/wave_encounters.asm` *(new, generated)* |

The engine-owned **vocabulary** stays in `src/`: `movement_format.asm`, `encounter_format.asm`. Neither is duplicated per level.

### New

| file | lines | role |
|---|---|---|
| `tools/level_editor/levels/level1/level.v6.json` | 4,256 | **the canonical Level 1 project** |
| `tools/level_editor/export_level.py` | 82 | the one export command |
| `tools/level_editor/test_v6_phase4_roundtrip.py` | 231 | 37 checks |
| `src/level1/wave_programs.asm` | 71 | generated |
| `src/level1/wave_encounters.asm` | 107 | generated |

### Modified (tracked)

| file | change |
|---|---|
| `Makefile` | one `-libdir $(ROOT)/src` on each of the two assembler invocations, with the reason |
| `src/level1/stage_config.asm` | regenerated — **the only data change in the whole set is the removal of `SCROLL_FRAME_DIVIDER`** |
| `src/level1/stage_charset.asm`, `stage_map.asm`, `stage_turrets.asm` | regenerated — **data identical**, headers/comments only |
| `tools/gen_proof420.py` | carries the encounter source into the proof directory; rescales the config comment it was leaving self-contradictory |

### Modified (untracked, inside `tools/level_editor/`)

`export_v6.py` (encounter renderers, six-file export), `import_engine_v6.py` (split engine/level paths), `engine_data.py` (`SCROLL_FRAME_DIVIDER` now optional), plus four test files repointed at the new boundary.

---

## 5. Canonical project

**`tools/level_editor/levels/level1/level.v6.json`** — `formatVersion 6`, 67,209 bytes, validates **0 errors / 0 warnings**.

It was produced deterministically, never hand-transcribed:

```
levels/level1/level.json  (v5)  --migration_v6-->  v6 terrain/turrets
                                --import_engine_v6--> + encounters
```

It stores **semantic references only** — a definition names `"movementProgram": "sweep"`, not a byte offset; triggers are objects with `species`, `fireMask` and `dropperSide`, not six columns. Asserted: the strings `progAt`, `byteOffset`, `offset`, `rowLo`, `rowHi` appear nowhere in it.

`levels/level1/level.json` (v5) and `levels/level2/level.json` (v5) remain as the **legacy migration sources** the Phase 1 tests exercise. There is exactly one v6 project in the tree.

---

## 6. Exporter architecture

Phase 2's `export_v6` extended from four files to six:

```python
TERRAIN_NAMES   = (stage_config, stage_charset, stage_map, stage_turrets)
ENCOUNTER_NAMES = (wave_programs, wave_encounters)
GENERATED_NAMES = TERRAIN_NAMES + ENCOUNTER_NAMES

export_v6.export_level(project, dest, *, level_name, validate_first=True,
                       carry_enemies_from=None)
```

Everything physical is **derived at render time** from the semantic model: program indices from list order, program byte offsets from cumulative `4 × stages`, definition indices from list order, the six trigger columns from the trigger objects, counts from `len()`, padding from the package layout. None of it is stored in JSON.

`validate_first=True` refuses to write anything if the project has errors; a v6 id that cannot become an assembler symbol is refused by name rather than producing source that will not assemble.

---

## 7. Generated representation

### `wave_programs.asm`

```asm
#importonce
#import "movement_format.asm"

.var progs = List()

// --- 1: S ---------------------------------------------------------
.eval progs.add(List()
    .add(List().add(WM_ARC_MIRROR, 12, 3, 12))
    .add(List().add(WM_ARC, 20, 3, WM_HEAD_CONT))
    .add(List().add(WM_EXIT, 0, 0, 0)))

.const PROG_SWEEP             = 0
...
.var progAt = List()
.var progBytes = 0
.for (var p = 0; p < progs.size(); p++) { ... }
.if (progBytes > 256) { .error "..." }
```

**The `.for` loop is emitted, not resolved.** `src/level_package.asm` emits a definition's tenth byte as `progAt.get(def.get(9))`, so the offsets are computed by the assembler from the pool it can see. Writing them out would let an emitted offset disagree with the records it points at — the one thing this arrangement exists to prevent.

`"CONT"` is emitted as the symbolic `WM_HEAD_CONT`, never as `$ff`. Signed velocities are emitted as signed decimals; `src/level_package.asm` applies `& $ff`.

4 programs, 13 records, **52 bytes**, offsets **0, 12, 24, 40**.

### `wave_encounters.asm`

```asm
.var defSweep = List().add(
    4, 22,                    // count, interval
    0, 0,                     // startX = 0, nine bits split low/high
    64,                       // startY
    0, 20,                    // xStep, yStep -- signed, per member
    10,                       // colour
    0,                        // launch heading
    PROG_SWEEP)               // movement program INDEX

.var waveDefs = List().add(defSweep).add(defS).add(defLinger).add(defLoop)
.const WAVE_DEFS              = 4
.const WAVE_DEF_SWEEP         = 0
...
.var trigRow      = List().add(48, 52, 90, 126)
.var trigDef      = List().add(WAVE_DEF_SWEEP, WAVE_DEF_S, WAVE_DEF_LINGER, WAVE_DEF_LOOP)
.var trigSpecies  = List().add(SPECIES_RING, SPECIES_DROPPER, SPECIES_RING, SPECIES_DROPPER)
.var trigSide     = List().add(DROP_SIDE_LEFT, DROP_SIDE_LEFT, DROP_SIDE_LEFT, DROP_SIDE_RIGHT)
.var trigFire     = List().add(%00000101, %00000010, %00000101, %00000000)
.const WAVE_TRIGGERS          = 4
```

4 definitions, **40 bytes**. Six parallel columns, **no interleaved record**. Species, sides and program references are symbolic; fire masks are binary literals over member index. **`WAVE_TRIGGERS` is the live count (4), not the 180-slot capacity.**

### Capacity and padding

Unchanged, and still enforced by the package rather than the exporter: `src/level_package.asm` pads each trigger column to `LEVELPKG_TRIG_SLOTS` (180) with zeroes, so the generated source never mentions the capacity. Budgets are untouched — movement 256 bytes / 64 records, definitions 26 × 10, triggers 180 × 6 columns. The exporter refuses anything over them before writing.

---

## 8. Build integration

```diff
-	java -jar "$(KA)" src/main.asm -libdir "$(LEVELDIR)" \
+	java -jar "$(KA)" src/main.asm -libdir "$(LEVELDIR)" -libdir "$(ROOT)/src" \
 	      -odir "$(ROOT)/build" -o "$(PRG)" -vicesymbols
 	java -jar "$(KA)" src/level_package.asm -libdir "$(ROOT)/build" \
-	      -libdir "$(LEVELDIR)" -odir "$(ROOT)/build" -o "$(LEVELPRG)"
+	      -libdir "$(LEVELDIR)" -libdir "$(ROOT)/src" \
+	      -odir "$(ROOT)/build" -o "$(LEVELPRG)"
```

That is the entire build change. No runtime semantics, no package addresses, no capacity budgets. Verified from the emitted memory map:

```
$e000-$e419 level map          $f532-$f565 level movement pool
$f130-$f34f level metatile defs $f632-$f659 level wave definitions
$f530-$f531 level stage header  $f736-$fb6d level wave triggers
                                $fb70-$fb73 level signature
```

The package's last byte is `$fb73`; `$fffa-$ffff` is untouched.

**The Makefile does not invoke Python.** Generation is explicit (`export_level.py`), so `make` cannot change the program's content and every regeneration is reviewable in the diff.

---

## 9. Export command

```
python3 tools/level_editor/export_level.py                 # canonical Level 1 -> src/level1
python3 tools/level_editor/export_level.py --check         # validate only, write nothing
python3 tools/level_editor/export_level.py --dest DIR      # somewhere else
```

Loads the canonical project, validates, exports all six files, carries `stage_enemies.asm` forward, prints what it wrote, and exits non-zero on validation failure or export refusal — writing nothing when it does.

---

## 10. Semantic equivalence

The deleted `src/wave_*.asm` at HEAD versus the generated `src/level1/wave_*.asm`, both read through the Phase 3 importer:

```
HEAD originals vs level-owned generated: SEMANTICALLY IDENTICAL = True
  movement pool bytes identical:   True
  wave definition bytes identical: True
  trigger columns identical:       True
```

Terrain side, parsed values against the pre-Phase-4 committed files:

| artefact | result |
|---|---|
| `stage_charset.asm` | 576 bytes **identical** (72 glyphs × 8) |
| `stage_map.asm` defs | 544 bytes **identical** (34 × 16) |
| `stage_map.asm` rows | 1050 bytes **identical** (105 × 10) |
| `stage_turrets.asm` | `TURRET_TOTAL 8`, rows `345…5`, cols `17…13` **identical** |
| `stage_config.asm` | every constant identical **except** the retired `SCROLL_FRAME_DIVIDER`, deliberately dropped |

---

## 11. Binary proof

Package regions, scratch build from the exported sources versus the pre-Phase-4 baseline:

| region | address | bytes | result |
|---|---|---|---|
| terrain map | `$E000-$E419` | 1050 | **IDENTICAL** |
| metatile defs | `$F130-$F34F` | 544 | **IDENTICAL** |
| stage header | `$F530-$F531` | 2 | **IDENTICAL** (encodes 340) |
| movement pool | `$F532-$F565` | 52 | **IDENTICAL** |
| wave definitions | `$F632-$F659` | 40 | **IDENTICAL** |
| trigger columns | `$F736-$FB6D` | 1080 | **IDENTICAL**, padding included |
| signature | `$FB70-$FB73` | 4 | **IDENTICAL** |

```
level1.prg  08ff411658468c2c9cab3cc942c752c6d8361787a0a4d3af401f28b5713d5828  BYTE-IDENTICAL
shmup.prg   e726d430c5e9a5aeba9fe687d53f431d23a536a1df1ad99aa24531d3dd411918  BYTE-IDENTICAL
```

---

## 12. Idempotence and fixed points

```
export N   vs N+1 identical: YES
export N+1 vs N+2 identical: YES
rebuild after repeated exports: level1.prg and shmup.prg still byte-identical
CLI scratch output vs production files: identical (destination does not affect content)
```

No timestamp, order or formatting churn; no generated file modifies itself.

**Import/export fixed point**, after ownership moved:

```
generated ASM -> importer -> v6 model        : semantically identical to the canonical project
model -> exporter -> ASM                     : BYTE-IDENTICAL, all six files
committed src/level1/ files                  : ARE the exporter's output, byte for byte
v6 JSON save -> load -> save                 : byte-identical (67,209 bytes)
```

One caveat worth stating plainly: the *first* export replaced the four hand-committed terrain files with generated text. That is the intended one-time ownership transfer, not instability — the data was already proven identical in Phase 2, and every export after it is a no-op.

---

## 13. Test results

### Editor — 27 files, 27 pass, 0 fail

| suite | checks |
|---|---|
| `test_v6_migration.py` (Phase 1) | **52** |
| `test_v6_validation.py` (Phase 1) | **64** |
| `test_v6_roundtrip.py` (Phase 1) | **20** |
| `test_v6_export.py` (Phase 2, extended) | **63** |
| `test_v6_import.py` (Phase 3) | **74** |
| `test_v6_phase4_roundtrip.py` (**new**) | **37** |
| **v6 total** | **310** |

Four existing tests were repointed at the boundary Phase 4 moved — not weakened:

* `test_v6_export.py` — now loads the **canonical** v6 project rather than the bare v5 migration (exporting the migration would ship a Level 1 with no waves at all), and asserts six generated files. Its encounter-region assertions changed from *"unchanged, still supplied by src/wave_*.asm"* to *"IDENTICAL, exported from the canonical v6 project"*.
* `test_wave_schema.py` — the Phase 2 "no encounter export" era is over; it now asserts six files, that `src/level1/` owns the encounter source, and that **`src/` holds no shadowing copy**.
* `test_v6_import.py` — its malformed-source fixtures were written against hand-authored spacing that the generated files no longer have. They are now **regex-based and assert they matched**, so a formatting change breaks the fixture loudly instead of silently testing nothing. Two fixtures had been doing exactly that.
* `engine_data.py` — `SCROLL_FRAME_DIVIDER` is now read-if-present rather than required, because the generated config correctly omits it. Without this, eight path-dependent tests failed the moment Phase 2's decision reached the production file.

### Engine / gameplay — 15 suites

**12 ALL PASS:** `boot`, `production`, **`wave_triggers`**, **`movement_pool`**, **`no_spawn_row`**, `boss`, `lifecycle`, `player_death`, `bank2_arena`, `boss_hud_transition`, `heat_cadence`, `turret_regression`.

The three bolded suites are the ones that would break first if the encounter move were wrong — absolute trigger scheduling with no wrap after exhaustion, movement-program semantics including the Stage 2 ARC entry contract, and the boss quiet zone. All pass.

**3 with failures, every one matching the pre-existing baseline recorded in the Phase 1 report exactly:**

| suite | failures | baseline |
|---|---|---|
| `token_encounter` | protector ascent `runs {}`, `schedBuildDefer 1` | identical |
| `dropper_flight` | `schedBuildDefer 1` | identical |
| `level_assets` | window pointers `[]`, `publishSkip 12`, `schedBuildDefer 1` | identical |

No gameplay test was rewritten. The only fixture path change was `tools/gen_proof420.py`, which genuinely required it: the encounter source is level-owned now, so a level directory without it does not assemble.

**420-row long-stage proof:** `make proof420` regenerates and builds — 420 metatile rows, stage end 1655, no-spawn row 1600, all eight turrets spread across the four copies. While fixing it I found the generated config's own comment still quoted the 105-row stage end (395) after the constants had been rescaled, so `gen_proof420.py` now rescales the prose too rather than shipping a file that contradicts itself.

---

## 14. VICE hygiene

The engine suites launch VICE through the harness, which owns each PID and reaps it in a `finally`. `pgrep -x x64sc` was empty before the run and **empty after it**. No broad `pkill`, no `killall`, no user-launched instance touched, no window raised — every launch used `-console`.

---

## 15. Deferred to Phase 5

* **The encounter authoring GUI.** No widgets, no timeline, no canvas changes. The GUI still parses and imports, and `engine_data` still loads the current level — but it is a v5-model editor and cannot open a v6 project. Bridging it is Phase 5's first job.
* **Movement preview and the trajectory simulator** (Contract v2 §7.5) remain deferred. `src/waves.asm` still owns the flight proof at assembly time; the editor still refuses to half-implement it.
* `import_generated_level.py` remains deprecated with its banner.

---

## 16. Unresolved questions

1. **`level.v6.json` is not regenerable by a committed command.** It was produced by `migration_v6` + `import_engine_v6`, but nothing in the tree re-runs that pipeline — and it should not, now that the JSON is the editable source and the engine files are derived from *it*. The provenance is recorded here and in the Phase 3 report; a one-shot `--from-engine` flag on the CLI would make it reproducible if that is ever wanted.
2. **`build_levels.py` and `acceptance_terrain_workshop.py`** are v5-era batch scripts that still call the v5 exporter. They work, and no test depends on their output, but they now produce a *subset* of a level directory (no encounter files). They belong to the v5 model and should retire with it.
3. **`levels/level2/level.json`** still migrates cleanly but has no engine counterpart; multi-level packaging remains undecided, as it has since the audit.
4. **The generated files are committed artefacts derived from a committed source.** That is deliberate — the assembler build stays a plain build — but it means a reviewer must trust that `src/level1/*.asm` matches `level.v6.json`. `test_v6_phase4_roundtrip.py` asserts exactly that, so CI catches a stale regeneration.

---

## 17. Repository status

**Nothing committed. Nothing pushed. No tag created.** HEAD is still `3718a45`.

```
 M Makefile
 M src/level1/stage_charset.asm
 M src/level1/stage_config.asm
 M src/level1/stage_map.asm
 M src/level1/stage_turrets.asm
D  src/wave_encounters.asm          <- staged deletion (moved)
D  src/wave_programs.asm            <- staged deletion (moved)
 M tools/gen_proof420.py
?? reports/level-editor-contract-v2-specification.md
?? reports/level-editor-v2-phase1-model-migration.md
?? reports/level-editor-v2-phase2-deterministic-exporter.md
?? reports/level-editor-v2-phase3-encounter-importer.md
?? reports/level-editor-v2-phase4-complete-roundtrip.md
?? src/level1/wave_encounters.asm
?? src/level1/wave_programs.asm
?? tools/level_editor/
```

| category | files |
|---|---|
| **modified, tracked** | `Makefile`, four `src/level1/stage_*.asm`, `tools/gen_proof420.py` |
| **deleted, staged** | `src/wave_programs.asm`, `src/wave_encounters.asm` |
| **new, untracked** | `src/level1/wave_programs.asm`, `src/level1/wave_encounters.asm`, five reports, `tools/level_editor/` (61 files: 46 restored in Phase 1, 15 authored across Phases 1–4) |
| **generated production files** | the six under `src/level1/` |
| **canonical project** | `tools/level_editor/levels/level1/level.v6.json` |

The two deletions are staged because `git rm` is how a move is expressed; nothing else is staged and no commit was made. Phase 1–3 intermediate work is untouched.

**No engine runtime was changed.** No `src/waves.asm`, movement, trigger, Dropper/token/protector, boss, no-spawn, renderer, raster, multiplexer, scroll or HUD code. The only non-generated engine-side edits in the entire phase are one `-libdir` per assembler invocation in the Makefile.

---

## 18. Hygiene

* `build/` **356 KB** — current binary and symbols plus the `proof420/` capacity fixture; no per-run directories. `build/level1.prg` is the authoritative artefact and byte-identical to the baseline.
* `tools/level_editor/` **944 KB**, 61 files. `__pycache__` cleared.
* Session scratch **5.3 MB**: the Phase 1 editor archive, the baseline binaries, and the comparison export directories. Every scratch build used `TemporaryDirectory` or the scratchpad; none wrote into the repository.
* No emulator processes left running.

---

## 19. Acceptance

All twenty-two Phase 4 criteria are met: movement programs, wave definitions and six-column triggers export to production ASM; padding and capacity are unchanged; the 52/40/1080 byte regions are exact; the canonical project carries the imported encounters; the generated sources are level-owned and consumed by the build; there is exactly one production copy; `level1.prg` and `shmup.prg` are byte-identical to the pre-Phase-4 baseline; export is idempotent; ASM↔model and JSON round trips are fixed points; Phases 1–3 remain green; the new exporter tests pass; the gameplay regressions match their recorded baseline; no runtime was redesigned; no GUI work was bundled in; nothing was committed or pushed.

**Phase 5 was not begun.**
