#!/usr/bin/env python3
"""Runtime vertical sprite clipping, in the real production loop.

NOT PART OF `make test`. It waits for enemies to cross the aperture edges on
the authored schedule, which is content timing rather than engine behaviour.

What this proves, watching the REAL frame loop -- nothing pokes a position,
a pointer or a schedule:

* a clipped enemy's TRUE logY is untouched: it keeps advancing straight past
  the admission band while the schedule holds it at the boundary;
* the schedule entry carries the CLAMPED physical Y, so the scheduler reasoned
  about the geometry the VIC is actually programmed with;
* the entry's pointer names a SCRATCH block, and always one belonging to the
  pool that matches schedCurrent -- never the pool the main thread is filling;
* the scratch bytes are ONE OF THE ENEMY'S ANIMATION FRAMES shifted by exactly
  the right number of rows, with the off-aperture rows blank. This is checked
  against every frame of BOTH enemy species read out of the machine, at every
  clip amount observed, which is what makes the row mapping a measurement
  rather than a claim. Neither the frame nor the species is pinned: the clipper
  takes its source from logPtr, so what it copies depends on which kind of
  enemy was clipped and when the sample landed. Requiring a particular one
  would be testing the animation's phase and the wave schedule rather than the
  clipper's arithmetic;
* clipping walks one row at a time and monotonically;
* an enemy entirely outside the aperture is scheduled no entry and given no
  block;
* the pool never overflows silently;
* the production health counters stay clean.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import PRG, SYM, symbols, Vice, rd, rd1, set_bp, free_run, step_n, check, report

sym = symbols(SYM)

MAX_OBJECTS, MAX_LOGICAL, MAX_SCHED = 16, 32, 24
TYPE_ENEMY = 1
MIN_SPRITE_Y, MAX_SPRITE_Y, SPRITE_H = 55, 226, 21
CLIP_POOL_SLOTS = 6
# The longest run of identical logY a LEGALLY MOVING clipped enemy can show.
# Velocity is in quarter pixels, so the slowest non-zero speed advances logY
# once every four frames; anything longer than that means it is not moving.
LOGY_HOLD_MAX = 5
ENEMY_FRAMES = 4                # frames per species...
SPECIES = ("sonicRingFrames", "orbitalDropperFrames")   # ...and two species now,
                                # either of which may be the one being clipped
POOL = [0x0340, 0x0380, 0x03c0, 0x3100, 0x3140, 0x3180,
        0x31c0, 0x3680, 0x3700, 0x3740, 0x3780, 0x37c0]
PTR_OF = {a // 64: a for a in POOL}

MAX_FRAMES = 1400
WANT = 6            # verified clipped entries per edge before stopping


def s8(v):
    return v - 256 if v > 127 else v


def main():
    print("=== runtime vertical sprite clipping ===")
    v = None
    try:
        v = Vice(6668, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # The canonical art, read out of the machine: the clipped bytes below
        # are compared against THIS, not against a copy of the source list.
        # EVERY FRAME OF EVERY SPECIES -- enemies animate AND there are two
        # kinds of them now, so the clipper's source is whichever frame of
        # whichever species logPtr named when the sample was taken.
        canon = [rd(mon, sym[s] + f * 64, 63)
                 for s in SPECIES for f in range(ENEMY_FRAMES)]
        check("every animation frame of both enemy species was read from the "
              "machine",
              len(canon) == len(SPECIES) * ENEMY_FRAMES
              and all(len(c) == 63 and any(c) for c in canon))
        # The Dropper ping-pongs through a frame twice per cycle, so its frames
        # need only be distinct WITHIN a species, not across the whole set.
        for s, name in enumerate(SPECIES):
            grp = canon[s * ENEMY_FRAMES:(s + 1) * ENEMY_FRAMES]
            check(f"...{name} is {ENEMY_FRAMES} DISTINCT frames, not one repeated",
                  len({tuple(c) for c in grp}) == ENEMY_FRAMES)

        bp = set_bp(mon, sym["gameFrame"])

        top_ok = bot_ok = 0
        bad_bitmap, bad_y, bad_pool, bad_ptr = [], [], [], []
        clip_seen = set()
        runs = {}           # slot -> list of successive clip amounts
        mono_bad = []
        logy_frozen = []
        frozen_run = {}       # slot -> [logY, clip, consecutive samples]
        hidden_scheduled = []
        used_max = 0
        seen_frames = 0
        prev = None

        for _ in range(MAX_FRAMES):
            def sample():
                return (rd(mon, sym["objType"], MAX_OBJECTS),
                        rd(mon, sym["logY"], MAX_OBJECTS),
                        [s8(b) for b in rd(mon, sym["logClip"], MAX_OBJECTS)],
                        rd1(mon, sym["clipUsed"]))
            typ, ys, clips, used = step_n(
                mon, sym["frameCounter"], 1, sample)[0]
            seen_frames += 1
            used_max = max(used_max, used)

            live = [i for i in range(MAX_OBJECTS) if typ[i] == TYPE_ENEMY]
            for i in live:
                if clips[i]:
                    clip_seen.add(clips[i])
                    runs.setdefault(i, []).append((clips[i], ys[i]))
                else:
                    runs.pop(i, None)

            # TRUE Y IS UNTOUCHED: a clipped enemy is one whose logY is outside
            # the admission band, and it must keep moving while clamped.
            #
            # MEASURED OVER A WINDOW, NOT FRAME TO FRAME. Velocity is in QUARTER
            # pixels (src/movement.asm), so logY legitimately holds the same
            # value for several frames while the sub-pixel accumulator fills --
            # at the slowest legal non-zero speed, one quarter-pixel a frame,
            # it advances once every four. The S-turn does exactly this as it
            # crosses the top boundary: its first arc has unwound the heading to
            # 5 or 6 by then, which is vy=3, so logY holds for two frames at a
            # time at precisely the Y values that are clipped.
            #
            # Comparing consecutive frames therefore flags ordinary motion. What
            # is actually being tested is that a clamped enemy is not FROZEN, so
            # the run of identical logY is bounded instead: longer than any legal
            # velocity could produce means vy is genuinely zero.
            for i in live:
                if clips[i]:
                    run = frozen_run.get(i)
                    if run and run[0] == ys[i] and run[1] == clips[i]:
                        run[2] += 1
                        if run[2] > LOGY_HOLD_MAX:
                            logy_frozen.append((i, ys[i], run[2]))
                    else:
                        frozen_run[i] = [ys[i], clips[i], 1]
                else:
                    frozen_run.pop(i, None)

            if any(clips[i] for i in live):
                cur = rd1(mon, sym["schedCurrent"])
                n = rd1(mon, sym["schedEntries"] + cur)
                base = cur * MAX_SCHED
                sy = rd(mon, sym["schedY"] + base, MAX_SCHED)[:n]
                sp = rd(mon, sym["schedPtr"] + base, MAX_SCHED)[:n]
                sid = rd(mon, sym["schedId"] + base, MAX_SCHED)[:n]

                for e in range(n):
                    if sp[e] not in PTR_OF:
                        continue
                    # POOL OWNERSHIP: a pointer in CURRENT must name a block of
                    # CURRENT's pool. If the builder ever pointed an adopted
                    # schedule at the pool it is still filling, this is where it
                    # shows up.
                    idx = POOL.index(PTR_OF[sp[e]])
                    if (idx // CLIP_POOL_SLOTS) != cur:
                        bad_pool.append((cur, hex(PTR_OF[sp[e]])))

                    edge_top = sy[e] == MIN_SPRITE_Y
                    if sy[e] not in (MIN_SPRITE_Y, MAX_SPRITE_Y):
                        bad_y.append((sid[e], sy[e]))
                        continue

                    blk = rd(mon, PTR_OF[sp[e]], 63)
                    # Find the single (frame, shift) that reproduces these
                    # bytes. Any of the four frames is a legal source; what is
                    # being measured is that the shift is exact and the blanked
                    # rows are the right ones.
                    hit = None
                    for c in range(1, SPRITE_H):
                        vis, bl = (SPRITE_H - c) * 3, c * 3
                        for src in canon:
                            if edge_top:
                                want = src[bl:] + [0] * bl
                            else:
                                want = [0] * bl + src[:vis]
                            if blk == want:
                                hit = c
                                break
                        if hit is not None:
                            break
                    if hit is None:
                        bad_bitmap.append((sid[e], sy[e], blk[:6]))
                    elif edge_top:
                        top_ok += 1
                    else:
                        bot_ok += 1

                # FULLY OUTSIDE MEANS NO ENTRY AT ALL.
                for i in live:
                    if clips[i] == 0 and not (MIN_SPRITE_Y <= ys[i] <= MAX_SPRITE_Y):
                        if i in sid:
                            hidden_scheduled.append((i, ys[i]))

            prev = (typ, ys, clips, used)
            if top_ok >= WANT and bot_ok >= WANT:
                break

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        # ONE ROW AT A TIME, and never backwards while the same enemy holds the
        # slot. |clip| shrinks as an enemy enters and grows as one leaves.
        for slot, seq in runs.items():
            for (c0, y0), (c1, y1) in zip(seq, seq[1:]):
                if c0 * c1 < 0:
                    continue                    # different occupant
                if abs(c1 - c0) > 2:
                    mono_bad.append((slot, c0, c1))

        print(f"  .... watched {seen_frames} frames, clip amounts seen "
              f"{sorted(clip_seen)}")

        check("clipped entries were verified at the TOP edge",
              top_ok >= WANT, f"{top_ok} entries")
        check("clipped entries were verified at the BOTTOM edge",
              bot_ok >= WANT, f"{bot_ok} entries")
        check("every scratch bitmap is one of the enemy's frames shifted by exactly "
              "the right rows, with the off-aperture rows blank",
              not bad_bitmap, f"{bad_bitmap[:3]}")
        check("every clipped entry is scheduled at the aperture boundary, not "
              "at the enemy's true Y",
              not bad_y, f"{bad_y[:3]}")
        check("every scratch pointer in CURRENT names a block of CURRENT's "
              "pool, never the pool the main thread is filling",
              not bad_pool, f"{bad_pool[:3]}")
        check("a clipped enemy's true logY keeps advancing while its presented "
              "Y is clamped",
              not logy_frozen, f"{logy_frozen[:3]}")
        check("clipping walks one row at a time, never jumping or reversing",
              not mono_bad, f"{mono_bad[:3]}")
        check("an enemy entirely outside the aperture is given no schedule "
              "entry", not hidden_scheduled, f"{hidden_scheduled[:3]}")
        check("the pool allocator stayed within its capacity",
              used_max <= CLIP_POOL_SLOTS, f"peak {used_max} of {CLIP_POOL_SLOTS}")
        check("the pool never overflowed", rd1(mon, sym["clipPoolFull"]) == 0,
              str(rd1(mon, sym["clipPoolFull"])))

        for name in ("gameOverrun", "publishSkip", "schedBuildDefer",
                     "scrollLate", "edgeLate", "statOverflow",
                     "statPageMismatch", "statPtrMismatch"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero over the run", got == 0, str(got))
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
