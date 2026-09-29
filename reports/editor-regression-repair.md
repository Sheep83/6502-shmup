# Repairing the editor regressions from the enemy-identity pass

**Date:** 2026-09-29
**Committed or pushed:** no. **No destructive git operation was used.**

---

## 0. What happened

I shipped editor code I had not run. I said so in the previous report — "the
editor UI was not exercised on screen… worth one manual open" — but naming a gap
is not the same as leaving it acceptable, and the gap was not cosmetic: the
Encounter window could not open, could not close, and the enemy selector could
not be used. A suite of 93 green tests said everything was fine.

All three reported failures reproduced exactly. A **fourth** of the same family
was found by the new test and fixed before it could reach you.

---

## 1. Reproduction

Reproduced first, from the current tree, in a **withdrawn** Tk session — the
widgets are really built by Tk but nothing is mapped, so no focus is taken:

```
F3 REPRODUCED: AttributeError: 'V5View' object has no attribute 'enemy_slots'
               and no __dict__ for setting new attributes
F1 REPRODUCED: AttributeError: 'EncounterWorkspace' object has no attribute 'project'
               return [C.identity_label(n) for n in C.level_identities(self.project)]
```

Failure 2 (`t_species` missing, `preview` missing on close) follows from F1 and
needed no separate reproduction: with construction aborting inside `_build()`,
those attributes are simply never created.

A fourth, **not in your list**, surfaced only once a slot actually changed:

```
AttributeError: 'V5View' object has no attribute 'triggers'
  editor.py _apply_enemy_art:  for t in self.project.triggers:
```

You had not reached it because the first exception fired earlier in the same
callback.

---

## 2. Root causes

All four are one mistake in two shapes: **I wrote to the wrong object.**

The editor holds two different things and I conflated them:

```
controller.project   ProjectV6   the real, mutable model
controller.view      V5View      a naming facade, __slots__ = ("_p",)
editor.self.project  = controller.view          <- the FACADE
workspace            has no `project` at all    <- by design
```

### Failure 1 — `EncounterWorkspace.project` never existed

`EncounterWorkspace`'s own docstring opens with *"It owns no project state.
Every edit goes through `controller`"* — and that was true. My two identity
helpers invented `self.project`. Because `_identity_labels()` is called from
`_build_triggers()`, construction raised **part-way through `_build()`**:
`_build_waves()` and `_build_programs()` never ran, so Wave Definitions and
Moves did not exist.

**Fix:** use `self.controller.project`, which is the interface the class already
documents.

### Failure 2 — a half-built window stayed alive

`__init__` called `_build()` with no teardown, so when `_build()` raised, Tk was
left holding a mapped `Toplevel` whose `WM_DELETE_WINDOW` handler
(`_close → self.preview.pause()`) referenced a preview construction never
reached. That is why it could not be closed and why every click raised.

**Fix, two parts:**

* `__init__` wraps `_build()`/`refresh()` and **destroys the window before
  re-raising**, so a failed construction cannot leave a live one behind;
* `_close()` is defensive *only where teardown genuinely needs it* — it is the
  window-close handler and must not itself raise. It pauses the preview if there
  is one, clears the host reference only if it still points at this workspace,
  and tolerates a Tk object already gone. No broad `hasattr()` scattering: the
  ordering fix is what makes the rest unnecessary.

### Failure 3 — `V5View` is slotted and had no `enemy_slots`

`V5View` is `__slots__ = ("_p",)` and exposes every editable field as a
**property pair**. I added identity slots to `ProjectV6` and to the editor, and
never added the property to the view the editor actually writes to.

**Fix:** a real `enemy_slots` property and setter on `V5View`, delegating to the
live `ProjectV6`. The setter normalises through `contract_v2`, so the view cannot
store a short, long or unknown selection. Both sides read one list — there is no
second copy to diverge.

### Failure 4 — the same mistake one line later

`_apply_enemy_art` also did `self.project.triggers`. Fixed to
`self.controller.project.triggers`. I then grepped `editor.py` for every other
`self.project.<model field>` access; `enemy_slots` is the only remaining one and
it now resolves through the new property.

---

## 3. Why the tests missed it

Every test I wrote called **helpers in isolation** — `enemy_slot_cost`,
`level_identities`, `render_stage_enemies` — or checked constants. Not one asked
Tk to build a window. `_identity_labels()` was never called on a real
`EncounterWorkspace`, and `V5View` was never assigned to.

The suite could not have caught this, and its greenness was actively
misleading — which is the failure mode `AGENTS.md` warns about: *"a green
instrument can be wrong."*

---

## 4. The new regression test

`tools/level_editor/test_editor_workspace.py` — **37 checks**, and it builds real
widgets rather than mocks:

* loads real Level 1 data and the real `EditorController`;
* proves the editor holds a `V5View` and that identities can be set **through
  it** and reach the underlying `ProjectV6`;
* constructs a real `EncounterWorkspace` and asserts a widget from **each** of
  the three areas — `t_species`, `wave_list`, `prog_list` — not tab labels,
  because the regression left the notebook present and the tabs missing;
* asserts the workspace never grows a bogus `project` attribute;
* checks the trigger selector lists the level's own identities by human name;
* selects a trigger, refreshes, and switches every tab;
* changes the level's identities and re-checks the trigger choices;
* closes through the real `WM_DELETE_WINDOW` handler and reopens;
* **simulates a construction failure** and proves no live window is left;
* round-trips identities through save → reload → export;
* constructs the **real `LevelEditor`**, as `python3 editor.py` does, and drives
  `_apply_enemy_art` through all three budget boundaries.

### It was proved to catch the original bug

With the one-line fix temporarily reverted:

```
FAIL EncounterWorkspace constructs without raising
       -- AttributeError: 'EncounterWorkspace' object has no attribute 'project'
FAIL a construction failure propagates rather than leaving a half window
12 passed, 2 failed
```

Fix restored: **37 passed, 0 failed.** A test that has never been seen to fail
is not evidence; this one has.

**It also caught Failure 4 on its first full run**, which is how that bug was
found rather than delivered to you.

If no display is available the file prints `SKIP` and exits 0 rather than
reporting a pass it did not earn.

---

## 5. Workflow exercised

Constructed and driven for real by Tk, withdrawn so no focus was taken:

| Step | Result |
|---|---|
| **A** editor starts | `LevelEditor` constructs; title `19656 Level Editor - level1` |
| **B** identity selection | 3 slot combos, **12** roster choices, budget live |
| | 8 + 6 + 4 → `18 / 20` · 8 + 6 + 6 → `20 / 20` · 8 + 8 + 5 → `21 / 20   OVER BUDGET` |
| | and another slot brings it back to `17 / 20` — recoverable |
| **C** Encounters opens | 3 tabs, all three areas' controls present |
| **D** trigger selector | `['Ring 3', 'Space Whisk', 'Spinner']` — real names |
| **E** interaction | trigger select, detail refresh, full refresh, every tab switched — no exceptions |
| **F** close / reopen | closes through its own handler, host reference cleared, reopens, closes again |
| | editor destroyed cleanly |

### Manual on-screen acceptance — not performed, and why

I did **not** put the editor on your screen. On macOS Tk is Aqua; there is no
Xvfb-style isolated display, so a mapped window would raise itself and steal
focus, which the brief asks me to avoid. Everything above is **real Tk widget
construction and interaction**, not mocks — but it is not a human looking at
pixels, and I am not claiming it is. The remaining check that only you can make
is visual: that the new controls look right and read well.

---

## 6. Round trip and export

```
load Level 1 -> set ['RING_3','SPACE_WHISK','SPINNER'] -> save -> reload
  identities survive                    yes
  the saved JSON carries enemySlots     yes
  exports with them                     Ring 3, Space Whisk, Spinner
  cost                                  LVL_SPR_BLOCKS = 20   // of 20
8 + 8 + 5 = 21                          refused by the exporter
```

The exact-20 boundary is exercised end to end, and the over-budget case is
refused by the exporter independently of anything the UI did.

---

## 7. Tests

| Suite | Result |
|---|---|
| `test_editor_workspace.py` (new) | **37 passed, 0 failed** |
| `test_spd_pipeline.py` | **93 passed, 0 failed** |
| `test_v6_validation.py` | **PASS** |
| `test_wave_schema.py` | **PASS** |
| `test_v6_phase5b_encounters.py` | **PASS** |
| `test_encounter_library.py` | 48 passed, **1 pre-existing failure** |
| `test_v6_import.py` | **1 pre-existing failure** |

One check of mine from the previous task needed updating: `{lvl} authors only
species the engine has` compared trigger species against `C.SPECIES` (the three
slot names), which stopped being what a trigger stores when identities landed.
It now checks a trigger names an enemy the level actually carries.

The two remaining failures predate both tasks and are unrelated to the editor:
`test_encounter_library` asserts Level 1 has nine triggers when it has twelve
(and had twelve at `HEAD`), and `test_v6_import` fails on `worldProgress 350 is
at or beyond noSpawnRow 340` in its own synthetic fixture. Neither is in the
Makefile's routine set; left alone, as instructed.

### Build and smoke

`make build` succeeds. `make smoke` — **PASS**, `ENGINE HEALTH: PASS`,
`ROUTINE REGRESSION: PASS`, every fatal counter zero. VICE launched and reaped
by exact PID; `pgrep -x x64sc` reports none remaining.

---

## 8. Files changed

| File | Change |
|---|---|
| `tools/level_editor/encounters_ui.py` | identity helpers use `self.controller.project`; `__init__` destroys the window if `_build()` raises; `_close()` made safe as a teardown path |
| `tools/level_editor/controller_v6.py` | `V5View.enemy_slots` property + setter |
| `tools/level_editor/editor.py` | `_apply_enemy_art` reads triggers from the model, not the view |
| `tools/sprite_export/test_spd_pipeline.py` | trigger check updated to the identity model |
| `tools/level_editor/test_editor_workspace.py` | **new** |
| `reports/editor-regression-repair.md` | **new** |

Nothing in the engine, the package format, the importer, the exporter's
behaviour, the roster, the budget rules or any level data was touched. The
variable-frame work, the package-local animation table, the identity model, the
Dropper behaviour association and the 20-slot budget are all exactly as they
were.

---

## 9. Remaining limitations

* **On-screen manual acceptance is still yours to do** (§5).
* The two pre-existing suite failures above remain.
* `import_engine_v6` still maps an engine species value back to the default
  identity for that slot, as documented last task.

---

## 10. Status

- **Nothing committed, nothing pushed.**
- **No `git checkout`, `restore`, `reset`, `stash` or `clean` was used.** Only
  `status`, `log`, `diff` and `show`, all read-only. Unrelated dirty work is
  intact.
- VICE: exact PIDs owned and reaped; no `pkill`/`killall`; no user-launched
  instance touched; no focus stolen at any point.
