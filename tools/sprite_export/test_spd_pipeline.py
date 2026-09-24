#!/usr/bin/env python3
"""The SpritePad -> game pipeline, and the Square's place in it.

    python3 tools/sprite_export/test_spd_pipeline.py

WHAT CHANGED SINCE test_spd_export.py. The .spd used to be a derived view of
authoritative .asm artwork; it is the source of truth now, and the tool that
wrote it has been replaced by one that imports it. So the direction every claim
points has reversed: the question is no longer "does the export describe the
program" but "does the program carry what the .spd says".

Expected values do not come from the writer. The reader is checked against a
hand-assembled byte literal, the generator against properties it cannot satisfy
by accident, and the built program against the .spd rather than against either.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "level_editor"))

import spd_reader                                              # noqa: E402
import import_spd                                              # noqa: E402
import sprite_source as src                                    # noqa: E402
import verify_sprites                                          # noqa: E402
import contract_v2 as C                                        # noqa: E402

PASS, FAIL = [], []
SPD = REPO / "assets" / "sprites" / "19656-sprites.spd"
GEN = REPO / "src" / "generated_sprites"


def check(label, ok, extra=""):
    (PASS if ok else FAIL).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{' -- ' + extra if extra else ''}")


def raises(label, exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        check(label, True, type(e).__name__)
        return
    except Exception as e:                                     # noqa: BLE001
        check(label, False, f"raised {type(e).__name__}, wanted {exc.__name__}")
        return
    check(label, False, "no exception")


# ---------------------------------------------------------------------------
# 1. the edited project's structure
# ---------------------------------------------------------------------------
spd = spd_reader.read(SPD)
check("the .spd is SpritePad 2.0 and parses strictly", spd.version == 1)
check("it holds 48 slots: 43 established roles, 4 Square frames, 1 unused",
      len(spd.sprites) == import_spd.EXPECTED_SLOTS, str(len(spd.sprites)))
check("the shared colours are the engine's $d025 / $d026",
      (spd.multicolour1, spd.multicolour2) == (src.SPR_MC_DARK, src.SPR_MC_LIGHT),
      f"{spd.multicolour1}, {spd.multicolour2}")
check("slot 15 is still the player's deliberate blank",
      not any(spd.sprites[15].bitmap))
check("slot 47 is the unused trailing slot", not any(spd.sprites[47].bitmap))
check("all four Square frames carry artwork",
      all(any(spd.sprites[i].bitmap) for i in import_spd.SQUARE_SLOTS))
check("all four Square frames are multicolour",
      all(spd.sprites[i].multicolour for i in import_spd.SQUARE_SLOTS))
check("every slot is exactly 63 bitmap bytes",
      all(len(s.bitmap) == 63 for s in spd.sprites))

# The established roles must still be in their original order. Proved through
# the engine's own placement: each group's slot range maps to one symbol.
order = [(g.symbol, verify_sprites.SLOT_OF_GROUP[g.symbol]) for g in src.GROUPS]
check("slots 0..42 still map to the established roles in order",
      [s for _, s in order] == [0, 16, 21, 22, 30, 34, 43, 38, 42],
      ", ".join(f"{n}@{s}" for n, s in order))

# ---------------------------------------------------------------------------
# 2. generation is deterministic and total
# ---------------------------------------------------------------------------
a, da = import_spd.generate()
b, db = import_spd.generate()
check("generation is deterministic", a == b and da == db, da[:12])
check("it produces one include per import point plus the stamp",
      len(a) == len(import_spd.GROUPS) + 1, f"{len(a)} files")
check("every generated file names its .spd by hash",
      all(f"// spd sha256: {da}" in text for text in a.values()))
check("every generated file says it is generated",
      all("DO NOT EDIT BY HAND" in text for text in a.values()))
on_disk_ok, msg = import_spd.check()
check("the tree on disk matches a fresh render", on_disk_ok, msg)

# a Square include really is emitted, with its four frame labels
sq = a["enemy_square_art.asm"]
check("the Square include carries all four frame labels",
      all(lbl in sq for lbl in ("square_0_full", "square_1_turn",
                                "square_2_narrow", "square_3_edge")))
check("the Square include emits 4 x 64 bytes",
      sq.count(".byte") == 4 * 22, f"{sq.count('.byte')} .byte rows")

# ---------------------------------------------------------------------------
# 3. malformed input fails loudly
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    raw = SPD.read_bytes()
    bad = d / "bad.spd"

    bad.write_bytes(raw + b"\x00")
    raises("a truncated/padded .spd is refused", import_spd.ImportError_,
           import_spd.load_spd, bad)
    bad.write_bytes(b"XXX" + raw[3:])
    raises("a .spd without the SPD signature is refused", import_spd.ImportError_,
           import_spd.load_spd, bad)
    # a structurally valid file with the WRONG number of slots
    shorter = bytearray(raw)
    shorter[4] = 42                       # claim 43 sprites
    del shorter[9 + 64 * 43:len(shorter) - 4]
    bad.write_bytes(bytes(shorter))
    raises("a .spd with a different slot count is refused (insert/delete)",
           import_spd.ImportError_, import_spd.load_spd, bad)
    # a Square frame blanked out
    blanked = bytearray(raw)
    for i in range(63):
        blanked[9 + 64 * 43 + i] = 0
    bad.write_bytes(bytes(blanked))
    raises("a blank Square frame is refused", import_spd.ImportError_,
           import_spd.load_spd, bad)
    # data in the slot that must stay blank
    filled = bytearray(raw)
    filled[9 + 64 * 15] = 0xFF
    bad.write_bytes(bytes(filled))
    raises("data in the player's blank block is refused", import_spd.ImportError_,
           import_spd.load_spd, bad)
    raises("a missing .spd is refused", import_spd.ImportError_,
           import_spd.load_spd, d / "nope.spd")

# ---------------------------------------------------------------------------
# 4. a stale tree cannot reach a build
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    shutil.copytree(GEN, d / "gen")
    ok, _ = import_spd.check(SPD, d / "gen")
    check("a freshly copied tree is current", ok)
    stamp = d / "gen" / import_spd.STAMP.name
    stamp.write_text(stamp.read_text().replace("// spd sha256: ",
                                               "// spd sha256: 0"), encoding="utf-8")
    ok, msg = import_spd.check(SPD, d / "gen")
    check("a tree generated from a different .spd is reported stale", not ok)
    (d / "gen" / "enemy_square_art.asm").write_text("// tampered\n", encoding="utf-8")
    shutil.copy(GEN / import_spd.STAMP.name, stamp)
    ok, msg = import_spd.check(SPD, d / "gen")
    check("a hand-edited generated file is reported stale even with a good stamp",
          not ok, msg[:60])
    ok, _ = import_spd.check(SPD, d / "empty")
    check("a missing tree is reported stale", not ok)

mk = (REPO / "Makefile").read_text(encoding="utf-8")
check("`make build` depends on the staleness check",
      "build: sprites-check" in mk)
check("`make sprites` regenerates", "\nsprites:\n" in mk)

# ---------------------------------------------------------------------------
# 5. the BUILT PROGRAM carries exactly what the .spd holds
# ---------------------------------------------------------------------------
n, compared, problems, _, sprites = verify_sprites.verify()
check("every payload in the built program equals the .spd", not problems,
      "; ".join(problems[:3]))
check("47 payloads and 2961 bytes were actually compared",
      (n, compared) == (47, 47 * 63), f"{n} payloads, {compared} bytes")
existing = [s for s in sprites if s.group != "squareFrames"]
square = [s for s in sprites if s.group == "squareFrames"]
check("43 of them are the established roles", len(existing) == 43,
      str(len(existing)))
check("4 of them are the Square", len(square) == 4, str(len(square)))
check("every 64th byte is still zero and separate from the payload",
      all(s.pad == 0 for s in sprites))

# the Square's frames are four consecutive blocks with consecutive pointers
ptrs = [s.pointer for s in square]
check("the Square's four frames are consecutive blocks",
      ptrs == list(range(ptrs[0], ptrs[0] + 4)), str([hex(p) for p in ptrs]))
check("they sit in the enemy sprite window at slot 8 ($2e00, pointers $b8..$bb)",
      square[0].address == 0x2E00 and ptrs == [0xB8, 0xB9, 0xBA, 0xBB],
      f"${square[0].address:04x} {[hex(p) for p in ptrs]}")
check("the Square is multicolour like every other gameplay sprite",
      all(s.multicolour for s in square))

# ---------------------------------------------------------------------------
# 6. species identity
# ---------------------------------------------------------------------------
check("Ring is still 0 and Dropper is still 8",
      (C.SPECIES["RING"], C.SPECIES["DROPPER"]) == (0, 8), str(C.SPECIES))
check("Square is 16 -- the third animation row, not an index",
      C.SPECIES["SQUARE"] == 2 * C.ENEMY_ANIM_STEPS, str(C.SPECIES["SQUARE"]))
check("every species value is a distinct whole animation row",
      len(set(C.SPECIES.values())) == 3
      and all(v % C.ENEMY_ANIM_STEPS == 0 for v in C.SPECIES.values()))
check("the editor offers a human label for the Square",
      C.SPECIES_LABELS["SQUARE"] == "Square")
check("the window slots pack in order without moving Ring or Dropper",
      C.DEFAULT_ENEMY_SLOTS == {"RING": 0, "DROPPER": 4, "SQUARE": 8},
      str(C.DEFAULT_ENEMY_SLOTS))

asm = (REPO / "src" / "encounter_format.asm").read_text(encoding="utf-8")
check("the engine declares SPECIES_SQUARE and a count of three",
      "SPECIES_SQUARE" in asm and ".const SPECIES_COUNT     = 3" in asm)

# ---------------------------------------------------------------------------
# 7. the editor and the simulator
# ---------------------------------------------------------------------------
from project_v6 import ProjectV6                               # noqa: E402
from controller_v6 import EditorController                     # noqa: E402
from validation_v6 import validate                             # noqa: E402
from movement_sim import simulate_trigger                      # noqa: E402

base = ProjectV6.load(REPO / "tools/level_editor/levels/level1/level.v6.json")
proj = base.copy()
proj.triggers[0].species = "SQUARE"
check("the editor validates a Square trigger", validate(proj).ok)
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    EditorController(proj).save(d / "level.v6.json")
    check("a Square trigger survives save and reload",
          ProjectV6.load(d / "level.v6.json").triggers[0].species == "SQUARE")
    EditorController(proj).export(d / "out", carry_enemies_from=d / "out")
    enc = (d / "out" / "wave_encounters.asm").read_text(encoding="utf-8")
    ste = (d / "out" / "stage_enemies.asm").read_text(encoding="utf-8")
    check("export emits the engine's own SPECIES_SQUARE", "SPECIES_SQUARE" in enc)
    check("export claims a window slot for the Square",
          "LVL_SLOT_SQUARE" in ste)

sq_sim = simulate_trigger(proj, 0)
rg = base.copy()
rg.triggers[0].species = "RING"
rg_sim = simulate_trigger(rg, 0)
check("the simulator accepts a Square and treats it as an ordinary wave",
      (sq_sim.count, sq_sim.frame_count, [len(p) for p in sq_sim.paths])
      == (rg_sim.count, rg_sim.frame_count, [len(p) for p in rg_sim.paths]))

# same-species adjacency stays legal, and a Square is never a Dropper
allsq = base.copy()
for t in allsq.triggers:
    t.species = "SQUARE"
check("consecutive Square triggers are legal", validate(allsq).ok)
check("a Square is not counted as a Dropper anywhere in validation",
      all("dropper" not in (i.code or "").lower() for i in validate(allsq).errors))

# ---------------------------------------------------------------------------
# 8. neither production level was touched
# ---------------------------------------------------------------------------
for lvl in ("level1", "level2"):
    doc = json.loads((REPO / f"tools/level_editor/levels/{lvl}/level.v6.json")
                     .read_text(encoding="utf-8"))
    species = {t["species"] for t in doc["triggers"]}
    check(f"{lvl} has no Square encounter", "SQUARE" not in species,
          ", ".join(sorted(species)))

check("the retired hand-authored art files are gone",
      not any((REPO / "src" / f).exists() for f in
              ("player_art.asm", "enemy_art.asm", "enemy_dropper_art.asm",
               "player_boom_art.asm", "player_muzzle_flash.asm", "boss_art.asm")))
check("nothing in src/ still imports them",
      not any('#import "player_art.asm"' in p.read_text(encoding="utf-8",
                                                        errors="replace")
              for p in (REPO / "src").rglob("*.asm")))
check("the PNG-based player generator is retired too",
      not (REPO / "tools" / "gen_player_ship.py").exists())

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1)
