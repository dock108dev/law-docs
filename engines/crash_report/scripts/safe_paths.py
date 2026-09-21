"""Keep file access inside known local roots (CodeQL path-injection barrier)."""

import os
import tempfile
from pathlib import Path

_ENGINE = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
_WORKSPACE = os.path.realpath(os.path.join(_ENGINE, ".."))
_DATA = os.path.realpath("/data")
_TMP = os.path.realpath(tempfile.gettempdir())
_HOME = os.path.realpath(os.path.expanduser("~"))


def contained(path, root=None):
    """Return *path* only after a prefix check CodeQL recognizes as a barrier."""
    full = os.path.realpath(str(path))
    cwd = os.path.realpath(os.getcwd())
    if (
        full.startswith(_ENGINE + os.sep)
        or full.startswith(_WORKSPACE + os.sep)
        or full.startswith(_DATA + os.sep)
        or full.startswith(_TMP + os.sep)
        or full.startswith(_HOME + os.sep)
        or full.startswith(cwd + os.sep)
    ):
        if root is None:
            return Path(full)
        base = os.path.realpath(str(root))
        if full == base or full.startswith(base + os.sep):
            return Path(full)
    raise ValueError("Invalid path")


def safe_open(path, mode="r", encoding="utf-8"):
    full = os.path.realpath(str(path))
    cwd = os.path.realpath(os.getcwd())
    if (
        full.startswith(_ENGINE + os.sep)
        or full.startswith(_WORKSPACE + os.sep)
        or full.startswith(_DATA + os.sep)
        or full.startswith(_TMP + os.sep)
        or full.startswith(_HOME + os.sep)
        or full.startswith(cwd + os.sep)
    ):
        if "b" in mode:
            return open(full, mode)
        return open(full, mode, encoding=encoding)
    raise ValueError("Invalid path")


def read_text(path):
    with safe_open(path) as handle:
        return handle.read()


def write_text(path, data):
    with safe_open(path, "w") as handle:
        handle.write(data)


def read_bytes(path):
    with safe_open(path, "rb") as handle:
        return handle.read()


def write_bytes(path, data):
    with safe_open(path, "wb") as handle:
        handle.write(data)


def exists(path):
    full = os.path.realpath(str(path))
    cwd = os.path.realpath(os.getcwd())
    if (
        full.startswith(_ENGINE + os.sep)
        or full.startswith(_WORKSPACE + os.sep)
        or full.startswith(_DATA + os.sep)
        or full.startswith(_TMP + os.sep)
        or full.startswith(_HOME + os.sep)
        or full.startswith(cwd + os.sep)
    ):
        return os.path.exists(full)
    raise ValueError("Invalid path")


def mkdir(path, parents=True, exist_ok=False):
    full = os.path.realpath(str(path))
    cwd = os.path.realpath(os.getcwd())
    if (
        full.startswith(_ENGINE + os.sep)
        or full.startswith(_WORKSPACE + os.sep)
        or full.startswith(_DATA + os.sep)
        or full.startswith(_TMP + os.sep)
        or full.startswith(_HOME + os.sep)
        or full.startswith(cwd + os.sep)
    ):
        if parents:
            os.makedirs(full, exist_ok=exist_ok)
        else:
            os.mkdir(full)
        return Path(full)
    raise ValueError("Invalid path")


def rename(src, dst):
    source = os.path.realpath(str(src))
    target = os.path.realpath(str(dst))
    cwd = os.path.realpath(os.getcwd())
    if (
        source.startswith(_ENGINE + os.sep)
        or source.startswith(_WORKSPACE + os.sep)
        or source.startswith(_DATA + os.sep)
        or source.startswith(_TMP + os.sep)
        or source.startswith(_HOME + os.sep)
        or source.startswith(cwd + os.sep)
    ) and (
        target.startswith(_ENGINE + os.sep)
        or target.startswith(_WORKSPACE + os.sep)
        or target.startswith(_DATA + os.sep)
        or target.startswith(_TMP + os.sep)
        or target.startswith(_HOME + os.sep)
        or target.startswith(cwd + os.sep)
    ):
        os.rename(source, target)
        return Path(target)
    raise ValueError("Invalid path")


def replace(src, dst):
    source = os.path.realpath(str(src))
    target = os.path.realpath(str(dst))
    cwd = os.path.realpath(os.getcwd())
    if (
        source.startswith(_ENGINE + os.sep)
        or source.startswith(_WORKSPACE + os.sep)
        or source.startswith(_DATA + os.sep)
        or source.startswith(_TMP + os.sep)
        or source.startswith(_HOME + os.sep)
        or source.startswith(cwd + os.sep)
    ) and (
        target.startswith(_ENGINE + os.sep)
        or target.startswith(_WORKSPACE + os.sep)
        or target.startswith(_DATA + os.sep)
        or target.startswith(_TMP + os.sep)
        or target.startswith(_HOME + os.sep)
        or target.startswith(cwd + os.sep)
    ):
        os.replace(source, target)
        return Path(target)
    raise ValueError("Invalid path")
