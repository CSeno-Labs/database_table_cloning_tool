from __future__ import annotations

import re
from pathlib import Path

from .i18n import t


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_$]+(?:\.[A-Za-z0-9_$]+)?$")


def parse_table_selection_input(value: str) -> tuple[list[str], str | None]:
    """Parse the interactive table field, preserving escapes in a --like pattern."""
    stripped = value.strip()
    if stripped == "--like" or stripped.startswith("--like "):
        raw_pattern = stripped[len("--like"):].strip()
        if not raw_pattern:
            raise ValueError("--like requires a pattern")
        if raw_pattern[0] in {"'", chr(34)}:
            quote = raw_pattern[0]
            if len(raw_pattern) < 2 or raw_pattern[-1] != quote:
                raise ValueError("--like pattern has an unclosed quote")
            pattern = raw_pattern[1:-1]
        else:
            if any(char.isspace() for char in raw_pattern):
                raise ValueError("--like accepts one pattern; quote it if needed")
            pattern = raw_pattern
        if not pattern:
            raise ValueError("--like requires a non-empty pattern")
        return [], pattern
    return parse_tables([value]), None


def table_name_matches_pattern(pattern: str, table_name: str) -> bool:
    """Match a table name using LIKE wildcards, plus ``*`` as a ``%`` alias."""
    regex_parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 1
            if index >= len(pattern):
                raise ValueError("table pattern ends with an escape character")
            regex_parts.append(re.escape(pattern[index]))
        elif char in {"%", "*"}:
            regex_parts.append("[\\s\\S]*")
        elif char == "_":
            regex_parts.append("[\\s\\S]")
        else:
            regex_parts.append(re.escape(char))
        index += 1
    return re.fullmatch("".join(regex_parts), table_name) is not None


def expand_table_pattern(pattern: str, table_names: list[str]) -> list[str]:
    """Return source table names matching a LIKE-style pattern."""
    return [name for name in table_names if table_name_matches_pattern(pattern, name)]


def parse_tables(values: list[str] | tuple[str, ...]) -> list[str]:
    tables: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw in re.split(r"[,;\s]+", value):
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
        raise ValueError(t("tables.invalid_identifier", identifier=repr(identifier)))
    return ".".join(f"`{part}`" for part in identifier.split("."))
