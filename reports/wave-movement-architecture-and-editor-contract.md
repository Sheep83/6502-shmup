# Current wave / movement architecture review and editor contract design

**Date:** 2026-09-17
**Engine HEAD:** `722dbbd` — *HUD bank switching, token progress*
**Scope:** investigation and architecture only. No production code changed, nothing committed, nothing pushed.
**Supersedes, in part:** `reports/level-editor-current-engine-contract-review.md` — two of its findings are corrected below (§9.1, §3.5).

---

## Executive findings

1. **The movement engine is far more capable than any existing abstraction over it.**
   `src/movement.asm` is a five-primitive, four-byte-per-stage interpreter over a 64-direction
   heading table with quarter-pixel signed velocity and per-object remainders. Arcs rotate a
   *persistent heading*, so stages compose: loops, S-turns, hooks and glides are **orderings**
   of the same primitives, not new modes. The old editor's 12-entry attack catalogue cannot
   express most of this.

2. **The current engine's data model is already the right decomposition.** Trigger → wave
   definition → formation → launch heading → movement programme → firing mask is exactly the
   layering the brief proposes. It does not need redesigning; **it needs generating**. The four
   named definitions are hard-coded *content*, not a bad *schema*.

3. **The four named definitions (`defSweep`/`defSTurn`/`defLinger`/`defLoop`) are stale as
   vocabulary but sound as records.** The 10-byte definition record should survive verbatim;
   the four names should not become the editor's public choices.

4. **There is an unchecked, hand-maintained semantic invariant.** `WM_STRAIGHT`/`WM_HOLD` set
   velocity but **never update `wmPhase`**, so an arc following a straight leg resumes from the
   *launch* heading, not from the straight leg's direction. All four authored programmes keep
   straight velocity numerically identical to their launch heading's table entry (verified, §1.7),
   and **no assembler check enforces it**. An editor that lets a user set a straight leg's
   direction freely would silently produce velocity discontinuities.

5. **A hard ceiling nobody is near yet: `wmStage` is one byte**, so the *entire* stage table
   across all programmes must stay ≤ 256 bytes = **64 stage records**. Currently 52 bytes / 13
   records. This bounds the *programme library*, not the encounter count — which is why
   encounters must reference shared programmes rather than carry their own.

6. **`waves.asm`'s "only author of enemy spawns" claim is false.** `src/token.asm:743` creates
   `TYPE_ENEMY` protectors directly. Architecturally defensible (engine-owned state machine),
   but the comment is a stated invariant the code violates.

7. **Memory correction (important).** The previous review recommended relocating level data into
   "`$9cec-$bfff`, ~8.9 KB free". **That region is not free.** `$a000-$bfff` (8 KB) is the VIC
   bank-2 static mirror (`vicMirrorStatic`, `src/vicbank.asm:306`), and `$8c00-$8fff` is bank 2's
   screen matrix — **declared by no KickAssembler segment, so it appears as a gap in the build's
   memory map**. Real free space is fragmented (§9).

8. **Per-member variation is mostly unnecessary.** Two co-located triggers already express
   "mixed species" and "one member flies differently" for 6 bytes and zero engine complexity.
   Only one per-member field is worth adding: a **mirror mask** (§6).

---

## 1. Current movement primitive inventory

`src/movement.asm`, 455 lines, code at `$7800-$7998` (409 B: ~281 B interpreter + 128 B heading table).

### 1.1 The primitives

| # | symbol | arg (byte 1) | byte 2 | byte 3 | termination |
|---|---|---|---|---|---|
| 0 | `WM_STRAIGHT` | frames | `vx` signed ¼px | `vy` signed ¼px | timer hits 0 → next stage |
| 1 | `WM_ARC` | heading **steps** | frames per step (**radius**) | unused | steps exhausted → next stage |
| 2 | `WM_ARC_MIRROR` | heading steps | frames per step | unused | as `WM_ARC`, anticlockwise |
| 3 | `WM_EXIT` | — | — | — | **terminal**; despawn rule in `enemy.asm` ends it |
| 4 | `WM_HOLD` | frames | `vx` | `vy` | identical mechanism to `WM_STRAIGHT` |

`WM_STAGE_SIZE = 4`. `WM_MODES = 5`.

`WM_HOLD` is **mechanically identical** to `WM_STRAIGHT` (`wmTimedStep` serves both, `movement.asm:316`).
It exists so "deliberately loitering" is visible in `wmMode` rather than inferred from a small velocity.
That is a *semantic* distinction the editor should preserve, not collapse.

### 1.2 Coordinate and velocity representation

- Velocity: **signed quarter-pixels per frame**, one byte per axis (`wmVX`, `wmVY`).
- Per-object remainder `wmAccX`/`wmAccY`, 0..3.
- Integration (`wmApplyVelocity`, `movement.asm:256`): `sum = acc + v`; `delta = sum >> 2`
  **arithmetic** (via the `cmp #$80 / ror` idiom, twice); `acc = sum & 3`.
  Exact floor division, positive remainder, **no drift**.
- X is **nine bits** (`logX` + `logXHi`) with explicit carry/borrow propagation.
  Y is **eight bits** (`logY`).
- Speed granularity: 12.5 px/s. Arc speed `WM_ARC_SPEED = 6` ¼px = 1.5 px/frame = 75 px/s.

### 1.3 Direction, heading and mirroring

- `wmPhase`, 0..63, **clockwise from east**, +y down. Anchors asserted at assembly time
  (`movement.asm:130-141`): 0 = east, 16 = south, 32 = west, 48 = north.
- Table generated from `cos`/`sin`, never hand-written. Two proofs run over it:
  **smoothness** (no step moves a component by more than one ¼px, checked across the wrap) and
  **no zero-velocity heading**.
- Wrap is `AND #WM_HEAD_MASK` (63) — which is *the whole of "loops work"*: an arc of more than
  64 steps simply wraps and keeps turning. There is no loop primitive, no orbit centre,
  no angle accumulator.
- **Mirroring is a stepping direction, not a negation.** `wmLoadHeading` reads the table
  unmodified; `WM_ARC_MIRROR` differs from `WM_ARC` only in `+1` vs `-1` on the phase
  (`movement.asm:341-354`).

### 1.4 Radius

Frames-per-step (byte 2) **is** the turn radius, authored *per stage*:
radius = `WM_ARC_SPEED * f * WM_HEAD_LEN / (8π)` → **61 px at f=4, 31 px at f=2**.
A lazy hook and a tight dogfight loop are one primitive with a different byte.

### 1.5 Chaining and entry

- `wmStage` is a **byte offset** into `waveStageTable`; `wmEnterNext` adds `WM_STAGE_SIZE`.
- `wmEnterStage` is **both** the spawn path and the continuation path (`movement.asm:406`), so a
  programme's first stage cannot behave differently from the same stage mid-programme.
- **`WM_EXIT` does not reset velocity** — that is what makes `ARC → EXIT` continuous.
- Arcs load the heading's velocity **immediately** on entry rather than after one step.

### 1.6 Acceleration

**None.** There is no acceleration, deceleration or momentum primitive. Speed changes are
step discontinuities between stages (`LINGER`'s hold → arc jump is deliberately one, and its
comment says so). If smooth acceleration is ever wanted it is a **new primitive**, not a
parameter — and the four-byte record has room (`arg`=frames, byte2=`dvx`, byte3=`dvy`).

### 1.7 The unchecked invariant (verified)

`wmEnterStage` sets `wmVX`/`wmVY` for `WM_STRAIGHT`/`WM_HOLD` but **does not touch `wmPhase`**.
A subsequent arc therefore resumes from the last heading an *arc* or the *launch* set.

Measured against the four authored programmes:

```
prog       launch heading  heading velocity  authored STRAIGHT vx,vy  match?
SWEEP                   0            (6, 0)                   (6, 0)   True
S-TURN                 12            (2, 6)   (first stage is an ARC)   n/a
LINGER                 10            (3, 5)                   (3, 5)   True
LOOP                    8            (4, 4)                   (4, 4)   True
```

Every straight leg is hand-matched to its launch heading. `LINGER`'s third stage is an arc that
follows a `(0,+1)` hold and resumes at heading 10's `(+3,+5)` — the "break away" the comment
describes is exactly this resume-from-stale-heading behaviour, used deliberately.

**The assembly-time validator does not check this.** Its checks (`waves.asm:360-400`) cover stage
lengths, `WM_EXIT` termination, arc frames-per-step ≥ 1, and X-speed vs the wrap clearance —
not heading/velocity agreement. **This is the single most important semantic for an editor
contract to get right.**

### 1.8 Formation and per-member behaviour

Members **share one programme** and get independent object state. Fan-out is in `waveSpawnMember`
(`waves.asm:1145-1185`): a *repeated add* of `xStep` (nine-bit, signed) and `yStep` (eight-bit,
signed), `wvIndex` times. No multiply.

Stagger is the definition's `interval` in frames. The header documents the mux constraint that
drives the choice between `yStep` and `interval`: a positive `yStep` on a **top-entering** wave
pushes later members *into view* rather than letting them arrive through the edge, so the three
top-entering patterns use `yStep = 0` and let the descent plus interval separate them. Only the
side-entering sweep uses an authored `yStep`.

### 1.9 Special-case movement

| thing | mechanism | generic? |
|---|---|---|
| **Dropper** | `dropperFly` **replaces** `wmTick` entirely (`enemy.asm:606`). Horizontal still goes through `wmApplyVelocity`; vertical is a 32-phase sine table. Three passes, authored entry side, exits the opposite side. State is **module-global** (7 B at `$c462`), legitimate because the one-live-Dropper rule is enforced at `waves.asm:1236`. | **No** — one-off choreography |
| **Protector / guard** | `tokenGuardMove` replaces `wmTick` for `enyRole >= ROLE_GUARD` (`enemy.asm:585`). 24-phase orbit ring, post = role offset. | **No** — one-off |
| **Egress (dismissed protector)** | `ROLE_EGRESS` is flown by **ordinary `wmTick`** on a terminal `WM_EXIT`. | **Yes** — reuses the generic path |
| **Boss** | `TYPE_BOSS`, four static cells, no movement at all. | n/a |

### 1.10 Runtime cost

**RAM, per object:** 10 bytes × `MAX_OBJECTS` (16) = **160 B** at `$7700-$779f`
(`wmMode`, `wmStage`, `wmPhase`, `wmTimer`, `wmSteps`, `wmVX`, `wmVY`, `wmAccX`, `wmAccY`, `wmBaseCol`).

**CPU** (static instruction counts, PAL frame = 19,656 cycles):

| path | cycles |
|---|---|
| `wmApplyVelocity`, no whole-pixel step | ~77 |
| `wmApplyVelocity`, both axes stepping | ~98 |
| `wmTick` dispatch ladder | ~21 |
| `wmTimedStep` (straight/hold, ordinary frame) | ~20 |
| `wmArcStep`, holding a heading | ~15 |
| `wmArcStep`, rotating (incl. `wmLoadHeading` + radius reload) | ~60 |
| **typical enemy-frame** | **~135** |
| **worst enemy-frame** (arc step + both axes moving) | **~190** |

8 concurrent movers ≈ **1,080–1,520 cycles (5.5–7.7 %)**.
Pool maximum of 16 (shared with projectiles) ≈ **2,160–3,040 cycles (11–15 %)**.
Comfortable. Movement is not the frame's problem.

---

## 2. The current wave pipeline

`src/waves.asm`, 1,415 lines. Code `$7c00-$7eda` (731 B), authored tables `$7edb-$7f4a` (112 B),
state `$77c0-$77da` (27 B).

### 2.1 Trigger → enemies, end to end

```
worldProgress (16-bit, +1 per coarse row, 1 row / 8 frames)
  │
  ├─ waveTick  ── lvlPhase != LP_LEVEL ? ─ yes → return (no spawns during boss)
  │              └─ 16-bit compare vs wvNextAtLo/Hi
  │                   └─ due? ── tkActive ? ─ yes → HOLD (walk target to worldProgress, cursor
  │                   │                              does not move, nothing is lost)
  │                   └─ waveStartNext
  │                        ├─ scan WAVE_SLOTS (=2) for a free instance
  │                        │    └─ none → wvDropped++, cursor STILL advances (drop, not queue)
  │                        ├─ latch def, species, fire mask, side onto the INSTANCE
  │                        ├─ wvLeft = def.count, wvTimer = 1, wvIndex = 0, wvActive = 1
  │                        └─ waveAdvanceCursor: cursor++, wraps at WAVE_TRIGGERS,
  │                                              wvNextAt += trigDelta[cursor]  ← DELTA, WRAPS
  │
  └─ per active instance: waveRunInstance
       └─ wvTimer-- → due → waveSpawnMember
            ├─ objectAlloc → full? → DEFER (wvTimer = 1, retry same member next frame)
            ├─ logX/logXHi/logY = startX/startY, then wvIndex × (xStep, yStep) repeated adds
            ├─ species latched; DROPPER → substituted with RING if one is already live
            ├─ fire permission = (encounter mask bit wvIndex) AND (species fire mode)
            ├─ logPtr = enemyAnimPtr (born in animation phase), logCol/wmBaseCol = def colour
            ├─ wmPhase = def.heading, wmStage = def.progOffset, wmEnterStage
            ├─ DROPPER → dropperLaunch OVERRIDES position/velocity/fire (after wmEnterStage)
            └─ objHP = ENEMY_MAX_HP, objType = TYPE_ENEMY, objectActivate
```

### 2.2 Records, exactly as they exist

**Wave definition — `WAVEDEF_SIZE = 10`**, table at `$7f0f-$7f36` (40 B):

| off | field | width | note |
|---|---|---|---|
| 0 | `count` | 1 | members sent |
| 1 | `interval` | 1 | frames between members |
| 2–3 | `startXLo/Hi` | 2 | nine-bit spawn X |
| 4 | `startY` | 1 | spawn line |
| 5 | `xStep` | 1 | signed, per member |
| 6 | `yStep` | 1 | signed, per member |
| 7 | `colour` | 1 | shared by all members |
| 8 | `heading` | 1 | launch heading 0..63 |
| 9 | `program` | 1 | **byte offset** of first stage record |

Field 9 is authored as an *index* and emitted as an *offset* (`waves.asm:1395`) so the 6502 never multiplies.

**Trigger — 5 parallel columns × 4 triggers = 20 B** at `$7f37-$7f4a`:
`waveTrigDelta`, `waveTrigDef`, `waveTrigSpecies`, `waveTrigFire`, `waveTrigSide`.

```
trigDelta   = 48, 4, 38, 36        ← DELTAS in coarse rows; the list WRAPS
trigDef     = SWEEP, S, LINGER, LOOP
trigSpecies = RING, DROPPER, RING, DROPPER
trigSide    = LEFT, LEFT, LEFT, RIGHT
trigFire    = %0101, %0010, %0101, %0000
```

Period = 48+4+38+36 = **126 coarse rows ≈ 20 s**, repeating for the whole 63-second stage.

**Stage table** at `$7edb-$7f0e` (**52 B**, 13 records): `progAt` = 0, 12, 24, 40.

### 2.3 Compile-time authored vs runtime-derived

| value | source |
|---|---|
| trigger deltas, def, species, side, fire mask | **compile-time** (`.var` lists in `waves.asm`) |
| wave definitions (all 10 fields) | **compile-time** |
| movement programmes (all stage bytes) | **compile-time** |
| `WAVE_FIRE_PERIOD`, fire band, muzzle offsets | **compile-time** |
| `wvNextAtLo/Hi` | runtime (running sum of deltas) |
| `wvActive/Def/Left/Timer/Index/Fire/Side/Species` | runtime (latched at arm) |
| member position | runtime (`startX + index × xStep`) |
| per-member fire permission | runtime (mask bit **AND** species mode), resolved once at spawn |
| Dropper live-claim / Ring substitution | runtime |
| `wvStarted/Dropped/Deferred/Spawned/Shots/ShotBlocked` | runtime diagnostics, saturating |

### 2.4 Policies worth preserving verbatim

- **Drop, don't queue**, on no free instance — a late encounter is worse than a missing one,
  because triggers are authored against *terrain*.
- **Defer, don't skip**, on a full pool — the wave stretches but never loses a member.
  This is what makes encounters deterministic under projectile pressure.
- **Hold, don't skip**, during a token encounter — the trigger is walked to `worldProgress`
  so it stays exactly due with no backlog.
- **One global firing opportunity**, round-robin over the pool. Fire density is a property of
  the **level**, not of the **population**. A missed opportunity is lost, not queued.

### 2.5 Stage end and boss

`waveTick` and `waveFireTick` both open with `lda lvlPhase / beq !playing / rts`.
`lvlPhase` leaves `LP_LEVEL` only when `worldProgress` reaches `STAGE_FINAL_VIEW_PROGRESS`
(= `STAGE_START_ROW`, derived from `STAGE_METATILE_ROWS`). So **there is no approach margin
today**: encounters can start on the last authored row, and `ARENA_CLEAR_DEADLINE = 200` frames
is the mechanism that empties the arena rather than a backstop.

---

## 3. Stale abstraction analysis

| layer | originally abstracted | what now exists beneath | still useful | redundant | **harmful to freeze** |
|---|---|---|---|---|---|
| **Old editor attack catalogue** (`ATTACK_TOP_TURN_LEFT` … 12 IDs) | a fixed *ingress → manoeuvre → egress* fragment chain with exit-class compatibility bits (old `main.asm:852-860`) | arbitrary-length sequences of 5 primitives over a persistent heading — strictly more general, no exit-class bookkeeping | the *idea* that entry and manoeuvre are separable | the IDs themselves | **Yes.** Each ID conflates **entry side + ingress + shape** into one opaque number. Freezing it re-imposes the old engine's 3-stage limit and its side/shape coupling |
| `attackIntervalData`, `attackSpriteStartData` | per-attack spawn interval and sprite/colour set | `interval` and `colour` are definition fields 1 and 7 | the two values | the tables | No — just dead. `.const ATTACK_` count in current `src/`: **0** |
| `ENEMY_TYPE_COUNT = 4`, `enemyType: 0..3` | four sprite/colour sets | `SPECIES_COUNT = 2`; species values are **animation ROW OFFSETS** (`SPECIES_RING=0`, `SPECIES_DROPPER=8`), not indices | nothing | the 0..3 range | **Yes.** An index where the engine wants a row offset is a silent wrong-art bug. `waves.asm:640` validates by **membership, not range**, precisely because of this |
| `composition: [{enemyType, count}]` (multi-entry) | mixed-species formations | **impossible**: `wvSpecies` is one byte per instance, latched at arm time | the total **count** | the multi-entry list | **Yes.** It promises something the engine cannot do. Mixed species = two co-located triggers (§6) |
| **The four named definitions** (`defSweep`…`defLoop`) | "the shapes the game has" | 4 definitions × 4 programmes, but the *records* are fully general | the **10-byte record** — keep it verbatim | the four **names** as a public vocabulary | Mild. Harmful only if the editor exposes "Sweep/S/Linger/Loop" as the choice set. They are engine-development content, not schema |
| `WAVE_DEF_*` / `PROG_*` constants | readable hand-authoring | byte offsets computed by `progAt` | readability in hand-written asm | nothing | No — but they must not survive into generated data |
| `spawnInterval` (nullable override) | per-wave pacing | definition field 1 | **maps 1:1** | nothing | No — keep |
| `worldRow` (absolute, 16-bit on export) | trigger placement | engine uses **deltas that wrap** | **the editor is right and the engine is wrong here** | nothing | No — the engine should adopt absolute |

**The one abstraction that must not be exposed raw:** `wmStage` byte offsets. The editor should
reference programmes by **identity**, and the exporter should compute offsets — exactly as
`progAt` does today. A hand-maintained offset is a number that is right until somebody inserts a stage.

---

## 4. Authoring granularity — the options, with costs

> **The question:** the smallest stable engine-defined vocabulary giving meaningful control over
> modern enemy movement without reimplementing the movement engine in Python.

### The constraint that shapes the answer

`wmStage` is **one byte**. `waves.asm:214`:

```
.if (progBytes > 256) { .error "the stage table has outgrown the one-byte cursor in wmStage" }
```

**The entire programme library across the whole level must fit 256 bytes = 64 stage records.**
Currently 52 B / 13 records → **51 records of headroom**. Any option where encounters carry
their own programmes blows this immediately; any option where they *share* a programme pool
fits comfortably.

### Option A — editor selects named engine programmes

Engine keeps a ROM catalogue; editor references IDs + supplies definition fields.

| axis | assessment |
|---|---|
| expressive power | **Low.** Bounded by the catalogue. A new shape = engine change + rebuild + re-review |
| ROM | programmes in engine ROM (52 B today); trigger 6 B each |
| RAM | **0 new** |
| CPU/frame | **0 new** |
| interpreter complexity | **0** — already exists |
| validation | trivial (ID range) |
| editor complexity | **lowest** — a dropdown |
| determinism / testability | excellent |
| new primitives | easy engine-side, invisible to editor until re-catalogued |
| formations / per-member | full (definition fields are orthogonal) |
| Python↔asm drift | **none** |
| 400-row level | fine |

**Verdict:** safe, cheap, and it re-creates the exact problem the brief is trying to escape —
the editor authoring against a frozen catalogue of shapes somebody else chose.

### Option B — editor emits stage bytecode

Editor composes stage sequences; engine interprets them unchanged.

| axis | assessment |
|---|---|
| expressive power | **Full** — everything the interpreter can do |
| ROM | 4 B/stage. Typical programme (2 stages + EXIT) = **12 B**; elaborate (5 + EXIT) = **24 B** |
| RAM | 0 new |
| CPU/frame | **0 new** — same interpreter, same records |
| interpreter complexity | **0 new**, *provided programmes are shared*; otherwise `wmStage` must widen to 16-bit, touching the hot path |
| validation | **the build already does it** — see below |
| editor complexity | moderate: a stage-list editor |
| determinism / testability | excellent (data is fixed at assembly) |
| new primitives | one new `.const` + one interpreter branch + one editor row type |
| formations / per-member | full |
| Python↔asm drift | **the real risk** — mitigated below |
| 400-row level | fine *if deduplicated* |

**The drift risk is smaller than it looks, and this is the crux.** The flight validator
(`waves.asm:340-480`) runs **at assembly time on whatever bytes are present** — it integrates
every path in quarter pixels using the same arithmetic the 6502 does, applies `enemy.asm`'s four
despawn rules frame by frame, and rejects a path that never leaves, never becomes visible,
walks X past zero, or materialises in view. **It does not care whether the bytes were
hand-written or generated.** So the editor does *not* need to reimplement movement semantics to
guarantee correctness — the build is the authority, and a bad export fails the build loudly.

The editor needs only *cheap structural* checks (stage count, `WM_EXIT` terminal, arg ≥ 1,
arc frames-per-step ≥ 1) to give fast feedback, plus one new check the engine does not have:
**heading/straight-velocity agreement** (§1.7).

### Option C — parameterised templates

Engine owns skeletons; editor fills in extent/radius/duration/direction within bounds.

| axis | assessment |
|---|---|
| expressive power | medium — between A and B, but the *shape* of the sequence is frozen |
| ROM | template table **plus** per-encounter parameter block: strictly more than B for less power |
| interpreter complexity | **new**: a template expander, or indirection at every stage read |
| validation | **hardest** — must prove every point in each template's parameter space is safe, or run the flight sim per instantiation anyway |
| editor complexity | moderate, and the bounds must be mirrored in Python → **drift risk higher than B** |

**Verdict: rejected.** It costs more machinery than B, delivers less than B, and increases the
very drift risk it is meant to reduce. Templates are what you build when the underlying
representation is dangerous; this one is four bytes and already proof-checked.

### Concrete byte comparison — a realistic level

10 distinct shapes, 20 formations, 50 encounters:

| | A | **B (shared pool)** | C |
|---|---|---|---|
| programmes | 52 B (engine ROM, fixed) | **~140 B** (10 × ~14) generated | ~80 B templates + 50 × 4 B params = 280 B |
| definitions | 20 × 10 = 200 B | **200 B** | 200 B |
| triggers | 50 × 6 = 300 B | **300 B** | 300 B |
| **total** | **552 B** | **640 B** | **780 B** |
| **new engine code** | 0 | **~0** | expander + validation |
| **shapes available** | 4 (fixed) | **unbounded ≤ 64 records** | 10 skeletons |

**B costs 88 bytes more than A and buys the entire movement engine.**

---

## 5. Formation versus movement

**They must stay separate, and the engine already separates them.** The 10-byte definition is
in fact two independent things that happen to share a record:

| formation (visual arrangement) | movement (the path) |
|---|---|
| `count`, `interval`, `startX`, `startY`, `xStep`, `yStep`, `colour` | `heading` (field 8), `program` (field 9) |

Two encounters that differ only in spacing, count, entry side or stagger **already** share a
programme — `program` is one byte naming a shared offset. Nothing is duplicated.

**Recommended decomposition** (which is what the engine does, stated explicitly):

```
trigger  ──(when: absolute 16-bit world row)
   └─ encounter ──(species, fire mask, Dropper side)
        └─ formation ──(count, interval, startX/Y, xStep, yStep, colour)
             └─ launch heading ──(0..63)
                  └─ movement programme ──(shared, by identity → byte offset)
```

**Shared:** movement programmes (a few per level), and formations across triggers.
**Independently configurable:** everything else, per trigger.

One caveat the editor must surface, because it is a *content* rule the engine cannot enforce:
**`yStep` is the mux-friendliness field.** A positive `yStep` on a top-entering wave pushes later
members into view instead of letting them arrive through the edge. Top-entering formations should
use `yStep = 0` and separate members by `interval` + descent; only side-entering formations
should use an authored `yStep`. The editor should warn, not forbid — it is a judgement about
where the wave enters.

---

## 6. Per-wave versus per-member control

Current per-member capability:

| variation | today | verdict |
|---|---|---|
| stagger / delay | ✅ `interval` (per wave, uniform) | keep |
| X / Y offset | ✅ `xStep`/`yStep` linear fan | keep |
| **firing permission** | ✅ **bitmask over member index** | keep — the model to copy |
| mirrored movement | ❌ | **add** (below) |
| movement phase offset | ❌ | reject |
| alternate exit direction | ❌ | reject — it is a different programme |
| different programme per member | ❌ | reject — use co-located triggers |
| species mixture | ❌ (one species per instance) | reject — use co-located triggers |

### The one addition worth making: a mirror mask

`trigFire` proves the pattern — **one byte, one bit per member, no new clock, resolved once at
spawn**. A `trigMirror` byte would let member *n* fly the programme with `WM_ARC` and
`WM_ARC_MIRROR` exchanged.

Cost: 1 authored byte/trigger, **1 byte/slot of RAM (16 B)**, one XOR at `wmEnterStage`'s arc
branch and in `wmArcStep`'s direction test — roughly **6 cycles per arc stage entry**, nothing
per frame. It **doubles the visual vocabulary of every existing programme** for essentially nothing:
a formation that splits, half hooking left and half right, from one programme.

### Why co-located triggers beat per-member fields

Two triggers at the same absolute row already give mixed species, mixed programmes, mixed
formations and mixed fire masks — for **6 bytes and zero engine change**. `waveStartNext` fires
one trigger per tick, so the second lands the following frame; `waveAdvanceCursor` handles it
naturally once rows are absolute.

The only limit is `WAVE_SLOTS = 2`. Raising it is cheap and the file says so explicitly
(`waves.asm:107`): *"The arrays, the loops and the free-instance scan are all written against
this constant, and no state is shared between instances, so raising it costs a few bytes of
state and no code at all."* **`WAVE_SLOTS = 4` costs 16 bytes of RAM and no code.**

That is the whole per-member answer: **one mirror mask, and more wave slots.**

---

## 7. Special encounters — ownership

| behaviour | engine-owned state machine | editor-authored |
|---|---|---|
| **Dropper flight** (3 passes, weave, ping, escape) | ✅ **all of it** — `dropper.asm`, module-global state, one-live rule at `waves.asm:1236` | **species byte + side byte on the trigger** (already the case) |
| **Dropper ⇒ P-token** | ✅ death hook → `tokenDropperDied` | nothing |
| **Protector / guard encounter** | ✅ **all of it** — ring geometry, posts, reinforcement, dismissal, egress | **nothing.** It is a *consequence* of a Dropper dying, not a placement |
| **Director hold during token encounter** | ✅ `tkActive` seam in `waveTick` | nothing |
| **Ring substitution** when a Dropper is already live | ✅ | nothing |
| **Boss approach / no-spawn** | gate in `waveTick` | ✅ **one generated constant** (below) |
| **Stage completion** | ✅ derived from `STAGE_METATILE_ROWS` | nothing |
| **Enemy fire cadence** (`WAVE_FIRE_PERIOD`, band, lead, round-robin) | ✅ **all of it** | **which members may fire** (mask) |

**No scripting language is warranted.** Every special behaviour above is either a
self-contained engine state machine keyed off a single authored byte, or a consequence of
gameplay. The complete authored vocabulary is: *when*, *which formation*, *which species*,
*which side*, *who shoots*, *who mirrors* — six values, all bytes.

### The one gap: boss approach

Recommend a generated constant in `stage_config.asm`:

```asm
.const STAGE_NO_SPAWN_ROW = <16-bit world row>   // last row that may START an encounter
```

Gate in `waveTick` beside the existing `lvlPhase` test — a 16-bit compare, ~14 cycles, only on
frames a trigger is due. With a 24–40 coarse-row margin (4–7 s), survivors leave under their own
`WM_EXIT` and the arena is empty when `stageComplete` fires; `ARENA_CLEAR_DEADLINE` becomes the
backstop it was meant to be. The editor draws the band on the map so the author *sees* the approach.

This is orthogonal to the wave-contract choice and can land independently.

---

## 8. Editor implications

Editor at `tools/level_editor/` in `~/Desktop/c64Shooter-main.zip` (not in this repo). **Not modified.**

### Reusable as-is

- **Definitions + triggers as separate concepts** — matches the engine exactly.
- **`worldRow` absolute, 16-bit on export** (`waveTriggerRowLo/Hi`) — the editor is **ahead** of
  the engine here.
- Canonical ordering: definitions by `id`, triggers by `(-worldRow, id)` → deterministic export.
- The **wave library** (`wave_repository/repository.json`, "Add from Library…") — exactly right
  for a shared formation/programme pool.
- Wave panel structure (list, New/Duplicate/Delete), stage-row context, map overlay.

### Must be replaced

| field | why | replacement |
|---|---|---|
| `attackId: 0..11` | catalogue does not exist; conflates side + ingress + shape | `formationId` (→ definition) + `programmeId` (→ shared programme) |
| `enemyType: 0..3` | engine has 2 species as **row offsets** | `species: "ring" \| "dropper"` → emits `SPECIES_*` |
| `composition: [{enemyType,count}]` | engine cannot mix species in one instance | `count: 1..8` (single species) |
| — | no entry geometry at all today | `startX`, `startY`, `xStep`, `yStep`, `colour`, `heading` |
| — | no firing control today | `fireMask` (per-member checkboxes) |
| — | | `mirrorMask`, `dropperSide` |

`spawnInterval` survives unchanged → definition field 1.

### A movement-programme editor: yes, and bounded

Worth building, at exactly one level of abstraction: **an ordered list of stage rows**, one row
per stage, typed by primitive:

```
STRAIGHT   frames [1..255]   vx [-128..127]   vy [-128..127]
HOLD       frames [1..255]   vx               vy
ARC        steps  [1..255]   frames/step [1..255]
ARC_MIRROR steps  [1..255]   frames/step [1..255]
EXIT       (terminal, always last)
```

Plus a **path preview** that integrates the same quarter-pixel arithmetic — for *visual feedback*,
explicitly **not** as the correctness authority.

### How the editor validates without duplicating engine semantics

This is the crux, and the answer is structural:

1. **Cheap structural checks in Python** (instant feedback, no semantics):
   last stage is `EXIT`, no `EXIT` before the end, `arg ≥ 1`, arc `frames/step ≥ 1`,
   total stage bytes ≤ 256, `|vx| ≤ ENEMY_CLEAR_X_LEFT × 4`, fire/mirror mask bits < `count`.
2. **One semantic check Python must own**, because the engine does not have it and cannot infer
   intent (§1.7): **a `STRAIGHT`/`HOLD` whose `(vx,vy)` differs from the current heading's table
   entry, when any later stage is an arc** → warn, and offer "snap to heading". This is the one
   place the editor must know a movement rule, and it is a table lookup, not a simulator.
3. **Everything else is delegated to the build.** The existing KickAssembler flight validator
   proves termination, arrival, no-wrap and no-materialise-in-view over the *generated* bytes
   exactly as it does over hand-written ones. **The build is the authority; a bad export fails
   the build.** No Python reimplementation of despawn rules, aperture bounds or integration.

That division is what keeps Python and assembly from drifting: Python owns *ergonomics*,
KickAssembler owns *truth*.

### Blocking prerequisite (unchanged from the previous review)

`engine_data.load_engine_data()` still cannot read this repo: it looks for
`src/generated/level1/stage_config.asm`; the package is at `src/level1/`. Three constants.
Until that is fixed, no round-trip work is possible.

---

## 9. Memory-layout implications

### 9.1 Correction to the previous review

> Previous report, §3.3: *"the free run above the game-state code — `$9cec-$bfff`, ~8.9 KB — is
> the obvious home… it is outside VIC bank 0 so it costs no graphics capacity."*

**That region is not free.** Two reservations are invisible in the build's memory map because
**no KickAssembler segment declares them**:

| range | size | what | evidence |
|---|---|---|---|
| `$8c00-$8fff` | 1,024 B | **VIC bank 2 screen matrix** (+ sprite pointers at `$8ff8`) | `VB2_SCREEN = $8c00`, `main.asm:163` |
| `$a000-$bfff` | 8,192 B | **VIC bank 2 static mirror** — sprites, terrain charset, clip scratch, HUD, boss cells, blank charset | `vicMirrorStatic` copies 32 pages `$2000→$a000` and 8 pages `$0800→$a800`, `vicbank.asm:306-318` |

Anything placed there is overwritten at cold start and corrupts the boss arena's display.

### 9.2 The corrected free map (≥ 64 B, above `$4000`)

```
$45a4-$45ff      92
$4759-$47ff     167
$4a59-$4aff     167
$4b26-$4bff     218
$4d4d-$4dff     179
$4f3d-$4fff     195
$52c6-$53ff     314
$5774-$57ff     140
$5e3a-$63ff    1478   ← largest contiguous run outside BOTH VIC banks
$6aee-$6bff     274
$6c0e-$6cff     242
$6d9d-$6dff      99
$6e8a-$6eff     118
$740d-$74ff     243
$76b3-$76ff      77
$7999-$79ff     103
$7b19-$7bff     231
$7f4b-$7fff     181   ← immediately after the existing wave tables
$8117-$85ff    1257   bank 2, not fetched
$8aaf-$8bff     337   bank 2, not fetched  (NOTE: $8c00-$8fff is the screen matrix)
$9000-$93ff    1024   bank 2 CHAR-ROM SHADOW — CPU-only, can never hold graphics
$968f-$96ff     113   char-ROM shadow
$9ce9-$9fff     791   char-ROM shadow
$c2a1-$c2ff      95   /  $c469-$c4bf 87  /  $c615-$c6ff 235
$c76f-$c95f     497   /  $c9ff-$ceff 1281
                      total ≥64 B above $4000: 10,235 B
```

### 9.3 Where encounter data should live — and why it does not compete with terrain

**Recommendation: the VIC character-ROM shadow, `$9000-$93ff` (1,024 B), with `$9ce9-$9fff`
(791 B) as the overflow.**

The VIC sees character ROM at bank-relative `$1000-$1fff` in banks 0 and 2 — i.e. **`$9000-$9fff`
can never hold graphics for either bank**. It is exclusively CPU-readable. The project already
treats it this way: boss code and game-state code occupy `$9400-$9ce8`. Read-only encounter
tables are precisely the right tenant, and placing them there **removes them from competition
with every graphics need in the machine**.

**It does not compete with the terrain-map relocation.** The terrain map needs one large
*contiguous* run; encounter data does not. The terrain map's realistic homes are
`$5e3a-$63ff` (1,478 B, directly adjacent to the existing `$5800` map — extending the segment to
`$63ff` gives **2,560 B contiguous**) and/or `$8117-$85ff` (1,257 B).

**A further correction worth recording:** a 400-metatile-row map needs 4,000 B of rows + 544 B of
defs = **4,544 B contiguous**, and **no such run exists** — the largest is 1,478 B. The previous
report's relocation plan rested on the phantom 8.9 KB. A 400-row stage needs either a
substantially rearranged memory map or a banked/streamed map, and that is a genuine open
question, not a settled one.

**Secondary placement** for the small, hot definition and programme tables: `$7f4b-$7fff`
(181 B) keeps them adjacent to the wave code that reads them, at zero cost.

---

## 10. The recommended contract

### 10.1 Shape

> **Movement programmes and encounters are editor-authored data; execution semantics stay in the
> engine. Programmes are shared by identity, and the assembler remains the correctness authority.**

Concretely: **Option B with a deduplicated programme pool**, over the engine's existing
decomposition. The movement interpreter needs **no change at all** — only the bytes move from
`.var progs` in `waves.asm` to a generated file.

### 10.2 Records

**Trigger** — parallel columns, `WAVE_TRIGGER_COUNT` entries, sorted ascending by row:

| column | width | range | note |
|---|---|---|---|
| `waveTrigRowLo` | 1 | | **absolute** `worldProgress`, 16-bit |
| `waveTrigRowHi` | 1 | 0..1600 | replaces today's wrapping deltas |
| `waveTrigDef` | 1 | 0..`WAVE_DEFS-1` | formation/definition index |
| `waveTrigSpecies` | 1 | `SPECIES_RING`/`SPECIES_DROPPER` | **membership-checked**, it is a row offset |
| `waveTrigFire` | 1 | bitmask over member index | unchanged |
| `waveTrigFlags` | 1 | bit 0 = Dropper side; bits 1-7 reserved | replaces `trigSide` |
| `waveTrigMirror` | 1 | bitmask over member index | **new** (§6) |

**7 bytes per trigger.** (6 if `mirror` is deferred.)

**Wave definition** — **unchanged, 10 bytes**, exactly as §2.2. Generated rather than hand-authored.

**Movement programme** — **unchanged**, 4 bytes per stage, `WM_EXIT`-terminated, referenced by
byte offset computed at export. Whole pool ≤ **256 B / 64 records**.

**Formation** — *not a separate record.* It is definition fields 0–7. Kept distinct in the
**editor's** model (so formations are reusable across programmes and vice versa) and flattened
into the 10-byte record on export.

**Per-member overrides** — two masks only: `fire`, `mirror`. Nothing else.

**Egress semantics** — unchanged: every programme ends in `WM_EXIT`; the despawn rules in
`enemy.asm` retire the object; the assembler proves every path reaches an edge.

**Stage constant** — `STAGE_NO_SPAWN_ROW` (16-bit) in `stage_config.asm`.

### 10.3 Storage estimates

| scenario | programmes | definitions | triggers | **total** |
|---|---|---|---|---|
| simple 4-enemy encounter, standalone | 3 stages = 12 B | 10 B | 7 B | **29 B** |
| …each **additional** encounter reusing both | 0 | 0 | 7 B | **7 B** |
| elaborate encounter, 5 movement stages | 6 stages = 24 B | 10 B | 7 B | **41 B** |
| **~50 encounters** (10 programmes, 20 formations) | ~140 B | 200 B | 350 B | **~690 B** |
| **~150 encounters** (14 programmes, 30 formations) | ~196 B | 300 B | 1,050 B | **~1,546 B** |

Both fit. 50 encounters fit `$9000-$93ff` alone. 150 encounters fit with the triggers in
`$8117-$85ff` (1,257 B = 179 triggers) and the small tables in `$9000-$93ff` or `$7f4b-$7fff`.

**What deduplicates:** movement programmes (a handful per level, referenced by many encounters)
and wave definitions (a formation reused at many rows). **What does not:** triggers — one per
authored moment, inherently linear in encounter count. That is why the trigger record is the
one to keep narrow.

### 10.4 Runtime cost of the contract

| | today | proposed | delta |
|---|---|---|---|
| RAM, director | 27 B | 27 B | **0** |
| RAM, per object | 160 B | +16 B (mirror flag) | **+16 B** |
| CPU, `waveTick` ordinary frame | ~50 cycles | ~50 | **0** |
| CPU, trigger due | 16-bit compare + `adc` carry chain | 16-bit compare, **no running sum** | **slightly cheaper** |
| CPU, per enemy per frame | ~135 | ~135 | **0** |
| CPU, arc stage entry | — | +~6 (mirror XOR) | negligible |

**Absolute rows are cheaper at runtime than deltas**, because `waveAdvanceCursor`'s 16-bit
running-sum maintenance disappears.

---

## 11. Migration roadmap — no implementation in this task

Each stage is independently testable, preserves visible gameplay, and is not a flag day.
**The editor adopts nothing until the engine-side representation is proven.**

| # | stage | scope | model | proof of success |
|---|---|---|---|---|
| **1** | **Absolute trigger rows** | Engine only. Replace `trigDelta` with `trigRowLo/Hi`; drop the wrap; `waveAdvanceCursor` loses its running sum. Author the *same* four triggers at the rows the deltas currently produce for cycle 1. | **Opus 5 High** — 16-bit cursor arithmetic, wrap-semantics removal, touches the director's hot path | `make test` green; a probe asserts `wvStarted` and the trigger rows over a full stage match the pre-change delta schedule for the first cycle; **manual non-warp VICE** confirms the same four formations at the same points |
| **2** | **`STAGE_NO_SPAWN_ROW`** | Engine + a generated constant. Gate in `waveTick` beside the `lvlPhase` test. | **Opus 5 High** — level-lifecycle seam | Probe: arena is empty at `stageComplete` **without** `ARENA_CLEAR_DEADLINE` firing; `make test` green |
| **3** | **Externalise the programme pool** | Engine only. Move `.var progs` bytes into `src/level1/stage_waves.asm` as a generated-shaped file, **hand-written for now**. `waveStageTable` imports it. Keep the flight validator operating on it. | **Opus 5 High** — proves the validator works on imported data and the 256 B cursor guard still binds | Assembled `waveStageTable` bytes **byte-identical** to today's; `make test` green; VICE indistinguishable |
| **4** | **Externalise definitions + triggers** | Engine only. Same treatment for `waveDefTable` and the trigger columns. | **Sonnet 5** — mechanical once stage 3 establishes the pattern | Byte-identical tables; `make test` green |
| **5** | **`WAVE_SLOTS = 4` + mirror mask** | Engine. 16 B state, one XOR at the arc branch, one new trigger column. | **Opus 5 High** — per-object movement state and the arc direction test | Probe: two co-located triggers both start; a mirrored member's heading walks the opposite way; **manual VICE** on the visual result |
| **6** | **Editor contract v2** | Editor only. Fix `engine_data` paths (blocking prerequisite); replace `attackId`/`enemyType`/`composition` with `formationId`/`programmeId`/`species`/`count`; add geometry, heading, fire/mirror masks; emit programmes, definitions and triggers. | **Sonnet 5** — bounded Python/exporter work | Re-export level 1 → generated files **byte-identical** to the hand-written ones from stages 3–4. That diff is the whole proof |
| **7** | **Movement-programme editor + preview** | Editor only. Stage-list rows, path preview, the heading/straight-velocity warning (§8). | **Sonnet 5**, escalating to Opus if the preview's integration semantics prove subtle | Author a genuinely new programme; it passes the KickAssembler flight validator unaided; **manual VICE** confirms it flies as previewed |
| **8** | **Author real content** | Content. 50+ encounters against terrain, quiet zones, a deliberate boss approach. | **Sonnet 5** | Full non-warp playthrough; trigger count, byte budgets and `wvDropped == 0` |

**Sequencing rationale:** stages 1–5 change the engine while the content stays byte-identical, so
every step is provable by diff and by eye. Stage 6's success criterion is *reproducing* what
stages 3–4 hand-wrote — the editor proves itself against a known-good target before it is ever
asked to author something new.

---

## 12. Tests and probes performed

| probe | result |
|---|---|
| `make` (KickAssembler 5.25) | **Clean.** All assembly-time proofs pass: heading-table anchors, smoothness, zero-velocity, wrap guard, stage-table ≤ 256 B, per-definition flight simulation of every member of every pattern |
| `make test` (engine invariant probe, VICE `x64sc`) | **1 failure — pre-existing at HEAD, not caused by this review:** `publishSkip is zero over 10s of ordinary play`. All other assertions green (phase schedule, aperture, sprite ownership, page/pointer coherence, HUD window, player/collision, renderer sanity) |
| Memory-map extraction + gap analysis | Free map computed (§9.2); **two undeclared bank-2 reservations identified** that the segment map does not show |
| Heading/straight-velocity consistency check (Python, against the generated table) | **All four authored programmes match exactly** — confirming a hand-maintained, unenforced invariant (§1.7) |
| Symbol-file table sizing (`build/main.vs`) | `waveStageTable` 52 B, `waveDefTable` 40 B, trigger columns 20 B, heading table 128 B |
| Spawn-authority audit (`grep objectAlloc / TYPE_ENEMY`) | Three allocators; **two** create `TYPE_ENEMY` (`waves.asm`, `token.asm`), contradicting `waves.asm`'s stated invariant |
| Old-engine attack model (`~/Desktop/c64Shooter-main.zip`) | 12 curated attacks = fixed ingress→manoeuvre→egress fragment chains with exit-class bits — strictly weaker than the current 5-primitive heading composition |

**VICE hygiene:** `pgrep -fl x64sc` before the run confirmed a clean baseline. The harness
launched and reaped exactly one instance (`pid 95395`, `rc=-15`), reported it, and
`pgrep` afterwards confirmed none remained. No broad `pkill`/`killall`; no user session touched;
`-console`, no focus stolen.

**Manual VICE:** not required — this review made no behavioural change.

---

## 13. Status and hygiene

```
$ git status --porcelain
?? reports/level-editor-current-engine-contract-review.md
?? reports/wave-movement-architecture-and-editor-contract.md

$ du -sh build/    96K
$ du -sh .         7.7M
```

Both untracked entries are reports. **No production code, test or editor file was modified.**
Temporary files (`/tmp/segs.txt`) were deleted. The old editor remains extracted read-only at
`/tmp/oldshooter`.

**Nothing was committed. Nothing was pushed.** The architecture is **not** implemented — this
report exists so the contract can be chosen first.
