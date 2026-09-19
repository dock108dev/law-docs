"""Bound the Linux OCR engine's memory lifetime to one page."""

import json, sys
from pathlib import Path
from pdf_only import audit, reads

sys.addaudithook(audit)
import pymupdf
from anchored import inspect_page

source, index, output = sys.argv[1:]
index = int(index)
out = Path(output)
with pymupdf.open(source) as document:
    result = inspect_page(document[index], index + 1, out)
(out / f"page-{index + 1:02}-result.json").write_text(json.dumps(result))
(out / f"page-{index + 1:02}-audit.json").write_text(
    json.dumps({"network_blocked": True, "reads": sorted(reads)})
)
