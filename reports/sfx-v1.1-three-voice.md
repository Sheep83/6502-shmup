# SFX v1.1 — all three SID voices during gameplay

**Date:** 2026-09-15
**Starting HEAD:** `0aff357023403e8d03175290a3ac0abbe6b0e1f6` — *Memory reconfigured for bank switch and multiload* (unchanged: **nothing was committed or pushed**)

**Starting working tree** — the uncommitted v1 SFX work, all of it preserved:

```
 M Makefile
 M src/collision.asm
 M src/main.asm
 M src/player.asm
 M src/turrets.asm
 M src/weapon.asm
?? reports/sfx-v1.md
?? src/sfx.asm
?? tests/test_sfx.py
```

**Final working tree** — the same nine paths, no additions and no deletions.
`src/sfx.asm` and `tests/test_sfx.py` were edited in place (both still
untracked); this report is the one new file. Nothing was reset, stashed,
cleaned or committed.

```
 M Makefile
 M src/collision.asm
 M src/main.asm
 M src/player.asm
 M src/turrets.asm
 M src/weapon.asm
?? reports/sfx-v1.1-three-voice.md
?? reports/sfx-v1.md
?? src/sfx.asm
?? tests/test_sfx.py
```

---

## 1. The previous one-voice architecture

v1 put all three effects on **voice 3** (`$d40e-$d414`) and reserved voices 1
and 2 for future music. One byte, `sfxId`, was the entire voice allocator; a
second, `sfxPri`, arbitrated between effects competing for that one voice, on
one rule — *accept when requested priority ≥ playing priority* — with
`sfxAccepted`/`sfxRejected` counting the outcome.

The weakness manual listening exposed was exactly the one the design implied:
**a shot fired while an enemy was exploding cut the explosion off.** That is not
audible as arbitration, it is audible as a bug.

The premise the reservation rested on is gone: **there is no in-level music, and
there is not going to be.** Music, if it comes, is for menus, transitions and
end-of-level screens — presentation states in which the game is not being
played. Holding two thirds of the chip back for something that by definition
never coexists with gameplay cost every overlapping effect in the game and
bought nothing.

## 2. Final voice mapping

| voice | registers | class | effect today |
|---|---|---|---|
| 1 | `$d400-$d406` | frequent / light | **player fire** |
| 2 | `$d407-$d40d` | enemy / world | **enemy and turret destruction** |
| 3 | `$d40e-$d414` | high-impact / player | **the ship taking damage** |

The mapping is **functional and author-time**, not dynamic. An effect's voice is
a constant looked up from its id (`sfxVoiceTab`). There is no allocator, no
mixer, no queue and no voice stealing, because we know what these three sounds
are and what each has to be able to overlap with. Enemy fire, when it arrives,
joins voice 2 with the rest of the world; a pickup chime joins voice 1 with the
other light traffic.

Voice 3 keeps player damage partly because it was already there and partly
because voice 3 is the one the hardware treats differently — it is the voice
that can be cut from the output on its own (`$d418` bit 7) — and the ship being
hit is the sound that would want that switch first.

**Future multi-voice effects are not prevented and not implemented.** Nothing in
the structure stops a later boss explosion from requesting work on two or three
channels; no such composite exists now.

## 3. Exact state and API changes

The **event → request → once-per-frame tick → SID** plumbing is v1's and has not
moved. `sfxInit` / `sfxSilence` / `sfxRequest` / `sfxTick` keep their names,
their call sites and their register contracts (`sfxRequest` still preserves X
and Y; A still carries the effect id).

| | v1 | v1.1 |
|---|---|---|
| `sfxId` | 1 byte, the single voice allocator | **`sfxChId`, 3 bytes** — one per voice |
| `sfxFrame` | 1 byte | **`sfxChFrame`, 3 bytes** — one per voice |
| `sfxPri` | 1 byte | **removed** |
| `sfxAccepted`, `sfxRejected` | 2 bytes | **`sfxRequests`, 1 byte** |
| `sfxReqId` | 1 byte scratch | unchanged |
| — | — | **`sfxCurCh`, 1 byte** — new scratch (see below) |
| **total** | **6 bytes** | **9 bytes** |

New internals, all private: `sfxVoiceTab` (effect id → channel), `sfxVoiceBase`
(channel → SID register offset 0/7/14), `sfxChannel` (advance one voice by one
frame), and `sfxSweepCtrl` (a per-frame control byte, parallel to the existing
per-frame frequency tables).

Two mechanical notes worth recording:

* **The three voices are identical seven-register blocks**, so a voice is just an
  offset in Y and every SID write in the file is one `sta abs,y`. Adding voices
  2 and 3 cost the code almost nothing — no register block is written out three
  times.
* **`sfxCurCh` exists because both index registers are spoken for** during the
  sweep step: one indexes the sweep tables, the other the voice's registers, and
  the channel index has nowhere else to live for those eight instructions.

One split changed. `sfxRequest` now writes the envelope and **zeroes the control
register**; the waveform, the gate and the opening frequency are `sfxTick`'s, on
the same frame. That zero *is* the falling edge that makes the next frame's
gated write a genuine retrigger, and it means the gate is raised in exactly one
place in the file instead of two that have to agree. Every request in the game is
made before `sfxTick` runs — `gameFrame` calls `weaponTick`, `collisionTick` and
`ebulletPlayerTick` above it — so frame 0 still reaches the chip on the frame the
event happened.

## 4. Priority: removed, and why

**Removed outright, not simplified.** `sfxPri`, `sfxPriTab`, the `SFX_PRI_*`
constants, the accept compare and `sfxRejected` are all gone.

Global priority existed for exactly one reason — three effects competing for one
voice. With a voice per effect the competition does not exist, so a priority byte
would be a rule that can never fire, read by a compare that can never fail, and
a rejection counter that is provably always zero. Keeping it would have been
complexity retained for historical reasons.

**What remains is the arbitration that was always doing the real work: a request
restarts its own voice.** Held fire retriggers the burst on voice 1; two enemies
dying in consecutive frames retrigger the crunch on voice 2; neither can touch
the other's voice at all. Nothing is queued and nothing is refused. No
cross-voice arbitration was built, because the three current effect classes no
longer compete for anything.

`sfxRequests` survives as a single saturating counter — it is how a test, or a
person at the monitor, tells "the hook never fired" from "the hook fired and the
sound was wrong".

## 5. Gameplay hooks: unchanged, and still logical-event based

**No gameplay file was edited in this pass.** The diffstat for the four hook
sites and `main.asm` is byte-for-byte what v1 left:

```
 src/collision.asm | 14 +++++++++++++-
 src/main.asm      | 39 +++++++++++++++++++++++++++++++++++++++
 src/player.asm    | 10 ++++++++++
 src/turrets.asm   | 11 +++++++++++
 src/weapon.asm    |  9 +++++++++
```

All four remain hooked to logical events, not to visual state:

| effect | site | the event |
|---|---|---|
| `SFX_FIRE` | `weaponFire` | a volley actually resolved — not the trigger held, not the muzzle flash lit, not the cadence timer reloading |
| `SFX_KILL` | `applyDamage` | the transition to zero health, **not** the twelve frames of explosion that follow |
| `SFX_KILL` | `turretDamage` | the kill event, **not** the `trtKills` running total |
| `SFX_HURT` | `playerTakeHit` | damage that passed the `plyInvuln` guard, once per hit |

Proven live, not by inspection: over 79 consecutive production frames, requests
== volleys + enemy kills + turret kills + player hits, **exactly** (4 vs 4); and
each hook was caught in the act, identified by the return address its `jsr` left
on the stack — `(FIRE, weapon)`, `(KILL, collision)`, `(HURT, player)`.

## 6. SID registers owned

| registers | who | when |
|---|---|---|
| `$d400-$d406` | voice 1, this file | on a request, and every frame fire is playing |
| `$d407-$d40d` | voice 2, this file | on a request, and every frame a destruction is playing |
| `$d40e-$d414` | voice 3, this file | on a request, and every frame the hurt wail is playing |
| `$d418` volume | **shared, claimed once** | `sfxInit` at boot, value `$0f`. Never written again — a menu music driver that wants to fade the chip takes it over and this file does not change |
| `$d415-$d417` filter | **shared, zeroed once** | `sfxInit` at boot. Not ownership. No effect is filtered and no voice is routed through the filter (`$d417` low bits stay clear), so the boot values are inaudible rather than merely unused |

A voice with nothing playing is written to zero once, when its effect ends, and
then left alone. **Verified on the bus, not from the source:** a store watchpoint
over the whole chip during firing play caught 40 writes and every one landed in
`$d400-$d414` — no filter write, no volume write. A quiet game wrote **nothing at
all** (0 stores over 40 stops / 39 frames).

Pulse-width registers are written by nobody now: no effect selects the pulse
waveform any more, so the duty `sfxInit` zeroed is never read. Noise is never
combined with another waveform — every control byte selects exactly one waveform
bit — which keeps the noise shift register alive on real hardware.

## 7. Reset and silence behaviour

`sfxSilence` loops the channel array and clears **all three** voices'
control registers and both state bytes each. It deliberately does not touch
`$d415-$d418`, so a restart cannot undo master volume or a future menu driver's
filter setup.

* **boot:** `entry` → `sfxInit` — all 25 SID registers to a known value, volume
  up, then falls through to `sfxSilence`.
* **every start, restart, death and return-to-menu:** `gameInit` → `sfxSilence`.

A stuck tone needs three independent failures: every effect has **sustain zero**
(a gate left high on a sustain-zero voice is silent, not a held note);
`sfxChannel` gates off at `len` and clears the control register at `len+1`; and
`sfxSilence` clears all three unconditionally. Proven: `sfxSilence` puts **three
simultaneously playing** effects away in one call, and a 24-frame quiet window
leaves all six state bytes at zero with zero SID traffic.

## 8. Memory — exact, before and after

| | v1 | v1.1 | delta |
|---|---|---|---|
| code + tables | `$1780-$18c7` — **328 bytes** | `$1780-$18e7` — **360 bytes** | **+32** |
| state | `$c600-$c605` — **6 bytes** | `$c600-$c608` — **9 bytes** | **+3** |
| PRG | 51,164 bytes | 51,164 bytes | **0** |

Placement retained exactly. The module stays in the VIC-invisible `$1000-$1fff`
run — the VIC sees the character ROM there, so this RAM costs no sprite block and
no character — between the HUD code ending at `$1768` and the sorter at `$1e00`,
with **1,304 bytes of headroom** left below the sorter. It is resident, CPU-only,
not level-replaceable, and survives the planned boss VIC-bank switch untouched.
State stays in the module-state region of bank 3, between the collision state
ending `$c5fe` and the HUD state at `$c960`, under the module's own `$c610`
assertion ceiling.

**Per-frame cost, counted instruction by instruction** (PAL budget 19,656):

* all three voices idle — the common case — **55 cycles** including the `jsr`
  from `gameFrame` (v1: 12);
* one voice in its sweep, the most expensive phase, **92 cycles**;
* the worst frame this game can currently produce, all three sounding at once,
  **~290 cycles — 1.5% of a frame**.

## 9. The one deliberate sound-design change: player fire

> **AMENDED 2026-09-15, after this report was written.** The three-impact burst
> described below was replaced by **a single heavy ballistic report** before any
> manual listening. The burst synthesised a second rhythm on top of the one
> `WPN_FIRE_PERIOD` already provides, and it made a single trigger tap produce
> three rounds — a gun the player is not holding. **One volley is now one gate
> rise.** The effect is 3 sweep frames + release + finish = **5 frames (~100 ms)**,
> noise struck once and held while its pitch collapses `$2600 → $1900 → $1000`,
> attack 0 into a 72 ms decay, gated for 60 ms. Against a legal volley every 8
> frames that leaves three clear frames of silence. Voice 1 ownership, the other
> two effects, and everything in §§1-8 and 10-12 are unchanged; module code is
> **354 bytes** (`$1780-$18e1`), state still 9 bytes. The focused test's
> `FIRE_SWEEP` constant and one gate-rise assertion were synced to the new
> length but **were not re-run in that pass** — see the note at the end of §11.


v1's fire was a descending pulse chirp — a clean electronic zap, and wrong for
the gun the player can see. The ship fires twin cannon with two muzzle flashes
and a volley every eight frames. **v1.1 replaces it with a three-round autocannon
burst.**

It is **noise, gated three times inside one effect** — not one sound with a
shape, but three separate percussive reports:

```
frame 0   gate high   impact  — 20 ms of noise, struck, not swelled
frame 1   gate low    release — 6 ms, then silence
frame 2   gate high   impact
frame 3   gate low
frame 4   gate high   impact
frame 5   (len)       release
frame 6   (len+1)     the voice is put away
```

* **attack 0 into a 48 ms decay against a 20 ms gate** — each impact strikes at
  full level and is already falling when the gate drops; the 6 ms release
  finishes it, leaving ~14 ms of genuine silence before the next. The impacts
  are separate events to the ear, which is the whole difference between a
  machine gun and a buzz.
* **40 ms between impacts = 25 rounds/second** — heavy autocannon rather than
  small-arms, and the fastest cadence a 50 Hz tick can produce while keeping the
  reports distinct.
* **Dark on purpose:** noise around `$2000`, stepping down `$2400 → $2100 →
  $1e00` across the three so the burst settles instead of repeating one
  identical click. That is an octave and a half below where the destruction
  crunch starts.
* **No explosion tail.** The whole burst is 140 ms — 5 sweep frames + release +
  finish = 7 frames, against `WPN_FIRE_PERIOD` of 8, so held fire leaves a frame
  of silence between volleys and every burst has stopped before the next starts.
* **Retriggers cleanly on voice 1:** a volley fired out of phase restarts from
  impact 1, because `sfxRequest` drops the gate before `sfxChannel` raises it.

The gate pattern was confirmed **on the bus**, as structure rather than as
timbre. Voice 1's control-register stream during live firing play:

```
00  81 80 81 80 81  80  00      00 = voice cleared/falling edge
                                81 = noise gated (an impact)
                                80 = noise, gate dropped
```

**Enemy destruction and player hit/death are unchanged in every number** —
waveform, envelope, sweep and length. Destruction moved from voice 3 to voice 2;
that is a register-offset change and nothing else. The hurt wail did not move at
all.

## 10. Focused proof — simultaneous independent playback

`make test-sfx`, one VICE launch, **ALL PASS**. The overlap proof is the new
part; everything about hooks, cadence, health and bus ownership still runs
through the real production frame loop.

| # | required proof | result |
|---|---|---|
| 1 | init leaves all three voices silent / gate-off | `sfxInit` → all six state bytes zero |
| 2 | player fire activates voice 1 only | `[(1,0), (0,0), (0,0)]` |
| 3 | enemy destruction activates voice 2 only | `[(0,0), (2,0), (0,0)]` |
| 4 | player hit/death activates voice 3 only | `[(0,0), (0,0), (3,0)]` |
| 5 | fire + destruction simultaneously | `[(1,1), (2,0), (0,0)]` — both playing, own frame indices |
| 6 | fire + player hit simultaneously | covered by 7, below |
| 7 | all three simultaneously | `[(1,2), (2,1), (3,0)]` — three effects, three voices, three frame indices |
| 8 | advancing one channel corrupts no other | `[[0..6], [0..7], [0..7]]` — one tick advances every playing channel by exactly one; and on the bus, every control byte on each voice carries that voice's own waveform, so no write crossed between SID blocks |
| 9 | each effect terminates independently | fire ends at frame 7 with the other two still playing → destruction ends at 14 with the wail still going → the wail ends at 32, leaving one single idle state everywhere |
| 10 | restart / game-over leaves gates safely off | `sfxSilence` puts three *playing* effects away at once; a quiet window writes nothing to the chip |
| 11 | gameplay events request each effect exactly once | requests == volleys + kills + turret kills + hits, **4 vs 4**, over 79 consecutive live frames; hooks identified off the stack |
| 12 | short gameplay smoke, catastrophic diagnostics zero | see below |

Effects were started by hand for items 5–9 and then left entirely to the
module's own `sfxTick`; what is driven is the three *events*, and everything the
checks look at afterwards is the tick's unassisted work. Overlap cannot be
*demanded* of a live run — it needs an enemy to die inside a 140 ms burst, which
the encounter director does not guarantee inside any 80-frame window — so the
live run reports its overlap as an observation (`busiest live frame used 1
voice`) rather than as a flaky assertion.

**Nothing here judges whether the sounds are any good.** No test was added to
assess the gunshot's timbre; the gate pattern is checked as structure only.

## 11. Health and smoke

Five seconds of uninterrupted real play with the trigger held, `sfxTick` in the
frame, counters zeroed first:

```
gameOverrun 0   schedBuildDefer 0   scrollLate 0
statPageMismatch 0   statPtrMismatch 0   publishSkip 0
```

All catastrophic diagnostics zero. `publishSkip` came in at **0** against the
ceiling of 8 that v1's paired measurement drew (HEAD baseline under the same
probe: 3/0/0/3/0). `gameSpanMax` is saturated at 255 and `gameSpanOver` 73 —
already saturated on unmodified HEAD under this probe, which is why v1 recorded
them as info rather than asserting them; `gameOverrun`, the counter that actually
says a frame was missed, is zero.

Then the project's default invariant suite, **once**, as the smoke gate:

```
test_boot               ALL PASS
test_production         ALL PASS
test_turret_regression  ALL PASS
test_encounter_director ALL PASS
test_player_ship        ALL PASS
test_level_assets       ALL PASS
test_sfx                ALL PASS
exit code 0
```

**Unrelated failures: none.** `tests/test_production.py`, which carries known
pre-existing sampling flakes around player movement and pool population, passed
on this run; it was not modified, not re-run to characterise it, and not
compared against a scratch checkout.

**The green runs above tested the three-impact burst**, not the single report
that replaced it (see the amendment in §9). The later change is data only —
`sfxLenTab`, three sweep-table slices, one envelope byte and the sweep base
constants — with no change to any routine; it builds clean and the focused
test's constants were synced to it, but the suite was not re-run in that pass
because the change was scoped to sound design pending manual listening.

No baseline-vs-worktree timing campaign, no multi-run statistics, no scratch
checkout, no renderer/mux investigation. The binary the green runs tested is
byte-identical to the one this report describes (`md5 fe1297377769bae0578801e23764a19e`
before and after a documentation-only comment correction).

### Test scope

`tests/test_sfx.py` went **738 → 796 lines (+58, ~8%)**. It was amended, not
rewritten or refactored: the priority section was deleted outright with the
mechanism it tested, a duplicated setup block left over from v1 was removed, the
one-voice assertions became three-voice ones, and the simultaneity section is
the only genuinely new material. One necessary harness fix: every SID write is
now an `absolute,Y` store, so the operand VICE disassembles is *voice 1's*
register and the voice actually written is only recoverable by adding the index
register — reading the operand alone would have reported the whole chip as voice
1.

## 12. VICE hygiene and disk

`pgrep -fl x64sc` **before**: nothing running. **After**: nothing running.

Every launch was `-console`, `+saveres` (never `-default`), launched directly
with no focus theft and no joystick-disable or global-detach overrides. Each run
owned and reaped its exact PID: `20302`, then `20479 / 20506 / 20637 / 20719 /
21167 / 21403 / 21426`. No broad `pkill` was used and no manual VICE session
existed to endanger. No temporary logs or captures were left under `/tmp`; no
per-run build artifacts were created.

```
du -sh build/     84K
du -sh .          5.2M
```

`build/` holds only `shmup.prg`, `main.sym`, `main.vs`.

---

## 13. What to listen for manually

Manual VICE listening is authoritative; this is what the change is asking you to
judge.

1. **The gun, first and mostly.** Tap the trigger: **exactly one report**, heavy
   and ballistic rather than laser-like. Then hold it: the rhythm should come
   from the eight-frame cadence alone, a steady hammering rather than a stutter.
   Listen for whether the report has enough weight (decay, `sfxADTab`) and
   whether its collapse is fast enough to read as a gunshot instead of a small
   explosion (`sfxSweepHi`, three bytes). Both are one-byte changes.
2. **Does it tire?** It is the most frequent sound in the game by an order of
   magnitude. Play a full minute of held fire and see whether it irritates.
3. **The overlap, which is the point of this pass.** Kill an enemy while firing:
   the crunch should ride *over* the gunfire, neither one cutting the other.
   Take a hit while firing: the wail should start under the gun and run its full
   two-thirds of a second without being chopped by your own shots — the failure
   v1 had.
4. **Balance across the three voices.** All three at once is now genuinely
   possible; check the mix does not turn to mush, and whether fire wants to sit
   lower relative to destruction.
5. **Distinctness of the two noise sounds.** Fire and destruction are both noise,
   and both collapse downward. They should not be confusable — the shot is dark,
   dry and 100 ms; the crunch is brighter and 280 ms. This is the pairing most
   likely to need a tweak.
6. **Silence, deliberately.** Stop firing and let the level run: the chip must go
   completely quiet, with no residual hum or held gate on any voice. Then die,
   restart, and confirm nothing is inherited.

## 14. Recommended next gameplay step

**Enemy firing**, as planned. It joins voice 2 with the rest of the world, needs
no architectural change here — one effect id, one table row per table, one
`jsr sfxRequest` at the logical spawn event — and it is the first thing that will
test whether voice 2 wants an arbitration rule of its own once destruction and
enemy fire share it.

Before that, the fire report's numbers should be settled by ear, since it is
cheaper to tune one effect than to tune it against a second one added on top.
