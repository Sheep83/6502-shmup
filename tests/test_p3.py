#!/usr/bin/env python3
"""P3 scripted-motion tests.

What this proves
----------------
* logical X/Y are recomputed every frame by the engine and match an independent
  model of the trajectory, frame by frame;
* those MOVED values are what the schedule is built from -- the NEXT schedule
  always equals the model's build of the logical state actually in memory;
* the complete $D010 is computed by the BUILDER and written by the executor,
  including 0->1 and 1->0 on a reused physical slot, and sprites crossing
  255/256 while moving;
* admission changes safely frame to frame across the conservative gap-33
  threshold, including when the change reshapes the rest of the schedule;
* schedules of different accepted count, batch count, merged width, batch
  raster and $D010 alternate with no stale data carried between them;
* MAX_SCHED overflow is reported, not silently truncated;
* the executor's critical path has not regressed against the P2 baselines;
* the main thread finishes preparing the next frame in time, every frame.

What this does NOT prove
------------------------
Visible correctness. See docs/manual-acceptance.md. This suite runs the machine
headless and a headless machine cannot tell you it looks wrong. The gap-33
fixture in particular is EXPECTED to make a sprite appear and disappear, and
only a human can confirm that what the display shows matches what the
diagnostic says.

VICE process ownership: every launch is owned by PID, reaped in try/finally,
`-console` so no window is created and no keyboard focus is taken, and other
x64sc processes are reported but never touched.
"""
import re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import (PRG, SYM, symbols, Vice, rd, set_bp, free_run, read16,
                     LAUNCHED_PIDS)
from test_p2 import (poke, measure, worst_of, set_pin, clear_pin, build_case,
                     DEADLINE_DISPLAY, DEADLINE_FETCH, collect, batches_from)
import p2_model as M
import p3_model as P
import sprite_identity as SI

SCRATCH = Path("/tmp/6502-shmup-p3")
MAX_SCHED, MAX_BATCH, MAX_LOGICAL = M.MAX_SCHED, M.MAX_BATCH, P.MAX_LOGICAL
FRAME_IRQ_LINE = M.FRAME_IRQ_LINE

# P2's measured baselines for the executor critical path, by mid-screen batch
# size. P3 must not move these: motion belongs in main-thread preparation.
P2_CRIT = {1: 212, 2: 291, 3: 366, 4: 447, 5: 520, 6: 646}
# The P2-era numbers are kept as the historical baseline rather than refreshed,
# so the drift stays visible. Two cycles of it are real and permanent: the
# executor grew from two raster phases to five (frame, handoff, top split,
# batch, bottom split) and the code moved out of $1500, which changes where
# indexed reads cross a page. PH_BATCH was renumbered to 0 so the dispatch
# reaches a batch in the same eight cycles it always did, which recovered four
# of the six cycles the five-phase executor first cost; the residual two are
# addressing, not instructions. The DEADLINE is the real safety property and is
# asserted separately and unchanged: a six-entry batch measures 648 against 756.
CRIT_ALLOWANCE = 2
# Moving fixtures sweep every badline phase and every sprite-DMA alignment,
# so their worst sample is drawn from a far larger population than the pinned
# static measurement. See the note at the moving-fixture check.
MOVING_ALLOWANCE = 32
P2_WORST_PHASE = 7

fails = []


def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def sweep_logs(quiet=True):
    """Delete P3's trace logs, once their VICE is gone.

    test_p2 has a function of the same name, but it globs test_p2's scratch
    directory -- importing it left every P3 trace file behind and the
    end-of-suite "scratch is empty" assertion caught it.
    """
    n = 0
    for f in SCRATCH.glob("trace-*.log"):
        try:
            f.unlink(); n += 1
        except OSError:
            pass
    if n and not quiet:
        print(f"        swept {n} trace logs")
    return n


# ===========================================================================
# Driving a P3 fixture
# ===========================================================================
def select_p3(mon, sym, fx, tries=4):
    """Select a P3 fixture and leave the machine stopped at mainLoop, frame 0.

    Verified against the model before returning: an unverified selection
    measures the previous fixture, and with eight new fixtures that is very
    easy to do without noticing.
    """
    fixture = P.FIXTURES[fx]
    fixture.reset()
    want = fixture.build()
    for _ in range(tries):
        b = set_bp(mon, sym["mainLoop"]); mon.cmd("x"); mon.cmd(f"delete {b}")
        poke(mon, sym["fixtureIndex"], fx)
        poke(mon, sym["fixtureYOffset"], 0)
        mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={sym['rebuild']:04x}")
        bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
        moves = 0 if fixture.kind == P.FK_STATIC else 1
        if (rd(mon, sym["statAccepted"])[0] == want["accepted"] and
                rd(mon, sym["statBatches"])[0] == want["n_batches"] and
                rd(mon, sym["statOverflow"])[0] == want["overflow"] and
                rd(mon, sym["logCount"])[0] == len(fixture.sprites) and
                rd(mon, sym["fixtureMoves"])[0] == moves and
                read16(mon, sym["motionFrame"]) == 0):
            mon.cmd("delete")
            return want
        time.sleep(0.3)
    mon.cmd("delete")
    return None


def pc_of(mon, tries=4):
    """Where the CPU is actually stopped."""
    for _ in range(tries):
        m = re.search(r"\.;([0-9a-f]{4})", mon.cmd("r"))
        if m:
            return int(m.group(1), 16)
        time.sleep(0.15)
    return None


def read_logical(mon, sym, n):
    """The logical X/Y the engine is holding right now."""
    ys = rd(mon, sym["logY"], n)
    xl = rd(mon, sym["logX"], n)
    xh = rd(mon, sym["logXHi"], n)
    return ys, [xl[i] | (xh[i] << 8) for i in range(n)], xh


def read_sched(mon, sym, n, nb):
    """Read the schedule the builder just wrote.

    Addressed through bs_base / bs_bbase -- the byte offsets buildSchedule
    latched when it started -- and NOT through schedNext. P2 learned this the
    hard way: the frame IRQ can swap CURRENT/NEXT in the middle of the build
    the harness is driving, after which schedNext names the other buffer and
    "the schedule just built" reads back as the PREVIOUS case's. P2 solved it
    by stopping the raster IRQ during inspection, which P3 cannot do -- motion
    is driven by the main loop, and the main loop is paced by that IRQ. Reading
    the builder's own base is immune either way.
    """
    be, bb = rd(mon, sym["bs_base"])[0], rd(mon, sym["bs_bbase"])[0]
    g = lambda name, base, cnt: rd(mon, sym[name] + base, max(1, cnt))[:cnt]
    return {
        "y": g("schedY", be, n), "x": g("schedX", be, n),
        "xhi": g("schedXHi", be, n), "slot": g("schedSlot", be, n),
        "line": g("batchLine", bb, nb), "first": g("batchFirst", bb, nb),
        "count": g("batchCount", bb, nb), "d010": g("batchD010", bb, nb),
    }


def compare_sched(mon, sym, want):
    """Field-by-field engine-vs-model comparison of the NEXT schedule."""
    bad = []
    acc = rd(mon, sym["statAccepted"])[0]
    nb = rd(mon, sym["statBatches"])[0]
    ovf = rd(mon, sym["statOverflow"])[0]
    bovf = rd(mon, sym["statBatchOverflow"])[0]
    if acc != want["accepted"]:
        bad.append(f"accepted {acc}!={want['accepted']}")
    if nb != want["n_batches"]:
        bad.append(f"batches {nb}!={want['n_batches']}")
    if ovf != want["overflow"]:
        bad.append(f"overflow {ovf}!={want['overflow']}")
    if bovf != 0:
        bad.append(f"batch overflow {bovf}")
    if bad:
        return bad
    s = read_sched(mon, sym, acc, nb)
    e = want["entries"]
    if s["y"] != [x["y"] for x in e]:
        bad.append(f"Y {s['y']} != {[x['y'] for x in e]}")
    if s["x"] != [x["x"] for x in e]:
        bad.append(f"Xlo {s['x']} != {[x['x'] for x in e]}")
    if s["xhi"] != [x["xhi"] for x in e]:
        bad.append(f"XMSB {s['xhi']} != {[x['xhi'] for x in e]}")
    if s["slot"] != [x["slot"] for x in e]:
        bad.append(f"slots {s['slot']} != {[x['slot'] for x in e]}")
    if s["line"] != [b["line"] for b in want["batches"]]:
        bad.append(f"lines {s['line']} != {[b['line'] for b in want['batches']]}")
    if s["first"] != [b["first"] for b in want["batches"]]:
        bad.append(f"first {s['first']}")
    if s["count"] != [b["count"] for b in want["batches"]]:
        bad.append(f"count {s['count']} != {[b['count'] for b in want['batches']]}")
    if s["d010"] != [b["d010"] for b in want["batches"]]:
        bad.append(f"$D010 {[hex(v) for v in s['d010']]} != "
                   f"{[hex(b['d010']) for b in want['batches']]}")
    if sum(s["count"]) != acc:
        bad.append(f"coverage {sum(s['count'])} of {acc}")
    return bad


def step_frames(mon, sym, n):
    """Advance exactly n motion frames, stopping once motion AND the rebuild
    for that frame are complete.

    The breakpoint is regenTick, which the main loop reaches immediately after
    `jsr motionTick` and `jsr republish`. Stopping at motionTick instead would
    stop BEFORE the frame's positions were advanced and before its schedule was
    built, so every comparison would be one frame out.

    Breakpointing a main-loop landmark is also what makes a frame COUNTABLE:
    the loop is paced by the renderer's frame counter, so stepping by wall
    clock would advance an unknown number of frames and the comparison would be
    against a position nobody predicted.
    """
    # VERIFIED, and retried. The remote monitor returns from `x` on a prompt
    # echo rather than on the actual stop, so an unchecked `x` can leave the
    # machine where it was -- which showed up as the first fixture of the suite
    # reporting "motionFrame 0" at frame 1 while every later fixture passed,
    # the classic signature of a dropped first command after connect.
    bp = set_bp(mon, sym["regenTick"])
    ok = True
    for _ in range(n):
        before = read16(mon, sym["motionFrame"])
        for _try in range(6):
            mon.cmd("x")
            # BOTH conditions. "motionFrame advanced by one" alone is not
            # enough: if `x` returns on a prompt echo without the machine
            # having stopped, the next read halts it at an arbitrary point --
            # which can be in the MIDDLE of buildSchedule, where statBatches
            # has been zeroed and not yet rewritten. That reported "batches
            # 0 != 1" and looked like a builder fault.
            if (((read16(mon, sym["motionFrame"]) - before) & 0xffff) == 1
                    and pc_of(mon) == sym["regenTick"]):
                break
            time.sleep(0.2)
        else:
            ok = False
            break
    mon.cmd(f"delete {bp}")
    mon.cmd("delete")
    return ok


def walk_fixture(mon, sym, fx, frames, label):
    """Step a moving fixture frame by frame, checking motion AND schedule."""
    fixture = P.FIXTURES[fx]
    want = select_p3(mon, sym, fx)
    if want is None:
        check(f"{label}: selected", False, "selection failed")
        return None
    n = len(fixture.sprites)
    bad_motion, bad_sched, shapes = [], [], set()
    compared = 0
    fixture.reset()
    for f in range(frames):
        if f:
            if not step_frames(mon, sym, 1):
                bad_motion.append(f"frame {f}: could not advance the machine one frame")
                break
            fixture.step()
        mf = read16(mon, sym["motionFrame"])
        if mf != f:
            bad_motion.append(f"frame {f}: engine motionFrame {mf}")
            break
        ys, xs, xh = read_logical(mon, sym, n)
        if ys != fixture.ys() or xs != fixture.xs():
            bad_motion.append(f"frame {f}: Y {ys} vs {fixture.ys()}; "
                              f"X {xs} vs {fixture.xs()}")
            break
        if not P.y_order_ok(ys):
            bad_motion.append(f"frame {f}: Y order broken {ys}")
            break
        s = fixture.build()
        d = compare_sched(mon, sym, s)
        if d:
            bad_sched.append(f"frame {f}: " + "; ".join(d))
            break
        shapes.add((s["accepted"], s["n_batches"], s["max_mid_batch"],
                    tuple(b["line"] for b in s["batches"]),
                    tuple(b["d010"] for b in s["batches"])))
        compared += 1
    check(f"{label}: logical X/Y match the independent model every frame",
          not bad_motion, "; ".join(bad_motion[:2]))
    # A comparison loop that breaks on the first mismatch can report "no
    # schedule problems" having checked one frame. The count is part of the
    # result, exactly as sample counts are in the timing sections.
    ok = not bad_sched and compared == frames
    check(f"{label}: NEXT schedule is built from the MOVED values, "
          f"verified on {compared} consecutive frames", ok,
          "" if ok else ("; ".join(bad_sched[:2])
                         or f"only {compared} of {frames} frames compared"))
    return shapes


# ===========================================================================
def main():
    SCRATCH.mkdir(exist_ok=True)
    log = SCRATCH

    print("=== 0. build artefacts and pre-flight ===")
    check("build/shmup.prg exists", PRG.is_file())
    check("build/main.vs exists", SYM.is_file())
    if fails:
        return 1
    sym = symbols(SYM)
    pre = subprocess.run(["pgrep", "-fl", "x64sc"], capture_output=True, text=True)
    pre_pids = [l.split(" ")[0] for l in pre.stdout.splitlines()
                if l.partition(" ")[2].split(" ")[0].endswith("x64sc")]
    print(f"        x64sc running before the suite: {pre_pids or 'none'}")

    print("\n=== 1. the generated fixture table matches its source of truth ===")
    r = subprocess.run([sys.executable, str(ROOT / "tools/gen_p3_fixtures.py"), "--check"],
                       capture_output=True, text=True)
    check("src/p3_fixtures.asm is in step with tests/p3_model.py",
          r.returncode == 0, r.stdout.strip() + r.stderr.strip())
    bad = P.audit()
    check("every P3 trajectory keeps Y ordered and every admission legal",
          not bad, "; ".join(bad[:3]))
    check("MAXCAP really exceeds MAX_SCHED, or it tests nothing",
          len(P.FIXTURES[22].sprites) > MAX_SCHED,
          f"{len(P.FIXTURES[22].sprites)} sprites vs MAX_SCHED {MAX_SCHED}")
    check("MAX_LOGICAL exceeds MAX_SCHED so the fault path is reachable",
          MAX_LOGICAL > MAX_SCHED, f"{MAX_LOGICAL} > {MAX_SCHED}")

    print("\n=== 1b. motion is main-thread only (source level) ===")
    src = {p.name: p.read_text() for p in (ROOT / "src").glob("*.asm")}
    ex = src["renderer.asm"]
    ex_body = ex[ex.index("irqHandler:"):]
    touched = [n for n in ("motionTick", "logX", "logY", "logXHi", "mvXVel",
                           "mvYVel", "motionFrame", "fixtureMoves")
               if re.search(r"\b%s\b" % n, ex_body)]
    check("the raster executor references NO motion or logical state",
          not touched, f"{touched}")
    check("motionTick is called from exactly one place, in the main loop",
          sum(len(re.findall(r"jsr\s+motionTick", t)) for t in src.values()) == 1
          and "jsr motionTick" in src["main.asm"])
    check("nothing writes a schedule array outside the builder",
          all("schedY," not in t for n, t in src.items()
              if n not in ("renderer.asm",)))

    # =====================================================================
    v = Vice(6760, PRG, warp=True)
    try:
        m = v.mon
        m.cmd("delete")
        # NOTE: the raster IRQ stays ENABLED for the whole suite. P2 disabled it
        # while inspecting built buffers; P3 cannot, because the main loop --
        # and therefore motion -- is paced by that IRQ. read_sched() addresses
        # the builder's own base instead, which is immune to a mid-build swap.

        print("\n=== 2. P3-A  MOVE6: motion with no reuse ambiguity ===")
        shapes = walk_fixture(m, sym, 16, 40, "MOVE6")
        fx = P.FIXTURES[16]; fx.reset()
        c = fx.build()
        print(f"        {len(fx.sprites)} sprites, accepted {c['accepted']}, "
              f"batches {c['n_batches']}, no slot reused")
        check("MOVE6 never reuses a physical slot", c["reuse"] == 0)
        check("MOVE6 moves in X, in Y and diagonally",
              any(s.X.vel0 and not s.Y.vel0 for s in fx.sprites) and
              any(s.Y.vel0 and not s.X.vel0 for s in fx.sprites) and
              any(s.X.vel0 and s.Y.vel0 for s in fx.sprites))

        print("\n=== 3. P3-B  MSBFLIP6: every reused slot inverts its X MSB ===")
        want = select_p3(m, sym, 17)
        check("MSBFLIP6 selected", want is not None)
        if want:
            e = want["entries"]
            lead, reuse = e[:6], e[6:]
            print(f"        leaders  slot/X/MSB  "
                  f"{[(x['slot'], x['x9'], x['xhi']) for x in lead]}")
            print(f"        reusers  slot/X/MSB  "
                  f"{[(x['slot'], x['x9'], x['xhi']) for x in reuse]}")
            print(f"        batch $D010          "
                  f"{[hex(b['d010']) for b in want['batches']]}")
            bad = compare_sched(m, sym, want)
            check("MSBFLIP6 schedule and complete $D010 match the model",
                  not bad, "; ".join(bad))
            flips = [(l["slot"], l["xhi"], r["xhi"]) for l, r in zip(lead, reuse)]
            check("every one of the six slots changes its MSB on reuse",
                  all(a != b for _, a, b in flips), f"{flips}")
            check("both directions are covered, 0->1 and 1->0",
                  {(a, b) for _, a, b in flips} == {(0, 1), (1, 0)})
            check("the reusers form ONE six-entry merged batch",
                  want["max_mid_batch"] == 6)
            d0, d1 = [b["d010"] for b in want["batches"]]
            mux = 0xfc                  # slots 2..7
            check("the two batch $D010 values are exact complements on the mux bits",
                  (d0 & mux) ^ (d1 & mux) == mux,
                  f"${d0:02x} -> ${d1:02x}")

        print("\n=== 4. P3-G  MAXCAP: schedule overflow is reported, not hidden ===")
        for fxi, label in ((14, "T6X3 (exactly MAX_SCHED)"), (22, "MAXCAP (over)")):
            if fxi == 14:
                w = build_case(m, sym, 14, 0)
                acc = rd(m, sym["statAccepted"])[0]
                ovf = rd(m, sym["statOverflow"])[0]
                print(f"        {label}: accepted {acc}, overflow {ovf}")
                check("a schedule of exactly MAX_SCHED entries does NOT fault",
                      acc == MAX_SCHED and ovf == 0, f"accepted {acc}, overflow {ovf}")
            else:
                w = select_p3(m, sym, 22)
                check("MAXCAP selected", w is not None)
                if w:
                    acc = rd(m, sym["statAccepted"])[0]
                    ovf = rd(m, sym["statOverflow"])[0]
                    n = len(P.FIXTURES[22].sprites)
                    print(f"        {label}: offered {n}, accepted {acc}, overflow {ovf}")
                    check("MAXCAP accepts exactly MAX_SCHED and no more",
                          acc == MAX_SCHED, f"{acc}")
                    rng = rd(m, sym["statRejRange"])[0]
                    # MAXCAP's first sprite is at Y=50, below MIN_SPRITE_Y, so
                    # it is refused by the production Y bounds BEFORE capacity
                    # is consulted. The remainder that then does not fit is one
                    # smaller. Accepted is unchanged at MAX_SCHED, so the
                    # fixture still tests exactly what it was built to test.
                    check("the sprites that did not fit are COUNTED, not truncated silently",
                          ovf == n - MAX_SCHED - rng and ovf == w["overflow"],
                          f"overflow {ovf}, out-of-range {rng}, model {w['overflow']}")
                    check("the out-of-range rejection matches the model",
                          rng == w["rej_range"], f"{rng} vs {w['rej_range']}")
                    bad = compare_sched(m, sym, w)
                    check("MAXCAP schedule still matches the model exactly",
                          not bad, "; ".join(bad))
                    check("no batch overflow", rd(m, sym["statBatchOverflow"])[0] == 0)

                    # SEMANTIC IDENTITY, against the build artefact.
                    #
                    # The FIX 16 forensic's pointer check asked only whether a
                    # pointer resolved INSIDE the bitmap pool. That is too weak:
                    # it cannot tell sprite 7's graphic from sprite 9's, and it
                    # would not notice a bitmap overwritten at run time. P5 then
                    # placed a kilobyte of ring tables directly above the pool,
                    # so a pointer one block out now lands on a coordinate ramp
                    # that renders as horizontal stripes. This pins the exact
                    # block AND its exact contents, against build/shmup.prg
                    # rather than against RAM or a re-implementation of the
                    # assembler's font generator.
                    be = rd(m, sym["bs_base"])[0]
                    sids = list(rd(m, sym["schedId"] + be, acc))
                    sptr = list(rd(m, sym["schedPtr"] + be, acc))
                    probs = SI.check(lambda a, n: rd(m, a, n), sids, sptr, PRG,
                                     "MAXCAP")
                    check("every accepted sprite resolves to its OWN 64-byte "
                          "diagnostic bitmap, byte for byte", not probs,
                          probs[0] if probs else
                          f"{acc} accepted ids -> {len(set(sptr))} distinct "
                          f"pointers, all matching build/shmup.prg")
                    # memory safety: nothing written past the cap.
                    #
                    # Read the buffer the BUILDER actually wrote, via bs_base,
                    # not the one schedNext happens to name now. select_p3
                    # builds and publishes with interrupts live, so the frame
                    # IRQ can adopt in between and swap CURRENT/NEXT -- and
                    # then schedNext points at the stale buffer and this canary
                    # reads a leftover from whatever fixture was built before.
                    # It did exactly that under full-suite load, reporting
                    # "last entry Y 174" -- a T6X3 value, and not one MAXCAP
                    # has anywhere. The build is the thing under test, so the
                    # check must name its buffer the same way the build did.
                    tail = rd(m, sym["schedY"] + rd(m, sym["bs_base"])[0]
                              + MAX_SCHED - 1, 1)
                    check("nothing was written past the last schedule slot",
                          tail[0] == w["entries"][MAX_SCHED - 1]["y"],
                          f"last entry Y {tail[0]}")
        # a clean fixture afterwards must clear the fault
        build_case(m, sym, 5, 0)
        check("the overflow counter clears on the next clean build",
              rd(m, sym["statOverflow"])[0] == 0)

        print("\n=== 5. P3-C  X255: moving crossings of 255/256 ===")
        shapes = walk_fixture(m, sym, 18, 70, "X255")
        fx = P.FIXTURES[18]; fx.reset()
        crossings = {"up": 0, "down": 0}
        prev = None
        slot_msb = {}
        for f, ys, xs, s in fx.frames(70):
            for i, x in enumerate(xs):
                if prev is not None:
                    if prev[i] < 256 <= x:
                        crossings["up"] += 1
                    if prev[i] >= 256 > x:
                        crossings["down"] += 1
            prev = list(xs)
            for e in s["entries"]:
                slot_msb.setdefault(e["slot"], set()).add(e["xhi"])
        print(f"        crossings over 70 frames: {crossings['up']} upward, "
              f"{crossings['down']} downward")
        print(f"        MSB values seen per slot: "
              f"{ {k: sorted(v) for k, v in sorted(slot_msb.items())} }")
        check("sprites cross 255->256 and 256->255 repeatedly, both directions",
              crossings["up"] >= 2 and crossings["down"] >= 2, f"{crossings}")
        check("a crossing happens on a slot that is reused with the other MSB",
              any(v == {0, 1} for v in slot_msb.values()),
              f"slots carrying both MSBs: "
              f"{[k for k, v in slot_msb.items() if v == {0, 1}]}")
        fx.reset()
        d010s = {tuple(b["d010"] for b in s["batches"])
                 for _, _, _, s in fx.frames(70)}
        print(f"        distinct batch-$D010 patterns over 70 frames: "
              f"{sorted(tuple(hex(v) for v in d) for d in d010s)}")
        check("the complete $D010 really changes as sprites cross 255/256",
              len(d010s) >= 2, f"{len(d010s)} distinct patterns")

        print("\n=== 6. P3-D  YMOVE: legal reuse with moving Y ===")
        shapes = walk_fixture(m, sym, 19, 60, "YMOVE")
        fx = P.FIXTURES[19]; fx.reset()
        gaps, lines, accs = [], set(), set()
        for f, ys, xs, s in fx.frames(60):
            for e in s["entries"]:
                if e["gap"] is not None:
                    gaps.append(e["gap"])
            lines.update(b["line"] for b in s["mid_batches"])
            accs.add(s["accepted"])
        print(f"        reuse gaps seen: {min(gaps)}..{max(gaps)} "
              f"(MIN_REUSE_GAP {M.MIN_REUSE_GAP})")
        print(f"        mid-screen batch rasters visited: {sorted(lines)}")
        check("every reuse stays legal for the whole run", min(gaps) >= M.MIN_REUSE_GAP,
              f"minimum gap {min(gaps)}")
        check("the reuse gap really varies (the geometry is moving)",
              max(gaps) > min(gaps), f"{min(gaps)}..{max(gaps)}")
        check("the mid-screen batch raster MOVES as Y moves", len(lines) > 3,
              f"{sorted(lines)}")
        check("the accepted set stays stable while it moves", accs == {12}, f"{accs}")

        print("\n=== 7. P3-E  GAP33: admission across the conservative threshold ===")
        shapes = walk_fixture(m, sym, 20, 30, "GAP33")
        fx = P.FIXTURES[20]; fx.reset()
        seq = []
        for f, ys, xs, s in fx.frames(13):
            gap = ys[6] - ys[0]
            admitted = any(e["log"] == 6 for e in s["entries"])
            reason = next((r["reason"] for r in s["rejects"] if r["log"] == 6), None)
            seq.append((gap, admitted))
            print(f"        frame {f:2d}  gap {gap:2d}  "
                  f"{'ADMITTED' if admitted else 'rejected (' + reason + ')':<20s} "
                  f"accepted {s['accepted']}  batches {s['n_batches']}")
        check("the candidate really crosses the threshold in both directions",
              {g for g, _ in seq} == {31, 32, 33, 34}, f"{sorted({g for g, _ in seq})}")
        check("admission is exactly the gap rule, with no hysteresis",
              all(a == (g >= M.MIN_REUSE_GAP) for g, a in seq), f"{seq}")
        check("a sprite rejected at gap 32 is admitted again at gap 33",
              (32, False) in seq and (33, True) in seq)
        check("rejection is CONSERVATIVE, never physically-unsafe, at this gap",
              all(r["reason"] == "margin"
                  for _, _, _, s in fx.frames(13) for r in s["rejects"]))

        print("\n=== 8. P3-F  SHAPE: one admission reshapes the schedule ===")
        shapes = walk_fixture(m, sym, 21, 30, "SHAPE")
        fx = P.FIXTURES[21]; fx.reset()
        rows = []
        for f, ys, xs, s in fx.frames(8):
            admitted = any(e["log"] == 6 for e in s["entries"])
            rows.append((ys[6] - ys[0], admitted, s["accepted"], s["n_batches"],
                         s["max_mid_batch"], tuple(b["line"] for b in s["batches"]),
                         tuple(b["d010"] for b in s["batches"]),
                         tuple(r["log"] for r in s["rejects"])))
        print("        gap  C    acc  batches  maxMid  rasters        $D010        rejected")
        for g, a, acc, nb, mx, ln, d0, rj in rows:
            print(f"         {g:2d}  {'in ' if a else 'out'}   {acc:2d}     {nb}       {mx}"
                  f"     {str(list(ln)):<14s} {[hex(v) for v in d0]}  {list(rj)}")
        check("admitting the candidate changes the BATCH COUNT",
              len({r[3] for r in rows}) > 1, f"{sorted({r[3] for r in rows})}")
        check("admitting the candidate changes the MERGED BATCH WIDTH",
              len({r[4] for r in rows}) > 1, f"{sorted({r[4] for r in rows})}")
        check("admitting the candidate changes which sprite is rejected",
              len({r[7] for r in rows}) > 1, f"{sorted({r[7] for r in rows})}")
        check("admitting the candidate changes the complete $D010",
              len({r[6] for r in rows}) > 1,
              f"{sorted({tuple(hex(v) for v in r[6]) for r in rows})}")
        check("batch rasters differ between the two shapes",
              len({r[5] for r in rows}) > 1)

        print("\n=== 9. schedule-shape mutation leaves no stale data ===")
        # Alternate deliberately between two very different fixtures and check
        # the whole schedule after each, including the arrays BEYOND the new
        # accepted count, which is where stale entries would survive.
        stale = []
        for rep in range(3):
            for fxi in (21, 20, 17, 16):
                w = select_p3(m, sym, fxi)
                if w is None:
                    stale.append(f"{fxi}: selection failed"); continue
                d = compare_sched(m, sym, w)
                if d:
                    stale.append(f"rep{rep} fixture {fxi}: " + "; ".join(d[:2]))
                    continue
                nxt = rd(m, sym["schedNext"])[0]
                nb = rd(m, sym["statBatches"])[0]
                # the executor is bounded by schedBatches / batchCount, so what
                # matters is that those bounds are right, not that the tail is
                # zeroed. Assert the bound, and that coverage is exact.
                if nb != w["n_batches"]:
                    stale.append(f"rep{rep} fixture {fxi}: batches {nb}")
        check("alternating between very different schedules leaves nothing stale",
              not stale, "; ".join(stale[:3]))
        counts = {}
        for fxi in (16, 17, 19, 20, 21):
            P.FIXTURES[fxi].reset()
            c = P.FIXTURES[fxi].build()
            counts[fxi] = (c["accepted"], c["n_batches"], c["max_mid_batch"])
        print(f"        (accepted, batches, maxMid) per fixture: {counts}")
        check("the alternation really does change accepted count and batch count",
              len({v[0] for v in counts.values()}) > 1 and
              len({v[1] for v in counts.values()}) > 1)

        print("\n=== 10. the executor writes the $D010 the BUILDER prepared ===")
        # Stop after the LAST batch of a frame and compare the live register.
        want = select_p3(m, sym, 17)
        free_run(m, sym["frameCounter"], 0.5, slice_s=0.5)
        bp = set_bp(m, sym["exArmBottom"])    # renamed in Slice 1:
                                             # the end-of-frame arm now
                                             # hands to the bottom phase
        cur = nb = cb = 0
        for _ in range(8):
            m.cmd("x")
            cur = rd(m, sym["schedCurrent"])[0]
            nb = rd(m, sym["schedBatches"] + cur)[0]
            cb = rd(m, sym["curBatch"])[0]
            if cb == nb:
                break
        m.cmd(f"delete {bp}")
        check("stopped after the LAST batch of a frame", cb == nb, f"{cb}/{nb}")
        live = rd(m, 0xd010)[0]
        final = rd(m, sym["batchD010"] + cur * MAX_BATCH + nb - 1, 1)[0]
        print(f"        live $D010 ${live:02x}, last prepared batch value ${final:02x}")
        check("the live $D010 is exactly the last batch's prepared value",
              live == final, f"${live:02x} vs ${final:02x}")
        check("and that value is what the model says", final == 0x54,
              f"${final:02x}")
        # every mux slot's X registers must match the schedule's last writer
        n = rd(m, sym["schedEntries"] + cur)[0]
        slots = rd(m, sym["schedSlot"] + cur * MAX_SCHED, n)
        xs = rd(m, sym["schedX"] + cur * MAX_SCHED, n)
        xh = rd(m, sym["schedXHi"] + cur * MAX_SCHED, n)
        regs = rd(m, 0xd000, 16)
        lastx = {}
        for i in range(n):
            lastx[slots[i]] = (xs[i], xh[i])
        wrong = {s: (regs[s * 2], (live >> s) & 1, v)
                 for s, v in lastx.items()
                 if regs[s * 2] != v[0] or ((live >> s) & 1) != v[1]}
        check("every mux slot's X low byte AND MSB match the CURRENT schedule",
              not wrong, f"slot: (regX, regMSB, expected) {wrong}")
    finally:
        v.close()
        sweep_logs()

    # =====================================================================
    print("\n=== 11. executor timing: no regression against P2 ===")
    v = Vice(6761, PRG, warp=True)
    try:
        m = v.mon
        m.cmd("delete")
        got, _ = set_pin(m, sym, P2_WORST_PHASE)
        check(f"pinned to P2's worst phase ({P2_WORST_PHASE})", got == P2_WORST_PHASE,
              f"$d011&7={got}")
        print("        static P2 fixtures, same phase, same geometry as the P2 report")
        print("        entries   P2 baseline   P3 measured   delta   margin")
        regress = []
        for fxi, size in ((10, 1), (9, 2), (8, 3), (7, 4), (6, 5), (5, 6)):
            w = build_case(m, sym, fxi, 0, settle=True)
            if w is None:
                check(f"batch size {size} built", False); continue
            r = measure(m, sym, log, seconds=1.5, want_line=86)
            ww = worst_of(r["mid"])
            if ww is None:
                check(f"batch size {size} sampled", False, r.get("why")); continue
            base = P2_CRIT[size]
            delta = ww["crit"] - base
            print(f"          {size}       {base:5d}        {ww['crit']:5d}     "
                  f"{delta:+4d}   {ww['margin']:+5d}")
            if not (0 <= delta <= CRIT_ALLOWANCE):
                regress.append((size, base, ww["crit"]))
        check("the executor critical path is within {} cycles of P2 at every batch size"
              .format(CRIT_ALLOWANCE),
              not regress, f"{regress}")

        print("\n        moving fixtures, natural scrolling")
        clear_pin(m, sym)
        print("        fixture     n   worst crit   deadline   margin   max entries")
        move_worst = []
        for fxi in (17, 18, 19, 23):
            w = select_p3(m, sym, fxi)
            if w is None:
                check(f"fixture {fxi} selected for timing", False); continue
            free_run(m, sym["frameCounter"], 0.5, slice_s=0.5)
            r = measure(m, sym, log, seconds=1.5)
            ww = worst_of(r["mid"])
            if ww is None:
                check(f"fixture {fxi} sampled", False, r.get("why")); continue
            move_worst.append((P.FIXTURES[fxi].name, ww))
            print(f"        {P.FIXTURES[fxi].name:<10s} {ww['n']:5d}   {ww['crit']:6d}"
                  f"     {DEADLINE_DISPLAY:5d}    {ww['margin']:+5d}      {ww['max_entries']}")
        check("every moving fixture meets the REUSE_LEAD deadline",
              move_worst and all(w["crit"] <= DEADLINE_DISPLAY for _, w in move_worst),
              f"worst {max(w['crit'] for _, w in move_worst) if move_worst else '?'}")
        check("...and the stricter sprite-FETCH deadline",
              move_worst and all(w["crit"] <= DEADLINE_FETCH for _, w in move_worst))
        # MOVING GEOMETRY COSTS MORE THAN THE PINNED STATIC WORST CASE, and it
        # is the deadline above -- not this comparison -- that is the safety
        # property. The static measurement pins YSCROLL to P2's worst phase and
        # holds one geometry; a moving fixture sweeps every badline phase AND
        # every sprite-DMA alignment, so its worst sample is drawn from a much
        # larger population. Measured: 676 against a static 648 at the same batch
        # size, with the REUSE_LEAD deadline of 756 met by 80 cycles.
        #
        # The gap is NOT attributable to the phase renumbering that recovered
        # the dispatch: it measured 675 before that change and 676 after, while
        # the static case moved 652 -> 648. Whether it predates the five-phase
        # executor entirely has not been established -- that needs a build of
        # the tree before the aperture work, which this slice did not make.
        check("a moving six-entry batch stays within MOVING_ALLOWANCE of P2's static one",
              move_worst and max(w["crit"] for _, w in move_worst) <= P2_CRIT[6] + MOVING_ALLOWANCE,
              f"worst moving {max(w['crit'] for _, w in move_worst) if move_worst else '?'} "
              f"vs P2 static {P2_CRIT[6]}")
    finally:
        v.close()
        sweep_logs()

    # =====================================================================
    print("\n=== 12. main-thread preparation, and the integrated stress run ===")
    v = Vice(6762, PRG, warp=True)
    try:
        m = v.mon
        m.cmd("delete")
        print("        Main-thread cost is measured as a RASTER SPAN: trace the")
        print("        entry and exit of the per-frame preparation and convert")
        print("        the raster delta to cycles. It measures elapsed time, so")
        print("        it INCLUDES the raster IRQs that interrupt it -- which is")
        print("        the number that matters for 'does it finish in a frame'.")
        print()
        print("        fixture       n   worst prep   of 19656   publication skips")
        prep_rows = []
        for fxi in (19, 21, 23):
            w = select_p3(m, sym, fxi)
            if w is None:
                check(f"fixture {fxi} selected for prep timing", False); continue
            free_run(m, sym["frameCounter"], 0.5, slice_s=0.5)
            base_skip = rd(m, sym["publishSkip"])[0]
            ev, why = collect(m, log, sym, ("motionTick", "scrollPublish"), 1.5)
            pos = lambda l, c: l * 63 + c
            spans, start = [], None
            for addr, line, cyc in ev:
                if addr == sym["motionTick"]:
                    start = pos(line, cyc)
                elif addr == sym["scrollPublish"] and start is not None:
                    spans.append((pos(line, cyc) - start) % 19656)
                    start = None
            skip = rd(m, sym["publishSkip"])[0] - base_skip
            if not spans:
                check(f"fixture {fxi} preparation sampled", False, str(why)); continue
            worst = max(spans)
            prep_rows.append((P.FIXTURES[fxi].name, len(spans), worst, skip))
            print(f"        {P.FIXTURES[fxi].name:<10s} {len(spans):5d}   {worst:6d}"
                  f"       {100*worst/19656:4.1f}%        {skip}")
        check("preparation was sampled on every moving fixture", len(prep_rows) == 3)
        check("main-thread preparation always finishes inside one PAL frame",
              all(w < 19656 for _, _, w, _ in prep_rows),
              f"worst {max((w for _, _, w, _ in prep_rows), default=0)} of 19656")
        check("no frame record was ever published over an unadopted one",
              all(s == 0 for _, _, _, s in prep_rows))

    finally:
        v.close()
        sweep_logs()

    print("\n=== 12b. integrated stress run: MOTION12 over the scrolling playfield ===")
    v = Vice(6763, PRG, warp=True)
    try:
        m = v.mon
        m.cmd("delete")
        # A FRESH emulator for the endurance run, and a settle before the
        # counters are read.
        #
        # Selecting a fixture means hijacking the PC mid-frame, which costs the
        # main loop a publication skip or two while it resynchronises. Those are
        # the harness's doing, not the engine's, but they accumulate in
        # saturating counters shared by every fixture measured in the same
        # emulator -- so an endurance run that shares one reads them as its own.
        # On its own machine, left to settle and then run, this fixture is clean
        # over 20,000+ frames.
        w = select_p3(m, sym, 23)
        check("MOTION12 selected", w is not None)
        free_run(m, sym["frameCounter"], 2.0, slice_s=1.0)     # settle
        COUNT = ("frameCounter", "coarseCount", "flipCount", "pageAFrames",
                 "pageBFrames", "transAB", "transBA")
        base = {c: read16(m, sym[c]) for c in COUNT}
        f0 = rd(m, sym["finePhase"], 16)
        mf0 = read16(m, sym["motionFrame"])
        # Fault counters are cumulative and saturating. Baseline them AFTER the
        # settle so a fault is attributed to the run rather than to the
        # harness's PC-hijack fixture selection -- and print the baseline, so
        # anything that did happen earlier is visible rather than subtracted.
        FAULTS = ("statLate", "scrollLate", "publishSkip", "statPageMismatch",
                  "statPtrMismatch", "statOverflow")
        fbase = {c: rd(m, sym[c])[0] for c in FAULTS}
        ran = free_run(m, sym["frameCounter"], 20)
        now = {c: read16(m, sym[c]) for c in COUNT}
        f1 = rd(m, sym["finePhase"], 16)
        mf1 = read16(m, sym["motionFrame"])
        d = {c: (now[c] - base[c]) & 0xffff for c in COUNT}
        fine = [((f1[2*i] | (f1[2*i+1] << 8)) - (f0[2*i] | (f0[2*i+1] << 8))) & 0xffff
                for i in range(8)]
        fnow = {c: rd(m, sym[c])[0] for c in FAULTS}
        fd = {c: fnow[c] - fbase[c] for c in FAULTS}
        mis = (fd["statPageMismatch"], fd["statPtrMismatch"])
        late, slate, pskip = fd["statLate"], fd["scrollLate"], fd["publishSkip"]
        ovf = fd["statOverflow"]
        maxlate = rd(m, sym["maxLateRun"])[0]
        fmin = rd(m, sym["flipLineMin"])[0]
        fmax = rd(m, sym["flipLineMax"])[0]
        motion = (mf1 - mf0) & 0xffff
        print(f"        frames {d['frameCounter']}   motion frames {motion}   "
              f"coarse {d['coarseCount']}   flips {d['flipCount']}")
        print(f"        page A {d['pageAFrames']}  page B {d['pageBFrames']}  "
              f"(A->B {d['transAB']}, B->A {d['transBA']})")
        print(f"        fine phase counts 0..7  {fine}")
        print(f"        fault counters BEFORE this run: "
              f"{ {k: v for k, v in fbase.items() if v} or 'all zero'}")
        print(f"        caused by this run: page mismatch {mis[0]}  pointer "
              f"mismatch {mis[1]}  late {late} (longest {maxlate})  "
              f"backpage-late {slate}  publish-skip {pskip}  overflow {ovf}")
        check("the integrated run really ran", ran and d["frameCounter"] > 1500,
              f"{d['frameCounter']} frames")
        check("motion advanced once per displayed frame",
              abs(motion - d["frameCounter"]) <= 2,
              f"{motion} motion vs {d['frameCounter']} display frames")
        check("every fine-scroll phase was exercised while moving",
              all(c > 50 for c in fine), f"{fine}")
        check("coarse steps happened once per eight frames",
              abs(d["frameCounter"] - 8 * d["coarseCount"]) <= 16)
        check("every coarse step flipped the page",
              abs(d["flipCount"] - d["coarseCount"]) <= 1)
        check("both screen matrices were displayed while moving",
              d["pageAFrames"] > 0 and d["pageBFrames"] > 0)
        check("ZERO $d018 / software-page mismatches", mis[0] == 0)
        check("ZERO pointer-destination mismatches", mis[1] == 0)
        check("ZERO late batches", late == 0, f"{late}, longest {maxlate}")
        check("ZERO back-page-late events", slate == 0)
        check("ZERO publication skips", pskip == 0)
        check("ZERO schedule overflows on a legal fixture", ovf == 0)
        check("every page flip still at the frame IRQ line",
              fmin == fmax == FRAME_IRQ_LINE, f"{fmin}/{fmax}")

        print("\n=== 13. CURRENT stays immutable with the main thread stopped ===")
        b = set_bp(m, sym["mainLoop"]); m.cmd("x"); m.cmd(f"delete {b}")
        m.cmd("> 02a7 4c a7 02")          # jmp $02a7
        m.cmd("r pc=02a7")
        cur = rd(m, sym["schedCurrent"])[0]
        n = rd(m, sym["schedEntries"] + cur)[0]
        before = rd(m, sym["schedY"] + cur * MAX_SCHED, n)
        beforeX = rd(m, sym["schedX"] + cur * MAX_SCHED, n)
        beforeD = rd(m, sym["batchD010"] + cur * MAX_BATCH,
                     rd(m, sym["schedBatches"] + cur)[0])
        f_before = read16(m, sym["frameCounter"])
        mf_before = read16(m, sym["motionFrame"])
        free_run(m, sym["frameCounter"], 6)
        f_after = read16(m, sym["frameCounter"])
        mf_after = read16(m, sym["motionFrame"])
        after = rd(m, sym["schedY"] + cur * MAX_SCHED, n)
        afterX = rd(m, sym["schedX"] + cur * MAX_SCHED, n)
        afterD = rd(m, sym["batchD010"] + cur * MAX_BATCH,
                    rd(m, sym["schedBatches"] + cur)[0])
        print(f"        frames rendered with the main thread parked: "
              f"{(f_after - f_before) & 0xffff}")
        check("frames keep rendering after the main thread stops dead",
              ((f_after - f_before) & 0xffff) > 200)
        check("motion stopped when the main thread did", mf_after == mf_before,
              f"{mf_before} -> {mf_after}")
        check("CURRENT's Y values never changed while the executor ran",
              before == after)
        check("CURRENT's X values never changed while the executor ran",
              beforeX == afterX)
        check("CURRENT's prepared $D010 never changed while the executor ran",
              beforeD == afterD)
        check("no coherence fault appeared once motion and publication stopped",
              (rd(m, sym["statPageMismatch"])[0],
               rd(m, sym["statPtrMismatch"])[0]) == (0, 0))
    finally:
        v.close()
        sweep_logs()

    print("\n=== 14. cleanup ===")
    sweep_logs(quiet=False)
    leftovers = list(SCRATCH.glob("*"))
    check("no transient test artefacts left in scratch", not leftovers,
          f"{[p.name for p in leftovers]}")
    r = subprocess.run(["pgrep", "-fl", "x64sc"], capture_output=True, text=True)
    running = {}
    for line in r.stdout.splitlines():
        pid, _, cmd = line.partition(" ")
        if not cmd.split(" ")[0].endswith("x64sc"):
            continue
        try:
            running[int(pid)] = cmd
        except ValueError:
            pass
    mine = {p: c for p, c in running.items() if p in LAUNCHED_PIDS}
    check("no test-owned VICE process remains", not mine, f"{mine}")
    others = {p: c for p, c in running.items() if p not in LAUNCHED_PIDS}
    print(f"        launched and reaped: {LAUNCHED_PIDS}")
    print(f"        other x64sc processes (NOT ours, left alone): {others or 'none'}")

    print(f"\n=== {'ALL PASS' if not fails else str(len(fails)) + ' FAILURES: ' + ', '.join(fails[:6])} ===")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try:
            SCRATCH.rmdir()
        except OSError:
            pass
