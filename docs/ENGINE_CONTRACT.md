# Engine contract

The rules game code must obey. Every number here was read out of `src/` when
this was written; if code and this document ever disagree, **the code is the
truth** and this document is the bug.

`tests/test_engine.py` restates the same numbers independently and checks them
against the running machine. Changing one means changing the contract, which is
a decision — not a test to adjust.

---

## 1. How game systems talk to the renderer

```
game logic  ->  logical sprite arrays  ->  sorter -> builder -> publication
                                                                     |
                                                        immutable CURRENT
                                                                     |
                                                           raster executor -> VIC
```

Game code writes **logical sprite state** (`logY`, `logX`, `logXHi`, `logPtr`,
`logCol`, `logCount`) and nothing else. It does not choose hardware slots, batch
lines, raster timing or `$d015`.

**No game system may mutate a published CURRENT schedule.** The architectural
test, inherited from the engine and still true: *if the main thread stopped dead
immediately after publication, the frame would still render correctly.* The
executor reads CURRENT and nothing else — not object state, not allocation
state, not a sorter.

Building and publishing is `sortTick` → `buildSchedule` → `publishSchedule`, in
that order, once per frame, from the main thread.

## 2. Hardware sprite slots

```
HW0        reserved — future player base
HW1        reserved — future player overlay
HW2-HW7    gameplay multiplex pool, time-shared with the top-border HUD
```

`MUX_FIRST_SLOT = 2`, `MUX_SLOTS = 6`. Accepted sprite *i* uses slot
`2 + (i mod 6)`, and its same-slot predecessor is accepted entry *i-6*.

## 3. Sprite admission rules

| rule | value | meaning |
|---|---|---|
| `MIN_SPRITE_Y` | **55** | below this a sprite is loose in the open border, over the HUD, and can ghost at Y+256 |
| `MAX_SPRITE_Y` | **226** | above this its DMA reaches the lines the bottom aperture split needs free |
| `SPRITE_HEIGHT` | 21 | hardware |
| `REUSE_LEAD` | 12 | rasters of lead a batch gets before its own sprite's Y — **measured, not chosen** |
| `MIN_REUSE_GAP` | 33 | `SPRITE_HEIGHT + REUSE_LEAD`; two sprites sharing a slot must be at least this far apart in Y |
| `MAX_LOGICAL` | 32 | logical pool |
| `MAX_SCHED` | 24 | schedule capacity; deliberately smaller than the pool so overflow is testable |

A sprite outside the Y range is **rejected and counted** (`statRejRange`), never
clamped. Clamping would move a sprite the caller placed deliberately.

**A VIC sprite at Y=n is displayed on rasters n+1 .. n+21**, not n .. n+20. That
off-by-one is why the HUD sits at Y=16 and not 18.

## 4. Raster phase schedule

Every phase is an interrupt; `exPhase` says which. `PH_BATCH` is 0 so the
dispatch reaches a mid-screen batch in eight cycles.

```
raster   4   exHud       program HW2-HW7 as the HUD, enable, arm 40
raster  40   exHandoff   restore gameplay sprite modes, run batch 0, enable
raster  53   exTop       poll to 55 (54 at YSCROLL=7), switch to the REAL charset
raster 68+   exBatch     mid-screen multiplex batches
raster 243   exBottom    hold the vertical border open, poll to 248, blank charset
raster 250   exFrame     ADOPTION ONLY: frame record, schedule, page, $d015 = 0
```

**`frameEntryLine == 250` on every frame is the engine's oldest invariant.** It
is checked by every suite here. A frame transaction that runs anywhere else
rewrites `$d011`, `$d018`, the pointer destination and `$d015` in the middle of
the display.

Structural phases are **never chased** when late, with one exception: a late
`PH_TOP` runs immediately, because skipping it would leave the blank charset
selected for a whole frame — a black screen.

## 5. HUD ownership

The HUD owns **HW2-HW7 only** between rasters 4 and 40, and hands them back
completely. HW0/HW1 are never touched by either side.

`exHandoff` writes, unconditionally, every register the HUD might have dirtied:
`$d017`, `$d01b`, `$d01c`, `$d01d`, then batch 0 sets per-slot X/Y/colour/
pointer and the complete `$d010`, and `$d015` is written **last** — after the
slots are programmed, never before.

`$d017` is the one register the HUD may not use: Y expansion doubles a sprite's
DMA span, and a Y-expanded HUD at Y=16 would fetch until line 58 — through the
handoff and into the aperture.

`$d025`/`$d026` are unreachable rather than unused: `$d01c` is forced to zero on
both sides, so every sprite is hires. If gameplay ever enables multicolour, they
join the handoff contract that day.

**The Y+256 ghost.** Sprite Y is compared against the low byte of the raster, so
the HUD's Y=16 matches again at raster 272. `exFrame` clears `$d015` at raster
250 and nothing sets it until `exHud` at raster 4, so the ghost compare passes
with nothing enabled. **Never enable a sprite between rasters 250 and 4.**

## 6. HUD bitmap preparation

`exHud` points the VIC at bitmaps that are already finished. It formats nothing,
converts nothing and draws nothing, and costs 434 cycles whatever the HUD says.

Bitmap RAM is written by the **main thread**, and only inside a window where the
VIC cannot be reading it:

```
the VIC fetches HUD sprite data on rasters 16..37, and nowhere else
hudUpdate refuses to start outside rasters HUD_SAFE_LO=56 .. HUD_SAFE_HI=200
hudUpdWrapped counts any update that left the frame -- it must read zero
```

`hudUpdate` is called from the main loop's **idle spin**, not the once-per-frame
block: that block reaches the same point at about raster 10, inside the fetch
window, and would defer every frame.

Components mark themselves dirty (`HUD_DIRTY_LIVES/HEAT/SCORE/UPGRADE`). With
nothing dirty the whole update is `lda hudDirty / bne / rts` — eleven cycles.

Lives (0..5) and upgrade (0..3) have a precomputed bitmap per value, so changing
them writes **one byte** of `hudPtrLive`, which is atomic against the interrupt
that reads it.

## 7. Page and pointer ownership

Two screen matrices, `SCREEN_A = $0400` and `SCREEN_B = $2800`, with sprite
pointer tables at `$07f8` and `$2bf8`. They share the low byte `$f8`, so **one
patched byte** selects the destination.

`exFrame` patches both pointer-writing instructions — the batch executor's and
the HUD's — from the same frame record, at the same instant it decides `$d018`.
Two stores, one source, one decision.

**Only the currently adopted page's pointer table is ever written.** Never write
both "to be safe": that is how a page flip produces a one-frame mismatch.

## 8. Scroller and aperture

The vertical border is held **open** all frame (the flip-flop is made to miss
both close comparisons), so the HUD can live in the top border. An open border
clips nothing, so the playfield is clipped by a **blank character set** instead:

```
BLANK_CHARSET = $3800     2 KB of zeros; also supplies the VIC idle byte at $3fff
real charset  = $1000     the character ROM image the VIC sees in bank 0

$d018 values:  A real $14   A blank $1e
               B real $a4   B blank $ae

raster  55   exTop     blank -> real      (54 at YSCROLL=7: see exTop)
raster 248   exBottom  real  -> blank
visible terrain = rasters 55..247, 193 lines
```

Matrix rows 0 and 24 carry ordinary terrain. There are **no blank guard rows**,
and reintroducing them would bring back the 6.25 Hz edge pop they caused.

The scroller publishes a **frame record** (fine scroll, `$d018`, pointer
destination, page) with the same atomic-publication discipline as the schedule;
the frame IRQ adopts it at raster 250 and the executor never asks the scroller
anything.

## 9. Direct VIC access — who owns what

| register | owner | who may write it |
|---|---|---|
| `$d000-$d010`, `$d015`, `$d017`, `$d01b`, `$d01c`, `$d01d`, `$d027-$d02e` | the renderer | `src/renderer.asm` only |
| sprite pointer tables | the renderer | `exPtrStore` and `huPtrStore`, both in the renderer |
| `$d011`, `$d018` | the renderer's frame transaction and the two aperture splits | `src/renderer.asm` only |
| `$d020`, `$d021`, colour RAM | boot | `src/main.asm`, once |

**Game logic must not bypass these owners.** `src/hud.asm` is the model for how
a new subsystem participates: it owns HUD *data* and writes not one VIC
register; the code that touches the VIC lives in the renderer beside the handoff.

The previous project accumulated thirteen independent writers of `$d015` and
became unreasonable. Do not repeat that.

## 10. Known deferred performance issue

**`RING-SLOW` and `RING-SHIFT` show visibly jerky motion and background glitching
under their 16-sprite moving workload.** Measured as frame-record publication
skips of roughly 12 % on those two modes; `RING-FAST`, `MAXCAP` and every
lighter fixture measure zero.

This is a **known deferred performance issue, not an engine correctness
failure**. A skipped frame record drops one frame of scroll — fine scroll, page,
pointer destination — and is adopted at the next raster 250. The *sprite*
schedule has no skip path and is never dropped, stale or corrupted by it.

It correlates with frame-record publication under high-batch moving workloads
and it is **not** caused by the HUD: measured with the HUD phase bypassed
entirely, and with the HUD demo stubbed out, the rate is unchanged.

**Do not optimise it opportunistically.** It is to be revisited with realistic
production scenes at roughly **6 / 8 / 10 / 12 / 14 / 16** gameplay sprites, so
the budget is measured against a real load rather than a torture fixture.

`FIX16 / MAXCAP` is an intentionally abusive stress ceiling — 30 logical sprites,
24 accepted, 19 batches — and is **not a production optimisation target**. Its
historical visual glitch has varied as the raster phases changed and may
currently be clean. Use it to detect *new* catastrophic corruption, nothing else.
