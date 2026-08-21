from syncdb.cli import interactive_schema
from syncdb.paths import AppPaths


def app_paths(tmp_path):
    return AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
    )


def test_interactive_schema_offers_manual_selection_without_cli_action(monkeypatch, tmp_path):
    paths = app_paths(tmp_path)
    menu_labels = []

    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: {
        "profiles": {
            "prod": {"label": "Prod", "host": "prod", "database": "db"},
            "local": {"label": "Local", "host": "local", "database": "db"},
        },
        "defaults": {"origin": "prod", "destination": "local"},
    })
    monkeypatch.setattr("syncdb.cli.choose_profile", lambda config, title, default, **kwargs: default)
    monkeypatch.setattr("builtins.input", lambda prompt="": "aluno")

    def fake_select(title, options, **kwargs):
        if title == "Estrutura das tabelas":
            menu_labels.extend(option.label for option in options)
        return "back"

    monkeypatch.setattr("syncdb.cli.select_option", fake_select)

    assert interactive_schema(paths) == -1000
    assert "Escolher manualmente o que aplicar" in menu_labels


def test_interactive_schema_manual_action_is_guided_and_does_not_apply_yet(monkeypatch, tmp_path, capsys):
    paths = app_paths(tmp_path)

    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: {
        "profiles": {
            "prod": {"label": "Prod", "host": "prod", "database": "db"},
            "local": {"label": "Local", "host": "local", "database": "db"},
        },
        "defaults": {"origin": "prod", "destination": "local"},
    })
    monkeypatch.setattr("syncdb.cli.choose_profile", lambda config, title, default, **kwargs: default)
    monkeypatch.setattr("builtins.input", lambda prompt="": "aluno")
    monkeypatch.setattr("syncdb.cli.select_option", lambda title, options, **kwargs: "manual")

    assert interactive_schema(paths) == 0
    shown = capsys.readouterr().out
    assert "seleção manual" in shown
    assert "Nenhuma alteração foi feita" in shown


def test_interactive_schema_preselects_last_tables(monkeypatch, tmp_path):
    paths = app_paths(tmp_path)
    choices = []

    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: {
        "profiles": {"prod": {"label": "Prod"}, "local": {"label": "Local"}},
        "defaults": {"origin": "prod", "destination": "local"},
    })
    monkeypatch.setattr("syncdb.cli.choose_profile", lambda config, title, default, **kwargs: default)
    monkeypatch.setattr("syncdb.cli.read_last_tables", lambda paths, config: ["pessoa", "func_geral"])

    def fake_select(title, options, **kwargs):
        choices.append((title, [option.label for option in options], kwargs.get("default_index")))
        return "last" if title.endswith("— tabelas") else "back"

    monkeypatch.setattr("syncdb.cli.select_option", fake_select)

    assert interactive_schema(paths) == -1000
    title, labels, default_index = choices[0]
    assert "tabelas" in title
    assert labels[0] == "Usar últimas (pessoa, func_geral)"
    assert default_index == 0
