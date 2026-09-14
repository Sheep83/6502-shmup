# VIC bank 0 reclamation

Implements `reports/vic-bank-0-memory-audit.md`, plus the full retirement of the
P0–P5 fixture infrastructure. The rule now holds:

> **Nothing lives in VIC bank 0 unless the VIC reads it.**

## What moved, and what went

| item | was | now |
|---|---|---|
| P5 ring tables | `$2400-$27ff` (VIC0) | **deleted** with the fixtures |
| raster executor | `$2c00-$3093` (VIC0) | `$8600-$8a93`, outside the bank |
| diagnostic sprites | `$2000-$23ff` (VIC0) | **deleted** |

The executor is at `$8600` because `$01` is `$35` while the game runs — BASIC and
KERNAL are both banked out, so `$8000-$bfff` is plain RAM only the CPU can see.
The IRQ vector at `$fffe` is written from a label, so it followed without being
told. The P5 tables were relocated first, then deleted outright when the fixture
system went; relocating and then removing is why they appear twice in the work.

## Resulting VIC bank 0 map

| range | size | contents |
|---|---:|---|
| `$0000-$033f` | 832 | system (ZP, stack, vectors) |
| `$0340-$03ff` | 192 | clip scratch, 3 blocks |
| `$0400-$07ff` | 1024 | screen page A |
| `$0800-$0fff` | 2048 | terrain charset window |
| `$1000-$1fff` | 4096 | character ROM shadow — CPU code only, never VIC capacity |
| **`$2000-$27ff`** | **2048** | **FREE — 32 blocks** |
| `$2800-$2bff` | 1024 | screen page B |
| **`$2c00-$30ff`** | **1280** | **FREE — 20 blocks** |
| `$3100-$31ff` | 256 | clip scratch, 4 blocks |
| `$3200-$357f` | 896 | HUD bitmaps |
| `$3580-$363f` | 192 | player bitmaps |
| `$3640-$367f` | 64 | enemy bitmap |
| `$3680-$36bf` | 64 | clip scratch |
| `$36c0-$36ff` | 64 | projectile bitmap |
| `$3700-$37ff` | 256 | clip scratch, 4 blocks |
| `$3800-$3fff` | 2048 | blank charset + idle byte `$3fff` |

## Reclaimed capacity

```
free:              3328 B  =  52 aligned 64-byte sprite blocks
sprite blocks used:  31     (HUD 14, clip 12, player 3, enemy 1, projectile 1)
total capacity:      83 blocks / 5312 B
```

**This matches the audit's prediction exactly: 52 spare blocks / 3328 B.** No
difference to explain. The audit derived it as 11456 B of VIC-addressable pool
(16384 − 4096 ROM shadow − 832 system) minus 8128 B committed, and the binary
now agrees to the byte.

The two free runs are not contiguous — screen page B sits between them — but
sprite blocks are independently addressed, so that costs nothing. The optional
contiguous-arena reorganisation was **not** attempted, as instructed.

## P0–P5 fixture infrastructure retired

Deleted outright: `src/sprites.asm`, `src/fixtures.asm`, `src/p3_fixtures.asm`,
`src/p4_fixtures.asm`, `src/p5_tables.asm`, `src/p5_ring.asm`;
`tests/test_p0..p5.py`, `test_engine.py`, `test_batch_window.py`,
`sprite_identity.py`, `p2_model.py`, `p3_model.py`, `p4_model.py`,
`p5_model.py`; `tools/gen_p3_fixtures.py`, `gen_p4_fixtures.py`,
`gen_p5_tables.py`; and the `test-p0..p5`, `test-engine-full`,
`test-renderer-full`, `test-fast`, `p3-fixtures`, `p4-fixtures` targets.

Removed from production source: the frame-loop hooks (`fixtureMoves` gating
`motionTick`, and its term in the rebuild-staleness test), the keyboard
selectors (`fixtureKeyPoll`, `readNextFixture`, `readJumpP3/P4/P5`,
`FIXTURE_KEYS` and its guarded call), `rebuild`/`republish`, `fixtureIndex` and
its key-edge state, the whole `motionTick` system with its `$c400` state block,
and the four fixture-only diagnostic HUD rows (P5, P3, P2, FIX) with their label
tables.

**Kept, because production genuinely uses them:**

- **`motion.asm`'s `$c300` logical sprite state** — `logCount`, `logY`, `logX`,
  `logXHi`, `logPtr`, `logCol`. These are the schedule builder's input; enemies,
  projectiles and the clipping layer write them every frame. They lived in that
  file only because the fixture loader was their first author, so the file
  survives holding exactly them.
- **Every production health counter.** Verified present in the binary after the
  cut: `gameOverrun`, `publishSkip`, `schedBuildDefer`, `scrollLate`,
  `edgeLate`, `topSplitMax`, `botSplitMax`, `statOverflow`, `statRejRange`,
  `statRejUnsafe`, `statRejMargin`, `statReuse`, `statAccepted`,
  `statPageMismatch`, `statPtrMismatch`, `clipPoolFull`, `wvDropped`,
  `objAllocFail`, `objDoubleFree`.
- **The stats and scroll HUD rows.** The stats row lost only its `FIX` field;
  `ACC`/`REU`/`MRG`/`UNS` are real renderer counters and stayed, with the
  remaining four fields shifted left into the vacated column.
- `sortTick` / `buildSchedule` / `publishSchedule`, which the production frame
  calls directly and which the fixtures merely also happened to use.

## Qualification

**Build:** clean.

**Focused relocation proof** (transient probe, scratchpad, since deleted):
ALL PASS over **17,622 frames** of ordinary production play.

- executor confirmed outside VIC0 (`irqHandler $8600`)
- `spriteBitmaps`, `ringXLo`, `motionTick`, `fixtureMoves`, `loadFixture`,
  `fixtureIndex` all absent from the symbol table
- all 18 production counters confirmed present
- `gameOverrun` `publishSkip` `schedBuildDefer` `scrollLate` `statOverflow`
  `statPageMismatch` `statPtrMismatch` `clipPoolFull` `objAllocFail`
  `objDoubleFree` all **0**

**Re-measured raster diagnostics after the executor move — unchanged:**

| | value | expected |
|---|---:|---|
| `topSplitMax` | **55** | 55 (54 only at YSCROLL=7) |
| `botSplitMax` | **248** | 248 |
| `edgeLate` | **0** | 0 |

Both aperture splits still land on their own raster. The relocation was an
address change, not a timing change, and the instrumentation says so.

**Production smoke — one `make test` run: ALL PASS, 5:03.** Boot, production,
turret regression and encounter director. Health counters zero throughout; the
turret firing regression, the projectile cap, the two-instance wave overlap and
the composed movement stages all behave as before.

The retired P0–P5 ladder was not replayed, as instructed.

## Notes

- The PRG is unchanged in size at 51,164 bytes despite ~9,400 lines removed: it
  spans `$0801-$cfda` and the reclaimed VIC0 regions are interior gaps, which a
  contiguous PRG fills with zeros either way.
- `src/terrain.asm` lost one term from a zero-page collision assertion — it
  named `fx_src`, the fixture loader's pointer, which no longer exists. `trSrc`
  is still checked against `scrPtr`.
- Comment blocks in the Makefile that documented the deleted targets were
  removed rather than left to mislead; no other comment surgery was done.
- **Incident, disclosed:** while removing the boot hooks, a regex of mine using
  `re.DOTALL` with a greedy `.*` over-matched and truncated `src/main.asm` from
  1444 lines to 354. Nothing was lost — the file was reconstructed forward from
  `git show HEAD:src/main.asm` with every edit reapplied, and the two guard
  attempts to recover it destructively were correctly refused by the harness.
  The final file is 959 lines and builds clean. Worth knowing only because it is
  the reason `main.asm`'s diff is large.

## Hygiene

```text
du -sh build/      84K     build/
du -sh .           3.5M    .
```

Transient probe and map extracts lived in the session scratchpad and `/tmp` and
are removed. Every VICE process was owned by PID and reaped (`rc=-15`); none
remain. No broad `pkill`, no focus theft, no persistent VICE settings touched.
Nothing committed or pushed.

```text
$ git status --short
 M Makefile                       D src/p3_fixtures.asm
 M src/enemy.asm                  D src/p4_fixtures.asm
 D src/fixtures.asm               D src/p5_ring.asm
 M src/hud.asm                    D src/p5_tables.asm
 M src/main.asm                   M src/player.asm
 M src/motion.asm                 M src/renderer.asm
 M src/movement.asm               D src/sprites.asm
 M src/objects.asm                M src/terrain.asm
 M src/waves.asm
 D tests/p2_model.py              D tests/test_p0.py
 D tests/p3_model.py              D tests/test_p1.py
 D tests/p4_model.py              D tests/test_p2.py
 D tests/p5_model.py              D tests/test_p3.py
 D tests/sprite_identity.py       D tests/test_p4.py
 D tests/test_batch_window.py     D tests/test_p5.py
 M tests/test_encounter_director.py
 D tests/test_engine.py
 D tools/gen_p3_fixtures.py
 D tools/gen_p4_fixtures.py
 D tools/gen_p5_tables.py
?? src/clip.asm                   ?? tests/test_clip_scratch.py
?? tests/test_flight_paths.py     ?? tests/test_ingress_egress.py
?? reports/  (six reports from this and preceding tasks)

$ git diff --stat
 34 files changed, 1195 insertions(+), 9449 deletions(-)
```

`src/clip.asm`, `src/movement.asm`, `src/waves.asm`, the clipping tests and the
earlier reports are the preceding slices' uncommitted work, not this task's.
