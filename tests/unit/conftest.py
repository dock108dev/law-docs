import hashlib
import json
from pathlib import Path
import pytest
import pymupdf


@pytest.fixture
def raw(tmp_path):
    source = tmp_path / "source.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((40, 40), "SYNTHETIC REPORT — EXAMPLE DATA")
    doc.save(source)
    doc.close()
    values = {
        "case": "TEST-001",
        "department": "Example police",
        "municipality_code": "1821",
        "date": "08 18 26",
        "vehicle1": "1",
        "vehicle2": "2",
        "118a": "25",
        "118b": "--",
        "119a": "02",
        "119b": "--",
        "v1_given": "Alex Q",
        "v1_last": "Example",
        "v1_street": "10 Sample St Apt 1",
        "v1_cityzip": "Watchung, NJ 07069",
        "v2_given": "Blair",
        "v2_last": "Demo",
        "v2_street": "20 Sample St",
        "v2_cityzip": "Watchung, NJ 07069",
        "A_83": "1",
        "A_84": "01",
        "A_86": "03",
        "A_95": "Example, Alex-10 Sample St Apt 1, Watchung, NJ 07069",
        "B_83": "2",
        "B_84": "03",
        "B_86": "03",
        "B_95": "Sample, Casey-20 Sample St, Watchung, NJ 07069",
    }
    fields = {
        k: {"normalized": v, "rect": [20, 60, 100, 75], "raw": v, "alternatives": []}
        for k, v in values.items()
    }
    return {
        "source_pdf": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "pages": [
            {
                "source_page": 1,
                "render_sha256": "synthetic-1",
                "fields": fields,
                "issues": [],
                "page_size": [612, 792],
            }
        ],
    }


@pytest.fixture
def row():
    return {
        "id": "p01-r01",
        "name": "EXAMPLE, ALEX",
        "case_number": "TEST 0001",
        "offenses": ["39:4-98"],
        "source_page": 1,
        "source_row": 1,
        "reviewed": True,
        "excluded": False,
        "exclusion_reason": "",
        "issues": [],
    }


@pytest.fixture
def plea_job(tmp_path, monkeypatch, row):
    from app import server

    monkeypatch.setattr(server, "DATA", tmp_path)
    p = tmp_path / ("a" * 32)
    p.mkdir()
    result = {
        "id": p.name,
        "filename": "synthetic.pdf",
        "status": "ready",
        "rows": [row],
        "pages": [{"number": 1, "reconciled": True}],
        "revision": 0,
    }
    server.write_job(p, result)
    d = pymupdf.open()
    d.new_page()
    d.save(p / "source.pdf")
    d.close()
    return server, p, result
