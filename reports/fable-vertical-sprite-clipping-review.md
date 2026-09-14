# Fable review — vertical sprite clipping with the border HUD preserved

Independent adversarial review. **No production code changed**; `make build` clean.
Source was read directly; the earlier investigation was *not* inherited — and it
was wrong on one point (it dismissed `$d01b` masking for a reason that does not
hold; see Q3–Q7). The masking technique is hardware-valid. It is still not
usable here, for two different reasons established below.

## 1. Facts from source (authoritative where comments disagree)

| item | value | source |
|---|---|---|
| playfield | rasters **55..247** (`TOP_SPLIT_LINE`=55, `BOT_SPLIT_LINE`=248) | main.asm:132-140 |
| sprite raster mapping | Y=n displays on rasters **n+1 .. n+21** (*measured*, Slice 3) | hud.asm:76-79 |
| admission | `MIN_SPRITE_Y`=55 .. `MAX_SPRITE_Y`=226, Y only, reject never clamp | renderer.asm:115-116, 590-596 |
| ⇒ fully inside | Y 55..226 → rows 56..247 | derived |
| ⇒ **top straddle** | Y **34..54** (rows cross line 55); fully hidden Y ≤ 33 | derived |
| ⇒ **bottom straddle** | Y **227..246** (rows cross line 247); fully below Y ≥ 247 | derived |
| graphics mode | multicolour text (MCM set in `$d016`), ECM off | terrain.asm:312-314 |
| colour RAM | **uniformly 9** = MC flag + colour 1, every cell | terrain.asm:58, 277-286 |
| `$d022` / `$d023` | 15 / 11, set once at init | terrain.asm:302-305 |
| char codes in use | 96..167 (terrain), 226..229 (turrets); **255 never used** | main.asm:29-32 |
| blank charset | `$3800-$3fff` all zero; **`$3fff` is the VIC idle byte**, deliberately zeroed | main.asm:46-47, 104-110 |
| VIC bank | 0 (`$0000-$3fff`); `$1000-$1fff` is char ROM to the VIC | main.asm:35-38 |
| priority today | handoff writes `$d01b`=**$00** (in front); HUD writes **`HUD_D01B`=%11111100 (behind)** | renderer.asm:1353, 1290-1291 |
| HUD | HW2–HW7, `HUD_Y`=16 → rasters 17..37; programmed at raster 4 | hud.asm:79,87; renderer.asm:164 |
| handoff (HUD→gameplay, batch 0) | armed raster **40**, measured exit **as late as 51**, "the tightest margin in the engine" | renderer.asm:176, 1253-1255 |
| top split margin | both stores on 55 in cycles 6..12 / 10..16; "**five cycles is the entire margin**"; already misses ~1% at YSCROLL=7 from HW0–2 DMA alone | renderer.asm:1657-1668, 1704-1706 |
| bottom split margin | `$d018` must beat cycle 15 of line 248; only thief is HW3–7 DMA in cycles 0..9 | renderer.asm:1541-1547 |
| sprite DMA windows | HW3–HW7: cycles **0..9 of their own line**; HW0–HW2: cycles 57..62 of the **previous** line | renderer.asm:1546, 118-121 |
| enemy art | one hires shape, 21×3 bytes, generated at assembly time from a script list (`enemyMC`) | enemy.asm:226-243 |

Two conventions coexist in comments (display n..n+20 in renderer.asm, n+1..n+21
measured in hud.asm). Every conclusion below survives either; the bands simply
shift together.

## 2. The HW2–HW7 lifecycle, traced

```
raster   4  exHud      HW2-7 ← HUD geometry/pointers; $d01b=%11111100; $d015=HUD|player
      17-37             HUD DISPLAYED (six sprites, "behind", visible over background idle lines)
raster  40  exHandoff  $d017/$d01b/$d01c/$d01d ← $00; batch 0 reprograms HW2-7 for gameplay;
                        $d015 ← schedEnable AFTER batch 0   (exits 45 typ, 51 worst)
raster  53  TOP_ARM → 55 exTop   $d018 real charset, $d021 level colour
  55..247   mux batches, REUSE_LEAD 12, slot 2+(i mod 6)
raster 243  exBottom arms (RSEL trick keeps border open) → 248: $d018 blank, $d021 black
raster 250  exFrame    $d015 ← 0; NEXT adopted; → raster 4
```

Restore points for any priority scheme already exist (handoff at 40, exHud at 4).
No new restore would be needed. That is not what blocks the idea.

## 3. The `$d01b` questions, answered from the VIC-II reference

Reference: C. Bauer, *The MOS 6567/6569 video controller*, §3.7.3.9 (idle
state), §3.15 (priority), §3.7.3.2 (multicolour text). Quotes were fetched, not
recalled.

1. **Dynamic, per pixel.** Foreground pixels that overlap non-transparent sprite
   pixels "inherit the priority of the sprite" as they are output. Not latched.
2. **Yes.** A mid-sprite `$d01b` write changes priority for every later row/pixel.
3. **Opaque = a *foreground* graphics pixel**, regardless of its colour: hires
   '1' bits; MC pairs `10`/`11`. A **black** foreground pixel hides a behind
   sprite just as well as a coloured one.
4. **Terrain is not a reliable mask** — wherever it is empty (pairs `00`/`01`)
   a behind sprite shows straight through.
5. **Yes, a dedicated opaque region is required**, and it *can* be built:
6. On `00` (and MC `01`) pixels a behind sprite is **visible**. This is exactly
   why the HUD — set "behind" — is visible today: the top-border lines are
   background.
7. **A visually-black, logically-foreground mask exists in hardware:**
   - *Idle lines* (rasters 0..47+YSCROLL and 248+YSCROLL..311): the VIC renders
     `$3fff`; in idle state '1' bits are drawn **black** (§3.7.3.9). Setting
     `$3fff = $FF` turns every idle line into solid black foreground. Cost: one
     byte. Char 255 is unused, so the blank charset's last row is free to hold it.
   - *Matrix lines through the blank charset* (48+YSCROLL..54 and
     248..247+YSCROLL): replace the all-`$00` blank charset with all-`$AA`
     (pairs `10`). Colour RAM is uniformly MC, so every cell renders pair-10
     foreground in `$d023`; switch `$d023` to 0 at 248 and back to 11 at 55.
     Visually black, opaque to behind sprites.
   - The HUD's `$d01b` would flip from "behind" to "in front" (it is set behind
     only to exercise the handoff's restore — hud.asm:90-93).
   So the earlier report's "idle lines have no foreground" was wrong.
8. Lines: gameplay bits 2..7 → **behind** at the handoff (40), → **front** at
   the top split (55), → behind at the bottom split (248). `$d023` at 55 and 248.
9. Register writes themselves are badline-safe (exTop already dodges the
   YSCROLL=7 badline by splitting on 54, an idle line).
10. Two extra 4-cycle stores per split (`$d01b`, `$d023`): 8 cycles each edge.
11. **No — but not because of the stores.** See §4.
12–14. Priority per incarnation is fine (written at 4 and at 40). The conflict is
    the **slot**, not the register: HW2–7 *are* the HUD until raster 37 and are
    not reprogrammed for gameplay until 40–51. See §4.
15. `$d01b` is global executor state, never per-entry: CURRENT stays immutable,
    reuse rules untouched. LOW.
16. **In principle yes at both edges. In this engine, no** — §4.

## 4. Why the hardware mask still fails here — two independent blockers

### Blocker A — the straddle bands *are* the split-DMA bands

A sprite in HW3–HW7 steals cycles 0..9 of **every raster its rows occupy**. Both
splits need cycles 0..14 of *their* line for `$d018` (`exTop` has five cycles of
margin total and already loses ~1% of frames to HW0–2 DMA at one scroll phase;
`exBottom` has the same shape).

```
top straddle    Y 34..54   ⇔  rows cover line 55   ⇔  DMA in cycles 0..9 of line 55
bottom straddle Y 227..246 ⇔  rows cover line 248  ⇔  DMA in cycles 0..9 of line 248
```

The correspondence is exact and structural: a 21-row sprite that straddles the
visible edge necessarily has a row on the split line. `exTop` says so itself:
*"the only remaining hazard is a sprite in HW3..HW7 already active at line 55
(Y ≤ 54), which would own cycles 0..9 … the MIN_SPRITE_Y admission rule removes
the possibility by construction."* Admitting straddlers puts one to five sprites'
DMA (up to ~13 stalled cycles counting BA-low lead-in) in front of the `$d018`
store on precisely the frames a mask would be needed — the leftmost characters
of line 55 render from the blank charset, or line 248 shows terrain. Only HW2
(fetched at the end of the previous line) is exempt, and round-robin
`2+(i mod 6)` cannot promise HW2. Any allocator that could would be the adaptive
allocator this review is told not to propose.

### Blocker B — the top slots are the HUD's until raster 37–51

Even with the mask perfect, a top straddler at Y 34..54 must have its HW2–7
registers written before raster Y. Those registers hold the HUD until its last
row at 37; batch 0 rewrites them at 40 and exits as late as **51**. The earliest
gameplay Y that is programmed reliably is ~52. So the mask could reveal at most
**rows 52..54 — three rows** of a 21-row sprite. That is not progressive entry;
it is the same pop three pixels earlier. Moving the handoff earlier than the
HUD's last fetch is impossible; moving the HUD up into the vertical blank is a
HUD-visibility gamble the brief forbids.

**Conclusion of §3–4:** `relax admission + opaque mask + two $d01b writes` is a
sane VIC-II technique — and it is disqualified in this engine by the split cycle
budgets at both edges (A) and, at the top, additionally by slot sharing with the
border HUD (B). Neither is a margin that tuning could recover: A is a raster
identity, B is the HUD staying where the brief says it stays.

## 5. The other classes, briefly

- **Relaxed admission alone:** draws enemies over the black band/HUD (open border
  clips nothing) *and* triggers Blocker A. Rejected.
- **`$d015` gating:** Bauer §3.8.1 — DMA starts only when `MxE` is set *and*
  raster==Y; it stops only when MCBASE reaches 63. Disabling before Y gives total
  absence, not partial entry; clearing after start neither blanks rows nor stops
  the DMA that starves the split. Rejected (verified, not inherited).
- **Raster-time Y rewrite:** repositions for reuse; cannot remove rows already
  scheduled, and moving Y across a split line re-creates Blocker A. Rejected.
- **Bitmap/character overlay inside the playfield:** irrelevant — the excess
  rows are *outside* it, and Blocker A stands.
- **Border tricks:** the bottom border cannot close while the top-border HUD is
  open (one flip-flop, cleared only at 51/55). Forbidden anyway.
- **Closing the border / moving the HUD:** disqualified by the brief.

## 6. Ranked approaches

| # | approach | top | bottom | raster | memory | complexity | mux risk | HUD risk | content burden |
|---|---|---|---|---|---|---|---|---|---|
| **1** | **Pre-clipped variants + presented-Y clamp** | **row-accurate** | **row-accurate** | **none** | 40 blocks (2.5 KB) at 1-row, 20 at 2-row, single shape | MEDIUM | **NONE** — presented Y always 55..226 | NONE | LOW now (assembly-generated); HIGH if animated |
| 2 | `$d01b` + opaque idle/`$AA` mask + relaxed admission | 3 rows only (Blocker B) | breaks split (A) | 8 cyc/split + split misses | ~0 | MEDIUM | HIGH | LOW | none |
| 3 | Content-side (avoid vertical exits) | pop | pop | none | 0 | LOW | none | none | forbids bottom dives — **temporary only** |

### How #1 works, and why it is the only one that respects every invariant

Enemy true Y stays exactly what movement/collision use today (`logY`). Only the
*presented* sprite changes:

```
top,    true Y = n in 34..54 :  presented Y = 55,  bitmap = enemy shifted UP by (55-n),  bottom (55-n) rows blank
bottom, true Y = n in 227..246: presented Y = 226, bitmap = enemy shifted DOWN by (n-226), top (n-226) rows blank
otherwise:                      presented Y = n,   bitmap = base
```

- Presented Y never leaves 55..226 → **no DMA on 55 or 248, ever** (Blocker A
  cannot arise); legality window, `MIN_REUSE_GAP`, batching, `2+(i mod 6)` all
  operate on presented Y unchanged; CURRENT/NEXT untouched in shape.
- Top entry at presented Y=55 is programmed by batch 0 in the ordinary handoff
  (Blocker B cannot arise).
- Bounded change: one signed per-object byte `logYAdj` (zeroed with the slot),
  `clc/adc logYAdj,x` where the builder copies Y into `schedY` (5 cycles/entry,
  renderer.asm:675), and ~30 cycles in `enemyTick` to pick `logYAdj` + `logPtr`.
  Collision keeps reading `logY` (true). `$d01b`, splits, HUD: untouched.
- Variants are generated **at assembly time** from `enemyMC` by the same
  KickAssembler loop that emits the base — no tooling, no artist step, cannot
  drift. 20 up-shifts + 20 down-shifts = 40 × 64 B = **2560 B**, single shape,
  no animation. Two-layer enemies would double it; a 4-frame animation would
  quadruple it (→ then generate at 2-row granularity, or shift at runtime for
  the ≤2–3 straddlers per frame at ~600 cycles each).
- **VIC bank 0 room today:** `$3000-$31ff` (8 blocks), `$3700-$37ff` (4),
  `$3680-$36bf` (1) = 13 blocks. Reaching 40 needs one of: relocate the raster
  executor `$2c00-$3093` out of the bank (the VIC never fetches code; a
  label-based ORG move frees 24 blocks — address change, not logic change), or
  2-row granularity (20 blocks: ≈1 px steps at ≤1.5 px/frame, visually
  smooth), or top-only first (20 blocks). `$8000-$bfff` is empty for the code.
- Historically this is exactly what open-border/sprite-panel C64 games did:
  clamp the coordinate and swap pre-clipped frames; priority masks were used for
  sprites passing *behind scenery*, not for playfield edges, because border and
  idle areas are background by default. Sane technique.

## 7. Hygiene

```text
$ du -sh build/   88K     build/
$ du -sh .        4.4M    .
$ git status --short
 M Makefile
 M src/enemy.asm
 M src/movement.asm
 M src/waves.asm
 M tests/test_encounter_director.py
?? reports/encounter-director-v1.1-flight-paths.md
?? reports/enemy-ingress-egress-spacing.md
?? reports/vertical-sprite-edge-clipping-investigation.md
?? tests/test_flight_paths.py
?? tests/test_ingress_egress.py
$ git diff --stat
 5 files changed, 982 insertions(+), 266 deletions(-)
```
All of that is the previous slices' uncommitted work. This review added only
this file. No VICE launched; no commit; no push.

---

**NO SAFE HARDWARE MASK FOUND — RECOMMEND: pre-clipped vertically-shifted
enemy sprite variants with a presented-Y clamp to 55..226 (assembly-generated,
one `logYAdj` byte per object, one add in the builder), starting at 2-row
granularity within existing bank-0 space or after relocating the raster executor
out of bank 0 for 1-row.**

The `$d01b`/opaque-mask technique is hardware-correct and the earlier report was
wrong to dismiss its mechanism; it is nonetheless unusable here because every
straddling sprite in HW3–HW7 lands DMA on the very raster each split must own,
and the top slots belong to the HUD until raster 37–51.

```text
BORDER HUD STAYS
OPEN VERTICAL BORDER STAYS
SIX GAMEPLAY MUX SLOTS STAY
BOTTOM-DIVING ENEMIES STAY
IMMUTABLE RENDER SCHEDULE STAYS
```
