#!/usr/bin/env python3
"""P0 structural + timing tests.

What this proves
----------------
* the schedule the 6502 builder produces matches an INDEPENDENT Python model of
  the documented rules (six-slot round robin, MIN_REUSE_GAP, batch merging);
* accepted / conservatively-rejected / unsafe-rejected counts are as designed;
* hardware slot assignment really is 2..7 and the first reuse happens at
  accepted index 6 (the six-slot model, not eight);
* the schedule fits its allocated memory;
* the executor's per-batch cost, so REUSE_LEAD can be justified rather than
  guessed.

What this does NOT prove
------------------------
Visible correctness. P0 is only GREEN after a human has watched it at normal
speed in VICE. See docs/manual-acceptance.md.

VICE process ownership: this script owns exactly the PIDs it launches, kills
them on success, failure and exception via try/finally, and reaps them.
"""
import os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRG  = ROOT / "build/shmup.prg"
SYM  = ROOT / "build/main.vs"
X64  = "/opt/homebrew/bin/x64sc"
SCRATCH = Path("/tmp/6502-shmup-p0")

# --- the documented model, reimplemented independently ----------------------
MUX_FIRST_SLOT = 2
MUX_SLOTS      = 6
SPRITE_HEIGHT  = 21
REUSE_LEAD     = 12
MIN_REUSE_GAP  = SPRITE_HEIGHT + REUSE_LEAD
FRAME_IRQ_LINE = 250
HANDOFF_LINE   = 40                         # batch 0 moved here: the HUD ->
                                            # gameplay ownership transfer
HUD_IRQ_LINE     = 4                        # the static top-border HUD phase
TOP_ARM_LINE     = 53                       # the top aperture split arms here
BORDER_OPEN_LINE = 243                      # border-open + bottom split
MAX_SPRITE_Y   = 226                        # production bound; see renderer.asm
MAX_SCHED      = 24
MAX_BATCH      = 24

# --- the two DIFFERENT batch deadlines --------------------------------------
# P0 asserted one lumped budget for every batch. That was a simplification, and
# a misleading one: REUSE_LEAD sizes MID-SCREEN slot reuse, where a batch must
# finish before the sprite it is reprogramming reaches its own Y.
#
# The frame batch is not that case. It fires in the lower border at raster 250
# and its sprites are not fetched until the earliest fixture Y, raster 55, on
# the NEXT frame: (312 - 250) + 55 = 117 raster lines = 7371 cycles. Asserting
# 756 against it measured nothing real and only held because P0 happened to fit.
PAL_LINES        = 312
MIN_SPRITE_Y     = 55                       # ALSO the production lower bound now:
                                            # the earliest Y any fixture uses and
                                            # the earliest admission allows
FRAME_BATCH_DEADLINE = ((PAL_LINES - FRAME_IRQ_LINE) + MIN_SPRITE_Y) * 63
FRAME_BATCH_BUDGET   = 2000                 # 27% of the deadline: generous, and
                                            # still a real ceiling
TRACE_SECONDS        = 2                    # of warp, free-running

FIXTURES = {
    0: [60, 90, 120, 150, 180, 210],
    1: [55, 82, 109, 136, 163, 190, 217],
    2: [55, 67, 79, 91, 103, 115, 127, 139, 151, 163, 175, 187, 199, 211],
    3: [60, 62, 64, 66, 68, 70, 72, 74],
    4: [60, 61, 62, 63, 64, 65, 80, 81, 92, 93],
}

def model(ys):
    sched, unsafe, margin, reuse, cyc = [], 0, 0, 0, 0
    for y in ys:
        # Production Y bounds, decided first: a property of the sprite alone.
        if not (MIN_SPRITE_Y <= y <= MAX_SPRITE_Y):
            continue
        if len(sched) >= MUX_SLOTS:
            gap = y - sched[len(sched) - MUX_SLOTS]["y"]
            if gap < SPRITE_HEIGHT:
                unsafe += 1; continue
            if gap < MIN_REUSE_GAP:
                margin += 1; continue
            reuse += 1
        sched.append({"y": y, "slot": MUX_FIRST_SLOT + cyc})
        cyc = (cyc + 1) % MUX_SLOTS
    batches = []
    if sched:
        n0 = min(MUX_SLOTS, len(sched))
        batches.append({"line": HANDOFF_LINE, "first": 0, "count": n0})
        i = n0
        while i < len(sched):
            line = sched[i]["y"] - REUSE_LEAD
            if batches[-1]["line"] == line:
                batches[-1]["count"] += 1
            else:
                batches.append({"line": line, "first": i, "count": 1})
            i += 1
    return sched, unsafe, margin, reuse, batches

# --- VICE monitor -----------------------------------------------------------
import socket
class Monitor:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), 10)
        self.s.settimeout(10)
        time.sleep(0.3); self._drain()
    def _drain(self):
        try:
            while True:
                if not self.s.recv(65536): break
        except Exception:
            pass
    def cmd(self, c, idle=0.30, deadline=4.0):
        """Send a command and collect the reply.

        The VICE remote monitor only emits its "(C:$xxxx)" prompt when the
        machine is stopped, so we cannot wait for it unconditionally. Read until
        the prompt appears OR the socket goes idle -- but never break on a bare
        ">", which begins every memory-dump line and previously truncated
        multi-line replies and desynchronised every following command.
        """
        self.s.sendall((c + "\n").encode())
        out = b""
        end = time.time() + deadline
        self.s.settimeout(idle)
        while time.time() < end:
            try:
                part = self.s.recv(65536)
            except socket.timeout:
                if out: break
                continue
            if not part: break
            out += part
            if b"(C:$" in out: break
        return out.decode(errors="replace")

    def close(self):
        try: self.s.close()
        except Exception: pass

def symbols(path):
    syms = {}
    for line in path.read_text().splitlines():
        m = re.match(r"al C:([0-9a-fA-F]{1,4})\s+\.?(\S+)", line)
        if m: syms[m.group(2)] = int(m.group(1), 16)
    return syms

def port_owner(port):
    """The PID listening on `port`, or None.

    Used to guarantee a suite talks to the emulator it started and no other.
    Attaching to somebody else's VICE is not a theoretical hazard: a P4 run
    whose cleanup raised left an emulator alive on its port, the next run
    connected to it instead of to the one it had just launched, and every
    measurement after that was of a machine in the previous run's state. The
    results looked like engine faults.
    """
    r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                       capture_output=True, text=True)
    pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    return pids[0] if pids else None


# Every PID this suite has ever launched. Ownership is by PID, never by
# pattern-matching `pgrep` output: the repository path appears in the command
# line of any manual VICE session the user has open on this project too, and a
# check that cannot tell those apart is one step away from killing one.
LAUNCHED_PIDS = []

class Vice:
    """Owns exactly one x64sc PID and guarantees cleanup."""
    def __init__(self, port, prg, warp=True):
        self.port, self.proc, self.mon = port, None, None
        # Same launch discipline as `make run`: +saveres so a -default run can
        # never write factory settings back over the user's own vicerc, and both
        # joystick devices detached so nothing steals host keys and drives CIA1
        # $DC00/$DC01 -- the registers the fixture-select scan uses.
        #
        # -console is NOT cosmetic and NOT an optimisation. An automated suite
        # must never open a window: x64sc's Gtk3 window takes the macOS
        # keyboard focus when it maps, and a suite launching a dozen of them
        # steals every keystroke from whatever the user is actually doing.
        # That happened, the user had to kill the emulator mid-run, and the
        # half-finished run looked exactly like a renderer fault.
        #
        # -console runs the full machine with no UI at all. The VIC-II is part
        # of the MACHINE, not the UI, so badlines, sprite DMA and cycle theft
        # are emulated the same either way. That was MEASURED before it was
        # relied on, by running this suite's timing section both ways on the
        # same binary:
        #
        #     windowed  min 247  median 289  max 871  mid-screen max 322
        #     -console  min 247  median 289  max 871  mid-screen max 322
        #
        # -- identical, over identical entry lines and sample counts. The
        # monitor `screenshot` command also still produces a correctly rendered
        # frame, so tools/capture_p0.py needs no window either.
        #
        # `make run` is unaffected and still opens a real window: manual
        # acceptance is a human watching a real display, and that is the one
        # thing this mode must never be used for.
        args = [X64, "-console", "-default", "+saveres", "-pal", "+sound",
                "-joydev1", "0", "-joydev2", "0", "+keyset", "-remotemonitor",
                "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
                "-autostartprgmode", "1", "-autostart", str(prg)]
        if warp: args.insert(1, "-warp")
        # Refuse to start on a port somebody else is already serving, rather
        # than launching a doomed second emulator and then connecting to the
        # first one by accident.
        squatter = port_owner(port)
        if squatter is not None:
            raise RuntimeError(
                f"port {port} is already served by pid {squatter}; refusing to "
                f"attach to a VICE this suite did not launch")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        LAUNCHED_PIDS.append(self.proc.pid)
        print(f"  [vice] launched pid {self.proc.pid} on port {port}")
        time.sleep(4)
        # ...and verify the machine we are about to drive really is ours.
        for _ in range(10):
            owner = port_owner(port)
            if owner == self.proc.pid:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(
                f"port {port} is served by pid {owner}, not by the pid "
                f"{self.proc.pid} this suite launched")
        self.mon = Monitor(port)
        # Handshake: the remote monitor silently drops the first commands after
        # connect. Poll until it actually answers before any test logic runs.
        for _ in range(25):
            if "(C:$" in self.mon.cmd("r"): break
            time.sleep(0.3)
        else:
            raise RuntimeError("VICE monitor never became responsive")
    def close(self):
        if self.mon: self.mon.close(); self.mon = None
        if self.proc:
            pid = self.proc.pid
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait(timeout=5)
            print(f"  [vice] reaped pid {pid} (rc={self.proc.returncode})")
            self.proc = None

fails = []
def check(label, ok, extra=""):
    if not ok: fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")

def stable_read(path, quiet=0.6, timeout=15.0):
    """Read a VICE log only once it has stopped growing.

    VICE flushes its trace log lazily. Reading it a fixed 0.5s after `log off`
    sometimes caught only the first line or two -- and the timing section then
    reported a confident single number derived from ONE sample. That is exactly
    the failure mode this project treats as a harness bug rather than a result,
    so the read now waits for the file to settle and the caller asserts a
    minimum sample count.
    """
    end = time.time() + timeout
    last, stable_since = -1, None
    while time.time() < end:
        size = path.stat().st_size if path.exists() else 0
        if size == last and size > 0:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= quiet:
                break
        else:
            stable_since = None
        last = size
        time.sleep(0.15)
    return path.read_text(errors="replace") if path.exists() else ""

def set_watch(mon, addr, kind="store", tries=8):
    """Arm a watchpoint and return its id. The remote monitor drops replies
    often enough that an unverified arm silently turns the following `x` loop
    into a free run, and the rasters it collects then mean nothing."""
    for _ in range(tries):
        m = re.search(r"WATCH: (\d+)", mon.cmd(f"watch {kind} {addr:04x}"))
        if m:
            return m.group(1)
        time.sleep(0.4)
    return None

def read16(mon, addr):
    v = rd(mon, addr, 2)
    return v[0] | (v[1] << 8)

def free_run(mon, frame_counter_addr, seconds, slice_s=2.0, max_stalls=30):
    """Free-run for `seconds` of wall time, VERIFYING the machine is running.

    The remote monitor occasionally drops an `x`, and a stress run against a
    halted machine cheerfully reports zero of everything as though that were a
    measurement. Each slice is only counted once the frame counter has actually
    moved; a slice that did not advance is retried, not counted.
    """
    remaining, stalls = seconds, 0
    while remaining > 0:
        before = read16(mon, frame_counter_addr)
        mon.cmd("x")
        t = min(slice_s, remaining)
        time.sleep(t)
        after = read16(mon, frame_counter_addr)     # any command halts it
        if after == before:
            # The monitor returns from `x` on a prompt echo rather than on the
            # actual stop, so a dropped or overlapped reply can leave the
            # machine halted while we believe it is running. Resynchronise and
            # try again rather than reporting a halted machine's zeros as a
            # measurement.
            stalls += 1
            if stalls > max_stalls:
                return False
            try:
                mon._drain()
            except Exception:
                pass
            mon.cmd("r")
            time.sleep(0.25)
            continue
        stalls = 0
        remaining -= t
    return True

def collect_handler_trace(mon, log, sym, seconds=None, tries=6):
    """Free-run with irqHandler/exDone traced; return (entry_line, cost) pairs.

    `trace` does not halt the machine, so a couple of seconds of warp yields
    thousands of samples across many full fine-scroll cycles.

    Stepping a breakpoint 300 times was tried first and is NOT reliable: runs
    were observed in which 300 stops advanced only a handful of frames, and the
    section then reported a worst case computed from ten samples. Collection is
    retried, because an empty or truncated collection must never be reported as
    a measurement.
    """
    seconds = TRACE_SECONDS if seconds is None else seconds
    best = []
    for _ in range(tries):
        if log.exists():
            log.unlink()
        mon.cmd(f'logname "{log}"')
        mon.cmd("log on")
        mon.cmd(f"trace exec {sym['irqHandler']:04x}")
        mon.cmd(f"trace exec {sym['exDone']:04x}")
        free_run(mon, sym["frameCounter"], seconds, slice_s=seconds)
        mon.cmd("log off")
        text = stable_read(log)
        ev = []
        for m in re.finditer(
                r"\(Trace  exec ([0-9a-f]{4})\)\s+(\d+)/\$[0-9a-f]+,\s+(\d+)/", text):
            ev.append((int(m.group(1), 16), int(m.group(2)), int(m.group(3))))
        pos = lambda l, c: l * 63 + c
        pairs, cur = [], None
        for addr, line, cyc in ev:
            if addr == sym["irqHandler"]:
                cur = (line, pos(line, cyc))
            elif addr == sym["exDone"] and cur:
                pairs.append((cur[0], (pos(line, cyc) - cur[1]) % 19656))
                cur = None
        if len(pairs) > len(best):
            best = pairs
        if len(best) >= 1000:
            break
        try:
            mon._drain()
        except Exception:
            pass
        mon.cmd("r")
        time.sleep(0.5)
    return best

def set_bp(mon, addr, tries=6):
    """Create a breakpoint and return its id. The remote monitor occasionally
    misses the first command after connect, so retry rather than crash."""
    for _ in range(tries):
        m = re.search(r"BREAK: (\d+)", mon.cmd(f"break {addr:04x}"))
        if m: return m.group(1)
        time.sleep(0.4)
    raise RuntimeError(f"could not set breakpoint at ${addr:04x}")

def rd(mon, a, n=1, tries=6):
    """Read n bytes, VERIFYING the reply is the one we asked for.

    Retrying a short read is not enough: a desynchronised monitor can return a
    complete but STALE dump from an earlier command, which silently yields wrong
    values. So check that the first dump line's address is the one requested,
    and that the reply covers the whole range.
    """
    lo, hi = a & ~0xF, (a + n - 1) | 0xF
    want_rows = (hi - lo + 1) // 16
    for _ in range(tries):
        reply = mon.cmd(f"m {lo:04x} {hi:04x}")
        rows = re.findall(r">C:([0-9a-f]{4})\s+((?:[0-9a-fA-F]{2}[ ]*)+)", reply)
        # EVERY row must be present, at its own address, and complete.
        #
        # Checking only the first row's address is not enough for any read that
        # straddles a sixteen-byte dump row, and several counters do -- a
        # sixteen-bit value at $c26f takes its low byte from one row and its
        # high byte from the next. A truncated or interleaved reply then yields
        # a value that is wrong rather than short, and the caller cannot tell.
        # That is exactly how a stress run once reported pageBFrames as 8 while
        # the machine held 8716, and called a perfectly healthy engine broken.
        if len(rows) >= want_rows and all(
                int(rows[i][0], 16) == lo + 16 * i for i in range(want_rows)):
            out, ok = [], True
            for _addr, body in rows[:want_rows]:
                bs = [int(x, 16) for x in re.findall(r"[0-9a-fA-F]{2}", body)[:16]]
                if len(bs) != 16:
                    ok = False
                    break
                out += bs
            if ok:
                got = out[a - lo: a - lo + n]
                if len(got) == n:
                    return got
        time.sleep(0.25)
    raise RuntimeError(f"could not read ${a:04x}+{n} reliably")

def main():
    SCRATCH.mkdir(exist_ok=True)
    print("=== 0. build artefacts present ===")
    check("build/shmup.prg exists", PRG.is_file())
    check("build/main.vs exists", SYM.is_file())
    if fails: return 1
    sym = symbols(SYM)

    print("\n=== 1. static memory-layout invariants ===")
    span = sym["schedCurrent"] - sym["schedY"]
    check("schedule arrays fit the allocated region",
          span <= 0x400, f"{span} bytes of schedule state")
    check("sprite bitmaps are 64-byte aligned", sym["spriteBitmaps"] % 64 == 0,
          f"${sym['spriteBitmaps']:04x}")
    check("sprite bitmaps stay inside VIC bank 0",
          sym["spriteBitmapsEnd"] <= 0x4000, f"${sym['spriteBitmapsEnd']:04x}")

    print("\n=== 2. schedule builder vs independent model ===")
    v = Vice(6510, PRG)
    try:
        mon = v.mon
        mon.cmd("delete")
        # run to the main loop, then take the IRQ out of the picture so the
        # publish/swap cannot race our inspection
        b = set_bp(mon, sym['mainLoop'])
        mon.cmd("x"); mon.cmd(f"delete {b}")
        mon.cmd("> d01a 00")

        nxt = rd(mon, sym["schedNext"])[0]
        base_e = nxt * MAX_SCHED
        base_b = nxt * MAX_BATCH

        for fx, ys in FIXTURES.items():
            m_sched, m_unsafe, m_margin, m_reuse, m_batches = model(ys)
            # VERIFIED selection, retried. This used to poke the fixture index
            # and run `rebuild` once, trusting both to land. A dropped poke then
            # builds the PREVIOUS fixture and every field comparison that
            # follows is against the wrong geometry -- which is exactly how it
            # presented: fixture 2 reporting fixture 1's Y values, once, on one
            # run. Nothing to do with what was being tested.
            for _attempt in range(4):
                mon.cmd(f"> {sym['fixtureIndex']:04x} {fx:02x}")
                # isolated call: rebuild leaves the CPU at the RTS sentinel
                mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
                mon.cmd(f"r sp=fd, pc={sym['rebuild']:04x}")
                bb = set_bp(mon, 0xc0fe)
                mon.cmd("x"); mon.cmd(f"delete {bb}")
                if (rd(mon, sym["fixtureIndex"])[0] == fx and
                        rd(mon, sym["statAccepted"])[0] == len(m_sched)):
                    break
                time.sleep(0.3)
            check(f"F{fx} selected and built", rd(mon, sym["fixtureIndex"])[0] == fx)

            acc = rd(mon, sym["statAccepted"])[0]
            uns = rd(mon, sym["statRejUnsafe"])[0]
            mar = rd(mon, sym["statRejMargin"])[0]
            reu = rd(mon, sym["statReuse"])[0]
            nb  = rd(mon, sym["statBatches"])[0]

            check(f"F{fx} accepted={acc}", acc == len(m_sched), f"model {len(m_sched)}")
            check(f"F{fx} unsafe-rejected={uns}", uns == m_unsafe, f"model {m_unsafe}")
            check(f"F{fx} margin-rejected={mar}", mar == m_margin, f"model {m_margin}")
            check(f"F{fx} reuse events={reu}", reu == m_reuse, f"model {m_reuse}")
            check(f"F{fx} batches={nb}", nb == len(m_batches), f"model {len(m_batches)}")

            ys_r   = rd(mon, sym["schedY"] + base_e, max(1, acc))[:acc]
            slot_r = rd(mon, sym["schedSlot"] + base_e, max(1, acc))[:acc]
            s2_r   = rd(mon, sym["schedSlot2"] + base_e, max(1, acc))[:acc]
            check(f"F{fx} entry Y values match", ys_r == [e["y"] for e in m_sched],
                  f"{ys_r}")
            check(f"F{fx} slot assignment is the six-slot round robin",
                  slot_r == [e["slot"] for e in m_sched], f"{slot_r}")
            check(f"F{fx} slots stay within 2..7",
                  all(MUX_FIRST_SLOT <= s <= MUX_FIRST_SLOT + MUX_SLOTS - 1 for s in slot_r))
            check(f"F{fx} precomputed slot*2 is consistent",
                  s2_r == [s * 2 for s in slot_r])
            check(f"F{fx} schedule fits MAX_SCHED", acc <= MAX_SCHED)
            check(f"F{fx} batches fit MAX_BATCH", nb <= MAX_BATCH)

            bl = rd(mon, sym["batchLine"] + base_b, max(1, nb))[:nb]
            bf = rd(mon, sym["batchFirst"] + base_b, max(1, nb))[:nb]
            bc = rd(mon, sym["batchCount"] + base_b, max(1, nb))[:nb]
            check(f"F{fx} batch lines match", bl == [b["line"] for b in m_batches], f"{bl}")
            check(f"F{fx} batch first/count match",
                  bf == [b["first"] for b in m_batches] and bc == [b["count"] for b in m_batches],
                  f"first {bf} count {bc}")
            check(f"F{fx} every entry is covered by exactly one batch",
                  sum(bc) == acc, f"covered {sum(bc)} of {acc}")

        # the six-slot model, stated explicitly
        m_sched, *_ = model(FIXTURES[1])
        check("first reuse is accepted index 6 (six-slot, not eight-slot)",
              len(m_sched) == 7 and m_sched[6]["slot"] == MUX_FIRST_SLOT,
              f"entry 6 -> hw slot {m_sched[6]['slot']}")
    finally:
        v.close()

    print("\n=== 3. executor timing (fixture 2, the nine-batch frame) ===")
    v = Vice(6511, PRG)
    log = SCRATCH / "trace.log"
    try:
        mon = v.mon
        mon.cmd("delete")
        b = set_bp(mon, sym['mainLoop'])
        mon.cmd("x"); mon.cmd(f"delete {b}")
        mon.cmd(f"> {sym['fixtureIndex']:04x} 02")
        mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={sym['rebuild']:04x}")
        bb = set_bp(mon, 0xc0fe)
        mon.cmd("x"); mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
        mon.cmd("delete")                # see select_fixture in test_p1.py: a
                                         # dropped delete leaves a breakpoint
                                         # armed and the machine cannot run

        nb_live = rd(mon, sym["statBatches"])[0]
        check("timing fixture really has nine batches", nb_live == 9, f"{nb_live}")
        # Take the armed lines from the INDEPENDENT model, not from emulator
        # memory: the freshly built schedule is still in the NEXT buffer until a
        # frame IRQ swaps it, so reading schedCurrent here races the swap.
        armed_lines = [b["line"] for b in model(FIXTURES[2])[4]]

        pairs = collect_handler_trace(mon, log, sym)

        if pairs:
            costs = [c for _, c in pairs]
            lines = sorted({l for l, _ in pairs})
            worst = max(costs)
            byline = {}
            for l, c in pairs:
                byline.setdefault(l, []).append(c)
            print(f"        IRQ entry lines observed: {lines}")
            print(f"        handler cost: min {min(costs)}  median {sorted(costs)[len(costs)//2]}"
                  f"  max {worst} cycles ({worst/63:.2f} raster lines)")
            FRAME_ENTRY = (FRAME_IRQ_LINE, FRAME_IRQ_LINE + 1)
            frame_costs = [c for l, cs in byline.items() if l in FRAME_ENTRY for c in cs]
            mid = [c for l, cs in byline.items() if l not in FRAME_ENTRY for c in cs]
            print(f"        frame batch (6 entries, line {FRAME_IRQ_LINE}): "
                  f"max {max(frame_costs) if frame_costs else 0} cycles")
            if mid:
                print(f"        mid-screen batches: max {max(mid)} cycles over "
                      f"{len(mid)} samples on lines "
                      f"{sorted({l for l in byline if l not in FRAME_ENTRY})}")

            # A sample count is part of the result. Without it a truncated log
            # reports one lucky measurement as if it were the worst case.
            check("collected enough timing samples", len(pairs) >= 1000,
                  f"{len(pairs)} handler pairs")
            # A raster IRQ is entered 0..1 lines after the line it was armed
            # for: the CPU finishes the current instruction and then spends 7
            # cycles vectoring, so an armed line of 127 is observed as 127 or
            # 128. Match against the armed lines rather than pretending the
            # entry raster is exact.
            def armed_for(l):
                for a in armed_lines:
                    if l in (a, (a + 1) % PAL_LINES):
                        return a
                return None
            seen = {armed_for(l) for l in lines}
            check("every armed batch line was sampled",
                  seen == set(armed_lines),
                  f"armed {sorted(armed_lines)}; matched {sorted(x for x in seen if x is not None)}")
            check("no IRQ entered on an unarmed line",
                  all(armed_for(l) is not None for l in lines),
                  f"unmatched {[l for l in lines if armed_for(l) is None]}")

            check("MID-SCREEN batch cost fits inside the REUSE_LEAD budget",
                  bool(mid) and max(mid) <= REUSE_LEAD * 63,
                  f"{max(mid) if mid else 'no samples'} cy vs budget "
                  f"{REUSE_LEAD*63} cy ({REUSE_LEAD} lines)")
            check("FRAME batch fits its own (much larger) deadline",
                  bool(frame_costs) and max(frame_costs) <= FRAME_BATCH_BUDGET,
                  f"{max(frame_costs) if frame_costs else 'no samples'} cy vs budget "
                  f"{FRAME_BATCH_BUDGET} cy; real deadline {FRAME_BATCH_DEADLINE} cy "
                  f"(raster {FRAME_IRQ_LINE} -> {MIN_SPRITE_Y} next frame)")
            check("frame IRQ fires on the documented line",
                  any(l in FRAME_ENTRY for l in lines), f"lines {lines}")
        else:
            check("collected executor timing samples", False, "no trace pairs parsed")
    finally:
        v.close()
        if log.exists(): log.unlink()

    print("\n=== 4. cleanup ===")
    leftovers = list(SCRATCH.glob("*"))
    check("no transient test artefacts left in scratch", not leftovers,
          f"{[p.name for p in leftovers]}")
    r = subprocess.run(["pgrep", "-fl", "x64sc"], capture_output=True, text=True)
    running = {}
    for line in r.stdout.splitlines():
        pid, _, cmd = line.partition(" ")
        # Match the EXECUTABLE, not any command line that merely contains
        # "x64sc" -- a grep over this very output otherwise reports itself as a
        # stray emulator.
        if not cmd.split(" ")[0].endswith("x64sc"):
            continue
        try: running[int(pid)] = cmd
        except ValueError: pass
    mine = {pid: cmd for pid, cmd in running.items() if pid in LAUNCHED_PIDS}
    check("no test-owned VICE process remains", not mine, f"{mine}")
    others = {pid: cmd for pid, cmd in running.items() if pid not in LAUNCHED_PIDS}
    print(f"        launched and reaped: {LAUNCHED_PIDS}")
    print(f"        other x64sc processes (NOT ours, left alone): "
          f"{others if others else 'none'}")

    print(f"\n=== {'ALL PASS' if not fails else str(len(fails)) + ' FAILURES: ' + ', '.join(fails[:6])} ===")
    return 1 if fails else 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        try: SCRATCH.rmdir()
        except OSError: pass
