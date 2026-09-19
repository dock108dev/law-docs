import io
from datetime import datetime, timezone
import math
import pymupdf
import copy
import json
import os
import threading
import uuid
from pathlib import Path
from flask import Flask, request, jsonify, send_file, abort
from .extract import extract_calendar
from .pdf_export import make_pdf, row_errors, person_key, build_slips

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
lock = threading.RLock()


def folder(job_id):
    if not (
        job_id == "sample" or (len(job_id) == 32 and all(c in "0123456789abcdef" for c in job_id))
    ):
        abort(404)
    p = DATA / job_id
    if not p.is_dir():
        abort(404)
    return p


def read_job(job_id):
    with lock:
        return json.loads((folder(job_id) / "result.json").read_text())


def write_job(directory, data):
    with lock:
        temp = directory / "result.json.tmp"
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(directory / "result.json")


EXTRACTION_LOCK = threading.Lock()


def run_extract(job_id):
    with EXTRACTION_LOCK:
        _run_extract(job_id)


def _run_extract(job_id):
    directory = folder(job_id)
    initial = read_job(job_id)
    try:

        def progress(message):
            initial["message"] = message
            write_job(directory, initial)

        extracted = extract_calendar(directory / "source.pdf", directory, progress)
        extracted.update(
            {
                "id": job_id,
                "filename": initial["filename"],
                "created": initial.get(
                    "created",
                    datetime.fromtimestamp(
                        getattr(directory.stat(), "st_birthtime", directory.stat().st_mtime),
                        timezone.utc,
                    ).isoformat(),
                ),
                "revision": 0,
            }
        )
        write_job(directory, extracted)
    except Exception as exc:
        initial.update(status="error", message=str(exc))
        write_job(directory, initial)


@app.before_request
def local_writes():
    if request.method in ("POST", "PATCH", "DELETE"):
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            abort(403, description="Use the local app to make changes.")


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Upload a PDF smaller than 40 MB."), 413


@app.errorhandler(ValueError)
def invalid(exc):
    return jsonify(error=str(exc)), 400


@app.get("/")
def home():
    return send_file(ROOT.parents[1] / "web/index.html")


@app.get("/api/jobs")
def jobs():
    result = []
    times_path = Path(os.environ.get("PLEA_UPLOAD_TIMES", ROOT / "upload-times.json"))
    upload_times = json.loads(times_path.read_text()) if times_path.exists() else {}
    for p in DATA.glob("*/result.json"):
        try:
            r = json.loads(p.read_text())
            result.append(
                {
                    "id": p.parent.name,
                    "filename": r.get("filename", "Supplied sample"),
                    "status": r["status"],
                    "count": len(r.get("rows", [])),
                    "created": r.get("created")
                    or upload_times.get(p.parent.name)
                    or datetime.fromtimestamp(
                        getattr(p.parent.stat(), "st_birthtime", p.parent.stat().st_mtime),
                        timezone.utc,
                    ).isoformat(),
                }
            )
        except (ValueError, KeyError):
            continue
    return jsonify(sorted(result, key=lambda job: (job["created"], job["id"]), reverse=True))


@app.post("/api/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".pdf"):
        raise ValueError("Choose a calendar PDF.")
    ident = uuid.uuid4().hex
    directory = DATA / ident
    directory.mkdir()
    f.save(directory / "source.pdf")
    if not (directory / "source.pdf").read_bytes().startswith(b"%PDF-"):
        raise ValueError("This file is not a PDF.")
    write_job(
        directory,
        {
            "id": ident,
            "filename": Path(f.filename).name,
            "created": datetime.now(timezone.utc).isoformat(),
            "status": "extracting",
            "message": "Reading calendar",
            "rows": [],
            "pages": [],
            "revision": 0,
        },
    )
    threading.Thread(target=run_extract, args=(ident,), daemon=True).start()
    return jsonify(id=ident), 202


@app.get("/api/jobs/<job_id>")
def job(job_id):
    return jsonify(read_job(job_id))


@app.patch("/api/jobs/<job_id>/rows/<row_id>")
def update_row(job_id, row_id):
    with lock:
        data = read_job(job_id)
        body = request.get_json()
        if data["status"] != "ready":
            raise ValueError("Wait for extraction to finish.")
        row = next((r for r in data["rows"] if r["id"] == row_id), None)
        if row is None:
            abort(404)
        for field in ("name", "case_number", "review_note", "exclusion_reason"):
            if field in body:
                row[field] = str(body[field]).strip()
        if "offenses" in body:
            if not isinstance(body["offenses"], list):
                raise ValueError("Offenses must be separate lines.")
            row["offenses"] = [str(s).strip() for s in body["offenses"] if str(s).strip()]
        row["reviewed"] = bool(body.get("reviewed", False))
        row["excluded"] = bool(body.get("excluded", row["excluded"]))
        if row["excluded"] and not row["exclusion_reason"]:
            raise ValueError("Record a reason before excluding a row.")
        if row["reviewed"] and not row["excluded"] and row_errors(row):
            raise ValueError("; ".join(row_errors(row)))
        for page in data["pages"]:
            if page["number"] == row["source_page"]:
                page["reconciled"] = False
        data["revision"] = data.get("revision", 0) + 1
        write_job(folder(job_id), data)
    return jsonify(data)


@app.post("/api/jobs/<job_id>/rows")
def add_row(job_id):
    with lock:
        data = read_job(job_id)
        body = request.get_json()
        if data["status"] != "ready":
            raise ValueError("Wait for extraction to finish.")
        number = int(body["source_page"])
        page = next((p for p in data["pages"] if p["number"] == number), None)
        if page is None:
            raise ValueError("Choose an existing source page.")
        try:
            position = float(body["source_row"])
        except (TypeError, ValueError):
            raise ValueError("Enter a valid row position.")
        if (
            not math.isfinite(position)
            or position <= 0
            or any(r["source_page"] == number and r["source_row"] == position for r in data["rows"])
        ):
            raise ValueError(
                "Choose an unused source position; use 2.5 to insert between rows 2 and 3."
            )
        row = {
            "id": "manual-" + uuid.uuid4().hex[:10],
            "source_page": number,
            "source_row": position,
            "name": "",
            "case_number": "",
            "offenses": [],
            "reviewed": False,
            "excluded": False,
            "exclusion_reason": "",
            "review_note": "Manually added printed row.",
            "manual": True,
            "issues": ["Enter the missing printed row from the source page."],
            "ocr": {},
            "raw_ocr": {},
        }
        data["rows"].append(row)
        data["rows"].sort(key=lambda r: (r["source_page"], r["source_row"]))
        page["reconciled"] = False
        data["revision"] = data.get("revision", 0) + 1
        write_job(folder(job_id), data)
    return jsonify(data=data, row_id=row["id"])


@app.patch("/api/jobs/<job_id>/pages/<int:number>")
def reconcile(job_id, number):
    with lock:
        data = read_job(job_id)
        body = request.get_json()
        page = next((p for p in data["pages"] if p["number"] == number), None)
        if page is None:
            abort(404)
        count = sum(r["source_page"] == number for r in data["rows"])
        if body.get("count") != count:
            raise ValueError(
                f"There are {count} recorded rows on this page. Add any missing printed rows or account for extra rows before confirming."
            )
        page["reconciled"] = True
        page["review_count"] = count
        data["revision"] = data.get("revision", 0) + 1
        write_job(folder(job_id), data)
    return jsonify(data)


@app.get("/api/jobs/<job_id>/images/<name>")
def source_image(job_id, name):
    if "/" in name or not name.endswith(".png"):
        abort(404)
    directory = folder(job_id)
    path = directory / name
    if path.parent != directory or not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/png")


@app.get("/api/jobs/<job_id>/source")
def source_pdf(job_id):
    return send_file(folder(job_id) / "source.pdf", mimetype="application/pdf")


@app.get("/api/jobs/<job_id>/preview/<row_id>")
def preview(job_id, row_id):
    with lock:
        data = read_job(job_id)
        row = next((r for r in data["rows"] if r["id"] == row_id), None)
        if row is None:
            abort(404)
        group = [
            copy.deepcopy(r)
            for r in data["rows"]
            if person_key(r) == person_key(row) and not r.get("excluded")
        ]
        if not group:
            group = [copy.deepcopy(row)]
            group[0]["excluded"] = False
        path = folder(job_id) / f"preview-{uuid.uuid4().hex}.pdf"
        make_pdf(group, path, draft=True)
    if request.args.get("format") == "png":
        with pymupdf.open(path) as document:
            number = int(request.args.get("page", "0"))
            if number < 0 or number >= len(document):
                raise ValueError("Preview page is out of range.")
            total = len(document)
            image = document[number].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).tobytes("png")
        response = send_file(io.BytesIO(image), mimetype="image/png", max_age=0)
        response.headers["X-Preview-Pages"] = str(total)
        return response
    # Preview uses the actual generated PDF; preview files are disposable.
    response = send_file(path, mimetype="application/pdf", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/jobs/<job_id>/export")
def export(job_id):
    data = read_job(job_id)
    if data["status"] != "ready":
        raise ValueError("Wait for extraction to finish.")
    draft = request.args.get("draft", "1") != "0"
    if not draft and any(not p["reconciled"] for p in data["pages"]):
        raise ValueError("Confirm every source page count before reviewed export.")
    tag = "review-draft" if draft else "reviewed-slips"
    path = folder(job_id) / f"{tag}-{uuid.uuid4().hex}.pdf"
    make_pdf(data["rows"], path, draft=draft)
    return send_file(
        path, mimetype="application/pdf", as_attachment=True, download_name=f"plea-{tag}.pdf"
    )


@app.get("/api/jobs/<job_id>/review-record")
def record(job_id):
    return send_file(
        folder(job_id) / "result.json", as_attachment=True, download_name="plea-review-record.json"
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1", port=int(os.environ.get("PLEA_PORT", "8790")), debug=False, threaded=True
    )
