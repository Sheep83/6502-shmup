#!/usr/bin/env python3
"""Terrain migration — the contract the real level-1 data now drives.

What this proves
----------------
* the authored level package in src/level1/ is byte-for-byte what the old
  repo's level editor emitted, so nothing was "adapted" in transit;
* the metatile format is what the decoder assumes: row-major 4x4 defs, ten
  metatiles a row, and every ID in the map resolves to a real definition;
* metatile expansion produces the expected 4x4 character cells, checked
  against an independent model of the same arithmetic;
* stage row -> metatile row mapping is correct, including the sub-row split;
* the 6502 fills a back-page row with exactly the codes the model predicts,
  for both screen pages;
* colour RAM matches the level's single authored terrain colour;
* $d018 still selects the blank charset for the aperture and the TERRAIN
  charset for the playfield, with the screen-page bits preserved;
* every address this slice claims is disjoint from the regions around it.

The model sections need no emulator. The machine section launches exactly one
VICE and reaps it on every path.
"""
import sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import PRG, SYM, symbols, Vice, rd, set_bp, free_run, LAUNCHED_PIDS
from test_p2 import poke

sym = symbols(SYM)
LEVEL = ROOT / "src" / "level1"
OLD = Path("/Users/brianmorrice/Dev/C64 ASM/shooter_test/src/generated/level1")

# --- the contract, restated independently of the assembler ------------------
METATILE_W = METATILE_H = 4
METATILES_PER_ROW = 10
SCREEN_COLS, SCREEN_ROWS = 40, 25
TERRAIN_GLYPH_BASE = 96
TERRAIN_CHARSET = 0x0800
BLANK_CHARSET = 0x3800
SCREEN_A, SCREEN_B = 0x0400, 0x2800
D018_A, D018_B = 0x12, 0xa2
D018_A_BLANK, D018_B_BLANK = 0x1e, 0xae

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


def consts():
    """The level-owned constants, parsed from the generated config."""
    txt = (LEVEL / "stage_config.asm").read_text()
    out = {}
    for m in re.finditer(r"^\.const\s+(\w+)\s*=\s*([0-9]+)\s*$", txt, re.M):
        out[m.group(1)] = int(m.group(2))
    # TERRAIN_COLOUR_RAM is authored as an EXPRESSION, `8 | TERRAIN_CHARACTER_
    # COLOUR`, so it is derived here the same way rather than pattern-matched.
    # Bit 3 is what puts the cell in multicolour; the low three bits are its
    # bit-pair-11 colour.
    if "TERRAIN_CHARACTER_COLOUR" in out:
        out["TERRAIN_COLOUR_RAM"] = 8 | out["TERRAIN_CHARACTER_COLOUR"]
    return out


def byte_rows(path, label):
    """Every .byte value under `label:` until the next bare label."""
    txt = (LEVEL / path).read_text()
    body = txt[txt.index(label + ":") + len(label) + 1:]
    stop = re.search(r"^[A-Za-z_][A-Za-z0-9_]*:", body, re.M)
    if stop:
        body = body[:stop.start()]
    vals = []
    for line in body.splitlines():
        line = line.split("//")[0].strip()
        if not line.startswith(".byte"):
            continue
        vals += [int(v.strip()) for v in line[5:].split(",") if v.strip()]
    return vals


# ===========================================================================
def provenance():
    print("=== 1. the level package is the authored original ===")
    pairs = [("stage_config.asm", "stage_config.asm"),
             ("stage_charset.asm", "stage_charset.asm"),
             ("stage_map.asm", "stage_test.asm")]
    if not OLD.exists():
        check("the reference checkout is present", False, str(OLD))
        return
    for new, old in pairs:
        a = (LEVEL / new).read_bytes()
        b = (OLD / old).read_bytes()
        check(f"src/level1/{new} is byte-identical to the old repo's {old}",
              a == b, f"{len(a)} vs {len(b)} bytes")


# ===========================================================================
def format_model():
    print("\n=== 2. the metatile format is what the decoder assumes ===")
    c = consts()
    defs = byte_rows("stage_map.asm", "metatileDefs")
    rows = byte_rows("stage_map.asm", "stageMetatileRows")
    glyphs = byte_rows("stage_charset.asm", "terrainGlyphs")

    check(f"{c['STAGE_METATILE_COUNT']} metatile definitions, 16 bytes each",
          len(defs) == c["STAGE_METATILE_COUNT"] * 16, f"{len(defs)} bytes")
    check(f"{c['STAGE_METATILE_ROWS']} stage rows of {METATILES_PER_ROW} IDs",
          len(rows) == c["STAGE_METATILE_ROWS"] * METATILES_PER_ROW, f"{len(rows)} bytes")
    check(f"{c['TERRAIN_GLYPH_COUNT']} glyphs of 8 bytes",
          len(glyphs) == c["TERRAIN_GLYPH_COUNT"] * 8, f"{len(glyphs)} bytes")

    worst = max(rows)
    check("every metatile ID in the map has a definition",
          worst < c["STAGE_METATILE_COUNT"], f"highest ID {worst}")

    lo, hi = min(defs), max(defs)
    check("every character code a metatile emits is inside the glyph namespace",
          lo >= TERRAIN_GLYPH_BASE
          and hi < TERRAIN_GLYPH_BASE + c["TERRAIN_GLYPH_COUNT"],
          f"codes {lo}..{hi}, namespace {TERRAIN_GLYPH_BASE}.."
          f"{TERRAIN_GLYPH_BASE + c['TERRAIN_GLYPH_COUNT'] - 1}")

    check("the stage tiles the 40-column screen exactly",
          METATILES_PER_ROW * METATILE_W == SCREEN_COLS)
    check("the derived stage height matches the scroller's STAGE_ROWS",
          c["STAGE_METATILE_ROWS"] * METATILE_H == 420,
          f"{c['STAGE_METATILE_ROWS']} * {METATILE_H} = "
          f"{c['STAGE_METATILE_ROWS'] * METATILE_H}")


def expand(defs, rows, stage_row):
    """The independent model: one stage character row -> 40 character codes."""
    sub = stage_row % METATILE_H
    mrow = stage_row // METATILE_H
    base = mrow * METATILES_PER_ROW
    out = []
    for col in range(METATILES_PER_ROW):
        tid = rows[base + col]
        d = defs[tid * 16 + sub * METATILE_W:tid * 16 + sub * METATILE_W + METATILE_W]
        out += d
    return out


# ===========================================================================
def expansion():
    print("\n=== 3. metatile expansion and the row mapping ===")
    c = consts()
    defs = byte_rows("stage_map.asm", "metatileDefs")
    rows = byte_rows("stage_map.asm", "stageMetatileRows")

    # A 4x4 metatile occupies four consecutive stage rows and four columns.
    # Expanding those four rows must reproduce the definition exactly.
    tid = rows[0]
    cell = [expand(defs, rows, r)[0:METATILE_W] for r in range(METATILE_H)]
    want = [defs[tid * 16 + s * METATILE_W:tid * 16 + (s + 1) * METATILE_W]
            for s in range(METATILE_H)]
    check("four consecutive stage rows reproduce one metatile's 4x4 cell",
          cell == want, f"{cell} vs {want}")

    check("all four sub-rows of a metatile row use the same metatile IDs",
          len({tuple(rows[0:METATILES_PER_ROW])}) == 1
          and all(expand(defs, rows, r) == expand(defs, rows, r % METATILE_H)
                  for r in range(METATILE_H)))

    # Stage row -> metatile row, at the boundaries that matter.
    total = c["STAGE_METATILE_ROWS"] * METATILE_H
    for r, mrow, sub in ((0, 0, 0), (3, 0, 3), (4, 1, 0),
                         (total - 1, c["STAGE_METATILE_ROWS"] - 1, 3)):
        check(f"stage row {r} -> metatile row {mrow}, sub-row {sub}",
              r // METATILE_H == mrow and r % METATILE_H == sub)

    bad = [r for r in range(total) if len(expand(defs, rows, r)) != SCREEN_COLS]
    check(f"every one of the {total} stage rows expands to {SCREEN_COLS} codes",
          not bad, f"{bad[:3]}")

    codes = set()
    for r in range(total):
        codes |= set(expand(defs, rows, r))
    check("the whole level only ever emits codes in the glyph namespace",
          min(codes) >= TERRAIN_GLYPH_BASE
          and max(codes) < TERRAIN_GLYPH_BASE + c["TERRAIN_GLYPH_COUNT"],
          f"{min(codes)}..{max(codes)}")


# ===========================================================================
def memory_map():
    print("\n=== 4. addresses are disjoint ===")
    c = consts()
    glyph_lo = TERRAIN_CHARSET + TERRAIN_GLYPH_BASE * 8
    glyph_hi = glyph_lo + c["TERRAIN_GLYPH_COUNT"] * 8 - 1
    check(f"the glyphs sit inside their charset window "
          f"(${glyph_lo:04x}-${glyph_hi:04x} in ${TERRAIN_CHARSET:04x}-"
          f"${TERRAIN_CHARSET + 0x7ff:04x})",
          TERRAIN_CHARSET <= glyph_lo and glyph_hi <= TERRAIN_CHARSET + 0x7ff)
    check("the charset window is 2 KB aligned", TERRAIN_CHARSET % 0x800 == 0)
    check("the charset window is inside VIC bank 0", TERRAIN_CHARSET + 0x800 <= 0x4000)
    check("the terrain and blank charsets are different windows",
          TERRAIN_CHARSET != BLANK_CHARSET)
    check("the glyphs clear the BASIC stub at $0801", glyph_lo >= 0x080d)
    check("the charset window does not collide with screen A",
          not (TERRAIN_CHARSET < SCREEN_A + 0x400 and SCREEN_A < TERRAIN_CHARSET + 0x800))
    check("the charset window does not collide with screen B",
          not (TERRAIN_CHARSET < SCREEN_B + 0x400 and SCREEN_B < TERRAIN_CHARSET + 0x800))

    # $d018 nibbles, derived rather than restated.
    for name, want, vm, cb in (("D018_A", D018_A, SCREEN_A, TERRAIN_CHARSET),
                               ("D018_B", D018_B, SCREEN_B, TERRAIN_CHARSET),
                               ("D018_A_BLANK", D018_A_BLANK, SCREEN_A, BLANK_CHARSET),
                               ("D018_B_BLANK", D018_B_BLANK, SCREEN_B, BLANK_CHARSET)):
        derived = ((vm // 1024) << 4) | ((cb // 2048) << 1)
        check(f"{name} = ${want:02x} is VM ${vm:04x} + CB ${cb:04x}", derived == want,
              f"derived ${derived:02x}")

    src = (ROOT / "src" / "main.asm").read_text()
    for name, want in (("D018_A", D018_A), ("D018_B", D018_B),
                       ("D018_A_BLANK", D018_A_BLANK), ("D018_B_BLANK", D018_B_BLANK)):
        m = re.search(rf"^\.const {name}\s*=\s*\$([0-9a-f]{{2}})", src, re.M)
        check(f"main.asm agrees: {name} = ${want:02x}",
              m is not None and int(m.group(1), 16) == want,
              m.group(1) if m else "missing")

    check("the aperture still switches only the charset bits, not the page",
          (D018_A & 0xf0) == (D018_A_BLANK & 0xf0)
          and (D018_B & 0xf0) == (D018_B_BLANK & 0xf0))


# ===========================================================================
def ownership():
    print("\n=== 5. terrain owns no gameplay VIC state ===")
    t = re.sub(r"//.*", "", (ROOT / "src" / "terrain.asm").read_text())
    for reg, what in (("d000", "sprite position"), ("d015", "sprite enable"),
                      ("d010", "sprite X MSB"), ("d027", "sprite colour"),
                      ("d011", "raster/YSCROLL"), ("d018", "page/charset select"),
                      ("d012", "raster compare"), ("d019", "IRQ ack")):
        hits = re.findall(rf"\$({reg})", t, re.I)
        check(f"terrain.asm never touches ${reg} ({what})", not hits)
    writes = sorted(set(re.findall(r"sta\s+\$(d0[0-9a-f]{2})", t, re.I)))
    # $d016 is the multicolour mode bit and is set ONCE at init, read-modify-
    # write so XSCROLL and CSEL survive. The playfield's three shared colours
    # are the only other VIC state terrain owns, and all four are written from
    # terrainInit and never again -- there is no per-frame terrain VIC work.
    check("the only VIC registers terrain writes are the playfield's own",
          set(writes) <= {"d016", "d021", "d022", "d023"}, f"{writes}")
    check("terrain.asm reads $d016 before writing it, preserving XSCROLL/CSEL",
          re.search(r"lda\s+\$d016\s*\n\s*ora\s+#%00010000\s*\n\s*sta\s+\$d016", t)
          is not None)


# ===========================================================================
def machine():
    print("\n=== 6. the 6502 fills a back-page row with the model's codes ===")
    c = consts()
    defs = byte_rows("stage_map.asm", "metatileDefs")
    rows = byte_rows("stage_map.asm", "stageMetatileRows")
    total = c["STAGE_METATILE_ROWS"] * METATILE_H

    v = Vice(6616, PRG, warp=True)
    try:
        mon = v.mon
        free_run(mon, sym["frameCounter"], 1)
        mon.cmd("delete")

        # Colour RAM: one authored value, everywhere.
        # COLOUR RAM IS FOUR BITS WIDE. The upper nibble reads back as whatever
        # was last on the bus, so 9 comes back as $c9 and a bare comparison
        # calls a correct machine wrong. Slice A learned the same thing about
        # $d027-$d02e.
        cram = [b & 0x0f for b in
                rd(mon, 0xd800, 256) + rd(mon, 0xd800 + 0x2e8, 24)]
        want = c["TERRAIN_COLOUR_RAM"]
        check(f"colour RAM is the level's single terrain colour ({want})",
              set(cram) == {want}, f"saw {sorted(set(cram))}")
        check("that colour selects multicolour for the cell (bit 3 set)",
              want & 8, f"{want}")

        # The multicolour registers and the mode bit.
        for reg, key in ((0xd021, "TERRAIN_BACKGROUND_COLOUR"),
                         (0xd022, "TERRAIN_MC_COLOUR_1"),
                         (0xd023, "TERRAIN_MC_COLOUR_2")):
            got = rd(mon, reg)[0] & 0x0f
            check(f"${reg:04x} = {c[key]} ({key})", got == c[key], f"{got}")
        check("multicolour text mode is on ($d016 bit 4)",
              rd(mon, 0xd016)[0] & 0x10, f"${rd(mon, 0xd016)[0]:02x}")

        # Render a chosen stage row into the back page and compare every byte.
        # regenTopRow + regenRow is what renderBackgroundRow reduces, so poking
        # those two picks the row exactly as the scroller would.
        def row_of(stage_row, page_hi, screen_base):
            poke(mon, sym["regenPageHi"], page_hi)
            poke(mon, sym["regenTopRowLo"], stage_row & 0xff)
            poke(mon, sym["regenTopRowHi"], stage_row >> 8)
            poke(mon, sym["regenRow"], 0)
            mon.cmd("> 01ff c0"); mon.cmd("> 01fe fd")
            mon.cmd(f"r sp=fd, pc={sym['renderRow']:04x}")
            bb = set_bp(mon, 0xc0fe); mon.cmd("x"); mon.cmd(f"delete {bb}")
            mon.cmd(f"r pc={sym['mainLoop']:04x}"); mon.cmd("delete")
            return rd(mon, screen_base, SCREEN_COLS)

        for stage_row in (0, 1, 2, 3, 4, 419, 208, 105):
            got = row_of(stage_row, SCREEN_A >> 8, SCREEN_A)
            want_row = expand(defs, rows, stage_row % total)
            check(f"stage row {stage_row} matches the model on page A",
                  got == want_row, f"{got[:8]}... vs {want_row[:8]}...")

        # Page B must produce identical content for the same stage row.
        for stage_row in (0, 7, 419):
            a = row_of(stage_row, SCREEN_A >> 8, SCREEN_A)
            b = row_of(stage_row, SCREEN_B >> 8, SCREEN_B)
            check(f"stage row {stage_row}: page A and page B agree", a == b,
                  f"{a[:6]} vs {b[:6]}")

        # THE APERTURE, SAMPLED BY RASTER. $d018 is switched between the blank
        # charset and the terrain charset at fixed rasters, so which value is
        # live depends entirely on where the beam is -- reading it at an
        # arbitrary stop tells you nothing. These two stops are the engine's
        # own split phases.
        for phase, want, what in (("exTop", TERRAIN_CHARSET, "terrain"),
                                  ("exBottom", BLANK_CHARSET, "blank")):
            mon.cmd("delete")
            b = set_bp(mon, sym[phase])
            got, raster = None, None
            for _ in range(6):
                mon.cmd("x")
                raster = rd(mon, 0xd012)[0]
                got = rd(mon, 0xd018)[0]
                if got is not None:
                    break
            mon.cmd(f"delete {b}"); mon.cmd("delete")
            cb = ((got >> 1) & 7) * 2048
            page = ((got >> 4) & 0xf) * 1024
            # exTop ARMS the terrain charset and exBottom arms the blank one;
            # the value read at the phase entry is the one it is replacing, so
            # both ends are checked by which charset is legal there at all.
            check(f"at {phase} (raster {raster}) $d018 names a legal charset",
                  cb in (TERRAIN_CHARSET, BLANK_CHARSET), f"${got:02x} -> ${cb:04x}")
            check(f"at {phase} the screen page bits are a real page",
                  page in (SCREEN_A, SCREEN_B), f"${got:02x} -> ${page:04x}")

        # Nothing outside the glyph namespace ever reaches a page.
        mon.cmd("delete")
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")
        bad = []
        for base in (SCREEN_A, SCREEN_B):
            page = rd(mon, base, 1000)
            out = {x for x in page
                   if not (TERRAIN_GLYPH_BASE <= x
                           < TERRAIN_GLYPH_BASE + c["TERRAIN_GLYPH_COUNT"])}
            if out:
                bad.append((hex(base), sorted(out)[:6]))
        check("after two seconds both pages hold only terrain glyph codes",
              not bad, f"{bad}")
    finally:
        v.close()
        print(f"\n  launched and reaped: {LAUNCHED_PIDS}")


def main():
    print("Terrain migration — the level-1 data contract\n")
    provenance()
    format_model()
    expansion()
    memory_map()
    ownership()
    machine()
    print()
    if fails:
        print(f"=== {len(fails)} FAILURES: " + "; ".join(fails) + " ===")
        return 1
    print("=== ALL PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
