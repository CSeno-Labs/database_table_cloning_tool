import json
import threading
import time
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

from syncdb.paths import AppPaths
from syncdb.update_check import check_for_update, fetch_latest_version, is_editable_install


def test_check_for_update_uses_fresh_cached_version_without_network(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    cache = paths.cache_dir / "update-check.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"checked_at": time.time(), "latest_version": "3.0.3"}), encoding="utf-8")
    calls = []

    latest = check_for_update(
        paths,
        "3.0.2",
        fetch_version=lambda: calls.append("fetch") or "3.0.4",
        editable_install=False,
    )

    assert latest == "3.0.3"
    assert calls == []


def test_check_for_update_fetches_and_caches_newer_version(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)

    latest = check_for_update(
        paths,
        "3.0.2",
        fetch_version=lambda: "3.0.3",
        editable_install=False,
        wait_seconds=1,
    )

    cache = json.loads((paths.cache_dir / "update-check.json").read_text(encoding="utf-8"))
    assert latest == "3.0.3"
    assert cache["latest_version"] == "3.0.3"
    assert cache["checked_at"] > 0


def test_check_for_update_does_not_retry_a_fresh_failed_check(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    attempts = []

    def fail_fetch():
        attempts.append(1)
        raise OSError("offline")

    assert check_for_update(paths, "3.0.2", fetch_version=fail_fetch, editable_install=False, wait_seconds=1) is None
    assert check_for_update(paths, "3.0.2", fetch_version=fail_fetch, editable_install=False, wait_seconds=1) is None
    assert attempts == [1]


def test_check_for_update_does_not_wait_for_a_slow_network_response(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_fetch():
        started.set()
        release.wait(0.5)
        finished.set()
        raise OSError("offline")

    result = check_for_update(
        paths,
        "3.0.2",
        fetch_version=slow_fetch,
        editable_install=False,
        wait_seconds=0.01,
    )

    assert result is None
    assert started.wait(0.2)
    assert not release.is_set()
    release.set()
    assert finished.wait(0.2)


def test_check_for_update_skips_editable_install(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    calls = []

    result = check_for_update(
        paths,
        "3.0.2",
        fetch_version=lambda: calls.append("fetch") or "3.0.3",
        editable_install=True,
    )

    assert result is None
    assert calls == []
    assert not (paths.cache_dir / "update-check.json").exists()


def test_check_for_update_only_returns_a_newer_version(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    cache = paths.cache_dir / "update-check.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"checked_at": time.time(), "latest_version": "3.0.2"}), encoding="utf-8")

    assert check_for_update(paths, "3.0.3", editable_install=False) is None


def test_check_for_update_ignores_corrupt_cache_and_offline_error(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    cache = paths.cache_dir / "update-check.json"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"\xff\xfe")

    assert check_for_update(
        paths,
        "3.0.2",
        fetch_version=lambda: (_ for _ in ()).throw(OSError("offline")),
        editable_install=False,
        wait_seconds=1,
    ) is None


def test_fetch_latest_version_extracts_version_from_remote_module(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b'__version__ = "3.1.0"\n'

    seen = []
    monkeypatch.setattr("syncdb.update_check.urlopen", lambda request, timeout: seen.append((request, timeout)) or Response())

    assert fetch_latest_version() == "3.1.0"
    assert seen[0][1] == 3.0


def test_is_editable_install_uses_package_direct_url_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("syncdb.update_check.__file__", str(tmp_path / "site-packages" / "syncdb" / "update_check.py"))
    distribution = SimpleNamespace(read_text=lambda _name: '{"dir_info":{"editable":true}}')
    monkeypatch.setattr("syncdb.update_check.importlib.metadata.distribution", lambda _name: distribution)

    assert is_editable_install() is True


def test_is_editable_install_skips_a_repository_checkout(monkeypatch, tmp_path: Path):
    root = tmp_path / "checkout"
    package_dir = root / "src" / "syncdb"
    package_dir.mkdir(parents=True)
    (root / ".git").touch()
    monkeypatch.setattr("syncdb.update_check.__file__", str(package_dir / "update_check.py"))

    def no_distribution(_name):
        raise PackageNotFoundError("not installed")

    monkeypatch.setattr("syncdb.update_check.importlib.metadata.distribution", no_distribution)

    assert is_editable_install() is True
