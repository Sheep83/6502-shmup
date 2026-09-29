#!/usr/bin/env python3
"""Absolute 16-bit wave-trigger rows: exactly once, in order, and never again.

THE CONTRACT THIS FILE EXISTS FOR
---------------------------------
    A trigger names one absolute 16-bit world row. Once consumed, it never
    becomes due again unless another authored trigger explicitly exists at
    another row.

It replaces a delta-coded schedule whose cursor WRAPPED, so Level 1's four
authored moments recurred every 126 coarse rows -- thirteen times over the
production stage and fifty-two times over the 420-row proof.

NOTHING HERE FREEZES THE AUTHORED SCHEDULE. It used to: PROD_ROWS, PROD_DEF,
PROD_SPECIES, PROD_FIRE, PROD_SIDE and `WAVE_TRIGGERS = 4` were literals, and
when Level 1 was re-authored to five triggers this file reported twelve failures
about an engine that was behaving perfectly. The authored table is now READ from
the loaded package, and what is asserted of it is structure -- every reference
resolves, every field is in range, the rows only go forwards -- not its values.
The behavioural cases run on DISPOSABLE schedules poked into the row columns,
which they always did.

What this proves
----------------
* whatever is authored, every live trigger resolves: a definition that exists, a
  legal species row, a legal side, a fire mask no wider than its wave, a legal
  colour byte, a legal firing mode and a legal speed;
* the rows are non-decreasing, as a forward-only cursor requires;
* each fires EXACTLY ONCE, at EXACTLY its row, in cursor order;
* the cursor stops on WAVE_TRIGGERS and stays there, and the world may then run
  for hundreds of rows with the production schedule loaded and nothing fires;
* the compare is genuinely SIXTEEN BIT, proved dynamically at 255/256, 511/512,
  1023/1024 and 1535/1536 -- every 8-bit boundary the 420-row world crosses;
* a row above the stage never fires;
* a trigger that comes due during a token-encounter hold is handled ONCE after
  release: neither lost nor duplicated;
* every firing over the whole run is accounted for -- the totals admit no
  trigger that any armed schedule did not authorise.

The boundary schedules are DISPOSABLE and poked into the ROW COLUMNS only, at
runtime. Definition, species, fire mask and side keep their authored values, so
every wave they fire is a real production wave. They are not production content,
and the authored rows are restored and re-checked at the end.

What this does NOT prove
------------------------
That the encounters look right where they land. Manual non-warp VICE is
authoritative -- see AGENTS.md.

One VICE launch.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, pc_of, check, report)
import campaign_data as CD                                       # noqa: E402

sym = symbols(SYM)
PORT = 6693

LEVELPKG_NOSPAWN = CD.NOSPAWN_ADDR    # the stage header in the loaded package
GS_PLAYING = 1
LP_LEVEL = 0

# THE AUTHORED SCHEDULE IS READ AT RUNTIME, from the package the engine loaded.
# WAVE_TRIGGERS and the five PROD_* lists used to be literals here; they are
# filled in by read_authored() below so that adding a trigger, changing a
# species or moving a row is an authoring change and not a test failure.
WAVE_TRIGGERS = None
PROD_ROWS = PROD_DEF = PROD_SPECIES = PROD_FIRE = PROD_SIDE = None

# The generated level, for the export-consistency check only: the package in RAM
# must carry what the level the engine was BUILT from declares. That is a real
# contract between exporter and engine, and it holds for any content.
L1 = CD.level("level1")

OLD_PERIOD = 126                     # the delta schedule's repeat, now retired
FAR = 0xF000                         # a row the stage can never reach

CATASTROPHIC = ("gameOverrun", "scrollLate", "statPageMismatch",
                "statPtrMismatch", "objDoubleFree", "objAllocFail")


# ---------------------------------------------------------------------------
# Monitor helpers
# ---------------------------------------------------------------------------
def w16(mon, name_lo):
    v = rd(mon, sym[name_lo], 2)
    return v[0] | (v[1] << 8)


def wp(mon):
    return w16(mon, "worldProgressLo")


def poke16(mon, addr_lo, addr_hi, value):
    poke(mon, addr_lo, value & 0xff)
    poke(mon, addr_hi, (value >> 8) & 0xff)


def poke_checked(mon, addr, val, tries=6):
    for _ in range(tries):
        poke(mon, addr, val)
        if rd1(mon, addr) == (val & 0xff):
            return
    raise RuntimeError(f"could not write ${addr:04x} = {val:02x}")


class Stepper:
    def __init__(self, mon):
        self.mon, self.last = mon, None

    def step(self, tries=10):
        for _ in range(tries):
            self.mon.cmd("x")
            f = rd(self.mon, sym["frameCounter"], 2)
            fc = f[0] | (f[1] << 8)
            if fc != self.last:
                self.last = fc
                return fc
        raise RuntimeError("the machine stopped advancing frames")

    def run(self, n):
        for _ in range(n):
            self.step()


def settle(mon):
    """Let an in-flight waveStartNext finish before anything is read or armed.

    collect_firings stops AT THE ENTRY to waveStartNext -- that is the whole
    point, because the cursor there still names the trigger being consumed. But
    the routine has not yet armed the instance, bumped wvStarted or advanced the
    cursor, so reading any of those at that moment sees the state as it was
    BEFORE the trigger just caught, and arming a fresh schedule there lets the
    half-finished call consume the NEW trigger 0 on its way out. One frame of
    ordinary execution settles all of it.
    """
    st = Stepper(mon)
    set_bp(mon, sym["gameFrame"])
    st.step()
    mon.cmd("delete")


def collect_firings(mon, until_row, expect=None, cap=3000, budget_s=120):
    """Every waveStartNext entry up to `until_row`, as (cursor, row) pairs.

    The cursor is read AT THE STOP, before waveAdvanceCursor runs, so it names
    the trigger being consumed rather than the next one.

    `expect` STOPS THE WORLD MOVING THE MOMENT THE LAST EXPECTED TRIGGER LANDS,
    and it is not an optimisation. Once the cursor is exhausted this breakpoint
    can never fire again, so every further `x` free-runs until the socket goes
    idle -- four seconds of warp, which is roughly 470 coarse rows. A first
    draft ran on to the row limit and left the world at 603 when it meant to
    leave it at 134, which put the 255/256 boundary pair permanently out of
    reach. Callers that want "and then nothing fired" use run_to_row instead.

    A WALL-CLOCK BUDGET, NOT JUST AN ITERATION CAP. Each resume that does not
    stop costs its full deadline, so a cap of three thousand is a cap of hours,
    and one run of this file duly sat for forty-five minutes on a boundary
    trigger it was never going to catch. The budget turns that into a reported
    failure in a couple of minutes, which is what a stuck probe should look
    like. Callers approach() first so the breakpoint is only a few hundred
    frames away and the ordinary case stops almost immediately.
    """
    want = sym["waveStartNext"]
    set_bp(mon, want)
    mon._drain()
    out = []
    deadline = time.time() + budget_s
    for _ in range(cap):
        if time.time() > deadline:
            print(f"  info collect_firings gave up after {budget_s}s at "
                  f"worldProgress {wp(mon)} with {len(out)} firings")
            break
        # 1.5s rather than the default 4: approach() has already brought the
        # breakpoint within a few hundred frames, so a stop that has not come
        # by now is a miss worth retrying rather than waiting longer on.
        if pc_of(mon.cmd("x", deadline=1.5)) != want:
            if wp(mon) > until_row:
                break
            continue
        out.append((rd1(mon, sym["wvNextTrig"]), wp(mon)))
        if expect is not None and len(out) >= expect:
            break
        if wp(mon) > until_row:
            break
    mon.cmd("delete")
    settle(mon)
    return out


def run_to_row(mon, target, cap=600, hold_token=False):
    """Advance until worldProgress passes `target`, stepping real FRAMES.

    ONLY FOR THE TOKEN HOLD. Frame stepping costs a monitor round trip per
    displayed frame -- eight per coarse row -- so covering a few hundred rows
    this way takes tens of minutes, and an early draft of this file spent
    twenty-six of them in Part 6 doing exactly that. Everything that merely
    needs to COVER GROUND uses approach(); this exists for the one caller that
    must touch every frame, because it re-asserts tkActive on each of them.

    hold_token re-asserts tkActive on every frame. THE FLAG CANNOT SIMPLY BE
    POKED ONCE: tokenTick owns it, and with tkActive set but no real token in
    tkSlot the encounter ends itself on the next frame and clears the flag. A
    first draft poked it once and watched the "held" trigger fire immediately.
    """
    st = Stepper(mon)
    set_bp(mon, sym["gameFrame"])
    for _ in range(cap):
        if hold_token:
            poke(mon, sym["tkActive"], 1)
        st.step()
        if wp(mon) > target:
            break
    mon.cmd("delete")
    return wp(mon)


def approach(mon, target, margin=40):
    """Bring the world to within `margin` rows BELOW `target`, cheaply.

    THIS EXISTS TO KEEP THE BREAKPOINT WAIT SHORT, and that is a correctness
    matter rather than a speed one. collect_firings waits at a breakpoint on
    waveStartNext; `mon.cmd("x")` gives up after four seconds of warp -- several
    hundred coarse rows -- and returns with the machine still running, so a
    trigger that comes due during that window can be stepped straight over and
    never recorded. Armed at row 512 and waiting for row 1023, the wait is five
    hundred rows and the miss is not hypothetical: it was measured, dropping
    1023 and 1024 from a four-trigger boundary schedule.

    Closing the gap first means the breakpoint is always only a few hundred
    FRAMES away and `x` stops on it long before the deadline.

    THE BURST LENGTH IS THE `deadline`, NOT A SLEEP. free_run cannot be used
    here: its `mon.cmd("x")` waits for the monitor to say something, and with no
    breakpoint armed the machine says nothing at all, so the call blocks for its
    full four-second deadline however small the slice argument is. Asking
    free_run for 0.15 s of advance therefore delivered about four hundred coarse
    rows -- measured, and it overshot row 255 to land past 512 on the first try.

    A short explicit deadline on the resume gives a burst that really is short
    (~0.25 s of warp, roughly twenty coarse rows), and the read that follows
    halts the machine again. The margin is many times one burst, because the
    world can never go back.

    THE BURST SHORTENS AS THE TARGET NEARS. A burst is wall-clock, so a system
    hiccup makes it longer than asked, and one long burst near the end can carry
    the world straight over the target -- measured, losing rows 1023 and 1024
    from a four-row schedule. Far out that does not matter; within a couple of
    hundred rows the bursts drop to a few rows each, so it would take a stall of
    an order of magnitude to overshoot the margin.

    A BURST THAT DELIVERED NOTHING IS NOT THE END OF THE WORLD. The monitor
    occasionally swallows a resume -- the same dropped-`x` the harness's own
    free_run retries around -- and a first draft treated one such burst as "the
    machine has stopped" and returned immediately. It duly gave up at row 133
    when asked for 215, and at 540 when asked for 983, and the boundary rows
    then went unobserved. A stalled burst is retried after resynchronising the
    monitor; only a long run of them is a real stop.

    THE MACHINE RUNS DURING A sleep, NOT DURING THE COMMAND, and that is the
    shape free_run already uses. Waiting inside `mon.cmd("x")` for its deadline
    looks equivalent and is not: the read that follows has to halt the emulator
    and resynchronise a socket that is mid-reply, and rd()'s retries then burn
    wall time with the machine STOPPED. Measured, that managed about six coarse
    rows per two seconds -- so bad that replacing frame stepping with it made
    this file slower, not faster (1 h 28 m against 46 min). Resuming with a very
    short deadline and then sleeping puts the wall time where the emulation is.

    ROWS PER SECOND IS MEASURED (~110 in warp here) and the burst is sized to
    cover about three quarters of what is left, so it converges quickly without
    stepping over the target.
    """
    stalls = 0
    while True:
        here = wp(mon)
        gap = (target - margin) - here
        if gap <= 0:
            return here
        secs = min(max(gap / 150.0, 0.05), 2.0)
        mon.cmd("x", idle=0.02, deadline=0.05)   # resume and return at once
        time.sleep(secs)                         # ...the machine runs HERE
        after = wp(mon)                          # ...and this halts it again
        if after > here:
            stalls = 0
            continue
        stalls += 1
        if stalls > 10:                  # genuinely not advancing
            return after
        mon.cmd("r")                     # resynchronise and try again


def read_authored(mon):
    """The authored trigger table, as the LOADED PACKAGE holds it.

    Fills the module-level PROD_* so the rest of the file can talk about "the
    authored rows" without any of them being written down here.
    """
    global WAVE_TRIGGERS, PROD_ROWS, PROD_DEF, PROD_SPECIES, PROD_FIRE, PROD_SIDE
    WAVE_TRIGGERS = rd1(mon, CD.TRIGN_ADDR)
    n = max(WAVE_TRIGGERS, 1)
    lo = rd(mon, sym["waveTrigRowLo"], n)
    hi = rd(mon, sym["waveTrigRowHi"], n)
    PROD_ROWS = [lo[i] | (hi[i] << 8) for i in range(WAVE_TRIGGERS)]
    PROD_DEF = list(rd(mon, sym["waveTrigDef"], n))[:WAVE_TRIGGERS]
    PROD_SPECIES = list(rd(mon, sym["waveTrigSpecies"], n))[:WAVE_TRIGGERS]
    PROD_FIRE = list(rd(mon, sym["waveTrigFire"], n))[:WAVE_TRIGGERS]
    PROD_SIDE = list(rd(mon, sym["waveTrigSide"], n))[:WAVE_TRIGGERS]
    return {"colour": list(rd(mon, sym["waveTrigColour"], n))[:WAVE_TRIGGERS],
            "fireMode": list(rd(mon, sym["waveTrigFireMode"], n))[:WAVE_TRIGGERS],
            "speed": list(rd(mon, sym["waveTrigSpeed"], n))[:WAVE_TRIGGERS]}


def open_the_approach(mon):
    """Push STAGE_NO_SPAWN_ROW out of the way for a synthetic schedule.

    The boss approach is per-level PACKAGE DATA now (src/levelpkg.asm), and
    Level 1 authors it at row 340 -- sensible for a stage that ends at 395 and
    fatal for this file, which proves the sixteen-bit trigger contract with
    synthetic rows at 255, 256, 511, 512, 1023, 1024, 1535 and 1536. Every one
    of those is past the authored approach, so the director would suppress them
    and this file would be measuring the quiet zone instead of the schedule.
    #
    Raising it to $ffff removes the approach entirely for the duration, which is
    exactly the isolation these cases want: they are about trigger rows, and the
    approach has its own file (tests/test_no_spawn_row.py).
    """
    poke_checked(mon, LEVELPKG_NOSPAWN + 0, 0xff)
    poke_checked(mon, LEVELPKG_NOSPAWN + 1, 0xff)


def boundaries_above(here, count=4, margin=8):
    """`count` rows straddling 8-bit boundaries, all comfortably above `here`.

    Returns e.g. [511, 512, 767, 768] -- pairs of (256k - 1, 256k), which is what
    makes the sixteen-bit compare the thing under test: the low byte wraps between
    the two members of every pair and the high byte does not.

    THE MARGIN IS SMALL ON PURPOSE. approach() returns immediately when the
    target is already close and the collector then simply waits at the
    breakpoint, so the only hard requirement is that the first boundary is
    strictly AHEAD of the world -- and keeping the margin tight is what lets the
    255/256 pair still be chosen when the authored schedule ends just below it,
    which is the case on the committed level (it ends at row 240).
    """
    k = (here + margin) // 256 + 1
    out = []
    while len(out) < count:
        out += [256 * k - 1, 256 * k]
        k += 1
    return out[:count]


def arm_schedule(mon, rows):
    """Poke a DISPOSABLE schedule into the row columns and rewind the cursor.

    THE LIVE COUNT IS SET TO len(rows) AS WELL. It was not, and that only worked
    while the level happened to author exactly as many triggers as a boundary
    pair needs: the level now authors five, so a four-row schedule left a fifth
    authored trigger live behind it, the terminal cursor was 4 rather than
    WAVE_TRIGGERS, and two checks failed on an engine that had consumed exactly
    what it was given. The count is package data like the rows; Part 6 puts both
    back and re-checks them.
    """
    for i, r in enumerate(rows):
        poke16(mon, sym["waveTrigRowLo"] + i, sym["waveTrigRowHi"] + i, r)
    poke_checked(mon, CD.TRIGN_ADDR, len(rows))
    open_the_approach(mon)
    poke_checked(mon, sym["wvNextTrig"], 0)
    poke_checked(mon, sym["wvStarted"], 0)


def main():
    print("=== absolute 16-bit wave trigger rows ===")
    v = None
    total_firings = 0
    try:
        # THE FRAME-ACCURATE BOOT IS SHARED INFRASTRUCTURE NOW. This file
        # proved the technique; tests/harness.py owns it as boot="exact" so
        # every test that needs the encounter window gets the same one.
        v = Vice(PORT, PRG, warp=True, boot="exact")
        mon = v.mon

        # ==================================================================
        # PART 1 -- the authored table, and the state the migration removed
        # ==================================================================
        extra = read_authored(mon)
        rows = PROD_ROWS
        print(f"  info the authored schedule: {WAVE_TRIGGERS} trigger(s) at "
              f"rows {rows}, definitions {PROD_DEF}, species {PROD_SPECIES}")
        check("the level authors at least one trigger and no more than the "
              "package reserves slots for",
              0 < WAVE_TRIGGERS <= CD.TRIG_SLOTS,
              f"{WAVE_TRIGGERS} of {CD.TRIG_SLOTS} slots")
        check("the authored rows are in non-decreasing order, as a forward-only "
              "cursor requires",
              all(rows[i] >= rows[i - 1] for i in range(1, len(rows))), str(rows))

        # ---- EVERY REFERENCE RESOLVES, EVERY FIELD IS IN RANGE -------------
        # This replaces four "waveTrigX is unchanged by the migration" checks
        # that compared the columns against literal copies of Level 1's August
        # content. What matters is not that a species is 0 or 8 but that it names
        # a slot the engine has; not that a mask is %0101 but that it does not
        # arm a member the wave never sends.
        wd = rd(mon, sym["waveDefTable"], L1.n_defs * CD.WAVEDEF_SIZE)
        counts = [wd[d * CD.WAVEDEF_SIZE + CD.WD_COUNT] for d in range(L1.n_defs)]
        slot_rows = {i * CD.C.ENEMY_ANIM_STEPS for i in range(CD.C.ENEMY_SLOTS)}
        bad = []
        for i in range(WAVE_TRIGGERS):
            d = PROD_DEF[i]
            if d >= L1.n_defs:
                bad.append((i, "definition", d))
                continue
            if PROD_SPECIES[i] not in slot_rows:
                bad.append((i, "species row", PROD_SPECIES[i]))
            if PROD_SIDE[i] > 1:
                bad.append((i, "dropper side", PROD_SIDE[i]))
            if PROD_FIRE[i] >> counts[d]:
                bad.append((i, f"fire mask arms past member {counts[d] - 1}",
                            bin(PROD_FIRE[i])))
            if extra["colour"][i] > CD.C.TRIG_COL_MASK + CD.C.TRIG_COL_RANDOM:
                bad.append((i, "colour byte", hex(extra["colour"][i])))
            if extra["fireMode"][i] > CD.TRIG_FIRE_MAX:
                bad.append((i, "firing mode", extra["fireMode"][i]))
            if not (CD.C.TRIG_SPEED_MIN <= extra["speed"][i]
                    <= CD.C.TRIG_SPEED_MAX):
                bad.append((i, "speed", extra["speed"][i]))
        check("EVERY live trigger resolves: a definition that exists, a legal "
              "species slot, side, fire mask, colour, firing mode and speed",
              not bad, str(bad) if bad else
              f"{WAVE_TRIGGERS} triggers x 7 fields checked against "
              f"{L1.n_defs} definitions")

        # ---- THE EXPORTER AND THE ENGINE AGREE ----------------------------
        # A contract between two programs, and true for any content: the package
        # in RAM carries what the generated level the engine was built from
        # declares. If the exporter dropped or reordered a column this fails.
        check("the package's trigger columns are what the generated level "
              "declares -- exporter and engine agree",
              (WAVE_TRIGGERS, PROD_ROWS, PROD_DEF, PROD_SPECIES, PROD_FIRE,
               PROD_SIDE, extra["colour"], extra["fireMode"], extra["speed"])
              == (L1.n_triggers, L1.trig_row, L1.trig_def, L1.trig_species,
                  L1.trig_fire, L1.trig_side, L1.trig_colour, L1.trig_fire_mode,
                  L1.trig_speed),
              f"{WAVE_TRIGGERS} triggers, all nine columns compared")

        check("the run begins before the first authored row",
              wp(mon) < PROD_ROWS[0], f"worldProgress {wp(mon)}")
        check("the cursor starts on trigger 0 with nothing to seed",
              rd1(mon, sym["wvNextTrig"]) == 0)
        check("no accumulated-target state survives the migration",
              "wvNextAtLo" not in sym and "wvNextAtHi" not in sym,
              "wvNextAtLo/Hi are gone from the symbol table")
        check("...and neither does the delta column",
              "waveTrigDelta" not in sym)

        for n in CATASTROPHIC:
            poke(mon, sym[n], 0)

        # WHERE AN OVERRUN HAPPENS, NOT JUST THAT ONE DID. gameOverrun counts
        # displayed frames the main thread did not prepare one for, and it MUST
        # read zero. This file drives the world two thousand coarse rows under
        # warp, halting the machine on a breakpoint and resuming it hundreds of
        # times, so an assertion at the end alone cannot say whether a non-zero
        # count came from ordinary gameplay or from the probing. Sampling it at
        # each phase boundary makes the answer readable in the output.
        overrun_marks = []

        def mark(where):
            overrun_marks.append((where, rd1(mon, sym["gameOverrun"]),
                                  wp(mon)))
            print(f"  info gameOverrun = {overrun_marks[-1][1]} after {where} "
                  f"(worldProgress {overrun_marks[-1][2]})")

        mark("the authored-table reads, before the world is driven")

        # ==================================================================
        # PART 2 -- the first cycle, preserved exactly
        # ==================================================================
        fired = collect_firings(mon, PROD_ROWS[-1] + 8, expect=WAVE_TRIGGERS)
        total_firings += len(fired)
        got_rows = [r for _, r in fired]
        got_cursors = [c for c, _ in fired]
        check(f"exactly the {WAVE_TRIGGERS} authored triggers were consumed",
              len(fired) == WAVE_TRIGGERS,
              f"{len(fired)} firings at rows {got_rows}")
        check("...each at EXACTLY its authored row",
              got_rows == PROD_ROWS, f"{got_rows} wanted {PROD_ROWS}")
        check("...in cursor order, each consumed once",
              got_cursors == list(range(WAVE_TRIGGERS)), str(got_cursors))
        check("the cursor is exhausted on WAVE_TRIGGERS",
              rd1(mon, sym["wvNextTrig"]) == WAVE_TRIGGERS,
              f"wvNextTrig = {rd1(mon, sym['wvNextTrig'])}")

        mark("part 2 -- the authored schedule, collected at a breakpoint")
        check("nothing was dropped for want of an instance",
              rd1(mon, sym["wvDropped"]) == 0,
              f"wvDropped = {rd1(mon, sym['wvDropped'])}")
        check("the stage is still playing, not ended",
              rd1(mon, sym["lvlPhase"]) == LP_LEVEL)

        # ==================================================================
        # PART 3 -- the compare is genuinely sixteen bit
        # ==================================================================
        # THE BOUNDARIES ARE CHOSEN FROM WHERE THE WORLD IS, not written down.
        #
        # Each pair straddles an 8-bit boundary, because that is the whole point:
        # a compare that dropped the high byte would fire 256 rows early, and one
        # that tested only the high byte could not tell 255 from 256 at all. But
        # the pairs were the literals [255, 256, 511, 512] and
        # [1023, 1024, 1535, 1536], and 255 is only reachable while the authored
        # schedule ends below it -- the world only moves forward and there is no
        # safe way to rewind it, since poking worldProgress would desynchronise
        # the scroller's own invariant.
        #
        # Measured on a tree whose Level 1 was legally re-authored to end at row
        # 270: four checks failed with "the approach stopped short of row 255 --
        # approach ended at 270". The engine was right; the constant was not.
        #
        # boundaries_above() therefore picks the next 8-bit boundaries ABOVE the
        # current position, so the case is exercised wherever the author has left
        # the world, and it is still exactly the case it claims to be.
        here_now = wp(mon)
        groups = [boundaries_above(here_now, 4),
                  boundaries_above(here_now + 900, 4)]
        print(f"  info 8-bit boundary pairs chosen from worldProgress "
              f"{here_now}: {groups[0]} then {groups[1]}")
        # THE PROPERTY, NOT THE NUMBERS. Whichever rows were chosen, they must be
        # ahead of the world, must come in (256k-1, 256k) pairs so the LOW byte
        # wraps inside each pair, and must span more than one high byte -- which is
        # exactly what a sixteen-bit compare has to get right.
        every = groups[0] + groups[1]
        check("the chosen rows are all ahead of the world and straddle 8-bit "
              "boundaries: the low byte wraps inside every pair",
              all(r > here_now for r in every)
              and all((every[i] + 1) == every[i + 1]
                      and every[i] % 256 == 255
                      for i in range(0, len(every), 2)),
              str(every))
        check("...and they span more than one high byte",
              len({r >> 8 for r in every}) > 1,
              f"high bytes {sorted({r >> 8 for r in every})}")
        for pair in groups:
            here = wp(mon)
            check(f"the disposable schedule {pair} is armed ahead of the world",
                  here < pair[0], f"worldProgress {here} < {pair[0]}")
            arm_schedule(mon, pair)
            # ONE ROW AT A TIME, APPROACHING BEFORE EACH. The rule that keeps
            # this reliable is that the breakpoint is never more than `margin`
            # rows away when we start waiting on it -- and the gaps WITHIN a
            # pair are as big as the gap before it (1024 to 1535 is 511 rows).
            # Arming all four and collecting four firings in one wait therefore
            # left the collector sitting on the breakpoint for hundreds of rows,
            # which is exactly where resumes get missed and budgets get burnt.
            fired, got, cur = [], [], []
            for row in pair:
                stopped = approach(mon, row)
                check(f"...the approach stopped short of row {row}",
                      stopped < row, f"approach ended at {stopped}")
                one = collect_firings(mon, row + 8, expect=1, budget_s=45)
                fired += one
                got += [r for _, r in one]
                cur += [c for c, _ in one]
            total_firings += len(fired)
            check(f"all four of {pair} fired, exactly once each, in order",
                  len(fired) == 4 and cur == [0, 1, 2, 3],
                  f"{len(fired)} firings, cursors {cur}")
            check("...each at EXACTLY its row, across the 8-bit boundary",
                  got == pair, f"{got} wanted {pair}")
            check("...and the cursor exhausted again, on the disposable "
                  "schedule's own length",
                  rd1(mon, sym["wvNextTrig"]) == len(pair),
                  f"wvNextTrig = {rd1(mon, sym['wvNextTrig'])} of {len(pair)}")

        # ---- a row the stage never reaches simply never fires --------------
        here = wp(mon)
        arm_schedule(mon, [FAR, FAR + 1, FAR + 2, FAR + 3])
        approach(mon, here + 120, margin=0)
        check("a trigger row far above the stage never fires",
              rd1(mon, sym["wvStarted"]) == 0
              and rd1(mon, sym["wvNextTrig"]) == 0,
              f"wvStarted = {rd1(mon, sym['wvStarted'])}, cursor = "
              f"{rd1(mon, sym['wvNextTrig'])} at worldProgress {wp(mon)} "
              f"vs row ${FAR:04x}")

        mark("parts 3 and 4 -- the eight boundary rows, with long approaches")

        # ==================================================================
        # PART 5 -- a trigger held by a token encounter is not lost
        # ==================================================================
        # THE HOLD IS NOW NOTHING AT ALL: an authored row is a constant and
        # worldProgress only increases, so the `>=` compare keeps a held trigger
        # due with no state written to remember it.
        here = wp(mon)
        due_at = here + 4
        arm_schedule(mon, [due_at, FAR, FAR + 1, FAR + 2])
        held_to = run_to_row(mon, due_at + 25, hold_token=True)
        check("the world passed the trigger's row while the encounter held it",
              held_to > due_at, f"worldProgress {held_to} > row {due_at}")
        check("...and the held trigger did NOT fire",
              rd1(mon, sym["wvStarted"]) == 0,
              f"wvStarted = {rd1(mon, sym['wvStarted'])}")
        check("...and it was not lost: the cursor still names it",
              rd1(mon, sym["wvNextTrig"]) == 0,
              f"wvNextTrig = {rd1(mon, sym['wvNextTrig'])}")

        poke_checked(mon, sym["tkActive"], 0)            # the encounter ends
        fired = collect_firings(mon, wp(mon) + 30, expect=1)
        total_firings += len(fired)
        check("the held trigger fired once the encounter released it",
              len(fired) == 1 and fired[0][0] == 0, f"firings {fired}")
        check("...exactly once, not once per row it was held over",
              rd1(mon, sym["wvStarted"]) == 1,
              f"wvStarted = {rd1(mon, sym['wvStarted'])}")
        check("...and the cursor moved on by exactly one",
              rd1(mon, sym["wvNextTrig"]) == 1,
              f"wvNextTrig = {rd1(mon, sym['wvNextTrig'])}")
        # ...and it is not still due. The remaining rows of that schedule are
        # all FAR, so a released trigger that somehow stayed due would show up
        # here as a second firing.
        approach(mon, wp(mon) + 40, margin=0)
        check("...and it did not fire again once released",
              rd1(mon, sym["wvStarted"]) == 1
              and rd1(mon, sym["wvNextTrig"]) == 1,
              f"wvStarted = {rd1(mon, sym['wvStarted'])}, "
              f"cursor = {rd1(mon, sym['wvNextTrig'])}")

        mark("part 5 -- the token hold, stepped frame by frame")

        # ==================================================================
        # PART 6 -- NO WRAP: the production schedule, exhausted, runs on
        # ==================================================================
        # THE OLD CODE WOULD HAVE RE-ARMED HERE. waveAdvanceCursor walked the
        # cursor back to zero at WAVE_TRIGGERS and added the next delta to a
        # running target, so the four authored moments recurred every 126 rows
        # for as long as the stage scrolled. The production rows go back in the
        # table, the cursor stays where Part 2 left it, and the world runs on.
        for i, r in enumerate(PROD_ROWS):
            poke16(mon, sym["waveTrigRowLo"] + i, sym["waveTrigRowHi"] + i, r)
        poke_checked(mon, CD.TRIGN_ADDR, WAVE_TRIGGERS)       # ...and the count
        poke_checked(mon, sym["wvNextTrig"], WAVE_TRIGGERS)   # as Part 2 left it
        poke_checked(mon, sym["wvStarted"], 0)
        lo = rd(mon, sym["waveTrigRowLo"], WAVE_TRIGGERS)
        hi = rd(mon, sym["waveTrigRowHi"], WAVE_TRIGGERS)
        check("the production rows and the live count are restored after the "
              "disposable schedules",
              [lo[i] | (hi[i] << 8) for i in range(WAVE_TRIGGERS)] == PROD_ROWS
              and rd1(mon, CD.TRIGN_ADDR) == WAVE_TRIGGERS,
              f"{WAVE_TRIGGERS} triggers at {PROD_ROWS}")

        here = wp(mon)
        end = approach(mon, here + 3 * OLD_PERIOD + 20, margin=0)
        check("an exhausted cursor stays exhausted over three more old periods",
              rd1(mon, sym["wvStarted"]) == 0
              and rd1(mon, sym["wvNextTrig"]) == WAVE_TRIGGERS,
              f"{here} -> {end}: wvStarted = {rd1(mon, sym['wvStarted'])}, "
              f"cursor = {rd1(mon, sym['wvNextTrig'])}")

        # EVERY FIRING IN THE WHOLE RUN IS ACCOUNTED FOR: four production
        # triggers, eight boundary triggers, one released from the hold.
        # THE BUDGET IS DERIVED: the authored schedule once, the eight boundary
        # rows, and the one trigger released from the token hold. It was
        # `4 + 8 + 1` and the 4 was Level 1's trigger count.
        want_firings = WAVE_TRIGGERS + 8 + 1
        check("every trigger consumed over the whole run was one an armed "
              "schedule authorised -- no wraparound anywhere",
              total_firings == want_firings,
              f"{total_firings} firings (wanted {want_firings} = "
              f"{WAVE_TRIGGERS} authored + 8 boundary + 1 released) over {end} "
              f"coarse rows ({end // OLD_PERIOD} old periods)")

        mark("part 6 -- three more old periods of free running")
        print("  info gameOverrun by phase: "
              + "; ".join(f"{v} after {w}" for w, v, _r in overrun_marks))

        # ---- gameOverrun IS ASSERTED WHERE THE INSTRUMENT CAN MEASURE IT ----
        #
        # It counts displayed frames the main thread did not prepare one for, and
        # in ordinary running it must be zero. But approach() deliberately
        # resumes the machine with a 0.05 s deadline, sleeps while it runs and
        # then HALTS IT AGAIN with a read, hundreds of times over a thousand
        # coarse rows -- and a halt across a frame boundary is indistinguishable,
        # to this counter, from a frame the game failed to prepare.
        #
        # The staged marks above show exactly that. It is 0 through the whole
        # authored schedule and 240 coarse rows of real gameplay, every increment
        # lands inside parts 3 and 4, and the total varies run to run with wall
        # clock (3 on one run, 4 on the next) -- which a deterministic engine
        # miss would not. tests/test_flight_paths.py watches 1,300 frames of the
        # same engine without the bursts and reads 0.
        #
        # So it is ASSERTED over the phases that run normally and REPORTED over
        # the probing phases, in the same way this file already treats
        # publishSkip and schedBuildDefer. Silently accepting any value would
        # lose a real regression; asserting across the bursts fails on the
        # measurement rather than on the engine.
        _before_bursts = overrun_marks[1][1]        # after part 2
        _after_bursts = overrun_marks[2][1]         # after parts 3 and 4
        _after_hold = overrun_marks[3][1]           # after part 5
        _final = overrun_marks[4][1]
        check("gameOverrun is zero through the authored schedule and 240 coarse "
              "rows of ordinary gameplay",
              _before_bursts == 0, f"{_before_bursts} after part 2")
        check("...and the monitor-driven parts 5 and 6 add none of their own",
              _final == _after_bursts and _after_hold == _after_bursts,
              f"{_after_bursts} -> {_after_hold} -> {_final}")
        print(f"  info gameOverrun rose by "
              f"{_after_bursts - _before_bursts} across parts 3 and 4's "
              f"approach bursts (measured, not asserted: a monitor halt across "
              f"a frame boundary is counted as a miss)")
        for name in CATASTROPHIC:
            if name == "gameOverrun":
                continue
            got = rd1(mon, sym[name])
            check(f"{name} is zero across the whole run", got == 0, str(got))
        print(f"  info publishSkip {rd1(mon, sym['publishSkip'])} "
              f"schedBuildDefer {rd1(mon, sym['schedBuildDefer'])} "
              f"(known noise, measured not asserted)")
        print(f"  info final worldProgress {end}, "
              f"wvSpawned {rd1(mon, sym['wvSpawned'])}, "
              f"wvDropped {rd1(mon, sym['wvDropped'])}")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
