# The protector guard orbit — diagnosed, and it is not a production defect

**Date:** 2026-09-18
**HEAD:** `a1dc0ec` *Wave contract stage 2: deterministic ARC entry, movement pool at $f530* — level with `origin/main`, 0 behind / 0 ahead.
**Starting tree:** `tests/test_token_encounter.py` modified (the previous task's repair, still uncommitted) plus its report.

## Headline

**There is no production defect. `src/token.asm` is untouched and both production binaries are byte-identical.** The two red orbit assertions are now **green**, and they got there by correcting two measurement faults in the test, each proved on the machine before it was changed.

My previous report concluded that production "contradicts its own documented intent". **That conclusion was wrong, and this report corrects it.** I compared measured guard angles against the *unclamped ideal* ring and never accounted for `src/token.asm`'s playfield clamp. With the clamp included, the guards were tracking their real targets correctly the whole time.

---

## 1. Diagnosis

### The path

| stage | code |
|---|---|
| conscription | `tokenAssignRoles` — one pass in slot order, skips `objHP == 0`, assigns `ROLE_GUARD + 0/1/2` |
| reinforcement | `tokenTick` — gated on `tkEnlisted < TK_GUARDS`; attritional, never refills |
| per-frame update | `src/enemy.asm` routes `enyRole >= ROLE_GUARD` to `tokenGuardMove` instead of `wmTick` |
| target | `tokenGuardMove`: phase = `((tkOrbit + p) / TK_ORBIT_HOLD + p * TK_ORBIT_SPAN) mod TK_ORBIT_STEPS`, then `tokenOrbXLo/Hi`, `tokenOrbY` |
| clamp | the post is clamped into `TK_X_MIN..TK_X_MAX` (28..330) |
| walk | `TK_STEP` = 3 px per axis per frame toward the post, snapping when inside one step |

Post assignment and the phase arithmetic are correct: `p * 8` of 24 phases is exactly a third of the ring, and I verified the emitted stations independently.

### Fault 1 — the token was at x = 0, so four fifths of the ring was clamped flat

The failing run killed the Dropper at **(0, 88)**. Measured live:

```
info killing dropper in slot 2 at (0,88)
TOKENX f=44 tokenX=0 tokenY=111 ring spans x -46..46  CLAMPED_LEFT=True (TK_X_MIN=28)
TOKENX f=84 tokenX=0 tokenY=131 ring spans x -46..46  CLAMPED_LEFT=True (TK_X_MIN=28)
```

`TK_RADIUS_X` is 46 and `TK_X_MIN` is 28, so with the token at x = 0 every post whose unclamped x fell below 28 was **collapsed onto the single line x = 28**. Only the narrow right-hand arc survived — which is exactly the −48°…+47° band, and exactly the "two quadrants only" the assertions reported. **The guards were tracking their clamped targets faithfully.**

The cause is the test. It selected the Dropper on Y alone:

```python
if s["hp"][i] > 0 and 70 <= s["logY"][i] <= 150:
```

A Dropper enters at `DROP_ENTRY_LEFT = 0`, **behind the left border** — the visible playfield starts at column 24 — so the test shot it on its first eligible frame, at a position **no player could ever shoot it from**, and then measured a ring the geometry forbids.

### Fault 2 — a corpse was being counted as a formation member

With the kill position fixed, the worst adjacent gap went from 0.4° to 43°, still under the 70° threshold. Tracing every frame that lowered the minimum:

```
NEWMIN f=107 gap=82.9 | g0p0 ang= 15.4 hp=0 tmr=8 | g1p1 ang=169.7 hp=6 | g3p2 ang=292.5 hp=6
NEWMIN f=108 gap=75.0 | g0p0 ang= 14.0 hp=0 tmr=7 | ...
NEWMIN f=110 gap=64.8 | g0p0 ang= 12.7 hp=0 tmr=5 | ...
NEWMIN f=113 gap=47.2 | g0p0 ang= 11.3 hp=0 tmr=2 | ...
NEWMIN f=114 gap=44.4 | g0p0 ang=  9.9 hp=0 tmr=1 | ...
```

Every one has `hp=0` on g0 — the guard the test *deliberately destroys* at frame 103. It keeps its slot, its `TYPE_ENEMY` and its `ROLE_GUARD` for the twelve frames of its death animation, sitting frozen at ~11° while the two survivors orbit on. **The worst gap before the kill was 84.2°.** The formation was never bunched; a dead guard was being measured as part of it.

---

## 2. Production is correct — the measurements that show it

With a representative token position, comparing each guard's **actual** angle against the ellipse point its post computes:

```
TRACK f= 44 orbit=47 | g0p0 tgt=170.1 act=171.0 err= +0.9 | g1p1 tgt=311.5 act=291.8 err=-19.7 | g3p2 tgt= 48.5 act= 37.5 err=-11.0 || target_min_gap= 97.0 actual_min_gap=105.7
TRACK f= 56 orbit=59 | g0p0 tgt=200.6 act=201.8 err= +1.2 | g1p1 tgt=350.1 act=338.2 err=-11.9 | g3p2 tgt=112.3 act= 96.1 err=-16.2 || target_min_gap= 88.3 actual_min_gap=105.7
TRACK f= 68 orbit=71 | g0p0 tgt=247.7 act=245.0 err= -2.7 | g1p1 tgt= 20.6 act=  9.0 err=-11.6 | g3p2 tgt=159.4 act=154.7 err= -4.6 || target_min_gap= 88.3 actual_min_gap= 90.3
TRACK f= 80 orbit=83 | g0p0 tgt=311.5 act=307.9 err= -3.6 | g1p1 tgt= 67.7 act= 47.4 err=-20.3 | g3p2 tgt=189.9 act=185.2 err= -4.7 || target_min_gap=116.1 actual_min_gap= 99.5
TRACK f= 92 orbit=95 | g0p0 tgt=350.1 act=348.4 err= -1.6 | g1p1 tgt=131.5 act=113.2 err=-18.3 | g3p2 tgt=228.5 act=219.8 err= -8.7 || target_min_gap= 97.0 actual_min_gap=106.6
TRACK f=104 orbit=11 | g0p0 tgt= 20.6 act= 16.7 err= -3.9 | g1p1 tgt=170.1 act=160.7 err= -9.4 | g3p2 tgt=292.3 act=275.7 err=-16.6 || target_min_gap= 88.3 actual_min_gap=101.0
```

| property | measured |
|---|---|
| target angular separation | **88.3°–116.1°** (posts are 120° apart *in phase*; the 46×30 ellipse maps that non-uniformly) |
| actual angular separation | **90.3°–106.6°** while all three live; worst over the whole live window **84.2°** |
| tracking error per guard | **−20.3° … +1.2°** — a small, consistent lag, exactly what smooth following at `TK_STEP` should produce |
| orbit coverage | all guards traverse the full ring — the quadrant assertion passes |
| ring radius | between `RING_BAND_MIN` and `RING_BAND_MAX` throughout; distances measured 30–46 px |

The minimum adjacent gap for a perfect 46×30 ellipse with posts 120° apart in phase is **~97°**; the engine holds 84–107° with live guards. The test's 70° threshold is correct and was never the problem.

---

## 3. What changed

**Production files changed: none.**

```
build/shmup.prg    b3549b79d1372896f0771fbf1c198fa6ad1fbe4caac35f2f70e33bba70cc3914   before and after
build/level1.prg   65d40468c8a2ecf29ddfd8b3919d986a185950079b68240e9879396e574d8ad1   before and after
```

Byte-identical, so there is nothing to report for code size, per-guard arithmetic, cycle cost or worst-case frame counters: **not one instruction changed**. The `$F530` movement pool and the level package were never involved.

**One file changed: `tests/test_token_encounter.py`** (+108 / −10 across this task and the previous repair).

| change | why |
|---|---|
| `TOKEN_X_MIN/MAX = TK_X_MIN + TK_RADIUS_X` … `TK_X_MAX - TK_RADIUS_X` (74…284), and the Dropper-selection gate now requires the Dropper to be inside that window | So the token lands where its whole orbit survives the clamp — and where a player could actually have shot it. Derived from `src/token.asm`'s own constants, not chosen. |
| `on_station` additionally requires `s["hp"][i] > 0` | A guard in its death animation is not holding station. The "is it still a coherent enemy" check deliberately still counts it; only the *geometry* excludes it. |

Neither is a weakening. No tolerance was lowered, no sample count reduced, no assertion deleted, and the required window is still `SPREAD_SAMPLES_WANTED = 60`.

---

## 4. Test results

`test_token_encounter`: **7 failures → 1**, and the one remaining is inherited noise.

| assertion | result |
|---|---|
| a guard swept several quadrants about the token | **PASS** (was red) |
| the three guards stay spread around the token, not bunched | **PASS** (was red) |
| the patrol ring is as wide as the constants say | PASS |
| …and never collapses onto the token | PASS |
| the three guards are never all stationary together | PASS |
| the defence is ATTRITIONAL: a destroyed guard is NOT replaced | **PASS** — `tkReinforced 0`, formation goes 3 → 2 and stays |
| the three-guard formation was observed before anything was destroyed | PASS — 71 settled frames, kill at frame 103 |
| `schedBuildDefer` is zero with the encounter run end to end | **FAIL — 1**, inherited noise |

```
info killing dropper in slot 2 at (75,99)      <- was (0,88)
info killed guard in slot 0 at frame 103       <- was frame 7
info tkStarted 1 tkEnded 1 tkReinforced 0 tkDenied 0 tkEgressed 3
```

### Regression

| target | result |
|---|---|
| `test-pickup`, `test-production`, `test-boot`, `test-boss`, `test-lifecycle`, `test-player-death`, `test-turret-regression` | **ALL PASS** |
| `test_wave_triggers`, `test_bank2_arena`, `test-movement-pool` | **ALL PASS** |
| `test-encounter-director` | `publishSkip` = 11, `schedBuildDefer` = 1 — **matches the documented baseline exactly** |

`gameOverrun` and `scrollLate` remain 0 wherever asserted. Nothing unrelated was repaired or weakened.

---

## 5. Manual VICE

**PID 50011**, PAL, visible, non-warp, launched without stealing focus.

What to look for: destroy a Dropper **inside the playfield**, then watch the three protectors. They should hold a rotating threefold ring about the P, roughly 90–110° apart, each sweeping the full orbit. If you destroy one, the remaining two should carry on and **no replacement should appear** — that is the attritional design, not a fault.

One genuine caveat the measurements make visible: if you shoot a Dropper very near the left or right screen edge, the ring **will** squash against `TK_X_MIN`/`TK_X_MAX` and the guards will bunch on the open side. That is the clamp doing its documented job of keeping defenders on screen. Whether that is the gameplay you want near the edges is a design question, not a defect — and deliberately out of scope here.

Your eyes are authoritative on the visual result.

---

## 6. Hygiene

`pgrep -x x64sc` confirmed a clean field before every run; every automated instance was reaped by exact PID and reported. No broad `pkill`/`killall`; no user-launched instance touched. All instrumented copies lived in disposable scratch and never in the repository.

```
$ du -sh build/    344K      (includes build/proof420; 96K after a plain `make build`)
$ du -sh .         8.9M
$ scratch          876K
```

---

## 7. Git

| | |
|---|---|
| local HEAD | `a1dc0ec` |
| upstream | `origin/main` = `a1dc0ec` — 0 behind, 0 ahead |
| uncommitted | `tests/test_token_encounter.py`; two untracked reports |
| committed / pushed | **nothing** |

**Nothing was committed or pushed, and no production source was modified.** The brief anticipated a production fix; the evidence did not support one, so I did not make one.
