#!/usr/bin/env python3
"""The P4 independent model: dynamic Y sorting, and the P4 fixture set.

The comparator and the admission rules are stated here from the rules, not from
the 6502. `tools/gen_p4_fixtures.py` emits the engine's fixture records from the
trajectories declared below, exactly as P3 does, and `tests/test_p4.py` checks
the running machine against the derived expectations.

What P4 adds to the P3 model is IDENTITY. Once a sorter exists, "accepted entry
3" is a position, not a sprite. Every expectation below is therefore stated in
logical sprite IDs: which IDs were sorted into what order, which IDs were
accepted, which ID is a given entry's same-slot predecessor.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import p2_model as M
import p3_model as P3
from p3_model import Sprite, Fixture, FK_STATIC, FK_MOTION

MAX_LOGICAL = P3.MAX_LOGICAL
MAX_SCHED = M.MAX_SCHED
MIN_REUSE_GAP = M.MIN_REUSE_GAP
MUX_SLOTS = M.MUX_SLOTS

P4_FIRST = 24


def sorted_ids(ys):
    """The documented comparator: Y ascending, then logical ID ascending."""
    return M.sorted_order(ys)


class SortFixture(Fixture):
    """A P3 fixture whose schedule is built from the SORTED id order."""

    def build(self):
        ys, xs = self.ys(), self.xs()
        return M.build(ys, 0, xs, order=sorted_ids(ys))

    def sorted(self):
        return sorted_ids(self.ys())


def _sortstatic():
    """Static, deliberately scrambled logical storage order.

    The Y values resolve to P2's six-entry merged geometry -- six leaders at
    60..65 and six reusers all at 98 -- but the logical IDs they are stored
    against alternate high and low, and the six reusers are a six-way equal-Y
    tie. If the builder scanned storage order instead of sorted order, the very
    first reuse test would compare against the wrong predecessor.

        storage:  ID 0 1 2 3 4 5 6 7 8 9 10 11
        Y:          98 61 98 60 98 64 98 62 98 63 98 65
        expected sorted IDs: 3 1 7 9 5 11 0 2 4 6 8 10
    """
    ys = [98, 61, 98, 60, 98, 64, 98, 62, 98, 63, 98, 65]
    xs = [40, 60, 90, 120, 140, 180, 210, 40, 264, 100, 300, 160]
    return [Sprite(ys[i], xs[i]) for i in range(12)]


def _cross2():
    """The smallest crossing: two sprites swapping Y order, with an exact tie.

        A (ID 0) 90 -> 102      B (ID 1) 102 -> 90
        they meet at 96, where the tie-break puts ID 0 first.

    Two sprites means no slot reuse, so this isolates one thing: identity
    surviving a sorted-order change. A moves from accepted index 0 to 1 and
    therefore from hardware slot 2 to slot 3 WITHOUT changing identity, which
    is the property the whole checkpoint exists to establish.
    """
    return [Sprite(90, 120, yvel=+1, ylo=90, yhi=102),
            Sprite(102, 200, yvel=-1, ylo=90, yhi=102)]


def _cross6():
    """Six interleaving sprites over six static reusers.

    Even IDs sweep down, odd IDs sweep up, all sharing one Y band, so adjacent
    pairs cross repeatedly and the whole group reorders continuously. The six
    reusers below them are static, so every change in their same-slot
    predecessor is caused purely by the crossings above.
    """
    s = [Sprite(70 + 10 * i, 40 + 34 * (i % 6),
                yvel=(+1 if i % 2 == 0 else -1), ylo=70, yhi=120)
         for i in range(6)]
    s += [Sprite(155, 30 + 36 * i) for i in range(6)]
    return s


def _predchange():
    """A crossing that changes WHICH sprite is a reuser's predecessor.

    IDs 0 and 1 swap around Y 61 while everything else stands still. The reuser
    (ID 6) never moves, but accepted entry 0 -- its same-slot predecessor --
    alternates between logical ID 0 and logical ID 1.

    Both states are comfortably legal (gaps 36..38), so admission does NOT
    change: this fixture isolates predecessor IDENTITY from admission, which
    SORTSHAPE then varies deliberately.
    """
    s = [Sprite(60, 40, yvel=+1, ylo=60, yhi=62),
         Sprite(62, 90, yvel=-1, ylo=60, yhi=62)]
    s += [Sprite(70 + i, 130 + 30 * i) for i in range(4)]
    s += [Sprite(98, 60)]
    return s


def _sortshape():
    """A crossing that changes ADMISSION, without the affected sprite moving.

    ID 5 sweeps down past the static leaders, so accepted entry 0 alternates
    between ID 5 (Y 60..62) and ID 0 (Y 63). The reuser ID 6 sits at a fixed
    Y 94 and never moves at all -- but its gap against entry 0 is 34, 33, 32 or
    31 depending on who entry 0 currently is, so it is admitted or rejected by
    someone else's movement.

    That admission change then reshapes everything below it: IDs 7..11 shift by
    one accepted index, which moves them onto different physical slots and
    changes the complete $D010.
    """
    s = [Sprite(63 + i, 40 + 30 * (i % 3)) for i in range(5)]      # IDs 0..4
    s += [Sprite(60, 200, yvel=+1, ylo=60, yhi=66)]                # ID 5 sweeps
    s += [Sprite(94, 160)]                                          # ID 6 fixed
    # Alternating MSB, so an accepted-index shift is also a $D010 change.
    s += [Sprite(130, 264 if i % 2 else 60) for i in range(5)]      # IDs 7..11
    return s


def _tie6():
    """Six equal-Y sprites arriving from the opposite end of storage.

        storage:  IDs 0..5  at Y 98      IDs 6..11 at Y 60..65
        sorted:   6 7 8 9 10 11 | 0 1 2 3 4 5

    A complete block swap, and the six-way tie resolves by ascending logical ID
    onto hardware slots 2..7 in that order. The result must be P2's six-entry
    merged batch, at P2's cost.
    """
    tie_x = [40, 264, 100, 300, 160, 336]
    s = [Sprite(98, tie_x[i]) for i in range(6)]
    s += [Sprite(60 + i, 40 + 34 * i) for i in range(6)]
    return s


def _sortcap():
    """More sprites than the schedule can hold, with the order changing.

    FOUR MERGED GROUPS plus a crossing pair that cannot fit, and the shape took
    three attempts because it kept measuring something other than capacity.

    (1) 30 sprites at pitch 7 swinging +/-4 put consecutive accepted sprites as
        little as 3 rasters apart, so their batches were armed 3 rasters apart
        while a single-entry batch takes about 5 to execute. The executor's
        late-recovery path chained batches inside one interrupt -- 17 sprite
        writes in one handler invocation, 1078 cycles -- and a frame IRQ was
        eventually serviced at raster 194 instead of 250. Reported here as a
        builder admission gap -- no rule for how close two BATCHES may be --
        which was the WRONG diagnosis. The cause was irqHandler acknowledging
        $d019 on entry and arming the next compare several lines later, so a
        latch raised mid-handler survived the rti and re-entered with curBatch
        already back at 0, running the frame transaction mid-display. Fixed in
        exArm; see reports/fix16-maxcap-visual-corruption-forensic.md. Never a
        sorter fault, and never an admission gap.

    (2) 13 crossing pairs in 8-raster bands fixed the spacing but still needed
        nineteen mid-screen batches, and still went late.

    (3) This. Twenty-four accepted sprites as four six-way ties, so the whole
        frame costs FOUR batches -- the least a 24-sprite schedule can cost --
        and statLate is zero. The two sprites that cannot fit are a crossing
        pair below the display, so the sorted order still changes every other
        frame at positions 24 and 25 while the accepted set stays exactly the
        first 24. That is precisely what P4-G asks: reordering must not make
        overflow nondeterministic.

    What this fixture then MEASURES, and what the report says plainly, is that
    26 logical sprites re-sorted and rebuilt every frame is past the main
    thread's budget: publication skips appear even at four batches. That is an
    engine capability ceiling that P4 is the first checkpoint to reach -- P3's
    MAXCAP had 30 sprites but was static, so it was built once -- and it is not
    caused by the sorter, which is about 7% of the preparation span.
    """
    out = []
    for g in range(4):                          # 24 accepted, as four ties
        y = 60 + 38 * g
        out += [Sprite(y, 30 + 30 * (i % 7)) for i in range(6)]
    # Two that cannot fit, crossing each other below the display.
    out.append(Sprite(220, 100, yvel=+4, ylo=220, yhi=228))
    out.append(Sprite(228, 200, yvel=-4, ylo=220, yhi=228))
    return out


FIXTURES = {
    24: SortFixture("SORTSTATIC", _sortstatic(), kind=FK_MOTION,
                    note="scrambled static logical order"),
    25: SortFixture("CROSS2", _cross2(), note="two-sprite adjacent crossing"),
    26: SortFixture("CROSS6", _cross6(), note="six interleaving over six reusers"),
    27: SortFixture("PREDCHANGE", _predchange(), note="crossing changes the i-6 predecessor"),
    28: SortFixture("SORTSHAPE", _sortshape(), note="crossing changes admission"),
    29: SortFixture("TIE6", _tie6(), kind=FK_MOTION, note="equal-Y tie, merged batch"),
    30: SortFixture("SORTCAP", _sortcap(), note="dynamic order at/over MAX_SCHED"),
}
FIXTURE_COUNT = P4_FIRST + len(FIXTURES)


def audit(frames=240):
    """Per-frame invariants P4 must hold, independent of the engine."""
    problems = []
    for idx, fx in sorted(FIXTURES.items()):
        try:
            fx.check()
        except AssertionError as e:
            problems.append(f"{fx.name}: {e}")
            continue
        for f, ys, xs, sched in fx.frames(frames):
            order = sorted_ids(ys)
            # the contract the sorter must satisfy
            if sorted(order) != list(range(len(ys))):
                problems.append(f"{fx.name} f{f}: order is not a permutation")
                break
            if any(ys[order[i]] > ys[order[i + 1]] for i in range(len(order) - 1)):
                problems.append(f"{fx.name} f{f}: not ascending in Y")
                break
            # ties must be broken by ascending ID
            for i in range(len(order) - 1):
                if ys[order[i]] == ys[order[i + 1]] and order[i] > order[i + 1]:
                    problems.append(f"{fx.name} f{f}: tie not broken by ID")
                    break
            if sched["over_batch"]:
                problems.append(f"{fx.name} f{f}: batch overflow")
                break
            for e in sched["entries"]:
                if e["gap"] is not None and e["gap"] < MIN_REUSE_GAP:
                    problems.append(f"{fx.name} f{f}: entry {e['acc']} gap {e['gap']}")
                    break
        # Y order is NOT required to be stable here -- crossing is the point.
    return problems


def reorder_frames(fx, frames=240):
    """How often the sorted order actually changes, and the worst single change."""
    prev, changes, worst = None, 0, 0
    for f, ys, xs, s in fx.frames(frames):
        o = sorted_ids(ys)
        if prev is not None and o != prev:
            changes += 1
            worst = max(worst, sum(1 for a, b in zip(o, prev) if a != b))
        prev = o
    return changes, worst


if __name__ == "__main__":
    bad = audit()
    print("audit:", "clean" if not bad else "\n  ".join([""] + bad))
    for idx, fx in sorted(FIXTURES.items()):
        fx.reset()
        c = fx.build()
        ch, worst = reorder_frames(fx, 120)
        shapes = set()
        for f, ys, xs, s in fx.frames(120):
            shapes.add((s["accepted"], s["n_batches"], s["max_mid_batch"],
                        tuple(b["d010"] for b in s["batches"])))
        print(f"{idx:2d} {fx.name:<11s} n={len(fx.sprites):2d} acc={c['accepted']:2d} "
              f"ovf={c['overflow']} batches={c['n_batches']:2d} maxMid={c['max_mid_batch']} "
              f"reorders={ch:3d}/120 maxdelta={worst:2d} shapes={len(shapes)}")
        print(f"   {'':11s} sorted@0 = {fx.sorted()}")
    sys.exit(1 if bad else 0)
