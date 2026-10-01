# Multiplexer slot architecture benchmark — 6+2 vs 7+1 vs fully pooled 8

**Date:** 2026-10-01
**Scope:** investigation and benchmark only. **No production slot architecture
was changed.** Production source is byte-identical to `HEAD` throughout.
**Committed or pushed:** no. **No destructive git operation was used.**

---

## 0. Recommendation

**Adopt 7+1 — one reserved player slot, seven pooled mux slots, the muzzle
flash scheduled as a clipped-capable pseudo-entry. Do not adopt fully pooled 8.**

Three measurements decide it, and none of them is the sprite count.

1. **Eight entries in one batch does not fit the raster timing**, and the
   timing constants are not on the table. An eight-entry batch 0 exits at
   raster **54** against `TOP_ARM_LINE` 52, and the engine's own `edgeLate`
   counter — the top aperture split landing off its target line — fired **17
   times in 200 frames**. At seven entries it exits at **52** and `edgeLate`
   was **0 in 1,200 frames**. A mid-screen eight-entry batch measured **796
   cycles** against the `REUSE_LEAD × 63 = 756`-cycle budget; seven entries
   measured at worst 699.

2. **Pooling the player spends the slot it just bought, in the one place the
   slot was wanted.** The player and its muzzle become two more demands inside
   the same 33-raster window they already occupied. Across 20,000 fuzz scenes
   pooled-8 drew more enemies than 7+1 in **0.60%** of them and *fewer* in
   **0.015%** — and the minimised case for the latter shows pooled-8 accepting
   *fourteen* sprites where 7+1 accepted thirteen, while drawing *twelve*
   enemies against thirteen.

3. **The win was never capacity; it is batch count.** Mean enemies drawn across
   the fuzz corpus moves 7.611 → 7.641 → 7.647, which is **+0.40%** and
   **+0.48%** — noise. Mean batches move 1.960 → 1.776 → 1.720, which is
   **−9.4%** and **−12.2%**, and a batch costs ~67 cycles in the builder plus
   67+77n in the interrupt. 7+1 takes two thirds of the available batch saving
   for one constant change and no new failure mode.

The honest summary of the hypothesis in the brief — *"a physical sprite used for
an enemy high on the screen need not be permanently unavailable to the player
low on the screen"* — is that **it is true, and it is worth one slot, not two.**
HW1 (the muzzle's slot) is genuinely idle most of the time and can be recovered.
HW0 cannot be recovered without either giving the player's own demand back to
the pool, or spending the raster budget that the eighth entry needs.

Current authored content does not reach any of these limits: level 1 peaks at
**8 accepted entries, 2 batches, mid-screen batches of 1–2 entries, and zero
rejections of any kind**. The case for 7+1 is a case about the hostile level the
user intends to author next, not about today's campaign.

---

## 1. Initial state

```
branch main, working tree CLEAN
HEAD f625216 Clipping optimisation
     26f07c8 regenTick optimised
     42370f3 Hitscan routines optimised
```

The previous pass's clip and scheduler work had been committed by the user
before this pass began. Nothing was dirty to preserve, and nothing was made
dirty: `git status --porcelain` is empty at the end of this report.

### Reports read first

`2026-09-13-fable-mux-capacity-audit.md` (the prior mux capacity audit — this
ground is **not** fresh and the brief's warning was right to say so),
`buildschedule-performance-audit.md`, `clipmakescratch-performance-audit.md`,
`mux-glitch-diagnostic-pass-1.md`, `mux-legality-window-batch-merge.md`,
`whole-frame-audit-and-regen-optimisation.md`, `regen-contiguous-row-copy.md`,
`top-border-raster-shimmer.md`, `player-muzzle-flash.md`,
`runtime-vertical-sprite-clipping.md`, `vic-bank-0-memory-audit.md`.

### Source read

`src/renderer.asm` in full (constants, `buildSchedule`, the batch pass, the
whole executor chain), `src/player.asm` (presentation block, muzzle, death,
blink), `src/hud.asm` (slot table and mode registers), `src/clip.asm`,
`src/sorter.asm`, `src/objects.asm`, `src/collision.asm`, `src/boss.asm`.

### What the prior audit already established, and is not re-litigated here

*Batch count, not sprite count, is the cost.* Sixteen sprites in four batches
fit the frame; the same sixteen in eleven do not. That audit's option 1 —
merging by legality window rather than exact line — has since shipped and is
what `bs_bLoop`/`bs_absorb` do today. This pass therefore measures slot policies
against a builder that **already** has the batch-merging win in it, which is why
the batch-count improvements below are smaller than that audit's figures.

---

## 2. Phase 1 — dependency archaeology

### 2a. The answer to "why are HW0/HW1 special"

It is discoverable and it is one sentence: **the HUD occupies HW2–HW7 exactly,
so HW0 and HW1 are the only two hardware sprites the border HUD does not use.**

`src/hud.asm:184` — `hudSlot: .byte 2, 3, 4, 5, 6, 7`, `HUD_SPRITE_COUNT = 6`,
`HUD_ENABLE = %11111100`. The HUD displays on rasters 17..37; the mux owns the
same six slots from raster 55 down; `exHandoff` at raster 40 transfers them.
`renderer.asm:33` says so without flinching: *"It is numerically EQUAL to
HUD_ENABLE, and that is not a coincidence worth hiding."*

The player therefore got the two slots that needed no handoff at all, and the
reservation bought a strong property: `exHud` programs HW0/HW1 once at raster 4
and **nothing** — no batch, no phase, no main-thread routine — can reach
`$d000-$d003`, `$d027/$d028` or the two pointer entries again before the next
raster 4. The file states the standard it is holding itself to: *"The player's
presentation is therefore immutable for the whole displayed frame in the
strongest sense — not merely unmodified, but unreachable."*

That is the property a migration spends. It is not a deeper architectural
reason than simplicity — but it is not *merely* simplicity either, because it is
what makes the player's visibility independent of every scheduling decision.

### 2b. Every dependency on physical sprite number, classified

Searched: direct register writes, `$d010` bits, pointer-table entries, colour
registers, multicolour/expansion/priority bits, enable bits, collision
registers, death/blink/invulnerability, muzzle lifetime, player explosion,
hitscan origin, input, HUD/aperture raster behaviour, IRQ code, the schedule
executor, clipping, pointer-table ownership, and any use of a hardware sprite
number as semantic identity.

**The renderer is the sole writer of gameplay sprite VIC state.** The only
writes to sprite 0/1 registers anywhere in `src/` are in `exHud`. Confirmed by
exhaustive grep: the other matches are `src/main.asm:564-577` (one-time boot
init), `src/gamestate.asm:1381` (the non-game attract path, `$d015 = 0`) and
comments.

| # | Dependency | Site | Class |
|---|---|---|---|
| 1 | `$d000/$d001/$d027`, `PTR_A+0` written for HW0 | `renderer.asm:1462-1471` | hard-coded, straightforward |
| 2 | `$d002/$d003/$d028`, `PTR_A+1` written for HW1 | `renderer.asm:1474-1481` | hard-coded, straightforward |
| 3 | `PLAYER_SLOT_MASK = %00000011` | `player.asm:50` | hard-coded, straightforward |
| 4 | `PLAYER_HW0_BIT = %00000001` | `player.asm:51` | hard-coded, straightforward |
| 5 | `plyPresEnable` sets `$d015` bits 0/1 | `player.asm:1212-1217` | hard-coded, straightforward |
| 6 | `plyPresD010` sets `$d010` bits 0/1 | `player.asm:1198-1200` | hard-coded, straightforward |
| 7 | the ten-byte `schedPly*` block and its copy | `renderer.asm:636-660` | hard-coded, straightforward |
| 8 | `bs_enable`/`bs_d010` seeded from the player's bits | `renderer.asm:690-700` | hard-coded, straightforward |
| 9 | `.if (MUX_FIRST_SLOT < 2) { .error }` | `renderer.asm:70` | correctness-sensitive — it *is* the guard being removed |
| 10 | four `.if` guards that the HUD's mode registers leave bits 0/1 alone | `renderer.asm:66-69` | correctness-sensitive, must be re-derived, not deleted |
| 11 | `PLAYER_D01C = %00000011`, `D01C_HUD_PHASE`, `D01C_GAMEPLAY` | `player.asm:209`, `renderer.asm:102-103` | already logical — the composed values do not change |
| 12 | **HUD owns HW2–HW7 exactly** | `hud.asm:184`, `HUD_ENABLE` | **structural**: the reason the reservation is where it is |
| 13 | **muzzle Y = `plyY − 7`, so its range is [48,219]** | `player.asm:193,1094` | **correctness-sensitive blocker** (§6) |
| 14 | `MIN_SPRITE_Y = 55` admission floor | `renderer.asm:169` | timing-sensitive: it is what keeps sprite DMA out of the top split |
| 15 | `MAX_SPRITE_Y = 226`, derived for HW3–HW7 DMA | `renderer.asm:170` | timing-sensitive, but **conservative** for HW0–HW2, which fetch a line earlier |
| 16 | `REUSE_LEAD = 12` → a 756-cycle batch budget | `renderer.asm:142` | **timing-sensitive blocker at 8 entries** (§7) |
| 17 | `HANDOFF_LINE = 40`, `TOP_ARM_LINE = 52` | `renderer.asm:252,301` | **timing-sensitive blocker at 8 entries** (§7) |
| 18 | `PLAYER_MIN_Y/MAX_Y` asserted equal to the mux bounds | `renderer.asm:177-178` | already logical |
| 19 | collision and hitscan | `collision.asm` | **already logical** — `$d01e` is never read anywhere in the engine |
| 20 | enemy-bullet and pickup collision | `ebullet.asm`, `pickup.asm` | already logical, same reason |
| 21 | death, explosion, blink, invulnerability | `player.asm` | already logical: all drive `plyVisible` → `plyPresEnable` |
| 22 | boss cells | `boss.asm` via `objectAlloc` | already logical — logical pool slots, not hardware |
| 23 | clip scratch pool | `clip.asm` | already logical and **slot-count independent** |
| 24 | sprite pointer table | `PTR_A,x` indexed by `schedSlot` | already logical |
| 25 | sorter and logical pool | `sorter.asm`, `objects.asm` | already logical — **the player is not in the pool at all** |

**Genuine blockers: three, and only three.** Items 13, 16 and 17. The first has
a clean repair (§6); the other two are what rule out eight slots (§7).

### 2c. One thing the archaeology found that is not about slots

`statRejUnsafe` is unreachable and `statRejRange` conflates two different
causes. In `buildSchedule`:

```asm
    cmp #MIN_REUSE_GAP
    bcs bs_accept
    cmp #SPRITE_HEIGHT
    bcs bs_margin          // 21..32
bs_outOfRange:             // <-- a gap of 0..20 FALLS THROUGH to here
    inc statRejRange
...
bs_unsafe:
    inc statRejUnsafe      // "< 21: the two sprites genuinely overlap"
```

`bs_unsafe` is reached only by `bcc` on a negative gap, which the sorted-list
precondition forbids. A genuine overlap therefore increments `statRejRange`,
whose own comment says it counts sprites *"refused because their Y was outside
the production range"*.

Proved on the machine, not read off the listing:

| case | accepted | `statRejRange` | `statRejUnsafe` | `statRejMargin` |
|---|---:|---:|---:|---:|
| 6 at Y=120 then 6 more at Y=120 (gap 0) | 6 | **6** | 0 | 0 |
| 6 at Y=120 then 6 at Y=130 (gap 10) | 6 | **6** | 0 | 0 |
| 6 at Y=120 then 6 at Y=140 (gap 20) | 6 | **6** | 0 | 0 |
| 6 at Y=120 then 6 at Y=141 (gap 21) | 6 | 0 | 0 | 6 |
| 6 at Y=120 then 6 at Y=152 (gap 32) | 6 | 0 | 0 | 6 |
| 6 at Y=120 then 6 at Y=153 (gap 33) | 12 | 0 | 0 | 0 |
| 3 below the floor + 3 in range | 3 | **3** | 0 | 0 |

**The rejection itself is correct in every row** — the sprite is refused, and
refused for the right reason. Only the counter is wrong, and two causes that
want different responses from a level author ("your wave is too tightly packed"
versus "your wave is outside the aperture") are reported in one number.

This is documented, **not fixed**: it is unrelated to the slot question and the
brief says not to broaden scope. It is listed as a prerequisite in §12 because
the migration's acceptance tests will want to distinguish the two.

---

## 3. Phase 2 — the authoritative current scheduler model

Transcribed from `src/renderer.asm`, not remembered.

**Logical input.** `sortedIDs[0 .. sortedCount-1]`, a permutation of logical IDs
with `logY[sortedIDs[i]] <= logY[sortedIDs[i+1]]`. Ascending Y is a
**precondition**, not a variable: the reuse rule compares an entry against
accepted entry `i − MUX_SLOTS` and is sound only on such a list.

**The player is not in that list.** It has no logical pool slot, no object type
and no sorter entry. It reaches the schedule as a ten-byte presentation block
(`plyPres` → `schedPly*`) copied by `buildSchedule`, and is programmed by
`exHud` at raster 4. This is the single most important fact for the migration:
pooling the player is *not* "add it to the pool", because the pool is walked by
eight files with a type dispatch (`TYPE_NONE/ENEMY/EBULLET/PICKUP/BOSS`).

**Presentation clamp, first.** `logClip != 0` → the presented Y becomes
`MIN_SPRITE_Y` (clip > 0, hanging above) or `MAX_SPRITE_Y` (bit 7 set, hanging
below). Every test downstream uses the presented Y, so the schedule is legal for
the sprite that is actually drawn.

**Admission, in this order:**

1. presented Y outside `[55, 226]` → rejected, `statRejRange`
2. `bs_acc == MAX_SCHED` (24) → rejected, `statOverflow`, scan continues
3. `bs_acc < MUX_SLOTS` → accept (no slot to reuse)
4. else `gap = Y_i − Y_(i−MUX_SLOTS)`:
   `gap >= 33` accept · `21 <= gap < 33` → `statRejMargin`
   · `0 <= gap < 21` → `statRejRange` (see §2c) · `gap < 0` → `statRejUnsafe`
5. clipped entry with `clipUsed == CLIP_POOL_SLOTS` → refused, `clipPoolFull`

**Slot allocation** is a fixed round robin: `MUX_FIRST_SLOT + (accepted mod
MUX_SLOTS)`, cursor reset per build. There is no free-list and no spatial
allocator; "which slot" is a pure function of accepted index.

**`$d010` and `$d015`** are accumulated during admission, seeded from the
player's two bits so every complete value the executor writes already contains
them. Each entry's running `$d010` is recorded in `bs_d010cum`.

**Batch formation.** Batch 0 is the first `min(accepted, MUX_SLOTS)` entries at
`HANDOFF_LINE = 40` — the only batch whose line is not derived from a sprite Y.
Thereafter, with `earliest_k = Y_(k−MUX_SLOTS) + 21` and `latest_j = Y_j − 12`:

```
open a batch at entry j on line L = latest_j
absorb entry k while earliest_k <= L
close when it will not fit, or at MUX_SLOTS entries
```

Batches address a **contiguous run** (`batchFirst` + `batchCount`), so grouping
can only join neighbours. A batch provably cannot exceed `MUX_SLOTS`, because
entry `j+S`'s predecessor is entry `j` itself and `Y_j + 21 > Y_j − 12`.

**Executor.** `exFrame` (250) adopts both published records and runs nothing
else; `exHud` (4) programs HW2–HW7 from the HUD tables and HW0/HW1 from the
player block; `exHandoff` (40) restores the gameplay mode registers and runs
batch 0; each subsequent batch fires at its own line; `exTop` (armed 52, acts on
55) opens the aperture; `exBottom` (243/248) closes it. `exArm` acknowledges
before arming and chases a line already passed, treating equality as late;
`exLate` chases `PH_BATCH` and — by name — `PH_TOP`, because a missed top split
blanks the screen.

**Publication** is one byte (`schedPending`), adopted at one point. A build that
begins with a publication outstanding withdraws it and counts
`schedBuildDefer`.

**Per-batch executor cost, from the source**: the entry loop is 77 cycles of
6502 per entry (`4+2+2+4+4+2+4+4+5+4+5+4+4+5+4+5+6+6+3`), and §7 measures what
that becomes once the VIC is stealing cycles.

---

## 4. Phase 3 — the benchmark, and the proof it matches production

`muxmodel.py` is a host model of `buildSchedule` parameterised by slot policy.
It is a transcription, including the two places where the assembly does not do
what its comment says: the §2c fallthrough is modelled as the machine behaves,
because a model that implemented the documented intent would disagree with the
machine and the disagreement would be read as a policy difference.

**Validation method.** The real builder is driven at its **real call site** —
a breakpoint on `buildSchedule`'s own entry, which is main-thread by
construction — with a synthetic logical scene written there. Nothing sets `PC`.
The builder then runs its ordinary course and the resulting schedule is read
back out of RAM and compared field by field.

Compared: **accepted count, every accepted Y, every slot assignment, batch
count, every batch line, every `batchFirst`/`batchCount`, every batch's complete
`$d010`, the `$d015` enable mask, `statRejRange`, `statRejUnsafe`,
`statRejMargin`, `statOverflow` and `statReuse`.**

**Validated against three real builders**, not one. The 7- and 8-slot figures in
this report are not model extrapolations: instrumented scratch variants were
built with `MUX_FIRST_SLOT/MUX_SLOTS` set to (1,7) and (0,8) and the mux-floor
assertion relaxed, and the model was checked against those machines too.

| builder | scenes | agree |
|---|---:|---:|
| production, 6 slots (HW2–HW7) | 30 | **30/30** |
| scratch variant, 7 slots (HW1–HW7) | 30 | **30/30** |
| scratch variant, 8 slots (HW0–HW7) | 30 | **30/30** |

The 30 scenes cover: single sprite; even chains of 2/5/6/7/8/10/12/16; spacing
at and either side of every threshold (20/21/32/33); same-Y clusters of 6, 8 and
12; two waves; three clusters; spread-10 and spread-11 over sixteen; the widest
legal spread; both aperture edges; below the floor; above the ceiling; a
26-sprite overflow; top-edge clipping; bottom-edge clipping; clip-pool
exhaustion; and X either side of 256 both mixed and uniform.

**The variants are instruments, not candidates.** With `MUX_FIRST_SLOT` below 2
the mux tramples the player's reserved slots by design, so they were used for
builder and executor measurement only. **No manual visual acceptance of a
variant is claimed, and none was performed** — a build whose player is
deliberately overwritten has nothing to accept visually. Production was rebuilt
from unmodified source after each variant and `git diff` confirmed empty.

---

## 5. Phases 4/5 — the corpus, the fuzz, and what capacity actually is

### 5a. Designed corpus — the pure slot-count case

A same-Y cluster is the only geometry where slot count maps one-for-one onto
sprites drawn, because every member presents at the same raster and none can
reuse another's slot.

| offered at one Y | 6+2 draws | 7+1 draws | pooled-8 draws |
|---:|---:|---:|---:|
| 6 | 6 | 6 | 6 |
| 7 | **6** | 7 | 7 |
| 8 | **6** | **7** | 8 |
| 9 … 16 | 6 | 7 | 8 |

One slot, one sprite, and then a hard wall. This is the whole of the capacity
story, and the rest of the corpus is about what it costs to get there.

### 5b. Designed corpus — everything else

`reports/mux-slot-architecture-capacity.csv` carries all 77 rows. Selected:

| scene | n | 6+2 drawn/batches/maxMid | 7+1 | pooled-8 |
|---|---:|---|---|---|
| top row, 8 at Y=55 | 8 | 6 / 1 / 0 | 7 / 1 / 0 | 8 / 1 / 0 |
| top row, 10 at Y=55 | 10 | 6 / 1 / 0 | 7 / 1 / 0 | 8 / 1 / 0 |
| dense upper, 10 at gap 4 | 10 | 7 / 2 / 1 | 8 / 2 / 1 | 9 / 2 / 1 |
| dense middle, 10 at gap 4 | 10 | 7 / 2 / 1 | 8 / 2 / 1 | 9 / 2 / 1 |
| dense lower, 10 at gap 4 | 10 | 7 / 2 / 1 | 8 / 2 / 1 | 9 / 2 / 1 |
| two waves 6 + 6 | 12 | 12 / 2 / 6 | 12 / 2 / 5 | 12 / 2 / 4 |
| **two waves 8 + 8** | 16 | **12** / 2 / 6 | **14** / 2 / 7 | **16** / 2 / **8** |
| three clusters of 4 | 12 | 12 / 3 / 4 | 12 / 3 / 4 | 12 / 2 / 4 |
| three clusters of 5 | 15 | 15 / 3 / 5 | 15 / 3 / 5 | 15 / 3 / 5 |
| even chain, gap 7, 16 | 16 | 16 / **6** / 2 | 16 / **4** / 3 | 16 / **3** / 4 |
| spread 10, 16 | 16 | 16 / **5** / 3 | 16 / **4** / 4 | 16 / **3** / 5 |
| spread 11, 16 | 16 | 16 / **4** / 4 | 16 / **3** / 5 | 16 / **3** / 6 |
| 8 enemies + 8 bullets | 16 | 16 / 5 / 3 | 16 / 4 / 4 | 16 / 3 / 5 |
| 6 enemies + 6 bullets | 12 | 12 / 3 / 3 | 12 / 3 / 4 | 12 / 2 / 4 |

Three things to read off it.

* **Where sprites are spread, every policy draws all sixteen.** The slot count
  changes only the batch count. That is the real currency.
* **`maxMid` rises with the slot count.** The widest mid-screen batch goes 6 → 7
  → 8, which is exactly the quantity §7 shows is unaffordable at eight.
* **"two waves 8+8" is the one scene where pooled-8 is dramatically better** —
  16 drawn against 12 — and it is also the scene that produces an eight-entry
  mid-screen batch. The capacity gain and the timing failure are *the same
  scenario*.

### 5c. Clipping, held constant — it is a separate resource

`CLIP_POOL_SLOTS = 6` and is independent of the mux slot count. Held constant
across the three policies, with eight unclipped sprites behind it:

| clipped offered | 6+2 drawn / clipUsed / poolFull | 7+1 | pooled-8 |
|---:|---|---|---|
| 0 … 6 | 8…14 / 0…6 / 0 | identical | identical |
| 7 | 14 / 6 / 0 | 14 / 6 / **1** | 14 / 6 / **1** |
| 8 | 14 / 6 / 0 | 14 / 6 / **2** | 14 / 6 / **2** |
| 9 | 14 / 6 / 0 | 14 / 6 / **3** | 14 / 6 / **3** |

Note the asymmetry, and it is the reason to insist on this control. At six slots
the seventh top-edge clipped sprite is refused by the **reuse rule** before it
ever asks for a block, so `clipPoolFull` stays zero and the clip pool looks
infinite. At seven and eight slots it gets as far as asking, and the clip pool
becomes the binding constraint instead. **Raising the mux slot count moves the
bottleneck onto the clip pool at the aperture edges** without drawing one extra
sprite. Eight mux slots do not imply eight clipping scratch slots, and the 832
bytes VIC bank 0 can spare do not permit them.

### 5d. Seeded fuzz — 20,000 scenes

Seed base **19656000**, 20,000 deterministic scenes: 1–16 sprites, Y drawn over
`[45,236]` (deliberately wider than the legal aperture so the range path is
exercised), X and the X MSB varied, one in six sprites clipped at a random
depth, player Y and firing state varied per seed.

| policy | mean enemies drawn | mean batches | mean reuses | player lost | muzzle lost | max pops | widest mid batch |
|---|---:|---:|---:|---:|---:|---:|---:|
| 6+2 | 7.6109 | 1.960 | 2.681 | 0 | 0 | 0 | 6 |
| 7+1 | 7.6413 | 1.776 | 2.434 | 0 | 423 | 0 | 7 |
| 7+1, muzzle clipped | 7.6410 | 1.778 | 2.445 | 0 | **16** | 0 | 7 |
| pooled-8 | 7.6471 | 1.720 | 2.441 | 0 | 411 | 1 | **8** |
| pooled-8, muzzle clipped | 7.6468 | 1.722 | 2.452 | 0 | **4** | 1 | **8** |
| pooled-8, **naive** greedy | 7.6481 | 1.720 | 2.440 | **23** | 411 | — | 8 |

**Where the extra slot actually pays**, same scene, enemies drawn:

| outcome | scenes | share |
|---|---:|---:|
| no policy draws more than 6+2 | 19,388 | **96.94%** |
| 7+1 beats 6+2, 8 adds nothing further | 489 | 2.44% |
| 8 beats 7+1 beats 6+2 | 115 | 0.57% |
| **8 beats 7+1, and 7+1 did not beat 6+2** | **5** | **0.03%** |
| **8 draws FEWER than 7+1** | **3** | **0.015%** |

So of the 604 scenes (3.02%) where anything improves at all, **7+1 captures 604
and pooled-8 adds 120** — and in three scenes pooled-8 is a regression.

### 5e. Minimised pathological fixtures

Reproducible, and each one exists to make a different point.

| fixture | definition | what it demonstrates |
|---|---|---|
| `top-row-8` | 8 sprites at Y = 55 | pooled-8's eight-entry batch 0; `edgeLate` 17/200 frames |
| `mid-cluster-8` | 8 sprites at Y = 150 | an eight-entry mid-screen batch; **796 cycles against a 756 budget** |
| `cluster-12@120` | 12 sprites at Y = 120 | the pure slot-count case: 6 / 7 / 8 drawn |
| `two-waves-8+8` | 8 at Y=70, 8 at Y=180 | the largest capacity gain (12 → 14 → 16) *and* the widest batch |
| `muzzle-floor` | empty screen, player Y 55…61, firing | pooled muzzle refused: `plyY − 7 < MIN_SPRITE_Y` |
| **`seed 19658686`** | 16 sprites, player Y 121, firing | **pooled-8 accepts 14 sprites and draws 12 enemies; 7+1 accepts 13 and draws 13** |
| `clip-pool-overflow+8` | 8 top-clipped + 8 plain | the clip pool binds before the mux does at 7 and 8 slots |
| `naive-player-loss` | 23 fuzz seeds | a greedy allocator that merely includes the player loses it |

The `seed 19658686` fixture is the one worth keeping on a wall:

```
offered presented Y: 45 49 55 67 75 83 89 91 97 101 103 111 117 127 221 233
player Y 121, firing

6+2        drawn=12  accepted=12   slots 2,3,4,5,6,7,2,3,4,5,6,7
7+1        drawn=13  accepted=13   slots 1..7,1..6
pooled-8   drawn=12  accepted=14   slots 0..7,0..5   <- player Y=121, muzzle Y=114
```

Pooled-8 accepted **two more sprites than 6+2 and one more than 7+1**, and drew
**fewer enemies than either**. The two extra slots went to the player and its
muzzle, in the middle of the crowd, which is where the crowd already was.

---

## 6. Phase 6 — guaranteeing the player, and the muzzle's own problem

### 6a. The player guarantee

The required invariant is absolute: **no legal or pathological enemy arrangement
may cause the player to disappear.** Under a fixed round robin the player, once
pooled, is simply an entry — and an entry at accepted index `a` is refused when
`Y_a − Y_(a−S) < 33`. Eight or more enemies within 32 rasters above the player
therefore refuse the player.

Measured: **a naive greedy allocator that merely includes the player in the
sorted stream loses it in 23 of 20,000 fuzz scenes (0.12%).** That settles the
brief's warning — this cannot be left to hope.

Candidates considered:

| strategy | verdict |
|---|---|
| **Reserve a lane** — run enemies over `S−1` slots so the last is always free | Sound, and it **is** 7+1 (or 6+2 for two layers). It gives up the entire point of pooling, because the player's slot can then never be reused by a distant enemy. Rejected as a *pooling* strategy; adopted as the recommendation by another name. |
| **Absolute priority in the sorted merge** | Does not guarantee anything on its own — the player is still an entry subject to the same local test. This is the naive case above. |
| **Build, detect infeasibility, drop lowest-priority and rebuild** | Works, but a rebuild is O(N) again and the worst case is several rebuilds. Unnecessary: the single-pass form below gets the same answer. |
| **Pop-the-crowder (adopted for the benchmark)** | When the player candidate fails its reuse test, release the **most recently accepted** entry and re-test. That entry is by construction the one immediately above the player in Y — exactly the sprite crowding it. The player's accepted index falls by one each time, so its predecessor moves further up the screen; termination is guaranteed because at index `< S` there is no predecessor at all. |
| **Evict the slot owner `a−S` directly** | Breaks the contiguous-run batch representation and the ascending-Y invariant the batch pass depends on. Rejected. |
| **Widen the window for the player only** | Would need a different `REUSE_LEAD` for one entry, i.e. a second timing contract. Rejected: §7 shows the existing one is already the binding constraint. |

**Pop-the-crowder measured: player lost 0 of 20,000, maximum pops in any scene
1.** Its cost is a handful of cycles — `dec bs_acc`, `dec bs_slotcycle` with
wrap, a conditional `dec clipUsed`, and the re-test — perhaps 30–40 cycles per
pop, bounded by `MAX_SCHED`. Nothing downstream has been written when it runs:
batches are formed afterwards, and the released slot's `$d015` bit stays set
because the player is about to take that very slot.

**The degradation policy a pooled design would require, stated rather than
invented:** the player is never dropped; the sprite that loses is *the enemy
immediately above the player in presented Y*; the choice is deterministic and
reproducible from the sorted list alone. That is a gameplay policy — "flying
into a dense formation makes the enemy you are about to touch vanish" — and it
is not obviously the policy a designer would choose. It is one more reason the
pooled design should not be adopted on capacity grounds alone.

### 6b. The muzzle flash cannot simply be pooled

`src/player.asm:193` — `PLAYER_FLASH_Y_LIFT = 7`, and
`playerEmit` sets `plyPresY1 = plyY − 7`:

> *"HW1 SITS SEVEN LINES ABOVE THE CRAFT. The flash artwork draws its two flares
> low in its own block so that, lifted by this much, each one lands on a
> wing-gun barrel of the craft underneath."*

The player's Y range is `[55, 226]`, so **the muzzle's Y range is `[48, 219]`**
— and the mux admission floor is **55**. A pooled muzzle is therefore refused
outright whenever the player is in the top seven rasters of its own legal range:

| policy | player Y at which the muzzle is lost on an **empty** screen |
|---|---|
| 7+1, muzzle pooled as-is | **55, 56, 57, 58, 59, 60, 61** |
| pooled-8, muzzle pooled as-is | **55, 56, 57, 58, 59, 60, 61** |
| 7+1, muzzle clipped | none |
| pooled-8, muzzle clipped | none |

That is a 7-of-172 band — 4% of the player's legal Y — in which firing produces
no muzzle flash at all. It is not an edge case the player has to work to find:
it is "fly to the top and shoot". Across the firing half of the fuzz corpus it
costs 407 of 10,000 scenes on range alone.

**It has a clean repair that is already built.** `src/clip.asm` exists precisely
to hold a sprite at an aperture edge with a row-shifted bitmap. Giving the
muzzle `logClip = 55 − (plyY − 7)` when that is positive makes it an ordinary
top-clipped entry: it is clamped to Y=55, its artwork is shifted so the flares
stay registered on the gun barrels, and the loss disappears entirely —
**16 of 10,000 under 7+1, all of them crowding rather than range.**

The price is honest and must be stated: ~1,000 cycles and **one of the six clip
scratch blocks**, on firing frames with the player in that 7-raster band. That
is the same band in which top-edge enemy clipping is most likely, so the two
compete for the same pool (§5c). It is affordable; it is not free.

**Priority.** The muzzle should **not** share the player's guarantee. It is
cosmetic and lives 1–3 frames; `plyPresEnable` already treats it as separable
(HW1 is enabled only while `plyFlash` is running, so an idle player costs no
second sprite). Two classes — player guaranteed, everything else best-effort —
are enough; a third class for the muzzle buys nothing the measurements can see,
and the brief is right that the recommendation should stay minimal.

---

## 7. Phase 7 — raster timing, which is what actually decides this

### 7a. Per-batch executor cost, measured

Elapsed cycles between `exBatch` and `exWritesDone` — the label the renderer put
there because *"this is the instant the reuse deadline applies to"*. Elapsed, so
badline stalls and VIC sprite-DMA theft are included, which is the point. Nine
samples per size on real mid-screen batches.

| entries | min | median | **max** | lines (median) | budget 756 |
|---:|---:|---:|---:|---:|---|
| 1 | 144 | 145 | 187 | 2.30 | ok |
| 2 | 221 | 263 | 266 | 4.17 | ok |
| 3 | 298 | 341 | 344 | 5.41 | ok |
| 4 | 375 | 421 | 422 | 6.68 | ok |
| 5 | 494 | 495 | 500 | 7.86 | ok |
| 6 | 572 | 578 | 614 | 9.17 | ok, 142 spare |
| 7 | 649 | 656 | 699 | 10.41 | ok, **57 spare** |
| 8 | 691 | 726 | **796** | 11.52 | **BLOWN by 40** |

The minima fit **`67 + 77n` exactly** at n = 1, 2, 3, 4 and 6 — the hand-counted
6502 cost of the entry loop — and the spread above it is badlines (43 cycles
each) and sprite DMA. That the pure arithmetic and the machine agree is the check
that the measurement is of the right thing.

The deadline is `REUSE_LEAD × 63 = 756` cycles, and at eight entries the
**measured worst case exceeds it**. The entry/exit rasters say the same thing
without arithmetic: an eight-entry batch led by a sprite at Y=150 fires at line
138 and finishes at line **150** — the line on which the VIC fetches that
sprite's data. For HW0–HW2, whose data for display line L is fetched in cycles
57..62 of line **L−1**, it is a full line late.

Note also that a six-entry batch costs 535 at six slots but 578 at seven and
eight. The code is identical; what changed is that more sprites are enabled, so
the VIC steals more. **Raising the slot count makes every batch slightly more
expensive, not only the wide ones.**

### 7b. Batch 0 against the handoff window, measured

Batch 0 is the one batch whose line is fixed at `HANDOFF_LINE = 40`, and it must
finish before `TOP_ARM_LINE = 52` and before the first legal sprite Y = 55.
Measured from the engine's own `handoffEntryMin/Max` and `handoffExitMax`, with
the scene sustained across 200 frames so every YSCROLL phase — and therefore
every badline alignment of lines 52..55 — is sampled.

| batch 0 entries | entry raster | **exit raster** | top split landed | **edgeLate / 200 frames** | statLate |
|---:|---:|---:|---|---:|---:|
| 5 | 40 | 50 | 54..55 | 0 | 0 |
| 6 | 40 | **51** | 54..55 | **0** | 0 |
| 7 | 40 | **52** | 54..55 | **0** | 0 |
| 8 | 40 | **54** | 54..55 | **17** | 0 |

`edgeLate` is production code comparing `topLanded` against `topTarget`: the top
aperture split landed on a line other than the one it aimed at.
`reports/top-border-raster-shimmer.md` already established what that looks like
— *"six or so characters of line 55 drawn from the BLANK charset and painted in
the border's black instead of the level's colour"*, a 12.5 Hz shimmer along the
top edge of the playfield. **The eight-entry batch 0 reintroduces, by a different
route, the exact defect that `TOP_ARM_LINE = 52` was moved to cure.**

The arithmetic agrees. Rasters 40..54 are 15 lines, 945 cycles. Batch 0's
prologue plus 8 × 77 is ~780; `exTop`'s entry and poll need ~143 by the
`TOP_ARM_LINE` derivation. 780 + 143 = **923 against 945** — before a single
cycle of sprite DMA. At seven entries it is 702 + 143 = 845, with 100 in hand,
which is why seven measures clean and eight does not.

### 7c. Can the scheduler legally split batch 0 instead?

The brief asks, and the answer is **no, not in the case that needs it.**

Batch 0 exists because the first `S` entries have no predecessor and must be
programmed before the earliest of them is fetched. If the first eight sprites
are at Y = 55, all eight genuinely must be in place before line 55. Capping
batch 0 at six and giving entries 6 and 7 their own batch puts that batch at
`Y_6 − 12 = 43` — a line the beam has not reached when batch 0 starts, but which
batch 0 is still executing through, so `exArm` finds it already passed and
`exLate` chases it immediately. The work does not move; only its bookkeeping
does, and the top split is pushed later still.

Splitting helps only when the eight sprites are *not* all at the top — and in
that case the batch pass already splits them, because `earliest_k > L` closes
the batch on its own. **The unaffordable configuration is exactly the one
splitting cannot relieve.**

### 7d. Whole-frame health under sustained load

Read from engine RAM only. An earlier attempt derived a frame period from the
monitor stopwatch between consecutive builds and reported **four PAL frames on
an idle screen**; that figure is the monitor's reply lag, not the machine, and
it is discarded rather than reported. A second attempt measured
`frameCounter` delta per build and found 4.000 frames/build at light load —
which turned out to be `buildSchedule`'s own dirty gate (`plyDirty | logCount |
sortDirty`, `main.asm:940`) correctly skipping work, not a frame overrun. Both
instruments were wrong in the direction of looking alarming; `gameOverrun` is
the one that answers the question.

240 builds per scene, scene re-injected every build:

| scene | acc 6/7/8 | batches 6/7/8 | `gameOverrun` 6/7/8 | `statLate` | **`edgeLate` 6/7/8** |
|---|---|---|---|---|---|
| idle | 0/0/0 | 0/0/0 | 0/0/0 | 0 | 0/0/0 |
| 8 at top row Y=55 | 6/7/8 | 1/1/1 | 0/0/0 | 0 | 0/0/**8** |
| 12 at one Y (120) | 6/7/8 | 1/1/1 | 0/0/0 | 0 | 0/0/**4** |
| 16 spread 11 | 16/16/16 | 4/3/3 | 0/0/0 | 0 | 0/0/**2**¹ |
| 16 spread 10 | 16/16/16 | 5/4/3 | 0/0/0 | 0 | 0/0/**1**¹ |
| two waves 8+8 | 12/14/16 | 2/2/2 | 0/0/0 | 0 | 0/0/0 |
| 16 + 6 clipped top | 22/22/22 | 7/5/4 | **221/198/179** | 0 | 0/0/1 |

¹ from the 150-frame pass; the 240-build pass shows the same pattern.

Two results worth separating.

* **`edgeLate` is zero in every scene at six and seven slots, and non-zero at
  eight whenever batch 0 holds eight entries.** Batch 0 always holds
  `min(accepted, S)` entries, so under pooled-8 *any* frame with eight or more
  accepted sprites is exposed — including the two spread scenes, where the
  sprites are nowhere near the top of the screen. This is not a corner; it is
  the common case of a busy frame.
* **The 22-accepted + 6-clipped scene overruns the frame in all three
  policies**, and pooled-8 overruns *least* (179 against 221) because it forms
  four batches instead of seven. That is the CPU benefit of pooling, measured —
  and it is real. It is also outside the design envelope in every policy, so it
  argues for the batch-count win, not for eight slots.

---

## 8. Phase 8 — CPU cost

Means over the same 20,000 fuzz scenes. Builder figures use a cost model fitted
to the 90 real builds of §4 (`380 + 283·accepted + 42·batches + 90·rejected`,
which reproduces the measured builds closely); executor figures use the measured
pure batch cost `67 + 77n`.

| policy | builder cycles | executor cycles | batches | total | % of PAL frame |
|---|---:|---:|---:|---:|---:|
| 6+2 | 2,696 | 717 | 1.960 | 3,413 | 17.4% |
| 7+1 | 2,832 | 744 | 1.776 | 3,576 | 18.2% |
| 7+1, muzzle clipped | 2,836 | 746 | 1.778 | 3,582 | 18.2% |
| pooled-8 | 3,114 | 818 | 1.720 | 3,932 | 20.0% |

* **7+1 costs ~163 cycles a frame more than 6+2** (0.8% of a frame): the muzzle
  becomes an admitted entry and an executor entry when firing. Against that it
  saves 0.18 batches a frame.
* **pooled-8 costs ~519 cycles a frame more** (2.6%): the player is admitted and
  executed every frame, the muzzle when firing, plus the guarantee's pops.
  `exHud` sheds about 68 cycles in exchange, so call it **~450 net**.
* Neither is large. **Neither is the reason to choose**, which is the point: the
  decision is a timing-correctness decision, not a CPU decision.

For context, these are the figures *after* the three optimisation passes that
preceded this one, so the headroom they recovered is not being spent here.

---

## 9. Phase 9 — envelope map

| question | 6+2 | 7+1 | pooled-8 |
|---|---|---|---|
| dense same-region layout (one Y) | **6** | **7** | **8** |
| vertically separated waves, 8+8 | 12 | 14 | 16 |
| sixteen spread ≥ 10 rasters | 16 drawn, 5 batches | 16 drawn, 4 batches | 16 drawn, 3 batches |
| random legal scene draws everything offered | 96.94% of scenes identical across all three | +2.44% improve | +0.60% further |
| effect of player Y | none (reserved) | none for the craft; muzzle lost at plyY 55–61 unless clipped | none for the craft (with the guarantee); 1 enemy lost in the player's own 33-raster window |
| effect of muzzle activity | none | −1 enemy slot in the player's band while firing | −1 enemy slot in the player's band while firing |
| Y spacing at which reuse becomes practical | ≥ 33 (`MIN_REUSE_GAP`); 21–32 is refused by margin | same | same |
| layouts that specifically benefit | ≥ 7 sprites within 32 rasters | ≥ 8 sprites within 32 rasters | as 7+1, plus one more |
| layouts where it gives nothing | anything spread ≥ 33 | same | same, plus the player's own band |
| **next bottleneck** | reuse legality | reuse legality, then the **clip pool** at the aperture edges | the **raster deadline** — it is reached before any capacity limit |

The last row is the whole report in one line. At six and seven slots the binding
constraint is the reuse rule, which is a wave-design constraint an author can
work with. At eight it is the raster deadline, which an author cannot see, cannot
predict, and whose failure is an intermittent flicker rather than a missing
sprite.

---

## 10. Phase 10 — what the real game actually asks for

Production binary, level 1, `boot="exact"` so the authored encounters at rows
48, 52, 90 and 126 are all still ahead, 90 sampling rounds of stepped emulated
time. No injection — the game plays itself.

```
peak accepted entries        8    (MAX_SCHED = 24)
peak batches in a schedule   2
peak MID-SCREEN batch size   1    (cap = MUX_SLOTS = 6)
mid-screen batches executed  288
executed batch sizes         1 entry: 31    2 entries: 10    3+: 0

statRejUnsafe 0   statRejMargin 0   statRejRange 0   statOverflow 0
statReuse     0   clipPoolFull  0   statLate      0   edgeLate     0
gameOverrun   0   statBatchOverflow 0
```

**Today's campaign never refuses a sprite and never builds a batch wider than
two.** The six-slot pool is not a limit the current game can reach, so no slot
policy change has any observable effect on shipped content. Every benefit
measured in this report is a benefit to content that does not exist yet — which
is exactly what the brief says the architecture choice is for, and is also why
there is no urgency.

### Representative cases from the model, checked on real hardware

| case the model identified | checked how | result |
|---|---|---|
| current-safe | production, level 1, 90 rounds | clean; counters above |
| 7-only benefit (`cluster-7@120`) | real 7-slot builder | 7 drawn vs 6; model matched |
| 8-only benefit (`cluster-8@120`, `two-waves-8+8`) | real 8-slot builder | 8 / 16 drawn; model matched |
| nastiest raster-deadline case (`top-row-8`) | real 8-slot executor, 200 frames | **`edgeLate` 17** |
| mid-screen 8-entry batch (`mid-cluster-8`) | real 8-slot executor | **796 cycles vs 756** |
| player-low / player-centre / player-high | host sweep over all 172 legal Y | player never lost under the guarantee |
| muzzle-active | host sweep, firing | lost at plyY 55–61 unless clipped |
| clipping-controlled | real builder at 6/7/8 | clip pool binds at 7 and 8, not at 6 |

**Manual visible VICE acceptance was not performed and is not claimed.**
Production source was never modified, so there is nothing new in it to accept
visually; and the 7-/8-slot builds deliberately overwrite the player's reserved
slots, so they are measurement instruments with nothing meaningful to show on
screen. The evidence offered instead is the engine's own production
instrumentation (`edgeLate`, `handoffExitMax`, `statLate`, `gameOverrun`) and
cycle-exact executor timing, which for a one-line raster race is a sharper
instrument than an eye on a moving sprite.

---

## 11. Migration complexity

### 11a. Shared prerequisite — how the muzzle (and, for 8, the player) reaches the schedule

**Not through the logical pool.** `logActive` is walked by eight files
(`objects`, `sorter`, `collision`, `ebullet`, `pickup`, `token`, `waves`,
`boss`) behind a type dispatch, and `objects.asm:327` currently asserts that a
pickup is *"the only other thing in the pool"*. Introducing a cosmetic object
type would touch every filter in all eight, and any one that forgot it would
make the muzzle shootable, collidable or a valid hitscan target.

**Through a pseudo-entry in `buildSchedule` instead**, exactly as the player
block is copied today. The admission loop walks `bs_pos` over `sortedIDs`; it
becomes a two-way merge between that list and one (or two) extra candidates,
taking whichever has the lower presented Y. That is one file, one loop, and it
keeps the sorted-ascending precondition by construction.

Estimated cost: ~25–30 cycles per admission iteration for the merge test, plus
the pseudo-entry's own admission. Consistent with the ~163 cycles/frame measured
for 7+1 in §8.

### 11b. 7+1 — the recommended migration

| # | Change | File | Risk |
|---|---|---|---|
| 1 | `MUX_FIRST_SLOT` 2 → 1, `MUX_SLOTS` 6 → 7 | `renderer.asm:30-31` | trivial; `MUX_SLOT_MASK`, `D01C_GAMEPLAY` and `batchSizeHist` all derive |
| 2 | re-derive the `MUX_FIRST_SLOT < 2` guard to `< 1`, keeping it a guard | `renderer.asm:70` | low, but it must be **re-derived, not deleted** |
| 3 | re-derive the four HUD-mode assertions against a one-bit `PLAYER_SLOT_MASK` | `renderer.asm:66-69` | low; they are what stop the HUD X-expanding or hiding the player |
| 4 | `exHud` stops programming HW1 (`$d002/$d003/$d028`, `PTR_A+1`) | `renderer.asm:1474-1481` | low; 8 instructions removed |
| 5 | `PLAYER_SLOT_MASK` → `%00000001`; `plyPresEnable`/`plyPresD010` stop setting bit 1 | `player.asm:50,1198,1217` | low |
| 6 | muzzle emitted as a pseudo-entry: Y = `plyY − 7`, X/XHi from the player, pointer and colour from the existing flash logic, `logClip = 55 − Y` when positive | `renderer.asm` + `player.asm` presentation block | **medium** — this is the real work |
| 7 | muzzle priority: best-effort, dropped before any enemy | `renderer.asm` | low |
| 8 | drop the now-dead `schedPlyX1/Y1/Ptr1/Col1` or repurpose them as the muzzle's pseudo-entry fields | `renderer.asm:357-360` | low |
| 9 | update the mux probes' slot/batch models in `make test` | `tests/` | low, but they must be updated **to the new rule**, not relaxed |

Properties preserved: the player stays immutable for the whole displayed frame
(HW0 programmed once at raster 4, unreachable thereafter); `MIN_SPRITE_Y`,
`MAX_SPRITE_Y`, `REUSE_LEAD`, `HANDOFF_LINE`, `TOP_ARM_LINE`, `MIN_REUSE_GAP`
and the aperture all unchanged; one update per hardware slot per frame; no
player guarantee machinery needed at all, because HW0 is still reserved.

**Measured risks, all zero or bounded:** `edgeLate` 0 in 1,200 sustained frames
at seven entries; worst seven-entry batch 699 cycles against 756; batch 0 exits
at raster 52, the arm line, which `exLate` already handles by name.

### 11c. Pooled 8 — what it would additionally require

Everything in 11b, plus:

| # | Change | Risk |
|---|---|---|
| 10 | `MUX_FIRST_SLOT` → 0, `MUX_SLOTS` → 8; the player-slot guard disappears entirely rather than moving | correctness-sensitive |
| 11 | `exHud` stops programming HW0 as well; the ten-byte player block becomes two pseudo-entries | medium |
| 12 | the player guarantee (pop-the-crowder) and its clip-block release | medium |
| 13 | a documented degradation policy: *the enemy immediately above the player disappears* | **gameplay decision, not an engineering one** |
| 14 | the player loses frame-long immutability: its registers are written by whichever batch owns it, and its slot may be reused 21 rasters later | **architectural loss** |
| 15 | **a resolution for the eight-entry raster deadline** — and the only available levers are `REUSE_LEAD`, `HANDOFF_LINE` and `TOP_ARM_LINE`, which the brief rules out | **blocker** |
| 16 | `MAX_SPRITE_Y` re-derivation, since HW0–HW2 fetch a line earlier than HW3–HW7 (conservative today, so safe, but it would no longer be *derived* for the slots in use) | low, but it is a weakened derivation |

Item 15 is not a cost, it is a refusal. Items 13 and 14 are the ones that would
remain even if the timing were solved: pooling the player trades a property the
engine currently has for free — *"not merely unmodified, but unreachable"* — for
0.6% more scenes drawing one extra sprite.

---

## 12. Files changed, tests, disk, git state

### Files changed

| File | Change |
|---|---|
| `reports/mux-slot-architecture-benchmark.md` | new (this report) |
| `reports/mux-slot-architecture-capacity.csv` | new — 77 corpus rows × 3 policies × 5 metrics |

**No file under `src/`, `tests/` or `tools/` was modified.** The 7- and 8-slot
instruments were produced by patching `src/renderer.asm`, building, copying the
artefacts to the scratchpad and restoring the file from a copy taken beforehand,
under a shell `trap` that restores on every exit path. `git status --porcelain`
was verified empty after each.

### Tests

| gate | result |
|---|---|
| model vs **production** builder, 30 scenes | **30/30 agree** |
| model vs **7-slot** builder, 30 scenes | **30/30 agree** |
| model vs **8-slot** builder, 30 scenes | **30/30 agree** |
| deterministic corpus | 77 scenes × 3 policies, host |
| seeded fuzz | 20,000 scenes, seed base **19656000**, host |
| raster soak, batch 0 | 200 frames × 6–7 configurations × 3 policies |
| `make smoke` | **PASS** — `ENGINE HEALTH: PASS`, `ROUTINE REGRESSION: PASS`, `edgeLate 0`, `statLate 0`, `publishSkip 0` |
| `make test` — engine invariant probe | **ALL PASS** (phase schedule, aperture, sprite ownership, page/pointer coherence, HUD write window, schedule overflow) |
| `make test` — `test_turret_regression.py` | **2 failures, pre-existing** |

The turret failures are **not** caused by this pass and that is established
rather than asserted: production source is byte-identical to `HEAD` (empty
`git status`, no stashes), so the binary under test *is* `HEAD`'s. Run twice,
identical both times. The test's own diagnostic says why — *"at least one turret
stayed visible long enough to judge — **0 qualifying runs**"* — its sampling
window never caught a turret on screen long enough to assess, while the
assertion that names the real regression, *"a continuously visible turret's fire
timer NEVER re-arms early"*, **passes**. It is a stale fixture, not an engine
fault, and it is outside this task's scope.

### Disk

```
build/                404K   current binary, symbols and disk image only; no per-run directories
scratchpad            708K   model, labs, two instrumented .d64 + .vs (350K of that), corpus
scratchpad (after)    316K   the two instrument binaries deleted; mkvariant.sh regenerates them in ~30s
```

Nothing was written to `/tmp`. Every screenshot-free capture and log lived in the
session scratchpad and is outside the repository.

### VICE hygiene

Fourteen emulator sessions were launched across this pass. Every one was
launched with `-console` directly (never `open -a`), its exact PID retained, and
terminated and reaped by that PID on success, failure and exception. No broad
`pkill` or `killall` was used at any point, no user-launched session was touched,
and no keyboard focus was taken. `pgrep -x x64sc` reports **none remaining**;
checked after every suite.

### Source control

- **Nothing committed. Nothing pushed.**
- **No `git checkout`, `restore`, `reset`, `stash`, `clean` or any other
  work-discarding operation was used.** The before/after source swaps were plain
  file copies under a `trap`.
- Final `git status --porcelain`:

```
?? reports/mux-slot-architecture-benchmark.md
?? reports/mux-slot-architecture-capacity.csv
```

---

## 13. Recommendation

### 1. The engineering recommendation

**Adopt 7+1. Do not adopt fully pooled 8. Do not defer 7+1 behind further
investigation — this pass is the investigation.**

Reserve HW0 for the player permanently. Pool HW1–HW7 as seven mux slots. Render
the muzzle flash as a best-effort pseudo-entry in `buildSchedule`, given
`logClip` when the player is high enough that the flash would fall below the
aperture floor.

### 2. The measured reasons

| | 6+2 | **7+1** | pooled-8 |
|---|---|---|---|
| dense same-Y capacity | 6 | **7** | 8 |
| mean enemies drawn, 20k scenes | 7.611 | **7.641 (+0.40%)** | 7.647 (+0.48%) |
| mean batches | 1.960 | **1.776 (−9.4%)** | 1.720 (−12.2%) |
| scenes improved over 6+2 | — | **604 (3.02%)** | 724 (3.62%) |
| scenes made *worse* than 7+1 | — | — | **3** |
| worst batch cycles vs 756 budget | 614 | **699** | **796 — BLOWN** |
| batch 0 exit raster vs arm line 52 | 51 | **52** | **54** |
| `edgeLate`, sustained frames | **0 / 1,200** | **0 / 1,200** | **17 / 200** |
| player guarantee needed | none | **none** | pop-the-crowder, plus a gameplay drop policy |
| player immutable for the frame | yes | **yes** | **no** |
| raster constants touched | — | **none** | `REUSE_LEAD` and/or `HANDOFF_LINE`/`TOP_ARM_LINE` |
| CPU cost over 6+2 | — | **+163/frame (0.8%)** | +450/frame (2.3%) |
| files to migrate | — | **2** (`renderer.asm`, `player.asm`) | 2, plus a guarantee, plus a policy decision |

7+1 takes **two thirds of the available batch-count saving and 83% of the
capacity improvement** for one constant, one phase edit, no new failure mode and
no raster constant touched. Pooled-8 buys the remaining third by reintroducing a
measured raster defect and giving up the player's frame-long immutability.

### 3. The principal risks of 7+1

1. **The muzzle is the whole of the work.** Its Y is `plyY − 7` and the
   admission floor is 55, so without the clip repair it vanishes for 4% of the
   player's legal Y — and that 4% is "at the top of the screen, firing". The
   clip repair is measured to remove it completely, but it spends one of six
   clip blocks in the band where top-edge enemy clipping is also likeliest.
   **This is the item to get right, and the item to accept visually.**
2. **Seven-entry batch 0 exits at raster 52 — the arm line exactly.** Measured
   clean over 1,200 frames across every YSCROLL phase, and `exLate` chases
   `PH_TOP` by name precisely for this case. But the margin is now one raster
   rather than two, so **any future growth in `exHandoff` or the batch prologue
   must be re-measured against the top split**, not reasoned about.
3. **The clip pool becomes the next bottleneck at the aperture edges** (§5c),
   and at six slots it was invisible because the reuse rule refused those
   sprites first. The migration should expect `clipPoolFull` to become reachable
   and should keep the counter honest.
4. **The capacity gain is small and will not be felt in today's content** —
   level 1 peaks at 8 accepted entries and rejects nothing. If the hostile level
   is not actually authored, 7+1 buys a cleaner batch profile and nothing
   visible.
5. **`statRejRange` currently conflates "too tightly packed" with "outside the
   aperture"** (§2c). An author tuning a dense wave against the new seven-slot
   limit will be reading that counter, so it should be separated before the
   hostile level is authored.

### 4. The exact next implementation task

> **# 19656 — Migrate the multiplexer to 7+1 and schedule the muzzle flash**
>
> Adopt seven pooled mux slots (HW1–HW7) with HW0 permanently reserved for the
> player, and move the muzzle flash from a reserved hardware slot to a
> best-effort pseudo-entry in `buildSchedule`.
>
> **Do not change** `MIN_SPRITE_Y`, `MAX_SPRITE_Y`, `MIN_REUSE_GAP`,
> `REUSE_LEAD`, `HANDOFF_LINE`, `TOP_ARM_LINE`, `CLIP_POOL_SLOTS`, `MAX_SCHED`,
> the aperture, or the player's legal Y range. **Do not** route the muzzle
> through the logical object pool.
>
> Work items, in order:
> 1. Separate `statRejUnsafe` from `statRejRange` (`renderer.asm`'s
>    `bs_outOfRange` fallthrough) so the migration's acceptance tests can tell
>    a crowded wave from an out-of-aperture one. Small, and a prerequisite.
> 2. `MUX_FIRST_SLOT` 2→1, `MUX_SLOTS` 6→7. Re-derive — do not delete — the
>    mux-floor guard and the four HUD-mode assertions against a one-bit
>    `PLAYER_SLOT_MASK`.
> 3. Stop programming HW1 in `exHud`; reduce `plyPresEnable`/`plyPresD010` to
>    bit 0.
> 4. Emit the muzzle as a pseudo-entry merged into the admission pass by
>    presented Y: `Y = plyY − PLAYER_FLASH_Y_LIFT`, X and X MSB from the
>    player, pointer and colour from the existing flash logic, and
>    `logClip = MIN_SPRITE_Y − Y` when that is positive. Best-effort priority:
>    dropped before any enemy, never dropped in preference to one.
> 5. Update the `make test` mux probes to the seven-slot rule. **Update them to
>    the new rule; do not weaken a check to make the change pass.**
>
> Acceptance:
> * `make test` green, `make test-engine-full` green (the renderer and aperture
>   are being touched).
> * `handoffExitMax` ≤ 52 and **`edgeLate` = 0** over at least 2,000 sustained
>   frames with a seven-entry batch 0, swept across all eight YSCROLL phases.
> * worst mid-screen seven-entry batch measured `exBatch → exWritesDone` under
>   756 cycles, with the margin recorded next to `REUSE_LEAD`.
> * `clipPoolFull` behaviour re-measured with the muzzle competing for blocks.
> * **Manual, non-warp, normal-speed visual acceptance, mandatory**: fly the
>   full legal Y range firing continuously, with particular attention to
>   `plyY` 55–61 where the muzzle is clipped, and to the top of the aperture
>   with seven enemies entering in a row. The muzzle must be present and
>   registered on the gun barrels at every Y, and the top edge of the playfield
>   must not shimmer.
>
> The reward is a mux that admits seven sprites in a 33-raster window instead of
> six, ~9% fewer raster interrupts a frame, and no raster constant moved — which
> is the headroom the hostile high-density level needs.
