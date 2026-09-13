#!/usr/bin/env python3
"""Turret combat: pulse, player hitscan, damage, destruction, restoration.

What this proves
----------------
* every combat constant is the old engine's own, read out of the archive:
  health, the pulse table and interval, the hit-flash colour and duration, and
  the sixteen-pixel hitbox that is NOT the enemy scan's twenty-four;
* the arbitration rule is the old one -- one winner per ray, nearest wins,
  and an ENEMY WINS AN EXACT TIE -- and the enemy scan is untouched by it;
* both cannons trace independently, so one volley can take two HP off the same
  turret when the ship is aligned to within a pixel;
* the world -> screen hitbox comes from the engine's own contract, with no
  second scroll counter, and only a wholly visible, living turret can be hit;
* the pulse cycles white/red/yellow/red at the old interval, follows the body
  as it scrolls, gives vacated cells back to the terrain colour, and stops
  when the turret dies;
* a hit flash overrides the pulse and then returns to it;
* a lethal hit clears turretAlive, and BOTH pages get the underlying terrain
  back -- the authoritative decode, not a cached copy -- with colour RAM
  returned to the level's single value and no other turret disturbed;
* turrets still consume no sprite, no logical object and no mux batch.

The model sections need no emulator. The machine section launches exactly one
VICE and reaps it on every path.
"""
import sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import PRG, SYM, symbols, Vice, rd, set_bp, free_run, LAUNCHED_PIDS
from test_p2 import poke
import test_terrain as T
import turret_model as TM
import old_repo

sym = symbols(SYM)
DEFS = T.byte_rows("stage_map.asm", "metatileDefs")
ROWS = T.byte_rows("stage_map.asm", "stageMetatileRows")

# --- the contract, restated independently of the assembler ------------------
STAGE_ROWS, SCREEN_ROWS, SCREEN_COLS = 420, 25, 40
STAGE_START_ROW = STAGE_ROWS - SCREEN_ROWS
SCREEN_A, SCREEN_B = 0x0400, 0x2800
COLOUR_RAM = 0xd800
TERRAIN_COLOUR_RAM = 9
APERTURE_TOP, APERTURE_BOT = 55, 247        # first/last terrain raster
ROW_NONE = 0xff
BODY_W = BODY_H = 2
MAX_OBJECTS = 16

# The authoritative old values. Every one is CHECKED against the archive below.
OLD_HEALTH = 3
OLD_PULSE = [1, 2, 7, 2]
OLD_PULSE_INTERVAL = 8
OLD_HIT_CRAM = 10 | 8
OLD_HIT_FRAMES = 4
OLD_HITBOX_W = 16
OLD_SCORE_PER_KILL = 100

PLAYER_CANNON_L, PLAYER_CANNON_R = 4, 19

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def asm_const(path, name):
    txt = (ROOT / "src" / path).read_text()
    m = re.search(rf"^\.const\s+{name}\s*=\s*([^/\n]+)", txt, re.M)
    return m.group(1).strip() if m else None


# ===========================================================================
def constants():
    print("=== 1. every combat constant is the old engine's own ===")
    if not old_repo.present():
        check("the reference archive is present", False, str(old_repo.ARCHIVE))
        return
    old = old_repo.old_text("src/background_turrets.asm")

    def old_const(name):
        m = re.search(rf"\.const\s+{name}\s*=\s*([^/\n]+)", old)
        return m.group(1).strip() if m else None

    for name, want in (("TURRET_START_HEALTH", str(OLD_HEALTH)),
                       ("TURRET_PULSE_LEN", str(len(OLD_PULSE))),
                       ("TURRET_PULSE_INTERVAL", str(OLD_PULSE_INTERVAL)),
                       ("TURRET_HIT_FRAMES", str(OLD_HIT_FRAMES)),
                       ("TURRET_HIT_CRAM", "10 | 8")):
        got = old_const(name)
        check(f"the old engine's {name} is {want}", got == want, str(got))

    # The pulse table, byte for byte, from the old source.
    m = re.search(r"turretPulseTable:\s*\n?\s*\.byte\s*([0-9,\s]+)", old)
    got = [int(v) for v in m.group(1).split(",")] if m else []
    check(f"the old pulse table is {OLD_PULSE} (white, red, yellow, red)",
          got == OLD_PULSE, str(got))

    # The hitbox width, out of traceTurretCannon itself.
    trace = old[old.index("traceTurretCannon:"):]
    trace = trace[:trace.index("hitCannonTarget:")]
    m = re.search(r"cmp #(\d+)\s*\n\s*bcs", trace)
    check(f"the old turret hitbox is {OLD_HITBOX_W} pixels, not the enemy's 24",
          m and int(m.group(1)) == OLD_HITBOX_W, m.group(1) if m else "?")

    # The eligibility gates, in the old order.
    check("the old trace required alive AND combat-visible",
          "lda TURRET_HEALTH,x" in trace and "lda TURRET_VISIBLE,x" in trace)
    check("the old trace rejected a turret at or below the ship",
          re.search(r"lda TURRET_Y,x\s*\n\s*cmp OBJECT_Y\s*\n\s*bcs", trace)
          is not None)
    check("the old trace required a turret to beat the incumbent STRICTLY "
          "(bcc AND beq reject), so an enemy wins a tie",
          re.search(r"cmp HITSCAN_TARGET_Y\s*\n\s*bcc [^\n]*\n\s*beq", trace)
          is not None)

    # Damage and destruction, out of hitCannonTarget.
    hit = old[old.index("hitCannonTarget:"):]
    hit = hit[:hit.index("TURRET_STATE_BEGIN:")]
    check("one HP per cannon hit, and never below zero",
          "lda TURRET_HEALTH,x" in hit and "beq !done+" in hit
          and "dec TURRET_HEALTH,x" in hit)
    check("a survivable hit reloads the hit timer",
          re.search(r"lda #TURRET_HIT_FRAMES\s*\n\s*sta TURRET_HIT_TIMER,x", hit)
          is not None)
    check("the killing hit does NOT flash: it goes straight to destruction",
          hit.index("!destroy:") > hit.index("sta TURRET_HIT_TIMER,x"))
    check(f"the old game awarded score on destruction (documented, not "
          f"migrated)", "awardKillScore" in hit)

    # The score value, from the old main.asm.
    main = old_repo.old_text("src/main.asm")
    m = re.search(r"\.const\s+SCORE_PER_KILL\s*=\s*(\d+)", main)
    check(f"...and the reward was {OLD_SCORE_PER_KILL}, the same as an enemy",
          m and int(m.group(1)) == OLD_SCORE_PER_KILL, m.group(1) if m else "?")

    # And now that this repo agrees with all of it.
    print("  -- and src/turrets.asm restates them:")
    for name, want in (("TURRET_START_HEALTH", str(OLD_HEALTH)),
                       ("TURRET_PULSE_LEN", str(len(OLD_PULSE))),
                       ("TURRET_PULSE_INTERVAL", str(OLD_PULSE_INTERVAL)),
                       ("TURRET_HIT_FRAMES", str(OLD_HIT_FRAMES)),
                       ("TURRET_HIT_CRAM", "10 | 8"),
                       ("TURRET_SCORE_PER_KILL", str(OLD_SCORE_PER_KILL))):
        got = asm_const("turrets.asm", name)
        check(f"src/turrets.asm {name} = {want}", got == want, str(got))
    ours = (ROOT / "src" / "turrets.asm").read_text()
    m = re.search(r"turretPulseTable:\s*\.byte\s*([0-9,\s]+)", ours)
    got = [int(v) for v in m.group(1).split(",")] if m else []
    check("src/turrets.asm's pulse table is the old one", got == OLD_PULSE,
          str(got))
    check("the hitbox is DERIVED from the body, not restated",
          asm_const("turrets.asm", "TURRET_HITBOX_W") == "TURRET_BODY_W * 8")


# ===========================================================================
# The model: world -> screen, restated independently of the assembler.
# ===========================================================================
def matrix_row(stage_row, top):
    return (stage_row - top) % STAGE_ROWS


def body_geometry(R, top, fine):
    """(paintRow, paintPair, logY, visible) for a turret whose top body row
    is stage row R, on a page whose matrix row 0 is stage row `top`."""
    m = matrix_row(R, top)
    if m < SCREEN_ROWS:
        paint_row = m
        paint_pair = 1 if m < SCREEN_ROWS - 1 else 0
        # logY AND visible ARE COMBAT QUANTITIES AND ARE DEFINED ONLY FOR A BODY
        # WHOLLY ON THE PAGE. With one body row on the page the other is off it,
        # so there is no 16-pixel body to place and logY reads 0 rather than a
        # number derived from the wrong row. That is the contract turretAimTick
        # states, and it is not cosmetic: deriving logY from the single on-page
        # row of a body that is ENTERING puts it a whole character too high, and
        # at fine scroll 7 the result lands on exactly raster 55 and reads as
        # fully visible. This model found that.
        if not paint_pair:
            return paint_row, 0, 0, 0
        log_y = 47 + fine + 8 * m
        top_raster = log_y + 1
        visible = (top_raster >= APERTURE_TOP
                   and top_raster + BODY_H * 8 - 1 <= APERTURE_BOT)
        return paint_row, paint_pair, log_y, int(visible)
    if m == STAGE_ROWS - 1:
        # The authored row is just above matrix row 0: only the BOTTOM body row
        # is on the page, and half a body is never combat-visible.
        return 0, 0, 0, 0
    return ROW_NONE, 0, 0, 0


def mapping():
    print("\n=== 2. world -> screen, from the engine's own contract ===")
    total, cols, rows = TM.authored()

    # The contract's relation, and nothing else.
    top = (STAGE_START_ROW - 0) % STAGE_ROWS
    check(f"at worldProgress 0 matrix row 0 is stage row {STAGE_START_ROW}",
          top == STAGE_START_ROW)

    # A turret walks DOWN the aperture, one matrix row per coarse step, and is
    # combat-visible only while the whole body is inside rasters 55..247.
    R = rows[0]
    seen = []
    for prog in range(STAGE_ROWS):
        t = (STAGE_START_ROW - prog) % STAGE_ROWS
        pr, pp, ly, vis = body_geometry(R, t, 0)
        if vis:
            seen.append(matrix_row(R, t))
    check("turret 0 is combat-visible on a contiguous run of matrix rows",
          seen == list(range(min(seen), max(seen) + 1)), f"{min(seen)}..{max(seen)}")
    check("...which excludes the partly clipped top and bottom rows",
          min(seen) == 1 and max(seen) == 23, f"{min(seen)}..{max(seen)}")

    # The window SLIDES with the fine scroll and never changes width: the
    # aperture is 193 rasters and a body is 16, so 23 whole character rows of
    # body always fit, wherever the eight-pixel phase has put them.
    spans = []
    for fine in range(8):
        s = [matrix_row(R, (STAGE_START_ROW - p) % STAGE_ROWS)
             for p in range(STAGE_ROWS)
             if body_geometry(R, (STAGE_START_ROW - p) % STAGE_ROWS, fine)[3]]
        spans.append((min(s), max(s)))
    # 193 aperture rasters is 24.125 character rows, so how many WHOLE 16-pixel
    # bodies fit depends on the eight-pixel phase: 23 at the two ends of the
    # phase and 22 in between. That is geometry, not a tolerance.
    check("the hittable window is 22 or 23 matrix rows at every fine phase",
          all(22 <= hi - lo + 1 <= 23 for lo, hi in spans), str(spans))
    check("...and never contains a row whose body the aperture clips",
          all(48 + f + 8 * lo >= APERTURE_TOP
              and 48 + f + 8 * hi + BODY_H * 8 - 1 <= APERTURE_BOT
              for f, (lo, hi) in enumerate(spans)), str(spans))
    check("...and slides down one row over the phase: 1..23 at fine 0, "
          "0..22 at fine 7", spans[0] == (1, 23) and spans[7] == (0, 22),
          str(spans))

    # The body is drawn wherever a body row is on the page, which is a WIDER
    # window than combat: that difference is the bug the old game shipped.
    drawn = [p for p in range(STAGE_ROWS)
             if body_geometry(R, (STAGE_START_ROW - p) % STAGE_ROWS, 0)[0]
             != ROW_NONE]
    combat = [p for p in range(STAGE_ROWS)
              if body_geometry(R, (STAGE_START_ROW - p) % STAGE_ROWS, 0)[3]]
    check("a turret is DRAWN on more coarse steps than it is hittable",
          len(drawn) > len(combat), f"{len(drawn)} drawn, {len(combat)} hittable")
    check("and every hittable step is also a drawn step",
          set(combat) <= set(drawn))

    # How many can be hittable at once? The report needs the real number.
    worst, worst_p = 0, 0
    for prog in range(STAGE_ROWS):
        t = (STAGE_START_ROW - prog) % STAGE_ROWS
        for fine in range(8):
            n = sum(body_geometry(r, t, fine)[3] for r in rows)
            if n > worst:
                worst, worst_p = n, prog
    check(f"at most {worst} turrets can be hittable at once in level 1",
          worst == 2, f"{worst} at worldProgress {worst_p}")

    drawnmax = 0
    for prog in range(STAGE_ROWS):
        t = (STAGE_START_ROW - prog) % STAGE_ROWS
        n = sum(1 for r in rows if body_geometry(r, t, 0)[0] != ROW_NONE)
        drawnmax = max(drawnmax, n)
    check(f"and at most {drawnmax} can be painted at once",
          drawnmax == 2, str(drawnmax))

    # The hitbox X is constant and is the body.
    for i, c in enumerate(cols):
        x = 24 + c * 8
        check(f"turret {i}: body columns {c},{c+1} are sprite X {x}..{x+15}",
              x + OLD_HITBOX_W - 1 == 24 + (c + 2) * 8 - 1)
        break


# ===========================================================================
def ownership():
    print("\n=== 3. combat consumes no sprite or object resource ===")
    src = re.sub(r"//.*", "", (ROOT / "src" / "turrets.asm").read_text())
    writes = sorted(set(re.findall(r"st[axy]\s+\$(d0[0-9a-f]{2})", src, re.I)))
    check("turrets.asm still writes NO VIC register", not writes, str(writes))
    check("...and still does not name one",
          not re.findall(r"\$(d0[0-9a-f]{2})", src, re.I))
    for token in ("objectAlloc", "objectActivate", "objectFree", "logActive",
                  "logCount", "logY,", "logPtr", "sortedIDs", "schedBatches",
                  "MUX_", "spritePtr", "$d015", "$d01e"):
        check(f"turrets.asm never mentions {token}", token not in src)
    # It DOES write colour RAM now, and only through one routine.
    cram = re.findall(r"(?<![A-Z_])COLOUR_RAM", src)
    check("colour RAM is reached from exactly one place", len(cram) == 1,
          f"{len(cram)} references")
    check("and that place is paintTurretCells",
          re.search(r"paintTurretCells:(?:(?!\n\s*rts).)*COLOUR_RAM", src, re.S)
          is not None)

    coll = re.sub(r"//.*", "", (ROOT / "src" / "collision.asm").read_text())
    check("collision.asm still reads no $d01e", "d01e" not in coll.lower())
    check("the turret trace runs AFTER the enemy scan, which is the tie-break",
          coll.index("jsr traceTurretRay") > coll.index("cpx #MAX_OBJECTS"))
    check("applyDamage dispatches on the target kind",
          re.search(r"applyDamage:\s*\n\s*lda csTargetKind", coll) is not None)


# ===========================================================================
def machine():
    print("\n=== 4. the 6502 ===")
    total, cols, rows = TM.authored()

    v = Vice(6623, PRG, warp=True)
    try:
        mon = v.mon

        # --- a clean production run FIRST, before any PC hijacking ---------
        free_run(mon, sym["frameCounter"], 3)
        mon.cmd("delete")
        for name in ("gameOverrun", "publishSkip", "scrollLate", "edgeLate"):
            got = rd(mon, sym[name])[0]
            check(f"{name} is zero with turret combat live", got == 0, str(got))
        check("the top split still lands on 54..55",
              54 <= rd(mon, sym["topSplitMin"])[0]
              and rd(mon, sym["topSplitMax"])[0] <= 55)
        check("the bottom split still lands on 248",
              rd(mon, sym["botSplitMin"])[0] == 248
              == rd(mon, sym["botSplitMax"])[0])

        health = rd(mon, sym["turretHealth"], total)
        alive = rd(mon, sym["turretAlive"], total)
        check(f"every turret boots with {OLD_HEALTH} health",
              health == [OLD_HEALTH] * total, str(health))
        check("every turret boots alive", alive == [1] * total, str(alive))
        check("nothing has been destroyed", rd(mon, sym["trtKills"])[0] == 0)
        check("no page repair is owed", rd(mon, sym["trtDeadPending"])[0] == 0)

        # ------------------------------------------------------------------
        # A deterministic bench. From here on the PC is hijacked, so the
        # counters read above are no longer meaningful -- which is why they
        # were read above.
        # ------------------------------------------------------------------
        def call(routine):
            mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym[routine]:04x}")
            bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
            mon.cmd(f"r pc={sym['mainLoop']:04x}"); mon.cmd("delete")

        def set_world(top, fine):
            poke(mon, sym["stageTopRowLo"], top & 0xff)
            poke(mon, sym["stageTopRowHi"], top >> 8)
            poke(mon, sym["scrollFine"], fine)
            call("turretWorldTick")

        def clear_objects():
            for i in range(MAX_OBJECTS):
                poke(mon, sym["logActive"] + i, 0)

        def fire(x, y, rays=1, x2=None):
            poke(mon, sym["shotY"], y)
            poke(mon, sym["shotXLo"] + 0, x & 0xff)
            poke(mon, sym["shotXHi"] + 0, x >> 8)
            if x2 is not None:
                poke(mon, sym["shotXLo"] + 1, x2 & 0xff)
                poke(mon, sym["shotXHi"] + 1, x2 >> 8)
            poke(mon, sym["shotRays"], rays)
            poke(mon, sym["shotFired"], 1)
            call("collisionTick")

        clear_objects()

        # --- THE PULSE, driven one frame at a time -------------------------
        # turretPaintTick is called exactly once per gameFrame, so calling it
        # directly IS a frame of pulse, and it is the only way to sample this
        # deterministically. Breakpointing it and counting stops does not work:
        # the remote monitor returns from `x` on a prompt echo rather than on
        # the actual stop, so the number of stops per frame is one or two and
        # not fixed. Sampling that way first reported a 16-frame interval and
        # then a 9-frame phase -- two different wrong answers about a machine
        # that was right both times.
        idx, col = [], []
        for _ in range(OLD_PULSE_INTERVAL * len(OLD_PULSE) + 4):
            call("turretPaintTick")
            idx.append(rd(mon, sym["trtPulseIndex"])[0])
            col.append(rd(mon, sym["trtPulseColour"])[0] & 0x0f)

        runs = []
        for v_ in idx:
            if runs and runs[-1][0] == v_:
                runs[-1][1] += 1
            else:
                runs.append([v_, 1])
        check("the pulse index cycles 0,1,2,3,0,... in order",
              all((runs[i + 1][0] - runs[i][0]) % len(OLD_PULSE) == 1
                  for i in range(len(runs) - 1)),
              str([r[0] for r in runs]))
        inner = [r[1] for r in runs[1:-1]]
        check(f"and holds each phase for exactly {OLD_PULSE_INTERVAL} frames",
              inner and all(n == OLD_PULSE_INTERVAL for n in inner), str(inner))
        want_cols = [(c | 8) & 0x0f for c in OLD_PULSE]
        check(f"the colours are the old table OR'd with the multicolour bit "
              f"{want_cols}", sorted(set(col)) == sorted(set(want_cols)),
              str(sorted(set(col))))
        check("...and each phase paints the colour its own table entry names",
              all(col[k] == want_cols[idx[k]] for k in range(len(idx))))


        # --- the world tick against the model ------------------------------
        bad = []
        for prog, fine in ((50, 0), (55, 3), (60, 7), (74, 0), (0, 0), (49, 7)):
            top = (STAGE_START_ROW - prog) % STAGE_ROWS
            set_world(top, fine)
            got = (rd(mon, sym["turretPaintRow"], total),
                   rd(mon, sym["turretPaintPair"], total),
                   rd(mon, sym["turretLogY"], total),
                   rd(mon, sym["turretVisible"], total))
            want = tuple(list(t) for t in
                         zip(*[body_geometry(r, top, fine) for r in rows]))
            if got != want:
                bad.append((prog, fine, got, want))
        check("turretWorldTick matches the model at every sampled origin",
              not bad, str(bad[:1]))

        # --- a hit, and the 16-pixel hitbox --------------------------------
        # Put turret 0 in the middle of the aperture and fire up its column.
        i = 0
        R, C = rows[i], cols[i]
        top = (R - 12) % STAGE_ROWS             # body at matrix row 12
        set_world(top, 0)
        ly = rd(mon, sym["turretLogY"], total)[i]
        vis = rd(mon, sym["turretVisible"], total)[i]
        check(f"turret {i} is combat-visible at matrix row 12", vis == 1)
        tx = 24 + C * 8
        shot_y = ly + 40                        # the ship, comfortably below

        for dx, want_hit in ((0, True), (15, True), (-1, False),
                             (OLD_HITBOX_W, False)):
            poke(mon, sym["turretHealth"] + i, OLD_HEALTH)
            poke(mon, sym["turretHitTimer"] + i, 0)
            fire(tx + dx, shot_y)
            hp = rd(mon, sym["turretHealth"], total)[i]
            check(f"a ray at turretX{dx:+d} "
                  f"{'hits' if want_hit else 'misses'}",
                  (hp == OLD_HEALTH - 1) == want_hit, f"health {hp}")

        # --- the hit flash --------------------------------------------------
        poke(mon, sym["turretHealth"] + i, OLD_HEALTH)
        poke(mon, sym["turretHitTimer"] + i, 0)
        fire(tx, shot_y)
        check(f"a survivable hit starts a {OLD_HIT_FRAMES}-frame flash",
              rd(mon, sym["turretHitTimer"], total)[i] == OLD_HIT_FRAMES,
              str(rd(mon, sym["turretHitTimer"], total)[i]))

        # The flash colour overrides the pulse while it runs, then returns.
        cram_at = lambda row, col: rd(mon, COLOUR_RAM + row * 40 + col)[0] & 0x0f
        call("turretPaintTick")
        check("...and the body's colour RAM is the hit colour, not the pulse",
              cram_at(12, C) == OLD_HIT_CRAM & 0x0f
              and cram_at(13, C + 1) == OLD_HIT_CRAM & 0x0f,
              f"{cram_at(12, C)}, {cram_at(13, C+1)}")
        for _ in range(OLD_HIT_FRAMES + 1):
            call("turretPaintTick")
        pulse = rd(mon, sym["trtPulseColour"])[0] & 0x0f
        check("after it expires the pulse colour comes back",
              rd(mon, sym["turretHitTimer"], total)[i] == 0
              and cram_at(12, C) == pulse, f"cram {cram_at(12, C)} pulse {pulse}")

        # --- eligibility: off-screen and dead turrets cannot be hit ---------
        poke(mon, sym["turretHealth"] + i, OLD_HEALTH)
        set_world((R - 40) % STAGE_ROWS, 0)     # far below the aperture
        check(f"turret {i} is not combat-visible off the page",
              rd(mon, sym["turretVisible"], total)[i] == 0)
        fire(tx, 200)
        check("an off-page turret cannot be hit",
              rd(mon, sym["turretHealth"], total)[i] == OLD_HEALTH)

        set_world(top, 0)
        poke(mon, sym["turretAlive"] + i, 0)
        fire(tx, shot_y)
        check("a destroyed turret cannot be hit again",
              rd(mon, sym["turretHealth"], total)[i] == OLD_HEALTH)
        poke(mon, sym["turretAlive"] + i, 1)

        # A ray fired from ABOVE the turret travels up, away from it.
        fire(tx, ly)
        check("a ray whose origin is at the turret's own Y misses it",
              rd(mon, sym["turretHealth"], total)[i] == OLD_HEALTH)

        # --- dual cannon: both rays can damage the SAME turret --------------
        poke(mon, sym["turretHealth"] + i, OLD_HEALTH)
        fire(tx + PLAYER_CANNON_L - PLAYER_CANNON_L, shot_y, rays=2,
             x2=tx + PLAYER_CANNON_R - PLAYER_CANNON_L)
        hp = rd(mon, sym["turretHealth"], total)[i]
        check("both cannons can damage one turret in a single volley",
              hp == OLD_HEALTH - 2, f"health {hp}")
        check(f"which is why {OLD_HEALTH} health is two volleys, not three",
              OLD_HEALTH - 2 == 1)

        # --- an enemy wins an exact tie ------------------------------------
        poke(mon, sym["turretHealth"] + i, OLD_HEALTH)
        poke(mon, sym["logActive"] + 3, 1)
        poke(mon, sym["objType"] + 3, 1)            # TYPE_ENEMY
        poke(mon, sym["objHP"] + 3, 6)
        poke(mon, sym["logY"] + 3, ly)              # EXACTLY the turret's Y
        poke(mon, sym["logX"] + 3, tx & 0xff)
        poke(mon, sym["logXHi"] + 3, tx >> 8)
        fire(tx, shot_y)
        check("at an exact Y tie the ENEMY takes the hit, not the turret",
              rd(mon, sym["objHP"], MAX_OBJECTS)[3] == 5
              and rd(mon, sym["turretHealth"], total)[i] == OLD_HEALTH,
              f"enemy {rd(mon, sym['objHP'], MAX_OBJECTS)[3]}, "
              f"turret {rd(mon, sym['turretHealth'], total)[i]}")

        # ...and one pixel nearer, the turret wins.
        poke(mon, sym["objHP"] + 3, 6)
        poke(mon, sym["logY"] + 3, ly - 1)
        fire(tx, shot_y)
        check("one pixel farther away, the enemy loses to the turret",
              rd(mon, sym["objHP"], MAX_OBJECTS)[3] == 6
              and rd(mon, sym["turretHealth"], total)[i] == OLD_HEALTH - 1,
              f"enemy {rd(mon, sym['objHP'], MAX_OBJECTS)[3]}, "
              f"turret {rd(mon, sym['turretHealth'], total)[i]}")
        clear_objects()

        # --- destruction, and the restoration contract ----------------------
        # Put the body on the displayed page and give the back page its own,
        # different origin, so the repair has to use each page's own mapping.
        disp_top = top
        back_top = (top - 1) % STAGE_ROWS
        poke(mon, sym["turretAlive"] + i, 1)
        poke(mon, sym["turretHealth"] + i, 1)
        poke(mon, sym["dispPage"], 0)
        poke(mon, sym["regenPageHi"], SCREEN_B >> 8)
        poke(mon, sym["regenTopRowLo"], back_top & 0xff)
        poke(mon, sym["regenTopRowHi"], back_top >> 8)
        set_world(disp_top, 0)

        # Compose both pages the way the scroller would, so there really is a
        # body to remove.
        def build_page(page_hi, page_top):
            poke(mon, sym["regenPageHi"], page_hi)
            poke(mon, sym["regenTopRowLo"], page_top & 0xff)
            poke(mon, sym["regenTopRowHi"], page_top >> 8)
            poke(mon, sym["regenRow"], 0)
            for _ in range(SCREEN_ROWS):
                call("renderRow")
                poke(mon, sym["regenRow"],
                     rd(mon, sym["regenRow"])[0] + 1)
        build_page(SCREEN_A >> 8, disp_top)
        build_page(SCREEN_B >> 8, back_top)
        poke(mon, sym["regenTopRowLo"], back_top & 0xff)
        poke(mon, sym["regenTopRowHi"], back_top >> 8)
        poke(mon, sym["regenPageHi"], SCREEN_B >> 8)

        mrow_a = matrix_row(R, disp_top)
        mrow_b = matrix_row(R, back_top)
        body = set(range(226, 230))
        a_before = rd(mon, SCREEN_A + mrow_a * 40 + C, 2)
        b_before = rd(mon, SCREEN_B + mrow_b * 40 + C, 2)
        check("the body really is on both pages before the kill",
              set(a_before) <= body and set(b_before) <= body,
              f"A {a_before} B {b_before}")

        kills_before = rd(mon, sym["trtKills"])[0]
        fire(tx, shot_y)
        check("the lethal hit clears turretAlive",
              rd(mon, sym["turretAlive"], total)[i] == 0)
        check("...and counts the kill",
              rd(mon, sym["trtKills"])[0] == kills_before + 1)
        pend = rd(mon, sym["trtDeadPending"])[0]
        check("...and flags the pages as owing a repair", pend & (1 << i),
              f"${pend:02x}")
        check("the body is STILL on the page until the repair runs",
              set(rd(mon, SCREEN_A + mrow_a * 40 + C, 2)) <= body)

        call("turretRestoreTick")
        check("after turretRestoreTick nothing is owed",
              rd(mon, sym["trtDeadPending"])[0] == 0)

        # Both pages must now hold the authoritative terrain for those rows.
        bad = []
        for page, page_top, base in ((SCREEN_A, disp_top, "A"),
                                     (SCREEN_B, back_top, "B")):
            for half in range(BODY_H):
                mrow = matrix_row(R + half, page_top)
                got = rd(mon, page + mrow * 40, SCREEN_COLS)
                want = T.expand(DEFS, ROWS, (R + half) % STAGE_ROWS)
                if got != want:
                    bad.append((base, half, got[C:C + 2], want[C:C + 2]))
        check("both pages now hold the authoritative terrain for the body's "
              "rows, all forty columns", not bad, str(bad[:2]))

        call("turretPaintTick")
        check("the dead turret's colour RAM is back to the level's terrain "
              "colour",
              cram_at(mrow_a, C) == TERRAIN_COLOUR_RAM
              and cram_at(mrow_a + 1, C + 1) == TERRAIN_COLOUR_RAM,
              f"{cram_at(mrow_a, C)}, {cram_at(mrow_a + 1, C + 1)}")

        # THE WHOLE COLOUR RAM, against the whole model. The invariant is not
        # "everything is terrain colour" -- turret 1 is at stage row 337, four
        # matrix rows above this one, and is alive and legitimately pulsing.
        # It is "every cell is terrain colour EXCEPT the cells of a living
        # turret that is on the page", and naming them is what makes the check
        # worth having: a stale cell left behind by a body that has scrolled
        # away or died would fail it wherever it was.
        # A FULL EXPECTED IMAGE, NOT "IS IT DIFFERENT FROM TERRAIN". Pulse phase
        # 0 is white | 8 = 9, which is EXACTLY TERRAIN_COLOUR_RAM, so a painted
        # cell is indistinguishable from an unpainted one at one phase in four.
        # A check written as "the painted cells are the ones that differ"
        # therefore passes or fails on the pulse phase the test happens to
        # land on -- which is how the first version of this reported a missing
        # turret that was being painted perfectly.
        alive_now = rd(mon, sym["turretAlive"], total)
        timers = rd(mon, sym["turretHitTimer"], total)
        pulse = rd(mon, sym["trtPulseColour"])[0] & 0x0f
        want = [TERRAIN_COLOUR_RAM] * 1000
        painted = 0
        for j, r in enumerate(rows):
            if not alive_now[j]:
                continue
            pr, pp, _, _ = body_geometry(r, disp_top, 0)
            if pr == ROW_NONE:
                continue
            colour = (OLD_HIT_CRAM & 0x0f) if timers[j] else pulse
            for dr in range(pp + 1):
                for dc in range(BODY_W):
                    want[(pr + dr) * 40 + cols[j] + dc] = colour
                    painted += 1
        cram = [b & 0x0f for b in rd(mon, COLOUR_RAM, 256)
                + rd(mon, COLOUR_RAM + 256, 256) + rd(mon, COLOUR_RAM + 512, 256)
                + rd(mon, COLOUR_RAM + 768, 232)]
        wrong = [k for k in range(1000) if cram[k] != want[k]]
        check(f"the whole of colour RAM matches the model: terrain colour "
              f"everywhere but the {painted} cells of the living on-page turret",
              not wrong,
              f"first wrong cell {wrong[0] if wrong else '-'} "
              f"(row {wrong[0] // 40 if wrong else '-'}, "
              f"col {wrong[0] % 40 if wrong else '-'}) "
              f"got {cram[wrong[0]] if wrong else '-'} "
              f"want {want[wrong[0]] if wrong else '-'}")

        # The other seven are untouched.
        alive = rd(mon, sym["turretAlive"], total)
        health = rd(mon, sym["turretHealth"], total)
        check("every other turret is still alive at full health",
              alive == [0 if j == i else 1 for j in range(total)]
              and health[1:] == [OLD_HEALTH] * (total - 1),
              f"{alive} {health}")

        # A future regeneration keeps it dead.
        build_page(SCREEN_A >> 8, disp_top)
        got = rd(mon, SCREEN_A + mrow_a * 40, SCREEN_COLS)
        check("a later regeneration still omits the dead turret",
              got == T.expand(DEFS, ROWS, R % STAGE_ROWS), f"{got[C:C+2]}")
    finally:
        v.close()
        print(f"\n  launched and reaped: {LAUNCHED_PIDS}")


def main():
    print("Turret combat: pulse, hitscan, damage, destruction, restore\n")
    constants()
    mapping()
    ownership()
    machine()
    print()
    if fails:
        print(f"=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
        return 1
    print("=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
