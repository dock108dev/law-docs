# Lawdocs

A focused workspace for NJ crash reports and municipal plea calendars. Upload a PDF and download organized results with source proofs.

**Live:** https://lawdocs.dock108.dev · No login required. Uploaded documents and results are shared on the site and deleted **48 hours after upload**. Download needed files before expiry. Editing and downloading do not extend that time.

## Workflows

- **Crash reports:** identify injured drivers with no recorded contributing action, and independently consider injured passengers. Group selected people by complete household address, including apartment/unit. Downloads include the household workbook, individual supporting records, and one original first crash page per distinct report per household. Letters and brochures are not generated. Unknown or conflicting evidence remains held for review.
- **Plea calendars:** read native text, scans, sideways pages, and mixed calendars. Group exact printed names into plea slips with up to four charges per page. Include original source and per-charge proofs. OCR uncertainty remains visible; proofs do not certify accuracy.

## Local development

Use Python 3.14+, Node 22.18+, and Tesseract with English and orientation data. On macOS install Tesseract with your package manager. On Debian/Ubuntu install `tesseract-ocr`, `libgl1`, and `libglib2.0-0`.

On a clean checkout, run `bash scripts/dev-setup.sh`, then `./start.command`. The app opens at http://127.0.0.1:8795. Local expiry is disabled by default; `JOB_RETENTION_HOURS=48` enables the hosted policy. The production Docker image pins the Python runtime, dependency hashes, OCR source version, and model hashes.

## Tests and delivery

See [testing and coverage](docs/TESTING.md) and [server operations](deploy/README.md). GitHub Actions checks unit coverage, browser behavior, actual OCR, document generation, dependency vulnerabilities, clean installation, and rollback before deploying a main-branch release. A separate manual workflow provisions an authorized fresh host and installs an already-tested release.

Real uploaded reports, saved job data, credentials, historical evidence, and local environments are excluded from Git. CI uses generated synthetic documents. Operating-system adapters and process launchers are verified in their corresponding runtime checks.
