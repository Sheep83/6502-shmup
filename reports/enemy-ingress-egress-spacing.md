# Enemy ingress/egress + encounter spacing correction

Built on the Encounter Director v1.1 flight-path work. Two reported problems:
enemies materialising and vanishing inside the playfield, and formations
overlapping almost continuously. Both fixed in enemy lifecycle semantics and
authored content. No renderer, scheduler, raster or multiplexer change.

**MANUAL VISUAL QUALIFICATION PENDING** — see the last section.

## What the coordinates actually mean

Established from the production source before changing anything:

| thing | value | where from |
|---|---|---|
| visible playfield | rasters **55..247** | `TOP_SPLIT_LINE`..`BOT_SPLIT_LINE-1`, main.asm |
| `logY` anchor | VIC sprite Y = raster of the sprite's **top** row | motion.asm / renderer |
| `logX` anchor | VIC sprite X, nine bits over `logX`/`logXHi`; display window is sprite X **24..343** | renderer builder |
| sprite extent | 21 rows × 24 columns | `SPRITE_HEIGHT`, VIC |
| renderer admission | `MIN_SPRITE_Y`=55 .. `MAX_SPRITE_Y`=226, **Y only** | renderer.asm |

Two findings decided the whole design:

**1. The admission band means "the whole sprite is inside the aperture", and
the renderer REJECTS rather than clips.** A sprite at Y=226 has its last row at
246, one line above the aperture floor; at 227 it is refused outright. Both
bounds are hardware-derived and were left alone: 226 is the largest Y that
keeps sprite DMA off lines 247–248, which is exactly the bottom split's timing
margin, and 55 makes the PAL raster double-match at Y+256 unreachable.

**2. There is no X admission test at all.** The builder checks Y and lets the
VIC clip horizontally. Side crossings are therefore already progressive in
hardware — which is why the sweep now enters through the left border.

## Old vs new semantics

**Old.** `ENEMY_DESPAWN_Y = 226` — the renderer's admission ceiling used as the
edge of the world, so an enemy died at the instant it stopped being drawn.
Spawn lines were 56..132, i.e. up to a third of the way down the aperture.
Together: enemies appeared in mid-air and disappeared in mid-air.

**New.** Lifetime is deliberately wider than visibility, and derived:

```
ENEMY_HIDDEN_Y      = APERTURE_TOP_RASTER - SPRITE_HEIGHT   = 34
ENEMY_CLEAR_Y       = APERTURE_BOT_RASTER + 1               = 248
ENEMY_CLEAR_X_LEFT  = 4        ENEMY_CLEAR_X_RIGHT = 344
```

- **Ingress.** Three patterns spawn at Y=30 (sprite ends at 50, four lines
  clear of the aperture) and descend in; the renderer simply does not admit
  them until they cross 55. The sweep spawns at **X=0**, entirely behind the
  left border, and is clipped column by column as it flies east.
- **Egress.** An enemy lives until `logY >= 248` (its top past the aperture
  floor) or until it has cleared a side border. The old 226 cutoff is gone.
- **Side rules are direction-aware.** Position alone cannot tell arriving from
  leaving — the sweep spawns behind the very border a naive rule would kill it
  at, which is exactly what the first draft did on frame one. An enemy behind a
  border is gone only if `wmVX` still carries it that way.
- **The left bound is also the wrap guard.** `logX`/`logXHi` are unsigned and
  the builder treats any non-zero high byte as the X MSB, so an enemy walking
  past zero would borrow to `$ff` and reappear 256 pixels right. Freeing at 4,
  with an assembly-time check that one frame's movement cannot step over that
  window, keeps the coordinate positive at all times. **No representation
  change was needed** and no renderer special case exists.

**Visibility/culling: unchanged.** The existing Y admission already skips
fully-off-aperture objects and counts them in `statRejRange` (documented as not
a fault), so alive-while-hidden costs no mux slot. Partially visible sprites
still render and the VIC clips them.

### The one limitation, stated plainly

Top and bottom ingress/egress are **not** progressive: the renderer admits only
whole-sprite-inside, so an enemy appears at the top aperture edge in one step
and vanishes when its top passes 226 (its body then one line above the floor).
Making those edges clip would require admitting partial sprites, which the
bottom's DMA/split timing forbids outright. Left/right crossings *are*
progressive. This is an architectural boundary, not an oversight — the fix for
the reported bug is that enemies now arrive and leave **at the edges** instead
of 20–130 pixels inside them.

## Path validator

Rewritten to fly each path frame by frame through the **real** three-edge
lifecycle rather than fencing coordinates in. Bounded off-screen travel is now
the point, so a runaway is distinguished from intentional travel by asking:

- **it leaves** — some edge reached inside 900 frames;
- **it arrives** — becomes visible inside the aperture, within 240 frames;
- **it never wraps** — X stays positive for the whole flight;
- **it does not materialise in view** — every member is entirely outside the
  playfield at spawn (hidden above, or behind a side border).

That last check caught the v1.1 spawns immediately, and a straight/hold leg
that could out-run the left clearance window is rejected too.

## Encounter spacing

The pacing error was measuring the wrong thing. A wave's *instance* is finished
in ~8 rows, but its *enemies* live far longer, so the interval that matters is
the whole footprint:

| pattern | instance | footprint (spawn span + last lifetime) |
|---|---|---|
| sweep | 8.4 rows | 243 frames ≈ 30 rows |
| s-turn | 6.6 | 252 ≈ 32 |
| linger | 6.6 | 258 ≈ 32 |
| loop | 8.6 | 385 ≈ 48 |

Deltas are now those footprints: **48, 4, 38, 36** over sweep → S-turn →
linger → loop, a 126-row (~20 s) period, against v1.1's 61 rows with two
overlapping pairs.

**One deliberate overlap remains**: the four-row delta from sweep to S-turn.
They are the right pair — the sweep enters through the **left border** at a
fixed height, the S-turn comes down from **above** on the other side, so they
are separated in entry point, direction and Y for the whole time they share the
aperture. Everything else gets empty sky between it and the next formation.

Member spacing follows ingress: the three top-entering patterns now use
`yStep 0`, because a downward yStep pushes later members *into view* before they
have entered. Every member descends, so a 26-frame interval is itself ~32 lines
of separation — more than a sprite is tall — by the time they are all on
screen. Only the sweep, entering level through the side, keeps an authored
`yStep` (+20).

The loop pattern gained a 40-frame `STRAIGHT (+4,+4)` **dive stage** in front of
its arc: it launched due east, the one heading that cannot arrive from above. A
stage, not a special case — which is what the composable system is for.

## Results

**Focused proof — `make test-ingress-egress` (new, NON-default): ALL PASS, 59 s.**
1150 production frames, all four patterns:

- **Y seen alive up to 247** — impossible under the old 226 cutoff; the
  premature despawn is gone
- 50 object-frames alive while wholly off screen; **19 enemies entered view**
- **no enemy materialises inside the playfield**
- **108 object-frames straddling a side border** (the sweep's VIC-clipped entry)
- 15 clean bottom exits; none freed away from an edge; none left past a bound
- **X never wrapped** — `logXHi` stayed 0 or 1 throughout

**`make test` (one run, 4:14): 3 of 4 suites ALL PASS.** Boot, production and
encounter director green. `test_production` shows the intended effect directly:
live object count **0..3** where v1.1 ran 2..7.

**The fourth suite failed on a flaky setup check, not a regression.**
`test_turret_regression` reported "a freshly arrived turret was found to watch"
— its *setup* step, which polls 40 times (each after 0.25 s of **warp**
free-running, i.e. hundreds of emulated frames) hoping to land in a 12-frame
window of a 100-frame timer. In that same run every substantive assertion
passed, including the actual regression ("fire timer NEVER re-arms early") and
"the real game launches a hostile projectile" (ebFired 76→78). `git diff --stat`
over `src/turrets.asm src/ebullet.asm src/terrain.asm src/scroll.asm` is empty —
this slice touches none of them. A focused re-run of that one target passed
outright, including the check that failed. Reported rather than patched, per
the brief; the lighter enemy population makes warp run faster, which widens the
poll's stride and makes a pre-existing race more likely to lose.

All production health counters **zero** in every run: `gameOverrun`,
`publishSkip`, `schedBuildDefer`, `scrollLate`, `edgeLate`, plus `wvDropped`,
`objAllocFail`, `objDoubleFree`.

### Permanent test

`tests/test_encounter_director.py` got **one constant change**: `MAX_FRAMES`
900 → 1250, because the authored period grew to 1008 frames and there is now
one overlap per cycle instead of two. No new checks, no new telemetry.

## Memory map

Unchanged — no state added. `enemy.asm` gained constants and ~20 bytes of
despawn code; `waves.asm` grew by four bytes of stage table.

```
$7700-$779f movement state     $7800-$7998 movement
$77c0-$77d0 wave state         $7c00-$7e09 waves   (guard $8000)
```

## Hygiene

VICE: every launch owned and reaped (`rc=-15`); none remain; harness untouched
(`+saveres`, no `-default`, no joystick overrides). No `/tmp` artifacts.

```text
$ du -sh build/        88K     build/
$ du -sh .             4.4M    .

$ git status --short
 M Makefile
 M src/enemy.asm
 M src/movement.asm
 M src/waves.asm
 M tests/test_encounter_director.py
?? reports/encounter-director-v1.1-flight-paths.md
?? tests/test_flight_paths.py
?? tests/test_ingress_egress.py

$ git diff --stat
 Makefile                         |  23 +-
 src/enemy.asm                    | 133 ++++++++-
 src/movement.asm                 | 399 +++++++++++++++++--------
 src/waves.asm                    | 617 +++++++++++++++++++++++++++++++--------
 tests/test_encounter_director.py |  76 ++++-
 5 files changed, 982 insertions(+), 266 deletions(-)
```

No commit, no push. No `.vscode/settings.json` change. (`movement.asm`,
`test_flight_paths.py` and the v1.1 report are the previous slice's uncommitted
work; this slice added one assert to `movement.asm`.)

## MANUAL VISUAL QUALIFICATION PENDING

`make run`, then judge:

1. enemies begin fully outside the aperture — nothing appears in mid-air;
2. they arrive **at an edge** rather than inside it (and the sweep visibly
   slides in through the **left border**, clipped as it comes);
3. side crossings clip naturally;
4. exits stay visible until the sprite has reached the edge;
5. no blinking out inside the playfield;
6. encounter spacing gives obvious breathing room — one formation, empty sky,
   next formation;
7. the sweep + S-turn pair still overlaps deliberately, and no longer dominates;
8. no sprite flicker, skips or hitches.

Worth a specific look: the top/bottom edges still change in one step rather
than clipping (see "the one limitation"). If that reads badly in motion, say
so — the alternative is raster work on the bottom split, which is a different
slice.
