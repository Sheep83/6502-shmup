# Audit: Enemy Movement Speed — Ownership and Runtime Path

**Date:** 2026-09-29
**Read-only audit. Nothing implemented. No commit, no push, no destructive Git operation.**

---

## Executive summary

Four findings, in order of how much they change the plan:

1. **The editor's "speed" control is not a movement speed at all.** It is the
   preview transport's wall-clock playback rate (`0.25x … 4x`). It never
   reaches the project, let alone the C64. The word "speed" appears in **zero**
   project files, **zero** library entries and **zero** generated `.asm` files.

2. **Nothing owns movement speed today.** It is *baked into the movement
   program* two different ways: `STRAIGHT`/`HOLD` carry explicit `vx,vy` bytes,
   and `ARC` has no velocity at all — it reads a heading table whose magnitude
   is the engine constant `WM_ARC_SPEED = 6`. Every authored travel leg in the
   game is 6 quarter-pixels/frame (1.5 px/frame); the only exception is
   `linger`'s deliberate 1 qpx hold.

3. **A trigger-owned speed is genuinely cheap**, because velocity is written in
   exactly **two cold places** and integrated in one. It costs no per-frame
   cycles at all.

4. **There is a hard ceiling, and it is lower than you would guess: ~4 px/frame
   horizontally.** `ENEMY_CLEAR_X_LEFT` is a once-a-frame *wrap guard*; step over
   it and `logXHi` borrows to `$ff` and the sprite teleports 256 px right. The
   assembler enforces `|vx| ≤ 16` qpx for straight legs — **but not for arcs**,
   which would become unguarded the moment anything scales them.

---

## 1. Editor speed controls

### 1.1 The preview transport multiplier — *not* project data

| | |
|---|---|
| **Control** | `speed_box`, a readonly `ttk.Combobox` in the preview transport bar |
| **File** | `tools/level_editor/preview_ui.py:172` |
| **Values** | `SPEEDS = (("0.25x", 0.25), ("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("4x", 4.0))` |
| **Stored in** | `self.speed = tk.StringVar(value="1x")` — a **widget variable** |
| **Default** | `1x` |
| **Units** | a wall-clock divisor on the frame timer; dimensionless |
| **Project data?** | **No.** Preview-only. |
| **Marks dirty?** | **No.** It is not routed through `_edit()` and touches no model object. |
| **Survives save/reload?** | **No.** It is not serialised anywhere; it resets to `1x` when the window is rebuilt. |

### 1.2 The controls that *are* real authored speed

These do reach the runtime, and they are the only ones that do:

| control | file | units | range | project data |
|---|---|---|---|---|
| **HOLD `drift`** | `encounters_ui.py:598` (semantic segment editor) | quarter px/frame **along the current heading** | ±`MAX_ABS_VX` = 16 | yes, saved, exported |
| **raw stage `vx` / `vy`** | `encounters_ui.py:663-664` (raw stage editor) | quarter px/frame, signed | ±16 each | yes, saved, exported |

Both belong to the **Movement Program**, not the wave and not the trigger.

**There is no "enemy travel speed" control anywhere in the editor.** A
`STRAIGHT` segment in the semantic vocabulary offers only `frames` and an
optional `heading`; a `TURN` offers `direction`, `steps` and `rate`. Neither can
express a speed. That is deliberate — `movement_semantic.py` compiles both from
a constant-magnitude heading table — but it means the answer to "how fast does
this enemy fly?" is currently "1.5 px/frame, always".

---

## 2. What the preview does with speed

`preview_ui.py`, the entire mechanism:

```python
def _schedule(self):
    mult = dict(SPEEDS).get(self.speed.get(), 1.0)
    self._job = self.after(max(1, int(PAL_FRAME_MS / mult)), self._advance)

def _advance(self):
    ...
    self.frame += 1          # ALWAYS exactly one simulated frame
    self._sync_transport()
    self._draw_markers()
    self._schedule()
```

`PAL_FRAME_MS = 20` (50 Hz). So:

```
wall-clock interval between simulated frames = 20 / multiplier  ms
simulated frames advanced per tick           = 1, invariably
```

It is **playback rate**, exactly like a video scrubber. At `4x` the preview
shows you the same trajectory, the same 1.5 px/frame, four times faster in real
time. The simulation itself is precomputed and indexed by frame number —
`step()` documents that frames are *looked up*, never integrated from the
marker — so the multiplier cannot affect the path even in principle.

---

## 3. Does it export? — the full chain

```
preview speed combobox
   └─► tk.StringVar  ──✗  STOPS HERE. Never read by anything but _schedule().
```

Verified rather than assumed:

```
grep -ril "speed" tools/level_editor/levels/*/level.v6.json
                  tools/level_editor/encounter_library.v6.json   → none
grep -ril "speed" src/level1/*.asm src/level2/*.asm src/level3/*.asm → none
```

The chain that **does** exist, for the authored velocities:

```
segment editor (drift) ─┐
raw stage editor (vx,vy)├─► MovementStage.vx/.vy  (project_v6)
semantic compile ───────┘         │
                                  ├─► encounter_library.v6.json  "vx": 6, "vy": 0
                                  ├─► export_v6.render_wave_programs
                                  ├─► src/level1/wave_programs.asm  (.var progs)
                                  ├─► src/level_package.asm → LEVELPKG_MOVE ($f532)
                                  └─► src/movement.asm wmEnterStage → wmVX/wmVY
```

**Independent runtime speed values** (nothing in the editor sets these):

| constant | file | value | meaning |
|---|---|---|---|
| `WM_ARC_SPEED` | `src/movement_format.asm` | **6** | quarter px/frame — the magnitude of *every* heading-table entry, so the speed of **every arc and every semantic straight** |
| `WM_ARC_STEP` | same | 4 | default frames per heading step (turn radius, not speed) |

---

## 4. How runtime movement actually advances

### 4.1 State (`src/movement.asm`, `$7700`)

| array | width | meaning |
|---|---|---|
| `wmVX`, `wmVY` | `MAX_OBJECTS` bytes each | **signed, quarter pixels per frame** |
| `wmAccX`, `wmAccY` | ditto | sub-pixel remainder, 0..3 |
| `wmMode`, `wmStage`, `wmPhase`, `wmTimer`, `wmSteps`, `wmBaseCol` | ditto | the rest |

Coordinates are **integer** `logX` (9-bit: `logX` + `logXHi`) and `logY`
(8-bit). Sub-pixel precision lives *only* in the 2-bit accumulators.

### 4.2 The integrator — `wmApplyVelocity`, once per object per frame

```
acc      = acc + v                  ; 8-bit add, v signed
remainder= acc & 3                  ; stays 0..3, always positive
delta    = floor(acc / 4)           ; two RORs preceded by CMP #$80 -> arithmetic
logX    += delta                    ; with explicit logXHi carry/borrow fixup
```

Y is the same without the high byte. **This is the only place position changes**
for a wave-driven enemy.

### 4.3 Where velocity is *written* — only two places

| site | when | source |
|---|---|---|
| `wmLoadHeading` | on entering an arc, and on **every heading step** | `wmHeadVX/VY[wmPhase]` — fixed magnitude 6 |
| `wmEnterStage` | on entering a `STRAIGHT`/`HOLD` stage | record bytes 2 and 3 |

`WM_EXIT` deliberately writes **nothing** — it inherits, which is what makes
`ARC → EXIT` continuous.

Both sites are **cold**: a handful of executions across an object's whole life,
never per frame. That is the single most important fact for the cost of any
speed feature.

### 4.4 Per-step deltas, and whether programs run at different speeds

* `STRAIGHT`/`HOLD` records **do** contain explicit per-stage velocity.
* `ARC`/`ARC_MIRROR` records **do not** — byte 2 is *frames per step* (radius)
  and byte 3 is the entry heading. **An arc's speed is not expressible.**
* So different programs can differ in speed *only* in their straight legs, and
  in practice they do not: measured across the live library —

```
sweep      STRAIGHT (6,0)   6.00 qpx = 1.500 px/frame   ARC fixed 1.5
s                                                       ARC ×2 fixed 1.5
linger     STRAIGHT (3,5)   5.83 qpx = 1.458 px/frame   HOLD (0,1) 0.25   ARC fixed
loop       STRAIGHT (4,4)   5.66 qpx = 1.414 px/frame   ARC fixed 1.5
dive_bomb  STRAIGHT (0,6)   6.00 qpx = 1.500 px/frame   ARC fixed 1.5
up_n_over  STRAIGHT (4,-4)  5.66 qpx = 1.414 px/frame   ARC fixed 1.5
```

Every travel leg is 6 qpx, give or take diagonal rounding. **The game has one
enemy speed.**

### 4.5 Global divisor / multiplier

**None.** There is no movement divisor, no frame skip, no global scalar.
`wmTick` runs once per object per `gameFrame`.

### 4.6 PAL cadence

Assumed throughout: one tick per frame at 50 Hz, and the heading table's
comment states the speed as "1.5 px/frame, 75 px/second". Nothing is
time-normalised; speed *is* per-frame.

### 4.7 Range and overflow — the ceilings

**Horizontal — the binding one.** `ENEMY_CLEAR_X_LEFT = 4`, and
`src/enemy.asm` says why in its own words:

> *"An enemy allowed to walk past zero would borrow `logXHi` down to `$ff` and
> reappear 256 pixels to the RIGHT — a sprite teleporting across the screen, not
> a sprite leaving it."*

The despawn test runs **once a frame**, so a leg that moves more than the
clearance window in one frame can step over it. The assembler enforces:

```asm
.if (abs(rec.get(2)) > ENEMY_CLEAR_X_LEFT * 4) {   // 16 qpx = 4 px/frame
    .error "a straight or hold leg moves in X fast enough to step over the
            left clearance window and wrap"
}
```

> ⚠ **That guard is in the non-arc branch.** Arcs are unchecked — safe today
> only because they are hard-wired to 6 qpx. Anything that scales arc velocity
> makes them unguarded.

**Vertical.** `logY` is 8-bit and the despawn test is `cmp #ENEMY_CLEAR_Y`
(248) → gone. From 247, a step of +8 lands on 255 (still ≥ 248, correctly
freed); a step of **+9 wraps to 0**, and the top-edge test then asks `wmVY` —
descending → *alive*. The enemy reappears at the top and flies down again.
Ceiling ≈ **8 px/frame (32 qpx)**.

**The accumulator.** `acc ∈ [0,3]`, `acc + v` is an 8-bit add read as signed, so
`v` must satisfy `acc + v ≤ 127` → **`v ≤ 124` qpx**. Not binding; the wrap
guards bite first by a factor of eight.

**Editor bound.** `contract_v2.MAX_ABS_VX = ENEMY_CLEAR_X_LEFT * WM_STAGE_SIZE`
= 16, applied by `validation_v6` to **both** axes — stricter than the engine,
which guards only X. Harmless, but note the derivation multiplies by
`WM_STAGE_SIZE` (the *record size*, 4) where the engine multiplies by the
*sub-pixel divisor* (also 4). Two different fours that happen to agree; a
latent confusion if either ever changes.

---

## 5. Where speed is owned today

| candidate | owns speed? |
|---|---|
| **Movement Program** | **Yes, for straight/hold legs** — `vx`/`vy` are stage record bytes |
| **Engine global** | **Yes, for arcs and semantic straights** — `WM_ARC_SPEED = 6` |
| Wave Definition | No |
| Trigger | No |
| Enemy identity / species | No |
| Move (semantic segment) | Only `HOLD.drift`, which is a loiter creep, not travel |

**Conceptual vs accidental.** Conceptually nobody decided the movement program
should own speed; velocity simply lives in the stage record because that is
where a velocity naturally goes. The *arc* case is stronger than accidental —
it is a deliberate design constraint: the 64-entry heading table exists at
magnitude 6 precisely because that radius yields 64 distinct lattice directions
(`movement_semantic.drift_is_faithful` documents this). At lower magnitudes the
directions collapse.

So: **speed is owned by the path data and by one engine constant, and the
constant is load-bearing for direction fidelity.**

---

## 6. Smallest clean Trigger-owned implementation

### 6.1 Shape

> **Trigger carries a speed scalar; the runtime applies it at the two places
> velocity is written.**

Not export-time preprocessing. Baking speed into duplicated programs would
consume the movement pool, which has a **hard 256-byte ceiling** (`wmStage` is
one byte) and currently uses 76 bytes — and it is exactly the duplication the
brief wants to avoid.

### 6.2 Representation

**`trigSpeed`: one byte, a numerator over 4.**

```
scaled_v = (v * trigSpeed) >> 2
```

| value | multiplier | arc becomes | notes |
|---|---|---|---|
| 1 | 0.25× | 1 qpx | directions collapse badly — see 6.7 |
| 2 | 0.5× | 3 qpx | |
| **4** | **1.0×** | **6 qpx** | **default; bit-exact no-op** |
| 6 | 1.5× | 9 qpx | |
| 8 | 2.0× | 12 qpx = 3 px/frame | comfortable headroom |
| 10 | 2.5× | 15 qpx | at the X wrap guard's edge |

**Why the default is exactly safe:** `(v * 4) >> 2 == v` for every `v`, with no
rounding. A migrated project reproduces current gameplay **bit for bit**, not
approximately.

**Recommended authored range: 1..8 (0.25× … 2.0×)**, default 4.

### 6.3 Change list

| layer | change |
|---|---|
| **Schema** | `Trigger.speed: int = None` (None = inherit/default 4), serialised `"speed"`; migration sets 4 — the existing `resolve_trigger_encounter_fields` already does exactly this pattern for colour and fire mode |
| **Trigger record** | a **9th column**, `trigSpeed` |
| **Editor** | one spinbox/combobox in the trigger pane beside fire mode; label it in multipliers, store the numerator |
| **Exporter** | one `_list_decl("trigSpeed", ...)` + `TRIG_SPEED_*` constants in `encounter_format.asm` |
| **Runtime storage** | `wvSpeed: .fill WAVE_SLOTS` (latched at arm, like colour and fire mode) → `wmSpeed: .fill MAX_OBJECTS` (copied at spawn) |
| **Runtime calc** | scale in `wmLoadHeading` and in `wmEnterStage`'s STRAIGHT/HOLD branch |
| **Validator** | extend the assembly-time flight proof — **see 6.8, this is the real work** |

### 6.4 Memory

| | bytes |
|---|---|
| `trigSpeed` column | 135 → becomes 120 slots (see §7) |
| `wvSpeed` | 2 (WAVE_SLOTS) |
| `wmSpeed` | 16 (MAX_OBJECTS) |
| **movement state headroom** | **160 of 192 used — 32 free, room for two more arrays.** Fits. |

### 6.5 Cycles

**Zero per frame.** The scale happens only where velocity is written:

* `wmEnterStage` — a few times per object lifetime;
* `wmLoadHeading` — once per heading step, i.e. every `framesPerStep` (2–4)
  frames *during arcs only*.

A signed 8×8→8 multiply-and-shift is ~40–70 cycles. Worst case (a tight arc at
`framesPerStep = 2`, six enemies) ≈ 3 × 70 × 6 ≈ 1,260 cycles per frame in the
absolute worst case — 6 % of the 19,656-cycle PAL budget, and only while six
enemies are all mid-arc. **If that is judged too much**, restrict speed to
powers of two (`>>1`, `×1`, `<<1`) and it collapses to a shift, ~8 cycles.
I would start with the multiply and measure, not pre-optimise.

### 6.6 Precision

Scaling *after* the heading lookup rounds a second time: `(6 × 6) >> 2 = 9`
exactly, but `(5 × 6) >> 2 = 7` where true 1.5× of 5 is 7.5. Directional error
grows as the multiplier moves away from integers. Acceptable for travel; worth
knowing.

### 6.7 The arc-direction caveat — the one real design risk

`movement_semantic.drift_is_faithful` documents that the number of distinct
directions expressible at magnitude *v* is roughly the number of lattice points
at that radius — **64 at v = 6, which is exactly why the table uses 6.** Scaling
arcs *down* therefore does not just slow the turn, it **coarsens it**: at 0.5×
(3 qpx) many of the 64 headings round to the same velocity and a smooth curve
becomes visibly polygonal.

**Scaling up is safe; scaling down below ~1.0× degrades arc quality.** If slow
formations matter, the honest answer for arcs is a larger `framesPerStep`
(wider radius, same speed) rather than a smaller magnitude — and that is already
authorable today.

### 6.8 The part that is *not* trivial

`src/waves.asm` flies **every authored path at assembly time** and proves four
properties: it leaves, it arrives, it never walks X past zero, it does not
materialise in view. That simulation integrates at the **authored** speed.

A runtime multiplier invalidates all four proofs. The validator must therefore
fly each program **once per distinct speed any trigger actually uses** — a join
over (trigger → definition → program, trigger → speed). That is very doable in
KickAssembler, and it is where most of the implementation effort will go. It is
also what would catch the unguarded-arc wrap risk from §4.7.

---

## 7. Trigger record budget

Measured from the current build, not remembered:

```
$f736-$fb6d  level wave triggers   = 1080 bytes
LEVELPKG_TRIG_MAX = 1600 - 2 - 256 - 260 = 1082
```

| | columns | bytes/trigger | slots |
|---|---|---|---|
| **now** | 8 | 8 | **135** |
| **with `trigSpeed`** | 9 | 9 | **120** |
| (for reference) | 10 | 10 | 108 |

Current use: **Level 1 = 12 triggers, Level 2 = 7.** 120 is ten times the
longest authored level. **This does not matter.**

> ⚠ `tests/test_movement_pool.py:28` hardcodes `TRIG_SLOTS = 180`, which is two
> column-additions stale. All nine of its current failures are that one
> constant. Whoever adds the ninth column should make it derive the value —
> see §11.

**Cheaper encoding, mentioned and not recommended:** `trigColour` uses bits 0-4
(`TRIG_COL_MASK` + `TRIG_COL_RANDOM`) and has **bits 5-7 free** — three bits,
eight speed values, zero capacity cost. It would work. I would not do it: it is
the colour byte, the last two refactors were specifically about *un*-muddling
overloaded bytes, and 120 slots costs nothing real.

---

## 8. Preview / runtime parity

**The preview is already a faithful port, not an approximation.**
`movement_sim.py` mirrors the engine routine for routine — `_enter_stage`,
`_load_heading`, `_apply_velocity` — and reproduces the integrator exactly:

```python
# acc_step: "s8(total) >> 2 is the same two RORs"
return s8(total) >> 2, total & 3
```

It even asserts the generated heading table matches the engine's quadrant
anchors at `WM_ARC_SPEED`.

**So parity for a speed feature is a mirrored edit in two named functions** —
`_load_heading` and `_enter_stage` — using the identical `(v * n) >> 2`. If both
sides use integer arithmetic in the same order, parity is exact, not close.

**Existing discrepancies found:** none in the integrator. The preview does
**not** model the object pool, the firing bands, the mux, or `WAVE_FIRE_PERIOD`
— it is a trajectory simulator, deliberately. So it will show you the path at
the new speed correctly, and will *not* show you that the wave stopped firing
(§9). Worth stating in the UI rather than fixing.

---

## 9. Interaction with encounter timing

| interacts with | effect of doubling speed | risk |
|---|---|---|
| **trigger row** | none — the row is where the wave *starts* | none |
| **intra-wave spawn interval** | interval is in **frames**, so members stay the same time apart and become **twice as far apart in space** | formation shape changes; this is a design consequence, not a bug |
| **inter-wave spacing** | waves clear faster, so overlap between consecutive triggers decreases | `WAVE_SLOTS = 2` unchanged |
| **wave duration** | roughly halves | |
| **continue-final-direction** | `WM_EXIT` inherits the (already scaled) velocity — correct with no extra work | none |
| **firing bands** | ⚠ **the significant one** — see below | real |
| **despawn** | ⚠ wrap guards, §4.7 | real, bounded by range |
| **formation offsets** | `xStep`/`yStep` are spatial and unscaled | unchanged |

### The firing-band interaction

`ENEMY_FIRE_MIN_Y = 70`, `ENEMY_FIRE_MAX_Y = 170` — a **100-pixel** band. The
whole screen gets **one** firing opportunity every `WAVE_FIRE_PERIOD = 48`
frames.

| descent speed | frames inside the band | opportunities that can fall inside |
|---|---|---|
| 1.5 px/frame (today) | ~67 | ~1.4 |
| 3.0 px/frame (2×) | ~33 | ~0.7 |

**A fast descending wave may pass through the firing band without ever getting
an opportunity.** Nothing breaks — the gate is a band test, not an assumption —
but "make this wave faster" silently also means "make this wave quieter". That
is a balance coupling you should know about before authoring with it. (Not
rebalanced here; `WAVE_FIRE_PERIOD` untouched.)

`ENEMY_FIRE_LEAD = 24` is unaffected — it is a positional lead, not a time.

### Two subsystems a trigger speed would *not* reach

`wmVX`/`wmVY` are also written directly by:

* **`src/dropper.asm`** — `dropperLaunch` takes a Dropper off its wave's path
  entirely and sets its own velocity; it also reads the **sign** of `wmVX` as
  its direction and negates `wmVX` to reverse.
* **`src/token.asm`** — protector patrol and upward dismissal.

Both are engine state machines rather than authored formations, so leaving them
unscaled is arguably correct — but **an author setting a speed on a DROPPER
trigger would see no effect**, and the UI should say so.

---

## 10. Is the desired UX sensible?

> define/reuse a Wave Definition → place a Trigger → pick identity → pick
> definition → **set speed** → preview reflects it → export reproduces it

**Yes, with one honest amendment.** Steps 1–5 and 7 fall out naturally: the
trigger already owns identity, colour and fire mode by exactly this pattern, and
the preview is already **trigger-sourced** (`_sync_preview_source`: *"the
TRIGGER is the most contextual, because it is the only selection that resolves
the whole authored chain"*). Step 6 is a two-function mirror.

The amendment is §6.7: **speeding up is clean; slowing down degrades arcs.** So
the control should be presented as a range centred on 1.0× with the slow end
either limited or flagged, and "slow formation pass" is better authored as a
wider turn radius than as a fractional speed.

---

## 11. Unrelated issues found (not fixed — this is an audit)

1. **`tests/test_movement_pool.py` — 9 failures, one cause.** Line 28 hardcodes
   `TRIG_SLOTS = 180`; the engine derives 135 since the colour and fire-mode
   columns landed. Every column address is off by the difference:
   `waveTrigRowHi` expected `$f7ea`, actual `$f7bd`. The data assertions fail
   downstream of that. **Adding a ninth column will move them again** — the fix
   is to derive the constant, not restate it.
2. **`tests/test_flight_paths.py` — 1 failure**, "two DIFFERENT authored
   patterns were in flight at once — 0 frames". Same family as the known
   `test_encounter_director` concurrency failures.
3. **`MAX_ABS_VX` derivation** multiplies `ENEMY_CLEAR_X_LEFT` by
   `WM_STAGE_SIZE` (record size) where the engine multiplies by the sub-pixel
   divisor. Both are 4, so the number is right by coincidence.
4. **The arc wrap guard gap** (§4.7) — latent today, live the moment arcs scale.
5. **`LEVELPKG_TRIG_SLOTS`'s inline comment still says `// 180`** where the
   expression yields 135.

---

## 12. Recommendation

**Implement `trigSpeed` as a ninth trigger column: one byte, a numerator over 4,
default 4, authored range 1–8.**

```
project JSON      "speed": 4                  (absent → migrate to 4)
package column    trigSpeed, 9th of 9         (135 → 120 trigger slots)
runtime           wvSpeed[WAVE_SLOTS] latched at arm
                  wmSpeed[MAX_OBJECTS] copied at spawn   (32 bytes free: fits)
calculation       scaled_v = (v * wmSpeed) >> 2
                  applied in wmLoadHeading and wmEnterStage ONLY
per-frame cost    zero
default           (v * 4) >> 2 == v  — bit-exact reproduction of today
```

Do it in this order, because the third item is the one that can bite:

1. **Schema + migration + editor + exporter**, defaulting everything to 4 and
   proving the generated bytes are unchanged. Nothing moves yet.
2. **Runtime scaling** at the two write sites, plus the preview mirror.
3. **Extend the assembly-time flight validator** to fly each program at each
   speed a trigger actually uses, and **add the missing arc wrap guard**. Until
   this exists, the build's "it leaves / it arrives / it never wraps" proofs do
   not cover scaled paths.

Clamp the scaled result so `|vx| ≤ 16` and `|vy| ≤ 32` quarter pixels, and
surface the firing-band consequence (§9) in the editor rather than discovering
it in play.

---

## Appendix — method

**Files inspected:** `AGENTS.md`; `src/movement_format.asm`, `src/movement.asm`,
`src/waves.asm`, `src/enemy.asm`, `src/ebullet.asm`, `src/dropper.asm`,
`src/token.asm`, `src/levelpkg.asm`, `src/level_package.asm`,
`src/encounter_format.asm`, `src/level1/wave_programs.asm`,
`src/level{1,2,3}/wave_encounters.asm`; `tools/level_editor/preview_ui.py`,
`movement_sim.py`, `movement_semantic.py`, `encounters_ui.py`, `contract_v2.py`,
`project_v6.py`, `validation_v6.py`, `export_v6.py`, `controller_v6.py`,
`encounter_library.v6.json`, `levels/*/level.v6.json`;
`tests/test_movement_pool.py`; reports `enemy-identity-authoring-model.md`,
`editor-regression-repair.md`, `variable-enemy-frames-and-roster.md`.

**Measurements performed:**

* `make build` — to read the authoritative package memory map
  (`$f736-$fb6d` = 8 × 135). Writes only `build/`; **no source or data file was
  modified**, so per the brief `make smoke` was not required and was not run.
* Parsed the live library and computed every authored leg's speed in
  quarter-pixels and px/frame (§4.4).
* `grep -ril "speed"` across all project JSON and all generated level `.asm` —
  **zero hits**, which is the proof that the chain breaks at the editor.
* Computed the trigger capacity for 8/9/10 columns from the derivation, and the
  135- vs 180-slot column addresses that diagnose the stale test.
* Ran `tests/test_movement_pool.py` (9 FAIL) and `tests/test_flight_paths.py`
  (1 FAIL) — both **pre-existing at the current clean HEAD**, diagnosed in §11.
* No VICE instance was left running; the two suites own and reap their own PIDs
  and `pgrep -fl x64sc` was clear afterwards.

**Git status:** clean, both before and after this audit.

```
$ git status --short
(no output)
```

HEAD is `0c50a46 More enemy types added to editor`.

**No commit, no push, and no `checkout`, `restore`, `reset`, `stash` or `clean`
was used at any point.** Nothing was implemented.
