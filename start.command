#!/bin/zsh
cd "${0:A:h}"
exec engines/plea_reports/.venv/bin/python server.py
