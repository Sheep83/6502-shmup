# Wave Contract Stage 1: absolute 16-bit trigger rows

**Date:** 2026-09-18
**HEAD at start:** `8f79574` — *Memory reshuffle to accomodate longer levels*
**Working tree at start:** **clean** (`git status --porcelain` empty)
**Outcome:** implemented and proven. Level 1 is spatially unchanged through its
four encounters; the schedule no longer repeats.
**Nothing committed. Nothing pushed. No destructive reset.**

This is stage 1 of the roadmap in
`reports/wave-movement-architecture-and-editor-contract.md` §11. Stages 2–8 were
not begun.

---

## 1. Initial state

```
$ git log --oneline -1
8f79574 Memory reshuffle to accomodate longer levels

$ git status --porcelain      (empty)
$ git diff --stat             (empty)
```

Read in full before editing: `AGENTS.md`,
`reports/wave-movement-architecture-and-editor-contract.md`,
`reports/definitive-440-row-memory-audit.md`,
`reports/e000-level-package-and-420-row-proof.md`,
`reports/scroll-speed-1px-restoration.md` — then the implementation itself
(`src/waves.asm`, 1,415 lines), rather than relying on the reports.

---

## 2. The old delta/wrap semantics

One authored column of **deltas**, and two bytes of runtime state holding a
running sum:

```asm
.var trigDelta = List().add(48, 4, 38, 36)

waveInit:        wvNextAt = trigDelta[0]          // 48
waveAdvanceCursor:
    inc wvNextTrig
    cmp #WAVE_TRIGGERS
    bcc !armed+
    lda #0
    sta wvNextTrig                                // <-- THE WRAP
!armed:
    wvNextAt += trigDelta[wvNextTrig]             // <-- of the INCOMING cursor
```

Two details matter and neither is obvious from the comments:

- `waveInit` armed the first trigger at **`trigDelta[0]`**, not at zero;
- `waveAdvanceCursor` added the delta of the trigger it had just moved **on to**,
  not of the one it had just consumed.

So the first cycle was `48`, `48+4`, `52+38`, `90+36`. The cursor then wrapped
and the sum kept climbing, giving a period of `48+4+38+36 = 126` coarse rows for
as long as the stage scrolled — thirteen repeats over Level 1's 395 rows and
**fifty-two over the 420-row proof stage**.

That repetition was an artefact of the encoding, not a decision: nothing could
be placed at row 900 without also placing it at 774 and 1026.

---

## 3. Measured old first-cycle positions

Derived from the running machine, not from the arithmetic. A probe breakpointed
`waveStartNext` and recorded the cursor and `worldProgress` at every firing,
booting **frame-accurately** so the first cycle was actually observable:

```
# HEAD 8f79574 -- DELTA, WRAPPING
# at PLAYING: worldProgress=0  stageHold=1  lvlPhase=0
# waveTrigDelta = [48, 4, 38, 36]
# armed at start: cursor=0 target=48

  # trig    row  target  def  spc  fire  side
  0    0     48      48    0    0     5     0
  1    1     52      52    1    8     2     0
  2    2     90      90    2    0     5     0
  3    3    126     126    3    8     0     1
  4    0    174     174    0    0     5     0     <-- the wrap
  5    1    178     178    1    8     2     0
  6    2    216     216    2    0     5     0
  7    3    252     252    3    8     0     1
  8    0    300     300    0    0     5     0
  ...  through 426 in 400 rows.  wvStarted = 13
```

**A measurement trap worth recording:** the first draft of that probe used
`harness._boot_to_game`, which presses fire with **a second of warp per press**.
It returned with the world already at row 811 — six cycles in — and the first
cycle was unobservable. The capture above uses a frame-accurate boot instead.

---

## 4. The new absolute representation

Authored data, `src/waves.asm`:

```asm
.var trigRow   = List().add(48, 52, 90, 126)
```

Emitted as two parallel columns beside the four that did not change:

| column | width | note |
|---|---|---|
| `waveTrigRowLo` | 1 | **absolute** `worldProgress` |
| `waveTrigRowHi` | 1 | genuinely 16-bit |
| `waveTrigDef` | 1 | unchanged |
| `waveTrigSpecies` | 1 | unchanged |
| `waveTrigFire` | 1 | unchanged |
| `waveTrigSide` | 1 | unchanged |

**Six bytes per trigger**, up from five. Split lo/hi rather than interleaved so
the compare is two `absolute,Y` loads against the cursor the director already
holds in Y — no record stride and no multiply. Parallel columns were kept
deliberately: introducing the final generated trigger record here would mix
stage 1 with the later externalisation.

### Assembly-time validation

| check | why |
|---|---|
| all six columns are `WAVE_TRIGGERS` long | unchanged |
| **rows are non-decreasing** | **new.** A forward-only cursor can never reach a row authored behind the one in front of it, and it would be invisible in play rather than a build failure |
| rows fit 16 bits | the real limit of the representation |
| definition exists; species by **membership**; fire mask fits the member count | unchanged |
| **species alternation no longer wraps** | trigger 3 has no successor now, so comparing it against trigger 0 would assert about an adjacency that never happens |
| trigger table is **six** bytes per trigger | was five |

`.if (trigDelta.get(t) < 1)` — "a delta of zero would fire every frame for
ever" — is gone; the failure it guarded cannot exist when rows are absolute.

**Non-decreasing, not strictly ascending, is deliberate.** Two triggers sharing
a row are legal: `waveStartNext` consumes one per tick, so a co-located pair
arms on consecutive frames. That is the mixed-species / mixed-formation
mechanism §6 of the architecture report describes, and it needed **no code** —
it falls out of a forward-only cursor. Nothing was added to support it.

---

## 5. Exact due semantics

```asm
!playing:
    ldy wvNextTrig
    cpy #WAVE_TRIGGERS
    bcs !noTrigger+          // exhausted: also the bounds check on the loads
    lda worldProgressHi
    cmp waveTrigRowHi,y
    bcc !noTrigger+
    bne !due+
    lda worldProgressLo
    cmp waveTrigRowLo,y
    bcc !noTrigger+
!due:
    lda tkActive
    bne !noTrigger+
    jsr waveStartNext
!noTrigger:
```

**The test is `worldProgress >= trigRow`, sixteen bit, high byte first**, with
the low byte consulted only when the high bytes are equal. `>=` rather than `==`
is load-bearing twice over:

- a trigger held through a token encounter stays due instead of being missed by
  a row;
- a row the stage never reaches simply never fires, rather than firing late.

### The token hold is now nothing at all

The delta director had to walk its running target forward to `worldProgress` on
every held frame, because the target was runtime state that would otherwise fall
behind and lose the trigger. **An authored row cannot fall behind**: it is a
constant, `worldProgress` only increases, and the compare is `>=`. Six
instructions and a 16-bit copy were deleted and replaced by `bne`.

One trigger is consumed per tick, so an encounter long enough to outlast two
authored rows releases them on consecutive frames rather than together. That is
the existing **drop, don't queue late** policy doing its job — if the second
finds both instances busy it is dropped and counted in `wvDropped`. It cannot
compound, because the cursor only moves forward.

**Policies preserved verbatim:** drop-don't-queue on no free instance;
defer-don't-skip on a full pool; Dropper substitution; species/side/fire
latching onto the instance at arm time; `WAVE_SLOTS` unchanged at 2; the global
firing cadence untouched.

---

## 6. Exhaustion behaviour

`wvNextTrig` counts **0..WAVE_TRIGGERS inclusive**. `WAVE_TRIGGERS` — one past
the last entry — *is* the exhausted state. `cpy / bcs` is simultaneously the
bounds check on the indexed loads and the termination test, and costs three
instructions on a frame with nothing to do.

```asm
waveAdvanceCursor:
    inc wvNextTrig
    rts
```

No flag, no sentinel row, no wrap. **It cannot run away:** the only path here is
through `waveStartNext`, which the exhausted test has already refused to reach —
so the cursor stops on exactly that value and needs no clamp. A stage that runs
for thousands of rows past its last authored moment takes the exhausted branch
every frame and does nothing.

---

## 7. Code and state removed

| removed | was |
|---|---|
| `wvNextAtLo`, `wvNextAtHi` | **2 bytes of director state** — the running sum |
| `waveTrigDelta` (table + `.var trigDelta`) | the delta column |
| the seed in `waveInit` | `wvNextAt = trigDelta[0]` |
| the wrap in `waveAdvanceCursor` | `cmp #WAVE_TRIGGERS / lda #0 / sta wvNextTrig` |
| the 16-bit running-sum add | `clc / adc / sta / bcc / inc` |
| the token-hold target walk | a 16-bit copy from `worldProgress`, every held frame |
| the delta-of-zero guard | meaningless for absolute rows |
| the wrapping species-alternation guard | trigger 3 has no successor |

No compatibility layer was left for the retired representation, and the new
comparison is not abstracted behind anything. Stale comments on the trigger
list, the state block, `waveInit`, `waveTick` and `waveAdvanceCursor` were
rewritten to describe what the code now does.

**The `waves` segment shrank from `$7c00-$7f4a` to `$7c00-$7f1d` — 45 bytes —
despite the trigger table gaining four.** Absolute rows are smaller *and*
cheaper: `waveAdvanceCursor` went from ~14 instructions to two, and the
per-trigger 16-bit carry chain is gone.

---

## 8. Before/after equivalence

Both columns measured on the running machine, from a frame-accurate boot at
`worldProgress = 0`.

| # | old accumulated target | **new absolute row** | old observed start | **new observed start** | def | species | fire | side |
|---|---|---|---|---|---|---|---|---|
| 0 | 48 | **48** | 48 | **48** | 0 SWEEP | 0 RING | `%0101` | 0 LEFT |
| 1 | 52 | **52** | 52 | **52** | 1 S-TURN | 8 DROPPER | `%0010` | 0 LEFT |
| 2 | 90 | **90** | 90 | **90** | 2 LINGER | 0 RING | `%0101` | 0 LEFT |
| 3 | 126 | **126** | 126 | **126** | 3 LOOP | 8 DROPPER | `%0000` | 1 RIGHT |

```
ok  exactly four triggers were consumed -- 4 firings at rows [48, 52, 90, 126]
ok  ...each at EXACTLY its authored row
ok  ...in cursor order 0,1,2,3, each consumed once -- [0, 1, 2, 3]
ok  waveTrigDef / Species / Fire / Side are unchanged by the migration
```

**Everything through the first four encounters is spatially and behaviourally
identical.** Definitions, formations, movement programmes, species, firing masks
and Dropper behaviour were not touched.

---

## 9. No-wrap proof

The delta schedule fired again at 174, 178, 216, 252, 300, 304, 342, 378, 426…
Every one is now absent.

```
ok  the cursor is exhausted on WAVE_TRIGGERS -- wvNextTrig = 4
ok  an exhausted cursor stays exhausted over three more old periods
    -- 1682 -> 1757: wvStarted = 0, cursor = 4
ok  every trigger consumed over the whole run was one an armed schedule
    authorised -- no wraparound anywhere
    -- 13 firings over 1757 coarse rows (13 old periods)
ok  ...and nothing was dropped for want of an instance -- wvDropped = 0
```

The total-firing reconciliation is the strongest form of this: over 1,757 coarse
rows — **thirteen old periods** — the only triggers consumed were the four
production ones, the eight disposable boundary ones, and the one released from
the token hold. Thirteen, exactly as authorised. Nothing was created by
wraparound anywhere in the run.

---

## 10. 16-bit boundary proof

Proved **dynamically**, with disposable schedules poked into the row columns at
runtime. Only the rows move — definition, species, fire mask and side keep their
authored values, so every wave these fire is a real production wave. They are
not production content, and the authored rows are restored and re-checked
afterwards.

```
ok  the disposable schedule [255, 256, 511, 512] is armed ahead of the world
    -- worldProgress 126 < 255
ok  all four fired, exactly once each, in order -- cursors [0, 1, 2, 3]
ok  ...each at EXACTLY its row, across the 8-bit boundary
    -- [255, 256, 511, 512]
ok  the disposable schedule [1023, 1024, 1535, 1536] is armed ahead of the world
ok  all four fired, exactly once each, in order -- cursors [0, 1, 2, 3]
ok  ...each at EXACTLY its row -- [1023, 1024, 1535, 1536]
ok  a trigger row far above the stage never fires
    -- cursor = 0 at worldProgress 1611 vs row $f000
```

All eight required rows, each firing exactly once at exactly its row. A compare
that dropped the high byte would fire 256 rows early; one that tested only the
high byte could not separate 255 from 256 at all.

`stageHold` — the scroller's own endless-stage diagnostic — is what makes the
world reach row 1,536 in the 395-row production stage, so no scratch build was
needed for this.

---

## 11. Token-hold proof

```
ok  the world passed the trigger's row while the encounter held it
    -- worldProgress 1641 > row 1615
ok  ...and the held trigger did NOT fire -- wvStarted = 0
ok  ...and it was not lost: the cursor still names it -- wvNextTrig = 0
ok  the held trigger fired once the encounter released it -- firings [(0, 1641)]
ok  ...exactly once, not once per row it was held over -- wvStarted = 1
ok  ...and the cursor moved on by exactly one -- wvNextTrig = 1
ok  ...and it did not fire again once released
```

Held across 26 coarse rows, fired once on release, neither lost nor duplicated.

**`tkActive` cannot simply be poked once.** `tokenTick` owns it, and with the
flag set but no real token in `tkSlot` the encounter ends itself on the next
frame and clears it — a first draft poked it once and watched the "held" trigger
fire immediately. The probe re-asserts it every frame of the hold window.

---

## 12. 420-row compatibility

`make proof420`, the full 1,655-row traversal, absolute triggers:

```
info traversed to worldProgress 1655, lvlPhase 2
ok  the 420-row stage traversed to its derived final row -- 1655
ok  the boss phase was reached after the long stage -- lvlPhase 2
ok  EXACTLY FOUR waves started over the whole 420-row stage
    (the wrapping schedule started 52) -- wvStarted = 4
ok  ...and the cursor stayed exhausted for the remaining ~1,500 rows
ok  ...with nothing dropped -- wvDropped = 0
ok  gameOverrun is zero across the 420-row traversal -- 0
ok  scrollLate is zero across the 420-row traversal -- 0
info publishSkip 12  schedBuildDefer 1  wvSpawned 13
```

**52 waves → 4.** The proof terrain was not modified; `src/level1` was not
touched. `build/proof420` was removed after use and `make build` restored the
production level.

---

## 13. Performance counters

| counter | 105-row production | 420-row proof | verdict |
|---|---|---|---|
| `gameOverrun` | **0** | **0** | clean |
| `scrollLate` | **0** | **0** | clean |
| `statPageMismatch` / `statPtrMismatch` | **0** | — | clean |
| `objDoubleFree` / `objAllocFail` | **0** | — | clean |
| `publishSkip` | 15–24 under monitor stepping; **0** in `test_production` | 12 | known noise, and see §14 |
| `schedBuildDefer` | 1–13 under heavy stepping | 1 | known noise |

Runtime cost moved the right way: `waveTick` loses nothing on an ordinary frame,
the trigger-due path loses a 16-bit carry chain, and `waveAdvanceCursor` is now
one `inc`.

---

## 14. Test results, and unrelated / consequential failures

Baseline runs were taken from a scratch tree identical to the working tree with
**only `src/waves.asm` reverted to HEAD**, so attribution is exact.

| suite | baseline (delta) | after (absolute) | verdict |
|---|---|---|---|
| build | clean | clean | — |
| **`tests/test_wave_triggers.py`** (new, 41 checks) | n/a | **ALL PASS** | — |
| 420-row proof (disposable) | n/a | **ALL PASS** | — |
| `test_boot` | pass | **ALL PASS** | — |
| `test_boss` | pass | **ALL PASS** | — |
| `test_lifecycle` | pass | **ALL PASS** | — |
| `test_turret_regression` | pass | **ALL PASS** | — |
| `test_production` | 1 failure: `publishSkip` | 1 failure: **`the pool actually cycled`** | **consequential — §14.1** |
| `test_encounter_director` | 2 failures: `publishSkip`, `schedBuildDefer` | **8 failures** | **consequential — §14.2** |
| `test_pickup` | `KeyError: waveTrigTokenLo` | same | pre-existing, untouched |

### 14.1 `test_production` — the failure changed, and both halves have one cause

Baseline failed `publishSkip` and passed the pool-cycling check. The new build
does the opposite, **deterministically across two runs**:

```
=== CURRENT test_production run 1 === 1 FAILURES: the pool actually cycled ...
=== CURRENT test_production run 2 === 1 FAILURES: the pool actually cycled ...
```

Both halves are the same single cause: **the level is now quiet past row 126.**
The harness boots with `_boot_to_game`, whose eight fire presses cost a second
of warp each, so sampling begins at roughly `worldProgress` 800. There are no
enemies there any more, so the pool population no longer varies — and with the
load gone, `publishSkip` stops being exceeded, which is why that failure
*disappeared*. The disappearance is corroborating evidence, not luck.

### 14.2 `test_encounter_director` — six new failures, all the same cause

```
an authored trigger started a wave during the run;
two wave instances were active concurrently for a real span;
enemies from two different wave definitions were on screen together;
at least one enemy progressed through several distinct phases of the curved
    primitive;
one enemy walked its authored path through several movement stages;
an enemy despawned and returned its pool slot
```

Every one of these requires a wave to start **inside the sampling window**. That
file uses `Vice(6661, PRG, warp=True)` — the default harness boot — and then
samples a bounded number of frames from roughly `worldProgress` 800. Measured
directly: a harness-style boot lands at `worldProgress` 395–811 with
`wvNextTrig = 4` and `wvStarted = 4`, i.e. **the schedule is already exhausted
before the test takes its first sample.**

Under the wrapping schedule a wave arrived every 126 rows for ever, so the
window always contained one. It never will again, and that is the intended
result: *"After the fourth trigger the level will intentionally become quiet."*

**The test was not modified, weakened or skipped.** It is now asserting about a
scenario the game no longer has. Fixing it means making it sample before row 48
— a frame-accurate boot, which `tests/test_wave_triggers.py` implements as
`boot_frame_accurate` and which would have to move into `tests/harness.py` to be
shared. That is a harness change affecting every test in the suite, and squarely
outside this task's scope. **Recommended as the first item of stage 2 work**, or
as a standalone test-infrastructure task.

### 14.3 Known noise, reported not hidden

`publishSkip`, occasional `schedBuildDefer = 1` (13 under heavy monitor
stepping), the stale `test_pickup` reference to the long-removed
`waveTrigTokenLo`, and population-sampling variation — all pre-existing, all
untouched, none weakened.

### 14.4 Three measurement traps paid for in this task

Recorded because AGENTS.md rule 4 exists for exactly these:

1. **`harness._boot_to_game` costs ~800 coarse rows.** A second of warp per fire
   press. Any probe that wants to see row 48 must boot in frames.
2. **`x` on a breakpoint that is not hit does not stop the machine.** A first
   frame-accurate boot stepped on `mainLoop` — which the router only reaches on
   a *state change* — and arrived at PLAYING with `worldProgress` already 395
   and the boss up: the stage had begun, run out and ended inside the
   "frame-accurate" loop. `gsAttractLoop` and `gameFrame` are now armed together
   so every frame of the transition stops somewhere. The same trap left the
   world at 603 when a collector meant to leave it at 134, putting the 255/256
   boundary permanently out of reach.
3. **`re.search` for the monitor prompt matches a STALE one** left in the socket
   by an earlier command. Taking the **last** match is what makes the address
   the one this command stopped at; with `re.search` the first two production
   triggers were silently missed and the run reported firings at `[90, 126]`
   instead of all four.

No assertion in any existing test was weakened to obtain a green result.

---

## 15. Manual VICE

**Launched and left running for you: PID 43115** — `x64sc`, **PAL, visible
window, non-warp, no acceleration**, autostarting `build/shmup.d64` (the
restored 105-row production Level 1).

Manual visible output is authoritative (AGENTS.md rule 2). **Please confirm by
eye:**

1. **The first four encounters are exactly as before** — the sweep from the left
   border, the S-turn from above on the other side, the linger, then the loop.
   Same places, same formations, same species, same shooting.
2. **The overlap between the first two is unchanged** — rows 48 and 52 are four
   rows apart and deliberately put two instances in flight at once.
3. **After the fourth, the old sequence does NOT restart.** Under the previous
   build a sweep reappeared at row 174, about twenty seconds after the first.
   That must not happen; the remainder of the stage is intentionally quiet.
4. **Scrolling is unchanged** — smooth 1 px/frame, ~63 s to the boss.
5. **Turrets, P-token and HUD behave normally**, including through the quiet
   stretch.
6. **Stage end and the boss transition are normal**, and the arena is empty when
   the boss arrives.

Item 3 is the one this task exists for, and item 6 is the one most worth
watching: with no encounters after row 126 the arena reaches the boss boundary
already empty, so `ARENA_CLEAR_DEADLINE` should never be needed.

Close it yourself, or say the word and I will terminate **that exact PID**. No
broad `pkill`/`killall` was used anywhere; every automated instance was launched
with `-console`, owned by PID, and reaped, and `pgrep -fl x64sc` confirmed a
clean field before each run.

---

## 16. Files changed

| file | change |
|---|---|
| `src/waves.asm` | the whole of this task: absolute rows, no wrap, exhaustion, the removed running sum and the rewritten comments |
| `tests/test_wave_triggers.py` | **new** — the 41-check permanent regression |

`src/level1`, the `$e000` loader, the memory contract, the scroller, movement
primitives, wave definitions, formations, species semantics, Dropper/P-token
architecture and the boss approach were **not touched**.

---

## 17. Final git status and diff

```
$ git status --porcelain
 M src/waves.asm
?? tests/test_wave_triggers.py

$ git diff --stat
 src/waves.asm | 229 ++++++++++++++++++++++++++++++++++++++--------------------
 1 file changed, 149 insertions(+), 80 deletions(-)
```

The insertion count is comments: the executable change is a net **reduction**,
and the assembled `waves` segment shrank by 45 bytes.

---

## 18. Disk usage

```
$ du -sh build/    292K
$ du -sh .         8.2M
```

`build/` holds the current binary, symbols, the level package and the disk
image. `build/proof420` — generated by `make proof420` for §12 — was removed
after use; `make proof420` regenerates it on demand. The pre-change baseline
tree used for §14's attribution was built in disposable scratch outside the
repository and deleted; `/tmp` carries no residue. No per-run directories exist.

---

## 19. Confirmation

**Nothing was committed. Nothing was pushed.** No destructive reset was used, no
report was altered or removed, no unrelated cleanup was performed, and no test
was fixed, weakened or hidden.

**The stop condition was not reached.** Absolute triggers required no change to
movement programmes, formations, species semantics, the token architecture,
level loading or the scroller — the migration was confined to the trigger
representation and the director's cursor, exactly as the roadmap predicted.

Stage 1 is complete. Movement-programme externalisation, `STAGE_NO_SPAWN_ROW`,
the `$f530` encounter package, mirror masks, `WAVE_SLOTS = 4` and editor work
were **not** begun.
