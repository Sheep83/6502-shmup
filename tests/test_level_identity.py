#!/usr/bin/env python3
"""A level looks the same however it was reached.

    python3 tests/test_level_identity.py

DIRECT LEVEL 2 vs CAMPAIGN-TRANSITIONED LEVEL 2, compared state for state at the
same scroll phase. The ENGINE is the same binary in both runs -- it is now
byte-identical whichever LEVELDIR it is built with -- so the only variable is
HOW level 2's package became resident: booted as LEVEL1 from a scratch disk, or
loaded at run time by the shop's Continue.

WHY THIS TEST EXISTS. Manual play found level 2's terrain wrong after a runtime
transition though correct when built directly, and the causes were three
separate compile-time leaks: terrainInit rewriting $d022/$d023 from the engine's
build-time palette, the metatile transpose walking only the build-time
definition count, and the wave director comparing against the build-time trigger
count. Each was invisible to every existing test because every existing test
plays the level the engine was built for. This one plays the level it was not.

IT COMPARES HASHES, not screenshots: the charset window, colour RAM, the
transposed sub-row tables, the metatile definitions, the map, the enemy sprite
window and the boss cells. If any of them ever diverges again, this says so.
"""
import hashlib
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (SYM, symbols, Vice, rd, rd1, set_bp,  # noqa: E402
                     step_n, check, report, LAUNCHED_PIDS)

sym = symbols(SYM)
COLOUR_RAM = 0xD800
# The first matrix row below the HUD. The HUD's own rows are excluded from the
# colour-RAM comparison; see snapshot().
PLAYFIELD_FIRST = 4
TERRAIN_GLYPHS = 0x0B00
TRTILES = 0x6400


def h(b):
    return hashlib.sha256(bytes(b)).hexdigest()[:12]


def settle(mon):
    """Step to a KNOWN scroll phase, so the two runs are compared like for like.

    $d011's low three bits are YSCROLL, $d018 names whichever page is currently
    published, and both change every frame with the fine scroll. Sampling the two
    runs at the same FRAME COUNT does not sample them at the same scroll PHASE --
    the transitioned run spends a different amount of time getting there -- so
    the first comparison reported those three as differences when they are simply
    the scroller doing its job. Landing both on fine phase 0 removes the variable.
    """
    for _ in range(16):
        step_n(mon, sym["frameCounter"], 1, lambda: None)
        if rd1(mon, sym["scrollFine"]) == 0:
            return True
    return False


def snapshot(mon):
    settle(mon)
    s = {}
    for r in (0x11, 0x16, 0x18, 0x20, 0x21, 0x22, 0x23):
        s[f"$d0{r:02x}"] = rd1(mon, 0xD000 + r)
    s["$dd00 (VIC bank)"] = rd1(mon, 0xDD00) & 3
    for n in ("trnBgColour", "trnCramValue", "trnGlyphCount", "turretCount",
              "wvNextTrig", "scrollFine"):
        s[n] = rd1(mon, sym[n])
    s["LEVELPKG_TRIGN"] = rd1(mon, 0xFF92)
    s["pkg signature"] = h(rd(mon, 0xFB70, 4))
    s["pkg palette"] = list(rd(mon, 0xFF74, 4))
    s["charset $0b00 (1K)"] = h(rd(mon, TERRAIN_GLYPHS, 1024))
    # THE PLAYFIELD'S COLOUR RAM, NOT ALL OF IT. The top rows carry the HUD,
    # whose cells depend on the score, the lives and the P count -- all of which
    # legitimately differ between a fresh boot and a run that has played a level
    # and been through the shop. What must match is the TERRAIN fill: every
    # playfield cell holding this level's trnCramValue.
    cram = rd(mon, COLOUR_RAM, 1000)
    fill = rd1(mon, sym["trnCramValue"]) & 0x0F
    play = [c & 0x0F for c in cram[PLAYFIELD_FIRST * 40:]]
    s["playfield cRAM all == fill"] = all(c == fill for c in play)
    s["playfield cRAM fill value"] = fill
    s["trTiles (1K)"] = h(rd(mon, TRTILES, 1024))
    s["metatile defs"] = h(rd(mon, 0xF130, 1024))
    s["map first 256"] = h(rd(mon, 0xE000, 256))
    s["enemy window (1280)"] = h(rd(mon, 0x2C00, 1280))
    s["boss cells (256)"] = h(rd(mon, 0x3580, 256))
    return s


def make_direct_disk():
    """A disk whose LEVEL1 is level 2's package, built into disposable scratch.

    THE SAME ENGINE BINARY, so the package is the only variable. Building a
    second engine with LEVELDIR=src/level2 would have compared two programs as
    well as two packages, and the whole point is to isolate the package.
    """
    import subprocess, tempfile
    d = Path(tempfile.mkdtemp(prefix="levelid-")) / "direct2.d64"
    c1541 = "/opt/homebrew/bin/c1541"
    q = subprocess.DEVNULL
    subprocess.run([c1541, "-format", "direct2,01", "d64", str(d)], stdout=q, stderr=q)
    subprocess.run([c1541, str(d), "-write", str(ROOT / "build/shmup.prg"), "engine"], stdout=q, stderr=q)
    for name in ("level1", "level2"):
        subprocess.run([c1541, str(d), "-write", str(ROOT / "build/level2.prg"), name], stdout=q, stderr=q)
    return d


def run_direct(disk):
    v = Vice(6630, str(disk), boot="exact")
    try:
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 40, lambda: None)
        return snapshot(mon)
    finally:
        v.close()


def run_transitioned():
    v = Vice(6631, str(ROOT / "build" / "shmup.d64"), boot="exact")
    try:
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        step_n(mon, sym["frameCounter"], 40, lambda: None)
        # the shop's own Continue: advance, load, re-init, resume
        # A FLAT SLEEP, NOT A POLL. Every monitor read HALTS the machine, so a
        # loop that polls gsState freezes the transition partway through and
        # then reports whatever it caught -- which is how an earlier run of this
        # script "found" colour RAM still holding level 1's value. The load and
        # re-init take well under two seconds of warp; four is generous.
        mon.cmd(f"g {sym['gsUpgradeContinue']:04x}")
        time.sleep(4.0)
        # the breakpoint is still armed, so we are on level 2's FIRST frame;
        # step to the same frame count the direct run used
        step_n(mon, sym["frameCounter"], 39, lambda: None)
        return snapshot(mon)
    finally:
        v.close()


# $d018's VM BITS NAME THE PUBLISHED PAGE, and the scroller alternates it every
# coarse step -- so two runs at the same fine phase can legitimately be on
# different pages. Its CHARSET bits are what matter here and are compared
# separately. Everything else must match exactly.
# $d011's LOW THREE BITS ARE YSCROLL, published one frame behind scrollFine by
# the double buffer, so two runs on the same fine phase can still read different
# values here. Its mode bits are compared instead, like $d018's charset bits.
PAGE_ALTERNATES = {"$d018", "$d011"}


def main():
    disk = make_direct_disk()
    a = run_direct(disk)
    b = run_transitioned()
    shutil.rmtree(disk.parent, ignore_errors=True)

    for k in sorted(set(a) - PAGE_ALTERNATES):
        check(f"direct and transitioned level 2 agree: {k}", a[k] == b[k],
              f"direct {a[k]}  transitioned {b[k]}")

    # the charset SELECT bits of $d018, which are not the alternating half
    check("direct and transitioned level 2 agree: $d011 mode bits",
          (a["$d011"] & 0xF8) == (b["$d011"] & 0xF8),
          f"direct ${a['$d011']:02x}  transitioned ${b['$d011']:02x} "
          f"(YSCROLL excluded: it is published a frame behind scrollFine)")
    check("direct and transitioned level 2 agree: $d018 charset bits",
          (a["$d018"] & 0x0E) == (b["$d018"] & 0x0E),
          f"direct ${a['$d018']:02x}  transitioned ${b['$d018']:02x} "
          f"(VM bits alternate with the published page and are excluded)")

    # and the level really is level 2, not level 1 twice over
    check("...and it IS level 2, not level 1 reached two ways",
          b["trnGlyphCount"] == 128 and b["trnBgColour"] == 5
          and b["turretCount"] == 0 and b["LEVELPKG_TRIGN"] == 7,
          f"{b['trnGlyphCount']} glyphs, bg {b['trnBgColour']}, "
          f"{b['turretCount']} turrets, {b['LEVELPKG_TRIGN']} triggers")

    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
