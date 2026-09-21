# Testing and coverage

Run `python -m pytest --cov --cov-report=json:coverage.json` then `python scripts/coverage_gate.py`. The gate requires **80% lines and 80% branches separately** in shared application code, crash processing, plea processing, and deployment logic. `npm test` separately requires 80% statements, branches, functions, and lines in the browser application.

The Python source list in `pyproject.toml` includes each runtime module and both deployment modules; imported packages include unexecuted files. Unit tests do not launch real OCR processes. Tests exercise document writers and routes with synthetic records and isolated temporary stores. The new crash field reader is separately testable without substituting its business logic.

`python -m pytest tests/integration` runs real OCR against generated native, scanned, and sideways documents. `python -m unittest discover -s tests -p test_integration.py` starts both real worker processes and checks uploads, PDFs, ZIPs, review edits, and expiry. Integration runs do not contribute to the unit-coverage gate. macOS runs a real Apple Vision smoke test independently of the Linux release.

`npm run test:browser` verifies desktop/mobile layout, keyboard access, upload, errors, filters, and downloads. Browser API responses are synthetic and deterministic. Playwright saves full-page review images; failure screenshots and traces are retained for three days in Actions. A deployment additionally runs real synthetic uploads and downloads and immediately removes only those check jobs.

Exclusions: `worker.py` and `page_worker.py` are subprocess entry points verified by integration tests; `web/main.js` only starts the application and polling; build/fixture/smoke scripts and shell provisioning are exercised by the clean-install workflow. Historical probes, personal documents, generated files, environment libraries, and superseded standalone browser UIs are not shipped application code. No business-rule module is excluded to improve coverage. CI coverage reports are the source of truth for each commit.

The CI runner installs onto a new empty `/opt/lawdocs/shared` and starts the same image sent to production. It then creates a deliberately broken production-start image, verifies deployment failure, and checks that the exact previous release is restored. This is never run against production.
