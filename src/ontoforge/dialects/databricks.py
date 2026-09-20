"""Spark SQL as spoken by Databricks SQL Warehouses."""
from __future__ import annotations

from .base import SqlDialect


class DatabricksDialect(SqlDialect):
    name = "databricks"

    def quote_identifier(self, name: str) -> str:
        return "`" + name.replace("`", "``") + "`"

    def string_literal(self, value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def concat(self, parts: list[str]) -> str:
        return parts[0] if len(parts) == 1 else "concat(" + ", ".join(parts) + ")"

    def to_text(self, expr: str) -> str:
        return f"CAST({expr} AS STRING)"

    def null_text(self) -> str:
        return "CAST(NULL AS STRING)"

    def iri_encode(self, expr: str) -> str:
        # url_encode() is form-encoding (space -> '+'); IRIs want '%20'.
        return f"replace(url_encode({expr}), '+', '%20')"
