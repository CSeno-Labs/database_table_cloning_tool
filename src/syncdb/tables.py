from __future__ import annotations

import re
from pathlib import Path

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_$]+(?:\.[A-Za-z0-9_$]+)?$")


def parse_tables(values: list[str] | tuple[str, ...]) -> list[str]:
    tables: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw in re.split(r"[,;\n\r\t]+", value):
            table = raw.strip()
            if table and not table.startswith("#") and table not in seen:
                tables.append(table)
                seen.add(table)
    return tables


def parse_tables_file(path: str | Path) -> list[str]:
    table_lines: list[str] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            table_lines.append(stripped)
    return parse_tables(table_lines)


def quote_identifier(identifier: str) -> str:
    if not identifier or not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Identificador inválido: {identifier!r}")
    return ".".join(f"`{part}`" for part in identifier.split("."))
