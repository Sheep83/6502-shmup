#!/usr/bin/env python3
"""SpritePad .spd -> generated KickAssembler sprite includes. The one direction.

    python3 tools/sprite_export/import_spd.py            # regenerate
    python3 tools/sprite_export/import_spd.py --check     # is the tree current?

THE SPD IS NOW THE SOURCE OF TRUTH for every editable gameplay sprite. Edit
assets/sprites/19656-sprites.spd in Spritemate, run this, rebuild. The files it
writes under src/generated_sprites/ are derived and must never be hand-edited --
the next run overwrites them.

WHY GENERATED .asm AND NOT A BINARY BLOB. The sprites do not live in one run:
they are pinned at $2000, $2400, $2580, $25c0, $2c00, $2d00, $3000, $3580 and
$36c0, and several of those addresses are owned by the file that imports them
(src/player.asm sets `* = PLAYER_SPRITES` and then imports the art). A single
`.import binary` cannot express that, and changing who owns the addresses would
mean rewriting the memory map to suit the tool. Emitting one include per
existing import point keeps every segment, label and assertion exactly where the
engine already expects it, so the diff is artwork and nothing else.

WHY THE BUILD DOES NOT RUN THIS. tools/level_editor/export_level.py states the
principle for level data: "regenerating source on every build would make `make`
able to change the program's content, so the generation step is explicit and its
output is reviewable in the diff." The same applies to artwork. Instead every
generated file records the SHA-256 of the .spd it came from, `make build`
validates it, and a stale tree fails the build loudly with the command to fix
it. So `make run` can never quietly draw last week's sprites.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import spd_reader                                              # noqa: E402

SPD = REPO / "assets" / "sprites" / "19656-sprites.spd"
OUT_DIR = REPO / "src" / "generated_sprites"
STAMP = OUT_DIR / "sprite_art_stamp.asm"

BITMAP = 63
BLOCK = 64

# The slot layout of the edited project. Slots 0..42 are the roles the first
# export established and MUST keep their order -- the engine addresses them by
# sprite pointer. 43..46 are the Square frames Brian appended. 47 is an empty
# trailing slot Spritemate left behind and is deliberately not imported.
EXPECTED_SLOTS = 48
SQUARE_SLOTS = (43, 44, 45, 46)
BLANK_SLOTS = (15, 47)          # 15 is the player's deliberate HW1 blank


class ImportError_(RuntimeError):
    """The .spd does not look the way the engine requires."""


@dataclass(frozen=True)
class Group:
    filename: str
    first: int                      # first SPD slot
    count: int
    title: str
    doc: tuple                      # header lines
    pin: str = ""                   # emit `* = <pin>` when the file owns its address
    head_label: str = ""
    frame_labels: tuple = ()        # one per block, or empty
    end_label: str = ""
    segment: str = ""


GROUPS = (
    Group("player_art.asm", 0, 15, "the player ship, fifteen multicolour frames",
          ("Five banking attitudes x three engine frames, bank-major:",
           "    index = bank * 3 + engine",
           "    bank 0..4 = hard left .. hard right",
           "    engine 0..2 = flame full, small, out",
           "",
           "The SIXTEENTH block is NOT here. src/player.asm emits it itself as",
           "playerBlankBitmap -- the blank HW1 draws -- and this importer checks",
           "that the .spd's slot 15 is still blank so the two cannot disagree.",
           "",
           "The caller owns the address: src/player.asm sets * = PLAYER_SPRITES."),
          head_label="player_art_frames"),
    Group("player_muzzle_flash.asm", 16, 5, "the muzzle flash, one per attitude",
          ("The caller owns the address: src/player.asm sets",
           "* = PLAYER_FLASH_SPRITES and wraps this in its own labels.",),
          head_label="player_muzzle_flash_frames"),
    Group("token_art.asm", 21, 1, "the collectible token",
          ("The caller owns the address and the labels: src/pickup.asm pins",
           "this between the muzzle flash and the fireball.",)),
    Group("player_boom_art.asm", 22, 8, "the player's death fireball, eight frames",
          ("Eight 24x21 multicolour blocks that replace the ship's silhouette on",
           "HW0 the instant the craft dies, so the explosion costs no mux slot.",
           "",
           "This file pins itself, as the hand-authored one did.",),
          pin="PLAYER_BOOM_SPRITES", segment="player fireball",
          head_label="playerBoomArt",
          frame_labels=tuple(f"playerBoomFrame{i}" for i in range(8)),
          end_label="playerBoomArtEnd"),
    Group("enemy_art.asm", 30, 4, "the Sonic Ring: four multicolour frames",
          ("Rotation order: north -> east -> south -> west. src/enemy.asm asserts",
           "each frame label lands on its own block, so the labels are part of the",
           "contract and not decoration.",
           "",
           "    %00  transparent",
           "    %01  $d025, SPR_MC_DARK   -- shared dark grey",
           "    %10  $d027+n              -- THIS enemy's own colour, which is",
           "                                 the wave's authored colour",
           "    %11  $d026, SPR_MC_LIGHT  -- shared white",
           "",
           "The caller owns the address: src/enemy.asm sets * = ENEMY_SPRITES.",),
          head_label="sonicRingFrames",
          frame_labels=("sonicRing_north", "sonicRing_east",
                        "sonicRing_south", "sonicRing_west"),
          end_label="sonicRingFramesEnd"),
    Group("enemy_dropper_art.asm", 34, 4, "the Orbital Dropper: four frames",
          ("Same four-pair palette as the Ring; pair 10 is the wave's authored",
           "colour and carries the orb itself.",
           "",
           "The caller owns the address: src/enemy.asm sets * = DROPPER_SPRITES.",),
          head_label="orbitalDropperFrames",
          frame_labels=("orbitalDropper_0_wide", "orbitalDropper_1_front_right",
                        "orbitalDropper_2_front", "orbitalDropper_3_front_left"),
          end_label="orbitalDropperFramesEnd"),
    Group("enemy_square_art.asm", 43, 4, "the Square: four multicolour frames",
          ("THE THIRD ORDINARY SPECIES. Appended to the .spd in Spritemate and",
           "imported here like any other artwork -- there is nothing special",
           "about it beyond being newer.",
           "",
           "The four frames are a spin: the silhouette narrows from a full",
           "square to an edge-on bar and the shading follows it round.",
           "",
           "Same four-pair palette as the Ring and the Dropper, so a wave's",
           "authored colour reaches pair 10 exactly as it does for them.",
           "",
           "The caller owns the address: src/enemy.asm sets * = SQUARE_SPRITES.",),
          head_label="squareFrames",
          frame_labels=("square_0_full", "square_1_turn",
                        "square_2_narrow", "square_3_edge"),
          end_label="squareFramesEnd"),
    Group("boss_art.asm", 38, 4, "the boss, four cells of one machine",
          ("The caller owns nothing: this file pins itself at BOSS_SPRITES, as",
           "the hand-authored one did.",),
          pin="BOSS_SPRITES", segment="boss cells",
          head_label="bossArt",
          frame_labels=tuple(f"bossCell{i}" for i in range(4)),
          end_label="bossArtEnd"),
    Group("ebullet_art.asm", 42, 1, "the hostile projectile",
          ("The caller owns the address and the labels: src/ebullet.asm sets",
           "* = EBULLET_SPRITE.",)),
)


def _banner(title, doc, digest):
    line = "// " + "=" * 74
    out = [line,
           "// AUTO-GENERATED by tools/sprite_export/import_spd.py.",
           "// DO NOT EDIT BY HAND -- the next import overwrites this file.",
           "//",
           f"// {title}",
           "//",
           "// Source of truth: assets/sprites/19656-sprites.spd, edited in",
           "// Spritemate. Regenerate with `make sprites`.",
           f"// spd sha256: {digest}",
           "//"]
    out += [f"// {d}" if d else "//" for d in doc]
    out.append(line)
    return out


def _rows(bitmap, pad):
    """21 rows of three, then the pad byte the VIC never fetches."""
    out = []
    for r in range(21):
        b = bitmap[r * 3:(r + 1) * 3]
        out.append("    .byte " + ", ".join(f"${v:02x}" for v in b))
    out.append(f"    .byte ${pad:02x}"
               + " " * 10 + "// the 64th byte: alignment, never fetched")
    return out


def load_spd(path=SPD):
    path = Path(path)
    if not path.is_file():
        raise ImportError_(f"{path} is missing")
    raw = path.read_bytes()
    try:
        f = spd_reader.parse(raw)
    except spd_reader.SpdReadError as e:
        raise ImportError_(f"{path}: {e}") from e
    if len(f.sprites) != EXPECTED_SLOTS:
        raise ImportError_(
            f"{path} holds {len(f.sprites)} sprites; the engine's layout "
            f"expects {EXPECTED_SLOTS} (43 established roles, 4 Square frames, "
            f"1 trailing blank). Sprites appear to have been inserted or "
            f"removed rather than edited -- refusing to guess which is which")
    for slot in BLANK_SLOTS:
        if any(f.sprites[slot].bitmap):
            raise ImportError_(
                f"{path}: slot {slot} is expected to be blank but has data. "
                f"Slot 15 is the player's deliberate HW1 blank and slot 47 is "
                f"the unused trailing slot")
    for slot in SQUARE_SLOTS:
        s = f.sprites[slot]
        if not any(s.bitmap):
            raise ImportError_(f"{path}: Square frame at slot {slot} is blank")
        if not s.multicolour:
            raise ImportError_(
                f"{path}: Square frame at slot {slot} is hires; every gameplay "
                f"sprite in this game is multicolour")
    for i, s in enumerate(f.sprites):
        if len(s.bitmap) != BITMAP:
            raise ImportError_(f"{path}: slot {i} is not {BITMAP} bytes")
    return raw, f


def render(group, spd, digest):
    lines = _banner(group.title, group.doc, digest) + [""]
    if group.pin:
        lines.append(f'* = {group.pin} "{group.segment}"')
    if group.head_label:
        lines.append(f"{group.head_label}:")
    for i in range(group.count):
        s = spd.sprites[group.first + i]
        if group.frame_labels:
            lines.append(f"{group.frame_labels[i]}:")
        elif i:
            lines.append("")
        lines += _rows(s.bitmap, 0)
    if group.end_label:
        lines.append(f"{group.end_label}:")
    return "\n".join(lines) + "\n"


def generate(spd_path=SPD, out_dir=OUT_DIR):
    raw, spd = load_spd(spd_path)
    digest = hashlib.sha256(raw).hexdigest()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for g in GROUPS:
        files[g.filename] = render(g, spd, digest)
    files[STAMP.name] = "\n".join(
        _banner("the stamp that makes a stale sprite tree impossible to miss",
                ("Nothing imports this file for its contents -- it has none. It",
                 "records which .spd the generated art beside it came from, and",
                 "tools/sprite_export/import_spd.py --check compares it with the",
                 "file on disk. `make build` runs that check, so editing the .spd",
                 "and forgetting to regenerate fails the build instead of quietly",
                 "shipping the previous artwork.",), digest)) + "\n"
    return files, digest


def write(spd_path=SPD, out_dir=OUT_DIR):
    files, digest = generate(spd_path, out_dir)
    out_dir = Path(out_dir)
    for name, text in sorted(files.items()):
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    return files, digest


def current_digest(out_dir=OUT_DIR):
    """The .spd hash the generated tree was produced from, or None."""
    stamp = Path(out_dir) / STAMP.name
    if not stamp.is_file():
        return None
    for line in stamp.read_text(encoding="utf-8").splitlines():
        if line.startswith("// spd sha256:"):
            return line.split(":", 1)[1].strip()
    return None


def check(spd_path=SPD, out_dir=OUT_DIR):
    """(ok, message). True when every generated file matches a fresh render."""
    spd_path = Path(spd_path)
    if not spd_path.is_file():
        return False, f"{spd_path} is missing"
    want = hashlib.sha256(spd_path.read_bytes()).hexdigest()
    have = current_digest(out_dir)
    if have is None:
        return False, f"{Path(out_dir) / STAMP.name} is missing -- never generated"
    if have != want:
        return False, (f"generated from a different .spd\n"
                       f"      generated from {have}\n"
                       f"      .spd is now    {want}")
    files, _ = generate(spd_path, out_dir)
    stale = [n for n, text in files.items()
             if not (Path(out_dir) / n).is_file()
             or (Path(out_dir) / n).read_text(encoding="utf-8") != text]
    if stale:
        return False, "these generated files differ from a fresh render: " \
                      + ", ".join(sorted(stale))
    return True, f"{len(files)} generated files current ({want[:12]})"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    for a in argv:
        if a != "--check":
            raise SystemExit(f"unknown argument {a!r}")
    try:
        if check_only:
            ok, msg = check()
            print(f"  sprite art: {msg}")
            if not ok:
                print("\n  The generated sprite art is STALE.\n"
                      "  Run:  make sprites\n")
                return 1
            return 0
        files, digest = write()
        for name in sorted(files):
            print(f"  wrote src/generated_sprites/{name}")
        print(f"  from assets/sprites/19656-sprites.spd ({digest[:12]})")
        return 0
    except ImportError_ as e:
        print(f"  sprite import refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
