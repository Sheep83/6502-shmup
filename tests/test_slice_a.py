#!/usr/bin/env python3
"""Slice A — the production loop and the player on HW0/HW1.

What this proves
----------------
* a production boot presents NO fixture: zero gameplay sprites, zero batches,
  and the player alone on the two reserved slots;
* the player's presentation is PUBLISHED, not poked: the registers the VIC is
  using always match the ADOPTED block, and only buildSchedule ever writes that
  block, and only into the buffer that is not current;
* the full-byte composition is correct in both directions -- the player's two
  bits survive every gameplay write to $d015 and $d010, and the multiplexer's
  six survive the player's;
* HW0/HW1 pointers follow the page flip, and their Y stays inside the range the
  renderer is promised;
* nothing is enabled across the vertical blank, so the Y+256 ghost stays
  unreachable;
* the engine's own invariants -- frame transaction at 250, handoff at 40, both
  aperture splits, the HUD write window -- are exactly where they were.

What this does NOT prove
------------------------
That it looks right, or that the stick feels right. Slice A is only GREEN after
a human has played it at normal speed with a joystick in port 2.

TWO HARNESS RULES THIS FILE PAID FOR
------------------------------------
1. Sample at a PHASE, not at "wherever the monitor halted". Under warp, VICE
   stops on a frame boundary, so an earlier draft of this file took fourteen
   samples and every one of them landed in the vertical blank -- the entire
   mid-display state went unobserved while the test reported nothing wrong.
2. Read in BULK and keep breakpoint traffic down. The schedule scalars are
   contiguous, so one `m` command fetches all of them; an earlier draft issued
   a dozen per sample, and the churn desynchronised the monitor badly enough
   that a verified fixture selection read back as an empty one. rd()'s own
   docstring warns about exactly this, and it was right.

VICE process ownership: this script owns exactly the PID it launches and kills
it on success, failure and exception via try/finally.
"""
import sys, re, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import (PRG, SYM, symbols, Vice, rd, set_bp, free_run,
                     LAUNCHED_PIDS, MAX_BATCH)
from test_p2 import poke
from test_p5 import select_p5

sym = symbols(SYM)

# --- the contract this slice adds, restated independently of the assembler ---
PLAYER_PTR_BASE, PLAYER_PTR_TRIM = 0xd6, 0xd7
PLAYER_SLOT_MASK = 0b00000011
PLAYER_MIN_Y, PLAYER_MAX_Y = 55, 226
PLAYER_MIN_X, PLAYER_MAX_X = 23, 321
HUD_ENABLE, HUD_D010 = 0b11111100, 0b10000000
PTR_A, PTR_B = 0x07f8, 0x2bf8
FRAME_IRQ_LINE, HUD_IRQ_LINE, HANDOFF_LINE, TOP_ARM_LINE = 250, 4, 40, 53
TOP_SPLIT, BOT_SPLIT = (54, 55), 248
BORDER_OPEN_LINE = 243      # exBottom's arming line, before it polls to 248
RING_SLOW, N_RING = 31, 16
JOY_IDLE = 0b00011111                       # active low: nothing pressed

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


# ===========================================================================
def source_invariants():
    """Ownership rules that can be read straight out of the source."""
    print("=== 1. player ownership (source level) ===")
    src = {p.name: p.read_text() for p in (ROOT / "src").glob("*.asm")}
    ply, main, ren = src["player.asm"], src["main.asm"], src["renderer.asm"]

    check("player.asm writes no VIC register",
          not re.search(r"^\s*sta\s+\$d0", ply, re.M | re.I))
    check("player.asm writes no sprite pointer table",
          not re.search(r"^\s*sta\s+(?:PTR_[AB]|\$07f8|\$2bf8)", ply, re.M | re.I))

    # $dc00 is the joystick AND the keyboard column drive. Exactly one read in
    # the production path, and every WRITE behind the fixture-key guard.
    reads = len(re.findall(r"^\s*lda\s+\$dc00", ply, re.M | re.I))
    check("player.asm reads $dc00 exactly once and never writes it",
          reads == 1 and not re.search(r"^\s*sta\s+\$dc00", ply, re.M | re.I),
          f"{reads} reads")
    check("fixture key selection is compiled out of the production path",
          re.search(r"^\.const FIXTURE_KEYS\s*=\s*false", main, re.M) is not None)
    check("the only call to the $dc00-writing key scan is behind that guard",
          re.search(r"\.if \(FIXTURE_KEYS\) \{\s*\n\s*jsr fixtureKeyPoll", main)
          is not None and main.count("jsr fixtureKeyPoll") == 1)

    # The published block is written by ONE routine, into the buffer that is
    # NOT current. This is what "immutable for the duration of the frame" means
    # mechanically: no instruction anywhere can reach the adopted copy.
    stores = re.findall(r"^\s*sta\s+schedPly\w*(\S*)", ren, re.M)
    check("every write to the published player block is indexed",
          len(stores) == 10 and all(s == ",x" for s in stores), f"{stores}")
    copy = ren[ren.index("lda plyPresX0"):ren.index("sta schedPlyD010,x")]
    before = ren[:ren.index("lda plyPresX0")]
    check("the player block is written with X = schedNext, never schedCurrent",
          before.rstrip().endswith("ldx schedNext") and "schedCurrent" not in copy)
    check("no other module writes the published player block",
          all("sta schedPly" not in t for n, t in src.items() if n != "renderer.asm"))
    check("exFrame still disables every sprite for the vertical blank",
          re.search(r"lda #0\s*\n\s*sta \$d015", ren) is not None)

    # Slice A read fire and stored it, and this check asserted nothing consumed
    # it. Slice B gave it a consumer -- src/weapon.asm -- so the claim is now
    # the narrower and more useful one: the INPUT LAYER still does not decide
    # weapon timing. player.asm names the bit once, to define it, and acts on it
    # nowhere.
    acts = [l for l in ply.splitlines()
            if "JOY_FIRE" in l and not l.strip().startswith(("//", ".const"))]
    check("the player defines the fire bit and does not act on it",
          "JOY_FIRE" in ply and not acts, f"{acts}")


# ===========================================================================
# One monitor command per group of state. See the harness note at the top.
SCHED_BASE = sym["schedBatches"]
SCHED_SPAN = 0x40
# Everything machine() reads out of that one dump, checked HERE rather than
# discovered as an IndexError somewhere in the middle of a run.
SCHED_FIELDS = ("schedBatches", "schedEnable", "schedEntries", "schedPlyX0",
                "schedPlyY0", "schedPlyPtr0", "schedPlyCol0", "schedPlyX1",
                "schedPlyY1", "schedPlyPtr1", "schedPlyCol1", "schedPlyEnable",
                "schedPlyD010", "schedCurrent", "curPage")
for _n in SCHED_FIELDS:
    assert 0 <= sym[_n] - SCHED_BASE < SCHED_SPAN - 1, (
        f"{_n} at ${sym[_n]:04x} is outside the bulk read "
        f"${SCHED_BASE:04x}..${SCHED_BASE + SCHED_SPAN - 1:04x}")


def machine(mon):
    """Sprite registers, the schedule scalars and the adopted player block."""
    r = rd(mon, 0xd000, 0x30)               # $d000..$d02f, one command
    s = rd(mon, SCHED_BASE, SCHED_SPAN)     # $c240..$c27f, one command
    g = lambda n: s[sym[n] - SCHED_BASE]
    c = g("schedCurrent")
    b = lambda n: s[sym[n] - SCHED_BASE + c]
    return {
        "raster": r[0x12] | ((r[0x11] & 0x80) << 1),
        "x0": r[0], "y0": r[1], "x1": r[2], "y1": r[3],
        "d010": r[0x10], "d015": r[0x15], "d017": r[0x17],
        "d01b": r[0x1b], "d01c": r[0x1c], "d01d": r[0x1d],
        # $d027-$d02e ARE FOUR-BIT REGISTERS. The VIC returns the unused top
        # nibble as ones, so $d027 holding colour 14 READS BACK as $fe. Comparing
        # the raw byte against the colour the block published fails every time,
        # on a machine that is doing exactly the right thing.
        "col0": r[0x27] & 0x0f, "col1": r[0x28] & 0x0f,
        "cur": c, "page": g("curPage"),
        "batches": b("schedBatches"), "schedEnable": b("schedEnable"),
        "entries": b("schedEntries"),
        "px0": b("schedPlyX0"), "py0": b("schedPlyY0"),
        "pptr0": b("schedPlyPtr0"), "pcol0": b("schedPlyCol0"),
        "px1": b("schedPlyX1"), "py1": b("schedPlyY1"),
        "pptr1": b("schedPlyPtr1"), "pcol1": b("schedPlyCol1"),
        "penable": b("schedPlyEnable"), "pd010": b("schedPlyD010"),
    }


def at_phase(mon, label, line, tries=8):
    """Stop at the ENTRY of a named raster phase and read the machine there.

    Each of these three points is an OWNERSHIP BOUNDARY, which is what makes
    checking the registers exactly there stronger than checking them somewhere:

        exHud      raster   4   nothing is enabled yet -- exFrame cleared $d015
                                at 250 and this phase has not written it
        exHandoff  raster  40   the HUD's composed values are live
        exBottom   raster 243   gameplay's composed values are live, and the
                                player's registers have survived the display

    THE STOP IS VERIFIED, and that is not a formality. The monitor returns from
    `x` on a prompt echo rather than on the actual stop -- free_run's own
    docstring says so -- so a sample can be read from a machine that is still
    running and land anywhere in the frame. It did: one reading of $d015 came
    back as $00, which is only true between rasters 250 and 4, and it was
    reported as the multiplexer having lost its enable bits.

    So the raster is checked against the line the phase owns, and a sample that
    did not land there is thrown away rather than believed.

    Only memory is read. The PC is never moved: doing that while stopped inside
    the handler leaves the I flag set and the machine never runs again.
    """
    for _ in range(tries):
        mon.cmd("delete")               # NO STALE CHECKPOINT. `x` can return on
        b = set_bp(mon, sym[label])     # a prompt echo before the machine has
        mon.cmd("x")                    # actually stopped, and the delete that
        m = machine(mon)                # follows then races it -- so a previous
        mon.cmd(f"delete {b}")          # phase's breakpoint can survive and be
        if m["raster"] == line:         # what the NEXT `x` stops on. It was:
            return m                    # a run of exBottom samples all came back
    check(f"stopped at {label} (raster {line})", False,   # at raster 40, which
          f"last reading was raster {m['raster']}")       # is exHandoff's line.
    return m


def settle(mon, seconds=0.5):
    """Clear every checkpoint and let the machine run free before bulk reads."""
    mon.cmd("delete")
    free_run(mon, sym["frameCounter"], seconds, slice_s=seconds)


def ptr_table(mon, page):
    """The two player entries of the pointer table the VIC is fetching from."""
    return tuple(rd(mon, (PTR_B if page else PTR_A), 2))


def hold_stick(mon, value=JOY_IDLE):
    """Drive the stick from the monitor instead of the host keyboard.

    AGENTS.md forbids sending simulated keyboard input to the emulated machine,
    and a detached joystick device cannot be driven at all -- so readInput has a
    hold flag, in the same spirit as `fixtureIndex` being pokeable and `pinFine`
    holding the scroll phase.
    """
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["joyState"], value)


def put_player(mon, x, y):
    """Place the player and let the whole publication path carry it through."""
    poke(mon, sym["plyX"], x & 0xff)
    poke(mon, sym["plyXHi"], x >> 8)
    poke(mon, sym["plyY"], y)
    free_run(mon, sym["frameCounter"], 0.4, slice_s=0.4)


# ===========================================================================
def quiet_mux(mon):
    """Empty the object pool and stop it refilling.

    Slice C gave production a real enemy that spawns on a timer, so "no
    gameplay sprites" stopped being something a production boot just IS and
    became something a test must ASK for. This file is about the player on its
    two reserved slots and about the zero-batch handoff path, both of which
    need an empty mux, so it says so explicitly rather than relying on the game
    having nothing else to draw.
    """
    # The spawner is switched OFF, not merely delayed. Every settle in this file
    # free-runs under warp for hundreds of frames, so a spawn timer poked to its
    # maximum expires several times over before the next read -- which is
    # exactly what the first version of this did, and it duly found two enemies
    # in a mux it had just emptied.
    poke(mon, sym["enemySpawnTick"], 0x60)      # RTS
    # The turrets are switched off for the same reason and by the same means.
    # They became a SECOND producer of pool objects when turret firing started
    # working: a hostile projectile is an ordinary pool object, so one in flight
    # makes "the mux pool is empty" false for a reason that has nothing to do
    # with the player.
    poke(mon, sym["turretFireTick"], 0x60)      # RTS
    for i in range(16):
        mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={sym['objectFree']:04x}, x={i:02x}")
        bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}")
    mon.cmd("delete")
    # AND THE SHIP IS MADE SOLID. Turrets can now shoot the player, and a hit
    # starts an invulnerability window that BLINKS the ship -- plyVisible 0 for
    # four frames in eight, which correctly clears plyPresEnable and so clears
    # the player's two bits in $d015. Every "the player publishes both reserved
    # slots" check in this repository reads as a failure on a dark frame. That
    # is the blink working, not the player being lost, so a file whose subject
    # is the player asks for a ship that is not mid-blink, exactly as it asks
    # for an empty mux above.
    poke(mon, sym["plyInvuln"], 0)
    poke(mon, sym["plyVisible"], 1)
    poke(mon, sym["plyDirty"], 1)           # force the republish

    settle(mon, 0.2)


# ===========================================================================
def production_boot(mon):
    print("\n=== 2. production boot: no fixture, no gameplay sprites ===")
    m = machine(mon)
    g = lambda n: rd(mon, sym[n])[0]
    check("the mux pool is empty (logCount 0)", g("logCount") == 0, f"{g('logCount')}")
    check("and the object pool holds no live membership bit",
          not any(rd(mon, sym["logActive"], 32)), "")
    check("nothing was accepted and no batch exists",
          m["entries"] == 0 and m["batches"] == 0,
          f"entries {m['entries']} batches {m['batches']}")
    check("no fixture is moving", g("fixtureMoves") == 0)
    check("the player is the only thing the frame enables",
          m["schedEnable"] == PLAYER_SLOT_MASK, f"${m['schedEnable']:02x}")
    check("the player block names both reserved slots",
          m["penable"] == PLAYER_SLOT_MASK, f"${m['penable']:02x}")
    check("the published pointers are the player's two bitmaps",
          (m["pptr0"], m["pptr1"]) == (PLAYER_PTR_BASE, PLAYER_PTR_TRIM),
          f"${m['pptr0']:02x}/${m['pptr1']:02x}")
    check("nothing is left dirty once the frame has been published",
          g("plyDirty") == 0)


def ownership_boundaries(mon):
    print("\n=== 3. raster 4: the vertical blank is empty (no Y+256 ghost) ===")
    m = at_phase(mon, "exHud", HUD_IRQ_LINE)
    check("the HUD phase is entered at raster 4", m["raster"] == HUD_IRQ_LINE,
          f"{m['raster']}")
    check("NOTHING is enabled between the frame transaction and the HUD phase",
          m["d015"] == 0, f"$d015 = ${m['d015']:02x} at raster {m['raster']}")
    check("the player's Y can never match a second time inside that window",
          m["py0"] >= PLAYER_MIN_Y and m["py1"] >= PLAYER_MIN_Y,
          f"{m['py0']}/{m['py1']}")

    print("\n=== 4. raster 40: exHud composed the HUD's bytes with the player's ===")
    m = at_phase(mon, "exHandoff", HANDOFF_LINE)
    check("the handoff is entered at raster 40", m["raster"] == HANDOFF_LINE,
          f"{m['raster']}")
    check("$d015 is the HUD's mask OR the player's, and nothing else",
          m["d015"] == (HUD_ENABLE | m["penable"]),
          f"${m['d015']:02x} vs ${HUD_ENABLE | m['penable']:02x}")
    check("$d010 is the HUD's bit OR the player's, and nothing else",
          m["d010"] == (HUD_D010 | m["pd010"]),
          f"${m['d010']:02x} vs ${HUD_D010 | m['pd010']:02x}")
    check("HW0/HW1 position registers equal the ADOPTED block",
          (m["x0"], m["y0"], m["x1"], m["y1"]) ==
          (m["px0"], m["py0"], m["px1"], m["py1"]),
          f"{(m['x0'], m['y0'], m['x1'], m['y1'])} vs "
          f"{(m['px0'], m['py0'], m['px1'], m['py1'])}")
    check("HW0/HW1 colours equal the adopted block",
          (m["col0"], m["col1"]) == (m["pcol0"], m["pcol1"]))
    check("the two layers are co-located",
          m["x0"] == m["x1"] and m["y0"] == m["y1"])
    check("the displayed page's pointer table holds the player's two bitmaps",
          ptr_table(mon, m["page"]) == (m["pptr0"], m["pptr1"]),
          f"{[hex(x) for x in ptr_table(mon, m['page'])]} page {m['page']}")
    modes = (m["d017"], m["d01c"], m["d01b"] & PLAYER_SLOT_MASK,
             m["d01d"] & PLAYER_SLOT_MASK)
    check("the HUD's mode registers leave the player hires, unexpanded, in front",
          modes == (0, 0, 0, 0), f"{modes}")

    print("\n=== 5. raster 243: the player has survived the whole display ===")
    m = at_phase(mon, "exBottom", BORDER_OPEN_LINE)
    check("the bottom phase is entered at raster 243", m["raster"] == 243,
          f"{m['raster']}")
    check("$d015 is the frame's complete enable mask",
          m["d015"] == m["schedEnable"],
          f"${m['d015']:02x} vs ${m['schedEnable']:02x}")
    check("$d010's player bits are still the adopted block's",
          (m["d010"] & PLAYER_SLOT_MASK) == m["pd010"],
          f"${m['d010']:02x} vs ${m['pd010']:02x}")
    check("HW0/HW1 were never touched again after raster 4",
          (m["x0"], m["y0"], m["x1"], m["y1"], m["col0"], m["col1"]) ==
          (m["px0"], m["py0"], m["px1"], m["py1"], m["pcol0"], m["pcol1"]))
    check("player Y is inside the range the renderer is promised",
          PLAYER_MIN_Y <= m["y0"] <= PLAYER_MAX_Y, f"{m['y0']}")
    modes = (m["d017"], m["d01c"], m["d01b"] & PLAYER_SLOT_MASK,
             m["d01d"] & PLAYER_SLOT_MASK)
    check("gameplay's mode registers leave the player hires, unexpanded, in front",
          modes == (0, 0, 0, 0), f"{modes}")

    print("\n=== 6. the pointers follow the page flip ===")
    seen, bad = {}, []
    for _ in range(8):
        m = at_phase(mon, "exBottom", BORDER_OPEN_LINE)
        got = ptr_table(mon, m["page"])
        seen[m["page"]] = seen.get(m["page"], 0) + 1
        if got != (m["pptr0"], m["pptr1"]):
            bad.append((m["page"], [hex(x) for x in got]))
    settle(mon)
    check("both pages were displayed during the sample", len(seen) == 2, f"{seen}")
    check("the DISPLAYED page's table always holds the player's two pointers",
          not bad, f"{bad[:3]}")
    check("the engine's own page/pointer self-checks are clean",
          rd(mon, sym["statPageMismatch"])[0] == 0 and
          rd(mon, sym["statPtrMismatch"])[0] == 0)


def x_msb(mon):
    print("\n=== 7. the X=255/256 crossing ===")
    for x in (254, 255, 256, 257, PLAYER_MAX_X):
        put_player(mon, x, 120)
        m = at_phase(mon, "exBottom", BORDER_OPEN_LINE)
        want = PLAYER_SLOT_MASK if x > 255 else 0
        ok = (m["px0"] == (x & 0xff) and m["px1"] == (x & 0xff)
              and m["pd010"] == want
              and m["x0"] == (x & 0xff) and m["x1"] == (x & 0xff)
              and (m["d010"] & PLAYER_SLOT_MASK) == want)
        check(f"  X={x}: low byte ${x & 0xff:02x}, MSB bits ${want:02x}", ok,
              f"block x={m['px0']} d010=${m['pd010']:02x} "
              f"reg x={m['x0']} d010=${m['d010']:02x}")
    settle(mon)


def bounds(mon):
    print("\n=== 8. the bounds are a total clamp, not a movement refusal ===")
    for px, py, wx, wy in ((0, 0, PLAYER_MIN_X, PLAYER_MIN_Y),
                           (511, 255, PLAYER_MAX_X, PLAYER_MAX_Y),
                           (5, 250, PLAYER_MIN_X, PLAYER_MAX_Y),
                           (400, 40, PLAYER_MAX_X, PLAYER_MIN_Y)):
        put_player(mon, px, py)
        gx = rd(mon, sym["plyX"])[0] | (rd(mon, sym["plyXHi"])[0] << 8)
        gy = rd(mon, sym["plyY"])[0]
        check(f"  poked ({px},{py}) -> ({wx},{wy})", (gx, gy) == (wx, wy), f"({gx},{gy})")
    m = at_phase(mon, "exBottom", BORDER_OPEN_LINE)
    check("the ship is still enabled after being driven out of bounds",
          m["penable"] == PLAYER_SLOT_MASK and
          (m["d015"] & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK,
          f"block ${m['penable']:02x} reg ${m['d015']:02x}")
    put_player(mon, 160, 200)
    settle(mon)


def load_ring(mon, tries=4):
    """Select RING-SLOW and VERIFY it is still loaded once the loop is running.

    select_p5 verifies at the instant of selection. That is not the same as
    "the fixture is running", and this file learned the difference the hard
    way: a desynchronised monitor returned a verified selection whose schedule
    read back empty a moment later. So it is re-checked after the machine has
    been left alone for a while, and retried if it is not there.
    """
    for _ in range(tries):
        if select_p5(mon, sym, RING_SLOW):
            settle(mon, 1.5)
            if (rd(mon, sym["logCount"])[0] == N_RING and
                    rd(mon, sym["ringActive"])[0] == 1 and
                    machine(mon)["batches"] > 0):
                return True
        time.sleep(0.3)
    return False


def composition(mon):
    print("\n=== 9. full-byte composition with a full mux (RING-SLOW) ===")
    if not load_ring(mon):
        check("RING-SLOW is loaded and running", False, "selection never held")
        return
    hold_stick(mon)
    put_player(mon, 300, 200)               # X >= 256, so the player owns MSB bits
    free_run(mon, sym["frameCounter"], 1.5)

    m = machine(mon)
    check("the fixture really is running", m["batches"] > 0, f"{m['batches']} batches")
    check("schedEnable carries the player's bits",
          (m["schedEnable"] & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK,
          f"${m['schedEnable']:02x}")
    check("schedEnable still carries gameplay bits",
          (m["schedEnable"] & ~PLAYER_SLOT_MASK & 0xff) != 0,
          f"${m['schedEnable']:02x}")
    check("the player's X MSB really is set for this test",
          m["pd010"] == PLAYER_SLOT_MASK, f"${m['pd010']:02x}")

    d010s = rd(mon, sym["batchD010"] + m["cur"] * MAX_BATCH, m["batches"])
    check("EVERY batch's $d010 carries the player's MSB bits",
          all((v & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK for v in d010s),
          f"{[hex(v) for v in d010s]}")
    check("at least one batch also sets a gameplay MSB bit",
          any((v & ~PLAYER_SLOT_MASK & 0xff) != 0 for v in d010s),
          f"{[hex(v) for v in d010s]}")

    live = [at_phase(mon, "exBottom", BORDER_OPEN_LINE) for _ in range(6)]
    settle(mon)
    check("$d015 keeps both the player's and the mux's bits",
          all((r["d015"] & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK and
              (r["d015"] & ~PLAYER_SLOT_MASK & 0xff) != 0 for r in live),
          f"{[hex(r['d015']) for r in live[:4]]}")
    check("$d010 keeps the player's MSB bits after the last batch of the frame",
          all((r["d010"] & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK for r in live),
          f"{[hex(r['d010']) for r in live[:4]]}")
    check("the player is still where the adopted block says, under full load",
          all((r["x0"], r["y0"]) == (r["px0"], r["py0"]) for r in live))
    check("the mux's own fault counters are clean",
          rd(mon, sym["statRejUnsafe"])[0] == 0 and
          rd(mon, sym["sortFault"])[0] == 0)


def engine_unchanged(mon, label, assert_budget=True):
    print(f"\n=== 10. engine invariants, {label} ===")
    settle(mon)
    for n in ("hudEntryMin", "handoffEntryMin", "topSplitMin", "botSplitMin",
              "hudUpdStartMin"):
        mon.cmd(f"> {sym[n]:04x} ff")
        mon.cmd(f"> {sym[n] + 1:04x} 00")
    for n in ("hudExitMax", "handoffExitMax", "edgeLate", "hudUpdWrapped",
              "scrollLate", "statPageMismatch", "statPtrMismatch", "gameOverrun",
              "gameSpanMax", "gameSpanOver", "publishSkip"):
        mon.cmd(f"> {sym[n]:04x} 00")
    free_run(mon, sym["frameCounter"], 8)
    g = lambda n, k=1: rd(mon, sym[n], k)
    fel, hud = g("frameEntryLine")[0], g("hudEntryMin", 2)
    ho, top, bot = g("handoffEntryMin", 2), g("topSplitMin", 2), g("botSplitMin", 2)
    check("the frame transaction is still at raster 250", fel == FRAME_IRQ_LINE, f"{fel}")
    check("every page flip happened at raster 250",
          g("flipLineMin")[0] == FRAME_IRQ_LINE and g("flipLineMax")[0] == FRAME_IRQ_LINE,
          f"{g('flipLineMin')[0]}..{g('flipLineMax')[0]}")
    check("the HUD phase still enters at raster 4", hud == [4, 4], f"{hud}")
    check("the HUD phase still finishes before its own first fetch",
          g("hudExitMax")[0] < 17, f"exit {g('hudExitMax')[0]}")
    check("the handoff still enters at raster 40", ho == [HANDOFF_LINE] * 2, f"{ho}")
    check("the handoff still finishes before the top split arms",
          0 < g("handoffExitMax")[0] < TOP_ARM_LINE, f"exit {g('handoffExitMax')[0]}")
    check("both aperture splits are exactly where they were",
          tuple(top) == TOP_SPLIT and bot == [BOT_SPLIT, BOT_SPLIT], f"{top} {bot}")
    check("no split was ever late", g("edgeLate")[0] == 0)
    check("no HUD bitmap write reached the VIC's fetch window",
          g("hudUpdWrapped")[0] == 0 and g("hudUpdStartMin")[0] >= 56)
    check("the scroller never found its back page unfinished", g("scrollLate")[0] == 0)

    span, over, run = g("gameSpanMax")[0], g("gameSpanOver")[0], g("gameOverrun")[0]
    skip = g("publishSkip")[0]
    print(f"  ..  main-thread span: worst {span} raster lines after the frame "
          f"transaction (~{span * 63} cycles of 19656); over-255 frames {over}, "
          f"missed frames {run}, publishSkip {skip}")
    if assert_budget:
        check("the main thread never missed a displayed frame", run == 0, f"{run}")
        check("the main thread finished inside the frame it was preparing",
              over == 0 and span < 250, f"span {span} over {over}")
    else:
        # RING-SLOW is the workload ENGINE_CONTRACT.md §10 names as a KNOWN
        # DEFERRED performance issue: sixteen moving sprites, re-sorted and
        # rebuilt every frame, measured at roughly 12% frame-record publication
        # skips before this slice existed. Asserting a budget here would be
        # asserting that a documented open issue is closed. The numbers are
        # printed so a before/after comparison has something to compare.
        print("  ..  not asserted: see docs/ENGINE_CONTRACT.md §10")
    return span, run, skip


# ===========================================================================
if __name__ == "__main__":
    source_invariants()
    v = None
    try:
        v = Vice(6604, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        hold_stick(mon)
        free_run(mon, sym["frameCounter"], 1)

        quiet_mux(mon)                          # this file is about the PLAYER
        production_boot(mon)
        ownership_boundaries(mon)
        x_msb(mon)
        bounds(mon)
        idle = engine_unchanged(mon, "0 gameplay sprites (production)")
        composition(mon)
        ring = engine_unchanged(mon, "16 gameplay sprites (RING-SLOW)",
                                assert_budget=False)
        print(f"\n  main-thread span, production: {idle[0]} lines, "
              f"{idle[1]} missed frames, {idle[2]} publishSkip")
        print(f"  main-thread span, RING-SLOW : {ring[0]} lines, "
              f"{ring[1]} missed frames, {ring[2]} publishSkip")
    finally:
        if v:
            v.close()
    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    print("\n=== ALL PASS ===" if not fails
          else f"\n=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
    sys.exit(1 if fails else 0)
