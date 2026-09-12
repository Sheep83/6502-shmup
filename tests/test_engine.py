#!/usr/bin/env python3
"""The engine invariant probe — the one to run constantly.

This is not a qualification suite. It is a compact guard over the handful of
invariants that are expensive to get wrong, cheap to break by accident, and not
visible until a human is staring at a glitch: the raster phase schedule, the
aperture splits, sprite ownership across the HUD handoff, page/pointer
coherence, and the window in which HUD bitmap RAM may be written.

It reads the engine's OWN instrumentation counters rather than re-deriving
anything, so it measures what the machine did over tens of thousands of frames
instead of sampling a few. Every counter it reads is a min/max or a saturating
fault count, which is why a single reading can speak for a whole run.

Runs in about a minute across five fixtures. The inherited qualification ladder
(test_p0..test_p5) is still here and still passes; it is not part of ordinary
game development. See docs/ENGINE_CONTRACT.md.
"""
import sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import (PRG, SYM, symbols, Vice, rd, free_run, LAUNCHED_PIDS,
                     MAX_SCHED)
from test_p3 import select_p3
from test_p5 import select_p5

sym = symbols(SYM)

# --- the production contract, restated independently of the assembler --------
# docs/ENGINE_CONTRACT.md is the prose; these are the numbers. If a change to
# the engine makes one of these wrong, the contract changed and that is a
# decision, not a test failure to paper over.
FRAME_IRQ_LINE  = 250
HUD_IRQ_LINE    = 4
HUD_Y           = 16
HANDOFF_LINE    = 40
TOP_ARM_LINE    = 53
TOP_SPLIT       = (54, 55)      # 54 at YSCROLL=7, 55 otherwise -- see exTop
BOT_SPLIT       = 248
MIN_SPRITE_Y    = 55
MAX_SPRITE_Y    = 226
BLANK_CHARSET   = 0x3800
GAMEPLAY_PTR    = range(0x80, 0x90)
HUD_PTR         = range(0xc8, 0xc8 + 18)

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def source_invariants():
    """Ownership rules that can be read straight out of the source."""
    print("=== 1. single-writer ownership (source level) ===")
    src = {p.name: p.read_text() for p in (ROOT / "src").glob("*.asm")}
    for reg in ("d000", "d001", "d010", "d015", "d017", "d01b", "d01c", "d01d", "d027"):
        outside = {n: len(re.findall(r"^\s*sta\s+\$%s" % reg, t, re.M | re.I))
                   for n, t in src.items()}
        outside = {n: c for n, c in outside.items() if c and n not in ("renderer.asm", "main.asm")}
        check(f"only the renderer writes ${reg}", not outside, f"{outside}")
    # FOUR pointer-writing instructions now, not two: the batch executor's, the
    # HUD's, and the player's two. The pattern matches an unindexed `sta PTR_A+1`
    # as well as an indexed one, so a new writer cannot hide by dropping the ,x.
    ptr = {n: len(re.findall(r"^\s*sta\s+PTR_[AB]\b", t, re.M)) for n, t in src.items()}
    check("exactly four instructions write a sprite pointer table, all in the renderer",
          sum(ptr.values()) == 4 and ptr.get("renderer.asm") == 4, f"{ptr}")
    patched = len(re.findall(r"sta\s+(?:exPtr|huPtr|plPtr0|plPtr1)Store\s*\+\s*2",
                             src["renderer.asm"]))
    check("all four pointer destinations are patched from one place (exFrame)",
          patched == 4, f"{patched} patch sites")
    for owner in ("hud.asm", "player.asm"):
        check(f"{owner} writes no VIC register at all",
              not re.search(r"^\s*sta\s+\$d0", src[owner], re.M | re.I))


def static_memory(mon):
    print("\n=== 2. static memory the VIC depends on ===")
    cs = []
    for a in range(BLANK_CHARSET, BLANK_CHARSET + 0x800, 0x40):
        cs += rd(mon, a, 16)
    check("the blank charset at $3800 is entirely zero", set(cs) == {0}, f"{sorted(set(cs))}")
    check("$3fff, the VIC idle byte, is zero", rd(mon, 0x3fff)[0] == 0)
    ptrs = rd(mon, sym["hudPtrLive"], 6)
    check("every live HUD pointer is inside the HUD bitmap pool",
          all(p in HUD_PTR for p in ptrs), f"{[hex(p) for p in ptrs]}")
    check("no HUD pointer collides with the gameplay bitmap pool",
          all(p not in GAMEPLAY_PTR for p in ptrs), f"{[hex(p) for p in ptrs]}")


def fixture_run(mon, name, seconds=4):
    """Zero every instrumented counter, free-run, and read what happened."""
    for n in ("hudEntryMin", "handoffEntryMin", "topSplitMin", "botSplitMin",
              "hudUpdStartMin"):
        mon.cmd(f"> {sym[n]:04x} ff")
        mon.cmd(f"> {sym[n] + 1:04x} 00")
    for n in ("hudExitMax", "handoffExitMax", "edgeLate", "hudUpdWrapped",
              "scrollLate", "statPageMismatch", "statPtrMismatch"):
        mon.cmd(f"> {sym[n]:04x} 00")
    f0 = rd(mon, sym["frameCounter"], 2)
    free_run(mon, sym["frameCounter"], seconds, slice_s=seconds)
    f1 = rd(mon, sym["frameCounter"], 2)
    g = lambda n, k=1: rd(mon, sym[n], k)
    return {
        "frames":   ((f1[0] | f1[1] << 8) - (f0[0] | f0[1] << 8)) & 0xffff,
        "hudEnter": g("hudEntryMin", 2),   "hudExit":  g("hudExitMax")[0],
        "hoEnter":  g("handoffEntryMin", 2), "hoExit":  g("handoffExitMax")[0],
        "top":      g("topSplitMin", 2),   "bot":      g("botSplitMin", 2),
        "edgeLate": g("edgeLate")[0],      "fel":      g("frameEntryLine")[0],
        "wrap":     g("hudUpdWrapped")[0], "updStart": g("hudUpdStartMin", 2),
        "pgMis":    g("statPageMismatch")[0], "ptrMis": g("statPtrMismatch")[0],
        "scrLate":  g("scrollLate")[0],
    }


def admitted_y(mon):
    """No sprite outside the production Y range may reach CURRENT."""
    cur = rd(mon, sym["schedCurrent"])[0]
    n = rd(mon, sym["schedEntries"] + cur)[0]
    if n == 0:
        return None
    ys = rd(mon, sym["schedY"] + cur * MAX_SCHED, n)
    return min(ys), max(ys)


if __name__ == "__main__":
    source_invariants()
    v = None
    try:
        v = Vice(6600, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        static_memory(mon)

        print("\n=== 3. raster phase schedule and coherence, per fixture ===")
        print("  fixture      frames   HUD      exit  handoff   exit  top       "
              "bottom      late  FEL  wrap  admitted Y")
        # The first row is the PRODUCTION boot state: no fixture, no gameplay
        # sprites, the player alone on HW0/HW1. It is deliberately first,
        # because "the engine still holds every invariant with an empty mux" is
        # the state the game actually runs in.
        for name, sel, fx in (("boot/game", None, None),
                              ("MAXCAP",     select_p3, 22),
                              ("RING-SLOW",  select_p5, 31),
                              ("RING-FAST",  select_p5, 32),
                              ("RING-SHIFT", select_p5, 33)):
            picked = True
            if sel:
                picked = False
                for _ in range(8):
                    if sel(mon, sym, fx):
                        picked = True
                        break
                free_run(mon, sym["frameCounter"], 1)
            # A fixture that did not actually load measures NOTHING, and every
            # check below then passes on an empty schedule. The selection
            # helpers already verify themselves and return None when they fail;
            # this is the caller finally paying attention to that.
            check(f"  {name}: the fixture actually loaded", picked)
            r = fixture_run(mon, name)
            yr = admitted_y(mon)
            ytxt = f"{yr[0]}..{yr[1]}" if yr else "none"
            print(f"  {name:11s} {r['frames']:6d}   {str(r['hudEnter']):8s} {r['hudExit']:4d}  "
                  f"{str(r['hoEnter']):8s} {r['hoExit']:5d}  {str(r['top']):8s}  "
                  f"{str(r['bot']):10s} {r['edgeLate']:4d} {r['fel']:4d} {r['wrap']:5d}  {ytxt}")
            ok = (r["fel"] == FRAME_IRQ_LINE
                  and r["hudEnter"] == [HUD_IRQ_LINE, HUD_IRQ_LINE]
                  and r["hudExit"] < HUD_Y + 1
                  and r["hoEnter"] == [HANDOFF_LINE, HANDOFF_LINE]
                  and r["hoExit"] < TOP_ARM_LINE
                  # THE SPLIT LANDED ON ITS OWN TARGET, WHICHEVER TARGET THAT
                  # WAS. exTop aims at 54 when the adopted YSCROLL is 7 and at
                  # 55 otherwise, and edgeLate counts any split that missed --
                  # so those two conditions ARE the invariant.
                  #
                  # This used to demand `top == (54, 55)` exactly, which also
                  # requires a YSCROLL=7 frame to have been DISPLAYED during the
                  # window. That is a statement about the fixture's frame-record
                  # health, not about the aperture: a fixture whose main thread
                  # is over budget drops frame records (ENGINE_CONTRACT.md §10),
                  # the displayed phases become a subsample of the eight, and
                  # which subsample survives is a matter of what the skipping
                  # pattern happens to be. It moved when the scroll direction
                  # reversed the order of the phases, and RING-FAST -- which
                  # skips publications with a period of two -- stopped showing
                  # phase 7 at all while still splitting perfectly on every
                  # frame it did display. Asserted where it is guaranteed
                  # instead: see the production check below.
                  and TOP_SPLIT[0] <= r["top"][0]
                  and r["top"][1] <= TOP_SPLIT[1]
                  and r["bot"] == [BOT_SPLIT, BOT_SPLIT]
                  and r["edgeLate"] == 0)
            check(f"  {name}: every raster phase landed on its own line", ok)
            if sel is None:
                # The production configuration keeps up with the frame: nothing
                # is dropped, so every one of the eight phases IS displayed and
                # both split lines MUST be observed.
                check("  production: both aperture split lines were exercised",
                      tuple(r["top"]) == TOP_SPLIT, f"{r['top']}")
            check(f"  {name}: page/pointer coherence and scroller clean",
                  r["pgMis"] == 0 and r["ptrMis"] == 0 and r["scrLate"] == 0,
                  f"pg {r['pgMis']} ptr {r['ptrMis']} scrollLate {r['scrLate']}")
            check(f"  {name}: no HUD bitmap write ever reached the VIC's fetch window",
                  r["wrap"] == 0 and r["updStart"][0] >= 56, f"wrap {r['wrap']}")
            check(f"  {name}: every admitted sprite inside the production Y range",
                  yr is None or (yr[0] >= MIN_SPRITE_Y and yr[1] <= MAX_SPRITE_Y), ytxt)
    finally:
        if v:
            v.close()
    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    print("\n=== ALL PASS ===" if not fails else f"\n=== {len(fails)} FAILURES: "
          + "; ".join(fails) + " ===")
    sys.exit(1 if fails else 0)
