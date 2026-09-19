# `STAGE_NO_SPAWN_ROW` — the authored boss approach

**Date:** 2026-09-19
**HEAD at start:** `a8ed378` *Editor contract v3* — level with `origin/main`, 0 behind / 0 ahead, working tree **clean**.
**Outcome:** a per-level 16-bit no-spawn row, held as **runtime package data**, gating ordinary authored encounters into a deterministic quiet zone before the boss.
**Nothing committed. Nothing pushed.**

---

## 1. Lifecycle audit, before editing

| | |
|---|---|
| stage end | `STAGE_FINAL_VIEW_PROGRESS = STAGE_START_ROW = STAGE_ROWS - SCREEN_ROWS` = **395** for the 105-row level. `scrollTick` sets `stageComplete` when `worldProgress` reaches it |
| boss entry | `bossTick` notices `stageComplete`, enters `LP_CLEARING`, arms `ARENA_CLEAR_DEADLINE` = **200 frames (4 s)**, then `LP_BOSS` |
| ordinary encounter start | exactly one path: `waveTick` → `waveStartNext`. Gated by `lvlPhase == LP_LEVEL`, then cursor bounds, then the 16-bit due compare, then the `tkActive` hold |
| special spawn paths | `token.asm` conscripts and reinforces protectors (creates `TYPE_ENEMY` directly); `dropper.asm` takes over an already-spawned member's flight; `boss.asm` creates `TYPE_BOSS`; `ebullet.asm`/`pickup.asm` create projectiles and tokens. **None** of these is an ordinary authored encounter start |
| a trigger due near stage end, before this task | it fired. The only brake was `lvlPhase`, which does not leave `LP_LEVEL` until `worldProgress` reaches 395 — so a wave could start on the very last row and the 200-frame deadline became the mechanism rather than the backstop |

**There was no quiet zone.** That is what this task adds.

---

## 2. The contract

> **An ordinary authored encounter that has not STARTED before `worldProgress` reaches `STAGE_NO_SPAWN_ROW` must never start.**

- **Coordinate domain:** coarse rows of `worldProgress`, 16-bit, the same domain as a Stage 1 trigger row.
- **Boundary:** `worldProgress < STAGE_NO_SPAWN_ROW` → eligible. `>=` → suppressed. A trigger authored *at* the row is therefore suppressed, as is anything above it.
- **Terminal, not skipped.** On crossing, the gate writes `WAVE_TRIGGERS` into `wvNextTrig`. The existing cursor-bounds test takes over from the next frame: nothing is reconsidered, nothing can be released later, there is no backlog, and the 16-bit compare is paid only while triggers remain.
- **Already-running waves are untouched.** The gate is only ever reached on the way to *starting* one.
- **No enemy is despawned** because the threshold was crossed.

### The token-hold decision

**A held-but-not-started trigger is suppressed.** The gate sits *above* the `tkActive` check, deliberately. A trigger that came due before the threshold but was still waiting on a token encounter when the world crossed it **has not started**, and the authoring contract is that nothing unstarted may begin at or beyond the row.

This is tested both ways: the same held trigger released *below* the threshold still fires, so the suppression case cannot pass for the wrong reason.

### Ordinary vs special

The gate touches **only** `waveStartNext`. An already-running Dropper encounter completes its token and protector sequence across the threshold untouched — protector conscription and reinforcement are engine-owned and were not gated. Conversely no *new* ordinary Dropper wave can begin after it.

---

## 3. Where the value lives — and a correction

It is **two bytes of runtime package data** at `$f530`, the base of the encounter reservation:

```
$f530-$f531   STAGE HEADER: STAGE_NO_SPAWN_ROW, lo/hi     2 B     <-- new
$f532-$f631   movement programs                         256 B
$f632-$f735   wave definitions                          260 B
$f736-$fb6f   absolute triggers                       1,082 B     (180 slots x 6)
$fb70-$fb73   package signature                           4 B
```

`2 + 256 + 260 + 1082 = 1600` — the reservation exactly, asserted at assembly time.

**It began as a `.const` in the level's `stage_config.asm`, and that was wrong.** The evidence was unambiguous: with the threshold compiled into the director as an immediate, `tests/test_wave_triggers.py` — the accepted Stage 1 proof — failed **14 assertions**. It proves the 16-bit trigger contract with synthetic rows at 255, 256, 511, 512, 1023, 1024, 1535 and 1536, and every one is beyond any threshold Level 1 could legally carry, because its stage ends at row 395. A compiled-in value silently invalidated an accepted proof **and no value could have rescued it**.

Moving it into the package fixed that, and is what the brief preferred anyway: per-level authored content, emitted beside the trigger rows it constrains, changeable without an engine rebuild, and movable by a test. `src/level1/stage_config.asm` still *authors* the number — one source, emitted into the package by `level_package.asm` and read by the engine from there. No second copy exists.

The movement pool moved `$f530` → `$f532` to make room. All guards and tests were updated in the same change.

---

## 4. The chosen Level 1 value

**`STAGE_NO_SPAWN_ROW = 340`.**

| | |
|---|---|
| stage end | 395 |
| quiet zone | **55 rows = 440 frames = 8.8 s** at 1 px/frame |
| longest authored wave footprint | **48 rows** (the loop: 68 frames of spawning + 317 of flight) |
| clearance margin | 7 rows |

**Fifty-five is derived, not picked.** A clearance shorter than the worst wave footprint could let a wave started on the last legal row still be on screen when the stage ends — precisely what `ARENA_CLEAR_DEADLINE` exists to mop up. Making the zone longer than the worst footprint keeps the deadline a backstop rather than the mechanism.

**Honest caveat:** this changes nothing observable in the current level. Level 1's last authored encounter is at row 126 and Stage 1 made it deliberately quiet thereafter, so rows 127–395 are already empty; the value suppresses nothing that exists. It **forbids** rather than describes: rows 127–339 remain legal to author in, and the number says where authoring stops. Its value today is as a contract for the editor and for the 3–4 minute levels the package can now hold.

---

## 5. Validation

**Build guards** (`src/waves.asm`, `src/levelpkg.asm`, `src/level_package.asm`):

- fits 16 bits; `>= 1`; not beyond `STAGE_FINAL_VIEW_PROGRESS`;
- **an authored trigger row at or beyond the threshold is a build error** — dead data occupying a package slot and describing an encounter the player can never meet;
- stage header is exactly 2 bytes, starts at the base of the reservation, and the four components sum to 1,600.

The trigger guard was proved by temporarily authoring rows around the boundary:

```
row 339  -> accepted
row 340  -> "an authored trigger row is at or beyond STAGE_NO_SPAWN_ROW and could never start"
row 341  -> same error
```

This replaced a now-stale note in `src/waves.asm` that said a row past the stage end was a legitimate way to "park" an encounter. With a no-spawn row the level states where authoring stops, so such a row is not parked — it is dead. The comment was updated rather than left contradicting the guard beside it.

**Runtime suppression is independent of the build guard**, because the package is externally loaded and may be malformed — §7 proves that directly.

---

## 6. Changed files

| file | why |
|---|---|
| `src/level1/stage_config.asm` | authors `STAGE_NO_SPAWN_ROW = 340`, with the derivation |
| `src/levelpkg.asm` | the stage header, its address and budget, and the relayout of the three components below it |
| `src/level_package.asm` | emits the two header bytes |
| `src/waves.asm` | the gate in `waveTick`, the `waveNoSpawnLo/Hi` labels, and the build guards |
| `tools/gen_proof420.py` | scales the threshold to the proof stage's own end (1655 − 55 = 1600) |
| `tests/test_no_spawn_row.py` | **new** — the contract test |
| `tests/test_movement_pool.py` | package addresses shifted by the header |
| `tests/test_wave_triggers.py` | opens the approach before installing a synthetic schedule (§8) |
| `tests/test_pickup.py` | opens the approach before its director-liveness check (§8) |
| `Makefile` | `test-no-spawn-row` target |

---

## 7. Proof

### The contract — `test-no-spawn-row`, ALL PASS

```
ok  the threshold is above 255, so the 16-bit compare is exercised -- 340 ($0154)
ok  the threshold is RUNTIME PACKAGE DATA at $f530, not a compiled-in immediate
ok  one row BEFORE the threshold, an authored trigger still starts -- wvStarted=2
ok  EXACTLY AT the threshold, no authored trigger starts -- wvStarted=0
ok  ...and the cursor is left terminally exhausted -- wvNextTrig=4
ok  BEYOND the threshold, no authored trigger starts
ok  row 255 is below a 340 threshold: the high byte is not ignored -- wvStarted=2
ok  a suppressed schedule never reopens, even if the world is wound back
ok  a trigger due before the threshold is HELD by a token encounter
ok  ...and once the world crossed the threshold while it was held, releasing the hold does NOT start it
ok  ...while the same held trigger released BELOW the threshold does start -- wvStarted=2
ok  a wave already running when the threshold is crossed keeps sending its members -- spawned 1 -> 3
ok  ...and no NEW wave started while it finished -- wvStarted=1
```

Two methodological notes, both discovered by measurement: every case calls `waveInit` first, because a trigger that finds both `WAVE_SLOTS` busy is *dropped* and looks exactly like suppression; and the hold is re-asserted every frame, because `tkActive` is engine-owned and `tokenTick` ends an encounter it cannot find — `gameFrame` calls `waveTick` before `tokenTick`, so one poke buys exactly one frame.

### 420-row suppression proof — ALL PASS

The build refuses to *author* a post-threshold trigger, so the runtime gate was proved against data written into the **loaded package in RAM** — the malformed-external-data case it must survive. Trigger 3 (authored row 126) was moved to row 1650, past the proof stage's no-spawn row of 1600:

```
ok  a trigger was injected at row 1650, beyond the no-spawn row 1600
ok  only the THREE pre-threshold triggers start: the injected post-threshold one
    is suppressed by STAGE_NO_SPAWN_ROW -- wvStarted = 3
ok  the trigger cursor is exhausted and stays there -- wvNextTrig = 4
ok  no trigger was dropped -- wvDropped = 0
ok  the stage completed at the derived final progress 1655
ok  the boss phase was reached after the long stage -- lvlPhase 2
ok  movement pool / wave definitions / trigger columns / signature / metatile defs all intact
ok  gameOverrun = 0, scrollLate = 0
ok  one coarse row still takes 8 displayed frames -- 7.92..8.06
[note] wvSpawned = 10 (13 minus the suppressed loop wave's three)
```

### Regression

| target | result |
|---|---|
| `test-no-spawn-row`, `test-movement-pool`, `test-boot`, `test-production`, `test-pickup`, `test-boss`, `test-lifecycle`, `test-turret-regression`, `test-player-death`, `test_wave_triggers`, `test_bank2_arena` | **ALL PASS** |
| `test_token_encounter` | `schedBuildDefer` = 1 — baseline |
| `test-encounter-director` | `publishSkip` = 12, `schedBuildDefer` = 1 — baseline |

Production still shows **four ordinary waves, two Dropper waves, no wrap**.

---

## 8. Two tests this change legitimately invalidated

Neither was weakened; both were *completing* a setup the new contract made necessary.

- **`test_wave_triggers`** installs synthetic rows at 255…1536 to prove the Stage 1 16-bit contract. All are beyond Level 1's authored approach, so the director correctly suppressed them and the file was measuring the quiet zone instead of the schedule. It now pushes the approach to `$ffff` when it arms a synthetic schedule — the isolation those cases want, since the approach has its own file.
- **`test_pickup`** rewinds `wvNextTrig` to 0 for a director-liveness check. Measured: `worldProgress` is **2265** at that point, far beyond 340, so the director correctly refused. It now opens the approach first, restoring the assertion's original meaning.

I measured both before changing either; neither was assumed.

---

## 9. Cost

| | |
|---|---|
| engine code added | waves segment `$7c00-$7ea9` → `$7c00-$7ec3` = **+26 bytes** |
| package data added | **2 bytes** (stage header); the three components below shifted by 2, budgets unchanged |
| remaining encounter budget | 180 trigger slots, 26 definitions, 64 movement records — **unchanged** |
| per-frame cost, triggers remaining | one 16-bit compare against package data: `lda abs`/`cmp abs` ×2 ≈ **10–19 cycles** |
| per-frame cost, after the threshold | **0** — the cursor-bounds test short-circuits before the gate |
| runtime-data vs immediate | `cmp abs` is 4 cycles against `cmp #`'s 2, so **+4 cycles** per gated frame for the testability the immediate could not provide |
| `gameOverrun` / `scrollLate` | **0** on the 105-row build and across the full 420-row traversal |
| `publishSkip` / `schedBuildDefer` | 12 / 1 — established baseline noise, unchanged |

---

## 10. The editor-facing contract

For Level Editor Contract v2, when it comes:

| | |
|---|---|
| **name** | `STAGE_NO_SPAWN_ROW` |
| **domain** | coarse rows of `worldProgress`, the same domain as a trigger row |
| **width** | 16-bit, little-endian |
| **storage** | two bytes at the base of the encounter package, `$f530` |
| **rule** | a trigger may start only while `worldProgress < STAGE_NO_SPAWN_ROW` |
| **legal range** | `1 .. STAGE_FINAL_VIEW_PROGRESS` (= `STAGE_METATILE_ROWS * 4 - 25`) |
| **trigger rows** | legal **strictly below** the threshold. A row at or above it is an **exporter error** — it is unreachable data, not a parked encounter |
| **held triggers** | a trigger due but not yet started when the world crosses is **cancelled**, permanently |
| **active encounters** | unaffected; they finish normally, including a Dropper's token and protector sequence |
| **duration** | one row = 8 frames = 0.16 s at 1 px/frame. A 55-row zone is 8.8 s |
| **sizing rule** | make the zone at least as long as the longest movement programme's footprint, so the arena-clear deadline stays a backstop |

---

## 11. Manual VICE

**PID 74624**, PAL, visible, non-warp, launched without stealing focus.

Expect the unchanged four-wave sequence (rows 48, 52, 90, 126 — two of them Droppers), then the level's existing quiet run-in to the boss. The contract is now explicit rather than incidental: from row 340 nothing new can begin, whatever a level's data asks for. Your eyes remain authoritative.

---

## 12. Hygiene

`pgrep -x x64sc` confirmed a clean field before every run; every automated instance was reaped by exact PID. No broad `pkill`/`killall`; no user-launched instance touched. Probes live in disposable scratch.

```
$ du -sh build/    344K      (includes build/proof420; 96K after a plain `make build`)
$ du -sh .         9.1M
$ scratch          940K
```

Two probe-side artefacts worth recording rather than hiding: the 420 probe's `coarseCount == worldProgress` check flaps run to run with a worst delta of 1, because the two counters are read with separate monitor commands and a coarse step can land between them — an engine fault would not alternate. And one `test_token_encounter` run reported a protector-ascent failure that did not reproduce in two consecutive clean re-runs.

---

## 13. Git

| | |
|---|---|
| local HEAD | `a8ed378` — level with `origin/main`, 0 behind / 0 ahead |
| uncommitted | 9 modified, 1 new test, 1 new report |
| committed / pushed | **nothing** |

Scope held: no editor changes, no Contract v2, no encounter-record redesign, no mirror support, no `WAVE_SLOTS` change, no movement-semantic change, and nothing touched in Dropper/protector choreography, turrets, the boss, the renderer or the scroll speed.
