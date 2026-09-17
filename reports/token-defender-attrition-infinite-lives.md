# Token defender attrition + Infinite Lives testing toggle

**Date:** 2026-09-17
**Starting HEAD:** `0f7d84f` — *Boss placeholder added*, unchanged.
**Starting git status:** the uncommitted Bank 2 boss work — `src/boss.asm`, `src/gamestate.asm`, `src/main.asm`, `src/renderer.asm`, `src/scroll.asm` modified; `src/vicbank.asm`, `tests/test_bank2_arena.py` and the two bank-2 reports untracked. All of it preserved.
**Final git status:** the same, plus `src/player.asm` and `src/token.asm` modified and `tests/test_attrition_inflives.py` new. **Nothing committed or pushed.**

**Result:** clean build; `tests/test_attrition_inflives.py` **ALL PASS** (34 checks); `make test` passes everything except the pre-existing `publishSkip` failure. `tests/test_token_encounter.py` fails six checks, every one of them the *intended* behaviour change or an artefact of how that test measures — §8. It was **not modified**.

---

## 1. Files changed

| file | why |
|---|---|
| `src/token.asm` | `tkEnlisted`, and the three-instruction gate that closes the complement |
| `src/player.asm` | `readKeyI`; the life-consumption and terminal-death conditionals |
| `src/gamestate.asm` | `gsInfLives`, `gsKeyIDown`, `gsInfToggle`, the title indicator |
| `src/scroll.asm` | segment moved `$4300` → `$4340` (§6) |
| `tests/test_attrition_inflives.py` *(new)* | the focused proof |

---

# Part A — defender attrition

## 2. Where replacement previously happened

`tokenTick`, in the block that used to be headed *"keep three posts filled"*:

```asm
    dec tkReinforce
    bne !noReinforce+
    lda #TK_REINFORCE_FRAMES
    sta tkReinforce
    jsr tokenFreePost          ← "is any post empty RIGHT NOW?"
    bcs !noReinforce+
    jsr tokenReinforce         ← spawn a Ring into it
```

`tokenFreePost` scans the live pool and reports the lowest post with no guard
standing on it. **It answers a question about occupancy, and occupancy cannot
tell the difference between a post never filled and a post whose guard has just
been shot.** So a kill emptied a post, and the next expiry filled it again.

## 3. Why it looked intermittent

Nothing to do with screen position directly, though the last item is close to
that intuition. Four gates sat between a kill and a visible replacement:

1. **The 24-frame timer.** Replacement is attempted only on a
   `TK_REINFORCE_FRAMES` expiry, so a kill could wait up to half a second before
   anything was even attempted.
2. **The pool.** `tokenReinforce` calls `objectAlloc` and abandons the attempt if
   the pool is full, counting `tkDenied` and waiting a further 24 frames.
3. **The encounter ending first.** If the token was collected or fell off the
   bottom in the meantime, no replacement ever appeared.
4. **The walk.** A replacement enters at `TK_SPAWN_Y = 30` in the token's own
   column and then walks down to its post. With the token low on the screen that
   is a long journey, so a replacement could be created and still not have
   *arrived* before the encounter ended. That is the bit that reads as "it
   depends where it is on screen" — the spawn is not gated by position, but the
   visible arrival is.

## 4. The change

One byte and one gate.

```asm
tkEnlisted:   .byte 0     // defenders this encounter has ever CREATED
```

```asm
    lda tkEnlisted
    cmp #TK_GUARDS
    bcs !noReinforce+      ← the complement is closed, for good
    dec tkReinforce
    ... unchanged ...
```

`tkEnlisted` is incremented in exactly two places: `tokenAssignRoles` when a live
enemy is promoted, and `tokenReinforce` when a Ring is successfully created. It
is zeroed by `tokenInit` and again by `tokenDropperDied`, so each encounter
enlists its own group.

**It counts creations, not occupancy, and that is the whole distinction.** A
count can only go up, so:

- the initial fill may still run asynchronously across frames;
- it can never reopen — not even if the player kills a defender *while the group
  is still being assembled*, which is the "reopen indefinitely" hazard;
- `tokenFreePost` still chooses *which* post an initial defender fills, so
  assembly is exactly as deterministic as before.

```
3 defenders → kill → 2 → kill → 1 → kill → 0        and it stays 0
```

**The state byte moved down one address, not up.** The dropper flight state
begins at `$c462`, immediately after the token block, but there are 62 free bytes
below it — so the segment now starts at `$c43f` and every *existing* field keeps
the exact offset from `tkActive` that the focused proofs read the block by.

## 5. Initial assembly still works

Measured: the complement still reaches three defenders and `tkEnlisted` reads 3.
In the proof's run all three came from reinforcement (`tkReinforced 3`), so the
top-up path is exercised, not just promotion.

**Nothing else in `token.asm` changed.** The complete functional diff is the
segment start, the counter, its resets/increments, and the three-instruction
gate — no orbit constant, no `tokenGuardMove` instruction, no geometry, no
timing. Orbit radius, stagger, speed, selection, egress, suppression and resume
are untouched.

---

# Part B — Infinite Lives

## 6. The flag

`gsInfLives` in `src/gamestate.asm`'s state block, **default 0 (OFF)** at a cold
boot.

It is a **separate explicit byte, not a fake lives count.** Stuffing `$ff` into
`hudLives` would draw a stock nobody has, would still decrement on every death
and would still reach zero — a long game, not an infinite one.

**Boot-scoped on purpose.** `gsResetRun` deliberately does *not* clear it: a game
started from the attract screen keeps whatever the tester set, which is the
entire point of being able to set it there. Nothing resets it but a cold start.

## 7. The `I` key and its debounce

There was **no keyboard reading anywhere in this game** — `readInput` samples
only the joystick. So `readKeyI` is new, and it lives in `src/player.asm` beside
`readInput` because that file already owns CIA 1.

```asm
.const KEY_I_COL = %11101111        // drive PA4 low: the column holding I
.const KEY_I_ROW = %00000010        // ...and read PB1, which is the I key

readKeyI:
    lda #KEY_I_COL
    sta $dc00
    lda $dc01                       // the row bits, active LOW
    ldx #$ff
    stx $dc00                       // every column off again, at once
    and #KEY_I_ROW
    beq !down+
    lda #0
    rts
!down:
    lda #1
    rts
```

**The hazard is real and is why the restore is where it is.** Port A is the
keyboard column drive *and* joystick 2. `KEY_I_COL` has bit 4 clear, so a column
left driven would read back through `readInput` as **FIRE being pulled**. `$dc00`
is restored in the instruction after the row read and before anything branches —
there is no path out that leaves it driven. Port B is never written and neither
data-direction register is touched, so `readInput`'s own guarantee still holds.
`readInput`'s comment, which claimed to be the only `$dc00` access, was corrected
rather than left to become false.

**The debounce** is a press-edge latch in `gsInfToggle`, called from
`gsAttractLoop` and nowhere else:

```asm
gsInfToggle:
    jsr readKeyI            // A = 1 while held
    cmp gsKeyIDown
    beq !steady+            // no edge: held, or still up
    sta gsKeyIDown
    cmp #1
    bne !steady+            // the RELEASE edge: nothing to do
    lda gsInfLives
    eor #1
    sta gsInfLives
!steady:
    rts
```

Being called only from the attract loop is what keeps the cheat out of gameplay:
`gameFrame` never reaches it, so the key is inert once a game has started.

## 8. The indicator

Two lines of equal length on the title page, at row 23:

```
INFINITE LIVES: OFF
INFINITE LIVES: ON
```

Same length so whichever is drawn covers the other and the page needs no clear.
Title page only; the flag lives in state, so it survives the high-score page
regardless. No title graphics, FIRE gate or attract timing was touched.

## 9. The life conditional

`playerTakeHit` in `src/player.asm`, at the single canonical point a life is
consumed. Two small conditionals, no duplicated death path:

```asm
!lives:
    lda gsInfLives
    bne !noCost+            ← skip the stock AND the terminal guard
    lda hudLives
    beq !done+
    dec hudLives
    ... HUD_DIRTY_LIVES ...
!noCost:
    ... plyDead = 1, boom frame/timer reset, muzzle out, plyVisible = 1 ...
    lda gsInfLives
    bne !done+              ← with the cheat on there is no "last one"
    lda hudLives
    bne !done+
    lda #1
    sta plyFatal
!done:
```

The terminal guard is skipped with the decrement, deliberately: a stock of zero
with the cheat on is not a terminal state, it is a number nobody is spending.

**Everything else is untouched and still real** — `plyHits` still counts, the SFX
still plays, `plyDead` is still set, the fireball still starts at frame 0,
`playerDeathTick` still runs the eight art frames, and the respawn still starts
the invulnerability blink. Damage and collision are not bypassed and there is no
second respawn implementation. Proven both ways in §10.

---

## 10. Focused tests run, and final results

`tests/test_attrition_inflives.py` — **ALL PASS, 34 checks, one VICE launch.**

```
Part A
  the initial complement still reaches three defenders   3, tkEnlisted=3
  killing a defender leaves 2, and it stays 2            tkActive=1
  killing a defender leaves 1, and it stays 1            tkActive=1
  killing a defender leaves 0, and it stays 0            tkActive=1
  no replacement defender was ever created               tkReinforced 3 -> 3
  the enlisted count never grew past the complement      3
  the encounter still ends when the token goes           tkEnded=1
  waves resumed                                          wvDropped 0

Part B
  Infinite Lives defaults OFF                            0
  pressing I turns it ON                                 1
  HOLDING it does not toggle again                       1 after 60 frames held
  releasing does not toggle                              1
  pressing again turns it OFF                            0
  survives the attract page flip                         page 0 -> 1, still 1
  scanning left no column driven                         $dc00 = $ff
  OFF: a death costs a life                              3 -> 2
  ON:  a death costs nothing                             3 -> 3
  both: the craft dies and the fireball starts at frame 0
  OFF: the last life is terminal                         plyFatal 1
  ON:  a stock of ZERO is not terminal                   plyFatal 0, still died

gameOverrun scrollLate statPageMismatch statPtrMismatch
objDoubleFree objAllocFail                               all 0
```

`make test` — all pass except `publishSkip is zero over 10s of ordinary play`,
which the bank-2 reports already verified fails identically at HEAD.

### One test-side correction I made

The first draft of Part A used `harness.free_run(..., 1)` between kills. That is
**one second of warp — thousands of frames** — so the whole encounter began,
assembled and ended inside the first call and the checks then sampled a machine
with nothing left to look at. Replaced with a frame stepper on a `gameFrame`
breakpoint. No assertion was weakened.

---

## 11. `tests/test_token_encounter.py` — six failures, untouched

This is the committed v2.1 token proof. It was **not modified**. Every failure is
explained, and none is a regression in orbit behaviour:

| failing check | why |
|---|---|
| `a killed guard was replaced` | **the intended change.** The test asserts the rule this task removes |
| `the patrol ring is as wide as the constants say` | **0 settled frames** |
| `...and never collapses onto the token` | **0 settled frames** |
| `the three guards stay spread...` | **0 settled frames** |
| `the three guards are never all stationary together` | **0 settled frames** |
| `schedBuildDefer is zero` | 1, from boot/attract — this file does not zero the counters first, unlike `tests/test_boss.py` |

The four formation checks all report **"0 settled frames"**, not a bad
measurement. The test kills a guard **on frame 1** of the encounter and then
samples its formation statistics only on frames where all three defenders are on
station — which, with attrition, never happens again. The geometry was never
measured, so it cannot have failed.

That the orbit itself is unchanged is verifiable from the diff: the complete
functional change to `token.asm` is the segment start, `tkEnlisted`, its
resets/increments and the three-instruction gate. No orbit constant or
`tokenGuardMove` instruction was touched.

**Deciding what that file should now assert is a content decision, not a
mechanical fix**, so I have left it alone for you.

---

## 12. Segment move

`src/player.asm` grew past `$4300` when it gained `readKeyI`, colliding with the
scroller. The scroller moved `$4300` → `$4340`, which had 239 bytes of slack
above it and is main-thread code reached by label.

While there, `player.asm`'s own growth guard was **tightened from `$4400` to
`$4340`** — it had been looser than the real boundary, which is why the collision
was caught by the linker rather than by the assertion that exists to catch it.

---

## 13. Manual VICE checks required

Please verify:

1. **`I` visibly toggles Infinite Lives on and off on the title**, and the
   indicator reads correctly.
2. **With it ON, deaths look and behave completely normally** — fireball,
   respawn, blink — except the life count does not decrease.
3. **Multiple deaths keep respawning** rather than reaching GAME OVER.
4. **With it OFF, ordinary finite-lives and GAME OVER behaviour is unchanged.**
5. **During a P-token defence, killing defenders permanently reduces the group**
   instead of summoning replacements.
6. **Token collection/escape and survivor egress feel unchanged.**

Also worth a glance, since the key scan shares the port: **the joystick still
behaves normally on the title screen** — no phantom FIRE.

---

## 14. Disk

```
du -sh build/   96K
du -sh .        7.0M
```

**Nothing committed. Nothing pushed.**
