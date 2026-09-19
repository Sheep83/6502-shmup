#!/usr/bin/env python3
"""Regenerate a level's assembler source from its v6 project. The one way to do it.

    python3 tools/level_editor/export_level.py                    # level 1 -> src/level1
    python3 tools/level_editor/export_level.py --check            # validate only
    python3 tools/level_editor/export_level.py --dest /tmp/out    # somewhere else

THE JSON IS THE EDITABLE SOURCE; the .asm files under src/<level>/ are derived.
This does not run from the Makefile, and that is deliberate: regenerating source
on every build would make `make` able to change the program's content, so the
generation step is explicit and its output is reviewable in the diff.

Exits non-zero on a validation failure or an export refusal, and writes nothing
when it does.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import export_v6                                                    # noqa: E402
from project_v6 import ProjectV6, ProjectV6Error                     # noqa: E402
from validation_v6 import validate                                   # noqa: E402

DEFAULT_PROJECT = HERE / "levels" / "level1" / "level.v6.json"
DEFAULT_DEST = REPO / "src" / "level1"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT,
                    help="v6 project JSON (default: the canonical Level 1)")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                    help="output directory (default: src/level1)")
    ap.add_argument("--level-name", default=None,
                    help="name for the generated headers (default: the project's)")
    ap.add_argument("--check", action="store_true",
                    help="validate only; write nothing")
    args = ap.parse_args(argv)

    try:
        project = ProjectV6.load(args.project)
    except (OSError, ProjectV6Error, ValueError) as exc:
        print(f"could not load {args.project}: {exc}", file=sys.stderr)
        return 2

    result = validate(project)
    for issue in result.warnings:
        print(f"warning: {issue}", file=sys.stderr)
    if not result.ok:
        for issue in result.errors:
            print(f"error: {issue}", file=sys.stderr)
        print(f"{len(result.errors)} validation error(s); nothing written",
              file=sys.stderr)
        return 1
    if args.check:
        print(f"{args.project.name}: valid "
              f"({len(result.warnings)} warning(s))")
        return 0

    try:
        written = export_v6.export_level(
            project, args.dest, level_name=args.level_name,
            carry_enemies_from=args.dest)
    except export_v6.ExportRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for name in sorted(written):
        try:
            shown = written[name].relative_to(REPO)
        except ValueError:
            shown = written[name]
        print(f"  {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
