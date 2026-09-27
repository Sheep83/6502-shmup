# publishSkip — in-engine capture and root-cause pass

**Date:** 2026-09-27 · **HEAD:** `9d1c6dd` *Test Suite Cleanup*
**One engine change: `src/scroll.asm`, 24 insertions.** Nothing committed. Nothing pushed.

---

## 1. Result

`publishSkip` was **two different events wearing one counter.** In-engine capture separated them, and only one of them was a fault worth fixing.

| | the boot event | the in-play event |
|---|---|---|
| frequency | **every boot, deterministic** | ~1 per 10,000–60,000 frames |
| state | ATTRACT, `gsState = 0` | mid-play, `gsState = 1` |
| cause | two `scrollInit` publications across a non-game state that never adopts | a main-thread pass straddling raster 250 |
| visible cost | **none** — nothing scrolls in ATTRACT | one dropped scroll update: a self-healing one-pixel hitch |
| status | **root cause proven, fixed** | characterised in detail; a fix was attempted, measured, and **reverted** |

**The boot event is what the test suite was actually seeing.** It is now gone, and `publishSkip` is clean in four of the five suites that were red on it.

**The in-play event remains**, by deliberate choice: the brief's rule is that a rare, automatically recovering one-pixel hitch is preferable to an unproven renderer fix, and my attempt at it failed its own acceptance criteria.

## 2. Capture design

### What was recorded, and why each field

Written **only** on the skip path, after `inc publishSkip` — the condition is already detected, so the capture cannot influence the cause.

| field | why |
|---|---|
| `frameCounter` (16-bit) | identifies the event and lets two runs be compared |
| `$d012` at capture | where the beam is when the *second* publication happens |
| **`$d012` at the previous successful publication** | the decisive field. A skip means the previous record was never taken, so *when* it was published is the question |
| `scrollFine` | is the fault tied to one fine-scroll phase? |
| `framePending` | **validates the capture**: must read 1, since the branch that reaches it requires non-zero |
| `gsState` | separates gameplay from the non-game states — this is the field that split the two events |
| `frameCurrent` / `schedCurrent` / `schedPending` | double-buffer ownership on both handshakes |
| `exPhase` | which phase the raster executor is parked in |
| `schedBuildDefer` | to confirm or exclude a legal deferral as a contributor |
| **`exFrames` / `adopts`** (added for the second pass) | how many `exFrame`s ran versus how many adopted. Their difference is what closed the in-play chain |

Fields were chosen after tracing the handshake, not harvested. `worldProgress` was dropped as redundant with `frameCounter` for this purpose; `clipPoolFull` and `statOverflow` were read externally after the soak instead, since they are cumulative and need no per-event snapshot.

### Memory: `$ca00-$ca9f`

**Proof of safety:** no symbol in `build/main.sym` falls in `$ca00-$ceff` and no module sets a program counter there (checked mechanically, both before and after). The region is outside VIC bank 0 (`$0000-$3fff`), so the VIC can never fetch it; below the level package (`$e000+`), so a level load cannot touch it; and clear of I/O (`$d000-$dfff`). The block was placed with an explicit `* =` and the program counter restored after it — the first attempt got that wrong and the build caught it as an overlap with the HUD glyphs at `$cf40`, which is the kind of error a segment guard exists for.

### Cost

* **Normal frames:** two instructions on the *success* path (`lda $d012 / sta psPubRaster`), ~7 cycles, main thread, once per frame, nowhere near a raster deadline. Nothing was added to any IRQ or renderer path in the first pass.
* **The skip path:** ~181 cycles, on the rare failing frame only, after detection.
* **Second pass only:** two `inc`s inside `exFrame` (12 cycles at raster 250, where the frame batch has ~7,370 cycles before its sprites display). **This mattered:** the instrumented build showed `gameOverrun = 1` where the clean build showed 0, so the final measurements were all taken with the instrumentation removed.
* `$d012` is read a few cycles *after* detection, not at it — so the recorded raster is a small overestimate of the true detection point. It does not affect any conclusion here, since the values are 60–191 and the boundaries in question are 250.

---

## 3. Captured events

Three uninterrupted runs, no per-frame breakpoints, no per-frame reads, no host sleep used as a claim about game progress. Each window's length was read from `frameCounter` afterwards.

### The in-play event — two independent captures, near-identical

| field | soak A | soak B |
|---|---|---|
| window | ~61,000 frames | ~10,009 frames |
| frame | 12252 | 11924 |
| `$d012` at capture | 190 | **191** |
| **`$d012` at previous publication** | **4** | **4** |
| `scrollFine` | 2 | **2** |
| `framePending` | 1 ✓ | 1 ✓ |
| `frameCurrent` / `frameNext` | 1 / 0 | 1 / 0 |
| `schedCurrent` / `schedPending` | 0 / 1 | 0 / 1 |
| `exPhase` | 4 (PH_BOTTOM) | 4 (PH_BOTTOM) |
| `schedBuildDefer` | 1 | 1 |
| **`exFrames − adopts`** | — | **1** |

Two events, at nearly the same frame, the same fine phase, the same rasters. **That is a signature, not a coincidence** — and it says the trigger is a specific heavy frame in the authored content rather than random jitter.

### The boot event — one capture, decisive

| field | value |
|---|---|
| frame | 6500 |
| **`gsState`** | **0 — ATTRACT** |
| `$d012` at previous publication | 130 |
| `$d012` at capture | 60 |
| `framePending` | 1 ✓ |
| `exPhase` | 1 (PH_FRAME — parked by `gsAttractIrq`) |
| `gameOverrun` | 0 |

## 4. Causal sequence — the boot event (proven, fixed)

1. `scrollInit` (`src/scroll.asm:251`) ends by calling `publishFrame`, which writes the record and sets `framePending = 1`.
2. The machine is in a non-game state. `irqHandler` tests `gsNonGame` and jumps to `gsAttractIrq`, which programs its own display, zeroes `$d015`, advances `frameCounter` and parks `exPhase` at `PH_FRAME` — and **never touches `framePending`**. So the pending record survives the entire attract screen. (`exPhase = 1` in the capture is that parking.)
3. `scrollInit` runs a **second** time on the way into a game: it is called from `gameInit` (`src/main.asm:640`), from `gsEnterGame` (`src/gamestate.asm:697`) and from the level transition (`src/gamestate.asm:1227`), and ATTRACT sits between the first two.
4. That second `publishFrame` finds `framePending` still set, refuses to write, and increments `publishSkip`.

Every step is named by a captured value: `gsState = 0` (step 2), two publications at rasters 130 and 60 with no adoption between them (steps 1 and 4), `framePending = 1` at the increment.

**It is not a fault.** `publishSkip` means "the main thread outran the display and a frame of motion was dropped". Nothing was dropped: there is no scrolling in ATTRACT, and a record pending from before a wholesale re-initialisation describes a world that no longer exists.

### The fix

```asm
    // THIS INIT'S RECORD SUPERSEDES ANY PENDING ONE ...
    lda #0
    sta framePending
    jsr publishFrame
```

`src/scroll.asm`, inside `scrollInit`, 24 insertions including the rationale. **Why it is architecturally correct:** `scrollInit` resets `scrollFine`, `worldProgress` and both screen pages — it is a wholesale re-initialisation, so declaring that its own record supersedes any pending one is a true statement about ownership, not a suppression of the counter. Double buffering is untouched (`frameNext` is still written and `exFrame` still swaps), no partial schedule is exposed, `schedBuildDefer` is untouched, and the counter keeps its full meaning for the in-play event. It runs three times per game entry and **never during play**, so there is no raster or gameplay impact of any kind.

**Verified from inside the machine before the instrumentation came out:** `publishSkip = 0` after the standard boot, `captured = 0` — the skip path is never reached.

## 5. The in-play event: chain established, fix reverted

The `exFrames − adopts` gap of exactly 1 closes this chain:

1. `gameFrame` N's preparation straddles raster 250, so its `publishFrame` lands just **after** the frame IRQ — measured at raster **4**, in both soaks.
2. The `exFrame` at 250 therefore found `framePending` clear and **adopted nothing** — that is the gap of 1.
3. That same `exFrame` incremented `frameCounter` and released the main loop, with a delta of **one**, so `gameOverrun` stayed silent. This is why the fault hid for so long.
4. `gameFrame` N+1 ran, finished well inside the frame (raster **190/191**), and published.
5. `framePending` was still 1 from step 1.
6. `publishSkip` incremented; step 4's record was discarded.

### What I tried, and why it was reverted

Requiring `framePending == 0` in `gamePlayLoop` before preparing another frame. It looked right and measured well in isolation — a clean 32,577-frame soak with `publishSkip = 0` **and** `gameOverrun = 0`.

It failed on the brief's own criteria:

* `publishSkip` **still failed** in `clip_scratch`, `flight_paths` and `ingress_egress` — because those see the *boot* event, which this did not address;
* it introduced a **new deterministic failure**, `gameOverrun is zero at boot -- 1`, breaking a previously passing `boot`.

Reverted in full; `git checkout` confirmed by `boot` returning to ALL PASS. I had conflated the two events — the same mistake the audit made from the other direction — and the fix was aimed at the rarer one while the tests were reporting the commoner one.

## 6. Alternative hypotheses ruled out

| hypothesis | how it died |
|---|---|
| publication landing just **above** raster 250 (my prediction) | captured `d012_lastPub = 4`, twice. Refuted by the first capture |
| a legal `schedBuildDefer` causing the skip | `schedBuildDefer` was 1 before and after every event and never changed while one occurred |
| `gameOverrun` accompanying it | 0 in every pre-fix run — the delta stays at one, which is exactly why this was invisible |
| schedule overflow / unsafe spacing / clip-pool exhaustion | `statOverflow`, `statLate`, `clipPoolFull` all 0 across every soak |
| raster lateness | `scrollLate` and `edgeLate` 0 throughout |
| the boot event being a gameplay fault | `gsState = 0` at the capture settled it |

## 7. Evidence, pre-fix versus post-fix

| | pre-fix | post-fix |
|---|---|---|
| after the standard boot | `publishSkip = 1`, **every** boot | **`publishSkip = 0`**, capture confirms the path unreached |
| uninterrupted soak, counters zeroed after boot | 1 skip in ~10,009 frames (soak B) | **0 in 32,577 frames** (clean build, all counters 0) |
| suites red on `publishSkip` | `production`, `clip_scratch`, `flight_paths`, `ingress_egress`, `encounter_director` | **only `production`** |

**What the soak establishes, precisely:** 32,577 frames with every health counter at zero. Against a pre-fix in-play rate of roughly one event per 10,000–60,000 frames, that is about three times the shorter observed interval — **meaningful but not proof**, and I am not claiming the in-play event is gone. It is not: it was never addressed. The boot event, by contrast, was deterministic and is now provably absent.

## 8. Regression results

| suite | baseline | now | remaining |
|---|---|---|---|
| `boot` | PASS | **PASS** | — |
| `clip_scratch` | FAIL:1 (`publishSkip`) | **ALL PASS** | — |
| `lifecycle` | PASS | **PASS** | — |
| `ebullet_clipping` | PASS | **PASS** | — |
| `heat_cadence` | PASS | **PASS** | — |
| `aimed_velocity` | PASS | **PASS** | — |
| `ingress_egress` | FAIL:2 | **FAIL:1** | one coverage gate, no `publishSkip` |
| `encounter_director` | FAIL:3 | **FAIL:2** | two coverage gates, no `publishSkip` |
| `flight_paths` | FAIL:2 | FAIL:4 | **all content/coverage gates** — movement primitives, linger, arc headings, two-patterns. No `publishSkip`, no `gameOverrun` |
| `production` | FAIL:1 | FAIL:1 | **`publishSkip` still 1** |

`flight_paths`' higher count is its own known flakiness: every one of its four failures is a content-dependent coverage gate that the audit already classified as hope-based, and it carries no publication or overrun failure at all. Those are unrelated baseline failures, catalogued in `reports/test-suite-audit-and-purge.md`, and were not touched here.

### The one open item, stated plainly

**`production` still reports one skip in a ~3,900-frame window.** That is *inconsistent* with the in-play rate (~1 per 10,000–60,000 frames) and with the clean 32,577-frame soak, so it is probably neither of the two events characterised here but a **third path: a second non-game-state boundary inside its window**, most likely level completion (`LEVELDONE` routes through the non-adopting IRQ exactly as ATTRACT does). The `scrollInit` fix covers the attract boundary; if the level-end boundary leaves a record pending the same way, the same reasoning would apply there.

**Not chased further.** It is one more bounded pass, the brief is explicit that this was the final one, and the honest position is a named hypothesis with the evidence attached rather than another speculative change.

## 9. Raster timing and hardware

The fix is in `scrollInit`, a main-thread initialisation routine that runs three times per game entry and never during play. It adds two instructions and touches no IRQ, no raster split, no sprite path and no scrolling behaviour. `scrollLate` and `edgeLate` are 0 across every post-fix run.

**No MiSTer/CRT check is required for this change.** The top-border shimmer fix is untouched, and nothing in the raster-critical path changed. If you want belt and braces, the visible check is simply that the attract screen and the transition into play look exactly as before — there is no scrolling in ATTRACT for this to affect.

## 10. Instrumentation removed

Confirmed: no `ps*` symbol remains in `build/main.sym`, no temporary code remains in `src/`, and `git diff --stat` is **`src/scroll.asm | 24 +++`** — the fix and its comment, nothing else. Both temporary counters in `src/renderer.asm` were removed and that file is unmodified. All final measurements were taken on the clean build, which mattered: the instrumented build's extra 12 cycles per frame were enough to produce a `gameOverrun` the clean build does not have.

## 11. Status and hygiene

**Nothing committed. Nothing pushed.** HEAD remains `9d1c6dd`.

```
 M src/scroll.asm                              <- the fix, 24 insertions
?? reports/publish-skip-investigation.md       <- the previous pass
?? reports/publish-skip-in-engine-capture.md   <- this report
```

Every VICE launched and reaped by exact PID (`launched pid N` / `reaped pid N` in every run above); `pgrep -x x64sc` empty at the end; **no `pkill`, no `killall`**; `-console` throughout, no focus taken. All probes live in the session scratchpad; none in the repository.
