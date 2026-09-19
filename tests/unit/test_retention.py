import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
import retention


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 2_000_000_000
        self.env = patch.dict(
            os.environ,
            {
                "JOB_RETENTION_HOURS": "48",
                "PLEA_UPLOAD_TIMES": str(self.root / "engines/plea_reports/upload-times.json"),
                "CRASH_BATCHES": str(self.root / "crash"),
                "PLEA_DATA": str(self.root / "plea"),
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def job(self, kind, name, age, created=True):
        p = self.root / kind / name
        p.mkdir(parents=True)
        timestamp = self.now - age * 3600
        meta = {"status": "ready"}
        if created:
            meta["created"] = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
        (p / ("batch.json" if kind == "crash" else "result.json")).write_text(json.dumps(meta))
        (p / "source.pdf").write_bytes(b"original")
        os.utime(p / "source.pdf", (timestamp, timestamp))
        (p / "edits.json").write_text("saved edits")
        (p / "exports").mkdir()
        (p / "exports/output.zip").write_bytes(b"output")
        return p

    def test_entire_job_expires_at_boundary_without_extending_on_edit(self):
        old = self.job("crash", "a" * 32, 48)
        young = self.job("plea", "b" * 32, 47.999)
        os.utime(young / "exports/output.zip", (0, 0))
        removed = retention.sweep(self.root, self.now)
        self.assertEqual(removed, [{"kind": "crash", "id": "a" * 32}])
        self.assertFalse(old.exists())
        self.assertTrue((young / "source.pdf").exists())
        retention.sweep(self.root, self.now + 4)
        self.assertFalse(young.exists())

    def test_legacy_upload_time_and_source_fallback(self):
        p = self.job("plea", "c" * 32, 1, created=False)
        mapping = self.root / "engines/plea_reports/upload-times.json"
        mapping.parent.mkdir(parents=True)
        mapping.write_text(
            json.dumps(
                {p.name: datetime.fromtimestamp(self.now - 49 * 3600, timezone.utc).isoformat()}
            )
        )
        backup = self.job("plea", "owner-review-baseline", 49, created=False)
        sample = self.job("plea", "sample", 49, created=False)
        self.assertEqual(len(retention.sweep(self.root, self.now)), 3)
        self.assertFalse(backup.exists())
        self.assertFalse(sample.exists())

    def test_local_default_keeps_files_and_external_links_are_untouched(self):
        old = self.job("crash", "d" * 32, 100)
        with patch.dict(os.environ, {"JOB_RETENTION_HOURS": "0"}):
            self.assertEqual(retention.sweep(self.root, self.now), [])
        self.assertTrue(old.exists())
        external = self.root / "external"
        external.mkdir()
        (external / "keep").write_text("keep")
        (self.root / "crash/link").symlink_to(external, target_is_directory=True)
        retention.sweep(self.root, self.now)
        self.assertTrue((external / "keep").exists())


if __name__ == "__main__":
    unittest.main()
