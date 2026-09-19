# Lawdocs server

- URL: https://lawdocs.dock108.dev
- Server: 62.238.114.86 (Ubuntu), SSH aliases `hetzner` and `lawdocs` on the owner's Mac.
- App: `/opt/lawdocs`, unprivileged `lawdocs` service account.
- Start/restart: `sudo systemctl restart lawdocs`. Logs: `sudo journalctl -u lawdocs`.
- HTTPS: Caddy, `/etc/caddy/Caddyfile`. No login is required. The former local credentials file is obsolete.
- The app and its processors bind to loopback only. Caddy exposes the public HTTPS site.
- Saved documents: `engines/crash_report/data` and `engines/plea_reports/data`. Back up both directories with the original PDFs, extraction records, and saved decisions together.
- Runtime: `/opt/lawdocs/.venv`, linked from both engines. `deploy/requirements.txt` records Python dependencies. A 2 GB swap file provides an additional memory reserve. Ubuntu packages: python3-venv, tesseract-ocr, caddy, libgl1, libglib2.0-0t64, rsync.
- Plea OCR uses Tesseract 5.5.1 at `/opt/lawdocs/tesseract/bin/tesseract`, matching the Mac version. English and orientation language files match the Mac by SHA-256. The source archive and build log are under `/opt/lawdocs/build`.
- Linux crash OCR runs each page in its own subprocess to release model memory. Upload extraction is serialized per workflow.
- Linux uses local RapidOCR for crash text and Tesseract for numeric retries and scanned plea tables. Models are downloaded during setup, then reused locally. Extraction blocks Python network connections in both the parent and isolated page workers. macOS keeps Apple Vision.
- Linux Excel generation uses the portable writer; the household records and source verification remain the same.
- The local Mac copy remains independent. After cutover, new server uploads/edits are not automatically copied back to the Mac.

Deployment copies source separately from data. Do not overwrite server data with an older Mac snapshot. Qualification output is archived on the Mac at `/Users/michaelfuscoletti/Desktop/report_workspace-archive/2026-09-18/server-qualification`; server test copies were removed.

## Verified migration and known OCR differences

All 2,383 saved data files matched their local SHA-256 hashes after transfer. The clean plea calendar reproduces all 131 rows and 69 slips. The sideways scan reproduces 133 rows; four OCR rows differ from the Mac and retain source-check notes, including one withheld case number. Details are in `deploy/scan-comparison.json`. Original saved results were not replaced by re-extraction.

The fresh nine-page crash qualification, with targeted page re-runs after crop corrections, reproduces the two expected injured drivers in two households, including all eight mailing fields. In the local qualification archive, the comparison is in `current-crash/comparison.json`; workbook, proof, and original household-page checks are in `final-crash-delivery/verification.json`. The Linux engine uses two confident focused reads before accepting code 25. OCR remains subject to the source-proof checks shown in downloads.

## Retention and synchronization

The hosted service sets `JOB_RETENTION_HOURS=48`. Each entire job (source PDF, OCR images, extraction records, edits, and exports) expires 48 hours after its original upload time. Editing, downloading, or restarting does not extend it. Cleanup runs at startup, every minute, and before requests; expired jobs cannot be downloaded. Legacy uploads use the migrated upload timestamps or original source-file mtime. This includes the sample and old job snapshots. Local cleanup is disabled unless explicitly configured.

The local and hosted application code and retained job data were synchronized after this change. This is a point-in-time sync, not continuous replication. OS-specific Python environments, OCR binaries, build caches, local archives, and development evidence are excluded. Do not push an old data snapshot back to the server: it can restore expired jobs. Server data is authoritative for future pulls; archive local-only jobs outside the active data folders before mirroring.

Use `deploy/sync-excludes.txt` for code synchronization so runtime files, report fixtures, archives, and job data are not accidentally copied or removed with source files. Job data must be reconciled separately. Required blank templates and NJ code references remain deployed.
