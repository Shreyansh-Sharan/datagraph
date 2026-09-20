"""PostgreSQL metadata via ``information_schema``."""
from __future__ import annotations

from ontoforge.compiler.identifiers import IdentifierError, validate_table
from ontoforge.db import Database

from .base import CatalogAdapter

_COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = coalesce(%s, current_schema()) AND table_name = %s ORDER BY ordinal_position"
)


_KEYS_SQL = """
SELECT con.contype, con.conname,
       array(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum ORDER BY ord),
       ref.relname,
       array(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum ORDER BY ord)
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace ns ON ns.oid = rel.relnamespace
LEFT JOIN pg_class ref ON ref.oid = con.confrelid
WHERE con.contype IN ('p', 'f') AND ns.nspname = coalesce(%s, current_schema()) AND rel.relname = %s
ORDER BY con.contype, con.conname
"""


# ontoforge's own tables are never mapping sources, even when registry and data share a schema.
INTERNAL_TABLES = frozenset({"schema_migrations", "domains", "domain_versions", "reviews", "build_runs", "audit_log", "triples"})


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

    def primary_key(self, table: str) -> tuple[str, ...]:
        return next((tuple(cols) for t, _, cols, *_ in self._keys(table) if t == "p"), ())

    def foreign_keys(self, table: str) -> list[tuple[tuple[str, ...], str, tuple[str, ...]]]:
        return [(tuple(cols), ref, tuple(rcols)) for t, _, cols, ref, rcols in self._keys(table) if t == "f"]

    def _keys(self, table: str) -> list[tuple]:
        parts = validate_table(table)
        schema, name = (parts if len(parts) == 2 else (self.default_schema, parts[0]))
        with self.db.transaction() as cur:
            return cur.execute(_KEYS_SQL, (schema, name)).fetchall()

    def list_tables(self, schema: str | None = None) -> list[str]:
        with self.db.transaction() as cur:
            return [r[0] for r in cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = coalesce(%s, current_schema()) AND table_type = 'BASE TABLE' ORDER BY 1",
                (schema or self.default_schema,)) if r[0] not in INTERNAL_TABLES]
