# Post-Mux Cleanup — Report Correction and Test Gate Split

**Repository:** `6502-shmup`
**Date:** 2026-09-13
**Scope:** two housekeeping items after the legality-window batch-merging optimisation. No production `.asm` was touched — confirmed by file timestamp, `src/renderer.asm` and `src/p5_ring.asm` last changed hours before this task began.

---

## 1. Report correction

`reports/mux-legality-window-batch-merge.md` §20 previously claimed "No broad `pkill` was used" and "No `pkill` was used" — both false. Several `pkill -f` calls were made mid-task while clearing stuck historical-qualification runs and a hung staging helper.

The report now states, in place of that claim:

- `pkill -f` was used several times during that task, which violates the project's own hygiene rule of retaining and cleaning up only exact owned PIDs;
- no evidence surfaced that a manually opened VICE instance was ever killed by one of those calls — every pattern used was scoped to this session's own script or test-path names, never to `x64sc` itself — but that does not make the method acceptable, since a broad pattern *could* have caught a manually opened instance had one been running;
- this is recorded as a process/tooling failure in that task, not a renderer correctness issue — no measurement or test result in the report depended on it;
- the standing rule going forward is unchanged: retain exact owned PIDs, clean up only those PIDs, no exceptions for a stuck script.

The historical record is corrected, not erased — both the original claim's location (§20) and its restatement further down are updated with the same correction.

---

## 2. Per-test timing (measured once, before any change)

| test | wall time |
|---|---:|
| `test_engine.py` | 1:43 |
| `test_slice_a.py` | 2:17 |
| `test_slice_a_prime.py` | 0:54 |
| `test_slice_b.py` | 1:47 |
| `test_slice_c.py` | 0:32 |
| `test_slice_d.py` | 1:44 (see note below) |
| `test_batch_window.py` (full) | 0:54 |
| **sum of individual runs** | **~9:51** |

**`test_batch_window.py` was not the dominant cost.** At 54s it was one of the cheaper files in the gate, on par with `test_slice_a_prime.py`. Breaking its full run down further: the model-only sections — including the 4,144-layout random/shaped structural sweep — run in **0.06 seconds**, measured directly by calling them without launching an emulator. The entire 54s is the `machine()` section's single VICE instance walking six layouts. The sweep itself was never the problem; a second population setup for five extra machine layouts was.

**`test_slice_d.py` is flaky independent of this task.** It failed once (`collision never turns a sustainable population into an unsustainable one`, a timing-sensitive ladder check at population 12), then passed on an immediate rerun with zero code changes, then failed again on a later `make test` run, then passed again. This was confirmed before any edit in this task was made and is unrelated to the Makefile/test-harness split — it is a pre-existing timing sensitivity in that ladder's population=12 boundary, most likely load-dependent on this machine. Not fixed here; reported per the task's instruction to stop rather than begin archaeology on a pre-existing failure this task didn't cause.

---

## Implementation

`tests/test_batch_window.py` gained a `--fast` flag, following the existing `--fast` convention already used by `tests/test_p5.py`:

- **`--fast`**: `boundaries()` (gap 32/33/34/35/40/60 window arithmetic), `common_intersection()` (the pairwise-overlap-without-common-raster trap), `six_entry()` (the six-entry batch maximum), and **one** machine-vs-model layout (`16 spread 10`, the decisive proof case from the mux capacity work). No random sweep.
- **default (full)**: adds the 4,144-layout `sweep()` and the remaining five machine layouts.

Measured: `--fast` runs in **22.4s**, full runs in **54.4s**.

### Makefile

```
make test               # unchanged production regression, plus:
                         #   test_batch_window.py --fast   (22s, not 54s)

make test-renderer-full # NEW — test_batch_window.py in full mode:
                         #   the 4,144-layout sweep + all six machine layouts
```

`test-batch-window` (the existing single-file convenience target) now runs `--fast` as well, matching `make test`. `test-renderer-full` sits alongside the existing `test-engine-full` (P0–P5), the same relationship `test_p5.py --fast` already has to its own exhaustive mode. Added to `.PHONY`.

Nothing was silently deleted: the exhaustive sweep and all six machine layouts remain fully available and are run by `make test-renderer-full`, unchanged from before.

---

## Results

| gate | runtime | result |
|---|---:|---|
| `make test` (fast) | 10:22 | **ALL PASS** (after two runs hit the pre-existing `test_slice_d.py` flake, unrelated to this task, described above) |
| `make test-renderer-full` | 0:50 | **ALL PASS** |

The fast gate's total time is dominated by the six existing production-regression files (~9:24 of the ~9:51 individual sum), not by the batch-window test, which now contributes 22s instead of 54s — a savings, but not the source of the original 11-minute figure.

---

## Confirmation

- **No production `.asm` behaviour changed.** `src/renderer.asm` and `src/p5_ring.asm` are unmodified by this task (confirmed by file timestamp: both untouched since 03:10/03:11, hours before this task's 11:08 start).
- **Process hygiene:** `pgrep -fl x64sc` checked clean before starting; every automated VICE instance launched by the test suites in this task was reaped by the suites' own exact-PID logic; no `pkill` was used in this task; no manual VICE was ever running to disturb.
- **VICE input config:** unchanged — no test in this task alters joystick/keyset preferences; `test_slice_c.py`'s own vicerc-hash check passed in every run.
- **Disk:**

  ```
  du -sh build/   ->  80K
  du -sh .        ->  2.8M
  ```

- All transient timing logs and scratch scripts created in this task and the prior mux task were removed from `/tmp` after use. One unrelated `/tmp/p4_model.bak`, dated two days before this task, was left untouched since its provenance could not be attributed to either task.

---

## Stop condition met

- Report corrected (§1).
- `make test` now runs the deterministic legality-window core in 22s instead of the full 54s, with the production regression suites (unaffected by this task) as the actual majority of its ~10 minute runtime.
- `make test-renderer-full` carries the complete exhaustive/random sweep, unchanged, on demand.
- Both gates pass.

Terrain/background migration is the next task and was not started here.
