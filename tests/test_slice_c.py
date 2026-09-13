#!/usr/bin/env python3
"""Slice C — the dynamic logical object pool and the first production enemy.

What this proves
----------------
* the stale sorted-ID shrink hazard is GONE: after any membership change every
  ID the builder considers names a currently active object, and no despawned
  ID can survive into NEXT or CURRENT;
* the pool's lifecycle is bounded and deterministic -- allocate, activate,
  update, despawn, REUSE -- and a full pool and a double free both fail safely;
* one real migrated enemy spawns, descends at the old game's two pixels a
  frame, crosses the 255/256 horizontal boundary in both directions, and
  despawns on a single rule;
* gameplay never learns that hardware sprites exist;
* the player, the weapon, the HUD, the aperture and the frame transaction are
  all exactly as Slices A, A' and B left them.

THE STEPPING RULE, ONCE MORE. `mon.cmd("x")` returns on a prompt echo rather
than on the actual stop, so every sample here is verified by frame counter, and
every group of state is read in ONE bulk command at ONE instant.

WHERE THE BREAKPOINT GOES. regenTick is the first call AFTER
sortTick/buildSchedule/publishSchedule, so a stop there sees this frame's
membership, this frame's sort and this frame's NEXT schedule. Stopping at
hudDemoTick -- one call earlier -- sees the PREVIOUS frame's schedule, and an
early draft of this file spent a while concluding the sorter did nothing.

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
MUX_FIRST_SLOT, MUX_SLOTS = 2, 6
MIN_SPRITE_Y, MAX_SPRITE_Y = 55, 226
ENEMY_VY, ENEMY_SPAWN_Y, ENEMY_DESPAWN_Y = 2, 55, 226
ENEMY_PTR = 0x3640 // 64                        # $d9
ENEMY_SPAWN_ENTRIES = 4
SPAWNS = [(72, 0, 0, 2), (160, 0, 0, 2), (248, 0, 1, 2), (40, 1, -1, 2)]
ENEMY_COLOURS = [2, 6, 10, 7]
TYPE_NONE, TYPE_ENEMY = 0, 1
PTR_A, PTR_B = 0x07f8, 0x2bf8
PLAYER_SLOT_MASK = 0b00000011
FRAME_IRQ_LINE = 250
JOY_IDLE = 0b00011111
FIRE_PERIOD = 8

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


advisories = []
def advise(label, ok, detail=""):
    """A finding about the MACHINE this is running on, not about the code.

    It is printed loudly and repeated in the summary, but it does not fail the
    suite: the gate exists to judge the repository, and a developer's own
    emulator settings are not part of it. Making the code gate red for an
    environment problem trains people to ignore a red gate.
    """
    if not ok:
        advisories.append((label, detail))
    print(f"  {'ok  ' if ok else '!!  '} {label}{(' -- ' + detail) if detail else ''}")


# ===========================================================================
# Harness
# ===========================================================================
def step(mon, n=1, tries=8):
    """n game frames, each verified by the frame counter, stopping where the
    schedule for that frame has already been built and published."""
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
    """Everything this slice touches, at ONE instant, in five bulk reads."""
    act = rd(mon, sym["logActive"], MAX_LOGICAL)
    # logY/logX/logXHi/logPtr/logCol are contiguous and MAX_LOGICAL apart.
    log = rd(mon, sym["logY"], 5 * MAX_LOGICAL)
    srt = rd(mon, sym["sortedIDs"], MAX_LOGICAL + 1)
    # READ THE SCALARS BY SYMBOL, NOT BY COMPUTED OFFSET.
    #
    # This used to bulk-read from objType and index the three counters at
    # 3*MAX_OBJECTS onward, which silently assumed objType/objVX/objVY were the
    # only per-object arrays. Slice D inserted objHP and objTimer ahead of the
    # counters, and the "double free" counter quietly became a live enemy's
    # health -- a probe reporting six double frees on a pool that had had one.
    # One extra monitor command is a fair price for a read that cannot drift
    # when the next slice adds a field.
    pool = rd(mon, sym["objType"], 3 * MAX_OBJECTS)
    counters = rd(mon, sym["objPeak"], 3)
    misc = rd(mon, sym["logCount"], 1)
    g = lambda i: log[i * MAX_LOGICAL:(i + 1) * MAX_LOGICAL]
    n = srt[MAX_LOGICAL]
    return {
        "active": act, "logY": g(0), "logX": g(1), "logXHi": g(2),
        "logPtr": g(3), "logCol": g(4),
        "sortedIDs": srt[:MAX_LOGICAL], "sortedCount": n,
        "window": srt[:n], "logCount": misc[0],
        "objType": pool[0:MAX_OBJECTS],
        "objVX": pool[MAX_OBJECTS:2 * MAX_OBJECTS],
        "objVY": pool[2 * MAX_OBJECTS:3 * MAX_OBJECTS],
        "peak": counters[0],
        "allocFail": counters[1],
        "doubleFree": counters[2],
        "live": [i for i in range(MAX_LOGICAL) if act[i]],
    }


def sched(mon, which="next"):
    """One schedule buffer, by logical identity. NEXT is what the builder just
    wrote; CURRENT is the immutable copy the executor is reading."""
    buf = rd(mon, sym["schedNext" if which == "next" else "schedCurrent"])[0]
    base = buf * MAX_SCHED
    n = rd(mon, sym["statAccepted"])[0]
    ids = rd(mon, sym["schedId"] + base, MAX_SCHED)
    ys = rd(mon, sym["schedY"] + base, MAX_SCHED)
    xs = rd(mon, sym["schedX"] + base, MAX_SCHED)
    xh = rd(mon, sym["schedXHi"] + base, MAX_SCHED)
    pt = rd(mon, sym["schedPtr"] + base, MAX_SCHED)
    sl = rd(mon, sym["schedSlot"] + base, MAX_SCHED)
    return {"buf": buf, "n": n, "ids": ids[:n], "y": ys[:n], "x": xs[:n],
            "xhi": xh[:n], "ptr": pt[:n], "slot": sl[:n],
            "raw_ids": ids, "raw_y": ys}


def call_x(mon, addr, x=0):
    """Call a main-thread routine on its own with X set, then put the CPU back.

    The sentinel and the PC restore are test_p4's, including the lesson in its
    docstring: leaving the PC on the sentinel executes schedule data as code and
    every later result in the file is quietly garbage.
    """
    mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
    mon.cmd(f"r sp=fd, pc={addr:04x}, x={x:02x}")
    bb = set_bp(mon, 0xc0fe)
    mon.cmd("x")
    mon.cmd(f"delete {bb}")
    mon.cmd(f"r pc={sym['mainLoop']:04x}")
    mon.cmd("delete")


def force_spawn(mon, entry=None):
    """One spawn on the next frame, through the REAL spawner."""
    if entry is not None:
        poke(mon, sym["enySpawnNext"], entry)
    poke(mon, sym["enySpawnTimer"], 1)
    step(mon, 1)


def populate(mon, n, entry=None):
    """Grow the live population to exactly n through the real spawn path."""
    for _ in range(n * 3):
        if rd(mon, sym["logCount"])[0] >= n:
            break
        force_spawn(mon, entry)
    return rd(mon, sym["logCount"])[0]


def clear_pool(mon):
    """Free every slot directly through the pool's own API."""
    for i in range(MAX_OBJECTS):
        call_x(mon, sym["objectFree"], i)
    poke(mon, sym["enySpawnTimer"], 200)        # no spawn during the next steps


def hold_stick(mon, value=JOY_IDLE):
    poke(mon, sym["joyHold"], 1)
    poke(mon, sym["joyState"], value)


# ===========================================================================
def source_invariants():
    print("=== 1. gameplay owns 'active'; the renderer owns the hardware ===")
    src = {n: (ROOT / "src" / f"{n}.asm").read_text() for n in ("objects", "enemy")}

    for name, text in src.items():
        body = re.sub(r"//.*", "", text)
        vic = re.findall(r"^\s*st[axy]\s+\$d0[0-9a-f]{2}", body, re.M | re.I)
        check(f"{name}.asm writes no VIC register", not vic, f"{vic[:3]}")
        ptr = re.findall(r"^\s*st[axy]\s+\$(?:07f8|2bf8)", body, re.M | re.I)
        check(f"{name}.asm writes no sprite pointer table", not ptr, f"{ptr[:3]}")
        rdv = re.findall(r"^\s*ld[axy]\s+\$d0[0-9a-f]{2}", body, re.M | re.I)
        check(f"{name}.asm reads no VIC register", not rdv, f"{rdv[:3]}")

    body = re.sub(r"//.*", "", src["enemy"])
    scroll = re.findall(r"(scrollFine|stageTopRow|worldProgress|curPage|schedNext)", body)
    check("the enemy reads no scroller or renderer state", not scroll, f"{set(scroll)}")

    # The hardware slot must be nowhere in gameplay: not as a constant, not as
    # an array index, not even by name.
    for name, text in src.items():
        body = re.sub(r"//.*", "", text)
        slots = re.findall(r"(MUX_FIRST_SLOT|MUX_SLOTS|schedSlot|bitMask)", body)
        check(f"{name}.asm never names a hardware sprite slot", not slots, f"{set(slots)}")

    sorter = (ROOT / "src" / "sorter.asm").read_text()
    check("the sorter reads membership from logActive, not from a count prefix",
          "logActive,x" in sorter and "sortRebuild" in sorter)
    # Scoped to sortTick's OWN body: sortReset still sets the count from
    # logCount, legitimately and once per fixture load, and a file-wide regex
    # cannot tell the two apart.
    body = sorter[sorter.index("sortTick:"):sorter.index("st_done:")]
    check("sortTick no longer resizes the window from logCount",
          not re.search(r"lda\s+logCount\s*\n\s*sta\s+sortedCount", body))
    check("sortTick rebuilds membership when, and only when, it changed",
          "lda sortDirty" in body and "jsr sortRebuild" in body)


# ===========================================================================
def pool_lifecycle(mon):
    print("\n=== 2. pool lifecycle ===")
    clear_pool(mon)
    step(mon, 1)
    s = snap(mon)
    check("1. the pool starts empty",
          s["logCount"] == 0 and not s["live"], f"count {s['logCount']} live {s['live']}")

    # --- allocation -------------------------------------------------------
    call_x(mon, sym["objectAlloc"], 0)
    # objectAlloc leaves the slot INACTIVE by design, so membership is unchanged.
    s = snap(mon)
    check("2. allocation reserves a slot without activating it",
          s["logCount"] == 0 and not s["live"], f"count {s['logCount']}")

    clear_pool(mon)
    n = populate(mon, 1)
    s = snap(mon)
    check("2b. a real spawn returns a valid free slot and fills it",
          len(s["live"]) == 1 and s["objType"][s["live"][0]] == TYPE_ENEMY,
          f"live {s['live']}")
    check("3. the active count matches the membership bits",
          s["logCount"] == len(s["live"]) == s["sortedCount"],
          f"logCount {s['logCount']} bits {len(s['live'])} sorted {s['sortedCount']}")

    # --- bounded, and full fails safely -----------------------------------
    clear_pool(mon)
    poke(mon, sym["objAllocFail"], 0)
    got = populate(mon, MAX_OBJECTS)
    s = snap(mon)
    check(f"4. allocation is bounded at {MAX_OBJECTS}",
          got == MAX_OBJECTS and len(s["live"]) == MAX_OBJECTS, f"{got} live {len(s['live'])}")
    check("4b. every live object is inside the pool's own slot range",
          all(i < MAX_OBJECTS for i in s["live"]), f"{s['live']}")

    before = snap(mon)
    force_spawn(mon)                            # the seventeenth
    after = snap(mon)
    check("5. a full pool refuses the allocation and counts it",
          rd(mon, sym["objAllocFail"])[0] >= 1 and after["logCount"] == MAX_OBJECTS,
          f"allocFail {after['allocFail']} count {after['logCount']}")
    check("5b. the refusal changed no other object",
          after["objType"] == before["objType"] and after["live"] == before["live"])
    check("5c. and raised no sorter fault", rd(mon, sym["sortFault"])[0] == 0)

    # --- free, reuse, double free ----------------------------------------
    victim = before["live"][3]
    call_x(mon, sym["objectFree"], victim)
    s = snap(mon)
    check("6. free returns the slot to the pool",
          victim not in s["live"] and s["logCount"] == MAX_OBJECTS - 1,
          f"count {s['logCount']}")
    check("6b. and clears its gameplay and presentation fields",
          s["objType"][victim] == TYPE_NONE and s["logY"][victim] == 0
          and s["objVY"][victim] == 0, f"type {s['objType'][victim]} y {s['logY'][victim]}")

    poke(mon, sym["objDoubleFree"], 0)
    call_x(mon, sym["objectFree"], victim)      # again, on an already-free slot
    s2 = snap(mon)
    check("8. a double free is a counted no-op, not a corruption",
          s2["logCount"] == MAX_OBJECTS - 1 and s2["doubleFree"] == 1
          and s2["live"] == s["live"], f"count {s2['logCount']} dbl {s2['doubleFree']}")

    force_spawn(mon)
    s3 = snap(mon)
    check("7. the freed slot is the one reused",
          victim in s3["live"] and s3["logCount"] == MAX_OBJECTS,
          f"live {s3['live']}")
    check("7b. and the reused slot inherited nothing from its previous life",
          s3["logY"][victim] == ENEMY_SPAWN_Y, f"y {s3['logY'][victim]}")

    # --- 0 -> 1 -> 0 -------------------------------------------------------
    clear_pool(mon)
    step(mon, 1)
    a = snap(mon)
    populate(mon, 1)
    b = snap(mon)
    slot = b["live"][0]
    call_x(mon, sym["objectFree"], slot)
    step(mon, 1)
    c = snap(mon)
    check("9. the 0 -> 1 -> 0 lifecycle is clean at every step",
          a["logCount"] == 0 and b["logCount"] == 1 and c["logCount"] == 0
          and a["sortedCount"] == 0 and b["sortedCount"] == 1 and c["sortedCount"] == 0,
          f"{a['logCount']}/{b['logCount']}/{c['logCount']}")
    check("9b. and leaves no live membership bit behind", not c["live"])


# ===========================================================================
def sort_membership(mon):
    print("\n=== 3. sort membership: the stale-ID hazard ===")
    clear_pool(mon)
    populate(mon, 1)
    s = snap(mon)
    check("10. one active enemy produces exactly one sorted ID",
          s["sortedCount"] == 1 and s["window"] == s["live"], f"{s['window']}")

    clear_pool(mon)
    populate(mon, 6)
    step(mon, 3)
    s = snap(mon)
    ys = [s["logY"][i] for i in s["window"]]
    check("11. multiple active enemies are sorted by Y",
          ys == sorted(ys) and len(ys) == s["logCount"], f"{ys}")
    check("12. no inactive slot appears in the window",
          all(s["active"][i] for i in s["window"]), f"{s['window']}")
    check("12b. every active object appears exactly once",
          sorted(s["window"]) == s["live"], f"{s['window']} vs {s['live']}")

    # --- 13: despawn the FIRST, MIDDLE and LAST sorted object ------------
    for where, pick in (("first", 0), ("middle", None), ("last", -1)):
        clear_pool(mon)
        populate(mon, 6)
        step(mon, 3)
        s = snap(mon)
        w = list(s["window"])
        idx = (len(w) // 2) if pick is None else pick
        victim = w[idx]
        call_x(mon, sym["objectFree"], victim)
        step(mon, 1)
        t = snap(mon)
        n = sched(mon, "next")
        check(f"13. despawning the {where} sorted object removes it from NEXT",
              victim not in t["window"] and victim not in n["ids"]
              and t["sortedCount"] == len(w) - 1,
              f"freed {victim}, window {t['window']}, sched {n['ids']}")

    # --- 14: the exact shrink that used to leave a ghost -------------------
    clear_pool(mon)
    populate(mon, 8)
    step(mon, 4)
    s = snap(mon)
    for victim in list(s["window"])[:3]:
        call_x(mon, sym["objectFree"], victim)
    step(mon, 1)
    t = snap(mon)
    n = sched(mon, "next")
    stale = [i for i in t["window"] if not t["active"][i]]
    missing = [i for i in t["live"] if i not in t["window"]]
    check("14. shrinking the active count leaves no stale sortedIDs",
          not stale, f"stale {stale}")
    check("14b. and drops no live object out of the window",
          not missing, f"missing {missing}")
    check("14c. no stale ID reaches the schedule either",
          all(t["active"][i] for i in n["ids"]), f"{n['ids']}")
    check("14d. sortedIDs is still a permutation of every logical ID",
          sorted(t["sortedIDs"]) == list(range(MAX_LOGICAL)))
    check("14e. and the sorter raised no fault", rd(mon, sym["sortFault"])[0] == 0)

    # --- 15: slot reuse must not inherit a sort position ------------------
    clear_pool(mon)
    populate(mon, 5)
    step(mon, 20)                               # spread them well apart in Y
    s = snap(mon)
    victim = s["window"][0]                     # the one nearest the top
    call_x(mon, sym["objectFree"], victim)
    force_spawn(mon)                            # same slot comes straight back
    t = snap(mon)
    check("15. a reused slot takes its NEW sort position, not its old one",
          victim in t["live"] and t["logY"][victim] == ENEMY_SPAWN_Y,
          f"y {t['logY'][victim]}")
    ys = [t["logY"][i] for i in t["window"]]
    check("15b. and the window is still ordered after the reuse",
          ys == sorted(ys), f"{ys}")

    # --- 16: equal Y is deterministic -------------------------------------
    clear_pool(mon)
    populate(mon, 4)
    step(mon, 1)
    s = snap(mon)
    for i in s["live"]:
        poke(mon, sym["logY"] + i, 120)
        poke(mon, sym["objVY"] + i, 0)          # hold them level
    step(mon, 1)
    a = snap(mon)
    step(mon, 1)
    b = snap(mon)
    check("16. equal-Y ordering is the logical-ID tie-break",
          list(a["window"]) == sorted(a["window"]), f"{a['window']}")
    check("16b. and is identical on the next frame",
          list(a["window"]) == list(b["window"]), f"{a['window']} vs {b['window']}")

    # --- 17: nothing active at all ----------------------------------------
    clear_pool(mon)
    step(mon, 2)
    s = snap(mon)
    n = sched(mon, "next")
    check("17. zero active objects build a valid empty schedule",
          s["sortedCount"] == 0 and n["n"] == 0 and rd(mon, sym["statBatches"])[0] == 0,
          f"sorted {s['sortedCount']} accepted {n['n']}")
    check("17b. with no overflow and no fault",
          rd(mon, sym["statOverflow"])[0] == 0 and rd(mon, sym["sortFault"])[0] == 0)


# ===========================================================================
def publication(mon):
    print("\n=== 4. publication safety across a despawn ===")
    clear_pool(mon)
    populate(mon, 5)
    step(mon, 4)

    # CURRENT is the adopted, immutable copy. Read it, free an object it names
    # WITHOUT running a frame, and read it again.
    cur_before = sched(mon, "current")
    victim = [i for i in cur_before["ids"] if i < MAX_OBJECTS]
    check("18a. an enemy really is present in the adopted CURRENT schedule",
          len(victim) > 0, f"ids {cur_before['ids']}")
    if victim:
        v = victim[0]
        call_x(mon, sym["objectFree"], v)
        cur_after = sched(mon, "current")
        check("18. freeing an object cannot mutate the adopted CURRENT schedule",
              cur_after["raw_ids"] == cur_before["raw_ids"]
              and cur_after["raw_y"] == cur_before["raw_y"],
              f"freed {v}")
        check("18b. and CURRENT still names it, because CURRENT is immutable",
              v in cur_after["ids"])

        step(mon, 1)
        nxt = sched(mon, "next")
        s = snap(mon)
        check("19. the NEXT schedule reflects the new lifecycle state",
              v not in nxt["ids"] and v not in s["window"],
              f"next {nxt['ids']}")

    check("20a. the page publication is consistent",
          rd(mon, sym["statPageMismatch"])[0] == 0,
          f"{rd(mon, sym['statPageMismatch'])[0]}")
    check("20b. the pointer destination matches the published page",
          rd(mon, sym["statPtrMismatch"])[0] == 0,
          f"{rd(mon, sym['statPtrMismatch'])[0]}")
    # 20c IS A MARGIN CHECK, NOT A CORRECTNESS CHECK, AND IT IS MEASURED AS ONE.
    #
    # schedBuildDefer counts the renderer's OWN protection working: the frame
    # IRQ landed between buildSchedule and publishSchedule, so the pending
    # publication -- which is the buffer this build is overwriting, and was
    # therefore already superseded -- is withdrawn. src/renderer.asm's note on
    # it is explicit that this "costs at most one frame of latency and cannot
    # starve", and that the counter exists "so the cost is visible rather than
    # silent". A non-zero reading is visibility, not damage.
    #
    # Asserting exactly zero turned out to be asserting that the main thread
    # never grows, and it has no margin left at all. Measured directly, on this
    # section, with the turret slice's per-frame calls STUBBED OUT and replaced
    # by a delay loop that does nothing whatsoever:
    #
    #     +0 cycles a frame     0 of 2 runs reported a deferral
    #     +220 cycles a frame   1 of 3 runs reported one
    #     +620 cycles a frame   2 of 3 runs reported one
    #
    # So it is a continuous probability in the main thread's total cost, it is
    # not attributable to whatever was added last, and no implementation of
    # anything makes it reliably zero again. The mechanism is the same one 30b
    # below documents: this section is breakpoint-driven from end to end, every
    # stop parks the machine mid-frame and resumes it somewhere else, and the
    # main thread's length decides where. This counter is never reset before
    # the check, so it reports every coincidence since boot. The bound is therefore a SMALL
    # NUMBER rather than zero: one or two deferrals over this section is the
    # mechanism absorbing a coincidence, and the 11.7%-of-builds rate the
    # renderer measured on RING-SLOW -- hundreds over a run like this -- is what
    # the check is really for and is still caught.
    #
    # The per-population ladder in section 8 still asserts ZERO at every
    # population, and still passes, which is the stronger statement of the two.
    #
    # RE-EVALUATED AFTER THE TURRET SCHEDULING OPTIMISATION, because the whole
    # argument above rests on main-thread cost and that cost then fell by a
    # factor of six -- an ordinary frame's turret work went from about
    # 1,490 cycles to about 250. If the margin had come back, this would have
    # gone back to == 0. It did not: restored to == 0 and run six times, it
    # failed twice. It is a genuine zero-margin, breakpoint-sensitive
    # assertion and not a consequence of anything this slice added, so the
    # small bound stays.
    defers = rd(mon, sym["schedBuildDefer"])[0]
    check("20c. schedule publications withdrawn mid-build stay rare",
          defers <= 4, f"{defers}")


# ===========================================================================
def rendering(mon):
    print("\n=== 5. rendering: the enemy reaches the mux, and only the mux ===")
    clear_pool(mon)
    populate(mon, 4)
    step(mon, 5)

    # --- 21: the pointer, on whichever page is adopted --------------------
    #
    # READ THROUGH THE SCHEDULE, NOT OUT OF THE POINTER TABLE. The table itself
    # is TIME-SHARED: the HUD owns HW2-HW7 for rasters 4..40 and leaves its own
    # pointers ($c8..$d5) sitting in it, and the mux overwrites them per batch
    # further down the frame. A main-thread breakpoint lands at an arbitrary
    # raster, so sampling the table there reads whichever owner happened to
    # have it -- an earlier draft of this check duly "found" a HUD pointer in a
    # gameplay slot and called it a bug.
    #
    # What the engine actually promises is stated in two pieces, and both are
    # checked here: the SCHEDULE carries the right pointer for every entry, and
    # exFrame patches the destination to the adopted page every frame, which
    # statPtrMismatch verifies continuously from inside the machine.
    pages, ptrs_ok = set(), True
    for _ in range(10):
        step(mon, 1)
        n = sched(mon, "next")
        d018 = rd(mon, 0xd018)[0]
        pages.add(1 if (d018 & 0xf0) == 0xa0 else 0)
        for e, sid in enumerate(n["ids"]):
            if sid < MAX_OBJECTS and n["ptr"][e] != ENEMY_PTR:
                ptrs_ok = False
    check("21. every scheduled enemy carries the enemy bitmap pointer", ptrs_ok)
    check("21b. and both screen pages were adopted during the run",
          pages == {0, 1}, f"{sorted(pages)}")
    check("21c. with the pointer destination matching the page on every frame",
          rd(mon, sym["statPtrMismatch"])[0] == 0 and rd(mon, sym["statPageMismatch"])[0] == 0,
          f"ptr {rd(mon, sym['statPtrMismatch'])[0]} page {rd(mon, sym['statPageMismatch'])[0]}")

    # --- 22: the 255/256 crossing, in both directions ---------------------
    for entry, direction in ((2, "rightward"), (3, "leftward")):
        clear_pool(mon)
        force_spawn(mon, entry)
        s = snap(mon)
        slot = s["live"][0]
        x0 = s["logX"][slot] | (s["logXHi"][slot] << 8)
        crossed, sched_ok = False, True
        for _ in range(60):
            step(mon, 1)
            t = snap(mon)
            if not t["active"][slot]:
                break
            x = t["logX"][slot] | (t["logXHi"][slot] << 8)
            n = sched(mon, "next")
            for e, sid in enumerate(n["ids"]):
                if sid == slot:
                    if (n["x"][e] | (n["xhi"][e] << 8)) != x:
                        sched_ok = False
            if (x >= 256) != (x0 >= 256):
                crossed = True
                break
        check(f"22. the {direction} X-MSB crossing is correct",
              crossed and sched_ok, f"from {x0} to {x}, schedule agrees {sched_ok}")

    # --- 23: the Y-range reject still works -------------------------------
    clear_pool(mon)
    populate(mon, 3)
    step(mon, 2)
    poke(mon, sym["statRejRange"], 0)
    s = snap(mon)
    high = s["live"][0]
    poke(mon, sym["logY"] + high, 30)           # above MIN_SPRITE_Y: unrenderable
    poke(mon, sym["objVY"] + high, 0)
    step(mon, 1)
    n = sched(mon, "next")
    t = snap(mon)
    check("23. an object above the production Y band is refused, not drawn",
          high not in n["ids"] and rd(mon, sym["statRejRange"])[0] >= 1,
          f"rejRange {rd(mon, sym['statRejRange'])[0]} sched {n['ids']}")
    check("23b. but it is still ALIVE: the renderer rejected it, gameplay did not",
          t["active"][high] and high in t["window"], f"window {t['window']}")

    # --- 24: the counters stay sane under a full pool ---------------------
    clear_pool(mon)
    populate(mon, MAX_OBJECTS)
    step(mon, 6)
    acc = rd(mon, sym["statAccepted"])[0]
    ovf = rd(mon, sym["statOverflow"])[0]
    rej = [rd(mon, sym[k])[0] for k in ("statRejUnsafe", "statRejMargin", "statRejRange")]
    s = snap(mon)
    check("24. accepted plus every reject accounts for the whole sorted window",
          acc + ovf + sum(rej) == s["sortedCount"],
          f"accepted {acc} overflow {ovf} rejects {rej} window {s['sortedCount']}")
    check("24b. nothing was accepted beyond the schedule's capacity",
          acc <= MAX_SCHED, f"{acc}")
    check("24c. the batch count is sane", rd(mon, sym["statBatchOverflow"])[0] == 0)

    # --- 24d: reject ATTRIBUTION, pinned because it is not what it says ----
    #
    # A FINDING, NOT A SLICE C CHANGE. The builder files a genuinely
    # overlapping sprite -- one whose gap to its same-slot predecessor is below
    # SPRITE_HEIGHT -- under statRejRange, the OUT-OF-Y-RANGE counter, because
    # that reject path is reached by falling through the margin test into the
    # label the Y-bounds test jumps to. statRejUnsafe is reachable only on a
    # NEGATIVE gap, which the sorted invariant makes impossible, so it is dead.
    #
    # Admission itself is correct: the sprite is rejected either way and nothing
    # unsafe is ever drawn. Only the attribution is wrong. This lives in
    # P3/P4-qualified code and changing the counters' meaning could invalidate
    # their retained tests, so Slice C measures it, states it, and leaves it.
    clear_pool(mon)
    populate(mon, 7)
    s = snap(mon)
    for k, i in enumerate(s["live"]):
        poke(mon, sym["logY"] + i, 100 + 2 * k)      # gap 12 at the reuse point
        poke(mon, sym["objVY"] + i, 0)
    step(mon, 2)
    ru = rd(mon, sym["statRejUnsafe"])[0]
    rm = rd(mon, sym["statRejMargin"])[0]
    rr = rd(mon, sym["statRejRange"])[0]
    t = snap(mon)
    inband = all(MIN_SPRITE_Y <= t["logY"][i] <= MAX_SPRITE_Y for i in t["live"])
    check("24d. an overlapping sprite is rejected (correct) and filed under "
          "statRejRange (a known misattribution)",
          inband and rr >= 1 and ru == 0,
          f"every Y in band {inband}; unsafe {ru} margin {rm} range {rr}")

    # --- 25 / 26: the player and the HUD are untouched --------------------
    n = sched(mon, "next")
    check("25. no pool object was ever given a player slot",
          all(sl >= MUX_FIRST_SLOT for sl in n["slot"]), f"{n['slot']}")
    d015 = rd(mon, sym["plyPresEnable"])[0]
    check("25b. the player still publishes both reserved slots",
          (d015 & PLAYER_SLOT_MASK) == PLAYER_SLOT_MASK, f"${d015:02x}")
    check("26. the HUD is undisturbed",
          rd(mon, 0xd017)[0] == 0 and rd(mon, 0xd01c)[0] == 0,
          f"$d017 ${rd(mon, 0xd017)[0]:02x} $d01c ${rd(mon, 0xd01c)[0]:02x}")


# ===========================================================================
def enemy_behaviour(mon):
    print("\n=== 6. the migrated enemy behaves as the old game's straight dive ===")
    clear_pool(mon)
    force_spawn(mon, 0)
    s = snap(mon)
    slot = s["live"][0]
    check("the enemy spawns at the first renderable line",
          s["logY"][slot] == ENEMY_SPAWN_Y, f"y {s['logY'][slot]}")
    check("with the old game's spawn X and colour",
          (s["logX"][slot], s["logXHi"][slot]) == SPAWNS[0][:2]
          and s["logCol"][slot] == ENEMY_COLOURS[0],
          f"x {s['logX'][slot]} col {s['logCol'][slot]}")
    check("and the enemy bitmap pointer",
          s["logPtr"][slot] == ENEMY_PTR, f"${s['logPtr'][slot]:02x}")

    ys = []
    for _ in range(6):
        step(mon, 1)
        ys.append(snap(mon)["logY"][slot])
    deltas = {ys[i + 1] - ys[i] for i in range(len(ys) - 1)}
    check(f"it descends exactly {ENEMY_VY} pixels a frame, the old ingress vector",
          deltas == {ENEMY_VY}, f"{ys}")

    # Ride it all the way out.
    poke(mon, sym["enySpawnTimer"], 250)
    poke(mon, sym["enyDespawned"], 0); poke(mon, sym["enyDespawned"] + 1, 0)
    last_y, frames = 0, 0
    for _ in range(200):
        step(mon, 1); frames += 1
        t = snap(mon)
        if not t["active"][slot]:
            break
        last_y = t["logY"][slot]
    check("it despawns on the single rule, past the last renderable line",
          not t["active"][slot] and last_y + ENEMY_VY > ENEMY_DESPAWN_Y,
          f"last y {last_y} after {frames} frames")
    check("and the despawn went through the pool, not around it",
          rd(mon, sym["enyDespawned"])[0] == 1 and t["logCount"] == 0,
          f"despawned {rd(mon, sym['enyDespawned'])[0]}")
    check("leaving nothing in the schedule",
          sched(mon, "next")["n"] == 0)

    # The Slice B shot event still fires and is still consumed by nobody.
    clear_pool(mon)
    populate(mon, 3)
    hold_stick(mon, JOY_IDLE & ~0b00010000)     # fire held
    poke(mon, sym["wpnCooldown"], 0)
    poke(mon, sym["wpnHeatLo"], 0); poke(mon, sym["wpnHeatHi"], 0)
    poke(mon, sym["wpnOverheated"], 0)
    step(mon, 1)
    s = snap(mon)
    fired = rd(mon, sym["shotFired"])[0]
    check("firing still emits a shot event with enemies present",
          fired == 1, f"shotFired {fired}")
    ys_before = [s["logY"][i] for i in s["live"]]
    step(mon, 1)
    t = snap(mon)
    check("and the enemies do not react to it: collision is Slice D",
          all(t["active"][i] for i in s["live"])
          and [t["logY"][i] for i in s["live"]] == [y + ENEMY_VY for y in ys_before],
          f"{ys_before} -> {[t['logY'][i] for i in s['live']]}")
    hold_stick(mon, JOY_IDLE)


# ===========================================================================
def regression(mon):
    print("\n=== 7. Slices A, A' and B are unchanged ===")
    clear_pool(mon)
    populate(mon, 4)
    step(mon, 2)

    # 27: the player still moves.
    poke(mon, sym["plyX"], 160); poke(mon, sym["plyXHi"], 0)
    hold_stick(mon, JOY_IDLE & ~0b00000100)     # left
    x0 = rd(mon, sym["plyX"])[0]
    step(mon, 6)
    x1 = rd(mon, sym["plyX"])[0]
    check("27. the player still moves one pixel a frame with enemies alive",
          x0 - x1 == 6, f"{x0} -> {x1}")
    hold_stick(mon, JOY_IDLE)

    # 28: heat still rises and falls.
    poke(mon, sym["wpnHeatLo"], 0); poke(mon, sym["wpnHeatHi"], 0)
    poke(mon, sym["wpnOverheated"], 0); poke(mon, sym["wpnCooldown"], 0)
    hold_stick(mon, JOY_IDLE & ~0b00010000)
    step(mon, 4)
    h_up = rd(mon, sym["wpnHeatLo"], 2)
    hold_stick(mon, JOY_IDLE)
    # LONGER THAN THE CADENCE. Heat rises while the cooldown timer is non-zero,
    # which is Slice B's definition of "firing" and has nothing to do with the
    # button -- so for up to eight frames after release the gun is still
    # heating. Sampling at four frames measures the tail of the volley and
    # calls it a cooling failure.
    step(mon, FIRE_PERIOD + 6)
    h_dn = rd(mon, sym["wpnHeatLo"], 2)
    check("28. the weapon still heats while firing and cools when released",
          (h_up[0] | h_up[1] << 8) > 0 and (h_dn[0] | h_dn[1] << 8) < (h_up[0] | h_up[1] << 8),
          f"{h_up[0] | h_up[1] << 8} -> {h_dn[0] | h_dn[1] << 8}")
    check("28b. and the HUD gauge is still driven by it",
          rd(mon, sym["hudHeatLo"], 2) == h_dn, f"{rd(mon, sym['hudHeatLo'], 2)}")

    # 29 / 30: the frame transaction and the aperture.
    lines = set()
    for _ in range(4):
        step(mon, 1)
        lines.add(rd(mon, sym["frameEntryLine"])[0])
    check("29. the frame transaction is still at raster 250", lines == {FRAME_IRQ_LINE},
          f"{sorted(lines)}")
    # THE RECORD SKIP IS MEASURED ON A FREE RUN, NOT ACROSS BREAKPOINTS.
    # Every stop in this file parks the machine mid-frame and resumes it
    # somewhere else, so the main thread can legitimately miss a frame boundary
    # that it would never miss running normally. Counting those as engine faults
    # would make the suite's own instrument the thing it measures.
    #
    # statLate IS IN THIS LIST NOW, AND ITS OMISSION WAS THE BUG. 30b below
    # says "over a free run" and was reading a counter that had been
    # accumulating since boot -- across every breakpoint, every call_x and
    # every clear_pool in this file, which is precisely the state the comment
    # above says must not be counted. It measured the harness, and it did it
    # silently for as long as the harness happened to stay lucky: it began
    # reporting 1 when the turret combat slice made the main thread longer and
    # therefore changed where each of this file's hundred-odd stops parks the
    # machine. The engine was not late; the instrument was.
    for name in ("publishSkip", "statPageMismatch", "statPtrMismatch",
                 "statLate"):
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
    check("30c. and enemies were really live throughout that run",
          rd(mon, sym["logCount"])[0] > 0, f"logCount {rd(mon, sym['logCount'])[0]}")
    check("30b. the executor never ran late", rd(mon, sym["statLate"])[0] == 0,
          f"{rd(mon, sym['statLate'])[0]}")


# ===========================================================================
def ladder(mon):
    print("\n=== 8. production population ladder ===")
    print("     pop   span  peak  acc  batch  ovf  rejR  reuse  sortWork  "
          "recSkip schedSkip  over")
    rows = []
    for pop in (0, 1, 4, 8, 12, 16):
        clear_pool(mon)
        step(mon, 1)
        if pop:
            populate(mon, pop)
        step(mon, 2)
        for name in ("gameSpanMax", "gameSpanOver", "gameOverrun", "publishSkip",
                     "schedBuildDefer", "statMaxBatch", "objPeak"):
            poke(mon, sym[name], 0)
        # Measure over a window, topping the population up as objects descend
        # out of the world, so the load is a REAL one rather than a frozen pose.
        worst_acc = worst_batch = worst_sort = worst_live = 0
        for _ in range(30):
            live = rd(mon, sym["logCount"])[0]
            if pop and live < pop:
                poke(mon, sym["enySpawnTimer"], 1)
            step(mon, 1)
            worst_live = max(worst_live, rd(mon, sym["logCount"])[0])
            worst_acc = max(worst_acc, rd(mon, sym["statAccepted"])[0])
            worst_batch = max(worst_batch, rd(mon, sym["statBatches"])[0])
            w = rd(mon, sym["sortWork"], 2)
            worst_sort = max(worst_sort, w[0] | (w[1] << 8))
        r = {
            "pop": pop,
            "span": rd(mon, sym["gameSpanMax"])[0],
            "peak": worst_live,
            "acc": worst_acc,
            "batch": worst_batch,
            "ovf": rd(mon, sym["statOverflow"])[0],
            "rejR": rd(mon, sym["statRejRange"])[0],
            "reuse": rd(mon, sym["statReuse"])[0],
            "sort": worst_sort,
            "recSkip": rd(mon, sym["publishSkip"])[0],
            "schedSkip": rd(mon, sym["schedBuildDefer"])[0],
            "over": rd(mon, sym["gameOverrun"])[0] + rd(mon, sym["gameSpanOver"])[0],
        }
        rows.append(r)
        print(f"    {r['pop']:4d}  {r['span']:5d} {r['peak']:5d} {r['acc']:4d} "
              f"{r['batch']:6d} {r['ovf']:4d} {r['rejR']:5d} {r['reuse']:6d} "
              f"{r['sort']:9d} {r['recSkip']:8d} {r['schedSkip']:9d} {r['over']:5d}")

    check("the main thread finishes inside the frame at every population",
          all(r["over"] == 0 for r in rows),
          f"{[(r['pop'], r['over']) for r in rows]}")
    check("the frame-record publication never skipped",
          all(r["recSkip"] == 0 for r in rows),
          f"{[(r['pop'], r['recSkip']) for r in rows]}")
    check("no schedule publication was withdrawn mid-build",
          all(r["schedSkip"] == 0 for r in rows),
          f"{[(r['pop'], r['schedSkip']) for r in rows]}")
    check("the cost grows with the population, as it must",
          rows[-1]["span"] >= rows[0]["span"],
          f"{rows[0]['span']} -> {rows[-1]['span']}")
    check("nothing overflowed the schedule at any population",
          all(r["ovf"] == 0 for r in rows), f"{[(r['pop'], r['ovf']) for r in rows]}")
    return rows


# ===========================================================================
def vice_config_hygiene(before):
    print("\n=== 9. the user's VICE configuration is untouched ===")
    src = (ROOT / "tests" / "test_p0.py").read_text()
    args = re.search(r"args = \[X64.*?\]", src, re.S).group(0)
    check("automated runs pass +saveres, so nothing is ever written back",
          '"+saveres"' in args, args[:60])
    check("input settings are per-process command-line arguments only",
          '"-joydev1", "0"' in args and '"-joydev2", "0"' in args and '"+keyset"' in args)
    check("and -default keeps this process off the user's stored settings",
          '"-default"' in args)
    # A WRITE, not a mention: this very file names vicerc in order to hash it,
    # and an unscoped search for the word matches itself and calls that a
    # finding. Look for the operations that could modify one instead.
    writes = []
    for f in sorted(os.listdir(ROOT / "tests")):
        if not f.endswith(".py"):
            continue
        text = (ROOT / "tests" / f).read_text()
        for m in re.finditer(r"(write_text|write_bytes|shutil\.copy|open\([^)]*['\"][wa]['\"])", text):
            ctx = text[max(0, m.start() - 120):m.end() + 40]
            if re.search(r"vice|joy|keyset|keymap", ctx, re.I):
                writes.append(f"{f}:{m.group(1)}")
    check("no test writes a VICE configuration or input file", not writes, f"{writes}")
    for path, digest in before.items():
        now = hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else None
        check(f"unchanged across this run: {Path(path).name}", now == digest,
              "MODIFIED" if now != digest else "")

    # --- the MANUAL run must not be able to destroy those settings either ----
    #
    # `-default` means "ignore the user's vicerc". Combined with any save it
    # does not merely ignore the file, it overwrites it with factory defaults --
    # measured on a throwaway config: with -default and -saveres, KeySet1Fire,
    # all four direction bindings and JoyDevice2 are all destroyed. A manual run
    # opens a real window, and a window can save from its own menu whatever the
    # command line said, so a manual run must not start from factory defaults.
    mk = (ROOT / "Makefile").read_text()
    opts = re.search(r"^VICE_OPTS\s*:?=\s*(.+)$", mk, re.M).group(1)
    check("the manual run does not start from factory defaults",
          "-default" not in opts, opts)
    check("the manual run still refuses to write settings back",
          "+saveres" in opts, opts)
    check("selecting a keyset actually enables keysets",
          re.search(r"KEYSET\s*:?=.*filter 2 3.*-keyset", mk) is not None)

    # --- and the user's own bindings are checked for the trap that bit us ----
    #
    # KeySet1Fire drives CIA1 $DC00 bit 4, the only fire line the hardware has.
    # KeySet1Fire2/Fire3 are extra buttons on multi-button host controllers and
    # reach no C64 register. A config with directions and Fire2 but no Fire
    # moves the ship and never shoots, which is indistinguishable from a
    # firmware bug until someone reads the file.
    for path in before:
        text = Path(path).read_text()
        dev = re.search(r"^JoyDevice2=(\d+)", text, re.M)
        if not dev or dev.group(1) not in ("2", "3"):
            continue
        n_set = "1" if dev.group(1) == "2" else "2"
        has_fire = re.search(rf"^KeySet{n_set}Fire=", text, re.M)
        dirs = len(re.findall(rf"^KeySet{n_set}(?:North|South|East|West)=", text, re.M))
        advise(f"the selected keyset {n_set} has a real Fire binding, not only Fire2",
               bool(has_fire),
               f"{dirs} directions bound, KeySet{n_set}Fire "
               f"{'present' if has_fire else 'MISSING'}"
               + ("" if has_fire else
                  f"\n       -> the ship will move but never shoot. Add this line to"
                  f"\n          {path}, under [C64SC], and restart VICE:"
                  f"\n              KeySet{n_set}Fire=<the key code you want>"
                  f"\n          KeySet{n_set}Fire2 is an extra controller button and"
                  f"\n          reaches no C64 register; only Fire drives $DC00 bit 4."))


def vicerc_snapshot():
    out = {}
    for p in (Path.home() / ".config/vice/vicerc",
              Path.home() / ".vice/vicerc",
              Path.home() / "Library/Preferences/vice/vicerc"):
        if p.exists():
            out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ===========================================================================
def main():
    print("Slice C — dynamic logical object pool + the first production enemy\n")
    source_invariants()
    cfg = vicerc_snapshot()
    print(f"\n  (VICE config files being watched: {len(cfg)})")

    v = None
    try:
        v = Vice(6613, PRG, warp=True)
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")
        hold_stick(mon, JOY_IDLE)
        pool_lifecycle(mon)
        sort_membership(mon)
        publication(mon)
        rendering(mon)
        enemy_behaviour(mon)
        regression(mon)
        ladder(mon)
    finally:
        if v: v.close()
        print(f"\n  launched and reaped: {LAUNCHED_PIDS}")

    vice_config_hygiene(cfg)

    print()
    for label, detail in advisories:
        print(f"=== ADVISORY (this machine, not the code): {label} ===")
        if detail:
            print(f"    {detail}")
    if fails:
        print(f"=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
        return 1
    print("=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
