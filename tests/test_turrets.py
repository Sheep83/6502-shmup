#!/usr/bin/env python3
"""Static turret presentation, and the black open border.

What this proves
----------------
* the authored placement layer in src/level1/stage_turrets.asm is byte-for-byte
  what the old repo's level editor emitted, and the body art is byte-for-byte
  the old repo's turretArt style TURRET_STATIC_STYLE;
* the count and every position match the old reference exactly -- eight
  turrets, at the authored rows and columns, not remembered ones;
* the editor's world rule (row = metatileRow*4+1) holds for every authored
  turret, which is what the row renderer's fast rejection depends on;
* the authored world position maps to the generated character cells the old
  installTurretRow wrote: TL/TR on the authored row, BL/BR on the row below;
* the 6502 composes exactly those cells into a hidden page and NOTHING ELSE:
  the rows either side are pure terrain, and both screen pages agree;
* the underlying terrain is recoverable -- clearing a turret's alive byte makes
  the next regeneration produce the terrain that was always underneath, with
  no repair, no cached codes and no second copy of the map;
* colour RAM is untouched by turrets: still the level's one authored value;
* turrets consume no sprite, no logical object, no mux batch and no sprite
  bitmap storage, and write no VIC register;
* $d021 is APERTURE STATE: black in the open top and bottom border, the
  level's authored background inside the playfield, switched by raster.

The model sections need no emulator. The machine section launches exactly one
VICE and reaps it on every path.
"""
import sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_p0 import PRG, SYM, symbols, Vice, rd, set_bp, free_run, LAUNCHED_PIDS
from test_p2 import poke
import test_terrain as T
import turret_model as TM
import old_repo

sym = symbols(SYM)
DEFS = T.byte_rows("stage_map.asm", "metatileDefs")
ROWS = T.byte_rows("stage_map.asm", "stageMetatileRows")

# --- the contract, restated independently of the assembler ------------------
METATILE_H = 4
SCREEN_COLS, SCREEN_ROWS = 40, 25
STAGE_ROWS = 420
SCREEN_A, SCREEN_B = 0x0400, 0x2800
PTR_A, PTR_B = 0x07f8, 0x2bf8
TERRAIN_CHARSET = 0x0800
TURRET_GLYPH_BASE = 226
TURRET_GLYPH_SPAN = 4
TURRET_NONE = 0xff
TURRET_GLYPHS = TERRAIN_CHARSET + TURRET_GLYPH_BASE * 8

# The authoritative old values, as the archive states them. Every one of these
# is CHECKED against the archive below rather than trusted.
OLD_TOTAL = 8
OLD_COLS = [17, 25, 29, 9, 25, 13, 25, 13]
OLD_ROWS = [345, 337, 225, 217, 117, 109, 25, 5]

# The aperture. $d021 is black outside it and the level's colour inside.
BORDER_D021 = 0
APERTURE_D021 = 12                      # TERRAIN_BACKGROUND_COLOUR
TOP_SPLIT_LINE, BOT_SPLIT_LINE = 55, 248

fails = []
def check(label, ok, extra=""):
    if not ok:
        fails.append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + extra) if extra else ''}")


# ===========================================================================
def provenance():
    print("=== 1. the authored data and the art are the old repo's own ===")
    if not old_repo.present():
        check("the reference archive is present", False, str(old_repo.ARCHIVE))
        return
    ours = (ROOT / "src" / "level1" / "stage_turrets.asm").read_bytes()
    theirs = old_repo.old_bytes("src/generated/level1/stage_turrets.asm")
    check("src/level1/stage_turrets.asm is byte-identical to the old repo's",
          ours == theirs, f"{len(ours)} vs {len(theirs)} bytes")

    old = old_repo.old_text("src/background_turrets.asm")

    # The glyph base and span, from the old engine rather than from memory.
    m = re.search(r"\.const\s+TURRET_GLYPH_BASE\s*=\s*(\d+)", old)
    check(f"the old engine's TURRET_GLYPH_BASE is {TURRET_GLYPH_BASE}",
          m and int(m.group(1)) == TURRET_GLYPH_BASE, m.group(1) if m else "?")
    m = re.search(r"\.const\s+TURRET_GLYPH_SPAN\s*=\s*(\d+)", old)
    check(f"the shared body is {TURRET_GLYPH_SPAN} character codes",
          m and int(m.group(1)) == TURRET_GLYPH_SPAN, m.group(1) if m else "?")
    m = re.search(r"\.const\s+TURRET_STATIC_STYLE\s*=\s*(\d+)", old)
    style = int(m.group(1)) if m else None
    check("the shared body is turretArt style 4 (down-facing)", style == 4,
          str(style))

    # The 32 bytes of that style, sliced out of the old turretArt table.
    body = old[old.index("turretArt:"):old.index("turretArtEnd:")]
    art = []
    for line in body.splitlines():
        line = line.split("//")[0].strip()
        if line.startswith(".byte"):
            art += [int(v.strip().lstrip("$"), 16)
                    for v in line[5:].split(",") if v.strip()]
    check("the old turretArt table holds seven 16x16 bodies",
          len(art) == 7 * 32, f"{len(art)} bytes")
    want = art[style * 32:(style + 1) * 32] if style is not None else []

    ours_asm = (ROOT / "src" / "turrets.asm").read_text()
    blk = ours_asm[ours_asm.index("turretGlyphs:"):ours_asm.index("turretGlyphsEnd:")]
    got = []
    for line in blk.splitlines():
        line = line.split("//")[0].strip()
        if line.startswith(".byte"):
            got += [int(v.strip().lstrip("$"), 16)
                    for v in line[5:].split(",") if v.strip()]
    check("src/turrets.asm's body bitmaps are that style, byte for byte",
          got == want, f"{got[:4]}... vs {want[:4]}...")

    # The 2x2 code layout, read out of the old installTurretRow rather than
    # assumed: the authored row takes GLYPH_BASE, the row after it +2, and each
    # writes that code and code+1 into column C and C+1.
    inst = old[old.index("installTurretRow:"):]
    inst = inst[:inst.index("publishTurretGlyphs:")]
    check("installTurretRow puts TURRET_GLYPH_BASE on the authored row",
          re.search(r"lda #TURRET_GLYPH_BASE\s*(//[^\n]*)?\s*\n\s*jmp", inst)
          is not None)
    check("installTurretRow puts TURRET_GLYPH_BASE + 2 on the row after it",
          "lda #TURRET_GLYPH_BASE + 2" in inst)
    check("each half writes code then code+1 into column C and C+1",
          re.search(r"sta \(TEXT_DST\),y\s*\n\s*clc\s*\n\s*adc #1\s*\n\s*iny"
                    r"\s*\n\s*sta \(TEXT_DST\),y", inst) is not None)


# ===========================================================================
def authored():
    print("\n=== 2. the authored placement: count, rows, columns ===")
    total, cols, rows = TM.authored()
    check(f"TURRET_TOTAL is {OLD_TOTAL}", total == OLD_TOTAL, str(total))
    check("the authored columns are the old repo's", cols == OLD_COLS, str(cols))
    check("the authored world rows are the old repo's", rows == OLD_ROWS, str(rows))
    check("both lists are TURRET_TOTAL long",
          len(cols) == total and len(rows) == total)

    # The editor's own documented rule, which the row renderer's fast rejection
    # is built on. If this ever stopped holding the assembler would refuse to
    # build; checking it here says WHY the build would refuse.
    bad = [r for r in rows if r % METATILE_H != TM.ROW_PHASE]
    check("every authored row is metatileRow * 4 + 1", not bad, str(bad))
    bad = [c for c in cols if c % METATILE_H != 1]
    check("every authored column is metatileCol * 4 + 1", not bad, str(bad))

    # A body is 2x2 and must fit the map and the screen.
    bad = [r for r in rows if r + TM.BODY_H - 1 >= STAGE_ROWS]
    check("every body fits inside the stage", not bad, str(bad))
    bad = [c for c in cols if c + TM.BODY_W > SCREEN_COLS]
    check("every body fits inside the 40 columns", not bad, str(bad))

    # A body occupies sub-rows 1 and 2 of ONE metatile row, so it can never
    # straddle a metatile boundary and the scan never needs two matches.
    subs = sorted({(r + h) % METATILE_H for r in rows for h in range(TM.BODY_H)})
    check("a body only ever occupies sub-rows 1 and 2", subs == [1, 2], str(subs))
    metas = [r // METATILE_H for r in rows]
    check("no two turrets share a metatile row",
          len(set(metas)) == len(metas), str(sorted(metas)))
    check("every metatile row fits one byte", max(metas) < 256, str(max(metas)))

    # The old engine's own placement guard: descending and at least 2 apart.
    check("the authored rows are sorted DESCENDING, at least 2 apart",
          all(rows[i - 1] - rows[i] >= 2 for i in range(1, len(rows))),
          str([rows[i - 1] - rows[i] for i in range(1, len(rows))]))


# ===========================================================================
def mapping():
    print("\n=== 3. world position -> generated cell ===")
    total, cols, rows = TM.authored()

    # Row R is the TOP half, R+1 the bottom, C the left column.
    for i in (7, 6, 0):
        r, c = rows[i], cols[i]
        top = TM.cells(r)
        bot = TM.cells(r + 1)
        check(f"turret {i} at world row {r}, col {c}: top row is TL/TR",
              top == [(c, 226), (c + 1, 227)], str(top))
        check(f"turret {i}: the row below is BL/BR",
              bot == [(c, 228), (c + 1, 229)], str(bot))
        check(f"turret {i}: the rows either side carry no turret cell",
              TM.cells(r - 1) == [] and TM.cells(r + 2) == [])

    # Exactly 2 * TURRET_TOTAL stage rows in the whole level carry a body.
    carry = [s for s in range(STAGE_ROWS) if TM.cells(s)]
    check(f"exactly {2 * total} of the {STAGE_ROWS} stage rows carry a body",
          len(carry) == 2 * total, f"{len(carry)}")
    check("and every one of them writes exactly two cells",
          all(len(TM.cells(s)) == 2 for s in carry))

    # worldProgress -> stageTopRow -> matrix row. The engine contract's own
    # relation, applied to a turret, so the mapping is stated once and shared.
    START = STAGE_ROWS - SCREEN_ROWS
    def matrix_row(stage_row, progress):
        top = (START - progress) % STAGE_ROWS
        return (stage_row - top) % STAGE_ROWS
    # The playfield scrolls DOWNWARD: stageTopRow decreases as worldProgress
    # increases, so a turret ENTERS at matrix row 0 and walks down to row 24.
    r = rows[0]                                     # 345, the first to appear
    prog = (START - r) % STAGE_ROWS
    check(f"turret 0's world row {r} enters at matrix row 0 at worldProgress "
          f"{prog}", matrix_row(r, prog) == 0)
    check("...is not on the aperture one coarse step earlier",
          matrix_row(r, prog - 1) >= SCREEN_ROWS)
    check("...reaches matrix row 24 twenty-four coarse steps later",
          matrix_row(r, prog + SCREEN_ROWS - 1) == SCREEN_ROWS - 1)
    check("...and has left the aperture the step after that",
          matrix_row(r, prog + SCREEN_ROWS) >= SCREEN_ROWS)


# ===========================================================================
def memory_map():
    print("\n=== 4. glyph codes, the charset window and the namespaces ===")
    c = T.consts()
    tg_lo, tg_hi = TURRET_GLYPHS, TURRET_GLYPHS + TURRET_GLYPH_SPAN * 8 - 1
    terr_lo = TERRAIN_CHARSET + T.TERRAIN_GLYPH_BASE * 8
    terr_hi = terr_lo + c["TERRAIN_GLYPH_COUNT"] * 8 - 1

    check(f"the turret glyphs sit inside the terrain charset window "
          f"(${tg_lo:04x}-${tg_hi:04x})",
          TERRAIN_CHARSET <= tg_lo and tg_hi <= TERRAIN_CHARSET + 0x7ff)
    check("they do not overlap the terrain glyph bitmaps",
          tg_lo > terr_hi, f"terrain ends ${terr_hi:04x}")
    check("their codes are outside the terrain glyph namespace",
          TURRET_GLYPH_BASE >= T.TERRAIN_GLYPH_BASE + c["TERRAIN_GLYPH_COUNT"],
          f"terrain 96..{T.TERRAIN_GLYPH_BASE + c['TERRAIN_GLYPH_COUNT'] - 1}")
    check("their codes fit in a byte", TURRET_GLYPH_BASE + TURRET_GLYPH_SPAN <= 256)
    check("the blank aperture charset is a different window entirely",
          TERRAIN_CHARSET != T.BLANK_CHARSET)

    # The assembler's own segments, from the symbol file: turret code, tables
    # and state are all outside VIC bank 0 -- only the bitmaps are inside it.
    for name in ("turretInit", "turretOverlayRow", "turretMetaRow",
                 "turretCol", "turretAlive"):
        check(f"{name} lives outside VIC bank 0", sym[name] >= 0x4000,
              f"${sym[name]:04x}")
    check("only the body bitmaps are inside bank 0, in the charset window",
          sym["turretGlyphs"] == TURRET_GLYPHS, f"${sym['turretGlyphs']:04x}")


# ===========================================================================
def ownership():
    print("\n=== 5. turrets consume no sprite or object resource ===")
    src = re.sub(r"//.*", "", (ROOT / "src" / "turrets.asm").read_text())

    writes = sorted(set(re.findall(r"st[axy]\s+\$(d0[0-9a-f]{2})", src, re.I)))
    check("turrets.asm writes NO VIC register at all", not writes, str(writes))
    reads = sorted(set(re.findall(r"\$(d0[0-9a-f]{2})", src, re.I)))
    check("turrets.asm does not even name one", not reads, str(reads))
    check("and no colour RAM either", "d800" not in src.lower())

    # The sprite and logical-object namespaces, by symbol. A turret that
    # allocated an object or named a hardware slot would show up here.
    for token in ("objectAlloc", "objectActivate", "objectFree", "logActive",
                  "logCount", "logY", "logX", "logPtr", "logCol", "sortedIDs",
                  "schedule", "batch", "HW_", "MUX_", "SPRITE", "spritePtr"):
        check(f"turrets.asm never mentions {token}", token not in src)

    # And the composition point is the hidden page, not the visible screen.
    scroll = (ROOT / "src" / "scroll.asm").read_text()
    check("the overlay is called from renderBackgroundRow, during hidden-page "
          "generation", re.search(r"jsr renderTerrainRow\s*\n\s*jmp "
                                  r"turretOverlayRow", scroll) is not None)
    check("no game system pokes a screen page directly",
          "turretOverlayRow" not in (ROOT / "src" / "main.asm").read_text())


# ===========================================================================
def machine():
    print("\n=== 6. the 6502, the pages and the aperture ===")
    total, cols, rows = TM.authored()

    v = Vice(6617, PRG, warp=True)
    try:
        mon = v.mon

        # ---------------------------------------------------------------
        # THE ENGINE'S OWN INSTRUMENTATION, READ FIRST AND ON A CLEAN
        # MACHINE. It has to be first: the row harness further down hijacks
        # the PC into renderRow about thirty times and leaves regenRow
        # mid-page, which is exactly the shape of interference that makes a
        # scroller report a late back page and a skipped publication. Those
        # counters are meaningless after it has run, and reading them there
        # would have been this project's fourth green-instrument-that-lies.
        # ---------------------------------------------------------------
        free_run(mon, sym["frameCounter"], 3)
        mon.cmd("delete")
        tmin, tmax = rd(mon, sym["topSplitMin"])[0], rd(mon, sym["topSplitMax"])[0]
        bmin, bmax = rd(mon, sym["botSplitMin"])[0], rd(mon, sym["botSplitMax"])[0]
        late = rd(mon, sym["edgeLate"])[0]
        check(f"the top split still lands on {TOP_SPLIT_LINE - 1}.."
              f"{TOP_SPLIT_LINE}",
              TOP_SPLIT_LINE - 1 <= tmin and tmax <= TOP_SPLIT_LINE,
              f"{tmin}..{tmax}")
        check(f"the bottom split still lands on {BOT_SPLIT_LINE}",
              bmin == bmax == BOT_SPLIT_LINE, f"{bmin}..{bmax}")
        check("no aperture edge arrived late", late == 0, f"edgeLate {late}")
        for name in ("gameOverrun", "publishSkip", "scrollLate"):
            got = rd(mon, sym[name])[0]
            check(f"{name} is zero with the overlay composing", got == 0, str(got))

        # --- the tables the assembler derived from the authored lists -------
        atrow = rd(mon, sym["turretAtMetaRow"], 105)
        want_atrow = [TURRET_NONE] * 105
        for i, r in enumerate(rows):
            want_atrow[r // METATILE_H] = i
        check("turretAtMetaRow names the right turret in the right metatile "
              "row, and TURRET_NONE everywhere else",
              atrow == want_atrow,
              f"{[(j, v) for j, v in enumerate(atrow) if v != TURRET_NONE]}")
        check(f"exactly {total} of the 105 metatile rows carry a turret",
              sum(1 for v in atrow if v != TURRET_NONE) == total)

        meta = rd(mon, sym["turretMetaRow"], total)
        col = rd(mon, sym["turretCol"], total)
        alive = rd(mon, sym["turretAlive"], total)
        check("turretMetaRow is the authored rows divided by the metatile "
              "height", meta == [r // METATILE_H for r in rows], str(meta))
        check("turretCol is the authored columns", col == cols, str(col))
        check("every authored turret boots alive", alive == [1] * total, str(alive))

        # --- the body bitmaps really loaded where the charset expects them --
        art = rd(mon, TURRET_GLYPHS, TURRET_GLYPH_SPAN * 8)
        want_art = [0x00, 0x00, 0x0f, 0x3f, 0xff, 0xff, 0xff, 0xff,
                    0x00, 0x00, 0xf0, 0xfc, 0xff, 0xff, 0xff, 0xff,
                    0xff, 0xff, 0xff, 0x55, 0x55, 0x15, 0x02, 0x02,
                    0xff, 0xff, 0xff, 0x55, 0x55, 0x54, 0x80, 0x80]
        check(f"the four body glyphs are resident at ${TURRET_GLYPHS:04x}",
              art == want_art, f"{art[:4]}...")

        # --- one generated row at a time, against the model -----------------
        # Exactly test_terrain's harness: poking regenTopRow/regenRow picks the
        # stage row the way the scroller would, and renderRow is the whole
        # composition path -- terrain decode and then the overlay.
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

        def terrain_of(stage_row):
            return T.expand(DEFS, ROWS, stage_row % STAGE_ROWS)

        # Three turrets, across the map: the first authored, one in the middle
        # and the one the boot aperture is nowhere near.
        for i in (7, 4, 0):
            r, c = rows[i], cols[i]
            for half in range(TM.BODY_H):
                got = row_of(r + half, SCREEN_A >> 8, SCREEN_A)
                want = TM.apply(terrain_of(r + half), r + half)
                check(f"turret {i}: stage row {r + half} composes "
                      f"{'TL/TR' if half == 0 else 'BL/BR'} at columns {c},{c+1}",
                      got == want,
                      f"cols {c},{c+1}: {got[c:c+2]} vs {want[c:c+2]}")
                check(f"turret {i}: stage row {r + half} is terrain everywhere "
                      f"else", [x for j, x in enumerate(got) if j not in (c, c + 1)]
                      == [x for j, x in enumerate(terrain_of(r + half))
                          if j not in (c, c + 1)])
            # The rows either side must be untouched terrain.
            for r2 in (r - 1, r + TM.BODY_H):
                got = row_of(r2, SCREEN_A >> 8, SCREEN_A)
                check(f"turret {i}: stage row {r2} is pure terrain",
                      got == terrain_of(r2), f"{got[c:c+2]}")

        # --- screen A and screen B compose identically ----------------------
        for i in (7, 0):
            r = rows[i]
            a = row_of(r, SCREEN_A >> 8, SCREEN_A)
            b = row_of(r, SCREEN_B >> 8, SCREEN_B)
            check(f"turret {i}: page A and page B agree on stage row {r}",
                  a == b, f"{a[:6]} vs {b[:6]}")

        # --- THE RESTORATION CONTRACT ---------------------------------------
        # Clearing one alive byte must make the next regeneration produce the
        # terrain that was always underneath -- with no cached codes, no repair
        # path and no change to any other turret.
        i = 4
        r, c = rows[i], cols[i]
        poke(mon, sym["turretAlive"] + i, 0)
        for half in range(TM.BODY_H):
            got = row_of(r + half, SCREEN_A >> 8, SCREEN_A)
            check(f"dead turret {i}: stage row {r + half} regenerates as pure "
                  f"terrain", got == terrain_of(r + half),
                  f"cols {c},{c+1}: {got[c:c+2]}")
        j = 5
        rj = rows[j]
        got = row_of(rj, SCREEN_A >> 8, SCREEN_A)
        check(f"...and turret {j} is unaffected by it",
              got == TM.apply(terrain_of(rj), rj), f"{got[cols[j]:cols[j]+2]}")
        poke(mon, sym["turretAlive"] + i, 1)
        got = row_of(r, SCREEN_A >> 8, SCREEN_A)
        check(f"marking turret {i} alive again brings its body straight back",
              got == TM.apply(terrain_of(r), r), f"{got[c:c+2]}")

        # --- colour RAM is untouched by turrets -----------------------------
        # Four bits wide: 9 reads back as $c9. The turret's dome is bit pair 11,
        # which is these low three bits -- the old game PULSED them and this
        # slice does not, so a uniform colour RAM is both the terrain contract
        # and the turret's held pulse-phase-0 colour.
        cram = [b & 0x0f for b in rd(mon, 0xd800, 256)
                + rd(mon, 0xd800 + 0x2e8, 24)]
        want21 = T.consts()["TERRAIN_COLOUR_RAM"]
        check(f"colour RAM is still the level's single value ({want21}) "
              f"everywhere", set(cram) == {want21}, f"saw {sorted(set(cram))}")

        # --- no sprite pointer can reach the turret bitmaps -----------------
        mon.cmd("delete")
        free_run(mon, sym["frameCounter"], 2)
        mon.cmd("delete")
        bad = []
        for base in (PTR_A, PTR_B):
            for p in rd(mon, base, 8):
                lo = (base & 0xc000) + p * 64
                if lo < TURRET_GLYPHS + TURRET_GLYPH_SPAN * 8 \
                        and TURRET_GLYPHS < lo + 64:
                    bad.append((hex(base), p))
        check("no sprite pointer on either page names the turret bitmaps",
              not bad, str(bad))

        # --- the body codes really are on the displayed pages ---------------
        seen = set()
        for base in (SCREEN_A, SCREEN_B):
            seen |= set(rd(mon, base, 1000))
        body = set(range(TURRET_GLYPH_BASE,
                         TURRET_GLYPH_BASE + TURRET_GLYPH_SPAN))
        check("the only non-terrain codes on either page are turret body codes",
              (seen - set(range(96, 96 + T.consts()["TERRAIN_GLYPH_COUNT"])))
              <= body, str(sorted(seen - body)[:6]))

        # ================================================================
        # THE BLACK BORDER, SAMPLED BY RASTER
        # ================================================================
        # $d021 is now aperture state. Reading it at an arbitrary stop says
        # nothing; reading it at each raster phase says everything, because the
        # phase IS the raster. Every value below is read at the phase's ENTRY,
        # before that phase's own store.
        print("\n=== 7. $d021 is aperture state: black border, level playfield ===")
        for phase, want, why in (
                ("exHud",     BORDER_D021,   "raster 4, the open top border"),
                ("exHandoff", BORDER_D021,   "raster 40, still the top border"),
                ("exTop",     BORDER_D021,   "raster 53, two lines above the "
                                             "aperture"),
                ("exBottom",  APERTURE_D021, "raster 243, inside the playfield"),
                ("exFrame",   BORDER_D021,   "raster 250, the bottom border")):
            mon.cmd("delete")
            b = set_bp(mon, sym[phase])
            mon.cmd("x")
            raster = rd(mon, 0xd012)[0]
            got = rd(mon, 0xd021)[0] & 0x0f
            mon.cmd(f"delete {b}"); mon.cmd("delete")
            check(f"at {phase} (raster {raster}) $d021 = {want}  [{why}]",
                  got == want, f"{got}")

        # The two splits, and that the CHARSET boundary and the BACKGROUND
        # boundary are the same two rasters. A background that switched
        # anywhere else would put a coloured line above or below the terrain.
        rsrc = (ROOT / "src" / "renderer.asm").read_text()
        pair = r"sta \$d018[^\n]*\n\s*stx \$d021"
        check("the background store follows the charset store at BOTH splits",
              len(re.findall(pair, rsrc)) == 2,
              f"{len(re.findall(pair, rsrc))} of 2")
        check("the YSCROLL=7 path gives the background its own poll to 55",
              re.search(r"exTopPhase7:", rsrc) is not None
              and re.search(r"!wait55:\s*\n\s*cpy \$d012", rsrc) is not None)

    finally:
        v.close()
        print(f"\n  launched and reaped: {LAUNCHED_PIDS}")


def main():
    print("Static turret presentation, and the black open border\n")
    provenance()
    authored()
    mapping()
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
