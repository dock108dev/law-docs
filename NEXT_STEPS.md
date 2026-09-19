# Lawdocs implementation tracker

The requested work is implemented in this repository. Final acceptance is tied to the successful GitHub Actions run and live release, not merely the presence of workflow files.

- Private standalone repository: `dock108dev/law-docs`.
- Unit coverage: enforced minimum 80% lines and branches for shared Python code, both processing engines, deployment code, and the frontend. Real OCR tests are separate.
- Delivery: pinned runtime and dependencies, synthetic integration tests, clean host installation, deliberately failed-release rollback, automatic production deployment, and a manual fresh-host workflow.
- Design: custom document workspace with desktop/mobile behavior, keyboard access, status and deletion times, and direct proof-linked downloads.

See [testing](docs/TESTING.md) for coverage scope and commands, and [operations](deploy/README.md) for deployment and host setup. Actions reports and `/api/health` identify the verified commit. Future enhancements should be proposed separately; this plan does not add unrelated product features.
