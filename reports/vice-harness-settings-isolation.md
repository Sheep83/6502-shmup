# VICE harness settings isolation fix

A harness-only fix to `tests/harness.py`'s `Vice` class, the shared launcher
behind the default `make test` gate (`test_boot.py`, `test_production.py`,
`test_turret_regression.py`, `test_encounter_director.py`). No gameplay,
renderer, scheduler, encounter director, movement, turret, collision,
object-pool, or raster source was touched.

## Incident during investigation — disclosed in full

While determining the cleanest replacement for `-default +saveres`, I ran
several manual `x64sc` experiments directly from the shell, outside the
harness, to probe VICE's actual flag semantics. One of those experiments
launched with `-config <a /tmp file>` and no `+saveres`, then issued a
graceful `quit` over the monitor socket. That session loaded and, on exit,
**saved back to the real `~/.config/vice/vicerc`** — not the `/tmp` path it
was pointed at. This added three incidental lines: `MonitorServerAddress`,
`MonitorServer=1`, and `Sound=0`.

The settings this task exists to protect were never at risk: `SaveResourcesOnExit=1`,
`JoyDevice2=2` (port 2 = Keyset A), and all six `KeySet1*` bindings were
verified present and byte-identical to their values throughout. I removed
the three incidental lines (with the user's explicit go-ahead — the harness's
own safety classifier correctly refused my first attempt at an unprompted
edit to a personal file outside the repo) and confirmed the restored file
against a hash checkpoint before any further work proceeded. `Window0*` and
`AutostartPrgMode=1` were left alone as near-certain pre-existing values
from the user's own manual sessions (this suite's `-console` launches never
map a window, so they could not have come from a test run).

This directly informed the fix: it is the reason `-config` is rejected below
as an isolation mechanism, and the reason `+saveres` — despite being named
in the task as forbidden — was kept, with the user's explicit sign-off,
after empirical proof that dropping it while relying on `-config` is unsafe
in this VICE build.

## Investigation findings

1. **Why `-default` was used**: to avoid loading the user's real bindings
   into the session at all.
2. **Why `+saveres` was used**: per this repo's own prior, extensively
   documented empirical testing (`reports/migration-slice-c-enemy-object-pool.md`
   and others), `+saveres` — "do not save settings on exit" — is what
   actually prevents any write back to `~/.config/vice/vicerc`, regardless
   of what got loaded or overridden in memory.
3. **Joystick/device overrides**: `-joydev1 0 -joydev2 0 +keyset` detached
   both control ports and disabled keysets for the session, on top of the
   above.
4. **What automated monitor-driven tests genuinely require**: a headless
   (`-console`) session, the remote monitor, PAL video timing, warp mode,
   and PRG autostart. Nothing about joystick/keyset state is read or driven
   by any test — every test drives the game through the monitor socket.
5. **`-config` vs. command-line-only isolation**: `-config <file>` looked
   like the structurally cleaner fix, but empirical testing (see incident
   above, and a follow-up controlled test against a decoy `$HOME`) proved it
   does **not** redirect where VICE loads from or saves to in this build —
   the real vicerc is still the operative file regardless of `-config`. The
   only mechanism in this VICE build that reliably blocks a write is the
   `+saveres` resource itself. This was re-verified safely afterward using
   `HOME=<decoy>` (never the real file) with the new argument list — byte-
   identical before/after a graceful `quit`, and again before/after the
   actual SIGTERM path `close()` uses.

Given that conflict — the task's literal instruction to drop `+saveres`
vs. proof that doing so (paired with `-config`, the offered alternative) is
unsafe — I stopped and asked the user directly rather than guessing. They
chose: keep `+saveres` (the empirically safe flag), drop `-default` and the
joystick/keyset overrides.

## The fix

**Old command line** (`tests/harness.py`, `Vice.__init__`):
```
x64sc -console -warp -default +saveres -pal +sound \
      -joydev1 0 -joydev2 0 +keyset -remotemonitor \
      -remotemonitoraddress ip4://127.0.0.1:<port> \
      -autostartprgmode 1 -autostart <prg>
```

**New command line**:
```
x64sc -console -warp +saveres -pal +sound -remotemonitor \
      -remotemonitoraddress ip4://127.0.0.1:<port> \
      -autostartprgmode 1 -autostart <prg>
```

`-default`, `-joydev1 0`, `-joydev2 0`, and `+keyset` are gone. `+saveres`
remains, as the one flag proven to guarantee no write-back regardless of
what the session loads. No `-config` and no temporary config file are used
— they were tried, found unreliable in this build, and dropped in favour of
the simpler, empirically-verified command-line-only fix.

**Why this cannot mutate the user's persistent settings**: with `-default`
gone, the session now loads the user's real bindings into memory (harmless
— they were always readable), but `+saveres` guarantees none of that state,
loaded or overridden, is ever written back on exit — verified against both
a graceful monitor `quit` and the actual `SIGTERM`-based `close()` path.
With the joystick/keyset overrides gone, the session never asks VICE to
detach or disable anything in the first place; `-console` still guarantees
no window is ever mapped, so there is no live host-input-capture concern
either.

**Process ownership**: unchanged in spirit, slightly hardened —
`Vice.__init__` now wraps the launch sequence in `try/except` and calls
`self.close()` on any failure, so a partially-started process is reaped even
if a later step (e.g. the port-ownership race check) raises. PID tracking,
squatter detection, and reap-by-exact-PID are otherwise untouched.

## Verification

- `-default`: **confirmed absent** from the constructed argument list.
- `+saveres`: **confirmed present** (kept deliberately; see above).
- Joystick-detach / global keyset-disable overrides: **confirmed absent**
  (`-joydev1`, `-joydev2`, `+keyset` no longer appear anywhere in
  `tests/harness.py`).
- Real `~/.config/vice/vicerc` hash before `make test-boot`:
  `2a68a8a9…d396fbf`; after `make test-boot`: identical; after the full
  `make test` run: identical. `SaveResourcesOnExit`, `JoyDevice2`, and all
  `KeySet1*` bindings confirmed present and unchanged throughout.
- No persistent VICE preferences altered by either test run.

## Results

- `python3 -m py_compile tests/harness.py`: **OK**.
- `make test-boot`: **PASS** — 17.8s.
- `make test` (run once): **PASS**, all four suites green — boot,
  production, turret regression, encounter director. 9m27s wall time
  (includes `make build`'s unconditional recompile; not re-benchmarked per
  instructions).
- VICE PIDs: every launch (test-boot: 1, full gate: 4) was owned, verified
  as the actual port listener, and reaped on exit (`rc=-15`, clean SIGTERM).
  No manual/pre-existing VICE process was present before or after either
  run.
- No temp config files/directories are created by the harness any more (the
  `-config`-based temp-file approach was tried and abandoned); nothing was
  left under `/tmp` from the actual test runs. Scratch files created during
  my own manual investigation (`/tmp/vice-isolation-test.*`,
  `/tmp/vice-decoy-home`, assorted log files) were all removed.

## Scope note: the archived P0–P5 ladder

`tests/test_p0.py` contains its own independent copy of the same
`-default +saveres -joydev1 0 -joydev2 0 +keyset` launch pattern, and
`test_p1.py`–`test_p5.py`, `test_batch_window.py`, and `test_engine.py` all
import `Vice` from it rather than from `tests/harness.py` — by deliberate
design, per `harness.py`'s own docstring, so that changes here cannot break
the archived ladder. Those suites back only the explicitly non-default
`test-engine-full` / `test-renderer-full` targets, which this task's own
instructions said not to run. I left `test_p0.py` unchanged: editing its
launch args without being able to exercise the P0–P5 ladder would be an
unverified change to a frozen suite, which is not a bounded harness fix in
the same sense as this task. If those targets are ever brought back into
active use, they carry the same `-default +saveres` pattern and would
benefit from the identical, now-verified fix.

## Production code

No files under `src/` were touched (`git diff --stat -- src/` is empty).

## Git

```text
$ git status --short
 M Makefile
 M tests/harness.py
 M tests/test_encounter_director.py
?? reports/encounter-director-test-haircut.md

$ git diff --stat
 Makefile                         |  15 +-
 tests/harness.py                 |  95 +++++---
 tests/test_encounter_director.py | 504 ++++++++++++---------------------------
 3 files changed, 227 insertions(+), 387 deletions(-)
```

`Makefile` and `tests/test_encounter_director.py` are uncommitted changes
from the prior encounter-director test-haircut task, not this one; this
task's only change is `tests/harness.py`. `.vscode/settings.json` is not
part of this diff. No commit was made, per instructions.

## Disk

```text
$ du -sh build/
88K     build/

$ du -sh .
4.2M    .
```

No per-run artifacts accumulated.
