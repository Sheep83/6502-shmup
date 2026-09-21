# Level Editor v2, Phase 6B.1 — Authoring UX, Partial Preview and the Reusable-Asset Boundary

**Date:** 2026-09-21
**Scope:** `tools/level_editor/` only.
**Engine source changed:** **none.** No movement opcode was added, and the gate in §14 was applied and not passed.
**Result:** Delivered. Movement is authored in compass directions and named turns, partial paths preview as they are built, production persistence stays strict, and the authoring pane is usable at 13-inch laptop size.

---

## 1. Starting state and content protection

```
HEAD      8dfd8f4  Editor v2 hotfixes      (Phase 6A.1)
branch    main     upstream origin/main, in sync
```

The working tree carried the Phase 6B work plus the user's authored Level 1.
Before touching anything, the authoritative content was hashed and copied to
disposable scratch:

```
6eb85882c76664acb02592986fce43702fd847ef4c08c837acc57a99dd7461c1  level.v6.json
6a84ecc8ac01bbd07c4f22dd92747caa044448aa27ee4e0410b106b346e960e1  stage_charset.asm
9085db3b1d2c0a28b3cd0385f82c529188921f797a2550848e49b3242b10c13f  stage_config.asm
f6fb0d253b8a650e5a01121aefc7bc2220d17a881b5e44a31179e1065b7cb7ee  stage_enemies.asm
667705ec63ba77b39adacf6b2fa6f20066116b419013cd2780fa2579f37da89f  stage_map.asm
86675fa5463240bb1b983446735876afd693935b432c472eb8f2d04614c9cc0d  stage_turrets.asm
ca1c01f13fc37fd2bc9234347c2c870e2e1a1e8369655f42750d10da34d706f7  wave_encounters.asm
46d8368be99b994f5a82252d11ab26650f8640a290c2fa46c15cb675206d277c  wave_programs.asm
```

**All eight verify unchanged at the end of the phase.** Nothing was restored
from a fixture, a report or the old 105-row level. Every destructive manual
test ran on a disposable copy in scratch.

---

## 2. Schema: one optional key, still `formatVersion 6`

```json
{"kind": "STRAIGHT", "frames": 30}                 // Continue  (the default)
{"kind": "STRAIGHT", "frames": 30, "heading": 16}  // establishes Down
```

`heading` is **absent for Continue**, so every STRAIGHT written before this
existed loads as Continue — which is exactly what it meant. No migration step,
no version bump, and a relative program stays visibly relative in the file.

The Phase 6B `segments`/`stages` split is unchanged: `stages` remains the only
thing the exporter, validator and faithful simulator read.

---

## 3. STRAIGHT: Continue, or an explicit direction

| | |
|---|---|
| **Continue** (default) | fly on along whatever the previous segment produced — or the wave's launch direction when it is the first segment |
| **Explicit** | deliberately establish a new direction, chosen on a dial |

A segment list now reads as the brief asked:

```
STRAIGHT ↓ 25f  →  QUARTER RIGHT  →  STRAIGHT Continue 30f  →  EXIT
```

**An explicit direction is an intentional change of trajectory, not a
continuity bug.** `intentional_breaks()` reports which stage indices the author
deliberately redirected, and the continuity check skips exactly those — so the
invariant "a *Continue* STRAIGHT is tangent-continuous" is still enforced
everywhere else. An explicit direction on the *first* segment introduces no
break at all, because there is nothing before it to break from.

### A real bug this feature introduced, found and fixed

An explicit STRAIGHT sets the *velocity* but the engine's `wmPhase` is
untouched — `WM_STRAIGHT` never writes it. So a following `CONT` arc snapped
back to the launch heading: the identical stale-heading fault Phase 6B
diagnosed, reintroduced by the new feature.

The compiler now tracks **both** quantities: `heading` (the way the object is
actually travelling) and `phase` (what `wmPhase` holds at runtime). A turn
emits `CONT` while they agree — which is what keeps a relative program reusable
— and names the real heading when an explicit direction has moved them apart.
Costs nothing, and removes the snap:

```
STRAIGHT ↓ 20f   →  {'kind':'STRAIGHT','frames':20,'vx':0,'vy':6}
QUARTER LEFT     →  {'kind':'ARC_MIRROR','steps':16,'framesPerStep':4,'entryHeading':16}
STRAIGHT Continue→  {'kind':'STRAIGHT','frames':20,'vx':6,'vy':0}
```

### Relative versus self-directing

`heading_dependent()` is now precise: a program depends on its launch heading
only until an explicit direction establishes one absolutely. A program whose
first STRAIGHT is Continue is **relative and reusable**; one that sets its own
direction is **self-directing** and flies the identical path from every launch
heading — proved by test for all 64.

---

## 4. The compass dial

`compass_ui.py` — one reusable control, used by an explicit STRAIGHT direction
**and** by a wave definition's launch direction, because they are the same
question. It is deliberately **not** offered on relative turns, which stay
Left/Right by an angle.

* 64 positions, because the engine has 64 headings:
  `heading = round(atan2(dy, dx) / 2π × 64) mod 64`. Screen y grows downward
  and the engine measures clockwise from east with +y down, so the canvas angle
  *is* the engine angle with no correction.
* The eight named points are drawn long, labelled with arrows, and **Shift
  snaps** to them — easy without being a restriction.
* The exact value is shown beside the dial (`Down (16)`) and is never required
  knowledge.

**Quantisation proven deterministic**: every one of the 64 headings round-trips;
dragging anywhere inside a heading's cell (±0.45 of a step, five offsets each,
all 64 boundaries) resolves to that heading; the pointer's radius is
irrelevant; dead centre asks for nothing rather than guessing.

Wave definitions keep their exact `heading` entry — the authored content uses
10 and 12, which no eight-point picker would offer — with the dial as a way of
choosing the number and a readout that places off-point headings
(`launch heading 12 — between Down-Right and Down`).

---

## 5. Turns, radius and zigzag

Segments now name themselves the way the author asked for them:

```
QUARTER RIGHT        HALF LEFT (tight)        LOOP RIGHT
TURN RIGHT 67.5°     ← only when the angle has no name
```

Quarter/Half/Loop remain **angles of the one TURN primitive**, not separate
kinds, with radius (`tight`/`normal`/`wide` → `framesPerStep` 2/4/6) free on
all of them. Every combination — 3 angles × 2 handednesses × 3 radii × several
launch headings — is continuous, proved by test.

Zigzag ships as a macro that expands into ordinary segments on insertion:

```
STRAIGHT Continue 30f → TURN RIGHT 45° → QUARTER LEFT → QUARTER RIGHT
                      → QUARTER LEFT → TURN RIGHT 45° → EXIT
7 semantic segments → 7 engine records / 28 bytes
```

It returns to the heading it started on, is continuous throughout, and its cost
is on screen the moment it lands.

---

## 6. Partial preview: tolerant draft, strict production

### Architecture

`compile_draft()` returns **the longest prefix the strict compiler accepts** —
deliberately built *on* `compile_segments` rather than beside it, so there is
no second compiler to drift. A synthetic EXIT terminates the prefix (the
interpreter must have something to read at the end of the table) and a frame
cap stops the flight at the end of the last authored segment.

`Draft.authored_stages` drops that synthetic terminator, and **that** is what
the project stores — so an unfinished program still reads as unfinished.

### The split, working

| authored | preview | production |
|---|---|---|
| `STRAIGHT ↓ 25f` | 26 frames, "incomplete" | **refused** |
| `+ QUARTER RIGHT` | 90 frames | **refused** |
| `+ STRAIGHT Continue` | 120 frames | **refused** |
| `+ EXIT` | full flight to despawn | **valid** |

The warning is explicit and readable:

> *Incomplete movement: no EXIT segment; preview stops at the end of the
> authored path.*

and a malformed later segment renders the valid prefix with the reason:

> *Preview stops after segment 1: segment 2 cannot be simulated — segment 2
> (TURN): steps must be 1..255, not 0*

The end marker changes with it: an **open amber ring labelled "incomplete"**
rather than the finished ✗, because "the path ends here" and "the path ran out
of authored segments" should not look alike.

### Strictness was not weakened anywhere

Save already refused on validation errors, and still does. A new rule,
`movement.unfinished`, compiles every semantic program **in full** and errors
if it will not — and it is asked of the **segments, not the records**. That
distinction is load-bearing: a draft's stored records are the compiled *prefix*,
so a malformed segment is simply absent from them; checking records alone would
have called the program clean and let Save ship it with the author's unfinished
work silently dropped. Nothing is ever auto-added.

---

## 7. Layout repair

Every reported symptom was reproduced by measurement, and the causes were not
where they looked:

| cause | effect |
|---|---|
| the **program-list column** demanded 420px of a 525px tab for its four buttons | the authoring frame got **85px** — the movement controls vanished |
| seven segment buttons on one line wanted 889px | **Move up / Move down clipped to nothing** |
| the mode strip's label + three buttons wanted ~1226px | **Convert truncated to one pixel** |
| the preview's member row requested 443px for a one-line readout | the picture crowded the controls |

Fixes: the list buttons and the segment buttons wrap to 2×N grids, the mode
strip's label and buttons take separate rows with short labels, the preview's
readout moved to its own row, and the preview canvas now **scales to the space
it is given** (`CANVAS_W` dropped 430→300 with a 220px floor) instead of
demanding a fixed width. The workspace is 1500×820 with a **1100×620 minimum**
— deliberately inside a 13-inch Mac window, because "make the window bigger" is
not a fix.

### Real-Tk geometry evidence (`test_layout_gui.py`, 33 checks)

```
13-inch  1280x760: timeline 170  tabs 648  preview 386   →  authoring 68% / preview 32%
15-inch  1440x820: timeline 170  tabs 808  preview 386   →  authoring 72% / preview 28%
full     1920x1080: timeline 170 tabs 1078 preview 386   →  authoring 76% / preview 24%
```

At every size: no mapped control is narrower than it asked to be, `▲ Move up`,
`▼ Move down` and `Convert…` are present and un-truncated, diagnostics wrap
inside the authoring column, the segment detail column keeps real room, and the
preview canvas stays above its readable floor. Shrinking then re-growing the
window returns the space to authoring rather than the picture.

---

## 8. Raw-mode behaviour: unchanged

Raw programs may still express what semantic mode forbids. The Phase 6B
machinery is untouched: the `movement.discontinuity` **warning**, the ⚠ marker
on the offending record, the plain-English explanation, and the explicit,
undoable **Make continuous** one-byte fix. Nothing is silently rewritten, the
engine was not changed to make raw programs behave, and none of this is
knowledge an ordinary semantic author needs.

---

## 9. The project-level reusable-asset boundary

**No library migration was performed, and none was smuggled in.** What was
required was not cementing the wrong ownership, and that holds:

* `movement_semantic.py` still knows nothing about a stage. Compilation is a
  pure function of `(segments, launch_heading)`; `resolve_for_headings()` takes
  a bare list of headings.
* The new draft compiler and the compass are equally stage-agnostic — a draft
  is `(segments, heading) → prefix`, and the dial is a widget over a number.
* `MovementProgram`'s docstring still records that **the segments are the asset
  and the records are a per-use cache** of one launch resolution.
* Nothing added in this phase introduced a stage-specific assumption into
  semantic persistence.

### The deferred migration, concretely

1. Move `movementPrograms` and `waveDefinitions` into a **repository-scoped**
   encounter-library file that travels with the repo (not machine-global);
   stages keep terrain, turrets, trigger placements and stage metadata, and
   triggers hold references.
2. Give the exporter a resolve-and-pack step: walk the stage's triggers, collect
   only the wave definitions and movement programs actually reached, compile
   each program against the launch heading of the wave that reaches it, assign
   compact runtime indices, and emit a normal stage-local package. Unused
   library assets then cost the C64 nothing.
3. A heading-dependent program used from two headings stops being a warning and
   becomes two packed entries — compilation is already per-(program, heading),
   so the packer simply calls it twice.

The runtime package format needs no change for any of this.

---

## 10. Tests

| Suite | Result |
|---|---|
| **`test_movement_semantic.py`** | **All 196 checks passed** |
| **`test_semantic_gui.py`** (real Tk) | **All 60 passed** |
| **`test_layout_gui.py`** (real Tk, new) | **All 33 passed** |
| `test_preview_gui.py` | All 61 passed |
| `test_encounters_gui.py` | All 59 passed |
| `test_v6_phase5a_gui.py` | All 56 passed |
| `test_editor_workshop_gui.py` / `test_editor_asset_workflow_gui.py` | 9 / 6 passed |
| 30 headless files | **30 pass, 0 fail** |

**The headless suite is fully green for the first time since the level grew.**

### Stale-fixture cleanup (§13)

Three suites were failing for the wrong reason — they encoded the *old* Level 1
rather than the contract under test. Each was repaired by deriving the value,
never by restoring content:

| file | was | now |
|---|---|---|
| `test_v6_export.py` | `noSpawnRow == 340` | `== project.stage.no_spawn_row`, with a non-zero guard so a failed load cannot pass vacuously |
| `test_v6_phase4_roundtrip.py` | moved trigger 3 to row 340/341 | moves the **last** trigger to `no_spawn_row` (+1), so the list stays sorted and the rule under test is the one that fires |
| `test_v6_phase5a_gui.py` | `no_spawn_row == 340`; append 2 turrets for "10, over the cap" | compares with the canonical project; appends until `MAX_TURRETS` is actually exceeded |

`test_v6_import.py` keeps its Phase 6B change (asserting the exact expected
warning pair rather than "no warnings"), so a new warning is still a failure.

### Faithful-trajectory evidence

Every trajectory claim is settled by flying it through the Phase 6A simulator,
which is proved frame-for-frame against a real 6502. **No second preview engine
was created.** Continuity is asserted on the **tangent**, not on the stored
heading — the assertion that would have caught the original Phase 6B bug.

---

## 11. Manual GUI proofs

Run on a disposable copy, never the canonical project.

**A — progressive construction.** `STRAIGHT ↓ 25f` previews immediately
(26 frames) with the incomplete warning and is refused by production; adding
`QUARTER RIGHT` extends it to 90 frames; adding `STRAIGHT Continue` to 120, with
tangent continuity confirmed apart from the deliberate first direction; adding
`EXIT` clears the warning and makes it valid.

**B — explicit direction.** Dragging to a cardinal (Down → 16, record `(0,+6)`),
a diagonal (Up-Right → 56, `(+4,-4)`) and an off-eight point (→ 2, `(+6,+1)`);
the preview follows each.

**C — inheritance.** With the first STRAIGHT set back to Continue the program is
relative, and launched Down / Left / Up every heading is rotated by exactly
16 / 32 / 48.

**D — turns and radius.** All Quarter/Half/Loop × Left/Right × tight/normal/wide
continuous; handedness correct from Down (Quarter LEFT → Right, Quarter RIGHT →
Left).

**E — zigzag.** Authored with no raw records: 7 segments → 7 records / 28 bytes,
continuous, returns to its entry heading, validator clean.

**F — layout.** Covered by the 33 geometry checks above at all three sizes.

---

## 12. Canonical Level 1

```
canonical sha256      6eb85882c76664acb02592986fce43702fd847ef4c08c837acc57a99dd7461c1
no-op JSON identical  True
programs all raw      True
ASM byte-identical    7/7
validator             0 errors, 16 warnings
```

All eight authored files verify against the pre-work baseline. No-op open, save
and export change nothing — guaranteed structurally, because the canonical
programs carry no `segments` and a program without segments is never
recompiled.

**Runtime / cycle / memory impact: none.** `src/` and `Makefile` were not
touched; every change is editor-side.

---

## 13. Files changed

```
 M project_v6.py            Segment gains `heading` (absent = Continue)
 M movement_semantic.py     explicit direction, engine-phase tracking, compass
                            names/arrows, compile_draft + Draft, named turns
 M controller_v6.py         drafts accepted, segment_incoming_heading, program_draft
 M validation_v6.py         movement.unfinished (asked of the SEGMENTS)
 M preview_ui.py            partial preview, incomplete marker, scaling canvas
 M encounters_ui.py         direction controls, layout repair, dial on waves
 M movement_sim.py          simulate_trigger forwards stages/max_frames
?? compass_ui.py            the reusable direction dial
?? test_layout_gui.py       33 real-Tk geometry checks
 M test_movement_semantic.py / test_semantic_gui.py / test_preview_gui.py
 M test_v6_export.py / test_v6_phase4_roundtrip.py / test_v6_phase5a_gui.py
                            stale fixtures derived rather than remembered
```

`src/level1/*.asm` and `levels/level1/level.v6.json` appear in `git status`
because **the user** modified them before this phase; they are byte-identical to
the baseline and were not touched here.

---

## 14. Unresolved and deferred

* **The encounter-library extraction** (§9) — deliberately deferred, with the
  abstraction and the migration path documented above.
* `test_v6_phase6a1_hotfixes.py` still hangs, as it did at HEAD before this
  phase. It is Tk-dependent and was not touched; not diagnosed here.
* Templates still unshipped: Dive, Pull Out, Sweep, Hover→Exit. The macro
  mechanism is in place; each is a few lines.
* Zigzag amplitude is swing-angle × radius rather than a pixel width.
* Phase 7 drag-and-drop encounter editing was **not** started.

---

## 15. Hygiene

* **Nothing committed, nothing pushed.**
* No VICE was needed; none is running. **No editor processes remain.**
* Destructive manual work ran on disposable scratch copies only.
* `__pycache__` cleared; no build artefacts accumulated.

```
build/  300K    tools/level_editor/  2.6M    repo  13M
```

---

## 16. Acceptance

All twenty-two criteria met. The three that carry the rest:

> **1. normal semantic authoring no longer requires understanding heading
> numbers** — directions are dragged on a compass and named (`Down (16)`), turns
> are Quarter/Half/Loop Left or Right, and no entry-heading control exists in
> the semantic view.
>
> **8/9. incomplete paths preview progressively, and still cannot be saved** —
> the draft compiler flies the longest valid prefix while `movement.unfinished`
> refuses the save, asked of the segments so nothing is silently dropped.
>
> **20. no speculative runtime opcode was added** — the existing VM expresses
> the whole of Phase 6B.1.
