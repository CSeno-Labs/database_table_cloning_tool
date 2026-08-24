import argparse

from syncdb.cli import cmd_schema, render_schema_plan_sql_file
from syncdb.paths import AppPaths
from syncdb.schema import SchemaSnapshot, build_schema_plan, compare_schema, inspect_schema


def snapshot(table, *, columns=(), indexes=(), foreign_keys=(), options=()):
    return SchemaSnapshot(
        table=table,
        exists=True,
        columns=tuple(columns),
        indexes=tuple(indexes),
        foreign_keys=tuple(foreign_keys),
        table_options=tuple(options),
    )


def test_compare_schema_reports_source_missing_target_extra_and_divergent_columns():
    source = snapshot(
        "aluno",
        columns=(
            ("id", "int", "NO", None, "auto_increment", None, 1),
            ("nome", "varchar(150)", "NO", None, "", "utf8mb4_unicode_ci", 2),
            ("idescola", "int", "YES", None, "", None, 3),
        ),
    )
    target = snapshot(
        "aluno",
        columns=(
            ("id", "int", "NO", None, "auto_increment", None, 1),
            ("nome", "varchar(80)", "YES", None, "", "utf8mb4_unicode_ci", 2),
            ("campo_dev", "text", "YES", None, "", "utf8mb4_unicode_ci", 3),
        ),
    )

    diff = compare_schema(source, target)

    assert diff.missing_columns == ("idescola",)
    assert diff.extra_columns == ("campo_dev",)
    assert diff.changed_columns == ("nome",)


def test_compare_schema_reports_indexes_foreign_keys_and_table_options():
    source = snapshot(
        "aluno",
        indexes=(("PRIMARY", True, ("id",)), ("idx_escola", False, ("idescola",))),
        foreign_keys=(("fk_aluno_escola", ("idescola",), "escola", ("id",), "RESTRICT", "CASCADE"),),
        options=(("engine", "InnoDB"), ("table_collation", "utf8mb4_unicode_ci")),
    )
    target = snapshot(
        "aluno",
        indexes=(("PRIMARY", True, ("id",)), ("idx_local", False, ("campo_dev",))),
        foreign_keys=(),
        options=(("engine", "InnoDB"), ("table_collation", "latin1_swedish_ci")),
    )

    diff = compare_schema(source, target)

    assert diff.missing_indexes == ("idx_escola",)
    assert diff.extra_indexes == ("idx_local",)
    assert diff.missing_foreign_keys == ("fk_aluno_escola",)
    assert diff.changed_table_options == ("table_collation",)


def test_inspect_schema_reads_columns_indexes_foreign_keys_and_options(monkeypatch):
    calls = []

    class Cursor:
        def execute(self, sql, params=None):
            calls.append((sql, params))
            if "SHOW FULL COLUMNS" in sql:
                self.rows = [{"Field": "id", "Type": "int", "Null": "NO", "Default": None, "Extra": "auto_increment", "Collation": None, "Ordinal": 1}]
            elif "SHOW INDEX" in sql:
                self.rows = [{"Key_name": "PRIMARY", "Non_unique": 0, "Column_name": "id", "Seq_in_index": 1}]
            elif "SHOW CREATE TABLE" in sql:
                self.rows = [{"Create Table": "CREATE TABLE `aluno` (`idescola` int, CONSTRAINT `fk_aluno_escola` FOREIGN KEY (`idescola`) REFERENCES `escola` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT)"}]
            else:
                self.rows = [{"ENGINE": "InnoDB", "TABLE_COLLATION": "utf8mb4_unicode_ci"}]

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def close(self):
            pass

    class Connection:
        def cursor(self, dictionary=False):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr("syncdb.schema.get_connection", lambda config: Connection())

    result = inspect_schema({"database": "db"}, "aluno")

    assert result.exists is True
    assert result.columns[0][0] == "id"
    assert result.indexes == (("PRIMARY", True, ("id",)),)
    assert result.foreign_keys[0][0] == "fk_aluno_escola"
    assert result.table_options == (("engine", "InnoDB"), ("table_collation", "utf8mb4_unicode_ci"))
    assert [name for name, _ in result.timings] == ["connect", "columns", "indexes", "foreign_keys", "table_options", "total"]
    assert len(calls) == 4


def test_schema_diff_command_prints_grouped_differences(monkeypatch, tmp_path, capsys):
    source = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1), ("idescola", "int", "YES", None, "", None, 2)))
    target = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1), ("campo_dev", "text", "YES", None, "", None, 2)))
    config = {
        "profiles": {
            "prod": {"host": "prod", "database": "db", "allow_as_origin": True},
            "local": {"host": "local", "database": "db", "allow_as_destination": True},
        },
        "defaults": {"origin": "prod", "destination": "local"},
    }
    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: config)
    monkeypatch.setattr("syncdb.cli.inspect_schema_pair", lambda origin, destination, table: (source, target))

    paths = AppPaths.from_base(tmp_path)
    code = cmd_schema(paths, argparse.Namespace(schema_command="diff", tables=["aluno"], file=None, origin="prod", destination="local", verbose=False))

    assert code == 0
    shown = capsys.readouterr().out
    assert "Colunas ausentes no destino: idescola" in shown
    assert "Extras no destino: campo_dev" in shown
    assert "Tempos de leitura" not in shown


def test_schema_diff_verbose_prints_timing_breakdown(monkeypatch, tmp_path, capsys):
    source = SchemaSnapshot(table="aluno", exists=True, timings=(("connect", 0.1), ("total", 0.2)))
    target = SchemaSnapshot(table="aluno", exists=True, timings=(("connect", 0.3), ("total", 0.4)))
    config = {
        "profiles": {
            "prod": {"host": "prod", "database": "db", "allow_as_origin": True},
            "local": {"host": "local", "database": "db", "allow_as_destination": True},
        },
        "defaults": {"origin": "prod", "destination": "local"},
    }
    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: config)
    monkeypatch.setattr("syncdb.cli.inspect_schema_pair", lambda origin, destination, table: (source, target))

    assert cmd_schema(AppPaths.from_base(tmp_path), argparse.Namespace(schema_command="diff", tables=["aluno"], file=None, origin="prod", destination="local", verbose=True)) == 0

    assert "Tempos de leitura" in capsys.readouterr().out


def test_schema_copy_command_shows_read_only_plan(monkeypatch, tmp_path, capsys):
    source = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1), ("novo", "int", "YES", None, "", None, 2)))
    target = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1), ("campo_dev", "text", "YES", None, "", None, 2)))
    config = {
        "profiles": {
            "prod": {"host": "prod", "database": "db", "allow_as_origin": True},
            "local": {"host": "local", "database": "db", "allow_as_destination": True},
        },
        "defaults": {"origin": "prod", "destination": "local"},
    }
    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: config)
    monkeypatch.setattr("syncdb.cli.inspect_schema_pair", lambda origin, destination, table: (source, target))

    code = cmd_schema(AppPaths.from_base(tmp_path), argparse.Namespace(schema_command="plan", plan_action="copy", tables=["aluno"], file=None, origin="prod", destination="local", yes=False))

    assert code == 0
    shown = capsys.readouterr().out
    assert "Plano de estrutura" in shown
    assert "+ coluna novo" in shown
    assert "- coluna campo_dev" in shown
    assert "Nenhuma alteração foi feita" in shown


def test_schema_plan_sql_flags_control_visual_and_sql_output(monkeypatch, tmp_path, capsys):
    source = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1), ("novo", "int", "YES", None, "", None, 2), ("outro", "int", "YES", None, "", None, 3)))
    target = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1),))
    config = {
        "profiles": {"prod": {"host": "prod", "database": "db", "allow_as_origin": True}, "local": {"host": "local", "database": "db", "allow_as_destination": True}},
        "defaults": {"origin": "prod", "destination": "local"},
    }
    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: config)
    monkeypatch.setattr("syncdb.cli.inspect_schema_pair", lambda origin, destination, table: (source, target))
    base = dict(schema_command="plan", plan_action="update", tables=["aluno"], file=None, origin="prod", destination="local")

    assert cmd_schema(AppPaths.from_base(tmp_path), argparse.Namespace(**base, sql=False, no_sql=False, sql_only=False)) == 0
    assert "ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;" in capsys.readouterr().out

    assert cmd_schema(AppPaths.from_base(tmp_path), argparse.Namespace(**base, sql=False, no_sql=True, sql_only=False)) == 0
    assert "ALTER TABLE" not in capsys.readouterr().out

    assert cmd_schema(AppPaths.from_base(tmp_path), argparse.Namespace(**base, sql=True, no_sql=True, sql_only=False)) == 0
    shown = capsys.readouterr().out
    assert "Plano de estrutura" in shown
    assert "SQL FINAL" in shown
    assert "ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;" in shown
    assert "SQL FINAL\nALTER TABLE" in shown
    assert ";\n\nALTER TABLE" not in shown

    assert cmd_schema(AppPaths.from_base(tmp_path), argparse.Namespace(**base, sql=False, no_sql=False, sql_only=True)) == 0
    shown = capsys.readouterr().out
    assert "ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;" in shown
    assert "Plano de estrutura" not in shown


def test_saved_schema_plan_is_executable_and_documents_sql_modes():
    source = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1), ("novo", "int", "YES", None, "", None, 2)))
    target = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1),))
    plan = build_schema_plan(compare_schema(source, target), action="update", source=source, target=target)

    default = render_schema_plan_sql_file([plan], origin="prod", destination="local")
    assert "-- Plano de estrutura: aluno (update)" in default
    assert "--     ADICIONAR (1)" in default
    assert "              ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;\n\n" in default
    assert "ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;" in default

    final = render_schema_plan_sql_file([plan], origin="prod", destination="local", include_final_sql=True)
    assert "--               SQL: ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;\n\n" in final
    assert "-- SQL FINAL" in final
    assert final.count("ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;") == 2

    no_sql = render_schema_plan_sql_file([plan], origin="prod", destination="local", show_item_sql=False)
    assert "-- SQL FINAL" in no_sql
    assert no_sql.count("ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;") == 1

    sql_only = render_schema_plan_sql_file([plan], origin="prod", destination="local", sql_only=True)
    assert sql_only == "ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;\n"


def test_schema_plan_save_writes_documented_sql_file(monkeypatch, tmp_path, capsys):
    source = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1), ("novo", "int", "YES", None, "", None, 2)))
    target = snapshot("aluno", columns=(("id", "int", "NO", None, "", None, 1),))
    config = {"profiles": {"prod": {"host": "prod", "database": "db", "allow_as_origin": True}, "local": {"host": "local", "database": "db", "allow_as_destination": True}}, "defaults": {"origin": "prod", "destination": "local"}}
    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: config)
    monkeypatch.setattr("syncdb.cli.inspect_schema_pair", lambda origin, destination, table: (source, target))
    output = tmp_path / "plano.sql"
    args = argparse.Namespace(schema_command="plan", plan_action="update", tables=["aluno"], file=None, origin="prod", destination="local", sql=False, no_sql=False, sql_only=False, save=str(output))

    assert cmd_schema(AppPaths.from_base(tmp_path), args) == 0
    shown = capsys.readouterr().out
    assert "Plano salvo:" in shown
    assert "Plano de estrutura" not in shown
    content = output.read_text(encoding="utf-8")
    assert "-- Plano de estrutura: aluno (update)" in content
    assert "ALTER TABLE `aluno` ADD COLUMN `novo` INT NULL AFTER `id`;" in content
