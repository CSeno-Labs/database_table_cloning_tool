from pathlib import Path

from syncdb.clients import ClientSource, DumpClient
from syncdb.engine import build_dump_command


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
