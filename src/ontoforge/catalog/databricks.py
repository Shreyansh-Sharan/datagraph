"""Unity Catalog metadata via ``system.information_schema``."""
from __future__ import annotations

from typing import Callable, Sequence

from ontoforge.compiler.identifiers import IdentifierError, validate_table

from .base import CatalogAdapter

QueryRunner = Callable[[str, tuple], Sequence[tuple]]
"""Executes parameterised SQL and returns rows. Adapters accept one so they can be tested
without a warehouse; production wires ``cursor.execute(sql, params); cursor.fetchall()``."""

_COLUMNS_SQL = (
    "SELECT column_name, full_data_type FROM system.information_schema.columns "
    "WHERE table_catalog = ? AND table_schema = ? AND table_name = ? ORDER BY ordinal_position"
)


class DatabricksCatalog(CatalogAdapter):
    def __init__(self, run_query: QueryRunner, default_catalog: str | None = None,
                 default_schema: str | None = None) -> None:
        self.run_query = run_query
        self.default_catalog, self.default_schema = default_catalog, default_schema

    def column_types(self, table: str) -> dict[str, str]:
        parts = list(validate_table(table))
        if len(parts) == 1:
            parts = [self.default_schema, *parts]
        if len(parts) == 2:
            parts = [self.default_catalog, *parts]
        if any(p is None for p in parts):
            raise IdentifierError(f"{table!r} needs catalog and schema (none configured as defaults)")
        return {name: sql_type for name, sql_type in self.run_query(_COLUMNS_SQL, tuple(parts))}
