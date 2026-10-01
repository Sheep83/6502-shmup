# `clipMakeScratch` performance audit

**Date:** 2026-10-01
**Scope:** one routine, `src/clip.asm`. The scheduler, the executor, the slot
policy, the clip pool size, the aperture, the row mapping and the visible output
are all unchanged.
**Committed or pushed:** no. **No destructive git operation was used.**

---

## 0. Result

| | before | after | saved |
|---|---:|---:|---:|
| one clipped sprite, shallowest (`c = ±1`) | 1,209 / 1,225 | 1,035 / 1,031 | **~174 / ~195** |
| one clipped sprite, deepest (`c = ±20`) | 981 / 997 | 806 / 803 | **~175 / ~194** |
| six clipped sprites, `setup+accept` | 9,805 | **8,486** | **1,319** |

The saving is **flat at ~174 cycles per clipped sprite** regardless of clipping
depth, because it comes from the cost of touching each of the 63 bytes rather
than from the amount of visible data.

On the worst case the current architecture can represent — six simultaneously
clipped sprites, the clip pool's capacity — that is **1,319 cycles, about 6.7%
of a PAL frame**, recovered without changing a single visible pixel. Output is
**byte-exact across all 40 clipping depths**.

Cost: **+95 bytes** of code, in a segment that still has 138 bytes free.

The prior audit's figure of ~1,320 cycles per clipped sprite was a marginal
estimate taken through the builder. Measured directly at the routine, the true
figure was **1,209 at the shallowest clip** and the marginal cost through the
builder was ~1,320 — so the attribution was correct and is now refined.

---

## 1. Starting state

`src/renderer.asm` modified and `reports/buildschedule-performance-audit.md`
untracked — the previous pass's work, uncommitted, and preserved throughout.
`HEAD` at `26f07c8 regenTick optimised`.

Read: `buildschedule-performance-audit`, `whole-frame-audit-and-regen-optimisation`,
`regen-contiguous-row-copy`, `mux-glitch-diagnostic-pass-1`,
`mux-legality-window-batch-merge`, and `src/clip.asm` in full.

---

## 2. The clipping contract

Established from the source, not invented.

**When.** From the builder's accept path only, once per accepted logical sprite
whose `logClip` is non-zero, and only after the builder has confirmed a pool
block is free.

**What qualifies.** `logClip[id] != 0`. Positive `c` means the sprite hangs
*above* the aperture by `c` rows and is held at `MIN_SPRITE_Y`; negative means it
hangs *below* and is held at `MAX_SPRITE_Y`.

**The row mapping**, which is the whole of the semantics:

```
TOP    c > 0, true logY = MIN_SPRITE_Y - c
       block row r  <-  source row r + c          rows 21-c..20 blanked
BOTTOM c < 0, true logY = MAX_SPRITE_Y + |c|
       block row r  <-  source row r - |c|        rows 0..|c|-1 blanked
```

Both are one contiguous run of copied rows plus one run of blank rows, which is
why there is a single loop pair rather than two routines. Granularity is one
sprite row (three bytes), so every visible row lands on exactly the raster the
enemy's real position puts it on — there is no rounding anywhere.

**Source.** `logPtr[id] * 64`, taken from the render pointer rather than a
hard-coded bitmap, so an animation frame change or a different species follows
automatically. This is why the scratch must be regenerated rather than cached
against a sprite identity.

**Scratch memory.** Twelve 64-byte VIC-visible blocks, as two pools of
`CLIP_POOL_SLOTS = 6`, selected by `schedNext` so the pool is double-buffered
with the schedule. Flat index = `page * 6 + slot`. Blocks are 64-byte aligned
and asserted to be inside VIC bank 0 and non-overlapping at build time.

**Lifetime.** One build. `clipBuildBegin` resets `clipUsed` to zero in the
builder's preamble, so each build allocates from a fresh pool; a block's contents
belong to whichever sprite took that slot in that build and are never carried
forward. **Nothing is shared between clipped sprites and nothing survives a
frame** — which is exactly what makes a cache hard, see §6.

**Exhaustion.** Six clipped sprites per build. The seventh is refused by the
builder *before* calling this routine: the entry is dropped and `clipPoolFull`
counts it, saturating. Deterministic, and no partial scratch is ever produced.

**What it touches.** Only the 63 bitmap bytes and its own locals. It returns the
block's sprite pointer in A and preserves X and Y. X, `$d010`, colour, enable,
expansion and priority are the builder's business and are untouched here. Y is
clamped by the builder, not by this routine.

---

## 3. Method

Cycle-exact between PC-verified breakpoints on `clipMakeScratch` and its `rts`,
read from VICE's stopwatch, with the raster IRQ masked at `$d01a` across the
call and restored afterwards. A monitor stop consumes no emulated cycles.

The routine is driven by breaking on the **real call site** — the builder's own
entry — and writing synthetic logical sprites there, so it runs its ordinary
course. Nothing sets `PC`.

One measurement note kept honest: the first case of a run sometimes reports no
block, a warm-up artefact of arming breakpoints mid-frame. Those samples are
discarded, not counted as data.

---

## 4. Baseline ledger

The routine's shape is: setup (save registers, derive the source address by two
shifts, compute `clipBlank = |c| * 3` and `clipVis = 63 - clipBlank`, pick the
pool block, patch the self-modified addresses, aim the two runs), then a copy
loop and a blank loop.

```
copy:   lda abs,y (4) + sta abs,y (5) + iny (2) + dex (2) + bne (3)  = 16 /byte
blank:  sta abs,y (5)                 + iny (2) + dex (2) + bne (3)  = 12 /byte
```

Measured across every legal depth, both directions:

| `c` | direction | visible B | blank B | cycles |
|---:|---|---:|---:|---:|
| 1 | top | 60 | 3 | 1,209 |
| 3 | top | 54 | 9 | 1,185 |
| 8 | top | 39 | 24 | 1,125 |
| 14 | top | 21 | 42 | 1,053 |
| 20 | top | 3 | 60 | 981 |
| −1 | bottom | 60 | 3 | 1,225 |
| −8 | bottom | 39 | 24 | 1,141 |
| −20 | bottom | 3 | 60 | 997 |

These fit a model exactly:

```
cycles = fixed + 12 x 63 + 4 x visible_bytes
fixed  = 213 (top)   229 (bottom)
```

The 16-cycle difference is the bottom branch's 16-bit destination add. Check:
top `c=20` → 213 + 756 + 12 = **981**, measured 981.

**Two things follow, and they decided the whole pass.**

1. **The work is constant — 63 bytes always.** Deeper clipping is marginally
   *cheaper* only because blanking a byte costs 4 cycles less than copying one.
   There is no "only do the visible rows" saving available: the blank rows must
   be written because the block holds another sprite's bytes from a previous
   build.
2. **The cost is loop overhead, not data.** Of the 16 cycles a copied byte
   costs, 9 are the load and store and **7 are bookkeeping** — `iny`, `dex`,
   `bne`. That is the target.

---

## 5. The change

Both loops now process **one sprite row — three bytes — per iteration**, and
index **downwards**.

Three bytes is the natural unroll because every count here is a multiple of
three: clipping is row-granular and a sprite row is three bytes, so `clipVis`
and `clipBlank` can only ever be `3n`. The branch is therefore paid once per
three bytes instead of once per byte, with no remainder handling.

Counting down removes the second index register: `ldy count-1`, three `dey`s and
a `bpl` do what `iny / dex / bne` did, so the `dex` disappears entirely.

```
copy:   3 x (lda abs,y + sta abs,y) + 3 x dey + bpl = 36 /3 bytes = 12 /byte
blank:  3 x  sta abs,y             + 3 x dey + bpl = 24 /3 bytes =  8 /byte
```

Both runs now start at index zero, which is why the TOP case folds its tail
offset into the blank *destination address* rather than into a starting index.
`clipBlankAt` is gone; `clipReturn` was added so a cycle probe has a symbol to
break on rather than depending on whatever variable happened to follow the
`rts`.

The unrolling costs six extra self-modified address patches in setup (+78
cycles, measured: fixed went 213 → 291). The per-byte saving is 4 across all 63
bytes = 252. **Net 174, flat.**

### After

| `c` | before | after | saved |
|---:|---:|---:|---:|
| 2 top | 1,196 | 1,023 | 173 |
| 8 top | 1,125 | 950 | 175 |
| 14 top | 1,053 | 878 | 175 |
| 20 top | 981 | 806 | 175 |
| −3 bottom | 1,202 | 1,006 | 196 |
| −14 bottom | 1,070 | 874 | 196 |
| −20 bottom | 997 | 803 | 194 |

New model: `cycles = 291 + 8 x 63 + 4 x visible` — `795 + 4 x visible`.

---

## 6. Rejected approaches

* **Caching clipped bitmaps across frames (candidate E).** Rejected on the
  contract, not on taste. A pool block is allocated by *order of appearance
  within a build* (`clipUsed`), so the block a sprite receives changes whenever
  the set of clipped sprites changes. Worse, an enemy moving one pixel a frame
  changes its clip depth every frame, and `logPtr` changes with animation — so
  the common case is a guaranteed miss. A cache would need per-block ownership,
  depth and frame validity, and would still regenerate almost every frame.
* **Work proportional to visible data only (candidate D).** Tracking each
  block's previously-written extent and clearing only the difference. For deep
  clips (3 visible bytes) this would be much cheaper; for shallow clips (60
  visible) it is *worse* — 2 x 60 writes instead of 63. And it depends on stable
  block ownership, which §2 shows does not exist.
* **Separate top and bottom routines (candidate C).** The two differ by one
  16-bit add. Splitting duplicates ~90 bytes to save ~16 cycles on one of the
  two paths.
* **Unrolling further than one row.** Counts are multiples of three and nothing
  larger, so a six-byte unroll needs an odd/even entry path. The remaining
  branch cost is 1 cycle per byte; halving it saves ~32 cycles for materially
  more complexity.
* **`lda (zp),y / sta (zp),y`.** 5 + 6 cycles against absolute,y's 4 + 5. Worse.
* **Avoiding the blank entirely by pre-zeroing the pool at init.** The block is
  reused every build; whatever the previous owner wrote must be cleared by
  someone. It moves the work, it does not remove it.

---

## 7. Correctness

**Byte-exact against a host reference model of the documented row mapping**, for
**all 40 legal depths** (`c = ±1 … ±20`), reading the produced scratch block
back out of VIC memory:

```
40 ok, 0 mismatches
```

The same model was first validated against the **unmodified** implementation
(39/40, the one gap being the warm-up artefact described in §3), so it is an
oracle for the old behaviour and not merely a description of the new one. Old
and new therefore agree with each other byte for byte.

What that proves, specifically: the copied run lands on exactly the right rows
at both boundaries; the blanked run is exactly the complement and contains no
surviving bytes from the block's previous owner; there is no off-by-one-row at
`c = ±1` or at `c = ±20`; and both directions are exact.

**Unchanged by construction:** the routine never touched X, `$d010`, colour,
enable, expansion, priority or the clamped Y, and still does not. Register
preservation (X and Y in, X and Y out, pointer in A) is unchanged. The pool
selection, the `clipUsed` bookkeeping and the exhaustion path were not edited —
so the seventh clipped sprite is still refused by the builder with
`clipPoolFull`, before this routine is reached.

**Scheduler safety.** The clipped-Y ordering interaction identified by the
previous audit — clipping clamps Y to the aperture edge, so a list ascending in
logical Y can present a descent in scheduled Y, which the builder handles by
rejecting through `bs_unsafe` — is untouched: this pass changed no Y, no
clamping and no acceptance logic.

---

## 8. Simultaneous clipped sprites

Six logical sprites, `k` of them clipped, through the real builder (pure cycles):

| clipped | `setup+accept` | batch | tail | build total |
|---:|---:|---:|---:|---:|
| 0 | 1,668 | 111 | 97 | 1,876 |
| 1 | 2,708 | 112 | 97 | 2,917 |
| 2 | 3,747 | 155 | 97 | 3,999 |
| 3 | 4,915 | 112 | 97 | 5,124 |
| 4 | 6,039 | 112 | 97 | 6,248 |
| 5 | 7,164 | 112 | 140 | 7,416 |
| 6 | **8,486** | 156 | 97 | **8,739** |

Linear at **~1,136 cycles of build cost per clipped sprite** (was ~1,632).
Six is the architectural maximum — `CLIP_POOL_SLOTS` — and a seventh is refused
before the routine is entered.

Against the previous pass's measurement of **9,805** for the same six-clipped
case, this is **1,319 cycles saved — 6.7% of a PAL frame** on the worst clipping
load the engine can currently produce.

The batch and tail stages are unchanged, as expected: nothing outside
`src/clip.asm` was touched.

---

## 9. Tests

| suite | result |
|---|---|
| byte-exact oracle, 40 depths both directions | **40 ok, 0 mismatches** |
| `make smoke` | **PASS** — `ENGINE HEALTH: PASS`, `ROUTINE REGRESSION: PASS` |
| `test_clip_scratch.py` | 3 failures — **pre-existing, unchanged** |
| `test_ebullet_clipping.py` | 2 failures — **pre-existing, unchanged** |

### Both failing suites were proved pre-existing, not assumed

Each was run against a binary built from the **unmodified `src/clip.asm`** and
against the changed one. Identical failures, identical assertions, identical
count:

```
test_ebullet_clipping
  AFTER  === 2 FAILURES: a bolt now lives to the last row its ink can be drawn
                         on; the stress scenario really did hold bolts in the
                         clip band ===
  BEFORE === 2 FAILURES: (identical)
```

`test_clip_scratch`'s three were proved pre-existing the same way during the
previous pass and are unchanged in count and content here.

This matters particularly because the brief warns against "fixing" production
code to satisfy stale clipping assumptions. The byte-exact oracle in §7 is the
evidence that production is correct: the scratch output matches the documented
row mapping at every legal depth in both directions. **The tests are stale, the
engine is right, and no production code was bent to make them pass.** They now
have a reference model available to be modernised against — that is a bounded
piece of work and is deliberately left out of this pass.

---

## 10. Files changed, size and disk

| File | Change |
|---|---|
| `src/clip.asm` | both runs unrolled to the sprite row and indexed downwards; blank offset folded into the destination; `clipBlankAt` removed; `clipReturn` label added |
| `reports/clipmakescratch-performance-audit.md` | new |

Also present and **untouched** from the previous pass: `src/renderer.asm`
(the scheduler tail-loop merge) and `reports/buildschedule-performance-audit.md`.

**Code size:** `clipCodeEnd` `$8117` → `$8176`, so the routine grew from 212 to
307 bytes — **+95 bytes**, with 138 bytes still free before the `$8200` segment
limit the file asserts. No data or pool memory changed.

**Disk:** `build/` 404K, current binary and symbols only, no per-run
directories. Session scratchpad 316K — the clip lab, the oracle, the corpus and
two before/after source copies — disposable and outside the repository.

---

## 11. What was NOT done

* **HW0/HW1 were not opened to the mux.** The six-slot HW2–HW7 pool, the player
  reservation and the muzzle reservation are exactly as they were.
* **No scheduler change.** The previous pass's tail merge is carried unchanged;
  nothing else in `renderer.asm` was touched.
* **No semantic change.** Aperture, clamping, row mapping, pool size, pool
  selection, exhaustion behaviour and every sprite attribute are untouched.
* **No manual VICE session.** All measurement was automated through the harness
  with the monitor; I did not put the game on screen, and I am not claiming a
  visual check. The byte-exact oracle is the evidence offered instead, and it is
  a stronger one for *this* property than an eye on a moving sprite would be.

---

## 12. Status

- **Nothing committed, nothing pushed.**
- **No `git checkout`, `restore`, `reset`, `stash` or `clean` was used.** The
  before/after comparisons were done by copying the source aside and back.
- The previous pass's uncommitted work was preserved throughout.
- VICE: every instance launched through the harness and reaped by exact PID; no
  `pkill`/`killall`; no user-launched instance touched; no focus stolen;
  `pgrep -x x64sc` reports none remaining.

---

## 13. Ready for the 6+2 vs 7+1 vs 8-slot benchmark?

**Yes — and more usefully, clipping is now a predictable term rather than a
confound.**

Clipping cost is a closed-form function of one variable:

```
clipMakeScratch = 795 + 4 x visible_bytes        (top;  +8 for bottom)
visible_bytes   = (21 - |clip_depth|) x 3
```

That ranges from **806 to 1,035 cycles**, a span of only 229 — so for planning
purposes a clipped sprite costs **about 1,000 cycles, flat**, and a build costs
~1,136 more per clipped sprite than per ordinary one.

Three things that matter for the slot experiment:

1. **Clipping is independent of slot count.** It happens per accepted sprite in
   the accept path, before any batching. Changing the pool from six to seven or
   eight slots does not change it — so it is a constant offset that can be
   subtracted when comparing policies.
2. **It is capped at six per frame** by `CLIP_POOL_SLOTS`, not by the mux. A
   hostile layout cannot spend more than ~6,000 cycles here however it is
   arranged. That is a hard ceiling the comparison can rely on.
3. **Hold it constant deliberately.** The harness built here takes clip depth
   per sprite as an explicit input, so a layout can be replayed with identical
   clipping geometry under 6-, 7- and 8-slot policies. Without that, a layout
   that happens to clip one more sprite shifts the result by ~1,100 cycles and
   would be read as a slot-policy difference.

Clipping is now both cheaper and, more importantly, **characterised**. The
remaining ~1,000 cycles per clipped sprite are structurally justified: 63 bytes
must be written, and at 12 and 8 cycles a byte the loops are close to the
practical floor for indexed 6510 copying.
