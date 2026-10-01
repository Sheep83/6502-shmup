# Making Dropper + Escort Semantics Explicit

**Task:** 19656 — Make Dropper + Escort Semantics Explicit
**Scope:** one runtime seam, two stale test fixtures, one new regression suite.
No authorable Dropper movement; no schema, column, editor or preview change.
**Tree:** `main`, HEAD `1a07c82 More test cleanups`.

---

## Executive summary

`reports/dropper-escort-substitution-audit.md` established that the useful
`Dropper + escorts` formation was a **side effect of a safety interlock**: every
member of a Dropper wave attempted to *be* the Dropper, member 0 claimed
`tkDropperLive` first, and members 1..N−1 were refused by their own sibling and
fell back to the ordinary identity.

That is now an explicit contract, stated at the seam and enforced by it:

> A Dropper Trigger's **member 0** is the sole Dropper candidate. Members
> 1..N−1 are ordinary level enemies — escorts — chosen as such deliberately. The
> one-live-Dropper guard governs **member 0 only**; it is a lifecycle rule, not
> the mechanism that manufactures the escorts.

**Visible behaviour is preserved**, and that is measured rather than asserted: the
control case is byte-identical before and after (1 Dropper at member 0, N−1
escorts at the authored offsets, same colour, same speed, same fire masks).

**The change is discriminated by an experiment neither build can fake.** Clear
`tkDropperLive` immediately after member 0 spawns — exactly what `enemyDespawn`
does when the player shoots the Dropper — and count the Droppers:

| | control | flag freed mid-wave |
|---|---|---|
| **old seam** | 1 Dropper | **2 Droppers** — member 1 claimed the freed flag |
| **new seam** | 1 Dropper | **1 Dropper** — the flag read 0 for members 1–3 and none took it |

So the old formation really did depend on repeated failed Dropper spawns, and the
new one does not. It also closes a gameplay anomaly the audit predicted: killing
the Dropper early used to mutate a mid-formation escort into a second Dropper,
with a second flight and a second token to come.

**One deliberate behaviour change, and it is the one the contract asks for.** In
the old seam a later member could become the Dropper when the flag happened to be
free. Under "member 0 is the sole candidate" it cannot. Everything else — the
ordinary case, the already-live case, fire-mask numbering, LEFT/RIGHT, escort
movement, speed, the hard-coded flight — is unchanged.

---

## Baseline

**An honest note about how the baseline was taken.** I started a baseline run and
then rebuilt the binary while it was still in flight, so `species_order` onward in
that run measured the *changed* build. Those results are reported below as
post-change, not as a baseline. The baseline for this task is therefore taken
from the two preceding reports, which were recorded at this exact HEAD with no
source changes:

| Suite | Baseline | Source |
|---|---|---|
| `test_dropper_flight` | **FAIL** 1 of 23 — "the second Dropper entered from the OTHER authored side -- first entered x=0, second x=0" | this session's audit, and re-confirmed at 11:26 before the rebuild |
| `test_token_encounter` | **FAIL** 1 of 22 — "a surviving protector visibly ASCENDED rather than being deleted -- runs {}"; **PASS** on a later run | the audit, and again at 11:26 |
| `test_species_order` | PASS | `reports/defreeze-tests-from-authored-content.md` |
| `test_pickup` | PASS | same |
| `test_wave_triggers` | PASS | same |
| `test_square_species` | not previously run | — |

`test_token_encounter` failing once and passing once at the same HEAD is itself a
finding: the failure is **flaky coverage-by-luck**, not a deterministic defect,
which is exactly why it needed a synthetic fixture rather than a tolerance.

---

## The implementation seam

One block, `src/waves.asm`, inside `waveSpawnMember` — the single instruction
that commits a species to an object. 52 insertions, 16 deletions, no other
runtime file touched.

### Before

```asm
    ldy wvInst
    lda wvSpecies,y          ; the authored species: DROPPER for EVERY member
    cmp lvlDropRow
    bne !species+
    ldy tkDropperLive
    beq !claim+
    lda lvlPlainRow          ; one is already out there -> substitute
    jmp !species+
!claim:
    ldy #1
    sty tkDropperLive
!species:
    sta enySpecies,x
```

Every member of a Dropper wave reached the interlock. Which one became the
Dropper was decided by *arrival order*, and "escort" was the name for *refused*.

### After

```asm
    ldy wvInst
    lda wvSpecies,y
    cmp lvlDropRow
    bne !species+                       ; not a Dropper wave: authored species,
                                        ; untouched

    ; Y is still the instance. wvIndex is the member being sent, 0-based and
    ; pre-increment -- waveTick bumps it after this routine returns.
    lda wvIndex,y
    bne !escort+                        ; members 1..N-1: escorts by decision,
                                        ; never candidates

    ; ---- member 0: the candidate, and the one-live guard decides ----------
    ldy tkDropperLive
    bne !escort+                        ; one is already out there
    ldy #1
    sty tkDropperLive                   ; this one is now THE Dropper
    lda lvlDropRow                      ; the wvIndex load above clobbered A
    jmp !species+

!escort:
    lda lvlPlainRow
!species:
    sta enySpecies,x
```

The seam carries the contract as a comment, in the file's own voice, including
why it used to be otherwise and the two consequences that had.

### Cost

- **Ordinary (non-Dropper) waves: not one extra cycle.** The `cmp lvlDropRow` /
  `bne` pair is unchanged and still the first thing tested.
- **A Dropper wave: one extra `lda wvIndex,y` (4 cycles) per member**, plus a
  reload of `lvlDropRow` on the claiming path. This runs once per member at spawn,
  never per frame.
- No new state: `wvIndex` already existed, indexed by instance, and is exactly
  the member index at this point.

---

## Proof that members 1+ no longer rely on failed Dropper spawning

Both builds are the same tree; only `src/waves.asm` differs. The old-seam build
was made in a scratch copy from `git show HEAD:src/waves.asm`, so the comparison
is the seam and nothing else.

The experiment: one synthetic Dropper wave, `count=4`, `interval=30`; clear
`tkDropperLive` the instant member 0 activates.

### Old seam

```
--- flag cleared after member 0 ---
    member species          tkDropperLive @activate
         0   8 DROPPER    1   <- flag cleared straight after this spawn
         1   8 DROPPER    1
         2   0 escort     1
         3   0 escort     1
    => 4 spawned, 2 DROPPER(s) at member(s) [0, 1]
```

Member 1 took the freed flag and became a second Dropper — and re-set it, so
members 2 and 3 were refused again and reverted to escorts.

### New seam

```
--- flag cleared after member 0 ---
    member species          tkDropperLive @activate
         0   8 DROPPER    1   <- flag cleared straight after this spawn
         1   0 escort     0
         2   0 escort     0
         3   0 escort     0
    => 4 spawned, 1 DROPPER(s) at member(s) [0]
```

The `0`s in the last column are the point: the interlock was **genuinely open**
for members 1, 2 and 3, and not one of them took it. They are escorts because the
seam says so, not because something refused them.

### Controls are identical

```
old seam, no interference:  4 spawned, 1 DROPPER at member [0]
new seam, no interference:  4 spawned, 1 DROPPER at member [0]
```

Same member, same species, same escort positions. Visible behaviour preserved.

---

## Already-live semantics

Measured, `count=4`, `tkDropperLive` pre-set before the wave arms:

```
info   mbr species          fire spd col   x   y  vx vy live
info     0   0 escort      1   4   5 100  60   6  0    1
info     1   0 escort      1   4   5 130  60   6  0    1
info     2   0 escort      1   4   5 160  60   6  0    1
info     3   0 escort      1   4   5 190  60   6  0    1
=> 4 spawned, 0 Dropper(s)
```

- the **whole authored wave is still sent** — four members, not three;
- **no second Dropper** exists;
- **member 0 falls back** to the ordinary enemy rather than being discarded;
- the trigger becomes an all-ordinary wave of the authored size.

That is what it already did, and it is now the *only* thing the interlock does.

One detail worth recording: member 0 lands at `x = 100`, which is the wave's own
`startX`. When member 0 *is* the Dropper, `dropperLaunch` overwrites that position
with the entry edge and the formation keeps a hole at slot 0. So a refused Dropper
wave is a *complete* formation and a successful one is not — unchanged by this
task, and noted for the later movement pass.

---

## Fire-mask and LEFT/RIGHT preservation

### Fire mask — numbering preserved, bit 0 intentionally inert

Unchanged and now asserted rather than merely true. `src/waves.asm` resolves the
mask for the member being spawned and `dropperLaunch` then withdraws the
Dropper's permission, so bit 0 names the Dropper and can never arm anything.

| Authored mask | member 0 (Dropper) | members 1..3 (escorts) |
|---|---|---|
| `%1111` | `enyFire 0` | `1, 1, 1` |
| `%0001` | `enyFire 0` | `0, 0, 0` — **nothing in the wave fires** |
| `%1110` | `enyFire 0` | `1, 1, 1` |

Renumbering was explicitly out of scope and would have silently changed every
authored mask in the campaign. The test documents the numbering as intentional.

### LEFT / RIGHT — entry only, never the choice of member

| side | Dropper member | entry | `wmVX` | `logY` | escorts |
|---|---|---|---|---|---|
| LEFT | **0** | `x=0` | `+12` | 88 | `(130,60) (160,60) (190,60)` |
| RIGHT | **0** | `x=343` | `−12` | 88 | `(130,60) (160,60) (190,60)` |

The Dropper enters on the flight's centreline (88), not the wave's `startY` (60);
the escorts are untouched by the side. Both proved in section 6 of the new suite.

---

## Synthetic-fixture changes

### `tests/test_dropper_flight.py` — the mirrored side is now constructed

Phase 2 proves the mirrored appearance runs through the same routine, so the two
flights must enter from opposite sides. That used to depend on Level 1 happening
to author one Dropper trigger LEFT and another RIGHT; it authors **both LEFT**
today, so the mirrored case stopped existing.

The file now forces the condition it needs: every live trigger's `waveTrigSide` is
set LEFT for phase 1 and RIGHT for phase 2, with a check on each. The side column
is package data like the rows `test_wave_triggers.py` already pokes; nothing on
disk is touched. Both entry sides are now exercised on every run, whatever the
campaign says.

```python
def force_side(value):
    for t in range(rd1(mon, CD.TRIGN_ADDR)):
        poke(mon, sym["waveTrigSide"] + t, value)
    return [...]

sides = force_side(DROP_SIDE_LEFT)      # phase 1
...
sides = force_side(DROP_SIDE_RIGHT)     # phase 2
```

### `tests/test_token_encounter.py` — the protectors are now staged

Phase 5 judged "a dismissed protector visibly ascends". It watched whatever
survived phase 4 — a phase that *deliberately destroys a guard* to prove the
defence is attritional, after which `tkEnlisted` closes the reinforcement gate for
the rest of the encounter. The encounter can therefore end, entirely correctly,
with nothing alive: the check reported `runs {}`, the honest "the case did not
occur" signal.

The condition is now built from production routines:

- `tokenReinforce` (A = post role) spawns each protector — "an ordinary enemy in
  every respect except that it is born already posted";
- the ring centre is pinned (`tkTokXLo/Hi`, `tkTokY`) rather than left wherever
  the last token fell, and `tkEnlisted` is cleared because the gate is a creation
  count;
- they are allowed to walk down into the aperture, so "rose" is measured over real
  travel rather than from the spawn line;
- `tokenDismissUp` (X = slot) dismisses each one, and `tkEgressed` is checked to
  have risen by exactly the number dismissed.

The **claim is unchanged**: a dismissed protector rises, never descends through
the player, and is retired by the ordinary despawn rule. Only the certainty that
there is one to watch is new.

---

## New regression coverage

`tests/test_dropper_escort_contract.py` — 388 lines, **44 checks, ALL PASS**,
11 VICE launched and reaped. Every composition is synthetic (`tests/synth.py`,
package RAM only); no authored level is read for its content.

| § | Contract point | Proved by |
|---|---|---|
| 1 | one-member Dropper Trigger → member 0 Dropper, **no escorts** | `1 spawned, 1 Dropper at member [0]`, no plain members |
| 2 | multi-member → member 0 Dropper, 1..N−1 `lvlPlainRow` | `4 spawned of 4`; escorts at member indices `[1, 2, 3]`, species `[0,0,0]` vs `plainRow 0` |
| 3 | **members 1+ are chosen, not left over** | the flag is cleared after member 0; members 1–3 run with it reading `0` and none becomes a Dropper |
| 4 | existing live Dropper → no second Dropper, all-ordinary wave preserved | `4 spawned of 4`, `0 Dropper(s)`, member 0 fell back |
| 5 | fire-mask numbering; bit 0 does not arm the Dropper | `%0001` arms nothing at all; `%1110` arms members 1–3 only |
| 6 | LEFT/RIGHT unchanged and not the member selector | Dropper is member 0 both ways; `x=0/+12` vs `x=343/−12`; escorts identical |
| 7 | escorts keep the Wave Definition's movement and formation | `startX + index*xStep` = `[130,160,190]`, authored `startY`, authored leg velocity, one shared `wmStage`, trigger colour on every member, ordinary HP, `enyRole 0` |
| 8 | speed unchanged: escorts scale, the flight does not | escorts `6 → 12` across 1.00×→2.00×; Dropper `12 → 12`, while still carrying `wmSpeed 4` then `8` on the object |

Section 3 is the one that matters most, and the file says why: a test that only
counted "one Dropper, N−1 escorts" would pass on **both** seams and prove nothing
about *why* the escorts are escorts.

Section 7 also pins the formation hole deliberately — "no member occupies
`startX`" — so the later movement pass has to decide about it consciously rather
than discover it.

---

## Test results

### Focused suites

| Suite | Baseline | After |
|---|---|---|
| `test_dropper_escort_contract` (new) | — | **ALL PASS** (44 checks) |
| `test_dropper_flight` | FAIL 1/23 | **ALL PASS** |
| `test_token_encounter` | FAIL 1/22, flaky | **ALL PASS** |
| `test_species_order` | PASS | **PASS** |
| `test_pickup` | PASS | **PASS** |
| `test_wave_triggers` | PASS | **PASS** |
| `test_movement_pool` | PASS | **PASS** |
| `test_wave_colour_mode` | PASS | **PASS** |
| `test_aimed_velocity` | PASS | **PASS** |
| `test_square_species` | — | **FAIL — pre-existing, unrelated** |

`test_movement_pool`, `test_wave_colour_mode` and `test_aimed_velocity` are the
other three suites that read the spawn path's output (the trigger columns, the
per-member colour roll and the resolved firing mode), so they are the ones that
would notice if the reordered seam had disturbed anything around it. It did not.

The `test_token_encounter` result below is the second run: the first failed with a
Python `TypeError` in my own staging block, before it reached the machine, because
`harness.call()` could set X but not A. Every check before that block was green on
both runs.

### `make smoke` — **ROUTINE REGRESSION: PASS**

```
CAMPAIGN LOOP: PASS
ENGINE HEALTH: PASS
ROUTINE REGRESSION: PASS
  VICE launched and reaped: [56527]
```

### The one failure, classified

`test_square_species` dies before its first check:

```
File "tests/test_square_species.py", line 102, in fly
  shape = rd(mon, sym["enemyAnimShape"], SPECIES_COUNT * ENEMY_ANIM_STEPS)
KeyError: 'enemyAnimShape'
```

`enemyAnimShape` is a label the **enemy-identity refactor removed** — a level's
animation table is now `LVL_ANIM` in its own `stage_enemies.asm`, copied into the
package. The name survives only in comments, and `git grep` confirms it is absent
from `HEAD`'s `src/` as well as from the working tree, so the suite could not have
passed at this HEAD before this task either. **Not caused by this change**, and
out of scope here: it is a stale-symbol repair of the same family as the
de-freezing task, and belongs with that work rather than inside a Dropper seam
change.

---

## Files changed

```
 src/waves.asm                          52 +  16 -   the seam and its contract
 tests/harness.py                        9 +   3 -   call() can set A as well as X
 tests/test_dropper_flight.py           38 +   6 -   mirrored side constructed
 tests/test_token_encounter.py          57 +   9 -   protectors staged
 tests/test_dropper_escort_contract.py 388 lines     NEW, the contract regression
```

`tests/harness.py` needed one small extension: `call()` could set X but not A, and
`tokenReinforce`'s entry contract takes the post role in the accumulator. Both
register arguments now default to `None`, so no existing caller changes behaviour.
My first attempt passed `a=` to the old signature and died with a `TypeError`
before reaching the machine -- the staging block was the only thing that failed,
with every check before it green.

No other file was modified.

### Campaign content unchanged

`git diff` over `src/level1`, `src/level2`, `src/level3`,
`tools/level_editor/levels/` and `encounter_library.v6.json` is **empty**. No
authored level, wave definition, trigger, movement program or generated `.asm` was
edited, and none was needed: every exact composition the new tests require is
installed into the package's spare room in RAM.

### What was deliberately NOT added

No `dropper_program`, no new trigger column, no second Wave Definition, no
authorable Dropper Movement Program, no editor control, no schema change, no
preview change, no HP change, no selectable escort identity, no token/protector
redesign, no animation or firing change, no renderer/mux/scroller/raster work.

---

## Observations for the later authorable-movement pass

Recorded, not acted on:

1. **The seam now has the hook it will need.** "Member 0 is the Dropper" is a
   test on `wvIndex`. Making the Dropper's position in the formation authorable
   later is a change to *what that byte is compared against*, not a restructure —
   a per-instance `wvDropMember` latched in `waveStartNext` (2 bytes at
   `WAVE_SLOTS = 2`) drops straight in where the literal `0` is now.
2. **`wmSpeed` is already correct on the Dropper's object** (measured: 4 at
   1.00×, 8 at 2.00×). Its flight simply never reads it. A Dropper flying a
   Movement Program would obey trigger speed the moment `src/enemy.asm:596`
   stopped diverting it — `wmApplySpeed` is reached from `wmEnterStage` and
   `wmLoadHeading`, both of which such a Dropper would go through. No new code.
3. **The formation hole is now asserted.** Section 7 pins "no member occupies
   `startX`" for a successful Dropper wave, while a refused one fills it. Whether
   an authored-movement Dropper should keep its formation slot is a design
   decision the test will force someone to make rather than let slide.
4. **Fire-mask bit 0 remains inert and unwarned.** The cheapest improvement
   available is still a validator warning; it needs no runtime change and no
   renumbering. Level 1 trigger 0 authors `%111111` on six members and gets five
   shooters.
5. **`tkDropperLive` is now purely a lifecycle guard**, which is what makes it
   safe to reason about separately. It is claimed in one place
   (`src/waves.asm`), released in one place (`src/enemy.asm:852`, on *either* way
   of leaving), and no longer has a second job.
6. **`movement_sim.py:650` and `controller_v6.py:841` still test
   `species == "DROPPER"` by literal name**, where `validation_v6.py` and
   `encounters_ui.py` use `identity_behaviour`. Harmless with one Dropper identity
   in the roster; it would split with two. Left alone deliberately — touching the
   preview was out of scope.

---

## Confirmation

**Production campaign content is unchanged.** Only the one runtime seam, two test
fixtures and one new test file were modified.

Final `git status`:

```
 M src/waves.asm
 M tests/harness.py
 M tests/test_dropper_flight.py
 M tests/test_token_encounter.py
?? reports/dropper-escort-explicit-contract.md
?? reports/dropper-escort-substitution-audit.md
?? tests/test_dropper_escort_contract.py
```

**Nothing committed and nothing pushed.** No `git checkout`, `git restore`,
`git reset`, `git stash` or destructive clean was used; the old-seam comparison
build was made with `rsync` plus `git show HEAD:src/waves.asm` into a scratch
copy, which has since been deleted. Every VICE launch was owned by exact PID,
launched with `-console`, and reaped in a `finally`; **0 remained** at the end of
each run and **0 remain now**.

Disk: the scratchpad holds 1.8 MB of run logs and two probe scripts; the 9.1 MB
old-seam tree was removed once its measurement was recorded. `build/` holds the
current binaries and symbols only (340 KB, gitignored). Nothing was written to
`/tmp`.
