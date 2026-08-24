from syncdb.cli import interactive_schema
from syncdb.paths import AppPaths
from syncdb.schema import SchemaAction, SchemaPlan, SchemaPlanOperation, SchemaSnapshot


class FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql):
        self.executed.append(sql)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass

    def close(self):
        pass


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


def test_interactive_manual_selects_only_one_operation_and_executes_it(monkeypatch, tmp_path):
    paths = app_paths(tmp_path)
    cursor = FakeCursor()
    plan = SchemaPlan("aluno", SchemaAction.COPY, (
        SchemaPlanOperation("add", "column", "nome", sql="ALTER TABLE `aluno` ADD COLUMN `nome` VARCHAR(100);"),
        SchemaPlanOperation("modify", "column", "email", sql="ALTER TABLE `aluno` MODIFY COLUMN `email` VARCHAR(255);"),
        SchemaPlanOperation("drop", "column", "legacy", sql="ALTER TABLE `aluno` DROP COLUMN `legacy`;"),
    ))
    calls = []
    inputs = iter(("aluno", "aplicar"))

    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: {
        "profiles": {
            "prod": {"label": "Prod", "host": "prod", "database": "db"},
            "local": {"label": "Local", "host": "local", "database": "db", "connection": FakeConnection(cursor)},
        },
        "defaults": {"origin": "prod", "destination": "local"},
    })
    monkeypatch.setattr("syncdb.cli.choose_profile", lambda config, title, default, **kwargs: default)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("syncdb.cli.inspect_schema_pair", lambda *args: (SchemaSnapshot("aluno", True), SchemaSnapshot("aluno", True)))
    monkeypatch.setattr("syncdb.cli.compare_schema", lambda *args: object())
    monkeypatch.setattr("syncdb.cli.build_schema_plan", lambda diff, action, **kwargs: calls.append(action) or plan)

    selections = iter(("manual", "toggle:0", "review"))
    monkeypatch.setattr("syncdb.cli.select_option", lambda title, options, **kwargs: next(selections))

    assert interactive_schema(paths) == 0
    assert calls == [SchemaAction.COPY]
    assert cursor.executed == ["ALTER TABLE `aluno` ADD COLUMN `nome` VARCHAR(100);"]


def test_interactive_manual_copy_offers_removal_operations(monkeypatch, tmp_path):
    paths = app_paths(tmp_path)
    plan = SchemaPlan("aluno", SchemaAction.COPY, (
        SchemaPlanOperation("add", "column", "nome", sql="ALTER TABLE `aluno` ADD COLUMN `nome` VARCHAR(100);"),
        SchemaPlanOperation("drop", "column", "legacy", sql="ALTER TABLE `aluno` DROP COLUMN `legacy`;"),
    ))
    inputs = iter(("aluno",))
    operation_labels = []

    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: {
        "profiles": {"prod": {}, "local": {}},
        "defaults": {"origin": "prod", "destination": "local"},
    })
    monkeypatch.setattr("syncdb.cli.choose_profile", lambda config, title, default, **kwargs: default)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("syncdb.cli.inspect_schema_pair", lambda *args: (SchemaSnapshot("aluno", True), SchemaSnapshot("aluno", True)))
    monkeypatch.setattr("syncdb.cli.compare_schema", lambda *args: object())
    monkeypatch.setattr("syncdb.cli.build_schema_plan", lambda *args, **kwargs: plan)

    selections = iter(("manual", "back"))

    def select(title, options, **kwargs):
        if title.startswith("Seleção manual"):
            operation_labels.extend(option.label for option in options)
        return next(selections)

    monkeypatch.setattr("syncdb.cli.select_option", select)

    assert interactive_schema(paths) == -1000
    assert any("legacy" in label for label in operation_labels)
