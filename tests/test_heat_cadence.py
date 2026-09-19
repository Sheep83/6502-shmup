#!/usr/bin/env python3
"""The heat gauge advances at the SAME RATE in the boss arena as in ordinary play.

The bug this file exists for
----------------------------
Reported as "the heat gauge moves in noticeably larger chunks once the game
reaches the boss -- in both directions". The obvious readings were all wrong:

  * the heat STATE was not being updated less often. It rises by WPN_HEAT_RISE
    on EVERY frame the trigger is held and falls by WPN_HEAT_FALL otherwise, in
    LP_LEVEL and LP_BOSS alike. src/main.asm's gameFrame calls playerTick,
    weaponTick and weaponHudFeed unconditionally -- there is no lvlPhase gate
    anywhere on that path;
  * src/hud.asm was not deferring the redraw either. The bank 0 bitmap moved a
    pixel at a time exactly as it always had.

What was actually wrong was PUBLICATION. The arena runs in VIC bank 2, where
the HUD is a MIRROR at $b200 that src/vicbank.asm walks across one 128-byte
slice a frame, round robin. HUD_HEAT_L and HUD_HEAT_R are blocks 0 and 1, so
the gauge is slice 0 -- and slice 0 came round once every VB_HUD_SLICES = 7
frames. The bar moves a pixel every ~3 frames firing and every ~2 cooling, so it
was published at a SEVENTH of the rate at which it changes: the gauge stood
still for six frames and then jumped the 2 or 3 pixels that had accumulated.

MEASURED BEFORE THE FIX, over 23 boss frames with the trigger held: the bank 0
bitmap changed 8 times, the bank 2 copy the VIC actually fetches changed 3, one
of those a 3-pixel step. The fix pins the heat slice to a copy every frame and
leaves the rest of the HUD taking turns -- the score, the lives and the P
economy change a few times a fight and a seventh of a second on those is
genuinely invisible, which is what the original round robin was reasoning about.

What this proves
----------------
* the heat STATE moves by the same amount, on the same frames, in LP_LEVEL and
  LP_BOSS -- measured, not assumed;
* THE BITMAP THE VIC ACTUALLY FETCHES advances one pixel at a time in both
  phases, heating and cooling;
* every pixel step src/hud.asm draws reaches the player in both phases, so the
  published gauge is not a coarsened sample of a smooth state;
* and the gauge moves the same NUMBER of times in a fixed frame budget in both.

WHY IT READS THE BITMAP AND NOT hudHeatPix. hudHeatPix is what the game
BELIEVES it is showing, and throughout this bug it was perfectly correct -- it
tracked the heat a pixel at a time all the way through the boss fight. A test
that asserted on it would have passed against the very defect it was written
for. The only honest measure of "what the player sees" is the sprite data at
the address the VIC is fetching from, which is a DIFFERENT ADDRESS in each
phase, and that is what bar_pixels() reads.

What this does NOT prove
------------------------
That it LOOKS right. Manual VICE is authoritative -- see AGENTS.md.

One VICE launch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     step_n, check, report)

sym = symbols(SYM)
PORT = 6733

LP_LEVEL, LP_CLEARING, LP_BOSS = 0, 1, 2
JOY_FIRE, JOY_IDLE = 0xef, 0xff

HUD_SPRITES  = 0x3200
MIRROR       = 0x8000               # VB2_BASE: bank 2 is bank 0 + $8000
HEAT_BAR_ROW = 7                    # inside HUD_HEAT_ROW0 .. +HUD_HEAT_ROWS
HUD_HEAT_PIXELS = 48
VB_HUD_SLICES   = (14 * 64) // 128  # HUD_BLOCKS * 64 / VB_SLICE

WPN_HEAT_RISE = 2                   # src/weapon.asm, per frame while firing
STAGE_FINAL   = 395
CADENCE_FRAMES = 24
# THE TWO BOUNDS, AND WHY THEY ARE WHERE THEY ARE.
#
# The bar only earns a pixel every 2-3 frames, so a displayed gauge standing
# still for 3 or 4 frames is the WEAPON's rate and not a publication defect --
# LP_LEVEL, which has no mirror at all and cannot lag by construction, measures
# a 4-frame plateau while firing. An absolute bound tight enough to catch the
# round robin would therefore fail ordinary play too.
#
# So the absolute bound is set at the thing that is unambiguously broken:
# holding the gauge still for a WHOLE slice cycle. The round robin did exactly
# that and nothing else can -- measured at 7 frames before the fix (the mirror
# moved on frames 4, 11 and 18 of 23) against 5 after it. The precision comes
# from comparing the two phases in the same run, which is the check at PART 4.
PLATEAU_MAX = VB_HUD_SLICES - 1     # 6: pre-fix measured 7, post-fix 5
JUMP_MAX    = 2                     # one raster-gate deferral, no more

CATASTROPHIC = ("gameOverrun", "scrollLate", "statPageMismatch",
                "statPtrMismatch", "objDoubleFree", "objAllocFail")


def bar_pixels(blk_l, blk_r, row=HEAT_BAR_ROW):
    """The gauge's filled pixels, read out of the bitmap itself.

    src/hud.asm's barFill is a SOLID LEFT-ALIGNED RUN, three bytes to a sprite
    row, so the population count of one row IS the pixel count: 0..24 per half
    and 0..48 across the gauge.
    """
    row_bytes = blk_l[row * 3:row * 3 + 3] + blk_r[row * 3:row * 3 + 3]
    return sum(bin(b).count("1") for b in row_bytes)


def block(mon, addr, n=64):
    out = []
    while len(out) < n:
        out += rd(mon, addr + len(out), min(64, n - len(out)))
    return out[:n]


def shown_bar(mon, bank2):
    """The gauge AS THE VIC FETCHES IT: the originals in bank 0, the mirror in
    bank 2. "What the player sees" is a different address in each phase, and
    that difference is the entire subject of this file."""
    base = HUD_SPRITES + (MIRROR if bank2 else 0)
    return bar_pixels(block(mon, base, 64), block(mon, base + 64, 64))


def heat_of(mon):
    b = rd(mon, sym["wpnHeatLo"], 2)
    return b[0] | (b[1] << 8)


def sample(mon, frames, joy, bank2):
    """One sample a displayed frame: (heat state, live bitmap, shown bitmap)."""
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["joyState"], joy)
    return step_n(mon, sym["frameCounter"], frames,
                  lambda: (heat_of(mon), shown_bar(mon, False),
                           shown_bar(mon, bank2)))


class Cadence:
    """What a stream of per-frame samples says about the gauge's PUBLICATION.

    THE PLATEAU IS THE MEASUREMENT THAT MATTERS. `jump` and `shown` describe
    the symptom, but a round robin of N slices distorts the gauge in a very
    specific way: it holds the displayed bar perfectly still for N-1 frames and
    then moves it by everything that accumulated. So the longest run of frames
    over which the shown bar does NOT move, while the bar the HUD draws IS
    moving, separates the two regimes cleanly and with room to spare --
    VB_HUD_SLICES = 7 frames before the fix against the 2-3 frames it takes the
    bar to earn its next pixel after it.

    ONE FRAME OF SLACK IS DESIGNED IN AND IS NOT THE BUG. vicMirrorLive copies
    at most once per displayed frame and only while the raster is inside
    HUD_SAFE_LO..HUD_SAFE_HI, because these are the bytes the VIC fetches for
    the HUD sprites and copying across that fetch would tear a digit. A frame
    whose hudUpdate ran late can push the copy past the window, which defers
    that frame's publication to the next one. Cooling moves a pixel every ~2.1
    frames, so a single deferral there can merge two steps into one of 2 px.
    That is a bounded, occasional one-frame lag, not a seven-frame plateau.
    """
    def __init__(self, stream):
        pairs = list(zip(stream, stream[1:]))
        self.steps = sorted({b[0] - a[0] for a, b in pairs})
        self.jump = max((abs(b[2] - a[2]) for a, b in pairs), default=0)
        self.live = sum(1 for a, b in pairs if a[1] != b[1])
        self.shown = sum(1 for a, b in pairs if a[2] != b[2])

        # The longest stretch of frames with no published movement, counted
        # only across the span in which the HUD was actually redrawing the bar
        # -- trailing frames after the gauge has bottomed out are not a plateau.
        moving = [i for i, (a, b) in enumerate(pairs) if a[1] != b[1]]
        if moving:
            marks = [i for i, (a, b) in enumerate(pairs) if a[2] != b[2]]
            marks = [m for m in marks if m <= moving[-1] + 2]
            edges = [moving[0] - 1] + marks + [moving[-1] + 1]
            self.plateau = max(b - a for a, b in zip(edges, edges[1:]))
        else:
            self.plateau = 0

    def __str__(self):
        return (f"{self.live} drawn, {self.shown} published, "
                f"biggest step {self.jump} px, "
                f"longest still stretch {self.plateau} frames")


def cool_to_empty(mon, bank2, limit=None):
    """Idle the stick until the gauge reads empty in BOTH banks.

    NOT a poke of hudHeatPix: weaponHudFeed marks the gauge dirty only when the
    pixel count it computes DIFFERS from hudHeatPix, so forcing that to zero
    alongside a heat of zero says "nothing changed" and the bitmap keeps
    whatever bar it last held. Zero the heat and let the HUD notice, which is
    what the game itself does.
    """
    for a in ("wpnHeatLo", "wpnHeatHi", "wpnOverheated"):
        poke(mon, sym[a], 0)
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["joyState"], JOY_IDLE)
    for _ in range(limit or 4 * VB_HUD_SLICES):
        step_n(mon, sym["frameCounter"], 1, lambda: None)
        if shown_bar(mon, bank2) == 0 and shown_bar(mon, False) == 0:
            return True
    return False


def measure(mon, label, bank2):
    """Heating then cooling, and everything both of them prove."""
    check(f"{label}: the gauge is empty in both banks before timing begins",
          cool_to_empty(mon, bank2),
          f"shown {shown_bar(mon, bank2)} px, live {shown_bar(mon, False)} px")

    up = Cadence(sample(mon, CADENCE_FRAMES, JOY_FIRE, bank2))
    check(f"{label}: the heat STATE rises by exactly WPN_HEAT_RISE on every "
          f"frame the trigger is held",
          up.steps == [WPN_HEAT_RISE],
          f"per-frame deltas seen: {up.steps}")
    check(f"{label}: THE BITMAP THE VIC FETCHES never sits still for a whole "
          f"slice cycle while the bar is moving",
          up.plateau <= PLATEAU_MAX, str(up))
    check(f"{label}: every pixel step the HUD draws reaches the player",
          up.shown >= up.live - 1, str(up))
    check(f"{label}: and it arrives a pixel at a time, not as an accumulated "
          f"jump", up.jump <= JUMP_MAX, str(up))

    dn = Cadence(sample(mon, CADENCE_FRAMES, JOY_IDLE, bank2))
    check(f"{label}: the heat STATE falls once the trigger is released",
          dn.steps and min(dn.steps) < 0, f"deltas {dn.steps}")
    check(f"{label}: COOLING is published at the same cadence -- the report "
          f"was of coarseness in BOTH directions",
          dn.plateau <= PLATEAU_MAX, str(dn))
    check(f"{label}: every cooling step reaches the player as well",
          dn.shown >= dn.live - 1, str(dn))
    check(f"{label}: and cooling arrives a pixel at a time too",
          dn.jump <= JUMP_MAX, str(dn))
    return up, dn


def main():
    print("=== heat gauge cadence: ordinary play vs the boss arena ===")
    v = None
    try:
        # boot="exact" because this drives worldProgress by hand below and a
        # warp-seconds boot lands at an arbitrary point in the stage.
        v = Vice(PORT, PRG, boot="exact")
        mon = v.mon
        mon.cmd("delete")
        set_bp(mon, sym["gameFrame"])
        for n in CATASTROPHIC:
            poke(mon, sym[n], 0)

        # ==================================================================
        # PART 1 -- ordinary play, in VIC bank 0
        # ==================================================================
        poke(mon, sym["stageHold"], 1)          # hold the stage still: this is
                                                # a measurement of the weapon,
                                                # not of the level
        check("ordinary play is in VIC bank 0", rd1(mon, sym["vicBank2"]) == 0)
        lvl_up, lvl_dn = measure(mon, "LP_LEVEL", bank2=False)
        check("LP_LEVEL: the phase really was LP_LEVEL throughout",
              rd1(mon, sym["lvlPhase"]) == LP_LEVEL,
              f"phase {rd1(mon, sym['lvlPhase'])}")

        # ==================================================================
        # PART 2 -- drive to the arena
        # ==================================================================
        poke(mon, sym["stageHold"], 0)
        poke(mon, sym["worldProgressLo"], (STAGE_FINAL - 1) & 0xff)
        poke(mon, sym["worldProgressHi"], (STAGE_FINAL - 1) >> 8)
        top = 1 % 420
        poke(mon, sym["stageTopRowLo"], top & 0xff)
        poke(mon, sym["stageTopRowHi"], top >> 8)
        reached = False
        for _ in range(80):
            step_n(mon, sym["frameCounter"], 8, lambda: None)
            if rd1(mon, sym["lvlPhase"]) >= LP_BOSS:
                reached = True
                break
        check("the boss phase was reached", reached,
              f"phase {rd1(mon, sym['lvlPhase'])}")
        check("...and the VIC is looking at bank 2, so the gauge the player "
              "sees is now the MIRROR and not the originals",
              rd1(mon, sym["vicBank2"]) == 1,
              f"vicBank2 = {rd1(mon, sym['vicBank2'])}")

        # ==================================================================
        # PART 3 -- the same measurement, through the mirror
        # ==================================================================
        boss_up, boss_dn = measure(mon, "LP_BOSS", bank2=True)

        # ==================================================================
        # PART 4 -- THE COMPARISON, which is the actual claim
        # ==================================================================
        check("THE STATE CADENCE IS IDENTICAL in LP_LEVEL and LP_BOSS while "
              "firing",
              boss_up.steps == lvl_up.steps == [WPN_HEAT_RISE],
              f"LP_BOSS {boss_up.steps} vs LP_LEVEL {lvl_up.steps}")
        check("...and so is the cadence at which the gauge is PUBLISHED while "
              "firing",
              abs(boss_up.shown - lvl_up.shown) <= 1,
              f"LP_BOSS [{boss_up}] vs LP_LEVEL [{lvl_up}]")
        check("...and while cooling",
              abs(boss_dn.shown - lvl_dn.shown) <= 2,
              f"LP_BOSS [{boss_dn}] vs LP_LEVEL [{lvl_dn}]")
        check("THE ARENA NEVER HOLDS THE GAUGE STILL LONGER THAN ORDINARY "
              "PLAY DOES, which is the whole report",
              boss_up.plateau <= lvl_up.plateau + 1
              and boss_dn.plateau <= lvl_dn.plateau + 1,
              f"firing {boss_up.plateau} vs {lvl_up.plateau} frames, "
              f"cooling {boss_dn.plateau} vs {lvl_dn.plateau} frames "
              f"(a {VB_HUD_SLICES}-slice round robin held it "
              f"{VB_HUD_SLICES - 1})")

        # ==================================================================
        # PART 5 -- nothing paid for it
        # ==================================================================
        # The pinned slice is one more VB_SLICE copy a frame, taken from the
        # idle spin while bank 2 is up. If that were too expensive it would
        # show up here first.
        for n in CATASTROPHIC:
            got = rd1(mon, sym[n])
            check(f"{n} is zero with the heat slice pinned", got == 0, str(got))
        check("the HUD's write window was never violated: hudUpdWrapped is zero",
              rd1(mon, sym["hudUpdWrapped"]) == 0,
              str(rd1(mon, sym["hudUpdWrapped"])))
        check("the live mirror ran throughout the boss fight",
              rd1(mon, sym["vicMirrorRuns"]) > 0,
              f"vicMirrorRuns = {rd1(mon, sym['vicMirrorRuns'])}")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
