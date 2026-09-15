# Player muzzle flash on HW1

**Repository:** `/Volumes/SSD/dev/C64/6502-shmup`
**Supplied asset:** `src/player_muzzle_flash.asm` (checked in verbatim)

---

## Status

A valid shot now produces a bank-matched **twin wing-gun** muzzle flash on
**HW1**: two bold flares held **red for both PAL frames**, then gone. **The
craft itself no longer reacts to firing at all** — the gun flashes, the hull
does not.

> **The hull flash is gone (latest change).** Firing used to swap `$d027` to
> red for three frames, so the whole craft reddened on every shot. Removed at
> your request. `plyMuzzle`, `PLAYER_MUZZLE_TIME` and the weapon's writes to
> them went with it — nothing else read that timer. §2a and §9.
>
> **Revisions.** The first pass used nose-mounted artwork, replaced by the
> supplied twin-gun version, then replaced again by the supplied **bold**
> twin-gun version now in the tree. The bold asset keeps the same gun
> alignment, the same HW1 placement and the same five blocks, but its header
> carries an **integration instruction as well as art**:
>
> > *"remove the earlier orange->red colour pulse in integration code. Set
> > $D028 to red for the full two-frame flash instead."*
>
> **That reverses the original brief's "frame 1 orange, frame 2 red".** I took
> the later asset as authoritative and removed the pulse; §3 and §9 record what
> changed in code. If the brief's pulse was meant to stand, that is the one
> decision here to hand back.

| | |
|---|---|
| build | clean |
| focused proof | **ALL PASS** — `tests/test_player_ship.py` |
| production gate | **RED** — on a pre-existing flake unrelated to this work. §9.4, and it needs your call |
| VICE | every run reaped, `pgrep -fl x64sc` clear at the end |
| health counters | `gameOverrun`, `publishSkip`, `schedBuildDefer`, `scrollLate`, `edgeLate`, `statPageMismatch`, `statPtrMismatch` all **0** |
| weapon cadence | **unchanged** — measured at exactly 8 frames |
| **manual visual judgement** | **yours** — §10 |

Measured: 5 accepted shots at exactly 8-frame spacing produced **10 lit frames
— exactly 2 per shot**, orange then red then dark, with the correct
bank-specific bitmap every time.

---

## 1. The supplied artwork, verified rather than assumed

The asset is checked in **byte for byte as delivered**. Nothing generates,
rewrites or rescales it. Its header documents the pixel semantics and the
gun-tip coordinates it was drawn against, and the focused proof checks both
against the bytes the VIC will actually read rather than taking them on trust:

| claim | verified |
|---|---|
| 5 blocks, 320 bytes | ✓ |
| uses only pairs 00, 10 (`$d028`) and 11 (`$d026` white) | ✓ — `bit pairs present: [0, 2, 3]` |
| **pair 01 (`$d025`) never appears** | ✓ — so lighting the flash cannot disturb the black the craft's outline is drawn in |
| two flares per frame, one per wing gun | ✓ — `[2, 2, 2, 2, 2]` |
| **each flare centred on a real gun barrel at the code's Y lift** | ✓ — no exceptions in any of the five banks |
| nothing reaches the craft's exhaust rows | ✓ |
| "same gun alignment as the corrected twin-gun version" | ✓ — every barrel re-derived independently |

That `$d025` row is still the load-bearing one. The craft on HW0 depends on
`$d025` being black, and the two sprites share both shared registers; because
the flash art never uses pair 01, the sting is a change to **`$d028` alone**, a
register nothing else in the game reads.

### The registration was checked, not assumed

The header names the gun tips it was drawn against. Those are claims about
**your amended ship art**, so they were checked against it rather than believed:

| bank | header's gun tips | lit pixel there in `player_art.asm` | flare stems (craft rows) |
|---|---|---|---|
| hard left | (2, 9) (8, 5) | ✓ ✓ | 5–8 and 1–4 |
| soft left | (2, 9) (9, 7) | ✓ ✓ | 5–8 and 3–6 |
| neutral | (2, 8) (9, 8) | ✓ ✓ | 4–7 both |
| soft right | (2, 7) (9, 9) | ✓ ✓ | 3–6 and 5–8 |
| hard right | (3, 5) (9, 9) | ✓ ✓ | 1–4 and 5–8 |

Every flare's centre column ends exactly **one row above** its barrel, in every
bank, with `PLAYER_FLASH_Y_LIFT = 7` applied. The bold asset's claim to keep
"the same gun alignment" holds: the barrels were re-derived from its own bytes,
not carried over. The artwork is precisely registered to the ship you amended,
and the existing lift is the one it was drawn for.

The bold flares are three columns wide for their full length and reach **above**
the craft's top row, which is what makes them read as muzzle flashes rather than
sparks. Lit bytes per frame went from `[9, 8, 8, 8, 9]` to `[19, 14, 14, 14, 19]`
in the same five blocks.

The five frames also preserve the ship's own mirror structure: hard-left is an
exact horizontal mirror of hard-right, soft-left of soft-right, and neutral is
mirror-symmetric to the pixel.

## 2. Integration point — `shotFired`

**The trigger is `shotFired`, and no weapon code was touched at all.**

`weaponFire` sets it only on a shot the weapon has **accepted** — past the
overheat test, past the cooldown, with the cadence already armed — and
`weaponTick` clears it at the top of every frame. `playerEmit` runs *after*
`weaponTick` in `gameFrame`, so it sees this frame's event and no other.

Reading the fire **button** instead would flash every frame the trigger was
held, sixty times a second, including for shots the weapon refused. The proof
measures this directly: over 40 frames of held fire, HW1 was lit on **10**,
not 40.

`plyMuzzle` was the other candidate — it is already the player-facing
"a shot happened" signal — but it runs for `PLAYER_MUZZLE_TIME` (3) frames and
drives the hull's own red flash. Keying off it would have tied the two effects'
durations together; `shotFired` is the event, `plyMuzzle` is one reaction to
it, and the flash is now another.

---

## 2a. Removing the hull flash

Firing drove **two** separate things. Only one of them was the supplied muzzle
flash:

| | signal | duration | what it did |
|---|---|---|---|
| HW0, the craft | `plyMuzzle` | 3 frames | swapped `$d027` to red — **the whole hull reddened** |
| HW1, the flash | `plyFlash` | 2 frames | the supplied artwork at the guns |

The first is what "the player flashes when firing" describes, and it is what
was removed. The second is the feature built over the previous revisions and it
is untouched.

**What went, and why more than one line:** `plyMuzzle` existed *only* to colour
the hull. With `playerEmit` no longer reading it, the byte, its
`PLAYER_MUZZLE_TIME` reload in `weaponFire` and its countdown in `weaponTick`
were a timer nothing read, so all three went too. `PLAYER_COL_MUZZLE` was also
what `PLAYER_COL_FLASH` borrowed its red from; the flash now names its own red
rather than depending on a constant whose reason for existing had gone.

**What did not go:** `shotFired`, the cadence, the heat, the overheat latch and
the hitscan are untouched — the proof measures the cadence at exactly 8 frames
either side of the change. `playerTakeHit` still drives the invulnerability
blink, so **the craft does still change appearance when hit**; it just no longer
does so when firing, which was the confusion.

This is the one place the change reaches outside `player.asm`: two small
deletions in `src/weapon.asm`, both presentation-only.

## 3. Flash state machine

One byte, `plyFlash`, in the player state block. Presentation only — nothing in
the weapon, collision or movement path reads it, and the weapon does not know
it exists.

```
shotFired  ->  plyFlash = PLAYER_FLASH_TIME (2)

plyFlash 2 : HW1 on, red ($d028 = PLAYER_COL_FLASH = PLAYER_COL_MUZZLE, 2)
plyFlash 1 : HW1 on, red ($d028 unchanged)
plyFlash 0 : HW1 off, pointer returned to the blank block
```

**The colour no longer varies with the count.** The original brief asked for an
orange frame then a red one; the bold artwork's header asks for flat red across
both, because it carries its own white-hot core in the shared white and wants a
single colour underneath. `PLAYER_COL_FLASH_1`/`_2` collapsed into one
`PLAYER_COL_FLASH`, and the branch on the count went with them — the count now
decides only *whether* HW1 is lit, not what colour it is.

The count is **decremented after the enable test has read it**, not when the
pointer and colour are chosen. That ordering is a bug I wrote and then caught:
decrementing at selection time emitted the red frame and disabled the sprite
for that same frame, so the sting was one frame long and the second never
appeared. The code says so where the decrement lives.

Both frames use the **same bitmap** and now the same colour, so HW1's private
register is written once per flash and the shared pair the craft depends on is
still never touched.

---

## 4. Bank → bitmap mapping

```
pointer = PLAYER_PTR_FLASH + plyBank        (plyBank is 0..4, unsigned)
```

| `plyBank` | attitude | flash pointer |
|---|---|---|
| 0 | hard left | `$90` |
| 1 | soft left | `$91` |
| 2 | neutral | `$92` |
| 3 | soft right | `$93` |
| 4 | hard right | `$94` |

The craft's own frames are bank-major (`bank * 3 + engine`), so the same
`plyBank` drives both — one add, no table. The supplied asset's order
(hard-left → hard-right) matches the existing bank order exactly, which is why
no remapping was needed. Every attitude is exercised in the proof.

---

## 5. Position

- **X:** `plyPresX1 = plyX` — unchanged; both player sprites already share one X.
- **Y:** `plyPresY1 = plyY - 7`, the offset the artwork was drawn for. The
  flares are drawn low in their own block so that, lifted by this much, each
  one lands on a wing-gun barrel of the craft underneath. The registration is
  the artwork's; this constant is the half of it that lives in code, and the
  proof now checks the two against each other (§1).
- **X-MSB:** untouched. `plyPresD010` still sets both player bits from
  `plyXHi` in one test, and a disabled sprite's MSB is ignored, so HW1 being
  conditionally enabled changes nothing here.

The subtraction has no borrow check because it cannot borrow: `PLAYER_MIN_Y`
is 55. That is asserted at assembly time rather than guarded at run time.

---

## 6. `$D01C`, and why nothing else is affected

```
PLAYER_D01C : %00000001  ->  %00000011
```

The repository already routes this through **one constant written by both
raster phases** (`exHud` at raster 4 and `exHandoff` at raster 40), because the
player is drawn through both and its mode may not change at the handoff. So
enabling HW1's multicolour bit was a one-constant change with no new register
write and no new cycles.

**Bits 2–7 remain clear**, so every HUD sprite and every gameplay mux slot is
still hires. This is enforced rather than asserted in prose — an existing
assembly-time guard refuses any `PLAYER_D01C` value with a bit outside
`PLAYER_SLOT_MASK`:

```
.if ((PLAYER_D01C & ~PLAYER_SLOT_MASK) != 0) {
    .error "only the player's own reserved slots may be switched to multicolour"
}
```

HW1's mode bit is set **permanently** rather than toggled with the flash: a
disabled sprite's mode is not read by anything, so there is nothing to switch
off and no frame on which the two could disagree.

The focused proof samples `$d01c` at several points in the frame and finds
`$03` every time, and separately confirms no gameplay schedule entry claims
slot 0 or 1.

---

## 7. HW1 ownership and enable

HW1 stays **player-owned and outside the multiplexer**. `MUX_FIRST_SLOT` is
still 2; the proof reads the adopted schedule and checks every entry's slot is
≥ 2.

What changed is that HW1 is no longer permanently enabled. It was a blank,
always-on second layer; it is now lit only for the two flash frames:

```
plyPresEnable = HW0 bit            when visible
              | HW1 bit            ...and only while plyFlash is non-zero
              = 0                  when the invulnerability blink hides the ship
```

The blink gates **both**, because it gates this one test — a blinking ship
whose gun kept flashing would be the one frame where the player is invisible
and their muzzle is not.

---

## 8. Files changed

| file | change |
|---|---|
| `src/player.asm` | *(hull flash removed; bold swap: colour pulse removed)* — flash allocation + guards, `PLAYER_COL_FLASH`, `PLAYER_FLASH_TIME`, `PLAYER_FLASH_Y_LIFT`, `PLAYER_HW0_BIT`, `PLAYER_D01C` → `%11`, `plyFlash` state, HW1 driving and enable logic in `playerEmit`, the flash bitmap segment |
| `src/player_muzzle_flash.asm` | the supplied **bold twin-gun** asset, verbatim |
| `tests/test_player_ship.py` | flash proof added; HW1 expectations updated; PNG-match assertion removed (§9); flash-geometry assertion replaced by the registration check (§9) |
| `tests/test_production.py` | `plyPresEnable` assertions updated for a conditionally-enabled HW1 |
| `src/weapon.asm` | **new this change** — the `plyMuzzle` reload in `weaponFire` and its countdown in `weaponTick` deleted. Cadence, heat, overheat and `shotFired` untouched |
| `src/main.asm` | one comment: the ordering note named `plyMuzzle`, now names `shotFired` |

**Not touched:** `collision.asm`, `renderer.asm`, `scroll.asm`,
`enemy.asm`, `waves.asm`, `movement.asm`, `hud.asm`, `turrets.asm`,
`ebullet.asm`, `objects.asm`, `main.asm`, `Makefile`. No weapon mechanics, fire
rate, hitscan, collision, enemy logic, encounter timing, movement, banking,
renderer, raster, HUD or mux scheduling was altered.

### VIC bank 0 allocation

```
$2000-$23ff   player ship      16 blocks, pointers $80-$8f   (unchanged)
$2400-$253f   MUZZLE FLASH      5 blocks, pointers $90-$94   (new)
$2540-$27ff   still free
```

Five 64-byte blocks in the free run immediately above the ship's own, verified
aligned, inside the bank, and disjoint from the HUD pool, the clip scratch
pools, the enemy and projectile bitmaps, both screen pages and both charsets.
Nothing was moved. Guards were added in the repository's existing style
(alignment, no overlap with the ship, no run past screen page B, pointer agrees
with the label).

---

## 9. Qualification

### Focused proof — `tests/test_player_ship.py`, ALL PASS

One VICE. The flash is a cadence behaviour, so it is watched through the **real
frame loop** with the fire button held and nothing poked — the cadence, the
heat and the accept decision are all the weapon's own.

| check | measured |
|---|---|
| holding fire produced accepted shots | 5 shots |
| **the cadence is unchanged** | gaps `[8, 8, 8, 8]` |
| HW1 lit on strictly fewer frames than held | **10 of 40** |
| **exactly 2 frames per accepted shot** | 10 lit for 5 complete shots |
| **red held for both frames → dark**, pointer back to blank | no violations |
| **firing never changes the hull colour** | `[14]` across all 40 frames |
| HW1's enable == flash AND ship visible, every frame | no exceptions |
| **every banking attitude selects its own frame** | all 5 banks |
| HW1 never appears in the gameplay schedule | slots `[2, 3]` |
| flash art uses only pairs 0/2/3, never `$d025` | ✓ |
| **two flares per frame, one per wing gun** | `[2, 2, 2, 2, 2]` |
| **each flare centred on a gun barrel, at the code's Y lift** | no exceptions |
| no part of the flash reaches the exhaust rows | ✓ |
| `$d01c` = `$03`, identical however sampled | ✓ |
| HW1 blank and **off** with no shot in flight | `ptr1=$8f enable=1` |
| HW1 co-located in X, lifted 7 in Y | `y0=220 y1=213` |
| ship, banking, engine animation, blink precedence | all still pass |

### Two defects found and fixed during implementation

1. **The decrement was in the wrong place** (§3) — the red frame was emitted
   and then disabled in the same pass, making the sting one frame long.
2. **Two stale assertions about HW1** in `test_production.py` — it asserted
   `plyPresEnable ∈ {0, PLAYER_SLOT_MASK}` and that a post-blink ship is
   "solid" only when *both* slots are on. Both encoded "HW1 is always enabled",
   which stopped being true. Restated rather than relaxed: the enable may now
   never set a bit **outside** the player's two slots, and **HW1 is never
   enabled without the craft it overlays** — a sharper invariant than the one
   it replaced, since it would catch the player reaching into the mux.

### The ship art is now hand-authored — one assertion removed

You amended `src/player_art.asm` after it was generated, so
`tools/gen_player_ship.py --check` now reports drift **correctly**: the PNG is
no longer the source of truth for that file. The assertion "the generated
bitmaps still match the sprite sheet" was therefore asserting the edits away
and has been removed; the tool remains as a record of provenance.

Nothing was lost, because the properties the engine actually relies on are
checked against the loaded bytes and **all still hold on your amended art** —
verified before changing anything:

- left banks are **exact horizontal mirrors** of the right
- neutral is **mirror-symmetric to the pixel**
- engine frames differ **only in rows 18–20**, the exhaust, never the hull

### The assertions the new art invalidated, and what replaced them

Three assertions had to change, and each was **restated rather than relaxed**:

**1. The row bound.** The original art lived in its top eight rows and the proof
asserted exactly that, as a proxy for "the streak meets the nose at the
documented Y lift". Both twin versions live lower, so it had to go — but
deleting it would have left the geometry unchecked, which is the one thing an
art swap can break. It was replaced by a **registration check**: for each flare
the proof finds its centre column and requires that the pixel one row below it,
*in the craft's coordinates with `PLAYER_FLASH_Y_LIFT` subtracted back out*, is
a lit pixel of the matching banked ship — the barrel the flare comes out of.
That fails on a wrong lift, a wrong bank order, a flare that misses its gun, or
art drawn for a different ship.

**2. "Tallest column" vs "any tall column".** My first version of that check
defined a flare's stem as any column with three or more lit pixels. The bold art
is three columns wide for its *full* length, so the flanking columns qualified
too and the check reported six stems per frame and four false misses. The art
was right and the check was wrong. It now groups contiguous lit columns into
flares and takes the column each flare burns **furthest down** as its centre —
two flares per frame, every centre on a barrel.

**3. The off-craft bound.** I had asserted no flash pixel falls outside the
craft's own 21 rows. The bold flares deliberately reach **above** the nose,
which is what makes them read as muzzle flashes, so that bound was simply wrong
about the art's intent. Only the downward extent is meaningful and it is now
bounded where it matters: nothing may reach the exhaust rows the engine flame
animates.

**4. The colour pulse.** `each shot lights HW1 ORANGE then RED` became `holds
HW1 RED for both frames`, following the asset header's instruction. The
surrounding structure is untouched: both frames must still be *enabled*, the
third must still be dark, and the pointer must still return to the blank block.

### The flash proof was measuring the wrong thing, and it hid a real failure

Removing the hull flash made the flash proof fail: **one lit frame per shot
instead of two**, every shot. The code was right and the test was wrong, and the
way it was wrong is worth recording.

The proof read "is the flash lit?" from **`plyPresEnable`**. That bit is the AND
of two independent things — the flash running *and* the ship being visible —
and `plyVisible` is driven by the invulnerability blink. The blink runs **four
frames dark, four lit: period 8. `WPN_FIRE_PERIOD` is also 8.** They
**phase-lock**: once the player is invulnerable, every shot lands on the same
phase of the blink, so the first frame of *every* flash is dark and the second
lit. That is indistinguishable, through the enable bit, from a flash that is one
frame short.

It had passed twice before only because the player happened not to be
invulnerable across the measurement window.

Two repairs, both strengthening:

1. **Measure the flash, not the AND.** "Lit" now reads HW1's published
   *pointer* off the blank block — the flash's own behaviour, which the blink
   cannot mask.
2. **Tie the two back together explicitly**, per frame: HW1's enable must equal
   *flash AND visible* on every single frame of the capture. That is a stronger
   statement than the original, and it is the one that would catch a real
   regression in either direction.

The window also now clears `plyInvuln` before measuring, with the phase-lock
written down next to it, so the measurement is not silently confounded by a hit
the player took seconds earlier.

### 9.4 The gate is RED, and it is not this change

`make test` failed on **both** attempts after the hull-flash removal. I am
reporting that as a failure rather than a footnote. It is not this change, and
here is the evidence rather than the assertion:

| run | failed on | re-run standalone, same binary |
|---|---|---|
| gate #1 | encounter director: *two wave instances active concurrently* | **3/3 PASS** (streak 5 each) |
| gate #2, #3 | production: *one pixel per frame* — `moved 4 px in 5 frames`, `mismatches [(1, 0)]` | **4/4 PASS** |

Two *different* suites failed on different attempts, and each passes repeatedly
on the identical binary. Neither touches anything this change reaches: the
movement check exercises `playerTick`, which was not modified, and the wave
check exercises the encounter director, which was not modified.

**The movement failure is a known one.** It has the exact signature investigated
earlier in this work — `x 161 -> 165`, `moved 4 px in 5 frames`,
`mismatches: [(1, 0)]` — and was proven pre-existing then. A coherent-sampling
guard was landed for it (`coherent()` in `test_production.py`, which re-reads
`frameCounter` either side of `plyX`). **That guard is insufficient.** It
detects a read *torn* across a frame boundary, but not a sample taken at a
different *phase* — after the frame counter has advanced but before `playerTick`
has moved the player that frame. `(1, 0)` is exactly that: one frame elapsed,
nothing moved. A single phase slip loses one pixel permanently, which is why the
total comes out 4 rather than 5.

One more thing worth knowing: it fails **inside `make test` (2 of 2)** and
passes **standalone (4 of 4)**. That is load-dependence in the harness, not
randomness — the monitor's read timing relative to the emulator shifts when the
machine is busier.

**I have not fixed it, deliberately.** Anchoring that sampler means changing a
gate acceptance check for a reason that has nothing to do with your request, and
the standing rule here is not to touch hard acceptance criteria to make a suite
go green. It is a contained fix — break after `playerTick` rather than at
`gameFrame` entry, so the counter and the position are always in the same phase
— and I will do it as its own piece of work if you want it.

### What this change itself is proved by

`tests/test_player_ship.py`, run **three times, ALL PASS every time** — three
runs rather than one because the assertion I had to repair (below) was one that
had passed twice by luck.

**Renderer health:** every counter zero on all three runs, with the twin-gun
art live and the hull flash gone.
No page/pointer mismatch, no publication skip, no missed frame, no late split.
The change adds no new register write and no raster work — the flash rides the
presentation block the renderer already publishes, and the replacement art
costs exactly the same five blocks the old art did.

---

## 10. What to look at in manual play

```sh
cd /Volumes/SSD/dev/C64/6502-shmup
make run
```

| # | Look for | Expected |
|---|---|---|
| 1 | **fire once** | **two** bold red flares with white-hot cores, one at each wing gun, gone in two frames |
| 2 | **hold fire** | one pair of flares per shot at the existing rhythm — **not** a sprite that sits there lit |
| 3 | **the colour** | flat red under a white-hot core, the same on both frames — the orange/red pulse is **gone**, per the asset header. If you wanted the pulse kept, say so and it is a two-line revert |
| 4 | **bank and fire** | **the most important check.** The two flares stagger as the craft leans — one rides forward, one drops back. Check hard left and hard right especially |
| 4b | **the new boldness** | the flares are roughly twice the lit area of the previous pair and reach above the nose. Judge whether that reads as punchy or as too much at 50 Hz |
| 5 | **the registration** | each flare should sit **on its own gun barrel**, not beside it or floating off the wing. Proven true frame by frame against your art, but the eye is the judge at 50 Hz. `PLAYER_FLASH_Y_LIFT` is the one number if it needs nudging |
| 6 | **the ship itself while firing** | **the hull must not change colour at all.** This is the behaviour that was removed — the craft used to redden on every shot |
| 6b | **the ship when HIT** | still blinks. Taking damage is the only thing that changes the craft's appearance now, which is the point of removing the other one |
| 7 | **fire while banking hard at a screen edge** | no wrap or tear, and **neither** flare clipped — the 9-bit X is shared with the hull |
| 8 | **fire while invulnerable** (take a hit, keep firing) | the flares blink with the ship rather than staying lit through the dark frames |
| 9 | **enemies, turrets, HUD, terrain** | unchanged, and still hires |
| 10 | **a minute of play** | no flicker or corruption attributable to the new sprite |

Checks 3 and 4b are the most likely to want tuning, and both are cheap:
`PLAYER_COL_FLASH` / `PLAYER_FLASH_TIME` for the colour and duration, and the
art itself for the boldness. The lift is proven correct against the art, so a
wrong-looking *height* would more likely mean the art wants moving than the
constant.

**One cosmetic thing to know about:** the supplied file's header line still
reads `player_muzzle_flash_twin_bold.asm` while the file is checked in as
`player_muzzle_flash.asm`. I left the asset **exactly** as delivered rather
than edit a supplied file, so this is yours to change or leave. It affects
nothing — the assembler never reads it.

---

## 11. Hygiene

- `pgrep -fl x64sc` inspected before each automated session; clear afterwards.
  Each art swap launched and reaped exactly one emulator: pid 45253, then
  pid 47098 for the bold pass.
- Every emulator `-console`, owned by exact PID, reaped on every exit path. No
  broad `pkill`, no `open -a`, no window, no focus theft, no `-default`,
  `+saveres` retained, no joystick overrides, no persistent VICE setting
  touched.
- Background tasks awaited by notification, not polled.
- Transient logs under `/tmp`, removed.

```
du -sh build/   ->   84K
du -sh .        ->   4.3M
```

---

## 12. Git

```
 M Makefile
 M src/enemy.asm
 M src/main.asm
 M src/player.asm
 M src/renderer.asm
 M src/scroll.asm
 M src/weapon.asm
 M tests/test_production.py
?? reports/player-blue-ship-integration.md
?? src/mnt/
?? src/player_art.asm
?? src/player_muzzle_flash.asm
?? tests/test_player_ship.py
?? tools/
```

**Nothing was committed, pushed, staged or tagged.**

Most of that tree is the previous task's work, still uncommitted and preserved
untouched. This task's own changes are `src/player.asm`, `src/weapon.asm`,
`src/main.asm`, `src/player_muzzle_flash.asm`, `tests/test_player_ship.py` and
`tests/test_production.py`.

---

*Removing the hull flash left the feature simpler than it found it: one timer
fewer, one branch fewer in `playerEmit`, two deletions in the weapon, and a
proof that now measures the flash itself rather than the flash AND the blink.
The craft's own `$d027` is, for the first time, never written by firing at all.
Allocation, trigger, cadence, `$d01c` and every register outside `$d028` are
exactly where they were four revisions ago. The
flash rides infrastructure that was already there: HW1 has been reserved,
co-located and plumbed through `plyPresPtr1`/`plyPresCol1`/`plyPresEnable` to
`$d028` and `$d015` since the ship became one multicolour sprite, and the
renderer already wrote the player's `$d01c` bits from a single constant in both
phases. What this task added is one byte of state, a trigger on the weapon's
own accepted-shot event, and five blocks of supplied art — and the weapon never
learned that any of it happened.*
