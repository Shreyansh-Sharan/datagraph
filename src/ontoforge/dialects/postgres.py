"""PostgreSQL dialect. Also the local development warehouse."""
from __future__ import annotations

from pathlib import Path

from .base import SqlDialect

_IRI_ENCODE_SQL = Path(__file__).parent.parent / "db" / "migrations" / "0001_iri_encode.sql"


class PostgresDialect(SqlDialect):
    name = "postgres"

    def quote_identifier(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def string_literal(self, value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def concat(self, parts: list[str]) -> str:
        return parts[0] if len(parts) == 1 else "(" + " || ".join(parts) + ")"

    def to_text(self, expr: str) -> str:
        return f"CAST({expr} AS TEXT)"

    def null_text(self) -> str:
        return "CAST(NULL AS TEXT)"

    def iri_encode(self, expr: str) -> str:
        return f"ontoforge_iri_encode({expr})"

    def create_table_as(self, table_sql: str, select_sql: str) -> list[str]:
        return [f"DROP TABLE IF EXISTS {table_sql}", f"CREATE TABLE {table_sql} AS {select_sql}"]

    def setup_sql(self) -> str:
        """DDL the source database needs before compiled SQL can run (idempotent)."""
        return _IRI_ENCODE_SQL.read_text()

    def xsd_for_sql_type(self, sql_type: str) -> str | None:
        t = sql_type.strip().lower()
        pg = {"integer": "INT", "bigint": "BIGINT", "smallint": "SMALLINT", "numeric": "DECIMAL",
              "double precision": "DOUBLE", "real": "REAL", "boolean": "BOOLEAN", "date": "DATE",
              "timestamp without time zone": "TIMESTAMP", "timestamp with time zone": "TIMESTAMP",
              "time without time zone": "TIME", "bytea": "BINARY"}
        return super().xsd_for_sql_type(pg.get(t, t))
