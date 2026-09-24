# Shared encounter library, per-level triggers

Movement Programs and Wave Definitions are now shared across every level and
persisted exactly once. Triggers, `noSpawnRow` and everything else genuinely
level-specific stay with the level. **New Level gives you a blank canvas, an
empty trigger timeline and the complete shared vocabulary immediately.**

Level 1's authored content — including the Square trigger at world row 310 —
survives exactly. Every generated `.asm` and all three binaries are byte-identical.

Nothing was committed or pushed.

---

## 1. Starting state

| | |
|---|---|
| HEAD | `a931958bb1657474b159267b83f1f03d9fd53e5e` — *Added level2 data to editor* |
| Branch / upstream | `main` … `origin/main`, in sync |
| VICE running | none |

The working tree was **not** clean, and two of the uncommitted changes were the
point of the exercise: `tools/level_editor/levels/level1/level.v6.json` and
`src/level1/wave_encounters.asm` carried Brian's newly authored Square trigger.
The whole sprite pipeline from the previous task was uncommitted too. All of it
was snapshotted (35 files) before anything was touched.

---

## 2. Ownership audit

The observed behaviour was confirmed rather than assumed.

| Question | Answer |
|---|---|
| Where are the three persisted? | All in `ProjectV6`: `movement_programs`, `wave_definitions`, `triggers` — serialised into each `level.v6.json` |
| Encounter state outside `ProjectV6`? | **None.** Every controller operation mutates `self.project.*` directly |
| What did New Level construct? | `editor.py:187` — `movement_programs=[], wave_definitions=[], triggers=[]`. **All three empty.** This is the bug |
| What does Open Level replace? | The whole controller, via `_adopt_project` — so everything, library included |
| What does Save write? | `controller.to_json()` → the entire document, vocabulary included |
| What does Export consume? | `project.movement_programs` / `.wave_definitions` / `.triggers` |
| Are runtime packages already level-specific? | **Yes.** `wave_programs.asm` and `wave_encounters.asm` are emitted per level into `src/levelN/` |
| Which tests assume embedded assets? | Nine, listed in §10 |

### Why Level 2 appeared to share encounters

It never did. Level 2 was created by **copying Level 1's project** during the PCB
promotion, so the two started with byte-identical vocabularies. Triggers then
diverged because Brian edited Level 1's. What looked like sharing was two copies
that happened to agree, which is exactly the failure mode the shared library
removes — had he edited a movement program instead of a trigger, the copies
would have silently drifted.

---

## 3. Level 1 vs Level 2: the semantic diff

```
=== movementPrograms ===
  level1: 6  ['dive_bomb','linger','loop','s','sweep','up_n_over']
  level2: 6  ['dive_bomb','linger','loop','s','sweep','up_n_over']
  only in level1: none      only in level2: none
  SAME id, DIFFERENT content: none

=== waveDefinitions ===
  level1: 7  ['dive_4','linger','loop','loop_5','s','sweep','up_n_over']
  level2: 7  ['dive_4','linger','loop','loop_5','s','sweep','up_n_over']
  only in level1: none      only in level2: none
  SAME id, DIFFERENT content: none
```

**Byte-identical.** No conflicts, no unique assets on either side, so the union
is either copy and reconciliation was trivially safe. Level 1 is still used as
the migration source and is processed first, so that if the two ever *do*
diverge it is Level 1's version that lands and Level 2's that is reported as a
conflict rather than quietly winning.

Triggers differ, as expected, and were not reconciled.

---

## 4. The shared library

`tools/level_editor/encounter_library.v6.json` — 4,480 bytes.

```json
{
  "formatVersion": 6,
  "kind": "encounterLibrary",
  "movementPrograms": [ … 6 … ],
  "waveDefinitions":  [ … 7 … ]
}
```

`kind` exists so a level document cannot be mistaken for a library and vice
versa; both mistakes are refused with a clear message. Serialisation is
deterministic and matches the v6 style already used for levels.

### Canonical per-level schema

```
formatVersion, name, stage (incl. noSpawnRow), palette, glyphs,
metatileDefs, map, turrets, triggers, levelMetatileSet
```

`movementPrograms` and `waveDefinitions` are **gone from both production level
files**. There is one persisted copy of the vocabulary and nothing to
synchronise — the duplication is not managed, it is absent.

### In memory, nothing moved

The library's assets are installed onto the live `ProjectV6` when a level opens,
so the controller, validator, exporter, simulator and preview all keep reading
`project.movement_programs` exactly as before. The ownership change is a
**persistence** change; spreading it through every consumer would have been a
rewrite rather than a fix.

---

## 5. Migration

`tools/level_editor/migrate_encounter_library.py` (with `--check`):

```
library before: 0 movement programs, 0 wave definitions
level1: embedded movementPrograms+waveDefinitions  (9 triggers, noSpawnRow 725)
level2: embedded movementPrograms+waveDefinitions  (7 triggers, noSpawnRow 352)
  added movement program 'sweep' from level1/level.v6.json
  … 13 assets added, all from level1 …
library after:  6 movement programs, 7 wave definitions
rewrote level1/level.v6.json (dropped 6 programs + 7 definitions)
rewrote level2/level.v6.json (dropped 6 programs + 7 definitions)
```

Nothing was added from Level 2 because everything it had was already present and
identical — which is reconciliation working, not data being dropped.

Backward migration is permanent, not one-shot: opening **any** document that
still carries embedded assets folds them into the library. Anything new is
added, anything identical is accepted, and an id meaning two different things
raises `LibraryConflict` naming both sides rather than guessing. Triggers are
never treated as shared. All four behaviours are tested.

---

## 6. Lifecycle

**New Level** — blank terrain and stage, **zero triggers**, and the shared
vocabulary installed in memory. Proved through the real
`editor._seed_v6_project`:

```
triggers:           0
movement programs:  6  ['sweep','s','linger','loop','dive_bomb','up_n_over']
wave definitions:   7
turrets:            0
map is blank:       True
level JSON keys:    formatVersion, glyphs, levelMetatileSet, map,
                    metatileDefs, name, palette, stage, triggers, turrets
```

**Open Level** — replaces the level half (triggers, `noSpawnRow`, terrain,
palette, turrets) and leaves the library alone. `Level 1 → Level 2 → Level 1`
swaps the trigger timeline and keeps the vocabulary; asserted for disposable
levels A and B.

**Save** — writes the level document, then harvests the live vocabulary back
into the library and writes that. Undo and the dirty marker still operate on the
*whole* in-memory document, so a movement-program edit is undoable and does mark
the level dirty — which is what makes "switch level with unsaved shared edits"
prompt rather than lose them.

---

## 7. Three safety rules the work uncovered

Each of these was a real hole found while wiring this up, not a theoretical one.

**A save may only drop the vocabulary when it has somewhere to go.** A
controller with no library keeps writing the whole document, because stripping
keys whose only copy is in that file would be deleting data to satisfy a layout
rule.

**A read-only vocabulary that has been edited cannot be silently dropped.** A
project can be *given* the library read-only (any loader does this). If those
assets are then edited and saved with no writable library, the save now
**refuses** and says why. Previously it would have discarded the edits. This is
acceptance gate 8, and it needed an explicit guard: the project remembers the
vocabulary exactly as it was handed over and compares.

**`canonical()` no longer defaults to a writable production library.** It is
what a dozen tests reach for when they want a realistic document, and defaulting
the path handed every one of them write access to the shared library — which is
precisely how a test run added `demo6b`, `prog` and `prog2` to it during this
work. Production data was restored from snapshot; the GUI now passes the path
explicitly and everything else gets a read-only attach.

A fourth, subtler one: `attach_if_absent` keys on the **presence** of the JSON
key, not its truthiness. A migrated v5 project carries `"movementPrograms": []`
— stating it has none — and treating that as "missing" silently gave it six
programs it never had.

---

## 8. Export and runtime

Unchanged, and that is the headline result. Export resolves a level's triggers
against the vocabulary and emits that level's own self-contained
`wave_programs.asm` and `wave_encounters.asm`. The C64 never learns an editor
library exists.

**Both levels re-exported from the shared-library model:**

```
14 generated files compared, 0 differ
```

**Binaries:**

```
IDENTICAL build/shmup.prg
IDENTICAL build/level1.prg
IDENTICAL build/shmup.d64
```

Level 2 also builds clean via `LEVELDIR`. Package budgets, contracts and species
IDs — Ring 0, Dropper 8, Square 16 — are untouched.

---

## 9. Preservation

### Level 1 and Level 2, field by field against the pre-migration snapshot

```
level1: 10 level-specific fields IDENTICAL -> formatVersion, glyphs,
        levelMetatileSet, map, metatileDefs, name, palette, stage,
        triggers, turrets
        differing: NONE
        removed (now shared): movementPrograms, waveDefinitions

level2: identical result
```

**Level 1's nine triggers, including Brian's Square at world row 310 (`dive_4`),
are byte-identical.** `noSpawnRow` 725 preserved. Level 2 keeps its seven
triggers and `noSpawnRow` 352, and **gained no Square trigger** — asserted.

`noSpawnRow` is per level and proved so: changing it on disposable level A
leaves B untouched.

### Sprite work

`assets/` and `src/generated_sprites/` are byte-identical to the snapshot. The
SpritePad pipeline was not touched.

---

## 10. Tests

**New: `tools/level_editor/test_encounter_library.py` — 49 checks, all passing.**
Disposable levels A and B share a temporary library and deliberately disagree
about their triggers, so isolation is proved without mutating anything Brian
authors. Production levels are read, never written.

Coverage: library schema and determinism, level-document boundary, migration
from embedded assets, unique-asset absorption, conflict refusal, the full New
Level acceptance case (empty triggers → shared vocabulary → new trigger → save →
reopen → export), cross-level trigger isolation in both directions, per-level
`noSpawnRow`, shared program and definition edits visible from both levels,
shared edits persisted to the library and not the level, per-level export
resolution, Level 1's Square trigger, Level 2 having none, and the preview
resolving both an ordinary and a Square trigger through the shared library.

| Suite | Before | After |
|---|---|---|
| `tools/level_editor/test_*.py` | 39 pass / **1 fail** | 40 pass / **1 fail** |
| `make test` (engine) | 2 pre-existing failures | same 2 |

The editor failure is `test_v6_import.py`, failing before this work began for an
unrelated reason (it imports live Level 1 encounters onto a frozen 105-row v5
fixture). The two `make test` failures were proven pre-existing at HEAD in an
earlier task.

### Nine existing tests updated, none weakened

Every change is the same correction: an assertion that read the vocabulary out
of a **level file**, where it no longer lives.

| Test | Change |
|---|---|
| `test_v6_import.py`, `test_v6_phase4_roundtrip.py`, `test_v6_phase5a_gui.py`, `test_v6_phase5b_encounters.py` | read "the document the editor loads" as level **+** library, via one merged binding rather than twenty index sites |
| `test_editor_asset_workflow_gui.py` | counts the vocabulary from the library |
| `test_v6_phase4_roundtrip.py`, `test_movement_semantic.py` | a level file's fixed point is `to_level_json()`, not `to_json()` |
| `test_v6_phase5b_encounters.py` | "the edit really reached a persisted file" — the *library* for shared edits, the *level JSON* for triggers. Asserting only the level JSON would have failed for exactly the edits sharing exists for |
| `test_semantic_gui.py` | given a **disposable** library (it drives the real editor and was writing the production one); its reopen assertions now compare against the library it resolved from |
| `test_v6_phase5b_encounters.py` | its round trip goes through a temporary library, because a shared edit needs somewhere to persist |

Two of these were genuine bugs the tests exposed rather than expectation drift:
the `save()` idempotence failure revealed `ProjectV6.load` attaching while
`save` wrote everything back, and the phase5a fixed-point failure revealed the
empty-list-vs-missing-key confusion.

---

## 11. Preview and simulator

No behaviour change and no duplicated data. The preview receives the current
level's triggers and the shared vocabulary through the same `project` object it
always used. Semantic and raw movement, `from wave`, Ring/Dropper/Square,
launch-heading compilation and CONT semantics are all preserved — `make test`'s
movement suites and the 197-check `test_movement_semantic.py` pass unchanged.

---

## 12. UI

Modest, as asked. The two encounter tabs now read **"Movement programs
(shared)"** and **"Wave definitions (shared)"**, so a designer editing
`up_n_over` can see they are editing it for every level. No project manager, no
level selector, no override system, no wizard.

---

## 13. Files

**Added**

```
tools/level_editor/encounter_library.py            the shared library model
tools/level_editor/encounter_library.v6.json       the library itself
tools/level_editor/migrate_encounter_library.py    the one-shot migration
tools/level_editor/test_encounter_library.py       49 checks
reports/shared-encounter-library.md
```

**Changed**

| File | Why |
|---|---|
| `project_v6.py` | `to_level_dict/json`, `shared_vocabulary`, `attached_vocabulary`, symmetrical `save` |
| `controller_v6.py` | library ownership, load/save/`save_library`, the three safety rules |
| `migration_v6.py` | `load_any` attaches the shared vocabulary |
| `editor.py` | one library per session; New Level seeds from it |
| `encounters_ui.py` | "(shared)" tab labels |
| `levels/level1/level.v6.json`, `levels/level2/level.v6.json` | the two shared keys removed; everything else identical |
| 7 × `test_*.py` | assertions repointed at the file that now owns the data |

**Deleted:** none.

---

## 14. Limitations

* **No per-level overrides**, by instruction. Editing `up_n_over` edits it
  everywhere; a level that wants a variant needs a differently-named asset.
* **The library is global to the repository**, with no namespacing. Two
  authors adding different `loop`s would meet `LibraryConflict` at migration —
  clear, but it is a stop rather than a merge.
* **No library UI.** It is edited through whichever level happens to be open,
  and only the tab label says it is shared.
* **Deleting a shared asset is unguarded**: nothing warns that another level's
  trigger still names it. Validation catches the dangling reference the next
  time that level is opened or exported, which is later than ideal.
* `test_v6_import.py` still fails for its pre-existing reason.
* **No VICE run.** Every generated file and all three binaries are
  byte-identical, so there is no runtime change to observe; the manual Square
  proof from the previous task still stands.

---

## 15. Hygiene

**Processes.** No VICE was launched by this work except `make test`, which
reaped its own PID; `pgrep -fl x64sc` is empty. No `pkill`/`killall`.

**Disk.** scratch 832K · `build/` 300K · `levels/` 188K · `assets/` 44K ·
library 4.5K. No per-run artefacts.

**A test run polluted production data mid-task** — `demo6b` into the shared
library and re-embedded assets into Level 1. Both were restored from the
pre-work snapshot, verified byte-identical, and the cause fixed (§7). The full
suite now leaves both files untouched, which is checked after every run.

**Final `git status`:** 22 modified, 7 deleted, 12 untracked — all listed in §13
plus the previous task's sprite work, which is unchanged.

**Nothing was committed and nothing was pushed.**

---

## Acceptance gate

| # | Criterion | Status |
|---|---|---|
| 1 | exactly one persisted authoritative shared library | ✅ `encounter_library.v6.json` |
| 2 | production levels no longer own divergent copies | ✅ both keys removed from both |
| 3 | triggers remain per-level | ✅ 9 and 7, isolation tested |
| 4 | `noSpawnRow` remains per-level | ✅ 725 and 352, isolation tested |
| 5 | New Level: blank triggers, shared defs/programs available | ✅ proved via the real seed path |
| 6 | opening swaps level composition, not the library | ✅ |
| 7 | shared edits visible from every level | ✅ both directions |
| 8 | saving/switching cannot silently lose shared edits | ✅ harvested, or refused loudly |
| 9 | runtime packages self-contained and level-specific | ✅ 14/14 files byte-identical |
| 10 | Level 1 content incl. Square trigger survives exactly | ✅ |
| 11 | Level 2 survives exactly, gains no Square | ✅ |
| 12 | Square/Ring/Dropper and movement contracts intact | ✅ |
| 13 | sprite-authority work untouched | ✅ byte-identical |
| 14 | nothing committed or pushed | ✅ |
