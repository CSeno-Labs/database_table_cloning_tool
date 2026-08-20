from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SchemaMode(StrEnum):
    BASIC = "basic"
    ADD = "add"
    COPY = "copy"
    RECREATE_TABLE = "recreate-table"


SCHEMA_INCLUDE_CATEGORIES = (
    "columns",
    "indexes",
    "keys",
    "foreign-keys",
    "table-options",
)

_SCHEMA_MODE_ALIASES = {
    "b": SchemaMode.BASIC,
    "basic": SchemaMode.BASIC,
    "a": SchemaMode.ADD,
    "add": SchemaMode.ADD,
    "additive": SchemaMode.ADD,
    "c": SchemaMode.COPY,
    "copy": SchemaMode.COPY,
    "recreate-table": SchemaMode.RECREATE_TABLE,
}


@dataclass(frozen=True)
class SchemaOptions:
    mode: SchemaMode
    include: tuple[str, ...]


def normalize_schema_mode(value: str | None) -> SchemaMode:
    raw = (value or "basic").strip().lower()
    if raw in _SCHEMA_MODE_ALIASES:
        return _SCHEMA_MODE_ALIASES[raw]
    raise ValueError("Modo de schema inválido. Use b/basic, a/add/additive, c/copy ou recreate-table.")


def normalize_schema_include(value: str | None) -> tuple[str, ...]:
    raw = (value or "").strip().lower()
    if not raw:
        return ()
    selected: list[str] = []
    for item in raw.split(","):
        category = item.strip()
        if not category:
            continue
        if category == "all":
            for known in SCHEMA_INCLUDE_CATEGORIES:
                if known not in selected:
                    selected.append(known)
            continue
        if category not in SCHEMA_INCLUDE_CATEGORIES:
            raise ValueError(
                "Categoria de schema inválida. Use columns,indexes,keys,foreign-keys,table-options ou all."
            )
        if category not in selected:
            selected.append(category)
    return tuple(selected)


def default_include_for_mode(mode: SchemaMode) -> tuple[str, ...]:
    if mode in {SchemaMode.BASIC, SchemaMode.ADD}:
        return ("columns",)
    if mode == SchemaMode.COPY:
        return SCHEMA_INCLUDE_CATEGORIES
    return ()


def resolve_schema_options(mode_value: str | None, include_value: str | None = None) -> SchemaOptions:
    mode = normalize_schema_mode(mode_value)
    include = normalize_schema_include(include_value)
    if include and mode == SchemaMode.BASIC:
        raise ValueError("O modo basic não aceita --include; ele sempre adiciona apenas colunas faltantes.")
    if include and mode == SchemaMode.RECREATE_TABLE:
        raise ValueError("O modo recreate-table não aceita --include; ele sempre recria a estrutura completa da tabela.")
    if not include:
        include = default_include_for_mode(mode)
    return SchemaOptions(mode=mode, include=include)


def describe_schema_options(options: SchemaOptions) -> str:
    include = ", ".join(options.include) if options.include else "estrutura completa"
    return f"mode={options.mode.value}; include={include}"
