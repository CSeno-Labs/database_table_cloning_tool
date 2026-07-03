from pathlib import Path

from syncdb.cli import main
from syncdb.clients import ClientSource, DumpClient


def test_client_install_uses_default_package_when_no_archive_url(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    installed = []
    statuses = []

    class FakeStatus:
        def __init__(self, message, spinner=None):
            statuses.append((message, spinner))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakePackage:
        file_name = "mariadb-11.4.8-winx64.zip"
        os_name = "Windows"
        cpu = "x86_64"
        sha256 = "abc"

    def fake_install(paths, archive_url=None, sha256=None):
        installed.append((archive_url, sha256))
        dump = tmp_path / "mariadb-dump.exe"
        mysql = tmp_path / "mariadb.exe"
        dump.write_text("")
        mysql.write_text("")
        return DumpClient(ClientSource.MANAGED, "mariadb", dump, mysql)

    monkeypatch.setattr("syncdb.cli.resolve_default_package", lambda: FakePackage())
    monkeypatch.setattr("syncdb.cli.install_managed_client", fake_install)
    monkeypatch.setattr("syncdb.cli.console.status", FakeStatus)

    code = main(["--config", str(config), "client", "install", "--yes"])

    captured = capsys.readouterr()
    assert code == 0
    assert installed == [(None, None)]
    assert statuses == [("Baixando e instalando cliente MariaDB gerenciado...", "dots")]
    assert "mariadb-11.4.8-winx64.zip" in captured.out
    assert "Cliente gerenciado instalado" in captured.out


def test_client_update_uses_default_install_flow(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    installed = []

    class FakePackage:
        file_name = "mariadb-11.4.8-winx64.zip"
        os_name = "Windows"
        cpu = "x86_64"
        sha256 = "abc"

    def fake_install(paths, archive_url=None, sha256=None):
        installed.append((archive_url, sha256))
        dump = tmp_path / "mariadb-dump"
        mysql = tmp_path / "mariadb"
        dump.write_text("")
        mysql.write_text("")
        return DumpClient(ClientSource.MANAGED, "mariadb", dump, mysql)

    monkeypatch.setattr("syncdb.cli.resolve_default_package", lambda: FakePackage())
    monkeypatch.setattr("syncdb.cli.install_managed_client", fake_install)

    code = main(["--config", str(config), "client", "update", "--yes"])

    assert code == 0
    assert installed == [(None, None)]


def test_client_install_accepts_custom_archive_url(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    installed = []

    def fake_install(paths, archive_url=None, sha256=None):
        installed.append((archive_url, sha256))
        dump = tmp_path / "mariadb-dump"
        mysql = tmp_path / "mariadb"
        dump.write_text("")
        mysql.write_text("")
        return DumpClient(ClientSource.MANAGED, "mariadb", dump, mysql)

    monkeypatch.setattr("syncdb.cli.install_managed_client", fake_install)

    code = main([
        "--config",
        str(config),
        "client",
        "install",
        "--archive-url",
        "https://example/client.zip",
        "--sha256",
        "abc",
        "--yes",
    ])

    assert code == 0
    assert installed == [("https://example/client.zip", "abc")]
