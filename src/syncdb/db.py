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


def list_table_names(config: dict[str, Any], *, connection_timeout: int | None = None) -> list[str]:
    """List base-table names in the profile's current database."""
    conn = (
        get_connection(config, connection_timeout=connection_timeout)
        if connection_timeout is not None
        else get_connection(config)
    )
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = %s ORDER BY TABLE_NAME",
            ("BASE TABLE",),
        )
        return [str(row[0]) for row in cur.fetchall()]
    finally:
        if cur is not None:
            cur.close()
        conn.close()


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
