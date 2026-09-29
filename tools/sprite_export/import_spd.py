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

# ---------------------------------------------------------------------------
# THE SOURCE PROJECT, AND WHY THE NUMBERS MOVED
# ---------------------------------------------------------------------------
# The .spd is now a 110-slot SpritePad v5 project and the artwork was
# REORGANISED, not merely extended. Verified by matching the old project's
# bitmaps into the new file rather than by trusting a description:
#
#   player ship      old  0..14  ->  $00..$0E   same slots (six frames redrawn)
#   HW1 blank        old 15      ->  $0F        still blank
#   muzzle flash     old 16..20  ->  $10..$14   identical bytes
#   player fireball  old 22..29  ->  $16..$1D   identical bytes
#   boss             old 38..41  ->  $22..$25   identical bytes
#   hostile bullet   old 42      ->  $26        identical bytes
#   token            old 21      ->  gone; the shaded replacement is $53
#   Sonic Ring       old 30..33  ->  gone; see RING below
#   Dropper          old 34..37  ->  redrawn at $1E..$21
#   Square           old 43..46  ->  redrawn at $27..$2A
#
# SPRITEPAD INDICES ARE THE ART'S IDENTITY NOW. Brian authors and refers to
# artwork by SpritePad index, so this table is the single place that maps a
# source index to a runtime home, and every generated file records the indices
# it came from in its own banner. Nothing downstream renumbers anything.
#
# MOST SLOTS HAVE NO RUNTIME HOME AND THAT IS CORRECT. The engine wires three
# enemy species, a player, a muzzle flash, a fireball, a token, a boss and a
# bullet -- 46 blocks in total. The other 64 blocks in the project, including
# every range Brian listed as disposable ($0F, $15, $2B-$33, $37-$3A, $4A-$4F),
# are simply not named below, so they cost no runtime memory at all. They stay
# in the .spd as the artwork authority. There is no compaction step and nothing
# to compact: only what is named here is ever emitted.
EXPECTED_SLOTS = 110
SQUARE_SLOTS = (0x27, 0x28, 0x29, 0x2A)
BLANK_SLOTS = (0x0F, 0x6D)      # $0F is the player's deliberate HW1 blank


class ImportError_(RuntimeError):
    """The .spd does not look the way the engine requires."""


@dataclass(frozen=True)
class Group:
    filename: str
    slots: tuple                    # the SPD source indices, in emit order
    title: str
    doc: tuple                      # header lines
    pin: str = ""                   # emit `* = <pin>` when the file owns its address
    head_label: str = ""
    frame_labels: tuple = ()        # one per block, or empty
    end_label: str = ""
    segment: str = ""


GROUPS = (
    Group("player_art.asm", tuple(range(0x00, 0x0F)),
          "the player ship, fifteen multicolour frames",
          ("SpritePad $00..$0E. Five banking attitudes x three engine frames,",
           "bank-major:",
           "    index = bank * 3 + engine",
           "    bank 0..4 = hard left .. hard right",
           "    engine 0..2 = flame full, small, out",
           "",
           "The SIXTEENTH block is NOT here. src/player.asm emits it itself as",
           "playerBlankBitmap -- the blank HW1 draws -- and this importer checks",
           "that the .spd's slot $0F is still blank so the two cannot disagree.",
           "",
           "The caller owns the address: src/player.asm sets * = PLAYER_SPRITES."),
          head_label="player_art_frames"),
    Group("player_muzzle_flash.asm", tuple(range(0x10, 0x15)),
          "the muzzle flash, one per attitude",
          ("SpritePad $10..$14.",
           "",
           "The caller owns the address: src/player.asm sets",
           "* = PLAYER_FLASH_SPRITES and wraps this in its own labels.",),
          head_label="player_muzzle_flash_frames"),
    Group("token_art.asm", (0x53,), "the collectible token",
          ("SpritePad $53, the SHADED power-up.",
           "",
           "THE SOURCE INDEX MOVED AND THE ROLE DID NOT. The token used to come",
           "from slot 21 of the old project; that artwork is the OLD power-up,",
           "which Brian has retired, and its slot is now $15 and is not imported",
           "by anything. $53 is the shaded replacement and is the only power-up",
           "the game draws.",
           "",
           "The caller owns the address and the labels: src/pickup.asm pins",
           "this between the muzzle flash and the fireball.",)),
    Group("player_boom_art.asm", tuple(range(0x16, 0x1E)),
          "the player's death fireball, eight frames",
          ("SpritePad $16..$1D. Eight 24x21 multicolour blocks that replace the",
           "ship's silhouette on HW0 the instant the craft dies, so the",
           "explosion costs no mux slot.",
           "",
           "This file pins itself, as the hand-authored one did.",),
          pin="PLAYER_BOOM_SPRITES", segment="player fireball",
          head_label="playerBoomArt",
          frame_labels=tuple(f"playerBoomFrame{i}" for i in range(8)),
          end_label="playerBoomArtEnd"),
    Group("boss_art.asm", tuple(range(0x22, 0x26)),
          "the boss, four cells of one machine",
          ("SpritePad $22..$25. Still the placeholder boss.",
           "",
           "The caller owns nothing: this file pins itself at BOSS_SPRITES, as",
           "the hand-authored one did.",),
          pin="BOSS_SPRITES", segment="boss cells",
          head_label="bossArt",
          frame_labels=tuple(f"bossCell{i}" for i in range(4)),
          end_label="bossArtEnd"),
    Group("ebullet_art.asm", (0x26,), "the hostile projectile",
          ("SpritePad $26.",
           "",
           "The caller owns the address and the labels: src/ebullet.asm sets",
           "* = EBULLET_SPRITE.",)),
)


# ---------------------------------------------------------------------------
# THE ENEMY ARTWORK ROSTER
# ---------------------------------------------------------------------------
# A ROSTER ENTRY IS ARTWORK, NOT A SPECIES, and the distinction is the whole
# design. In this engine a *species* is a BEHAVIOUR: SPECIES_DROPPER has its own
# movement in src/enemy.asm and its own handling in src/waves.asm, src/waves.asm
# validates an authored species by membership of the three, and src/token.asm
# spawns a SPECIES_RING by name. There are three of those and this task does not
# add a fourth.
#
# What a level now chooses is which ARTWORK each of its three behavioural slots
# wears. So the roster below is twelve sequences of bitmaps with frame counts,
# and a level says "slot A wears ring_3, slot B wears the Dropper, slot C wears
# the Square" -- costing 8 + 4 + 4 = 16 of the window's 20 blocks.
#
# FRAME COUNTS ARE THE SOURCE RANGE'S LENGTH AND NOTHING ELSE. No sequence is
# sampled, padded or truncated to fit a fixed layout; that interim compromise
# (ring_3 as $60,$62,$64,$66) is gone.
#
# THE SHAPE is the eight animation STEPS mapped onto those frames. The engine's
# phase is eight steps wide because it is masked out of a free-running frame
# counter and 8 divides the 256-frame wrap; that is unchanged. For a sequence of
# N frames the default shape is simply `step mod N`, which reaches every frame
# and states no direction. The three sequences that already had an authored
# shape keep it exactly, so no existing level changes behaviour. LOOP and
# PINGPONG modes are explicitly a later task and nothing here pre-empts them.
ENEMY_ANIM_STEPS = 8


# THE ONLY BEHAVIOUR THE OLD THREE SPECIES ACTUALLY CARRIED.
#
# Audited site by site before any of this was written. Of the three legacy
# species, Ring and Square were behaviourally IDENTICAL -- every difference
# between them was artwork. Health is global TYPE data (ENEMY_MAX_HP), there is
# no per-species collision box and no per-species score, and enemyFireModeTab
# held three entries all reading ENEMY_FIRE_DOWN.
#
# The Dropper is genuinely different, in five places: it drops the token on
# death, it owns the one-live-Dropper claim, it clears that claim when it leaves
# by any route, it flies dropperLaunch instead of its wave's path, and a refused
# Dropper is substituted with an ordinary enemy rather than dropped. That is a
# BEHAVIOUR, and it belongs to an identity rather than to a slot -- which is
# what lets "Space Whisk" be an enemy in its own right instead of artwork
# pretending to be a Sonic Ring.
BEHAVIOUR_PLAIN = 0
BEHAVIOUR_DROPPER = 1


@dataclass(frozen=True)
class Roster:
    name: str                       # the engine/editor identifier
    label: str                      # what the editor shows a human
    slots: tuple                    # SpritePad source indices, in order
    shape: tuple = ()               # 8 steps; default is step mod frames
    behaviour: int = BEHAVIOUR_PLAIN

    @property
    def frames(self):
        return len(self.slots)

    @property
    def steps(self):
        return self.shape or tuple(i % self.frames for i in range(ENEMY_ANIM_STEPS))

    @property
    def filename(self):
        return f"enemy_{self.name.lower()}_art.asm"

    @property
    def symbol(self):
        parts = self.name.lower().split("_")
        return parts[0] + "".join(w.capitalize() for w in parts[1:]) + "Frames"


ENEMY_ROSTER = (
    # The three that already existed keep their authored shapes verbatim.
    Roster("DROPPER", "Dropper", tuple(range(0x1E, 0x22)),
           shape=(0, 1, 2, 3, 3, 2, 1, 0),       # out and back
           behaviour=BEHAVIOUR_DROPPER),         # the token carrier
    Roster("SQUARE", "Square", tuple(range(0x27, 0x2B)),
           shape=(0, 1, 2, 3, 3, 2, 1, 0)),      # a spin reverses
    # New artwork. Default shape: step mod frames.
    Roster("ALLEYKAT_A", "Modded Alleykat A", tuple(range(0x34, 0x37))),
    Roster("ALLEYKAT_B", "Modded Alleykat B", tuple(range(0x3B, 0x3E))),
    Roster("RING_1", "Ring 1", tuple(range(0x3E, 0x41))),
    Roster("RING_2", "Ring 2", tuple(range(0x41, 0x44))),
    Roster("SPINNER", "Spinner", tuple(range(0x44, 0x4A))),
    Roster("SPACE_MINE", "Space Mine", tuple(range(0x50, 0x53))),
    Roster("SPINNY", "Spinny Thing", tuple(range(0x54, 0x5A))),
    Roster("SPACE_WHISK", "Space Whisk", tuple(range(0x5A, 0x60))),
    Roster("RING_3", "Ring 3", tuple(range(0x60, 0x68))),
    Roster("SPINNY_ROT", "Spinny Rotatey", tuple(range(0x68, 0x6D))),
)

ROSTER_BY_NAME = {r.name: r for r in ENEMY_ROSTER}

for _r in ENEMY_ROSTER:
    if not 1 <= _r.frames <= 8:
        raise SystemExit(f"roster {_r.name}: {_r.frames} frames, must be 1..8")
    if len(_r.steps) != ENEMY_ANIM_STEPS:
        raise SystemExit(f"roster {_r.name}: shape is not {ENEMY_ANIM_STEPS} steps")
    if any(x >= _r.frames for x in _r.steps):
        raise SystemExit(f"roster {_r.name}: a step names a frame it does not have")


# THE ONE PLACE A SOURCE INDEX BECOMES A RUNTIME IDENTITY.
#
# Each generated include is addressed by the engine through a label, and
# tools/sprite_export/verify_sprites.py needs to know which SpritePad slots sit
# behind each of those labels. That knowledge used to be written out a SECOND
# time, as a SLOT_OF_GROUP dictionary of literal slot numbers, and after this
# reorganisation that copy was silently wrong while its test still passed --
# the test compared the stale dictionary against a stale literal list, so the
# two agreed with each other and proved nothing.
#
# So the mapping is derived from GROUPS and nowhere else. A tuple, not a base
# index, because the Ring's four blocks are $60, $62, $64 and $66 -- not
# contiguous -- and "base + n" cannot express that.
RUNTIME_SYMBOL = {
    "player_art.asm":          "player_art_frames",
    "player_muzzle_flash.asm": "playerFlashBitmaps",
    "token_art.asm":           "tokenBitmap",
    "player_boom_art.asm":     "playerBoomArt",
    "boss_art.asm":            "bossArt",
    "ebullet_art.asm":         "ebulletBitmap",
}

SLOTS_OF_SYMBOL = {RUNTIME_SYMBOL[g.filename]: g.slots for g in GROUPS}
# the roster's symbols are its own; they are not renamed anywhere
SLOTS_OF_SYMBOL.update({r.symbol: r.slots for r in ENEMY_ROSTER})

if set(RUNTIME_SYMBOL) != {g.filename for g in GROUPS}:
    raise SystemExit("RUNTIME_SYMBOL and GROUPS disagree about the file set")


def roster_groups():
    """One include per roster entry, carrying ALL of its frames.

    The level package decides which of these it ships and where in the window
    they land; this only guarantees that every frame of every sequence exists,
    in source order, with nothing sampled away.
    """
    out = []
    for r in ENEMY_ROSTER:
        src = " ".join(f"${x:02X}" for x in r.slots)
        out.append(Group(
            r.filename, r.slots,
            f"{r.label}: {r.frames} multicolour frame(s)",
            (f"SpritePad {src} -- every frame, in source order.",
             "",
             f"Animation steps for this artwork: {r.steps}",
             "(eight steps because the engine masks its phase out of a",
             "free-running frame counter; see src/enemy.asm.)",
             "",
             "    %00  transparent",
             "    %01  $d025, SPR_MC_DARK   -- shared dark grey",
             "    %10  $d027+n              -- the TRIGGER's authored colour",
             "    %11  $d026, SPR_MC_LIGHT  -- shared white",
             "",
             "The caller owns the address: a level package pins the window."),
            head_label=r.symbol,
            end_label=r.symbol + "End"))
    return tuple(out)


ALL_GROUPS = GROUPS + roster_groups()


def roster_constants(digest):
    """`.const` frame counts so a level package can check its own budget."""
    lines = _banner("the enemy artwork roster: frame counts",
                    ("Generated from the roster in import_spd.py. A level",
                     "package uses these to prove its chosen artwork fits the",
                     "engine's enemy sprite window.",
                     "",
                     "A ROSTER ENTRY IS ARTWORK, NOT A SPECIES. The engine has",
                     "three behavioural species; a level chooses which artwork",
                     "each of them wears.",), digest) + [""]
    lines.append(f".const ENEMY_ROSTER_COUNT = {len(ENEMY_ROSTER)}")
    lines.append(f".const ENEMY_ANIM_STEPS_GEN = {ENEMY_ANIM_STEPS}")
    lines.append("")
    for i, r in enumerate(ENEMY_ROSTER):
        lines.append(f".const ROSTER_{r.name} = {i}"
                     f"{' ' * max(1, 22 - len(r.name))}// {r.label},"
                     f" ${r.slots[0]:02X}-${r.slots[-1]:02X}")
        lines.append(f".const ROSTER_{r.name}_FRAMES = {r.frames}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# A LEVEL'S CHOICE OF ARTWORK, TURNED INTO THE 24 BYTES THE ENGINE LOADS
# ---------------------------------------------------------------------------
# The engine has three behavioural species and an eight-step animation phase, so
# what it ultimately wants is 24 sprite pointers: one per (species, step). Those
# pointers are `window base + block`, and the only part a LEVEL decides is the
# block. So a level package carries exactly 24 bytes -- the window-relative
# block for each species and step -- and the engine adds its window base.
#
# That is the whole of the variable-frame-count change at runtime. A species
# wearing 8-frame artwork has eight distinct blocks in its 24-byte row; one
# wearing 3-frame artwork has three. Nothing in the engine counts frames.
ENEMY_SPECIES_SLOTS = 3         # src/encounter_format.asm SPECIES_COUNT
LEVEL_SPRITE_BLOCKS = 20        # src/main.asm -- the enemy sprite window


class BudgetError(ValueError):
    """A level's chosen artwork does not fit the enemy sprite window."""


def level_sprite_plan(choices):
    """[roster name] -> (packed layout, the 24-byte table). Deterministic.

    `choices` is one roster NAME per behavioural species slot, in species order
    (RING, DROPPER, SQUARE). Artwork is packed into the window contiguously in
    that order, each entry taking exactly its own frame count -- so the window
    holds only what this level actually uses.
    """
    if len(choices) != ENEMY_SPECIES_SLOTS:
        raise BudgetError(
            f"a level names artwork for {ENEMY_SPECIES_SLOTS} species; "
            f"got {len(choices)}")
    layout, base = [], 0
    for name in choices:
        r = ROSTER_BY_NAME.get(name)
        if r is None:
            raise BudgetError(f"{name!r} is not in the enemy artwork roster")
        layout.append((r, base))
        base += r.frames
    if base > LEVEL_SPRITE_BLOCKS:
        raise BudgetError(
            f"this level's artwork needs {base} sprite blocks and the enemy "
            f"window holds {LEVEL_SPRITE_BLOCKS}: "
            + " + ".join(f"{r.label} {r.frames}" for r, _ in layout)
            + f" = {base}")
    table = []
    for r, b in layout:
        table += [b + step for step in r.steps]
    return layout, table


def level_enemies_asm(choices, digest, level_name=""):
    """stage_enemies.asm: the slot claims and the 24-byte animation table."""
    layout, table = level_sprite_plan(choices)
    used = sum(r.frames for r, _ in layout)
    names = ("RING", "DROPPER", "SQUARE")
    lines = _banner(f"which enemy identities this level's three slots hold"
                    + (f" -- {level_name}" if level_name else ""),
                    ("A ROSTER ENTRY IS ARTWORK, NOT A SPECIES. The engine has",
                     "three behavioural species -- RING, DROPPER, SQUARE -- and",
                     "this file says which artwork each of them wears here, and",
                     "where in the enemy sprite window that artwork was loaded.",
                     "",
                     "levelAnimOffsets is the whole animation contract: one byte",
                     "per (species, step), holding the WINDOW-RELATIVE BLOCK that",
                     "step shows. The engine adds its window base and nothing",
                     "else. A species wearing eight-frame artwork simply names",
                     "eight different blocks; nothing counts frames at run time.",
                     ), digest) + [""]
    for (r, b), sp in zip(layout, names):
        lines.append(f".const LVL_SLOT_{sp:<8} = {b:<3}"
                     f"// {r.label}, {r.frames} frame(s), "
                     f"${r.slots[0]:02X}-${r.slots[-1]:02X}")
    lines.append("")
    lines.append(f".const LVL_SPR_BLOCKS = {used}"
                 f"   // of {LEVEL_SPRITE_BLOCKS}")
    lines.append("")
    # A LIST, NOT `.byte`. src/level_package.asm imports this file twice -- once
    # for the constants above and once to emit the table at its own address --
    # so anything that emitted bytes here would land in both places. The list is
    # inert; the package decides where it goes.
    # WHICH SLOT BEHAVES HOW. Row offsets, so the engine compares one byte.
    drop = next((i * ENEMY_ANIM_STEPS for i, (r, _) in enumerate(layout)
                 if r.behaviour == BEHAVIOUR_DROPPER), 0xFF)
    plain = next((i * ENEMY_ANIM_STEPS for i, (r, _) in enumerate(layout)
                  if r.behaviour == BEHAVIOUR_PLAIN), 0)
    lines.append(f".const LVL_DROP_ROW  = ${drop:02x}"
                 + ("   // no identity here drops the token"
                    if drop == 0xFF else
                    f"   // {names[drop // ENEMY_ANIM_STEPS]} slot carries the token"))
    lines.append(f".const LVL_PLAIN_ROW = ${plain:02x}"
                 f"   // {names[plain // ENEMY_ANIM_STEPS]} slot, ordinary behaviour")
    lines.append("")
    lines.append(".var LVL_ANIM = List()")
    for (r, b), sp in zip(layout, names):
        row = ".".join(f"add({b + step})" for step in r.steps)
        lines.append(f"    .eval LVL_ANIM.{row}"
                     + f"   // {sp}: {r.label}")
    return "\n".join(lines) + "\n", layout, table


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
            f"{path} holds {len(f.sprites)} sprites; this project is expected "
            f"to hold {EXPECTED_SLOTS} ($00..$6D). Sprites appear to have been "
            f"inserted or removed rather than edited, which would silently "
            f"repoint every group below -- refusing to guess which is which")
    for slot in BLANK_SLOTS:
        if any(f.sprites[slot].bitmap):
            raise ImportError_(
                f"{path}: slot ${slot:02X} is expected to be blank but has "
                f"data. $0F is the player's deliberate HW1 blank and $6D is "
                f"the unused trailing slot")
    # EVERY BLOCK THIS IMPORTER ACTUALLY EMITS is checked, not just the Square:
    # a hires or empty block anywhere in a wired group is a mistake that would
    # otherwise only show up as a corrupt sprite on the screen.
    for g in ALL_GROUPS:
        for slot in g.slots:
            s = f.sprites[slot]
            if not any(s.bitmap):
                raise ImportError_(
                    f"{path}: ${slot:02X} is blank but {g.filename} needs art there")
            if not s.multicolour:
                raise ImportError_(
                    f"{path}: ${slot:02X} is hires; every gameplay sprite in "
                    f"this game is multicolour")
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
    for i, slot in enumerate(group.slots):
        s = spd.sprites[slot]
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
    for g in ALL_GROUPS:
        files[g.filename] = render(g, spd, digest)
    files['enemy_roster.asm'] = roster_constants(digest)
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
