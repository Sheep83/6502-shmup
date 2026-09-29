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
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "level_editor"))
import contract_v2                                              # noqa: E402
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
check("the .spd is a SpritePad version this reader supports",
      spd.version in (1, 5), f"version byte {spd.version}")
check(f"it holds {import_spd.EXPECTED_SLOTS} slots ($00..$6D)",
      len(spd.sprites) == import_spd.EXPECTED_SLOTS, str(len(spd.sprites)))
check("every sprite in the project is multicolour",
      all(x.multicolour for x in spd.sprites))
check("the shared colours are the engine's $d025 / $d026",
      (spd.multicolour1, spd.multicolour2) == (src.SPR_MC_DARK, src.SPR_MC_LIGHT),
      f"{spd.multicolour1}, {spd.multicolour2}")
for _b in import_spd.BLANK_SLOTS:
    check(f"${_b:02X} is blank, as the layout requires",
          not any(spd.sprites[_b].bitmap))
check("all four Square frames carry artwork",
      all(any(spd.sprites[i].bitmap) for i in import_spd.SQUARE_SLOTS))

# EVERY WIRED SOURCE INDEX, PROVED AGAINST THE PROJECT. This is the check that
# would catch a retargeted group pointing at the wrong artwork: each group's
# declared SpritePad slots must exist, carry art and be multicolour.
for _g in import_spd.GROUPS:
    check(f"{_g.filename}: sources {' '.join(f'${x:02X}' for x in _g.slots)} "
          f"all carry multicolour art",
          all(x < len(spd.sprites) and any(spd.sprites[x].bitmap)
              and spd.sprites[x].multicolour for x in _g.slots))
check("all four Square frames are multicolour",
      all(spd.sprites[i].multicolour for i in import_spd.SQUARE_SLOTS))
check("every slot is exactly 63 bitmap bytes",
      all(len(s.bitmap) == 63 for s in spd.sprites))

# Every runtime group the readback tool knows about must have a source mapping,
# and the two tools must agree on the SET of groups. This replaces a check that
# compared a stale dictionary against a stale literal list of slot numbers: both
# copies were wrong after the project was reorganised and the check stayed green.
check("every readback group has a declared SpritePad source",
      all(g.symbol in verify_sprites.SLOTS_OF_GROUP for g in src.GROUPS),
      ", ".join(g.symbol for g in src.GROUPS
                if g.symbol not in verify_sprites.SLOTS_OF_GROUP) or "all present")
# THE TWO TOOLS COVER DIFFERENT THINGS NOW, on purpose: sprite_source reads
# main.prg and the enemy and boss artwork is not in it. Every group it does
# read must still have a declared source, which the check above proves; here we
# prove the importer is a SUPERSET, so nothing the readback tool wants is
# missing from the mapping.
check("the readback tool's groups are a subset of the importer's",
      {g.symbol for g in src.GROUPS} <= set(verify_sprites.SLOTS_OF_GROUP),
      ", ".join(sorted({g.symbol for g in src.GROUPS}
                       - set(verify_sprites.SLOTS_OF_GROUP))) or "subset")
# The player's run is SIXTEEN blocks but only FIFTEEN come from the .spd: the
# last is playerBlankBitmap, which src/player.asm emits itself and this importer
# deliberately does not own. Every other group is exactly its source slots.
ENGINE_EMITTED = {"player_art_frames": 1}
def _expected(sym):
    return len(verify_sprites.SLOTS_OF_GROUP[sym]) + ENGINE_EMITTED.get(sym, 0)
_bad = [f"{g.symbol}: {g.count} blocks vs {_expected(g.symbol)} expected"
        for g in src.GROUPS if g.symbol in verify_sprites.SLOTS_OF_GROUP
        and g.count != _expected(g.symbol)]
check("each readback group's block count matches its source slots "
      "(plus the player's engine-emitted blank)", not _bad,
      ", ".join(_bad) or "all match")

# ---------------------------------------------------------------------------
# 2. generation is deterministic and total
# ---------------------------------------------------------------------------
a, da = import_spd.generate()
b, db = import_spd.generate()
check("generation is deterministic", a == b and da == db, da[:12])
check("it produces one include per import point, one per roster entry, "
      "the roster constants and the stamp",
      len(a) == len(import_spd.ALL_GROUPS) + 2, f"{len(a)} files")
check("every generated file names its .spd by hash",
      all(f"// spd sha256: {da}" in text for text in a.values()))
check("every generated file says it is generated",
      all("DO NOT EDIT BY HAND" in text for text in a.values()))
on_disk_ok, msg = import_spd.check()
check("the tree on disk matches a fresh render", on_disk_ok, msg)

# a Square include really is emitted, with its four frame labels
# EVERY ROSTER ENTRY EMITS EXACTLY ITS OWN FRAME COUNT. This is the structural
# proof that nothing is sampled, padded or truncated: 3-frame artwork emits 3
# blocks, 8-frame artwork emits 8, and the ring_3 line is the one that used to
# be four sampled frames.
_wrong = []
for _r in import_spd.ENEMY_ROSTER:
    rows = a[_r.filename].count(".byte")
    if rows != _r.frames * 22:
        _wrong.append(f"{_r.name}: {rows // 22} blocks for {_r.frames} frames")
check("every roster entry emits exactly its own frame count", not _wrong,
      ", ".join(_wrong) or
      ", ".join(f"{r.name} {r.frames}" for r in import_spd.ENEMY_ROSTER))
check("ring_3 emits all eight frames, not four sampled ones",
      a["enemy_ring_3_art.asm"].count(".byte") == 8 * 22,
      f"{a['enemy_ring_3_art.asm'].count('.byte') // 22} blocks")

# ---------------------------------------------------------------------------
# 2b. THE SLOT MAPPING, PROVED BYTE FOR BYTE
# ---------------------------------------------------------------------------
# The claim under test is the one that matters after a reorganisation: that the
# 63 bytes of SpritePad slot N really are the 63 bytes emitted into the runtime
# block the engine will fetch. Proved by re-parsing the generated assembler, not
# by trusting the generator that wrote it.
def _emitted_blocks(text):
    """The .byte rows of a generated include, back into 64-byte blocks."""
    vals = []
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if line.startswith(".byte"):
            vals += [int(t.strip().lstrip("$"), 16)
                     for t in line[5:].split(",") if t.strip()]
    return [vals[i:i + 64] for i in range(0, len(vals), 64)]

_all_ok, _detail = True, []
for _g in import_spd.GROUPS:
    _blocks = _emitted_blocks(a[_g.filename])
    if len(_blocks) != len(_g.slots):
        _all_ok = False
        _detail.append(f"{_g.filename}: {len(_blocks)} blocks for {len(_g.slots)} slots")
        continue
    for _n, _slot in enumerate(_g.slots):
        if bytes(_blocks[_n][:63]) != spd.sprites[_slot].bitmap:
            _all_ok = False
            _detail.append(f"{_g.filename} block {_n} != ${_slot:02X}")
check("every emitted 64-byte block equals its SpritePad slot, byte for byte",
      _all_ok, "; ".join(_detail) or
      f"{sum(len(g.slots) for g in import_spd.GROUPS)} blocks verified")

# The indices Brian named, each resolved to the runtime label that fetches it,
# or to nothing at all. Both answers are correct; which is which is the point.
WHERE = {}
for _g in import_spd.GROUPS:
    for _n, _slot in enumerate(_g.slots):
        WHERE[_slot] = (import_spd.RUNTIME_SYMBOL[_g.filename], _n)
NAMED = (0x00, 0x0E, 0x10, 0x1E, 0x26, 0x27, 0x34, 0x3E,
         0x44, 0x50, 0x53, 0x5A, 0x60, 0x6C)
check("every named index either resolves to one runtime block or to none",
      all(WHERE.get(i) is None or WHERE[i][0] in verify_sprites.SLOTS_OF_GROUP
          for i in NAMED),
      "; ".join(f"${i:02X}->" + (f"{WHERE[i][0]}[{WHERE[i][1]}]" if i in WHERE
                                 else "not resident") for i in NAMED))

# The disposable ranges must reach no runtime block whatsoever.
DISPOSABLE = ([0x0F, 0x15] + list(range(0x2B, 0x34))
              + list(range(0x37, 0x3B)) + list(range(0x4A, 0x50)))
check("no disposable slot consumes a runtime block",
      not [i for i in DISPOSABLE if i in WHERE],
      ", ".join(f"${i:02X}" for i in DISPOSABLE if i in WHERE)
      or f"{len(DISPOSABLE)} slots confirmed non-resident")

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
    # THE BODY OFFSET IS DERIVED, NOT WRITTEN DOWN. These pokes used to carry a
    # literal 9 -- the version 1 body offset -- and a literal slot 43 for the
    # Square. The project is version 5 now, whose body starts at 20, so every
    # one of those pokes landed in the wrong sprite: the "blank block" case
    # silently corrupted an unrelated block, left $0F genuinely blank, and
    # passed for the wrong reason. Ask the reader where the body is instead.
    BODY = {1: 9, 5: 20}[spd_reader.parse(raw).version]
    SQUARE0 = import_spd.SQUARE_SLOTS[0]
    BLANK0 = import_spd.BLANK_SLOTS[0]

    # a structurally valid file with the WRONG number of slots
    shorter = bytearray(raw)
    shorter[5] = (import_spd.EXPECTED_SLOTS - 1) & 0xFF   # claim one fewer
    del shorter[BODY + 64 * (import_spd.EXPECTED_SLOTS - 1):
                BODY + 64 * import_spd.EXPECTED_SLOTS]
    bad.write_bytes(bytes(shorter))
    raises("a .spd with a different slot count is refused (insert/delete)",
           import_spd.ImportError_, import_spd.load_spd, bad)
    # a Square frame blanked out
    blanked = bytearray(raw)
    for i in range(63):
        blanked[BODY + 64 * SQUARE0 + i] = 0
    bad.write_bytes(bytes(blanked))
    raises("a blank Square frame is refused", import_spd.ImportError_,
           import_spd.load_spd, bad)
    # data in the slot that must stay blank
    filled = bytearray(raw)
    filled[BODY + 64 * BLANK0] = 0xFF
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
check("every payload in main.prg was actually compared",
      n == sum(g.count for g in src.GROUPS), f"{n} payloads, {compared} bytes")
check("every 64th byte is still zero and separate from the payload",
      all(s.pad == 0 for s in sprites))

# ---------------------------------------------------------------------------
# 5b. THE LEVEL PACKAGES — where enemy and boss artwork lives now
# ---------------------------------------------------------------------------
# These are the structural proofs for variable frame counts. A package is built
# from a level's CHOICE of artwork, so the check is against that choice: the
# right bytes, in the right blocks, at the right frame count, with every frame
# reachable and nothing else in the window.
PACKAGES = {
    REPO / "build" / "level1.prg": ("RING_3", "DROPPER", "SQUARE"),     # 8+4+4
    REPO / "build" / "level2.prg": ("RING_3", "DROPPER", "SQUARE"),      # 8+4+4
}
pkg_problems, pkg_sizes = verify_sprites.verify_packages(PACKAGES)
check("every built level package matches the .spd and its own choice",
      not pkg_problems, "; ".join(pkg_problems[:3])
      or ", ".join(f"{Path(k).name} {v} blocks" for k, v in pkg_sizes.items()))
check("a level ships only the artwork it chose",
      all(v <= import_spd.LEVEL_SPRITE_BLOCKS for v in pkg_sizes.values()),
      ", ".join(f"{Path(k).name} {v}/{import_spd.LEVEL_SPRITE_BLOCKS}"
                for k, v in pkg_sizes.items()))

# ---------------------------------------------------------------------------
# 5b2. FIXTURES: one level per frame count, proved through the real planner
# ---------------------------------------------------------------------------
# The planner is what the exporter and the package build both consume, and the
# two real levels above prove a planned layout reaches the built package byte
# for byte. So a fixture proves a frame count end to end without assembling a
# whole level for each one.
for _name, _ids, _blocks in (
        ("a 3-frame enemy", ["RING_1", "DROPPER", "SQUARE"], 11),
        ("a 4-frame enemy", ["SQUARE", "DROPPER", "RING_1"], 11),
        ("a 5-frame enemy", ["SPINNY_ROT", "DROPPER", "SQUARE"], 13),
        ("a 6-frame enemy", ["SPACE_WHISK", "DROPPER", "SQUARE"], 14),
        ("the 8-frame Ring 3", ["RING_3", "DROPPER", "SQUARE"], 16),
):
    _lay, _tab = import_spd.level_sprite_plan(_ids)
    _got = sum(r.frames for r, _ in _lay)
    _first = import_spd.ROSTER_BY_NAME[_ids[0]]
    _row = set(_tab[0:8])
    check(f"a level using {_name} packs {_blocks} blocks and reaches every frame",
          _got == _blocks and _row == set(range(_first.frames)),
          f"{_got} blocks, row 0 reaches {sorted(_row)} of {_first.frames}")

# TWO IDENTITIES THAT BOTH USED TO BE "SONIC RING" STAY DISTINCT. Before this
# change both would have been authored as species RING and told apart only by
# which artwork the level happened to load. Now they are different enemies with
# different frame counts landing in different blocks.
_lay_a, _tab_a = import_spd.level_sprite_plan(["RING_3", "DROPPER", "SQUARE"])
_lay_b, _tab_b = import_spd.level_sprite_plan(["SPACE_WHISK", "DROPPER", "SQUARE"])
check("two identities that were both 'Sonic Ring' resolve differently",
      _tab_a != _tab_b and _tab_a[0:8] != _tab_b[0:8],
      f"Ring 3 row {_tab_a[0:8]} vs Space Whisk row {_tab_b[0:8]}")
check("and their behaviours are identical, as the audit found",
      import_spd.ROSTER_BY_NAME["RING_3"].behaviour
      == import_spd.ROSTER_BY_NAME["SPACE_WHISK"].behaviour
      == import_spd.BEHAVIOUR_PLAIN)
check("only the Dropper identity carries the token-dropping behaviour",
      [r.name for r in import_spd.ENEMY_ROSTER
       if r.behaviour == import_spd.BEHAVIOUR_DROPPER] == ["DROPPER"])

# ---------------------------------------------------------------------------
# 5c. THE BUDGET, at its exact boundary
# ---------------------------------------------------------------------------
def _cost(*names):
    return sum(import_spd.ROSTER_BY_NAME[n].frames for n in names)

for names, total, want_ok in (
        (("RING_3", "SPINNER", "SQUARE"), 18, True),      # 8 + 6 + 4
        (("RING_3", "SPINNER", "SPACE_WHISK"), 20, True),  # 8 + 6 + 6  exactly full
        (("RING_3", "RING_3", "SPINNY_ROT"), 21, False),   # 8 + 8 + 5  one too many
):
    assert _cost(*names) == total, names
    try:
        import_spd.level_sprite_plan(list(names))
        got_ok = True
    except import_spd.BudgetError:
        got_ok = False
    check(f"{' + '.join(str(import_spd.ROSTER_BY_NAME[n].frames) for n in names)}"
          f" = {total} is {'accepted' if want_ok else 'rejected'}",
          got_ok == want_ok)
    # AND THE EDITOR MUST AGREE. Two validators that disagree are worse than
    # one, because whichever the author is looking at is the one they believe.
    editor_ok = not contract_v2.enemy_slot_problems(list(names))
    check(f"   the editor agrees about {total}", editor_ok == want_ok,
          "; ".join(contract_v2.enemy_slot_problems(list(names))) or "accepted")

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
# DEFAULT_ENEMY_SLOTS IS GONE. It said every species sat four blocks apart,
# which was only ever true while all three wore four-frame artwork. Slots are
# now packed from the level's own choice, each taking its artwork's real frame
# count, so what can be checked here is that the packing is contiguous and
# in species order -- which is what stops a level's artwork overlapping.
_layout, _ = import_spd.level_sprite_plan(list(C.DEFAULT_ENEMY_IDENTITIES))
_bases = [b for _r, b in _layout]
_expected, _run = [], 0
for _r, _ in _layout:
    _expected.append(_run)
    _run += _r.frames
check("a level's artwork packs contiguously, in species order, with no overlap",
      _bases == _expected,
      ", ".join(f"{r.label}@{b}+{r.frames}" for r, b in _layout))

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
# 8. the production levels author only species the engine has
# ---------------------------------------------------------------------------
# THIS USED TO ASSERT THAT NEITHER LEVEL HAD A SQUARE ENCOUNTER, which was true
# when the Square was new and unused. Level 1 authors Squares now, so the check
# asserted something both false and undesirable -- it would have had to be
# deleted the day the species was first used. What is worth checking is that a
# level never names a species the engine does not have, which stays true for as
# long as there are three of them.
for lvl in ("level1", "level2"):
    doc = json.loads((REPO / f"tools/level_editor/levels/{lvl}/level.v6.json")
                     .read_text(encoding="utf-8"))
    species = {t["species"] for t in doc["triggers"]}
    # A TRIGGER NAMES AN ENEMY IDENTITY, and it must be one the level carries.
    # This asserted membership of C.SPECIES -- the engine's three SLOT names --
    # which stopped being what a trigger stores when identities landed.
    slots = set(doc.get("enemySlots") or C.DEFAULT_ENEMY_IDENTITIES)
    check(f"{lvl} authors only enemies it carries",
          species <= slots,
          f"triggers {sorted(species)} against slots {sorted(slots)}")

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



# ---------------------------------------------------------------------------
# 9. THE EDITOR SIDE: roster, round-trip, export determinism, refusal
# ---------------------------------------------------------------------------
import copy as _copy
import project_v6 as _pv6                                        # noqa: E402
import export_v6 as _ex                                          # noqa: E402
from controller_v6 import EditorController as _EC                # noqa: E402

_WANT = {"DROPPER": 4, "SQUARE": 4, "ALLEYKAT_A": 3, "ALLEYKAT_B": 3,
         "RING_1": 3, "RING_2": 3, "SPINNER": 6, "SPACE_MINE": 3,
         "SPINNY": 6, "SPACE_WHISK": 6, "RING_3": 8, "SPINNY_ROT": 5}
check("every useful enemy sequence is selectable in the editor",
      set(C.ROSTER_FRAMES) == set(_WANT),
      ", ".join(sorted(set(_WANT) ^ set(C.ROSTER_FRAMES))) or "all twelve")
_badcost = [f"{n}: {C.ROSTER_FRAMES[n]} != {f}"
            for n, f in _WANT.items() if C.ROSTER_FRAMES.get(n) != f]
check("each one advertises its true physical frame count", not _badcost,
      ", ".join(_badcost) or "all twelve correct")

_EXCLUDED_SRC = ([0x0F, 0x15] + list(range(0x2B, 0x34))
                 + list(range(0x37, 0x3B)) + list(range(0x4A, 0x50)))
_offered = {x for r in import_spd.ENEMY_ROSTER for x in r.slots}
check("no disposable or reference artwork is offered as an enemy",
      not (_offered & set(_EXCLUDED_SRC)),
      f"{len(_EXCLUDED_SRC)} excluded slots confirmed absent")
for _n, _lo, _hi in (("player", 0x00, 0x0E), ("muzzle", 0x10, 0x14),
                     ("explosion", 0x16, 0x1D), ("boss", 0x22, 0x25),
                     ("bullet", 0x26, 0x26), ("power-up", 0x53, 0x53)):
    check(f"the {_n} artwork is not offered as an enemy species",
          not (_offered & set(range(_lo, _hi + 1))))

_proj = _EC.load(REPO / "tools/level_editor/levels/level1/level.v6.json").project
_proj.enemy_slots = ["SPACE_WHISK", "DROPPER", "RING_1"]
_round = _pv6.ProjectV6.from_dict(json.loads(json.dumps(_proj.to_dict())))
check("save and reload preserve the level's enemy identities",
      _round.enemy_slots == _proj.enemy_slots, str(_round.enemy_slots))
check("its cost is what the roster says",
      C.enemy_slot_cost(_round.enemy_slots) == 13,
      str(C.enemy_slot_cost(_round.enemy_slots)))

_over = _pv6.ProjectV6.from_dict(json.loads(json.dumps(
    {**_proj.to_dict(),
     "enemySlots": ["RING_3", "RING_3", "SPINNY_ROT"]})))
check("an over-budget project loads without crashing",
      _over.enemy_slots[1] == "RING_3")
check("and is reported rather than silently exported",
      bool(C.enemy_slot_problems(_over.enemy_slots)),
      "; ".join(C.enemy_slot_problems(_over.enemy_slots)))
try:
    _ex.render_stage_enemies(_over, "overbudget")
    _refused = False
except _ex.ExportRefused:
    _refused = True
check("the exporter refuses an over-budget level on its own", _refused)

_a = _ex.render_stage_enemies(_proj, "level1")
check("exporting the same selection twice gives identical bytes",
      _a == _ex.render_stage_enemies(_copy.deepcopy(_proj), "level1"))
check("a different selection gives different output",
      _a != _ex.render_stage_enemies(
          _pv6.ProjectV6.from_dict({**_proj.to_dict(),
                                    "enemySlots": list(C.DEFAULT_ENEMY_IDENTITIES)}),
          "level1"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1)
