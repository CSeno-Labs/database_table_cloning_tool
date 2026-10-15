from __future__ import annotations

import importlib.metadata
import json
import re
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .paths import AppPaths

UPDATE_CHECK_URL = "https://raw.githubusercontent.com/CSeno-Labs/database_table_cloning_tool/main/src/syncdb/__init__.py"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_CHECK_WAIT_SECONDS = 0.25
_CACHE_NAME = "update-check.json"
_VERSION_PATTERN = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")
_REMOTE_VERSION_PATTERN = re.compile(r"^\s*__version__\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)


def is_editable_install() -> bool:
    """Return True for a source/editable install, which should use git pull."""
    repository_root = Path(__file__).resolve().parents[2]
    if (repository_root / ".git").exists():
        return True
    try:
        distribution = importlib.metadata.distribution("database-table-cloning-tool")
        direct_url = distribution.read_text("direct_url.json")
        if not direct_url:
            return False
        return bool(json.loads(direct_url).get("dir_info", {}).get("editable"))
    except (importlib.metadata.PackageNotFoundError, OSError, json.JSONDecodeError, AttributeError):
        return False


def fetch_latest_version() -> str | None:
    request = Request(UPDATE_CHECK_URL, headers={"User-Agent": "sync-db-update-check"})
    with urlopen(request, timeout=3.0) as response:
        content = response.read(32_000).decode("utf-8")
    match = _REMOTE_VERSION_PATTERN.search(content)
    return match.group(1) if match else None


def _cache_path(paths: AppPaths) -> Path:
    return paths.cache_dir / _CACHE_NAME


def _read_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _write_cache(path: Path, data: dict) -> None:
    temporary = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _refresh_cache(path: Path, fetch_version) -> None:
    data = _read_cache(path)
    try:
        latest = fetch_version()
    except Exception:
        return
    if not isinstance(latest, str) or not _VERSION_PATTERN.match(latest):
        return
    data["latest_version"] = latest
    data["checked_at"] = time.time()
    _write_cache(path, data)


def _version_parts(version: str) -> tuple[int, ...] | None:
    match = _VERSION_PATTERN.match(version)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def _is_newer(latest: str, current: str) -> bool:
    latest_parts = _version_parts(latest)
    current_parts = _version_parts(current)
    if latest_parts is None or current_parts is None:
        return False
    width = max(len(latest_parts), len(current_parts))
    return latest_parts + (0,) * (width - len(latest_parts)) > current_parts + (0,) * (width - len(current_parts))


def check_for_update(
    paths: AppPaths,
    current_version: str,
    *,
    fetch_version=fetch_latest_version,
    editable_install: bool | None = None,
    wait_seconds: float = UPDATE_CHECK_WAIT_SECONDS,
) -> str | None:
    """Return a newer cached/discovered version; network checks are throttled and bounded."""
    if editable_install is None:
        editable_install = is_editable_install()
    if editable_install:
        return None

    path = _cache_path(paths)
    data = _read_cache(path)
    try:
        checked_at = float(data.get("checked_at", 0))
    except (TypeError, ValueError):
        checked_at = 0
    if time.time() - checked_at >= UPDATE_CHECK_INTERVAL_SECONDS:
        data["checked_at"] = time.time()
        _write_cache(path, data)
        worker = threading.Thread(target=_refresh_cache, args=(path, fetch_version), daemon=True)
        worker.start()
        worker.join(max(0.0, wait_seconds))
        data = _read_cache(path)

    latest = data.get("latest_version")
    if isinstance(latest, str) and _is_newer(latest, current_version):
        return latest
    return None
