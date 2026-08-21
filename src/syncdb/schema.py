from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .db import get_connection
from .tables import quote_identifier


class SchemaAction(StrEnum):
    DIFF = "diff"
    COPY = "copy"
    UPDATE = "update"
    RECREATE_TABLE = "recreate-table"


_SCHEMA_ACTIONS = {action.value: action for action in SchemaAction}


@dataclass(frozen=True)
class SchemaSnapshot:
    table: str
    exists: bool
    columns: tuple[tuple[Any, ...], ...] = ()
    indexes: tuple[tuple[Any, ...], ...] = ()
    foreign_keys: tuple[tuple[Any, ...], ...] = ()
    table_options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SchemaDiff:
    table: str
    source_exists: bool
    target_exists: bool
    missing_columns: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()
    changed_columns: tuple[str, ...] = ()
    reordered_columns: tuple[str, ...] = ()
    missing_indexes: tuple[str, ...] = ()
    extra_indexes: tuple[str, ...] = ()
    changed_indexes: tuple[str, ...] = ()
    missing_foreign_keys: tuple[str, ...] = ()
    extra_foreign_keys: tuple[str, ...] = ()
    changed_foreign_keys: tuple[str, ...] = ()
    changed_table_options: tuple[str, ...] = ()

    @property
    def is_equal(self) -> bool:
        return not any((
            not self.source_exists,
            not self.target_exists,
            self.missing_columns,
            self.extra_columns,
            self.changed_columns,
            self.reordered_columns,
            self.missing_indexes,
            self.extra_indexes,
            self.changed_indexes,
            self.missing_foreign_keys,
            self.extra_foreign_keys,
            self.changed_foreign_keys,
            self.changed_table_options,
        ))


def normalize_schema_action(value: str | None) -> SchemaAction:
    raw = (value or "diff").strip().lower()
    if raw in _SCHEMA_ACTIONS:
        return _SCHEMA_ACTIONS[raw]
    raise ValueError("Ação de schema inválida. Use diff, copy, update ou recreate-table.")


def describe_schema_action(action: SchemaAction) -> str:
    if action == SchemaAction.DIFF:
        return "diff: mostra diferenças sem alterar nada"
    if action == SchemaAction.COPY:
        return "copy: copia estrutura da origem para o destino; pode adicionar, alterar e remover"
    if action == SchemaAction.UPDATE:
        return "update: copia estrutura preservando extras do destino; pode adicionar e alterar, mas não remove extras"
    return "recreate-table: recria a tabela do destino com a estrutura da origem"


def _close(cursor: Any) -> None:
    close = getattr(cursor, "close", None)
    if close:
        close()


def _group_indexes(rows: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["Key_name"])].append(row)
    result = []
    for name, entries in grouped.items():
        entries.sort(key=lambda row: int(row.get("Seq_in_index") or 0))
        result.append((name, not bool(entries[0].get("Non_unique")), tuple(str(row["Column_name"]) for row in entries)))
    return tuple(sorted(result, key=lambda item: item[0]))


def _group_foreign_keys(rows: list[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["CONSTRAINT_NAME"])].append(row)
    result = []
    for name, entries in grouped.items():
        entries.sort(key=lambda row: int(row.get("ORDINAL_POSITION") or 0))
        first = entries[0]
        result.append((
            name,
            tuple(str(row["COLUMN_NAME"]) for row in entries),
            str(first["REFERENCED_TABLE_NAME"]),
            tuple(str(row["REFERENCED_COLUMN_NAME"]) for row in entries),
            str(first.get("UPDATE_RULE") or ""),
            str(first.get("DELETE_RULE") or ""),
        ))
    return tuple(sorted(result, key=lambda item: item[0]))


def inspect_schema(config: dict[str, Any], table: str) -> SchemaSnapshot:
    conn = get_connection(config)
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SHOW FULL COLUMNS FROM {quote_identifier(table)}")
        columns = tuple(
            (
                str(row["Field"]),
                str(row.get("Type") or ""),
                str(row.get("Null") or ""),
                row.get("Default"),
                str(row.get("Extra") or ""),
                row.get("Collation"),
                int(row.get("Ordinal") or index),
            )
            for index, row in enumerate(cursor.fetchall(), 1)
        )
        cursor.execute(f"SHOW INDEX FROM {quote_identifier(table)}")
        indexes = _group_indexes(cursor.fetchall())
        table_name = table.split(".")[-1]
        cursor.execute(
            "SELECT k.CONSTRAINT_NAME, k.COLUMN_NAME, k.REFERENCED_TABLE_NAME, "
            "k.REFERENCED_COLUMN_NAME, rc.UPDATE_RULE, rc.DELETE_RULE, k.ORDINAL_POSITION "
            "FROM information_schema.KEY_COLUMN_USAGE k "
            "JOIN information_schema.REFERENTIAL_CONSTRAINTS rc "
            "ON rc.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA AND rc.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
            "WHERE k.TABLE_SCHEMA = DATABASE() AND k.TABLE_NAME = %s "
            "AND k.REFERENCED_TABLE_NAME IS NOT NULL",
            (table_name,),
        )
        foreign_keys = _group_foreign_keys(cursor.fetchall())
        cursor.execute(
            "SELECT ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (table_name,),
        )
        options_row = cursor.fetchone() or {}
        table_options = tuple((key, str(options_row.get(key.upper()) or "")) for key in ("engine", "table_collation"))
        return SchemaSnapshot(table=table, exists=True, columns=columns, indexes=indexes, foreign_keys=foreign_keys, table_options=table_options)
    except Exception as exc:
        message = str(exc).lower()
        if "doesn't exist" in message or "does not exist" in message or "unknown table" in message:
            return SchemaSnapshot(table=table, exists=False)
        raise
    finally:
        if cursor is not None:
            _close(cursor)
        conn.close()


def _compare_named(source: tuple[tuple[Any, ...], ...], target: tuple[tuple[Any, ...], ...]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    source_map = {str(item[0]): item for item in source}
    target_map = {str(item[0]): item for item in target}
    missing = tuple(sorted(name for name in source_map if name not in target_map))
    extra = tuple(sorted(name for name in target_map if name not in source_map))
    changed = tuple(sorted(name for name in source_map.keys() & target_map.keys() if source_map[name] != target_map[name]))
    return missing, extra, changed


def _compare_columns(source: tuple[tuple[Any, ...], ...], target: tuple[tuple[Any, ...], ...]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    source_map = {str(item[0]): item for item in source}
    target_map = {str(item[0]): item for item in target}
    missing = tuple(sorted(name for name in source_map if name not in target_map))
    extra = tuple(sorted(name for name in target_map if name not in source_map))
    shared = source_map.keys() & target_map.keys()
    changed = tuple(sorted(name for name in shared if source_map[name][1:-1] != target_map[name][1:-1]))
    reordered = tuple(sorted(name for name in shared if source_map[name][-1] != target_map[name][-1]))
    return missing, extra, changed, reordered


def compare_schema(source: SchemaSnapshot, target: SchemaSnapshot) -> SchemaDiff:
    if not source.exists or not target.exists:
        return SchemaDiff(table=source.table, source_exists=source.exists, target_exists=target.exists)
    missing_columns, extra_columns, changed_columns, reordered_columns = _compare_columns(source.columns, target.columns)
    missing_indexes, extra_indexes, changed_indexes = _compare_named(source.indexes, target.indexes)
    missing_foreign_keys, extra_foreign_keys, changed_foreign_keys = _compare_named(source.foreign_keys, target.foreign_keys)
    source_options = dict(source.table_options)
    target_options = dict(target.table_options)
    changed_options = tuple(sorted(key for key in source_options.keys() | target_options.keys() if source_options.get(key) != target_options.get(key)))
    return SchemaDiff(
        table=source.table,
        source_exists=True,
        target_exists=True,
        missing_columns=missing_columns,
        extra_columns=extra_columns,
        changed_columns=changed_columns,
        reordered_columns=reordered_columns,
        missing_indexes=missing_indexes,
        extra_indexes=extra_indexes,
        changed_indexes=changed_indexes,
        missing_foreign_keys=missing_foreign_keys,
        extra_foreign_keys=extra_foreign_keys,
        changed_foreign_keys=changed_foreign_keys,
        changed_table_options=changed_options,
    )
