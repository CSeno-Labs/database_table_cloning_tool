from pathlib import Path

from syncdb.clients import ClientSource, DumpClient
from syncdb.engine import build_dump_command, build_import_command, build_truncate_preamble


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


def test_truncate_preamble_deletes_existing_table_conditionally():
    sql = build_truncate_preamble("periodo")

    assert "SET FOREIGN_KEY_CHECKS=0;" in sql
    assert "information_schema.tables" in sql
    assert "table_name = 'periodo'" in sql
    assert "DELETE FROM `periodo`" in sql
    assert "PREPARE syncdb_stmt" in sql


def test_truncate_preamble_handles_schema_table_name():
    sql = build_truncate_preamble("escola.periodo")

    assert "table_name = 'periodo'" in sql
    assert "DELETE FROM `escola`.`periodo`" in sql
