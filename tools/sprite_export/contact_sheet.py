#!/usr/bin/env python3
"""Diagnostic: render the sprites twice and prove the two renders identical.

    python3 tools/sprite_export/contact_sheet.py <out.png>

Once from the bytes the BUILT PROGRAM carries and once from the bytes parsed
out of the authoritative .spd, then compares the two rasters pixel by pixel. It is
a sanity check on top of the byte comparison in verify_sprites.py, not a substitute
for it -- if the payloads match, the renders must; this exists to make that
visible to a human as well as to a diff.

Nothing here is allowed to touch the artwork. The renderer expands the C64's
own encoding and does not scale, mirror, crop or recolour anything.

Pillow is optional and is only needed by this file; the exporter and its tests
are standard library only.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sprite_source as src                                   # noqa: E402
import spd_reader                                             # noqa: E402
from verify_sprites import SPD as OUT_SPD                     # noqa: E402
BACKGROUND = src.BACKGROUND

# VICE's own rendering of the C64 palette, sampled from an x64sc capture.
PALETTE = [
    (0, 0, 0), (255, 255, 255), (129, 51, 56), (112, 190, 192),
    (127, 57, 149), (98, 213, 50), (67, 57, 197), (255, 255, 70),
    (133, 76, 20), (83, 57, 0), (180, 101, 105), (74, 74, 74),
    (120, 120, 120), (183, 255, 134), (115, 133, 255), (205, 205, 205),
]

CELL_W, CELL_H = 24, 21         # a C64 sprite, in C64 pixels


def raster(bitmap, multicolour, colour):
    """63 bytes -> a 24x21 grid of RGB, exactly as the VIC would resolve it."""
    pens = (PALETTE[BACKGROUND], PALETTE[src.SPR_MC_DARK],
            PALETTE[colour], PALETTE[src.SPR_MC_LIGHT])
    rows = []
    for r in range(21):
        row = []
        for b in bitmap[r * 3:(r + 1) * 3]:
            if multicolour:
                # four double-width pixels per byte, high pair first
                for shift in (6, 4, 2, 0):
                    row += [pens[(b >> shift) & 3]] * 2
            else:
                for shift in range(7, -1, -1):
                    row.append(PALETTE[colour] if (b >> shift) & 1
                               else PALETTE[BACKGROUND])
        rows.append(row)
    return rows


def sheet(entries, per_row=8, zoom=3, gap=4):
    from PIL import Image
    rows = (len(entries) + per_row - 1) // per_row
    w = per_row * (CELL_W * zoom + gap) + gap
    h = rows * (CELL_H * zoom + gap) + gap
    img = Image.new("RGB", (w, h), (24, 24, 24))
    px = img.load()
    for i, grid in enumerate(entries):
        cy, cx = divmod(i, per_row)
        ox = gap + cx * (CELL_W * zoom + gap)
        oy = gap + cy * (CELL_H * zoom + gap)
        for y, line in enumerate(grid):
            for x, rgb in enumerate(line):
                for dy in range(zoom):
                    for dx in range(zoom):
                        px[ox + x * zoom + dx, oy + y * zoom + dy] = rgb
    return img


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: contact_sheet.py <out.png>")
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise SystemExit("Pillow is not installed; this diagnostic is optional")

    sprites = src.extract()
    from_engine = [raster(s.bitmap, s.multicolour, s.colour) for s in sprites]

    if not OUT_SPD.is_file():
        raise SystemExit(f"{OUT_SPD} does not exist")
    parsed = spd_reader.read(OUT_SPD)
    # PAIRED BY SLOT, NOT BY POSITION. The extractor walks the program in
    # address order and the .spd is in its own authored order; they also differ
    # in length, because the player's blank block is emitted by src/player.asm
    # rather than imported and the .spd carries an unused trailing slot.
    from verify_sprites import slot_for
    pos, from_spd = {}, []
    for s in sprites:
        i = pos.get(s.group, 0)
        pos[s.group] = i + 1
        t = parsed.sprites[slot_for(s, i)]
        from_spd.append(raster(t.bitmap, s.multicolour, s.colour))
    pixels = 0
    bad = 0
    for a, b in zip(from_engine, from_spd):
        for ra, rb in zip(a, b):
            for pa, pb in zip(ra, rb):
                pixels += 1
                if pa != pb:
                    bad += 1
    print(f"  rendered {len(from_engine)} sprites twice")
    print(f"  pixels compared  {pixels}")
    print(f"  differing pixels {bad}")
    if bad:
        return 1
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet(from_spd).save(out)
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
