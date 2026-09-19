# Level Editor v2, Phase 6A — Faithful Ordinary-Wave Simulator + Trajectory Preview

**Date:** 2026-09-19
**Scope:** `tools/level_editor/` plus two new test-only fixture recorders in `tests/`.
**Engine source changed:** **none.** `src/` and `Makefile` are untouched and both
production binaries are byte-identical.
**Result:** Delivered. **Zero authoritative mismatches** against the real 6502
across 1,660 directly-driven frames and two complete production-loop waves.

---

## 1. Starting state

```
HEAD        f9f688e  Level editor v2: add encounter authoring UI
branch      main
upstream    origin/main   (in sync, nothing ahead or behind)
status      clean
```

**The Phase 5B checkpoint was committed cleanly**, as `f9f688e`, with exactly the
six files the Phase 5B report listed (`controller_v6.py`, `editor.py`,
`encounters_ui.py`, the two new test files, and the report). Verified rather
than assumed. Nothing has been committed or pushed in this phase.

---

## 2. Engine movement audit

Everything below was read out of current source. Where a report or a comment
disagreed with the code, the code won and the disagreement is recorded in §3.

### Coordinate and fixed-point representation

| Thing | Representation | Source |
|---|---|---|
| X | **nine bits**, `logX` (low byte) + `logXHi` (bit 8) | `movement.asm` |
| Y | **eight bits**, `logY`, and it **wraps at 256** | `movement.asm` |
| Velocity | signed byte, **quarter pixels per frame** | `movement.asm` |
| Sub-pixel | `wmAccX`/`wmAccY`, 0..3, per object | `movement.asm` |
| Heading | `wmPhase`, 0..63, clockwise from **east**, +y **down** | `movement_format.asm` |

**These are VIC sprite coordinates, not an abstract space.** `renderer.asm:803`
copies `logX`/`logXHi` and `logY` straight into `schedX`/`schedXHi`/`schedY`,
which become the sprite registers. The display window is sprite X **24..343**
and rasters **55..247**, and a sprite is 24×21 with the stored coordinate at its
**top-left**.

### The quarter-pixel integration (`wmApplyVelocity`)

```
sum   = (acc + velocity) & 0xFF      ; clc/adc, the carry out is DISCARDED
acc   = sum & 3                      ; and #3   -- always positive
delta = s8(sum) >> 2                 ; cmp #$80 / ror, twice -- ARITHMETIC
```

The sign handling is the whole trick and `movement.asm` says why: for `sum = -5`
the arithmetic shift gives `-2` (floor, not truncation) and `-5 & 3 = 3`, so
`-2*4 + 3 = -5`. The remainder stays positive and the division floors. A logical
shift, or negate-shift-negate, would drift one pixel every four frames in one
direction and every curve in the game would visibly sag.

X then adds with an explicit carry/borrow into `logXHi`; **Y has no high byte at
all** and simply wraps.

### Update order (`wmTick`)

**Position first, then the primitive advances.** An object spawned with a
velocity already set moves by exactly that velocity on its first frame, and a
phase change takes effect on the frame *after* the one that requested it.
Advance-then-move would silently skip the first phase of every arc.

### The five primitives

| Kind | Behaviour |
|---|---|
| `STRAIGHT` | authored velocity for `frames` frames |
| `HOLD` | the same mechanism, kept distinct so a deliberate loiter is visible in the state |
| `ARC` | rotate heading **clockwise** one step every `framesPerStep` frames, `steps` times |
| `ARC_MIRROR` | identical but **anticlockwise** — it differs in which way it steps and *nothing else* |
| `EXIT` | terminal; timer 0, **velocity NOT reset**, runs until the despawn rule |

`AND #WM_HEAD_MASK` is the whole of "loops work": a turn of more than a full
circle wraps the heading and keeps going. There is no loop primitive, no orbit
centre and no angle accumulator.

**Arc timing, exactly.** `wmEnterStage` arms `steps` and `timer =
framesPerStep` and takes the entry heading's velocity **immediately**. Each
frame `wmArcStep` decrements the timer; at zero it rotates, reloads the timer
and decrements `steps`; at `steps == 0` it enters the next stage. So an arc of
N steps at f frames lasts **exactly N·f frames**, uses headings
`H, H+1, … H+N-1`, and the final rotation leaves the object on **`H+N`** —
which an `EXIT` after it inherits. That is what makes ARC → EXIT continuous.

### Entry heading and `WM_HEAD_CONT`

Byte 3 of an arc is its **entry heading**, or `$ff` (`WM_HEAD_CONT`) meaning
"continue from the heading already held". This is the determinism rule: a
program is a function of its own bytes, so the same program invoked by two
encounters with different launch headings flies the same path.

### Formation and spawn (`waveSpawnMember`, `waveRunInstance`)

* placement is a **repeated add**, not a multiply: `startX + index*xStep` in
  nine bits with carry, `startY + index*yStep` in eight **with wrap**;
* the launch heading is written to `wmPhase`, the program's first record to
  `wmStage`, the accumulators are zeroed, and then **the same `wmEnterStage`**
  every later stage uses is called — so a program's first stage cannot behave
  differently from the same stage mid-program;
* members are independent: `wmClearSlot` wipes every field on allocation, so a
  reused slot inherits nothing;
* `waveRunInstance` spawns when `wvTimer` reaches zero and then reloads it with
  the authored `interval`.

### Lifecycle, clamps and despawn (`enemyTick`)

There are **no position clamps on ordinary movement at all**. There are four
despawn rules, read *after* `wmTick` on the post-move position and the
post-advance velocity:

| Rule | Condition |
|---|---|
| left | `logXHi == 0 && logX < 4` **and still travelling left** |
| right | `logXHi != 0 && logX >= 88` (X ≥ 344) **and still travelling right** |
| bottom | `logY >= 248` — no direction test; gone either way |
| top | `logY < 35` **and still travelling up** |

The direction tests are load-bearing. Every wave in the game spawns above the
aperture and descends through the top line, so position alone would free every
enemy at birth. The left bound is also the **wrap guard**: `logX`/`logXHi` are
unsigned, so an enemy allowed past zero would borrow `logXHi` to `$ff` and
reappear 256 pixels to the right.

**Logical movement and rendering visibility are separate authorities** and the
simulator preserves that: `MemberFrame.visible` is a derived question
(admission band 55..226 *and* inside the display window horizontally), never a
constraint on the path. This is exactly the trap the brief names — the
protector-test mistake where impossible placement plus an X clamp made a valid
orbit look broken.

---

## 3. Where source and source disagreed

Two findings, both reported rather than "fixed", because the engine is
authoritative and nothing in it is wrong.

### 3.1 The assembly-time path proof is one heading step out of phase

`src/waves.asm` flies every authored pattern at build time to prove it leaves,
arrives and never wraps. Its inner loop **rotates the heading before** applying
the first `framesPerStep` frames (`waves.asm:238`), whereas the engine holds the
entry heading first and rotates at the end of the step. So the build-time proof
walks headings `H+1 … H+N` where the engine walks `H … H+N-1`.

This is harmless for what that proof asserts — it is a conservative check that a
path terminates and becomes visible, not a frame-exact model — but it means
**it must not be copied**, and it was not. The simulator follows
`src/movement.asm`. No change was made to `waves.asm`.

### 3.2 "The first member goes out next frame" — it goes out on the same frame

`src/waves.asm` sets `wvTimer = 1` when arming an instance, commented *"the
first member goes out next frame"*. That is what the timer means in isolation,
but `waveTick` calls `waveStartNext` **first** and only then walks the
instances, so the instance it just armed is run in the same frame: the timer is
decremented to zero immediately and member 0 is sent.

Caught by the production-loop fixture, not by reading. The simulator models
member k at frame **k·interval**, with frame 0 the frame the trigger became due.

---

## 4. Simulator architecture

`tools/level_editor/movement_sim.py` — **no Tkinter import anywhere**, and no
Tk type in the API.

```
s8(b)                       a byte read as signed
acc_step(acc, v)            -> (whole pixels, new remainder)   wmApplyVelocity
add_x9(lo, hi, delta)       -> (lo, hi)                        nine-bit carry
add_y8(y, delta)            -> y                               eight-bit wrap

trace_program(stages, x=, y=, heading=, frames=)  -> [MemberFrame]
    the interpreter ALONE: wmEnterStage then wmTick, no lifecycle

member_start(wave, m)       -> (lo, hi, y)                     the fan-out
simulate_member(...)        -> ([MemberFrame], exited)         + despawn rules
simulate_wave(project, wave)-> WaveSimulation                  a whole formation
simulate_trigger(project, i)-> WaveSimulation                  trigger->wave->program
preview_program(project, p) -> WaveSimulation                  a bare program
wave_by_id / resolve_program
SimulationError                                                 refusals
```

`MemberFrame` is a **frozen dataclass** of integers: `frame, member, spawned,
active, exited, x, y, stage_index, stage_kind, heading, vx, vy, acc_x, acc_y,
timer, steps`, plus a derived `visible` property. `WaveSimulation` carries
`frames` (per-frame tuples), `paths` (per-member histories), `spawn_frames`,
`all_exited` and `frame_count`.

**No floating point reaches simulated state.** The one use of `cos`/`sin` is
deriving the heading table once, with `floor(v + 0.5)` — Java's `Math.round`,
which is what KickAssembler uses — written out rather than delegated to Python's
`round()`, which is banker's rounding and would be a different table the day a
value landed exactly on `.5`. Everything after that is integer.

**Deliberate representation choice.** `wmStage` is a byte offset in the engine
and a **record index** in the simulator. They are the same cursor —
`wmEnterNext` advances by exactly `WM_STAGE_SIZE` and nothing else writes it —
and the equivalence test reconciles the two explicitly. A byte offset would be
an exporter concern leaking into a simulator.

### What is deliberately not modelled

* **Dropper/token/protector choreography.** `waveSpawnMember` calls
  `dropperLaunch` immediately after `wmEnterStage`, overwriting the mode,
  velocity and timer the wave just armed. The member never flies the authored
  path, so `simulate_trigger` **refuses** rather than drawing a fiction.
* **Pool pressure.** `waveRunInstance` *defers* a member when `objectAlloc`
  refuses, stretching a wave by however many frames the shared pool was busy —
  a property of the whole running game, not of the authored encounter.
  Simulated as an always-free pool, which is the authored intent.
* Collision, firing, animation and colour.

---

## 5. Fixture methodology

Two independent engine-grounded fixtures, deliberately different in kind.
**Neither adds anything to the engine**: there is no diagnostic build, no test
hook and no production source change.

### Fixture A — direct drive (`tests/movement_trace.py`)

The machine is stopped at a breakpoint **for the whole session**, so the game's
frame loop never advances and nothing can race what is measured. One pool slot
is set up by hand and left with `logActive = 0`. The **shipped** `wmEnterStage`
and `wmTick` are then called through the monitor, once per recorded frame, and
the slot's full authoritative state is dumped after each call.

Why not only watch real waves: **two of Level 1's four triggers are DROPPER
appearances**, so the `s` and `loop` programs are never flown by the running
game at all. Direct drive is the only way to ground all four production
programs — and it also reaches cases no authored content contains.

Synthetic programs are written into the **unused tail of the movement pool**
($f566–$f631, between the 52 authored bytes and the wave definitions), which
nothing reads.

The recorder reads the program bytes **back out of the machine** and stores them
in the fixture, so a fixture can never describe a program the engine did not
actually have loaded. It also dumps the heading table itself.

### Fixture B — the production loop (`tests/wave_formation_trace.py`)

Nothing is called by hand. The game boots to `worldProgress 0` (`boot="exact"`),
the director arms its own triggers, `waveSpawnMember` places its own formations
and `enemyTick` applies its own despawn rules. Sampled at the `gameFrame`
breakpoint — the top of a frame, and therefore the settled end of the one
before it, after `objectUpdateAll` moved everything and after `waveTick` spawned
anything new.

Spawns are attributed using the **director's own instance state** (`wvIndex`,
`wvDef`), not by matching positions — because position is the thing being
proved, and a matcher keyed on it could only ever agree with itself.

Both fixtures are regenerable and say so in their headers.

---

## 6. Equivalence results — the acceptance criterion

### All four production programs, direct drive

Every authoritative field compared every frame: X, Y, mode, stage cursor,
heading, both timers, both velocities and both sub-pixel remainders.

```
case                      kind        frames   X   Y  mode stage head timr step  vx  vy accX accY
sweep                     production    200    0   0     0     0    0    0    0   0   0    0    0
s                         production    200    0   0     0     0    0    0    0   0   0    0    0
linger                    production    230    0   0     0     0    0    0    0   0   0    0    0
loop                      production    320    0   0     0     0    0    0    0   0   0    0    0
mirror_wrap_down          synthetic     120    0   0     0     0    0    0    0   0   0    0    0
arc_wrap_up               synthetic     120    0   0     0     0    0    0    0   0   0    0    0
explicit_after_straight   synthetic     140    0   0     0     0    0    0    0   0   0    0    0
cont_chain                synthetic     140    0   0     0     0    0    0    0   0   0    0    0
hold_still                synthetic     110    0   0     0     0    0    0    0   0   0    0    0
negative_velocity         synthetic      80    0   0     0     0    0    0    0   0   0    0    0
```

**1,660 frames × 11 fields. Zero mismatches. Zero X, zero Y, zero heading, zero
stage-transition, zero exit-timing.**

The heading table the simulator derives is **byte-identical** to the table read
out of the running machine, VX and VY.

The canonical content is confirmed against HEAD: **4 programs, 13 stage records,
52 bytes, start offsets 0 / 12 / 24 / 40.**

The synthetic cases cover what the authored content cannot: `ARC_MIRROR`
wrapping **down** past heading 0 (Level 1's only mirrored arc stops exactly *on*
zero), `ARC` wrapping **up** past 63, an explicit entry heading contradicting
the heading already held, **CONT twice in a row**, a zero-velocity `HOLD`, and
negative velocities on both axes.

### The formation, in the production loop

```
wave    member  spawn frame           placement          life (frames)
sweep      0    384 (+  0, want +  0)   engine (0, 64)     sim (0, 64)      engine 182 sim 182
sweep      1    406 (+ 22, want + 22)   engine (0, 84)     sim (0, 84)      engine 168 sim 168
sweep      2    428 (+ 44, want + 44)   engine (0, 104)    sim (0, 104)     engine 155 sim 155
sweep      3    450 (+ 66, want + 66)   engine (0, 124)    sim (0, 124)     engine 142 sim 142
linger     0    720 (+  0, want +  0)   engine (120, 30)   sim (120, 30)    engine 206 sim 206
linger     1    746 (+ 26, want + 26)   engine (156, 30)   sim (156, 30)    engine 206 sim 206
linger     2    772 (+ 52, want + 52)   engine (192, 30)   sim (192, 30)    engine 206 sim 206
```

**Zero formation mismatches.** Every member is placed exactly where the
simulator puts it, at the authored interval; no member moves on the frame it
spawns; every frame of flight matches; and **the engine frees each member on
exactly the frame the simulator does**. The six Dropper-wave members are
identified by the director's instance state and deliberately not compared.

### Two defects this caught in the simulator

Both were found by the fixtures, not by reading, which is the point of having
them:

1. **Lifetime was one frame too long.** `enemyTick` moves and then applies the
   despawn rules in the same call, so a freed object never reaches the renderer
   on that frame. The path now ends on the last frame the object was still
   alive.
2. **Member 0's spawn frame** — see §3.2.

---

## 7. Preview UI

`tools/level_editor/preview_ui.py`, a `PreviewPanel` added as a **third column**
of the Phase 5B workspace. The timeline, the three tabs and the validation panel
are all unchanged; the window grew from 1180×760 to 1620×800. A column rather
than a notebook tab because the point of a preview is to be visible *while* the
stage being edited is visible.

**It draws only.** Every number comes out of `movement_sim`. Nothing in the
panel computes a position, an interval or a lifetime.

### Coordinate mapping

The canvas is the VIC's own space, `x ∈ [-8, 400]`, `y ∈ [0, 256]`, uniformly
scaled and centred. Verified numerically against the engine constants rather
than by eye:

| Drawn | World extent | Engine constant |
|---|---|---|
| visible playfield | X 24..344, Y 55..248 | display window / aperture |
| left margin | X −8..4 | `ENEMY_CLEAR_X_LEFT` = 4 |
| right margin | X 344..400 | `ENEMY_CLEAR_X_RIGHT` = 344 |
| bottom margin | Y 248..256 | `ENEMY_CLEAR_Y` = 248 |

Markers are drawn at the sprite **centre** (the engine stores the top-left), and
the selected member also gets its true 24×21 footprint as a dashed rectangle —
so "is it on screen yet" is answerable by eye. Off-screen travel is drawn
dimmed rather than cropped, and the despawn margins are shaded so an author can
see *why* a path ends where it does.

### Selection and controls

| Selection | Preview |
|---|---|
| trigger | the full authored chain — the most contextual |
| wave definition | that wave |
| movement program | flown alone, borrowing the launch heading and start position of the first wave that uses it, **and saying whose they are** |

Controls: **Play/Pause, Restart, ◀ / ▶ single-frame, a scrubber with a frame
readout, a speed selector (0.25× / 0.5× / 1× / 2× / 4×, 1× = PAL 20 ms), a paths
toggle and a member selector.** Selecting something **never starts playback** —
a selection that began animating would make the workspace jitter on every click.

Scrubbing and stepping **index the precomputed simulation**; nothing is
integrated from where a marker happens to be, so stepping backwards is exact.

### Diagnostics

`X, Y, stage index and kind, heading, on/off screen`, plus a developer line with
`vx/vy` in quarter pixels, the `acc_x/acc_y` sub-pixel remainders, and the arc
`timer`/`steps`. **No assembler address appears anywhere** — asserted by test.

### The Dropper limitation, stated not faked

A DROPPER trigger draws **no path at all**. The panel says:

> DROPPER triggers are not previewed in this phase.
>
> A Dropper is taken off its wave's authored path the instant it spawns —
> `src/dropper.asm` installs its own three-pass flight over the top of the
> aperture — so an ordinary-wave preview would show a trajectory the engine
> never flies.

### Invalid state

Phase 5B deliberately lets an author hold an invalid project while editing, so
the preview must survive it. It does not crash, does not guess and **does not
clamp**: it states the reason and draws nothing. Proved for a zero interval, a
zero count, a dangling movement-program reference, a launch heading out of
range, a program not ending in EXIT, a stage after EXIT, zero-length stages,
zero-step arcs and an out-of-range entry heading.

### Live editing

The panel recomputes from a cheap **signature** of the wave and its program, so
an ordinary refresh does not re-fly a 360-frame wave for nothing, but any
authored change to either is picked up immediately — including unsaved ones.
Proved for a member-count edit and a movement-stage edit, both ways through
undo.

---

## 8. A Phase 5B defect found and fixed

**Undo and redo did not refresh the encounter workspace.** Phase 5B hooked the
workspace refresh into the level-settings path only, so undoing an encounter
edit restored the model correctly and left the other window showing the state
*before* it. Phase 5B's own test only compared `controller.to_json()`, so it
never saw the stale widgets.

Fixed by moving the refresh into `_refresh_all`, which is the single path every
whole-document redraw goes through — `_restore_state` included:

```python
if self._encounters is not None and self._encounters.winfo_exists():
    self._encounters.refresh()
```

Found because the preview made it visible: an undone edit left the *trajectory*
stale, which is much harder to miss than a stale entry box.

---

## 9. Canonical preservation

Opened Level 1, then **played, paused, scrubbed, stepped, restarted, toggled
paths and selected every trigger, every wave definition and every movement
program**, then saved with no authored edit:

```
canonical sha256    : acef2dc09c6c366dae223dbde6e8702098d45176dde560140c710b8c72e1a2ec
dirty after use     : False
JSON byte-identical : True
ASM byte-identical  : 7/7   stage_charset, stage_config, stage_enemies,
                            stage_map, stage_turrets, wave_encounters, wave_programs
```

Binaries, before and after a full rebuild:

```
e726d430c5e9a5aeba9fe687d53f431d23a536a1df1ad99aa24531d3dd411918  build/shmup.prg
08ff411658468c2c9cab3cc942c752c6d8361787a0a4d3af401f28b5713d5828  build/level1.prg
```

**Identical.** And separately asserted by test: after all that transport, the
project is byte-for-byte unchanged and **not one undo step was pushed**.

---

## 10. Tests

### Editor suites — 34 files, all pass

| Suite | Result |
|---|---|
| 29 headless files (Phase 1–5B + 6A) | **all pass** |
| `test_v6_phase5a_gui.py` | All 55 passed |
| `test_editor_workshop_gui.py` | All 9 passed |
| `test_editor_asset_workflow_gui.py` | All 6 passed |
| `test_encounters_gui.py` (Phase 5B) | All 59 passed |
| **`test_movement_sim.py`** | **All 95 passed** |
| **`test_movement_sim_engine.py`** | **All 17 passed** |
| **`test_formation_sim_engine.py`** | **All 28 passed** |
| **`test_preview_gui.py`** | **All 61 passed** |

Phase 6A adds **201 checks**. Real-Tk suites run under `/usr/local/bin/python3`
(Tk 8.6), as established in Phase 5A.

`test_movement_sim.py` opens by stating what it *cannot* prove: it is Python
checking Python, so it can only show the simulator does what that file believes
the engine does. The engine-equivalence files are what settle it.

### Engine regressions

| Test | Result | Baseline |
|---|---|---|
| `test_wave_triggers` | **ALL PASS** | |
| `test_movement_pool` | **ALL PASS** | |
| `test_no_spawn_row` | **ALL PASS** | |
| `test_production` (pristine health gate) | **ALL PASS** | |
| `test_flight_paths` | 2 failures — `publishSkip`, `schedBuildDefer` | identical |
| `test_encounter_director` | 2 failures — same two counters | identical |
| `test_dropper_flight` | 1 failure — `schedBuildDefer` = 1 | identical |
| `test_token_encounter` | 1 failure — `schedBuildDefer` = 1 | identical |
| `test_ingress_egress` | 3 failures | identical count |
| `make proof420` | package builds clean; map `$e000-$f067`, signature `$fb70-$fb73` | |

**Every movement and director behavioural assertion passed.** `test_flight_paths`
matters most here — it is the file that proves the composable movement
vocabulary in the real loop, and all of its vocabulary assertions passed, which
corroborates the simulator independently of my own fixtures.

**The failures are the long-documented counter noise.** `schedBuildDefer` is
described in [renderer.asm:338](src/renderer.asm#L338) as a *saturating counter
of the deferral guard working*, not a fault, and `tests/test_enemy_fire.py:181`
already records that it "is deliberately not asserted" because it drifts under
harness breakpoint stepping. The counts match prior reports exactly:
`test-token-encounter-exact-boot-repair.md:129`,
`wave-contract-stage3-external-wave-data.md:201`,
`protector-guard-orbit-fix.md:126`, `e000-level-package-and-420-row-proof.md:320`,
and `scroll-speed-1px-restoration.md:155` for the director's pair.
`test_ingress_egress` is recorded at **3 failures, "identical on baseline"** in
`boss-transition-hud-regression.md:285`.

**These results are definitionally independent of this phase**: the engine
binary is byte-identical, `src/` and `Makefile` are unmodified, and no existing
file under `tests/` was touched. No assertion was weakened and no test was
edited to make anything pass.

One bookkeeping note for honesty: `test-harness-frame-accurate-boot-repair.md`
named `test_ingress_egress`'s behavioural failure as *"no enemy materialises
inside the playfield away from an edge"*, whereas the one seen now is *"all four
authored patterns ran during the window"*. The count is the same and that report
predates the absolute-trigger work, which stopped the trigger list repeating —
a sampling window that no longer spans all four encounters is the expected
consequence. Flagged, not fixed: it is engine-test scope, not this task's.

---

## 11. Manual verification

Every ordinary production wave was inspected, and the canvas display list was
exported and rendered so the drawing itself could be looked at rather than
inferred.

* **`sweep`** — four members enter from off-screen left at X 0, fly right, and
  the 16-step ARC bends them cleanly down and out through the bottom. Staggered
  by `yStep` 20.
* **`s`** — the S is unmistakable: three members descend, curve one way, then
  the other.
* **`linger`** — the straight leg, the visible HOLD, then the arc out.
* **`loop`** — three members fly diagonally down-right and each draws a **full
  circle** before continuing out the bottom. The 76-step arc really does go all
  the way round: **all 64 headings** appear in the path.

Measured rather than eyeballed:

```
ok  - sweep/s/linger/loop: path is continuous - no step exceeds the 1.5px/frame top speed  [max per-axis step 2px]
ok  - S-turn: curvature reverses EXACTLY once in the whole flight
ok  - S-turn: the CONT arc inherits heading 0 at the stage boundary  [frame 36, heading 0]
ok  - S-turn: it then holds that inherited heading for its framesPerStep before turning back
                                                        [boundary 36, first opposite turn 39, framesPerStep 3]
ok  - S-turn: heading sweeps 12 down to 0, then back up to 20
ok  - a mirrored arc curves the opposite way from a plain one  [ARC +1, MIRROR -1]
ok  - ...and they are mirror images in Y about the start line
ok  - one marker per live member, each exactly on its simulated position
ok  - playback keeps up and the UI stays responsive  [120 frames in 1.24s at 1x]
```

The curvature reversal is a nice detail: heading reaches 0 exactly at the CONT
boundary (frame 36), the second arc holds that **inherited** heading for its own
`framesPerStep`, and only then turns back — visible in the drawing and exact in
the numbers.

A Dropper trigger was also inspected: no path, no markers, and the explanation
rendered on the canvas.

---

## 12. Performance

| Wave | Members | Simulated frames |
|---|---|---|
| `sweep` | 4 | 208 |
| `s` | 3 | 232 |
| `linger` | 3 | 258 |
| `loop` | 3 | 357 |

A whole wave is precomputed when selected, which is what makes scrubbing
deterministic and cheap. The largest is under 400 frames — the entire Level 1
preview set is a few thousand integer steps, well under a frame of work.

Playback redraws **markers only**; the field and the paths stand between frames,
and nothing outside the panel is touched. Measured: **120 frames in 1.24 s at
1×** (i.e. tracking 50 Hz within timer granularity) with the UI responsive
throughout. A refresh whose signature is unchanged does not re-simulate at all,
so editing an unrelated field costs nothing.

---

## 13. Files

```
 M tools/level_editor/editor.py            +7     the Phase 5B undo-refresh fix
 M tools/level_editor/encounters_ui.py     +63/-6 preview pane + selection routing
?? tools/level_editor/movement_sim.py             the simulator (GUI-free)
?? tools/level_editor/preview_ui.py               the preview panel
?? tools/level_editor/test_movement_sim.py        95 checks
?? tools/level_editor/test_movement_sim_engine.py 17 checks, engine equivalence
?? tools/level_editor/test_formation_sim_engine.py 28 checks, formation equivalence
?? tools/level_editor/test_preview_gui.py         61 checks, real Tk
?? tools/level_editor/fixtures/                   the two recorded fixtures
?? tests/movement_trace.py                        TEST-ONLY fixture recorder
?? tests/wave_formation_trace.py                  TEST-ONLY fixture recorder
```

**Test-only engine fixture files:** `tests/movement_trace.py` and
`tests/wave_formation_trace.py`. Neither is imported by any test, neither is in
`make test`, and neither changes the engine — they drive the shipped routines
through the monitor and write JSON. **No production engine source change was
made, and none was needed.**

Fixture sizes: 312 KB and 473 KB.

---

## 14. Hygiene

* **Nothing committed, nothing pushed.** Working tree left dirty for review.
* VICE: `-console` only, owned PIDs only, no `pkill`/`killall`, no focus steal;
  `pgrep -fl x64sc` before and after every run; **none left behind**.
* GUI: every verification window was `withdraw()`n and destroyed. **No editor
  processes remain running.**
* `__pycache__` removed; the disposable `build/proof420` tree removed;
  transient captures written to the session scratchpad, not the repo.

```
build/                292K
tools/level_editor/   1.9M
tests/                548K
.                      11M
```

```
 M tools/level_editor/editor.py
 M tools/level_editor/encounters_ui.py
?? tests/movement_trace.py
?? tests/wave_formation_trace.py
?? tools/level_editor/fixtures/
?? tools/level_editor/movement_sim.py
?? tools/level_editor/preview_ui.py
?? tools/level_editor/test_formation_sim_engine.py
?? tools/level_editor/test_movement_sim.py
?? tools/level_editor/test_movement_sim_engine.py
?? tools/level_editor/test_preview_gui.py
```

---

## 15. Unresolved, and deferred

**Unresolved:** none that block the phase.

**Deferred special-encounter preview work**, all of it engine-owned behaviour
with its own source file:

* the **Dropper**'s three-pass flight across the top of the aperture, and its
  two entry sides (`src/dropper.asm`);
* the **token** encounter and its guard/protector orbits (`src/token.asm`);
* pool-pressure **deferral**, which stretches a wave when the shared pool is
  busy;
* the **boss**, which is not a wave at all.

Each can now be proved the same way this phase proved ordinary movement: the
two fixture recorders are general, and adding a Dropper case to
`tests/wave_formation_trace.py` is a few lines.

**Also worth a later look** (both flagged above, neither in scope here): the
build-time path proof in `src/waves.asm` being one heading step out of phase
with the engine, and `test_ingress_egress`'s sampling window no longer spanning
all four encounters.

**Phase 6A did not proceed into Dropper/protector preview or any later editor
phase.**

---

## 16. Acceptance

All thirty criteria in §26 of the brief are met. The two that carry the rest:

> **11. Python vs engine comparison has zero authoritative mismatches** — 1,660
> directly-driven frames across 11 fields, plus 7 complete members in the
> production loop. **Zero.**
>
> **28. No production gameplay semantics changed** — `src/` and `Makefile`
> untouched; `shmup.prg` and `level1.prg` byte-identical.

Nothing was committed or pushed.
