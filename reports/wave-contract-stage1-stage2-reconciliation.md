# Reconciling Stage 1 + harness repair + Stage 2 after a stale checkout

**Date:** 2026-09-18
**Outcome:** reconciled cleanly. Local is now **level with `origin/main`** at `6d30ec7`, with Stage 2 replayed on top as uncommitted work. All three contracts coexist and are proven.
**Nothing was pushed. No new commits were created.**

---

## 1. The divergence, precisely

It was **not** a divergence. Local was cleanly **behind by one commit, ahead by zero**:

```
$ git rev-list --left-right --count origin/main...HEAD
behind origin/main: 1   ahead: 0

$ git log --oneline HEAD..origin/main
6d30ec7 Tests updated
```

| | |
|---|---|
| local HEAD at start | `8f79574` *Memory reshuffle to accomodate longer levels* |
| upstream | `origin/main` = `6d30ec7`, a **direct child** of `8f79574` |
| uncommitted | Wave Contract Stage 2 — 5 modified files, 4 untracked |
| stashes | none |

**The cause:** `6d30ec7` (Stage 1 + the harness repair) was committed and pushed from the other machine. This machine never pulled it, so Stage 2 was built on `8f79574` instead of on top of Stage 1. Because history was still **linear** — no local commits after `8f79574` — the fix was a fast-forward plus a replay, not a merge or rebase of divergent branches.

`6d30ec7` contains **both** outstanding jobs:

```
reports/test-harness-frame-accurate-boot-repair.md    607 +
reports/wave-contract-stage1-absolute-trigger-rows.md 575 +
src/waves.asm                                         229 +-      <- Stage 1
tests/harness.py                                      131 +-      <- harness repair
tests/test_wave_triggers.py                           497 +       <- Stage 1 proof
tests/test_pickup.py                                  249 +-      <- stale waveTrigTokenLo repair
tests/test_production.py, test_encounter_director.py, +8 more     <- caller migration
```

---

## 2. Protective steps

Nothing destructive was used at any point. **No `git reset --hard`, no `git clean`, no forced checkout.**

1. **Plain-file backup first** — all nine Stage 2 files copied to disposable scratch, plus `git diff > stage2-tracked.patch` (19,447 bytes). Recoverable even if every Git mechanism failed.
2. **`git stash push --include-untracked`** — the reversible Git mechanism, capturing tracked edits *and* the four new files.
3. **`git merge --ff-only origin/main`** — chosen deliberately over `pull`: it refuses rather than creating a merge commit if a fast-forward is not possible. It fast-forwarded.
4. **`git stash pop`** — replayed Stage 2 onto the new base.

Every step was verified before the next.

---

## 3. What was recovered vs reconstructed

**Everything accepted was recovered as the exact upstream commit. Nothing was reimplemented from memory.**

| work | source |
|---|---|
| Stage 1 absolute trigger rows | **recovered** — `6d30ec7`, byte for byte |
| Harness frame-accurate boot repair | **recovered** — `6d30ec7`, byte for byte |
| Stage 2 movement semantics + external pool | **replayed** — my own uncommitted work, unchanged |

---

## 4. Conflicts and their resolution

**`git stash pop` reported no conflicts.** Git's three-way merge resolved `src/waves.asm` automatically because the two jobs touched disjoint regions of the file:

| region | owner |
|---|---|
| ~lines 110–340: movement program import, arc byte-3 guard, flight simulator | **Stage 2** |
| ~lines 456–900: trigger data, director state, `waveTick`, `waveStartNext`, `waveAdvanceCursor` | **Stage 1** |
| ~line 1354: `waveStageTable` label | **Stage 2** |
| ~lines 1377–1480: emitted trigger tables | **Stage 1** |

**A clean textual merge is not proof of a correct one**, so both contracts were verified explicitly in the merged source *and* in the built binaries (§5, §6). `tests/harness.py` was changed only by `6d30ec7` — Stage 2 never touched it — so there was no contention there either.

No file was resolved "ours" or "theirs", and no unrelated cleanup was introduced.

---

## 5. Final trigger contract (Stage 1, intact)

```asm
.var trigRow = List().add(48, 52, 90, 126)      // absolute, authored
waveTrigRowLo / waveTrigRowHi                   // 16-bit, 6 bytes per trigger
waveAdvanceCursor:
    inc wvNextTrig
    rts                                         // no wrap, no clamp, no carry chain
```

Verified **in the assembled binary**, not merely in source:

```
STAGE 1: waveTrigRowLo = $7ed2, trigger table 24 bytes (6 per trigger)
STAGE 1: authored trigger rows in the binary = [48, 52, 90, 126]
```

- due comparison remains 16-bit `worldProgress >= authoredRow`;
- `wvNextTrig` is documented "0..WAVE_TRIGGERS inclusive" and simply stops at 4;
- **no delta table, wrap period, seed/carry chain or token target-walking exists.** The only remaining mention of `wvNextAt` is a comment recording that it was removed.

---

## 6. Final movement contract (Stage 2, intact)

Byte 3 of an `ARC`/`ARC_MIRROR` record is its **entry heading** (0..63), or **`WM_HEAD_CONT` ($ff)** meaning "continue from the heading already held". `WM_STRAIGHT`, `WM_HOLD` and `WM_EXIT` still never touch `wmPhase`.

Verified in the built package:

```
STAGE 2: arc entry headings = [(1, 0), (3, 12), (4, 255), (8, 10), (11, 8)]
```

Record 4 carries `255` — the S-turn's join, the one intentional continuation, still explicit. Undocumented phase inheritance has **not** crept back.

### The `$F530` pool

```
$e000-$e419   level map                 1,050 B   (4,200 B in the 420-row proof)
$f130-$f34f   metatile definitions        544 B
$f530-$f563   MOVEMENT PROGRAM POOL        52 B   = 13 records x 4 bytes
$fb70-$fb73   package signature             4 B
$fffa-$ffff   hardware vectors                    (never touched)
```

- `waveStageTable` resolves to **`$f530`** — verified from `build/main.vs`;
- program start offsets **0, 12, 24, 40** — verified against the implementation, unchanged;
- **no authoritative engine-resident duplicate** — the test asserts the 52 bytes are absent from `shmup.prg`;
- guards retained for four-byte records, the 256-byte `wmStage` ceiling, encounter-package boundaries and collision with the signature/vectors.

---

## 7. Uncommitted files after reconciliation

```
 M Makefile                   (test-movement-pool target)
 M src/level_package.asm      (emits the pool at $f530)
 M src/levelpkg.asm           (LEVELPKG_MOVE + guards)
 M src/movement.asm           (arc entry reads byte 3)
 M src/waves.asm              (imports wave_programs; waveStageTable -> $f530)
?? src/movement_format.asm    (shared record format)
?? src/wave_programs.asm      (the authored programs)
?? tests/test_movement_pool.py
?? reports/wave-contract-stage2-movement-pool.md
?? reports/wave-contract-stage1-stage2-reconciliation.md   (this file)
```

```
 Makefile              |   5 +-
 src/level_package.asm |  37 ++++++++
 src/levelpkg.asm      |  26 ++++++
 src/movement.asm      |  79 +++++-----------
 src/waves.asm         | 148 ++++++----------------------
```

---

## 8. Focused proofs — both pass on the reconciled tree

```
### test_wave_triggers (Stage 1)
=== absolute 16-bit wave trigger rows ===
=== ALL PASS ===

### test-movement-pool (Stage 2)
=== ALL PASS ===
```

Stage 2's seventeen assertions include the stale-phase proof — each explicit arc entered three times with a deliberately corrupted `wmPhase`, including the value a stale earlier arc would plausibly have left — plus the `$f530`-vs-package byte comparison and the no-duplicate check.

---

## 9. Combined 420-row integration proof — ALL PASS

Run with the repaired **`boot="exact"`**, so the traversal begins at `worldProgress` 0 and every authored trigger falls inside the window.

```
ok  EXACTLY FOUR authored waves start across the whole 420-row stage
    -- the old wrapped 52 is gone -- wvStarted = 4
ok  the trigger cursor is exhausted and stays there -- wvNextTrig = 4 (WAVE_TRIGGERS = 4)
ok  no trigger was dropped -- wvDropped = 0
ok  the stage completed at the derived final progress 1655
ok  the traversal really crossed every 8-bit boundary -- final worldProgress 1655
ok  the scroller froze on the last complete authored screen (stageTopRow 0)
ok  the fine scroll froze too -- 0
ok  the boss phase was reached after the long stage -- lvlPhase 2
ok  the movement pool at $f530 still matches the built package after the traversal -- intact
ok  the package signature at $fb70 is intact after the traversal -- intact
ok  the metatile definitions at $f130 are intact after the traversal -- intact
ok  gameOverrun is zero across the whole 420-row traversal -- 0
ok  scrollLate is zero across the whole 420-row traversal -- 0
ok  one coarse row still takes 8 displayed frames -- 13 intervals, min 7.92 max 8.08
[note] wvSpawned = 13 enemies from those four waves
[note] publishSkip = 12, schedBuildDefer = 1
```

**This is the headline number: `wvStarted = 4`.** Before reconciliation the same probe on the same 420-row stage reported **52** — the delta list wrapping about thirteen times. Stage 1's absolute rows are demonstrably in force across a 1,655-row level, and 13 spawned enemies is exactly the four definitions' member counts (4+3+3+3).

---

## 10. Broader suite

| target | result | change vs pre-reconciliation baseline |
|---|---|---|
| `test-boot` | **ALL PASS** | same |
| `test-production` | **ALL PASS** | **improved** — `publishSkip` failure gone (the exact boot removed the warped free-run that caused it) |
| `test-pickup` | **ALL PASS** | **repaired** — was `KeyError: 'waveTrigTokenLo'` |
| `test-turret-regression` | **ALL PASS** | same |
| `test-boss` | **ALL PASS** | same |
| `test-lifecycle` | **ALL PASS** | same |
| `test-player-death` | **ALL PASS** | same |
| `test_bank2_arena` | **ALL PASS** | same |
| `test-encounter-director` | `publishSkip` = 11, `schedBuildDefer` = 1 | noise, and **halved** (was 22) |
| `test_token_encounter` | **7 failures** | **inherited — see below** |

### `test_token_encounter`: inherited, not caused here

I did not assume this. I built **pristine `6d30ec7` in scratch, without Stage 2**, and ran the same test:

```
=== 7 FAILURES: a guard swept several quadrants about the token...;
    the patrol ring is as wide as the constants say; ...and never collapses onto
    the token; the three guards stay spread around the token, not bunched; the
    three guards are never all stationary together; a killed guard was replaced;
    schedBuildDefer is zero with the encounter run end to end ===
```

**Identical seven failures, same messages, without any Stage 2 code present.** The reconciliation did not cause them.

Cause, from the commit itself: `6d30ec7` migrated this file to `boot="exact"` with the note *"since Wave Contract Stage 1 they exist only around the four authored encounters at coarse rows 48, 52, 90 and 126 — Level 1 is deliberately quiet afterwards."* The failure detail lines read `0 settled frames`, `widest standoff seen 0 px`, `refilled after None frames` — the test is finding **no settled frames at all**, i.e. the encounter never reaches the state it asserts about under the new boot.

That is a **genuine inherited regression in the accepted remote work, not diagnostic noise**, and it deserves its own task. Per this brief I did not touch it and did not weaken a single assertion.

`publishSkip` / `schedBuildDefer` remain established low-level noise; both are **lower** than the pre-reconciliation baseline, not worse.

---

## 11. Manual VICE

**PID 37914** — the reconciled build, PAL, visible, **non-warp**, launched without stealing focus.

Expect: the four authored encounters at rows 48, 52, 90 and 126 — sweep, S-turn, linger, loop — flying exactly as before, and then a **deliberately quiet level** afterwards, which is Stage 1's intended behaviour rather than a fault. Manual visible output remains authoritative for movement and rendering; that judgement is yours.

Close it yourself, or say the word and I will terminate that exact PID.

---

## 12. Hygiene

`pgrep -x x64sc` confirmed a clean field before every run; every automated instance was reaped by exact PID (35155 and each harness's own) and reported. No broad `pkill`/`killall`; no user-launched instance touched. The scratch copy of pristine `6d30ec7` was deleted after use.

```
$ du -sh build/    344K      (includes build/proof420; 96K after a plain `make build`)
$ du -sh .         8.8M
$ scratch          708K      (Stage 2 backup + probes, outside the repository)
```

---

## 13. Git state, and what to do next

| | |
|---|---|
| **local HEAD** | `6d30ec7` *Tests updated* |
| **upstream HEAD** | `origin/main` = `6d30ec7` |
| **relationship** | **level — 0 behind, 0 ahead.** Not diverged. |
| **uncommitted** | Wave Contract Stage 2: 5 modified, 5 untracked (incl. two reports) |
| **new commits created** | **none** |
| **pushed** | **nothing** |

**Yes — it is now safe to review and commit Stage 2.** It sits cleanly on top of the accepted Stage 1 + harness base, all three contracts are proven to coexist, and the working tree is exactly the reviewable state the brief asked for.

### Recommended next action

```bash
git add -A
git commit -m "Wave contract stage 2: deterministic ARC entry, movement pool at \$f530"
```

`git add -A` is appropriate here because every untracked file listed in §7 is intended Stage 2 content. If you would rather keep the reports separate from the code, commit `src/`, `tests/` and `Makefile` first and the two `reports/` files second.

The stash was popped and dropped, so there is nothing left parked in Git; the scratch backup remains until this session's scratch is cleared.

**Recommended follow-up task, not started here:** `test_token_encounter`'s seven inherited failures (§10). They arrived with `6d30ec7` and are the one genuinely unresolved item in the reconciled tree.
