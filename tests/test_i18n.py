import json

import pytest

from syncdb.cli import main, print_schema_plan, set_config_language
from syncdb.config import default_config, load_config
from syncdb.i18n import set_language
from syncdb.paths import AppPaths
from syncdb.schema import SchemaAction, SchemaPlan, SchemaPlanOperation


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


def test_global_lang_override_uses_english_help_without_persisting(tmp_path, capsys):
    config_path = tmp_path / "config" / "config.json"
    main(["--config", str(config_path), "init", "--quiet"])
    before = config_path.read_text(encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["schema", "diff", "--lang", "en", "--help"])

    assert exc.value.code == 0
    assert "Analyze and synchronize table structure" in capsys.readouterr().out
    assert config_path.read_text(encoding="utf-8") == before


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
