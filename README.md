# 6502-shmup

A PAL C64 shoot-'em-up, built on the engine qualified in the sibling
[`6502-engine`](../6502-engine) repository.

It boots into the **game**: a joystick-controlled player ship on the two
reserved hardware sprites, over a playfield that scrolls **downward** past them
-- the original game's forward-play direction -- clipped to a fixed pixel-exact
aperture, under a live top-border HUD showing lives, a heat gauge, a score and a
status indicator. The six-sprite gameplay multiplexer is idle --
there are no enemies yet — and the HUD's four values are still on their
demonstration cadences.

**Target:** Commodore 64, PAL, KickAssembler 5.25, VICE 3.10 `x64sc`,
legal NMOS 6502/6510 only.

## Build

```sh
make build          # -> build/shmup.prg
make d64            # -> build/shmup.d64
```

## Run

```sh
make run            # windowed x64sc, normal speed, no warp
```

Launch **only** through `make run` or the VS Code task. The options in
`VICE_OPTS` are not cosmetic: without `-default` a saved `vicerc` applies, and a
joystick keyset can bind the host SPACE key to an emulated joystick — VICE then
eats the key and the C64 keyboard matrix never sees it, so fixture selection is
silently dead and nothing on screen explains why.

Control port 2 is the player's stick. `JOY2` selects which host device drives
it — `1` is the numpad and is the default, `4` is the first real joystick or
gamepad:

```sh
make run JOY2=4     # a MacBook keyboard has no numpad
```

The qualification fixtures are no longer on the startup path and their keyboard
selection is compiled out (`FIXTURE_KEYS` in `src/main.asm`), because the scan
writes the same CIA register the stick is read from. They are still assembled,
still reachable, and still what `make test` measures — it selects them through
the monitor, which needs no keyboard. Set `FIXTURE_KEYS = true` for a debug
build and **SPACE** / **M** / **S** / **R** work exactly as they did.

## Test

```sh
make test               # the two probes to run constantly, ~2 min
make test-slice-a       # just the game path: production boot, player, composition
make test-fast          # + ring model agreement and a short ring walk
make test-engine-full   # the inherited qualification ladder. Slow.
```

`make test` is two probes. `tests/test_engine.py` reads the engine's own
instrumentation counters — the frame transaction's raster, the HUD and handoff
entry rasters, both aperture splits, page/pointer coherence, the HUD
bitmap-write window and the admitted sprite Y range — across the production boot
and four fixtures. `tests/test_slice_a.py` guards the game's own path: that a
production boot presents no fixture, that what the VIC displays for the player
always came from the *adopted* block rather than from live state, and that the
player's two bits and the multiplexer's six share `$d015` and `$d010` without
either erasing the other.

## Where things are

```
src/                 the engine, the HUD and the game
src/player.asm       the player: logical state, input, presentation block
docs/ENGINE_CONTRACT.md   the rules game code must obey -- read this first
tests/test_engine.py the compact invariant probe
tests/test_slice_a.py the game path: boot, player, register composition
tests/test_p0..p5    the inherited qualification ladder
tools/               generators for the fixture and ring tables
reports/             development reports from here onward
```

Game code lives **outside VIC bank 0**, at `$4000` and above. Bank 0's 16 KB is
contended by two screen pages, the sprite bitmaps, the HUD's and the player's
bitmap pools, the blank charset and eventually a real character set; main-thread
code is never fetched by the VIC and has no business competing for it.

**Start with [`docs/ENGINE_CONTRACT.md`](docs/ENGINE_CONTRACT.md).** It records
the raster phase schedule, sprite slot ownership, admission bounds, HUD handoff,
page/pointer rules, the world/stage progression contract and the known deferred
performance issue, with the actual constants from `src/`.

Historical qualification — the aperture forensics, the architecture reviews and
the four implementation slices — remains in `../6502-engine/reports`.
