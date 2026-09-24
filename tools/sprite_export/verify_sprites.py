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
SLOT_OF_GROUP = {
    "player_art_frames": 0,          # 0..14 art, 15 the blank
    "playerFlashBitmaps": 16,
    "tokenBitmap": 21,
    "playerBoomArt": 22,
    "sonicRingFrames": 30,
    "orbitalDropperFrames": 34,
    "squareFrames": 43,
    "bossArt": 38,
    "ebulletBitmap": 42,
}


def slot_for(sprite, group_index):
    return SLOT_OF_GROUP[sprite.group] + group_index


def verify():
    spd = spd_reader.read(SPD)
    sprites = src.extract()
    problems, compared, n = [], 0, 0

    group_pos = {}
    for s in sprites:
        i = group_pos.get(s.group, 0)
        group_pos[s.group] = i + 1
        slot = slot_for(s, i)
        want = bytes(spd.sprites[slot].bitmap)
        got = bytes(s.bitmap)
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
