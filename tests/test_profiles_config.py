import json
from pathlib import Path

from syncdb.config import db_connection_config, load_config, resolve_profile_pair, save_config
from syncdb.paths import AppPaths


def test_old_origem_destino_config_is_migrated_to_profiles(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    paths.config_file.write_text(
        json.dumps(
            {
                "origem": {"alias": "PROD", "host": "prod.local", "port": 3306, "user": "u", "password": "p", "database": "dbp", "charset": "latin1"},
                "destino": {"alias": "LOCAL", "host": "127.0.0.1", "port": 3307, "user": "root", "password": "", "database": "dbl", "charset": "latin1"},
                "client": {"mode": "auto"},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(paths)

    assert "origem" not in config
    assert "destino" not in config
    assert config["defaults"] == {"origin": "prod", "destination": "local"}
    assert config["profiles"]["prod"]["host"] == "prod.local"
    assert config["profiles"]["local"]["port"] == 3307


def test_db_connection_config_strips_profile_metadata():
    profile = {
        "alias": "prod",
        "label": "PROD",
        "host": "h",
        "port": 3306,
        "user": "u",
        "password": "p",
        "database": "db",
        "charset": "latin1",
        "allow_as_origin": True,
        "allow_as_destination": False,
    }

    assert db_connection_config(profile) == {
        "host": "h",
        "port": 3306,
        "user": "u",
        "password": "p",
        "database": "db",
        "charset": "latin1",
    }


def test_resolve_profile_pair_uses_defaults_and_cli_overrides(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    config = load_config(paths)
    config["profiles"]["homolog"] = {
        "label": "Homolog",
        "host": "h",
        "port": 3306,
        "user": "u",
        "password": "p",
        "database": "db",
        "charset": "latin1",
        "allow_as_origin": True,
        "allow_as_destination": True,
    }
    save_config(config, paths)

    config = load_config(paths)
    origin, destination = resolve_profile_pair(config, origin="homolog", destination=None)

    assert origin["alias"] == "homolog"
    assert destination["alias"] == config["defaults"]["destination"]


def test_resolve_profile_pair_blocks_source_only_destination(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)
    config = load_config(paths)
    config["profiles"]["prod"] = {
        "label": "Prod",
        "host": "p",
        "port": 3306,
        "user": "u",
        "password": "p",
        "database": "db",
        "charset": "latin1",
        "allow_as_origin": True,
        "allow_as_destination": False,
    }
    save_config(config, paths)

    config = load_config(paths)

    try:
        resolve_profile_pair(config, origin="local", destination="prod")
    except ValueError as exc:
        assert "não pode ser destino" in str(exc)
    else:
        raise AssertionError("source_only profile should not be accepted as destination")
