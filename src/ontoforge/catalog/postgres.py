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
INTERNAL_TABLES = frozenset({"schema_migrations", "domains", "domain_versions", "connections", "reviews", "build_runs", "audit_log", "triples",
                             "principals", "api_keys", "metadata_snapshots", "analytics_runs", "comments", "cohorts"})

_DETAILS_SQL = """
SELECT c.column_name, c.data_type,
       col_description(format('%%I.%%I', c.table_schema, c.table_name)::regclass, c.ordinal_position)
FROM information_schema.columns c
WHERE c.table_schema = coalesce(%s::text, current_schema()) AND c.table_name = %s::text
ORDER BY c.ordinal_position
"""


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

    def column_details(self, table: str) -> list[dict]:
        schema, name = self._split(table)
        with self.db.transaction() as cur:
            return [{"name": n, "type": t, "comment": c} for n, t, c in cur.execute(_DETAILS_SQL, (schema, name))]

    def table_comment(self, table: str) -> str | None:
        schema, name = self._split(table)
        with self.db.transaction() as cur:
            row = cur.execute("SELECT obj_description(format('%%I.%%I', coalesce(%s::text, current_schema()), %s::text)::regclass, 'pg_class')",
                              (schema, name)).fetchone()
        return row[0] if row else None

    def _split(self, table: str) -> tuple[str | None, str]:
        parts = validate_table(table)
        if len(parts) == 3:
            raise IdentifierError(f"{table!r}: Postgres tables are schema.table (database is the connection)")
        return parts if len(parts) == 2 else (self.default_schema, parts[0])

    def primary_key(self, table: str) -> tuple[str, ...]:
        return next((tuple(cols) for t, _, cols, *_ in self._keys(table) if t == "p"), ())

    def foreign_keys(self, table: str) -> list[tuple[tuple[str, ...], str, tuple[str, ...]]]:
        return [(tuple(cols), ref, tuple(rcols)) for t, _, cols, ref, rcols in self._keys(table) if t == "f"]

    def _keys(self, table: str) -> list[tuple]:
        parts = validate_table(table)
        schema, name = (parts if len(parts) == 2 else (self.default_schema, parts[0]))
        with self.db.transaction() as cur:
            return cur.execute(_KEYS_SQL, (schema, name)).fetchall()

    def list_schemas(self, catalog: str | None = None) -> list[str]:
        with self.db.transaction() as cur:
            return [r[0] for r in cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT LIKE 'pg\\_%' AND schema_name <> 'information_schema' ORDER BY 1")]

    def list_tables(self, schema: str | None = None) -> list[str]:
        with self.db.transaction() as cur:
            return [r[0] for r in cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = coalesce(%s, current_schema()) AND table_type = 'BASE TABLE' ORDER BY 1",
                (schema or self.default_schema,)) if r[0] not in INTERNAL_TABLES]
