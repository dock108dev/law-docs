import io, json
from unittest.mock import Mock
import pytest
from PIL import Image


def test_routes(plea_job, monkeypatch):
    s, p, result = plea_job
    c = s.app.test_client()
    base = "/api/jobs/" + p.name
    assert c.get("/").status_code == 200
    assert c.get("/api/jobs").json[0]["id"] == p.name
    assert c.get("/api/jobs/invalid").status_code == 404
    assert c.get(base).json["revision"] == 0
    assert c.get(base + "/source").data.startswith(b"%PDF")
    assert c.get(base + "/review-record").status_code == 200
    Image.new("RGB", (10, 10), "white").save(p / "test.png")
    assert c.get(base + "/images/test.png").status_code == 200
    for name in ["no.png", "bad.txt"]:
        assert c.get(base + "/images/" + name).status_code == 404
    assert c.get(base + "/preview/missing").status_code == 404
    for suffix in ["", "?format=png", "?format=png&page=99", "?format=png&page=-1"]:
        assert c.get(base + "/preview/p01-r01" + suffix).status_code == (
            400 if "page=" in suffix else 200
        )
    assert c.get(base + "/export?draft=0").status_code == 200
    result["rows"][0]["excluded"] = True
    s.write_job(p, result)
    assert c.get(base + "/preview/p01-r01").status_code == 200
    assert (
        c.patch(
            base + "/rows/p01-r01", json={}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert c.patch(base + "/rows/missing", json={}).status_code == 404
    for body in [{"offenses": "x"}, {"excluded": True}, {"name": "", "reviewed": True}]:
        result["rows"][0]["excluded"] = False
        s.write_job(p, result)
        assert c.patch(base + "/rows/p01-r01", json=body).status_code == 400
    assert (
        c.patch(
            base + "/rows/p01-r01",
            json={
                "offenses": ["39:4-98", " "],
                "name": "EXAMPLE, BLAIR",
                "review_note": "checked",
                "reviewed": True,
            },
        ).status_code
        == 200
    )
    assert c.get(base + "/export?draft=0").status_code == 400
    for body in [
        {"source_page": 99, "source_row": 2},
        {"source_page": 1, "source_row": "bad"},
        {"source_page": 1, "source_row": 1},
        {"source_page": 1, "source_row": 0},
    ]:
        assert c.post(base + "/rows", json=body).status_code == 400
    assert c.post(base + "/rows", json={"source_page": 1, "source_row": 1.5}).status_code == 200
    assert c.patch(base + "/pages/99", json={"count": 1}).status_code == 404
    assert c.patch(base + "/pages/1", json={"count": 99}).status_code == 400
    assert c.patch(base + "/pages/1", json={"count": 2}).status_code == 200
    result["status"] = "extracting"
    s.write_job(p, result)
    assert c.get(base + "/export").status_code == 400
    assert c.patch(base + "/rows/p01-r01", json={}).status_code == 400
    assert c.post(base + "/rows", json={}).status_code == 400


def test_upload_and_extract(plea_job, monkeypatch):
    s, p, result = plea_job
    c = s.app.test_client()
    assert c.post("/api/upload").status_code == 400
    for filename, content in [("bad.txt", b"x"), ("bad.pdf", b"x")]:
        assert (
            c.post("/api/upload", data={"file": (io.BytesIO(content), filename)}).status_code == 400
        )
    thread = Mock()
    monkeypatch.setattr(s.threading, "Thread", thread)
    r = c.post(
        "/api/upload", data={"file": (io.BytesIO((p / "source.pdf").read_bytes()), "input.pdf")}
    )
    assert r.status_code == 202
    thread.return_value.start.assert_called_once()
    ident = r.json["id"]

    def extract(source, directory, progress):
        progress("working")
        return result.copy()

    monkeypatch.setattr(s, "extract_calendar", extract)
    s.run_extract(ident)
    assert s.read_job(ident)["status"] == "ready"
    monkeypatch.setattr(s, "extract_calendar", Mock(side_effect=ValueError("bad layout")))
    s.run_extract(ident)
    assert s.read_job(ident)["status"] == "error"
    with s.app.app_context():
        assert s.too_large(None)[1] == 413
    (p.parent / "invalid").mkdir()
    (p.parent / "invalid/result.json").write_text("{bad")
    assert c.get("/api/jobs").status_code == 200
