# Modernising `test_level_assets` for Package-Local Variable-Frame Animation

**Task:** 19656 — Modernise `test_level_assets` for Package-Local Variable-Frame Animation
**Scope:** one test rebuilt; comments only in `src/level_assets.asm`.
**Tree:** `main`, HEAD `1a07c82 More test cleanups`, with the two preceding tasks'
dirty work preserved untouched.

---

## Executive summary

`tests/test_level_assets.py` was the second casualty of the move to package-local
variable-frame animation, flagged by `reports/repair-stale-square-species-test.md`.
It failed nine checks, all cascading from one host-side expectation built out of a
retired model.

It has been rebuilt against the current contract. The package-swap fixture now
does what a real level load does — put different bytes in the package region and
reload — using the **actual emitted format**, with three deliberately unequal run
lengths (3 / 7 / 5, none of them four) so a fixed-four assumption reappearing
anywhere fails here.

**No production defect was found.** The comment cleanup in `src/level_assets.asm`
is provably behaviour-free: the rebuilt binary is **byte-identical**, and `git
diff` adds **zero non-comment lines**.

Two corrections to my own first attempt are recorded below — a coverage-by-luck
check and a counter I asserted that the repository classifies as reported-only.

Three pieces of **dead production state** were found and are **reported, not
removed**, since the brief scoped source edits to comments.

---

## What the old test was trying to prove

Six claims, from its own docstring:

1. the window is aligned, inside VIC bank 0, and overlaps nothing else the VIC
   reads — the memory boundary the whole model rests on;
2. level 1's artwork really landed on the slots its package claims, checked
   against the bytes in the PRG rather than the constants that placed them;
3. the Ring's former pinned home at `$3580` is genuinely vacated;
4. at boot, `enemyAnimSeq` holds pointers **resolved** by `levelAssetsLoad` — RAM,
   not constants baked at assembly;
5. **replacement**: loading a second package re-resolves every entry to different
   slots, in the opposite species order, with no gameplay code aware anything
   moved — and a live enemy's published pointer follows;
6. the engine survives the round trip with the production counters clean.

Every one of those is still worth proving. Claims 1, 3 and 6 are essentially
architecture-independent. Claims 2, 4 and 5 are about *how* the animation data is
represented and resolved, and that is what moved.

---

## Obsolete assumptions found

| Assumption | Reality |
|---|---|
| `SPECIES_COUNT, ANIM_STEPS, FRAMES = 2, 8, 4` | **three** enemy slots, and frame count is per identity |
| `RING_SHAPE` / `DROPPER_SHAPE` literals | shapes are per-identity roster data, composed by the exporter |
| `expected_table()` = `PTR_FIRST + slot + frame index` | the package ships the composed block; the engine adds only the base |
| `L1_RING, L1_DROPPER = 0, 4` | this level packs 8 + 4 + 6, so the runs start at 0 / 8 / 12 |
| `LB_RING, LB_DROPPER = 12, 8` from `level_assets.asm` | **the "Level B" descriptor no longer exists** |
| `call(levelAssetsLoad, x=PKG_B)` | the routine takes **no argument**; it reads the absolute `LEVELPKG_ANIM` |
| `lvlPackage` changes on load | `lvlPackage` is **never written** by any production code |
| `schedBuildDefer` must be zero | classified repository-wide as a bounded cost, reported not asserted |

The first failure said it plainly:

```
FAIL at boot the table holds level 1's resolved pointers
  got  b0 b1 b2 b3 b4 b5 b6 b7  b8 b9 ba bb bb ba b9 b8
  want b0 b1 b2 b3 b0 b1 b2 b3  b4 b5 b6 b7 b7 b6 b5 b4
```

The `got` row was correct throughout — an 8-frame identity followed by a 4-frame
one.

---

## The modern equivalent contract

From `src/level_assets.asm`, the engine's entire remaining job:

```asm
    ldy #LEVELPKG_ANIM_MAX - 1
!entry:
    lda LEVELPKG_ANIM,y
    clc
    adc #LEVEL_PTR_FIRST
    sta enemyAnimSeq,y
    dey
    bpl !entry-
```

So what the test now asserts, none of it naming an identity or a frame count:

| Contract | Check |
|---|---|
| a package carries its **own** resolved data | the bytes in RAM at `LEVELPKG_ANIM` are the bytes `build/level1.prg` shipped (`0 mismatches of 24`) |
| one row per slot | `ANIM_MAX == SLOTS * STEPS` |
| each identity gets a **contiguous run, used in full** | `max-min+1 == len(distinct)` per row |
| rows are **disjoint** | no identity wears another's artwork |
| runs **pack from block 0 in slot order** | the successor to "Ring 0, Dropper 4" |
| **variable frame counts are real** | the run lengths are *not all equal* — asserted as such |
| the artwork is really there | every claimed block is non-blank, and the slots' first frames are distinct drawings |
| the former pinned home stays vacated | no slot's artwork is resident at `$3580` |
| `enemyAnimSeq` is **RAM resolved on demand** | poisoned with `$EE`, then every entry rewritten — `0 entries still poisoned` |
| pointer = package block + window base | exact, for all 24 |
| all pointers inside the window | `$b0..$c1` of `$b0..$c3` |
| **swapping a package re-resolves everything** | see below |
| **runtime lookup uses the new rows** | a live enemy's `logPtr` comes from the newly loaded row for its own slot |

The window's compile-time properties (alignment, bank 0, neighbours, representable
pointers) are kept, but read from `src/main.asm`'s own constants rather than
restated — and noted as already being assembler-guarded there by four `.if`s, so
the build fails before the test would.

---

## Package-swap fixture redesign

The old fixture selected an engine-resident descriptor row that no longer exists.
The new one does **what a real level load does**: a real load copies a new package
into the package region and then calls `levelAssetsLoad`, so the test writes a new
`LEVELPKG_ANIM` there and calls it.

```python
SYN_RUNS = (3, 7, 5)                # frames per slot: all different, no 4

def _syn_table():
    """A well-formed LEVELPKG_ANIM in the CURRENT format: window-relative
    blocks, packed from 0 in slot order, one row of STEPS per slot."""
    out, base = [], 0
    for run in SYN_RUNS:
        out += [base + (step % run) for step in range(STEPS)]
        base += run
    return out
```

That is the emitted format, not a parallel representation: window-relative blocks,
packed in slot order, `SLOTS * STEPS` entries. It is put through the **same
`structure()` helper** as the resident table, so the fixture is held to the same
well-formedness rules it is testing the loader against:

```
info synthetic slot 0: [0, 1, 2, 0, 1, 2, 0, 1]  (3 frames)
info synthetic slot 1: [3, 4, 5, 6, 7, 8, 9, 3]  (7 frames)
info synthetic slot 2: [10, 11, 12, 13, 14, 10, 11, 12]  (5 frames)
```

Recognisable bytes are planted on the blocks it names, so "the pointers address
those blocks" is checked rather than assumed. 15 of 20 window blocks — asserted to
fit before the VICE launch.

**Two checks the old file did not have:**

- **poison before every load.** "The table holds the right values" is also true of
  a table of assembled constants. Filling `enemyAnimSeq` with `$EE` and finding no
  `$EE` afterwards is what proves the loader rebuilt *every* entry rather than
  patching the ones that changed.
- **per-slot frame counts survive.** `(3, 7, 5) wanted (3, 7, 5)`, recovered from
  the resolved pointers.

The old "opposite species order" check is gone. It existed to rule out a loader
that ignored the descriptor and added a constant — and the poison check rules that
out far more directly, because a loader adding a constant to stale data leaves
poison behind.

---

## How variable frame counts are exercised

Three ways, and the third is the one that matters most:

1. **The resident table is asserted to have unequal runs** —
   `frames per slot [8, 4, 6]`. A level that went back to four-everywhere would
   fail this, not silently pass.
2. **The synthetic table uses 3 / 7 / 5** — none of them four, none matching the
   resident level's, and all different from each other. Any arithmetic that
   assumed a fixed stride resolves the wrong blocks and the exact-match check
   fails.
3. **The runtime draws from the 3-frame run.** After the swap, a synthetic wave of
   the *first* slot is installed and the live loop watched:

```
ok   live enemies published window pointers during real play -- ['0xb0', '0xb1', '0xb2']
ok   ...and every one comes from the NEWLY LOADED package's rows
ok   ...specifically from the row of the slot the wave sends -- ['0xb0','0xb1','0xb2'] vs slot 0 ['0xb0','0xb1','0xb2']
```

Three pointers, not four — `enemyAnimPtr` walked eight animation steps across a
**three**-frame identity and never left its run. That is the variable-frame
contract reaching all the way to what the VIC would fetch.

---

## Built bytes, not parser helpers — and why

`LEVELPKG_ANIM` is read out of `build/level1.prg`:

```python
def pkg_anim_from_prg():
    prg = (ROOT / "build" / "level1.prg").read_bytes()
    base = prg[0] | (prg[1] << 8)
    return list(prg[2 + ANIM_AT - base: 2 + ANIM_AT - base + ANIM_MAX])
```

The generated source emits `LVL_ANIM` as a chained
`.eval LVL_ANIM.add(0).add(1)...`, which the editor's `asm_decl` reader rejects
(`trailing tokens after .eval`). Teaching a test-only parser more assembly syntax
to recover an inspection the package itself already answers would be the wrong
trade — and the built bytes are the more authoritative artefact anyway, since they
are what the engine actually loads. This is the same technique
`tests/test_movement_pool.py` uses for the movement pool and wave definitions.

**No shared helper was changed.** `asm_decl` is untouched.

One small local reader was added *inside the test*: `_main_consts()` resolves
`LEVEL_SPRITES`, `LEVEL_SPRITE_BLOCKS`, `LEVEL_SPRITES_END` and `LEVEL_PTR_FIRST`
from `src/main.asm`. The window geometry is engine memory map; reading it means
this file cannot drift from the map, the same reason `tests/campaign_data.py` reads
`src/levelpkg.asm`. It resolves only the plain arithmetic those four actually use.

---

## Stale source-comment update

`src/level_assets.asm`, **comments only**. Three blocks rewritten:

1. **The header's model table** listed `enemyAnimShape` as resident state and
   `levelAssetDescs` as per-level data. It now describes what a package carries:
   the identity in each slot, that identity's frame count, its step order, and the
   bytes — all as data.
2. **The "LEVEL B IS A TEST PACKAGE" paragraph** described a test descriptor that
   no longer exists. Replaced with an explanation of what the package ships and,
   explicitly, why the old two-table model *could not* express variable frame
   counts: "a shape of frame indices says nothing about how many frames exist and
   the slot arithmetic assumed every species was the same size."
3. **`levelAssetsLoad`'s entry contract** said `Entry: X = package index
   (LEVEL_PACKAGE_1 or LEVEL_PACKAGE_B)`. Those constants do not exist and X is
   not read. It now says it takes no arguments and resolves whatever package is
   resident.

Two mentions of the old names survive **deliberately**, in a paragraph that names
them as retired ("IT USED TO BE COMPOSED HERE, out of two separately owned
tables…"). Describing history as history is not staleness.

**Proof this changed no behaviour:**

```
$ cmp shmup_before.prg build/shmup.prg
BINARY BYTE-IDENTICAL: the comment edit changed no code

$ git diff src/level_assets.asm | (added lines that are not comments or blank)
0
```

---

## Was any genuine production defect found?

**No behavioural defect.** Every structural property held on the first run, the
engine's arithmetic matched the shipped package byte for byte, and the swap,
re-resolve and restore all behaved exactly as documented.

**Three pieces of dead state, reported rather than removed** — removing any of
them is a production change, and this pass was scoped to comments:

1. **`lvlPackage` is never written.** `src/level_assets.asm:65` declares it as
   "which package levelAssetsLoad last resolved", and `grep` finds no
   `sta/stx/sty lvlPackage` anywhere in `src/`. The old test asserted it changed
   across a load — one of its nine failures. One byte of RAM and a misleading
   comment.
2. **`tests/run_smoke.py:165` reads it into a dead variable.** `pkg_before` is
   assigned and never used again, which is why smoke has been passing over a
   counter that never moves. Harmless; worth removing next time that file is open.
3. **`lvlDescBase` is marked "(vestigial scratch; the descriptor table is gone)"**
   at `src/level_assets.asm`. Self-documented as dead.

And one stale string outside this pass's remit:

4. **`src/enemy.asm:168`** — an assembly-time `.error` message still reads
   "…means extending enemyAnimShape, enemyFireModeTab, the level descriptor rows
   and this check". Only surfaces if that guard trips, and the brief named
   `src/level_assets.asm` specifically, so it is flagged rather than edited.

---

## Two corrections to my own first attempt

Recorded because both were real mistakes in this pass, not pre-existing issues:

1. **I asserted `schedBuildDefer == 0`** (inherited from the old file) and it read
   `1`. That counter is classified repository-wide as a bounded cost, not a fault:
   `tests/run_smoke.py` lists it in `REPORTED` as *"a documented bounded cost
   ('cannot starve'), not a fault"*, and `src/renderer.asm:377` describes the race
   it counts. Stepping several hundred frames through the monitor is exactly the
   condition that defers a build. Moved to reported-not-asserted, citing that
   classification rather than inventing a tolerance. `gameOverrun`,
   `statPageMismatch` and `statPtrMismatch` remain asserted.
2. **My first live-play check inherited the old coverage-by-luck** and reported an
   empty set: it booted with warp and no exact arrival and sampled 64 frames of
   whatever the stage was doing. Now it boots `exact` and installs its own
   synthetic wave *after* the swap, so every enemy is born under the new rows —
   which also made the tighter "from the sending slot's row" assertion possible.

---

## Test results

### Focused

| Suite | Before | After |
|---|---|---|
| `test_level_assets` | **FAIL** — 9 checks | **ALL PASS** — 38 checks |
| `test_square_species` | PASS (repaired last pass) | **PASS** |
| `test_level_identity` | — | **PASS** |
| `test_species_order` | — | **PASS** |

`test_level_identity` is the established bounded package-swap runtime test — it
builds a disk whose `LEVEL1` is level 2's package and compares two snapshots — so
it is the right companion for a change about package-local resolution.

### The modernised run

```
ok   the window is 64-byte aligned -- $2c00
ok   the window is inside VIC bank 0 -- $2c00-$30ff
ok   the window clears screen page B below it and the clip scratch above
ok   every block in the window has a representable sprite pointer -- $b0..$c3
ok   the synthetic replacement table fits the window too -- 15 blocks of 20, runs (3, 7, 5)
ok   the animation table lives outside VIC bank 0 -- $c410
ok   the package's animation table in RAM is the one the build shipped -- 0 mismatches of 24
ok   it is one row of 8 entries per enemy slot -- 24 entries
info resident slot 0: [0, 1, 2, 3, 4, 5, 6, 7]  (8 frames)
info resident slot 1: [8, 9, 10, 11, 11, 10, 9, 8]  (4 frames)
info resident slot 2: [12, 13, 14, 15, 16, 17, 12, 13]  (6 frames)
ok   resident: the slots' frame runs are DISJOINT
ok   resident: each run is CONTIGUOUS and used in full -- slot 0: 0..7; slot 1: 8..11; slot 2: 12..17
ok   resident: the runs pack from block 0 in slot order -- 18 blocks used
ok   resident: the whole window fits the engine's sprite budget -- 18 blocks of 20
ok   resident: the runs are NOT all the same length -- frames per slot [8, 4, 6]
ok   every block the package claims holds real artwork -- 18 blocks, all non-blank
ok   ...and the slots' first frames are genuinely different drawings -- 3 distinct of 3
ok   no slot's artwork is resident at the former pinned home
ok   the table was poisoned before the loader ran
ok   levelAssetsLoad rewrote EVERY entry -- no poison survived
ok   every pointer is the package's own block plus the window base -- 0 mismatches; base $b0
ok   every resolved pointer addresses a block inside the window -- $b0..$c1
ok   a synthetic package table is resident, in the current format -- runs (3, 7, 5), 15 blocks
info synthetic slot 0: [0, 1, 2, 0, 1, 2, 0, 1]  (3 frames)
info synthetic slot 1: [3, 4, 5, 6, 7, 8, 9, 3]  (7 frames)
info synthetic slot 2: [10, 11, 12, 13, 14, 10, 11, 12]  (5 frames)
ok   synthetic: the slots' frame runs are DISJOINT
ok   synthetic: each run is CONTIGUOUS and used in full
ok   synthetic: the runs pack from block 0 in slot order -- 15 blocks used
ok   synthetic: the runs are NOT all the same length -- frames per slot [3, 7, 5]
ok   reloading re-resolves EVERY entry to the new package's blocks -- 0 mismatches
ok   ...with no poison left, so nothing was skipped
ok   ...and the table really did change -- 20 of 24 entries differ
ok   the new pointers address the bytes planted on those blocks -- slot bases [0, 3, 10]
ok   each slot resolved exactly its own frame count, all different -- (3, 7, 5) wanted (3, 7, 5)
ok   live enemies published window pointers during real play -- ['0xb0', '0xb1', '0xb2']
ok   ...and every one comes from the NEWLY LOADED package's rows
ok   ...specifically from the row of the slot the wave sends
ok   restoring the package's own table resolves it exactly again
ok   gameOverrun is zero after the round trip -- 0
ok   statPageMismatch is zero after the round trip -- 0
ok   statPtrMismatch is zero after the round trip -- 0
info schedBuildDefer 1 (measured, not asserted -- a bounded cost; see tests/run_smoke.py REPORTED)

  launched and reaped: [64014]

=== ALL PASS ===
```

### `make smoke` — **ROUTINE REGRESSION: PASS**

```
CAMPAIGN LOOP: PASS
Frames observed: 4079
  gameOverrun          0
  schedBuildDefer      0   (a bounded cost, not a fault)
ENGINE HEALTH: PASS
ROUTINE REGRESSION: PASS
```

Worth noting beside the counter discussion above: smoke's own 4,079-frame
free-running window reports `schedBuildDefer 0`, while this file's few hundred
monitor-stepped frames reported 1. That is the difference the classification
exists for -- halting and resuming the machine is what defers a build, not the
engine misbehaving.

---

## Files changed

```
 src/level_assets.asm            36 +  30 -   COMMENTS ONLY; binary byte-identical
 tests/test_level_assets.py     387 + 168 -   rebuilt against the current model
```

No other file was modified by this pass. No generated level, no editor module, no
campaign document, and no runtime or exporter behaviour.

The two preceding tasks' dirty work is preserved exactly:
`src/waves.asm`, `tests/harness.py`, `tests/test_dropper_flight.py`,
`tests/test_token_encounter.py`, `tests/test_square_species.py`,
`tests/test_dropper_escort_contract.py` and the three earlier reports.

---

## Confirmation

Final `git status`:

```
 M src/level_assets.asm
 M src/waves.asm
 M tests/harness.py
 M tests/test_dropper_flight.py
 M tests/test_level_assets.py
 M tests/test_square_species.py
 M tests/test_token_encounter.py
?? reports/dropper-escort-explicit-contract.md
?? reports/dropper-escort-substitution-audit.md
?? reports/modernise-level-assets-test.md
?? reports/repair-stale-square-species-test.md
?? tests/test_dropper_escort_contract.py
```

This pass added exactly two lines to that list: `src/level_assets.asm` (comments
only, binary byte-identical) and `tests/test_level_assets.py`. Everything else was
already dirty when it started and is unchanged by it.

**Nothing committed and nothing pushed.** No `git checkout`, `git restore`,
`git reset`, `git stash` or destructive clean was used. Every VICE launch was
owned by exact PID, launched with `-console`, and reaped in a `finally`.

**Dropper movement work has not been started, and this pass ends here.**
