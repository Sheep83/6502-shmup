#!/usr/bin/env python3
"""Convert the blue player craft out of the supplied sprite sheet into C64
multicolour sprite bitmaps, and emit them as KickAssembler source.

    python3 tools/gen_player_ship.py            # rewrite src/player_art.asm
    python3 tools/gen_player_ship.py --check    # verify it is up to date

WHY A TOOL AND NOT HAND-TRANSCRIPTION. Fifteen 63-byte bitmaps is 945 bytes of
bit-pair packing, six of them horizontal mirrors of others. Doing that by eye
is how a single wrong pair value ends up in production looking like a
rendering bug.

THE BUILD DOES NOT RUN THIS. It writes a checked-in .asm file; the assembler
reads that file and nothing else, so the game has no Python dependency and the
emitted bytes are whatever was reviewed. `--check` is how a human or CI
confirms the checked-in file still matches the PNG.

--- what the artwork is, established from the pixels ------------------------
The craft is the BLUE INTERCEPTOR at x39..76, rows 0..49 of the sheet: a clean
3x3 grid of 12x16 cells.

  * THREE COLOURS PLUS TRANSPARENT -- black outline, medium blue body, white
    highlight. Twelve pixels wide with three colours is exactly one C64
    MULTICOLOUR sprite (12 double-width pixels = 24 screen px; pairs 01/10/11
    plus transparent 00). Multicolour is the artwork's native mode and ONE
    sprite is its native composition.
  * ROWS ARE BANKING. Band A (rows 0..15) is mirror-symmetric to the pixel and
    is the neutral frame; bands B and C lean progressively, and they lean LEFT
    -- in both, the right wingtip rides high while the left drops, which is a
    left roll. The sheet draws one direction, so the right-hand frames are
    horizontal mirrors.
  * COLUMNS ARE THE ENGINE. The three cells of a band differ ONLY in their
    bottom two rows: the exhaust flame full, small, then out. That is an
    animation to be cycled, not three more bank stages.

  => 5 bank states x 3 engine frames = 15 blocks.

THE PALETTE MUST BE READ BY INDEX. The sheet has TWO black entries: index 0,
an opaque black the art uses for its outlines, and index 255, the transparency
key, which is also (0,0,0). Opening the file with .convert("RGB") merges them
and silently turns every outline pixel into background -- which is exactly the
mistake an earlier pass made, producing a hollow ship from a different part of
the sheet entirely.
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "src/mnt/data/Shooter_SpriteSheet_C64(1).png"
OUT = ROOT / "src/player_art.asm"

# --- the source cells ------------------------------------------------------
# THE BLUE INTERCEPTOR, x39..76 of the sheet: a 3x3 grid of 12x16 cells on a
# clean uniform pitch, unlike the rest of the sheet.
#
#   rows          = BANKING state   (A symmetric = neutral, B and C lean left)
#   columns       = ENGINE ANIMATION (the flame shrinking: full, small, out)
#
# Every cell is exactly 12 px wide, so the artist's own registration inside
# that box is used as-is. No centroid alignment is needed or wanted here --
# guessing at placement would only move frames the sheet already lines up.
BANDS = {"neutral": (0, 15), "bankL1": (17, 32), "bankL2": (34, 49)}
ANIM_X = [(39, 50), (52, 63), (65, 76)]
CELL_W, CELL_H = 12, 16
ANIM_FRAMES = 3

# --- colour -> multicolour bit pair -----------------------------------------
# 00 transparent, 01 = $d025 (shared), 10 = $d027+n (per sprite), 11 = $d026.
#
# The DARK blue is the per-sprite pair, for two reasons: it is the ship's
# outline and therefore its identity, and src/player.asm already turns the
# per-sprite colour red for the muzzle-flash frames, which now flashes the
# outline rather than a separate bitmap.
# INDICES, NOT RGB. The sheet's palette has TWO black entries -- index 0, an
# opaque black the art uses for outlines, and index 255, the transparency key,
# which is also (0,0,0). Reading the file as RGB merges them and silently turns
# every outline pixel into background; this craft is drawn with a black outline
# throughout, so that mistake is the difference between the real artwork and a
# hollow one.
TRANSPARENT = 255
IDX_BLACK   = 0             # -> pair 01, $d025, C64 black      (0)  outline
IDX_BLUE    = 4             # -> pair 10, $d027, C64 light blue (14) body
IDX_WHITE   = 12            # -> pair 11, $d026, C64 white      (1)  highlight
PAIR = {TRANSPARENT: 0, IDX_BLACK: 1, IDX_BLUE: 2, IDX_WHITE: 3}

SPRITE_W_MC = 12            # multicolour pixels across a 24-px sprite
SPRITE_H    = 21


def load_cells():
    """{band: [anim0, anim1, anim2]} of 16x12 pair grids, read by INDEX."""
    from PIL import Image
    im = Image.open(SHEET)                  # mode P: no convert, see PAIR above
    if im.mode != "P":
        raise SystemExit("the sheet is expected to be a palette image")
    px = im.load()
    out = {}
    for band, (y0, y1) in BANDS.items():
        if y1 - y0 + 1 != CELL_H:
            raise SystemExit(f"band {band} is not {CELL_H} rows tall")
        frames = []
        for (x0, x1) in ANIM_X:
            if x1 - x0 + 1 != CELL_W:
                raise SystemExit(f"a cell of {band} is not {CELL_W} px wide")
            rows = []
            for y in range(y0, y1 + 1):
                row = []
                for x in range(x0, x1 + 1):
                    i = px[x, y]
                    if i not in PAIR:
                        raise SystemExit(
                            f"{band} ({x},{y}) is palette index {i}, which is "
                            f"not one of the three colours plus transparent "
                            f"this craft is drawn in")
                    row.append(PAIR[i])
                rows.append(row)
            frames.append(rows)
        out[band] = frames
    return out


def mirror(cell):
    return [list(reversed(r)) for r in cell]


def centroid(cell):
    tot = sx = 0
    for row in cell:
        for i, p in enumerate(row):
            if p:
                tot += 1
                sx += i
    return sx / tot


def place(cell, x_off, y_off):
    """Drop a cell into a blank SPRITE_W_MC x SPRITE_H frame."""
    frame = [[0] * SPRITE_W_MC for _ in range(SPRITE_H)]
    for y, row in enumerate(cell):
        for x, p in enumerate(row):
            if p:
                fx, fy = x + x_off, y + y_off
                if not (0 <= fx < SPRITE_W_MC and 0 <= fy < SPRITE_H):
                    raise SystemExit(f"a pixel falls outside the sprite at {fx},{fy}")
                frame[fy][fx] = p
    return frame


def best_x_off(cell, target_cx):
    """The integer offset whose centroid lands nearest the neutral's.

    Registration matters more than it looks: the frames have different widths
    (12, 11, 10), so placing them all flush left would slide the ship sideways
    by two screen pixels every time it banked. Matching centroids keeps the
    craft's centre of mass still and lets only its shape change.
    """
    w = len(cell[0])
    cands = range(0, SPRITE_W_MC - w + 1)
    return min(cands, key=lambda o: abs(centroid(cell) + o - target_cx))


def pack(frame):
    """21 rows x 12 multicolour pixels -> 63 bytes, 4 pairs per byte."""
    out = []
    for row in frame:
        for b in range(3):
            v = 0
            for p in range(4):
                v |= (row[b * 4 + p] & 3) << (6 - 2 * p)
            out.append(v)
    return out


BANK_ORDER = ["bankL2", "bankL1", "neutral", "bankR1", "bankR2"]


def build():
    """15 frames, bank-major: index = bank * ANIM_FRAMES + anim.

    Bank-major is what lets src/player.asm turn a signed lean and an engine
    phase into a pointer with a shift, an add and an add -- no table.
    """
    cells = load_cells()
    src = {
        "bankL2":  cells["bankL2"],
        "bankL1":  cells["bankL1"],
        "neutral": cells["neutral"],
        "bankR1":  [mirror(f) for f in cells["bankL1"]],
        "bankR2":  [mirror(f) for f in cells["bankL2"]],
    }
    # Every cell is the same 12-wide box, so the artist's own registration
    # inside it is used unchanged: x offset 0 for all fifteen. Vertically the
    # 16 rows are centred in the sprite's 21.
    y_off = (SPRITE_H - CELL_H) // 2
    frames = []
    for bank in BANK_ORDER:
        for anim in range(ANIM_FRAMES):
            frames.append((f"{bank}/engine{anim}",
                           pack(place(src[bank][anim], 0, y_off))))
    return frames


HEADER = '''// ===========================================================================
// player_art.asm — the player craft's multicolour sprite bitmaps
// ===========================================================================
// GENERATED by tools/gen_player_ship.py from the supplied sprite sheet. Do not
// edit by hand: rerun the tool, which also has a --check mode that fails if
// this file has drifted from the PNG.
//
// FIFTEEN frames of one 24x21 MULTICOLOUR sprite, BANK-MAJOR:
//
//     index = bank * 3 + engine        bank 0..4 = hard left .. hard right
//                                      engine 0..2 = flame full, small, out
//
// The sheet draws the neutral craft and two LEFT-leaning bank stages, each
// with three engine frames; the right-hand banks are horizontal mirrors.
//
// Bit pairs, and which register each reaches:
//     00  transparent
//     01  $d025  shared        black       (the outline)
//     10  $d027  sprite 0      light blue  (the body: the colour
//                                           src/player.asm turns red for the
//                                           muzzle flash)
//     11  $d026  shared        white
//
// Each frame is 63 bytes of bitmap plus one padding byte, because a C64 sprite
// costs a 64-byte block whatever it uses.
// ===========================================================================
'''


def emit(frames):
    L = [HEADER, "player_art_frames:\n"]
    for name, data in frames:
        L.append(f"// --- {name}\n")
        for r in range(SPRITE_H):
            row = data[r * 3:r * 3 + 3]
            L.append("    .byte " + ", ".join(f"${b:02x}" for b in row) + "\n")
        L.append("    .byte $00\n\n")
    return "".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    frames = build()
    text = emit(frames)
    if a.check:
        if not OUT.exists():
            print(f"FAIL {OUT} does not exist"); return 1
        if OUT.read_text() != text:
            print(f"FAIL {OUT} has drifted from {SHEET.name}"); return 1
        print(f"ok   {OUT.name} matches {SHEET.name}")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(frames)} frames)")
    for name, data in frames:
        lit = sum(1 for b in data for p in range(4) if (b >> (6 - 2 * p)) & 3)
        print(f"   {name:18s} lit pairs={lit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
