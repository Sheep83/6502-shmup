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

Constraint #4: the machine is free-running production code. The first two
launches poke NOTHING -- the authored Level 1 already contains a fixed
appearance and eleven random ones. The third pokes only the trigger colour
column of the loaded package, which is ordinary authored data and is the
technique tests/test_aimed_velocity.py already uses on the firing mode.

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

sym = symbols(SYM)

PORT = 6615
MAX_OBJECTS, WAVE_SLOTS = 16, 2
TYPE_ENEMY = 1
ENEMY_FIRE_AIMED = 2                    # src/enemy.asm
WAVEDEF_SIZE, WD_RESERVED = 10, 7
COL_MASK, COL_RANDOM = 0x0F, 0x10       # the TRIGGER colour byte
TRIG_FIRE_DOWN, TRIG_FIRE_AIMED = 0, 1  # the TRIGGER firing mode byte
WAVE_DEFS, WAVE_TRIGGERS = 7, 12        # src/level1/wave_encounters.asm
PLAYER_COL_SHIP = 14                    # src/player.asm

HIT_COL_FLASH = 4                       # src/collision.asm
DEATH_COLS = (7, 8, 2)

DEF_NAMES = ("sweep", "s", "linger", "loop", "loop_5", "dive_4", "up_n_over")
TRIG_ROWS = (20, 52, 90, 126, 160, 205, 260, 310, 350, 450, 550, 665)

SPAWN_SAMPLES = 150
STABLE_FRAMES = 420

REG_X = re.compile(r"^\.;[0-9a-f]{4}\s+[0-9a-f]{2}\s+([0-9a-f]{2})", re.M)


def pool_of(mon):
    n = rd1(mon, sym["wvColCount"])
    return n, rd(mon, sym["wvColPool"], 16)[:n], rd(mon, sym["wvColBan"], 4)


def trigger_columns(mon):
    """The authored trigger list as the loaded package holds it."""
    return {
        "def": rd(mon, sym["waveTrigDef"], WAVE_TRIGGERS),
        "colour": rd(mon, sym["waveTrigColour"], WAVE_TRIGGERS),
        "firemode": rd(mon, sym["waveTrigFireMode"], WAVE_TRIGGERS),
        "firemask": rd(mon, sym["waveTrigFire"], WAVE_TRIGGERS),
        "species": rd(mon, sym["waveTrigSpecies"], WAVE_TRIGGERS),
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
    for row, d, c in zip(TRIG_ROWS, cols["def"], cols["colour"]):
        mode = "RANDOM" if c & COL_RANDOM else "fixed "
        print(f"       row {row:>4}  {DEF_NAMES[d]:<10} ${c:02x}  {mode} "
              f"colour {c & COL_MASK}")
    check("every authored trigger carries a colour byte",
          len(cols["colour"]) == WAVE_TRIGGERS)
    check("no trigger colour byte sets a bit outside colour and the flag",
          all(c <= COL_MASK + COL_RANDOM for c in cols["colour"]),
          str([hex(c) for c in cols["colour"]]))

    res = [rd1(mon, sym["waveDefTable"] + d * WAVEDEF_SIZE + WD_RESERVED)
           for d in range(WAVE_DEFS)]
    check("A DEFINITION'S BYTE 7 IS RESERVED AND ZERO -- no colour, no firing",
          all(b == 0 for b in res),
          ", ".join(f"{n}=${b:02x}" for n, b in zip(DEF_NAMES, res)))
    for row, d, f, m in zip(TRIG_ROWS, cols["def"], cols["firemode"],
                            cols["firemask"]):
        if f or m:
            print(f"       row {row:>4}  {DEF_NAMES[d]:<10} "
                  f"fire {'AIMED' if f else 'DOWN '} mask %{m:08b}")
    check("the firing mode is on the TRIGGER now",
          len(cols["firemode"]) == WAVE_TRIGGERS)
    check("no trigger names a firing mode that does not exist",
          all(f <= TRIG_FIRE_AIMED for f in cols["firemode"]),
          str(list(cols["firemode"])))
    check("...and the AIMED appearance is the one the author authored",
          [TRIG_ROWS[i] for i, f in enumerate(cols["firemode"]) if f] == [20],
          str([TRIG_ROWS[i] for i, f in enumerate(cols["firemode"]) if f]))
    check("every appearance with a firing mode also sends a shooter",
          all(cols["firemask"][i] for i, f in enumerate(cols["firemode"]) if f))

    # THE SAME DEFINITION AT SEVERAL ROWS. This is the arrangement the move was
    # made for, and the authored level already has it.
    shared = collections.defaultdict(list)
    for i, d in enumerate(cols["def"]):
        shared[d].append(i)
    reused = {DEF_NAMES[d]: [TRIG_ROWS[i] for i in g]
              for d, g in shared.items() if len(g) > 1}
    check("the authored level really does reuse definitions across triggers",
          bool(reused), "; ".join(f"{k} at {g}" for k, g in reused.items()))

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
    fixed_seen.append((DEF_NAMES[d], tc & COL_MASK, len(rows)))
    for s in rows:
        if s["base"] != tc & COL_MASK or s["logcol"] != tc & COL_MASK:
            bad.append((DEF_NAMES[d], tc & COL_MASK, s["base"]))
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
        varied.append((DEF_NAMES[d], sorted(set(cs))))
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
      str(sorted({(DEF_NAMES[s['def']], s['fire']) for s in armed})))

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
# THE CLAIM THE WHOLE REFACTOR EXISTS FOR, measured on the machine. The
# authored level leaves every `loop` trigger random, so two of them are given
# different FIXED colours here -- a poke of the package's own trigger colour
# column, which is authored data and nothing else.
print("\n=== two triggers on ONE definition, coloured independently ===")
v = None
seen = []
shared_def = None
try:
    v = Vice(PORT + 2, PRG, boot="exact")
    mon = v.mon
    cols = trigger_columns(mon)
    # A SHARED DEFINITION WHOSE TRIGGERS FIELD ORDINARY SHOOTERS. Level 1's
    # `loop` is shared four ways but every one of them carries a DROPPER, and a
    # Dropper is taken off its wave's path by dropperLaunch the instant it
    # spawns -- so it is the wrong specimen for a firing comparison. Ring
    # appearances are the ordinary case and the one worth proving.
    SPECIES_DROPPER = 8
    groups = collections.defaultdict(list)
    for i, d in enumerate(cols["def"]):
        if cols["species"][i] != SPECIES_DROPPER:
            groups[d].append(i)
    shared_def, idx = next((k, g) for k, g in sorted(groups.items())
                           if len(g) > 1)
    a, b = idx[0], idx[1]
    poke(mon, sym["waveTrigColour"] + a, 3)          # cyan, fixed
    poke(mon, sym["waveTrigColour"] + b, 7)          # yellow, fixed
    # ...AND DIFFERENT FIRING, from the same definition. Both need a shooter
    # before a mode can matter, so member 0 of each is given the mask bit.
    poke(mon, sym["waveTrigFire"] + a, 0x01)
    poke(mon, sym["waveTrigFire"] + b, 0x01)
    poke(mon, sym["waveTrigFireMode"] + a, TRIG_FIRE_AIMED)
    poke(mon, sym["waveTrigFireMode"] + b, TRIG_FIRE_DOWN)
    check(f"two triggers on {DEF_NAMES[shared_def]!r} set to different colours",
          (rd1(mon, sym["waveTrigColour"] + a),
           rd1(mon, sym["waveTrigColour"] + b)) == (3, 7),
          f"rows {TRIG_ROWS[a]} and {TRIG_ROWS[b]}")
    check("...and to different firing modes",
          (rd1(mon, sym["waveTrigFireMode"] + a),
           rd1(mon, sym["waveTrigFireMode"] + b))
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
      set(mine) == {3, 7}, f"trigger colour bytes seen: {sorted(mine)}")
check("ONE DEFINITION PRODUCED ENEMIES OF TWO DIFFERENT COLOURS",
      mine.get(3) == {3} and mine.get(7) == {7},
      "; ".join(f"trigger colour {k} -> enemies {sorted(g)}"
                for k, g in sorted(mine.items())))
armed_a = {f for tf, f in fires.get(3, set()) if f}
armed_b = {f for tf, f in fires.get(7, set()) if f}
check("...AND ENEMIES THAT ATTACK TWO DIFFERENT WAYS",
      armed_a == {ENEMY_FIRE_AIMED} and armed_b and ENEMY_FIRE_AIMED not in armed_b,
      f"appearance A armed {sorted(armed_a)} (2=AIMED), "
      f"appearance B armed {sorted(armed_b)} (1=DOWN)")

sys.exit(report(__name__))
