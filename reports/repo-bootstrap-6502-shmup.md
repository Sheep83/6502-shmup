# Repository bootstrap — 6502-shmup

**Result: `/Users/brianmorrice/Dev/C64 ASM/6502-shmup` is an independent, clean,
buildable Git repository containing the qualified production engine, a compact
regression probe, and a written engine contract. It builds and runs with no
reference to the old repository. Nothing was committed and no remote exists.**

`6502-engine` is byte-for-byte unchanged.

---

## 1. Source repo state

```
HEAD    3708cfff5a8bd84548f8301eaa7b359152556e37
        "HUD elements added, engine v1.0"
status  clean -- no uncommitted changes
```

The working tree equalled HEAD, so the question of copying uncommitted
production files did not arise; the copy is the current qualified source either
way. Verified unchanged again at the end of this task: same HEAD, empty status.

Nothing in `6502-engine` was modified, moved, renamed, cleaned or re-initialised.

## 2. Destination

```
/Users/brianmorrice/Dev/C64 ASM/6502-shmup
```

Confirmed not to exist before creation.

## 3. What was copied

| from | what | why |
|---|---|---|
| `src/` | **all 12 `.asm` files** | see §16 — they are one coupled unit |
| `tests/` | `test_p0..p5`, 4 model files, `sprite_identity.py` | see §5 |
| `tools/` | `gen_p3_fixtures.py`, `gen_p4_fixtures.py`, `gen_p5_tables.py` | they generate committed source data; the suites check it for drift |
| root | `Makefile`, `.gitignore`, `.vscode/tasks.json` | build tooling |

Written fresh for this repo: `README.md`, `AGENTS.md`,
`docs/ENGINE_CONTRACT.md`, `reports/README.md`, `tests/test_engine.py`.

## 4. What was deliberately omitted

| omitted | why |
|---|---|
| `.git/` | new repo, fresh history — not a clone |
| `build/` (3 files) | generated; recreated by `make build` |
| `reports/` — **19 historical reports** | archaeology. Stays authoritative in `../6502-engine/reports` |
| `docs/` — 6 files: `manual-acceptance.md`, `qualification-ladder.md`, `p2-static-y-matrix.md`, `p3-scripted-motion.md`, `p4-dynamic-y-sorter.md`, `reuse-inventory.md` | qualification-ladder archaeology, superseded by `docs/ENGINE_CONTRACT.md`. The VICE launch discipline they documented is preserved in the Makefile's `VICE_OPTS` comment and the README |
| `tests/test_transition.py` | fixture-transition hardening machinery — exhaustive qualification archaeology, not useful during ordinary development. Nothing imports it |
| `tools/capture_p0.py` | screenshot aid for the P0 fixtures specifically; archaeology |
| `.DS_Store` | noise |

The three `du` figures: source repo 3.1 M, new repo **1.2 M** including a 76 K
`build/`.

## 5. Tests retained, and why

The invariants the brief names are covered as follows:

| invariant | covered by |
|---|---|
| frame transaction at raster 250 | `test_engine`, `test_p1`, `test_p3`, `test_p4`, `test_p5` |
| publication / CURRENT immutability | `test_engine` (source-level single-writer), `test_p1` (freeze the main thread and keep rendering), `test_p4` |
| gameplay mux reuse | `test_p2`, `test_p3`, `test_p4` against the shared independent model |
| X-MSB / `$d010` | `test_p3` (MSBFLIP6, X255), `test_p5`, `test_engine` (handoff restoration) |
| page/pointer coherence | `test_engine`, `test_p1` |
| aperture timing | **`test_engine`** — both splits, `edgeLate`, per fixture |
| HUD ghost / handoff | **`test_engine`** — HUD and handoff entry/exit rasters, pointer pools, `$d015` ownership; `test_p4` (`$d015` three-owner model, pointer sanity) |
| representative moving-sprite regression | `test_p5` (ring modes), `test_p3` (motion fixtures) |

**`tests/test_engine.py` is new and is the headline retained check.** It reads
the engine's *own* instrumentation counters rather than re-deriving anything —
`frameEntryLine`, `hudEntryMin/Max`, `hudExitMax`, `handoffEntryMin/Max`,
`handoffExitMax`, `topSplitMin/Max`, `botSplitMin/Max`, `edgeLate`,
`hudUpdWrapped`, `hudUpdStartMin`, `statPageMismatch`, `statPtrMismatch`,
`scrollLate` — across five fixtures in about a minute. Because every one of
those is a min/max or a saturating fault count, a single reading speaks for tens
of thousands of frames.

**It closes a real gap.** Those counters were added across implementation slices
1-4 and were only ever checked by transient scratch scripts; no committed test
read them. The aperture splits, the HUD phase and the handoff — the newest and
most delicate machinery in the engine — had no standing regression at all.

**`tests/test_p2.py` was retained despite being the most archaeological suite**,
because it is not only a suite: `test_p3`, `test_p4` and `test_p5` all import
helpers from it (`poke`, `measure`, `worst_of`, `set_pin`, `clear_pin`,
`build_case`, `collect`). Dropping it would have broken three retained suites.
Its own exhaustive boundary matrix is no longer in any default target; it is
invokable deliberately with `make test-p2`.

## 6. Tests omitted, and why

Only `tests/test_transition.py` (287 lines). Its purpose was fixture-transition
hardening — proving a fixture change cannot produce a mixed CURRENT. That is
qualification archaeology about a fixture-selection path the game will not use,
nothing imports it, and the one production invariant it also checked
(`statRejRange` on MAXCAP) is checked by `test_p3`.

Nothing else was dropped. Per the brief, correctness checks were not weakened to
make the repo look smaller.

## 7. Renamed identifiers

```
build/engine.prg   ->  build/shmup.prg
build/engine.d64   ->  build/shmup.d64
/tmp/6502-engine-* ->  /tmp/6502-shmup-*        (test scratch directories)
Makefile header, .vscode task labels, src/main.asm file header
```

Applied to `Makefile`, `.vscode/tasks.json`, `tests/test_p0..p4`, `src/main.asm`.
**No architectural symbol was renamed.** `exFrame`, `exHud`, `exHandoff`,
`exTop`, `exBottom`, `PTR_A/B`, `HUD_*`, `MIN_SPRITE_Y` and the rest are
untouched — renaming them for cosmetics would have invalidated every report in
the sibling repo that refers to them.

The Makefile's test surface was retargeted, which is a change of intent rather
than of engine code:

```
make test               tests/test_engine.py                      ~1 min
make test-fast          + p5 model, ring table drift, p5 --fast
make test-engine-full   the inherited ladder, test_p0..test_p5    slow
make test-p0 .. test-p5 each suite, invokable deliberately
```

`make capture` and `make test-transition` were removed with their scripts.

## 8. `docs/ENGINE_CONTRACT.md`

Ten sections, every constant read out of `src/` rather than remembered:

1. how game systems talk to the renderer — logical sprite state in, and the
   architectural test that CURRENT is immutable;
2. hardware slots: HW0/HW1 reserved, HW2-HW7 the mux pool shared with the HUD;
3. admission rules — `MIN_SPRITE_Y 55`, `MAX_SPRITE_Y 226`, `REUSE_LEAD 12`,
   `MIN_REUSE_GAP 33`, `MAX_SCHED 24`, and the fact that a sprite at Y=n is
   displayed on n+1..n+21;
4. the raster phase schedule — 4 HUD, 40 handoff, 53 top split, mid-screen
   batches, 243 bottom, 250 adoption-only — and that structural phases are never
   chased except a late top split;
5. HUD ownership, the unconditional register restoration, why `$d017` is
   forbidden to the HUD, and the Y+256 ghost rule;
6. HUD bitmap preparation — the 16..37 fetch window, the 56..200 write window,
   `hudUpdWrapped`, and why the update lives in the idle spin;
7. page and pointer ownership — one patched byte, adopted page only;
8. the blank-charset aperture with the four `$d018` values and the 55..247
   visible band;
9. **who owns which VIC register**, and that game logic must not bypass those
   owners — with `src/hud.asm` named as the model for how a new subsystem
   participates;
10. the known deferred performance issue, carried forward verbatim (§12 below).

## 9. Build

Clean build from an empty `build/`, entirely inside the new repo:

```
$0810-$0c84 main           $2000-$23ff diagnostic sprites
$1000-$12a2 schedule builder   $2400-$27ff p5 ring tables
$1300-$13f6 p5 ring        $2c00-$3005 raster executor
$1400-$17ca hud code       $3200-$357f hud bitmaps
$1800-$19ea fixtures       $c000-$cfda state, tables and glyphs
$1a00-$1bc2 scroller
```

`build/shmup.prg` written, 51,164 bytes. No warnings, no errors.

## 10. Smoke

`make test` — **ALL PASS**, five fixtures, ~26,000 frames:

```
  fixture      frames   HUD      exit  handoff   exit  top       bottom      late  FEL  wrap  admitted Y
  boot/fix0     7050   [4, 4]     10  [40, 40]    51  [54, 55]  [248, 248]    0  250     0  60..210
  MAXCAP        3099   [4, 4]     10  [40, 40]    51  [54, 55]  [248, 248]    0  250     0  56..194
  RING-SLOW     3255   [4, 4]     10  [40, 40]    51  [54, 55]  [248, 248]    0  250     0  70..210
  RING-FAST     6653   [4, 4]     10  [40, 40]    51  [54, 55]  [248, 248]    0  250     0  70..210
  RING-SHIFT    6602   [4, 4]     10  [40, 40]    51  [54, 55]  [248, 248]    0  250     0  63..201
```

Every phase on its own line, both aperture splits exact, page/pointer coherence
clean, no HUD bitmap write ever in the VIC's fetch window, every admitted sprite
inside 55..226.

Visual smoke on the booted binary, captured at the HUD phase:

```
  HUD band     rasters 17..37 : 11 lit lines  -> HUD IS PRESENT
  gap          rasters 38..54 : 0 lit lines   -> clear
  playfield    rasters 55..247: 189 lit lines -> TERRAIN IS SCROLLING
  below/ghost  rasters 248..  : 0 lit lines   -> clear, no ghost
  SMOKE: PASS
```

Module graph after dropping `test_transition.py`: all twelve retained test
modules import cleanly. `gen_p5_tables.py --check` reports the ring tables still
match the model; `gen_p3_fixtures.py --check` passes.

## 11. Proof of independence

```
references to "6502-engine" in .asm / .py / Makefile / .json :  1, a Makefile
                                                                prose comment
absolute paths outside this repo                             :  none, except the
                                                                KickAssembler jar
parent-directory escapes ("../")                             :  none
```

Every harness path derives from `ROOT = Path(__file__).resolve().parent.parent`.
The build wrote `/Users/.../6502-shmup/build/main.vs` — inside the new repo. The
only remaining mentions of the old repo are in `README.md`, `AGENTS.md`,
`reports/README.md` and one Makefile comment, all of which point at it
deliberately as the archaeology source.

## 12. Known issue carried forward

Recorded in `docs/ENGINE_CONTRACT.md` §10, unchanged and **not** worked on:

- `FIX16 / MAXCAP` is an intentionally abusive stress ceiling and is **not** a
  production optimisation target. Its visual glitch has varied as the raster
  phases changed and may currently be clean; use it to detect *new* catastrophic
  corruption only.
- `RING-SLOW` and `RING-SHIFT` show visibly jerky motion and background
  glitching under their 16-sprite moving workload — roughly 12 % frame-record
  publication skips. `RING-FAST`, `MAXCAP` and every lighter fixture measure
  zero.
- This is a **known deferred performance issue, not an engine correctness
  failure**. The sprite schedule has no skip path and is never dropped or stale;
  what is lost is one frame of scroll.
- It correlates with frame-record publication under high-batch moving workloads,
  and it is **not** caused by the HUD — measured with the HUD phase bypassed
  entirely and with the HUD demo stubbed out, the rate is unchanged.
- To be revisited with realistic production scenes at roughly **6 / 8 / 10 / 12
  / 14 / 16** gameplay sprites.

## 13. Disk

```
du -sh build/   76K
du -sh .        1.2M        (source repo, for comparison: 3.1M)
```

`build/` holds `shmup.prg`, `main.sym`, `main.vs` and nothing else. No per-run
directories. Transient captures went to `/tmp` and were deleted.

## 14. Git status

```
branch:  main
remotes: 0
commits: 0

?? .gitignore   ?? .vscode/   ?? AGENTS.md   ?? Makefile   ?? README.md
?? docs/        ?? reports/   ?? src/        ?? tests/     ?? tools/
```

`.git/` is freshly initialised, not copied — it contains only the default
skeleton. `build/`, `*.prg`, `*.vs`, `*.sym`, `.DS_Store` and `__pycache__/` are
ignored, so the generated binary is correctly untracked.

## 15. No commit, no remote, no push

Confirmed: **0 commits, 0 remotes, nothing pushed, no GitHub repository
created.** Everything above is staged as untracked working-tree content awaiting
your authorisation.

## 16. Decisions that need your approval before game migration

**1. The whole of `src/` was copied, fixtures included — this is the big one.**

The brief asked for a repo that does not feel like a copied qualification
laboratory, and `src/` is still exactly that: `fixtures.asm`, `p3_fixtures.asm`,
`p4_fixtures.asm`, `p5_ring.asm`, `p5_tables.asm` and `motion.asm` are fixture
machinery, and `sprites.asm` is sixteen diagnostic numerals rather than game art.

They were kept because removing them is **not** a copy decision, it is an engine
change. `main.asm`'s boot path calls `rebuild` → `loadFixture`, its main loop
calls `motionTick` and `republish` for moving fixtures, and its key scan selects
fixtures; `renderer.asm` consumes the logical arrays those fixtures fill. Cutting
them means rewriting `main.asm`'s main loop and inventing whatever feeds logical
sprite state instead — which is the first act of game migration, and this task
explicitly forbids beginning it.

So the baseline boots and visibly demonstrates the qualified engine, as asked,
and the fixture corpus is the thing game migration replaces first. **If you would
rather the fixtures were stripped and replaced with a minimal "one moving sprite"
driver as part of the migration's first step, say so and that becomes slice 1 of
the migration rather than a repo-split decision.**

**2. `sprites.asm` will need real art.** The sixteen hollow-rectangle numerals
are diagnostic by design — a sprite showing the wrong number is meant to be
unmissable. They are the right thing for regression and the wrong thing for a
game. The HUD's own bitmaps (`src/hud.asm`) are already purpose-built and do not
have this problem.

**3. `HUD_VISIBLE = false` in `main.asm`** still switches off the *old*
in-matrix diagnostic HUD rows (distinct from the sprite HUD, which is always on).
The dead code behind that switch is a candidate for removal during migration;
it was left alone here because deleting it is an engine change.

**4. The regression ladder is inherited, not designed for this repo.**
`test_engine.py` is the check to grow. The P0-P5 suites are a safety net for
engine work; when game systems start replacing fixtures, several of them will
lose their subject and should be retired deliberately rather than left to rot.
