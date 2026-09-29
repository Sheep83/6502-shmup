#!/usr/bin/env python3
"""The two-level layout contract: one editor project and one generated package
per level, and no way for either level to reach into the other.

WHY THIS FILE EXISTS. The repository accumulated four level-shaped JSON files
and one generated ASM directory while the editor was being built, and it was no
longer obvious which was authoritative. Level 1 is real authored content; Level
2 is the promoted PCB prototype. The layout is now:

    tools/level_editor/levels/level1/level.v6.json   <- authored, authoritative
    tools/level_editor/levels/level2/level.v6.json   <- promoted PCB, authoritative
    src/level1/                                      <- Level 1's generated package
    src/level2/                                      <- Level 2's generated package

MOST OF THIS FILE USES CONTROLLED FIXTURES, NOT THE PRODUCTION LEVELS. Brian
authors Level 1 continuously; a contract test that asserts its glyph count or
its trigger rows is a test that breaks every time the game is worked on. So the
generic contract -- export completeness, isolation, identity-after-rename -- is
proved against synthetic projects built here, and the production levels are
touched only for the few claims that are genuinely about them: that they exist
at the canonical paths, that they are distinct, and that Level 2 carries the PCB
artwork.

    python3 tools/level_editor/test_multi_level_layout.py
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import export_v6                                                    # noqa: E402
import contract_v2 as C                                             # noqa: E402
from controller_v6 import EditorController                          # noqa: E402
from project_v6 import ProjectV6, Stage, Palette                    # noqa: E402

PASS, FAIL = [], []

LEVELS = HERE / "levels"
L1_JSON = LEVELS / "level1" / "level.v6.json"
L2_JSON = LEVELS / "level2" / "level.v6.json"
SRC_L1 = REPO / "src" / "level1"
SRC_L2 = REPO / "src" / "level2"


def check(label, ok, extra=""):
    (PASS if ok else FAIL).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{' -- ' + extra if extra else ''}")

def _campaign_sequence():
    """The levels the run actually plays, from src/campaign.asm.

    THE SEQUENCE IS ENGINE DATA and the directory listing is authoring; keeping
    them separate is what lets a fourth level be started without failing a test
    about the campaign.
    """
    src = (REPO / "src" / "campaign.asm").read_text(encoding="utf-8")
    body = src.split("cmpLevelNames:", 1)[1].split("cmpLevelNamesEnd", 1)[0]
    return re.findall(r'\.text\s+"([^"]*)"', body)


def _synthetic(name, rows=8, bg=2):
    """A minimal but VALID v6 project owing nothing to either real level."""
    glyphs = [[0] * 8 for _ in range(8)]
    glyphs[1] = [0b01010101] * 8
    return ProjectV6(
        name=name,
        stage=Stage(metatile_rows=rows, no_spawn_row=C.default_no_spawn_row(rows)),
        palette=Palette(background=bg, multicolour1=1, multicolour2=15, character=1),
        glyphs=glyphs,
        metatile_defs=[[C.TERRAIN_GLYPH_BASE] * 16,
                       [C.TERRAIN_GLYPH_BASE + 1] * 16],
        map_rows=[[0] * C.METATILES_PER_ROW for _ in range(rows)],
        turrets=[], movement_programs=[], wave_definitions=[], triggers=[],
        level_metatile_set=None,
    )


# ---------------------------------------------------------------------------
# 1-3. the canonical layout, and that each level loads its OWN data
# ---------------------------------------------------------------------------
check("both editor projects exist at the canonical paths",
      L1_JSON.is_file() and L2_JSON.is_file())
check("both generated packages exist at the canonical paths",
      SRC_L1.is_dir() and SRC_L2.is_dir())

c1 = EditorController.load(L1_JSON)
c2 = EditorController.load(L2_JSON)
check("opening level1 yields a project named 'level1'", c1.project.name == "level1",
      c1.project.name)
check("opening level2 yields a project named 'level2'", c2.project.name == "level2",
      c2.project.name)
check("neither project needed migrating (both are already v6)",
      not c1.migrated and not c2.migrated)

# The two must be genuinely different documents, field by field.
differing = [f for f in ("palette", "glyphs", "metatileDefs", "map", "stage")
             if json.dumps(c1.project.to_dict()[f], sort_keys=True)
             != json.dumps(c2.project.to_dict()[f], sort_keys=True)]
check("level1 and level2 differ in palette, glyphs, metatiles, map and stage",
      len(differing) == 5, ", ".join(differing))

# Level 2 really is the PCB artwork, named by its own distinctive properties
# rather than by a count that will drift if the map is edited.
p2 = c2.project.to_dict()
check("level2 carries the PCB palette (green board, black, grey, gold)",
      p2["palette"] == {"background": 5, "multicolour1": 0,
                        "multicolour2": 15, "character": 7}, str(p2["palette"]))
names2 = [e["name"] for e in p2["levelMetatileSet"]]
pcb_markers = {"BOARD", "TRACE_V", "TRACE_X", "DIP_TOP_L", "EDGE_FINGERS", "VIA_FIELD"}
check("level2's metatile set is the PCB vocabulary",
      pcb_markers <= set(names2), f"{len(names2)} metatiles")
check("level1 is NOT the PCB vocabulary",
      not pcb_markers <= {e["name"] for e in c1.project.to_dict()["levelMetatileSet"]})

# ---------------------------------------------------------------------------
# 4-5. saving one level cannot touch the other
# ---------------------------------------------------------------------------
b1, b2 = L1_JSON.read_bytes(), L2_JSON.read_bytes()
c2.save(L2_JSON)
check("saving level2 leaves level1's JSON byte-identical", L1_JSON.read_bytes() == b1)
check("saving level2 leaves level2's own JSON byte-identical (deterministic)",
      L2_JSON.read_bytes() == b2)
c1.save(L1_JSON)
check("saving level1 leaves level2's JSON byte-identical", L2_JSON.read_bytes() == b2)
check("saving level1 leaves level1's own JSON byte-identical (deterministic)",
      L1_JSON.read_bytes() == b1)

# ---------------------------------------------------------------------------
# 6-7. export writes only its own directory
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    a, b = d / "src" / "level1", d / "src" / "level2"
    EditorController(_synthetic("level1")).export(a, carry_enemies_from=a)
    before = {p.name: p.read_bytes() for p in a.iterdir()}
    EditorController(_synthetic("level2", rows=9, bg=5)).export(b, carry_enemies_from=b)
    check("exporting one level writes nothing into the other's directory",
          {p.name: p.read_bytes() for p in a.iterdir()} == before)
    check("the two exported packages have different stage_config.asm",
          (a / "stage_config.asm").read_bytes() != (b / "stage_config.asm").read_bytes())

# ---------------------------------------------------------------------------
# 8-9. a FRESH export is complete, and an incomplete one is refused
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    fresh = Path(d) / "src" / "brand_new"
    written = EditorController(_synthetic("brand_new")).export(
        fresh, carry_enemies_from=fresh)          # the GUI's own call shape
    on_disk = {p.name for p in fresh.iterdir()}
    missing = set(export_v6.REQUIRED_PACKAGE_NAMES) - on_disk
    check("a fresh export produces every file the engine imports",
          not missing, f"{len(on_disk)} files; missing {sorted(missing) or 'none'}")
    check("...including stage_enemies.asm",
          (fresh / export_v6.ENEMIES_NAME).is_file())
    check("...and it does not depend on src/level1 existing",
          SRC_L1.as_posix() not in
          (fresh / export_v6.ENEMIES_NAME).read_text(encoding="utf-8"))
    text = (fresh / export_v6.ENEMIES_NAME).read_text(encoding="utf-8")
    check("the generated slot symbols are level-NEUTRAL, not L1_*",
          "LVL_SLOT_RING" in text and "L1_SLOT" not in text)
    # ONE SYMBOL PER ENGINE SPECIES SLOT, AND ITS VALUE IS THE BLOCK THE ARTWORK
    # WAS LOADED AT. `C.DEFAULT_ENEMY_SLOTS` no longer exists and a "canonical
    # slot" no longer does either: since a slot holds any roster identity, its
    # window offset is the sum of the frame counts before it. The structural
    # claims are that every species is declared exactly once, that the offsets
    # are the running total of the chosen artwork's frame counts, and that the
    # whole window fits the engine's budget.
    ids = C.level_identities(EditorController(_synthetic("brand_new")).project)
    running, want_slots = 0, {}
    for sp, ident in zip(C.SPECIES_ORDER, ids):
        want_slots[sp] = running
        running += C.ROSTER_FRAMES[ident]
    decls = dict(re.findall(r"\.const\s+LVL_SLOT_(\w+)\s*=\s*(\d+)", text))
    check("every engine species slot is declared exactly once",
          set(decls) == set(C.SPECIES_ORDER),
          f"{sorted(decls)} vs {sorted(C.SPECIES_ORDER)}")
    check("...at the window offset its chosen artwork's frame counts imply",
          {k: int(v) for k, v in decls.items()} == want_slots,
          f"{decls} vs {want_slots} for identities {ids}")
    check("...and the whole window fits the engine's sprite budget",
          running <= C.LEVEL_SPRITE_BLOCKS,
          f"{running} of {C.LEVEL_SPRITE_BLOCKS} blocks")

    # stage_enemies.asm AND stage_sprites.asm ARE REGENERATED EVERY EXPORT.
    # This check used to assert the opposite -- "a hand-authored one survives" --
    # which was the behaviour before a slot could hold any roster identity.
    # export_v6.export_level says so in as many words: carrying an old one
    # forward would ship the previous level's animation table against this
    # level's sprite window. So the claim is now that a stale copy is REPLACED,
    # which is what protects the level from a silently wrong animation table.
    stale = ".const LVL_SLOT_RING = 99   // stale, from another level\n"
    for name in (export_v6.ENEMIES_NAME, export_v6.SPRITES_NAME):
        (fresh / name).write_text(stale, encoding="utf-8")
    EditorController(_synthetic("brand_new")).export(fresh, carry_enemies_from=fresh)
    for name in (export_v6.ENEMIES_NAME, export_v6.SPRITES_NAME):
        got = (fresh / name).read_text(encoding="utf-8")
        check(f"a stale {name} is REGENERATED, not carried forward",
              got != stale and "99" not in got,
              f"{len(got)} bytes, regenerated")

# Export must FAIL LOUDLY rather than leave an incomplete package behind.
with tempfile.TemporaryDirectory() as d:
    dest = Path(d) / "sabotaged"
    dest.mkdir(parents=True)
    real_render = export_v6.render_stage_enemies
    export_v6.render_stage_enemies = lambda *a, **k: ""      # produce nothing useful
    try:
        # Remove the file straight after it is written, to stand in for any
        # reason the package could come out short.
        orig_replace = export_v6.os.replace

        def sabotage(src, dst):
            orig_replace(src, dst)
            if Path(dst).name == export_v6.ENEMIES_NAME:
                Path(dst).unlink()
        export_v6.os.replace = sabotage
        refused = False
        try:
            EditorController(_synthetic("sabotaged")).export(dest, carry_enemies_from=dest)
        except export_v6.ExportRefused as exc:
            refused = export_v6.ENEMIES_NAME in str(exc)
        finally:
            export_v6.os.replace = orig_replace
        check("an incomplete package is REFUSED, naming the missing file", refused)
    finally:
        export_v6.render_stage_enemies = real_render

# ---------------------------------------------------------------------------
# 10. identity survives a move, and drives the default export directory
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as d:
    levels = Path(d) / "levels"
    (levels / "level2").mkdir(parents=True)
    proj = _synthetic("level2pcb")
    ctl = EditorController(proj)
    moved = levels / "level2" / "level.v6.json"
    ctl.save(moved)
    check("a Save As into levels/level2/ does NOT silently rename the project",
          ctl.project.name == "level2pcb", ctl.project.name)
    ctl.name = moved.parent.name                    # what Rename Level does
    ctl.save(moved)
    check("after Rename Level the project identifies as its directory",
          ctl.project.name == "level2", ctl.project.name)
    check("and the rename survives a reload",
          EditorController.load(moved).project.name == "level2")
    out = Path(d) / "src" / ctl.project.name
    ctl.export(out, carry_enemies_from=out)
    check("the renamed project exports to src/<name>/ and names itself in the header",
          out.name == "level2"
          and "Level: level2" in (out / "stage_config.asm").read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# 14-15. nothing obsolete left where it could be mistaken for live level data
# ---------------------------------------------------------------------------
check("no level2pcb project directory remains",
      not (LEVELS / "level2pcb").exists() and not (LEVELS / "level2pcb-blue").exists())
check("no generated ASM lives under the editor's level directories",
      not list(LEVELS.rglob("*.asm")))
stray = sorted(p.relative_to(REPO).as_posix()
               for p in LEVELS.rglob("*.json") if p.name != "level.v6.json")
check("levels/ holds ONLY level.v6.json documents", not stray, ", ".join(stray))
# HOW MANY LEVELS EXIST IS AUTHORING. This said `== ["level1", "level2"]` and
# duly failed the day a third level was started. What must hold is that every
# directory under levels/ really is a level document, and that every level the
# CAMPAIGN sequence names is one of them -- a dangling campaign entry is a run
# that reaches for a package that is not on the disk.
_dirs = sorted(p.name for p in LEVELS.iterdir() if p.is_dir())
check("every directory under levels/ holds a level document",
      _dirs and all((LEVELS / n / "level.v6.json").is_file() for n in _dirs),
      ", ".join(_dirs))
_seq = [n.lower() for n in _campaign_sequence()]
check("every level the campaign sequence names exists as a document",
      set(_seq) <= set(_dirs), f"campaign {_seq}, present {_dirs}")
check("...and the campaign's generated packages are all under src/",
      all((REPO / "src" / n).is_dir() for n in _seq), ", ".join(_seq))
check("no level JSON has leaked under src/", not list((REPO / "src").rglob("*.json")))
check("the frozen v5 fixtures are out of levels/ and under fixtures/",
      (HERE / "fixtures" / "legacy_v5" / "level1" / "level.json").is_file()
      and (HERE / "fixtures" / "legacy_v5" / "level2" / "level.json").is_file())

# ---------------------------------------------------------------------------
# 12. Level 1's authored content is what it was
# ---------------------------------------------------------------------------
# Deliberately a STRUCTURAL claim, not a hash: this file must not need editing
# every time the level is authored further. The hash proof against the
# pre-change snapshot lives in the task report.
d1 = c1.project.to_dict()
check("level1 still declares a self-consistent shape -- whatever is authored, "
      "the map, metatile and glyph counts agree with their headers",
      d1["stage"]["metatileCols"] == C.METATILES_PER_ROW
      and len(d1["map"]) == d1["stage"]["metatileRows"]
      and len(d1["metatileDefs"]) >= 1
      and d1["glyphs"]["count"] == len(d1["glyphs"]["bitmaps"]),
      f"{d1['stage']['metatileRows']} rows, {len(d1['metatileDefs'])} metatiles, "
      f"{d1['glyphs']['count']} glyphs, {len(d1['turrets'])} turrets, "
      f"{len(d1['triggers'])} triggers")
check("level1's generated package is complete",
      all((SRC_L1 / n).is_file() for n in export_v6.REQUIRED_PACKAGE_NAMES))
check("level2's generated package is complete",
      all((SRC_L2 / n).is_file() for n in export_v6.REQUIRED_PACKAGE_NAMES))
check("level1's package still uses the neutral slot symbols",
      "LVL_SLOT_RING" in (SRC_L1 / "stage_enemies.asm").read_text(encoding="utf-8"))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1)
