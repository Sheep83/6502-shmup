#!/usr/bin/env python3
"""Aimed projectiles must MOVE at the velocity the aim path calculated.

WHY THIS FILE EXISTS, given tests/test_aimed_fire.py already covers aimed fire.
That file reads objVX and objVY -- the STORED velocity -- and computes the
shot's speed as sqrt(vx^2 + vy^2) from those bytes. Every one of its claims is
therefore true of the numbers the aim path wrote and says nothing about the
numbers the projectile flies by. ebulletTick consumed objVX for the horizontal
step and a CONSTANT for the vertical one, so the steepest slope stored a
vertical step of 2 and moved 3: the speed-normalisation the table exists for
never reached the screen, and the stored-value test stayed green throughout.

So this file measures POSITION. It breaks on ebulletTick -- which runs once per
frame per projectile, before the move -- and differences consecutive positions
of the same slot. That is an observed displacement, not an inferred one.

Constraint #4: the machine is free-running production code. Nothing is poked
except the player's X (to choose which aim bucket the enemy fires into) and the
wave definitions' firing mode, both of which are ordinary authored state.

One VICE launch per player position.
"""
import re, sys, collections, math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import campaign_data as CD                                       # noqa: E402
from harness import (PRG, SYM, symbols, Vice, rd1, poke, set_bp,  # noqa: E402
                     read16,
                     check, report)

sym = symbols(SYM)

MAX_OBJECTS = 16
TYPE_EBULLET = 2
PORT = 6602
# HOW A WAVE FIRES IS A TRIGGER FIELD. It used to be bits 4-5 of the wave
# DEFINITION's byte 7, and this file forced the mode by poking that byte; byte 7
# is now reserved and zero, and the mode lives in the trigger list's own
# trigFireMode column (src/encounter_format.asm). Poking the old place stopped
# doing anything, which is exactly what this note exists to stop happening
# silently again.
LEVELPKG_TRIGN = CD.TRIGN_ADDR   # the live trigger count; src/levelpkg.asm
TRIG_FIRE_DOWN, TRIG_FIRE_AIMED = 0, 1
EBULLET_VX_MAX = 2
EBULLET_VY_MAX = 3            # src/ebullet.asm: the fastest a bolt ever falls
EXPECTED_VY = {0: 3, 1: 3, 2: 2}        # src/ebullet.asm ebulletAimVY
TICKS = 600
POSITIONS = (32, 150, 300)              # far left, middle, far right

REG = re.compile(r"^\.;[0-9a-f]{4}\s+[0-9a-f]{2}\s+([0-9a-f]{2})", re.M)


def signed(b):
    return b - 256 if b > 127 else b


def flights_at(player_x):
    """Every projectile flight seen with the ship held at player_x.

    Returns [[(x, y, vx, vy), ...], ...], one list per flight, in tick order.
    """
    v = None
    seq = collections.defaultdict(list)
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        for t in range(rd1(mon, LEVELPKG_TRIGN)):
            poke(mon, sym["waveTrigFireMode"] + t, TRIG_FIRE_AIMED)

        def hold_ship():
            poke(mon, sym["plyX"], player_x & 0xFF)
            poke(mon, sym["plyXHi"], (player_x >> 8) & 1)

        hold_ship()
        bp = set_bp(mon, sym["ebulletTick"])
        for _ in range(TICKS):
            mon.cmd("x")
            m = REG.search(mon.cmd("registers"))
            if not m:
                continue
            s = int(m.group(1), 16)
            if s >= MAX_OBJECTS:
                continue
            hold_ship()                 # the bucket must not change mid-flight
            # EVERY SAMPLE IS PINNED TO A FRAME, and this is not optional.
            #
            # harness.step_n() warns that `mon.cmd("x")` returns on a prompt
            # echo rather than on the actual stop, so a dropped or duplicated
            # reply hands back the SAME frame twice. Without this guard that
            # duplicate becomes a displacement of zero, and the file then
            # reports "steps seen [0, 3]" as though a bolt had stopped moving.
            # It happened: this test failed exactly that way on a loaded host,
            # having been written without the check the harness documents.
            fr = read16(mon, sym["frameCounter"])
            if seq[s] and seq[s][-1][4] == fr:
                continue                # the same frame twice: not a new sample
            seq[s].append((
                rd1(mon, sym["logX"] + s) | (rd1(mon, sym["logXHi"] + s) << 8),
                rd1(mon, sym["logY"] + s),
                signed(rd1(mon, sym["objVX"] + s)),
                rd1(mon, sym["objVY"] + s),
                fr,
            ))
        mon.cmd(f"delete {bp}")
    finally:
        if v:
            v.close()

    # A LIVE BOLT NEVER HAS objVY ZERO. ebulletSpawn writes EBULLET_VY or the
    # steep 2 before the slot is activated (src/ebullet.asm ebulletAimVY), so a
    # sample carrying zero is a slot that has been freed and not yet refilled --
    # not a projectile that stopped. Dropping those is what stops a dead slot
    # being reported as a bolt moving 0 pixels a frame.
    for s in list(seq):
        seq[s] = [r for r in seq[s] if r[3] != 0]

    out = []
    for s, rows in seq.items():
        if not rows:
            continue
        cur = [rows[0]]
        for a, b in zip(rows, rows[1:]):
            # A SLOT REUSED BY A NEW BOLT restarts higher up, changes slope --
            # or restarts LOWER DOWN, which the first two tests miss. A bolt
            # falls at most EBULLET_VY pixels a frame, so a larger gap is a
            # different projectile in the same slot and not a teleport. That
            # case only began appearing once this file drove every authored
            # appearance into aimed fire, which put far more bolts through the
            # same few slots.
            if b[1] < a[1] or b[2] != a[2] or (b[1] - a[1]) > EBULLET_VY_MAX:
                out.append(cur)
                cur = [b]
            else:
                cur.append(b)
        out.append(cur)
    return [f for f in out if len(f) >= 3]


all_flights = []
for px in POSITIONS:
    all_flights += flights_at(px)

check("bolts were observed in flight", bool(all_flights),
      f"{len(all_flights)} flights of 3+ ticks")

by_bucket = collections.defaultdict(list)
for f in all_flights:
    by_bucket[abs(f[0][2])].append(f)

check("every quantised slope was exercised",
      set(by_bucket) == {0, 1, 2}, f"buckets seen {sorted(by_bucket)}")

# ---- THE ASSERTION: measured motion == the velocity the aim path stored ----
bad_y, bad_x = [], []
for a, flights in sorted(by_bucket.items()):
    for f in flights:
        for p, q in zip(f, f[1:]):
            if q[1] - p[1] != f[0][3]:
                bad_y.append((a, f[0][3], q[1] - p[1]))
            if abs(q[0] - p[0]) != a:
                bad_x.append((a, abs(q[0] - p[0])))

check("VERTICAL: every frame advances by the slope's OWN stored objVY, "
      "not a constant",
      not bad_y,
      "ok" if not bad_y else
      f"{len(bad_y)} frames disagreed, e.g. |VX|={bad_y[0][0]} "
      f"stored VY={bad_y[0][1]} but moved {bad_y[0][2]}")

check("HORIZONTAL: every frame advances by |objVX|",
      not bad_x,
      "ok" if not bad_x else f"{len(bad_x)} frames disagreed, e.g. {bad_x[0]}")

for a, flights in sorted(by_bucket.items()):
    dys = {q[1] - p[1] for f in flights for p, q in zip(f, f[1:])}
    check(f"|VX|={a}: measured vertical step is the authored {EXPECTED_VY[a]}",
          dys == {EXPECTED_VY[a]}, f"{len(flights)} flights, steps seen {sorted(dys)}")

# ---- the speed the authored table actually asks for -----------------------
# NOT A TOLERANCE. An earlier draft of this file asserted "within 10%", a
# threshold lifted from tests/test_aimed_fire.py -- and the authored table does
# not meet it: [3,3,2] gives 3.00, 3.16 and 2.83 px/frame, an 11.7% spread. A
# gate the design cannot pass is a gate that will one day be "fixed" by
# changing the design, so the claim here is exact instead: each bucket must fly
# at the speed ITS OWN authored entry implies. Whether 11.7% is the right arc
# is a tuning question for a human, and is reported rather than asserted.
speeds = {}
for a, flights in sorted(by_bucket.items()):
    dys = [q[1] - p[1] for f in flights for p, q in zip(f, f[1:])]
    measured = math.hypot(a, sum(dys) / len(dys))
    want = math.hypot(a, EXPECTED_VY[a])
    speeds[a] = round(measured, 2)
    check(f"|VX|={a}: MEASURED speed is the authored "
          f"hypot({a},{EXPECTED_VY[a]}) = {want:.2f} px/frame",
          abs(measured - want) < 0.005, f"measured {measured:.2f}")
lo, hi = min(speeds.values()), max(speeds.values())
print(f"\n  note: the authored arc spans {lo}..{hi} px/frame "
      f"({(hi - lo) / lo * 100:.1f}% spread) -- a design value, not a defect")

report("aimed projectile velocity consumption")
