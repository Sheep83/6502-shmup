# Trigger-Owned Fire Behaviour, and the Enemy-Projectile Cap Audit

**Part A done: firing mode has moved from the reusable Wave Definition to the Wave Trigger. A definition now owns formation only — its byte 7 is reserved and zero.**

**Part B: the cap is NOT 2. `EBULLET_MAX` has been 3 since the day it was written. It was not changed. But the measurement explains the recollection, and the finding matters more than the constant.**

**No commit, no push, and no destructive Git operation was run against the dirty tree.**

---

## PART A — Fire behaviour moved to Wave Triggers

### 1. What the representation was

Firing was split across three places, and only one of them was wrong:

| authority | where | says |
|---|---|---|
| `trigFire` | **trigger** column 4, an 8-bit mask over member index | **which** members shoot |
| `enemyFireModeTab` | `src/enemy.asm`, per species | whether the species **can** shoot, and its default mode |
| `WAVEDEF_FIRE_BITS` | **wave definition** byte 7, bits 4-5 | **how** they aim — `$10` = AIMED |

The mask was already a trigger field. Only the mode was on the definition, which
made every occurrence of one reusable formation attack identically.

### 2. Final ownership

| | owns |
|---|---|
| **Wave Definition** | count, interval, spawn X/Y, per-member X/Y step, launch heading, movement program. **Nothing about colour or firing.** |
| **Wave Trigger** | worldProgress, definition, species, Dropper side, **fire mask**, **fire mode**, colour mode, fixed colour |

`resolved_fire_mode` sits beside `fire_mask` on the trigger, so the two halves of
"how does this appearance attack" are now one place.

### 3. Encoding, and why not a borrowed bit

**An eighth trigger column, `trigFireMode`**, carrying `TRIG_FIRE_DOWN` (0) or
`TRIG_FIRE_AIMED` (1).

I checked for a spare bit before growing the record, because that is the cheaper
answer when it is available:

* **`trigFire` has none.** It is a full eight-bit mask and the validator says so
  in as many words — *"the fire mask is one byte: member N cannot be
  addressed"*. Every bit is reachable by a real member.
* **`trigSide` has seven free bits**, and `trigSpecies` several. Neither is where
  a firing mode belongs, and a species value is an *animation row offset* that
  grows as species are added — `SPECIES_SQUARE` is already 16, so a fourth
  species reaches 24 and a fifth 32. Hiding a flag above it is a trap with a
  date on it.
* **The trigger colour byte has bits 5-7 free.** Also rejected: it is the colour
  byte, and putting the firing mode in it recreates exactly the muddle this task
  exists to undo.

So the list grew a real column with a real name.

**"No firing" needed no value.** It is an empty `trigFire` mask, which is how it
has always been said and is still the only way to say it. Inventing a third mode
for it would have created two ways to express one thing.

**What it cost.** The slot count is derived from the column count, so eight
columns take the authored-trigger ceiling from **154 to 135**. Level 1 uses 12,
level 2 uses 7. `contract_v2` derives the same number the assembler does, and a
test asserts they agree.

**The definition's byte 7 is now reserved and must be zero**, with a build-time
guard:

```asm
.if (def.get(WAVEDEF_RESERVED_7) != 0) {
    .error "a wave definition's reserved byte 7 is not zero -- colour and firing mode belong to the trigger now"
}
```

I deliberately did **not** shrink the record to nine bytes. `waveDefBase` forms
`def * 10` as `n*8 + n*2` in a single byte; dropping to nine moves the heading
and program index, changes that arithmetic, and touches the exporter, the
package emitter and every `waveDefTable + n` offset past byte 7 — a lot of blast
radius to reclaim 26 bytes. Recorded as a deliberate trade, not an oversight.

### 4. Runtime

The mode is **latched onto the wave instance when the wave is armed**, beside
the mask, the species and the side, and for the identical reason — the trigger
cursor has moved on by the time the members go out:

```asm
    lda waveTrigFireMode,y
    sta wvFireMode,x                    // per INSTANCE, never per definition
```

and at spawn, the three authorities resolve in the same order they always did:

```asm
    ldy wvInst
    lda wvFireMode,y
    cmp #TRIG_FIRE_AIMED
    bne !mayFire+
    lda #ENEMY_FIRE_AIMED
    sta enyFire,x
```

**Cadence is untouched.** `WAVE_FIRE_PERIOD` (48) and `TURRET_FIRE_INTERVAL`
(100) were not altered, and neither were the firing bands. Only the *mode*
moved; nothing about *how often* anything fires changed.

Two new assembly-time proofs: a mode outside the known set is refused, and an
appearance that sets a mode while its fire mask is empty is refused — that is
authored data nobody can ever read, and the editor warns about it in red before
the build does.

### 5. Editor

**Wave Definitions pane**: the "firing" combobox is gone. Remaining: count,
interval, start X/Y, X/Y step, heading, movement program. Formation only.

**Trigger pane**: gained "fire mode", placed directly under the fire-mask
checkboxes because the two are one question asked twice. When the mask is empty
the note beside it turns red and says so.

**Model**: `Trigger.fire_mode` (`None` = not authored yet, resolved by
migration); `WaveDefinition.fire_mode` removed, replaced by a migration-only
`legacy_fire_mode` that is read from JSON and never written back.

**Validation**: `wavedef.fire_mode` removed; `trigger.fire_mode` and
`trigger.fire_mode_unused` added.

### 6. Migration, and what it preserves

`resolve_trigger_encounter_fields` (the colour migration, generalised) copies
each definition's colour, colour mode **and firing mode** onto the triggers that
reference it, once, on every load path. Idempotent; never overwrites a trigger
that already has a value; does nothing until the vocabulary is present.

Measured on the committed levels before saving anything:

```
level 1   row  20  sweep   AIMED  mask [0,2]      <- the only AIMED appearance
          row  52  s       DOWN   mask [1]
          row  90  linger  DOWN   mask [0,2]
          ... nine more, all DOWN, masks unchanged
level 2   row  20  sweep   AIMED  mask [0,2]
          ... six more, all DOWN
```

**Nothing about Level 1 or Level 2 gameplay changed.** Every mask is
byte-identical, and the single AIMED appearance in each level is the one that
was AIMED before.

#### The known Level 2 `sweep` AIMED/DOWN state

Reported rather than quietly folded in, as asked. The current authoritative
state — established by the previous task, when the eighth-column change forced a
regeneration — is that **level 2's `sweep` is AIMED in both the project and the
generated package**, matching level 1 and matching the shared library. This task
found that state, migrated it faithfully onto level 2's row-20 trigger, and
changed nothing about it. The older generated DOWN byte is long gone and was not
resurrected. If level 2's opening sweep should *not* be aimed, that is now a
one-trigger edit in the editor rather than a definition-wide one — which is
arguably the best argument for this refactor, but it is still your decision and
I have not made it.

### 7. Generated data

```diff
-//   7 firing     bits 4-5 the firing mode; the rest reserved...
+//   7 reserved   always zero. Enemy colour and firing mode are
+//                TRIGGER fields, not definition fields
-    16,                       // firing mode AIMED
+    0,                        // reserved -- must be zero

+.var trigFireMode = List().add(TRIG_FIRE_AIMED, TRIG_FIRE_DOWN, TRIG_FIRE_DOWN, ...)
```

Symbolic, so the source says `TRIG_FIRE_AIMED` rather than `1`. Deterministic:
exporting twice is byte-identical, and a change-and-revert cycle returns all six
generated files byte-identical.

---

## PART B — The enemy-projectile cap: authoritative audit

### The eight questions

**1. What is the maximum number of simultaneously active enemy projectiles?**
**Three.** `EBULLET_MAX = 3`, `src/ebullet.asm:28`.

**2. Where is the limit defined?** One constant, enforced in one place —
`ebulletSpawnBody`:

```asm
    lda ebCount
    cmp #EBULLET_MAX
    bcc !room+
```

**3. What kind of limit is it?** A **dedicated logical projectile cap**, and
nothing else. It is not a pool reservation, not a renderer or mux limit, and not
a collision-array size. A projectile is an ordinary object from the shared
16-slot pool; `src/ebullet.asm` reads and writes no VIC register at all, and
there is no reserved hardware sprite. `ebCount` is a plain counter incremented
at spawn and decremented in `ebulletRetire`, guarded against underflow.

**4. Do turrets and moving enemies share it?** **Yes — completely.** Both go
through the same two entry points into one body:

```
src/turrets.asm:1731  jsr ebulletSpawn        (turrets: always aimed)
src/waves.asm:1087    jsr ebulletSpawnDown    (wave members: straight down)
src/waves.asm:1090    jsr ebulletSpawn        (wave members: aimed)
```

One cap, one allocator, one lifecycle. Three turret bolts in flight leave no
room for an enemy's.

**5. Logical or rendered?** **Logical.** `ebCount` changes only at spawn and
retire; nothing about admission, clipping or rendering touches it. A projectile
clipped at the bottom edge, or one the mux could not fit this frame, still
occupies its slot. Verified: over 3,000 frames, `ebCount` and a direct scan of
the object pool for `TYPE_EBULLET` **disagreed on zero frames**.

**6. Other hidden effective limits?** Yes, and this is the important part —
several bind *before* the cap does:

| mechanism | value | effect |
|---|---|---|
| `objectAlloc` (shared pool) | 16 objects | can refuse first; counted as a refusal |
| `WAVE_FIRE_PERIOD` | 48 frames | **one** moving-enemy firing opportunity for the whole screen, so no two enemy bolts ever leave on the same frame |
| `ENEMY_FIRE_MIN_Y` / `MAX_Y` | 70 / 170 | a narrow band in which an enemy may fire at all |
| `TURRET_FIRE_INTERVAL` | 100 frames | per turret |
| `TURRET_FIRE_MIN_Y` / `MAX_Y` | 88 / 201 | and typically ~2 turrets combat-visible at once |
| `MUX_SLOTS` | 6 | a **rendering** constraint on same-raster overlap, not a projectile cap |

**7. Is the cap historical?** **No.** `EBULLET_MAX` has been **3 since the commit
that introduced it** (`2a17da6 Complete turret firing and player damage`) — it
was never 2, and `git log -S` confirms it has never been changed. Its own comment
argues from the current frame budget (`docs/ENGINE_CONTRACT.md` §10, "about eight
well-separated sprites"), not from any renderer or scroll-jank workaround.

**8. What happens at the cap?** The shot is **refused and forgotten**, not
queued: `ebRefused` is bumped (saturating at 255), carry is set, and the caller
gives up. `src/waves.asm` states the policy — *"a missed opportunity is lost, not
queued"* — because a queued shot would fire later from an enemy that had since
moved, died or left.

### What the machine actually does

3,000 frames of ordinary play, production code, nothing poked:

```
ebCount histogram    {0: 2149, 1: 845, 2: 6}
peak simultaneous    2
ebRefused            0
ebCount vs pool scan disagreed on 0 frames
```

### The finding

> **The cap is 3. The observed ceiling is 2. The cap is never reached.**

Your recollection of "2" matches what the game *does*; it just is not where the
number lives. Two projectiles is the practical ceiling because the **rate
limiters bind long before the cap**:

* a bolt lives ~26–59 frames (falling 3 px/frame from the firing band to
  retirement at Y 247);
* moving enemies get **one** opportunity every 48 frames, screen-wide → at most
  ~1.2 in flight;
* each turret reloads for 100 frames, with ~2 combat-visible → ~1 in flight.

≈ 2, which is exactly what was measured, with `ebRefused` at zero across the
whole run.

**So I changed nothing**, per the brief's instruction to stop at the audit if the
cap is not 2. And it is worth being blunt about why that is the right outcome
rather than a technicality: **raising 3 → 4 would have changed nothing
observable.** If you want more simultaneous hostile fire, the levers are
`WAVE_FIRE_PERIOD`, `TURRET_FIRE_INTERVAL` and the firing bands — all of which
are rebalancing, and all of which this task was told not to touch. The cap has
one spare slot already waiting for them.

The three-projectile stress validation was therefore **not run**: there is no
change to validate, and the engine has always permitted three.

---

## Validation

### Build and smoke

```
make build   OK   wave state $77c0-$77f1 (50 of 64 bytes)
                  level wave triggers $f736-$fb6d = 8 x 135, clear of the
                  signature at $fb70
make smoke   PASS   BOOT / CAMPAIGN LOOP / ENGINE HEALTH / ROUTINE REGRESSION
  4007 frames: gameOverrun 0  scrollLate 0  edgeLate 0  statOverflow 0
                publishSkip 0  schedBuildDefer 0  statLate 0  clipPoolFull 0
                objDoubleFree 0  objAllocFail 0
```

The campaign loop passes, which exercises the level-2 transition with the
eight-column package.

### Editor proof — `tools/level_editor/test_wave_colour_mode.py`, **83 passed, 0 failed**

```
ok  - a WaveDefinition exposes no colour field / no colour mode / NO FIRING MODE
ok  - ...and what remains is formation only
      [count, heading, id, interval, movementProgram, startX, startY, xStep, yStep]
ok  - a Trigger owns the colour / the colour mode / THE FIRING MODE
ok  - ...and still owns the fire MASK it always did
ok  - a legacy definition's firing mode is read as MIGRATION INPUT  [AIMED, DOWN, None]
ok  - a trigger inherits its definition's AIMED -- not reset to DOWN
ok  - a definition with no fireMode at all migrates as DOWN
ok  - two triggers on one definition each get their own firing copy
ok  - two triggers share the definition 'loop'  [rows 126 and 350]
ok  - trigger A is now AIMED
ok  - ...AND TRIGGER B, ON THE SAME DEFINITION, STILL FIRES DOWN
ok  - ...and the shared definition has no firing mode to change
ok  - ...AND SO DO THEIR FIRING MODES, from one shared definition  [AIMED, DOWN, DOWN, DOWN]
ok  - EVERY definition's byte 7 is now reserved and zero  [[0]]
ok  - the AIMED appearance exports AIMED in the TRIGGER column
ok  - the fire MASK column is untouched by the move
ok  - EVERY generated file is byte-identical after the round trip
ok  - exporting the same project twice is byte-identical
```

One trap paid for and written down: assigning `sel_trigger` directly does not
survive the next `app.update()` — the tree still holds a pending
`<<TreeviewSelect>>` whose handler re-derives the selection and overwrites the
assignment. The test now selects through the tree, the way a user does.

### Runtime proof — `tests/test_wave_colour_mode.py`, **ALL PASS**, 3 VICE launches

```
ok   A DEFINITION'S BYTE 7 IS RESERVED AND ZERO -- no colour, no firing
       sweep=$00, s=$00, linger=$00, loop=$00, loop_5=$00, dive_4=$00, up_n_over=$00
ok   the firing mode is on the TRIGGER now
ok   ...and the AIMED appearance is the one the author authored  [row 20]
ok   every appearance with a firing mode also sends a shooter
ok   every armed enemy's mode matches its APPEARANCE's latched mode  [25 armed]
ok   the AIMED appearance really did arm its members AIMED
ok   ...and no DOWN appearance was given aimed fire
ok   two triggers on 'dive_4' set to different colours  [rows 205 and 310]
ok   ...and to different firing modes
ok   ...and the definition they share carries neither, to conflict with
ok   ONE DEFINITION PRODUCED ENEMIES OF TWO DIFFERENT COLOURS
ok   ...AND ENEMIES THAT ATTACK TWO DIFFERENT WAYS
       appearance A armed [2] (2=AIMED), appearance B armed [1] (1=DOWN)
```

The shared-definition specimen is `dive_4` rather than `loop`: all four `loop`
triggers carry DROPPERs, and a Dropper is taken off its wave's path by
`dropperLaunch` the instant it spawns, which makes it the wrong thing to compare
firing on. Rings are the ordinary case.

### Visible output — headless captures

`x64sc -console` through the harness, frames from the monitor's own
`screenshot`. No window, no focus stolen.

| capture | observation |
|---|---|
| `fire_aimed` | every appearance forced AIMED: bolts in flight carry **vx [2, 2]** — leaning toward the ship |
| `fire_down` | every appearance forced DOWN: bolts carry **vx [0, 0]** — falling straight |

Both frames render correctly with the eight-column package: full random-coloured
Ring formation, terrain, turrets, HUD, player, and a bolt visible mid-screen. No
flicker, corruption or scroll artefact in either.

**Final visual acceptance is still yours**, and MiSTer/CRT more so. A long,
normal-speed, non-warp session is the thing I cannot do, and `AGENTS.md` puts it
above everything above.

### Regressions

| suite | result | note |
|---|---|---|
| `test_wave_colour_mode` (runtime + editor) | **pass** | rewritten for this move |
| `test_aimed_fire` | **0 FAIL** | **repointed — see below** |
| `test_aimed_velocity` | **0 FAIL** | **repointed + instrument fixed — see below** |
| `test_boot`, `test_enemy_fire`, `test_p_economy_colours`, `test_lifecycle` | pass | |
| `test_wave_schema`, `test_v6_roundtrip`, `test_v6_validation`, `test_v6_migration`, `test_level_packages`, `test_v6_phase5b_encounters`, `test_v6_phase5a_gui`, `test_semantic_gui`, `test_encounters_gui` | pass | |
| `test_encounter_director` | 2 FAIL | pre-existing (wave concurrency), unchanged |
| `test_wave_triggers` | 3 FAIL + load-flaky `gameOverrun` | pre-existing, unchanged |
| `test_encounter_library`, `test_multi_level_layout` | 1 FAIL each | pre-existing stale counts |
| `test_v6_export` | FAIL | pre-existing (`Can't open file: stage_sprites.asm`) |
| `test_v6_import`, `test_v6_phase4_roundtrip` | FAIL | pre-existing — see below |

#### Two tests I repointed, because they tested the thing that moved

`test_aimed_fire` and `test_aimed_velocity` forced aimed fire by poking the wave
**definition's** byte 7. That byte is now reserved, so the poke silently did
nothing and both tests began measuring straight-down bolts. They now poke
`waveTrigFireMode` over the live trigger count, with a comment naming exactly
this failure mode so it cannot recur quietly.

#### One instrument that was lying, and how I knew

After repointing, `test_aimed_velocity` reported four failures including *"stored
VY=0 but moved 64"* and *"steps seen [0, 3, 64]"*. Per `AGENTS.md` rule 4 I
checked which side was wrong before changing either:

* `ebulletSpawn` writes `EBULLET_VY` (3) or `EBULLET_VY_STEEP` (2) before the
  slot is activated, and `ebulletAimVY` holds only `{3, 3, 2}` — **a live bolt
  can never have `objVY == 0`**;
* a bolt falls at most 3 pixels a frame, so **a 64-pixel jump is impossible**.

Both artefacts were a freed slot refilled by a new bolt *lower down*, which the
test's flight-splitter did not detect — it split on "restarts higher up" and
"slope changed" only. The density that exposed it is new (all twelve appearances
now genuinely aimed). The splitter now also drops `objVY == 0` samples and splits
on any downward jump larger than one step. All ten checks pass, including the
`objVY` vertical-movement behaviour the brief asks about:

```
ok   VERTICAL: every frame advances by the slope's OWN stored objVY, not a constant
ok   |VX|=0: measured vertical step is the authored 3   |VX|=1: 3   |VX|=2: 2
ok   measured speeds 3.00 / 3.16 / 2.83 px/frame
```

**The engine was correct throughout.** Only the measurement was.

#### `import_engine_v6.py`

The trigger layout changed, so I audited its consumers. This module reads the
trigger columns and did not know about the two new ones, so it now reads
`trigColour` and `trigFireMode` and its reference encoder emits them. Its own
tests still fail, for reasons that predate this task and are unrelated to
firing: with the import now getting further, what surfaces is stale stage
geometry in the test's fixture (`worldProgress 450 is past the last row the
stage reaches (395)`). Left alone — the module is used only by those two test
files and never by the live export path.

---

## Unrelated issues, deliberately left

1. **`test_v6_import` / `test_v6_phase4_roundtrip`** — stale stage-geometry
   fixtures, as above.
2. **`test_encounter_library`** expects nine level-1 triggers (there are 12);
   **`test_multi_level_layout`** expects two levels (there are three).
3. **`test_v6_export`** fails on a missing `stage_sprites.asm` in its scratch
   build.
4. **`test_wave_triggers`** expects a trigger at row 48 that is authored at 20,
   and its `gameOverrun is zero` check is load-flaky.
5. **`/opt/homebrew/bin/python3` segfaults** on any real-Tk editor test;
   `/usr/local/bin/python3` works.
6. **The two new test files are still named `test_wave_colour_mode.py`** though
   they now cover colour *and* firing. Renaming would strand the references in
   the two earlier reports; flagged rather than done.

---

## Files changed

| file | change |
|---|---|
| `src/encounter_format.asm` | `TRIG_FIRE_DOWN` / `_AIMED` / `_MAX`, and the three-authority note |
| `src/levelpkg.asm` | `LEVELPKG_TRIG_COLS` 7 → 8 (slots 154 → 135, derived) |
| `src/level_package.asm` | emits the `trigFireMode` column |
| `src/waves.asm` | `WAVEDEF_FIRE_BITS`/`_AIMED` removed, byte 7 reserved + guard; `waveTrigFireMode` label; `wvFireMode` per instance; latch in `waveStartNext`; spawn reads the instance; two new authored-data proofs |
| `src/ebullet.asm` | stale cross-reference to `WAVEDEF_FIRE_BITS` corrected |
| `src/level{1,2,3}/wave_encounters.asm` | **generated** — byte 7 zero; `trigFireMode` added |
| `contract_v2.py` | fire modes reframed as a trigger field; 8 columns, derived slots |
| `project_v6.py` | `fire_mode` off `WaveDefinition` (→ `legacy_fire_mode`), onto `Trigger`; `resolve_trigger_colours` → `resolve_trigger_encounter_fields` (alias kept) |
| `controller_v6.py`, `encounter_library.py` | trigger CRUD carries the mode; migration call sites |
| `validation_v6.py` | `wavedef.fire_mode` → `trigger.fire_mode` + `trigger.fire_mode_unused` |
| `export_v6.py` | `wavedef_fire_byte` → `wavedef_reserved_byte`; `trigger_fire_mode_byte`/`_expr`; the new column |
| `encounters_ui.py` | firing control removed from definitions, added to triggers with an empty-mask warning |
| `import_engine_v6.py`, `movement_sim.py` | follow the moved field; importer reads all eight columns |
| `encounter_library.v6.json`, `levels/level{1,2}/level.v6.json` | **migrated data** |
| `tests/test_aimed_fire.py`, `tests/test_aimed_velocity.py` | repointed at the trigger column; splitter hardened |
| `tests/test_wave_colour_mode.py`, `tools/level_editor/test_wave_colour_mode.py` | extended to firing |

Scope held: no renderer/mux/scroller/raster redesign, scroll still 1 px/frame,
no 2 px experiment, random-colour exclusions unchanged, player colour still
eligible, no Level 3 turret work, no AngryLoad, no runtime-variable stage
length, **no wave sizes/speeds/intervals rebalanced**, no projectile artwork
touched, and no projectile cap change.

---

## Final state

```
 M src/ebullet.asm                       M tools/level_editor/encounter_library.py
 M src/encounter_format.asm              M tools/level_editor/encounter_library.v6.json
 M src/gamestate.asm                     M tools/level_editor/encounters_ui.py
 M src/level1/wave_encounters.asm        M tools/level_editor/export_v6.py
 M src/level2/wave_encounters.asm        M tools/level_editor/import_engine_v6.py
 M src/level3/wave_encounters.asm        M tools/level_editor/levels/level1/level.v6.json
 M src/level_package.asm                 M tools/level_editor/levels/level2/level.v6.json
 M src/levelpkg.asm                      M tools/level_editor/movement_sim.py
 M src/waves.asm                         M tools/level_editor/project_v6.py
 M tests/test_aimed_fire.py              M tools/level_editor/test_v6_phase5b_encounters.py
 M tests/test_aimed_velocity.py          M tools/level_editor/test_v6_validation.py
 M tools/level_editor/contract_v2.py     M tools/level_editor/test_wave_schema.py
 M tools/level_editor/controller_v6.py   M tools/level_editor/validation_v6.py
?? reports/per-enemy-random-wave-colour.md
?? reports/trigger-owned-enemy-colour.md
?? reports/trigger-owned-fire-and-projectile-cap-audit.md
?? tests/test_wave_colour_mode.py
?? tools/level_editor/test_wave_colour_mode.py

26 files changed, 1057 insertions(+), 210 deletions(-)
```

* **Nothing committed. Nothing pushed.** HEAD is still `d5fc70d`.
* **No destructive Git operation was used.** No `checkout`, `restore`, `reset`,
  `stash`, or `clean` was run at any point in this task. Every file was inspected
  and edited in place. Baselines came from reading history with `git log -S` and
  `git show`, which write nothing. A tar snapshot of the dirty tree was taken
  into scratch before the first edit, purely as a safety net, and was never
  needed.
* VICE: every instance launched through the harness with `-console`, owned by
  exact PID and reaped in a `finally`. No broad `pkill`/`killall`, no
  user-launched instance touched, no focus stolen. `pgrep -fl x64sc` confirms
  **none running**.
* `build/` is **340 K**, current artefacts only. Scratch probes, captures and the
  safety snapshot live in the session scratchpad (7.2 M); the `/tmp` logs from
  this task were deleted. **92 GiB free of 228 GiB.**
