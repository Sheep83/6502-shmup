# Enemy projectile early-despawn audit

**Date:** 2026-09-26
**HEAD:** `8795c39` *Upgrade shop to level transition added.*
**Working tree at start:** `src/renderer.asm` modified (the top-border raster fix, uncommitted) plus its report. **Both left untouched by this audit.**
**No code was changed by this task. Nothing committed. Nothing pushed.**

---

## 1. Answer first

The projectile is **not being killed early, not clipped, and not starved of a hardware sprite.** It is **hidden**: it stops being submitted to the renderer, and stops being able to hit the player, at the same coordinate — and then goes on living, invisibly, for another 24 rasters before it is freed.

| transition | Y | enforced in |
|---|---|---|
| stops being **drawn** | `logY > 226` (`MAX_SPRITE_Y`) | `buildSchedule`, `src/renderer.asm:732-734` |
| stops being **dangerous** | `logY > 226` (`MAX_SPRITE_Y`) | `ebulletPlayerTick`, `src/ebullet.asm:491-493` |
| is **freed** | `logY >= 250` (`EBULLET_Y_MAX`) | `ebulletRetire`, `src/ebullet.asm:431` |

**And the cutoff constant is not wrong.** `MAX_SPRITE_Y = 226` is correct, deliberate, and rests on two independent derivations that both still hold. The early *appearance* of the disappearance comes from somewhere else entirely:

> **The bolt inks only rows 0..6 of a 21-row sprite.** The admission ceiling is sized for the full 21-row DMA footprint — correctly — so at the last drawn position the ink sits on rasters 227..233 while the playfield runs to 247. **The bolt vanishes 14 rasters above the floor**, which is about 1.75 character rows, and that is exactly what the player is seeing.

Nothing is broken. The bound is right for the sprite the VIC fetches; it is 14 rasters too high for the sprite the player sees.

## 2. Screen geometry, traced rather than inferred

| quantity | value | source |
|---|---|---|
| playfield (aperture) | rasters **55..247** | `TOP_SPLIT_LINE`=55, `BOT_SPLIT_LINE`=248, `src/main.asm:197-205` |
| sprite raster mapping | Y=n displays rasters **n+1 .. n+21** | measured; `reports/fable-vertical-sprite-clipping-review.md` §1, and `MAX_SPRITE_Y + SPRITE_HEIGHT is 247` at `renderer.asm:1085` |
| `SPRITE_HEIGHT` (DMA rows) | **21** | `renderer.asm:141` |
| admission band | **55..226**, Y only, reject never clamp | `MIN_SPRITE_Y`/`MAX_SPRITE_Y`, `renderer.asm:169-170` |
| a full-height sprite at Y=226 | rasters **227..247** — exactly the aperture floor | derived |
| **projectile ink** | **rows 0..6 only**; rows 7..20 are `$00` | `src/generated_sprites/ebullet_art.asm` |
| **projectile ink at Y=226** | rasters **227..233** | derived |
| **unused playfield below it** | **234..247 — 14 rasters** | derived |
| projectile speed | 3 px/frame downward | `EBULLET_VY`, `ebullet.asm:29` |
| projectile cap | 3 concurrent | `EBULLET_MAX`, `ebullet.asm:28` |
| player Y range | 55..226, asserted equal to the mux band | `renderer.asm:179-180` |

The bitmap is the whole story:

```
.byte $14, $00, $00     <- row 0   ink
.byte $69, $00, $00        rows 1..5 ink
.byte $14, $00, $00     <- row 6   ink
.byte $00, $00, $00     <- rows 7..20, fourteen blank rows
```

---

## 3. The lifecycle, end to end

| # | stage | where | Y behaviour |
|---|---|---|---|
| 1 | spawn | `ebulletSpawn` (`ebullet.asm`), from turrets and from enemies | at the firer's position, inside the band |
| 2 | initial X/Y, velocity | `EBULLET_VY = 3` down; X slope quantised into three aim buckets (`EBULLET_AIM_NEAR` 24, `EBULLET_AIM_MID` 72), `EBULLET_VX_MAX = 2` | — |
| 3 | per-frame movement | `ebulletTick`, main thread via `objectUpdateAll` | `logY += 3` |
| 4 | logical alive/dead | `logActive` + `objType == TYPE_EBULLET` | alive until step 9 |
| 5 | **renderer admission** | `buildSchedule` Y test, **before** capacity or reuse | **rejected when `logY > 226`** |
| 6 | hardware sprite assignment | never reached once rejected at step 5 | — |
| 7 | **collision eligibility** | `ebulletPlayerTick` band gate | **refused when `logY > 226`** |
| 8 | clipping | `logClip` is **hardcoded zero for projectiles** | never clipped, either edge |
| 9 | despawn | `ebulletRetire` — the single exit | `logY >= 250`, X out of 8..345, or on hitting the player |

Between **227 and 249** the projectile is alive, moving, and invisible to both the renderer and the collision test. That stretch is deliberate and documented:

> *"Vertical despawn. Wider than the renderable band on purpose: a projectile may fly on below the aperture undrawn, but it stops being able to hit the player there -- see ebulletPlayerTick."*

### Why drawn and dangerous are the same number

This is stated as a rule, not a coincidence, and any change must honour it:

> *"ONLY INSIDE THE RENDERABLE BAND, MIN_SPRITE_Y..MAX_SPRITE_Y. A projectile the builder would reject on Y is not drawn, and something the player cannot see must not be able to kill them. This band must therefore stay the same one buildSchedule admits on."*

## 4. Measured on the machine

VICE, warp, `boot="exact"`, sampling real elapsed time; every instance launched and reaped by PID.

**Retirement coordinate** — breakpoint on `ebulletRetire`, reading `logY[X]`:

```
  logY at retirement: 214 (x6), 217 (x3), 250 (x6), 252 (x3), 0 (x3)
```

* **250 / 252** — the vertical bound. It overshoots 250 by up to two because the test is applied after `logY += 3`, so the first value `>= 250` can be 250, 251 or 252.
* **214 / 217** — player hits, not the vertical bound. These retire early and correctly.
* **0** — retirement called on a slot already free, which `ebulletRetire` documents as safe and guards against.

**Admission** — the published schedule (`schedY[schedCurrent]`) against live projectiles:

```
  in-band projectile samples: 16
  matched to a schedule entry: 16   (100%)
  highest Y ever written into the published schedule: 216   (ceiling 226)
  highest projectile logY seen alive:                 247   (bound 250)
```

Projectiles **are** submitted throughout the band, and **are** alive well past it — seen at Y=247, twenty-one rasters below the last Y at which anything is drawn. The schedule never carried a Y above the ceiling.

### Two instrument errors worth recording

Both produced confident, wrong numbers before being caught, which is the `AGENTS.md` rule-4 hazard in miniature:

1. A first probe stepped with the monitor's `z`, which advances **one instruction**, not one frame — so it never advanced time and reported "no projectile observed". That was the instrument, not the engine.
2. A second probe matched a live bullet's `logY` against the published schedule and reported **0% submitted even inside the band**. The builder writes `schedNext` and the swap happens at the frame IRQ, so `schedCurrent` always describes the **previous** frame's logical state — and a bullet moves 3 px per frame. The equality test was off by exactly `EBULLET_VY`. Matching on `logY` **or** `logY - 3` gives 16/16.

The figures above are from the corrected instrument, validated in the same samples.

---

## 5. Was the cutoff intentional? — documented intent, not inference

**Yes, and on two independent derivations, both of which still hold.** This is documented intent; where I am inferring, I say so.

### Derivation 1 — the aperture floor (visual)

`MAX_SPRITE_Y + SPRITE_HEIGHT = 226 + 21 = 247`, and 247 is `APERTURE_BOT_RASTER`. 226 is precisely the largest Y at which a full-height sprite's last row lands on the last row of the playfield. `renderer.asm:1085-1087` guards the arithmetic explicitly, and says so:

> *"MAX_SPRITE_Y + SPRITE_HEIGHT is 247 so this cannot fire today -- it is here so that raising MAX_SPRITE_Y cannot silently wrap into a false 'the slot is already free'"*

### Derivation 2 — the bottom aperture split (raster timing)

> *"At line 248 the charset switches to blank... The write must beat line 248's first g-access in cycle 15. Line 248 can never be a badline... so the only thing that can steal cycles 0..9 is sprite DMA for slots 3..7, which needs a sprite still active there -- **Y >= 228**. That is exactly what MAX_SPRITE_Y = 226 forbids at admission, and botSplitMin/Max below is the standing proof that it never happens."*

Note this derivation's own limit is **227**, one raster below the constant. The binding number is 226 because derivation 1 is tighter. Both are live constraints, and `renderer.asm:179-180` asserts the player's bounds against the same pair so the two cannot drift.

### The projectile's own bound

`EBULLET_Y_MAX = 250` is separately and deliberately chosen to sit **below** the renderable band, with the reason given in the comment quoted in §3. It is not a stale value and it is not the cause of the complaint — the projectile is already invisible for 24 rasters before it reaches 250.

### What the evidence does NOT show

* No comment, report or commit message anywhere treats the projectile's disappearance point as a **deliberate gameplay decision**. It is a consequence of the shared mux band, never a projectile-specific choice.
* Nothing describes it as temporary or conservative-pending-review.
* Nothing indicates it was inherited from an older screen layout. `MAX_SPRITE_Y` has been reworked as recently as `7730b6b` and `2ff3b80` ("border sprite clipping"), both of which sharpened it rather than leaving it behind.

**Inference, stated as such:** that the 14-raster visual shortfall was simply never noticed. Every derivation of the band reasons about a 21-row body; nothing reasons about a sprite whose ink is 7 rows tall, and the projectile is the only such sprite in the game.

## 6. The mechanism that would fix it already exists — and excludes projectiles

`src/clip.asm` renders vertically clipped bitmaps into schedule-owned scratch blocks: the sprite's **physical Y is pinned at the boundary** and its **pixels are shifted instead**, so every visible row still lands on the raster the object's true position demands.

> *"To let an enemy cross an edge smoothly, its PHYSICAL Y is pinned at the boundary and its PIXELS are shifted instead... Logical Y is never touched: movement, collision, paths, lifecycle and diagnostics all keep reading the truth."*

**This costs nothing in raster timing**, which is the decisive point: the presented Y is always clamped into 55..226, so sprite DMA never reaches line 247 or 248 and the bottom split's margin is untouched. The top-border fix just verified on MiSTer is likewise unaffected — clipping changes bitmaps, not the split.

The annotator is already generic and already shared:

> *"IT IS SHARED, AND THE LABEL IS WHY. enemyTick falls straight into this, but src/pickup.asm calls it: a token is clipped by exactly the same rule and through exactly the same schedule-owned scratch... **Nothing in here is enemy-specific -- it reads logY and writes logClip.**"*

Projectiles simply never call it. The builder records the exclusion as a fact, with no reason attached:

> *"logClip is zero for everything that is not a clipped enemy -- ordinary enemies, **projectiles, all of it** -- so this costs them a load and a branch and changes nothing they do."*

So the shortfall is an **omission**, not a constraint: projectiles would be the third caller of a routine written to be shared.

---

## 7. What extending the lifetime would actually cost

Assessed, not implemented. This is where the audit stops, and §8 says why.

| dimension | effect of enrolling projectiles in the existing clip path |
|---|---|
| **raster timing** | **none.** Presented Y stays ≤ 226, so no sprite DMA reaches lines 247/248 and the bottom split keeps its margin. The top-border fix is untouched. |
| **logical sprite count** | unchanged — the projectile already exists in the pool; it would simply remain admitted for 20 more rasters. |
| **Y sorting / render plan** | unchanged in kind. Clamping is monotonic, so ascending true order stays ascending presented order — the builder documents this. |
| **hardware sprite reuse** | **real cost.** Every bottom-clipped entry presents at Y=226, so they all share one schedule Y and the reuse rule refuses more than `MUX_SLOTS` (6) per edge. Up to 3 projectiles would compete with bottom-exiting enemies for those. |
| **scratch pool** | **the binding cost.** `CLIP_POOL_SLOTS` is **6**, double-buffered. Three projectiles plus a bottom-diving formation can exceed it; overflow drops the entry and counts `clipPoolFull`. **Dropping an enemy's clipped bitmap would be a worse artefact than the cosmetic one being fixed.** |
| **collision** | **must change in lockstep.** The engine's stated rule is that visible and dangerous are the same band. Extending drawing without extending `ebulletPlayerTick` would leave a visible bolt that cannot kill — the exact inversion the comment forbids. Extending both makes bolts lethal for 20 rasters longer, which is a **gameplay balance change**, not a rendering fix. |
| **worst-case density** | `EBULLET_MAX` is 3, so the added pressure is bounded at three entries — but three is half the clip pool. |

### The alternative that costs nothing

Redrawing the bolt so its ink occupies **rows 14..20** instead of 0..6 would put the ink on rasters 241..247 at Y=226 — the floor — with no clip pool, no mux, no collision and no raster consequence at all.

It is not free in a different currency: `logY` would then mean "14 rasters above the ink", so spawn positions and the hit window (`EBULLET_HIT_UP`/`DOWN`) must be re-based by 14, and the bolt could never ink above raster 69, so a bolt fired by an enemy near the top of the aperture would appear to leave the muzzle 14 rasters low. **It trades the bottom 14 rasters for the top 14.** For a projectile that always travels downward that is arguably the right trade, but it is a content and feel decision, not a mechanical one.

## 8. Change made

**None.** The brief's gate is explicit: *"If there is any meaningful renderer, multiplexer, raster, collision, or sprite-budget consequence, stop at diagnosis and recommendation rather than making a speculative architectural change."*

Both available routes cross that line — one spends a scarce scratch pool and changes lethality, the other re-bases the projectile's coordinate meaning. Neither is a stale constant being corrected, which was the only case the brief authorised me to fix outright.

No file was modified by this audit.

## 9. Tests

No code changed, so these record the state, not a verdict on a change.

| suite | result |
|---|---|
| `test_enemy_fire` | **2 failures** — see below |

```
FAIL member n fires if and only if the authored mask says bit n
     -- members 0..3 got [2, 0, 2, 0] from mask 0b101
FAIL the director keeps spawning after all of that
     -- spawned 55->55, started 12->12
```

Both concern **wave fire masks and director spawning**, not projectile lifetime, and neither touches the Y band this audit is about.

Because the working tree carries the uncommitted top-border raster fix, "pre-existing" was verified rather than assumed: the committed renderer was restored under a shell trap, rebuilt, and the same test re-run. Result in §12.

The wider engine suite was **not** re-run here. It was measured in full two tasks ago and is largely red at `8795c39` — thirteen of seventeen suites failing, two more non-deterministic — which is recorded in `reports/top-border-raster-shimmer.md` §12 and is unrelated to this audit.

---

## 10. Recommendation — the correct long-term rule

**The rule in the brief is the right one**, and I would adopt it as the engine's stated contract:

> A hostile projectile should remain visible **and** dangerous until it has genuinely left the visible playfield — and those two must remain the same coordinate, which the engine already requires.

Today it is neither, 14 rasters early. Three routes, in the order I would take them:

### Preferred — enrol projectiles in the existing clip path

One call to `logClipAnnotate` from `ebulletTick`, exactly as `pickup.asm` already does, plus extending the `ebulletPlayerTick` band to match so visible and dangerous stay identical.

* **Buys:** the full playfield. The bolt stays drawn and lethal to raster 247.
* **Costs:** up to 3 of the 6 `CLIP_POOL_SLOTS`, shared with bottom-exiting enemies; mux-slot pressure at the shared presented Y of 226; and bolts lethal for ~20 rasters longer, which is a **balance change to play-test, not just a render fix**.
* **Do first:** instrument `clipPoolFull` under the worst authored content — a bottom-diving formation with three bolts in flight. If it never trips, the cost is only the balance change. If it trips, raising `CLIP_POOL_SLOTS` from 6 to 9 costs 768 bytes double-buffered against the 832 spare that `clip.asm` documents in VIC bank 0 — tight, and worth measuring before promising.

### Cheaper — move the ink to the bottom of the bitmap

Rows 14..20 instead of 0..6. Zero raster, mux, pool and collision cost. Pays instead in coordinate meaning: spawn Y and the hit window re-based by 14, and no bolt ink above raster 69. **Good for a strictly downward projectile, wrong the day one travels upward.**

### Not recommended — raise `MAX_SPRITE_Y`

Gains one raster (227 is the DMA limit), still 13 short, and spends the bottom split's proven margin to do it. The constant is doing its job; it is not the problem.

### And regardless of route

`EBULLET_Y_MAX = 250` should be revisited **after** whichever route is taken, so the invisible tail is whatever is genuinely needed to leave the screen rather than an inherited 24 rasters of nothing.

## 11. Remaining manual checks

Per `AGENTS.md` rule 2, none of the above is settled by a counter. If a change is later made, the acceptance is visual:

1. Let a bolt miss and fly off the bottom. It should reach the playfield floor and disappear **at** the boundary, not above it.
2. Park the ship at the very bottom and take a hit. The bolt should connect where it visually touches the ship, and the ship's lower rows must not be a safe zone.
3. A bottom-diving enemy formation with bolts in flight, watching for an enemy whose clipped bitmap is **dropped** — that is what `clipPoolFull` would be counting.
4. Non-warp, normal-speed observation; and on MiSTer/CRT if the clip route is taken, since it changes what the mux is asked to do near the bottom edge.

## 12. Test attribution

`test_enemy_fire`, run on both the current tree and the committed renderer under a shell trap:

| check | pristine (arm 53) | current tree (arm 52) | verdict |
|---|---|---|---|
| *member n fires iff the authored mask says bit n* — `[2,0,2,0]` from mask `0b101` | fail 3/3 | fail 3/3 | **deterministic, pre-existing** |
| *the director keeps spawning after all of that* | fail **1 of 3** | fail **2 of 3** | **flaky on BOTH builds** |

The director check fails at baseline, so it is not attributable to the uncommitted raster fix; 1/3 against 2/3 is not a distinguishable difference at three samples, and I am not claiming one. Neither failure concerns projectile lifetime.

The wider suite was not re-run — it was measured in full two tasks ago and is largely red at `8795c39`; see `reports/top-border-raster-shimmer.md` §12.

## 13. Status and hygiene

**No file was modified by this audit. Nothing committed. Nothing pushed.** HEAD remains `8795c39`.

```
 M src/renderer.asm          <- the top-border raster fix, from the PREVIOUS task
?? reports/top-border-raster-shimmer.md
?? reports/enemy-projectile-despawn-audit.md
```

The raster fix was restored byte-for-byte after each A/B swap and is verified present (`TOP_ARM_LINE = 52`, `renderer.asm:291`).

* Every VICE instance was launched and reaped by the harness by exact PID (`[vice] launched pid N` / `[vice] reaped pid N`). **No `pkill`, no `killall`**, no user session touched, `-console` throughout. `pgrep -x x64sc` empty at the end.
* All probes live in the session scratchpad, none in the repo.
* Disk after the run: reported in the final message.
