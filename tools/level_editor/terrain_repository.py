"""Reusable Terrain Asset Repository for the 19656 level editor.

A persistent, schema-versioned, human-inspectable store of native C64 terrain
metatiles that outlives any single level project. It holds OUR native derivative
(16 logical multicolour pixels x 32 rows, values 0..3) plus provenance - never a
redistributed copy of a third-party source PNG.

Location:   tools/level_editor/terrain_repository/repository.json
Format:     one deterministic JSON document
                { "schemaVersion": 1, "assets": [ <asset>... sorted by id ] }
            <asset> = {
                "id":   "asset_0001",        # stable, unique, sortable
                "name": "Crater rim NW",
                "native": { "width": 16, "height": 32, "pixels": [[0..3]*16]*32 },
                "provenance": {               # all fields optional, descriptive only
                    "sourcePack":     "Dithart's FREE Sci-fi Tileset v0.1",
                    "sourceTileIndex": 42,
                    "sourceCoords":   [col, row],
                    "sourceTileSize": [32, 32],
                    "licenceNote":    "Derivative work; original pack not redistributed.",
                    "localSourcePath":"/abs/path/tileset_for_free.png"   # informational
                },
                "notes": "",
                "tags":  ["crater", "rock"]
            }

Determinism: json.dumps(sort_keys=True, indent=2) + trailing newline, assets
sorted by id, NO timestamps (so re-saving an unchanged repo is a no-op diff and
correctness never depends on a volatile field or an external file).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from native_metatile import NATIVE_H, NATIVE_W, pixels_to_rowstrings, validate_pixels

SCHEMA_VERSION = 1
DEFAULT_REPO_DIRNAME = "terrain_repository"
DEFAULT_REPO_FILENAME = "repository.json"

_ID_RE = re.compile(r"^asset_(\d{4,})$")
_PROVENANCE_KEYS = (
    "sourcePack", "sourceTileIndex", "sourceCoords", "sourceTileSize",
    "licenceNote", "localSourcePath",
)


class TerrainRepositoryError(ValueError):
    """Malformed repository document or asset."""


def default_repo_path(editor_dir=None):
    base = Path(editor_dir) if editor_dir else Path(__file__).resolve().parent
    return base / DEFAULT_REPO_DIRNAME / DEFAULT_REPO_FILENAME


def _canon_provenance(raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TerrainRepositoryError("provenance must be an object")
    out = {}
    for key in _PROVENANCE_KEYS:
        if key not in raw or raw[key] in (None, ""):
            continue
        value = raw[key]
        if key in ("sourceCoords", "sourceTileSize"):
            if (not isinstance(value, (list, tuple)) or len(value) != 2
                    or any(not isinstance(v, int) or isinstance(v, bool) for v in value)):
                raise TerrainRepositoryError(f"provenance.{key} must be [int, int]")
            out[key] = [int(value[0]), int(value[1])]
        elif key == "sourceTileIndex":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TerrainRepositoryError("provenance.sourceTileIndex must be a non-negative int")
            out[key] = int(value)
        else:
            out[key] = str(value)
    return out


def _canon_native(raw):
    if not isinstance(raw, dict):
        raise TerrainRepositoryError("asset.native must be an object")
    pixels = validate_pixels(raw.get("pixels"))
    return {"width": NATIVE_W, "height": NATIVE_H, "pixels": pixels}


def canonical_asset(raw):
    """Validate + normalise one asset dict into its canonical serialised form."""
    if not isinstance(raw, dict):
        raise TerrainRepositoryError("asset must be an object")
    asset_id = raw.get("id")
    if not isinstance(asset_id, str) or not _ID_RE.match(asset_id):
        raise TerrainRepositoryError(f"asset.id must match asset_NNNN; got {asset_id!r}")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TerrainRepositoryError(f"asset {asset_id}: name must be a non-empty string")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise TerrainRepositoryError(f"asset {asset_id}: tags must be a list of strings")
    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise TerrainRepositoryError(f"asset {asset_id}: notes must be a string")
    return {
        "id": asset_id,
        "name": name.strip(),
        "native": _canon_native(raw.get("native")),
        "provenance": _canon_provenance(raw.get("provenance")),
        "notes": notes,
        "tags": sorted(tags),
    }


class TerrainRepository:
    def __init__(self, assets=None, path=None, schema_version=SCHEMA_VERSION):
        self.path = Path(path) if path else None
        self.schema_version = schema_version
        self._assets = {}
        for a in (assets or []):
            c = canonical_asset(a)
            self._assets[c["id"]] = c

    # -- persistence ------------------------------------------------------
    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls(path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TerrainRepositoryError(f"{path}: invalid JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise TerrainRepositoryError(f"{path}: root must be an object")
        version = data.get("schemaVersion")
        if version not in (SCHEMA_VERSION,):
            raise TerrainRepositoryError(
                f"{path}: unsupported schemaVersion {version!r} (this build writes {SCHEMA_VERSION})"
            )
        raw_assets = data.get("assets", [])
        if not isinstance(raw_assets, list):
            raise TerrainRepositoryError(f"{path}: assets must be a list")
        repo = cls(assets=raw_assets, path=path, schema_version=version)
        return repo

    def to_dict(self, *, serialised=False):
        """In-memory form keeps native.pixels as 32 lists of 16 ints;
        serialised=True writes the compact 32 "0".."3" row-string form."""
        assets = []
        for i in sorted(self._assets):
            a = self._assets[i]
            if serialised:
                a = dict(a)
                a["native"] = dict(a["native"])
                a["native"]["pixels"] = pixels_to_rowstrings(a["native"]["pixels"])
            assets.append(a)
        return {"schemaVersion": self.schema_version, "assets": assets}

    def dumps(self):
        return json.dumps(self.to_dict(serialised=True), indent=2, sort_keys=True,
                          ensure_ascii=False) + "\n"

    def save(self, path=None):
        target = Path(path) if path else self.path
        if target is None:
            raise TerrainRepositoryError("no path to save the repository to")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.dumps(), encoding="utf-8")
        self.path = target

    # -- queries --------------------------------------------------------
    def __len__(self):
        return len(self._assets)

    def ids(self):
        return sorted(self._assets)

    def list(self):
        return [self._assets[i] for i in sorted(self._assets)]

    def get(self, asset_id):
        if asset_id not in self._assets:
            raise KeyError(f"no terrain asset {asset_id!r} in the repository")
        return self._assets[asset_id]

    def has(self, asset_id):
        return asset_id in self._assets

    def _next_id(self):
        used = {int(_ID_RE.match(i).group(1)) for i in self._assets}
        n = 1
        while n in used:
            n += 1
        return f"asset_{n:04d}"

    # -- mutation -----------------------------------------------------
    def add_asset(self, name, native_pixels, *, provenance=None, notes="",
                  tags=None, asset_id=None):
        asset_id = asset_id or self._next_id()
        if asset_id in self._assets:
            raise TerrainRepositoryError(f"asset id {asset_id!r} already exists")
        asset = canonical_asset({
            "id": asset_id, "name": name, "native": {"pixels": native_pixels},
            "provenance": provenance or {}, "notes": notes, "tags": list(tags or []),
        })
        self._assets[asset_id] = asset
        return asset

    def update_asset(self, asset_id, *, name=None, native_pixels=None,
                     provenance=None, notes=None, tags=None):
        current = dict(self.get(asset_id))
        if name is not None:
            current["name"] = name
        if native_pixels is not None:
            current["native"] = {"pixels": native_pixels}
        if provenance is not None:
            current["provenance"] = provenance
        if notes is not None:
            current["notes"] = notes
        if tags is not None:
            current["tags"] = list(tags)
        self._assets[asset_id] = canonical_asset(current)
        return self._assets[asset_id]

    def remove(self, asset_id):
        self._assets.pop(asset_id, None)

    def snapshot(self, asset_id):
        """A deep, standalone copy of an asset's native pixels + provenance, for
        embedding into a level package. The project keeps this copy as the
        authoritative data, so a later edit/delete of the repository asset can
        never make an existing level fail to build (task section 25)."""
        a = self.get(asset_id)
        return {
            "pixels": [row[:] for row in a["native"]["pixels"]],
            "name": a["name"],
            "provenance": dict(a["provenance"]),
            "repositoryAssetId": asset_id,
        }
