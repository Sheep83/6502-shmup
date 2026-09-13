#!/usr/bin/env python3
"""Slice A' — scroll direction and the world/stage progression contract.

What this proves
----------------
* the playfield scrolls DOWNWARD: the fine scroll counts UP 0..7 and the stage
  row at the top of the page steps BACK one per wrap, which is the original
  game's forward-play direction;
* one coarse step per eight pixel steps, never missed and never doubled;
* the two counters are exactly what the contract says they are --
  `worldProgress` only ever increases, `stageTopRow` only ever steps back, and
  `stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS` on every
  single frame of a long trace;
* every row of the DISPLAYED page carries the stage row it should, all 25 of
  them, so a duplicated, skipped or reversed row cannot hide;
* the HIDDEN page holds the exact rows the next coarse step will reveal;
* the aperture, the HUD, the frame transaction and the player are where Slice 1
  and Slice A left them.

The heart of it is ONE TRACE. Stopping at frameDiagnostics -- inside exFrame,
after $d011 and $d018 have been written -- on consecutive frames gives the
displayed YSCROLL, the stage row, the progress counter and the page together,
frame by frame. Direction, cadence, progression and row continuity are all
statements about how those four move relative to each other, so one trace
settles all of them at once and no two checks can disagree about which frame
they were looking at.

VICE process ownership: this script owns exactly the PID it launches and kills
it on success, failure and exception via try/finally.
"""
import sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import PRG, SYM, symbols, Vice, rd, set_bp, free_run, LAUNCHED_PIDS

sym = symbols(SYM)

# --- the contract, restated independently of the assembler ------------------
STAGE_ROWS      = 420
SCREEN_ROWS     = 25
STAGE_START_ROW = STAGE_ROWS - SCREEN_ROWS          # 395
SCREEN_A, SCREEN_B = 0x0400, 0x2800
FRAME_IRQ_LINE  = 250
TOP_SPLIT, BOT_SPLIT = (54, 55), 248
PLAYER_SLOT_MASK = 0b00000011
HEXDIGIT = [0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,0x38,0x39,1,2,3,4,5,6]

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def w16(mon, name):
    b = rd(mon, sym[name + "Lo"], 1) + rd(mon, sym[name + "Hi"], 1)
    return b[0] | (b[1] << 8)


# ===========================================================================
def source_invariants():
    print("=== 1. the direction, as the source states it ===")
    src = (ROOT / "src/scroll.asm").read_text()

    check("the fine scroll counts UP", "inc scrollFine" in src
          and "dec scrollFine" not in src)
    check("the stage row steps BACK through the map, never forward",
          "jsr rowBack" in src and "inc stageTopRow" not in src)
    check("world progress only ever increases",
          "inc worldProgressLo" in src and "dec worldProgress" not in src)
    m = re.search(r"^\.const STAGE_ROWS\s*=\s*(\d+)", src, re.M)
    n = re.search(r"^\.const STAGE_START_ROW\s*=\s*STAGE_ROWS - SCREEN_ROWS", src, re.M)
    check("the stage height and start row are stated as constants",
          m is not None and int(m.group(1)) == STAGE_ROWS and n is not None,
          f"STAGE_ROWS {m.group(1) if m else '?'}")
    check("the scroller still writes no VIC register",
          not re.search(r"^\s*sta\s+\$d0", src, re.M | re.I))
    # The old name carried the opposite direction. Leaving it in place while
    # reversing what it counts is exactly the overloading this slice exists to
    # remove, so the rename is checked rather than assumed.
    check("no variable still called worldRow survives the reversal",
          "worldRowLo" not in src and "worldRowHi" not in src)


# ===========================================================================
def trace(mon, n=140):
    """Sample inside exFrame, after the adoption, and KEY EVERY SAMPLE TO ITS
    FRAME NUMBER.

    `mon.cmd("x")` returns on a prompt echo rather than on the actual stop, so a
    plain loop reads some frames twice and calls the result consecutive: an
    earlier draft of this file produced the sequence 2,2,3,4,4,5,5,6,6,7,7,0,0
    and reported that the fine scroll was not advancing one pixel per frame, on
    a machine that was advancing exactly one pixel per frame. The frame counter
    is what makes a sample identifiable, so it is read with every one.
    """
    out = []
    mon.cmd("delete")
    b = set_bp(mon, sym["frameDiagnostics"])
    for _ in range(n):
        mon.cmd("x")
        vic = rd(mon, 0xd011, 2)                     # $d011 and $d012 together
        raster = vic[1] | ((vic[0] & 0x80) << 1)
        # DID WE ACTUALLY STOP HERE? frameDiagnostics is reached about two
        # raster lines after exFrame is entered at 250. A sample read from a
        # machine that never stopped can be taken anywhere in the frame, and
        # then $d011 and the counters describe different instants -- which is
        # what produced a YSCROLL sequence of 3,3,4,5,6,0,0 on a machine that
        # was advancing one pixel per frame perfectly.
        if not (FRAME_IRQ_LINE <= raster <= FRAME_IRQ_LINE + 4):
            continue
        f = rd(mon, sym["frameCounter"], 2)
        st = rd(mon, sym["stageTopRowLo"], 4)        # top lo/hi, progress lo/hi
        out.append({
            "frame": f[0] | (f[1] << 8),
            "yscroll": vic[0] & 7,
            "top": st[0] | (st[1] << 8),
            "prog": st[2] | (st[3] << 8),
            "page": rd(mon, sym["curPage"])[0],
        })
    mon.cmd(f"delete {b}")
    mon.cmd("delete")
    uniq = [f for i, f in enumerate(out) if i == 0 or f["frame"] != out[i - 1]["frame"]]
    return uniq


def direction(mon):
    print("\n=== 2. consecutive frames: direction and cadence ===")
    t = trace(mon)
    # Only ADJACENT frames can say anything about a per-frame step, so the
    # analysis is built from pairs the frame counter proves are adjacent.
    pr = [(a, b) for a, b in zip(t, t[1:]) if ((b["frame"] - a["frame"]) & 0xffff) == 1]
    print(f"  {len(t)} distinct frames, {len(pr)} adjacent pairs")
    print(f"  YSCROLL   {[f['yscroll'] for f in t[:32]]}")
    print(f"  stageTop  {[f['top'] for f in t[:32]]}")
    print(f"  progress  {[f['prog'] for f in t[:32]]}")
    print(f"  page      {''.join('AB'[f['page']] for f in t[:32])}")
    check("enough adjacent frame pairs to judge a per-frame step", len(pr) >= 16,
          f"{len(pr)}")

    # --- fine scroll: UP, one per frame, wrapping 7 -> 0 -------------------
    check("the fine scroll advances exactly one pixel per frame, upward",
          all((a["yscroll"] + 1) % 8 == b["yscroll"] for a, b in pr),
          f"{[(a['yscroll'], b['yscroll']) for a, b in pr if (a['yscroll'] + 1) % 8 != b['yscroll']][:3]}")
    check("every one of the eight phases appears in the trace",
          {f["yscroll"] for f in t} == set(range(8)),
          f"{sorted({f['yscroll'] for f in t})}")

    # --- the coarse step happens on the 7 -> 0 wrap, and ONLY there --------
    wrap = [(a["yscroll"] == 7 and b["yscroll"] == 0) for a, b in pr]
    check("coarse steps happened during the trace", sum(wrap) >= 2, f"{sum(wrap)}")
    check("world progress changes on the 7->0 wrap and nowhere else",
          all((b["prog"] != a["prog"]) == w for (a, b), w in zip(pr, wrap)))
    check("the stage row changes on the 7->0 wrap and nowhere else",
          all((b["top"] != a["top"]) == w for (a, b), w in zip(pr, wrap)))
    check("the page flips on the 7->0 wrap and nowhere else",
          all((b["page"] != a["page"]) == w for (a, b), w in zip(pr, wrap)))

    # --- the two counters -------------------------------------------------
    steps = [(a, b) for (a, b), w in zip(pr, wrap) if w]
    check("world progress advances by exactly one per coarse step, always up",
          all(b["prog"] == a["prog"] + 1 for a, b in steps),
          f"{[(a['prog'], b['prog']) for a, b in steps[:3]]}")
    check("the stage row steps BACK exactly one per coarse step",
          all(b["top"] == (a["top"] - 1) % STAGE_ROWS for a, b in steps),
          f"{[(a['top'], b['top']) for a, b in steps[:3]]}")
    check("the stage row never advances forward through the map",
          all(b["top"] in (a["top"], (a["top"] - 1) % STAGE_ROWS) for a, b in pr))

    # --- THE contract, on every frame of the trace ------------------------
    bad = [(f["top"], f["prog"]) for f in t
           if f["top"] != (STAGE_START_ROW - f["prog"]) % STAGE_ROWS]
    check("stageTopRow == (STAGE_START_ROW - worldProgress) mod STAGE_ROWS",
          not bad, f"{bad[:3]}")
    # stageLoops increments on the coarse step whose stage row is zero on
    # ENTRY, i.e. at progress = START+1, START+1+ROWS, START+1+2*ROWS, ...
    loops, prog = w16_pair(mon, "stageLoopsLo"), t[-1]["prog"]
    want = 0 if prog <= STAGE_START_ROW else 1 + (prog - 1 - STAGE_START_ROW) // STAGE_ROWS
    check("the stage-loop counter agrees with the row arithmetic",
          loops == want, f"stageLoops {loops}, expected {want} at progress {prog}")
    check("the coarse-step diagnostic agrees with world progress",
          w16(mon, "worldProgress") == w16_pair(mon, "coarseCount"),
          f"progress {w16(mon, 'worldProgress')} vs coarse "
          f"{w16_pair(mon, 'coarseCount')}")
    return t


def w16_pair(mon, name):
    b = rd(mon, sym[name], 2)
    return b[0] | (b[1] << 8)


# ===========================================================================
def row_continuity(mon):
    print("\n=== 3. every row of both pages carries the stage row it should ===")
    mon.cmd("delete")
    b = set_bp(mon, sym["frameDiagnostics"])
    mon.cmd("x")
    mon.cmd(f"delete {b}")

    cur = rd(mon, sym["curPage"])[0]
    top = w16(mon, "stageTopRow")
    regen = w16(mon, "regenTopRow")
    regen_row = rd(mon, sym["regenRow"])[0]
    front = rd(mon, SCREEN_A if cur == 0 else SCREEN_B, 1000)
    back = rd(mon, SCREEN_B if cur == 0 else SCREEN_A, 1000)
    mon.cmd("delete")

    def ident(page, r):
        return tuple(page[r * 40: r * 40 + 2])

    def want(row):
        v = row % STAGE_ROWS & 0xff
        return (HEXDIGIT[v >> 4], HEXDIGIT[v & 0x0f])

    bad = [(r, ident(front, r), want(top + r)) for r in range(SCREEN_ROWS)
           if ident(front, r) != want(top + r)]
    check(f"the DISPLAYED page holds stage rows {top}..{top + 24}, in order",
          not bad, f"{bad[:3]}")

    # Rows increase DOWN the screen and the window steps back, so consecutive
    # matrix rows must differ by exactly one. A mirrored page would still have
    # the right SET of rows; this is what catches the order.
    order = [((front[(r + 1) * 40] << 8 | front[(r + 1) * 40 + 1])
              != (front[r * 40] << 8 | front[r * 40 + 1]))
             for r in range(SCREEN_ROWS - 1)]
    check("no two adjacent rows of the displayed page are identical",
          all(order))

    check("the hidden page is being built one row FURTHER BACK",
          regen == (top - 1) % STAGE_ROWS, f"regenTopRow {regen}, stageTopRow {top}")
    if regen_row >= SCREEN_ROWS:
        badb = [(r, ident(back, r), want(regen + r)) for r in range(SCREEN_ROWS)
                if ident(back, r) != want(regen + r)]
        check(f"the HIDDEN page already holds stage rows {regen}..{regen + 24}",
              not badb, f"{badb[:3]}")
    else:
        # Mid-regeneration: only the rows already written can be checked, and
        # reporting that honestly beats asserting something about rows that do
        # not exist yet.
        badb = [(r, ident(back, r), want(regen + r)) for r in range(regen_row)
                if ident(back, r) != want(regen + r)]
        check(f"the HIDDEN page's first {regen_row} rebuilt rows are correct",
              not badb, f"{badb[:3]}")

    check("pageTopRow names the stage row the displayed page really starts at",
          (rd(mon, sym["pageTopRowLo"] + cur)[0]
           | (rd(mon, sym["pageTopRowHi"] + cur)[0] << 8)) == top,
          f"pageTopRow[{cur}] vs stageTopRow {top}")


def flip_continuity(mon):
    """The flip itself: does the newly displayed page START on the newly
    revealed stage row, or does it repeat one / miss one?

    Section 2 proves the COUNTERS step by one. This proves the SCREEN agrees
    with them, which is the part a duplicated or skipped row would show up in.
    """
    print("\n=== 4. the page flip neither duplicates nor skips a row ===")
    mon.cmd("delete")
    bp = set_bp(mon, sym["frameDiagnostics"])
    seen, last = [], None
    for _ in range(120):
        mon.cmd("x")
        vic = rd(mon, 0xd011, 2)
        raster = vic[1] | ((vic[0] & 0x80) << 1)
        if not (FRAME_IRQ_LINE <= raster <= FRAME_IRQ_LINE + 4):
            continue                                # not stopped where we think
        cur = rd(mon, sym["curPage"])[0]
        top = w16(mon, "stageTopRow")
        if last is not None and cur != last[0]:
            first = rd(mon, SCREEN_A if cur == 0 else SCREEN_B, 2)
            seen.append((last[1], top, (first[0] << 8) | first[1]))
        last = (cur, top)
        if len(seen) >= 4:
            break
    mon.cmd(f"delete {bp}")
    mon.cmd("delete")

    check("page flips were observed", len(seen) >= 3, f"{len(seen)}")
    steps = [(before - after) % STAGE_ROWS for before, after, _ in seen]
    check("each flip moves the window back by EXACTLY one stage row",
          bool(steps) and all(s == 1 for s in steps), f"{steps}")
    idents = []
    for _, after, first in seen:
        v = after % STAGE_ROWS & 0xff
        idents.append((first, (HEXDIGIT[v >> 4] << 8) | HEXDIGIT[v & 0x0f]))
    check("the newly displayed page's top row IS the newly revealed stage row",
          bool(idents) and all(a == b for a, b in idents),
          f"{[(hex(a), hex(b)) for a, b in idents[:3]]}")


# ===========================================================================
def engine_unchanged(mon):
    print("\n=== 5. the engine is where Slice 1 and Slice A left it ===")
    mon.cmd("delete")
    for n in ("hudEntryMin", "handoffEntryMin", "topSplitMin", "botSplitMin",
              "hudUpdStartMin"):
        mon.cmd(f"> {sym[n]:04x} ff")
        mon.cmd(f"> {sym[n] + 1:04x} 00")
    for n in ("hudExitMax", "handoffExitMax", "edgeLate", "hudUpdWrapped",
              "scrollLate", "statPageMismatch", "statPtrMismatch", "publishSkip",
              "gameOverrun", "gameSpanMax", "gameSpanOver"):
        mon.cmd(f"> {sym[n]:04x} 00")
    px, py = rd(mon, sym["plyX"])[0], rd(mon, sym["plyY"])[0]
    free_run(mon, sym["frameCounter"], 8)
    g = lambda n, k=1: rd(mon, sym[n], k)

    check("the frame transaction is still at raster 250",
          g("frameEntryLine")[0] == FRAME_IRQ_LINE, f"{g('frameEntryLine')[0]}")
    check("every page flip still happens at raster 250",
          g("flipLineMin")[0] == FRAME_IRQ_LINE == g("flipLineMax")[0],
          f"{g('flipLineMin')[0]}..{g('flipLineMax')[0]}")
    top, bot = g("topSplitMin", 2), g("botSplitMin", 2)
    check("the top aperture split still lands on 55, and on 54 at YSCROLL=7",
          tuple(top) == TOP_SPLIT, f"{top}")
    check("the bottom aperture split still lands on 248 every frame",
          bot == [BOT_SPLIT, BOT_SPLIT], f"{bot}")
    check("no aperture split was ever late", g("edgeLate")[0] == 0)
    check("the HUD phase still enters at 4 and finishes before its own fetch",
          g("hudEntryMin", 2) == [4, 4] and g("hudExitMax")[0] < 17,
          f"enter {g('hudEntryMin', 2)} exit {g('hudExitMax')[0]}")
    check("the handoff still enters at 40 and finishes before the top split",
          g("handoffEntryMin", 2) == [40, 40] and 0 < g("handoffExitMax")[0] < 53,
          f"enter {g('handoffEntryMin', 2)} exit {g('handoffExitMax')[0]}")
    check("no HUD bitmap write reached the VIC's fetch window",
          g("hudUpdWrapped")[0] == 0 and g("hudUpdStartMin")[0] >= 56)
    check("ZERO page and pointer mismatches",
          g("statPageMismatch")[0] == 0 and g("statPtrMismatch")[0] == 0)
    check("the back page was always finished before it was displayed",
          g("scrollLate")[0] == 0, f"{g('scrollLate')[0]}")
    check("no frame record was published over an unadopted one",
          g("publishSkip")[0] == 0, f"{g('publishSkip')[0]}")

    check("the player did not drift when the background reversed",
          (rd(mon, sym["plyX"])[0], rd(mon, sym["plyY"])[0]) == (px, py),
          f"({px},{py}) -> ({rd(mon, sym['plyX'])[0]},{rd(mon, sym['plyY'])[0]})")
    # $d015 is raster-dependent by design -- exFrame clears it at 250 and exHud
    # re-enables at 4 -- so it has to be read somewhere it means something.
    # Raster 243, where gameplay's composed value is live.
    mon.cmd("delete")
    b = set_bp(mon, sym["exBottom"])
    mon.cmd("x")
    d015 = rd(mon, 0xd015)[0]
    mon.cmd(f"delete {b}")
    mon.cmd("delete")
    check("the player is still enabled with no gameplay sprites",
          (d015 & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK, f"${d015:02x} at raster 243")
    # "No fixture" used to be the same statement as "logCount is zero", because
    # nothing else could put a logical sprite in the pool. Slice C's enemies can,
    # so the check now says what it always meant: no fixture is loaded, and
    # anything that IS in the pool got there through the production object pool.
    live = [i for i in range(32) if rd(mon, sym["logActive"], 32)[i]]
    types = rd(mon, sym["objType"], 16)
    check("production startup still presents no fixture",
          rd(mon, sym["fixtureMoves"])[0] == 0
          and all(i < 16 and types[i] == 1 for i in live),
          f"fixtureMoves {rd(mon, sym['fixtureMoves'])[0]}, live {live}")

    span, over, run = (g("gameSpanMax")[0], g("gameSpanOver")[0],
                       g("gameOverrun")[0])
    print(f"  ..  main-thread span: worst {span} raster lines after the frame "
          f"transaction (~{span * 63} cycles of 19656); over-255 {over}, "
          f"missed frames {run}")
    check("the main thread still finishes inside the frame it is preparing",
          run == 0 and over == 0 and span < 250, f"span {span} over {over} run {run}")
    return span


# ===========================================================================
if __name__ == "__main__":
    source_invariants()
    v = None
    try:
        v = Vice(6608, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        # Hold the stick idle so the player cannot move under the checks below.
        mon.cmd(f"> {sym['joyHold']:04x} 01")
        mon.cmd(f"> {sym['joyState']:04x} 1f")
        free_run(mon, sym["frameCounter"], 1)

        direction(mon)
        row_continuity(mon)
        flip_continuity(mon)
        engine_unchanged(mon)
    finally:
        if v:
            v.close()
    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    print("\n=== ALL PASS ===" if not fails
          else f"\n=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
    sys.exit(1 if fails else 0)
