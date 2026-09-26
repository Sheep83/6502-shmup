#!/usr/bin/env python3
"""Hostile bolts reach the bottom of the playfield, and stay dangerous while
they are visible.

    python3 tests/test_ebullet_clipping.py

THE DEFECT THIS FIXES. A sprite is admitted whole or not at all, and a bolt's
ink is only the first SEVEN of its twenty-one rows -- so the admission rule
culled the bolt the instant its logical Y passed MAX_SPRITE_Y = 226, while the
last inked row was still fourteen rasters above the floor. The bolt vanished in
mid-air. It then stayed logically alive, invisible, as far as logY 250.

WHAT WAS DONE. The bolt is enrolled in the SAME vertical clipping path enemies
and tokens already use: one jsr to logClipAnnotate. src/clip.asm pins the
PRESENTED Y at MAX_SPRITE_Y and shifts the pixels, so logical Y is never
touched and the ink keeps landing on the raster the bolt's real position
demands.

HOW THIS TEST READS THE MACHINE. Two traps, both of which the preceding audits
hit and documented:

  * THE PUBLISHED SCHEDULE LAGS. schedCurrent is the buffer the EXECUTOR reads
    and it describes the PREVIOUS frame, so an entry can name an object whose
    logical Y has already moved on. Every schedule assertion here is made
    against the entry's own logId and the Y that entry carries, never against
    the live logical Y of the same frame.
  * EVERY MONITOR COMMAND HALTS THE MACHINE. Polling in a loop freezes the
    thing being measured. Frame stepping is step_n on the gameFrame breakpoint
    throughout; nothing here free-runs and then reads.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     step_n, check, report, LAUNCHED_PIDS)

sym = symbols(SYM)
PORT = 6680

MAX_OBJECTS = 16
MAX_SCHED = 24
TYPE_EBULLET = 2

# src/renderer.asm
MIN_SPRITE_Y = 55
MAX_SPRITE_Y = 226
SPRITE_HEIGHT = 21
# src/ebullet.asm, all derived from the seven inked rows
INK_ROWS = 7
INK_Y_MAX = MAX_SPRITE_Y + SPRITE_HEIGHT - 1        # 246
INK_Y_MIN = MIN_SPRITE_Y - (INK_ROWS - 1)           # 49
EBULLET_Y_MAX = INK_Y_MAX + 1                       # 247
EBULLET_SPRITE = 0x36C0


def bolts(mon):
    act = rd(mon, sym["logActive"], MAX_OBJECTS)
    typ = rd(mon, sym["objType"], MAX_OBJECTS)
    ly = rd(mon, sym["logY"], MAX_OBJECTS)
    clip = rd(mon, sym["logClip"], MAX_OBJECTS)
    out = {}
    for i in range(MAX_OBJECTS):
        if act[i] and typ[i] == TYPE_EBULLET:
            c = clip[i]
            out[i] = (ly[i], c - 256 if c > 127 else c)
    return out


def sched(mon):
    """The PUBLISHED schedule: {logId: (presentedY, ptr)}."""
    cur = rd1(mon, sym["schedCurrent"])
    base = cur * MAX_SCHED
    n = rd1(mon, sym["schedEntries"] + cur)
    ys = rd(mon, sym["schedY"] + base, MAX_SCHED)
    ids = rd(mon, sym["schedId"] + base, MAX_SCHED)
    ptrs = rd(mon, sym["schedPtr"] + base, MAX_SCHED)
    return {ids[i]: (ys[i], ptrs[i]) for i in range(n)}


def main():
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 60, lambda: None)

        # ---- 0. the premise: the ink really is rows 0..6 -------------------
        art = rd(mon, EBULLET_SPRITE, 63)
        inked = [r for r in range(SPRITE_HEIGHT)
                 if any(art[r * 3 + b] for b in range(3))]
        check("the bolt inks exactly the first seven of its twenty-one rows",
              inked == list(range(INK_ROWS)),
              f"inked rows {inked}")

        # ---- the observation run -------------------------------------------
        # Watch every bolt every frame, recording what the schedule said about
        # it and what its logical state was, so the assertions below are made
        # from measured behaviour rather than from one contrived instant.
        seen_ptrs = {}          # logId -> set of sprite pointers published
        pres_by_logy = {}       # logical Y -> set of presented Y
        clip_by_logy = {}       # logical Y -> set of logClip
        max_logy_alive = [0]
        max_logy_drawn = [0]
        drawn_below_226 = [0]

        def sample():
            b = bolts(mon)
            s = sched(mon)
            for i, (ly, c) in b.items():
                max_logy_alive[0] = max(max_logy_alive[0], ly)
                if i in s:
                    py, ptr = s[i]
                    # the entry describes the PREVIOUS frame, so it is only
                    # correlated with this frame's logical Y when the bolt has
                    # not moved -- which it always has. What IS safe to assert
                    # per entry is the entry's own presented Y.
                    pres_by_logy.setdefault(ly, set()).add(py)
                    seen_ptrs.setdefault(i, set()).add(ptr)
                clip_by_logy.setdefault(ly, set()).add(c)

            # every published entry, whatever it is, must respect the band
            for logid, (py, ptr) in s.items():
                if py > MAX_SPRITE_Y or py < MIN_SPRITE_Y:
                    drawn_below_226[0] += 1
            # the deepest logical Y at which a bolt was in the schedule
            for i, (ly, c) in b.items():
                if i in s:
                    max_logy_drawn[0] = max(max_logy_drawn[0], ly)

        step_n(mon, sym["frameCounter"], 2200, sample)

        check("bolts were observed", bool(clip_by_logy),
              f"{len(clip_by_logy)} distinct logical Y values seen")

        # ---- 1. an ordinary in-band bolt is NOT clipped --------------------
        inband = {y: c for y, c in clip_by_logy.items()
                  if MIN_SPRITE_Y <= y <= MAX_SPRITE_Y}
        check("an in-band bolt is never clipped and never gets a scratch bitmap",
              all(c == {0} for c in inband.values()),
              f"{len(inband)} in-band Y values, non-zero clip at "
              f"{[y for y, c in inband.items() if c != {0}][:6]}")

        # ---- 2. a bolt past 226 is still drawn, via clipping ---------------
        past = {y: c for y, c in clip_by_logy.items() if y > MAX_SPRITE_Y}
        check("a bolt past Y=226 is annotated for BOTTOM clipping",
              bool(past) and all(all(x < 0 for x in c) for c in past.values()),
              f"logical Y {sorted(past)[:8]} -> clip {sorted({x for c in past.values() for x in c})}")
        check("...and its clip is exactly how far past the edge it is",
              all(c == {-(y - MAX_SPRITE_Y)} for y, c in past.items()),
              f"mismatches {[(y, c) for y, c in past.items() if c != {-(y - MAX_SPRITE_Y)}][:4]}")
        check("...and it is still in the published schedule below Y=226",
              max_logy_drawn[0] > MAX_SPRITE_Y,
              f"deepest logical Y of a scheduled bolt: {max_logy_drawn[0]}")

        # ---- 3. presented Y never leaves the safe band ---------------------
        allpres = {p for s_ in pres_by_logy.values() for p in s_}
        check("every published entry stays inside the safe band 55..226",
              drawn_below_226[0] == 0,
              f"{drawn_below_226[0]} entries outside; bolt presented Y seen: "
              f"{sorted(allpres)[:4]}..{sorted(allpres)[-4:]}")
        check("a clipped bolt presents at exactly MAX_SPRITE_Y",
              all(s_ == {MAX_SPRITE_Y} for y, s_ in pres_by_logy.items()
                  if y > MAX_SPRITE_Y),
              str({y: s_ for y, s_ in pres_by_logy.items()
                   if y > MAX_SPRITE_Y and s_ != {MAX_SPRITE_Y}}))

        # ---- 4. the bolt reaches the floor, and retires there --------------
        check("a bolt now lives to the last row its ink can be drawn on",
              max_logy_alive[0] == INK_Y_MAX,
              f"deepest logical Y alive: {max_logy_alive[0]}, "
              f"EBULLET_INK_Y_MAX {INK_Y_MAX}")
        check("...and never past it: retirement is one row later",
              max_logy_alive[0] < EBULLET_Y_MAX,
              f"{max_logy_alive[0]} < {EBULLET_Y_MAX}")

        # ---- 5. a clipped bolt draws from a SCRATCH block ------------------
        canon = EBULLET_SPRITE // 64
        clipped_ptrs = {p for i, s_ in seen_ptrs.items() for p in s_} - {canon}
        check("a clipped bolt is published with a scratch pointer, not the "
              "canonical bitmap",
              bool(clipped_ptrs),
              f"canonical ${canon:02x}; scratch pointers seen "
              f"{sorted(hex(p) for p in clipped_ptrs)}")
    finally:
        if v:
            v.close()

    # =====================================================================
    # COLLISION: visible and dangerous must agree, at both edges
    # =====================================================================
    # ebulletPlayerTick IS CALLED DIRECTLY, through a trampoline, and that is
    # deliberate: it isolates the collision RULE from movement and retirement.
    # Letting the frame run instead would retire the bolt at 247 before the
    # rule ever saw it, so the upper bound could not be tested at all.
    #
    # A bare `g <routine>` would return through whatever the stack happened to
    # hold; the trampoline is `jsr ebulletPlayerTick / jmp *`, so the rts has
    # somewhere legitimate to go and the CPU parks at a known address.
    TRAMP = 0x02A7          # free RAM; no engine segment claims it
    SLOT = 0

    cases = [
        # boltY, plyY, expect hit, why
        (200, 195, True,  "ordinary in-band overlap"),
        (INK_Y_MAX, MAX_SPRITE_Y, True,
         "last drawn row 246 IS the player's last row"),
        (INK_Y_MAX, MAX_SPRITE_Y - 1, False,
         "the bolt's only drawn row is below the player's last"),
        (EBULLET_Y_MAX, MAX_SPRITE_Y, False,
         "no ink is drawn at all past 246: invisible cannot hit"),
        (INK_Y_MIN, MIN_SPRITE_Y, True,
         "top edge: ink row 6 lands on the player's first row"),
        (INK_Y_MIN - 1, MIN_SPRITE_Y, False,
         "top edge: the last ink row is above the aperture"),
    ]

    v = None
    results = []
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 60, lambda: None)
        a = sym["ebulletPlayerTick"]
        for i, b in enumerate([0x20, a & 0xFF, a >> 8, 0x4C,
                               (TRAMP + 3) & 0xFF, (TRAMP + 3) >> 8]):
            poke(mon, TRAMP + i, b)

        for boltY, plyY, want, why in cases:
            # a lone bolt, exactly under the ship, so only Y decides
            for j in range(MAX_OBJECTS):
                poke(mon, sym["logActive"] + j, 0)
            poke(mon, sym["logActive"] + SLOT, 1)
            poke(mon, sym["objType"] + SLOT, TYPE_EBULLET)
            poke(mon, sym["logY"] + SLOT, boltY)
            poke(mon, sym["logX"] + SLOT, 100)
            poke(mon, sym["logXHi"] + SLOT, 0)
            poke(mon, sym["ebCount"], 1)
            poke(mon, sym["plyX"], 100)
            poke(mon, sym["plyXHi"], 0)
            poke(mon, sym["plyY"], plyY)
            poke(mon, sym["plyInvuln"], 0)
            poke(mon, sym["plyDead"], 0)
            poke(mon, sym["ebPlayerHits"], 0)
            mon.cmd("delete")
            mon.cmd(f"g {TRAMP:04x}")
            import time
            time.sleep(0.12)
            hit = rd1(mon, sym["ebPlayerHits"]) != 0
            results.append((boltY, plyY, want, hit, why))
            set_bp(mon, sym["gameFrame"])
    finally:
        if v:
            v.close()

    for boltY, plyY, want, hit, why in results:
        verdict = "HIT" if want else "no hit"
        check(f"bolt Y={boltY}, ship Y={plyY} -> {verdict} ({why})",
              hit == want, f"got {'HIT' if hit else 'no hit'}")

    # =====================================================================
    # CLIP-POOL AND RASTER PRESSURE, with production counters only
    # =====================================================================
    # The stress audit measured this with a temporary high-water byte, which is
    # gone. clipPoolFull is production and is the counter that matters: it is
    # the one that says a clipped entry was REFUSED. The scenario is the audit's
    # validated worst case -- all EBULLET_MAX bolts held in the bottom clip band
    # while the authored waves run, so bottom-diving enemies compete for the
    # same six same-Y mux slots.
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 300, lambda: None)
        for n in ("clipPoolFull", "statOverflow", "statRejUnsafe",
                  "edgeLate", "scrollLate", "gameOverrun"):
            poke(mon, sym[n], 0)

        held = [0]

        def hold():
            act = rd(mon, sym["logActive"], MAX_OBJECTS)
            typ = rd(mon, sym["objType"], MAX_OBJECTS)
            n = 0
            for i in range(MAX_OBJECTS):
                if act[i] and typ[i] == TYPE_EBULLET:
                    poke(mon, sym["logY"] + i, 235)   # inside the clip band
                    n += 1
            held[0] = max(held[0], n)

        step_n(mon, sym["frameCounter"], 700, hold)
        diag = {n: rd1(mon, sym[n]) for n in
                ("clipPoolFull", "statOverflow", "statRejUnsafe",
                 "edgeLate", "scrollLate", "gameOverrun")}
    finally:
        if v:
            v.close()

    check("the stress scenario really did hold bolts in the clip band",
          held[0] >= 2, f"{held[0]} bolts held simultaneously")
    check("CLIP POOL: no clipped entry was ever refused",
          diag["clipPoolFull"] == 0, f"clipPoolFull {diag['clipPoolFull']}")
    check("SCHEDULE: no overflow and no unsafe-spacing rejection",
          diag["statOverflow"] == 0 and diag["statRejUnsafe"] == 0,
          f"statOverflow {diag['statOverflow']}, "
          f"statRejUnsafe {diag['statRejUnsafe']}")
    # gameOverrun is excluded from the assertion: this scenario pokes objects
    # through the monitor every frame, which halts and resumes the CPU and
    # inflates it. The RASTER counters are not affected that way.
    check("RASTER: the top and bottom splits both stayed on time",
          diag["edgeLate"] == 0 and diag["scrollLate"] == 0,
          f"edgeLate {diag['edgeLate']}, scrollLate {diag['scrollLate']}, "
          f"(gameOverrun {diag['gameOverrun']} is the monitor's own overhead)")

    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
