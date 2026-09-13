#!/usr/bin/env python3
"""Legality-window batch merging — the proof obligations for that one change.

What this proves
----------------
* the window arithmetic is right at the reuse boundary: gap 32 is still
  rejected, gap 33 gives exactly a one-raster window, and it widens by one
  raster per unit of gap above that;
* every entry's batch line lies inside ITS OWN window -- not merely inside the
  leader's -- for a large sweep of layouts, in the model AND on the machine;
* windows that overlap pairwise but share no common raster are NOT grouped,
  which is the one way a "merge if they overlap" rule silently goes wrong;
* a batch never holds two updates for one hardware slot, and never exceeds six;
* the 6502 and the two independent models agree on the batch geometry byte for
  byte, for the layouts the capacity work is judged on.

Model-only sections need no emulator and run in milliseconds. The machine
section launches exactly one VICE and reaps it on every path.

Two modes:
  default   everything -- the 4,144-layout random/shaped sweep plus all six
            machine-vs-model layouts. This is the exhaustive proof and belongs
            under `make test-renderer-full`, not the everyday gate.
  --fast    the deterministic core only: boundary arithmetic, the
            common-intersection trap, the six-entry maximum, and ONE
            machine-vs-model layout (the primary "16 spread 10" proof case).
            No random sweep. This is what `make test` runs.

The random sweep costs nothing in itself -- 4,144 layouts run in 0.06s, all
pure Python -- so --fast is not about that loop. It is about NOT launching a
second VICE instance's worth of population setup for five extra layouts that
add coverage but no new failure mode over what the boundary and trap tests
already pin down.
"""
import sys, re, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import p2_model as M
from test_p0 import (PRG, SYM, symbols, Vice, rd, set_bp, free_run,
                     LAUNCHED_PIDS, model as p0_model)
from test_p2 import poke

sym = symbols(SYM)
MUX_SLOTS, SPRITE_HEIGHT, REUSE_LEAD = M.MUX_SLOTS, M.SPRITE_HEIGHT, M.REUSE_LEAD
MIN_REUSE_GAP, HANDOFF_LINE = M.MIN_REUSE_GAP, M.HANDOFF_LINE
MIN_SPRITE_Y, MAX_SPRITE_Y = 55, 226
MAX_SCHED, MAX_BATCH = 24, 24

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def window(entries, i):
    """[earliest, latest] for accepted entry i, or None for the first six."""
    if i < MUX_SLOTS:
        return None
    return (entries[i - MUX_SLOTS]["y"] + SPRITE_HEIGHT, entries[i]["y"] - REUSE_LEAD)


def audit(entries, batches):
    """Every structural promise the batch geometry makes. Returns a fault list."""
    bad, covered = [], []
    for bi, b in enumerate(batches):
        members = list(range(b["first"], b["first"] + b["count"]))
        covered += members
        if b["count"] > MUX_SLOTS:
            bad.append(f"batch {bi} holds {b['count']} entries")
        slots = [entries[i]["slot"] for i in members]
        if len(set(slots)) != len(slots):
            bad.append(f"batch {bi} repeats a hardware slot: {slots}")
        if bi == 0:
            if b["line"] != HANDOFF_LINE:
                bad.append(f"batch 0 is not the handoff: line {b['line']}")
            continue
        for i in members:
            w = window(entries, i)
            if w is None:
                bad.append(f"entry {i} has no predecessor but is mid-screen")
                continue
            if not (w[0] <= b["line"] <= w[1]):
                bad.append(f"entry {i} line {b['line']} outside window {w}")
    if covered != list(range(len(entries))):
        bad.append("batches do not cover the accepted entries exactly once")
    return bad


# ===========================================================================
def boundaries():
    print("=== 1. window arithmetic at the reuse boundary ===")
    # Seven sprites: six at a common base, then one at base+gap. The seventh
    # reuses the first's slot, so the gap under test is the one that matters.
    base = 60
    for gap, accepted, width in ((32, False, None), (33, True, 1), (34, True, 2),
                                 (35, True, 3), (40, True, 8), (60, True, 28)):
        ys = [base] * MUX_SLOTS + [base + gap]
        sched, unsafe, margin, reuse, batches = p0_model(ys)
        got_acc = len(sched) == MUX_SLOTS + 1
        check(f"gap {gap}: {'accepted' if accepted else 'rejected'}",
              got_acc == accepted,
              f"accepted {len(sched)} of 7, margin {margin}, unsafe {unsafe}")
        if not accepted:
            continue
        e = M.build(ys)["entries"]
        lo, hi = window(e, MUX_SLOTS)
        check(f"gap {gap}: window is [{lo}, {hi}], {hi - lo + 1} raster(s) wide",
              (hi - lo + 1) == width, f"expected {width}")
    check("the accepted gap is exactly SPRITE_HEIGHT + REUSE_LEAD",
          MIN_REUSE_GAP == SPRITE_HEIGHT + REUSE_LEAD == 33)

    # 8-bit arithmetic: a predecessor at the top of the band must not wrap into
    # a false "the slot is already free".
    hi_y = MAX_SPRITE_Y
    check("predecessor Y + SPRITE_HEIGHT cannot wrap eight bits in the legal band",
          hi_y + SPRITE_HEIGHT <= 0xff, f"{hi_y} + {SPRITE_HEIGHT} = {hi_y + SPRITE_HEIGHT}")
    check("the latest legal line cannot underflow in the legal band",
          MIN_SPRITE_Y - REUSE_LEAD >= 0, f"{MIN_SPRITE_Y} - {REUSE_LEAD}")


# ===========================================================================
def common_intersection():
    print("\n=== 2. grouping needs a COMMON raster, not pairwise overlap ===")
    # Build a layout whose consecutive windows chain but share no single line.
    # Entry k's window is [Y[k-6] + SPRITE_HEIGHT, Y[k] - REUSE_LEAD], so the
    # first three Y values set the three earliest bounds and the last three set
    # the three latest bounds, independently:
    #
    #   e6: pred Y 60 -> earliest  81, Y 120 -> latest 108   [ 81, 108]
    #   e7: pred Y 80 -> earliest 101, Y 130 -> latest 118   [101, 118]
    #   e8: pred Y 95 -> earliest 116, Y 140 -> latest 128   [116, 128]
    #
    # 6-7 share 101..108 and 7-8 share 116..118, but the three together need a
    # raster that is both >= 116 and <= 108, and there is none.
    ys = [60, 80, 95, 100, 105, 110,    # the six predecessors
          120, 130, 140]                # Y - 12 gives 108, 118, 128
    s = M.build(ys)
    e, batches = s["entries"], s["batches"]
    w = [window(e, i) for i in range(MUX_SLOTS, len(e))]
    print(f"  ..  windows: {w}")
    pair67 = w[0][1] >= w[1][0] and w[1][1] >= w[0][0]
    pair78 = w[1][1] >= w[2][0] and w[2][1] >= w[1][0]
    common = max(x[0] for x in w) <= min(x[1] for x in w)
    check("the layout really is the trap shape: 6-7 and 7-8 overlap, 6-7-8 do not",
          pair67 and pair78 and not common,
          f"6-7 {pair67}, 7-8 {pair78}, common {common}")
    mid = [b for b in batches if not b.get("frame")]
    biggest = max(b["count"] for b in mid)
    check("the three are NOT grouped together", biggest < 3,
          f"largest mid-screen batch holds {biggest}")
    check("and the geometry is legal anyway", not audit(e, batches),
          str(audit(e, batches)))

    # The positive control: windows that DO share a raster are grouped.
    ys = [60, 61, 62, 63, 64, 65, 120, 121, 122]
    s = M.build(ys)
    mid = [b for b in s["batches"] if not b.get("frame")]
    check("windows with a common raster ARE grouped into one batch",
          mid and mid[0]["count"] == 3, f"{[b['count'] for b in mid]}")


# ===========================================================================
def sweep():
    print("\n=== 3. every entry's line is inside its own window, over a sweep ===")
    rng = random.Random(20260913)
    shapes = {"packed": lambda n: [60 + 2 * k for k in range(n)],
              "spacing 6": lambda n: [60 + 6 * k for k in range(n)],
              "spread 10": lambda n: [60 + 10 * k for k in range(n)],
              "spread 33": lambda n: [60 + 33 * k for k in range(n)],
              "rows of 4": lambda n: [60 + 40 * (k // 4) for k in range(n)],
              "two clusters": lambda n: [60 + 2 * k for k in range(n // 2)]
                                        + [160 + 2 * k for k in range(n - n // 2)]}
    bad, cases, sizes = [], 0, set()
    for name, f in shapes.items():
        for n in range(1, 25):
            ys = [y for y in f(n) if MIN_SPRITE_Y <= y <= MAX_SPRITE_Y]
            if not ys:
                continue
            s = M.build(ys); cases += 1
            sizes |= {b["count"] for b in s["batches"]}
            bad += [f"{name}/{n}: {x}" for x in audit(s["entries"], s["batches"])]
    for _ in range(4000):
        n = rng.randint(1, 24)
        ys = sorted(rng.randint(MIN_SPRITE_Y, MAX_SPRITE_Y) for _ in range(n))
        s = M.build(ys); cases += 1
        sizes |= {b["count"] for b in s["batches"]}
        bad += [f"random{ys}: {x}" for x in audit(s["entries"], s["batches"])]
    check(f"no structural fault in {cases} layouts", not bad, "; ".join(bad[:3]))
    check("batch sizes observed stay within one update per slot",
          max(sizes) <= MUX_SLOTS, f"sizes seen {sorted(sizes)}")
    check("the sweep actually produced multi-entry mid-screen batches",
          max(sizes) >= 3, f"largest {max(sizes)}")


# ===========================================================================
def six_entry():
    print("\n=== 4. a legal six-entry merged batch ===")
    # Six followers whose windows all contain one raster: put the six
    # predecessors together low and the six followers together high.
    ys = [60] * 6 + [120] * 6
    s = M.build(ys)
    e, batches = s["entries"], s["batches"]
    mid = [b for b in batches if not b.get("frame")]
    check("six followers merge into a single batch",
          len(mid) == 1 and mid[0]["count"] == 6, f"{[b['count'] for b in mid]}")
    check("it holds six DISTINCT hardware slots",
          len({e[i]["slot"] for i in range(6, 12)}) == 6)
    check("and it is legal for every member", not audit(e, batches),
          str(audit(e, batches)))
    # Seven cannot: entry 12's predecessor is entry 6, inside the batch.
    ys = [60] * 6 + [120] * 7
    s = M.build(ys)
    mid = [b for b in s["batches"] if not b.get("frame")]
    check("a seventh cannot join: its predecessor is in the same batch",
          max(b["count"] for b in mid) == MUX_SLOTS,
          f"{[b['count'] for b in mid]}")


# ===========================================================================
def machine(fast=False):
    print("\n=== 5. the 6502 agrees with the model, byte for byte ===")
    LAYOUTS = [("16 spread 10", [60 + 10 * k for k in range(16)]),
               ("16 spacing 6", [60 + 6 * k for k in range(16)]),
               ("16 formation 4x4", [60 + 40 * (k // 4) for k in range(16)]),
               ("16 two clusters", [60 + 2 * k for k in range(8)] + [160 + 2 * k for k in range(8)]),
               ("12 spread 10", [60 + 10 * k for k in range(12)]),
               ("16 packed 2", [60 + 2 * k for k in range(16)])]
    if fast:
        # ONE representative layout: the decisive "16 spread 10" proof case
        # from the mux capacity work (11 batches before, 5 after). The other
        # five add coverage of shapes the boundary/trap tests do not, but none
        # of them is a DIFFERENT failure mode from this one against the model.
        LAYOUTS = LAYOUTS[:1]
        print("  (fast mode: one layout, not all six)")

    def fc(mon):
        f = rd(mon, sym["frameCounter"], 2); return f[0] | (f[1] << 8)
    def call_x(mon, addr, x=0):
        mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={addr:04x}, x={x:02x}")
        bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}"); mon.cmd("delete")
    def step(mon):
        mon.cmd("delete"); b = set_bp(mon, sym["regenTick"]); prev = fc(mon)
        for _ in range(10):
            mon.cmd("x"); now = fc(mon)
            if 1 <= ((now - prev) & 0xffff) <= 4: break
            prev = now
        mon.cmd(f"delete {b}"); mon.cmd("delete")

    v = Vice(6615, PRG, warp=True)
    try:
        mon = v.mon; free_run(mon, sym["frameCounter"], 1); mon.cmd("delete")
        poke(mon, sym["joyHold"], 1); poke(mon, sym["joyState"], 0x1f)
        sb = rd(mon, sym["enemySpawnTick"])[0]
        # AND TURRET FIRE IS SWITCHED OFF, for the same reason the enemy
        # spawner is: this file poses an EXACT population at chosen Y values
        # and freezes it (objVY = 0) so that the machine's schedule and the
        # model's are comparable. A hostile projectile is an ordinary pool
        # object and it is NOT frozen -- it descends three pixels a frame, so
        # the model's expected entry count changes underneath the settle loop
        # below and the loop can never converge. It was seen as "CURRENT holds
        # 14 entries, model says 16".
        poke(mon, sym["turretFireTick"], 0x60)      # RTS
        for name, ys in LAYOUTS:
            mon.cmd("delete"); free_run(mon, sym["frameCounter"], 0.3); mon.cmd("delete")
            poke(mon, sym["enemySpawnTick"], 0x60)
            for i in range(16): call_x(mon, sym["objectFree"], i)
            poke(mon, sym["ebCount"], 0)        # freed behind ebullet.asm's back
            poke(mon, sym["plyX"], 160); poke(mon, sym["plyXHi"], 0); poke(mon, sym["plyY"], 235)
            ok_pop = True
            for k, y in enumerate(ys):
                before = {i for i in range(16) if rd(mon, sym["logActive"], 16)[i]}
                new = []
                for _ in range(6):
                    poke(mon, sym["enemySpawnTick"], sb); poke(mon, sym["enySpawnTimer"], 1)
                    step(mon); poke(mon, sym["enemySpawnTick"], 0x60)
                    new = sorted({i for i in range(16) if rd(mon, sym["logActive"], 16)[i]} - before)
                    if new: break
                if not new:
                    ok_pop = False; break
                s = new[0]
                poke(mon, sym["objVY"] + s, 0); poke(mon, sym["objVX"] + s, 0)
                poke(mon, sym["logY"] + s, y)
                poke(mon, sym["logX"] + s, 40 + (k % 6) * 44)
                poke(mon, sym["logXHi"] + s, 0); poke(mon, sym["objHP"] + s, 200)
            step(mon); step(mon)
            if not ok_pop:
                check(f"{name}: population established", False); continue

            # LET THE ADOPTED SCHEDULE CATCH UP WITH THE POPULATION.
            #
            # logY and schedCurrent are two different instants: the logical
            # arrays are current, but CURRENT is whatever was last ADOPTED, and
            # under a load that misses frames adoption lags the build. Comparing
            # a fresh population against a stale schedule reported "machine
            # 14/9, model 16/11" on a layout whose sixteen enemies were all
            # present and correct.
            live = [i for i in range(16) if rd(mon, sym["logActive"], 16)[i]]
            ly = rd(mon, sym["logY"], 32)
            actual = sorted(ly[i] for i in live)
            want_acc = M.build(actual)["accepted"]
            settled = False
            for _ in range(12):
                cur = rd(mon, sym["schedCurrent"])[0]
                if rd(mon, sym["schedEntries"] + cur)[0] == want_acc:
                    settled = True
                    break
                step(mon)
            check(f"{name}: the adopted schedule caught up with the population",
                  settled,
                  f"CURRENT holds {rd(mon, sym['schedEntries'] + rd(mon, sym['schedCurrent'])[0])[0]} "
                  f"entries, model says {want_acc}")
            if not settled:
                continue

            buf = rd(mon, sym["schedCurrent"])[0]
            base, bbase = buf * MAX_SCHED, buf * MAX_BATCH
            nb = rd(mon, sym["schedBatches"] + buf)[0]
            acc = rd(mon, sym["schedEntries"] + buf)[0]
            sy = rd(mon, sym["schedY"] + base, MAX_SCHED)
            slot = rd(mon, sym["schedSlot"] + base, MAX_SCHED)
            bl = rd(mon, sym["batchLine"] + bbase, MAX_BATCH)
            bf = rd(mon, sym["batchFirst"] + bbase, MAX_BATCH)
            bn = rd(mon, sym["batchCount"] + bbase, MAX_BATCH)
            hw = [{"y": sy[i], "slot": slot[i]} for i in range(acc)]
            hw_b = [{"line": bl[i], "first": bf[i], "count": bn[i]} for i in range(nb)]

            # MODEL THE POPULATION THE MACHINE ACTUALLY HAS, not the one this
            # test meant to place. A spawn that lands a frame late leaves an
            # enemy at its spawn Y, and comparing against the intended list
            # then reports a builder disagreement that is really a harness one.
            check(f"{name}: the intended population was placed",
                  actual == sorted(ys), f"{len(actual)} live, {actual[:8]}...")
            want = M.build(actual)
            wb = want["batches"]
            check(f"{name}: accepted and batch count match the model",
                  acc == want["accepted"] and nb == want["n_batches"],
                  f"machine {acc}/{nb}, model {want['accepted']}/{want['n_batches']}")
            same = (len(wb) == nb and all(
                wb[i]["line"] == hw_b[i]["line"] and wb[i]["first"] == hw_b[i]["first"]
                and wb[i]["count"] == hw_b[i]["count"] for i in range(nb)))
            check(f"{name}: every batch line, first and count match",
                  same, f"machine {[(b['line'], b['first'], b['count']) for b in hw_b[:6]]} "
                        f"model {[(b['line'], b['first'], b['count']) for b in wb[:6]]}")
            check(f"{name}: machine geometry is legal for every entry",
                  not audit(hw, hw_b), str(audit(hw, hw_b)))
    finally:
        v.close(); print(f"\n  launched and reaped: {LAUNCHED_PIDS}")


def main():
    fast = "--fast" in sys.argv[1:]
    print("Legality-window batch merging — model and machine proofs")
    print("(fast mode: core boundary/trap/batch-size proofs, one machine "
          "layout, no random sweep)" if fast else
          "(full mode: adds the 4,144-layout random/shaped sweep and all "
          "six machine layouts)")
    print()
    boundaries()
    common_intersection()
    if not fast:
        sweep()
    six_entry()
    machine(fast=fast)
    print()
    if fails:
        print(f"=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
        return 1
    print("=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
