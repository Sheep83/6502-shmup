# Top border / playfield raster shimmer

**Date:** 2026-09-26
**HEAD at start:** `8795c39` *Upgrade shop to level transition added.* — level with `origin/main`, 0 ahead / 0 behind, **working tree clean**.
**Nothing committed. Nothing pushed.**

---

## 1. What the join actually is

The artefact sits at raster **55**, but not for the reason the estimate suggested, and the distinction is the whole investigation.

There is **no border transition at line 55**. The vertical border is held open for the entire frame, so rasters 0..47 are VIC idle lines, 48..54 are real matrix lines rendered through a BLANK charset, and 55..247 are the playfield. All three are bit pair 00, which in multicolour text mode is `$d021` and nothing else. From `src/main.asm`:

> *"the open top and bottom border are exactly '$d021, whatever it is'. ... the playfield's background and the border's background are THE SAME BIT PAIR OF THE SAME REGISTER, and the only thing that can tell them apart is WHERE THE BEAM IS."*

So the top edge of the playfield is manufactured by exactly two register writes on line 55:

| write | from → to | deadline | why that cycle |
|---|---|---|---|
| `$d018` | blank charset → real charset | **cycle 15** | the line's first g-access |
| `$d021` | `BORDER_D021` (black) → `trnBgColour` | **cycle 17** | the first displayed pixel, x=24 |

Both are in `exTop` (`src/renderer.asm`). `TOP_SPLIT_LINE = 55` and `APERTURE_TOP_RASTER` derive from it; the bottom mirror is 248.

**A write that lands late is therefore directly visible as a horizontal run of the wrong thing** — blank glyphs and border-black — starting at the left edge of the playfield and ending wherever the write actually happened. That is the reported artefact, and its length is the lateness.

## 2. Why every existing counter said the split was fine

`edgeLate`, `topSplitMin`, `topSplitMax` and `topLanded` all compare `$d012` — the **raster line**. Every failing frame in this investigation landed on line 55 exactly as intended. The defect was entirely in the **cycle within the line**, which nothing in the engine measured.

`edgeLate` read **0** throughout, before and after the fix. It was never wrong; it was answering a different question. This is the `AGENTS.md` rule #4 case — a green instrument that is not lying, just not looking.

## 3. Instrument

VICE's monitor reports `LIN` and `CYC` with the register dump, so a watchpoint on the store gives the raster line and the cycle within it at the moment the write happens. Stopping *at* the store cannot change the cycle the store already occurred on, so each sample is valid even though continuing perturbs later frames.

Two calibrations, both necessary:

* **VICE reports the PC *after* the storing instruction** — `$88F7` for the `STX $D021` at `$88F4`. The write therefore happened in the immediately preceding cycle, so every number in this report is `CYC - 1`.
* **The two stores are exactly 4 cycles apart** in the measured data at every phase (`sta $d018` then `stx $d021`, 4 cycles each, write on the last). That is the independent check that `CYC` is a faithful per-write cycle and not an approximation.

With that correction the measurement reproduces the engine's own documented windows — `$d018` "writes in cycles 6..12", `$d021` "writes in cycles 10..16" — at phases 0..4, which is the strongest available evidence that the instrument and the source agree.

---

## 4. Root cause A — the shimmer: a badline inside the interrupt prologue

`exTop` is armed at `TOP_ARM_LINE` and opens with a raster poll. Getting from the interrupt to the poll's first `cpy $d012` costs about **100 cycles**, and none of it is negotiable:

| | cycles |
|---|---|
| interrupt latency (finish current instruction + 7-cycle sequence) | up to 14 |
| prologue `pha/txa/pha/tya/pha`, `sta $d019` | 19 |
| lifecycle test (`gsNonGame`) | ~6 |
| dispatch chain — `PH_TOP` is the fourth structural compare, each an absolute `jmp` | ~29 |
| YSCROLL-7 test | 14 |
| the three loads the stores need | ~17 |

That is already **a raster and a half**. Armed at 53, the budget to the start of line 55 is lines 53 and 54 — **126 cycles**.

**A badline stalls the CPU from cycle 12 to 54 of its line: 43 cycles.** Line 53 is a badline at YSCROLL=5 and line 54 is a badline at YSCROLL=6 (`raster & 7 == YSCROLL`). At those two phases the budget becomes 100 + 43 = **143 needed against 126 available**.

What overflows is the **poll**. Its first sample already reads 55, so the guard

```asm
    cpy $d012
    beq !split+                 // already there, or already past it?
    bcc !split+
```

takes the early exit and the two stores go out wherever the beam happens to be — and `topLanded` then reads 55, which is the target, so `edgeLate` stays at zero.

The existing rationale for `TOP_ARM_LINE = 53` asked the wrong question:

> *"exactly one of lines 48..55 is a badline, and at YSCROLL=5 (the only phase where line 53 is one) the target is 55, two lines further on, which the poll reaches with the whole of line 54 in hand."*

It considered whether the **target** line is a badline. What decides this is whether a badline falls **between the arm and the target**, because the hundred-cycle prologue has to cross it. Line 54 — a badline at YSCROLL=6 — is not mentioned at all.

### Measured, at the store, before any change

```
                $d018 (deadline 15)        $d021 (deadline 17)
  YSCROLL 0-4    7, 8, 9, 11, 12  ok        10..16, one 16/17  ok
  YSCROLL 5     19, 21, 23, 24   LATE      23, 25, 26, 27, 28  LATE
  YSCROLL 6     20, 22, 23       LATE      24, 25, 26, 27, 29  LATE
```

Two phases in eight: **a 12.5 Hz shimmer**, about six characters wide, drawn from the blank charset and painted in the border's black. Both writes miss, which is why the artefact reads as a *line* rather than merely a colour change — the blank charset is also pair 00, so it too resolves to black.

## 5. Root cause B — the whole scanline: a 7-cycle poll against a 12-cycle window

At YSCROLL=7, line 55 is itself the frame's first badline. The engine already handles the charset for this case by splitting `$d018` on line 54, which is legal because lines 48..54 are idle at that phase and the VIC renders them from `$3fff` whatever the charset says.

**`$d021` cannot follow it there.** Idle lines are drawn in `$d021`, so moving the background store to 54 would paint line 54 in the playfield's colour at one phase in eight — the 6.25 Hz boundary pop the design explicitly refuses.

So `$d021` must be written on line 55, where the badline stalls the CPU from cycle 12. The window is **cycles 0..11 — twelve cycles**. The poll loop is

```asm
!wait55:
    cpy $d012        // 4
    bne !wait55-     // 3 taken
```

**seven cycles**, and seven is also its worst-case lateness: the sample that first reads 55 lands at cycle 0..6 and the store follows six cycles later (`bne` not taken 2, `stx abs` 4), at **6..12**.

**And the grid is phase-locked, so this is not an occasional coincidence.** A PAL line is 63 cycles and **63 = 9 × 7**, so a 7-cycle poll samples at exactly the same offset on every line it spins through. Which of the seven offsets a frame gets is fixed by interrupt latency; one of the seven always lands on cycle 12, is stalled to cycle 55, and paints **the whole of line 55** in the border's black.

Measured before the change: **22 of 86 phase-7 frames** stalled to cycle 55.

### It is not sprite DMA

The source attributed this hazard to HW0..HW2 sprite DMA in cycles 57..62 of the previous line. The measurement does not support that:

```
  LANDED (cycle < 17)          MISSED (cycle 55)
  0:220 2:55  3:87  4:130      0:220 2:100 3:101 4:122
  0:220 2:55  3:84             0:220 2:88  3:91  4:124
  0:220 2:55                   0:220 2:62  3:85  4:91
```

Frames that **landed** had a sprite at Y=55, at the very top of the aperture; frames that **missed** had nothing near the split. The correlation is absent in both directions. The cause is the poll's own granularity, not the bus.

---

## 6. The fix

Two changes, both in `src/renderer.asm`, both derived from the numbers above. No renderer or multiplexer restructuring.

### 6.1 `TOP_ARM_LINE` 53 → 52

One raster earlier, which buys back exactly what the badline takes.

```
  armed at 53:  budget lines 53..54 = 126 cycles   need 100 + 43 = 143   FAILS
  armed at 52:  budget lines 52..54 = 189 cycles   need 100 + 43 = 143   46 in hand
```

Exactly one of lines 52, 53, 54 can be the badline whatever YSCROLL is, so the 43 is paid once, never twice.

**The handoff's exit is not the obstacle it appeared to be.** 52 was previously rejected because the handoff exits as late as raster 51 and "the handoff is the phase most likely to grow". But an arm the beam has already passed is not dropped — `exLate` chases `PH_TOP` **by name**, precisely because a missed top split blanks the whole screen:

> *"THE TOP SPLIT IS DIFFERENT. ... Running it immediately instead costs at worst a few blank characters on line 55 ... and edgeLate records that it happened."*

So a handoff that ever exits at 52 or later runs `exTop` immediately, from three lines out, with **more** margin than the interrupt would have given it. The failure mode the two-raster gap protected against does not exist for this phase.

### 6.2 At YSCROLL=7, `$d021` is counted, not polled

A 7-cycle poll cannot hold a 12-cycle window — §5 is the proof, and it is arithmetic rather than tuning. So the beam is not asked where it is.

The poll for line 54 has just seen it at cycle `s`, and **`s` is bounded to 0..6 because the poll was already spinning** — which is what 6.1 now guarantees. From the end of the `$d018` store, a counted **56 cycles** lands the `$d021` write at `s + 62`:

```asm
    cpy $d012        // 4   still on 54? Y is 54
    bne exTop7Poll   // 2   the count has no anchor if the poll never spun
    lda $d012        // 4
    sta topLanded    // 4
    ldx trnBgColour  // 4
    ldy #5           // 2
!pad:
    dey              // 2 x5
    bne !pad-        // 3 taken x4 + 2  = 24
    nop              // 2
    nop              // 2
    nop              // 2
    nop              // 2
    stx $d021        // 4   write on the last cycle: s + 62
```

`4+2+4+4+4+2+24+8+4 = 56`. Verified against the assembled binary: the `bne` at `$8925` targets `$8924` with the next instruction at `$8927`, both in page `$89`, so the taken branch is 3 cycles and not 4.

**Both ends of the landing window are safe, which is what makes 56 a derived number rather than a tuned one:**

| `s` | write lands | what is there |
|---|---|---|
| 0 | line 54, cycle 62 | right border — the main border flip flop set at x=344 in cycle 56, so `$d021` is not displayed |
| 6 | line 55, cycle 5 | before the badline stall at 12 |

The safe window is 18 cycles wide (line 54 cycle 57 through line 55 cycle 11) against a 7-cycle spread — it absorbs the spread twice over. The only thing that can still steal cycles here is HW0..HW2 sprite DMA in cycles 58..62 of line 54, at most five cycles, which lands the write at cycle 10 of line 55 — still inside. Nothing else can: line 54 is never a badline at YSCROLL=7, and HW3..HW7 DMA would own cycles 0..9 of line 55 only for a sprite active *at* 55, which `MIN_SPRITE_Y = 55` refuses at admission.

**The fallback is kept.** If the poll never spun — the handler arrived inside line 54 or later — `s ∈ 0..6` does not hold and the count is anchored to nothing, so `exTop7Poll` polls as before and takes the 1-in-7. With the arm two lines early and `exLate` chasing this phase, reaching it means something upstream grew by a whole raster, and then the count is exactly the wrong thing to trust.

### Cost

43 extra cycles in the interrupt at YSCROLL=7 only — one frame in eight, about **5 cycles per frame averaged**, out of 19,656. No new memory. `gameOverrun` stayed at 0 across every run.

---

## 7. Measured result of the fix

Same instrument, same method, gameplay frames only, `gsNonGame` excluded. **779 samples.**

| phase | `$d018` (deadline 15) | `$d021` | verdict |
|---|---|---|---|
| 0 | 6..12 | 10..15 | ok |
| 1 | 6..12 | 10..15 | ok |
| 2 | 6..12 | 10..15 | ok |
| 3 | 6..12 | 10..15 | ok |
| 4 | 6..11 | 10..15 | ok |
| 5 | 6..12 | 10..14 | **was 19..24 / 23..28** |
| 6 | 6..12 | 10..14 | **was 20..23 / 24..29** |
| 7 | 6..12 on line 54 (idle) | line 54 c62 .. line 55 c5 | **was 1-in-7 whole line** |

`edgeLate = 0`, `scrollLate = 0`, `gameOverrun = 0`.

**Zero landings outside the safe window, all eight phases.** Phase 7's `$d018` also improved as a side effect of the arm change — it used to land at cycles 36..41 of line 54 and now lands at 6..12. That was never visible, because line 54 is idle at that phase, but it was the same lateness and it is gone for the same reason.

---

## 8. All eight YSCROLL phases, and the badline in each

`raster & 7 == YSCROLL` inside 48..247, so exactly one line in eight is a badline. What matters is which of them the prologue has to cross and whether the target itself is one.

| YSCROLL | badline in 52..55 | prologue crossed it? | target line | before | after |
|---|---|---|---|---|---|
| 0 | none of 52..55 (48 is) | no | 55 | ok | ok |
| 1 | none (49) | no | 55 | ok | ok |
| 2 | none (50) | no | 55 | ok | ok |
| 3 | none (51) | no | 55 | ok | ok |
| 4 | **52** | only with the new arm, and it is the arm line itself | 55 | ok | ok |
| 5 | **53** | **yes, armed at 53** | 55 | **LATE 23..28** | ok |
| 6 | **54** | **yes, at either arm** | 55 | **LATE 24..29** | ok |
| 7 | **55 — the target** | no | 54 then 55 | **whole line, 1 in 7** | ok |

Phase 4 is worth naming: moving the arm to 52 puts the badline *on the arm line*. That is harmless and is why the budget is computed as "one stall, paid once" — the interrupt is raised at cycle 0 of 52 and the stall from cycle 12 is inside the 189-cycle budget, not on top of it.

## 9. Sprite DMA

Sprite DMA is the one thing that can steal cycles from a non-badline line, and it is accounted for rather than assumed away:

* **HW3..HW7** own cycles 0..9 of a line, but only for a sprite *active on that line* — Y ≤ 54 for line 55. `MIN_SPRITE_Y = 55` refuses those at admission, and the rule is asserted against `PLAYER_MIN_Y` in the same file, so the player cannot take the room either.
* **HW0..HW2** are fetched in cycles 57..62 of the *previous* line. For line 55 that is the tail of line 54 — after the phase 0..6 stores (cycles 6..16) and inside the phase-7 counted path's 18-cycle window, where five stolen cycles land the write at cycle 10 of line 55, still before the stall at 12.

The measurement agrees: across the stress run the landing position is **invariant to both the number of sprites enabled and the presence of an HW0..HW2 sprite at the top of the aperture**. See §11.

## 10. VIC border timing used here

The numbers the deadlines rest on, and where each comes from:

| quantity | value | source |
|---|---|---|
| PAL line length | 63 cycles | 6569 |
| first g-access | cycle 15 | fixes the `$d018` deadline |
| left display edge x=24 | cycle 17 | fixes the `$d021` deadline |
| right display edge x=344 | cycle 56 | makes cycles 57..62 invisible, which the phase-7 count relies on |
| badline condition | `48 ≤ raster ≤ 247`, `raster & 7 == YSCROLL`, DEN=1 | |
| badline CPU stall | cycles 12..54 — 43 cycles | |
| vertical border compare, RSEL=0 | top 55, bottom 247 | why `TOP_SPLIT_LINE` is 55 and not an estimate |

The engine holds the vertical border open for the whole frame, so the RSEL comparison never closes it; the top edge is the `$d018`/`$d021` pair and nothing else.

---

## 11. Sprite DMA, measured rather than argued

Two runs, because the first one left a hole worth naming.

**Ordinary play, `boot=exact`, 895 samples.** Landing position is invariant to sprite count:

```
  1 sprite  n=833   positions [-1,1,2,3,4,5, 10..16]
  2 sprites n= 25   positions [0,3,4, 10..16]
  3 sprites n=  8   positions [4, 10,12,15,16]
  4 sprites n= 25   positions [1,2,3, 10..16]
  5 sprites n=  4   positions [10,11,16]
  UNSAFE LANDINGS: 0      edgeLate=0  gameOverrun=0  statOverflow=0
```

But it also reported `frames with an HW0..HW2 sprite fetched across the 54/55 boundary: none`. **That is exactly the case the phase-7 count depends on**, and ordinary play never produced it — so at that point the claim rested on arithmetic, not measurement.

**Forced worst case, 582 samples.** The player is HW0/HW1, so flying it to `PLAYER_MIN_Y = 55` puts its fetch in cycles 57..62 of line 54 — the only sprite DMA that can reach the split window. Driven by real input through the engine's own `joyHold`/`joyState` path, not by poking sprite registers, so admission and the renderer behave normally:

```
  player Y seen: [55]
  HW0..2 across the 54/55 boundary = True:  n=582   (every sample)
      phase 0: [10,11,13,15,16]      phase 4: [10,11,12,13,15]
      phase 1: [10,11,12,13,15,16]   phase 5: [10,11,12,13,14,16]
      phase 2: [10,11,12,13,15,16]   phase 6: [10,11,12,13,14,15,16]
      phase 3: [10,11,13,15,16]      phase 7: [-1,1,2,3,4,5]
  UNSAFE LANDINGS: 0      edgeLate=0  gameOverrun=0
```

Phase 7 is **unmoved** by the DMA — still −1..5. The five stolen cycles fall in the same stretch the counted write is already crossing, and the 18-cycle window absorbs them, which is what the count was sized for.

Observed loads peaked at **five concurrent sprites** and `statOverflow` stayed 0; that is what this level produces, and it is stated rather than described as "heavy".

---

## 12. Regression testing, and an honest account of the suite

### The change is one file

`git diff --stat` — `src/renderer.asm`, +143 / −24, and most of that is comment. The executable changes are a constant and the phase-7 store.

### A/B against the pristine renderer

Because so much of the suite was already red, "it still fails the same way" is only meaningful against a measured baseline. So the committed renderer was restored, rebuilt, and the failing set re-run, with the fixed file kept in scratch and restored by a shell trap.

| suite | pristine (arm 53) | fixed (arm 52) | verdict |
|---|---|---|---|
| `boot` | ALL PASS | ALL PASS | — |
| `player_death` | ALL PASS | ALL PASS | — |
| `production` | 1 | 1 | pre-existing |
| `wave_triggers` | 3 | 3 | pre-existing |
| `no_spawn_row` | 7 | 7 | pre-existing |
| `species_order` | 3 | 3 | pre-existing |
| `boss` | fails | fails | pre-existing |
| `heat_cadence` | 10 | 10 | pre-existing |
| `bank2_arena` | 2 | 2 | pre-existing |
| `ingress_egress` | 3 | 3 | pre-existing |
| `flight_paths` | 3 | 3 | pre-existing |
| `dropper_flight` | 1 | 1 | pre-existing |
| `token_encounter` | 2 | 1 | pre-existing, flaky (the protector-ascent check) |
| `lifecycle` | ALL PASS | 10, then **ALL PASS**, then a *different* 10 | **flaky, not a regression** |
| `turret_regression` | pass, pass, **fail** | fail, fail | **flaky at baseline too, not a regression** |

The last two were not taken on one run each. `lifecycle` was re-run on the fixed build and passed, then failed with an entirely different failure set (`$d016 = c8`, display ownership) from the first (GAME OVER, initials) — the signature of a non-deterministic test, not a broken feature. Its failures also sit in `gsNonGame` states, where `irqHandler` branches to `gsAttractIrq` before the phase dispatch and `exTop` never runs at all.

`turret_regression` was re-run **three times on the pristine build**: pass, pass, fail.

### Why `turret_regression` is flaky, specifically

Its seek loop gives the scroller forty quarter-second slices — ten seconds of warp — to bring a turret into the aperture. The level's highest turret is at logical row 345 of 800, measured at roughly 12,000 frames, about 31 s of warp. The window expires first whenever the host is loaded, and the test then reports "no turret to watch" as though the firing path were broken. **Left alone**: repairing it is unrelated work, and acceptance gate 9 forbids it here.

### The state of the suite is itself a finding

Thirteen of seventeen suites were already failing at `8795c39`, and two more are non-deterministic. `boss` asserts against `worldProgress 395` while `production` asserts against `775` — two different stage lengths, which places those expectations before the level-2 and campaign work now in HEAD.

**So "the suite is unchanged by this fix" is a weaker safety statement here than it sounds**, and it is reported as such rather than presented as a clean baseline. What actually guards this change is the cycle measurement in §7 and §11, not the suite.

---

## 13. MiSTer / CRT acceptance — the open gate

**The shimmer is not declared gone.** VICE and the cycle measurements prove where the writes land; they cannot prove what a CRT shows. `AGENTS.md` rule #2 is explicit that manual visual output is authoritative and that a passing harness is evidence, never a veto.

An interim VICE observation during this task reported the shimmer absent. That is consistent with the measurements and is encouraging, but the brief records that this artefact is hard to capture in VICE and was reproduced on MiSTer — so the VICE observation is not the gate.

### What to look for

Level 2 is the better test: its bright green playfield puts maximum contrast against the border's black, which is the wrong colour that used to leak in.

1. Play Level 2 and watch **only** the top edge of the playfield, the join just under the HUD.
2. **The old partial-line symptom:** a dark bar along the left of the top playfield line, roughly six characters wide, flickering at about 12.5 Hz — fast enough to read as a shimmer rather than a blink. It was strongest while scrolling, because the scroll is what cycles YSCROLL through 5 and 6.
3. **The old whole-line symptom:** the entire top playfield line going black for a single frame, intermittently, a few times a second.
4. Both should be absent, and the top edge should be a clean, static boundary.
5. Worth a look with the ship parked at the very top of the aperture and with several enemies on screen — that is the sprite-DMA case, and the case §9 argues is safe.

If anything remains, the useful detail is **which** of the two symptoms it is, since they had different causes and different fixes.

## 14. What is proven where

| claim | proven by |
|---|---|
| the join is raster 55, and is two register writes not a border transition | source: `TOP_SPLIT_LINE`, the `$d021` aperture note in `src/main.asm`, `exTop` |
| the deadlines are cycles 15 and 17 | VIC-II timing, matching the engine's own stated derivation |
| phases 5 and 6 wrote at cycles 18..29 before the change | VICE `LIN`/`CYC` at a watchpoint on the store |
| phase 7 lost the whole line on 22 of 86 frames | same |
| the phase-7 loss is not sprite DMA | sprite Y captured at the store; correlation absent both ways |
| all eight phases now land inside the safe window | 779 gameplay samples, zero outside |
| sprite load does not move the landing | stress run, §11 |
| **the shimmer is gone on real hardware** | **NOT PROVEN — MiSTer/CRT, §13** |

---

## 15. Files changed

| file | change |
|---|---|
| `src/renderer.asm` | `TOP_ARM_LINE` 53 → 52 with its derivation; the YSCROLL-7 `$d021` store converted from a poll to a counted 56 cycles, with `exTop7Poll` kept as the unanchored fallback; three comments corrected where they stated the old arm line or described the phase-7 store as a poll |

`git diff --stat`: one file, +143 / −24, the large majority of it comment. **No other file in the repository was modified.** No gameplay, scroller, multiplexer, HUD, collision, level or editor code was touched.

### Diagnostics

All measurement was external — VICE watchpoints plus `LIN`/`CYC` — so **no diagnostic code was added to the build and none has to be removed**. The scripts live in the session scratchpad, not the repo. No border-colour markers, no debug builds, no temporary instrumentation left behind.

The engine's own counters (`edgeLate`, `topSplitMin`, `topSplitMax`, `topLanded`) are unchanged and still line-granular. They were not extended to cycles: doing so would need a cycle source the machine does not have, and the external measurement is both exact and free at runtime.

## 16. Memory and cycle impact

* **Memory:** none. No new variables; the pad is four `nop`s and a `dey`/`bne` loop.
* **Cycles:** the arm moves one raster earlier, so the poll spins about 63 cycles longer per frame; the phase-7 count adds 43 cycles on one frame in eight, roughly 5 per frame averaged. Against 19,656 cycles a frame that is about 0.35%, and `gameOverrun` stayed 0 in every run including the forced worst case.

## 17. Repository status

**Nothing committed. Nothing pushed.** HEAD is still `8795c39`.

```
 M src/renderer.asm
```

Untracked: the report itself.

### Hygiene

* Every VICE was launched and reaped by the harness with its own PID recorded (`[vice] launched pid N` / `[vice] reaped pid N` in every run above). **No `pkill`, no `killall`**, no user session touched, `-console` throughout so nothing took focus. `pgrep -x x64sc` is empty at the end.
* The A/B swapped `src/renderer.asm` to the committed version and back under a shell `trap`, with the fixed file held in scratch and verified by SHA-256 on the way out (`f7926a19c9a8efbe`). The tree is the fixed version now, confirmed by `TOP_ARM_LINE = 52` at line 291.
* Disk: `build/` **404 KB**, session scratch **256 KB**. No per-run directories, no accumulated artefacts.
