# Vertical sprite edge clipping — architecture investigation

Investigation only. **No production code was changed**; `make build` is clean.

## The one-sentence answer

The sides clip because the **horizontal border is closed** and the VIC does it
for free. The top and bottom pop because this engine **deliberately holds the
vertical border open** so a HUD can live above the playfield — and an open
vertical border clips nothing. The "aperture" is a `$d018`/`$d021` colour and
charset illusion, not a clipping boundary. Every technique that could clip rows
at the two vertical edges is blocked either by that (top) or by the bottom
split's cycle budget (bottom).

## Established geometry

| item | value | source |
|---|---|---|
| top split / first terrain line | raster **55** | `TOP_SPLIT_LINE`, main.asm:132 |
| bottom split | raster **248** | `BOT_SPLIT_LINE`, main.asm:133 |
| last terrain line | raster **247** | `APERTURE_BOT_RASTER` |
| `logY` meaning | VIC sprite Y = raster of the sprite's **top** row | motion.asm / builder |
| sprite extent | `logY .. logY+20` (21 rows), 24 px wide | `SPRITE_HEIGHT` = 21 |
| admission | `MIN_SPRITE_Y`=55 .. `MAX_SPRITE_Y`=226, **Y only**, reject not clamp | renderer.asm:115-116, 590-596 |
| HUD | `HUD_Y` = **16** on **HW2–HW7**, i.e. rasters 16–36 | hud.asm:79,87 |
| sprite priority | `$d01b` = **sprites in front** of the playfield | main.asm:341 |

### Exact Y ranges

```
logY <=  34     sprite entirely above the playfield        (hidden today)
logY  35..54    STRADDLES raster 55  — partial at top      (REJECTED → pop)
logY  55..227   entirely inside 55..247                    (admitted, 55..226)
logY 228..247   STRADDLES raster 247 — partial at bottom   (REJECTED → pop)
logY >= 248     entirely below the playfield
```

The renderer admits only whole-sprite-inside, so both straddle bands are
refused outright and counted in `statRejRange`. That single rule is the whole
cause of both pops.

## Why the pops happen — and why relaxing the bound does not fix them

`renderer.asm:92-104` states it directly: *"The vertical border is held open so
a HUD can eventually live in it, and an open border clips NOTHING: the blank
charset clips characters, and there is no equivalent for sprites."*

Rasters 0–47 are VIC **idle** lines and 48–54 are matrix lines through the
**blank** charset; both render as bit pair 00 = `$d021`, which the splits paint
black outside the aperture. Nothing above 55 or below 247 covers a sprite.

**The HUD is the proof, and it costs nothing to verify.** HUD sprites sit at
Y=16 — 39 rasters above the playfield — and are plainly visible in the open top
border every frame. That is the same mechanism a "partially visible" enemy
would use. So admitting `logY` = 45 does not clip the enemy: it draws the enemy
in the black band above the terrain, across the HUD's territory. Same at the
bottom.

**The asymmetry with the sides is now explained:** only the *vertical* border
is opened. The main (horizontal) border flip-flop still runs — `exBottom`'s own
comment notes it "uncovers [the first visible pixel] in cycle 17" — so left and
right edges clip in hardware. That is exactly the behaviour the user likes, and
it is unavailable vertically by construction.

## The bottom edge is additionally cycle-constrained

`exBottom` (renderer.asm:1541-1547) must land `$d018` before line 248's first
g-access **in cycle 15**. Line 248 can never be a badline, so the only cycle
thief is sprite DMA for HW3–HW7, which owns cycles 0–9 of its own line. Present
margin: detection lands in cycles 0–6, `$d018` writes in 6–12, `$d021` in
10–16. There is no room for a 10-cycle DMA steal.

A sprite at `logY` DMAs across lines `logY .. logY+20` (plus residual accesses
on `logY+21` before DMA is switched off in cycle 16). So:

> **Every position in the bottom straddle band 228..247 puts sprite DMA on or
> immediately around line 248** — precisely the cycles the split needs.

This is structural, not a tuning accident: the playfield's last line (247) is
one line before the split (248), and the sprite is 21 rows tall, so a sprite
straddling the visible bottom necessarily DMAs across the split. The engine's
comment says the hazard starts at Y ≥ 228; by the residual-access rule it may
start at 227. The difference is one raster and visually worthless, so I did not
chase it — either way `MAX_SPRITE_Y` = 226 is correct and conservative.

## VIC-II sprite DMA semantics — the decisive facts

From Christian Bauer's *The MOS 6567/6569 video controller (VIC-II)*, §3.8.1:

1. **DMA switches ON** in cycles 55/56 only if the `MxE` bit is set **and** the
   sprite's Y matches the low byte of RASTER, and DMA is currently off.
2. **DMA switches OFF** in cycle 16 when MCBASE reaches 63 — i.e. after all 21
   rows.
3. Display is turned on at cycle 58 when DMA is on and Y matches; it turns off
   when DMA turns off. **Clearing `MxE` mid-frame does not stop a sprite that
   is already displaying** — it runs out its 21 rows.

These two rules jointly kill the most promising idea:

- **Top:** a sprite disabled while raster == its Y never starts DMA at all, so
  enabling gameplay slots at raster 55 yields *total absence*, not a partial
  entry. You cannot start a sprite late and have it resume mid-body.
- **Bottom:** clearing `$d015` at line 247 neither blanks the remaining rows
  nor stops the DMA, so the split is starved anyway.

`$d015` can only gate a whole sprite. It cannot clip rows at either edge.

## Solution classes

| # | approach | top | bottom | complexity | raster cost | mux risk | visual | arch change |
|---|---|---|---|---|---|---|---|---|
| A | relax admission | **fails** – enemy drawn over HUD band | **fails** – breaks split | LOW | — | HIGH | BAD | no |
| B | `$d015` gating at splits | **impossible** (DMA can't start late) | **impossible** (DMA can't stop early) | — | — | HIGH | — | no |
| C | raster-time Y rewrite | no – can't retroactively clip rows | no | MED | MED | HIGH | — | no |
| D | mask / overlay | no – `$d01b` = in front, and idle lines have no foreground | no | MED | LOW | LOW | — | yes |
| E | extended band + mask elsewhere | inherits D's failure | inherits bottom timing | HIGH | MED | MED | — | yes |
| F | content-side authoring | n/a | n/a | LOW | none | none | GOOD | no |
| **G** | **close the vertical border** | **perfect** | **perfect** | MED-HIGH | **none** | LOW | BEST | **yes – HUD must move** |
| **H** | **pre-shifted sprite artwork** | good | good | MED | none | none | GOOD | no (needs VIC RAM) |

**D is dead twice over:** `$d01b` puts gameplay sprites *in front*, so a
foreground strip cannot cover them, and above line 48 the VIC emits idle lines
(bit pair 00) where no foreground exists to draw with. Flipping priority
globally would let the terrain occlude enemies — wrong for a shooter.

**G — close the vertical border.** The flip-flop is set by the RSEL compare at
line 247 (RSEL=0) and cleared at 55, so a closed border clips sprites to
**exactly 55..247 — the aperture, to the raster**. Free, hardware, both edges,
zero cycles, no mux involvement; it would also make the `$d018`/`$d021` split
pair largely redundant. The price is the whole open-border HUD design (`exHud`,
`HUD_ENABLE`, the HW2–HW7 ownership handoff at raster 40): a HUD at Y=16 would
be behind the border and invisible. This is how most C64 vertical shooters
behaved — sprites clipped at the display window, status panel *inside* it.

**H — pre-shifted artwork.** Keep `logY` legal and swap in bitmaps with the
enemy shifted up/down and the off-playfield rows blanked, so it appears to
slide through the edge. No raster, DMA, split or mux implication whatsoever.
Cost: smooth clipping needs ~41 variants × 64 B ≈ **2.6 KB inside VIC bank 0**,
and bank 0 has no such contiguous space left (largest free gaps are ≈364 B at
`$3094-$31ff` and 256 B at `$3700-$37ff`). A coarse 4-row-granularity version
(~10 variants, 640 B) would fit but steps rather than glides.

## Ranked recommendation

1. **Do nothing to the renderer now.** Classes A, B, C, D, E are individually
   unsafe or physically impossible on this hardware, and the bottom edge in
   particular cannot be made partial while the split lives at 248.
2. **Content-side (F) is the correct immediate answer.** Side ingress/egress is
   already the visual standard the user approves of; author top entries to
   begin close above raster 55 so the pop is small and edge-adjacent (already
   true after the ingress slice), and prefer side exits over bottom exits where
   a pattern allows it.
3. **If the vertical pop later becomes unacceptable, the honest fix is G**, and
   it is a *HUD relocation task*, not a clipping task: move the HUD inside the
   display window, close the vertical border, delete the masking half of both
   splits, and let the VIC clip. That buys perfect clipping at both edges for
   zero raster cost — but it must be scoped and qualified on its own.
4. **H is the fallback** if the HUD must stay in the border. It needs a VIC
   bank 0 memory plan first.

One micro-fact for completeness: `MAX_SPRITE_Y` could arguably move 226 → 227
(geometrically the last fully-inside position). It gains a single raster, sits
on the exact off-by-one the DMA residual-access rule makes ambiguous, and is
not worth the risk to the split.

## Proof performed

None beyond reading. A pixel-level VICE experiment was considered and judged
unnecessary: the engine's **own HUD**, six sprites displayed 39 rasters above
the playfield every frame, already demonstrates conclusively that sprites are
visible outside the aperture, which is the single assumption the whole
"relax admission" family rests on. The `$d015` question was resolved against
the authoritative VIC-II reference rather than guessed at. No VICE process was
launched, so there is nothing to reap and no settings were touched.

## Hygiene

```text
$ du -sh build/        88K     build/
$ du -sh .             4.4M    .

$ git status --short
 M Makefile
 M src/enemy.asm
 M src/movement.asm
 M src/waves.asm
 M tests/test_encounter_director.py
?? reports/encounter-director-v1.1-flight-paths.md
?? reports/enemy-ingress-egress-spacing.md
?? tests/test_flight_paths.py
?? tests/test_ingress_egress.py

$ git diff --stat
 Makefile                         |  23 +-
 src/enemy.asm                    | 133 ++++++++-
 src/movement.asm                 | 399 +++++++++++++++++--------
 src/waves.asm                    | 617 +++++++++++++++++++++++++++++++--------
 tests/test_encounter_director.py |  76 ++++-
 5 files changed, 982 insertions(+), 266 deletions(-)
```

Everything listed is the **previous** slices' uncommitted work. This
investigation added only this report. No commit, no push.

## Source

- Christian Bauer, *The MOS 6567/6569 video controller (VIC-II) and its
  application in the Commodore 64*, §3.8.1 — sprite DMA on/off and display
  rules: <https://www.cebix.net/VIC-Article.txt>

---

**RECOMMEND CONTENT-SIDE WORKAROUND** for now, with **closing the vertical
border (class G) as a separately scoped HUD-relocation task** if smooth
vertical clipping is later judged worth the HUD's current home. Do **not**
relax the vertical admission bounds: at the top it draws enemies over the HUD
band, and at the bottom it starves the raster split.
