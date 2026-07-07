from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
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
    stage: str = ""
    backup_table: str | None = None
    sync_type: str = "full_replace"
    primary_key: list[str] | None = None
    origin_matched_rows: int | None = None
    deleted_rows: int | None = None
    inserted_rows: int | None = None
    skipped_existing_rows: int | None = None
    destination_matched_rows: int | None = None
    planned_insert_rows: int | None = None


class SyncError(RuntimeError):
    pass


DANGEROUS_WHERE_PATTERNS = [
    ";",
    "--",
    "/*",
    "*/",
    r"\bDELETE\b",
    r"\bDROP\b",
    r"\bUPDATE\b",
    r"\bINSERT\b",
    r"\bALTER\b",
    r"\bCREATE\b",
    r"\bTRUNCATE\b",
]


def normalize_where_clause(where_clause: str | None) -> str:
    where = (where_clause or "").strip()
    if where.lower().startswith("where "):
        where = where[6:].strip()
    return where


def validate_where_clause(where_clause: str | None) -> str:
    where = normalize_where_clause(where_clause)
    if not where:
        return ""
    upper = where.upper()
    for pattern in DANGEROUS_WHERE_PATTERNS:
        if pattern.startswith(r"\b"):
            if re.search(pattern, upper):
                token = pattern.replace("\\b", "")
                raise ValueError(f"WHERE contém comando não permitido: {token}")
        elif pattern in where:
            raise ValueError(f"WHERE contém token não permitido: {pattern}")
    return where


def chunked(items: list[tuple], size: int):
    for start in range(0, len(items), max(1, size)):
        yield items[start : start + max(1, size)]


def build_key_predicate(primary_key: list[str], keys: list[tuple]) -> tuple[str, list[Any]]:
    if not keys:
        return "0=1", []
    clauses = []
    params: list[Any] = []
    for key in keys:
        values = tuple(key) if isinstance(key, tuple) else (key,)
        if len(values) != len(primary_key):
            raise SyncError("Quantidade de valores da chave não bate com a chave primária.")
        parts = []
        for column, value in zip(primary_key, values):
            parts.append(f"{quote_identifier(column)} = %s")
            params.append(value)
        clauses.append("(" + " AND ".join(parts) + ")" if len(parts) > 1 else parts[0])
    return "(" + " OR ".join(clauses) + ")", params


def get_primary_key(config: dict[str, Any], table: str) -> list[str]:
    conn = get_connection(config)
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(f"SHOW KEYS FROM {quote_identifier(table)} WHERE Key_name = 'PRIMARY'")
        rows = cur.fetchall()
        rows.sort(key=lambda row: int(row.get("Seq_in_index", 0)))
        primary_key = [row["Column_name"] for row in rows]
        if not primary_key:
            raise SyncError(f"A tabela {table} não possui chave primária. Sincronização parcial precisa de chave primária para identificar linhas.")
        return primary_key
    finally:
        conn.close()


def validate_where_for_table(config: dict[str, Any], table: str, primary_key: list[str], where_clause: str) -> int:
    where = validate_where_clause(where_clause)
    columns = ", ".join(quote_identifier(col) for col in primary_key)
    sql = f"SELECT {columns} FROM {quote_identifier(table)}"
    if where:
        sql += f" WHERE {where}"
    sql += " LIMIT 1"
    count_sql = f"SELECT COUNT(*) FROM {quote_identifier(table)}"
    if where:
        count_sql += f" WHERE {where}"
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cur.fetchone()
        cur.execute(count_sql)
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def preflight_advanced_sync(config: dict[str, Any], tables: list[str], where_clause: str = "", insert_missing: bool = False) -> list[TableResult]:
    origem = config["origem"]
    destino = config["destino"]
    sync_cfg = config.get("sync", {})
    batch_size = int(sync_cfg.get("batch_size", 1000))
    where = validate_where_clause(where_clause)
    sync_type = advanced_sync_type(where, insert_missing)
    results: list[TableResult] = []
    for table in tables:
        try:
            primary_key = get_primary_key(origem, table)
            matched = validate_where_for_table(origem, table, primary_key, where)
            source_keys = select_keys(origem, table, primary_key, where)
            destination_matches = 0
            planned_insert = len(source_keys)
            skipped_existing = 0
            if source_keys and table_exists(destino, table):
                existing = select_existing_keys(destino, table, primary_key, source_keys, batch_size)
                destination_matches = len(existing)
                skipped_existing = destination_matches
                if insert_missing:
                    planned_insert = len(source_keys) - destination_matches
            elif insert_missing:
                planned_insert = len(source_keys)
            results.append(
                TableResult(
                    table=table,
                    ok=True,
                    engine="python/advanced",
                    stage="preflight",
                    sync_type=sync_type,
                    primary_key=primary_key,
                    origin_matched_rows=matched,
                    destination_matched_rows=destination_matches,
                    planned_insert_rows=planned_insert,
                    skipped_existing_rows=skipped_existing if insert_missing else None,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(TableResult(table=table, ok=False, engine="python/advanced", stage="validate_where" if where else "inspect_primary_key", message=str(exc), sync_type=sync_type))
    return results


def advanced_sync_type(where_clause: str, insert_missing: bool) -> str:
    where = bool(normalize_where_clause(where_clause))
    if where and insert_missing:
        return "where_insert_missing"
    if where:
        return "where_replace"
    if insert_missing:
        return "insert_missing"
    return "full_replace"


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


def backup_existing_table(config: dict[str, Any], table: str, *, suffix: str | None = None, backup_name: str | None = None) -> str:
    suffix = suffix or datetime.now().strftime("%Y%m%d_%H%M%S")
    base = table.split(".")[-1]
    backup_name = backup_name or f"{base}_syncdb_backup_{suffix}"
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {quote_identifier(backup_name)}")
        cur.execute(f"CREATE TABLE {quote_identifier(backup_name)} AS SELECT * FROM {quote_identifier(table)}")
        conn.commit()
        return backup_name
    finally:
        conn.close()


def drop_table(config: dict[str, Any], table: str) -> None:
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {quote_identifier(table)}")
        conn.commit()
    finally:
        conn.close()


def run_table_backup(config: dict[str, Any], table: str, backup_name: str) -> TableResult:
    try:
        created = backup_existing_table(config, table, backup_name=backup_name)
        return TableResult(table=table, ok=True, engine="backup", stage="done", backup_table=created)
    except Exception as exc:  # noqa: BLE001
        return TableResult(table=table, ok=False, engine="backup", message=str(exc), stage="backup_table")


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
    stage = "prepare"
    backup_table: str | None = None
    try:
        stage = "check_dest"
        needs_creation = not table_exists(destino, table)
        if not needs_creation and sync_cfg.get("backup_before_replace"):
            stage = "backup_dest"
            backup_table = backup_existing_table(destino, table)
        if not needs_creation and sync_cfg.get("truncate_before_insert", True):
            stage = "cleanup_dest"
            delete_existing_rows(destino, table)
        stage = "dump_source"
        dump_cmd = build_dump_command(client, src_defaults, database=origem["database"], table=table, include_create=needs_creation)
        with sql_path.open("w", encoding="utf-8") as out:
            out.write("SET FOREIGN_KEY_CHECKS=0;\n")
            proc = subprocess.run(dump_cmd, stdout=out, stderr=subprocess.PIPE, text=True, check=False)
            if proc.returncode != 0:
                raise SyncError(f"Falha no dump de {table}: {proc.stderr.strip()}")
            out.write("\nSET FOREIGN_KEY_CHECKS=1;\n")

        stage = "import_dest"
        import_cmd = build_import_command(client, dst_defaults, database=destino["database"])
        with sql_path.open("rb") as fh:
            proc = subprocess.run(import_cmd, stdin=fh, stderr=subprocess.PIPE, text=True, check=False)
        if proc.returncode != 0:
            raise SyncError(f"Falha no import de {table}: {proc.stderr.strip()}")
        stage = "count_dest"
        return TableResult(table=table, ok=True, engine=f"dump/{client.source.value}/{client.vendor}", rows=row_count(destino, table), stage="done", backup_table=backup_table)
    except Exception as exc:  # noqa: BLE001
        return TableResult(table=table, ok=False, engine="dump", message=str(exc), stage=stage, backup_table=backup_table)
    finally:
        for path in (src_defaults, dst_defaults, sql_path):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def select_keys(config: dict[str, Any], table: str, primary_key: list[str], where_clause: str = "") -> list[tuple]:
    where = validate_where_clause(where_clause)
    columns = ", ".join(quote_identifier(col) for col in primary_key)
    sql = f"SELECT {columns} FROM {quote_identifier(table)}"
    if where:
        sql += f" WHERE {where}"
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return [tuple(row if isinstance(row, (tuple, list)) else (row,)) for row in cur.fetchall()]
    finally:
        conn.close()


def select_existing_keys(config: dict[str, Any], table: str, primary_key: list[str], keys: list[tuple], batch_size: int) -> set[tuple]:
    if not keys:
        return set()
    found: set[tuple] = set()
    conn = get_connection(config)
    try:
        cur = conn.cursor()
        columns = ", ".join(quote_identifier(col) for col in primary_key)
        for batch in chunked(keys, batch_size):
            predicate, params = build_key_predicate(primary_key, batch)
            cur.execute(f"SELECT {columns} FROM {quote_identifier(table)} WHERE {predicate}", params)
            for row in cur.fetchall():
                found.add(tuple(row if isinstance(row, (tuple, list)) else (row,)))
    finally:
        conn.close()
    return found


def run_python_advanced_sync(config: dict[str, Any], table: str, *, where_clause: str = "", insert_missing: bool = False) -> TableResult:
    origem = config["origem"]
    destino = config["destino"]
    sync_cfg = config.get("sync", {})
    batch_size = int(sync_cfg.get("batch_size", 1000))
    where = validate_where_clause(where_clause)
    sync_type = advanced_sync_type(where, insert_missing)
    stage = "inspect_primary_key"
    backup_table: str | None = None
    primary_key: list[str] = []
    try:
        primary_key = get_primary_key(origem, table)
        source_columns = get_columns(origem, table)
        if not source_columns:
            raise SyncError(f"Tabela {table} não encontrada na origem.")
        create_sql = sanitize_create_table(get_create_table(origem, table))
        stage = "ensure_dest_structure"
        ensure_structure(destino, table, create_sql, source_columns, create_missing=bool(sync_cfg.get("create_missing_tables", True)), add_missing_columns=bool(sync_cfg.get("add_missing_columns", True)))
        stage = "read_source_keys"
        source_keys = select_keys(origem, table, primary_key, where)
        if not source_keys:
            return TableResult(table=table, ok=True, engine="python/advanced", rows=0, stage="done", sync_type=sync_type, primary_key=primary_key, origin_matched_rows=0, deleted_rows=0, inserted_rows=0, skipped_existing_rows=0)
        keys_to_insert = source_keys
        skipped_existing = 0
        if insert_missing:
            stage = "read_dest_keys"
            existing = select_existing_keys(destino, table, primary_key, source_keys, batch_size)
            stage = "filter_missing_keys"
            keys_to_insert = [key for key in source_keys if key not in existing]
            skipped_existing = len(source_keys) - len(keys_to_insert)
        if table_exists(destino, table) and sync_cfg.get("backup_before_replace"):
            stage = "backup_dest"
            backup_table = backup_existing_table(destino, table)

        columns = list(source_columns.keys())
        quoted_cols = ", ".join(quote_identifier(col) for col in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        insert_sql = f"INSERT INTO {quote_identifier(table)} ({quoted_cols}) VALUES ({placeholders})"
        src = get_connection(origem)
        dst = get_connection(destino)
        rows_inserted = 0
        rows_deleted = 0
        dst_cur = None
        try:
            src_cur = src.cursor()
            dst_cur = dst.cursor()
            dst_cur.execute("SET FOREIGN_KEY_CHECKS=0")
            if not insert_missing:
                stage = "delete_dest_keys"
                for batch in chunked(source_keys, batch_size):
                    predicate, params = build_key_predicate(primary_key, batch)
                    dst_cur.execute(f"DELETE FROM {quote_identifier(table)} WHERE {predicate}", params)
                    rows_deleted += int(getattr(dst_cur, "rowcount", 0) or 0)
            stage = "copy_missing_rows" if insert_missing else "copy_rows"
            for batch in chunked(keys_to_insert, batch_size):
                predicate, params = build_key_predicate(primary_key, batch)
                src_cur.execute(f"SELECT {quoted_cols} FROM {quote_identifier(table)} WHERE {predicate}", params)
                rows = src_cur.fetchall()
                if rows:
                    dst_cur.executemany(insert_sql, rows)
                    rows_inserted += len(rows)
            dst.commit()
            stage = "restore_fk"
        finally:
            if dst_cur is not None:
                try:
                    dst_cur.execute("SET FOREIGN_KEY_CHECKS=1")
                    dst.commit()
                except Exception:
                    pass
            src.close()
            dst.close()
        return TableResult(table=table, ok=True, engine="python/advanced", rows=rows_inserted, stage="done", backup_table=backup_table, sync_type=sync_type, primary_key=primary_key, origin_matched_rows=len(source_keys), deleted_rows=rows_deleted, inserted_rows=rows_inserted, skipped_existing_rows=skipped_existing)
    except Exception as exc:  # noqa: BLE001
        return TableResult(table=table, ok=False, engine="python/advanced", message=str(exc), stage=stage, backup_table=backup_table, sync_type=sync_type, primary_key=primary_key or None)


def run_python_sync(config: dict[str, Any], table: str) -> TableResult:
    origem = config["origem"]
    destino = config["destino"]
    sync_cfg = config.get("sync", {})
    batch_size = int(sync_cfg.get("batch_size", 1000))
    stage = "read_source_schema"
    backup_table: str | None = None
    try:
        source_columns = get_columns(origem, table)
        if not source_columns:
            raise SyncError(f"Tabela {table} não encontrada na origem.")
        create_sql = sanitize_create_table(get_create_table(origem, table))
        stage = "ensure_dest_structure"
        ensure_structure(
            destino,
            table,
            create_sql,
            source_columns,
            create_missing=bool(sync_cfg.get("create_missing_tables", True)),
            add_missing_columns=bool(sync_cfg.get("add_missing_columns", True)),
        )
        if table_exists(destino, table) and sync_cfg.get("backup_before_replace"):
            stage = "backup_dest"
            backup_table = backup_existing_table(destino, table)
        columns = list(source_columns.keys())
        quoted_cols = ", ".join(quote_identifier(col) for col in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        select_sql = f"SELECT {quoted_cols} FROM {quote_identifier(table)}"
        insert_sql = f"INSERT INTO {quote_identifier(table)} ({quoted_cols}) VALUES ({placeholders})"

        stage = "connect"
        src = get_connection(origem)
        dst = get_connection(destino)
        rows = 0
        dst_cur = None
        try:
            src_cur = src.cursor()
            dst_cur = dst.cursor()
            stage = "cleanup_dest"
            dst_cur.execute("SET FOREIGN_KEY_CHECKS=0")
            if sync_cfg.get("truncate_before_insert", True):
                dst_cur.execute(f"DELETE FROM {quote_identifier(table)}")
            stage = "copy_rows"
            src_cur.execute(select_sql)
            while True:
                batch = src_cur.fetchmany(batch_size)
                if not batch:
                    break
                dst_cur.executemany(insert_sql, batch)
                rows += len(batch)
            dst.commit()
            stage = "restore_fk"
        finally:
            if dst_cur is not None:
                try:
                    dst_cur.execute("SET FOREIGN_KEY_CHECKS=1")
                    dst.commit()
                except Exception:
                    pass
            src.close()
            dst.close()
        return TableResult(table=table, ok=True, engine="python", rows=rows, stage="done", backup_table=backup_table)
    except Exception as exc:  # noqa: BLE001
        return TableResult(table=table, ok=False, engine="python", message=str(exc), stage=stage, backup_table=backup_table)


def sanitize_create_table(sql: str) -> str:
    return sql.replace("utf8mb4_0900_ai_ci", "utf8mb4_general_ci")
