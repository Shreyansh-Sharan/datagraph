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


_DETAILS_SQL = (
    "SELECT column_name, full_data_type, comment FROM system.information_schema.columns "
    "WHERE table_catalog = ? AND table_schema = ? AND table_name = ? ORDER BY ordinal_position"
)


class DatabricksCatalog(CatalogAdapter):
    def __init__(self, run_query: QueryRunner, default_catalog: str | None = None,
                 default_schema: str | None = None) -> None:
        self.run_query = run_query
        self.default_catalog, self.default_schema = default_catalog, default_schema

    def column_details(self, table: str) -> list[dict]:
        return [{"name": n, "type": t, "comment": c} for n, t, c in self.run_query(_DETAILS_SQL, self._parts(table))]

    def column_types(self, table: str) -> dict[str, str]:
        return {name: sql_type for name, sql_type in self.run_query(_COLUMNS_SQL, self._parts(table))}

    def list_schemas(self, catalog: str | None = None) -> list[str]:
        cat = catalog or self.default_catalog
        if not cat:
            raise IdentifierError("A catalog is required to list schemas")
        rows = self.run_query("SELECT schema_name FROM system.information_schema.schemata WHERE catalog_name = ? "
                              "AND schema_name NOT IN ('information_schema') ORDER BY schema_name", (cat,))
        return [r[0] for r in rows]

    def list_tables(self, schema: str | None = None) -> list[str]:
        catalog, sch = self._schema_parts(schema)
        rows = self.run_query("SELECT table_name FROM system.information_schema.tables WHERE table_catalog = ? AND table_schema = ? "
                              "AND table_name NOT LIKE '\\_\\_%' ORDER BY table_name", (catalog, sch))
        return [r[0] for r in rows]

    def table_comment(self, table: str) -> str | None:
        rows = self.run_query("SELECT comment FROM system.information_schema.tables WHERE table_catalog = ? AND table_schema = ? "
                              "AND table_name = ?", self._parts(table))
        return rows[0][0] if rows and rows[0][0] else None

    def _schema_parts(self, schema: str | None) -> tuple[str, str]:
        parts = (schema or "").split(".") if schema else []
        if len(parts) == 2:
            return parts[0], parts[1]
        sch = parts[0] if parts else self.default_schema
        if not self.default_catalog or not sch:
            raise IdentifierError("A schema is required (and a default catalog must be configured)")
        return self.default_catalog, sch

    def _parts(self, table: str) -> tuple:
        parts = list(validate_table(table))
        if len(parts) == 1:
            parts = [self.default_schema, *parts]
        if len(parts) == 2:
            parts = [self.default_catalog, *parts]
        if any(p is None for p in parts):
            raise IdentifierError(f"{table!r} needs catalog and schema (none configured as defaults)")
        return tuple(parts)
