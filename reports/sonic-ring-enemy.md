# Sonic Ring enemy — animated four-frame multicolour sprite

Replaces the single placeholder enemy bitmap with the supplied four-frame Sonic
Ring artwork and gives `TYPE_ENEMY` a deterministic `north → east → south →
west` spin. Presentation only: no movement, encounter, collision, HP, firing,
despawn or scheduling behaviour was touched.

## Files changed

| file | change |
|---|---|
| `src/enemy_art.asm` | **new.** The supplied artwork, checked in verbatim |
| `src/enemy.asm` | frame constants, cadence, `enemyAnimPtr`, `enemyTick` hook |
| `src/waves.asm` | spawn seeds `logPtr` from the live phase, not frame 0 |
| `src/main.asm` | VIC bank 0 memory-map comment only |
| `tests/test_clip_scratch.py` | stale single-bitmap assumption removed |

`src/collision.asm`, `src/ebullet.asm`, `src/player.asm`, `src/renderer.asm`,
`tests/test_player_ship.py` and the rest of `src/main.asm` also show as modified
in `git status` — that is the **preceding** uncommitted multicolour work, not
this task.

## Where the frames live

`$3580-$367f`, four aligned and adjacent 64-byte blocks, pointers `$d6-$d9`:

```
$3580  sonicRing_north   ptr $d6
$35c0  sonicRing_east    ptr $d7
$3600  sonicRing_south   ptr $d8
$3640  sonicRing_west    ptr $d9
```

This is the three blocks the player's old hires layers vacated plus the one the
placeholder occupied — the only run in the bank where four aligned blocks are
free and contiguous. Adjacency is load-bearing: the animation *adds an index*
to `ENEMY_PTR_FIRST` rather than reading a table, so assembly-time assertions
pin each label to its exact slot and reordering the art file is a build error.

The bytes are byte-identical to the supplied file (verified by extraction and
compare, 256/256). Only the comment syntax changed, `;` → `//`, because
KickAssembler does not accept `;`. No pixel was redrawn.

## Animation mechanism and cadence

`enemyAnimPtr` derives the phase from the renderer's free-running
`frameCounter`:

```
frame = ((frameCounter >> ENEMY_ANIM_SHIFT) & (ENEMY_FRAMES - 1))
ptr   = ENEMY_PTR_FIRST + frame
```

`ENEMY_ANIM_SHIFT = 3` → each frame held **8 displayed frames**, a full rotation
in **32 frames ≈ 0.64 s** of PAL. Fast enough that the specular clearly travels
the rim, slow enough to read as a spin rather than a flicker.

`enemyTick` calls it unconditionally and writes `logPtr` — the canonical path.
No renderer change: `buildSchedule` publishes `logPtr` as it always did, and
`src/clip.asm` takes its clip source from `logPtr`, so a clipped ring follows
the animation for free. A dying ring keeps spinning deliberately; freezing it
mid-ramp would read as the animation breaking rather than the enemy.

`waves.asm` calls the same routine at spawn. Seeding frame 0 instead would show
the wrong frame for exactly one frame and then snap into phase, because
`waveTick` runs after `objectUpdateAll` and a new enemy's first `enemyTick` is a
frame away.

Two assertions guard the scheme: `ENEMY_FRAMES` must be a power of two (the
phase is masked, not compared), and 256 must be a whole number of cycles
(`mod(256, ENEMY_FRAMES << ENEMY_ANIM_SHIFT) == 0`) — that is what makes it
safe to read only the **low byte** of `frameCounter` without stuttering once
every 256 frames.

## Global, and why

**Global phase, zero new state.** Not one byte was added. `frameCounter` already
advances exactly once per displayed frame, so shifting and masking it gives the
cadence for free — nothing to decrement, nothing that can drift if a frame is
skipped, and nothing to clear on spawn or free.

That was also forced: the enemy state block `$c517-$c519` is exactly full
against its `$c51a` guard, so a timer would have needed a memory-map change for
a feature that does not need memory.

Every ring spins in lockstep, which for a field of identical rings reads as one
mechanism rather than clutter. Callers ask a *routine* rather than compute the
phase inline, so the day a second species needs its own phase this becomes a
per-object byte with no caller changes.

## Memory

| | |
|---|---|
| artwork | 256 B (4 × 64) |
| **net new VIC bank 0** | **192 B** — the 4th block was already the enemy bitmap |
| code | `enemy code` `$4900-$49db` → `$49dd` (+2 B); `waves` `$7c00-$7e09` → `$7e0d` (+4 B) |
| state | **0 B** |
| VIC bank 0 free after | 1984 B / 31 blocks (`$2540-$27ff`, `$2c00-$30ff`) |

## Stale test assumptions

`tests/test_clip_scratch.py` (not in `make test`; a focused out-of-suite test)
read `enemyBitmap` as *the* canonical art and brute-forced which row shift
reproduced each clipped scratch block. With four frames the clipper's source is
whichever frame `logPtr` named when the sample landed, so matching against one
bitmap would fail.

Updated to read all four frames and accept any as the source. The real
invariant — *the scratch is a frame shifted by exactly the clip amount, with the
off-aperture rows blank* — is unchanged and still measured. Pinning a particular
frame would test the animation's phase rather than the clipper's arithmetic.
Two assertions added: four frames resident, and four *distinct* frames.

No other test encoded enemy-art assumptions. `make test`'s five suites needed no
changes.

## Focused proof

Transient probe, session scratchpad under `/private/tmp`, **ALL PASS**:

- four frames resident, distinct, at adjacent pointers `$d6..$d9`, matching the
  symbol table;
- **silhouette identical in all four frames** — it spins, it does not flicker
  between shapes;
- 4 white specular pixels per frame, in a different place in each;
- every live enemy's `logPtr` is exactly the frame the global phase names, on
  every sampled frame (sampled at `collisionTick`, after `objectUpdateAll`);
- all enemies show the same frame — lockstep confirmed;
- all four frames observed in play, each held for **exactly 8** displayed frames
  (`observed holds: [8, 8, 8, 8, 8, 8]`);
- no enemy's authored colour changed while spinning, and colours seen are
  authored wave colours;
- `gameOverrun`, `publishSkip`, `schedBuildDefer`, `scrollLate`, `edgeLate`,
  `statOverflow`, `clipPoolFull`, `objAllocFail`, `objDoubleFree` all **0**.

`tests/test_clip_scratch.py` re-run after the update: **ALL PASS** — 39 bottom-edge
and matching top-edge clipped entries verified against the four frames.

## Final regression gate

```
make test → 5/5 suites ALL PASS, exit 0, zero FAIL lines
  test_boot / test_production / test_turret_regression
  test_encounter_director / test_player_ship
```

Build clean. `build/shmup.prg` = `eb7983dda796483b7c2ef61a78ee8f025cfcf12997ce5960c584cdff6feceb2f`

## Visual inspection

Headless VICE framebuffer captures (no window, no focus theft), four screenshots
one per phase:

- **all 6 of 6 phase pairs differ** — the screen genuinely changes, not merely
  the pointer;
- the ring renders as intended: dark-grey structure (`$d025`), **the enemy's own
  authored colour as the rim** (captured yellow, wave colour 7), and a white
  specular;
- rendering the four frames from the checked-in bytes with the live palette
  shows the specular at top → right → bottom → left, the correct rotation.

One honest note on how it reads: the specular is 4 pixels of a 24×21 sprite, so
at 8 frames per step it is a **gentle glint travelling the rim**, not a dramatic
spin. That is the supplied "broken specular" artwork behaving as designed; if a
more emphatic rotation is wanted it is an art change, not a code one. Dropping
`ENEMY_ANIM_SHIFT` to 2 would double the rate at zero cost if preferred.

## Hygiene

```
du -sh build/    84K
du -sh .         4.3M
```

- **No VICE process remains** — every instance was launched by the harness,
  owned by PID and reaped (`rc=-15`). No broad `pkill`, no `-default`,
  `+saveres` retained, no persistent VICE config touched, no `open -a`, no
  focus stolen.
- No transient captures under `build/` — probes, logs and screenshots live in
  the session scratchpad under `/private/tmp`.

## Nothing committed

`HEAD` is still `a9c5dd2`. Nothing committed, pushed or tagged. `src/enemy_art.asm`
is untracked; the rest are working-tree modifications.

## Out of scope, untouched as instructed

Enemy death is still an intact ring tinted yellow/orange/red; no solid death
bitmap added. `gen_player_ship.py --check` still stale. Stale black wording in
`tools/gen_player_ship.py` untouched. Hit flash, terrain, `$D025`/`$D026`, HUD,
raster splits and mux scheduling all unchanged.
