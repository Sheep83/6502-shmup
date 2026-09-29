#!/usr/bin/env python3
"""Enemy colour AND firing mode belong to the TRIGGER: what the machine does.

The authoring path is proved in tools/level_editor/test_wave_colour_mode.py.
This proves the runtime half:

  * a trigger's colour byte is latched onto the WAVE INSTANCE when the wave is
    armed, so two triggers playing the same reusable definition colour their
    enemies independently -- the claim the whole ownership move exists for;
  * a FIXED appearance gives every member exactly its trigger's colour;
  * a RANDOM appearance gives its members DIFFERENT colours, all eligible;
  * the eligible pool is still built from the RESIDENT LEVEL'S live colours and
    still excludes black, both shared sprite multicolours and the terrain's
    charset colour, with the player's colour still in it;
  * the choice is made once at spawn and does not move again;
  * a hit flash returns to the enemy's own chosen colour;
  * the firing mode is a trigger field too: two triggers on one definition can
    attack differently, and byte 7 of a definition is now reserved and zero.

WHAT USED TO BE HERE, AND WHY IT HAD TO GO. The first two launches "poke
NOTHING -- the authored Level 1 already contains a fixed appearance and eleven
random ones", and the third hunted the authored list for a definition shared by
two non-Dropper triggers. Both were readings of Level 1 in August: seven
definitions, twelve triggers at named rows, one AIMED appearance at row 20. The
level has five triggers now, and four checks failed because nothing about the
engine had changed.

So the appearances these cases need are BUILT: one FIXED and one RANDOM trigger,
and a shared definition with two triggers on it at two colours and two firing
modes -- installed into the spare room the package reserves (tests/synth.py),
package RAM only, never the disk. The eligible-colour pool, the exclusions and
the flash restore are still measured on the level as it really ships, because
those are properties of the RESIDENT LEVEL'S palette rather than of its
schedule.

Three VICE launches.
"""
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,  # noqa: E402
                     read16, step_n, call, check, report)
import campaign_data as CD                                       # noqa: E402
import synth                                                     # noqa: E402

sym = symbols(SYM)

PORT = 6615
MAX_OBJECTS, WAVE_SLOTS = 16, 2
TYPE_ENEMY = 1
ENEMY_FIRE_AIMED = 2                    # src/enemy.asm
WAVEDEF_SIZE, WD_RESERVED = CD.WAVEDEF_SIZE, CD.WD_RESERVED
COL_MASK, COL_RANDOM = CD.C.TRIG_COL_MASK, CD.C.TRIG_COL_RANDOM
TRIG_FIRE_DOWN = CD.C.FIRE_MODES["DOWN"]
TRIG_FIRE_AIMED = CD.C.FIRE_MODES["AIMED"]
PLAYER_COL_SHIP = 14                    # src/player.asm

HIT_COL_FLASH = 4                       # src/collision.asm
DEATH_COLS = (7, 8, 2)

# HOW MANY DEFINITIONS AND TRIGGERS THE LEVEL HAS, AND WHAT THEY ARE CALLED, IS
# READ -- and used only for the info lines and the export-consistency check.
# `WAVE_DEFS, WAVE_TRIGGERS = 7, 12`, a tuple of seven definition names and a
# tuple of twelve rows used to be literals here.
_L1 = CD.level("level1")
WAVE_DEFS = _L1.n_defs
WAVE_TRIGGERS = _L1.n_triggers
TRIG_ROWS = tuple(_L1.trig_row)
DEF_NAMES = tuple(f"def{i}" for i in range(WAVE_DEFS))

# The synthetic appearances the ownership cases fly.
SYN_ROW_A, SYN_ROW_B = 8, 24
SYN_COUNT, SYN_INTERVAL = 4, 8
SYN_FIXED_COLOUR, SYN_OTHER_COLOUR = 3, 7       # cyan and yellow, both eligible

SPAWN_SAMPLES = 150
STABLE_FRAMES = 420

REG_X = re.compile(r"^\.;[0-9a-f]{4}\s+[0-9a-f]{2}\s+([0-9a-f]{2})", re.M)


def pool_of(mon):
    n = rd1(mon, sym["wvColCount"])
    return n, rd(mon, sym["wvColPool"], 16)[:n], rd(mon, sym["wvColBan"], 4)


def trigger_columns(mon, n=None):
    """The live trigger list as the loaded package holds it, however long."""
    n = rd1(mon, CD.TRIGN_ADDR) if n is None else n
    return {
        "n": n,
        "def": rd(mon, sym["waveTrigDef"], n),
        "colour": rd(mon, sym["waveTrigColour"], n),
        "firemode": rd(mon, sym["waveTrigFireMode"], n),
        "firemask": rd(mon, sym["waveTrigFire"], n),
        "species": rd(mon, sym["waveTrigSpecies"], n),
    }


def watch_spawns(mon, n):
    """Every enemy spawned, with the wave INSTANCE that made it.

    objectActivate is the moment a spawn becomes real. wvInst still names the
    instance being served, so the appearance's own latched colour byte and the
    definition it is playing are both readable -- production state only.
    """
    out = []
    bp = set_bp(mon, sym["objectActivate"])
    for _ in range(n):
        mon.cmd("x")
        m = REG_X.search(mon.cmd("registers"))
        if not m:
            continue
        slot = int(m.group(1), 16)
        if slot >= MAX_OBJECTS:
            continue
        if rd1(mon, sym["objType"] + slot) != TYPE_ENEMY:
            continue
        inst = rd1(mon, sym["wvInst"])
        if inst >= WAVE_SLOTS:
            continue
        out.append({
            "inst": inst,
            "def": rd1(mon, sym["wvDef"] + inst),
            "trigcol": rd1(mon, sym["wvColour"] + inst),
            "trigfire": rd1(mon, sym["wvFireMode"] + inst),
            "base": rd1(mon, sym["wmBaseCol"] + slot),
            "logcol": rd1(mon, sym["logCol"] + slot),
            "fire": rd1(mon, sym["enyFire"] + slot),
            "frame": read16(mon, sym["frameCounter"]),
        })
    mon.cmd(f"delete {bp}")
    return out


# ===========================================================================
# LAUNCH 1 -- the authored level: ownership, the pool, and every spawn
# ===========================================================================
print("\n=== the trigger list carries the colour, the definitions do not ===")
v = None
spawns, pool, bans = [], [], []
try:
    v = Vice(PORT, PRG, boot="exact")
    mon = v.mon

    cols = trigger_columns(mon)
    rows = [rd1(mon, sym["waveTrigRowLo"] + i)
            | (rd1(mon, sym["waveTrigRowHi"] + i) << 8)
            for i in range(cols["n"])]
    for row, d, c in zip(rows, cols["def"], cols["colour"]):
        mode = "RANDOM" if c & COL_RANDOM else "fixed "
        print(f"       row {row:>4}  definition {d:<3} ${c:02x}  {mode} "
              f"colour {c & COL_MASK}")
    check("every live trigger carries a colour byte",
          len(cols["colour"]) == cols["n"], f"{cols['n']} triggers")
    check("no trigger colour byte sets a bit outside colour and the flag",
          all(c <= COL_MASK + COL_RANDOM for c in cols["colour"]),
          str([hex(c) for c in cols["colour"]]))
    check("the package's colour and firing-mode columns are what the generated "
          "level declares -- exporter and engine agree",
          (list(cols["colour"]), list(cols["firemode"]))
          == (_L1.trig_colour, _L1.trig_fire_mode),
          f"{cols['n']} triggers, two columns compared")

    res = [rd1(mon, sym["waveDefTable"] + d * WAVEDEF_SIZE + WD_RESERVED)
           for d in range(WAVE_DEFS)]
    check("A DEFINITION'S BYTE 7 IS RESERVED AND ZERO -- no colour, no firing",
          all(b == 0 for b in res),
          ", ".join(f"def{i}=${b:02x}" for i, b in enumerate(res)))
    for row, d, f, m in zip(rows, cols["def"], cols["firemode"],
                            cols["firemask"]):
        if f or m:
            print(f"       row {row:>4}  definition {d:<3} "
                  f"fire {'AIMED' if f else 'DOWN '} mask %{m:08b}")
    check("the firing mode is on the TRIGGER now",
          len(cols["firemode"]) == cols["n"])
    check("no trigger names a firing mode that does not exist",
          all(f <= TRIG_FIRE_AIMED for f in cols["firemode"]),
          str(list(cols["firemode"])))
    # WHICH appearances are AIMED is authoring. `== [20]` used to be here, and
    # it froze one row of Level 1 as though it were an engine property. What
    # matters is that a mode is never authored onto a formation with no shooter
    # in it, which would be an authored intention the engine silently drops.
    check("every appearance with a firing mode also sends a shooter",
          all(cols["firemask"][i] for i, f in enumerate(cols["firemode"]) if f),
          f"{sum(1 for f in cols['firemode'] if f)} appearance(s) with a mode")

    print("\n=== the eligible-colour pool ===")
    n, pool, bans = pool_of(mon)
    cram = rd1(mon, sym["trnCramValue"])
    want = [0, rd1(mon, 0xD025) & 0x0F, rd1(mon, 0xD026) & 0x0F, cram & 0x07]
    check("the engine latched the four exclusions it was asked to",
          list(bans) == want, f"engine {list(bans)} vs derived {want}")
    distinct = sorted(set(want))
    check("the pool is every colour that is not excluded",
          n == 16 - len(distinct)
          and sorted(pool) == [c for c in range(16) if c not in distinct],
          f"{n} colours: {list(pool)}")
    check("BLACK is not in the pool", 0 not in pool)
    check("shared multicolour 1 ($d025) is not in the pool", want[1] not in pool)
    check("shared multicolour 2 ($d026) is not in the pool", want[2] not in pool)
    check("the terrain's charset colour is not in the pool",
          want[3] not in pool, f"charset colour {want[3]}")
    check("THE PLAYER'S COLOUR IS STILL ELIGIBLE", PLAYER_COL_SHIP in pool)

    # ---- ONE FIXED AND ONE RANDOM APPEARANCE, BUILT ------------------
    # Whether the author has left a fixed appearance in the level today is not
    # something the engine promises. Both modes are installed on a synthetic
    # definition of this file's own, so both are always observed and neither
    # observation can be lost to re-authoring. TWO TRIGGERS ON ONE DEFINITION
    # at the same time, which is also the arrangement the ownership move exists
    # for -- the definition cannot be the thing deciding.
    pkg = synth.Package(mon, sym)
    prog = pkg.straight_then_exit(2, 4)          # a gentle diagonal, any path
    syn_def = pkg.install_definition(count=SYN_COUNT, interval=SYN_INTERVAL,
                                     start_x=80, start_y=48, x_step=24,
                                     y_step=0, heading=0, program=prog)
    pkg.pair_on_one_definition(
        rows=(SYN_ROW_A, SYN_ROW_B), definition=syn_def,
        colours=(SYN_FIXED_COLOUR, COL_RANDOM + SYN_OTHER_COLOUR),
        fire_modes=(TRIG_FIRE_AIMED, TRIG_FIRE_DOWN),
        fire=(0b0001, 0b0001))
    check("a FIXED and a RANDOM appearance were installed on ONE definition",
          rd1(mon, sym["waveTrigColour"] + 0) == SYN_FIXED_COLOUR
          and rd1(mon, sym["waveTrigColour"] + 1) & COL_RANDOM
          and rd1(mon, sym["waveTrigDef"] + 0) == rd1(mon, sym["waveTrigDef"] + 1),
          f"definition {syn_def}: trigger 0 fixed colour {SYN_FIXED_COLOUR}, "
          f"trigger 1 RANDOM")

    print(f"\n=== watching up to {SPAWN_SAMPLES} activations ===")
    spawns = watch_spawns(mon, SPAWN_SAMPLES)
finally:
    if v:
        v.close()

check("enemies were observed being spawned", bool(spawns), f"{len(spawns)} enemies")

by_col = collections.defaultdict(list)
for s in spawns:
    by_col[(s["def"], s["trigcol"])].append(s)

print("\n=== a FIXED appearance gives every member its trigger's colour ===")
bad, fixed_seen = [], []
for (d, tc), rows in sorted(by_col.items()):
    if tc & COL_RANDOM:
        continue
    fixed_seen.append((f"def{d}", tc & COL_MASK, len(rows)))
    for s in rows:
        if s["base"] != tc & COL_MASK or s["logcol"] != tc & COL_MASK:
            bad.append((f"def{d}", tc & COL_MASK, s["base"]))
check("every member of a fixed appearance wore exactly its trigger's colour",
      not bad,
      str(bad[:4]) if bad
      else "; ".join(f"{n}: colour {c}, {k} members" for n, c, k in fixed_seen))
check("a fixed appearance was actually observed", bool(fixed_seen),
      str(fixed_seen))

print("\n=== a RANDOM appearance varies, within the pool ===")
rnd, varied = [], []
for (d, tc), rows in sorted(by_col.items()):
    if not tc & COL_RANDOM:
        continue
    cs = [s["base"] for s in rows]
    rnd += cs
    if len(rows) > 1:
        varied.append((f"def{d}", sorted(set(cs))))
check("a random appearance produced more than one colour among its members",
      any(len(c) > 1 for _n, c in varied),
      "; ".join(f"{n}: {c}" for n, c in varied))
check("every random colour handed out was in the eligible pool",
      all(c in pool for c in rnd), f"{len(rnd)} picks, {sorted(set(rnd))}")
check("no random pick was ever one of the four forbidden colours",
      not [c for c in rnd if c in set(bans)],
      f"forbidden {sorted(set(bans))}, picked {sorted(set(rnd))}")
check("logCol agreed with wmBaseCol at spawn for every enemy",
      all(s["base"] == s["logcol"] for s in spawns))

print("\n=== the firing mode reaching the enemy came from the TRIGGER ===")
armed = [s for s in spawns if s["fire"]]
check("every armed enemy's mode matches its APPEARANCE's latched mode",
      all((s["fire"] == ENEMY_FIRE_AIMED) == (s["trigfire"] == TRIG_FIRE_AIMED)
          for s in armed),
      f"{len(armed)} armed enemies")
aimed_armed = [s for s in armed if s["trigfire"] == TRIG_FIRE_AIMED]
check("the AIMED appearance really did arm its members AIMED",
      bool(aimed_armed)
      and all(s["fire"] == ENEMY_FIRE_AIMED for s in aimed_armed),
      f"{len(aimed_armed)} aimed members")
check("...and no DOWN appearance was given aimed fire",
      all(s["fire"] != ENEMY_FIRE_AIMED
          for s in armed if s["trigfire"] != TRIG_FIRE_AIMED),
      str(sorted({(f"def{s['def']}", s['fire']) for s in armed})))

# ===========================================================================
# LAUNCH 2 -- the colour is chosen once and then stands
# ===========================================================================
print("\n=== chosen once at spawn, stable for the whole life ===")
v = None
frames = []
try:
    v = Vice(PORT + 1, PRG, boot="exact")
    mon = v.mon
    bp = set_bp(mon, sym["gameFrame"])

    def snap():
        return (rd(mon, sym["logActive"], MAX_OBJECTS),
                rd(mon, sym["objType"], MAX_OBJECTS),
                rd(mon, sym["wmBaseCol"], MAX_OBJECTS),
                rd(mon, sym["logCol"], MAX_OBJECTS),
                read16(mon, sym["frameCounter"]))

    frames = step_n(mon, sym["frameCounter"], STABLE_FRAMES, snap)

    # ---- THE FLASH RESTORE, DRIVEN RATHER THAN WAITED FOR ---------------
    # A real hit needs the player to shoot something, which may or may not
    # happen inside any given window -- the earlier version of this file
    # reported "no flash happened" and proved nothing. enemyBaseColour IS the
    # routine enemyFlashTick jumps to when the flash expires, so calling it on
    # a live enemy whose logCol has been forced to the flash colour tests the
    # restore itself rather than the odds of being shot at.
    # WAIT FOR A CROWD, briefly and boundedly: restoring one enemy proves the
    # routine, but several with DIFFERENT colours is what proves it restores
    # each one's own rather than something wave-wide.
    def live_enemies():
        act = rd(mon, sym["logActive"], MAX_OBJECTS)
        typ = rd(mon, sym["objType"], MAX_OBJECTS)
        return [s for s in range(MAX_OBJECTS) if act[s] and typ[s] == TYPE_ENEMY]

    live = live_enemies()
    for _ in range(600):
        if len({rd1(mon, sym["wmBaseCol"] + s) for s in live}) >= 3:
            break
        step_n(mon, sym["frameCounter"], 1, lambda: None)
        live = live_enemies()
    restores = []
    for s in live:
        own = rd1(mon, sym["wmBaseCol"] + s)
        poke(mon, sym["logCol"] + s, HIT_COL_FLASH)
        flashed_to = rd1(mon, sym["logCol"] + s)
        call(mon, sym, "enemyBaseColour", x=s)
        restores.append((own, flashed_to, rd1(mon, sym["logCol"] + s)))
    mon.cmd(f"delete {bp}")
finally:
    if v:
        v.close()

runs, cur = [], {}
for active, types, base, col, fr in frames:
    for s in range(MAX_OBJECTS):
        if active[s] and types[s] == TYPE_ENEMY:
            cur.setdefault(s, []).append((base[s], col[s], fr))
        elif s in cur:
            runs.append(cur.pop(s))
runs += list(cur.values())
runs = [r for r in runs if len(r) >= 8]

check("enemies were watched over many frames", bool(runs),
      f"{len(runs)} lifetimes of 8+ frames over {len(frames)} frames")
moved = [sorted({b for b, _c, _f in r}) for r in runs
         if len({b for b, _c, _f in r}) > 1]
check("NO enemy's stored colour ever changed while it was alive",
      not moved,
      str(moved[:4]) if moved else f"{len(runs)} lifetimes, one colour each")
strays = [(b, c) for r in runs for b, c, _f in r
          if c != b and c != HIT_COL_FLASH and c not in DEATH_COLS]
check("the presented colour was the stored one except while flashing or dying",
      not strays, f"{len(strays)} strays: {strays[:4]}")
check("a flash was applied to every live enemy and then expired",
      bool(restores) and all(f == HIT_COL_FLASH for _o, f, _g in restores),
      f"{len(restores)} enemies flashed")
check("EVERY ONE came back to its OWN colour, not to a wave-wide one",
      all(got == own for own, _f, got in restores),
      "; ".join(f"own {o} -> flash {f} -> {g}" for o, f, g in restores))
check("...and those colours really were different enemies' own",
      len({o for o, _f, _g in restores}) > 1 or len(restores) < 2,
      str(sorted({o for o, _f, _g in restores})))
check("a colour held across many animation frames",
      max((len(r) for r in runs), default=0) >= 40,
      f"longest lifetime {max((len(r) for r in runs), default=0)} frames")

# ===========================================================================
# LAUNCH 3 -- TWO TRIGGERS, ONE DEFINITION, DIFFERENT COLOURS
# ===========================================================================
# THE CLAIM THE WHOLE REFACTOR EXISTS FOR, measured on the machine.
#
# IT USED TO HUNT THE AUTHORED LIST for a definition shared by two non-Dropper
# triggers, and take the first one it found. Level 1 no longer has one -- its
# only shared definition is used by an ordinary trigger and a Dropper -- so the
# hunt returned a pair whose members never both appear, and three checks failed.
# A Dropper is the wrong specimen anyway: dropperLaunch takes it off its wave's
# path the instant it spawns.
#
# The pair is therefore BUILT: one definition, two triggers, two colours, two
# firing modes, two rows the world reaches at once, and an ordinary shooting
# species. Package RAM only.
print("\n=== two triggers on ONE definition, coloured independently ===")
v = None
seen = []
shared_def = None
A_COL, B_COL = SYN_FIXED_COLOUR, SYN_OTHER_COLOUR
try:
    v = Vice(PORT + 2, PRG, boot="exact")
    mon = v.mon
    pkg = synth.Package(mon, sym)
    prog = pkg.straight_then_exit(2, 4)
    shared_def = pkg.install_definition(count=SYN_COUNT, interval=SYN_INTERVAL,
                                        start_x=80, start_y=48, x_step=24,
                                        y_step=0, heading=0, program=prog)
    pkg.pair_on_one_definition(
        rows=(SYN_ROW_A, SYN_ROW_B), definition=shared_def,
        colours=(A_COL, B_COL),
        fire_modes=(TRIG_FIRE_AIMED, TRIG_FIRE_DOWN),
        # BOTH NEED A SHOOTER before a mode can matter, so member 0 of each is
        # given the mask bit.
        fire=(0b0001, 0b0001))
    check(f"two triggers on definition {shared_def} set to different colours",
          (rd1(mon, sym["waveTrigColour"] + 0),
           rd1(mon, sym["waveTrigColour"] + 1)) == (A_COL, B_COL),
          f"rows {SYN_ROW_A} and {SYN_ROW_B}")
    check("...and to different firing modes",
          (rd1(mon, sym["waveTrigFireMode"] + 0),
           rd1(mon, sym["waveTrigFireMode"] + 1))
          == (TRIG_FIRE_AIMED, TRIG_FIRE_DOWN))
    check("...and the definition they share carries neither, to conflict with",
          rd1(mon, sym["waveDefTable"] + shared_def * WAVEDEF_SIZE
              + WD_RESERVED) == 0)

    seen = watch_spawns(mon, SPAWN_SAMPLES)
finally:
    if v:
        v.close()

mine = collections.defaultdict(set)
fires = collections.defaultdict(set)
for s in seen:
    if s["def"] == shared_def and not s["trigcol"] & COL_RANDOM:
        mine[s["trigcol"]].add(s["base"])
        fires[s["trigcol"]].add((s["trigfire"], s["fire"]))
check("both appearances of the shared definition were observed",
      set(mine) == {A_COL, B_COL}, f"trigger colour bytes seen: {sorted(mine)}")
check("ONE DEFINITION PRODUCED ENEMIES OF TWO DIFFERENT COLOURS",
      mine.get(A_COL) == {A_COL} and mine.get(B_COL) == {B_COL},
      "; ".join(f"trigger colour {k} -> enemies {sorted(g)}"
                for k, g in sorted(mine.items())))
armed_a = {f for tf, f in fires.get(A_COL, set()) if f}
armed_b = {f for tf, f in fires.get(B_COL, set()) if f}
check("...AND ENEMIES THAT ATTACK TWO DIFFERENT WAYS",
      armed_a == {ENEMY_FIRE_AIMED} and armed_b and ENEMY_FIRE_AIMED not in armed_b,
      f"appearance A armed {sorted(armed_a)} (2=AIMED), "
      f"appearance B armed {sorted(armed_b)} (1=DOWN)")

sys.exit(report(__name__))
