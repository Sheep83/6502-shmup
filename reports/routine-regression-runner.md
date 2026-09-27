# Routine regression runner

**Date:** 2026-09-27 · **HEAD:** `9d1c6dd` *Test Suite Cleanup*
**Nothing committed. Nothing pushed.** No production source was changed by this task.

---

## 1. What exists now

```
make smoke                      # routine regression, ~90 seconds
python3 tests/run_smoke.py      # the same thing without a build
```

```
BOOT: PASS   reached ATTRACT in 15s, frame 5646
CAMPAIGN LOOP: PASS
  ATTRACT -> PLAYING      ok (entered and ran on to gsState 3 before the first sample)
  PLAYING -> LEVELDONE    ok  (the upgrade shop)
  CONTINUE advances       ok  cmpLevel 0 -> 1
  level 2 package loaded  ok  noSpawnRow 725 -> 352
  level 2 -> PLAYING      ok
  PLAYING -> GAME OVER    ok  gsState 2
  returns to the front    ok  gsState 3

Frames observed: 4157
  gameOverrun          0
  scrollLate           0
  edgeLate             0
  statOverflow         0
  statPageMismatch     0
  statPtrMismatch      0
  objDoubleFree        0
  objAllocFail         0
  clipPoolFull         0
  publishSkip          0   (permitted: rare in-play miss, budget 5 per 3000 frames)
  schedBuildDefer      0   (a bounded cost, not a fault)
  statLate             0
ENGINE HEALTH: PASS

ROUTINE REGRESSION: PASS
```

## 2. Files

| file | status |
|---|---|
| `tests/run_smoke.py` | **new** — the routine runner |
| `docs/TESTING.md` | **new** — the policy and the exact commands |
| `Makefile` | `smoke` target added |
| `tests/harness.py` | `run_until_state()` added; `run_frames`/`run_until` documented as **gameplay-only** |

**No test was deleted, gutted or repaired.** All **33** certification suites are present and invokable. The other modified files in `git status` are carried forward from the previous phase-2 task, untouched here.

## 3. Commands

| purpose | command | cost |
|---|---|---|
| **routine** | `make smoke` | **~90 s** |
| certification, cheap tier | `make test-fast` | 12 bounded suites |
| certification, curated | `make test` | 13 suites |
| certification, everything | `make test-full` | all 33 |
| certification, unbounded | `make test-soak` | 8 suites, 25 s–2226 s each |

## 4. What the runner verifies

**Boot** — builds, launches, reaches ATTRACT within a bounded deterministic wait, does not hang.

**Campaign loop** — the structural contract only: the front screen can start a run; level completion reaches the shop; CONTINUE advances the campaign; **the next level's package actually loads**; play resumes; death returns through GAME OVER to the front.

**Engine health** — twelve counters over an uninterrupted ~4,100-frame window of real level-2 play.

It deliberately does **not** check waves, movement programs, Dropper choreography, token behaviour, art or feel. Five minutes of play establishes those better, and `docs/TESTING.md` says so.

## 5. How the campaign transitions are driven

| transition | how | why |
|---|---|---|
| ATTRACT → PLAYING | real input: fire press **and release** | the attract gate opens on the release |
| PLAYING → LEVELDONE | `call(gsEnterLevelDone)` | a plain state entry, no load, no cadence dependency — inside `call()`'s documented contract. Reaching it by play means killing a boss: minutes of emulated time and a content dependency |
| CONTINUE → level 2 | **real input through the shop loop**: cursor onto the CONTINUE row, then a fire press **and release** | `gsUpgradeContinue` does a genuine disk load and hands the display back to the executor. See §8 — calling it directly was unreliable |
| PLAYING → GAME OVER | `call(gsEnterGameOver)` | a state entry |

**Level 2 residency is proved by data, not a flag:** the boss-approach row is authored per level and read from the package at `$f530` — `725` for level 1, `352` for level 2. A change there means a different package is genuinely in RAM.

## 6. Health counters

**Fatal if non-zero** — each means a frame was *mishandled*, not merely costed:
`gameOverrun`, `scrollLate`, `edgeLate`, `statOverflow`, `statPageMismatch`,
`statPtrMismatch`, `objDoubleFree`, `objAllocFail`, `clipPoolFull`.

**Reported, not asserted:** `publishSkip`, `schedBuildDefer` (a documented bounded cost that "cannot starve"), `statLate`.

### publishSkip policy and rationale

Always reported with the frames observed. **Fails only above 5 per ~3,000-frame window.**

The rare in-play miss is known, understood and permitted: a main-thread pass straddling raster 250 drops one scroll update, recovers by itself and costs about a pixel, at roughly **one event per 10,000–60,000 frames** (`reports/publish-skip-in-engine-capture.md`). At that rate a window this size expects well under one event, so **1 is unremarkable** and 5 would mean the rare thing had become common. The threshold is deliberately coarse; no false precision is claimed, and a non-zero value is **not** grounds for an investigation.

**I did not have to relax anything else to make this pass.** An early run showed `gameOverrun = 1` and I left the strict-zero invariant alone pending evidence — which was right: it turned out to be a consequence of my own bug parking the machine inside `gsWaitFireRelease` while the health window ran. With that fixed it reads 0, and the nine fatal counters stand as written.

## 7. Runs

| run | result | wall |
|---|---|---|
| clean build + smoke (first) | **PASS** | 94 s |
| smoke again, no rebuild | **PASS** | 90 s |

Consistent, and comfortably inside the routine-development target. Earlier development runs measured 75–151 s including a build.

**The campaign checks demonstrably execute** — each prints its own evidence (`cmpLevel 0 -> 1`, `noSpawnRow 725 -> 352`, `gsState 2`, `gsState 3`), and they were observed *failing* honestly during development before the driving was fixed, which is the better proof that they are real.

## 8. Three instrument errors during development, and what they taught

All three looked like engine faults and were mine. Recorded because the runner's shape is a direct consequence.

| attempt | symptom | cause |
|---|---|---|
| `call(gsUpgradeContinue)` | passed once, then **froze the frame counter** | `call()`'s docstring says it is only for self-contained routines; this one does a disk load and hands back the display. A hang in a smoke test is worse than no smoke test |
| `run_frames`/`run_until` in the shop | the FIRE press was silently swallowed; a later wait hung | those arm a breakpoint on `gameFrame`, which **does not execute while `gsNonGame` is set**. In ATTRACT, the shop, GAME OVER or INITIALS they advance nothing. Fixed by adding `run_until_state()` and documenting the limitation |
| fire pressed, never released | CONTINUE "did not work" — `cmpLevel 0 -> 0` | `gsUpgradeContinue` opens with `jsr gsWaitFireRelease`, deliberately, so one press cannot both buy and leave. The probe showed `gsUpgPrev` had recorded the press while `gsState` stayed on the shop |
| a six-press retry loop | `ATTRACT -> PLAYING` failed **every** run while every later step passed | 0.3 s polling is ~600 warp frames; PLAYING began and ended between samples, and each extra press landed in GAME OVER. Fixed with a ~0.03 s poll and granting lives the instant PLAYING is seen |

The engine was correct every time. The pattern — an instrument producing a confident wrong answer about the engine — is the one `AGENTS.md` rule 4 exists for.

## 9. When to run full certification

Documented in `docs/TESTING.md`: before a release; after **multiplexer** changes; after **scroller or raster** changes; after **renderer scheduling or capacity** changes; after **clipping or object-pool** changes; or when deliberately investigating engine capacity.

**Not** after ordinary sprite art, animation, level content, sound, presentation or balance work. That doc also records that the full suite is slow and partly red **on purpose**, with the failures catalogued, and says plainly: *a red certification suite is not a licence to start fixing tests instead of making the game.*

## 10. Hygiene

One VICE per run, launched and reaped by **exact PID** through the existing harness — `[vice] launched pid N` / `[vice] reaped pid N` in every run above, and `close()` in a `finally` so it happens on success, failure and exception alike. **No `pkill`, no `killall`**, no user session touched, `-console` so nothing takes focus. `tools/run_tier.sh` launches nothing and kills nothing. `pgrep -x x64sc` empty after every run. No per-run files: the runner writes nothing to disk.

`build/` 404 KB, session scratch 1.4 MB.

## 11. Status

**Nothing committed. Nothing pushed.** HEAD remains `9d1c6dd`.

```
 M Makefile                        <- `make smoke`
 M tests/harness.py                <- run_until_state(), documentation
?? docs/TESTING.md                 <- the policy
?? tests/run_smoke.py              <- the runner
?? tools/run_tier.sh               <- (previous task)
?? reports/*.md                    <- (previous tasks + this one)
 M src/scroll.asm                  <- the ACCEPTED publishSkip fix, carried forward
 M tests/test_*.py (7 files)       <- phase-2 repairs, carried forward
```

**No production engine change was made or needed by this task.**
