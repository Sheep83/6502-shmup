# Multiload-ready memory architecture + boss VIC bank feasibility

**Repository:** `/Volumes/SSD/dev/C64/6502-shmup`
**Starting HEAD:** `db56d3a Second animated enemy type added`
**Working tree at start:** **clean** — see §0.
**Date:** 2026-09-15

---

## 0. Two corrections to the brief's premises, before anything else

**The path.** The brief names `/Users/brianmorrice/Dev/C64 ASM/6502-shmup`. That
directory does not exist on this machine. The repository is at
`/Volumes/SSD/dev/C64/6502-shmup`, which is where all of this was done.

**The working tree.** The brief says to expect "uncommitted changes from the
recently integrated Orbital Dropper work" and to preserve them. **There were
none.** `git status` was empty at start and HEAD was already
`db56d3a Second animated enemy type added`, which contains the Dropper. Nothing
was reset, cleaned, stashed or checked out; the tree was clean and stayed that
way apart from this task's own edits.

---

## 1. Result

| | |
|---|---|
| audit | complete — four banks, from linked addresses, §2 |
| architecture | enemy art is now a **level asset window**, not per-species homes, §4 |
| replacement proof | **ALL PASS** — dummy Level B re-resolves every pointer, §6 |
| build | clean |
| smoke gate | **RED on 3 pre-existing `test_production.py` failures** — out of scope by the brief, recorded not investigated, §7.2 |
| boss bank | **feasible — bank 2, and for a better reason than "it looks empty"**, §5 |
| VICE | 3 launched, 3 reaped, `pgrep -fl x64sc` clear |

The single most useful finding is in §5: **the three things a bank switch must
change are already runtime data, not code.**

---

## 2. Authoritative four-bank memory map

Taken from the build's own segment map (`make` prints every linked block) plus
the source, not from filenames. Ranges not listed are free.

### Bank 0 — `$0000-$3fff` — the gameplay bank

| range | contents | VIC? |
|---|---|---|
| `$0000-$033f` | zero page, stack, vectors | — |
| `$0340-$03ff` | clip scratch, 3 blocks | yes |
| `$0400-$07ff` | screen page A, sprite pointers `$07f8` | yes |
| `$0800-$0fff` | terrain charset (glyphs `$0b00-$0d3f`, turret glyphs `$0f10-$0f2f`) | yes |
| `$1000-$1fff` | **VIC sees CHARACTER ROM here** — so CPU-only code lives in it: schedule builder `$1000-$133f`, HUD code `$1400-$1768`, sorter `$1e00-$1ed6` | **no** |
| `$2000-$23ff` | player bitmaps, 16 blocks, ptrs `$80-$8f` | yes |
| `$2400-$253f` | player muzzle flash, 5 blocks, ptrs `$90-$94` | yes |
| `$2540-$27ff` | **free, 11 blocks** | yes |
| `$2800-$2bff` | screen page B, sprite pointers `$2bf8` | yes |
| `$2c00-$30ff` | **THE LEVEL ENEMY SPRITE WINDOW**, 20 blocks, ptrs `$b0-$c3` (new) | yes |
| `$3100-$31ff` | clip scratch, 4 blocks | yes |
| `$3200-$357f` | HUD bitmaps, 14 blocks, ptrs `$c8-$d5` | yes |
| `$3580-$367f` | **free, 4 blocks** — the Ring's former home, vacated by this task | yes |
| `$3680-$36bf` | clip scratch, 1 block | yes |
| `$36c0-$36ff` | hostile projectile bitmap | yes |
| `$3700-$37ff` | clip scratch, 4 blocks | yes |
| `$3800-$3fff` | blank charset (the aperture) + the VIC idle byte at `$3fff` | yes |

**Free VIC-usable bank 0:** `$2540-$27ff` (11 blocks) + `$3580-$367f` (4 blocks)
= **15 blocks / 960 bytes**, plus **12 unused blocks inside the level window**.
Before this task it was 27 blocks; the window now reserves 20 of the run it sat
in, which is the point — that space is a level's to spend, not a general pool.

`$1000-$1fff` is **not** VIC capacity and must never be counted as such.

### Bank 1 — `$4000-$7fff` — main-thread code and data

Occupied essentially end to end, `$4000-$7e20`: player, scroller, weapon, object
pool, enemy, **level assets (new, `$4b00-$4b25`)**, collision, main, terrain map
/ tables / code, turret tables / state / code, projectile, movement state, wave
state, movement, waves. Largest gaps are a few hundred bytes each.

**Not a graphics-bank candidate** without relocating ~16 KB of working code.

### Bank 2 — `$8000-$bfff` — nearly empty, and usefully shaped

| range | contents |
|---|---|
| `$8000-$8116` | clip (279 bytes) |
| `$8600-$8a97` | raster executor (1,176 bytes) |
| everything else | **free — 14,929 bytes** |

`$01 = $35` is set in `src/renderer.asm:2144` when the engine takes the IRQ, so
BASIC and KERNAL are banked out and **`$a000-$bfff` is plain RAM** to the CPU.
Verified in source rather than assumed; it matters, because a boss bank that the
CPU could not write would be useless.

**The shape that matters:** in VIC banks 0 and 2 the VIC sees the character ROM
at bank offset `$1000-$1fff`. For bank 2 that is **`$9000-$9fff`** — 4 KB that
is invisible to the VIC and therefore free for CPU code at no cost in graphics
capacity. Clip and the raster executor together are ~1.5 KB and would fit
inside it with 2.5 KB to spare.

### Bank 3 — `$c000-$ffff` — state, I/O and the vector

| range | contents |
|---|---|
| `$c000-$c29e` | schedule buffers |
| `$c300-$c3f7` | logical sprite / sorter / clip state |
| `$c400-$c401` | **level asset state (new)** |
| `$c4f0-$c4ff` | **resolved enemy animation table (new)** |
| `$c500-$c5fe` | enemy species, enemy, player, scroll, weapon, object pool, collision state |
| `$c960-$c9fc` | HUD state |
| `$cf00-$cfda` | screen row table, HUD glyphs |
| `$d000-$dfff` | **I/O to the CPU.** The VIC reads RAM beneath it, but the CPU cannot write that RAM without banking I/O out — while the IRQ needs I/O |
| `$e000-$ffff` | RAM (KERNAL out), holds the IRQ vector at `$fffe` |

**Poor candidate.** Every module's state is here, and the `$d000-$dfff` split
between what the VIC reads and what the CPU can write makes it the worst of the
four to populate.

---

## 3. Resident vs level-replaceable

The minimum model this game needs — not a framework.

### Resident (survives a level transition)

- core engine code, IRQ / raster executor / renderer / mux / sorter / clip
- object pool, collision, input, movement, weapon, player code and bitmaps
- HUD code and bitmaps, the blank charset and the aperture
- **the enemy sprite window's address and size** — engine memory map
- **a species' identity** (`SPECIES_RING`, `SPECIES_DROPPER`)
- **a species' animation shape** — the order it walks its own frames
- the schedule, frame records, and every module's state

### Level-replaceable (may be overwritten wholesale)

- terrain map, tile tables, terrain charset, level palette (`stage_config.asm`)
- turret authoring (`stage_turrets.asm`)
- **the contents of the enemy sprite window**
- **which slot of that window each species occupies** (`stage_enemies.asm`, new)
- encounter/wave data, and eventually level music

### Addresses that improperly encoded permanent ownership

| was | why it was wrong |
|---|---|
| `ENEMY_SPRITES = $3580`, `ENEMY_PTR_FIRST = $d6` | the Ring's identity and its physical home were one fact |
| `DROPPER_SPRITES = $2c00`, `DROPPER_PTR_FIRST = $b0` | same |
| `enemyAnimSeq` as **assembled constants** built from those two | the animation table could not be changed without reassembling the game |

All three are gone. `ENEMY_SPRITES`/`DROPPER_SPRITES` still exist but are now
**derived from level 1's slot claims** and are used only to place level 1's
compiled-in artwork and assert it landed correctly — **no runtime code reads
them.**

### Indirection actually needed

One byte table and one loop. That is all. No vtable, no asset manager, no
per-species record — the only thing that genuinely varies per level is *where a
species' blocks landed*, so that is the only thing the descriptor carries.

---

## 4. The asset window as implemented

```
$2c00-$30ff   LEVEL ENEMY SPRITE WINDOW   20 blocks   pointers $b0-$c3
```

Chosen because it is the **only contiguous run in bank 0 large enough for a
level's enemy library**. Bounded below by screen page B and above by the clip
scratch at `$3100`; guards in `main.asm` assert alignment, both bounds, and that
every block has a representable sprite pointer.

**The Ring moved out of `$3580` so the window could be one run instead of two
pinned homes.** That is the only asset relocated, and it is enemy artwork — the
thing this task is about. Nothing else moved.

### The three-part split

```
resident   enemyAnimShape    frame INDICES per species     (src/enemy.asm)
per level  levelAssetDescs   slot index per species        (src/level_assets.asm)
resolved   enemyAnimSeq      RAM, $c4f0-$c4ff              (built at gameInit)

           pointer = window base + slot + frame index
```

`levelAssetsLoad` (X = package index) walks the 16 entries once. A species owns
exactly one run of `ENEMY_ANIM_STEPS` consecutive entries, so an entry index's
high bits *are* its species — the same arithmetic `enemyAnimPtr` already used,
run in reverse, which is why no third table was needed.

**The hot path did not change.** `enemyAnimPtrBody` still does one `ORA` and one
absolute-`,Y` load from `enemyAnimSeq`; the table is simply RAM now. No gameplay
code learned an address, and no caller changed.

### Ring / Dropper, before and after

| | before | after |
|---|---|---|
| Ring art | `$3580-$367f`, pinned | window slot 0 → `$2c00-$2cff` |
| Ring pointers | `$d6-$d9`, compile-time constants | `$b0-$b3`, **resolved at init** |
| Dropper art | `$2c00-$2cff`, pinned | window slot 4 → `$2d00-$2dff` |
| Dropper pointers | `$b0-$b3`, compile-time constants | `$b4-$b7`, **resolved at init** |
| animation table | 16 constants in the PRG | 16 bytes of RAM at `$c4f0` |
| `$3580-$367f` | the Ring | **free** |

### Files

| file | change |
|---|---|
| `src/level_assets.asm` | **new** — packages, descriptors, guards, state, `levelAssetsLoad` |
| `src/level1/stage_enemies.asm` | **new** — level 1's slot claims, constants only, in the level package beside `stage_config.asm` |
| `src/enemy.asm` | species homes → window slots; `enemyAnimSeq` constants → `enemyAnimShape` + RAM table; art segments name their slots |
| `src/main.asm` | window constants + guards in the memory map; two imports; `levelAssetsLoad` in `gameInit`; **the bank 0 map comment corrected** (it still described the pre-banking player sprites) |
| `Makefile` | `test_level_assets.py` added to `test` and as `test-level-assets` |

---

## 5. Boss-bank feasibility

### The finding that decides it

A VIC bank switch needs three things changed. **All three are already runtime
data in this engine, not code:**

| what must change | where it lives now | cost |
|---|---|---|
| sprite pointer table destination | `framePtrHi`, a **frame-record byte** published by the scroller; the renderer self-modifies `exPtrStore+2` / `huPtrStore+2` from it once per frame | change the published value |
| screen + charset select | `frameD018`/`frameD018B`, also frame-record bytes. `$d018`'s VM/CB bits are **bank-relative** | **zero, if the layouts match** |
| the bank itself | `$dd00` bits 0-1 — **nothing in the codebase writes `$dd00` at all** today; the game runs on CIA2's power-on default (`%11` = bank 0) | one read-modify-write |

So an identical *relative* layout in the boss bank means `$d018` needs no change
whatever, `framePtrHi` differs by a constant `+$80`, and the switch itself is:

```
lda $dd00
and #%11111100
ora #%00000001      // %01 = bank 2 ($8000-$bfff)
sta $dd00
```

**Preserving bits 2-7 is mandatory** — they carry the serial bus (clock/data in
and out), ATN and RS232, and a blind `sta $dd00` would break the drive the
eventual loader depends on. The read-modify-write above is the whole discipline.

### Per-bank assessment

| bank | verdict | why |
|---|---|---|
| 0 `$0000-$3fff` | **normal gameplay bank — keep** | already the proven arrangement; `$0000-$03ff` is system RAM and can never be reclaimed |
| 1 `$4000-$7fff` | **no** | ~16 KB of main-thread code and data, occupied end to end. Relocating it to free a graphics bank is a large, high-risk move for no advantage over bank 2 |
| 2 `$8000-$bfff` | **YES — the recommendation** | only two residents (~1.5 KB), and its VIC-invisible `$9000-$9fff` window is exactly where they should go |
| 3 `$c000-$ffff` | **no** | all module state; `$d000-$dfff` is I/O to the CPU while the VIC reads RAM under it; the IRQ vector lives at `$fffe` |

### Recommended arrangement

```
bank 0  $0000-$3fff   normal gameplay          (unchanged)
bank 2  $8000-$bfff   boss presentation
          $9000-$9fff   clip + raster executor  <- VIC-invisible, no graphics cost
          rest          boss screen, arena charset, duplicated player/HUD,
                        boss sprite components, projectiles, explosion library
```

**Relocations this would require** (none of them done here, none needed yet):

1. `clip` `$8000-$8116` → inside `$9000-$9fff`
2. `raster executor` `$8600-$8a97` → inside `$9000-$9fff`

Both are position-independent code with no VIC-visible data of their own, so
this is a `*=` change plus a rebuild. **~1.5 KB into a 4 KB hole that costs
nothing.** That is the low-risk move the brief asks about, and it is the only
one required.

### Costs to budget

| item | bank 2 cost |
|---|---|
| screen matrix + sprite pointers | 1 KB (one page may be enough — a boss arena need not scroll, so the double-buffered page flip may not be needed) |
| blank charset / aperture | 2 KB if the aperture is kept; the idle byte must be zeroed at bank offset `$3fff` (= `$bfff`) |
| arena charset | up to 2 KB |
| player bitmaps + muzzle flash | **1,344 bytes duplicated** — unavoidable, the VIC can only see one bank |
| HUD bitmaps | **896 bytes duplicated** |
| projectile + clip scratch (12 blocks) | 832 bytes duplicated |
| **remaining for the boss itself** | comfortably **6-8 KB**, i.e. 96-128 sprite blocks |

Duplication is real but small against what is gained: today the whole game has
15 free blocks in bank 0; a boss bank offers roughly a hundred.

### Other answers the brief asked for

- **Can the boss bank stay populated during normal gameplay?** **Yes.** With
  `$01 = $35` the whole of `$8000-$bfff` is CPU-writable RAM and the VIC simply
  is not looking at it. Populating it at level load and leaving it is exactly
  what makes the reveal instant.
- **Does the IRQ/raster code assume bank 0 addresses?** Only through
  `framePtrHi`, which is data (above). The raster executor itself writes
  `$d011`/`$d016`/`$d018`/`$d015`/`$d027`+ and the pointer table — all either
  bank-relative or data-driven.
- **Clipping scratch and schedule-owned bitmap state.** `src/clip.asm` copies
  *rows of sprite data* into scratch blocks and repoints the sprite at the
  scratch block, so **its scratch must be VIC-visible in whichever bank is
  live** — 12 blocks, duplicated per bank. This is the one subsystem that
  genuinely needs mirroring, and it is the detail most likely to be missed.
- **Identical relative layouts?** Strongly recommended, and cheap: it reduces
  the entire switch to `$dd00` plus a `framePtrHi` constant.

### Not recommended yet

Do not move clip or the raster executor now. Nothing needs bank 2 until there
is a boss to put in it, and the move is equally cheap later. This report exists
so that decision is made on measured facts rather than on `$8000-$bfff` looking
convenient.

---

## 6. The dummy Level B replacement proof

`LEVEL_PACKAGE_B` disagrees with level 1 about **both** species — different
slots, and the two species in the **opposite order** within the window:

| | level 1 | Level B |
|---|---|---|
| Ring | slot 0 → `$b0-$b3` | slot 12 → `$bc-$bf` |
| Dropper | slot 4 → `$b4-$b7` | slot 8 → `$b8-$bb` |

The reversal is deliberate: a package that merely shifted both by a constant
could pass while the loader ignored the descriptor entirely.

Level B carries **no artwork** — the contract under test is where pointers come
from, not what the blocks contain, so the test plants its own recognisable bytes
in Level B's slots and confirms the resolved pointers address them.

Proved, in `tests/test_level_assets.py`:

- loading Level B re-resolves **every one of the 16 entries**;
- to **different** pointers than level 1 used, in the **opposite order**;
- those pointers address the planted bytes;
- **a live enemy in the real frame loop publishes only Level B pointers** —
  `['0xbc','0xbd','0xbe','0xbf']` — with no gameplay code aware anything moved;
- reloading level 1 restores its table exactly;
- health counters clean across the round trip.

---

## 7. Test results

### 7.1 Focused proof — `tests/test_level_assets.py`, **ALL PASS**

One VICE launch. 28 checks: window boundaries; both packages' slots fit and do
not overlap; level 1's art resident on its claimed slots checked **against the
bytes the VIC will fetch**; `$3580` genuinely vacated (0 non-zero bytes); the
boot table resolved from the descriptor; the full Level B round trip; and a
short live-play pass with `gameOverrun`, `publishSkip`, `schedBuildDefer`,
`statPageMismatch`, `statPtrMismatch` all zero.

**One defect found in my own test and fixed.** The first run reported a stray
level-1 pointer after the switch. The cause was the test, not the engine: it
scanned all 16 `logPtr` entries without gating on `logActive`, so a slot that
had died *before* the switch still held its last pointer and was counted as
evidence. Gated on membership — and the first sample after the switch dropped,
because the breakpoint is at the top of `gameFrame` and an enemy there still
carries what its previous `enemyTick` wrote, which is correct behaviour.

### 7.2 Smoke gate — **RED, on failures this task did not cause**

`make test`, run **once**, exit 2. `test_boot` ALL PASS. `test_production` then
failed three checks and make halted:

```
FAIL the pool actually cycled during ordinary play -- [3]
FAIL ...at exactly one pixel per frame, the movement model's rate -- moved 4 px in 5 frames
FAIL ...on every single sampled interval -- (frames, px) mismatches: [(1, 0)]
```

All three are in `test_production.py`, which **the brief declares out of scope**:
its sampling flakes are pre-existing and it is not to be touched to make a gate
green. The last two are the known movement-sampler flake with its exact recorded
signature. The first is a population-sampling window check.

Per the brief I **recorded and stopped**: no investigation campaign, no repeat
runs to characterise, and `test_production.py` was not modified.

**What this means for confidence, stated honestly:** because make halts on
failure, `test_turret_regression`, `test_encounter_director` and
`test_level_assets` **did not run in that gate**. The focused proof was run
separately and passed, and boot passed, but the turret and encounter suites have
not been exercised against this change. If you want that coverage, running them
individually is the next command — I did not, because doing so would have been
the "repeated campaign" the brief rules out.

### VICE hygiene

3 launched, 3 reaped (pids 8988, 9102, and the gate's 2). `pgrep -fl x64sc`
clear before and after. `-console`, `+saveres`, no `-default`, no joystick
overrides, no focus theft. Transient logs and maps under `/tmp`, deleted.

---

## 8. What was deliberately not implemented

- **no disk/1541 loader**, no streaming, no compression — explicitly excluded
- **no boss** and no boss state machine
- **no `$dd00` write and no bank switch** — §5 establishes feasibility; adding a
  switch with nothing to switch to would be untested code in the IRQ's path
- **clip and the raster executor were not moved.** Nothing needs bank 2 yet and
  the move is equally cheap later
- **no second set of enemy artwork.** Level B proves the address contract;
  inventing art is not this task
- **no level-selection UI** — the brief says the proof need not be player-facing
- **no changes** to the encounter director, mux, renderer, scroller, collision,
  turrets, or either species' artwork
- **`test_production.py` untouched**

---

## 9. Final state

```
HEAD  db56d3a Second animated enemy type added   (unchanged, nothing committed)

 M Makefile
 M src/enemy.asm
 M src/main.asm
?? src/level1/stage_enemies.asm
?? src/level_assets.asm
?? tests/test_level_assets.py
```

Nothing committed, pushed, staged or tagged.

```
du -sh build/   ->   84K
du -sh .        ->   4.9M
```

---

## 10. Recommended next step

**Put a second real species' artwork into the window and load it as level 2's
package.** That is the smallest thing that turns this from a proven contract
into a used one, and it exercises the part Level B deliberately does not: actual
bytes arriving in the window rather than a pointer remapping.

Only then is a loader worth writing — at which point the two segments in
`enemy.asm` marked *"when there is a loader these are what it writes"* are its
target, and the descriptor is already the manifest it needs.

Defer the bank 2 move until a boss exists. The facts in §5 will keep.

---

*The change is small on purpose: one new module, one level-package include, a
table that became RAM, and one call in `gameInit`. What it buys is that enemy
artwork no longer has a permanent address — a species now has an identity and a
shape, and a level says where its frames happen to live this time.*
