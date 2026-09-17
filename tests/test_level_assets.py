#!/usr/bin/env python3
"""The level enemy sprite window and its pointer indirection.

What this proves
----------------
* the window is aligned, inside VIC bank 0, and overlaps nothing else the VIC
  reads -- the memory boundary the whole model rests on;
* level 1's compiled-in artwork really landed on the slots its package claims,
  checked against the bytes in the PRG rather than against the constants that
  placed them;
* the Ring's former pinned home at $3580 is genuinely vacated (the run now
  holds the end-of-level boss, which is not the Ring);
* at boot, enemyAnimSeq holds POINTERS resolved from level 1's descriptor --
  the table is RAM built by levelAssetsLoad, not constants baked at assembly;
* REPLACEMENT: loading the dummy Level B package re-resolves every entry to
  different window slots, in the opposite species order, with no gameplay code
  aware that anything moved -- and a live enemy's published sprite pointer
  follows into the new slots;
* the engine survives the round trip and keeps animating on the resident
  package, with the production health counters clean.

What this does NOT prove
------------------------
Anything about a loader: there is no disk I/O here and none in the engine. The
Level B package deliberately carries no artwork -- the contract under test is
"where do pointers come from", not "what do the blocks contain", so the test
writes its own recognisable bytes into Level B's slots.

Proportionality: this is a memory-ownership change, so the checks are memory
boundaries, pointer resolution and one replacement round trip, plus a short
live-play sanity pass. One VICE launch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, step_n, call, check, report)

# --- the contract, restated independently of the assembler ------------------
WINDOW       = 0x2c00
WINDOW_BLOCKS = 20
WINDOW_END   = WINDOW + WINDOW_BLOCKS * 64          # $3100
PTR_FIRST    = WINDOW // 64                         # $b0
SCREEN_B     = 0x2800
CLIP_SCRATCH = 0x3100
HUD_END      = 0x3580
RING_OLD_HOME = 0x3580                              # vacated by this change

SPECIES_COUNT, ANIM_STEPS, FRAMES = 2, 8, 4
PKG_1, PKG_B = 0, 1

L1_RING, L1_DROPPER = 0, 4                          # level1/stage_enemies.asm
LB_RING, LB_DROPPER = 12, 8                         # level_assets.asm

RING_SHAPE    = [0, 1, 2, 3, 0, 1, 2, 3]
DROPPER_SHAPE = [0, 1, 2, 3, 3, 2, 1, 0]


def expected_table(ring_slot, dropper_slot):
    """What levelAssetsLoad must produce: window base + slot + frame index."""
    return ([PTR_FIRST + ring_slot + f for f in RING_SHAPE] +
            [PTR_FIRST + dropper_slot + f for f in DROPPER_SHAPE])


def main():
    print("=== level enemy sprite window ===")
    if not (PRG.is_file() and SYM.is_file()):
        check("build artefacts exist", False)
        return report(__name__)
    sym = symbols(SYM)

    # --- 1. the window as a memory boundary ---------------------------------
    check("the window is 64-byte aligned", WINDOW % 64 == 0, f"${WINDOW:04x}")
    check("the window is inside VIC bank 0", WINDOW_END <= 0x4000,
          f"${WINDOW:04x}-${WINDOW_END - 1:04x}")
    check("the window clears screen page B below it", WINDOW >= SCREEN_B + 0x400)
    check("the window clears the clip scratch above it", WINDOW_END <= CLIP_SCRATCH,
          f"ends ${WINDOW_END:04x}, scratch at ${CLIP_SCRATCH:04x}")
    check("every block in the window has a representable sprite pointer",
          PTR_FIRST + WINDOW_BLOCKS <= 256,
          f"${PTR_FIRST:02x}..${PTR_FIRST + WINDOW_BLOCKS - 1:02x}")
    # Both packages must fit. LEVEL B IS CHECKED TOO -- a window sized only for
    # the resident level would fail the first time a package used a later slot.
    for name, slots in (("level 1", (L1_RING, L1_DROPPER)),
                        ("level B", (LB_RING, LB_DROPPER))):
        check(f"{name}'s slots hold whole species inside the window",
              all(s + FRAMES <= WINDOW_BLOCKS for s in slots), f"{slots}")
        a, b = sorted(slots)
        check(f"{name}'s two species do not overlap each other",
              a + FRAMES <= b, f"{slots}")

    v = None
    try:
        v = Vice(6671, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # --- 2. level 1's artwork is where its package says ------------------
        # Checked against the BYTES the VIC will fetch, not against the
        # constants that placed them: this is what would catch an art segment
        # and a descriptor drifting apart.
        ring = rd(mon, WINDOW + L1_RING * 64, FRAMES * 64)
        drop = rd(mon, WINDOW + L1_DROPPER * 64, FRAMES * 64)
        check("level 1's Ring frames are resident on its claimed slot",
              all(any(ring[f * 64:f * 64 + 63]) for f in range(FRAMES)),
              f"slot {L1_RING} (${WINDOW + L1_RING * 64:04x}), lit bytes "
              f"{[sum(1 for b in ring[f*64:f*64+63] if b) for f in range(FRAMES)]}")
        check("level 1's Dropper frames are resident on its claimed slot",
              all(any(drop[f * 64:f * 64 + 63]) for f in range(FRAMES)),
              f"slot {L1_DROPPER} (${WINDOW + L1_DROPPER * 64:04x}), lit bytes "
              f"{[sum(1 for b in drop[f*64:f*64+63] if b) for f in range(FRAMES)]}")
        check("the two species' blocks really are distinct artwork",
              ring[:FRAMES * 64] != drop[:FRAMES * 64])

        # THE OLD PINNED HOME IS VACATED. $3580 was the Ring's permanent
        # address; if anything still assembled there the window would not be
        # the single source of enemy art it claims to be.
        # THE POINT OF THIS CHECK IS THE RING, NOT THE ADDRESS. It was written
        # as "is $3580 empty" because nothing had claimed the run yet; the
        # end-of-level boss now lives there (src/boss_art.asm), which does not
        # resurrect the Ring's old pinned home in the slightest. So it asks the
        # question it always meant: the Ring's artwork is NOT resident there.
        old = rd(mon, RING_OLD_HOME, FRAMES * 64)
        ring_now = rd(mon, WINDOW + L1_RING * 64, FRAMES * 64)
        check("the Ring's artwork is not resident at its former pinned home",
              old != ring_now,
              "the bytes at $3580 are the Ring's own frames")

        # --- 3. the resident table is RESOLVED, not assembled ----------------
        seq = sym["enemyAnimSeq"]
        n = SPECIES_COUNT * ANIM_STEPS
        check("the animation table lives outside VIC bank 0",
              seq >= 0x4000, f"${seq:04x}")
        got = rd(mon, seq, n)
        want = expected_table(L1_RING, L1_DROPPER)
        check("at boot the table holds level 1's resolved pointers",
              got == want,
              f"got {[hex(b) for b in got]} want {[hex(b) for b in want]}")
        check("gameInit recorded which package is resident",
              rd1(mon, sym["lvlPackage"]) == PKG_1)
        check("every resolved pointer addresses a block inside the window",
              all(PTR_FIRST <= b < PTR_FIRST + WINDOW_BLOCKS for b in got))

        # --- 4. THE REPLACEMENT PROOF ----------------------------------------
        # Level B carries no artwork, so put recognisable bytes on its slots
        # first: the point is that the engine resolves pointers INTO them.
        for slot, mark in ((LB_RING, 0x5a), (LB_DROPPER, 0xa5)):
            for f in range(FRAMES):
                poke(mon, WINDOW + (slot + f) * 64, mark ^ f)

        call(mon, sym, "levelAssetsLoad", x=PKG_B)
        gotB = rd(mon, seq, n)
        wantB = expected_table(LB_RING, LB_DROPPER)
        check("loading Level B re-resolves EVERY entry to its slots",
              gotB == wantB,
              f"got {[hex(b) for b in gotB]} want {[hex(b) for b in wantB]}")
        check("...to different pointers than level 1 used",
              all(a != b for a, b in zip(got, gotB)),
              f"level1 {[hex(b) for b in got[:4]]} levelB {[hex(b) for b in gotB[:4]]}")
        # THE SPECIES ORDER IS REVERSED IN LEVEL B, which is what rules out a
        # loader that ignored the descriptor and just added a constant.
        check("...with the two species in the opposite order within the window",
              (got[0] < got[ANIM_STEPS]) != (gotB[0] < gotB[ANIM_STEPS]),
              f"level1 ring ${got[0]:02x} dropper ${got[ANIM_STEPS]:02x}; "
              f"levelB ring ${gotB[0]:02x} dropper ${gotB[ANIM_STEPS]:02x}")
        check("Level B's pointers address the bytes the test planted",
              rd1(mon, (gotB[0]) * 64) == (0x5a ^ 0) and
              rd1(mon, (gotB[ANIM_STEPS]) * 64) == (0xa5 ^ 0),
              f"ring block ${gotB[0]:02x} dropper block ${gotB[ANIM_STEPS]:02x}")
        check("the loader recorded the new package",
              rd1(mon, sym["lvlPackage"]) == PKG_B)

        # GAMEPLAY FOLLOWS WITHOUT KNOWING. enemyAnimPtr is unchanged code; run
        # the real loop and watch what a live enemy publishes. Any pointer it
        # emits must now be a Level B pointer.
        # GATED ON logActive, AND THAT MATTERS. logPtr is MAX_LOGICAL entries
        # and a slot keeps its last value after its object dies, so scanning
        # the array unfiltered reports pointers belonging to enemies that were
        # already dead when the package changed. Membership is an explicit bit
        # in this engine; use it rather than reading a stale slot as evidence.
        #
        # The first sample is dropped for a related reason: the breakpoint is
        # at the TOP of gameFrame, so on the first frame after the switch an
        # enemy still carries the pointer its last enemyTick wrote, one frame
        # before the table changed. That is correct behaviour, not a leak.
        bp = set_bp(mon, sym["gameFrame"])
        seen = step_n(mon, sym["frameCounter"], 64, lambda: (
            rd(mon, sym["logActive"], 16),
            rd(mon, sym["logPtr"], 16)))
        mon.cmd(f"delete {bp}"); mon.cmd("delete")
        enemy_ptrs = {p for act, ptrs in seen[1:]
                      for a, p in zip(act, ptrs)
                      if a and PTR_FIRST <= p < PTR_FIRST + WINDOW_BLOCKS}
        check("live enemies published window pointers during real play",
              bool(enemy_ptrs), f"{sorted(hex(p) for p in enemy_ptrs)}")
        check("...and every one of them is a Level B pointer, not a level 1 one",
              enemy_ptrs <= set(wantB), f"{sorted(hex(p) for p in enemy_ptrs)} "
              f"vs levelB {sorted(set(hex(p) for p in wantB))}")

        # --- 5. back to the resident package ---------------------------------
        call(mon, sym, "levelAssetsLoad", x=PKG_1)
        check("reloading level 1 restores its table exactly",
              rd(mon, seq, n) == want)

        # --- 6. short smoke: the engine is unharmed --------------------------
        free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        for label, name in (("gameOverrun", "gameOverrun"),
                            ("publishSkip", "publishSkip"),
                            ("schedBuildDefer", "schedBuildDefer"),
                            ("statPageMismatch", "statPageMismatch"),
                            ("statPtrMismatch", "statPtrMismatch")):
            val = rd1(mon, sym[name])
            check(f"{label} is zero after the round trip", val == 0, str(val))
    finally:
        if v: v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
