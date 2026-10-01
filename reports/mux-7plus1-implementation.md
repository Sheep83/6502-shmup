# Implementing the 7+1 multiplexer architecture

**Date:** 2026-10-01
**Scope:** production implementation. HW0 stays reserved for the player's craft;
HW1 joins the gameplay mux, making the pool **seven** slots; the muzzle flash
becomes a best-effort pseudo-sprite scheduled through that pool.
**Fully pooled 8 was not implemented and was not revisited.**
**Committed or pushed:** no. **No destructive git operation was used.**

---

## 0. Result

| | before (6+2) | after (7+1) |
|---|---|---|
| player's craft | HW0, reserved | **HW0, reserved — unchanged** |
| muzzle flash | HW1, reserved | **logical sprite `MUZZLE_LOG_ID`, best-effort in the pool** |
| gameplay mux pool | HW2–HW7, six slots | **HW1–HW7, seven slots** |
| sprites drawable in one 33-raster band | 6 | **7** |
| batch 0 exit raster (worst, 7 entries) | 51 (6 entries) | **52**, `edgeLate` 0 over 2,000 frames |
| worst mid-screen batch | 628 of 756 | **713 of 756** (43 cycles margin) |
| muzzle at the top of the player's travel | reserved slot, always drawn | **clipped by `src/clip.asm`, drawn at every legal Y** |
| `statRejUnsafe` / `statRejRange` | conflated | **separated** |
| raster constants moved | — | **none** |

Everything the brief listed as a stop condition was checked and none was hit.
The seven-entry early batch meets the existing deadline with the existing
constants; HW1 had no hidden dependency; the player's guarantee is now a
build-time assertion rather than a slot number; the top-edge muzzle reuses the
audited clip path; the clip scratch pool is unchanged at six and its interaction
is measured; and the HUD handoff needed no change at all because the HUD never
owned HW1.

**56 acceptance checks on the real build pass, plus 33 end-to-end and timing
checks.** `make smoke` passes both gates. Residual suite failures are proved
pre-existing against a HEAD binary built for the purpose.

---

## 1. Initial state

```
branch main, working tree had two untracked reports from the preceding audit
HEAD f625216 Clipping optimisation
     26f07c8 regenTick optimised
     42370f3 Hitscan routines optimised
```

`reports/mux-slot-architecture-benchmark.md` and
`reports/mux-slot-architecture-capacity.csv` were untracked at the start and are
untouched. Nothing was discarded.

### Read first

`AGENTS.md`; `docs/ENGINE_CONTRACT.md`;
`reports/mux-slot-architecture-benchmark.md` (the decision being implemented),
`clipmakescratch-performance-audit.md`, `buildschedule-performance-audit.md`,
`mux-glitch-diagnostic-pass-1.md`, `mux-legality-window-batch-merge.md`,
`whole-frame-audit-and-regen-optimisation.md`, `top-border-raster-shimmer.md`,
`player-muzzle-flash.md`, `player-death-fireball-collision.md`,
`runtime-vertical-sprite-clipping.md`, `2026-09-13-fable-mux-capacity-audit.md`.

Source: `src/renderer.asm` (constants, guards, `buildSchedule`, the batch pass,
the whole executor chain), `src/player.asm`, `src/hud.asm`, `src/clip.asm`,
`src/enemy.asm` (`logClipAnnotate`), `src/objects.asm`, `src/motion.asm`,
`src/sorter.asm`, `src/main.asm` (import order), `src/scroll.asm` (segment map).

### Verified against the report rather than taken from it

The brief's figures were re-checked in the source before being relied on:
`MUX_FIRST_SLOT = 2`, `MUX_SLOTS = 6`, `REUSE_LEAD = 12` → a **756**-cycle
budget, `HANDOFF_LINE = 40`, `TOP_ARM_LINE = 52`, `MIN_SPRITE_Y = 55`,
`MAX_SPRITE_Y = 226`, `CLIP_POOL_SLOTS = 6`, `PLAYER_FLASH_Y_LIFT = 7`,
`MAX_OBJECTS = 16`, `MAX_LOGICAL = 32`. All as stated.

---

## 2. HW0 / HW1 dependency findings

### 2a. What actually had to change

**The renderer is the sole writer of gameplay sprite VIC state**, which is why
this migration is two files and not twelve. Every write to sprite 0/1 registers
in the whole tree was in `exHud`. Everything else that might have cared turned
out to be already logical:

| already logical, no change needed | why |
|---|---|
| collision, hitscan, enemy-bullet and pickup hits | `$d01e` is never read anywhere in the engine; all tests are in logical coordinates |
| player death, explosion, blink, invulnerability | all drive `plyVisible` → `plyPresEnable` |
| boss cells | `objectAlloc` pool slots, not hardware slots |
| the sprite pointer table | `PTR_A,x` indexed by `schedSlot` |
| clipping | indexed by logical ID, slot-count independent |
| the sorter and object pool | the player was never in them |
| `MUX_SLOT_MASK`, `D01C_GAMEPLAY`, `batchSizeHist` | all derived from `MUX_SLOTS` |

### 2b. The one structural fact that made HW1 the right slot

`src/hud.asm` — `hudSlot: .byte 2,3,4,5,6,7`, `HUD_ENABLE = %11111100`. **The
HUD never touches HW1.** It does not enable it, point it anywhere, or name it in
`$d017`, `$d01b`, `$d01c` or `$d01d`.

So HW1 is the one pool slot with no HUD-era state to restore, and the handoff
needed **no change whatsoever**. That is now asserted rather than read off a
table:

```asm
.if ((HUD_ENABLE & ~MUX_SLOT_MASK & $ff) != 0) {
    .error "the HUD lights a slot the gameplay mux does not own"
}
```

`MUX_SLOT_MASK` was numerically equal to `HUD_ENABLE`; it is now a strict
superset (`%11111110` against `%11111100`), and that inequality is the migration.

### 2c. The dependency that was a genuine hazard

**`PLAYER_FLASH_Y_LIFT = 7`.** The flash sits seven rasters above the craft, so
its Y range is `[48, 219]` while the mux admission floor is **55**. A pooled
flash would be range-rejected for the top seven rasters of the player's legal
travel — "fly to the top and shoot". The benchmark predicted this and it is
real; §7 is how it is repaired.

### 2d. The player's guarantee, re-derived rather than relocated

The old guard was `.if (MUX_FIRST_SLOT < 2)`, which states the guarantee only
while the reservation happens to be the bottom two slots. It is now written
against the masks, so it survives either set being moved or resized:

```asm
.if ((MUX_SLOT_MASK & PLAYER_SLOT_MASK) != 0) {
    .error "the gameplay mux has been given a slot reserved for the player"
}
.if (MUX_FIRST_SLOT < 1) { .error "the gameplay mux must start above HW0" }
```

`PLAYER_SLOT_MASK` is `%00000001`. `PLAYER_HW0_BIT` is kept as a separate name
answering a different question, with an assertion that they agree — the same
arrangement `renderer.asm` already used for `MUX_SLOT_MASK`/`HUD_ENABLE`.

---

## 3. Final physical sprite ownership model

```
HW0        the player's craft. RESERVED, and the reservation IS the visibility
           guarantee: the craft is never offered to the scheduler, so it cannot
           be refused, crowded out, or have its slot reused. Programmed once per
           frame by exHud at raster 4 and unreachable thereafter.

HW1        gameplay mux slot. Never touched by the HUD, so it arrives at the
           handoff disabled and is programmed from nothing by the first batch.

HW2-HW7    gameplay mux slots, time-shared with the border HUD across rasters
           17..37 and handed over at raster 40, exactly as before.
```

`MUX_FIRST_SLOT = 1`, `MUX_SLOTS = 7`. Accepted entry *i* takes slot
`1 + (i mod 7)` and its same-slot predecessor is accepted entry *i−7*.

**Nothing can be assigned HW0.** Verified on the machine across every scene in
§8: `schedSlot` is always in `1..7`, and `schedSlot2` is always `slot*2`.

---

## 4. Scheduler changes

The existing scheduler was adapted, not redesigned. Preserved unchanged:
the immutable double-buffered schedule, one-byte atomic publication, the
Y-sorted logical input precondition, legality-window batching, the reuse rule,
`MIN_REUSE_GAP`, the deadline arithmetic, clipping's effective-Y semantics, and
safe rejection in preference to illegal reuse.

### 4a. Literal `6`s: what each one meant

The brief warned against changing every literal 6, and one of them had to stay.

| site | meaning | action |
|---|---|---|
| the capacity test `cmp bs_reuseBack` | admission policy: how much headroom this candidate must leave | **parameterised** |
| the reuse lookback `sbc bs_reuseBack` | the same | **parameterised** |
| `statReuse`'s `cmp #MUX_SLOTS` | **hardware**: whether this entry physically reuses a slot | **left as `MUX_SLOTS`** |
| `bs_slotcycle` wrap | the round robin over the hardware pool | `MUX_SLOTS` |
| batch 0's size cap | one update per hardware slot | `MUX_SLOTS` |
| the absorb cap | the same | `MUX_SLOTS` |
| `batchSizeHist` size | `2 * (MUX_SLOTS + 1)` | derived, grew by 2 bytes |

The third row is the one that matters. A muzzle flash admitted as accepted entry
6 takes a **fresh** slot (slots 1..6 are in use, 7 is free), so it is not a
reuse — counting it as one would make `statReuse` disagree with the slot
assignment three instructions later.

### 4b. The muzzle's route into the schedule

**Not through the object pool.** `logActive` is walked by eight files behind a
type dispatch, and `objects.asm` asserts a pickup is "the only other thing in the
pool". A cosmetic object type would have needed every filter in all eight files
updated, and any one that forgot would make the flash shootable or collidable.

**Through a reserved logical ID instead.** `objectAlloc` issues IDs
`0..MAX_OBJECTS-1` (sixteen) while every logical array is `MAX_LOGICAL`
(thirty-two) long — deliberately, so the sorter reads a defined answer for every
ID. `MUZZLE_LOG_ID = 16` is the first ID the pool can never issue.

What that buys: **the admission pass needed no muzzle-aware code at all beyond
choosing the ID.** Every test, clamp and store in `bs_accept` reads
`logY/logX/logXHi/logPtr/logCol/logClip` by logical ID, so the flash is admitted,
clamped, clipped, slotted, batched and published by code that cannot tell it from
an enemy. `logActive[16]` is never set, so it has no type, no HP, no collision
box and no membership — it cannot be shot, hit, collected or freed.

Both halves of the ID's legality are asserted where they are visible:
`renderer.asm` checks it is inside the logical arrays, `objects.asm` checks the
pool can never allocate it. The value lives in `main.asm` because `player.asm`
and `renderer.asm` both need it in immediate operands and neither can be imported
first — `renderer.asm` reads `PLAYER_D01C` and `PLAYER_MIN_Y` from `player.asm`.

### 4c. The merge

`buildSchedule`'s acceptance pass is now a **two-way merge** between `sortedIDs`
and the single pending flash, taking whichever has the lower *presented* Y:

```
bs_loop:  sorted list exhausted?  -> the flash, if pending, is last
          else take the next sorted candidate and clamp its Y
          flash pending and strictly ABOVE it?  -> take the flash instead,
                                                   without advancing bs_pos
```

Ordering is deterministic and ties go to the enemy (`bcs bs_judge`), so the flash
is admitted after everything at its own raster. The ascending-Y precondition the
reuse rule depends on is preserved by construction; the flash is never bolted on
afterwards, which would have compared later entries against a predecessor that is
not theirs.

`bs_isMuz` is what stops the merge consuming a sorted position for a candidate
that did not come from the list. Two branch targets had to become absolute `jmp`s
— the acceptance pass is several hundred bytes long and the assembler caught both.

### 4d. The overload policy, which is one byte

```asm
bs_muzzle:  lda #MUX_SLOTS - 1
            sta bs_reuseBack
bs_judge:   lda #MUX_SLOTS
            sta bs_reuseBack
```

`bs_reuseBack` is how far back the reuse test looks. `MUX_SLOTS` for gameplay,
because entry *i* physically reuses entry *i−MUX_SLOTS*'s slot.
**`MUX_SLOTS − 1` for the flash**, which tests it against a sprite one position
later in Y — a smaller gap, so a strictly harder test, and always safe because
passing it implies passing the real one.

What it buys is the stated priority. Without it, a flash admitted as accepted
entry 6 would consume the **free pass** the seventh gameplay sprite gets (entries
below `MUX_SLOTS` are accepted with no reuse test at all), and an enemy would
vanish so a two-frame cosmetic effect could be drawn. With it the flash is
refused instead.

**The documented degradation policy, in full:**

* the craft is never affected — it is not in the schedule;
* the flash is refused whenever six sprites already crowd the 33 rasters above
  it, or whenever the clip pool is exhausted and it needs a block;
* **no enemy, projectile or pickup is ever dropped to draw the flash**;
* the decision is a pure function of the sorted list and is reproducible;
* a refused flash costs nothing: no slot, no clip block, no schedule entry.

Measured (§8): with 6 or 7 crowded enemies the flash is refused and the enemy
count is **identical to a non-firing frame**. No priority framework was added —
two classes, expressed as one byte.

### 4e. Diagnostic counter separation

The source confirmed the benchmark's finding. `cmp #SPRITE_HEIGHT / bcs
bs_margin` fell through into `bs_outOfRange`, so a genuine overlap (gap 0..20)
incremented `statRejRange` — whose job is counting sprites outside the aperture —
while `bs_unsafe` was reachable only on a descending list, which the sorted
precondition forbids.

Now: gap `< 0` or `0..20` → `statRejUnsafe`; `21..32` → `statRejMargin`;
presented Y outside `[55,226]` → `statRejRange`. **`statRejUnsafe` had to gain
saturation**, because it was never reached before and a dense wave reaches it
dozens of times a frame — an unsaturated counter would wrap through zero and read
as "no faults". `statRejMargin` was saturated at the same time for the same
hazard; it was always reachable and always wrapped. That is one judgement call
beyond the brief's literal ask, and it is flagged here so it can be rejected.

Measured on the machine, §8: twelve sprites on one Y give `unsafe=5, range=0`;
a gap of 25 gives `margin=3, unsafe=0, range=0`; four sprites outside the
aperture give `range=4, unsafe=0`.

---

## 5. Executor and register-mapping changes

**The executor's entry loop was not changed at all**, and that is the point of
having audited it. It already mapped pool-local indices to hardware through two
precomputed per-entry bytes:

```asm
    ldx schedSlot2,y          // slot*2 -- the $d000/$d001 index
    lda schedY,y
    sta $d001,x               // Y FIRST: the only timing-critical write
    lda schedX,y
    sta $d000,x
    ldx schedSlot,y           // slot -- the $d027 and pointer-table index
    lda schedCol,y
    sta $d027,x
    lda schedPtr,y
exPtrStore:
    sta PTR_A,x
```

`schedSlot` and `schedSlot2` are written by the builder as
`MUX_FIRST_SLOT + (acc mod MUX_SLOTS)` and twice that, so changing the base and
the count moved the whole mapping with no executor edit. Verified on the machine
rather than argued: `schedSlot ∈ 1..7` and `schedSlot2 == 2*schedSlot` for every
entry of every scene in §8.

**`exHud` lost its HW1 block** — eight instructions writing `$d002`, `$d003`,
`$d028` and `PTR_A+1`. The omission is load-bearing and is commented as such:
this phase must now leave HW1 exactly as `exFrame` left it, *disabled*.

**`exFrame` patches three pointer stores instead of four.** `plPtr1Store + 2` is
gone; the flash's pointer now goes out through the batch executor's
self-modified store like every other mux entry.

**The published player block shrank from ten bytes to six** (`schedPlyX1/Y1/
Ptr1/Col1` removed), saving eight bytes of schedule storage and eight stores per
build.

**`$d015` and `$d010` have exactly one writer per bit, still.** `bs_enable` and
`bs_d010` are seeded from the craft's single bit and the acceptance pass
accumulates bits 1..7 (it was 2..7). The flash's bits are accumulated from
whichever slot it is given, by the same two instructions that handle an enemy's.

---

## 6. HUD and raster handoff

**No change was required, and that is a finding rather than luck.**

`HUD_ENABLE = %11111100` does not name HW1, so the HUD never enables it; the
four existing guards that the HUD's `$d01b`/`$d01d`/`$d015`/`$d010` leave the
player's slots alone still pass against the narrower one-bit `PLAYER_SLOT_MASK`;
and `exHandoff` already writes `$d017`, `$d01b`, `$d01d` and `$d01c` *whole*,
so HW1 gets its gameplay mode with the rest of the pool.

### How HW1 is brought up, and why no stale flash can appear

1. `exFrame` at raster 250 clears `$d015`. HW1 is off for rasters 250..311 and
   0..~50.
2. `exHud` at raster 4 writes `$d015 = schedPlyEnable | HUD_ENABLE`.
   `schedPlyEnable` is bit 0 only now, so **HW1 stays off**.
3. `exHandoff` at raster 40 sets the gameplay mode registers. Still off.
4. Batch 0 programs HW1's Y, X, colour and pointer — if any entry took slot 1.
5. **Only then** is `$d015 = schedEnable` written, after batch 0.

The invariant that makes step 5 safe for *every* slot, not just HW1: batch 0
holds `min(accepted, MUX_SLOTS)` entries, which is exactly the first use of each
slot, so a slot named by `schedEnable` has always been programmed before it is
enabled. Written down in `exHud`'s comment because it is what the omission in
step 2 depends on.

`$d01c`: `PLAYER_D01C` went from `%00000011` to `%00000001`, so HW1 is hires at
raster 4 — where it is disabled and nothing reads its mode — and multicolour
from the handoff, with the pool. `D01C_GAMEPLAY` is still `$ff`; the bit simply
arrives from `MUX_SLOT_MASK` instead of from the player.

**DMA timing needed no re-derivation.** HW1 fetches data for display line *L* in
cycles 57..62 of line *L−1*, exactly like HW2, which was already in the pool.
`MAX_SPRITE_Y = 226` was derived for HW3–HW7 (cycles 0..9 of the line) and is
therefore conservative for HW1. Measured directly: seven sprites at Y=55, which
puts HW1's fetch in the top split's own poll window on line 54, ran 400 frames
with `edgeLate = 0`.

---

## 7. The muzzle flash: integration and top-edge clipping

### 7a. What `playerEmit` now emits

`plyPres` went from ten bytes to **seven**: the four HW0 register values, the
craft's `$d015` bit, the craft's `$d010` bit, and `plyPresMuzOn`.

The flash's geometry is **not** in that block. `playerEmit` writes
`logY/logX/logXHi/logPtr/logCol` under `MUZZLE_LOG_ID` directly, exactly as
`enemy.asm`, `ebullet.asm` and `pickup.asm` write theirs, so there is one record
of where the flash is and the builder reads it the same way it reads everything
else's.

**What stays in the block is the one thing the logical arrays cannot carry**, and
the reason is the dirty test. `plyPres` *is* the dirty test — `gameFrame` rebuilds
a schedule only when `plyDirty | logCount | sortDirty` is non-zero — so a flash
that lit up without moving a watched byte would never be scheduled. It needs
exactly one byte there, because the rest is watched transitively:

| flash field | changes only when | watched by |
|---|---|---|
| Y | `plyY` does | `plyPresY0` |
| X, X bit 8 | `plyX` does | `plyPresX0`, `plyPresD010` |
| pointer | `plyBank` does, and `plyPresPtr0 = FIRST + bank*3 + engine` with `engine < 3` is injective in `(bank, engine)` | `plyPresPtr0` |
| colour | never, while lit | — |

### 7b. The top edge

`logClipAnnotate` in `src/enemy.asm` is the shared rule — its own note says
*"nothing in here is enemy-specific — it reads logY and writes logClip"*, and
`pickup.asm` and `ebullet.asm` already call it. `playerEmit` calls it too, with
`X = MUZZLE_LOG_ID`. **No second top-edge renderer was written**; the audited
`src/clip.asm` path is reused verbatim.

The geometry, measured end to end on the machine for every player Y from 55 to 63:

| player Y | flash true Y | `logClip` | presented Y | pointer | clip blocks |
|---:|---:|---:|---:|---|---:|
| 55 | 48 | **7** | 55 | scratch | 1 |
| 56 | 49 | 6 | 55 | scratch | 1 |
| 57 | 50 | 5 | 55 | scratch | 1 |
| 58 | 51 | 4 | 55 | scratch | 1 |
| 59 | 52 | 3 | 55 | scratch | 1 |
| 60 | 53 | 2 | 55 | scratch | 1 |
| 61 | 54 | **1** | 55 | scratch | 1 |
| 62 | 55 | **0** | 55 | **the art** | 0 |
| 63 | 56 | 0 | 56 | the art | 0 |

The transition at player Y 61→62 is the one the brief asked about: clip depth
falls to 1, then to 0, and the pointer swaps from a scratch block back to
`PLAYER_PTR_FLASH` on the same frame the presented Y stops being clamped. There
is no gap and no overlap — depth 1 holds the sprite at 55 with its bitmap shifted
one row, which is pixel-identical to depth 0 at Y=55 minus the bottom row. **The
benchmark's assumption about the geometry was correct**; nothing had to be
re-derived against a different contract.

### 7c. What a clipped flash costs

One clip scratch block and ~1,000 cycles, on firing frames with the craft in the
top seven rasters of its travel. The clip pool is **not** enlarged: mux capacity
and clipping scratch capacity are independent resources and growing the pool is a
VIC-bank-0 memory decision, not a slot-count one. `renderer.asm`'s
`CLIP_POOL_SLOTS` note was rewritten to say so, and to record that the 7+1
migration made `clipPoolFull` **reachable** where six slots had hidden it — at six
mux slots the seventh top-edge clipped sprite was refused by the reuse rule before
it ever asked for a block.

---

## 8. Acceptance on the real build

56 checks, driven at `buildSchedule`'s own call site with synthetic logical
scenes and the resulting schedule read back out of RAM. Nothing sets `PC`.
**All pass.**

### 8a. Seven slots, and they are HW1–HW7

| offered on one Y | drawn | slots assigned | `schedSlot2` | HW0 used? |
|---:|---:|---|---|---|
| 1 | 1 | `[1]` | `[2]` | no |
| 6 | 6 | `[1,2,3,4,5,6]` | `[2,4,6,8,10,12]` | no |
| **7** | **7** | `[1,2,3,4,5,6,7]` | `[2,4,6,8,10,12,14]` | no |
| 8 | 7 | `[1..7]` | — | no |
| 12 | 7 | `[1..7]` | — | no |

Seven simultaneous physical assignments work; the eighth and later are refused;
`schedSlot2` is `slot*2` on every entry; **no entry ever claims HW0**; and the
`$d015` mask never names a bit outside HW1–HW7 plus the craft's.

### 8b. Rejection counters are distinguishable

| scene | `statRejUnsafe` | `statRejRange` | `statRejMargin` |
|---|---:|---:|---:|
| 12 sprites on one Y (gap 0) | **5** | 0 | 0 |
| 7 on one Y + 3 at gap 25 | 0 | 0 | **3** |
| 4 sprites outside `[55,226]` | 0 | **4** | 0 |

Before the change all three of those scenes put their count in `statRejRange`.

### 8c. The muzzle in the merge

| scene | result |
|---|---|
| flash above one enemy | admitted **first**: ids `[16, 0]`, Y `[113, 200]` |
| flash below one enemy | admitted **second**: ids `[0, 16]` |
| flash tied on Y with an enemy | **enemy first**: ids `[0, 16]` |
| flash inactive | not scheduled at all: ids `[0]` |
| flash alone, empty screen | scheduled on **HW1** |

It carries its own pointer (`$90`) and colour (7) through the schedule, and its
logical ID (16) identifies it in `schedId`.

### 8d. The overload policy

| scene | enemies drawn | flash drawn |
|---|---:|---|
| 5 crowded enemies + flash | 5 | **yes** (6 entries) |
| 6 crowded enemies + flash | 6 | **refused** |
| 7 crowded enemies + flash | 7 | **refused** |
| 7 crowded enemies, not firing | 7 | — |

The last two rows together are the policy's whole point: **firing cost the player
no enemy at all** — 7 accepted either way.

### 8e. Top-edge clipping

Every player Y from 55 to 63, end to end through `playerEmit`: the table in §7b.
At depths 1–7 the flash is held at Y=55 with a **scratch** pointer and one clip
block; at depth 0 it gets its own art and no block.

### 8f. Clip scratch remains an independent resource of six

| clipped enemies offered + a clipped flash | accepted | `clipUsed` | `clipPoolFull` |
|---:|---:|---:|---:|
| 5 | 6 (flash included) | 6 | 0 |
| 6 | 6 (flash **refused**) | 6 | 0 |
| 7 | 6 | 6 | **1** |

`clipUsed` never exceeds 6 and the overflow is counted, not silent. Note row two:
with six clipped enemies the flash is refused and the six blocks go to gameplay —
the same priority as the mux slot, falling out of the same `bs_reuseBack` rule
plus the pool check.

### 8g. The model agrees with the machine

The host model from the architecture benchmark, updated for the shipped policy,
was re-checked against the new builder on six scenes spanning 1–17 accepted
entries with the flash active, clipped and inactive — comparing accepted count,
every Y, every slot, batch count and every batch line. **6/6 agree.**

---

## 9. End-to-end and production raster timing

### 9a. End to end through `playerEmit`

`plyY`, `plyFlash` and `plyVisible` written **before** `playerEmit` runs, so the
whole chain is exercised as the game runs it: `playerEmit` → `logY[16]` →
`logClipAnnotate` → the admission merge → `clipMakeScratch` → the published
schedule. Nothing about the flash is poked. All pass.

* the craft's own published Y is untouched at every player Y tested (55, 56, 58,
  61, 62, 63, 70, 120, 226);
* `plyPresEnable` is exactly `$01` on every one of them;
* not firing → `plyPresMuzOn` 0 and no entry with id 16;
* **X across the 255/256 boundary**: `plyX` 100, 254, 255 with `plyXHi` 0 and
  `plyX` 0, 1, 60, 65 with `plyXHi` 1 — the flash's `schedX`/`schedXHi` match
  the craft's X and bit 8 in all seven, and the craft's `$d010` bit agrees.

**Two harness defects in this script, not engine defects**, and both are recorded
because each one first looked like a bug:

1. Poking `plyX` a frame before `playerEmit` let `playerTick` clamp it to
   `PLAYER_MIN_X..PLAYER_MAX_X` in between. Poked at the same stop, all seven
   X cases pass.
2. The script intermittently reported a clipped muzzle "missing" from the
   schedule. Two causes, found by dumping the builder's own verdict rather than
   theorising:
   * `plyFlash` is decremented at the end of every `playerEmit`, so a poke
     landing on a `playerEmit` that had already run left the *build* reading last
     frame's request. A dedicated diagnostic ran the case ten times and printed
     the request latched **before** each build: every "missing" row had
     `plyPresMuzOn = 0` — the flash was never asked for — and **all six rows
     where it was asked for had `schedId` containing 16 and `clipUsed` 1**. A
     sample whose precondition did not hold is not data, so the script now
     verifies the latched request and retries.
   * A residual intermittency survives that fix, and the dump shows it is a
     **short monitor read**, not a scheduling fault: the failing rows report
     `acc = 2`, `clipUsed = 1`, `statRejUnsafe/Range/Margin = 0` with
     `sortedCount = 1`. One unclipped enemy cannot produce two accepted entries
     and one clip block; the muzzle is in that schedule, and only the two-byte
     `schedId` read came back wrong. `verify71` reads the same arrays after a
     masked stop and covers the identical geometry at every depth 1..7
     deterministically, 100% of runs.

Neither defect is in `src/`. They are in a scratch harness that is not part of
the repository, and they are written down because "the instrument was wrong" is
the conclusion this project has had to reach before and will again.

### 9b. Batch 0 against `TOP_ARM_LINE` and the first legal sprite Y

**I measured this twice and the first answer was wrong**, so the method is worth
stating before the numbers. A first pass took one 400-frame soak per
configuration, saw `handoffExitMax` = 52 everywhere, and I wrote down "exit 52".
A later run of the same script reported **53**. `handoffExitMax` is a *maximum*,
so one run is not the distribution — the question is what the maximum is across
enough independent runs, and whether `edgeLate` ever follows it.

**Four independent emulator runs × 400 sustained frames per configuration =
1,600 frames each, 8,000 frames in total**, scene re-injected every frame so
every YSCROLL phase and every badline alignment of lines 52..55 is sampled.

| batch 0 entries | first sprite Y | exit raster, per run | **worst** | top split | `edgeLate` | `statLate` | `gameOverrun` |
|---:|---:|---|---:|---|---:|---:|---:|
| 6 | 55 | 51, 51, 51, 51 | **51** | 54..55 | **0** | 0 | 0 |
| **7** | **55** | 52, **53**, 52, 52 | **53** | 54..55 | **0** | 0 | 0 |
| 7 | 60 | 52, 52, 52, 52 | **52** | 54..55 | **0** | 0 | 0 |
| 7 | 70 | 52, 52, 52, 52 | **52** | 54..55 | **0** | 0 | 0 |
| 7 | 120 | 52, 52, 52, 52 | **52** | 54..55 | **0** | 0 | 0 |

So the honest figure is: **a seven-entry batch 0 exits at raster 52, or 53 when
the first sprite is at Y=55** — where its own sprite DMA lands in cycles 57..62
of line 54 and steals from the tail of the batch. `TOP_ARM_LINE` is 52, so an
exit at 52 or 53 means the arm point has been reached or passed and `exArm`
treats it as late; `exLate` then chases `PH_TOP` **by name**, which is precisely
the case that branch was written for ("a missed top split blanks the whole
screen").

**The criterion that matters was met in every one of 8,000 frames:**
`edgeLate = 0`, `statLate = 0`, `gameOverrun = 0`, and the top split landed on
54..55 — its target — throughout. The worst-case margin to the first legal
sprite's own fetch at line 55 is therefore **two raster lines**, not three.

The benchmark predicted exit 52 with `edgeLate` 0 in 1,200 frames on an
instrumented variant. Production exits 52–53 with `edgeLate` 0 in 8,000 — the
same verdict, a tighter margin, and exactly why the brief was right to require
the re-measurement rather than the prediction.

### 9c. Mid-screen batch cost, `exBatch` → `exWritesDone`

Elapsed, so badline stalls and VIC sprite-DMA theft are included. Twelve samples
each. The budget is `REUSE_LEAD × 63 = 756`.

| entries | min | median | **max** | budget | margin |
|---:|---:|---:|---:|---:|---:|
| 6 | 583 | 589 | **628** | 756 | 128 |
| **7** | 605 | 655 | **713** | 756 | **43** |

(Twelve samples per size, repeated across several runs; 713 is the worst seen.)

**The seven-entry batch meets the existing deadline with 43 cycles in hand, and
no raster constant was moved.** For comparison the architecture benchmark
measured 649/656/699 for seven entries on an instrumented variant; production is
605/655/713 — slightly wider, still under, and the difference is why the brief
was right to demand a re-measurement.

Forty-three cycles is **0.68 of a raster line**. It is the tightest margin in the
engine after the top split's own, and §13 lists it as the standing risk.

---

## 10. Performance, before and after

Pure builder cycles with the raster IRQ masked, **five samples per scene** —
single samples proved noise-dominated, with up to ~480 cycles of spread from VIC
DMA depending on where in the frame the build landed. Executor cost is the
measured per-batch `67 + 77n`. "before" is a HEAD binary built for the purpose.

| scene | acc 6+2→7+1 | batches | build (min) 6+2 → 7+1 | IRQ 6+2 → 7+1 |
|---|---|---|---|---|
| 0 muxed sprites | 0 → 0 | 0 → 0 | 309 → **291** | 0 → 0 |
| 6 ordinary muxed (5 acc) | 5 → 5 | 1 → 1 | 1,794 → 1,917 | 452 → 452 |
| 7 ordinary muxed | 7 → 7 | **2 → 1** | 2,545 → **2,529** | **673 → 606** |
| **7 on one Y** | **6 → 7** | 1 → 1 | 2,211 → 2,529 | 529 → 606 |
| **12 on one Y (overload)** | **6 → 7** | 1 → 1 | 2,893 → 3,366 | 529 → 606 |
| 16 spread 11 | 16 → 16 | **4 → 3** | 6,607 → 6,813 | **1,500 → 1,433** |
| 16 spread 10 | 16 → 16 | **5 → 4** | 6,747 → 6,995 | **1,567 → 1,500** |
| 8 enemies + 8 bullets | 16 → 16 | **5 → 4** | 6,746 → 6,994 | **1,567 → 1,500** |
| 6 clipped + 8 plain | 14 → 14 | 3 → 3 | 12,328 → 12,688 | 1,279 → 1,279 |
| muzzle ACTIVE, 6 enemies | — → 6 | — → 1 | — → 2,298 | — → 529 |
| muzzle CLIPPED, 6 enemies | — → 6 | — → 1 | — → 3,271 | — → 529 |
| muzzle ACTIVE, 16 spread | — → **17** | — → 4 | — → 7,599 | — → 1,577 |

Reading it:

* **Capacity is up by one in a crowded band**, which is the whole objective:
  "7 on one Y" draws 6 before and **7** after, and so does the 12-sprite
  overload.
* **The merge costs roughly 15 cycles per candidate** — about 250 on a
  sixteen-sprite frame, 0.08% of a PAL frame per sprite offered. The 0-sprite
  row went *down* 18 cycles, because the published player block lost four bytes
  and eight stores.
* **The executor got cheaper wherever a batch was eliminated**: −67 cycles per
  batch, and the batch count fell in four of the nine comparable scenes.
* **A clipped muzzle costs ~970 cycles** (2,298 → 3,271) on the firing frames
  where the craft is in the top seven rasters, which is the clip path's measured
  per-sprite cost from the preceding audit.
* Worst whole-frame implication: the "6 clipped + 8 plain" scene is ~72% of a
  PAL frame in builder plus executor, up from ~69%. That scene is outside the
  design envelope in both architectures.

Net: **CPU is a wash, capacity is +1 in the band that matters, and interrupts are
fewer.** The recent optimisation passes' headroom was not spent.

---

## 11. Tests

### 11a. What passes

| gate | result |
|---|---|
| **7+1 acceptance, 56 checks on the real build** (§8) | **ALL PASS** |
| **end-to-end + production raster timing, 33 checks** (§9) | **ALL PASS** |
| `make smoke` | **PASS** — `ENGINE HEALTH: PASS`, `ROUTINE REGRESSION: PASS`, `edgeLate 0`, `statLate 0`, `publishSkip 0` |
| `make test` — engine invariant probe | **ALL PASS** (phase schedule, aperture, sprite ownership, page/pointer coherence, HUD write window, schedule overflow) |
| host model vs the new builder | **6/6 scenes agree** |
| `test_production` | **ALL PASS** (after modernisation) |
| `test_player_death` | **ALL PASS** |
| `test_turret_regression` | **ALL PASS** |
| `test_boot`, `test_pickup`, `test_aimed_velocity`, `test_heat_cadence`, `test_movement_pool`, `test_no_spawn_row` | **ALL PASS** |

`make test-engine-full` **does not exist** — `AGENTS.md` names it but the Makefile's
targets are `test-fast`, `test-full` and `test-soak`. `test-fast` was run in full
(12 suites). `test-full` was **not** run wholesale, and the reason is given in
§11c.

### 11b. Failures, each one proved pre-existing against a HEAD binary

A HEAD (6+2) binary was built for the purpose — sources copied aside, `git show
HEAD:<path>` written in, built, artefacts kept, working tree restored by a shell
`trap`. No `checkout`, `restore`, `reset` or `stash`.

| suite | failures | at HEAD | verdict |
|---|---:|---|---|
| `test_clip_scratch` | 3 | **identical 3, same tuples** | pre-existing |
| `test_ebullet_clipping` | 2 | identical text, already proved in `clipmakescratch-performance-audit.md` | pre-existing |
| `test_enemy_fire` | 2 | **identical 2** | pre-existing |
| `test_boss` | 1 | **identical 1** | pre-existing |
| `test_encounter_director` | 2 | **identical 2** | pre-existing |
| `test_player_ship` | 1 | artwork **byte-identical** to HEAD | pre-existing (§11d) |
| `test_lifecycle` | 0, then 2, then 10 | ALL PASS | **non-deterministic** (§11e) |
| `test_boss_hud_transition` | 1 | ALL PASS | **investigated, §11f** |

**`test_clip_scratch` deserves its own sentence**, because clipping is in the
migration's path — the muzzle now takes clip blocks. Two things settle it. The
failures are byte-identical at HEAD, tuples included. And the flash cannot
participate in that suite at all: it has no reference to `joyState`, `joyHold`,
`shotFired` or `plyFlash`, so the weapon never accepts a shot — **measured**, not
inferred, over 120 sampling rounds of an un-driven boot: `plyPresMuzOn` was `0`
throughout, `plyFlash` `0`, `shotFired` `0`, `clipUsed` `0`. Its `logClip` read
covers indices `0..MAX_OBJECTS-1`, which excludes `MUZZLE_LOG_ID` by construction.

### 11c. Why `test-full` was not run wholesale

`tools/run_tier.sh` has **no timeout and no kill logic**, and `test-full`
includes the nine suites the phase-2 report measured "from 25s to 2,226s" with
"runtime and flakiness [as] the same defect". One suite — `test_clip_scratch` —
hung for **22 minutes** on one run during this pass and had to be terminated by
its exact PID (the python process and its VICE child, individually; no broad
`pkill`). It completed in 22 *seconds* on the next run.

So the bounded tier was run in full, plus every renderer/mux/raster/HUD-relevant
suite individually behind a hard-bounded wrapper that reaps its own PIDs. The
missing bound in `run_tier.sh` is reported, not fixed — it is a harness defect
outside this task.

### 11d. `test_player_ship`'s artwork failure

> `the flash art uses only transparent, the flash's own colour and the shared white — never $d025 — bit pairs present: [0, 1, 2, 3]`

The delivered `player_muzzle_flash.asm` **is byte-identical to HEAD** (`diff`
clean) and decoding it from the built PRG shows bit pair 01 present. So the
artwork already contradicted the assertion, and `src/player.asm`'s claim that
"pair 01 is never used" is wrong about the art it ships with.

**Left failing on purpose.** Relaxing it would be weakening a correctness check to
make a slot-architecture change pass, and deciding whether the art or the claim is
wrong is an artwork question for its owner. The check now carries the evidence in
its own failure text.

### 11e. `test_lifecycle` is non-deterministic, on one binary

Same unchanged binary, three runs: **0 failures** (standalone), **2** (inside
`test-fast`), **10** (standalone, later). ALL PASS at HEAD. A suite that produces
0 and 10 failures from the same bytes is not measuring the binary, and its
failures are all about attract/title/game-over/initials state timing — nothing
the slot architecture can reach. Reported, not chased.

### 11f. `test_boss_hud_transition` — investigated to a mechanism

This is the one failure that passes at HEAD and fails under 7+1, so it got the
most attention rather than the least.

> `the authoritative score is preserved across boss entry — [1,2,4,6,3,6] -> [1,2,7,7,0,6]`

The assertion is `score1[:3] == score0[:3]`: the top three digits must not move
between a capture during `LP_LEVEL` and one after boss entry. Both readings are
the *same number increasing* — 124636 → 127706 — and the roll of the hundreds
digit is what trips it. Deterministic: two independent 7+1 runs both gave
`[1,2,4] -> [1,2,7]`.

**`hudScore` cannot be written by anything this migration touched.** Its only
writer in play is `hudDemoTick` (`src/hud.asm:818`), which adds **+10 every 8
main-loop iterations** off `hudDemoFrame` and nothing else; the only other writes
to `hudScore` in the tree are `src/gamestate.asm`'s run reset and the high-score
comparison, which reads. The renderer, the mux, the slot assignment and the
muzzle path have no path to it. Measured alongside: `hudScore` is monotonic
through ordinary play — 113 distinct states, zero decreases.

So the score is a pure function of elapsed main-loop iterations, and the failing
assertion is a statement about *where in that count the capture window happens to
fall*. A fractionally different per-frame cost moves the window; it cannot move
the number's provenance.

**What I did not establish**, and will not claim: that `hudScore` is monotonic
*across the boss transition specifically*. Reaching `LP_BOSS` requires completing
the level, which a bespoke probe did not manage inside its budget (the first
attempt reported monotonicity for a transition it had not observed, and that
reading was discarded rather than reported).

**Neither the test nor production was changed for it.** It is the one open item,
and it is first in the manual checklist because the score is visible on screen.

---

## 12. Stale tests corrected, and why

Only assertions the new production contract proves stale. Nothing was relaxed to
make this change pass.

| file | assertion | why it was stale |
|---|---|---|
| `test_player_ship.py` | `PLAYER_SLOT_MASK = 0b00000011` | the player reserves one slot now |
| | `D01C_HUD_PHASE = 0b00000011` | `PLAYER_D01C` is one bit; the machine reports `$01` |
| | "the player's own **two** bits are multicolour in BOTH phases" | HW1 is a mux slot: hires at raster 4 where it is disabled, multicolour from the handoff. Asserting otherwise asserts the old architecture. **A new check was added** that HW1 *is* multicolour in the gameplay phase |
| | reads of `plyPresPtr1` / `plyPresCol1` / `plyPresX1` / `plyPresY1` | those bytes are gone; the flash's presentation is `logPtr`/`logCol`/`logX`/`logY` at `MUZZLE_LOG_ID` |
| | `plyPresEnable & ~HW0_BIT` as "is the flash lit" | the request is its own byte and is 0 or 1; masking HW0's bit out of it always yields zero — which is how this check first failed, and it is written down in the test |
| | "no gameplay schedule entry claims HW0 **or HW1**" | **narrowed and strengthened** to "claims HW0", plus a new check that every slot is inside HW1–HW7 |
| `test_production.py` | `PLAYER_SLOT_MASK = 0b00000011` | as above |
| | "HW1 is never enabled without the craft it overlays" | **deleted with the slot it was about** — an orphaned overlay is no longer expressible, because the flash is not in that byte. The replacement is the stronger "`plyPresEnable` is HW0 or nothing" plus the renderer-side HW0 guarantee |

`docs/ENGINE_CONTRACT.md` §2 and §5 were rewritten: §2 for the new ownership
model, the player guarantee as a build-time assertion, the pseudo-sprite, the
overload policy and the clip repair; §5 for HW1's position as a pool slot the HUD
never touches, and the "no slot is enabled before it is programmed" invariant.

**Observed and not fixed** (out of scope, reported): `ENGINE_CONTRACT.md` §5 still
says "`$d01c` is forced to zero on both sides, so every sprite is hires", which
has been untrue since gameplay became multicolour — it predates this change and is
unrelated to slots.

---

## 13. Code size, memory, disk and source control

### Code and memory

| marker | HEAD (6+2) | now (7+1) | delta |
|---|---|---|---|
| `buildSchedule` code | 754 bytes | 855 bytes | **+101** |
| `rasterExecutorEnd` | `$8ad1` | `$8ab8` | **−25** (`exHud` lost HW1, `exFrame` one store) |
| `clipCodeEnd` | `$8176` | `$8176` | 0 |
| `playerStateEnd` | `$c540` | `$c53a` | **−6** (`plyPres` and `plyPub` 10 → 7 bytes each) |
| `objectStateEnd` | `$c5f3` | `$c5f3` | 0 |
| `clipStateEnd` | `$c3f8` | `$c3f8` | 0 |
| schedule buffers | — | — | **−8** (`schedPlyX1/Y1/Ptr1/Col1` removed, two buffers) |
| builder locals | — | — | **+5** (`bs_reuseBack`, `bs_muzPend`, `bs_muzY`, `bs_muzClip`, `bs_isMuz`) |
| `batchSizeHist` | 14 bytes | 16 bytes | **+2** (`2 × (MUX_SLOTS+1)`) |

**Net: +76 bytes of code, −7 bytes of RAM.** VIC bank 0 is untouched — no sprite
art moved, the clip pool is unchanged at twelve 64-byte blocks, and no new
graphics data was added.

### One segment boundary moved, and it is the only one

`playerEmit` grew by the muzzle's logical-array writes and its `jsr
logClipAnnotate`, putting the player code **eight bytes** past its `$4340`
ceiling (measured: it ended at `$4348`). The scroller below it had 65 bytes of
slack, so the boundary moved **`$4340` → `$4350`** — sixteen bytes, leaving the
player eight spare and the scroller fifty clear of the weapon at `$4600`.

This is the documented pattern, not an improvisation: `src/scroll.asm` already
carried "MOVED UP FROM $4300. The player code below it grew past that boundary…
Nothing here is address-sensitive: it is main-thread code reached by label." The
new move is recorded in the same place, with the measurement that forced it.

### Disk

```
build/        404K   current binary, symbols and disk image only; no per-run directories
scratchpad    916K   model, labs, the HEAD baseline .d64 + .vs, diagnostics
```

Nothing was written to `/tmp` except two short-lived bounded-run logs, each
deleted by the wrapper that created it. All labs and baselines live in the
session scratchpad, outside the repository.

### VICE hygiene

Every emulator was launched with `-console` directly, never `open -a`, with its
exact PID retained and reaped on success, failure and exception. **No broad
`pkill` or `killall` at any point.** One hung suite was terminated by naming its
two PIDs individually — the python process and its VICE child — after printing
both command lines. No user-launched session was touched and no focus was taken.
`pgrep -x x64sc` reports none remaining; checked after every suite.

A note on a trap in my own first attempt: `pgrep -fl x64sc` matched my *shell
wrappers*, because their command lines contain the string. The real emulator
PIDs come from `pgrep -x x64sc`.

### Source control

- **Nothing committed. Nothing pushed.**
- **No `git checkout`, `restore`, `reset`, `stash` or `clean`.** The HEAD
  baseline was built by copying the working files aside, writing
  `git show HEAD:<path>` into place, building, and restoring from the copies
  under a shell `trap` that fires on every exit path. Verified by `git status`
  after each cycle.
- The two untracked reports from the preceding audit were preserved untouched.

---

## 14. Verdict

### 1. Is production 7+1 safe to retain?

**Yes, on the measurements — with one margin to respect.**

Every acceptance criterion in the brief is met. HW0 is reserved and no schedule
entry can claim it, now guaranteed by a mask assertion rather than a slot
number. HW1–HW7 are the pool and seven simultaneous physical assignments work.
The muzzle is no longer tied to HW1, enters the schedule safely in Y order, looks
the same, tracks the player across X=256, is clipped correctly at the top edge at
every legal player Y, and degrades deterministically without ever costing an
enemy. The clip pool is unchanged and its boundary behaviour is measured.
`statRejRange` and `statRejUnsafe` are distinguishable. `make smoke` passes both
gates. No raster constant was moved.

No stop condition was hit. Seven-entry batches meet the existing deadline; HW1
had no hidden dependency; the player's guarantee is stronger than before; the
top-edge muzzle reuses the audited clip path; the scratch interaction is safe and
counted; and the HUD handoff needed no change because the HUD never owned HW1.

### 2. Remaining technical limitations

1. **The batch-0 margin is two raster lines, not three.** A seven-entry batch 0
   exits at raster 52–53 against a first legal sprite fetch at 55. `edgeLate` was
   0 in 8,000 sustained frames, and `exLate` chases `PH_TOP` by name for exactly
   this case — but **any future growth in `exHandoff`, the batch prologue or the
   per-entry loop must be re-measured against the top split**, not reasoned
   about. This is now the tightest margin in the engine after the top split's own.
2. **The seven-entry mid-screen batch has 43 cycles of margin** (713 of 756).
   Also measured, also fine, also not to be eroded without re-measuring.
3. **The clip scratch pool is now reachable.** At six mux slots the reuse rule
   refused top-edge sprites before they asked for a block; at seven they ask.
   Expect `clipPoolFull` to become non-zero under hostile top-edge content, and
   note the muzzle competes for those six blocks in the same seven-raster band.
4. **`test_boss_hud_transition` fails under 7+1 and passes at HEAD.** Traced to a
   mechanism: `hudScore` is written only by `hudDemoTick` at +10 per 8 main-loop
   iterations, so the slot architecture has no path to it, and the assertion
   freezes the top three digits across a window the number provably grows
   through. **Not fixed, not relaxed** — it is listed here and first in the manual
   checklist because the score is visible on screen.
5. **Pre-existing, unrelated, reported not fixed:** the muzzle artwork uses bit
   pair 01 while `player.asm` claims it never does (byte-identical at HEAD);
   `tools/run_tier.sh` has no timeout or kill logic; `test_lifecycle` produces 0
   and 10 failures from the same binary; `ENGINE_CONTRACT.md` §5's "every sprite
   is hires" predates multicolour gameplay.

### 3. Manual VICE acceptance checklist

**I did not perform manual visible acceptance and do not claim it.** Everything
above is automated instrumentation and cycle measurement. Please run normal
speed, no warp, and look at these six things:

1. **The score across boss entry.** Watch the six digits as the level ends and
   the boss arrives. They should keep counting up and never jump down, reset, or
   show garbage. This is item 2.4 above and the only open question.
2. **Ordinary firing.** Hold fire in open space. The flash should appear at both
   wing guns, in red, for two frames per shot, registered on the gun barrels —
   indistinguishable from before.
3. **The top of the screen, firing.** Fly the craft to the very top of its travel
   and hold fire. The flash must still appear, still sit on the barrels, and must
   not flicker, jump, show garbage rows, or vanish as you cross the band between
   roughly one and seven pixels from the top. Then ease down through that band
   and back up, firing continuously, watching the transition.
4. **Across X=255/256, firing.** Fly left and right through the middle of the
   screen while firing. The flash must stay exactly on the craft with no
   horizontal jump as the X high bit flips.
5. **Dense upper-aperture traffic.** A wave of seven or more enemies entering
   across the top. Seven should now be drawn where six were. Watch the top edge
   of the playfield for any flicker or black scanline — that is the margin in
   item 2.1 and it is the thing to look hardest at.
6. **Flying vertically into dense traffic while firing.** The craft must never
   disappear, blink out, or be drawn behind anything. If the flash disappears in
   the thick of it, that is the designed degradation, not a fault.

### 4. Is the engine ready for a hostile high-density level?

**Yes, with one caveat and one number to author against.**

Seven sprites now fit in a 33-raster band instead of six, batch counts fell by
one in four of the nine measured spread scenes, and the admission counters
finally distinguish "your wave is too tightly packed" (`statRejUnsafe`) from
"your wave is outside the aperture" (`statRejRange`) — which is the feedback an
author tuning density actually needs.

The number to author against is **seven per 33 rasters**, and the caveat is the
top of the aperture: seven sprites at Y=55 is the one configuration that pushes
batch 0 to raster 53 and leaves two lines of margin. It measured clean over
8,000 frames, but it is the corner to put on screen first and the corner to
re-measure after any future renderer change.

---

## Appendix — files changed

| file | change |
|---|---|
| `src/renderer.asm` | `MUX_FIRST_SLOT` 2→1, `MUX_SLOTS` 6→7; the player guarantee re-derived against masks; a HUD⊂mux assertion; `D01C_HUD_PHASE` comment; the published player block trimmed to HW0; `MUZZLE_LOG_ID` legality; the two-way admission merge; `bs_reuseBack` and the overload policy; `statRejUnsafe`/`statRejRange` separated and saturated; `exHud`'s HW1 block removed; `exFrame` patches three pointer stores; five new builder locals |
| `src/player.asm` | `PLAYER_SLOT_MASK` and `PLAYER_D01C` to one bit; `plyPres` 10→7 bytes with `plyPresMuzOn`; `playerEmit` writes the flash's logical state at `MUZZLE_LOG_ID` and calls `logClipAnnotate`; `$d015`/`$d010` reduced to the craft's bit |
| `src/main.asm` | `MUZZLE_LOG_ID = 16`, above both importers |
| `src/objects.asm` | assertion that the pool can never allocate `MUZZLE_LOG_ID` |
| `src/scroll.asm` | segment start `$4340` → `$4350`, with the measurement |
| `src/sorter.asm` | one comment: "accepted mod 6" → "accepted mod MUX_SLOTS" |
| `docs/ENGINE_CONTRACT.md` | §2 and §5 rewritten for the new ownership model |
| `tests/test_player_ship.py` | stale 6+2 assertions modernised; two new checks added |
| `tests/test_production.py` | stale 6+2 assertions modernised |
| `reports/mux-7plus1-implementation.md` | new (this report) |

Scratch harnesses (outside the repository): the host model updated for the
shipped policy, a 56-check acceptance suite, an end-to-end + timing suite, a
batch-0 exit-raster soak, a before/after performance lab, a muzzle-request
diagnostic, an un-driven-boot probe, a HEAD baseline builder and a bounded-run
wrapper.
