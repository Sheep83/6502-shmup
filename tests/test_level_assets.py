#!/usr/bin/env python3
"""The level enemy sprite window, and package-local animation resolution.

    python3 tests/test_level_assets.py

WHAT THIS PROVES
----------------
* the window is aligned, inside VIC bank 0, and clears its neighbours -- the
  memory boundary the whole model rests on;
* THE RESIDENT PACKAGE CARRIES ITS OWN RESOLVED ANIMATION DATA: the bytes in
  RAM at LEVELPKG_ANIM are the bytes the built package shipped;
* every identity gets a CONTIGUOUS run of physical frames, used in full, and
  the runs are disjoint -- no identity wears another's artwork;
* VARIABLE FRAME COUNTS ARE HONOURED: the runs are not all the same length, and
  nothing assumes four;
* the artwork really is resident on the blocks the package claims;
* enemyAnimSeq is RAM RESOLVED BY levelAssetsLoad, not constants baked at
  assembly -- proved by poisoning the table and watching every entry come back;
* REPLACEMENT: writing a different package's animation table into the package
  region and reloading re-resolves EVERY entry, with no stale pointer from the
  previous package surviving, and a live enemy's published pointer follows;
* the engine survives the round trip with the production counters clean.

---------------------------------------------------------------------------
WHY THIS FILE WAS REBUILT: THE FIXED-FOUR-FRAME DESCRIPTOR MODEL IS GONE
---------------------------------------------------------------------------
It used to compose its expectations host-side out of a SHAPE and a SLOT:

    SPECIES_COUNT, ANIM_STEPS, FRAMES = 2, 8, 4
    RING_SHAPE    = [0, 1, 2, 3, 0, 1, 2, 3]
    DROPPER_SHAPE = [0, 1, 2, 3, 3, 2, 1, 0]
    return ([PTR_FIRST + ring_slot + f for f in RING_SHAPE] +
            [PTR_FIRST + dropper_slot + f for f in DROPPER_SHAPE])

Two species, four frames each, and an engine-resident descriptor saying which
slot each landed on. All three of those are retired:

* a level has THREE enemy slots, each holding any roster identity;
* an identity owns ITS OWN frame count -- this level packs 8 + 4 + 6 blocks, so
  the runs start at $b0/$b8/$bc rather than four apart;
* the SHAPE and the SLOT are composed by the exporter now and shipped as one
  window-relative block per (species, step) in LEVELPKG_ANIM. levelAssetsLoad
  adds the window base and does nothing else.

It also called `levelAssetsLoad` with `x=PKG_B` to select a second, engine-
resident "Level B" descriptor. That descriptor no longer exists and the routine
ignores X entirely: it reads the absolute LEVELPKG_ANIM out of whatever package
is resident. So the replacement proof is now done the way a real level load does
it -- by putting different bytes in the package region and reloading.

`reports/repair-stale-square-species-test.md` did the same repair for
tests/test_square_species.py and flagged this file; this is that follow-up.

---------------------------------------------------------------------------
WHAT IS DELIBERATELY NOT ASSERTED
---------------------------------------------------------------------------
WHICH IDENTITIES A LEVEL CHOOSES IS AUTHORING, and so are their frame counts.
Nothing here names Ring 3, Dropper or Space Whisk, and no run length is written
down: the resident half is checked for STRUCTURE against the package that
shipped, and every exact value the swap needs comes from a SYNTHETIC table this
file builds. That table deliberately uses three different run lengths, none of
them four, so a fixed-four assumption reappearing anywhere fails here.

The window's compile-time properties are also asserted by the assembler itself
(src/main.asm, four `.if` guards). They are re-checked here from the same
constants because a test that reads them cannot drift from them, but the build
would fail first.

One VICE launch.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     free_run, step_n, call, check, report)
import campaign_data as CD                                            # noqa: E402
import synth                                                          # noqa: E402

MAX_OBJECTS = 16
TYPE_ENEMY = 1
PORT = 6671


def _main_consts(*names):
    """`.const NAME = ...` values from src/main.asm, resolved in file order.

    The window's geometry is engine memory map and belongs to src/main.asm, so it
    is read rather than restated and this file cannot disagree with the map --
    the same reason tests/campaign_data.py reads src/levelpkg.asm. Only the plain
    arithmetic src/main.asm actually uses for these four is resolved; anything
    else is left to fail loudly rather than be guessed at.
    """
    src = (ROOT / "src" / "main.asm").read_text(encoding="utf-8")
    seen = {}
    for name in names:
        m = re.search(rf"^\s*\.const\s+{name}\s*=\s*(.+)$", src, re.M)
        if not m:
            raise SystemExit(f"{name} not found in src/main.asm")
        expr = m.group(1).split("//")[0].strip()
        expr = re.sub(r"\$([0-9a-fA-F]+)",
                      lambda g: str(int(g.group(1), 16)), expr)
        seen[name] = int(eval(expr, {"__builtins__": {}}, dict(seen)))  # noqa: S307
    return [seen[n] for n in names]


# Declared in this order because the later two are expressions over the first two.
WINDOW, WINDOW_BLOCKS, WINDOW_END, PTR_FIRST = _main_consts(
    "LEVEL_SPRITES", "LEVEL_SPRITE_BLOCKS", "LEVEL_SPRITES_END",
    "LEVEL_PTR_FIRST")

SCREEN_B = 0x2800                   # src/main.asm's second screen page
CLIP_SCRATCH = 0x3100               # the run the window must not reach
FORMER_PINNED_HOME = 0x3580         # where the Ring's art used to be nailed

ANIM_AT = CD.pkg("LEVELPKG_ANIM")
ANIM_MAX = CD.pkg("LEVELPKG_ANIM_MAX")
SLOTS = CD.C.ENEMY_SLOTS            # 3
STEPS = CD.C.ENEMY_ANIM_STEPS       # 8
POISON = 0xEE                       # never a legal window pointer

# ---------------------------------------------------------------------------
# THE SYNTHETIC PACKAGE TABLE -- the whole point of the replacement proof.
#
# THREE DIFFERENT RUN LENGTHS, NONE OF THEM FOUR, and none matching this
# level's. If a fixed-four-frame assumption ever comes back -- in the loader, in
# the exporter's emission, or in a future version of this test -- these rows
# stop resolving and the checks below say so.
#
# The shape of each row is "step modulo the run length", which is the default
# the sprite exporter uses for a new identity; the ping-pong the Dropper's
# artwork happens to use is authoring, so it is not imitated here.
# ---------------------------------------------------------------------------
SYN_RUNS = (3, 7, 5)                # frames per slot: all different, no 4


def _syn_table():
    """A well-formed LEVELPKG_ANIM in the CURRENT format: window-relative
    blocks, packed from 0 in slot order, one row of STEPS per slot."""
    out, base = [], 0
    for run in SYN_RUNS:
        out += [base + (step % run) for step in range(STEPS)]
        base += run
    return out


SYN_TABLE = _syn_table()
SYN_BASES, _b = [], 0
for _run in SYN_RUNS:
    SYN_BASES.append(_b)
    _b += _run
SYN_BLOCKS = _b


def rows_of(table):
    return [table[k * STEPS:(k + 1) * STEPS] for k in range(SLOTS)]


def pkg_anim_from_prg():
    """LEVELPKG_ANIM out of the package the engine was built to load.

    The built bytes, not the generated source: LVL_ANIM is emitted as a chained
    `.eval LVL_ANIM.add(0).add(1)...`, which the editor's asm_decl reader
    rejects, and teaching a test-only parser more assembly syntax to recover an
    inspection the package itself already answers would be the wrong trade. The
    same technique tests/test_movement_pool.py uses for the movement pool.
    """
    prg = (ROOT / "build" / "level1.prg").read_bytes()
    base = prg[0] | (prg[1] << 8)
    return list(prg[2 + ANIM_AT - base: 2 + ANIM_AT - base + ANIM_MAX])


def structure(label, table, budget=None):
    """The properties a well-formed animation table must have, whatever a level
    chose. Returns the per-slot block sets."""
    rows = rows_of(table)
    sets = [set(r) for r in rows]
    for k, r in enumerate(rows):
        print(f"  info {label} slot {k}: {r}  ({len(sets[k])} frames)")

    overlap = [(a, b, sorted(sets[a] & sets[b]))
               for a in range(SLOTS) for b in range(a + 1, SLOTS)
               if sets[a] & sets[b]]
    check(f"{label}: the slots' frame runs are DISJOINT -- no identity wears "
          f"another's artwork",
          not overlap, str(overlap) if overlap else
          "; ".join(f"slot {k}: {len(s)}" for k, s in enumerate(sets)))

    bad = [(k, sorted(s)) for k, s in enumerate(sets)
           if max(s) - min(s) + 1 != len(s)]
    check(f"{label}: each run is CONTIGUOUS and used in full -- an identity owns "
          f"exactly its artwork's frame count",
          not bad, str(bad) if bad else
          "; ".join(f"slot {k}: {min(s)}..{max(s)}" for k, s in enumerate(sets)))

    at, packing = 0, []
    for k, s in enumerate(sets):
        packing.append((k, min(s) == at, min(s), at))
        at = min(s) + len(s)
    check(f"{label}: the runs pack from block 0 in slot order",
          all(ok for _k, ok, _g, _w in packing),
          "; ".join(f"slot {k}: at {g}, expected {w}"
                    for k, ok, g, w in packing if not ok)
          or f"{at} blocks used")
    if budget is not None:
        check(f"{label}: the whole window fits the engine's sprite budget",
              at <= budget, f"{at} blocks of {budget}")

    # VARIABLE FRAME COUNTS, ASSERTED AS SUCH. This is the check that fails if
    # anything goes back to four-frames-for-everyone.
    lengths = [len(s) for s in sets]
    check(f"{label}: the runs are NOT all the same length -- variable frame "
          f"counts are real",
          len(set(lengths)) > 1, f"frames per slot {lengths}")
    return sets


def main():
    print("=== the level enemy sprite window ===")
    if not (PRG.is_file() and SYM.is_file()):
        check("build artefacts exist", False)
        return report(__name__)
    sym = symbols(SYM)

    # --- 1. the window as a memory boundary ---------------------------------
    # src/main.asm asserts all four of these at assembly time; they are here so
    # a reader of this file sees the boundary the rest of it depends on.
    check("the window is 64-byte aligned", WINDOW % 64 == 0, f"${WINDOW:04x}")
    check("the window is inside VIC bank 0", WINDOW_END <= 0x4000,
          f"${WINDOW:04x}-${WINDOW_END - 1:04x}")
    check("the window clears screen page B below it and the clip scratch above",
          WINDOW >= SCREEN_B + 0x400 and WINDOW_END <= CLIP_SCRATCH,
          f"${WINDOW:04x}..${WINDOW_END:04x} between ${SCREEN_B + 0x400:04x} "
          f"and ${CLIP_SCRATCH:04x}")
    check("every block in the window has a representable sprite pointer",
          PTR_FIRST + WINDOW_BLOCKS <= 256,
          f"${PTR_FIRST:02x}..${PTR_FIRST + WINDOW_BLOCKS - 1:02x}")
    check("the synthetic replacement table fits the window too",
          SYN_BLOCKS <= WINDOW_BLOCKS,
          f"{SYN_BLOCKS} blocks of {WINDOW_BLOCKS}, runs {SYN_RUNS}")

    v = None
    try:
        # boot="exact" SO THE MACHINE IS DETERMINISTICALLY IN PLAYING, near the
        # start of the stage. The old file booted with warp and no exact arrival,
        # which is why its live-play check depended on whether the window it
        # happened to sample contained any enemies at all -- it reported an empty
        # set. Section 5 installs its own wave rather than hoping for one.
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        mon.cmd("delete")

        seq = sym["enemyAnimSeq"]
        check("the animation table lives outside VIC bank 0",
              seq >= 0x4000, f"${seq:04x}")

        # --- 2. THE RESIDENT PACKAGE CARRIES ITS OWN ANIMATION DATA ----------
        live_pkg = list(rd(mon, ANIM_AT, ANIM_MAX))
        built_pkg = pkg_anim_from_prg()
        check("the package's animation table in RAM is the one the build "
              "shipped",
              live_pkg == built_pkg,
              f"{sum(1 for a, b in zip(live_pkg, built_pkg) if a != b)} "
              f"mismatches of {ANIM_MAX}")
        check(f"it is one row of {STEPS} entries per enemy slot",
              ANIM_MAX == SLOTS * STEPS, f"{ANIM_MAX} entries")
        sets = structure("resident", live_pkg, budget=WINDOW_BLOCKS)

        # ...AND THE ARTWORK IS REALLY THERE. Checked against the bytes the VIC
        # will fetch, which is what would catch an art segment and the package's
        # own claims drifting apart.
        empty = []
        for k, s in enumerate(sets):
            for blk in sorted(s):
                if not any(rd(mon, WINDOW + blk * 64, 63)):
                    empty.append((k, blk))
        check("every block the package claims holds real artwork",
              not empty, str(empty) if empty else
              f"{sum(len(s) for s in sets)} blocks, all non-blank")
        distinct = {bytes(rd(mon, WINDOW + min(s) * 64, 63)) for s in sets}
        check("...and the slots' first frames are genuinely different drawings",
              len(distinct) == SLOTS, f"{len(distinct)} distinct of {SLOTS}")

        # THE FORMER PINNED HOME IS STILL VACATED. $3580 was one species'
        # permanent address before the window existed; the question is whether
        # any slot's artwork is resident there, not what occupies the run now
        # (src/boss_art.asm does).
        resurrected = [k for k, s in enumerate(sets)
                       if rd(mon, FORMER_PINNED_HOME, 63)
                       == rd(mon, WINDOW + min(s) * 64, 63)]
        check("no slot's artwork is resident at the former pinned home",
              not resurrected,
              f"slot(s) {resurrected} found at ${FORMER_PINNED_HOME:04x}")

        # --- 3. enemyAnimSeq IS RESOLVED, NOT ASSEMBLED ----------------------
        # POISON FIRST. "The table holds the right values" is also true of a
        # table of assembled constants; that EVERY entry is rewritten on demand
        # is what makes it RAM built by the loader.
        for i in range(ANIM_MAX):
            poke(mon, seq + i, POISON)
        check("the table was poisoned before the loader ran",
              set(rd(mon, seq, ANIM_MAX)) == {POISON})
        call(mon, sym, "levelAssetsLoad")       # takes no argument any more
        resident = list(rd(mon, seq, ANIM_MAX))
        check("levelAssetsLoad rewrote EVERY entry -- no poison survived",
              POISON not in resident,
              f"{resident.count(POISON)} entries still poisoned")
        want = [b + PTR_FIRST for b in live_pkg]
        check("every pointer is the package's own block plus the window base",
              resident == want,
              f"{sum(1 for a, b in zip(resident, want) if a != b)} mismatches; "
              f"base ${PTR_FIRST:02x}")
        check("every resolved pointer addresses a block inside the window",
              all(PTR_FIRST <= b < PTR_FIRST + WINDOW_BLOCKS for b in resident),
              f"${min(resident):02x}..${max(resident):02x}")

        # --- 4. THE REPLACEMENT PROOF, IN THE CURRENT FORMAT -----------------
        # A REAL LEVEL LOAD PUTS NEW BYTES IN THE PACKAGE REGION and calls
        # levelAssetsLoad. That is exactly what happens here: the synthetic
        # table is written where LEVELPKG_ANIM lives, with recognisable artwork
        # planted on the blocks it names, and the loader is asked to resolve it.
        for k, base in enumerate(SYN_BASES):
            for f in range(SYN_RUNS[k]):
                poke(mon, WINDOW + (base + f) * 64, (0x5A + k * 0x20) ^ f)
        for i, b in enumerate(SYN_TABLE):
            poke(mon, ANIM_AT + i, b)
        check("a synthetic package table is resident, in the current format",
              list(rd(mon, ANIM_AT, ANIM_MAX)) == SYN_TABLE,
              f"runs {SYN_RUNS}, {SYN_BLOCKS} blocks")
        structure("synthetic", SYN_TABLE, budget=WINDOW_BLOCKS)

        for i in range(ANIM_MAX):               # poison again: prove a full
            poke(mon, seq + i, POISON)          # rebuild, not a partial patch
        call(mon, sym, "levelAssetsLoad")
        swapped = list(rd(mon, seq, ANIM_MAX))
        want_syn = [b + PTR_FIRST for b in SYN_TABLE]
        check("reloading re-resolves EVERY entry to the new package's blocks",
              swapped == want_syn,
              f"{sum(1 for a, b in zip(swapped, want_syn) if a != b)} mismatches")
        check("...with no poison left, so nothing was skipped",
              POISON not in swapped)
        # NO STALE POINTER SURVIVES. The two tables share some pointers by
        # construction (both pack from the window base), so the claim is that
        # every entry now matches the NEW package -- which the check above
        # makes -- and that the tables genuinely differ.
        check("...and the table really did change",
              swapped != resident,
              f"{sum(1 for a, b in zip(swapped, resident) if a != b)} of "
              f"{ANIM_MAX} entries differ")
        check("the new pointers address the bytes planted on those blocks",
              all(rd1(mon, (PTR_FIRST + b) * 64) == ((0x5A + k * 0x20) ^ 0)
                  for k, b in enumerate(SYN_BASES)),
              f"slot bases {SYN_BASES}")
        # VARIABLE COUNTS SURVIVED THE ROUND TRIP, per slot.
        got_runs = tuple(len({p - PTR_FIRST for p in swapped[k * STEPS:(k + 1) * STEPS]})
                         for k in range(SLOTS))
        check("each slot resolved exactly its own frame count, all different",
              got_runs == SYN_RUNS, f"{got_runs} wanted {SYN_RUNS}")

        # --- 5. GAMEPLAY FOLLOWS WITHOUT KNOWING -----------------------------
        # enemyAnimPtr is unchanged code; run the real loop and watch what a live
        # enemy publishes. Every pointer it emits must now come out of the newly
        # loaded rows.
        #
        # THE ENEMIES ARE INSTALLED, NOT WAITED FOR. This check used to sample 64
        # frames of whatever the stage happened to be doing and assert the set was
        # non-empty; it reported `[]`, which is the honest "no enemy was alive"
        # signal rather than a finding. A synthetic wave at an early row makes the
        # population certain, and it is installed AFTER the table swap so every
        # enemy it sends is born under the new rows.
        pkg = synth.Package(mon, sym)
        prog = pkg.straight_then_exit(3, 4)
        d = pkg.install_definition(count=4, interval=12, start_x=90, start_y=50,
                                   x_step=30, y_step=0, heading=8, program=prog)
        pkg.only_trigger(row=8, definition=d, species=synth.SLOT_ROW[0],
                         fire=0, colour=5, speed=CD.C.TRIG_SPEED_1X)

        # GATED ON logActive, AND THAT MATTERS: logPtr keeps its last value after
        # an object dies, so an unfiltered scan reports pointers from enemies that
        # were already dead when the table changed. The first sample is dropped
        # for a related reason -- the breakpoint is at the top of gameFrame, so on
        # the first frame an enemy still carries what its last enemyTick wrote.
        bp = set_bp(mon, sym["gameFrame"])
        seen = step_n(mon, sym["frameCounter"], 240, lambda: (
            rd(mon, sym["logActive"], MAX_OBJECTS),
            rd(mon, sym["objType"], MAX_OBJECTS),
            rd(mon, sym["logPtr"], MAX_OBJECTS)))
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")
        ptrs = {p for act, typ, pp in seen[1:]
                for a, t, p in zip(act, typ, pp)
                if a and t == TYPE_ENEMY
                and PTR_FIRST <= p < PTR_FIRST + WINDOW_BLOCKS}
        check("live enemies published window pointers during real play",
              bool(ptrs), f"{sorted(hex(p) for p in ptrs)}")
        check("...and every one comes from the NEWLY LOADED package's rows",
              ptrs <= set(want_syn),
              f"{sorted(hex(p) for p in ptrs)} vs synthetic "
              f"{sorted({hex(p) for p in want_syn})}")
        # ...AND OUT OF THE ROW FOR THE SLOT THEY ACTUALLY ARE. The wave sends
        # slot 0, so nothing may draw from slot 1's or slot 2's run.
        own = {PTR_FIRST + b for b in SYN_TABLE[0:STEPS]}
        check("...specifically from the row of the slot the wave sends",
              ptrs <= own,
              f"{sorted(hex(p) for p in ptrs)} vs slot 0 "
              f"{sorted(hex(p) for p in own)}")

        # --- 6. back to the resident package ---------------------------------
        for i, b in enumerate(live_pkg):
            poke(mon, ANIM_AT + i, b)
        call(mon, sym, "levelAssetsLoad")
        check("restoring the package's own table resolves it exactly again",
              list(rd(mon, seq, ANIM_MAX)) == want,
              "the resident table is back")

        # --- 7. the engine is unharmed ---------------------------------------
        free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        for name in ("gameOverrun", "statPageMismatch", "statPtrMismatch"):
            val = rd1(mon, sym[name])
            check(f"{name} is zero after the round trip", val == 0, str(val))
        # schedBuildDefer IS REPORTED, NOT ASSERTED, and that is the repository's
        # own classification of it rather than a tolerance invented here:
        # tests/run_smoke.py lists it in REPORTED as "a documented bounded cost
        # ('cannot starve'), not a fault", and src/renderer.asm:377 describes the
        # race state it counts. This file steps several hundred frames through the
        # monitor, which is exactly the condition that defers a build, and the old
        # version duly failed on a value of 1 while the engine was behaving as
        # designed.
        print(f"  info schedBuildDefer {rd1(mon, sym['schedBuildDefer'])} "
              f"(measured, not asserted -- a bounded cost; see "
              f"tests/run_smoke.py REPORTED)")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
