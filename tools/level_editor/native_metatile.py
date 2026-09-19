"""Native C64 multicolour representation of a terrain metatile, plus the
decomposition / deduplication that turns it into packed character glyphs.

A metatile is 4x4 characters. In VIC-II multicolour text mode a character is
4 logical pixels wide x 8 rows, each pixel a 2-bit value:

    0 -> $D021 background      1 -> $D022 (mc1)
    2 -> $D023 (mc2)           3 -> colour RAM (character colour)

So a whole metatile is:

    NATIVE_W = 16 logical multicolour pixels across   (4 chars x 4)
    NATIVE_H = 32 rows                                  (4 chars x 8)

Every pixel is a LOGICAL palette index 0..3 - never an RGB value and never a
specific level palette entry. The same native asset renders under any compatible
4-colour terrain palette later; logical 2 always means "level multicolour 2".

Char (cr, cc), cr/cc in 0..3, covers native rows cr*8..cr*8+7 and native
columns cc*4..cc*4+3. Its 8 bytes encode each row's 4 pixels left-to-right as
    byte = (p0 << 6) | (p1 << 4) | (p2 << 2) | p3
which is exactly what src/main.asm's decodeStageCharacterRow / the VIC expect.
"""
from __future__ import annotations

from engine_data import TERRAIN_GLYPH_BASE, TERRAIN_GLYPH_NAMESPACE

NATIVE_W = 16
NATIVE_H = 32
CHARS_PER_SIDE = 4
CHAR_W = 4          # logical multicolour pixels
CHAR_H = 8          # rows
GLYPH_BYTES = 8
CELLS_PER_METATILE = CHARS_PER_SIDE * CHARS_PER_SIDE   # 16


class NativeMetatileError(ValueError):
    """Raised for a malformed native metatile grid."""


def blank_pixels(value=0):
    """A fresh NATIVE_H x NATIVE_W grid of logical index `value`."""
    if value not in (0, 1, 2, 3):
        raise NativeMetatileError(f"fill value must be 0..3; got {value!r}")
    return [[value] * NATIVE_W for _ in range(NATIVE_H)]


def validate_pixels(pixels):
    """Check a native pixel grid: exactly 32 rows x 16 cols, every value 0..3.
    Accepts either a 32-list of 16-int rows OR a 32-list of 16-char "0".."3"
    strings (the compact on-disk form). Always returns 32 lists of 16 ints."""
    if not isinstance(pixels, (list, tuple)) or len(pixels) != NATIVE_H:
        raise NativeMetatileError(
            f"native metatile must have exactly {NATIVE_H} rows; got "
            f"{len(pixels) if isinstance(pixels, (list, tuple)) else type(pixels).__name__}"
        )
    grid = []
    for y, row in enumerate(pixels):
        if isinstance(row, str):
            if len(row) != NATIVE_W or any(ch not in "0123" for ch in row):
                raise NativeMetatileError(
                    f"native metatile row {y} must be {NATIVE_W} of '0'..'3'; got {row!r}"
                )
            grid.append([int(ch) for ch in row])
            continue
        if not isinstance(row, (list, tuple)) or len(row) != NATIVE_W:
            raise NativeMetatileError(
                f"native metatile row {y} must have exactly {NATIVE_W} pixels; "
                f"got {len(row) if isinstance(row, (list, tuple)) else type(row).__name__}"
            )
        out_row = []
        for x, value in enumerate(row):
            if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1, 2, 3):
                raise NativeMetatileError(
                    f"native metatile pixel ({y},{x}) = {value!r}; logical indices are 0..3 only"
                )
            out_row.append(int(value))
        grid.append(out_row)
    return grid


def pixels_to_rowstrings(pixels):
    """32 x 16 int grid -> 32 compact "0".."3" row strings (the on-disk form)."""
    return ["".join(str(v) for v in row) for row in validate_pixels(pixels)]


def pixels_to_glyphs(pixels):
    """Decompose a validated native grid into 16 character glyphs, each an
    8-tuple of bytes, in reading order: (cr=0,cc=0),(0,1),(0,2),(0,3),(1,0)...

    This is the exact bit packing the engine consumes, so a metatile definition
    is simply the 16 glyph codes for these 16 cells."""
    grid = validate_pixels(pixels)
    glyphs = []
    for cr in range(CHARS_PER_SIDE):
        for cc in range(CHARS_PER_SIDE):
            glyph = []
            for y in range(CHAR_H):
                row = grid[cr * CHAR_H + y]
                x0 = cc * CHAR_W
                p0, p1, p2, p3 = row[x0:x0 + CHAR_W]
                glyph.append((p0 << 6) | (p1 << 4) | (p2 << 2) | p3)
            glyphs.append(tuple(glyph))
    return glyphs


def glyph_to_cell_pixels(glyph):
    """One 8-byte glyph -> an 8x4 list-of-rows of logical indices 0..3."""
    if len(glyph) != GLYPH_BYTES:
        raise NativeMetatileError(f"glyph must be {GLYPH_BYTES} bytes; got {len(glyph)}")
    cell = []
    for byte in glyph:
        byte &= 0xFF
        cell.append([(byte >> 6) & 3, (byte >> 4) & 3, (byte >> 2) & 3, byte & 3])
    return cell


def glyphs_to_pixels(glyphs):
    """Recompose 16 character glyphs (reading order) back into a NATIVE_H x
    NATIVE_W logical grid. Inverse of pixels_to_glyphs; used to migrate an
    existing packed tileset into the native editor representation."""
    if len(glyphs) != CELLS_PER_METATILE:
        raise NativeMetatileError(
            f"a metatile needs exactly {CELLS_PER_METATILE} glyphs; got {len(glyphs)}"
        )
    grid = blank_pixels(0)
    for cell_index, glyph in enumerate(glyphs):
        cr, cc = divmod(cell_index, CHARS_PER_SIDE)
        cell = glyph_to_cell_pixels(glyph)
        for y in range(CHAR_H):
            for x in range(CHAR_W):
                grid[cr * CHAR_H + y][cc * CHAR_W + x] = cell[y][x]
    return grid


# --------------------------------------------------------------------------
# Deduplication: "metatiles are cheap; unique live character glyphs are
# precious." A level owns an ordered list of unique 8-byte glyph bitmaps
# (<= TERRAIN_GLYPH_NAMESPACE). Adding a metatile reuses any bitmap already in
# the set and only allocates the genuinely new ones.
# --------------------------------------------------------------------------

class GlyphBudgetExceeded(ValueError):
    """Adding an asset would need more unique terrain glyphs than the live
    namespace (codes 96..223, 128 slots) can hold."""

    def __init__(self, needed, capacity, existing):
        self.needed = needed
        self.capacity = capacity
        self.existing = existing
        super().__init__(
            f"asset needs {needed} unique terrain glyphs but only "
            f"{capacity - existing} of {capacity} are free "
            f"({existing} already used)"
        )


def _as_tuple(glyph):
    return tuple(int(b) & 0xFF for b in glyph)


class GlyphSet:
    """An ordered, de-duplicated collection of 8-byte terrain glyph bitmaps.
    Index i == char code TERRAIN_GLYPH_BASE + i once compiled into a level."""

    def __init__(self, glyphs=None, capacity=TERRAIN_GLYPH_NAMESPACE):
        self.capacity = capacity
        self._list = []
        self._index = {}
        for g in (glyphs or []):
            self._append(_as_tuple(g))

    def _append(self, key):
        self._index[key] = len(self._list)
        self._list.append(key)

    def __len__(self):
        return len(self._list)

    def __iter__(self):
        return iter(self._list)

    def glyphs(self):
        return [list(g) for g in self._list]

    def index_of(self, glyph):
        return self._index.get(_as_tuple(glyph))

    def cost(self, glyphs):
        """Without mutating: (reused, new_unique) for a candidate glyph list."""
        seen_new = set()
        reused = 0
        for g in glyphs:
            key = _as_tuple(g)
            if key in self._index:
                reused += 1
            else:
                seen_new.add(key)
        return reused, len(seen_new)

    def add_glyphs(self, glyphs, *, dry_run=False):
        """Fold a list of glyph bitmaps into the set, deduplicating. Returns the
        list of assigned indices (parallel to `glyphs`). Raises
        GlyphBudgetExceeded if the new unique bitmaps would overflow capacity."""
        keys = [_as_tuple(g) for g in glyphs]
        new_unique = []
        for key in keys:
            if key not in self._index and key not in new_unique:
                new_unique.append(key)
        if len(self._list) + len(new_unique) > self.capacity:
            raise GlyphBudgetExceeded(len(new_unique), self.capacity, len(self._list))
        if dry_run:
            projected = dict(self._index)
            nxt = len(self._list)
            for key in new_unique:
                projected[key] = nxt
                nxt += 1
            return [projected[k] for k in keys]
        for key in new_unique:
            self._append(key)
        return [self._index[k] for k in keys]


def pack_metatiles(native_grids, *, capacity=TERRAIN_GLYPH_NAMESPACE, glyph_base=TERRAIN_GLYPH_BASE):
    """Turn an ordered list of native pixel grids (one per level metatile) into
    a packed tileset:

        {"glyphCount": N, "glyphs": [[8]...N], "metatileDefs": [[16 codes]...]}

    Deterministic: glyph order is first-seen across the metatiles in the order
    given, char cells scanned in reading order. Raises GlyphBudgetExceeded if
    the level's metatiles need more than `capacity` unique glyphs."""
    gs = GlyphSet(capacity=capacity)
    defs = []
    for grid in native_grids:
        glyphs = pixels_to_glyphs(grid)
        indices = gs.add_glyphs(glyphs)
        defs.append([glyph_base + i for i in indices])
    return {"glyphCount": len(gs), "glyphs": gs.glyphs(), "metatileDefs": defs}
