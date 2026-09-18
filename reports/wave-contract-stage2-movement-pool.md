# Wave Contract Stage 2 — deterministic ARC entry, and the externalised movement pool

**Date:** 2026-09-18
**HEAD at start:** `8f79574` — *Memory reshuffle to accomodate longer levels*. Working tree **clean**.
**Outcome:** both goals delivered and proven. No authored trajectory changed.
**Nothing committed. Nothing pushed.**

---

## 0. Two premises in the brief do not match the repository

The brief asks me to treat the checked-out repo as authoritative, so I checked before editing. Two of its stated prerequisites **have not been done**:

| brief says | repository actually contains |
|---|---|
| "Wave Contract Stage 1 (absolute 16-bit trigger rows, no wrap)" | **Not present.** `src/waves.asm:526` is still `.var trigDelta = List().add(48, 4, 38, 36)`, and `waveAdvanceCursor` still wraps the cursor (`cmp #WAVE_TRIGGERS / bcc / lda #0`) and accumulates deltas. Triggers are delta-coded and **do** wrap. |
| "the frame-accurate test-harness boot repair" | **Not present.** `tests/harness.py` has the original `_boot_to_game`, `free_run` and `step_n`. The only recent harness change is mine from the previous task (boot from the disk image). |

`8f79574` is the previous task's commit; nothing else has landed since.

**This did not block Stage 2**, because Stage 2 is orthogonal to trigger representation and the brief's own scope exclusions forbid touching triggers. I have not gone near them, so wrapping is neither restored nor removed — it is exactly as it was. The first four encounters still fire at world rows **48, 52, 90, 126** (the cumulative deltas), which is what the brief expects, and then the list repeats as it always has.

**Stage 1 remains outstanding** and should be scheduled before the trigger externalisation stage.

---

## 1. Inspection, before editing

| question | answer |
|---|---|
| movement-program representation | `.var progs` in `src/waves.asm`, emitted as `waveStageTable` into the **engine PRG** at `$7edb` |
| size | **52 bytes = 13 records** of 4 bytes; 4 programs at offsets 0, 12, 24, 40 |
| consumers | **`src/movement.asm` only** — six `lda waveStageTable + n,y` sites, Y = `wmStage` (one byte per object) |
| `$f530` reservation | `LEVELPKG_ENC = $f530`, `LEVELPKG_ENC_MAX = 1600`; **nothing emitted there** — entirely empty |
| package build/load | `src/level_package.asm` → `build/level1.prg` (load address `$e000`) → written to `build/shmup.d64` as `LEVEL1` → loaded by `src/levelload.asm` as the first instruction of `entry`, before `$01` switches to `$35` |
| `wmPhase` semantics | written **only** by `wmArcStep` (±1 per heading step) and at spawn from the wave definition's launch heading. `WM_STRAIGHT`, `WM_HOLD` and `WM_EXIT` never touch it. Read only by `wmLoadHeading` |
| tests exercising movement | `test_flight_paths.py`, `test_ingress_egress.py`, `test_encounter_director.py`, `test_enemy_fire.py`, `test_dropper_flight.py`, plus the **assembly-time flight simulator** in `waves.asm` that flies every member of every wave |

---

## 2. The semantic audit

I simulated every authored program rather than reading it, tracking where `wmPhase` comes from at each ARC entry:

```
--- 0 SWEEP: launch heading 0
    stage 0 WM_STRAIGHT    vel=(6,0)  phase UNCHANGED at 0
    stage 1 WM_ARC         enters at phase  0  (from launch heading)
--- 1 S-TURN: launch heading 12
    stage 0 WM_ARC_MIRROR  enters at phase 12  (from launch heading)
    stage 1 WM_ARC         enters at phase  0  (from ARC at stage 0)
--- 2 LINGER: launch heading 10
    stage 0 WM_STRAIGHT    vel=(3,5)  phase UNCHANGED at 10
    stage 1 WM_HOLD        vel=(0,1)  phase UNCHANGED at 10
    stage 2 WM_ARC         enters at phase 10  (from launch heading)
--- 3 LOOP: launch heading 8
    stage 0 WM_STRAIGHT    vel=(4,4)  phase UNCHANGED at 8
    stage 1 WM_ARC         enters at phase  8  (from launch heading)

ARC entries depending on a STALE phase (an ARC separated from its phase
source by STRAIGHT/HOLD): 0
```

**The architecture review's "stale ARC history" hazard is not exercised by any current content.** Every ARC entry takes its phase from either the launch heading or the arc immediately before it.

But the audit found a **sharper and more damaging dependency**: three of the four programs take their arc heading from `def.heading` — **a field of the wave definition, not of the program**. That is the real obstacle to a shared, editor-authored pool: the same program invoked by two encounters with different launch headings flies two different paths, and a previewer cannot draw a program at all without knowing which encounter will run it.

Demonstrated, by re-flying each program with the launch heading shifted by +20:

```
SWEEP    launch heading +20 -> OLD DIFFERENT path | NEW same
S-TURN   launch heading +20 -> OLD DIFFERENT path | NEW same
LINGER   launch heading +20 -> OLD DIFFERENT path | NEW same
LOOP     launch heading +20 -> OLD DIFFERENT path | NEW same
```

---

## 3. The final ARC-entry contract

> **Byte 3 of an ARC/ARC_MIRROR record is its ENTRY HEADING (0..63), or `WM_HEAD_CONT` ($ff) meaning "continue from the heading the object already holds".**
>
> `WM_STRAIGHT`, `WM_HOLD` and `WM_EXIT` still never touch `wmPhase`. Nothing else changed.

Why this rule and not another:

- **Byte 3 was genuinely free.** For arcs the interpreter read bytes 0, 1 and 2 only; byte 3 was documented "unused". The pool does not grow by one byte.
- **It makes a program self-contained.** Its trajectory is now a function of its own bytes and nothing else, which is precisely the contract the brief asked for: an editor can determine an ARC's initial behaviour from the record without reconstructing history.
- **It keeps continuity, and makes it explicit.** The S-turn's join genuinely wants to continue from the preceding arc — that is what makes an S an S rather than two unrelated curves. It now says so with `WM_HEAD_CONT` instead of relying on an undocumented accident.
- **It is one compare in a cold path.** Arc entry happens a handful of times in an object's life, never per frame.

Rejected alternatives: making STRAIGHT/HOLD write `wmPhase` (their velocity need not lie on the 64-heading circle, so there is no exact heading to write); resetting to the launch heading on ARC entry (breaks the S-turn's join and keeps the dependency on the wave definition); a flag bit in the kind byte (more machinery than a sentinel in a byte that was already spare).

**Guards added:** byte 3 of an arc must be a heading or `WM_HEAD_CONT` (an out-of-range value would index off the end of the heading table at run time), and `WM_HEAD_CONT` must not collide with a real heading.

**Staleness is not silently possible.** The assembly-time flight simulator in `waves.asm` now honours the new rule and flies every path under it, so editing an early arc and leaving a later explicit heading behind yields either a still-legal path or a build error — never a quiet wrong trajectory. (I deliberately did *not* assert "explicit heading must equal the inherited one": that would forbid a legitimate future program from deliberately starting an arc on a new heading.)

---

## 4. Migration, byte for byte

Only byte 3 of the five arc records changed. Nothing else in the pool moved.

| program | record | before | after | meaning |
|---|---|---|---|---|
| SWEEP | rec 1 `WM_ARC 16, 4` | `0` | **`0`** | unchanged — it already read 0 |
| S-TURN | rec 3 `WM_ARC_MIRROR 12, 3` | `0` | **`12`** | names the launch heading it used to inherit |
| S-TURN | rec 4 `WM_ARC 20, 3` | `0` | **`255`** (`WM_HEAD_CONT`) | the join, now explicit |
| LINGER | rec 8 `WM_ARC 12, 4` | `0` | **`10`** | names the heading it flew in on |
| LOOP | rec 11 `WM_ARC 76, 2` | `0` | **`8`** | names the dive's heading |

**Proof that no trajectory changed** — every member of every wave flown under both semantics in the same quarter-pixel arithmetic the 6502 uses:

```
SWEEP    launch heading  0   401 frames  OLD vs NEW: IDENTICAL
S-TURN   launch heading 12   401 frames  OLD vs NEW: IDENTICAL
LINGER   launch heading 10   401 frames  OLD vs NEW: IDENTICAL
LOOP     launch heading  8   401 frames  OLD vs NEW: IDENTICAL

every authored trajectory unchanged
```

`def.heading` (wave definition field 8) is now **vestigial for arc behaviour**. It is still written to `wmPhase` at spawn and still read by any `WM_HEAD_CONT` arc that is a program's first stage. It was left in place: removing it is a wave-definition change, which this stage excludes.

---

## 5. The external pool: address and layout

```
$e000-$e419   level map                 1,050 B   (4,200 B for the 420-row proof)
$f130-$f34f   metatile definitions        544 B
$f530-$f563   MOVEMENT PROGRAM POOL        52 B   <-- new in Stage 2
$fb70-$fb73   package signature             4 B
$fffa-$ffff   hardware vectors                    (never touched)
```

`src/levelpkg.asm` gains `LEVELPKG_MOVE = LEVELPKG_ENC` and `LEVELPKG_MOVE_MAX = 256`, with guards that the pool starts at the base of the encounter reservation, fits inside it, and cannot exceed 256 bytes.

**The 256-byte ceiling is hardware, not budget.** Each object carries its cursor in `wmStage`, one byte, and the interpreter indexes the pool with that same byte — so 64 stage records is the hard limit until per-object state widens. That is restated in three places that must agree: `wave_programs.asm` (source), `levelpkg.asm` (contract) and `level_package.asm` (emitted bytes).

**Verified in the built binaries:**

```
waveStageTable resolves to $f530
engine 'lda $f53n,y' sites (movement pool reads):
   $78b4 -> $f532      $78df -> $f530      $78f1 -> $f531      $78f7 -> $f532
   $78fd -> $f533      $7904 -> $f531      $790a -> $f532      $7910 -> $f533

package $f530 pool bytes (13 records):
   rec  0:   0  34   6   0      rec  7:   4  48   0   1
   rec  1:   1  16   4   0      rec  8:   1  12   4  10
   rec  2:   3   0   0   0      rec  9:   3   0   0   0
   rec  3:   2  12   3  12      rec 10:   0  40   4   4
   rec  4:   1  20   3 255      rec 11:   1  76   2   8
   rec  5:   3   0   0   0      rec 12:   3   0   0   0
   rec  6:   0  28   3   5
```

Eight `lda abs,y` sites reading straight out of the loaded package. **No copy is made into ordinary RAM**, and the engine binary contains no duplicate.

**Program offsets are unchanged: 0, 12, 24, 40** — production wave definitions needed no edit.

---

## 6. Files changed

| file | change |
|---|---|
| `src/movement_format.asm` | **new** — the stage record format, the five primitives and the heading geometry, as constants only. Shared by both builds; `#importonce` |
| `src/wave_programs.asm` | **new** — the four authored programs (moved out of `waves.asm`), their `PROG_*` ids and their computed byte offsets. Shared by both builds |
| `src/movement.asm` | imports the format file instead of defining it; ARC entry reads byte 3 and honours `WM_HEAD_CONT` |
| `src/waves.asm` | imports `wave_programs.asm`; **stops emitting the pool** — `waveStageTable` is now `.label = LEVELPKG_MOVE`; flight simulator honours the new ARC-entry rule; byte-3 range guard added |
| `src/level_package.asm` | **emits the pool** at `LEVELPKG_MOVE`, with width/size/boundary guards |
| `src/levelpkg.asm` | `LEVELPKG_MOVE`, `LEVELPKG_MOVE_MAX` and their guards; `#importonce` |
| `tests/test_movement_pool.py` | **new** — the Stage 2 focused tests |
| `Makefile` | `test-movement-pool` target |

```
 Makefile                     |   5 +
 src/level_package.asm        |  36 ++++++
 src/levelpkg.asm             |  33 ++++++
 src/movement.asm             | 121 +++-----------------
 src/waves.asm                | 213 ++++--------------------------------
 src/movement_format.asm      | new
 src/wave_programs.asm        | new
 tests/test_movement_pool.py  | new
```

---

## 7. Memory and cycle accounting

| | before | after |
|---|---|---|
| **engine PRG bytes holding the pool** | **52** (`$7edb-$7f0e`) | **0** |
| waves segment | `$7c00-$7f4a` (843 B) | `$7c00-$7f16` (**791 B**) — 52 B freed |
| free run after the waves segment | `$7f4b-$7fff` (181 B) | `$7f17-$7fff` (**233 B**) |
| **level-package bytes at/after `$f530`** | 0 | **52** |
| remaining encounter-package budget | 1,600 | **1,548** |
| engine RAM (`wmStage` etc.) | unchanged | unchanged — no new per-object state |
| engine PRG file size | 51,164 B | 51,164 B (padded to `$cfda`; the 52 bytes became free space, not a smaller file) |
| level package file size | 7,030 B | 7,030 B (padded to `$fb73`; the pool filled existing zero padding) |

**Cycle cost of the relocation: zero.** The reads were `lda waveStageTable + n,y` and remain `lda abs,y` — four cycles wherever the table lives.

**Cycle cost of the semantic change**, per ARC stage *entered* (never per frame):

| path | before | after | delta |
|---|---|---|---|
| explicit heading | `jmp` = 3 | `lda abs,y`+`cmp #`+`beq`+`sta abs,x`+`jmp` = 16 | **+13** |
| `WM_HEAD_CONT` | `jmp` = 3 | `lda abs,y`+`cmp #`+`beq` = 9 | **+6** |

Over the whole 420-row proof — 169 enemies spawned, one or two arc entries each — that is on the order of **2,000–4,000 cycles across 13,240 frames**, i.e. under 0.3 cycles per frame.

**Worst-case frame counters, measured:** `gameOverrun = 0` and `scrollLate = 0` on both the 105-row build and the full 420-row traversal, unchanged from the previous baseline.

---

## 8. Tests and proofs

### New: `test-movement-pool` — ALL PASS

```
ok  the movement pool in RAM at $f530 matches the built level package byte for byte -- 0 mismatches
ok  waveStageTable resolves into the level package, not the engine PRG -- $f530
ok  the engine PRG carries no second copy of the pool -- absent from the engine binary, as intended
ok  the pool is a whole number of four-byte stage records -- 13 records
ok  every program start offset resolves to a record boundary -- [0, 12, 24, 40]
ok  each program still starts with the primitive it always did -- [0, 2, 0, 0]
ok  the pool contains the expected arc stages -- 5
ok  exactly one arc asks to CONTINUE, and it is the S-turn's join -- [4]
ok  an ARC with an explicit heading ignores wmPhase entirely (4 arcs x 3 corrupted seeds) -- 0 wrong
ok  ARC entry after STRAIGHT (SWEEP) is deterministic -- phase 0 vel (6,0), wanted 0
ok  ARC entry after HOLD (LINGER) is deterministic -- phase 10 vel (3,5), wanted 10
ok  ARC entry after STRAIGHT (LOOP) is deterministic -- phase 8 vel (4,4), wanted 8
ok  ARC entry as first stage (S-TURN, MIRROR) is deterministic -- phase 12 vel (2,6), wanted 12
ok  WM_HEAD_CONT continues from whatever heading the object holds -- [(0,0,6,0), (12,12,2,6), (40,40,252,252)]
ok  ...and it is therefore the ONLY arc whose entry depends on history -- 1 continue-arcs
ok  WM_ARC_MIRROR starts on its named heading and steps ANTICLOCKWISE -- entered 12, stepped to 11
ok  WM_ARC steps CLOCKWISE from the same explicit contract -- stepped to 1, wanted 1
```

The stale-phase proof is the strongest of these: each explicit arc is entered three times with a **deliberately corrupted `wmPhase`** — including the value a stale earlier arc would most plausibly have left — and the resulting heading and velocity are determined entirely by the record.

### Regression — matches the documented baseline exactly

| target | result | vs baseline |
|---|---|---|
| `test-boot` | ALL PASS | same |
| `test-turret-regression` | ALL PASS | same |
| `test-boss` | ALL PASS | same |
| `test-lifecycle` | ALL PASS | same |
| `test-player-death` | ALL PASS | same |
| `test_bank2_arena` | ALL PASS | same |
| `test-production` | `publishSkip` = 14 | baseline 12–18 — **inherited noise** |
| `test-encounter-director` | `publishSkip` = 22, `schedBuildDefer` = 1 | baseline 21 / 1 — **inherited noise** |
| `test_pickup` | `KeyError: 'waveTrigTokenLo'` | **inherited breakage**, a symbol the engine removed long ago |

**No new failures.** Nothing was weakened, and no production code was changed to make a test pass.

### Long-stage proof (420 rows) — ALL PASS

```
ok  the stage completed at the derived final progress 1655
ok  the traversal really crossed every 8-bit boundary -- final worldProgress 1655
ok  the scroller froze on the last complete authored screen (stageTopRow 0)
ok  the boss phase was reached after the long stage -- lvlPhase 2
ok  the movement pool at $f530 still matches the built package after the full traversal -- intact
ok  the package signature at $fb70 is intact after the traversal
ok  the metatile definitions at $f130 are intact after the traversal
ok  gameOverrun is zero across the whole 420-row traversal -- 0
ok  scrollLate is zero across the whole 420-row traversal -- 0
ok  one coarse row still takes 8 displayed frames -- 12 intervals, min 7.95 max 8.08
[note] publishSkip = 24, schedBuildDefer = 1 (inherited noise)
[note] wave director: wvStarted=52 wvDropped=0 wvSpawned=169
```

No corruption at `$f530` or in the adjacent package regions across 1,655 coarse rows, and no trigger wrap was introduced (the director's own wrapping is unchanged, 52 waves started, none dropped).

### On the "frame-accurate boot helper"

It does not exist (§0). The new test uses `set_bp(gameFrame)` + `step_n`, which verifies every step against the frame counter and retries a stall, and `call()` for direct routine invocation — no arbitrary warped sleeps.

---

## 9. Manual VICE

**PID 33255** — the default 105-row build, PAL, visible, **non-warp**, launched without stealing focus, running the movement pool out of `$f530`.

What to look for: the four encounters should fly exactly as before — the sweep's quarter turn, the S-turn's join, the linger's hang-then-break, and the loop. The migration proof says the trajectories are identical to the frame; **your eyes are authoritative over that claim**, and this is the one thing the automated results cannot settle.

Close it yourself, or say the word and I will terminate that exact PID.

---

## 10. Hygiene

`pgrep -x x64sc` confirmed a clean field before every run; every automated instance was reaped by exact PID (31276, 32846 and each `make test-*` harness's own) and reported. No broad `pkill`/`killall`; no user-launched instance touched. Probes and the trajectory-equivalence simulation live in disposable scratch outside the repository.

```
$ du -sh build/    344K      (includes build/proof420; 96K after a plain `make build`)
$ du -sh .         8.6M
$ scratch          508K
```

---

## 11. Final state

```
$ git status --porcelain
 M Makefile
 M src/level_package.asm
 M src/levelpkg.asm
 M src/movement.asm
 M src/waves.asm
?? reports/wave-contract-stage2-movement-pool.md
?? src/movement_format.asm
?? src/wave_programs.asm
?? tests/test_movement_pool.py
```

**Nothing was committed. Nothing was pushed.** Wave definitions, triggers, the 7-byte trigger format, `STAGE_NO_SPAWN_ROW`, `WAVE_SLOTS`, per-member mirroring, formations, firing, the editor, the renderer and the 1 px/frame scroll were all left alone, as the scope required.

**Recommended next:** Wave Contract Stage 1 (absolute 16-bit trigger rows, no wrap), which this brief assumed was already done and which should precede externalising the trigger records.
