#!/usr/bin/python3
"""Restricted SSH upload receiver; the key can only deliver a hashed release."""

import hashlib, os, re, subprocess, sys
from pathlib import Path

command = os.environ.get("SSH_ORIGINAL_COMMAND", "")
match = re.fullmatch(r"deploy ([a-f0-9]{40}) ([a-f0-9]{64})", command)
if not match:
    raise SystemExit("Expected deploy COMMIT SHA256")
commit, digest = match.groups()
path = Path("/opt/lawdocs/incoming") / (commit + ".tar.gz")
h = hashlib.sha256()
count = 0
try:
    with path.open("wb") as f:
        while block := sys.stdin.buffer.read(1024 * 1024):
            count += len(block)
            if count > 2 * 1024**3:
                raise ValueError("Release exceeds 2 GB")
            h.update(block)
            f.write(block)
    if h.hexdigest() != digest:
        raise ValueError("Release checksum mismatch")
    subprocess.run(["sudo", "/usr/local/sbin/lawdocs-release", commit, digest], check=True)
finally:
    path.unlink(missing_ok=True)
