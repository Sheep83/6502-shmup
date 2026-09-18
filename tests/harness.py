#!/usr/bin/env python3
"""The shared VICE-monitor harness: launch, talk to, and reap exactly one
x64sc process at a time, and read/write/symbolise its memory reliably.

This is infrastructure, not a test. It carries no assertions of its own and
proves nothing about the game -- it exists so that test_boot.py,
test_production.py and test_turret_regression.py do not each reinvent PID
ownership, retry-on-drop reads, or free-run verification.

Extracted from tests/test_p0.py and tests/test_p2.py during the test-suite
rewrite at the `legacy-tests-retired` tag, where this code originated and is
still exercised by the retained test-engine-full / test-renderer-full targets
(tests/test_p0.py..test_p5.py, tests/test_batch_window.py). Keep this file and
those in sync if the monitor protocol or launch discipline ever changes; they
were deliberately left as independent copies rather than made to import this
module, so that retiring this file later cannot break the archived ladder.
"""
import re, socket, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRG  = ROOT / "build/shmup.prg"
# THE MACHINE BOOTS FROM THE DISK IMAGE, NOT FROM THE PRG.
#
# The engine loads its level package ("LEVEL1", to $e000) from disk during the
# first instruction of entry, so a bare PRG is no longer a runnable artefact:
# autostarting one leaves no drive for the KERNAL to load from and the boot
# halts on a red border by design. Every launch therefore attaches the d64 that
# `make build` now always produces.
D64  = ROOT / "build/shmup.d64"
SYM  = ROOT / "build/main.vs"
X64  = "/opt/homebrew/bin/x64sc"

# --- symbol table -------------------------------------------------------
def symbols(path):
    syms = {}
    for line in path.read_text().splitlines():
        m = re.match(r"al C:([0-9a-fA-F]{1,4})\s+\.?(\S+)", line)
        if m: syms[m.group(2)] = int(m.group(1), 16)
    return syms


# --- VICE monitor protocol -----------------------------------------------
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
        machine is stopped, so we cannot wait for it unconditionally. Read
        until the prompt appears OR the socket goes idle -- but never break on
        a bare ">", which begins every memory-dump line.
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


def port_owner(port):
    """The PID listening on `port`, or None.

    Used to guarantee a suite talks to the emulator it started and no other:
    attaching to somebody else's VICE by accident makes every subsequent
    measurement describe that machine's leftover state, not this run's.
    """
    r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                       capture_output=True, text=True)
    pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    return pids[0] if pids else None


# HOW FAR INTO THE STAGE boot="exact" is allowed to arrive. The first authored
# encounter is at coarse row 48 and one coarse row is eight displayed frames, so
# a handful of rows of slack would already be dozens of frames of gameplay the
# caller did not ask for. Four is generous for a boot that steps single frames
# and still an order of magnitude clear of row 48.
BOOT_EXACT_MAX_ROW = 4


def pc_of(reply):
    """The PC out of the monitor's own "(C:$xxxx)" prompt, or None.

    TWO TRAPS, BOTH PAID FOR IN THIS SUITE:

    1. `mon.cmd("x")` RETURNS ON AN IDLE SOCKET AS WELL AS ON A STOP, so "the
       call returned" is not "the breakpoint fired". Anything that needs to know
       WHERE the machine stopped has to ask, rather than assume.
    2. The reply can carry a STALE prompt left in the socket by an earlier
       command, and re.search happily matches that one. Taking the LAST match is
       what makes the address the one this command stopped at. With re.search a
       trigger probe silently missed the first two firings of a four-trigger
       schedule and reported rows [90, 126] instead of [48, 52, 90, 126].
    """
    m = re.findall(r"\(C:\$([0-9a-fA-F]{4})\)", reply)
    return int(m[-1], 16) if m else None


# Every PID this session has ever launched. Ownership is by PID, never by
# pattern-matching `pgrep` output: the repository path appears in the command
# line of any manual VICE session the user has open on this project too, and a
# check that cannot tell those apart is one step from killing one.
LAUNCHED_PIDS = []


class Vice:
    """Owns exactly one x64sc PID and guarantees cleanup.

    Settings isolation: +saveres ("do not save settings on exit") is the one
    flag in this VICE build empirically proven to stop a session from ever
    writing ~/.config/vice/vicerc -- verified against a decoy $HOME, on both
    a clean monitor "quit" and the SIGTERM this class actually sends in
    close(), before being trusted here (see
    reports/vice-harness-settings-isolation.md). -config, which looked like
    the more structural fix, is NOT used: a session launched with
    `-config <fresh /tmp file>` still loaded the real vicerc's bindings and,
    on a graceful exit, saved back to the REAL vicerc regardless of the
    -config path given -- so it provides no isolation in this build despite
    what its help text implies.

    -default is dropped: this suite no longer needs to blank the loaded
    settings to something safe-to-discard, because +saveres alone already
    guarantees nothing is ever written back, loaded or not. The joystick
    port / keyset overrides (-joydev1 0 -joydev2 0 +keyset) are dropped for
    the same reason -- with saving disabled and -console meaning no window
    is ever mapped to receive host key events, there is nothing left for
    detaching them to protect against, so the user's own bindings are simply
    left loaded in memory for the session's lifetime and never touched on
    disk.
    """
    def __init__(self, port, prg, warp=True, start_game=True, boot="fast"):
        """start_game: drive the restored lifecycle from ATTRACT into GAME.

        THE MACHINE NO LONGER BOOTS INTO GAMEPLAY. src/gamestate.asm restores the
        old shooter's outer loop, so a cold boot lands on the attract screen and
        waits for fire -- and every test in this suite that predates it assumes
        the game is already running. Pressing fire here, once, in the one place
        that owns bringing a machine up, keeps all of them testing exactly what
        they tested before. A test that wants the lifecycle itself passes
        start_game=False and drives it by hand.

        boot: WHERE IN THE LEVEL THE TEST WAKES UP, and since absolute wave
        triggers landed this is a real choice rather than an implementation
        detail.

            "fast"   the historical boot. Cheap, and it arrives some HUNDREDS of
                     coarse rows into the stage -- see _boot_to_game. Correct for
                     any test indifferent to world position.
            "exact"  arrives at worldProgress 0, frame by frame, so the authored
                     encounters at rows 48, 52, 90 and 126 are all still ahead.
                     Costs a few seconds more. Required by any test that must
                     observe the encounter window.

        Ordinary waves used to repeat every 126 rows for ever, so "hundreds of
        rows in" was indistinguishable from "at the start" and the overshoot was
        invisible. Level 1 now runs its four encounters ONCE and the director is
        then exhausted, so a fast boot lands in permanent quiet.
        """
        # THE ARGUMENT IS KEPT, THE ARTEFACT IS NOT.
        #
        # Every test in this suite passes PRG, and every one of them means "boot
        # the game". Since the engine gained its separately loaded level package
        # that is no longer the PRG -- a bare PRG has no drive to load "LEVEL1"
        # from and halts on a red border by design -- so the one place that owns
        # bringing a machine up substitutes the disk image beside it. Doing it
        # here rather than in twenty call sites means there is exactly one line
        # in the suite that knows the boot artefact changed.
        if str(prg).endswith(".prg"):
            prg = D64
        self.port, self.proc, self.mon = port, None, None
        try:
            # -console: an automated suite must never open a window (it
            # steals macOS keyboard focus the instant it maps).
            args = [X64, "-console", "+saveres", "-pal", "+sound",
                    "-remotemonitor",
                    "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
                    "-autostart", str(prg)]
            if warp: args.insert(1, "-warp")
            squatter = port_owner(port)
            if squatter is not None:
                raise RuntimeError(
                    f"port {port} is already served by pid {squatter}; refusing "
                    f"to attach to a VICE this suite did not launch")
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            LAUNCHED_PIDS.append(self.proc.pid)
            print(f"  [vice] launched pid {self.proc.pid} on port {port}")
            time.sleep(4)
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
            for _ in range(25):
                if "(C:$" in self.mon.cmd("r"): break
                time.sleep(0.3)
            else:
                raise RuntimeError("VICE monitor never became responsive")
            if start_game:
                if boot == "exact":
                    self._boot_to_game_exact()
                elif boot == "fast":
                    self._boot_to_game()
                else:
                    raise ValueError(f"unknown boot mode {boot!r}")
        except Exception:
            self.close()
            raise

    def _boot_to_game(self):
        """ATTRACT -> GAME, through the real input path the player uses. FAST.

        Fire is PRESSED and then RELEASED because the restored attract loop
        gates the start on the release -- the old game's own debounce, which
        exists so one press cannot also reach the game's first frame.

        THIS ARRIVES HUNDREDS OF COARSE ROWS INTO THE STAGE, and that is
        inherent rather than a bug to tune away. free_run takes SECONDS OF WALL
        TIME and the machine is in warp, so each press and each release carries
        a second of emulated play; the gsState check happens only after both.
        The game therefore starts somewhere inside one of those seconds and the
        remainder runs as ordinary gameplay. Measured returns are recorded in
        reports/test-harness-frame-accurate-boot-repair.md.

        That was harmless while ordinary waves repeated every 126 rows for ever.
        It is not harmless now: a test that needs to see an authored encounter
        must use boot="exact" instead. Shortening these intervals would not fix
        it -- the overshoot would merely become smaller and still nondeterministic.
        """
        sym = symbols(SYM)
        mon = self.mon
        poke(mon, sym["joyHold"], 1)
        # THE MACHINE IS HALTED HERE. Every monitor command stops the emulator,
        # so the responsiveness probe above left it standing still -- sleeping
        # would advance nothing at all. Each press and release has to be carried
        # by a real run of frames.
        for _ in range(8):
            poke(mon, sym["joyState"], 0xef)        # fire down
            free_run(mon, sym["frameCounter"], 1)
            mon.cmd("delete")
            poke(mon, sym["joyState"], 0xff)        # ...and up: the gate opens
            free_run(mon, sym["frameCounter"], 1)
            mon.cmd("delete")
            if rd1(mon, sym["gsState"]) == 1:       # GS_PLAYING
                break
        else:
            raise RuntimeError(
                "the lifecycle never reached PLAYING: gsState = "
                f"{rd1(mon, sym['gsState'])}")
        poke(mon, sym["joyState"], 0xff)
        poke(mon, sym["joyHold"], 0)                # tests own the stick again

        # A STOCK THE TEST CANNOT EXHAUST, and this restores an assumption
        # rather than inventing one. Before the lifecycle existed the ship could
        # not die: playerTakeHit only granted invulnerability, so a stationary
        # ship under fire blinked forever and every test in this suite was
        # written against a game that never ends. Lives are real now, and in
        # warp a parked ship loses five of them in a fraction of a probe --
        # after which the machine is sitting on the attract screen and the test
        # is measuring nothing. A test that wants to watch a game END drives the
        # lifecycle itself with start_game=False.
        poke(mon, sym["hudLives"], 250)

        # ...AND THE LEVEL IS HELD OPEN, for the same kind of reason. The stage
        # is finite now: one traversal freezes the arena, stops every encounter
        # and spawns the end-of-level boss. A human reaches that after
        # sixty-three seconds; in warp a five-second probe reaches it, so every
        # pre-existing test that free-runs for a while would be measuring the
        # boss arena instead of ordinary play. stageHold is src/scroll.asm's
        # own diagnostic switch, beside pinFine, and it makes the stage endless
        # exactly as it used to be. A test about the END of a level clears it.
        poke(mon, sym["stageHold"], 1)

    def _boot_to_game_exact(self):
        """ATTRACT -> GAME at worldProgress 0, one frame at a time.

        Same input path, same debounce, same post-conditions as _boot_to_game --
        the only difference is that emulated time is advanced in FRAMES rather
        than in seconds of wall clock, so the world cannot run away underneath
        the transition.

        THE BREAKPOINT MUST BE HIT EVERY FRAME IN BOTH STATES, and that is the
        whole difficulty. `x` on a breakpoint that is NOT hit does not stop the
        machine: it free-runs until the socket goes idle, which in warp is
        hundreds of coarse rows, and step_n then accepts the enormous frame jump
        as "one step". So both per-frame seams are armed together:

            gsAttractLoop   once per frame while the attract page is up
                            (its first instruction is jsr gsWaitFrame)
            gameFrame       once per frame once PLAYING has begun

        Breaking only on mainLoop does NOT work and was measured failing: the
        router reaches it on a STATE CHANGE, not per frame, so the stepper
        free-ran and one boot arrived at PLAYING with worldProgress already 395
        and the boss phase up -- the stage had begun, run out and ended inside
        the "frame-accurate" loop.

        THE POST-CONDITION IS CHECKED, NOT ASSUMED. Overshoot is exactly the
        failure this routine exists to prevent, so it raises rather than
        returning a machine that is quietly in the wrong place.
        """
        sym = symbols(SYM)
        mon = self.mon
        bp_attract = set_bp(mon, sym["gsAttractLoop"])
        set_bp(mon, sym["gameFrame"])
        poke(mon, sym["joyHold"], 1)
        for _ in range(200):
            if rd1(mon, sym["gsState"]) == 1:           # GS_PLAYING
                break
            poke(mon, sym["joyState"], 0xef)            # fire down
            step_n(mon, sym["frameCounter"], 2, lambda: None)
            poke(mon, sym["joyState"], 0xff)            # ...and up: gate opens
            step_n(mon, sym["frameCounter"], 2, lambda: None)
        else:
            raise RuntimeError(
                "the lifecycle never reached PLAYING: gsState = "
                f"{rd1(mon, sym['gsState'])}")
        poke(mon, sym["joyState"], 0xff)
        poke(mon, sym["joyHold"], 0)                    # tests own the stick

        # The same two post-conditions the fast boot establishes, for the same
        # reasons -- a stock the test cannot exhaust, and a stage that does not
        # end underneath it. A test that wants the level to END clears stageHold.
        poke(mon, sym["hudLives"], 250)
        poke(mon, sym["stageHold"], 1)

        mon.cmd(f"delete {bp_attract}")
        mon.cmd("delete")
        where = read16(mon, sym["worldProgressLo"])
        if where > BOOT_EXACT_MAX_ROW:
            raise RuntimeError(
                f"the exact boot overshot: worldProgress = {where}, limit "
                f"{BOOT_EXACT_MAX_ROW}. The authored encounters are at rows "
                f"48, 52, 90 and 126 and a test asking for boot='exact' cannot "
                f"observe them from here.")

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

    A desynchronised monitor can return a complete but STALE dump from an
    earlier command, which silently yields wrong values. So check that every
    row is present, at its own address, and complete before trusting it.
    """
    lo, hi = a & ~0xF, (a + n - 1) | 0xF
    want_rows = (hi - lo + 1) // 16
    for _ in range(tries):
        reply = mon.cmd(f"m {lo:04x} {hi:04x}")
        rows = re.findall(r">C:([0-9a-f]{4})\s+((?:[0-9a-fA-F]{2}[ ]*)+)", reply)
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


def rd1(mon, a, tries=6):
    """rd() for the common case of exactly one byte."""
    return rd(mon, a, 1, tries)[0]


def poke(mon, addr, val):
    mon.cmd(f"> {addr:04x} {val & 0xff:02x}")


def read16(mon, addr):
    v = rd(mon, addr, 2)
    return v[0] | (v[1] << 8)


def free_run(mon, frame_counter_addr, seconds, slice_s=2.0, max_stalls=30):
    """Free-run for `seconds` of wall time, VERIFYING the machine is running.

    The remote monitor occasionally drops an `x`, and a stress run against a
    halted machine cheerfully reports zero of everything as though that were a
    measurement. Each slice is only counted once the frame counter has
    actually moved; a slice that did not advance is retried, not counted.
    """
    remaining, stalls = seconds, 0
    while remaining > 0:
        before = read16(mon, frame_counter_addr)
        mon.cmd("x")
        t = min(slice_s, remaining)
        time.sleep(t)
        after = read16(mon, frame_counter_addr)
        if after == before:
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


def step_n(mon, frame_counter_addr, n, read_fn, max_tries=None):
    """Step exactly n DISTINCT frames at an already-armed breakpoint, calling
    read_fn() once per accepted frame and returning the list of results.

    THE STEPPING RULE (this codebase's own recurring warning, restated here
    because test_production.py's first draft violated it): `mon.cmd("x")`
    returns on a prompt echo rather than on the actual stop, so a dropped or
    duplicated reply can leave the machine halted -- or can return without the
    breakpoint having fired again at all -- while the caller believes one more
    frame just ran. A bare `for _ in range(n): mon.cmd("x")` loop can silently
    sample fewer than n real frames. This verifies every step by the frame
    counter and retries a stall instead of recording it.
    """
    if max_tries is None:
        max_tries = n * 6 + 20
    out, prev, tries = [], None, 0
    while len(out) < n and tries < max_tries:
        tries += 1
        mon.cmd("x")
        f = rd(mon, frame_counter_addr, 2)
        fc = f[0] | (f[1] << 8)
        if fc == prev:
            continue                    # a stalled/duplicate stop: retry
        prev = fc
        out.append(read_fn())
    return out


def call(mon, sym, routine, x=None):
    """Call a routine to completion via a synthetic return address, then
    resume at mainLoop. Only for routines that are genuinely self-contained
    (constraint #4) -- anything whose behaviour depends on frame cadence
    belongs in a free-running production loop instead, driven by set_bp +
    free_run/step, not by this."""
    mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
    if x is None:
        mon.cmd(f"r sp=fd, pc={sym[routine]:04x}")
    else:
        mon.cmd(f"r sp=fd, pc={sym[routine]:04x}, x={x:02x}")
    bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
    mon.cmd(f"r pc={sym['mainLoop']:04x}")


fails = []
def check(label, ok, extra=""):
    if not ok: fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def report(module_name):
    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    if fails:
        print(f"\n=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
        return 1
    print("\n=== ALL PASS ===")
    return 0
