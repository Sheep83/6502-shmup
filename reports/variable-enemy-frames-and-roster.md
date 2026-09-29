# Variable enemy frame counts + the full sprite roster in the editor

**Date:** 2026-09-29
**Engine, package, importer, editor and verifier changes. No gameplay changes.**
**Committed or pushed:** no. **No destructive git operation was used.**

---

## 0. The design decision, stated first because everything follows from it

**A roster entry is ARTWORK, not a species.**

In this engine a *species* is a **behaviour**: `SPECIES_DROPPER` has its own
movement in `src/enemy.asm` and its own handling in `src/waves.asm`,
`src/waves.asm` validates an authored species by membership of the three, and
`src/token.asm` spawns a `SPECIES_RING` by name. Turning twelve artwork
sequences into twelve gameplay species would mean inventing movement, health,
collision and firing for nine of them — which this brief forbids and which its
"do not change" list rules out line by line.

So the roster is twelve **sequences of bitmaps**, and a level chooses **which
artwork each of its three behavioural species wears**. That delivers everything
asked for — variable frame counts, full-frame playback, an editor roster, the
20-slot budget, compact packages — and invents no gameplay. Species-per-level
stays at three, as instructed.

If you meant twelve *behavioural* species, this is the thing to tell me: it is a
much larger task and it starts with movement programs, not artwork.

---

## 1. Before

| | |
|---|---|
| frames per species | `ENEMY_FRAMES = 4`, engine-wide, plus `DROPPER_FRAMES`/`SQUARE_FRAMES` and a guard that they were all equal |
| animation steps | `ENEMY_ANIM_STEPS = 8`, a power of two so the phase could be masked out of a free-running `frameCounter` |
| step → frame | `enemyAnimShape`, resident, 3 rows × 8 frame INDICES (Ring `0,1,2,3,0,1,2,3`; Dropper and Square `0,1,2,3,3,2,1,0`) |
| where the art was | a per-level 20-block window at `$2c00`–`$30ff`, filled from the level package |
| where the slots were | `levelAssetDescs`, **resident**, one row per package, built at assembly time from the build-time level's `stage_enemies.asm` |
| species per level | 3 |

`levelAssetsLoad` resolved `pointer = LEVEL_PTR_FIRST + slot + shape[step]` once
at boot, out of that resident table.

### A bug that fell out of the audit

Because the descriptor was **resident and resolved once**, every level in the
campaign had to use the same slot layout as the level the binary was built
against. Level 2 only worked because its `stage_enemies.asm` was a byte copy of
Level 1's. A level that chose different artwork — which is exactly what this
task introduces — would have been drawn with Level 1's pointers. That is fixed
here as a consequence of the redesign, not as a separate change.

---

## 2. The new architecture

**The package carries 24 resolved bytes and the engine adds one number.**

A level package now ships `LEVELPKG_ANIM` — `SPECIES_COUNT × ENEMY_ANIM_STEPS`
= 24 bytes, one per (species, step), each holding the **window-relative BLOCK**
that step shows. `levelAssetsLoad` is now:

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

Fifteen bytes of code at `$4b00`. There is no species division, no descriptor
row, no frame count and nothing to compare. **A species wearing eight-frame
artwork simply names eight different blocks in its row; one wearing three-frame
artwork names three.** Nothing at run time counts frames, which is why the
supported range is 1–8 without the engine knowing the range exists.

The hot path is untouched: `phase = (frameCounter >> 3) & 7`,
`index = species ORA phase`, `pointer = enemyAnimSeq[index]`.

### Package-local frame base and runtime pointer

```
packing (export time)    base(0) = 0;  base(n) = base(n-1) + frames(n-1)
table   (export time)    anim[species][step] = base(species) + shape[step]
pointer (run time)       LEVEL_PTR_FIRST + anim[species][step]
                         LEVEL_PTR_FIRST = $2c00 / 64 = $b0
```

### Every fixed-four assumption, and what happened to it

| Assumption | Where | Outcome |
|---|---|---|
| `ENEMY_FRAMES = 4` | `src/enemy.asm` | **removed** — no engine-wide answer exists any more |
| `DROPPER_FRAMES`, `SQUARE_FRAMES` | `src/enemy.asm` | **removed** |
| guard "all three frame counts equal" | `src/enemy.asm` | **removed** |
| `RING/DROPPER/SQUARE_SHAPE` + `enemyAnimShape` | `src/enemy.asm` | **removed** — the shape belongs with the artwork choice, so it is folded into the level's table at export |
| `ENEMY_SPRITES`/`DROPPER_SPRITES`/`SQUARE_SPRITES` | `src/enemy.asm` | **removed** — the engine no longer names a species' address |
| `levelAssetDescs`, `LEVEL_DESC_ROW_STRIDE/SHIFT`, `LB_SLOT_*`, `LEVEL_PACKAGE_*` | `src/level_assets.asm` | **removed** — the package carries its own table |
| six `slot + ENEMY_FRAMES > LEVEL_SPRITE_BLOCKS` guards | `src/level_assets.asm` | **removed**, replaced by one budget guard where the artwork is chosen |
| `LVL_SLOT_* + 4 > sprBlocks` | `src/level_package.asm` | **replaced** by `LVL_SPR_BLOCKS != sprBlocks` and a per-entry check that no step names an unfilled block |
| `ENEMY_FRAMES = 4`, `DEFAULT_ENEMY_SLOTS` | `tools/level_editor/contract_v2.py` | **removed**, replaced by the roster and `enemy_art_cost` |
| `render_stage_enemies` default packing | `tools/level_editor/export_v6.py` | **replaced** — generated from the selection every export |
| `ENEMY_ANIM_STEPS = 8` | everywhere | **kept**, and deliberately: it is a property of the phase, not of the artwork |
| `SPECIES_COUNT = 3` | `src/encounter_format.asm` | **kept**, as instructed |

---

## 3. Animation semantics — preserved, not redesigned

The eight-step phase stays. For a sequence of **N** frames the default shape is
`step mod N`, which reaches every frame and states **no direction**. The two
sequences that already had an authored shape keep it byte for byte:

| Artwork | Steps | Note |
|---|---|---|
| Dropper (4) | `0,1,2,3,3,2,1,0` | out and back — unchanged |
| Square (4) | `0,1,2,3,3,2,1,0` | a spin reverses — unchanged |
| Ring 3 (8) | `0,1,2,3,4,5,6,7` | a full rotation, all eight |
| 6-frame | `0,1,2,3,4,5,0,1` | every frame reached |
| 5-frame | `0,1,2,3,4,0,1,2` | every frame reached |
| 3-frame | `0,1,2,0,1,2,0,1` | every frame reached |

**LOOP and PINGPONG are not implemented and nothing here pre-empts them.** No
field was added for them. Where N does not divide 8 the early frames are shown
twice per cycle; that is the honest consequence of keeping the existing stateless
phase, and it is exactly what the deferred per-species animation-mode pass is
for. No frame is sampled away and no physical layout is padded.

---

## 4. The global roster

Twelve sequences, every one selectable in the editor:

| Editor label | Roster name | Source | Frames |
|---|---|---|---:|
| Dropper | `DROPPER` | `$1E–$21` | 4 |
| Square | `SQUARE` | `$27–$2A` | 4 |
| Modded Alleykat A | `ALLEYKAT_A` | `$34–$36` | 3 |
| Modded Alleykat B | `ALLEYKAT_B` | `$3B–$3D` | 3 |
| Ring 1 | `RING_1` | `$3E–$40` | 3 |
| Ring 2 | `RING_2` | `$41–$43` | 3 |
| Spinner | `SPINNER` | `$44–$49` | 6 |
| Space Mine | `SPACE_MINE` | `$50–$52` | 3 |
| Spinny Thing | `SPINNY` | `$54–$59` | 6 |
| Space Whisk | `SPACE_WHISK` | `$5A–$5F` | 6 |
| Ring 3 | `RING_3` | `$60–$67` | 8 |
| Spinny Rotatey | `SPINNY_ROT` | `$68–$6C` | 5 |

**Deliberately unavailable**, and proved so by test: `$0F` (the hole, and the
player's HW1 blank), `$15` (obsolete power-up), `$2B–$33` (old Alleykat
explosion), `$37–$3A` (unmodified Alleykat reference), `$4A–$4F` (Hades
reference), plus the player, muzzle flash, explosion, boss, bullet and power-up.

The roster lives once, in `tools/sprite_export/import_spd.py`, beside the
SpritePad source it is cut from. `contract_v2.py` imports it rather than
repeating it.

---

## 5. The 20-slot budget

**One authoritative constant**: `LEVEL_SPRITE_BLOCKS = 20` in `src/main.asm`,
mirrored once in `import_spd.py` and imported from there by the editor. The
package sizes `LEVELPKG_SPR` with the same number.

Three independent gates, which must agree:

1. **Editor** — an `Enemy artwork:` row with one combobox per species, each
   showing `Label  (frames)`, and a live indicator:
   `Enemy sprite budget: 16 / 20`, appending `OVER BUDGET` past the limit. It
   updates the instant a selection changes and follows the document when another
   level is opened. It deliberately does **not** block the combobox: swapping two
   8-frame sequences must pass through an illegal intermediate state, and a
   selector you cannot move is worse than a red number.
2. **Exporter** — `render_stage_enemies` and `render_stage_sprites` both raise
   `ExportRefused` before writing anything. UI validation is not relied upon.
3. **Package build** — `LVL_SPR_BLOCKS != sprBlocks` and a per-entry guard that
   no animation step names a block the package never filled.

Boundary proofs, all passing, with the editor and exporter agreeing on each:

```
8 + 6 + 4 = 18  accepted        the editor agrees about 18
8 + 6 + 6 = 20  accepted        the editor agrees about 20   <- exactly full
8 + 8 + 5 = 21  rejected        the editor agrees about 21
```

An over-budget project **loads without crashing**, reports
`enemy sprite budget exceeded: Ring 3 8 + Ring 3 8 + Spinny Rotatey 5 = 21, and
the window holds 20`, and cannot be exported.

---

## 6. Package generation

Chosen artwork is packed contiguously in species order, each entry taking exactly
its own frame count. A level ships only what it uses.

| Level | Artwork | Blocks | Payload |
|---|---|---:|---:|
| level1 | Ring 3 (8) + Dropper (4) + Square (4) | **16 / 20** | 1,024 B of 1,280 |
| level2 | Spinner (6) + Dropper (4) + Spinny Rotatey (5) | **15 / 20** | 960 B of 1,280 |
| level3 | Ring 3 (8) + Dropper (4) + Square (4) | **16 / 20** | 1,024 B |

Unclaimed blocks are zeroed by the package, so a shorter level cannot leave the
previous level's enemies readable — proved by test.

### How the three numbering systems relate

```
SpritePad source index   $60..$67        the artwork's identity; what Brian draws
roster name              RING_3          the editor's and the exporter's handle
package-local block      0..19           where THIS level loaded it
runtime sprite pointer   $b0 + block     what the VIC fetches
runtime species          0 / 8 / 16      the BEHAVIOUR wearing it, unchanged
```

Level 1's emitted table, straight out of `build/level1.prg`:

```
[0,1,2,3,4,5,6,7,  8,9,10,11,11,10,9,8,  12,13,14,15,15,14,13,12]
 Ring 3, all eight  Dropper, out and back  Square, out and back
```

---

## 7. Full-frame proof

Read back off the **running machine** (`enemyAnimSeq`, window base `$b0`):

```
RING     ptrs $b0 $b1 $b2 $b3 $b4 $b5 $b6 $b7   blocks 0..7   -> 8 distinct
DROPPER  ptrs $b8 $b9 $ba $bb $bb $ba $b9 $b8   blocks 8..11  -> 4 distinct
SQUARE   ptrs $bc $bd $be $bf $bf $be $bd $bc   blocks 12..15 -> 4 distinct
```

`ring_3` reaches **eight distinct blocks**. The interim sampled mapping
(`$60,$62,$64,$66`) is gone. Confirmed by generated-file byte counts too:

```
ring_3 8 frames · spinner 6 · spinny 6 · space_whisk 6 · spinny_rot 5
dropper 4 · square 4 · alleykat_a 3 · alleykat_b 3 · ring_1 3 · ring_2 3
space_mine 3
```

and by a package check that each species' eight steps cover **exactly** its own
block range — a sampled sequence would leave blocks unnamed.

---

## 8. Tooling repair

`verify_sprites.py` / `sprite_source.py` could not run at all: they search
`main.prg` for symbols that moved into the level package at commit `8795c39`.
Repaired, bounded:

* `sprite_source.GROUPS` now lists only what is genuinely in `main.prg` — the
  player, muzzle flash, token, fireball and projectile. Five groups, 31 payloads.
* `verify_sprites.verify_packages()` is new and verifies the package side: every
  chosen frame byte-for-byte in its block, the animation table against the plan,
  every frame reachable, and unclaimed blocks zeroed.
* `slot_for` returns `None` for the player's engine-emitted blank instead of
  indexing past the end, and `verify()` proves that block is blank rather than
  pretending it came from the `.spd`.

---

## 9. Validation

**Build** — `make build` succeeds; the package memory map shows
`$ff93-$ffaa level anim table`, 24 bytes exactly.

**`make smoke`** — **PASS**, every fatal counter zero, `publishSkip` 0.

**Tests** — `tools/sprite_export/test_spd_pipeline.py`: **85 passed, 0 failed**,
covering every proof the brief lists: per-frame-count export (3/4/5/6/8), bytes
against the `.spd`, contiguous packing without aliasing, first-and-last frame
pointer arithmetic, unselected artwork consuming nothing, the three budget
boundaries with editor/exporter agreement, roster availability and exclusions,
save/reload round-trip, export determinism, and refusal of an over-budget level.

**VICE** — see §7 for the runtime table read. Stills in §10.

---

## 10. Observations and what still needs your eye

### Runtime reads, on the machine

`enemyAnimSeq` read out of a running emulator, window base `$b0`:

**Level 1** — Ring 3 (8) + Dropper (4) + Square (4):
```
RING     $b0 $b1 $b2 $b3 $b4 $b5 $b6 $b7   blocks 0..7    -> 8 distinct
DROPPER  $b8 $b9 $ba $bb $bb $ba $b9 $b8   blocks 8..11   -> 4 distinct
SQUARE   $bc $bd $be $bf $bf $be $bd $bc   blocks 12..15  -> 4 distinct
```

**Level 2** — Spinner (6) + Dropper (4) + Spinny Rotatey (5):
```
RING     $b0 $b1 $b2 $b3 $b4 $b5 $b0 $b1   blocks 0..5    -> 6 distinct
DROPPER  $b6 $b7 $b8 $b9 $b9 $b8 $b7 $b6   blocks 6..9    -> 4 distinct
SQUARE   $ba $bb $bc $bd $be $ba $bb $bc   blocks 10..14  -> 5 distinct
```

So **8-frame, 6-frame, 5-frame and 4-frame artwork all resolve to exactly their
own number of distinct blocks**, in three different behavioural slots, across two
different levels with different packings. There is no four-frame truncation left
anywhere.

### Visible

Level 1 captured at two scroll depths through `tests/harness.py` (exact PIDs,
`-console`, no focus stolen). The Ring 3 artwork draws correctly at gameplay
scale, in the trigger's authored colours (yellow, red, blue, cyan), with the
white rim highlight in different positions on enemies at different animation
steps — the rotation running. No sprite corruption, no pointer wrap, no
cross-species frame bleed, no scroll jank, no package-load corruption.

### What still needs your eye

- **LOOP/PINGPONG is deliberately absent.** Where a frame count does not divide
  eight, the first frames show twice per cycle. That is the honest consequence
  of keeping the existing stateless phase and is exactly what the deferred
  animation-mode task is for. Do not read it as a bug.
- **MiSTer/CRT** remains the authority on how the new sequences actually look in
  motion; I have only stills and the runtime tables.
- **The editor UI was not exercised on screen.** Its Tk window would steal
  focus, so the roster, the round-trip and the budget are proved through the
  same code paths the UI calls, not by clicking it. Worth one manual open.

---

## 11. Files

**Engine** — `src/enemy.asm`, `src/level_assets.asm`, `src/level_package.asm`,
`src/levelpkg.asm`, `src/main.asm`.
**Levels** — `src/level{1,2,3}/stage_enemies.asm`, `.../stage_sprites.asm`.
**Importer** — `tools/sprite_export/import_spd.py` (roster, plan, level files).
**Generated** — `src/generated_sprites/`: twelve roster art files,
`enemy_roster.asm`, and the retired `enemy_art.asm` removed.
**Editor** — `tools/level_editor/contract_v2.py`, `project_v6.py`,
`export_v6.py`, `editor.py`.
**Tooling** — `tools/sprite_export/sprite_source.py`, `verify_sprites.py`,
`test_spd_pipeline.py`.

**Untouched:** renderer, multiplexer, scroller, raster code, collision, wave
pacing, firing cadence, projectile cap, trigger-owned colour and fire mode,
enemy health and movement, species count, and all artwork.

---

## 12. Status

- **Nothing committed, nothing pushed.**
- **No `git checkout`, `restore`, `reset`, `stash` or `clean` was used.** Only
  `status`, `log`, `diff` and `show`, all read-only. The dirty working tree
  carrying the previous SpritePad import was snapshotted before any edit and is
  preserved intact.
- VICE: every instance launched through the harness with its exact PID recorded
  and reaped; no `pkill`/`killall`; `pgrep -x x64sc` reports none remaining.
