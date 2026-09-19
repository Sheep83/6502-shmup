"""Deterministic conversion of a source artwork tile into the native C64
multicolour terrain representation (16 logical pixels x 32 rows, values 0..3).

This is only a STARTING POINT for the Terrain Asset Workshop - the artist then
edits the native pixels by hand. It never invents colours: it maps each source
pixel to the closest of the FOUR colours the project's terrain palette currently
uses, taken from the one editor C64 colour table (engine_data.C64_PALETTE_RGB).
The result stores LOGICAL indices 0..3 (0 = background, 1 = mc1, 2 = mc2,
3 = character), not RGB and not a specific palette entry.

Horizontal pair-reduction policy (documented, deterministic):
  A 32-wide source row has twice the horizontal resolution of the 16 native
  multicolour pixels. Native pixel x is derived from source columns 2x and 2x+1
  by averaging their RGB, then taking the nearest palette colour. A source tile
  whose width/height is not 32 is first nearest-neighbour resampled to 32x32, so
  the pair-reduction rule always applies to a 32-wide row.
"""
from __future__ import annotations

from engine_data import C64_PALETTE_RGB
from native_metatile import NATIVE_H, NATIVE_W

SOURCE_REF = 32          # the resolution the pair-reduction rule is defined at
LOGICAL_KEYS = ("background", "multicolour1", "multicolour2", "character")


def palette_rgb_for_logical(project_palette):
    """[rgb0, rgb1, rgb2, rgb3] - the RGB the 4 logical terrain indices resolve
    to under this project palette, from the single editor C64 colour table."""
    return [C64_PALETTE_RGB[int(project_palette[k]) & 0x0F] for k in LOGICAL_KEYS]


def nearest_logical_index(rgb, logical_rgb):
    """Nearest of the 4 logical terrain colours to `rgb` (squared RGB distance).
    Deterministic: ties resolve to the lower logical index (0 before 3)."""
    r, g, b = rgb
    best_i, best_d = 0, None
    for i, (pr, pg, pb) in enumerate(logical_rgb):
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if best_d is None or d < best_d:
            best_i, best_d = i, d
    return best_i


def _get_px(rgb_rows, x, y):
    return rgb_rows[y][x]


def _resample_to_ref(rgb_rows):
    """Nearest-neighbour resample an arbitrary HxW grid of (r,g,b) rows to
    SOURCE_REF x SOURCE_REF. A no-op when already 32x32."""
    h = len(rgb_rows)
    w = len(rgb_rows[0]) if h else 0
    if h == SOURCE_REF and w == SOURCE_REF:
        return [list(row) for row in rgb_rows]
    if h == 0 or w == 0:
        raise ValueError("source tile is empty")
    out = []
    for ry in range(SOURCE_REF):
        sy = min(h - 1, ry * h // SOURCE_REF)
        row = []
        for rx in range(SOURCE_REF):
            sx = min(w - 1, rx * w // SOURCE_REF)
            row.append(tuple(rgb_rows[sy][sx]))
        out.append(row)
    return out


def source_tile_to_native(rgb_rows, project_palette):
    """rgb_rows: list of H rows, each a list of W (r,g,b) tuples (0..255).
    Returns a NATIVE_H x NATIVE_W grid of logical indices 0..3.

    32 source columns -> 16 native multicolour pixels (documented pair average);
    32 source rows    -> 32 native rows (1:1)."""
    ref = _resample_to_ref(rgb_rows)
    logical_rgb = palette_rgb_for_logical(project_palette)
    grid = []
    for y in range(NATIVE_H):                       # NATIVE_H == SOURCE_REF == 32
        out_row = []
        for x in range(NATIVE_W):                   # NATIVE_W == 16
            (r0, g0, b0) = ref[y][2 * x]
            (r1, g1, b1) = ref[y][2 * x + 1]
            avg = ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2)
            out_row.append(nearest_logical_index(avg, logical_rgb))
        grid.append(out_row)
    return grid
