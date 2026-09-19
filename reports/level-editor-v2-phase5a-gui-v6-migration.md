# Level Editor v2 — Phase 5A: the GUI on the canonical v6 model

**Date:** 2026-09-19
**HEAD:** `20fa317` *Level editor re-done* — branch `main`, tracking `origin/main`, **level, 0 ahead / 0 behind**.
**Working tree at start:** **clean.** The Phase 1–4 checkpoint is committed and pushed, as expected.
**Scope:** GUI compatibility and refactoring only. **No encounter authoring UI, no movement preview.**
**Nothing committed. Nothing pushed.**

---

## 1. Headline result

The editor now opens, edits, saves and exports the **canonical v6 Level 1**, and
a round trip through it changes nothing:

```
levels/level1/level.v6.json
   -> EditorController (the object the GUI edits)
   -> no edits
   -> save   : BYTE-IDENTICAL JSON      acef2dc0…  67,209 bytes
   -> export : 6/6 ASM BYTE-IDENTICAL   to the committed src/level1/
   -> build  : level1.prg 08ff4116…     BYTE-IDENTICAL
               shmup.prg  e726d430…     BYTE-IDENTICAL
```

The live document is a `ProjectV6`. The movement programs, wave definitions,
absolute triggers and `noSpawnRow` that this phase does not edit survive a
terrain edit, a turret edit, an undo and a save — and the file comes back byte
for byte.

**No engine source, generated stage data or Makefile was touched.**
`git status --porcelain src/ Makefile` is empty.

---

## 2. Phase 1–4 checkpoint state, verified

```
$ git log --oneline -1
20fa317 Level editor re-done
$ git status --porcelain          (empty)
$ git status -sb
## main...origin/main
```

Verified rather than assumed, and the canonical project's content was measured
against the brief's expectations rather than forced:

| expected | measured |
|---|---|
| width 10 | `stage.metatileCols` **10** |
| 105 metatile rows | **105** (`map` is 105 × 10) |
| current palette | `{background 12, mc1 15, mc2 11, character 1}` |
| 72 terrain glyphs | **72** |
| 34 metatile definitions | **34** |
| 8 turrets | **8** |
| `noSpawnRow = 340` | **340** |
| 4 movement programs | **4** (13 records, 52 bytes) |
| 4 wave definitions | **4** |
| 4 triggers | **4** |

**Canonical path:** `tools/level_editor/levels/level1/level.v6.json`
**sha256:** `acef2dc09c6c366dae223dbde6e8702098d45176dde560140c710b8c72e1a2ec`
Validation: **0 errors, 0 warnings.** Derived duration: 420 logical rows, 395
playable, 3,160 frames, **63.2 s**.

`levels/level1/level.json` (v5) remains the migration fixture and was never
used as the GUI's target.

**Baseline before any change:** 27 editor test files, **27 pass / 0 fail**;
`build/level1.prg` `08ff4116…`, `build/shmup.prg` `e726d430…`.

---

## 3. The v5 assumption audit, and the old → v6 map

Measured by counting every `self.project.<attr>` in `editor.py` before editing.
**Fifty-three of the ~150 uses were the obsolete encounter UI** — which is why
removing it was the largest single part of the work.

| old GUI concept | uses | v6 field / API | disposition |
|---|---|---|---|
| `project.wave_definitions` | 30 | — | **removed** (attack catalogue) |
| `project.wave_triggers` | 20 | — | **removed** |
| `canonical_wave_definitions/_triggers` | 2 | — | **removed** |
| `project.level_metatile_set` | 23 | `ProjectV6.level_metatile_set` | kept, **with a form fix (§9)** |
| `project.palette` (dict) | 21 | `Palette` dataclass | via `V5View.palette` |
| `project.objects` (turret dicts) | 14 | `turrets: list[Turret]` | via controller |
| `project.name` | 11 | `name` | direct |
| `project.scroll_frame_divider` | 10 | — | **inert**, always 1 |
| `project.height` | 9 | `len(map_rows)` | via `V5View.height` |
| `project.tileset` | 8 | `glyphs` + `metatile_defs` | via `V5View.tileset` |
| `project.metatile_rows` | 4 | `map_rows` | via `V5View.metatile_rows` |
| `project.metatile_metadata` | 2 | — | **dropped** (`{}`) |
| `MIN/MAX_STAGE_ROWS` 1..768 | — | `C.MIN/MAX_METATILE_ROWS` **7..440** | replaced |
| `load_engine_data()` seeding from generated ASM | — | canonical `level.v6.json` | replaced |
| `ka_export.export_level` (4 files) | — | `export_v6.export_level` (**6 files**) | replaced |
| `save_project` / `load_project` (v5) | — | controller `save` / `migration_v6.load_any` | replaced |
| `validate_project` (v5) | — | `validation_v6.validate` | replaced |
| `self.data.attack_catalogue` | 3 | — | **removed** |
| duration × `scrollFrameDivider` | — | `contract_v2` derivation | replaced |

Verified inert afterwards — every remaining mention in the live GUI path
(`editor.py`, `controller_v6.py`) is a comment or the deliberately inert
property:

```
scrollFrameDivider 0   attack_catalogue 0   waveTriggers 0
load_engine_data   0   ka_export        0   stage_waves  0
attackId/enemyType/composition  1 (one comment)
src/generated / stage_test      3 (comments saying they no longer exist)
```

---

## 4. Files changed

| file | change |
|---|---|
| `tools/level_editor/controller_v6.py` | **new**, 529 lines — the GUI-independent controller and the v5-shaped view |
| `tools/level_editor/editor.py` | migrated to v6; **1,993 → 1,593 lines** (−675 / +274) |
| `tools/level_editor/test_v6_phase5a_gui.py` | **new**, 358 lines — 55 checks |
| `tools/level_editor/test_editor_asset_workflow_gui.py` | its v5 wave-library section replaced by the v6 assertion (§8) |

```
 tools/level_editor/editor.py                       | 890 ++++++---------------
 tools/level_editor/test_editor_asset_workflow_gui.py |  59 +-
 2 files changed, 274 insertions(+), 675 deletions(-)
```

Nothing else. No `src/`, no `Makefile`, no engine, no generated stage data.

---

## 5. Load/save architecture

```
levels/<name>/level.v6.json
        │  migration_v6.load_any()        v6 direct; v1..v5 migrate, notices kept
        ▼
   EditorController          ← the GUI holds THIS
        ├── .project   ProjectV6          the single authoritative object
        ├── .view      V5View             v5 names over the live v6 model
        ├── .save()    deterministic v6
        ├── .export()  export_v6, six files
        └── .validate() validation_v6
```

`editor.py` keeps `self.project = controller.view`, so the canvas, the metatile
workshop, the glyph packer and the turret overlay carry on using the attribute
names they were written against — while the object underneath is v6.

**`V5View` holds no data.** Every attribute is a property reading or writing the
`ProjectV6`, and the lists it hands out *are* the project's lists, so an
in-place mutation by an existing helper (`repack_tileset_from_metatile_set`,
`remove_metatile`, `metatile_id_usage`) lands on the v6 model directly. There is
no synchronisation step that could drift or be forgotten.

Two v5 names survive as deliberately inert compatibility: `scroll_frame_divider`
(always 1, and **assignment is ignored**, so a stale widget cannot write a
fiction into a project with no field for it) and `metatile_metadata` (always
`{}`).

---

## 6. Preservation of unexposed v6 data

The rule, and the whole mechanism:

> **hold the project that was loaded, mutate only what the user edits, and write
> the same object back out.**

The controller keeps the `ProjectV6` instance the loader returned and never
rebuilds one from GUI-known fields. `ProjectV6.to_dict()` emits every field it
holds; the fields the GUI cannot reach are the ones it never touches. There is
no merge step and no "preserve these keys" list to forget to update — **a new v6
field is preserved by default**, which is the safe direction.

Two places where that could have leaked, and did not:

* **the dirty/undo snapshot** was a tuple of the fields the v5 GUI knew about, so
  a change to anything else was invisible to undo. It is now the project's own
  canonical JSON, and `_restore_state` rebuilds the whole document from it —
  so undo restores an encounter with the same fidelity as a terrain cell;
* **`_adopt_project`** takes a *controller*, not a project, so switching
  documents replaces the whole thing and no field of the previous one survives.

Measured (§12, §13): encounters, `noSpawnRow`, turrets, palette, glyphs and
metatile definitions are all bit-identical across a terrain edit and a turret
edit, and reversing either edit returns the canonical bytes.

---

## 7. Stage, duration and resizing

Row range is now the engine's: **7..440**, read from `contract_v2`
(`LEVELPKG_MAP_MAX / 10 = 440`; the scroller needs more than a screenful, so
`ceil(26/4) = 7`). The retired 768 is gone.

Duration uses the current contract and nothing else:

```
logicalRows    = metatileRows * 4
playableRows   = logicalRows - 25          the screenful that never plays
playableFrames = playableRows * 8          1 px/frame, 8 px to a coarse row
seconds        = playableFrames / 50       PAL
```

For Level 1: `≈ 1:03 at 1 px/frame PAL (395 playable of 420 logical rows, 3160
frames)`. The old readout multiplied *total* pixels by a scroll divider the
engine does not read and counted the 25 rows the player never scrolls through,
so it over-reported every stage.

**Resizing refuses rather than deletes.** The v5 editor offered to discard
turrets and wave triggers for you; with real encounters in the project that is
no longer an acceptable default, so the controller declines and says why:

```
cannot shrink to 10 rows: 6 turret(s) sit at or past it (metatile rows …).
    Move or delete them first.
cannot shrink to N rows: the stage would end at worldProgress P, at or before
    the no-spawn row 340. Lower noSpawnRow first.
cannot shrink to N rows: 2 trigger(s) would fall at or past the new stage end.
```

Losing only *blank* terrain off the end is still silent; losing painted terrain
still asks, as before.

---

## 8. The old encounter controls

**Removed, not disabled.** Three blocks left `editor.py` entirely:
`_build_wave_panel` (the Waves side panel), `_draw_wave_triggers` (the trigger
flags on the stage), and the whole wave-editing section from
`_refresh_wave_panel` to `_delete_selected_trigger` — about 19,400 characters.
The "Waves" edit mode, its click/drag/delete routing, the wave form variables
and the global wave repository all went with them.

Approximate mapping was never attempted, and the reason is in the Phase 1
report: an `attackId` indexes a curated catalogue of twelve that no longer
exists in the engine, `enemyType` 0..3 does not map onto two species, and
nothing in v5 supplies a spawn X/Y, a per-member fan, a launch heading, a
movement program, a fire mask or a Dropper side.

Reaching for the old surface on a v6 project now **fails loudly** rather than
silently editing something it cannot represent:

```python
>>> view.wave_definitions
ControllerError: the v5 wave-definition surface is not available on a v6
project: encounters are movement programs, wave definitions and absolute
triggers, and authoring them is Phase 5B
```

In place of the panel there is a one-line read-only summary, so the author can
see what the project carries rather than think the editor lost it:

```
Encounters: 4 programs · 4 wave defs · 4 triggers · no-spawn 340
```

`wave_repository.py` and its JSON are left untouched on disk and are simply not
loaded — Phase 5B decides whether a v6 encounter library replaces them.

---

## 9. Two findings the migration exposed

### 9.1 The native metatile set has two forms, and the v5 GUI never met the file one

`test_editor_asset_workflow_gui.py` failed after the migration. The cause was
real, not cosmetic: a native 16×32 metatile is stored on disk as **32 row
strings** (`"1111111111111111"`) to keep a level file a few kilobytes instead of
about a megabyte, while the workshop, the glyph packer and the terrain
repository all expect **32 lists of 16 ints**.

The v5 editor never noticed because it seeded itself by parsing the generated
assembler, which produces the in-memory form directly. **Opening a real project
file was a path the old GUI never took.** Both v5 `level.json` and v6
`level.v6.json` store the string form.

Fixed at one seam. `EditorController.adopt()` normalises on load (through
`project.py`'s own `canonical_metatile_set_entry`, so there is one answer to the
question) and `to_json()` re-serialises on save. The GUI edits lists, the file
keeps strings, and the no-op round trip stays byte-identical.

### 9.2 Turret refusal order

With Level 1 already at the eight-turret cap, clicking an occupied row reported
*"this level already has the maximum of 8 turrets"* — true, but not about where
the pointer was. The row rule is now checked first: *"metatile row 25 already
carries a turret (the engine allows one per row)"*. Both refusals still apply;
the more actionable one is reported.

---

## 10. Terrain, metatile and turret behaviour

Unchanged in feel, and proven so against real Tk (§15). Painting, selection,
the grid, the viewport aperture overlay, the metatile palette, New Tile,
Duplicate, Edit in Workshop, Import PNG, Save to Repository, Rename, Delete,
Trim unused, the repository dialog and undo/redo all still work.

One behavioural improvement fell out of the model change: **"Import metatiles
from another project" now accepts any version**, because it goes through the
same one-loader rule as Open instead of a v5-only reader.

Turret placement, selection and removal now go through the controller, so the
one-per-row rule and the eight-turret cap live in one place and are tested
headlessly. Level 1's eight turrets display correctly with 24 markers drawn.

---

## 11. Export integration

GUI Export calls `EditorController.export()`, which calls the Phase 4
`export_v6.export_level` and writes **six** files:

```
stage_config.asm  stage_charset.asm  stage_map.asm
stage_turrets.asm wave_programs.asm  wave_encounters.asm
```

`stage_enemies.asm` is carried forward (level-owned but hand-authored; a level
directory without it does not assemble). Validation errors **block** the export
and are shown in full — nothing is written when the project is invalid:

```
export refused -- the project has 2 validation error(s):
• …
```

No `src/generated/…`, no `stage_test.asm`, no `stage_waves.asm`, and no
obsolete exporter API. `ka_export.py` is no longer reachable from the GUI.
Encounters are **not** re-imported from ASM: the v6 project is authoritative.

---

## 12. The canonical no-op proof

All nine steps of the brief, end to end:

```
canonical sha256 : acef2dc09c6c366dae223dbde6e8702098d45176dde560140c710b8c72e1a2ec
1-5  JSON byte-identical : True            67,209 bytes
6-7  ASM byte-identical  : 6/6             vs committed src/level1/
8-9  level1.prg          : BYTE-IDENTICAL  08ff4116…
     shmup.prg           : BYTE-IDENTICAL  e726d430…
```

Re-run after the dead-code removal, with the same result. The reload of the
saved file is itself a fixed point, so this is stability rather than luck:

```
save -> load -> save : byte-identical
```

**GUI initialisation does not normalise or mutate the project.** The metatile
form conversion of §9.1 is the only transformation, and it is exactly reversed
on save — which is why the bytes match.

---

## 13. Scoped edit proofs

### Terrain

```
ok  a terrain edit changes exactly one map cell            [(40,3) 4 -> 5]
ok  ...and leaves every encounter untouched
ok  ...and leaves noSpawnRow untouched
ok  ...and leaves turrets untouched
ok  ...and leaves palette, glyphs and metatile definitions untouched
ok  restoring the cell returns byte-identical canonical JSON
```

The "exactly one" is measured by diffing all 1,050 cells against a freshly
loaded canonical project, not asserted about the one cell that was written.

### Turret

Level 1 is already at the eight-turret cap, so the legal edit the UI supports is
a **removal**:

```
ok  a turret edit removes exactly one turret   [removed metatile row 55, col 25]
ok  ...and leaves every encounter untouched
ok  ...and leaves noSpawnRow untouched
ok  ...and leaves the terrain untouched
ok  ...and leaves palette, glyphs and metatile definitions untouched
ok  putting it back returns byte-identical canonical JSON
```

**The canonical project was never mutated**: every proof runs on its own freshly
loaded copy and writes only into `TemporaryDirectory()`.

---

## 14. Historical v5 migration

`v5 project → GUI load path → v6 model → save v6`, through the same
`EditorController.load` the Open menu uses:

```
ok  a v5 project still opens through the GUI's load path    [from v5]
ok  ...and becomes a v6 model
ok  ...keeping its terrain, glyphs, definitions and turrets [105 rows, 8 turrets]
ok  ...with a derived noSpawnRow                            [340]
ok  ...and the v5 encounters deliberately discarded         [0/0/0]
ok  ...and the migration says so, so the GUI can tell the author
ok  ...and a migrated project saves as deterministic v6
ok  ...with no v5-only field names left in it
ok  ...and that file is itself a fixed point
```

Notices remain available and are surfaced **concisely and only when data was
lost**. A v6 file produces one `migration.none` notice, so "there are notices"
is not "something happened to your project" — opening the canonical level raises
no dialog. Opening a v5 project shows what could not be carried:

```
Opened a formatVersion 5 project and migrated it to v6.
Saving will write v6.

Data that could NOT be carried forward:
• DISCARDED 33 old wave definition(s): …the curated catalogue they index no
  longer exists in the engine
• DISCARDED 53 old wave trigger(s): …
```

The old attack catalogue is never resurrected.

---

## 15. Manual GUI smoke test

**Tk is not available on the default interpreter here.** `python3` (3.14,
Homebrew) has no `_tkinter`, and the system `/usr/bin/python3` (3.9) has Tk 8.5
which refuses to start on this macOS build (`macOS 15 (1507) or later required,
have instead 15 (1506)`). `/usr/local/bin/python3` has a working **Tk 8.6** and
is what every GUI result below was produced with.

**This matters for the baseline:** the two GUI test files *skip* when Tk is
missing, so the 27-pass HEAD baseline included two tests that were not
exercising the GUI at all. Run under the working interpreter they do — and both
pass.

Every item on the brief's checklist was driven against real Tk with the window
**withdrawn**, so nothing stole focus:

| item | result |
|---|---|
| canonical Level 1 opens without traceback | ok — `level1`, 105 rows |
| the document is genuinely v6 | ok — `ProjectV6`, `level.v6.json` |
| terrain renders | ok — 1,194 canvas items |
| metatile palette renders | ok — 103 palette items |
| stage scrolling works | ok — scrolls, clamps both ends, no wrap |
| all 105 rows accessible | ok — scrollregion `0 0 320 3360` |
| eight turrets appear correctly | ok — 8 turrets, 24 markers |
| selection / painting works | ok — writes the selected tile; undo restores |
| palette / metatile workflow works | ok — New Tile +1, undoable; workshop suite green |
| Save As works | ok — 67,209 bytes, deterministic v6 |
| Export works | ok — six generated files plus the carried `stage_enemies.asm` |
| stale encounter controls cannot edit v6 | ok — removed; summary read-only |
| close / reopen works | ok — reopened at 105 rows |

One item needed a second look rather than a fix: the first probe reported
scrolling as broken, but the viewport opens at 397, which **is** the maximum
(420 logical − 23 visible), so nudging further is correctly clamped. Nudging the
other way moves it, and `set_viewport(0)` then `nudge(-1)` stays at 0 — it
clamps at both ends without wrapping.

**A visible instance is running for you now: PID 80496**
(`/usr/local/bin/python3 editor.py`, clean start, no output). Programmatic
inspection is evidence; whether the stage *looks* right is your judgement, and
that is the one thing this report cannot claim for you. Close it yourself, or
say the word and I will terminate that exact PID.

---

## 16. Automated test totals

### Editor — 28 files, **28 pass, 0 fail**

| suite | checks |
|---|---|
| `test_v6_migration.py` (Phase 1) | 52 |
| `test_v6_validation.py` (Phase 1) | 64 |
| `test_v6_roundtrip.py` (Phase 1) | 20 |
| `test_v6_export.py` (Phase 2) | 63 |
| `test_v6_import.py` (Phase 3) | 74 |
| `test_v6_phase4_roundtrip.py` (Phase 4) | 37 |
| **`test_v6_phase5a_gui.py` (new)** | **55** |
| **v6 total** | **365** |

### GUI, against real Tk 8.6

| file | checks |
|---|---|
| `test_editor_workshop_gui.py` | **9** — all pass |
| `test_editor_asset_workflow_gui.py` | **6** — all pass |

The Phase 5A file covers everything §17 of the brief asks for: canonical load,
no-op save identity, encounter preservation, `noSpawnRow` preservation,
deterministic save, six-file exporter invocation, generated ASM equality,
terrain single-cell isolation, turret isolation, v5 migration through the GUI
path, row limits, the current duration calculation, the turret limit, no active
`scrollFrameDivider`, and no active attack catalogue.

### Engine

**Not re-run, and it does not need to be.** `src/` and the `Makefile` have no
diff, and `level1.prg` and `shmup.prg` are byte-identical to the Phase 4
baseline — a byte-identical binary from byte-identical source is a complete
proof that no engine behaviour changed. No engine source change was necessary at
any point, so the brief's stop condition was not reached.

---

## 17. Remaining legacy GUI code

Left deliberately, none of it reachable from the v6 GUI path:

| file | state |
|---|---|
| `ka_export.py` | the v5 four-file exporter. Unused by the GUI; still imported by the v5-era batch scripts |
| `project.py` | the v5 loader. **Retained on purpose** — `migration_v6` delegates every pre-v6 normalisation to it, and the metatile/turret/viewport helpers the canvas uses live there |
| `wave_repository.py`, `wave_repository/repository.json` | v5 attack-catalogue library. Not loaded; left on disk untouched |
| `build_levels.py`, `acceptance_terrain_workshop.py`, `install_level1_terrain.py`, `import_generated_level.py` | v5-era batch scripts flagged in the Phase 4 report; they now produce a *subset* of a level directory |
| `levels/level1/level.json`, `levels/level2/level.json` | v5 migration fixtures |
| `engine_data.py` | still parses the generated ASM. No longer used to seed the GUI; other tooling and tests use it |

Dead code removed from `editor.py` with the wave UI: `PAL_FRAMES_PER_SECOND`,
`_logical_row_from_event` (placed a trigger by logical row),
`_turret_index_in_row` (the rule moved to the controller), `_metatile_row_usage`,
`_baseline_tileset`, `_seed_project`, `_obj_key`/`_obj_from_key`.

---

## 18. Deferred to Phase 5B, and unresolved

**Phase 5B (explicitly not begun):** the encounter timeline and trigger UI, the
wave-definition editor, the movement-program editor, trajectory
preview/simulation, graphical no-spawn authoring, multi-turret-per-row.

Unresolved, carried forward:

1. **`noSpawnRow` has no editor at all** — it is loaded, validated, preserved,
   saved and displayed read-only in the encounter summary. Graphical authoring
   is Phase 5B; a plain numeric field would have been trivial but is
   authoring, which this phase is scoped out of.
2. **The wave repository's future.** It stores v5 snapshots that no v6 project
   can accept. Either a v6 encounter library replaces it in Phase 5B or it
   retires with the v5 model.
3. **Tk availability on this machine is fragile** (§15) — two of three
   interpreters cannot open a window. Worth pinning the editor's interpreter
   before Phase 5B adds more GUI surface.
4. **`level.v6.json` is still not regenerable by a committed command** (Phase 4
   §16.1). Unchanged by this phase, and now more load-bearing: the GUI's default
   document is that file.
5. **v5-era batch scripts** (§17) still call the v5 exporter and would write an
   incomplete level directory. They belong to the v5 model.

---

## 19. Hygiene and disk

```
$ du -sh build/                292K   current binary, symbols, level package, d64
$ du -sh tools/level_editor/   968K
$ du -sh .                      10M
```

`__pycache__` cleared. Every proof wrote into `TemporaryDirectory()`; the one
scratch build used `LEVELDIR=<temp>` and the production build was restored
afterwards (`level1.prg` / `shmup.prg` re-verified at the baseline hashes). No
per-run directories, no build artefacts accumulated, and `/tmp/le-head` — the
pristine HEAD tree used to attribute the GUI-test failure — was deleted.

---

## 20. Final git status

```
$ git status --porcelain
 M tools/level_editor/editor.py
 M tools/level_editor/test_editor_asset_workflow_gui.py
?? tools/level_editor/controller_v6.py
?? tools/level_editor/test_v6_phase5a_gui.py

$ git diff --stat
 tools/level_editor/editor.py                         | 890 +++++-------------
 tools/level_editor/test_editor_asset_workflow_gui.py |  59 +-
 2 files changed, 274 insertions(+), 675 deletions(-)

$ git status --porcelain src/ Makefile
 (empty)
```

Four files, all under `tools/level_editor/`. No unrelated user work exists in
the tree to preserve — it was clean at start and every change here is Phase 5A's.

---

## 21. Acceptance

| # | criterion | result |
|---|---|---|
| 1 | GUI opens canonical v6 Level 1 | ✅ |
| 2 | live GUI state is genuinely v6 | ✅ `ProjectV6`; the view holds no data |
| 3 | terrain/metatile editing works | ✅ 9 workshop checks, real Tk |
| 4 | turret editing works within current limits | ✅ cap 8, one per row |
| 5 | encounter data is preserved | ✅ across load, edits, undo, save |
| 6 | `noSpawnRow` preserved | ✅ 340 throughout |
| 7 | stale encounter controls cannot corrupt v6 | ✅ removed; access raises |
| 8 | Save writes deterministic v6 | ✅ |
| 9 | no-op open/save byte-identical JSON | ✅ `acef2dc0…` |
| 10 | no-op export byte-identical six ASM files | ✅ 6/6 |
| 11 | `level1.prg` byte-identical | ✅ `08ff4116…` |
| 12 | `shmup.prg` byte-identical | ✅ `e726d430…` |
| 13 | isolated terrain edit changes only map state | ✅ |
| 14 | isolated turret edit changes only turret state | ✅ |
| 15 | v1–v5 migration works through GUI load path | ✅ |
| 16 | duration uses the 1 px/frame contract | ✅ |
| 17 | 7..440 row range enforced | ✅ |
| 18 | obsolete scroll divider inactive | ✅ inert and ignored |
| 19 | current complete exporter used | ✅ six files |
| 20 | all prior tests remain green | ✅ 28/28, 365 v6 checks |
| 21 | manual GUI smoke test passes | ✅ programmatically against real Tk; **visual judgement is yours** — PID 80496 is running |
| 22 | no engine/gameplay architecture changed | ✅ `src/` and `Makefile` untouched |
| 23 | nothing committed or pushed | ✅ |

**A no-op GUI round trip does not change canonical Level 1.**

**Phase 5B was not begun.**
