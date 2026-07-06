from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .clients import DumpClient
from .db import get_connection
from .paths import AppPaths
from .tables import quote_identifier


@dataclass
class TableResult:
    table: str
    ok: bool
    engine: str
    rows: int | None = None
    message: str = ""


class SyncError(RuntimeError):
    pass


def table_exists(config: dict[str, Any], table: str) -> bool:
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW TABLES LIKE %s", (table.split(".")[-1],))
        return cur.fetchone() is not None
    finally:
        conn.close()


def get_columns(config: dict[str, Any], table: str) -> dict[str, dict[str, Any]]:
    conn = get_connection(config)
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(f"SHOW FULL COLUMNS FROM {quote_identifier(table)}")
        return {row["Field"]: row for row in cur.fetchall()}
    finally:
        conn.close()


def get_create_table(config: dict[str, Any], table: str) -> str:
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(f"SHOW CREATE TABLE {quote_identifier(table)}")
        row = cur.fetchone()
        return row[1]
    finally:
        conn.close()


def sanitize_collation(collation: str | None) -> str | None:
    if not collation:
        return None
    return collation.replace("0900_ai_ci", "general_ci")


def ensure_structure(config: dict[str, Any], table: str, create_sql: str, source_columns: dict[str, dict[str, Any]], *, create_missing: bool, add_missing_columns: bool) -> None:
    exists = table_exists(config, table)
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        if not exists:
            if not create_missing:
                raise SyncError(f"Tabela {table} não existe no destino e create_missing_tables=false.")
            cur.execute(create_sql)
            conn.commit()
            return

        if not add_missing_columns:
            return

        target_columns = get_columns(config, table)
        for name, details in source_columns.items():
            if name in target_columns:
                continue
            col_type = details.get("Type") or details.get("type")
            collation = sanitize_collation(details.get("Collation") or details.get("collation"))
            sql = f"ALTER TABLE {quote_identifier(table)} ADD COLUMN {quote_identifier(name)} {col_type}"
            if collation:
                sql += f" COLLATE {collation}"
            sql += " NULL"
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


def row_count(config: dict[str, Any], table: str) -> int:
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _defaults_file(db_config: dict[str, Any], tmpdir: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix="sync-db-client-", suffix=".cnf", dir=tmpdir)
    os.close(fd)
    path = Path(name)
    user = db_config.get("user", "")
    password = db_config.get("password", "")
    host = db_config.get("host", "")
    port = db_config.get("port", 3306)
    charset = db_config.get("charset") or "latin1"
    path.write_text(
        "[client]\n"
        f"user={user}\n"
        f"password={password}\n"
        f"host={host}\n"
        f"port={port}\n"
        f"default-character-set={charset}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def build_dump_command(client: DumpClient, defaults_file: Path, *, database: str, table: str, include_create: bool) -> list[str]:
    command = [str(client.dump), f"--defaults-extra-file={defaults_file}"]
    if client.vendor == "mariadb":
        # Newer MariaDB clients may verify server certificates by default and fail
        # against production servers that use private/self-signed chains. Python's
        # connector in this tool does not verify by default, so keep dump behavior
        # equivalent unless the user later opts into strict SSL verification.
        command.append("--ssl-verify-server-cert=0")
    if not include_create:
        command.append("--no-create-info")
    command.extend([
        "--complete-insert",
        "--skip-add-locks",
        "--skip-comments",
        "--single-transaction",
        "--quick",
        database,
        table,
    ])
    return command


def sql_string_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def build_truncate_preamble(table: str) -> str:
    table_name = table.split(".")[-1]
    delete_sql = f"DELETE FROM {quote_identifier(table)}"
    return (
        "SET FOREIGN_KEY_CHECKS=0;\n"
        "SET @syncdb_table_exists := ("
        "SELECT COUNT(*) FROM information_schema.tables "
        f"WHERE table_schema = DATABASE() AND table_name = {sql_string_literal(table_name)});\n"
        f"SET @syncdb_sql := IF(@syncdb_table_exists > 0, {sql_string_literal(delete_sql)}, 'SELECT 1');\n"
        "PREPARE syncdb_stmt FROM @syncdb_sql;\n"
        "EXECUTE syncdb_stmt;\n"
        "DEALLOCATE PREPARE syncdb_stmt;\n"
    )


def delete_existing_rows(config: dict[str, Any], table: str) -> None:
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        cur.execute(f"DELETE FROM {quote_identifier(table)}")
        conn.commit()
    finally:
        conn.close()


def build_import_command(client: DumpClient, defaults_file: Path, *, database: str) -> list[str]:
    command = [str(client.mysql), f"--defaults-extra-file={defaults_file}"]
    if client.vendor == "mariadb":
        # The managed MariaDB client may inherit TLS preferences from modern
        # defaults. Local/dev MariaDB servers often do not support SSL, so keep
        # imports to local destinations non-TLS by default. Source dumps still
        # use TLS when the server requires it.
        command.append("--ssl=0")
    command.append(database)
    return command


def run_dump_sync(config: dict[str, Any], table: str, client: DumpClient, paths: AppPaths) -> TableResult:
    paths.ensure_dirs()
    origem = config["origem"]
    destino = config["destino"]
    sync_cfg = config.get("sync", {})
    tmpdir = paths.temp_dir
    src_defaults = _defaults_file(origem, tmpdir)
    dst_defaults = _defaults_file(destino, tmpdir)
    sql_path = tmpdir / f"sync-db-{table.replace('.', '_')}.sql"
    try:
        needs_creation = not table_exists(destino, table)
        if not needs_creation and sync_cfg.get("truncate_before_insert", True):
            delete_existing_rows(destino, table)
        dump_cmd = build_dump_command(client, src_defaults, database=origem["database"], table=table, include_create=needs_creation)
        with sql_path.open("w", encoding="utf-8") as out:
            out.write("SET FOREIGN_KEY_CHECKS=0;\n")
            proc = subprocess.run(dump_cmd, stdout=out, stderr=subprocess.PIPE, text=True, check=False)
            if proc.returncode != 0:
                raise SyncError(f"Falha no dump de {table}: {proc.stderr.strip()}")
            out.write("\nSET FOREIGN_KEY_CHECKS=1;\n")

        import_cmd = build_import_command(client, dst_defaults, database=destino["database"])
        with sql_path.open("rb") as fh:
            proc = subprocess.run(import_cmd, stdin=fh, stderr=subprocess.PIPE, text=True, check=False)
        if proc.returncode != 0:
            raise SyncError(f"Falha no import de {table}: {proc.stderr.strip()}")
        return TableResult(table=table, ok=True, engine=f"dump/{client.source.value}/{client.vendor}", rows=row_count(destino, table))
    except Exception as exc:  # noqa: BLE001
        return TableResult(table=table, ok=False, engine="dump", message=str(exc))
    finally:
        for path in (src_defaults, dst_defaults, sql_path):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def run_python_sync(config: dict[str, Any], table: str) -> TableResult:
    origem = config["origem"]
    destino = config["destino"]
    sync_cfg = config.get("sync", {})
    batch_size = int(sync_cfg.get("batch_size", 1000))
    try:
        source_columns = get_columns(origem, table)
        if not source_columns:
            raise SyncError(f"Tabela {table} não encontrada na origem.")
        create_sql = sanitize_create_table(get_create_table(origem, table))
        ensure_structure(
            destino,
            table,
            create_sql,
            source_columns,
            create_missing=bool(sync_cfg.get("create_missing_tables", True)),
            add_missing_columns=bool(sync_cfg.get("add_missing_columns", True)),
        )
        columns = list(source_columns.keys())
        quoted_cols = ", ".join(quote_identifier(col) for col in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        select_sql = f"SELECT {quoted_cols} FROM {quote_identifier(table)}"
        insert_sql = f"INSERT INTO {quote_identifier(table)} ({quoted_cols}) VALUES ({placeholders})"

        src = get_connection(origem)
        dst = get_connection(destino)
        rows = 0
        try:
            src_cur = src.cursor()
            dst_cur = dst.cursor()
            dst_cur.execute("SET FOREIGN_KEY_CHECKS=0")
            if sync_cfg.get("truncate_before_insert", True):
                dst_cur.execute(f"DELETE FROM {quote_identifier(table)}")
            src_cur.execute(select_sql)
            while True:
                batch = src_cur.fetchmany(batch_size)
                if not batch:
                    break
                dst_cur.executemany(insert_sql, batch)
                rows += len(batch)
            dst.commit()
            dst_cur.execute("SET FOREIGN_KEY_CHECKS=1")
            dst.commit()
        finally:
            src.close()
            dst.close()
        return TableResult(table=table, ok=True, engine="python", rows=rows)
    except Exception as exc:  # noqa: BLE001
        return TableResult(table=table, ok=False, engine="python", message=str(exc))


def sanitize_create_table(sql: str) -> str:
    return sql.replace("utf8mb4_0900_ai_ci", "utf8mb4_general_ci")
