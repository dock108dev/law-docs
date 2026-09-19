from unittest.mock import Mock
import numpy as np
import cv2
import pytest
import pymupdf
from app import extract as e


def result(lines, confidence=99):
    return {"lines": lines, "confidence": confidence}


def test_parse_and_cells(monkeypatch):
    values, issues = e.parse_cells(
        [result(["DOE, JANE"]), result(["TEST 001"]), result(["39:4-98"])]
    )
    assert values["name"] == "DOE, JANE"
    assert not issues
    values, issues = e.parse_cells(
        [
            result(["handwriting", "DOE| JANE"], 20),
            result(["abc$"], 20),
            result(["bad"] + ["39:4-98"] * 5, 20),
        ]
    )
    assert len(issues) >= 6
    assert values["case_number"] == ""
    assert len(e.parse_cells([result([]), result([]), result([])])[1]) == 3
    monkeypatch.setattr(
        e.pytesseract,
        "image_to_data",
        Mock(
            return_value={
                "text": ["", " ABC ", "DEF"],
                "block_num": [1] * 3,
                "par_num": [1] * 3,
                "line_num": [1, 1, 2],
                "conf": [-1, 90, 80],
            }
        ),
    )
    assert e.cell_ocr(np.zeros((100, 100, 3), np.uint8)) == result(["ABC", "DEF"], 80)
    monkeypatch.setattr(e.pytesseract, "image_to_data", Mock(return_value={"text": []}))
    assert e.cell_ocr(None)["confidence"] == 0
    assert e.groups([1, 2, 20]) == [1, 20]


def test_geometry_and_orientation(monkeypatch):
    im = np.full((500, 600, 3), 255, np.uint8)
    with pytest.raises(ValueError):
        e.geometry(im)
    for x in [30, 160, 290, 420, 550]:
        cv2.line(im, (x, 20), (x, 470), (0, 0, 0), 2)
    with pytest.raises(ValueError):
        e.geometry(im)
    for y in [25, 160, 300, 465]:
        cv2.line(im, (30, y), (550, y), (0, 0, 0), 2)
    xs, ys = e.geometry(im)
    assert len(xs) == 5
    assert len(ys) == 4
    d = pymupdf.open()
    page = d.new_page(width=200, height=200)
    for rot in [0, 90]:
        monkeypatch.setattr(e.pytesseract, "image_to_osd", Mock(return_value={"rotate": rot}))
        assert e.upright(page)[1] == rot
    monkeypatch.setattr(
        e.pytesseract,
        "image_to_osd",
        Mock(side_effect=e.pytesseract.TesseractError(1, "synthetic")),
    )
    assert e.upright(page)[1] == 0
    d.close()


def test_scan_flow(tmp_path, monkeypatch):
    d = pymupdf.open()
    d.new_page(width=300, height=300)
    d.save(tmp_path / "source.pdf")
    d.close()
    monkeypatch.setattr(e, "upright", lambda p: (np.full((500, 600, 3), 255, np.uint8), 90, 0))
    monkeypatch.setattr(e, "geometry", lambda im: ([20, 140, 260, 380, 560], [20, 30, 100, 200]))

    def ocr(im):
        return result(["DOE, JANE"])

    monkeypatch.setattr(e, "cell_ocr", ocr)
    r = e.extract_calendar(tmp_path / "source.pdf", tmp_path / "out")
    assert len(r["rows"]) == 2
    assert r["pages"][0]["issues"]
    monkeypatch.setattr(e, "cell_ocr", lambda im: result(["Defendant Case Offense"]))
    assert not e.extract_calendar(tmp_path / "source.pdf", tmp_path / "header")["rows"]
    monkeypatch.setattr(e, "geometry", Mock(side_effect=ValueError("layout")))
    assert e.extract_calendar(tmp_path / "source.pdf", tmp_path / "bad")["pages"][0]["issues"] == [
        "layout"
    ]
