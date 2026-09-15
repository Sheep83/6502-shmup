# Orbital Dropper — second enemy species

Adds the supplied Orbital Dropper as the game's second enemy presentation,
alternating by authored wave against the Sonic Ring, and then replaces its
artwork with the revised coloured-orb variant. Visual and type identity only:
no token drops, no special behaviour, no movement, HP, firing, encounter timing
or renderer changes.

## Files changed

| file | change |
|---|---|
| `src/enemy_dropper_art.asm` | **new.** Supplied artwork, data bytes verbatim |
| `src/enemy.asm` | species constants, second frame set, per-species animation table, per-object species array |
| `src/waves.asm` | authored species column, per-instance latch, copy to object at spawn |
| `src/objects.asm` | `objectZeroSlot` clears the species byte |
| `tests/test_clip_scratch.py` | two-species clip sources; plus a pre-existing false positive fixed |
| `tests/test_player_ship.py` | VIC occupancy list corrected |

`tests/test_production.py` is **unmodified** — see the note at the end.

## The artwork, and the revision

Both the original and the revised Dropper art were checked in with data bytes
**byte-identical to the supplied file** (256/256 verified by extraction and
compare). Only the comment syntax `;` → `//` and a `.align $40` made redundant
by the caller's pinned, asserted address were changed.

The **revised coloured-orb variant** inverts the colour allocation, and it is a
large improvement:

| | original | revised |
|---|---:|---:|
| pair 10 (enemy's own colour) | 4–6 px | **68–75 px** |
| pair 01 (shared dark grey) | 77–82 px | **11–12 px** |
| pair 11 (shared white) | 21–22 px | 22–23 px |

The first version spent pair 01 on the whole orb, so every Dropper was the same
shared dark grey whatever its wave authored — and dark grey is also the
terrain's `$d023`, so it sank into the background. That was the legibility
concern raised in the previous report; the revision resolves it. The orb is now
carried by the authored wave colour, the dozen remaining dark pixels are a
shadow crescent down the lower right, and transparency defines the silhouette
rather than an outline.

## Enemy-type representation

**One byte per pool slot, `enySpecies`, written at spawn and never again.**
Stored on the *object*, not looked up through the wave: instances are two
recycled slots, an enemy routinely outlives the one that spawned it, and that
slot is then re-armed by a different wave. Cleared by `objectZeroSlot`, so the
pool's "a reused slot inherits nothing" invariant covers it. No framework — two
constants, because there is no second *behaviour* yet; when token drops arrive,
this is the byte they branch on.

**The value of a species is its animation table row** (`RING = 0`,
`DROPPER = 8`), so the per-enemy lookup is one `ORA` from memory rather than a
shift or branch.

## How authored waves alternate

A third **authored column** parallel to the existing trigger table:

```
trigDelta   = 48, 4, 38, 36
trigDef     = SWEEP,        S,               LINGER,       LOOP
trigSpecies = SPECIES_RING, SPECIES_DROPPER, SPECIES_RING, SPECIES_DROPPER
```

A column rather than `cursor AND 1` because the alternation is *content*: it
reads at a glance, survives someone inserting a fifth trigger (which `AND 1`
would silently invert for every wave after it), and pinning one pattern to one
species later is a byte here rather than a special case in the director. An
assembly-time assertion checks the alternation **including across the wrap**.

Latched onto the wave **instance** when armed — the last moment `wvNextTrig`
still names that wave — then copied to the **object** at each member spawn.

## Stable identity through overlapping waves

Measured over 900 sampled frames with both waves live:

- **no enemy ever changed species while alive**;
- **175 sampled frames had both species on screen at once**;
- every enemy's `logPtr` was its **own** species' sequence entry on every sample.

## Animation

One global phase from `frameCounter` — zero state, 8 displayed frames per step:

```
step = (frameCounter >> 3) & 7
ptr  = enemyAnimSeq[species | step]
```

The table holds **pointers, not frame indices**, so the lookup is the answer.

| species | sequence | effect |
|---|---|---|
| Ring | 0,1,2,3,0,1,2,3 | rotates twice per cycle |
| Dropper | 0,1,2,3,3,2,1,0 | ping-pong, dwelling at each turnaround |

Full cycle 64 frames ≈ 1.28 s PAL.

**Eight steps, not the six a strict ping-pong needs — a deliberate deviation.**
Six can never divide `frameCounter`'s 256-frame low-byte wrap (6 has a factor of
3; 256 is a power of two), so a six-step sequence would jog one step every 256
frames for ever, or need a byte of counter state plus a once-per-frame tick.
Eight divides cleanly, and the two spare steps dwell at the turnarounds — which
is what a satellite crossing a sphere does: slowest at the extremes, fastest
through the middle. No `3 → 0` wrap, so no satellite teleport; verified
numerically (`abs(seq[i] − seq[i+1]) ≤ 1` at every step) and by eye.

## Sprite memory

| | |
|---|---|
| Dropper frames | **`$2c00-$2cff`**, 256 B |
| pointers | **`$b0, $b1, $b2, $b3`** |
| blocks consumed | **4** |
| blocks remaining | **27** — `$2540-$27ff` (11), `$2d00-$30ff` (16) |
| new state | 16 B `enySpecies` (`$c500-$c50f`) + 2 B `wvSpecies` |
| new table | 16 B `enemyAnimSeq` |

The artwork revision changed no address, pointer or size. VIC bank 0 was not
reorganised.

## A real timing regression, found and fixed

The first working version introduced **`publishSkip = 5`** over ~39k frames
(baseline 0), reproducible in free runs with no breakpoints. It persisted with
*no Dropper ever spawned*, so it was not the art. The decisive test was adding
**three NOPs to the unmodified baseline's `enemyAnimPtr`** — 6 cycles per enemy
per frame, the same order as the real delta — which produced *exactly the same 5
skips*.

**The main thread has essentially no headroom left at peak enemy population.**
`gameSpanMax` and `gameSpanOver` both saturate at 255, so it routinely uses more
than 255 of a PAL frame's 312 raster lines. Anything added to the per-enemy path
tips it.

Fixed by making the change *cheaper than baseline*: the body is a macro, and
`enemyTick` — which runs it once per live enemy per frame — expands it **inline**,
while the rare caller (`waveSpawnMember`) keeps the subroutine. That removes 12
cycles of `jsr`/`rts` per enemy per frame, more than paying for the species
lookup. `publishSkip` back to **0**, confirmed twice. This headroom finding is
worth carrying forward independently of this task.

## Tests updated

**`tests/test_clip_scratch.py`** — matched clipped scratch bytes against the Ring's
four frames only; a clipped Dropper would have failed. Now reads every frame of
both species and accepts any as the source, with distinctness asserted *within* a
species (the Dropper shows a frame twice per cycle).

**`tests/test_player_ship.py`** — the VIC occupancy list was stale twice: the enemy
bitmap was listed as `$3640-$3680` (one block, missed when the Ring took four at
`$3580`) and the Dropper was absent. Both corrected.

**A pre-existing false positive in the clip test, diagnosed and fixed.** It failed
on an assertion I had not touched — *"a clipped enemy's true logY keeps
advancing"* — which compared consecutive frames. Velocity is in **quarter
pixels**, so `logY` legitimately holds for several frames while the sub-pixel
accumulator fills. Confirmed by arithmetic: the S-turn's first arc reaches the
top clip boundary at heading 5–6, `vy = 3` quarter-pixels, holding `logY = 54`
for two frames — reproducing the exact reported failure. The assertion now bounds
the *run* of identical `logY` instead of demanding motion every frame.

## Qualification of the final build

`build/shmup.prg` = `d2b1f0b5bc9420a8deb56357a4fe556d74acf3fbe158c79a8d968fd9cad49b90`

On this exact binary:

- **clean build**, no warnings;
- artwork **byte-identical** to the supplied file, four frames, four distinct
  bitmaps, unchanged addresses and pointers;
- **focused Dropper proof: ALL PASS** — both frame sets resident and distinct,
  adjacent pointers `$b0..$b3`, species identity stable for every enemy's
  lifetime, both species spawned, both on screen together, per-species sequences
  exact, no authored colour changed (Ring `[7, 10]`, Dropper `[3, 13]` — exactly
  the authored colours of their triggers), orb drawn in the private colour
  (`private=[75,69,68,68]` vs `shared-dark=[12,11,12,12]`), and all ten health
  counters zero over a free run;
- **`tests/test_clip_scratch.py`: ALL PASS**;
- **`tests/test_boot.py`: ALL PASS**;
- **`tests/test_production.py`: ALL PASS** on two standalone runs (see the flake
  note below).

**Not re-run on this binary:** `test_turret_regression`, `test_encounter_director`
and `test_player_ship`. They passed 5/5 on the immediately preceding build
(`03c27e85`), which differs from this one by **256 bytes of sprite bitmap data
only** — same addresses, same code, same size. Testing was stopped at your
instruction before `make test` completed end to end on the final binary, so this
report does **not** claim a 5/5 green on it.

## Visual qualification

Headless framebuffer captures; no window, no focus stolen.

- Ring and Dropper waves alternate, and a capture shows three light-red Sonic
  Rings and a cyan Orbital Dropper on screen **simultaneously** — the Dropper
  partially clipped as it enters, which is the vertical clipper working.
- The revised Dropper reads as a **lit coloured sphere**: body in the authored
  wave colour, white specular cap upper-left, dark-grey shadow crescent
  lower-right, with satellites crossing it and sitting out at the rim on the
  "wide" frame.
- The two Dropper waves (cyan and light green) are now clearly distinguishable
  from each other, which they were not before the revision.
- No visual jump at the animation turnaround; no new flicker or clipping
  regression.

## Observation, out of scope: `test_production.py` sampling flakes

Two assertions in `tests/test_production.py` fail intermittently. **Both are
pre-existing and unrelated to this task** — I reproduced the movement one on
**unmodified `HEAD`** (`d008c8b`, no Dropper, none of this work) on 1 of 3 runs,
with the identical failure text.

1. *"...at exactly one pixel per frame, the movement model's rate"* —
   `joyHold` and `joyState` are poked as two separate monitor commands with the
   machine free-running between them, so a frame can elapse with input frozen
   but no direction yet written. That frame legitimately moves the ship zero
   pixels, and if the measurement window encloses it the run fails with an
   interval of `(1 frame, 0 px)`.
2. *"the pool actually cycled during ordinary play"* — asserts the instantaneous
   `logCount` varies within a 150-frame window whose start is wall-clock
   dependent, on a wave schedule with a far longer period. A window opening on a
   quiet stretch fails while the pool is working correctly.

I had begun fixing both; at your direction those edits were **reverted in full**
and `tests/test_production.py` is byte-identical to `HEAD`. Recorded here as an
observation only — they are not blockers for a 256-byte sprite bitmap
replacement, and the fixes belong in a harness pass of their own.

## Hygiene

```
du -sh build/    84K
du -sh .         4.5M
```

**No VICE process remains.** Every instance was harness-launched, owned by PID and
reaped (`rc=-15`). No broad `pkill`, no `-default`, `+saveres` retained, no
persistent VICE config touched, no `open -a`, no focus stolen. All probes, logs
and captures live in the session scratchpad under `/private/tmp`; no per-run
artifacts under `build/`. Both temporary git worktrees used for baseline
comparison were removed — `git worktree list` shows only the main tree.

## Nothing committed

`HEAD` is still `d008c8b`. Nothing committed, pushed or tagged.
`src/enemy_dropper_art.asm` and this report are untracked; `src/enemy.asm`,
`src/objects.asm`, `src/waves.asm`, `tests/test_clip_scratch.py` and
`tests/test_player_ship.py` are working-tree modifications.

## Out of scope, untouched

Token drops, pickups, special HP/firing/movement/score, sound. Enemy death still
tints an intact sprite. `gen_player_ship.py --check` still stale. `$D025`/`$D026`,
terrain colours, HUD, raster splits, mux scheduling, encounter density, the Sonic
Ring art and the Dropper art itself all unchanged.
