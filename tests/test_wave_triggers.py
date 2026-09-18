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

What this proves
----------------
* the four authored rows are the ones the delta schedule actually produced for
  its first cycle -- 48, 52, 90, 126 -- so Level 1 is spatially unchanged;
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

sym = symbols(SYM)
PORT = 6693

WAVE_TRIGGERS = 4
GS_PLAYING = 1
LP_LEVEL = 0

# The authored production schedule, restated here so a silent edit to
# src/waves.asm is a failure in this file rather than a surprise in play.
PROD_ROWS    = [48, 52, 90, 126]
PROD_DEF     = [0, 1, 2, 3]
PROD_SPECIES = [0, 8, 0, 8]          # SPECIES_RING / SPECIES_DROPPER
PROD_FIRE    = [0b0101, 0b0010, 0b0101, 0b0000]
PROD_SIDE    = [0, 0, 0, 1]

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


def arm_schedule(mon, rows):
    """Poke a DISPOSABLE schedule into the row columns and rewind the cursor."""
    for i, r in enumerate(rows):
        poke16(mon, sym["waveTrigRowLo"] + i, sym["waveTrigRowHi"] + i, r)
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
        lo = rd(mon, sym["waveTrigRowLo"], WAVE_TRIGGERS)
        hi = rd(mon, sym["waveTrigRowHi"], WAVE_TRIGGERS)
        rows = [lo[i] | (hi[i] << 8) for i in range(WAVE_TRIGGERS)]
        check("the authored rows are the ones the delta schedule produced for "
              "its first cycle", rows == PROD_ROWS, f"{rows}")
        check("...in non-decreasing order, as a forward-only cursor requires",
              all(rows[i] >= rows[i - 1] for i in range(1, len(rows))), str(rows))
        for name, want in (("Def", PROD_DEF), ("Species", PROD_SPECIES),
                           ("Fire", PROD_FIRE), ("Side", PROD_SIDE)):
            got = rd(mon, sym[f"waveTrig{name}"], WAVE_TRIGGERS)
            check(f"waveTrig{name} is unchanged by the migration",
                  got == want, f"{got} wanted {want}")
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

        # ==================================================================
        # PART 2 -- the first cycle, preserved exactly
        # ==================================================================
        fired = collect_firings(mon, PROD_ROWS[-1] + 8, expect=WAVE_TRIGGERS)
        total_firings += len(fired)
        got_rows = [r for _, r in fired]
        got_cursors = [c for c, _ in fired]
        check("exactly four triggers were consumed",
              len(fired) == WAVE_TRIGGERS,
              f"{len(fired)} firings at rows {got_rows}")
        check("...each at EXACTLY its authored row",
              got_rows == PROD_ROWS, f"{got_rows} wanted {PROD_ROWS}")
        check("...in cursor order 0,1,2,3, each consumed once",
              got_cursors == list(range(WAVE_TRIGGERS)), str(got_cursors))
        check("the cursor is exhausted on WAVE_TRIGGERS",
              rd1(mon, sym["wvNextTrig"]) == WAVE_TRIGGERS,
              f"wvNextTrig = {rd1(mon, sym['wvNextTrig'])}")

        check("nothing was dropped for want of an instance",
              rd1(mon, sym["wvDropped"]) == 0,
              f"wvDropped = {rd1(mon, sym['wvDropped'])}")
        check("the stage is still playing, not ended",
              rd1(mon, sym["lvlPhase"]) == LP_LEVEL)

        # ==================================================================
        # PART 3 -- the compare is genuinely sixteen bit
        # ==================================================================
        # THIS RUNS BEFORE ANY LONG ADVANCE, and the ordering is forced: row 255
        # is only 129 rows past the last authored trigger, so it stops being
        # reachable the moment the world is allowed to run on. The world only
        # moves forward, and there is no safe way to rewind it -- poking
        # worldProgress would desynchronise the scroller's own invariant.
        # Each pair straddles an 8-bit boundary: a compare that dropped the high
        # byte would fire 256 rows early, and one that tested only the high byte
        # could not tell 255 from 256 at all.
        for pair in ([255, 256, 511, 512], [1023, 1024, 1535, 1536]):
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
            check("...and the cursor exhausted again",
                  rd1(mon, sym["wvNextTrig"]) == WAVE_TRIGGERS,
                  f"wvNextTrig = {rd1(mon, sym['wvNextTrig'])}")

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
        poke_checked(mon, sym["wvNextTrig"], WAVE_TRIGGERS)   # as Part 2 left it
        poke_checked(mon, sym["wvStarted"], 0)
        lo = rd(mon, sym["waveTrigRowLo"], WAVE_TRIGGERS)
        hi = rd(mon, sym["waveTrigRowHi"], WAVE_TRIGGERS)
        check("the production rows are restored after the disposable schedules",
              [lo[i] | (hi[i] << 8) for i in range(WAVE_TRIGGERS)] == PROD_ROWS)

        here = wp(mon)
        end = approach(mon, here + 3 * OLD_PERIOD + 20, margin=0)
        check("an exhausted cursor stays exhausted over three more old periods",
              rd1(mon, sym["wvStarted"]) == 0
              and rd1(mon, sym["wvNextTrig"]) == WAVE_TRIGGERS,
              f"{here} -> {end}: wvStarted = {rd1(mon, sym['wvStarted'])}, "
              f"cursor = {rd1(mon, sym['wvNextTrig'])}")

        # EVERY FIRING IN THE WHOLE RUN IS ACCOUNTED FOR: four production
        # triggers, eight boundary triggers, one released from the hold.
        check("every trigger consumed over the whole run was one an armed "
              "schedule authorised -- no wraparound anywhere",
              total_firings == 4 + 8 + 1,
              f"{total_firings} firings over {end} coarse rows "
              f"({end // OLD_PERIOD} old periods)")

        for name in CATASTROPHIC:
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
