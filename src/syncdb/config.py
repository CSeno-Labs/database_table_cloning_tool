from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .i18n import DEFAULT_LANGUAGE, normalize_language
from .paths import AppPaths


class ConfigError(RuntimeError):
    """Raised when the user config cannot be loaded."""


PROFILE_TEMPLATE: dict[str, Any] = {
    "label": "",
    "host": "",
    "port": 3306,
    "user": "",
    "password": "",
    "database": "",
    "charset": "latin1",
    "allow_as_origin": True,
    "allow_as_destination": True,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "language": DEFAULT_LANGUAGE,
    "profiles": {
        "prod": {
            **PROFILE_TEMPLATE,
            "label": "Produção leitura",
            "allow_as_destination": False,
        },
        "local": {
            **PROFILE_TEMPLATE,
            "label": "Local",
            "host": "127.0.0.1",
            "user": "root",
        },
    },
    "defaults": {
        "origin": "prod",
        "destination": "local",
    },
    "sync": {
        "last_tables_file": "last_tables.txt",
        "truncate_before_insert": True,
        "create_missing_tables": True,
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
    try:
        with paths.config_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Config JSON inválido em {paths.config_file}: {exc.msg} "
            f"(line {exc.lineno} column {exc.colno})."
        ) from exc
    except OSError as exc:
        raise ConfigError(f"Não consegui ler o config {paths.config_file}: {exc}") from exc
    return merge_defaults(data)


def save_config(config: dict[str, Any], paths: AppPaths | None = None) -> Path:
    paths = paths or AppPaths.current()
    paths.ensure_dirs()
    paths.config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths.config_file


def merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    data = migrate_legacy_config(copy.deepcopy(data))
    merged = default_config()
    _deep_update(merged, data)
    merged.get("client", {}).pop("auto_download", None)
    merged["language"] = normalize_language(merged.get("language"))
    for tag, profile in list(merged.get("profiles", {}).items()):
        merged["profiles"][tag] = normalize_profile(tag, profile)
    return merged


def migrate_legacy_config(data: dict[str, Any]) -> dict[str, Any]:
    if "profiles" in data:
        data.pop("origem", None)
        data.pop("destino", None)
        return data

    origem = data.pop("origem", None)
    destino = data.pop("destino", None)
    if origem or destino:
        profiles = {}
        defaults = data.setdefault("defaults", {})
        if origem:
            origin_tag = profile_tag(origem.get("alias") or "prod")
            profiles[origin_tag] = legacy_profile(origin_tag, origem, allow_as_destination=False)
            defaults.setdefault("origin", origin_tag)
        if destino:
            destination_tag = profile_tag(destino.get("alias") or "local")
            profiles[destination_tag] = legacy_profile(destination_tag, destino, allow_as_destination=True)
            defaults.setdefault("destination", destination_tag)
        data["profiles"] = profiles
    return data


def legacy_profile(tag: str, old: dict[str, Any], *, allow_as_destination: bool) -> dict[str, Any]:
    return normalize_profile(
        tag,
        {
            "label": old.get("alias") or tag,
            "host": old.get("host", ""),
            "port": old.get("port", 3306),
            "user": old.get("user", ""),
            "password": old.get("password", ""),
            "database": old.get("database", ""),
            "charset": old.get("charset", "latin1"),
            "allow_as_origin": True,
            "allow_as_destination": allow_as_destination,
        },
    )


def normalize_profile(tag: str, profile: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(PROFILE_TEMPLATE)
    _deep_update(normalized, profile)
    normalized["port"] = int(normalized.get("port") or 3306)
    normalized.setdefault("label", tag)
    return normalized


def profile_tag(value: str) -> str:
    value = (value or "db").strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "db"


def db_connection_config(profile: dict[str, Any]) -> dict[str, Any]:
    allowed = {"host", "port", "user", "password", "database", "charset"}
    return {key: value for key, value in profile.items() if key in allowed}


def resolve_profile_pair(config: dict[str, Any], origin: str | None = None, destination: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    profiles = config.get("profiles", {})
    defaults = config.get("defaults", {})
    origin_tag = origin or defaults.get("origin")
    destination_tag = destination or defaults.get("destination")
    if not origin_tag or origin_tag not in profiles:
        raise ValueError(f"Origem não encontrada: {origin_tag or '(não configurada)'}")
    if not destination_tag or destination_tag not in profiles:
        raise ValueError(f"Destino não encontrado: {destination_tag or '(não configurado)'}")
    origin_profile = normalize_profile(origin_tag, profiles[origin_tag])
    destination_profile = normalize_profile(destination_tag, profiles[destination_tag])
    if not origin_profile.get("allow_as_origin", True):
        raise ValueError(f"{origin_tag} não pode ser origem.")
    if not destination_profile.get("allow_as_destination", True):
        raise ValueError(f"{destination_tag} não pode ser destino.")
    origin_profile["alias"] = origin_tag
    destination_profile["alias"] = destination_tag
    return origin_profile, destination_profile


def sync_runtime_config(config: dict[str, Any], origin: str | None = None, destination: str | None = None) -> dict[str, Any]:
    origem, destino = resolve_profile_pair(config, origin, destination)
    runtime = copy.deepcopy(config)
    runtime["origem"] = origem
    runtime["destino"] = destino
    return runtime


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(config)
    for profile in redacted.get("profiles", {}).values():
        if profile.get("password"):
            profile["password"] = "********"
    for section in ("origem", "destino"):
        password = redacted.get(section, {}).get("password")
        if password:
            redacted[section]["password"] = "********"
    return redacted
