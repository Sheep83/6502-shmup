# Turret Firing and Player Damage

**Repository:** `/Volumes/SSD/dev/C64/6502-shmup` (Mac mini)
**Reference:** `~/Desktop/c64Shooter-main.zip`
**Date:** 2026-09-13

---

## STATUS

**The turrets now fire in the actual game.** That sentence could not be written
before this corrective task: the previous slice shipped sixteen green firing
checks over a subsystem that **could not fire a single shot in any real game,
ever**.

| | |
|---|---|
| production firing | **WORKING** — 234 projectiles in one free-running session, nothing poked |
| player damage | **WORKING** — 34 hits taken in the same session |
| root cause | found, proven frame by frame, fixed in five lines |
| regression test | added, and **validated in both directions** |
| `make test` | **1 failure**, in `test_batch_window`, **proven pre-existing** — §9 |
| manual visual qualification | **still the user's to declare.** This report does not declare it |

The one outstanding `make test` failure is reproduced byte-for-byte on the
untouched commit with none of this work applied, at three failures in ten
runs. It is not this task's, it is not weakened to hide it, and §9 gives the
evidence.

---

## 1. The defect, as the game showed it

The report this file replaces claimed automated GREEN. Manual VICE
qualification found turrets visibly present and visibly not shooting, and
manual behaviour is authoritative. It was right and the test suite was wrong.

Reproduced first, before anything was edited, on the unmodified production
build:

```
t(s) plyY logCount ebCount ebRefused  visible/timer/logY
  1   220        2       0         0  vis=[7] timer=[94] logY=[156]
  4   220        2       0         0  vis=[0] timer=[94] logY=[92]
  6   220        1       0         0  vis=[6] timer=[93] logY=[149]
  8   220        2       0         0  vis=[4] timer=[96] logY=[114]
 10   220        2       0         0  vis=[2,3] timer=[92,92] logY=[190,126]
```

Three things in that table matter.

**`ebRefused` is 0.** Nothing was ever refused, so `ebulletSpawn` was never
reached. The cap, the pool and the aim were never in the story.

**`logCount` is 1–2.** The population gate (`logCount >= 8`) was one of the two
suspects named in the brief. Ordinary play is nowhere near it. **Not
implicated, and not changed.**

**Every `turretFireTimer` reads 92–96.** Against an interval of 100. A second
is fifty frames; the timer should be falling fifty a second. It never gets
below 92.

---

## 2. Root cause

Sampled every frame, at a fixed point in the frame, on the production loop:

```
frame  scrollFine  visible  timer  logY
    0        7      [2]      93     70
    1        0      [2]     100     71     <- coarse step
    2        1      [2]      99     72
    ...
    8        7      [2]      93     78
    9        0      [2]     100     79     <- coarse step
```

A perfect eight-frame sawtooth with a floor of 93, on a turret whose `logY`
advances one pixel a frame and whose `turretVisible` never drops — it sat
wholly inside the aperture the entire time. The reset lands exactly on
`scrollFine == 0`, which is the coarse step.

**`turretWorldTick` blanked `turretVisible[]` for all eight turrets at every
coarse step**, as the aim pass's cheap reject path:

```asm
    ldx #TURRET_TOTAL - 1
    lda #0
!blank:
    sta turretVisible,x         ; ALL EIGHT, unconditionally
    sta turretLogY,x
    dex
    bpl !blank-
```

`turretAimTick` arms the firing clock on the `turretVisible` 0 → 1
**transition**. So the blank **manufactured an arrival, every eight frames, for
a turret that had not moved at all**. A hundred-frame clock re-armed every
eight frames reaches 93 and stops. **No turret could ever fire.**

The two routines were each correct about their own job and disagreed about what
`turretVisible == 0` means. To the coarse step it meant "not yet derived for
this page". To the aim pass it meant "this turret was not on the aperture last
frame". Nothing in either file wrote that down, and the previous slice added
the second reader without noticing the first writer.

---

## 3. The fix

Five lines. Blank only the turrets that are genuinely off the new page:

```asm
    ldx #TURRET_TOTAL - 1
!blank:
    lda turretPaintPair,x                // == 0 is turretAimTick's !next exactly:
    bne !keep+                           // the shadow raises pair only for rel
    lda #0                               // 0..23, where row is always positive,
    sta turretVisible,x                  // so row < 0 cannot occur with pair != 0
    sta turretLogY,x
!keep:
    dex
    bpl !blank-
```

**`turretPaintPair == 0` is exactly `turretAimTick`'s own `!next` condition**,
not an approximation of it. `turretDeriveShadow` clears the shadow to
`row = $ff, pair = 0` and `turretDeriveOne` raises `pair` only for `rel 0..23`,
where `row` is always positive — so `row < 0` cannot occur with `pair != 0`,
and testing the pair alone is equivalent to testing both. The two tests are
now the same test, written once in each place with a comment pointing at the
other.

A turret that IS on the page has both bytes written authoritatively by
`turretAimTick` later in the same frame — on the visible path and on `!clipped`
alike, both of which store `turretLogY` before they branch — so not blanking it
changes nothing any reader can observe, except the false arrival.

The three states are now:

| the turret | who clears it | when |
|---|---|---|
| off the page | this blank | once, at the coarse step that took it off |
| on the page, clipped | `turretAimTick`'s `!clipped` | every frame |
| on the page, wholly visible | nobody | **the clock keeps counting** |

**What was NOT done.** The arming-on-transition rule was not replaced with a
per-frame scan of all eight turrets — that scan is what `trtVisibleMask` exists
to avoid and it is the reason firing is affordable at all. The population gate
was not touched. Nothing about the projectile pool, the renderer, the coarse-
step shadow, the `scrollFine == 7` preparation, `$D01E/$D01F`, or sprite
ownership was touched.

**One knock-on.** The turret code segment was four bytes from `$7400` and this
added five. The projectile segment moved `$7400 → $7500`; the next used region
after it is `$c000`, so there is 18KB of headroom and nothing else moved.

```
$6f00-$7401  turret code
$7500-$7692  projectile code
```

---

## 4. Production proof

The real game, launched normally, **nothing poked**.

### It fires, and it keeps firing

```
  t=  9s  ebFired= 45  ebRefused=0  plyHits= 7  logCount=2
  t= 18s  ebFired= 63  ebRefused=0  plyHits= 9  logCount=2
  t= 27s  ebFired= 80  ebRefused=0  plyHits=12  logCount=2
  t= 36s  ebFired= 96  ebRefused=0  plyHits=14  logCount=2
  t= 46s  ebFired=113  ebRefused=0  plyHits=17  logCount=2
  t= 55s  ebFired=131  ebRefused=0  plyHits=19  logCount=2
  t= 64s  ebFired=148  ebRefused=0  plyHits=22  logCount=1
  t= 73s  ebFired=164  ebRefused=0  plyHits=24  logCount=2
  t= 83s  ebFired=182  ebRefused=0  plyHits=26  logCount=2
  t= 92s  ebFired=199  ebRefused=0  plyHits=29  logCount=2
  t=101s  ebFired=217  ebRefused=0  plyHits=31  logCount=1
  t=110s  ebFired=234  ebRefused=0  plyHits=34  logCount=2

  gameOverrun 0   publishSkip 0   schedBuildDefer 0
  scrollLate  0   edgeLate    0   gameSpanMax 189   gameSpanOver 0
```

A steady ~17 shots per slice — not one burst and then silence. **`plyHits`
climbing to 34 is the damage path working end to end**: spawn, flight,
software collision, `playerTakeHit`, invulnerability window.

### One projectile, frame by frame

Broken on `ebulletSpawn` in the live game, then followed:

```
muzzle handed in: ebSpawnX = 228  ebSpawnY = 166   player at (160, 220)

  frame   X    Y   vX  vY  col  ptr  type
  +0     227  169  -1   3    7  $db    2
  +1     226  172  -1   3    7  $db    2
  +5     222  184  -1   3    7  $db    2
  +10    217  199  -1   3    7  $db    2
  +15    212  214  -1   3    7  $db    2
```

Every recovered rule is visible in that table:

- **the muzzle** — the turret's `logY` was 154, and 154 + `TURRET_MUZZLE_Y` 12
  = 166. Out of the barrel, not the roof;
- **the aim** — dx = 160 − 228 = −68, and |68| < `EBULLET_AIM_MID` 72, so
  bucket 1, so vX = −1. The old quantised slope, arrived at independently by
  the machine;
- **the trajectory is immutable** — vX and vY never change after launch;
- **the speed** — exactly 3 pixels a frame down, `EBULLET_VY`;
- **the presentation** — colour 7 (yellow), pointer `$db`, and `$db × 64 =
  $36c0`, the shared projectile bitmap;
- **the type** — 2, `TYPE_EBULLET`, an ordinary pool object.

### What the automated proof cannot do

It cannot tell you the bolt looks right. §11 is the manual checklist and it is
short, because the register-level behaviour above is already established.

---

## 5. Why the old tests missed it

`test_turret_firing.py`'s cadence section drove the routine directly:

```python
for k in range(n):
    call("turretFireTick")
```

**A routine called in a loop never advances a frame.** The scroller never takes
a coarse step, so the interaction that broke firing could not occur. Sixteen
firing checks passed against a subsystem that had never fired.

That is the general lesson and it is not specific to turrets: in this engine
the interesting failures live in the interaction between a subsystem and the
scroller/renderer cadence, which is exactly what a direct-call fixture removes.

---

## 6. The regression test

A new `production()` section in `tests/test_turret_firing.py`. It pokes
nothing, hijacks no PC, and drives no routine by hand.

1. **seek** — free-run until a turret is on the aperture **and its fire timer
   is still near the full interval**, i.e. it arrived recently and has most of
   its ~176 visible frames ahead;
2. **sample** — 90 frames at a breakpoint at a fixed point in the frame,
   carrying the frame counter with every sample, keeping only genuinely
   consecutive ones;
3. **assert** — for every maximal run of frames in which a turret was
   continuously visible **and which contains a coarse step**, the timer falls
   by exactly one per frame.

The predicate allows exactly one kind of reload: **from zero**. That is the
turret taking its shot (or having it refused) and restarting the interval,
which is the recovered rule. A reload from a **non-zero** count is the defect,
and nothing else is.

Plus: ordinary production `logCount` stays under the firing gate; the real game
launches projectiles with nothing poked; the cap refuses none at ordinary
population; and `gameOverrun`/`publishSkip`/`schedBuildDefer`/`scrollLate`/
`edgeLate` are all still zero after 45 seconds of live firing.

### Validated in both directions

A regression test that does not fail on the bug is worth nothing, so it was
run against the defective build — twice, because the detector was rewritten
after the first validation:

| check | defective build | fixed build |
|---|---|---|
| timer never re-arms | **FAIL** `turret 3: fine 7 timer 100 -> fine 0 timer 100` | ok |
| timers reach below the interval | **FAIL** lowest observed 93 | ok, lowest 0 |
| the real game launches projectiles | **FAIL** `ebFired = 0 in 45s` | ok, `ebFired = 85` |

**And every other check in the file passed on the defective build** — which is
precisely how this shipped the first time.

### Three sampling attempts, and why the first two were wrong

Recorded because this repository has now hit the same class of error four
times, and the pattern is worth recognising.

1. **settle by sleeping (0.02s, then 0.06s).** At 0.02 every frame read
   `turretVisible` all zero; at 0.06 it worked on one run and not the next.
   Timing the monitor measures the harness.
2. **sample blind, keep the longest contiguous run.** Sound sampling — 111
   consecutive frames across 14 coarse steps — but the window landed in a
   stretch of level with no turret on the aperture at all. **That was real
   data, not a harness artifact**: eight turrets over 420 stage rows leaves
   long gaps.
3. **seek to a freshly arrived turret, then step.** Stable. Three consecutive
   standalone runs, three different turrets, 46–72 contiguous frames, 5–9
   coarse steps, 2 qualifying runs each.

An earlier draft of attempt 2 would have reported a vacuous pass — no visible
frames means no runs means nothing to violate. The "at least one turret stayed
visible across a coarse step" guard exists to make that impossible, and it
caught it.

---

## 7. What working turrets broke elsewhere

Six suites failed once turrets could actually shoot. **Every one was a real
consequence of the feature working**, and none was made to pass by weakening
what it asserts.

Two hazards, appearing repeatedly:

- **H1 — a projectile is a pool object.** Suites that posed an exact population
  asserted "every live slot is `TYPE_ENEMY`" or "the pool is empty";
- **H2 — a damaged ship blinks.** `playerInvulnTick` clears `plyVisible` for
  four frames in eight, which correctly clears `plyPresEnable`, which clears
  the player's two bits in `$d015`. Suites asserting "the player publishes both
  reserved slots" read that as a failure.

| suite | failure | what was done |
|---|---|---|
| `slice_b`, `slice_a_prime` | `production startup still presents no fixture` | **`TYPE_EBULLET` admitted as a production pool type** beside `TYPE_ENEMY`. `fixtureMoves == 0` untouched; a live slot holding `TYPE_NONE`, or at index ≥ 16, still fails |
| `slice_c` | `despawn went through the pool` / `leaving nothing in the schedule` | turret fire silenced **for that section only**, exactly as it already silences the enemy spawner. Both assertions kept verbatim |
| `slice_c` | `25b. the player still publishes both reserved slots` | samples a ship that is not mid-blink |
| `slice_d` | `31b. the player still owns both reserved slots` | same |
| `slice_a`, `slice_b` | (latent H1+H2) | their existing `quiet_mux` — whose whole job is "nothing else is happening" — now also silences turret fire and makes the ship solid; `slice_b`'s `busy_mux` hands both back |
| `batch_window` | `the adopted schedule caught up with the population` | turret fire silenced: this suite poses a **frozen** population (`objVY = 0`) and a projectile is *not* frozen, so it moved the model's expected answer underneath the settle loop |

The `TYPE_EBULLET` admission is the only assertion whose *content* changed, and
it restates the intent the check's own comment already carried — *"no fixture is
loaded, and anything in the pool got there through the production object
pool"* — for the second producer. That comment already records the same
evolution once, for Slice C's enemies.

### And one of my own checks was vacuous

`test_turret_firing.py` asserted `no projectile exists at boot` **after a
three-second warp free-run**. It passed only because turrets could never fire.
Replaced with invariants that hold on a live machine and could actually catch
something: the cap is honoured, and **`ebCount` agrees with the live
`TYPE_EBULLET` slots** — a drifted counter would silently refuse every future
shot. The boot-vulnerability intent is kept as "never invulnerable without a
hit to explain it" (it read `plyInvuln 0, plyHits 5` — the ship had genuinely
been shot five times in those three seconds).

### A measurement bug, fixed where it was still live

`test_slice_c`'s population ladder computed

```python
"over": gameOverrun + gameSpanOver
```

**the same defect corrected in `test_slice_d` during the previous slice and
never applied here**, and exactly what the brief warns against. `gameOverrun`
is a fault — the main thread missed a 312-line frame. `gameSpanOver` is a
diagnostic — the 8-bit `gameSpanMax` saturated, so the span column is a floor.
Summing them reported a saturated counter as a missed frame: population 16 read
`over 4` with **`gameOverrun` actually 0**.

Separated. `gameOverrun == 0` remains a hard assertion at every population;
saturation is printed as a note.

---

## 8. Performance

The fix is a coarse-step path — once in eight frames — trading two stores per
on-page turret for a load and a branch per turret. Net ≈ +28 cycles once every
eight frames, about **+3.5 cycles a frame**. Re-measured rather than argued:

| | min | med | max |
|---|---|---:|---:|
| `turretFireTick`, no turret on the aperture | **12** | 12 | 12 |
| `ebulletPlayerTick`, nothing in flight | **12** | 12 | 12 |
| `playerInvulnTick`, ship not invulnerable | **12** | 12 | 55 |
| `turretFireTick`, a frame that actually launches | 628 | 714 | 1381 |
| `ebulletPlayerTick`, three in flight | 347 | 390 | 901 |
| `turretWorldTick`, `scrollFine == 7` preparation | 893 | 979 | 1522 |
| `turretWorldTick`, the coarse step adopting its shadow | 645 | 688 | 1244 |

**An ordinary frame still pays 36 cycles** for firing and damage. **The two
protected frames are unchanged** — the coarse-step shadow and the quiet-frame
preparation measure what they measured before, and the architecture the
previous slice established is intact.

### Capacity — the hard gate, with firing genuinely live

`test_slice_c`, with `gameOverrun` and `gameSpanOver` now separate:

```
 pop   span  spanOver  peak  acc  ovf  recSkip  schedSkip  over
   0    151         0     0    0    0        0          0     0
   1    172         0     2    2    0        0          0     0
   4    200         0     4    4    0        0          0     0
   8    228         0     8    6    0        0          0     0
  12    243         0    12    6    0        0          0     0
  16    255         1    16    6    0        0          0     0
```

`test_slice_d`, population ladder with collision on and off:

```
 enemies  collision   span  spanOver  overrun  recSkip  schedSkip
       8  OFF          244         0        0        0          0
       8  ON           255        29        0        0          0
```

**Population 8 with collision ON: `gameOverrun` 0, `publishSkip` 0,
`schedBuildDefer` 0.** Nothing relaxed. Population 16 in the slice_d ladder
still overruns and remains the documented `docs/ENGINE_CONTRACT.md` §10 limit.

---

## 9. `make test`

**Ten suites ALL PASS. 874 checks. Twelve VICE instances launched and twelve
reaped. `pgrep -fl x64sc` clear afterwards.**

**One failure**, in `test_batch_window`, layout "16 spread 10":

```
FAIL 16 spread 10: every batch line, first and count match
  machine [(40,0,6), (98,6,3), (128,9,3), (158,12,3), (188,15,1)]
  model   [(40,0,6), (108,6,3),(138,9,3), (168,12,3), (198,15,1)]
```

### It is pre-existing, and here is the proof

The entire working tree was stashed — no `ebullet.asm`, no turret firing, no
test changes, turret code back at `$737d` — and the same suite run repeatedly
on the untouched commit:

| build | runs | failures |
|---|---|---|
| this task's | 3 standalone | 1 |
| **untouched commit** | **10 standalone** | **3** |

and the failure on the untouched commit is **byte-for-byte identical**:

```
machine [(40,0,6), (98,6,3), (128,9,3), (158,12,3), (188,15,1)]
model   [(40,0,6), (108,6,3),(138,9,3), (168,12,3), (198,15,1)]
```

Both observed variants — this one, and `CURRENT holds 15 entries, model says
16` — occur on the untouched commit. They are one phenomenon: the adopted
schedule lagging the posed population by one step, which **the suite's own
source comment already documents**:

> *"under a load that misses frames adoption lags the build. Comparing a fresh
> population against a stale schedule reported 'machine 14/9, model 16/11' on a
> layout whose sixteen enemies were all present and correct."*

The twelve-iteration settle loop written to mitigate it does not always
converge.

**It was left alone.** Weakening a pre-existing assertion to make this task's
gate green is precisely what the brief forbids, and fixing an unrelated flaky
harness is outside this corrective task. It is reported here, with the numbers,
rather than hidden. **The gate is not green, and this is why.**

---

## 10. Files changed

**Production — the fix is entirely in one hunk of one file:**

| file | change |
|---|---|
| `src/turrets.asm` | the coarse-step blank made conditional; segment guard `$7400 → $7500` |
| `src/ebullet.asm` | segment start `$7400 → $7500`, guard `$7600 → $7700`. No logic change |

`src/renderer.asm`, `src/scroll.asm`, `src/terrain.asm`, `src/collision.asm`,
`src/enemy.asm`, `src/sorter.asm`, `src/motion.asm`, `src/hud.asm`,
`src/player.asm` and `src/objects.asm` are **unchanged by this corrective
task**. No renderer or scheduler invariant was touched, which is why P0–P5,
`test-engine-full` and `test-renderer-full` were not run.

**Tests:** `test_turret_firing.py` (the `production()` section, the vacuous boot
check replaced), `test_slice_a.py`, `test_slice_a_prime.py`, `test_slice_b.py`,
`test_slice_c.py`, `test_slice_d.py`, `test_batch_window.py` (§7).

---

## 11. Manual visual checklist

**Please run this yourself. This report does not declare visual GREEN.**

```sh
cd /Volumes/SSD/dev/C64/6502-shmup
make run
```

Comes up on **keyset A, port 2**, your own bindings, save-on-exit enabled.

Turrets appear in pairs, the first about 50 coarse rows in. A turret must be
wholly on screen for two seconds before it can shoot, and it will not shoot if
you are above it or level with it — so **fly below a turret and wait**. If you
sit still near the bottom, you will be hit within a few seconds.

| # | Look for | Expected |
|---|---|---|
| 1 | a turret firing | a small yellow bolt leaves the **barrel** at the bottom of the dome |
| 2 | the aim | leans toward where your ship was when it left; straight down if you were level |
| 3 | the trajectory | **straight** — it does not curve or re-aim after launch |
| 4 | the cadence | about one bolt every two seconds per turret, not the instant it appears |
| 5 | flying **above** a turret | it holds fire entirely |
| 6 | **destroying** a turret | it stops firing at once, and a bolt already in the air **keeps going** |
| 7 | **being hit** | the ship flashes on and off for about two seconds |
| 8 | during the flash | further bolts pass through you, and turrets stop shooting at you |
| 9 | after it ends | the ship is **solid**, not invisible or mid-blink |
| 10 | how many bolts at once | never more than three |
| 11 | bolts leaving | they vanish at the bottom and off the sides, never pile up |
| 12 | the turret pulse and destruction | **exactly as before** — white/red/yellow/red, light-red hit flash, three hits, correct terrain underneath |
| 13 | enemies, HUD, black border, scrolling | unchanged |
| 14 | a full minute of play | no new hitch, including on frames that fire |

Checks 6 and 9 are what this slice could most plausibly still get wrong. The
known whole-sprite enemy pop at the Y bounds is **not** a regression here.

---

## 12. Hygiene

- `pgrep -fl x64sc` run before every automated session; clear every time, and
  clear now.
- Every emulator launched with `-console` under a **retained PID** and reaped by
  that exact PID. Twelve launched, twelve reaped in the final gate.
- **No `pkill`**, no termination by name, no user VICE signalled, no `open -a`,
  no window opened, no focus stolen.
- No joystick, keyset or controller preference created or modified.
- `~/.config/vice/vicerc` **unchanged across this task**:
  `3510a90f9bac9702af2c7ce1aeb48b98a97f7f74`, 364 bytes, start and finish.
  `test_slice_c` hashes it before and after its own run and reported it
  unchanged in every gate.
- `make run`'s manual context is as the previous slice left it: `-saveres`
  (saves on exit), port 2 = keyset A, keysets enabled, port 1 left attached, no
  `-default`. Automated runs keep their own `-console -default +saveres` line
  and never write the user's settings back.
- All transient diagnostics, source backups and gate logs under `/tmp` removed.
  No `git stash` entries remain; both experiment stashes were popped and
  verified.

```
du -sh build/   ->   84K     main.sym, main.vs, shmup.prg
du -sh .        ->   3.9M
```

**No commits, no pushes.**

---

*A hundred-frame clock, re-armed every eight frames by a routine that meant
something different by the same byte. The turrets now shoot back on the old
cadence, through the old quantised aim, with the old cap of three; the bolts
are ordinary logical objects the renderer draws without knowing they are
hostile; the ship takes damage from software collision and gets the old
invulnerability window; and an ordinary frame still pays thirty-six cycles for
all of it.*
