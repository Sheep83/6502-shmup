# 6502-shmup

A PAL C64 shoot-'em-up, built on the engine qualified in the sibling
[`6502-engine`](../6502-engine) repository.

The engine baseline is production-ready and boots to a live demonstration of it:
a smooth-scrolling playfield clipped to a fixed pixel-exact aperture, a
six-sprite multiplexer, and a live top-border HUD showing lives, a heat gauge, a
score and a status indicator.

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

In the running program: **SPACE** cycles the sprite fixtures, **M** / **S** /
**R** jump to the first P3 / P4 / P5 fixture. The HUD runs live on all of them.

## Test

```sh
make test               # the engine invariant probe -- run this constantly, ~1 min
make test-fast          # + ring model agreement and a short ring walk
make test-engine-full   # the inherited qualification ladder. Slow.
```

`make test` reads the engine's own instrumentation counters — the frame
transaction's raster, the HUD and handoff entry rasters, both aperture splits,
page/pointer coherence, the HUD bitmap-write window and the admitted sprite Y
range — across five fixtures.

## Where things are

```
src/                 the engine and the HUD
docs/ENGINE_CONTRACT.md   the rules game code must obey -- read this first
tests/test_engine.py the compact invariant probe
tests/test_p0..p5    the inherited qualification ladder
tools/               generators for the fixture and ring tables
reports/             development reports from here onward
```

**Start with [`docs/ENGINE_CONTRACT.md`](docs/ENGINE_CONTRACT.md).** It records
the raster phase schedule, sprite slot ownership, admission bounds, HUD handoff,
page/pointer rules and the known deferred performance issue, with the actual
constants from `src/`.

Historical qualification — the aperture forensics, the architecture reviews and
the four implementation slices — remains in `../6502-engine/reports`.
