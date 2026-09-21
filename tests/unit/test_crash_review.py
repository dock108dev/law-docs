import copy, io, json, shutil
from unittest.mock import Mock
from types import SimpleNamespace as NS
import pytest
import review_app as r
from extract import normalize


@pytest.fixture
def batch(raw, tmp_path, monkeypatch):
    p = tmp_path / ("b" * 32)
    p.mkdir()
    (p / "extraction").mkdir()
    shutil.copy(raw["source_pdf"], p / "source.pdf")
    for name, value in [
        ("batch.json", {"id": p.name, "status": "ready", "created": "2026-01-01", "test": True}),
        ("extraction/raw.json", raw),
        ("extraction/automatic.json", normalize(raw)),
    ]:
        r.save(p / name, value)
    r.initialize(p)
    monkeypatch.setattr(r, "STORE", tmp_path)
    monkeypatch.setenv("CRASH_WORKBOOK", "portable")
    return p


def handler(path, method="GET", body=b"", headers=None):
    h = object.__new__(r.Handler)
    h.path = path
    h.server = NS(server_port=9999)
    h.headers = {
        "Host": "127.0.0.1:9999",
        "X-Review-App": "1",
        "Content-Length": str(len(body)),
        **(headers or {}),
    }
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    h.send = Mock()
    h.send_response = Mock()
    h.send_header = Mock()
    h.end_headers = Mock()
    return h


def test_decisions(batch):
    p = batch
    d = r.read(p / "decisions.json")
    ident = d["order"][0]
    for change in [
        {"revision": 99},
        {"order": []},
        {"id": ident, "values": {}},
        {"id": ident, "status": "bad"},
        {"id": ident, "values": dict(d["people"][ident]["values"], first_name="Changed")},
    ]:
        with pytest.raises(ValueError):
            r.update(p, {"revision": 0, **change})
    d = r.update(p, {"revision": 0, "order": list(reversed(d["order"]))})
    assert d["revision"] == 1
    d = r.update(p, {"revision": 1, "id": ident, "status": "approved"})
    assert d["people"][ident]["status"] == "approved"
    assert r.paired_export(p, 2)["count"] == 1
    with pytest.raises(ValueError):
        r.paired_export(p, 1)
    d = r.update(
        p,
        {
            "revision": 2,
            "id": ident,
            "values": dict(d["people"][ident]["values"], first_name="Changed"),
            "reason": "Source correction",
            "status": "approved",
        },
    )
    assert d["people"][ident]["status"] == "unresolved"
    with pytest.raises(ValueError):
        r.paired_export(p, 3)
    manual = "p01-driver-2"
    with pytest.raises(ValueError):
        r.update(p, {"revision": 3, "id": manual, "status": "approved"})
    d = r.update(
        p,
        {
            "revision": 3,
            "id": manual,
            "status": "approved",
            "manual": True,
            "reason": "Synthetic exception",
        },
    )
    assert r.paired_export(p, 4)["count"] == 1
    for field, value in [("first_name", ""), ("zip_code", "bad"), ("crash_date", "bad")]:
        state = copy.deepcopy(d)
        state["people"][ident]["values"][field] = value
        r.save(p / "decisions.json", state)
        with pytest.raises(ValueError):
            r.update(p, {"revision": 4, "id": ident, "status": "approved"})
    with pytest.raises(ValueError):
        r.batch("../bad")
    from safe_paths import contained

    with pytest.raises(ValueError):
        contained("/etc/passwd")
    from safe_paths import exists, read_text

    with pytest.raises(ValueError):
        exists("/etc/passwd")
    with pytest.raises(ValueError):
        read_text("/etc/passwd")
    assert "\r" not in r.header_value("a\r\nb")
    assert r.header_value("plain") == "plain"


def test_handler_and_extraction(batch, monkeypatch):
    for path in [
        "/",
        "/api/batches",
        "/api/batches/" + batch.name,
        "/api/batches/" + batch.name + "/page/1",
        "/api/batches/" + batch.name + "/bad",
        "/api/batches/" + batch.name + "/download/nope",
    ]:
        h = handler(path)
        h.do_GET()
        assert h.send.called
    h = handler("/", headers={"Host": "other"})
    h.do_GET()
    assert h.send.call_args.kwargs["code"] == 400
    for headers, body in [
        ({"Host": "other"}, b"x"),
        ({"Origin": "https://bad"}, b"x"),
        ({"X-Review-App": "0"}, b"x"),
        ({}, b""),
        ({}, b"notpdf"),
    ]:
        h = handler("/api/upload", "POST", body, headers)
        h.do_POST()
        assert h.send.call_args.kwargs["code"] == 400
    monkeypatch.setattr(r.threading, "Thread", Mock())
    h = handler("/api/upload", "POST", (batch / "source.pdf").read_bytes())
    h.do_POST()
    assert "id" in h.send.call_args.args[0]
    for action, body in [
        ("decision", {"revision": 0, "order": r.read(batch / "decisions.json")["order"]}),
        ("export", {"revision": 1}),
        ("unknown", {}),
    ]:
        h = handler("/api/batches/" + batch.name + "/" + action, "POST", json.dumps(body).encode())
        h.do_POST()
        assert h.send.called
    monkeypatch.setattr(r.subprocess, "run", Mock(return_value=NS(returncode=0)))
    r.extract(batch)
    assert r.read(batch / "batch.json")["status"] == "ready"
    monkeypatch.setattr(r.subprocess, "run", Mock(return_value=NS(returncode=1)))
    r.extract(batch)
    assert r.read(batch / "batch.json")["status"] == "error"
    h = handler("/")
    del h.send
    r.Handler.send(h, {"ok": True})
    assert b'"ok": true' in h.wfile.getvalue()
    h.log_message("test")
