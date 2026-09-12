# AGENTS.md — 6502-shmup

A PAL C64 shoot-'em-up, built on the engine qualified in the sibling
`6502-engine` repository. Read this before changing anything.

**The priority here is production game behaviour.** The engine is qualified;
this repo exists to build a game on it, not to maximise synthetic fixture
complexity. Fixtures are a safety net, not the product.

## Target and toolchain
- Commodore 64, **PAL**, 19,656 cycles/frame. Never optimise for NTSC.
- **Legal NMOS 6502/6510 only.** No illegal opcodes.
- KickAssembler 5.25 (`/Users/brianmorrice/dev/tools/kickassembler/KickAss.jar`).
- VICE 3.10, `x64sc` (`/opt/homebrew/bin/x64sc`).

## The rules that matter most

**1. Game code obeys `docs/ENGINE_CONTRACT.md`.**
Logical sprite state in, rendering out. No game system writes gameplay sprite
VIC registers, chooses hardware slots, touches a published CURRENT schedule, or
writes the pointer table of a page that is not the adopted one. If a new
subsystem needs VIC state, it participates the way `src/hud.asm` does: it owns
its data and the renderer owns the registers.

**2. Manual visual output is authoritative.**
A change is not done because counters pass. Automated tests are *evidence*,
never a veto over what a human can see. If a human sees corruption and the
harness does not, the **harness** is wrong. Long, normal-speed, **non-warp**
observation is part of acceptance.

**3. Timing is measured, not assumed.**
No architectural change — raster lines, phase order, admission rules, the
aperture, the HUD handoff — without a measurement that justifies it, recorded
next to the constant it justifies. `REUSE_LEAD` began as a guess of 3 lines and
measurement rejected it. `HUD_Y` moved from 18 to 16 because a capture showed a
sprite occupies rasters n+1..n+21. Numbers like these belong to measurement.

**4. A green instrument can be wrong.**
This project has been bitten repeatedly: a 16-bit histogram that wrapped, a
saturating counter read as a rate, a nine-bit raster compared as eight bits, a
monitor dump validated on its first row only. When a test disagrees with the
machine, find out which one is lying before changing either.

## Avoid abstraction
Prefer a small readable module with documented limits over a general one with
fragile ownership. If a change starts to look like a miniature re-creation of an
old engine's adaptive-reuse machinery, stop and simplify.

## Tests
- `make test` — the engine invariant probe. Run it constantly; it is about a
  minute and it guards the phase schedule, the aperture, sprite ownership,
  page/pointer coherence and the HUD write window.
- `make test-fast` — the above plus the ring model and a short ring walk.
- `make test-engine-full` — the inherited qualification ladder. Slow. Run it
  when the renderer, scroller or aperture has been touched, not routinely.

Do not weaken a correctness check to make a change pass.

## VICE process ownership (hard invariant)
Before a suite: `pgrep -fl x64sc` and account for anything running.
Every launch must retain its **exact PID** and terminate + reap it on success,
failure, timeout and exception (`try/finally` or `trap`). Verify at the end that
no test-owned VICE remains. Do **not** use broad `pkill` when the PID is known,
and never kill a user's manual VICE session. **Never steal keyboard focus**:
automated runs use `-console`, launch directly, never `open -a`.

Two harness traps already paid for:
- any monitor command **halts** the emulator, so a harness cannot observe a
  freely-running non-warp machine — advance emulated time by stepping;
- never hijack the CPU (`r pc=...`) while stopped **inside the IRQ handler**:
  the I flag stays set, interrupts never resume, and the failure looks like a
  renderer bug.

## Build/test hygiene
`build/` holds only the current binary and symbols. **No per-run directories,
ever.** All screenshots, traces and captures go to `/tmp` and are deleted after
use; a harness cleans up its own run-specific output. Report disk usage after
large runs.

## Reports
Substantial investigations go in `/reports` as a dated markdown file **and** are
printed normally in the reply. Historical engine qualification reports are not
here — they remain in `../6502-engine/reports`.

## Source control
**Do not commit or push unless explicitly asked.** Initialising a repo and
configuring a remote is fine; committing is not. Use **SSH** for GitHub remotes.
