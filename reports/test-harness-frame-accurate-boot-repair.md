# Test-harness repair after absolute wave triggers

**Date:** 2026-09-18
**HEAD:** `8f79574` — *Memory reshuffle to accomodate longer levels*
**Working tree at start:** the Wave Contract Stage 1 work (`src/waves.asm`
modified, plus its report and `tests/test_wave_triggers.py`).
**Outcome:** the boot overshoot is fixed at its cause, nine test files are
repaired, and the regression baseline is trustworthy again.
**Zero production-engine source changes. Nothing committed. Nothing pushed.**

---

## 1. Initial state

```
$ git log --oneline -1
8f79574 Memory reshuffle to accomodate longer levels

$ git status --porcelain
 M src/waves.asm
?? reports/wave-contract-stage1-absolute-trigger-rows.md
?? tests/test_wave_triggers.py
```

`src/waves.asm` was modified on arrival — that is the Stage 1 migration this
task follows, not an unexpected change, so the stop condition did not apply. It
was fingerprinted before any work began so that "untouched" could be proved
rather than asserted (§14).

---

## 2. Exact cause of the old boot overshoot

`Vice._boot_to_game` presses fire through the real input path, and carries each
press and each release with `free_run(mon, frameCounter, 1)`.

**`free_run` takes SECONDS OF WALL CLOCK, and the machine is in warp.** Worse,
its `mon.cmd("x")` waits for the monitor to say something; with no breakpoint
armed the machine says nothing at all, so the call blocks for its **full
four-second deadline** before the one-second sleep even begins. Each press or
release is therefore ~5 seconds of emulated play — roughly 550 coarse rows — and
the `gsState` check happens only *after* both. The game starts somewhere inside
one of those intervals and the remainder runs as ordinary gameplay.

Shortening the interval does not fix it: the overshoot merely becomes smaller
and stays nondeterministic, because the boot cannot see the moment the state
changed.

This was harmless while ordinary waves repeated every 126 rows for ever — any
arrival point had a wave along shortly. Since Stage 1 the four authored
encounters happen **once**, at coarse rows **48, 52, 90 and 126**, after which
the director is permanently exhausted, so "hundreds of rows in" now means "past
all the content".

---

## 3. Measured old helper return positions

Five repeats, reading the state the helper leaves behind:

```
 #  wall s  worldProg    gsState  stageHold  lvlPhase  wvNextTrig  wvStarted
 0    22.1        108    PLAYING          1     LEVEL           3          3
 1    18.2        110    PLAYING          1     LEVEL           3          3
 2    25.9        395    PLAYING          1      BOSS           4          4
 3    17.9        107    PLAYING          1     LEVEL           3          3
 4    18.2        107    PLAYING          1     LEVEL           3          3

worldProgress: min 107  max 395  spread 288
```

**Three of the four authored encounters are already consumed** on a typical
boot (`wvStarted = 3`), and one run in five had run the entire stage out and
arrived in the **boss phase**. A spread of 288 coarse rows is not a margin a
test can be written against.

---

## 4. The new helper: contract and implementation

`tests/harness.py` gains a `boot` argument:

```python
Vice(port, prg, warp=True, start_game=True, boot="fast" | "exact")
```

| mode | contract |
|---|---|
| **`"fast"`** | the historical boot, unchanged. Arrives some hundreds of coarse rows in. Correct for any test indifferent to world position |
| **`"exact"`** | arrives at `worldProgress` 0, so rows 48/52/90/126 are all still ahead. Same input path, same debounce, same post-conditions |

`_boot_to_game_exact` advances in **frames**, not seconds. The difficulty is
that the breakpoint must be hit every frame in **both** states:

```python
bp_attract = set_bp(mon, sym["gsAttractLoop"])   # once per frame while attracting
set_bp(mon, sym["gameFrame"])                    # once per frame while playing
```

**Breaking only on `mainLoop` does not work, and was measured failing.** The
router reaches `mainLoop` on a *state change*, not per frame, so `x` free-ran
and one boot arrived at PLAYING with `worldProgress` already 395 and the boss
phase up — the stage had begun, run out and ended inside the "frame-accurate"
loop. `gsAttractLoop` is the per-frame seam in attract (its first instruction is
`jsr gsWaitFrame`); `gameFrame` is the per-frame seam in play. Armed together,
every frame of the transition stops somewhere.

Post-conditions match the fast boot exactly (`hudLives = 250`,
`stageHold = 1`), and the result is **checked, not assumed**:

```python
if read16(mon, sym["worldProgressLo"]) > BOOT_EXACT_MAX_ROW:
    raise RuntimeError(...)          # BOOT_EXACT_MAX_ROW = 4
```

Overshoot is the failure this routine exists to prevent, so it raises rather
than handing back a machine quietly in the wrong place.

### Also moved into shared infrastructure

`pc_of(reply)` — the monitor-prompt parser — with both traps recorded beside it:

1. `mon.cmd("x")` returns on an idle socket as well as on a stop, so "the call
   returned" is not "the breakpoint fired";
2. the reply can carry a **stale** prompt from an earlier command, and
   `re.search` happily matches that one. Taking the **last** match is what makes
   the address the one this command stopped at — with `re.search` a trigger
   probe silently missed the first two firings of a four-trigger schedule and
   reported rows `[90, 126]` instead of `[48, 52, 90, 126]`.

---

## 5. Repeated deterministic-return measurements

Five repeats of the new helper, same instrumentation as §3:

```
 #  wall s  worldProg    gsState  stageHold  lvlPhase  wvNextTrig  wvStarted
 0    17.9          0    PLAYING          1     LEVEL           0          0
 1    18.4          0    PLAYING          1     LEVEL           0          0
 2    19.7          0    PLAYING          1     LEVEL           0          0
 3    18.4          0    PLAYING          1     LEVEL           0          0
 4    23.6          0    PLAYING          1     LEVEL           0          0

worldProgress: min 0  max 0  spread 0
```

**Spread zero across five boots**, cursor on trigger 0, nothing started, warp on,
stage held, lives stocked. All four authored encounters ahead.

---

## 6. `_boot_to_game` caller audit

Twenty-one callers used the default boot; `test_lifecycle` passes
`start_game=False` because it *is* the lifecycle. Every caller was audited
against one question: **does its observation window need live ordinary
enemies, or the beginning of the level?**

| test | needs early gameplay? | action | before → after |
|---|---|---|---|
| `test_production` | **yes** — pool cycling needs enemies | `boot="exact"` + sample reordered (§7) | 1 → **ALL PASS** |
| `test_encounter_director` | **yes** — every assertion needs a wave | `boot="exact"`, 2 s warp removed (§8) | 8 → **2** (noise) |
| `test_pickup` | no (stages its own token) | fast boot kept; stale symbols repaired (§9) | crash → **ALL PASS** |
| `test_clip_scratch` | **yes** — clipping needs enemies at the edges | `boot="exact"` | 4 → **2** (noise) |
| `test_attrition_inflives` | **yes** — needs a Dropper to destroy | `boot="exact"` | 1 → **ALL PASS** |
| `test_flight_paths` | **yes** — every movement primitive needs enemies | `boot="exact"` | 9 → **2** (noise) |
| `test_ingress_egress` | **yes** — needs enemies crossing the aperture | `boot="exact"` | 8 → **3** |
| `test_dropper_flight` | **yes** — needs a Dropper launch | `boot="exact"` | 2 → **1** (noise) |
| `test_enemy_fire` | partly — a post-abuse director check | director re-armed (§9.4) | 1 → **ALL PASS** |
| `test_token_encounter` | **yes** — needs a Dropper to reach the aperture | `boot="exact"` | 1 → **7** (unmasked, §11) |
| `test_wave_triggers` | **yes** | folded onto the shared helper (§12) | **ALL PASS** |
| `test_sfx` | **yes**, but a boot swap is not the fix | **tried and reverted** (§11) | 3 → 3 (unchanged) |
| `test_level_assets` | **yes**, but its window is 64 frames | **not migrated** (§11) | 3 → 3 (unchanged) |
| `test_boot` | no — boots and checks the counter advances | fast boot kept | ALL PASS |
| `test_lifecycle` | drives the lifecycle itself | untouched | ALL PASS |
| `test_boss` | no — wants the stage to **end** | fast boot kept | ALL PASS |
| `test_bank2_arena` | no — wants the boss arena | fast boot kept | ALL PASS |
| `test_boss_hud_transition` | no — wants the boss transition | fast boot kept | ALL PASS |
| `test_player_death` | no — player only | fast boot kept | ALL PASS |
| `test_player_ship` | no — player only | fast boot kept | ALL PASS |
| `test_p_economy_colours` | no — stages its own pickups | fast boot kept | ALL PASS |
| `test_turret_regression` | no — turrets, not waves | fast boot kept | ALL PASS |

**Nine files changed, twelve left on the fast boot deliberately.** Tests that
want the *end* of a level (`test_boss`, `test_bank2_arena`,
`test_boss_hud_transition`) would be actively harmed by starting at row 0, and
tests about the player or about static assets do not care where the world is.

---

## 7. `test_production` before and after

**Before:** 1 failure, deterministic across two runs —
`the pool actually cycled during ordinary play (not frozen at one population)`.

The cause was not the pool. The fast boot arrived at row ~107; the ten-second
health window that ran *before* the sample is a further ~700 coarse rows; so the
150-frame sample was taken deep in the quiet stretch where **no ordinary enemy
exists**. The population was frozen because there was genuinely nothing alive.

Corroborating evidence, and the reason this diagnosis is not a guess: on the
same runs `publishSkip` **stopped** failing. With no enemies the frame is
lighter and the scheduler never skips a publication. One cause, two symptoms,
moving in opposite directions.

**After:** `boot="exact"`, and the sample moved **ahead of** the health window:

```python
SAMPLE_FRAMES = 700       # 8 frames per coarse row -> rows 0..87
samples = frames(mon, bp, SAMPLE_FRAMES)      # contains rows 48 and 52 in full
... then the ten-second health window
```

`SAMPLE_FRAMES` is derived from the content, not tuned until it passed: 700
frames from row 0 spans rows 0–87 and therefore contains the first two authored
encounters entire — their spawns, their concurrent flight and their despawns.
No waiting, no warp, no staged scene.

**Result: ALL PASS, 48.7 s.**

---

## 8. `test_encounter_director` before and after

**Before:** 8 failures — its 2 long-standing counter failures plus **6
behavioural ones**, every one of which needs a wave to start inside the
sampling window:

```
an authored trigger started a wave during the run;
two wave instances were active concurrently for a real span;
enemies from two different wave definitions were on screen together;
at least one enemy progressed through several distinct phases of the curved
    primitive;
one enemy walked its authored path through several movement stages;
an enemy despawned and returned its pool slot
```

**After:** `boot="exact"` and the `free_run(..., 2)` removed — two seconds of
warp is ~220 coarse rows and would have put the world past row 126 before the
first sample. `MAX_FRAMES = 1250` is 156 coarse rows, so from row 0 the existing
budget covers all four encounters with room to spare, and the loop still stops
as soon as every behaviour has been witnessed.

**All six behavioural failures repaired**, back to the file's baseline of two:

```
ok  an authored trigger started a wave during the run
ok  two wave instances were active concurrently -- longest streak 34, 683 frames
ok  enemies from two different wave definitions were on screen together
ok  several distinct phases of the curved primitive -- best run 20 phases
ok  one enemy walked its authored path through several movement stages
ok  an enemy despawned and returned its pool slot
FAIL publishSkip is zero with the director running -- 11
FAIL schedBuildDefer is zero with the director running -- 1
```

---

## 9. `test_pickup`: stale-symbol diagnosis and replacement

This file has **crashed on import of a removed symbol since commit `d5566b0`**,
so none of its assertions had run for three commits. Fixing the crash exposed
three further stale premises. Each was replaced with the current contract, none
deleted, and each carries its history in the file.

### 9.1 The token column (the reported crash)

`KeyError: 'waveTrigTokenLo'`. A token used to be authored **content**: the
trigger list carried `waveTrigTokenLo/Hi` and two of the four appearances
brought a P at an authored X. `src/waves.asm` removed that deliberately — *"a
token is now a REWARD… No trigger creates one, and no P appears merely because a
wave started."*

The intent was never "there is a token column"; it was **"a P's appearance is
deterministic and authored, never a random drop"**. That intent is intact, so it
is asserted in current terms:

```
ok  no authored trigger creates a token any more -- a P is a reward, not a placement
ok  ...and the removed token columns are gone from the build
ok  a Dropper's death spawns exactly one token
ok  ...at EXACTLY the position the Dropper died at, not a fixed line -- (173, 118)
```

Driving `tokenDropperDied` with `pkSpawnXLo/Hi/Y` set is the real production
path with the *death* arranged and nothing else — the same shape the old section
used for `waveStartNext`. All four triggers are now exercised (both wave
instances are freed first, so none takes the early "dropped" path and skips
reading its own columns).

### 9.2 The descent rate

`the token descends exactly one pixel per frame -- the scroll's own speed` failed
at `[118, 119, 119, 120, ...]`. **This is not an engine regression**, and the
source says so beside the constant:

> *…APPLIED ON ONE FRAME IN TWO… the token is now the centre of an encounter
> that has to be watched, so it descends at half the scroll rate… The token no
> longer matches the scroll, and that is now correct.*

The replacement is **stricter**, not looser — it pins the cadence the mechanism
actually guarantees (`PICKUP_VY_MASK`, a frameCounter bit, no accumulator):

```
ok  the token descends one pixel every OTHER frame -- steps [0,1,0,1,0,1,0,1]
ok  ...on a strictly alternating cadence, not an irregular one
ok  ...so it covers exactly half the ground the scroll does -- 119 -> 123 over 8 frames
```

A token moving every frame, every third frame, or irregularly all fail here; the
old check accepted only one of those. The despawn test now runs two frames
rather than one, because from an arbitrary alignment the token needs up to two
frames to take its next step — it still despawns on the very step that crosses
`PICKUP_Y_MAX`.

### 9.3 The collection counter

`the ship overlapping a token collects it, once` failed at `pkTokensP 0->0`,
while the very next check confirmed the token had been removed and its slot
released. `pkTokensP` now counts **spendable units** and moves only on every
third pickup, with `pkCharge` holding the 0–2 partial. Replaced with the
economy's total, which is exactly what the old check meant and is stricter than
reading either byte:

```python
units * PICKUP_P_PER_UNIT + charge
```

A collection that bumped the charge without carrying, or carried without
clearing the charge, both fail.

### 9.4 "The director keeps running after all of that"

Failed at `started 8->8`. The question this asks is *"is the encounter director
still alive after the pool abuse"*, **not** *"does Level 1 still have content
left"* — and by that point the file has driven `waveStartNext` several times, so
the cursor is legitimately exhausted and no wave can start however healthy the
director is. One disposable trigger is placed two coarse rows ahead of the world
and the cursor wound back to it; everything then observed is the real production
path. `spawned 13->20, started 8->10`.

The identical check in `test_enemy_fire` had the identical cause and the
identical fix.

**`test_pickup`: ALL PASS.**

---

## 10. Full regression results

Every suite, on the repaired tree:

| suite | result |
|---|---|
| `test_boot` | **ALL PASS** |
| `test_production` | **ALL PASS** |
| `test_turret_regression` | **ALL PASS** |
| `test_lifecycle` | **ALL PASS** |
| `test_boss` | **ALL PASS** |
| `test_bank2_arena` | **ALL PASS** |
| `test_boss_hud_transition` | **ALL PASS** |
| `test_player_death` | **ALL PASS** |
| `test_player_ship` | **ALL PASS** |
| `test_p_economy_colours` | **ALL PASS** |
| `test_pickup` | **ALL PASS** |
| `test_attrition_inflives` | **ALL PASS** |
| `test_enemy_fire` | **ALL PASS** |
| `test_wave_triggers` | **ALL PASS** (×3 consecutive) |
| `test_encounter_director` | 2 — `publishSkip`, `schedBuildDefer` |
| `test_flight_paths` | 2 — `publishSkip`, `schedBuildDefer` |
| `test_clip_scratch` | 2 — `publishSkip`, `schedBuildDefer` |
| `test_dropper_flight` | 1 — `schedBuildDefer` |
| `test_ingress_egress` | 3 — 2 counters + 1 pre-existing (§11) |
| `test_sfx` | 3 — unchanged, not migrated (§11) |
| `test_level_assets` | 3 — unchanged, not migrated (§11) |
| `test_token_encounter` | 7 — unmasked pre-existing (§11) |
| `make test` (aggregate) | 2 ALL PASS + the director's 2 counters |

**Fourteen suites now pass completely.** Every remaining failure is either the
known monitor-sensitive counter noise or a pre-existing behavioural failure
identified below — none is a repaired-harness failure, and no assertion was
weakened anywhere.

---

## 11. Remaining known noise, and what was deliberately not repaired

### Monitor-sensitive counters

`publishSkip` and `schedBuildDefer` remain non-zero under heavy monitor
stepping, exactly as every report since the scroll-speed restoration records.
Untouched, unasserted where the files already say so, and never hidden.

### `test_token_encounter` — 1 → 7, and that is the truth surfacing

The migration **worked**: the original failure (`an authored Dropper reached the
aperture during the run`) is gone, because the test can now find a Dropper. It
then reaches the guard-orbit assertions it could never previously execute, and
seven fail:

```
a guard swept several quadrants about the token: it patrols rather than parks;
the patrol ring is as wide as the constants say;
...and never collapses onto the token;
the three guards stay spread around the token, not bunched;
the three guards are never all stationary together;
a killed guard was replaced;
schedBuildDefer is zero with the encounter run end to end
```

**These are exactly the seven recorded as this file's baseline in
`reports/boss-transition-hud-regression.md`**, measured at an older HEAD before
any of this work. They are long-standing and unrelated; the missing Dropper had
been masking them by making the test bail early. Reverting the migration would
hide them again, which is the wrong trade — a baseline that cannot reach its own
subject matter is worth less than one that reports honestly.

### `test_sfx` — migration attempted, measured, reverted

Its `deliver_a_kill` needs an enemy already alive, so it looked like the same
class. It is not: the kill happens far enough into the file that an exact boot
has long since drifted past the encounters. The migration did not repair the
KILL check **and added two counter failures**, so it was reverted — the file is
byte-identical to HEAD. Its three failures are unchanged: the hard-coded sfx
segment address, "sfx state is nine bytes" (it is ten, since the Dropper ping
added `sfxRefused`), and the KILL check. Repairing it needs a window change
inside the file, not a boot swap.

### `test_level_assets` — not migrated, and why

`live enemies published window pointers during real play` needs enemies, but the
check samples **64 frames** — eight coarse rows. From row 0 that is nowhere near
row 48, so `boot="exact"` alone cannot help; the file needs its sampling window
moved to the encounters. Out of scope for a boot repair, reported instead.

### `test_ingress_egress` — 1 residual behavioural failure

`no enemy materialises inside the playfield away from an edge`. The other five
behavioural failures were repaired by the migration. This one is listed with the
same two counters in `reports/boss-transition-hud-regression.md`'s baseline at an
older HEAD — pre-existing and unrelated.

### One check made against the engine, not assumed

`test_pickup`'s descent failure (§9.2) was the one result that could have been a
genuine engine regression. It was checked against `src/pickup.asm`, which
documents the change deliberately. **No stop condition was triggered**, and no
production behaviour was altered to make a test pass.

---

## 12. `test_wave_triggers`, and a harness performance lesson worth keeping

The Stage 1 file proved the frame-accurate technique; it now uses the shared
`boot="exact"` and the shared `pc_of`, with its local copies deleted.

Making it reliable took four measured iterations, and the last one is the
generally useful finding:

| symptom | cause | fix |
|---|---|---|
| first two firings missed, reported `[90, 126]` | `re.search` matched a **stale** prompt | take the **last** match |
| world jumped 126 → 603, putting row 255 out of reach | the collector kept polling after the cursor exhausted; one free-running `x` is ~470 rows | stop on the expected count |
| boundary rows missed; then a **45-minute hang** | waiting at a breakpoint hundreds of rows away; `cap=3000` × 4 s deadline is a cap of hours | approach first; hard wall-clock budget |
| **1 h 28 m** run | see below | see below |

**The machine must run during a `sleep`, not during the command.** Waiting
inside `mon.cmd("x")` for its deadline looks equivalent and is not: the read
that follows has to halt the emulator and resynchronise a socket that is
mid-reply, and `rd()`'s retries then burn wall time with the machine **stopped**.
Measured, that managed about six coarse rows per two seconds — so bad that
replacing frame stepping with it made the file *slower*. Resuming with a very
short deadline and then sleeping puts the wall time where the emulation is.

```
46 min  ->  1 h 28 m  ->  55.6 s      (ALL PASS, three consecutive runs)
```

This is the same shape `free_run` already uses, and it is why `free_run` is fast
and the naive alternative is not.

---

## 13. Runtime impact

| | before | after |
|---|---|---|
| **the boot itself** | 17.9–25.9 s | **17.9–23.6 s** |
| `test_production` | — | 48.7 s |
| `test_wave_triggers` | 46 min (worst 1 h 28 m) | **55.6 s** |
| `test_encounter_director` | always ran its full 1250-frame budget, because nothing was ever witnessed | 6 min 3 s, stopping early at 683 frames |

**The exact boot is not slower than the fast boot.** Almost all of a boot is the
fixed four-second VICE start plus the port-ownership check; the exact boot
replaces seconds of warp with a few dozen fast frame steps. The two modes are
kept as explicit concepts anyway, because the *semantic* difference — where in
the level you wake up — is real and worth stating at each call site even though
the cost is not.

---

## 14. Confirmation of zero production-engine source changes

`src/waves.asm` was hashed before any work began and again at the end:

```
before:  2c696fc2d6266913edbf6fab9a11059103e9a537807b716c3c8caf0df15e1e13
after:   2c696fc2d6266913edbf6fab9a11059103e9a537807b716c3c8caf0df15e1e13

$ git status --porcelain src/
 M src/waves.asm        <- the pre-existing Stage 1 work, byte-identical
```

**It is the only file under `src/` with any diff at all, and that diff is
unchanged from the state this task inherited.** No waves, scroller, renderer,
terrain, turret, level-package, movement, Dropper/P-token or boss source was
edited. The engine binary this task tested is the engine binary it was given.

---

## 15. Final git status and diff

```
$ git status --porcelain
 M src/waves.asm                       <- inherited Stage 1 work, untouched
 M tests/harness.py                    <- this task
 M tests/test_attrition_inflives.py    <- this task
 M tests/test_clip_scratch.py          <- this task
 M tests/test_dropper_flight.py        <- this task
 M tests/test_encounter_director.py    <- this task
 M tests/test_enemy_fire.py            <- this task
 M tests/test_flight_paths.py          <- this task
 M tests/test_ingress_egress.py        <- this task
 M tests/test_pickup.py                <- this task
 M tests/test_production.py            <- this task
 M tests/test_token_encounter.py       <- this task
?? reports/wave-contract-stage1-absolute-trigger-rows.md   <- preserved
?? tests/test_wave_triggers.py         <- Stage 1 file, folded onto the helper

$ git diff --stat
 src/waves.asm                    | 229 ++++++++++++++++++++++-------------
 tests/harness.py                 | 131 +++++++++++++++++++-
 tests/test_attrition_inflives.py |  12 +-
 tests/test_clip_scratch.py       |  12 +-
 tests/test_dropper_flight.py     |  12 +-
 tests/test_encounter_director.py |  20 +++-
 tests/test_enemy_fire.py         |  18 +++
 tests/test_flight_paths.py       |  12 +-
 tests/test_ingress_egress.py     |  12 +-
 tests/test_pickup.py             | 249 +++++++++++++++++++++++++++++++--------
 tests/test_production.py         |  47 ++++++--
 tests/test_token_encounter.py    |   8 +-
 12 files changed, 602 insertions(+), 160 deletions(-)
```

`tests/test_sfx.py` appears nowhere: its attempted migration was reverted and it
is byte-identical to HEAD.

---

## 16. Disk usage

```
$ du -sh build/    292K
$ du -sh .         8.2M
```

`build/` holds the current binary, symbols, the level package and the disk
image — no per-run directories. The boot-measurement and schedule probes were
written to disposable scratch outside the repository and deleted; `/tmp` carries
no residue.

---

## 17. VICE hygiene

Every automated instance was launched with `-console`, owned by exact PID and
reaped by the harness's `try/finally`. `pgrep -fl x64sc` confirmed a clean field
before each batch and none remaining after.

One intervention is worth recording. A `test_wave_triggers` run hung for
**45 minutes** (against a normal ~5); `ps -o etime` confirmed the stall rather
than assuming it, the background task was stopped by id, and the test-owned VICE
(PID 53609) was checked individually — the harness's `finally` had already
reaped it. **No broad `pkill`/`killall` was used at any point and no
user-launched VICE was touched.** That hang is what the wall-clock budget in
§12 now prevents.

No visible manual VICE run was required: the automated behaviour is trustworthy,
and this task changed no production behaviour for a human to check.

---

## 18. Confirmation

**Nothing was committed. Nothing was pushed.** No destructive reset was used, no
report was altered or removed, no unrelated cleanup was performed, and **no
assertion in any test was weakened** — the three replaced premises in
`test_pickup` are each strictly stricter than what they replaced, and every
migration changed *where a test looks*, never *what it demands*.

The stop condition was not reached: restoring these tests required no change to
production engine behaviour, and deterministic frame-accurate boot needed no
harness redesign — one shared helper, armed on the two per-frame seams that
already existed.
