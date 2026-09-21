import io, json, http.client
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
import server


def handler(path="/", method="GET", headers=None, body=b""):
    h = object.__new__(server.Handler)
    h.server = NS(server_port=9999)
    h.path = path
    h.command = method
    h.headers = {"Host": "127.0.0.1:9999", **(headers or {})}
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    h.send = Mock()
    return h


def test_routes(monkeypatch):
    monkeypatch.setattr(server, "WORKERS", {"crash": 1, "plea": 2})
    monkeypatch.setenv("JOB_RETENTION_HOURS", "0")
    for path, status in [
        ("/assets/app.js", 200),
        ("/assets/style.css", 200),
        ("/", 200),
        ("/api/health", 200),
        ("/crash/", 200),
        ("/plea/", 200),
        ("/crash", 302),
        ("/unknown", 404),
    ]:
        h = handler(path)
        h.handle_request()
        assert (
            h.send.call_args.kwargs.get(
                "status", h.send.call_args.args[1] if len(h.send.call_args.args) > 1 else 200
            )
            == status
        )
    for headers in [{"Host": "bad"}, {"Origin": "https://bad"}]:
        h = handler(headers=headers)
        h.handle_request()
        assert h.send.call_args.args[1] == 403
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://lawdocs.dock108.dev")
    h = handler(headers={"Host": "lawdocs.dock108.dev", "Origin": "https://lawdocs.dock108.dev"})
    h.handle_request()
    assert h.send.called
    monkeypatch.setattr(server.retention, "expired", lambda *args: True)
    h = handler("/plea/api/package/" + "a" * 32)
    h.handle_request()
    assert h.send.call_args.args[1] == 410


def test_proxy(monkeypatch):
    monkeypatch.setattr(server, "WORKERS", {"crash": 1})
    monkeypatch.setenv("JOB_RETENTION_HOURS", "0")
    conn = Mock()
    response = conn.getresponse.return_value
    response.status = 200
    response.getheader.return_value = "application/json"
    response.read.return_value = b"{}"
    response.getheaders.return_value = []
    monkeypatch.setattr(server.http.client, "HTTPConnection", Mock(return_value=conn))
    h = handler("/crash/api/batches", headers={"Origin": "http://127.0.0.1:9999"})
    h.handle_request()
    assert h.send.call_args.args[1] == 200
    conn.close.assert_called_once()
    for headers in [
        {"Content-Length": "bad"},
        {"Content-Length": "999999999"},
        {"Transfer-Encoding": "chunked"},
    ]:
        h = handler("/crash/api/upload", headers=headers)
        h.handle_request()
        assert h.send.call_args.args[1] in (400, 413)
    conn.request.side_effect = OSError("unavailable")
    h = handler("/crash/api/batches")
    h.handle_request()
    assert h.send.call_args.args[1] == 502
    assert server.adapt(b"<header>/api/test /static/x</header>", "text/html", "crash").startswith(
        b"<div"
    )
    assert server.adapt(b"abc", "application/pdf", "crash") == b"abc"


def test_package(monkeypatch):
    monkeypatch.setattr(server, "WORKERS", {"plea": 1})
    monkeypatch.setenv("JOB_RETENTION_HOURS", "0")

    def run(args, **kwargs):
        from pathlib import Path

        (Path(args[-1]) / "results.zip").write_bytes(b"PKtest")
        return NS(returncode=0, stderr="")

    monkeypatch.setattr(server.subprocess, "run", run)
    h = handler("/plea/api/package/sample")
    h.handle_request()
    assert h.send.call_args.args[0] == b"PKtest"
    monkeypatch.setattr(
        server.subprocess, "run", lambda *args, **kw: NS(returncode=1, stderr="failed")
    )
    h = handler("/plea/api/package/sample")
    h.handle_request()
    assert h.send.call_args.args[1] == 400


def test_send():
    h = handler()
    del h.send
    h.send_response = Mock()
    h.send_header = Mock()
    h.end_headers = Mock()
    h.send({"ok": True}, headers=[("X-Test", "yes")])
    assert json.loads(h.wfile.getvalue()) == {"ok": True}
    h.send_header.reset_mock()
    h.send(b"x", headers=[("X-Inject", "a\r\nSet-Cookie: x")])
    assert all(
        "\n" not in call.args[1] and "\r" not in call.args[1]
        for call in h.send_header.call_args_list
    )
    h.log_message("ignored")
