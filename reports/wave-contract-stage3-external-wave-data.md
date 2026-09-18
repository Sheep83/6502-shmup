# Wave Contract Stage 3 — wave definitions and absolute triggers move to the level package

**Date:** 2026-09-19
**HEAD at start:** `d1e4d0d` *Protector orbit fix* — level with `origin/main`, 0 behind / 0 ahead, working tree **clean**.
**Outcome:** the ordinary encounter schedule now lives entirely in the separately loaded level package. The engine PRG contains no authored wave data at all.
**Nothing committed. Nothing pushed.**

---

## 1. The accepted baseline, before editing

| | |
|---|---|
| package layout | map `$e000-$e419` (1,050 B) · metatile defs `$f130-$f34f` (544 B) · movement pool `$f530-$f563` (52 B) · signature `$fb70` |
| encounter reservation | `LEVELPKG_ENC = $f530`, `LEVELPKG_ENC_MAX = 1600`; movement pool 52 B, **1,548 B unallocated** |
| wave definitions | `waveDefTable` at **`$7eaa-$7ed1`, 40 B** — 4 records × `WAVEDEF_SIZE` 10. Ten consumers, all `lda waveDefTable + n,y` with Y = `def * 10` from `waveDefBase` |
| triggers | `waveTrigRowLo/Hi/Def/Species/Fire/Side` at **`$7ed2-$7ee9`, 24 B** — **six parallel columns**, 4 bytes each. Six consumers, all `absolute,y` with Y = `wvNextTrig` |
| indexing limits | `waveDefBase` forms `def * 10` in **one byte** → last reachable definition is 25. The trigger cursor is **one byte** → 255 triggers. `wmStage` is one byte → 64 movement records |

Both tables are addressed purely `absolute,Y` — **position-independent**, exactly as the movement pool was in Stage 2. That is what makes the move free.

---

## 2. Representation: parallel columns kept, deliberately

The brief allowed converting the six parallel trigger columns into interleaved records. **I did not**, and the reason is arithmetic:

- **Parallel:** one cursor serves all six columns. Each field is `lda waveTrigX,y` — **4 cycles**, no arithmetic.
- **Interleaved:** a six-byte record needs the cursor multiplied by six on **every** read (two shifts and an add, or a lookup table), for no gain in what can be stored.

The wave-definition record stays 10 bytes and interleaved because that is what it already was and `waveDefBase` already pays the multiply once per wave, not once per field.

So the *logical* layout is unchanged; only ownership moved. That is also the simplest thing for a future exporter to emit — six flat columns and a flat record array.

**The columns are emitted at FIXED width** (`LEVELPKG_TRIG_SLOTS` = 180) whatever a level authors, because the engine addresses them as fixed bases. A column that shrank with the trigger count would move every column above it and the engine's labels would point at the wrong data. Unused tails are zero.

---

## 3. The new package layout

```
$e000-$e419   level map                   1,050 B   (4,200 B for the 420-row proof)
$f130-$f34f   metatile definitions          544 B
$f530-$f62f   MOVEMENT PROGRAMS             256 B budget   (52 B used, 64 records max)
$f630-$f733   WAVE DEFINITIONS              260 B budget   (40 B used, 26 defs max)
$f734-$fb6f   ABSOLUTE TRIGGERS           1,084 B budget   (1,080 B used, 180 triggers)
$fb70-$fb73   package signature               4 B
$fffa-$ffff   hardware vectors                        (never touched)
```

`256 + 260 + 1084 = 1600` — the encounter reservation exactly, asserted at assembly time.

### Why 26 definitions and not a rounder number

`waveDefBase` forms the index as `def * 10` in a single byte, so the last **reachable** definition is 25. A 32-record table would have stored seven records the engine could never read. The table is therefore exactly 26 records — every byte addressable — and the 60 bytes a rounder table would have wasted went to the triggers, which have a real use for them.

### Verified in the built binaries

```
waveStageTable   -> $f530        waveTrigRowLo    -> $f734
waveDefTable     -> $f630        waveTrigRowHi    -> $f7e8
                                 waveTrigDef      -> $f89c
                                 waveTrigSpecies  -> $f950
                                 waveTrigFire     -> $fa04
                                 waveTrigSide     -> $fab8

package trigger columns (first four of each):
   rowLo   [48, 52, 90, 126]      species [0, 8, 0, 8]
   rowHi   [0, 0, 0, 0]           fire    [5, 2, 5, 0]
   def     [0, 1, 2, 3]           side    [0, 0, 0, 1]
   -> absolute rows [48, 52, 90, 126]

package wave definitions (4 x 10):
   def0: [4, 22, 0, 0, 64, 0, 20, 10, 0,  0]     def2: [3, 26, 120, 0, 30, 36, 0,  7, 10, 24]
   def1: [3, 26, 90, 0, 30, 28, 0, 3, 12, 12]     def3: [3, 34,  70, 0, 30, 50, 0, 13,  8, 40]

engine PRG contains a copy of the 40 definition bytes? False
```

Every authored value survived: rows 48/52/90/126, species RING/DROPPER/RING/DROPPER, fire masks `%0101 %0010 %0101 %0000`, sides LEFT/LEFT/LEFT/RIGHT, and definition field 9 carrying the program offsets 0/12/24/40.

---

## 4. Changed files

| file | why |
|---|---|
| `src/encounter_format.asm` | **new** — the vocabulary a level's data speaks: `ENEMY_ANIM_STEPS`, `SPECIES_*`, `DROP_SIDE_*`. The package build emits these values as authored bytes and shares no labels with the engine, so they had to live where both can import them — the same pattern as `movement_format.asm` |
| `src/wave_encounters.asm` | **new** — the authored wave definitions and the absolute trigger list, moved out of `waves.asm`. Imported by `waves.asm` (which validates them) and by `level_package.asm` (which emits them) |
| `src/enemy.asm` | imports the vocabulary instead of defining `ENEMY_ANIM_STEPS` / `SPECIES_*`. What a species *does* is still this file's business |
| `src/dropper.asm` | imports the vocabulary instead of defining `DROP_SIDE_*` |
| `src/levelpkg.asm` | `LEVELPKG_WAVEDEF`, `LEVELPKG_TRIG`, their budgets and slot counts, and seven new guards |
| `src/waves.asm` | imports `wave_encounters.asm`; **stops emitting both tables** — `waveDefTable` and the six trigger columns are now `.label`s at package addresses. All proofs stay |
| `src/level_package.asm` | **emits** the definitions and the six fixed-width trigger columns, with width/count/bounds guards |
| `tests/test_movement_pool.py` | extended to prove package ownership of the new tables |

**Engine-owned choreography was not touched.** The Dropper's flight, the P-token, protector conscription (which creates `TYPE_ENEMY` directly, and deliberately so) and the boss lifecycle remain engine state machines. A level authors only *which trigger carries a Dropper and from which side*.

---

## 5. Memory accounting

| | before | after |
|---|---|---|
| engine PRG — wave definitions | **40 B** (`$7eaa-$7ed1`) | **0** |
| engine PRG — trigger data | **24 B** (`$7ed2-$7ee9`) | **0** |
| waves segment | `$7c00-$7ee9` (746 B) | `$7c00-$7ea9` (**682 B**) — **64 B freed** |
| package — movement pool | 52 B | 52 B (unchanged) |
| package — wave definitions | 0 | **40 B** |
| package — triggers | 0 | **1,080 B** (6 fixed columns × 180) |
| encounter region allocated | 256 of 1600 | **1,600 of 1,600** — fully laid out |
| authored content inside it | 52 B | **116 B** (52 + 40 + 24 meaningful trigger bytes) |
| engine PRG file | 51,164 B | 51,164 B (padded to `$cfda`; the 64 bytes became free space) |
| level package file | 7,030 B | 7,030 B (padded to `$fb73`; the tables filled existing zero padding) |
| **code size for new access logic** | — | **0 bytes** — labels only, not one instruction added |

### Budget projection for the editor contract

The architecture review's target was ~150 authored encounters in ~1.5 KB. The concrete layout **meets it with room**:

| | capacity | review target | verdict |
|---|---|---|---|
| triggers, 6 columns | **180** | 150 | ✅ |
| triggers if a 7th column (mirror) is added later | **154** (1084 / 7) | 150 | ✅ still fits — worth knowing before the contract is frozen |
| wave definitions | **26** | ~20–30 formations | ✅ at the low end; 26 is the hard `def * 10 ≤ 255` ceiling, not a budget choice |
| movement records | **64** | a handful of shapes | ✅ (`wmStage` is one byte) |

**The one number to watch is the 26-definition ceiling.** It is an *addressing* limit, not a space limit — raising it means widening `waveDefBase`'s index, which is a later decision. If the editor wants more than 26 formations, that is the constraint it will hit first, and it will hit it long before it runs out of trigger slots.

---

## 6. Runtime cost

**Zero.** Every consumer was `absolute,Y` before and remains `absolute,Y`:

| access | before | after |
|---|---|---|
| trigger row compare (2 reads) | `cmp waveTrigRowHi,y` / `cmp waveTrigRowLo,y` | identical opcode, different base |
| trigger field reads (4) | `lda waveTrigX,y` | identical |
| definition field reads (10) | `lda waveDefTable + n,y` | identical |

`absolute,Y` is four cycles wherever the table lives. No indexing mode changed, no arithmetic was added, no runtime copy is made — the engine reads the loaded package directly, under the banked-out KERNAL, exactly as it already did for the movement pool.

Measured: `gameOverrun = 0` and `scrollLate = 0` across the full 420-row traversal, and the 1 px/frame cadence held at **7.92–8.06 frames per coarse row** over 19 intervals.

---

## 7. Proof

### Package ownership — `test-movement-pool`, ALL PASS

Now covers all three tables:

```
ok  the movement pool in RAM at $f530 matches the built level package byte for byte
ok  the wave definitions in RAM at $f630 match the built level package
ok  waveDefTable resolves into the level package, not the engine PRG -- $f630
ok  the engine PRG carries no second copy of the wave definitions
ok  waveTrigRowLo/RowHi/Def/Species/Fire/Side each resolve to their package column
ok  the authored trigger rows are ABSOLUTE and 16-bit in the package -- [48, 52, 90, 126]
ok  every trigger names a definition that exists -- [0, 1, 2, 3]
ok  the authored species survived the move -- [0, 8, 0, 8]
ok  the authored fire masks survived the move -- [5, 2, 5, 0]
ok  the authored Dropper sides survived the move -- [0, 0, 0, 1]
ok  every definition's movement-program offset lands on a record boundary -- [0, 12, 24, 40]
ok  the definitions still name the programs they always did
ok  an ARC with an explicit heading ignores wmPhase entirely (Stage 2, retained)
ok  WM_HEAD_CONT continues from whatever heading the object holds (Stage 2, retained)
ok  WM_ARC_MIRROR starts on its named heading and steps ANTICLOCKWISE
```

### Combined 420-row proof — ALL PASS

```
ok  EXACTLY FOUR authored waves start across the whole 420-row stage -- wvStarted = 4
ok  the trigger cursor is exhausted and stays there -- wvNextTrig = 4
ok  no trigger was dropped -- wvDropped = 0
ok  the stage completed at the derived final progress 1655
ok  the boss phase was reached after the long stage -- lvlPhase 2
ok  the movement pool at $f530 still matches the built package after the traversal
ok  the wave definitions at $f630 are intact after the full traversal
ok  all six trigger columns at $f734 are intact after the full traversal
ok  the absolute trigger rows are still 48/52/90/126 at the end of a 1,655-row stage
ok  the package signature at $fb70 is intact
ok  the metatile definitions at $f130 are intact
ok  gameOverrun is zero / scrollLate is zero
ok  one coarse row still takes 8 displayed frames -- 19 intervals, 7.92..8.06
[note] wvSpawned = 13 enemies from those four waves
```

Four waves, thirteen enemies (4+3+3+3), no wrap, over a 1,655-coarse-row stage with all three package tables verified intact at the end.

### Regression — matches baseline exactly

| target | result |
|---|---|
| `test-boot`, `test-production`, `test-pickup`, `test-boss`, `test-lifecycle`, `test-turret-regression`, `test-player-death` | **ALL PASS** |
| `test_wave_triggers` (Stage 1 contract) | **ALL PASS** |
| `test_bank2_arena` | **ALL PASS** |
| `test-movement-pool` | **ALL PASS** |
| `test_token_encounter` | 1 failure: `schedBuildDefer` = 1 — **the repaired orbit assertions stayed green** |
| `test-encounter-director` | `publishSkip` = 11, `schedBuildDefer` = 1 |

`publishSkip` / `schedBuildDefer` are the established diagnostic noise, identical to the documented baseline. No assertion was weakened and nothing unrelated was repaired.

---

## 8. Manual VICE

**PID 57723**, PAL, visible, non-warp, launched without stealing focus.

Expect the unchanged four-wave production sequence: **row 48 sweep (rings) · row 52 S-turn (Dropper) · row 90 linger (rings) · row 126 loop (Dropper)**, then a deliberately quiet level. Two Dropper waves, no repeat. Everything the game reads to produce that now comes off the disk rather than out of the program. Your eyes remain authoritative.

---

## 9. Hygiene

`pgrep -x x64sc` confirmed a clean field before every run; every automated instance was reaped by exact PID and reported (57163, 57409, 57470, plus each harness's own). No broad `pkill`/`killall`; no user-launched instance touched. Probes live in disposable scratch.

```
$ du -sh build/    344K      (includes build/proof420; 96K after a plain `make build`)
$ du -sh .         9.0M
$ scratch          896K
```

One honest note on method: the first 420-row run reported the wave definitions as altered. That was a **variable collision in my own probe** — `defs_before` already named the metatile defs at `$f130` — not an engine fault. I measured package-vs-RAM directly, found them byte-identical, fixed the probe and re-ran.

---

## 10. Git

| | |
|---|---|
| local HEAD | `d1e4d0d` — level with `origin/main`, 0 behind / 0 ahead |
| uncommitted | 6 modified, 2 new source files, 1 new report |
| committed / pushed | **nothing** |

```
 src/dropper.asm             |   5 +-
 src/enemy.asm               |  12 +-
 src/level_package.asm       |  72 ++++++++++
 src/levelpkg.asm            |  52 +++++++
 src/waves.asm               | 330 ++++++-----------------------------
 tests/test_movement_pool.py |  58 +++++++-
 + src/encounter_format.asm, src/wave_encounters.asm (new)
```

Stage 3 is complete and scoped: no editor contract v2, no 7-byte trigger record, no mirror support, no `STAGE_NO_SPAWN_ROW`, no `WAVE_SLOTS` change, and no change to formations, firing, Dropper/protector choreography, turrets, the renderer or the scroll speed.
