# Report Workspace

Upload a PDF, then click **Download + proof sheet**. The hosted workspace is https://lawdocs.dock108.dev (no login required). A separate local copy can run at http://127.0.0.1:8795. See [server operation notes](deploy/README.md).

Double-click `start.command` to start. Leave its terminal open; Control-C stops the app. Existing files appear automatically. The same simple screen opens at the former crash and plea URLs.

## Downloads

- **Crash reports:** a ZIP with a Household mailings Excel sheet, individual supporting records, one report-pages PDF per household, a combined report-pages PDF, and source mapping/proof records. Each household receives the first page of each distinct crash once. Drivers need their own recorded injury (01–04), an unambiguous vehicle/driver-seat association, and no contributing action recorded (25). Injured passengers qualify independently of their driver. Unknown/conflicting evidence is held. Full mailing addresses include apartment/unit numbers; incomplete addresses stay separate and flagged. Saved corrections, exclusions, and explicitly labeled manual inclusions are retained. Existing uploads are re-evaluated from retained readings on download without rewriting the originals. This groups households within each download, not across previous mailings. Add your own letters/brochures; these downloads contain the report-page portion of the mailing.
- **Plea calendars:** a ZIP containing plea slips, a proof sheet matching each slip/charge to its source row image, the original PDF, and a source map. Matching printed names group across the calendar, with up to four charges per sheet. Previously saved edits and exclusions are retained. No row review or page-count confirmation is needed.

Missing fields remain blank and detected uncertainties appear on the proof sheet. Source proofs make checking easier; they do not certify OCR accuracy. If no results are found, the download contains an explanatory proof sheet. It does not invent recipients or charges. Original extraction and saved review records are not modified by downloads.

Supported inputs include NJTR-1 first-page crash PDFs (60 MB limit) and ruled court calendars (40 MB, 60 pages). Calendars with embedded text use the labeled Defendant Name, Case Number, and Offense columns directly; scanned and sideways calendars use local OCR. The extraction method is selected per page, so mixed PDFs are supported. Other layouts need extractor work. Files persist locally until manually removed.

## One local root

`report_workspace` contains the shared app and `engines/crash_report/` and `engines/plea_reports/`, including installed environments, source documents, templates, saved data, and historical evidence. Keep this workspace together. Earlier documents inside the engines describe historical workflows. macOS Python, Tesseract, and the installed Codex dependency runtime are still used on this Mac.

The launcher starts and stops both engines. Do not run their standalone launchers at the same time. `REPORT_PORT` overrides 8795. Interrupted extractions retain their original input and can be retried with a fresh upload.

## Checks

Run `engines/plea_reports/.venv/bin/python -m unittest discover -s tests -v`. Integration checks use temporary stores and cover uploads, simple routes, ungated downloads, proof mapping, unchanged saved records, and empty results. The original engine tests remain in their engine folders.

The consolidation inventory in `migration/` records the earlier folder move. It is historical evidence, not a checksum of subsequent code changes.
