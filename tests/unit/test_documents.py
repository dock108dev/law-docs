import copy, json, zipfile
from pathlib import Path
import pytest
import pymupdf
from pypdf import PdfReader
from app.pdf_export import row_errors, person_key, build_slips, make_pdf
from extract import normalize
from export import export_bundle
from verify_delivery import verify
from households import group_households, export_household_pages, verify_household_workbook
import delivery


def test_slips(row, tmp_path):
    assert row_errors({}) == ["Name is blank", "Case number is blank", "Offense is blank"]
    assert person_key({"name": "", "id": "one"}) == ("unresolved", "one")
    many = [dict(row, offenses=["39:4-98"] * 5), dict(row, id="excluded", excluded=True)]
    assert len(build_slips(many)) == 2
    for draft, automated in [(True, False), (False, False), (False, True)]:
        p = make_pdf(many, tmp_path / f"{draft}-{automated}.pdf", draft=draft, automated=automated)
        assert len(PdfReader(p).pages) == 2
    for rows in [[], [dict(row, reviewed=False)], [dict(row, name="")]]:
        with pytest.raises(ValueError):
            make_pdf(rows, tmp_path / "bad.pdf", draft=False)
    with pytest.raises(ValueError):
        make_pdf([dict(row, name="X" * 1000)], tmp_path / "long.pdf")
    make_pdf([dict(row, name="", case_number="", offenses=[])], tmp_path / "draft.pdf")


def test_crash_outputs(raw, tmp_path, monkeypatch):
    monkeypatch.setenv("CRASH_WORKBOOK", "portable")
    model = normalize(raw)
    model["households"] = group_households(model["recipients"])
    out = tmp_path / "output"
    export_bundle(model, raw, out)
    assert verify(out, raw)["excel_rows"] == 2
    mapping = export_household_pages(model, out)
    assert verify_household_workbook(model, out, mapping)["households"] == 2
    with pytest.raises(FileExistsError):
        export_bundle(model, raw, out)
    with pytest.raises(ValueError):
        export_bundle(dict(model, recipients=[]), raw, tmp_path / "empty")
    with pytest.raises(AssertionError):
        export_bundle(dict(model, source_sha256="bad"), raw, tmp_path / "changed")


def test_plea_package(plea_job, tmp_path, monkeypatch):
    s, p, result = plea_job
    monkeypatch.setenv("PLEA_DATA", str(p.parent))
    out = tmp_path / "package"
    delivery.generate("plea", p.name, out)
    with zipfile.ZipFile(out / "results.zip") as z:
        assert z.testzip() is None
        assert any(n.startswith("plea-slips-") for n in z.namelist())
    assert s.read_job(p.name) == result
    result["rows"][0]["excluded"] = True
    s.write_job(p, result)
    delivery.generate("plea", p.name, tmp_path / "excluded")
    with pytest.raises(ValueError):
        delivery.generate("plea", "../escape", tmp_path / "bad")
    result["status"] = "extracting"
    s.write_job(p, result)
    with pytest.raises(ValueError):
        delivery.generate("plea", p.name, tmp_path / "wait")


def test_crash_package(raw, tmp_path, monkeypatch):
    import review_app

    p = tmp_path / ("b" * 32)
    p.mkdir()
    (p / "extraction").mkdir()
    import shutil

    shutil.copy(raw["source_pdf"], p / "source.pdf")
    raw["source_pdf"] = str(p / "source.pdf")
    model = normalize(raw)
    for name, value in [
        ("batch.json", {"status": "ready", "id": p.name}),
        ("extraction/raw.json", raw),
        ("extraction/automatic.json", model),
    ]:
        (p / name).write_text(json.dumps(value))
    review_app.initialize(p)
    monkeypatch.setenv("CRASH_BATCHES", str(tmp_path))
    monkeypatch.setenv("CRASH_WORKBOOK", "portable")
    delivery.generate("crash", p.name, tmp_path / "crash-package")
    decisions = json.loads((p / "decisions.json").read_text())
    for value in decisions["people"].values():
        value["status"] = "excluded"
    (p / "decisions.json").write_text(json.dumps(decisions))
    delivery.generate("crash", p.name, tmp_path / "empty-package")
    (p / "batch.json").write_text('{"status":"extracting"}')
    with pytest.raises(ValueError):
        delivery.generate("crash", p.name, tmp_path / "not-ready")
