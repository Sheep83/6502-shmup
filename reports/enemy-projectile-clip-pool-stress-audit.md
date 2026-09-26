# 19656 — Enemy Projectile Clip-Pool Stress Audit

**Verdict: the clip pool is NOT the binding constraint for bottom-edge projectile clipping. `CLIP_POOL_SLOTS = 6` is comfortable for that purpose, because the six same-Y mux slots refuse a seventh bottom-clipped entry *before* the pool is ever consulted. The pool can only be exhausted when BOTH edges are loaded at once, which 15,105 frames of real play never approached.**

**Measurement only. No gameplay, renderer, clipping, collision, raster or sprite-budget change was made. All temporary instrumentation is removed and the working tree reproduces `HEAD` byte for byte.**

---

## 1. Starting state, and one correction to the brief

| | |
|---|---|
| HEAD | `c2b658e` — *Raster glitch fix* |
| Branch | `main` |
| Working tree at start | **clean** |

> **The brief asks me to "preserve the existing uncommitted top-border raster
> fix". There is no uncommitted work — the raster fix is committed, as
> `c2b658e`.** Nothing was at risk, and nothing about it was touched.

---

## 2. Clipping architecture

### The pool

| | |
|---|---|
| `CLIP_POOL_SLOTS` | **6** (`src/renderer.asm:206`) |
| Double-buffered | yes — **12** blocks total, 64 bytes each = **768 bytes** |
| Flat index | `page * CLIP_POOL_SLOTS + slot`, page = `schedNext` |
| Pool 0 | `$0340 $0380 $03c0 $3100 $3140 $3180` |
| Pool 1 | `$31c0 $3680 $3700 $3740 $3780 $37c0` |

Three blocks live in the cassette buffer's tail at `$0340`; the engine banks the
KERNAL out and takes `$fffe` directly, so nothing collides. They are not emitted
into the PRG and need no initialising — every block is written in full before it
is pointed at.

### Ownership, allocation and release

The pool is **indexed by `schedNext`, the same byte the schedule buffers are**.
The builder may only write blocks in the pool it owns; on the atomic swap the
block travels with its schedule and the main thread moves to the other pool.
There is consequently no handover, no raster-progress test and no
safe-to-overwrite window.

Allocation is a **bump allocator with no free**: `clipBuildBegin` zeroes
`clipUsed` at the top of every build, and `clipMakeScratch` takes the next block
and increments it. A slot is therefore "released" by the next build starting,
not by the object leaving.

### Who enrols

`logClipAnnotate` (`src/enemy.asm:720`) is entirely generic — it reads `logY,x`
and writes `logClip,x`, with nothing enemy-specific in it. Callers:

| caller | |
|---|---|
| `src/enemy.asm` | every live enemy, every frame |
| `src/pickup.asm:424` | every live token |
| **projectiles** | **do not enrol** — this is the gap the audit is about |

`objectZeroSlot` clears `logClip` so a reused slot inherits nothing.

### Both edges share one pool

There is one pool, and it is edge-agnostic. `logClip` is positive for rows above
the top edge and negative for rows below the bottom one; `clipMakeScratch`
handles both with one loop pair. **Top-clipped and bottom-clipped entries compete
for the same six blocks.** This is the single most important structural fact in
this report.

### The gate order, per candidate entry

Established by reading `bs_` in `src/renderer.asm`, and it is what the whole
verdict turns on:

1. **Clamp** presented Y from `logClip` — top → `MIN_SPRITE_Y` 55, bottom → `MAX_SPRITE_Y` 226.
2. **Range** `55..226` → else `statRejRange`.
3. **Schedule capacity** `MAX_SCHED = 24` → else `statOverflow`.
4. **Reuse / spacing** against the entry `MUX_SLOTS = 6` places back. The first
   six always fit. Beyond that `gap = thisY - ownerY`: `>= MIN_REUSE_GAP` (33)
   accept; `21..23` accept with a margin note; **`< 21` refuse**.
5. **Clip pool** `clipUsed >= CLIP_POOL_SLOTS` → refuse, `clipPoolFull++`.

**The pool is the LAST gate.** An entry refused for spacing never asks for a
block.

### On exhaustion

The entry is dropped for that frame and `clipPoolFull` increments (saturating at
255). `bs_acc` is untouched, no slot is consumed, and the object's logical life
carries on — it simply is not drawn this frame, which for a sprite half outside
the aperture is the least visible thing that could be dropped.

### Counters

`clipPoolFull`, `statOverflow`, `statRejRange`, `statRejUnsafe`, `statReuse`,
plus the raster counters `edgeLate`, `scrollLate`, `gameOverrun`.

> **A diagnostic wrinkle worth knowing before anyone reads these counters.** A
> same-Y refusal (gap 0, which is what two bottom-clipped entries produce) falls
> through into the `bs_outOfRange` label and increments **`statRejRange`**, not
> `statRejUnsafe`. `statRejUnsafe` is reached only by the `bcc` arm — a negative
> gap, i.e. an unsorted list. So "rejected for range" in this engine means
> *either* an out-of-bounds Y *or* insufficient spacing, and Scenario C's
> `statRejRange = 2` with `statRejUnsafe = 0` is the measured corroboration.

---

## 3. Memory: correcting the previous audit

**The brief asks me to confirm or correct "raising the pool from 6 to 9 would
cost approximately 768 bytes double-buffered and would be very tight against the
documented remaining VIC-bank space". Both halves need correcting.**

### The cost

| change | extra blocks | extra bytes |
|---|---|---|
| 6 → 9 | 6 (3 per pool) | **384** |
| 6 → 12 | 12 | **768** |

768 is the cost of going to **twelve**, not nine. The current pool's *total*
footprint is 768 bytes, which is likely where the figure came from.

### The space

`src/clip.asm` says "VIC bank 0 has 832 spare". **That is stale.** Accounting for
everything the bank actually contains — including the two runtime destinations
the PRG memory map does not show, because their bytes now arrive from the level
package:

| | |
|---|---|
| `$25c0-$27bf` | player fireball — was documented as free |
| `$3580-$367f` | `BOSS_SPRITES`, the boss's runtime destination — was documented as "free, 4 blocks, kept EMPTY" |
| `$2c00-$30ff` | `LEVEL_SPRITES` enemy window, runtime |
| `$0800-$0fff` | terrain charset window, runtime-filled |
| `$1000-$1fff` | character ROM shadow — **the VIC cannot see RAM here at all** |

Genuinely free, VIC-visible, 64-byte-aligned:

```
    $2540-$257f    64 B = 1 block
    $27c0-$27ff    64 B = 1 block
    TOTAL         128 B = 2 blocks
```

Plus, with a caveat, up to **3 more** in the charset window's unused tail
`$0f30-$0fff` — glyph codes 230..255, which terrain (96..223) and the turret
body (226..229) do not use. Those are VIC-addressable as sprite blocks.

**So the ceiling without relocating something is about 5 blocks, and 6 → 9 needs
6.** The previous audit's conclusion ("very tight") was right in spirit and
wrong in both numbers: it is not 768 bytes, and it does not merely squeeze — **it
does not fit.**

`src/main.asm`'s own map comments (lines 37 and 46) still advertise both runs as
free and should be corrected whenever that file is next touched. I have not
changed them, as this task is measurement only.

---

## 4. Methodology and instrument validation

### Instrumentation (temporary, now removed)

1. **`clipUsedMax`** in `src/clip.asm` — a high-water byte updated beside
   `inc clipUsed`. `clipUsed` is reset every build and therefore cannot answer
   "what was the most this run ever needed"; the brief explicitly asks for a
   high-water mark rather than an inference.
2. **One `jmp logClipAnnotate`** at the end of `ebulletTick` in
   `src/ebullet.asm` — enrols projectiles in exactly the path enemies and tokens
   use. This is literally the one line a real implementation would need.

Both were bracketed with `=== TEMPORARY AUDIT INSTRUMENTATION ===` banners.

### Validation before trusting it

The brief warns twice about instruments that lie, and both warnings earned their
place:

* **The published schedule, not the one being built.** All schedule reads use
  `schedCurrent` (the executor's buffer) and its `schedEntries` count — never
  `schedNext`. The published buffer **lags by one frame**, so a schedule entry
  can name an object that has since despawned; I correlate peaks against the
  world snapshot taken at the same instant rather than assuming they match.
* **The high-water was checked against the instantaneous value.** After 400
  frames of ordinary play `clipUsed = 1` while `clipUsedMax = 2` — the mark was
  demonstrably tracking above the sample, not merely mirroring it.
* **No `z`.** Frame stepping is `step_n` on a `gameFrame` breakpoint, the
  harness's own mechanism.
* **Monitor reads halt the machine.** Scenarios that poke every live object each
  frame perturb timing badly; their `gameOverrun` counts are the *instrument*,
  not the engine. The definitive run (E) therefore uses **no per-frame tap at
  all** and free-runs undisturbed, which the high-water mark makes possible.

---

## 5. Measured results

| # | scenario | clip high-water | `clipPoolFull` | peak @ Y=226 | peak @ Y=55 | objects wanting a clip |
|---|---|---|---|---|---|---|
| **A** | baseline, 1,500 frames, projectiles **not** clipped | **2** / 6 | 0 | 2 | 1 | 2 |
| **B1** | projectiles enrolled, 2,500 frames ordinary play | **2** / 6 | 0 | 2 | 1 | 2 |
| **E** | projectiles enrolled, **15,105 frames undisturbed** | **2** / 6 | **0** | — | — | — |
| **B2** | all `EBULLET_MAX` = 3 bolts held in the bottom band | **4** / 6 | 0 | 4 | 1 | 4 |
| **C** | *constructed*: every live object in the bottom band | **6** / 6 | **0** | **6** | 0 | **9** |
| **D** | *constructed*: **both edges** loaded at once | **6** / 6 | **255 (saturated)** | 3 | 5 | 9 |

Scenario E covers `worldProgress` 0 → 1,892 — the whole authored Level 1 more
than twice over, with the wave director running your current twelve triggers and
turrets firing. `statOverflow`, `statRejRange`, `statRejUnsafe`, `statReuse`,
`edgeLate`, `scrollLate` and `gameOverrun` were **all zero**.

### Valid gameplay versus constructed

* **A, B1, E are valid gameplay** — the engine left to run, nothing poked.
* **B2, C and D are constructed.** Each object is placed at a Y it legitimately
  occupies while falling (227..246 is the bottom clip band, 34..54 the top one),
  so no individual state is impossible — but *all of them being there at once* is
  not something the authored content produces. They are a ceiling probe, not a
  prediction.
* **Nothing here is synthetically impossible.** I did not raise `MAX_OBJECTS`,
  force more objects than the pool can hold, or fabricate states the engine
  cannot reach.

### What C and D together prove

This is the core result.

**C — bottom edge only.** Nine objects wanted a clip. **Six** were scheduled, at
Y=226, in hardware slots **2, 3, 4, 5, 6, 7** — every mux slot. The high-water
reached exactly 6 and **`clipPoolFull` stayed at 0**. The seventh candidate was
refused by the *spacing* rule (gap 0 between two Y=226 entries) at gate 4, and
so never reached the pool at gate 5.

**D — both edges.** The same nine objects, split between the two edges. Now the
seventh clipped candidate *passes* the spacing test — the gap between Y=55 and
Y=226 is 171, comfortably over `MIN_REUSE_GAP` — reaches the pool gate, and is
refused. **`clipPoolFull` saturated at 255.**

> **The pool and the mux bind at the same number, 6, but not in the same
> circumstances.** For bottom-edge pressure alone the mux is strictly the
> tighter of the two and the pool cannot be reached. The pool becomes the
> binding constraint only when a top-edge population and a bottom-edge
> population coexist.

---

## 6. Answers to the brief's questions

**1. Maximum clip slots required by currently valid gameplay?**
**2**, over 15,105 undisturbed frames.

**2. What would it become with up to `EBULLET_MAX` clipped projectiles?**
Measured **2** in 15,105 frames of real play with projectiles enrolled —
projectiles reach the bottom band, but three of them rarely coincide there.
Forcing all three to coincide with an enemy gives **4**. The structural ceiling
for bottom-edge-only demand is **6**, and it is imposed by the mux, not the pool.

**3. Can `CLIP_POOL_SLOTS = 6` accommodate that?**
**Yes, with headroom.** Real play used 2 of 6; the hardest constructed
bottom-edge case used 6 of 6 and still never overflowed.

**4. Can bottom-clamped projectiles create a separate mux bottleneck at shared
Y=226?**
**Yes, and it is the real limit.** The maximum number of entries the renderer
can schedule at Y=226 is **6** — measured, occupying slots 2..7 — because all
bottom-clipped entries present at exactly the same Y and the seventh fails the
spacing test. This bites at or before the pool in every bottom-edge scenario.

**5. Can a projectile consume capacity a bottom-diving enemy needs?**
**Yes — but through the mux and the sort order, not the pool.** The builder
sorts by true `logY` ascending, so among objects competing for the six Y=226
slots the one **higher on screen wins**. A bolt at y=228 is scheduled ahead of an
enemy at y=240. The loser is dropped for that frame with no counter naming it as
a projectile-versus-enemy conflict.

**6. Does `clipPoolFull` ever occur?**
**Never in valid gameplay** (0 across every unpoked run, including 15,105
frames). It occurs readily in the constructed both-edges scenario (D), saturating
at 255.

**7. Is six sufficient, marginal or insufficient?**
For the stated purpose — enrolling hostile projectiles at the bottom edge —
**comfortably sufficient**, and it cannot be otherwise, because the mux refuses
the seventh bottom-clipped entry first. See §8 for the caveat that is *not* about
projectiles.

---

## 7. Raster safety

Every undisturbed run: `edgeLate 0`, `scrollLate 0`, `gameOverrun 0`, including
the 15,105-frame run with projectiles enrolled and clipping actively producing
bottom-clamped entries at Y=226.

Presented-Y clamping therefore preserved the bottom split timing exactly as
expected. The `gameOverrun` values in scenarios C (128) and D (126) are the
measurement harness poking up to sixteen objects per frame through the monitor,
which halts and resumes the CPU; they are not engine behaviour and no conclusion
rests on them.

**The committed top-border raster fix was not touched.**

---

## 8. Findings that affect the later design

### The pool's real risk is not projectiles

Adding projectiles to the bottom edge cannot exhaust the pool. What *can* is a
top-edge population coexisting with a bottom-edge one — six entering enemies and
six exiting objects demand twelve blocks from a pool of six, exactly as
`src/clip.asm` predicts. Real play never came close (peak Y=55 was 1, peak Y=226
was 2), but a denser future level could, and **projectile clipping would add to
the bottom half of that sum**. It is a reason to keep watching `clipPoolFull`,
not a reason to refuse the feature.

### The pool cannot be grown to 9 without moving something

§3: about 5 usable VIC-visible blocks remain against the 6 needed. If the pool
ever must grow, something else relocates first.

### A same-Y refusal is counted as `statRejRange`

Anyone diagnosing a dropped bottom-edge sprite will look at `statRejUnsafe` and
find zero. §2.

### `objVY` is dead for motion — and this affects the collision design

While tracing projectile state I measured this and then confirmed it in the
source: **`ebulletTick` advances a bolt vertically by the constant
`#EBULLET_VY`; nothing anywhere reads `objVY` for movement.**

```
  MEASURED PROJECTILE MOTION  (objVX, objVY) -> observed dY per frame
    vx=+1 objVY=3  ->  dY [3]
    vx=+2 objVY=2  ->  dY [3]        <- stores 2, moves 3
```

The `ebulletAimVY` table added in the aimed-fire task writes `objVY` and that
byte is never used, so the speed-matching fix **never took effect**: the steepest
diagonal still travels `sqrt(2² + 3²)` = 3.61 px/frame against 3.00 straight
down, the 20 % spread that work set out to remove. The test I wrote for it
asserted the *stored byte* rather than measured displacement, so it passed while
proving nothing about the trajectory. That is my error and I am recording it
rather than quietly fixing it, because gameplay changes are out of scope here.

It matters to the collision work because **a bolt's vertical rate is uniform**:
any "how long is a bolt dangerous below Y=226" arithmetic can assume 3 px/frame
for every bolt regardless of its aim, which is simpler than the design would
otherwise have to be — but only while that remains true. If `objVY` is ever
wired up, that assumption breaks.

---

## 9. Recommendation

**Proceed with enrolling hostile projectiles in the existing clip path.** The
evidence says the pool is not the constraint and will not become one from this
change.

The design should account for what *is* the constraint:

1. **Six bottom-clipped entries is the hard ceiling**, shared between bolts,
   diving enemies and falling tokens. Enrolling projectiles makes them
   competitors for those six slots.
2. **The sort decides who wins** — higher `logY` first. Whether a bolt should be
   able to displace an enemy is a gameplay question the renderer currently
   answers by accident.
3. **Watch `clipPoolFull` in play**, since the both-edges case is the one that
   can genuinely overflow.
4. **Keep visible and dangerous lifetime consistent**, as the previous audit
   established — clipping extends the *visible* life to Y=246 while
   `ebulletPlayerTick` stops it being dangerous at Y=226. That gap is the
   substance of the collision task and is untouched here.

The single line required is the one this audit used temporarily:
`jmp logClipAnnotate` at the end of `ebulletTick`.

---

## 10. Hygiene and final state

* **All temporary instrumentation removed.** `grep -rn "TEMPORARY AUDIT\|clipUsedMax" src/` returns nothing.
* **Production source restored and proved.** `git status` is empty, and a
  **pristine `HEAD` worktree builds byte-identically** to the current tree
  (`shmup.prg` `14716a49ecb7726b` both ways). My session-start hash differed
  because that first `make build` inherited a `build/` directory left over from
  the previous task; the pristine comparison is the authoritative check.
* **VICE:** every instance launched through the harness with exact PID ownership
  and reaped in a `finally`. No broad `pkill`/`killall`, no user instance
  touched, `-console` throughout. `ps` confirms **none running**.
* **No worktrees left**; `git worktree list` shows only the repository.
* **Disk:** `build/` 340 K (current artefacts only); session scratch 4.3 M,
  disposable. 94 GiB free of 228 GiB.
* **Nothing committed. Nothing pushed.** HEAD is still `c2b658e`.

### Unproven / not covered

* **The boss arena.** Every run ended with `lvlPhase 0` — the stage wraps rather
  than completing (a pre-existing behaviour, consistent with the known
  `test_boss` failures, which I did not investigate or repair). Clip demand
  during the boss fight is therefore **not measured**. The boss sits mid-screen
  rather than at an edge, so it is unlikely to add clip pressure, but I have not
  shown that.
* **Level 2.** All measurements are Level 1. Level 2 authors no turrets, so its
  bottom-edge projectile population should be lower, but it was not measured.
* **Manual visible VICE.** Not performed; this audit is entirely counter-based,
  and every conclusion rests on engine instrumentation rather than on looking at
  the screen.
