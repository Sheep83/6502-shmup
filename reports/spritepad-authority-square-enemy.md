# SpritePad becomes authoritative, and the Square joins the roster

Brian's edited `.spd` is now the source of truth for every editable gameplay
sprite. His edits to 26 of the 43 existing sprites appear byte-for-byte in the
built game, the four frames he appended are a genuine third ordinary enemy
species called **Square**, and a normal build can no longer draw stale artwork.

Nothing was committed or pushed.

---

## 1. Starting state

| | |
|---|---|
| HEAD | `a931958bb1657474b159267b83f1f03d9fd53e5e` — *Added level2 data to editor* |
| Branch / upstream | `main` … `origin/main`, in sync |
| Working tree at start | clean but for the previous task's untracked `assets/`, `tools/sprite_export/` and reports |
| VICE running | none |

---

## 2. The edited SPD

| | |
|---|---|
| Found at | `/Users/brianmorrice/Desktop/mysprites.spd` (the only `.spd` outside the repo) |
| sha256 | `f70e5a967d7acff2a7f6293a86387141ad1ce4073ecd0dab5ce31168e5ff31c9` |
| Size | 3,085 bytes |
| Structure | SpritePad 2.0, version 1, **48 slots**, 0 animations, shared colours 0 / 11 / 1 |

### The count was not 47

The brief expected 47 (43 + 4). The file holds **48**, and `9 + 64×47 + 4 = 3021`
does not equal 3,085 while `9 + 64×48 + 4` does exactly. So the assumption was
proved rather than taken:

* **slots 0–42 are the established roles, in order, with nothing inserted,
  deleted or reordered.** Every group still lines up with its engine symbol, and
  the edits are coherent per role (ship banks, all five flashes, six boom
  frames, all four Ring and all four Dropper frames).
* **slots 43–46** are four valid, non-blank, multicolour frames — the Square.
* **slot 47 is entirely blank** (0/63 non-zero bytes): a trailing empty slot
  Spritemate left behind.

That is "edited and appended", not a reordering, so it did not warrant stopping.
The importer knows about the trailing slot explicitly, refuses any `.spd` whose
slot count differs, and refuses one where slot 15 or 47 stops being blank.

### Exactly what changed in slots 0–42

**17 identical, 26 changed.** Shared colours unchanged.

| Slot | Name | Role | Change |
|---|---|---|---|
| 3, 4, 5 | `ship_bank1_engine0/1/2` | player ship | 1/63 bytes each |
| 9, 10, 11 | `ship_bank3_engine0/1/2` | player ship | 1/63 bytes each |
| 16–20 | `muzzle_bank0..4` | muzzle flash | 7, 6, 6, 6, 7 bytes |
| 23, 24, 25, 26 | `boom_1..4` | death fireball | 1, 3, 4, 10 bytes |
| 28, 29 | `boom_6`, `boom_7` | death fireball | 1 byte each |
| 30–33 | `ring_north/east/south/west` | Sonic Ring | 41, 38, 42, 38 bytes — a redraw |
| 34–37 | `dropper_*` | Orbital Dropper | 31, 32, 34, 32 bytes — a redraw |
| 42 | `ebullet` | hostile projectile | 3 bytes **+ colour 7 → 2** |

**No ordering change. No mode change. No shared-colour change.**

> **One thing for you to decide.** Slot 42's *metadata colour* moved from 7 to 2.
> The projectile's runtime colour is the engine constant `EBULLET_COL = 7`, and
> the brief says to preserve runtime colour behaviour and treat SPD colour as
> editing metadata — so the game still draws it yellow. **Its bitmap edit did
> land.** If you meant the projectile to become red, that is a one-line change to
> `EBULLET_COL` in `src/ebullet.asm`; say the word.

### The Square frames

Four frames of a spinning square: a full face narrowing through two turns to an
edge-on bar.

| Slot | sha256 (12) | Non-zero bytes | Mode | SPD colour |
|---|---|---|---|---|
| 43 | `8afd1a28c7f8` | 49/63 | multicolour | 4 |
| 44 | `26a663b097d5` | 63/63 | multicolour | 4 |
| 45 | `8c482a8edbe8` | 63/63 | multicolour | 4 |
| 46 | `9abab6ce8738` | 21/63 | multicolour | 4 |

Spritemate's synthetic names (`sprite44`…) were not used for anything; the roles
come from position and from the engine's own placement.

---

## 3. The new authority and how generation works

```
assets/sprites/19656-sprites.spd          <- SOURCE OF TRUTH, edit in Spritemate
    -> tools/sprite_export/import_spd.py
    -> src/generated_sprites/*.asm         <- generated, never hand-edited
    -> KickAssembler
    -> build/shmup.prg
```

### Why generated `.asm` and not a binary blob

The brief preferred a binary asset "if it integrates cleanly". It does not. The
sprites are not one run — they are pinned at `$2000`, `$2400`, `$2580`, `$25c0`,
`$2c00`, `$2d00`, `$2e00`, `$3580` and `$36c0` — and several of those addresses
are owned by the file that imports them (`src/player.asm` sets
`* = PLAYER_SPRITES` and *then* imports the art). A single `.import binary`
cannot express that, and changing who owns the addresses would mean rewriting
the memory map to suit the tool. **One generated include per existing import
point** keeps every segment, label and assertion exactly where the engine
already expects it, so the diff is artwork and nothing else.

### Generated files

| File | Slots | Notes |
|---|---|---|
| `player_art.asm` | 0–14 | 15 frames; the 16th blank stays in `src/player.asm` |
| `player_muzzle_flash.asm` | 16–20 | |
| `token_art.asm` | 21 | extracted out of `src/pickup.asm` |
| `player_boom_art.asm` | 22–29 | pins itself, as before |
| `enemy_art.asm` | 30–33 | Ring, with its four asserted frame labels |
| `enemy_dropper_art.asm` | 34–37 | Dropper, likewise |
| `enemy_square_art.asm` | 43–46 | **new** |
| `boss_art.asm` | 38–41 | pins itself, as before |
| `ebullet_art.asm` | 42 | extracted out of `src/ebullet.asm` |
| `sprite_art_stamp.asm` | — | records the `.spd` hash; imported by nothing |

### Build integration and the staleness gate

```
make sprites          regenerate from the .spd
make build            VALIDATES that the tree matches the .spd, else fails
```

The build **validates rather than regenerates**, deliberately, following the
principle this repository already states for level data in
`tools/level_editor/export_level.py`: *"regenerating source on every build would
make `make` able to change the program's content, so the generation step is
explicit and its output is reviewable in the diff."* Every generated file records
the `.spd`'s SHA-256 and `build:` depends on `sprites-check`. A stale tree fails
with the fix:

```
  sprite art: generated from a different .spd
      generated from f70e5a967d7a…
      .spd is now    6a72b4689381…

  The generated sprite art is STALE.
  Run:  make sprites

make: *** [sprites-check] Error 1
```

Verified by corrupting the `.spd` and confirming the build stops. The check also
catches a **hand-edited generated file** even when the stamp still matches,
because it re-renders and compares, not just the hash.

So `save SPD → make run → unknowingly run old sprite art` is impossible.

---

## 4. Retired duplicate authority

| Removed | Why it was safe |
|---|---|
| `src/player_art.asm` | now generated |
| `src/enemy_art.asm` | now generated |
| `src/enemy_dropper_art.asm` | now generated |
| `src/player_boom_art.asm` | now generated |
| `src/player_muzzle_flash.asm` | now generated |
| `src/boss_art.asm` | now generated |
| `tools/gen_player_ship.py` | a **third** authority (PNG → `player_art.asm`); keeping it would mean a PNG, a `.spd` and an `.asm` all claiming the same pixels |
| `tools/sprite_export/export_spd.py` | wrote the `.spd` *from* the program. With the `.spd` authoritative that is a second editable copy — replaced by `verify_sprites.py`, which only checks |

The literal byte blocks inside `src/pickup.asm` and `src/ebullet.asm` became
`#import`s of generated files, so no hand-authored gameplay bitmap authority
remains anywhere.

**Retained deliberately:** the HUD's `.fill` framebuffers and its
`livesByte()` / `pchargeByte()` generators, every memory-map constant and label,
and `src/player.asm`'s own `playerBlankBitmap` (the importer asserts the `.spd`
slot 15 is still blank so the two cannot drift apart).

---

## 5. Memory placement

Re-audited against the **current** build rather than the map comments:

```
enemy window $2c00-$30ff, 20 blocks
  slots  0- 3  $2c00  ptr $b0-$b3  DATA  Ring
  slots  4- 7  $2d00  ptr $b4-$b7  DATA  Dropper
  slots  8-19  $2e00  ptr $b8-$c3  free
```

**Square takes slot 8 — `$2e00`, pointers `$b8`–`$bb`** — proven free before
placement, four consecutive blocks inside the window, 64-byte aligned. That is
the natural packing (`species index × ENEMY_FRAMES`) so Ring and Dropper do not
move.

One thing had to move. `enemyAnimSeq` is one row of `ENEMY_ANIM_STEPS` pointers
per species, so a third species took it from 16 to 24 bytes and it no longer fit
between `$c4f0` and the species array at `$c500`. **The existing segment guard
caught this as a build error** rather than letting it overwrite anything. It now
lives at `$c410`, in the hole between the level asset state and the token
encounter state — the right neighbourhood, since `levelAssetsLoad` is what fills
it. `$c4f0-$c4ff` is now free.

The descriptor row also had to change: the loader turned a package index into a
row base with a *shift*, which needs a power-of-two stride and worked only while
`SPECIES_COUNT` was 2. The row is now padded to `LEVEL_DESC_ROW_STRIDE = 4`
(3 used), so the shift survives and no multiply appears on that path.

---

## 6. Species ID

**`SPECIES_SQUARE = 2 × ENEMY_ANIM_STEPS = 16`**, and it was not a free choice.

`src/encounter_format.asm` explains why Dropper is 8 and not 1: *"Frame lookup
is `species ORA step`, so a row offset makes that a single ORA straight out of
memory."* A species value **is** its row offset in the animation table, so the
only legal values are multiples of `ENEMY_ANIM_STEPS`. Ring keeps 0, Dropper
keeps 8, the third row begins at 16. **Neither existing ID was renumbered.**

### Every two-species assumption found and extended

| Location | Change |
|---|---|
| `src/encounter_format.asm` | `SPECIES_SQUARE`, `SPECIES_COUNT` 2 → 3 |
| `src/enemy.asm` | the `SPECIES_COUNT != 2` guard (which told us exactly what to extend) |
| `src/enemy.asm` | `SQUARE_FRAMES`, `SQUARE_SPRITES`, frame-count equality guard |
| `src/enemy.asm` | `enemyFireModeTab` — a third entry |
| `src/enemy.asm` | `SQUARE_SHAPE` + its range check + the `enemyAnimShape` row |
| `src/enemy.asm` | `enemyAnimSeq` sized by `SPECIES_COUNT`, relocated |
| `src/enemy.asm` | Square art segment + four frame-placement assertions |
| `src/level_assets.asm` | row stride, descriptor rows, `LB_SLOT_SQUARE`, window and overlap guards |
| `src/waves.asm` | the assembly-time authored-species membership check |
| `src/level1/stage_enemies.asm` | `LVL_SLOT_SQUARE = 8` (one line) |
| `src/level2/stage_enemies.asm` | same |
| `tools/level_editor/contract_v2.py` | `SPECIES`, `SPECIES_ORDER`, `SPECIES_LABELS` |
| `tools/level_editor/encounters_ui.py` | timeline colour for Square |

**Nothing else needed changing**, and that is a fact about the engine rather
than luck: every runtime species test is `cmp #SPECIES_DROPPER / bne`, so
anything that is not a Dropper already falls through to generic handling. Square
therefore gets ordinary behaviour — and is excluded from the one-live-Dropper
substitution — **by construction**.

---

## 7. Square's gameplay semantics

Generic, as instructed. Formations, movement programs, launch headings, firing
masks, collision, damage, despawn and wave colour all come from the ordinary
wave path with no Square-specific code anywhere.

The two places a per-species default was required:

* **Firing** — `ENEMY_FIRE_DOWN`, the Ring's baseline.
* **Animation shape** — `0,1,2,3, 3,2,1,0`, out and back, the Dropper's shape
  rather than the Ring's `0,1,2,3, 0,1,2,3`. A spin reverses: frames 0→3 narrow
  the silhouette to an edge-on bar, so running them out and back is one
  revolution instead of a jump from edge-on straight back to full face.

HP and score are **not** species-indexed in this engine — they come from the
object pool and the wave — so there was nothing to choose. **Ring and Dropper
were not rebalanced.**

---

## 8. Colour handling

Three different things share the word, and the manifest now says so explicitly:

| | What it is | Where it lives |
|---|---|---|
| **Bitmap payload** | the 63 bytes | the `.spd`, authoritative |
| **SPD editing colour** | what Spritemate shows while drawing | the `.spd`, reaches nothing at run time |
| **Runtime colour** | what the engine writes to `$d027+n` | the engine, or the wave |

Square uses **the wave's authored colour**, exactly like Ring and Dropper — the
SPD's editing colour (4) is never baked into gameplay. The runtime screenshots
show this directly: the same four frames appear cyan, yellow, green and white in
different waves.

Shared multicolours are unchanged and match the engine: `$d025` = 11,
`$d026` = 1.

---

## 9. Payload equivalence proof

```
generated tree: 10 generated files current (f70e5a967d7a)
payloads compared  47
bytes compared     2961
mismatches         0
```

Both halves of the requirement, from the **built PRG** read at the symbols'
addresses and compared against the `.spd` on disk:

* **slots 0–42** → 43 payloads, 2,709 bytes, **0 mismatches**
* **slots 43–46** → 4 payloads, 252 bytes, **0 mismatches**

Square's frames in the binary hash to `8afd1a28c7f8`, `26a663b097d5`,
`8c482a8edbe8`, `9abab6ce8738` — identical to the `.spd`.

Visual cross-check: all 47 rendered twice, once from the program and once from
the `.spd`, **23,688 pixels compared, 0 differing**
(`reports/spritepad-authority-square/contact-sheet.png`).

---

## 10. Runtime proof

### Automated — `tests/test_square_species.py`, 24 checks, all passing

**No level was modified.** The trigger table is package data in RAM, so the
species column is poked at boot — the technique `tests/test_species_order.py`
already uses. Nothing on disk was touched, so nothing needed restoring.

```
ok  levelAssetsLoad resolved THREE animation rows, not two -- 24 entries
ok  the Square's row is its own four sprite pointers in the spin order
       [0xb8,0xb9,0xba,0xbb,0xbb,0xba,0xb9,0xb8]
ok  the Ring's row is unchanged        [0xb0,0xb1,0xb2,0xb3,0xb0,0xb1,0xb2,0xb3]
ok  the Dropper's row is unchanged     [0xb4,0xb5,0xb6,0xb7,0xb7,0xb6,0xb5,0xb4]
ok  the level's descriptor row is Ring 0, Dropper 4, Square 8
ok  all-Square: Squares actually spawned -- peak 6
ok  all-Square: SEVERAL are alive at once, as Rings may be -- peak 6
ok  all-Square: not one object was ever committed as a Dropper -- peak 0
ok  all-Square: Squares move under the ordinary movement system
ok  all-Square: they despawn rather than accumulating -- peak 6, spawned 28
ok  mixed: NEVER more than one live Dropper -- the rule still holds -- peak 1
ok  mixed-with-Square: all three species coexist -- peak S=6 R=4 D=1
ok  mixed-with-Square: the Dropper rule is unaffected by Squares -- peak 1
```

### Manual, which AGENTS.md makes authoritative

A **disposable** package (Level 1's terrain, every trigger switched to Square and
pulled forward) was built through `LEVELDIR` and flown in `x64sc` 3.10 — neither
production level was touched on disk, and the canonical build was restored
afterwards.

`reports/spritepad-authority-square/square-runtime-quad.png` shows Squares
spawning in formation, flying the authored paths, spinning through all four
frames (full face → narrowing → edge-on bar), several alive at once, over Level
1's terrain — **in four different wave-authored colours**, which is the colour
model working end to end.

---

## 11. Ring, Dropper and level preservation

**Ring and Dropper:** animation rows byte-identical to before, one-live-Dropper
rule intact at peak 1, both still spawn and fly in mixed waves.

**Authored level content — all identical to the pre-task snapshot:**

| | `stage_charset` | `stage_config` | `stage_map` | `stage_turrets` | `wave_encounters` | `wave_programs` | `level.v6.json` |
|---|---|---|---|---|---|---|---|
| Level 1 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Level 2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

The only level-owned file that changed is `stage_enemies.asm` in each, by
**exactly one line** — the new window claim. Level 1's file is still the
hand-authored original with its own documentation (an earlier regeneration
overwrote it; that was reverted and only the single `.const` added):

```diff
+.const LVL_SLOT_SQUARE   = 8             // the Square's four frames
```

**Neither level gained a Square encounter**: Level 1 still uses `{DROPPER, RING}`
across 8 triggers, Level 2 the same across 7. Asserted by test.

### Binary differences, bounded and explained

Expected — artwork changed and a species was added.

```
old PRG 51162 bytes, new 51162 bytes, delta +0
14 differing runs, 2048 bytes total (4.0% of the program)

  $20d0-$2150   129  player bitmaps        ship bank 1
  $2250-$22d0   129  player bitmaps        ship bank 3
  $2414-$252f   284  muzzle flash          all five
  $2610-$26f4   229  death fireball        frames 1-4
  $2771-$27a5    53  death fireball        frames 6-7
  $2c01-$2efd   765  Ring/Dropper/SQUARE   redraws + the new art at $2e00
  $36c6-$36cc     7  projectile
  $48c8-$4a64   413  engine                enemyFireModeTab, enemyAnimShape (+8), code shift
  $4b05-$4b26    34  engine                descriptor table + row-stride loader
  5 single bytes     engine                operands following enemyAnimSeq's move
```

**Program size is unchanged** — Square's art went into previously-zero window
space and the animation table moved within existing RAM. Every differing run is
accounted for by an intended change.

---

## 12. Tests

| Suite | Result |
|---|---|
| `tools/sprite_export/test_spd_pipeline.py` | **54 passed, 0 failed** (new) |
| `tests/test_square_species.py` | **24 passed, 0 failed** (new) |
| `tools/level_editor/test_*.py` (39 files) | **38 pass, 1 fail** — the pre-existing `test_v6_import.py` |
| `make test` | 2 failures, **both pre-existing at HEAD** (`publishSkip`, `stageTopRow`), proven so in an earlier task by building and running in a pristine `git worktree` |

New coverage spans: the 48-slot structure, slots 0–42 order, the four Square
frames, deterministic generation, built payloads == SPD for both ranges, Square
pointer sequence, stable non-conflicting species ID, Ring/Dropper IDs unchanged,
editor accept/save/load/export, simulator acceptance, same-species adjacency,
Square-is-not-a-Dropper, both levels unchanged, no Square encounter added,
malformed/truncated/reordered SPD refusal, and stale generated data blocked
(including a hand-edited file with a valid stamp).

**One existing expectation was corrected, not weakened.**
`test_v6_phase5b_encounters.py` asserted `set(C.SPECIES) == {"RING","DROPPER"}`
under the label *"species are symbolic"*. The label is the claim; the census was
incidental and wrong the moment a species was added. It now asserts that species
are names, that the two established ones are present, and that every value is a
whole animation row — with the roll-call owned by the pipeline test.

---

## 13. Files added, changed, deleted

**Added**

```
src/generated_sprites/                    10 generated includes
assets/sprites/README.md                  the workflow documentation
tools/sprite_export/import_spd.py         .spd -> generated .asm (+ --check)
tools/sprite_export/verify_sprites.py     built PRG == .spd, refreshes the manifest
tools/sprite_export/test_spd_pipeline.py  54 checks
tests/test_square_species.py              24 runtime checks
reports/spritepad-authority-square-enemy.md
reports/spritepad-authority-square/       contact sheet + runtime captures
```

**Changed**

| File | Why |
|---|---|
| `assets/sprites/19656-sprites.spd` | replaced with Brian's edited file (now authoritative) |
| `assets/sprites/19656-sprites.json` | manifest regenerated for 47 sprites + colour model |
| `Makefile` | `sprites`, `sprites-check`, `build:` gate |
| `src/encounter_format.asm` | `SPECIES_SQUARE`, count 3 |
| `src/enemy.asm` | species plumbing, Square art segment, animation table move |
| `src/level_assets.asm` | descriptor stride and rows |
| `src/waves.asm` | authored-species membership |
| `src/player.asm`, `src/main.asm` | imports repointed at `generated_sprites/` |
| `src/pickup.asm`, `src/ebullet.asm` | literal bitmaps → imports |
| `src/level1/stage_enemies.asm`, `src/level2/stage_enemies.asm` | one claim each |
| `tools/level_editor/contract_v2.py` | species, order, labels |
| `tools/level_editor/encounters_ui.py` | Square timeline colour |
| `tools/level_editor/test_v6_phase5b_encounters.py` | corrected expectation |
| `tools/sprite_export/sprite_source.py`, `contact_sheet.py` | Square group, slot pairing |

**Deleted**

```
src/player_art.asm  src/enemy_art.asm  src/enemy_dropper_art.asm
src/player_boom_art.asm  src/player_muzzle_flash.asm  src/boss_art.asm
tools/gen_player_ship.py
tools/sprite_export/export_spd.py   tools/sprite_export/test_spd_export.py
```

---

## 14. Limitations

* **Slot 42's colour change was not honoured** — the projectile stays
  `EBULLET_COL = 7`. See §2; one line if you want it red.
* **`.spd` slot count is pinned at 48.** Adding a species means appending four
  frames *and* extending the group table in `import_spd.py`. The importer fails
  loudly rather than guessing — deliberate, but it is a manual step.
* **Square has no bespoke identity**: same firing mode and HP/score treatment as
  any ordinary enemy, and no sound of its own.
* **Package B has no Square art.** `LB_SLOT_SQUARE = 16` points at empty window
  space; it never carried artwork and does not need to, since what it proves is
  pointer arithmetic.
* **The build validates rather than regenerates**, so editing sprites costs one
  extra `make sprites`. Chosen to match this repository's stated principle about
  generated content; a `build: sprites` dependency would remove the step at the
  cost of letting `make` change the program.
* **Not yet opened in Spritemate since import.** The `.spd` is byte-identical to
  the file you saved, so it will open as it did.
* `test_v6_import.py` still fails for its pre-existing reason.

---

## 15. Scope confirmations

* **HUD sprites remain under their existing authority** — untouched.
* **Level 1 and Level 2 authored content unchanged**; neither gained a Square
  encounter.
* **Ring = 0 and Dropper = 8 were not renumbered**, and their animation rows are
  byte-identical.
* No renderer, multiplexer, raster, scrolling, boss, collision or movement
  redesign; Ring/Dropper behaviour is unchanged beyond generic species plumbing.

---

## 16. Hygiene

**Processes.** Every VICE launch went through `tests/harness.Vice` with
`-console`: exact PIDs retained and reaped in a `finally` on all exit paths, no
window mapped, focus never taken, no `pkill`/`killall`. `pgrep -fl x64sc` before
and after every run, **empty now**. PIDs launched and reaped: `12659, 12739,
12879, 13043, 13133, 13246, 13490, 14769`.

**Disk.** scratch 712K · `assets/` 44K · `src/generated_sprites/` 52K ·
`tools/sprite_export/` 152K · `build/` 300K · report images 36K. No per-run
build directories; the disposable Square fixture and all raw captures stayed in
the session scratchpad.

**Final hashes**

```
f70e5a967d7acff2a7f6293a86387141ad1ce4073ecd0dab5ce31168e5ff31c9  assets/sprites/19656-sprites.spd
01cbc320b59fc44f7302d7f3134e9b85b5039e45931ca5e626fadd001cc87ab9  build/shmup.prg
1d8667c75b8558e91ee03cafccfabfd2a7ef6d77dcd361db2fc65975ca61b371  build/level1.prg
ef1cfb0eb2944c91d8751fa5eb965f42ff3ae31a6fd0d4bf4200cb17ae8f43ab  build/shmup.d64
```

**Final `git status`:** 13 modified, 8 deleted, 7 new untracked paths — listed in
§13. **Nothing was committed and nothing was pushed.**

---

## Acceptance gate

| # | Criterion | Status |
|---|---|---|
| 1 | edited SPD authoritative for gameplay sprite art | ✅ |
| 2 | edits to the 43 existing sprites appear byte-for-byte | ✅ 43 payloads, 2,709 bytes, 0 mismatches |
| 3 | four Square frames appear byte-for-byte | ✅ 4 payloads, 252 bytes, 0 mismatches |
| 4 | Square is a genuine third ordinary species | ✅ ID 16, own animation row, own window slot |
| 5 | selectable / serialisable / exportable in the editor | ✅ |
| 6 | ordinary formations, movement, firing, collision, despawn | ✅ 24 runtime checks + visual |
| 7 | Ring and Dropper still work | ✅ |
| 8 | Ring/Dropper IDs and contracts intact | ✅ |
| 9 | no unintended level change or Square encounter | ✅ |
| 10 | a normal build cannot use stale generated data | ✅ demonstrated |
| 11 | HUD/runtime-generated sprites keep their authority | ✅ |
| 12 | nothing committed or pushed | ✅ |
