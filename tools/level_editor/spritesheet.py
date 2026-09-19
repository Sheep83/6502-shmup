"""Source-spritesheet importer core (no GUI).

Slices a PNG (or any Pillow-readable image) into a grid of fixed-size source
tiles. The tile size is configurable and defaults to 32x32 - the size the
Terrain Asset Workshop's conversion rule is defined at and the size the DithArt
acceptance sheet uses. Basic PNG-grid slicing works standalone; optional Tiled
`.tsx` metadata detection is a convenience layered on top by the caller.

Incomplete edge cells are never silently cropped into short tiles: only whole
`tile_w x tile_h` cells become tiles, and any leftover strip on the right/bottom
is reported in `warnings`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TILE = 32
MAX_TILES = 4096          # a sane ceiling so a mis-set tile size cannot explode


def load_rgb_rows(path):
    """Read an image file -> (width, height, rows) where rows[y][x] = (r,g,b).
    Requires Pillow (import is local so the module loads without it)."""
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        px = im.load()
        rows = [[tuple(px[x, y]) for x in range(w)] for y in range(h)]
    return w, h, rows


@dataclass
class SpriteSheet:
    path: Path
    tile_w: int
    tile_h: int
    width: int
    height: int
    rows: list                       # full-image rgb rows
    cols_count: int                  # whole tiles across
    rows_count: int                  # whole tiles down
    warnings: list = field(default_factory=list)

    @property
    def tile_count(self):
        return self.cols_count * self.rows_count

    def tile_rc(self, col, row):
        """rgb rows for the tile at grid (col, row), size tile_h x tile_w."""
        if not (0 <= col < self.cols_count and 0 <= row < self.rows_count):
            raise IndexError(f"tile ({col},{row}) out of range "
                             f"{self.cols_count}x{self.rows_count}")
        x0, y0 = col * self.tile_w, row * self.tile_h
        return [
            [self.rows[y0 + dy][x0 + dx] for dx in range(self.tile_w)]
            for dy in range(self.tile_h)
        ]

    def tile(self, index):
        """rgb rows for the tile at flat reading-order `index`."""
        if not 0 <= index < self.tile_count:
            raise IndexError(f"tile index {index} out of range 0..{self.tile_count - 1}")
        return self.tile_rc(index % self.cols_count, index // self.cols_count)

    def tile_coords(self, index):
        """(col, row) grid coordinates for a flat index - for provenance."""
        return index % self.cols_count, index // self.cols_count


def slice_sheet(path, tile_w=DEFAULT_TILE, tile_h=DEFAULT_TILE):
    """Load `path` and slice it into a grid of tile_w x tile_h tiles."""
    tile_w, tile_h = int(tile_w), int(tile_h)
    if tile_w < 1 or tile_h < 1:
        raise ValueError(f"tile size must be >= 1x1; got {tile_w}x{tile_h}")
    path = Path(path)
    w, h, rows = load_rgb_rows(path)
    cols_count, rem_x = divmod(w, tile_w)
    rows_count, rem_y = divmod(h, tile_h)
    warnings = []
    if rem_x:
        warnings.append(
            f"image width {w} is not a multiple of tile width {tile_w}; "
            f"the rightmost {rem_x}px column is not covered by any tile"
        )
    if rem_y:
        warnings.append(
            f"image height {h} is not a multiple of tile height {tile_h}; "
            f"the bottom {rem_y}px strip is not covered by any tile"
        )
    if cols_count < 1 or rows_count < 1:
        raise ValueError(
            f"image {w}x{h} is smaller than one {tile_w}x{tile_h} tile"
        )
    if cols_count * rows_count > MAX_TILES:
        raise ValueError(
            f"{cols_count * rows_count} tiles exceeds the {MAX_TILES} ceiling - "
            f"is the tile size ({tile_w}x{tile_h}) right?"
        )
    return SpriteSheet(
        path=path, tile_w=tile_w, tile_h=tile_h, width=w, height=h, rows=rows,
        cols_count=cols_count, rows_count=rows_count, warnings=warnings,
    )
