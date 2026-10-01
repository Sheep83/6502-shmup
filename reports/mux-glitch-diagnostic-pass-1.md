# 19656 — Multiplexer Glitch: Diagnostic Pass 1

**Date:** 2026-10-01
**Scope:** read-only diagnosis. **No production file was changed.**
**Outcome: B — the mechanism is identified and it is NOT the multiplexer.**
The symptom is a **main-thread frame overrun**: at 6-8 live objects the game's
per-frame work reaches **101-107% of a PAL frame**, so a displayed frame is
missed, `objectUpdateAll` does not run, and every sprite stops moving for that
frame before resuming. No speculative patch is applied.

**The user's description is what identified it.** Sections 1-3 below are the
multiplexer investigation that came first and found nothing; §4A is the actual
finding. The mux exoneration is kept because it is load-bearing: it rules out
the explanation everyone expected.

> **The user's visible VICE result stands.** `AGENTS.md` rule 2 makes manual
> visible output authoritative and rule 4 says a green instrument can be wrong.
> Nothing below should be read as "there is no glitch". It is an account of
> where the glitch is **not**, which is worth having before anyone changes the
> multiplexer.

---

## 1. The reproduction

The authored stripped level was read as the user left it — **the working tree was
preserved and nothing was re-authored.**

```
trigRow      40            41              50
trigDef      DIVE_4        SWEEP_L         SWEEP_R
trigSpecies  DROPPER       SQUARE          SQUARE
trigFire     %00000000     %00000001       %00000100
trigFireMode DOWN          AIMED           DOWN
trigSpeed    1.00x         1.50x           1.50x
trigDropProg PROG_DIVE_BOMB  LEGACY        LEGACY
```

| | members | start | per-member | program |
|---|---|---|---|---|
| Dropper | 1 (forced) | (175, 0) | — | `PROG_DIVE_BOMB`, authored |
| wave 1 | 3 | (0, 64) | y+20 | `PROG_SWEEP_L` |
| wave 2 | 3 | (350, 48) | y+20 | `PROG_SWEEP_R`, heading 32 |

**Spawn Y: 48, 64, 68, 84, 88, 104 — gaps 16, 4, 16, 4, 16, every one below the
21-raster sprite height.** Up to five enemies mutually overlap. Sprites also
straddle the 256-pixel X boundary in both directions, which no earlier level
exercised as hard.

**Reproduced automatically: the LOAD, yes. The GLITCH, no.**

---

## 2. What the hardware budget actually is

| | |
|---|---|
| HW0, HW1 | the player: ship and muzzle flash. Never in the schedule. |
| HW2–HW7 | `MUX_SLOTS = 6`, shared with the HUD above the aperture |
| peak logical | **8** (Dropper + 6 enemies + 1 enemy bullet) |
| peak accepted | **8** on 6 slots — two slot reuses |
| peak batches | **2** |

The player's shot is a **ray**, not a pooled projectile; holding fire adds the
muzzle flash on HW1 and **no mux load at all** (measured: peak unchanged at 8).

---

## 3. Every axis measured, and the result

All figures from the user's level, `boot="exact"`, exact owned PIDs, every VICE
reaped.

### 3.1 Scheduling invariants — 114 published schedules

| Invariant | Result |
|---|---|
| schedule sorted by Y | **holds** |
| every Y inside `MIN_SPRITE_Y..MAX_SPRITE_Y` (55..226) | **holds** |
| every slot in 2..7 | **holds** |
| **reuse gap ≥ `MIN_REUSE_GAP` (33) for any slot reused** | **holds** |
| slot assignment is the i−6 round robin | **holds** |
| batch lines ascending | **holds** |
| no mid-screen batch at or above `TOP_ARM_LINE` | **holds** |
| no batch larger than `MUX_SLOTS` | **holds** |
| batch counts cover the schedule exactly | **holds** |
| every batch fires ≥ `REUSE_LEAD` before its sprite | **holds** |

### 3.2 Acceptance faults — PC-confirmed breakpoints

`statRejRange` is documented as **not a fault** (the Y-admission rule; every
enemy approaching from off-screen trips it). The real faults:

| Path | Meaning | Reached? |
|---|---|---|
| `bs_margin` | gap 21..32 — hardware-legal, dropped by **our** 12-line margin | **never** |
| `bs_unsafe` | gap < 0 — the sorted list is not sorted | **never** |
| `statOverflow` | `MAX_SCHED` full | 0 |
| `statBatchOverflow` | `MAX_BATCH` full | 0 |

**Not one in-band sprite was ever missing from the schedule**, across every run
including one with the trigger held and the ship swept.

### 3.3 Timing — 31,454 frames, free-running, **no monitor traffic**

The only un-perturbed measurement in this report.

```
gameOverrun      0        statLate         0        clipPoolFull     0
scrollLate       0        edgeLate         0        objAllocFail     0
objDoubleFree    0        schedBuildDefer  +0       publishSkip      +3
```

`publishSkip 3 in 31,454 frames` is far inside the documented budget (5 per
3,000).

### 3.4 Batch execution rasters — the deadline nobody counts

`statLate` only catches "the line I am about to **arm** has already passed". It
cannot see a batch that starts on time, runs long, and writes sprite Y after the
beam has passed it. Measured from the emulator's own raster (`LIN`):

```
1,242 batch executions
batches finishing at or after their first sprite's Y:   0
worst margin overall:      5 lines  (batch 0, 6 entries, ran 41->50, Ymin 55)
worst mid-screen margin:   7 lines  (2 entries, ran 177->182, Ymin 189)
```

### 3.5 `$d010` X-MSB across the 256-pixel boundary

This level is the first to drive sprites across x=256 in both directions while
sharing slots.

```
frames with sprites on both sides of the boundary:  85
batch $d010 snapshots checked:                     288
mismatches against the complete correct value:       0
```

### 3.6 Clip scratch — both edges

`tests/test_clip_scratch.py` fails, and it is a renderer test, so it was chased
to the bottom. **The engine is right and the test is wrong**, evidenced by
stopping inside `clipMakeScratch` and dumping the bytes:

```
BOTTOM clip id=4 logY=229 logClip=-3  -> MATCHES CONTRACT
BOTTOM clip id=4 logY=232 logClip=-6  -> MATCHES CONTRACT
BOTTOM clip id=4 logY=235 logClip=-9  -> MATCHES CONTRACT
```

The scratch bytes equal `[0]*3|c| + src[:63-3|c|]` exactly, which is the
documented bottom contract. The test's failures are artefacts:

* it compares the **CURRENT** schedule's scratch (built on the previous frame)
  against the enemy's **current** `logY`/`logClip`, and at 1.50× speed the clip
  changes by **3 rows per frame**, so the comparison is three rows out;
* `clipping walks one row at a time` is a stale assumption — at 1.50× an enemy
  legitimately moves 3 px a frame.

**These are pre-existing: `test_clip_scratch` fails identically at HEAD.** They
are test debt, not the glitch, and were not "fixed" here.

### 3.7 Pixels

114 PNGs captured through the encounter and decoded. Automated search for the
most likely visible symptom:

```
one-frame dropouts (coloured pixels at N-1 and N+1, absent at N):  0
anomalous frame-to-frame changes in coloured sprite pixels:        0
```

### 3.8 Projectiles — the brief's item 12

**Not causal, and present throughout.** Enemy bullets (`TYPE_EBULLET = 2`) are in
every busy capture. `wvShots = 2` over 30 s: exactly the two authored firing
members. Runs with and without them are indistinguishable on every axis above.

### 3.9 Token encounter

Killing the Dropper through the engine's own staged death path (timer first, then
health) starts the encounter and conscripts protectors (roles 0–3 all observed).
Peak logical 5, refusals 0, invariant breaches 0. **Not reproduced here either**,
though see §6 — this is the load case I am least confident I drove hard enough.

---

## 4A. THE ROOT CAUSE — main-thread frame overrun

The user's report settled it: *"not a sprite glitch, more an 'all enemy sprites
stop moving'... does not occur when player not firing"*, and *"all sprites pause
briefly"*. That is not a mux fault at all. It is the game missing a displayed
frame: the renderer IRQ keeps drawing, so nothing vanishes or tears -- the
objects simply are not **moved**, because `objectUpdateAll` did not run.

### The measurement

Elapsed cycles from `gameFrame` entry to `gameSpan` (which `gameFrame` falls
through into, so this is the whole of the main thread's per-frame work),
measured with the emulator's own cycle counter:

| live objects | frames | median | worst | worst in lines | % of PAL frame |
|---:|---:|---:|---:|---:|---:|
| 0 | 543 | 8,140 | 12,191 | 193 | 62% |
| 3 | 23 | 11,528 | 14,478 | 229 | 74% |
| 4 | 63 | 11,846 | 15,285 | 242 | 78% |
| 5 | 30 | 13,693 | 17,939 | 284 | 91% |
| **6** | 43 | 15,338 | **19,948** | 316 | **101%** |
| **7** | 31 | 15,275 | **20,935** | 332 | **107%** |
| **8** | 10 | 18,142 | **20,556** | 326 | **105%** |

**A PAL frame is 19,656 cycles.** From six live objects the worst case exceeds
it. This encounter sustains 6-8 live objects for its whole duration.

### Why firing is the trigger

Firing is not the cause; it is the straw. The 2026-09-13 audit measured it:

> **Collision on a volley frame.** Two full 16-slot scans, ~170 cycles per enemy
> per ray. **~3,400 pure, ~5,000 elapsed.**

5,000 cycles is **80 raster lines**. At six objects the span is already 101% of
a frame in the worst case and ~78% typically, so a volley frame pushes typical
frames over the line. That is exactly "it only happens when I fire".

### Why it looks like sprite pressure

Because it *is* proportional to sprite count -- just not through the mux.
`objectUpdateAll`, `sortTick` and `buildSchedule` are all O(objects), so the
cost tracks the population. The user's instinct ("sprite pressure on the mux")
was right about the correlation and the mux was the wrong suspect: §3 proves its
scheduling, timing, reuse and `$d010` handling are all correct.

### The instrumentation is lying, and that is its own defect

* `gameSpanOver` = **25** in one run: 25 frames finished past the 255-line
  measurement ceiling. The counter **saturates**, so the true cost was
  invisible -- exactly the "saturating counter read as a rate" trap `AGENTS.md`
  rule 4 names. The cycle measurement above is what got past it.
* `gameOverrun` = **0** throughout, while direct measurement shows spans over
  100% of a frame. Its detection (`frameCounter` delta >= 2 at the top of the
  main loop) is not catching this. **That is a reportable instrumentation
  defect**: the one counter whose entire job is to detect this symptom does not.

### Why no fix is applied here

The brief forbids capping the encounter, reducing enemies or projectiles, or
adding delays, and requires a narrow principled fix only once the mechanism is
identified. The mechanism is now identified but the remedy is a **cycle-budget**
change, and the 2026-09-13 audit already ranked the options and measured their
yield -- merge batches by legality window (~3,500), regen scheduling
(~1,500-2,500), builder constant factor (~1,500), interrupt fixed overhead
(~1,000), single-pass collision (~1,300). Together ~7,000-8,000 cycles, which
turns a 107% frame into ~70%.

Choosing among those is a performance pass with its own measurements, not
something to improvise at the end of a diagnostic. **Recommended next pass:
single-pass collision first** (it is the firing-specific term, it is ranked low
risk and low complexity, and it directly addresses the "only when firing"
trigger), then the builder and interrupt constant factors.

---

## 4B. A second, smaller finding

**Batch 0 costs nearly twice what the code says it does.**

`src/renderer.asm` justifies `HANDOFF_LINE = 40` with:

> "it leaves twelve lines before `TOP_ARM_LINE` and fifteen before the first
> legal sprite Y, **against a six-entry batch 0 costing about five**."

Measured: a six-entry batch 0 runs **41 → 50, nine raster lines**. The margin
before the first legal sprite Y is therefore **5 lines, not the ~10 the comment
implies**.

This is **not** the glitch — the margin holds, and batch 0 is capped at
`MUX_SLOTS` so nine lines is its worst case. But it is a load-bearing number that
is wrong in a comment that exists to justify a raster constant, and
`AGENTS.md` rule 3 says numbers like that belong to measurement. It should be
corrected in whatever pass next touches the renderer.

No fix is applied here because the brief forbids changing raster constants
without an invariant, and nothing is currently violated.

---

## 5. Architecture comparison

**Neither replacement is indicated.** The failure is not a scheduling fault, so
changing the scheduling architecture would cost cycles rather than save them --
and cycles are the actual scarce resource. For the record, the current design **already is** an immutable
double-buffered Y-sorted schedule: two buffers, one atomic publish byte, the
executor reading `schedCurrent` while the builder writes `schedNext`, and the
pool-separation check passes. Recommending a replacement for an architecture
whose invariants all measure clean would be speculation.

The 2026-09-13 audit's capacity concern (**batches, not sprites**; 11 batches
overran the frame) **does not apply to this level**: peak 2 batches.

---

## 6. What I could not rule out about the MUX (superseded by §4A)

Honest list, ranked by how much I distrust my own coverage:

1. **A symptom my probes cannot see.** Everything samples at the frame IRQ with
   the machine halted, or free-runs and reads counters. A mid-frame visual
   artefact lasting part of one raster — a torn sprite edge, a one-line colour
   smear at a batch boundary — would be invisible to all of it and plainly
   visible to a person.
2. **The token encounter at full wave load.** I killed the Dropper at 5 live
   objects; a player might kill it with 7–8 live and the protector ring posted,
   clustering Y far tighter than anything I measured.
3. **Longer play.** My longest un-perturbed run was 30 s. The user plays longer
   and reaches states I did not.
4. **The HUD↔gameplay HW7 handoff.** HW7 changes owner between the HUD and
   gameplay on **82 of 114 frames** in this level — far more often than in
   previous content. I verified the schedule side but not the HUD side.

---

## 7. Answered

The user's description is what cracked this, and it is worth recording why: no
amount of counter-reading could have inferred it, because every mux counter was
correctly green. "All sprites pause" ruled out the entire class of defect the
investigation had been built around and pointed at the frame budget in one
sentence.

---

## 8. Tests run

| | |
|---|---|
| `tests/test_clip_scratch.py` | 3 failures, **pre-existing at HEAD**, diagnosed as test artefacts (§3.6) |
| Diagnostic probes (disposable, scratch only) | invariants, fault paths, batch timing, `$d010`, pixels, played run, token run |
| `make smoke` | **not re-run** — no production file was changed, so the binary is identical to the one smoke last passed against |

`make smoke` is deliberately omitted: this pass changed nothing to validate, and
running it would only re-measure an unchanged binary.

---

## 9. Hygiene

* **No production file changed.** No commit, no push. No destructive git use.
* All probes are disposable and live in the session scratchpad; the 616 KB of
  captured PNGs was deleted after analysis.
* Disk after the run: scratchpad 26 MB (probe scripts and task logs), `build/`
  340 KB, 10 files — no per-run directories.
* VICE: exact owned PIDs, every launch reaped on success and failure, no broad
  `pkill`, `-console` only, no focus stolen. `pgrep -f x64sc` = **0** after every
  run.
* **No human visual confirmation is claimed.** The user's observation is the only
  visual evidence in this report.

## 10. Final `git status`

Unchanged from the start of this pass — 46 paths, all pre-existing work from
earlier tasks plus the user's own re-authored level, every one preserved. The
only addition is this report.
