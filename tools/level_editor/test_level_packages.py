#!/usr/bin/env python3
"""Regression tests for the two-level PACKAGE model.

  * Level 1 and Level 2 packages coexist, each owning its own terrain map,
    palette/config, turrets, wave data AND terrain tileset;
  * loading a level yields that level's glyphs (not the other's);
  * saving one level never touches the other's file;
  * each level round-trips load -> edit -> save -> reload -> export;
  * per-level export is deterministic and the two levels' generated dirs never
    collide (gameplay consumes level1/ only).

Run:  python3 tools/level_editor/test_level_packages.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import build_levels                                                        # noqa: E402
from engine_data import load_engine_data                                   # noqa: E402
from ka_export import export_level                                         # noqa: E402
from project import load_project, save_project, validate_project           # noqa: E402

PASS = []
D = load_engine_data(REPO)


def ok(m):
    PASS.append(m)
    print(f"ok  - {m}")


J1 = HERE / "fixtures" / "legacy_v5" / "level1" / "level.json"
J2 = HERE / "fixtures" / "legacy_v5" / "level2" / "level.json"

# 0. both level packages exist, and each exports into its OWN directory
#
# THIS USED TO READ src/generated/level1 AND src/generated/level2 OUT OF THE
# REPOSITORY, and neither has existed for some time: the production level lives
# in src/level1/ and there is no second level directory in the tree at all. The
# property under test -- that two level packages export independently and never
# collide -- does not need committed output, so both are exported into a scratch
# directory the test owns. Nothing here can now touch the authoritative
# src/level1/.
_SCRATCH = tempfile.TemporaryDirectory()
_GEN = Path(_SCRATCH.name) / "generated"
for p in (J1, J2):
    assert p.exists(), f"missing {p}"
L1 = _GEN / "level1"
L2 = _GEN / "level2"
export_level(load_project(J1), L1, engine_data=D)
export_level(load_project(J2), L2, engine_data=D)
ok("both level packages exist and export into separate directories")

p1 = load_project(J1)
p2 = load_project(J2)

# 1. distinct, self-contained tilesets
assert p1.tileset and p2.tileset
assert p1.tileset["glyphs"] != p2.tileset["glyphs"], "level 1 and 2 share a tileset"
assert p1.tileset["metatileDefs"] != p2.tileset["metatileDefs"]
assert p1.palette != p2.palette
ok(f"level packages own distinct tilesets ({len(p1.tileset['glyphs'])} vs "
   f"{len(p2.tileset['glyphs'])} glyphs) + distinct palettes")

# 2. each level's generated charset matches ITS OWN tileset, not the other's
c1 = (L1 / "stage_charset.asm").read_text()
c2 = (L2 / "stage_charset.asm").read_text()
assert c1 != c2
b1 = [int(x) for line in c1.splitlines() if ".byte" in line for x in line.split(".byte")[1].split("//")[0].split(",")]
assert b1[:8] == [b & 0xFF for b in p1.tileset["glyphs"][0]], "level1 charset != level1 tileset glyph 0"
b2 = [int(x) for line in c2.splitlines() if ".byte" in line for x in line.split(".byte")[1].split("//")[0].split(",")]
assert b2[:8] == [b & 0xFF for b in p2.tileset["glyphs"][0]], "level2 charset != level2 tileset glyph 0"
ok("each level's generated stage_charset.asm carries its own glyphs")

# 3. saving level 1 does not modify level 2's file (and vice versa)
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    a = td / "l1.json"; b = td / "l2.json"
    shutil.copy(J1, a); shutil.copy(J2, b)
    before_b = b.read_bytes()
    q1 = load_project(a)
    q1.wave_triggers.append({"id": "extra", "worldRow": 8, "waveDef": q1.wave_definitions[0]["id"]})
    save_project(q1, a)
    assert b.read_bytes() == before_b, "editing/saving level 1 changed level 2's file"
ok("saving one level package leaves the other's file byte-identical")

# 4. round-trip load -> edit -> save -> reload -> export, per level, independently
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    for src_json, name in ((J1, "level1"), (J2, "level2")):
        j = td / f"{name}.json"
        shutil.copy(src_json, j)
        pr = load_project(j)
        pr.metatile_rows[1][0] = (pr.metatile_rows[1][0] + 1) % 16     # a trivial edit
        assert validate_project(pr) == [], validate_project(pr)
        save_project(pr, j)
        pr2 = load_project(j)
        assert pr.to_dict() == pr2.to_dict()
        g1 = export_level(pr2, td / f"{name}-g1", engine_data=D)
        g2 = export_level(pr2, td / f"{name}-g2", engine_data=D)
        assert all(x.read_text() == y.read_text() for x, y in zip(g1, g2)), f"{name} export not deterministic"
        # FOUR FILES, NOT FIVE. stage_test.asm is stage_map.asm, and there is no
        # stage_waves.asm: encounter data ships as level-package bytes authored
        # in src/wave_programs.asm and src/wave_encounters.asm until Phase 3.
        assert sorted(p.name for p in g1) == [
            "stage_charset.asm", "stage_config.asm", "stage_map.asm",
            "stage_turrets.asm"], [p.name for p in g1]
        assert not (td / f"{name}-g1" / "stage_waves.asm").exists(), \
            "the exporter must not emit stage_waves.asm"
ok("each level: load -> edit -> save -> reload -> export round-trips; "
   "4-file deterministic export, no stage_waves.asm")

# 5. re-running build_levels is byte-identical (deterministic per-level export)
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    e = load_engine_data(REPO)
    for proj in (build_levels.build_level1(e), build_levels.build_level2()):
        d1 = export_level(proj, td / f"{proj.name}-a", engine_data=e)
        d2 = export_level(proj, td / f"{proj.name}-b", engine_data=e)
        assert all(x.read_bytes() == y.read_bytes() for x, y in zip(d1, d2))
# and the two levels' dirs are different paths
assert L1 != L2 and L1.name == "level1" and L2.name == "level2"
ok("per-level export deterministic; level1/ and level2/ are separate output dirs")

# 6. the authoritative repository level directory is src/level1, and this test
#    never wrote to it.
AUTHORITATIVE = REPO / "src" / "level1"
assert (AUTHORITATIVE / "stage_map.asm").is_file(), AUTHORITATIVE
assert not (REPO / "src" / "generated").exists(), \
    "src/generated/ is the retired output path and must not reappear"
assert _GEN not in AUTHORITATIVE.parents
ok("the production level directory is src/level1/ and src/generated/ is gone")

print(f"\nAll {len(PASS)} level-package checks passed.")
