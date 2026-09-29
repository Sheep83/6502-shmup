# Correcting the enemy identity / trigger authoring model

**Date:** 2026-09-29
**Committed or pushed:** no. **No destructive git operation was used.**

---

## 1. Root cause

One line:

```python
# tools/level_editor/encounters_ui.py
self.t_species = ttk.Combobox(d, state="readonly", width=12,
                              values=sorted(C.SPECIES))     # <- three keys
```

`C.SPECIES` is the **engine's** three-entry map of species names to animation row
offsets (`RING: 0, DROPPER: 8, SQUARE: 16`). The trigger dropdown was wired
directly to it, so it could only ever show three entries no matter how much
artwork existed.

The deeper cause is the model the previous pass chose. I read a "species" as a
behaviour and made the roster a set of **costumes** for three legacy species —
and I said so at the time, flagging it as the one decision to confirm. It was the
wrong call for how you want to author: the roster is the enemy list, not a
wardrobe.

---

## 2. What the three legacy species actually controlled

Audited site by site before anything was changed:

| Property | Per species? | Evidence |
|---|---|---|
| artwork / animation row | **yes** | the row offset *is* the species value |
| health | no | `ENEMY_MAX_HP = 6`, commented "TYPE data: every enemy starts here" |
| collision box | no | no per-species box exists anywhere |
| score / value | no | none exists |
| firing behaviour | **no** | `enemyFireModeTab` held three entries, all `ENEMY_FIRE_DOWN` |
| spawn / movement | **Dropper only** | five sites |

**Ring and Square were behaviourally identical.** Every difference between them
was artwork. The only genuine behaviour is the Dropper's, in five places:

1. `enemy.asm` — drops the token on death;
2. `enemy.asm` — clears `tkDropperLive` when it leaves by any route;
3. `enemy.asm` — a role-check ordering shortcut;
4. `waves.asm` — the one-live-Dropper claim, and substituting an ordinary enemy
   when a second is refused;
5. `waves.asm` — flies `dropperLaunch` instead of its wave's path.

And `SPECIES_RING` appeared twice not as "a Ring" but as a synonym for **"an
ordinary enemy"** — the substitute for a refused Dropper, and the escort the
token encounter spawns. That literal is precisely what forced every new identity
to masquerade as a legacy species.

---

## 3. The model now

```
ENEMY IDENTITY   artwork + frame count + animation steps + behaviour
                 twelve of them, in tools/sprite_export/import_spd.py

LEVEL            holds THREE identities, in slot order
                 slot 0 -> species row 0, slot 1 -> row 8, slot 2 -> row 16

TRIGGER          names an IDENTITY; the exporter resolves it to this level's
                 slot. Still owns colour, colour mode, fire mask, fire mode,
                 placement and Dropper side -- unchanged.

WAVE DEFINITION  formation, movement, timing -- untouched.
```

The engine still has three enemy slots per level, as instructed. What changed is
that a slot no longer *is* one of three fixed species: it **holds** an identity,
and the identity carries its own artwork, frame count and behaviour.

### Behaviour moved to the identity

The five hardcoded tests became one-byte comparisons against package data:

```asm
    cmp #SPECIES_DROPPER      ->    cmp lvlDropRow
    lda #SPECIES_RING         ->    lda lvlPlainRow
```

Two new package bytes, both **species row offsets** so the comparison is the
same instruction at the same cost:

| | |
|---|---|
| `LEVELPKG_DROPROW` `$ffab` | the slot whose identity drops the token, or `$ff` for none |
| `LEVELPKG_PLAINROW` `$ffac` | a slot with ordinary behaviour — "an ordinary enemy" |

`$ff` can never equal a species value, so a level that carries no Dropper simply
has the whole mechanism lie dormant. `levelAssetsLoad` copies both bytes beside
the 24-byte animation table it already loaded.

---

## 4. Editor UX

* **Level scope** — the row is now `Level enemies:` with three comboboxes
  (`1:`, `2:`, `3:`), each offering the **full twelve-identity roster** with its
  frame cost, e.g. `Space Whisk  (6)`. Beside them, live:
  `Enemy sprite budget: 16 / 20`, appending `OVER BUDGET` past the limit.
* **Trigger scope** — the field is now labelled `enemy` and offers **this
  level's three identities by name**. Selecting "Space Whisk" says Space Whisk.
* **Swapping a level enemy rewrites its triggers.** Replacing the identity in
  slot 2 repoints every trigger that used slot 2, because a trigger naming an
  enemy the level no longer carries would be unexportable. The encounter window
  is told to re-offer its choices immediately.
* **The Dropper side field** now enables on `identity_behaviour(...) ==
  DROPPER`, not on the name `"DROPPER"`.

---

## 5. Migration

Deterministic, and it reads three generations without guessing:

| Project shape | Read as |
|---|---|
| `enemySlots: [...]` | the current list, in slot order |
| `enemyArt: {RING: ..., ...}` | the interim map the variable-frame pass wrote |
| neither | Ring 3, Dropper, Square — Ring 3 being the successor to the Sonic Ring artwork the SpritePad project retired |

A trigger naming a legacy species migrates to **whichever identity that level put
in that slot** — which is exactly what it was already drawing. Nothing changes on
screen; the trigger simply now says what it always meant.

`Trigger.species` now defaults to `RING_3` rather than `RING`, so a
directly-constructed trigger is valid.

The three level projects were migrated in place through the editor's own
`save()`:

```
level1  enemySlots ['RING_3','DROPPER','SQUARE']  triggers RING->RING_3
level2  enemySlots ['RING_3','DROPPER','SQUARE']  triggers RING->RING_3
level3  enemySlots ['RING_3','DROPPER','SQUARE']  no triggers
```

### Level 2's artwork restored

The previous pass put Spinner + Spinny Rotatey into Level 2 purely to demonstrate
5- and 6-frame sequences. That was my demonstration, not your level. Level 2 is
back to **Ring 3 + Dropper + Square**, matching its original Ring/Dropper/Square
intent, and the frame-count demonstrations live in test fixtures where they
belong.

### A mistake I made and corrected

My first migration pass wrote the projects with `to_json()` instead of the
editor's `save()`. `to_json()` serialises everything, so it **inlined the shared
movement vocabulary into all three level files** — 743 lines of programs that
belong to the shared library and must not be persisted per level. Caught by the
round-trip test, and fixed by re-saving through `EditorController.save()` with
the library attached. The diffs are now 5–17 lines each: `enemySlots` added and
the species renamed, nothing else.

---

## 6. The 20-slot budget

Unchanged in behaviour, now keyed on identities. One authoritative constant
(`LEVEL_SPRITE_BLOCKS = 20`, `src/main.asm`, imported by the tools). Three
independent gates:

1. **Editor** — `enemy_slot_cost(identities)`, shown live.
2. **Exporter** — `enemy_slot_problems()` raises `ExportRefused` before writing,
   and `_identity_slot()` refuses a trigger naming an enemy the level lacks.
3. **Package build** — `LVL_SPR_BLOCKS != sprBlocks`, plus a per-entry guard that
   no animation step names an unfilled block.

Boundaries, all proving, with editor and exporter agreeing:

```
8 + 6 + 4 = 18   accepted
8 + 6 + 6 = 20   accepted        exactly full
8 + 8 + 5 = 21   rejected
```

---

## 7. The roster now selectable

| Enemy | Identity | Source | Frames | Behaviour |
|---|---|---|---:|---|
| Dropper | `DROPPER` | `$1E–$21` | 4 | **token carrier** |
| Square | `SQUARE` | `$27–$2A` | 4 | plain |
| Modded Alleykat A | `ALLEYKAT_A` | `$34–$36` | 3 | plain |
| Modded Alleykat B | `ALLEYKAT_B` | `$3B–$3D` | 3 | plain |
| Ring 1 | `RING_1` | `$3E–$40` | 3 | plain |
| Ring 2 | `RING_2` | `$41–$43` | 3 | plain |
| Spinner | `SPINNER` | `$44–$49` | 6 | plain |
| Space Mine | `SPACE_MINE` | `$50–$52` | 3 | plain |
| Spinny Thing | `SPINNY` | `$54–$59` | 6 | plain |
| Space Whisk | `SPACE_WHISK` | `$5A–$5F` | 6 | plain |
| Ring 3 | `RING_3` | `$60–$67` | 8 | plain |
| Spinny Rotatey | `SPINNY_ROT` | `$68–$6C` | 5 | plain |

Still deliberately unavailable: `$0F`, `$15`, `$2B–$33`, `$37–$3A`, `$4A–$4F`,
and the player, muzzle, explosion, boss, bullet and power-up artwork.

---

## 8. Tests

### Sprite/package/data suite — `tools/sprite_export/test_spd_pipeline.py`

**93 passed, 0 failed.** Includes the fixtures this task asked for:

```
ok  a level using a 3-frame enemy packs 11 blocks and reaches every frame
ok  a level using a 4-frame enemy packs 11 blocks and reaches every frame
ok  a level using a 5-frame enemy packs 13 blocks and reaches every frame
ok  a level using a 6-frame enemy packs 14 blocks and reaches every frame
ok  a level using the 8-frame Ring 3 packs 16 blocks and reaches every frame
ok  two identities that were both 'Sonic Ring' resolve differently
       Ring 3 row [0,1,2,3,4,5,6,7] vs Space Whisk row [0,1,2,3,4,5,0,1]
ok  and their behaviours are identical, as the audit found
ok  only the Dropper identity carries the token-dropping behaviour
ok  8 + 6 + 4 = 18 is accepted        the editor agrees about 18
ok  8 + 6 + 6 = 20 is accepted        the editor agrees about 20
ok  8 + 8 + 5 = 21 is rejected        the editor agrees about 21
ok  every built level package matches the .spd and its own choice
ok  save and reload preserve the level's enemy identities
ok  the exporter refuses an over-budget level on its own
ok  exporting the same selection twice gives identical bytes
```

The "two identities that were both Sonic Ring" case is the one that would have
been impossible to state before: they are now distinguishable enemies with
different frame counts landing in different blocks.

### Editor suites

| Suite | Result |
|---|---|
| `test_v6_validation.py` | **PASS** |
| `test_wave_schema.py` | **PASS** |
| `test_v6_phase5b_encounters.py` | **PASS** |
| `test_encounter_library.py` | 48 passed, **1 pre-existing failure** |
| `test_v6_import.py` | **1 pre-existing failure** |

Both remaining failures predate this task and are unrelated to enemy identity:

* `test_encounter_library` asserts "Level 1 still has all nine triggers". Level 1
  has **twelve**, and had twelve at `HEAD` — verified with `git show`. A stale
  content assertion, like the "no Square encounter" one retired last task.
* `test_v6_import` fails on `worldProgress 350 is at or beyond noSpawnRow 340` in
  its own synthetic fixture — trigger row arithmetic, nothing to do with species.

Neither is in the Makefile's routine set. Left alone rather than turned into test
archaeology, as instructed.

### Build and smoke

`make build` succeeds; the package map shows `$ff93-$ffaa level anim table` and
`$ffab-$ffac level enemy behaviour`.

`make smoke` — **PASS**, every fatal counter zero.

### Export determinism

The exporter reproduces all three levels' `stage_enemies.asm` byte for byte from
the migrated projects.

---

## 9. Runtime proof

Read from a running emulator:

```
enemyAnimSeq, window base $b0
  RING     $b0 $b1 $b2 $b3 $b4 $b5 $b6 $b7   blocks 0..7    -> 8 distinct
  DROPPER  $b8 $b9 $ba $bb $bb $ba $b9 $b8   blocks 8..11   -> 4 distinct
  SQUARE   $bc $bd $be $bf $bf $be $bd $bc   blocks 12..15  -> 4 distinct

lvlDropRow  = $08 -> DROPPER slot      (the identity that carries the token)
lvlPlainRow = $00 -> RING slot         ("an ordinary enemy")
```

So the level's chosen identities resolve to the right compact graphics, and the
behaviour the Dropper used to own by hardcoded constant is now carried by the
package and loaded per level.

### Visible

Level 1 captured through `tests/harness.py` (exact PIDs, `-console`, no focus
stolen). Ring 3 draws at gameplay scale in the trigger's authored colours with
the rim highlight at different positions across enemies — the 8-frame rotation
running. No corruption, no pointer wrap, no cross-identity bleed, no scroll jank.

---

## 10. Limitations and deferred work

* **Three enemy slots per level**, unchanged as instructed. The roster is twelve;
  a level picks three.
* **Behaviour is still binary** — PLAIN or DROPPER. That is not a simplification
  I imposed: it is everything the audit found. HP, collision and score remain
  global, and this task deliberately did not invent per-identity versions.
* **Animation semantics untouched.** No LOOP/PINGPONG, no per-identity speed, no
  phase randomisation. Where a frame count does not divide eight the early frames
  still show twice per cycle.
* **The editor UI was not exercised on screen** — its Tk window would steal
  focus. The roster, the trigger dropdown, the budget, the slot-swap trigger
  repointing and the round-trip are proved through the code paths the UI calls.
  Worth one manual open, and that is the check that would confirm the acceptance
  criteria as you wrote them.
* **`import_engine_v6`** maps an engine species value back to the DEFAULT
  identity for that slot, because it reads encounter tables and not
  `stage_enemies.asm`. Re-importing a level whose slots hold non-default
  identities needs them set again in the editor. Documented in the file.

---

## 11. Files and status

**Engine** — `enemy.asm`, `waves.asm`, `token.asm`, `level_assets.asm`,
`level_package.asm`, `levelpkg.asm`.
**Levels** — `src/level{1,2,3}/stage_enemies.asm`, `stage_sprites.asm`.
**Projects** — `levels/level{1,2,3}/level.v6.json` (migrated).
**Tools** — `import_spd.py`, `contract_v2.py`, `project_v6.py`, `export_v6.py`,
`validation_v6.py`, `import_engine_v6.py`, `editor.py`, `encounters_ui.py`,
and five test suites.

**Untouched:** renderer, multiplexer, scroller, raster, collision, wave pacing,
firing cadence, projectile cap, enemy HP and speed, scroll speed, player and
power-up behaviour, trigger-owned colour and fire mode, and all artwork.

- **Nothing committed, nothing pushed.**
- **No `git checkout`, `restore`, `reset`, `stash` or `clean` was used.** Only
  `status`, `log`, `diff` and `show`, all read-only.
- VICE: every instance launched through the harness with its exact PID recorded
  and reaped; no `pkill`/`killall`; `pgrep -x x64sc` reports none remaining.
