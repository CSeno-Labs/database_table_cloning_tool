import pytest

from syncdb.cli import build_parser, run_interactive_menu
from syncdb.paths import AppPaths
from syncdb.schema import SchemaAction, normalize_schema_action


def app_paths(tmp_path):
    return AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
    )


def test_schema_action_names_are_explicit():
    assert normalize_schema_action("copy") == SchemaAction.COPY
    assert normalize_schema_action("update") == SchemaAction.UPDATE
    assert normalize_schema_action("recreate-table") == SchemaAction.RECREATE_TABLE


@pytest.mark.parametrize("alias", ["c", "sync", "preserve-extra", "recreate", "rebuild"])
def test_schema_actions_have_no_short_aliases(alias):
    with pytest.raises(ValueError):
        normalize_schema_action(alias)


def test_schema_help_exposes_explicit_commands(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["schema", "--help"])

    assert exc.value.code == 0
    shown = capsys.readouterr().out
    assert "diff" in shown
    assert "copy" in shown
    assert "update" in shown
    assert "recreate-table" in shown
    assert "--mode" not in shown
    assert "--include" not in shown


@pytest.mark.parametrize("command", ["copy", "update", "recreate-table"])
def test_schema_action_help_has_no_mode_or_include(command, capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["schema", command, "--help"])

    assert exc.value.code == 0
    shown = capsys.readouterr().out
    assert "--mode" not in shown
    assert "--include" not in shown


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
