"""Single loopback entry point for crash and plea report workflows."""

import http.client
from datetime import datetime
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import re
import retention

ROOT = Path(__file__).resolve().parent
WORKERS = {}
ACTIVE_REQUESTS = 0
REQUEST_LOCK = threading.Lock()
NAV = """<div id="workspace-nav"><a href="/">Report workspace</a><a href="/crash/">Crash reports</a><a href="/plea/">Plea calendars</a><span>Saved on this Mac</span></div><style>#workspace-nav{display:flex;align-items:center;gap:24px;padding:13px 28px;background:#102e35;color:#dceae6;font:14px -apple-system,BlinkMacSystemFont,sans-serif}#workspace-nav a{color:inherit;text-decoration:none}#workspace-nav a:first-child{font-weight:700;color:white}#workspace-nav span{margin-left:auto;font-size:12px}.layout{height:calc(100vh - 202px)!important}@media(max-width:650px){#workspace-nav{gap:14px;padding:12px;flex-wrap:wrap}#workspace-nav span{display:none}}</style>"""


def header_value(value):
    return str(value).replace("\r", "").replace("\n", "")


def adapt(data, content_type, kind):
    if not any(t in content_type for t in ("text/html", "javascript", "text/css")):
        return data
    text = data.decode("utf-8")
    # Only rewrite application assets; never modify OCR, source PDFs, or exports.
    for prefix in ("/api/", "/static/"):
        text = text.replace(prefix, "/" + kind + prefix)
    if "text/html" in content_type:
        text = text.replace("<header>", NAV + "<header>", 1)
        if kind == "crash":
            text = text.replace(
                "home().catch(e=>message(e.message));",
                "(location.hash.length>1?open(location.hash.slice(1)):home()).catch(e=>message(e.message));",
            )
    return text.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, status=200, content_type="application/json", headers=()):
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", header_value(content_type))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in headers:
            self.send_header(header_value(key), header_value(value))
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self):
        global ACTIVE_REQUESTS
        counted = urlsplit(self.path).path != "/api/health"
        if counted:
            with REQUEST_LOCK:
                ACTIVE_REQUESTS += 1
        try:
            return self.dispatch_request()
        finally:
            if counted:
                with REQUEST_LOCK:
                    ACTIVE_REQUESTS -= 1

    def dispatch_request(self):
        host = self.headers.get("Host")
        public_origin = os.environ.get("PUBLIC_ORIGIN", "").rstrip("/")
        allowed_hosts = {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }
        if public_origin:
            allowed_hosts.add(urlsplit(public_origin).netloc)
        if host not in allowed_hosts:
            return self.send({"error": "Open the app using its local address."}, 403)
        if self.headers.get("Origin") not in (
            None,
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
            public_origin or f"http://{host}",
        ):
            return self.send({"error": "Use the local app to upload or edit files."}, 403)
        path = urlsplit(self.path).path
        job = re.match(
            r"^/(crash|plea)/api/(?:package|batches|jobs)/([a-f0-9]{32}|sample)(?:/|$)", path
        )
        is_expired = job and retention.expired(job[1], job[2])
        retention.sweep()
        if is_expired:
            return self.send(
                {"error": "This file expired after 48 hours. Upload it again to start a new job."},
                410,
            )
        if self.command == "GET" and path in (
            "/assets/app.js",
            "/assets/main.js",
            "/assets/style.css",
        ):
            asset = ROOT / "web" / Path(path).name
            return self.send(
                asset.read_bytes(),
                content_type="text/css" if asset.suffix == ".css" else "text/javascript",
            )
        if self.command == "GET" and path == "/":
            return self.send(
                (ROOT / "web/index.html").read_bytes(), content_type="text/html; charset=utf-8"
            )
        if self.command == "GET" and path == "/api/health":
            return self.send(
                {
                    "status": "ready",
                    "workflows": list(WORKERS),
                    "retention_hours": retention.hours(),
                    "release": os.environ.get("LAW_DOCS_RELEASE", "local"),
                    "active_requests": ACTIVE_REQUESTS,
                }
            )
        if (
            self.command == "POST"
            and path.endswith("/api/upload")
            and Path(os.environ.get("DRAIN_FILE", "/nonexistent/lawdocs-draining")).exists()
        ):
            return self.send(
                {"error": "An update is being installed. Please try your upload again shortly."},
                503,
            )
        kind = path.strip("/").split("/")[0]
        if kind not in WORKERS:
            return self.send({"error": "Page not found."}, 404)
        if self.command == "GET" and path == "/" + kind + "/":
            return self.send(
                (ROOT / "web/index.html").read_bytes(), content_type="text/html; charset=utf-8"
            )
        match = re.fullmatch(r"/(crash|plea)/api/package/([a-f0-9]{32}|sample)", path)
        if self.command == "GET" and match:
            folder = "crash_report" if kind == "crash" else "plea_reports"
            with tempfile.TemporaryDirectory(prefix="report-download-") as output:
                run = subprocess.run(
                    [
                        str(ROOT / "engines" / folder / ".venv/bin/python"),
                        str(ROOT / "delivery.py"),
                        kind,
                        match[2],
                        output,
                    ],
                    capture_output=True,
                    text=True,
                )
                if run.returncode:
                    return self.send(
                        {"error": run.stderr.strip()[-1000:] or "Unable to create the download."},
                        400,
                    )
                return self.send(
                    (Path(output) / "results.zip").read_bytes(),
                    content_type="application/zip",
                    headers=[
                        (
                            "Content-Disposition",
                            f'attachment; filename="{kind}-results-and-proofs-{datetime.now().astimezone():%Y-%m-%d_%H-%M-%S}.zip"',
                        )
                    ],
                )
        if path == "/" + kind:
            return self.send(b"", 302, headers=[("Location", "/" + kind + "/")])
        try:
            length = int(self.headers.get("Content-Length", "0"))
            limit = (61 if kind == "crash" else 41) * 1024 * 1024
            if self.headers.get("Transfer-Encoding") or not 0 <= length <= limit:
                return self.send({"error": "Choose a PDF within the upload size limit."}, 413)
            body = self.rfile.read(length) if length else None
            port = WORKERS[kind]
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() in ("content-type", "x-review-app", "x-filename", "x-test-batch")
            }
            headers["Host"] = f"127.0.0.1:{port}"
            if self.headers.get("Origin"):
                headers["Origin"] = f"http://127.0.0.1:{port}"
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=600)
            try:
                conn.request(self.command, self.path[len(kind) + 1 :] or "/", body, headers)
                res = conn.getresponse()
                content_type = res.getheader("Content-Type", "application/octet-stream")
                data = adapt(res.read(), content_type, kind)
                extra = [
                    (k, v)
                    for k, v in res.getheaders()
                    if k.lower() in ("content-disposition", "x-preview-pages")
                ]
                return self.send(data, res.status, content_type, extra)
            finally:
                conn.close()
        except (OSError, http.client.HTTPException):
            return self.send(
                {
                    "error": "The local processor is unavailable. Restart Report Workspace and reopen your saved work."
                },
                502,
            )
        except ValueError:
            return self.send({"error": "Invalid request."}, 400)

    do_GET = handle_request
    do_POST = handle_request
    do_PATCH = handle_request
    do_DELETE = handle_request


def main():
    port = int(os.environ.get("REPORT_PORT", "8795"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    children = []
    retention.start()

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        with tempfile.TemporaryDirectory(prefix="report-workspace-") as temp:
            for kind, folder in [("crash", "crash_report"), ("plea", "plea_reports")]:
                ready = Path(temp) / kind
                python = ROOT / "engines" / folder / ".venv/bin/python"
                child = subprocess.Popen(
                    [str(python), str(ROOT / "worker.py"), kind, str(ready)],
                    cwd=ROOT / "engines" / folder,
                )
                children.append(child)
                deadline = time.monotonic() + 40
                while not ready.exists():
                    if child.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(
                            f"{kind} processor could not start. See the terminal details."
                        )
                    time.sleep(0.1)
                WORKERS[kind] = int(ready.read_text())
            print(f"Report Workspace ready: http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for child in children:
            child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
