"""Keep file access inside known local roots (CodeQL path-injection barrier)."""

import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SAFE = re.compile(r"^[\w\s.\-/]+$")


def realpath(path):
    return os.path.realpath(str(path))


def allowed_roots():
    return [
        realpath(ROOT),
        realpath(ROOT.parents[1]),
        realpath("/data"),
        realpath(tempfile.gettempdir()),
        realpath(Path.home()),
        realpath(os.getcwd()),
    ]


def contained(path, root=None):
    """Resolve *path* and require it to stay under a trusted root."""
    full = realpath(path)
    if not _SAFE.fullmatch(full):
        raise ValueError("Invalid path")
    roots = [realpath(root)] if root is not None else allowed_roots()
    for base in roots:
        if full == base or full.startswith(base + os.sep):
            return Path(full)
    raise ValueError("Invalid path")
