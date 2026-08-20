import pytest

from syncdb.cli import build_parser, run_interactive_menu
from syncdb.paths import AppPaths
from syncdb.schema import (
    SchemaMode,
    normalize_schema_include,
    normalize_schema_mode,
    resolve_schema_options,
)


def app_paths(tmp_path):
    return AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
    )


def test_schema_mode_aliases_are_normalized():
    assert normalize_schema_mode("b") == SchemaMode.BASIC
    assert normalize_schema_mode("basic") == SchemaMode.BASIC
    assert normalize_schema_mode("a") == SchemaMode.ADD
    assert normalize_schema_mode("add") == SchemaMode.ADD
    assert normalize_schema_mode("additive") == SchemaMode.ADD
    assert normalize_schema_mode("c") == SchemaMode.COPY
    assert normalize_schema_mode("copy") == SchemaMode.COPY
    assert normalize_schema_mode("recreate-table") == SchemaMode.RECREATE_TABLE


@pytest.mark.parametrize("alias", ["r", "recreate", "recreate_table", "rebuild"])
def test_recreate_table_has_no_alias(alias):
    with pytest.raises(ValueError, match="recreate-table"):
        normalize_schema_mode(alias)


def test_include_all_expands_to_every_schema_category():
    assert normalize_schema_include("all") == (
        "columns",
        "indexes",
        "keys",
        "foreign-keys",
        "table-options",
    )


def test_add_mode_can_choose_include_categories():
    options = resolve_schema_options("a", "columns,indexes")

    assert options.mode == SchemaMode.ADD
    assert options.include == ("columns", "indexes")


def test_basic_mode_rejects_include_to_keep_it_unambiguous():
    with pytest.raises(ValueError, match="basic.*--include"):
        resolve_schema_options("basic", "indexes")


def test_recreate_table_rejects_include_because_it_is_complete():
    with pytest.raises(ValueError, match="recreate-table.*--include"):
        resolve_schema_options("recreate-table", "all")


def test_schema_help_exposes_modes_and_include_all(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["schema", "sync", "--help"])

    assert exc.value.code == 0
    shown = capsys.readouterr().out
    assert "basic" in shown
    assert "add" in shown
    assert "copy" in shown
    assert "recreate-table" in shown
    assert "all" in shown


def test_main_menu_has_schema_option_before_backup(monkeypatch, tmp_path):
    choices_seen = []

    def fake_select(title, options, **kwargs):
        if title == "Menu sync-db":
            choices_seen.extend(option.label for option in options)
            return "exit"
        return "back"

    monkeypatch.setattr("syncdb.cli.select_option", fake_select)
    monkeypatch.setattr("syncdb.cli.print_exit_banner", lambda: None)

    code = run_interactive_menu(app_paths(tmp_path))

    assert code == 0
    assert choices_seen.index("Estrutura das tabelas") < choices_seen.index("Backup de tabelas")


def test_interactive_sync_no_longer_prompts_for_backup(monkeypatch, tmp_path):
    from syncdb.config import ensure_config
    from syncdb.cli import interactive_sync

    paths = app_paths(tmp_path)
    ensure_config(paths)
    prompts = []

    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: {
        "profiles": {
            "prod": {"label": "Prod", "host": "prod", "database": "db", "allow_as_origin": True, "allow_as_destination": False},
            "local": {"label": "Local", "host": "local", "database": "db", "allow_as_origin": True, "allow_as_destination": True},
        },
        "defaults": {"origin": "prod", "destination": "local"},
    })
    monkeypatch.setattr("syncdb.cli.choose_profile", lambda config, title, default, **kwargs: default)
    monkeypatch.setattr("syncdb.cli.read_last_tables", lambda paths, config: [])
    monkeypatch.setattr("builtins.input", lambda prompt="": "aluno")

    def fake_confirm(question):
        prompts.append(question)
        return False

    monkeypatch.setattr("syncdb.cli.confirm", fake_confirm)
    monkeypatch.setattr("syncdb.cli.confirm_default", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("backup prompt should not be used")))

    code = interactive_sync(paths)

    assert code == 1
    assert prompts == ["Continuar?"]
