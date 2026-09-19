from unittest.mock import Mock
from PIL import Image
import pymupdf
import pytest
import anchored as a


@pytest.mark.parametrize(
    "scenario",
    [
        "normal",
        "native",
        "city-one",
        "city-both",
        "vehicle-one",
        "vehicle-both",
        "municipality-fallback",
        "pitch",
        "few-columns",
        "column-order",
        "name-column",
        "grid-four",
        "grid-short",
        "last-one",
        "last-both",
        "unsupported",
        "missing-name",
    ],
)
def test_inspection_paths(tmp_path, monkeypatch, scenario):
    d = pymupdf.open()
    page = d.new_page(width=300, height=400)
    if scenario == "native":
        page.insert_text((20, 30), "SYNTHETIC EXAMPLE " * 15, fontsize=5)
    observations = [
        {
            "text": "NJTR-1 P1" if scenario != "unsupported" else "Other",
            "confidence": 1,
            "rect": [0.1, 0.05, 0.2, 0.066],
        }
    ]
    if scenario != "last-both":
        observations.append(
            {"text": "Last Name", "confidence": 1, "rect": [0.27, 0.2, 0.35, 0.216]}
        )
    if scenario not in ("last-both", "last-one"):
        observations.append(
            {"text": "Last Name", "confidence": 1, "rect": [0.67, 0.2, 0.75, 0.216]}
        )
    calls = iter([observations, [], [], [], []])
    monkeypatch.setattr(a, "recognize", lambda im: next(calls))

    def anchor(self, pattern, near=None):
        if "26" in pattern and "Dr" in pattern:
            if scenario == "missing-name":
                raise ValueError("Missing driver")
            return [0.1, 0.2, 0.2, 0.216]
        if "56" in pattern:
            return [0.5, 0.2, 0.6, 0.216]
        if "27" in pattern:
            return [0.1, 0.28, 0.2, 0.296]
        if "57" in pattern:
            return [0.5, 0.28, 0.6, 0.296]
        if "28" in pattern:
            if scenario in ("city-one", "city-both"):
                raise ValueError("City missing")
            return [0.1, 0.35, 0.2, 0.366]
        if "58" in pattern:
            if scenario == "city-both":
                raise ValueError("City missing")
            return [0.5, 0.35, 0.6, 0.366]
        if "30" in pattern:
            return [0.1, 0.42, 0.2, 0.436]
        if "60" in pattern:
            return [0.5, 0.42, 0.6, 0.436]
        if "Last Name" in pattern:
            if scenario == "last-both":
                return [0.27, 0.2, 0.35, 0.216]
            return [0.27, 0.2, 0.35, 0.216]
        if "Case Number" in pattern:
            return [0.1, 0.01, 0.2, 0.026]
        if "Dept" in pattern:
            return [0.1, 0.04, 0.2, 0.056]
        if "Station" in pattern:
            return [0.1, 0.07, 0.2, 0.086]
        if "2[36]" in pattern:
            if scenario in ("vehicle-one", "vehicle-both"):
                raise ValueError("Vehicle missing")
            return [0.1, 0.16, 0.14, 0.176]
        if "53" in pattern:
            if scenario == "vehicle-both":
                raise ValueError("Vehicle missing")
            return [0.5, 0.16, 0.54, 0.176]
        if "Date" in pattern:
            return [0.3, 0.09, 0.4, 0.106]
        if "Day" in pattern:
            return [0.45, 0.09, 0.48, 0.106]
        if "Municip" in pattern:
            if scenario == "municipality-fallback":
                raise ValueError("Missing municipality label")
            return [0.55, 0.09, 0.6, 0.106]
        if "1?7" in pattern:
            return [0.55, 0.09, 0.6, 0.106]
        if "118b" in pattern:
            return [0.9, 0.45, 0.93, 0.466]
        for i, key in enumerate(["119a", "119b", "120a", "120b"], 1):
            if key in pattern:
                if scenario == "pitch":
                    raise ValueError("Missing pitch")
                return [0.9, 0.45 + i * 0.05, 0.93, 0.466 + i * 0.05]
        if "Names" in pattern:
            return [0.5, 0.74, 0.7, 0.756]
        for n in [83, 84, 85, 86, 87, 94, 95]:
            if str(n) in pattern:
                if (scenario == "few-columns" and n < 87) or (
                    scenario == "name-column" and n == 95
                ):
                    raise ValueError("Missing column")
                x = 0.12 + (n - 83) * (0.03 if scenario != "column-order" else -0.003)
                return [x, 0.74, x + 0.01, 0.756]
        raise ValueError(pattern)

    monkeypatch.setattr(a.Layout, "anchor", anchor)
    lines = [0.78, 0.82, 0.86, 0.9, 0.94]
    if scenario == "grid-four":
        lines = [0.78, 0.82, 0.9, 0.94]
    if scenario == "grid-short":
        lines = [0.78, 0.82, 0.86]
    monkeypatch.setattr(a.Layout, "horizontal", lambda *args: lines)

    def read(key, *args, record, **kwargs):
        record["fields"][key] = {"normalized": "synthetic"}
        return "synthetic"

    monkeypatch.setattr(a, "read_field", read)
    result = a.inspect_page(page, 1, tmp_path)
    if scenario in (
        "normal",
        "native",
        "city-one",
        "vehicle-one",
        "municipality-fallback",
        "grid-four",
        "last-one",
    ):
        assert "D_95" in result["fields"]
    else:
        assert result["issues"]
    assert (tmp_path / "evidence/page-01/source.png").exists()
    d.close()
