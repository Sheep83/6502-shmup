#!/usr/bin/env python3
"""Semantic sprite identity: does logical sprite X actually resolve to X's graphic?

WHY THIS EXISTS, AND WHY THE OLD CHECK WAS NOT ENOUGH

The FIX 16 forensic added a "semantic pointer validity" check whose invariant
was, in effect:

    the pointer resolves somewhere inside the sprite bitmap allocation

That is far too weak, and P5 is exactly the kind of change that shows why. P5
added a kilobyte of ring tables at $2400 -- immediately above the bitmap pool at
$2000-$23FF and immediately below screen page B at $2800. Nothing overlapped,
but the pool is now bracketed by structured data on both sides, and a pointer
that was one block out would still have been "inside a defined allocation" under
several plausible relaxations of that rule. A pointer of $90 resolves to $2400,
which is a smooth coordinate ramp and renders as horizontal stripes.

So the invariant here is the strong one the P5/FIX16 regression brief asks for:

    logical sprite ID X resolves to the EXACT 64-byte block that holds X's
    diagnostic graphic, and that block still contains exactly the bytes the
    assembler put there.

INDEPENDENCE

The expected bytes come from the assembled PRG on disk, not from RAM and not
from a Python re-implementation of the KickAssembler font generator. Re-deriving
the glyphs in Python would only prove that two copies of the same logic agree;
reading the build artefact proves that what is in memory is what was built. A
bitmap silently overwritten at run time -- the P4 class of fault -- fails here,
and so does a pointer that names the wrong block.
"""
import hashlib
from pathlib import Path

SPRITE_BLOCK = 0x2000
SPRITE_COUNT = 16
SPRITE_PTR_FIRST = SPRITE_BLOCK // 64          # $80
BLOCK = 64


def prg_bitmaps(prg_path):
    """The sixteen 64-byte diagnostic bitmaps, as the assembler emitted them."""
    b = Path(prg_path).read_bytes()
    load = b[0] | (b[1] << 8)
    off = 2 + (SPRITE_BLOCK - load)
    pool = b[off:off + SPRITE_COUNT * BLOCK]
    if len(pool) != SPRITE_COUNT * BLOCK:
        raise AssertionError(f"PRG does not cover the sprite pool ({len(pool)} bytes)")
    return [pool[i * BLOCK:(i + 1) * BLOCK] for i in range(SPRITE_COUNT)]


def expected_pointer(logical_id):
    """The pointer byte logical sprite `logical_id` must carry.

    loadFixture wraps with AND, so logical IDs past the sixteenth repeat the
    graphics from the start. That wrap is deliberate and is why MAXCAP's thirty
    sprites only need sixteen bitmaps -- but it also means the check has to
    state the wrap explicitly rather than accept any pointer in range.
    """
    return SPRITE_PTR_FIRST + (logical_id & (SPRITE_COUNT - 1))


def check(rd_fn, ids, pointers, prg_path, label=""):
    """Verify identity for a set of accepted (logical id, pointer) pairs.

    `rd_fn(addr, n)` reads emulator memory. Returns a list of problems.
    """
    want = prg_bitmaps(prg_path)
    bad = []

    # 0. The graphics must be distinguishable at all. If two blocks were equal,
    #    a human could not tell a mis-pointed sprite from a correct one, and
    #    neither could this check.
    if len(set(want)) != SPRITE_COUNT:
        dup = [i for i in range(SPRITE_COUNT)
               if want.count(want[i]) > 1]
        bad.append(f"{label}: diagnostic bitmaps are not all distinct: blocks {dup}")

    # 1. Every block in RAM must still be byte-identical to the build artefact.
    for i in range(SPRITE_COUNT):
        got = bytes(rd_fn(SPRITE_BLOCK + i * BLOCK, BLOCK))
        if got != want[i]:
            n = sum(1 for a, b in zip(got, want[i]) if a != b)
            bad.append(f"{label}: bitmap {i} at ${SPRITE_BLOCK + i*BLOCK:04x} "
                       f"differs from the build in {n}/64 bytes "
                       f"(ram {hashlib.sha1(got).hexdigest()[:8]} "
                       f"vs prg {hashlib.sha1(want[i]).hexdigest()[:8]})")

    # 2. Every accepted entry must name its OWN block, exactly.
    for acc, (lid, ptr) in enumerate(zip(ids, pointers)):
        exp = expected_pointer(lid)
        if ptr != exp:
            bad.append(f"{label}: accepted {acc} is logical id {lid}, which must "
                       f"carry pointer ${exp:02x} (${SPRITE_BLOCK + (lid & 15)*BLOCK:04x}) "
                       f"but carries ${ptr:02x} (${ptr*BLOCK:04x})")
            continue
        addr = ptr * BLOCK
        if not (SPRITE_BLOCK <= addr < SPRITE_BLOCK + SPRITE_COUNT * BLOCK):
            bad.append(f"{label}: accepted {acc} pointer ${ptr:02x} resolves to "
                       f"${addr:04x}, outside the pool")
            continue
        got = bytes(rd_fn(addr, BLOCK))
        if got != want[lid & (SPRITE_COUNT - 1)]:
            bad.append(f"{label}: accepted {acc} (logical {lid}) reads the wrong "
                       f"graphic at ${addr:04x}")
    return bad
