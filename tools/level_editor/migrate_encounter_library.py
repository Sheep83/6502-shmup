#!/usr/bin/env python3
"""One-shot: lift the shared encounter vocabulary out of the level documents.

    python3 tools/level_editor/migrate_encounter_library.py --check
    python3 tools/level_editor/migrate_encounter_library.py

Reads every level under levels/, folds their EMBEDDED movementPrograms and
waveDefinitions into tools/level_editor/encounter_library.v6.json, and rewrites
each level document without them. Triggers and noSpawnRow are level-specific and
are not touched by any of this.

SAFE BY REFUSAL, not by cleverness. Two different definitions sharing one id is
an authoring question, so the migration stops and names both rather than picking
a winner. Nothing unique is ever dropped: an asset only one level has is added
to the library like any other.

Re-running it is a no-op once the levels carry no embedded assets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import encounter_library                                        # noqa: E402
from encounter_library import EncounterLibrary, LibraryConflict  # noqa: E402
import migration_v6                                             # noqa: E402

LEVELS = HERE / "levels"

# LEVEL 1 FIRST, DELIBERATELY. The two production levels currently hold
# identical vocabularies, so order cannot matter today -- but Level 1 is the
# level Brian actually authors, so if they ever diverge it is the one whose
# version should land in the library first and the other's that should be
# reported as a conflict rather than quietly winning.
PREFERRED_ORDER = ("level1", "level2")


def level_documents():
    found = {p.parent.name: p for p in sorted(LEVELS.glob("*/level.v6.json"))}
    ordered = [found.pop(n) for n in PREFERRED_ORDER if n in found]
    return ordered + [found[k] for k in sorted(found)]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    for a in argv:
        if a != "--check":
            raise SystemExit(f"unknown argument {a!r}")

    lib = EncounterLibrary.load_or_empty()
    print(f"  library before: {lib.summary()}")

    docs = level_documents()
    if not docs:
        raise SystemExit(f"no level documents under {LEVELS}")

    embedded, notices = [], []
    for path in docs:
        raw = json.loads(path.read_text(encoding="utf-8"))
        has = [k for k in ("movementPrograms", "waveDefinitions") if raw.get(k)]
        project = migration_v6.load_any(path).project
        n_trig = len(project.triggers)
        if has:
            embedded.append(path)
            try:
                notices += lib.reconcile(project, f"{path.parent.name}/{path.name}")
            except LibraryConflict as e:
                print(f"\n  MIGRATION REFUSED\n  {e}\n", file=sys.stderr)
                return 2
        print(f"  {path.parent.name}: {'embedded ' + '+'.join(has) if has else 'no embedded assets'}"
              f"  ({n_trig} triggers, noSpawnRow {project.stage.no_spawn_row})")

    for n in notices:
        print(f"    {n}")
    print(f"  library after:  {lib.summary()}")

    if check_only:
        print("  --check: nothing written")
        return 0

    lib.save()
    print(f"  wrote {lib.path.relative_to(HERE.parent.parent)}")

    for path in docs:
        raw = json.loads(path.read_text(encoding="utf-8"))
        before = len(raw.get("movementPrograms") or []), len(raw.get("waveDefinitions") or [])
        project = migration_v6.load_any(path).project
        text = project.to_level_json()
        # THE SHARED KEYS MUST BE GONE AND NOTHING ELSE MAY HAVE MOVED.
        after = json.loads(text)
        assert "movementPrograms" not in after and "waveDefinitions" not in after
        for key in ("stage", "palette", "glyphs", "metatileDefs", "map",
                    "turrets", "triggers", "levelMetatileSet", "name"):
            if key in raw:
                assert json.dumps(after.get(key), sort_keys=True) == \
                       json.dumps(raw.get(key), sort_keys=True), \
                       f"{path.parent.name}: {key} changed during migration"
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"  rewrote {path.parent.name}/level.v6.json "
              f"(dropped {before[0]} programs + {before[1]} definitions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
