#!/usr/bin/env python3
"""Deprecated shim. The acceptance level is now Level 1 of the two-level package
set; use tools/level_editor/build_levels.py, which rebuilds both level packages
and their generated engine includes deterministically.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_levels  # noqa: E402

if __name__ == "__main__":
    build_levels.main()
