# Definitive C64 memory audit for 440-row levels

**Date:** 2026-09-17
**HEAD:** `722dbbd` — *HUD bank switching, token progress*
**Working tree:** clean. `git diff` empty; only four untracked reports from earlier tasks.
**Build audited:** PRG 51,162 bytes, `$0801-$cfda`, sha256 `cbaeb0f4…779803f7`
**Nothing committed. Nothing pushed. No production file modified.**

---

## 1. Executive recommendation

> **Put the generated level package at `$e000-$fff9` — 8,186 bytes of RAM under the
> banked-out KERNAL — as a separately loaded file. Store the 440-row map RAW and
> CONTIGUOUS. Do not compress. Do not segment. Do not stream.**

Three measured facts make this the answer:

1. **`$e000-$fff9` is the only contiguous run in the machine large enough.** It is
   8,186 bytes. The next largest is **1,478 bytes** (`$5e3a-$63ff`). A 440-row map
   needs 4,400 bytes for rows alone. Nothing else comes close, and no plausible
   rearrangement below `$d000` creates a comparable run without relocating three
   working modules.
2. **The engine needs no change to read it.** The stage map is dereferenced through
   a computed 16-bit **zero-page pointer** — `trSrc = stageMetatileRows + row*10`,
   read as `lda (trSrc),y` (`src/terrain.asm:402-435`). It is completely
   position-independent: no `absolute,X` index, no page alignment, no 256-byte
   limit. Relocating the map is one `* =` directive and one guard. **Runtime cost
   of the move: zero cycles.**
3. **Compression is measurably counter-productive here** (§10). The best cheap
   scheme tested saves ~36 % on the real Level 1 terrain, would cost a decoder plus
   a row index table to preserve the random access the scroller actually needs, and
   is unnecessary when 8,186 bytes are available for a 4,400-byte requirement.

`$e000` is untouched by the running engine — **proved dynamically**, not inferred
(§17): filled with a pattern, then survived 12 s of real gameplay *and* the
stage-end/bank-2 boss transition with zero bytes altered.

**The one real cost** is that `$e000-$ffff` lies outside the PRG's load span and a
single PRG cannot reach it (a contiguous file spanning `$d000-$dfff` would write
into I/O during load). It therefore needs a **second load file**. That is not merely
an acceptable cost — it is the natural shape for a multi-level game, and it makes
"the level package" a real, loadable artefact the editor can own.

**Second-best fallback:** raw map at `$5800`, extended through `$63ff` and onward by
relocating `trTiles`, terrain code and the VIC-bank module — a ~4.5 KB contiguous
run below `$d000` at the cost of moving three modules and still leaving almost no
growth margin. §12.

---

## 2. HEAD and working-tree state

```
$ git log --oneline -1
722dbbd HUD bank switching, token progress

$ git status --porcelain
?? reports/level-editor-current-engine-contract-review.md
?? reports/scroll-speed-1px-restoration.md
?? reports/scroll-speed-2px-per-frame-trial.md
?? reports/wave-movement-architecture-and-editor-contract.md

$ git diff --stat        <empty>
```

The 1 px/frame restoration holds: `src/` is byte-identical to HEAD.

---

## 3. Authoritative `$0000-$ffff` ownership map

Memory configuration during gameplay is **`$01 = $35`** (`src/renderer.asm:2199`):
LORAM=1, **HIRAM=0**, CHAREN=1 → **BASIC and KERNAL ROM are both banked out**, I/O is
mapped at `$d000-$dfff`. This is the fact the whole audit turns on.

Legend: **OCC** occupied · **RT** runtime-owned/undeclared · **COND** conditionally
reusable · **FREE** genuinely free · **UNC** uncertain, must not use

| range | size | owner | VIC | decl? | class |
|---|---|---|---|---|---|
| `$0000-$0001` | 2 | 6510 processor port | — | no | **RT** |
| `$0002-$00f6` | 245 | zero page, unused by the game | — | no | COND (tiny) |
| `$00f7-$00fe` | 8 | `trSrc`, `gsDst`, `gsSrc`, `scrPtr` | — | `.const` | **OCC** |
| `$0100-$01ff` | 256 | hardware stack | — | no | **RT** |
| `$0200-$033f` | 320 | KERNAL/BASIC workspace — banked out, unused | — | no | **FREE** (bank 0) |
| **`$0340-$03ff`** | **192** | **clip scratch ×3, VIC-visible sprite data** | **yes** | **NO** | **RT — trap, see §6** |
| `$0400-$07ff` | 1,024 | **screen page A** + sprite ptrs `$07f8` | yes | **NO** | **RT** |
| `$0800-$0aff` | 768 | terrain charset, codes 0..95 (zero) | yes | no | UNC (§6) |
| `$0b00-$0d3f` | 576 | terrain glyphs (generated) | yes | yes | **OCC** |
| `$0d40-$0f0f` | 464 | charset codes 168..225 (zero) | yes | no | UNC |
| `$0f10-$0f2f` | 32 | turret glyphs | yes | yes | **OCC** |
| `$0f30-$0fff` | 208 | charset codes 230..255 (zero) | yes | no | UNC |
| `$1000-$1fff` | 4,096 | **CPU-only** (char-ROM shadow, bank 0) — sched builder, HUD, SFX, sorter code | **never** | partly | OCC + 1,251 free |
| `$2000-$27bf` | 1,984 | player/muzzle/token/fireball sprites | yes | yes | **OCC** |
| `$2800-$2bff` | 1,024 | **screen page B** + sprite ptrs `$2bf8` | yes | **NO** | **RT** |
| `$2c00-$2dff` | 512 | level1 ring + dropper frames | yes | yes | **OCC** |
| `$2e00-$30ff` | 768 | **level enemy sprite window tail** — reserved capacity, currently unused | yes | no | **COND** |
| `$3100-$37ff` | 1,792 | clip scratch ×9, HUD bitmaps, boss cells, projectile | yes | yes | **OCC** |
| `$3800-$3fff` | 2,048 | **blank charset** + VIC idle byte `$3fff` | yes | **NO** | **RT** |
| `$4000-$7fff` | 16 KB | **outside both VIC banks** — main-thread code/data | never | mostly | OCC + 4,074 free |
| `$8000-$8116` | 279 | clip code | no | yes | **OCC** |
| `$8117-$85ff` | 1,257 | — | no | no | **FREE** |
| `$8600-$8aae` | 1,199 | **raster executor — deliberately immovable** | no | yes | **OCC** |
| `$8aaf-$8bff` | 337 | — | no | no | **FREE** |
| **`$8c00-$8fff`** | **1,024** | **bank-2 screen matrix + sprite ptrs `$8ff8`** | **yes (bank 2)** | **NO** | **RT — trap, §6** |
| `$9000-$9fff` | 4,096 | **CPU-only** (char-ROM shadow, bank 2) — boss + game-state code | **never** | partly | OCC + 1,928 free |
| **`$a000-$bfff`** | **8,192** | **bank-2 static mirror of `$2000-$3fff`** + terrain charset overlay `$a800`, HUD feed `$b200` | **yes (bank 2)** | **NO** | **RT — trap, §6** |
| `$c000-$cfda` | 4,059 | schedule buffers + all module state | never | yes | OCC + 2,256 free |
| `$cfdb-$cfff` | 37 | — | never | no | **FREE** |
| `$d000-$dfff` | 4,096 | **I/O** (VIC/SID/CIA/colour RAM) while `$01=$35` | — | no | **COND, high risk (§5)** |
| **`$e000-$fff9`** | **8,186** | **RAM under banked-out KERNAL — unused** | **never** | **NO** | **FREE — the recommendation** |
| `$fffa-$ffff` | 6 | hardware vectors; `$fffe` set by `installRenderer` | — | no | **RT** |

**Total free in chunks ≥ 32 B: 20,324 bytes** — but see §7: it is badly fragmented.

---

## 4. VIC-bank map

The engine uses **bank 0** (`$0000-$3fff`) for play and **bank 2** (`$8000-$bfff`)
for the boss arena. `src/vicbank.asm` switches `$dd00` via a frame-record field.

### Bank 0 — normal play

| what | where |
|---|---|
| screen matrices | `$0400-$07ff` (page A), `$2800-$2bff` (page B) |
| sprite pointers | `$07f8-$07ff`, `$2bf8-$2bff` |
| terrain charset (CB=`$0800`) | `$0800-$0fff` — glyphs 96..167 at `$0b00`, turret glyphs 226..229 at `$0f10` |
| blank charset (CB=`$3800`) | `$3800-$3fff`, idle byte `$3fff` |
| sprite data | `$2000-$27bf`, `$2c00-$30ff` (level window), `$3100-$37ff` |
| **CPU-only inside the bank** | **`$1000-$1fff`** — the VIC sees character ROM here, never this RAM |

### Bank 2 — boss arena

| what | where | evidence |
|---|---|---|
| screen matrix + sprite pointers | **`$8c00-$8fff`** (`$8ff8`) | `VB2_SCREEN`, `main.asm:163` |
| sprite data mirror | `$a000-$a7ff` | `vicMirrorStatic` copies 32 pages `$2000→$a000` |
| terrain charset overlay | `$a800-$afff` | copies 8 pages `$0800→$a800` |
| clip scratch / HUD / boss cells / projectile mirror | `$b100-$b7ff` | part of the 32-page copy |
| blank charset + idle byte `$bfff` | `$b800-$bfff` | same copy |
| HUD **dynamic** feed | `$b200+` | `vicMirrorHud`, `adc #>(HUD_SPRITES + VB2_BASE)` |
| **CPU-only inside the bank** | **`$9000-$9fff`** — character-ROM shadow | `vicbank.asm:67-70` |
| **not fetched by the VIC** | `$8000-$8bff` — chosen *around* the immovable raster executor at `$8600-$8a9f` | `vicbank.asm:75-76` |

### The two reservations the linker map does not show — verified, not repeated

Both were confirmed **on the running machine**, not from comments:

- **`$a000-$bfff` is a live mirror.** Six 32-byte windows sampled across
  `$2000-$3fff` vs `$a000-$bfff` were **6/6 identical**; three windows of the
  `$a800` terrain-charset overlay vs `$0800` were **3/3 identical**.
- **`$8c00-$8fff` is the live screen matrix.** After driving the level into
  `lvlPhase == LP_BOSS`, the first 64 bytes held **14 distinct values** — real
  matrix content, not fill.

Neither range has a KickAssembler segment. **Anything placed there is destroyed at
cold start by `vicMirrorStatic`, or overwritten by the HUD feed while the boss is up.**

---

## 5. ROM-shadow analysis

| shadow | size | accessible with `$01=$35`? | verdict |
|---|---|---|---|
| **BASIC ROM `$a000-$bfff`** | 8,192 | **Yes** — HIRAM=0 banks BASIC out, it is plain RAM | **Already in use** as the bank-2 mirror. Not available. |
| **KERNAL ROM `$e000-$ffff`** | 8,192 | **Yes** — HIRAM=0 banks KERNAL out. The engine takes the hardware IRQ vector at `$fffe` directly (`installRenderer`) and needs no KERNAL call during play. | **FREE and recommended.** VIC bank 3 (`$c000-$ffff`) is never selected, so the VIC can never fetch it. |
| **I/O / character ROM `$d000-$dfff`** | 4,096 | Only by setting CHAREN=0 (`$01=$34`), which **removes VIC/SID/CIA access** | **Conditionally reusable, not recommended** — see below |
| **Char-ROM shadows `$1000-$1fff`, `$9000-$9fff`** | 4,096 each | Always RAM to the CPU; **the VIC can never fetch either** in the banks this engine uses | **Excellent for CPU-only code/data.** Already hosts the schedule builder, HUD, SFX, sorter, boss and game-state code. |

### Why `$e000-$ffff` is safe here specifically

- **Loading:** KERNAL constraints do not apply at runtime because the KERNAL is
  banked out *after* boot. During loading `$01` is still `$37`, and on the C64
  **writes always reach RAM** at `$a000-$ffff` (ROM is read-only), so a file whose
  load address is `$e000` lands in RAM normally.
- **IRQs:** the raster IRQ vector is `$fffe`, which `installRenderer` writes itself.
  Leaving `$fffa-$ffff` out of the level package (hence `$fff9` as the top) keeps
  the vectors clear.
- **NMI:** `$fffa` is never written by the engine — pressing RESTORE would already
  be undefined behaviour today. This is a **pre-existing** latent issue, unchanged
  by anything recommended here, but worth recording.
- **Debugging/reset:** unaffected; VICE monitor reads RAM there normally (this
  audit did exactly that).

### Why `$d000-$dfff` is rejected

Reading terrain from under I/O costs `sei / $01=$34 / read / $01=$35 / cli` — only
~20 cycles per coarse row, which is *cheap*. The problem is not cost, it is that it
**blocks interrupts inside the most timing-sensitive engine in the project**.
`AGENTS.md` requires measurement before any raster-timing change, and there is no
need to take that risk for 4 KB when 8 KB is available unconditionally. Classified
**conditionally reusable, high risk, not recommended**.

---

## 6. Hidden reservations not represented by assembler segments

These are the traps this audit exists to record. **Never classify a linker-map gap
as free.**

| range | size | why it is invisible | consequence of using it |
|---|---|---|---|
| **`$0340-$03ff`** | 192 | Three of the twelve clip-scratch blocks live in the cassette-buffer tail. They are **deliberately not emitted into the PRG** (`src/clip.asm:45-51`) because the file starts at `$0801` and reaching down would drag in the stack and screen page A. | Corrupted clipped sprites — VIC-visible data, rewritten every frame |
| **`$0400-$07ff`** | 1,024 | Screen page A is written at runtime, never declared | Display destroyed |
| **`$2800-$2bff`** | 1,024 | Screen page B, same | Display destroyed |
| **`$3800-$3fff`** | 2,048 | Blank charset, zeroed by `clearCharset` at boot | The playfield aperture and the VIC idle byte break |
| **`$8c00-$8fff`** | 1,024 | Bank-2 screen matrix; no segment declares it | Boss arena display destroyed |
| **`$a000-$bfff`** | 8,192 | Bank-2 static mirror, written by `vicMirrorStatic` at cold start | Silently overwritten at boot |
| **`$2e00-$30ff`** | 768 | Reserved tail of the 20-block level enemy sprite window | Future level enemy art has nowhere to go |

Two further ranges are **uncertain and must not be used**: the zero-filled parts of
the terrain charset (`$0800-$0aff`, `$0d40-$0f0f`, `$0f30-$0fff`, 1,440 B total).
The VIC only fetches character data for codes actually present in the matrix, and
the engine only ever writes terrain and turret codes — so in principle those slots
are never fetched. That reasoning is **fragile** (one stray code, one future HUD
character, one debug row and it renders garbage), the engine deliberately keeps
them zero, and the payoff is small. Left as **UNC**.

---

## 7. Largest genuinely safe contiguous ranges

Fragmentation is the real story — total free is 20,324 B but it is in 41 pieces:

| rank | range | size | class |
|---|---|---|---|
| **1** | **`$e000-$fff9`** | **8,186** | RAM under KERNAL, never VIC-visible |
| 2 | `$5e3a-$63ff` | 1,478 | outside both VIC banks |
| 3 | `$c9ff-$ceff` | 1,281 | outside both VIC banks |
| 4 | `$8117-$85ff` | 1,257 | bank 2, not VIC-fetched |
| 5 | `$9000-$93ff` | 1,024 | char-ROM shadow, CPU-only |
| 6 | `$9ce9-$9fff` | 791 | char-ROM shadow, CPU-only |
| 7 | `$1b60-$1dff` | 672 | char-ROM shadow, CPU-only |
| 8 | `$c76f-$c95f` | 497 | outside both VIC banks |

**The largest run is 5.5× the next largest.** Excluding `$e000`, the entire machine
offers 12,138 free bytes in pieces of at most 1,478 — which is why every
alternative architecture below is a workaround for not using `$e000`.

---

## 8. The exact 440-row requirement

| | rows | map bytes | logical rows | coarse steps | duration @ 1 px/frame |
|---|---|---|---|---|---|
| Level 1 today | 105 | 1,050 | 420 | 395 | 63.2 s |
| 4-minute stage | 380 | 3,800 | 1,520 | 1,495 | 3 m 59 s |
| **target** | **440** | **4,400** | **1,760** | **1,735** | **4 m 37 s** |

Plus metatile definitions: **544 B** at today's 34 defs, **1,024 B** at the editor's
`METATILE_CAPACITY = 64`.

**Total: 4,944 B (current defs) to 5,424 B (full def set).**

> **Consistency note for the brief:** 440 rows yields **4 m 37 s**, which overshoots
> the stated "approximately 3–4 minute" goal. **380 rows is exactly 3 m 59 s.**
> 440 is therefore a generous *capacity* target rather than a duration target — which
> is fine, and the recommendation holds either way, but the two numbers in the brief
> are not the same requirement.

All 16-bit arithmetic is safe: `TERRAIN_STAGE_ROWS = 1,760`, `STAGE_START_ROW = 1,735`
— both well inside the engine's 16-bit `worldProgress`/`stageTopRow` counters, and
inside the 16-bit turret and wave-trigger row exports.

---

## 9. Architecture evaluation

### A. Raw contiguous — **recommended**

- **At `$e000`:** fits immediately. **Zero engine changes** beyond the segment
  address and its guard, because the map is read through a computed zero-page
  pointer. Cost: a second load file.
- **Below `$d000`:** no 4,400-byte run exists (largest 1,478). Creating one means
  clearing e.g. `$5800-$6980`, which requires relocating **`trTiles`** (1 KB, and it
  **must stay page-aligned** — `terrain.asm:174`), the terrain code, and the
  VIC-bank module. Feasible, but it moves three working modules, consumes most of
  the remaining scattered free space, and still leaves almost no growth margin.

### B. Raw segmented

Split the map across e.g. `$5e3a-$63ff` (1,478) + `$8117-$85ff` (1,257) +
`$9000-$93ff` (1,024) + others — **four or five segments** for 4,400 bytes.

- Row lookup becomes a range test plus per-segment base, on a path that currently
  costs one 16-bit multiply-by-10 and one add.
- Boundaries would **not** be rare: with ~1 KB segments a boundary falls every
  ~100 metatile rows, and `regenAll` at init walks 25 arbitrary rows.
- Breaks nothing in the `absolute,X` sense (there is none), but complicates the
  exporter, the editor's world-row model and every debugging session.
- **Rejected:** all the complexity of a workaround, to avoid a load file.

### C. Streaming / rolling buffer

Keep a window of rows resident and refill from backing store.

- At 1 px/frame a new coarse row is needed **every 8 frames** — a leisurely cadence,
  so the refill itself is cheap.
- But **where is the backing store?** It must still live somewhere, and the only
  place large enough is `$e000`. **Streaming from `$e000` into a buffer is strictly
  worse than reading `$e000` directly**, which the zero-page pointer already does.
- It would also interact badly with the double-page regeneration: `regenAll` and the
  stage wrap (`rowBack` folding 0 → `STAGE_ROWS-1`) both need **arbitrary** rows, not
  a sliding window.
- **Rejected: it moves the problem rather than solving it.**

### D. Compression — measured, and rejected (§10)

### E. Hybrid

The recommendation *is* a mild hybrid: raw map + definitions + encounter package in
one region, with the char-ROM shadows held in reserve for growth. A
compressed-backing-store hybrid is rejected for the same reasons as C and D.

---

## 10. Compression experiments — measured against the real Level 1 terrain

Schemes tested against `src/level1/stage_map.asm` (105 rows × 10 = 1,050 B; 34
metatile IDs; **58 distinct rows**):

| scheme | result | % of raw |
|---|---|---|
| A. run-length on identical consecutive rows | 91 runs, longest run **3** → 1,001 B | **95 %** |
| B. distinct-row dictionary + 1 index byte/row | 58×10 + 105 → 685 B | **65 %** |
| C. dictionary + RLE'd index stream | 762 B | 73 % |
| D. byte-level RLE over the flat stream | 377 runs, mean run 2.79 → 754 B | 72 % |
| E. vertical masked delta (56 % of cells match the row above) | 674 B | **64 %** |
| F. bit-pack to the 34-ID alphabet (6 bits) | 788 B | 75 % |

**Best case ~64 %, saving ~1,576 B at 440 rows (4,400 → ~2,824).**

Why that is not worth taking:

- **The saving is not needed.** 8,186 B available against a 4,400 B requirement.
- **The scroller needs random access.** `renderBackgroundRow` computes
  `rrStage = (regenTopRow + regenRow) mod STAGE_ROWS` — an arbitrary row — and
  `rowBack` folds row 0 to `STAGE_ROWS-1` at the wrap. Schemes A, C, D and E have no
  O(1) random access; restoring it needs a row-offset index (440 × 2 = **880 B**),
  which eats over half the saving.
- **Only scheme B keeps random access**, and it is the weaker of the two best
  (65 %), needs ≤ 256 distinct rows, and adds a second indirection per row.
- **Longer stages compress worse, not better.** Level 1 reuses 45 % of its rows
  across 105 rows of one biome; a 4½-minute stage with more varied content will have
  a higher distinct-row ratio.
- Decoder state, exporter complexity and a second place for terrain bugs to hide —
  against `AGENTS.md`'s explicit "avoid abstraction / prefer a small readable module".

**A methodological note, because it nearly went the other way:** the first run of
this experiment reported *every* row unique and all schemes inflating to 110-120 %.
That was wrong — the parser was reading the generated file's `// row N` comments as
data, inflating the alphabet to 105 IDs. Stripping comments before parsing gives the
table above. The conclusion (reject) survived, but for different numbers.

---

## 11. Encounter-data reservation

From `wave-movement-architecture-and-editor-contract.md`: 7 B per trigger, 10 B per
wave definition, 4 B per movement stage (pool ≤ 256 B by the one-byte `wmStage`
cursor), plus `STAGE_NO_SPAWN_ROW`.

| scale | programmes | definitions | triggers | total |
|---|---|---|---|---|
| ~50 encounters | ~140 B | 200 B | 350 B | **~690 B** |
| ~150 encounters | ~196 B | 300 B | 1,050 B | **~1,546 B** |

**Reserve 1,600 B.** Two coherent homes, both verified clean by probe:

- **Preferred — inside the level package at `$e000`.** One generated artefact, one
  load, one contract, and it keeps terrain and encounters versioned together.
- **Alternative — the bank-2 char-ROM shadow**, re-verified here from first
  principles: the VIC sees character ROM at bank-relative `$1000-$1fff` in banks 0
  and 2, so `$9000-$9fff` can **never** be fetched in either bank this engine uses.
  Free there: `$9000-$93ff` (1,024) + `$9ce9-$9fff` (791) + `$968f-$96ff` (113) =
  **1,928 B**. The previous review's suggestion is **confirmed correct**.

---

## 12. Recommended memory contract

| item | address | size | notes |
|---|---|---|---|
| `stageMetatileRows` | `$e000` | 4,400 | 440 × 10, raw, contiguous |
| `metatileDefs` | `$f130` | 1,024 | 64 defs × 16; **read once at init**, transposed into `trTiles` |
| encounter package | `$f530` | 1,600 | triggers, definitions, programme pool, masks, `STAGE_NO_SPAWN_ROW` |
| *(spare)* | `$fb70-$fff9` | **1,162** | growth |
| *(untouched)* | `$fffa-$ffff` | 6 | hardware vectors |

**Loaded as a second file** with load address `$e000`; the engine's boot path calls
KERNAL LOAD for it *before* `installRenderer` (while `$01` is still `$37`), then
proceeds as now.

**Nothing needs to move.** `$5800-$5e39` is vacated by the map's departure, giving
back `$5800-$63ff` = **2,560 contiguous bytes** below `$d000` as a bonus.

**Required engine changes** (small, and none in the hot path):
1. `src/terrain.asm`: the map `* =` and its `> $6000` guard.
2. A boot-time KERNAL LOAD call for the level file.
3. `Makefile`/`d64`: emit and write two PRGs.

**Required exporter/editor changes:**
1. Emit the map to its own file/segment at `$e000`.
2. Compute `MAX_STAGE_ROWS` from the region size rather than the stale
   `ENGINE_MAX_STAGE_ROWS = 768`.
3. (Later) emit the encounter package into the same region.

**Expected runtime cost: zero.** The map is already read through a computed
zero-page pointer; only the pointer's base changes. No extra cycle per coarse row,
per frame or per page regeneration. The 1 px/frame regeneration budget (25 rows over
7 of 8 frames, ~3,619 cycles/frame average, 18 % of the frame — measured in the
2 px trial) is **completely unaffected**.

### Second-best fallback

Raw map at `$5800`, extended to ~`$6980` by relocating `trTiles` (to a page-aligned
home such as `$ca00-$cdff`), the terrain code and the VIC-bank module. Yields ~4.5 KB
contiguous, keeps a single-file PRG, but moves three working modules, leaves
essentially no growth margin, and still has nowhere coherent for the encounter
package. Choose it only if a second load file is judged unacceptable.

---

## 13. Remaining headroom under the recommendation

| | bytes |
|---|---|
| spare inside the level package (`$e000`) | **1,162** |
| freed by the map leaving `$5800` | **1,478** → merges to `$5800-$63ff` = **2,560 contiguous** |
| char-ROM shadow, held in reserve (`$9000`/`$9ce9`/`$968f`) | **1,928** |
| bank-2 non-fetched (`$8117`, `$8aaf`) | **1,594** |
| `$c000-$cfff` state area | **2,256** |
| other `$4000-$7fff` gaps | ~2,600 |
| **total free after the move** | **~20,300** (unchanged; it is redistributed, not consumed) |
| **largest contiguous after the move** | **2,560 B** (`$5800-$63ff`) |

Growth is covered: definitions to the editor's 64-def cap are already budgeted;
encounter data has 1,600 B budgeted plus 1,928 B in reserve; sound/music and future
boss content have the `$5800-$63ff` and `$8117-$85ff` runs.

---

## 14. Runtime and cycle implications

| | figure | measured or estimated |
|---|---|---|
| coarse row cadence at 1 px/frame | one per **8 frames** | measured (1 px restoration probe: `gaps=[8]` over 24 steps) |
| back-page regeneration | `ROWS_PER_TICK = 4`, 25 rows over 7 of 8 frames | measured |
| regeneration cost | ~1,158 cycles/row; peak ~4,630; **average ~3,619 cy/frame (18 %)** | engine's own documented figure; the 2 px trial confirmed the 2× scaling |
| map read per coarse row | 10 × `lda (trSrc),y` + one 16-bit ×10 | measured from source |
| **cost of relocating the map to `$e000`** | **0 cycles** | computed pointer, position-independent |
| cost of option B (segmented) | +range test per row lookup | estimated |
| cost of option D (compressed) | decoder + 880 B index to keep random access | estimated |

The 2 px/frame failure is the relevant precedent: it showed the engine has under
~3,600 spare cycles/frame. **The recommendation adds none.**

---

## 15. Risks and unresolved uncertainties

| risk | severity | mitigation |
|---|---|---|
| **Two-file load** — build, d64 layout and boot sequence all change | medium | Contain it in one boot step before `installRenderer`, while the KERNAL is still mapped. It also buys multi-level loading. |
| **RESTORE/NMI** — `$fffa` is never written and the KERNAL is banked out | low, **pre-existing** | Unchanged by this proposal. Worth fixing independently (point `$fffa` at an RTI). |
| Level package must not overrun into `$fffa` | low | Assembly-time guard, exactly like the current `> $6000` guard |
| `trTiles` page alignment | low | Only relevant to the *fallback*, not the recommendation |
| 440 rows = 4 m 37 s vs the "3–4 minute" goal | — | Decide capacity vs duration; 380 rows = 3 m 59 s |
| `$0800-$0fff` charset slack (1,440 B) classified UNC | low | Left unused; revisit only if desperate |
| `$d000-$dfff` RAM (4,096 B) rejected on IRQ-latency risk | low | Documented; would need measurement per `AGENTS.md` |

**Nothing in the recommendation rests on an unproven assumption about free memory.**
Every region relied upon was fill-tested on the running machine.

---

## 16. Staged implementation roadmap — not implemented

| # | stage | model | proof |
|---|---|---|---|
| **1** | **Two-file build and boot load.** Emit an empty/placeholder `$e000` file, write both to the d64, add the KERNAL LOAD call before `installRenderer`. Terrain still at `$5800`. | **Opus 5 High** — boot sequencing and memory config | Game runs identically; `make test` unchanged; manual VICE identical |
| **2** | **Relocate the existing 105-row map to `$e000`**, unchanged content. Update the guard. | **Opus 5 High** — segment/guard + verifying the zero-page pointer path | **Byte-equivalence:** assembled `stageMetatileRows` bytes identical; `test-boss`/`test-turret-regression` pass; a probe asserts every one of the 25 displayed rows matches the pre-move page content at the same `worldProgress`; manual VICE identical |
| **3** | **Exporter emits the map to the new region** and derives `MAX_STAGE_ROWS` from the region size. | **Sonnet 5** — bounded Python | Re-export Level 1 → **byte-identical** to stage 2's file |
| **4** | **Author and run a long stage** (380 or 440 rows). Exercise the 16-bit row arithmetic, the wrap, turret rows and stage end at scale. | **Sonnet 5** | Full non-warp playthrough; `scrollLate`/`gameOverrun` zero; stage completes at the derived row |
| **5** | **Reserve and populate the encounter package** at `$f530`, once the wave contract lands. | **Opus 5 High** (engine) + **Sonnet 5** (exporter) | Per the wave-contract roadmap |

**Migration/testing strategy for Level 1** is stage 2's whole point: prove
byte-and-spatial equivalence on the existing 105-row stage *before* any 440-row
content exists, so a later failure can only be content, never plumbing.

---

## 17. Build, probe and VICE evidence

**Build:** clean, 0 errors. PRG `$0801-$cfda`, 51,162 bytes, sha256 `cbaeb0f4…`.

**Dynamic ownership probe** (disposable scratch). Every candidate region filled with
an alternating `$5a/$a5` pattern, then subjected to **12 s of free-running gameplay**
and **the stage-end → bank-2 boss transition** (`lvlPhase` driven to `LP_BOSS`,
confirmed reached), then scanned byte by byte:

```
ok  the probe actually drove the level into the bank-2 boss arena -- highest lvlPhase seen = 2
ok  $0200-$033f  below the clip scratch     [ 320 B] untouched -- CLEAN
ok  $2e00-$30ff  level enemy window tail    [ 768 B] untouched -- CLEAN
ok  $5e3a-$63ff  above the terrain map      [1478 B] untouched -- CLEAN
ok  $8117-$85ff  bank2, below raster exec   [1257 B] untouched -- CLEAN
ok  $8aaf-$8bff  bank2, above raster exec   [ 337 B] untouched -- CLEAN
ok  $9000-$93ff  char-ROM shadow            [1024 B] untouched -- CLEAN
ok  $968f-$96ff  char-ROM shadow            [ 113 B] untouched -- CLEAN
ok  $9ce9-$9fff  char-ROM shadow            [ 791 B] untouched -- CLEAN
ok  $cfdb-$cfff  above the PRG              [  37 B] untouched -- CLEAN
ok  $e000-$fff9  RAM under KERNAL           [8186 B] untouched -- CLEAN
ok  $a000-$bfff is a live mirror of $2000-$3fff -- 6/6 sampled windows identical
ok  $a800-$afff carries the terrain charset overlay -- 3/3 identical
ok  $8c00-$8fff holds the bank-2 screen matrix -- 14 distinct bytes in the first 64
=== ALL PASS ===
```

**Source evidence** for the position-independent map read: `src/terrain.asm:402-435`
(`trSrc = stageMetatileRows + rowBase*10`, `lda (trSrc),y`) and `:299-318`
(`metatileDefs` transposed once into `trTiles`). **Memory configuration:**
`src/renderer.asm:2199` (`lda #$35 / sta $01`). **Undeclared clip blocks:**
`src/clip.asm:45-57, 297-305`. **Bank-2 mirror:** `src/vicbank.asm:306-320`.

**VICE hygiene:** `pgrep -fl x64sc` confirmed a clean field before the run; the probe
launched and reaped exactly one instance (**pid 4125**) and reported it; `pgrep`
afterwards confirmed none remained. `-console`, no focus stolen, no broad
`pkill`/`killall`, no user session touched.

---

## 18. Final git status and disk usage

```
$ git status --porcelain
?? reports/definitive-440-row-memory-audit.md
?? reports/level-editor-current-engine-contract-review.md
?? reports/scroll-speed-1px-restoration.md
?? reports/scroll-speed-2px-per-frame-trial.md
?? reports/wave-movement-architecture-and-editor-contract.md

$ git diff --stat        <empty>

$ du -sh build/    96K
$ du -sh .         7.8M
```

Scratch (400 K, outside the repository) holds the ownership probe, the compression
experiments and the map-generation script. Temporary files were removed. **All four
pre-existing untracked reports are preserved.**

---

## 19. Confirmation

**Nothing was committed. Nothing was pushed. No production file was modified** —
`git diff` against HEAD is empty. No data was relocated, no scroller code changed, no
level format altered, no generated file touched, and the recommendation is **not**
implemented.

### Corrections to earlier reports, stated explicitly

1. The **first** memory review treated `$9cec-$bfff` as ~8.9 KB free. **Wrong** —
   `$a000-$bfff` is the bank-2 mirror. Already corrected in the wave review and
   re-confirmed here by live sampling.
2. The **wave review** proposed the char-ROM shadow for encounter data. **Confirmed
   correct** from first principles and by probe.
3. The wave review also stated that **no contiguous run large enough for a 440-row
   map exists**, calling long-level storage "a genuine open question". **That is now
   answered:** `$e000-$fff9` provides 8,186 bytes. The earlier audits simply never
   examined RAM under the banked-out KERNAL — the single most valuable region in the
   machine for this purpose, and invisible to the linker map.
