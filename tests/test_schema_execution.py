from __future__ import annotations

import argparse

import pytest

from syncdb.paths import AppPaths
from syncdb.schema import SchemaAction, SchemaPlan, SchemaPlanOperation, SchemaSnapshot


class FakeCursor:
    def __init__(self, fail_sql: str | None = None):
        self.fail_sql, self.executed, self.closed = fail_sql, [], False

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        if sql == self.fail_sql:
            raise RuntimeError("database rejected statement")

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self.cursor_instance, self.closed = cursor, False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def app_paths(tmp_path):
    return AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "state", tmp_path / "cache")


def execution_plan(action: SchemaAction = SchemaAction.COPY) -> SchemaPlan:
    return SchemaPlan("child", action, (
        SchemaPlanOperation("drop", "column", "obsolete", sql="ALTER TABLE `child` DROP COLUMN `obsolete`;"),
        SchemaPlanOperation("drop", "index", "idx_obsolete", sql="ALTER TABLE `child` DROP INDEX `idx_obsolete`;"),
        SchemaPlanOperation("drop", "foreign_key", "fk_obsolete", sql="ALTER TABLE `child` DROP FOREIGN KEY `fk_obsolete`;"),
        SchemaPlanOperation("modify", "column", "parent_id", sql="ALTER TABLE `child` MODIFY COLUMN `parent_id` INT NOT NULL;"),
        SchemaPlanOperation("add", "index", "idx_parent", sql="ALTER TABLE `child` ADD INDEX `idx_parent` (`parent_id`);"),
        SchemaPlanOperation("add", "foreign_key", "fk_parent", sql="ALTER TABLE `child` ADD CONSTRAINT `fk_parent` FOREIGN KEY (`parent_id`) REFERENCES `parent` (`id`);"),
    ))


def test_execute_missing_table_plan_runs_source_create_table_for_copy_and_update():
    from syncdb.schema import build_schema_plan, compare_schema, execute_schema_plan

    create_sql = "CREATE TABLE `child` (`id` INT NOT NULL) ENGINE=InnoDB"
    source = SchemaSnapshot(table="child", exists=True, create_sql=create_sql)
    target = SchemaSnapshot(table="child", exists=False)

    for action in (SchemaAction.COPY, SchemaAction.UPDATE):
        cursor = FakeCursor()
        report = execute_schema_plan(
            {"connection": FakeConnection(cursor)},
            build_schema_plan(compare_schema(source, target), action, source=source, target=target),
        )
        assert report.ok is True
        assert cursor.executed == [create_sql + ";"]


def test_execute_schema_plan_orders_fk_and_index_drops_before_column_drop():
    from syncdb.schema import execute_schema_plan

    cursor = FakeCursor()
    report = execute_schema_plan({"connection": FakeConnection(cursor)}, execution_plan())

    assert report.ok is True
    assert cursor.executed == [
        "ALTER TABLE `child` DROP FOREIGN KEY `fk_obsolete`;",
        "ALTER TABLE `child` DROP INDEX `idx_obsolete`;",
        "ALTER TABLE `child` MODIFY COLUMN `parent_id` INT NOT NULL;",
        "ALTER TABLE `child` DROP COLUMN `obsolete`;",
        "ALTER TABLE `child` ADD INDEX `idx_parent` (`parent_id`);",
        "ALTER TABLE `child` ADD CONSTRAINT `fk_parent` FOREIGN KEY (`parent_id`) REFERENCES `parent` (`id`);",
    ]
    assert report.applied == tuple(cursor.executed)
    assert report.failed is None


def test_execute_schema_plan_stops_at_first_failed_statement_and_reports_progress():
    from syncdb.schema import execute_schema_plan

    failed = "ALTER TABLE `child` DROP INDEX `idx_obsolete`;"
    cursor = FakeCursor(failed)
    report = execute_schema_plan({"connection": FakeConnection(cursor)}, execution_plan())

    assert report.ok is False
    assert report.applied == ("ALTER TABLE `child` DROP FOREIGN KEY `fk_obsolete`;",)
    assert report.failed == failed
    assert "database rejected statement" in report.error
    assert cursor.executed == ["ALTER TABLE `child` DROP FOREIGN KEY `fk_obsolete`;", failed]


def test_execute_schema_plan_keeps_semicolon_inside_sql_string_literal():
    from syncdb.schema import execute_schema_plan

    cursor = FakeCursor()
    sql = "ALTER TABLE `child` ADD COLUMN `note` VARCHAR(20) DEFAULT 'a;b';"
    report = execute_schema_plan({"connection": FakeConnection(cursor)}, SchemaPlan(
        "child", SchemaAction.COPY, (SchemaPlanOperation("add", "column", "note", sql=sql),),
    ))

    assert report.ok is True
    assert cursor.executed == [sql]


def test_execute_schema_plan_never_executes_update_preserve_operations():
    from syncdb.schema import execute_schema_plan

    cursor = FakeCursor()
    plan = SchemaPlan("child", SchemaAction.UPDATE, (
        SchemaPlanOperation("preserve", "column", "destination_only", sql="ALTER TABLE `child` DROP COLUMN `destination_only`;"),
    ))
    report = execute_schema_plan({"connection": FakeConnection(cursor)}, plan)

    assert report.ok is True
    assert cursor.executed == []


def test_schema_copy_requires_yes_without_tty_and_does_not_inspect_or_execute(monkeypatch, tmp_path, capsys):
    from syncdb import cli

    args = argparse.Namespace(schema_command="copy", tables=["child"], file=None, origin=None, destination=None, yes=False)
    monkeypatch.setattr(cli, "load_config", lambda paths: {})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli, "inspect_schema_pair", lambda *args: (_ for _ in ()).throw(AssertionError("must not inspect")))

    assert cli.cmd_schema(app_paths(tmp_path), args) == 2
    assert "--yes" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["copy", "update"])
def test_schema_command_applies_create_ddl_for_missing_destination(monkeypatch, tmp_path, capsys, command):
    from syncdb import cli

    create_sql = "CREATE TABLE `child` (`id` INT NOT NULL) ENGINE=InnoDB"
    source = SchemaSnapshot(table="child", exists=True, create_sql=create_sql)
    target = SchemaSnapshot(table="child", exists=False)
    args = argparse.Namespace(schema_command=command, tables=["child"], file=None, origin=None, destination=None, yes=True)
    executed = []
    monkeypatch.setattr(cli, "load_config", lambda paths: {"language": "pt-BR"})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli, "inspect_schema_pair", lambda *args: (source, target))
    monkeypatch.setattr(cli, "execute_schema_plan", lambda destination, plan: executed.append(plan) or type("Report", (), {"ok": True, "applied": (create_sql + ";",), "failed": None, "error": ""})())

    assert cli.cmd_schema(app_paths(tmp_path), args) == 0
    assert len(executed) == 1
    assert executed[0].operations[0].sql == create_sql + ";"
    shown = capsys.readouterr().out
    assert "CREATE TABLE `child`" in shown
    assert "OK child: 1 SQL aplicado(s)." in shown


@pytest.mark.parametrize("command", ["copy", "update"])
def test_schema_command_prints_completion_summary(monkeypatch, tmp_path, capsys, command):
    from syncdb import cli

    source_created = SchemaSnapshot(table="new_table", exists=True, create_sql="CREATE TABLE `new_table` (`id` INT)")
    target_missing = SchemaSnapshot(table="new_table", exists=False)
    source_updated = SchemaSnapshot(table="updated_table", exists=True, columns=(("id", "int", "NO", None, "", None, 1),))
    target_updated = SchemaSnapshot(table="updated_table", exists=True)
    unchanged = SchemaSnapshot(table="unchanged_table", exists=True)
    snapshots = {
        "new_table": (source_created, target_missing),
        "updated_table": (source_updated, target_updated),
        "unchanged_table": (unchanged, unchanged),
    }
    args = argparse.Namespace(schema_command=command, tables=list(snapshots), file=None, origin=None, destination=None, yes=True)
    monkeypatch.setattr(cli, "load_config", lambda paths: {"language": "pt-BR"})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli, "inspect_schema_pair", lambda _source, _target, table: snapshots[table])
    monkeypatch.setattr(
        cli,
        "execute_schema_plan",
        lambda _destination, plan: type("Report", (), {"ok": True, "applied": tuple(op.sql for op in plan.operations if op.sql), "failed": None, "error": ""})(),
    )

    assert cli.cmd_schema(app_paths(tmp_path), args) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "Processamento concluído: 3 tabelas processadas — 1 criada sem dados, 1 atualizada, 1 sem alterações; 0 falhas." in output


def test_schema_command_summarizes_failure_and_unprocessed_tables(monkeypatch, tmp_path, capsys):
    from syncdb import cli

    snapshots = {
        table: (SchemaSnapshot(table=table, exists=True), SchemaSnapshot(table=table, exists=True))
        for table in ("first", "failed", "pending")
    }
    args = argparse.Namespace(schema_command="copy", tables=list(snapshots), file=None, origin=None, destination=None, yes=True)
    calls = []

    def execute(_destination, plan):
        calls.append(plan.table)
        if plan.table == "failed":
            raise RuntimeError("simulated failure")
        return type("Report", (), {"ok": True, "applied": (), "failed": None, "error": ""})()

    monkeypatch.setattr(cli, "load_config", lambda paths: {"language": "pt-BR"})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli, "inspect_schema_pair", lambda _source, _target, table: snapshots[table])
    monkeypatch.setattr(cli, "execute_schema_plan", execute)

    assert cli.cmd_schema(app_paths(tmp_path), args) == 1
    assert calls == ["first", "failed"]
    output = " ".join(capsys.readouterr().out.split())
    assert "Processamento interrompido: 2 de 3 tabelas — 1 sem alterações, 1 falha; 1 não processada." in output


def test_schema_copy_recomputes_displays_and_executes_plan_with_yes(monkeypatch, tmp_path, capsys):
    from syncdb import cli

    args = argparse.Namespace(schema_command="copy", tables=["child"], file=None, origin=None, destination=None, yes=True)
    plan = SchemaPlan("child", SchemaAction.COPY, (SchemaPlanOperation("add", "column", "id", sql="ALTER TABLE `child` ADD COLUMN `id` INT NOT NULL;"),))
    calls = []
    monkeypatch.setattr(cli, "load_config", lambda paths: {})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli, "inspect_schema_pair", lambda *args: (SchemaSnapshot("child", True), SchemaSnapshot("child", True)))
    monkeypatch.setattr(cli, "build_schema_plan", lambda diff, action, **kwargs: calls.append((diff, action, kwargs)) or plan)
    monkeypatch.setattr(cli, "execute_schema_plan", lambda destination, received: calls.append((destination, received)) or type("Report", (), {"ok": True, "applied": (plan.operations[0].sql,), "failed": None, "error": ""})())

    assert cli.cmd_schema(app_paths(tmp_path), args) == 0
    assert len(calls) == 2
    assert "Plano de estrutura: child (copy)" in capsys.readouterr().out


def test_schema_copy_in_tty_accepts_case_insensitive_typed_confirmation(monkeypatch, tmp_path):
    from syncdb import cli

    args = argparse.Namespace(schema_command="copy", tables=["child"], file=None, origin=None, destination=None, yes=False)
    plan = SchemaPlan("child", SchemaAction.COPY, ())
    monkeypatch.setattr(cli, "load_config", lambda paths: {})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "inspect_schema_pair", lambda *args: (SchemaSnapshot("child", True), SchemaSnapshot("child", True)))
    monkeypatch.setattr(cli, "build_schema_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr("builtins.input", lambda prompt: "aplicar")
    monkeypatch.setattr(cli, "execute_schema_plan", lambda *args: type("Report", (), {"ok": True, "applied": (), "failed": None, "error": ""})())

    assert cli.cmd_schema(app_paths(tmp_path), args) == 0


def test_schema_copy_and_update_parser_accept_yes_flag():
    from syncdb.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["schema", "copy", "-t", "child", "--yes"]).yes is True
    assert parser.parse_args(["schema", "update", "-t", "child", "--yes"]).yes is True


def test_schema_recreate_table_parser_accepts_yes_and_keep_backup():
    from syncdb.cli import build_parser

    args = build_parser().parse_args(["schema", "recreate-table", "-t", "child", "--yes", "--keep-backup"])

    assert args.yes is True
    assert args.keep_backup is True


def test_schema_recreate_table_requires_yes_without_tty_before_inspection(monkeypatch, tmp_path, capsys):
    from syncdb import cli

    args = argparse.Namespace(schema_command="recreate-table", tables=["child"], file=None, origin=None, destination=None, yes=False, keep_backup=False)
    monkeypatch.setattr(cli, "load_config", lambda paths: {})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli, "execute_recreate_table", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not execute")))

    assert cli.cmd_schema(app_paths(tmp_path), args) == 2
    assert "--yes" in capsys.readouterr().out


def test_schema_recreate_table_tty_prompts_backup_then_requires_case_insensitive_aplicar(monkeypatch, tmp_path):
    from syncdb import cli

    args = argparse.Namespace(schema_command="recreate-table", tables=["child"], file=None, origin=None, destination=None, yes=False, keep_backup=False)
    inputs = iter(("S", "aplicar"))
    calls = []
    monkeypatch.setattr(cli, "load_config", lambda paths: {})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: calls.append(prompt) or next(inputs))
    monkeypatch.setattr(cli, "execute_recreate_table", lambda *args, **kwargs: calls.append(kwargs) or type("Report", (), {"ok": True, "backup_table": "child_syncdb_backup_20260824_120000", "failed": None, "error": ""})())

    assert cli.cmd_schema(app_paths(tmp_path), args) == 0
    assert calls[0] == "Deseja manter tabela atual como backup? [s/N] "
    assert calls[1] == "Digite APLICAR para recriar a tabela: "
    assert calls[2] == {"keep_backup": True}


def test_schema_recreate_missing_target_reports_creation(monkeypatch, tmp_path, capsys):
    from syncdb import cli

    args = argparse.Namespace(schema_command="recreate-table", tables=["child"], file=None, origin=None, destination=None, yes=True, keep_backup=False)
    monkeypatch.setattr(cli, "load_config", lambda paths: {"language": "pt-BR"})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "prod"}, {"alias": "local"}))
    monkeypatch.setattr(
        cli,
        "execute_recreate_table",
        lambda *args, **kwargs: type("Report", (), {"ok": True, "created": True, "backup_table": None, "failed": None, "error": ""})(),
    )

    assert cli.cmd_schema(app_paths(tmp_path), args) == 0
    assert "criada sem dados" in capsys.readouterr().out


def test_schema_recreate_table_yes_defaults_to_deleting_old_table(monkeypatch, tmp_path):
    from syncdb import cli

    args = argparse.Namespace(schema_command="recreate-table", tables=["child"], file=None, origin=None, destination=None, yes=True, keep_backup=False)
    calls = []
    monkeypatch.setattr(cli, "load_config", lambda paths: {})
    monkeypatch.setattr(cli, "resolve_profile_pair", lambda *args: ({"alias": "source"}, {"alias": "target"}))
    monkeypatch.setattr(cli, "execute_recreate_table", lambda *args, **kwargs: calls.append(kwargs) or type("Report", (), {"ok": True, "backup_table": None, "failed": None, "error": ""})())

    assert cli.cmd_schema(app_paths(tmp_path), args) == 0
    assert calls == [{"keep_backup": False}]
