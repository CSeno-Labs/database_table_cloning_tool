import os
from pathlib import Path

from syncdb.clients import ClientSource, find_managed_client, find_system_client, resolve_client
from syncdb.paths import AppPaths


def make_executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_find_managed_client_prefers_mariadb_pair(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    bin_dir = paths.managed_client_dir / "mariadb" / "current" / "bin"
    bin_dir.mkdir(parents=True)
    dump = make_executable(bin_dir / "mariadb-dump")
    mysql = make_executable(bin_dir / "mariadb")

    client = find_managed_client(paths)

    assert client is not None
    assert client.source == ClientSource.MANAGED
    assert client.dump == dump
    assert client.mysql == mysql
    assert client.vendor == "mariadb"


def test_find_system_client_uses_path_pair(tmp_path: Path, monkeypatch):
    make_executable(tmp_path / "mysqldump")
    make_executable(tmp_path / "mysql")
    monkeypatch.setenv("PATH", str(tmp_path))

    client = find_system_client()

    assert client is not None
    assert client.source == ClientSource.SYSTEM
    assert client.vendor == "mysql"
    assert client.dump.name == "mysqldump"
    assert client.mysql.name == "mysql"


def test_resolve_client_auto_falls_back_to_python_when_no_dump_client(tmp_path: Path, monkeypatch):
    paths = AppPaths.from_base(tmp_path)
    monkeypatch.setenv("PATH", os.devnull)

    resolved = resolve_client(paths, mode="auto")

    assert resolved.kind == "python"
    assert resolved.client is None
    assert "Nenhum cliente dump" in resolved.reason
