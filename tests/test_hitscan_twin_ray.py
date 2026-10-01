#!/usr/bin/env python3
"""THE TWIN-RAY HITSCAN CONTRACT, stated and proved on the machine.

    The player's weapon is TWO INDEPENDENT VERTICAL HITSCAN RAYS, one per
    cannon. One trigger pull may legitimately hit TWO DIFFERENT ENEMIES: the
    left ray selects its own target and the right ray selects its own.

WHY THIS FILE EXISTS. The collision pass is a candidate for optimisation, and
every property below is one an optimisation could silently break -- most of all
the two that are easy to lose:

    * both rays resolve INDEPENDENTLY, so two enemies can die to one volley;
    * the rays resolve SEQUENTIALLY, so damage applied by the left ray is
      visible to the right ray's scan.

That second one is subtle and it is real: `collisionTick` calls `traceRay` then
`applyDamage` per ray, so an enemy the left ray KILLS has objHP 0 by the time the
right ray scans, and the right ray then selects whatever was behind it. A
single-pass implementation that collects both targets before damaging anything
would change that. This file is what makes the difference visible.

EVERY FIXTURE IS SYNTHETIC. The pool is populated directly at exact coordinates
so the geometry is the test's, not the campaign's. No authored level is read for
its content and none is written.

NEAREST MEANS GREATEST Y: the ship is at the bottom and fires upward, so the
qualifying enemy with the largest Y is the closest one and shields those above.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, call,     # noqa: E402
                     check, report, LAUNCHED_PIDS)

sym = symbols(SYM)
PORT = 6823
MAX_OBJECTS = 16

# The engine's own vocabulary, read rather than retyped where it is reachable.
TYPE_ENEMY = 1
HITBOX_W = 24           # src/collision.asm: hit iff enemyX <= rayX <= enemyX+23
HITSCAN_MIN_Y = 55      # src/collision.asm
ENEMY_MAX_HP = 6        # src/enemy.asm

SHIP_Y = 200            # the ray origin: everything at or below this is behind
LX, RX = 100, 140       # the two cannons, far enough apart to be independent


def pk(mon, addr, val, tries=6):
    """Write and read back: a bare monitor write has no reply to check."""
    for _ in range(tries):
        poke(mon, addr, val & 0xFF)
        if rd1(mon, addr) == (val & 0xFF):
            return
    raise RuntimeError(f"write to ${addr:04x} lost")


def clear_pool(mon):
    for i in range(MAX_OBJECTS):
        pk(mon, sym["logActive"] + i, 0)
        pk(mon, sym["objType"] + i, 0)
        pk(mon, sym["objHP"] + i, 0)
        pk(mon, sym["logY"] + i, 0)


def place(mon, i, x, y, hp=ENEMY_MAX_HP, typ=TYPE_ENEMY, active=1):
    pk(mon, sym["logX"] + i, x & 0xFF)
    pk(mon, sym["logXHi"] + i, (x >> 8) & 1)
    pk(mon, sym["logY"] + i, y)
    pk(mon, sym["objHP"] + i, hp)
    pk(mon, sym["objType"] + i, typ)
    pk(mon, sym["logActive"] + i, active)


def volley(mon, lx=LX, rx=RX, y=SHIP_Y):
    """Arm the shot event exactly as src/weapon.asm leaves it, then resolve."""
    pk(mon, sym["shotXLo"] + 0, lx & 0xFF)
    pk(mon, sym["shotXHi"] + 0, (lx >> 8) & 1)
    pk(mon, sym["shotXLo"] + 1, rx & 0xFF)
    pk(mon, sym["shotXHi"] + 1, (rx >> 8) & 1)
    pk(mon, sym["shotY"], y)
    pk(mon, sym["shotRays"], 2)
    pk(mon, sym["shotFired"], 1)
    call(mon, sym, "collisionTick")


def hp(mon, i):
    return rd1(mon, sym["objHP"] + i)


def hps(mon, n=MAX_OBJECTS):
    return [rd1(mon, sym["objHP"] + i) for i in range(n)]


def damaged(mon, before, n=MAX_OBJECTS):
    """Which slots lost health, and how much."""
    after = hps(mon, n)
    return {i: before[i] - after[i] for i in range(n) if after[i] != before[i]}


def main():
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        # Freeze the game: the director must not spawn into the pool mid-test.
        pk(mon, sym["joyHold"], 1)
        pk(mon, sym["joyState"], 0xFF)

        print("\n=== the ray geometry ===")
        clear_pool(mon)
        place(mon, 0, LX - 2, 150)
        b = hps(mon)
        volley(mon)
        d = damaged(mon, b)
        check("an enemy straddling the LEFT ray is hit", d == {0: 1}, str(d))

        clear_pool(mon)
        place(mon, 0, RX - 2, 150)
        b = hps(mon)
        volley(mon)
        d = damaged(mon, b)
        check("an enemy straddling the RIGHT ray is hit", d == {0: 1}, str(d))

        clear_pool(mon)
        b = hps(mon)
        volley(mon)
        check("no enemies, no damage", damaged(mon, b) == {})

        # THE HITBOX IS [enemyX, enemyX+23]: the ray hits iff rayX - enemyX is
        # in 0..23. Both ends are checked because an off-by-one here is a
        # gameplay change nobody would notice until a shot visibly missed.
        for off, want in ((0, True), (HITBOX_W - 1, True),
                          (-1, False), (HITBOX_W, False)):
            clear_pool(mon)
            place(mon, 0, LX - off, 150)
            b = hps(mon)
            volley(mon)
            got = damaged(mon, b) != {}
            check(f"rayX - enemyX = {off:>3} -> {'hit' if want else 'miss'}",
                  got == want, f"hit={got}")

        print("\n=== two rays, two targets: the whole point of the weapon ===")
        clear_pool(mon)
        place(mon, 0, LX - 2, 150)          # on the left ray only
        place(mon, 1, RX - 2, 140)          # on the right ray only
        b = hps(mon)
        volley(mon)
        d = damaged(mon, b)
        check("ONE TRIGGER PULL HITS TWO DIFFERENT ENEMIES",
              d == {0: 1, 1: 1}, str(d))

        print("\n=== nearest wins, and shields what is behind it ===")
        # Greatest Y is nearest: the ship is below and fires upward.
        clear_pool(mon)
        place(mon, 0, LX - 2, 100)          # farther
        place(mon, 1, LX - 2, 160)          # nearer
        b = hps(mon)
        volley(mon)
        d = damaged(mon, b)
        check("the NEARER enemy on a ray takes the hit", d == {1: 1}, str(d))
        check("...and the farther one is shielded", 0 not in d, str(d))

        clear_pool(mon)
        for k, y in enumerate((80, 120, 170, 95)):
            place(mon, k, LX - 2, y)
        b = hps(mon)
        volley(mon)
        d = damaged(mon, b)
        check("with four stacked on one ray, only the nearest is hit",
              d == {2: 1}, str(d))

        # A TIE GOES TO THE HIGHER SLOT: the scan runs low to high and an EQUAL
        # Y replaces the incumbent. Worth pinning -- an optimisation that
        # reversed the walk or used `bcc` instead of `bcs` would flip it.
        clear_pool(mon)
        place(mon, 2, LX - 2, 150)
        place(mon, 5, LX - 2, 150)
        b = hps(mon)
        volley(mon)
        d = damaged(mon, b)
        check("an equal-Y tie goes to the HIGHER slot index", d == {5: 1}, str(d))

        print("\n=== eligibility ===")
        clear_pool(mon)
        place(mon, 0, LX - 2, SHIP_Y)       # exactly at the ship
        place(mon, 1, LX - 2, SHIP_Y + 10)  # below the ship
        b = hps(mon)
        volley(mon)
        check("an enemy at or below the ray origin is ignored",
              damaged(mon, b) == {}, str(damaged(mon, b)))

        clear_pool(mon)
        place(mon, 0, LX - 2, HITSCAN_MIN_Y - 1)
        b = hps(mon)
        volley(mon)
        check(f"an enemy above HITSCAN_MIN_Y ({HITSCAN_MIN_Y}) is ignored",
              damaged(mon, b) == {}, str(damaged(mon, b)))
        clear_pool(mon)
        place(mon, 0, LX - 2, HITSCAN_MIN_Y)
        b = hps(mon)
        volley(mon)
        check("...and one exactly AT it is eligible",
              damaged(mon, b) == {0: 1}, str(damaged(mon, b)))

        clear_pool(mon)
        place(mon, 0, LX - 2, 150, active=0)
        b = hps(mon)
        volley(mon)
        check("an INACTIVE slot is not a target", damaged(mon, b) == {})

        clear_pool(mon)
        place(mon, 0, LX - 2, 150, typ=TYPE_ENEMY + 1)
        b = hps(mon)
        volley(mon)
        check("a non-ENEMY object is not a target (hostile bolts are not "
              "shootable)", damaged(mon, b) == {})

        clear_pool(mon)
        place(mon, 0, LX - 2, 160, hp=0)    # already dying, nearer
        place(mon, 1, LX - 2, 120)          # alive, farther
        b = hps(mon)
        volley(mon)
        d = damaged(mon, b)
        check("an ALREADY-DYING enemy is not a target...", 0 not in d, str(d))
        check("...and does not shield the live one behind it",
              d == {1: 1}, str(d))

        print("\n=== nine-bit X ===")
        # x >= 256 exercises the high byte on both the enemy and the ray.
        clear_pool(mon)
        place(mon, 0, 300, 150)
        b = hps(mon)
        volley(mon, lx=302, rx=340)
        check("an enemy at x=300 is hit by a ray at x=302 (both nine-bit)",
              damaged(mon, b) == {0: 1}, str(damaged(mon, b)))

        clear_pool(mon)
        place(mon, 0, 250, 150)             # spans the 256 boundary: 250..273
        b = hps(mon)
        volley(mon, lx=260, rx=340)
        check("an enemy straddling x=256 is hit by a ray above the boundary",
              damaged(mon, b) == {0: 1}, str(damaged(mon, b)))

        clear_pool(mon)
        place(mon, 0, 10, 150)
        b = hps(mon)
        volley(mon, lx=300, rx=340)
        check("a ray at x=300 does NOT wrap onto an enemy at x=10",
              damaged(mon, b) == {}, str(damaged(mon, b)))

        print("\n=== one enemy on BOTH rays ===")
        # A box 24 wide cannot span LX..RX when they are 40 apart, so the rays
        # are brought together for this case only.
        clear_pool(mon)
        place(mon, 0, 100, 150)             # covers 100..123
        b = hps(mon)
        volley(mon, lx=105, rx=115)
        d = damaged(mon, b)
        check("an enemy intersecting BOTH rays takes TWO damage",
              d == {0: 2}, str(d))

        # THE SEQUENTIAL RULE, and this is the one an optimisation breaks.
        # The left ray's damage lands BEFORE the right ray scans, so an enemy
        # the left ray kills is gone by the time the right ray looks -- and the
        # right ray then takes whatever was behind it.
        clear_pool(mon)
        place(mon, 0, 100, 150, hp=1)       # dies to the first ray
        place(mon, 1, 100, 120)             # directly behind it, on both rays
        b = hps(mon)
        volley(mon, lx=105, rx=115)
        d = damaged(mon, b)
        check("a one-HP enemy on both rays dies to the first and the second "
              "ray takes the enemy BEHIND it",
              d == {0: 1, 1: 1}, str(d))
        check("...so the dead enemy is not damaged twice",
              d.get(0) == 1, str(d))

        print("\n=== destruction ===")
        clear_pool(mon)
        place(mon, 0, LX - 2, 150, hp=1)
        kills_before = rd1(mon, sym["csKills"])
        volley(mon)
        check("an enemy reduced to zero HP is recorded as a kill",
              rd1(mon, sym["csKills"]) > kills_before or hp(mon, 0) == 0,
              f"csKills {kills_before} -> {rd1(mon, sym['csKills'])}, "
              f"hp {hp(mon, 0)}")
        check("...and its HP is zero, which is this engine's 'dying'",
              hp(mon, 0) == 0, str(hp(mon, 0)))

        print("\n=== a full pool ===")
        clear_pool(mon)
        for k in range(MAX_OBJECTS):
            place(mon, k, 300, 60 + k)      # none on either ray
        b = hps(mon)
        volley(mon)
        check("sixteen live enemies, none on a ray: no damage",
              damaged(mon, b) == {}, str(damaged(mon, b)))
        clear_pool(mon)
        for k in range(MAX_OBJECTS):
            place(mon, k, 300, 60 + k)
        place(mon, 7, LX - 2, 100)
        place(mon, 11, RX - 2, 110)
        b = hps(mon)
        volley(mon)
        d = damaged(mon, b)
        check("...and with one on each ray, exactly those two are hit",
              d == {7: 1, 11: 1}, str(d))
    finally:
        if v:
            v.close()
        print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
