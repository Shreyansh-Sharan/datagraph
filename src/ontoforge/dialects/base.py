"""The SQL dialect port. A dialect knows how to spell primitives; the compiler decides what to say.

Every warehouse is one implementation of this interface. Nothing in the compiler may
reference a concrete warehouse.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

XSD = "http://www.w3.org/2001/XMLSchema#"


class SqlDialect(ABC):
    name: str

    @abstractmethod
    def quote_identifier(self, name: str) -> str: ...

    @abstractmethod
    def string_literal(self, value: str) -> str: ...

    @abstractmethod
    def concat(self, parts: list[str]) -> str: ...

    @abstractmethod
    def to_text(self, expr: str) -> str: ...

    @abstractmethod
    def iri_encode(self, expr: str) -> str:
        """Percent-encode a text expression for safe use inside an IRI template (R2RML §7.3)."""

    def create_table_as(self, table_sql: str, select_sql: str) -> list[str]:
        """Statements that (re)create a snapshot table from a query."""
        return [f"CREATE OR REPLACE TABLE {table_sql} AS {select_sql}"]

    def post_materialize_sql(self, table_sql: str) -> list[str]:
        """Statements to run after a snapshot table is created (clustering, statistics, ...)."""
        return []

    def null_text(self) -> str:
        """A NULL that is typed as text, so UNION ALL branches agree on the column type."""
        return "NULL"

    def quote_table(self, dotted: str) -> str:
        from ontoforge.compiler.identifiers import validate_table
        return ".".join(self.quote_identifier(p) for p in validate_table(dotted))

    def xsd_for_sql_type(self, sql_type: str) -> str | None:
        """Natural RDF datatype for a SQL type (R2RML §10.2). None means plain string literal."""
        t = sql_type.strip().upper().split("(")[0]
        return _NATURAL_XSD.get(t)


_NATURAL_XSD = {
    "INT": XSD + "integer", "INTEGER": XSD + "integer", "BIGINT": XSD + "integer",
    "SMALLINT": XSD + "integer", "TINYINT": XSD + "integer", "LONG": XSD + "integer",
    "DECIMAL": XSD + "decimal", "NUMERIC": XSD + "decimal",
    "FLOAT": XSD + "double", "DOUBLE": XSD + "double", "REAL": XSD + "double",
    "BOOLEAN": XSD + "boolean", "BOOL": XSD + "boolean",
    "DATE": XSD + "date", "TIMESTAMP": XSD + "dateTime", "TIMESTAMP_NTZ": XSD + "dateTime",
    "DATETIME": XSD + "dateTime", "TIME": XSD + "time",
    "BINARY": XSD + "hexBinary", "VARBINARY": XSD + "hexBinary",
}
