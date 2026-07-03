from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .paths import AppPaths

DEFAULT_CONFIG: dict[str, Any] = {
    "origem": {
        "alias": "PROD",
        "host": "",
        "port": 3306,
        "user": "",
        "password": "",
        "database": "",
        "charset": "latin1",
    },
    "destino": {
        "alias": "LOCAL",
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "",
        "charset": "latin1",
    },
    "sync": {
        "default_tables_file": "tabelas_puxar.csv",
        "truncate_before_insert": True,
        "create_missing_tables": True,
        "add_missing_columns": True,
        "batch_size": 1000,
        "default_character_set": "latin1",
    },
    "client": {
        "mode": "auto",
        "preferred_source": "managed",
        "vendor": "mariadb",
    },
}


def default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def ensure_config(paths: AppPaths | None = None) -> Path:
    paths = paths or AppPaths.current()
    paths.ensure_dirs()
    if not paths.config_file.exists():
        paths.config_file.write_text(
            json.dumps(default_config(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return paths.config_file


def load_config(paths: AppPaths | None = None) -> dict[str, Any]:
    paths = paths or AppPaths.current()
    ensure_config(paths)
    with paths.config_file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return merge_defaults(data)


def save_config(config: dict[str, Any], paths: AppPaths | None = None) -> Path:
    paths = paths or AppPaths.current()
    paths.ensure_dirs()
    paths.config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths.config_file


def merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    merged = default_config()
    _deep_update(merged, data)
    # Historical configs/old proposals may have had auto_download. Keep config transparent.
    merged.get("client", {}).pop("auto_download", None)
    return merged


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(config)
    for section in ("origem", "destino"):
        password = redacted.get(section, {}).get("password")
        if password:
            redacted[section]["password"] = "********"
    return redacted
