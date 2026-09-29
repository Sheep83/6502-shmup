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

Constraint #4: production code, free-running. The only things poked are the
package's own trigger columns -- speed, and in the last section the definition
index -- which are authored data, the technique tests/test_aimed_fire.py
already uses on the firing mode.

Six VICE launches, each short.
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     read16, step_n, call, check, report)

sym = symbols(SYM)

PORT = 6680
MAX_OBJECTS = 16
TYPE_ENEMY = 1
LEVELPKG_TRIGN = 0xFF92                 # the live trigger count; src/levelpkg.asm
SPEED_CHOICES = (4, 5, 6, 7, 8)
LABEL = {4: "1.00x", 5: "1.25x", 6: "1.50x", 7: "1.75x", 8: "2.00x"}
SWEEP_VX = 6                            # the opening STRAIGHT of `sweep`
WATCH = 340                             # frames: trigger 0 is due at ~160


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


def observe(speed):
    """One short launch with every trigger at `speed`. Returns its runs."""
    v = None
    try:
        v = Vice(PORT + speed, PRG, boot="exact")
        mon = v.mon
        set_all_speeds(mon, speed)
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
    col = rd(mon, sym["waveTrigSpeed"], n)
    check("every authored trigger carries a movement speed", len(col) == n,
          f"{n} triggers")
    check("...and every one of them is 1.00x", set(col) == {4},
          str(sorted(set(col))))
    check("the padding past the live triggers is 1.00x, not zero -- a zero "
          "would be a multiplier of nothing",
          rd1(mon, sym["waveTrigSpeed"] + n) == 4)
finally:
    if v:
        v.close()

# ===========================================================================
# 2. THE SCALED VELOCITY, MEASURED, AT ALL FIVE SPEEDS
# ===========================================================================
print("\n=== the velocity the engine computes, per speed ===")
for n in SPEED_CHOICES:
    rs = observe(n)
    by_speed[n] = rs
    if not rs:
        check(f"{LABEL[n]}: enemies were seen", False)
        continue
    check(f"{LABEL[n]}: every enemy carries it on the OBJECT",
          all(r[0][5] == n for r in rs),
          f"{len(rs)} lifetimes, speeds {sorted({r[0][5] for r in rs})}")
    # THE OPENING LEG OF `sweep` IS A KNOWN STRAIGHT: vx = SWEEP_VX, vy = 0.
    # It is the first wave the level sends, so a short window always has it.
    want = scale(SWEEP_VX, n)
    opening = [r for r in rs if r[0][3] == want and r[0][5] == n]
    check(f"...and its straight leg runs at the scaled velocity {want}",
          bool(opening),
          f"opening vx seen: {sorted({r[0][3] for r in rs})}, wanted {want}")
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

check("1.00x is bit-identical to the engine's own authored velocity",
      any(r[0][3] == SWEEP_VX for r in by_speed.get(4, [])),
      f"wmVX = {SWEEP_VX} quarter pixels, unscaled")
check("2.00x is exactly double",
      scale(SWEEP_VX, 8) == 2 * SWEEP_VX
      and any(r[0][3] == 2 * SWEEP_VX for r in by_speed.get(8, [])))

print("\n=== arcs scale too, though they carry no authored velocity ===")
for n in SPEED_CHOICES:
    rs = by_speed.get(n) or []
    mags = {max(abs(s[3]), abs(s[4])) for r in rs for s in r}
    want = scale(6, n)                  # WM_ARC_SPEED at this speed
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
# THE CLAIM THE FEATURE EXISTS FOR. Level 1 does reuse definitions across
# triggers, but its shared pairs sit at world rows 205 and 310 -- frames 1640
# and 2480 -- and stepping that far through the monitor costs minutes for one
# assertion. So two EARLY triggers are pointed at one definition instead:
# trigDef is authored data exactly like trigSpeed, and the thing being proved
# is a runtime property of sharing, not of where the author put the rows.
print("\n=== two triggers on ONE definition, at two speeds ===")
v = None
seen = {}
try:
    v = Vice(PORT + 20, PRG, boot="exact")
    mon = v.mon
    set_all_speeds(mon, 4)
    shared = rd1(mon, sym["waveTrigDef"] + 0)       # whatever trigger 0 plays
    poke(mon, sym["waveTrigDef"] + 1, shared)       # trigger 1 now plays it too
    poke(mon, sym["waveTrigSpeed"] + 0, 4)
    poke(mon, sym["waveTrigSpeed"] + 1, 8)
    check("two early triggers now share one definition",
          rd1(mon, sym["waveTrigDef"] + 0) == rd1(mon, sym["waveTrigDef"] + 1),
          f"definition {shared}")
    check("...at 1.00x and 2.00x",
          (rd1(mon, sym["waveTrigSpeed"] + 0),
           rd1(mon, sym["waveTrigSpeed"] + 1)) == (4, 8))
    rs = runs(watch(mon, 620))          # far enough for trigger 1 (row 52)
    for r in rs:
        sp = r[0][5]
        seen.setdefault(sp, set()).update(abs(s[3]) for s in r if s[3])
finally:
    if v:
        v.close()

check("enemies from BOTH appearances were observed in one run",
      {4, 8} <= set(seen), f"speeds seen {sorted(seen)}")
if {4, 8} <= set(seen):
    check("ONE DEFINITION PRODUCED ENEMIES AT TWO DIFFERENT VELOCITIES",
          scale(SWEEP_VX, 4) in seen[4] and scale(SWEEP_VX, 8) in seen[8],
          f"1.00x |vx| {sorted(seen[4])}; 2.00x |vx| {sorted(seen[8])}")
    check("...and the fast one's maximum is twice the slow one's",
          max(seen[8]) == 2 * max(seen[4]),
          f"{max(seen[4])} -> {max(seen[8])} quarter pixels a frame")

sys.exit(report(__name__))
