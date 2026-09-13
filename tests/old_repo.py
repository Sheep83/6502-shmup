#!/usr/bin/env python3
"""The authoritative old shooter, read straight out of its archive.

The migration reference is `~/Desktop/c64Shooter-main.zip` on this machine.
Earlier suites pointed at a *checkout* of the same repository, at a path that
no longer exists here -- so the provenance checks that were meant to prove "the
level package is the authored original" quietly turned into one failing
"the reference checkout is present" and stopped proving anything at all.

Reading from the zip removes the whole class of problem: there is nothing to
extract, nothing to leave behind under /tmp and nothing to clean up, and the
bytes compared are the archive's own.
"""
import zipfile
from pathlib import Path

ARCHIVE = Path.home() / "Desktop" / "c64Shooter-main.zip"
PREFIX = "c64Shooter-main/"


def present():
    return ARCHIVE.is_file()


def old_bytes(relpath):
    """A file from the old repo, by its path inside the repo root."""
    with zipfile.ZipFile(ARCHIVE) as z:
        return z.read(PREFIX + relpath)


def old_text(relpath):
    return old_bytes(relpath).decode("utf-8", "replace")
