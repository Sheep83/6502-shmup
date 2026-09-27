# Enemy projectile aimed-velocity consumption

**Date:** 2026-09-26
**HEAD:** `f45a53d` *Bullet clipping fixed* — working tree clean at start.
**Nothing committed. Nothing pushed.**

---

## 1. The bug is real, and it is one operand

`ebulletTick` consumed the horizontal velocity from the object and the vertical velocity from a **constant**:

```asm
    lda objVX,x          // horizontal: the slot's own velocity
    ...
!vertical:
    lda logY,x
    clc
    adc #EBULLET_VY      // vertical: the CONSTANT, whatever the aim decided
```

`objVY` was written twice on the way in and **never read by anything**. The aimed path computed the slope-matched vertical step, stored it, and the projectile then ignored it.

| question | answer |
|---|---|
| Is `objVX` consumed by movement? | **Yes** — `ebulletTick`, `src/ebullet.asm:424` |
| Is `objVY` consumed? | **No.** There was no `lda objVY` anywhere in `src/` |
| Is `EBULLET_VY` used directly every frame? | **Yes** — `src/ebullet.asm:461` (pre-fix numbering) |
| Intended values | `ebulletAimVY = [3, 3, 2]`, indexed by `|VX|` |
| Purpose of `EBULLET_VY_STEEP` / `ebulletAimVY` | speed normalisation across the aimed arc |

### Every projectile-related writer and reader

| symbol | writers | readers |
|---|---|---|
| `objVX` | `ebullet.asm:328` (straight, 0), `ebulletAim` at `:363/:367/:373/:387`; `objects.asm:166` (alloc zero); `boss.asm:449`; | **`ebulletTick:424`** — consumed |
| `objVY` | `ebullet.asm:304` (spawn, `EBULLET_VY`), `ebullet.asm:324` (from `ebulletAimVY`); `objects.asm:167` (alloc zero); `pickup.asm:341`; `boss.asm:450` | **none, before this fix** |

`pickup.asm` writes `objVY` and moves tokens in its own tick, so it is unaffected either way; `boss.asm` zeroes both on a slot it owns.

### The repo evidence for the intended design

Not inferred — stated twice in the source, at the two places that matter.

At the store, `src/ebullet.asm`:

> *"The vertical step that keeps this slope's speed near the others. |VX| is 0, 1 or 2 and indexes the table directly."*

At the table:

> *"One vertical step per quantised slope, indexed by |VX|. Kept next to ebulletSlope because the two together ARE the trajectory table: **change one and the speeds stop matching**."*

And the table is guarded for shape:

```asm
ebulletAimVY:
    .byte EBULLET_VY, EBULLET_VY, EBULLET_VY_STEEP        // 3, 3, 2
.if (* - ebulletAimVY != EBULLET_VX_MAX + 1) {
    .error "the aimed vertical table is not one entry per quantised slope"
}
```

A table that exists solely to normalise speed, kept deliberately adjacent to the slope table, with a build-time guard on its shape — and nothing reading the value it produces. The intent is unambiguous: **`objVY` is meant to drive vertical movement.**

---

## 2. Measured before the fix

Trajectories measured from **position**, not from the stored byte: a breakpoint on `ebulletTick` (which runs once per frame per projectile, before the move) with consecutive positions of the same slot differenced. Three player positions to reach all three aim buckets; the ship is held still each tick so a bolt cannot change bucket mid-flight.

| `|VX|` | stored `objVY` | measured dY/frame | measured dX/frame | measured px/frame | direction |
|---|---|---|---|---|---|
| 0 (vertical) | 3 | 3.00 | 0.00 | **3.00** | straight down |
| 1 (shallow) | 3 | 3.00 | 1.00 | **3.16** | 18.4° off vertical |
| 2 (steep) | **2** | **3.00** | 2.00 | **3.61** | 33.7° off vertical |

The steep bucket **stores 2 and moves 3**. That is the bug, visible directly in the data: 51 flights across three ship positions, every one of them consistent.

**The earlier audit's 3.61 px/frame figure is confirmed exactly**, as is 3.00 for the vertical. The spread across the arc is `(3.61 − 3.00) / 3.00 = 20.3%`, against a table written to hold it near zero.

### What consuming `objVY` would give instead

| `|VX|` | VY | px/frame | vs vertical |
|---|---|---|---|
| 0 | 3 | 3.00 | — |
| 1 | 3 | 3.16 | +5.4% |
| 2 | 2 | 2.83 | −5.7% |

Spread **11.7%**, and symmetric about the vertical rather than running 20% fast at one end. Not perfect normalisation — see §7 — but that is the authored design.

## 3. Why it is not evident in play

The user's report that this does not show in gameplay is accurate, and the measurements say why:

1. **Only one bucket in three is wrong.** Vertical and shallow shots were already flying at exactly their stored velocity. The defect is confined to `|VX| = 2`.
2. **That bucket needs the player far away.** `ebulletSlope` returns 2 only beyond `EBULLET_AIM_MID` = 72 px of horizontal separation. Close-quarters fire — where a player is watching individual bolts — is bucket 0 or 1 and was always correct.
3. **The error is one pixel per frame.** 3 instead of 2, on a bolt whose whole visible life is roughly 60 frames.
4. **It is a speed error, not a direction error.** The bolt still travels along the correct slope and still arrives where it was aimed; it simply gets there ~21% sooner. There is no visual reference for "this diagonal should be slower", and the aim is not homing, so nothing on screen contradicts it.
5. **Integer motion, no accumulator.** Every step is a whole pixel, so there is no jitter or sub-pixel drift to draw the eye — just a consistently slightly faster diagonal.

The honest summary is that the engine was flying a *plausible* trajectory that was not the *authored* one.

## 4. The existing test could not have caught it

`tests/test_aimed_fire.py` is a real test of the aim path and it passes both before and after this fix — **because every value it reads is identical in both builds.** It samples `objVX` and `objVY`, the stored bytes, and never a position:

```python
seen[s] = (signed(vx[s]), vy[s])
...
check("AIMED: each slope carries its matched vertical step",
      all(EXPECTED_VY[a] == vy for a, vy in pairs), ...)
speeds = sorted({round((a * a + vy * vy) ** 0.5, 2) for a, vy in pairs})
check("AIMED: the diagonal does not outrun the vertical (within 10%)", ...)
```

Its speed check computes `sqrt(vx² + vy²)` **from the stored velocity**, so it certified the normalisation as holding while the projectile flew at a different speed entirely. This is the `AGENTS.md` rule-4 case and the same class as the note already in the project's memory: a green instrument that is measuring the intent rather than the machine.

### A second, independent flaw in that gate

Its `within 10%` threshold **cannot be met by the authored design**. With `EXPECTED_VY = {0: 3, 1: 3, 2: 2}` the stored speeds are 3.00, 3.16 and 2.83 — an 11.7% spread. The check therefore passes only on runs where buckets 1 and 2 are not both observed, which is why it has not fired.

**Left unrepaired**: it is not failing, and repairing it is outside this brief. It is reported here because anyone tightening it should assert the authored speeds exactly rather than pick another threshold — see §6.

---

## 5. The fix

One operand, in `ebulletTick`:

```asm
    lda logY,x
    clc
-   adc #EBULLET_VY
+   adc objVY,x
    bcs ebulletRetire                   // wrapped: definitely below the screen
```

Nothing else changed. X semantics, the nine-bit horizontal path, the retirement tests, `EBULLET_Y_MAX`, the bottom clipping call, collision, the aim buckets, `ebulletSlope`, `ebulletAimVY` and the artwork are all untouched. No fractional motion was introduced and no speed was rebalanced — the engine now flies the numbers it was already calculating.

### The domain was established before the add was changed

`adc` on a memory operand is only safe here because a projectile's `objVY` is provably narrow:

* **Never zero** — `ebulletSpawn` writes `EBULLET_VY` (3) *before* `objectActivate`, and the aimed path can only overwrite it from `ebulletAimVY`, whose entries are 3, 3, 2. A zero would mean a bolt that hangs in the air forever.
* **Never negative** — so the carry out of this add still means exactly one thing, "the position wrapped past 255, the bolt is below the screen", and `bcs ebulletRetire` keeps its meaning. A signed step would break that test, not just the add.
* **Only 2 or 3** in the shipped build.

This is recorded in the source comment, together with the note that a future upward-travelling projectile must revisit the add **and** the retirement test as a pair.

### Cost

`adc #imm` (2 cycles) became `adc abs,x` (4). Two cycles per projectile per frame, `EBULLET_MAX` is 3, so **at most 6 cycles a frame** out of 19,656. No memory.

## 6. The new test

`tests/test_aimed_velocity.py` — **it measures position.**

It breaks on `ebulletTick`, which runs once per frame per projectile before the move, and differences consecutive positions of the same slot: an observed displacement, never an inferred one. Flights are split where a slot is reused or its slope changes. Three ship positions (32, 150, 300) reach all three buckets; the ship is re-held every tick so a bolt cannot change bucket mid-flight. Nothing is poked but the player's X and the wave definitions' firing mode, both ordinary authored state.

**It was written and run BEFORE the fix, and failed:**

```
ok   bolts were observed in flight -- 51 flights of 3+ ticks
ok   every quantised slope was exercised -- buckets seen [0, 1, 2]
FAIL VERTICAL: every frame advances by the slope's OWN stored objVY, not a constant
     -- 1278 frames disagreed, e.g. |VX|=2 stored VY=2 but moved 3
ok   HORIZONTAL: every frame advances by |objVX| -- ok
ok   |VX|=0: measured vertical step is the authored 3 -- 2 flights, steps seen [3]
ok   |VX|=1: measured vertical step is the authored 3 -- 11 flights, steps seen [3]
FAIL |VX|=2: measured vertical step is the authored 2 -- 38 flights, steps seen [3]
```

It is discriminating, not merely red: the horizontal claim and both correct buckets passed while only the defective bucket failed.

### One correction made to this file, and why it matters

A first draft asserted *"MEASURED speeds are normalised across the arc (within 10%)"*, a threshold lifted from `test_aimed_fire.py`. **The authored design does not meet it** — `[3,3,2]` spreads 11.7% — so after the fix the test still failed, on a gate I had invented rather than on the engine.

The obvious way to make that gate green would have been to change `EBULLET_VY_STEEP` or the table, i.e. to rebalance gameplay to satisfy a number of my own. The brief forbids exactly that, so the **threshold** was removed instead. Each bucket is now asserted to fly at `hypot(|VX|, ebulletAimVY[|VX|])` exactly, and the 11.7% arc is *printed as a note*, a design value for a human to judge:

```python
check(f"|VX|={a}: MEASURED speed is the authored hypot({a},{EXPECTED_VY[a]}) ...",
      abs(measured - want) < 0.005, ...)
```

---

## 7. Measured after the fix — the before/after proof

`tests/test_aimed_velocity.py`, **ALL PASS**:

```
ok   VERTICAL: every frame advances by the slope's OWN stored objVY, not a constant
ok   HORIZONTAL: every frame advances by |objVX|
ok   |VX|=0: measured vertical step is the authored 3 -- 2 flights, steps seen [3]
ok   |VX|=1: measured vertical step is the authored 3 -- 9 flights, steps seen [3]
ok   |VX|=2: measured vertical step is the authored 2 -- 28 flights, steps seen [2]
ok   |VX|=0: MEASURED speed is the authored hypot(0,3) = 3.00 px/frame -- measured 3.00
ok   |VX|=1: MEASURED speed is the authored hypot(1,3) = 3.16 px/frame -- measured 3.16
ok   |VX|=2: MEASURED speed is the authored hypot(2,2) = 2.83 px/frame -- measured 2.83

  note: the authored arc spans 2.83..3.16 px/frame (11.7% spread)
```

### Before / after, per aim bucket

| `|VX|` | stored `objVY` | dY/frame **before** | dY/frame **after** | px/frame **before** | px/frame **after** | changed? |
|---|---|---|---|---|---|---|
| 0 — vertical | 3 | 3.00 | 3.00 | 3.00 | 3.00 | **no** |
| 1 — shallow | 3 | 3.00 | 3.00 | 3.16 | 3.16 | **no** |
| 2 — steep | 2 | **3.00** | **2.00** | **3.61** | **2.83** | **yes** |
| arc spread | — | — | — | **20.3%** | **11.7%** | |

**Straight and shallow shots are unchanged in behaviour** — identical stored values, identical measured motion. Only the steepest bucket moves, which is precisely the bucket the audit predicted and the reason the defect was invisible in play.

The proof that movement now consumes the intended state is the per-frame equality itself: for every flight in every bucket, `dY == objVY` for that slot, measured 0 disagreements against 1278 before.

## 8. Regressions, and baseline failures kept separate

Every failing suite was re-run against the **pristine `ebullet.asm`** under a shell trap, so "pre-existing" is measured rather than asserted.

### Passed with the fix in place

| suite | result | why it matters here |
|---|---|---|
| **`test_ebullet_clipping`** | **ALL PASS** | the accepted bottom-clipping fix is undisturbed — and this is a real check, not a formality: a slower steep bolt reaches the clip boundary later and spends more frames straddling it |
| `test_aimed_fire` | ALL PASS | the stored-value test still agrees; the aim path itself is unchanged |
| `test_pickup` | ALL PASS | `pickup.asm` is the other `objVY` writer; tokens are unaffected |
| `test_lifecycle` | ALL PASS | retirement and object lifetime |
| `test_boot` | ALL PASS | |

### Pre-existing failures — identical on both builds

| suite | pristine | with fix | verdict |
|---|---|---|---|
| `test_enemy_fire` | 2 (fire mask; director spawning) | 2, same | **pre-existing** |
| `test_flight_paths` | 3 (patterns in flight; `publishSkip`; `schedBuildDefer`) | 3, same | **pre-existing** |
| `test_ingress_egress` | 3 (materialise inside playfield; `publishSkip`; `schedBuildDefer`) | 3, same | **pre-existing** |
| `test_production` | 2 (`publishSkip`; `stageTopRow`/`worldProgress 775`) | 2, same | **pre-existing** |
| `test_clip_scratch` | `KeyError: 'sonicRingFrames'` | same | **pre-existing** — a stale symbol in the test, not a build failure |

None repaired: outside this brief.

**One measurement error of my own, recorded:** the first A/B pass printed *nothing* for `test_enemy_fire` on the pristine build, because of a `sed` filter in my own command. An empty result is not a pass, so it was re-run with full output — twice — and gave the same 2 failures both times. Had it been taken at face value it would have read as "the fix introduced 2 failures".

---

## 9. Manual feel — what to look for, and what NOT to do about it

The user's report that the discrepancy is not evident in play is treated here as evidence, and the measurements agree with it: two of the three aim buckets did not change at all.

**What changed, precisely:** a bolt fired at a player more than 72 px away horizontally now descends at 2 px/frame instead of 3, while still moving 2 px/frame sideways. It takes about **21% longer** to cross the playfield and travels a visibly flatter, more deliberate diagonal.

To compare:

1. Park the ship near one edge and let an enemy on the far side fire — that is the only bucket that changed. Watch the bolt's descent rate against a bolt fired by an enemy directly overhead; they should now look like the same projectile travelling in two directions, which is what `ebulletAimVY` is for.
2. Close-quarters fire should feel **identical**. If it does not, something other than this change is responsible.
3. Dodgeability at long range is the thing most likely to feel different: a slower steep bolt is on screen longer and is easier to read, but also lingers in the lane.
4. Normal speed, non-warp, per `AGENTS.md` rule 2.

**If it feels wrong, do not undo this fix to correct it.** The engine is now doing what the trajectory table says. If the steep bolt is too slow, the value to change is `EBULLET_VY_STEEP`, deliberately, with the table's comment in view — a gameplay tuning decision, made explicitly, and not the same question as whether movement consumes the velocity it calculated. **Reported here rather than pre-empted.**

## 10. Files changed

| file | change |
|---|---|
| `src/ebullet.asm` | `ebulletTick`: `adc #EBULLET_VY` → `adc objVY,x`, plus the comment recording the measurement and the signed/zero domain argument |
| `tests/test_aimed_velocity.py` | **new** — measures displacement per frame per aim bucket; fails on the bug, passes only when movement consumes `objVY` |

No other file was touched. `src/renderer.asm`, `src/clip.asm`, the projectile artwork, the aim tables and every geometry constant are unchanged.

## 11. Status and hygiene

**Nothing committed. Nothing pushed.** HEAD remains `f45a53d`.

```
 M src/ebullet.asm
?? tests/test_aimed_velocity.py
?? reports/enemy-projectile-velocity-consumption.md
```

* Every VICE instance was launched and reaped by the harness by exact PID, visible as `[vice] launched pid N` / `[vice] reaped pid N` in each run above. **No `pkill`, no `killall`**, no user session touched, `-console` throughout so nothing took focus.
* Each A/B swap restored `src/ebullet.asm` under a shell `trap` and verified the restore by grepping the patched line back (`adc objVY,x`, line 487).
* The monitor traps from earlier audits were respected: `z` single-steps an instruction and does not advance a frame, so per-frame sampling is done from a breakpoint on `ebulletTick`; and the schedule's current/next buffer ownership was not relied on at all here, since this measurement reads object state rather than the published schedule.
* All probes live in the session scratchpad; none in the repo.
