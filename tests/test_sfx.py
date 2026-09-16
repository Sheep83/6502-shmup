#!/usr/bin/env python3
"""The SFX subsystem, v1.1 -- three effects, one SID voice each.

What this proves
----------------
* MEMORY: the module is resident CPU-only code and state -- inside the
  VIC-invisible $1000-$1fff run, clear of the HUD code and the sorter either
  side of it, and clear of every VIC-visible and level-replaceable region;
* HEALTH: with sfxTick in the frame, ordinary uninterrupted play leaves the
  catastrophic engine diagnostics at zero;
* THE THREE EVENTS, through the real production frame loop: firing plays the
  fire effect, and heavier effects appear when things are destroyed and when
  the ship is hit;
* ONCE PER LOGICAL EVENT: over a live run, the number of requests the module
  received equals the number of logical events the game reported, exactly. So
  the kill sound does not retrigger across the twelve frames of explosion, and
  the hurt sound does not retrigger across the hundred frames of
  invulnerability;
* CADENCE: no fire effect outlives the weapon's own eight-frame period, and
  voice 1 is genuinely released between volleys;
* OWNERSHIP, ON THE BUS: every SID write a running game performs lands in a
  voice register, $d400-$d414, and every control byte written to a voice
  carries that voice's own waveform. The filter and the volume register are
  never touched during play. This is a store watchpoint over the whole chip,
  not an inspection of the source;
* NO STUCK GATE: a quiet game writes nothing to the SID at all -- no held gate,
  and no per-frame traffic, on any of the three voices;
* SIMULTANEOUS INDEPENDENT PLAYBACK, which is the point of v1.1: each effect
  activates its own voice and no other; fire, destruction and the player's hurt
  wail can all be in flight at once; one tick advances every playing channel by
  exactly one without touching another channel's state; and each of the three
  ends by itself, in its own time, leaving the others playing;
* SILENCE ON DEMAND: sfxInit leaves all three channels idle, and sfxSilence
  puts three PLAYING effects away at once, which is how a restart or a
  game-over cannot inherit a sound or leave a gate up.

What this does NOT prove
------------------------
Whether the three sounds are any good. Nothing in Python can hear, and nothing
here tries to judge a timbre: the weight and character of the fire report are a
question for a person in front of VICE. One volley is one gate rise, which IS
checked -- but as structure, never as sound.

ORDER MATTERS IN THIS FILE, and not for convenience. The health gate runs
FIRST, on a pristine machine. harness.call() hijacks the program counter and
the stack pointer in the middle of a gameFrame, abandoning that frame's work
part-done, and a watchpoint halts the CPU dozens of times -- after either, the
main-thread span and the publication handshake describe the debugger rather
than the game. So the sections that abuse the machine come last, and the
question "is ordinary play still healthy" is asked before any of them.

Proportionality: one VICE launch, no fixtures, and no engine qualification
replayed. This is a 360-byte module.
"""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, step_n, call, check, report)

# --- the contract, restated independently of the assembler ------------------
SFX_NONE, SFX_FIRE, SFX_KILL, SFX_HURT, SFX_ESHOT, SFX_TOKEN = 0, 1, 2, 3, 4, 5

SFX_CODE      = 0x1780          # src/sfx.asm's code segment
CPU_ONLY_LO   = 0x1000          # the VIC sees the character ROM here, so RAM
CPU_ONLY_HI   = 0x2000          # in this run is invisible to it
HUD_CODE_END  = 0x1768          # the neighbour below
SORTER        = 0x1e00          # the neighbour above
SFX_STATE     = 0xc600
SFX_STATE_LEN = 9               # id x3, frame x3, curCh, requests, reqId
COLLISION_END = 0xc5ff          # the state run below sfx state
HUD_STATE     = 0xc960          # ...and above it
VIC_BANK_END  = 0x4000
LEVEL_WINDOW  = (0x2c00, 0x3100)    # the level-replaceable enemy sprite window

# THE VOICE MAP, restated from src/sfx.asm. A channel is the voice number less
# one, and it indexes both the module's state arrays and the tables here.
CH_FIRE, CH_KILL, CH_HURT = 0, 1, 2
CHANNEL_OF    = {SFX_FIRE: CH_FIRE, SFX_KILL: CH_KILL, SFX_HURT: CH_HURT}

SID           = 0xd400
SFX_VOICES    = ((0xd400, 0xd406),  # voice 1: player fire
                 (0xd407, 0xd40d),  # voice 2: enemy and turret destruction
                 (0xd40e, 0xd414))  # voice 3: the ship taking damage
SID_CTRL      = (0xd404, 0xd40b, 0xd412)
SID_VOLUME    = 0xd418

# The waveform each voice's effect selects, and so the only control bytes that
# voice may ever see: the waveform gated, the same waveform with the gate
# dropped (the release frame at the end of an effect's sweep),
# and zero (the voice put away, and the falling edge sfxRequest writes).
# Voice 2 carries THREE effects -- the destruction crunch (noise), the enemy
# shot (pulse) and the token chime (triangle) -- so it is the one voice whose
# legal set is not a single waveform.
VOICE_WAVE    = {CH_FIRE: (0x80,),
                 CH_KILL: (0x80, 0x40, 0x10),   # crunch, enemy spit, token chime
                 CH_HURT: (0x20,)}

FIRE_SWEEP    = 3               # sfxLenTab's entry for the fire effect
FIRE_FRAMES   = FIRE_SWEEP + 2  # sweep, then a release frame, then a finish
KILL_FRAMES   = 12 + 2
HURT_FRAMES   = 30 + 2
WPN_FIRE_PERIOD = 8             # src/weapon.asm: frames between held volleys

JOY_FIRE_HELD = 0xef            # active low: bit 4 down, nothing else pressed
JOY_FIRE_LEFT = 0xeb            # ...and bit 2, left
JOY_FIRE_RIGHT = 0xe7           # ...and bit 3, right
JOY_IDLE      = 0xff

MIN_SPRITE_Y  = 55              # src/renderer.asm: the band the builder admits
MAX_OBJECTS   = 16              # src/objects.asm: pool slots
TYPE_ENEMY    = 1               # src/objects.asm
SHOT_DAMAGE   = 1               # src/collision.asm: health lost per cannon hit
HITSCAN_MIN_Y = 55              # src/collision.asm: the band a ray can reach
PLAYER_CANNON_L = 4             # src/player.asm: the left ray's X offset

# ONE consolidated read covers everything the accounting samples: plyHits
# ($c524), shotFired ($c576), csKillsLo/Hi ($c5fd) and the whole sfx state
# ($c600). Each monitor round trip costs a tenth of a second and a per-frame
# sample is the most expensive thing this file does, so the reads are folded
# into one dump rather than four.
SAMPLE_BASE   = 0xc520
SAMPLE_LEN    = 0xc608 - SAMPLE_BASE

# Which module a request came from, by the segment the return address lands in.
# These are the segment BASES from the build's memory map and the base of the
# next segment above each -- boundaries that move only when the map is
# deliberately rearranged, unlike the code sizes inside them.
CALLER_SEGMENTS = (
    ("player", 0x4000, 0x4300),
    ("weapon", 0x4600, 0x4800),
    ("collision", 0x4c00, 0x4d00),      # ...up to the pickup segment's base
    ("turrets", 0x6f00, 0x7500),
    ("waves", 0x7c00, 0x8000),
    ("pickup", 0x4d00, 0x5000),
)

# The only (effect, requesting module) pairs this game is allowed to produce.
LEGAL_HOOKS = {
    (SFX_FIRE, "weapon"),       # weaponFire, when a volley resolves
    (SFX_KILL, "collision"),    # applyDamage, when an enemy's health hits zero
    (SFX_KILL, "turrets"),      # turretDamage, when a turret is destroyed
    (SFX_HURT, "player"),       # playerTakeHit
    (SFX_ESHOT, "waves"),       # waveFireShot, on a hostile bolt that EXISTS
    (SFX_TOKEN, "pickup"),      # pickupCollect, on a token actually collected
}

PORT = 6529


# ---------------------------------------------------------------------------
# harness.call() sets X but not A, and sfxRequest takes its effect id in A.
# Same synthetic-return-address technique, and the same constraint on what may
# be called this way: a self-contained state routine, never one whose behaviour
# depends on frame cadence.
# ---------------------------------------------------------------------------
def call_a(mon, sym, routine, a):
    mon.cmd("> 01ff c0")
    mon.cmd("> 01fe fd")
    mon.cmd(f"r sp=fd, pc={sym[routine]:04x}, a={a:02x}")
    bb = set_bp(mon, 0xc0fe)
    mon.cmd("x")
    mon.cmd(f"delete {bb}")
    mon.cmd(f"r pc={sym['mainLoop']:04x}")


# The store's target and the byte that went out on the bus. EVERY SID WRITE IN
# v1.1 IS AN absolute,Y STORE -- the voice is an offset of 0, 7 or 14 in Y --
# so the operand the monitor disassembles is voice 1's register and the voice
# actually written is only recoverable by adding the index register. Reading
# group(1) alone would have reported the whole chip as voice 1.
STORE_RE = re.compile(
    r"ST[AXY] \$([0-9A-Fa-f]{4})(,[XY])?\s+-\s+A:([0-9a-fA-F]{2}) "
    r"X:([0-9a-fA-F]{2}) Y:([0-9a-fA-F]{2})")


def collect_sid_stores(mon, n, deadline=90.0):
    """Step a store watchpoint until n stores are read. Returns (pairs, misses).

    The watchpoint reply carries the instruction that just executed and the
    register file at that moment, so the value written is the accumulator --
    which is the only way to see a SID write at all. The chip is write-only and
    its registers are unreadable through the monitor: verified on this VICE
    build, where $d41c (voice 3's envelope, the one register the hardware does
    expose) reads zero whatever the voice is doing, with sound on or off.

    `misses` counts stops whose reply could not be read, so a store the regex
    failed on shows up as a discrepancy rather than as one fewer sample.
    """
    out, misses, end = [], 0, time.time() + deadline
    while len(out) < n and time.time() < end:
        reply = mon.cmd("x", idle=0.4, deadline=6.0)
        m = STORE_RE.search(reply)
        if m:
            addr = int(m.group(1), 16)
            if m.group(2) == ",X":
                addr += int(m.group(4), 16)
            elif m.group(2) == ",Y":
                addr += int(m.group(5), 16)
            out.append((addr & 0xffff, int(m.group(3), 16)))
        elif "Stop on store" in reply:
            misses += 1
    return out, misses


STOP_RE = re.compile(
    r"- A:([0-9a-fA-F]{2}) X:[0-9a-fA-F]{2} Y:[0-9a-fA-F]{2} "
    r"SP:([0-9a-fA-F]{2})")


def caller_of(addr):
    for name, base, top in CALLER_SEGMENTS:
        if base <= addr < top:
            return name
    return f"${addr:04x}"


def _identify(mon, reply):
    """(effect id, calling module) from a stop inside sfxRequest, or None.

    The first instruction has not run yet, so A still holds the effect id the
    caller passed, and the two bytes on top of the stack are the return address
    the jsr pushed -- one less than the instruction to come back to, which is
    inside the calling module. That pair is the whole proof that a hook is in
    the production path: not that a counter moved, but that THIS module asked
    for THAT sound while the game was running its own code.
    """
    m = STOP_RE.search(reply)
    if not m:
        return None
    a, sp = int(m.group(1), 16), int(m.group(2), 16)
    if sp >= 0xfe:                      # the return address would wrap
        return None
    lo, hi = rd(mon, 0x0101 + sp, 2)
    return a, caller_of((((hi << 8) | lo) + 1) & 0xffff)


def sample_requests(mon, sym, joy_addr, n=20):
    """Stop on every request for a short while: the ordinary traffic mix."""
    out, counts = [], {}
    mon.cmd("delete")
    set_bp(mon, sym["sfxRequest"])
    for i in range(n):
        if i % 6 == 0:
            poke(mon, joy_addr, (JOY_FIRE_LEFT, JOY_FIRE_RIGHT)[(i // 6) % 2])
        got = _identify(mon, mon.cmd("x", idle=0.4, deadline=8.0))
        if got:
            out.append(got)
            counts[got[0]] = counts.get(got[0], 0) + 1
    mon.cmd("delete")
    return out, counts


def deliver_a_kill(mon, sym, tries=10):
    """Put the ship under an enemy that is one cannon hit from death, and let
    the player's own gun finish it. Returns the identified pair, or None.

    WHY THIS IS ARRANGED RATHER THAN WAITED FOR, same as the hit below: a kill
    needs an enemy to cross the ship's column while the cadence allows a volley
    and the gun is not locked out on heat, and a VICE checkpoint suppresses
    warp, so waiting for that costs tens of seconds per attempt and misses often
    enough to make a gate useless.

    WHAT IS ARRANGED IS THREE NUMBERS, all of them states the game reaches by
    itself: how much health an enemy ALREADY ALIVE has left (set to exactly what
    one cannon takes off), which column the ship is in, and a cool gun. Slots
    that are free, not enemies, already dying, or outside the band a ray can
    reach are left alone. Everything after that is production code: weaponTick
    resolves the volley, traceRay picks the target, applyDamage takes the last
    point off and asks for the sound.
    """
    mon.cmd("delete")
    poke(mon, sym["joyState"], JOY_FIRE_HELD)
    for _ in range(tries):
        # BETWEEN ATTEMPTS THE MACHINE RUNS WITH NO CHECKPOINT ARMED, and that
        # is the point: a VICE checkpoint suppresses warp, so stepping frame by
        # frame to wait for the next wave covers a handful of frames a second.
        # Free-running in warp for a fraction of a second covers hundreds, which
        # is what it takes for the encounter director to put enemies on screen
        # when an attempt lands between waves.
        mon.cmd("delete")
        free_run(mon, sym["frameCounter"], 0.4)
        mon.cmd("delete")

        # Two dumps cover the pool's membership and the presentation view the
        # hitscan reads: $c580.. is logActive/objType/objHP, $c300.. is
        # logY/logX/logXHi. One read each, once per attempt.
        pool = rd(mon, sym["logActive"],
                  sym["objHP"] + MAX_OBJECTS - sym["logActive"])
        log = rd(mon, sym["logY"],
                 sym["logXHi"] + MAX_OBJECTS - sym["logY"])

        def arr(name):
            base, buf = ((sym["logActive"], pool) if name.startswith("obj")
                         or name == "logActive" else (sym["logY"], log))
            off = sym[name] - base
            return buf[off:off + MAX_OBJECTS]

        active, types, hp = arr("logActive"), arr("objType"), arr("objHP")
        ys, xs, xhs = arr("logY"), arr("logX"), arr("logXHi")

        ply_y = rd1(mon, sym["plyY"])
        target = next(
            (i for i in range(MAX_OBJECTS)
             if active[i] and types[i] == TYPE_ENEMY and hp[i]
             and HITSCAN_MIN_Y <= ys[i] < ply_y),
            None)
        if target is None:                              # between waves
            continue

        # The ship moves into the enemy's column: the left cannon's ray leaves
        # at plyX + PLAYER_CANNON_L and the hitbox is enemyX..enemyX+23, so the
        # enemy's own X puts both rays inside it.
        poke(mon, sym["plyX"], xs[target])
        poke(mon, sym["plyXHi"], xhs[target])
        poke(mon, sym["objHP"] + target, SHOT_DAMAGE)
        # A COOL GUN. Five seconds of held fire in the health run leaves the
        # weapon cycling through its overheat lockout, and a locked weapon
        # resolves no volley at all -- the reason an earlier version of this
        # waited a long time for a kill that could not happen.
        call(mon, sym, "weaponInit")

        mon.cmd(f"break {sym['sfxRequest']:04x} if A == {SFX_KILL}")
        got = _identify(mon, mon.cmd("x", idle=0.6, deadline=6.0))
        mon.cmd("delete")
        if got:
            return got
    mon.cmd("delete")
    return None


def deliver_a_hit(mon, sym, tries=6):
    """Put ONE real hostile projectile just above the ship and let the game do
    the rest. Returns the identified (effect, module) pair, or None.

    WHY THIS IS ARRANGED RATHER THAN WAITED FOR. A player hit is the rarest
    event in the game: turrets have to be on the aperture, one has to fire, the
    shot has to reach the hull, and each hit that lands buys a hundred frames
    of invulnerability. Measured, it arrives about once per five hundred
    frames -- and a VICE checkpoint suppresses warp, so waiting for one costs
    tens of seconds of wall clock per attempt and fails often enough to make a
    gate useless.

    WHAT IS ARRANGED IS THE PROJECTILE'S STARTING POINT AND NOTHING ELSE. It is
    launched by the game's own ebulletSpawn, aimed by the game's own
    ebulletAim, flown by ebulletTick inside the real frame loop, and the
    collision that follows is ebulletPlayerTick's -- which is what calls
    playerTakeHit, which is what asks for the sound. Every link in the chain
    under test runs in production code on a freely running machine; the test
    only decides where the shot comes from, exactly as it decides where the
    joystick is pointing.
    """
    mon.cmd("delete")
    set_bp(mon, sym["gameFrame"])
    poke(mon, sym["joyState"], JOY_IDLE)     # the ship holds still to be hit
    for _ in range(tries):
        mon.cmd("x")                         # the top of a frame: no gameFrame
        mon.cmd("delete")                    # work is in flight here
        poke(mon, sym["plyInvuln"], 0)
        px = rd(mon, sym["plyX"], 2)
        py = rd1(mon, sym["plyY"])
        poke(mon, sym["ebSpawnXLo"], px[0])
        poke(mon, sym["ebSpawnXHi"], px[1])
        poke(mon, sym["ebSpawnY"], max(py - 45, MIN_SPRITE_Y + 5))
        before = rd1(mon, sym["ebFired"])
        call(mon, sym, "ebulletSpawn")
        launched = rd1(mon, sym["ebFired"]) != before
        poke(mon, sym["plyInvuln"], 0)
        if not launched:                     # the three-projectile cap was full
            set_bp(mon, sym["gameFrame"])    # let one retire and try again
            continue
        mon.cmd(f"break {sym['sfxRequest']:04x} if A == {SFX_HURT}")
        got = _identify(mon, mon.cmd("x", idle=0.6, deadline=15.0))
        mon.cmd("delete")
        if got:
            return got
        set_bp(mon, sym["gameFrame"])
    mon.cmd("delete")
    return None



def main():
    sym = symbols(SYM)

    # --- 1. memory: resident, CPU-only, and out of everyone's way ------------
    # The module's own labels are the evidence for where it landed; the source
    # asserts the segment, and these are the boundaries that assertion is about.
    labels = {k: v for k, v in sym.items() if k.startswith("sfx")}
    code = {k: v for k, v in labels.items() if CPU_ONLY_LO <= v < VIC_BANK_END}
    state = {k: v for k, v in labels.items() if v >= 0xc000}
    check("the sfx module has both code and state labels",
          bool(code) and bool(state), f"{len(code)} code, {len(state)} state")

    lo, hi = min(code.values()), max(code.values())
    check("sfx code is inside the VIC-invisible $1000-$1fff run",
          CPU_ONLY_LO <= lo and hi < CPU_ONLY_HI, f"${lo:04x}-${hi:04x}")
    check("...starting where the source says, clear of the HUD code below",
          lo == SFX_CODE and lo > HUD_CODE_END,
          f"${lo:04x} vs ${HUD_CODE_END:04x}")
    check("...and clear of the sorter above", hi < SORTER, f"${hi:04x}")
    check("sfx code costs no VIC-visible capacity and no level-replaceable "
          "space",
          not (LEVEL_WINDOW[0] <= lo < LEVEL_WINDOW[1]) and hi < CPU_ONLY_HI,
          "the VIC reads the character ROM at $1000-$1fff, not this RAM")

    # sfxStateEnd is the module's own ceiling marker, one past the last byte,
    # and is the honest measure of the run's length -- max() over the labels
    # would count that marker itself as a byte of state.
    slo, send = min(state.values()), sym["sfxStateEnd"]
    check("sfx state is in the module-state region, outside VIC bank 0",
          slo == SFX_STATE and slo >= VIC_BANK_END, f"${slo:04x}")
    check("...clear of the collision state below and the HUD state above",
          slo >= COLLISION_END and send <= HUD_STATE,
          f"${slo:04x}-${send - 1:04x}")
    check("sfx state is nine bytes: two per voice, plus a scratch byte and a "
          "counter", send - slo == SFX_STATE_LEN, f"{send - slo}")

    v = None
    try:
        v = Vice(PORT, PRG, warp=True)
        mon = v.mon
        set_bp(mon, sym["gameFrame"])
        mon.cmd("x")

        # --- 2. health, FIRST, on a machine nothing has interfered with ------
        # Five seconds of real play with the trigger held, uninterrupted. The
        # counters are zeroed first only because the emulator has already
        # autostarted and run for several seconds before the monitor could
        # attach, and what is under test is this run, not that one.
        HEALTH = ("gameOverrun", "schedBuildDefer", "scrollLate",
                  "statPageMismatch", "statPtrMismatch")
        poke(mon, sym["joyHold"], 1)
        poke(mon, sym["joyState"], JOY_FIRE_HELD)
        for name in HEALTH + ("publishSkip", "gameSpanOver", "gameSpanMax"):
            poke(mon, sym[name], 0)
        mon.cmd("delete")

        ran = free_run(mon, sym["frameCounter"], 5)
        mon.cmd("delete")
        check("the health run really ran, non-stop, with the trigger held", ran)
        for name in HEALTH:
            val = rd1(mon, sym[name])
            check(f"{name} is zero with sfxTick in the frame", val == 0,
                  str(val))

        # publishSkip IS NOT ASSERTED AT ZERO, AND THAT IS A MEASUREMENT RATHER
        # THAN AN EXCUSE. Under five seconds of HELD FIRE -- heavier frames than
        # any other test in this suite runs -- it comes up non-zero
        # intermittently on the UNMODIFIED HEAD binary: measured over five
        # paired runs of an identical probe, HEAD gave 3, 0, 0, 3, 0 and this
        # build gave 0, 0, 0, 3, 0, with gameOverrun and scrollLate zero in
        # every one of the ten. The rates are indistinguishable, so demanding
        # zero here would be a flaky check that blamed this change for a
        # pre-existing engine characteristic.
        #
        # It is still CHECKED, against the envelope that measurement drew. A
        # main thread genuinely pushed over the edge by a new per-frame cost
        # would not produce three of these in five warped seconds; it would
        # produce hundreds, and would take gameOverrun with it.
        PUBLISH_SKIP_CEILING = 8
        skip = rd1(mon, sym["publishSkip"])
        check("publishSkip stays inside the envelope HEAD itself occupies",
              skip <= PUBLISH_SKIP_CEILING,
              f"{skip}, ceiling {PUBLISH_SKIP_CEILING} "
              f"(HEAD baseline under the same probe: 3/0/0/3/0)")
        check("the subsystem was busy throughout the health run",
              rd1(mon, sym["sfxRequests"]) > 0,
              f"sfxRequests {rd1(mon, sym['sfxRequests'])}")
        # gameSpanMax / gameSpanOver are NOT asserted here. Both are already
        # saturated on the unmodified HEAD binary under this same probe --
        # measured at 68, 104 and 92 over three baseline runs against 111, 100
        # and 105 with this module linked in, one overlapping spread with no
        # signal in it -- so a zero assertion would be a false claim about the
        # engine rather than a check on this change. gameOverrun, above, is the
        # counter that actually says whether a frame was missed, and it is zero.
        print(f"  info gameSpanMax {rd1(mon, sym['gameSpanMax'])} lines, "
              f"gameSpanOver {rd1(mon, sym['gameSpanOver'])} "
              f"(HEAD baseline: 68/104/92 over three runs)")

        # --- 3. the real frame loop: events, cadence, once per event ---------
        # A breakpoint only; nothing here hijacks the machine. This is the
        # section that proves the hooks are in the production path at all.
        set_bp(mon, sym["gameFrame"])
        poke(mon, sym["joyState"], JOY_FIRE_HELD)
        poke(mon, sym["plyInvuln"], 0)
        # THE COUNTER SATURATES AT 255, and the health run above deliberately
        # held the trigger for five seconds. A delta taken off a pinned counter
        # is not a measurement, so it is put back to zero here -- it is a
        # diagnostic with a defined starting value, and this is that value.
        poke(mon, sym["sfxRequests"], 0)

        def off(name):
            return sym[name] - SAMPLE_BASE

        N = 80
        trt0 = rd1(mon, sym["trtKills"])
        sample = step_n(mon, sym["frameCounter"], N, lambda: (
            rd(mon, sym["frameCounter"], 2),
            rd(mon, SAMPLE_BASE, SAMPLE_LEN)))
        trt1 = rd1(mon, sym["trtKills"])
        check(f"stepped {N} distinct production frames", len(sample) == N,
              str(len(sample)))

        ids = [b[off("sfxChId") + CH_FIRE] for _, b in sample]
        check("the fire effect really plays on VOICE 1 during ordinary held "
              "fire", SFX_FIRE in ids, f"ids seen on voice 1: {sorted(set(ids))}")
        check("...and voice 1 is genuinely released between volleys",
              SFX_NONE in ids, f"idle frames: {ids.count(SFX_NONE)}")
        check("nothing but the fire effect is ever routed to voice 1",
              set(ids) <= {SFX_NONE, SFX_FIRE}, str(sorted(set(ids))))
        # Live overlap is observed, not demanded: see section 6.
        live = [sum(1 for c in range(3) if b[off("sfxChId") + c]) for _, b in sample]
        print(f"  info busiest live frame used {max(live)} voice(s); "
              f"{sum(1 for n in live if n > 1)} of {len(live)} frames overlapped")

        # EVERY REQUEST IS COUNTED IN EXACTLY ONE of sfxAccepted/sfxRejected,
        # so their sum is the number of times gameplay asked for a sound. Every
        # logical event the game reports must be one request and no more -- that
        # is the claim, and this is the arithmetic for it.
        #
        # ALIGNMENT, because an off-by-one would hide the very thing the check
        # exists for. The counters read at the top of frame k describe events up
        # to and including frame k-1, and shotFired read there is the volley of
        # frame k-1 (weaponTick clears it below this breakpoint). So for any two
        # CONSECUTIVE samples, the counter delta and the later sample's
        # shotFired describe the same single frame. Pairs whose frame numbers
        # are not adjacent -- step_n retries a stalled monitor and can leave a
        # gap -- are dropped from both sides rather than fudged.
        def val16(b, name):
            return b[off(name)] | b[off(name) + 1] << 8

        req = events = pairs = gaps = 0
        for (fa, a), (fb, b) in zip(sample, sample[1:]):
            if (((fb[0] | fb[1] << 8) - (fa[0] | fa[1] << 8)) & 0xffff) != 1:
                gaps += 1
                continue
            pairs += 1
            req += (b[off("sfxRequests")] - a[off("sfxRequests")]) & 0xff
            events += 1 if b[off("shotFired")] else 0            # a volley
            events += (val16(b, "csKillsLo") - val16(a, "csKillsLo")) & 0xffff
            events += (b[off("plyHits")] - a[off("plyHits")]) & 0xff
        # Turret kills are read at the ends rather than per frame: a fourth
        # monitor round trip per sampled frame is a fifth of the whole test's
        # runtime, and this term is almost always zero over three seconds.
        events += (trt1 - trt0) & 0xff
        check("the sampled frames were overwhelmingly consecutive",
              pairs >= N - 5, f"{pairs} adjacent pairs, {gaps} gaps")
        check("plyHits did not saturate, so its delta is a real count",
              sample[-1][1][off("plyHits")] < 0xff,
              str(sample[-1][1][off("plyHits")]))
        check("requests == volleys + enemy kills + turret kills + player hits, "
              "exactly", req == events, f"{req} requests vs {events} events")
        check("the run actually fired",
              sum(1 for _, b in sample[1:] if b[off("shotFired")]) > 0)

        # Held fire is one volley every WPN_FIRE_PERIOD frames and the report is
        # deliberately shorter than that period. A fire effect that outlived its
        # own cadence would show as a run of the id that never returns to idle.
        runs, cur = [], 0
        for i in ids:
            if i == SFX_FIRE:
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0
        check("no fire effect outlives its own cadence",
              bool(runs) and max(runs) <= FIRE_FRAMES <= WPN_FIRE_PERIOD,
              f"longest run {max(runs) if runs else 0} frames, "
              f"budget {FIRE_FRAMES}, weapon period {WPN_FIRE_PERIOD}")

        # --- 3b. WHO asked for WHAT, read off the stack ----------------------
        # The accounting above proves the NUMBER of requests is right. This
        # proves their PROVENANCE: a breakpoint on sfxRequest itself, with the
        # effect id taken from A and the calling module from the return address
        # the jsr left on the stack. A hook wired to the wrong event, or a sound
        # requested by something that has no business requesting it, shows up
        # here and nowhere else.
        mon._drain()
        seen, counts = sample_requests(mon, sym, sym["joyState"])
        check("ordinary play is a stream of requests, and fire dominates it",
              counts.get(SFX_FIRE, 0) >= 5, f"counts by effect: {counts}")
        check("the FIRE effect is requested by the weapon, on a resolved volley",
              (SFX_FIRE, "weapon") in seen, str(sorted(set(seen))))

        kill = deliver_a_kill(mon, sym)
        check("the KILL effect is requested when something is destroyed",
              kill in ((SFX_KILL, "collision"), (SFX_KILL, "turrets")),
              str(kill))

        hurt = deliver_a_hit(mon, sym)
        check("the HURT effect is requested by the player, on taking damage",
              hurt == (SFX_HURT, "player"), str(hurt))

        identified = set(seen) | {p for p in (kill, hurt) if p}
        check("every identified request is a legal (effect, module) pair",
              identified <= LEGAL_HOOKS, str(sorted(identified)))
        print(f"  info identified hooks: {sorted(identified)}")

        # --- 4. quiet: the voice is released and stays released --------------
        # The trigger comes up and the ship is made untouchable for the length
        # of the window, so no event can occur.
        poke(mon, sym["joyState"], JOY_IDLE)
        poke(mon, sym["plyInvuln"], 0xff)
        # $c600..$c607 in one read: the three channel ids, the three frame
        # indices, the tick's scratch byte and the request counter.
        quiet = step_n(mon, sym["frameCounter"], 24,
                       lambda: rd(mon, sym["sfxChId"], 8))
        check("every voice goes idle once the trigger is released",
              quiet[-1][:3] == [SFX_NONE] * 3, str(quiet[-1][:6]))
        tail = quiet[-12:]
        check("...and idle is ONE state on all three: nothing playing, every "
              "frame index reset",
              all(q[:6] == [0] * 6 for q in tail), str(tail[-1][:6]))
        check("no request arrives during a quiet window",
              tail[0][7] == tail[-1][7],
              f"sfxRequests {tail[0][7]}->{tail[-1][7]}")

        # NOW THE BUS, over the same quiet window. Both checkpoints are armed at
        # once, so each `x` stops at whichever comes first -- the next frame, or
        # a SID store. Bounding the window by FRAMES rather than by wall-clock
        # time is what makes it sound: plyInvuln counts down one per frame, and
        # in warp a bare one-second run is thousands of frames, long enough for
        # the ship to become vulnerable again and be hit. Re-arming it at every
        # stop keeps the window genuinely event-free.
        mon.cmd("delete")
        set_bp(mon, sym["gameFrame"])
        mon.cmd(f"watch store {SID:04x} {SID_VOLUME:04x}")
        before = rd(mon, sym["frameCounter"], 2)
        traffic, steps = 0, 40
        for _ in range(steps):
            poke(mon, sym["plyInvuln"], 0xff)
            if "Stop on store" in mon.cmd("x"):
                traffic += 1
        after = rd(mon, sym["frameCounter"], 2)
        mon.cmd("delete")
        advanced = ((after[0] | after[1] << 8)
                    - (before[0] | before[1] << 8)) & 0xffff
        check("the machine really ran during the silent-traffic window",
              advanced >= steps // 2, f"{advanced} frames over {steps} stops")
        check("a quiet game writes NOTHING to the SID -- no per-frame traffic, "
              "no held gate", traffic == 0, f"{traffic} stores")

        # --- 5. SID ownership, watched on the bus ----------------------------
        # The whole chip, not just the three voices: anything in this game that
        # wrote the filter or the master volume during play is caught here.
        mon.cmd("delete")
        mon._drain()
        mon.cmd("r")                            # resynchronise before the loop
        poke(mon, sym["joyState"], JOY_FIRE_HELD)
        poke(mon, sym["plyInvuln"], 0)
        mon.cmd(f"watch store {SID:04x} {SID_VOLUME:04x}")
        stores, misses = collect_sid_stores(mon, 40)
        mon.cmd("delete")
        check("a firing game really does write the SID", len(stores) >= 10,
              f"{len(stores)} stores read")
        check("every store the watchpoint caught was readable",
              misses == 0, f"{misses} unreadable stops")
        strays = sorted({a for a, _ in stores
                         if not any(lo <= a <= hi for lo, hi in SFX_VOICES)})
        check("every SID write during play lands in a voice register "
              "($d400-$d414), so the filter and $d418 are untouched by play",
              not strays, f"strays: {[hex(a) for a in strays]}")

        # WHICH VOICE, AND WHAT IT CARRIED. A write that crossed from one
        # channel's SID block into another's -- the failure mode a shared index
        # register makes possible -- shows up here as a sawtooth byte on voice 1
        # or a noise byte on voice 3, and nowhere else.
        for c in range(3):
            ctrls = [v for a, v in stores if a == SID_CTRL[c]]
            legal = {0x00}
            for w in VOICE_WAVE[c]:
                legal |= {w, w | 1}
            check(f"every control byte on voice {c + 1} is one of its own "
                  f"effects' waveforms, gated or not", set(ctrls) <= legal,
                  f"{sorted(hex(x) for x in set(ctrls))} vs "
                  f"{sorted(hex(x) for x in legal)}")

        # The envelope retriggers on the gate's RISING EDGE and on nothing
        # else, so a gate that goes up without having come down inherits the
        # previous sound's envelope instead of striking. Repeated identical
        # writes are not edges -- the sustained effects rewrite their control
        # byte every frame and the chip sees no change -- so the stream is
        # reduced to its transitions first.
        ctrls = [v for a, v in stores if a == SID_CTRL[CH_FIRE]]
        edges = [c for i, c in enumerate(ctrls) if i == 0 or c != ctrls[i - 1]]
        raised = [i for i, c in enumerate(edges) if c & 1]
        check("on voice 1 the gate is dropped before it is raised, every time",
              all(edges[i - 1] & 1 == 0 for i in raised if i > 0),
              f"{[hex(c) for c in edges]}")
        check("...and it was struck more than once inside the window, so a "
              "held trigger really does retrigger the report",
              len(raised) >= 2, f"{len(raised)} gate rises on voice 1")

        # --- 6. the API, and SIMULTANEOUS INDEPENDENT PLAYBACK ---------------
        # LAST, because harness.call() hijacks the program counter and the stack
        # pointer mid-frame; everything above was measured on a machine running
        # its own program. Overlap cannot be DEMANDED of a live run -- it needs
        # an enemy to die and the ship to be hit inside one 100 ms report -- so
        # the three events are delivered by hand here and everything the checks
        # then look at is sfxTick's own unassisted work.
        mon.cmd("delete")
        call(mon, sym, "sfxInit")
        st = rd(mon, sym["sfxChId"], SFX_STATE_LEN)
        check("sfxInit leaves all three voices idle and the counter cleared",
              st[:6] == [SFX_NONE] * 6 and st[7] == 0, str(st))

        def chans():
            """(id, frame) per channel, in one monitor read."""
            b = rd(mon, sym["sfxChId"], 6)
            return [(b[c], b[3 + c]) for c in range(3)]

        for eff, name in ((SFX_FIRE, "fire"), (SFX_KILL, "destruction"),
                          (SFX_HURT, "player-hit")):
            ch = CHANNEL_OF[eff]
            call(mon, sym, "sfxSilence")
            call_a(mon, sym, "sfxRequest", eff)
            st = chans()
            check(f"the {name} effect activates voice {ch + 1}, and ONLY voice "
                  f"{ch + 1}",
                  st[ch][0] == eff and all(st[i][0] == SFX_NONE
                                           for i in range(3) if i != ch),
                  str(st))

        # Started one frame apart, so a channel that had quietly copied
        # another's state would say so in its frame index.
        call(mon, sym, "sfxSilence")
        call_a(mon, sym, "sfxRequest", SFX_FIRE)
        call(mon, sym, "sfxTick")
        call_a(mon, sym, "sfxRequest", SFX_KILL)
        st = chans()
        check("fire and enemy destruction sound TOGETHER, on voices 1 and 2, "
              "each at its own point in its own effect",
              st[0][0] == SFX_FIRE and st[0][1] == 1
              and st[1][0] == SFX_KILL and st[1][1] == 0, str(st))
        call(mon, sym, "sfxTick")
        call_a(mon, sym, "sfxRequest", SFX_HURT)
        st = chans()
        check("...and the player-hit wail joins them on voice 3: all three "
              "playing at once, on three frame indices",
              [c[0] for c in st] == [SFX_FIRE, SFX_KILL, SFX_HURT]
              and [c[1] for c in st] == [2, 1, 0], str(st))

        # THE RESTART PATH, with the chip at its busiest. gameInit calls this.
        call(mon, sym, "sfxSilence")
        check("sfxSilence puts THREE playing effects away at once, so no "
              "restart or game-over can leave a gate up",
              chans() == [(SFX_NONE, 0)] * 3, str(chans()))

        # --- 7. three effects in flight, ending in their own time ------------
        for eff in (SFX_FIRE, SFX_KILL, SFX_HURT):
            call_a(mon, sym, "sfxRequest", eff)
        walk = [chans()]
        for _ in range(FIRE_FRAMES):
            call(mon, sym, "sfxTick")
            walk.append(chans())
        adv = [[w[c][1] for w in walk if w[c][0] != SFX_NONE] for c in range(3)]
        check("one tick advances EVERY playing channel by exactly one, and no "
              "channel's frame index disturbs another's",
              all(a == list(range(len(a))) for a in adv), str(adv))
        check("the fire report ends by itself while the other two play on",
              walk[-1][0] == (SFX_NONE, 0)
              and walk[-1][1][0] == SFX_KILL
              and walk[-1][2][0] == SFX_HURT, str(walk[-1]))
        for _ in range(KILL_FRAMES - FIRE_FRAMES):
            call(mon, sym, "sfxTick")
        st = chans()
        check("...then the destruction crunch ends, in its own time, with the "
              "wail still going",
              st[1] == (SFX_NONE, 0) and st[2][0] == SFX_HURT, str(st))
        for _ in range(HURT_FRAMES - KILL_FRAMES):
            call(mon, sym, "sfxTick")
        check("...and finally the wail ends, leaving ONE single idle state on "
              "every voice", chans() == [(SFX_NONE, 0)] * 3, str(chans()))
        call(mon, sym, "sfxTick")
        check("a tick with all three voices idle changes nothing",
              chans() == [(SFX_NONE, 0)] * 3, str(chans()))

        # A request restarts its OWN voice and touches no other: the only
        # arbitration v1.1 keeps, and the whole of what held fire relies on.
        call_a(mon, sym, "sfxRequest", SFX_HURT)
        for _ in range(4):
            call(mon, sym, "sfxTick")
        call_a(mon, sym, "sfxRequest", SFX_KILL)
        mid = chans()
        call_a(mon, sym, "sfxRequest", SFX_HURT)
        st = chans()
        check("a repeated request retriggers its own effect from frame 0",
              mid[2][1] > 0 and st[2] == (SFX_HURT, 0),
              f"was {mid[2]}, now {st[2]}")
        check("...and leaves the other voices exactly as they were",
              st[1] == mid[1] and st[0] == mid[0], f"{mid} -> {st}")

        call(mon, sym, "sfxSilence")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
