#!/usr/bin/env python3
"""Audited PDF-only entry point; refuses reference/correction reads and networking."""

import json, runpy, sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
reads = set()


def audit(event, args):
    if event == "socket.connect":
        raise RuntimeError("Extraction is local only")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(args[0]).resolve()
        if (
            path.suffix.lower() == ".xlsx"
            or root / "review" in path.parents
            or path.name == "pdf-reviewed.json"
        ):
            raise RuntimeError(
                "Reference workbooks and visual corrections are forbidden extraction inputs"
            )
        mode = args[1]
        if mode is None or isinstance(mode, str) and "r" in mode:
            reads.add(str(path))


if __name__ == "__main__":
    sys.addaudithook(audit)
    runpy.run_path(str(root / "scripts/extract.py"), run_name="__main__")
    output = Path(sys.argv[sys.argv.index("--output") + 1])
    (output / "input-audit.json").write_text(
        json.dumps(
            {
                "reference_and_corrections_blocked": True,
                "python_network_connections_blocked": True,
                "python_read_paths": sorted(reads),
                "note": "Apple Vision and Tesseract run locally; OS-native reads are not captured by Python audit hooks.",
            },
            indent=2,
        )
    )
