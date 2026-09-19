"""Delete complete server jobs after their fixed upload lifetime."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import threading
import time

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()


def hours():
    return float(os.environ.get("JOB_RETENTION_HOURS", "0"))


def stores(root=ROOT):
    return {
        "crash": Path(os.environ.get("CRASH_BATCHES", root / "engines/crash_report/data/batches")),
        "plea": Path(os.environ.get("PLEA_DATA", root / "engines/plea_reports/data")),
    }


def uploaded(directory, kind, root=ROOT):
    metadata = directory / ("batch.json" if kind == "crash" else "result.json")
    try:
        value = json.loads(metadata.read_text()).get("created")
        if not value and kind == "plea":
            value = json.loads(
                Path(
                    os.environ.get(
                        "PLEA_UPLOAD_TIMES", root / "engines/plea_reports/upload-times.json"
                    )
                ).read_text()
            ).get(directory.name)
        if value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()
    except (OSError, ValueError, TypeError):
        pass
    # Original source mtime survives migration and is unaffected by edits/downloads.
    source = directory / "source.pdf"
    return source.stat().st_mtime if source.is_file() else directory.stat().st_mtime


def expired(kind, ident, root=ROOT, now=None):
    if hours() <= 0:
        return False
    directory = stores(root)[kind] / ident
    try:
        return directory.is_dir() and uploaded(directory, kind, root) + hours() * 3600 <= (
            time.time() if now is None else now
        )
    except FileNotFoundError:
        return False


def sweep(root=ROOT, now=None):
    if hours() <= 0:
        return []
    now = time.time() if now is None else now
    removed = []
    with LOCK:
        for kind, store in stores(root).items():
            if not store.exists():
                continue
            for directory in store.iterdir():
                if directory.is_symlink() or not directory.is_dir():
                    continue
                if expired(kind, directory.name, root, now):
                    try:
                        shutil.rmtree(directory)
                    except FileNotFoundError:
                        continue
                    removed.append({"kind": kind, "id": directory.name})
        if removed:
            print(json.dumps({"retention_deleted": removed}), flush=True)
    return removed


def start():
    if hours() <= 0:
        return
    sweep()

    def run():
        while True:
            time.sleep(60)
            try:
                sweep()
            except Exception as exc:
                print(f"Retention cleanup failed: {exc}", flush=True)

    threading.Thread(target=run, daemon=True, name="job-retention").start()
