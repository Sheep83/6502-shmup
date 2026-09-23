#!/usr/bin/env python3
"""End-to-end Terrain Asset Workshop acceptance (task sections 13-30, 39).

Headless run of the whole authoring pipeline:

  open source sheet -> slice 32x32 -> import one tile -> convert to native
  16x32 C64 multicolour -> (simulated) manual edit -> save to the reusable
  Terrain Asset Repository WITH provenance -> snapshot that asset into ONE level
  package's metatile set -> prove the OTHER level keeps its own independent
  tileset -> repack + export both level packages -> confirm the generated
  engine sources differ and each is internally consistent.

Uses DithArt's sheet (~/Desktop/Ditharts_Free_Scifi_Tileset_v01/texture/
tileset_for_free.png) when present - as an EXTERNAL fixture, never copied into
the repo - otherwise the committed synthetic sheet. Nothing is committed and no
existing level.json is modified (a temp copy of the packages is used).

    python3 tools/level_editor/acceptance_terrain_workshop.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from engine_data import load_engine_data                            # noqa: E402
from ka_export import export_level                                  # noqa: E402
from native_metatile import pixels_to_glyphs                        # noqa: E402
from project import (                                               # noqa: E402
    ensure_level_metatile_set, load_project, metatile_set_entry_from_native,
    metatile_set_glyph_cost, repack_tileset_from_metatile_set, save_project,
    validate_project,
)
from spritesheet import slice_sheet                                 # noqa: E402
from terrain_convert import source_tile_to_native                   # noqa: E402
from terrain_repository import TerrainRepository                    # noqa: E402

DITHART = Path.home() / "Desktop" / "Ditharts_Free_Scifi_Tileset_v01" / "texture" / "tileset_for_free.png"
SYNTH = HERE / "testdata" / "synthetic_tileset.png"
STEPS = []


def step(msg):
    STEPS.append(msg)
    print(f"ok  - {msg}")


def main():
    # -- source sheet (external DithArt if available, else committed synthetic) --
    if DITHART.exists():
        sheet_path, sheet_kind = DITHART, "DithArt FREE Sci-fi Tileset v0.1 (external, not bundled)"
    else:
        if not SYNTH.exists():
            subprocess.run([sys.executable, str(HERE / "make_test_spritesheet.py")], check=True)
        sheet_path, sheet_kind = SYNTH, "synthetic committed fixture"
    sheet = slice_sheet(sheet_path, 32, 32)
    assert sheet.tile_count >= 100, sheet.tile_count
    step(f"opened source sheet ({sheet_kind}): {sheet.width}x{sheet.height}px "
         f"-> {sheet.cols_count}x{sheet.rows_count} = {sheet.tile_count} tiles of 32x32")

    # -- pick one recognisable tile and convert it to native 16x32 C64 MC -------
    tile_index = 42 if sheet.tile_count > 42 else sheet.tile_count // 2
    src_tile = sheet.tile(tile_index)
    col, row = sheet.tile_coords(tile_index)
    project_palette = {"background": 0, "multicolour1": 11, "multicolour2": 14, "character": 1}
    native = source_tile_to_native(src_tile, project_palette)
    assert len(native) == 32 and all(len(r) == 16 and all(0 <= v <= 3 for v in r) for r in native)
    step(f"imported tile #{tile_index} (grid {col},{row}) and converted to a "
         f"16x32 logical-multicolour grid (values 0..3)")

    # -- simulate a manual edit: repair a couple of pixels ---------------------
    native[0][0] = (native[0][0] + 1) % 4
    native[31][15] = (native[31][15] + 2) % 4
    step("applied a manual native-pixel edit (artefact repair)")

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # -- save to the reusable repository WITH provenance ------------------
        repo_path = d / "terrain_repository" / "repository.json"
        repo = TerrainRepository(path=repo_path)
        asset = repo.add_asset(
            "Acceptance ridge",
            native,
            provenance={
                "sourcePack": ("Dithart's FREE Sci-fi Tileset v0.1"
                               if sheet_path == DITHART else "synthetic test sheet"),
                "sourceTileIndex": tile_index,
                "sourceCoords": [col, row],
                "sourceTileSize": [32, 32],
                "licenceNote": ("Derivative work; original pack not redistributed."
                                if sheet_path == DITHART else "test fixture"),
                "localSourcePath": str(sheet_path),
            },
            notes="workshop acceptance asset",
            tags=["acceptance", "ridge"],
        )
        repo.save()
        reloaded = TerrainRepository.load(repo_path)
        assert reloaded.get(asset["id"])["native"]["pixels"] == native
        assert reloaded.get(asset["id"])["provenance"]["sourceTileIndex"] == tile_index
        assert reloaded.dumps() == repo.dumps()          # deterministic
        step(f"saved native derivative to the repository as {asset['id']} with full "
             f"provenance; reload is byte-identical (deterministic, no timestamps)")

        # -- work on a temp copy of the two committed level packages ---------
        # THE TWO v5 PACKAGES ARE FIXTURES NOW, not live levels. They used to
        # sit in levels/level1/ and levels/level2/ beside the authoritative v6
        # documents, where they were indistinguishable from current level data;
        # they live under fixtures/legacy_v5/ so that this script -- and the
        # migration tests -- keep a frozen v5 input without anything in
        # levels/ being mistakable for it. Still copied to temp before use.
        legacy_src = HERE / "fixtures" / "legacy_v5"
        legacy = d / "legacy_v5"
        shutil.copytree(legacy_src, legacy)
        engine = load_engine_data(REPO)
        l1 = load_project(legacy / "level1" / "level.json")
        l2 = load_project(legacy / "level2" / "level.json")
        ensure_level_metatile_set(l1)
        ensure_level_metatile_set(l2)
        l1_set_len_before = len(l1.level_metatile_set)
        l2_glyphs_before = [list(g) for g in l2.tileset["glyphs"]]
        l2_defs_before = [list(x) for x in l2.tileset["metatileDefs"]]

        # -- glyph-budget readout before adding -----------------------------
        cost = metatile_set_glyph_cost(l1, candidate_pixels=native)
        step(f"Level 1 terrain glyphs: {cost['used']}/{cost['capacity']}  |  "
             f"this asset: 16 cells, {cost['candidate_reuse']} existing reused, "
             f"{cost['candidate_new']} new unique required")
        assert cost["used"] + cost["candidate_new"] <= cost["capacity"], "would exceed budget"

        # -- snapshot the repo asset into LEVEL 1 only ----------------------
        snap = repo.snapshot(asset["id"])
        l1.level_metatile_set.append(metatile_set_entry_from_native(
            snap["pixels"], name=snap["name"],
            source={"repositoryAssetId": snap["repositoryAssetId"],
                    "provenance": snap["provenance"]},
        ))
        repack_tileset_from_metatile_set(l1)
        assert validate_project(l1) == [], validate_project(l1)
        assert len(l1.level_metatile_set) == l1_set_len_before + 1
        new_id = len(l1.level_metatile_set) - 1
        # use the new metatile somewhere in the map so it is a live ID > 15
        l1.metatile_rows[1][1] = new_id
        assert validate_project(l1) == []
        step(f"snapshotted {asset['id']} into Level 1 as metatile ID {new_id} "
             f"(> 15) and painted it into the map")

        # -- prove LEVEL 2 is untouched ------------------------------------
        assert l2.tileset["glyphs"] == l2_glyphs_before
        assert l2.tileset["metatileDefs"] == l2_defs_before
        assert len(l2.level_metatile_set) == 16
        # the repo edit/delete cannot reach into Level 1's copy either
        repo.update_asset(asset["id"], native_pixels=[[0] * 16 for _ in range(32)])
        repo.remove(asset["id"])
        assert l1.level_metatile_set[new_id]["native"]["pixels"] == snap["pixels"]
        step("Level 2's tileset is byte-for-byte unchanged; Level 1's snapshot "
             "survives a later repository edit + delete (independent copies)")

        # -- export both packages; confirm they differ and are consistent --
        out1, out2 = d / "gen" / "level1", d / "gen" / "level2"
        save_project(l1, legacy / "level1" / "level.json")
        save_project(l2, legacy / "level2" / "level.json")
        p1 = export_level(l1, out1, engine_data=engine)
        p2 = export_level(l2, out2, engine_data=engine)
        cfg1 = (out1 / "stage_config.asm").read_text()
        cfg2 = (out2 / "stage_config.asm").read_text()
        def _count(cfg):
            line = [l for l in cfg.splitlines()
                    if l.strip().startswith(".const STAGE_METATILE_COUNT")][0]
            return int(line.split("=", 1)[1].strip())
        n1, n2 = _count(cfg1), _count(cfg2)
        assert n1 == l1_set_len_before + 1, (n1, l1_set_len_before)
        assert n2 == len(l2.level_metatile_set), (n2,)
        assert (out1 / "stage_map.asm").read_text() != (out2 / "stage_map.asm").read_text()
        # re-export is deterministic
        p1b = export_level(l1, d / "gen2" / "level1", engine_data=engine)
        assert (out1 / "stage_map.asm").read_text() == (d / "gen2" / "level1" / "stage_map.asm").read_text()
        step(f"exported both packages independently: Level 1 STAGE_METATILE_COUNT={n1}, "
             f"Level 2 STAGE_METATILE_COUNT={n2}; re-export byte-identical")

    print(f"\nPASS: terrain-workshop end-to-end acceptance ({len(STEPS)} steps). "
          f"Source: {sheet_kind}. No files committed; committed level.json untouched.")


if __name__ == "__main__":
    main()
