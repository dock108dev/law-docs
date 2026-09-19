"""CI-only failure injection on the disposable runner; never targets production."""

import hashlib, io, json, subprocess, sys, tempfile, urllib.request
from pathlib import Path

commit = sys.argv[1]
bad = "f" * 40
with tempfile.TemporaryDirectory() as temp:
    folder = Path(temp)
    # JSON encoding avoids shell/Dockerfile quoting ambiguity.
    command = 'if [ "$REPORT_PORT" = 18795 ]; then exec python server.py; else exit 1; fi'
    (folder / "Dockerfile").write_text(
        f"FROM lawdocs:{commit}\nCMD " + json.dumps(["sh", "-c", command]) + "\n"
    )
    subprocess.run(["docker", "build", "-t", f"lawdocs:{bad}", str(folder)], check=True)
    target = folder / "bad.tar"
    subprocess.run(["docker", "save", "-o", str(target), f"lawdocs:{bad}"], check=True)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    subprocess.run(["sudo", "cp", str(target), f"/opt/lawdocs/incoming/{bad}.tar.gz"], check=True)
    result = subprocess.run(["sudo", "/usr/local/sbin/lawdocs-release", bad, digest])
    assert result.returncode != 0, "Broken release was accepted"
    with urllib.request.urlopen("http://127.0.0.1:8795/api/health", timeout=20) as r:
        assert json.load(r)["release"] == commit
print("Failed release rolled back to the exact previous commit")
