from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from secrets import token_hex
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
    details: tuple[str, ...] = ()
    sql: str = ""

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


@dataclass(frozen=True)
class SchemaExecutionReport:
    applied: tuple[str, ...] = ()
    failed: str | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.failed is None


@dataclass(frozen=True)
class RecreateTableReport:
    applied: tuple[str, ...] = ()
    backup_table: str | None = None
    failed: str | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.failed is None


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


_CREATE_TABLE_IDENTIFIER_RE = re.compile(
    r"(?P<prefix>^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)"
    r"(?P<identifier>`(?:[^`]|``)+`(?:\.`(?:[^`]|``)+`)?|[A-Za-z0-9_$]+(?:\.[A-Za-z0-9_$]+)?)",
    re.IGNORECASE,
)


def rewrite_create_table_identifier(create_sql: str, target_table: str) -> str:
    """Replace only SHOW CREATE TABLE's leading table identifier."""
    target = quote_identifier(target_table)
    rewritten, count = _CREATE_TABLE_IDENTIFIER_RE.subn(rf"\g<prefix>{target}", create_sql, count=1)
    if count != 1:
        raise ValueError("SHOW CREATE TABLE não retornou uma instrução CREATE TABLE válida.")
    return rewritten


def _create_sql_from_row(row: Any) -> str:
    if isinstance(row, dict):
        value = row.get("Create Table")
    elif isinstance(row, (tuple, list)) and len(row) > 1:
        value = row[1]
    else:
        value = None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("SHOW CREATE TABLE não retornou a estrutura da tabela de origem.")
    return value


def _recreate_name(table: str, suffix: str) -> str:
    parts = table.split(".")
    return ".".join((*parts[:-1], f"{parts[-1]}_{suffix}"))


def execute_recreate_table(
    source_config: dict[str, Any],
    target_config: dict[str, Any],
    table: str,
    *,
    keep_backup: bool = False,
    temporary_name: str | None = None,
    backup_name: str | None = None,
) -> RecreateTableReport:
    """Recreate a destination table using an atomic two-table rename.

    The source DDL is created under a unique temporary name first.  The old
    target is then renamed away in the same RENAME TABLE statement that puts
    the new table in place, so a failed CREATE never destroys the target.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique = token_hex(4)
    temporary_name = temporary_name or _recreate_name(table, f"syncdb_recreate_tmp_{stamp}_{unique}")
    backup_name = backup_name or _recreate_name(table, f"syncdb_backup_{stamp}_{unique}")
    source_connection = source_config.get("connection") or get_connection(source_config)
    target_connection = target_config.get("connection") or get_connection(target_config)
    source_cursor = target_cursor = None
    applied: list[str] = []
    current = ""
    swapped = False
    try:
        source_cursor = source_connection.cursor()
        current = f"SHOW CREATE TABLE {quote_identifier(table)}"
        source_cursor.execute(current)
        create_sql = rewrite_create_table_identifier(_create_sql_from_row(source_cursor.fetchone()), temporary_name)

        target_cursor = target_connection.cursor()
        current = create_sql
        target_cursor.execute(current)
        applied.append(current)
        current = (
            f"RENAME TABLE {quote_identifier(table)} TO {quote_identifier(backup_name)}, "
            f"{quote_identifier(temporary_name)} TO {quote_identifier(table)}"
        )
        target_cursor.execute(current)
        applied.append(current)
        swapped = True
        if not keep_backup:
            current = f"DROP TABLE {quote_identifier(backup_name)}"
            target_cursor.execute(current)
            applied.append(current)
        commit = getattr(target_connection, "commit", None)
        if commit:
            commit()
        return RecreateTableReport(tuple(applied), backup_name if keep_backup else None)
    except Exception as exc:  # noqa: BLE001 - report the exact failed database statement
        return RecreateTableReport(tuple(applied), backup_name if swapped else None, current or None, str(exc))
    finally:
        if source_cursor is not None:
            _close(source_cursor)
        if target_cursor is not None:
            _close(target_cursor)
        if source_connection is target_connection:
            source_connection.close()
        else:
            source_connection.close()
            target_connection.close()


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


def _column_move_plan(source_names: list[str], target_names: list[str], shared: set[str]) -> tuple[tuple[str, str | None], ...]:
    """Move shared columns into source order while simulating every move."""
    simulated = list(target_names)
    moves: list[tuple[str, str | None]] = []
    for source_position, name in enumerate(source_names):
        if name not in shared:
            continue
        after = source_names[source_position - 1] if source_position else None
        current_position = simulated.index(name)
        expected_position = simulated.index(after) + 1 if after is not None else 0
        if current_position == expected_position:
            continue
        simulated.pop(current_position)
        simulated.insert(simulated.index(after) + 1 if after is not None else 0, name)
        moves.append((name, after))
    return tuple(moves)


def _target_order_after_additions(source_names: list[str], target_names: list[str]) -> list[str]:
    """Simulate source-order ADD COLUMN operations before planning moves."""
    simulated = list(target_names)
    for position, name in enumerate(source_names):
        if name in simulated:
            continue
        if position:
            simulated.insert(simulated.index(source_names[position - 1]) + 1, name)
        else:
            simulated.insert(0, name)
    return simulated


def _compare_columns(source: tuple[tuple[Any, ...], ...], target: tuple[tuple[Any, ...], ...]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    source_map = {str(item[0]): item for item in source}
    target_map = {str(item[0]): item for item in target}
    missing = tuple(sorted(name for name in source_map if name not in target_map))
    extra = tuple(sorted(name for name in target_map if name not in source_map))
    shared = source_map.keys() & target_map.keys()
    column_changes = tuple(sorted((name, _column_change_reasons(source_map[name], target_map[name])) for name in shared if source_map[name][1:-1] != target_map[name][1:-1]))
    changed = tuple(name for name, _ in column_changes)
    source_order = tuple(str(item[0]) for item in source if str(item[0]) in shared)
    target_order = tuple(str(item[0]) for item in target if str(item[0]) in shared)
    reordered = tuple(name for name, _ in _column_move_plan(list(source_order), list(target_order), set(shared)))
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


def _column_description(column: tuple[Any, ...]) -> str:
    _, column_type, nullable, default, extra, collation, _ = column
    text = f"{str(column_type).upper()} {'NULL' if nullable == 'YES' else 'NOT NULL'}"
    if default is not None:
        text += f" DEFAULT {default!r}"
    if extra:
        text += f" {extra.upper()}"
    if collation:
        text += f" COLLATE {collation}"
    return text


def _column_sql(column: tuple[Any, ...]) -> str:
    _, column_type, nullable, default, extra, collation, _ = column
    text = f"{str(column_type).upper()} {'NULL' if nullable == 'YES' else 'NOT NULL'}"
    if default is not None:
        if isinstance(default, str) and default.upper().startswith("CURRENT_"):
            text += f" DEFAULT {default}"
        else:
            text += f" DEFAULT {default!r}"
    if extra:
        text += f" {extra.upper()}"
    if collation:
        text += f" COLLATE {collation}"
    return text


def build_schema_plan(diff: SchemaDiff, action: SchemaAction | str, *, source: SchemaSnapshot | None = None, target: SchemaSnapshot | None = None) -> SchemaPlan:
    action = normalize_schema_action(action.value if isinstance(action, SchemaAction) else action)
    if action not in {SchemaAction.COPY, SchemaAction.UPDATE}:
        raise ValueError("Plano automático suporta apenas copy ou update.")
    if not diff.source_exists or not diff.target_exists:
        raise ValueError("Não é possível gerar plano automático quando a tabela não existe nos dois bancos.")

    operations: list[SchemaPlanOperation] = []
    source_columns = {str(column[0]): column for column in (source.columns if source else ())}
    target_columns = {str(column[0]): column for column in (target.columns if target else ())}
    source_names = [str(column[0]) for column in source.columns] if source else []
    target_names = [str(column[0]) for column in target.columns] if target else []
    shared_columns = set(source_columns) & set(target_columns)
    for name in (name for name in source_names if name in diff.missing_columns):
        details = []
        position = source_names.index(name)
        if name in source_columns:
            details.append(_column_description(source_columns[name]))
            details.append(f"depois de {source_names[position - 1]}" if position else "primeira coluna")
        after_sql = f" AFTER {quote_identifier(source_names[position - 1])}" if position else " FIRST"
        sql = f"ALTER TABLE {quote_identifier(diff.table)} ADD COLUMN {quote_identifier(name)} {_column_sql(source_columns[name])}{after_sql};" if name in source_columns else ""
        operations.append(SchemaPlanOperation("add", "column", name, tuple(details), sql))
    for name in diff.changed_columns:
        details = ()
        if name in source_columns and name in target_columns:
            details = (f"destino: {_column_description(target_columns[name])}", f"origem: {_column_description(source_columns[name])}")
        sql = f"ALTER TABLE {quote_identifier(diff.table)} MODIFY COLUMN {quote_identifier(name)} {_column_sql(source_columns[name])};" if name in source_columns else ""
        operations.append(SchemaPlanOperation("modify", "column", name, details, sql))
    move_target_names = _target_order_after_additions(source_names, target_names)
    for name, source_after in _column_move_plan(source_names, move_target_names, shared_columns):
        details = ()
        sql = ""
        if name in source_columns:
            source_after_label = source_after or "início"
            details = (f"origem: depois de {source_after_label}",)
            after_sql = f" AFTER {quote_identifier(source_after)}" if source_after else " FIRST"
            sql = f"ALTER TABLE {quote_identifier(diff.table)} MODIFY COLUMN {quote_identifier(name)} {_column_sql(source_columns[name])}{after_sql};"
        operations.append(SchemaPlanOperation("move", "column", name, details, sql))
    for name in diff.extra_columns:
        operation = "drop" if action == SchemaAction.COPY else "preserve"
        sql = f"ALTER TABLE {quote_identifier(diff.table)} DROP COLUMN {quote_identifier(name)};" if operation == "drop" else ""
        operations.append(SchemaPlanOperation(operation, "column", name, (), sql))

    source_indexes = {str(index[0]): index for index in (source.indexes if source else ())}
    source_fks = {str(fk[0]): fk for fk in (source.foreign_keys if source else ())}
    def index_add(index):
        name, unique, columns = index
        cols = ", ".join(quote_identifier(str(c)) for c in columns)
        if name == "PRIMARY": return f"ALTER TABLE {quote_identifier(diff.table)} ADD PRIMARY KEY ({cols});"
        return f"ALTER TABLE {quote_identifier(diff.table)} ADD {'UNIQUE INDEX' if unique else 'INDEX'} {quote_identifier(str(name))} ({cols});"
    def index_drop(name):
        return f"ALTER TABLE {quote_identifier(diff.table)} {'DROP PRIMARY KEY' if name == 'PRIMARY' else 'DROP INDEX ' + quote_identifier(name)};"
    for name in diff.missing_indexes:
        index = source_indexes.get(name)
        operations.append(SchemaPlanOperation("add", "index", name, (f"origem: ({', '.join(index[2])})",) if index else (), index_add(index) if index else ""))
    for name in diff.changed_indexes:
        index = source_indexes.get(name)
        operations.append(SchemaPlanOperation("replace", "index", name, (), f"{index_drop(name)}\n{index_add(index)}" if index else ""))
    for name in diff.extra_indexes:
        op = "drop" if action == SchemaAction.COPY else "preserve"
        operations.append(SchemaPlanOperation(op, "index", name, (), index_drop(name) if op == "drop" else ""))

    def fk_add(fk):
        name, columns, ref_table, ref_columns, update, delete = fk
        cols = ", ".join(quote_identifier(str(c)) for c in columns)
        refs = ", ".join(quote_identifier(str(c)) for c in ref_columns)
        return f"ALTER TABLE {quote_identifier(diff.table)} ADD CONSTRAINT {quote_identifier(str(name))} FOREIGN KEY ({cols}) REFERENCES {quote_identifier(str(ref_table))} ({refs}) ON UPDATE {update} ON DELETE {delete};"
    for name in diff.missing_foreign_keys:
        fk = source_fks.get(name)
        operations.append(SchemaPlanOperation("add", "foreign_key", name, (), fk_add(fk) if fk else ""))
    for name in diff.changed_foreign_keys:
        fk = source_fks.get(name)
        operations.append(SchemaPlanOperation("replace", "foreign_key", name, (), f"ALTER TABLE {quote_identifier(diff.table)} DROP FOREIGN KEY {quote_identifier(name)};\n{fk_add(fk)}" if fk else ""))
    for name in diff.extra_foreign_keys:
        op = "drop" if action == SchemaAction.COPY else "preserve"
        operations.append(SchemaPlanOperation(op, "foreign_key", name, (), f"ALTER TABLE {quote_identifier(diff.table)} DROP FOREIGN KEY {quote_identifier(name)};" if op == "drop" else ""))

    source_options = dict(source.table_options) if source else {}
    for name in diff.changed_table_options:
        value = source_options.get(name, "")
        sql = f"ALTER TABLE {quote_identifier(diff.table)} ENGINE={value};" if name == "engine" else f"ALTER TABLE {quote_identifier(diff.table)} DEFAULT COLLATE {value};"
        operations.append(SchemaPlanOperation("modify", "table_option", name, (f"origem: {value}",), sql))
    return SchemaPlan(table=diff.table, action=action, operations=tuple(operations))


def _operation_statements(operation: SchemaPlanOperation) -> tuple[str, ...]:
    """Return the single statements encoded in a planned operation.

    Plan SQL is generated internally and may contain a drop/add pair for a
    replacement.  It is deliberately never submitted as a multi-statement
    query so an error can be reported at the exact failing statement.
    """
    statements: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for character in operation.sql:
        current.append(character)
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif quote:
            if character == quote:
                quote = ""
        elif character in {"'", '"', "`"}:
            quote = character
        elif character == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)
    return tuple(statements)


def _execution_statements(plan: SchemaPlan) -> tuple[str, ...]:
    operations = [operation for operation in plan.operations if operation.action != "preserve" and operation.sql]

    def statements(category: str, actions: set[str], *, drops: bool | None = None) -> list[str]:
        selected: list[str] = []
        for operation in operations:
            if operation.category != category or operation.action not in actions:
                continue
            for statement in _operation_statements(operation):
                is_drop = " DROP " in f" {statement.upper()} "
                if drops is None or is_drop == drops:
                    selected.append(statement)
        return selected

    # Constraints and indexes must be removed before dependent columns.  The
    # inverse order applies when rebuilding them.  In copy mode this also
    # ensures destination-only columns are dropped only after their FK/index.
    ordered = [
        *statements("foreign_key", {"drop", "replace"}, drops=True),
        *statements("index", {"drop", "replace"}, drops=True),
        *statements("column", {"add", "modify", "move"}),
        *statements("column", {"drop"}),
        *statements("table_option", {"modify"}),
        *statements("index", {"add", "replace"}, drops=False),
        *statements("foreign_key", {"add", "replace"}, drops=False),
    ]
    return tuple(ordered)


def execute_schema_plan(target_config: dict[str, Any], plan: SchemaPlan) -> SchemaExecutionReport:
    """Execute a freshly reviewed plan, one SQL statement at a time."""
    connection = target_config.get("connection") or get_connection(target_config)
    cursor = None
    applied: list[str] = []
    try:
        cursor = connection.cursor()
        for statement in _execution_statements(plan):
            try:
                cursor.execute(statement)
            except Exception as exc:  # noqa: BLE001 - return the database error to the CLI
                return SchemaExecutionReport(tuple(applied), statement, str(exc))
            applied.append(statement)
        commit = getattr(connection, "commit", None)
        if commit:
            commit()
        return SchemaExecutionReport(tuple(applied))
    finally:
        if cursor is not None:
            _close(cursor)
        connection.close()
