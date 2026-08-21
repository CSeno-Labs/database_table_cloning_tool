from __future__ import annotations

from enum import StrEnum


class SchemaAction(StrEnum):
    DIFF = "diff"
    COPY = "copy"
    UPDATE = "update"
    RECREATE_TABLE = "recreate-table"


_SCHEMA_ACTIONS = {action.value: action for action in SchemaAction}


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
    if action == SchemaAction.RECREATE_TABLE:
        return "recreate-table: recria a tabela do destino com a estrutura da origem"
    return action.value
