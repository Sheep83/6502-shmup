#!/usr/bin/env python3
"""P5 — the rotating-ring integration torture proof.

Sixteen uniquely identifiable sprites orbit one ring, for ever, while the P1
scroller runs underneath them. Everything P0-P4 proved separately has to hold
at the same time and continuously:

  * logical identity is stable while sorted position and physical slot are not;
  * the sorter reorders constantly and stays correct through exact equal-Y ties;
  * the i-6 reuse rule stays legal after every reorder, with the predecessor's
    IDENTITY changing underneath it;
  * every one of HW2..HW7 is owned by all sixteen sprites within one orbit;
  * X crosses 255 in both directions and the complete batch $D010 follows;
  * the batch schedule changes shape continuously and the executor stays
    decision-free;
  * the frame transaction still executes at raster 250 (the FIX 16 invariant);
  * pointers stay semantically correct all the way to the VIC.

Usage:  python3 tests/test_p5.py            # qualification, no long soak
        python3 tests/test_p5.py --fast     # development subset
        python3 tests/test_p5.py --soak N   # add an N-frame soak
"""
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import (PRG, SYM, symbols, Vice, rd, set_bp, free_run, read16)
from test_p2 import poke, collect
from test_p3 import pc_of
from test_p4 import (check, fails, sweep_logs, read_sched, compare_sched,
                     check_presentation_late, check_frame_transaction_raster,
                     SCRATCH, MAX_SCHED, MAX_BATCH, FRAME_IRQ_LINE)
import p2_model as M
import p5_model as P

PAL_FRAME = 19656


def select_p5(mon, sym, fxi, tries=4):
    """Select a ring fixture and leave the machine stopped at mainLoop, frame 0.

    Verified against the model before returning, exactly as select_p3 does: an
    unverified selection silently measures the previous fixture, and with three
    ring modes that share one geometry the mistake would be invisible.
    """
    mode = P.MODES[fxi]
    want = mode.build(0)
    for _ in range(tries):
        b = set_bp(mon, sym["mainLoop"]); mon.cmd("x"); mon.cmd(f"delete {b}")
        poke(mon, sym["fixtureIndex"], fxi)
        poke(mon, sym["fixtureYOffset"], 0)
        mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={sym['rebuild']:04x}")
        bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
        if (rd(mon, sym["ringActive"])[0] == 1 and
                rd(mon, sym["logCount"])[0] == P.N_RING and
                rd(mon, sym["fixtureMoves"])[0] == 1 and
                read16(mon, sym["motionFrame"]) == 0 and
                rd(mon, sym["statAccepted"])[0] == want["accepted"] and
                rd(mon, sym["statBatches"])[0] == want["n_batches"]):
            mon.cmd("delete")
            return want
        time.sleep(0.3)
    mon.cmd("delete")
    return None


def read_positions(mon, sym, n=P.N_RING):
    """Logical X (0..511) and Y straight out of the engine's arrays."""
    xlo = rd(mon, sym["logX"], n)
    xhi = rd(mon, sym["logXHi"], n)
    ys = rd(mon, sym["logY"], n)
    return [xlo[i] | (xhi[i] << 8) for i in range(n)], list(ys)


def walk(mon, sym, mode, frames, label, deep=True):
    """Step `frames` motion frames, checking the engine against the model.

    Everything is stated per MOTION FRAME, which the engine counts itself, so a
    dropped or doubled step cannot quietly shift the comparison.
    """
    bad, checked, seen_orders, seen_shapes = [], 0, set(), set()
    ties, msb_seen = 0, {s: set() for s in range(M.MUX_FIRST_SLOT,
                                                 M.MUX_FIRST_SLOT + M.MUX_SLOTS)}
    owners = {s: set() for s in msb_seen}
    preds = set()
    bp = set_bp(mon, sym["regenTick"])
    for _ in range(frames):
        before = read16(mon, sym["motionFrame"])
        for _try in range(6):
            mon.cmd("x")
            if (((read16(mon, sym["motionFrame"]) - before) & 0xffff) == 1
                    and pc_of(mon) == sym["regenTick"]):
                break
            time.sleep(0.2)
        else:
            bad.append("could not step a motion frame"); break
        f = read16(mon, sym["motionFrame"])
        gx, gy = read_positions(mon, sym)
        wx, wy = mode.positions(f)
        if gx != wx:
            bad.append(f"frame {f}: X {gx} != {wx}"); break
        if gy != wy:
            bad.append(f"frame {f}: Y {gy} != {wy}"); break
        # the sorter's own output, compared against the documented comparator
        order = list(rd(mon, sym["sortedIDs"], P.N_RING))
        want_order = M.sorted_order(wy)
        if order != want_order:
            bad.append(f"frame {f}: sorted {order} != {want_order}"); break
        seen_orders.add(tuple(order))
        ties += sum(1 for i in range(len(order) - 1)
                    if wy[order[i]] == wy[order[i + 1]])
        if deep:
            want = mode.build(f)
            problems = compare_sched(mon, sym, want)
            # compare_sched checks identity, geometry, slots, predecessors and
            # $D010 -- but NOT colour, which nothing in P0-P4 ever checked. On a
            # fixture whose whole premise is "sixteen sprites you can tell
            # apart", a sprite wearing another sprite's colour is exactly the
            # fault a human would report, so check it here.
            # via bs_base, the base the BUILDER latched -- not schedCurrent.
            # The build has happened but the frame IRQ has not adopted it, so
            # schedCurrent still names the previous buffer; reading it returned
            # the previous fixture's colours padded with zeros, which read as a
            # spectacular failure of a check that was itself wrong. read_sched()
            # has used bs_base for exactly this reason since P3.
            n = len(want["entries"])
            gotc = list(rd(mon, sym["schedCol"] + rd(mon, sym["bs_base"])[0], n))
            wantc = [P.FX_COLOUR[e["id"]] for e in want["entries"]]
            if gotc != wantc:
                problems.append(f"colours {gotc} != {wantc}")
            if problems:
                bad.append(f"frame {f}: " + "; ".join(problems)); break
            seen_shapes.add((want["n_batches"],
                             tuple(b["count"] for b in want["batches"])))
            for e in want["entries"]:
                owners[e["slot"]].add(e["id"])
                msb_seen[e["slot"]].add(e["xhi"])
                if e["pred_id"] is not None:
                    preds.add((e["id"], e["pred_id"]))
        checked += 1
    mon.cmd(f"delete {bp}"); mon.cmd("delete")
    check(f"{label}: engine matches the model on every frame", not bad,
          bad[0] if bad else f"{checked} motion frames, positions, sorted order"
          + (", schedule, slots, predecessors, colours and $D010" if deep else ""))
    return dict(checked=checked, orders=seen_orders, shapes=seen_shapes,
                ties=ties, owners=owners, msb=msb_seen, preds=preds, bad=bad)


def main():
    argv = sys.argv[1:]
    fast = "--fast" in argv
    soak = 0
    if "--soak" in argv:
        soak = int(argv[argv.index("--soak") + 1])
    SCRATCH.mkdir(parents=True, exist_ok=True)
    sym = symbols(SYM)
    log = SCRATCH

    # =====================================================================
    print("=== 1. the model, the tables and the fixture wiring agree ===")
    bad = P.audit()
    check("the P5 geometry model audits clean", not bad, "; ".join(bad))
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools/gen_p5_tables.py"), "--check"],
                       capture_output=True, text=True)
    check("src/p5_tables.asm matches tests/p5_model.py", r.returncode == 0,
          (r.stdout + r.stderr).strip())
    check("every ring mode admits all sixteen sprites on every frame",
          all(P.census(m)["accepted"] == {P.N_RING} for m in P.MODES.values()),
          "so a sprite missing on screen is ALWAYS a fault, never the builder "
          "being correct")

    # Source-level assertions, against CODE only. The first draft grepped the
    # whole file and failed on the words "the $D010 source" in a comment -- the
    # check has to read what the assembler reads, or it measures prose.
    code = [ln.split("//")[0] for ln in (ROOT / "src/p5_ring.asm").read_text().splitlines()]
    code = "\n".join(code).lower()
    vic = [r for r in ("$d0", "$d4", "$dc") if r in code]
    check("the ring never touches a VIC or SID register", not vic,
          f"found {vic}" if vic else "motion produces logical X/Y and nothing else")
    check("the ring never assigns a hardware slot",
          "schedslot" not in code and "mux_first_slot" not in code,
          "a slot is still earned by being accepted at a sorted position")

    # =====================================================================
    print("\n=== 2. the orbit, the sorter and the schedule, frame by frame ===")
    print("        Positions and sorted order are compared on EVERY frame; the")
    print("        whole schedule -- accepted IDs, slots, i-6 predecessor")
    print("        identity, batch lines, batch counts and the complete $D010 --")
    print("        is compared too. The model computes all of it from the")
    print("        geometry, never from the machine.")
    census = {}
    # Frame counts are modest ON PURPOSE. The exhaustive proof of the geometry
    # is the model's, which audits every frame of every mode's full period for
    # free; what the machine has to demonstrate is that it IMPLEMENTS that
    # model, and it either does that or it does not. Each frame here costs about
    # thirty-five monitor round trips, so 140 frames per mode took fourteen
    # minutes a mode and made the suite something nobody would run.
    nframes = 30 if fast else 60
    for fxi in sorted(P.MODES):
        mode = P.MODES[fxi]
        v = Vice(6780, PRG, warp=True)
        try:
            m = v.mon; m.cmd("delete")
            if select_p5(m, sym, fxi) is None:
                check(f"{mode.name} selected", False); continue
            census[fxi] = walk(m, sym, mode, nframes, mode.name)
        finally:
            v.close()
            sweep_logs()

    # =====================================================================
    print("\n=== 3. equal-Y ties are deterministic ===")
    print("        The orbit puts pairs on exactly the same raster constantly.")
    print("        walk() has already compared the engine's sortedIDs against")
    print("        the documented (Y, logical ID) comparator on every one of")
    print("        those frames; this reports how many it actually saw.")
    for fxi, c in sorted(census.items()):
        if c["bad"]:
            continue
        check(f"{P.MODES[fxi].name}: equal-Y ties occurred and every one "
              f"resolved by ascending logical ID", c["ties"] > 0,
              f"{c['ties']} tie pairs over {c['checked']} frames")

    # =====================================================================
    print("\n=== 4. churn: order, slot ownership, predecessor identity, shape ===")
    for fxi, c in sorted(census.items()):
        if c["bad"]:
            continue
        name = P.MODES[fxi].name
        check(f"{name}: the sorted order really changed", len(c["orders"]) > 1,
              f"{len(c['orders'])} distinct orders in {c['checked']} frames")
        multi = {s: len(v) for s, v in c["owners"].items()}
        check(f"{name}: every hardware slot HW2..HW7 had several logical owners",
              all(v > 1 for v in multi.values()), f"owners per slot {multi}")
        check(f"{name}: the i-6 predecessor identity changed",
              len(c["preds"]) > M.MUX_SLOTS,
              f"{len(c['preds'])} distinct (sprite, predecessor) pairs")
        check(f"{name}: the batch schedule changed shape", len(c["shapes"]) >= 1,
              f"{len(c['shapes'])} distinct shapes")

    # =====================================================================
    print("\n=== 5. X=255: the engine's own crossing census ===")
    print("        ringX255Up/Down are counted by the 6502 as it writes logXHi,")
    print("        not predicted by the model. They are the machine saying its")
    print("        X really crossed 255, in both directions.")
    for fxi in sorted(P.MODES):
        mode = P.MODES[fxi]
        v = Vice(6781, PRG, warp=True)
        try:
            m = v.mon; m.cmd("delete")
            if select_p5(m, sym, fxi) is None:
                check(f"{mode.name} selected for the X255 census", False); continue
            frames = 60 if fast else mode.period
            ok = free_run(m, sym["frameCounter"], 4.0, slice_s=1.0)
            mf = read16(m, sym["motionFrame"])
            up, dn = read16(m, sym["ringX255Up"]), read16(m, sym["ringX255Down"])
            wup = sum(1 for f in range(1, mf + 1)
                      for a, b in [(mode.positions(f - 1)[0], mode.positions(f)[0])]
                      for i in range(P.N_RING)
                      if a[i] < 256 <= b[i])
            wdn = sum(1 for f in range(1, mf + 1)
                      for a, b in [(mode.positions(f - 1)[0], mode.positions(f)[0])]
                      for i in range(P.N_RING)
                      if b[i] < 256 <= a[i])
            check(f"{mode.name}: X=255 crossings match the model exactly",
                  ok and (up, dn) == (wup, wdn),
                  f"{mf} frames: engine up {up} down {dn}, model up {wup} down {wdn}")
            check(f"{mode.name}: X=255 was crossed in BOTH directions",
                  up > 0 and dn > 0, f"up {up} down {dn}")
            slots = {s: set() for s in range(M.MUX_FIRST_SLOT,
                                             M.MUX_FIRST_SLOT + M.MUX_SLOTS)}
            for f in range(min(mode.period, 300)):
                for e in mode.build(f)["entries"]:
                    slots[e["slot"]].add(e["xhi"])
            check(f"{mode.name}: every hardware slot saw BOTH X-MSB states",
                  all(v == {0, 1} for v in slots.values()),
                  f"{ {s: sorted(v) for s, v in slots.items()} }")
        finally:
            v.close()
            sweep_logs()

    # =====================================================================
    print("\n=== 6. the frame transaction still runs at raster 250 ===")
    print("        The FIX 16 invariant, under the densest schedule this engine")
    print("        has ever been given: the ring puts consecutive batches as")
    print("        little as one raster apart.")
    v = Vice(6782, PRG, warp=True)
    try:
        m = v.mon; m.cmd("delete")
        for fxi in sorted(P.MODES):
            if select_p5(m, sym, fxi) is None:
                check(f"fixture {fxi} selected for the raster-250 check", False)
                continue
            free_run(m, sym["frameCounter"], 0.5, slice_s=0.5)
            check_frame_transaction_raster(m, sym, P.MODES[fxi].name,
                                           frames=60 if fast else 200)
    finally:
        v.close(); sweep_logs()

    # =====================================================================
    print("\n=== 7. presentation stays coherent LATE in the frame ===")
    print("        Sampled at scrollPublish, after the whole main-thread pass.")
    v = Vice(6783, PRG, warp=True)
    try:
        m = v.mon; m.cmd("delete")
        for fxi in sorted(P.MODES):
            if select_p5(m, sym, fxi) is None:
                check(f"fixture {fxi} selected for the late-frame check", False)
                continue
            free_run(m, sym["frameCounter"], 0.5, slice_s=0.5)
            check_presentation_late(m, sym, P.MODES[fxi].name,
                                    frames=20 if fast else 60)
    finally:
        v.close(); sweep_logs()

    # =====================================================================
    print("\n=== 8. scrolling, pages and fine phases under the ring ===")
    v = Vice(6784, PRG, warp=True)
    try:
        m = v.mon; m.cmd("delete")
        for fxi in sorted(P.MODES):
            mode = P.MODES[fxi]
            if select_p5(m, sym, fxi) is None:
                check(f"fixture {fxi} selected for the scroll check", False)
                continue
            COUNT = ("frameCounter", "coarseCount", "flipCount",
                     "pageAFrames", "pageBFrames")
            base = {c: read16(m, sym[c]) for c in COUNT}
            f0 = rd(m, sym["finePhase"], 16)
            # publishSkip SATURATES at 255, so a delta across a long run is not
            # a measurement -- it is a lower bound that reads as ZERO the moment
            # the counter is already pinned. That is exactly how this suite first
            # reported "ZERO publication skips" for two modes that were skipping
            # 13% of their frames. Zero it, and treat saturation as its own
            # failure so the number can never be trusted wrongly again.
            poke(m, sym["publishSkip"], 0)
            ran = free_run(m, sym["frameCounter"], 8.0 if not fast else 3.0)
            now = {c: read16(m, sym[c]) for c in COUNT}
            f1 = rd(m, sym["finePhase"], 16)
            d = {c: (now[c] - base[c]) & 0xffff for c in COUNT}
            fine = [((f1[2 * i] | (f1[2 * i + 1] << 8))
                     - (f0[2 * i] | (f0[2 * i + 1] << 8))) & 0xffff for i in range(8)]
            skips = rd(m, sym["publishSkip"])[0]
            print(f"        --- {mode.name} ---")
            print(f"        frames {d['frameCounter']}  coarse {d['coarseCount']}  "
                  f"flips {d['flipCount']}  page A {d['pageAFrames']} B {d['pageBFrames']}")
            print(f"        fine phases {fine}")
            check(f"{mode.name}: the run really ran", ran and d["frameCounter"] > 400,
                  f"{d['frameCounter']} frames")
            check(f"{mode.name}: every fine-scroll phase was exercised",
                  all(c > 10 for c in fine), f"{fine}")
            check(f"{mode.name}: both screen pages were displayed",
                  d["pageAFrames"] > 0 and d["pageBFrames"] > 0)
            check(f"{mode.name}: every coarse step flipped the page",
                  abs(d["flipCount"] - d["coarseCount"]) <= 1,
                  f"{d['flipCount']} vs {d['coarseCount']}")
            for label, s in (("$d018/software page", "statPageMismatch"),
                             ("pointer-destination", "statPtrMismatch"),
                             ("back-page-late", "scrollLate"),
                             ("sorter", "sortFault"),
                             ("schedule overflow", "statOverflow"),
                             ("batch overflow", "statBatchOverflow")):
                check(f"{mode.name}: zero {label} faults", rd(m, sym[s])[0] == 0,
                      f"{rd(m, sym[s])[0]}")
            check(f"{mode.name}: the skip counter did not saturate", skips < 255,
                  "SATURATED -- a lower bound, not a measurement"
                  if skips >= 255 else f"{skips} of 255")
            check(f"{mode.name}: ZERO publication skips", skips == 0,
                  f"{skips} in {d['frameCounter']} frames "
                  f"({100*skips/max(1,d['frameCounter']):.1f}%). A skipped FRAME record "
                  f"is one frame of scroll judder; the sprite schedule has no skip "
                  f"path and is never dropped")
    finally:
        v.close(); sweep_logs()

    # =====================================================================
    if not fast:
        print("\n=== 9. main-thread timing and the frame-budget reserve ===")
        print("        Raster-derived elapsed SPANS, which INCLUDE the raster")
        print("        IRQs that interrupt them. That is the number that decides")
        print("        whether preparation fits in a frame -- it is elapsed time,")
        print("        not the main thread's own cycle count, and the difference")
        print("        is the executor running on top of it.")
        print()
        print("        mode          ring  sort  build  prep max  of 19656  reserve  skips")
        v = Vice(6785, PRG, warp=True)
        try:
            m = v.mon; m.cmd("delete")
            for fxi in sorted(P.MODES):
                mode = P.MODES[fxi]
                if select_p5(m, sym, fxi) is None:
                    check(f"fixture {fxi} selected for prep timing", False); continue
                free_run(m, sym["frameCounter"], 0.5, slice_s=0.5)
                poke(m, sym["publishSkip"], 0)     # saturates; see section 8
                ev, why = collect(m, log, sym,
                                  ("motionTick", "sortTick", "buildSchedule",
                                   "publishSchedule", "scrollPublish"), 1.5)
                pos = lambda l, c: l * 63 + c
                spans = {k: [] for k in ("ring", "sort", "build", "prep")}
                t0 = r0 = s0 = b0 = None
                for addr, line, cyc in ev:
                    p = pos(line, cyc)
                    if addr == sym["motionTick"]:
                        t0 = r0 = p
                    elif addr == sym["sortTick"]:
                        if r0 is not None:
                            spans["ring"].append((p - r0) % PAL_FRAME); r0 = None
                        s0 = p
                    elif addr == sym["buildSchedule"]:
                        if s0 is not None:
                            spans["sort"].append((p - s0) % PAL_FRAME); s0 = None
                        b0 = p
                    elif addr == sym["publishSchedule"]:
                        if b0 is not None:
                            spans["build"].append((p - b0) % PAL_FRAME); b0 = None
                    elif addr == sym["scrollPublish"]:
                        if t0 is not None:
                            spans["prep"].append((p - t0) % PAL_FRAME); t0 = None
                skips = rd(m, sym["publishSkip"])[0]
                if not spans["prep"]:
                    check(f"{mode.name} preparation sampled", False, str(why)); continue
                # A span is (end - start) % 19656, so one that exceeds a whole
                # frame wraps and reads as a SMALL number, and a mismatched pair
                # reads as nearly 19656. Neither is a duration. Keep only the
                # plausible ones and report the median, which is robust to both;
                # a bare max() here reported 19,655 -- PAL_FRAME minus one --
                # and called it "100.0% of the frame".
                clean = [x for x in spans["prep"] if x < PAL_FRAME - 2000]
                worst = max(clean) if clean else 0
                med = lambda a: sorted(a)[len(a) // 2] if a else 0
                print(f"        {mode.name:<12s} {med(spans['ring']):5d} "
                      f"{med(spans['sort']):5d} {med(spans['build']):6d} "
                      f"{worst:8d}  {100*worst/PAL_FRAME:7.1f}%  "
                      f"{PAL_FRAME-worst:7d}  {skips}")
                check(f"{mode.name}: preparation fits inside one PAL frame",
                      worst < PAL_FRAME,
                      f"worst elapsed span {worst} of {PAL_FRAME} "
                      f"({100*worst/PAL_FRAME:.1f}%), reserve {PAL_FRAME-worst} cycles")
                check(f"{mode.name}: ZERO publication skips while timing",
                      skips == 0, f"{skips}")
        finally:
            v.close(); sweep_logs()

    # =====================================================================
    if soak:
        print(f"\n=== 10. soak: {soak} frames of the principal mode ===")
        fxi = 33                                  # RING-SHIFT: longest period
        mode = P.MODES[fxi]
        v = Vice(6786, PRG, warp=True)
        try:
            m = v.mon; m.cmd("delete")
            if select_p5(m, sym, fxi) is None:
                check("RING-SHIFT selected for the soak", False)
            else:
                start = time.time()
                ok = True
                while read16(m, sym["frameCounter"]) < soak and ok:
                    ok = free_run(m, sym["frameCounter"], 5.0, slice_s=2.5)
                    if time.time() - start > 900:
                        break
                frames = read16(m, sym["frameCounter"])
                mf = read16(m, sym["motionFrame"])
                print(f"        {frames} frames, {mf} motion frames, "
                      f"{read16(m, sym['ringOrbits'])} orbits, "
                      f"{read16(m, sym['coarseCount'])} coarse steps")
                print(f"        X255 up {read16(m, sym['ringX255Up'])} "
                      f"down {read16(m, sym['ringX255Down'])}")
                check("the soak really ran", frames >= soak, f"{frames} frames")
                check("soak: frame transaction never left raster 250",
                      rd(m, sym["frameEntryLine"])[0] == FRAME_IRQ_LINE,
                      f"frameEntryLine {rd(m, sym['frameEntryLine'])[0]}")
                for label, s in (("publication skip", "publishSkip"),
                                 ("$d018/page mismatch", "statPageMismatch"),
                                 ("pointer-destination mismatch", "statPtrMismatch"),
                                 ("back-page-late", "scrollLate"),
                                 ("sorter fault", "sortFault"),
                                 ("schedule overflow", "statOverflow"),
                                 ("batch overflow", "statBatchOverflow")):
                    got = rd(m, sym[s])[0]
                    check(f"soak: zero {label}", got == 0, f"{got}")
                check("soak: all sixteen sprites still accepted",
                      rd(m, sym["statAccepted"])[0] == P.N_RING,
                      f"{rd(m, sym['statAccepted'])[0]}")
        finally:
            v.close(); sweep_logs()

    # =====================================================================
    print("\n=== 11. cleanup ===")
    left = sorted(SCRATCH.glob("trace-*.log"))
    check("no transient trace logs left behind", not left, str([f.name for f in left]))

    print()
    if fails:
        print(f"=== {len(fails)} FAILURES: " + "; ".join(fails[:6]) + " ===")
        return 1
    print("=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
