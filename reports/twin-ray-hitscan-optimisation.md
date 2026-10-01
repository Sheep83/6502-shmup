# 19656 — Twin-Ray Hitscan: Investigation and Optimisation

**Date:** 2026-10-01
**Scope:** investigate, measure, optimise the player's twin-ray hitscan.
**Outcome:** the current cost is explained and **corrected downward**; a
single-pass twin-ray resolution is implemented and **cuts collision by 34%**
with behaviour proved identical; and the frame-overrun instrumentation is
repaired. **It does not restore worst-frame headroom**, because the worst frame
is not a volley frame — `regenTick` is, and it is 2.4× collision's entire cost.

No commit, no push. The stripped stress encounter is untouched.

---

## 1. The inherited number was wrong for this load

The brief carried **~5,000 cycles on a volley frame**, from the 2026-09-13
audit. Measured on this build, that figure is a **16-enemy elapsed** reading. At
the stress encounter's actual load it is far smaller:

| live objects | collisionTick, **elapsed**, volley frame |
|---:|---:|
| 0 | 727 |
| 3 | 1,448 |
| 4 | 1,894 |
| 5 | 2,217 (11.3% of a frame) |

Extrapolating the measured slope, 16 objects lands near 5,000 — so the audit's
number was right for *its* load and wrong for *ours*. **Do not treat it as the
volley cost of this encounter.**

---

## 2. Exact twin-ray semantics (established before changing anything)

From `src/collision.asm` and `src/weapon.asm`, confirmed on the machine:

* **Two rays** (`WPN_RAYS = 2`), one per cannon, at `plyX + PLAYER_CANNON_L/R`,
  both at `shotY = plyY`.
* **Vertical, upward.** Eligible enemies satisfy
  `HITSCAN_MIN_Y (55) <= logY < shotY`.
* **Hitbox 24 px**: hit iff `0 <= rayX - enemyX < HITBOX_W`, computed as a
  **nine-bit** delta so `x >= 256` works and no ray wraps onto a distant enemy.
* **Target filter**: `logActive`, `objType == TYPE_ENEMY`, `objHP != 0`. A
  *dying* enemy is not a target **and does not shield** the live one behind it.
* **Nearest wins, and nearest means GREATEST Y** (the ship is below, firing up).
  **A tie goes to the higher slot index** — the scan runs low→high and an equal
  Y replaces the incumbent.
* **Turrets extend the same competition** (`traceTurretRay`) and must beat the
  incumbent *strictly*, so an enemy wins a tie against a turret.
* **A miss lets the ray reach the boss** (`bossRayHit`).
* **One enemy in both rays takes TWO damage applications.**
* **THE RAYS RESOLVE SEQUENTIALLY.** `collisionTick` ran
  `traceRay` → `applyDamage` per ray, so the left ray's damage was already in
  `objHP` when the right ray scanned. Observable: a **one-HP** enemy in both
  rays dies to the left ray, and the right ray then takes **whatever was behind
  it** rather than hitting the corpse twice.

That last property is the one an optimisation destroys, and it is now pinned by
a test.

---

## 3. Where the cost went (Phase 1)

Measured **pure** (raster IRQ masked, so only VIC DMA intrudes), minimum of
three runs, via a breakpoint pair around the call:

| scenario | pure cycles |
|---|---:|
| 0 enemies, no hit | 721 |
| 6 enemies, no hit | 1,474 |
| 16 enemies, no hit | 2,514 |
| 6 enemies, both rays hit | 1,622 |
| 16 enemies, both rays hit | 2,533 |

**Fixed 721. Slope 112 cycles per occupied slot** (two rays together, so ~56 per
slot per ray). `traceRay` alone at 6 enemies measured 589, so the two scans were
1,178 of the 1,474 — **80% of the cost was the pool walk, done twice.**

### The duplication, precisely

`traceRay` walks all 16 slots with no early exit, and resolving two rays ran it
twice. Per occupied slot, **each** pass paid:

```
logActive, objType, objHP          liveness and type      ~18 cycles
logY vs HITSCAN_MIN_Y, vs shotY    both halves of Y       ~16
nine-bit X delta vs HITBOX_W       the only per-ray part  ~24
nearest-Y compare and store                               ~10
loop                                                      ~7
```

Everything except the X delta is **identical for both rays** and was computed
twice. That is the whole finding: the rays differ only in one coordinate.

Also measured and found *not* to be causes: no general object-vs-object
machinery is used (the ray query is already bespoke), no nested passes, no
reconstruction of collision state per ray beyond two byte copies, and call
overhead is three `jsr`s per volley.

---

## 4. Approaches compared (Phase 3)

| | approach | 6 enemies, both hit | vs current |
|---|---|---:|---|
| **A** | current: one full pool walk per ray | 1,622 | baseline |
| **B** | two scans, general machinery removed | — | nothing general to remove; A *is* B |
| **C** | **single pass resolving both rays** | **1,078** | **−34%** |
| D | Y-ordered early-out | rejected | the only Y order is the renderer's sorted schedule; coupling gameplay collision to mux ordering is exactly the fragile ownership the brief warns against |
| E | 6502-specific extras | partly taken | the ray coordinates are read straight out of the shot event instead of being copied to locals, which removed four stores and two bytes of state |

**B deserves its result stated plainly:** there was no general collision
machinery to strip. `traceRay` is already a purpose-built ray query, so the
"optimised two-scan" control collapses onto the baseline. All the cost was
structural duplication, which is what C removes.

---

## 5. The chosen implementation, and how the sequential rule survives

`traceBothRays` walks the pool **once**, testing the shared eligibility (type,
liveness, both halves of Y) a single time and then both ray X positions against
the same object, keeping an independent nearest-candidate per ray.

The hazard is that a single pass collects both candidates *before* any damage,
so it cannot see the sequential rule. The resolution is exact rather than
approximate:

> Ray 0's damage can only ever make ray 1's candidate **ineligible**. It cannot
> move an enemy, change a Y, or make a new one eligible. So the *only* way one
> pass can differ from two is "ray 1's candidate just died" — three
> instructions to detect, and handled by running the **original** single-ray
> scan for ray 1.

```asm
    lda csTarget2
    cmp #$ff
    beq !fast+          ; ray 1 found nothing: nothing to spoil
    tax
    lda objHP,x
    bne !fast+          ; still alive: the candidate stands
    jsr traceRay        ; it died to ray 0 -- re-choose exactly as before
    jmp csResolve
```

The fast path is the common case; the rare path **is the old code**. Nothing
approximates anything.

Two further structural changes:

* **`WPN_RAYS != 2` is now a build error** instead of a runtime fallback loop.
  The general "loop over `shotRays`" path was dead code for a case the weapon
  cannot produce, and a fast path that silently did the wrong thing for three
  rays would be a trap. A `.error` naming `collideTwinRays` tells whoever
  changes the weapon exactly what to revisit.
* **`csResolve`** factors the "damage the winner, or let the ray reach the
  boss" tail that all three resolution paths shared.

### Relocated state

The collision state block lived in a 13-byte run at `$c5f3` between the object
pool and the SFX state, with **one** byte spare; the scan needs two
(`csTarget2`, `csTarget2Y`). It moved to `$c616` — the free run above the vic
bank state, 234 bytes — with its guard updated to `$c700`. Nothing reads these
by address; every consumer uses the symbol.

---

## 6. Behavioural equivalence

`tests/test_hitscan_twin_ray.py` — **31 checks, synthetic fixtures, all pass
before and after.** It covers every item the brief listed, and in particular:

| property | proof |
|---|---|
| one trigger pull hits two different enemies | `{0: 1, 1: 1}` |
| nearest (greatest Y) wins and shields the rest | 4 stacked → only slot 2 hit |
| equal-Y tie goes to the higher slot | slots 2 and 5 at Y=150 → slot 5 |
| hitbox exactly `[enemyX, enemyX+23]` | offsets 0 and 23 hit; −1 and 24 miss |
| at/below the ray origin ignored | no damage |
| above `HITSCAN_MIN_Y` ignored, exactly at it eligible | both checked |
| inactive / non-ENEMY ignored | no damage |
| dying enemy is not a target and does not shield | `{1: 1}` |
| **nine-bit X**: x=300 hit, straddling x=256 hit, no wrap from 300 onto 10 | all three |
| one enemy in both rays takes **two** damage | `{0: 2}` |
| **sequential rule**: 1-HP enemy in both rays dies to ray 0, ray 1 takes the one behind | `{0: 1, 1: 1}` |
| destruction records the kill and leaves HP 0 | `csKills`, `objHP` |
| full pool of 16, one per ray | `{7: 1, 11: 1}` |

---

## 7. Results

### Collision cost, before → after

| scenario | before | after | saving |
|---|---:|---:|---:|
| 0 enemies, no hit | 721 | **468** | −35% |
| 1 enemy, no hit | 825 | **544** | −34% |
| 3 enemies, no hit | 1,033 | **696** | −33% |
| 6 enemies, no hit | 1,474 | **924** | −37% |
| 16 enemies, no hit | 2,514 | **1,813** | −28% |
| 1 enemy, left ray hits | 955 | **723** | −24% |
| 2 enemies, both rays hit | 1,077 | **817** | −24% |
| same target on both rays | 1,040 | **680** | −35% |
| 6 enemies, both rays hit | 1,622 | **1,078** | −34% |
| 16 enemies, both rays hit | 2,533 | **1,838** | −27% |

**Fixed 721 → 468. Slope 112 → 84 cycles per occupied slot.**

### In the running game (elapsed, volley frames)

| live objects | before | after | saving |
|---:|---:|---:|---:|
| 0 | 727 | 474 | −35% |
| 2 | 891 | 588 | −34% |
| 3 | 1,448 | 634 | −56% |
| 4 | 1,894 | 1,443 | −24% |
| 5 | 2,217 | 1,745 | −21% |

### The stripped stress encounter: headroom

Main-thread span (`gameFrame` → `gameSpan`), trigger held, same method as the
previous diagnostic:

| live objects | worst before | worst after | delta |
|---:|---:|---:|---:|
| 0 | 12,191 | 12,255 | +64 |
| 3 | 14,478 | 14,523 | +45 |
| 4 | 15,285 | **14,418** | −867 |
| 5 | 17,939 | 17,887 | −52 |
| **6** | **19,948** | **19,948** | **0 — still over** |

**The worst frame did not move.** The reason is measurable and decisive: the
worst frames are **`regenTick` working frames that carry no volley**. Collision
costs 24 cycles on a non-volley frame.

| phase | median | % of frame |
|---|---:|---:|
| **regenTick** | **5,613** | **28.6%** |
| playerTick | 398 | 2.0% |
| buildSchedule | 343 | 1.7% |
| playerEmit | 321 | 1.6% |
| collisionTick (volley, 5 objects) | 2,217 → 1,745 | 11.3% → 8.9% |
| collisionTick (non-volley) | 24 | 0.1% |

**Answer to the brief's key question: no.** The optimisation is real and worth
keeping — it removes a third of a cost that peaks above 11% of a frame — but it
cannot restore worst-frame headroom for this encounter, because it is not what
spends the worst frame.

---

## 8. Frame-overrun instrumentation, repaired

The previous diagnostic found the counters reporting green while measured work
exceeded the frame. Both defects confirmed:

* **`gameSpanMax` saturates at 255 raster lines**, which is 82% of a frame.
  Every span from 82% to over 100% reports the same `255`.
* **`gameOverrun` is a lagging measure.** It counts frames the main thread
  *dropped* — a `frameCounter` delta of ≥2 at the top of the loop. A frame
  costing 101% of budget steals only 1% of the next, so the delta stays 1 and
  nothing is recorded until enough debt accumulates to skip a whole frame.

### The fix

`gameFrame` runs between two frame transactions, and the transaction at raster
250 is what increments `frameCounter`. **So if `frameCounter` has changed
between `gameFrame`'s entry and `gameSpan`, that frame's work occupied more than
a whole displayed frame.** One byte stamped at entry, one compare at exit, one
saturating counter — no raster arithmetic, no saturation, no wrap case.

```
after 25 s of the stress encounter with the trigger held:
  gameOverrun      0      <- the old counter still says clean
  gameFrameOver    1      <- the new one sees it
  gameSpanMax      255    <- saturated, uninformative
  gameSpanOver     5
```

A future stress test can no longer report "zero overruns" while main-thread work
exceeds the frame.

---

## 9. Corrected stale comment

`src/renderer.asm` justified `HANDOFF_LINE = 40` with *"a six-entry batch 0
costing about five"* raster lines. The previous diagnostic timed 1,242 real
batch executions: a six-entry batch 0 runs **41 → 50, nine lines**, leaving a
**five**-line margin rather than the ten implied. Comment corrected with the
measurement and its source. **Documentation only — `HANDOFF_LINE` is unchanged**
and nothing measured asks for it to move.

---

## 10. Tests

| suite | result |
|---|---|
| `tests/test_hitscan_twin_ray.py` (new, 31 checks) | **PASS** before and after |
| `test_dropper_movement_program.py` | PASS |
| `test_pickup.py` | PASS |
| `test_lifecycle.py` | PASS |
| `test_enemy_fire.py` | FAIL — **also fails at HEAD** (frozen `AUTHORED_MASKS`) |
| `test_token_encounter.py` | FAIL — **also fails at HEAD** |
| `test_dropper_flight.py` | FAIL — **also fails at HEAD** |
| `test_turret_regression.py` | **flaky on BOTH builds** — see below |
| `make smoke` | **PASS**, every counter zero |

### `test_turret_regression` — flaky, on both builds

It passed at HEAD on the first run and failed on mine, which looked like a
regression, so it was run three times on each:

```
mine: FAIL PASS FAIL      (1 of 3)
HEAD: PASS PASS FAIL      (2 of 3)
```

**HEAD fails too**, so this is not a regression introduced here, and the turret
damage path is untouched by this work. The failure is always the same:
*"a freshly arrived turret was found to watch — 0 qualifying runs"*, i.e. the
search never caught a turret in the state it wanted, not that a turret
misbehaved.

The mechanism is the test's own: it hunts with
`free_run(mon, frameCounter, 0.25)` — **wall-clock** seconds, in warp mode. How
many emulated frames pass in a wall-clock quarter-second depends on how fast the
host emulates, which depends on how much work the game does per frame. A cheaper
frame therefore steps the search in coarser emulated-frame increments and can
stride past the arriving turret, which plausibly explains why this build failed
more often — though at n=3 per build that difference is not significant and is
not claimed as one. This is the same wall-clock coupling recorded in
`reports/mux-glitch-diagnostic-pass-1.md`; it is test debt and was not "fixed"
here.

### Verified against HEAD

The three unconditional failures were verified against a pristine `HEAD` build (`git archive` into
scratch, built and run there). `test_dropper_flight`'s failure is explained:
the stripped level puts trigger 0's Dropper on `PROG_DIVE_BOMB`, so a test
asserting the hard-coded three-pass flight reports *"entry x=175, logY 1..155"* —
it is asserting legacy behaviour against an authored-movement Dropper. That is
the user's deliberate level change, not a fault.

---

## 11. Hygiene

* No commit, no push. No destructive git operations.
* The stripped stress encounter is **unchanged** — no authored content edited.
* VICE: exact owned PIDs, every launch reaped, no broad `pkill`, `-console`
  only, no focus stolen. `pgrep -f x64sc` = 0 after every run.
* Disposable probes in the session scratchpad only.

---

## 12. Remaining headroom and the next target

**`regenTick` at 5,613 cycles median (28.6% of a frame) is the next
optimisation, and it is 2.4× the entire collision cost.** The 2026-09-13 audit
already ranked it and measured the remedy: spreading 25 rows over 8 frames
instead of 5 over 5, and unrolling the row fill, for **~1,500–2,500 cycles**.
That alone is larger than the 1,279-cycle overrun the stress encounter shows at
7 objects.

After that, in measured order: the schedule builder's constant factor
(~1,500), the batch interrupt's fixed overhead (~1,000), and the empty-slot
walks in `objectUpdateAll`/`collisionTick` (~200–600).

Collision is no longer on that list: at 84 cycles per occupied slot and a 468
fixed cost it is a small term, and further work on it would be micro-optimising
the wrong routine.
