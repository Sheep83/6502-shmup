#!/usr/bin/env python3
"""The engine's THIRD enemy slot is a real ordinary species, proved on the machine.

    python3 tests/test_square_species.py

WHAT THIS FILE IS FOR. The engine has three enemy slots. One of them carries the
token-dropping behaviour and is special everywhere; the other two are ordinary.
This proves the THIRD slot is genuinely one of the ordinary ones -- that it
resolves its own artwork, spawns, flies, crowds and despawns exactly as the first
does, and that adding it took nothing away from the Dropper's rules.

    * does the level's animation table resolve a third row, out of the third
      slot's OWN artwork, with nothing borrowed from the other two?
    * does a wave whose species byte is the third slot row actually spawn?
    * do the spawned objects carry that species for life?
    * can several be alive at once, the way the first slot's can and the
      Dropper deliberately cannot?
    * does the one-live-Dropper rule leave them alone?
    * do they move, and do they eventually despawn?
    * and do the first slot and the Dropper still behave exactly as they did?

---------------------------------------------------------------------------
WHY THIS FILE WAS REWRITTEN: enemyAnimShape AND levelAssetDescs ARE GONE
---------------------------------------------------------------------------
It used to read two symbols that no longer exist, and it died on the first of
them with `KeyError: 'enemyAnimShape'` before reaching a single check.

The OLD model composed a sprite pointer at level-load time out of two separately
owned tables -- src/level_assets.asm still describes it:

    the SHAPE   enemyAnimShape  -- frame indices; resident species behaviour
    the SLOT    levelAssetDescs -- where this level put that species' frames
    pointer = window base + slot + frame index

Both halves have since moved OUT of the engine and INTO the level package. The
exporter (tools/sprite_export/import_spd.py) now composes slot and shape itself
and emits one window-relative BLOCK per (species, step) as LVL_ANIM, which the
package carries at LEVELPKG_ANIM. levelAssetsLoad's whole remaining job is:

    pointer = LEVELPKG_ANIM[i] + LEVEL_PTR_FIRST

-- "no species division, no descriptor row, no frame count", as it now says. So
the two symbols were not renamed; the composition they represented stopped
happening at run time at all.

The old expectations were stale in a second way, and it is the more interesting
one. They asserted the rows were built from $b0/$b4/$b8 -- three species four
blocks apart -- because every species wore exactly four frames. A slot now holds
any roster identity and an identity owns its own frame count, so this level packs
8 + 4 + 6 blocks and the rows start at $b0/$b8/$bc. Renaming a symbol would not
have caught that; the assertion had to be rebuilt from what the contract now is.

---------------------------------------------------------------------------
WHAT IS ASSERTED, AND WHAT IS DELIBERATELY NOT
---------------------------------------------------------------------------
WHICH IDENTITY SITS IN THE THIRD SLOT IS AUTHORING. Level 1 holds Ring 3,
Dropper and Space Whisk today; it held a Ring, a Dropper and a Square when this
file was written, and the frame counts went 4/4/4 -> 8/4/6 with it. None of that
is an engine property, so none of it is asserted. What is asserted is the
STRUCTURE the runtime depends on, whatever a level chooses:

    every pointer is LEVELPKG_ANIM's byte plus the window base -- the engine's
    entire remaining job, checked against the package that shipped;
    every pointer lies inside the enemy sprite window;
    the three rows use DISJOINT blocks, so no slot wears another's art;
    each row's blocks form a contiguous run it uses in full -- a species owns
    exactly its artwork's frame count;
    the runs pack from the start of the window in slot order.

THE ENCOUNTERS ARE SYNTHETIC. Exact member counts and exact species are needed,
and neither is the campaign's business: tests/synth.py installs them into the
spare room the package reserves, in RAM only. The file used to poke the authored
species column and then read tools/level_editor/levels/level1/level.v6.json to
work out how many triggers could become due inside its frame budget -- a
double coupling to mutable content that is simply gone now.

Three short VICE launches.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, set_bp,  # noqa: E402
                     step_n, check, report, LAUNCHED_PIDS)
import campaign_data as CD                                      # noqa: E402
import synth                                                    # noqa: E402

sym = symbols(SYM)

MAX_OBJECTS = 16
TYPE_ENEMY = 1
PORT = 6581

# THE ENGINE'S THREE SLOT ROWS, not three legacy species names. A species value
# IS its row offset in the animation table, so slot k is k * ENEMY_ANIM_STEPS.
SLOT_ROW = synth.SLOT_ROW                       # (0, 8, 16)
ENEMY_ANIM_STEPS = CD.C.ENEMY_ANIM_STEPS        # 8
SLOTS = CD.C.ENEMY_SLOTS                        # 3
THIRD = SLOT_ROW[2]                             # the slot this file is about
FIRST = SLOT_ROW[0]

# src/main.asm: the enemy sprite window and the pointer it starts at.
LEVEL_SPRITE_BLOCKS = CD.C.LEVEL_SPRITE_BLOCKS  # 20, from the sprite exporter
LEVEL_PTR_FIRST = 0x2C00 // 64                  # $b0; LEVEL_SPRITES / 64

# The synthetic encounters. Early rows, so a short window reaches them.
SYN_COUNT, SYN_INTERVAL = 4, 14
SYN_ROWS = (8, 40, 72)
WATCH = 700


def _pkg_anim():
    """LEVELPKG_ANIM out of the package the engine was built to load.

    Read from build/level1.prg rather than parsed out of the generated source:
    LVL_ANIM is emitted as a chained `.eval LVL_ANIM.add(0).add(1)...`, which the
    editor's declaration reader does not accept, and the built bytes are the more
    authoritative artefact anyway -- they are what the engine actually loads.
    """
    prg = (ROOT / "build" / "level1.prg").read_bytes()
    base = prg[0] | (prg[1] << 8)
    at, n = CD.pkg("LEVELPKG_ANIM"), CD.pkg("LEVELPKG_ANIM_MAX")
    return list(prg[2 + at - base: 2 + at - base + n])


OBJ_BASE = sym["enySpecies"]
OBJ_SPAN = sym["objType"] + MAX_OBJECTS - OBJ_BASE


def sample(mon):
    blk = rd(mon, OBJ_BASE, OBJ_SPAN)
    wv = rd(mon, sym["wvStarted"], 4)
    ys = rd(mon, sym["logY"], MAX_OBJECTS)
    ptr = rd(mon, sym["logPtr"], MAX_OBJECTS)

    def field(name):
        o = sym[name] - OBJ_BASE
        return blk[o:o + MAX_OBJECTS]

    species, active, typ = field("enySpecies"), field("logActive"), field("objType")
    live = [(s, species[s]) for s in range(MAX_OBJECTS)
            if active[s] and typ[s] == TYPE_ENEMY]
    return {"live": live,
            "ys": {s: ys[s] for s, _ in live},
            "ptrs": {s: (ptr[s], species[s]) for s, _ in live},
            "started": wv[0],
            "spawned": wv[sym["wvSpawned"] - sym["wvStarted"]]}


def count_of(frame, row):
    return sum(1 for _, sp in frame["live"] if sp == row)


def fly(schedule, label, watch=WATCH):
    """Install a SYNTHETIC schedule -- [(row, species), ...] -- and watch it fly.

    One definition, shared by every trigger: this file is about the species
    column, so everything else is held constant on purpose.
    """
    v = None
    try:
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        pkg = synth.Package(mon, sym)
        prog = pkg.straight_then_exit(3, 4)     # a gentle diagonal, any path
        d = pkg.install_definition(count=SYN_COUNT, interval=SYN_INTERVAL,
                                   start_x=80, start_y=50, x_step=30, y_step=0,
                                   heading=8, program=prog)
        for i, (row, species) in enumerate(schedule):
            pkg.write_trigger(i, row=row, definition=d, species=species,
                              fire=0, side=0, colour=5, fire_mode=0,
                              speed=CD.C.TRIG_SPEED_1X)
        pkg.set_trigger_count(len(schedule))
        pkg.open_the_approach()
        pkg.rewind_cursor()

        got = list(rd(mon, sym["waveTrigSpecies"], len(schedule)))
        check(f"{label}: the species column reads back as installed",
              got == [sp for _r, sp in schedule],
              f"{got} vs {[sp for _r, sp in schedule]}")

        anim = list(rd(mon, sym["enemyAnimSeq"], SLOTS * ENEMY_ANIM_STEPS))
        # THE TOKEN-DROPPING SLOT, from the engine's own byte. It is package data
        # copied into lvlDropRow at level load, so it is read rather than assumed
        # to be the middle slot -- and read here, inside a session that is
        # already open, rather than costing a VICE launch of its own.
        drop_row = rd1(mon, sym["lvlDropRow"])
        set_bp(mon, sym["gameFrame"])
        frames = step_n(mon, sym["frameCounter"], watch, lambda: sample(mon))
    finally:
        if v:
            v.close()
    return frames, anim, drop_row


def main():
    # =====================================================================
    # 1. THE ANIMATION TABLE, THROUGH THE CURRENT PACKAGE-LOCAL MODEL
    # =====================================================================
    print("\n=== the resolved animation table ===")
    frames, anim, drop_row = fly([(SYN_ROWS[0], THIRD)], "all third-slot")
    pkg_anim = _pkg_anim()

    check(f"the table is one row of {ENEMY_ANIM_STEPS} pointers per enemy slot",
          len(anim) == SLOTS * ENEMY_ANIM_STEPS == len(pkg_anim),
          f"{len(anim)} entries in RAM, {len(pkg_anim)} in the package")

    # THE ENGINE'S WHOLE REMAINING JOB, checked against the package that shipped.
    # levelAssetsLoad adds the window base to every package byte and does nothing
    # else; if it ever did more, this is the check that would say so.
    want = [b + LEVEL_PTR_FIRST for b in pkg_anim]
    check("every pointer is the package's own block plus the window base -- the "
          "whole of levelAssetsLoad's arithmetic",
          anim == want,
          f"{sum(1 for a, b in zip(anim, want) if a != b)} mismatches; "
          f"base ${LEVEL_PTR_FIRST:02x}")

    lo, hi = LEVEL_PTR_FIRST, LEVEL_PTR_FIRST + LEVEL_SPRITE_BLOCKS - 1
    check("every pointer addresses a block inside the enemy sprite window",
          all(lo <= p <= hi for p in anim),
          f"pointers ${min(anim):02x}..${max(anim):02x}, window "
          f"${lo:02x}..${hi:02x}")

    rows = [anim[k * ENEMY_ANIM_STEPS:(k + 1) * ENEMY_ANIM_STEPS]
            for k in range(SLOTS)]
    sets = [set(r) for r in rows]
    for k, r in enumerate(rows):
        print(f"  info slot {k} (species row {SLOT_ROW[k]}): "
              f"{[hex(p) for p in r]}")

    # NO SLOT WEARS ANOTHER'S ART. This is the claim the old "the Ring's row is
    # unchanged" / "the Dropper's row is unchanged" pair was really making, and
    # it holds for any identities and any frame counts.
    overlap = [(a, b, sorted(sets[a] & sets[b]))
               for a in range(SLOTS) for b in range(a + 1, SLOTS)
               if sets[a] & sets[b]]
    check("the slots' rows are DISJOINT: no slot borrows another's artwork",
          not overlap, str(overlap) if overlap else
          "; ".join(f"slot {k}: {len(s)} blocks" for k, s in enumerate(sets)))

    # A SPECIES OWNS EXACTLY ITS ARTWORK'S FRAME COUNT -- a contiguous run, and
    # it uses all of it. An identity with six frames names six different blocks.
    bad_run = []
    for k, s in enumerate(sets):
        if max(s) - min(s) + 1 != len(s):
            bad_run.append((k, sorted(s)))
    check("each slot's blocks form a CONTIGUOUS run, used in full",
          not bad_run, str(bad_run) if bad_run else
          "; ".join(f"slot {k}: ${min(s):02x}..${max(s):02x} ({len(s)})"
                    for k, s in enumerate(sets)))

    # ...AND THE RUNS PACK FROM THE START OF THE WINDOW, IN SLOT ORDER. This is
    # the successor to "Ring 0, Dropper 4, Square 8": the same claim, with the
    # step sizes coming from the artwork rather than from a fixed four.
    at, packing = LEVEL_PTR_FIRST, []
    for k, s in enumerate(sets):
        packing.append((k, min(s) == at, min(s), at))
        at = min(s) + len(s)
    check("the runs pack contiguously from the window base, in slot order",
          all(ok for _k, ok, _g, _w in packing),
          "; ".join(f"slot {k}: at ${g:02x}, expected ${w:02x}"
                    for k, ok, g, w in packing if not ok)
          or "; ".join(f"slot {k} at ${g:02x}" for k, _o, g, _w in packing))
    check("...and the whole window fits the engine's sprite budget",
          at - LEVEL_PTR_FIRST <= LEVEL_SPRITE_BLOCKS,
          f"{at - LEVEL_PTR_FIRST} blocks of {LEVEL_SPRITE_BLOCKS}")

    # THE THIRD SLOT IS AN ORDINARY ONE. Which slot drops the token is package
    # data; what matters here is that it is not this one.
    check("the third slot is NOT the token-dropping slot: it is an ordinary "
          "species",
          THIRD != drop_row, f"third slot row {THIRD}, drop row {drop_row}")

    # =====================================================================
    # 2. THE THIRD SLOT'S SPECIES FLIES LIKE AN ORDINARY ENEMY
    # =====================================================================
    print("\n=== a wave of the third slot's species ===")
    peak = max(count_of(f, THIRD) for f in frames)
    drops = max(count_of(f, SLOT_ROW[1]) for f in frames)
    spawned = max(f["spawned"] for f in frames)
    started = max(f["started"] for f in frames)
    check("its trigger started", started >= 1, f"{started} started")
    check("it actually spawned", peak > 0, f"peak {peak}")
    check("SEVERAL are alive at once, as the first slot's may be",
          peak > 1, f"peak {peak}")
    check("not one object was ever committed as a Dropper", drops == 0,
          f"peak {drops}")
    # THE EXTRA TEXT PRINTS ON SUCCESS TOO, so it states what was seen rather
    # than what a failure would mean -- inherited phrasing here read as
    # "ok ... -- a live enemy carried another species", which is a contradiction.
    others = sorted({sp for f in frames for _, sp in f["live"] if sp != THIRD})
    check("every live enemy carried the third slot's species for its whole life",
          not others,
          f"other species seen: {others}" if others
          else f"species row {THIRD} only, over {len(frames)} frames")

    # ITS SPRITE POINTER COMES OUT OF ITS OWN ROW, every frame it is alive. This
    # is the link between the table above and what the runtime actually draws --
    # the reason the table is worth checking at all.
    own = sets[2]
    stray = {(s, hex(p)) for f in frames for s, (p, sp) in f["ptrs"].items()
             if sp == THIRD and p not in own}
    check("every one of them draws from its OWN animation row, every frame",
          not stray, str(sorted(stray)[:4]) if stray else
          f"all pointers inside ${min(own):02x}..${max(own):02x}")

    moved = any(slot in b["ys"] and b["ys"][slot] != y
                for a, b in zip(frames, frames[1:])
                for slot, y in a["ys"].items())
    check("they move under the ordinary movement system", moved)
    check("they despawn rather than accumulating",
          frames[-1]["live"] == [] or spawned > peak,
          f"peak {peak}, spawned {spawned}, final {len(frames[-1]['live'])}")
    check("the pool never overflowed",
          all(len(f["live"]) <= MAX_OBJECTS for f in frames))

    # =====================================================================
    # 3. THE FIRST SLOT AND THE DROPPER ARE UNAFFECTED
    # =====================================================================
    print("\n=== the first slot and the Dropper, beside it ===")
    frames2, _a2, _d2 = fly([(SYN_ROWS[0], FIRST), (SYN_ROWS[1], drop_row),
                      (SYN_ROWS[2], FIRST)], "first slot and Dropper")
    check("the first slot's species still spawns",
          max(count_of(f, FIRST) for f in frames2) > 0)
    check("the Dropper still spawns",
          max(count_of(f, drop_row) for f in frames2) > 0)
    check("NEVER more than one live Dropper -- the rule still holds",
          max(count_of(f, drop_row) for f in frames2) <= 1,
          f"peak {max(count_of(f, drop_row) for f in frames2)}")
    check("no third-slot enemy appeared from nowhere",
          max(count_of(f, THIRD) for f in frames2) == 0)

    frames3, _a3, _d3 = fly([(SYN_ROWS[0], THIRD), (SYN_ROWS[1], drop_row),
                      (SYN_ROWS[2], FIRST)], "all three slots")
    peaks = {k: max(count_of(f, SLOT_ROW[k]) for f in frames3)
             for k in range(SLOTS)}
    check("all three enemy slots appear in one run",
          all(v > 0 for v in peaks.values()),
          "; ".join(f"slot {k} peak {v}" for k, v in peaks.items()))
    check("...and the one-live-Dropper rule is unaffected by the others",
          max(count_of(f, drop_row) for f in frames3) <= 1,
          f"peak {max(count_of(f, drop_row) for f in frames3)}")

    print(f"\n  launched and reaped: {LAUNCHED_PIDS}")
    return report(__name__)



if __name__ == "__main__":
    sys.exit(main())
