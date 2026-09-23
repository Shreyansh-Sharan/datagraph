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


# Unity Catalog publishes declared constraints here. They are informational (Databricks does not
# enforce them), but a declared key is still the warehouse's own statement about the table, and
# autodrafting a relation from it beats guessing from a column name.
_PK_SQL = (
    "SELECT k.column_name FROM system.information_schema.table_constraints c "
    "JOIN system.information_schema.key_column_usage k "
    "  ON k.constraint_catalog = c.constraint_catalog AND k.constraint_schema = c.constraint_schema "
    " AND k.constraint_name = c.constraint_name "
    "WHERE c.constraint_type = 'PRIMARY KEY' AND c.table_catalog = ? AND c.table_schema = ? AND c.table_name = ? "
    "ORDER BY k.ordinal_position"
)

_FK_SQL = (
    "SELECT c.constraint_name, k.column_name, u.table_catalog, u.table_schema, u.table_name, u.column_name "
    "FROM system.information_schema.table_constraints c "
    "JOIN system.information_schema.key_column_usage k "
    "  ON k.constraint_catalog = c.constraint_catalog AND k.constraint_schema = c.constraint_schema "
    " AND k.constraint_name = c.constraint_name "
    "JOIN system.information_schema.referential_constraints r "
    "  ON r.constraint_catalog = c.constraint_catalog AND r.constraint_schema = c.constraint_schema "
    " AND r.constraint_name = c.constraint_name "
    "JOIN system.information_schema.key_column_usage u "
    "  ON u.constraint_catalog = r.unique_constraint_catalog AND u.constraint_schema = r.unique_constraint_schema "
    " AND u.constraint_name = r.unique_constraint_name AND u.ordinal_position = k.ordinal_position "
    "WHERE c.constraint_type = 'FOREIGN KEY' AND c.table_catalog = ? AND c.table_schema = ? AND c.table_name = ? "
    "ORDER BY c.constraint_name, k.ordinal_position"
)


class DatabricksCatalog(CatalogAdapter):
    def __init__(self, run_query: QueryRunner, default_catalog: str | None = None,
                 default_schema: str | None = None) -> None:
        self.run_query = run_query
        self.default_catalog, self.default_schema = default_catalog, default_schema

    def column_details(self, table: str) -> list[dict]:
        return [{"name": n, "type": t, "comment": c} for n, t, c in self.run_query(_DETAILS_SQL, self._parts(table))]

    def primary_key(self, table: str) -> tuple[str, ...]:
        return tuple(r[0] for r in self.run_query(_PK_SQL, self._parts(table)))

    def foreign_keys(self, table: str) -> list[tuple[tuple[str, ...], str, tuple[str, ...]]]:
        by_constraint: dict[str, tuple[list[str], str, list[str]]] = {}
        for name, column, ref_cat, ref_schema, ref_table, ref_column in self.run_query(_FK_SQL, self._parts(table)):
            cols, _, ref_cols = by_constraint.setdefault(name, ([], ".".join(p for p in (ref_cat, ref_schema, ref_table) if p), []))
            cols.append(column)
            ref_cols.append(ref_column)
        return [(tuple(cols), ref, tuple(ref_cols)) for cols, ref, ref_cols in by_constraint.values()]

    def column_types(self, table: str) -> dict[str, str]:
        return {name: sql_type for name, sql_type in self.run_query(_COLUMNS_SQL, self._parts(table))}

    def list_schemas(self, catalog: str | None = None) -> list[str]:
        cat = catalog or self.default_catalog
        if not cat:
            raise IdentifierError("A catalog is required to list schemas")
        rows = self.run_query("SELECT schema_name FROM system.information_schema.schemata WHERE catalog_name = ? "
                              "AND schema_name NOT IN ('information_schema') ORDER BY schema_name", (cat,))
        return [r[0] for r in rows]

    def list_tables_detailed(self, schema: str | None = None) -> list[dict]:
        catalog, sch = self._schema_parts(schema)
        rows = self.run_query(
            "SELECT t.table_name, count(c.column_name), max(t.comment) FROM system.information_schema.tables t "
            "LEFT JOIN system.information_schema.columns c ON c.table_catalog = t.table_catalog AND c.table_schema = t.table_schema AND c.table_name = t.table_name "
            "WHERE t.table_catalog = ? AND t.table_schema = ? AND t.table_name NOT LIKE '\\_\\_%' GROUP BY t.table_name ORDER BY t.table_name", (catalog, sch))
        return [{"name": r[0], "columns": int(r[1] or 0), "comment": r[2]} for r in rows]

    def list_tables(self, schema: str | None = None) -> list[str]:
        catalog, sch = self._schema_parts(schema)
        rows = self.run_query("SELECT table_name FROM system.information_schema.tables WHERE table_catalog = ? AND table_schema = ? "
                              "AND table_name NOT LIKE '\\_\\_%' ORDER BY table_name", (catalog, sch))
        return [r[0] for r in rows]

    def table_comment(self, table: str) -> str | None:
        rows = self.run_query("SELECT comment FROM system.information_schema.tables WHERE table_catalog = ? AND table_schema = ? "
                              "AND table_name = ?", self._parts(table))
        return rows[0][0] if rows and rows[0][0] else None

    def qualified(self, table: str, schema: str | None = None) -> str:
        if table.count(".") == 2:
            return table
        catalog, sch = self._schema_parts(schema if schema or table.count(".") == 0 else table.rsplit(".", 1)[0])
        return f"{catalog}.{sch}.{table.rsplit('.', 1)[-1]}"

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
