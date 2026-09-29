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


# ---------------------------------------------------------------------------
# STAGE GEOMETRY, READ FROM THE ENGINE RATHER THAN RESTATED.
#
# Five suites carried their own copy of this, one of them commented "restated
# independently", and every copy went stale the day the campaign landed: they
# said 105 metatile rows / 420 logical / 395 final while the engine had been
# fixed at 200 / 800 / 775. test_boss then asserted STAGE_FINAL == 395, never
# saw the stage complete, never started the boss, and crashed indexing an empty
# list -- and test_heat_cadence failed ten checks downstream of the same thing.
#
# THE HEIGHT IS THE ENGINE'S, NOT THE LEVEL'S. src/levelpkg.asm fixes
# LEVELPKG_STAGE_ROWS for every package ("the campaign fixed the engine at one
# height ... and every package now emits exactly that", enforced by a build
# guard in src/level_package.asm). A level's own STAGE_METATILE_ROWS -- 200 for
# level 1, 138 for level 2 -- is how much of that height it AUTHORS, not how
# far the scroller runs. So this is one number for the whole campaign, and it
# is read out of the source that defines it.
# ---------------------------------------------------------------------------
# A CLAIM ABOUT NOTHING IS NOT A PASSING CLAIM.
#
# `check("every X is Y", all(f(x) for x in xs))` passes when xs is EMPTY, and
# an empty xs is exactly what a test gets when the scenario it needed never
# happened -- no enemy spawned, no bolt flew, the window was too short. The
# suite has 68 such assertions and the aimed-velocity bug showed what they cost:
# a test can be green for years while proving nothing at all.
#
# check_all() splits the two questions it was conflating: did the case occur,
# and was it correct. A missing case fails with "NO <what> were exercised",
# which is actionable, instead of passing silently.
def check_all(msg, seq, pred, what="cases", detail=None):
    """check() that refuses to pass on an empty sequence."""
    items = list(seq)
    if not items:
        check(f"{msg} -- NO {what} WERE EXERCISED", False,
              f"0 {what} observed: the test never reached its own scenario")
        return False
    bad = [x for x in items if not pred(x)]
    check(msg, not bad,
          detail(items, bad) if detail else
          (f"{len(items)} {what} checked" if not bad
           else f"{len(bad)} of {len(items)} {what} failed, e.g. {bad[0]!r}"))
    return not bad


def check_exercised(msg, count, minimum=1, what="cases"):
    """State plainly that the scenario occurred, as its own assertion."""
    check(f"{msg}", count >= minimum,
          f"{count} {what} (needed at least {minimum})")
    return count >= minimum


# ---------------------------------------------------------------------------
# AUTHORED CONSTANTS COME FROM THE LEVEL, NOT FROM A COPY IN THE TEST.
#
# test_no_spawn_row carried `NO_SPAWN = 340  # src/level1/stage_config.asm`.
# The comment named the source of truth and the code ignored it, so when the
# level was re-authored to 725 the test failed seven checks while the engine was
# behaving perfectly. That is the same failure as the five stale copies of the
# stage geometry, and it has the same fix: read it.
def level_const(name, level="level1", root=None):
    """The value of a `.const NAME = n` in a level's stage_config.asm."""
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    cfg = (root / "src" / level / "stage_config.asm").read_text(encoding="utf-8")
    m = re.search(rf"^\s*\.const\s+{re.escape(name)}\s*=\s*(\d+)", cfg, re.M)
    if not m:
        raise SystemExit(f"{name} not found in src/{level}/stage_config.asm")
    return int(m.group(1))


def stage_geometry(root=None):
    """(metatile_rows, logical_rows, final_view_progress) from the engine."""
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    pkg = (root / "src" / "levelpkg.asm").read_text(encoding="utf-8")
    m = re.search(r"^\s*\.const\s+LEVELPKG_STAGE_ROWS\s*=\s*(\d+)", pkg, re.M)
    if not m:
        raise SystemExit("LEVELPKG_STAGE_ROWS not found in src/levelpkg.asm")
    rows = int(m.group(1))
    terrain = (root / "src" / "terrain.asm").read_text(encoding="utf-8")
    mh = re.search(r"^\s*\.const\s+METATILE_H\s*=\s*(\d+)", terrain, re.M)
    metatile_h = int(mh.group(1)) if mh else 4
    logical = rows * metatile_h
    return rows, logical, logical - 25          # SCREEN_ROWS


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


# HOW FAR INTO THE STAGE boot="exact" is allowed to arrive. One coarse row is
# eight displayed frames, so a handful of rows of slack would already be dozens
# of frames of gameplay the caller did not ask for. Four is generous for a boot
# that steps single frames and leaves any plausible authored schedule ahead of
# the arrival point -- it is deliberately NOT expressed relative to whatever row
# the first encounter happens to sit at today.
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
        # THE BOOT RACE IS REAL AND IS NOT FIXED HERE. Sampling gsState once
        # per wall-clock second can miss PLAYING entirely: hudLives is not
        # topped up until PLAYING has been SEEN, so in warp the game can start,
        # the parked ship can lose every life, and the lifecycle can be sitting
        # in INITIALS by the next sample -- which is the intermittent
        # `never reached PLAYING: gsState = 3` that test_player_ship hits.
        #
        # A frame-stepped version of this loop WAS written and measured, and it
        # did fix that crash. It also moved where every other suite starts, and
        # two that had been passing (test_turret_arming, test_boss_hud_
        # transition) then failed deterministically, because their assertions
        # are coupled to the old, sloppier arrival point. Trading one
        # intermittent crash for two deterministic failures is not an
        # improvement, so the racy loop stands until those couplings are
        # repaired in the same change. See the audit report.
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


# ---------------------------------------------------------------------------
# WAIT IN FRAMES, NOT IN SECONDS.
#
# free_run() below advances WALL-CLOCK time and verifies only that the machine
# is moving -- not how far it got. That is the right primitive for "let the
# game breathe", and the wrong one for "wait until X happens", because every
# event this engine has is denominated in FRAMES. Eight seconds of host time
# buys a different number of frames on a cold first run after a build, on a
# loaded machine, or when another suite is running beside this one -- which is
# exactly the "fails the first time, passes the second" and "fails in batch,
# passes alone" pattern this suite has been chasing.
#
# So: wait on the frame counter. The budget is frames, the machine is advanced
# in short slices, and a stalled emulator is an error rather than a timeout.
def frames_elapsed(mon, frame_counter_addr, since):
    """How many frames have passed since `since`, 16-bit wraparound safe."""
    return (read16(mon, frame_counter_addr) - since) & 0xffff


# ---------------------------------------------------------------------------
# THREE WAYS TO ADVANCE THE MACHINE, AND THEY ARE NOT INTERCHANGEABLE.
#
#   free_run(seconds)        HOST time. Verifies only that the machine moved,
#                            never how far. Do not assert on a window it sized.
#   run_frames(n)/step_n(n)  GAME frames, verified, via a breakpoint every
#                            frame. Exact -- and it PERTURBS TIMING: stopping
#                            at gameFrame resets the phase relationship between
#                            the main thread and the raster IRQ, which was
#                            measured to MASK the rare publishSkip event
#                            entirely (4,500 stepped frames: nothing; one
#                            7,631-frame uninterrupted window: one event). Use
#                            it to sample state, never to judge timing health.
#   soak_frames(n)           GAME frames, measured, with as few stops as
#                            possible. The machine runs uninterrupted in long
#                            slices and the elapsed frames are READ rather than
#                            assumed. This is the primitive for any window whose
#                            SUBJECT is timing: publishSkip, gameOverrun,
#                            scrollLate, edgeLate.
#
# The rule: if the test is asking "what did the engine compute", step it. If it
# is asking "did the engine keep up", soak it.
def soak_frames(mon, frame_counter_addr, target, max_slices=20):
    """Run uninterrupted until ~`target` frames have elapsed, and not far past.

    Returns the frames actually run, measured from the counter.

    THE WINDOW HAS TO BE BOUNDED ABOVE AS WELL AS BELOW. A first version slept a
    fixed four seconds per slice, which in warp is thousands of frames: asked for
    1,800 it delivered 7,778, and an invariant that only holds over a short
    window is worthless if the window is four times longer than asked. So the
    machine is calibrated first -- one short slice measures frames per host
    second -- and each following slice is sized to the frames still wanted.
    Monitor contact stays in single figures, nowhere near the per-frame stopping
    that masks renderer timing.
    """
    start = read16(mon, frame_counter_addr)

    def done():
        return (read16(mon, frame_counter_addr) - start) & 0xffff

    CAL_S = 0.2
    before = read16(mon, frame_counter_addr)
    mon.cmd("x")
    time.sleep(CAL_S)
    mon.cmd("delete")
    per_s = max(1.0, ((read16(mon, frame_counter_addr) - before) & 0xffff) / CAL_S)

    for _ in range(max_slices):
        short = target - done()
        if short <= 0:
            return done()
        # aim at 80% of what is left, so the last slice cannot overshoot far
        nap = max(0.02, min(2.0, (short * 0.8) / per_s))
        before = read16(mon, frame_counter_addr)
        mon.cmd("x")
        time.sleep(nap)
        mon.cmd("delete")
        ran = (read16(mon, frame_counter_addr) - before) & 0xffff
        if ran == 0:
            raise RuntimeError("the machine advanced no frames in a slice: "
                               "it is halted, not slow")
        per_s = max(1.0, ran / nap)     # re-estimate: host speed drifts
    return done()


def run_frames(mon, frame_counter_addr, n, frame_sym=None):
    """Advance EXACTLY n distinct frames, verified, and return them.

    A BREAKPOINT IS NOT OPTIONAL HERE, and the first draft of this helper is
    why the comment says so. It advanced the machine with `x` + sleep() and
    called the result a frame budget -- but with nothing armed, `x` runs free
    until the next monitor command, so a 0.25s slice in warp is THOUSANDS of
    frames. Asking for 30 delivered about 30,000, the parked ship lost every
    life inside the "budget", and the lifecycle sailed past PLAYING into
    INITIALS. That is the same wall-clock-for-frames error this helper exists
    to remove, reproduced inside the fix for it.

    So the frame routine is armed and every stop is verified against the
    counter, exactly as step_n() does for sampling.
    """
    sym = symbols(SYM)
    addr = frame_sym if frame_sym is not None else sym["gameFrame"]
    bp = set_bp(mon, addr)
    try:
        start = prev = read16(mon, frame_counter_addr)
        tries, budget = 0, n * 6 + 20
        while frames_elapsed(mon, frame_counter_addr, start) < n:
            tries += 1
            if tries > budget:
                raise RuntimeError(
                    f"only {frames_elapsed(mon, frame_counter_addr, start)} of "
                    f"{n} frames ran in {tries} stops: the machine is halted")
            mon.cmd("x")
            now = read16(mon, frame_counter_addr)
            if now == prev:
                continue                    # a dropped/duplicated stop
            prev = now
        return frames_elapsed(mon, frame_counter_addr, start)
    finally:
        mon.cmd(f"delete {bp}")


def run_until_state(mon, frame_counter_addr, predicate, seconds=20, slice_s=0.3):
    """Wait for predicate() ACROSS STATE CHANGES, including non-game states.

    THIS EXISTS BECAUSE run_frames/run_until ARE GAMEPLAY-ONLY. They arm a
    breakpoint on gameFrame, and gameFrame does not execute while gsNonGame is
    set -- irqHandler routes to gsAttractIrq instead. So in ATTRACT, the upgrade
    shop, GAME OVER or INITIALS those helpers advance NOTHING: the breakpoint
    never fires, no frames pass, and a caller waiting for a transition waits for
    ever. That is not a hypothetical -- it hung the smoke runner at the level-2
    load and silently swallowed a FIRE press in the shop.

    Time here is host time, deliberately: this is for DRIVING the lifecycle and
    watching for a state change, never for judging timing health. Use
    soak_frames for that, and run_frames to sample inside gameplay.
    """
    end = time.time() + seconds
    while True:
        if predicate():
            return True
        if time.time() >= end:
            return False
        mon.cmd("x")
        time.sleep(slice_s)
        mon.cmd("delete")


def run_until(mon, frame_counter_addr, predicate, max_frames, frame_sym=None):
    """Step frames until predicate() holds, or max_frames pass.

    GAMEPLAY ONLY: this arms a breakpoint on gameFrame, which does not run in
    non-game states. Crossing ATTRACT / the shop / GAME OVER needs
    run_until_state() instead.

    Returns (ok, frames_used). THE BUDGET IS FRAMES, so the same call covers
    the same amount of game on a cold host as on a warm one -- which is the
    whole point, and what free_run() cannot promise. The predicate is sampled
    EVERY frame, so a state that is only briefly true cannot be stepped over.
    """
    sym = symbols(SYM)
    addr = frame_sym if frame_sym is not None else sym["gameFrame"]
    if predicate():
        return True, 0
    bp = set_bp(mon, addr)
    try:
        start = prev = read16(mon, frame_counter_addr)
        tries, budget = 0, max_frames * 6 + 20
        while True:
            used = frames_elapsed(mon, frame_counter_addr, start)
            if used >= max_frames:
                return False, used
            tries += 1
            if tries > budget:
                raise RuntimeError("the machine stopped advancing frames")
            mon.cmd("x")
            now = read16(mon, frame_counter_addr)
            if now == prev:
                continue
            prev = now
            if predicate():
                return True, frames_elapsed(mon, frame_counter_addr, start)
    finally:
        mon.cmd(f"delete {bp}")


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
