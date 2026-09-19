"""Run the existing extraction engines with their own installed dependencies."""

import json
import os
import re
import sys
from pathlib import Path

kind, ready_file = sys.argv[1:]
ROOT = Path(__file__).resolve().parent / "engines"
if kind == "crash":
    sys.path.insert(0, str(ROOT / "crash_report/scripts"))
    import review_app as engine
    from http.server import ThreadingHTTPServer

    engine.STORE.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), engine.Handler)
    store, pattern, state_file = engine.STORE, "*/batch.json", "batch.json"
else:
    sys.path.insert(0, str(ROOT / "plea_reports"))
    import app.server as engine
    from werkzeug.serving import make_server

    if os.environ.get("PLEA_DATA"):
        engine.DATA = Path(os.environ["PLEA_DATA"])
    engine.DATA.mkdir(parents=True, exist_ok=True)
    original_jobs = engine.app.view_functions["jobs"]

    def visible_jobs():
        # Backup snapshots are not editable jobs and are rejected by the engine.
        return engine.jsonify(
            [
                job
                for job in original_jobs().get_json()
                if job["id"] == "sample" or re.fullmatch(r"[a-f0-9]{32}", job["id"])
            ]
        )

    engine.app.view_functions["jobs"] = visible_jobs
    server = make_server("127.0.0.1", 0, engine.app, threaded=True)
    store, pattern, state_file = engine.DATA, "*/result.json", "result.json"
# Previous unfinished work is retained and made visibly recoverable.
for path in store.glob(pattern):
    data = json.loads(path.read_text())
    if data.get("status") == "extracting":
        data.update(
            status="error",
            error="Processing was interrupted. Upload the PDF again; the original is retained.",
            message="Processing was interrupted. Upload the PDF again; the original is retained.",
        )
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(path)
Path(ready_file).write_text(str(server.server_port))
server.serve_forever()
