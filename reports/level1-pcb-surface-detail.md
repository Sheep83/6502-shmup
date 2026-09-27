# Level 2 — PCB surface-detail pass

**Date:** 2026-09-27
**Scope:** sparse surface detail to break up the flat solder-mask areas of the
green PCB stage. Art/content only.
**Engine changes:** none. **Level 1 / Level 3 changes:** none.
**Committed or pushed:** no.

> **A note on the filename.** The brief was issued as "Level 1 PCB surface-detail
> pass" and asks for the report at `/reports/level1-pcb-surface-detail.md`, so
> that is where it is. The green PCB board with the components is **Level 2**;
> Level 1 is the grey/white stage (`$d021/$d022/$d023 = 12/15/11`). The user
> confirmed Level 2 was meant. All work below is on Level 2 and Level 1 was not
> touched.

---

## 1. What was inspected

| Thing | Where | What it said |
|---|---|---|
| stage geometry & palette | `src/level2/stage_config.asm` | 138 metatile rows, 49 metatiles, 128 glyphs |
| the tileset | `src/level2/stage_charset.asm` | 128 glyph bitmaps at codes 96..223 |
| the map | `src/level2/stage_map.asm` | `metatileDefs` + `stageMetatileRows` |
| the authored project | `tools/level_editor/levels/level2/level.v6.json` | the canonical, editor-authored source |
| the original generator | `tools/level_editor/gen_level2_pcb.py` | its palette reasoning, its DSL, and its own ownership warning |
| the namespace limit | `tools/level_editor/engine_data.py` | `TERRAIN_GLYPH_NAMESPACE = 128` |

### The flat-green problem, quantified

`BOARD` — the genuinely empty green metatile — is **807 of the map's 1380 cells,
58% of the board**. That is the flat field the brief is about, and it is not an
impression: it is most of the stage.

---

## 2. Constraints found, and the one that decided the design

### The palette already contains the gold

```
$D021 = 5   GREEN        bare solder mask   measured out of x64sc as (98,213,50)
$D022 = 0   BLACK        IC bodies, drill holes
$D023 = 15  LIGHT GREY   traces, solder, silkscreen   (205,205,205)
cRAM  = 7   YELLOW       pads, vias, test points      (255,255,70)
```

Terrain colour RAM is written once at init and never again, so the level has
exactly four colours for its whole surface. Character colour is restricted to
0..7 by the engine and yellow is 7 — so **the gold the brief asked for is
already reachable and no palette change was needed or made.**

### The glyph budget looked full and was not

`TERRAIN_GLYPH_NAMESPACE` is **128** and it is structural: terrain owns character
codes 96..223, exactly half the charset, and the exporter additionally requires
the count to be a multiple of eight. Level 2 emits 128 glyphs, which reads as
completely full.

It is not. Only **121 are referenced by any metatile**. Codes **217..223 are
seven byte-identical copies of the blank glyph**, emitted purely as padding to
reach the multiple of eight. So there were exactly **seven free glyph slots, and
they could be taken without touching one pixel of existing artwork**. That is the
entire budget for this task, and it is what the design was cut to fit.

Seven is enough because of how the packer works: a mark that fits inside **one
character cell** costs **one glyph**, however many times it is used, at any cell
position, in any metatile. Seven marks therefore stretch across eight variants.

### Metatiles were not the constraint

49 of 64 used, so 15 free. Eight were taken.

---

## 3. Where the work had to go, and why not the generator

`gen_level2_pcb.py` says of itself, in its own footer:

> *"THIS SCRIPT IS NO LONGER THE SOURCE OF TRUTH. levels/level2/ was promoted to
> the real Level 2 and is authored in the editor now, so regenerating over it
> would discard every edit made since."*

It also refuses to write to the authoritative path without `--force`. And it is,
as of now, **simply broken**: it raises `KeyError: 'movementPrograms'`, a key the
v6 schema no longer carries, so it cannot produce a project at all. Regeneration
was therefore not merely discouraged but impossible.

So the work follows the pattern of `author_level1_five_enemy.py`: a one-shot
**author-time** script that edits the canonical project and carries everything
else through untouched.

**Added:** `tools/level_editor/author_level2_surface_detail.py`
**Changed:** `tools/level_editor/levels/level2/level.v6.json`, and the exported
`src/level2/stage_charset.asm`, `stage_config.asm`, `stage_map.asm`.

Generation stays deterministic: the placement uses an explicit LCG with a fixed
seed rather than `random`, so it is reproducible across Python versions, and the
script refuses to run twice over its own output.

---

## 4. The vocabulary added

### Seven marks — the whole glyph cost

| Mark | Pixels | Tone | Reads as |
|---|---|---|---|
| `dot` | 1 x 2 | gold | a square fleck of exposed copper |
| `fine` | 1 x 1 | gold | the faintest possible grain |
| `grain` | 3, irregular | gold | a small solder crumb |
| `pair` | 2, far apart | gold | two separate specks in one cell |
| `splash` | 1 x 2 | light grey | solder / silkscreen splash |
| `nick` | 1 x 1 | black | a nick through the mask — battle wear |
| `scratch` | 3, stepped | light grey | a short scuff |

**Scale is set by the pixel, not by taste.** A multicolour pixel is two screen
pixels wide and one tall, so `1 x 1` native is a 2 x 1 screen grain and `1 x 2`
is a 2 x 2 square dot. Nothing here exceeds three native pixels. A trace is 2
native px wide and runs the full height of a tile, so these cannot compete with
the artwork — which is the point.

**Why gold is the default.** On this board gold is exposed metal: pads, vias,
test points. A fleck of it reads as stray copper or a stray blob of solder, which
is what a real board has. Grey and black appear once each and no more — grey
matches the existing `BOARD_SPECK` silkscreen idiom, and black is the only tone
that can read as a hole rather than a mark.

**Why they do not read as vias.** A via on this board is a gold ring with a
**black centre**. Every mark here is flat solid colour with no centre. Confirmed
side by side on hardware at 3x: they are plainly different objects.

### Eight mostly-blank variants

`BOARD_GRAIN_A`..`F`, `BOARD_NICK`, `BOARD_SCUFF`. Each carries two or three
marks placed in two or three of its sixteen character cells; the other thirteen
or fourteen cells are plain board. Cell positions are scattered rather than
centred so that a variant repeated elsewhere does not show its own grid.

---

## 5. Two things that were measured rather than guessed

### Density: the first attempt was too sparse, and a screenshot proved it

The first cut gave each variant a **single** mark and placed a variant in 10% of
BOARD cells — 72 tiles. A before/after of the same VICE frame differed by
**106 pixels out of 69,120 (0.15%)**, and the board still read as a flat green
field. The acceptance question is whether the flat field is broken up, and at
that density it plainly was not.

The fix was the cheap axis: **more marks per variant, not more marked tiles.**
A mark is one character cell, so reusing the same seven bitmaps at further cells
costs nothing at all, and spreading the marks more thickly over the same number
of tiles leaves far more tiles completely plain than simply marking more tiles
would. Variants went to 2–3 marks and the rate to 16%.

Final density, measured over the whole stage rather than from one frame:

| Per 6-row screen (60 metatiles) | min | median | max |
|---|---:|---:|---:|
| marked tiles | 1 | **4** | 10 |
| mark pixels | 3 | **14** | 33 |

No screen is entirely without a mark, and the median screen carries four marked
tiles out of sixty — so 56 of 60 metatiles on a typical screen are still
completely plain board.

**A caution about how this was nearly mis-measured.** The frame first used for
the A/B happened to sit near the stage *minimum* (3 mark pixels). Judging the
result from it alone would have said the change had made things worse. The
density table above, computed from the project data across all 132 screen
positions, is the honest measure; single frames are samples, not verdicts.

### The black nick was too frequent at first

Variants were initially chosen uniformly, which gave the two darkest of the eight
about an eighth of placements each — roughly nine apiece. Black against this
green is the highest contrast on the board, and at that frequency they read as
specks of **dirt**, not wear. Selection is now weighted (gold 17/21, grey 3/21,
black 1/21) and the nick was cut from two pixels to one, so it lands three or
four times in the whole stage. That is what "a very small number of battle scars"
has to mean on a surface this size.

---

## 6. Placement

Scattered over `BOARD` cells only, by seeded LCG, with one rule: a candidate is
rejected if **any of its eight neighbours** already carries a mark. That keeps the
marks isolated specks rather than clumps or lines, and it is what prevents the
regular spacing and the diagonals the brief warns about. Everything not chosen
stays `BOARD`, which is what keeps the calm areas calm.

Placed across the whole stage rather than in one showcase band — there is no
sample-catalogue row, and no region was laid out to display the variants.

---

## 7. Nothing existing was altered — verified, not asserted

Checked against `git show HEAD:` rather than against a working copy:

```
charset bytes          HEAD 1024   now 1024      (package size unchanged)
glyph codes changed    [217, 218, 219, 220, 221, 222, 223]   <- the blank padding
existing artwork (codes 96..216) byte-identical       True
metatiles              HEAD 49     now 57
existing 49 metatile defs identical                   True
map cells changed      103 of 1380
every change BOARD(0) -> new variant(>=49)            True
no existing non-BOARD cell touched                    True
```

The charset is the **same 1024 bytes** it was: the seven new glyphs went into
slots that previously held blank padding, so the level package did not grow and
no package constraint moved.

---

## 8. Validation

### Build

`make LEVELDIR=$PWD/src/level2 build` succeeds. Glyph count stays 128, metatiles
49 -> 57 of 64.

### VICE

Captured with `x64sc -console -exitscreenshot` through `tests/harness.py`, so PID
ownership and the no-window rule come from the one place that owns them.
Frame-accurate stepping (`run_frames`), four points across the stage, plus a
baseline capture of the unmodified level for direct comparison.

Against the acceptance question — *does the PCB still read as a clean PCB, but no
longer as a large perfectly flat green field?* — **yes, on both halves.**

- The green fields now carry an occasional gold speck and read as a *surface*.
- Traces, vias, DIPs, the mount hole, the silkscreen and the edge fingers all
  remain unambiguously dominant; nothing new competes with them.
- The marks do not read as vias: vias are gold rings with black centres, these
  are flat and tiny.
- Sprite readability is unaffected — pink enemies and the white ship separate
  cleanly from the board at every capture.
- Repetition is not conspicuous: eight variants at three or four marks each,
  scattered with a no-adjacent-neighbour rule, show no grid and no diagonals.

### Projectile readability — checked, because it was a real risk

`src/ebullet.asm` draws the enemy bolt with a **yellow body and a white core**
inside a dark edge, so "small gold mark" and "projectile" are in principle
confusable. They are not in practice: the bolt is a seven-row sprite with a white
core and a dark outline, roughly 14 x 7 screen pixels, while the largest mark
here is three native pixels of flat gold. Different size, different structure,
and the marks scroll with the board while bolts move independently. Worth the
user's eye on the CRT all the same — it is the one place this change touches
gameplay legibility at all.

### Routine regression

`make smoke` — see §11 for the result. It was warranted because this change
alters Level 2's **package data** (charset, metatile defs, map), and Level 2 is
in the campaign the smoke runner plays through.

The full certification suite was **not** run, per the brief.

### What still needs the user's eye

- **The CRT is the final authority**, and the emulator window is magnified. The
  marks were deliberately tuned on the 1x render and the unscaled VICE frame,
  not on the zoomed view.
- **Motion.** Stills cannot answer whether the specks shimmer as the stage
  scrolls. The relevant physics is on record in `gen_level2_pcb.py`: the stage
  scrolls one pixel per frame, so any pattern that *repeats down the screen*
  alternates at a fixed screen point and flickers — which is why that file
  rejected every substrate dither it tried. Isolated specks are not a repeating
  pattern and should not behave that way, but only a long non-warp run settles it.
- **Whether 14 mark pixels per screen is the right amount.** It is a judgement
  call, and it is now a single number in one place: `rate` in
  `author_level2_surface_detail.py`, plus the per-variant mark lists.

---

## 9. Unrelated observations, deliberately left untouched

1. **`gen_level2_pcb.py` is broken.** It raises `KeyError: 'movementPrograms'`
   because the v6 schema dropped that key (and `waveDefinitions`). It cannot
   generate a project at all. It is no longer the source of truth, so nothing
   depends on it, but it is dead code that looks alive. Not repaired — out of
   scope.
2. **Seven glyph slots were being wasted as blank padding.** Now used. Worth
   knowing that the same padding trick may leave headroom in other levels: Level
   1 emits 80 glyphs, and whether any are padding was not checked.
3. **The substrate green was already questioned by its own author.** The
   generator's docstring notes colour 5 measures `(98,213,50)` — a vivid grass
   green rather than solder-mask olive — and offers a `blue` palette (colour 6)
   as "more convincingly a circuit board". That is a whole-palette decision the
   brief explicitly told me not to take, so I have not. Flagged only.
4. **`src/level2/wave_encounters.asm` in git is STALE against the shared wave
   library, and re-exporting Level 2 silently changes gameplay.** Exporting the
   project rewrote one byte in it: a wave's colour went `10` -> `26`, which is
   colour 10 **plus the AIMED firing-mode flag** (`0x10`). The project itself
   carries no `waveDefinitions` at all — the v6 schema moved them into a shared
   library — so the exporter emits from that library, and the committed Level 2
   asm predates the library gaining AIMED on that wave. **I reverted that file**,
   because this task is art and must not change gameplay; the surface-detail
   change is confined to the charset, the metatile defs and the map.

   This matters beyond my change: *anyone* who re-exports Level 2 for any reason
   will pick that up without noticing. Either the library is right and Level 2
   should be re-exported deliberately, with the aimed-fire change play-tested, or
   the asm is right and the library entry is wrong. That is a decision, not a
   cleanup, so I have not made it.
5. From the previous task: the authored Level 3 turrets do not render. Unrelated
   to this change and already reported in
   `/reports/level3-planetscape-charset.md`.

---

## 10. Files

**Added**
- `tools/level_editor/author_level2_surface_detail.py`
- `reports/level1-pcb-surface-detail.md`

**Changed**
- `tools/level_editor/levels/level2/level.v6.json`
- `src/level2/stage_charset.asm`, `stage_config.asm`, `stage_map.asm`

**Untouched:** all of `src/level1`, all of `src/level3`, every sprite, the
engine, the raster IRQs, the scroller, the multiplexer, collision, and the
campaign loader.

---

## 11. Status

`make smoke` — **PASS**, with the changed Level 2 package loaded in the campaign:

```
CAMPAIGN LOOP: PASS
  ATTRACT -> PLAYING   ok      PLAYING -> LEVELDONE  ok  (the upgrade shop)
  CONTINUE advances    ok      level 2 package loaded ok  noSpawnRow 725 -> 352
  level 2 -> PLAYING   ok      PLAYING -> GAME OVER   ok
  returns to the front ok
Frames observed: 4062
  gameOverrun 0  scrollLate 0  edgeLate 0  statOverflow 0  statPageMismatch 0
  statPtrMismatch 0  objDoubleFree 0  objAllocFail 0  clipPoolFull 0
  publishSkip 0  schedBuildDefer 0  statLate 0
ENGINE HEALTH: PASS
ROUTINE REGRESSION: PASS
```

Every fatal counter zero. The run reaches `level 2 -> PLAYING`, so the modified
package is the one it exercised.

Smoke was run **twice**: once before the `wave_encounters.asm` revert described
in §9.4, and again afterwards, since reverting changed the built binary. Both
passed with every fatal counter at zero; the figures above are the first run and
the second was identical in verdict.

- **Nothing committed, nothing pushed.**
- VICE: every instance launched through the harness with its exact PID recorded
  and reaped; no `pkill` or `killall`; `pgrep -x x64sc` reports none remaining.
- Scratch captures and previews live in the session scratchpad, not the repo.
