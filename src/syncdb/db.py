from __future__ import annotations

from typing import Any

from .config import db_connection_config


def connection_params(config: dict[str, Any]) -> dict[str, Any]:
    return db_connection_config(config)


def get_connection(config: dict[str, Any], *, connection_timeout: int | None = None):
    import mysql.connector  # lazy import keeps non-DB commands lightweight

    params = connection_params(config)
    if connection_timeout is not None:
        params["connection_timeout"] = connection_timeout
    return mysql.connector.connect(**params)


def test_connection(config: dict[str, Any], *, connection_timeout: int | None = None) -> tuple[bool, str]:
    try:
        conn = (
            get_connection(config, connection_timeout=connection_timeout)
            if connection_timeout is not None
            else get_connection(config)
        )
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        cur.close()
        conn.close()
        return True, str(version)
    except Exception as exc:  # noqa: BLE001 - show friendly diagnostic
        return False, str(exc)
