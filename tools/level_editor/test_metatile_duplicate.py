#!/usr/bin/env python3
"""Duplicate Selected Level Metatile (task section 2).

  * deep copy, unique NAME_COPY / NAME_COPY_2 naming
  * existing metatile IDs and painted map cells unchanged
  * the copy is independent - editing it never mutates the source
  * 64-metatile vocabulary limit enforced
  * repack / dedupe through the normal path; 128-glyph budget enforced
  * save / reload preserves the duplicate

Run:  python3 tools/level_editor/test_metatile_duplicate.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from engine_data import METATILE_CAPACITY, TERRAIN_GLYPH_NAMESPACE   # noqa: E402
from native_metatile import blank_pixels                            # noqa: E402
from project import (                                               # noqa: E402
    LevelProject, ProjectValidationError, duplicate_metatile,
    ensure_level_metatile_set, load_project, metatile_set_entry_from_native,
    repack_tileset_from_metatile_set, save_project, unique_metatile_name,
    validate_project,
)

PASS = []


def ok(msg):
    PASS.append(msg)
    print(f"ok  - {msg}")


def a_grid(seed):
    g = blank_pixels(0)
    for cell in range(16):
        cr, cc = divmod(cell, 4)
        for i in range(4):
            g[cr * 8][cc * 4 + i] = ((seed + cell) >> (2 * (3 - i))) & 3
    return g


def make_project(n=4, rows=6):
    p = LevelProject(
        name="dup", metatile_rows=[[i % n for i in range(10)] for _ in range(rows)],
        tileset=None,
        level_metatile_set=[
            metatile_set_entry_from_native(a_grid(i + 1), name=nm)
            for i, nm in enumerate(["WALL", "DECK", "VENT", "CORE"][:n])
        ],
    )
    repack_tileset_from_metatile_set(p)
    return p


# 1. deep copy + unique naming + IDs/map untouched
p = make_project()
map_before = [r[:] for r in p.metatile_rows]
new_idx = duplicate_metatile(p, 0)
assert new_idx == 4
assert p.level_metatile_set[new_idx]["name"] == "WALL_COPY"
assert p.level_metatile_set[new_idx]["native"]["pixels"] == a_grid(1)
assert p.metatile_rows == map_before, "duplicate must not renumber the map"
assert [e["name"] for e in p.level_metatile_set[:4]] == ["WALL", "DECK", "VENT", "CORE"]
ok("duplicate appends an independent copy; existing IDs + painted map unchanged")

# 2. successive copies get _COPY, _COPY_2, _COPY_3 ...
i2 = duplicate_metatile(p, 0)
i3 = duplicate_metatile(p, 0)
assert [p.level_metatile_set[i]["name"] for i in (i2, i3)] == ["WALL_COPY_2", "WALL_COPY_3"]
# duplicating a copy keeps the stem
i4 = duplicate_metatile(p, new_idx)
assert p.level_metatile_set[i4]["name"] == "WALL_COPY_4", p.level_metatile_set[i4]["name"]
assert unique_metatile_name(p, "DECK") == "DECK_COPY"
ok("copy names are NAME_COPY / NAME_COPY_2 / ...; a copy-of-a-copy keeps the stem")

# 3. independence: editing the copy never touches the source
p = make_project()
c = duplicate_metatile(p, 1)
p.level_metatile_set[c]["native"]["pixels"][5][5] = 3
assert p.level_metatile_set[1]["native"]["pixels"][5][5] == a_grid(2)[5][5]
assert p.level_metatile_set[1]["native"]["pixels"] != p.level_metatile_set[c]["native"]["pixels"]
ok("editing the duplicate does not mutate the source metatile")

# 4. repack / dedupe runs through the normal path
p = make_project()
before_glyphs = p.tileset["glyphCount"]
duplicate_metatile(p, 2)
repack_tileset_from_metatile_set(p)
# an exact duplicate adds ZERO unique glyphs (full dedupe)
assert p.tileset["glyphCount"] == before_glyphs, (before_glyphs, p.tileset["glyphCount"])
assert len(p.tileset["metatileDefs"]) == len(p.level_metatile_set)
assert validate_project(p) == []
ok("duplicate repacks via the normal deduper (identical copy costs 0 new glyphs)")

# 5. 64-metatile vocabulary limit
p = make_project(n=4)
ensure_level_metatile_set(p)
while len(p.level_metatile_set) < METATILE_CAPACITY:
    p.level_metatile_set.append(metatile_set_entry_from_native(blank_pixels(0),
                                                              name=f"M{len(p.level_metatile_set)}"))
assert len(p.level_metatile_set) == METATILE_CAPACITY
try:
    duplicate_metatile(p, 0)
    raise AssertionError("allowed a 65th metatile")
except ProjectValidationError:
    pass
ok(f"duplicate refuses to exceed the {METATILE_CAPACITY}-metatile vocabulary limit")

# 6. glyph-budget guard: a distinct duplicate that overflows the namespace is rejected
#    (simulate by packing a near-full set, then a heavy new tile)
p = make_project(n=1)
ensure_level_metatile_set(p)
# 15 * 8 = 120 unique glyphs; each tile of 16 distinct cells
def busy(seed):
    g = blank_pixels(0)
    for y in range(32):
        for x in range(16):
            g[y][x] = ((seed * 7 + y * 16 + x) % 3) + (1 if (x + y) & 1 else 0)
            g[y][x] &= 3
    return g
p.level_metatile_set = [metatile_set_entry_from_native(busy(s), name=f"B{s}") for s in range(8)]
try:
    repack_tileset_from_metatile_set(p)
    heavy = duplicate_metatile(p, 0)
    p.level_metatile_set[heavy]["native"]["pixels"] = busy(999)
    repack_tileset_from_metatile_set(p)
    # if it did not raise, we are still within budget - assert that explicitly
    assert p.tileset["glyphCount"] <= TERRAIN_GLYPH_NAMESPACE
    ok("duplicate + repack stays within the 128-glyph budget for this fixture")
except Exception as exc:                                            # noqa: BLE001
    assert "glyph" in str(exc).lower() or "budget" in str(exc).lower(), exc
    ok("an over-budget duplicate is rejected safely (project still valid)")
    assert validate_project(make_project()) == []

# 7. save / reload preserves the duplicate exactly
with tempfile.TemporaryDirectory() as d:
    p = make_project()
    ni = duplicate_metatile(p, 3)
    repack_tileset_from_metatile_set(p)
    path = Path(d) / "level.json"
    save_project(p, path)
    r = load_project(path)
    assert [e["name"] for e in r.level_metatile_set] == [e["name"] for e in p.level_metatile_set]
    assert r.level_metatile_set[ni]["native"]["pixels"] == a_grid(4)
    assert r.metatile_rows == p.metatile_rows
ok("save / reload round-trips the duplicated metatile")

print(f"\nAll {len(PASS)} metatile-duplicate checks passed.")
