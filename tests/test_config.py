from pathlib import Path

from syncdb.config import DEFAULT_CONFIG, ensure_config, load_config
from syncdb.paths import AppPaths


def test_ensure_config_creates_default_without_overwriting(tmp_path: Path):
    paths = AppPaths.from_base(tmp_path)

    created = ensure_config(paths)

    assert created == paths.config_file
    data = load_config(paths)
    assert data["client"]["mode"] == "auto"
    assert data["client"]["preferred_source"] == "managed"
    assert data["client"]["vendor"] == "mariadb"
    assert "auto_download" not in data["client"]

    paths.config_file.write_text('{"custom": true}', encoding="utf-8")
    second = ensure_config(paths)
    assert second == paths.config_file
    assert paths.config_file.read_text(encoding="utf-8") == '{"custom": true}'


def test_default_config_has_no_auto_download_flag():
    assert DEFAULT_CONFIG["client"] == {
        "mode": "auto",
        "preferred_source": "managed",
        "vendor": "mariadb",
    }
