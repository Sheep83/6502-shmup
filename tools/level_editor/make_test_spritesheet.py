#!/usr/bin/env python3
"""Generate a deterministic synthetic source spritesheet for automated tests.

DithArt's pack is used for HUMAN acceptance only and is never committed. The
automated importer / conversion / slicing tests need a checked-in fixture, so
this writes a plain PNG grid of recognisable 32x32 "terrain" tiles built from a
handful of flat/striped/checker patterns in a fixed 4-colour ramp.

    python3 tools/level_editor/make_test_spritesheet.py [out.png] [cols] [rows] [tile]

Default: tools/level_editor/testdata/synthetic_tileset.png, 12 x 10 tiles of
32x32 (120 tiles, matching the DithArt sheet's tile count for browser perf).
"""
import sys
from pathlib import Path

# A fixed dusty ramp - four distinct RGBs so nearest-colour conversion is
# unambiguous under any sensible 4-colour project palette.
RAMP = [(16, 16, 24), (150, 96, 40), (210, 190, 150), (250, 250, 250)]


def _tile_pattern(index, tile):
    """A tile as tile x tile list of (r,g,b), pattern chosen by index."""
    kind = index % 6
    a = RAMP[index % 4]
    b = RAMP[(index + 1) % 4]                       # always != a
    px = [[a] * tile for _ in range(tile)]
    if kind == 0:                                   # flat
        pass
    elif kind == 1:                                 # horizontal stripes
        for y in range(tile):
            if (y // 4) % 2:
                px[y] = [b] * tile
    elif kind == 2:                                 # vertical stripes
        for y in range(tile):
            for x in range(tile):
                if (x // 4) % 2:
                    px[y][x] = b
    elif kind == 3:                                 # checker
        for y in range(tile):
            for x in range(tile):
                if ((x // 4) + (y // 4)) % 2:
                    px[y][x] = b
    elif kind == 4:                                 # diagonal ridge
        for y in range(tile):
            for x in range(tile):
                if abs(x - y) < 5:
                    px[y][x] = b
    else:                                           # framed / crater-ish
        for y in range(tile):
            for x in range(tile):
                if x < 3 or y < 3 or x >= tile - 3 or y >= tile - 3:
                    px[y][x] = b
                elif (x - tile // 2) ** 2 + (y - tile // 2) ** 2 < 40:
                    px[y][x] = RAMP[3]
    return px


def build(out_path, cols, rows, tile):
    from PIL import Image

    im = Image.new("RGB", (cols * tile, rows * tile))
    px = im.load()
    for r in range(rows):
        for c in range(cols):
            pattern = _tile_pattern(r * cols + c, tile)
            for y in range(tile):
                for x in range(tile):
                    px[c * tile + x, r * tile + y] = pattern[y][x]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return out_path


def main():
    args = sys.argv[1:]
    out = Path(args[0]) if args else Path(__file__).resolve().parent / "testdata" / "synthetic_tileset.png"
    cols = int(args[1]) if len(args) > 1 else 12
    rows = int(args[2]) if len(args) > 2 else 10
    tile = int(args[3]) if len(args) > 3 else 32
    path = build(out, cols, rows, tile)
    print(f"wrote {path} ({cols}x{rows} tiles of {tile}x{tile} = {cols * rows} tiles, "
          f"{cols * tile}x{rows * tile}px)")


if __name__ == "__main__":
    main()
