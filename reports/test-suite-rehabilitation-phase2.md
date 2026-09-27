# Test suite rehabilitation, phase 2

**Date:** 2026-09-27 · **HEAD:** `9d1c6dd` *Test Suite Cleanup*
**Nothing committed. Nothing pushed.**

---

## 1. The finding that reframes phase 1

Phase 1 said the suite confuses host wall-clock time with C64 game time. That was right, and incomplete. Phase 2 measured the same suites four times and found the other half of it:

> **Eight of thirty-three suites vary between 5× and 69× in runtime from run to run — and they are exactly the suites that wait for content-dependent events.**

| suite | fastest | slowest | spread |
|---|---|---|---|
| `token_encounter` | 25 s | **1728 s** | **69×** |
| `dropper_flight` | 36 s | **2226 s** | **62×** |
| `ingress_egress` | 31 s | 801 s | 26× |
| `encounter_director` | 25 s | 351 s | 14× |
| `flight_paths` | 29 s | 214 s | 7× |
| `square_species` | 118 s | 834 s | 7× |
| `production` | 44 s | 282 s | 6× |
| `species_order` | 120 s | 693 s | 6× |

The other 25 suites are steady: `no_spawn_row` 17–20 s, `heat_cadence` 17–25 s, `lifecycle` 73–81 s, `aimed_velocity` 69–90 s.

**Runtime variance and flakiness are the same defect.** A test that waits for the dropper encounter, or for two wave patterns to coincide, or for every movement primitive to appear, is unbounded in *both* time and verdict: when the event arrives early it is fast and green, and when it does not it either grinds for twenty minutes or fails "0 frames". Phase 1 saw this from the verdict side. This is the cost side of the identical problem.

That has a practical consequence I got wrong first time round, described in §6: **you cannot tier a suite like this on median runtime**, because a median hides a 69× tail.

## 2. Refreshed inventory and classification

33 suites, all VICE-launching, 820 assertions. `make test` ran **13 of 33** — an implicit, undocumented tier.

| classification | count | which |
|---|---|---|
| **KEEP** | 12 | `boot`, `aimed_velocity`, `heat_cadence`, `lifecycle`, `pickup`, `player_death`, `movement_pool`*, `no_spawn_row`*, `clip_scratch`, `boss_hud_transition`, `ebullet_clipping`, `player_ship`* |
| **REPAIRED NOW** | 7 | `production`, `no_spawn_row`, `ebullet_clipping`, `flight_paths`, `player_ship`, `clip_scratch`, `level_assets` |
| **RE-TIERED (SLOW-EXHAUSTIVE)** | 8 | the unbounded eight in §1 |
| **DELETE** | 0 | — nothing earned deletion; see phase 1, where two candidates turned out to be three-line repairs |

\* KEEP as contracts, with repairs applied or still outstanding as noted.

## 3. Deterministic game-time control

One shared mechanism, and the important part is that it is **three** mechanisms with the difference written down where it cannot be missed (`tests/harness.py`):

| primitive | unit | perturbs timing? | use for |
|---|---|---|---|
| `free_run(seconds)` | **host time** | no | letting the game breathe. **Never** assert on a window it sized |
| `run_frames(n)` / `step_n(n)` | **game frames, verified** | **yes** | sampling what the engine computed |
| `soak_frames(n)` | **game frames, measured** | minimally | judging whether the engine *kept up* |

> **If the test asks what the engine computed, step it. If it asks whether the engine kept up, soak it.**

That distinction is not pedantry, it is the `publishSkip` lesson: stepping at `gameFrame` every frame resets the phase relationship between the main thread and the raster IRQ, and was measured to **mask** the rare publication miss entirely — 4,500 stepped frames found nothing where a single 7,631-frame uninterrupted window found one. So the phase-1 instinct to replace every `free_run` with a frame-stepped loop is wrong for any window whose subject *is* timing.

`soak_frames` also needed correcting twice, which is worth recording: the first version guaranteed only a *minimum* and overshot 1,800 frames to **7,778**, making the bounded invariant it existed to support meaningless. It now calibrates — one short slice measures frames per host second, each following slice targets 80% of what remains — and lands within roughly 2× while keeping monitor contact in single figures.

## 4. New shared helpers

| helper | what it removes |
|---|---|
| `soak_frames()` | wall-clock windows in timing-sensitive tests |
| `check_all()` | assertions that pass on an empty collection — fails with "NO cases WERE EXERCISED" |
| `check_exercised()` | coverage stated as its own claim rather than implied |
| `level_const(name, level)` | authored constants copied into tests |
| `stage_geometry()` | (phase 1) five stale copies of the stage height |

---

## 5. Changes made

| file | change |
|---|---|
| `tests/harness.py` | `soak_frames()` (calibrated, bounded), `check_all()`, `check_exercised()`, `level_const()`, and the three-way time distinction documented |
| `tests/test_production.py` | health window **measured in frames** instead of 10 wall-clock seconds; `publishSkip` converted from a blanket zero to a **rate invariant** over the measured window |
| `tests/test_no_spawn_row.py` | `NO_SPAWN = 340` → `level_const("STAGE_NO_SPAWN_ROW")`. The level had been re-authored to **725**; the test failed seven checks about an engine behaving correctly |
| `tests/test_ebullet_clipping.py` | three `all()` assertions over **filtered** subsets converted to `check_all()` — the parent collection was gated, the subsets were not |
| `tests/test_player_ship.py`, `test_clip_scratch.py`, `test_flight_paths.py`, `test_level_assets.py` | `publishSkip` removed from blanket zero-assertions |
| `tests/test_flight_paths.py` | the two possible meanings of each failure — *content never produced the case* vs *the primitive misbehaved* — stated in the file |
| `Makefile` + `tools/run_tier.sh` | four documented tiers and a runner that does not abort on the first failure |

### Wall-clock assumptions removed

`publishSkip` was asserted zero over an unmeasured window in **five** suites. It now has exactly **one** owner — `test_production` — where the window is frame-measured and the claim is a rate. The other four report it as information. That is the brief's instruction followed literally: *keep focused zero invariants where genuinely required*, and nowhere else.

### False-confidence assertions

68 `all(...)` assertions exist inside `check()`. **33 have no non-emptiness gate**; excluding those over `range(...)` (never empty), ~25 are genuinely reachable-empty. Three were converted in `ebullet_clipping` and validated. The remaining ~22 are inventoried below rather than bulk-edited — bulk edits broke two files earlier in this rehabilitation, and an unvalidated mechanical sweep across 13 files is a worse risk than a documented list:

`player_death` (burning, dying, inner, ptrs), `movement_pool` (PROG_AT, cols, offs), `p_economy_colours` (after, ptrs, samples), `token_encounter` (boot, enemies), `bank2_arena` (boss_ptrs, ptr2), `level_assets` (got, slots), `lifecycle` (rows), `player_ship` (gaps, slots), `production` (counts, ys), `sfx` (tail), `square_species` (frames, square_row), `turret_arming` (gaps).

## 6. Tiers — and the correction to how they were chosen

**I first tiered on median runtime and it failed.** `dropper_flight` (median 37 s, max 2226 s) and `flight_paths` went into the fast tier, and the "7-minute" tier measured **27 minutes cold and 104 minutes warm**. A median cannot describe a distribution with a 69× tail.

Re-tiered on **worst case, and only for suites whose runtime does not swing**:

| tier | suites | worst-case budget | command |
|---|---|---|---|
| **fast** | 12 | 769 s | `make test-fast` |
| **integration** | 13 (bounded, slower) | 2603 s | `make test` |
| **soak** | 8 (**unbounded**) | 25 s – 2226 s each | `make test-soak` |
| **full** | 33 | — | `make test-full` |

The fast tier still touches every major contract: boot, package data, clipping, HUD publication, projectile velocity, firing, the player, pickups, lifecycle and the bank switch.

`tools/run_tier.sh` exists because `make` stops at the first failing recipe line: the first cold fast-tier run reported **one result out of twelve** before aborting, which is useless for the one job a fast tier has. The runner collects every verdict, prints per-suite timings, and fails at the end.

## 7. `_boot_to_game` audit

| finding | detail |
|---|---|
| **The race is real and documented, not fixed** | It samples `gsState` once per wall-clock second while `hudLives` is only topped up *after* PLAYING is seen, so in warp the game can start, the parked ship can lose every life, and the lifecycle can be in INITIALS by the next sample. A frame-stepped version was built and measured during the `publishSkip` work: it **fixed** the crash and **broke** two previously-passing suites whose assertions are coupled to the old sloppy arrival point. Reverted; the finding is in the code. |
| **`stageHold = 1`** | The helper makes the stage endless. **This resolves the phase-1 open question** — see §8. |
| **`hudLives = 250`** | A stock the test cannot exhaust, restoring a pre-lifecycle assumption deliberately. |

## 8. The remaining `production` publishSkip — resolved

The in-engine report hypothesised a second non-adopting boundary at LEVELDONE. **That hypothesis is dead, and the reason is in the harness:** `_boot_to_game` sets `stageHold = 1`, `src/scroll.asm`'s own switch that makes the stage endless. **No test using the standard boot can reach the end of the level at all**, so `production`'s window cannot cross that boundary.

What was left was therefore the deterministic boot-time skip — fixed by the accepted `scrollInit` change — or the known permitted rare in-play miss. With the window now measured, `production` passed with **0 skips in 4,123 frames**; before the repair the same window ran **7,778 frames** and caught one, which is exactly what a rate of one per 10,000–60,000 predicts.

**No renderer archaeology was needed, and none was done.** It was a test-window question, as the brief suspected.

## 9. Engine defects found (not fixed here)

| finding | evidence | judgement |
|---|---|---|
| `player_ship`: the muzzle-flash art uses bit pair 1 (`$d025`) | *"the flash art uses only transparent, HW1's own colour and the shared white -- never $d025 -- bit pairs present: [0, 1, 2, 3]"*, both runs | Either the art was changed or the assertion is stale. **A content question for the sprite phase**, which is next — flagged rather than guessed at |
| `no_spawn_row`: 3 checks still fail | `wvStarted=0, cursor=12` after the 340→725 repair | Stale expectations tied to authored trigger counts, not an engine fault |
| `movement_pool`: stale authored trigger rows | wants other rows, package says `[20, 52, 90, 126]` | Same class; needs the rows read from the package |
| `aimed_velocity`: the duplicate-sample artefact recurred | `steps seen [0, 3]` on one loaded cold run, passing otherwise | My frame-pin guard reduced but did not eliminate it. The monitor can still hand back a stale read under load |

---

## 10. Validation matrix

| # | what | result |
|---|---|---|
| 1 | clean build + fast tier, **first run** | 6 passed, 6 failed, 1226 s |
| 2 | fast tier again, **no rebuild** | 6 passed, 6 failed, 2001 s |
| 3 | full regression | **not run to completion** — see below |
| 4 | VICE-heavy suites individually | `production` ALL PASS, `ebullet_clipping` ALL PASS, validated singly as each repair landed |
| 5 | same suites in batch | agree with their individual results; the batch/isolation difference phase 1 found did **not** recur |
| 6 | repeated runs | the two fast-tier runs agree on **which** suites fail except `clip_scratch` (passed cold, failed warm) and `aimed_velocity` (failed cold, passed warm) |
| 7 | soak tier | **not run** — the eight members are the unbounded ones, 25 s–2226 s each; running them at the observed throughput would have taken hours with no new information |

### Cold versus warm

Cold and warm agree on the verdict for 10 of 12 fast-tier suites. Two differ, and both are known-flaky: `clip_scratch` (schedule-entry check) and `aimed_velocity` (the duplicate-sample artefact). **The historic "first run after a clean build behaves differently" pattern did not recur** — the cold run was, if anything, the faster of the two.

### An honest problem with every runtime figure here

The tier budgets come from four full-suite runs measured earlier in this session. Late in the session **every suite ran 5–12× slower than those measurements on an unloaded host** — `heat_cadence` 17–25 s became 118–236 s, with load average 1.68 across 10 CPUs and 64% memory free. Nothing in the tests or the build explains it; the most likely cause is sustained-load throttling of the emulator after many hours of continuous warp execution.

**So the absolute seconds in this report are only comparable within a measurement window.** What survives that caveat: the *relative* ordering, the *variance* finding in §1 (which is a property of the tests, not the host), and the tier structure. **The tier budgets should be re-measured on a rested machine** before anyone treats 769 s as a promise.

## 11. Remaining limitations

1. **The unbounded eight are isolated, not repaired.** Their waits still depend on authored content arriving. The repair is deliberate arrangement — poke a movement program, run it, observe the headings — which is real work against the `wm*` state machine and was **not** attempted. Lengthening windows until probability makes them green is explicitly worse and was refused.
2. **~22 reachable-empty `all()` assertions remain**, inventoried in §5.
3. **`_boot_to_game` is still racy.** The fix exists, was measured, and costs two other suites until their assertions are decoupled from arrival timing.
4. **Stale authored expectations remain** in `no_spawn_row` (3 checks) and `movement_pool` (trigger rows).
5. **The full suite was not run end to end in this phase**, for the throughput reason above. Phase 1 has four complete runs; this phase changed 8 test files and validated each individually plus two full fast-tier runs.
6. **`aimed_velocity` remains mildly load-sensitive.**

## 12. Process and hygiene

Every VICE launched and reaped by exact PID; `pgrep -x x64sc` empty after every run reported here; **no `pkill`, no `killall`**; `-console` throughout; `tools/run_tier.sh` launches nothing and kills nothing. All probes in the session scratchpad.

**One process error of mine, recorded:** I edited test files while the phase-2 baseline run was in flight, contaminating it — the same discipline I had flagged in phase 1. I stopped that run rather than present a mixed baseline as clean, and used phase 1's four complete runs as the "before" instead.

**Disk after the runs:** `build/` 404 KB, session scratch 1.3 MB. No accumulating artefacts.

## 13. Status

**Nothing committed. Nothing pushed.** HEAD remains `9d1c6dd`.

```
 M Makefile                      M tests/test_flight_paths.py
 M src/scroll.asm                M tests/test_level_assets.py
 M tests/harness.py              M tests/test_no_spawn_row.py
 M tests/test_clip_scratch.py    M tests/test_player_ship.py
 M tests/test_ebullet_clipping.py  M tests/test_production.py
?? tools/run_tier.sh
?? reports/publish-skip-investigation.md
?? reports/publish-skip-in-engine-capture.md
?? reports/test-suite-rehabilitation-phase2.md
```

`src/scroll.asm` is the **accepted** `publishSkip` fix from the previous task, carried forward unchanged. **No other production source was modified in this phase.**

## 14. Is the suite something we are willing to believe?

**More than before, and not yet fully.**

What you can believe now: the fast tier's twelve suites have bounded runtime and stated contracts; `publishSkip` has one honest owner instead of five dishonest ones; authored constants are read from the level rather than copied; a filtered-subset assertion can no longer pass on an empty set; and a tier run reports all twelve results instead of stopping at the first.

What you cannot yet believe: anything the unbounded eight say about *engine capability*, because they are really reporting what Level 1 did in an arbitrary window. They are honest — they fail loudly when the case does not arrive — but they are content observations wearing engine clothing, and §11.1 is the work that would change that.

The next phase is sprites and art. The `player_ship` muzzle-flash finding in §9 is waiting there already.
