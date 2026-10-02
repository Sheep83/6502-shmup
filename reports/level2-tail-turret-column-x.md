# Level 2's inert turrets — the ninth bit of a turret's sprite X

**Date:** 2026-10-02
**Symptom reported:** the last two Level 2 turrets appear but are decorative —
player hitscan has no effect and neither turret appears to fire; earlier Level 2
turrets work.
**Verdict:** root cause proven. One dropped carry bit in
`turretBuildTables`. **Four** turrets were affected, not two.
**Committed or pushed:** no. **No destructive git operation was used.**
**No authored or generated Level 2 content was altered.**

---

## 0. Root cause, in one paragraph

`src/turrets.asm`'s `turretBuildTables` derived a turret's sprite X from its
authored column with three bare `asl`s and the comment *"c * 8; c <= 37 so this
cannot carry"*. The bound is wrong: `8 * 32` is 256, so for any column of 32 or
more the third shift pushes bit 5 of the column out of the accumulator into the
carry, where the following `clc` discarded it. The `lda #0 / adc #0` that
collected "the ninth bit" only ever saw the carry out of `adc #24`.

A turret's authored column is derived into **two** representations with
different consumers. The **drawing** path (`turretOverlayRow`,
`turretPaintTick`) uses `turretCol` and was always correct, so the body appeared
in exactly the right place. **Combat** (`traceTurretRay`) and the **hostile
bolt** (`turretFireTick`) use `turretXLo/turretXHi` — so a column-33 turret was
drawn at screen X 288 and fought at screen X **32**, 256 pixels away on the
opposite side of the display. The player's hitscan could never reach it, and
its bolt was launched from the far left of the screen. Visible, unhittable and
apparently silent, from one bit.

It hid behind the authored content. Level 1 authors columns 17, 29, 9, 25, 13
and Level 3 authors 21, 9 — **none reaches 32**, which is why every existing
turret suite passed. Level 2 is the first level to place turrets in the
right-hand quarter of the screen, and it has four of them at column 33.

---

## 1. Initial state

```
branch main
HEAD 581afbe Level 2 rebuild in progress
     a9d43fe 7+1 final mux optimised
     f625216 Clipping optimisation

dirty (AUTHORED WORK, PRESERVED UNTOUCHED):
 M src/level2/stage_charset.asm      M src/level2/stage_map.asm
 M src/level2/stage_config.asm       M src/level2/stage_sprites.asm
 M src/level2/stage_enemies.asm      M src/level2/stage_turrets.asm
 M src/level2/wave_encounters.asm    M src/level2/wave_programs.asm
 M tools/level_editor/encounter_library.v6.json
 M tools/level_editor/levels/level2/level.v6.json
```

Every one of those files is in the same state at the end of this pass as at the
start — see §9.

Read: `AGENTS.md`, `docs/ENGINE_CONTRACT.md`, and
`reports/turret-combat-player-damage.md`, `turret-firing-player-damage.md`,
`turret-presentation-migration.md`, `enemy-fire-turret-activation-art.md`,
`multiload-memory-architecture.md`, `e000-level-package-and-420-row-proof.md`,
`definitive-440-row-memory-audit.md`, `twin-ray-hitscan-optimisation.md`.

Source: `src/turrets.asm` in full, `src/levelpkg.asm`, `src/level_package.asm`,
`src/levelload.asm`, `src/collision.asm`, `src/scroll.asm`, `src/boss.asm`,
`src/gamestate.asm`, `src/objects.asm`, `tools/level_editor/levels/level2/level.v6.json`.

---

## 2. The pipeline, traced end to end

The brief asked for a working turret as a control. The export sorts descending
by row, which is the order the downward-scrolling stage crosses them, so the
reported "last two" are **array indices 6 and 7**:

| idx | world row | metatile row | col | role |
|---:|---:|---:|---:|---|
| 0 | 713 | 178 | 17 | |
| 1 | 581 | 145 | **33** | |
| 2 | 553 | 138 | **33** | |
| 3 | 489 | 122 | 17 | |
| 4 | 373 | 93 | 17 | |
| 5 | 265 | 66 | 21 | **CONTROL** — the one immediately preceding |
| 6 | 229 | 57 | **33** | reported broken |
| 7 | 193 | 48 | **33** | reported broken |

### 2a. Editor / project data — **all eight present**

`tools/level_editor/levels/level2/level.v6.json` holds exactly eight turret
records, `{metatileRow, metatileCol}`, at metatile rows 48, 57, 66, 93, 122,
138, 145, 178 and columns 8, 8, 5, 4, 4, 8, 8, 4. Applying the editor's own
stated rule (`world row = metatileRow*4+1`, `world col = metatileCol*4+1`)
reproduces the table above exactly.

### 2b. Export — **all eight, byte for byte**

`src/level2/stage_turrets.asm` (generated): `TURRET_TOTAL = 8`,
`turretCols = 17, 33, 33, 17, 17, 21, 33, 33`,
`turretRows = 713, 581, 553, 489, 373, 265, 229, 193`. Identical to the
derivation from the project file. **The generated count includes them.**

### 2c. Package build — emitted, and guarded

`src/level_package.asm` emits the count at `$ff79`, the columns at `$ff7a` and
the rows lo/hi at `$ff82`/`$ff8a`, padded to `LEVELPKG_TRT_MAX = 8`. Its guards
check the row phase, the body against the stage bottom, the body against the
screen's right edge, and duplicate metatile rows. **All pass.** §6 returns to
one of those guards, because it is implicated.

### 2d. Runtime package loading — **all eight installed**

Read from the resident package with the KERNAL banked out:

```
LEVELPKG_TRTN = 8
 i  pkgCol  pkgRow  rowHi | genCol  genRow  match
 0      17     713      2 |     17     713  ok
 1      33     581      2 |     33     581  ok
 2      33     553      2 |     33     553  ok
 3      17     489      1 |     17     489  ok
 4      17     373      1 |     17     373  ok
 5      21     265      1 |     21     265  ok
 6      33     229      0 |     33     229  ok
 7      33     193      0 |     33     193  ok
```

A first attempt at this read reported a turret at stage row 51473. That was the
instrument, not the engine: `$e000-$ffff` is KERNAL ROM in the monitor's default
bank, and the package is the RAM underneath it. The figures above are taken with
`bank ram` and with the harness's address-verifying reader, because a
desynchronised monitor returns complete but **stale** dumps — which is what
produced the nonsense.

### 2e. Table derivation — correct except for one field

`turretBuildTables` output, all eight slots:

```
turretCount = 8
 i  col   row  rowHi  metaRow  wantMeta  alive  hp
 0   17   713      2      178       178      1   3
 1   33   581      2      145       145      1   3
 2   33   553      2      138       138      1   3
 3   17   489      1      122       122      1   3
 4   17   373      1       93        93      1   3
 5   21   265      1       66        66      1   3
 6   33   229      0       57        57      1   3
 7   33   193      0       48        48      1   3
```

Every column, row, metatile row, alive flag and health is right. **The sprite X
is not**, and §3 is that measurement.

### 2f. Enumeration — the lookup reaches all eight

`turretAtMetaRow` is a two-page table built at run time, and it is the only
thing the row renderer consults. A census of all 512 entries found exactly
eight stamped indices, one metatile row each:

```
turret 0 -> 178   turret 2 -> 138   turret 4 ->  93   turret 6 ->  57
turret 1 -> 145   turret 3 -> 122   turret 5 ->  66   turret 7 ->  48
```

### 2g. Activation — all eight go live

With the stage seeked so each body sits mid-page, every turret reported
`turretPaintPair = 1`, a sane `turretPaintRow`, `turretVisible = 1`, a sensible
`turretLogY`, and its own bit in `trtVisibleMask`:

```
 i   row  paintRow  pair  visible  logY  mask
 0   713       $0e     1        1   159   $01
 ...
 6   229       $0d     1        1   155   $40
 7   193       $0d     1        1   157   $80
```

Then the engine's **own scroller** was free-run across the last three turrets
from a point above the control, rather than poked, because a poked
`stageTopRow` takes `turretWorldTick`'s `!fallback` path while real play uses
the prepared shadow:

```
 turret  row  pair  visFrames    T window   logY range  shots
      5  265     1        178    264..242      54..231      2   <- CONTROL
      6  229     1        178    228..206      54..231      2
      7  193     1        178    192..170      54..231      2
```

**The broken pair are indistinguishable from the control here** — same number of
visible frames, same logY sweep, and both *fired twice*. So the fault is not
presence, not export, not loading, not enumeration, not activation, and not the
firing clock. Questions 1 through 8 of the brief all answer "correct".

---

## 3. Where it breaks: the sprite X

The discriminating measurement. For the control and each suspect, the stage was
seeked so the body sits mid-page, the ship was aligned so its **left cannon**
(`plyX + PLAYER_CANNON_L`) lands on the body's left edge, and the fire button
was held for 90 frames while `turretHealth` was watched.

```
 turret  row  col  body X  INSTALLED X  plyX  hp 3->  ray hit
      5  265   21     192          192   188       0  enemy/turret   ok
      6  229   33     288           32   284       3  nothing        FAIL
      7  193   33     288           32   284       3  nothing        FAIL
```

**`turretXLo | turretXHi<<8` is 32 where it should be 288.** Widening the same
measurement to all eight turrets gives a perfect correlation with the column:

```
 turret  col  body X  INSTALLED X  took damage
      0   17     160          160  yes
      1   33     288           32  NO
      2   33     288           32  NO
      3   17     160          160  yes
      4   17     160          160  yes
      5   21     192          192  yes
      6   33     288           32  NO
      7   33     288           32  NO

=> 4 UNDAMAGED: turrets 1, 2, 6, 7 -- every column-33 turret, and only those
```

**The reported fault is four turrets, not two.** Indices 1 and 2 (world rows 581
and 553) are equally inert; they arrive earlier in the level, where they were
presumably not engaged, or engaged from a position that happened not to matter.

---

## 4. The arithmetic

```asm
    lda LEVELPKG_TRTCOL,x
    sta turretCol,x
    // the body's left edge in sprite X: 24 + 8c, nine bits
    asl
    asl
    asl                                 // c * 8; c <= 37 so this cannot carry
    clc
    adc #24
    sta turretXLo,x
    lda #0
    adc #0                              // the ninth bit, from the add above
    sta turretXHi,x
```

Executed as the 6502 does it:

| col | want X | engine computed | |
|---:|---:|---:|---|
| 17 | 160 | 160 | ok |
| 21 | 192 | 192 | ok |
| 28 | 248 | 248 | ok |
| 29 | 256 | 256 | ok — the ninth bit comes from `adc #24` |
| 31 | 272 | 272 | ok |
| **32** | **280** | **24** | the shift's carry is lost |
| **33** | **288** | **32** | |
| **37** | **320** | **64** | |

Up to column 31 the derivation is right, and for columns 29–31 it is right *for
the stated reason* — the ninth bit really does come from the `+ 24`. From column
32 the multiply needs a ninth bit of its own and there is nowhere for it to go.
`c <= 37` was the author's bound on the authored column; the bound that keeps
`asl asl asl` inside a byte is `c <= 31`.

---

## 5. Why both symptoms, from one bit

One authored column, two derived representations, and only one of them wrong:

| path | reads | consequence |
|---|---|---|
| `turretOverlayRow` (`src/turrets.asm:1217`) writes the body's character cells | **`turretCol`** | the body is drawn at column 33 — **correct**, hence "appears visually" |
| `turretPaintTick` (`:1452`) paints its colour RAM | **`turretCol`** | colour follows the body — correct |
| `traceTurretRay` (`:1545-1548`) tests the player's nine-bit ray | **`turretXLo/XHi`** | the hitbox is at X 32..47, far left. A player under the body can never hit it → **"hitscan has no effect"** |
| `turretFireTick` (`:1720-1724`) launches the bolt | **`turretXLo/XHi`** | `ebSpawnX = 32 + TURRET_MUZZLE_X = 36`. The turret **does** fire — the free-run in §2g counted two shots each — but the bolt leaves from the opposite side of the screen → **"neither turret appears to fire"** |

That is the whole of it, and it explains why the turrets looked *decorative*
rather than *missing*: everything about their appearance is driven by the field
that was correct.

---

## 6. The capacity/range assumption, and why the guard did not catch it

`src/level_package.asm` guards the authored column:

```asm
.if (turretCols.get(t) + LEVELPKG_TRT_BODY_W > LEVELPKG_SCREEN_COLS) {
    .error "an authored turret body runs off the right of the screen"
}
```

`LEVELPKG_SCREEN_COLS = 40`, `LEVELPKG_TRT_BODY_W = 2`, so the largest
**authorised** column is **38**, while the derivation was correct only to **31**.
The guard positively permitted the columns the arithmetic got wrong. There was
no second guard anywhere expressing the 31.

Classification, as the brief asked: the limit was **neither intentional nor
obsolete — it was never stated.** It is an accidental consequence of a shift
sequence, and it was enforced nowhere. The editor can place a turret anywhere in
the right-hand quarter of the screen; nothing refused it; it simply came out
inert.

---

## 7. The fix

Smallest change that restores the intended contract: make the multiply carry its
own ninth bit, by rolling each shift's carry into a high byte — a real sixteen-bit
`(col << 3) + 24` instead of a bound nobody can check by eye.

```asm
    lda #0
    sta trtTmp                          // the ninth bit of 8c, accumulated
    lda turretCol,x
    asl
    rol trtTmp
    asl
    rol trtTmp
    asl
    rol trtTmp
    clc
    adc #24
    sta turretXLo,x
    lda trtTmp
    adc #0                              // ...plus any carry out of the add
    sta turretXHi,x
```

`trtTmp` is this routine's own declared scratch and is re-initialised a few
instructions below for the metatile-row derivation. Cost: three `rol` plus a
store and a load, **once per turret per level load** — eight turrets, once.
Nothing in any per-frame path changed.

And the bound is now asserted, against the **same** limit the authoring guard
enforces rather than against a number typed twice:

```asm
.if (24 + 8 * (LEVELPKG_SCREEN_COLS - LEVELPKG_TRT_BODY_W) > 511) {
    .error "an authored turret column can produce a sprite X wider than nine bits"
}
```

### Verified after the fix

```
 turret  row  col  body X  INSTALLED X  took damage
      0   17     160          160  yes
      1   33     288          288  yes   <- was inert
      2   33     288          288  yes   <- was inert
      3   17     160          160  yes
      4   17     160          160  yes
      5   21     192          192  yes   <- control, unchanged
      6   33     288          288  yes   <- was inert
      7   33     193->288     288  yes   <- was inert

=== every turret tested took damage ===
```

The control turret behaves exactly as before; the four column-33 turrets now
address the same pixels they are drawn on.

---

## 8. The regression

`tests/test_turret_column_x.py` — **an invariant, not a snapshot.**

> For every column the package build is willing to emit
> (`0 .. SCREEN_COLS - TRT_BODY_W`), the derived sprite X must equal
> `24 + 8 * col`, in nine bits; and the column the body is **drawn** at must be
> the same cell as the X it is **fought** at.

It pokes one package turret slot across the whole supported column range,
rebuilds the tables, and reads the derivation back. It asserts **nothing** about
any level's turret count, positions, rows or layout, and it restores the slot it
borrowed. It runs on whatever level the boot loads, because the invariant is not
a property of a level.

That shape is deliberate and is the lesson of this bug: the fault was invisible
in all the content that existed, so a test asserting today's Level 2 would not
have caught it and one asserting tomorrow's will not catch the next one. What is
not mutable is that every column the exporter permits must work.

**It fails before and passes after** — proved by reverting the derivation,
rebuilding, and running it:

```
pre-fix:  FAIL every legal authored column 0..38 derives sprite X = 24 + 8 * col
            -- col 32: want X 280, got 24; col 33: want X 288, got 32;
               col 34: want X 296, got 40; ... and 1 more
          FAIL the column the body is DRAWN at and the X it is FOUGHT at are the
               same cell
          === 2 FAILURES ===

post-fix: === ALL PASS ===
            col 31  want X 272  got 272  ok
            col 32  want X 280  got 280  ok
            col 33  want X 288  got 288  ok
```

Wired into `make test`, `make test-fast` and `make test-full`, plus its own
`make test-turret-column-x` target.

---

## 9. Files changed

| file | change | why |
|---|---|---|
| `src/turrets.asm` | `turretBuildTables`: three bare `asl`s → a real sixteen-bit `(col << 3) + 24` rolling each carry into a high byte; plus a build-time assertion that the widest authorised column fits nine bits, written against `LEVELPKG_SCREEN_COLS - LEVELPKG_TRT_BODY_W` | the root cause, and the bound that was stated nowhere |
| `tests/test_turret_column_x.py` | **new** — the column→sprite-X invariant across the whole supported range | fails before, passes after; see §8 |
| `Makefile` | `test-turret-column-x` target; the suite added to `test`, `test-fast` and `test-full` | so the regression actually runs |

**Nothing else.** No collision code was touched — the brief said not to start
there, and the evidence never pointed there. No renderer, scroller, clipping,
mux, scheduler, player, enemy, wave or Dropper file was modified.

### Generated Level 2 data: **not changed, and not regenerated**

The authored and generated Level 2 files were dirty when this pass started and
are in exactly the same state now. They still carry their original
modification time:

```
src/level2/stage_turrets.asm                      2 Oct 18:50
src/level2/stage_map.asm                          2 Oct 18:50
src/level2/stage_charset.asm                      2 Oct 18:50
src/level2/stage_config.asm                       2 Oct 18:50
src/level2/stage_enemies.asm                      2 Oct 18:50
src/level2/stage_sprites.asm                      2 Oct 18:50
src/level2/wave_encounters.asm                    2 Oct 18:50
src/level2/wave_programs.asm                      2 Oct 18:50
tools/level_editor/levels/level2/level.v6.json    2 Oct 18:50
tools/level_editor/encounter_library.v6.json      2 Oct 18:50
```

No exporter was run and no re-export was required: the authored data was correct
at every stage (§2a–§2d). The fault was entirely in the engine's runtime
derivation, so **the normal workflow needed nothing beyond `make build`**.

---

## 10. Tests

| gate | result |
|---|---|
| **`tests/test_turret_column_x.py`** (new) | **ALL PASS** — and **2 FAILURES on the pre-fix engine** |
| per-turret hitscan damage, all 8, Level 2 | **8/8 take damage** (was 4/8) |
| `make smoke` | **PASS** — `BOOT: PASS`, `CAMPAIGN LOOP: PASS`, `ENGINE HEALTH: PASS`, `ROUTINE REGRESSION: PASS`, `edgeLate 0`, `statLate 0` |
| `test_regen_page_shift` (a turret destroyed mid-regeneration — the closest existing suite to this code) | **ALL PASS** |
| `test_turret_regression` | 2 failures — **identical on the pre-fix engine** |
| `test_turret_arming` | 3 failures — **identical on the pre-fix engine** |
| `test_sfx` | 4 failures — **identical on the pre-fix engine** |

The three failing suites were run against an engine built from the pre-fix
derivation — the only production file this pass changed — and failed with the
same assertions and the same text in both builds. `test_sfx`'s two structural
ones (`$1840 vs $1768`, "sfx state is nine bytes … 10") are byte-identical
either way and are unrelated to turrets; its two counter assertions
(`schedBuildDefer`, `publishSkip`) are over the test's ceiling in both builds.

Larger renderer/mux/scroller/raster tiers were **not** run: the fix is six
instructions in a routine that executes once per level load, touches no
per-frame path, and the brief asks for those tiers only if the fix implicates
them. `make smoke`'s engine-health gate covers the frame budget and the raster
diagnostics, and it passes.

### Manual VICE acceptance was NOT performed and is not claimed

Everything above is automated instrumentation. The engine's own counters and
`turretHealth` prove the hitbox now coincides with the body, but a human has not
watched a column-33 turret take fire on screen. Two minutes, at normal speed,
on Level 2:

1. **Fly to the right-hand side and shoot the turrets there.** The four at
   column 33 — the ones about three quarters of the way across the playfield —
   should now flash on each hit and be destroyed by three. Before this fix they
   absorbed nothing.
2. **Sit under one of them and let it shoot back.** Its bolt should now leave
   *its own barrel*, not the left edge of the screen.
3. The turrets at columns 17 and 21 should behave exactly as they always did.

---

## 11. Remaining risks and follow-up

1. **The reported scope was two turrets; the real scope was four.** Indices 1
   and 2 (world rows 581 and 553, column 33) were equally inert and are equally
   repaired. Worth knowing when re-playing the level: four turrets have changed
   behaviour, not two.
2. **The other guard in that family is still only as wide as its arithmetic.**
   This pass fixed the column derivation and asserted its bound. The sibling
   derivation in the same loop — the metatile row, a genuine sixteen-bit shift —
   was read carefully and is correct, and §2e measured it right for all eight
   turrets including both rows below 256. No other single-byte truncation was
   found in `turretBuildTables`.
3. **`CONTRACT v2 TEMPORARY LIMITS` are still in force** and are unrelated to
   this bug: at most 8 turrets (`trtDeadPending` is one byte of flags) and at
   most one per metatile row (`turretAtMetaRow` holds a single index). Both are
   enforced at package build with explicit errors, both are honest about being
   temporary, and Level 2 sits exactly at the 8 limit — so the *next* turret
   Level 2 authors will be a build error, not a silent drop. That is the next
   thing likely to bite an author, and it is a real limit rather than an
   accidental one.
4. **The stage wrapped rather than completing** in one long free-run
   observation (`stageTopRow` folded past 0 and the level carried on, with
   `lvlPhase` 0 and `stageComplete` 0 throughout). That run drove the scroller
   through coarse free-run slices after a `gsEnterNextLevel`, so the condition
   may well be an artefact of how it was driven rather than something a player
   can reach. **It was not pursued** — it is unrelated to the turret fault, and
   chasing it would have been scope creep. Flagged because if Level 2 ever fails
   to hand over to its boss, this is the first thing to look at.
5. **`tools/run_tier.sh` still has no timeout or kill logic**, so one hung suite
   stalls a whole tier. It stalled this pass once and the suite had to be
   terminated by its exact PID. Pre-existing, reported in the previous pass,
   still true.

---

## 12. Status

- **Nothing committed, nothing pushed.**
- **No `git checkout`, `restore`, `reset`, `stash` or `clean`.** The before/after
  comparisons were made by copying `src/turrets.asm` aside and back under a
  shell `trap` that fires on every exit path, verified by `git status` after
  each cycle.
- **All dirty authored work was preserved** — the ten Level 2 and editor files
  are byte-for-byte as they were, with their original timestamps (§9).
- **VICE hygiene:** every emulator launched with `-console` directly, never
  `open -a`, exact PID retained and reaped on success, failure and exception.
  No broad `pkill`/`killall` at any point; one hung suite was terminated by
  naming its python and VICE PIDs individually. No user-launched session
  touched, no focus taken. `pgrep -x x64sc` reports none remaining, checked
  after every run.
- **Disk:** `build/` 404K (current binary, symbols and disk image only, no
  per-run directories); session scratchpad 1.0M, outside the repository, holding
  the diagnostics and one pre-fix copy of `turrets.asm`.
- Final `git status --porcelain`:

```
 M Makefile                                        <- this pass
 M src/level2/stage_charset.asm                    } pre-existing authored work,
 M src/level2/stage_config.asm                     } untouched
 M src/level2/stage_enemies.asm                    }
 M src/level2/stage_map.asm                        }
 M src/level2/stage_sprites.asm                    }
 M src/level2/stage_turrets.asm                    }
 M src/level2/wave_encounters.asm                  }
 M src/level2/wave_programs.asm                    }
 M src/turrets.asm                                 <- this pass
 M tools/level_editor/encounter_library.v6.json    } pre-existing, untouched
 M tools/level_editor/levels/level2/level.v6.json  }
?? reports/level2-tail-turret-column-x.md          <- this pass
?? tests/test_turret_column_x.py                   <- this pass
```

---

## 13. The answers, as asked

| # | question | answer |
|---:|---|---|
| 1 | all final turrets in authoritative editor data? | **yes**, 8 of 8 |
| 2 | all exported into generated data? | **yes**, byte for byte |
| 3 | does the generated count include them? | **yes**, `TURRET_TOTAL = 8` |
| 4 | row/position/type values correct and representable? | **yes** — rows, columns and metatile rows all correct and in range |
| 5 | does the package loader install all records? | **yes**, `LEVELPKG_TRTN = 8` and all 8 columns/rows match |
| 6 | does runtime enumeration reach the final records? | **yes** — the two-page lookup holds exactly 8 stamped indices, one row each |
| 7 | do they enter the expected activation/live state? | **yes** — `turretVisible = 1`, sane `logY`, own bit in `trtVisibleMask`, `alive = 1`, `hp = 3` |
| 8 | if they activate, why do they not fire? | **they DO fire** — the free-run counted two shots each. The bolt is launched from `turretXLo/XHi`, so it left from screen X 36 instead of 292 |
| 9 | are they in the state the hitscan inspects? | **yes for `turretVisible`/`turretAlive`, no for X** — `traceTurretRay` tested a hitbox 256 pixels from the body |
| 10 | any end-of-table / max-count / byte-width / sentinel / stage-row / range / indexing / package-size boundary? | **yes: a byte-width boundary.** `8 * col` crosses 256 at column 32 and the carry was discarded. Not a count, not a table end, not a sentinel, not a stage row |
| 11 | are the visible graphics merely map characters? | **no.** Level 2's metatile glyph codes span 96–218 and the engine's turret glyphs are 226–229, so the body can only have been drawn by `turretOverlayRow` — which means the record existed. Ruled out by data, early |
| 12 | why do earlier Level 2 turrets work? | **they are at columns 17 and 21.** Every column-33 turret failed and only those — indices 1, 2, 6 and 7. Level 1 (17, 29, 9, 25, 13) and Level 3 (21, 9) never reach column 32, which is why no existing suite saw it |
