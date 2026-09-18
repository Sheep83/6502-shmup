# The `$e000` level package, and a 420-row capacity proof

**Date:** 2026-09-18
**HEAD:** `722dbbd` — *HUD bank switching, token progress* (the HEAD the memory audit was performed at; no production modifications existed beyond the five untracked reports)
**Outcome:** implemented and proven. Both checkpoints passed, the 420-row stage traverses end to end, and two previously invisible defects were found and fixed.
**Nothing committed. Nothing pushed.**

---

## 1. Executive summary

The level terrain now lives in a **separately loaded file** at `$e000`, in RAM under
the banked-out KERNAL, exactly as the memory audit recommended. The 105-row
production level is byte- and pixel-identical after relocation, and a 420-row
proof stage — the authored terrain repeated four times — scrolls its full
**1,655 coarse rows (4 min 24.8 s)** to a correct stage end and boss transition
with `gameOverrun` and `scrollLate` both zero.

**The audit's central claim held: the terrain reader really is position-independent
and the relocation cost zero cycles.** But the audit was *necessary and not
sufficient*, and two things it could not have seen had to be fixed:

1. **You cannot read the level package while the KERNAL is mapped.** A 6510 store
   at `$e000-$ffff` always reaches RAM — which is why the load works — but a
   *load* from those addresses returns ROM. `terrainInit` and `scrollInit` both
   run before the old `$01 = $35`, so they transposed and printed KERNAL ROM. The
   fix is one store moved to the top of `entry`.
2. **The turret subsystem independently capped stages at 255 metatile rows**, and
   `turretOverlayRow` derived its metatile row with a shift that is only exact to
   511 stage rows. Neither is visible at 105 rows; both are hard blockers for 440.

---

## 2. Initial state

```
$ git log --oneline -1
722dbbd HUD bank switching, token progress
$ git status --porcelain       (five untracked reports only)
$ git diff --stat              <empty>
```

---

## 3. Checkpoint A — the level-file load path

Implemented **with terrain still at `$5800`**, so the game could not be affected
by anything except the load itself.

**New files:** `src/levelpkg.asm` (the address contract, imported by both builds),
`src/levelload.asm` (the loader), `src/level_package.asm` (the package's own PRG).

**Result — all pass:**

```
ok  the level package signature is present at $fb70 after boot -- [0x19,0x65,0x6c,0x70]
ok  all 1050 stage-map bytes at $e000 match the generated source -- 0 mismatches
ok  all 544 metatile-definition bytes at $f130 match the source -- 0 mismatches
ok  the IRQ vector at $fffe is the engine's own handler, not level data -- $8600
ok  the game is running after the load -- frameCounter 6664 -> 7530
ok  gameOverrun is zero right after boot -- 0
ok  scrollLate is zero right after boot -- 0
```

### The first defect: the signature could never have matched

The first attempt halted on the loader's red border at `$5343`. The KERNAL had
reported success and the bytes *were* in RAM — but the check read them back with
`$01 = $37`, so every `lda LEVELPKG_SIG` returned a byte of KERNAL ROM. The
verification now banks the ROM out across the compare, with interrupts held off
because the IRQ vector still points into the KERNAL at that point in the boot.

`levelLoad` also now records **why** it failed in `levelLoadError` (the KERNAL
status byte, or `$ff` for a signature mismatch) — a red border alone cannot tell
"no such file" from "loaded the wrong thing".

---

## 4. Checkpoint B — relocating the 105-row terrain

`src/terrain.asm` no longer emits the map. It declares where the package puts it:

```asm
.label metatileDefs      = LEVELPKG_DEFS     // $f130
.label stageMetatileRows = LEVELPKG_MAP      // $e000
```

**Nothing else in that file changed**, because the row lookup already builds a
full 16-bit pointer (`trSrc = stageMetatileRows + row*10`, `lda (trSrc),y`).

### The second defect: the engine read the package too early

With the map moved, the screen filled with values like `76`, `201`, `240` —
6502 opcodes. `terrainInit` transposes `metatileDefs` into `trTiles` and
`scrollInit` builds both pages, and **both run before `installRenderer` switched
`$01`**. They were reading KERNAL ROM, exactly as the signature check had been.

The fix is one store, moved from `installRenderer` to the top of `entry`, right
after the load:

```asm
    jsr levelLoad
    sei
    lda #$35
    sta $01          // the package is unreadable until this
```

Verified safe: `src/levelload.asm` is **the only caller of a ROM routine in the
whole project** (`grep` for `jsr $ff..` outside it returns nothing), and
interrupts stay off until `installRenderer` has installed its own `$fffe`.

### Equivalence proof

The pre-relocation binary was rebuilt from a pristine `git archive HEAD` in
scratch, and both builds were fingerprinted by sampling five matrix rows of the
displayed page keyed by `pageTopRow` — terrain is a pure function of stage row,
so equal stamps must give equal bytes.

```
TERRAIN: 50 rows across 10 stage-row positions -> IDENTICAL
TURRET authored world rows -> IDENTICAL  [345,337,225,217,117,109,25,5]
TURRET paint rows at 10 common worldProgress values -> IDENTICAL
COUNTERS ref {gameOverrun 0, scrollLate 0, publishSkip 12, schedBuildDefer 1}
         new {gameOverrun 0, scrollLate 0, publishSkip 12, schedBuildDefer 1}
```

This was re-run **after** the turret rework of §6 and still reported IDENTICAL.

`test-boss` (stage end + boss transition), `test-turret-regression` and
`test-bank2-arena` all pass.

---

## 5. The final load architecture

| | |
|---|---|
| **filename** | `LEVEL1` — on-disk bytes `4c 45 56 45 4c 31`, byte-identical to the `.text "LEVEL1"` the loader compares (upper-case ASCII and PETSCII share `$41-$5a`) |
| **load address** | `$e000`, carried in the file's own first two bytes |
| **secondary address** | **1**, so the KERNAL honours the file's load address — `$e000` is written down once, in `src/levelpkg.asm` |
| **device** | 8 |
| **build output** | `build/level1.prg`, written to `build/shmup.d64` beside `engine` by `make build`, which now always produces the disk image |
| **when** | the **first instruction of `entry`**, before `sei`, while `$01 = $37` and the KERNAL's own interrupts still run |
| **failure** | fatal and visible — `levelLoadError` records the cause, border and background go red, the machine halts. There is no fallback terrain to fall back to |
| **register/KERNAL state** | the loader uses only A/X/Y and KERNAL zero page (`$ae`-`$c4`); the engine's own pointers are `$f7-$fe` and are untouched |
| **`$01` → `$35`** | immediately after the load returns, at the top of `entry` |
| **IRQs** | enabled (the KERNAL's) during the load; `sei` immediately after; `cli` only after `installRenderer` |
| **generalising** | a second level is the same call with a different name. No asset manager, no resource table |

### Package layout (the audited contract, unchanged)

| component | address | budget | 105-row | 420-row |
|---|---|---|---|---|
| stage map | `$e000` | 4,400 | 1,050 | **4,200** (`$e000-$f067`) |
| metatile defs | `$f130` | 1,024 | 544 | 544 |
| encounter package | `$f530` | 1,600 | **reserved, empty** | reserved |
| signature | `$fb70` | 4 | 4 | 4 |
| hardware vectors | `$fffa` | — | never touched | never touched |

Guards in `src/levelpkg.asm` prove at assembly time that the components fit, do
not overlap, and cannot reach `$fffa`; guards in `src/level_package.asm` prove the
emitted sizes; guards in `src/terrain.asm` prove the level the *engine* was
compiled against fits the same budgets.

---

## 6. Previously hidden 8-bit assumptions

Both were in `src/turrets.asm`, both invisible at 105 rows, both **hard build
failures** at 420 — so no 440-row stage could ever have been built without them.

| # | assumption | was | now |
|---|---|---|---|
| 1 | `turretAtMetaRow` is one page indexed by one byte | `.if (STAGE_METATILE_ROWS > 255) .error` | **two pages**, base selected from bit 8 of the metatile row |
| 2 | `turretOverlayRow` derives metatileRow with two shifts through A, dropping everything above bit 8 of the stage row | `.if (TERRAIN_STAGE_ROWS > 511) .error` | a **real 16-bit shift** keeping the high half in `trtMetaHi` |
| 3 | the once-per-coarse-step page-reach scan kept a byte cursor and wrapped with `cpx #STAGE_METATILE_ROWS` | byte | **16-bit cursor** with a 16-bit wrap |

Costs: the overlay path gains ~25 cycles and runs on about two generated rows a
frame — **~50 cycles/frame**, against 19,656. The scan runs **once per coarse
step**, on the idle frame the scroller already reserves for it, so its widening
is unmeasurable. `gameOverrun` and `scrollLate` stayed at zero throughout.

`turretAtMetaRow` at two pages no longer fitted the 256 bytes at `$6d00`, so the
turret tables **moved to `$5800`** — the run the terrain map itself vacated,
precisely the bonus the memory audit predicted. Still CPU-only data outside VIC
bank 0. Tables now `$5800-$5a33`; `$5a34-$63ff` remains free.

### One limit deliberately NOT changed

`trtDeadPending` is one **bit per turret in a single byte**, so `TURRET_TOTAL`
cannot exceed 8. That is a turret-*count* limit, not a stage-row assumption, and
it is not part of the memory contract — so per the brief it was left alone, and
the proof's turret layout was designed around it (§8).

---

## 7. The 420-row proof stage

Generated by **`tools/gen_proof420.py`** (kept; the expanded data is not):

```
$ make proof420
build/proof420: 420 metatile rows (4200 map bytes), 1680 logical rows,
                turret rows [1605, 1597, 1065, 1057, 537, 529, 25, 5]
```

- Terrain: the authored Level 1 map repeated **four times, byte for byte**.
  Nothing invented, nothing edited.
- Metatile definitions and charset: **shared, not repeated** — one tile set.
- `src/level1` is untouched. The proof is generated into `build/proof420` and
  selected with the new `LEVELDIR` make variable, which KickAssembler resolves
  through `-libdir`. `make build` returns the production level.

**Geometry, verified against the engine rather than assumed:**

| | value |
|---|---|
| map bytes | 4,200 (`$e000-$f067`) |
| logical rows | 1,680 |
| `STAGE_START_ROW` | **1,655** |
| frames | 1,655 × 8 = **13,240** |
| duration | **264.8 s = 4 min 24.8 s** |

---

## 8. Turret offsets

The eight authored turrets are spread **two per terrain copy**, each offset by its
copy's world-row base (420 logical rows per copy), preserving its position within
that copy. Thirty-two would have exceeded the `trtDeadPending` byte (§6).

| copy | offset | world rows |
|---|---|---|
| 0 | +0 | 5, 25 |
| 1 | +420 | 529, 537 |
| 2 | +840 | 1057, 1065 |
| 3 | +1260 | 1597, 1605 |

This is what the proof actually needs: authored world rows either side of **every**
8-bit boundary the stage crosses. Verified live, read back as 16-bit values:

```
ok  the eight authored turret world rows are the offset copies, 16-bit
    -- [1605, 1597, 1065, 1057, 537, 529, 25, 5]
ok  ...and they straddle every 8-bit boundary the stage crosses
```

Every generated row keeps `row mod 4 == 1`, no two share a metatile row, and every
body fits the stage — all checked by the engine's own existing assembly-time guards.

---

## 9. Wave behaviour over the long stage

**Unchanged, and deliberately so.** The director still uses its wrapping
delta-coded trigger list (period 126 coarse rows). Over 1,655 rows it simply
repeats about thirteen times:

```
wvStarted = 52    wvDropped = 0    wvSpawned = 169
```

`wvDropped = 0` is the useful number: across a stage thirteen times longer than
the authored cycle, no trigger ever found both wave instances busy. No mechanical
adjustment was needed. The absolute-trigger-row migration remains a separate task.

---

## 10. Boundary tests

Terrain was verified not by eye but by **decoding the expected characters from the
level editor's own bytes** — for stage row *r*, each of the ten metatiles of row
*r*/4 must print `metatileDefs[id*16 + (r%4)*4 + 0..3]` — and comparing against the
live screen at world rows on both sides of every boundary
(255/256, 511/512, 767/768, 1023/1024, 1279/1280, 1535/1536):

```
ok  the 4200-byte map at $e000 is 4 exact copies of the authored terrain
ok  terrain at all 12 boundary world rows decodes to real glyphs -- 0 bad
ok  every sampled row decodes EXACTLY as the authored source says
    (60 rows across 12 boundary world rows) -- 0 rows differ
```

That exercises the whole path — the map at `$e000`, the 16-bit row lookup, the
transposed sub-row tables and the row writer — at world rows a 105-row level can
never reach.

---

## 11. Full-stage traversal

```
ok  worldProgress advanced monotonically for the whole traversal
ok  coarseCount tracks worldProgress 1:1 -- no coarse row skipped or repeated -- worst delta 0
ok  the scroller invariant held at every sample, past every 8-bit boundary -- 0 violations
ok  the stage completed at the derived final progress 1655
    -- stageComplete first seen at worldProgress 1655
ok  the traversal really crossed every 8-bit boundary -- final worldProgress 1655
ok  the scroller froze on the last complete authored screen (stageTopRow 0)
ok  the fine scroll froze too -- 0
ok  the boss phase was reached after the long stage -- lvlPhase 2
ok  gameOverrun is zero across the whole 420-row traversal -- 0
ok  scrollLate is zero across the whole 420-row traversal -- 0
ok  one coarse row still takes 8 displayed frames at 1 px/frame, measured across
    the whole 420-row stage -- 19 intervals, min 7.92 max 8.10
```

The cadence measurement is the one that matters most for a long stage: the
1 px/frame contract holds at row 1,600 exactly as it does at row 16.

---

## 12. Performance counters

| counter | 105-row (relocated) | 420-row proof | verdict |
|---|---|---|---|
| `gameOverrun` | **0** | **0** | clean |
| `scrollLate` | **0** | **0** | clean |
| `publishSkip` | 12–18 | 24 | **pre-existing noise** (11–17 at HEAD before any of this work) |
| `schedBuildDefer` | 1 | 1 | pre-existing noise |

---

## 13. Test results on the restored default build

| target | result |
|---|---|
| `test-boot` | **ALL PASS** |
| `test-boss` | **ALL PASS** — stage end and boss transition intact |
| `test-turret-regression` | **ALL PASS** |
| `test-bank2-arena` | **ALL PASS** — the boss bank-2 mirror is unaffected by the package |
| `test-lifecycle` | **ALL PASS** |
| `test-player-death` | **ALL PASS** |
| `test-production` | 1 failure: `publishSkip` = 14 |
| `test-clip-scratch` | 2 failures: `publishSkip` = 18, `schedBuildDefer` = 1 |

**Known pre-existing noise, not regressions and not fixed or hidden:**
`publishSkip` has been non-zero and failing since before this work (11 at the
audit's baseline); `schedBuildDefer` = 1 appears under heavy monitor stepping;
`test-pickup` still references the removed symbol `waveTrigTokenLo`; some
population-sampling assertions vary run to run. No test was weakened.

### One test-infrastructure change

`tests/harness.py` substitutes the disk image when handed the PRG. A bare PRG can
no longer boot — there is no drive for `LEVEL1` — so the one place that owns
bringing a machine up makes the substitution, rather than editing twenty call
sites. `-autostartprgmode 1` is dropped; `make run` likewise now autostarts the d64.

---

## 14. Manual VICE

Both launched visibly, PAL, **non-warp, no acceleration**, owned by this task:

- **PID 18449** — the restored 105-row production stage (terminated after its look).
- **PID 18592** — the **420-row proof stage**, left running. This is the one that
  needs human eyes: 4 min 25 s of continuous scrolling is where a timing or
  regeneration fault would show that no counter catches.

Watch for terrain smoothness across the four copy seams, turrets appearing at the
offset world rows in copies 2–4, and the stage ending cleanly into the boss.
**Manual visible output is authoritative over the green automated results above —
that judgement is yours, not mine.**

Close it yourself or say the word and I will terminate that exact PID. No broad
`pkill`/`killall` was used; every automated instance was reaped by exact PID and
`pgrep` confirmed a clean field before each run.

---

## 15. Final content state

- **`src/level1` is untouched.** The authored production level remains the default.
- `make build` produces the 105-row game; `make proof420` regenerates and builds
  the long stage; `make build` returns to default.
- **The generator is kept (`tools/gen_proof420.py`), not the expanded data.**
  `build/proof420` is generated output under `build/`, not tracked source.
- `build/` currently holds the **420-row** artefacts because the manual VICE
  session above is running them. One `make build` restores the default.

---

## 16. Files changed

| file | change |
|---|---|
| `src/levelpkg.asm` | **new** — the package address contract, shared by both builds |
| `src/levelload.asm` | **new** — the KERNAL load, signature check and fatal-failure halt |
| `src/level_package.asm` | **new** — the package's own PRG: map, defs, signature |
| `tools/gen_proof420.py` | **new** — the 420-row proof generator |
| `src/main.asm` | `jsr levelLoad` first; `$01 = $35` moved to the top of `entry`; imports `levelpkg.asm` and `levelload.asm`; level imports made directory-relative; main's guard tightened to `$5300` |
| `src/terrain.asm` | map/defs become `.label`s at the package addresses; size guards replaced by budget guards |
| `src/turrets.asm` | 16-bit metatile-row derivation and scan cursor; two-page `turretAtMetaRow`; tables moved to `$5800`; guards widened to 2,047 stage rows / 512 metatile rows |
| `Makefile` | `LEVELDIR`; map split; second KickAssembler invocation; d64 always built with both files; `proof420` target; `run` autostarts the d64 |
| `tests/harness.py` | boots the disk image |

```
 Makefile         |  59 +++++++++++++++---
 src/main.asm     |  52 ++++++++++++++--
 src/terrain.asm  |  52 ++++++++++------
 src/turrets.asm  | 145 +++++++++++++++++++++++++++++++++-----------
 tests/harness.py |  21 +++++-
 5 files changed, 264 insertions(+), 65 deletions(-)
```

---

## 17. Final git status and disk usage

```
$ git status --porcelain
 M Makefile
 M src/main.asm
 M src/terrain.asm
 M src/turrets.asm
 M tests/harness.py
?? reports/definitive-440-row-memory-audit.md
?? reports/e000-level-package-and-420-row-proof.md
?? reports/level-editor-current-engine-contract-review.md
?? reports/scroll-speed-1px-restoration.md
?? reports/scroll-speed-2px-per-frame-trial.md
?? reports/wave-movement-architecture-and-editor-contract.md
?? src/level_package.asm
?? src/levelload.asm
?? src/levelpkg.asm
?? tools/gen_proof420.py

$ du -sh build/    364K   (includes build/proof420; 96K after `make build`)
$ du -sh .         8.2M
```

All five pre-existing untracked reports are preserved. Disposable scratch holds
the probes and logs; the pristine-HEAD reference tree used for the equivalence
comparison was deleted after use.

---

## 18. Confirmation

**Nothing was committed. Nothing was pushed.** No destructive reset was used, no
test was weakened, no unrelated system was refactored, and the wave/editor
contract was not touched. The stop condition was not reached: the `$e000`
architecture did not contradict the implementation — loading corrupted no runtime
state, the KERNAL loaded the file cleanly in the real boot sequence, and the
terrain reader proved to be exactly as position-independent as the audit claimed.
The two defects found were in *reading* the package and in the turret subsystem's
own row widths, and both are fixed and proven.
