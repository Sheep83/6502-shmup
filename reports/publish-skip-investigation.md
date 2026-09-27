# publishSkip — investigation

**Date:** 2026-09-27 · **HEAD:** `9d1c6dd` *Test Suite Cleanup* · working tree clean at start.
**No engine change was made. Nothing committed. Nothing pushed.**

---

## 1. Verdict first

`publishSkip` is a **real event, it is rare, and it occurs during ordinary gameplay** — measured at roughly **one per 12,000 frames**, about once every four minutes of play. Zero is the correct invariant and the assertions that test it should stay.

**But the mechanism is not proven, so nothing was changed.** The brief is explicit: *"Do not proceed to a fix until there is a discriminating reproduction or a sufficiently strong state trace explaining the fault."* I have a reproduction of the *event* and not of its *cause*, and the one instrument that could close that gap cannot be built from outside the machine — see §7.

**My own previous classification was wrong in its specifics and is corrected here.** `reports/test-suite-audit-and-purge.md` §13 said the counter "reaches 1 during ordinary play" and reasoned that because `test_production` zeroes it and still reads 1, it must recur during play. The direction was right; the inference was not. The observation is fully explained by the rate: `test_production`'s window is ~3,900 frames, so it expects about half an event — which is precisely why that test is intermittent rather than reliably red.

## 2. What publishSkip means, from source

The frame record is the set of things that decide what a displayed frame *is*: `$d011` (fine scroll), `$d018` (screen page and charset), and the pointer-table destination. It is double buffered.

| step | where | what happens |
|---|---|---|
| build + publish | `publishFrame`, `src/scroll.asm:517` (main thread, inside `gameFrame`) | writes the record into `frameNext`, then `framePending = 1` — *"the handover. One byte, atomic."* |
| adopt | `exFrame`, `src/renderer.asm:1280` (raster-250 IRQ) | if `framePending`: clear it and swap `frameCurrent` ↔ `frameNext` |
| the counter | `publishFrame`'s first test | if `framePending` is **still set** on entry, the record is *not written* and `publishSkip` is incremented (saturating at `$ff`) |

```asm
publishFrame:
    lda framePending
    beq !free+
    lda publishSkip                     // previous record not adopted yet
    cmp #$ff
    beq !skipped+
    inc publishSkip
!skipped:
    rts
```

### What a skip costs

**Not data loss, not stale rendering, and it recovers by itself.** The new record is simply never written, so the display continues to show the last adopted one while the main thread's own scroll counters have already moved on. The next publication writes the then-current state, so the handshake self-heals within one frame. The visible cost is one update of scroll motion dropped — a one-pixel hitch.

The engine says so itself, at `src/main.asm:1144`, where the round-robin HUD design is justified:

> *"Drawing every row every frame pushed the main thread's per-frame preparation past 74% of a PAL frame, at which point passes start straddling the frame boundary, publishFrame finds the previous record still unadopted, and the publication skip shows as a one-frame scroll stutter."*

So the intended meaning is **main-thread overrun**, and `src/scroll.asm:198` calls it *"a real fault"*. **Zero is the intended invariant in valid gameplay.** No source comment, report or history describes any legitimate condition that permits it.

### Why it should be structurally impossible

`gamePlayLoop` (`src/main.asm:679`) is frame-locked: it spins while `frameCounter == lastFrameSeen` and then calls `gameFrame` exactly once. `frameCounter` is incremented by `frameDiagnostics`, which is *"frame IRQ only"* and runs **after** the adoption at the top of `exFrame`. So the loop cannot be released until adoption has already happened, and the next `publishFrame` should always find `framePending` clear.

That reasoning is sound and the event still happens, which is exactly why this is worth a separate task rather than a guess.

---

## 3. Deterministic reproduction

No wall-clock waits are used as a proxy for game time anywhere below: every window's length is **read from `frameCounter`**, and the machine is advanced either by verified frame stepping (`run_frames`, breakpoint on `gameFrame`) or by an uninterrupted run whose elapsed frames are then measured.

### The measurements

```
  fresh boot:                                    publishSkip = 1   (at frame 7478)

  zeroed, then FRAME-STEPPED:
     300 frames  -> 0      world 152     overrun 0   defer 1
     600 frames  -> 0      world 227     overrun 0   defer 1
    1200 frames  -> 0      world 377     overrun 0   defer 1
    2400 frames  -> 0      world 677     overrun 0   defer 1

  zeroed, then UNINTERRUPTED:
    7631 frames  -> 1      overrun 0
    3721 frames  -> 0      overrun 0
    3719 frames  -> 0      overrun 0
```

### What that establishes

* **The event is real and occurs in ordinary gameplay** — world progress advanced normally throughout, `gameOverrun` stayed 0, and no state was poked except zeroing the counter itself.
* **The rate is roughly one per 12,000 frames.** Two events across ~24,000 frames of play (one during the ~7,400-frame boot, one in the 7,631-frame window). About once every four minutes.
* **Every earlier observation is now explained by the rate.** Boot ≈ 1 expected event; `test_production`'s ~3,900-frame window ≈ 0.5, hence intermittent; my 1,200 and 2,400-frame windows ≈ 0.1–0.2, hence clean and misleading.
* **`schedBuildDefer` held at 1 in every run, and is a different thing.** It is documented as a bounded cost that *"cannot starve"*; it never moved and is not implicated. The two must not be conflated, and the skip is not a consequence of a legal deferral in any run observed here.

### Breakpoint stepping MASKS the event — which is the key methodological finding

4,500 frames of frame-stepped play produced zero skips; a single 7,631-frame uninterrupted window produced one. Stepping halts the CPU at `gameFrame` every frame and so resets the phase relationship between the main thread and the raster IRQ on every frame. **The fault lives in that phase relationship, so any instrument that stops the machine each frame destroys the thing it is trying to observe.**

That rules out the external approach the brief asks for — per-frame generation/ownership traces read over the monitor — and is why §7 recommends in-engine instrumentation instead.

## 4. What is NOT established

Honestly and specifically: **how two publications come to fall between two adoptions.**

The structural argument in §2 says it cannot happen, and it does. The candidates, none of which I could confirm:

| candidate | status |
|---|---|
| main-thread pass straddling the frame boundary (the documented cause) | plausible and is what the engine's own comment describes — but `gameOverrun` was **0** in every run, so the pass never missed a whole frame |
| a non-game IRQ path advancing `frameCounter` without adopting (`gsAttractIrq`, `src/gamestate.asm:1350`) | real mechanism, and `framePending` is indeed left set through non-game states — but the measured event occurred in `gs = 1`, mid-play, with no transition nearby |
| a legal `schedBuildDefer` leading to a skip | **not supported** — `schedBuildDefer` was 1 before and after every window and never changed while a skip occurred |
| scroll-phase / badline / sprite-DMA coupling | not examined to a conclusion; the one captured event has no recorded fine phase or raster, because the external instruments that could have recorded it are the ones that mask the fault |

A fix chosen from that list would be a guess, and a guess in `publishFrame` or `exFrame` touches the raster-critical path that was hardware-accepted on MiSTer. **So no change was made.**

## 5. Instrumentation: four attempts, three wrong

Recorded because the failures are the substance of why this is not yet solved, and each produced numbers a root cause could have been written around.

| attempt | what it reported | why it was wrong |
|---|---|---|
| breakpoint on a **guessed** PC (`$44d0`, assumed to be `inc publishSkip`) | "caught the skip" with `framePending = 0` | the address was never verified; `framePending = 0` is impossible at that instruction, since the branch reaching it requires non-zero. A false catch. |
| watchpoint on `publishSkip` | four "hits", all with PCs inside `gsWaitFrame` | the `watch` command's reply was not checked. `gsWaitFrame` writes only `lastFrameSeen` (`$52d2`), not `publishSkip` (`$c56b`). With no live checkpoint, `x` ran free and the monitor halted wherever it landed — in ATTRACT, the three-instruction spin loop. **Nothing was being measured**, and it produced the (wrong) conclusion that the skip happens in ATTRACT. |
| breakpoint on `publishFrame` entry | 3 of 400 calls with `framePending` set, yet `publishSkip` never moved | internally contradictory: those three should have driven the counter to 4. Most likely the stop itself perturbs the handshake — the same masking §3 then demonstrated. |
| **zero the counter, advance measured frames, read back** | the numbers in §3 | plain memory reads and measured frame counts; no dependence on checkpoint semantics. This is the only one of the four whose output survived scrutiny. |

The pattern is the one this project's `AGENTS.md` rule 4 exists for. It also cost the first three conclusions of this investigation, each of which I stated before checking the instrument.

## 6. Raster safety and regressions

**No source file was modified**, so there is nothing to account for: the top-border raster fix, the projectile fixes and all timing-critical paths are untouched. `git diff` is empty.

No regression test was added. The brief asks for one that "reliably exercised the pre-fix `publishSkip`" — and §3 shows the reliable exerciser is an **uninterrupted ~7,600-frame window**, which is a soak, not a focused reproduction, and would be intermittent at that length (one of three windows caught it). Writing a test that fails about a third of the time would add a flaky red to a suite that has just been audited for exactly that. **The soak evidence is in §3 and the test is deferred to the fix.**

Counters across every window: `publishSkip` as tabulated, `gameOverrun` 0, `schedBuildDefer` 1 (unchanged, legitimate), `scrollLate` 0, `edgeLate` 0.

## 7. Recommended next step

**Instrument inside the engine, not over the monitor**, because §3 shows external stepping destroys the fault.

The smallest useful thing: in `publishFrame`, on the skip path only, record a few bytes into a small ring buffer — `frameCounter`, `$d012` at entry, `scrollFine`, `framePending`, and the phase the executor is in. That is a handful of cycles on a path that today does nothing but `inc` and `rts`, it runs only on the rare failing frame, and it would immediately say whether the skip lands at a particular raster, a particular fine phase, or after a particular event. A soak would then fill it in minutes.

With that trace the mechanism should fall out, and the fix can be chosen rather than guessed. **That is a separate, small task — and it is the honest next move rather than a speculative change to a hardware-accepted timing path.**

Also worth deciding deliberately: at roughly one dropped scroll update every four minutes, the *visible* cost is a single-pixel hitch that no one has reported seeing. That is a reason to fix it properly rather than urgently.

## 8. Test-suite context

The five suites that assert `publishSkip == 0` are **correct to do so** and were not weakened. They are intermittently red because the event is rare, not because the assertion is wrong — and `test_bank2_arena`'s practice of zeroing the counter before its own window is the right pattern for the others to follow once the fault is fixed.

Unrelated baseline failures were not touched and are catalogued in `reports/test-suite-audit-and-purge.md`.

## 9. Status

**No engine change. No test change. Nothing committed. Nothing pushed.** HEAD remains `9d1c6dd`.

```
working tree: clean apart from this report
?? reports/publish-skip-investigation.md
```

**Temporary instrumentation:** none was added to the engine, so none had to be removed — every probe lived in the session scratchpad and none is in the repository.

**Hygiene:** every VICE launched and reaped by exact PID (`launched pid N` / `reaped pid N` in each run above); `pgrep -x x64sc` empty at the end; **no `pkill`/`killall`**; `-console` throughout, no focus stolen. Frame-accurate advancement was used for every assertion; the one deliberately uninterrupted window measured its own length from `frameCounter` rather than assuming it from seconds.

**Manual checks for Brian:** none required — nothing changed. If you ever want to *see* this event, it is a single-frame, one-pixel vertical hitch in the scroll, about once every four minutes, and it is almost certainly below the threshold of noticing.
