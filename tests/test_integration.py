import http.client, json, os, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.children = []
        env = dict(
            os.environ, CRASH_BATCHES=str(cls.root / "crash"), PLEA_DATA=str(cls.root / "plea")
        )
        cls.envpatch = patch.dict(
            os.environ, {"CRASH_BATCHES": env["CRASH_BATCHES"], "PLEA_DATA": env["PLEA_DATA"]}
        )
        cls.envpatch.start()
        for kind, folder in [("crash", "crash_report"), ("plea", "plea_reports")]:
            ready = cls.root / (kind + ".port")
            p = subprocess.Popen(
                [
                    str(server.ROOT / "engines" / folder / ".venv/bin/python"),
                    str(server.ROOT / "worker.py"),
                    kind,
                    str(ready),
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cls.children.append(p)
            for _ in range(400):
                if ready.exists():
                    break
                if p.poll() is not None:
                    raise RuntimeError("Worker failed")
                time.sleep(0.1)
            server.WORKERS[kind] = int(ready.read_text())
        cls.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.http.server_port
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        for p in cls.children:
            p.terminate()
            p.wait(timeout=10)
        cls.envpatch.stop()
        cls.temp.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        c.request(method, path, body, headers or {})
        r = c.getresponse()
        data = r.read()
        result = (r.status, data, dict(r.getheaders()))
        c.close()
        return result

    def test_routes_and_origin(self):
        backup = self.root / "plea" / "owner-review-baseline"
        backup.mkdir(exist_ok=True)
        (backup / "result.json").write_text(json.dumps({"status": "ready", "rows": []}))
        self.assertNotIn("owner-review-baseline", self.request("/plea/api/jobs")[1].decode())
        for kind in ("crash", "plea"):
            status, body, _ = self.request("/" + kind + "/")
            self.assertEqual(status, 200)
            self.assertIn(b"Your documents", body)
            self.assertNotIn(b"Review alongside", body)
            self.assertEqual(
                self.request(
                    "/" + kind + "/api/upload", "POST", b"bad", {"Origin": "https://other.example"}
                )[0],
                403,
            )
            self.assertEqual(
                self.request("/" + kind + "/api/upload", "POST", b"bad", {"X-Review-App": "1"})[0],
                400,
            )
        status, js, _ = self.request("/assets/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"/plea/api/jobs", js)

    def test_expired_job_is_removed_and_download_denied(self):
        from datetime import datetime, timezone, timedelta

        ident = "e" * 32
        directory = self.root / "plea" / ident
        directory.mkdir()
        (directory / "source.pdf").write_bytes(b"expired source")
        (directory / "result.json").write_text(
            json.dumps(
                {
                    "created": (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat(),
                    "status": "ready",
                    "rows": [],
                }
            )
        )
        with patch.dict(os.environ, {"JOB_RETENTION_HOURS": "48"}):
            status, body, _ = self.request("/plea/api/package/" + ident)
            self.assertEqual(status, 410, body)
            self.assertFalse(directory.exists())
            self.assertEqual(json.loads(self.request("/api/health")[1])["retention_hours"], 48)

    def test_public_origin_routes(self):
        with patch.dict(os.environ, {"PUBLIC_ORIGIN": "https://lawdocs.dock108.dev"}):
            headers = {"Host": "lawdocs.dock108.dev", "Origin": "https://lawdocs.dock108.dev"}
            self.assertEqual(self.request("/api/health", headers=headers)[0], 200)
            self.assertEqual(self.request("/plea/api/upload", "POST", b"bad", headers)[0], 400)
            headers["Origin"] = "https://untrusted.example"
            self.assertEqual(self.request("/plea/api/upload", "POST", b"bad", headers)[0], 403)
            self.assertEqual(
                self.request("/api/health", headers={"Host": "untrusted.example"})[0], 403
            )

    def test_uploads(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Synthetic integration test. No report rows.")
        pdf = doc.tobytes()
        doc.close()
        for kind in ("crash", "plea"):
            headers = {"Origin": f"http://127.0.0.1:{self.port}"}
            if kind == "crash":
                body = pdf
                headers.update(
                    {"X-Review-App": "1", "X-Test-Batch": "1", "X-Filename": "synthetic.pdf"}
                )
            else:
                body = (
                    b'--BOUNDARY\r\nContent-Disposition: form-data; name="file"; filename="synthetic.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
                    + pdf
                    + b"\r\n--BOUNDARY--\r\n"
                )
                headers["Content-Type"] = "multipart/form-data; boundary=BOUNDARY"
            status, raw, _ = self.request("/" + kind + "/api/upload", "POST", body, headers)
            self.assertIn(status, (200, 202), raw)
            ident = json.loads(raw)["id"]
            path = f"/{kind}/api/" + ("batches/" if kind == "crash" else "jobs/") + ident
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                status, raw, _ = self.request(path)
                result = json.loads(raw)
                if result["status"] != "extracting":
                    break
                time.sleep(0.3)
            self.assertEqual(result["status"], "ready", result)
            self.assertEqual((self.root / kind / ident / "source.pdf").read_bytes(), pdf)
            status, package, _ = self.request(f"/{kind}/api/package/{ident}")
            self.assertEqual(status, 200, package)
            self.assertTrue(package.startswith(b"PK"))
            if kind == "crash":
                self.assertEqual(result["people"], [])
                self.assertTrue(self.request(path + "/page/1")[1].startswith(b"\x89PNG"))
                self.assertEqual(
                    self.request(
                        path + "/export",
                        "POST",
                        b'{"revision":0}',
                        {"X-Review-App": "1", "Content-Type": "application/json"},
                    )[0],
                    400,
                )
            else:
                self.assertEqual(result["rows"], [])
                self.assertEqual(self.request(path + "/source")[1], pdf)

    def test_review_and_download(self):
        folder = self.root / "plea" / "sample"
        folder.mkdir(exist_ok=True)
        row = {
            "id": "p01-r01",
            "name": "EXAMPLE, ALEX",
            "case_number": "TEST 000001",
            "offenses": ["TEST"],
            "source_page": 1,
            "source_row": 1,
            "reviewed": False,
            "excluded": False,
            "exclusion_reason": "",
            "issues": [],
        }
        (folder / "result.json").write_text(
            json.dumps(
                {
                    "id": "sample",
                    "status": "ready",
                    "rows": [row],
                    "pages": [{"number": 1, "reconciled": False}],
                    "revision": 0,
                }
            )
        )
        base = "/plea/api/jobs/sample"
        before = (folder / "result.json").read_bytes()
        status, package, _ = self.request("/plea/api/package/sample")
        self.assertEqual(status, 200, package)
        import io, zipfile

        with zipfile.ZipFile(io.BytesIO(package)) as z:
            self.assertTrue(
                any(n.startswith("plea-slips-") and n.endswith(".pdf") for n in z.namelist())
            )
            self.assertTrue(
                any(n.startswith("proof-sheet-") and n.endswith(".pdf") for n in z.namelist())
            )
            mapping = json.loads(
                z.read(next(n for n in z.namelist() if n.startswith("source-map-")))
            )
            self.assertEqual(mapping[0]["case_number"], "TEST 000001")
        self.assertEqual(before, (folder / "result.json").read_bytes())
        status, pdf, h = self.request(base + "/export?draft=1")
        self.assertEqual(status, 200)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn("attachment", h["Content-Disposition"])
        self.assertEqual(self.request(base + "/export?draft=0")[0], 400)
        self.assertEqual(
            self.request(
                base + "/rows/p01-r01",
                "PATCH",
                b'{"reviewed":true}',
                {"Content-Type": "application/json"},
            )[0],
            200,
        )
        self.assertEqual(
            self.request(
                base + "/pages/1", "PATCH", b'{"count":1}', {"Content-Type": "application/json"}
            )[0],
            200,
        )
        self.assertTrue(json.loads((folder / "result.json").read_text())["rows"][0]["reviewed"])
        status, pdf, _ = self.request(base + "/export?draft=0")
        self.assertEqual(status, 200)
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
