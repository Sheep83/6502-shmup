#!/usr/bin/env python3
"""Recover the project's complete GENERATED native terrain set into the Terrain
Asset Repository.

The generated set is authored deterministically in
``tools/level_editor/native_terrain_tiles.py`` (the "terrain workshop" bas-relief
sci-fi vocabulary: ~31 native 16x32 metatiles built from reusable 4x8 cells). This
tool copies that authoritative generator's output into the repository as ordinary
repository assets - not a special class - so they can then be edited / imported /
promoted like any other asset.

  * The user's existing repository assets are NEVER overwritten or removed.
  * An identical asset (same 16x32 logical pixels) that is already present is
    left alone - a deterministic fingerprint check avoids meaningless duplicates.
  * Recovered assets are tagged ``generated`` + ``sci-fi-terrain`` and carry a
    provenance note pointing at the generator, so they are identifiable later.
  * Serialisation stays deterministic (no timestamps).

    python3 tools/level_editor/recover_generated_terrain.py            # apply
    python3 tools/level_editor/recover_generated_terrain.py --dry-run  # report only
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import native_terrain_tiles as ntt                                   # noqa: E402
from native_metatile import validate_pixels                          # noqa: E402
from terrain_repository import TerrainRepository, default_repo_path   # noqa: E402

GENERATED_TAGS = ["generated", "sci-fi-terrain"]
GENERATED_SOURCE_PACK = "19656 generated native terrain set (native_terrain_tiles.py)"


def _fingerprint(pixels):
    return tuple(tuple(row) for row in validate_pixels(pixels))


def recover_generated_set(repo, *, dry_run=False):
    """Add every generated native metatile missing from `repo`.

    Returns a dict:
      generated   total metatiles the generator defines
      added       [(name, asset_id), ...] newly created assets (empty if dry_run)
      existing    [(name, matched_asset_id), ...] already present, left untouched
    """
    existing_prints = {}
    for a in repo.list():
        existing_prints.setdefault(_fingerprint(a["native"]["pixels"]), a["id"])

    added, existing = [], []
    for name, pixels in ntt.metatiles():
        fp = _fingerprint(pixels)
        if fp in existing_prints:
            existing.append((name, existing_prints[fp]))
            continue
        if dry_run:
            added.append((name, None))
            continue
        asset = repo.add_asset(
            name, pixels,
            provenance={"sourcePack": GENERATED_SOURCE_PACK},
            notes="Recovered from the deterministic native terrain generator.",
            tags=list(GENERATED_TAGS),
        )
        existing_prints[fp] = asset["id"]
        added.append((name, asset["id"]))
    return {"generated": len(ntt.names()), "added": added, "existing": existing}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv
    repo_path = default_repo_path(HERE)
    repo = TerrainRepository.load(repo_path)
    before = len(repo)
    result = recover_generated_set(repo, dry_run=dry_run)
    if not dry_run and result["added"]:
        repo.save(repo_path)

    print(f"generated set: {result['generated']} native metatiles "
          f"(source: native_terrain_tiles.py)")
    print(f"repository:    {before} asset(s) before -> {len(repo)} after"
          + ("  [dry-run: nothing written]" if dry_run else ""))
    print(f"  added:    {len(result['added'])}"
          + ("" if not result["added"]
             else "  (" + ", ".join(n for n, _ in result["added"]) + ")"))
    print(f"  skipped:  {len(result['existing'])} already present (identical artwork, left untouched)")
    for n, aid in result["existing"]:
        print(f"            {n} == {aid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
