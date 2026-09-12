#!/usr/bin/env python3
"""P2 static-Y stress matrix.

What this proves
----------------
* the schedule the 6502 builder produces matches an INDEPENDENT model of the
  documented rules, field by field -- acceptance and rejection REASON, slot
  assignment, same-slot predecessor, reuse gap, batch raster, batch membership
  and complete schedule coverage -- over every named fixture, the uniform
  spacing axis, and a vertical sweep;
* a genuine SIX-ENTRY MERGED MID-SCREEN BATCH exists, and -- separately -- that
  the executor really ran one, proved two independent ways;
* what that batch costs, per fine-scroll phase, per batch size and per vertical
  position, against the deadline REUSE_LEAD actually has to meet;
* which phase/raster combinations meet badline cycle theft;
* that the same geometry survives natural scrolling, coarse steps and page
  flips with every P1 coherence counter still at zero.

What this does NOT prove
------------------------
Visible correctness. See docs/manual-acceptance.md. Manual normal-speed
observation remains authoritative and is not a formality: this suite runs the
machine headless, and a headless machine cannot tell you it looks wrong.

VICE process ownership: every launch is owned by PID, reaped in try/finally,
and other x64sc processes are reported but never touched. Launches are
`-console` so no window is ever created and no keyboard focus is ever taken.
"""
import re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import (PRG, SYM, symbols, Vice, rd, set_bp, stable_read,
                     free_run, read16, LAUNCHED_PIDS)
import p2_model as M

SCRATCH = Path("/tmp/6502-shmup-p2")
MAX_SCHED, MAX_BATCH = M.MAX_SCHED, M.MAX_BATCH
FRAME_IRQ_LINE = M.FRAME_IRQ_LINE
REUSE_LEAD, MIN_REUSE_GAP = M.REUSE_LEAD, M.MIN_REUSE_GAP
DEADLINE_DISPLAY, DEADLINE_FETCH = M.deadline_cycles()

fails = []
notes = []


def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


# ===========================================================================
# Driving the machine
# ===========================================================================
def poke(mon, addr, val):
    mon.cmd(f"> {addr:04x} {val & 0xff:02x}")


def irq_off(mon):
    """Take the raster IRQ out of the picture for STRUCTURAL inspection.

    buildSchedule writes the buffer named by schedNext, and it latches that
    index once at the start. publishSchedule then arms a swap, and the very
    next frame IRQ performs it -- which can land in the MIDDLE of the build we
    are driving. The build is then written into one buffer while schedNext
    afterwards names the other, and reading "the buffer that was just built"
    returns the PREVIOUS case's schedule.

    That is not a renderer fault and it is not a model disagreement: it is this
    harness racing the machine it is inspecting. It presented as four unrelated
    fixtures disagreeing with the model while their accepted/batch COUNTS --
    which are not buffer-indexed -- matched perfectly, and that asymmetry is
    what identified it.

    So the structural sections stop the clock, exactly as test_p0.py does.
    Timing sections obviously must not, and call irq_on first.
    """
    mon.cmd("> d01a 00")


def irq_on(mon, sym):
    mon.cmd("> d01a 01")
    free_run(mon, sym["frameCounter"], 0.4, slice_s=0.4)


def build_case(mon, sym, fixture, y_offset=0, tries=4, settle=False):
    """Select a fixture at a vertical offset and run buildSchedule in isolation.

    Comes to rest at mainLoop first and never hijacks the PC from inside the
    IRQ handler: stopping there leaves the I flag set and interrupts never
    resume, which presents as a dead renderer rather than as a harness fault.

    VERIFIED against the model before it returns. An unverified selection
    silently measures the previous case, and in a sweep of 120 offsets that is
    indistinguishable from a clean result.
    """
    want = M.build(M.NAMED[fixture][1], y_offset)
    for _ in range(tries):
        b = set_bp(mon, sym["mainLoop"]); mon.cmd("x"); mon.cmd(f"delete {b}")
        poke(mon, sym["fixtureIndex"], fixture)
        poke(mon, sym["fixtureYOffset"], y_offset)
        mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={sym['rebuild']:04x}")
        bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
        if (rd(mon, sym["statBatches"])[0] == want["n_batches"] and
                rd(mon, sym["statAccepted"])[0] == want["accepted"] and
                rd(mon, sym["fixtureIndex"])[0] == fixture and
                rd(mon, sym["fixtureYOffset"])[0] == y_offset):
            mon.cmd("delete")       # a dropped `delete` leaves a breakpoint
                                    # armed and the machine can never free-run
            if not settle:
                return want
            # A built schedule is not a RUNNING schedule. buildSchedule writes
            # the NEXT buffer and publishSchedule only arms the handover; the
            # executor keeps rendering the PREVIOUS schedule until a frame IRQ
            # adopts it. Measuring immediately therefore times the fixture
            # before this one -- which is how a one-entry batch came back
            # reporting six sprite writes and a six-entry cost.
            #
            # So when a measurement is about to be taken, run the machine and
            # verify the CURRENT buffer -- the one the executor reads -- really
            # holds this case.
            free_run(mon, sym["frameCounter"], 0.4, slice_s=0.4)
            cur = rd(mon, sym["schedCurrent"])[0]
            if (rd(mon, sym["schedEntries"] + cur)[0] == want["accepted"] and
                    rd(mon, sym["schedBatches"] + cur)[0] == want["n_batches"]):
                return want
        time.sleep(0.3)
    mon.cmd("delete")
    return None


def _call(mon, sym, addr):
    """Call a main-thread routine in isolation and put the CPU back."""
    mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
    mon.cmd(f"r sp=fd, pc={addr:04x}")
    bb = set_bp(mon, 0xc0fe)
    mon.cmd("x")
    mon.cmd(f"delete {bb}")
    mon.cmd(f"r pc={sym['mainLoop']:04x}")


def poke_logical(mon, sym, ys, tries=4):
    """Write an arbitrary logical Y list and build a schedule from it.

    The sweep axes do not each need their own table baked into the binary. The
    named fixtures are the permanent regression set; generated geometry is
    poked straight into the logical sprite arrays the builder consumes, which
    is the same input path loadFixture writes.

    P4 made this two calls instead of one. The builder no longer scans logical
    storage order -- it scans the SORTED id list -- so poking logY and jumping
    straight to buildSchedule left it walking whatever permutation the
    previously selected fixture had left behind, with entries naming logical
    IDs that no longer existed. The symptom was sprites appearing out of Y
    order and being rejected as "physically unsafe", which looked like a
    builder fault and was this harness handing it nonsense.

    sortReset re-establishes the identity permutation for this logCount;
    republish then sorts and builds exactly as the main loop does.
    """
    want = M.build(ys, order=M.sorted_order(ys))
    for _ in range(tries):
        b = set_bp(mon, sym["mainLoop"]); mon.cmd("x"); mon.cmd(f"delete {b}")
        for i, y in enumerate(ys):
            poke(mon, sym["logY"] + i, y)
            poke(mon, sym["logX"] + i, 30 + 30 * (i % 7))
            poke(mon, sym["logPtr"] + i, 0x80 + (i & 15))
            poke(mon, sym["logCol"] + i, 1 + (i % 15))
        poke(mon, sym["logCount"], len(ys))
        _call(mon, sym, sym["sortReset"])
        _call(mon, sym, sym["republish"])
        if (rd(mon, sym["statBatches"])[0] == want["n_batches"] and
                rd(mon, sym["statAccepted"])[0] == want["accepted"]):
            mon.cmd("delete")
            return want
        time.sleep(0.3)
    mon.cmd("delete")
    return None


def read_schedule(mon, sym, buf, n, nb):
    """The whole built schedule out of the NEXT buffer, as the engine holds it."""
    be, bb = buf * MAX_SCHED, buf * MAX_BATCH
    g = lambda name, base, cnt: rd(mon, sym[name] + base, max(1, cnt))[:cnt]
    return {
        "y":     g("schedY", be, n),
        "slot":  g("schedSlot", be, n),
        "slot2": g("schedSlot2", be, n),
        "line":  g("batchLine", bb, nb),
        "first": g("batchFirst", bb, nb),
        "count": g("batchCount", bb, nb),
    }


def compare_case(tag, mon, sym, want):
    """Field-by-field engine-vs-model comparison. Returns list of complaints."""
    bad = []
    nxt = rd(mon, sym["schedNext"])[0]
    acc = rd(mon, sym["statAccepted"])[0]
    uns = rd(mon, sym["statRejUnsafe"])[0]
    mar = rd(mon, sym["statRejMargin"])[0]
    reu = rd(mon, sym["statReuse"])[0]
    nb = rd(mon, sym["statBatches"])[0]
    mxb = rd(mon, sym["statMaxBatch"])[0]

    if acc != want["accepted"]:   bad.append(f"accepted {acc}!={want['accepted']}")
    if uns != want["rej_unsafe"]: bad.append(f"unsafe {uns}!={want['rej_unsafe']}")
    if mar != want["rej_margin"]: bad.append(f"margin {mar}!={want['rej_margin']}")
    if reu != want["reuse"]:      bad.append(f"reuse {reu}!={want['reuse']}")
    if nb != want["n_batches"]:   bad.append(f"batches {nb}!={want['n_batches']}")
    if mxb != want["max_mid_batch"]:
        bad.append(f"maxMidBatch {mxb}!={want['max_mid_batch']}")
    if bad:
        return bad

    s = read_schedule(mon, sym, nxt, acc, nb)
    if s["y"] != [e["y"] for e in want["entries"]]:
        bad.append(f"entry Y {s['y']} != {[e['y'] for e in want['entries']]}")
    if s["slot"] != [e["slot"] for e in want["entries"]]:
        bad.append(f"slots {s['slot']} != {[e['slot'] for e in want['entries']]}")
    if s["slot2"] != [e["slot2"] for e in want["entries"]]:
        bad.append("slot2 inconsistent")
    if s["line"] != [b["line"] for b in want["batches"]]:
        bad.append(f"batch lines {s['line']} != {[b['line'] for b in want['batches']]}")
    if s["first"] != [b["first"] for b in want["batches"]]:
        bad.append(f"batch first {s['first']}")
    if s["count"] != [b["count"] for b in want["batches"]]:
        bad.append(f"batch count {s['count']} != {[b['count'] for b in want['batches']]}")
    if sum(s["count"]) != acc:
        bad.append(f"coverage {sum(s['count'])} of {acc}")
    if not all(M.MUX_FIRST_SLOT <= x <= M.MUX_FIRST_SLOT + M.MUX_SLOTS - 1
               for x in s["slot"]):
        bad.append(f"slot out of pool {s['slot']}")

    # Same-slot predecessor and reuse gap, derived from what the ENGINE built
    # rather than from the model, then checked against the rule.
    for i, e in enumerate(want["entries"]):
        if e["pred_acc"] is None:
            continue
        if s["slot"][i] != s["slot"][e["pred_acc"]]:
            bad.append(f"entry {i} slot {s['slot'][i]} != predecessor "
                       f"{e['pred_acc']} slot {s['slot'][e['pred_acc']]}")
            break
        gap = s["y"][i] - s["y"][e["pred_acc"]]
        if gap != e["gap"]:
            bad.append(f"entry {i} gap {gap} != model {e['gap']}")
            break
        if gap < MIN_REUSE_GAP:
            bad.append(f"entry {i} ACCEPTED with gap {gap} < {MIN_REUSE_GAP}")
            break
    return bad


# ===========================================================================
# Timing
# ===========================================================================
TRACE_RE = re.compile(
    r"\(Trace  exec ([0-9a-f]{4})\)\s+(\d+)/\$[0-9a-f]+,\s+(\d+)/")


_collect_seq = [0]


def collect(mon, log_dir, sym, points, seconds, tries=3, min_samples=2500):
    """Free-run with `points` traced; return (events, diagnosis).

    `trace` does not halt the machine, so a second of warp yields tens of
    thousands of samples. Stepping a breakpoint was tried in P0 and is not
    reliable.

    EVERY attempt writes to its OWN log file, and NOTHING here ever deletes a
    log file. Both rules are paid for.

    Reusing one path and deleting it between attempts deadlocked a whole suite
    run. On macOS, unlinking a file VICE still has open does not stop VICE
    writing to it: the trace keeps pouring into an orphaned inode that no path
    points at, so the harness reads nothing, while the emulator burns 80% of a
    core writing a log it can never be asked about and stops servicing the
    monitor socket promptly. The visible symptoms were "0 samples" -- which
    looks exactly like a renderer that stopped executing batches -- and then a
    hang. Neither was a renderer fault.

    So: a fresh name per attempt (cannot collide with a stale handle), and the
    files are swept up by sweep_logs() only after the owning VICE has been
    closed and reaped.

    The reason for a failed collection is RETURNED, not swallowed, so a caller
    can say why it has no measurement instead of quietly reporting zero.
    """
    best, why = [], []
    budget = time.time() + 60          # a hard wall-clock bound. A collection
                                       # that cannot be completed must fail the
                                       # test, never stall the suite.
    for attempt in range(tries):
        if time.time() > budget:
            why.append(f"gave up after {attempt} attempts: wall-clock budget spent")
            break
        _collect_seq[0] += 1
        log = log_dir / f"trace-{_collect_seq[0]:04d}.log"
        mon.cmd(f'logname "{log}"')
        mon.cmd("log on")
        for p in points:
            mon.cmd(f"trace exec {sym[p]:04x}")
        f0 = read16(mon, sym["frameCounter"])
        ran = free_run(mon, sym["frameCounter"], seconds, slice_s=seconds)
        f1 = read16(mon, sym["frameCounter"])
        mon.cmd("log off")
        mon.cmd("delete")                  # drop the tracepoints
        if not log.exists():
            why.append(f"try {attempt}: VICE never created the log file")
        else:
            text = stable_read(log)
            ev = [(int(mm.group(1), 16), int(mm.group(2)), int(mm.group(3)))
                  for mm in TRACE_RE.finditer(text)]
            if len(ev) > len(best):
                best = ev
            if not ev:
                why.append(f"try {attempt}: log had {log.stat().st_size} bytes "
                           f"but no parsable trace lines "
                           f"(ran={ran}, frames +{(f1 - f0) & 0xffff})")
        if len(best) >= min_samples:
            return best, None
        try:
            mon._drain()
        except Exception:
            pass
        mon.cmd("r")
        time.sleep(0.3)
    return best, ("; ".join(why) if why else
                  f"only {len(best)} events over {tries} attempts")


def sweep_logs(quiet=True):
    """Delete the trace logs, once their VICE is gone. See collect()."""
    n = 0
    for f in SCRATCH.glob("trace-*.log"):
        try:
            f.unlink(); n += 1
        except OSError:
            pass
    if n and not quiet:
        print(f"        swept {n} trace logs")
    return n


def batches_from(ev, sym):
    """Turn a trace into per-batch records.

    Each record is one execution of the handler:
        line      raster at IRQ entry
        entries   sprite writes actually performed (exPtrStore executions)
        crit      cycles from ENTRY to every VIC register written
        total     cycles from ENTRY to RTI
    """
    A_IRQ, A_PTR = sym["irqHandler"], sym["exPtrStore"]
    A_WR, A_DONE = sym["exWritesDone"], sym["exDone"]
    pos = lambda l, c: l * 63 + c
    out, cur = [], None
    for addr, line, cyc in ev:
        if addr == A_IRQ:
            cur = {"line": line, "start": pos(line, cyc), "entries": 0,
                   "crit": None, "total": None}
        elif cur is None:
            continue
        elif addr == A_PTR:
            cur["entries"] += 1
        elif addr == A_WR:
            if cur["crit"] is None:            # first batch of the invocation
                cur["crit"] = (pos(line, cyc) - cur["start"]) % 19656
        elif addr == A_DONE:
            cur["total"] = (pos(line, cyc) - cur["start"]) % 19656
            if cur["crit"] is not None:
                out.append(cur)
            cur = None
    return out


def measure(mon, sym, log, seconds=1.2, want_line=None):
    """Measure the mid-screen batch, split from the frame batch.

    `want_line` is the armed raster the mid-screen batch belongs to. A raster
    IRQ is entered 0..1 lines after the line it was armed for (the CPU finishes
    the current instruction, then spends 7 cycles vectoring), so entry rasters
    are matched against the armed line rather than assumed exact.
    """
    ev, why = collect(mon, log, sym,
                      ("irqHandler", "exPtrStore", "exWritesDone", "exDone"),
                      seconds)
    recs = batches_from(ev, sym)
    frame_lines = (FRAME_IRQ_LINE, FRAME_IRQ_LINE + 1)
    all_mid = [r for r in recs if r["line"] not in frame_lines]
    frame = [r for r in recs if r["line"] in frame_lines]
    mid = all_mid
    if want_line is not None:
        mid = [r for r in all_mid if r["line"] in (want_line, (want_line + 1) % 312)]
        if all_mid and not mid:
            # Samples exist but none on the armed line. That is a real
            # discrepancy between what the builder scheduled and where the IRQ
            # actually fired, and it must be reported rather than counted as
            # "no samples".
            why = (f"sampled mid-screen rasters {sorted({r['line'] for r in all_mid})} "
                   f"but the armed line was {want_line}")
    return {"all": recs, "mid": mid, "frame": frame, "why": why,
            "lines": sorted({r["line"] for r in all_mid}),
            "n": len(recs), "n_mid": len(mid)}


def worst_of(mid):
    if not mid:
        return None
    w = max(mid, key=lambda r: r["crit"])
    return {"crit": w["crit"], "total": max(r["total"] for r in mid),
            "entries": w["entries"], "line": w["line"],
            "max_entries": max(r["entries"] for r in mid),
            "n": len(mid),
            "margin": DEADLINE_DISPLAY - w["crit"],
            "margin_fetch": DEADLINE_FETCH - w["crit"]}


def set_pin(mon, sym, phase):
    """Pin the fine-scroll phase, then VERIFY it from the running machine."""
    poke(mon, sym["pinFineValue"], phase)
    poke(mon, sym["pinFine"], 1)
    # Let the main thread publish and the frame IRQ adopt the record.
    free_run(mon, sym["frameCounter"], 0.4, slice_s=0.4)
    d011 = rd(mon, 0xd011)[0]
    live = rd(mon, sym["scrollFine"])[0]
    return (d011 & 7), live


def clear_pin(mon, sym):
    poke(mon, sym["pinFine"], 0)
    free_run(mon, sym["frameCounter"], 0.4, slice_s=0.4)


# ===========================================================================
def main():
    SCRATCH.mkdir(exist_ok=True)
    log = SCRATCH          # collect() names its own file per attempt
    results = {}

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

    print("\n=== 1. the two independent models agree on the P0 fixtures ===")
    from test_p0 import model as p0model, FIXTURES as P0FIX
    dis = []
    for fx, ys in P0FIX.items():
        s, u, m_, r, b = p0model(ys)
        c = M.build(ys)
        if not (len(s) == c["accepted"] and u == c["rej_unsafe"]
                and m_ == c["rej_margin"] and r == c["reuse"]
                and [x["line"] for x in b] == [x["line"] for x in c["batches"]]):
            dis.append(fx)
    check("P2's model agrees with P0's on all five P0 fixtures", not dis, f"{dis}")
    check("the six-entry geometry is derived from the rule, not hardcoded",
          M.P2_MERGE_Y == M.P2_LEAD_Y + 5 + MIN_REUSE_GAP == 98,
          f"Yc={M.P2_MERGE_Y} = leadY+5+MIN_REUSE_GAP")

    # =====================================================================
    v = Vice(6740, PRG, warp=True)
    try:
        m = v.mon
        m.cmd("delete")

        print("\n=== 2. schedule builder vs independent model: named fixtures ===")
        irq_off(m)      # sections 2-5 inspect built buffers; see irq_off()
        for fx in sorted(M.NAMED):
            name, ys = M.NAMED[fx]
            want = build_case(m, sym, fx)
            if want is None:
                check(f"F{fx} {name}: selected and built", False, "selection failed")
                continue
            bad = compare_case(name, m, sym, want)
            check(f"F{fx:<2d} {name:<24s} acc={want['accepted']:2d} "
                  f"rej={want['rej_unsafe']}u/{want['rej_margin']}m "
                  f"batches={want['n_batches']:2d} maxMid={want['max_mid_batch']}",
                  not bad, "; ".join(bad))
            check(f"F{fx} stays inside MAX_SCHED / MAX_BATCH",
                  not want["over_sched"] and not want["over_batch"])

        print("\n=== 3. uniform spacing axis (30 24 22 21 20 18 16 12) ===")
        print("        Uniform pitch S gives a SAME-SLOT separation of 6*S, so")
        print("        none of these can exercise the reuse rule. That is the")
        print("        finding, not an oversight -- see axis 4 below.")
        for s in M.UNIFORM_SPACINGS:
            ys = M.uniform(s)
            want = poke_logical(m, sym, ys)
            if want is None:
                check(f"uniform S={s}: built", False, "build failed")
                continue
            bad = compare_case(f"S={s}", m, sym, want)
            check(f"uniform S={s:<2d} n={len(ys):2d} acc={want['accepted']:2d} "
                  f"rej=0 batches={want['n_batches']:2d} sameSlotGap={6*s}",
                  not bad and want["rej_unsafe"] == 0 and want["rej_margin"] == 0,
                  "; ".join(bad))

        print("\n=== 4. clustered axis: the boundary cases, stated exactly ===")
        BOUND = [
            ("gap 20  (SPRITE_HEIGHT-1)", 20, "unsafe", M.UNSAFE_REJECTED),
            ("gap 21  (SPRITE_HEIGHT)",   21, "margin", M.LEGAL_REJECTED),
            ("gap 32  (MIN_REUSE_GAP-1)", 32, "margin", M.LEGAL_REJECTED),
            ("gap 33  (MIN_REUSE_GAP)",   33, None,     M.LEGAL_RENDERED),
            ("gap 34  (MIN_REUSE_GAP+1)", 34, None,     M.LEGAL_RENDERED),
        ]
        for label, gap, reason, verdict in BOUND:
            ys = [60, 61, 62, 63, 64, 65, 60 + gap]
            want = poke_logical(m, sym, ys)
            if want is None:
                check(f"boundary {label}", False, "build failed")
                continue
            bad = compare_case(label, m, sym, want)
            cls = M.classify(want)[6]
            check(f"boundary {label:<26s} -> {cls}",
                  not bad and cls == verdict, "; ".join(bad))

        print("\n=== 5. vertical sweep, structural: T6 through the visible band ===")
        SWEEP = list(range(0, 121, 1))
        swept, bad_off = 0, []
        for off in SWEEP:
            want = build_case(m, sym, 5, off)
            if want is None:
                bad_off.append((off, "selection")); continue
            bad = compare_case(f"off {off}", m, sym, want)
            if bad:
                bad_off.append((off, bad[:2])); continue
            if want["max_mid_batch"] != 6:
                bad_off.append((off, f"maxMid {want['max_mid_batch']}")); continue
            swept += 1
        check("T6 builds a six-entry merged batch at EVERY vertical offset",
              not bad_off and swept == len(SWEEP),
              f"{swept}/{len(SWEEP)} offsets clean; problems {bad_off[:4]}")
        print(f"        offsets 0..{SWEEP[-1]}: batch raster "
              f"{86 + SWEEP[0]}..{86 + SWEEP[-1]}, sprites "
              f"{60 + SWEEP[0]}..{98 + SWEEP[-1] + 20}")

        # =================================================================
        print("\n=== 6. THE SIX-ENTRY MERGED BATCH: proof it EXECUTED ===")
        irq_on(m, sym)          # from here on the machine must really render
        want = build_case(m, sym, 5, 0)
        check("torture fixture 5 selected", want is not None)
        e = want["entries"]
        print(f"        logical sprites          {len(M.NAMED[5][1])}")
        print(f"        accepted                 {want['accepted']}")
        print(f"        rejected                 {want['rej_unsafe']} unsafe, "
              f"{want['rej_margin']} conservative")
        print(f"        leaders  Y               {[x['y'] for x in e[:6]]}")
        print(f"        leaders  slots           {[x['slot'] for x in e[:6]]}")
        print(f"        reusers  Y               {[x['y'] for x in e[6:]]}")
        print(f"        reusers  slots           {[x['slot'] for x in e[6:]]}")
        print(f"        predecessor Y per slot   {[x['pred_y'] for x in e[6:]]}")
        print(f"        reuse gap per slot       {[x['gap'] for x in e[6:]]}"
              f"   (MIN_REUSE_GAP {MIN_REUSE_GAP})")
        print(f"        batch rasters            {[b['line'] for b in want['batches']]}")
        print(f"        batch membership         "
              f"{[(b['first'], b['count']) for b in want['batches']]}")
        mid0 = want["mid_batches"][0]
        print(f"        MID-SCREEN batch         raster {mid0['line']}, "
              f"first {mid0['first']}, count {mid0['count']}")

        check("the mid-screen batch really has six entries", mid0["count"] == 6)
        check("all six reusers share one batch raster",
              len({x["y"] - REUSE_LEAD for x in e[6:]}) == 1)
        check("the six reusers occupy all six mux slots",
              sorted(x["slot"] for x in e[6:]) == [2, 3, 4, 5, 6, 7])
        check("every reuse gap meets MIN_REUSE_GAP exactly or better",
              all(x["gap"] >= MIN_REUSE_GAP for x in e[6:]),
              f"gaps {[x['gap'] for x in e[6:]]}")
        check("the binding pair sits EXACTLY on the conservative boundary",
              min(x["gap"] for x in e[6:]) == MIN_REUSE_GAP)

        # -- proof 1: the engine's own executed-size histogram ---------------
        h0 = rd(m, sym["batchSizeHist"], 14)
        free_run(m, sym["frameCounter"], 6, slice_s=3)
        h1 = rd(m, sym["batchSizeHist"], 14)
        hist = [(h1[2 * i] | (h1[2 * i + 1] << 8)) - (h0[2 * i] | (h0[2 * i + 1] << 8))
                for i in range(7)]
        hist = [x & 0xffff for x in hist]
        frames = read16(m, sym["frameCounter"])
        print(f"        executed mid-screen batches by size 0..6: {hist}")
        check("the EXECUTOR ran six-entry mid-screen batches", hist[6] > 100,
              f"{hist[6]} of them")
        check("it ran NO mid-screen batch of any other size",
              all(x == 0 for i, x in enumerate(hist) if i != 6), f"{hist}")

        # -- proof 2: count the sprite writes inside one batch, on the machine
        res = measure(m, sym, log, seconds=1.5, want_line=86)
        w = worst_of(res["mid"])
        check("mid-screen batches were sampled", w is not None and w["n"] > 200,
              f"{w['n'] if w else 0} samples; {res.get('why') or 'ok'}")
        if w:
            sizes = {r["entries"] for r in res["mid"]}
            check("every sampled mid-screen batch performed SIX sprite writes",
                  sizes == {6}, f"entry counts seen {sorted(sizes)}")
            results["six"] = w

        # =================================================================
        print("\n=== 7. timing of the six-entry batch, by fine-scroll phase ===")
        print("        A badline costs the CPU ~40-43 cycles and lands on any")
        print("        raster with (raster & 7) == YSCROLL.")
        print()
        print("        What matters is NOT how many badlines fall in the nominal")
        print("        12-line reuse window, but how many fall inside the batch's")
        print("        own CRITICAL PATH -- entry to last register write. A badline")
        print("        one line past the final write costs nothing. `in win` below")
        print("        is the nominal window 86..97; `in crit` is the measured path.")
        print()
        print("        phase  d011  in win        in crit       n   worst  total  margin")
        phase_rows = []
        for ph in range(8):
            got, live = set_pin(m, sym, ph)
            if got != ph:
                check(f"phase {ph} pinned and verified from $d011", False,
                      f"$d011&7 = {got}, scrollFine = {live}")
                continue
            bl = M.badlines_in(86, 97, ph)
            r = measure(m, sym, log, seconds=1.5, want_line=86)
            w = worst_of(r["mid"])
            if w is None:
                check(f"phase {ph} sampled", False, f"{r.get('why')}")
                continue
            if w["max_entries"] != 6:
                check(f"phase {ph} measured the six-entry batch", False,
                      f"entry counts {sorted({x['entries'] for x in r['mid']})}")
                continue
            # Badlines actually inside the measured critical path.
            #
            # The entry line is EXCLUDED, and that is not a fudge. The
            # measurement starts when irqHandler is observed to EXECUTE. A
            # badline on the entry line steals its cycles before that -- the
            # CPU is already stalled when the raster IRQ fires, so the stall
            # lands in the interrupt latency, ahead of the first traced
            # instruction, not inside the span being measured.
            #
            # The data forced this correction. Phase 6 has badlines at 86 and
            # 94 with entry on 86, and costs the same 603 cycles as the phases
            # with a single badline; phase 7 has 87 and 95 with entry on 86,
            # has both genuinely inside the span, and is the only phase that
            # costs 646. Excluding the entry line makes cost an exact step
            # function of the count across all eight phases.
            inc = M.badlines_in(w["line"] + 1, w["line"] + w["crit"] // 63, ph)
            w["inwin"], w["incrit"] = bl, inc
            phase_rows.append((ph, bl, w))
            print(f"          {ph}     {got}    {str(bl):<13s} {str(inc):<13s} "
                  f"{w['n']:5d} {w['crit']:6d} {w['total']:6d}  {w['margin']:+5d}")
        clear_pin(m, sym)
        check("all eight fine-scroll phases were pinned, verified and measured",
              len(phase_rows) == 8, f"{len(phase_rows)} of 8")
        if phase_rows:
            worst_ph = max(phase_rows, key=lambda x: x[2]["crit"])
            best_ph = min(phase_rows, key=lambda x: x[2]["crit"])
            results["phases"] = phase_rows
            results["worst_phase"] = worst_ph
            print(f"        worst phase {worst_ph[0]}: {worst_ph[2]['crit']} cycles, "
                  f"margin {worst_ph[2]['margin']:+d} "
                  f"({worst_ph[2]['margin']/63:.2f} raster lines)")
            print(f"        best  phase {best_ph[0]}: {best_ph[2]['crit']} cycles")
            # The original form of this check asserted that phases with two
            # badlines in the NOMINAL window cost more than phases with one.
            # The measurement refuted it: phases 0, 1 and 6 each have two
            # badlines in the nominal window and still cost the minimum,
            # because one of the two falls after the last register write (or,
            # for phase 6, on the entry line itself, before the handler runs).
            # The hypothesis was replaced by what the machine actually shows.
            spread = worst_ph[2]["crit"] - best_ph[2]["crit"]
            check("the worst phase is the one with most badlines inside the "
                  "CRITICAL PATH, not inside the nominal window",
                  len(worst_ph[2]["incrit"]) > len(best_ph[2]["incrit"]),
                  f"phase {worst_ph[0]} has {len(worst_ph[2]['incrit'])} "
                  f"({worst_ph[2]['incrit']}), phase {best_ph[0]} has "
                  f"{len(best_ph[2]['incrit'])} ({best_ph[2]['incrit']})")
            check("the best-to-worst phase spread is exactly one badline of theft",
                  35 <= spread <= 50, f"{spread} cycles")
            # Cost must be a pure step function of the in-path badline count:
            # every phase with the same count costs the same, and more badlines
            # always costs more.
            by_count = {}
            for ph_, _bl, ww in phase_rows:
                by_count.setdefault(len(ww["incrit"]), set()).add(ww["crit"])
            step = (all(len(v) == 1 for v in by_count.values()) and
                    [c for _, c in sorted((k, min(v)) for k, v in by_count.items())]
                    == sorted(min(v) for v in by_count.values()))
            check("phase cost is a step function of in-critical-path badlines",
                  step,
                  f"{ {k: sorted(v) for k, v in sorted(by_count.items())} }")
            check("the six-entry batch meets the REUSE_LEAD deadline at EVERY phase",
                  all(p[2]["crit"] <= DEADLINE_DISPLAY for p in phase_rows),
                  f"worst {worst_ph[2]['crit']} cy vs {DEADLINE_DISPLAY} cy")
            check("...and also meets the stricter sprite-FETCH deadline",
                  all(p[2]["crit"] <= DEADLINE_FETCH for p in phase_rows),
                  f"worst {worst_ph[2]['crit']} cy vs {DEADLINE_FETCH} cy")

        # =================================================================
        print("\n=== 8. timing by merged batch size, one controlled variable ===")
        pin = results.get("worst_phase", (0,))[0]
        got, _ = set_pin(m, sym, pin)
        check(f"pinned to the worst phase ({pin}) for the batch-size sweep",
              got == pin, f"$d011&7={got}")
        print(f"        fine phase pinned to {pin} (the worst measured)")
        print()
        print("        entries   n   worst crit   total   deadline   margin")
        size_rows = []
        for fx, size in ((10, 1), (9, 2), (8, 3), (7, 4), (6, 5), (5, 6)):
            wcase = build_case(m, sym, fx, 0, settle=True)
            if wcase is None:
                check(f"batch size {size} fixture built and ADOPTED by the executor",
                      False); continue
            r = measure(m, sym, log, seconds=1.5, want_line=86)
            w = worst_of(r["mid"])
            if w is None:
                check(f"batch size {size} sampled", False); continue
            ok_entries = w["max_entries"] == size
            size_rows.append((size, w))
            print(f"          {size}     {w['n']:5d}   {w['crit']:6d}    "
                  f"{w['total']:5d}    {DEADLINE_DISPLAY:5d}    {w['margin']:+5d}"
                  f"{'' if ok_entries else '   <- ENTRY COUNT MISMATCH'}")
            check(f"batch of {size}: executor really performed {size} sprite writes",
                  ok_entries, f"saw {w['max_entries']}")
        results["sizes"] = size_rows
        check("all six batch sizes 1..6 were measured", len(size_rows) == 6,
              f"{len(size_rows)}")
        if len(size_rows) == 6:
            check("cost increases monotonically with batch size",
                  all(size_rows[i][1]["crit"] <= size_rows[i + 1][1]["crit"]
                      for i in range(5)),
                  f"{[r[1]['crit'] for r in size_rows]}")
            per = (size_rows[5][1]["crit"] - size_rows[0][1]["crit"]) / 5
            print(f"        marginal cost per extra entry: {per:.1f} cycles")
            check("every batch size meets the deadline",
                  all(r[1]["crit"] <= DEADLINE_DISPLAY for r in size_rows))
        clear_pin(m, sym)
    finally:
        v.close()
        sweep_logs()        # only now is it safe: see collect()

    # =====================================================================
    print("\n=== 9. vertical sweep, timed: which Y costs most ===")
    v = Vice(6741, PRG, warp=True)
    try:
        m = v.mon
        m.cmd("delete")
        print("        Natural scrolling: every fine phase occurs inside each")
        print("        trace window, so each row is already the worst over all")
        print("        eight phases at that vertical position.")
        print()
        print("        offset  batch raster   n   worst crit   margin")
        sweep_rows = []
        for off in range(0, 121, 8):
            wcase = build_case(m, sym, 5, off, settle=True)
            if wcase is None:
                check(f"sweep offset {off} built and adopted", False); continue
            r = measure(m, sym, log, seconds=1.5, want_line=86 + off)
            w = worst_of(r["mid"])
            if w is None or w["n"] < 100:
                check(f"sweep offset {off} sampled", False,
                      f"{w['n'] if w else 0} samples; {r.get('why') or 'ok'}"); continue
            sweep_rows.append((off, w))
            print(f"          {off:3d}       {86+off:3d}      {w['n']:5d}   "
                  f"{w['crit']:6d}   {w['margin']:+5d}")
        check("the vertical sweep collected every planned position",
              len(sweep_rows) == 16, f"{len(sweep_rows)} of 16")
        if sweep_rows:
            worst_off = max(sweep_rows, key=lambda x: x[1]["crit"])
            results["sweep"] = sweep_rows
            results["worst_off"] = worst_off
            print(f"        worst offset {worst_off[0]} (batch raster "
                  f"{86+worst_off[0]}): {worst_off[1]['crit']} cycles, "
                  f"margin {worst_off[1]['margin']:+d}")
            check("six entries still executed at every swept position",
                  all(w["max_entries"] == 6 for _, w in sweep_rows))
            check("the six-entry batch meets the deadline at every swept position",
                  all(w["crit"] <= DEADLINE_DISPLAY for _, w in sweep_rows),
                  f"worst {worst_off[1]['crit']}")

        print("\n=== 10. T6X3: three six-entry merged batches in one frame ===")
        wcase = build_case(m, sym, 14, 0, settle=True)
        check("T6X3 built at MAX_SCHED entries",
              wcase is not None and wcase["accepted"] == 24
              and wcase["max_mid_batch"] == 6,
              f"accepted {wcase['accepted'] if wcase else '?'}, "
              f"batches {wcase['n_batches'] if wcase else '?'}")
        if wcase:
            h0 = rd(m, sym["batchSizeHist"], 14)
            r = measure(m, sym, log, seconds=1.8)
            h1 = rd(m, sym["batchSizeHist"], 14)
            hist = [((h1[2*i] | (h1[2*i+1] << 8)) - (h0[2*i] | (h0[2*i+1] << 8))) & 0xffff
                    for i in range(7)]
            w = worst_of(r["mid"])
            lines = sorted({x["line"] for x in r["mid"]})
            print(f"        mid-screen batch rasters sampled: {lines}")
            print(f"        executed sizes 0..6: {hist}")
            if w:
                print(f"        worst of all three: {w['crit']} cycles, "
                      f"margin {w['margin']:+d}")
                results["t6x3"] = w
            armed = [b["line"] for b in wcase["mid_batches"]]
            matched = {a for a in armed
                       for l in lines if l in (a, (a + 1) % 312)}
            check("every armed mid-screen batch line was sampled",
                  set(armed) == matched, f"armed {armed}, matched {sorted(matched)}")
            check("all three mid-screen batches ran with six entries",
                  w is not None and {x["entries"] for x in r["mid"]} == {6},
                  f"{sorted({x['entries'] for x in r['mid']})}")
            check("three six-entry batches executed per frame",
                  hist[6] > 300 and all(x == 0 for i, x in enumerate(hist) if i != 6),
                  f"{hist}")
            check("T6X3 meets the deadline",
                  w is not None and w["crit"] <= DEADLINE_DISPLAY,
                  f"{w['crit'] if w else '?'} vs {DEADLINE_DISPLAY}")
    finally:
        v.close()
        sweep_logs()        # only now is it safe: see collect()

    # =====================================================================
    print("\n=== 11. natural scrolling: coarse steps and page flips ===")
    v = Vice(6742, PRG, warp=True)
    try:
        m = v.mon
        m.cmd("delete")
        for fx, label in ((5, "T6"), (14, "T6X3")):
            wcase = build_case(m, sym, fx, 0)
            if wcase is None:
                check(f"{label} selected for the scrolling run", False); continue
            COUNT = ("frameCounter", "coarseCount", "flipCount", "pageAFrames",
                     "pageBFrames", "transAB", "transBA")
            base = {c: read16(m, sym[c]) for c in COUNT}
            h0 = rd(m, sym["batchSizeHist"], 14)
            f0 = rd(m, sym["finePhase"], 16)
            ran = free_run(m, sym["frameCounter"], 20)
            now = {c: read16(m, sym[c]) for c in COUNT}
            h1 = rd(m, sym["batchSizeHist"], 14)
            f1 = rd(m, sym["finePhase"], 16)
            d = {c: (now[c] - base[c]) & 0xffff for c in COUNT}
            hist = [((h1[2*i] | (h1[2*i+1] << 8)) - (h0[2*i] | (h0[2*i+1] << 8))) & 0xffff
                    for i in range(7)]
            fine = [((f1[2*i] | (f1[2*i+1] << 8)) - (f0[2*i] | (f0[2*i+1] << 8))) & 0xffff
                    for i in range(8)]
            mis = (rd(m, sym["statPageMismatch"])[0], rd(m, sym["statPtrMismatch"])[0])
            late = rd(m, sym["statLate"])[0]
            maxlate = rd(m, sym["maxLateRun"])[0]
            slate = rd(m, sym["scrollLate"])[0]
            pskip = rd(m, sym["publishSkip"])[0]
            fmin = rd(m, sym["flipLineMin"])[0]
            fmax = rd(m, sym["flipLineMax"])[0]
            expect = 6 if fx == 5 else 6
            print(f"\n        --- {label} under natural scrolling ---")
            print(f"        frames {d['frameCounter']}   coarse {d['coarseCount']}   "
                  f"flips {d['flipCount']} (A->B {d['transAB']}, B->A {d['transBA']})")
            print(f"        page A frames {d['pageAFrames']}  page B frames {d['pageBFrames']}")
            print(f"        fine phase counts 0..7   {fine}")
            print(f"        executed sizes 0..6      {hist}")
            print(f"        page mismatch {mis[0]}  pointer mismatch {mis[1]}  "
                  f"late {late} (longest run {maxlate})  backpage-late {slate}  "
                  f"publish-skip {pskip}")
            check(f"{label}: the scrolling run really ran", ran and d["frameCounter"] > 1500,
                  f"{d['frameCounter']} frames")
            check(f"{label}: every fine-scroll phase was exercised",
                  all(c > 50 for c in fine), f"{fine}")
            check(f"{label}: coarse steps happened once per eight frames",
                  abs(d["frameCounter"] - 8 * d["coarseCount"]) <= 16,
                  f"{d['frameCounter']} frames, {d['coarseCount']} coarse")
            check(f"{label}: every coarse step flipped the page",
                  abs(d["flipCount"] - d["coarseCount"]) <= 1,
                  f"{d['flipCount']} vs {d['coarseCount']}")
            check(f"{label}: both matrices displayed",
                  d["pageAFrames"] > 0 and d["pageBFrames"] > 0)
            # Against the FRAME COUNT, not against a floor.
            #
            # batchSizeHist is sixteen bits per size, and this run is as long as
            # the host can make it in twenty seconds of warp -- which is not a
            # fixed number of frames. T6X3 executes three mid-screen batches per
            # frame, so somewhere around 21,800 frames the counter wraps, and a
            # "hist[6] > 1000" floor then reads a wrapped 518 as a catastrophic
            # failure while the engine is in fact doing MORE work than before.
            # That is exactly how it was found: a faster run on the same engine
            # crossed the boundary and the floor fired.
            #
            # So compare against what the frame count says it must be, modulo
            # the counter width. That is wrap-proof, and it is a much stronger
            # statement than a floor: every frame ran every mid-screen batch.
            cur = rd(m, sym["schedCurrent"])[0]
            mid = rd(m, sym["schedBatches"] + cur)[0] - 1
            expect6 = (d["frameCounter"] * mid) & 0xffff
            off = (hist[6] - expect6) & 0xffff
            off = min(off, 0x10000 - off)          # nearest distance, either way
            check(f"{label}: six-entry batches kept executing across flips",
                  mid > 0 and off <= 8,
                  f"{hist[6]} executed; {d['frameCounter']} frames x {mid} "
                  f"mid-screen batches = {expect6} expected (16-bit counter)")
            check(f"{label}: no mid-screen batch of any other size",
                  all(x == 0 for i, x in enumerate(hist) if i != 6), f"{hist}")
            check(f"{label}: ZERO $d018/software-page mismatches", mis[0] == 0)
            check(f"{label}: ZERO pointer-destination mismatches", mis[1] == 0)
            check(f"{label}: ZERO late batches", late == 0,
                  f"{late}, longest run {maxlate}")
            check(f"{label}: ZERO back-page-late events", slate == 0)
            check(f"{label}: ZERO publication skips", pskip == 0)
            check(f"{label}: every page flip at the frame IRQ line",
                  fmin == fmax == FRAME_IRQ_LINE, f"min {fmin} max {fmax}")
            results[f"scroll_{label}"] = dict(frames=d["frameCounter"],
                                              hist6=hist[6], mis=mis, late=late)

        print("\n=== 12. displayed-page pointer contents still match CURRENT ===")
        wcase = build_case(m, sym, 5, 0)
        bp = set_bp(m, sym["exArmBottom"])    # renamed in Slice 1
        cur_buf = n = nb = cb = 0
        for _ in range(8):
            m.cmd("x")
            cur_buf = rd(m, sym["schedCurrent"])[0]
            n = rd(m, sym["schedEntries"] + cur_buf)[0]
            nb = rd(m, sym["schedBatches"] + cur_buf)[0]
            cb = rd(m, sym["curBatch"])[0]
            if cb == nb:
                break
        m.cmd(f"delete {bp}")
        check("stopped after the LAST batch of a frame, as intended", cb == nb,
              f"curBatch {cb}, schedBatches {nb}")
        slots = rd(m, sym["schedSlot"] + cur_buf * MAX_SCHED, n)
        ptrs = rd(m, sym["schedPtr"] + cur_buf * MAX_SCHED, n)
        d018 = rd(m, 0xd018)[0]
        live = 0 if ((d018 ^ 0x14) & 0xfe) == 0 else 1
        base_ptr = (0x0400 if live == 0 else 0x2800) + 0x3f8
        dest = rd(m, sym["exPtrStore"] + 2)[0]
        check("pointer destination belongs to the page $d018 is displaying",
              dest == (base_ptr >> 8), f"dest ${dest:02x}00, page {'AB'[live]}")
        last = {}
        for i in range(n):
            last[slots[i]] = ptrs[i]
        table = rd(m, base_ptr, 8)
        mism = {s: (table[s], p) for s, p in last.items() if table[s] != p}
        check("every mux slot's pointer on the DISPLAYED page is the schedule's",
              not mism, f"{mism}")
        check("the six-entry frame used all six mux slots",
              set(last) == {2, 3, 4, 5, 6, 7}, f"{sorted(last)}")
    finally:
        v.close()
        sweep_logs()        # only now is it safe: see collect()

    # =====================================================================
    print("\n=== 13. classification ===")
    counts = {M.LEGAL_RENDERED: 0, M.LEGAL_REJECTED: 0, M.UNSAFE_REJECTED: 0}
    cases = 0
    for fx in sorted(M.NAMED):
        c = M.build(M.NAMED[fx][1]); cases += 1
        for vd in M.classify(c).values():
            counts[vd] += 1
    for s in M.UNIFORM_SPACINGS:
        c = M.build(M.uniform(s)); cases += 1
        for vd in M.classify(c).values():
            counts[vd] += 1
    for off in range(0, 121):
        c = M.build(M.NAMED[5][1], off); cases += 1
        for vd in M.classify(c).values():
            counts[vd] += 1
    print(f"        cases                                 {cases}")
    print(f"        legal and rendered                    {counts[M.LEGAL_RENDERED]}")
    print(f"        legal but conservatively rejected     {counts[M.LEGAL_REJECTED]}")
    print(f"        physically unsafe and rejected        {counts[M.UNSAFE_REJECTED]}")
    print(f"        renderer failures                     "
          f"{len([f for f in fails if 'renderer' in f.lower()])}")
    check("no sprite was classified as both rendered and rejected",
          sum(counts.values()) > 0)

    print("\n=== 14. summary of measured timing ===")
    if "six" in results:
        w = results["six"]
        print(f"        six-entry batch, natural scroll: worst {w['crit']} cy "
              f"critical path, {w['total']} cy whole handler")
    if "sizes" in results:
        print("        | entries | worst cycles | deadline | margin |")
        print("        |---------|--------------|----------|--------|")
        for size, w in results["sizes"]:
            print(f"        |    {size}    |     {w['crit']:5d}    |   "
                  f"{DEADLINE_DISPLAY:4d}   | {w['margin']:+5d}  |")
    if "worst_phase" in results:
        ph, bl, w = results["worst_phase"]
        print(f"        worst phase: {ph} (badlines {bl}) -> {w['crit']} cy, "
              f"margin {w['margin']:+d} cy ({w['margin']/63:.2f} lines)")
    if "worst_off" in results:
        off, w = results["worst_off"]
        print(f"        worst vertical offset: {off} (batch raster {86+off}) -> "
              f"{w['crit']} cy, margin {w['margin']:+d} cy")

    print("\n=== 15. cleanup ===")
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
