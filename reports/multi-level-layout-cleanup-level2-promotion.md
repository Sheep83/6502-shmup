# Multi-level layout cleanup and Level 2 promotion

The repository now has two real levels, each with one obvious editor project and
one obvious generated package. The PCB prototype is Level 2. Level 1's authored
content is byte-for-byte what it was, and the one Level 1 source file that
changed is a two-line symbol rename proven not to move a single byte of the
built program.

**Runtime Level 1 → Level 2 transition was NOT implemented.** Nothing was
committed or pushed.

---

## 1. Starting state

| | |
|---|---|
| HEAD | `4e0d713c80cad3770f8a08b4ab91eb3e67011cc6` — *Authored waves built into level 1* |
| Branch / upstream | `main` … `origin/main`, in sync |
| Working tree | clean apart from the previous task's untracked reports and the PCB prototype |
| VICE running | none |

`AGENTS.md` read first. The rules that bound this task: manual visual output is
authoritative; a green instrument can be wrong; **do not weaken a correctness
check to make a change pass**; strict VICE PID ownership; no per-run build
directories; do not commit or push.

---

## 2. Pre-cleanup inventory and classification

Everything level-shaped in the tree, classified before anything was deleted or
moved.

| Path | Class | Disposition |
|---|---|---|
| `tools/level_editor/levels/level1/level.v6.json` | **1. authoritative Level 1** | untouched |
| `src/level1/*.asm` (7 files) | **1. authoritative Level 1** | untouched except the symbol rename (§7) |
| `tools/level_editor/levels/level2pcb/level.v6.json` | **2. PCB Level 2 to promote** | promoted to `levels/level2/` |
| `tools/level_editor/levels/level2pcb/README.md` | 2. supporting doc | rewritten for the new identity |
| `tools/level_editor/levels/level2pcb-blue/level.v6.json` | **5. disposable generated output** | deleted — a palette study, reproducible with `--palette=blue` |
| `tools/level_editor/levels/level1/level.json` | **8. ambiguous → investigated** | **v5**, 72 glyphs / 34 metatiles, stale. Live input to 8 test files → **moved to fixtures**, not deleted |
| `tools/level_editor/levels/level2/level.json` | **8. ambiguous → investigated** | **v5**, 48 glyphs / 16 metatiles, the old planet-surface export proof. Live input to 3 test files → **moved to fixtures** |
| `tools/level_editor/fixtures/*.json` (2) | 3. controlled test fixtures | untouched |
| `tools/level_editor/terrain_repository/repository.json` | 3. editor asset repository | untouched |
| `tools/level_editor/wave_repository/repository.json` | 3. editor asset repository (v5, dormant) | untouched |
| `tools/level_editor/*.py` (39 sources, 38 tests) | 3. editor source/tooling | only path constants updated |
| `src/*.asm` (engine) | 3. engine source | only the symbol rename |
| `src/mnt/data/*.png` | 3. art asset | untouched — not level data |
| `src/generated/` | 7. obsolete generated ASM | **did not exist**; already gone before this task |
| `reports/**` | 4. documentation | untouched |
| `build/**` | 5. disposable build output | rebuilt to canonical Level 1 at the end |

### The one judgement call worth spelling out

The two v5 `level.json` files were the only genuinely ambiguous items, and they
were **both** obsolete level data *and* live test inputs — read by
`test_v6_migration`, `test_v6_import`, `test_v6_export`, `test_v6_roundtrip`,
`test_level_packages`, `test_native_terrain_tiles`, `test_wave_schema`,
`test_v6_phase5a_gui`, plus `build_levels.py`, `install_level1_terrain.py`,
`author_level1_five_enemy.py` and `acceptance_terrain_workshop.py`.

Deleting them would have destroyed the v5→v6 migration coverage. Leaving them
would have kept a stale `level.json` sitting beside the authoritative
`level.v6.json` in the canonical directory — exactly the ambiguity this task
exists to remove, and it also blocked `levels/level2/` as the promotion target.

They were therefore **moved, not deleted**, to
`tools/level_editor/fixtures/legacy_v5/levelN/level.json`. Git records both as
**100% renames**, and the hashes confirm it:

```
rename tools/level_editor/{levels => fixtures/legacy_v5}/level1/level.json (100%)
rename tools/level_editor/{levels => fixtures/legacy_v5}/level2/level.json (100%)

e0b7ecd1a5bc7487ed3dbca461adc1ff49ed388579d457cfa6774138b9f4d094  fixtures/legacy_v5/level1/level.json
e0b7ecd1a5bc7487ed3dbca461adc1ff49ed388579d457cfa6774138b9f4d094  (the original hash)
```

This satisfies both instructions at once: the obsolete level JSON leaves the
canonical location, and the controlled fixtures survive. It also *decouples* the
migration tests from the production Level 1 path, which §10 explicitly asks for.

---

## 3. Level 1 snapshot and hashes

Snapshotted before any change, to a disposable location outside every path
touched (`…/scratchpad/cleanup/snapshot/`, 11 files).

```
e0b7ecd1a5bc7487ed3dbca461adc1ff49ed388579d457cfa6774138b9f4d094  levels/level1/level.json      (the v5 file, now a fixture)
c2f0f94164811dfb851a3a2a404f558c3dc6a44027c31d9a40b616e6646037ed  levels/level1/level.v6.json
6a84ecc8ac01bbd07c4f22dd92747caa044448aa27ee4e0410b106b346e960e1  src/level1/stage_charset.asm
9085db3b1d2c0a28b3cd0385f82c529188921f797a2550848e49b3242b10c13f  src/level1/stage_config.asm
f6fb0d253b8a650e5a01121aefc7bc2220d17a881b5e44a31179e1065b7cb7ee  src/level1/stage_enemies.asm
667705ec63ba77b39adacf6b2fa6f20066116b419013cd2780fa2579f37da89f  src/level1/stage_map.asm
86675fa5463240bb1b983446735876afd693935b432c472eb8f2d04614c9cc0d  src/level1/stage_turrets.asm
0e072e0efc265a3a1a0d5486fb69e3040e0c366c2984da890da8abba9c43e4fd  src/level1/wave_encounters.asm
d9903293de7529e93dc249c5cb152a58329e15db595e42e118d878d8b138bdfb  src/level1/wave_programs.asm
```

Built binaries, captured before the symbol rename:

```
0f82cf55604652412ad7713109be47f6768d50827a9a7f294fc3bd7b1c8d7cb4  build/shmup.prg
1d8667c75b8558e91ee03cafccfabfd2a7ef6d77dcd361db2fc65975ca61b371  build/level1.prg
184c328647dcf54e273a427fde945c5e2fa5f3a8b18768f3e86577cce1c4d889  build/shmup.d64
```

---

## 4. Moves, renames and removals

| Action | From | To |
|---|---|---|
| move (100% rename) | `levels/level1/level.json` | `fixtures/legacy_v5/level1/level.json` |
| move (100% rename) | `levels/level2/level.json` | `fixtures/legacy_v5/level2/level.json` |
| **promote** | `levels/level2pcb/` | `levels/level2/` |
| delete | `levels/level2pcb-blue/` | — (palette study; `--palette=blue` reproduces it) |
| new | — | `src/level2/` (7 generated files) |

Nothing was deleted that is not trivially reproducible, and nothing authored was
deleted at all.

---

## 5. Final canonical tree

```
tools/level_editor/levels/
  level1/level.v6.json          authored Level 1        (authoritative)
  level2/level.v6.json          promoted PCB Level 2    (authoritative)
  level2/README.md

tools/level_editor/fixtures/
  legacy_v5/level1/level.json   frozen v5 migration fixture
  legacy_v5/level2/level.json   frozen v5 migration fixture
  movement_engine_trace.json    engine-recorded fixtures (untouched)
  wave_formation_trace.json

src/level1/   stage_charset stage_config stage_enemies stage_map
              stage_turrets wave_encounters wave_programs
src/level2/   (the same seven)
```

Verified mechanically:

```
level JSON under src/:  0
ASM under levels/:      0
level2pcb anywhere:     0     (outside the previous task's reports)
levels/ subdirectories: level1, level2
```

---

## 6. Level 2 promotion, proven content-preserving

`levels/level2pcb/level.v6.json` → `levels/level2/level.v6.json`, with `"name"`
changed from `level2pcb` to `level2` and rewritten through the project's own
canonical serialiser. Compared field by field against the pre-move snapshot:

```
IDENTICAL fields: formatVersion, glyphs, levelMetatileSet, map, metatileDefs,
                  movementPrograms, palette, stage, triggers, turrets,
                  waveDefinitions
CHANGED  fields:  name     'level2pcb' -> 'level2'

glyphs            ce76968780b64ccd == ce76968780b64ccd  OK
metatileDefs      87806031ca0d5ecc == 87806031ca0d5ecc  OK
map               b968edea06879dda == b968edea06879dda  OK
levelMetatileSet  495c945d1eb2b322 == 495c945d1eb2b322  OK
palette           8d80651cabfadebe == 8d80651cabfadebe  OK
stage             0e4d5da0f7b08d0b == 0e4d5da0f7b08d0b  OK
```

Exactly one field changed, and it is the one that had to. The PCB palette (green
/ black / grey / gold), all 128 glyphs, all 49 metatiles, the 138-row showcase
map, the stage config, the turrets and the carried encounter data are unchanged.

### The generator is no longer the source of truth

`gen_level2_pcb.py` built the PCB vocabulary, but `levels/level2/level.v6.json`
is now authored in the editor. Regenerating over it would discard every later
edit — the same ownership trap `build_levels.py` documents for Level 1. The
generator now writes to a scratch directory by default and **refuses** the
authoritative path:

```
$ python3 tools/level_editor/gen_level2_pcb.py --out=tools/level_editor/levels/level2
refusing to overwrite tools/level_editor/levels/level2/level.v6.json:
  that is the authoritative Level 2 project, authored in the editor.
  Pass --force only if you really mean to discard edits made since
  the PCB prototype was promoted.
```

It is kept because it documents how the vocabulary was constructed and because
its edge-contract checks remain the clearest statement of the tile contract.

---

## 7. Project identity: Save As and Rename Level

The audit found Save As could move a project while leaving its internal name
behind, so Export went on suggesting the old directory. Tracing it turned up a
**real bug underneath**: `EditorController` had **no `name` setter at all**. The
setter lived on the view object, so `controller.name = x` silently bound a new
attribute on the controller and the project kept its old name. My first version
of the Rename command had exactly that bug, and the new test caught it.

Three changes, smallest coherent form:

1. **`EditorController.name`** — a real property with a setter that writes
   through to the project and rejects an empty name.
2. **File → Rename Level…** — an explicit, undoable command. The name is a
   schema field, so it is changed deliberately, never inferred from a filename.
3. **Save As reconciliation** — after saving to `levels/<dir>/level.v6.json`,
   if the level's name disagrees with `<dir>`, the editor *asks* whether to
   rename, naming the consequence (`src/old/` → `src/new/`). Asked, never
   assumed: renaming behind the author's back would be worse, and it must never
   happen to Level 1 by accident.

Level 1 continues to identify as `level1` and to target `src/level1/`; Level 2
identifies as `level2` and targets `src/level2/`.

---

## 8. Fresh-export completeness

`export_v6.export_level` ended with:

```python
if carry_enemies_from is not None:
    src = Path(carry_enemies_from) / ENEMIES_NAME
    if src.exists():        # silently does nothing when it does not
```

Both callers pass **the destination itself**, so on a fresh level directory the
source did not exist, the copy was skipped without a word, and the export
returned a six-file package that `src/main.asm` cannot assemble.

### Ownership decision

`stage_enemies.asm` is genuinely level-owned — it says which slot of the enemy
sprite window each species was loaded into — but it is currently *effectively
boilerplate*: the default packing is simply "species in order, `ENEMY_FRAMES`
blocks each". So, per the brief, one canonical generation path:

* **`contract_v2.DEFAULT_ENEMY_SLOTS`** derives `{RING: 0, DROPPER: 4}` from
  `ENEMY_FRAMES` (`src/enemy.asm`) and `SPECIES_ORDER`
  (`src/encounter_format.asm`). It is **not** read out of `src/level1/`, so a
  fresh Level 2 export has no dependency on Level 1 existing.
* **`export_v6.render_stage_enemies()`** emits the file from that template.
* The exporter **generates when absent, preserves when present** — a level that
  needs a different packing keeps its own file and re-exports never clobber it.
* **`REQUIRED_PACKAGE_NAMES`** (7 files) plus a completeness gate: the export
  now verifies every required file is on disk and raises `ExportRefused` naming
  what is missing. `ExportRefused` was taught to carry a plain reason as well as
  a validation result, since a short package has no `ValidationResult`.

Proven: a fresh export into an empty directory yields **7 files including
`stage_enemies.asm`**, and a deliberately sabotaged export is refused by name.

---

## 9. Neutral symbols

`L1_SLOT_RING` / `L1_SLOT_DROPPER` are level-owned constants the **engine**
referenced by name, so a generated Level 2 would have had to define symbols
named after Level 1. Renamed to `LVL_SLOT_RING` / `LVL_SLOT_DROPPER` across
three files (12 occurrences), plus three `.error` guard messages that said
"level 1's Ring slot" about what are now generic symbols.

The complete Level 1 diff — two lines, symbol names only:

```diff
--- a/src/level1/stage_enemies.asm
+++ b/src/level1/stage_enemies.asm
-.const L1_SLOT_RING     = 0             // the Sonic Ring's four frames
-.const L1_SLOT_DROPPER  = 4             // the Orbital Dropper's four frames
+.const LVL_SLOT_RING     = 0             // the Sonic Ring's four frames
+.const LVL_SLOT_DROPPER  = 4             // the Orbital Dropper's four frames
```

Values, order, comments and the whole header block are untouched. **This is a
source-byte change, not an authored-content change**: no terrain, glyph,
metatile, map, turret, encounter, trigger or no-spawn value is involved.

Proof it moved nothing — rebuilt and compared to the pre-rename hashes:

```
build/shmup.prg: OK
build/level1.prg: OK
build/shmup.d64: OK
```

Re-verified again after the guard-message edit, and once more at the end.

---

## 10. Level 1 preservation proof

The explicit final gate.

**Authored JSON — field by field against the snapshot:**

```
fields compared:  12
fields differing: NONE
terrain     80 glyphs / 41 metatiles / 200 map rows / 5 turrets
encounters  6 programs / 7 waves / 8 triggers / noSpawnRow 725
```

**Generated ASM — against the snapshot:**

```
IDENTICAL  src/level1/stage_charset.asm
IDENTICAL  src/level1/stage_config.asm
IDENTICAL  src/level1/stage_map.asm
IDENTICAL  src/level1/stage_turrets.asm
IDENTICAL  src/level1/wave_encounters.asm
IDENTICAL  src/level1/wave_programs.asm
IDENTICAL  tools/level_editor/levels/level1/level.v6.json
CHANGED    src/level1/stage_enemies.asm   (the 2-line symbol rename, §9)
```

**Built binaries — against the pre-change baseline:**

```
build/shmup.prg: OK
build/level1.prg: OK
build/shmup.d64: OK
```

Level 1 was never regenerated, never migrated through a new serialiser and never
used as a test canvas. Six of its seven generated files and its project JSON are
byte-identical; the seventh differs by two symbol names and produces an
identical program.

---

## 11. Builds

| Build | Result |
|---|---|
| Default (`make build`) | clean, binaries byte-identical to baseline |
| Explicit Level 1 (`LEVELDIR=$PWD/src/level1`) | clean |
| Level 2 (`LEVELDIR=$PWD/src/level2`) | clean; `level1.prg` hash differs from Level 1's, as it must |
| **Level 2 with `src/level1` moved away entirely** | **clean — 0 errors** |

That last row is the real proof of independence: `src/level1` was moved out of
the tree, Level 2 built with zero errors, and `src/level1` was restored and
re-verified. The Makefile passes `-libdir $(LEVELDIR) -libdir $(ROOT)/src`, and
`src/` holds no `stage_*.asm`, so nothing can fall through to another level.

`build/` was left holding canonical Level 1.

---

## 12. VICE

Level 2 was built and flown in `x64sc` 3.10. The PCB terrain displays correctly
after promotion: traces, corners and junctions connect across metatile
boundaries, vias read as gold rings with black drills, the staggered bus
termination and the gold edge-finger bank render cleanly, silkscreen specks are
present, and the player ship and ring enemies stay readable over the green
board. No corruption, no glyph collision, HUD unaffected.

Evidence in `reports/multi-level-layout-cleanup/`:
`level2-promoted-row020.png`, `row052`, `row096`, `edgefingers`.

One note on method, since it bit twice: `free_run()` takes **wall-clock**
seconds, so under warp a single call overshoots hundreds of map rows, and a
non-warp boot never reaches PLAYING within the harness timeout. Precise framing
needs `step_n()` against the `gameFrame` breakpoint, which is what the final
captures used.

---

## 13. Tests

New: **`tools/level_editor/test_multi_level_layout.py` — 37 checks, all passing.**

Deliberately fixture-based. Most claims are proved against synthetic projects
built in the file, because a contract test that asserts Level 1's glyph count
breaks every time the game is authored further. The production levels are
touched only for claims genuinely about them.

Coverage against the brief's list:

| # | Claim | Covered |
|---|---|---|
| 1 | both projects coexist at canonical paths | ✅ |
| 2 | opening Level 1 loads Level 1 data | ✅ |
| 3 | opening Level 2 loads the PCB data | ✅ palette + PCB metatile vocabulary |
| 4 | saving Level 2 cannot modify Level 1 | ✅ byte-compare |
| 5 | saving Level 1 cannot modify Level 2 | ✅ byte-compare |
| 6 | exporting Level 1 writes only its directory | ✅ |
| 7 | exporting Level 2 writes only its directory | ✅ |
| 8 | fresh export creates every required file | ✅ incl. `stage_enemies.asm` |
| 9 | export never silently succeeds incomplete | ✅ sabotaged export is refused by name |
| 10 | identity consistent after Save As / rename | ✅ incl. survives reload and drives the export dir |
| 11 | both packages build independently | ✅ §11 (in-report; builds are not run from the suite) |
| 12 | Level 1's authored content unchanged | ✅ structural in-suite; hash proof in §10 |
| 13 | PCB content survives promotion | ✅ §6 hashes + in-suite vocabulary check |
| 14 | no live `level2pcb` path remains | ✅ |
| 15 | no legacy duplicates in misleading locations | ✅ no ASM under `levels/`, no JSON under `src/`, `levels/` holds only `level.v6.json` |

### Existing suites

| Suite | Baseline (before) | After |
|---|---|---|
| `tools/level_editor/test_*.py` | 37 pass / **1 fail** | 38 pass / **1 fail** |
| `make test` (engine) | 2 pre-existing failures | same 2 |

The editor failure is `test_v6_import.py`, failing **before** this task began and
for a reason this task did not create: it imports encounters from the *live*
Level 1 (a trigger at world row 665) onto the *frozen v5* fixture (105 rows,
max 395). Production grew; the fixture did not. It is the exact coupling §10
warns about. I did **not** touch its assertion — AGENTS.md forbids weakening a
correctness check to make a change pass, and fixing it properly means
re-basing that test's encounter source, which is outside this cleanup.

The two `make test` failures (`publishSkip`, `stageTopRow`) were proven
pre-existing at pristine `HEAD` in the previous task, by building and running in
a clean `git worktree` that had never seen any of this work.

One expectation was updated rather than weakened: `test_wave_schema.py` asserted
the export produces exactly six files. The correct set is now seven, by design,
so it asserts `sorted(export_v6.REQUIRED_PACKAGE_NAMES)` — still an exact set, so
a file appearing or vanishing is still a failure.

---

## 14. Exact files added, changed, deleted

**Added**

```
tools/level_editor/levels/level2/level.v6.json     (promoted)
tools/level_editor/levels/level2/README.md
tools/level_editor/test_multi_level_layout.py
src/level2/  (7 generated .asm files)
reports/multi-level-layout-cleanup-level2-promotion.md
reports/multi-level-layout-cleanup/  (4 VICE captures)
```

**Moved** — `levels/level{1,2}/level.json` → `fixtures/legacy_v5/level{1,2}/level.json` (100% renames)

**Deleted** — `tools/level_editor/levels/level2pcb-blue/` (palette study), and `levels/level2pcb/` as a path (promoted, not removed)

**Changed**

| File | Why |
|---|---|
| `src/level1/stage_enemies.asm` | 2-line symbol rename (§9) |
| `src/enemy.asm`, `src/level_assets.asm` | the other side of that rename + 3 guard messages |
| `tools/level_editor/export_v6.py` | `render_stage_enemies`, `REQUIRED_PACKAGE_NAMES`, completeness gate, `ExportRefused` reason |
| `tools/level_editor/contract_v2.py` | `ENEMY_FRAMES`, `SPECIES_ORDER`, `DEFAULT_ENEMY_SLOTS` |
| `tools/level_editor/controller_v6.py` | `EditorController.name` property + setter |
| `tools/level_editor/editor.py` | Rename Level command, Save As reconciliation |
| `tools/level_editor/gen_level2_pcb.py` | `--out`/`--force`, refuses the authoritative path |
| `tools/level_editor/build_levels.py` | inputs repointed at the frozen fixtures |
| `tools/level_editor/acceptance_terrain_workshop.py` | copies fixtures instead of `levels/` |
| `author_level1_five_enemy.py`, `install_level1_terrain.py` | v5 path constants |
| 8 × `test_*.py` | fixture path constants; `test_wave_schema.py` also the 6→7 file set |

---

## 15. Encounter-library boundary

Not touched. Movement Programs, Wave Definitions and Triggers remain as the v6
documents model them today, owned by each level. Nothing here makes the future
extraction into a repository-scoped shared library harder: no new cross-level
coupling was introduced, and the one new shared constant
(`DEFAULT_ENEMY_SLOTS`) is sprite-window packing, not encounter data.

Level 2's encounters are still Level 1's, carried verbatim so that real sprites
fly over the terrain. They are not authored for the stage and the README says so.

---

## 16. Known limitations

* **No runtime level selection, by design.** `src/levelload.asm` loads one
  package named `LEVEL1` once at boot and the Makefile writes the disk entry as
  `level1`, so a build carries exactly one level. `make build LEVELDIR=…`
  chooses which. Explicitly out of scope.
* `build/` holds whichever level was compiled last — leaving it on Level 2 makes
  the whole test suite exercise the wrong level. Both READMEs say so.
* `test_v6_import.py` remains failing for the pre-existing reason in §13.
* Level 2's encounters are Level 1's, unauthored for the stage.
* `Rename Level` and the Save As prompt are Tk paths and are covered
  headlessly through the controller, not by a GUI test.
* `build_levels.py`, `install_level1_terrain.py` and `author_level1_five_enemy.py`
  are retired v5 tooling kept for coverage and history; only `export_level.py`
  is the current export path.

---

## 17. Hygiene

**Processes.** Every VICE launch went through `tests/harness.Vice`, which retains
the exact PID and reaps it in a `finally` on all exit paths — exercised for real
when one run raised `RuntimeError` mid-boot and still reaped. All runs used
`-console`: no window was mapped, focus was never taken, nothing used `open -a`.
No `pkill`/`killall` at any point. `pgrep -fl x64sc` before and after every run,
**empty now**. PIDs launched and reaped: `67876, 67952, 68179`.

**Disk.**

| Path | Size |
|---|---|
| scratch (`…/scratchpad/cleanup`) | 480K |
| `build/` | 300K |
| `src/level2/` | 48K |
| `tools/level_editor/levels/` | 200K |
| `reports/multi-level-layout-cleanup/` | 16K |

No per-run build directories. Snapshots, the hidden-`src/level1` proof, the
regenerated PCB project and all raw captures stayed in the session scratchpad.

**Final `git status`:**

```
 M src/enemy.asm
 M src/level1/stage_enemies.asm
 M src/level_assets.asm
 M tools/level_editor/acceptance_terrain_workshop.py
 M tools/level_editor/author_level1_five_enemy.py
 M tools/level_editor/build_levels.py
 M tools/level_editor/contract_v2.py
 M tools/level_editor/controller_v6.py
 M tools/level_editor/editor.py
 M tools/level_editor/export_v6.py
R  tools/level_editor/levels/level1/level.json -> tools/level_editor/fixtures/legacy_v5/level1/level.json
R  tools/level_editor/levels/level2/level.json -> tools/level_editor/fixtures/legacy_v5/level2/level.json
 M tools/level_editor/install_level1_terrain.py
 M tools/level_editor/test_level_packages.py
 M tools/level_editor/test_native_terrain_tiles.py
 M tools/level_editor/test_v6_export.py
 M tools/level_editor/test_v6_import.py
 M tools/level_editor/test_v6_migration.py
 M tools/level_editor/test_v6_phase5a_gui.py
 M tools/level_editor/test_v6_roundtrip.py
 M tools/level_editor/test_wave_schema.py
?? reports/level2-pcb-terrain-visual-prototype.md
?? reports/level2-pcb-terrain-visual-prototype/
?? reports/multi-level-layout-cleanup-level2-promotion.md
?? reports/multi-level-layout-cleanup/
?? reports/multi-level-workflow-audit.md
?? src/level2/
?? tools/level_editor/gen_level2_pcb.py
?? tools/level_editor/levels/level2/
?? tools/level_editor/test_multi_level_layout.py
```

Canonical Level 1 is unchanged in content and behaviour. The runtime Level 1 →
Level 2 transition was **not** implemented. **Nothing was committed or pushed.**
