from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
import re
from time import perf_counter
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
    timings: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class SchemaDiff:
    table: str
    source_exists: bool
    target_exists: bool
    missing_columns: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()
    changed_columns: tuple[str, ...] = ()
    column_changes: tuple[tuple[str, tuple[str, ...]], ...] = ()
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


@dataclass(frozen=True)
class SchemaPlanOperation:
    action: str
    category: str
    name: str

    @property
    def destructive(self) -> bool:
        return self.action == "drop"


@dataclass(frozen=True)
class SchemaPlan:
    table: str
    action: SchemaAction
    operations: tuple[SchemaPlanOperation, ...]

    @property
    def has_destructive_operations(self) -> bool:
        return any(operation.destructive for operation in self.operations)


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


_FOREIGN_KEY_RE = re.compile(
    r"CONSTRAINT\s+`(?P<name>[^`]+)`\s+FOREIGN\s+KEY\s*\((?P<columns>[^)]+)\)\s+"
    r"REFERENCES\s+`(?P<table>[^`]+)`\s*\((?P<referenced_columns>[^)]+)\)(?P<rules>.*?)"
    r"(?=,\s*(?:CONSTRAINT|KEY|UNIQUE|PRIMARY)|\s*\)|$)",
    re.IGNORECASE | re.DOTALL,
)


def _identifiers_from_sql(value: str) -> tuple[str, ...]:
    return tuple(part.strip().strip("`") for part in value.split(","))


def parse_foreign_keys_from_create(create_sql: str) -> tuple[tuple[Any, ...], ...]:
    foreign_keys = []
    for match in _FOREIGN_KEY_RE.finditer(create_sql):
        rules = match.group("rules")
        update = re.search(r"ON\s+UPDATE\s+(RESTRICT|CASCADE|SET\s+NULL|NO\s+ACTION)", rules, re.IGNORECASE)
        delete = re.search(r"ON\s+DELETE\s+(RESTRICT|CASCADE|SET\s+NULL|NO\s+ACTION)", rules, re.IGNORECASE)
        foreign_keys.append((
            match.group("name"),
            _identifiers_from_sql(match.group("columns")),
            match.group("table"),
            _identifiers_from_sql(match.group("referenced_columns")),
            (update.group(1).upper() if update else "RESTRICT"),
            (delete.group(1).upper() if delete else "RESTRICT"),
        ))
    return tuple(sorted(foreign_keys, key=lambda item: item[0]))


def inspect_schema(config: dict[str, Any], table: str):
    total_started = perf_counter()
    connect_started = perf_counter()
    conn = get_connection(config)
    timings: list[tuple[str, float]] = [("connect", perf_counter() - connect_started)]
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        started = perf_counter()
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
        timings.append(("columns", perf_counter() - started))
        started = perf_counter()
        cursor.execute(f"SHOW INDEX FROM {quote_identifier(table)}")
        indexes = _group_indexes(cursor.fetchall())
        timings.append(("indexes", perf_counter() - started))
        table_name = table.split(".")[-1]
        started = perf_counter()
        cursor.execute(f"SHOW CREATE TABLE {quote_identifier(table)}")
        create_row = cursor.fetchone() or {}
        create_sql = create_row.get("Create Table", "") if isinstance(create_row, dict) else create_row[1]
        foreign_keys = parse_foreign_keys_from_create(str(create_sql))
        timings.append(("foreign_keys", perf_counter() - started))
        started = perf_counter()
        cursor.execute(
            "SELECT ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (table_name,),
        )
        options_row = cursor.fetchone() or {}
        table_options = tuple((key, str(options_row.get(key.upper()) or "")) for key in ("engine", "table_collation"))
        timings.append(("table_options", perf_counter() - started))
        timings.append(("total", perf_counter() - total_started))
        return SchemaSnapshot(table=table, exists=True, columns=columns, indexes=indexes, foreign_keys=foreign_keys, table_options=table_options, timings=tuple(timings))
    except Exception as exc:
        message = str(exc).lower()
        if "doesn't exist" in message or "does not exist" in message or "unknown table" in message:
            return SchemaSnapshot(table=table, exists=False)
        raise
    finally:
        if cursor is not None:
            _close(cursor)
        conn.close()


def inspect_schema_pair(source_config: dict[str, Any], target_config: dict[str, Any], table: str) -> tuple[SchemaSnapshot, SchemaSnapshot]:
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="syncdb-schema") as executor:
        source_future = executor.submit(inspect_schema, source_config, table)
        target_future = executor.submit(inspect_schema, target_config, table)
        return source_future.result(), target_future.result()


def _compare_named(source: tuple[tuple[Any, ...], ...], target: tuple[tuple[Any, ...], ...]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    source_map = {str(item[0]): item for item in source}
    target_map = {str(item[0]): item for item in target}
    missing = tuple(sorted(name for name in source_map if name not in target_map))
    extra = tuple(sorted(name for name in target_map if name not in source_map))
    changed = tuple(sorted(name for name in source_map.keys() & target_map.keys() if source_map[name] != target_map[name]))
    return missing, extra, changed


def _column_change_reasons(source: tuple[Any, ...], target: tuple[Any, ...]) -> tuple[str, ...]:
    labels = ("type", "nullable", "default", "extra", "collation")
    return tuple(label for index, label in enumerate(labels, 1) if source[index] != target[index])


def _compare_columns(source: tuple[tuple[Any, ...], ...], target: tuple[tuple[Any, ...], ...]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    source_map = {str(item[0]): item for item in source}
    target_map = {str(item[0]): item for item in target}
    missing = tuple(sorted(name for name in source_map if name not in target_map))
    extra = tuple(sorted(name for name in target_map if name not in source_map))
    shared = source_map.keys() & target_map.keys()
    column_changes = tuple(sorted((name, _column_change_reasons(source_map[name], target_map[name])) for name in shared if source_map[name][1:-1] != target_map[name][1:-1]))
    changed = tuple(name for name, _ in column_changes)
    reordered = tuple(sorted(name for name in shared if source_map[name][-1] != target_map[name][-1]))
    return missing, extra, changed, reordered, column_changes


def compare_schema(source: SchemaSnapshot, target: SchemaSnapshot) -> SchemaDiff:
    if not source.exists or not target.exists:
        return SchemaDiff(table=source.table, source_exists=source.exists, target_exists=target.exists)
    missing_columns, extra_columns, changed_columns, reordered_columns, column_changes = _compare_columns(source.columns, target.columns)
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
        column_changes=column_changes,
        reordered_columns=reordered_columns,
        missing_indexes=missing_indexes,
        extra_indexes=extra_indexes,
        changed_indexes=changed_indexes,
        missing_foreign_keys=missing_foreign_keys,
        extra_foreign_keys=extra_foreign_keys,
        changed_foreign_keys=changed_foreign_keys,
        changed_table_options=changed_options,
    )


def build_schema_plan(diff: SchemaDiff, action: SchemaAction | str) -> SchemaPlan:
    action = normalize_schema_action(action.value if isinstance(action, SchemaAction) else action)
    if action not in {SchemaAction.COPY, SchemaAction.UPDATE}:
        raise ValueError("Plano automático suporta apenas copy ou update.")
    if not diff.source_exists or not diff.target_exists:
        raise ValueError("Não é possível gerar plano automático quando a tabela não existe nos dois bancos.")

    operations: list[SchemaPlanOperation] = []
    for name in diff.missing_columns:
        operations.append(SchemaPlanOperation("add", "column", name))
    for name in diff.changed_columns:
        operations.append(SchemaPlanOperation("modify", "column", name))
    for name in diff.reordered_columns:
        operations.append(SchemaPlanOperation("move", "column", name))
    for name in diff.extra_columns:
        operations.append(SchemaPlanOperation("drop" if action == SchemaAction.COPY else "preserve", "column", name))

    for name in diff.missing_indexes:
        operations.append(SchemaPlanOperation("add", "index", name))
    for name in diff.changed_indexes:
        operations.append(SchemaPlanOperation("replace", "index", name))
    for name in diff.extra_indexes:
        operations.append(SchemaPlanOperation("drop" if action == SchemaAction.COPY else "preserve", "index", name))

    for name in diff.missing_foreign_keys:
        operations.append(SchemaPlanOperation("add", "foreign_key", name))
    for name in diff.changed_foreign_keys:
        operations.append(SchemaPlanOperation("replace", "foreign_key", name))
    for name in diff.extra_foreign_keys:
        operations.append(SchemaPlanOperation("drop" if action == SchemaAction.COPY else "preserve", "foreign_key", name))

    for name in diff.changed_table_options:
        operations.append(SchemaPlanOperation("modify", "table_option", name))
    return SchemaPlan(table=diff.table, action=action, operations=tuple(operations))
