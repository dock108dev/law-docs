from unittest.mock import Mock
from types import SimpleNamespace as NS
import pytest
from PIL import Image, ImageDraw
import anchored as a


def obs(text, rect=None):
    return {"text": text, "confidence": 0.99, "rect": rect or [0.1, 0.1, 0.2, 0.12]}


def test_layout():
    im = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(im).line((0, 50, 99, 50), fill="black")
    layout = a.Layout(
        im, [obs("B", [0.3, 0.1, 0.4, 0.12]), obs("A"), obs("C", [0.1, 0.4, 0.2, 0.42])]
    )
    assert [x["text"] for x in layout.select([0, 0, 1, 1])] == ["A", "B", "C"]
    assert layout.anchor("C", near=0.4)[1] == 0.4
    with pytest.raises(ValueError):
        layout.anchor("missing")
    assert layout.horizontal(0, 1, 0, 1) == [0.5]
    assert a.grouped([1, 2, 8], 2) == [1.5, 8]


@pytest.mark.parametrize(
    "key,numeric,text,expected",
    [
        ("case", False, " TEST ", "TEST"),
        ("v1_street", False, "10MainApt 2", "10Main Apt 2"),
        ("v1_cityzip", False, "Watchung, NJ 07069", "Watchung, NJ 07069"),
        ("v1_given", False, "Alex Q", "Alex Q"),
        ("vehicle1", True, "1", "1"),
        ("A_83", True, "2", "2"),
        ("A_84", True, "03", "03"),
        ("municipality_code", True, "1821", "1821"),
        ("118a", True, "25", "25"),
        ("date", False, "081826", "08 18 26"),
    ],
)
def test_field_read(tmp_path, monkeypatch, key, numeric, text, expected):
    im = Image.new("RGB", (300, 300), "white")
    record = {"fields": {}, "issues": []}
    monkeypatch.setattr(a, "recognize", lambda im: [obs(text)])
    monkeypatch.setattr(a.subprocess, "run", Mock(return_value=NS(stdout=text)))
    monkeypatch.setattr(a, "BACKEND", "vision")
    value = a.read_field(
        key,
        [0.1, 0.1, 0.9, 0.9],
        numeric=numeric,
        l=a.Layout(im, []),
        anchors=[],
        im=im,
        folder=tmp_path,
        out=tmp_path,
        record=record,
        page=NS(rect=NS(width=100, height=100)),
    )
    assert value == expected
    assert record["fields"][key]["crop"] == key + ".png"


@pytest.mark.parametrize("key", ["date", "118a", "vehicle1", "A_83", "municipality_code", "A_84"])
def test_unreadable_field_stays_unreadable(tmp_path, monkeypatch, key):
    im = Image.new("RGB", (300, 300), "white")
    record = {"fields": {}, "issues": []}
    monkeypatch.setattr(a, "recognize", lambda im: [obs("noise")])
    monkeypatch.setattr(a.subprocess, "run", Mock(return_value=NS(stdout="noise")))
    monkeypatch.setattr(a, "BACKEND", "rapidocr")
    monkeypatch.setattr(a, "focused_code", lambda crop: (None, []))
    value = a.read_field(
        key,
        [0.1, 0.1, 0.9, 0.9],
        numeric=key != "date",
        l=a.Layout(im, []),
        anchors=[],
        im=im,
        folder=tmp_path,
        out=tmp_path,
        record=record,
        page=NS(rect=NS(width=100, height=100)),
    )
    assert value == "noise"


def test_focused_contradiction_and_native_selection(tmp_path, monkeypatch):
    im = Image.new("RGB", (300, 300), "white")
    record = {"fields": {}, "issues": []}
    native = obs("25")
    native["native"] = True
    monkeypatch.setattr(a, "recognize", lambda im: [obs("25")])
    monkeypatch.setattr(a, "BACKEND", "rapidocr")
    monkeypatch.setattr(a, "focused_code", lambda crop: (None, []))
    args = dict(
        l=a.Layout(im, [obs("25")]),
        anchors=[native],
        im=im,
        folder=tmp_path,
        out=tmp_path,
        record=record,
        page=NS(rect=NS(width=100, height=100)),
    )
    assert a.read_field("118a", [0, 0, 1, 1], numeric=True, **args) == ""
    assert record["issues"]
    monkeypatch.setattr(a, "focused_code", lambda crop: ("25", []))
    assert a.read_field("118a", [0, 0, 1, 1], numeric=True, **args) == "25"
