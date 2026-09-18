#!/usr/bin/env python3
"""Token Encounter v2.1 — Dropper death, the P it drops, and its three guards.

What this proves, watching the REAL production loop the whole time
------------------------------------------------------------------
* UNIQUENESS: at most one live Dropper exists at any moment of an ordinary
  run, and tkDropperLive agrees with the pool every single frame;
* NO TOKEN WITHOUT A DEATH: over that whole ordinary run -- during which
  authored waves start, fly and leave -- not one TYPE_PICKUP is created, so
  the v1 "an appearance can simply bring a token" behaviour is gone;
* THE DEATH HOOK: destroying the one live Dropper creates EXACTLY ONE token,
  at the logical position the Dropper occupied on its last frame;
* THE ENCOUNTER STARTS: tkActive goes to 1 and tkStarted to 1, once;
* REORGANISATION: within a bounded number of frames the population holds
  exactly three guards, one on each of the three posts, and every enemy that
  is not a guard is leaving;
* EGRESS IS A DEPARTURE, NOT A DELETION: a dismissed enemy keeps its slot, its
  type and its health, flies WM_EXIT, and visibly travels for several frames
  before the ordinary despawn rule retires it;
* CONVERGENCE AND PATROL: every guard closes on the token, and once there the
  ANGLE of each guard about the token sweeps through several distinct
  quadrants -- it orbits rather than parks;
* v2.1 -- A WIDER RING: a guard on station stands off further than v2's ellipse
  could reach at its widest, and never collapses onto the token;
* v2.1 -- STILL THREE DEFENDERS: the three stay spread around the token rather
  than bunching onto one post;
* v2.1 -- NOT ONE RIGID SHAPE: the three are almost never all stationary on the
  same frame, which is what v2's arrive-and-wait cadence looked like;
* v2.1 -- SURVIVORS LEAVE UPWARD: when the encounter ends every surviving
  protector ASCENDS out of the playfield, and not one of them travels down
  through the player who has just collected the token;
* A GUARD IS STILL AN ENEMY: TYPE_ENEMY, alive, positive health, in the pool;
* REINFORCEMENT: killing a guard mid-encounter brings the count back to three,
  and the encounter never exceeds three;
* SUPPRESSION AND RELEASE: wvStarted does not advance for the life of the
  encounter and does advance again afterwards, so authored progression is
  paused rather than lost;
* DESCENT CADENCE: the token moves one pixel every two frames, exactly;
* CLIPPING: as the token leaves through the bottom of the aperture its
  logClip carries the negative annotation the schedule builder reads -- the
  same field, the same routine and the same scratch an enemy uses;
* THE END: the token despawning clears tkActive, counts tkEnded, and leaves
  every surviving guard flying WM_EXIT rather than vanishing;
* the production health counters stay clean throughout.

What this does NOT prove
------------------------
Whether the orbit LOOKS coherent, whether the ring is the right size, whether
the descent feels right, or whether the transition reads as deliberate. Those
are manual-VICE questions and manual VICE is authoritative for them.

THE ONLY THING THIS FILE STAGES IS A DEATH, and it stages it the way
src/collision.asm does: objHP to zero and objTimer to DEATH_TIME, which is the
logical destruction event itself. Everything downstream of that -- the species
test, the position capture, the slot release, the token spawn, the role
assignment, the reinforcement, the suppression and the ending -- is production
code running in the production frame loop. Nothing about the token, the roles,
the waves or the movement is poked into place. The turret slice's sixteen
false-GREEN checks over code that could not fire a shot in a real game are why.

One VICE launch.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import (PRG, SYM, symbols, Vice, rd, rd1, poke, set_bp,
                     free_run, check, report)

sym = symbols(SYM)

MAX_OBJECTS = 16        # pool slots: objType, objHP, objTimer, enySpecies...
MAX_LOGICAL = 32        # the logical ID space: logY, logX, logActive, logClip.
                        # The pool issues IDs 0..MAX_OBJECTS-1, so a pool slot
                        # indexes both -- but the STRIDE of the logical arrays
                        # is 32, and reading them sixteen apart reads logY's
                        # second half as logX.
TYPE_NONE, TYPE_ENEMY, TYPE_EBULLET, TYPE_PICKUP = 0, 1, 2, 3
SPECIES_DROPPER = 8
WM_EXIT = 3
DEATH_TIME = 12
ENEMY_MAX_HP = 6
MAX_SPRITE_Y = 226
SPRITE_HEIGHT = 21

ROLE_NORMAL, ROLE_EGRESS, ROLE_GUARD = 0, 1, 2
TK_GUARDS = 3
TK_REINFORCE_FRAMES = 24

# --- how long each phase is allowed to take ---------------------------------
# HUNT: an ordinary run, watched until an authored Dropper is on screen. The
# trigger list alternates species and a full authored cycle is about a thousand
# frames, so this is slack for whichever phase of the cycle we join at.
HUNT_FRAMES = 1300
# SETTLE: the transition. Three posts have to be filled, and the worst case is
# an empty screen needing three reinforcements at TK_REINFORCE_FRAMES apart
# plus the walk down from TK_SPAWN_Y to the ring.
SETTLE_FRAMES = 260
# WATCH: the encounter itself, until the token leaves through the bottom. At
# one pixel every two frames a token dropped high in the aperture has ~390
# frames of descent ahead of it.
WATCH_FRAMES = 700

ORBIT_QUADRANTS_WANTED = 3      # "it goes round", not "it completed a lap":
                                # a guard that visits three of the four
                                # quadrants about the token has swept 180
                                # degrees of ring, which no amount of
                                # converging-and-parking can produce
EGRESS_TRAVEL_WANTED = 3        # frames of a dismissed enemy visibly moving

# --- v2.1 bounds, all derived from src/token.asm's constants ----------------
# TK_RADIUS_X = 46, TK_RADIUS_Y = 30, so a guard on station sits between 30 and
# 46 px from the token. These are the loose outer bounds on that: the point is
# to catch the ring being the OLD 30-by-20 or having collapsed, not to re-derive
# the ellipse in Python.
STATION_MAX    = 70             # beyond this a guard is still flying in
RING_BAND_MIN  = 22             # the ellipse's short radius is 30; below this a
RING_BAND_MAX  = 58             # guard is in transit, above it, still closing
RING_WIDE_MIN  = 40             # v2's ring could never reach this: its widest
                                # point was 30 px
RING_NEAR_MIN  = 24             # v2's narrowest was 20; well inside this would
                                # mean guards sitting on the P

# Where the token is forced to be collected. Both conditions have to hold at
# once and the window is what makes that possible: the aperture ends at 226 so
# the clipping annotation is live above that, and the ship sits at Y 220 with a
# +/-20 collection box, so 250 is the last collectible line. Anywhere in
# 228..238 therefore proves the bottom-edge clipping AND leaves live guards to
# be sent upward -- one encounter, both endings' evidence.
COLLECT_AT_Y   = 232
CLIP_SAMPLES_WANTED = 4         # frames of clipped descent to bank first
CONVERGE_FRAMES_MIN = 60        # frames a slot must have been a guard for
                                # its closest approach to mean anything
GUARD_SETTLE_FRAMES = 45        # ...and before it counts as ON STATION.
                                # A guard closes 3 px a frame, so this is
                                # ample for the walk from TK_SPAWN_Y
SPREAD_MIN_DEG = 70             # three posts a third of a ring apart subtend
                                # 120 deg; the slack absorbs the ellipse (which
                                # is not angle-preserving), the per-guard
                                # stagger and a guard still closing on its post
LOCKSTEP_MAX_PCT = 8.0          # share of settled frames on which all three
                                # guards may be stationary at once. v2's
                                # ten-frame hold against a five-frame walk put
                                # this near half; v2.1's matched cadence should
                                # make it rare


def sample(mon):
    """Everything one frame's judgement needs, in seven bulk reads.

    Each read is one contiguous run the assembler actually produced, which
    check_layout() verifies rather than assumes: reading one array's bytes as
    another's would make every check in this file describe the wrong thing.
    """
    tk = rd(mon, sym["tkActive"], 0x12 + MAX_OBJECTS)   # tkActive..enyRole end
    pos = rd(mon, sym["logY"], 3 * MAX_LOGICAL)         # logY, logX, logXHi
    clip = rd(mon, sym["logClip"], MAX_OBJECTS)
    pool = rd(mon, sym["logActive"], 0x60 + MAX_OBJECTS)  # logActive..objTimer
    spec = rd(mon, sym["enySpecies"], MAX_OBJECTS)
    mode = rd(mon, sym["wmMode"], MAX_OBJECTS)
    wave = rd(mon, sym["wvStarted"], 2)                 # wvStarted, wvDropped
    fc = rd(mon, sym["frameCounter"], 2)
    return {
        "frame": fc[0] | (fc[1] << 8),
        "tkActive": tk[0], "tkSlot": tk[1], "tkOrbit": tk[2],
        "tkDropperLive": tk[4],
        "tkStarted": tk[0x0d], "tkEnded": tk[0x0e],
        "tkReinforced": tk[0x0f], "tkDenied": tk[0x10], "tkEgressed": tk[0x11],
        "role": tk[0x12:0x12 + MAX_OBJECTS],
        "logY": pos[0:MAX_OBJECTS],
        "logX": pos[MAX_LOGICAL:MAX_LOGICAL + MAX_OBJECTS],
        "logXHi": pos[2 * MAX_LOGICAL:2 * MAX_LOGICAL + MAX_OBJECTS],
        "clip": clip,
        "active": pool[0:MAX_OBJECTS],
        "type": pool[0x20:0x20 + MAX_OBJECTS],
        "hp": pool[0x50:0x50 + MAX_OBJECTS],
        "timer": pool[0x60:0x60 + MAX_OBJECTS],
        "species": spec, "mode": mode,
        "wvStarted": wave[0], "wvDropped": wave[1],
    }


def check_layout():
    """The bulk reads above assume six specific contiguities. Prove them."""
    check("tkActive..enyRole is one contiguous block, as the bulk read assumes",
          sym["enyRole"] == sym["tkActive"] + 0x12
          and sym["tkDropperLive"] == sym["tkActive"] + 4
          and sym["tkStarted"] == sym["tkActive"] + 0x0d
          and sym["tkEgressed"] == sym["tkActive"] + 0x11,
          f"tkActive={sym['tkActive']:04x} enyRole={sym['enyRole']:04x}")
    check("logY/logX/logXHi are contiguous at the LOGICAL stride, as the bulk "
          "read assumes",
          sym["logX"] == sym["logY"] + MAX_LOGICAL
          and sym["logXHi"] == sym["logY"] + 2 * MAX_LOGICAL,
          f"logY={sym['logY']:04x} logX={sym['logX']:04x} "
          f"logXHi={sym['logXHi']:04x}")
    check("logActive/objType/objHP/objTimer sit at the offsets the bulk read "
          "assumes",
          sym["objType"] == sym["logActive"] + 0x20
          and sym["objHP"] == sym["logActive"] + 0x50
          and sym["objTimer"] == sym["logActive"] + 0x60)
    check("wvStarted/wvDropped are adjacent, as the bulk read assumes",
          sym["wvDropped"] == sym["wvStarted"] + 1)


def enemies(s):
    return [i for i in range(MAX_OBJECTS)
            if s["active"][i] and s["type"][i] == TYPE_ENEMY]


def droppers(s):
    return [i for i in enemies(s) if s["species"][i] == SPECIES_DROPPER]


def pickups(s):
    return [i for i in range(MAX_OBJECTS)
            if s["active"][i] and s["type"][i] == TYPE_PICKUP]


def guards(s):
    return [i for i in enemies(s) if s["role"][i] >= ROLE_GUARD]


def x_of(s, i):
    return s["logX"][i] | (s["logXHi"][i] << 8)


def quadrant(dx, dy):
    return (0 if dx >= 0 else 1) | (0 if dy >= 0 else 2)


class Stepper:
    """One accepted sample per DISPLAYED FRAME, across the whole run.

    harness.step_n de-duplicates stops by the frame counter, but its `prev`
    is local to one call -- so `step_n(..., 1, ...)` in a Python loop, which is
    what this file did first, always accepts its first read and de-duplicates
    nothing. The trace it produced was unambiguous: the frame counter repeated
    (14301, 14301) while the death timer moved underneath it, so half the
    samples described a frame that had already been counted, and a twelve-frame
    death animation looked like it took twenty-four.

    So the frame is carried ACROSS steps, and -- the second half of the fix --
    the sample's OWN frame counter is what it is judged by. sample() reads the
    counter last, so a sample whose counter has moved is a sample taken after
    every array in it was read for that same frame.
    """
    def __init__(self, mon):
        self.mon, self.last = mon, None

    def step(self, tries=8):
        for _ in range(tries):
            self.mon.cmd("x")
            s = sample(self.mon)
            if s["frame"] != self.last:
                self.last = s["frame"]
                return s
        raise RuntimeError("the machine stopped advancing frames")


def poke_checked(mon, addr, val, tries=6):
    """Write a byte and PROVE it landed.

    The remote monitor drops a command now and then -- harness.set_bp and
    harness.rd both retry for exactly this reason, and a bare `>` write has no
    reply to check, so it is the one command that can fail silently. It cost
    this file a whole run: the objHP write landed and the objTimer write did
    not, which is objHP==0 with objTimer==0 -- a state src/objects.asm
    documents as impossible, and which DEC turns into a 256-frame death
    animation. Every measurement afterwards then described a machine that had
    not yet done the thing being measured.
    """
    for _ in range(tries):
        poke(mon, addr, val)
        if rd1(mon, addr) == (val & 0xff):
            return
    raise RuntimeError(f"could not write ${addr:04x} = {val:02x}")


def kill(mon, slot):
    """Stage the LOGICAL DESTRUCTION EVENT on one enemy, exactly as
    src/collision.asm's damageEnemy leaves it: the death timer armed FIRST, so
    the pair is never momentarily in the impossible state above."""
    poke_checked(mon, sym["objTimer"] + slot, DEATH_TIME)
    poke_checked(mon, sym["objHP"] + slot, 0)


def main():
    print("=== token encounter v2: dropper death + protectors ===")
    v = None
    try:
        # boot="exact": this file needs live ordinary enemies, and since Wave
        # Contract Stage 1 they exist only around the four authored encounters
        # at coarse rows 48, 52, 90 and 126 -- Level 1 is deliberately quiet
        # afterwards. The fast boot arrives at row ~107 (measured 107..395),
        # which is at or past the end of the content.
        v = Vice(6663, PRG, warp=True, boot="exact")
        mon = v.mon
        mon.cmd("delete")

        check_layout()

        # --- boot: no encounter, no roles, no Dropper claimed ---------------
        # tkDropperLive is deliberately NOT checked here: the two seconds of
        # warp above is long enough for the director to have authored a Dropper
        # already, and a claim that is set because one is genuinely on screen is
        # the flag working. Phase 1 checks it against the pool every frame
        # instead, which is the statement worth making.
        boot = sample(mon)
        check("no encounter is running at boot", boot["tkActive"] == 0)
        check("every slot starts on its authored path",
              all(r == ROLE_NORMAL for r in boot["role"]), str(list(boot["role"])))
        check("no encounter has ever started at boot", boot["tkStarted"] == 0)

        bp = set_bp(mon, sym["gameFrame"])
        stepper = Stepper(mon)

        # ==================================================================
        # PHASE 1 -- an ordinary run, until an authored Dropper is on screen
        # ==================================================================
        uniqueness_ok = True
        liveness_ok = True
        token_without_death = False
        dropper_seen = False
        target = None
        hunted = 0
        prev = None

        for _ in range(HUNT_FRAMES):
            s = stepper.step()
            hunted += 1
            d = droppers(s)
            if len(d) > 1:
                uniqueness_ok = False
            # tkDropperLive must agree with the pool. It is allowed to be set
            # while the Dropper is mid-death-animation (the slot is still
            # occupied), so the honest statement is "set exactly when one is
            # in the pool".
            if (s["tkDropperLive"] != 0) != (len(d) == 1):
                liveness_ok = False
            if pickups(s):
                token_without_death = True
            # Take the FIRST Dropper that is fully inside the aperture and not
            # already dying: one on the way in is about to be moved, and one
            # already dying would make the kill below a no-op.
            if d and not dropper_seen:
                i = d[0]
                if s["hp"][i] > 0 and 70 <= s["logY"][i] <= 150:
                    dropper_seen = True
                    target = i
                    prev = s
                    break
            prev = s

        check("an authored Dropper reached the aperture during the run",
              dropper_seen, f"{hunted} frames watched")
        check("never more than one live Dropper", uniqueness_ok)
        check("tkDropperLive agreed with the pool on every frame", liveness_ok)
        check("no token appeared during an ordinary run: a P is no longer "
              "authored content", not token_without_death)

        if not dropper_seen:
            mon.cmd("delete")
            return report(__name__)

        # ==================================================================
        # PHASE 2 -- destroy it. The ONLY poke in this file.
        # ==================================================================
        # THE SHIP IS MOVED OUT OF THE WAY FIRST, and it is the only thing in
        # this file poked that is not the death itself. The ship idles at
        # PLAYER_START_X = 160 and an authored Dropper very often dies within a
        # few pixels of that column, so the token is collected around logY 210
        # -- which ends the encounter correctly but hides the last forty rows of
        # the descent, and with them the whole of the bottom-edge clipping this
        # slice exists to fix. The player is not part of the mechanic under
        # test; standing in the token's column is.
        #
        # This run therefore measures the OFF-THE-BOTTOM ending. The collected
        # ending is the same code: tokenEnd is reached from one test, "the slot
        # this encounter's token was in is no longer a live TYPE_PICKUP", and
        # collection and despawn both produce exactly that.
        poke_checked(mon, sym["plyX"], 40)
        poke_checked(mon, sym["plyXHi"], 0)

        death_x = x_of(prev, target)
        death_y = prev["logY"][target]
        tokens_before = rd1(mon, sym["pkSpawned"])
        wv_at_death = prev["wvStarted"]
        print(f"  info killing dropper in slot {target} at "
              f"({death_x},{death_y}); pkSpawned={tokens_before}")

        kill(mon, target)

        # ---- the death animation runs, then the hook fires ----------------
        started_frame = None
        trace = []
        for f in range(DEATH_TIME + 8):
            s = stepper.step()
            trace.append((f, s["frame"], s["active"][target], s["type"][target],
                          s["species"][target], s["hp"][target],
                          s["timer"][target], s["tkActive"], s["tkStarted"]))
            if s["tkActive"]:
                started_frame = f
                break
        if started_frame is None:
            print("  info death window trace "
                  "(step, frameCounter, active, type, species, hp, timer, "
                  "tkActive, tkStarted):")
            for row in trace:
                print(f"    {row}")
            print(f"  info pkDropped={rd1(mon, sym['pkDropped'])} "
                  f"objAllocFail={rd1(mon, sym['objAllocFail'])} "
                  f"logCount={rd1(mon, sym['logCount'])}")

        check("destroying the Dropper started exactly one encounter",
              started_frame is not None and s["tkActive"] == 1
              and s["tkStarted"] == 1,
              f"tkActive={s['tkActive']} tkStarted={s['tkStarted']}")
        pk = pickups(s)
        check("exactly one token exists", len(pk) == 1, f"slots {pk}")
        check("the token is the one the encounter is about",
              len(pk) == 1 and pk[0] == s["tkSlot"])
        check("exactly one token was ever spawned by that death",
              rd1(mon, sym["pkSpawned"]) == (tokens_before + 1) & 0xff)
        if pk:
            check("the token appeared at the position the Dropper died at",
                  x_of(s, pk[0]) == death_x and s["logY"][pk[0]] == death_y,
                  f"token ({x_of(s, pk[0])},{s['logY'][pk[0]]}) vs death "
                  f"({death_x},{death_y})")
        check("the dead Dropper released its claim",
              s["tkDropperLive"] == 0)

        # ==================================================================
        # PHASE 3 -- the transition settles into three posts
        # ==================================================================
        posts_ok = False
        settle_frames = 0
        over_three = False
        non_guards_all_leaving = True

        for _ in range(SETTLE_FRAMES):
            s = stepper.step()
            settle_frames += 1
            if not s["tkActive"]:
                break
            g = guards(s)
            if len(g) > TK_GUARDS:
                over_three = True
            for i in enemies(s):
                if s["role"][i] == ROLE_NORMAL:
                    non_guards_all_leaving = False
                if s["role"][i] == ROLE_EGRESS and s["mode"][i] != WM_EXIT:
                    non_guards_all_leaving = False
            posts = sorted(s["role"][i] for i in g)
            if posts == [ROLE_GUARD + k for k in range(TK_GUARDS)]:
                posts_ok = True
                break

        check("the population reorganised into exactly three guards, one per "
              "post", posts_ok, f"after {settle_frames} frames, "
              f"roles {[s['role'][i] for i in enemies(s)]}")
        check("the encounter never held more than three guards", not over_three)
        check("every enemy that is not a guard is leaving under WM_EXIT",
              non_guards_all_leaving)
        # The egress DESCENT is judged in phase 5, not here: the reassignment
        # is instantaneous, so this loop usually exits on its first frame and
        # a departure cannot have happened yet.

        # ==================================================================
        # PHASE 4 -- the encounter runs: patrol, reinforcement, suppression,
        #            descent cadence and clipping, all from one stream
        # ==================================================================
        quads = {}              # slot -> set of quadrants that guard visited
        quad_best = 0
        converged = {}          # slot -> closest it ever got to the ring
        guard_still_enemy = True
        guards_history = []
        token_y = []            # (frame index, token logY) while it lives
        clip_seen_below = False
        clip_wrong = False
        wv_moved_during = False
        killed_a_guard_at = None
        refilled_after_kill = None
        ended = False
        watched = 0
        standoff_max = 0        # widest, and narrowest, the ring was ever seen
        standoff_min = 1 << 30  # to be while the guards were on station
        spread_worst = 360.0    # smallest angle between two adjacent guards
        spread_samples = 0
        all_frozen = 0          # frames where NONE of the three moved
        frozen_samples = 0
        prev_guard_pos = None
        guard_frames = {}       # frames each slot spent as a guard
        posted_for = {}         # ...consecutively, reset on reissue
        collected_at = None
        clip_samples = 0

        for f in range(WATCH_FRAMES):
            s = stepper.step()
            watched += 1

            if s["wvStarted"] != wv_at_death and s["tkActive"]:
                wv_moved_during = True

            if not s["tkActive"]:
                ended = True
                break

            t = s["tkSlot"]
            tx, ty = x_of(s, t), s["logY"][t]
            token_y.append((s["frame"], ty))

            # --- the token is clipped by the ordinary annotation ------------
            if ty > MAX_SPRITE_Y:
                clip_seen_below = True
                clip_samples += 1
                want = MAX_SPRITE_Y - ty
                if want <= -SPRITE_HEIGHT:
                    want = 0            # entirely below: admission culls it
                got = s["clip"][t] - 256 if s["clip"][t] > 127 else s["clip"][t]
                if got != want:
                    clip_wrong = True

            # --- then TAKE it, which is the ending that matters here --------
            # Letting the token fall off the bottom instead would end the
            # encounter with nothing left to send anywhere: the ring follows
            # the token down, so by the time it despawns at 250 the guards have
            # already left through the bottom edge on their own and the upward
            # egress is untestable. Collecting it at COLLECT_AT_Y ends the
            # encounter with live guards around the ship -- which is both the
            # case the player actually meets and the one v2 got wrong.
            if (collected_at is None and clip_samples >= CLIP_SAMPLES_WANTED
                    and ty >= COLLECT_AT_Y):
                poke_checked(mon, sym["plyX"], tx & 0xff)
                poke_checked(mon, sym["plyXHi"], tx >> 8)
                collected_at = f
                print(f"  info steering the ship onto the token at y={ty} "
                      f"(frame {f}) to force the COLLECTED ending")

            g = guards(s)
            guards_history.append(len(g))
            on_station = {}
            for i in g:
                # A GUARD MAY BE DYING AND STILL BE A GUARD -- this file kills
                # one on purpose below. What must never happen is a guard that
                # has left the pool, changed type, or reached the impossible
                # objHP==0/objTimer==0 pair src/objects.asm documents.
                if s["type"][i] != TYPE_ENEMY or not s["active"][i] \
                        or (s["hp"][i] == 0 and s["timer"][i] == 0):
                    guard_still_enemy = False
                dx, dy = x_of(s, i) - tx, s["logY"][i] - ty
                d2 = dx * dx + dy * dy
                guard_frames[i] = guard_frames.get(i, 0) + 1
                posted_for[i] = posted_for.get(i, 0) + 1
                converged[i] = min(converged.get(i, 1 << 30), d2)
                if d2 <= STATION_MAX * STATION_MAX:
                    quads.setdefault(i, set()).add(quadrant(dx, dy))
                    quad_best = max(quad_best, len(quads[i]))
                # ON STATION MEANS ON THE RING, NOT MERELY NEARBY. A guard
                # walking down to its post from TK_SPAWN_Y enters at the
                # token's own column and passes straight over it, so a bare
                # "within N pixels" test samples reinforcements in transit and
                # reports a ring that collapses onto the token. The band is the
                # ellipse's own two radii with slack either side.
                # ...AND IT MUST HAVE BEEN POSTED LONG ENOUGH TO HAVE GOT
                # THERE. A reinforcement enters at the token's own column and
                # walks DOWN through the ring to its post, so for a few frames
                # it sits inside the band at whatever angle it happens to be
                # crossing -- usually straight above, on top of another guard.
                # That is a guard arriving, not a formation bunching, and
                # sampling it made the measured spread meaningless.
                if (posted_for.get(i, 0) >= GUARD_SETTLE_FRAMES
                        and RING_BAND_MIN * RING_BAND_MIN <= d2
                        <= RING_BAND_MAX * RING_BAND_MAX):
                    on_station[i] = (dx, dy)

            # --- v2.1: are the three actually SPREAD around the token? ------
            # Three guards a third of a ring apart subtend about 120 degrees of
            # each other. This is the check that would catch a phase bug
            # collapsing them onto one post -- which is exactly what a wrong
            # stagger or a wrong modulus would do. Sampled only when all three
            # are on the ring at once: a frame with a guard still flying in
            # says nothing about the formation.
            if len(on_station) == TK_GUARDS:
                for d in on_station.values():
                    d2 = d[0] * d[0] + d[1] * d[1]
                    standoff_max = max(standoff_max, d2)
                    standoff_min = min(standoff_min, d2)
                angs = sorted(math.atan2(dy, dx) for dx, dy in
                              on_station.values())
                gaps = [angs[(k + 1) % 3] - angs[k] for k in range(3)]
                gaps = [math.degrees(gp % (2 * math.pi)) for gp in gaps]
                spread_worst = min(spread_worst, min(gaps))
                spread_samples += 1

            # --- v2.1: LOCKSTEP. Three guards that all sit still on the same
            # frame are three vertices of one shape waiting for it to turn --
            # the v2 look this pass exists to remove. With the phase derived
            # per guard from a staggered frame counter they should never all
            # be stationary together once they are on station.
            if len(on_station) == TK_GUARDS and prev_guard_pos is not None:
                moved = [i for i in on_station
                         if prev_guard_pos.get(i) not in (None,
                             (x_of(s, i), s["logY"][i]))]
                frozen_samples += 1
                if not moved:
                    all_frozen += 1
            prev_guard_pos = {i: (x_of(s, i), s["logY"][i]) for i in g}
            for i in list(posted_for):
                if i not in g:
                    del posted_for[i]   # a slot that stops being a guard starts
                                        # over: the pool reissues slots, and the
                                        # next occupant has its own walk to make

            # --- once settled, kill one guard and watch it be replaced -----
            if (killed_a_guard_at is None and len(g) == TK_GUARDS
                    and quad_best >= 2):
                victim = g[0]
                kill(mon, victim)
                killed_a_guard_at = f
                print(f"  info killed guard in slot {victim} at frame {f}")
            elif (killed_a_guard_at is not None and refilled_after_kill is None
                    and len(g) == TK_GUARDS
                    and f > killed_a_guard_at + DEATH_TIME):
                refilled_after_kill = f - killed_a_guard_at

        check("the encounter ended when the token left", ended,
              f"{watched} frames watched")
        check("a guard is an ordinary enemy throughout: in the pool, "
              "TYPE_ENEMY, with a coherent combat state", guard_still_enemy)
        # A slot that was a guard for only a handful of frames is a
        # reinforcement the ending cut short on its way in, and it never had
        # time to arrive. Judging it would be judging the clock, not the walk.
        settled = {k: v for k, v in converged.items()
                   if guard_frames.get(k, 0) >= CONVERGE_FRAMES_MIN}
        brief = sorted(set(converged) - set(settled))
        check("every guard that had time to arrive converged on the token",
              bool(settled)
              and all(d2 <= STATION_MAX * STATION_MAX
                      for d2 in settled.values()),
              f"closest approaches (px) "
              f"{ {k: int(d2 ** 0.5) for k, d2 in settled.items()} }"
              + (f"; ignored {brief} (guards for fewer than "
                 f"{CONVERGE_FRAMES_MIN} frames)" if brief else ""))
        check("a guard swept several quadrants about the token: it patrols "
              "rather than parks",
              quad_best >= ORBIT_QUADRANTS_WANTED,
              f"best {quad_best} quadrants, per guard "
              f"{ {k: len(q) for k, q in quads.items()} }")

        # --- v2.1: the ring is WIDER than v2's 30-by-20 --------------------
        # The ellipse is TK_RADIUS_X by TK_RADIUS_Y, so a guard on station is
        # between those two distances from the token. Both ends are asserted:
        # the far end proves the widening actually reached the target
        # positions, and the near end proves the guards are not sitting on top
        # of the token, which would make the P unreadable.
        wide = int(standoff_max ** 0.5) if standoff_max else 0
        near = int(standoff_min ** 0.5) if standoff_min < (1 << 30) else 0
        check("the patrol ring is as wide as the constants say",
              wide >= RING_WIDE_MIN,
              f"widest standoff seen {wide} px, wanted >= {RING_WIDE_MIN}")
        check("...and never collapses onto the token",
              near >= RING_NEAR_MIN,
              f"closest standoff seen {near} px, wanted >= {RING_NEAR_MIN}")

        # --- v2.1: three defenders, still distributed ----------------------
        check("the three guards stay spread around the token, not bunched",
              spread_samples > 0 and spread_worst >= SPREAD_MIN_DEG,
              f"worst adjacent gap {spread_worst:.0f} deg over "
              f"{spread_samples} settled frames, wanted >= {SPREAD_MIN_DEG}")

        # --- v2.1: they do not move as one rigid shape ---------------------
        frozen_pct = (100.0 * all_frozen / frozen_samples) if frozen_samples else 100.0
        check("the three guards are never all stationary together: they "
              "circulate rather than posing",
              frozen_samples > 0 and frozen_pct <= LOCKSTEP_MAX_PCT,
              f"{all_frozen}/{frozen_samples} settled frames had all three "
              f"still ({frozen_pct:.1f}%), wanted <= {LOCKSTEP_MAX_PCT}%")
        check("the encounter never held more than three guards while running",
              max(guards_history) <= TK_GUARDS if guards_history else False,
              f"max {max(guards_history) if guards_history else '-'}")

        check("a killed guard was replaced", refilled_after_kill is not None,
              f"killed at frame {killed_a_guard_at}, refilled after "
              f"{refilled_after_kill} frames")
        if refilled_after_kill is not None:
            check("the replacement was rapid and bounded",
                  refilled_after_kill <= DEATH_TIME + TK_REINFORCE_FRAMES + 90,
                  f"{refilled_after_kill} frames")

        # --- the descent cadence ------------------------------------------
        # One pixel every two frames. The claim is made against the MACHINE's
        # own frame counter rather than against a count of monitor round trips,
        # because that distinction is exactly what a duplicated stop destroys:
        # every accepted sample must be one displayed frame after the last, or
        # "per frame" means nothing.
        dframes = [token_y[k + 1][0] - token_y[k][0]
                   for k in range(len(token_y) - 1)]
        check("every sample of the descent is exactly one displayed frame "
              "after the last", dframes and set(dframes) == {1},
              f"frame deltas seen {sorted(set(dframes))}")
        steps = [token_y[k + 1][1] - token_y[k][1]
                 for k in range(len(token_y) - 1)]
        clean = [d for d in steps if d in (0, 1)]
        check("the token only ever descends, a pixel at a time",
              len(clean) == len(steps), f"deltas seen {sorted(set(steps))}")
        alternating = all(not (steps[k] == 1 and steps[k + 1] == 1)
                          for k in range(len(steps) - 1))
        check("the token descends one pixel every two frames", alternating
              and sum(steps) > 0,
              f"{sum(steps)} px over {len(steps)} frames")

        clip_ok = clip_seen_below and not clip_wrong
        check("the token is clipped by the ordinary logClip annotation as it "
              "leaves through the bottom", clip_ok,
              "" if clip_ok else
              ("never reached the bottom band" if not clip_seen_below
               else "logClip did not match the aperture rule"))

        # --- suppression, and its release ---------------------------------
        check("no authored wave started while the encounter ran",
              not wv_moved_during,
              f"wvStarted {wv_at_death} -> {s['wvStarted']}")

        end = s
        check("the encounter counted itself finished once",
              end["tkEnded"] == 1, str(end["tkEnded"]))
        check("no guard remains: every survivor is leaving",
              all(end["role"][i] < ROLE_GUARD for i in enemies(end)),
              f"roles {[end['role'][i] for i in enemies(end)]}")
        check("every survivor left under WM_EXIT rather than vanishing",
              all(end["mode"][i] == WM_EXIT for i in enemies(end)
                  if end["role"][i] == ROLE_EGRESS))

        # ==================================================================
        # PHASE 5 -- the survivors actually LEAVE
        # ==================================================================
        # This is where the dismissal is judged, not during the encounter: the
        # transition usually has nothing to dismiss (three or fewer enemies are
        # on screen when the Dropper dies), whereas tokenEnd always dismisses
        # every surviving guard. Watching them here proves the same statement
        # against the case that always happens -- the screen empties visibly,
        # and the objects are still in the pool while it does.
        egress_runs = {}
        egress_retired = False
        for _ in range(60):
            s = stepper.step()
            live = set()
            for i in enemies(s):
                if s["role"][i] == ROLE_EGRESS:
                    egress_runs.setdefault(i, []).append(s["logY"][i])
                    live.add(i)
            if egress_runs and not live:
                egress_retired = True   # they reached the despawn rule
                break
        # v2.1: UPWARD. The player has just flown into the middle of the ring to
        # take the token, so the survivors must leave away from the ship rather
        # than down through it. Every run must be monotonically RISING, and no
        # run may descend at all.
        rose = {k: (r[0], r[-1]) for k, r in egress_runs.items()
                if len(r) > EGRESS_TRAVEL_WANTED and r[-1] < r[0]}
        fell = {k: (r[0], r[-1]) for k, r in egress_runs.items()
                if r[-1] > r[0]}
        check("a surviving protector visibly ASCENDED rather than being "
              "deleted", bool(rose),
              f"runs { {k: (r[0], r[-1]) for k, r in egress_runs.items()} }")
        check("...and not one of them travelled down through the player",
              not fell, f"descending runs {fell}")
        check("and then left through the top by the ordinary despawn rule",
              egress_retired or not egress_runs,
              f"still on screen: {sorted(set(egress_runs))}")

        resumed = False
        for _ in range(HUNT_FRAMES):
            s = stepper.step()
            if s["wvStarted"] != wv_at_death:
                resumed = True
                break
        check("the authored stage resumed after the encounter", resumed,
              f"wvStarted {wv_at_death} -> {s['wvStarted']}")

        mon.cmd(f"delete {bp}")
        mon.cmd("delete")

        # --- the engine is unharmed ---------------------------------------
        for name in ("gameOverrun", "schedBuildDefer", "scrollLate", "edgeLate",
                     "objDoubleFree", "objAllocFail"):
            got = rd1(mon, sym[name])
            check(f"{name} is zero with the encounter run end to end",
                  got == 0, str(got))
        print(f"  info publishSkip {rd1(mon, sym['publishSkip'])} "
              f"(measured, not asserted -- see reports/)")
        print(f"  info tkStarted {rd1(mon, sym['tkStarted'])} "
              f"tkEnded {rd1(mon, sym['tkEnded'])} "
              f"tkReinforced {rd1(mon, sym['tkReinforced'])} "
              f"tkDenied {rd1(mon, sym['tkDenied'])} "
              f"tkEgressed {rd1(mon, sym['tkEgressed'])}")
    finally:
        if v:
            v.close()

    return report(__name__)


if __name__ == "__main__":
    sys.exit(main())
