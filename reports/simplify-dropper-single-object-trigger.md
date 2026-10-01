# 19656 — Simplify Dropper to a Single-Object Trigger

**Date:** 2026-09-30
**Scope:** implementation. The composite Dropper+escort encounter is removed. A
Dropper Trigger spawns exactly one Dropper; an ordinary Trigger spawns an
ordinary Wave; company for a Dropper is a second, independent Trigger authored
nearby.
**Working tree:** dirty, preserved. No commit, no push. No campaign content
edited.

---

## 1. The new contract, in four lines

> A **Dropper Trigger** spawns exactly **one** object. It is the Dropper.
> An **ordinary Trigger** spawns its Wave Definition's formation, as always.
> There is no engine concept of a Dropper escort.
> A Dropper with company is two Triggers a row apart.

Nothing links them: no encounter id, no pairing field, no same-row coupling, no
simultaneity machinery. The existing forward-only trigger cursor schedules both.

---

## 2. What was removed from the composite model

| Removed | Where it lived |
|---|---|
| member 0 = the Dropper candidate, members 1..N-1 = escorts | `src/waves.asm` species seam |
| escort substitution with `lvlPlainRow` | same seam (`!escort:` branch) |
| the Dropper consuming formation slot 0, and the "hole" left behind | spawn placement + preview |
| the definition's member count driving a Dropper's spawn count | `waveArm` |
| fire-mask bit 0 as the Dropper's special, inert bit | `src/waves.asm` firing block |
| composite preview (member 0 Dropper + N-1 escorts from one trigger) | `movement_sim.simulate_trigger` |
| composite validation (mask members checked against a Dropper's count) | `validation_v6` |
| "escorts stay escorts after `tkDropperLive` is cleared" | `tests/test_dropper_escort_contract.py`, **deleted** |

The `!escort:` label and every read of `lvlPlainRow` are gone from the wave
director. `lvlPlainRow` itself **stays**: `src/token.asm:731` uses it for token
protectors, which is a different system and out of scope.

**No dead compatibility branch was left behind.** The composite architecture
existed only during development; nothing persisted needs it, because the one
thing persisted data does carry — a multi-member definition behind a Dropper — is
handled by forcing the count at runtime rather than by a migration path.

---

## 3. Start-position representation, and why

### The decision

**A Dropper Trigger keeps its Wave Definition reference, and that definition is
its PLACEMENT.** The engine arms the instance with `wvLeft = 1` whatever the
definition's count says, so what remains readable of the definition is exactly:

```
startX, startY   the Dropper's start position
heading          its launch heading
```

`count`, `interval`, `xStep`, `yStep` and the definition's own `program` are
inert for a Dropper.

### Why this rather than new fields

A Wave Definition **with `count = 1` already IS "one object's placement and
heading"**. That is not a coincidence to exploit; it is what the record reduces
to when the formation fields fall away. The brief asked to prefer an existing
sensible single-object representation, and this is one.

The alternative was three new Trigger columns (`startXLo`, `startXHi`, `startY`)
and possibly a fourth for heading:

| Columns | Derived capacity |
|---|---|
| 10 (today) | **108** |
| 13 (+ position) | 83 |
| 14 (+ heading) | 77 |

That is a 23–29 % capacity cost to duplicate a representation the schema already
has, and the brief is explicit that clarity beats recovering slots and that the
format should not churn. Level 1 uses five triggers.

### The one real objection, and the answer

A definition is **shared**, so two Dropper Triggers pointing at one definition
share a start position. That is the same reusability an ordinary wave gets, and
two Droppers at different positions need two definitions exactly as two ordinary
waves at different positions do. It is coherent rather than surprising.

### Why the count is FORCED, not required

`waveArm` forces one member instead of the validator demanding `count == 1`:

* a definition may legitimately be referenced by a Dropper Trigger **and** by an
  ordinary Trigger that really does send six — rewriting its count would break
  the ordinary encounter;
* it is what makes a project authored under the short-lived composite model load
  as one Dropper **with no migration of authored data at all.**

The editor and validator say what is inert instead of changing it (§8, §9).

---

## 4. Final Trigger record and capacity

**Unchanged by this pass.** Ten parallel columns, and the tenth
(`trigDropProg`) remains the cleanest representation of Legacy-vs-authored
movement — simplifying the model gave no reason to move it, and churning the
format to recover slots was explicitly not wanted.

```
rowLo · rowHi · def · species · fire · side · colour · fireMode · speed · dropProg

LEVELPKG_TRIG_RESERVATION = 1600 - 2 - 256 - 260   = 1082
LEVELPKG_TRIG_SLOTS       = floor(1082 / 10)       = 108
emitted footprint         = 10 × 108 = 1080 of 1082   ($f736-$fb6d, 2 spare)
```

Capacity is derived at both ends (`src/levelpkg.asm` by `floor()`,
`contract_v2` by `//`) and written as a literal nowhere.

**What the columns mean for a Dropper Trigger now:** `rowLo/rowHi` its
activation row; `def` its **placement**; `species` that it is a Dropper;
`side` the legacy entry edge; `colour` its colour; `speed` its pace;
`dropProg` Legacy or an authored program. `fire` and `fireMode` are **not read**.

---

## 5. The runtime seam

### One member, forced at arming

```asm
    jsr waveDefBase
    lda waveDefTable + 0,y              ; the definition's count...
    ldy wvSpecies,x
    cpy lvlDropRow
    bne !count+
    lda #1                              ; ...unless this is a Dropper Trigger
!count:
    sta wvLeft,x
```

### The interlock refuses before allocating, and creates nothing

```asm
waveSpawnMember:
    jsr waveDefBase
    sty wvDefBase
    stx wvInst
    lda wvSpecies,x                     ; X is still the instance
    cmp lvlDropRow
    bne !mayspawn+
    lda tkDropperLive
    beq !mayspawn+
    jmp waveSpawnRefused                ; out of branch range; the file's idiom
!mayspawn:
    jsr objectAlloc
```

`waveSpawnRefused` returns **carry clear** — the member is *spent*, so the
instance retires — where `waveSpawnFull` returns carry set to *defer*. The
distinction matters: a full pool is momentary and deferring is right; a live
Dropper may be on screen for hundreds of frames and there is no formation to hold
a place in. Tested **before** `objectAlloc`, so a refused Dropper never takes a
pool slot and hands it straight back.

### The species seam, with nothing composite left

```asm
    ldy #WV_DROP_NONE
    sty wvDropMode                      ; unconditional: module scratch
    cmp lvlDropRow
    bne !species+
    ldy #1
    sty tkDropperLive                   ; cannot fail: checked at entry
    ldy wvInst
    lda wvDropProg,y
    cmp #TRIG_DROP_LEGACY
    beq !legacy+
    ...
```

No member index is consulted, no escort is manufactured, no formation slot is
consumed. The interlock claim **cannot fail**, because a Dropper that reaches
here is one the entry guard already admitted.

### The fire mask is not consulted for a Dropper

```asm
    lda wvDropMode
    bne !noFire+                        ; a Dropper: src/dropper.asm decides
```

This is the **removal** of a special case, not a new one. A mask is a mask over
member index; a Dropper Trigger has no members to index. Under the composite
model bit 0 nominally addressed the Dropper and was documented as inert — two
rules where none is needed. `src/dropper.asm` withdraws the permission outright,
so consulting the mask first and overriding it a hundred instructions later only
ever reached the same answer twice.

### Cost to the ordinary case

One indexed load and one compare at arming; one indexed load and one compare at
spawn entry, on a path every ordinary member already walks. Per frame: nothing
new. `src/enemy.asm`'s `drMode` dispatch is unchanged from the previous pass.

---

## 6. Legacy vs authored movement

| | Legacy (`TRIG_DROP_LEGACY`) | Authored (a program) |
|---|---|---|
| Objects spawned | **1** | **1** |
| Mover | `dropperFly` | `wmTick` |
| Start position | `DROP_ENTRY_LEFT/RIGHT` at `DROP_CENTRE_Y` | **its own authored placement** |
| Trigger speed | ignored (`wmApplyVelocity`, never `wmApplySpeed`) | applies, quarter-scale |
| Launch heading | not read | applies, via the definition's `wmPhase` |
| LEFT/RIGHT | the entry edge | **not read** |
| Sonar ping | yes | yes |
| Fires | no | no |
| Token on death | yes | yes |

Faster authored arcs and loops remain **intentionally wider** — linear velocity
scales, angular progression does not. Not corrected, by instruction.

---

## 7. Already-live interlock behaviour

**A refused Dropper Trigger creates nothing at all.**

The composite model substituted the level's ordinary enemy, because the wave
around the Dropper had an authored count and shape that losing a member would
have rewritten. There is no wave around it now. The authored encounter was "a
Dropper here"; if one is already flying, that moment has nothing to say, and
manufacturing an unrelated ordinary enemy would be inventing content the level
never asked for.

Measured: `wvSpawned +0`, **0 live enemies**, species `[]`, `wvDropRefused 0 → 1`,
`wvActive [0, 0]` (the instance retired rather than retrying), `gameOverrun 0`.

A new saturating counter `wvDropRefused` makes the refusal **provable** rather
than inferred from an absence of enemies.

---

## 8. Editor changes

* **The wave-definition field relabels itself.** For an ordinary Trigger it reads
  `wave definition`; for a Dropper it reads **`placement`**, with a note saying
  "one Dropper: start position and launch heading". Calling it a wave definition
  over a single Dropper is what would imply the escorts this pass removed.
* **When the definition sends more than one**, the note says so in warning colour
  and names the count as not read — so a migrated Trigger explains itself in
  place rather than looking wrong.
* **No fire checkboxes at all for a Dropper** — not one disabled box for a
  notional member 0, which would still imply the formation. The note reads "a
  Dropper is one object and does not fire — for company, add an ordinary trigger
  a row away", which is also where the new authoring workflow is taught.
* **The trigger list** shows `1 Dropper` in a column now headed **sends** (was
  `fires`), and the last column is headed **flight** and carries the entry side
  for Legacy or the program for authored.
* **Retained** from the previous pass: the `Dropper movement` selector (Legacy
  first, then the level's programs), speed, heading, and LEFT/RIGHT disabled and
  labelled "not used" when authored movement is selected.
* **No "escort Trigger" type was added.** An escort is an ordinary Trigger.

---

## 9. Validation changes

* `trigger.fire_member_absent`, `trigger.fire_member`, `trigger.fire_width` and
  `trigger.fire_mode_unused` **no longer apply to a Dropper**. Reporting "member
  3 does not exist" against an encounter with no members would be a fault in a
  field nothing reads.
* **`trigger.dropper_fire_mask_ignored`** (warning) — a mask left on a Dropper is
  inert; almost always left over from a species change, and free to clear.
* **`trigger.dropper_definition_count`** (warning) — raised **only when no
  ordinary Trigger shares the definition**, i.e. only when tidying the count to 1
  is safe and free. A shared definition's count is not cruft, and a warning
  nobody can act on without breaking the other encounter is worse than silence.
* `trigger.dropper_program_missing` / `_ignored` (errors) retained from the
  previous pass.

Both production levels still validate, with these advisories naming exactly which
fields went inert.

---

## 10. Preview changes

`simulate_trigger` now branches once: an ordinary Trigger simulates its wave; a
Dropper Trigger goes to a new `simulate_dropper`, which forces `count = 1` for
the same reason the runtime does and draws **one path**. Legacy draws the actual
`src/dropper.asm` trajectory (constants parsed from that file, not retyped);
authored draws the program from the Trigger's own placement, at its speed and
heading, with high-speed widening preserved.

**No phantom escorts are drawn from a Dropper Trigger** — asserted as "at most one
object on every frame", not merely "one path".

Cache keys: `dropper_program`, `dropper_side`, `resolved_speed` and the Dropper
program's own stages all remain in `PreviewPanel._signature`. Nothing composite
was in the key, so nothing needed removing; the previous pass's speed fix is
intact and re-asserted.

---

## 11. Migration and backward compatibility

* **No schema version bump, and no field added or removed.** `dropper_program`
  keeps its meaning and its absent/`null`/empty-string → Legacy defaulting.
* **A composite-era Dropper Trigger loads as one Dropper.** Its definition's
  count is forced to 1 at spawn; the definition on disk is untouched.
* **No escort Triggers are invented during migration.** Authors add an ordinary
  Trigger where they want one — the brief's requirement, and the reason the count
  is forced rather than migrated.
* The canonical `level.v6.json` documents remain **byte-for-byte JSON fixed
  points**, and export → import → export is still a fixed point.

---

## 12. Token/lifecycle verification

Unchanged and verified on the machine: the one-live interlock, token creation on
destruction, death/despawn cleanup and interlock release, collision, damage,
scoring and the sonar ping. An authored Dropper killed through the engine's own
staged death path releases the interlock and starts the encounter
(`tkStarted 0 → 1`) with `gameOverrun 0`.

The known token protector/egress interaction with unrelated live enemies was
**out of scope** and not touched.

---

## 13. Tests

**Deleted:** `tests/test_dropper_escort_contract.py` (388 lines). Its purpose was
the composite contract — member 0 vs escorts, escort substitution, fire-mask bit
0, escorts surviving a cleared `tkDropperLive`. Everything in it that was about
the Dropper rather than the composite now lives in the rewritten runtime test.

**Rewritten:** `tests/test_dropper_movement_program.py` around the single-object
contract. Sections 1–2 now prove one object from a **deliberately four-member**
definition; 5 proves the refusal creates nothing; **5b is new** — a Dropper on row
N and an ordinary wave on row N+1, sharing one definition, so that if the count
could leak into the Dropper this is where it would.

**Updated because they were riding on composite behaviour:**
`tools/level_editor/test_movement_sim.py`, `test_dropper_movement.py`,
`acceptance_dropper_movement.py`.

**Updated because they were accidentally riding on trigger 0 being a Dropper** —
a real content-coupling, fixed by selecting an ordinary trigger *by behaviour*:
`test_encounters_gui.py`, `test_v6_phase5b_encounters.py`.

**Updated fixtures** to express the new model (a Dropper carries no mask, and a
Dropper-only definition has count 1): `test_v6_validation.py`. The strict
`expect_clean` helper was **not** weakened. `test_v6_import.py` gained the two
Dropper advisories to its existing `_ADVISORY` allow-list, which is that
mechanism's purpose.

### Brief coverage

| # | Requirement | Where |
|---|---|---|
| 1 | one object regardless of legacy count | runtime §1, §2 |
| 2 | that object is the Dropper | runtime §1 |
| 3 | no `lvlPlainRow` escorts | runtime §1, §2, §5 |
| 4 | nearby ordinary Trigger sends its full wave | runtime §5b |
| 5 | adjacent-row activation through the existing scheduler | runtime §5b |
| 6 | interlock blocks a second, with no implicit wave | runtime §5 |
| 7 | Legacy unchanged for the single Dropper | runtime §1, §8, §8b |
| 8 | authored program works | runtime §2, §3 |
| 9 | authored uses its own start position | runtime §2, §4 |
| 10 | speed 1×/1.5×/2× | runtime §6 |
| 11 | high-speed loops widen | runtime §7 |
| 12 | initial heading | runtime §9 |
| 13 | LEFT/RIGHT legacy-only | runtime §8 |
| 14 | token/lifecycle | runtime §10 |
| 15 | preview shows one Dropper, no escorts | editor + `test_movement_sim` |
| 16 | editor enables/disables correctly | editor + acceptance |
| 17 | missing movement data defaults to Legacy | editor |
| 18 | save/reload/export deterministic | editor |
| 19 | invalid references / unsafe paths reject | editor + build-time |
| 20 | capacity derived from record size | editor |

---

## 14. Results

### The runtime contract, on the machine

`tests/test_dropper_movement_program.py` — **ALL PASS**, 11 sections, 20 VICE
sessions, all reaped.

The discriminating fixture is a Dropper Trigger behind a **four-member**
definition — the arrangement that produced one Dropper and three escorts under
the composite model:

```
definition sends 4, legacy    → 1 object  DROPPER  stage 76  x=0    y=88  vx=+12       drMode=0
definition sends 4, authored  → 1 object  DROPPER  stage 84  x=120  y=60  vx=-5 vy=+4  drMode=1
definition sends 1, authored  → 1 object  DROPPER  stage 84  x=120  y=60  (identical placement)
```

No `lvlPlainRow` escort appears in any of them; species seen is `[8]` with
`plainRow 0`.

**Already live** — the refusal creates nothing:

```
wvSpawned +0 · live enemies 0 · species [] · wvDropRefused 0 → 1
wvActive [0, 0]  (the instance retired, it did not retry) · gameOverrun 0
```

**Adjacent rows, one shared definition** — the new authoring model, and the
strongest form of the leak test:

```
row N    mbr 0  DROPPER   stage 84  x=120
row N+1  mbr 0  ordinary  stage 76  x=120
         mbr 1  ordinary  stage 76  x=148
         mbr 2  ordinary  stage 76  x=176
         mbr 3  ordinary  stage 76  x=204
5 activations · Dropper on its own program · wave on its own, at its own offsets
```

**Speed**, Dropper and the independent ordinary wave each scaled from their own
authored velocity by the same trigger speed:

| speed | authored Dropper | ordinary wave |
|---|---|---|
| 4/4 | (−5, +4) | (+6, 0) |
| 6/4 | (−7, +6) | (+9, 0) |
| 8/4 | (−10, +8) | (+12, 0) |

**Arc widening** over the 72 frames both speeds survived:
1× span (48, 76) → 2× span (97, 153).

**LEFT/RIGHT**: legacy `LEFT (0, +12)` / `RIGHT (343, −12)`; authored
`LEFT (120, −5)` / `RIGHT (120, −5)` — identical, the side reaching nothing.
Legacy still crosses at `DROP_VX` at every trigger speed.

**Heading**: 0 → (+6, 0), 16 → (0, +6), each the engine's own table entry.

**Token lifecycle**: interlock held while alive, released on death,
`tkStarted 0 → 1`, `gameOverrun 0`.

**Flight integration**: descends exactly one pixel per frame (a 4-quarter-pixel
leg has no sub-pixel remainder — something the legacy weave cannot do), and
drifts left 29 px over 23 frames against an exact 28.75.

### Focused suites

| Suite | Result |
|---|---|
| Editor: all 45 files | **PASS** |
| `test_dropper_movement.py` | **94 checks pass** |
| `acceptance_dropper_movement.py` (real editor, real Tk) | **38 steps, all clear** |
| `test_movement_sim.py` | **100 checks pass** |
| `test_v6_validation.py` | **68 checks pass** |
| `test_encounters_gui.py` | **61 checks pass** |
| `test_v6_phase5b_encounters.py` | **74 checks pass** |
| `test_v6_import.py` | **82 checks pass** |
| Runtime: `dropper_flight`, `token_encounter`, `species_order`, `wave_triggers`, `movement_pool`, `trigger_speed`, `no_spawn_row`, `lifecycle`, `campaign` | **PASS** |

### `make smoke`

**PASS.** 3,899 frames; `gameOverrun`, `scrollLate`, `edgeLate`, `statOverflow`,
`statPageMismatch`, `statPtrMismatch`, `objDoubleFree`, `objAllocFail`,
`clipPoolFull`, `publishSkip`, `schedBuildDefer`, `statLate` **all zero**.
ENGINE HEALTH: PASS. ROUTINE REGRESSION: PASS.

### Bounded Dropper/token/flight soak

`dropper_movement_program` PASS · `pickup` PASS · `p_economy_colours` PASS ·
`flight_paths` PASS.

`pickup` failed on its first run and **passes serially on an idle machine** — I
had `make smoke` launching its own VICE alongside the soak. `tests/harness.py:350`
documents the warp boot loop as wall-clock sensitive; loading the machine while it
runs is my error, not a regression, and it is the second time in this session I
have made it.

### Manual Tk acceptance

`tools/level_editor/acceptance_dropper_movement.py`: **38 steps, all clear**
against the real `editor.LevelEditor` and the real `EncounterWorkspace` on Tk
8.6, windows withdrawn so no focus was stolen, both committed documents
byte-identical afterwards. It now asserts the preview shows **exactly one object
with no escort implied** in both Legacy and authored modes.

**STATED PRECISELY: this drove the real GUI PROGRAMMATICALLY. It is not a human
looking at pixels.** `AGENTS.md` rule 2 makes visible output authoritative, so a
human visual pass is still required; the script says so in its own output. The
brief's remaining acceptance items — that a Dropper Trigger *visually* represents
one Dropper, and that adding an ordinary Trigger on the next row is comfortable
to author — are judgements only a person at the screen can return.

### The one still-failing runtime test, stated plainly

`test_encounter_director` fails with the **byte-identical** two checks it fails at
pristine HEAD, `longest streak 0` included: it wants two wave instances active
concurrently, and Level 1's authored schedule no longer provides that.

**It is fair to note this pass works against what that test measures.** A Dropper
Trigger used to hold its instance active for `count × interval` frames while
sending six members; it now sends one and retires immediately, so Dropper
instances are much shorter-lived. That cannot make an already-zero streak worse,
and the failure predates this work — but the test's premise is now further from
the engine's behaviour, and it belongs in the de-freezing pass listed in §16
rather than being quietly counted as unrelated.

---

## 15. Files changed

**Engine:** `src/waves.asm`
(`src/dropper.asm`, `src/enemy.asm`, `src/levelpkg.asm`,
`src/level_package.asm`, `src/encounter_format.asm` carry the previous pass's
changes and were **not** further modified by this one.)

**Editor:** `movement_sim.py` · `validation_v6.py` · `encounters_ui.py`

**Tests:** deleted `tests/test_dropper_escort_contract.py`; rewrote
`tests/test_dropper_movement_program.py`; updated
`tools/level_editor/{test_movement_sim,test_dropper_movement,acceptance_dropper_movement,test_encounters_gui,test_v6_phase5b_encounters,test_v6_validation,test_v6_import}.py`

**Generated data and campaign content: unchanged.** No level document, no
`wave_encounters.asm`, no `wave_programs.asm`.

---

## 16. Follow-ups

* **Per-identity / reduced Dropper HP** — still the next independent
  gameplay/data feature, and unaffected by anything here. Every enemy including
  the Dropper is `ENEMY_MAX_HP`.
* **Tidying the campaign's Dropper Triggers** is now a one-click authoring job the
  editor explains in place: clear the inert fire masks, and where a definition is
  used only by Droppers set its count to 1. Deliberately not done here —
  campaign content is the author's.
* **`src/enemy.asm:168`** still names the retired `enemyAnimShape` in a stale
  `.error` string. Harmless, reported before, still unfixed.
* **Nine pre-existing runtime-suite failures** (five frozen against an older
  Level 1, four exposed to the documented warp-boot flake) remain; all fail at
  HEAD independently of this work and want their own bounded de-freezing pass.
* **The escort identity is not selectable**, and no longer needs to be: an escort
  is an ordinary Trigger with its own identity.
