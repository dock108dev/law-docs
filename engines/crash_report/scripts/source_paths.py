"""Resolve historical source references after consolidation without editing evidence."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = Path("/Users/michaelfuscoletti/Desktop/crash_report")


def source_path(value):
    path = Path(value)
    try:
        relative = path.relative_to(LEGACY_ROOT)
    except ValueError:
        prefix = "/Users/michaelfuscoletti/Desktop/report_workspace/engines/crash_report"
        try:
            return ROOT / path.relative_to(prefix)
        except ValueError:
            return path
    return ROOT / relative
