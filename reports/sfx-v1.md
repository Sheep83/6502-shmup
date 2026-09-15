# Minimal SID SFX subsystem — v1

**Date:** 2026-09-15
**Starting HEAD:** `0aff357023403e8d03175290a3ac0abbe6b0e1f6` — *Memory reconfigured for bank switch and multiload*
**Starting working tree:** clean (no uncommitted work existed; nothing was stashed, reset or discarded)
**Final working tree:** six modified files, two new files, **nothing committed and nothing pushed**

```
 M Makefile
 M src/collision.asm
 M src/main.asm
 M src/player.asm
 M src/turrets.asm
 M src/weapon.asm
?? src/sfx.asm
?? tests/test_sfx.py

 Makefile          | 18 ++++++++++++++++++
 src/collision.asm | 14 +++++++++++++-
 src/main.asm      | 39 +++++++++++++++++++++++++++++++++++++++
 src/player.asm    | 10 ++++++++++
 src/turrets.asm   | 11 +++++++++++
 src/weapon.asm    |  9 +++++++++
 6 files changed, 100 insertions(+), 1 deletion(-)
```

---

## 1. Existing SID usage found before implementation

**None whatsoever.** A search of `src/`, `tests/`, `tools/` and the `Makefile`
for `$d4xx`, the decimal forms `54272`/`54296`, and the words *sid*, *sfx*,
*sound* and *audio* returned exactly one hit — the word "sound" inside a
comment in `src/renderer.asm` about a sorted list being *sound*.

So this subsystem started from a genuinely blank chip: no register was owned,
no voice reserved, no init performed, and nothing in the IRQ or raster executor
touched `$d400-$d418`. The raster executor writes `$d011`/`$d016`/`$d018`/
`$d015`/`$d027`+ and the sprite pointer table, and nothing else.

One consequence worth stating: because nothing had ever set `$d418`, the
machine was silent by construction rather than by design, and somebody had to
claim master volume. See §6.

---

## 2. Chosen SID voice, and why

**Voice 3 — `$d40e-$d414`.** The reservation this subsystem establishes:

```
voice 1   $d400-$d406     future music   — untouched by this file
voice 2   $d407-$d40d     future music   — untouched by this file
voice 3   $d40e-$d414     SFX            — this file, and only this file
```

The reason is about music, not about sound effects. Voice 3 is the one the
hardware treats differently: it is the only voice that can be cut from the
output on its own (`$d418` bit 7), and the only voice whose oscillator and
envelope are readable (`$d41b`/`$d41c`). That is exactly why tracker music puts
the parts that matter on voices 1 and 2 and leaves voice 3 for whatever is
left — so giving SFX the odd voice out costs music nothing it wanted.

There is **no mixer, no voice allocator and no stealing**. One effect plays at a
time; `sfxId` is the whole allocator. When music arrives it takes voices 1 and 2
and nothing here changes. Whether a death should later be allowed to borrow a
music voice is deliberately not pre-built.

---

## 3. Module location and exact memory cost

| segment | range | bytes |
|---|---|---|
| `sfx` (code + tables) | `$1780-$18c7` | **328** |
| `sfx state` | `$c600-$c605` | **6** |
| hook code added to five existing modules | — | **29** |
| **total** | | **363** |

Hook cost, measured as the growth of each existing segment against the HEAD
build:

| module | before | after | delta |
|---|---|---|---|
| `player code` | `$4000-$422d` | `$4000-$4232` | +5 |
| `weapon code` | `$4600-$4749` | `$4600-$474e` | +5 |
| `collision` | `$4c00-$4ce5` | `$4c00-$4cea` | +5 |
| `main` | `$5000-$5287` | `$5000-$5290` | +9 |
| `turret code` | `$6f00-$7401` | `$6f00-$7406` | +5 |

**The PRG is byte-for-byte the same size, 51,164 bytes, before and after.** The
image spans `$0801-$cfda` in both builds and the new code lands entirely in
gaps that were already inside it.

### Why these addresses

**Code at `$1780`, inside `$1000-$1fff`.** That run is where the VIC sees the
character ROM, so RAM there is invisible to it and is the established home for
resident CPU-only code — the schedule builder (`$1000-$133f`), the HUD code
(`$1400-$1768`) and the sorter (`$1e00-$1ed6`) already live in it. The module
sits in the free run between the HUD code and the sorter, with **1,336 bytes
still free** above it (`$18c8-$1dff`). The source asserts the ceiling:
`.if (* > $1e00) { .error ... }`.

This respects the architecture the last memory audit set out, rather than
picking a convenient address:

- It is **resident**. Nothing here is level-replaceable, and it is nowhere near
  the level enemy sprite window at `$2c00-$30ff`.
- It costs **no VIC-visible capacity**. `$1000-$1fff` is explicitly recorded as
  "NOT VIC capacity" in the bank-0 map, so a sprite block or character was not
  spent on sound.
- It does **not touch bank 2**. `$8000-$bfff` is the recommended future boss VIC
  bank, and `$9000-$9fff` inside it is already earmarked for relocating clip and
  the raster executor. Nothing was taken from it.
- It **survives the planned bank switch untouched**: `$1000-$1fff` is plain RAM
  to the CPU whichever bank the VIC is looking at.

**State at `$c600`, six bytes.** In the module-state region of bank 3, in the
free run between the collision state that ends at `$c5fe` (whose own assertion
is a `$c600` ceiling) and the HUD state at `$c960`. Outside VIC bank 0, with
every other module's state. Ceiling asserted at `$c610`.

---

## 4. SFX state and API

Six bytes of state. Three routines. That is the entire interface.

```
sfxId        the playing effect, or 0. THIS BYTE IS THE VOICE ALLOCATOR.
sfxPri       its priority, 0 when idle
sfxFrame     the sweep index to play on this frame
sfxAccepted  saturating diagnostic, requests granted
sfxRejected  saturating diagnostic, requests refused on priority
sfxReqId     scratch: the requested id, parked for the length of sfxRequest
```

```
sfxInit      cold start. Called ONCE, from entry. Every one of the SID's 25
             registers to a known value, then master volume, then falls through
             to sfxSilence.
sfxSilence   voice 3 off and nothing playing. VOICE 3 ONLY. Called by gameInit.
sfxRequest   A = effect id. "This happened." X AND Y ARE PRESERVED; A is not.
sfxTick      one frame of sound. Called once per frame from gameFrame.
```

`sfxRequest` preserving X and Y is a deliberate contract, not an accident: every
hook site is in the middle of a loop over a pool slot or a turret index — and
`applyDamage` documents "X = the target, preserved" in its own header — so a
sound request that quietly ate X would be a corruption bug in the system that
made the noise. Twenty-two cycles of push and pull, on an event that happens a
few times a second, buys a two-instruction insertion that cannot break its host.

### Cost

- **Idle frame: 12 cycles** — a load, an untaken branch and a return; 18 counting
  the `jsr`. This is most frames.
- **Playing frame: 54 cycles** — two table reads, two SID stores, one increment.
- Against a PAL budget of 19,656 cycles.

There is no sequencer, no note list, no instrument format, and **no per-object
audio update anywhere in the engine**. A gameplay object cannot own a voice
because there is nothing to own: one byte says what is playing.

### Where sfxTick runs

In `gameFrame`, immediately after `hudDemoTick` and **above** the rebuild/publish
block. Main thread, once per displayed frame — not in the raster IRQ.

Three things make that the right point:

1. Every routine that can request a sound has already run — `weaponTick` for the
   shot, `collisionTick` for an enemy or turret destroyed, `ebulletPlayerTick`
   for the ship being hit — so a sound asked for on this frame is programmed onto
   the SID on this frame rather than the next.
2. It is **above** the publish block deliberately. The schedule is rebuilt only
   when something on screen changed; a frame in which nothing moved must still
   advance a playing effect, so sound cannot sit behind that condition.
3. It is **not** in the raster IRQ. The executor's job is to consume an immutable
   schedule and write VIC registers at fixed rasters. A PAL frame is the
   resolution this subsystem works at anyway, so putting a recurring sequencer
   inside the tightest code in the engine would add a second writer for nothing.

---

## 5. Priority behaviour

One compare:

```
accept when   requested priority >= playing priority
```

| effect | id | priority |
|---|---|---|
| player hit | 3 | highest |
| enemy / turret destroyed | 2 | medium |
| player fire | 1 | lowest |

Priority *is* the id. That is not laziness — the three effects genuinely rank in
the order they were numbered, so a separate table would be a second copy of the
same fact and a chance for the two to disagree. It is still stated as named
constants, because the next effect added may well not rank where its id happens
to fall, and that is where it would be fixed.

**Consequences, all verified:**

- A trivial sound can never cut off an important one.
- An **equal-ranked request retriggers** — which is what makes held fire sound
  like repeated shots, and two enemies dying in one frame sound like the second
  one died.
- **Nothing is queued.** An effect that loses is gone, not deferred. A queue
  would deliver a 140 ms zap *after* the explosion that outranked it, which is
  worse than not hearing it.
- **Deterministic within a frame:** requests are honoured in the order the frame
  makes them, so several in one frame resolve to the highest-ranked, and among
  equals to the last one asked.

---

## 6. SID and global-register ownership

| registers | owner | when written |
|---|---|---|
| `$d40e-$d414` voice 3 | **this file** | every frame an effect is playing, and at no other time |
| `$d418` master volume | **claimed once**, `sfxInit`, at boot | never again |
| `$d400-$d40d` voices 1-2 | not owned | written once, to zero, by `sfxInit` at boot |
| `$d415-$d417` filter | not owned | written once, to zero, by `sfxInit` at boot |

The whole-chip clear at boot is a cold-start "the chip is in a known state"
action, **not** ownership. Power-on SID state is undefined and a previously
running program's state certainly is; an engine that zeroes its VIC idle byte by
construction rather than by luck should not leave the sound chip to chance. A
music driver initialising after `sfxInit` overwrites all of it and nothing here
notices or cares.

Master volume is the one real claim, and it is unavoidable: it is SID-wide and
there is no sound at all without it. A music driver that later wants to fade the
whole chip simply takes `$d418` over; this file does not have to change, because
it never writes it again.

**The 25 registers are cleared once, at boot — never per frame.** During play the
only registers written are the seven belonging to voice 3, and that is proven on
the bus rather than asserted: see §10.

**No filter is used.** Voice 3 is not routed through it, so `$d415-$d417` stay at
the zero `sfxInit` left them at and this subsystem has no opinion about
resonance or cutoff. Music can take the filter without negotiating.

---

## 7. Exact gameplay event hook points

Four sites, each a two-instruction insertion at a genuine one-shot logical event.
None of them is a visual side effect or a diagnostic.

| file | routine | site | effect |
|---|---|---|---|
| `src/weapon.asm` | `weaponFire` | after `sta shotFired` | `SFX_FIRE` |
| `src/collision.asm` | `applyDamage` | the `!death:` arm, after `inc csKills` | `SFX_KILL` |
| `src/turrets.asm` | `turretDamage` | the `!destroy:` arm, after `inc trtKills` | `SFX_KILL` |
| `src/player.asm` | `playerTakeHit` | after `sta plyInvuln` | `SFX_HURT` |

**Why each is once-per-event and not once-per-frame:**

- **Fire.** `weaponFire` is the one point at which a volley is known to have
  actually resolved — not the trigger being held, not the muzzle flash being
  lit, not the cadence timer reloading. A shot refused by the cooldown or the
  overheat lockout branches to `!refuse` above the hook and is silent, which
  makes the lockout audible as well as visible.
- **Enemy destruction.** The `!death:` arm is reached only on the transition to
  zero health, and `lda objHP,x / beq !done+` at the top of `applyDamage` refuses
  to re-enter it. The twelve frames of explosion that follow are silent.
  Requesting from `enemyDeathTick`, where the explosion visibly runs, would have
  restarted the sound on every one of those frames.
- **Turret destruction** gets the *same* effect as a flying enemy, deliberately:
  a turret is a thing the player shoots and destroys, and a fourth sound earned
  by nothing but a different file owning its health would be noise. It is hooked
  at the `!destroy:` arm rather than by watching `trtKills`, which is a running
  total this file never clears — watching a total for a change is how a
  once-per-event sound becomes a once-per-frame one.
- **Player hit.** `playerTakeHit` is already the single point at which damage
  means anything, and the `plyInvuln` guard three lines above the hook — which
  exists for the collision rule, not for the sound — means the next hundred
  frames of blinking, and every projectile that passes through the ship during
  them, reach `!done` and make no sound. One hit, one wail.

`src/sfx.asm` is imported **first** in `src/main.asm`: the `SFX_*` ids are
constants, four files name them, and KickAssembler resolves constants strictly in
import order. It imports nothing itself and depends on no other module.

---

## 8. The three effects

Each is five numbers and a frequency sweep. There is no instrument format and
deliberately no way to author a fourth effect without editing the file.

**Every effect has sustain zero**, so its envelope falls to silence by itself and
its *decay*, not the frame count, is what the ear hears as the length. Sweep
lengths are chosen to run out at about the same time as the decay.

Sweep values are PAL SID register units: `register = Hz × 16777216 / 985248`,
i.e. `Hz × 17.028`. NTSC would want a different table; this game is PAL.

### Player fire — a pulse zap, 5 sweep frames, ~140 ms

| | |
|---|---|
| waveform | pulse, 12.5% duty (`$d411 = $08`, low byte permanently 0) |
| ADSR | attack 0 (2 ms), decay 4 (114 ms), sustain 0, release 0 (6 ms) |
| sweep | 3800 → 2900 → 2100 → 1450 → 1000 Hz |
| total | 5 + 2 = 7 frames |

Thin and electronic rather than round, and the opposite of weighty on purpose.
3800 Hz down to 1000 Hz in five frames is the shortest gesture that still reads
as a shot rather than a click.

**The cadence is the constraint.** `WPN_FIRE_PERIOD` is 8 frames, so held fire
asks for this 6.25 times a second; 7 frames of effect leaves a frame of silence
between shots rather than a continuous tone, and a 114 ms decay under a 100 ms
sweep means each zap has genuinely stopped before the next starts. This is the
effect most likely to become irritating and it is deliberately the one with the
least in it.

### Enemy / turret destruction — a noise burst, 12 sweep frames, ~280 ms

| | |
|---|---|
| waveform | noise |
| ADSR | attack 0, decay 7 (240 ms), sustain 0, release 0 |
| sweep | `$4200` down to `$0600`, twelve steps |
| total | 12 + 2 = 14 frames |

Noise rather than a waveform is the single biggest timbral step away from the
fire zap this chip offers: no pitch, just a band of hiss whose brightness falls
as the value drops. Swept from bright down to a low rumble it is a crunch that
collapses — about twice the length and weight of a shot. The sweep is written as
raw register values rather than frequencies because noise has no pitch; the
number sets how fast the shift register is clocked, which the ear hears as
brightness.

### Player hit — a sawtooth wail, 30 sweep frames, ~640 ms

| | |
|---|---|
| waveform | sawtooth |
| ADSR | attack 0, decay 9 (750 ms), sustain 0, release 0 |
| sweep | 600 Hz down to 64 Hz, thirty steps |
| total | 30 + 2 = 32 frames |

The one sound that is neither noise nor pulse, because being obviously different
from an enemy exploding matters more than anything else about it. A sawtooth
falling three and a half octaves into a buzz over six-tenths of a second, under a
750 ms decay, is the ship's systems dying. It is the longest sound in the game by
a factor of two and there is nothing else in the mix it can be confused with. It
cannot stack: `plyInvuln` refuses a second hit for 100 frames, three times this
effect's length.

### The trigger sequence, and why the gate falls first

On every accepted request: ADSR, pulse width, then the **opening frequency**, then
`control & ~GATE`, then `control`. Two details are load-bearing:

- The oscillator is put on the effect's opening pitch **before** the gate opens.
  The other way round, the attack would begin on whatever frequency the previous
  effect ended on — audible as a wrong-pitched click in front of every sound.
- **Gate low, then high.** The envelope generator retriggers on the *rising edge*
  of the gate bit and on nothing else, so writing a control byte with the gate
  already set would leave a still-decaying effect decaying: the new sound would
  inherit the old envelope and fade out instead of striking.

---

## 9. Game-state reset and silence behaviour

The current flow has **no menu and no game over**: `entry` → `gameInit` →
`mainLoop` forever. So the behaviour was chosen for the flow that will exist, not
just the one that does.

- `jsr sfxInit` in **`entry`**, beside the other one-time hardware init. Whole
  chip to a known state, master volume up, voice 3 silent, counters zero.
- `jsr sfxSilence` in **`gameInit`** — the routine any future restart, death or
  return-to-menu will re-enter gameplay through. Whatever was playing when the
  last session ended is gated off and forgotten, so no start can inherit a sound.

The split matters and is not decoration: `sfxSilence` is **voice 3 only**. Once
music exists, a restart must not wipe the music driver's registers, and the day
that matters is not the day anyone will remember this routine.

### Why a stuck tone is not possible

Three independent things would each have to fail:

1. **Every effect has sustain zero.** The envelope decays to silence on its own,
   whatever the rest of the file does. A gate left high on a sustain-zero voice
   is silent, not a held note. This is the property that makes the subsystem
   *safe* rather than merely careful.
2. `sfxTick` gates the voice off at the end of every effect and clears the
   control register outright on the frame after that.
3. `sfxSilence` clears the voice unconditionally and `gameInit` calls it.

---

## 10. Focused proof — `tests/test_sfx.py`, **ALL PASS**

One VICE launch, no fixtures, no engine qualification replayed. Run **three
consecutive times, green every time**, ~112 s per run.

A note on how the proof is built, because the obvious instrument turned out to be
a liar. The plan was to read voice 3's envelope at `$d41c` — the one register the
hardware exposes. **On this VICE build it reads zero whatever the voice is doing,
with sound enabled and disabled, with a dummy sound device and a real one.** That
was measured before anything was built on it. What replaced it is a **store
watchpoint over the whole chip**: at each stop the instruction that just executed
and the register file are both in the reply, so the target address and the byte
that went out on the bus are directly observable. That is a stronger instrument
than the one originally wanted, and it watches all 25 registers rather than one.

Ordering inside the file is load-bearing and documented there: the health gate
runs **first, on a pristine machine**, because `harness.call()` hijacks the PC and
stack pointer mid-`gameFrame` and a watchpoint halts the CPU dozens of times.
Everything that abuses the machine comes last.

### Results

**Memory — static, from the build's own symbols**
```
ok  sfx code is inside the VIC-invisible $1000-$1fff run -- $1780-$1899
ok  ...starting where the source says, clear of the HUD code below -- $1780 vs $1768
ok  ...and clear of the sorter above -- $1899
ok  sfx code costs no VIC-visible capacity and no level-replaceable space
ok  sfx state is in the module-state region, outside VIC bank 0 -- $c600
ok  ...clear of the collision state below and the HUD state above -- $c600-$c605
ok  sfx state is six bytes -- 6
```

**Health — five seconds of uninterrupted play with the trigger held**
```
ok  the health run really ran, non-stop, with the trigger held
ok  gameOverrun is zero with sfxTick in the frame -- 0
ok  schedBuildDefer is zero with sfxTick in the frame -- 0
ok  scrollLate is zero with sfxTick in the frame -- 0
ok  statPageMismatch is zero with sfxTick in the frame -- 0
ok  statPtrMismatch is zero with sfxTick in the frame -- 0
ok  publishSkip stays inside the envelope HEAD itself occupies -- 0, ceiling 8
ok  the subsystem was busy throughout the health run -- sfxAccepted 255
```

**The real frame loop — 80 stepped production frames**
```
ok  stepped 80 distinct production frames
ok  the fire effect really plays during ordinary held fire
ok  ...and the voice is genuinely released between shots
ok  the sampled frames were overwhelmingly consecutive -- 79 adjacent pairs, 0 gaps
ok  plyHits did not saturate, so its delta is a real count
ok  requests == volleys + enemy kills + turret kills + player hits, EXACTLY
ok  the run actually fired
ok  no fire effect outlives its own cadence -- longest run 6 frames, budget 7,
    weapon period 8
```

The accounting identity is the *once-per-logical-event* proof. Every request is
counted in exactly one of `sfxAccepted`/`sfxRejected`, so their sum is the number
of times gameplay asked for a sound; it is compared against the number of logical
events the game itself reported. The alignment is exact rather than tolerated:
counters read at the top of frame *k* describe events through frame *k-1*, and
`shotFired` read there is the volley of frame *k-1*, so for any two consecutive
samples both sides describe the same single frame. Non-adjacent pairs are dropped
from both sides rather than fudged. **If the kill sound retriggered across the
twelve frames of explosion, or the hurt sound across the hundred frames of
invulnerability, this equation would not balance.**

**Provenance — who asked for what, read off the stack**
```
ok  ordinary play is a stream of requests, and fire dominates it
ok  the FIRE effect is requested by the weapon, on a resolved volley
ok  the KILL effect is requested when something is destroyed
ok  the HURT effect is requested by the player, on taking damage
ok  every identified request is a legal (effect, module) pair
    -- [(1, 'weapon'), (2, 'collision'), (3, 'player')]
```

A breakpoint on `sfxRequest` itself: A still holds the effect id the caller
passed, and the two bytes on top of the stack are the return address the `jsr`
left, which identifies the calling module by segment. Not "a counter moved" —
*this module asked for that sound while the game was running its own code*. An
earlier run also caught `(2, 'turrets')` from `turretDamage`.

Kills and hits are *arranged, not faked*. A kill sets an already-alive enemy's
health to exactly what one cannon takes off, moves the ship into its column and
cools the gun; a hit launches one projectile from the game's own `ebulletSpawn`
just above the ship. Everything after that is production code — `weaponTick`
resolves the volley, `traceRay` picks the target, `applyDamage` and
`ebulletPlayerTick` do the rest inside the real frame loop. Waiting for these
events instead was tried and rejected: a VICE checkpoint suppresses warp, so a
wait covers a few hundred frames per attempt against a hit rate of roughly one in
five hundred, and the gate failed about half the time.

**Quiet — no stuck gate, no traffic**
```
ok  the voice goes idle once the trigger is released
ok  ...and idle is ONE state: nothing playing, no priority, frame index reset
ok  no request arrives during a quiet window
ok  the machine really ran during the silent-traffic window -- 40 stops
ok  a quiet game writes NOTHING to the SID -- no per-frame traffic, no held gate
```

**SID ownership, on the bus**
```
ok  a firing game really does write the SID -- 40 stores read
ok  every store the watchpoint caught was readable -- 0 unreadable stops
ok  every SID write during play lands in voice 3 ($d40e-$d414), so voices 1
    and 2, the filter and $d418 are untouched by play -- strays: []
ok  every control byte written is a legal waveform/gate combination
ok  the gate is dropped before it is raised, on every trigger
ok  ...and the voice was triggered more than once in the window
```

**API, priority and termination**
```
ok  sfxInit leaves nothing playing and the counters cleared
ok  a request starts the effect it asked for
ok  sfxSilence puts a PLAYING effect away, not just an idle one
ok  fire cannot take the voice from a playing hurt
ok  ...and neither can a kill
ok  both refusals were counted
ok  a kill DOES take the voice from a playing fire
ok  ...and a hurt takes it from a playing kill
ok  an EQUAL-ranked request retriggers from the start
ok  the frame index advances by exactly one per tick -- [0,1,2,3,4,5,6]
ok  the fire effect occupies its sweep plus a release and a finish -- 7 vs 7
ok  ...and then ends, leaving one single idle state -- (0, 0, 0)
ok  a tick on an idle voice changes nothing
```

### What this proof does not prove

Whether the sounds are any good. Nothing in Python can hear. The frequencies,
envelopes and lengths are a first pass and manual VICE listening is the only
authority on them.

### Proportionality, stated honestly

`tests/test_sfx.py` is 738 lines, of which 414 are statements — comparable to the
largest existing test in the repo (`test_player_ship.py`, 384 statements) and the
rest is the prose density this codebase uses everywhere. It maps one-to-one onto
the proof list the task asked for, with no fixture system and no generated
content. It is wired into `make test` as `test-sfx`, and has its own
`make test-sfx` target, because what it guards is a hook in production code that
a future change could silently unwire — the same reason the turret regression
lives in the default gate.

---

## 11. Smoke gate and timing

`make test` — the repository's everyday gate — was run once after the change.
**All six pre-existing suites passed** against this exact binary:

```
test_boot.py               ALL PASS
test_production.py         ALL PASS
test_turret_regression.py  ALL PASS
test_encounter_director.py ALL PASS
test_player_ship.py        ALL PASS
test_level_assets.py       ALL PASS
```

The binary has not changed since that run: the only subsequent edits were to
`tests/test_sfx.py` and to comments in `src/sfx.asm`, and the segment map is
byte-identical.

### The one number that needed a real measurement

The first draft of the health gate asserted `publishSkip == 0` and
`gameSpanOver == 0`, and both tripped. Rather than assume either way, the HEAD
binary was rebuilt into a scratch directory (`git archive HEAD` — **the working
tree was never touched, reset or stashed**) and an identical probe was run
against both: boot, zero the counters, hold fire, free-run five seconds
undisturbed, read.

| metric | HEAD (unmodified) | with sfxTick |
|---|---|---|
| `gameOverrun` | 0, 0, 0, 0, 0 | 0, 0, 0, 0, 0 |
| `scrollLate` | 0, 0, 0, 0, 0 | 0, 0, 0, 0, 0 |
| `publishSkip` | **3, 0, 0, 3, 0** | 0, 0, 0, 3, 0 |
| `gameSpanOver` | 68, 104, 92 | 111, 100, 105 |
| `gameSpanMax` | 255 (saturated) | 255 (saturated) |

**Conclusion: no frame or schedule regression.** `publishSkip` under sustained
held fire — heavier frames than any other test in the suite runs — comes up
non-zero intermittently on the *unmodified* binary at an indistinguishable rate,
and `gameSpanOver`/`gameSpanMax` are already saturated on HEAD with the two
spreads fully overlapping. `gameOverrun`, the counter that actually says whether
a frame was missed, is zero in all ten runs.

The gate reflects that measurement rather than papering over it: the five
reliably-zero counters are asserted at zero, and `publishSkip` is checked against
the envelope HEAD itself occupies (ceiling 8) with the baseline numbers recorded
next to the constant. A main thread genuinely pushed over the edge by a new
per-frame cost would not produce three of these in five warped seconds; it would
produce hundreds, and would take `gameOverrun` with it.

Which is the expected result for 12 idle / 54 active cycles against 19,656.

### Unrelated or pre-existing failures

**None encountered.** The known `test_production.py` sampling flakes did not
fire; `test_production.py` was not modified, and neither was any other existing
test.

The `gameSpanOver` / `gameSpanMax` saturation documented above **is** a
pre-existing engine characteristic, clearly labelled as such. It was measured
because this task needed to rule it out, and it was not investigated further —
the task is sound, not the frame budget.

---

## 12. VICE hygiene

- `pgrep -fl x64sc` was checked before and after every automated run.
- Every launch used `-console`, retained `+saveres`, and **never** `-default`.
- No joystick-detach or global-disable overrides; no window was ever mapped, so
  no focus was stolen.
- Ownership was by exact PID via the harness's `try/finally`; **no broad `pkill`
  was ever issued** and no manually launched VICE existed to endanger.
- One background run had to be interrupted mid-suite; its VICE was confirmed
  reaped immediately afterwards (`no x64sc`).

**Final state: `no x64sc running`.**

Transient captures, probe scripts and the scratch HEAD build all live under
`/private/tmp/.../scratchpad`, outside the repository. No per-run build
directories were created; `build/` holds only the current binary and symbols.

```
du -sh build/     84K
du -sh .          5.1M
```

---

## 13. What to listen for in manual VICE

`make run` (sound is on by default there; the automated suites disable it).

1. **Fire.** A short, thin, high zap that falls fast. Held fire is 6.25 a second
   with a frame of silence between — listen for whether it stays a *tick-tick-
   tick* or starts to smear into a drone. This is the one most likely to need
   tuning; if it is annoying, the decay (`sfxADTab` entry 1, currently `$04` =
   114 ms) is the first knob, then the 12.5% duty in `sfxPWHiTab`.
2. **Destruction.** Noticeably heavier and about twice as long as a shot — a
   noise crunch that collapses downward. It should land as an event, not a tick.
   If it feels thin against the fire zap, the decay (`$07` = 240 ms) is the knob.
3. **Player hit.** Unmistakable: a sawtooth wail dropping three and a half
   octaves over six-tenths of a second. It must never be confusable with an
   explosion. If it is too long in play, shorten the sweep (`sfxLenTab` entry 3,
   currently 30) before touching the decay.
4. **Priority in action.** Fire into a group and take a hit at the same moment —
   the wail should win outright and the fire zaps should simply not be heard for
   its duration. Firing while an explosion is running should also lose.
5. **The overheat lockout is now audible.** Hold fire until the gauge locks: the
   sound stops dead along with the shots. That is the hook sitting on the real
   volley event rather than on the trigger, and it is worth confirming it feels
   right rather than broken.
6. **Silence when idle.** Stop firing, stay untouched: the chip should go
   completely quiet with no residual hum, buzz or clicking.

---

## 14. Recommended next gameplay step

**Scoring and lives** — the systems the combat code has already been leaving hooks
for, and the cheapest way to turn existing feedback into consequence.

Everything needed is already published and unconsumed: `csKills` and `csKillType`
carry the enemy kill event and its type, `trtKills` counts turret kills, and
`plyHits` is documented as "the hook a lives system would read". The HUD already
draws score, lives and an upgrade slot from `hudDemoTick`, which is stated in
`gameFrame` to be demo values because "their systems do not exist yet". So the
work is connecting three counters to three HUD fields plus a game-over
transition — and that transition is exactly the path `sfxSilence` was put into
`gameInit` for, which would make this the change that proves the reset behaviour
in production rather than only in a test.

Music is the obvious alternative and deliberately *not* the recommendation yet.
The architecture for it is now open and documented — voices 1 and 2 free, the
filter untouched, `$d418` a one-line handover — but a game with sound and no
stakes is a worse demo than a game with stakes and three sounds.
