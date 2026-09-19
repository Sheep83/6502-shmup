# Engine ↔ Level Editor Contract v2 — audit and specification

**Date:** 2026-09-19
**HEAD at start:** `3718a45` *Boss hud bug fixed* — level with `origin/main`, 0 behind / 0 ahead, working tree **clean**.
**Editor audited:** `~/Desktop/c64shooter-main.zip` (snapshot dated 10 Sep 2026), extracted to disposable scratch. `tools/level_editor/` **does not exist in the repository**; the editor lives only in that archive.
**Nature:** audit and specification only. **No implementation file was changed. Nothing committed, nothing pushed.**

---

## 0. The headline

The editor and the engine have diverged far enough that **the editor cannot currently produce a loadable level**, and the divergence is not mostly about encounters — it is about *where the level lives*. The editor still believes terrain is assembled into the engine PRG at `$6600-$8800`; the engine now loads a separate `LEVEL1` file into `$e000-$fff9`. Everything downstream of that — the row ceiling, the generated filenames, the duration estimate — follows from it.

Three divergences are severe enough to be called out before the detail:

1. **Trigger rows run in the opposite direction.** The editor authors `worldRow` in the *stage-row* domain, descending (390, 382, 375 …). The engine consumes `worldProgress`, ascending from 0, and **fails the build** if rows are not non-decreasing. The conversion is `worldProgress = STAGE_FINAL_VIEW_PROGRESS − stageRow`. Section 3 makes this impossible to get wrong.
2. **The editor's whole encounter model is the pre-Stage-1 "attack catalogue"** (`attackId` 0..11, `enemyType` 0..3). The engine now has movement programs, 10-byte wave definitions and 6-column absolute triggers. None of the editor's 33 definitions or 53 triggers can be mapped forward; they must be discarded, not migrated. Section 15 says so explicitly.
3. **Turrets: the editor allows 255, the engine build-errors above 8.** `trtDeadPending` is one byte, one bit per turret.

---

## 1. Repository and provenance

| | |
|---|---|
| HEAD | `3718a45` *Boss hud bug fixed* |
| upstream | `origin/main`, 0 behind / 0 ahead |
| working tree | clean at audit start |
| editor source | `c64shooter-main.zip` on the Desktop, 10 Sep 2026, ~9,400 lines of Python under `tools/level_editor/` |
| editor in repo | **absent** — `tools/` holds only `gen_player_ship.py` and `gen_proof420.py` |

The archive is a snapshot of the whole repository as it stood on 10 Sep. Where the archive's engine sources disagree with the current tree, **the current tree is authoritative** and the archive is treated purely as the editor's source.

---

## 2. Existing editor audit

### 2.1 Project JSON, as it stands

`formatVersion` **5**, accepting 1–5 with migration. Top-level keys, from `Project.to_dict`:

| key | type | status against the current engine |
|---|---|---|
| `formatVersion` | int | **correct**, mechanism reusable |
| `name` | str | **correct** |
| `width` | int (10) | **correct** — `METATILES_PER_ROW = 10` |
| `height` | int (105) | **correct** — maps to `STAGE_METATILE_ROWS` |
| `scrollFrameDivider` | int (2) | **stale and inert** — see 2.4 |
| `palette` | 4 × colour index | **correct** |
| `metatileRows` | 105 × 10 ints | **correct** |
| `metatileMetadata` | object (empty) | editor-only, harmless |
| `objects` | 8 turrets `{type, metatileRow, metatileCol}` | **correct in shape**, limits stale |
| `levelMetatileSet` | 34 native metatiles | editor-owned authoring source, **correct** |
| `tileset` | `{glyphCount:72, glyphs:[72], metatileDefs:[34]}` | **correct** — derived cache |
| `waveDefinitions` | 33, attack-catalogue shape | **incompatible** |
| `waveTriggers` | 53, `{id, worldRow, waveDef}` | **incompatible** |
| — | — | **missing: `STAGE_NO_SPAWN_ROW`, movement programs, species, fire mask, Dropper side** |

### 2.2 What the editor gets right

Verified against `src/level1/` byte for byte:

* **Stage dimensions.** `height = 105` → `STAGE_METATILE_ROWS = 105`. `width = 10` matches `METATILES_PER_ROW`.
* **Palette.** `{background:12, multicolour1:15, multicolour2:11, character:1}` is exactly `stage_config.asm`.
* **Glyph namespace.** `TERRAIN_GLYPH_BASE = 96`, namespace 128 — the engine's base is 96 and its real ceiling is 130 (§5), so 128 is safe.
* **Metatile capacity 64** — matches `LEVELPKG_DEFS_MAX / 16`.
* **Metatile geometry** 4×4 chars, row-major `def[subRow*4 + col]`.
* **Turret coordinate derivation.** `world row = metatileRow*4 + 1`, `world col = metatileCol*4 + 1` — matches `TURRET_ROW_PHASE = 1`. The 8 authored turrets resolve to world rows `[5, 25, 109, 117, 217, 225, 337, 345]`, exactly `stage_turrets.asm` reversed.
* **Turret export order.** `_sorted_turrets_desc` emits descending world row; the committed asm is `345, 337, 225, 217, 117, 109, 25, 5`. **Correct and must be preserved.**
* **One turret per metatile row** is already validated — and is still a real engine rule.
* **Deterministic output**: sorted turrets, canonical ordering on save, fixed formatting.

### 2.3 What is stale

| editor assumption | source | current engine truth |
|---|---|---|
| `ENGINE_MAX_STAGE_ROWS = 768`, derived from `metatileDefs`+rows occupying `$6600..$8800` | `engine_data.py` | terrain is a **separately loaded package** at `$e000`; ceiling is **440** rows from `LEVELPKG_MAP_MAX = 4400` |
| `MAX_AUTHORED_TURRETS = 255`, "streamed through a pool of 8" | `engine_data.py`, `project.py` | **`TURRET_TOTAL > 8` is a build error** — `trtDeadPending` is one byte |
| turret behaviour in `src/background_turrets.asm` | `engine_data.py` comment | file does not exist; it is `src/turrets.asm` |
| `ATTACK_COUNT = 12`, `ENEMY_TYPE_COUNT = 4` | `engine_data.py` | no attack catalogue exists. `SPECIES_COUNT = 2` (`SPECIES_RING = 0`, `SPECIES_DROPPER = 8`) |
| generated file `stage_test.asm` | `ka_export.py` | the repo file is `stage_map.asm` |
| generated file `stage_waves.asm` | `ka_export.py` | **does not exist and must not be generated** — waves now ship as package bytes |
| output dir `src/generated/<level>/` | `engine_data.py` | actual dir is `src/level1/` |
| charset comment "codes 96..223 … `$3B00-$3EFF`" | emitted into `stage_charset.asm` | charset is at `$0800`; terrain glyph bitmaps at `$0b00`; terrain owns 96..167 |
| trigger domain `SCROLL_ROW == worldRow`, descending | `ka_export.py` | `worldProgress`, **ascending**, non-decreasing enforced |

### 2.4 `scrollFrameDivider` — generated, and consumed by nothing

`SCROLL_FRAME_DIVIDER = 2` is emitted into `stage_config.asm` by `render_stage_config`. A search of the entire repository finds **exactly one occurrence — the generated line itself**. No engine source reads it.

The engine scrolls **1 pixel per frame unconditionally**: `gameFrame` calls `scrollTick` once per frame (`src/main.asm:868`) and `scrollTick` does `inc scrollFine` on the natural path. The editor's duration estimate multiplies by this dead constant and is therefore wrong by exactly a factor of 2.

**Contract v2: drop the field entirely.** It is not a level property.

### 2.5 Incomplete / ambiguous

* **`waveDefinitions`** carry `attackId`, `composition[{enemyType, count}]`, `spawnInterval`. The engine needs count, interval, 9-bit startX, startY, xStep, yStep, colour, launch heading and a movement-program offset. Only *count* and *interval* survive conceptually, and neither can be trusted because the catalogue that supplied the rest is gone.
* **`waveTriggers`** carry `{id, worldRow, waveDef}`. The engine needs six columns. **Species, fire mask and Dropper side have no editor representation at all.**
* **Movement programs** have no editor representation at all.
* **`STAGE_NO_SPAWN_ROW`** has no editor representation at all; `render_stage_config` does not emit it.
* **`metatileMetadata`** is an empty object with no documented schema.
* **`MIN_STAGE_ROWS = 1`** is legal to the editor but the engine requires `STAGE_ROWS >= SCREEN_ROWS + 1` = **26 logical rows = 7 metatile rows**.

### 2.6 Migration handling already present

`_migrate_tileset` rebases glyph codes from 160 to 96 for `formatVersion <= 4`; v1–v3 files gain a derived `levelMetatileSet`. The mechanism is sound and v2 should extend it rather than replace it.

---

## 3. Coordinate systems — the glossary

**This is the section that exists to stop "metatile row 90" being confused with "worldProgress row 90".**

Anchor facts, all from `src/scroll.asm` and `src/terrain.asm`:

* The playfield **scrolls downward**; the player flies *up* through the stage; new terrain enters at the **top**.
* The editor stores rows **top-to-bottom in visual order**, and the authored **bottom** is where play begins.
* `stageTopRow` starts at `STAGE_START_ROW` and **decreases**; `worldProgress` starts at 0 and **increases**.
* The exact invariant, quoted from `src/scroll.asm`:
  `stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS`

### 3.1 The domains

| # | domain | unit | width | origin | direction | wraps | authored? |
|---|---|---|---|---|---|---|---|
| 1 | **editor metatile row** | 4×4-char tile | int | 0 = authored **top** | down | no | **yes** |
| 2 | **metatile column** | tile | 0..9 | 0 = left | right | no | **yes** |
| 3 | **metatile sub-cell** | char | 0..3 each | tile TL | — | no | **yes** |
| 4 | **logical char row** (`stage row`) | char row | 0..`STAGE_ROWS-1` | 0 = authored top | down | no | derived |
| 5 | **screen/matrix row** | char row | 0..24 | 0 = top of matrix | down | no | no |
| 6 | **fine scroll** `scrollFine` | pixel | 0..7 | — | counts **up** | 7→0 | no |
| 7 | **`stageTopRow`** | logical row | 16-bit | `STAGE_START_ROW` | **decreases** | mod `STAGE_ROWS` | no |
| 8 | **`worldProgress`** | coarse row | **16-bit** | 0 at stage start | **increases** | **never** | no |
| 9 | **turret row** | logical char row | 16-bit | 0 = authored top | down | no | **yes** (derived from 1) |
| 10 | **trigger row** | **`worldProgress`** | **16-bit** | 0 | increases | no | **yes** |
| 11 | **`STAGE_NO_SPAWN_ROW`** | **`worldProgress`** | **16-bit** | 0 | increases | no | **yes** |
| 12 | **sprite X** | pixel | 9-bit, 0..511 | 0 = left border | right | no | **yes** |
| 13 | **sprite Y** (`logY`) | raster | 8-bit, 0..255 | — | down | no | **yes** |
| 14 | **heading** | 1/64 turn | 0..63 | 0 = **east** | **clockwise** | `AND 63` | **yes** |

### 3.2 The conversions

With `METATILE_H = 4`, `SCREEN_ROWS = 25`:

```
STAGE_ROWS               = STAGE_METATILE_ROWS * METATILE_H        # 105*4 = 420
STAGE_START_ROW          = STAGE_ROWS - SCREEN_ROWS                # 420-25 = 395
STAGE_FINAL_VIEW_PROGRESS= STAGE_START_ROW                         # 395

logicalRow   = metatileRow * 4 + subRow                            # 0..STAGE_ROWS-1
turretRow    = metatileRow * 4 + 1                                 # TURRET_ROW_PHASE
turretWorldX = 24 + metatileCol * 4 * 8                            # pixels
stageTopRow  = (STAGE_START_ROW - worldProgress) mod STAGE_ROWS

# THE ONE THAT MATTERS:
worldProgress = STAGE_FINAL_VIEW_PROGRESS - stageRowAtTopOfAperture
stageRowAtTopOfAperture = STAGE_FINAL_VIEW_PROGRESS - worldProgress
```

**Turret rows and trigger rows are NOT the same domain.** A turret's row is a *logical char row measured from the authored top*. A trigger's row is *`worldProgress`, measured from the start of play*. They point in opposite directions.

### 3.3 Worked examples (Level 1, 105 metatile rows)

**A — a turret.** Editor turret at `metatileRow = 27, metatileCol = 3`.
`turretRow = 27*4 + 1 = 109`. `turretCol = 3*4 + 1 = 13`. `turretX = 24 + 13*8 = 128`.
Emitted into `turretRows`/`turretCols` as `109` / `13` — both present in `src/level1/stage_turrets.asm`. It is crossed when `worldProgress ≈ 395 − 109 = 286`, i.e. about `286*8/50 = 45.8 s` into the level.

**B — a trigger.** The authored sweep fires at **`worldProgress = 48`**, which is `48*8 = 384` frames = **7.7 s** in. In editor stage-row terms that is `395 − 48 = 347` — a row near the *bottom* of the authored map, which is correct because play starts at the bottom.

**C — the editor's current data, converted.** `waveTriggers[0].worldRow = 390` → `worldProgress = 395 − 390 = 5`. `worldRow = 0` → `worldProgress = 395`. The descending editor list becomes an ascending engine list, which is exactly the ordering the engine requires.

**D — the no-spawn row.** `STAGE_NO_SPAWN_ROW = 340` is `worldProgress`. Quiet zone = `395 − 340 = 55` coarse rows = `55*8/50 = 8.8 s`.

---

## 4. Stage dimensions and duration

### 4.1 Verified limits

| | value | source |
|---|---|---|
| width | **10 metatiles = 40 chars**, fixed | `METATILES_PER_ROW * METATILE_W == SCREEN_COLS` guard |
| max metatile rows | **440** | `STAGE_METATILE_ROWS * 10 > LEVELPKG_MAP_MAX (4400)` → error |
| turret ceiling on rows | 512 metatile / 2047 logical | `turrets.asm` guards — **not binding** |
| min rows | **7 metatile rows** (26 logical) | `STAGE_ROWS < SCREEN_ROWS + 1` → error |
| scroll rate | **1 px/frame**, coarse row every **8 frames** | `scrollTick` per frame, `inc scrollFine` |
| Level 1 | 105 rows | `stage_config.asm` |

### 4.2 The duration formula for Contract v2

```
logicalRows      = metatileRows * 4
playableRows     = logicalRows - 25          # = STAGE_FINAL_VIEW_PROGRESS
playableFrames   = playableRows * 8
playableSeconds  = playableFrames / 50
```

The **playable** distance is `STAGE_FINAL_VIEW_PROGRESS`, not the full map height: the last 25 logical rows are the final screenful, already on display when the stage ends.

| rows | logical | playable rows | seconds | m:ss |
|---|---|---|---|---|
| 105 (**Level 1**) | 420 | 395 | 63.2 | **1:03** |
| 288 | 1152 | 1127 | 180.3 | 3:00 |
| 381 | 1524 | 1499 | 239.8 | 4:00 |
| **440 (max)** | 1760 | 1735 | 277.6 | **4:38** |

**The 3–4 minute design target needs 288–381 metatile rows**, comfortably inside 440. The 440-row budget is therefore correctly sized for the stated goal, and Level 1 at 1:03 is well short of it.

The editor currently reports **2:14** for Level 1 — wrong twice over: it multiplies by the inert `scrollFrameDivider` (×2) and counts the full map height rather than the playable distance.

**Boss effect on perceived duration:** the quiet zone is inside the playable distance, not additional. After `stageComplete`, `LP_CLEARING` adds up to `ARENA_CLEAR_DEADLINE = 200` frames (4 s), then the boss fight is untimed. The editor should display *terrain duration* and label it as such.

---

## 5. Glyph and metatile contract

| item | value | source |
|---|---|---|
| terrain glyph base | **96** | `TERRAIN_GLYPH_BASE` |
| terrain glyphs in use | codes **96..167** (72) | `TERRAIN_GLYPH_COUNT = 72` |
| bytes per glyph | **8** (single-colour-pair 8×8, rendered multicolour) | charset |
| charset window | **`$0800-$0fff`**, 2 KB, VIC bank 0 | `TERRAIN_CHARSET` |
| terrain glyph bitmaps | `$0800 + 96*8` = **`$0b00`** | `TERRAIN_GLYPHS` |
| turret glyphs | codes **226..229** at `$0f10` | `TURRET_GLYPH_BASE` |
| **max terrain glyphs** | **130** | `TURRET_GLYPH_BASE(226) >= 96 + count` |
| metatile | **4×4 chars = 32×32 px** | `METATILE_W/H` |
| metatile def | **16 bytes**, row-major `def[subRow*4+col]` = char code | `terrain.asm` |
| metatile ID | **1 byte**, 0..`STAGE_METATILE_COUNT-1` | map cell |
| max metatile defs | **64** | `LEVELPKG_DEFS_MAX / 16` |
| Level 1 defs | **34** | `stage_config.asm` |

The build-time namespace guard is `TERRAIN_GLYPH_BASE + TERRAIN_GLYPH_COUNT > 256` (≤160), but the **binding** limit is the turret base at 226, giving **130**. The editor's namespace of 128 is safe; it should be stated as 130 with 128 as the conservative editor bound.

### 5.1 Colour — no per-cell colour, and none is coming

Verified in `src/terrain.asm`:

* `TERRAIN_BACKGROUND_COLOUR` → `$d021` (bit pair 00) — written by the renderer's aperture splits, not `terrainInit`.
* `TERRAIN_MC_COLOUR_1` → `$d022` (01).
* `TERRAIN_MC_COLOUR_2` → `$d023` (10).
* `TERRAIN_CHARACTER_COLOUR` → colour RAM low 3 bits (11); `TERRAIN_COLOUR_RAM = 8 | character`, so **every cell is multicolour**.

> *"COLOUR RAM IS WRITTEN ONCE, AT INIT, AND NEVER AGAIN … there is one `$d800` for both screen pages … A per-cell colour table would double the row cost AND require a colour-RAM double buffer that does not exist."*

**The editor may author exactly four colour indices (0..15) and nothing else.** Per-cell colour must not be represented, offered, or stored. `character` is masked to 3 bits by `8 | c`, so values 8..15 alias 0..7 — the editor should restrict `character` to **0..7** and say why.

---

## 6. Turret contract — with its v2 temporary limits

| field | domain | range | notes |
|---|---|---|---|
| `metatileRow` | editor metatile row | `0 .. STAGE_METATILE_ROWS-1` | authored |
| `metatileCol` | metatile column | `0..9` | authored |
| `turretRows[i]` | logical char row, 16-bit | `= metatileRow*4 + 1` | generated |
| `turretCols[i]` | char column | `= metatileCol*4 + 1` | generated |
| `TURRET_TOTAL` | count | **0..8** | generated |

Generated tables the engine derives: `turretMetaRow`, `turretCol`, `turretRowLo/Hi`, `turretXLo/Hi` (`= 24 + col*8`), and `turretAtMetaRow` (two pages, `TURRET_NONE = $ff`).

**Build-time rules, all currently enforced:**

* `turretRows[t] mod 4 == 1` — "authored turret row is not metatileRow * METATILE_H + 1"
* `turretRows[t] + 2 - 1 < TERRAIN_STAGE_ROWS`
* `turretCols[t] + 2 <= 40`
* **no two turrets share a metatile row** — "turretAtMetaRow holds only one"
* `turretCols.size() == turretRows.size() == TURRET_TOTAL`
* `TURRET_TOTAL <= 8`
* ordering: emitted **descending by world row** (ties by ascending column)

### ⚠ Contract v2 temporary engine limitations

> **`TURRET_TOTAL > 8` is a hard build error**, because `trtDeadPending` is a single byte holding one bit per turret (`trtVisibleMask` likewise). **One turret per metatile row** is likewise a hard error, because `turretAtMetaRow` stores one index per row.
>
> Both are scheduled to be lifted. Until they are, **the editor must refuse to export a ninth turret or a second turret on a row** — an ERROR, never a silent drop. `TURRET_NONE` also constrains any future rise to ≤127 (`bmi` sign test).

---

## 7. Movement-program contract

Record width `WM_STAGE_SIZE = 4`. Pool at `LEVELPKG_MOVE = $f532`, **max 256 bytes = 64 records**.

### 7.1 The record

| byte | `WM_STRAIGHT` / `WM_HOLD` | `WM_ARC` / `WM_ARC_MIRROR` | `WM_EXIT` |
|---|---|---|---|
| 0 | kind | kind | kind |
| 1 | **frames** (≥1) | **heading steps** (≥1) | ignored |
| 2 | **vx**, signed ¼px/frame | **frames per step** (≥1) | ignored |
| 3 | **vy**, signed ¼px/frame | **entry heading** 0..63, or `WM_HEAD_CONT` ($ff) | ignored |

Opcodes: `WM_STRAIGHT = 0`, `WM_ARC = 1` (clockwise), `WM_ARC_MIRROR = 2` (anticlockwise), `WM_EXIT = 3`, `WM_HOLD = 4`; `WM_MODES = 5`.

### 7.2 Headings

`WM_HEAD_LEN = 64`, mask 63, **clockwise from east** with **+y down**: 0 = east `(+6,0)`, 8 = down-right, 16 = south `(0,+6)`, 24 = down-left, 32 = west, 48 = north. Speed `WM_ARC_SPEED = 6` quarter-pixels/frame (1.5 px/frame, 75 px/s). `WM_QUARTER = 16`. Default `WM_ARC_STEP = 4`.

Turn radius `= WM_ARC_SPEED * f * 64 / (8π)` — **61 px at f=4, 31 px at f=2**.

### 7.3 Explicit heading versus deliberate continuation

This is the distinction the editor must never blur:

* **`heading 0..63` — self-contained.** The arc begins on that heading whatever the object was doing. A program that names its headings is a pure function of its own bytes and can be shared by any encounter and previewed standalone.
* **`WM_HEAD_CONT ($ff)` — joined.** The arc continues from the heading already held. This is what makes an S-turn an S rather than two unrelated curves.

Historically byte 3 was unread and an arc inherited the **wave definition's launch heading** — an input from outside the program. Three of four programs depended on it. **A v2 editor must always write byte 3 explicitly** — a real heading or `WM_HEAD_CONT` — and must never leave it implicit. The stale-`wmPhase` dependency must not be recreated.

`WM_EXIT` reads none of its bytes and **keeps the velocity the previous stage left**, which is what makes ARC → EXIT continuous.

### 7.4 Validation (all enforced today)

* last record of every program **must** be `WM_EXIT`
* `WM_EXIT` is terminal — nothing may follow it
* `rec[1] >= 1` on every non-EXIT stage
* arcs: `rec[2] >= 1`
* arcs: `rec[3] == $ff` or `0 <= rec[3] < 64`
* straight/hold: `abs(rec[2]) <= ENEMY_CLEAR_X_LEFT * 4`
* pool `<= 256` bytes and a whole number of 4-byte records
* program offsets are **byte offsets computed from `progAt`**, never hand-authored

Level 1: 4 programs, 13 records, **52 bytes** (`$f532-$f565`); offsets 0, 12, 24, 40.

### 7.5 What a preview would need to simulate (design note only — do not build yet)

Quarter-pixel integrator: per frame, accumulate `vx/vy`; for arcs step the heading every `f` frames and re-derive velocity from the 64-entry table. Termination is the **despawn rule**, not a coordinate fence. The assembler already flies every path under exactly these rules with `SIM_FRAME_BUDGET = 900` and `SIM_ENTER_BUDGET = 240`, so a preview that agrees with `src/waves.asm` is the correctness target.

---

## 8. Wave-definition contract

`WAVEDEF_SIZE = 10`. Table at `LEVELPKG_WAVEDEF = $f632`. Indexing `waveDefTable + n, y` with `y = def * 10`.

| off | field | unit / range | consumer |
|---|---|---|---|
| 0 | `count` | members, **≥1**, ≤8 in practice | `wvLeft` |
| 1 | `interval` | frames between members, **≥1** | `wvTimer` |
| 2 | `startXLo` | 9-bit spawn X, 0..511 | `logXLo` |
| 3 | `startXHi` | high bit of X | `logXHi` |
| 4 | `startY` | raster, 0..255 | `logY` |
| 5 | `xStep` | **signed**, added per member | spawn fan |
| 6 | `yStep` | **signed**, added per member | spawn fan |
| 7 | `colour` | C64 colour **0..15** | `logCol`, `wmBaseCol` |
| 8 | `heading` | launch heading **0..63** | `wmPhase` |
| 9 | `program` | **byte offset** into the movement pool | `wmStage` |

**Byte 9 is authored as a program *index* and emitted as that program's *byte offset*** (`progAt.get(def.get(9))` in `level_package.asm`). The editor authors an index; the exporter translates. This is what stops an offset disagreeing with the records it points at.

### 8.1 Ceiling: why 26

`waveDefBase` forms `def * 10` in **one byte**. The last reachable definition is index 25 (250). The table is therefore exactly **26 records / 260 bytes**, every byte addressable; the 60 bytes a rounder 32-record table would waste go to the triggers. Guard: `(LEVELPKG_WAVEDEF_SLOTS - 1) * 10 > 255` → error.

Definition index **0 has no special meaning**. Definitions are **reusable templates**: several triggers may name the same definition, and the species/fire/side that vary between appearances live on the *trigger*, not the definition. Level 1 uses 4 definitions for 4 triggers, but that is content, not a rule.

### 8.2 Validation (enforced)

`count >= 1`; `interval >= 1`; `0 <= heading < 64`; `program < progs.size()`; spawn **entirely off-screen** (hidden above `y0+20 < 55`, or left `x0+23 < 24`, or right `x0 > 343`); `0 <= x0 <= 511`; `0 <= y0 <= 255`. Then every member of every definition is **flown at assembly time** and must (a) reach a despawn edge within 900 frames, (b) be visible in the aperture at some point, (c) enter view within 240 frames, (d) never walk X past zero.

---

## 9. Absolute trigger contract

`LEVELPKG_TRIG = $f736`, `LEVELPKG_TRIG_COLS = 6`, `LEVELPKG_TRIG_SLOTS = 180`. **Six parallel columns**, each a fixed 180 bytes regardless of how many triggers the level authors; unused tail zero-filled.

| col | label | address | content |
|---|---|---|---|
| 0 | `waveTrigRowLo` | **`$f736`** | `worldProgress` low byte |
| 1 | `waveTrigRowHi` | **`$f7ea`** | `worldProgress` high byte |
| 2 | `waveTrigDef` | **`$f89e`** | wave-definition index, `< WAVE_DEFS` |
| 3 | `waveTrigSpecies` | **`$f952`** | `SPECIES_RING(0)` \| `SPECIES_DROPPER(8)` |
| 4 | `waveTrigFire` | **`$fa06`** | fire bitmask over member index |
| 5 | `waveTrigSide` | **`$faba`** | `DROP_SIDE_LEFT(0)` \| `DROP_SIDE_RIGHT(1)` |

Columns are fixed-base because the engine addresses them as constants; a column that shrank with the trigger count would move every column above it.

### 9.1 Semantics

* **Absolute 16-bit `worldProgress` rows.** Not deltas. The list **does not repeat**.
* **Due test is `>=`, not `==`** — a genuine 16-bit compare, high byte first. This is load-bearing: it lets a trigger held through a token encounter stay due, and makes a row the stage never reaches simply never fire.
* **No wrapping.** `worldProgress` only increases.
* **The cursor is the termination.** `wvNextTrig >= WAVE_TRIGGERS` is both the bounds check and "schedule exhausted", and it is terminal — nothing is reconsidered.
* **Equal rows are legal and meaningful.** Ordering is **non-decreasing, not strictly ascending**. `waveStartNext` consumes one trigger per tick, so a pair sharing a row arms on consecutive frames — this is how a mixed-species appearance is authored with no extra machinery.
* **Token hold.** `tkActive` pauses the director *below* the due test: a trigger due during a token encounter is **held, not lost**, and fires the frame the encounter ends. If it then finds both `WAVE_SLOTS` (=2) busy it is **dropped** and counted in `wvDropped`.
* **`STAGE_NO_SPAWN_ROW` sits *above* the `tkActive` hold**, so it suppresses a held trigger too.

### 9.2 Ordering — and what happens if it is wrong

**Non-decreasing order is a build error if violated**, not a runtime fixup:

> *"the authored trigger rows are not in non-decreasing order"*

Because the cursor only walks forward, an out-of-order trigger could never become due — it would be invisible in play rather than a build failure. **The exporter must sort by `worldProgress` ascending and must treat any inversion it cannot resolve as an ERROR.** Ties are preserved in authored order.

### 9.3 Other enforced rules

* `0 <= row <= $ffff`
* **`row < STAGE_NO_SPAWN_ROW`** — a trigger at or beyond it "could never start"
* `def < WAVE_DEFS`
* species by **membership**, not range (a species value is an animation row offset, so "< count" would be wrong)
* `(fire >> waveDefs[def].count) == 0` — no fire bit may name a member the wave never sends
* **no two consecutive triggers may use the same species**
* all six columns the same length

### 9.4 Scope note

The previously proposed **seven-byte interleaved trigger format is explicitly not adopted**. Contract v2 exports the six parallel columns above. The editor may hold a structured object internally; the export shape is the engine's.

---

## 10. `STAGE_NO_SPAWN_ROW` contract

| | |
|---|---|
| authored as | `.const STAGE_NO_SPAWN_ROW` in `src/level1/stage_config.asm` |
| **stored as** | **runtime package data**, 2 bytes little-endian at `LEVELPKG_STAGE = $f530-$f531` |
| read as | `waveNoSpawnLo = $f530`, `waveNoSpawnHi = $f531` |
| width | **16-bit** |
| domain | **`worldProgress` coarse rows** — the same domain as a trigger row |
| Level 1 | **340**, giving `395 − 340 = 55` rows = **8.8 s** quiet zone |

**Both forms exist on purpose.** The `.const` is what the editor authors and what the *engine build* validates against; the two bytes are what the *running director* compares. Both builds import `stage_config.asm`, so they cannot drift. It was moved to package data deliberately: as a compiled-in immediate it silently invalidated `tests/test_wave_triggers.py`, which writes synthetic rows at 255…1536 — all beyond any threshold Level 1 could legally carry.

### 10.1 Semantics

The gate, from `waveTick`, runs **before** the due test and **before** the `tkActive` hold:

```
if (worldProgress >= STAGE_NO_SPAWN_ROW) { wvNextTrig = WAVE_TRIGGERS }   // terminal
```

* Comparison is **`>=` suppresses**; `<` may start. So row `STAGE_NO_SPAWN_ROW` itself is **forbidden**.
* **Terminal, not skip-and-retry**: writing `WAVE_TRIGGERS` into the cursor means the bounds test takes over from the next frame and the 16-bit compare is paid only while triggers remain.
* **Suppresses a held trigger**, deliberately — a trigger due before the threshold but still waiting on a token encounter when the world crosses it has not *started*, and the contract is that nothing unstarted may begin at or beyond the row.
* **Already-running waves are untouched.** The gate is only reached on the way to *starting* one.
* **Dropper / token / protector choreography is unaffected.** Those are engine state machines with their own lifetimes; the gate governs only `waveStartNext`.
* **Boss entry is independent**: `stageComplete` is set by the scroller at `STAGE_FINAL_VIEW_PROGRESS`; `bossWatchStage` notices it and enters `LP_CLEARING`. The quiet zone exists so the arena is *already* clear when that happens, leaving `ARENA_CLEAR_DEADLINE` a backstop rather than the mechanism.

### 10.2 Build-time validation (enforced)

* `0 <= STAGE_NO_SPAWN_ROW <= $ffff`
* `STAGE_NO_SPAWN_ROW <= STAGE_FINAL_VIEW_PROGRESS`
* `STAGE_NO_SPAWN_ROW >= 1` — row zero would suppress the entire stage
* package side: `1 <= value <= $ffff`, header exactly 2 bytes
* every authored trigger row `< STAGE_NO_SPAWN_ROW`

**Runtime defensive behaviour:** the `waveTick` gate is robust whatever the data says — it must survive malformed external package data — but a level that *asks* for a trigger beyond the threshold has contradicted itself and the build says so.

### 10.3 How 55 was derived (the editor should reproduce this reasoning)

55 rows is **not** a round number. The longest authored wave footprint in Level 1 (the loop) is **48 coarse rows** from first member leaving the spawn line to last member reaching a despawn edge. The quiet zone must exceed the worst footprint, or a wave started on the last legal row could still be on screen when the stage ends. `tools/gen_proof420.py` scales it as `stage_end − 55` for the 420-row proof, confirming the rule travels.

**The editor must author this**, and should offer the derived default `STAGE_FINAL_VIEW_PROGRESS − max(waveFootprint)` with the longest footprint computed from the flight simulation.

---

## 11. Boss / stage-end contract

| | |
|---|---|
| stage end | `STAGE_FINAL_VIEW_PROGRESS = STAGE_START_ROW = STAGE_ROWS − 25` |
| set by | `scrollTick`, which freezes itself and sets `stageComplete` |
| noticed by | `bossWatchStage` → `LP_CLEARING`, arms `lvlTimer = ARENA_CLEAR_DEADLINE` |
| lifecycle | `LP_LEVEL(0) → LP_CLEARING(1) → LP_BOSS(2) → LP_VICTORY(3) → LP_EXIT(4) → LP_DONE(5)` |
| arena clear deadline | **200 frames (4 s)** — still current |

**Editor-controlled:** `STAGE_METATILE_ROWS` (which *is* the stage end, derived) and `STAGE_NO_SPAWN_ROW`.
**Engine-owned:** everything else — phases, deadline, boss identity, arena, bank-2 transition.

### Validation

| rule | class |
|---|---|
| `STAGE_NO_SPAWN_ROW < STAGE_FINAL_VIEW_PROGRESS` | **ERROR** (engine: `>` errors; `==` gives a zero-length zone) |
| `STAGE_NO_SPAWN_ROW >= 1` | **ERROR** |
| every trigger row `< STAGE_NO_SPAWN_ROW` | **ERROR** |
| quiet zone `>= longest authored wave footprint` | **WARNING** |
| quiet zone `< 25` rows (4 s) | **WARNING** — "a 0.2-second quiet zone is legal and poor" |
| quiet zone `> 40%` of the stage | **WARNING** — probably a mistake |

The distinction matters: **engine legality** is `1 <= row <= STAGE_FINAL_VIEW_PROGRESS` with all triggers below it. **Authoring quality** is whether the zone is long enough to actually clear the screen. Only the first may block an export.

---

## 12. Enum and symbol mappings

All from `src/encounter_format.asm` and `src/movement_format.asm` — both shared by *both* builds, which is exactly why they are the editor's source of truth.

### Species — `encounter_format.asm`
| symbol | value | note |
|---|---|---|
| `SPECIES_RING` | **0** | the Sonic Ring |
| `SPECIES_DROPPER` | **8** | the Orbital Dropper |
| `SPECIES_COUNT` | 2 | |

**A species value is its animation ROW OFFSET, not an index** (`species ORA step`). Validate by **membership**, never by range.

### Dropper side — `encounter_format.asm`
| symbol | value |
|---|---|
| `DROP_SIDE_LEFT` | 0 |
| `DROP_SIDE_RIGHT` | 1 |

Read **only** when species is `SPECIES_DROPPER`; a Ring wave carries whatever is written and ignores it.

### Movement opcodes — `movement_format.asm`
| symbol | value |
|---|---|
| `WM_STRAIGHT` | 0 |
| `WM_ARC` | 1 (clockwise) |
| `WM_ARC_MIRROR` | 2 (anticlockwise) |
| `WM_EXIT` | 3 |
| `WM_HOLD` | 4 |
| `WM_MODES` | 5 |
| `WM_HEAD_CONT` | **$ff** |

### Headings
0..63, clockwise from east, `+y` down. 0 E, 8 down-right, 16 S, 24 down-left, 32 W, 48 N. `WM_QUARTER = 16`.

### Firing
A **bitmask over member index**, bit 0 = first member sent. `0` = the wave never shoots. Not a rate: *"A mask says WHICH SILHOUETTES ON SCREEN ARE THE DANGEROUS ONES."* Level 1: sweep `%0101`, s-turn `%0010`, linger `%0101`, loop `%0000`.

### Formations
**There is no formation enum.** A "formation" is the emergent result of `count`, `interval`, `startX/Y`, `xStep`, `yStep` and the movement program. The editor must not invent one.

### Colour
0..15, C64 palette, `logCol`. Terrain `character` colour is masked `8 | c` so only **0..7** are distinct.

### Engine-private — not editor-selectable
`WAVE_SLOTS (2)`, `ENEMY_ANIM_STEPS (8)`, `WM_ARC_SPEED/STEP`, `WM_HEAD_LEN`, `SIM_*` budgets, `ARENA_CLEAR_DEADLINE`, `LP_*`, `TURRET_*` behaviour constants, enemy sprite-window slots (`L1_SLOT_RING`/`L1_SLOT_DROPPER` — physical placement, engine-managed).

---

## 13. Engine-owned special behaviour — the boundary

`src/wave_encounters.asm` states the boundary itself:

> *"WHAT IS DELIBERATELY NOT HERE: anything the ENGINE owns. The Dropper's flight, the P-token, the protector conscription and the boss lifecycle are engine state machines that a level does not author; the only thing a level says about the Dropper is which trigger carries it and which side it enters from."*

| behaviour | owner | what the editor may say |
|---|---|---|
| Dropper flight (weave, three passes, reversals, escape) | `src/dropper.asm` | **only** species + side |
| P-token lifecycle, collection, egress | `src/token.asm` | **nothing** |
| Protector conscription, guard post, orbit | `src/token.asm` | **nothing** |
| Token hold on the director (`tkActive`) | `src/token.asm` | **nothing** |
| Boss spawn, arena, bank-2 transition, victory | `src/boss.asm`, `src/vicbank.asm` | **nothing** |
| Enemy animation, sprite window slots | `src/enemy.asm`, `src/level_assets.asm` | **nothing** |

**The token column has been removed from the trigger list.** A P-token is no longer authored content an appearance brings — it is a **reward for destroying the level's one Dropper, dropped where that Dropper died**. A v2 project must **not** carry a token X, and migration must drop any it finds.

---

## 14. Proposed Project JSON v2

Design principles: **one authoritative value per fact** (derive byte counts and durations, never persist them); **symbolic names in JSON**, numeric translation in the exporter; **no engine-owned state**.

```jsonc
{
  "formatVersion": 6,
  "name": "level1",

  "stage": {
    "metatileRows": 105,            // int, 7..440, REQUIRED, authoritative
    "metatileCols": 10,             // int, fixed 10, REQUIRED
    "noSpawnRow": 340               // int, worldProgress, 1..playableRows-1
  },

  "palette": {                      // colour indices, not RGB
    "background":   12,             // 0..15  -> $d021
    "multicolour1": 15,             // 0..15  -> $d022
    "multicolour2": 11,             // 0..15  -> $d023
    "character":     1              // 0..7   -> colour RAM (8|c)
  },

  "glyphs":  { "count": 72, "bitmaps": [[8 ints], ...] },   // DERIVED cache
  "metatileDefs": [[16 char codes], ...],                   // DERIVED cache
  "levelMetatileSet": [ /* native 32x32 authoring source, 1..64 */ ],

  "map": [[10 metatile IDs], ...],  // metatileRows x 10, top-to-bottom

  "turrets": [
    { "metatileRow": 1, "metatileCol": 3 }   // 0..8 entries, distinct rows
  ],

  "movementPrograms": [
    { "id": "sweep",
      "stages": [
        { "kind": "STRAIGHT", "frames": 34, "vx": 6, "vy": 0 },
        { "kind": "ARC",      "steps": 16, "framesPerStep": 4, "entryHeading": 0 },
        { "kind": "EXIT" }
      ] }
  ],

  "waveDefinitions": [
    { "id": "sweep",
      "count": 4, "interval": 22,
      "startX": 0, "startY": 64,
      "xStep": 0, "yStep": 20,
      "colour": 10, "heading": 0,
      "movementProgram": "sweep" }     // by ID; exporter resolves to byte offset
  ],

  "triggers": [
    { "worldProgress": 48,
      "waveDefinition": "sweep",
      "species": "RING",               // "RING" | "DROPPER"
      "fireMask": [0, 2],              // member indices, or an int bitmask
      "dropperSide": "LEFT" }          // "LEFT" | "RIGHT"; ignored unless DROPPER
  ]
}
```

### Field table

| path | type | unit | req | default | validation | owner |
|---|---|---|---|---|---|---|
| `formatVersion` | int | — | ✔ | 6 | `== 6` on write | tool |
| `name` | str | — | ✔ | — | non-empty | user |
| `stage.metatileRows` | int | metatile rows | ✔ | — | 7..440 | **user** |
| `stage.metatileCols` | int | — | ✔ | 10 | `== 10` | fixed |
| `stage.noSpawnRow` | int | **worldProgress** | ✔ | derived | 1..playable−1; > all trigger rows | **user** |
| `palette.*` | int | colour index | ✔ | see §2 | 0..15; `character` 0..7 | user |
| `glyphs.count` | int | — | ✔ | — | 1..130 | **derived** |
| `glyphs.bitmaps[n]` | int[8] | bytes | ✔ | — | each 0..255 | derived |
| `metatileDefs[n]` | int[16] | char codes | ✔ | — | each 96..96+count−1 | **derived** |
| `levelMetatileSet` | list | — | ✔ | — | 1..64 | **user** |
| `map[r][c]` | int | metatile ID | ✔ | 0 | 0..len(defs)−1 | **user** |
| `turrets[i].metatileRow` | int | metatile row | ✔ | — | 0..rows−1, **distinct** | **user** |
| `turrets[i].metatileCol` | int | metatile col | ✔ | — | 0..9 | **user** |
| `movementPrograms[i].id` | str | — | ✔ | — | unique | user |
| `…stages[j].kind` | enum | — | ✔ | — | STRAIGHT/ARC/ARC_MIRROR/EXIT/HOLD | user |
| `…frames` / `…steps` | int | frames / heading steps | ✔¹ | — | ≥1 | user |
| `…vx`,`…vy` | int | ¼ px/frame, signed | ✔¹ | — | `abs ≤ ENEMY_CLEAR_X_LEFT*4` | user |
| `…framesPerStep` | int | frames | ✔² | 4 | ≥1 | user |
| `…entryHeading` | int\|"CONT" | 1/64 turn | ✔² | — | 0..63 or `"CONT"` — **never omitted** | **user** |
| `waveDefinitions[i].id` | str | — | ✔ | — | unique | user |
| `…count` | int | members | ✔ | — | ≥1 (≤8 practical) | user |
| `…interval` | int | frames | ✔ | — | ≥1 | user |
| `…startX` | int | px, 9-bit | ✔ | — | 0..511, spawn off-screen | user |
| `…startY` | int | raster | ✔ | — | 0..255, spawn off-screen | user |
| `…xStep`,`…yStep` | int | px, signed | ✔ | 0 | member fan stays in range | user |
| `…colour` | int | colour index | ✔ | — | 0..15 | user |
| `…heading` | int | 1/64 turn | ✔ | — | 0..63 | user |
| `…movementProgram` | str | program ID | ✔ | — | must exist | user |
| `triggers[i].worldProgress` | int | **worldProgress** | ✔ | — | 0..65535, `< noSpawnRow` | **user** |
| `…waveDefinition` | str | def ID | ✔ | — | must exist | user |
| `…species` | enum | — | ✔ | — | `RING`\|`DROPPER`; no two consecutive equal | user |
| `…fireMask` | int[] \| int | member indices | ✔ | `[]` | every index `< count` | user |
| `…dropperSide` | enum | — | — | `LEFT` | `LEFT`\|`RIGHT` | user |

¹ STRAIGHT/HOLD only · ² ARC/ARC_MIRROR only

### Deliberately absent

`scrollFrameDivider` (inert), `width`/`height` as separate top-level keys (folded into `stage`), `attackId`, `enemyType`, `composition`, token X, any per-cell colour, byte counts, durations, program byte offsets, `TURRET_TOTAL`, `STAGE_METATILE_COUNT`, `TERRAIN_GLYPH_COUNT` — all derived at export.

---

## 15. Migration from v5

| v5 field | v6 | notes |
|---|---|---|
| `formatVersion: 5` | → `6` | |
| `name` | unchanged | |
| `width` | → `stage.metatileCols` | assert `== 10` |
| `height` | → `stage.metatileRows` | **ERROR if > 440** — 105 is fine |
| `scrollFrameDivider` | **dropped** | inert; record the drop in a migration note |
| `palette` | unchanged | warn if `character > 7` |
| `metatileRows` | → `map` | renamed only |
| `metatileMetadata` | **dropped** | empty and undocumented |
| `objects` | → `turrets` | filter `type == "turret"`; **ERROR if > 8**; drop `type` |
| `levelMetatileSet` | unchanged | |
| `tileset.glyphs` | → `glyphs.bitmaps` | |
| `tileset.glyphCount` | → `glyphs.count` | recompute, don't trust |
| `tileset.metatileDefs` | → `metatileDefs` | |
| `waveDefinitions` | **DISCARDED** | attack-catalogue model; no engine counterpart |
| `waveTriggers` | **DISCARDED** | see below |
| — | `stage.noSpawnRow` | **new**, no v5 source |
| — | `movementPrograms` | **new**, no v5 source |

### 15.1 Migration is lossy, and deliberately so

**The 33 wave definitions and 53 triggers cannot be migrated.** `attackId` 0..11 indexed a curated catalogue that supplied formation, pattern, ingress and egress; that catalogue no longer exists in any form. `enemyType` 0..3 does not map onto `SPECIES_COUNT = 2`. Nothing in the v5 data supplies `startX/Y`, `xStep/yStep`, `heading`, a movement program, a fire mask or a Dropper side.

Attempting a mapping would be inventing content. **The correct migration is to drop them and say so loudly**, leaving `movementPrograms`, `waveDefinitions` and `triggers` empty.

The trigger *rows* are worth preserving as a **commented-out suggestion list**, converted to the right domain (`worldProgress = playableRows − worldRow`), so an author can see where encounters used to sit. They must not be emitted as live triggers.

### 15.2 Defaults for new data

* `stage.noSpawnRow`: default `playableRows − 55`; for Level 1 that is `395 − 55 = 340`, matching the committed value exactly.
* `movementPrograms` / `waveDefinitions` / `triggers`: empty lists. **A level with no triggers is legal** — the cursor is immediately exhausted and the stage is simply quiet.

### 15.3 Determinism

Migration of everything *except* the encounter data is **deterministic and lossless** — terrain, palette, metatiles, glyphs and turrets round-trip exactly. The encounter data is **deterministically discarded**. Both halves are reproducible; the tool must report which fields it dropped.

---

## 16. Export contract

Two artefacts, because the level is **two build inputs**: constants the engine compiles against, and bytes the package emits.

| file | dest | role | in engine PRG? |
|---|---|---|---|
| `stage_config.asm` | `src/level1/` | constants only | **yes**, imported early |
| `stage_charset.asm` | `src/level1/` | terrain glyph bitmaps | **yes**, at `$0b00` |
| `stage_map.asm` | `src/level1/` | `metatileDefs:` then rows | **no** — split into `build/stage_map_{defs,rows}.asm`, emitted into `LEVEL1` |
| `stage_turrets.asm` | `src/level1/` | `TURRET_TOTAL`, `turretCols`, `turretRows` | **yes** |
| `wave_programs.asm` | **`src/`** | `progs` list | both builds |
| `wave_encounters.asm` | **`src/`** | `waveDefs`, `trigRow`, `trigDef`, `trigSpecies`, `trigFire`, `trigSide` | both builds |

### Symbols each must emit

**`stage_config.asm`** — `STAGE_METATILE_ROWS`, **`STAGE_NO_SPAWN_ROW`** *(new)*, `STAGE_METATILE_COUNT`, `TERRAIN_BACKGROUND_COLOUR`, `TERRAIN_MC_COLOUR_1`, `TERRAIN_MC_COLOUR_2`, `TERRAIN_CHARACTER_COLOUR`, `TERRAIN_COLOUR_RAM`, `TERRAIN_GLYPH_COUNT`. **Drop `SCROLL_FRAME_DIVIDER`.**

**`stage_charset.asm`** — `terrainGlyphs:` … `terrainGlyphsEnd:` with a self-checking byte count. **Fix the stale header**: codes 96..167 at `$0b00` in the `$0800` window, *not* `$3B00`.

**`stage_map.asm`** — `metatileDefs:` (16 bytes/def, row-major) then `stageMetatileRows:` … `STAGE_METATILE_ROWS_END:`. Order matters: the Makefile splits on those labels.

**`stage_turrets.asm`** — `TURRET_TOTAL`, `turretCols`, `turretRows`, **descending world row**.

**`wave_programs.asm`** — `progs` as nested `List()`s plus `PROG_*` constants; `progAt`/`progBytes` are computed by the existing code and must not be emitted.

**`wave_encounters.asm`** — `WAVEDEF_SIZE`, the `.var def*` lists, `waveDefs`, `WAVE_DEFS`, `WAVE_DEF_*`, `trigRow`, `trigDef`, `trigSpecies`, `trigSide`, `trigFire`, `WAVE_TRIGGERS`. **Byte 9 of a definition is the program INDEX**, not an offset.

### Conventions

Decimal for counts, rows, headings and colours; `%00000101` for fire masks; `$ff` for `WM_HEAD_CONT`. Header on every file: the `AUTO-GENERATED … DO NOT EDIT BY HAND` banner plus level name. Deterministic ordering everywhere: turrets descending by row, triggers ascending by `worldProgress` (ties in authored order), definitions and programs in declaration order. Byte-identical output for identical input — no timestamps, no dict iteration order, LF endings, trailing newline.

### Becoming generated-data-free

Once v2 is implemented, **`src/wave_programs.asm` and `src/wave_encounters.asm` become generated artefacts**. Both already say so:

> *"The level editor will eventually generate this file. Until it does, it is authored here."*

They must move under the level's own directory or gain the generated banner. **Do not do this now.** `src/movement_format.asm`, `src/encounter_format.asm` and `src/levelpkg.asm` stay **hand-maintained engine contracts** — they are the shared vocabulary, not level content.

---

## 17. Validation matrix

**ERROR** = cannot export · **WARNING** = legal but suspect · **DERIVED** = computed, never stored

### Terrain
| rule | class |
|---|---|
| `metatileCols == 10` | ERROR |
| `7 <= metatileRows <= 440` | ERROR |
| `metatileRows * 10 <= 4400` | DERIVED (equivalent) |
| every row exactly 10 entries | ERROR |
| `0 <= mapCell < len(metatileDefs)` | ERROR |
| `1 <= len(metatileDefs) <= 64` | ERROR |
| `1 <= glyphCount <= 130` | ERROR |
| glyph codes in `96 .. 96+glyphCount-1` | ERROR |
| glyph bitmap exactly 8 bytes, each 0..255 | ERROR |
| metatile def exactly 16 codes | ERROR |
| unreferenced metatile defs | WARNING |
| unreferenced glyphs | WARNING |
| `glyphCount`, `metatileCount`, map bytes | DERIVED |

### Turrets
| rule | class |
|---|---|
| `count <= 8` | **ERROR** *(v2 temporary)* |
| distinct `metatileRow` | **ERROR** *(v2 temporary)* |
| `0 <= metatileRow < metatileRows` | ERROR |
| `0 <= metatileCol <= 9` | ERROR |
| `turretRow + 1 < STAGE_ROWS` | ERROR |
| world row/col, X, descending order | DERIVED |

### Movement
| rule | class |
|---|---|
| pool `<= 256` bytes | ERROR |
| whole number of 4-byte records (`<= 64`) | ERROR |
| last stage is `EXIT` | ERROR |
| nothing follows `EXIT` | ERROR |
| `kind` in the five opcodes | ERROR |
| `frames`/`steps >= 1` | ERROR |
| `framesPerStep >= 1` (arcs) | ERROR |
| `entryHeading` is 0..63 or `"CONT"`, **always present** | ERROR |
| `abs(vx) <= ENEMY_CLEAR_X_LEFT*4` | ERROR |
| program offsets are record-aligned | DERIVED |
| program unreferenced by any definition | WARNING |
| `"CONT"` on a program's **first** arc | **WARNING** — inherits the launch heading; the old stale-`wmPhase` trap |

### Wave definitions
| rule | class |
|---|---|
| `count <= 26` definitions | ERROR |
| `count >= 1`, `interval >= 1` | ERROR |
| `0 <= startX <= 511`, `0 <= startY <= 255` | ERROR |
| every member spawns entirely off-screen | ERROR |
| `0 <= heading <= 63` | ERROR |
| `0 <= colour <= 15` | ERROR |
| `movementProgram` resolves | ERROR |
| flight reaches a despawn edge within 900 frames | ERROR |
| flight is visible in the aperture at some point | ERROR |
| flight enters view within 240 frames | ERROR |
| flight never walks X past zero | ERROR |
| `count > 8` | WARNING (exceeds `WAVE_SLOTS` practice) |
| definition unreferenced by any trigger | WARNING |

### Triggers
| rule | class |
|---|---|
| `count <= 180` | ERROR |
| `0 <= worldProgress <= 65535` | ERROR |
| **non-decreasing** after sort; unresolvable inversion | ERROR |
| `worldProgress < noSpawnRow` | ERROR |
| `waveDefinition` resolves | ERROR |
| `species` in {`RING`,`DROPPER`} | ERROR |
| no two **consecutive** triggers share a species | ERROR |
| every fire-mask index `< definition.count` | ERROR |
| `worldProgress > playableRows` | ERROR (unreachable) |
| more than 2 triggers due within a few rows | WARNING (`WAVE_SLOTS = 2`; third is dropped) |
| gap to next trigger `<` this wave's footprint | WARNING (formations overlap) |
| `dropperSide` present on a `RING` trigger | WARNING (ignored) |
| row lo/hi split, column padding to 180 | DERIVED |

### Boss approach
| rule | class |
|---|---|
| `1 <= noSpawnRow <= playableRows` | ERROR |
| `noSpawnRow < playableRows` | ERROR |
| quiet zone `>= longest wave footprint` | WARNING |
| quiet zone `< 25` rows (4 s) | WARNING |
| quiet zone `> 40%` of the stage | WARNING |

---

## 18. Capacity / budget table

| resource | physical package | engine indexing | editor should enforce | temporary? |
|---|---|---|---|---|
| stage width | 10 metatiles | 40 chars fixed | **10** | no |
| metatile rows | **440** (4400 B ÷ 10) | 512 (turret table) | **440** | no |
| map bytes | **4400** (`$e000-$f12f`) | — | derived | no |
| metatile defs | **64** (1024 B ÷ 16) | 1-byte ID | **64** | no |
| terrain glyphs | 2 KB charset window | code 96 + count | **130** | no |
| turrets | — | **8** (`trtDeadPending` byte) | **8** | **YES** |
| turrets per row | — | **1** (`turretAtMetaRow`) | **1** | **YES** |
| movement pool | **256 B** (`$f532-$f631`) | `wmStage` 1 byte | **256 B / 64 records** | **YES** |
| wave definitions | 260 B (`$f632-$f735`) | **26** (`def*10` ≤ 255) | **26** | **YES** |
| triggers | 1082 B (`$f736-$fb6f`) | **180** slots; 255 cursor max | **180** | no |
| concurrent waves | — | **`WAVE_SLOTS = 2`** | warn only | **YES** |
| encounter package | **1600 B** (`$f530-$fb6f`) | — | derived | no |
| whole package | **`$e000-$fff9`** (8186 B) | — | derived | no |
| trigger row width | 2 B | 16-bit `worldProgress` | 0..65535 | no |
| no-spawn row width | 2 B | 16-bit | 1..playable−1 | no |

### Current Level 1 occupancy

| region | address | used | budget | free |
|---|---|---|---|---|
| map | `$e000-$e419` | **1050** (105 rows) | 4400 | 3350 |
| metatile defs | `$f130-$f34f` | **544** (34 defs) | 1024 | 480 |
| stage header | `$f530-$f531` | **2** | 2 | 0 |
| movement pool | `$f532-$f565` | **52** (13 records) | 256 | 204 |
| wave definitions | `$f632-$f659` | **40** (4 defs) | 260 | 220 |
| triggers | `$f736-$fb6d` | **1080** reserved (4 authored) | 1082 | 2 |
| signature | `$fb70-$fb73` | **4** | 4 | 0 |
| spare | `$fb74-$fff9` | 0 | **1158** | 1158 |

---

## 19. Level 1 round-trip acceptance plan

**Target:** import the authoritative `src/level1/` + `src/wave_*.asm` into the v2 model, export, build, and prove equivalence.

### Tier 1 — byte-for-byte required

| artefact | comparison |
|---|---|
| `build/level1.prg` **map region** `$e000-$e419` | identical 1050 bytes |
| **metatile defs** `$f130-$f34f` | identical 544 bytes |
| **stage header** `$f530-$f531` | identical (`340` = `$54,$01`) |
| **movement pool** `$f532-$f565` | identical 52 bytes |
| **wave definitions** `$f632-$f659` | identical 40 bytes |
| **trigger columns** `$f736-$fb6d` | identical 1080 bytes incl. zero padding |
| **signature** `$fb70-$fb73` | `$19 $65 $6c $70` |
| `stage_charset.asm` glyph bytes | identical 576 bytes (72 × 8) |
| `stage_turrets.asm` lists | `TURRET_TOTAL = 8`; rows `345,337,225,217,117,109,25,5`; cols `17,25,29,9,25,13,25,13` |
| `stage_config.asm` values | every constant identical |

Byte equality of the **whole `level1.prg`** is the single strongest check and should be the headline assertion.

### Tier 2 — semantic where layout legitimately changes

Only the **comment text** of generated files may differ (stale headers are being corrected — §16). Assert on *parsed values*, not file bytes, for `.asm` sources; assert on **bytes** for `level1.prg`, which carries no comments.

### Tier 3 — behavioural

| check | how |
|---|---|
| four waves fire at rows 48, 52, 90, 126 | `tests/test_wave_triggers.py` |
| two Droppers, sides L then R | trigger columns + `test_token_encounter.py` |
| species alternate | build guard |
| no encounter starts at/after row 340 | `tests/test_no_spawn_row.py` |
| boss transition at `worldProgress = 395` | `tests/test_boss.py`, `test_lifecycle.py` |
| movement pool flown identically | `tests/test_movement_pool.py` |
| turrets appear at the same rows | `tests/test_turret_regression.py` |
| long-stage capability | `make proof420` — 420 rows, no-spawn rescaled to `stage_end − 55` |
| `gameOverrun == 0`, `scrollLate == 0` | boss/production suites |

### Tier 4 — build determinism

Export twice from the same project into separate directories; the generated files and `level1.prg` must be **byte-identical**. Export → import → export must also be a fixed point.

**Acceptance = Tier 1 byte equality + Tier 3 green + Tier 4 determinism.** Anything less means the model has lost information.

---

## 20. Recommended implementation phases

Derived from the audit: the model and exporter are the risk; the GUI is not. Keep them apart.

**Phase 1 — model + migration, no GUI.**
v6 schema, loader, validator (§17), v5→v6 migration (§15) including the loud discard of encounter data. Unit-testable with no Tkinter. *Done when: `levels/level1/level.json` migrates, validates, and the dropped fields are reported.*

**Phase 2 — deterministic exporter for what already round-trips.**
Emit `stage_config.asm` (with `STAGE_NO_SPAWN_ROW`, without `SCROLL_FRAME_DIVIDER`), `stage_charset.asm`, `stage_map.asm`, `stage_turrets.asm`. Fix the stale headers. Enforce the 8-turret ceiling. *Done when: Tier 1 terrain/turret/config artefacts are byte-identical and the game builds.*

**Phase 3 — importer for the authoritative engine data.**
Parse `src/wave_programs.asm` and `src/wave_encounters.asm` into the v2 model. This is what makes Level 1's encounters *exist* in the editor at all, and it must precede any authoring UI. *Done when: import → export reproduces both files' parsed values exactly.*

**Phase 4 — encounter exporter + full round-trip proof.**
Emit `wave_programs.asm` and `wave_encounters.asm`; run the §19 acceptance in full. *Done when: `level1.prg` is byte-identical and Tiers 3 and 4 pass.*

**Phase 5 — encounter authoring UI.** Triggers, definitions, movement programs as first-class editable objects, with §17 surfaced inline.

**Phase 6 — movement/wave preview.** The quarter-pixel simulator of §7.5, validated against `src/waves.asm`'s assembly-time flight proof.

**Phase 7 — usability.** Correct duration (§4.2), capacity gauges (§18), quiet-zone visualisation.

Phases 1–4 are the contract; 5–7 are the product. **Do not bundle a GUI rewrite with the exporter.**

---

## 21. Unresolved questions

1. **`metatileMetadata`** — empty in `level1.json`, no schema, no consumer found. Proposed dropped in v6; confirm nothing depended on it.
2. **Practical `count` ceiling.** The engine validates `count >= 1` but not an upper bound; the editor's old `WAVE_MAX_COMPOSITION_COUNT = 8` has no current engine counterpart. Whether >8 is safe with `WAVE_SLOTS = 2` is **not established from source** — flagged as WARNING, not ERROR.
3. **`level2/`** exists in the editor archive with its own `level.json`. The engine builds only `LEVEL1`. Whether Contract v2 should carry multi-level packaging is out of scope here and undecided.
4. **Editor-owned vs engine-owned glyph bitmaps.** `stage_charset.asm` is level-owned, but turret glyphs (226..229) are engine-owned in the same window. If a level ever wants custom turret art the boundary needs restating; today it does not.
5. **`ENEMY_CLEAR_X_LEFT`** bounds the straight/hold `vx` rule. Its value was not read during this audit; the exporter must import it from source rather than hard-code a number.
6. **Trigger column tail padding** is currently zero. Zero is a legal `worldProgress`, a legal def index and a legal species — safety rests entirely on `WAVE_TRIGGERS` bounding the cursor. Correct today; worth restating if the count ever becomes runtime data.

---

## 22. Confirmations

* **No implementation file was changed.** No engine source, no editor source, no project JSON, no generated stage data, no package layout. The only repository write is this report.
* `git status` at completion: `?? reports/level-editor-contract-v2-specification.md` and nothing else.
* **Nothing committed. Nothing pushed.**
* The editor archive was extracted to **disposable scratch**, never into the repository.
* **No VICE was launched** — every fact here came from source, generated files and one `make` whose memory map confirmed the package addresses. The manual VICE from the previous task (PID 88519) was already closed by the user; `pgrep -x x64sc` was clean throughout.
* Disk: `build/` **344 KB** (current binary and symbols only, no per-run directories); session scratch **5.0 MB**, almost all the extracted editor archive.
