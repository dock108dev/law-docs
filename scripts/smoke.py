"""Exercise only disposable synthetic jobs against a running workspace."""

import argparse, io, json, time, urllib.request, zipfile
import pymupdf


def run(base, expected=None):
    def request(path, data=None, headers=None):
        req = urllib.request.Request(
            base + path, data=data, headers={"User-Agent": "Lawdocs-CI/1", **(headers or {})}
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()

    health = json.loads(request("/api/health"))
    if expected:
        assert health["release"] == expected, health
    ids = []
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((30, 40), "SYNTHETIC CI CHECK - NO CLIENT DATA")
    pdf = doc.tobytes()
    doc.close()
    for kind in ("crash", "plea"):
        if kind == "crash":
            data = pdf
            headers = {"X-Review-App": "1", "X-Test-Batch": "1", "X-Filename": "synthetic-ci.pdf"}
        else:
            data = (
                b'--CI\r\nContent-Disposition: form-data; name="file"; filename="synthetic-ci.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
                + pdf
                + b"\r\n--CI--\r\n"
            )
            headers = {"Content-Type": "multipart/form-data; boundary=CI"}
        ident = json.loads(request(f"/{kind}/api/upload", data, headers))["id"]
        ids.append((kind, ident))
        route = "batches" if kind == "crash" else "jobs"
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            job = json.loads(request(f"/{kind}/api/{route}/{ident}"))
            if job["status"] != "extracting":
                break
            time.sleep(1)
        assert job["status"] == "ready", job
        with zipfile.ZipFile(io.BytesIO(request(f"/{kind}/api/package/{ident}"))) as z:
            assert z.testzip() is None and any(n.startswith("proof-sheet-") for n in z.namelist())
    print(json.dumps({"release": health["release"], "synthetic_jobs": ids, "result": "passed"}))
    return ids


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--release")
    a = parser.parse_args()
    run(a.url, a.release)
