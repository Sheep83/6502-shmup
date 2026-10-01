# Dropper Escort/Substitution Architecture Audit

**Task:** 19656 — Dropper Escort/Substitution Architecture Audit
**Scope:** read-only architecture audit. No redesign implemented.
**Tree:** `main`, HEAD `1a07c82 More test cleanups`, clean at start and at finish.

---

## Executive summary

The observed behaviour is real, and the mechanism is not what it looks like.

**There is no "designate one member as the Dropper" logic anywhere in the
engine.** A Dropper Trigger authors a wave whose *every* member is a Dropper.
What produces "1 Dropper + N−1 escorts" is the **one-live-Dropper rule**
combined with the order members are sent: the first member to spawn claims
`tkDropperLive`, and every later member of the same wave finds the flag already
set, is *refused*, and is substituted with the level's ordinary identity.

The substitution is therefore a **side effect of a safety interlock**, not a
feature. Nobody wrote "member 0 is the Dropper"; member 0 is simply first.

Five consequences follow, and all five are measured below:

1. **Total spawned always equals the Wave Definition's member count.** Nothing
   is added or dropped — a 6-member wave sends 6 objects, a 1-member wave sends 1
   and has no escort at all.
2. **The Dropper is always member index 0**, regardless of side, speed or count.
3. **Escorts are not the authored species.** They are `lvlPlainRow` — a single
   level-wide identity — so escorts cannot vary, and they are not "the species
   the author chose minus its Dropper behaviour".
4. **The Dropper consumes formation slot 0 and fire-mask bit 0, and wastes both.**
   Its authored position is overwritten by `dropperLaunch`, leaving a gap in the
   formation; its fire permission is withdrawn after the mask has already been
   evaluated, so bit 0 of a Dropper wave's mask is inert. Nothing warns.
5. **Trigger speed reaches the Dropper's object and is then ignored.** `wmSpeed`
   is written correctly and `dropperFly` never consults it.

The coupling between Dropper and escorts after spawn is **loose but real, and it
is not the substitution**: escorts are ordinary independent enemies until the
Dropper dies, at which point `tokenAssignRoles` conscripts *every* live enemy —
escorts included, but equally anything from any other trigger — into the
protector ring or dismisses it. So the "escort" relationship is emergent from
proximity in time, not from the wave they shared.

This is **spawn-time substitution plus a shared-liveness interlock**, not a
deeply coupled subsystem. `src/dropper.asm` is 389 well-documented lines that
own four module bytes and one weave table, and they touch nothing else. That is
the good news for the redesign: the seam is narrow.

**Recommendation: Option A**, with one refinement — give the Dropper its own
Movement Program reference on the Trigger, and fix the member-0 substitution to
be an explicit choice rather than a race. Details in *Recommended architecture*.

---

## Trigger and export representation

### Editor / project schema

`tools/level_editor/project_v6.py:254` — `Trigger` carries, per authored moment:

| Field | Type | Dropper relevance |
|---|---|---|
| `world_progress` | int, 16-bit | when the wave arms |
| `wave_definition` | str (id) | the wave **both** Dropper and escorts reference |
| `species` | str (roster identity) | `"DROPPER"` selects Dropper behaviour |
| `fire_mask` | list of member indices | bit 0 is the Dropper's, and is inert |
| `dropper_side` | `"LEFT"` / `"RIGHT"` | read **only** for a Dropper wave |
| `colour`, `colour_mode` | int / str | applied to Dropper and escorts alike |
| `fire_mode` | str | applied at spawn; withdrawn from the Dropper |
| `speed` | int 4..8 | reaches the Dropper's object and is ignored |

### Identity, detection and behaviour

Behaviour belongs to the **identity**, not to a slot — `tools/sprite_export/import_spd.py:207-208`:

```python
BEHAVIOUR_PLAIN = 0
BEHAVIOUR_DROPPER = 1
```

`import_spd.py:239-241` — exactly one roster entry carries it today:

```python
Roster("DROPPER", "Dropper", tuple(range(0x1E, 0x22)),
       shape=(0, 1, 2, 3, 3, 2, 1, 0),       # out and back
       behaviour=BEHAVIOUR_DROPPER),         # the token carrier
```

`import_spd.py:434-437` derives the two package bytes from the level's chosen
identities:

```python
drop = next((i * ENEMY_ANIM_STEPS for i, (r, _) in enumerate(layout)
             if r.behaviour == BEHAVIOUR_DROPPER), 0xFF)
plain = next((i * ENEMY_ANIM_STEPS for i, (r, _) in enumerate(layout)
              if r.behaviour == BEHAVIOUR_PLAIN), 0)
```

For Level 1 (`src/level1/stage_enemies.asm`):

```asm
.const LVL_DROP_ROW  = $08   // DROPPER slot carries the token
.const LVL_PLAIN_ROW = $00   // RING slot, ordinary behaviour
```

### Package and runtime

`src/levelpkg.asm:305-306` places them at `$ffab` / `$ffac`;
`src/level_assets.asm:126-128` copies them into engine RAM at level load:

```asm
lda LEVELPKG_DROPROW
sta lvlDropRow
lda LEVELPKG_PLAINROW
sta lvlPlainRow
```

**Every Dropper test in the engine is one `cmp lvlDropRow`.** There are exactly
four, and that is the whole of Dropper detection at runtime:

| Site | Purpose |
|---|---|
| `src/waves.asm:1308` | claim or substitute at spawn |
| `src/waves.asm:1461` | take the claimed one off its authored path |
| `src/enemy.asm:596` | route it to `dropperFly` instead of `wmTick` |
| `src/enemy.asm:810` | drop the token on destruction |
| `src/enemy.asm:858` | release liveness on **any** despawn |

`$ff` can never equal a species row, so a level that chooses no Dropper identity
makes all five tests fail and the mechanism goes dormant with no branch of its
own. That part of the design is clean.

### The generated trigger columns

`src/level1/wave_encounters.asm` — nine parallel columns, one entry per trigger.
Level 1 as committed:

| # | row | def | species | side | fire | colour | mode | speed | wave count |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 40 | 6 `up_n_over` | **8 DROPPER** | LEFT | `%111111` | 1 | AIMED | 1.00× | **6** |
| 1 | 90 | 3 `loop` | 0 RING_3 | LEFT | `%111` | RANDOM 1 | AIMED | 1.50× | 3 |
| 2 | 140 | 3 `loop` | 16 SPACE_WHISK | LEFT | `%111` | 1 | AIMED | 2.00× | 3 |
| 3 | 200 | 5 `dive_4` | 0 RING_3 | LEFT | `%1111` | 1 | AIMED | 1.25× | 4 |
| 4 | 240 | 1 `s` | **8 DROPPER** | LEFT | `%111` | 1 | AIMED | 1.25× | **3** |

Trigger 0 with 6 members and trigger 4 with 3 members are exactly the two cases
reported from play: **1 + 5** and **1 + 2**.

---

## Runtime substitution flow

### Latching, per wave instance

`waveStartNext` (`src/waves.asm:915`) copies the trigger's columns onto a **wave
instance**, because the cursor has moved on by the time the members go out:

```asm
lda waveTrigSpecies,y
sta wvSpecies,x          ; ...and Def, Fire, Side, Speed, FireMode, Colour
```

`src/waves.asm:529-570` — every one of these is **per instance, one value for the
whole wave**. There is no per-member species, and that is the root of the whole
behaviour: `wvSpecies` says "this wave is made of Droppers", full stop.

### The substitution, at the one instruction that commits a species

`src/waves.asm:1293-1320`:

```asm
    ldy wvInst
    lda wvSpecies,y          ; the authored species -- DROPPER for every member
    cmp lvlDropRow
    bne !species+
    ldy tkDropperLive
    beq !claim+
    lda lvlPlainRow          ; ONE IS ALREADY OUT THERE -> substitute
    jmp !species+
!claim:
    ldy #1
    sty tkDropperLive        ; this one is now THE Dropper
!species:
    sta enySpecies,x
```

In plain English, per member, in spawn order:

> Is this wave made of Droppers? If a Dropper is already alive, this member
> becomes the level's ordinary identity instead. Otherwise this member *is* the
> Dropper, and claims the flag.

Member 0 finds the flag clear and claims. Members 1..N−1 find it set — **set by
their own sibling, moments earlier** — and are substituted. The file's own
comment frames this as a refusal ("*A REFUSED DROPPER STILL FLIES*"), which is
precisely right for its original purpose of guarding against two *triggers*
overlapping; that it also produces the escort formation is unintended.

### Then, and only then, the claimed one is taken off its path

`src/waves.asm:1448-1466`, after `wmEnterStage` has already armed the member like
any other:

```asm
    lda enySpecies,x
    cmp lvlDropRow
    bne !ordinary+
    ldy wvInst
    lda wvSide,y
    jsr dropperLaunch        ; X preserved
!ordinary:
```

The ordering is deliberate and load-bearing: `wmEnterStage` writes `wmMode`,
`wmVX`, `wmVY` and `wmTimer`, so installing the flight before it would be
overwritten. The object is a complete wave member right up to the instant it
becomes a complete Dropper.

### Measured

Probe A, a synthetic 4-member Dropper wave (`start_x=100`, `x_step=30`,
straight leg `vx=6`):

```
inst member species          fire role spd   x   y  vx vy mode
   1      0   8 DROPPER     0    0   4   0  88  12  0    0
   1      1   0 plain       1    0   4 130  60   6  0    0
   1      2   0 plain       1    0   4 160  60   6  0    0
   1      3   0 plain       1    0   4 190  60   6  0    0
=> 4 spawned, 1 Dropper(s); Dropper member index(es) [0]
```

Note `x = 130` for member 1: the formation's slot 0 at `x = 100` is **gone**,
because `dropperLaunch` overwrote it with the entry edge. The escort formation
has a hole where its first member should be.

---

## Dropper member selection

**Member index 0, always.** Proven four ways:

| Case | Result |
|---|---|
| 4-member wave, side LEFT | Dropper member index `[0]` |
| side RIGHT (every trigger repointed) | Dropper member index `[0]`; only entry X and direction changed — `x=343, vx=-12` instead of `x=0, vx=+12` |
| 1-member wave | `1 spawned, 1 Dropper, 0 escorts` |
| speed 2.00× | Dropper member index `[0]` |

**Side does not change the choice.** It changes only `logX` and the sign of
`wmVX`, inside `dropperLaunch` (`src/dropper.asm:234-251`).

**Why member 0 and not, say, the middle:** nothing chooses it. `wvIndex` walks
0,1,2… and the first arrival wins a flag. `wvIndex` is incremented *after*
`waveSpawnMember` returns (`src/waves.asm:1043`, label `!sent:`), which is how
the member index can be read at the spawn breakpoint at all.

> **Diagnostic correction.** My first probe printed the member index as
> `wvIndex - 1`, on the assumption the increment happened inside the spawn. It
> does not, so member 0 printed as `-1` and one activation for trigger 0 fell
> outside the sample budget, briefly making it look as though trigger 0 produced
> no Dropper. Re-reading `!sent:` fixed the calculation; probe 2 onward reads
> `wvIndex` directly and the answer is unambiguous.

---

## Escort identity source

**Escorts are `lvlPlainRow`** — the level's single ordinary identity — and **not**
the authored trigger species.

Measured by repointing the engine's own byte:

| `lvlPlainRow` | Member 0 | Members 1..3 |
|---|---|---|
| `$00` (as authored) | row 8 DROPPER | row **0** |
| `$10` | row 8 DROPPER | row **16** |
| `$08` (= `lvlDropRow`) | row 8 DROPPER | row **8 — four Droppers** |

> **A second diagnostic correction, and it matters.** The first attempt poked the
> *package* byte `$ffac` and reported escorts unchanged at row 0 while printing
> `lvlPlainRow=$10` — the value it had just written. `src/level_assets.asm:126`
> copies the package byte into engine RAM at level load, so poking the package
> after the level is resident changes nothing. The instrument was reading one
> byte and the engine another. Poking `sym["lvlPlainRow"]` gives the table above.

**Escorts cannot vary in identity.** There is one `lvlPlainRow` per level, and no
per-member authored field exists to vary it. Whatever identity occupies the
level's first `BEHAVIOUR_PLAIN` slot is what every escort of every Dropper wave
wears — and it is also what `tokenReinforce` spawns as a replacement guard
(`src/token.asm:731`).

### The last row is a latent structural fragility, not a live bug

Forcing `lvlPlainRow == lvlDropRow` produced **four Droppers at identical
positions**, all flying `dropperFly` off the same four module bytes
(`drPassLeft`, `drPhase`, `drHold`, `drPing` — `src/dropper.asm:132-136`). They
would share one pass counter and one weave phase.

The exporter cannot produce this today: `import_spd.py:434-437` derives `drop`
from the single `BEHAVIOUR_DROPPER` entry and `plain` from the first
`BEHAVIOUR_PLAIN` entry, and no roster entry is both. But the *engine* does not
check it — the substitution writes `lvlPlainRow` without asking whether that is
also the Dropper row. It shows exactly how thin the one-live-Dropper invariant
is: the flight state is module-scoped precisely *because* the rule guarantees one
Dropper, and the rule is enforced in one place with no assertion behind it.

---

## Side and fire-mask semantics

### Side

- Authored per Trigger, `LEFT`/`RIGHT`; constants in `src/encounter_format.asm`.
- Read **only** at `src/waves.asm:1464`, passed to `dropperLaunch` in A.
- Consumed at `src/dropper.asm:234-251`: selects `DROP_ENTRY_LEFT = 0` /
  `DROP_ENTRY_RIGHT = 343` and the sign of `DROP_VX`.
- Escorts never see it. `validation_v6.py:720-723` warns `trigger.side_ignored`
  when a non-Dropper trigger carries a non-`LEFT` side — correctly, and using
  `identity_behaviour`, not a name comparison.

### Fire mask — the Dropper occupies bit 0 and wastes it

`src/waves.asm:1324-1374` resolves firing for the member being spawned, *then*
`dropperLaunch` (`src/dropper.asm:230-231`) withdraws it:

```asm
    lda #ENEMY_FIRE_NONE
    sta enyFire,x
```

Measured, 4-member Dropper wave:

| Authored mask | Dropper `enyFire` | Escort `enyFire` (members 1..3) |
|---|---|---|
| `%1111` | 0 | 1, 1, 1 |
| `%0001` | 0 | **0, 0, 0 — nothing in the wave fires at all** |
| `%1110` | 0 | 1, 1, 1 |

So bit 0 of a Dropper wave's fire mask is **dead data**. Level 1 trigger 0
authors `%111111` on a six-member wave; only five of those six bits do anything.

Nothing tells the author. `src/waves.asm:450` checks the mask against the member
count; `validation_v6.py:679-693` checks range and member existence. Neither
knows bit 0 is unreachable on a Dropper wave. **This is the single cheapest
improvement available today** — a validator warning, no runtime change.

---

## Wave Definition ownership matrix

Which authored property actually affects which enemy:

| Wave Definition property | Dropper | Escorts | Notes |
|---|---|---|---|
| **member count** (byte 0) | ◑ counts it | ✅ | Total spawned = count. The Dropper consumes one slot of it. Count 1 ⇒ no escorts. |
| **spawn interval** (byte 1) | ✅ | ✅ | The Dropper is sent on the interval like any member; it is member 0, so it is first. |
| **startX / startY** (2,3,4) | ❌ overwritten | ✅ | `dropperLaunch` writes `logX` = entry edge, `logY` = `DROP_CENTRE_Y`. |
| **xStep / yStep** (5,6) | ❌ overwritten | ✅ | Applied to the Dropper, then discarded — the formation keeps a hole at slot 0. |
| **launch heading** (byte 8) | ❌ | ✅ | Written to `wmPhase` then irrelevant: `dropperFly` never reads `wmPhase`. |
| **Movement Program** (byte 9) | ❌ | ✅ | Written to `wmStage`, armed by `wmEnterStage`, then overwritten by `dropperLaunch`. |
| **movement legs** (STRAIGHT/HOLD) | ❌ | ✅ | |
| **arcs / turn data** | ❌ | ✅ | |
| **wave duration / final direction** | ❌ | ✅ | `WM_EXIT` inheritance is escort-only. The Dropper's exit is `drPassLeft` reaching 0. |
| **Trigger speed** | ❌ *copied and ignored* | ✅ | `wmSpeed` is written (`src/waves.asm:1444`) and never read for the Dropper. |
| **Trigger colour / colour mode** | ✅ | ✅ | Both, identically — `src/waves.asm:1398-1409` runs before the Dropper branch. |
| **Trigger fire mode** | ❌ withdrawn | ✅ | |
| **Trigger fire mask bit** | ◑ occupies bit 0, inert | ✅ bits 1..N−1 | |
| **side** | ✅ | ❌ | The only property that is Dropper-only. |

Legend: ✅ applies, ❌ does not, ◑ consumes the resource without using it.

**Nine of thirteen rows are "escorts only".** That is the measure of how little
of the Wave Definition the Dropper actually uses — and the reason Option A below
is cheap: almost nothing has to be taken away from anybody.

### The build-time flight validator flies a path the Dropper never takes

`src/waves.asm:255-300` flies every definition at every speed a trigger asks for,
and collects speeds by `trigDef` match with no species test. A Dropper trigger's
speed therefore constrains its definition's legs against the wrap guard **on
behalf of escorts only** — correct today, since escorts do fly it, but the
validator has no notion that one member does not.

---

## The complete Dropper movement state machine

`src/dropper.asm`. Four module bytes, one weave table, three routines. There is
no per-object flight state: `src/dropper.asm:39-46` argues this is *the truth*
rather than a saving, because the one-live-Dropper rule means these describe THE
Dropper.

### State

| Byte | Meaning |
|---|---|
| `drPassLeft` | crossings still to make; 0 = leaving for good |
| `drPhase` | index into the 32-entry weave table |
| `drHold` | frames until the weave advances one phase |
| `drPing` | frames until the next sonar ping |

Diagnostics, saturating: `drLaunched`, `drEscaped`, `drPinged`.

**Direction is not stored.** It is the sign of `wmVX`, kept truthful because
`src/enemy.asm`'s despawn rules read that byte to tell an enemy *arriving*
through a border from one *leaving* through it (`src/dropper.asm:48-52`).

### Constants

| Constant | Value | Meaning |
|---|---|---|
| `DROP_ENTRY_LEFT` / `_RIGHT` | 0 / 343 | outside the visible 24..343 window, so it slides in through the border |
| `DROP_X_LEFT` / `_RIGHT` | 24 / 320 | turn points — the *visible* edges, so reversal happens on screen |
| `DROP_PASSES` | 3 | odd, so it exits the opposite side; asserted odd at assembly time |
| `DROP_VX` | 12 qpx = 3 px/frame | ~99 frames a crossing, ~6 s for the flight |
| `DROP_CENTRE_Y` | 88 | upper third of the 55..247 aperture |
| `DROP_AMPLITUDE` | 16 | keeps it inside 72..104; asserted against the aperture |
| `DROP_PHASES` / `_HOLD` | 32 / 2 | a 64-frame weave cycle |
| `DROP_PING_PERIOD` / `_FIRST` | 48 / 8 | sonar locator cadence |

### `dropperLaunch` (`src/dropper.asm:186`) — entry A = side, X = slot

```
drPassLeft  <- DROP_PASSES
drPhase     <- 0            (phase 0 is the centreline by construction)
drHold      <- DROP_PHASE_HOLD
drPing      <- DROP_PING_FIRST
logY        <- DROP_CENTRE_Y
wmVY, wmAccX, wmAccY <- 0   (wmVY is NOT spare: the top despawn rule reads it)
enyFire     <- ENEMY_FIRE_NONE
if side == RIGHT:  logX <- 343,  wmVX <- -12
else:              logX <- 0,    wmVX <- +12
drLaunched++ (saturating)
```

### `dropperFly` (`src/dropper.asm:272`) — replaces `wmTick`, one frame

```
jsr wmApplyVelocity            -- the ORDINARY integrator, X axis only
                                  (wmVY is zero, so logY is untouched)

-- the weave --
if --drHold == 0:
    drHold <- DROP_PHASE_HOLD
    drPhase <- (drPhase + 1) mod DROP_PHASES
logY <- DROP_CENTRE_Y + dropperWeave[drPhase]      -- written OUTRIGHT

-- the turn --
if drPassLeft != 0:
    if travelling right and logX >= DROP_X_RIGHT:  turn
    if travelling left  and logX <= DROP_X_LEFT:   turn
    turn:
        if --drPassLeft == 0:        -- that was the third
            drEscaped++              -- fly on out; the ordinary despawn rule
                                     -- retires it. Nothing is reversed.
        else:
            wmVX <- -wmVX            -- reverse
            wmAccX <- 0              -- start the turn from a whole pixel

fall through to dropperPing
```

**The pass test is skipped entirely once `drPassLeft` is 0**, and must be: the
Dropper is then past the turning point and getting further past it every frame,
so a test that still ran would reverse it on every one of them.

**The phase is never reset after launch**, which is what makes a reversal smooth
— the Dropper turns round horizontally and carries on through the same weave.

### `dropperPing` (`src/dropper.asm:357`)

Decrements `drPing`; on zero requests `SFX_PING` and reloads. Driven from the
flight, which is what makes it stop by itself: a dying enemy goes to
`enemyDeathTick` before reaching the movement call, and a despawned one no longer
exists. There is no "stop the ping" path to get wrong.

### The branch away from ordinary movement

`src/enemy.asm:595-607` — species is tested **first**, before roles:

```asm
    lda enySpecies,x
    cmp lvlDropRow
    beq !dropper+
    lda enyRole,x            ; ROLE_GUARD and above -> tokenGuardMove
    ...
!dropper:
    jsr dropperFly
    jmp !moved+
!authored:
    jsr wmTick
```

### What ordinary machinery is bypassed, and what is not

| Machinery | Dropper |
|---|---|
| `wmTick` | **bypassed** |
| `wmEnterStage` | runs once at spawn, then overwritten |
| stage advance / `wmTimedStep` | **bypassed** — no stage ever advances |
| `wmArcStep`, `wmLoadHeading`, `wmPhase` | **bypassed** |
| `wmApplySpeed` | **bypassed** — this is why speed does nothing |
| `wmApplyVelocity` | **used**, deliberately: nine-bit signed quarter-pixel X travel is exactly what it already does correctly |
| `logY` integration | **bypassed** — written outright from the weave table |
| despawn rules (`src/enemy.asm`) | **used** — which is why `wmVX`/`wmVY` must stay truthful |
| death path, animation, collision, HP | **used unchanged** |
| scroll / `worldProgress` | **no interaction at all** — the flight is in screen space and does not read `worldProgress`; only the *trigger row* does |

`wmSpeed` is the one field written for the Dropper and never read.

---

## Intrinsic lifecycle and token behaviour

Genuinely identity-specific mechanics, separable from movement:

| Mechanic | Where | Notes |
|---|---|---|
| **token spawn** | `src/enemy.asm:806-820` → `tokenDropperDied` (`src/token.asm:303`) | Reached **only** from `enemyDeathTick`'s release path: `objHP` reached zero *and* the death animation finished. |
| **destruction requirement** | `src/enemy.asm:791-797` | An escaped Dropper drops nothing — it leaves through `enemyTick`'s despawn rules and never reaches the hook. `drEscaped` counts it. |
| **slot ordering** | `src/enemy.asm:806-818` | Position captured, slot freed, *then* the token requested — so the pool always has room. No deferred queue; a reward cannot be lost. |
| **one-live-Dropper** | `tkDropperLive` (`src/token.asm:219`) | Claimed at `src/waves.asm:1316`, released at `src/enemy.asm:852-862`. |
| **release on either exit** | `enemyDespawn` (`src/enemy.asm:851`) | Deliberately here and not on the death path, because *both* ways of leaving must clear it. Read before `objectFree` erases the species. |
| **second token refused** | `src/token.asm:304-308` | `tkActive` guards it: "the one-Dropper rule should have made this impossible, and a second token is the one outcome worth refusing". |
| **firing** | `src/dropper.asm:230` | Withdrawn with the path it was granted for. The species *table* says the Dropper can fire (`enemyFireModeTab`, `src/enemy.asm:409` = `ENEMY_FIRE_DOWN`); the flight overrides it. |
| **collision / damage / HP** | none | Entirely ordinary — see *HP architecture*. |
| **sprite / resource ownership** | none | One ordinary pool object. Not one VIC register is written from `src/dropper.asm`. |
| **sound** | `src/dropper.asm:357` | The sonar ping, driven from the flight. |

### A second Dropper Trigger while one is alive

Measured — two Dropper triggers at rows 8 and 12, 3 members each, one definition:

```
inst member species          fire role spd   x   y  vx vy mode
   1      0   8 DROPPER     0    0   4   0  88  12  0    0      <- instance 1
   1      1   0 plain       1    0   4 120  50   3  3  8   76
   1      2   0 plain       1    0   4 150  50   3  3  8   76
   3      0   0 plain       1    0   4  90  50   3  3  8   76   <- instance 0
   4      1   0 plain       1    0   4 120  50   3  3  8   76
   5      2   0 plain       1    0   4 150  50   3  3  8   76
=> 6 spawned, 1 Dropper(s)
```

The second wave sends its full 3 members and **every one of them is an escort**.
Its member 0 is refused exactly as its siblings are. Two Dropper triggers close
together therefore produce one Dropper and five ordinary enemies, and the second
trigger's authored intent silently evaporates. Nothing warns; `validation_v6` has
a `trigger.crowded` warning for `WAVE_SLOTS + 1` triggers in a window but nothing
for two Dropper triggers in one Dropper's lifetime.

---

## Escort coupling

**Escorts are ordinary independent enemies from the instant they spawn.** They
carry `enyRole = ROLE_NORMAL` (measured: `role 0` throughout), fly `wmTick`
normally, obey the authored program, formation offsets, colour, trigger speed and
their own fire-mask bit, take `ENEMY_MAX_HP` damage, and despawn by the ordinary
rules. Nothing links an escort to its Dropper: no back-pointer, no wave-instance
lookup at tick time, no shared state.

| Property | Escort source |
|---|---|
| identity | `lvlPlainRow` — level-wide, cannot vary |
| movement | the Trigger's Wave Definition, fully |
| formation offset | `startX + index*xStep`, `startY + index*yStep` — index 0 unused |
| speed | Trigger speed, scaled normally |
| heading | the definition's launch heading |
| colour | the Trigger's colour byte, rolled per member if RANDOM |
| firing | its own mask bit, plus the Trigger's fire mode |
| collision / HP | ordinary, `ENEMY_MAX_HP` |
| lifecycle | ordinary despawn |

**Dropper death does not affect escorts directly** — but it triggers something
that does. `tokenAssignRoles` (`src/token.asm:385`) runs when the token appears
and scans **every live enemy in slot order**:

- the first `TK_GUARDS` (3) are posted as guards — `tokenSilence` + `tokenHalt`,
  and thereafter moved by `tokenGuardMove` instead of `wmTick`;
- the surplus is dismissed onto a terminal `WM_EXIT`.

So surviving escorts usually *become* the protectors — which makes the
one-Trigger authoring genuinely coherent in play. But the coupling is **temporal,
not structural**: any live enemy from any trigger is equally eligible, and an
escort that has already left is simply not there. Escort death does not affect
the Dropper at all.

**Verdict: spawn-time substitution, not a deeply coupled subsystem.** The only
persistent link is one shared byte, `tkDropperLive`.

---

## Trigger speed behaviour

Confirmed semantics (unchanged by this audit): encoded 4..8 = 1.00×..2.00×,
linear velocity scales, angular progression does not, so loops widen.

| | `wmSpeed` on the object | velocity at 1.00× | velocity at 2.00× |
|---|---|---|---|
| **Dropper** | written correctly (4, then 8) | `wmVX = 12` | `wmVX = 12` — **unchanged** |
| **Escorts** | written correctly | `wmVX = 6` (authored) | `wmVX = 12` (6 × 2) |

Measured in one run at 2.00×:

```
inst member species          fire role spd   x   y  vx vy mode
   1      0   8 DROPPER     0    0   8   0  88  12  0    0
   1      1   0 plain       1    0   8 130  60  12  0    0
   1      2   0 plain       1    0   8 160  60  12  0    0
   1      3   0 plain       1    0   8 190  60  12  0    0
```

At 2.00× the escort velocity coincidentally equals `DROP_VX`; the 1.00× run
separates them (Dropper 12, escorts 6). **The Dropper ignores trigger speed**
because `dropperLaunch` writes `DROP_VX` as a literal and `dropperFly` calls
`wmApplyVelocity`, never `wmApplySpeed` (`src/movement.asm:353`).

**Would existing speed machinery apply if the Dropper used ordinary Movement
Programs? Yes, with no new code.** `wmApplySpeed` is invoked from exactly two
cold places — `wmLoadHeading` for arcs and the STRAIGHT/HOLD branch of
`wmEnterStage` (`src/movement.asm:424`, `:468`). Any object that enters stages
through `wmEnterStage` is scaled automatically, and `wmSpeed` is *already* on the
Dropper's object. A Dropper flying a Movement Program would obey trigger speed
the moment the branch at `src/enemy.asm:596` stopped diverting it — nothing would
need adding. The build-time validator would also start covering the Dropper's
path for free, since it already flies every definition at every speed a trigger
asks for.

---

## Preview behaviour

`movement_sim.simulate_trigger` (`tools/level_editor/movement_sim.py:650`)
**refuses** a Dropper trigger outright:

```python
if trig.species == "DROPPER":
    raise SimulationError(
        "DROPPER triggers are not previewed in this phase.\n\n"
        "A Dropper is taken off its wave's authored path the instant it "
        "spawns -- src/dropper.asm installs its own three-pass flight over "
        "the top of the aperture -- so an ordinary-wave preview would show "
        "a trajectory the engine never flies.")
```

The panel shows "preview unavailable", the reason on the canvas, and a one-line
summary in the detail strip; `test_preview_gui.py` asserts all of that.

**What is missing, and why:** the refusal is correct about the Dropper and throws
away the escorts with it. The wave *is* fully previewable for members 1..N−1 —
they fly the authored program exactly. So today the author gets nothing for a
Dropper trigger, including the five-sixths of it that would be accurate.

**Is there enough data to preview Dropper + escorts accurately? Yes, entirely.**
Everything the runtime flight uses is a compile-time constant in
`src/dropper.asm` — `DROP_ENTRY_LEFT/RIGHT`, `DROP_X_LEFT/RIGHT`, `DROP_PASSES`,
`DROP_VX`, `DROP_CENTRE_Y`, `DROP_AMPLITUDE`, `DROP_PHASES`, `DROP_PHASE_HOLD` —
plus `dropper_side` from the Trigger. The weave is `round(A*sin(2πk/32))`, which
`movement_sim` can compute directly. A faithful preview needs no new authored
data and no new engine field; it needs the constants mirrored (or, better, parsed
out of `src/dropper.asm` the way `asm_decl` already parses the encounter format).

Two consistency notes, neither changed here:

- `movement_sim.py:650` and `controller_v6.py:841` test `species == "DROPPER"` by
  **literal name**, while `validation_v6.py:720` and `encounters_ui.py:95-102`
  correctly use `C.identity_behaviour(...) == C.BEHAVIOUR_DROPPER`. With one
  Dropper identity in the roster the two agree; a second would split them.
- `encounters_ui.py:836,872` greys the side field for non-Droppers using the
  behaviour test — correct.

---

## HP architecture

**Definition.** One constant, `src/enemy.asm:25`:

```asm
.const ENEMY_MAX_HP      = 6        // TYPE data: every enemy starts here, so
                                    // no per-object maximum is stored
```

**Damage.** One constant, `src/collision.asm:39` — `SHOT_DAMAGE = 1`, applied at
`src/collision.asm:434-438`. Six cannon hits kill any enemy.

**Every write of enemy HP** (the complete set):

| Site | Purpose |
|---|---|
| `src/waves.asm:1470` | wave spawn — Dropper and escorts alike |
| `src/token.asm:740` | reinforcement guard spawn |
| `src/objects.asm:168` | slot reuse must not inherit health |
| `src/collision.asm:438` | damage |
| `src/boss.asm:447`, `src/ebullet.asm:308`, `src/pickup.asm:344` | non-enemy types |

**Is it shared, identity-specific, or hard-coded?** Shared and hard-coded. It is
`TYPE` data by explicit design, and **there is no Dropper special handling
anywhere** — the Dropper takes six hits exactly like a Ring. The audit found no
HP branch on species, role, or identity.

**Cleanest future home for per-identity HP metadata.** HP belongs with the
identity, and identities are the *level's* choice, so it belongs in package data
beside the two bytes that already work this way:

1. Add `hp` to `Roster` in `tools/sprite_export/import_spd.py:215` beside
   `behaviour` — one field, defaulting to `ENEMY_MAX_HP`, so every existing entry
   is unchanged.
2. Emit `LVL_SLOT_HP` as a 3-entry list in `stage_enemies.asm`, generated by
   `level_enemies_asm` exactly as `LVL_ANIM`, `LVL_DROP_ROW` and `LVL_PLAIN_ROW`
   are today (`import_spd.py:425-445`).
3. Reserve 3 bytes in the package after `LEVELPKG_PLAINROW`. There are **77 spare
   bytes** between `LEVELPKG_ASSETS_END` (`$ffad`) and `LEVELPKG_TOP` (`$fff9`).
4. Copy to a 3-byte `lvlSlotHP` array in `src/level_assets.asm` beside
   `lvlDropRow`/`lvlPlainRow`.
5. Replace `lda #ENEMY_MAX_HP` at `src/waves.asm:1470` with an indexed load on
   `enySpecies >> ENEMY_ANIM_SHIFT` — the same shift `enemyFireModeTab` already
   uses. `src/token.asm:740` follows.

That is one authored field, three package bytes, and two `lda #` becoming
`lda tab,y`. It also removes the current situation where the exporter knows an
identity's frame count and behaviour but not its toughness. **Not implemented
here.**

---

## Option comparison

### A — Escort Wave + separate Dropper Movement Program

The Trigger keeps its Wave Definition for escort count, formation and movement;
one member is still the Dropper; the Dropper gets its own **Movement Program**
reference, flown by ordinary machinery.

| | |
|---|---|
| **Schema** | one new Trigger field: `dropper_program: str \| None`. `None` ⇒ keep the current hard-coded flight, so migration is a no-op. |
| **Export** | one new trigger column (`trigDropProg`) holding a program byte offset, or `$ff` for "the built-in flight". Costs **120 bytes** of the package's trigger reservation — and the reservation has only **2 spare bytes** at 9 columns × 120 slots = 1080 of 1082. A tenth column forces the slot count from 120 to 108. |
| **Runtime seam** | `src/waves.asm:1461` — instead of unconditionally calling `dropperLaunch`, branch: if the trigger names a program, write `wmStage` from it, call `wmEnterStage`, and **do not** divert at `src/enemy.asm:596`. Needs one bit of per-object state ("this Dropper flies a program") so the movement branch knows. `enyRole` has spare values, or a spare bit in `enySpecies`'s high nibble. |
| **Reuse** | total. Arcs, legs, headings, `WM_EXIT` inheritance, trigger speed, the build-time flight validator and the preview all start working on the Dropper with no new code. |
| **Intrinsic behaviour** | untouched. Token, liveness, ping and death are keyed on `enySpecies`, not on how it moves. |
| **Preview** | becomes ordinary for the whole wave — one member on the Dropper program, the rest on the wave's. |
| **Risk** | the "where it dies matters" argument in `src/dropper.asm:8-14` becomes the **author's** responsibility. A Dropper authored to die at the bottom leaves the P no room. Mitigable with a validator rule: warn if the Dropper program's path spends its life below some row. |
| **Cost** | moderate. One schema field, one column (with a capacity consequence), one runtime branch, one state bit, editor UI, and a validator rule. |

### B — Escort Wave + second Dropper Wave Definition

| | |
|---|---|
| **What it buys over A** | count, interval, formation offsets and launch heading for the Dropper. |
| **What that is worth** | ~nothing. The Dropper is *one* enemy: count is 1, interval is meaningless, formation offsets are meaningless, and the only field that matters — the Movement Program — is the one field A already provides. A whole 10-byte Wave Definition to carry one useful field. |
| **Cost** | a definition slot per Dropper trigger (26 slots total, 7 used), a second trigger column anyway, a validator rule that the Dropper definition has count 1, and an editor concept ("this trigger has two waves") that is harder to explain than the thing it models. |
| **Verdict** | **unnecessarily heavyweight.** Strictly worse than A. |

### C — Remove substitution

Dropper becomes an ordinary member of its wave; escorts need their own Trigger(s).

| | |
|---|---|
| **Simplicity won** | real and considerable. Delete the claim/substitute branch (`src/waves.asm:1296-1318`); a Dropper wave is just a wave. |
| **Authoring lost** | the one-Trigger Dropper+escort encounter, which the brief identifies as genuinely useful, and which `tokenAssignRoles` makes coherent by turning the survivors into protectors. |
| **New problems** | the one-live-Dropper rule still has to exist (two Dropper *triggers* can still overlap), so the interlock does not go away — only the substitution does, and it would have to become an outright refusal or a dropped member, both of which silently rewrite authored content. `src/waves.asm:1303-1307` already argues against exactly that. |
| **Also** | authoring Dropper + escorts then needs two triggers at the same row, and `validation_v6` already warns `trigger.crowded` when more than `WAVE_SLOTS` triggers fall in one window. |
| **Verdict** | cleanest engine, worst authoring. Rejected. |

### D — The better seam the code reveals

**The substitution and the liveness interlock are two different things wearing one
branch, and separating them is the real improvement.**

`src/waves.asm:1296-1318` answers two unrelated questions in one place:

1. *Which member of this wave is the Dropper?* — an **authoring** question with a
   sensible answer (member 0) that nobody has written down.
2. *May a Dropper exist right now?* — a **safety** question about global state.

Because they share a branch, the answer to (1) is a race won by whoever spawns
first, and a second Dropper trigger silently degrades to an all-escort wave.

The seam is: **give the wave instance a "Dropper member index" and make the
interlock a separate, explicit refusal.**

```asm
; at waveStartNext, per instance:
wvDropMember[inst] <- 0        ; or authored, later
                               ; $ff once this instance's Dropper has been sent

; at waveSpawnMember:
is_dropper = (wvSpecies == lvlDropRow) && (wvIndex == wvDropMember[inst])
if is_dropper && tkDropperLive:  is_dropper = false   ; the interlock, explicit
if is_dropper:  claim; wvDropMember[inst] <- $ff
else:           enySpecies <- (wvSpecies == lvlDropRow) ? lvlPlainRow : wvSpecies
```

One byte per instance (`WAVE_SLOTS` = 2, so **2 bytes**). It makes the current
behaviour explicit and unchanged, removes the race, and gives Option A the field
it needs to place the Dropper anywhere in the formation later. It also makes
"this wave already sent its Dropper" a fact the code states rather than infers
from a global flag.

---

## Recommended architecture

**Option A, on the Option D seam.** Smallest coherent change that meets all six
goals.

### Step 1 — make the member choice explicit (no behaviour change)

Add `wvDropMember` (2 bytes) as in D. Restructure `src/waves.asm:1296-1318` so
the member test and the liveness test are separate conditions. Behaviour is
byte-identical today; the race is gone and the seam exists.

*Why first:* it is independently valuable, testable against current behaviour,
and it is the thing Option A needs. No schema, no export, no editor change.

### Step 2 — make Dropper movement authorable

| Layer | Change |
|---|---|
| **Schema** | `Trigger.dropper_program: str \| None = None`. `None` means the built-in flight, so every existing project migrates untouched. |
| **Export** | new trigger column `trigDropProg`, program byte offset or `$ff`. **Capacity:** a tenth column takes the slot count from 120 to 108 (1082 reserved / 10). That is a real cost and it should be a deliberate decision — `LEVELPKG_ENC_MAX` is 1600 with the trigger reservation computed as the remainder, so growing the reservation instead is also on the table. |
| **Runtime** | at `src/waves.asm:1461`, if the trigger names a program: write `wmStage`, call `wmEnterStage`, set a "flies a program" marker. Otherwise `dropperLaunch` as now. At `src/enemy.asm:596`, divert to `dropperFly` **only** when that marker is absent. |
| **State** | one flag per object. Cheapest honest home is a spare `enyRole` value (`ROLE_NORMAL`/`ROLE_EGRESS`/`ROLE_GUARD+n` leave room) — but roles are `src/token.asm`'s, so a dedicated `enyDropFlies` byte array (16 bytes) is the clearer choice. |
| **Validator** | warn when a Dropper program's path would leave the P no room to be fought over — the invariant `src/dropper.asm:92-96` currently enforces by construction. Also: warn that fire-mask bit 0 is inert on a Dropper wave (see below). |
| **Editor UX** | one extra combo on the Trigger pane, enabled only for a Dropper identity, defaulting to "built-in flight". The side field greys out when a program is chosen, since side is the built-in flight's input. |
| **Preview** | `simulate_trigger` stops refusing. A Dropper trigger previews as N paths: member 0 on the Dropper program (or the mirrored built-in flight), the rest on the wave's. |
| **Migration** | none required. `None`/`$ff` reproduces today's behaviour exactly, so the change is opt-in per trigger. |

### What this preserves

1. **One-Trigger authoring** — unchanged; the Trigger still carries the whole
   encounter.
2. **Dropper movement authorable** — the point of the exercise.
3. **Normal machinery reused** — arcs, legs, speed, the flight validator and the
   preview all apply with no new movement engine.
4. **Intrinsic behaviour preserved** — token, liveness, ping, death and
   conscription are keyed on identity, not on movement.
5. **No duplicated engine** — `src/dropper.asm` stays as the *default* flight,
   not a parallel system; and when no trigger names a program it is exactly what
   runs today.
6. **Understandable semantics** — "the Dropper is member 0 and flies this
   program" is one sentence.

### Cheapest improvements available *without* any of the above

Worth separating out, because two of them cost almost nothing:

- **Warn that fire-mask bit 0 is inert on a Dropper wave.** Validator only, no
  runtime change. Level 1 trigger 0 authors `%111111` and gets five shooters.
- **Warn when two Dropper triggers fall within one Dropper's flight** (~6 s at
  `DROP_VX`, so ~99 × 3 frames ≈ 37 coarse rows). The second one's authored
  intent currently evaporates in silence.
- **Preview the escorts** even while refusing the Dropper — draw N−1 paths and
  mark member 0 "built-in flight, not previewed". Editor only.
- **Use `identity_behaviour` instead of `== "DROPPER"`** at
  `movement_sim.py:650` and `controller_v6.py:841`, matching what
  `validation_v6.py` and `encounters_ui.py` already do.

---

## Diagnostics run

Three temporary probes in the session scratchpad, all read-only: they poke the
**loaded package in RAM** (`tests/synth.py`, built in the previous task) and the
engine's own `lvlPlainRow`, never a file. Every VICE launch was owned by exact
PID, `-console`, and reaped in a `finally`; **0 VICE processes remained** at the
end of each run and at the end of the audit.

| Probe | Cases | What it settled |
|---|---|---|
| `dropper_probe.py` | authored Level 1; side=RIGHT; count=1; two Dropper triggers; speed 1.00× and 2.00× | total = member count; 1+2 for trigger 4; side changes entry only; no escort at count 1; second trigger is all escorts |
| `dropper_probe2.py` | member index; fire mask `%1111`/`%0001`/`%1110`; speed 2.00× | Dropper is member 0; bit 0 inert; Dropper vx constant at 12 while escorts scale 6→12 |
| `dropper_probe3.py` | `lvlPlainRow` = default / 16 / 8 | escorts come from `lvlPlainRow`; forcing it equal to `lvlDropRow` yields four stacked Droppers sharing one flight state |

**Two instrument errors found and corrected** — recorded because AGENTS.md rule 4
is that a green instrument can be wrong:

1. Member index read as `wvIndex - 1`; the increment is *after*
   `waveSpawnMember` (`src/waves.asm:1043`), so member 0 printed as `-1` and one
   activation fell outside the sample budget, briefly suggesting trigger 0
   produced no Dropper at all.
2. Escort identity probed by poking the **package** byte `$ffac`, which
   `src/level_assets.asm:126` has already copied into `lvlPlainRow` at level
   load. The probe reported "escorts unchanged" while printing the value it had
   just written to a byte nothing reads. Poking `lvlPlainRow` gave the real
   answer, which is the opposite conclusion.

**Existing suites, as corroboration** (no changes made to them). Both report one
failure, and **neither failure contradicts anything in this audit** — both are
pre-existing and content-dependent, in suites this session did not touch:

```
dropper_flight         FAIL  1 of 23 -- "the second Dropper entered from the
                             OTHER authored side -- first entered x=0, second x=0"
token_encounter        FAIL  1 of 22 -- "a surviving protector visibly ASCENDED
                             rather than being deleted -- runs {}"
```

- `test_dropper_flight.py:449` expects Level 1's **two** Dropper triggers to be
  authored on **opposite** sides, so it can prove the mirrored appearance runs
  through the same routine. Both are `LEFT` today (the side column is
  `[0,0,0,0,0]`), so the mirrored case simply does not exist in the content. This
  is the same authored-content freeze class dealt with in
  `reports/defreeze-tests-from-authored-content.md`; that task covered the
  content-coupled suites in `test-full`, and this one is in the `test-soak` tier
  and was out of its scope. The check would pass the moment one Dropper trigger
  is authored `RIGHT`, and it proves nothing about the engine either way.
- `test_token_encounter.py:864` reports `runs {}` — the honest "the case did not
  occur" signal. The run ended with `tkEgressed 0` and no surviving protector, so
  there was nothing to watch leave. Coverage by luck, of exactly the kind
  `test_flight_paths.py` documented about itself; the neighbouring check "no guard
  remains: every survivor is leaving -- roles []" passed on the same empty set.

**What did pass in those suites is the corroboration that matters**, and every
one of these lines is a claim this audit also makes:

```
ok   a second authored Dropper was launched
ok   ...through the same routine: same pass count, same centreline -- passLeft=3 logY=88
ok   ...travelling INTO the playfield from that side -- x=0 vx=12
ok   ordinary Rings still fly the movement interpreter, with real velocities
ok   destroying it started the encounter
ok   exactly one token exists -- slots [0]
ok   the P appeared exactly where the Dropper died -- P at (144,79) vs death (144,79)
ok   the death released the one-Dropper claim
ok   a destroyed Dropper stops pinging immediately -- drPinged 11 -> 11
ok   no authored wave started while the encounter ran -- wvStarted 1 -> 1
ok   the authored stage resumed after the encounter -- wvStarted 1 -> 2
```

The second Dropper launching at all is itself worth noting: it confirms
`tkDropperLive` is released between triggers 0 and 4, so the two authored Dropper
waves each get their Dropper when they are far enough apart.

Disk usage: the three probe scripts and their output total **56 KB** in the
session scratchpad. The scratchpad had also accumulated 34 MB of tree copies and
tarballs from earlier tasks in this session; those are no longer needed and were
deleted, leaving 1.7 MB of run logs. `build/` holds the current binaries and
symbols only (340 KB, gitignored, including the normal `build/level2/` package
intermediates). Nothing was written to `/tmp`.

---

## Confirmation

**No production code or content was changed.** The only file added is this
report. `src/`, `tools/`, `tests/` and every authored level document are
byte-identical to `HEAD`.

Final `git status`:

```
On branch main
Untracked files:
  reports/dropper-escort-substitution-audit.md

nothing added to commit but untracked files present
```

`git status --short`:

```
?? reports/dropper-escort-substitution-audit.md
```

**Nothing committed and nothing pushed.** No `git checkout`, `git restore`,
`git reset`, `git stash` or destructive clean was used at any point. No redesign
was implemented.
