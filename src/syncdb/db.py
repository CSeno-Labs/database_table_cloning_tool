from __future__ import annotations

from typing import Any


def connection_params(config: dict[str, Any]) -> dict[str, Any]:
    params = dict(config)
    params.pop("alias", None)
    return params


def get_connection(config: dict[str, Any]):
    import mysql.connector  # lazy import keeps non-DB commands lightweight

    return mysql.connector.connect(**connection_params(config))


def test_connection(config: dict[str, Any]) -> tuple[bool, str]:
    try:
        conn = get_connection(config)
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        cur.close()
        conn.close()
        return True, str(version)
    except Exception as exc:  # noqa: BLE001 - show friendly diagnostic
        return False, str(exc)
