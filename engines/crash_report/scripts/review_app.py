#!/usr/bin/env python3
"""Loopback-only, disk-backed PDF review. Extraction is immutable; decisions are separate."""

import copy, datetime, hashlib, io, json, os, re, subprocess, sys, threading, uuid, zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
import pymupdf as fitz
from export import export_bundle
from verify_delivery import verify
from safe_paths import contained

ROOT = Path(__file__).resolve().parents[1]
STORE = contained(os.environ.get("CRASH_BATCHES", ROOT / "data/batches"))
KEYS = [
    "first_name",
    "last_name",
    "street_address",
    "mailing_city",
    "state",
    "zip_code",
    "crash_date",
    "crash_municipality",
]
LOCK = threading.RLock()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def header_value(value):
    return str(value).replace("\r", "").replace("\n", "")


def read(p):
    return json.loads(contained(p).read_text())


def save(p, d):
    p = contained(p)
    t = contained(p.with_suffix(".tmp"))
    t.write_text(json.dumps(d, indent=2))
    t.replace(p)


def batch(b):
    if not re.fullmatch("[a-f0-9]{32}", b):
        raise ValueError("Invalid batch")
    return contained(STORE / b, STORE)


def candidates(m):
    selected = {r["id"]: r for r in m["recipients"]}
    result = []
    for original in m["drivers"] + m["occupants"]:
        r = copy.deepcopy(original)
        report = next(x for x in m["reports"] if x["id"] == r["report"])
        if not report["first_page"]:
            continue
        rv = next(
            (
                x
                for x in m["review"]
                if x.get("report") == r["report"]
                and x.get("occupant_row") == r.get("occupant_row")
                and r.get("occupant_row")
            ),
            {},
        )
        if rv.get("reason") == "driver already handled":
            continue
        r.update(
            first_page=report["first_page"],
            support_pages=[r["source_page"]],
            crash_date=report["crash_date"],
            crash_municipality=report["municipality"],
        )
        if "occupant_row" in r:
            r.update(
                role=rv.get("role", "unknown"),
                evidence_fields=rv.get("evidence_fields", []),
                selection=rv.get("reason", "Unresolved occupant"),
            )
        else:
            v = r["id"].rsplit("-", 1)[1]
            box = "118" if v == "1" else "119"
            r["evidence_fields"] += [box + "a", box + "b", "vehicle" + v]
            r["selection"] = r["disposition"] + "; " + box + " A/B = " + "/".join(r["codes"])
        if r["id"] in selected:
            r.update(selected[r["id"]])
        r["eligible"] = r["id"] in selected
        context = ROOT / "data/review-context.json"
        if context.exists():
            notes = read(context)
            if notes["source_sha256"] == m["source_sha256"]:
                r["prior_review_note"] = notes["notes"].get(r["id"], "")
        r["evidence_fields"] = list(
            dict.fromkeys(r["evidence_fields"] + ["department", "date", "municipality_code"])
        )
        result.append(r)
    return result


def initialize(p):
    m = read(p / "extraction/automatic.json")
    people = candidates(m)
    save(
        p / "decisions.json",
        {
            "revision": 0,
            "order": [r["id"] for r in people],
            "people": {
                r["id"]: {
                    "values": {k: r.get(k, "") for k in KEYS},
                    "status": "unresolved",
                    "manual": False,
                    "reason": "",
                    "history": [],
                }
                for r in people
            },
            "exports": [],
        },
    )


def update(p, body):
    d = read(p / "decisions.json")
    if body["revision"] != d["revision"]:
        raise ValueError("This batch changed. Reopen it before saving.")
    if "order" in body:
        if sorted(body["order"]) != sorted(d["order"]):
            raise ValueError("Order must contain each entry exactly once")
        d["order"] = body["order"]
    else:
        rid = body["id"]
        a = d["people"][rid]
        r = next(r for r in candidates(read(p / "extraction/automatic.json")) if r["id"] == rid)
        vals = body.get("values", a["values"])
        if set(vals) != set(KEYS) or any(
            not isinstance(v, str) or len(v) > 250 for v in vals.values()
        ):
            raise ValueError("Invalid recipient fields")
        changes = {
            k: {"before": a["values"][k], "after": vals[k]}
            for k in KEYS
            if vals[k] != a["values"][k]
        }
        reason = body.get("reason", "").strip()
        status = body.get("status", "unresolved")
        if status not in ("approved", "excluded", "unresolved"):
            raise ValueError("Invalid decision")
        if changes and not reason:
            raise ValueError("Explain the field correction before saving.")
        # Editing and approving are separate actions, including a crafted API request.
        if changes:
            status = "unresolved"
        manual = status == "approved" and not r["eligible"]
        if manual and (not body.get("manual") or not reason):
            raise ValueError(
                "Manual inclusion requires an explicit checkbox and reason; source screening evidence remains unchanged."
            )
        if status == "approved":
            if not all(v.strip() for v in vals.values()):
                raise ValueError("Complete all eight recipient fields before approval.")
            datetime.date.fromisoformat(vals["crash_date"])
            if not re.fullmatch(r"\d{5}(-\d{4})?", vals["zip_code"]):
                raise ValueError("ZIP must have five digits or ZIP+4.")
        a["history"].append(
            {
                "at": now(),
                "changes": changes,
                "previous_status": a["status"],
                "status": status,
                "reason": reason,
                "manual": manual,
            }
        )
        a.update(values=vals, status=status, manual=manual, reason=reason)
    d["revision"] += 1
    save(p / "decisions.json", d)
    return d


def paired_export(p, revision):
    d = read(p / "decisions.json")
    if revision != d["revision"]:
        raise ValueError("Review changed. Refresh before export.")
    m = read(p / "extraction/automatic.json")
    raw = read(p / "extraction/raw.json")
    people = {r["id"]: r for r in candidates(m)}
    m["recipients"] = []
    for rid in d["order"]:
        a = d["people"][rid]
        if a["status"] != "approved":
            continue
        r = copy.deepcopy(people[rid])
        r.update(a["values"])
        r["selection"] += (
            ("; MANUAL INCLUSION: " + a["reason"]) if a["manual"] else "; Explicitly approved"
        )
        m["recipients"].append(r)
    if not m["recipients"]:
        raise ValueError("Approve at least one recipient before export.")
    m["correction_status"] = (
        "Isolated technical test; not owner acceptance"
        if contained(p / "batch.json", p).exists() and read(p / "batch.json").get("test")
        else "Reviewed locally; original extraction retained"
    )
    m["review_decisions"] = d
    m["review"] += [
        {
            "candidate": people[rid],
            "reason": a["status"]
            + ("; MANUAL INCLUSION" if a["manual"] else "")
            + "; "
            + a["reason"]
            + "; Full correction history: paired decisions.json",
        }
        for rid, a in d["people"].items()
    ]
    version = f"v{len(d['exports']) + 1:03d}-r{d['revision']}"
    out = contained(p / "exports" / version, p)
    export_bundle(m, raw, out)
    save(out / "verification.json", verify(out, raw))
    save(out / "decisions.json", d)
    with zipfile.ZipFile(out / "matched-pair.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name in [
            "recipients.xlsx",
            "recipient-proofs.pdf",
            "proof-manifest.json",
            "COMPLETE.json",
            "decisions.json",
            "verification.json",
        ]:
            z.write(out / name, name)
    d["exports"].append(
        {"version": version, "revision": d["revision"], "count": len(m["recipients"]), "at": now()}
    )
    save(p / "decisions.json", d)
    return d["exports"][-1]


EXTRACTION_LOCK = threading.Lock()


def extract(p):
    with EXTRACTION_LOCK:
        _extract(p)


def _extract(p):
    try:
        with contained(p / "progress.log", p).open("w") as log:
            run = subprocess.run(
                [
                    sys.executable,
                    "-u",
                    str(ROOT / "scripts/pdf_only.py"),
                    str(p / "source.pdf"),
                    "--output",
                    str(p / "extraction"),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if run.returncode:
            raise ValueError(
                "Extraction failed. See local extraction log. Unsupported or damaged PDF may require a new scan."
            )
        initialize(p)
        meta = read(p / "batch.json")
        meta.update(status="ready")
        save(p / "batch.json", meta)
    except Exception as e:
        meta = read(p / "batch.json")
        meta.update(status="error", error=str(e))
        save(p / "batch.json", meta)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, kind="application/json", code=200, headers=()):
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", header_value(kind))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in headers:
            self.send_header(header_value(key), header_value(value))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.headers.get("Host") not in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            ):
                raise ValueError("Loopback host required")
            u = urlparse(self.path)
            parts = u.path.strip("/").split("/")
            q = parse_qs(u.query)
            if u.path == "/":
                return self.send(
                    (ROOT.parents[1] / "web/index.html").read_bytes(), "text/html; charset=utf-8"
                )
            if u.path == "/api/batches":
                return self.send(
                    sorted(
                        [read(p) for p in STORE.glob("*/batch.json")],
                        key=lambda batch: (batch.get("created", ""), batch["id"]),
                        reverse=True,
                    )
                )
            p = batch(parts[2])
            meta = read(contained(p / "batch.json", p))
            if len(parts) == 3:
                log = contained(p / "progress.log", p)
                meta["progress"] = (
                    log.read_text()[-3000:] if log.exists() else "Starting extraction"
                )
                if meta["status"] == "ready":
                    m = read(p / "extraction/automatic.json")
                    raw = read(p / "extraction/raw.json")
                    meta.update(
                        people=candidates(m),
                        reports=m["reports"],
                        review=m["review"],
                        decisions=read(p / "decisions.json"),
                        pages=[
                            {
                                "source_page": r["source_page"],
                                "page_size": r["page_size"],
                                "fields": r["fields"],
                                "issues": r["issues"],
                            }
                            for r in raw["pages"]
                        ],
                    )
                return self.send(meta)
            if parts[3] == "page":
                with fitz.open(p / "source.pdf") as doc:
                    return self.send(
                        doc[int(parts[4]) - 1].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png"),
                        "image/png",
                    )
            if parts[3] == "download":
                version = parts[4]
                if not re.fullmatch(r"v\d{3}-r\d+", version):
                    raise ValueError("Incomplete or unknown export")
                if version not in [x["version"] for x in read(p / "decisions.json")["exports"]]:
                    raise ValueError("Incomplete or unknown export")
                data = contained(p / "exports" / version / "matched-pair.zip", p).read_bytes()
                return self.send(
                    data,
                    "application/zip",
                    headers=[
                        (
                            "Content-Disposition",
                            f'attachment; filename="{p.name[:8]}-{version}-matched-pair.zip"',
                        )
                    ],
                )
            raise ValueError("Unknown route")
        except Exception as e:
            self.send({"error": str(e)}, code=400)

    def do_POST(self):
        try:
            if self.headers.get("Host") not in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            ):
                raise ValueError("Loopback host required")
            if (
                self.headers.get("Origin")
                and self.headers["Origin"] != f"http://{self.headers.get('Host')}"
            ):
                raise ValueError("Local same-origin requests only")
            if self.headers.get("X-Review-App") != "1":
                raise ValueError("Use the local review interface")
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= 60 * 1024 * 1024:
                raise ValueError("Choose a PDF smaller than 60 MB")
            data = self.rfile.read(n)
            parts = urlparse(self.path).path.strip("/").split("/")
            if self.path == "/api/upload":
                if not data.startswith(b"%PDF"):
                    raise ValueError("The upload is not a PDF")
                with fitz.open(stream=data, filetype="pdf") as doc:
                    if doc.is_encrypted:
                        raise ValueError("Password-protected PDFs are unsupported")
                    if not len(doc):
                        raise ValueError("PDF has no pages")
                bid = uuid.uuid4().hex
                p = batch(bid)
                p.mkdir(parents=True)
                (p / "source.pdf").write_bytes(data)
                save(
                    p / "batch.json",
                    {
                        "id": bid,
                        "name": unquote(self.headers.get("X-Filename", "Uploaded PDF"))[:180],
                        "status": "extracting",
                        "created": now(),
                        "test": self.headers.get("X-Test-Batch") == "1",
                    },
                )
                threading.Thread(target=extract, args=(p,), daemon=True).start()
                return self.send({"id": bid})
            p = batch(parts[2])
            body = json.loads(data)
            with LOCK:
                if parts[3] == "decision":
                    return self.send(update(p, body))
                if parts[3] == "export":
                    return self.send(paired_export(p, body["revision"]))
            raise ValueError("Unknown action")
        except Exception as e:
            self.send({"error": str(e)}, code=400)


def main():
    STORE.mkdir(parents=True, exist_ok=True)
    for f in STORE.glob("*/batch.json"):
        m = read(f)
        if m["status"] == "extracting":
            m.update(
                status="error",
                error="Extraction interrupted by restart. Upload again; original batch retained.",
            )
            save(f, m)
    port = int(os.environ.get("CRASH_PORT", "8794"))
    print(f"Local review: http://127.0.0.1:{port}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    pidfile = ROOT / "data/review-server.pid"
    pidfile.write_text(str(os.getpid()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if pidfile.exists() and pidfile.read_text() == str(os.getpid()):
            pidfile.unlink()


if __name__ == "__main__":
    main()
