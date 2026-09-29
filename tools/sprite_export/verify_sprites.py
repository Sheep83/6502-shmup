#!/usr/bin/env python3
"""Prove the built game draws exactly the artwork the .spd holds.

    python3 tools/sprite_export/verify_sprites.py

    assets/sprites/19656-sprites.spd   what Spritemate saved
        -> import_spd.py               -> src/generated_sprites/*.asm
        -> KickAssembler               -> build/shmup.prg
        -> sprite_source.extract()     the bytes at the symbols' addresses
        -> compared here, byte for byte

THIS REPLACED AN EXPORTER. While the .asm art was authoritative, the tool in
this directory ran the other way and WROTE the .spd from the program. The .spd
is the source of truth now, so a writer pointing back at it would be a second
editable copy of the same pixels -- the one thing the pipeline is meant to stop.
What is left is the half that is still worth having: an independent check that
the round trip did not lose or move a byte.

It also refreshes the manifest, which is documentation rather than data: names,
roles, addresses and the runtime-colour notes that SpritePad has nowhere to put.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sprite_source as src                                    # noqa: E402
import spd_reader                                              # noqa: E402
import import_spd                                              # noqa: E402

REPO = HERE.parent.parent
SPD = REPO / "assets" / "sprites" / "19656-sprites.spd"
MANIFEST = REPO / "assets" / "sprites" / "19656-sprites.json"

# Which .spd slot every extracted sprite came from. The extractor walks the
# program in address order; the .spd is in its own authored order, and slot 15
# (the player's blank HW1 block) is emitted by src/player.asm rather than
# imported, so the two sequences are not the same list.
# DERIVED, NOT REPEATED. This was a dictionary of literal slot numbers, which
# meant the SpritePad-index -> runtime-label mapping existed twice. When the
# project was reorganised the copy here went stale and stayed green, because the
# test that guarded it compared this stale dictionary against an equally stale
# literal list. Two wrong things agreeing is not a check. The mapping now comes
# from import_spd.GROUPS, which is the only place it is written down.
#
# A TUPLE PER GROUP, not a base index: the Ring's blocks are $60, $62, $64, $66,
# so "first slot + n" is not expressible and never was safe to assume.
SLOTS_OF_GROUP = import_spd.SLOTS_OF_SYMBOL


def slot_for(sprite, group_index):
    """The SpritePad slot behind one block, or None when the engine emitted it.

    The player's run is sixteen blocks and only fifteen come from the project:
    the last is playerBlankBitmap, which src/player.asm emits itself. Asking
    which SpritePad slot it came from has no answer, and returning one would be
    a lie rather than a lookup.
    """
    slots = SLOTS_OF_GROUP[sprite.group]
    return slots[group_index] if group_index < len(slots) else None


# ---------------------------------------------------------------------------
# THE LEVEL PACKAGES, which is where enemy and boss artwork actually lives now
# ---------------------------------------------------------------------------
# A package carries the twenty-block sprite window, the boss cells and a 24-byte
# animation table of window-relative blocks. This proves all three against the
# .spd and against each other:
#
#   * every block a level claims holds the exact SpritePad bytes of the artwork
#     that level chose, at the frame count that artwork actually has;
#   * the animation table only ever names blocks the package filled;
#   * each species' steps reach EVERY frame of its artwork -- the proof that no
#     sequence is being sampled or truncated any more;
#   * unchosen roster artwork occupies no block at all.
PKG_SPR = 0xE7D0                # LEVELPKG_SPR
PKG_BOSS = 0xECD0               # LEVELPKG_BOSS
PKG_ANIM = 0xFF93               # LEVELPKG_ANIM
PKG_ANIM_MAX = 24
BLOCK = 64


def _package_bytes(path):
    raw = Path(path).read_bytes()
    load = raw[0] | (raw[1] << 8)
    return raw[2:], load


def verify_package(path, choices):
    """(problems, blocks_used) for one built level package against the .spd."""
    spd = spd_reader.read(import_spd.SPD)
    body, load = _package_bytes(path)

    def at(addr, n):
        off = addr - load
        return body[off:off + n]

    layout, table = import_spd.level_sprite_plan(list(choices))
    problems = []
    used = sum(r.frames for r, _ in layout)

    # 1. every chosen frame is in its block, byte for byte
    for r, base in layout:
        for i, slot in enumerate(r.slots):
            got = at(PKG_SPR + (base + i) * BLOCK, 63)
            if bytes(got) != spd.sprites[slot].bitmap:
                problems.append(
                    f"{r.label} frame {i} (SpritePad ${slot:02X}) is not in "
                    f"window block {base + i}")

    # 2. the animation table is what the plan says, and names only filled blocks
    got_table = list(at(PKG_ANIM, PKG_ANIM_MAX))
    if got_table != table:
        problems.append(f"animation table is {got_table}, expected {table}")
    for i, blk in enumerate(got_table):
        if blk >= used:
            problems.append(
                f"animation entry {i} names block {blk}, but the package only "
                f"filled {used}")

    # 3. EVERY frame of every chosen sequence is reachable -- the no-truncation
    #    proof. A sampled sequence would leave some of its blocks unnamed.
    for idx, (r, base) in enumerate(layout):
        row = set(got_table[idx * 8:(idx + 1) * 8])
        want = set(range(base, base + r.frames))
        if row != want:
            missing = sorted(want - row)
            problems.append(
                f"{r.label} ({r.frames} frames) reaches blocks {sorted(row)}; "
                f"frames at blocks {missing} are never shown")

    # 4. nothing else occupies the window: unclaimed blocks are zeroed
    for blk in range(used, 20):
        if any(at(PKG_SPR + blk * BLOCK, 64)):
            problems.append(f"unclaimed window block {blk} is not zeroed")
    return problems, used


def verify_packages(packages):
    """{path: choices} -> (problems, {path: blocks}). Nothing is assumed."""
    problems, sizes = [], {}
    for path, choices in packages.items():
        if not Path(path).is_file():
            problems.append(f"{path} has not been built")
            continue
        probs, used = verify_package(path, choices)
        problems += [f"{Path(path).name}: {m}" for m in probs]
        sizes[str(path)] = used
    return problems, sizes


def verify():
    spd = spd_reader.read(SPD)
    sprites = src.extract()
    problems, compared, n = [], 0, 0

    group_pos = {}
    for s in sprites:
        i = group_pos.get(s.group, 0)
        group_pos[s.group] = i + 1
        slot = slot_for(s, i)
        got = bytes(s.bitmap)
        if slot is None:
            # The engine's own blank block. There is no .spd slot to compare it
            # with; what CAN be proved is that it really is blank, which is the
            # property src/player.asm depends on.
            n += 1
            if any(got):
                problems.append(f"{s.name}: the engine's blank block is not blank")
            else:
                compared += len(got)
            if s.pad != 0:
                problems.append(f"{s.name}: 64th byte is ${s.pad:02x}, not zero")
            continue
        want = bytes(spd.sprites[slot].bitmap)
        n += 1
        if got != want:
            bad = sum(1 for a, b in zip(got, want) if a != b)
            problems.append(f"{s.name} (slot {slot}): {bad}/63 bytes differ")
        else:
            compared += len(got)
        if s.pad != 0:
            problems.append(f"{s.name}: 64th byte is ${s.pad:02x}, not zero")
    return n, compared, problems, spd, sprites


def manifest(spd, sprites):
    group_pos = {}
    entries = []
    for s in sprites:
        i = group_pos.get(s.group, 0)
        group_pos[s.group] = i + 1
        slot = slot_for(s, i)
        entries.append({
            "spdSlot": slot,
            "name": s.name,
            "role": s.role,
            "sourceSymbol": s.source_symbol,
            "address": f"${s.address:04x}",
            "spritePointer": f"${s.pointer:02x}",
            "multicolour": s.multicolour,
            "spdEditingColour": spd.sprites[slot].colour,
            "runtimeColour": s.colour,
            "colourNote": s.colour_note,
            "blank": s.blank,
        })
    return {
        "sourceOfTruth": "assets/sprites/19656-sprites.spd",
        "editWith": "Spritemate (https://spritemate.com), SpritePad 2.0 format",
        "regenerate": "make sprites",
        "generatedInto": "src/generated_sprites/ -- never hand-edit",
        "spd": {
            "slots": len(spd.sprites),
            "establishedRoles": "0..42",
            "square": "43..46",
            "unusedTrailingSlot": 47,
            "background": spd.background,
            "multicolour1": spd.multicolour1,
            "multicolour2": spd.multicolour2,
        },
        "bitPairs": {
            "00": "transparent",
            "01": f"$d025 shared multicolour 1 = {src.SPR_MC_DARK} (dark grey)",
            "10": "this sprite's own $d027+n -- for enemies, the WAVE's colour",
            "11": f"$d026 shared multicolour 2 = {src.SPR_MC_LIGHT} (white)",
        },
        "colourModel": (
            "Three different things share the word colour. The BITMAP PAYLOAD is "
            "the 63 bytes and is authoritative. The SPD EDITING COLOUR is what "
            "Spritemate shows while drawing and reaches nothing at run time. The "
            "RUNTIME COLOUR is what the engine writes to $d027+n, and for the "
            "three enemy species it is the wave's authored colour, so one sprite "
            "appears in as many colours as there are waves using it."),
        "excluded": [
            {"symbol": s, "blocks": n, "role": r, "reason": why}
            for s, n, r, why in src.EXCLUDED
        ],
        "sprites": entries,
    }


def main():
    ok, msg = import_spd.check()
    print(f"  generated tree: {msg}")
    if not ok:
        print("  refusing to verify against a stale tree; run `make sprites`")
        return 1

    n, compared, problems, spd, sprites = verify()
    print(f"  payloads compared  {n}")
    print(f"  bytes compared     {compared}")
    print(f"  mismatches         {len(problems)}")
    for p in problems:
        print(f"    ! {p}")
    if problems:
        return 1

    MANIFEST.write_text(json.dumps(manifest(spd, sprites), indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"  wrote {MANIFEST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
