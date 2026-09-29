# Trigger-Owned Enemy Movement Speed

**Date:** 2026-09-29
**Committed or pushed:** no. **No destructive Git operation was used.**

---

## Summary

Physical movement speed is now a **Trigger** property, selectable per occurrence
from **1.00× / 1.25× / 1.50× / 1.75× / 2.00×**, default 1.00×. The same Wave
Definition can be walked at five different paces without being cloned.

Four things are worth knowing before the detail:

1. **1.00× is bit-exact, not approximately unchanged.** The encoding is a
   numerator over four and `(v * 4) >> 2 == v` for every `v`, so a project that
   never touches the field produces identical bytes and identical movement.
   Every authored trigger in Level 1 and Level 2 migrated to 1.00×.

2. **It costs nothing per frame.** Velocity is written in exactly two cold
   places in the whole engine, and the scaling happens there. `wmApplyVelocity`
   — the per-frame integrator — is untouched.

3. **The build-time flight validator now flies every path at every speed a
   trigger actually asks for**, and a new static guard bounds *scaled*
   horizontal velocity. This closes the arc gap the audit found: before today
   nothing bounded an arc's velocity at all.

4. **The stale capacity test is fixed structurally.** `test_movement_pool.py`
   had frozen five different derived values; all of them now come from
   `src/levelpkg.asm` and the generated level.

---

## 1. Schema and representation

### The field

| | |
|---|---|
| project JSON | `"speed"` on each **trigger** |
| model | `Trigger.speed: int = None` (None = not authored), `resolved_speed` |
| values | `4, 5, 6, 7, 8` — a **numerator over four** |
| default | `4` (1.00×) |
| package | `trigSpeed`, the **ninth** trigger column |
| runtime | `wvSpeed[WAVE_SLOTS]` → `wmSpeed[MAX_OBJECTS]` |

```
scaled = (|v| * speed) >> 2,  with the sign of v put back
```

**Why a numerator over four.** The engine already works in quarter pixels per
frame, so the divide is a shift, and 1.00× is the identity for that shift —
which is what makes the default bit-exact rather than merely close.

**Why no slower-than-1× choice.** The 64-entry heading table exists at magnitude
`WM_ARC_SPEED` because that radius is where 64 lattice directions are
distinguishable. Scaling an arc *down* collapses neighbouring headings onto the
same velocity and a smooth curve goes visibly polygonal. A slower formation is
better authored as a wider turn radius, which costs nothing and is already
expressible. Recorded in `src/encounter_format.asm` beside the constants.

**Why sign-magnitude rather than an arithmetic shift.** `+5` must scale to
exactly `-5`'s negation or an `ARC` and its own `ARC_MIRROR` would trace
different curves. `floor(-5 * 6 / 4)` is `-8`; taking the magnitude and putting
the sign back gives `-7`, matching `+7`. Both the 6502 routine and both Python
copies do it this way, and the symmetry is asserted exhaustively.

### Constants

`src/encounter_format.asm` — the file both builds import:

```asm
.const TRIG_SPEED_SHIFT = 2
.const TRIG_SPEED_1X    = 4          // the default
.const TRIG_SPEED_125X  = 5
.const TRIG_SPEED_150X  = 6
.const TRIG_SPEED_175X  = 7
.const TRIG_SPEED_2X    = 8
.const TRIG_SPEED_MIN   = TRIG_SPEED_1X
.const TRIG_SPEED_MAX   = TRIG_SPEED_2X
```

`TRIG_SPEED_1X` is written as `4` rather than `1 << TRIG_SPEED_SHIFT`, with a
build-time guard asserting they agree. The editor's `asm_decl` parser reads
these declarations to keep both halves honest and has no shift operator; a
literal both sides can read beats a derivation only one of them can.

---

## 2. Migration and default

`resolve_trigger_encounter_fields` — the same pass that migrated colour and
firing mode — now fills in speed. Speed is simpler than those two: it never
lived on the definition, so there is nothing to inherit and the answer is
always the default.

```
row  20  sweep      1.00x        row 310  dive_4     1.00x
row  52  s          1.00x        row 350  loop       1.00x
row  90  linger     1.00x        row 450  loop       1.00x
row 126  loop       1.00x        row 550  loop       1.00x
row 160  loop_5     1.00x        row 665  up_n_over  1.00x
row 205  dive_4     1.00x
row 260  up_n_over  1.00x        (level 2: all seven likewise 1.00x)
```

A trigger whose definition does not exist still gets the default — a dangling
reference cannot withhold a value that never came from the definition.

Out-of-range values are refused in three places: the editor validator
(`trigger.speed`), the assembler's per-trigger proof
(`TRIG_SPEED_MIN..TRIG_SPEED_MAX`), and the runtime's own defensive floor.

---

## 3. Runtime

### Where the scaling happens

**Two cold sites, both of which write velocity; nothing else changed.**

| site | when | covers |
|---|---|---|
| `wmLoadHeading` | arc entry, and each heading step | **ARC / ARC_MIRROR** |
| `wmEnterStage` STRAIGHT/HOLD branch | stage entry | **STRAIGHT / HOLD** |

`WM_EXIT` is covered **by doing nothing**: it deliberately does not rewrite the
velocity, so continue-final-direction inherits whatever was last scaled. That is
not an accident of the implementation — it is the existing rule that makes
`ARC → EXIT` continuous, and it gives the scaled case for free.

### The scaler

```asm
wmApplySpeed:
    lda wmSpeed,x
    cmp #TRIG_SPEED_1X + 1
    bcc !done+                  ; 1x, or a slot that never got one: 4 cycles
    ... wmScaleOne on wmVX and wmVY ...

wmScaleOne:                     ; A = (|A| * wmSpeed[X]) >> 2, sign restored
    sta wmSgn
    bpl !mag+
    eor #$ff / clc / adc #1     ; |v|
!mag:
    sta wmMag
    lda #0
    ldy wmSpeed,x               ; 5..8 -- bounded by the assembler's own check
!mul:
    clc / adc wmMag / dey / bne !mul-
    lsr / lsr                   ; >> TRIG_SPEED_SHIFT
    ldy wmSgn / bpl !done+
    eor #$ff / clc / adc #1
```

**Repeated addition rather than a general multiply**, because the multiplier is
5..8 and the operand is bounded: at most eight adds, ~64 cycles, on a path that
runs a handful of times in an object's life and at most once every
`framesPerStep` during an arc. A general 8×8 routine would be more code for a
case that never occurs. The 1.00× early-out means the default costs four cycles.

**It cannot overflow**, and that is asserted at build time rather than argued:

```asm
.if ((ENEMY_CLEAR_X_LEFT * 4) * TRIG_SPEED_MAX > 255
     || WM_ARC_SPEED * TRIG_SPEED_MAX > 255) { .error ... }
```

16 × 8 = 128 for a straight leg, 6 × 8 = 48 for an arc — both inside the byte
the loop accumulates in.

### Ownership lifetime

```
trigSpeed[t]  --(waveStartNext, when the wave is armed)-->  wvSpeed[instance]
              --(waveSpawnMember, before the first stage)-->  wmSpeed[object]
```

**Copied to the object, not read from the instance later**, and the order
matters twice:

* a wave sends its members over many frames and its slot is recycled, so an
  enemy reading `wvSpeed` later could take its pace from whatever appearance
  happened to be running;
* the copy happens **before** `wmEnterStage`, because that call writes and
  scales the first velocity — put it after and every wave's opening leg would
  fly at 1× while later stages obeyed the trigger.

`wmClearSlot` clears `wmSpeed` to `TRIG_SPEED_1X`, **not to zero** — it is the
one movement field where zero is not the harmless value. The package's unused
trigger padding is `TRIG_SPEED_1X` for the same reason, where every other column
pads with zero.

### What is deliberately not scaled

`src/dropper.asm` and `src/token.asm` write `wmVX`/`wmVY` directly. A Dropper is
taken off its wave's path by `dropperLaunch` the instant it spawns and flies its
own three-pass flight; protector patrol is a token-encounter state machine.
Both are engine behaviours rather than authored formations, so they keep their
own pace. **An author setting a speed on a DROPPER trigger will see no effect**
— worth knowing, and listed under limitations.

---

## 4. Flight validator

The audit's sharpest finding was that flying each path once, at 1×, would stop
proving anything the moment a trigger could walk it at 2×. Two changes:

**1. Every definition is flown at every speed its triggers actually ask for.**
`src/waves.asm` builds the set of distinct speeds per definition by joining
trigger → definition, then runs the existing four-property simulation once per
speed. A definition no trigger uses is still flown, at the default, so unused
authored content does not silently stop being checked. The simulation's
velocities go through `wmScaleSim`, an assembler-side copy of `wmScaleOne`
written the same way rather than the convenient way.

**2. A static, alignment-independent wrap guard on scaled velocity.**

```asm
.if (abs(wmScaleSim(rec.get(2), speed)) > ENEMY_CLEAR_X_LEFT * 4) { .error ... }
.if (wmScaleSim(WM_ARC_SPEED, speed) > ENEMY_CLEAR_X_LEFT * 4) { .error ... }
```

A simulated bound is not enough here: whether a too-fast leg actually lands on a
negative X depends on where it started. Stepping 8 pixels left from `px=8` lands
on 0 and is freed correctly; from `px=7` it lands on −1, `logXHi` borrows to
`$ff`, and the sprite teleports 256 pixels right. The rule is the **window
width** — `ENEMY_CLEAR_X_LEFT` is 4 pixels and the despawn test runs once a
frame, so holding every scaled velocity to 4 px/frame makes the jump impossible
at any alignment.

**The second line is where arcs finally get checked at all.** The pre-existing
per-record test guards STRAIGHT and HOLD only, because an arc has no authored
velocity to look at. That was fine while every arc was `WM_ARC_SPEED`; it is not
fine now.

Headroom at each speed, all inside the 16-quarter-pixel window:

| speed | arc becomes | authored straight leg limit |
|---|---|---|
| 1.00× | 6 | 16 |
| 1.25× | 7 | 13 |
| 1.50× | 9 | 11 |
| 1.75× | 10 | 9 |
| 2.00× | **12** | 8 |

The library's fastest authored leg is 6 quarter pixels, so **all current content
is safe at all five speeds** — proved by assembling it, not by arithmetic alone.

---

## 5. Editor

**Trigger pane** gained `movement speed`, a readonly combobox showing
`1.00x / 1.25x / 1.50x / 1.75x / 2.00x`. The author never sees the encoded
integer. Beside it, a note that this is physical travel only and that a faster
wave spends less time in the firing band.

**Wave Definition pane** is unchanged and owns no speed.

**Preview** takes the selected trigger's speed and the headline states it, so
the same definition previewed from two triggers visibly travels at two rates.
`simulate_trigger` passes `trig.resolved_speed`; `simulate_wave` and
`simulate_member` accept it and set `obj.speed` before the first
`_enter_stage`.

---

## 6. Preview / runtime parity

The preview simulator is a faithful port of the engine, so parity was a mirrored
edit at the **same two named functions** — `_load_heading` and `_enter_stage` —
using `contract_v2.scale_velocity`, which is the same sign-magnitude rule.

Measured, per speed, over the opening STRAIGHT leg of `sweep` (vx = 6):

```
1.00x: travels exactly its scaled velocity   got (45, 0), expected (45, 0) from v=6
1.25x: travels exactly its scaled velocity   got (52, 0), expected (52, 0) from v=7
1.50x: travels exactly its scaled velocity   got (67, 0), expected (67, 0) from v=9
1.75x: travels exactly its scaled velocity   got (75, 0), expected (75, 0) from v=10
2.00x: travels exactly its scaled velocity   got (90, 0), expected (90, 0) from v=12
```

**Exact, not close.** And an arc — which has no authored velocity at all —
scales monotonically: `(47,31) → (55,35) → (69,43) → (78,49) → (94,62)`.

### A documented rounding consequence

1.25× of 6 quarter pixels is **7, not 7.5** — the engine has no half quarter
pixel. So the *distance* covered is not 1.25× the distance; the *velocity* is
the scaled velocity, exactly. This is inherent to the representation, identical
in preview and runtime, and is why the parity test predicts from the scaled
velocity rather than from scaled distance.

> My first draft of both the editor and runtime tests got this wrong and wanted
> a fudge factor. The runtime one also summed path length as `|dx|+|dy|`, which
> on a 45° leg is 1.41× the distance travelled, and averaged over windows whose
> content mix differed between runs — it reported **1.64×** for a change that is
> exactly 2×. Both tests now measure quantities that are actually defined.

---

## 7. Runtime evidence

`tests/test_trigger_speed.py` — **all pass**, six short VICE launches.

```
ok   every authored trigger carries a movement speed -- 12 triggers
ok   ...and every one of them is 1.00x
ok   the padding past the live triggers is 1.00x, not zero
ok   1.00x: ...straight leg runs at the scaled velocity 6
ok   1.25x: ...7      1.50x: ...9      1.75x: ...10      2.00x: ...12
ok   2.00x: the position advances at 12/4 px a frame -- 57 px in 19 frames
ok   1.00x is bit-identical to the engine's own authored velocity
ok   arcs scale too: 1.00x=6  1.25x=7  1.50x=9  1.75x=10  2.00x=12
ok   the 6502 scaler agrees with the model for every value and speed -- 75 cases
ok   ...including negatives, which no observed path reached
ok   ...and zero stays zero at every speed
ok   ONE DEFINITION PRODUCED ENEMIES AT TWO DIFFERENT VELOCITIES
       1.00x |vx| [1,2,3,4,5,6];  2.00x |vx| [2,4,6,8,10,12]
ok   ...and the fast one's maximum is twice the slow one's -- 6 -> 12
```

Two notes on method:

* **The signed cases are exercised, not observed.** Level 1's opening waves
  travel right and down, so watching them proves nothing about negative
  components. `wmApplySpeed` is self-contained, so it is simply *called* with
  poked inputs — 75 combinations of value and speed, on the real processor.
* **The shared-definition proof points two early triggers at one definition.**
  Level 1 does reuse definitions, but its shared pairs sit at world rows 205 and
  310 — frames 1640 and 2480 — and stepping that far through the monitor costs
  minutes for one assertion. `trigDef` is authored data exactly like
  `trigSpeed`, and the property being proved is about sharing, not about where
  the author put the rows.

### Visible VICE

Headless framebuffer captures, `-console`, no window and no focus taken. Both
runs sampled at **the same frame offset after the first spawn**, so the only
difference is the one being demonstrated:

| | enemy X positions | `wmVX` |
|---|---|---|
| **1.00×** | 43, 76, 103, 115 | 1, 4, 6 |
| **2.00×** | 87, 153, 206, 230 | 2, 8, 12 |

Every position and every velocity exactly doubled. In the images the 1.00×
formation is still bunched in the left third while the 2.00× formation has
spread across the middle and right. Rendering is clean in both — no corruption,
flicker or scroll artefact.

**Final visual acceptance is still yours**, and MiSTer/CRT more so. A long,
normal-speed, non-warp session is the thing I cannot do.

---

## 8. Trigger record and capacity

| | before | after |
|---|---|---|
| columns | 8 | **9** |
| bytes per trigger | 8 | **9** |
| reservation | 1082 bytes | 1082 bytes |
| **capacity** | 135 | **120** |
| level 1 uses | 12 | 12 |
| level 2 uses | 7 | 7 |

`$f736–$fb6d` = 1080 bytes = 9 × 120, ending two bytes below the package
signature at `$fb70`. Level 1 uses **10 %** of the ceiling.

Memory elsewhere: `wmSpeed` 16 bytes (movement state now 178 of 192),
`wvSpeed` 2 bytes (wave state 52 of 64), two scratch bytes for the scaler.

### The capacity test, fixed structurally

`tests/test_movement_pool.py` had frozen **five** derived values, and all five
had gone stale:

| was | actual | now |
|---|---|---|
| `TRIG_SLOTS = 180` | 120 | `C.LEVELPKG_TRIG_SLOTS` |
| six column names | nine | nine, asserted against `C.LEVELPKG_TRIG_COLS` |
| `WAVE_DEFS, WAVE_TRIGGERS = 4, 4` | 7, 12 | read from the generated level |
| `TRIG_ROWS/SPECIES/FIRE/SIDE` | changed | read from the generated level |
| `PROG_AT = [0,12,24,40]`, 52-byte pool | 7 offsets, 76 bytes | derived from `progs` |

Everything now comes from `src/levelpkg.asm` (via `contract_v2`) and the
generated `wave_encounters.asm`/`wave_programs.asm`, read through the editor's
own declaration parser. It also gained explicit capacity checks:

```
ok   the trigger columns tile the package's reservation exactly -- 9 x 120 = 1080 of 1082
ok   the editor's authoring ceiling is that same slot count -- 120
ok   ...and this level fits inside it -- 12 of 120 slots used
ok   the whole trigger list stays below the package signature -- ends at $fb6e
```

I also fixed the same anti-pattern in my **own** test from the previous task,
which had frozen `(8, 135)`; it now asserts the relationship.

---

## 9. Firing and timing — observed, not compensated

**Nothing about cadence was changed.** `WAVE_FIRE_PERIOD` (48),
`TURRET_FIRE_INTERVAL` (100), `ENEMY_FIRE_MIN_Y/MAX_Y` (70/170),
`ENEMY_FIRE_LEAD` (24), `WAVE_SLOTS` (2), spawn intervals, wave spacing,
formation offsets and scroll speed are all untouched. The diff of `src/waves.asm`
contains no firing constant.

The consequence the audit predicted stands and is documented rather than
corrected:

| descent speed | frames inside the 100-px firing band | firing opportunities |
|---|---|---|
| 1.5 px/frame (1.00×) | ~67 | ~1.4 |
| 3.0 px/frame (2.00×) | ~33 | ~0.7 |

**A fast descending wave may cross the firing band without ever getting an
opportunity.** Nothing breaks — the gate is a band test, not an assumption — but
"make this wave faster" also quietly means "make it quieter". The editor says so
next to the control.

Other thresholds crossed sooner at 2×: waves clear in about half the time, so
consecutive triggers overlap less; and because the spawn interval is in *frames*,
a formation's members end up twice as far apart in space. Both are design
consequences of the feature working, not faults, and neither was rebalanced.

---

## 10. Manual Tk acceptance — stated precisely

**I did not perform a human-eyes-on-screen acceptance, and I am not claiming
one.** What was done, with real Tk:

`tools/level_editor/test_trigger_speed.py` builds the actual `LevelEditor`,
opens the real Encounter workspace, and drives it through real widget callbacks
— in a **withdrawn** window, so the widgets are genuinely constructed and
mapped-state is false and no focus is taken from your desktop. That is the
strongest check available without disrupting you, and it is the level at which
the previous identity regression would have been caught.

```
ok  - the trigger pane offers a movement speed
ok  - ...showing the five friendly labels  ['1.00x','1.25x','1.50x','1.75x','2.00x']
ok  - ...and NOT the encoded integers
ok  - the wave-definition pane offers no speed
ok  - two triggers share the definition 'loop'  [rows 126 and 350]
ok  - a trigger shows its own speed
ok  - choosing 2.00x sets THIS trigger
ok  - ...AND LEAVES THE OTHER ON THE SAME DEFINITION ALONE
ok  - the edit marked the document dirty
ok  - switching trigger shows the OTHER one's speed
ok  - ...and switching back shows 2.00x again
ok  - all three workspace tabs still select cleanly
ok  - the wave-definition pane still populates
ok  - the movement-program pane still populates
ok  - the Encounter window closes and reopens without a traceback
```

The close-and-reopen case is included specifically because that is where the
last regression hid. **One real look from you is still worth having.**

---

## 11. Tests and results

| suite | result |
|---|---|
| `tools/level_editor/test_trigger_speed.py` (new) | **77 passed, 0 failed** |
| `tools/level_editor/test_trigger_speed_validator.py` (new) | **9 passed, 0 failed** |
| `tests/test_trigger_speed.py` (new) | **ALL PASS** |
| `tests/test_movement_pool.py` (repaired) | **ALL PASS** (was 9 FAIL) |
| `tools/level_editor/test_wave_colour_mode.py` | 83 passed, 0 failed |
| `make smoke` | **PASS** |
| `test_boot`, `test_aimed_fire`, `test_aimed_velocity`, `test_wave_colour_mode`, `test_dropper_flight` | pass |
| editor: `test_wave_schema`, `test_v6_validation`, `test_v6_migration`, `test_level_packages`, `test_v6_phase5b_encounters`, `test_v6_phase5a_gui`, `test_semantic_gui`, `test_encounters_gui` | pass |

```
make smoke   4046 frames
  gameOverrun 0   scrollLate 0   edgeLate 0   statOverflow 0
  publishSkip 0   schedBuildDefer 0   statLate 0   clipPoolFull 0
  BOOT PASS / CAMPAIGN LOOP PASS / ENGINE HEALTH PASS / ROUTINE REGRESSION PASS
```

### Pre-existing failures, verified against HEAD

Baselined by exporting HEAD read-only with `git archive` into scratch — no
`checkout`, `stash` or `reset` was involved — and running the suites there.
All four fail identically at HEAD and come from the enemy-identity work:

| suite | failure | at HEAD |
|---|---|---|
| `test_encounter_director` | 2 FAIL, wave concurrency | same |
| `test_flight_paths` | 1 FAIL, same family | same |
| `test_v6_roundtrip` | key order drifted (`enemySlots`) | identical |
| `test_encounter_library` | `StopIteration` on a SQUARE trigger, line 349 | identical |
| `test_multi_level_layout` | `contract_v2` has no `DEFAULT_ENEMY_SLOTS` | identical |

---

## 12. One mistake, caught and corrected

Re-exporting levels 2 and 3 caused the **level editor's exporter to overwrite
`src/level{2,3}/stage_sprites.asm`**, which is owned by
`tools/sprite_export/import_spd.py`. The change was comments only — no
functional difference — but it replaced the sprite importer's provenance header,
including the `.spd` sha256, with the editor's generic one. That is exactly the
unrelated generated-data drift this task was told not to create.

Both files were restored by **plain file copy** from the read-only HEAD export,
and `git status` confirms they are byte-identical to HEAD again. The build was
re-run and `make smoke` re-run afterwards.

**Two generators write the same filename**, and nothing stops the wrong one
winning. Left alone as out of scope, but flagged: it will happen again to
whoever next re-exports a level.

---

## 13. Files changed

| file | change |
|---|---|
| `src/encounter_format.asm` | `TRIG_SPEED_*` constants and the rationale |
| `src/levelpkg.asm` | `LEVELPKG_TRIG_COLS` 8 → 9; stale `// 180` comment removed |
| `src/level_package.asm` | emits `trigSpeed`, padded with `TRIG_SPEED_1X` |
| `src/waves.asm` | `waveTrigSpeed` label; `wvSpeed`; the latch; the spawn copy; per-trigger range proof; **per-speed flight validation**; **scaled wrap guard**; `wmScaleSim` |
| `src/movement.asm` | `wmSpeed`, `wmSgn`, `wmMag`; `wmApplySpeed`; `wmScaleOne`; applied at the two write sites; `wmClearSlot` clears to 1× |
| `src/level{1,2,3}/wave_encounters.asm` | **generated** — the `trigSpeed` column |
| `contract_v2.py` | `SPEED_CHOICES`, `SPEED_LABELS`, `scale_velocity`; 9 columns; capacity **derived** from its own parts |
| `project_v6.py` | `Trigger.speed` + `resolved_speed`; migration |
| `validation_v6.py` | `trigger.speed` |
| `export_v6.py` | `trigger_speed_byte`/`_expr`; the new column |
| `controller_v6.py` | trigger CRUD carries speed |
| `encounters_ui.py` | the movement-speed control |
| `movement_sim.py` | `_apply_speed`; `speed` on the object and through the API |
| `preview_ui.py` | the trigger's speed reaches the preview and its headline |
| `levels/level{1,2}/level.v6.json` | **migrated data** — every trigger 1.00× |
| `tests/test_movement_pool.py` | **capacity and content fully derived** |
| `tools/level_editor/test_wave_colour_mode.py` | its frozen capacity check now derives |
| `tests/test_trigger_speed.py` | **new** |
| `tools/level_editor/test_trigger_speed.py` | **new** |
| `tools/level_editor/test_trigger_speed_validator.py` | **new** |

Not touched: renderer, multiplexer, scroller, raster, firing cadence, spawn
intervals, wave spacing, HP, projectile cap, scroll speed, sprite animation,
enemy identities, collision.

---

## 14. Limitations and deferred work

1. **Droppers and token protectors do not scale.** They write their own
   velocity; a speed set on a DROPPER trigger has no effect. Arguably correct —
   they are engine state machines, not authored formations — but the UI does not
   yet say so.
2. **No slower than 1.00×**, by design (§1). If slow passes are wanted, the
   honest lever is a wider turn radius.
3. **1.25× and 1.75× round.** 6 → 7 and 6 → 10 rather than 7.5 and 10.5.
   Identical in preview and runtime; inherent to quarter-pixel velocity.
4. **The firing-band interaction is real** (§9) and deliberately uncompensated.
5. **Two generators own `stage_sprites.asm`** (§12).
6. **Animation speed remains untouched**, as instructed.

---

## 15. Final state

```
 M src/encounter_format.asm              M tools/level_editor/contract_v2.py
 M src/level1/wave_encounters.asm        M tools/level_editor/controller_v6.py
 M src/level2/wave_encounters.asm        M tools/level_editor/encounters_ui.py
 M src/level3/wave_encounters.asm        M tools/level_editor/export_v6.py
 M src/level_package.asm                 M tools/level_editor/levels/level1/level.v6.json
 M src/levelpkg.asm                      M tools/level_editor/levels/level2/level.v6.json
 M src/movement.asm                      M tools/level_editor/movement_sim.py
 M src/waves.asm                         M tools/level_editor/preview_ui.py
 M tests/test_movement_pool.py           M tools/level_editor/project_v6.py
                                         M tools/level_editor/test_wave_colour_mode.py
                                         M tools/level_editor/validation_v6.py
?? reports/enemy-movement-speed-ownership-audit.md
?? reports/trigger-owned-movement-speed.md
?? tests/test_trigger_speed.py
?? tools/level_editor/test_trigger_speed.py
?? tools/level_editor/test_trigger_speed_validator.py

22 files changed, 660 insertions(+), 114 deletions(-)
```

* **Nothing committed. Nothing pushed.** HEAD is still
  `0c50a46 More enemy types added to editor`.
* **No destructive Git operation was used.** No `checkout`, `restore`, `reset`,
  `stash` or `clean` at any point. Baselines came from `git archive HEAD` into a
  scratch directory, which writes nothing to the repository; the two
  accidentally-regenerated files were restored from that same read-only export
  by file copy.
* VICE: every instance launched through the harness with `-console`, owned by
  exact PID and reaped in a `finally`. No broad `pkill`/`killall`, no
  user-launched instance touched, no focus stolen. `pgrep -fl x64sc` confirms
  **none running**.
* `build/` is **340 K**, current artefacts only. Scratch — the HEAD export,
  probes and captures — is **14 M** in the session scratchpad; `/tmp` logs were
  deleted. **93 GiB free of 228 GiB.**
