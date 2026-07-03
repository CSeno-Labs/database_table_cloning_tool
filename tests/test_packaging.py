import tomllib
from pathlib import Path


def test_only_sync_db_console_script_is_declared():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]
    assert scripts == {"sync-db": "syncdb.cli:main"}
    assert "sinc-db" not in scripts


def test_legacy_bat_alias_removed():
    assert not Path("sinc-db.bat").exists()
