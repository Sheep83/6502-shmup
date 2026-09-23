# Multi-level workflow audit — File → New / Open / Save / Export

Read-only audit of whether the existing editor and build already support a second
independent level. **Nothing was modified.** Findings are from tracing the code
and then exercising the real code paths; the two build attempts in §6 wrote only
to scratch, and the canonical Level 1 build was restored afterwards.

## Verdict

**Six of the seven steps already work. One is blocked, by a single missing file.**

| # | Want | Status |
|---|---|---|
| 1 | Level 1 stays untouched | ✅ Works |
| 2 | New Level creates an independent Level 2 | ✅ Works — but see §2, it copies the open level's tileset |
| 3 | Level 2 owns palette / glyphs / metatiles / map / turrets | ✅ Works, fully per-level |
| 4 | Save/Open Level 1 and Level 2 independently | ✅ Works |
| 5 | Use the PCB prototype as the basis | ✅ Works — it is already a valid v6 project; skip New Level entirely |
| 6 | Export Level 2 into its own source folder without touching Level 1 | ⚠️ **Blocked** — export omits `stage_enemies.asm`, so the folder will not assemble |
| 7 | Build/load that package as Level 2 | ⚠️ **Partially** — you can build a disk *whose only level is Level 2*; you cannot have both on one disk or choose at runtime |

The gap at step 6 is one file and one line of process. Step 7's limit is the
real multi-level architecture, which is not present and was explicitly out of
scope.

---

## 1. What each command actually does

### File → New Level… (`editor.py:1474`)

1. `_confirm_discard()` — offers to save if dirty.
2. Asks for a **level name** (`simpledialog`, default `"new_level"`).
3. Asks for **stage rows** (default/min/max from `contract_v2`).
4. Builds the document with `_seed_v6_project(name, rows)` (§2).
5. `_adopt_project(controller, None)` — **path is `None`**, so the document is
   unsaved and the first Save picks the default path.

No file is written and no directory is created. Nothing named `level1` is
touched.

### File → Open Level… (`editor.py:1489`)

* `initialdir` = `tools/level_editor/levels/` (falls back to the legacy
  `projects/` dir if `levels/` is missing).
* Filters: `level.v6.json`, then `*.json`, then all files.
* Loads through `EditorController.load(path)` → `migration_v6.load_any()`, so v6
  opens directly and v1–v5 migrate with notices shown in a dialog.
* `_adopt_project(controller, path)` replaces the **whole controller**, which is
  what guarantees no field of the previous document survives.

Completely generic. It will open any level package anywhere on disk.

### File → Save / Save As… (`editor.py:1547`, `1552`)

```python
def _default_level_path(self):
    return self.levels_dir / self.project.name / "level.v6.json"
```

* **Save** — if `project_path is None` (a new level), writes to
  `levels/<project.name>/level.v6.json`, creating the directory
  (`controller.save()` does `target.parent.mkdir(parents=True, exist_ok=True)`).
  Otherwise it rewrites the path it was opened from.
* **Save As** — `asksaveasfilename` with `initialdir` = that same default and
  `initialfile` = `level.v6.json`. You choose freely.

Both validate first and refuse to write on a validation error. The **whole**
document is written, including movement programs, wave definitions, triggers and
`noSpawnRow` that the terrain GUI cannot edit — open-and-save without an edit
reproduces the file byte for byte.

Level 1 is only ever written if `project.name == "level1"` and you Save an
unsaved document, or you deliberately Save As over it.

### File → Export level package… (`editor.py:1584`)

1. Validates; errors block and are listed.
2. `default_dir = self.repo_root / "src" / self.project.name` — **derived from
   the project's own name**, not hardcoded.
3. `askdirectory(...)` — **you choose the destination**; the default is only the
   dialog's starting point.
4. `self.controller.export(out, carry_enemies_from=out)`.
5. Success dialog lists what was written, plus one of two strings chosen by
   `if self.project.name == "level1"` — purely cosmetic (§4).

`controller.export()` re-validates, then calls
`export_v6.export_level(project, dest, level_name=project.name, ...)`, which
renders all six files **before writing any of them** and moves each into place
with `os.replace`, so a failure cannot leave a half-old, half-new package.

The six generated files are:

| File | Carries |
|---|---|
| `stage_config.asm` | stage rows, metatile count, **palette** (`$d021/$d022/$d023`, colour RAM), `TERRAIN_GLYPH_COUNT`, `noSpawnRow` |
| `stage_charset.asm` | the glyph bitmaps (`terrainGlyphs`/`terrainGlyphsEnd`) |
| `stage_map.asm` | metatile definitions **and** map rows (the Makefile splits it on four labels) |
| `stage_turrets.asm` | `TURRET_TOTAL`, `turretCols`, `turretRows` |
| `wave_programs.asm` | the movement pool |
| `wave_encounters.asm` | wave definitions and triggers |

---

## 2. What New Level actually creates

This is the question with the least obvious answer. From `_seed_v6_project`
(`editor.py:166`), whose own docstring says *"A new, empty v6 level that carries
the current graphics"*:

| Field | New Level gives you |
|---|---|
| `name` | what you typed |
| `stage` | your row count; `noSpawnRow` derived so it validates immediately |
| `palette` | **`DEFAULT_PALETTE`** — `bg 0, mc1 12, mc2 15, char 1`. *Not* the open level's palette |
| `glyphs` | **copied from the currently open document** |
| `metatile_defs` | **copied from the currently open document** |
| `level_metatile_set` | **copied**, via `json.loads(json.dumps(...))` |
| `map_rows` | blank — all metatile 0 |
| `turrets` | empty |
| `movement_programs` / `wave_definitions` / `triggers` | all empty |

So, precisely:

* **It does inherit graphics.** A New Level created while Level 1 is open starts
  with Level 1's 80 glyphs and 41 metatiles.
* **The inheritance is a deep copy, not a reference.** `[list(g) for g in ...]`
  for glyphs and defs, and a JSON round-trip for the native metatile set. There
  is **no aliasing** — editing the new level cannot reach back into Level 1's
  in-memory document, and Level 1 on disk is not written at all.
* **The palette is *not* inherited** — it resets to the default. So a New Level
  from Level 1 shows Level 1's artwork under a different, wrong palette until you
  set your own.

The copy is deliberate and documented: *"a level with no tiles to paint with
cannot be edited."* But it means **New Level is the wrong starting point for the
PCB prototype** — you would inherit 41 runway metatiles and then have to delete
them. See §5.

---

## 3. Is the per-level data really independent?

Yes. Everything in the list is per-level in both the v6 document and the
generated package:

* **Palette** — four fields in `project.palette`, emitted as
  `TERRAIN_BACKGROUND_COLOUR` / `TERRAIN_MC_COLOUR_1` / `TERRAIN_MC_COLOUR_2` /
  `TERRAIN_CHARACTER_COLOUR` in `stage_config.asm`.
* **Charset/glyphs** — `project.glyphs`, emitted whole into `stage_charset.asm`;
  `TERRAIN_GLYPH_COUNT` is level-owned.
* **Metatiles** — `metatileDefs` + the native `levelMetatileSet`;
  `STAGE_METATILE_COUNT` is level-owned (1..64).
* **Map** — `map`, emitted as `stageMetatileRows`; `STAGE_METATILE_ROWS` is
  level-owned.
* **Turrets** — `turrets`, emitted as `stage_turrets.asm`.
* **Encounters** — movement programs, wave definitions and triggers, emitted as
  the two `wave_*.asm` files.

The engine reaches all of this by **bare `#import` name** resolved through
KickAssembler's `-libdir`, which is exactly the mechanism `LEVELDIR` exploits.
`src/terrain.asm:109` imports `stage_charset.asm`, `src/turrets.asm:35` imports
`stage_turrets.asm`, `src/main.asm:81-82` imports `stage_config.asm` and
`stage_enemies.asm`. None of those names contains a level.

**There is no project-global graphics library.** Each level genuinely owns its
own charset, which matches the intended architecture.

---

## 4. Everything currently hardcoded to `level1`

| Location | What | Does it block a second level? |
|---|---|---|
| `controller_v6.py:70` | `CANONICAL_LEVEL = ("levels","level1","level.v6.json")` | **No.** Only the editor's startup document. |
| `editor.py:1613` | `if self.project.name == "level1"` picking one of two success strings | **No.** Cosmetic only. |
| `engine_data.py:93` | `LEVEL1_DIR_NAME = "level1"` | **No.** One consumer (`engine_data.py:337`), a legacy ASM-parsing path the editor no longer seeds from. |
| `export_level.py:28-29` | CLI defaults `--project levels/level1/...`, `--dest src/level1` | **No.** Both are overridable flags. |
| `Makefile:29` | `LEVELDIR ?= $(ROOT)/src/level1` | **No.** `?=` default; `proof420` already overrides it. |
| `Makefile:21` | `LEVELPRG := $(ROOT)/build/level1.prg` | **Only** if you want two packages on one disk. |
| `Makefile:172` | `c1541 "$(D64)" -write "$(LEVELPRG)" level1` | **Only** for two-on-one-disk. |
| `src/levelload.asm:160` | `.text "LEVEL1"` — the KERNAL filename | **Yes, for step 7.** One level per disk, loaded once at boot. |
| `src/level1/stage_enemies.asm:17-18` | defines `L1_SLOT_RING`, `L1_SLOT_DROPPER` | **Yes, awkwardly** — see below. |

### The `L1_` symbol leak

`stage_enemies.asm` is level-owned and hand-authored, but the **engine references
its symbols by their `L1_`-prefixed names**:

```
src/enemy.asm:109         .const ENEMY_SPRITES   = levelSlotAddr(L1_SLOT_RING)
src/enemy.asm:110         .const DROPPER_SPRITES = levelSlotAddr(L1_SLOT_DROPPER)
src/level_assets.asm:62   .byte L1_SLOT_RING, L1_SLOT_DROPPER     // LEVEL_PACKAGE_1
src/level_assets.asm:73-81 four assertions naming L1_SLOT_*
```

So a Level 2's `stage_enemies.asm` must **also define constants called
`L1_SLOT_RING` and `L1_SLOT_DROPPER`**, despite not being level 1. It works, but
it reads wrongly and will confuse the next person.

Related: `src/level_assets.asm:47-49` already has a `LEVEL_PACKAGE_1` /
`LEVEL_PACKAGE_B` / `LEVEL_PACKAGE_COUNT = 2` table. That is about **enemy sprite
window slot claims**, not terrain levels — `LEVEL_PACKAGE_B` is described in the
source as "the replacement proof". It is a useful precedent for per-level asset
descriptors but it is not a second level.

---

## 5. Using the PCB prototype as the basis for Level 2

**This already works, and does not need New Level at all.**

`tools/level_editor/levels/level2pcb/level.v6.json` is an ordinary formatVersion
6 project. Verified by running the real loader:

```
1. Open Level on level2pcb:  ok  name='level2pcb' migrated=False glyphs=128 metatiles=49
   palette: {'background': 5, 'multicolour1': 0, 'multicolour2': 15, 'character': 7}
3. Level 1 still opens:      ok  name='level1' rows=200
```

The recommended route is therefore **File → Open Level → `level2pcb/level.v6.json`**,
then **Save As** into `levels/level2/level.v6.json`. That gives an independent
Level 2 carrying the PCB palette, 128 glyphs, 49 metatiles and the 138-row map,
with no inheritance from Level 1 at all.

Using **New Level** instead would be strictly worse here: it would seed Level 1's
41 runway metatiles and the default grey palette, and you would then have to
delete all of them and re-import the PCB artwork.

One wart if you go the Save As route: **Save As does not change
`project.name`.** `_write_project` updates `self.project_path` but never the
name, and there is no GUI command to rename a level (the setter exists at
`controller_v6.py:119` but nothing calls it). So a project saved into
`levels/level2/` still reports `name='level2pcb'`, and Export's default directory
will still be `src/level2pcb`. Harmless — you pick the directory anyway — but the
generated header comments will say the wrong level name until the JSON's `"name"`
field is edited by hand.

---

## 6. The one real blocker: export omits `stage_enemies.asm`

`export_v6.export_level` ends:

```python
if carry_enemies_from is not None:
    src = Path(carry_enemies_from) / ENEMIES_NAME
    if src.exists():                      # <-- silently does nothing if absent
        ...copy...
```

and both callers pass **the destination itself** as `carry_enemies_from`
(`editor.py:1602`, `export_level.py:67`). The intent is "an existing level
directory keeps its hand-authored enemy file across a re-export" — which is
correct for Level 1 and for any *re*-export. But for a **new, empty** level
directory the source does not exist, the copy is skipped without comment, and you
get six files instead of seven.

Confirmed by exporting the PCB project into an empty directory exactly as the GUI
does:

```
2. Export into empty src/<level>/ dir, GUI-style:
      stage_charset.asm  stage_config.asm  stage_map.asm
      stage_turrets.asm  wave_encounters.asm  wave_programs.asm
   stage_enemies.asm present: False
```

and then building against it:

```
$ make build LEVELDIR=<that dir>
(src/main.asm 82:9) Error: Can't open file: stage_enemies.asm
(src/enemy.asm 109:42) Error: Unknown symbol 'L1_SLOT_RING'
(src/enemy.asm 110:42) Error: Unknown symbol 'L1_SLOT_DROPPER'
(src/level_assets.asm 62:11) Error: Unknown symbol 'L1_SLOT_RING'
… 11 errors
```

Copying one 1.1 KB file in and rebuilding:

```
$ cp src/level1/stage_enemies.asm <that dir>/
$ make build LEVELDIR=<that dir>
second build rc=0
```

**The whole blocker is that one file.** The export itself is otherwise correct and
complete, and it wrote nothing outside the chosen directory — Level 1 was
untouched throughout.

---

## 7. Building and loading it as Level 2

`make build LEVELDIR=<dir>` assembles the whole game against that level and is
already the supported mechanism — `proof420` uses it, and this audit used it
twice. `$(LEVELDIR)` is passed as the **first** `-libdir`, ahead of `src/`, so the
level's own files win name resolution.

What you get is a **complete disk image whose only level is Level 2**. What you
cannot currently do:

* **Have both levels on one disk.** `LEVELPRG` is fixed at `build/level1.prg` and
  the `c1541 -write` step names the disk entry `level1`.
* **Choose a level at runtime.** `src/levelload.asm` sets the KERNAL filename to
  the literal `"LEVEL1"` and runs exactly once at boot. There is no level index,
  no table of packages, no reload path. `stageComplete` (`src/scroll.asm:444`) is
  consumed by `src/boss.asm` and does not lead anywhere near loading another
  package.

So the `$e000` per-level package architecture *does* already give each level its
own independent package — that part is real, and it is what makes
`LEVELDIR` work. What is missing is the **selection** layer above it.

---

## 8. Smallest gaps, in order of cost

**G1 — `stage_enemies.asm` is not produced for a new level directory.**
*Blocks step 6.* Cheapest fix today: `cp src/level1/stage_enemies.asm src/level2/`
once, by hand. Cheapest code fix: when `carry_enemies_from` finds nothing, either
fall back to `src/level1/stage_enemies.asm` or have the Export dialog say
"this directory has no stage_enemies.asm; copy one from …?". Either is a few
lines and touches no engine code.

**G2 — the `L1_` prefix on level-owned enemy slot symbols.** *Cosmetic but
confusing.* Level 2's copy must define `L1_SLOT_RING`/`L1_SLOT_DROPPER`. A clean
fix renames them (e.g. `LVL_SLOT_RING`) in `stage_enemies.asm`, `src/enemy.asm`
and `src/level_assets.asm` — three files, no behaviour change, but it does touch
engine source.

**G3 — the package filename is fixed.** *Blocks two levels on one disk only.*
`Makefile:21,172` and `src/levelload.asm:160`. Not needed if you are content to
build one level at a time, which `LEVELDIR` already supports.

**G4 — no runtime level selection.** *This is the actual multi-level
architecture*, not a gap in the editor: a level index, a per-level filename, and
a reload path in `levelload.asm`. Explicitly out of scope.

**G5 — minor editor ergonomics.**
 * Save As does not update `project.name`, so Export's default directory and the
   generated header comments keep the old name.
 * There is no GUI command to rename a level, though the controller has the
   setter.
 * New Level always inherits the open document's tileset; there is no "start
   empty" option. Not a problem if you use Open + Save As (§5).

---

## 9. Recommended route with today's code

No code changes needed beyond one file copy:

1. **Open Level** → `tools/level_editor/levels/level2pcb/level.v6.json`
2. **Save As** → `tools/level_editor/levels/level2/level.v6.json`
   *(optionally edit `"name": "level2"` in the JSON so headers and defaults read right)*
3. **Export level package…** → `src/level2/`
4. `cp src/level1/stage_enemies.asm src/level2/` ← **the one manual step (G1)**
5. `make build LEVELDIR=$PWD/src/level2` → a disk whose level is the PCB stage
6. `make build` → restores canonical Level 1 into `build/`

Step 6 matters: `build/` holds whichever level was compiled last, so leaving it
on Level 2 would make the next `make run` and the entire test suite silently
exercise the wrong level.

Level 1 is not read or written at any point in steps 1–5 except for the one
`stage_enemies.asm` copy, which reads it.

---

## Process notes

No file in the repository was modified. The two `make build` invocations in §6
wrote only to `build/` and to session scratch; the canonical Level 1 build was
rebuilt afterwards and `build/` is back to the canonical artefacts. No VICE was
launched. Nothing was committed or pushed.

`git status` is unchanged from before this audit apart from this report:

```
?? reports/multi-level-workflow-audit.md
?? reports/level2-pcb-terrain-visual-prototype.md
?? reports/level2-pcb-terrain-visual-prototype/
?? tools/level_editor/gen_level2_pcb.py
?? tools/level_editor/levels/level2pcb-blue/
?? tools/level_editor/levels/level2pcb/
```
