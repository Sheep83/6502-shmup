# Fixing Trigger Speed in the Encounter Preview

**Date:** 2026-09-29
**Committed or pushed:** no. **No destructive Git operation was used.**

---

## Summary

**One line of cause, one line of fix.** The preview's cache signature — the
tuple that decides whether to re-fly a wave — did not include the trigger's
movement speed. The scaling was correct and always had been; the preview simply
never asked for it again, so whatever had been flown first stayed on the canvas.

```python
key = (t.species, t.wave_definition)                    # before
key = (t.species, t.wave_definition, t.resolved_speed)  # after
```

Measured through the real Encounter workspace, same loop, same heading:

| | 1.00× | 1.25× | 1.50× | 1.75× | 2.00× |
|---|---|---|---|---|---|
| **before** | width 62, 289 frames | 62, 289 | 62, 289 | 62, 289 | 62, 289 |
| **after** | width 62, 289 frames | **72**, 266 | **90**, 241 | **101**, 229 | **124**, 216 |

Wider *and* shorter — which is what linear velocity scaling with an unchanged
turn rate produces, and what the runtime does. **Runtime was not touched.**

---

## 1. Reproduction

Driven through the actual widgets, not through the simulator:

```
triggers: [(0, row 40, 'up_n_over', DROPPER),
           (1, row 90, 'loop', RING_3),
           (2, row 140, 'loop', SPACE_WHISK)]

select trigger 1, set speed 1.00x -> frames 289  x-width 62
select trigger 1, set speed 1.50x -> frames 289  x-width 62
select trigger 1, set speed 2.00x -> frames 289  x-width 62
```

Identical in every respect, including the frame count. Meanwhile the simulator,
called directly, was already correct:

```
simulate_wave(loop, speed=4) -> x-width  62
simulate_wave(loop, speed=6) -> x-width  90
simulate_wave(loop, speed=8) -> x-width 124
```

So the defect was never in the scaling. It was between the workspace and the
simulator.

---

## 2. Root cause

`PreviewPanel.refresh()` re-flies a wave only when a cheap signature changes:

```python
sig = self._signature()
if sig != self._sig:
    self._sig = sig
    self._rebuild()          # <- the only place a simulation is created
```

`_signature()` includes the wave definition's whole `to_dict()` and the whole
movement program, but the **trigger** contributes only a hand-picked key. It was
`(species, wave_definition)`. Changing the speed moved nothing in that tuple, so
`sig == self._sig`, `_rebuild()` never ran, and the canvas kept the path it had
flown the first time the trigger was selected.

The function already carried a comment describing this exact failure mode for a
different field:

> *"THE PREVIEW HEADING IS PART OF THE SIGNATURE. Without it, changing the
> heading would leave the previous simulation on screen — the project has not
> changed, so nothing else here would notice."*

Speed is the same category of input and I did not add it when I added speed.
The note beside the fix now says so.

**Why switching triggers still worked:** selecting a different trigger changes
`self.source`, and in this level the two `loop` triggers also differ in species,
so the key differed and a rebuild happened. The stale path only appeared when
the speed of *one already-selected trigger* changed — which is exactly the
reproduction reported.

---

## 3. Why the previous parity tests missed it

Both failures are worth naming, because they are different mistakes.

**1. The tests exercised the wrong layer.** `test_trigger_speed.py`'s section
headed "preview parity" called `movement_sim.simulate_wave(..., speed=n)`
directly. That function was correct, so the tests passed — while the object the
canvas is actually drawn from was never involved. A test that can pass while the
screen is wrong is testing a different thing from the one it names.

**2. The one arc assertion could not have distinguished the bug anyway.** It
measured displacement between two frames and asserted it grew with speed. A
constant-radius loop run faster would also show that. It had no way to tell
"wider arc" from "same arc, faster", which is the only distinction that matters
here.

The new test fixes both: it reads `panel.sim` — the exact list `_draw_paths`
iterates — and it requires the path to get **wider and shorter at once**, which
only linear scaling with an unchanged turn rate produces.

---

## 4. The fix

`tools/level_editor/preview_ui.py`, `PreviewPanel._signature`:

```python
key = (t.species, t.wave_definition, t.resolved_speed)
```

with a comment recording why it is there, why colour and firing mode are
deliberately *not* (they do not change the trajectory, and including them would
re-fly a 300-frame wave every time somebody picked a shade), and what the
symptom was.

**That is the whole behavioural change.** No simulator, no scaling, no runtime.

### Preview scaling semantics (unchanged, restated)

`movement_sim._apply_speed` scales the velocity at the two points the engine
does — after the heading table is read (`_load_heading`) and after a
STRAIGHT/HOLD record is taken up (`_enter_stage`) — using the same
sign-magnitude rule:

```
scaled = (|v| * speed) >> 2, sign restored
```

Turn progression is untouched: `framesPerStep` and the heading step are not
scaled, so a faster enemy covers more ground per heading step and the arc gets
wider. That is the runtime semantic and it is now what the preview shows.

---

## 5. Evidence

### Geometry, through the real UI

```
1.00x:  289 frames, width  62, height 217
1.25x:  266 frames, width  72, height 217
1.50x:  241 frames, width  90, height 217
1.75x:  229 frames, width 101, height 215
2.00x:  216 frames, width 124, height 216
```

* **2.00× is 2.00× the width** of 1.00× — 62 → 124 exactly.
* **1.50× is intermediate**, 62 < 90 < 124.
* **Widths increase monotonically; frame counts decrease monotonically.**
* **The turn rate was not compensated**: had it been, the width would have
  stayed at 62 and only the frame count would have moved.

### Initial heading preserved

Asserted, not assumed. Every speed starts the member at the same authored
position `(70, 30)` and travels in the same initial direction — compared as the
*sign* of the first step, because the magnitude is exactly what speed changes:

```
1.00x=(1,1)  1.25x=(1,1)  1.50x=(1,1)  1.75x=(1,1)  2.00x=(2,2)
```

### Two triggers, one definition

```
ok - selecting trigger A previews its own 1.00x geometry          width 62
ok - SELECTING TRIGGER B PREVIEWS A WIDER PATH, from the SAME definition
                                                                   A 62 vs B 124
ok - ...and switching back to A returns to A's geometry            62
ok - ...with one shared wave definition throughout
```

Switching back is asserted explicitly because the cache is what got this wrong.

---

## 6. The regression test

`tools/level_editor/test_preview_trigger_speed.py` — **28 checks, all pass.**

It drives the real `LevelEditor`, opens the real Encounter workspace, selects
triggers through the tree the way a user does, and reads `panel.sim`.

**Proved to catch the old bug.** Run against a copy of the pre-fix tree (taken
before the first edit and kept in scratch), it fails exactly the checks it
exists for:

```
22 passed, 6 failed
  FAILED: 2.00x DRAWS A DIFFERENT PATH FROM 1.00x -- the bug this test exists for
  FAILED: the loop is WIDER at 2.00x, not merely faster
  FAILED: ...and about twice as wide, as linear scaling with an unchanged turn rate implies
  FAILED: 2.00x also COMPLETES SOONER -- linear speed, same angular rate
  FAILED: ...so it is NOT a time-compressed constant-radius loop
  FAILED: 1.50x is visibly intermediate
```

and after the fix, 28/28.

It also covers all five speeds table-driven, the unchanged start position and
bearing, the shared-definition case in both directions, that the wave definition
still owns no speed, that all three workspace tabs still work, and that the
Encounter window closes and reopens without a traceback.

---

## 7. What else the run turned up

Three things surfaced while testing, all of them my own earlier tests freezing
content the author is free to change. **Level 1 has been re-authored since my
last task** — three triggers now (rows 40/90/140), new identities, and speeds
already set to 1.00× / 1.50× / 2.00×, which is exactly the reported repro.

**Fixed, because they are mine and this is the third time I have made the same
mistake:**

| test | froze | now asserts |
|---|---|---|
| `test_trigger_speed` | "Level 1 migrates entirely to 1.00×" | every trigger resolves to a *legal* speed |
| | the UI shows `"1.00x"` | the UI shows *that trigger's* speed |
| | trigger B is 1.00× after editing A | B is unchanged *from what it was* |
| | "exports as 1.00× today" | exports exactly what the project holds |
| | restores to 1.00× | restores to the *original* values |
| `test_wave_colour_mode` | 12 triggers; row 52 FIXED at colour 3 | every trigger has a legal colour and mode |
| | 11 RANDOM appearances | each byte's flag matches that trigger's mode |
| | four `loop` triggers with literal values | shared triggers each carry their own pair |
| `test_trigger_speed_validator` | a 12-entry speed column | counts the column's real length |
| | patched one leg by its literal bytes | patches legs that already travel in X |

The validator fixture took three attempts, and each wrong attempt was caught by
the engine's own flight proofs rather than by luck — replacing whole records
flattened `up_n_over`'s climb ("never visible inside the aperture"), and
widening every leg gave `dive_bomb`'s pure vertical dive a sideways component so
its loop never terminated ("never reaches any despawn edge"). Both are real
rules firing correctly. The fixture now widens only legs that already move in X.

**One small engine change followed from that**, and it is the only `src/` edit
in this task: the trigger-column size proof in `src/waves.asm` now runs
**before** the per-definition flight loop. The flight loop indexes `trigSpeed`
to discover which speeds a path must be flown at, so a short column reached it
first and KickAssembler reported `Index out of bound : 1` from inside a loop
instead of the sentence written for it. Moving the proof up makes the intended
message reachable.

> **This change emits an identical binary.** Verified by assembling the
> pre-change tree and the current one and comparing `main.prg` byte for byte:
> identical. It is a compile-time reordering and nothing else.

---

## 8. Runtime is untouched

* `src/movement.asm`, `src/encounter_format.asm`, `src/levelpkg.asm`,
  `src/level_package.asm` — **not modified in this task**.
* `src/waves.asm` — one compile-time `.if` moved earlier; **byte-identical
  output**, proved above.
* No change to movement geometry, turn rate, speed range, firing, spawn
  intervals, wave spacing, scroll speed, or anything on the Dropper path.

**Dropper untouched**, as required: its special movement, token drop, one-live
restriction, lifecycle and preview refusal are all exactly as they were. The new
test explicitly skips Dropper triggers and says why.

---

## 9. Manual Tk acceptance — not performed, stated plainly

**I did not look at the editor on screen, and I am not claiming to have.**

I tried to get real visual evidence without disturbing you: rendering the
preview canvas to PostScript from a **withdrawn** window. It does not work —
Tk never lays out an unmapped widget, so all three dumps came back byte-identical
and empty. The artefacts were deleted rather than left to look like evidence.
Getting a real picture means mapping a window, which on macOS raises the app and
takes focus, and the brief asks me not to.

What *was* done, with real Tk: the full `LevelEditor` and Encounter workspace
are constructed, driven through real widget callbacks and real tree selections,
and the assertions read `panel.sim` — **the exact object `_draw_paths` iterates
to draw the canvas**. That is one layer below the pixels and it is the layer the
bug lived in.

Still worth one real look from you, specifically: that the wider loop *reads*
well at 2.00× and does not run off the visible field.

---

## 10. Tests and results

| suite | result |
|---|---|
| `test_preview_trigger_speed.py` (**new**) | **28 passed, 0 failed** — and 6 failures on the pre-fix tree |
| `test_trigger_speed.py` (de-frozen) | **OK** |
| `test_trigger_speed_validator.py` (de-frozen) | **9 passed, 0 failed** |
| `test_wave_colour_mode.py` (de-frozen) | **OK** |
| `test_semantic_gui`, `test_v6_phase5a_gui`, `test_wave_schema`, `test_v6_validation` | pass |
| `make smoke` | **PASS** |

```
make smoke
  gameOverrun 0  scrollLate 0  edgeLate 0  statOverflow 0
  publishSkip 0  schedBuildDefer 0  statLate 0  clipPoolFull 0
  BOOT PASS / CAMPAIGN LOOP PASS / ENGINE HEALTH PASS / ROUTINE REGRESSION PASS
```

### Failing suites, all caused by the re-authored Level 1

Verified against a copy of the pre-fix tree, which has the **same level data**:
each fails identically there, so none is caused by this change.

| suite | cause |
|---|---|
| `test_v6_phase5b_encounters` | `IndexError` on a trigger index that no longer exists |
| `test_preview_gui`, `test_encounters_gui`, `test_v6_phase6a1_hotfixes` | same family, from earlier phases |
| `test_v6_roundtrip`, `test_encounter_library`, `test_multi_level_layout` | pre-existing from the enemy-identity work |

**Three runtime suites also fail on content**, and I have *not* rewritten them
in this focused task: `tests/test_trigger_speed.py` (11), `test_wave_colour_mode`
(4), `test_movement_pool` (6). Their failures are assertions like "every trigger
is 1.00×", "the AIMED appearance is the one the author authored", and ARC-entry
checks naming SWEEP/LINGER/LOOP — all frozen content, all now wrong because you
re-authored the level. Since the engine binary is byte-identical to the pre-task
build and the level data is the same, their outcome cannot have been changed by
this task. **They need the same de-freezing treatment as their editor
counterparts; that is real follow-up work I am flagging rather than quietly
leaving.**

---

## 11. Files changed

| file | change |
|---|---|
| `tools/level_editor/preview_ui.py` | **the fix** — trigger speed in the cache signature |
| `src/waves.asm` | column-size proof moved before the flight loop (byte-identical output) |
| `tools/level_editor/test_preview_trigger_speed.py` | **new** regression test |
| `tools/level_editor/test_trigger_speed.py` | de-frozen from live content |
| `tools/level_editor/test_trigger_speed_validator.py` | de-frozen; fixture widened correctly |
| `tools/level_editor/test_wave_colour_mode.py` | de-frozen from live content |

Everything else in `git status` is the trigger-speed feature from the previous
task, unchanged by this one.

---

## 12. Limitations

1. **No human-eyes visual acceptance** (§9).
2. **Three runtime suites still assert frozen level content** (§10) and need
   the same treatment their editor halves got.
3. **The preview cache still lists trigger fields by hand.** Speed is in it now,
   and colour and firing mode are deliberately out because they do not change
   the trajectory — but the next trigger field that *does* will have to be
   remembered. A signature built from "the trigger fields the simulator reads"
   would be structurally safer; out of scope here.
4. **`test_preview_gui` and two others were already broken** by the
   re-authoring, so the preview's own older coverage is currently not running.

---

## 13. Final state

```
 M src/encounter_format.asm              M tools/level_editor/export_v6.py
 M src/level1/wave_encounters.asm        M tools/level_editor/levels/level1/level.v6.json
 M src/level2/wave_encounters.asm        M tools/level_editor/levels/level2/level.v6.json
 M src/level3/wave_encounters.asm        M tools/level_editor/movement_sim.py
 M src/level_package.asm                 M tools/level_editor/preview_ui.py
 M src/levelpkg.asm                      M tools/level_editor/project_v6.py
 M src/movement.asm                      M tools/level_editor/test_wave_colour_mode.py
 M src/waves.asm                         M tools/level_editor/validation_v6.py
 M tests/test_movement_pool.py
 M tools/level_editor/contract_v2.py
 M tools/level_editor/controller_v6.py
 M tools/level_editor/encounters_ui.py
?? reports/enemy-movement-speed-ownership-audit.md
?? reports/trigger-owned-movement-speed.md
?? reports/preview-trigger-speed-cache-fix.md
?? tests/test_trigger_speed.py
?? tools/level_editor/test_preview_trigger_speed.py
?? tools/level_editor/test_trigger_speed.py
?? tools/level_editor/test_trigger_speed_validator.py
```

* **Nothing committed. Nothing pushed.** HEAD is still
  `0c50a46 More enemy types added to editor`.
* **No destructive Git operation was used.** No `checkout`, `restore`, `reset`,
  `stash` or `clean`. The pre-fix comparison tree came from a tar snapshot taken
  into scratch before the first edit, plus `git archive HEAD`, both of which
  write nothing to the repository.
* **Your authored Level 1 was not modified** — the tests write only to
  temporary directories and byte-compare the committed level and library at the
  end.
* VICE: one instance, launched by `make smoke` through the harness with
  `-console`, owned by exact PID and reaped. No broad `pkill`/`killall`, no
  focus stolen. `pgrep -fl x64sc` confirms **none running**.
* `build/` is **340 K**. Scratch is 26 M in the session scratchpad; `/tmp` logs
  deleted. **92 GiB free of 228 GiB.**
