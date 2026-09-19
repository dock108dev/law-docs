"""Resolve migrated report sources into the current persistent job store."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = Path("/Users/michaelfuscoletti/Desktop/crash_report")


def source_path(value):
    path = Path(value)
    roots = [
        ROOT,
        LEGACY_ROOT,
        Path("/Users/michaelfuscoletti/Desktop/report_workspace/engines/crash_report"),
        Path("/opt/lawdocs/engines/crash_report"),
    ]
    for root in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if relative.parts[:2] == ("data", "batches") and os.environ.get("CRASH_BATCHES"):
            return Path(os.environ["CRASH_BATCHES"]).joinpath(*relative.parts[2:])
        return ROOT / relative
    return path
