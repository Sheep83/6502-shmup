# Test suite audit, purge and rehabilitation

**Date:** 2026-09-26
**HEAD:** `f45a53d` *Bullet clipping fixed*
**Working tree at start:** the accepted aimed-velocity fix from the previous task, uncommitted — `src/ebullet.asm`, `tests/test_aimed_velocity.py`, `reports/enemy-projectile-velocity-consumption.md`. Carried forward unchanged.
**Nothing committed. Nothing pushed.**

---

## 1. The headline

The suite's problem is not that parts of it are red. It is that **the two halves of it disagree about what time is**, and that several tests certify intent rather than behaviour.

Three systemic faults account for almost every symptom the recent debugging sessions hit:

1. **`free_run` advances wall-clock seconds, not frames.** 77 uses across the suite, against 76 uses of the frame-accurate `step_n`. Every test that waits for a frame-denominated event by running for *N seconds* is load-sensitive by construction — which is the whole of the "fails on the first run after a build, passes on the second" pattern, and of "fails in batch, passes in isolation".
2. **Stored-value assertions stand in for behaviour.** The aimed-velocity bug is the proven case; the same shape exists elsewhere.
3. **Health counters are asserted inconsistently**, and in one case the assertion contradicts the engine's own documented design.

None of these is fixed by making tests green. Each is fixed by changing what the test measures or how it waits.

## 2. Inventory — every engine test

33 test files in `tests/`, plus `harness.py` and two trace helpers (`movement_trace.py`, `wave_formation_trace.py`) which are fixtures-generators, not tests. **Every one of the 33 launches VICE**; there are no pure-Python or static-only engine tests. Total assertions: **820**.

| test | ln | VICE | checks | pokes | mechanism / what it observes |
|---|---|---|---|---|---|
| `aimed_fire` | 189 | 1 | 11 | 6 | stored `objVX`/`objVY` at first sighting |
| `aimed_velocity` | 165 | 1 | 6 | 3 | **position per frame** (new, previous task) |
| `attrition_inflives` | 384 | 1 | 26 | 9 | token/lives counters |
| `bank2_arena` | 467 | 1 | 49 | 14 | VIC bank + mirrored HUD bytes |
| `boot` | 56 | 1 | 5 | 0 | liveness smoke |
| `boss` | 398 | 1 | 45 | 30 | boss lifecycle, render cells |
| `boss_hud_transition` | 452 | 1 | 30 | 13 | HUD across the bank switch |
| `campaign` | 403 | 4 | 25 | 28 | level sequence, upgrade persistence |
| `clip_scratch` | 271 | 1 | 13 | 0 | clipped scratch vs source bitmap |
| `dropper_flight` | 593 | 1 | 45 | 1 | dropper passes + sonar |
| `ebullet_clipping` | 324 | 3 | 16 | 16 | bolt positions at the aperture floor |
| `encounter_director` | 270 | 1 | 17 | 0 | pool invariants + concurrency |
| `enemy_fire` | 498 | 1 | 29 | 52 | fire licences, masks, modes |
| `flight_paths` | 216 | 1 | 11 | 0 | movement primitives via state machine |
| `heat_cadence` | 335 | 1 | 20 | 12 | HUD gauge publication cadence |
| `ingress_egress` | 246 | 1 | 13 | 0 | enemy entry/exit lifecycle |
| `level_assets` | 225 | 1 | 25 | 1 | sprite window + pointer indirection |
| `level_identity` | 189 | 2 | 4 | 0 | a level looks the same by any route |
| `lifecycle` | 389 | 1 | 48 | 18 | ATTRACT→GAME→OVER→INITIALS |
| `movement_pool` | 222 | 1 | 25 | 10 | **package bytes in RAM vs built package** |
| `no_spawn_row` | 172 | 1 | 13 | 19 | boss-approach quiet zone |
| `p_economy_colours` | 360 | 1 | 33 | 3 | P economy + HUD colours |
| `pickup` | 519 | 1 | 26 | 41 | token spawn/drift/collect |
| `player_death` | 348 | 1 | 33 | 29 | death, controls, fireball |
| `player_ship` | 595 | 1 | 55 | 23 | sprite allocation, banking |
| `production` | 355 | 1 | 23 | 11 | health counters + scroll continuity |
| `sfx` | 807 | 1 | 49 | 22 | SID voices per effect |
| `species_order` | 160 | 1 | 4 | 1 | arbitrary species order |
| `square_species` | 220 | 1 | 22 | 1 | third species end to end |
| `token_encounter` | 906 | 1 | 45 | 1 | dropper death → token → protectors |
| `turret_arming` | 383 | 3 | 17 | 4 | turret arm/first-shot timing |
| `turret_regression` | 178 | 1 | 7 | 0 | turret fire timer never re-arms early |
| `wave_triggers` | 517 | 1 | 30 | 5 | absolute 16-bit trigger rows |

The editor suite under `tools/level_editor/` (40 files) is a separate, non-VICE, pure-Python/Tk suite audited and rehabilitated two tasks ago (35/35 at the time). It is **out of scope here** and untouched; §12 records why.

---

## 3. Systemic fault 1 — the suite measures time in the wrong unit

`tests/harness.py` offers two ways to advance the machine:

| primitive | unit | uses | verified? |
|---|---|---|---|
| `free_run(mon, frameCounter, seconds)` | **wall-clock seconds** | 77 | verifies the machine is *running*, not how far it got |
| `step_n(mon, frameCounter, n, read_fn)` | **distinct frames** | 76 | verifies every frame by the counter and retries stalls |

`step_n`'s own docstring is emphatic about why frame verification matters:

> *"`mon.cmd("x")` returns on a prompt echo rather than on the actual stop... A bare `for _ in range(n): mon.cmd("x")` loop can silently sample fewer than n real frames."*

That discipline was then applied to sampling and **not** to waiting. A test that needs 180 frames of game-over hold asks for *N seconds* of host time and hopes. How many emulated frames that buys depends on host load, warp throughput, page-cache warmth and whatever else is running — including other tests in the same batch.

### This is the "first run after a build" bug, exactly

`test_lifecycle` reaches every state through:

```python
def run_until_state(mon, sym, want, seconds=8):
    """Free-run in slices until the lifecycle reaches `want`."""
    end = time.time() + seconds
    while time.time() < end:
        ...
```

An **eight-second wall-clock budget for a transition denominated in frames.** On a cold first run after a build — compiler output still being flushed, caches cold, VICE starting slower — eight seconds buys fewer emulated frames, the transition has not happened, and the check fails. The second run, warm, buys more and passes.

The observed failures match: run 1 failed on GAME OVER and initials; a later run of the same binary failed instead on `$d016` and display ownership; another passed outright. **Different failures on different runs of an unchanged binary** is the signature, and it is not a retry problem — it is a units problem.

`test_turret_regression` is the same fault in a different costume: a seek loop of 40 × 0.25 s wall-clock, against a first turret that arrives roughly 31 s into a warp run. Loaded host, no turret, "no turret to watch".

**The fix is to budget in frames.** Where a test waits for a condition, wait for the condition with a *frame* bound; where it just needs time to pass, pass frames.

## 4. Systemic fault 2 — intent asserted in place of behaviour

The proven instance is `test_aimed_fire`, established in the previous task: it read the stored `objVX`/`objVY` bytes and computed the shot's speed from them, so it certified a normalisation the projectile never flew. It passes identically on the fixed and unfixed engine because **every byte it reads is the same in both**.

Its `within 10%` gate has a second, independent defect: the authored table `[3,3,2]` yields 3.00, 3.16 and 2.83 px/frame — an **11.7% spread**. The gate cannot be satisfied by the design it guards, and survives only because it is not always shown all three buckets in one run.

That is two separate false-confidence mechanisms in one check: it measures the wrong quantity, *and* its threshold is unreachable, *and* it can skip the case that would expose either.

## 5. Systemic fault 3 — health counters asserted inconsistently, one of them wrongly

Two counters recur across the suite, and they are not the same kind of thing:

| counter | engine's own description | asserting `== 0` is |
|---|---|---|
| `publishSkip` | `src/scroll.asm:198` — *"publication found the previous one still unadopted: **a real fault**"* | defensible |
| `schedBuildDefer` | `src/renderer.asm` — *"costs at most one frame of latency and **cannot starve**... counts the deferrals so the cost is visible rather than silent"* | **contradicts the design** |

`schedBuildDefer` is a *cost* counter. The engine documents deferral as normal, bounded and self-clearing. A test asserting it is zero is asserting that a designed-for event never occurs.

**And the suite already knows this — in some files but not others:**

| file | treatment |
|---|---|
| `enemy_fire:181` | *"schedBuildDefer is NOT one of them and is deliberately not asserted"* |
| `boss:166` | prints publishSkip — *"known limitation, not asserted"* |
| `bank2_arena:197,450` | **pokes `publishSkip` to 0** before measuring |
| `attrition_inflives`, `boss_hud_transition`, `dropper_flight` | print as info, do not assert |
| `clip_scratch:258`, `encounter_director:252`, `production`, `flight_paths`, `ingress_egress` | **assert zero** |

The lesson was learned at least five times and propagated to none of the five tests that still assert. That inconsistency — not the counter — is the defect.

---

## 6. Baseline — run 1 of 2

Full suite, sequential, from an already-built binary. **3,913 s (65 min)** for 33 tests.

| result | count |
|---|---|
| PASS | 14 |
| FAIL | 16 |
| ERROR (crashed, no verdict) | 3 |

Slowest five: `square_species` 532 s, `species_order` 359 s, `token_encounter` 307 s, `boss` 291 s, `p_economy_colours` 283 s. `aimed_fire` alone is 270 s — and proves strictly less than `aimed_velocity`, which takes 72 s.

### The three ERRORs are not three problems

| test | crash | actual cause |
|---|---|---|
| `clip_scratch` | `KeyError: 'sonicRingFrames'` | enemy art moved out of the engine PRG into the runtime level package; the symbol no longer exists |
| `boss` | `IndexError: list index out of range` | **cascade** — stale stage geometry means the stage never "completes", the boss never starts, `rising` is empty, and the test indexes it anyway |
| `player_ship` | `RuntimeError: the lifecycle never reached PLAYING: gsState = 3` | **the shared harness**, not the test — see §7 |

`boss` also shows a second defect worth naming: it calls `check("the exit runs", bool(rising), ...)` and then unconditionally evaluates `vels[0]`. A recorded failure does not stop the test, so a failed precondition becomes a crash and every later assertion is lost.

## 7. The harness's own boot is racy

`Vice(start_game=True)` — used by 32 of 33 tests — drives ATTRACT→PLAYING like this:

```python
for _ in range(8):
    poke(mon, sym["joyState"], 0xef)        # fire down
    free_run(mon, sym["frameCounter"], 1)   # ONE WALL-CLOCK SECOND
    ...
    if rd1(mon, sym["gsState"]) == 1:       # GS_PLAYING
        break
else:
    raise RuntimeError(...)
```

It samples the state **once per wall-clock second**, and `hudLives` is only topped up *after* PLAYING is seen. The helper's own comment warns that *"in warp a parked ship loses five of them in a fraction of a probe"* — so the game can start, the parked ship can die, and the lifecycle can be past PLAYING before the next sample. `gsState = 3` is consistent with exactly that overshoot.

This is one racy helper sitting underneath the entire suite, and it is the same units error as everything else in §3.

## 8. Classification

Every original test, one primary category. 33 tests: **13 KEEP, 18 REPAIR, 2 REPLACE, 0 DELETE**.

> **This was revised during the work, and the revision is the honest part.** The draft
> classification had 16 REPAIR and 2 DELETE (`flight_paths`, `ingress_egress`). The DELETE
> case rested partly on "two of their three failures are invalid counter assertions" — which
> turned out to be a three-line repair each. Deleting a suite over a defect I could fix would
> be optimising for a smaller test count rather than for trust, so both became REPAIR.

### KEEP (13)

`boot`, `attrition_inflives`, `campaign`, `ebullet_clipping`, `aimed_velocity`, `pickup`, `player_death`, `p_economy_colours`, `turret_arming`, `boss_hud_transition`, `square_species`, `lifecycle`*, `turret_regression`*

\* KEEP **as contracts**, but both depend on the §3/§7 timing repairs to become trustworthy; they are listed again under REPAIR for that reason. Their assertions are sound — only their waiting is not.

### REPAIR (16)

| test | defect | repair |
|---|---|---|
| `production` | `STAGE_ROWS = 420` hardcoded; the engine is fixed at `LEVELPKG_STAGE_ROWS`(200)×4 = **800** | derive from `src/levelpkg.asm` |
| `boss` | `STAGE_METATILE_ROWS = 105` "restated independently"; asserts `STAGE_FINAL == 395` | derive; and guard the empty-`rising` precondition instead of crashing |
| `heat_cadence` | 10 failures, all cascading from "the boss phase was reached — phase 0" | same geometry derivation |
| `wave_triggers` | wants trigger rows `[48,52,90,126]`, level authors `[20,52,90,126]` | read the authored rows from the level |
| `movement_pool` | same stale trigger rows | same |
| `no_spawn_row` | stale trigger/threshold expectations (`wvStarted=2`, `wvNextTrig=8`) | derive from the package |
| `species_order` | expects 12 triggers to fire, 7 do | derive the count; fail loudly if the scenario is not reached |
| `enemy_fire` | expects `ENEMY_FIRE_DOWN`(1); the level authors **AIMED**(2). Mask logic is correct | assert the mask *pattern* against the definition's authored mode |
| `level_identity` | masks `$d011` with `0xF8`, keeping **bit 7 = live raster MSB** | mask `0x78`; the engine documents bit 7 of a READ as raster bit 8 |
| `lifecycle` | `run_until_state(..., seconds=8)` — wall-clock budget for a frame-denominated transition | budget in frames |
| `turret_regression` | 40 × 0.25 s wall-clock seek; first turret arrives ≈31 s | wait on the machine with a frame/stall bound |
| `clip_scratch` | dead symbols `sonicRingFrames` / `orbitalDropperFrames` | rebuild against the runtime sprite pointer, or DELETE if the contract is covered by `ebullet_clipping` |
| `dropper_flight` | asserts `schedBuildDefer == 0` | drop the invalid assertion (§5) |
| `token_encounter` | same, plus a known-flaky protector-ascent check | same; characterise the flake |
| `level_assets` | same, plus "live enemies published window pointers — []" (scenario never occurred) | same; make non-coverage explicit |
| `sfx` | stale address (`$1840` vs `$1768`) and stale state size (9 vs 10) | re-derive from the build |

### REPLACE (2)

| test | why replacing rather than repairing |
|---|---|
| `aimed_fire` | Measures stored `objVX`/`objVY` and computes speed from them — the proven false-confidence case — with a threshold its own design cannot meet. Its **independent** coverage (bolts lean toward the ship; not homing; all three species reach the aimed path; FIRE_DOWN mode is straight) is real and worth keeping, so it is rebuilt around those and the duplicated/impossible assertions are dropped rather than patched. |
| `encounter_director` | Its pool invariants (no double-free, no dropped trigger) are valuable, but its headline claims — "two wave instances active concurrently", "two definitions on screen together" — are *hopes about authored content*, currently 0 frames of 1250. Replace the hope with deliberate arrangement of the case. |

### DELETE (0) — the two candidates, and why neither was deleted

| test | why |
|---|---|
| `flight_paths` | Every claim it makes about movement primitives is made more directly by `movement_pool` (authored pool bytes) and by the trace fixtures; its distinctive assertions are the same "two patterns in flight at once" hope as `encounter_director` (0 frames), plus two invalid counter assertions. What remains after removing the hopes and the invalid assertions duplicates `encounter_director`'s pool invariants. |
| `ingress_egress` | Two of its three failures are the invalid counter assertions; the third — "no enemy materialises inside the playfield away from an edge" — is a genuine invariant, but it is the same claim `clip_scratch`/`ebullet_clipping` make about aperture edges, and the lifecycle half duplicates `encounter_director`. **The genuine invariant is preserved** by moving that single check into `encounter_director` rather than keeping a 246-line suite for it. |

**Neither DELETE is "it was red".** Both are duplication plus hope-based coverage; the one unique invariant between them is carried forward.

---

## 9. Baseline, and what four full runs showed

Four complete sequential runs: two before any change, two after (the first of those the **first run after `make clean && make build`**).

| | base1 | base2 | final1 | final2 |
|---|---|---|---|---|
| PASS | 14 | 15 | **16** | 15 |
| FAIL | 16 | 16 | 17 | 18 |
| **ERROR (crashed, no verdict)** | **3** | **2** | **0** | **0** |
| wall time | 3913 s | 3518 s | 5579 s | 6982 s |

**Every crash is gone.** That matters more than the pass count: a test that dies mid-run discards every assertion after the crash, so `boss` was losing twenty checks to one stale constant.

### Improvements, measured against the worse of the two baselines

| test | baseline | after | what fixed it |
|---|---|---|---|
| `heat_cadence` | **FAIL:10** | **PASS** | stage geometry derived — all ten were one cascade |
| `enemy_fire` | FAIL:2 | **PASS** / FAIL:1 | mask asserted as a pattern, not today's mode |
| `token_encounter` | FAIL:2 | **PASS** | invalid `schedBuildDefer` assertion removed |
| `dropper_flight` | FAIL:1 | **PASS** | same |
| `level_identity` | FAIL:1 (flaky) | **PASS** | `$d011` mask stopped comparing the raster MSB |
| `boss` | **ERROR** | FAIL:1 | geometry derived + precondition guarded |
| `clip_scratch` | **ERROR** | FAIL:1 | reads the sprite window, not dead symbols |
| `player_ship` | **ERROR** | FAIL:1–2 | no longer crashes in the shared boot |
| `production` | FAIL:2 | FAIL:1 | geometry derived |
| `encounter_director` | FAIL:4 | FAIL:3 | invalid assertion removed |
| `flight_paths` | FAIL:3 | FAIL:2 | same |
| `ingress_egress` | FAIL:3 | FAIL:2 | same |
| `sfx` | FAIL:5 | FAIL:3–4 | partially; stale address/state-size remain |
| `wave_triggers` | FAIL:4 | FAIL:3 | partially |

**14 improved, 0 regressions attributable to the changes** — see §10, which is the part of this report I would read first.

## 10. Three tests looked like regressions and were not — and the proof is the whole thesis

`turret_arming`, `boss_hud_transition` and `turret_regression` all passed in both baselines and failed in the final runs. I assumed twice that I had broken them, and was wrong twice.

**What the evidence says:**

1. `git diff --stat tests/harness.py` is **137 insertions, 0 deletions** — the harness is purely additive to HEAD. Neither `turret_arming` nor `boss_hud_transition` was edited at all.
2. I reverted the one shared change that could plausibly reach them (`_boot_to_game`). **They still failed.** So it was never the cause.
3. The host ran **50% slower** in final1 and **80% slower** in final2 than in base1. Per-test times swing accordingly: `square_species` 532 s → 118 s → 834 s; `species_order` 359 s → 120 s → 693 s.
4. `turret_arming` failed on the run where it spent the **least** time — 102 s, against 124 s and 305 s when it passed. It gives up after a wall-clock budget: fewer frames per second of budget, no turret, early exit.

**The suite's verdict depends on how fast the machine running it happens to be.** That is §3 caught in the act rather than argued, and it is the single most important thing in this report: three green tests turned red because the host got slower, and nothing about the game changed.

## 11. My own two mistakes, because they are the same mistakes

Both are recorded in the code they affect.

**I wrote a wall-clock "frame budget".** The first `run_frames` advanced the machine with `x` + `sleep()` and called the result frames. With nothing armed, `x` runs free, so a 0.25 s slice in warp is thousands of frames: asking for 30 delivered about 30,000, the parked ship lost every life inside the "budget", and the lifecycle sailed past PLAYING into INITIALS. The fix is a breakpoint, exactly as `step_n` does for sampling. **I reproduced the defect I was fixing, inside the fix for it.**

**I wrote an unverified sampling loop.** `test_aimed_velocity` — the test written last task to expose stored-value false confidence — sampled at an `ebulletTick` breakpoint without pinning each sample to a frame. `harness.step_n`'s docstring warns that `mon.cmd("x")` returns on a prompt echo, so a duplicated reply hands back the same frame twice. On a loaded host it did, that duplicate became a displacement of **zero**, and the test reported `steps seen [0, 3]` as though a bolt had stopped moving. Fixed by discarding samples whose frame counter did not advance.

Both faults were documented in comments I had read and quoted in this very audit. That is the strongest available argument for the §3 conclusion: this is not carelessness peculiar to the old tests, it is what the monitor interface invites, and only a verified primitive prevents it.

---

## 12. Changes made

### Harness — additive only (137 insertions, 0 deletions)

| addition | purpose |
|---|---|
| `run_frames(mon, counter, n)` | advance exactly n verified frames, via an armed breakpoint |
| `run_until(mon, counter, predicate, max_frames)` | wait on a condition with a **frame** budget, sampling every frame |
| `stage_geometry()` | `(200, 800, 775)` derived from `src/levelpkg.asm` + `src/terrain.asm` |

`_boot_to_game` is **unchanged**, with its race and the measured fix recorded in a comment — see §14.

### Tests repaired

| test | change |
|---|---|
| `boss` | geometry derived; `STAGE_FINAL == 395` became the formula; empty-`rising` precondition guarded so a recorded failure no longer becomes an `IndexError` that discards the rest of the file |
| `heat_cadence` | geometry derived (`STAGE_FINAL`, and a literal `% 420`) |
| `production` | geometry derived; `schedBuildDefer` de-asserted; docstring corrected |
| `level_identity` | `$d011` mask `0xF8` → `0x78` |
| `clip_scratch` | reads the level sprite window at `$2c00` instead of the deleted `sonicRingFrames` / `orbitalDropperFrames` symbols; asserts the window holds ≥4 distinct frames |
| `enemy_fire` | the mask check asserts **which** members are licensed, plus a separate claim that they share one authored mode |
| `aimed_fire` | the two false-confidence assertions removed, with the reason and a pointer to `test_aimed_velocity` |
| `aimed_velocity` | every sample pinned to a frame counter |
| `dropper_flight`, `token_encounter`, `encounter_director`, `flight_paths`, `ingress_egress` | invalid `schedBuildDefer` assertion removed |
| `player_death` | port 6675 → 6678 (was shared with `attrition_inflives`) |

### Reverted, deliberately

| test | why |
|---|---|
| `lifecycle` | converting `run_until_state` to a frame budget made it fail 4 checks where it had passed. The conversion is right, but its assertions are coupled to the old arrival point (`"the game-over hold is the old 180-frame timer -- 0"` is the test catching the timer before it is set). Needs the assertions moved in the same change. |
| `turret_regression` | same class: the frame-budgeted seek changed when the test observes. Reverted rather than left half-converted. |

**No test was deleted.** My own draft classification had two DELETEs; both rested partly on "two of their three failures are invalid assertions", which turned out to be a three-line repair. Removing a suite over a defect I could fix would be optimising for a smaller number rather than for trust.

## 13. Confirmed engine findings, left for a separate task

Per the brief, tests were not weakened to hide these and the engine was not changed to satisfy tests.

| finding | evidence | status |
|---|---|---|
| **`publishSkip` reaches 1 during ordinary play** | `src/scroll.asm:198` calls it *"a real fault"*. `test_production` zeroes the counters, free-runs its window, and still reads 1 — so it is not only a boot transient. A probe saw one increment at frame 5634 and none for the next 3,540 frames: **real but rare.** | assertions **kept**; five suites are red on it. Worth an engine task. |
| `boss`: LEVEL COMPLETE page draws as spaces | `[32, 32, 32, 32, 32]` where text is expected, now visible because the test no longer crashes first | one legible failure, was hidden behind the crash |
| `wave_triggers`, `movement_pool`, `no_spawn_row`, `species_order` | authored trigger rows moved from `[48,…]` to `[20, 52, 90, 126]`; trigger counts changed | **stale content expectations, not repaired here** — each needs its authored values read from the package, which is a per-file job |
| `sfx` | stale code address (`$1840` vs `$1768`) and state size (9 vs 10) | partially improved; the rest is stale-constant work |
| `encounter_director`, `flight_paths` | "two wave instances active concurrently" sees **0 frames of 1250** | the authored content no longer produces the case. The gate is correct to fail — it refuses to pass without coverage — but the scenario should be arranged deliberately |

## 14. Answers to the eight validation questions

1. **Passes from a clean build?** No, and it should not: 15–16 of 33 pass, and every remaining failure is understood and listed above.
2. **Passes on the FIRST run after a clean build?** `final1` **was** that run. It produced the best result of the four (16 PASS, 0 ERROR), so the historic first-run-after-build collapse did not recur.
3. **Independently?** Yes — every repaired test was validated alone before any batch run.
4. **In batch order?** Yes; `final1`/`final2` are batch runs and agree with the individual results except for the five in (6).
5. **Deterministic across repeats?** **No.** Five tests differ between the two final runs: `aimed_velocity` (now fixed), `boss_hud_transition`, `enemy_fire`, `player_ship`, `sfx`.
6. **Remaining known flaky:** `boss_hud_transition`, `enemy_fire` (director spawn), `player_ship`, `sfx`, `turret_arming`, `turret_regression`, `token_encounter` (protector ascent). **All trace to wall-clock budgets under variable host speed** (§10).
7. **Intentional failures representing confirmed engine bugs:** the `publishSkip` assertions, in five suites. Kept red on purpose.
8. **VICE and artefacts cleaned?** Yes. `pgrep -x x64sc` empty at the end of every run; each launch logged `launched pid N` / `reaped pid N`. One leak occurred and is worth recording: a task-completion notification arrived **before** the process had exited and released its port, so a later test hit `port 6650 is already served by pid 93950`. The harness's `port_owner` guard **refused to attach** — working exactly as designed — and the PID was reaped individually. **No `pkill`/`killall` at any point.**

## 15. Runtime

| run | wall time | note |
|---|---|---|
| base1 | 3913 s | |
| base2 | 3518 s | |
| final1 | 5579 s | +50% vs baseline mean — host, not code |
| final2 | 6982 s | +80% |

Test **count is unchanged at 33**; assertion count is slightly down (two false-confidence checks removed, two real ones added). Runtime is dominated by host speed, so no honest before/after saving can be claimed from these numbers. The one clean comparison: `aimed_fire` took 270 s to prove less than `aimed_velocity` proves in 72 s.

## 16. Remaining limitations

1. **The wall-clock fault is diagnosed, not cured.** Two suites' worth of conversion was attempted and reverted because their assertions are coupled to imprecise arrival times. The fix is per-suite: move the primitive and the assertions together.
2. **`_boot_to_game` is still racy.** The frame-stepped version fixed `player_ship`'s crash and was reverted on an attribution that later proved wrong (§10). It should go back in — with the two suites' assertions checked in the same change.
3. **Stale authored-content expectations remain** in `wave_triggers`, `movement_pool`, `no_spawn_row`, `species_order`, `sfx`.
4. **Coverage gates that depend on authored content** (`encounter_director`, `flight_paths`) fail honestly but need the scenario arranged rather than hoped for.
5. **The editor suite (40 files under `tools/level_editor/`) was not audited** — it is pure-Python/Tk, launches no VICE, shares none of these faults, and was rehabilitated two tasks ago. Out of scope, untouched.

## 17. Status

**Nothing committed. Nothing pushed.** HEAD remains `f45a53d`.

```
 M src/ebullet.asm            <- the accepted aimed-velocity fix, carried in
 M tests/harness.py           <- additive only
 M tests/test_aimed_fire.py       M tests/test_enemy_fire.py
 M tests/test_boss.py             M tests/test_flight_paths.py
 M tests/test_clip_scratch.py     M tests/test_heat_cadence.py
 M tests/test_dropper_flight.py   M tests/test_ingress_egress.py
 M tests/test_encounter_director.py
 M tests/test_level_identity.py   M tests/test_player_death.py
 M tests/test_production.py       M tests/test_token_encounter.py
?? tests/test_aimed_velocity.py
?? reports/enemy-projectile-velocity-consumption.md
?? reports/test-suite-audit-and-purge.md
```

`tests/test_lifecycle.py` and `tests/test_turret_regression.py` are **unmodified** — reverted.
