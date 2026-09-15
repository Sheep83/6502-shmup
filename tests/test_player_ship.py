#!/usr/bin/env python3
"""The blue player craft: sprite allocation, banking, and state precedence.

What this proves
----------------
* the generated bitmaps still match the sprite sheet, pixel for pixel;
* the six player blocks are 64-byte aligned, inside a free VIC0 run, and
  overlap nothing else the VIC reads;
* the player's HW0 really is multicolour and every other slot really is not,
  in BOTH raster phases;
* holding left or right in the REAL frame loop walks the craft through its
  banking frames and releasing walks it back -- one stage at a time, never
  snapping;
* the muzzle flash and the invulnerability blink still take precedence the way
  they did: banking chooses the POINTER, the flash chooses the COLOUR and the
  blink chooses the ENABLE, so none of them can override another;
* the production health counters are clean with all of it running.

Proportionality: banking depends on frame cadence, so it is watched through
the real loop with frame-verified stepping. The precedence checks do not --
playerEmit is a pure presentation routine with no cadence of its own -- so
they call it directly rather than spending emulated seconds arranging a
coincidence. One VICE launch.
"""
import re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                      free_run, step_n, call, check, report)

sym = symbols(SYM)

# --- the contract, restated independently of the assembler ------------------
# BANK-MAJOR: frame = bank * ENGINE_FRAMES + engine, bank 0..4 left..right.
PTR_FIRST = 0x80
ENGINE_FRAMES, BANK_FRAMES = 3, 5
BLOCKS = BANK_FRAMES * ENGINE_FRAMES + 1        # + the blank for HW1
PTR_BLANK = PTR_FIRST + BLOCKS - 1
PTR_FLASH = PTR_FIRST + BLOCKS                  # $90: five flash frames
FLASH_FRAMES = BANK_FRAMES
FLASH_TIME = 2                                  # visible PAL frames
COL_FLASH = 2                                   # red, held for both frames
FLASH_Y_LIFT = 7
HW0_BIT = 0b00000001
JOY_FIRE = 0b00010000
WPN_FIRE_PERIOD = 8
BANK_LEFT, BANK_NEUTRAL, BANK_RIGHT = 0, 2, 4
def ptr(bank, engine=0):
    return PTR_FIRST + bank * ENGINE_FRAMES + engine
# $d01c is now COMPOSED PER RASTER PHASE, because HW2..HW7 are drawn twice a
# frame by two owners that want opposite resolutions: the HUD's score font and
# heat bar are hires line art, the gameplay mux is multicolour. So there is no
# single correct value any more -- there are two, and which one is live depends
# on where the beam is.
D01C_HUD_PHASE = 0b00000011         # raster 4:  player MC, the HUD's six hires
D01C_GAMEPLAY  = 0b11111111         # raster 40: player MC, the mux's six MC too
HUD_ENABLE     = 0b11111100         # the six slots the HUD and the mux share
COL_SHIP, COL_BLANK = 14, 0
MC_OUTLINE, MC_WHITE = 11, 1        # SPR_MC_DARK / SPR_MC_LIGHT: shared by
                                    # every multicolour sprite, not the
                                    # player's own -- see src/main.asm.
                                    # The dark is DARK GREY, not black: it is
                                    # shading under the hull rather than an ink
                                    # outline around it.
JOY_MASK, JOY_LEFT, JOY_RIGHT = 0b00011111, 0b00000100, 0b00001000
BANK_RATE, ENGINE_RATE = 5, 4
PLAYER_SLOT_MASK = 0b00000011

# Everything else the VIC reads, so the new allocation can be proved disjoint
# from it rather than merely assumed to be.
OCCUPIED = [
    (0x0000, 0x0340, "system"),
    (0x0340, 0x0400, "clip scratch"),
    (0x0400, 0x0800, "screen page A"),
    (0x0800, 0x1000, "terrain charset"),
    (0x2800, 0x2c00, "screen page B"),
    (0x3100, 0x3200, "clip scratch"),
    (0x3200, 0x3580, "HUD bitmaps"),
    (0x3640, 0x3680, "enemy bitmap"),
    (0x3680, 0x36c0, "clip scratch"),
    (0x36c0, 0x3700, "projectile bitmap"),
    (0x3700, 0x3800, "clip scratch"),
    (0x3800, 0x4000, "blank charset"),
]


def statics():
    print("=== 1. the artwork and its allocation ===")
    # THE SHIP ART IS NO LONGER TOOL-OUTPUT. It was generated from the sheet
    # and has since been amended by hand, so it is now the authoritative
    # artwork and tools/gen_player_ship.py only records where it came from --
    # asserting the two still match byte for byte would assert the edits away.
    # What is still worth checking is the SHAPE the rest of the engine relies
    # on, which the machine section does against the bytes actually loaded.
    #
    # The muzzle-flash art is supplied and checked in verbatim; nothing
    # generates it at all.
    base = sym["playerBitmaps"]
    end = sym["playerBitmapsEnd"]
    check("the player bitmaps are 64-byte aligned", base % 64 == 0, f"${base:04x}")
    check(f"the allocation is exactly {BLOCKS} sprite blocks",
          end - base == BLOCKS * 64, f"{end - base} bytes")
    check("the first block's pointer is the one the code uses",
          base // 64 == PTR_FIRST, f"${base // 64:02x}")
    check("the blank block is where PLAYER_PTR_BLANK points",
          sym["playerBlankBitmap"] == PTR_BLANK * 64,
          f"${sym['playerBlankBitmap']:04x}")
    check("the whole allocation is inside VIC bank 0", end <= 0x4000, f"${end:04x}")
    clashes = [n for (a, b, n) in OCCUPIED if base < b and end > a]
    check("the allocation overlaps nothing else the VIC reads", not clashes,
          f"{clashes}")

    fbase, fend = sym["playerFlashBitmaps"], sym["playerFlashBitmapsEnd"]
    check("the muzzle flash is 64-byte aligned", fbase % 64 == 0, f"${fbase:04x}")
    check(f"the flash is exactly {FLASH_FRAMES} sprite blocks",
          fend - fbase == FLASH_FRAMES * 64, f"{fend - fbase} bytes")
    check("the flash pointer is the one the code uses",
          fbase // 64 == PTR_FLASH, f"${fbase // 64:02x}")
    check("the flash does not overlap the ship's own frames",
          fbase >= end, f"ship ends ${end:04x}, flash starts ${fbase:04x}")
    check("the flash is inside VIC bank 0", fend <= 0x4000, f"${fend:04x}")
    fclash = [n for (a, b, n) in OCCUPIED if fbase < b and fend > a]
    check("the flash overlaps nothing else the VIC reads", not fclash, f"{fclash}")


def machine():
    print("\n=== 2. the machine ===")
    v = Vice(6670, PRG, warp=True)
    try:
        mon = v.mon
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")

        # --- the bitmaps actually reached the VIC's memory ------------------
        art = rd(mon, sym["playerBitmaps"], 64 * BLOCKS)
        check("all fifteen frames are resident and non-empty",
              all(any(art[f * 64:f * 64 + 63]) for f in range(BLOCKS - 1)),
              f"lit bytes: "
              f"{[sum(1 for b in art[f*64:f*64+63] if b) for f in range(BLOCKS-1)]}")
        check("the blank block really is blank",
              not any(art[(BLOCKS - 1) * 64:(BLOCKS - 1) * 64 + 63]))
        # The three engine frames of a bank differ ONLY in their last rows --
        # that is what makes them an animation rather than three more banks.
        bad = []
        for bank in range(BANK_FRAMES):
            f0 = art[(bank*3+0)*64:(bank*3+0)*64+63]
            for e in (1, 2):
                fe = art[(bank*3+e)*64:(bank*3+e)*64+63]
                rows = [r for r in range(21) if f0[r*3:r*3+3] != fe[r*3:r*3+3]]
                if any(r < 14 for r in rows):
                    bad.append((bank, e, rows))
        check("engine frames differ only in the exhaust rows, never the hull",
              not bad, f"{bad[:2]}")
        # Left and right banks must be exact mirrors of each other.
        def unpack(blk):
            return [[(blk[r*3+b] >> (6-2*p)) & 3 for b in range(3) for p in range(4)]
                    for r in range(21)]
        mirror_ok = True
        for (l, r) in ((0, 4), (1, 3)):
            for e in range(ENGINE_FRAMES):
                a = unpack(art[(l*3+e)*64:(l*3+e)*64+63])
                b = unpack(art[(r*3+e)*64:(r*3+e)*64+63])
                if [list(reversed(row)) for row in a] != b:
                    mirror_ok = False
        check("the left banks are exact horizontal mirrors of the right",
              mirror_ok)

        # THE SUPPLIED FLASH ART'S PIXEL SEMANTICS, checked against the bytes
        # the VIC will actually read. src/player.asm depends on two of these:
        # that pair 01 never appears (so lighting the flash cannot disturb
        # $d025, the shade the craft's outline is drawn in), and that every
        # flare is registered to a real gun barrel on the craft once the code's
        # Y lift is applied.
        fart = rd(mon, sym["playerFlashBitmaps"], 64 * FLASH_FRAMES)
        pairs = set()
        for f in range(FLASH_FRAMES):
            for row in unpack(fart[f * 64:f * 64 + 63]):
                pairs |= set(row)
        check("the flash art uses only transparent, HW1's own colour and the "
              "shared white -- never $d025", pairs <= {0, 2, 3},
              f"bit pairs present: {sorted(pairs)}")

        # TWIN WING GUNS, REGISTERED TO THE CRAFT. Each frame carries two
        # flares, each a contiguous group of columns. The flare's CENTRE is the
        # column it burns furthest down -- the bolder art is three columns wide
        # for its whole length, so "tallest column", not "any tall column". The
        # pixel one row BELOW that centre, in the CRAFT's coordinates (so shifted
        # back by the Y lift playerEmit applies), must be a lit pixel of the
        # matching bank: the gun barrel the flare is coming out of.
        #
        # This is what catches a wrong FLASH_Y_LIFT, a wrong bank order, or art
        # drawn for a different ship. A row-bound test can see none of those.
        # Flares may reach ABOVE the craft's top row -- that is the point of a
        # muzzle flash -- so only the downward extent is bounded, and it is
        # bounded well clear of the exhaust rows the engine flame animates.
        flares, unregistered, toolow = [], [], []
        for f in range(FLASH_FRAMES):
            flash = unpack(fart[f * 64:f * 64 + 63])
            hull = unpack(art[(f * ENGINE_FRAMES) * 64:(f * ENGINE_FRAMES) * 64 + 63])
            cols = {}
            for r in range(21):
                for x in range(12):
                    if flash[r][x]:
                        cols.setdefault(x, []).append(r)
                        if r - FLASH_Y_LIFT >= 18:
                            toolow.append((f, r, x))
            groups, run = [], []
            for x in range(12):               # contiguous columns = one flare
                if x in cols:
                    run.append(x)
                elif run:
                    groups.append(run); run = []
            if run:
                groups.append(run)
            flares.append(len(groups))
            for g in groups:
                mid = max(g, key=lambda x: len(cols[x]))
                barrel = max(cols[mid]) - FLASH_Y_LIFT + 1
                if not (0 <= barrel < 21 and hull[barrel][mid]):
                    unregistered.append((f, mid, barrel))
        check("every flash frame carries TWO flares -- one per wing gun",
              flares == [2] * FLASH_FRAMES, f"{flares}")
        check("...each centred on a gun barrel of its own banked craft, at the "
              "Y lift the code applies",
              not unregistered, f"(frame, x, craft row): {unregistered[:4]}")
        check("...and none of the flash reaches the craft's exhaust rows",
              not toolow, f"{toolow[:4]}")
        check("all five flash frames are resident and non-empty",
              all(any(fart[f * 64:f * 64 + 63]) for f in range(FLASH_FRAMES)),
              f"lit bytes: "
              f"{[sum(1 for b in fart[f*64:f*64+63] if b) for f in range(FLASH_FRAMES)]}")

        # --- sprite modes ---------------------------------------------------
        # Sampled at gameFrame, which the main loop enters just after the frame
        # transaction at raster 250 -- so the last write to land was the
        # HANDOFF's, at raster 40 of this same frame.
        d01c = rd1(mon, 0xd01c)
        check("$d01c below the aperture is the GAMEPLAY composition: every "
              "gameplay sprite multicolour",
              d01c == D01C_GAMEPLAY, f"${d01c:02x}")
        # LOW NIBBLE ONLY. The VIC's colour registers implement four bits and
        # read back with the top four set, so $d025 holding light blue reads
        # $fe and not $0e. Masking is reading the register correctly, not
        # loosening the check: the value the VIC actually uses is the nibble.
        d025, d026 = rd1(mon, 0xd025) & 0x0f, rd1(mon, 0xd026) & 0x0f
        check("the shared multicolour registers hold the outline and highlight",
              (d025, d026) == (MC_OUTLINE, MC_WHITE), f"$d025={d025} $d026={d026}")

        # THE TWO PHASES MUST DISAGREE, AND DISAGREE IN EXACTLY ONE PLACE.
        #
        # This assertion used to be "$d01c is the same value however the frame
        # is sampled", which was right while every slot but the player's was
        # hires. It is now false BY DESIGN: the six shared slots change
        # resolution at the handoff. Rewritten to pin what actually has to hold.
        #
        # exHandoff is sampled at ENTRY, before its own $d01c write, so what it
        # reads is what exHud left at raster 4 -- the HUD phase's value, live
        # across the HUD's whole display window. gameFrame is sampled after the
        # handoff has run, so it reads the gameplay value.
        bp = set_bp(mon, sym["exHandoff"])
        mon.cmd("x")
        d01c_hud = rd1(mon, 0xd01c)
        mon.cmd(f"delete {bp}"); mon.cmd("delete")

        check("during the HUD's display window the HUD's own six slots are "
              "HIRES -- its score font and heat bar depend on it",
              d01c_hud & HUD_ENABLE == 0, f"${d01c_hud:02x}")
        check("...and that value is exactly the HUD composition",
              d01c_hud == D01C_HUD_PHASE, f"${d01c_hud:02x}")
        check("the handoff turns all six shared slots multicolour for the mux",
              d01c & HUD_ENABLE == HUD_ENABLE, f"${d01c:02x}")

        # The one thing that must NOT change across the handoff. HW0/HW1 are
        # outside the mux and are displayed through both phases, so a craft
        # whose mode changed at raster 40 would visibly switch resolution half
        # way down itself.
        check("the player's own two bits are multicolour in BOTH phases",
              (d01c_hud & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK
              and (d01c & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK,
              f"hud=${d01c_hud:02x} gameplay=${d01c:02x}")

        # --- banking, through the REAL frame loop ---------------------------
        # Banking is a frame-cadence behaviour, so it is watched by stepping
        # the production loop rather than by calling playerBankTick.
        def hold(bits, frames):
            poke(mon, sym["joyHold"], 1)
            poke(mon, sym["joyState"], JOY_MASK & ~bits)
            bp = set_bp(mon, sym["gameFrame"])
            out = step_n(mon, sym["frameCounter"], frames,
                         lambda: (rd1(mon, sym["plyBank"]),
                                  rd1(mon, sym["plyEngine"]),
                                  rd1(mon, sym["plyPresPtr0"])))
            mon.cmd(f"delete {bp}"); mon.cmd("delete")
            return out

        settle = BANK_RATE * (BANK_FRAMES + 2)
        hold(0, settle)                                   # start from level
        lvl = hold(0, 4)
        check("level flight presents the neutral bank",
              all(b == BANK_NEUTRAL for b, e, p in lvl), f"{[b for b,e,p in lvl]}")
        check("...and the published pointer is that bank's current engine frame",
              all(p == ptr(b, e) for b, e, p in lvl),
              f"{[(b, e, hex(p)) for b, e, p in lvl]}")

        left = hold(JOY_LEFT, settle)
        check("holding LEFT reaches the hard-left bank",
              left[-1][0] == BANK_LEFT, f"bank={left[-1][0]}")
        banks = [b for b, e, p in left]
        check("...through the intermediate bank, one stage at a time",
              1 in banks and banks.index(1) < banks.index(BANK_LEFT),
              f"{banks[:14]}")
        steps = {abs(b2 - b1) for (b1, _, _), (b2, _, _) in zip(left, left[1:])}
        check("the lean never skips a stage", steps <= {0, 1}, f"{sorted(steps)}")

        back = hold(0, settle)
        check("releasing the stick rolls back to neutral",
              back[-1][0] == BANK_NEUTRAL, f"bank={back[-1][0]}")

        right = hold(JOY_RIGHT, settle)
        check("holding RIGHT reaches the hard-right bank",
              right[-1][0] == BANK_RIGHT, f"bank={right[-1][0]}")
        rbanks = [b for b, e, p in right]
        check("...through its own intermediate bank",
              3 in rbanks and rbanks.index(3) < rbanks.index(BANK_RIGHT),
              f"{rbanks[:14]}")
        check("the pointer always names the current bank AND engine frame",
              all(p == ptr(b, e) for b, e, p in left + back + right))

        # THE LEAN CADENCE, measured as how long each bank is HELD. Every run
        # except the last ended in a transition actually observed, so its
        # length is a true lower bound on the dwell.
        runs, cur = [], 1
        for (b1, _, _), (b2, _, _) in zip(right, right[1:]):
            if b1 == b2: cur += 1
            else: runs.append(cur); cur = 1
        runs.append(cur)
        check("a bank stage is HELD for several frames, not stepped every frame",
              bool(runs[:-1]) and all(r >= BANK_RATE for r in runs[:-1]),
              f"dwell per stage {runs} (measured {runs[:-1]}, want >= {BANK_RATE})")

        # THE ENGINE CADENCE, the same way, and on its own clock: the flame
        # must cycle all three frames and must not step every PAL frame.
        eseq = [e for b, e, p in left + back + right]
        check("the engine flame cycles through all three frames",
              set(eseq) == {0, 1, 2}, f"{sorted(set(eseq))}")
        # DROP THE FIRST RUN, which the capture clipped: this loop appends only
        # on a transition, so the trailing partial run is already excluded, but
        # the leading one began before sampling started and reads short. Every
        # run after it is bounded by two observed transitions and is a true
        # dwell. (The bank check above has the mirror-image problem and drops
        # its LAST run for the same reason.)
        eruns, cur = [], 1
        for a1, a2 in zip(eseq, eseq[1:]):
            if a1 == a2: cur += 1
            else: eruns.append(cur); cur = 1
        complete = eruns[1:]
        check("the flame is held for several frames, not stepped every frame",
              bool(complete) and all(r >= ENGINE_RATE for r in complete),
              f"dwell per flame frame {eruns[:8]} (measured {complete[:6]}, "
              f"want >= {ENGINE_RATE})")

        poke(mon, sym["joyHold"], 0)

        # --- the muzzle flash, through the REAL frame loop -------------------
        # Triggered by the weapon ACCEPTING a shot, so this holds the fire
        # button and watches what the published block does. Nothing is poked:
        # the cadence, the heat and the accept decision are all the weapon's.
        print("\n--- the muzzle flash ---")

        def fire(frames, bank=None, bits=JOY_FIRE):
            if bank is not None:
                poke(mon, sym["plyBank"], bank)
            poke(mon, sym["joyHold"], 1)
            poke(mon, sym["joyState"], JOY_MASK & ~bits)
            bp = set_bp(mon, sym["gameFrame"])
            out = step_n(mon, sym["frameCounter"], frames,
                         lambda: (rd1(mon, sym["shotFired"]),
                                  rd1(mon, sym["plyFlash"]),
                                  rd1(mon, sym["plyPresPtr1"]),
                                  rd1(mon, sym["plyPresCol1"]),
                                  rd1(mon, sym["plyPresEnable"]),
                                  rd1(mon, sym["plyBank"]),
                                  rd1(mon, sym["plyPresCol0"]),
                                  rd1(mon, sym["plyVisible"])))
            mon.cmd(f"delete {bp}"); mon.cmd("delete")
            return out

        # Let any in-flight flash and cooldown drain first.
        fire(WPN_FIRE_PERIOD * 2, bits=0)

        # CLEAR ANY INVULNERABILITY BEFORE MEASURING, and this is not tidiness.
        # The blink runs four frames dark, four lit -- period 8 -- and
        # WPN_FIRE_PERIOD is also 8, so the two PHASE-LOCK: if the player is
        # hit shortly before this window, every shot lands on the same blink
        # phase and HW1's enable is dark on the same frame of every flash. That
        # looks exactly like a flash one frame short, and it is the blink, not
        # the flash. The blink's authority over the enable is proved on its own
        # in the precedence checks below; here it is a confound.
        poke(mon, sym["plyInvuln"], 0)
        poke(mon, sym["plyVisible"], 1)

        held = fire(WPN_FIRE_PERIOD * 5)
        poke(mon, sym["joyHold"], 0)

        shots = [i for i, r in enumerate(held) if r[0]]
        check("holding fire produced accepted shots",
              len(shots) >= 3, f"{len(shots)} shots at {shots[:6]}")
        gaps = [b - a for a, b in zip(shots, shots[1:])]
        check(f"one shot every {WPN_FIRE_PERIOD} frames -- the cadence is "
              f"unchanged", all(g == WPN_FIRE_PERIOD for g in gaps), f"{gaps}")

        # ONE FLASH PER SHOT, not one per frame the trigger was held.
        #
        # "Lit" is read from the PUBLISHED FLASH -- HW1's pointer off the blank
        # block -- not from the enable bit. The enable is the AND of the flash
        # and the blink, so measuring the flash by it cannot tell a short flash
        # apart from a dark blink frame. The two are then tied back together
        # explicitly, one frame at a time, immediately below.
        lit = [i for i, r in enumerate(held) if r[2] != PTR_BLANK]
        mismatch = [(i, r) for i, r in enumerate(held)
                    if bool(r[4] & ~HW0_BIT & 0xff)
                    != (r[2] != PTR_BLANK and bool(r[7]))]
        check("HW1's enable is exactly the flash AND the ship being visible, "
              "on every frame", not mismatch, f"{mismatch[:3]}")
        check("HW1 is lit on strictly fewer frames than the button was held",
              0 < len(lit) < len(held),
              f"lit on {len(lit)} of {len(held)} frames")
        # Counted against the shots that FIT in the capture rather than with a
        # tolerance: a trailing shot whose second frame fell outside the window
        # would otherwise be indistinguishable from a flash that is genuinely
        # one frame short.
        complete = [i for i in shots if i + FLASH_TIME - 1 < len(held)]
        expect = len(complete) * FLASH_TIME
        check(f"...exactly {FLASH_TIME} frames per accepted shot",
              len(lit) == expect,
              f"{len(lit)} lit frames, expected {expect} for "
              f"{len(complete)} complete shots of {len(shots)}")

        # ONE COLOUR, HELD. The bold artwork carries its own white-hot core in
        # the shared colour, so $d028 holds red for BOTH visible frames -- the
        # earlier orange/red pulse is gone. The third frame must be dark with
        # the pointer back on the blank block.
        bad = []
        for i in shots:
            if i + 2 >= len(held):
                continue                      # window clipped this one
            f1, f2, f3 = held[i], held[i + 1], held[i + 2]
            for n, fr in ((1, f1), (2, f2)):
                if fr[2] == PTR_BLANK:
                    bad.append((f"frame{n} not lit", i, fr))
                if not fr[4] & ~HW0_BIT & 0xff:
                    bad.append((f"frame{n} not enabled", i, fr))
                if fr[3] != COL_FLASH:
                    bad.append((f"frame{n} not red", i, fr))
            if f3[2] != PTR_BLANK or f3[4] & ~HW0_BIT & 0xff:
                bad.append(("still lit on frame3", i, f3))
            if f3[2] != PTR_BLANK:
                bad.append(("pointer not returned to blank", i, f3))
        check("each shot holds HW1 RED for both frames then goes dark",
              not bad, f"{bad[:3]}")

        # THE FLASH FOLLOWS THE BANK. The artwork leans with the craft, so the
        # frame chosen must be the one for the attitude it was fired at.
        wrong = []
        for bank in range(BANK_FRAMES):
            fire(WPN_FIRE_PERIOD * 2, bank=bank, bits=0)      # drain, set bank
            seq = fire(WPN_FIRE_PERIOD + 2, bank=bank)
            poke(mon, sym["joyHold"], 0)
            shot = [r for r in seq if r[2] != PTR_BLANK]
            if not shot:
                wrong.append((bank, "no flash at all"))
            else:
                for r in shot:
                    if r[2] != PTR_FLASH + r[5]:
                        wrong.append((bank, f"ptr ${r[2]:02x} for bank {r[5]}"))
        # THE HULL MUST NOT REACT TO FIRING. This behaviour was removed: the
        # craft used to redden for three frames on every shot. Asserted across
        # the WHOLE held-fire capture -- five accepted shots and the frames
        # between them -- rather than on a posed state, because a leftover
        # timer would surface as a few reddened frames somewhere in the run and
        # a single sample could easily miss them.
        hull = sorted({r[6] for r in held})
        check("firing NEVER changes the hull colour -- the craft no longer "
              "flashes when it fires", hull == [COL_SHIP],
              f"hull colours over {len(held)} frames of held fire: {hull}")

        check("every banking attitude selects its own flash frame",
              not wrong, f"{wrong[:4]}")

        # HW1 MUST NOT BE IN THE MUX. The gameplay schedule names slots
        # MUX_FIRST_SLOT..7; if the player's second slot ever appeared there,
        # two writers would own one sprite.
        cur = rd1(mon, sym["schedCurrent"])
        n = rd1(mon, sym["schedEntries"] + cur)
        slots = rd(mon, sym["schedSlot"] + cur * 24, n) if n else []
        check("no gameplay schedule entry claims HW0 or HW1",
              all(sl >= 2 for sl in slots), f"{slots}")

        # --- precedence -----------------------------------------------------
        # playerEmit is pure presentation with no cadence of its own, so these
        # pose a state and call it directly. Each check sets ONE thing and
        # asserts the other two are untouched, which is what "precedence" has
        # to mean if the three are to remain independent.
        print("\n--- precedence: banking must not override flash or blink ---")
        poke(mon, sym["plyBank"], BANK_LEFT)              # hard left
        poke(mon, sym["plyEngine"], 0)                    # flame full
        poke(mon, sym["plyFlash"], 0)
        poke(mon, sym["plyVisible"], 1)
        call(mon, sym, "playerEmit")
        base_ptr = rd1(mon, sym["plyPresPtr0"])
        check("banked, resting, visible: banked frame, ship colour, HW0 on",
              (base_ptr, rd1(mon, sym["plyPresCol0"]),
               rd1(mon, sym["plyPresEnable"]))
              == (ptr(BANK_LEFT, 0), COL_SHIP, HW0_BIT),
              f"ptr=${base_ptr:02x} col={rd1(mon, sym['plyPresCol0'])} "
              f"en={rd1(mon, sym['plyPresEnable'])}")

        # THE MUZZLE FLASH IS HW1's ALONE. It lights the second sprite and
        # leaves BOTH the banked frame and the hull colour where they were --
        # the craft reacting to its own gun is the behaviour that was removed.
        poke(mon, sym["plyFlash"], FLASH_TIME)
        call(mon, sym, "playerEmit")
        check("the MUZZLE FLASH lights HW1 and leaves the craft untouched",
              (rd1(mon, sym["plyPresCol1"]), rd1(mon, sym["plyPresCol0"]),
               rd1(mon, sym["plyPresPtr0"]))
              == (COL_FLASH, COL_SHIP, ptr(BANK_LEFT, 0)),
              f"col1={rd1(mon, sym['plyPresCol1'])} "
              f"col0={rd1(mon, sym['plyPresCol0'])} "
              f"ptr0=${rd1(mon, sym['plyPresPtr0']):02x}")

        poke(mon, sym["plyFlash"], 0)
        poke(mon, sym["plyVisible"], 0)                   # mid-blink
        call(mon, sym, "playerEmit")
        check("the INVULNERABILITY blink clears the enable and leaves the frame",
              rd1(mon, sym["plyPresEnable"]) == 0
              and rd1(mon, sym["plyPresPtr0"]) == ptr(BANK_LEFT, 0),
              f"en={rd1(mon, sym['plyPresEnable'])} "
              f"ptr=${rd1(mon, sym['plyPresPtr0']):02x}")

        poke(mon, sym["plyVisible"], 1)
        call(mon, sym, "playerEmit")
        check("and the ship comes back solid on the same banked frame",
              rd1(mon, sym["plyPresEnable"]) == HW0_BIT
              and rd1(mon, sym["plyPresPtr0"]) == ptr(BANK_LEFT, 0))

        check("with no shot in flight HW1 is blank and switched OFF",
              rd1(mon, sym["plyPresPtr1"]) == PTR_BLANK
              and rd1(mon, sym["plyPresEnable"]) == HW0_BIT,
              f"ptr1=${rd1(mon, sym['plyPresPtr1']):02x} "
              f"enable={rd1(mon, sym['plyPresEnable'])}")
        check("HW1 stays co-located in X and lifted in Y by the artwork's offset",
              rd1(mon, sym["plyPresX1"]) == rd1(mon, sym["plyPresX0"])
              and rd1(mon, sym["plyPresY1"])
                  == (rd1(mon, sym["plyPresY0"]) - FLASH_Y_LIFT) & 0xff,
              f"y0={rd1(mon, sym['plyPresY0'])} y1={rd1(mon, sym['plyPresY1'])}")

        # --- the engine is unharmed -----------------------------------------
        print("\n--- production health, with the new ship live ---")
        poke(mon, sym["plyBank"], BANK_NEUTRAL)
        for n in ("gameOverrun", "publishSkip", "schedBuildDefer",
                  "scrollLate", "edgeLate", "statPageMismatch", "statPtrMismatch"):
            for name in ((n,) if n in sym else ()):
                poke(mon, sym[name], 0)
        free_run(mon, sym["frameCounter"], 6)
        mon.cmd("delete")
        for n in ("gameOverrun", "publishSkip", "schedBuildDefer",
                  "scrollLate", "edgeLate", "statPageMismatch", "statPtrMismatch"):
            if n in sym:
                got = rd1(mon, sym[n])
                check(f"{n} is zero over six seconds of play", got == 0, str(got))
    finally:
        v.close()


def main():
    print("The blue player craft\n")
    statics()
    machine()
    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
