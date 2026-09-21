# Level Editor v2, Phase 6B — Composable Semantic Movement Authoring

**Date:** 2026-09-21
**Scope:** `tools/level_editor/` only.
**Engine source changed:** **none.** No movement opcode was added, and none was needed.
**Result:** Delivered. Movement is authored as continuous segments —
`STRAIGHT → TURN RIGHT 90° → STRAIGHT → EXIT` — with no heading arithmetic
anywhere, and the canonical Level 1 is byte-for-byte untouched.

---

## 1. Starting state, and the content that had to be protected

```
HEAD        8dfd8f4  Editor v2 hotfixes          (Phase 6A.1)
            fa64867  Level editor v2: add engine-faithful wave preview  (6A)
branch      main     upstream origin/main, in sync
```

**The working tree was not clean, and that mattered.** It carried
**uncommitted, user-authored Level 1 content**: `level.v6.json` plus five
regenerated files in `src/level1/`. That is the authoritative content §0
protects, so before anything else it was hashed and copied to disposable
scratch:

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

The level has grown well past the old baseline — **200 metatile rows, 41
metatile definitions, 5 turrets, 5 triggers, 5 wave definitions,
noSpawnRow 725**. Nothing was restored from any historical fixture, and
**all eight hashes verify unchanged at the end of the phase** (§14).

Phase 6A.1 has no report of its own; its seven hotfixes are documented in
`tools/level_editor/test_v6_phase6a1_hotfixes.py`.

---

## 2. Audit: what the VM already carries, and what it made authors restate

The movement VM is untouched since `a1dc0ec`, so the Phase 6A audit stands. What
Phase 6B needed to establish is narrower: **what continuity already exists.**

| State | Carried between records? |
|---|---|
| position | **yes** — nothing resets it |
| heading (`wmPhase`) | **yes** — `WM_STRAIGHT` and `WM_HOLD` never touch it |
| velocity | **only into `WM_EXIT`**, which is what makes ARC → EXIT continuous |
| arc step/timer | per stage, re-armed by `wmEnterStage` |

**So continuity was already the engine's behaviour.** The one thing that broke
it was byte 3 of an arc: an ABSOLUTE entry heading. `WM_HEAD_CONT` ($ff) already
existed to say "continue from the heading already held" — it was simply never
the default, and only one of the four authored programs used it.

### What made authors restate inherited state

1. **An arc's entry heading.** Writing "turn right 90°" meant knowing the
   heading the object would be carrying and writing that number down.
2. **A straight leg's velocity.** `WM_STRAIGHT` stores a signed quarter-pixel
   `(vx, vy)` pair, so "fly on" meant looking up the heading table.

Both are pure arithmetic over state the compiler can track. That is the whole
of Phase 6B.

### What needed a runtime opcode

**Nothing.** §11's gate was applied and not passed:

| Wanted | Compiles to |
|---|---|
| Straight | `WM_STRAIGHT`, velocity = heading table at the tracked heading |
| Turn left/right, any angle | `WM_ARC_MIRROR` / `WM_ARC`, `steps = angle/5.625`, entry `CONT` |
| Quarter / half / full turn | the same record, `steps` 16 / 32 / 64 |
| Variable radius | `framesPerStep`, which *is* the turn radius |
| Hold | `WM_HOLD`, drift = a speed along the current heading |
| Exit | `WM_EXIT`, inheriting velocity |
| S-curve, loop, zigzag, sweep, hook | an ORDER of the above; no new record kind |

`AND #WM_HEAD_MASK` already makes a heading that wraps a loop, so a full circle
is **one record**. **No movement-engine change was made.**

---

## 3. The semantic model

`tools/level_editor/movement_semantic.py` — no Tkinter, no stage, no project in
the compiler's signature.

### The vocabulary is four kinds, deliberately

```
STRAIGHT   frames                      fly on along the heading inherited
TURN       direction, steps, rate      turn RELATIVE to the heading inherited
HOLD       frames, drift               stay put, or creep ALONG the heading
EXIT       --                          carry on out on what it inherits
```

Following the mid-phase clarification: **a quarter turn, a half turn and a full
loop are angles of the one turn, not separate kinds.** Making them distinct
types would mean mirroring, compiling, costing and lifting each learning three
things where one will do; `radius` is the turn's other axis and is free on all
of them. The named three are the first choices in the editor, with 45°/135°/270°
after them and a step count for anything else.

Angles are **stored in steps and presented in degrees** — 5.625° is not an
integer, and a stored float would be a rounding argument waiting to happen.

### Continuity is the default and is not a new mechanism

Every compiled turn emits `WM_HEAD_CONT`. Nothing else. A turn therefore means
"turn from wherever I am", the compiler tracks the heading so a `STRAIGHT` after
a 90° turn gets the *turned* heading's velocity, and **no segment contains an
absolute world X/Y or a heading index**.

### Macros expand on insertion

S-curve, loop and zigzag expand into core segments the moment they are added.
That keeps the persisted vocabulary at four kinds, puts the record cost on
screen immediately (§10), and leaves the author free to tune either half. A
zigzag is parameterised by swing, radius and repeats, returns to the heading it
started on, and costs `2·repeats + 1` records — which is exactly why it is a
macro and not a primitive that hides an arbitrary number of records behind one
row.

### Schema: one additive key, and **no version bump**

```json
{"id": "sweep",
 "stages":   [ ...engine records... ],
 "segments": [ {"kind": "STRAIGHT", "frames": 34}, ... ]   // optional
}
```

`stages` remains the only thing the exporter, the validator and the faithful
simulator read, so **nothing downstream of the model changed**. `segments` is
emitted only when non-empty, so a program authored before Phase 6B serialises
exactly as before.

§6 asked whether a version change was actually necessary. **It is not:** a file
carrying `segments` is still a valid `formatVersion 6` file, because `stages`
still carries the truth and a reader that ignores the new key gets a fully
correct project. Bumping would have invalidated every existing file for a key
that changes nothing about how the data is interpreted.

---

## 4. Compilation

`compile_segments(segments, launch_heading) → [MovementStage]`, deterministic,
with a designer-readable `CompileError` rather than a patch-around. It refuses:
a program not ending in EXIT, a segment after EXIT, zero-length anything, a
count that will not fit one byte, a drift past the engine's wrap guard, a
heading outside 0..63 — and one case worth naming:

> **a HOLD with no drift immediately before EXIT** would inherit no velocity,
> so the object would never leave and would hold a pool slot for the rest of the
> level. `src/waves.asm` rejects the same thing at assembly time as "never
> reaches any despawn edge"; the compiler catches it while it is still an edit.

### The one thing that is not heading-free — and why it matters for reuse

`heading_dependent(segments)` is true exactly when a program contains a
`STRAIGHT`, because that velocity is stored *in* the record. A program of
turns, holds and exits compiles to **identical bytes from all 64 launch
headings** — proven by test — which is precisely the property a shared library
asset wants. The editor surfaces which kind a program is
(`heading-free, so it serves any launch heading`) and names the conflict when a
heading-dependent program is used from two different headings.

---

## 5. Mirroring

A screen-space mirror is two halves that live in different objects:

| half | who owns it |
|---|---|
| every turn changes hand | the **movement program** — `mirror_segments()` |
| the launch heading `h → (32−h) mod 64`, and the spawn column | the **wave definition** — *not rewritten* |

This is **not** a swap of `WM_ARC`/`WM_ARC_MIRROR` in compiled records: that
would be wrong for any program holding an absolute entry heading and would say
nothing about the launch state. It is a transform of what was *authored*, and
because every compiled turn continues from the heading it inherits, the
reflection is exact.

Mirroring a program shows a dialog stating the mirrored launch heading the wave
would need and that **no wave definition has been changed** — asserted by test.

### Proved, not assumed

Over **all 64 launch headings**, flying both versions through the Phase 6A
faithful simulator:

* the **heading is exactly reflected on every frame**;
* the **velocity is exactly reflected on every frame** (`vx' = −vx`, `vy' = vy`);
* the position reflection offset `(x−x₀) + (x′−x₀)` is **always 0 or −1, never
  more** — the true reflection rounded to the pixel grid, which is the best
  integer arithmetic allows, because the engine's sub-pixel division floors in
  a fixed direction.

`mirror_segments` and `mirror_heading` are both involutions.

---

## 6. Existing programs: recognised, never converted behind the author's back

All four of the canonical project's raw programs **can** be said in semantic
terms, and the editor can show what they would become before anything happens:

| program | lifts to | records |
|---|---|---|
| `sweep` | `STRAIGHT 34f → TURN RIGHT 90° → EXIT` | 3 |
| `s` | `TURN LEFT 67.5° (3f/step) → TURN RIGHT 112.5° (3f/step) → EXIT` | 3 |
| `linger` | `STRAIGHT 28f → HOLD 48f drift +0,+1 → TURN RIGHT 67.5° → EXIT` | 4 |
| `loop` | `STRAIGHT 40f → TURN RIGHT 427.5° (tight) → EXIT` | 3 |

`sweep` is literally the brief's target sentence.

### The subtlety the fixture caught

Lifting is **path-lossless but byte-changing**. Three of the four were authored
before `WM_HEAD_CONT` existed, so their arcs name an absolute entry heading that
*happens* to be the one already held. A relative turn compiles to `CONT`
instead, so byte 3 changes from a heading to `$ff` — while `wmEnterStage`
reaches an identical state either way (it stores a heading it already holds,
versus skipping the store).

So the criterion for "lossless" is **the flight, not the bytes**: `lift_is_exact`
flies both versions through the faithful simulator and compares every
authoritative field, and reports byte-identity *separately* so the editor can
put it in front of the author:

> *The flight is provably identical, but the compiled BYTES will change… Nothing
> about how it flies changes.*

**Conversion is opt-in, dialog-confirmed, and one undo step.** A program that
cannot be lifted stays raw for ever — a supported state, not a failure — and the
only alternative offered is explicitly destructive and separately confirmed.
Raw and semantic programs coexist in one project; the canonical project's four
are **all still raw**.

---

## 6b. The continuity bug, investigated and fixed

Reported during manual testing: a raw `dive` program (`STRAIGHT → ARC → EXIT`)
visibly snapped direction where the straight met the arc, even though the arc
said `CONT`.

### Reproduced, and the divergence traced

```
frame  stage      x    y   vx  vy   wmPhase   direction of travel
   19  STRAIGHT  179   59   +4  +4       0        45.0 deg   (heading says 0.0)
   20  ARC       180   60   +6  +0       0         0.0 deg   <-- 45 deg SNAP
```

**Stored heading and actual travel had diverged, exactly as suspected.**
`WM_STRAIGHT` writes `wmVX`/`wmVY` and never touches `wmPhase` — `wmEnterStage`
has no `sta wmPhase` on that path, and `src/movement_format.asm` says so in
words: *"WM_STRAIGHT and WM_HOLD do not touch wmPhase and never have"*. So for
20 frames the object travelled at 45° while `wmPhase` still said 0, and
`WM_HEAD_CONT` then faithfully inherited a **stale** heading.

### How far it reached

Measured on the flown path against the arc's own per-step rotation (12.53°,
the table's widest single step — comparing against zero would flag every arc
in the game):

| | |
|---|---|
| raw `dive` | **45° snap** — the report |
| raw `linger` | **31° snap**, twice, around its drifting hold (pre-existing) |
| raw `sweep`, `s`, `loop` | continuous |
| semantic `STRAIGHT → TURN`, `TURN → STRAIGHT → TURN`, `STRAIGHT → TURN → STRAIGHT`, still `HOLD → TURN` | **continuous at all 64 launch headings** |
| semantic **HOLD with a drift** | **broken** — the one real hole |

Semantic programs were already safe for the reported case, and by construction
rather than luck: the compiler only ever emits a straight's velocity *from the
heading table at the heading it is tracking*, so the two cannot diverge.

### The hole, and the fix at the compiler boundary

A `HOLD`'s drift was a free `(vx, vy)` — an **absolute** vector inside an
otherwise relative vocabulary — so it could point away from the direction of
travel. That is precisely how `linger` acquired its 31° kink.

**`drift` is now a speed along the current heading**, not a vector. It cannot
point anywhere else, so both boundaries of a hold are continuous by
construction; and mirroring a hold now needs no transform at all, because a
speed reflects with its heading for free.

Two further engine facts had to be modelled to get this right:

1. **An arc's final rotation lands on the hand-off frame**, so the last
   velocity it actually *applies* is `HEAD[H+N−1]`, not `HEAD[H+N]` — the
   rotated velocity is overwritten by the next stage (except `EXIT`, which
   keeps it). The drift is checked against that true incoming tangent.
2. **A slow velocity cannot carry an arbitrary direction.** Velocities are
   whole quarter pixels, so the directions expressible at speed *v* are the
   lattice points at that radius: 64 at the arcs' speed of 6 (which is exactly
   why the heading table uses that magnitude), but only four at speed 1. A
   drift of 1 near a diagonal rounds to an axis and points up to **31°** away.

So the compiler **refuses** a drift whose rounding would take it off-heading,
naming a speed that works:

> *segment 2 (HOLD): a drift of 1 on heading 37 rounds to (-1, 0), which does
> not point along the heading — the engine's velocities are whole quarter
> pixels, so a slow drift cannot carry every direction. Use a drift of 2 or
> more, or none.*

That is the limitation the brief asked me to stop and report rather than
paper over. **No engine change was needed or made**: the options were (a) name
the arc's entry heading, which is one existing byte, or (b) make `WM_STRAIGHT`
derive and store `wmPhase`, which would cost cycles on every stage entry and
silently change existing content. (a) is sufficient.

### Result

**Zero continuity breaks across 6,680 randomly generated semantic programs at
random launch headings**, plus every preset angle × both directions × five
radii × seven launch headings. The regression asserts the **tangent**, not the
stored heading — the assertion the original suite lacked, which is why it
passed while the bug was visible.

### Raw programs: surfaced, never silently rewritten

Raw records can still kink — that is the engine's own latitude, and `linger`
ships with one. So the editor now says so instead of leaving it to be
discovered visually:

* `validation_v6` gains **`movement.discontinuity`** (a *warning*: the engine
  runs these paths perfectly well and erroring would condemn shipped content);
* the raw record list marks the offending stage with ⚠ and explains it;
* a **Make continuous** button applies the one-byte fix — entering the arc on
  the heading actually being travelled. On `dive` that is entry heading 8, and
  the 45° snap becomes **0.0°**. Explicit, undoable, never automatic.

`linger` consequently **no longer lifts** to semantic segments, and that is the
correct outcome rather than a regression: its hold genuinely kinks the path,
the continuous vocabulary cannot express that, and the long-standing rule is
that a program which cannot be said exactly stays raw. It keeps working
untouched.

---

## 6c. Preview launch heading, and compass terminology

Manual use exposed a missing authoring control: a new semantic program previews
on heading 0, so `STRAIGHT` naturally flies +x and there was no way to design
"straight down, then a quarter turn" in isolation.

**`STRAIGHT` was deliberately left alone.** Its meaning stays "continue along
the inherited heading" — direction is entry state, not a property of a leg.
Instead the preview gained a **launch heading**, which is authoring context:

* offered as the **eight compass points** — `Right (0)`, `Down-Right (8)`,
  `Down (16)`, `Down-Left (24)`, `Left (32)`, `Up-Left (40)`, `Up (48)`,
  `Up-Right (56)` — every one an *exact* heading, since 64 divides by eight;
* shown only for a **movement program**, because a trigger and a wave already
  carry a real launch heading and offering to override those would blur the
  ownership the control exists to clarify;
* defaulting to `from wave`, so it never misrepresents a wave's actual heading.

The header now reads in human terms:

```
movement program 'sd_demo' — semantic, preview heading: Down (16)   from (160, 40)
```

**It never touches the asset.** Changing it recompiles the *segments* against
the new heading and flies the result without storing it — `simulate_wave` and
`preview_program` gained an explicit-stages parameter for exactly this, because
a program's stored records are compiled against the launch heading of the waves
that use it and a straight leg's velocity is baked in. Asserted by test:
segments, compiled records, document JSON, dirty flag and undo depth are all
unchanged by any amount of preview-heading use.

### The proof asked for

`STRAIGHT 30f → TURN RIGHT 90° → STRAIGHT 30f → EXIT`, one asset, two launches:

| launched | compiled straights | flies |
|---|---|---|
| **Right** | `(6,0)` then `(0,6)` | right, quarter turn, then down |
| **Down** | `(0,6)` then `(-6,0)` | down, quarter turn, then left |

Every heading in the second path is the first **rotated by exactly 16 steps**,
with identical stage timing — and **no kink at either boundary** in either.
Continuous from all eight compass points, same shape from each. The `STRAIGHT`
segments still serialise as `{"kind": "STRAIGHT", "frames": 30}`: no direction
was added to them.

### Compass terminology on wave definitions

The wave's `heading` field keeps its exact 0–63 value and gains a compass
picker beside it plus a live readout. Off-point headings are **not** rounded —
the authored content really does use 10 and 12, and those read as
`launch heading 12 — between Down-Right and Down` with the exact number still
editable. Choosing a compass point types its exact heading in, as one undoable
edit (a wave's heading *is* project data, unlike the preview's).

### Layout

The Movement Programs pane got the horizontal room it needed: the window is
1800×840 (min 1240×660), the timeline ruler narrowed 210→170, record and
segment detail columns widened, and the diagnostics wrap at 860px instead of
620. The preview column was requesting **559px** when its canvas needs 430 —
the transport bar's macOS ttk buttons were the widest thing in the panel, and
an unbounded `diag` label did not help. Both fixed; the preview now requests
442 and the authoring tabs gained ~90px.

---

## 7. A real defect found by the manual proof

**Editing a wave could leave a program's records stale.** A semantic program's
records are compiled against the launch heading of the waves that use it, so
pointing a new wave at a program — or changing an existing wave's heading —
invalidates them. Without a resync the editor showed a straight leg going one
way and the engine would have flown it another.

Found in manual proof D, where a mirror that should have reflected exactly gave
offsets of 0..45 instead of {0, −1}. Fixed with
`EditorController.resync_semantic_programs()`, called from **every** wave-definition
mutator (add, update, rename, delete, duplicate). It recompiles only semantic
programs, only when the records actually differ — so it cannot manufacture a
spurious edit — and **never touches a raw program**. Regression-tested, and D
now gives `{-1, 0}` with Y preserved exactly.

---

## 8. GUI

The Movement programs tab gained a **semantic view**, with the raw record editor
retained beside it.

```
sweep — semantic, launched on heading 0        [Mirror movement] [Edit raw records]
3 semantic segments → 3 engine records / 12 bytes    project pool 13/64 records, 52/256 bytes

 #  segment            what it does
 1  STRAIGHT 34f       fly on, on heading 0, for 34 frames
 2  TURN RIGHT 90°     from heading 0, turn right 90° to heading 16
 3  EXIT               leave the world on heading 16

[Add] [Insert before] [Insert after] [Duplicate] [Delete] [▲ Earlier] [▼ Later]
manoeuvre [S-curve left ▾] [Insert]  — expands into segments, so its cost is visible immediately
```

* **Selecting a segment shows only its own parameters.** A turn shows direction,
  angle and radius; a straight shows a duration; a hold shows frames and drift.
  **No entry-heading control exists in the semantic view** — asserted by test.
* The **inherited heading is shown as a readout** in every row. That is the
  thing the author no longer has to work out, so seeing it confirms the
  continuity rather than asking them to supply it.
* **Advanced/Raw** remains one button away for any semantic program and is the
  only view for a raw one. Switching is a *view*, not an edit, and cannot dirty
  the document.
* Live preview is the Phase 6A faithful simulator over the compiled records —
  **one compiler, one simulator, no second opinion**, and it follows unsaved
  segment edits immediately.

### Two Tk defects fixed along the way

1. **An infinite geometry loop.** `sem_view` and `raw_view` were gridded into
   one cell and swapped with `tkraise()`, so the cell had to satisfy both
   requested widths at once; with a weighted column either side the layout
   oscillated and `update()` never returned. Isolated by variant testing, fixed
   by mapping exactly one view (`grid_remove`).
2. **An event storm.** Entries apply on `<FocusOut>`; refreshing repopulates
   them, which moves focus, which fires `<FocusOut>` again. Fixed by making an
   apply that changes nothing do nothing — which is also simply correct.

Long status labels were given `wraplength`, following the 6A.1 hotfix that
established the pattern.

---

## 9. Cost visibility and overflow

The mode strip always shows both numbers:

```
9 semantic segments → 9 engine records / 36 bytes    project pool 19/64 records, 76/256 bytes
```

Macro expansion is therefore never hidden. **Overflow is caught by the existing
rule set, not a second one**: semantic programs compile into `stages`, which
`validation_v6` already counts, so a program that overruns the pool raises
`movement.too_many_records` / `movement.pool_overflow` and Export is blocked.
Pool limits are unchanged at **64 records / 256 bytes**.

---

## 10. Manual GUI proof (§13)

Run against a **disposable copy**, never the canonical project.

**A — build the brief's sentence with no raw editing.** Authored
`STRAIGHT 30f → TURN RIGHT 90° → STRAIGHT 30f → EXIT` entirely from the
semantic controls. Compiled:

```
{'kind':'STRAIGHT','frames':30,'vx':6,'vy':0}
{'kind':'ARC','steps':16,'framesPerStep':4,'entryHeading':'CONT'}
{'kind':'STRAIGHT','frames':30,'vx':0,'vy':6}      <- the turned heading's velocity
{'kind':'EXIT'}
```

Flown as a 3-member wave from the left: 190 frames, all exited, becomes visible,
validator clean. **No heading index was typed and no record was edited.**

**B — the same movement from a different launch heading.** Segments unchanged;
the compiled straight follows the new heading; every heading in the flight
rotated by exactly 48.

**C — a semantic S-curve.** `STRAIGHT 30f → TURN LEFT 90° → TURN RIGHT 90° → EXIT`,
4 records / 16 bytes; flown, **exactly one curvature reversal**.

**D — mirror.** Turns flipped; launched on the mirrored heading the x-reflection
offsets are **{−1, 0}** and **Y is preserved exactly**; the wave's launch
heading was **not** rewritten.

**E — save, close, reopen.** Both programs return as the same sentences, the
preview works, the mode strip reads correctly.

**F — cost.**

```
sweep        raw        -  segments ->  3 records /  12 bytes
s            raw        -  segments ->  3 records /  12 bytes
linger       raw        -  segments ->  4 records /  16 bytes
loop         raw        -  segments ->  3 records /  12 bytes
sweep_right  semantic   4  segments ->  4 records /  16 bytes
scurve       semantic   4  segments ->  4 records /  16 bytes
project pool: 21/64 records, 84/256 bytes       validator: clean
```

---

## 11. Tests

| Suite | Result |
|---|---|
| **`test_movement_semantic.py`** | **All 150 checks passed** |
| **`test_semantic_gui.py`** (real Tk) | **All 58 checks passed** |
| `test_encounters_gui.py` (5B) | All 59 passed |
| `test_preview_gui.py` (6A) | All 61 passed |
| `test_editor_workshop_gui.py` / `test_editor_asset_workflow_gui.py` | 9 / 6 passed |
| 28 other headless editor files | all pass |

Phase 6B adds **208 checks**. The trajectory claims — continuity, relative
turns from any launch heading, the mirror, lift equivalence — are all settled by
flying both versions through the Phase 6A simulator, which is itself proved
frame-for-frame against a real 6502.

### Pre-existing failures, isolated by experiment rather than argued

Four editor files fail. **Each was re-run with my three modified files stashed,
and each failed identically at HEAD**, so all are consequences of the user's
content edits (noSpawnRow 340 → 725, new trigger rows), not of Phase 6B:

| File | Failure | At HEAD |
|---|---|---|
| `test_v6_export.py` | `noSpawnRow: got 725, want 340` | **identical** |
| `test_v6_phase4_roundtrip.py` | trigger-ordering error fires first | **identical** |
| `test_v6_phase5a_gui.py` | 2 checks (noSpawnRow, export gating) | **identical** |
| `test_v6_phase6a1_hotfixes.py` | hangs | **hangs at HEAD too** |

These are tests with the **old** content's expectations hard-coded. Updating
them is content-maintenance and was deliberately not smuggled into this phase;
it is listed as follow-up work in §14.

### Engine regressions

`src/` and `Makefile` are untouched. The engine tests were run and show
content-driven failures of the same kind — trigger rows, concurrent wave counts,
the no-spawn threshold, and `make proof420`'s turret assertion — all naming
facts about the authored level rather than about movement. **The built binaries
are a pure function of unchanged engine source and the user's own
`src/level1/*.asm`**, which verify byte-identical to the baseline.

```
ddc186955a152d0c0e5520ee63e8491c35ad63ca919bcad27710b02c794a382e  build/shmup.prg
f8f194ce5be00a07d163e8996d9466e8946fa5a23b578aeed562620f7e770c25  build/level1.prg
```

They differ from the Phase 6A report's hashes because the level content differs
— that is the user's authoring, correctly compiled.

---

## 12. Canonical Level 1 preservation (§14)

```
canonical sha256      6eb85882c76664acb02592986fce43702fd847ef4c08c837acc57a99dd7461c1
JSON byte-identical   True
programs all raw      True
ASM byte-identical    7/7
movement bytes        unchanged
```

All eight authored files verify against the baseline taken before any work
began. **No-op open, save and export change nothing**, and the movement bytes in
particular are untouched — guaranteed structurally, because the canonical
programs have no `segments` and a program without segments is never recompiled.

---

## 13. Files changed

```
 M tools/level_editor/project_v6.py     +41   optional `segments`, documented as the asset
 M tools/level_editor/controller_v6.py  +293  semantic operations, lifting, mirror, resync
 M tools/level_editor/encounters_ui.py  +517  the semantic view; raw view retained
?? tools/level_editor/movement_semantic.py    the model, compiler, macros, mirror, lifter
?? tools/level_editor/test_movement_semantic.py   114 checks
?? tools/level_editor/test_semantic_gui.py        43 checks, real Tk
```

`src/level1/*.asm` and `levels/level1/level.v6.json` appear in `git status`
because **the user** modified them before this phase; they are byte-identical to
the baseline and were not touched here.

**No engine source change. No new runtime opcode. Nothing committed or pushed.**

---

## 14. The encounter library — where this lands, and the clean next step

The mid-phase clarification asked that movement programs and wave definitions
become project-level reusable assets rather than stage-owned ones, without
blowing up this phase. Phase 6B does not move them, but it is built so that
moving them changes nothing here:

* **`movement_semantic.py` does not know what a stage is.** Compilation is a
  pure function of `(segments, launch_heading)`; `resolve_for_headings()` takes
  a bare list of headings; only a thin convenience wrapper mentions a project.
* **The segments are the asset; the records are a cache.** `MovementProgram`'s
  docstring says so: `stages` is the compilation against *one* launch heading,
  a per-use resolution rather than a property of the program.
* **Heading-freeness is surfaced**, because it is exactly the property that
  decides whether one program can serve many waves.

### The clean next step

1. Move `movementPrograms` and `waveDefinitions` into a repository-scoped
   encounter library file (travelling with the repo, not machine-global), leaving
   stages holding terrain, turrets and trigger *references*.
2. Give the exporter a resolve-and-pack step: walk the stage's triggers, collect
   only the wave definitions and movement programs actually reached, compile each
   program against the launch heading of the wave that reaches it, and assign
   compact runtime indices. A large library then costs the C64 nothing.
3. That step is where a heading-dependent program used from two headings stops
   being a warning and becomes two compiled entries — the packer can simply emit
   both, because compilation is already per-(program, heading).

The runtime package format needs no change for any of this; it stays stage-local.

---

## 15. Unresolved / deferred

* **Four editor test files carry the old content's expectations** and fail
  (one hangs) independently of this phase — content-maintenance, listed above.
* `make proof420` fails on a turret assertion in `tools/gen_proof420.py` against
  the new 5-turret content — same class, and engine-test scope.
* **Templates not shipped**: Dive, Pull Out, Sweep, Hover→Exit. The macro
  mechanism is in place and each is a few lines; they were left out rather than
  guessed at.
* Zigzag amplitude is expressed as swing angle × radius rather than a pixel
  width; a pixel-accurate amplitude would need the compiler to integrate the
  arc, which is possible but was not required.
* Phase 7 drag-and-drop encounter editing was **not** started.

---

## 16. Hygiene

* **Nothing committed, nothing pushed.** Working tree left for review.
* Destructive experiments ran on disposable copies in scratch; the canonical
  project was never the target.
* No VICE was needed for this phase; none was launched beyond the regression
  run, and none is running. **No editor processes remain** (one stray probe
  process from the geometry investigation was found and reaped).
* `__pycache__` and the disposable `build/proof420` tree removed.

```
build/  300K    tools/level_editor/  2.5M    tests/  548K    repo  12M
```

---

## 17. Acceptance

All twenty criteria met, with the two that carry the rest stated plainly:

> **3. ordinary authors need no ARC heading arithmetic** — every compiled turn
> emits `WM_HEAD_CONT`, the compiler tracks the heading through the program, and
> no entry-heading control exists in the semantic view.
>
> **14/15. canonical Level 1 is preserved** — all eight authored files verify
> against the pre-work baseline; no-op open/save/export changes nothing,
> movement bytes included.

**17. no speculative opcode added** — the existing VM expresses the whole Phase
6B vocabulary, so no movement-engine change was made.
