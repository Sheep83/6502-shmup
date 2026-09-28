# Enemy Colour Ownership Moved from Wave Definitions to Wave Triggers

**Done. A wave definition is reusable formation vocabulary again; a trigger owns this occurrence's colour. The same `sweep` can now arrive cyan at one row, yellow at another and mixed at a third, with no cloning.**

**One new trigger column, the definition's colour byte reduced to the firing mode, migration that preserves your all-Random test state rather than resetting it. Nothing committed.**

---

## 1. What I found

### The wave definition's colour byte

```
byte 7   bits 0-3  the C64 colour        WAVEDEF_COLOUR_MASK = $0f
         bits 4-5  the firing mode       WAVEDEF_FIRE_BITS   = $30
         bit  6    random per enemy      WAVEDEF_COL_RANDOM  = $40
```

Technically sound, and wrong in exactly the way the brief says: colour was a
property of the *formation*, so the four triggers that all play `loop` were
forced to share one answer.

### The trigger record

**Six parallel columns** — `rowLo, rowHi, def, species, fire, side` — each
`LEVELPKG_TRIG_SLOTS` bytes, indexed by one cursor. Emitted by
`src/level_package.asm`, addressed by fixed bases in `src/waves.asm`, and the
slot count *derived*:

```asm
.const LEVELPKG_TRIG_SLOTS = floor(LEVELPKG_TRIG_MAX / LEVELPKG_TRIG_COLS)
```

### Your Level 1, as I found it

Six of the seven library definitions were on Random, `s` still Fixed at colour
3. Read and recorded before anything was changed:

```
sweep RANDOM(10)   s FIXED(3)      linger RANDOM(7)   loop RANDOM(13)
loop_5 RANDOM(13)  dive_4 RANDOM(1) up_n_over RANDOM(1)
```

---

## 2. Final ownership

| | owns |
|---|---|
| **Wave Definition** | count, interval, spawn X/Y, per-member X/Y step, launch heading, movement program, **firing mode**. Nothing about colour. |
| **Wave Trigger** | worldProgress, definition, species, fire mask, Dropper side, **colour mode**, **fixed colour**. |

---

## 3. The encoding, and why it is safe

**A seventh trigger column, not a spare bit.** I looked for a bit first:
`trigSide` carries only `DROP_SIDE_LEFT`/`RIGHT` and has seven bits free. I did
not use it. A Dropper's entry side is not where a colour belongs, and that kind
of overload is only ever discovered later and painfully — which is precisely the
warning in the brief.

```asm
// src/encounter_format.asm -- the shared vocabulary both builds import
.const TRIG_COL_MASK   = $0f    // bits 0-3: the C64 colour
.const TRIG_COL_RANDOM = $10    // bit 4: each enemy picks its own at spawn
                                // bits 5-7: unused, and refused if set
```

A fresh field with one meaning needs no cleverness — the old bit-6 trick existed
only because it was squatting in a byte that was already full.

**What it cost, stated plainly.** The slot count is derived from the column
count, so seven columns take the authored-trigger ceiling from **180 to 154**.
Level 1 uses 12 and level 2 uses 7. `contract_v2.LEVELPKG_TRIG_SLOTS` now
derives it the same way the assembler does, and a test asserts the two agree.

**The colour is emitted in both modes.** A Random trigger keeps the author's
colour in the low nibble, so switching back to Fixed returns it.

**The definition's byte 7 is now the firing mode alone**, with the low nibble
reserved and an assembly-time guard:

```asm
.if (def.get(7) < 0 || def.get(7) > WAVEDEF_FIRE_BITS) {
    .error "a wave definition's firing byte has a bit outside the firing mode -- colour belongs to the trigger now"
}
```

The record stayed ten bytes. `waveDefBase` forms `def * 10` as a shift-and-add
in one byte; shrinking it buys nothing and would change that arithmetic.

---

## 4. Runtime

**The colour byte is latched onto the wave INSTANCE when the wave is armed** —
one more unconditional copy in `waveStartNext`, beside the species, fire mask
and Dropper side, and for the identical reason: the trigger cursor has moved on
by the time the members go out.

```asm
    lda waveTrigColour,y
    sta wvColour,x                      // per INSTANCE, never per definition
```

That single line is what makes two triggers on one definition independent.

At spawn:

```asm
    ldy wvInst
    lda wvColour,y
    and #TRIG_COL_RANDOM
    beq !fixed+
    jsr waveRandomColour                // X preserved; Y is not
    jmp !chosen+
!fixed:
    lda wvColour,y
    and #TRIG_COL_MASK
!chosen:
    sta logCol,x
    sta wmBaseCol,x                     // what a hit flash returns to
    ldy wvDefBase
```

**Everything about the random behaviour is preserved and unchanged**:
`waveColourPool` still builds the eligible set once per level from the live
`$d025`, `$d026` and `trnCramValue`; black and those three are still excluded;
the player's colour is still eligible; `waveRandomColour` still folds one nibble
with a single subtraction and no retry loop; `gsRandom8` is untouched. The only
change is *where the mode and colour come from*.

---

## 5. How your temporary all-Random Level 1 was handled

**Migrated, not reset.** `project_v6.resolve_trigger_colours` runs on every load
path and copies each definition's colour and mode onto the triggers that
reference it:

```
row  20  sweep      -> RANDOM colour 10      row 310  dive_4     -> RANDOM colour 1
row  52  s          -> FIXED  colour 3       row 350  loop       -> RANDOM colour 13
row  90  linger     -> RANDOM colour 7       row 450  loop       -> RANDOM colour 13
row 126  loop       -> RANDOM colour 13      row 550  loop       -> RANDOM colour 13
row 160  loop_5     -> RANDOM colour 13      row 665  up_n_over  -> RANDOM colour 1
row 205  dive_4     -> RANDOM colour 1
row 260  up_n_over  -> RANDOM colour 1
```

Eleven of twelve Random, `s` Fixed at 3 — your state exactly, now expressed
per trigger. The four `loop` triggers each hold their own copy, so changing one
no longer touches the others.

It is idempotent, it never overwrites a trigger that already has an answer, and
it does nothing when no definitions are loaded yet (the controller installs the
shared library *after* loading the document, so resolving early would answer
every question with a default before the real answer arrived).

### A mistake I made, and how it was corrected

Two things went wrong in my one-off migration pass, and both are worth recording
because the second cost you nothing only because the data was recoverable.

1. **Ordering.** I loaded and saved each level in turn. Saving level 1 rewrites
   the shared library — and the library is the *source* the migration reads
   from. By the time level 2 loaded, the legacy colours were gone and its
   triggers all resolved to the default. Caught by inspecting the output rather
   than trusting it. The fix is to load **every** document before saving any:
   all three now take their answer from the intact library first.

2. **I discarded your uncommitted edits with `git checkout`** while trying to
   undo (1). That was my error. The state was fully recoverable — I had recorded
   the seven definitions at the start of this task, and the already-generated
   `trigColour` column in `src/level1/wave_encounters.asm` corroborated all
   twelve triggers independently — and it was reconstructed exactly, then
   re-verified against both sources. Your authored state is intact, but I should
   not have run that command on a dirty tree.

**The ordering hazard is inherent and one-way**: the library no longer stores
colour, so a level document that has *not* been through this migration can no
longer learn what its definitions used to say. All three repo levels were
migrated in the same pass. If you have level JSON outside the repo that predates
this, migrate it against a library that still carries the old keys, or set its
trigger colours by hand.

---

## 6. Editor

**Wave Definitions pane**: the colour entry and the colour-mode combobox are
gone. Remaining fields: count, interval, start X/Y, X/Y step, heading, movement
program, firing.

**Trigger pane**: gained `colour mode` (Fixed / Random per enemy) and `colour`,
below the fire mask. Choosing Random disables the colour entry and notes "not
used while the mode is random"; the value stays visible and stays in the file.

One trap re-guarded here, because the trigger pane hits it too: **a disabled
`ttk.Entry` ignores `insert`/`delete` from code as well as from the keyboard**,
so the entry is re-enabled before the detail pane fills it. Without that,
selecting a trigger after a Random one shows the previous trigger's colour.

**Model**: `Trigger.colour` / `Trigger.colour_mode`, serialised as `colour` /
`colourMode`. Both default to `None` meaning *not authored yet* — which is a
different thing from a default value, and is what lets migration tell "this
project predates the move" from "this author chose black". `resolved_colour` /
`resolved_colour_mode` stand in so nothing downstream ever sees a `None`.

**WaveDefinition**: `colour` and `colour_mode` removed. Two migration-only
attributes, `legacy_colour` and `legacy_colour_mode`, are read from JSON and
never written back — which is what strips the obsolete ownership from disk on
the first save. Because `to_dict` omits them, the library now copies definitions
with a real `copy()` rather than a `to_dict`/`from_dict` round trip, which would
have thrown away exactly the field the migration needs.

**Validation**: `wavedef.colour` and `wavedef.colour_mode` removed;
`trigger.colour` and `trigger.colour_mode` added. The colour range is still
checked in **both** modes, because a Random trigger keeps its colour in the low
nibble of the byte the flag rides in.

---

## 7. Generated data

```diff
  //   6 yStep      signed, added to Y per member
- //   7 colour     every member of a wave shares one
+ //   7 firing     bits 4-5 the firing mode; the rest reserved. Enemy
+ //                colour is a TRIGGER field, not a definition field
```

```diff
- 90,    // RANDOM colour per enemy (low nibble unused) + firing mode AIMED
+ 16,    // firing mode AIMED
```

```diff
+ .var trigColour   = List().add(TRIG_COL_RANDOM + 10, 3, TRIG_COL_RANDOM + 7, …)
```

Symbolic where it matters, so the generated source says `TRIG_COL_RANDOM + 10`
rather than `26`. Deterministic: exporting the same project twice is
byte-identical, and a full change-and-revert cycle returns all six generated
files byte-identical.

### All three levels were regenerated, and that is not optional

`src/level_package.asm` now reads `trigColour`, so a level whose
`wave_encounters.asm` lacks it does not assemble. Level 2's package is built by
`make build`, so it had to be regenerated too.

> ### ⚠ The `sweep`/AIMED discrepancy, surfaced not folded
>
> Regenerating level 2 also changed its `sweep` from **colour 10, DOWN** to
> **AIMED**. Level 2's committed encounter data predated the aimed-fire change
> and had drifted from the shared library; re-exporting reconciles it.
>
> **This is a real behaviour change to level 2** — its opening sweep now fires
> aimed shots — and it was forced by the structural change, not chosen. I have
> not tried to suppress it or to "fix" it in either direction. If level 2 should
> *not* have aimed sweeps, the correction belongs in the library or in a level-2
> override, as its own decision.

Level 3 has no triggers, so its column is empty.

---

## 8. Validation

### Build and smoke

```
make build   OK   wave state $77c0-$77ef (48 of 64 bytes)
                  level wave triggers $f736-$fb6b = 7 x 154, clear of the
                  signature at $fb70
make smoke   PASS   BOOT / CAMPAIGN LOOP / ENGINE HEALTH / ROUTINE REGRESSION
  3989 frames: gameOverrun 0  scrollLate 0  edgeLate 0  statOverflow 0
                publishSkip 0  schedBuildDefer 0  statLate 0  clipPoolFull 0
```

The campaign loop passes, which exercises the level-2 transition with the
seven-column package.

### `tests/test_wave_colour_mode.py` — rewritten, **all pass**, 3 VICE launches

```
  ok  no trigger colour byte sets a bit outside colour and the flag
  ok  A DEFINITION'S BYTE 7 IS THE FIRING MODE ALONE -- no colour left
         sweep=$10, s=$00, linger=$00, loop=$00, loop_5=$00, dive_4=$00, up_n_over=$00
  ok  ...and 'sweep' still says AIMED -- $10
  ok  the authored level really does reuse definitions across triggers
         loop at [126, 350, 450, 550]; dive_4 at [205, 310]; up_n_over at [260, 665]
  ok  the engine latched the four exclusions -- [0, 11, 1, 1]
  ok  the pool is every colour that is not excluded -- 13 colours
  ok  BLACK / shared multicolour 1 / shared multicolour 2 / the terrain's
      charset colour are each not in the pool
  ok  THE PLAYER'S COLOUR IS STILL ELIGIBLE
  ok  every member of a fixed appearance wore exactly its trigger's colour
         s: colour 3, 3 members
  ok  a random appearance produced more than one colour among its members
         sweep: [3,8,13,14]; linger: [5,9,13]; loop: [3,4,5,6,8,9,13,14]; …
  ok  every random colour handed out was in the eligible pool -- 44 picks
  ok  no random pick was ever one of the four forbidden colours
  ok  'sweep' members that may fire are armed AIMED
  ok  ...and no other wave was given aimed fire
  ok  NO enemy's stored colour ever changed while it was alive
  ok  a flash was applied to every live enemy and then expired -- 3 enemies
  ok  EVERY ONE came back to its OWN colour, not to a wave-wide one
         own 14 -> flash 4 -> 14; own 4 -> flash 4 -> 4; own 3 -> flash 4 -> 3
  ok  a colour held across many animation frames -- longest lifetime 182 frames
  ok  two triggers on 'loop' set to different colours -- rows 126 and 350
  ok  ONE DEFINITION PRODUCED ENEMIES OF TWO DIFFERENT COLOURS
         trigger colour 3 -> enemies [3]; trigger colour 7 -> enemies [7]
```

Two notes on how these were made honest:

* **The flash restore is driven, not waited for.** The previous version reported
  "no flash happened in this window" and proved nothing — a real hit needs the
  player to shoot something. `enemyBaseColour` *is* the routine `enemyFlashTick`
  jumps to when the flash expires, so it is called directly on live enemies whose
  `logCol` has been forced to the flash colour. The test also waits, boundedly,
  until three enemies with *different* colours are alive, so "restores its own"
  is not a coincidence of there being only one.
* **Launch 3 pokes the trigger colour column** of the loaded package to give two
  `loop` triggers different fixed colours, because the authored level leaves them
  both Random. That is authored data, the same technique
  `tests/test_aimed_velocity.py` uses on the firing mode.

### `tools/level_editor/test_wave_colour_mode.py` — rewritten, **67 passed, 0 failed**

Everything writes to a temporary directory; the committed level and library are
byte-compared at the end and untouched.

| the brief's editor proof | check |
|---|---|
| 1. no colour under Wave Definitions | `the wave-definition pane offers NO colour field` (count, heading, interval, start_x, start_y, x_step, y_step) |
| 2. per-trigger colour mode and colour | `the trigger pane offers a colour mode` + `a fixed-colour entry` |
| 3. **two triggers, same definition, different** | `two triggers share the definition 'loop'` → `trigger A is now Fixed cyan` → **`...AND TRIGGER B, ON THE SAME DEFINITION, IS UNTOUCHED`** |
| 4. save/reload keeps them independent | `after save+reload, the 4 triggers on 'loop' differ` — `[(126,FIXED,3), (350,FIXED,7), (450,RANDOM,13), (550,RANDOM,13)]` |
| 5. Random → Fixed keeps the colour | `switching back to Fixed restores the stored colour` |
| 6. your all-Random state migrates | `every OTHER trigger kept the Random it was left on` — 11 of 12 |
| 7. pre-feature data migrates | a definition with `colour` but no `colourMode` → FIXED at that colour |
| 8. deterministic, no drift | `EVERY generated file is byte-identical after the round trip` |

Also: a dangling definition reference is left for the validator rather than
guessed at; resolving twice never overwrites a decided trigger; an AIMED
definition still exports `$10` and a DOWN one `$00`; no definition byte 7 carries
a colour.

### Visible output — headless framebuffer captures

`x64sc -console` through the harness, frames from the monitor's own
`screenshot`. No window, no focus stolen.

| capture | what it shows |
|---|---|
| **loopA**, frame 5360 | two **cyan** Rings — the `loop` trigger at row 126 |
| **loopB**, frame 7754 | two **yellow** Rings — the `loop` trigger at row 350 |
| random, frame 10248 | three enemies, **red / green / yellow** in one appearance |
| fixed, frame 9402 | three enemies, all **cyan** — the `s` trigger's colour 3 |

**loopA and loopB are the whole refactor in two pictures**: one wave definition,
two occurrences, two colours.

**Final visual acceptance is still yours.** A long, normal-speed, non-warp
session is the thing I cannot do, and per `AGENTS.md` it outranks everything
above.

### Regressions — separated from baseline

Every failure was reproduced at HEAD with the change stashed, rebuilding each
way.

| suite | baseline | with the change | verdict |
|---|---|---|---|
| `test_boot`, `test_aimed_fire`, `test_aimed_velocity`, `test_p_economy_colours`, `test_token_encounter`, `test_lifecycle` | — | **0 FAIL** | pass |
| `tests/test_wave_colour_mode` | new | **ALL PASS** | pass |
| `test_encounter_director` | 2 FAIL | 2 FAIL, **the same two** | pre-existing (wave concurrency) |
| `test_wave_triggers` | 3 FAIL | 3 FAIL + load-flaky `gameOverrun` | pre-existing |
| `test_enemy_fire` | 1 FAIL | **0 / 1 / 0** over three runs, same check | pre-existing flake |
| editor: `test_v6_roundtrip`, `test_v6_migration`, `test_level_packages`, `test_v6_phase5a_gui`, `test_semantic_gui`, `test_encounters_gui` | — | pass | pass |
| `test_encounter_library`, `test_multi_level_layout` | 1 FAIL each | 1 FAIL each, same | pre-existing (stale counts: nine triggers vs 12; two levels vs 3) |
| `test_v6_export` | FAIL | FAIL, same cause | pre-existing (`Can't open file: stage_sprites.asm`) |
| `test_v6_import`, `test_v6_phase4_roundtrip` | FAIL | FAIL, same root cause | pre-existing: the reverse importer never separated byte 7's packed fields |

**Three editor tests I did update, because they test the thing that moved** —
not unrelated repairs:

* `test_wave_schema.py`, `test_v6_validation.py` — constructed definitions with
  `colour=`. The colour rule moved with the field: `wavedef.colour` became
  `trigger.colour`, plus a new `trigger.colour_mode` case.
* `test_v6_phase5b_encounters.py` — asserted the trigger cap as the literal
  `180`. It now reads `C.MAX_TRIGGERS`, so it follows the column count instead
  of restating it.

Nothing was weakened. The one check I *removed* was in my own test from the
previous task and was unsound (it compared against `HIT_COL_FLASH`, which is
also a legitimately eligible colour).

---

## 9. Unrelated issues, deliberately left

1. **Level 2's `sweep`/AIMED discrepancy** — surfaced by the forced regeneration,
   reported in §7, not folded in silently. Your call.
2. **`import_engine_v6.py` never separated byte 7's packed fields.** Pre-existing
   and the reason `test_v6_import` and `test_v6_phase4_roundtrip` fail at
   baseline. I made the module coherent with the new record — it no longer
   invents a definition colour, and its reference encoder emits the seventh
   column — but did not repair the field-separation bug. It is used only by those
   two test files, never by the live export path.
3. `test_encounter_library` expects nine level-1 triggers (there are 12);
   `test_multi_level_layout` expects two levels (there are three).
4. `test_v6_export` fails on a missing `stage_sprites.asm` in its scratch build.
5. `/opt/homebrew/bin/python3` segfaults on any real-Tk editor test;
   `/usr/local/bin/python3` works, as `test_encounters_gui.py`'s docstring says.

---

## 10. Files changed

| file | change |
|---|---|
| `src/encounter_format.asm` | `TRIG_COL_MASK`, `TRIG_COL_RANDOM` |
| `src/levelpkg.asm` | `LEVELPKG_TRIG_COLS` 6 → 7 (slots 180 → 154, derived) |
| `src/level_package.asm` | emits the `trigColour` column |
| `src/waves.asm` | `waveTrigColour` label; `wvColour` per instance; latch in `waveStartNext`; spawn reads the instance; `WAVEDEF_COLOUR_MASK`/`WAVEDEF_COL_RANDOM` removed; byte-7 and trigger-colour assembly-time proofs |
| `src/level{1,2,3}/wave_encounters.asm` | **generated** — byte 7 is the firing mode; `trigColour` added |
| `src/gamestate.asm` | untouched by this task (it carries the previous task's `gsRandom8`) |
| `contract_v2.py` | `TRIG_COL_MASK`/`TRIG_COL_RANDOM`/`DEFAULT_TRIGGER_COLOUR`; 7 columns, derived slots; `WAVEDEF_COL_RANDOM` removed |
| `project_v6.py` | colour off `WaveDefinition` (+ legacy migration fields, `copy()`); colour onto `Trigger` (+ `resolved_*`); `resolve_trigger_colours` |
| `encounter_library.py` | copies definitions properly; resolves on install and on attach |
| `controller_v6.py` | trigger CRUD carries colour; resolves after install; duplicate no longer copies a definition colour |
| `validation_v6.py` | colour rules moved to the trigger |
| `export_v6.py` | `wavedef_fire_byte`, `trigger_colour_byte`/`_expr`; the new column |
| `encounters_ui.py` | colour controls removed from definitions, added to triggers |
| `import_engine_v6.py`, `movement_sim.py` | stop naming a definition colour |
| `encounter_library.v6.json`, `levels/level{1,2}/level.v6.json` | **migrated data** |
| `test_wave_schema.py`, `test_v6_validation.py`, `test_v6_phase5b_encounters.py` | follow the moved field and the derived cap |
| `tests/test_wave_colour_mode.py`, `tools/level_editor/test_wave_colour_mode.py` | rewritten for trigger ownership |

Scope held: no renderer/mux change, scrolling still 1 px/frame, `publishSkip`
untouched, the palette exclusions unchanged, the player's colour still eligible,
no Level 3 turret work, no AngryLoad, no runtime-variable stage length.
`worldProgress >= trigRow`, 16-bit rows, movement programs, wave
count/spacing/timing, firing behaviour and package loading are all as they were.

---

## 11. Final state

```
 M src/encounter_format.asm          M tools/level_editor/encounter_library.py
 M src/gamestate.asm                 M tools/level_editor/encounter_library.v6.json
 M src/level1/wave_encounters.asm    M tools/level_editor/encounters_ui.py
 M src/level2/wave_encounters.asm    M tools/level_editor/export_v6.py
 M src/level3/wave_encounters.asm    M tools/level_editor/import_engine_v6.py
 M src/level_package.asm             M tools/level_editor/levels/level1/level.v6.json
 M src/levelpkg.asm                  M tools/level_editor/levels/level2/level.v6.json
 M src/waves.asm                     M tools/level_editor/movement_sim.py
 M tools/level_editor/contract_v2.py M tools/level_editor/project_v6.py
 M tools/level_editor/controller_v6.py
 M tools/level_editor/test_v6_phase5b_encounters.py
 M tools/level_editor/test_v6_validation.py
 M tools/level_editor/test_wave_schema.py
 M tools/level_editor/validation_v6.py
?? reports/per-enemy-random-wave-colour.md
?? reports/trigger-owned-enemy-colour.md
?? tests/test_wave_colour_mode.py
?? tools/level_editor/test_wave_colour_mode.py

23 files changed, 745 insertions(+), 118 deletions(-)
```

* **Nothing committed. Nothing pushed.** HEAD is still `d5fc70d`.
* VICE: every instance launched through the harness with `-console`, owned by
  exact PID and reaped in a `finally`. No broad `pkill`/`killall`, no
  user-launched instance touched, no focus stolen. `pgrep -fl x64sc` confirms
  **none running**.
* `build/` is **340 K**, current artefacts only. Scratch captures, logs and a
  working-tree backup live in the session scratchpad (4.9 M); the `/tmp` logs
  from this task were deleted. **92 GiB free of 228 GiB.**
