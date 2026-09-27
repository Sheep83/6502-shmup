# Testing policy — 19656

**Routine development = smoke regression + manual playtest.**
**Full suite = final certification, or changes to sensitive engine architecture.**

The engine, multiplexer and scroller are mature and effectively frozen. The
33-suite battery in `tests/` was built to establish their capacity and to
diagnose them while they were still moving. It is a **certification** tool. It
does not need to re-prove the multiplexer every time somebody redraws a
spaceship.

---

## 1. Routine regression — run this

```
python3 tests/run_smoke.py        # ~75 seconds
make smoke                        # the same thing, after a build
```

It answers four questions and stops:

1. does it build and boot?
2. does the campaign loop still turn?
   `ATTRACT -> PLAYING -> LEVELDONE (shop) -> CONTINUE -> level 2 resident and
   PLAYING -> GAME OVER -> back to the front`
3. what do the engine health counters say over a real uninterrupted window?
4. has anything catastrophically broken?

Nine counters are **fatal** if non-zero — each means a frame was *mishandled*:
`gameOverrun`, `scrollLate`, `edgeLate`, `statOverflow`, `statPageMismatch`,
`statPtrMismatch`, `objDoubleFree`, `objAllocFail`, `clipPoolFull`.

Three are **reported, not asserted**: `publishSkip` (see below),
`schedBuildDefer` (a documented bounded cost that "cannot starve"), `statLate`.

### publishSkip is not a zero-or-fail invariant

A rare in-play publication miss is known, understood and permitted: when a
main-thread pass straddles raster 250 the engine drops one scroll update,
recovers by itself, and costs about one pixel. Measured at roughly **one event
per 10,000–60,000 frames** — see `reports/publish-skip-in-engine-capture.md`.

The runner **reports the count and the frames observed** and fails only above a
deliberately coarse budget (**5** per ~3,000-frame window). At the measured rate
such a window expects well under one event, so 1 is unremarkable and 5 would mean
the rare thing had become a common thing. **Do not open an investigation because
the number is not zero.**

## 2. Manual playtesting — authoritative

The game plays through in about five minutes. Manual VICE, and especially
MiSTer/CRT, is **authoritative** for gameplay feel, sprite and art correctness,
animation, encounter behaviour, visual glitches, collisions in ordinary play,
balance, presentation and content. `AGENTS.md` rule 2 already says this: a
passing harness is evidence, never a veto over what a human can see.

Do not try to automate what five minutes of play establishes better.

## 3. Full certification suite — the big hammer

```
make test-fast      # 12 bounded suites, worst case ~13 min
make test           # the curated integration set, ~18 min
make test-full      # all 33 suites, ~62 min on a good day
make test-soak      # the 8 whose runtime is UNBOUNDED (25 s - 2226 s each)
```

**Run full certification when:**

* preparing a release;
* the **multiplexer** architecture changed;
* the **scroller or raster** architecture changed;
* **renderer scheduling or capacity** changed;
* **clipping or object-pool** architecture changed;
* you are deliberately investigating engine capacity.

**Do not run it** — and do not "repair" it — after ordinary sprite art,
animation, level content, sound, presentation or balance work, unless that work
touched one of the systems above. Routine runner plus a playtest is the answer
there.

### Known state of the full suite

It is slow and partly red **on purpose**, and the failures are understood and
catalogued in `reports/test-suite-audit-and-purge.md` and
`reports/test-suite-rehabilitation-phase2.md`. In particular eight suites have
runtime that varies 5x-69x between runs because they wait for authored content
to happen; that is a known limitation, recorded rather than repaired. A red
certification suite is not a licence to start fixing tests instead of making the
game.

---

## Which primitive should a test use to advance the machine?

This is the mistake the suite has made most often, so it is written down:

| primitive | unit | works in non-game states? | use for |
|---|---|---|---|
| `free_run(seconds)` | host time | yes | letting the game breathe. **Never** assert on a window it sized |
| `run_frames(n)` / `step_n(n)` | game frames, verified | **no — gameplay only** | sampling what the engine computed |
| `soak_frames(n)` | game frames, measured | gameplay | judging whether the engine **kept up** |
| `run_until_state(pred)` | host time, bounded | **yes** | driving the lifecycle across states |

> **If the test asks what the engine computed, step it. If it asks whether the
> engine kept up, soak it. If it is driving the lifecycle, use
> `run_until_state`.**

`run_frames`/`run_until` arm a breakpoint on `gameFrame`, which does not execute
while `gsNonGame` is set — so in ATTRACT, the shop, GAME OVER or INITIALS they
advance nothing at all and a caller waits for ever.
