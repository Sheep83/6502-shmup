# Encounter Director test haircut

Encounter Director v1 is manually GREEN (visually qualified in VICE: two
player sprite layers, seven enemies, one enemy projectile, two background
turrets, no skips/hitches/raster instability). This was a bounded cleanup of
its permanent regression test only — no gameplay, movement, renderer,
scheduler, object pool, or authored-content changes.

## What was removed from `test_encounter_director.py`

- **The synthetic pool-pressure section entirely** (section 9 of the old
  file, ~100 lines): filling all 16 pool slots by hand via `objectAlloc`/
  `objectActivate` called from the monitor, waiting for a wave mid-spawn to
  pressure, then asserting `wvDeferred` increased and no member was lost.
  This was real implementation-time qualification of the defer-on-
  allocation-failure policy, but it posed a state the real game cannot reach
  on its own and does not belong in a permanent fast regression. The
  production defer-on-allocation-failure behaviour is untouched.
- **The pairwise independent-advancement analysis** (old section 4): the
  lockstep-timer check across two active instances, and the "does sending a
  member on one wave rewrite the other's definition" disturbance scan.
  Observing two distinct concurrent active instances with different
  definitions is enough for this regression.
- **The velocity-smoothness proof of the arc primitive**: the "no phase
  change moves a velocity component by more than one quarter pixel" check
  and the "the turn genuinely changes direction" check. Those proved the
  authored arc table was implemented correctly at build time; the permanent
  regression only needs to see the primitive progress through several
  distinct phases.
- **The requirement to observe all 16 arc phases** — replaced with a
  threshold of 4 distinct phases in one continuous run.
- **Per-frame Y-band / sprite-clipping check, `logY` sampling, `logCount`
  per-frame sampling, `wvTimer`/`wvIndex`/`wvLeft` sampling** — none of these
  fields were needed for the six required proofs; dropping them cut the
  monitor round-trips per frame from 5 to 4.
- **The fixed 700-frame capture-then-analyze structure** — replaced with a
  frame-by-frame loop (capped at 650 frames as a safety margin, one full
  authored cycle is ~512 frames) that exits the instant every required
  behaviour has been witnessed, instead of always walking a fixed count.
- **The `s8()` signed-velocity helper and `MIN_SPRITE_Y`/`MAX_SPRITE_Y`
  constants**, no longer used.

## What the slim regression still proves

Watching the real production frame loop the entire time (no direct calls to
`waveTick`, `wmTick`, or `waveSpawnMember`):

1. an authored trigger starts a wave;
2. a second wave instance becomes active concurrently with the first, for a
   real span (≥5 consecutive frames, not one flickering frame);
3. enemies from both wave definitions (by colour) are on screen together;
4. at least one enemy progresses through ≥4 distinct phases of the curved
   (arc) movement primitive, with slot-reuse correctly excluded from the run
   (a despawned slot's replacement is not read as the same enemy continuing
   its arc);
5. an enemy despawns and returns its pool slot through the ordinary
   `objType` transition;
6. the production health counters (`gameOverrun`, `publishSkip`,
   `schedBuildDefer`, `scrollLate`, `edgeLate`) stay zero throughout, plus
   `wvDropped`, `objAllocFail`, `objDoubleFree` at boot and at the end.

A small, monitor-call-free layout check still guards the two field-pair
contiguity assumptions (`wvActive`/`wvDef`, `wmMode`/`wmNext`/`wmPhase`) the
bulk reads rely on.

`test_encounter_director.py`: 399 lines → 209 lines.

## Runtimes

- **Focused test** (`make test-encounter-director`): ~18 seconds wall time
  (down from ~3 minutes). The loop satisfied every required condition within
  67–77 sampled frames on both runs, well inside the 650-frame cap and the
  30–90s target.
- **Full gate** (`make test`): 7m26s wall time in this run. The encounter
  director test's own contribution to that total was ~20–25s (consistent
  with its isolated runtime); the remainder is `make build`'s unconditional
  KickAssembler recompile (phony `build` target, reruns every invocation)
  plus the three untouched tests — `test_boot.py`, `test_production.py`
  (which explicitly free-runs a 10-second health window and several other
  real-time phases), and `test_turret_regression.py` — each of which also
  pays its own ~4–5s VICE launch/settle cost. None of those were in scope
  for this task and none were modified. This run's wall-clock total is
  higher than the ~6.5-minute figure quoted at the start of this task; given
  the instruction not to re-run gates chasing a number, this is reported as
  measured rather than re-benchmarked. What did change, and what this task
  was scoped to change, is real: the director test's own footprint dropped
  from ~3 minutes to well under 30 seconds.

## Results

- `make test-encounter-director`: **PASS** (all 19 checks green).
- `make test`: **PASS** (all four suites green — boot, production, turret
  regression, encounter director).

## Production source

No files under `src/` were touched (`git diff --stat -- src/` is empty).
Encounter Director v1's implementation, movement, renderer, scheduler,
object pool, encounter timings, and authored wave content are unchanged.

## VICE hygiene

Every automated run launched exactly one owned `x64sc` PID, verified as the
actual listener on its port before talking to it, and reaped it on exit
(`rc=-15`, i.e. terminated cleanly by the harness). No manual/pre-existing
VICE process was present before either run and none was left running after
either run. No persistent joystick/keyset/vicerc preferences were altered
(`-default +saveres` per the existing harness).

## Disk

```text
$ du -sh build/
88K     build/

$ du -sh .
4.2M    .
```

No per-run artifacts accumulated; `build/` holds only the standard three
build outputs (`shmup.prg`, `main.sym`, `main.vs`).

## Git

```text
$ git status --short
 M Makefile
 M tests/test_encounter_director.py

$ git diff --stat
 Makefile                         |  15 +-
 tests/test_encounter_director.py | 504 ++++++++++++---------------------------
 2 files changed, 167 insertions(+), 352 deletions(-)
```

Only the test file and the `make test` comment block describing it were
touched. `.vscode/settings.json` is not part of this diff. No commit was
made, per instructions.
