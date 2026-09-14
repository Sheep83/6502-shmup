# Encounter Director v1.1 — composable flight paths

Built on the `encounter-director-v1` tag. Movement is now expressed as short
sequences of reusable stages rather than one primitive per shape, and four
authored patterns use that vocabulary.

**MANUAL VISUAL QUALIFICATION PENDING** — see the last section. The automated
gates below are green; whether the patterns actually look and feel good is the
user's call, not theirs.

## Movement-stage architecture

v1 gave each enemy one primitive plus one queued follow-on (`wmNext`), which is
exactly enough for "fly in, then turn". Two things changed.

**1. A stage cursor instead of a single follow-on.** `wmNext` became `wmStage`,
a byte offset into a shared authored stage table. When a stage finishes,
`wmEnterNext` advances the cursor by one record and `wmEnterStage` takes up
whatever it now names. The same `wmEnterStage` is what `waveSpawnMember` calls
to launch an enemy, so a pattern's first stage cannot behave differently from
the same stage mid-pattern.

**2. The arc table became a heading table.** This is the change that makes arcs
compose. v1's arc was a quarter turn *from a fixed heading* — sixteen phases
from east to south, with the mirrored variant negating vx — so two arcs could
not be joined: the second restarted pointing east whatever the first had left
the object doing. `wmPhase` now holds a **heading** (0..63 clockwise from east,
+y down) and an arc stage means "rotate the heading N steps". The old quarter
arc is the first sixteen entries of the new table, so a v1 sweep still launches
east and still turns south at the same rate.

The stage record is four bytes, and bytes 2–3 mean different things per kind
because an arc has no use for a velocity:

| kind | arg | byte 2 | byte 3 |
|---|---|---|---|
| `WM_STRAIGHT` | frames | vx | vy |
| `WM_HOLD` | frames | vx | vy |
| `WM_ARC` (clockwise) | heading steps | frames per step | — |
| `WM_ARC_MIRROR` (anticlockwise) | heading steps | frames per step | — |
| `WM_EXIT` | — | — | — |

`WM_EXIT` is terminal and keeps whatever velocity it inherited, which is what
makes `ARC -> EXIT` continuous. The format lives in `movement.asm` beside the
interpreter; the bytes live in `waves.asm` beside the rest of the content.

This is not a VM: the interpreter is one compare ladder and five primitives,
and everything interesting comes from the order the content puts them in.

## Per-object state

The `$7700` block went from nine arrays to ten (144 → 160 bytes):

- `wmStage` — **repurposed** from `wmNext`: the stage cursor.
- `wmPhase` — **repurposed**: heading 0..63, not progress through one turn.
- `wmSteps` — **new**: heading steps left in the current arc stage.

Everything else (`wmMode`, `wmTimer`, `wmVX/VY`, `wmAccX/AccY`, `wmBaseCol`) is
unchanged, and the quarter-pixel integrator `wmApplyVelocity` was not touched at
all. Frames-per-step is read from the stage record when a step completes, so the
per-stage turn radius costs no per-object state.

## How the shapes are made

- **Extended turns and loops** — `AND #63` on the heading is the whole of it. A
  turn of more than a full circle wraps and keeps going; there is no loop
  primitive, no orbit centre, no angle accumulator. 16 steps is a quarter, 32 a
  half, 64 a full circle, 76 a circle plus a new exit heading.
- **S-turns** — `WM_ARC` then `WM_ARC_MIRROR` (or the reverse). The S is the
  join between two opposite-handed arcs. No spline or curve engine.
- **Turn radius** — frames-per-step, per stage. The heading sweeps a full circle
  in 64 steps regardless, so a step held for *f* frames walks a circle of radius
  ≈ 15.3·*f* px: 61 px at *f*=4 (v1's wide sweep), 31 px at *f*=2 (a tight
  loop). One primitive is both a lazy hook and a dogfight loop.
- **Hold/linger** — a bounded stage with an authored, usually slow velocity,
  sharing the timed-step code with `WM_STRAIGHT`. It is a distinct mode value
  purely so "this enemy is deliberately loitering" is visible in state. The
  authored hold is `(0,+1)`, not `(0,0)`: a dead stop reads as a hung sprite,
  and a quarter pixel a frame keeps it descending toward the despawn rule.

## The four authored patterns

| # | pattern | count × interval | fan (x, y) | path |
|---|---|---|---|---|
| 0 | echelon sweep | 4 × 22 | +16, **+20** | `STRAIGHT 34 (6,0)` → `ARC 16 @4` → `EXIT` |
| 1 | S-turn | 3 × 26 | +26, **+18** | `ARC_MIRROR 12 @3` → `ARC 20 @3` → `EXIT` |
| 2 | linger and break | 3 × 26 | +34, **+24** | `STRAIGHT 28 (3,5)` → `HOLD 48 (0,1)` → `ARC 12 @4` → `EXIT` |
| 3 | loop | 3 × 34 | +40, **+26** | `ARC 76 @2` → `EXIT` |

Pattern 1 launches on heading 12 (steep), unwinds to level east and rolls over
past south to down-left — a bulge right then a sweep away left. Pattern 3
launches east so the circle's centre is directly *below* the entry point, which
is why the loop hangs from the spawn line and never climbs above it.

## Entry and exit geometry

**`yStep` is the new wave-definition field and it is the mux-friendliness one.**
v1 fanned members along X only, so a four-strong wave entered as a rank on one
raster line and stayed that way through its level launch leg — four logical
sprites competing for one reuse window, which is the geometry the multiplexer
finds hardest. Every pattern now fans Y as well, 18–26 lines per member against
a 21-line sprite, so entries are echelons and members reach the exit corridor at
different times. Exits inherit the same stagger and are further spread by the
turns themselves.

The assembler **flies every pattern** at build time — the same quarter-pixel
arithmetic the 6502 does, for the first and last member of each wave — and
rejects one that never descends past `MAX_SPRITE_Y` (a permanent pool-slot
resident), climbs above `MIN_SPRITE_Y` (invisible mid-manoeuvre, and a `logY`
that passes zero wraps to 255 and silently despawns), or leaves the nine-bit X
world (a negative X is `logXHi = $ff`, which the builder puts back on screen on
the wrong side). v1 could prove termination by inspection; composition ends
that, so it is now integrated rather than argued.

## Encounter schedule and the density fix

Deltas `26, 5, 26, 4` over sweep, S-turn, linger, loop — a 61-row (~10 s)
period. The sequence is **pairs, not a round robin**: a short delta that makes
two *different* patterns share the director, then a long one that lets the
screen clear. An instance is held until its last member is sent, i.e.
`1 + (count-1)*interval` frames, so sweep (67 frames) overlaps an S-turn
triggered 40 frames later, and linger (53) overlaps a loop triggered 32 later.

**The first schedule was wrong and the renderer said so.** Deltas of 7/16/8/15
read well on paper and put **ten** enemies on screen, because enemies outlive
their waves by seconds and three waves' worth were airborne together:
`publishSkip 43` over 900 frames. The fix is in the content, not the scheduler.
With the long deltas, a 44,403-frame run (~15 minutes of emulated play) peaked
at **7 enemies / 7 pool objects** with every counter at zero.

An earlier revision also mis-derived occupancy as `count*interval`, which
overshoots by a whole interval; the pairs missed each other by five frames and
the director never held two instances at all. It is derived in frames now.

## Memory map

| block | v1 | v1.1 | headroom |
|---|---|---|---|
| movement state | `$7700–$778f` | `$7700–$779f` | 32 B (guard `$77c0`) |
| wave state | `$77a0–$77b0` | `$77c0–$77d0` | 47 B (guard `$7800`) |
| movement code | `$7800–$7903` | `$7800–$7998` | 615 B (guard `$7c00`) |
| waves code | `$7a00–$7bca` | `$7c00–$7e05` | 507 B (guard `$8000`) |

Wave state moved down 32 bytes to give the movement block room for its tenth
array; the waves segment moved to `$7c00` because the stage table and four
patterns did not fit in the 54 bytes v1 had left, and `$7c00–$bfff` was empty
(the next thing above is the schedule buffers at `$c000`). Both files now have
real headroom instead of sitting against a wall. Guards updated accordingly.

## Results

**Focused proof — `make test-flight-paths` (new, NON-default): ALL PASS, 57 s.**
Watched 395 production frames; nothing calls `wmTick`/`wmEnterStage`/
`waveSpawnMember` directly.

- every primitive ran including the linger: `ARC ARC_MIRROR EXIT HOLD STRAIGHT`
- a three-stage path walked end to end (2 transitions on one enemy)
- **3 enemies ran both arc handednesses** — the S-turn is composed, not a curve
- **2 holds advanced** — the linger ends by itself and hands on
- **40 of 64 distinct headings on one enemy** (64/64 on an earlier run) — the
  loop, which a fixed quarter turn could not express
- 10 slots returned; two *different* patterns in flight for 46 frames

**`make test`: ALL PASS** (boot, production, turret regression, encounter
director), 15:53 wall.

**Permanent regression — `make test-encounter-director`: ALL PASS, 3:16**,
232 frames watched, longest two-instance streak 5, best arc run 63 phases.

All production health counters **zero** in every run: `gameOverrun`,
`publishSkip`, `schedBuildDefer`, `scrollLate`, `edgeLate`, plus `wvDropped`,
`wvDeferred`, `objAllocFail`, `objDoubleFree`.

### On runtime, honestly

The permanent test watched 88 frames in v1 and 232–387 now, because its overlap
windows are narrower than v1's (21–27 frames against 45) and it additionally
waits for a two-transition composed path. **Wall-clock on this machine is
extremely variable** and is not a reliable signal: the *same* flight-paths
binary measured 57 s, 6:37 and 9:40 on three runs, differing only in background
load. I have not tuned further — the brief asks not to optimise the test
framework or re-benchmark — but if the default gate feels slow, widening the
paired waves' *intervals* (not shortening the deltas) would both widen the
overlap windows and lower instantaneous density.

The vocabulary proof is deliberately **not** in `make test`: it waits for four
specific patterns on a ten-second cycle to re-prove content that only changes
when someone edits it. The permanent test proves the *architecture* — that an
enemy walks an authored stage list — and does not know any pattern by name.

## Unchanged

No renderer, scheduler, raster, sorter, builder, multiplexer, pool-policy or
harness changes. Player movement, hitscan, enemy damage/destruction, turret
presentation/damage/firing, enemy projectiles, player damage/invulnerability,
terrain scrolling and aperture presentation are untouched; the director still
knows nothing of hardware sprite numbers or VIC registers. VICE flags confirmed
in-flight as `-warp -console +saveres -pal +sound -remotemonitor …` — no
`-default`, no joystick-detach overrides, no persistent settings altered. Every
launched PID was owned and reaped (`rc=-15`); none remain.

## Hygiene

```text
$ du -sh build/
88K     build/

$ du -sh .
4.3M    .
```

Transient probes lived in the session scratchpad and are gone; no `/tmp`
artifacts remain.

```text
$ git status --short
 M Makefile
 M src/movement.asm
 M src/waves.asm
 M tests/test_encounter_director.py
?? tests/test_flight_paths.py

$ git diff --stat
 Makefile                         |  13 +-
 src/movement.asm                 | 388 ++++++++++++++++++---------
 src/waves.asm                    | 552 +++++++++++++++++++++++++++++++--------
 tests/test_encounter_director.py |  74 ++++--
 4 files changed, 777 insertions(+), 250 deletions(-)
```

No commit, no push. No `.vscode/settings.json` change.

## MANUAL VISUAL QUALIFICATION PENDING

`make run`, then judge:

- do the four patterns look **visibly distinct** (echelon sweep, S weave,
  hover-and-break, loop)?
- do the arcs, the S join and the loop look **smooth** — no kink where stages
  hand over?
- does the linger read as **deliberate** hovering rather than a stuck sprite,
  and is the deliberate speed jump out of the hold (from `(0,+1)` to full arc
  speed) a good "break away" or just abrupt?
- do enemies stay **engageable** long enough, and is the loop's ~4 s too long?
- do the **overlapping pairs** (sweep+S, linger+loop) look good together?
- do entries and exits keep a sensible **Y spread**?
- any visible **skips or hitches** at the busiest moment (~7 enemies)?

Automated green is not this slice's gate. Until the above is seen, v1.1 is not
GREEN.
