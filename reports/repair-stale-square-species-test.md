# Repairing the Stale Square Species Test

**Task:** 19656 — Repair Stale Square Species Test
**Scope:** test-only. One file rewritten; no production code or content changed.
**Tree:** `main`, HEAD `1a07c82 More test cleanups`, with the previous task's
dirty work preserved untouched.

---

## Executive summary

`tests/test_square_species.py` died before its first check with
`KeyError: 'enemyAnimShape'`. It was reading **two** symbols that no longer
exist — `enemyAnimShape` and `levelAssetDescs` — and it was stale in a second,
more interesting way that a rename would not have caught: it asserted the three
animation rows were built from `$b0`/`$b4`/`$b8`, three species four blocks
apart, because every species used to wear exactly four frames.

The behavioural contract the file was protecting is intact and worth keeping. It
has been rebuilt against the current package-local animation model, with the
composition checked where it now happens and the encounters made synthetic.

**No production defect was found.** The current architecture is authoritative and
behaves exactly as `src/level_assets.asm` documents. The test was wrong, not the
engine.

Result: **25 checks, ALL PASS**, three VICE launches (down from three much longer
ones), and no coupling to Level 1's authoring left in the file.

---

## What the old test was trying to prove

From its own docstring, seven things:

1. does `levelAssetsLoad` resolve a **third** animation row, holding the third
   species' own sprite pointers in the authored shape?
2. does a wave whose species byte is `SPECIES_SQUARE` actually spawn?
3. do the spawned objects carry that species for life?
4. can several be alive at once, the way Rings can and Droppers deliberately
   cannot?
5. does the one-live-Dropper substitution leave them alone?
6. do they move, and do they eventually despawn?
7. and do Ring and Dropper still behave exactly as they did?

Items 2–7 are **behavioural claims about an ordinary third enemy slot** and are
as valid today as they were written. Item 1 is a claim about *how* the animation
pointers get built, and that is the part the architecture moved.

---

## Why `enemyAnimShape` became stale

`src/level_assets.asm` still describes the old model in the comment above
`levelAssetsLoad`:

```
//     the SHAPE   enemyAnimShape  -- frame indices; resident species behaviour
//     the SLOT    levelAssetDescs -- where this level put that species' frames
//
//     pointer = window base + slot + frame index
```

Two separately owned tables, composed **at level-load time by the engine**.

Both halves have since moved out of the engine and into the level package.
`tools/sprite_export/import_spd.py` now composes slot and shape itself and emits
one window-relative **block** per (species, step):

```python
for (r, b), sp in zip(layout, names):
    row = ".".join(f"add({b + step})" for step in r.steps)
    lines.append(f"    .eval LVL_ANIM.{row}   // {sp}: {r.label}")
```

That list becomes `LEVELPKG_ANIM` (24 bytes at `$ff93`), and
`levelAssetsLoad`'s entire remaining job is one add per entry — its own comment
now says so:

```asm
    // THE PACKAGE HAS ALREADY DONE THE ARITHMETIC. Every byte of the table is
    // a window-relative BLOCK, so all that is left is the window's own pointer
    // base. No species division, no descriptor row, no frame count.
    ldy #LEVELPKG_ANIM_MAX - 1
!entry:
    lda LEVELPKG_ANIM,y
    clc
    adc #LEVEL_PTR_FIRST
    sta enemyAnimSeq,y
    dey
    bpl !entry-
```

So the two symbols were not renamed. **The composition they represented stopped
happening at run time at all**, which is why the right repair was to check the
contract where it now lives rather than to hunt for a replacement name.

### The second staleness, which mattered more

The old expectations were:

```python
want_ring    = [0xB0 + f for f in RING_SHAPE]     # slot 0, 4 frames
want_dropper = [0xB4 + f for f in DROPPER_SHAPE]  # slot 4, 4 frames
want_square  = [0xB8 + f for f in SQUARE_SHAPE]   # slot 8, 4 frames
check("the level's descriptor row is Ring 0, Dropper 4, Square 8", ...)
```

A slot now holds **any roster identity**, and an identity owns **its own frame
count**. Level 1 today packs 8 + 4 + 6 blocks, so the rows actually start at
`$b0`/`$b8`/`$bc`:

```
slot 0 (species row 0):  b0 b1 b2 b3 b4 b5 b6 b7     Ring 3, 8 frames
slot 1 (species row 8):  b8 b9 ba bb bb ba b9 b8     Dropper, 4 frames, ping-pong
slot 2 (species row 16): bc bd be bf c0 c1 bc bd     Space Whisk, 6 frames
```

Renaming a symbol would have left all three `want_*` literals wrong. The
assertions had to be rebuilt from what the contract now *is*.

---

## The current equivalent contract

Five structural properties the runtime depends on, none of which mentions an
identity, a frame count or a slot offset:

| Contract | Why it matters |
|---|---|
| `enemyAnimSeq[i] == LEVELPKG_ANIM[i] + LEVEL_PTR_FIRST` for every entry | **the engine's entire remaining job**, checked against the package that shipped |
| every pointer lies inside the enemy sprite window | a pointer outside it draws someone else's memory |
| the three rows use **disjoint** blocks | no slot wears another's artwork — the successor to "the Ring's row is unchanged" |
| each row's blocks form a **contiguous run, used in full** | a species owns exactly its artwork's frame count |
| the runs **pack from the window base in slot order** | the successor to "Ring 0, Dropper 4, Square 8", with the step sizes coming from the artwork instead of a fixed four |

Plus the link that makes the table worth checking at all, which the old file did
not assert: **every live enemy's `logPtr` comes out of its own row, on every
frame it is alive.** That ties the resolved table to what the runtime actually
draws.

And one identity-free restatement of "the Square is ordinary": the third slot row
is **not** `lvlDropRow`, read from the engine's own byte rather than assumed to be
the middle slot.

---

## Exact test changes

`tests/test_square_species.py` — 284 insertions, 153 deletions (220 → 351 lines).

### Removed

| Removed | Why |
|---|---|
| `rd(mon, sym["enemyAnimShape"], ...)` | symbol gone; the shape is composed by the exporter now |
| `rd(mon, sym["levelAssetDescs"], 8)` | symbol gone; the slot is composed by the exporter now |
| `SQUARE_SHAPE` / `RING_SHAPE` / `DROPPER_SHAPE` literals | frame shapes are per-identity roster data, not engine constants |
| `want_square = [0xB8 + f ...]` and the other two | slot offsets now follow the chosen artwork's frame counts |
| `check("the level's descriptor row is Ring 0, Dropper 4, Square 8", ...)` | replaced by the derived packing check |
| `check("every Square pointer addresses the Square's own art at $2e00", ...)` | a hard-coded address for one identity's artwork |
| `_due_triggers()` — read `levels/level1/level.v6.json` and counted triggers whose `worldProgress * 8` fitted the frame budget | **double coupling to mutable content**: the authored trigger count *and* their rows |
| poking the authored species column for 8 triggers | Level 1 authors 5; the surplus wrote into padding the director never reads |
| `SPECIES_RING, SPECIES_DROPPER, SPECIES_SQUARE = 0, 8, 16` | replaced by `synth.SLOT_ROW`, derived from `ENEMY_ANIM_STEPS` |
| `MAX_FRAMES = 2300` × three sessions | synthetic rows are early, so 700 frames reaches everything |

### Added

- `_pkg_anim()` — reads `LEVELPKG_ANIM` out of `build/level1.prg`. The generated
  `LVL_ANIM` is emitted as a chained `.eval LVL_ANIM.add(0).add(1)...`, which the
  editor's `asm_decl` reader rejects (`trailing tokens after .eval`); the built
  bytes are the more authoritative artefact anyway, since they are what the engine
  loads. This is the same technique `test_movement_pool.py` uses for the movement
  pool and the wave definitions.
- the five structural checks in the table above, plus the window-budget check.
- the `logPtr`-in-own-row check, sampled every frame of every live enemy.
- `fly(schedule, label)` now installs a **synthetic** schedule via
  `tests/synth.py` — `[(row, species), ...]`, one shared definition, exact member
  count — instead of poking the authored species column. Package RAM only.
- the token-dropping row is read from `lvlDropRow` inside a session that is
  already open, so identifying it costs no extra VICE launch.

### A message that misread on success

My first pass inherited the original's phrasing for one check and the extra text
prints on success as well as failure, so it read:

```
ok   every live enemy carried the third slot's species for its whole life -- a live enemy carried another species
```

Fixed to state what was seen rather than what a failure would have meant:

```
ok   ... -- species row 16 only, over 700 frames
```

---

## Was any production defect found?

**No.** Every structural property held on the first run, the engine's arithmetic
matched the package byte for byte (`0 mismatches`), and all seven behavioural
claims the old file made are true of the current build. `src/level_assets.asm`
does exactly what its comment says.

Two observations that are *not* defects, recorded for completeness:

1. **`src/level_assets.asm`'s comment still describes the retired model** — the
   `enemyAnimShape` / `levelAssetDescs` paragraph sits above a routine that no
   longer works that way, immediately followed by a paragraph that describes what
   it does now. It is confusing to read but nothing depends on it. Correcting a
   comment was not in scope for a test-only pass; flagging it here instead.
2. **`asm_decl` cannot parse a chained `.eval NAME.add(x).add(y)`**, which is the
   form `LVL_ANIM` is emitted in. It raises `trailing tokens after .eval`. Only
   the editor's own importer uses that reader and it never reads
   `stage_enemies.asm`, so nothing is broken — but a future test that wants
   `LVL_ANIM` from source rather than from the built package will hit it.

---

## Test results

### Focused

| Suite | Before | After |
|---|---|---|
| `test_square_species` | **FAIL** — `KeyError: 'enemyAnimShape'`, 0 checks reached | **ALL PASS** — 25 checks |
| `test_species_order` | PASS | **PASS** |
| `test_level_assets` | — | **FAIL — 9 checks, same root cause, different file** |

`test_level_assets` and `test_species_order` are the two suites that touch the
same ground: the first reads `enemyAnimSeq` at boot, the second drives the species
column to prove authored species order.

### `test_level_assets` is stale in exactly the same way — REPORTED, NOT FIXED

Running the companions turned up a **second** file carrying the retired
fixed-four-frames model. It is untouched by this pass (`git status` shows no
modification), so its failure is pre-existing by construction, and it is the same
root cause rather than a new one:

```
tests/test_level_assets.py:57
RING_SHAPE    = [0, 1, 2, 3, 0, 1, 2, 3]
DROPPER_SHAPE = [0, 1, 2, 3, 3, 2, 1, 0]
    return ([PTR_FIRST + ring_slot + f for f in RING_SHAPE] +
            [PTR_FIRST + dropper_slot + f for f in DROPPER_SHAPE])
```

Two species, four frames each, composed host-side from a shape and a slot — the
model that moved into the exporter. Its first failure says so plainly:

```
FAIL at boot the table holds level 1's resolved pointers
  got  b0 b1 b2 b3 b4 b5 b6 b7  b8 b9 ba bb bb ba b9 b8
  want b0 b1 b2 b3 b0 b1 b2 b3  b4 b5 b6 b7 b7 b6 b5 b4
```

The `got` row is correct: Ring 3's eight frames followed by the Dropper's four.

Nine checks fail, and they cascade from that one expectation — the file also
plants its own "Level B" descriptor bytes and swaps packages, which the current
package-local model does not consume, so the swap half of the file needs
rebuilding too (its `schedBuildDefer is zero -- 1` is a knock-on of the failed
swap, not an independent finding).

**Deliberately not fixed here.** This pass was scoped to `test_square_species`,
and rebuilding `test_level_assets`'s package-swap fixture is a comparable piece of
work to the one just done, not a line or two. It is flagged rather than folded in
so the decision stays visible. The structural checks written for
`test_square_species` transfer to it directly: compare `enemyAnimSeq` against the
built package's `LEVELPKG_ANIM` plus the window base, and assert disjoint
contiguous runs instead of literal shapes.

### The repaired run

```
ok   the table is one row of 8 pointers per enemy slot -- 24 entries in RAM, 24 in the package
ok   every pointer is the package's own block plus the window base -- the whole of
     levelAssetsLoad's arithmetic -- 0 mismatches; base $b0
ok   every pointer addresses a block inside the enemy sprite window -- pointers $b0..$c1, window $b0..$c3
info slot 0 (species row 0):  ['0xb0','0xb1','0xb2','0xb3','0xb4','0xb5','0xb6','0xb7']
info slot 1 (species row 8):  ['0xb8','0xb9','0xba','0xbb','0xbb','0xba','0xb9','0xb8']
info slot 2 (species row 16): ['0xbc','0xbd','0xbe','0xbf','0xc0','0xc1','0xbc','0xbd']
ok   the slots' rows are DISJOINT: no slot borrows another's artwork -- slot 0: 8 blocks; slot 1: 4 blocks; slot 2: 6 blocks
ok   each slot's blocks form a CONTIGUOUS run, used in full -- slot 0: $b0..$b7 (8); slot 1: $b8..$bb (4); slot 2: $bc..$c1 (6)
ok   the runs pack contiguously from the window base, in slot order -- slot 0 at $b0; slot 1 at $b8; slot 2 at $bc
ok   ...and the whole window fits the engine's sprite budget -- 18 blocks of 20
ok   the third slot is NOT the token-dropping slot: it is an ordinary species -- third slot row 16, drop row 8

=== a wave of the third slot's species ===
ok   its trigger started -- 1 started
ok   it actually spawned -- peak 4
ok   SEVERAL are alive at once, as the first slot's may be -- peak 4
ok   not one object was ever committed as a Dropper -- peak 0
ok   every live enemy carried the third slot's species for its whole life
ok   every one of them draws from its OWN animation row, every frame -- all pointers inside $bc..$c1
ok   they move under the ordinary movement system
ok   they despawn rather than accumulating -- peak 4, spawned 4, final 0
ok   the pool never overflowed

=== the first slot and the Dropper, beside it ===
ok   the first slot's species still spawns
ok   the Dropper still spawns
ok   NEVER more than one live Dropper -- the rule still holds -- peak 1
ok   no third-slot enemy appeared from nowhere
ok   all three enemy slots appear in one run -- slot 0 peak 4; slot 1 peak 1; slot 2 peak 4
ok   ...and the one-live-Dropper rule is unaffected by the others -- peak 1

  launched and reaped: [59830, 59895, 59977]

=== ALL PASS ===
```

### `make smoke` — **ROUTINE REGRESSION: PASS**

```
CAMPAIGN LOOP: PASS
Frames observed: 3995
  gameOverrun 0   scrollLate 0   edgeLate 0   statOverflow 0
  statPageMismatch 0   statPtrMismatch 0   objDoubleFree 0
  objAllocFail 0   clipPoolFull 0   publishSkip 0
  schedBuildDefer 0    statLate 0
ENGINE HEALTH: PASS
ROUTINE REGRESSION: PASS
  VICE launched and reaped: [60680]
```

---

## Files changed

```
 tests/test_square_species.py   284 +  153 -   rewritten against the current model
```

**No production code or content was changed.** No `src/` file, no generated
level, no editor module, no campaign document.

The previous task's dirty work is preserved exactly as it was:
`src/waves.asm`, `tests/harness.py`, `tests/test_dropper_flight.py`,
`tests/test_token_encounter.py`, `tests/test_dropper_escort_contract.py` and the
two reports are untouched by this pass.

---

## Confirmation

Final `git status`:

```
 M src/waves.asm
 M tests/harness.py
 M tests/test_dropper_flight.py
 M tests/test_square_species.py
 M tests/test_token_encounter.py
?? reports/dropper-escort-explicit-contract.md
?? reports/dropper-escort-substitution-audit.md
?? reports/repair-stale-square-species-test.md
?? tests/test_dropper_escort_contract.py
```

`tests/test_square_species.py` is the only line this pass added to that list.
Everything else was already dirty when it started and is byte-identical to how it
was left.

**Nothing committed and nothing pushed.** No `git checkout`, `git restore`,
`git reset`, `git stash` or destructive clean was used. Every VICE launch was
owned by exact PID, launched with `-console`, and reaped in a `finally`.

**No authorable Dropper movement work was begun.**
