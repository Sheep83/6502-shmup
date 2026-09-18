# Repairing `test_token_encounter` — and a production defect it uncovered

**Date:** 2026-09-18
**HEAD at start:** `a1dc0ec` *Wave contract stage 2: deterministic ARC entry, movement pool at $f530*
**Upstream:** `origin/main` = `a1dc0ec` — 0 behind, 0 ahead. Working tree clean.
**Result:** 7 failures → **3**. Four repaired, one stale assertion replaced by the contract production actually implements, and **two remain because they have found a genuine production defect**, which per the brief I have reported rather than fixed.
**Zero production source changes. Nothing committed. Nothing pushed.**

---

## 1. What the test intends, and why it was failing

### What it establishes

Kill an authored Dropper → it drops the P → three ordinary enemies are conscripted as protectors, one per post on an elliptical ring about the token → observe that ring → collect the token → watch the survivors leave upward.

### How it used to establish it

Before the exact-boot migration the file ran under `boot="fast"` and the **pre-Stage-1 wrapping trigger list**, so enemies existed all the way through the level and one was always available to conscript.

### Why it failed after migration — measured, not inferred

I instrumented a copy of the test in scratch. The WATCH loop reported:

```
DIAG f=  0 tokenY= 89 guards=3 posted={0:1, 1:1, 3:1} onstation=0
DIAG f= 25 tokenY=101 guards=2 posted={1:26, 3:26}    onstation=0
...
DIAG watched=288 spread_samples=0 frozen_samples=0 guard_frames={0: 19, 1: 270, 3: 287}
```

Three guards at frame 0; **two from frame 19 onward**. Slot 0 was a guard for only 19 frames. Stepping frame by frame showed it already dying at f=10 (`hp=0`, death timer 9 counting down).

The cause is in the test itself:

```python
if (killed_a_guard_at is None and len(g) == TK_GUARDS
        and quad_best >= 2):          # <-- satisfied within a few frames
```

`quad_best >= 2` means "some guard has been seen in two quadrants", which a guard satisfies almost immediately while still walking to its post. **The test destroyed one of the three guards on frame 7 — before the formation had ever been on station.**

And `src/token.asm:575-598` is explicit that this is unrecoverable:

> *"THE DEFENCE IS ATTRITIONAL… The gate is a creation count, not an occupancy scan. Until TK_GUARDS defenders have been ENLISTED the encounter is still assembling its group and may still reinforce; from the moment the third is created this branch is taken for the rest of the encounter and nothing can reopen it.*
> *3 defenders -> kill one -> 2 -> kill one -> 1 -> kill one -> 0"*

So the complement stayed at two for the rest of the encounter, `len(on_station) == TK_GUARDS` could never be true again, and **six assertions were left judging zero samples**.

The exact boot did not cause this. It removed the warped free-run that had been masking a self-defeating ordering bug: the test shot its own subject and then measured the hole.

### The correct synchronisation point

Not elapsed time — **the sample count of the thing being asserted on**. The kill that proves the attrition rule must not happen until the three-guard formation has been observed for long enough that the orbit assertions have their evidence.

---

## 2. The repair

**One file changed: `tests/test_token_encounter.py`** (+61 / −9). No helper was added — the synchronisation is local to this file, so no shared harness change was needed and no other test was migrated.

### (a) Kill after the evidence is banked

```python
SPREAD_SAMPLES_WANTED = 60
```

**Derived from the ring's own period, not chosen by taste.** `src/token.asm` turns the ring one phase every `TK_ORBIT_HOLD` (4) frames through `TK_ORBIT_STEPS` (24) phases, so a full lap is 96 frames. Sixty settled frames is well over half a lap — long enough for a guard to sweep the required quadrants and for the spread and lockstep percentages to be measurements rather than anecdotes.

The gate is deliberately **only** the sample count, not `quad_best`, because chaining it to the orbit-coverage property would stop the attrition contract being exercised whenever that property is broken — which is exactly the situation below.

### (b) The stale assertion, replaced

`"a killed guard was replaced"` tested behaviour the engine **deliberately removed** — the source records that summoning a replacement was the bug, because "a post emptied by the player was indistinguishable from a post never filled… the formation could not be broken down". It is now the statement production actually makes, which is also the one that would catch the old behaviour returning:

```python
check("the defence is ATTRITIONAL: a destroyed guard is NOT replaced, "
      "so the formation can be broken down", refilled_after_kill is None, ...)
```

### (c) Two new guards against vacuous success

The formation must have been observed, and the kill must actually have happened — otherwise the attrition assertion could be satisfied by an encounter nobody ever measured.

**No tolerance was weakened, no sample count reduced, no assertion deleted or skipped.**

---

## 3. The production defect the repair uncovered

With the ordering fixed the test banks **226 settled frames** (was 0) — and immediately exposes something real.

`src/token.asm:775-815` derives each guard's station as `post * TK_ORBIT_SPAN` = 8 phases = **120° apart**, described as *"three defenders around the token, not three that drift into a bunch."*

I compared each guard's **target** phase against its **actual** angle every 30 settled frames:

```
POSTS f=103 tkOrbit=10 | g0(post0) target= 30.0 actual= 18.0 lag= 12.0
                       | g1(post1) target=150.0 actual= 28.2 lag=121.8
                       | g3(post2) target=285.0 actual=313.0 lag=332.0
POSTS f=133 tkOrbit=40 | g0(post0) target=150.0 actual= 36.9 lag=113.1
                       | g1(post1) target=270.0 actual=313.0 lag=317.0
                       | g3(post2) target= 30.0 actual= 18.0 lag= 12.0
```

**The targets are correctly 120° apart. The guards are not.** At f=103 two of them sit at 18° and 28° — ten degrees apart when their posts are 120° apart — and lag their stations by up to 122°. Across 226 settled frames every guard visited only **two of four quadrants** (`quads={0:[0,2], 1:[0,2], 3:[0,2]}`), and the worst adjacent gap fell to **0.4°**.

The guards never track their posts around the ring: they converge into a narrow arc and oscillate there.

**This is a production behaviour that contradicts its own documented intent, not a harness artefact.** The brief says to stop and report rather than fix the engine in this task, so `src/token.asm` is untouched and these two assertions are left failing loudly:

- `a guard swept several quadrants about the token: it patrols rather than parks`
- `the three guards stay spread around the token, not bunched`

They are now failing on **71–226 real observations** instead of on zero, which is the difference between a broken test and a working test reporting a broken engine. **This deserves its own task.**

---

## 4. The original seven assertions

| # | assertion | now |
|---|---|---|
| 1 | a guard swept several quadrants about the token | **still fails** — production defect (§3), now on real samples |
| 2 | the patrol ring is as wide as the constants say | **PASSES** |
| 3 | …and never collapses onto the token | **PASSES** |
| 4 | the three guards stay spread around the token, not bunched | **still fails** — production defect (§3), 0.4° worst over 71 frames |
| 5 | the three guards are never all stationary together | **PASSES** |
| 6 | a killed guard was replaced | **replaced** — was stale; the attritional contract now **PASSES** |
| 7 | schedBuildDefer is zero with the encounter run end to end | **still fails** — inherited diagnostic noise, unchanged |

Plus two new assertions, both passing: the formation was observed before anything was destroyed, and a guard was then deliberately destroyed.

### Evidence the test is now watching the right thing

```
info killing dropper in slot 2 at (0,88); pkSpawned=0
info killed guard in slot 0 at frame 103         <- was frame 7
info steering the ship onto the token at y=232 (frame 285)
info tkStarted 1 tkEnded 1 tkReinforced 1 tkDenied 0 tkEgressed 1
```

- **Synchronisation condition:** `spread_samples >= 60` with all three guards simultaneously on the ring band.
- **Encounter start:** on the death of the first authored Dropper, from the row-52 encounter (`boot="exact"`, so the authored rows 48/52/90/126 are all inside the window).
- **Guards observable:** three posted (roles `ROLE_GUARD+0/+1/+2`) from the first WATCH frame; token descending from y≈89.
- **Settled frames sampled:** **71** before the kill, 226 when the kill is deferred entirely.
- **Object evidence:** all three in the pool as `TYPE_ENEMY`, `active`, non-zero HP, distinct post roles 2/3/4.

---

## 5. Zero production changes — proved

```
                                     before                            after
build/shmup.prg    b3549b79d1372896f0771fbf1c198fa6ad1fbe4caac35f2f70e33bba70cc3914   (identical)
build/level1.prg   65d40468c8a2ecf29ddfd8b3919d986a185950079b68240e9879396e574d8ad1   (identical)

$ git status --porcelain
 M tests/test_token_encounter.py
```

Both production binaries are **byte-identical**. A 420-row proof was therefore not required: no production source, level data or package layout changed, and no shared harness module was touched.

---

## 6. Focused and regression results

| target | result |
|---|---|
| `test_token_encounter` | **3 failures** (2 production defect, 1 inherited noise) — was 7 |
| `test-pickup` | **ALL PASS** |
| `test_wave_triggers` | **ALL PASS** |
| `test-production` | **ALL PASS** |
| `test-boot` | **ALL PASS** |
| `test-boss` | **ALL PASS** |
| `test-lifecycle` | **ALL PASS** |
| `test-turret-regression` | **ALL PASS** |
| `test_bank2_arena` | **ALL PASS** |
| `test-movement-pool` | **ALL PASS** |
| `test-encounter-director` | `publishSkip` = 11, `schedBuildDefer` = 1 |

`test-encounter-director` matches the reconciliation report's baseline exactly (11 / 1). `schedBuildDefer = 1` in the token test is the same established noise. Nothing unrelated was repaired or weakened.

---

## 7. Hygiene

`pgrep -x x64sc` confirmed a clean field before every run; every automated instance was reaped by exact PID and reported. No broad `pkill`/`killall`; no user-launched instance touched. The instrumented copy of the test lived in disposable scratch and never in the repository.

```
$ du -sh build/    344K      (includes build/proof420; 96K after a plain `make build`)
$ du -sh .         8.9M
$ scratch          772K
```

**Manual VICE: PID 43686**, PAL, visible, non-warp, launched without stealing focus. Worth a look specifically at §3: destroy the Dropper, then watch the three protectors. If they bunch into a narrow arc instead of sitting a third of a ring apart, that is the defect the test is now correctly reporting — and your eyes are authoritative on it.

---

## 8. Git

| | |
|---|---|
| local HEAD | `a1dc0ec` |
| upstream | `origin/main` = `a1dc0ec` — 0 behind, 0 ahead |
| uncommitted | `tests/test_token_encounter.py` (+61 / −9) |
| committed / pushed | **nothing** |

**Recommended follow-up, not started here:** the protector ring does not reach the 120° distribution `src/token.asm` documents (§3). That is a production task with a real visible symptom, and the repaired test is now the instrument for it.
