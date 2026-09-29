#!/usr/bin/env python3
"""Trigger-owned movement speed, on the machine.

The authoring path is proved in tools/level_editor/test_trigger_speed.py and
the build-time flight validator in test_trigger_speed_validator.py. This proves
what the C64 does with the byte they produce.

HOW IT MEASURES, AND WHY NOT THE OBVIOUS WAY. A first draft averaged the path
length of every enemy over a fixed window and compared the mean at 1x with the
mean at 2x. Both numbers were right and the comparison was meaningless: path
length was summed as |dx|+|dy|, which on a 45-degree leg is 1.41 times the
distance travelled, and at 2x more waves complete inside the window so the
average is taken over a different mix of paths. It reported 1.64x for a change
that is exactly 2x.

So this measures the two things that are actually defined:

  * wmVX / wmVY -- the velocity the engine COMPUTED for a live enemy, which
    must equal the scaled authored value exactly, for all five speeds;
  * the per-frame displacement of one enemy, which must equal that velocity
    integrated in quarter pixels.

THE WAVE IT FLIES IS SYNTHETIC, AND THAT IS THE POINT.

The first version leant on the authored level: `SWEEP_VX = 6  # the opening
STRAIGHT of sweep`, and "trigger 0 is due at ~160", and "every authored trigger
is 1.00x". All three were readings of Level 1 in August. The level has since been
re-authored -- it no longer opens with `sweep` and it authors four different
speeds -- and eleven checks failed about an engine that was entirely correct.

So the velocity under test is one this file WRITES: a STRAIGHT leg of a known
magnitude, in a wave definition of its own, on a trigger of its own, at a row
the world reaches immediately. Everything installed goes into the SPARE ROOM the
package reserves and no level uses (tests/synth.py) -- package RAM only, never
the disk, so no authored level is edited to make a test pass.

Constraint #4: production code, free-running. The only things poked are the
package's own movement pool, definition table and trigger columns, all of which
are authored data -- the technique tests/test_aimed_fire.py already uses on the
firing mode and tests/test_wave_triggers.py on the rows.

Six VICE launches, each short.
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     read16, step_n, call, check, report)
import campaign_data as CD                                       # noqa: E402
import synth                                                     # noqa: E402

sym = symbols(SYM)

PORT = 6680
MAX_OBJECTS = 16
TYPE_ENEMY = 1
LEVELPKG_TRIGN = CD.TRIGN_ADDR          # the live trigger count; src/levelpkg.asm
SPEED_CHOICES = tuple(CD.C.SPEED_CHOICES)
LABEL = dict(CD.C.SPEED_LABELS)

# THE SYNTHETIC SPECIMEN. A STRAIGHT leg of this velocity, flown by a wave of
# this size, from a trigger at this row. Nothing here is read off a level.
#
# SYN_VX IS CHOSEN SO THE FIVE SCALINGS ARE FIVE DISTINCT VALUES -- 6, 7, 9, 10
# and 12 quarter pixels -- otherwise "the velocity changed with the speed" could
# pass while two speeds quietly produced the same number. It is also small
# enough that 2.00x stays inside the despawn guard: 12 quarter pixels is 3 whole
# pixels a frame and ENEMY_CLEAR_X_LEFT allows 4.
SYN_VX, SYN_VY = 6, 0
SYN_ROW = 8                             # boot="exact" arrives below row 4
SYN_ROW_B = 24                          # the second trigger of the shared pair
SYN_COUNT, SYN_INTERVAL = 3, 10
WATCH = 200                             # frames: the row above is due at once


def s8(b):
    return b - 256 if b > 127 else b


def scale(v, n):
    """The engine's wmScaleOne: magnitude, shift, sign back on."""
    mag = abs(v) * n >> 2
    return -mag if v < 0 else mag


def set_all_speeds(mon, value):
    """Every AUTHORED trigger to one speed. Live entries only -- the columns
    are padded to the slot count and the director never reads past TRIGN."""
    for t in range(rd1(mon, LEVELPKG_TRIGN)):
        poke(mon, sym["waveTrigSpeed"] + t, value)


def watch(mon, frames):
    """Per-frame (x, y, vx, vy, speed) for every live enemy, keyed by slot."""
    seq = collections.defaultdict(list)
    bp = set_bp(mon, sym["gameFrame"])

    def snap():
        act = rd(mon, sym["logActive"], MAX_OBJECTS)
        typ = rd(mon, sym["objType"], MAX_OBJECTS)
        xlo = rd(mon, sym["logX"], MAX_OBJECTS)
        xhi = rd(mon, sym["logXHi"], MAX_OBJECTS)
        ys = rd(mon, sym["logY"], MAX_OBJECTS)
        vx = rd(mon, sym["wmVX"], MAX_OBJECTS)
        vy = rd(mon, sym["wmVY"], MAX_OBJECTS)
        sp = rd(mon, sym["wmSpeed"], MAX_OBJECTS)
        fr = read16(mon, sym["frameCounter"])
        return [(s, fr, xlo[s] | (xhi[s] << 8), ys[s],
                 s8(vx[s]), s8(vy[s]), sp[s])
                for s in range(MAX_OBJECTS)
                if act[s] and typ[s] == TYPE_ENEMY]

    for rows in step_n(mon, sym["frameCounter"], frames, snap):
        for s, fr, x, y, vx, vy, spd in rows:
            seq[s].append((fr, x, y, vx, vy, spd))
    mon.cmd(f"delete {bp}")
    return seq


def runs(seq):
    """Split each slot into runs of continuous occupancy by one enemy."""
    out = []
    for rows in seq.values():
        cur = [rows[0]]
        for a, b in zip(rows, rows[1:]):
            if b[0] != a[0] + 1:
                out.append(cur)
                cur = [b]
            else:
                cur.append(b)
        out.append(cur)
    return [r for r in out if len(r) >= 6]


def install_specimen(mon, sym, *, speed, vx=None, vy=None, arc=False):
    """Replace the schedule with ONE synthetic wave of known velocity.

    Returns (pkg, definition index, program byte offset). `arc=True` appends an
    ARC after the straight leg so the arc magnitude can be observed in the same
    run -- the arc carries no authored velocity of its own, which is exactly why
    it has to be watched rather than computed.
    """
    vx = SYN_VX if vx is None else vx
    vy = SYN_VY if vy is None else vy
    pkg = synth.Package(mon, sym)
    stages = [[synth.WM_STRAIGHT, 120, vx & 0xFF, vy & 0xFF]]
    if arc:
        stages.append([synth.WM_ARC, 32, 4, 0])      # clockwise from east
    stages.append([synth.WM_EXIT, 0, 0, 0])
    prog = pkg.install_program(stages)
    defn = pkg.install_definition(count=SYN_COUNT, interval=SYN_INTERVAL,
                                  start_x=80, start_y=50, x_step=0, y_step=18,
                                  heading=0, program=prog)
    pkg.only_trigger(row=SYN_ROW, definition=defn, speed=speed)
    return pkg, defn, prog


def observe(speed, *, arc=False):
    """One short launch flying the SYNTHETIC wave at `speed`. Returns its runs."""
    v = None
    try:
        v = Vice(PORT + speed, PRG, boot="exact")
        mon = v.mon
        install_specimen(mon, sym, speed=speed, arc=arc)
        return runs(watch(mon, WATCH))
    finally:
        if v:
            v.close()


# ===========================================================================
# 1. THE PACKAGE CARRIES IT, AND IT IS 1.00x AS AUTHORED
# ===========================================================================
print("\n=== the package carries a speed column ===")
by_speed = {}
v = None
try:
    v = Vice(PORT, PRG, boot="exact")
    mon = v.mon
    n = rd1(mon, LEVELPKG_TRIGN)
    col = list(rd(mon, sym["waveTrigSpeed"], n))
    check("every authored trigger carries a movement speed", len(col) == n,
          f"{n} triggers")
    # WHAT THE AUTHOR CHOSE IS NOT THIS FILE'S BUSINESS. This check used to be
    # `set(col) == {4}` -- "every one of them is 1.00x" -- which was a reading of
    # the level on the day the migration ran, and became false the moment Brian
    # used the feature. The invariant is that every byte is one the engine can
    # multiply by.
    check("...and every one is a speed the engine defines",
          all(CD.C.TRIG_SPEED_MIN <= c <= CD.C.TRIG_SPEED_MAX for c in col),
          f"{sorted(set(col))} within "
          f"{CD.C.TRIG_SPEED_MIN}..{CD.C.TRIG_SPEED_MAX} "
          f"({', '.join(LABEL[c] for c in sorted(set(col)))})")
    check("the padding past the live triggers is 1.00x, not zero -- a zero "
          "would be a multiplier of nothing",
          rd1(mon, sym["waveTrigSpeed"] + n) == CD.C.TRIG_SPEED_1X,
          f"slot {n} = {rd1(mon, sym['waveTrigSpeed'] + n)}")
    check("...and so is every slot to the end of the column, not just the first",
          set(rd(mon, sym["waveTrigSpeed"] + n, CD.TRIG_SLOTS - n))
          == {CD.C.TRIG_SPEED_1X},
          f"{CD.TRIG_SLOTS - n} padding slots")
finally:
    if v:
        v.close()

# ===========================================================================
# 2. THE SCALED VELOCITY, MEASURED, AT ALL FIVE SPEEDS
# ===========================================================================
print("\n=== the velocity the engine computes, per speed ===")
print(f"       the specimen: a STRAIGHT leg of ({SYN_VX}, {SYN_VY}) quarter "
      f"pixels, on a synthetic wave of {SYN_COUNT} at row {SYN_ROW}")
seen_vx = {}
for n in SPEED_CHOICES:
    rs = observe(n, arc=True)
    by_speed[n] = rs
    if not rs:
        check(f"{LABEL[n]}: enemies were seen", False)
        continue
    check(f"{LABEL[n]}: every enemy carries it on the OBJECT",
          all(r[0][5] == n for r in rs),
          f"{len(rs)} lifetimes, speeds {sorted({r[0][5] for r in rs})}")
    # THE STRAIGHT LEG IS THE ONE THIS FILE WROTE, so the expected velocity is
    # arithmetic on SYN_VX and not a reading of anybody's level.
    want = scale(SYN_VX, n)
    opening = [r for r in rs if r[0][3] == want and r[0][5] == n]
    seen_vx[n] = sorted({r[0][3] for r in rs})
    check(f"...and the synthetic straight leg runs at the scaled velocity "
          f"{want}", bool(opening),
          f"opening vx seen: {seen_vx[n]}, wanted {want}")
    # ...AND THE POSITION ACTUALLY MOVES AT THAT VELOCITY. Reading wmVX only
    # proves the scaler ran; differencing logX proves the integrator used it.
    if opening:
        r = opening[0]
        span = [s for s in r if s[3] == want][:20]
        if len(span) >= 6:
            dx = span[-1][1] - span[0][1]
            frames = span[-1][0] - span[0][0]
            check(f"...and the position advances at {want}/4 px a frame",
                  abs(dx - frames * want // 4) <= 1,
                  f"{dx} px in {frames} frames, expected "
                  f"{frames * want // 4}")

check("1.00x is bit-identical to the authored velocity -- the multiplier is a "
      "no-op, not a rounding",
      SYN_VX in (by_speed.get(CD.C.TRIG_SPEED_1X) and
                 [r[0][3] for r in by_speed[CD.C.TRIG_SPEED_1X]] or []),
      f"wmVX = {SYN_VX} quarter pixels, unscaled")
top = max(SPEED_CHOICES)
check(f"{LABEL[top]} is exactly double",
      scale(SYN_VX, top) == 2 * SYN_VX
      and any(r[0][3] == 2 * SYN_VX for r in by_speed.get(top, [])))
check("the five speeds produced FIVE DISTINCT straight-leg velocities -- no two "
      "of them quietly agree",
      len({scale(SYN_VX, n) for n in SPEED_CHOICES}) == len(SPEED_CHOICES)
      and all(scale(SYN_VX, n) in seen_vx.get(n, []) for n in SPEED_CHOICES),
      "; ".join(f"{LABEL[n]}={scale(SYN_VX, n)}" for n in SPEED_CHOICES))

print("\n=== arcs scale too, though they carry no authored velocity ===")
# WM_ARC_SPEED IS AN ENGINE CONSTANT, read from the movement format rather than
# written as a 6. The ARC stage is part of the synthetic program above, so this
# no longer depends on the authored level containing a turn at all.
ARC_SPEED = CD.WM_ARC_SPEED
for n in SPEED_CHOICES:
    rs = by_speed.get(n) or []
    mags = {max(abs(s[3]), abs(s[4])) for r in rs for s in r}
    want = scale(ARC_SPEED, n)
    check(f"{LABEL[n]}: a velocity of the scaled arc magnitude {want} appears",
          want in mags, f"magnitudes seen {sorted(mags)}")

# ===========================================================================
# 2b. THE SCALER ITSELF, EXERCISED ON THE 6502
# ===========================================================================
# OBSERVATION CANNOT REACH THE SIGNED CASES. Level 1's opening waves travel
# right and down, so watching them proves nothing about negative components,
# and waiting for a path that turns west costs minutes for one assertion.
# wmApplySpeed is self-contained -- it reads wmSpeed[X] and rewrites wmVX[X]
# and wmVY[X] in place -- so it can simply be called, which turns "probably
# symmetric" into every value, every speed, on the real processor.
print("\n=== wmApplySpeed, called directly, over the whole range ===")
SLOT = 12                               # a slot the authored waves leave free
v = None
mismatch = []
tried = 0
try:
    v = Vice(PORT + 15, PRG, boot="exact")
    mon = v.mon
    for n in SPEED_CHOICES:
        poke(mon, sym["wmSpeed"] + SLOT, n)
        for raw in (-16, -12, -9, -6, -5, -3, -1, 0, 1, 3, 5, 6, 9, 12, 16):
            poke(mon, sym["wmVX"] + SLOT, raw & 0xFF)
            poke(mon, sym["wmVY"] + SLOT, (-raw) & 0xFF)
            call(mon, sym, "wmApplySpeed", x=SLOT)
            gx = s8(rd1(mon, sym["wmVX"] + SLOT))
            gy = s8(rd1(mon, sym["wmVY"] + SLOT))
            tried += 1
            if (gx, gy) != (scale(raw, n), scale(-raw, n)):
                mismatch.append((n, raw, gx, gy,
                                 scale(raw, n), scale(-raw, n)))
finally:
    if v:
        v.close()

check("the 6502 scaler agrees with the model for every value and speed",
      not mismatch, str(mismatch[:4]) if mismatch else f"{tried} cases")
check("...including negatives, which no observed path reached",
      tried and not [m for m in mismatch if m[1] < 0], "-16 .. -1 covered")
check("...and zero stays zero at every speed", not [m for m in mismatch if m[1] == 0])
check("...and it is exactly antisymmetric: scale(-v) == -scale(v)",
      all(scale(-x, n) == -scale(x, n)
          for x in range(0, 33) for n in SPEED_CHOICES) and not mismatch)

# ===========================================================================
# 3. TWO TRIGGERS, ONE DEFINITION, TWO SPEEDS
# ===========================================================================
# THE CLAIM THE FEATURE EXISTS FOR, BUILT RATHER THAN LOOKED FOR. An earlier
# version pointed authored trigger 1 at authored trigger 0's definition and
# depended on trigger 1's row being early enough to reach; the rows moved and
# the observation window stopped containing it. Both triggers, the definition
# they share and the rows they sit at are now this file's own -- so "one
# definition, two speeds" is a property of the engine and not of the schedule.
print("\n=== two triggers on ONE definition, at two speeds ===")
SLOW, FAST = CD.C.TRIG_SPEED_1X, max(SPEED_CHOICES)
v = None
seen = {}
try:
    v = Vice(PORT + 20, PRG, boot="exact")
    mon = v.mon
    pkg = synth.Package(mon, sym)
    prog = pkg.straight_then_exit(SYN_VX, SYN_VY)
    shared = pkg.install_definition(count=SYN_COUNT, interval=SYN_INTERVAL,
                                    start_x=80, start_y=50, x_step=0,
                                    y_step=18, heading=0, program=prog)
    pkg.pair_on_one_definition(rows=(SYN_ROW, SYN_ROW_B), definition=shared,
                               speeds=(SLOW, FAST))
    check("two synthetic triggers share ONE definition",
          rd1(mon, sym["waveTrigDef"] + 0) == rd1(mon, sym["waveTrigDef"] + 1)
          == shared, f"definition {shared}")
    check(f"...at {LABEL[SLOW]} and {LABEL[FAST]}",
          (rd1(mon, sym["waveTrigSpeed"] + 0),
           rd1(mon, sym["waveTrigSpeed"] + 1)) == (SLOW, FAST))
    check("...and the definition itself carries no speed to conflict with -- "
          "byte 7 is reserved and zero",
          rd1(mon, sym["waveDefTable"] + shared * CD.WAVEDEF_SIZE
              + CD.WD_RESERVED) == 0)
    rs = runs(watch(mon, 400))          # both synthetic rows are within reach
    for r in rs:
        sp = r[0][5]
        seen.setdefault(sp, set()).update(abs(s[3]) for s in r if s[3])
finally:
    if v:
        v.close()

check("enemies from BOTH appearances were observed in one run",
      {SLOW, FAST} <= set(seen), f"speeds seen {sorted(seen)}")
if {SLOW, FAST} <= set(seen):
    check("ONE DEFINITION PRODUCED ENEMIES AT TWO DIFFERENT VELOCITIES",
          scale(SYN_VX, SLOW) in seen[SLOW]
          and scale(SYN_VX, FAST) in seen[FAST],
          f"{LABEL[SLOW]} |vx| {sorted(seen[SLOW])}; "
          f"{LABEL[FAST]} |vx| {sorted(seen[FAST])}")
    check("...and the fast one's maximum is twice the slow one's",
          max(seen[FAST]) == 2 * max(seen[SLOW]),
          f"{max(seen[SLOW])} -> {max(seen[FAST])} quarter pixels a frame")

sys.exit(report(__name__))
