#!/usr/bin/env python3
"""Turret firing, hostile projectiles, and the player taking damage.

What this proves
----------------
* every firing and projectile constant is the old engine's own, read out of
  the archive: the 100-frame per-turret interval, the fire window, the lead
  the ship must have, the population gate, the cap of three, the fixed
  downward speed, the quantised aim buckets and the player hitbox;
* a turret fires only while it is combat-visible, alive, in the fire window,
  above the ship, and the world is not already busy -- and its timer restarts
  from the top the moment it leaves the aperture;
* a destroyed turret never fires;
* the projectile spawns at the muzzle, aimed with the old quantised slope;
* the pool is capped at three globally, refusals are counted, and slots are
  reused;
* a projectile flies on its launch vector and retires off either side or at
  the bottom;
* projectile -> player collision is SOFTWARE, in logical coordinates, and the
  projectile is consumed by the hit so it cannot damage the ship twice;
* invulnerability prevents further damage and expires;
* projectiles reach the screen through the ordinary logical renderer path --
  a pool slot, logY/logX/logXHi/logPtr/logCol -- with no reserved hardware
  sprite and no VIC collision register anywhere;
* the turret presentation and destruction of the previous slice still work.

The model sections need no emulator. The machine section launches exactly one
VICE and reaps it on every path.
"""
import sys, re, statistics, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import PRG, SYM, symbols, Vice, rd, set_bp, free_run, LAUNCHED_PIDS
from test_p2 import poke
import turret_model as TM
import old_repo

sym = symbols(SYM)

# --- the contract, restated independently of the assembler ------------------
STAGE_ROWS, SCREEN_ROWS = 420, 25
MAX_OBJECTS = 16
MIN_SPRITE_Y, MAX_SPRITE_Y = 55, 226
TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET = 0, 1, 2

# The authoritative old values. Every one is CHECKED against the archive below.
OLD_FIRE_INTERVAL = 100
OLD_FIRE_MIN_Y, OLD_FIRE_MAX_Y = 88, 201
OLD_FIRE_LEAD = 24
OLD_FIRE_MAX_POP = 8
OLD_MAX_BULLETS = 3
OLD_BULLET_VY = 3
OLD_BULLET_COL = 7
OLD_AIM_NEAR, OLD_AIM_MID = 24, 72
OLD_MUZZLE_X, OLD_MUZZLE_Y = 4, 12
OLD_INVULN_TIME = 100
EBULLET_SPRITE = 0x36c0
EBULLET_PTR = EBULLET_SPRITE // 64

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def asm_const(path, name):
    txt = (ROOT / "src" / path).read_text()
    m = re.search(rf"^\.const\s+{name}\s*=\s*([^/\n]+)", txt, re.M)
    return m.group(1).strip() if m else None


def aim_slope(dx):
    """The old chooseEnemyBulletSlope, restated: signed dx -> velocity."""
    mag = abs(dx)
    v = 0 if mag < OLD_AIM_NEAR else (1 if mag < OLD_AIM_MID else 2)
    return v if dx >= 0 else -v


# ===========================================================================
def constants():
    print("=== 1. every firing and projectile constant is the old engine's ===")
    if not old_repo.present():
        check("the reference archive is present", False, str(old_repo.ARCHIVE))
        return
    turr = old_repo.old_text("src/background_turrets.asm")
    main = old_repo.old_text("src/main.asm")

    def old_const(txt, name):
        m = re.search(rf"\.const\s+{name}\s*=\s*([^/\n]+)", txt)
        return m.group(1).strip() if m else None

    check(f"the old TURRET_FIRE_INTERVAL is {OLD_FIRE_INTERVAL}",
          old_const(turr, "TURRET_FIRE_INTERVAL") == str(OLD_FIRE_INTERVAL),
          str(old_const(turr, "TURRET_FIRE_INTERVAL")))
    for name, want in (("MAX_ENEMY_BULLETS", OLD_MAX_BULLETS),
                       ("ENEMY_BULLET_SPEED_Y", OLD_BULLET_VY),
                       ("ENEMY_BULLET_COLOUR", OLD_BULLET_COL)):
        check(f"the old {name} is {want}",
              old_const(main, name) == str(want), str(old_const(main, name)))
    check(f"the old PLAYER_RESPAWN_TIME is {OLD_INVULN_TIME}",
          old_const(main, "PLAYER_RESPAWN_TIME") == str(OLD_INVULN_TIME),
          str(old_const(main, "PLAYER_RESPAWN_TIME")))

    # The firing block of updateBackgroundTurrets, read directly.
    fire = turr[turr.index("updateBackgroundTurrets:"):]
    fire = fire[:fire.index("// --- Routine: pulseTurretColour")]
    check("the old timer is PER TURRET and only runs while visible",
          "sta TURRET_FIRE_TIMER,x" in fire and "lda TURRET_VISIBLE,x" in fire)
    check("...and restarts at the full interval when it is not",
          re.search(r"lda TURRET_VISIBLE,x\s*\n\s*bne [^\n]*\n\s*lda "
                    r"#TURRET_FIRE_INTERVAL\s*\n\s*sta TURRET_FIRE_TIMER,x",
                    fire) is not None)
    check("the old timer reloads BEFORE the eligibility tests",
          fire.index("lda #TURRET_FIRE_INTERVAL\n    sta TURRET_FIRE_TIMER,x\n    lda TURRET_Y,x")
          > 0)
    check(f"the old fire window is {OLD_FIRE_MIN_Y}..{OLD_FIRE_MAX_Y - 1}",
          re.search(rf"cmp #{OLD_FIRE_MIN_Y}\s", fire) is not None
          and re.search(rf"cmp #{OLD_FIRE_MAX_Y}\s", fire) is not None)
    check(f"the old lead is {OLD_FIRE_LEAD} pixels below the turret",
          re.search(rf"adc #{OLD_FIRE_LEAD}\s*\n\s*cmp OBJECT_Y", fire) is not None)
    check(f"the old population gate is SORTED_COUNT < {OLD_FIRE_MAX_POP}",
          re.search(rf"lda SORTED_COUNT\s*\n\s*cmp #{OLD_FIRE_MAX_POP}", fire)
          is not None)
    check(f"the old muzzle offset is +{OLD_MUZZLE_X}, +{OLD_MUZZLE_Y}",
          re.search(rf"adc #{OLD_MUZZLE_X}\s", fire) is not None
          and re.search(rf"adc #{OLD_MUZZLE_Y}\s", fire) is not None)
    check("a dead turret never reaches the firing block",
          re.search(r"lda TURRET_HEALTH,x\s*\n\s*bne !alive\+", fire) is not None)

    # The aim buckets, from chooseEnemyBulletSlope.
    slope = main[main.index("chooseEnemyBulletSlope:"):]
    slope = slope[:slope.index("moveEnemyBullet:")]
    check(f"the old aim buckets are <{OLD_AIM_NEAR} and <{OLD_AIM_MID}",
          re.search(rf"cmp #{OLD_AIM_NEAR}\s", slope) is not None
          and re.search(rf"cmp #{OLD_AIM_MID}\s", slope) is not None)

    # The player hitbox, from checkBulletPlayerOverlap.
    box = main[main.index("checkBulletPlayerOverlap:"):]
    box = box[:box.index("!bulletHit:")]
    check("the old bullet/player box is -7..+23 across and -7..+20 down",
          "cmp #$f9" in box and "cmp #24" in box and "cmp #21" in box)

    # And that this repo restates all of it.
    print("  -- and this repo restates them:")
    for path, name, want in (
            ("turrets.asm", "TURRET_FIRE_INTERVAL", OLD_FIRE_INTERVAL),
            ("turrets.asm", "TURRET_FIRE_MIN_Y", OLD_FIRE_MIN_Y),
            ("turrets.asm", "TURRET_FIRE_MAX_Y", OLD_FIRE_MAX_Y),
            ("turrets.asm", "TURRET_FIRE_LEAD", OLD_FIRE_LEAD),
            ("turrets.asm", "TURRET_FIRE_MAX_POP", OLD_FIRE_MAX_POP),
            ("turrets.asm", "TURRET_MUZZLE_X", OLD_MUZZLE_X),
            ("turrets.asm", "TURRET_MUZZLE_Y", OLD_MUZZLE_Y),
            ("ebullet.asm", "EBULLET_MAX", OLD_MAX_BULLETS),
            ("ebullet.asm", "EBULLET_VY", OLD_BULLET_VY),
            ("ebullet.asm", "EBULLET_COL", OLD_BULLET_COL),
            ("ebullet.asm", "EBULLET_AIM_NEAR", OLD_AIM_NEAR),
            ("ebullet.asm", "EBULLET_AIM_MID", OLD_AIM_MID),
            ("player.asm", "PLAYER_INVULN_TIME", OLD_INVULN_TIME)):
        got = asm_const(path, name)
        check(f"src/{path} {name} = {want}", got == str(want), str(got))


# ===========================================================================
def ownership():
    print("\n=== 2. no VIC state, no reserved sprite, no collision register ===")
    eb = re.sub(r"//.*", "", (ROOT / "src" / "ebullet.asm").read_text())
    check("ebullet.asm writes no VIC register",
          not re.findall(r"st[axy]\s+\$(d0[0-9a-f]{2})", eb, re.I))
    check("ebullet.asm does not name $d01e or $d01f",
          "d01e" not in eb.lower() and "d01f" not in eb.lower())
    check("ebullet.asm names no VIC register at all",
          not re.findall(r"\$(d0[0-9a-f]{2})", eb, re.I))
    check("ebullet.asm touches no colour RAM", "d800" not in eb.lower())
    for token in ("MUX_", "HW0", "HW1", "schedBatches", "schedCurrent",
                  "exBatch", "spritePtr", "$d015"):
        check(f"ebullet.asm never mentions {token}", token not in eb)

    # It reaches the screen the ordinary way: a pool slot and the logical arrays.
    for name in ("objectAlloc", "objectActivate", "objectFree",
                 "logX,x", "logY,x", "logPtr,x", "logCol,x"):
        check(f"...and it does use {name}", name in eb)

    tu = re.sub(r"//.*", "", (ROOT / "src" / "turrets.asm").read_text())
    check("turrets.asm still writes no VIC register",
          not re.findall(r"st[axy]\s+\$(d0[0-9a-f]{2})", tu, re.I))
    check("the firing tick is gated on the visibility mask it already has",
          re.search(r"turretFireTick:\s*\n\s*lda trtVisibleMask\s*\n\s*bne",
                    tu) is not None)

    mn = (ROOT / "src" / "main.asm").read_text()
    check("firing runs after collisionTick, so a destroyed turret cannot fire",
          mn.index("jsr turretFireTick") > mn.index("jsr collisionTick"))
    check("...and beside enemySpawnTick, before the schedule is rebuilt",
          mn.index("jsr turretFireTick") < mn.index("jsr sortTick"))
    check("the player-damage pass runs after every object has moved",
          mn.index("jsr ebulletPlayerTick") > mn.index("jsr objectUpdateAll"))


# ===========================================================================
def machine():
    print("\n=== 3. the 6502 ===")
    total, cols, rows = TM.authored()

    v = Vice(6635, PRG, warp=True)
    try:
        mon = v.mon

        # --- the clean production counters, FIRST -------------------------
        free_run(mon, sym["frameCounter"], 3)
        mon.cmd("delete")
        for name in ("gameOverrun", "publishSkip", "scrollLate", "edgeLate",
                     "schedBuildDefer"):
            got = rd(mon, sym[name])[0]
            check(f"{name} is zero with firing live", got == 0, str(got))
        # NOT "no projectile exists": three seconds of warp have passed and a
        # turret that has been on the aperture is legitimately allowed to have
        # shot. That check was written when turrets COULD NOT FIRE, so it
        # passed for the same reason the whole feature was broken. What must
        # hold on a live production machine is that the cap is honoured and
        # that the counter agrees with the pool it is counting -- an ebCount
        # that has drifted from the live TYPE_EBULLET slots would silently
        # refuse every future shot.
        live_eb = rd(mon, sym["objType"], MAX_OBJECTS).count(TYPE_EBULLET)
        eb = rd(mon, sym["ebCount"])[0]
        check("the projectile cap is honoured on a live production machine",
              eb <= OLD_MAX_BULLETS, f"ebCount {eb}")
        check("...and ebCount agrees with the live projectile slots",
              eb == live_eb, f"ebCount {eb}, TYPE_EBULLET slots {live_eb}")
        # The ship may have been SHOT in those three seconds, which is the
        # feature working. What must not happen is invulnerability without a
        # hit to explain it.
        check("the ship is only ever invulnerable after taking a hit",
              rd(mon, sym["plyInvuln"])[0] == 0 or rd(mon, sym["plyHits"])[0] > 0,
              f"plyInvuln {rd(mon, sym['plyInvuln'])[0]} "
              f"plyHits {rd(mon, sym['plyHits'])[0]}")
        # NOT "every timer reads the interval": three seconds have passed and a
        # turret that has been on the aperture is legitimately counting down.
        # What must hold is that none has run past its reload.
        timers = rd(mon, sym["turretFireTimer"], total)
        check("no fire timer has run past its interval",
              all(0 <= v <= OLD_FIRE_INTERVAL for v in timers), str(timers))
        art = rd(mon, EBULLET_SPRITE, 8 * 3)
        check(f"the projectile bitmap is resident at ${EBULLET_SPRITE:04x}",
              art[0::3] == [0x3c, 0xff, 0xff, 0x3c, 0x3c, 0x18, 0x18, 0x00],
              str(art[0::3]))

        # ------------------------------------------------------------------
        # A deterministic bench. From here the PC is hijacked, so the counters
        # above are no longer meaningful -- which is why they were read above.
        # ------------------------------------------------------------------
        def call(routine):
            mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym[routine]:04x}")
            bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
            mon.cmd(f"r pc={sym['mainLoop']:04x}"); mon.cmd("delete")

        def clear_pool():
            for i in range(MAX_OBJECTS):
                call_x("objectFree", i)
            poke(mon, sym["ebCount"], 0)

        def call_x(routine, x):
            mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym[routine]:04x}, x={x:02x}")
            bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
            mon.cmd(f"r pc={sym['mainLoop']:04x}"); mon.cmd("delete")

        call("turretInit")
        check("turretInit arms every turret with a full fire interval",
              rd(mon, sym["turretFireTimer"], total) == [OLD_FIRE_INTERVAL] * total,
              str(rd(mon, sym["turretFireTimer"], total)))

        def set_world(top, fine=0):
            poke(mon, sym["stageTopRowLo"], top & 0xff)
            poke(mon, sym["stageTopRowHi"], top >> 8)
            poke(mon, sym["scrollFine"], fine)
            call("turretWorldTick")

        def put_player(x, y, invuln=0):
            poke(mon, sym["plyX"], x & 0xff)
            poke(mon, sym["plyXHi"], x >> 8)
            poke(mon, sym["plyY"], y)
            poke(mon, sym["plyInvuln"], invuln)

        def live_slots():
            act = rd(mon, sym["logActive"], MAX_OBJECTS)
            typ = rd(mon, sym["objType"], MAX_OBJECTS)
            return [i for i in range(MAX_OBJECTS)
                    if act[i] and typ[i] == TYPE_EBULLET]

        # Put turret 0 in the middle of its pass, well inside the fire window.
        i = 0
        R, C = rows[i], cols[i]
        top = (R - 12) % STAGE_ROWS          # body at matrix row 12
        set_world(top, 0)
        ly = rd(mon, sym["turretLogY"], total)[i]
        tx = 24 + C * 8
        check(f"turret {i} is combat-visible at matrix row 12 (logY {ly})",
              rd(mon, sym["turretVisible"], total)[i] == 1)
        check("...and inside the old fire window",
              OLD_FIRE_MIN_Y <= ly < OLD_FIRE_MAX_Y, str(ly))

        clear_pool()
        put_player(tx, ly + 60)
        poke(mon, sym["ebRefused"], 0)

        # --- the cadence ---------------------------------------------------
        # Drive turretFireTick a frame at a time and record which calls fire.
        def fire_frames(n, reset=True):
            if reset:
                for j in range(total):
                    poke(mon, sym["turretFireTimer"] + j, OLD_FIRE_INTERVAL)
            shots = []
            before = rd(mon, sym["ebFired"])[0]
            for k in range(n):
                call("turretFireTick")
                now = rd(mon, sym["ebFired"])[0]
                if now != before:
                    shots.append(k)
                    before = now
                # keep the pool clear so the cap never masks the cadence
                for s in live_slots():
                    call_x("ebulletRetire", s)
            return shots

        shots = fire_frames(OLD_FIRE_INTERVAL * 2 + 3)
        check(f"the first shot comes after exactly {OLD_FIRE_INTERVAL} frames "
              f"on the aperture", shots and shots[0] == OLD_FIRE_INTERVAL,
              str(shots[:3]))
        check(f"and the cadence is {OLD_FIRE_INTERVAL} frames thereafter",
              len(shots) >= 2 and shots[1] - shots[0] == OLD_FIRE_INTERVAL + 1,
              str(shots[:3]))

        # --- eligibility ---------------------------------------------------
        def one_shot(setup=None):
            """Arm the timer and take a single firing opportunity."""
            for j in range(total):
                poke(mon, sym["turretFireTimer"] + j, 0)
            if setup:
                setup()
            before = rd(mon, sym["ebFired"])[0]
            call("turretFireTick")
            return rd(mon, sym["ebFired"])[0] != before

        clear_pool()
        put_player(tx, ly + 60)
        check("an armed, visible, living turret fires", one_shot())
        for s in live_slots():
            call_x("ebulletRetire", s)

        check("a DESTROYED turret never fires",
              not one_shot(lambda: poke(mon, sym["turretAlive"] + i, 0)))
        poke(mon, sym["turretAlive"] + i, 1)

        check("...and a dead turret's timer is held at the full interval",
              rd(mon, sym["turretFireTimer"], total)[i] == OLD_FIRE_INTERVAL,
              str(rd(mon, sym["turretFireTimer"], total)[i]))

        # Off the aperture: the turret is not combat-visible at all.
        far = (R - 40) % STAGE_ROWS
        check("an OFF-APERTURE turret never fires",
              not one_shot(lambda: set_world(far, 0)))
        # The clock is armed when the turret ARRIVES, not when it leaves, so the
        # test for "it cannot fire the instant it returns" is to send it away
        # with an expired timer and bring it back.
        poke(mon, sym["turretFireTimer"] + i, 0)
        set_world(top, 0)
        check("a turret that comes back must earn its interval again",
              rd(mon, sym["turretFireTimer"], total)[i] == OLD_FIRE_INTERVAL,
              str(rd(mon, sym["turretFireTimer"], total)[i]))
        before = rd(mon, sym["ebFired"])[0]
        call("turretFireTick")
        check("...and it does not fire on the frame it returns",
              rd(mon, sym["ebFired"])[0] == before)

        check("a turret does not fire at a ship ABOVE it",
              not one_shot(lambda: put_player(tx, ly - 20)))
        check("a turret does not fire at a ship right on top of it",
              not one_shot(lambda: put_player(tx, ly + OLD_FIRE_LEAD)))
        check("...but does when the ship is one pixel further down",
              one_shot(lambda: put_player(tx, ly + OLD_FIRE_LEAD + 1)))
        for s in live_slots():
            call_x("ebulletRetire", s)

        check("a turret does not fire at an INVULNERABLE ship",
              not one_shot(lambda: put_player(tx, ly + 60, invuln=30)))
        put_player(tx, ly + 60)

        # The population gate: fill the pool with enemies.
        def busy_world():
            for k in range(OLD_FIRE_MAX_POP):
                call_x("objectAlloc", 0)
                # objectAlloc leaves X = the slot; activate it as an enemy
            # simpler: drive the real spawner's fields directly
        clear_pool()
        for k in range(OLD_FIRE_MAX_POP):
            poke(mon, sym["objType"] + k, TYPE_ENEMY)
            poke(mon, sym["logY"] + k, 100)
            call_x("objectActivate", k)
        check(f"the world is busy: logCount {OLD_FIRE_MAX_POP}",
              rd(mon, sym["logCount"])[0] == OLD_FIRE_MAX_POP,
              str(rd(mon, sym["logCount"])[0]))
        check(f"a turret holds fire at a population of {OLD_FIRE_MAX_POP}",
              not one_shot())
        clear_pool()
        check("...and fires again once the world quietens", one_shot())
        for s in live_slots():
            call_x("ebulletRetire", s)

        # --- the muzzle and the aim ----------------------------------------
        for dx, want_vx in ((0, 0), (16, 0), (-16, 0), (40, 1), (-40, -1),
                            (100, 2), (-100, -2)):
            clear_pool()
            put_player(tx + dx, ly + 60)
            one_shot()
            s = live_slots()
            if not s:
                check(f"aim dx={dx:+d}: a projectile exists", False)
                continue
            k = s[0]
            bx = rd(mon, sym["logX"], MAX_OBJECTS)[k] \
                | (rd(mon, sym["logXHi"], MAX_OBJECTS)[k] << 8)
            by = rd(mon, sym["logY"], MAX_OBJECTS)[k]
            vx = rd(mon, sym["objVX"], MAX_OBJECTS)[k]
            vx = vx - 256 if vx > 127 else vx
            check(f"aim dx={dx:+d}: muzzle at turretX+{OLD_MUZZLE_X}, "
                  f"turretY+{OLD_MUZZLE_Y}",
                  bx == tx + OLD_MUZZLE_X and by == ly + OLD_MUZZLE_Y,
                  f"({bx},{by}) vs ({tx + OLD_MUZZLE_X},{ly + OLD_MUZZLE_Y})")
            check(f"aim dx={dx:+d}: quantised slope {want_vx:+d}",
                  vx == want_vx, f"{vx:+d}")
            for s2 in live_slots():
                call_x("ebulletRetire", s2)

        # --- the presentation the renderer will consume --------------------
        clear_pool()
        put_player(tx, ly + 60)
        one_shot()
        k = live_slots()[0]
        check("the projectile is an ACTIVE pool object of the projectile type",
              rd(mon, sym["logActive"], MAX_OBJECTS)[k] == 1
              and rd(mon, sym["objType"], MAX_OBJECTS)[k] == TYPE_EBULLET)
        check(f"its pointer is the shared bitmap (${EBULLET_PTR:02x})",
              rd(mon, sym["logPtr"], MAX_OBJECTS)[k] == EBULLET_PTR,
              str(rd(mon, sym["logPtr"], MAX_OBJECTS)[k]))
        check(f"its colour is the old {OLD_BULLET_COL}",
              rd(mon, sym["logCol"], MAX_OBJECTS)[k] == OLD_BULLET_COL)
        check(f"it falls at {OLD_BULLET_VY} pixels a frame",
              rd(mon, sym["objVY"], MAX_OBJECTS)[k] == OLD_BULLET_VY)
        check("it has no health, so the player's hitscan cannot target it",
              rd(mon, sym["objHP"], MAX_OBJECTS)[k] == 0)
        check("and the sorter counts it like any other logical sprite",
              rd(mon, sym["logCount"])[0] == 1)

        # --- flight and despawn --------------------------------------------
        y0 = rd(mon, sym["logY"], MAX_OBJECTS)[k]
        x0 = rd(mon, sym["logX"], MAX_OBJECTS)[k]
        call("objectUpdateAll")
        check(f"one frame of flight moves it {OLD_BULLET_VY} down",
              rd(mon, sym["logY"], MAX_OBJECTS)[k] == y0 + OLD_BULLET_VY,
              f"{y0} -> {rd(mon, sym['logY'], MAX_OBJECTS)[k]}")
        check("...and its X follows its launch vector",
              rd(mon, sym["logX"], MAX_OBJECTS)[k] == x0)

        poke(mon, sym["logY"] + k, 248)
        call("objectUpdateAll")
        check("a projectile retires at the bottom of the screen",
              rd(mon, sym["logActive"], MAX_OBJECTS)[k] == 0
              and rd(mon, sym["ebCount"])[0] == 0,
              f"active {rd(mon, sym['logActive'], MAX_OBJECTS)[k]} "
              f"count {rd(mon, sym['ebCount'])[0]}")

        # Off the right edge.
        clear_pool()
        put_player(tx + 100, ly + 60)        # force a +2 slope
        one_shot()
        k = live_slots()[0]
        poke(mon, sym["logX"] + k, 0x58)
        poke(mon, sym["logXHi"] + k, 1)      # 344, one short of the limit
        call("objectUpdateAll")
        check("a projectile retires off the right edge",
              rd(mon, sym["logActive"], MAX_OBJECTS)[k] == 0
              and rd(mon, sym["ebCount"])[0] == 0)

        # --- the cap --------------------------------------------------------
        clear_pool()
        put_player(tx, ly + 60)
        poke(mon, sym["ebRefused"], 0)
        for n in range(OLD_MAX_BULLETS + 2):
            one_shot()
        check(f"the pool is capped at {OLD_MAX_BULLETS} projectiles globally",
              rd(mon, sym["ebCount"])[0] == OLD_MAX_BULLETS
              and len(live_slots()) == OLD_MAX_BULLETS,
              f"count {rd(mon, sym['ebCount'])[0]} live {live_slots()}")
        check("...and the refusals are counted, not silent",
              rd(mon, sym["ebRefused"])[0] >= 2,
              str(rd(mon, sym["ebRefused"])[0]))
        s = live_slots()
        call_x("ebulletRetire", s[0])
        check("retiring one frees the slot and the cap admits another",
              rd(mon, sym["ebCount"])[0] == OLD_MAX_BULLETS - 1)
        one_shot()
        check("...and the freed slot is reused",
              rd(mon, sym["ebCount"])[0] == OLD_MAX_BULLETS
              and sorted(live_slots()) == sorted(s),
              f"{live_slots()} vs {s}")

        # --- the player takes a hit ----------------------------------------
        clear_pool()
        poke(mon, sym["plyHits"], 0)
        PLY_HIT_Y = 200                         # comfortably below the turret's
        put_player(160, PLY_HIT_Y)              # lead, and inside the band
        one_shot()
        k = live_slots()[0]
        # Park it exactly on the ship.
        poke(mon, sym["logX"] + k, 160)
        poke(mon, sym["logXHi"] + k, 0)
        poke(mon, sym["logY"] + k, PLY_HIT_Y)
        call("ebulletPlayerTick")
        check("a projectile on the ship damages it",
              rd(mon, sym["plyHits"])[0] == 1,
              str(rd(mon, sym["plyHits"])[0]))
        check("...and the ship becomes invulnerable for the old window",
              rd(mon, sym["plyInvuln"])[0] == OLD_INVULN_TIME,
              str(rd(mon, sym["plyInvuln"])[0]))
        check("...and the PROJECTILE IS CONSUMED, so it cannot hit twice",
              rd(mon, sym["logActive"], MAX_OBJECTS)[k] == 0
              and rd(mon, sym["ebCount"])[0] == 0)
        check("...and the hit is counted", rd(mon, sym["ebPlayerHits"])[0] >= 1)

        # A second projectile while invulnerable does nothing.
        clear_pool()
        put_player(160, PLY_HIT_Y, invuln=OLD_INVULN_TIME)
        poke(mon, sym["plyHits"], 0)
        # place one by hand, since a turret will not fire at an invulnerable ship
        poke(mon, sym["objType"] + 5, TYPE_EBULLET)
        poke(mon, sym["logX"] + 5, 160)
        poke(mon, sym["logXHi"] + 5, 0)
        poke(mon, sym["logY"] + 5, PLY_HIT_Y)
        call_x("objectActivate", 5)
        poke(mon, sym["ebCount"], 1)
        call("ebulletPlayerTick")
        check("an INVULNERABLE ship takes no further damage",
              rd(mon, sym["plyHits"])[0] == 0,
              str(rd(mon, sym["plyHits"])[0]))
        check("...and the projectile flies on rather than being consumed",
              rd(mon, sym["logActive"], MAX_OBJECTS)[5] == 1)

        # The hitbox edges, with invulnerability off.
        for dx, dy, want in ((0, 0, True), (23, 0, True), (24, 0, False),
                             (-7, 0, True), (-8, 0, False),
                             (0, 20, True), (0, 21, False),
                             (0, -7, True), (0, -8, False)):
            poke(mon, sym["plyInvuln"], 0)
            poke(mon, sym["plyHits"], 0)
            # objType MUST be re-established every time: a hit retires the
            # projectile, and objectFree zeroes the whole slot. Without this the
            # first case frees slot 5 and every later "should hit" case is
            # quietly testing a TYPE_NONE slot the scan skips -- which reads as
            # a tighter hitbox than the code actually has.
            poke(mon, sym["objType"] + 5, TYPE_EBULLET)
            poke(mon, sym["logX"] + 5, (160 + dx) & 0xff)
            poke(mon, sym["logXHi"] + 5, (160 + dx) >> 8)
            poke(mon, sym["logY"] + 5, PLY_HIT_Y + dy)
            poke(mon, sym["logActive"] + 5, 1)
            poke(mon, sym["ebCount"], 1)
            call("ebulletPlayerTick")
            got = rd(mon, sym["plyHits"])[0] == 1
            check(f"hitbox dx={dx:+d} dy={dy:+d}: "
                  f"{'hit' if want else 'miss'}", got == want)

        # Outside the renderable band it cannot hit at all.
        for y, what in ((MIN_SPRITE_Y - 1, "above the band"),
                        (MAX_SPRITE_Y + 1, "below the band")):
            poke(mon, sym["plyInvuln"], 0)
            poke(mon, sym["plyHits"], 0)
            put_player(160, y)
            poke(mon, sym["objType"] + 5, TYPE_EBULLET)
            poke(mon, sym["logX"] + 5, 160)
            poke(mon, sym["logXHi"] + 5, 0)
            poke(mon, sym["logY"] + 5, y)
            poke(mon, sym["logActive"] + 5, 1)
            poke(mon, sym["ebCount"], 1)
            call("ebulletPlayerTick")
            check(f"a projectile {what} cannot cause an invisible hit",
                  rd(mon, sym["plyHits"])[0] == 0)

        # --- invulnerability runs out, and blinks while it does -------------
        clear_pool()
        put_player(160, PLY_HIT_Y)
        poke(mon, sym["plyInvuln"], 9)
        seen = set()
        for n in range(9):
            call("playerInvulnTick")
            seen.add(rd(mon, sym["plyVisible"])[0])
        check("the ship blinks while invulnerable", seen == {0, 1}, str(seen))
        check("the window expires", rd(mon, sym["plyInvuln"])[0] == 0)
        check("...and the ship is left SOLID, not mid-blink",
              rd(mon, sym["plyVisible"])[0] == 1)

        # --- the turret slice underneath is untouched ----------------------
        set_world(top, 0)
        check("the turret is still alive and at full health",
              rd(mon, sym["turretAlive"], total)[i] == 1
              and rd(mon, sym["turretHealth"], total)[i] == 3)
        check("and the page geometry still names its body row",
              rd(mon, sym["turretPaintRow"], total)[i] == 12,
              str(rd(mon, sym["turretPaintRow"], total)[i]))

        # ================================================================
        print("\n=== 4. what firing costs, and on which frame ===")

        def sw(tries=12):
            last = None
            for _ in range(tries):
                m = re.search(r"Stopwatch:\s+(\d+)", mon.cmd("stopwatch"))
                if m:
                    val = int(m.group(1))
                    if val == last:
                        return val
                    last = val
            raise RuntimeError("stopwatch")

        def timed(routine, setup, n=15):
            out = []
            for _ in range(n):
                setup()
                mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
                mon.cmd(f"r sp=fd, pc={sym[routine]:04x}")
                bb = set_bp(mon, 0xc0fe)
                a = sw(); mon.cmd("x"); b = sw()
                mon.cmd(f"delete {bb}")
                mon.cmd(f"r pc={sym['mainLoop']:04x}"); mon.cmd("delete")
                if b > a:
                    out.append(b - a)
            return out

        def stat(label, xs):
            print(f"  {label:<52} min {min(xs):5d}   med "
                  f"{int(statistics.median(xs)):5d}   max {max(xs):5d}")
            return min(xs)

        results = {}
        none_top = (rows[0] - 200) % STAGE_ROWS
        clear_pool()
        set_world(none_top, 0)
        results["fire_none"] = stat(
            "turretFireTick, no turret on the aperture",
            timed("turretFireTick", lambda: None))
        results["hit_none"] = stat(
            "ebulletPlayerTick, nothing in flight",
            timed("ebulletPlayerTick", lambda: None))

        set_world(top, 0)
        put_player(tx, ly + 60)

        def armed_counting():
            for j in range(total):
                poke(mon, sym["turretFireTimer"] + j, 50)
        results["fire_counting"] = stat(
            "turretFireTick, turrets visible, counting down",
            timed("turretFireTick", armed_counting))

        def armed_firing():
            clear_pool()
            for j in range(total):
                poke(mon, sym["turretFireTimer"] + j, 0)
        results["fire_shot"] = stat(
            "turretFireTick, a frame that actually launches",
            timed("turretFireTick", armed_firing))

        def three_bullets():
            clear_pool()
            for j, slot in enumerate((3, 7, 11)):
                poke(mon, sym["objType"] + slot, TYPE_EBULLET)
                poke(mon, sym["logX"] + slot, 40 + j * 40)
                poke(mon, sym["logXHi"] + slot, 0)
                poke(mon, sym["logY"] + slot, 120 + j * 20)
                poke(mon, sym["objVY"] + slot, OLD_BULLET_VY)
                poke(mon, sym["logActive"] + slot, 1)
            poke(mon, sym["ebCount"], OLD_MAX_BULLETS)
            poke(mon, sym["plyInvuln"], 0)
            put_player(300, 200)
        results["hit_three"] = stat(
            f"ebulletPlayerTick, {OLD_MAX_BULLETS} in flight, all missing",
            timed("ebulletPlayerTick", three_bullets))
        results["move_three"] = stat(
            f"objectUpdateAll, {OLD_MAX_BULLETS} projectiles flying",
            timed("objectUpdateAll", three_bullets))
        results["move_none"] = stat(
            "objectUpdateAll, an empty pool",
            timed("objectUpdateAll", clear_pool))
        results["invuln_off"] = stat(
            "playerInvulnTick, the ship not invulnerable",
            timed("playerInvulnTick",
                  lambda: poke(mon, sym["plyInvuln"], 0)))

        # The two frames the previous slice protected.
        def prepare_frame():
            set_world(top, 3)
            poke(mon, sym["trtNextHi"], 0xff)
            poke(mon, sym["scrollFine"], 7)
        results["world_prepare"] = stat(
            "turretWorldTick, the scrollFine == 7 preparation frame",
            timed("turretWorldTick", prepare_frame))

        def coarse_frame():
            prepare_frame()
            call("turretWorldTick")
            nxt = (top - 1) % STAGE_ROWS
            poke(mon, sym["stageTopRowLo"], nxt & 0xff)
            poke(mon, sym["stageTopRowHi"], nxt >> 8)
            poke(mon, sym["scrollFine"], 0)
        results["world_coarse"] = stat(
            "turretWorldTick, the coarse step adopting its shadow",
            timed("turretWorldTick", coarse_frame))

        print()
        check("an ordinary frame pays under 40 cycles for firing and damage",
              results["fire_none"] + results["hit_none"]
              + results["invuln_off"] < 40,
              f"{results['fire_none']} + {results['hit_none']} + "
              f"{results['invuln_off']}")
        # THE BOUND IS FOR TWO SIMULTANEOUS LAUNCHES, because that is what the
        # bench sets up: every timer armed with both visible turrets on the
        # aperture, so one call spawns two projectiles. A turret fires at most
        # once per hundred frames and at most two are ever visible, so this is
        # the rarest frame the system can produce, not a typical one.
        check("the busiest firing frame -- two launches at once -- stays "
              "under 800 cycles",
              results["fire_shot"] < 800, str(results["fire_shot"]))
        check("three projectiles in flight cost under 400 cycles to test",
              results["hit_three"] < 400, str(results["hit_three"]))
        check("the coarse-step and preparation frames are untouched by firing",
              results["world_coarse"] < 750 and results["world_prepare"] < 1200,
              f"coarse {results['world_coarse']} prepare "
              f"{results['world_prepare']}")
    finally:
        v.close()
        print(f"\n  launched and reaped: {LAUNCHED_PIDS}")


# ===========================================================================
def production():
    """THE REGRESSION. The real frame loop, with nothing poked at all.

    This section exists because every other firing check in this file drives
    turretFireTick directly, and a routine called in a loop never advances a
    frame -- so the scroller never takes a coarse step, and the whole of the
    interaction that broke firing in the actual game was invisible.

    What broke it: turretWorldTick blanked turretVisible[] for ALL EIGHT
    turrets at every coarse step, as the aim pass's cheap reject path.
    turretAimTick arms the fire clock on the turretVisible 0 -> 1 transition,
    so the blank manufactured an arrival every eight frames for a turret that
    had not moved, and turretFireTimer ran

        100, 99, 98, 97, 96, 95, 94, 93, 100, 99, ...

    for ever against an interval of 100. No turret could ever fire, in any
    real game, ever -- while this file reported sixteen green firing checks.

    So the assertions below are about a FREE-RUNNING PRODUCTION MACHINE and
    nothing else: no poked visibility, no poked timer, no hijacked PC.
    """
    print("\n=== 4. the production frame loop (the regression) ===")
    total, cols, rows = TM.authored()
    v = Vice(6636, PRG, warp=True)
    try:
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # --- FIND A TURRET THAT HAS JUST ARRIVED, then sample every frame --
        # Not merely "any turret visible": that caught one at the END of its
        # pass, which then left the aperture a few frames into the sample and
        # produced no run long enough to span a coarse step. A turret whose
        # fire timer is still near the full interval was armed recently, so it
        # has most of its ~176 visible frames ahead of it. That is exactly the
        # turret this section wants to watch.
        fresh = None
        for _ in range(60):
            vis = rd(mon, sym["turretVisible"], total)
            tmr = rd(mon, sym["turretFireTimer"], total)
            cand = [i for i in range(total)
                    if vis[i] and tmr[i] >= OLD_FIRE_INTERVAL - 12]
            if cand:
                fresh = cand[0]
                break
            free_run(mon, sym["frameCounter"], 0.25)
            mon.cmd("delete")
        check("a freshly arrived turret was found to watch",
              fresh is not None, f"turret {fresh}")

        # NO SLEEPS, and the frame counter carried with every sample. A
        # settle-time sampler was tried first and was not reliable: at 0.02s
        # every frame read turretVisible all zero, and at 0.06s it worked on
        # one run and not the next. Timing the monitor measures the harness.
        # tests/test_slice_b.py's steps() already solved this -- carry the
        # frame number and keep only genuinely consecutive samples.
        bp = set_bp(mon, sym["turretFireTick"])
        raw = []
        for _ in range(90):
            mon.cmd("x")
            f = rd(mon, sym["frameCounter"], 2)
            raw.append((
                f[0] | (f[1] << 8),
                rd(mon, sym["scrollFine"])[0],
                rd(mon, sym["turretVisible"], total),
                rd(mon, sym["turretFireTimer"], total),
            ))
        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        # EVERY contiguous segment, not just the longest: a dropped sample in
        # the middle should cost the two halves' junction, not all the data
        # on one side of it.
        uniq = [r for i, r in enumerate(raw) if i == 0 or r[0] != raw[i - 1][0]]
        segs, cur = [], uniq[:1]
        for a, c in zip(uniq, uniq[1:]):
            if ((c[0] - a[0]) & 0xffff) == 1:
                cur.append(c)
            else:
                segs.append(cur); cur = [c]
        segs.append(cur)
        segs = [[(r[1], r[2], r[3]) for r in g] for g in segs if len(g) >= 2]
        frames = max(segs, key=len) if segs else []
        check("a long contiguous run of production frames was captured",
              len(frames) >= 30,
              f"{len(frames)} longest of {len(raw)} samples in {len(segs)} segments")

        # --- a coarse step really did happen in that window ----------------
        steps = sum(1 for seg in segs for a, b in zip(seg, seg[1:]) if b[0] < a[0])
        check("the sample window spans several coarse steps",
              steps >= 4, f"{steps} steps in {len(frames)} frames")

        # --- THE ASSERTION -------------------------------------------------
        # For every turret, over every maximal run of consecutive frames in
        # which it was continuously combat-visible, the timer must fall by
        # exactly one per frame. A coarse step inside that run must change
        # nothing: the turret did not go anywhere.
        worst = None
        runs = 0
        for t in range(total):
          for seg in segs:
            run = []
            for f in seg + [None]:
                if f is not None and f[1][t]:
                    run.append(f)
                    continue
                if len(run) >= 10:
                    runs += 1
                    crossed = any(b[0] < a[0] for a, b in zip(run, run[1:]))
                    if crossed:
                        for a, b in zip(run, run[1:]):
                            # A reload FROM ZERO is the turret taking its shot,
                            # or having it refused -- either way the interval
                            # restarts, and that is the recovered rule. The
                            # defect is a reload from a NON-ZERO count, which
                            # is the clock being told a turret that never moved
                            # had just arrived.
                            want = (OLD_FIRE_INTERVAL if a[2][t] == 0
                                    else a[2][t] - 1)
                            if b[2][t] != want:
                                worst = (t, a[0], a[2][t], b[0], b[2][t])
                                break
                run = []
        check("at least one turret stayed visible across a coarse step",
              runs >= 1, f"{runs} runs of 10+ visible frames")
        check("a continuously visible turret's fire timer NEVER re-arms -- "
              "this is the exact production defect", worst is None,
              "" if worst is None else
              f"turret {worst[0]}: fine {worst[1]} timer {worst[2]} -> "
              f"fine {worst[3]} timer {worst[4]}")

        # --- and the timer therefore reaches values a fixture never saw ----
        allf = [f for seg in segs for f in seg]
        seen = min(t for f in allf for i, t in enumerate(f[2]) if f[1][i]) \
               if any(any(f[1]) for f in allf) else 999
        check("fire timers reach well below the interval in ordinary play",
              seen < OLD_FIRE_INTERVAL - 20, f"lowest observed {seen}")

        # --- ordinary production population, for the record ---------------
        # The population gate was the other suspect. It is not implicated and
        # this records why: ordinary play is nowhere near it. If a future
        # change makes routine traffic reach the gate, turrets go silent in
        # normal play again and this check is the one that says so.
        pops = []
        for _ in range(25):
            free_run(mon, sym["frameCounter"], 0.4)
            mon.cmd("delete")
            pops.append(rd(mon, sym["logCount"])[0])
        check(f"ordinary production logCount stays under the "
              f"{OLD_FIRE_MAX_POP}-object firing gate",
              max(pops) < OLD_FIRE_MAX_POP,
              f"max {max(pops)} over {len(pops)} samples: {sorted(set(pops))}")

        # --- THE POINT OF THE WHOLE SLICE ---------------------------------
        poke(mon, sym["ebFired"], 0)
        poke(mon, sym["ebRefused"], 0)
        free_run(mon, sym["frameCounter"], 45)
        mon.cmd("delete")
        fired = rd(mon, sym["ebFired"])[0]
        check("THE REAL GAME LAUNCHES HOSTILE PROJECTILES, with nothing poked",
              fired > 0, f"ebFired = {fired} in 45s of ordinary play")
        check("...and the cap refused none of them at ordinary population",
              rd(mon, sym["ebRefused"])[0] == 0,
              str(rd(mon, sym["ebRefused"])[0]))

        # --- the engine is still healthy with firing live ------------------
        for name in ("gameOverrun", "publishSkip", "schedBuildDefer",
                     "scrollLate", "edgeLate"):
            got = rd(mon, sym[name])[0]
            check(f"{name} is still zero after 45s of live firing",
                  got == 0, str(got))
    finally:
        v.close()
        print(f"\n  launched and reaped: {LAUNCHED_PIDS}")


def main():
    print("Turret firing, hostile projectiles, and player damage\n")
    constants()
    ownership()
    machine()
    production()
    print()
    if fails:
        print(f"=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
        return 1
    print("=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
