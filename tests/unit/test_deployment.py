import hashlib, io, json, os
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from deploy import receive, release

COMMIT = "a" * 40
DIGEST = hashlib.sha256(b"image").hexdigest()


def test_receiver(tmp_path, monkeypatch):
    call = Mock()
    monkeypatch.setattr(receive.subprocess, "run", call)
    receive.receive(f"deploy {COMMIT} {DIGEST}", io.BytesIO(b"image"), tmp_path)
    call.assert_called_once()
    assert not list(tmp_path.iterdir())
    with pytest.raises(SystemExit):
        receive.receive("rm -rf /", io.BytesIO(), tmp_path)
    for digest, limit in [("b" * 64, 100), (DIGEST, 1)]:
        with pytest.raises(ValueError):
            receive.receive(f"deploy {COMMIT} {digest}", io.BytesIO(b"image"), tmp_path, limit)
    assert not list(tmp_path.iterdir())


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / "root"
    config = tmp_path / "config"
    units = tmp_path / "units"
    for p in (
        root / "incoming",
        root / "releases",
        root / "shared/crash",
        root / "shared/plea",
        config,
        units,
    ):
        p.mkdir(parents=True, exist_ok=True)
    (root / "incoming" / f"{COMMIT}.tar.gz").write_bytes(b"image")
    (config / "site").write_text("lawdocs.example")
    (units / "lawdocs.service").write_text("old service")
    (units / "lawdocs.service.next").write_text("new service")
    monkeypatch.setattr(release, "ROOT", root)
    monkeypatch.setattr(release, "CONFIG", config)
    monkeypatch.setattr(release, "UNITS", units)
    monkeypatch.setattr(release, "LOCKFILE", tmp_path / "lock")
    monkeypatch.setattr(
        release.pwd, "getpwnam", lambda name: NS(pw_uid=os.getuid(), pw_gid=os.getgid())
    )
    monkeypatch.setattr(release, "run", Mock())
    monkeypatch.setattr(release.subprocess, "run", Mock())
    monkeypatch.setattr(release, "health", lambda *args: {"release": COMMIT, "active_requests": 0})
    monkeypatch.setattr(release, "wait_health", Mock())
    monkeypatch.setattr(release, "smoke", Mock())
    return root, config, units


def test_release_success_and_pruning(host, monkeypatch):
    root, config, units = host
    for i in range(4):
        p = root / "releases" / str(i)
        p.write_text("{}")
        os.utime(p, (0, 0))
    release.main(COMMIT, DIGEST)
    assert len(list((root / "releases").iterdir())) == 3
    assert (units / "lawdocs.service").read_text() == "new service"
    assert f"RELEASE={COMMIT}" in (config / "release.env").read_text()
    assert not (root / "shared/.draining").exists()


def test_release_rolls_back_exact_previous_configuration(host, monkeypatch):
    root, config, units = host
    previous = "b" * 40
    (config / "release.env").write_text(f"RELEASE={previous}\n")

    def check(commit, port=8795):
        if commit == COMMIT and port == 8795:
            raise RuntimeError("broken release")

    monkeypatch.setattr(release, "wait_health", check)
    with pytest.raises(RuntimeError):
        release.main(COMMIT, DIGEST)
    assert (config / "release.env").read_text() == f"RELEASE={previous}\n"
    assert (units / "lawdocs.service").read_text() == "old service"
    assert not (root / "shared/.draining").exists()


def test_release_rejects_bad_artifacts_and_active_work(host, monkeypatch):
    root, config, units = host
    for commit, digest in [("bad", DIGEST), (COMMIT, "b" * 64)]:
        with pytest.raises(ValueError):
            release.main(commit, digest)
    target = root / "incoming" / f"{COMMIT}.tar.gz"
    target.unlink()
    target.symlink_to(config / "site")
    with pytest.raises(ValueError):
        release.main(COMMIT, DIGEST)
    target.unlink()
    target.write_bytes(b"image")
    p = root / "shared/crash" / ("c" * 32)
    p.mkdir()
    (p / "batch.json").write_text('{"status":"extracting"}')
    monkeypatch.setattr(release.time, "monotonic", Mock(side_effect=[0, 901]))
    with pytest.raises(RuntimeError, match="drain"):
        release.main(COMMIT, DIGEST)
    assert (units / "lawdocs.service").read_text() == "old service"


def test_health_and_smoke_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        release.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b'{"release":"test"}')
    )
    assert release.health()["release"] == "test"
    monkeypatch.setattr(release.time, "sleep", lambda n: None)
    release.wait_health("test")
    monkeypatch.setattr(release, "health", Mock(side_effect=OSError("offline")))
    with pytest.raises(RuntimeError):
        release.wait_health("test")
    for k in ("crash", "plea"):
        (tmp_path / k / ("d" * 32)).mkdir(parents=True)
    report = {"result": "passed", "synthetic_jobs": [["crash", "d" * 32], ["plea", "d" * 32]]}
    monkeypatch.setattr(release, "run", lambda *a, **kw: NS(stdout=json.dumps(report)))
    release.smoke(COMMIT, 8795, tmp_path)
    assert not (tmp_path / "crash" / ("d" * 32)).exists()
    report["synthetic_jobs"] = [["crash", "../outside"]]
    with pytest.raises(ValueError):
        release.smoke(COMMIT, 8795, tmp_path)
