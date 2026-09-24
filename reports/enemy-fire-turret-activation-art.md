# 19656 — Enemy Aimed Fire, Earlier Turret Arming, and Turret Art Prototype

**Status: complete. Gameplay play-tested; turret art candidate B2 APPROVED AND INSTALLED into production glyph data.**

---

## 1. Starting state

| | |
|---|---|
| HEAD | `a931958` — *Added level2 data to editor* |
| Branch | `main` |
| Upstream | `origin/main` |
| Remote | `git@github.com:Sheep83/6502-shmup.git` |
| Committed | **nothing** |
| Pushed | **nothing** |

### Files already dirty before this task

This task ran inside a longer session. Everything below was already modified by
the five preceding briefs (Level 2 PCB terrain, multi-level layout cleanup,
SpritePad export, SpritePad import + `square` species, shared encounter
library) and was dirty *before* any of this task's work:

```
M  Makefile                              M  src/pickup.asm
D  src/boss_art.asm                      M  src/player.asm
M  src/encounter_format.asm              D  src/player_art.asm
D  src/enemy_art.asm                     D  src/player_boom_art.asm
D  src/enemy_dropper_art.asm             D  src/player_muzzle_flash.asm
M  src/level1/stage_enemies.asm          D  tools/gen_player_ship.py
M  src/level1/wave_encounters.asm        M  src/level_assets.asm
M  src/level2/stage_enemies.asm          M  src/main.asm
M  tools/level_editor/{controller,editor,migration,project,contract}_*.py
M  tools/level_editor/levels/level{1,2}/level.v6.json
M  tools/level_editor/test_*.py  (7 files)
?? assets/  ?? src/generated_sprites/  ?? tools/sprite_export/
?? tools/level_editor/encounter_library*.{py,v6.json}
?? tests/test_square_species.py  ?? reports/*.md
```

**Level 1 and Level 2 authored content was not touched by this task.** Proof:
re-exporting both level documents through the editor produces all fourteen
generated `.asm` files **byte-identical** to what is on disk (§7).

### What this task changed

```
M  src/ebullet.asm          M  src/turrets.asm          M  src/waves.asm
M  src/enemy.asm            (one constant + comments)
M  tools/level_editor/{contract_v2,project_v6,validation_v6,export_v6,
                       controller_v6,encounters_ui}.py
   tools/level_editor/encounter_library.v6.json   (still untracked, from the
                                                   previous task; re-serialised
                                                   here — §12)
A  tests/test_aimed_fire.py
A  tests/test_turret_arming.py
A  tools/turret_art/turret_candidates.py          (preview-only; rewritten
                                                   for the second art pass)
A  reports/turret-art/*.png                       (4 sheets)
```

---

## 2. Enemy firing architecture — the audit

### Where firing lives

| Concern | Location |
|---|---|
| Per-enemy firing mode | `enyFire` — `.fill MAX_OBJECTS` at `$c4e0`, `src/enemy.asm:396` |
| Species default mode | `enemyFireModeTab`, `src/enemy.asm:430` — one byte per species |
| Mode constants | `ENEMY_FIRE_NONE/DOWN`, `src/enemy.asm:78` |
| Which wave members may fire | fire mask in the wave trigger, `src/waves.asm` |
| Cadence | `WAVE_FIRE_PERIOD = 48` frames, `src/waves.asm:77` |
| Shot → projectile | `waveFireShot`, `src/waves.asm:~879` |
| Round-robin cursor | `wvFireCursor`, `src/waves.asm:457` |
| Projectile pool | `src/ebullet.asm` — `EBULLET_MAX = 3`, shared with turrets |

The firing mode is stored as a **value, not a flag** — `src/enemy.asm`'s own
comment says so explicitly ("a later species fires differently by storing a
different value here"). That is the hook this task used; no new subsystem was
needed.

### The cadence

`waveFireShot` runs one firing opportunity every `WAVE_FIRE_PERIOD` (48) frames
and scans the object pool **round-robin** from `wvFireCursor`, so consecutive
opportunities do not all fall to the same enemy. One opportunity produces at
most one bolt. The projectile cap (`EBULLET_MAX = 3`) is global and shared with
turret fire.

### Ring / Dropper / Square

All three pass through the *same* path: `waveSpawnMember` seeds `enyFire,x` from
`enemyFireModeTab` indexed by species, and `waveFireShot` reads `enyFire,x`. The
Dropper's special behaviour is in its *flight* (`src/dropper_flight.asm`), not in
its firing, and is untouched. `enemyFireModeTab` currently reads
`DOWN, DOWN, DOWN` — Square was given the Ring's baseline deliberately in the
previous task.

### Bullet representation and velocity constraints

A projectile is an ordinary pool object — no reserved hardware sprite.

| Field | Width | Notes |
|---|---|---|
| `logX` + `logXHi` | 9 bits | VIC X, `$d010` source |
| `logY` | 8 bits | VIC Y (top raster) |
| `objVX` | **8-bit signed, whole pixels/frame** | was always present; previously only turrets used it |
| `objVY` | 8-bit signed, whole pixels/frame | was a constant `EBULLET_VY = 3` |

**There is no fixed-point.** Velocity is whole pixels per frame, added once per
axis per frame by `objectUpdateAll`. That is the hard constraint the aim design
had to live inside, and it is why the arc is quantised rather than trigonometric.

### What already existed

Aimed fire was **already implemented for turrets** — `ebulletSpawn` →
`ebulletAim` → `ebulletSlope`. `src/ebullet.asm` had even anticipated this task
in a comment: *"A third firing mode later is another entry point and another arm
of the branch below, not another copy of this routine."*

`ebulletSlope` quantises |Δx| into three buckets:

| |Δx| | `objVX` |
|---|---|
| < `EBULLET_AIM_NEAR` (24) | 0 |
| < `EBULLET_AIM_MID` (72) | ±1 |
| ≥ 72 | ±2 = `EBULLET_VX_MAX` |

`ebulletAim` handles the 9-bit X properly: it subtracts low bytes, then
high bytes with borrow, and treats a high byte of neither `$00` nor `$ff` as
"further than 255 pixels away, use the steepest slope". Near-zero deltas fall
into bucket 0 and fire straight down. Edge-of-screen and player-above-enemy
cases are all covered by the same three buckets.

### The one real defect found in the existing aim

With `objVY` fixed at 3, the three available speeds were:

| slope | vx, vy | speed |
|---|---|---|
| straight | 0, 3 | 3.00 px/frame |
| shallow | ±1, 3 | 3.16 |
| **steep** | **±2, 3** | **3.61 — 20.2 % faster** |

That is precisely the "diagonal shots move dramatically faster than vertical
shots" the brief warned against. It was already live for turret fire; extending
it unchanged to enemies would have made it far more visible.

### One thing I did **not** change, and you should know about it

`ebulletAim` computes `plyX - logX,x` — **left edge to left edge**, not centre to
centre. The ship is 24 px wide and the bolt 8, so the true centre-to-centre delta
is 8 px larger than the one used. The bucket boundaries are therefore effectively
at 16 and 64 px rather than 24 and 72.

I left it alone deliberately: this code is shared with turret fire, its constants
are recovered/tuned values, and shifting every turret's aim by 8 px is a
gameplay change the brief did not ask for. It is a one-line fix
(`clc / adc #8` after the subtract) whenever you want it.

---

## 3. The aimed-fire implementation

### The mode

```asm
.const ENEMY_FIRE_NONE   = 0      // this species never fires
.const ENEMY_FIRE_DOWN   = 1      // one bolt, straight down
.const ENEMY_FIRE_AIMED  = 2      // one bolt, aimed at where the ship WAS
```

### Aimed, not homing

The trajectory is written once, at launch, into `objVX`/`objVY`, and nothing
reads the player again. `objectUpdateAll` adds the two velocities per frame. A
shot is always dodgeable. This is proved on the machine, not by inspection —
§7, check 10.

### Speed matching — the table

Rather than scale both axes (which needs a multiply), the **vertical step gives
way** on the steepest slope only:

```asm
.const EBULLET_VY       = 3
.const EBULLET_VY_STEEP = 2       // vertical step on the steepest slope

ebulletAimVY:
    .byte EBULLET_VY, EBULLET_VY, EBULLET_VY_STEEP
.if (* - ebulletAimVY != EBULLET_VX_MAX + 1) {
    .error "the aimed vertical table is not one entry per quantised slope"
}
```

Indexed by `|objVX|`, which is 0, 1 or 2 — so the table indexes itself.

| slope | before | after |
|---|---|---|
| 0, 3 | 3.00 | 3.00 |
| ±1, 3 | 3.16 | 3.16 |
| ±2, 3 → ±2, 2 | **3.61 (+20.2 %)** | **2.83 (−5.7 %)** |

Spread drops from **20.2 % to 5.7 %**, for one table lookup at launch and
**nothing per frame**. This also improves the pre-existing *turret* fire, which
shares the path.

### Where the branch is

`waveFireShot`, after the muzzle is computed:

```asm
    // THE MODE IS READ BEFORE THE CURSOR MOVES, and it has to be: the next
    // three instructions advance X past this enemy, so `enyFire,x` after them
    // is the mode of whoever happens to be in the NEXT pool slot. Y survives
    // the advance untouched, which is why it carries the answer across.
    ldy enyFire,x

    inx                                 // advance the round-robin past this
    txa                                 // enemy before anything can fail
    and #MAX_OBJECTS - 1
    sta wvFireCursor

    cpy #ENEMY_FIRE_AIMED
    beq !aimed+
    jsr ebulletSpawnDown
    jmp !fired+
!aimed:
    jsr ebulletSpawn
!fired:
    bcs !blocked+
```

> **This ordering cost me a debugging round and is worth flagging.** My first
> version put `ldy enyFire,x` *after* the `inx`, which read the **next pool
> slot's** firing mode. Aimed waves produced bolts with `vx = 0` about half the
> time. `Y` is untouched by `inx / txa / and / sta`, so reading the mode first
> and carrying it in `Y` is both correct and free.

### Runtime, memory and cycle cost

| Site | Cost | Frequency |
|---|---|---|
| `waveSpawnMember` mode select | ~14 cycles | once per enemy **spawned** |
| `waveSpawnMember` colour mask | 2 cycles | once per enemy spawned |
| `waveFireShot` branch | ~9 cycles | once per firing **opportunity** (1 in 48 frames) |
| `ebulletSpawnBody` VY lookup | ~20 cycles | once per **aimed bolt launched** |
| Per-frame flight | **0** | `objectUpdateAll` already added both axes |

**Zero added per-frame cost.** The PAL frame budget of 19,656 cycles is
untouched: the worst case is one enemy spawn plus one launch in the same frame,
under 50 cycles, and that happens at most once every 48 frames.

**Memory:** `ebulletAimVY` is 3 bytes. No new RAM state, no new pool, no new
object type, no new sprite reservation. The new code is a few dozen bytes inside
existing segments; every segment guard in the build still passes.

Legal NMOS 6502 only — `ldy/inx/txa/and/sta/cpy/beq/jsr/jmp/lda/bpl/eor/clc/adc/tay`.

---

## 4. Authoring and schema

### Why the firing mode lives in the colour byte

A wave definition is **ten bytes**, and `waveDefBase` forms `def * 10` in a
single byte by shift-and-add. An eleventh byte would:

* cap a level at **24** definitions instead of 26, and
* turn the shift-and-add into a general multiply.

The colour field is a C64 colour — 0..15 — with a **free high nibble**. So:

```asm
.const WAVEDEF_COLOUR_MASK = $0f        // the authored colour
.const WAVEDEF_FIRE_BITS   = $30        // bits 4-5: 0 = species default, 1 = aimed
.const WAVEDEF_FIRE_AIMED  = $10
```

**This is also what makes old packages safe.** Every colour byte ever exported
has a zero high nibble, and mode 0 means "fire the way the species always did".
A level built before aimed fire existed **cannot** acquire it. Bits 6-7 remain
free for two further modes.

### Species says *whether*, definition says *how*

`waveSpawnMember` keeps the existing species gate first — a species whose
`enemyFireModeTab` entry is `ENEMY_FIRE_NONE` still never fires, whatever the
definition asks for — and only then applies the definition's mode. Adding a
species with some third capability does not have to know about this.

### Editor

| File | Change |
|---|---|
| `contract_v2.py` | `FIRE_MODES = {"DOWN": 0, "AIMED": 1}`, `FIRE_MODE_LABELS`, `WAVEDEF_FIRE_SHIFT = 4` |
| `project_v6.py` | `WaveDefinition.fire_mode: str = "DOWN"`; `from_dict` reads `raw.get("fireMode", "DOWN")` — **absent means DOWN** |
| `validation_v6.py` | `wavedef.fire_mode` membership error |
| `export_v6.py` | packs `colour \| (FIRE_MODES[mode] << 4)` |
| `controller_v6.py` | `update_wave_definition` handles `fire_mode` as a string |
| `encounters_ui.py` | a **firing** combobox on the Wave Definition pane, under movement program |

The control sits on the **Wave Definition**, not the trigger — it is a property
of the wave's design, and a shared definition is exactly the unit you want to opt
into aimed fire. No new subsystem; one new row in an existing pane.

---

## 5. Turret lifecycle — the audit

`turretWorldTick` → `turretPrepareTick` → `turretAimTick` run once per frame from
`gameFrame` (`src/main.asm:737`).

| Stage | Answered by | When |
|---|---|---|
| Known to the engine | `turretAtMetaRow` lookup, built at assembly time | always — the whole authored set exists from boot |
| Page geometry derived | `turretPaintRow` / `turretPaintPair` | when `stageTopRow` reaches the turret's row |
| **Drawn** | `turretPaintRow != TURRET_ROW_NONE` | as soon as *either* body row is on the page — a half-on turret is still drawn |
| **Targetable** | `turretVisible` / `trtVisibleMask` | when the whole 16-px body is inside the aperture — `logY == 54` |
| **Fire clock armed** | `turretAimTick`, on the `turretVisible` 0→1 edge | `logY == 54` |
| **May emit** | `turretFireTick` | `TURRET_FIRE_MIN_Y (88) <= logY < TURRET_FIRE_MAX_Y (201)`, ship `TURRET_FIRE_LEAD (24)` below, not invulnerable, `logCount < TURRET_FIRE_MAX_POP (8)` |

There is **no tracking or acquisition phase**. A turret snapshots the player at
the moment it fires (`ebulletSpawn` → `ebulletAim`) and never again — the same
aimed-not-homing rule enemies now use.

Activation is driven by **`stageTopRow`**, a world row, not by a timer or by
player proximity. `turretLogY` is the derived sprite-scale Y that lets the
hitscan compare turrets and enemies on one scale.

### The defect, precisely

`turretAimTick` armed the clock with the **full repeat interval**:

```
arm at logY 54  +  TURRET_FIRE_INTERVAL (100) frames  @ 1 px/frame
                =  first opportunity at logY 154
```

`logY 154` is the **middle of the screen**, and the legal firing window opens at
`logY 88` — so the turret sat through **66 pixels of legal window doing
nothing**. The player's instinct on seeing a turret is to climb and engage it, so
by frame 100 the ship was usually just underneath, and the first shot went off
point-blank at a position the player had only just taken. It read as the turret
waiting for the player rather than the player walking into a turret.

---

## 6. The arming change

Three concepts, now kept separate — **only the first moved**:

| | mechanism | changed? |
|---|---|---|
| ARMING | `turretAimTick`, at `logY 54` | **the delay it loads** |
| TARGETABLE | `turretVisible` | no |
| MAY FIRE | Y window + lead + population | no |

```asm
.const TURRET_ARM_Y = APERTURE_TOP_RASTER - 1                        // 54
.const TURRET_FIRST_FIRE_DELAY = TURRET_FIRE_MIN_Y - TURRET_ARM_Y    // 34
.if (TURRET_FIRST_FIRE_DELAY <= 0 || TURRET_FIRST_FIRE_DELAY > TURRET_FIRE_INTERVAL) {
    .error "the first-fire delay must be positive and no longer than the interval"
}
```

and in `turretAimTick`, on the 0→1 edge only:

```asm
    lda #TURRET_FIRST_FIRE_DELAY        // NOT the full interval
    sta turretFireTimer,x
```

**One immediate operand. Zero cycles, zero bytes, zero new state.**

### Derived, not picked

The delay is *exactly* the distance from arming to the top of the legal window.
That is not cosmetic precision — `turretFireTick` **reloads the interval before
it tests the Y window**, so an opportunity arriving one frame early at `logY 87`
is not merely early, it is **thrown away** and the real first shot slips to
`logY 188`. Deriving the constant makes that impossible by construction.

### Tuning

| Constant | Meaning |
|---|---|
| `TURRET_ARM_Y` | where the clock starts (tracks the aperture) |
| `TURRET_FIRST_FIRE_DELAY` | how much of the approach is spent counting |
| `TURRET_FIRE_MIN_Y` | where a shot becomes legal at all |
| `TURRET_FIRE_INTERVAL` | the **repeat** cadence — unchanged at 100 |

Move `TURRET_FIRE_MIN_Y` and the first-fire delay follows automatically. The
`.if` guard fails the build if they are ever made inconsistent.

Turret count, placement derivation, damage, collision, scrolling and the pulse
are all untouched.

### Old vs new

| | arms at | first opportunity | where that is |
|---|---|---|---|
| **Before** | `logY 54` | `logY 154` | mid-screen, 66 px into the legal window |
| **After** | `logY 54` | `logY 88` | the **first** legal pixel |

---

## 7. Automated proof

### `tests/test_aimed_fire.py` — 11/11 pass

Pokes the firing-mode bits of the in-RAM wave definition table. **No level file
is modified.**

```
ok   DOWN: bolts were produced -- 2 seen
ok   DOWN: every bolt falls straight -- no horizontal velocity -- [0]
ok   DOWN: every bolt keeps the plain vertical step -- [3]
ok   AIMED, ship far LEFT: bolts lean left -- [-2]
ok   AIMED, ship far RIGHT: bolts lean right -- [2]
ok   AIMED: every horizontal velocity is inside the quantised arc -- [-2, 2]
ok   AIMED: each slope carries its matched vertical step -- [(2, 2)]
ok   AIMED: the diagonal does not outrun the vertical (within 10%) -- speeds [2.83] -> 0.0% spread
ok   AIMED: the ship was moved while a bolt was in flight -- 1 bolt(s) still alive afterwards
ok   AIMED IS NOT HOMING: no bolt changed course after launch -- {}
ok   Ring, Dropper and Square all reach the aimed path -- 2 bolt(s) from a mixed-species stage, vx [-2, 2]
```

Covering the brief's list: player below (bucket 0, straight down), down-left and
down-right (checks 4/5), strong horizontal offset (±2 at both extremes),
**moves after firing and does not home** (check 10 — the ship is teleported
across the screen while a bolt is airborne and the bolt's `vx` is re-read every
sampled frame until it dies), speed consistency (check 8), downward mode
unchanged (checks 1–3), all three species (check 11).

### `tests/test_turret_arming.py` — 17/17 pass

Watches `turretFireTimer` / `turretLogY` / `turretVisible` **every frame**.

```
ok   turrets were seen arriving on the aperture -- 2 arrival(s): [(1, 0), (2, 0)]
ok   a turret arms as its whole body enters the aperture -- arm logY [54], expected 54
ok   the clock is armed with the FIRST-FIRE delay, not the full interval -- observed [33] (loaded 34), interval would be 100
ok   the clock ran down and the turret took its opportunity -- 2 of 2 pass(es) reached a shot
ok   the FIRST opportunity lands EXACTLY at the top of the legal window -- first opportunity at logY [88, 88], TURRET_FIRE_MIN_Y 88
ok   ...far earlier than the old behaviour could manage -- [88, 88] vs logY 154 before the change
ok   ...and never before shots become legal at all -- earliest 88 >= 88
ok   every shot reloads the FULL interval, first one included -- reloads [100], interval 100
ok   a second opportunity, when the pass is long enough, is an interval later -- gaps between opportunities [101]
ok   each turret arms exactly ONCE per pass, across every fine phase -- armings per turret {1: 1, 2: 1}
ok   the clock counts down one a frame and is never reset mid-approach -- t1: 178 frames watched; t2: 178 frames watched
ok   more than one turret was exercised, and neither disturbed the other -- turrets [1, 2]
ok   the first shot really is emitted, from the turret's own muzzle -- t1 expected (4, 100) pool [(4, 100)]; t2 expected (100, 100) pool [(100, 100)]
ok   the muzzle is inside the aperture, not off the top of it -- muzzle Y [100, 100], aperture rows 88..201
ok   with NOTHING POKED, the stage scrolls to a turret on its own -- turret(s) [0] arrived unaided around frame 3448
ok   ...and it arms at the same logY, with the same first-fire delay -- arm logY [54], clock [33]
ok   ...and its first opportunity is the same logY too -- first opportunity at logY [88]
```

Mapping to the brief's turret list:

* **old first-fire point** — `logY 154`, derived from the constants the code used
  to load and confirmed by the 100-frame reload the test still observes;
* **new first-fire point** — `logY 88`, measured;
* **armed earlier** — 66 pixels earlier, measured;
* **projectile origin valid** — the bolt is identified by its **muzzle
  coordinates** (`turretXLo + 4`, `turretLogY + 12`), which an enemy bolt cannot
  imitate at that turret's column on that exact frame, and the muzzle is checked
  to be inside the aperture;
* **fine phases** — a pass spans ~180 frames, crossing all eight fine phases and
  ~22 coarse steps; the test asserts **exactly one arming per turret** and a
  clock that falls by exactly one per frame with no mid-approach reset. This is
  the guard on `turretWorldTick`'s conditional blanking, whose unconditional
  form is the documented historical bug that made firing impossible;
* **multiple turrets** — turrets 1 and 2 are on the aperture simultaneously and
  each shows an independent, uncorrupted clock.

#### Two things about this test worth recording

**It seeks the stage, and then proves the seek didn't fabricate the answer.**
Level 1's turrets sit at stage rows 344 / 224 / 216 / 116 / 108; `stageTopRow`
starts at **775** and steps back one every eight frames, so the first turret does
not reach the aperture until frame **~3450** and the last until ~5340. My first
version ran 2400 frames and reported zero arrivals — *there was nothing there
yet*. The test now pokes `stageTopRow` (which `turretWorldTick`'s fallback path
exists for, in those words) to reach turrets in ~200 frames — **and then runs a
final pass that pokes nothing at all**, free-running the real stage to turret 0
and checking the same two numbers. They match exactly.

**The repeat gap is 101 frames, not 100, and that is pre-existing.**
`turretAimTick` arms the clock and `turretFireTick` decrements it later the same
frame, so an arming of 34 spends 34 frames. The reload happens on the
`turretFireTick` path that does *not* then decrement, so a reload of 100 spends
101. Nothing in this change touched either path; it is recorded so the number
reads as measured rather than as a fault.

### Backward compatibility — measured, not argued

Re-exporting both level documents through the editor **with the new firing-mode
field present**:

```
  level1/stage_charset.asm        IDENTICAL   level2/stage_charset.asm        IDENTICAL
  level1/stage_config.asm         IDENTICAL   level2/stage_config.asm         IDENTICAL
  level1/stage_enemies.asm        IDENTICAL   level2/stage_enemies.asm        IDENTICAL
  level1/stage_map.asm            IDENTICAL   level2/stage_map.asm            IDENTICAL
  level1/stage_turrets.asm        IDENTICAL   level2/stage_turrets.asm        IDENTICAL
  level1/wave_encounters.asm      IDENTICAL   level2/wave_encounters.asm      IDENTICAL
  level1/wave_programs.asm        IDENTICAL   level2/wave_programs.asm        IDENTICAL

  ALL BYTE-IDENTICAL
```

**No existing level silently changes firing mode.** Your authored Level 1
content, including the Square trigger, is exactly as you left it.

---

## 8. Manual VICE play

AGENTS.md and the brief both make manual visible play authoritative for whether
the timing *feels* fair. I could not do it myself — judging feel requires
watching and playing, and a visible VICE would steal focus, which the standing
constraints forbid.

**Brian has since play-tested it: "Turret and enemy firing pass the play test
well."** That is the authoritative result, and no further tuning was done on
test evidence alone.

The original notes on what to look for, kept for the record:

* a turret should now begin its cycle as it clears the top of the playfield, so
  by the time you have climbed to engage it, its clock is already well down;
* the first shot arrives at `logY 88` — roughly a third of the way down — so it
  should read as "the turret shot as I approached" rather than "the turret waited
  for me to arrive";
* if it ever feels *too* eager, raise `TURRET_FIRE_MIN_Y`; the first-fire delay
  follows automatically.

---

## 9. Turret graphics constraints — the audit

> The brief's note of "12 glyphs around code 226" is **out of date**. Verified
> against the current source:

```asm
.const TURRET_GLYPH_BASE = 226
.const TURRET_GLYPH_SPAN = 4            // TL, TR, BL, BR -- ONE shared body
.const TURRET_BODY_W     = 2            // characters
.const TURRET_BODY_H     = 2
```

**Four glyphs, 226–229**, not twelve. One shared body for every turret on the
level:

```
world row R   , col C   TL = 226      col C+1   TR = 227
world row R+1 , col C   BL = 228      col C+1   BR = 229
```

| | |
|---|---|
| Footprint | 2 × 2 chars = **16 × 16 screen pixels** |
| Mode | multicolour → **8 logical px across, 16 rows down**; a logical pixel is 2 screen px wide, 1 tall |
| Budget | **128 logical pixels total** |
| Glyph data | `TURRET_GLYPHS = TERRAIN_CHARSET + 226*8`, assembled at `$0f10-$0f2f` |
| Hitbox | `TURRET_HITBOX_W = 16` — exactly the body, tied to the 2-char width |

**Namespace safety** is enforced by the build, not by convention — terrain owns
96..167 and two `.if` guards refuse a base that overlaps it or runs past 255:

```asm
.if (TURRET_GLYPH_BASE < TERRAIN_GLYPH_BASE + TERRAIN_GLYPH_COUNT) { .error ... }
.if (TURRET_GLYPH_BASE + TURRET_GLYPH_SPAN > 256) { .error ... }
.if (TURRET_GLYPHS + TURRET_GLYPH_SPAN * 8 > TERRAIN_CHARSET + $800) { .error ... }
```

No star, HUD or terrain glyph can be reached.

### Colour: what is global and what is not

| bit pair | source | scope |
|---|---|---|
| `00` | `$d021` | **global** — the stage background |
| `01` | `$d022` | **global** — terrain multicolour 1 |
| `10` | `$d023` | **global** — terrain multicolour 2 |
| `11` | **colour RAM** | **per character cell — and this is what pulses** |

Level 1's stage palette (`src/level1/stage_config.asm`): `$d021` = 12 mid grey,
`$d022` = 15 light grey, `$d023` = 11 dark grey.

### The pulse

```asm
turretPulseTable: .byte 1, 2, 7, 2      // white, red, yellow, red
.const TURRET_PULSE_INTERVAL = 8
```

`turretPaintTick` walks **one global phase** through that table every 8 frames
and writes it to all four cells of every turret — so two turrets on screen pulse
in step, and the pulse **cannot light one corner of a cell and not another**.
But *within* a cell, **bit pair 11 pulses and the other three do not.**

That is the whole opportunity, and it needs **no engine change**: no raster
split, no extra IRQ work, no per-frame charset rewriting, no extra character
bank, no sprite reservation.

### Why the current art flashes as a blob

The production body spends **66 of its 128 pixels on bit pair 11** — the entire
dome. So the whole turret strobes white/red/yellow and reads as a light, not as
metal with illuminated vents.

```asm
.byte $00,$00,$0f,$3f,$ff,$ff,$ff,$ff   // 226 TL
.byte $00,$00,$f0,$fc,$ff,$ff,$ff,$ff   // 227 TR
.byte $ff,$ff,$ff,$55,$55,$15,$02,$02   // 228 BL
.byte $ff,$ff,$ff,$55,$55,$54,$80,$80   // 229 BR
```

---

## 10. Turret art candidates — second pass

The first pass (octagon / ports / vent ring) was rejected on aesthetics. This
set starts again to a different brief: **static appearance first — a convincing
top-down metallic dome in highlight and shadow — with animation cut back to the
smallest centred indicator that is technically possible.**

`tools/turret_art/turret_candidates.py` — **preview only**. It draws each body
in a four-symbol grid, packs it to the four glyphs, and renders PNGs. **It
reproduces the production glyph bytes exactly from its own ASCII**, which is
what validates the packing.

### The palette finding that makes a dome possible

`$d023` / `$d021` / `$d022` are **11 / 12 / 15 — dark, medium, light grey**: an
evenly spaced three-step ramp. That is enough for real highlight-and-shadow
shading, which the first pass never exploited.

The catch is that **the mid-tone IS the stage background**, so it only works
enclosed by a closed dark rim. Two consequences drove every shape here, and both
were found by rendering rather than by reasoning:

* **A dome shaded the obvious way disappears.** Light highlight → mid body →
  dark shadow loses its entire shaded side into the ground and reads as a bright
  smear with no bottom. My first attempt did exactly that. So the body is
  **predominantly light grey**, the mid-tone is a **one-pixel terminator band**,
  and dark is spent on the rim and a shadow crescent at the lower right.
* **Every candidate's silhouette is machine-checked for closure.** Any mid-tone
  or lamp pixel touching the outside is a hole, not a shade. The tool prints
  `silhouette CLOSED` per candidate — and prints 28 leaks for the **current**
  production body, which has no outline at all.

### The lamp

**The smallest centred lamp is 2 × 2 logical pixels.** The body is 8 logical
pixels across so the centre falls between columns 3 and 4; it is 16 rows tall so
the centre falls between rows 7 and 8. A single pixel cannot be centred. On
screen that is **4 × 2 pixels — 4 of the body's 128**, against the production
body's 66.

It sits exactly where all four character cells meet, which is **free**: all four
cells always carry the same colour RAM value, so the lamp is seamless across the
cell boundary.

`turret-lamp-size.png` shows 2 × 2 against the next size up (2 × 4, square on
screen). **2 × 2 wins clearly** — 2 × 4 dominates the dome and reads as a white
block rather than a lamp. The sheet is there so the decision is visible rather
than asserted.

### The three candidates of pass two

Same dome, same 2 × 2 lamp; they differed only in how the static metal was
finished:

| | finish | outcome |
|---|---|---|
| **A  smooth dome** | gradient only; lamp flush on the metal | cleanest sphere, but at the white pulse phase the lamp is white on light grey and nearly vanishes |
| **B  dome, recessed lamp housing** | a thin dark collar machined around the lamp | **chosen.** The lamp reads as an aperture at every phase, at native size |
| **C  hard two-tone dome** | mid-band closed up entirely | most graphic; terminator unmissable at 1:1 |

A fourth idea — a **mounting flange** ring near the rim, as in the reference
photographs — was built and **rejected on the evidence**: at 8 logical pixels
across, a second concentric ring consumes most of the lit side and the dome
comes out as a stack of stripes. With three greys and a 16-pixel footprint, a
gradient and two rings cannot coexist. That finding is recorded in the tool.

---

## 10a. Pass three — a mounting plate under B

**B was chosen.** The follow-up brief: keep B's dome and centre essentially
unchanged, and use its currently unused outer pixels for a low-profile
octagonal or square mounting plate underneath. Do not make the dome larger.

### Where the free pixels actually are

The dome already fills its 2 × 2 character footprint — it reaches columns 0 and
7 across rows 4–11. **The only pixels it leaves free are the four corners**,
about five usable each. That turns out to be exactly right rather than a
limitation: a plate seen from directly overhead is mostly *hidden by the dome
standing on it*, and the corners are precisely where it would show.

### The dome is untouched, and that is machine-checked

The plate is drawn **only into pixels the dome does not use**, and the tool
diffs every variant against plain B:

```
B   dome, no plate  (chosen)           plate  0px  dome untouched: YES
B1  octagonal plate, lit  (rejected)   plate 12px  dome untouched: YES
B2  octagonal plate, shadowed          plate 12px  dome untouched: YES
B3  square plate, shadowed             plate 28px  dome untouched: YES
```

Every changed pixel was background in B. The dome, the collar and the lamp are
bit-for-bit what you approved.

### The three plate treatments

| | plate | outcome |
|---|---|---|
| **B1  octagonal, lit** | shaded by the same light as the dome, so its upper-left corner catches the highlight | **rejected.** The dome's dark rim separates that highlight from the dome's own lit side, so it reads as a detached bright notch — damage, not metal. Kept in the sheets as evidence |
| **B2  octagonal, shadowed** | the whole plate held in the dome's shadow | **my recommendation.** Reads as a dark octagonal base with a lit dome standing on it, and the chamfer keeps a shaped silhouette |
| **B3  square, shadowed** | no chamfer at all; fills the entire 16 × 16 footprint | heaviest and most industrial. Clear at 1:1, but its silhouette is a plain rectangle that butts straight against neighbouring terrain with no gap, so it can read as a dark patch *in* the ground rather than an object *on* it |

**The chamfer needed to be diagonal.** Cutting the corners with a box test only
shaved a single pixel off each and the plate still read as a rectangle; a
taxicab-distance cut is what gives an eight-sided outline in the handful of
pixels available.

**The plate does not use the mid-tone, deliberately.** Every plate pixel is on
the outer boundary by definition, and mid-tone there is the ground showing
through rather than a shade of metal. Plate pixels are light or dark grey only,
and all three variants still report `silhouette CLOSED`.

### What the plate does *not* change

The plate is bit pairs 01 and 10, so **bit pair 11 is still only the 4 lamp
pixels**. The hit-flash consequence below is unaffected by adding a plate.

### Previews

All four sheets now show **B and its three plate variants** side by side.

| File | Shows |
|---|---|
| `reports/turret-art/turret-static.png` | **the static look**, 10×, on Level 1's real ground colour — this is the sheet to judge |
| `reports/turret-art/turret-native.png` | native 1:1 and 8×, plus a row of three as they would sit on a stage |
| `reports/turret-art/turret-pulse.png` | all four pulse phases, on the ground colour |
| `reports/turret-art/turret-lamp-size.png` | 2 × 2 vs 2 × 4 lamp — the lamp decision, settled in pass two |

`turret-pulse.png` is the clearest statement of the change: the production body
strobes **white → red → yellow → red across its whole surface**, while all three
candidates hold a still grey dome and only the lamp changes.

### Three defects found in the existing colour handling

These are **pre-existing and unfixed**, and the third one is a genuine
consequence of the new direction that needs your decision.

**1. Bit pair 11 can never be grey.** It takes the **low three bits** of colour
RAM, so only colours 0–7 are reachable: black, white, red, cyan, purple, green,
blue, yellow. There is no grey among them except black and white. The current
turret spends 66 of its 128 pixels on bit pair 11, which is why it can only ever
be a coloured blob and never metal. This is the root cause of the look you asked
me to replace.

**2. The hit flash is the same colour as half the idle pulse.**
`TURRET_HIT_CRAM = 10 | 8` is **10**, not 18 as its comment says (`|` is not
`+`; 10 already has bit 3 set). Its low three bits are **2 — red**. Pulse phases
1 and 3 are also **2 — red**. So the source's claim that *"the hit-flash colour
is deliberately NOT one of the pulse colours, so a hit is unmistakable against
the idle animation"* does not hold on the hardware. Cheap fix whenever you want
it: change the constant to `3 | 8` (cyan) or `5 | 8` (green), neither of which
is in the pulse.

**3. ADOPTING ANY OF THESE CANDIDATES WEAKENS THE HIT FLASH.** The hit flash is
a **colour RAM write** — `turretPaintTick` stores `TURRET_HIT_CRAM` into
`trtColour` and paints the cells — so it recolours **bit pair 11 and nothing
else**. Today that is the whole dome (66/128 pixels). With a small central lamp
it becomes **4/128 pixels**: a hit would tint a 4 × 2 pixel dot for
`TURRET_HIT_FRAMES` = 4 frames, which is close to invisible.

Options, in increasing cost:

* **Accept it** — the hit already reads ambiguously (defect 2), and kill
  feedback also comes from the sound effect and the turret's destruction.
* **Make the lamp jump colour on a hit** — fix defect 2 as above so the lamp
  snaps to cyan or green. One constant; small but unambiguous.
* **Give the hit its own glyphs** — codes 230–233 are free (terrain owns 96–175,
  turrets 226–229) and the charset has room. But the body's character codes are
  written by the **page generator**, not by the colour painter, so a hit would
  have to rewrite screen codes on both pages — materially more invasive than
  today's colour-only flash, and not something to do without deciding it is
  worth it.

I have not implemented any of them. Which trade-off you want is a gameplay-feel
call, and the art is approval-gated in any case.

---

## 11. Production turret artwork — B2 INSTALLED

**Brian approved B2 and asked for it to be installed. It has been.** This
supersedes the approval gate that held through the first two passes.

### What changed

`src/turrets.asm` `turretGlyphs`, codes 226–229:

```asm
// before                                   // after (B2)
.byte $00,$00,$0f,$3f,$ff,$ff,$ff,$ff       .byte $0a,$29,$25,$a5,$95,$96,$99,$9b   // 226 TL
.byte $00,$00,$f0,$fc,$ff,$ff,$ff,$ff       .byte $a0,$68,$58,$5a,$52,$92,$62,$ea   // 227 TR
.byte $ff,$ff,$ff,$55,$55,$15,$02,$02       .byte $9b,$99,$96,$80,$a0,$2a,$2a,$0a   // 228 BL
.byte $ff,$ff,$ff,$55,$55,$54,$80,$80       .byte $ea,$6a,$aa,$2a,$aa,$a8,$a8,$a0   // 229 BR
```

The body is drawn out as ASCII in a comment beside the bytes, because four
columns of hex is not something anyone can proofread.

### What did NOT change

* `turretPulseTable` — still `1, 2, 7, 2`. A small indicator lamp wants every
  phase lit, so the dark-phase proposal from the first pass stays withdrawn.
* `TURRET_HIT_CRAM` — still `10 | 8`, defect and all (see below).
* `TURRET_GLYPH_BASE` (226), `TURRET_GLYPH_SPAN` (4), `TURRET_BODY_W/H`,
  `TURRET_HITBOX_W` (16) — identical. **Same four codes, same footprint, same
  hitbox, same placement derivation.** Nothing outside the 32 bytes of bitmap
  moved, so collision, damage, scrolling and the pulse machinery are untouched.
* No SpritePad asset was involved. Turrets are background characters.

### Verified, not assumed

Three checks, all run:

1. **The installed bytes decode to candidate B2 exactly** — all 16 rows match
   what the tool generates.
2. **The ASCII in the source comment matches the installed bytes** — all 16
   rows. A comment that disagrees with its data is worse than no comment.
3. **`turret_candidates.py` now carries `verify_installed()`**, which decodes
   the four glyphs straight out of `src/turrets.asm` and compares them to the
   candidate named by its `INSTALLED` constant. Running the tool prints:

   ```
   [ok  ] src/turrets.asm carries 'B2  octagonal plate, shadowed' exactly
   ```

   The body is generated, so it can drift; that check is what will say so if
   either side is ever edited alone.

The tool's previous-body constant was renamed `PREVIOUS` and kept, so the
preview sheets still show a before and after.

### The live consequence: the hit flash is now much smaller

This was flagged before installation and is now **in effect**. The hit flash is
a colour RAM write, so it recolours **bit pair 11 and nothing else**:

| | bit pair 11 pixels | hit flash covers |
|---|---|---|
| previous body | 66 / 128 | the whole dome |
| **B2** | **4 / 128** | the lamp only |

A hit now tints a 4 × 2 pixel lamp for `TURRET_HIT_FRAMES` = 4 frames. It is
still *there*, but it is far less legible than the old whole-dome flash.

It was already ambiguous: `TURRET_HIT_CRAM = 10 | 8` is **10** (not 18 as its
comment says — `|` is not `+`), whose low three bits are **2, red** — the same
red as pulse phases 1 and 3. So the source's claim that the hit colour is
"deliberately NOT one of the pulse colours" has never held on the hardware.

**Cheapest worthwhile fix, not applied:** change `TURRET_HIT_CRAM` to `3 | 8`
(cyan) or `5 | 8` (green). Neither appears in the pulse, so the lamp would snap
to an unmistakable colour on a hit. One constant, no cycles, no new state. Say
the word and it is a one-line change — I have left it alone because you have not
asked for it and it changes how the game reads.

## 12. Tests and builds

`make build` — **clean**, both the engine PRG and the Level 1 package. Every
segment and namespace guard passes.

### This task's new suites

| Suite | Result |
|---|---|
| `tests/test_aimed_fire.py` | **11 / 11 pass** |
| `tests/test_turret_arming.py` | **17 / 17 pass** |

### Engine suite — working tree vs clean HEAD

`make test` stops at the first failure, so each test was also run individually,
and the **same set was run against a clean `a931958` worktree** to separate
pre-existing failures from anything this task caused.

| Test | clean HEAD | working tree | verdict |
|---|---|---|---|
| `test_boot.py` | pass | pass | — |
| `test_production.py` | 2 FAIL | 1 FAIL | pre-existing (`stageTopRow`; `publishSkip` is flaky) |
| `test_turret_regression.py` | 2 FAIL | 1 FAIL | **pre-existing** — see below |
| `test_encounter_director.py` | 4 FAIL | 4 FAIL | pre-existing, identical |
| `test_player_ship.py` | 1 FAIL | 1 FAIL | pre-existing, **different check** — see below |
| `test_level_assets.py` | 3 FAIL | 3 FAIL | pre-existing, one check differs |
| `test_sfx.py` | 6 FAIL | 5 FAIL | pre-existing (stale addresses/state size) |
| `test_enemy_fire.py` | 1 FAIL | **pass** | **improved** |
| `test_pickup.py` | 2 FAIL | **pass** | **improved** |
| `test_lifecycle.py` | pass | pass | — |
| `test_player_death.py` | pass | pass | — |
| `test_boss.py` | 17 FAIL | 17 FAIL | pre-existing, identical |
| `test_heat_cadence.py` | 10 FAIL | 10 FAIL | pre-existing, identical |

**Nothing regressed.** No test that passed at HEAD fails in the working tree.

#### `test_turret_regression.py` — why it fails, and why it is not this change

Its remaining failure is `turret 7`. **Level 1 has five turrets**
(`src/level1/stage_turrets.asm:18`, committed at HEAD), but the test hardcodes
`TURRET_TOTAL = 8` at line 49. Index 7 of `turretFireTimer` is not a fire timer
at all — the array is 5 long, so index 7 lands on `trtPulseColour`, which cycles
1 → 2 → 7 → 2 and therefore "re-arms early" on every pulse step.

It fails **identically at clean HEAD**, with the same `turret 7`. The same stale
assumption cost me a debugging round in my own turret test before I derived the
count from the symbol table instead:

```python
TURRET_TOTAL = sym["turretVisible"] - sym["turretLogY"]
```

I did **not** change the regression test's constant. It is a real (if stale)
correctness check and silently editing it to make my change look green is exactly
what the standing constraint forbids. It should be fixed as its own piece of work
— at which point it will be a genuine guard on the behaviour I changed.

#### `test_player_ship.py` and `test_level_assets.py` — from an earlier task

Both fail at HEAD too, but on a *different* check in the working tree:

* `test_player_ship.py` — working tree fails *"the flash art uses only
  transparent, HW1's own colour and the shared white — never `$d025` — bit pairs
  present: [0, 1, 2, 3]"*. The muzzle-flash art now uses bit pair 3. That comes
  from the **SpritePad import task**, not this one (`src/player_muzzle_flash.asm`
  was replaced by `src/generated_sprites/`). Flagging it because it is a real
  behavioural difference that deserves its own look.
* `test_level_assets.py` — the differing check is about which level's window
  pointers live enemies publish, which moved when the **third species** was added.
  Also from an earlier task.

Neither is caused by aimed fire or turret arming.

### Editor suite — 25 files

All pass except:

| Test | Result |
|---|---|
| `test_encounter_library.py` | **49 / 49 pass** after re-serialising the library (below) |
| `test_v6_import.py` | fails at HEAD **and** in the working tree — pre-existing |
| `test_semantic_gui.py`, `test_encounters_gui.py`, `test_layout_gui.py`, `test_v6_phase6a1_hotfixes.py` | **hang / SIGSEGV at clean HEAD and in the working tree alike** — pre-existing Tk breakage in this environment |

`test_encounter_library.py` initially failed one check — *"what is on disk is
exactly what the model round-trips"*. That was **mine**: adding `fire_mode` to
`WaveDefinition` changed the serialised shape, so the on-disk
`encounter_library.v6.json` (itself created earlier in this session) was stale.
Re-saving it through the library's own `save()` fixed it. The file now carries
`"fireMode": "DOWN"` on every definition — which is what it already meant.

---

## 13. Files changed and added

### Engine

| File | Change |
|---|---|
| `src/enemy.asm` | `ENEMY_FIRE_AIMED = 2` + its rationale |
| `src/waves.asm` | `WAVEDEF_COLOUR_MASK/FIRE_BITS/FIRE_AIMED`; mode select in `waveSpawnMember`; colour read masked; the `ldy`-before-`inx` branch in `waveFireShot` |
| `src/ebullet.asm` | `EBULLET_VY_STEEP`; `ebulletAimVY` + its guard; the VY lookup after `ebulletAim`; corrected the header comment that still claimed enemy fire is never aimed |
| `src/turrets.asm` | `TURRET_ARM_Y`, `TURRET_FIRST_FIRE_DELAY` + guard; one operand in `turretAimTick` |

### Editor

`contract_v2.py`, `project_v6.py`, `validation_v6.py`, `export_v6.py`,
`controller_v6.py`, `encounters_ui.py`. Plus `encounter_library.v6.json`,
re-serialised — it is still an untracked file from the previous task, so it
shows as `??` rather than `M`.

### New

| File | Purpose |
|---|---|
| `tests/test_aimed_fire.py` | 11 machine-measured checks |
| `tests/test_turret_arming.py` | 17 machine-measured checks |
| `tools/turret_art/turret_candidates.py` | candidate art + PNG previews, **preview only** |
| `reports/turret-art/*.png` | 4 preview sheets |
| `reports/enemy-fire-turret-activation-art.md` | this report |

---

## 14. Hygiene

* **Nothing committed. Nothing pushed.** Working tree only.
* **VICE:** every launch went through `tests/harness.py`'s `Vice` class — exact
  PID ownership, `-console`, reaped in a `finally`. Every run printed matching
  `launched` / `reaped` lines. No broad `pkill` or `killall` was used; no
  user-launched VICE was touched; no window was opened and no focus stolen.
  **`ps` confirms no `x64sc` process is running.**
* One editor test process that hung (a pre-existing Tk hang) was stopped **by its
  exact PID**.
* **Scratch:** all probes, baselines and the temporary clean-HEAD worktree lived
  under the session scratchpad and are removed. `git worktree list` shows only
  the repository itself.
* **`build/` holds only the current binary and symbols** — no per-run
  directories. `du -sh build` = **300 K**. `reports/turret-art` = 40 K,
  `tools/turret_art` = 12 K. Disk: 94 GiB free of 228 GiB.

### Final git status

`HEAD` is still `a931958`, branch `main`, upstream `origin/main`. Nothing
staged beyond the deletions already present at the start of this task.

```
 M Makefile                          M src/turrets.asm
D  src/boss_art.asm                  M src/waves.asm
 M src/ebullet.asm                  D  tools/gen_player_ship.py
 M src/encounter_format.asm          M tools/level_editor/contract_v2.py
 M src/enemy.asm                     M tools/level_editor/controller_v6.py
D  src/enemy_art.asm                 M tools/level_editor/editor.py
D  src/enemy_dropper_art.asm         M tools/level_editor/encounters_ui.py
 M src/level1/stage_enemies.asm      M tools/level_editor/export_v6.py
 M src/level1/wave_encounters.asm    M tools/level_editor/levels/level1/level.v6.json
 M src/level2/stage_enemies.asm      M tools/level_editor/levels/level2/level.v6.json
 M src/level_assets.asm              M tools/level_editor/migration_v6.py
 M src/main.asm                      M tools/level_editor/project_v6.py
 M src/pickup.asm                    M tools/level_editor/validation_v6.py
 M src/player.asm                    M tools/level_editor/test_*.py  (7 files)
D  src/player_art.asm
D  src/player_boom_art.asm
D  src/player_muzzle_flash.asm

?? assets/                           ?? tests/test_aimed_fire.py
?? reports/enemy-fire-turret-activation-art.md
?? reports/shared-encounter-library.md               ?? tests/test_square_species.py
?? reports/spritepad-2-export.md   ?? reports/spritepad-2-export/
?? reports/spritepad-authority-square-enemy.md
?? reports/spritepad-authority-square/               ?? tests/test_turret_arming.py
?? reports/turret-art/               ?? tools/level_editor/encounter_library.py
?? src/generated_sprites/            ?? tools/level_editor/encounter_library.v6.json
?? tools/sprite_export/              ?? tools/level_editor/migrate_encounter_library.py
?? tools/turret_art/                 ?? tools/level_editor/test_encounter_library.py
```

Most of that is the five preceding briefs. This task's own contribution is the
four `src/*.asm` files, the six editor modules, the library re-serialisation,
and the four new files under `tests/`, `tools/turret_art/` and `reports/`.

---

## 15. Acceptance gate

**Gameplay**

| # | | |
|---|---|---|
| 1 | Existing downward fire unchanged | ✅ checks 1–3; 14 generated files byte-identical |
| 2 | New aimed mode exists | ✅ `ENEMY_FIRE_AIMED` |
| 3 | Snapshots at fire time, does not home | ✅ check 10, measured in flight |
| 4 | Speed/direction visually reasonable | ✅ spread 20.2 % → 5.7 % |
| 5 | Ring, Dropper, Square all reach it | ✅ check 11 |
| 6 | No level silently switches | ✅ mode 0 = old behaviour; byte-identical re-export |
| 7 | Turret lifecycle documented | ✅ §5 |
| 8 | Turrets arm sufficiently earlier | ✅ first shot `logY 154` → `88`, measured |
| 9 | Exposed through named constants | ✅ `TURRET_ARM_Y`, `TURRET_FIRST_FIRE_DELAY`, guarded |
| 10 | No unrelated architecture disturbed | ✅ mux, raster IRQ, scrolling (still 1 px/frame), encounter-library ownership, triggers, movement semantics, species IDs, SpritePad, boss, terrain data all untouched |

**Art**

| # | | |
|---|---|---|
| 11 | Constraints audited | ✅ §9 — **4 glyphs, not 12** |
| 12 | Multiple constrained candidates | ✅ three shaded domes, all fitting the exact footprint |
| 13 | Enlarged PNG previews | ✅ 4 sheets, incl. native 1:1 |
| 14 | Colour-cycle demonstrated | ✅ all four phases, on the real ground colour |
| 15 | Production artwork gated on approval | ✅ held through two passes; **B2 approved and installed** at Brian's instruction — §11 |

**Outstanding for you:**

1. **Look at B2 in motion.** The static and native sheets are as faithful as I
   can make them, but the body has not been seen on a real stage over real
   terrain, and that is the one thing previews cannot settle.
2. **Decide about the hit flash** (§11). It is now 4 pixels rather than 66. The
   one-line `TURRET_HIT_CRAM` change is ready when you want it.

Turret timing and enemy aimed fire are settled — you play-tested both.
