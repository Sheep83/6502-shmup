# Level editor / current engine contract review

**Date:** 2026-09-17
**Engine HEAD:** `722dbbd` — *HUD bank switching, token progress*. Working tree **clean**.
**Editor source:** `~/Desktop/c64Shooter-main.zip` → `tools/level_editor/` (the editor is **not** in the current repo; the current repo's only Python outside `tests/` is `tools/gen_player_ship.py`).
**Changes made by this task: none.** Review only; nothing committed, nothing pushed. One export was run into `/tmp/lvlexp` and deleted afterwards.

---

## 0. The three findings that matter

1. **The terrain pipeline is alive and exact.** Re-exporting `levels/level1/level.json` through the editor's own `ka_export.export_level()` reproduces the shipped `src/level1/` package **byte-identically** (ignoring comments) for all four consumed files. The editor is not stale content-wise.
2. **The editor cannot read the current engine.** `engine_data.load_engine_data()` raises immediately: it looks for `src/generated/level1/stage_config.asm`; the engine moved the package to `src/level1/`. Three constants fix it.
3. **The editor's stage-length ceiling is wrong by 5–7×, in the dangerous direction.** It believes `ENGINE_MAX_STAGE_ROWS = 768`; the current linked layout allows **150** metatile rows with level 1's 34-metatile set (**102** with a full 64-metatile set). Authoring a "full-length" 400-row stage today produces a build that fails an assembler guard — or, if that guard is ever relaxed without moving the segment, silently overruns.

---

# Review 1 — the editor as it exists

## 1.1 Structure

`tools/level_editor/`, ~9,400 lines of Python/Tkinter, 47 files:

| file | lines | role |
|---|---|---|
| `editor.py` | 1,989 | the Tkinter application |
| `project.py` | 923 | project model, schema, validation, migration |
| `engine_data.py` | 443 | engine constants + parsers that read the engine back |
| `workshop_ui.py` | 436 | metatile/terrain workshop panels |
| `native_terrain_tiles.py` | 365 | native tile representation |
| `ka_export.py` | 314 | **the exporter** |
| `wave_repository.py` | 264 | reusable wave library |
| `terrain_repository.py` | 241 | reusable terrain asset library |
| `native_metatile.py` | 239 | 16×32 native metatile pixels |
| `level2_tileset.py`, `build_levels.py`, `import_generated_level.py`, `install_level1_terrain.py`, `recover_generated_terrain.py`, `spritesheet.py`, `terrain_convert.py`, … | — | tooling |
| `test_*.py` (25 files) | ~2,600 | editor-side unit/GUI tests |

Data: `levels/level1/level.json` (78 KB), `levels/level2/level.json` (35 KB), `terrain_repository/repository.json`, `wave_repository/repository.json`, `testdata/synthetic_tileset.png`.

## 1.2 Project JSON schema (`FORMAT_VERSION = 5`, supports 1–5 with migration)

```jsonc
{
  "formatVersion": 5,
  "name": "level1",
  "width": 10,                       // always METATILES_PER_ROW; derived, not free
  "height": 105,                     // metatile rows
  "scrollFrameDivider": 2,
  "palette": { "background": 12, "multicolour1": 15,
               "multicolour2": 11, "character": 1 },
  "metatileRows": [[10 ints], ...],  // height × 10 metatile indices
  "metatileMetadata": { ... },
  "objects": [ {"type":"turret","metatileRow":R,"metatileCol":C}, ... ],
  "levelMetatileSet": [ {"name":..., "native":{"width":16,"height":32,
                          "pixels":[32 rowstrings]}, "source":...}, ... ],
  "tileset": { "glyphCount": 72, "glyphs": [[8 bytes], ...],
               "metatileDefs": [[16 char codes], ...] },
  "waveDefinitions": [ {"id","name","attackId","composition":[{"enemyType","count"}],
                        "spawnInterval"} ],
  "waveTriggers":    [ {"id","worldRow","waveDef"} ]
}
```

**Canonicalisation is deterministic**: `canonical_wave_definitions()` sorts by `id`; `canonical_wave_triggers()` sorts by `(-worldRow, id)`; turrets are re-emitted in canonical form. Export is reproducible (proved in §3.1).

## 1.3 Engine constants the editor believes (`engine_data.py`)

| constant | editor value | note |
|---|---|---|
| `METATILE_W` / `METATILE_H` | 4 / 4 | ✅ matches engine |
| `METATILES_PER_ROW` | 10 | ✅ matches |
| `METATILE_CAPACITY` | 64 | ceiling on the level metatile set |
| `TERRAIN_GLYPH_BASE` | 96 | ✅ matches |
| `TERRAIN_GLYPH_NAMESPACE` | 128 (codes 96..223) | engine's real ceiling is **130** (96..225, turret bodies start at 226) — editor is conservative, safe |
| `ENGINE_MAX_STAGE_ROWS` | **768** | ❌ **wrong**, see §3.2 |
| `VIEWPORT_ROWS` | **23** | ❌ stale: assumes a fixed hires HUD on matrix row 0 |
| `VIEWPORT_COLS` | 40 | ✅ |
| `TURRET_POOL` | 8 | ❌ no longer how turrets work |
| `MAX_AUTHORED_TURRETS` | **255** | ❌ engine guard is `TURRET_TOTAL > 127` |
| `ATTACK_COUNT` | 12 | ❌ no attack catalogue exists in the engine any more |
| `ENEMY_TYPE_COUNT` | 4 | ❌ engine has `SPECIES_COUNT = 2` |
| `DEFAULT_SCROLL_FRAME_DIVIDER` | 2 | ❌ constant is dead in the engine |
| `GENERATED_DIR_REL` | `src/generated` | ❌ engine uses `src` |
| `GENERATED_STAGE_NAME` | `stage_test.asm` | ❌ engine file is `stage_map.asm` |

`load_engine_data()` also parses the engine back: `_parse_generated_config`, `_parse_generated_turrets`, and **`_parse_attack_catalogue(main.asm)`**, which scrapes `.const ATTACK_* = n`, `attackIntervalData` and `attackSpriteStartData`. The current `src/main.asm` contains **none** of these (`grep -c "\.const ATTACK_"` → 0 across `src/`).

## 1.4 What the exporter emits

`ka_export.export_level(project, out_dir)` writes five files:

| generated file | content |
|---|---|
| `stage_config.asm` | `STAGE_METATILE_ROWS`, `SCROLL_FRAME_DIVIDER`, `STAGE_METATILE_COUNT`, `TERRAIN_BACKGROUND_COLOUR`, `TERRAIN_MC_COLOUR_1`, `TERRAIN_MC_COLOUR_2`, `TERRAIN_CHARACTER_COLOUR`, `TERRAIN_COLOUR_RAM`, `TERRAIN_GLYPH_COUNT` |
| `stage_charset.asm` | `terrainGlyphs:` … `terrainGlyphsEnd:` + a size guard. **No `* =` directive** — address-independent |
| `stage_test.asm` | `metatileDefs:` (16 bytes/def) + `stageMetatileRows:` (10 bytes/row) + `METATILE_DEFS_END`, `STAGE_METATILE_ROWS_END` |
| `stage_turrets.asm` | `.const TURRET_TOTAL`, `.var turretCols = List()…`, `.var turretRows = List()…`, sorted descending by world row |
| `stage_waves.asm` | `.const WAVE_TRIGGER_COUNT`, `waveTriggerRowLo/Hi`, `waveTriggerAttackId`, `waveTriggerCount`, `waveTriggerSprite`, `waveTriggerInterval` |

Turret world mapping (`project.turret_world_row/col`): `row = metatileRow*4 + 1`, `col = metatileCol*4 + 1` (`TURRET_BODY_CHAR_OFFSET = 1`).

## 1.5 UI surface

Three edit modes on one toolbar: **Terrain**, **Turrets**, **Waves**. Stage-row spinbox bounded by `MIN_STAGE_ROWS=1 .. MAX_STAGE_ROWS=ENGINE_MAX_STAGE_ROWS`; a duration readout; an editor-only gameplay-viewport overlay (never saved/exported); a metatile workshop with repository import/save/duplicate/delete and capacity accounting; a wave panel with definition list, New/Duplicate/Delete and **Add from Library…** backed by `wave_repository/repository.json`.

Validation is substantial: `validate_project()` covers palette, metatile set, tileset, objects (turret placement, `turret_screen_peak`) and waves (`_validate_waves`); `export_readiness_errors()` gates export; `wrap_seam_warning()` flags the stage wrap seam.

**Known limitations visible in the code:** waves resolve through an attack catalogue that no longer exists; `MAX_STAGE_ROWS` is an unsafe ceiling; the viewport model is one HUD row out of date; nothing authors enemy *sprite slot* claims (`stage_enemies.asm`); there is no representation for the Dropper/P-token encounter, quiet zones, or the boss approach.

---

# Review 2 — the engine's level-data consumers

| subsystem | data source | exact symbols |
|---|---|---|
| terrain metatile map | **generated** | `src/terrain.asm:125` `* = $5800` → `#import "level1/stage_map.asm"` → `metatileDefs`, `stageMetatileRows`; guards at `:129`, `:132`, `:135` |
| terrain glyphs | **generated** | `src/terrain.asm:108` `* = TERRAIN_GLYPHS` ($0800 + 96·8 = **$0b00**) → `stage_charset.asm`'s `terrainGlyphs` |
| stage dimensions | **generated** | `STAGE_METATILE_ROWS` → `TERRAIN_STAGE_ROWS = STAGE_METATILE_ROWS * METATILE_H` (`terrain.asm:67`) |
| terrain colours | **generated** | `TERRAIN_BACKGROUND_COLOUR`, `TERRAIN_MC_COLOUR_1/2`, `TERRAIN_CHARACTER_COLOUR`, `TERRAIN_COLOUR_RAM` (uniform, written once, `terrain.asm:232`) |
| scrolling / row model | **engine** | `src/scroll.asm`: `STAGE_ROWS`, `STAGE_START_ROW = STAGE_ROWS - SCREEN_ROWS`, `stageTopRowLo/Hi`, `worldProgressLo/Hi`, invariant `stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS`. **1 pixel per frame, unconditionally** |
| turret placement | **generated** | `src/turrets.asm:35` `#import "level1/stage_turrets.asm"` → `TURRET_TOTAL`, `turretCols`, `turretRows`; `.fill TURRET_TOTAL` state arrays at `:237`–`:252`; guards `:178`–`:205` incl. `TURRET_TOTAL > 127` |
| turret behaviour | **engine** | `src/turrets.asm` (`TURRET_FIRE_INTERVAL`, aim/fire/paint/restore ticks) |
| enemy sprite slots | **hand-authored** | `src/level1/stage_enemies.asm`: `L1_SLOT_RING = 0`, `L1_SLOT_DROPPER = 4`. **Not generated by the editor** |
| wave definitions | **engine, hard-coded** | `src/waves.asm`: `defSweep/defSTurn/defLinger/defLoop`, `waveDefs`, `WAVEDEF_SIZE = 10` |
| flight paths | **engine, hard-coded** | `src/waves.asm` stage programs over `src/movement.asm` primitives (`WM_STRAIGHT/HOLD/ARC/ARC_MIRROR/EXIT`) |
| wave triggers | **engine, hard-coded** | `src/waves.asm:526–586`: `.var trigDelta`, `trigDef`, `trigSpecies`, `trigSide`, `trigFire`; `WAVE_TRIGGERS = 4`; emitted as `waveTrigDelta/Def/Species/Fire/Side` → `waveTrigEnd`, **5 bytes per trigger**. Deltas are in coarse rows and the list **wraps**, so the sequence repeats every Σdeltas (126 rows) |
| enemy firing | **engine + authored mask** | `trigFire` bit-per-member mask; `WAVE_FIRE_PERIOD` global cadence |
| P-token / Dropper encounter | **engine, via the wave table** | a trigger whose `trigSpecies == SPECIES_DROPPER` carries the Dropper; `trigSide` authors the drop side; `tkActive` in `src/token.asm` gates the encounter |
| stage end / boss approach | **derived** | `src/scroll.asm`: `STAGE_FINAL_VIEW_PROGRESS = STAGE_START_ROW`, sets `stageComplete`, freezes the scroller. `stageHold` is a test-only diagnostic |
| boss lifecycle | **engine** | `src/boss.asm`: `lvlPhase`, `ARENA_CLEAR_DEADLINE = 200`, `BOSS_HP_FULL`, `BOSS_X/Y`, victory pause, scripted exit |
| VIC bank | **engine** | `src/vicbank.asm` ($6980) + `frameBank` in the frame record (`renderer.asm:448`, committed at `:1266`); boss switches to bank 2 at a phase boundary |

---

# Review 3 — contract and mismatch table

## 3.1 Verified compatibility

Export of `levels/level1/level.json` → diff against `src/level1/`, comments stripped:

```
stage_config.asm   IDENTICAL
stage_charset.asm  IDENTICAL
stage_turrets.asm  IDENTICAL
stage_test.asm  vs  stage_map.asm   IDENTICAL
```

The project also matches the engine's numbers exactly: 105 metatile rows, 34 metatile defs, 72 glyphs, 8 turrets.

## 3.2 Mismatches

| # | datum | editor | generated | engine consumer | compatible? | constraint | risk | owner going forward |
|---|---|---|---|---|---|---|---|---|
| 1 | package location | `src/generated/<level>/` | — | `src/level1/` | ❌ **editor cannot load engine data at all** | — | blocks every round-trip feature | editor: 2 constants |
| 2 | stage map filename | `stage_test.asm` | ✓ | `stage_map.asm` | ❌ name only | — | export writes a file nothing imports | editor: 1 constant |
| 3 | **stage height ceiling** | `ENGINE_MAX_STAGE_ROWS = 768` | `STAGE_METATILE_ROWS` | `terrain.asm` `$5800`, guard `> $6000` | ❌ **5–7× over** | 2048 B total for defs **+** rows | authoring a long level fails the build; worse if the guard is ever relaxed | engine must move/enlarge the segment, then editor computes the bound |
| 4 | wave triggers | 53 authored | `stage_waves.asm` | **none** | ❌ **dead output** | — | 53 authored triggers silently discarded; engine runs 4 hard-coded ones | to be decided — §4 |
| 5 | attack catalogue | `ATTACK_COUNT = 12`, `attackIntervalData`, `attackSpriteStartData` | `waveTriggerAttackId/Interval/Sprite` | **none** | ❌ vocabulary gone | — | wave export resolves against a catalogue that no longer exists | editor must adopt the engine's archetypes |
| 6 | `SCROLL_FRAME_DIVIDER` | authored, default 2 | emitted | **none** | ❌ **dead constant** | — | duplicated truth: engine scrolls 1 px/frame | delete, or make the engine honour it |
| 7 | viewport rows | `VIEWPORT_ROWS = 23` | — | `SCREEN_ROWS = 25`, aperture ≈24 rows | ❌ off by 1–2 | — | trigger rows and the editor overlay sit ~2 rows out relative to what the player sees | editor |
| 8 | authored turret count | `MAX_AUTHORED_TURRETS = 255` | `TURRET_TOTAL` | guard `TURRET_TOTAL > 127` | ❌ editor over-permissive | ≤127 | a 128+ turret level fails the build late | editor |
| 9 | turret model | "pool of 8, streamed" | — | `.fill TURRET_TOTAL` state arrays | ❌ comment stale | 8 B/turret of state | none functional; misleading | editor comments |
| 10 | enemy sprite slots | — | — | `stage_enemies.asm` (hand-written) | ⚠️ **gap** | — | a second level needs this authored; editor cannot | editor should generate |
| 11 | glyph namespace | 128 (96..223) | `TERRAIN_GLYPH_COUNT` | guard vs `TURRET_GLYPH_BASE = 226` | ✅ safe (real ceiling 130) | ≤130 | none | either |
| 12 | charset address | comments say `$3B00` | address-free data | `$0b00` | ✅ data fine | — | comments only | editor comments |
| 13 | special encounter | — | — | `trigSpecies`/`trigSide` in `waves.asm` | ⚠️ **gap** | — | Dropper/P-token placement is not authorable | §5 |
| 14 | boss approach | — | — | derived from stage end | ⚠️ **gap** | — | no authored quiet zone | §5 |

## 3.3 Stage-length arithmetic — is the long-level representation engine-safe?

**Data widths are sound.** Every row counter that matters is 16-bit: `worldProgressLo/Hi`, `stageTopRowLo/Hi`, `pageTopRowLo/Hi`, `regenTopRowLo/Hi`; turret rows are exported and stored `Lo/Hi` (`turretRowLo/Hi`), and the wave exporter already splits `worldRow` into `waveTriggerRowLo/Hi`. `TERRAIN_STAGE_ROWS = 105 × 4 = 420` needs 16 bits and gets them. **No 8-bit boundary was found in the row path.**

**Capacity is not sound.** `src/terrain.asm:125` places the level map at `$5800` with `.if (terrainMapEnd > $6000)` — **2048 bytes for `metatileDefs` + `stageMetatileRows` together**:

| metatile defs | defs bytes | max metatile rows | max logical rows | ≈ seconds to boss |
|---|---|---|---|---|
| 16 | 256 | **179** | 716 | 114 s |
| **34 (level 1)** | 544 | **150** | 600 | 96 s |
| 64 (capacity) | 1,024 | **102** | 408 | 65 s |

Level 1 uses 1,594 of 2,048 bytes — **454 bytes spare, i.e. 45 more metatile rows**. The historical target of **400 metatile rows needs 4,000 bytes of rows alone**, roughly **twice the whole segment**.

The engine's guard is exact and will fail the build loudly, so this is a **capability limit, not a latent corruption** — provided nobody relaxes the guard without moving the segment.

**Where the space is.** `$6000-$63ff` is free (1,024 B) immediately above, which would raise the ceiling to ~252 rows with level 1's def table. For genuinely long stages the free run above the game-state code — **`$9cec-$bfff`, ~8.9 KB** — is the obvious home: at 10 B/row that is ~900 metatile rows, comfortably past the 400-row target, and it is outside VIC bank 0 so it costs no graphics capacity.

---

# 4 — Who should own enemy encounters?

## 4.1 Facts first

- The engine's encounter data **is already authored** — just in `src/waves.asm` rather than by the editor: 4 triggers × 5 bytes, delta-coded, and the list **wraps**, so level 1's encounters repeat every 126 coarse rows (~20 s) for the whole 63-second stage.
- The engine's *archetypes* are strong and reusable: 4 wave definitions (10 B each) plus 4 flight-path programs built from composable movement primitives. That vocabulary is worth keeping.
- The editor already models exactly the right shape — reusable **definitions** ("what") plus **triggers** anchored to `worldRow` ("when") — and already holds 33 definitions and 53 triggers for level 1. Only the *vocabulary* it resolves against is obsolete.
- Turrets are authored at **absolute world rows**; terrain is authored per row. Encounters that cannot also be placed at absolute rows can never be synchronised with either.

## 4.2 Consequences

| | **A — procedural** | **B — fully authored** | **C — hybrid** |
|---|---|---|---|
| deliberate pacing | ✗ cannot author a quiet stretch | ✓ total control | ✓ control over when/what |
| terrain & turret sync | ✗ impossible | ✓ | ✓ |
| quiet / intense sections | ✗ | ✓ | ✓ |
| replay variation | ✓ free | ✗ identical every run | ✓ bounded, inside authored constraints |
| special encounters | ✗ | ✓ | ✓ |
| boss approach | ✗ needs a special case anyway | ✓ | ✓ |
| data size | ~0 | large (paths + per-member data) | **~6 B/trigger** |
| runtime complexity | high (selection/pacing logic) | lowest | low |
| editor complexity | lowest | **high** (path authoring UI) | moderate — *already mostly built* |
| determinism/testing | poor | excellent | good |
| C64 maintainability | logic drift | data bloat | archetypes stay in asm, content in data |

**A** is ruled out by the game's own design: the level has authored terrain and authored turrets, and the boss approach needs a deliberate lull. **B** would require the editor to own flight paths, duplicating `movement.asm`'s primitives in Python — a large lift for capability the engine already expresses well.

## 4.3 Recommendation — **C, and concretely**

> **The editor authors WHEN and WHICH; the engine owns HOW.**

**Editor-authored, exported per trigger (absolute 16-bit `worldRow`, sorted descending):**

| field | width | meaning |
|---|---|---|
| `rowLo`/`rowHi` | 2 B | absolute world row the trigger fires on |
| `def` | 1 B | wave-definition index (the engine's archetype: sweep / S-turn / linger / loop) |
| `species` | 1 B | `SPECIES_RING` / `SPECIES_DROPPER` |
| `flags` | 1 B | fire mask (bits 0–3, per member) + drop side (bit 6) + reserved |
| `count` | 1 B *(optional)* | override the definition's member count |

**5–6 bytes per trigger.** Everything else stays in the engine: the flight-path programs, the member fan-out arithmetic, the enemy-fire opportunity cadence (`WAVE_FIRE_PERIOD`), the Dropper's choreography, the pool-pressure defer policy, and the wave-instance pool.

**What runtime may still vary, inside authored constraints:** nothing about timing or archetype. The variation the game already has — which *eligible* enemy gets the next fire opportunity (round-robin), pool-pressure deferral, Dropper ping cadence — is sufficient and is already bounded. Deliberately **no RNG** is introduced; the current engine has none, and determinism is worth more here than novelty.

This is a small delta from what the editor already does: replace `attackId → attack catalogue` with `def → the engine's wave definitions`, add `species`/`flags`, drop `sprite`, and switch the engine from delta-coded to absolute rows.

---

# 5 — Boss approach, quiet zones and special encounters

## 5.1 Where the behaviour belongs

Today: `stageComplete` fires at `worldProgress == 395`; `boss.asm` then waits for the arena to empty with `ARENA_CLEAR_DEADLINE = 200` frames as a backstop. Correct, but the boss can be gated by a cleanup timeout rather than by design.

**Under the recommended hybrid, the fix is one authored constant, not new logic:**

```asm
// stage_config.asm (generated)
.const STAGE_NO_SPAWN_ROW = <16-bit world row>   // last row that may start an encounter
```

- `waveTick` refuses to start a wave once `worldProgress >= STAGE_NO_SPAWN_ROW` — the same shape as the existing `lvlPhase` gate, ~6 cycles.
- With a well-authored margin (say 24–40 coarse rows ≈ 4–7 s), surviving enemies leave under their own egress and the arena is naturally empty when `stageComplete` fires. `ARENA_CLEAR_DEADLINE` reverts to being a backstop that normally never fires.
- The editor draws the no-spawn band on the map, so the author *sees* the boss approach.

Under **A** this would have to be a runtime "distance remaining" rule — which is the same constant, only invisible to the author. Under **B** it falls out of not authoring triggers there, but nothing enforces it. **The authored constant is the cheapest mechanism that is also visible in the tool**, and it does not conflict with any of the three architectures, which is why it is safe to adopt before the wave question is finally settled.

## 5.2 Special events

The game needs **a small closed set of event types, not a scripting language**. Two already exist implicitly and should become authored data:

| event | today | recommendation |
|---|---|---|
| Dropper / P-token encounter | `trigSpecies == SPECIES_DROPPER` + `trigSide` | fold into the trigger record (`species` + `flags`) — no separate event type needed |
| boss approach / no-spawn | none | `STAGE_NO_SPAWN_ROW` constant (§5.1) |
| quiet zone | none | falls out for free: simply author no triggers in that row range |
| turret-heavy section | authored turret rows | already authored; nothing to add |

That covers every case named in the brief with **one new constant and one widened trigger record**. A general event/script table should be deferred until something needs it that this cannot express.

---

# 6 — Memory and performance

| item | cost |
|---|---|
| trigger record | **6 B** (rowLo, rowHi, def, species, flags, count) |
| level 1 today | 4 triggers = 24 B (engine, 5 B each) |
| level 1 as authored in the editor | 53 triggers = **318 B** |
| worst case, 400-row stage | ~150 triggers = **900 B** |
| `STAGE_NO_SPAWN_ROW` | 2 B constant, 0 RAM |
| runtime RAM added | **0** — the cursor is the existing `wvNextTrig` + a 16-bit target; absolute rows *remove* the running-sum state deltas need |
| CPU, per frame | one 16-bit compare against the next trigger row, ~10 cycles — the same as today |
| CPU, no-spawn gate | ~6 cycles in `waveTick` |
| stage map, 400 metatile rows | 4,000 B rows + 544 B defs = **4,544 B** — does not fit `$5800-$5fff` (2,048 B); needs the segment moved (§3.3) |
| all of it | read-only, generated, outside VIC bank 0 — no bank-layout impact, no loader change |

Absolute 16-bit rows are *cheaper at runtime* than the current deltas, which must maintain a 16-bit running target (`wvNextAtLo/Hi`) across the wrap.

---

# 7 — Answers to the ten questions

1. **What the editor does:** terrain/metatile authoring with a repository, turret placement, wave definition+trigger authoring, validation, deterministic export.
2. **What it exports:** `stage_config`, `stage_charset`, `stage_test`, `stage_turrets`, `stage_waves` — into `src/generated/<level>/`.
3. **What the engine consumes:** the first four (as `src/level1/…`, with `stage_test`→`stage_map`), plus a hand-written `stage_enemies.asm`. Waves come from hard-coded tables in `src/waves.asm`.
4. **Mismatches:** §3.2 — 14 rows; the blocking ones are #1, #3, #4, #5.
5. **Is the long-level representation engine-safe?** Widths yes (16-bit throughout); **capacity no** — 150 metatile rows today, not 768.
6. **Editor-authored:** terrain, glyphs, colours, stage height, turret placement, encounter timing/archetype/species/flags, the no-spawn row, and (new) the enemy sprite-slot claim.
7. **Runtime-generated:** flight paths, member fan-out, fire-opportunity cadence, Dropper choreography, pool-pressure policy, boss lifecycle.
8. **Encounters:** hybrid — absolute-row triggers naming engine archetypes, 6 B each.
9. **Boss approach:** an authored `STAGE_NO_SPAWN_ROW`, enforced in `waveTick`; the existing deadline becomes a backstop.
10. **Implementation order:** §8.

---

# 8 — Roadmap

Each stage is independently reviewable and leaves the build green.

| # | stage | what | model |
|---|---|---|---|
| **1** | **Contract re-alignment (editor only)** | Point `engine_data` at `src/level1/`; rename `stage_test.asm` → `stage_map.asm`; delete or stop emitting `SCROLL_FRAME_DIVIDER`; set `MAX_AUTHORED_TURRETS = 127`; fix `VIEWPORT_ROWS`; refresh the stale `$3B00`/turret-pool comments. No engine change; prove by re-exporting level 1 and diffing byte-identically against `src/level1/`. | **Sonnet 5** |
| **2** | **Stage capacity (engine)** | Move the terrain map segment out of `$5800` to the free `$9cec-$bfff` run (or extend to `$6400` for a cheaper interim), update the guard, and re-derive the true ceiling. Then have the editor compute `MAX_STAGE_ROWS` from `(segment − defs·16) / 10` instead of hard-coding it. | **Opus 5 High** |
| **3** | **Enemy sprite-slot export** | Generate `stage_enemies.asm` from the project so a second level can declare its own species slots. | **Sonnet 5** |
| **4** | **Wave contract v2 (engine)** | Switch `waves.asm` from delta-coded to **absolute 16-bit** trigger rows; widen the record to `row, def, species, flags[, count]`; keep the existing definitions and flight programs untouched. Prove the current 4-trigger level behaves identically. | **Opus 5 High** |
| **5** | **Wave export v2 (editor)** | Re-point wave definitions at the engine's archetypes instead of the dead attack catalogue; emit the v2 record; migrate the 33 defs / 53 triggers already authored. | **Sonnet 5** |
| **6** | **Boss approach** | Add `STAGE_NO_SPAWN_ROW` to `stage_config.asm`, gate `waveTick`, draw the band in the editor. Prove the arena empties before `stageComplete` without the deadline firing. | **Opus 5 High** (engine gate) + **Sonnet 5** (editor band) |
| **7** | **Full-length authoring readiness** | Author a genuinely long level end-to-end; confirm capacity, trigger counts, boss approach and build guards. | **Sonnet 5**, escalating to Opus if capacity work resurfaces |

**Do stage 1 before anything else** — it is small, unblocks every round-trip feature, and until it lands the editor cannot even read the engine it is meant to target.

---

# 9 — Hygiene

No VICE was launched. No repository file was modified — `git status` is clean apart from this report. The single generated export went to `/tmp/lvlexp` and was deleted; the old editor remains extracted read-only at `/tmp/oldshooter`.

```
du -sh build/     96K
du -sh .          7.7M
```
