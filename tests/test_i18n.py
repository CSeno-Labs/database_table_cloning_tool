import json
from argparse import Namespace
from types import SimpleNamespace

import pytest

from rich.console import Console

from syncdb.cli import (
    _manual_schema_operation_options,
    advanced_backup_options,
    advanced_menu_options,
    advanced_mode_options,
    advanced_rows_text,
    cmd_client,
    cmd_doctor,
    confirm,
    cleanup_temporary_backups,
    format_sync_context,
    interactive_language,
    main,
    print_schema_plan,
    set_config_language,
)
from syncdb.engine import TableResult
from syncdb.config import default_config, load_config, resolve_profile_pair
from syncdb.engine import validate_where_clause
from syncdb.i18n import set_language
from syncdb.interactive import MenuOption, menu_renderable
from syncdb.paths import AppPaths
from syncdb.schema import (
    SchemaAction,
    SchemaDiff,
    SchemaPlan,
    SchemaPlanOperation,
    SchemaSnapshot,
    build_schema_plan,
    normalize_schema_action,
)
from syncdb.tables import quote_identifier


def test_english_sync_failure_output_is_fully_localized(monkeypatch, tmp_path, capsys):
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    config = default_config()
    config["language"] = "en"
    paths.config_file.write_text(json.dumps(config), encoding="utf-8")

    result = TableResult(
        table="sample_table",
        ok=False,
        engine="dump",
        stage="import_dest",
        message="Failure during import_dest for sample_table: ERROR 1062 duplicate entry",
        details="full diagnostic",
    )
    monkeypatch.setattr(
        "syncdb.cli.resolve_client",
        lambda *args, **kwargs: SimpleNamespace(kind="dump", reason="managed client available (mariadb).", client=object()),
    )
    monkeypatch.setattr("syncdb.cli.test_connection", lambda *args, **kwargs: (True, "test server"))
    monkeypatch.setattr("syncdb.cli.run_dump_sync", lambda *args: result)
    monkeypatch.setattr("syncdb.cli.write_sync_log", lambda *args, **kwargs: None)

    assert main(["--config", str(paths.config_file), "sync", "-t", "sample_table"]) == 1
    output = capsys.readouterr().out

    for expected in (
        "Flow:", "Engine:", "Synchronizing sample_table", "Summary", "Table", "Status",
        "Stage", "Rows", "FAILED", "Synchronization errors", "Detailed log:",
    ):
        assert expected in output
    for untranslated in (
        "Fluxo:", "Motor:", "Sincronizando", "Resumo", "Tabela", "FALHOU", "Etapa",
        "Linhas", "Erros da sincronização", "Log detalhado:", "Falha em",
    ):
        assert untranslated not in output


def test_english_advanced_sync_failure_output_is_localized_after_summary(monkeypatch, tmp_path, capsys):
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    config = default_config()
    config["language"] = "en"
    paths.config_file.write_text(json.dumps(config), encoding="utf-8")

    from syncdb.engine import TableResult

    preflight = TableResult(
        table="sample_table", ok=True, engine="python/advanced", stage="preflight",
        primary_key=["id"], origin_matched_rows=1, destination_matched_rows=0,
        planned_insert_rows=1,
    )
    failure = TableResult(
        table="sample_table", ok=False, engine="python/advanced", stage="import_dest",
        message="Failure during import_dest for sample_table: ERROR 1062 duplicate entry",
    )
    monkeypatch.setattr("syncdb.cli.preflight_advanced_sync", lambda *args: [preflight])
    monkeypatch.setattr("syncdb.cli.run_python_advanced_sync", lambda *args, **kwargs: failure)
    import syncdb.cli as cli
    events = []
    original_print_sync_errors = cli.print_sync_errors

    def fake_write_sync_log(*args, **kwargs):
        events.append("log")

    def tracked_print_sync_errors(*args, **kwargs):
        events.append("errors")
        return original_print_sync_errors(*args, **kwargs)

    monkeypatch.setattr("syncdb.cli.write_sync_log", fake_write_sync_log)
    monkeypatch.setattr("syncdb.cli.print_sync_errors", tracked_print_sync_errors)

    assert main([
        "--config", str(paths.config_file), "sync", "-t", "sample_table",
        "--insert-missing", "-y",
    ]) == 1
    assert events == ["log", "errors"]
    captured = capsys.readouterr()
    output = captured.out + captured.err

    for expected in (
        "Advanced synchronization preview", "Primary key", "Rows in source",
        "Summary", "Synchronization errors", "Stage: import_dest",
        "Error: ERROR 1062 duplicate entry", "Detailed log:", "FAILED",
    ):
        assert expected in output
    assert output.index("Summary") < output.index("Synchronization errors")
    for untranslated in (
        "Prévia da sincronização", "Sincronizando", "Etapa:", "Erro:",
        "Erros da sincronização", "Log detalhado:",
    ):
        assert untranslated not in output


def test_english_profile_validation_errors_are_localized():
    set_language("en")
    try:
        with pytest.raises(ValueError, match="Source database not found: prod"):
            resolve_profile_pair({"profiles": {}}, "prod", "local")
    finally:
        set_language("pt-BR")


def test_english_where_validation_errors_are_localized():
    set_language("en")
    try:
        with pytest.raises(ValueError, match="WHERE clause contains a disallowed command: DROP"):
            validate_where_clause("name = 1 OR DROP")
    finally:
        set_language("pt-BR")


def test_english_schema_action_error_is_localized():
    set_language("en")
    try:
        with pytest.raises(ValueError, match="Invalid schema action"):
            normalize_schema_action("invalid")
    finally:
        set_language("pt-BR")


def test_english_invalid_table_identifier_error_is_localized():
    set_language("en")
    try:
        with pytest.raises(ValueError, match="Invalid identifier"):
            quote_identifier("bad-name")
    finally:
        set_language("pt-BR")


def test_english_temporary_backup_cleanup_messages_are_localized(monkeypatch):
    set_language("en")
    try:
        success = TableResult("orders", True, "dump", backup_table="orders_backup")
        monkeypatch.setattr("syncdb.cli.drop_table", lambda *_args: None)
        cleanup_temporary_backups({"destino": {}}, "temp", [success])
        assert success.message == "temporary backup removed"
        assert success.backup_table is None

        def fail_drop(*_args):
            raise RuntimeError("permission denied")

        failure = TableResult("orders", True, "dump", backup_table="orders_backup")
        monkeypatch.setattr("syncdb.cli.drop_table", fail_drop)
        cleanup_temporary_backups({"destino": {}}, "temp", [failure])
        assert failure.ok is False
        assert failure.message.startswith("Synchronization finished, but temporary backup")
        assert "falhou" not in failure.message
    finally:
        set_language("pt-BR")


def test_english_schema_plan_details_are_localized():
    set_language("en")
    try:
        source = SchemaSnapshot(
            "orders", True,
            columns=(("id", "INT", "NO", None, "", "", 1), ("name", "VARCHAR(40)", "YES", None, "", "", 2)),
        )
        target = SchemaSnapshot("orders", True, columns=(("id", "INT", "NO", None, "", "", 1),))
        diff = SchemaDiff("orders", True, True, missing_columns=("name",), changed_columns=("id",))
        plan = build_schema_plan(diff, "update", source=source, target=target)
        details = [detail for operation in plan.operations for detail in operation.details]
        assert "after id" in details
        assert "destination: INT NOT NULL" in details
        assert "source: INT NOT NULL" in details
        assert not any("origem" in detail or "destino" in detail or "depois de" in detail for detail in details)
    finally:
        set_language("pt-BR")



def test_default_configuration_uses_brazilian_portuguese():

    assert default_config()["language"] == "pt-BR"


def test_existing_config_migrates_language_and_menu_helper_persists_english(tmp_path):
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    paths.config_file.write_text(json.dumps({"profiles": {}}), encoding="utf-8")

    config = load_config(paths)
    assert config["language"] == "pt-BR"

    set_config_language(paths, config, "en")

    saved = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert saved["language"] == "en"
    assert load_config(paths)["language"] == "en"


def test_interactive_language_menu_uses_current_language_without_name_error(monkeypatch, tmp_path):
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    paths.config_file.write_text(json.dumps({"language": "en", "profiles": {}}), encoding="utf-8")
    monkeypatch.setattr("syncdb.cli.select_option", lambda *args, **kwargs: "back")

    assert interactive_language(paths) == 0


def test_global_lang_override_uses_english_help_without_persisting(tmp_path, capsys):
    config_path = tmp_path / "config" / "config.json"
    main(["--config", str(config_path), "init", "--quiet"])
    before = config_path.read_text(encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["schema", "diff", "--lang", "en", "--help"])

    assert exc.value.code == 0
    assert "Analyze and synchronize table structure" in capsys.readouterr().out
    assert config_path.read_text(encoding="utf-8") == before


def test_language_cli_accepts_pt_en_and_lag_alias(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--lag", "en", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--lang {pt,en}" in output
    assert "--lag {pt,en}" in output


def test_saved_english_language_localizes_top_level_help_before_parser_construction(tmp_path, capsys):
    set_language("pt-BR")
    config_path = tmp_path / "config" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps({"language": "en", "profiles": {}}), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["--config", str(config_path), "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "MySQL/MariaDB table synchronizer" in output
    assert "Manage configuration" in output
    assert "Manage registered databases/connections" in output
    assert "Manage logs" in output
    assert "Gerencia configuração" not in output


def test_english_schema_diff_help_has_no_portuguese_option_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["schema", "diff", "--lang", "en", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Tables to synchronize" in output
    assert "Model/source database tag" in output
    assert "Show detailed read timings" in output
    assert "Tabelas para sincronizar" not in output
    assert "Tag do banco" not in output
    assert "Mostra tempos" not in output


def test_english_interactive_chrome_context_and_table_choices_are_localized():
    set_language("en")
    console = Console(record=True, width=120)
    console.print(menu_renderable("Menu", [MenuOption("Back", "back")], 0))
    chrome = console.export_text()

    assert "Use ↑/↓ to navigate, Enter to select, Esc/← to go back." in chrome
    assert "Use ↑/↓ para navegar" not in chrome
    assert format_sync_context(origin="source", destination="target", tables=["orders"], mode="auto", step="tables") == (
        "Selected source: source\nSelected destination: target\nSelected tables: orders\nSelected engine: auto\nChoose tables to synchronize"
    )
    assert [option.label for option in advanced_menu_options({}, "", "", [], "", False, "auto")][-1] == "Back"
    assert [option.label for option in _manual_schema_operation_options(SchemaPlan("orders", SchemaAction.COPY, ()), set())] == [
        "Review/apply selected",
        "Back",
    ]
    set_language("pt-BR")


def test_english_schema_plan_labels_preserve_sql_identifiers(capsys):
    set_language("en")
    plan = SchemaPlan(
        table="AlunoEspecial",
        action=SchemaAction.UPDATE,
        operations=(SchemaPlanOperation("add", "column", "NomeOriginal", ("source: VARCHAR(50)",), "ALTER TABLE `AlunoEspecial` ADD COLUMN `NomeOriginal` VARCHAR(50);"),),
    )

    print_schema_plan(plan, show_sql=True)

    output = capsys.readouterr().out
    assert "Schema plan: AlunoEspecial (update)" in output
    assert "ADD (1)" in output
    assert "column NomeOriginal" in output
    assert "ALTER TABLE `AlunoEspecial` ADD COLUMN `NomeOriginal`" in output
    set_language("pt-BR")


def test_english_advanced_menu_and_confirmation_are_fully_translated(monkeypatch):
    set_language("en")
    labels = [option.label for option in advanced_menu_options({}, "", "", [], "", False, "auto")]
    descriptions = [option.description for option in advanced_backup_options() + advanced_mode_options("", False)]
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "y")

    assert labels == [
        "Source database",
        "Destination database",
        "Choose tables",
        "Add condition (WHERE)",
        "Which rows to add",
        "Synchronization engine",
        "Run advanced synchronization",
        "Back",
    ]
    assert advanced_rows_text(False) == "ALL — replaces the entire table"
    assert confirm("Continue?") is True
    assert prompts == ["Continue? [y/N] "]
    assert not any("não" in text or "recomendado" in text or "cliente do sistema" in text for text in descriptions)
    set_language("pt-BR")


def test_english_client_and_doctor_status_tables_have_no_portuguese(monkeypatch, tmp_path, capsys):
    set_language("en")
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    paths.config_file.write_text(json.dumps({"language": "en", "profiles": {}, "client": {"vendor": "mariadb", "mode": "auto", "preferred_source": "managed"}}), encoding="utf-8")
    monkeypatch.setattr("syncdb.cli.find_managed_client", lambda *args: None)
    monkeypatch.setattr("syncdb.cli.find_system_client", lambda *args: None)

    assert cmd_client(paths, Namespace(client_command="status")) == 0
    assert cmd_doctor(paths) == 0

    output = capsys.readouterr().out
    for portuguese in ("Cliente MariaDB", "Pasta gerenciada", "Detalhes", "Conexões", "Versão / mensagem", "Nenhum cliente dump", "ainda não configurados"):
        assert portuguese not in output
    set_language("pt-BR")


def test_english_interactive_sync_backup_db_logs_and_client_use_english_labels(monkeypatch, tmp_path, capsys):
    from syncdb import cli

    set_language("en")
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    config = {"language": "en", "profiles": {"source": {}, "target": {}}, "defaults": {"origin": "source", "destination": "target"}}
    monkeypatch.setattr(cli, "load_config", lambda _paths: config)
    monkeypatch.setattr(cli, "read_last_tables", lambda *_args: [])
    choices = iter(["source", "target"])
    monkeypatch.setattr(cli, "choose_profile", lambda *_args, **_kwargs: next(choices))
    monkeypatch.setattr(cli, "read_tables_input", lambda: ["orders"])
    monkeypatch.setattr(cli, "confirm", lambda question: question == "Continue?")
    monkeypatch.setattr(cli, "cmd_sync", lambda *_args, **_kwargs: 0)

    assert cli.interactive_sync(paths) == 0
    output = capsys.readouterr().out
    assert "Synchronization summary" in output
    assert "Summary of synchronization" not in output
    assert "Resumo da sincronização" not in output

    seen = []
    monkeypatch.setattr(cli, "select_option", lambda title, options, **_kwargs: seen.append((title, [option.label for option in options])) or "back")
    monkeypatch.setattr(cli, "choose_profile", lambda _config, title, *_args, **kwargs: seen.append((title, kwargs.get("footer", ""))) or "back")
    assert cli.interactive_backup(paths) == cli.MENU_BACK
    assert cli.interactive_db(paths) == 0
    assert cli.interactive_logs(paths) == 0
    assert cli.interactive_client(paths) == 0

    rendered = "\n".join(str(item) for item in seen)
    for portuguese in ("Backup de tabelas", "Bancos / conexões", "Listar bancos", "Mostrar caminho", "Instalar/atualizar MariaDB"):
        assert portuguese not in rendered
    for english in ("Table backup", "Databases / connections", "List databases", "Show path", "Install/update MariaDB"):
        assert english in rendered
    set_language("pt-BR")
