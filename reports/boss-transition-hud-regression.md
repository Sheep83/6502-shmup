# The boss transition HUD regression: bank 2's mirror was a photograph

**Date:** 2026-09-17
**HEAD:** `7730b6b` — *Boss VIC bank switching, infinite lives toggle added*
**Working tree at start:** the completed P-token HUD / economy / attract-colour
iteration (`reports/p-token-hud-economy-title-colours.md`), uncommitted.
**Nothing committed. Nothing pushed.**

**Result:** root cause found and proven; two defects fixed; a new 38-check
regression proof passes in full; **no suite in the repository gained a single
failure** — every failing check outside the new file fails identically on a
baseline tree built from this same working tree with only my three files
reverted.

---

## 1. Summary

**Neither defect was introduced by the P-token iteration.** `src/vicbank.asm`
and `src/boss.asm` were untouched by it — `git diff` against HEAD showed both
files clean before I started. The regression is old; what the P-token work did
was add a HUD element whose failure mode was *legible* (a digit that vanishes)
where the existing ones were not (a frozen bar looks like a bar).

| | |
|---|---|
| **Defect 1** | the bank-2 HUD mirror stopped at the instant the bank changed |
| **Defect 2** | the mirror's slice offset was computed as `n * 2` where `n * 128` was meant, so it only ever copied 506 of 896 bytes |

---

## 2. Root cause

### 2.1 The HUD lives in bank 0; the boss arena runs in bank 2

The HUD's bitmaps are at `$3200-$357f` — VIC **bank 0**. The boss arena switches
the VIC to **bank 2**, where the same (bank-relative) sprite pointers resolve to
`$b200-$b57f`. `src/vicbank.asm` keeps a **mirror** there, walked across a slice
a frame, and that mirror is the only thing the VIC can see once the bank changes.

`src/hud.asm` never stopped working. It kept formatting the score, filling the
heat bar and stamping the P digit into `$3200` for the whole boss fight,
perfectly correctly, into bytes nothing was reading.

### 2.2 Defect 1 — the feed stopped

`vicMirrorTick` was called from **`bossClearTick` and nowhere else**, i.e. only
during `LP_CLEARING` — the phase *before* the switch. The moment `bossSpawn`
selected bank 2, the mirror froze. Everything the HUD drew from then on went
nowhere.

`src/vicbank.asm`'s own header claimed the opposite, and the claim is what hid
the bug:

> the screen matrix crosses once during the clearing phase and **the HUD keeps
> crossing for as long as bank 2 is up**

It did not. Nothing called it.

### 2.3 Defect 2 — the slice offset was arithmetic for a different number

A slice's byte offset into the block is `n * 128`, sixteen bits. The code read:

```asm
    lda vicMirrorAt
    asl                 // slice -> 128-byte offset, 16 bits
    tax                 // low byte of the offset      <-- this is n * 2
    lda vicMirrorAt
    lsr                 // ...and its high byte        <-- this one is right
    tay
```

`n * 128` is `n` shifted left seven, which is a shift **right** by one with the
bytes swapped: high byte `n >> 1`, low byte the bit that fell out (`$00` or
`$80`). The high byte was computed that way; the low byte was `asl`, which is
`n * 2` and correct only for `n = 0`.

So the seven slices read from `$3200`, `$3202`, `$3304`, `$3306`, `$3408`,
`$340a`, `$350c` instead of `$3200`, `$3280`, `$3300`, … Each one started two
bytes late and stopped 126 bytes short of the next, leaving **three 130-byte
holes that no cursor ever revisited**.

Slice 6 also ran to `$358b` — twelve bytes past the block it owns, into the
`boss cells` mirror at `$3580`. Harmless in effect (that art is static and
already identical in both banks) but out of bounds.

---

## 3. Why the three symptoms differed

This is the part the observation report got exactly right, and the asymmetry is
what made the diagnosis quick.

| what you saw | why |
|---|---|
| **heat gauge freezes** | the *fill* is bitmap data, so it stopped crossing with everything else (defect 1) |
| **…but its overheat flash still works, and stops correctly when cool** | **colour is a VIC register, not bank data.** `weaponHudFeed` → `hudSetHeatColour` → `hudCol` → `exHud` → `$d02a`/`$d02b`. That path never touches a bank, so it was never affected. `weaponHudFeed` also runs every frame in `gameFrame` regardless of phase — which is why cooling still released the lockout |
| **score becomes 0, rather than freezing** | defect **2**. The score sprites are `$3280-$32ff`, which sat squarely inside the first hole — **score-right crossed 0 bytes of 64, score-left 2 of 64**. The bank-2 score was therefore *never once written after boot*, and `vicMirrorStatic` runs at cold start immediately after `hudInit`, which draws `000000`. The player was looking at the boot image |
| **P pips visible but the number disappears** | the pips are in the four precomputed charge blocks, which `vicMirrorStatic` copied at boot and which never change — so the boxes are always right in bank 2 whatever the mirror does. The **digit** is stamped at run time into whichever block the pointer selects, and P blocks 0 and 1 sat inside the third hole (**block 1: 0 bytes of 64**). At boot only block 0 carries a digit, so a charge of 1 selects a block that has never held one: **blank** |

So "the HUD update loop stopped" was indeed the wrong model, and the three
components disagreed because they fail through three different mechanisms: one
register path (unaffected), one static-art path (unaffected), and one dynamic
bitmap path that was broken twice over.

---

## 4. Evidence

Two probes, each one VICE launch, PID-owned and reaped.

### 4.1 The mirror's coverage, measured directly

Fill `$3200-$357f` with a pattern, zero the bank-2 copy, drive one full cursor
cycle by hand, and count what crossed:

```
BEFORE THE FIX                      AFTER
bytes copied : 506 / 896            bytes copied : 896 / 896
missed ranges:                      missed ranges: (none)
  $3282-$3303  (130)  score L, score R
  $3386-$3407  (130)  lives
  $348a-$350b  (130)  P blocks 0,1,2

per component:                      per component:
  heat L        64/ 64                heat L        64/ 64
  heat R        64/ 64                heat R        64/ 64
  score L        2/ 64                score L       64/ 64
  score R        0/ 64  <-- NEVER      score R       64/ 64
  lives 0-5    250/384                lives 0-5    384/384
  P block 0     10/ 64                P block 0     64/ 64
  P block 1      0/ 64  <-- NEVER      P block 1     64/ 64
  P block 2     52/ 64                P block 2     64/ 64
  P block 3     64/ 64                P block 3     64/ 64
```

### 4.2 The boss transition, before the fix

Score poked to a distinctive value, then the level run out:

```
BEFORE (bank 0)   b0_scoreL  30 78 78 70 cc cc 30 0c cc 30 38 7c   <- "123"
                  b2_scoreL  7c 7c 7c c6 c6 c6 ce ce ce d6 d6 d6   <- "000"

AT BOSS ENTRY     b0_scoreL  30 78 30 70 cc 70 30 0c 30 30 38 30
                  b2_scoreL  7c 7c 7c c6 c6 c6 ce ce ce d6 d6 d6   <- STILL "000"

+ SEVERAL SECONDS b0_scoreL  30 78 1c 70 cc 3c 30 0c 6c 30 38 cc
                  b2_scoreL  7c 7c 7c c6 c6 c6 ce ce ce d6 d6 d6   <- STILL "000"
```

`7c c6 ce d6 e6 c6 7c 00` is `digitGlyph`'s zero. Bank 0 changes every sample;
bank 2 never changes at all, and holds the boot image rather than a frozen real
value — the signature of defect 2 on top of defect 1.

`vicMirrorAt` reads **4** at boss entry and **4** for ever after: the cursor
stopped moving the moment the bank changed.

### 4.3 The same probe, after the fix

Every bank-2 block tracks bank 0 exactly, across entry and throughout the fight:

```
AT BOSS ENTRY     b0_scoreL == b2_scoreL     b0_scoreR == b2_scoreR
+ SEVERAL SECONDS b0_scoreL == b2_scoreL     b0_scoreR == b2_scoreR
                  b0_Pdig0..3 == b2_Pdig0..3
```

---

## 5. The fix

Three files, and the shape of it is ownership: **the mirror is a feed, not a
photograph, and the bank may not be selected over half a picture.**

### 5.1 `src/vicbank.asm` — the arithmetic

```asm
    lda vicMirrorAt
    lsr                 // n >> 1 IS the high byte...
    tay
    lda #0
    ror                 // ...and carry -> bit 7 is the low one
    tax
```

Slice 6 now reads `$3500-$357f`, ending exactly on the block boundary.

### 5.2 `src/vicbank.asm` — `vicMirrorLive`, the feed

New routine, called from the main loop's **idle spin** beside `hudUpdate`. Two
gates, both load-bearing:

- **the bank gate** — `lda vicBank2 / beq` : five cycles and an `rts` in bank 0,
  which is all of ordinary play;
- **the frame gate** — the spin runs thousands of times a frame and the mirror
  must run once, so the displayed-frame number is the gate. One slice per frame,
  the whole block current again within seven frames (140 ms). That is the
  cadence `src/vicbank.asm`'s existing reasoning already chose and justified;
- **the raster gate** — `HUD_SAFE_LO..HUD_SAFE_HI`. **These are the bytes the
  VIC fetches on rasters 16..37.** `src/hud.asm` refuses to write the bank 0
  originals outside 56..200 for exactly that reason, and the bank 2 copies are
  the same bytes seen through a different bank; copying them across the fetch
  would tear a digit. A refusal costs microseconds because the spin comes back
  round immediately.

It lives in the spin rather than in `gameFrame` for the reason `gamePlayLoop`
already documents for `hudUpdate`: the per-frame block reaches that point at
around raster 10, *inside* the fetch window.

### 5.3 `src/vicbank.asm` + `src/boss.asm` — the gate

`vicMirrorDone` is armed low by `vicMirrorScreen` (which now resets the HUD
cursor too, since it free-runs) and raised by the wrap at the end of a complete
HUD pass. `bossClearTick` holds the spawn until it is set:

```asm
!clean:
    lda vicMirrorDone
    bne !ready+
    rts
!ready:
    jmp bossSpawn
```

**Bounded and short:** fifteen frames from the arm in the worst case, so an
arena that was already empty when the stage ran out waits three tenths of a
second nobody can see. Without it, a short clearing phase would start the boss
fight showing the boot HUD and then snap — the flicker this lifecycle was
rebuilt to remove. The deadline path falls into the same gate and needs no wait
of its own: `ARENA_CLEAR_DEADLINE` is 200 frames and the mirror needs 15.

`vicMirrorFinish` now waits on `vicMirrorDone` rather than on the screen cursor
alone, so it covers both halves of the picture. It is a safety net that should
never do anything, and it is still bounded by construction.

### 5.4 What did **not** change

No renderer, multiplexer, raster-executor, schedule, `$d018`, pointer-table or
bank-selection behaviour. No change to `src/hud.asm`, the P economy, the
celebration or the jingle. `vicSelectBank2` still does not write `$dd00`; the
frame IRQ still commits it.

---

## 6. Memory and VIC-bank implications

None beyond one byte of state and a few bytes of code.

```
  $1400-$17e5 hud code          $3200-$357f hud bitmaps   (14 blocks, 896 bytes)
  $1840-$1b5f sfx               $3580-$367f boss cells
  $6980-$6aed vic bank          (ceiling $6c00)
  $c60a-$c614 vic bank state    (ceiling $c620)
```

Three bytes added to the vic-bank state block (`vicMirrorDone`,
`vicMirrorFrame`, `vicMirrorRuns`), which had room. The code block grew to
`$6aed` against a `$6c00` ceiling. **No segment moved, no sprite pointer
changed, and the bank-2 layout is untouched** — this was never a layout problem.
The HUD mirror keeps its bank-0 offset exactly as `vicbank.asm` requires.

**Cost:** five cycles and an `rts` per spin pass in bank 0. In bank 2, one
128-byte copy per displayed frame (~1,800 cycles) — measured `gameOverrun = 0`
across the whole transition.

---

## 7. Tests and results

| suite | result | attribution |
|---|---|---|
| build | **clean** | |
| **`tests/test_boss_hud_transition.py`** (new, 38 checks) | **ALL PASS** | |
| `tests/test_p_economy_colours.py` | **ALL PASS** | |
| `tests/test_bank2_arena.py` | **ALL PASS** | |
| `tests/test_boss.py` | **ALL PASS** | |
| `tests/test_lifecycle.py` | **ALL PASS** | |
| `tests/test_player_death.py` | **ALL PASS** | |
| `tests/test_attrition_inflives.py` | **ALL PASS** | |
| `tests/test_boot.py` | **ALL PASS** | |
| `tests/test_turret_regression.py` | **ALL PASS** | |
| `make test` | 1 failure: `publishSkip` | pre-existing |
| `tests/test_encounter_director.py` | 2 failures | **identical on baseline** |
| `tests/test_ingress_egress.py` | 3 failures | **identical on baseline** |
| `tests/test_clip_scratch.py` | 2 failures | **identical on baseline** |
| `tests/test_token_encounter.py` | 7 failures | **identical on baseline** |
| `tests/test_flight_paths.py` | 2 failures | **identical on baseline** |
| `tests/test_sfx.py` | 10 failures | **10 on baseline, 9 names shared** |
| `tests/test_pickup.py` | `KeyError: waveTrigTokenLo` | stale since `d5566b0` |

### How attribution was established

A **pre-task baseline tree** was built in `/tmp`: a copy of this exact working
tree with only `src/vicbank.asm` and `src/boss.asm` reverted to HEAD and the
`jsr vicMirrorLive` block removed from `src/main.asm`. That isolates this task's
changes from the P-token iteration, which is also uncommitted and would otherwise
be conflated with them. Every failing suite above was then run on both trees.

The failure *names* match one for one on every suite. `test_sfx.py` produces ten
failures on both trees with nine names shared; the one that differs
(`the machine really ran during the silent-traffic window` here versus
`requests == volleys + ... exactly` there) is run-to-run variance inside the
idle/quiet family already documented as flaky in the previous report — and both
trees carry a byte-identical `src/sfx.asm`, so it cannot be attributable either
way.

`test_pickup.py` fails at import of a symbol, not on an assertion:
`waveTrigTokenLo` was removed from `src/` at commit `d5566b0`
("Powerup Token mechanic added"), two commits before HEAD, and the test was
never updated. Stale, unrelated, **not touched** — per the standing rule, an
unrelated failure is not permission to start test archaeology.

### The new regression proof

`tests/test_boss_hud_transition.py`, one VICE launch, PID-owned, reaped on every
path. Selected results:

```
ok  the live mirror does nothing at all in bank 0
ok  THE WHOLE PICTURE HAD CROSSED before the bank switch -- vicMirrorDone = 1
                                                            at bossSpawn
ok  the boss phase began, in VIC bank 2, at full health (50)
ok  the authoritative score is preserved across boss entry
ok  lives were carried into the arena, not reset      -- 243 -> 242
ok  the spendable P count and its partial charge      -- P 7->7, charge 2->2
ok  the bank 2 score-left / score-right sprites match bank 0    (0 / 4 frames)
ok  the bank 2 heat-left / heat-right sprites match bank 0      (0 / 0 frames)
ok  the bank 2 P charge block on the pointer matches bank 0     (0 frames)
ok  ...and that digit is actually drawn, not blank
ok  a score change DURING the fight reaches bank 2              (5 frames)
ok  heat fed during the fight moves the fill  -- 0 -> 47 of 48 pixels
ok  ...and the filled bar reached bank 2
ok  the overheat alarm still flashes          -- colours seen: $00, $02
ok  the boss health bar still tracks its HP, in colour RAM
ok  the boss still takes damage in bank 2
ok  gameOverrun / scrollLate / statPageMismatch / statPtrMismatch
    / objDoubleFree / objAllocFail are zero across the transition
ok  hudUpdWrapped is zero -- the HUD write window was never violated
ok  lives did not move during the boss fight itself
ok  the live mirror ran throughout      -- vicMirrorRuns = 76
ok  one cursor cycle crosses the WHOLE HUD block: 896 of 896 bytes
```

The last check is the guard against defect 2 returning: it reads 506 of 896 if
the `n * 128` offset is ever written as `n * 2` again.

No existing assertion was weakened, and no test outside the new file was
modified.

### Three test-side mistakes I made and fixed in my own file

1. **`mon.cmd("x")` returning is not "the breakpoint fired."** It returns on an
   idle socket too — the trap `harness.py` documents — so my first gate check
   read `vicMirrorDone` at an arbitrary halt in the middle of `LP_CLEARING` and
   reported a correct gate as broken. It now parses the monitor's own
   `(C:$xxxx)` prompt and confirms the PC really is `bossSpawn`.
2. **`hudDemoTick` still bumps the score every eight frames**, so asserting the
   poked digits came back was asserting against the game working.
3. **Lives legitimately fall during `LP_LEVEL`** — the harness parks the ship
   with no input and it gets shot — so a baseline captured before the level ran
   out was the wrong one. Captured at boss entry now, exactly as
   `test_bank2_arena.py` already does and says why.

I also corrected one *assertion* that tested the wrong mechanism: `bossDrawBar`
is called from the damage path, not from `bossFightTick`, so poking `bossHP` and
waiting proves nothing. It is now driven directly and the colour RAM row checked
cell by cell.

---

## 8. Observation recorded, not acted on — end-of-stage enemies

Confirmed while tracing, and **deliberately left alone** per the scope exclusion.

`bossClearTick` gives whatever is in flight `ARENA_CLEAR_DEADLINE` = 200 frames
(four seconds) to leave under its own rules before `bossPurgeArena` removes it.
Enemies still on screen therefore *can* postpone the boss by up to four seconds,
and `lvlForced` records when the deadline was hit rather than the arena having
genuinely emptied.

Two notes for whoever takes the wave-generation decision:

- the deadline is already a hard bound, so the boss cannot be postponed
  *indefinitely* today — the worst case is four seconds;
- my gate adds at most fifteen further frames, and **only when the arena cleared
  faster than the mirror**, so it cannot interact with this at all: if enemies
  are delaying the clear, the mirror finished long before.

No behavioural change was made here.

---

## 9. Manual VICE checks still required

Manual visible output is authoritative (AGENTS.md rule 2). Automated counters
say the right bytes are in the right place; they cannot say it looks right.

**The regression itself:**

1. **Score** — reads its real value the instant the boss appears, not `000000`.
2. **Score during the fight** — shoot the boss and watch it climb normally.
3. **Heat gauge** — the fill follows the weapon throughout the boss fight, and
   in particular **keeps moving while you fire**, rather than freezing.
4. **Heat gauge, closely** — watch the joint at the middle of the 48-pixel bar
   as the fill crosses it. The two halves are mirrored on adjacent frames, so a
   one-frame disagreement at the seam is the thing to look for; I do not expect
   it to be visible but it is the honest worst case of a one-slice-per-frame
   feed.
5. **Overheat flash** — still alternates during the boss fight, and still stops
   correctly when the weapon cools.
6. **P charge pips** — correct for your actual charge as the boss arrives.
7. **P count** — **the number is present and correct**, including when your
   charge is 1 or 2 (that is the case that showed nothing before).
8. **Collect a P during the boss fight if you can** — the celebration, the
   flash and the jingle should behave exactly as they do in normal play, and the
   number should step up afterwards.
9. **Lives** — unchanged across the transition.
10. **Boss health bar** — draws and drains normally.

**The transition, and what my gate could have disturbed:**

11. **No flicker or snap at boss entry** — the HUD should be correct on the
    first boss frame, not correct-after-a-moment.
12. **The boss still arrives promptly** when the arena empties early. The gate
    can add up to 0.3 s; it should not read as a hesitation.
13. **Level complete and restart** still behave — the return to bank 0, the
    LEVEL COMPLETE page, and ordinary gameplay afterwards.
14. **Ordinary pre-boss gameplay is unchanged** — this is the case the fix must
    cost nothing in.

---

## 10. Repository state

**Final git status**

```
 M src/boss.asm          <- this task
 M src/main.asm          <- this task (one jsr in the idle spin)
 M src/vicbank.asm       <- this task
 M src/gamestate.asm     }
 M src/hud.asm           }  the P-token iteration, unchanged by this task
 M src/pickup.asm        }
 M src/sfx.asm           }
?? reports/boss-transition-hud-regression.md    <- this report
?? tests/test_boss_hud_transition.py            <- this task
?? reports/p-token-hud-economy-title-colours.md }  the previous iteration
?? reports/p-token-hud/                         }
?? tests/test_p_economy_colours.py              }
```

**Disk**

```
du -sh build/   96K
du -sh .        7.3M
```

`build/` holds only the current binary and symbols — no per-run directories. The
baseline tree and both probes were built in disposable scratch locations and
have been deleted; `/tmp` carries no residue. `pgrep -fl x64sc` reports nothing
running: every VICE this session launched was owned by PID and reaped, and no
manual session was touched.

**Nothing committed. Nothing pushed.**
