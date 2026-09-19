# Level Editor v2, Phase 5B — Encounter Authoring UI

**Date:** 2026-09-19
**Scope:** `tools/level_editor/` only. No engine source, test or Makefile change.
**Result:** Delivered. The v6 encounter model is directly editable from the GUI;
every Phase 1–5A round-trip guarantee still holds byte-for-byte.

---

## 1. What was built

A new **Encounter workspace** — a `Toplevel` over the host editor's live
controller, opened from *File → Encounters…*, `Ctrl+E`, or the toolbar button.
It was made a separate window rather than a notebook tab so the terrain,
metatile and turret workflow is not restructured at all; this follows the
existing `workshop_ui.WorkshopDialog` precedent in the same codebase.

Layout:

```
┌─ capacity strip: triggers 4/180 · wave defs 4/26 · movement records 13/64 · movement bytes 52/256 ─┐
│                              │  ┌ Triggers ┬ Wave definitions ┬ Movement programs ┐               │
│  Stage (worldProgress)       │  │                                                 │               │
│  ascending canvas timeline   │  │  master list  │  detail form                    │               │
│  + noSpawnRow entry          │  │                                                 │               │
│  + quiet-zone readout        │  └─────────────────────────────────────────────────┘               │
├──────────────────────────────┴─────────────────────────────────────────────────────────────────────┤
│  Validation — the validator's own issues, error red / warning amber, click to jump to the object    │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Three files carry the work:

| File | State | Lines |
|---|---|---|
| [controller_v6.py](tools/level_editor/controller_v6.py) | modified, +406 | 929 |
| [encounters_ui.py](tools/level_editor/encounters_ui.py) | **new** | 932 |
| [editor.py](tools/level_editor/editor.py) | modified, +41 | — |
| [test_v6_phase5b_encounters.py](tools/level_editor/test_v6_phase5b_encounters.py) | **new** | 374 |
| [test_encounters_gui.py](tools/level_editor/test_encounters_gui.py) | **new** | 233 |

### The split, and why

Every encounter operation lives in `controller_v6.py`, which imports no Tk.
`encounters_ui.py` draws and dispatches; it decides nothing. The consequence is
that the authoring guarantees are provable **headlessly** — 71 of the checks in
this phase never construct a widget — and the widget suite is left to prove only
that the window is *wired* to those operations.

---

## 2. The brief's constraints, one at a time

### Absolute `worldProgress`, not editor row coordinates

The timeline axis is `worldProgress` ascending 0..`playableProgress`, drawn
directly from the model. `_y_of(progress)` / `_progress_at(y)` convert only for
pixels. **No converted coordinate is stored anywhere.**

The terrain cross-reference a level designer needs is present but **display
only**, recomputed on every refresh from `stage.logical_rows`:

```
worldProgress 48 → (logical row 371, metatile row ≈ 92)
```

### Exporter concerns stay hidden

Row low/high bytes, definition indices, physical column offsets and trigger
capacity padding appear nowhere in the UI. The only capacity the user sees is
the honest budget strip — `4/180`, `4/26`, `13/64`, `52/256` — which is what a
designer needs to know before adding content, not a byte layout.

### One rule set

The workspace contains **no validation logic**. `controller_v6.py`'s encounter
section carries this header:

> *None of them validates. `validation_v6` is the one rule set (the brief's "do
> not invent a second"), so an operation that would produce an invalid project
> still performs it and the workspace shows the validator's own error. The
> exceptions are the STRUCTURAL refusals — a duplicate id, a delete that would
> strand a reference.*

So nothing is silently coerced. Setting `noSpawnRow` to 40 with triggers at 48+
**succeeds**, and the validation panel turns red with the validator's own
`noSpawnRow` errors, with export blocked until the author fixes it. That is
proved by test rather than asserted here (§4, last GUI check).

### `CONT` is a real choice

```python
HEADINGS = ["CONT"] + [str(i) for i in range(C.WM_HEAD_LEN)]
```

`CONT` is the first entry of the entry-heading combobox and is kept as the
string `"CONT"` through `update_stage` — never as `255`. The canonical Level 1
already authors it: program `s`, stage 1 displays `20 steps, 3 frames/step,
entry CONT`.

### Fire mask — checkboxes, and no silent data loss

The mask is rebuilt as one checkbutton per member, the count coming from
`controller.trigger_members(index)` — i.e. from the **referenced wave**, not the
trigger. No hexadecimal byte is ever typed.

Re-pointing a trigger at a smaller wave therefore leaves member indices that
cannot exist. Phase 5B does **not** drop them. `impossible_fire_members(index)`
reports them, the validator errors on them, and a **Trim** button appears beside
the checkboxes only while that list is non-empty. Trimming is the explicit,
confirmed cleanup action the brief asked for, never an automatic one.

### Renames, duplicates, deletes

`rename_wave_definition` and `rename_movement_program` rewrite the id *and every
reference to it* in a single operation, which reaches the undo stack as **one
step** (proved). Duplicate ids raise `ControllerError`. `delete_wave_definition`
refuses while any trigger references it, and names the referencing triggers in
the refusal, rather than leaving the author to guess.

### No stale payload

`set_stage_kind` **replaces the stage object entirely** rather than mutating
fields. Changing `ARC` → `STRAIGHT` leaves `entry_heading` at `None` and `steps`
at `0`, so nothing hidden can reappear on a later kind change. Verified directly
in the headless suite.

### Dropper side

`update_trigger` resets `dropper_side` to the canonical neutral `LEFT` whenever
species leaves `DROPPER` (the validator warns on a `RING` carrying a non-`LEFT`
side). In the UI the side combobox is `readonly` for `DROPPER` and `disabled`
otherwise — observed in both states.

### Stable trigger sort

Equal `worldProgress` values are legal in v6 — only a *decrease* is an error —
so `sort_triggers()` sorts non-decreasing and **stably**, preserving author
order among ties. Tested.

---

## 3. Not built, deliberately

Per the brief, **no graphical trajectory or movement preview**. Absent by
design, and recorded in the module docstring so Phase 6 inherits the intent:

- no sprite-path drawing
- no per-frame movement simulation
- no formation preview
- no launch-to-exit animation
- no viewport/clamp simulation
- no Dropper/protector visualisation

The old v5 Waves panel was **not** recreated; the notebook is compact
master/detail throughout. No new dependency was introduced — Tkinter only.

---

## 4. Proof

### Canonical no-op — the headline guarantee, re-run on the final tree

```
canonical sha256: acef2dc09c6c366dae223dbde6e8702098d45176dde560140c710b8c72e1a2ec
JSON byte-identical : True
stage_charset.asm        identical
stage_config.asm         identical
stage_enemies.asm        identical
stage_map.asm            identical
stage_turrets.asm        identical
wave_encounters.asm      identical
wave_programs.asm        identical
validator           : clean
```

Opening and saving the canonical project without edits still produces byte-identical
JSON, and export still reproduces `src/level1/` exactly.

### Editor suites — 30 files, 30 pass, 0 fail

| Suite | Result |
|---|---|
| 26 headless files | all pass |
| `test_v6_phase5a_gui.py` (real Tk) | All 55 Phase 5A GUI-model checks passed |
| `test_editor_workshop_gui.py` (real Tk) | All 9 passed |
| `test_editor_asset_workflow_gui.py` (real Tk) | All 6 passed |
| **`test_v6_phase5b_encounters.py`** | **All 71 Phase 5B encounter-authoring checks passed** |
| **`test_encounters_gui.py`** (real Tk) | **All 59 encounter-workspace GUI checks passed** |

Real-Tk suites run under `/usr/local/bin/python3` (Tk 8.6), as established in
Phase 5A.

**The round-trip shape of the headless suite.** Each controlled edit runs an
`edit_cycle(name, mutate, verify, restore)` that proves four things: the edit
survives save/reload, it *really changed the JSON* (so the test cannot pass
vacuously), and on restore the project returns to byte-identical canonical JSON
**and** byte-identical generated ASM. Four cycles run: trigger move, `noSpawnRow`
change, wave-definition field, movement-stage field.

**The shape of the widget suite.** Each edit runs a `cycle(name, do, changed,
undo_back)` proving it marks the document dirty, pushes **exactly one** undo
step, that undo restores the whole project and redo re-applies it. Covered:
trigger add / edit / delete, `noSpawnRow`, wave field, stage edit, stage
reorder, fire checkboxes, program rename, Save As + reopen, and the
validator-driven error panel. Navigation — selecting triggers, waves and
programs — is separately proved **not** to dirty the document.

### Manual acceptance (§23), observed against canonical Level 1

```
ok  - triggers shown at 48, 52, 90, 126
ok  - noSpawn shown at 340
ok  - four wave definitions listed
ok  - four movement programs listed
ok  - 13 movement records / 52 bytes
ok  - species/fire/side values correct
ok  - trigger names its wave  [s]
ok  - wave names its program  [s]
ok  - wave reports which triggers use it  [used by 1 trigger(s) at worldProgress 52]
ok  - program shows its ordered stages  [ARC_MIRROR, ARC, EXIT]
ok  - ...with readable payloads, no byte offsets  [12 steps, 3 frames/step, entry 12]
ok  - ARC entry heading offers CONT as a real choice
ok  - ...and the canonical second arc already uses it  [CONT]
ok  - timeline marks the quiet zone and the boundary
ok  - canonical project still validates clean in the workspace
```

Quiet-zone readout: `quiet zone 55 rows ≈ 8.8s (stage ends 395)`.

---

## 5. A Phase 5A defect found and fixed here

**This must be reported plainly: Phase 5A shipped a bug, and I shipped it.**

`editor.py` `_apply_level_settings` referenced `C.MAX_C64_COLOUR`, **which does
not exist**. Any change to a palette spinbox raised `AttributeError`. It
survived Phase 5A because that phase's smoke test exercised painting, metatiles,
save, export and reopen — but never the palette-apply path.

Fixed:

```python
ranges = {"background": C.MAX_COLOUR, "multicolour1": C.MAX_COLOUR,
          "multicolour2": C.MAX_COLOUR, "character": C.MAX_CHARACTER_COLOUR}
```

Verified: apply 12→5 works, out-of-range 99 is rejected, undo restores 12.

A second defect was found in my own Phase 5B work in progress:
`duplicate_wave_definition` constructed its clone twice, the first time via
`WaveDefinition(**{**src.to_dict(), ...})` — which passes *JSON* field names
(`startX`, `movementProgram`) to a dataclass that wants Python ones. The dead
construction was removed and a comment left explaining the trap.

---

## 6. Engine regressions (§26)

**`src/`, `tests/` and `Makefile` are untouched — `git status --porcelain` on
them is empty — and the built `shmup.prg` and `level1.prg` are byte-identical to
the pre-change build.** No engine test outcome can be attributable to Phase 5B.
The runs below are therefore a check that the tree is where it was, not a claim
about new code.

| Test | Result |
|---|---|
| `test_wave_triggers` | **ALL PASS** |
| `test_movement_pool` | **ALL PASS** |
| `test_no_spawn_row` | **ALL PASS** |
| `test_production` (pristine health gate) | **ALL PASS** |
| `test_dropper_flight` | 1 failure — `schedBuildDefer` = 1 |
| `test_token_encounter` | 1 failure — `schedBuildDefer` = 1 |
| `test_level_assets` | 3 failures — `publishSkip` 12, `schedBuildDefer` 1, window-pointer sampling |
| `make proof420` | package builds clean, rc 0 |

### These failures are inherited, and I did not touch them

`schedBuildDefer` is documented in [renderer.asm:338](src/renderer.asm#L338) as a
**saturating counter of the deferral guard working**, not a fault:

> *the swap is DEFERRED while a build is in progress… `schedBuildDefer` counts
> the deferrals so the cost is visible rather than silent.*

`tests/test_enemy_fire.py:181` already records the judgement that it "is NOT one
of them and is deliberately not asserted", because it drifts once the harness
hijacks the PC with breakpoint stepping — which is exactly what both failing
tests do before they read it. The value 1 matches prior reports precisely:

- `reports/test-token-encounter-exact-boot-repair.md:129` — *"still fails —
  inherited diagnostic noise, unchanged"*
- `reports/wave-contract-stage3-external-wave-data.md:201` — *"1 failure:
  `schedBuildDefer` = 1"*
- `reports/protector-guard-orbit-fix.md:126` — *"FAIL — 1, inherited noise"*
- `reports/e000-level-package-and-420-row-proof.md:320` — *"pre-existing noise"*

`test_level_assets`'s third failure is likewise already analysed in
`reports/test-harness-frame-accurate-boot-repair.md:433`: the check "needs
enemies, but the check samples 64 frames — eight coarse rows. From row 0 that is
nowhere near row 48… the file needs its sampling window moved to the
encounters." Out of scope here, as it was there.

**No assertion was weakened and no test was edited to make anything pass.**

### 420-row proof

`make proof420` regenerates the 420-row stage and assembles the package; its
capacity guards are assembler-time, so a clean build *is* the gate. It passed,
with the long stage's map running `$e000-$f067` and the package still closing on
`$fb70-$fb73 level signature`. The production build was then restored and
re-verified (`$e000-$e419 level map`).

---

## 7. Hygiene

- **No commit, no push.** Working tree left dirty for review.
- VICE: every run used `-console`, owned PIDs only, no `pkill`/`killall`, no
  focus steal. `pgrep -fl x64sc` before and after each run; none left behind.
- GUI: all verification windows were `withdraw()`n (no focus stealing) and
  destroyed. `pgrep` confirms **no editor processes left running**.
- `__pycache__` removed.

```
build/               356K
tools/level_editor/  1.3M
.                     11M
```

```
 M tools/level_editor/controller_v6.py
 M tools/level_editor/editor.py
?? tools/level_editor/encounters_ui.py
?? tools/level_editor/test_encounters_gui.py
?? tools/level_editor/test_v6_phase5b_encounters.py
```

```
 tools/level_editor/controller_v6.py | 406 +++++++++++++++++++++++++++++++++++-
 tools/level_editor/editor.py        |  41 +++-
 2 files changed, 442 insertions(+), 5 deletions(-)
```

---

## 8. What Phase 6 inherits

A complete, validated, GUI-editable encounter model with no preview layer. The
timeline canvas already owns the `worldProgress ↔ pixel` mapping and the quiet
zone, which is the coordinate system a trajectory preview needs; the controller
already exposes `movement_records` / `movement_bytes` / `movement_offsets()` as
derived values. Phase 6 builds the simulation against this model — it does not
need to restructure it.

**Phase 6 was not started.**
