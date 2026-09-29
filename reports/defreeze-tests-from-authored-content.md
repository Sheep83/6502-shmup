# De-freezing the Tests from Authored Campaign Content

**Task:** 19656 — De-freeze Tests from Authored Campaign Content
**Scope:** test-suite housekeeping. No gameplay, engine or authored-content change.
**Tree:** `main`, HEAD `e5532cc Variable enemy speed added`, clean at start.

---

## The problem, stated in the repository's own numbers

Automated tests exist to catch the engine, the editor, the schema, the exporter
and the package layout misbehaving. A great many of them had instead been
catching *Brian authoring the game*.

Level 1 was re-authored between tasks: it now carries **five** triggers at rows
40/90/140/200/240, playing `up_n_over`, `loop` (twice), `dive_4` and `s`, with
species DROPPER/RING_3/SPACE_WHISK/RING_3/DROPPER, four different movement
speeds and one RANDOM colour. Four of its seven wave definitions are no longer
referenced by any trigger at all.

Nothing about the engine changed. The suites reported:

| Suite | Baseline verdict |
|---|---|
| `tests/test_wave_triggers.py` | **12 failures** — every one a frozen literal |
| `tests/test_trigger_speed.py` | **11 failures** — `SWEEP_VX = 6`, "all 1.00x" |
| `tests/test_wave_colour_mode.py` | **4 failures** — a hunted shared definition |
| `tests/test_flight_paths.py` | **4 failures** — all "0 of N" coverage-by-luck |
| `tests/test_no_spawn_row.py` | **3 failures** — `WAVE_TRIGGERS = 4` |
| `tests/test_aimed_fire.py` | **1 failure** — "bolts lean left" |
| 10 of 45 editor suites | crashes and failures, listed below |

That is the failure mode the task names: *"`Level 1 has 12 Triggers` is a bad
test. `Every Trigger references a valid Wave Definition` is a good test."*

---

## Baseline, recorded before any change

**Editor suites** (45 files, `/usr/local/bin/python3`, real Tk): **35 pass, 10 fail**

```
test_encounter_library       FAIL   SimulationError: trigger 0 is now a Dropper
test_encounters_gui          FAIL   StopIteration: the authored mask covers every member
test_movement_sim            FAIL   TypeError: WaveDefinition(colour=…) — stale API
test_multi_level_layout      FAIL   AttributeError: C.DEFAULT_ENEMY_SLOTS — stale API
test_preview_gui             FAIL   IndexError: RING[0] — no plain RING trigger exists
test_v6_import               FAIL   species sequence: 'SQUARE' vs 'SPACE_WHISK'
test_v6_phase4_roundtrip     FAIL   export→import→export not a fixed point
test_v6_phase5b_encounters   FAIL   "renaming a wave updates every trigger" [0 references]
test_v6_phase6a1_hotfixes    FAIL   "RING-RING is accepted" [trigger.species]
test_v6_roundtrip            FAIL   key order drifted (enemySlots added to the schema)
```

**Runtime suites** (the content-coupled set, real VICE):

```
wave_triggers      FAIL  12 failures + gameOverrun 3
no_spawn_row       FAIL   3 failures
pickup             PASS
aimed_fire         FAIL   1 failure
wave_colour_mode   FAIL   4 failures
trigger_speed      FAIL  11 failures
movement_pool      FAIL   6 failures (ARC entry section)
campaign           PASS
species_order      PASS
flight_paths       FAIL   4 failures
```

Raw output was captured to the session scratchpad (transient, not committed);
the failure lines are reproduced verbatim throughout this report.

---

## Classification

Every content-coupled assertion found was put in one of the four categories the
task defines.

### (1) Genuine structural / safety invariant over real campaign data — RETAINED

These are the good tests, and several were **added** where a freeze was removed,
because "the level says X" was replaced by "whatever the level says is legal".

| Invariant | Where |
|---|---|
| every live trigger names a wave definition that exists | `test_wave_triggers`, `test_encounter_library` |
| every wave definition names a movement program that exists | `test_encounter_library` |
| every species value is one of the engine's slot rows | `test_wave_triggers` |
| every fire mask arms only members its wave actually sends | `test_wave_triggers` |
| every colour byte is inside `TRIG_COL_MASK + TRIG_COL_RANDOM` | `test_wave_triggers`, `test_wave_colour_mode` |
| every firing mode ≤ `TRIG_FIRE_MAX` | `test_wave_triggers` |
| every speed inside `TRIG_SPEED_MIN..MAX`, padding at `TRIG_SPEED_1X` | `test_wave_triggers`, `test_trigger_speed` |
| trigger rows non-decreasing (forward-only cursor) | `test_wave_triggers`, `test_no_spawn_row` |
| every authored row strictly below `STAGE_NO_SPAWN_ROW` | `test_no_spawn_row` (new) |
| the package's nine columns are what the generated level declares | `test_wave_triggers` (new), `test_wave_colour_mode` (new) |
| the pool is a whole number of stage records; every program offset lands on a boundary | `test_movement_pool` |
| every arc's byte 3 is a heading in range or `WM_HEAD_CONT` — no third value | `test_movement_pool` (new) |
| the trigger columns tile the reservation exactly; the editor ceiling equals the slot count | `test_movement_pool` |
| the whole trigger list stays below the package signature | `test_movement_pool` |
| the resident package matches the level it claims to be, and differs from the other | `test_campaign` |
| every level the campaign sequence names exists as a document | `test_multi_level_layout` (new) |
| every trigger previews or is refused for a named reason | `test_encounter_library` (new), `test_movement_sim` (new) |
| memory bounds, table limits, sprite/pool budgets, path safety, corruption counters | untouched |

### (2) Machinery test that should use synthetic data — REFACTORED

| Test | Was | Now |
|---|---|---|
| `test_trigger_speed` | flew `sweep`'s opening leg, `SWEEP_VX = 6` | installs a STRAIGHT leg of its own at a known velocity |
| `test_trigger_speed` §3 | pointed authored trigger 1 at trigger 0's definition | builds both triggers, the definition and the rows |
| `test_wave_colour_mode` §1 | relied on "one fixed and eleven random" appearances | installs one FIXED and one RANDOM on one definition |
| `test_wave_colour_mode` §3 | hunted for a shared non-Dropper definition | builds the pair |
| `test_no_spawn_row` | drove the authored schedule | installs one disposable trigger at a low row |
| `test_movement_pool` | tested CONT / mirror / clockwise on whichever authored records had the right shape | installs synthetic arc records, including both table wraps |
| `test_flight_paths` | waited for Level 1 to exercise all five primitives | installs a five-stage program that walks every one |
| `test_aimed_fire` | "ship far left ⇒ every bolt leans left" | asserts the exact quantised aim law from the measured distance |
| `test_preview_trigger_speed` | borrowed whatever shared definition existed | builds its own program, wave and two triggers |
| `test_movement_sim` §12 | hunted a "RING" and a "DROPPER" trigger | uses a fixture; adds a structural pass over the real level |
| `test_preview_gui` | `RING[0]`, `DROP[0]` | arranges two previewable triggers and a Dropper in memory |
| `test_encounters_gui` | found a member with no fire bit set | clears one, then re-reads the widget row |
| `test_v6_phase5b_encounters` | renamed/deleted wave definition index 0 | finds a definition a trigger actually references |
| `test_v6_phase6a1_hotfixes` | `["RING","RING"]` species sequences | builds them from the level's own identities |
| `test_v6_phase4_roundtrip` | 33 programs, a "27th" definition, a "181st" trigger | derived limits, tested **at** and **one past** |
| `test_v6_import` corruption fixtures | named `WM_STRAIGHT, 34, 6, 0`, `WAVE_DEF_SWEEP`, `SPECIES_RING`, `PROG_LOOP = 3` | structural: "the first record of this kind", "the first entry of this column", "the last `PROG_*`" |

### (3) Authored-content freeze with no safety value — REMOVED

| Removed assertion | Why it had no safety value |
|---|---|
| "the authored rows are the ones the delta schedule produced for its first cycle — 48, 52, 90, 126" | a spatial layout decision |
| `waveTrigDef/Species/Fire/Side is unchanged by the migration` (×4, literal copies) | replaced by range and reference checks |
| "the AIMED appearance is the one the author authored" `== [20]` | one row of Level 1 |
| "the authored level really does reuse definitions across triggers" | replaced by a built pair |
| "exactly one arc asks to CONTINUE, and it is the S-turn's join" (record index 4) | how many S-turns a level has |
| the hand-written arc-context map `{1: "…(SWEEP)", 8: "…(LINGER)", 11: "…(LOOP)", 3: "…"}` | record indices and program names |
| "every authored trigger is 1.00×" | false the moment the feature was used |
| `WAVE_DEFS = 7` in `test_aimed_fire` | dead constant, never referenced |
| "Level 1 still has Brian's Square trigger" / "all nine triggers" / each level's `noSpawnRow` literal (×6) | replaced by ownership-separation checks |
| "exactly two levels are present" | a third level was legitimately started |
| "a hand-authored `stage_enemies.asm` survives a re-export" | the exporter deliberately regenerates it now; the check asserted the opposite |
| the frozen eleven-key JSON order list | replaced by "the writer's own order, stable across a round trip" |
| the frozen two-warning set on import | replaced by "no errors, and every warning is an advisory kind" |
| `glyphCount == 80 / 128`, `bg == 12 / 5`, `turretCount == 5 / 0`, `"LEVEL1LEVEL2"` | read from each level's own `stage_config.asm` and `campaign.asm` |

### (4) Genuinely stable integration / golden contract — RETAINED, documented

| Golden | Why it stays |
|---|---|
| **the package byte comparison** in `test_movement_pool` and `test_v6_import` — pool, definitions and all 1,080 trigger column bytes against `build/level1.prg` | not a snapshot of content: it compares two *independent encodings of the same data*. The engine emits the bytes; the importer's reference encoder re-derives them from the source. Either side drifting is a real defect. It now reads `POOL_BYTES` and the derived reservation rather than 52/40/1080. |
| **`src/level1/` files ARE the exporter's output, byte for byte** (`test_v6_phase4_roundtrip`) | the committed generated files must be reproducible from the project. Content-independent by construction. |
| **`save → load → save` is byte-identical** (`test_v6_roundtrip`, `test_multi_level_layout`) | determinism of the writer, not a content snapshot. |
| **`export → import → export` is a byte fixed point** | the same, one layer out. |
| **`test_level_identity`**: two snapshots of the same package loaded two ways | compares a level against itself; no literal content anywhere. |
| **the fixtures in `fixtures_v6.py`** | goldens over these are goldens over a *fixed synthetic* thing, which is the only kind worth having. |

---

## New shared infrastructure

### `tests/campaign_data.py` — the authored campaign, read not remembered

Parses the generated level the engine was **actually built against**, through the
editor's own declaration reader (`asm_decl` — the same one the importer uses), and
exposes it as data: rows, definitions, species, fire masks, colours, firing modes,
speeds, wave definitions, programs, pool offsets, `prog_at`.

It also resolves every `.const LEVELPKG_*` out of `src/levelpkg.asm`, which
removed the last transcribed addresses from the runtime suites. That is not
cosmetic: `test_movement_pool` carried `WAVEDEF = 0xf632` while `levelpkg.asm`
itself *spells that constant `$f630` in a comment*. The derived value is `$f632`;
the comment is stale. Deriving it makes the question unanswerable by transcription.

`python3 tests/campaign_data.py` prints both levels as a readable dump.

### `tests/synth.py` — synthetic encounters in the loaded package

Installs movement programs, wave definitions and triggers into the **spare room
the package reserves and no level uses** — 256 pool bytes of which 76 are used, 26
definition slots of which 7 are used, 120 trigger slots of which 5 are used.
Package RAM only; the disk is never written. Every installer refuses rather than
overflowing a reservation, so a level that grows until the spare room is gone gets
a clear failure naming the budget instead of a corrupted package.

The useful shapes: `straight_then_exit(vx, vy)`, `only_trigger(...)`,
`pair_on_one_definition(rows, definition, speeds, colours, fire_modes, fire)`.

### `tools/level_editor/fixtures_v6.py` — minimal deterministic v6 projects

`tiny()`, `shared_wave()`, `wide_wave()`, `two_species()`, `at_capacity(n)`. All
validate clean; `at_capacity` defaults to the **derived** `C.MAX_TRIGGERS`.
`python3 tools/level_editor/fixtures_v6.py` prints their shapes and the derived
ceiling.

---

## Capacity: derived at both ends, tested from both sides

The task asked for this specifically, and it mattered: `test_v6_phase4_roundtrip`
said *"a 181st trigger is refused"*. The trigger record grew from six columns to
nine and the slot count fell 180 → 154 → 135 → **120**, so that check was
refusing the 181st of 120 — true, and sixty triggers past the boundary it claimed
to test.

Capacity is now computed from `src/levelpkg.asm`'s reservation and column count
(via `contract_v2`, which reads the file), and each limit is tested **twice**:

```
derived limits: 32 x 8-byte programs (256 pool bytes), 26 wave definitions, 120 triggers
  ok   a movement pool of exactly 32 programs (256 of 256 bytes) is accepted
  ok   ...and one more program (264 bytes) is refused -- movement.pool_overflow
  ok   exactly 26 wave definitions are accepted
  ok   ...and a 27th is refused -- wavedef.too_many
  ok   exactly 120 triggers are accepted -- the package's own 9 x 120 reservation
  ok   ...and a 121th is refused -- trigger.too_many
```

A refusal alone cannot tell an off-by-one ceiling from a correct one. Both halves
are now asserted, and no historical number appears anywhere.

---

## Defects the de-freezing exposed

Four real problems were hiding behind frozen or crashing tests. All four are
machinery, not authored content.

1. **`import_engine_v6.reference_encode_trigger_columns` emitted eight of nine
   columns.** The movement-speed column was added to the package, the exporter
   and the engine, and not to the reference encoder — 960 bytes against the
   package's 1,080, so the byte-for-byte comparison could not even be attempted.
   Fixed, with a guard that fails loudly if the count ever disagrees with
   `LEVELPKG_TRIG_COLS`, and with the per-column padding the package uses
   (`TRIG_SPEED_1X`, not zero, for the speed column).

2. **`import_triggers` ignored `trigSpeed` entirely.** A level authored at 1.50×
   re-imported at 1.00× with nothing said. Fixed, with a column-count guard and a
   range check; a speed outside the engine's five choices is now refused.

3. **The importer resolved species slots to the *default* identity.** A level
   holding Space Whisk re-imported as `"SQUARE"` and would then have re-exported
   as species row 0 — silently changing which enemy the trigger sends. The caller
   now supplies the destination project's own `enemySlots`, which is what makes
   export → import → export a genuine fixed point.

4. **`EditorController.suggested_species()` returned the literal `"RING"`.**
   `"RING"` stopped being a species when a slot could hold any roster identity, so
   **Add Trigger produced a trigger the validator rejects** (`trigger.species`,
   "unknown enemy 'RING'"). No test noticed because none of them validated after
   adding one. It now returns the level's slot-0 identity, and the test asserts
   the project still validates afterwards.

Two further findings, reported rather than changed:

5. **`test_flight_paths` documented its own defect and never fixed it** — "coverage
   by luck […] the proper repair is to arrange each primitive deliberately". The
   luck ran out. It is now arranged deliberately, which is what `tests/synth.py`
   made cheap.

6. **`gameOverrun` in `test_wave_triggers`** — see *Remaining issues*.

---

## Sanity proof A: legal authoring changes do not break unrelated tests

A copy of the tree was made in the scratchpad (`rsync`, no `.git`), and **seven
ordinary authoring edits** were applied to its Level 1 through the editor's own
controller, then exported and rebuilt:

```
BEFORE:
    (40, 'up_n_over', 'DROPPER',     4, 1, 'FIXED',  'AIMED', [0,1,2,3,4,5])
    (90, 'loop',      'RING_3',      6, 1, 'RANDOM', 'AIMED', [0,1,2])
    (140,'loop',      'SPACE_WHISK', 8, 1, 'FIXED',  'AIMED', [0,1,2])
    (200,'dive_4',    'RING_3',      5, 1, 'FIXED',  'AIMED', [0,1,2,3])
    (240,'s',         'DROPPER',     5, 1, 'FIXED',  'AIMED', [0,1,2])

1. added a trigger at row 270 on wave 'linger'
2. deleted trigger 1 (row 90, RING_3)
3. trigger 1: species SPACE_WHISK -> RING_3
4. trigger 2: wave dive_4 -> linger
5. every speed changed
6. every colour and colour mode changed
7. every fire mask and firing mode changed

AFTER:
    (40, 'up_n_over', 'DROPPER', 5,  4, 'RANDOM', 'DOWN', [0,2,4])
    (140,'loop',      'RING_3',  4,  5, 'RANDOM', 'DOWN', [0,2])
    (200,'linger',    'RING_3',  4,  6, 'RANDOM', 'DOWN', [0,2])
    (240,'s',         'DROPPER', 4,  7, 'RANDOM', 'DOWN', [0,2])
    (270,'linger',    'RING_3',  4, 12, 'FIXED',  'DOWN', [0,2])

validate: OK []
```

Every trigger-owned field, the trigger count, the species, the wave references and
the shared-definition pairing are all different from the committed level. It
builds. Results are in *Test results* below.

## Sanity proof B: genuinely invalid data still fails

Fifteen corruptions, each one thing that actually matters. **15 of 15 refused.**

Editor / schema (validator error code, and the export refused in every case):

```
REFUSED  a trigger naming a wave definition that does not exist    trigger.dangling_definition
REFUSED  a wave definition naming a program that does not exist    wavedef.dangling_program
REFUSED  a movement speed outside the engine's five choices        trigger.speed
REFUSED  a trigger colour outside four bits                        trigger.colour
REFUSED  a trigger AT noSpawnRow, which could never start          trigger.at_or_after_no_spawn
REFUSED  descending trigger rows                                   trigger.unsorted
REFUSED  a fire mask arming a member the wave never sends          trigger.fire_member_absent
REFUSED  an unknown enemy identity                                 trigger.species
REFUSED  one trigger past the derived capacity (121 of 120)        trigger.too_many
```

The assembler, on corrupted **generated** data (build refused, `rc=2`, in a
throwaway copy):

```
REFUSED  a trigger row at or beyond STAGE_NO_SPAWN_ROW
REFUSED  a trigger naming a wave definition index that does not exist
REFUSED  a movement speed outside TRIG_SPEED_MIN..MAX
REFUSED  a trigger colour byte with a bit outside colour and the RANDOM flag
REFUSED  descending trigger rows -- the last two swapped
REFUSED  a fire mask arming a member the wave never sends
```

Each of the six alters exactly one field of one column, so each exercises the
guard it names rather than tripping a different one first. (KickAssembler prints
the first `.error` *text* in the file, which is not always the guard that fired;
the refusal — a non-zero exit and no `main.prg` — is what is asserted.)

---

## Test results

### Editor suites, current tree — **45 of 45 pass** (baseline 35/45)

All ten baseline failures fixed. No suite regressed.

### Runtime suites, current tree

| Suite | Baseline | Now |
|---|---|---|
| `test_wave_triggers` | 12 fail + `gameOverrun 3` | **ALL PASS** |
| `test_trigger_speed` | 11 fail | **ALL PASS** |
| `test_movement_pool` | 6 fail | **ALL PASS** |
| `test_wave_colour_mode` | 4 fail | **ALL PASS** |
| `test_flight_paths` | 4 fail | **ALL PASS** |
| `test_no_spawn_row` | 3 fail | **ALL PASS** |
| `test_aimed_fire` | 1 fail | **ALL PASS** |
| `test_pickup` | pass | pass |
| `test_campaign` | pass | pass |
| `test_species_order` | pass | pass |

### `make smoke` — **ROUTINE REGRESSION: PASS**

```
CAMPAIGN LOOP: PASS
  ATTRACT -> PLAYING      ok
  PLAYING -> LEVELDONE    ok  (the upgrade shop)
  CONTINUE advances       ok  cmpLevel 0 -> 1
  level 2 package loaded  ok  noSpawnRow 725 -> 352
  level 2 -> PLAYING      ok
  PLAYING -> GAME OVER    ok
  returns to the front    ok

Frames observed: 3917
  gameOverrun 0   scrollLate 0   edgeLate 0   statOverflow 0
  statPageMismatch 0   statPtrMismatch 0   objDoubleFree 0
  objAllocFail 0   clipPoolFull 0   publishSkip 0
  schedBuildDefer 0    statLate 0
ENGINE HEALTH: PASS
```

`gameOverrun 0` over 3,917 frames of a real campaign loop is the third
independent measurement saying the same thing about the counter discussed under
*Remaining issues*.

### The legal-change tree (proof A)

**Editor suites against the re-authored level: 45 of 45 pass.**

One of them failed on the first attempt and the failure was worth having.
`test_preview_trigger_speed` — the regression test written for the preview-cache
fix — reported seven failures:

```
ok  - two ordinary triggers share the definition 'linger'  [rows 200 and 270]
       1.00x:  206 frames, width   70
       1.25x:  180 frames, width   51
       1.50x:  156 frames, width   44
       1.75x:  142 frames, width   53
       2.00x:  119 frames, width   66
FAIL- the loop is WIDER at 2.00x, not merely faster  [70 -> 66 (0.94x)]
FAIL- all five speeds widen monotonically
```

It hunted the level for two triggers sharing one wave definition and found
`linger`, whose program **loiters** — a STRAIGHT leg, then a HOLD drifting at
(0, 1), then an arc. Scaling a hold that slow barely moves the geometry, so the
premise "the loop gets steadily wider" was a property of the *program*, not of the
engine. The preview was drawing exactly what the runtime would fly.

It now builds its own program (east, a quarter turn to south, out through the
bottom — chosen so the straight leg and the arc radius both count toward the
measured width and both scale), and the reading is unambiguous:

```
       1.00x:  171 frames, width   62
       1.25x:  152 frames, width   72
       1.50x:  126 frames, width   92
       1.75x:  116 frames, width  103
       2.00x:  102 frames, width  125
ok  - the loop is WIDER at 2.00x, not merely faster  [62 -> 125 (2.02x)]
ok  - all five speeds widen monotonically
ok  - ...and complete monotonically sooner
```

Two earlier shapes were rejected along the way and both are recorded in the
file: a full circle exiting east put the width in the run to the border, the same
distance at every speed; and turning too far left the aperture before the arc
closed, truncating the 2.00× path so it came out *narrower*.

**Runtime suites against the re-authored level:**

```
no_spawn_row     PASS      campaign         PASS
aimed_fire       PASS      species_order    PASS
wave_colour_mode PASS      flight_paths     PASS
trigger_speed    PASS      aimed_velocity   PASS
level_identity   PASS
```

`test_wave_triggers` failed on the first attempt, and that failure was also worth
having — it found a freeze the first pass had left behind:

```
FAIL the disposable schedule [255, 256, 511, 512] is armed ahead of the world -- worldProgress 270 < 255
FAIL ...the approach stopped short of row 255 -- approach ended at 270
```

The boundary rows were still the literals `[255, 256, 511, 512]` and
`[1023, 1024, 1535, 1536]`. The world only moves forward, so 255 is reachable only
while the authored schedule ends below it — and the re-authored level ends at row
270. `boundaries_above()` now picks the next 8-bit boundaries above wherever the
world actually is, and the *property* is asserted rather than the numbers: every
chosen row ahead of the world, in `(256k-1, 256k)` pairs so the low byte wraps
inside each pair, spanning more than one high byte. On the committed level that
still selects 255/256:

```
info 8-bit boundary pairs chosen from worldProgress 240: [255, 256, 511, 512] then [1279, 1280, 1535, 1536]
ok   the chosen rows are all ahead of the world and straddle 8-bit boundaries -- the low byte wraps inside every pair
ok   ...and they span more than one high byte -- high bytes [0, 1, 2, 4, 5, 6]
```

`test_pickup` and `test_movement_pool` each hit the harness's known boot flake
(`RuntimeError: the lifecycle never reached PLAYING: gsState = 3`) — the same
flake that hit `test_movement_pool` in the *baseline* run on the unmutated tree.
Not content-related. Re-run, with the boundary fix in place:

```
wave_triggers    PASS
pickup           PASS
movement_pool    PASS
```

**All twelve runtime suites and all 45 editor suites pass against a Level 1 whose
trigger count, species, wave references, speeds, colours, colour modes, fire masks
and firing modes are every one of them different from the committed level.** That
is the claim the task asked to be demonstrated.

---

## Remaining issues

**`gameOverrun` in `test_wave_triggers` was a pre-existing failure and is now a
scoped assertion.** It counts displayed frames the main thread did not prepare one
for and must read zero. Staged sampling, added by this task, locates every
increment precisely:

```
info gameOverrun = 0 after the authored-table reads, before the world is driven (worldProgress 0)
info gameOverrun = 0 after part 2 -- the authored schedule, collected at a breakpoint (worldProgress 240)
info gameOverrun = 4 after parts 3 and 4 -- the eight boundary rows, with long approaches (worldProgress 1658)
info gameOverrun = 4 after part 5 -- the token hold, stepped frame by frame (worldProgress 1730)
info gameOverrun = 4 after part 6 -- three more old periods of free running (worldProgress 2128)
```

Zero through the whole authored schedule and 240 coarse rows of real gameplay;
every increment inside parts 3 and 4, which resume the machine with a 0.05 s
deadline, sleep while it runs, and then **halt it again with a read**, hundreds of
times. A halt across a frame boundary is indistinguishable, to this counter, from
a frame the game failed to prepare — and the total varies run to run with wall
clock (3 on the baseline run, 4 on the next), which a deterministic engine miss
would not. `test_flight_paths` watches 900 production frames of the same engine
without the bursts and reads 0.

So the counter is **asserted** over the phases that run normally and **reported**
over the probing phases — the same treatment this file already gives `publishSkip`
and `schedBuildDefer`. Accepting any value would lose a real regression; asserting
across the bursts fails on the instrument rather than the engine.

**Two generators still own `src/levelN/stage_enemies.asm`** — the editor exporter
and `tools/sprite_export/import_spd.py`. Flagged in an earlier task and unchanged
here; `test_multi_level_layout` now asserts the exporter's actual behaviour
(regenerate, do not carry forward), which is what `export_v6.py` documents.

**The harness's boot flake.** `Vice._boot_to_game()` presses fire up to eight
times waiting for `GS_PLAYING`, and under CPU contention — two emulators at once,
which this task's proof runs created — all eight presses can be missed and the
suite dies before its first check. It bit `test_movement_pool` once in the
baseline and `test_pickup` and `test_movement_pool` once each in the proof-A run;
every re-run passed. Raising the retry count is a one-line change, but it is
lifecycle behaviour rather than content freezing and could mask a real
ATTRACT→PLAYING regression, so it is reported rather than changed.

**`tests/movement_trace.py`** still names `("sweep", 0, 0, 64, 0, 200)`. It is a
diagnostic script, not a test, and is in no tier. Left alone.

**Species constants spelled by legacy name.** `tests/test_dropper_flight.py`,
`test_enemy_fire.py`, `test_species_order.py` and `test_square_species.py` carry
`SPECIES_RING, SPECIES_DROPPER, SPECIES_SQUARE = 0, 8, 16`. Those are the engine's
**slot row offsets**, not authored content, and each of those suites pokes the
species column rather than reading it — so they are content-independent and pass.
The names are a legacy spelling worth tidying when one of those files is next
touched; no assertion depends on which artwork a slot holds.

---

## Files changed

**New (3):**

```
tests/campaign_data.py                    262 lines
tests/synth.py                            230 lines
tools/level_editor/fixtures_v6.py         211 lines
```

**Modified — runtime tests (12):**

```
tests/harness.py                     de-contented one comment
tests/test_aimed_fire.py             the aim law; derived TRIGN; slot-named species
tests/test_aimed_velocity.py         derived TRIGN
tests/test_campaign.py               derived look() and campaign sequence
tests/test_flight_paths.py           deliberate primitive coverage
tests/test_level_identity.py         derived package addresses
tests/test_movement_pool.py          derived pool size, arc contexts, synthetic primitives
tests/test_no_spawn_row.py           synthetic schedule + a new authored-row invariant
tests/test_pickup.py                 derived trigger count and approach address
tests/test_trigger_speed.py          synthetic specimen throughout
tests/test_wave_colour_mode.py       synthetic FIXED/RANDOM and the shared pair
tests/test_wave_triggers.py          read the authored table; staged gameOverrun
```

**Modified — editor (13, two of them production code):**

```
tools/level_editor/controller_v6.py               suggested_species() defect fix
tools/level_editor/import_engine_v6.py            ninth column, trigSpeed import, identities
tools/level_editor/test_encounter_library.py      ownership-separation invariants
tools/level_editor/test_encounters_gui.py         fire-mask scaffolding
tools/level_editor/test_movement_sim.py           stale colour= kwarg; fixture trigger section
tools/level_editor/test_multi_level_layout.py     derived slot offsets; level-count invariant
tools/level_editor/test_preview_gui.py            arranged specimens
tools/level_editor/test_preview_trigger_speed.py  builds its own program and wave
tools/level_editor/test_v6_import.py              species by row; structural corruption fixtures
tools/level_editor/test_v6_phase4_roundtrip.py    derived capacity, both sides
tools/level_editor/test_v6_phase5b_encounters.py  operates on a referenced definition
tools/level_editor/test_v6_phase6a1_hotfixes.py   level identities; no silent skip
tools/level_editor/test_v6_roundtrip.py           stable-not-frozen key order
```

**Not touched:** every `tools/level_editor/levels/*/level.v6.json`, the shared
`encounter_library.v6.json`, every `src/levelN/*.asm`, every engine source file
except the two editor modules named above. No authored level was edited to make a
test pass.

---

## Disk usage

The session scratchpad held the baseline and after-run logs, an 8.4 MB `rsync`
copy of the tree for proof A, and several throwaway `shutil.copytree` build trees
for proof B (each deleted immediately after its build). All of it is outside the
repository and none of it is committed. Inside the repository, the only growth is
the three new source files (703 lines) and this report.

## Commit status

**Nothing committed and nothing pushed.** No `git checkout`, `git restore`,
`git reset`, `git stash` or destructive clean was used at any point; the scratch
copy was made with `rsync` and the throwaway build trees with `shutil.copytree`.
