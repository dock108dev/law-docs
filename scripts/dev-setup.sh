#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r deploy/requirements.lock -r deploy/dev-requirements.lock
if [ "$(uname -s)" = Darwin ]; then
    .venv/bin/pip install pyobjc-framework-Vision==12.2 pyobjc-framework-Quartz==12.2
fi
for engine in crash_report plea_reports; do
    if [ ! -e "engines/$engine/.venv" ]; then ln -s ../../.venv "engines/$engine/.venv"; fi
done
.venv/bin/python scripts/install_models.py
npm ci
printf 'Setup complete. Start with ./start.command; tests are documented in docs/TESTING.md.\n'
