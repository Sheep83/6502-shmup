# 19656 — Bottom-Edge Enemy Projectile Clipping

**Implemented. A hostile bolt now travels to the floor of the playfield instead of vanishing fourteen rasters above it, and it remains dangerous for exactly as long as it remains visible — at both edges.**

**Two source files changed, 21 focused checks passing, `MAX_SPRITE_Y` and `CLIP_POOL_SLOTS` untouched, nothing committed.**

---

## 1. What changed, in three numbers

| | old | new |
|---|---|---|
| **Rendering** — drawn while | `logY <= 226` | **`logY <= 246`** |
| **Collision** — dangerous while | `55 <= logY <= 226` | **`49 <= logY <= 246`** |
| **Retirement** — freed at | `logY >= 250` | **`logY >= 247`** |

Measured on a real bolt, frame by frame:

```
   logY  clip  presY  ptr    ink rasters
    223     0    223  $db   223..229
    226     0    226  $db   226..232      <- the old last visible frame
    229    -3    226  $0d   229..235
    232    -6    226  $c7   232..238
    235    -9    226  $0d   235..241
    238   -12    226  $c7   238..244
    241   -15    226  $0d   241..246
    244   -18    226  $c7   244..246      <- the new last visible frame
```

**Old:** the bolt disappeared with rasters 233..246 of playfield still beneath
it — the ~14 rasters the despawn audit measured. **New:** its ink reaches 246,
the lowest raster any sprite in this engine can draw.

---

## 2. Facts verified against current source

Every "established fact" in the brief was checked rather than assumed:

| | |
|---|---|
| Aperture | rasters **55..247** (`TOP_SPLIT_LINE` 55, `BOT_SPLIT_LINE` 248) ✓ |
| `MAX_SPRITE_Y = 226` | ✓ and its reason: it is the largest Y leaving lines 247/248 free of sprite DMA, which is the bottom split's entire margin |
| `SPRITE_HEIGHT = 21`, sprite at 226 covers 226..246 | ✓ |
| The bolt inks rows 0..6 | ✓ **verified from the bitmap in memory**, not from the art source — `tests/test_ebullet_clipping.py` reads `$36c0` and asserts rows 7..20 are blank |
| Rejected past 226 by both the builder and the collision gate | ✓ |
| Alive to ~250 | ✓ `EBULLET_Y_MAX` was 250 |
| `clip.asm` is generic | ✓ `logClipAnnotate` reads `logY,x` and writes `logClip,x` with nothing type-specific in it |
| Enemies and tokens already enrol | ✓ `src/enemy.asm`, `src/pickup.asm:424` |

---

## 3. Rendering: how projectiles enter the clipping path

**One `jmp logClipAnnotate` at the end of `ebulletTick`** — the same call
`src/pickup.asm` makes, in the same tail-call form, after the vertical step and
after the retirement test.

```asm
    sta logY,x
    cmp #EBULLET_Y_MAX
    bcs ebulletRetire
    ...
    jmp logClipAnnotate                 // X preserved; its rts is ours
```

No projectile-specific bitmap shifter was written, the artwork was not moved
within the sprite, and the renderer, multiplexer, raster split, `MAX_SPRITE_Y`
and `CLIP_POOL_SLOTS` are all untouched.

### Logical Y remains truthful

`logClipAnnotate` writes **only** `logClip`. `logY` is never modified for
rendering — movement, the collision test and retirement all keep reading the
real position. Confirmed by the trace above: `logY` walks 226 → 229 → … → 244
while the presented Y sits at 226 throughout.

### `logClip` lifecycle

* **Spawn** — `objectAlloc` calls `objectZeroSlot`, which clears `logClip`, so a
  slot inherited from a clipped enemy cannot hand a fresh bolt a clamped Y.
* **Every frame** — `logClipAnnotate` rewrites it from the current `logY`,
  writing **0** whenever the bolt is wholly inside the band.
* **Retire** — `objectFree` calls `objectZeroSlot` again.

### In-band bolts are unaffected

Measured across 122 distinct in-band logical Y values: `logClip` was **always
0**, the entry took the ordinary admission path, and the published sprite
pointer stayed the canonical `$db`. No bitmap substitution, no clip block.

### Presented Y and DMA safety

A bottom-clipped sprite presents at **exactly `MAX_SPRITE_Y`**, so its DMA
footprint is identical to any other sprite at 226 and lines 247/248 stay free.
This is not an assumption — the test asserts that every published entry, of
every type, lies within 55..226, and that a clipped bolt's presented Y is
exactly 226. Both hold across 2,200 frames.

### Scratch blocks

The trace shows the pointer alternating `$0d` / `$c7` — `$0340` (pool 0 slot 0)
and `$31c0` (pool 1 slot 0). That is the double buffer working as designed: the
block travels with its schedule and the builder writes the other pool.

---

## 4. Collision: the geometry, and why the box needed no change

The old gate reused the renderer's admission band as a lethality test. That was
correct only while admission was all-or-nothing. It is not any more.

The new gate is **the reach of the ink**:

```asm
.const EBULLET_INK_ROWS  = 7                                    // rows 0..6
.const EBULLET_INK_Y_MAX = MAX_SPRITE_Y + SPRITE_HEIGHT - 1     // 246
.const EBULLET_INK_Y_MIN = MIN_SPRITE_Y - (EBULLET_INK_ROWS - 1) // 49
```

* **246** because `clip.asm` fills block row `r` from source row `r - c` and the
  block ends at row 20 — so source row 0 is the last thing drawable, at raster
  `MAX_SPRITE_Y + 20`.
* **49** because the bolt's *last* inked row is row 6, so the first logical Y at
  which any ink is inside the aperture is `55 - 6`.

### The `EBULLET_HIT_*` box is unchanged, and that is a result rather than an omission

I inspected it as the brief asks. `EBULLET_HIT_UP = 8`, `EBULLET_HIT_DOWN = 21`,
giving `bulletY - plyY` in `-7..20`.

**`PLAYER_MAX_Y` is `MAX_SPRITE_Y` = 226** (the renderer asserts the two are
equal). So the player's twenty-one rows reach at most raster **246** — which is
exactly the lowest raster the clipper can draw.

> **Every ink row the clipper drops is a row the player can never be standing
> on.** "Visible overlap" and "box overlap" are therefore the same test, and no
> per-row visibility arithmetic is needed. This is the reason the change is a
> two-constant gate and not a new collision model.

Checked at the boundary:

| bolt `logY` | ship `plyY` | geometry | result |
|---|---|---|---|
| 246 | 226 | bolt's only drawn row is 246; ship's last row is 246 | **hit** |
| 246 | 225 | ship's last row is 245, below the bolt's only drawn row | no hit |
| 247 | 226 | no ink drawn at all | no hit |
| 49 | 55 | bolt's row 6 lands on the ship's first row | **hit** |
| 48 | 55 | bolt's last ink row is 54, above the aperture | no hit |

All five measured by calling `ebulletPlayerTick` directly — see §6.

### The top edge

Enrolling bolts in clipping means a bolt can now be *drawn* above `MIN_SPRITE_Y`
as well as below `MAX_SPRITE_Y`. A turret muzzle is `turretLogY + 12` and an
enemy muzzle is `enemyY + 18`, and enemies fire while top-clipped, so a bolt at
`logY` 52 is reachable.

**Had I extended only the bottom bound, I would have created newly-visible,
newly-harmless pixels at the top** — the same inconsistency this task exists to
remove, mirrored. So the lower bound moved from 55 to 49 for the same reason the
upper one moved from 226 to 246: it is where the ink is.

### One pre-existing asymmetry, left alone

`EBULLET_HIT_UP = 8` treats the bolt as 8 rows tall where the ink is 7 — one row
generous *upward*. It is pre-existing, it is not at the edge this task concerns,
and narrowing it would change in-band collision feel. Recorded, not changed.

---

## 5. Retirement

`EBULLET_Y_MAX` is now **derived, not chosen**:

```asm
.const EBULLET_Y_MAX = EBULLET_INK_Y_MAX + 1        // 247
```

One row past the last row at which anything is drawn. The previous 250 left the
bolt alive and invisible for four more logical rows — the "invisible tail" the
despawn audit found — and there is now nothing to see and nothing to hit past
246, so there is nothing left to be.

A build-time guard keeps retirement inside the clipper's reach:

```asm
.if (EBULLET_Y_MAX > MAX_SPRITE_Y + SPRITE_HEIGHT) {
    .error "a bolt would outlive the reach of the bottom clip"
}
```

Because `EBULLET_VY` is 3, a bolt in practice steps …241, 244, 247 → retires; its
last drawn frame is 244 with ink at 244..246.

**A stale cross-reference was corrected.** `PICKUP_Y_MAX` (250) carried a comment
saying it was "chosen to match the projectile's own `EBULLET_Y_MAX`". That is no
longer true, so the comment now says so. `PICKUP_Y_MAX` itself is unchanged —
re-deriving it is not this change's business.

---

## 6. Tests

`tests/test_ebullet_clipping.py` — **21 checks, all passing.**

Two measurement traps, both inherited from the preceding audits and both
designed around explicitly:

* **The published schedule lags a frame.** Every schedule assertion is made
  against the entry's own `logId` and the Y that entry carries, never against
  the live logical Y of the same frame.
* **Every monitor command halts the machine.** Frame stepping is `step_n` on the
  `gameFrame` breakpoint throughout; nothing free-runs and then reads.

The collision cases call **`ebulletPlayerTick` directly through a trampoline**
(`jsr … / jmp *`, so the `rts` has somewhere legitimate to go). That is
deliberate: letting the frame run would retire the bolt at 247 *before* the rule
saw it, so the upper bound could not be tested at all.

```
ok   the bolt inks exactly the first seven of its twenty-one rows -- [0,1,2,3,4,5,6]
ok   an in-band bolt is never clipped and never gets a scratch bitmap -- 122 Y values
ok   a bolt past Y=226 is annotated for BOTTOM clipping -- clip -1 .. -20
ok   ...and its clip is exactly how far past the edge it is
ok   ...and it is still in the published schedule below Y=226 -- deepest 246
ok   every published entry stays inside the safe band 55..226 -- 0 outside
ok   a clipped bolt presents at exactly MAX_SPRITE_Y
ok   a bolt now lives to the last row its ink can be drawn on -- 246
ok   ...and never past it: retirement is one row later -- 246 < 247
ok   a clipped bolt is published with a scratch pointer, not the canonical bitmap
ok   bolt Y=200, ship Y=195 -> HIT   (ordinary in-band overlap)
ok   bolt Y=246, ship Y=226 -> HIT   (last drawn row IS the ship's last row)
ok   bolt Y=246, ship Y=225 -> no hit
ok   bolt Y=247, ship Y=226 -> no hit (invisible cannot hit)
ok   bolt Y=49,  ship Y=55  -> HIT   (top edge: ink row 6 on the ship's first row)
ok   bolt Y=48,  ship Y=55  -> no hit
ok   the stress scenario really did hold bolts in the clip band
ok   CLIP POOL: no clipped entry was ever refused -- clipPoolFull 0
ok   SCHEDULE: no overflow and no unsafe-spacing rejection
ok   RASTER: the top and bottom splits both stayed on time -- edgeLate 0, scrollLate 0
```

Mapping to the brief's ten required behaviours: 1 → in-band check; 2 → clipped
and scheduled past 226; 3 → band assertion; 4 → deepest 246 and the descent
trace; 5 → the two HIT cases; 6 and 7 → `Y=247` and `Y=48`; 8 → retirement at
247; 9 → the stress section; 10 → the raster section.

### Clip pool and same-Y mux

The stress audit's validated worst case — all `EBULLET_MAX` bolts held in the
bottom clip band while the authored waves run, so bottom-diving enemies compete
for the same six same-Y slots — over 700 frames:

```
clipPoolFull 0     statOverflow 0     statRejUnsafe 0
```

**No clipped entry was ever refused.** This matches the audit's prediction: the
six same-Y mux slots refuse a seventh bottom-clipped entry before the pool is
consulted, so bottom-edge pressure alone cannot exhaust it. The pool was not
enlarged and no priority policy was introduced; the builder's existing
true-Y ordering decides who gets a slot, exactly as before.

### Raster

`edgeLate 0`, `scrollLate 0` in the stress run and every undisturbed run.
Presented Y never exceeds 226, so the bottom split's DMA margin is preserved by
construction and measured to be. **No raster timing code was touched.**

`gameOverrun` is excluded from the assertion in the stress section only, and the
test says why: that scenario pokes objects through the monitor every frame,
which halts and resumes the CPU and inflates it. The raster counters are not
affected that way.

---

## 7. Baseline failures — separated, and one investigated properly

| Test | result | attribution |
|---|---|---|
| `test_ebullet_clipping.py` | **21/21** | new |
| `test_boot`, `test_campaign`, `test_level_identity`, `test_turret_arming`, `test_aimed_fire`, `test_player_death`, `test_pickup` | pass | — |
| `test_production` | 1–2 FAIL | pre-existing (`stageTopRow` constant stale; `publishSkip` flaky) |
| `test_enemy_fire` | 1 FAIL | pre-existing |
| `test_level_assets`, `test_encounter_director`, `test_player_ship`, `test_sfx`, `test_boss`, `test_heat_cadence` | 3 / 4 / 2 / 5 / 17 / 10 FAIL | pre-existing, unchanged |
| `test_turret_regression` | 2 FAIL in batch, **0 in isolation** | known flaky |
| `test_lifecycle` | 10 FAIL on the first run after a build, 0 on the second | **investigated — not mine** |

`test_lifecycle` looked like a regression, so I checked it rather than assuming.
Stashing my change and rebuilding gives the **identical pattern** — 10 FAIL then
0 FAIL — with and without it:

```
--- WITHOUT my change (HEAD) ---    run 1: 10 FAIL    run 2: 0 FAIL
--- WITH my change ---              run 1: 10 FAIL    run 2: 0 FAIL
```

It is flaky on the first run after a build, in both trees. Not caused by this
work, and not repaired here.

---

## 8. Manual VICE

**I could not perform the visual check**, and it remains yours. Judging "does
the bolt now travel to the floor" means watching it, and a visible VICE would
steal focus, which the standing constraints forbid.

The nearest substitute is the frame-by-frame descent in §1, which is the same
information a recording would carry: logical Y, the clip annotation, the
presented Y and the published sprite pointer, for every frame of one bolt's life
from mid-screen to retirement.

**What to look for, and what the automated evidence already says about each:**

| | evidence so far |
|---|---|
| a missing bolt travels to the bottom edge and disappears there | ink now reaches raster 246 vs 232 before |
| clipped enemies still disappear correctly | `clipPoolFull 0`, no change to their path |
| sprite corruption from scratch reuse | pointers alternate `$0d`/`$c7` across the two pools, as designed |
| flicker at Y=226 | every clipped entry presents at exactly 226; `statRejUnsafe 0` |
| disturbance to the bottom split | `edgeLate 0`, presented Y never above 226 |
| recurrence of the top-border shimmer | `edgeLate 0`, `scrollLate 0`; no raster code touched |

**MiSTer/CRT remains the final hardware check.** The bottom split's margin is the
thing to watch there, since this change puts sprites at Y=226 more often than
before — though never lower, and never more than the six the mux already allowed.

---

## 9. Out of scope, and confirmed untouched

* **The `objVY` movement bug is unchanged.** The clip-pool audit found that
  `ebulletTick` advances a bolt by the constant `#EBULLET_VY` and that nothing
  reads `objVY` for motion, so the aimed-fire speed-matching table is inert.
  `EBULLET_VY_STEEP` and `ebulletAimVY` are exactly as they were, and the
  descent trace above shows the uniform 3 px/frame that implies. Fixing it here
  would have changed bolt speed and made this change impossible to evaluate on
  its own.
* Renderer, multiplexer, raster split, `MAX_SPRITE_Y`, `CLIP_POOL_SLOTS`,
  clipping priority: **none altered**.

---

## 10. Files changed and final state

| file | change |
|---|---|
| `src/ebullet.asm` | `EBULLET_INK_ROWS` / `_INK_Y_MIN` / `_INK_Y_MAX` added and `EBULLET_Y_MAX` derived; `jmp logClipAnnotate` in `ebulletTick`; the collision gate's two bounds |
| `src/pickup.asm` | one stale comment corrected; no code change |
| `tests/test_ebullet_clipping.py` | new, 21 checks |

Symbols affected: `EBULLET_Y_MAX` (250 → 247), new `EBULLET_INK_ROWS`,
`EBULLET_INK_Y_MIN`, `EBULLET_INK_Y_MAX`. No symbol was removed or renamed.

```
 M src/ebullet.asm
 M src/pickup.asm
?? reports/enemy-projectile-clip-pool-stress-audit.md
?? reports/enemy-projectile-bottom-clipping.md
?? tests/test_ebullet_clipping.py
```

* **Nothing committed. Nothing pushed.** HEAD is still `c2b658e`.
* VICE: every instance launched through the harness with exact PID ownership and
  reaped in a `finally`; no broad `pkill`/`killall`, no user instance touched,
  `-console` throughout. `ps` confirms **none running**.
* No worktrees left. `build/` 340 K, current artefacts only. 94 GiB free of
  228 GiB.
