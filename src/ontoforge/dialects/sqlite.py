"""SQLite dialect. Used for in-process end-to-end tests and as the reference ANSI-ish target.

SQLite has no percent-encoding function; ``register_functions`` installs one on a connection.
"""
from __future__ import annotations

import sqlite3
from urllib.parse import quote

from .base import SqlDialect


def iri_safe(value: str | None) -> str | None:
    # R2RML §7.3: percent-encode everything outside the iunreserved set.
    return None if value is None else quote(str(value), safe="-._~")


def register_functions(conn: sqlite3.Connection) -> None:
    conn.create_function("iri_encode", 1, iri_safe, deterministic=True)


class SQLiteDialect(SqlDialect):
    name = "sqlite"

    def quote_identifier(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def string_literal(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def concat(self, parts: list[str]) -> str:
        return parts[0] if len(parts) == 1 else "(" + " || ".join(parts) + ")"

    def to_text(self, expr: str) -> str:
        return f"CAST({expr} AS TEXT)"

    def iri_encode(self, expr: str) -> str:
        return f"iri_encode({expr})"
