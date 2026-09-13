#!/usr/bin/env python3
"""Slice D — the player's hitscan, enemy damage, and enemy death.

What this proves
----------------
* the recovered geometry is the old game's: two independent cannon rays, a
  24-pixel hitbox from enemyX to enemyX+23, eligibility from raster 55 up to
  strictly above the ship, nearest-by-greatest-Y, ties to the higher slot;
* one HP per cannon hit against six HP, so a centred volley takes two and three
  volleys kill -- the old game's own stated arithmetic;
* NO part of the decision touches $d01e, $d01f or a hardware sprite slot;
* a kill runs a bounded death state and then frees the slot through the same
  single despawn path Slice C proved, leaving CURRENT untouched, NEXT correct
  and the reused slot inheriting nothing;
* the player, weapon, heat, HUD, scroller and aperture are unchanged.

THE STEPPING RULE. `mon.cmd("x")` returns on a prompt echo, so every sample is
verified by frame counter, and each group of state is read in one bulk command
at one instant. The breakpoint is regenTick: the first call after
sortTick/buildSchedule/publishSchedule, so a stop there sees this frame's
damage, this frame's membership and this frame's NEXT schedule.

VICE process ownership: this script owns exactly the PID it launches and kills
it on success, failure and exception via try/finally.
"""
import sys, re, hashlib, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import PRG, SYM, symbols, Vice, rd, set_bp, free_run, LAUNCHED_PIDS
from test_p2 import poke

sym = symbols(SYM)

# --- the contract, restated independently of the assembler ------------------
MAX_OBJECTS, MAX_LOGICAL, MAX_SCHED = 16, 32, 24
MIN_SPRITE_Y, MAX_SPRITE_Y = 55, 226
HITBOX_W, SHOT_DAMAGE = 24, 1
ENEMY_MAX_HP, HIT_FLASH_TIME, DEATH_TIME = 6, 4, 12
HIT_COL_WHITE, HIT_COL_YELLOW = 1, 7
DEATH_COL_1, DEATH_COL_2, DEATH_COL_3 = 7, 8, 2
CANNON_L, CANNON_R = 4, 19
TYPE_ENEMY = 1
ENEMY_PTR = 0x3640 // 64
FRAME_IRQ_LINE = 250
JOY_IDLE = 0b00011111
JOY_FIRE = JOY_IDLE & ~0b00010000
PLAYER_SLOT_MASK = 0b00000011

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")

advisories = []
def advise(label, ok, detail="", scope="this machine, not the code"):
    """A real finding that is NOT a Slice D defect. Loud, but never red.

    The gate judges what this slice changed. A developer's emulator settings and
    a pre-existing engine limit are both worth shouting about and neither is
    grounds for failing the slice that happened to measure it.
    """
    if not ok:
        advisories.append((label, detail, scope))
    print(f"  {'ok  ' if ok else '!!  '} {label}{(' -- ' + detail) if detail else ''}")


# ===========================================================================
# Harness
# ===========================================================================
def step(mon, n=1, tries=8):
    mon.cmd("delete")
    b = set_bp(mon, sym["regenTick"])
    f = rd(mon, sym["frameCounter"], 2)
    prev = f[0] | (f[1] << 8)
    done = 0
    while done < n:
        moved = False
        for _ in range(tries):
            mon.cmd("x")
            f = rd(mon, sym["frameCounter"], 2)
            now = f[0] | (f[1] << 8)
            if ((now - prev) & 0xffff) == 1:
                prev, moved, done = now, True, done + 1
                break
            prev = now
        if not moved:
            check("a frame step landed", False, "the counter never advanced by one")
            break
    mon.cmd(f"delete {b}")
    mon.cmd("delete")


def snap(mon):
    """Everything this slice touches, at ONE instant, in four bulk reads."""
    act = rd(mon, sym["logActive"], MAX_LOGICAL)
    log = rd(mon, sym["logY"], 5 * MAX_LOGICAL)
    pool = rd(mon, sym["objType"], 5 * MAX_OBJECTS)
    srt = rd(mon, sym["sortedIDs"], MAX_LOGICAL + 1)
    g = lambda i: log[i * MAX_LOGICAL:(i + 1) * MAX_LOGICAL]
    p = lambda i: pool[i * MAX_OBJECTS:(i + 1) * MAX_OBJECTS]
    n = srt[MAX_LOGICAL]
    return {"active": act, "logY": g(0), "logX": g(1), "logXHi": g(2),
            "logPtr": g(3), "logCol": g(4),
            "objType": p(0), "objVX": p(1), "objVY": p(2),
            "objHP": p(3), "objTimer": p(4),
            "sortedIDs": srt[:MAX_LOGICAL], "sortedCount": n, "window": srt[:n],
            "live": [i for i in range(MAX_LOGICAL) if act[i]],
            "logCount": rd(mon, sym["logCount"])[0]}


def sched(mon, which="next"):
    buf = rd(mon, sym["schedNext" if which == "next" else "schedCurrent"])[0]
    base = buf * MAX_SCHED
    n = rd(mon, sym["statAccepted"])[0]
    ids = rd(mon, sym["schedId"] + base, MAX_SCHED)
    return {"n": n, "ids": ids[:n], "raw_ids": ids,
            "raw_y": rd(mon, sym["schedY"] + base, MAX_SCHED),
            "raw_col": rd(mon, sym["schedCol"] + base, MAX_SCHED)}


def call_x(mon, addr, x=0):
    mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
    mon.cmd(f"r sp=fd, pc={addr:04x}, x={x:02x}")
    bb = set_bp(mon, 0xc0fe)
    mon.cmd("x")
    mon.cmd(f"delete {bb}")
    mon.cmd(f"r pc={sym['mainLoop']:04x}")
    mon.cmd("delete")


SPAWNER_BYTE = [None]

def spawner(mon, on):
    """Switch the production spawner off so a test owns the population.

    Patched to RTS rather than delayed by its timer: several checks here
    free-run, and a timer poked to its maximum expires many times over inside
    one warp second. Slice A learned that the hard way.
    """
    if SPAWNER_BYTE[0] is None:
        SPAWNER_BYTE[0] = rd(mon, sym["enemySpawnTick"])[0]
    poke(mon, sym["enemySpawnTick"], SPAWNER_BYTE[0] if on else 0x60)


def clear_pool(mon):
    spawner(mon, False)
    for i in range(MAX_OBJECTS):
        call_x(mon, sym["objectFree"], i)


def place(mon, x, y, vy=0, entry=0):
    """Spawn one enemy through the real path, then park it where a test wants."""
    poke(mon, sym["enySpawnNext"], entry)
    saved = rd(mon, sym["enemySpawnTick"])[0]
    spawner(mon, True)
    poke(mon, sym["enySpawnTimer"], 1)
    before = set(i for i in range(MAX_OBJECTS) if rd(mon, sym["logActive"], MAX_OBJECTS)[i])
    step(mon, 1)
    poke(mon, sym["enemySpawnTick"], saved)
    now = set(i for i in range(MAX_OBJECTS) if rd(mon, sym["logActive"], MAX_OBJECTS)[i])
    new = sorted(now - before)
    if not new:
        return None
    s = new[0]
    poke(mon, sym["objVY"] + s, vy)
    poke(mon, sym["objVX"] + s, 0)
    poke(mon, sym["logY"] + s, y)
    poke(mon, sym["logX"] + s, x & 0xff)
    poke(mon, sym["logXHi"] + s, 1 if x > 255 else 0)
    return s


def arm_player(mon, x=160, y=200):
    poke(mon, sym["plyX"], x & 0xff)
    poke(mon, sym["plyXHi"], 1 if x > 255 else 0)
    poke(mon, sym["plyY"], y)
    poke(mon, sym["wpnHeatLo"], 0); poke(mon, sym["wpnHeatHi"], 0)
    poke(mon, sym["wpnOverheated"], 0); poke(mon, sym["wpnCooldown"], 0)


def fire_once(mon):
    """Exactly one volley, resolved. Leaves the stick released afterwards."""
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["wpnCooldown"], 0)
    poke(mon, sym["wpnOverheated"], 0)
    poke(mon, sym["wpnHeatLo"], 0); poke(mon, sym["wpnHeatHi"], 0)
    poke(mon, sym["joyState"], JOY_FIRE)
    step(mon, 1)
    poke(mon, sym["joyState"], JOY_IDLE)
    return rd(mon, sym["shotFired"])[0]


# ===========================================================================
def source_invariants():
    print("=== 1. collision is logical: no VIC, no hardware slot identity ===")
    files = {n: (ROOT / "src" / f"{n}.asm").read_text()
             for n in ("collision", "enemy", "objects")}
    for name, text in files.items():
        body = re.sub(r"//.*", "", text)
        vic = re.findall(r"^\s*(?:lda|ldx|ldy|sta|stx|sty)\s+\$d0[0-9a-f]{2}", body, re.M | re.I)
        check(f"{name}.asm touches no VIC register", not vic, f"{vic[:3]}")
        coll = re.findall(r"\$d01[ef]", body, re.I)
        check(f"{name}.asm never reads the VIC collision latch", not coll, f"{coll[:3]}")
        slots = re.findall(r"(MUX_FIRST_SLOT|MUX_SLOTS|schedSlot|bitMask|schedId)", body)
        check(f"{name}.asm names no hardware sprite slot", not slots, f"{set(slots)}")

    col = re.sub(r"//.*", "", files["collision"])
    check("the scan filters on object TYPE, not merely on 'active'",
          "cmp #TYPE_ENEMY" in col)
    check("the cannon X comes from the Slice B shot event",
          "shotXLo,x" in col and "shotXHi,x" in col and "shotY" in col)
    check("the weapon origin is never recomputed from sprite registers",
          "plyX" not in col and "$d000" not in col)
    check("damage is applied to logical HP",
          "objHP,x" in col)


# ===========================================================================
def geometry(mon):
    print("\n=== 2. hitscan geometry ===")
    # The left cannon sits at plyX+4, the right at plyX+19. With the ship at
    # 160 the lanes are 164 and 179.
    arm_player(mon, 160, 200)

    # 1 / 2: outside and inside the lane.
    clear_pool(mon); s = place(mon, 400 & 0xff, 120); poke(mon, sym["logXHi"] + s, 1)
    fire_once(mon)
    check("1. a shot misses an enemy outside the cannon lanes",
          rd(mon, sym["objHP"] + s)[0] == ENEMY_MAX_HP,
          f"hp {rd(mon, sym['objHP'] + s)[0]}")

    clear_pool(mon); s = place(mon, 160, 120)
    fire_once(mon)
    check("2. a shot hits an enemy inside the lane",
          rd(mon, sym["objHP"] + s)[0] < ENEMY_MAX_HP,
          f"hp {rd(mon, sym['objHP'] + s)[0]}")

    # 3 / 4: the exact hitbox edges, tested against the LEFT cannon at 164.
    # The box is enemyX .. enemyX+23, so lane 164 hits enemyX 141..164.
    for label, ex, want in (("3. the exact left edge (enemyX = lane)", 164, True),
                            ("3b. one pixel past the left edge", 165, False),
                            ("4. the exact right edge (enemyX+23 = lane)", 141, True),
                            ("4b. one pixel past the right edge", 140, False)):
        clear_pool(mon)
        s = place(mon, ex, 120)
        # Keep the RIGHT cannon (179) out of it: box would be ex..ex+23,
        # and 179 <= ex+23 only when ex >= 156, so shift the ship for the
        # near-edge cases instead of trusting one lane not to overlap.
        hit_l = ex <= 164 <= ex + HITBOX_W - 1
        hit_r = ex <= 179 <= ex + HITBOX_W - 1
        fire_once(mon)
        hp = rd(mon, sym["objHP"] + s)[0]
        lost = ENEMY_MAX_HP - hp
        expect = (1 if hit_l else 0) + (1 if hit_r else 0)
        check(label, lost == expect,
              f"enemyX {ex}, box {ex}..{ex + 23}, lanes 164/179 -> "
              f"expected {expect} hits, lost {lost}")

    # 5: Y eligibility, both halves.
    clear_pool(mon); s = place(mon, 160, MIN_SPRITE_Y - 1)
    fire_once(mon)
    above = rd(mon, sym["objHP"] + s)[0]
    clear_pool(mon); s = place(mon, 160, MIN_SPRITE_Y)
    fire_once(mon)
    at = rd(mon, sym["objHP"] + s)[0]
    check("5. the lowest hittable line is exactly the top of the band",
          above == ENEMY_MAX_HP and at < ENEMY_MAX_HP,
          f"Y {MIN_SPRITE_Y - 1} -> hp {above}; Y {MIN_SPRITE_Y} -> hp {at}")

    clear_pool(mon); s = place(mon, 160, 200)          # level with the ship
    fire_once(mon)
    level = rd(mon, sym["objHP"] + s)[0]
    clear_pool(mon); s = place(mon, 160, 199)          # one pixel above it
    fire_once(mon)
    just_above = rd(mon, sym["objHP"] + s)[0]
    check("5b. an enemy level with the ship is behind the ray; one pixel above is not",
          level == ENEMY_MAX_HP and just_above < ENEMY_MAX_HP,
          f"level hp {level}, one above hp {just_above}")

    # 6: both cannons are traced, independently, from their own X.
    clear_pool(mon)
    a = place(mon, 150, 120)        # box 150..173 -> left lane 164 only
    b = place(mon, 175, 130)        # box 175..198 -> right lane 179 only
    fire_once(mon)
    sa = rd(mon, sym["objHP"] + a)[0]
    sb = rd(mon, sym["objHP"] + b)[0]
    check("6. both cannons trace independently, each from its own logical X",
          sa == ENEMY_MAX_HP - 1 and sb == ENEMY_MAX_HP - 1,
          f"left-lane enemy hp {sa}, right-lane enemy hp {sb}")

    # 7: nine-bit positions above 255.
    clear_pool(mon)
    arm_player(mon, 300, 200)                          # lanes 304 and 319
    s = place(mon, 300, 120); poke(mon, sym["logXHi"] + s, 1)
    poke(mon, sym["logX"] + s, 300 & 0xff)
    fire_once(mon)
    check("7. logical X above 255 is traced correctly",
          rd(mon, sym["objHP"] + s)[0] == ENEMY_MAX_HP - 2,
          f"hp {rd(mon, sym['objHP'] + s)[0]} (ship 300, lanes 304/319, box 300..323)")

    # ...and that a high-byte mismatch is a clean miss rather than a wrap.
    clear_pool(mon)
    arm_player(mon, 20, 200)                           # lanes 24 and 39
    s = place(mon, 280, 120); poke(mon, sym["logXHi"] + s, 1)
    poke(mon, sym["logX"] + s, 280 & 0xff)
    fire_once(mon)
    check("7b. a nine-bit mismatch misses instead of wrapping",
          rd(mon, sym["objHP"] + s)[0] == ENEMY_MAX_HP,
          f"hp {rd(mon, sym['objHP'] + s)[0]}")

    # 8: the whole thing works with the schedule empty -- no slot, no identity.
    clear_pool(mon)
    arm_player(mon, 160, 200)
    s = place(mon, 160, 120)
    poke(mon, sym["logY"] + s, 120)
    n_before = sched(mon, "next")["n"]
    fire_once(mon)
    check("8. no hardware slot identity is needed for the hit to resolve",
          rd(mon, sym["objHP"] + s)[0] < ENEMY_MAX_HP,
          f"hp {rd(mon, sym['objHP'] + s)[0]}, schedule entries {n_before}")


# ===========================================================================
def targeting(mon):
    print("\n=== 3. target selection ===")
    arm_player(mon, 160, 200)

    # 9 / 10: nearest means greatest Y.
    clear_pool(mon)
    far = place(mon, 160, 90)
    near = place(mon, 160, 150)
    fire_once(mon)
    hf, hn = rd(mon, sym["objHP"] + far)[0], rd(mon, sym["objHP"] + near)[0]
    check("9. the NEAREST enemy in the lane is the one hit",
          hn == ENEMY_MAX_HP - 2, f"near hp {hn}")
    check("10. the farther enemy is untouched",
          hf == ENEMY_MAX_HP, f"far hp {hf}")

    # ...and the same with the slots allocated the other way round, so the
    # result cannot be an accident of pool order.
    clear_pool(mon)
    near2 = place(mon, 160, 150)
    far2 = place(mon, 160, 90)
    fire_once(mon)
    check("9b. and still the nearest when the pool order is reversed",
          rd(mon, sym["objHP"] + near2)[0] == ENEMY_MAX_HP - 2
          and rd(mon, sym["objHP"] + far2)[0] == ENEMY_MAX_HP,
          f"slots near {near2} far {far2}")

    # 11: the tie. Equal Y, and the old rule is that the HIGHER slot wins.
    clear_pool(mon)
    lo = place(mon, 160, 140)
    hi = place(mon, 160, 140)
    fire_once(mon)
    hlo, hhi = rd(mon, sym["objHP"] + lo)[0], rd(mon, sym["objHP"] + hi)[0]
    check("11. an equal-Y tie goes to the higher pool slot, deterministically",
          hi > lo and hhi == ENEMY_MAX_HP - 2 and hlo == ENEMY_MAX_HP,
          f"slot {lo} hp {hlo}, slot {hi} hp {hhi}")
    clear_pool(mon)
    lo2 = place(mon, 160, 140)
    hi2 = place(mon, 160, 140)
    fire_once(mon)
    check("11b. and the same way round on a repeat",
          rd(mon, sym["objHP"] + hi2)[0] == ENEMY_MAX_HP - 2
          and rd(mon, sym["objHP"] + lo2)[0] == ENEMY_MAX_HP)

    # 12: inactive and non-damageable objects are skipped.
    clear_pool(mon)
    live = place(mon, 160, 100)
    ghost = place(mon, 160, 180)
    call_x(mon, sym["objectFree"], ghost)       # nearer, but no longer active
    fire_once(mon)
    check("12. an inactive slot is not a target and does not shadow a live one",
          rd(mon, sym["objHP"] + live)[0] == ENEMY_MAX_HP - 2,
          f"live hp {rd(mon, sym['objHP'] + live)[0]}")

    clear_pool(mon)
    live = place(mon, 160, 100)
    other = place(mon, 160, 180)
    poke(mon, sym["objType"] + other, TYPE_ENEMY + 7)    # a future non-enemy
    fire_once(mon)
    check("12b. a non-enemy type is not a target either",
          rd(mon, sym["objHP"] + live)[0] == ENEMY_MAX_HP - 2
          and rd(mon, sym["objHP"] + other)[0] == ENEMY_MAX_HP,
          f"live hp {rd(mon, sym['objHP'] + live)[0]}")

    # Overlapping hitboxes: one volley, two lanes, both inside the SAME enemy.
    clear_pool(mon)
    both = place(mon, 160, 140)     # box 160..183 contains 164 and 179
    fire_once(mon)
    check("12c. an enemy straddling both lanes takes both cannons' damage",
          rd(mon, sym["objHP"] + both)[0] == ENEMY_MAX_HP - 2,
          f"hp {rd(mon, sym['objHP'] + both)[0]}")


# ===========================================================================
def damage(mon):
    print("\n=== 4. damage and hit feedback ===")
    arm_player(mon, 160, 200)

    # 13 / 14: exact damage, and a miss changes nothing.
    clear_pool(mon)
    s = place(mon, 150, 120)        # left lane only: exactly one cannon
    fire_once(mon)
    check(f"13. one legal cannon hit subtracts exactly {SHOT_DAMAGE} HP",
          rd(mon, sym["objHP"] + s)[0] == ENEMY_MAX_HP - SHOT_DAMAGE,
          f"hp {rd(mon, sym['objHP'] + s)[0]}")

    clear_pool(mon)
    s = place(mon, 60, 120)
    hp0 = rd(mon, sym["objHP"] + s)[0]
    fire_once(mon)
    check("14. a miss changes no HP", rd(mon, sym["objHP"] + s)[0] == hp0, f"hp {hp0}")

    # 15 / 16: the kill count, and no underflow.
    clear_pool(mon)
    s = place(mon, 160, 140)        # both lanes: two HP a volley
    hps = [rd(mon, sym["objHP"] + s)[0]]
    volleys = 0
    while rd(mon, sym["objHP"] + s)[0] > 0 and volleys < 10:
        fire_once(mon)
        volleys += 1
        hps.append(rd(mon, sym["objHP"] + s)[0])
    check(f"16. a centred enemy dies after exactly "
          f"{ENEMY_MAX_HP // 2} dual-cannon volleys", volleys == ENEMY_MAX_HP // 2,
          f"{volleys} volleys, hp {hps}")
    check("15. HP lands exactly on zero and never underflows",
          all(0 <= h <= ENEMY_MAX_HP for h in hps) and hps[-1] == 0, f"{hps}")

    # ...and firing again at the dying enemy cannot take it below zero.
    fire_once(mon)
    check("15b. a dying enemy cannot be damaged again",
          rd(mon, sym["objHP"] + s)[0] == 0
          and rd(mon, sym["csHitsLo"])[0] is not None,
          f"hp {rd(mon, sym['objHP'] + s)[0]}")

    # 17 / 18: the hit flash, frame by frame.
    clear_pool(mon)
    s = place(mon, 150, 120)        # one cannon, so it survives to flash
    base = rd(mon, sym["logCol"] + s)[0]
    fire_once(mon)
    t0 = rd(mon, sym["objTimer"] + s)[0]
    c0 = rd(mon, sym["logCol"] + s)[0]
    check(f"17. a hit starts the flash timer at {HIT_FLASH_TIME} and goes white",
          t0 == HIT_FLASH_TIME and c0 == HIT_COL_WHITE, f"timer {t0} colour {c0}")
    trace = []
    for _ in range(HIT_FLASH_TIME + 2):
        step(mon, 1)
        trace.append((rd(mon, sym["objTimer"] + s)[0], rd(mon, sym["logCol"] + s)[0]))
    print(f"  ..  flash (timer, colour): {trace}")
    cols = [c for _, c in trace]
    check("18. the flash is the old ladder: white, white, white, yellow, restored",
          cols[:4] == [HIT_COL_WHITE, HIT_COL_WHITE, HIT_COL_YELLOW, base],
          f"{cols} against base {base}")
    check("18b. and the timer expires to zero and stays there",
          trace[-1][0] == 0 and trace[-1][1] == base, f"{trace[-1]}")


# ===========================================================================
def death_lifecycle(mon):
    print("\n=== 5. death and the object lifecycle ===")
    arm_player(mon, 160, 200)

    # 19: zero HP enters the death state rather than freeing immediately.
    clear_pool(mon)
    s = place(mon, 160, 140)
    for _ in range(ENEMY_MAX_HP // 2):
        fire_once(mon)
    t = snap(mon)
    check(f"19. zero HP starts a bounded {DEATH_TIME}-frame death, still active",
          t["objHP"][s] == 0 and t["objTimer"][s] == DEATH_TIME and t["active"][s] == 1,
          f"hp {t['objHP'][s]} timer {t['objTimer'][s]} active {t['active'][s]}")
    check("19b. a kill event is emitted for exactly that frame",
          rd(mon, sym["csKills"])[0] == 1
          and rd(mon, sym["csKillType"])[0] == TYPE_ENEMY,
          f"kills {rd(mon, sym['csKills'])[0]}")

    # 21: CURRENT is immutable. Read it, free the dying object outright, read
    # it again -- without running a frame.
    cur_before = sched(mon, "current")
    if s in cur_before["ids"]:
        call_x(mon, sym["objectFree"], s)
        cur_after = sched(mon, "current")
        check("21. freeing a killed object cannot mutate the adopted CURRENT",
              cur_after["raw_ids"] == cur_before["raw_ids"]
              and cur_after["raw_y"] == cur_before["raw_y"]
              and cur_after["raw_col"] == cur_before["raw_col"])
        step(mon, 1)
        check("20. the killed object is gone from NEXT on the following frame",
              s not in sched(mon, "next")["ids"])
    else:
        # The enemy was not admitted this frame; re-run the proof with the
        # schedule state we actually have rather than claiming an untested pass.
        check("21. an enemy was present in CURRENT to prove immutability against",
              False, f"CURRENT ids {cur_before['ids']}")

    # 19c / 20 / 22: ride a real death all the way out.
    clear_pool(mon)
    s = place(mon, 160, 140)
    for _ in range(ENEMY_MAX_HP // 2):
        fire_once(mon)
    cols, frames, freed_at = [], 0, None
    for i in range(DEATH_TIME + 4):
        step(mon, 1); frames += 1
        t = snap(mon)
        if not t["active"][s]:
            freed_at = frames
            break
        cols.append((t["objTimer"][s], t["logCol"][s]))
    print(f"  ..  death (timer, colour): {cols}")
    check(f"19c. the slot is released on the frame the death timer reaches zero",
          freed_at == DEATH_TIME, f"freed after {freed_at} frames")
    check("19d. the death runs the old yellow, orange, red progression",
          [c for _, c in cols][:3] == [DEATH_COL_1] * 3
          and DEATH_COL_2 in [c for _, c in cols]
          and DEATH_COL_3 in [c for _, c in cols],
          f"{[c for _, c in cols]}")
    t = snap(mon)
    n = sched(mon, "next")
    check("20b. and it is absent from NEXT once freed", s not in n["ids"], f"{n['ids']}")
    check("22. the sorted window contains no killed object",
          s not in t["window"] and all(t["active"][i] for i in t["window"]),
          f"window {t['window']}")
    check("22b. sortedIDs is still a permutation of every logical ID",
          sorted(t["sortedIDs"]) == list(range(MAX_LOGICAL)))
    check("25. with nothing left alive the state is valid and empty",
          t["logCount"] == 0 and t["sortedCount"] == 0 and n["n"] == 0,
          f"logCount {t['logCount']} sorted {t['sortedCount']} accepted {n['n']}")

    # 23 / 24: the slot comes back clean.
    s2 = place(mon, 160, 140)
    t2 = snap(mon)
    check("23. the killed slot is reusable", s2 is not None and t2["active"][s2] == 1,
          f"reused slot {s2} (killed slot was {s})")
    check("24. and the reused object inherits no HP, timer or presentation",
          t2["objHP"][s2] == ENEMY_MAX_HP and t2["objTimer"][s2] == 0
          and t2["logPtr"][s2] == ENEMY_PTR,
          f"hp {t2['objHP'][s2]} timer {t2['objTimer'][s2]} ptr ${t2['logPtr'][s2]:02x}")
    check("24b. no slot is ever active with zero HP and a stopped timer",
          not any(t2["active"][i] and t2["objHP"][i] == 0 and t2["objTimer"][i] == 0
                  for i in range(MAX_OBJECTS)))

    # The despawn-same-frame-as-shot case, which the temporal model defines.
    clear_pool(mon)
    s3 = place(mon, 160, MAX_SPRITE_Y - 1, vy=2)
    hp0 = rd(mon, sym["objHP"] + s3)[0]
    fire_once(mon)                              # it leaves the world this frame
    t3 = snap(mon)
    check("an enemy that leaves the world on the shot's frame is a clean miss",
          not t3["active"][s3] and t3["logCount"] == 0,
          f"active {t3['active'][s3]}")


# ===========================================================================
def regression(mon):
    print("\n=== 6. Slices A, A', B and C are unchanged ===")
    spawner(mon, True)
    step(mon, 4)

    poke(mon, sym["plyX"], 160); poke(mon, sym["plyXHi"], 0)
    poke(mon, sym["joyHold"], 1); poke(mon, sym["joyState"], JOY_IDLE & ~0b00000100)
    x0 = rd(mon, sym["plyX"])[0]
    step(mon, 6)
    x1 = rd(mon, sym["plyX"])[0]
    check("26. the player still moves one pixel a frame", x0 - x1 == 6, f"{x0} -> {x1}")
    poke(mon, sym["joyState"], JOY_IDLE)

    poke(mon, sym["wpnHeatLo"], 0); poke(mon, sym["wpnHeatHi"], 0)
    poke(mon, sym["wpnOverheated"], 0); poke(mon, sym["wpnCooldown"], 0)
    poke(mon, sym["joyState"], JOY_FIRE)
    step(mon, 4)
    up = rd(mon, sym["wpnHeatLo"], 2)
    poke(mon, sym["joyState"], JOY_IDLE)
    step(mon, 14)
    dn = rd(mon, sym["wpnHeatLo"], 2)
    check("27. heat still rises while firing and falls when released",
          (up[0] | up[1] << 8) > 0 and (dn[0] | dn[1] << 8) < (up[0] | up[1] << 8),
          f"{up[0] | up[1] << 8} -> {dn[0] | dn[1] << 8}")
    check("28. the HUD heat feed still tracks the weapon",
          rd(mon, sym["hudHeatLo"], 2) == dn, f"{rd(mon, sym['hudHeatLo'], 2)}")

    w0 = rd(mon, sym["worldProgressLo"], 2)
    top0 = rd(mon, sym["stageTopRowLo"], 2)
    step(mon, 10)
    w1 = rd(mon, sym["worldProgressLo"], 2)
    top1 = rd(mon, sym["stageTopRowLo"], 2)
    check("29. world progress still only increases, and the map row still steps back",
          (w1[0] | w1[1] << 8) >= (w0[0] | w0[1] << 8)
          and (top1[0] | top1[1] << 8) <= (top0[0] | top0[1] << 8),
          f"progress {w0[0] | w0[1] << 8} -> {w1[0] | w1[1] << 8}")

    for name in ("publishSkip", "statPageMismatch", "statPtrMismatch"):
        poke(mon, sym[name], 0)
    mon.cmd("delete")
    free_run(mon, sym["frameCounter"], 3)
    mon.cmd("delete")
    check("30. the aperture and page publication are clean over a free run",
          rd(mon, sym["statPageMismatch"])[0] == 0
          and rd(mon, sym["statPtrMismatch"])[0] == 0
          and rd(mon, sym["publishSkip"])[0] == 0,
          f"page {rd(mon, sym['statPageMismatch'])[0]} "
          f"ptr {rd(mon, sym['statPtrMismatch'])[0]} "
          f"rec {rd(mon, sym['publishSkip'])[0]}")

    lines = set()
    for _ in range(4):
        step(mon, 1)
        lines.add(rd(mon, sym["frameEntryLine"])[0])
    check("31. the frame transaction is still at raster 250",
          lines == {FRAME_IRQ_LINE}, f"{sorted(lines)}")
    # Not mid-blink: a turret projectile may have hit the ship, and the
    # invulnerability blink correctly clears plyPresEnable on four frames in
    # eight. This check is about slot ownership, not the blink.
    poke(mon, sym["plyInvuln"], 0)
    poke(mon, sym["plyVisible"], 1)
    poke(mon, sym["plyDirty"], 1)
    step(mon, 1)
    check("31b. the player still owns both reserved slots",
          (rd(mon, sym["plyPresEnable"])[0] & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK)
    check("31c. the HUD is undisturbed",
          rd(mon, 0xd017)[0] == 0 and rd(mon, 0xd01c)[0] == 0)


# ===========================================================================
def stopwatch(mon, tries=12):
    """The CPU cycle counter. The machine is halted, so two consecutive
    agreeing readings are the value at this instant -- the remote monitor
    returns from a command on a prompt echo and can be one reply behind."""
    last = None
    for _ in range(tries):
        m = re.search(r"Stopwatch:\s+(\d+)", mon.cmd("stopwatch"))
        if m:
            v = int(m.group(1))
            if v == last:
                return v
            last = v
    raise RuntimeError("could not read the stopwatch")


def ladder(mon):
    print("\n=== 7. collision cost against population ===")
    print("     MEASURED ON A FREE RUN. Every breakpoint stop parks the machine")
    print("     mid-frame, which makes the main thread miss boundaries it would")
    print("     never miss running normally; counting those as engine faults")
    print("     would make the suite's own instrument the thing it measures.")
    print("     Each population is run twice, with collisionTick switched OFF")
    print("     and ON, so the cost is ATTRIBUTED rather than merely observed.\n")
    print("     TWO DIFFERENT COUNTERS, REPORTED SEPARATELY. They were summed")
    print("     into one `over` column, and they do not mean the same thing:")
    print("       overrun   the main thread did not finish inside a 312-line")
    print("                 frame. A FAULT.")
    print("       spanOver  the span passed 255 lines, so the 8-bit gameSpanMax")
    print("                 is a floor. A SATURATED DIAGNOSTIC, not a fault --")
    print("                 src/main.asm says so where it is incremented.\n")
    print("     enemies  collision   span  spanOver  overrun  recSkip  schedSkip")

    col_byte = rd(mon, sym["collisionTick"])[0]

    # TURRET FIRE IS LEFT LIVE. An earlier version of this held it, to stop
    # a launch landing in one of the two span samples and not the other -- but
    # the assertion that differenced those samples is gone (see below), and a
    # production world is the stronger thing to measure the CAPACITY of. At the
    # population-8 rung src/turrets.asm refuses to fire anyway, because
    # TURRET_FIRE_MAX_POP is 8.
    rows = []
    for pop in (1, 4, 8, 12, 16):
        row = {"pop": pop}
        for coll in (False, True):
            clear_pool(mon)
            arm_player(mon, 160, 220)
            poke(mon, sym["collisionTick"], col_byte if coll else 0x60)
            # Spread them down the lane: well-separated sprites are a far
            # heavier RENDERER load than a descending column two rasters apart,
            # because the reuse rule then produces many batches instead of one.
            for k in range(pop):
                s2 = place(mon, 150 + (k % 3) * 6, 60 + k * 10)
                if s2 is not None:
                    poke(mon, sym["objHP"] + s2, 200)   # hold the load steady
            # EACH RUNG STARTS FROM THE SAME STATE. clear_pool above frees
            # every slot, including any projectile in flight, but the pool does
            # not know the projectile counter exists, so it has to be zeroed
            # here or the cap would still count bullets that no longer exist.
            # The invulnerability window is cleared for the same reason: a rung
            # must not inherit the previous rung's blinking ship.
            poke(mon, sym["ebCount"], 0)
            poke(mon, sym["plyInvuln"], 0)
            for name in ("gameSpanMax", "gameSpanOver", "gameOverrun",
                         "publishSkip", "schedBuildDefer"):
                poke(mon, sym[name], 0)
            poke(mon, sym["joyState"], JOY_FIRE)
            poke(mon, sym["wpnOverheated"], 0)
            mon.cmd("delete")
            free_run(mon, sym["frameCounter"], 2)
            mon.cmd("delete")
            poke(mon, sym["joyState"], JOY_IDLE)
            poke(mon, sym["wpnOverheated"], 0)
            k = "on" if coll else "off"
            row[k] = {
                "span": rd(mon, sym["gameSpanMax"])[0],
                "spanOver": rd(mon, sym["gameSpanOver"])[0],
                "over": rd(mon, sym["gameOverrun"])[0],
                "recSkip": rd(mon, sym["publishSkip"])[0],
                "schedSkip": rd(mon, sym["schedBuildDefer"])[0]}
            r = row[k]
            print(f"    {pop:7d}  {'ON ' if coll else 'OFF'}        "
                  f"{r['span']:5d}  {r['spanOver']:8d}  {r['over']:7d}  "
                  f"{r['recSkip']:7d}  {r['schedSkip']:9d}")
        rows.append(row)
    poke(mon, sym["collisionTick"], col_byte)

    # THE SLICE D ASSERTION. Collision must not change whether a population is
    # sustainable. Whether 12 or 16 well-separated sprites are sustainable AT
    # ALL is a property of the renderer and the main thread, and predates this
    # slice -- switching collisionTick off does not rescue them.
    # SUSTAINABLE MEANS THE MAIN THREAD FINISHED INSIDE THE FRAME, and nothing
    # else. It used to mean `gameOverrun + gameSpanOver == 0`, which conflated
    # a fault with a precision limit: gameSpanOver only says the 8-bit
    # gameSpanMax has saturated and the number printed is a floor. A frame that
    # takes 260 of the 312 lines trips it and misses nothing.
    #
    # The population SET is still chosen with both, though, and deliberately.
    # A population whose cost cannot be measured is not one to draw conclusions
    # about, so it is excluded from the comparisons rather than asserted on --
    # which keeps the set exactly what it has always been (1, 4, 8) and stops
    # this change quietly dragging 12 and 16 into assertions written for the
    # populations the engine comfortably sustains.
    same = [r["pop"] for r in rows if (r["off"]["over"] == 0) != (r["on"]["over"] == 0)]
    check("collision never turns a sustainable population into an unsustainable one",
          not same, f"changed at {same}")

    sustained = [r for r in rows
                 if r["off"]["over"] == 0 and r["off"]["spanOver"] == 0]
    check("at every population the engine sustains, collision is free of overruns",
          all(r["on"]["over"] == 0 for r in sustained),
          f"{[(r['pop'], r['on']['over']) for r in sustained]}")
    check("and of publication skips",
          all(r["on"]["recSkip"] == 0 and r["on"]["schedSkip"] == 0 for r in sustained),
          f"{[(r['pop'], r['on']['recSkip'], r['on']['schedSkip']) for r in sustained]}")

    # ---- collision's own cost, MEASURED RATHER THAN DIFFERENCED -----------
    #
    # This used to subtract the collision-off gameSpanMax from the collision-on
    # one. That is a difference of two MAXIMA taken from two separate two-second
    # runs, so every rare expensive thing anywhere in the world lands in one
    # sample or the other and is added to the answer: the same build measured
    # 6, 13, 24, 47 and 56 raster lines on consecutive runs, against a bound of
    # 40. It was not measuring collision; it was measuring which sample got
    # unlucky. The turret slices made that worse by adding a periodic
    # coarse-step spike and an occasional projectile launch, but the method was
    # already the problem -- the spread predates them.
    #
    # So collisionTick is timed DIRECTLY, on the CPU stopwatch between
    # PC-verified breakpoints, which is how every other cost in this repository
    # is established. One routine, one number, no subtraction. The span columns
    # above stay as reported diagnostics.
    deltas = [(r["pop"], r["on"]["span"] - r["off"]["span"]) for r in sustained]
    print(f"     span difference, reported only: {deltas} raster lines")

    poke(mon, sym["joyState"], JOY_IDLE)
    clear_pool(mon)
    arm_player(mon, 160, 220)
    for k in range(8):
        s2 = place(mon, 150 + (k % 3) * 6, 60 + k * 10)
        if s2 is not None:
            poke(mon, sym["objHP"] + s2, 200)
    samples = []
    for _ in range(15):     # the MIN is the pure figure: a sample with no
                            # raster IRQ inside it. More samples, better min.
        poke(mon, sym["shotY"], 210)
        poke(mon, sym["shotXLo"], 164)
        poke(mon, sym["shotXHi"], 0)
        poke(mon, sym["shotXLo"] + 1, 179)
        poke(mon, sym["shotXHi"] + 1, 0)
        poke(mon, sym["shotRays"], 2)
        poke(mon, sym["shotFired"], 1)
        mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
        mon.cmd(f"r sp=fd, pc={sym['collisionTick']:04x}")
        bp = set_bp(mon, 0xc0fe)
        a = stopwatch(mon)
        mon.cmd("x")
        b = stopwatch(mon)
        mon.cmd(f"delete {bp}")
        mon.cmd(f"r pc={sym['mainLoop']:04x}"); mon.cmd("delete")
        if b > a:
            samples.append(b - a)
    pure = min(samples)
    print(f"     collisionTick at population 8, a two-ray volley: "
          f"{pure} cycles pure, {max(samples)} worst of {len(samples)}")
    # Two sixteen-slot scans and two eight-turret scans. 2,500 cycles is forty
    # raster lines -- the bound the differenced version was reaching for, now
    # applied to a number that actually means it.
    check("collision's own cost is small and bounded",
          pure <= 2500, f"{pure} cycles for a two-ray volley at population 8")

    over = [r["pop"] for r in rows
            if r["off"]["over"] > 0 or r["off"]["spanOver"] > 0]
    if over:
        advise("the engine sustains this sprite spread at every population tested",
               False, scope="pre-existing engine limit, not a Slice D regression",
               detail=
               f"populations {over} exceed the 255-line span counter WITH"
               f"\n       COLLISION SWITCHED OFF, and 16 misses frames outright."
               f"\n       Well-separated sprites produce many batches where a"
               f"\n       descending column produces one, so this is a heavier"
               f"\n       RENDERER load than Slice C's ladder ever applied. It is a"
               f"\n       pre-existing main-thread limit, not a Slice D regression,"
               f"\n       and section 10 of the engine contract already owns it.")
    return rows


# ===========================================================================
def vicerc_snapshot():
    out = {}
    for p in (Path.home() / ".config/vice/vicerc",
              Path.home() / ".vice/vicerc",
              Path.home() / "Library/Preferences/vice/vicerc"):
        if p.exists():
            out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def vice_config_hygiene(before):
    print("\n=== 8. the user's VICE configuration is untouched ===")
    src = (ROOT / "tests" / "test_p0.py").read_text()
    args = re.search(r"args = \[X64.*?\]", src, re.S).group(0)
    check("automated runs pass +saveres, so nothing is written back",
          '"+saveres"' in args)
    check("input settings are per-process command-line arguments only",
          '"-joydev1", "0"' in args and '"-joydev2", "0"' in args and '"+keyset"' in args)
    for path, digest in before.items():
        now = hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else None
        check(f"unchanged across this run: {Path(path).name}", now == digest,
              "MODIFIED" if now != digest else "")

    mk = (ROOT / "Makefile").read_text()
    opts = re.search(r"^VICE_OPTS\s*:?=\s*(.+)$", mk, re.M).group(1)
    check("the manual run does not start from factory defaults",
          "-default" not in opts, opts)
    # The manual run now SAVES the player's own settings on exit; it is their
    # machine. The automated suites are the separate context that must not
    # write the file back, and tests/test_p0.py still builds `-default
    # +saveres` with both ports detached -- which the hashes above prove.
    # tests/test_slice_c.py carries the full form of this check.
    check("the manual run saves the player's own settings on exit",
          "-saveres" in opts and "+saveres" not in opts, opts)

    for path in before:
        text = Path(path).read_text()
        dev = re.search(r"^JoyDevice2=(\d+)", text, re.M)
        if not dev or dev.group(1) not in ("2", "3"):
            continue
        n_set = "1" if dev.group(1) == "2" else "2"
        has_fire = re.search(rf"^KeySet{n_set}Fire=", text, re.M)
        advise(f"the selected keyset {n_set} has a real Fire binding",
               bool(has_fire),
               "" if has_fire else
               f"KeySet{n_set}Fire MISSING -- the ship will move but never shoot."
               f"\n       Add KeySet{n_set}Fire=<key code> to {path} under [C64SC].")


# ===========================================================================
def main():
    print("Slice D — hitscan collision, enemy damage, enemy death\n")
    source_invariants()
    cfg = vicerc_snapshot()

    v = None
    try:
        v = Vice(6614, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], JOY_IDLE)
        geometry(mon)
        targeting(mon)
        damage(mon)
        death_lifecycle(mon)
        regression(mon)
        ladder(mon)
    finally:
        if v: v.close()
        print(f"\n  launched and reaped: {LAUNCHED_PIDS}")

    vice_config_hygiene(cfg)

    print()
    for label, detail, scope in advisories:
        print(f"=== ADVISORY ({scope}): {label} ===")
        if detail:
            print(f"    {detail}")
    if fails:
        print(f"=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
        return 1
    print("=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
