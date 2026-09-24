#!/usr/bin/env python3
"""The authoritative current sprite data, taken from the artefact the VIC sees.

WHERE THE TRUTH LIVES, and why it is not the .asm files.

Sprite bytes in this project reach the machine three different ways: literal
`.byte` rows (enemy_art.asm), rows a comment says were row-replicated from
16 authored lines to 21 (player_art.asm), and bytes produced entirely by
assembler functions inside `.for` loops (hud.asm's `livesByte(n, r, c)`).
Re-parsing the source would mean re-implementing KickAssembler, and would be
wrong for the third kind. So this module reads the ASSEMBLED PROGRAM at the
addresses the symbol file reports, which is by definition what the game draws.

    build/shmup.prg   the bytes
    build/main.vs     the addresses (KickAssembler -vicesymbols)

Nothing here contains a second copy of any artwork. The only thing declared by
hand is the GROUP TABLE below -- which run of blocks is what, what mode it is
drawn in and what colour the engine gives it -- and every entry of that table is
cross-checked against the build before it is used.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PRG = REPO / "build" / "shmup.prg"
SYMBOLS = REPO / "build" / "main.vs"

BLOCK = 64          # what the VIC steps by
BITMAP = 63         # 21 rows x 3 bytes; the 64th byte is never fetched


class SpriteSourceError(RuntimeError):
    """The build does not look the way this module requires."""


# ---------------------------------------------------------------------------
# the group table
# ---------------------------------------------------------------------------
# EVERY GAMEPLAY SPRITE IN THIS GAME IS MULTICOLOUR. src/renderer.asm sets
# D01C_GAMEPLAY for all six mux slots plus the player's two, and asserts it:
#   "the gameplay phase's $d01c leaves a mux slot in hires".
# The only hires sprites are the HUD's, which are excluded below.
#
# `colour` is the value the engine puts in this sprite's own $d027+n. Where the
# runtime changes it, the authored/primary value is used and `colour_note` says
# what actually happens -- SpritePad stores one colour per sprite and cannot
# express an animation.
@dataclass(frozen=True)
class Group:
    symbol: str                 # label in build/main.vs
    count: int                  # blocks
    role: str
    colour: int
    multicolour: bool = True
    names: tuple = ()           # per-block names; generated when empty
    colour_note: str = ""
    end_symbol: str = ""        # when present, count is PROVED against it
    ends_at_symbol: str = ""    # or against where the next run starts


GROUPS = (
    Group("player_art_frames", 16, "player ship", 14,
          names=tuple(
              f"ship_bank{b}_engine{e}"
              for b in range(5) for e in range(3)) + ("ship_blank_hw1",),
          colour_note="PLAYER_COL_SHIP=14 for the 15 drawn frames; the 16th "
                      "block is the deliberate blank HW1 draws with "
                      "PLAYER_COL_BLANK=0",
          ends_at_symbol="playerFlashBitmaps"),
    Group("playerFlashBitmaps", 5, "player muzzle flash", 2,
          names=tuple(f"muzzle_bank{b}" for b in range(5)),
          colour_note="PLAYER_COL_FLASH=2, red, both frames",
          end_symbol="playerFlashBitmapsEnd"),
    Group("tokenBitmap", 1, "collectible token", 1,
          names=("token_P",),
          colour_note="pulses PICKUP_P_COL_LIT=1 (white) <-> "
                      "PICKUP_P_COL_DARK=15 (light grey) as a brightness "
                      "flash; the lit value is exported"),
    Group("playerBoomArt", 8, "player death fireball", 2,
          names=tuple(f"boom_{i}" for i in range(8)),
          colour_note="PLAYER_COL_BOOM=2, red, in HW0's own $d027",
          end_symbol="playerBoomArtEnd"),
    Group("sonicRingFrames", 4, "enemy: Sonic Ring", 13,
          names=("ring_north", "ring_east", "ring_south", "ring_west"),
          colour_note="NO FIXED COLOUR. Pair 10 is the wave's authored colour "
                      "in $d027+n; level 1 authors 10, 3, 7, 13 and 1. 13 is "
                      "exported as an editing default because it is an "
                      "authored value and differs from both shared "
                      "multicolours",
          end_symbol="sonicRingFramesEnd"),
    Group("orbitalDropperFrames", 4, "enemy: Orbital Dropper", 13,
          names=("dropper_wide", "dropper_front_right",
                 "dropper_front", "dropper_front_left"),
          colour_note="same per-wave colour as the Ring; see above",
          end_symbol="orbitalDropperFramesEnd"),
    Group("squareFrames", 4, "enemy: Square", 4,
          names=("square_0_full", "square_1_turn",
                 "square_2_narrow", "square_3_edge"),
          colour_note="NO FIXED COLOUR, exactly like the Ring and the Dropper: "
                      "pair 10 is the wave's authored colour in $d027+n. The "
                      "value here is the .spd's editing colour and never "
                      "reaches the game",
          end_symbol="squareFramesEnd"),
    Group("bossArt", 4, "boss", 4,
          names=tuple(f"boss_cell{i}" for i in range(4)),
          colour_note="BOSS_COL=4 (purple); the whole machine flashes to "
                      "BOSS_COL_HIT=1 (white) while taking a hit",
          end_symbol="bossArtEnd"),
    Group("ebulletBitmap", 1, "hostile projectile", 7,
          names=("ebullet",),
          colour_note="EBULLET_COL=7, yellow"),
)

# Shared registers, from src/main.asm.
SPR_MC_DARK = 11        # $d025, bit-pair 01
SPR_MC_LIGHT = 1        # $d026, bit-pair 11
BACKGROUND = 0          # $d021 as gameInit leaves it; an editing
                        # backdrop only -- terrain sets the level's

# DELIBERATELY NOT EXPORTED, and listed so the omission is a decision rather
# than an oversight. hudBitmaps ($3200, 14 blocks) is the only other sprite
# memory with a symbol, and none of it is artwork anybody would edit:
#   blocks 0..3   heat left/right, score left/right -- `.fill 64, 0` in the
#                 source and drawn into by the CPU every frame. Zero in the
#                 binary; they are framebuffers, not pictures.
#   blocks 4..13  lives 0..5 and upgrade 0..3 -- emitted by the assembler
#                 functions livesByte()/pchargeByte() inside `.for` loops, so
#                 they are regenerated from code on every build and a pixel
#                 edited in an editor could not survive.
# They are also the game's only HIRES sprites, so including them would make the
# project mixed-mode for no gain.
EXCLUDED = (
    ("hudBitmaps", 14, "HUD: heat, score, lives, upgrade pips",
     "4 runtime framebuffers (zero at build) + 10 assembler-generated; hires"),
)


# ---------------------------------------------------------------------------
# reading the build
# ---------------------------------------------------------------------------
_SYMBOL_RE = re.compile(r"^al\s+C:([0-9a-fA-F]{4})\s+\.(\S+)\s*$")


def load_symbols(path=SYMBOLS):
    """{name: address} from a KickAssembler VICE symbol file."""
    path = Path(path)
    if not path.is_file():
        raise SpriteSourceError(
            f"{path} is missing. Run `make build` first: this exporter reads "
            f"the assembled program, not the .asm sources.")
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SYMBOL_RE.match(line.strip())
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    if not out:
        raise SpriteSourceError(f"{path} yielded no symbols")
    return out


class Program:
    """The assembled PRG, addressable the way the machine addresses it."""

    def __init__(self, path=PRG):
        path = Path(path)
        if not path.is_file():
            raise SpriteSourceError(f"{path} is missing. Run `make build` first.")
        raw = path.read_bytes()
        if len(raw) < 3:
            raise SpriteSourceError(f"{path} is too short to be a PRG")
        self.load = raw[0] | (raw[1] << 8)
        self.body = raw[2:]
        self.end = self.load + len(self.body)

    def read(self, addr, n):
        off = addr - self.load
        if off < 0 or off + n > len(self.body):
            raise SpriteSourceError(
                f"${addr:04x}+{n} is outside the PRG "
                f"(${self.load:04x}..${self.end - 1:04x})")
        return self.body[off:off + n]


@dataclass(frozen=True)
class Sprite:
    index: int
    name: str
    group: str
    role: str
    source_symbol: str
    address: int
    pointer: int            # the VIC sprite-pointer value, address / 64
    bitmap: bytes           # exactly 63
    pad: int                # the 64th byte the VIC never fetches
    multicolour: bool
    colour: int
    colour_note: str = ""
    blank: bool = False


def extract(prg=None, symbols=None):
    """Every exported sprite, in a stable order. Raises on anything surprising."""
    prg = prg or Program()
    symbols = symbols if symbols is not None else load_symbols()

    sprites = []
    for g in GROUPS:
        if g.symbol not in symbols:
            raise SpriteSourceError(
                f"the build has no symbol '{g.symbol}'; the sprite layout has "
                f"changed and this exporter's group table is out of date")
        base = symbols[g.symbol]
        if base % BLOCK:
            raise SpriteSourceError(
                f"{g.symbol} is at ${base:04x}, which is not 64-byte aligned; "
                f"the VIC cannot address it as a sprite")

        # PROVE THE COUNT rather than trusting the table.
        expected_end = base + g.count * BLOCK
        if g.end_symbol:
            if g.end_symbol not in symbols:
                raise SpriteSourceError(f"missing end symbol '{g.end_symbol}'")
            actual = symbols[g.end_symbol]
            if actual != expected_end:
                raise SpriteSourceError(
                    f"{g.symbol}: {g.count} blocks would end at ${expected_end:04x} "
                    f"but {g.end_symbol} is at ${actual:04x}")
        elif g.ends_at_symbol:
            if g.ends_at_symbol not in symbols:
                raise SpriteSourceError(f"missing symbol '{g.ends_at_symbol}'")
            actual = symbols[g.ends_at_symbol]
            if actual != expected_end:
                raise SpriteSourceError(
                    f"{g.symbol}: {g.count} blocks would end at ${expected_end:04x} "
                    f"but the next run ({g.ends_at_symbol}) starts at ${actual:04x}")

        names = g.names or tuple(f"{g.symbol}_{i}" for i in range(g.count))
        if len(names) != g.count:
            raise SpriteSourceError(
                f"{g.symbol}: {len(names)} names for {g.count} blocks")

        for i in range(g.count):
            addr = base + i * BLOCK
            block = prg.read(addr, BLOCK)
            bitmap, pad = block[:BITMAP], block[BITMAP]
            if len(bitmap) != BITMAP:
                raise SpriteSourceError(
                    f"{names[i]} yielded {len(bitmap)} bytes, not {BITMAP}")
            blank = not any(bitmap)
            colour = g.colour
            if g.symbol == "player_art_frames" and blank:
                colour = 0                      # PLAYER_COL_BLANK
            sprites.append(Sprite(
                index=len(sprites), name=names[i], group=g.symbol, role=g.role,
                source_symbol=g.symbol, address=addr, pointer=addr // BLOCK,
                bitmap=bitmap, pad=pad, multicolour=g.multicolour,
                colour=colour, colour_note=g.colour_note, blank=blank))
    return sprites


def duplicate_map(sprites):
    """{index -> index of the first sprite with identical 63 bytes}.

    Reported, never acted on: collapsing two entries would renumber everything
    after them and break the correspondence with the engine's sprite pointers.
    """
    first = {}
    out = {}
    for s in sprites:
        key = bytes(s.bitmap)
        if key in first:
            out[s.index] = first[key]
        else:
            first[key] = s.index
    return out
