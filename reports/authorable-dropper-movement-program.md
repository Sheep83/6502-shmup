# 19656 — Authorable Dropper Movement Program

**Date:** 2026-09-30
**Scope:** implementation. A Dropper Trigger can now give **member 0** — the
Dropper itself — an authored Movement Program, flown by the ordinary movement
engine, while the escorts keep the Wave Definition and the legacy hard-coded
flight remains the default.
**Working tree:** dirty, preserved. No commit, no push. No campaign content
edited.

---

## 1. What changed, in one paragraph

A Dropper Trigger now owns one more decision: **what its Dropper flies.** Either
`TRIG_DROP_LEGACY` — the hard-coded three-pass flight in `src/dropper.asm`, which
is what every level authored before this column existed says and what the engine
does with a package that never mentions it — or a **Movement Program**, which
member 0 flies on the same interpreter every other enemy uses. The escorts,
members 1..N-1, are untouched in both cases: they fly the Wave Definition, keep
their own member indices and their own per-member offsets, and the member-0
"hole" is neither closed nor renumbered. Nothing about the one-Trigger
Dropper+escort model changed.

---

## 2. The encoding decision, and why

### 2.1 What was looked for first

The brief asked for a clean existing encoding before a new field. The repository
had already done most of that analysis, in `src/levelpkg.asm`'s own layout
comment, when colour, firing mode and speed each became a column:

> `trigFire` is a full eight-bit mask over member index — the validator says so
> in as many words — so it has no spare bits. `trigSide` and `trigSpecies` do
> have some, but a Dropper's entry side and a species' own animation row offset
> are not where a colour or a firing mode belongs […] Hiding a field in either is
> the kind of overload that is only ever found later and painfully.

For **this** field the case is stronger still, and for a reason that did not
apply to colour or firing mode:

* **There is no sub-byte encoding of it to hide.** The package carries a Dropper
  program as a **byte offset into the movement pool**, and the pool is
  `LEVELPKG_MOVE_MAX` = 256 bytes *precisely because* `wmStage` is one byte. The
  value needs all eight bits by construction. A colour fits in a nibble; a pool
  offset does not fit in anything smaller than the byte it already is.
* **`trigSide` was the one plausible host and it is the one field that stays
  live beside the new one.** LEFT/RIGHT is what the legacy flight reads, and the
  brief requires legacy to keep working. A trigger may need *both* answers at
  once — "legacy, from the right" — so the two cannot share a byte even in
  principle.

### 2.2 What was done

**A tenth Trigger column, `trigDropProg`.** Capacity falls from 120 authored
triggers to 108, derived at both ends and written down as a literal nowhere:

```
LEVELPKG_TRIG_RESERVATION = 1600 - 2 - 256 - 260        = 1082
LEVELPKG_TRIG_SLOTS       = floor(1082 / 10)            = 108
```

The reservation footprint is unchanged — `10 × 108 = 1080` of 1082, exactly as
`9 × 120 = 1080` was — so the package map is byte-for-byte the same shape:
`$f736-$fb6d`, two spare. Level 1 uses five triggers and level 2 uses seven; the
ceiling has never been within an order of magnitude of the content, which is why
the clearer encoding wins over the cheaper one.

### 2.3 The sentinel, and why `$FF` is safe rather than merely unlikely

`TRIG_DROP_LEGACY = $ff`. Zero could not be used: it is the **first program's
offset**. `$ff` is provably unreachable rather than conventionally reserved:

> Every program ends in a `WM_STAGE_SIZE`-byte `WM_EXIT` record inside a pool of
> `LEVELPKG_MOVE_MAX` bytes, so the highest offset a program can **start** at is
> `LEVELPKG_MOVE_MAX - WM_STAGE_SIZE` = 252. 253, 254 and 255 are unreachable by
> construction.

That is asserted at assembly time in **two** places, deliberately:

* `src/waves.asm` — the general claim, `TRIG_DROP_LEGACY > MOVE_MAX - STAGE_SIZE`.
  (It cannot live beside the constant in `src/encounter_format.asm`: that file
  imports nothing and KickAssembler resolves constants in *import order*, so a
  `.if` there fails with "reference to not yet defined symbol". The comment says
  so.)
* `src/level_package.asm` — the same claim checked against the **real offsets**
  this level emits, so a future pool layout that broke it fails in both places.

**Why not a separate flag column plus an offset column.** Two columns are two
ways to say one thing, and they admit the state "legacy, but here is a program
anyway" that nothing could interpret. One column with one unreachable value has
no such state.

---

## 3. Trigger record and schema changes

| Layer | Change |
|---|---|
| `src/levelpkg.asm` | `LEVELPKG_TRIG_COLS` 9 → **10**; slots 120 → **108**, still derived by `floor()`. Layout comment rewritten to name the tenth column and record why it could not borrow bits. |
| `src/encounter_format.asm` | `TRIG_DROP_LEGACY = $ff`, with the reasoning and a pointer to where the proof lives. |
| `src/waves.asm` | `.label waveTrigDropProg = LEVELPKG_TRIG + 9 * LEVELPKG_TRIG_SLOTS`; instance column `wvDropProg`; scratch `wvDropMode` + `WV_DROP_NONE/LEGACY/AUTHORED`. |
| `src/level_package.asm` | Tenth column emitted, resolving the authored **index** to a **byte offset** through `progAt` — exactly as a wave definition's tenth byte is. **Padding is `TRIG_DROP_LEGACY`, not zero**, for the same reason the speed column pads with `TRIG_SPEED_1X`: zero is a valid offset and would tell the engine that 100-odd nonexistent triggers fly program 0. |
| Generated data | `trigDropProg` list added to both levels' `wave_encounters.asm`, every entry `TRIG_DROP_LEGACY`. |
| `tools/level_editor/contract_v2.py` | `LEVELPKG_TRIG_COLS = 10`, `TRIG_DROP_LEGACY`, `DROPPER_MOVEMENT_LEGACY` label. |
| `tools/level_editor/project_v6.py` | `Trigger.dropper_program: str = None` + `dropper_is_legacy`. |

### Capacity is derived, and the test asserts the derivation

`tools/level_editor/test_trigger_speed.py` previously asserted the literal string
`"LEVELPKG_TRIG_COLS   = 9"` was present in `src/levelpkg.asm` — which made
*adding a column* a test failure rather than a capacity change, the precise
anti-pattern that deriving the slot count exists to avoid. It now asserts the two
properties that matter: the engine **derives** the slot count from the column
count, and the engine and the editor **agree** how many columns there are (the
count read out of the file, not typed in).

`tests/test_movement_pool.py` had a second copy of the column-name list; it now
reads `campaign_data.TRIG_COLS`, so there is one list and it is the one already
checked against the engine on import.

---

## 4. Backward compatibility

**Every existing project and every existing level is unchanged in meaning, and
most are unchanged byte for byte.**

* **No field, explicit `null`, and empty string all mean the legacy flight.** A
  project written before a Dropper could be given a path had exactly one Dropper
  trajectory, and opening it must not invent another.
* **`to_dict()` omits the key when it is `None`.** This is a deliberate
  asymmetry with `colour`/`fireMode`/`speed`, which *are* written resolved, and
  the reason is in the code: their `None` means "ask my definition" — an
  ambiguous state that must be made permanent on save or a later edit to the
  shared definition would retroactively change what an occurrence meant.
  `dropper_program`'s `None` means "the legacy flight": a concrete, stable answer
  nothing else in the document can change. There is nothing to make permanent, so
  the canonical `level.v6.json` documents are **still byte-for-byte JSON fixed
  points, unmigrated** — asserted in the new test.
* **The generated data diff is a pure addition.** Regenerating both levels
  produced exactly one new declaration per level and changed nothing else.
  (Level 2's `stage_sprites.asm` differs from a fresh export for an unrelated,
  pre-existing reason — that file is owned by `tools/sprite_export/import_spd.py`,
  not the level exporter — so it was deliberately left alone.)

---

## 5. The runtime seam

### 5.1 The decision is made once, where it can be made

`src/waves.asm`'s species block is the only place that decides an object **is**
the Dropper, so it is the only place that decides what the Dropper flies. It
records the answer in `wvDropMode` (`NONE` / `LEGACY` / `AUTHORED`), written
unconditionally through `Y` so the authored species stays in `A`:

```asm
    ldy #WV_DROP_NONE
    sty wvDropMode          ; the byte is scratch: the previous member's answer
    ldy wvInst              ; is still in it
    cmp lvlDropRow
    bne !species+
    lda wvIndex,y
    bne !escort+            ; members 1..N-1: escorts by decision
    ldy tkDropperLive
    bne !escort+            ; one is already out there
    ldy #1
    sty tkDropperLive
    ldy wvInst              ; ---- and WHAT it will fly, at the same instant
    lda wvDropProg,y
    cmp #TRIG_DROP_LEGACY
    beq !legacy+
    lda #WV_DROP_AUTHORED
    jmp !mode+
!legacy:
    lda #WV_DROP_LEGACY
!mode:
    sta wvDropMode
    lda lvlDropRow
```

`wvDropMode` is **scratch, not per-object**: its whole life is one call to
`waveSpawnMember`, and a per-object byte would cost `MAX_OBJECTS` to hold a value
that is dead by the time the routine returns.

### 5.2 The program is substituted *before* the single arming

```asm
    lda waveDefTable + 8,y
    sta wmPhase,x                   ; launch heading
    lda waveDefTable + 9,y
    sta wmStage,x                   ; the ESCORTS' first stage record...
    lda wvDropMode
    cmp #WV_DROP_AUTHORED
    bne !stage+
    ldy wvInst
    lda wvDropProg,y                ; ...or the DROPPER'S OWN, a pool offset
    sta wmStage,x
!stage:
    ...
    lda wvSpeed,y
    sta wmSpeed,x
    jsr wmEnterStage                ; ONE arming, whichever program it is
```

**Before, not after, and that is the whole of it.** Pointing `wmStage` elsewhere
and calling `wmEnterStage` a second time would also work, and would also mean an
object briefly armed with a path it never flies. A Dropper that is going to fly
its own program is simply never armed with the escorts'.

The speed is written before `wmEnterStage` for the reason it always was — the
stage's opening velocity is scaled on the way in — so an authored Dropper is
scaled by the same instruction as every other member.

### 5.3 Only a *legacy* Dropper is taken off the path

```asm
    lda wvDropMode
    beq !ordinary+                  ; not the Dropper at all
    cmp #WV_DROP_LEGACY
    bne !authored+
    ldy wvInst
    lda wvSide,y
    jsr dropperLaunch               ; position, velocity, height, side
    jmp !ordinary+
!authored:
    jsr dropperArmAuthored          ; the Dropper-ness WITHOUT the trajectory
!ordinary:
```

### 5.4 `dropperArmAuthored` — the other half of `dropperLaunch`

The split is the architectural point of the pass. `dropperLaunch` did two
separable jobs: it decided the **trajectory**, and it decided what being a
Dropper means regardless of trajectory. Only the second half belongs to an
authored Dropper, so only the second half is in the new entry point:

**Overridden:** the mover (`drMode = DROP_MODE_PROGRAM`); the sonar ping seed;
the firing permission, withdrawn exactly as before.
**Deliberately not overridden:** the position (the formation placed member 0 and
that is where it starts); `wmVX`/`wmVY` (the Dropper's own program's opening leg,
already scaled); `wmMode`, `wmTimer`, `wmStage` (the ordinary interpreter owns
them). A vertical velocity is now legitimate — an authored Dropper may climb and
dive, and `src/enemy.asm`'s top despawn edge reads `wmVY` to decide whether it is
leaving, which is the right answer for a path that means it.

### 5.5 The dispatch in `src/enemy.asm`

```asm
!dropper:
    lda drMode
    bne !dropperProgram+
    jsr dropperFly                  ; three passes above the aperture
    jmp !moved+
!dropperProgram:
    jsr wmTick                      ; its own authored path, on the engine
    jsr dropperPing                 ; ...and the sonar cue regardless
    jmp !moved+
```

**There is no second Dropper-specific interpreter.** An authored Dropper's arcs,
straights, timers, heading and trigger speed are the same ones every other enemy
gets; `src/movement.asm` learned nothing about Droppers. The only thing this file
does differently for it is the **ping**.

**`drMode` is module state, not per-object**, and that is consistent rather than
lazy: there is at most **one** live Dropper — `src/waves.asm`'s one-live interlock
guarantees it, and `drPassLeft`/`drPhase` have relied on that since the file was
written. `dropperInit` clears it alongside `tkDropperLive` in the level-scoped
reset, so a cold start and a package that says nothing both give the flight the
engine has always flown.

**Why the ping survives.** `dropperPing` is driven from the movement call for the
reason its own comment gives — that is what makes it stop by itself when the
Dropper dies or despawns — and an authored Dropper needs announcing exactly as
much as a legacy one. Finding it is the fight. This is the one narrowly documented
adaptation the brief allowed for.

### 5.6 Cost to the ordinary case

Five cycles per **spawn** (`ldy #0` / `sty wvDropMode`), plus one latch of
`wvDropProg` when a wave is armed. Per **frame**: one extra `lda`/`bne` for the
at-most-one live Dropper, and nothing at all for any other enemy. Ordinary waves
are unchanged in the hot path.

---

## 6. Legacy vs authored semantics

| | Legacy (`TRIG_DROP_LEGACY`) | Authored (a program) |
|---|---|---|
| Mover | `dropperFly` | `wmTick` |
| Start X | `DROP_ENTRY_LEFT` / `DROP_ENTRY_RIGHT` | the formation's **slot 0** |
| Start Y | `DROP_CENTRE_Y` | the formation's slot 0 |
| Vertical | `logY` written outright from the weave table; `wmVY` held at 0 | the integrator's, `wmVY` meaningful |
| Trigger speed | **ignored** (`wmApplyVelocity`, never `wmApplySpeed`) | **applies**, quarter-scale |
| Launch heading | not read | applies, through the definition's `wmPhase` |
| LEFT/RIGHT | chooses the entry edge | **not read** |
| Passes / turning points | three, then out | whatever the program says |
| Sonar ping | yes | yes |
| Fires | no | no |
| Token on death | yes | yes |

### Formation and start position

**Member 0 starts where the formation put it.** Forcing an authored-movement
Dropper to the legacy left/right edge would mean an authored path could never
choose its own entry — and the edge is a property of the hard-coded flight, not
of being a Dropper. **The escorts keep their indices and offsets**: member *k*
still spawns at `startX + k·xStep` on frame `k·interval`, and the member-0 hole is
not closed or renumbered.

### Speed semantics are intentional and were not "corrected"

Linear velocity scales; angular progression does not. An arc advances one heading
step every `frames_per_step` frames whatever the speed, while each frame's travel
is multiplied — so **a faster authored loop is a wider loop.** That is the
engine's documented behaviour for every wave and is deliberately not compensated
for a Dropper: the radius is a consequence the author can see in the preview and
tune, not a bug. Measured on the machine at 1× vs 2× over half a turn: X span
grows, Y span grows.

---

## 7. Build-time validation

The brief asked to reuse the existing Movement Program validation rather than
build a parallel one. `src/waves.asm` was restructured so there is exactly one
implementation of each proof:

1. **Structural checks moved out of the per-definition loop** and now walk **every
   program in the pool**. A program can be reached two ways now — a definition's
   tenth byte, or a trigger's `trigDropProg` — so checking from inside the
   definition loop would have left a Dropper-only program unchecked and checked a
   shared one once per definition using it. The pool is the thing being proved, so
   the pool is what is walked.
2. **Two `.function`s** carry the speed-dependent halves, returning `""` or the
   sentence to fail with (functions, not macros, so nothing is emitted and
   nothing depends on where they are invoked from):
   * `waveScaledBoundFault(prog, speed)` — the left-clearance wrap guard;
   * `waveFlightFault(prog, x0, y0, head, speed)` — the four flight properties
     (never wraps, reaches an edge, becomes visible, does so within
     `SIM_ENTER_BUDGET`).
3. **A new per-trigger pass** flies every authored Dropper path from the
   referenced definition's **member-0 start**, on the definition's heading, at
   **that trigger's speed**. Per trigger and not per program, because a Dropper
   flight is a function of three things the trigger owns or reaches — which
   program, at which speed, from which formation start — so two triggers naming
   one program at two speeds are two flights and both are flown. It also refuses
   an out-of-range index and refuses a **non-Dropper trigger naming a Dropper
   program**: the runtime reads the column only for a Dropper wave, so a path left
   behind by a species change would silently never be flown.

**No Dropper-specific bound and no Dropper-specific despawn rule**, because at run
time there is no Dropper-specific mover. A *legacy* Dropper is not flown here at
all; its trajectory is `src/dropper.asm`'s own, bounded by that file's own
assertions (which are unchanged).

The editor validator mirrors it: `trigger.dropper_program_missing` (dangling,
renamed or deleted reference) and `trigger.dropper_program_ignored` (set on a
non-Dropper) are both **errors**, so the author hears it in the editor rather than
from KickAssembler.

---

## 8. Escorts preserved

Asserted at three levels rather than argued:

* **Runtime** — every member > 0 is `lvlPlainRow`, on the escort program's stage
  offset, at the escort leg's velocity, at `startX + k·xStep`; an authored
  Dropper program reached nobody but member 0.
* **Preview** — the escorts' frame-by-frame paths are *identical* between the
  legacy and authored runs of the same trigger, and their spawn frames are still
  `k·interval`.
* **Editor** — selecting a Dropper path changes no wave definition at all
  (JSON-compared before and after) and leaves the trigger's `wave_definition`
  alone.

The one-live interlock still governs member 0 alone: a Dropper already alive gives
an **all-ordinary wave of the authored size**, every member on the wave
definition, with the authored Dropper program reaching nobody; and clearing the
flag mid-wave still promotes nobody.

---

## 9. LEFT/RIGHT UX

The field keeps the meaning it has always had and gains no second one.

* **Not a Dropper** — both controls disabled, as before.
* **Dropper, legacy** — both live. LEFT/RIGHT is the edge `src/dropper.asm`
  enters from.
* **Dropper, authored** — the movement control is live; **LEFT/RIGHT is disabled
  and labelled** "not used: the authored path decides where the Dropper enters".
  Disabled and explained, never silently repurposed.

The state follows an edit *immediately*, before the refresh it triggers, so
choosing an authored program greys LEFT/RIGHT out as the author watches — the same
thing the colour entry does when the mode goes Random.

---

## 10. Editor changes

* **One new control, `Dropper movement`**, directly under `Dropper side`, offering
  **`Legacy Dropper Flight`** first and then the level's movement programs.
  Legacy is an item in the list, not a blank or a checkbox beside it, because it
  is a choice of equal standing — the one every existing level made.
* **Not a second Wave Definition selector.** The formation, count, interval and
  escort path stay one choice made once above; this names a movement *program*.
* **The list is re-offered on every refresh**, like the wave definitions, so
  adding, renaming or deleting a program changes what a Dropper can select without
  reopening the workspace.
* **A reference that no longer resolves is shown as itself**, not silently
  replaced by Legacy: the validator reports it and the author needs to see which
  name it was.
* **The trigger list's last column** shows the entry side for a legacy Dropper and
  the program for an authored one — the side is not shown when nothing reads it.
* **Species changes are safe both ways.** Switching away from a Dropper clears the
  Dropper path along with the side, to the canonical neutral, because leaving a
  path on a Ring wave would fail the engine's build for a field the author can no
  longer see. Switching back gives a plain legacy Dropper.

### A production defect fixed on the way

`controller_v6.py` tested `if t.species != "DROPPER"` — a **literal name** — to
decide whether to reset `dropper_side`, while `validation_v6` has always asked
`identity_behaviour(...) == BEHAVIOUR_DROPPER`. An identity carrying
`BEHAVIOUR_DROPPER` under any other name therefore had its side reset on every
edit, and the two authorities disagreed. Both now ask the behaviour.
`movement_sim.simulate_trigger` had the same literal test and is likewise fixed
(`trigger_is_dropper`).

---

## 11. Preview changes and cache keys

### Both modes are drawn; the refusal is gone

`simulate_trigger` used to refuse a Dropper outright, and that was **honest while
a Dropper had no path of its own** — `src/waves.asm` took it off the escorts' path
immediately, so an ordinary-wave picture was a fiction. Now:

* **Legacy** — `simulate_legacy_dropper()` flies `src/dropper.asm`'s actual
  trajectory: entry edge, `DROP_CENTRE_Y` plus the weave table, the crossing
  velocity, the turning points, the passes, and `src/enemy.asm`'s ordinary despawn
  rules. Thirty lines, and it is correct. The alternative — draw member 0 on the
  escorts' wave and be done — would be a lie the author could act on.
  It **ignores trigger speed**, because the engine does.
* **Authored** — member 0 on its own program, from the formation's slot 0, at the
  trigger's speed and the definition's heading; members 1..N-1 on the escort wave.

`simulate_wave` gained one optional `member0` callable. It is one override for one
member; the rest of the routine does not know it happened, which is what keeps the
escorts' indices, spawn frames and offsets exactly as the definition gives them.

**The legacy constants are parsed from `src/dropper.asm`, not retyped.**
`contract_v2`'s convention (a literal beside a source comment) is right for numbers
nobody moves; entry edges, turning points, crossing speed and weave amplitude are
gameplay tuning values that have each been changed at least once, and a preview
quietly drawing last month's amplitude is exactly the kind of wrong a preview must
not be. `asm_decl` is the same reader the importer uses.

### The cache signature

The previous pass's `resolved_speed` fix is **intact and re-asserted**. Added, by
the same rule — *name every trigger field the simulation reads*:

* `dropper_program` — whether member 0 is on the legacy trajectory or a program,
  and which one. Without it, switching Legacy ↔ authored would leave the previous
  picture on the canvas: the signature would compare equal and `_rebuild()` would
  never run.
* `dropper_side` — the legacy entry edge, which changes member 0's whole path. It
  was not needed before because a Dropper could not be previewed at all.
* **the Dropper program's own stages and segments** — a second program the
  simulation reads, so editing a stage of it invalidates the cache exactly as
  editing the escorts' does.

Each of the five is asserted to change the signature, and returning to Legacy is
asserted to change it back.

---

## 12. Token lifecycle and intrinsic behaviour

Everything intrinsic to *being* the Dropper is unchanged, and none of it was
reached by the movement change:

identity and artwork · the one-live interlock · the member-0 contract · token
spawning on destruction · destruction (not escape) being the requirement ·
death/despawn cleanup and interlock release · the saturating diagnostics ·
collision and damage · scoring · state flags.

The token hook in `src/enemy.asm`'s `!release:` path tests the **species** and
reads `logX`/`logY` — it never referenced the trajectory, so it needed no
adaptation. Proved on the machine: an authored Dropper killed through the engine's
own damage path releases the interlock and **starts the token encounter**
(`tkStarted` increments), exactly as a legacy one does. Verified with
`gameOverrun == 0` across the flight and the death.

**Fire mask:** not redesigned. Bit 0 still belongs to the Dropper and is still
inert — `dropperArmAuthored` withdraws `enyFire` exactly as `dropperLaunch` does,
so an authored path does not implicitly promote the Dropper to a normal firing
enemy. The member-index numbering is unchanged.

**HP:** not touched. `ENEMY_MAX_HP` for every enemy including the Dropper, as
before. Per-identity Dropper HP remains the next independent feature.

---

## 13. Tests

### New

**`tests/test_dropper_movement_program.py`** — the runtime contract, 10 sections,
one short VICE per section, exact owned PIDs. The discriminator is **`wmStage` at
activation**: `src/waves.asm` points it at the Dropper's own program before the
single `wmEnterStage`, and the legacy path leaves it on the *escorts'* program
(`dropperLaunch` overrides position and velocity, never the cursor). So the offset
says which of the two happened, at the instant the object exists.

1. legacy is the default and is unchanged (edge, centreline, `DROP_VX`, escort
   stage cursor, `drMode = 0`)
2. authored: member 0 on its own program, at the formation's slot 0, not at any
   legacy edge; escorts on the wave at their own offsets; the Dropper still silent
3. `wmTick` moves it, frame by frame, down-left where the legacy flight only goes
   sideways at a fixed height; the weave never touches its Y; the ping still runs
4. a one-member authored trigger: one Dropper, no invented escort
5. already-live → all-ordinary wave of the authored size, the authored program
   reaching nobody; and (5b) the flag freed mid-wave promotes nobody
6. trigger speed scales the authored Dropper at 1× / 1.5× / 2×, and the escorts
   by the same trigger
7. a faster authored arc sweeps a **wider** span in X and in Y
8. LEFT/RIGHT moves a legacy Dropper and leaves an authored one identical;
   (8b) legacy still ignores trigger speed while still carrying it for its escorts
9. two launch headings give two different opening velocities, each the engine's own
   heading-table entry
10. an authored Dropper's death releases the interlock and starts the token
    encounter

**`tools/level_editor/test_dropper_movement.py`** — schema, migration, controller,
validation, export/import/bytes, capacity, preview, cache, widgets. **95 checks,
all pass.** Fixtures are synthetic (`fixtures_v6`); the committed documents and
the shared library are byte-compared at the end.

### Updated, and why each was wrong rather than inconvenient

* **`tests/test_dropper_flight.py`** — bulk-read the flight state and indexed it
  **positionally** (`dr[4]` = `drLaunched`). `drMode` landed between `drPing` and
  `drLaunched`, every later field shifted, and the read went on reporting `drMode`
  as the launch counter: a Dropper launched on every frame and the test believed
  none ever had. Now indexed **by symbol** through a name→offset map, so the next
  field costs nothing and cannot silently re-point an existing one. The
  companion contiguity check asserted `drPinged == drPassLeft + 6` — a picture of
  the block, not a property of it; it now asserts the block is one run with no
  gaps, whatever its length.
* **`tools/level_editor/test_movement_sim.py`**, **`test_preview_gui.py`**,
  **`test_v6_phase6a1_hotfixes.py`** — asserted a Dropper trigger is **refused** a
  preview. That contract is exactly what this pass replaces. They now assert
  member 0 is drawn and is *not* on the escorts' path, and that the escorts are.
  (`test_v6_phase6a1_hotfixes`'s real purpose — the workspace-geometry regression
  from a multi-line message — is intact and still passes.)
* **`tools/level_editor/test_trigger_speed.py`** — the frozen `= 9` literal,
  replaced by the derivation property (§3).
* **`tests/test_movement_pool.py`**, **`tests/campaign_data.py`**,
  **`tests/synth.py`** — column list extended in one place; `synth.write_trigger`
  and `only_trigger` gained `drop_prog`, defaulting to legacy, with the sentinel
  read from `src/encounter_format.asm`.

No test was weakened, and no authored level was edited to make one pass. Every
new fixture is synthetic and installed into package RAM only.

---

## 14. Results

### Focused: the new suites

| Suite | Result |
|---|---|
| `tests/test_dropper_movement_program.py` (runtime, 10 sections, 20 VICE) | **ALL PASS** |
| `tools/level_editor/test_dropper_movement.py` (schema→bytes→preview→widgets) | **95 checks, all pass** |
| `tools/level_editor/acceptance_dropper_movement.py` (real editor, real Tk) | **37 steps, all clear** |

The runtime discrimination, from one wave with **one authored byte** different:

```
LEGACY    mbr 0  DROPPER  stage 76   x=0    y=88  vx=+12  vy=0  drMode=0
          mbr 1  escort   stage 76   x=148  y=60  vx=+6   vy=0
          mbr 2  escort   stage 76   x=176  y=60  vx=+6   vy=0
          mbr 3  escort   stage 76   x=204  y=60  vx=+6   vy=0

AUTHORED  mbr 0  DROPPER  stage 84   x=120  y=60  vx=-5   vy=+4 drMode=1
          mbr 1  escort   stage 76   x=148  y=60  vx=+6   vy=0
          mbr 2  escort   stage 76   x=176  y=60  vx=+6   vy=0
          mbr 3  escort   stage 76   x=204  y=60  vx=+6   vy=0
```

Member 0 moves off the screen edge and the weave centreline onto the formation's
own slot 0, with its own program's velocity and its own stage cursor, while the
escorts are **byte-for-byte unchanged** at 148/176/204 on the escort program.

Speed scaling, exact at all three points, Dropper and escorts through the same
instruction:

| Trigger speed | authored Dropper leg | escort leg |
|---|---|---|
| 4/4 (1.00×) | (−5, +4) | (+6, 0) |
| 6/4 (1.50×) | (−7, +6) | (+9, 0) |
| 8/4 (2.00×) | (−10, +8) | (+12, 0) |

Arc widening, over the 72 frames both speeds survived:
**1× span (48, 76) → 2× span (97, 153)** — a faster authored loop is a wider
loop, roughly doubled in both axes, which is the intended semantics.

LEFT/RIGHT ownership: legacy `LEFT (x=0, vx=+12)` / `RIGHT (x=343, vx=−12)`;
authored `LEFT (120, −5)` / `RIGHT (120, −5)` — identical, the side reaching
nothing. Legacy still crosses at `DROP_VX` at every trigger speed while still
carrying that speed for its escorts.

Launch heading: heading 0 → (+6, 0), heading 16 → (0, +6), each the engine's own
heading-table entry.

Token lifecycle under an authored path: the Dropper holds the interlock while
alive, releases it on death (`tkDropperLive 1 → 0`), and **starts the encounter**
(`tkStarted 0 → 1`), with `gameOverrun` zero throughout.

### Build-time validation, proved by negative test

Four deliberately invalid trees, each assembled in an isolated copy, each
rejected with the right sentence:

| Planted fault | Build result |
|---|---|
| Dropper trigger names program index 99 | `a trigger names a Dropper movement program that does not exist` |
| A **Ring** trigger names a real program | `a trigger that is not a Dropper's names a Dropper movement program: …would never be flown` |
| Dropper path that never reaches an edge | `a pattern never reaches any despawn edge inside SIM_FRAME_BUDGET frames` |
| Leg `vx = −14`: legal at 1×, illegal at the trigger's own 1.25× | `a straight or hold leg, at a speed some trigger asks for, moves in X fast enough to step over the left clearance window and wrap` |

The last one is the important one: it proves the new per-trigger pass really
flies Dropper paths **at the speed that trigger asks for**, not at 1×.

A diagnostic-sentence diff against HEAD confirms **no check was lost** in the
validator refactor: HEAD stated 42 sentences, the current file states 46 — the
same 42 plus four new ones.

### `make smoke`

**PASS.** 4,081 frames observed; `gameOverrun`, `scrollLate`, `edgeLate`,
`statOverflow`, `statPageMismatch`, `statPtrMismatch`, `objDoubleFree`,
`objAllocFail`, `clipPoolFull`, `publishSkip`, `schedBuildDefer` and `statLate`
**all zero**. ENGINE HEALTH: PASS. ROUTINE REGRESSION: PASS.

### The editor suite

All 45 files pass, including the three whose Dropper expectations this pass
inverted (§13).

### Manual Tk acceptance

`tools/level_editor/acceptance_dropper_movement.py` constructs the **real**
`editor.LevelEditor` and the real `EncounterWorkspace` on real Tk 8.6, windows
withdrawn so no focus is stolen, and walks the brief's sequence through actual
widget callbacks: workspace opens → Legacy selected with both controls live and
member 0 on the legacy trajectory → select `sweep`: stored, LEFT/RIGHT disabled
and labelled "not used…", preview changes to member 0 on ARC/STRAIGHT with the
escorts' paths identical to the legacy preview → speed 2.00× updates the preview
→ heading 0→16 updates it → save/reload preserves the selection → species to
`RING_3` clears the path and disables the control with an explanation → back to
Dropper gives a plain legacy Dropper, both controls live → four rounds of
Dropper↔ordinary selection leave the control correct → clean close. Both
committed documents byte-identical afterwards.

**STATED PRECISELY: this drove the real GUI PROGRAMMATICALLY. It is not a human
looking at pixels.** `AGENTS.md` rule 2 makes manual visual output authoritative,
so a human visual pass is still required and the script says so in its own
output. What it does establish is the class of fault the brief was worried about
— that the real application constructs, that every control is in the state it
should be in, and that nothing raises across repeated selection.

### The full runtime suite: 12 pre-existing failures, none from this change

The 36-file runtime suite reports 12 failures. **Every one was measured to be
independent of this change**, and the first run was partly my own fault:

* **3 were CPU contention of my own making** — `boss_hud_transition`,
  `ingress_egress`, `player_death`. They pass when re-run serially on an idle
  machine. `tests/harness.py:350` documents the warp boot loop as **wall-clock
  sensitive** ("per wall-clock second…the parked ship can lose every life"), and
  I was running `make build` and the Tk suite alongside it. My error, the same
  class as rebuilding a binary mid-run.
* **4 fail at pristine HEAD with the documented `gsState = 3` boot flake** —
  `bank2_arena`, `boss`, `player_ship`, `sfx`. `gsState 3` is `GS_INITIALS`, and
  that comment names `test_player_ship` as the test which hits it.
* **5 fail at pristine HEAD with byte-identical failing checks** —
  `clip_scratch`, `encounter_director`, `enemy_fire`, `turret_arming`,
  `turret_regression`.

Method: a pristine `HEAD` tree was extracted with `git archive` into the
scratchpad (no destructive git operation on the working tree), built, and the
failures run against it serially on an idle machine — HEAD engine with HEAD
tests. `encounter_director` is the one that exercises the wave director this pass
modified; it fails at HEAD with the same two checks, so the director is clear.

`test_enemy_fire` is worth naming: line 55 is
`AUTHORED_MASKS = [0b0101, 0b0010, 0b0101, 0b0000]  # sweep, s-turn, linger, loop`
— a frozen snapshot of a Level 1 composition that no longer exists (it now
authors `[63, 7, 7, 15, 7]`), byte-identical at HEAD. That is the uncovered tail
of the earlier de-freezing pass, and **deliberately not fixed here**: repairing
five unrelated frozen suites is its own bounded task, not something to fold into
this one.

Every runtime test that covers what this pass changed **passes**:
`dropper_escort_contract`, `dropper_flight`, `movement_pool`, `trigger_speed`,
`wave_triggers`, `wave_colour_mode`, `no_spawn_row`, `species_order`,
`token_encounter`, `level_assets`, `square_species`, `campaign`, `production`,
`flight_paths`, `lifecycle`.

### VICE hygiene

Exact owned PIDs throughout, every launch reaped on success and failure, no broad
`pkill`, `-console` only, no focus stolen. `pgrep -f x64sc` returns **0** at the
end of every run reported here.

---

## 15. Files changed

**Engine**
`src/levelpkg.asm` · `src/encounter_format.asm` · `src/waves.asm` ·
`src/dropper.asm` · `src/enemy.asm` · `src/level_package.asm`

**Generated data** (regenerated by the exporter, pure addition)
`src/level1/wave_encounters.asm` · `src/level2/wave_encounters.asm`

**Editor**
`contract_v2.py` · `project_v6.py` · `controller_v6.py` · `validation_v6.py` ·
`export_v6.py` · `import_engine_v6.py` · `encounters_ui.py` · `movement_sim.py` ·
`preview_ui.py`

**Tests and acceptance**
new: `tests/test_dropper_movement_program.py` ·
`tools/level_editor/test_dropper_movement.py` ·
`tools/level_editor/acceptance_dropper_movement.py`
updated: `tests/test_dropper_flight.py` · `tests/test_movement_pool.py` ·
`tests/campaign_data.py` · `tests/synth.py` ·
`tools/level_editor/test_movement_sim.py` · `test_preview_gui.py` ·
`test_trigger_speed.py` · `test_v6_phase6a1_hotfixes.py`

Also present in the dirty tree from earlier tasks and untouched by this one:
`src/level_assets.asm`, `tests/harness.py`, `tests/test_level_assets.py`,
`tests/test_square_species.py`, `tests/test_token_encounter.py`,
`tests/test_dropper_escort_contract.py`, four earlier reports.

---

## 16. Limitations and what is next

* **Per-identity / lower Dropper HP is not implemented.** Out of scope by
  instruction; every enemy including the Dropper is still `ENEMY_MAX_HP`. It is
  the next independent gameplay/data feature and is unaffected by anything here.
* **The legacy path is still present and is still the default.** Deleting it was
  explicitly out of scope; nothing in the campaign selects an authored path yet.
* **The Dropper's launch heading is the wave definition's.** There is no separate
  heading field: the trigger owns one heading, by way of the definition it
  references, and the Dropper takes it exactly as the escorts do. If a Dropper
  ever needs a heading independent of its escorts, that is a new field and a new
  decision.
* **The Dropper member index is not configurable**, by instruction. Member 0 is
  the Dropper.
* **`src/enemy.asm:168`** still carries a stale `.error` string naming the retired
  `enemyAnimShape`; reported in an earlier pass, still not fixed, still harmless.
* **The escort identity is not selectable** — escorts are `lvlPlainRow`. Out of
  scope.
* **A human visual pass is still owed.** The Tk acceptance is programmatic; see
  §14 and `AGENTS.md` rule 2.
* **Five unrelated runtime suites are frozen against an older Level 1**
  (`clip_scratch`, `encounter_director`, `enemy_fire`, `turret_arming`,
  `turret_regression`) and four more are exposed to the documented warp-boot
  flake. All nine fail at HEAD, independently of this change; they are the
  remaining tail of the de-freezing work and want their own bounded pass.
