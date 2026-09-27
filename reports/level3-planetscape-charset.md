# Level 3 — Planetscape Terrain Charset

**Date:** 2026-09-27
**Scope:** a barren-planet terrain tileset and metatile vocabulary for Level 3,
authored through the existing level editor pipeline and exported to `src/level3`.
**Engine changes:** none. **Level 1 / Level 2 changes:** none.
**Committed or pushed:** no.

---

## 1. What was built

A new terrain vocabulary for a bombarded, airless world: orange regolith under a
low north-west sun, cratered at three scales, with boulders, scattered grit and a
constructed turret platform. It is authored as two Python modules that drive the
existing v6 project format, and exported by the ordinary exporter — no new format,
no engine accommodation, no runtime composition.

### Files added

| File | Role |
|---|---|
| `tools/level_editor/level3_planetscape.py` | the drawing primitives: `crater`, `boulder`, `pebbles`, `crack`, `ridge`, `pit`, canvas/slice helpers, the deterministic PRNG |
| `tools/level_editor/gen_level3_planetscape.py` | builds the vocabulary, the palette and the showcase map; writes the v6 project |
| `tools/level_editor/levels/level3/level.v6.json` | the editable project, same shape as levels 1 and 2 |
| `src/level3/*.asm` | the exported package (8 files, listed in §7) |

### Files changed

None outside the above. `src/level1`, `src/level2` and their editor projects are
untouched; `git status` shows them clean.

One unrelated artefact was removed: `tools/level_editor/parallax-ram.bin`, a
65,538-byte VICE RAM dump left in the source tree by a monitor `save` earlier in
this session. Nothing references it and it is reproducible.

---

## 2. The pipeline, as discovered

The route a level takes is:

```
tools/level_editor/levels/<name>/level.v6.json     the editable project
        |  tools/level_editor/export_level.py --project ... --dest ...
        v
src/<name>/{stage_charset, stage_config, stage_map, stage_turrets,
            stage_enemies, stage_sprites, wave_encounters, wave_programs}.asm
        |  make LEVELDIR=$PWD/src/<name> build
        v
build/level1.prg  (the level package, written into build/shmup.d64)
```

`LEVELDIR` selects which level the game boots into; it defaults to `src/level1`.
Building with `LEVELDIR=$PWD/src/level3` puts Level 3 on the machine **without
extending the campaign** — `LEVEL2DIR` still supplies the second level, and the
campaign is still two levels long.

Two schema details were established against the real `levels/level1/level.v6.json`
rather than assumed, because `gen_level2_pcb.py` is out of date on both:

- the palette keys are `background`, `multicolour1`, `multicolour2`, `character`;
- `movementPrograms` / `waveDefinitions` as written there no longer exist.

`src/level3/stage_sprites.asm` is copied from `src/level1`. Levels 1 and 2 are
byte-identical in that file — it is an enemy-sprite **manifest**, not artwork — so
copying is the established pattern, and the copy carries a header saying so.

---

## 3. The palette, and why

```
$D021 = 8   ORANGE       the regolith. Medium, dominant, quiet.
$D022 = 15  LIGHT GREY   sunlit: west faces, crater rims, boulder caps.
$D023 = 9   BROWN        shade: east faces, inner walls, cast shadow.
cRAM  = 0   BLACK        the deepest shadow only.
```

In multicolour text mode pair `00` is `$D021`, `01` is `$D022`, `10` is `$D023`
and `11` comes from colour RAM's low three bits — so pair 3 can only be 0..7, and
of those black is the one that reads as a **hole** rather than as a stain.

Luminance runs black < brown < orange < light grey. That ordering is monotonic,
so the four tones stack into relief instead of fighting, and it is deliberately
the ramp `src/turrets.asm` draws its dome against: pair 1 lit, pair 2 shadow, pair
0 the background that must never touch the body's outline. Level 1 honours that
ramp and Level 2 inverts it, which is why the shared turret reads as metal on one
and as a mistake on the other. Level 3 honours it, and gets a correctly lit dome
for free.

Warm where it counts and grey where it counts: orange dust and brown shade make
it a planet; light grey keeps the lit edges reading as **rock** rather than as
more dust. No second hue exists for its own sake.

---

## 4. Lighting

One sun, low, to the north-west (`LIGHT_X, LIGHT_Y = -1.0, -0.45`). Every raised
thing catches light on its west face and throws shade east; every hollow does the
exact opposite. Nothing in the tileset departs from it.

A metatile is 16 native pixels across and 32 rows down, and a native multicolour
pixel is **twice as wide as it is tall**. Every round thing is therefore drawn
with `ry = 2 * rx`; drawn with equal radii it comes out an egg.

---

## 5. Budget

| | |
|---|---|
| glyphs | **125** of the packer's 128 (codes 96..220) |
| hard ceiling | 130 — `src/turrets.asm` fails the build if terrain reaches the turret namespace at code 226 |
| metatiles | **20** of 64 |
| map | 36 metatile rows x 10 cols = 144 world rows |

### Price list (marginal cost, measured by repacking without each piece)

| Piece | Metatiles | Marginal glyphs |
|---|---:|---:|
| `ground_plain` | 1 | 0 |
| `ground_grit_a` | 1 | 4 |
| `ground_grit_b` | 1 | 5 |
| `crater_small` | 1 | 13 |
| `crater_med` (2x2) | 4 | 28 |
| `crater_big` (3x3) | 9 | **48** |
| `rock_small` | 1 | 3 |
| `rock_med` | 1 | 6 |
| `turret_pad` | 1 | 10 |

The 3x3 crater costs 38% of the namespace on its own. It stays because the brief
asked specifically for genuine multi-metatile craters, and it is the one feature
on the surface with real scale. Dropping it would free 48 glyphs and buy every
accent primitive plus six more boulders — that is a decision about what the level
is for, not a budget accident, and the numbers above are what it would be made on.

Three economies were measured rather than guessed:

- **Crater rim wobble 0.07 → 0.035** freed 7 glyphs. Every cell a wobbly edge
  crosses is a glyph unique to that spot. Half the jitter still breaks the curve
  up at the size these are drawn, and the 7 glyphs bought `rock_med` and
  `ground_grit_b`.
- **Stripping the incidental debris welded into the two boulder tiles** freed 3.
  Same argument as the crater ejecta: scatter attached to a feature tile repeats
  wherever that feature is placed, where scatter in the grit tiles is the level
  designer's to put down.
- **Broad tonal bands instead of traced outlines.** A cell falling entirely
  inside one band is a single reused glyph; a cell crossed by a thin curve is
  unique. This is also the better-looking choice on a CRT, where a one-pixel
  traced curve reads as a scratch and shimmers when it scrolls.

The accent primitives (`crack`, `ridge`, `pit`) are written, tested and **unused**
— each costs about 5 glyphs and there is room for none of them at 125/128. They
remain in `level3_planetscape.py` to be traded in against the price list above.

---

## 6. The vocabulary

**Filler (2 + plain).** `ground_plain` costs zero glyphs and carries most of the
stage; quiet ground is what makes the craters read, and a surface textured
everywhere has no features, only noise. `ground_grit_a` and `ground_grit_b` are
two densities of scattered grit — two variants rather than one because a single
grit tile repeated down a scrolling column beats out a visible period.

**Craters (3 scales, 14 metatiles).**

| Piece | Layout | Canvas | Native size |
|---|---|---|---|
| `crater_small` | 1 metatile | 16 x 32 | rx 5.4 |
| `crater_med_{NW,NE,SW,SE}` | **2 x 2** | 32 x 64 | rx 10.5 |
| `crater_big_{NW,N,NE,W,C,E,SW,S,SE}` | **3 x 3** | 48 x 96 | rx 15.0 |

Both multi-metatile craters are drawn on **one canvas and then cut**
(`slice_metatiles`), so the seams between their pieces line up by construction
rather than by luck. The pieces are named for their compass position, which is
how they are identified and assembled in the editor.

**Boulders (2).** `rock_small` is a pebble-scale rock; `rock_med` is large enough
to read as an obstacle the ship flies over. Both are a lit west cap, a dark east
flank and a cast shadow hugging the base.

**Turret platform (1).** `turret_pad` — see §8, including a defect that is reported rather than fixed.

---

## 7. Export and build

`export_level.py --check` reports `level.v6.json: valid (9 warning(s))`. All nine
are `wavedef.unused`: default wave definitions named by no trigger, which is
expected for a terrain showcase that authors no encounters.

Exported, 8 files:

```
src/level3/stage_charset.asm    7996   125 glyph bitmaps at codes 96..220
src/level3/stage_config.asm     2147   geometry, palette, glyph count
src/level3/stage_map.asm        4849   metatileDefs + stageMetatileRows
src/level3/stage_turrets.asm     879   2 turrets
src/level3/stage_enemies.asm    1607
src/level3/stage_sprites.asm    2291   copied from level1 (manifest, not art)
src/level3/wave_encounters.asm  6100
src/level3/wave_programs.asm    3345
```

`stage_config.asm`:

```
STAGE_METATILE_ROWS      = 36      STAGE_METATILE_COUNT      = 20
STAGE_NO_SPAWN_ROW       = 94      TERRAIN_GLYPH_COUNT       = 125
TERRAIN_BACKGROUND_COLOUR = 8      TERRAIN_MC_COLOUR_1       = 15
TERRAIN_MC_COLOUR_2       = 9      TERRAIN_CHARACTER_COLOUR  = 0
```

`make LEVELDIR=$PWD/src/level3 build` **succeeds**, emitting the full package
layout through `$ff92-$ff92 level trigger count`.

Level 3 is reachable only through that explicit `LEVELDIR`. The default build is
unchanged and still boots Level 1; nothing about the campaign was touched.

### Editor validation

The editor is a Tk GUI with no CLI entry point, and launching it would map a
window and steal keyboard focus, which the hygiene rules forbid. Instead the
editor's own loader was driven directly:

```
level1  loads OK  metatiles=41 glyphs= 80 rows=200 turrets=5 palette=(12,15,11,1)
level2  loads OK  metatiles=49 glyphs=128 rows=138 turrets=0 palette=(5,0,15,7)
level3  loads OK  metatiles=20 glyphs=125 rows= 36 turrets=2 palette=(8,15,9,0)
```

Level 3 loads through `EditorController.load` exactly as levels 1 and 2 do, and
levels 1 and 2 still load unchanged. In the editor each piece is identified by
its name: `ground_plain`, `ground_grit_a`, `ground_grit_b`, `crater_small`,
`crater_med_NW/NE/SW/SE`, `crater_big_NW/N/NE/W/C/E/SW/S/SE`, `rock_small`,
`rock_med`, `turret_pad`.

---

## 8. The turret platform

`src/turrets.asm` writes its four body glyphs at `metatileRow*4+1`,
`metatileCol*4+1` — the middle four character cells, native pixels x 4..11,
y 8..23. **That box belongs to the turret, not to this artwork**: anything drawn
there is overwritten the moment a turret is placed. All of the pad's construction
therefore lives in the outer ring, and the deck under the turret is left flat so
an empty pad still looks deliberate. The four bolt heads sit at y 6 and y 25,
clear of the box whatever their column.

The showcase places two turrets, and the exporter resolves them to character
`col 9, row 65` and `col 21, row 129` — exactly `(metatile 2, 16) * 4 + 1` and
`(metatile 5, 32) * 4 + 1`, the seats of the pads at map rows 16 and 32. The
third pad is left empty so the platform can be judged both occupied and bare.

**One turret per metatile row is a hard exporter rule**, not a style choice:
`turretAtMetaRow` holds a single index per row and the exporter refuses a second
with `turret.duplicate_row` (contract v2 temporary limit). The showcase puts two
pads on row 16, so only one of those can ever be occupied.

### The authored turrets do not render — unresolved, and out of scope

This is a real finding and it is **not fixed**. Both pads render as correctly
constructed slabs but permanently bare, at every scroll depth, in every capture.

What was ruled out, with evidence rather than reasoning:

- **"The player shot it."** Refuted twice. `turretAlive[0]` reads 1 at every
  sample across the whole stage, and the score increases by exactly 150 every
  120 frames at all five samples — it is distance scoring, not kills.
- **"The authored coordinates are wrong."** The engine's own tables, read out of
  a running machine, are all correct: `turretCount = 1`, `turretMetaRow[0] = 16`,
  `turretCol[0] = 9`, and `turretAtMetaRow` non-empty at exactly one row, 16.
- **"It is that particular row."** A second turret was authored at metatile row
  32 and the level rebuilt. Neither turret appears.

What is actually observed: `turretVisible` stays 0 at every sample, and no turret
is drawn anywhere in any of the fourteen frame-accurate captures spanning the
whole stage, including frames where a pad sits fully inside the aperture at both
authored rows.

Going further means reading `turretWorldTick`'s scan and the overlay path — engine
work, on a mature engine, in a task whose brief says *"do not improve it while
drawing rocks."* So it is reported here and left alone. It does not affect the
terrain charset, which is what this task delivers, and Level 1's five turrets are
untouched and unaffected.

---

## 9. Defects found by inspection, and fixed

Every one of these was found by rendering the **exported** assembler back out —
reading `stage_charset.asm`, `metatileDefs` and `stageMetatileRows` and composing
the image the VIC would fetch — not from the generator's intent.

**1. The craters read as mounds, not holes.** The floor tone was `DRK`, the same
tone as the shaded inner wall, so the two merged into one undifferentiated dark
mass with no boundary; with the sunward rim lit across the whole north cap, the
top half read as a bright mound. Fixed by re-banding so consecutive bands always
step in tone. West to east across a crater the eye now crosses five real steps:

```
ground | LIT rim | DEEP wall | DRK floor | MED floor | LIT wall | DRK rim | ground
         raised    in its      shadow      open to     the sun-   raised,
         sunward   own rim's   the west    the sun     facing     facing
                   shadow      rim casts               crescent   away
```

That is also the physics of a low sun: the lip on the sun side shades its own
inner wall and throws a crescent of shadow across the near floor, while the *far*
inner wall is the brightest thing in the feature.

**2. The craters read as washers.** The lit rim arc spanned `facing > -0.12` —
194 degrees, over half the circumference — so the lit **outer** rim on the near
side ran round the poles and joined the lit **inner** wall on the far side,
closing the grey into an unbroken annulus. A complete bright ring is a torus
lying on the ground. Tightened to `+/-0.15` on both arcs: each lit arc is now
about 160 degrees, and between them sit two wedges, at the north-east and
south-west, where the light merely grazes and both bands go dark. Those two breaks
are what stop the ring closing.

**3. The turret pad read as an empty picture frame.** Its deck was filled with
`MED` — the regolith tone — and only a lip was drawn, so there was no tonal
difference between the platform and the dirt it sat on. Redrawn as a slab: a
`DRK` deck, a `LIT` lip along the sunward north-west edges, and a `DEEP` cast
shadow thrown onto the regolith to the south and east. Then the bolt heads, first
placed at y 5, had their lit crowns touching the lit lip above them and merged,
leaving only their shadows — they read as notches chopped out of the rim. Moved
to y 6, one pixel of deck between.

**4. The filler read as a repeated stamp.** Every pebble was the same `LIT` pixel
with a `DRK` one east of it — and since a native pixel is twice as wide as it is
tall, that mark is four screen pixels wide and one tall: a **dash**. Clusters of
identical dashes formed the streaky diagonal texture. The lighting was never
wrong; the silhouette was. Grit now has three shapes — a dark speck, a lit crown
with its shadow, and a two-row-tall rock.

**5. The showcase was unreadable as a showcase.** The first layout left a screen
of empty ground around every feature — the right instinct for a playable stage,
the wrong one for a display case. At game scale it was four small rings adrift in
an orange field and answered none of the questions the art has to answer.
Rebuilt to put the awkward cases next to each other: the same 2x2 crater twice on
one screen, the two filler variants side by side, the small boulder against the
medium, an occupied pad and an empty one. Repetition, seams and stamping only
show up when things repeat.

### One instrument was wrong before the artwork was

The first PNG preview used **red's** RGB for colour 8 and a bogus value for
colour 9, making orange and brown near-identical in luminance and the whole
surface look like mud. The correct Pepto values are 8 = (111,79,37) and
9 = (67,57,0), which are well separated. The palette was never the problem; the
preview was. Nothing was changed on the strength of that render.

---

## 10. What the machine shows

Captured with `x64sc -console -exitscreenshot`, launched through `tests/harness.py`
so PID ownership, the no-window rule and the port-squatter refusal all come from
the one place that owns them. Six scroll depths, `boot="exact"`, warp.

- **Craters read as depressions at game scale**, at all three sizes. The 2x2 and
  the 3x3 are unambiguous: lit rim crescent, dark interior, lit far wall.
- **Continuity across the multi-metatile pieces is clean.** No seam is visible at
  any join of either the 2x2 or the 3x3 — expected, since both are cut from one
  canvas, and confirmed on the exported data and on the machine.
- **Light direction is consistent.** Every crater, boulder and pad edge is lit
  from the same north-west sun.
- **No 4x4 metatile boundaries are visible.** The grid does not show.
- **Filler does not read as a repeated pattern** after the grit fix.
- **Contrast against sprites is strong.** The player ship — white and light blue —
  separates cleanly from orange regolith and grey rims at every scroll depth.
- **The turret platform reads as constructed**: a dark machined deck, a bright
  north-west lip, a black cast shadow to the south-east, and four legible bolt
  heads. Judged **bare only** — see §8: the authored turrets never render, so the
  occupied case could not be assessed.

### First sampling attempt was invalid

The first capture pass used `soak_frames`, which guarantees only a **minimum**.
It overshot every target — 420 requested, 4009 measured; 680 requested, 4463 —
so all six stills landed at essentially the same place, past the end of the
36-row map where the engine holds the last row and the screen is plain ground.
Re-captured with `run_frames`, which breaks on `gameFrame` and advances an exactly
verified count.

### What still needs your eye

- **Scrolling shimmer cannot be judged from stills.** The dithering is
  deliberately sparse and the bands are broad, which is the shape of the problem
  that avoids it, but only a long non-warp run on the MiSTer/CRT settles it.
- **Aesthetic approval of the palette** — orange/grey/brown against Level 1 and
  Level 2 — is a judgement call, not a measurement.
- **The small crater repeated in a row** (showcase row 30 places five in a line)
  does read as stamped. That is a map-authoring caution, not a tileset defect;
  the showcase does it on purpose to expose the limit.
- **The showcase is 36 metatile rows**, far shorter than a real stage. Once
  scrolled past, the engine holds the last row — plain ground. Expected.

---

## 10a. Routine regression

This work touched build and package tooling, so `make smoke` was run once after
it was stable. **PASS**, on the ordinary campaign build (default `LEVELDIR`, i.e.
Level 1 into Level 2 — Level 3 is not in the campaign):

```
BOOT: PASS   reached ATTRACT in 14s, frame 4933
CAMPAIGN LOOP: PASS
  ATTRACT -> PLAYING      ok        PLAYING -> LEVELDONE   ok  (the upgrade shop)
  CONTINUE advances       ok        level 2 package loaded ok  noSpawnRow 725 -> 352
  level 2 -> PLAYING      ok        PLAYING -> GAME OVER   ok
  returns to the front    ok
Frames observed: 4031
  gameOverrun 0   scrollLate 0   edgeLate 0   statOverflow 0   statPageMismatch 0
  statPtrMismatch 0   objDoubleFree 0   objAllocFail 0   clipPoolFull 0
  publishSkip 0   schedBuildDefer 0   statLate 0
ENGINE HEALTH: PASS
ROUTINE REGRESSION: PASS
```

Every fatal counter is zero, and `publishSkip` — which is a budget rather than a
zero-or-fail invariant — came in at 0 against a budget of 5 per ~3000 frames.
Note that smoke rebuilds with the default `LEVELDIR`, so `build/` is left holding
the ordinary Level 1 campaign binary, not the Level 3 one.

The many-hour certification suite was **not** run, per the brief.

---

## 11. Hygiene

- Every VICE launch was made through `tests/harness.py`, which records its exact
  PID, refuses to attach to a port it did not open, and terminates only
  `self.proc`. No `pkill` or `killall` was used at any point. Audited: the
  harness contains no broad kill and no atexit sweep.
- Twenty VICE instances were launched across this task, every one through the
  harness and every one reaped: `69466, 69523, 69597, 69626, 69657, 69683,
  69717, 69739, 69869, 69932, 69955, 69993, 70046, 70171, 70863, 71103, 71136,
  71156, 71480, 71506` for the captures and probes, and `71608` for smoke.
  `pgrep -x x64sc` reports none remaining.
- One wait-loop of mine printed a misleading leftover by running `pgrep -fl
  x64sc`, which matched the shell whose own command line contained the string.
  Leftover checks use `pgrep -x` for that reason.
- A **user-launched** `x64sc -nativemonitor` (PID 68890) was running at the start
  and was never touched; it disappeared between two checks, and nothing run here
  is capable of having ended it.
- All captures, previews and scratch scripts are in the session scratchpad, not
  in the repository and not in `/tmp`.
- `build/` holds only the current binary and symbols (404K). No per-run
  directories. This task's captures and previews peaked at ~200K in the
  session scratchpad and were all deleted afterwards; the 1.1M still there
  belongs to earlier tasks in this session. The repository gained 88K
  (`src/level3` 44K, `levels/level3` 44K) plus this report.
- The 64K `parallax-ram.bin` left in the source tree earlier in this session was
  removed.

---

## 12. Status

- **Nothing committed, nothing pushed.** The working tree carries only untracked
  additions: `src/level3/`, `tools/level_editor/gen_level3_planetscape.py`,
  `tools/level_editor/level3_planetscape.py`, `tools/level_editor/levels/level3/`
  and `reports/level3-planetscape-charset.md`.
- `src/level1`, `src/level2` and their editor projects are clean.
- The campaign is unchanged and still two levels long.
