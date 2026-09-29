#!/usr/bin/env python3
"""The build-time flight validator must fail a path that is only unsafe FAST.

WHY THIS IS A SEPARATE FILE. Every other test in this repository proves that
something works; this one has to prove that the assembler REFUSES something,
which means actually running KickAssembler and requiring a non-zero exit. That
is slow and noisy, so it stands on its own rather than making a fast suite slow.

WHAT IT GUARDS. Before trigger speed existed, src/waves.asm flew each authored
path once, at the speed its bytes said. A trigger can now walk the same path at
up to 2x, and a path that is safe at 1x is not automatically safe at 2x: the
steps get bigger, and a big enough step jumps clean over the four-pixel left
clearance window -- logXHi borrows to $ff and the sprite reappears 256 pixels to
the right. The three cases below are the three ways that could go unnoticed.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
KA = Path("/Users/brianmorrice/dev/tools/kickassembler/KickAss.jar")
LEVEL = REPO / "src" / "level1"

PASS, FAIL = [], []


def ok(m, x=""):
    PASS.append(m)
    print(f"ok  - {m}" + (f"  [{x}]" if x else ""))


def check(m, c, x=""):
    if c:
        ok(m, x)
    else:
        FAIL.append(m)
        print(f"FAIL- {m}" + (f"  [{x}]" if x else ""))


def assemble(speeds=None, leg=None):
    """Copy level 1, optionally repoint its speeds and one straight leg, build.

    `speeds` is a symbol every trigger's speed becomes; `leg` is a vx in
    quarter pixels that every WM_STRAIGHT record is widened to. Returns (returncode, output). Nothing
    is written outside the temp dir -- the production level is copied, never
    edited.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        lvl = tmp / "level"
        shutil.copytree(LEVEL, lvl)
        if speeds is not None:
            enc = lvl / "wave_encounters.asm"
            text = enc.read_text()
            new = set_all_speeds(text, speeds)
            assert new != text, "the speed patch changed nothing"
            enc.write_text(new)
        if leg is not None:
            # EVERY STRAIGHT LEG, not the first one. The pool carries programs
            # this level does not use, and an unused program is validated only
            # at the default speed -- correctly, since no trigger walks it
            # fast. Patching the first leg therefore widened a program nothing
            # flew, and the case silently stopped testing anything the day the
            # level was re-authored to use different programs.
            prg = lvl / "wave_programs.asm"
            text = prg.read_text()
            # ONLY vx, AND ONLY ON LEGS THAT ALREADY TRAVEL HORIZONTALLY.
            #
            # Two earlier fixtures were too blunt and both were caught by the
            # validator doing its job rather than by luck. Replacing the whole
            # record flattened up_n_over's climb ("a pattern is never visible
            # inside the aperture"); widening every leg gave dive_bomb's pure
            # vertical dive a sideways component and its loop then never
            # terminated ("a pattern never reaches any despawn edge"). Both
            # were real rules firing for reasons that had nothing to do with
            # speed.
            #
            # A leg that already moves in X can move in X faster without
            # becoming a different path, which is the only change this fixture
            # wants to make.
            new, n = re.subn(r"(WM_STRAIGHT, *\d+, *)(-[1-9]\d*|[1-9]\d*)(, *-?\d+)",
                             lambda m: m.group(1)
                             + ("-" if m.group(2).startswith("-") else "")
                             + str(leg) + m.group(3), text)
            assert n, "this level has no horizontally-travelling straight leg"
            prg.write_text(new)
        r = subprocess.run(
            ["java", "-jar", str(KA), "src/main.asm",
             "-libdir", str(lvl), "-libdir", str(REPO / "src"),
             "-odir", str(tmp), "-o", str(tmp / "out.prg")],
            cwd=REPO, capture_output=True, text=True, timeout=300)
        return r.returncode, r.stdout + r.stderr


def set_all_speeds(text, symbol):
    """Repoint every trigSpeed entry, KEEPING THE COLUMN'S LENGTH.

    It used to emit a fixed twelve, which was the level's trigger count the
    day this was written. When the level was re-authored to three, the column
    no longer matched WAVE_TRIGGERS and the engine's own size proof fired --
    correctly, but for a reason that had nothing to do with speed, so three
    checks here started testing the wrong error.
    """
    m = re.search(r"\.var trigSpeed\s*=\s*List\(\)\.add\(([^)]*)\)", text)
    assert m, "the generated level declares no trigSpeed column"
    # COUNT THE ARGUMENTS, NOT THE CALLS. _list_decl emits ONE .add() with a
    # comma-separated list, so counting ".add(" gave 1 however many triggers
    # there were -- which wrote a one-entry column and made the engine report
    # an index error instead of the check this test meant to exercise.
    n = len([x for x in m.group(1).split(",") if x.strip()])
    assert n, "the trigSpeed column is empty; this level authors no triggers"
    return (text[:m.start()]
            + ".var trigSpeed = List().add("
            + ", ".join([symbol] * n) + ")"
            + text[m.end():])


if not KA.is_file():
    print(f"SKIP- KickAssembler not found at {KA}")
    sys.exit(0)

# ===========================================================================
# 0. the control: the level as authored must still assemble
# ===========================================================================
rc, out = assemble()
check("the authored level assembles unchanged (the control)", rc == 0,
      out.strip().splitlines()[-1] if rc else "")

# ===========================================================================
# 1. every authored path is still safe at the top speed
# ===========================================================================
# Not a rejection test -- the opposite. If this failed, 2x would be unusable on
# the current content and the feature would be shipping broken.
rc, out = assemble(speeds="TRIG_SPEED_2X")
check("every authored level-1 path survives being flown at 2.00x", rc == 0,
      "\n".join(l for l in out.splitlines() if "Error" in l)[:300])

# ===========================================================================
# 2. a leg that is legal at 1x but wraps at 2x IS REFUSED
# ===========================================================================
# vx = 9 QUARTER PIXELS IS THE SMALLEST PERTURBATION THAT PROVES THE POINT.
# It is comfortably legal at 1.00x (9 <= 16, the per-record ceiling) and
# illegal at 2.00x (9*8>>2 = 18 > 16, wider than the clearance window), so
# speed is the only variable between the two cases below.
#
# The first attempt used 16 -- the ceiling itself -- applied as a whole
# replacement record. That flattened up_n_over's climb and tripped "a pattern
# is never visible inside the aperture": a real rule, firing for a reason with
# nothing to do with speed. A gentle widening keeps every path its own shape.
rc, out = assemble(speeds="TRIG_SPEED_2X", leg=9)
check("a straight leg that only wraps once scaled is REFUSED", rc != 0)
check("...and the error names the clearance window",
      "clearance window" in out,
      next((l.strip() for l in out.splitlines() if "clearance" in l), out[:200]))

# ===========================================================================
# 3. the same leg at 1x is still accepted
# ===========================================================================
# The proof that case 2 failed for the RIGHT reason: identical bytes, default
# speed, must assemble. Without this, case 2 could be passing because the leg
# is malformed rather than because it is too fast.
#
# 1.00x IS PINNED EXPLICITLY rather than left to the level. The authored level
# now uses 1.50x and 2.00x, so "no speed patch" is not "the default" any more
# and this control was being refused by the very rule it exists to isolate.
rc, out = assemble(speeds="TRIG_SPEED_1X", leg=9)
check("...while the identical leg at 1.00x still assembles", rc == 0,
      "\n".join(l for l in out.splitlines() if "Error" in l)[:300])

# ===========================================================================
# 4. a speed outside the authored range is refused
# ===========================================================================
# 3 IS BELOW THE RANGE BUT SLOWER, so it trips the range check and nothing
# else -- which is what makes it the right probe for that check specifically.
# A value like 16 is also refused, but by the wrap guard above it, because a
# quadruple-speed arc jumps the clearance window before anyone asks whether 16
# was an authored choice.
rc, out = assemble(speeds="3")
check("a trigger speed below TRIG_SPEED_MIN is refused", rc != 0)
check("...and the error names the range",
      "movement speed outside" in out,
      next((l.strip() for l in out.splitlines() if "movement speed" in l),
           out[:200]))

rc, out = assemble(speeds="16")
check("an absurd trigger speed is refused by SOME guard", rc != 0,
      next((l.strip() for l in out.splitlines()
            if "clearance" in l or "movement speed" in l), "")[:120])

rc, out = assemble(speeds="0")
check("a trigger speed of zero is refused", rc != 0)

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for m in FAIL:
    print(f"  FAILED: {m}")
sys.exit(1 if FAIL else 0)
