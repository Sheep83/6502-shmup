"""Global Wave Definition Repository for the 19656 level editor.

A persistent, schema-versioned, human-inspectable store of reusable enemy-wave
DEFINITIONS - the "what" of an encounter - that outlives any single level
project. It is the wave analogue of terrain_repository.TerrainRepository.

Location:   tools/level_editor/wave_repository/repository.json
Format:     one deterministic JSON document
                { "schemaVersion": 1, "definitions": [ <def>... sorted by id ] }
            <def> = {
                "id":            "wave_0001",     # stable, unique, sortable
                "name":          "Alpha sweep",
                "attackId":      0,               # engine ATTACK_* catalogue id
                "composition":   [ {"enemyType": 0, "count": 5}, ... ],
                "spawnInterval": null | 1..255,   # null => attack-table default
                "notes":         "",
                "tags":          ["intro", "sweep"]
            }

A repository definition holds ONLY the reusable fields the level's own wave
definition schema already supports. It deliberately carries NO level-specific
trigger placement (`worldRow` lives on a wave TRIGGER, never here) and no
`id` collision with a level: copying into a level always assigns a fresh
level-local id.

Determinism: json.dumps(sort_keys=True, indent=2) + trailing newline,
definitions sorted by id, NO timestamps - re-saving an unchanged repository is a
no-op diff and correctness never depends on a volatile field.

Snapshot semantics (mirrors the Terrain Asset Repository):

    Global Wave Repository  --copy-->  level waveDefinitions  <--ref--  triggers

`snapshot()` returns a standalone level-local wave-definition dict. After the
copy the two are fully independent: a later global rename / edit / delete cannot
change the level, and editing the level copy cannot change the global asset.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_REPO_DIRNAME = "wave_repository"
DEFAULT_REPO_FILENAME = "repository.json"

_ID_RE = re.compile(r"^wave_(\d{4,})$")

# Kept in sync with engine_data / project.py. Imported lazily so this module has
# no hard dependency on the Tk editor stack.
_ENEMY_TYPE_COUNT = 4
_ATTACK_COUNT = 12
_MAX_COMPOSITION_COUNT = 8


class WaveRepositoryError(ValueError):
    """Malformed wave-repository document or definition."""


def default_repo_path(editor_dir=None):
    base = Path(editor_dir) if editor_dir else Path(__file__).resolve().parent
    return base / DEFAULT_REPO_DIRNAME / DEFAULT_REPO_FILENAME


def _canon_composition(raw):
    if not isinstance(raw, list) or not raw:
        raise WaveRepositoryError("composition must be a non-empty list")
    out = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            raise WaveRepositoryError(f"composition[{i}] must be an object")
        et = c.get("enemyType", 0)
        cn = c.get("count", 1)
        if isinstance(et, bool) or not isinstance(et, int) or not 0 <= et < _ENEMY_TYPE_COUNT:
            raise WaveRepositoryError(
                f"composition[{i}].enemyType must be 0..{_ENEMY_TYPE_COUNT - 1}"
            )
        if isinstance(cn, bool) or not isinstance(cn, int) or not 1 <= cn <= _MAX_COMPOSITION_COUNT:
            raise WaveRepositoryError(
                f"composition[{i}].count must be 1..{_MAX_COMPOSITION_COUNT}"
            )
        out.append({"enemyType": int(et), "count": int(cn)})
    return out


def canonical_definition(raw):
    """Validate + normalise one wave definition into its canonical form."""
    if not isinstance(raw, dict):
        raise WaveRepositoryError("wave definition must be an object")
    def_id = raw.get("id")
    if not isinstance(def_id, str) or not _ID_RE.match(def_id):
        raise WaveRepositoryError(f"wave definition id must match wave_NNNN; got {def_id!r}")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WaveRepositoryError(f"wave definition {def_id}: name must be a non-empty string")
    attack_id = raw.get("attackId", 0)
    if isinstance(attack_id, bool) or not isinstance(attack_id, int) or not 0 <= attack_id < _ATTACK_COUNT:
        raise WaveRepositoryError(
            f"wave definition {def_id}: attackId must be 0..{_ATTACK_COUNT - 1}"
        )
    interval = raw.get("spawnInterval", None)
    if interval in (None, ""):
        interval = None
    elif isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 255:
        raise WaveRepositoryError(
            f"wave definition {def_id}: spawnInterval must be null or 1..255"
        )
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise WaveRepositoryError(f"wave definition {def_id}: tags must be a list of strings")
    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise WaveRepositoryError(f"wave definition {def_id}: notes must be a string")
    if "worldRow" in raw:
        raise WaveRepositoryError(
            f"wave definition {def_id}: worldRow is trigger placement and must not be stored globally"
        )
    return {
        "id": def_id,
        "name": name.strip(),
        "attackId": int(attack_id),
        "composition": _canon_composition(raw.get("composition")),
        "spawnInterval": interval,
        "notes": notes,
        "tags": sorted(tags),
    }


class WaveRepository:
    def __init__(self, definitions=None, path=None, schema_version=SCHEMA_VERSION):
        self.path = Path(path) if path else None
        self.schema_version = schema_version
        self._defs = {}
        for d in (definitions or []):
            c = canonical_definition(d)
            self._defs[c["id"]] = c

    # -- persistence ------------------------------------------------------
    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls(path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WaveRepositoryError(f"{path}: invalid JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise WaveRepositoryError(f"{path}: root must be an object")
        version = data.get("schemaVersion")
        if version not in (SCHEMA_VERSION,):
            raise WaveRepositoryError(
                f"{path}: unsupported schemaVersion {version!r} (this build writes {SCHEMA_VERSION})"
            )
        raw_defs = data.get("definitions", [])
        if not isinstance(raw_defs, list):
            raise WaveRepositoryError(f"{path}: definitions must be a list")
        return cls(definitions=raw_defs, path=path, schema_version=version)

    def to_dict(self):
        return {
            "schemaVersion": self.schema_version,
            "definitions": [self._defs[i] for i in sorted(self._defs)],
        }

    def dumps(self):
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def save(self, path=None):
        target = Path(path) if path else self.path
        if target is None:
            raise WaveRepositoryError("no path to save the wave repository to")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.dumps(), encoding="utf-8")
        self.path = target

    # -- queries --------------------------------------------------------
    def __len__(self):
        return len(self._defs)

    def ids(self):
        return sorted(self._defs)

    def list(self):
        return [self._defs[i] for i in sorted(self._defs)]

    def get(self, def_id):
        if def_id not in self._defs:
            raise KeyError(f"no wave definition {def_id!r} in the repository")
        return self._defs[def_id]

    def has(self, def_id):
        return def_id in self._defs

    def _next_id(self):
        used = {int(_ID_RE.match(i).group(1)) for i in self._defs}
        n = 1
        while n in used:
            n += 1
        return f"wave_{n:04d}"

    # -- mutation -----------------------------------------------------
    def add_definition(self, name, attack_id, composition, *, spawn_interval=None,
                       notes="", tags=None, def_id=None):
        def_id = def_id or self._next_id()
        if def_id in self._defs:
            raise WaveRepositoryError(f"wave definition id {def_id!r} already exists")
        d = canonical_definition({
            "id": def_id, "name": name, "attackId": attack_id,
            "composition": [dict(c) for c in composition],
            "spawnInterval": spawn_interval, "notes": notes, "tags": list(tags or []),
        })
        self._defs[def_id] = d
        return d

    def add_from_level_definition(self, level_def, *, name=None, tags=None, notes=""):
        """Promote a level-local wave definition dict (which carries a level-local
        `id` and no `worldRow`) to the global library under a fresh repo id."""
        return self.add_definition(
            name or level_def.get("name", "wave"),
            int(level_def.get("attackId", 0)),
            level_def.get("composition") or [{"enemyType": 0, "count": 5}],
            spawn_interval=level_def.get("spawnInterval"),
            notes=notes, tags=tags,
        )

    def update_definition(self, def_id, *, name=None, attack_id=None, composition=None,
                          spawn_interval="__keep__", notes=None, tags=None):
        current = dict(self.get(def_id))
        if name is not None:
            current["name"] = name
        if attack_id is not None:
            current["attackId"] = attack_id
        if composition is not None:
            current["composition"] = [dict(c) for c in composition]
        if spawn_interval != "__keep__":
            current["spawnInterval"] = spawn_interval
        if notes is not None:
            current["notes"] = notes
        if tags is not None:
            current["tags"] = list(tags)
        self._defs[def_id] = canonical_definition(current)
        return self._defs[def_id]

    def remove(self, def_id):
        self._defs.pop(def_id, None)

    def snapshot(self, def_id, *, local_id):
        """A standalone level-local wave-definition dict for embedding in a level
        package. `local_id` is the level-local id the caller allocates (repo ids
        and level ids are independent namespaces). The returned dict is a deep
        copy carrying only the fields the level's own wave-definition schema
        already stores, so the level stays self-contained and byte-identical in
        shape to a hand-authored definition. After the copy the two are fully
        independent: a later global edit/delete cannot change the level."""
        d = self.get(def_id)
        return {
            "id": str(local_id),
            "name": d["name"],
            "attackId": int(d["attackId"]),
            "composition": [dict(c) for c in d["composition"]],
            "spawnInterval": d["spawnInterval"],
        }
