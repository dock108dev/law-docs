"""Real OCR regression tests are separate from the unit-coverage gate."""

import sys
from pathlib import Path
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.fixtures import calendar, crash
from app.extract import extract_calendar
from anchored import inspect_page
from extract import normalize, digest


def test_calendar_native_and_sideways_scan(tmp_path):
    for scanned in (False, True):
        source = tmp_path / f"{scanned}.pdf"
        calendar(source, scanned, scanned)
        result = extract_calendar(source, tmp_path / f"output-{scanned}")
        assert len(result["rows"]) == 2
        assert [r["name"] for r in result["rows"]] == ["EXAMPLE, ALEX", "SAMPLE, CASEY"]
        assert [r["case_number"] for r in result["rows"]] == ["S 2026 000001", "S 2026 000002"]


def test_crash_real_ocr(tmp_path):
    source = tmp_path / "crash.pdf"
    crash(source)
    with pymupdf.open(source) as d:
        r = inspect_page(d[0], 1, tmp_path / "out")
    model = normalize(
        {"source_pdf": str(source), "source_sha256": digest(source.read_bytes()), "pages": [r]}
    )
    assert {p["first_name"] for p in model["recipients"]} == {"Alex", "Casey"}, (
        r["issues"],
        model["review"],
    )
