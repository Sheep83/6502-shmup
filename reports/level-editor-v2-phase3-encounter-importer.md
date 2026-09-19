# Level Editor Contract v2 — Phase 3: authoritative encounter importer

**Date:** 2026-09-19
**HEAD at start:** `3718a45` *Boss hud bug fixed* — level with `origin/main`, 0 behind / 0 ahead.
**Working tree at start:** the Phase 1/2 editor work and three reports, untracked and intact.
**Scope:** Phase 3 only — import the engine's encounters into the v6 model. **No encounter exporter. No engine change.**
**Nothing committed. Nothing pushed.**

---

## 1. Headline result

The authoritative encounter data imports into the v6 model **losslessly**, and the proof is a byte comparison rather than an opinion:

| region | bytes | re-encoded from the v6 model vs `build/level1.prg` |
|---|---|---|
| movement pool | **52** | **IDENTICAL** |
| wave definitions | **40** | **IDENTICAL** |
| trigger columns | **1080** | **IDENTICAL**, zero padding included |

If the model could not hold something the engine authored, those bytes would differ.

The populated Level 1 project **validates with no errors and no warnings**, and the Phase 2 binary-equivalence proof still passes unchanged: `level1.prg` and `shmup.prg` remain byte-identical.

---

## 2. Preserved Phase 1 / Phase 2 state

Nothing was reset, cleaned or checked out over. HEAD is unchanged and `src/` is **byte-identical to HEAD** (`git diff HEAD -- src/` is empty). All earlier suites re-run green:

```
test_v6_migration.py       All 52 migration checks passed.
test_v6_validation.py      All 64 validation checks passed.
test_v6_roundtrip.py       All 20 round-trip checks passed.
test_v6_export.py          All 61 export checks passed.
```

---

## 3. Files

### New — 3 files

| file | lines | role |
|---|---|---|
| `tools/level_editor/asm_decl.py` | 294 | the bounded authored-declaration reader |
| `tools/level_editor/import_engine_v6.py` | 399 | engine → v6 conversion, plus reference encoders |
| `tools/level_editor/test_v6_import.py` | 331 | **74 checks** |

### Modified — 1 file

`import_generated_level.py` — a deprecation banner only; no behaviour changed.

### Unchanged

**No engine source, `Makefile`, package layout or `tests/` file.** `src/wave_programs.asm` and `src/wave_encounters.asm` are untouched. The Phase 1 and Phase 2 modules are untouched, except for the one improvement in §8.

`tools/level_editor/` now holds **58 files**.

---

## 4. Importer architecture

Parsing and domain knowledge are kept apart, as the brief asked:

```
src/movement_format.asm   ┐
src/encounter_format.asm  ├─> asm_decl.parse_files()  -> AsmSource (consts, lists)
src/wave_programs.asm     │        (knows no encounters)
src/wave_encounters.asm   ┘
                                   │
                          import_engine_v6            -> MovementProgram
                             (knows no assembler)        WaveDefinition
                                   │                     Trigger
                          validation_v6.validate()
```

`asm_decl.py` knows nothing about encounters; `import_engine_v6.py` knows nothing about assembler syntax. Model validation is **not** duplicated in the parser — the importer checks only what the *engine's own build guards* check plus the storage widths, and then hands the result to the normal v6 validator.

---

## 5. The supported KickAssembler subset

Deliberately tiny, and it raises rather than guesses:

```
.const NAME = <arith>
.var   NAME = <arith>
.var   NAME = List()[.add(<element>, ...)]...
.eval  NAME.add(<element>, ...)

<element> := <arith> | nested List() expression | the name of a .var list
<arith>   := + - * / and parentheses over decimal, $hex, %binary and
             identifiers bound earlier
```

**Control flow is skipped whole, never interpreted.** `.for` and `.if` blocks are tracked by brace depth and recorded. Four were skipped in this import:

```
movement_format.asm:126 .if      wave_programs.asm:134 .for
wave_programs.asm:143 .if        wave_encounters.asm:149 .if
```

`wave_programs.asm:134` is the loop that builds `progAt`/`progBytes`. Rather than pretend to execute assembler macros, the importer **derives** those offsets with the same arithmetic the engine uses (`WM_STAGE_SIZE * stages`) and then proves the result by byte comparison. Segments, labels, `.byte` emission, macros, functions and strings are all outside the subset; anything else fails with `file:line`.

---

## 6. Authoritative source syntax found

Verified unchanged from the audit at current HEAD:

```asm
// src/wave_programs.asm
.var progs = List()
.eval progs.add(List()
    .add(List().add(WM_STRAIGHT, 34, 6, 0))
    .add(List().add(WM_ARC, WM_QUARTER, 4, 0))
    .add(List().add(WM_EXIT, 0, 0, 0)))
.const PROG_SWEEP  = 0

// src/wave_encounters.asm
.var defSweep = List().add(4, 22, 0, 0, 64, 0, 20, 10, 0, PROG_SWEEP)
.var waveDefs = List().add(defSweep).add(defSTurn).add(defLinger).add(defLoop)
.var trigRow   = List().add(48, 52, 90, 126)
.var trigFire  = List().add(%00000101, %00000010, %00000101, %00000000)
.const WAVE_TRIGGERS = 4
```

Constants needing real evaluation: `SPECIES_RING = 0 * ENEMY_ANIM_STEPS`, `SPECIES_DROPPER = 1 * ENEMY_ANIM_STEPS` (→ 0 and **8**), `WM_QUARTER = WM_HEAD_LEN / 4` (→ 16), `WM_HEAD_CONT = $ff`.

---

## 7. What was imported

### Movement programs — 4, 13 records, 52 bytes

IDs are derived from the engine's own `PROG_*` symbols, minus the prefix, lowercased.

| id | stages | records |
|---|---|---|
| `sweep` | `STRAIGHT(34, +6, 0)` → `ARC(16 steps, 4/step, heading 0)` → `EXIT` | 3 |
| `s` | `ARC_MIRROR(12, 3/step, heading 12)` → `ARC(20, 3/step, **CONT**)` → `EXIT` | 3 |
| `linger` | `STRAIGHT(28, +3, +5)` → `HOLD(48, 0, +1)` → `ARC(12, 4/step, heading 10)` → `EXIT` | 4 |
| `loop` | `STRAIGHT(40, +4, +4)` → `ARC(76, 2/step, heading 8)` → `EXIT` | 3 |

Derived byte offsets: `sweep 0, s 12, linger 24, loop 40` — matching the audit exactly.

### Wave definitions — 4, 40 bytes

| id | count | interval | startX | startY | xStep | yStep | colour | heading | program |
|---|---|---|---|---|---|---|---|---|---|
| `sweep` | 4 | 22 | 0 | 64 | 0 | 20 | 10 | 0 | `sweep` |
| `s` | 3 | 26 | 90 | 30 | 28 | 0 | 3 | 12 | `s` |
| `linger` | 3 | 26 | 120 | 30 | 36 | 0 | 7 | 10 | `linger` |
| `loop` | 3 | 34 | 70 | 30 | 50 | 0 | 13 | 8 | `loop` |

**Byte 9 is authored as a program INDEX and emitted as a byte OFFSET** (`progAt.get(def.get(9))` in `src/level_package.asm`). The editor stores the program's **ID**; the offset is derived at encode time, which is what stops an offset disagreeing with the records it points at.

### Triggers — 4 live

| worldProgress | definition | species | fire mask | Dropper side |
|---|---|---|---|---|
| **48** | `sweep` | RING | `[0, 2]` | LEFT |
| **52** | `s` | DROPPER | `[1]` | LEFT |
| **90** | `linger` | RING | `[0, 2]` | LEFT |
| **126** | `loop` | DROPPER | `[]` | RIGHT |

Rows, species alternation and both Dropper sides are exactly as the accepted contract expected, verified from source rather than assumed. The two Droppers enter **LEFT then RIGHT**.

---

## 8. Padding, signedness and sentinels

**Padding.** The six trigger columns are 180 slots each and the tail is zero-filled. A zero row, a zero definition index and a zero species (`SPECIES_RING`) are each individually *legal*, so nothing about a padded slot distinguishes it from content — only `WAVE_TRIGGERS` does. The importer reads exactly `WAVE_TRIGGERS` entries, and a test asserts the remaining tail is all zero in the authoritative package, confirming the assumption it relies on.

**Widths are checked on the way in**, because Python integers are unbounded and the engine's are not:

| value | width enforced | why |
|---|---|---|
| stage frames / steps / frames-per-step | unsigned byte | emitted directly |
| stage `vx` / `vy` | **signed byte** (−128..127) | emitted `& $ff` |
| definition `xStep` / `yStep` | **signed byte** | emitted `& $ff` |
| definition `startX` | **9-bit** (0..511) | emitted lo + hi |
| definition launch heading | **0..63** | see below |
| trigger `worldProgress` | **16-bit** | emitted lo + hi |
| fire mask | unsigned byte | one bit per member |

**Sentinel.** `WM_HEAD_CONT` (`$ff`) on byte 3 of an `ARC`/`ARC_MIRROR` becomes the symbolic `"CONT"`; any other value must be a heading `0..63`. The S-turn is the case that matters: its first arc keeps its **explicit heading 12** and only the second carries `CONT`, which is precisely the distinction that stops the old stale-`wmPhase` dependency being recreated.

**One model correction, justified against engine source.** A definition's **launch heading** (byte 8) has no continuation sentinel — `src/waves.asm` build-errors on `def.get(8) >= WM_HEAD_LEN`. The importer initially range-checked it only as an unsigned byte, so `$ff` was accepted; a malformed-source test caught it. It now rejects any launch heading outside `0..63`, matching the engine's own guard. This is an importer tightening, not a model change; the Phase 1 validator already enforced the same rule.

---

## 9. Project overlay behaviour

```python
import_engine_v6.read_encounters(src_dir) -> ImportResult          # touches no project
import_engine_v6.import_encounters(project, src_dir, *, replace=False)
```

* Populates `movementPrograms`, `waveDefinitions` and `triggers` **only**.
* **Refuses to overwrite silently.** A project that already carries encounters raises `EncounterImportError` naming the counts and telling the caller to pass `replace=True`. The engine is the source of truth exactly once; after that, the editor's copy is the thing being edited.
* Terrain, palette, glyphs, metatile definitions, the map, turrets, stage dimensions and `noSpawnRow` are **not touched** — asserted by serialising all eight before and after and comparing.

After import: 105 rows, `noSpawnRow` 340, 8 turrets, 72 glyphs, 34 metatile defs — all unchanged; capacity `movementRecords 13/64`, `movementBytes 52/256`, `waveDefinitions 4/26`, `triggers 4/180`.

---

## 10. Determinism and JSON shape

* importing twice from identical source → **byte-identical project JSON** (67,209 bytes);
* `save → load → save` is a fixed point with encounters present;
* no engine paths, no source filenames, no timestamps, **no derived byte offsets** in the JSON;
* a definition stores `"movementProgram": "sweep"` — an ID, not an offset;
* triggers are stored as semantic objects (`species: "RING"`, `fireMask: [0, 2]`, `dropperSide: "RIGHT"`), **not** as the six physical columns.

---

## 11. Malformed source fails loudly

Seventeen negative cases, each built by perturbing the real source in scratch so the genuine parser path is exercised:

| case | message |
|---|---|
| unknown movement opcode | `program 'sweep' stage 0 names movement opcode 9, which is not one of [...]` |
| stage not four values | `program 'sweep' stage 0 is not 4 values: [0, 34, 6]` |
| missing `PROG_*` | `wave_encounters.asm:128: unknown identifier 'PROG_LOOP'` |
| duplicate `PROG_*` value | `PROG_* symbols PROG_SWEEP and PROG_LOOP share the value 0; an imported id would be ambiguous` |
| definition → missing program | `wave definition 'loop' names movement program index 9, but the source declares 4` |
| trigger → missing definition | `trigger 0 names wave definition index 9, but the source declares 4` |
| unknown species | `trigger 0 names species 3, which is not one of [('DROPPER', 8), ('RING', 0)]` |
| unknown Dropper side | `trigger 0 names Dropper side 7, ...` |
| mismatched column lengths | `the trigger columns are not all the same length: {'trigRow': 3, ...}` |
| `WAVE_TRIGGERS` beyond rows | `WAVE_TRIGGERS is 9 but the columns hold only 4 entries` |
| `WAVE_DEFS` disagreeing | `WAVE_DEFS is 3 but waveDefs holds 4 definition(s)` |
| `$ff` as a launch heading | `wave definition 'sweep' launch heading is not a launch heading 0..63: 255` |
| unknown identifier | `wave_programs.asm:63: unknown identifier 'WM_NOPE'` |
| expression outside the subset (`<<`) | `wave_encounters.asm:213: unsupported character '<'` |
| duplicate declaration | `wave_encounters.asm:308: 'WAVE_TRIGGERS' is already defined (wave_encounters.asm:306)` |
| velocity past a signed byte | `program 'sweep' stage 0 vx does not fit a signed byte: 200` |
| trigger row past 16 bits | `trigger 3 worldProgress does not fit sixteen bits: 70000` |
| unsupported `.eval` form | `wave_programs.asm:147: the only supported .eval form is NAME.add(...)` |

---

## 12. Test results

| suite | result |
|---|---|
| **all 26 editor tests** | **26 pass, 0 fail** |
| `test_v6_import.py` (new) | **74 checks** |
| `test_v6_export.py` (Phase 2) | 61 checks, green — build proof re-run |
| `test_v6_migration.py` / `_validation` / `_roundtrip` (Phase 1) | 52 / 64 / 20, green |

### Phase 2 binary equivalence, re-run after the importer exists

```
*** THE WHOLE level1.prg IS BYTE-IDENTICAL ***
*** shmup.prg IS BYTE-IDENTICAL *** (charset + turret tables live there)
    build/ restored from src/level1: True
```

The four encounter package regions still read *"unchanged, still supplied by `src/wave_*.asm`"* — the Phase 2 exporter correctly ignores the newly-populated encounter model, which was the specific coupling risk this rerun exists to catch.

---

## 13. `import_generated_level.py`

**Left deprecated, with a banner explaining why.** Its job is unrelated: it inverts the *v5* `ka_export` to rebuild a *v5* `level.json` from generated **terrain/config/turret** assembler, and it reads `stage_test.asm` and `stage_waves.asm` from `src/generated/<level>/` — a directory and two filenames that have all been retired.

Refactoring it onto the current layout would create a **second authoritative terrain import path** alongside the v6 model that Phase 2 already round-trips byte-for-byte, which is exactly the duplication Contract v2 exists to remove. The banner now points readers at `import_engine_v6.py` and states plainly that this is not the encounter importer. No test references it.

---

## 14. Deferred to Phase 4

* **The encounter exporter.** Nothing writes `src/wave_programs.asm`, `src/wave_encounters.asm` or encounter bytes into `LEVEL1`. Those files have not moved, carry no generated banner, and the Makefile does not consume editor-generated encounter ASM.
* The `reference_encode_*` functions produce **bytes for verification only** — no files, no assembler. Their docstring says so, and says where the real exporter will live.
* Movement preview and the trajectory simulator remain deferred (Contract v2 §7.5, phases 4/6), as recorded in Phase 1.

---

## 15. Unresolved questions

1. **ID collisions across namespaces.** `sweep`, `s`, `linger` and `loop` name both a movement program and a wave definition, because the engine's `PROG_*` and `WAVE_DEF_*` symbols use the same words. The v6 model validates uniqueness *within* each list, so this is legal and faithful — but a future UI may want to disambiguate them visually.
2. **`WAVE_DEF_S` yields the id `s`**, which is terse. It is the engine's own name and stable; renaming would invent content.
3. **The importer reads four files by fixed name** from a `src` directory. Multi-level packaging is still undecided (carried forward from the audit), so nothing was generalised speculatively.

---

## 16. Hygiene and repository status

* **Nothing committed. Nothing pushed.**
* `git status --short`:
  ```
  ?? reports/level-editor-contract-v2-specification.md
  ?? reports/level-editor-v2-phase1-model-migration.md
  ?? reports/level-editor-v2-phase2-deterministic-exporter.md
  ?? reports/level-editor-v2-phase3-encounter-importer.md
  ?? tools/level_editor/
  ```
* **`git diff HEAD -- src/` is empty.** No engine source changed: not `waves.asm`, not the encounter/movement/trigger runtime, not Dropper/token/protector, not boss or no-spawn behaviour, not the package layout, raster, renderer, multiplexer, scrolling or HUD.
* `build/` holds the **authoritative** artefact — the export test's `finally` rebuilds with the default `LEVELDIR=src/level1` and verifies it.
* **No VICE was launched**; `pgrep -x x64sc` was never non-empty.
* All malformed-source fixtures were written to `tempfile` directories and removed. `__pycache__` cleared.
* Disk: `tools/level_editor/` **840 KB** (58 files), `build/` **344 KB**, session scratch **5.0 MB**.

**Phase 4 was not begun.**
