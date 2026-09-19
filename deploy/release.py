#!/usr/bin/python3
"""Load, verify, activate, and roll back one tested container release."""

import fcntl, hashlib, json, os, pwd, re, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path("/opt/lawdocs")
CONFIG = Path("/etc/lawdocs")
UNITS = Path("/etc/systemd/system")
LOCKFILE = Path("/run/lock/lawdocs-deploy.lock")


def run(*args, **kw):
    return subprocess.run(args, check=True, **kw)


def health(port=8795):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:
        return json.load(r)


def wait_health(commit, port=8795):
    for _ in range(90):
        try:
            if health(port)["release"] == commit:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Release health check failed")


def smoke(commit, port, data):
    result = run(
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--entrypoint",
        "python",
        f"lawdocs:{commit}",
        "scripts/smoke.py",
        f"http://127.0.0.1:{port}",
        "--release",
        commit,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["result"] == "passed"
    for kind, ident in report["synthetic_jobs"]:
        if kind not in ("crash", "plea") or not re.fullmatch("[a-f0-9]{32}", ident):
            raise ValueError("Invalid synthetic check identity")
        shutil.rmtree(data / kind / ident)
    print("Synthetic upload/download check passed")


def main(commit, digest):
    if not re.fullmatch("[a-f0-9]{40}", commit) or not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("Invalid release identity")
    artifact = ROOT / "incoming" / f"{commit}.tar.gz"
    if artifact.is_symlink():
        raise ValueError("Symlink artifact forbidden")
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
        raise ValueError("Artifact checksum mismatch")
    with LOCKFILE.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run("docker", "load", "-i", str(artifact))
        uid = pwd.getpwnam("lawdocs").pw_uid
        gid = pwd.getpwnam("lawdocs").pw_gid
        with tempfile.TemporaryDirectory(prefix="lawdocs-check-") as temp:
            data = Path(temp)
            os.chmod(data, 0o755)
            for kind in ("crash", "plea"):
                (data / kind).mkdir()
                os.chown(data / kind, uid, gid)
            try:
                run(
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    "lawdocs-candidate",
                    "--network",
                    "host",
                    "--user",
                    f"{uid}:{gid}",
                    "-e",
                    "REPORT_PORT=18795",
                    "-e",
                    f"LAW_DOCS_RELEASE={commit}",
                    "-v",
                    f"{data}:/data",
                    f"lawdocs:{commit}",
                    stdout=subprocess.DEVNULL,
                )
                wait_health(commit, 18795)
                smoke(commit, 18795, data)
            finally:
                subprocess.run(
                    ["docker", "rm", "-f", "lawdocs-candidate"], stdout=subprocess.DEVNULL
                )
        drain = ROOT / "shared/.draining"
        drain.touch()
        try:
            deadline = time.monotonic() + 900
            while True:
                pending = []
                for pattern in ("crash/*/batch.json", "plea/*/result.json"):
                    for p in (ROOT / "shared").glob(pattern):
                        if json.loads(p.read_text()).get("status") == "extracting":
                            pending.append(p)
                try:
                    active = health().get("active_requests", 0)
                except Exception:
                    active = 0
                if not pending and not active:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("Active work did not drain; deployment cancelled")
                time.sleep(2)
            previous = (
                (CONFIG / "release.env").read_bytes() if (CONFIG / "release.env").exists() else None
            )
            old_unit = (
                (UNITS / "lawdocs.service").read_bytes()
                if (UNITS / "lawdocs.service").exists()
                else None
            )
            (CONFIG / "release.env").write_text(f"RELEASE={commit}\nAPP_UID={uid}\nAPP_GID={gid}\n")
            site = (CONFIG / "site").read_text().strip()
            origin = site if "://" in site else "https://" + site
            (CONFIG / "app.env").write_text(
                f"PUBLIC_ORIGIN={origin}\nJOB_RETENTION_HOURS=48\nDRAIN_FILE=/data/.draining\n"
            )
            shutil.copy(UNITS / "lawdocs.service.next", UNITS / "lawdocs.service")
            run("systemctl", "daemon-reload")
            run("systemctl", "enable", "lawdocs")
            try:
                run("systemctl", "restart", "lawdocs")
                wait_health(commit)
                drain.unlink(missing_ok=True)
                smoke(commit, 8795, ROOT / "shared")
            except Exception:
                if previous is not None:
                    (CONFIG / "release.env").write_bytes(previous)
                if old_unit is not None:
                    (UNITS / "lawdocs.service").write_bytes(old_unit)
                run("systemctl", "daemon-reload")
                run("systemctl", "restart", "lawdocs")
                if previous is not None:
                    wait_health(re.search(rb"RELEASE=(\w+)", previous)[1].decode())
                raise
            (ROOT / "releases" / commit).write_text(
                json.dumps(
                    {"commit": commit, "artifact_sha256": digest, "deployed_at": time.time()}
                )
            )
            releases = sorted(
                (ROOT / "releases").iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
            )
            for old in releases[3:]:
                subprocess.run(
                    ["docker", "image", "rm", f"lawdocs:{old.name}"], stdout=subprocess.DEVNULL
                )
                old.unlink()
            print("Deployed and verified " + commit)
        finally:
            drain.unlink(missing_ok=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
