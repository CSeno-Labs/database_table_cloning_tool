from pathlib import Path

from syncdb.clients import ClientSource, DumpClient
from syncdb.engine import (
    TableResult,
    backup_existing_table,
    build_dump_command,
    build_import_command,
    build_key_predicate,
    delete_existing_rows,
    drop_table,
    normalize_where_clause,
    preflight_advanced_sync,
    run_table_backup,
    validate_where_clause,
)


def test_where_clause_normalization_accepts_with_or_without_where():
    assert normalize_where_clause("ano >= 2026") == "ano >= 2026"
    assert normalize_where_clause("WHERE ano >= 2026") == "ano >= 2026"
    assert normalize_where_clause("  where idescola = 123  ") == "idescola = 123"


def test_where_clause_validation_blocks_dangerous_tokens():
    validate_where_clause("idescola IN (SELECT id FROM escola WHERE idsme = 92)")

    for bad in ["1=1; DROP TABLE aluno", "id=1 -- comentario", "id=1 /* x */", "UPDATE aluno SET nome='x'"]:
        try:
            validate_where_clause(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"WHERE perigoso deveria falhar: {bad}")


def test_build_key_predicate_supports_simple_and_composite_primary_keys():
    sql, params = build_key_predicate(["id"], [(1,), (2,)])
    assert sql == "(`id` = %s OR `id` = %s)"
    assert params == [1, 2]

    sql, params = build_key_predicate(["idescola", "idaluno"], [(10, 1), (10, 2)])
    assert sql == "((`idescola` = %s AND `idaluno` = %s) OR (`idescola` = %s AND `idaluno` = %s))"
    assert params == [10, 1, 10, 2]

def test_preflight_insert_missing_counts_new_rows_on_destination(monkeypatch):
    monkeypatch.setattr("syncdb.engine.get_primary_key", lambda config, table: ["id"])
    monkeypatch.setattr("syncdb.engine.validate_where_for_table", lambda config, table, primary_key, where: 4)
    monkeypatch.setattr("syncdb.engine.select_keys", lambda config, table, primary_key, where: [(1,), (2,), (3,), (4,)])
    monkeypatch.setattr("syncdb.engine.table_exists", lambda config, table: True)
    monkeypatch.setattr("syncdb.engine.select_existing_keys", lambda config, table, primary_key, keys, batch_size: {(1,), (3,)})

    results = preflight_advanced_sync({"origem": {"database": "prod"}, "destino": {"database": "local"}}, ["turma2026"], insert_missing=True)

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].origin_matched_rows == 4
    assert results[0].destination_matched_rows == 2
    assert results[0].planned_insert_rows == 2
    assert results[0].skipped_existing_rows == 2


def test_preflight_where_counts_rows_that_would_be_replaced_on_destination(monkeypatch):
    monkeypatch.setattr("syncdb.engine.get_primary_key", lambda config, table: ["id"])
    monkeypatch.setattr("syncdb.engine.validate_where_for_table", lambda config, table, primary_key, where: 3)
    monkeypatch.setattr("syncdb.engine.select_keys", lambda config, table, primary_key, where: [(10,), (11,), (12,)])
    monkeypatch.setattr("syncdb.engine.table_exists", lambda config, table: True)
    monkeypatch.setattr("syncdb.engine.select_existing_keys", lambda config, table, primary_key, keys, batch_size: {(10,), (12,)})

    results = preflight_advanced_sync({"origem": {"database": "prod"}, "destino": {"database": "local"}}, ["turma2026"], where_clause="idescola = 1111")

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].origin_matched_rows == 3
    assert results[0].destination_matched_rows == 2
    assert results[0].planned_insert_rows == 3


def test_table_result_has_stage_and_backup_metadata():
    result = TableResult(table="periodo", ok=False, engine="dump", stage="import_dest", message="erro", backup_table="periodo_syncdb_backup_1")

    assert result.stage == "import_dest"
    assert result.backup_table == "periodo_syncdb_backup_1"


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


def test_backup_existing_table_creates_timestamped_copy(monkeypatch):
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

    backup_name = backup_existing_table({"database": "local"}, "periodo", suffix="20260706_120000")

    assert backup_name == "periodo_syncdb_backup_20260706_120000"
    assert "DROP TABLE IF EXISTS `periodo_syncdb_backup_20260706_120000`" in executed
    assert "CREATE TABLE `periodo_syncdb_backup_20260706_120000` AS SELECT * FROM `periodo`" in executed
    assert "COMMIT" in executed


def test_drop_table_drops_backup_table(monkeypatch):
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

    drop_table({"database": "local"}, "periodo_syncdb_backup_1")

    assert executed == ["DROP TABLE IF EXISTS `periodo_syncdb_backup_1`", "COMMIT", "CLOSE"]


def test_run_table_backup_uses_explicit_backup_name(monkeypatch):
    calls = []
    monkeypatch.setattr("syncdb.engine.backup_existing_table", lambda config, table, backup_name=None: calls.append((table, backup_name)) or backup_name)

    result = run_table_backup({"database": "local"}, "periodo", "periodo_bkp")

    assert result.ok is True
    assert result.backup_table == "periodo_bkp"
    assert calls == [("periodo", "periodo_bkp")]


def test_run_dump_sync_dumps_source_before_cleaning_destination(monkeypatch, tmp_path: Path):
    import subprocess

    from syncdb.engine import run_dump_sync
    from syncdb.paths import AppPaths

    client = DumpClient(ClientSource.MANAGED, "mariadb", tmp_path / "mariadb-dump", tmp_path / "mariadb")
    paths = AppPaths.from_base(tmp_path / "app")
    events = []

    monkeypatch.setattr("syncdb.engine.table_exists", lambda *args: True)
    monkeypatch.setattr("syncdb.engine._defaults_file", lambda config, tmpdir: tmpdir / f"{config['database']}.cnf")
    monkeypatch.setattr("syncdb.engine.build_dump_command", lambda *args, **kwargs: ["dump"])
    monkeypatch.setattr("syncdb.engine.build_import_command", lambda *args, **kwargs: ["import"])
    monkeypatch.setattr("syncdb.engine.delete_existing_rows", lambda *args: events.append("cleanup_destination"))
    monkeypatch.setattr("syncdb.engine.row_count", lambda *args: 1)

    def fake_run(command, **kwargs):
        events.append(command[0])
        if command[0] == "dump":
            kwargs["stdout"].write("CREATE TABLE `registros` (...);\n")
        return subprocess.CompletedProcess(command, 0, stderr="")

    monkeypatch.setattr("syncdb.engine.subprocess.run", fake_run)

    result = run_dump_sync(
        {
            "origem": {"database": "source"},
            "destino": {"database": "target"},
            "sync": {"truncate_before_insert": True, "backup_before_replace": False},
        },
        "registros",
        client,
        paths,
    )

    assert result.ok is True
    assert events == ["dump", "cleanup_destination", "import"]


def test_run_dump_sync_does_not_clean_destination_when_source_dump_fails(monkeypatch, tmp_path: Path):
    import subprocess

    from syncdb.engine import run_dump_sync
    from syncdb.paths import AppPaths

    client = DumpClient(ClientSource.MANAGED, "mariadb", tmp_path / "mariadb-dump", tmp_path / "mariadb")
    paths = AppPaths.from_base(tmp_path / "app")
    cleaned = []

    monkeypatch.setattr("syncdb.engine.table_exists", lambda *args: True)
    monkeypatch.setattr("syncdb.engine._defaults_file", lambda config, tmpdir: tmpdir / f"{config['database']}.cnf")
    monkeypatch.setattr("syncdb.engine.build_dump_command", lambda *args, **kwargs: ["dump"])
    monkeypatch.setattr("syncdb.engine.delete_existing_rows", lambda *args: cleaned.append(True))
    monkeypatch.setattr(
        "syncdb.engine.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stderr="2002 connection timeout"),
    )

    result = run_dump_sync(
        {
            "origem": {"database": "source"},
            "destino": {"database": "target"},
            "sync": {"truncate_before_insert": True},
        },
        "registros",
        client,
        paths,
    )

    assert result.ok is False
    assert result.stage == "dump_source"
    assert cleaned == []


def test_run_dump_sync_returns_compact_import_error_and_preserves_full_stderr(monkeypatch, tmp_path: Path):
    import subprocess

    from syncdb.engine import run_dump_sync
    from syncdb.paths import AppPaths

    client = DumpClient(ClientSource.MANAGED, "mariadb", tmp_path / "mariadb-dump", tmp_path / "mariadb")
    paths = AppPaths.from_base(tmp_path / "app")
    paths.ensure_dirs()
    sql = "INSERT INTO t VALUES\n" + ",\n".join(f"({i})" for i in range(2000))
    full_stderr = sql + "\nERROR 1062 (23000) at line 65619: Duplicate entry '688146' for key 'PRIMARY'"
    calls = iter([subprocess.CompletedProcess([], 0, stderr=""), subprocess.CompletedProcess([], 1, stderr=full_stderr)])

    monkeypatch.setattr("syncdb.engine.table_exists", lambda *args: True)
    monkeypatch.setattr("syncdb.engine._defaults_file", lambda config, tmpdir: tmpdir / f"{config['database']}.cnf")
    monkeypatch.setattr("syncdb.engine.build_dump_command", lambda *args, **kwargs: ["dump"])
    monkeypatch.setattr("syncdb.engine.build_import_command", lambda *args, **kwargs: ["import"])
    monkeypatch.setattr("syncdb.engine.subprocess.run", lambda *args, **kwargs: next(calls))

    result = run_dump_sync(
        {"origem": {"database": "source"}, "destino": {"database": "target"}, "sync": {"truncate_before_insert": False}},
        "registros",
        client,
        paths,
    )

    assert result.ok is False
    assert result.stage == "import_dest"
    assert "INSERT INTO" not in result.message
    assert "ERROR 1062 (23000) at line 65619" in result.message
    assert len(result.message) < 200
    assert result.details.endswith("ERROR 1062 (23000) at line 65619: Duplicate entry '688146' for key 'PRIMARY'")
    assert len(result.details) > 10000


def test_summarize_dump_error_extracts_duplicate_key_diagnostic_from_large_sql():
    from syncdb.engine import summarize_dump_error

    sql_payload = "INSERT INTO `frequenciaBioV2_registros` VALUES\n" + ",\n".join(f"({i}, 'registro enorme')" for i in range(5000))
    stderr = f"{sql_payload}\nERROR 1062 (23000) at line 65619: Duplicate entry '688146' for key 'PRIMARY'"

    summary = summarize_dump_error(stderr)

    assert summary == "ERROR 1062 (23000) at line 65619: Duplicate entry '688146' for key 'PRIMARY'"
    assert len(summary) < 200


def test_summarize_dump_error_limits_unstructured_stderr():
    from syncdb.engine import summarize_dump_error

    summary = summarize_dump_error("x" * 5000)

    assert len(summary) <= 503
    assert summary.endswith("...")
