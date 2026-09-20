"""The catalog port: what the compiler needs to know about warehouse tables.

One implementation per warehouse. The compiler only ever sees the ``ColumnTypeResolver``
returned by ``resolver()``; nothing upstream references a concrete warehouse.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ontoforge.compiler.compiler import ColumnTypeResolver
from ontoforge.r2rml.model import LogicalTable


class CatalogAdapter(ABC):
    @abstractmethod
    def column_types(self, table: str) -> dict[str, str]:
        """Column name -> SQL type name for a (possibly dotted) table name."""

    def list_tables(self, schema: str | None = None) -> list[str]:
        return []

    def column_details(self, table: str) -> list[dict]:
        """[{name, type, comment}] — default derives from column_types without comments."""
        return [{"name": n, "type": t, "comment": None} for n, t in self.column_types(table).items()]

    def table_comment(self, table: str) -> str | None:
        return None

    def primary_key(self, table: str) -> tuple[str, ...]:
        return ()

    def foreign_keys(self, table: str) -> list[tuple[tuple[str, ...], str, tuple[str, ...]]]:
        """[(local columns, referenced table, referenced columns)]."""
        return []

    def resolver(self) -> ColumnTypeResolver:
        cache: dict[str, dict[str, str]] = {}

        def resolve(lt: LogicalTable, column: str) -> str | None:
            if lt.table_name is None:  # rr:sqlQuery: no catalog entry to consult
                return None
            if lt.table_name not in cache:
                cache[lt.table_name] = {k.lower(): v for k, v in self.column_types(lt.table_name).items()}
            return cache[lt.table_name].get(column.lower())

        return resolve
