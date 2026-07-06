from pathlib import Path

from syncdb.clients import ClientSource, DumpClient
from syncdb.engine import build_dump_command, build_import_command, delete_existing_rows


def test_mariadb_dump_command_disables_server_cert_verification_by_default(tmp_path: Path):
    defaults = tmp_path / "client.cnf"
    client = DumpClient(ClientSource.MANAGED, "mariadb", tmp_path / "mariadb-dump.exe", tmp_path / "mariadb.exe")

    command = build_dump_command(client, defaults, database="db", table="periodo", include_create=False)

    assert "--ssl-verify-server-cert=0" in command


def test_mysql_dump_command_does_not_get_mariadb_specific_ssl_flag(tmp_path: Path):
    defaults = tmp_path / "client.cnf"
    client = DumpClient(ClientSource.SYSTEM, "mysql", tmp_path / "mysqldump.exe", tmp_path / "mysql.exe")

    command = build_dump_command(client, defaults, database="db", table="periodo", include_create=False)

    assert "--ssl-verify-server-cert=0" not in command


def test_mariadb_import_command_disables_ssl_for_local_destination_by_default(tmp_path: Path):
    defaults = tmp_path / "client.cnf"
    client = DumpClient(ClientSource.MANAGED, "mariadb", tmp_path / "mariadb-dump.exe", tmp_path / "mariadb.exe")

    command = build_import_command(client, defaults, database="db")

    assert "--ssl=0" in command


def test_mysql_import_command_does_not_get_mariadb_specific_ssl_flag(tmp_path: Path):
    defaults = tmp_path / "client.cnf"
    client = DumpClient(ClientSource.SYSTEM, "mysql", tmp_path / "mysqldump.exe", tmp_path / "mysql.exe")

    command = build_import_command(client, defaults, database="db")

    assert "--ssl=0" not in command


def test_delete_existing_rows_disables_foreign_keys_and_commits(monkeypatch):
    executed = []

    class FakeCursor:
        def execute(self, sql):
            executed.append(sql)

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            executed.append("COMMIT")

        def close(self):
            executed.append("CLOSE")

    monkeypatch.setattr("syncdb.engine.get_connection", lambda config: FakeConnection())

    delete_existing_rows({"database": "local"}, "periodo")

    assert executed == [
        "SET FOREIGN_KEY_CHECKS=0",
        "DELETE FROM `periodo`",
        "COMMIT",
        "CLOSE",
    ]


def test_delete_existing_rows_handles_schema_table_name(monkeypatch):
    executed = []

    class FakeCursor:
        def execute(self, sql):
            executed.append(sql)

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("syncdb.engine.get_connection", lambda config: FakeConnection())

    delete_existing_rows({"database": "local"}, "escola.periodo")

    assert "DELETE FROM `escola`.`periodo`" in executed
