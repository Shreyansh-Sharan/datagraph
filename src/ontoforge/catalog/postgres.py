"""PostgreSQL metadata via ``information_schema``."""
from __future__ import annotations

from ontoforge.compiler.identifiers import IdentifierError, validate_table
from ontoforge.db import Database

from .base import CatalogAdapter

_COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = coalesce(%s, current_schema()) AND table_name = %s ORDER BY ordinal_position"
)


class PostgresCatalog(CatalogAdapter):
    def __init__(self, db: Database, default_schema: str | None = None) -> None:
        self.db, self.default_schema = db, default_schema

    def column_types(self, table: str) -> dict[str, str]:
        parts = validate_table(table)
        if len(parts) == 3:
            raise IdentifierError(f"{table!r}: Postgres tables are schema.table (database is the connection)")
        schema, name = (parts if len(parts) == 2 else (self.default_schema, parts[0]))
        with self.db.transaction() as cur:
            return {col: typ for col, typ in cur.execute(_COLUMNS_SQL, (schema, name))}

    def list_tables(self, schema: str | None = None) -> list[str]:
        with self.db.transaction() as cur:
            return [r[0] for r in cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = coalesce(%s, current_schema()) AND table_type = 'BASE TABLE' ORDER BY 1",
                (schema or self.default_schema,))]
