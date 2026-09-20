"""The source-engine port: where the mapped tables live and how to run SQL there."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ontoforge.catalog import CatalogAdapter, PostgresCatalog
from ontoforge.db import Database
from ontoforge.dialects import PostgresDialect, SqlDialect


class SourceEngine(ABC):
    dialect: SqlDialect
    catalog: CatalogAdapter

    def prepare(self) -> None:
        """Install anything compiled SQL depends on (idempotent)."""

    @abstractmethod
    def stream(self, sql: str, batch: int = 10_000) -> Iterator[tuple]:
        """Execute a SELECT and yield rows."""

    @abstractmethod
    def execute(self, sql: str) -> None:
        """Run a DDL/DML statement in the warehouse."""

    @abstractmethod
    def query(self, sql: str, limit: int = 100) -> tuple[list[str], list[tuple]]:
        """Run a SELECT with a row cap; returns (column names, rows)."""

    @abstractmethod
    def query_params(self, sql: str, params: dict, limit: int = 100) -> tuple[list[str], list[tuple]]:
        """Run a SELECT with ``:name`` placeholders bound from ``params`` and a row cap."""

    @staticmethod
    def guard_select(sql: str) -> str:
        sql = sql.strip().rstrip(";").strip()
        if ";" in sql or not sql:
            raise ValueError("Expected a single SELECT statement without ';'")
        if not sql.lower().startswith(("select", "with")):
            raise ValueError("Only SELECT queries can be previewed")
        return sql

    def ensure_schema(self, schema: str) -> None:
        self.execute(f"CREATE SCHEMA IF NOT EXISTS {self.dialect.quote_table(schema)}")


class PostgresSource(SourceEngine):
    def __init__(self, db: Database, default_schema: str | None = None) -> None:
        self.db = db
        self.dialect = PostgresDialect()
        self.catalog = PostgresCatalog(db, default_schema)

    def prepare(self) -> None:
        with self.db.transaction() as cur:
            cur.execute(self.dialect.setup_sql())

    def stream(self, sql: str, batch: int = 10_000) -> Iterator[tuple]:
        with self.db.connection() as conn:
            with conn.cursor(name="ontoforge_source") as cur:
                cur.itersize = batch
                cur.execute(sql)
                yield from cur

    def execute(self, sql: str) -> None:
        with self.db.transaction() as cur:
            cur.execute(sql)

    def query(self, sql: str, limit: int = 100) -> tuple[list[str], list[tuple]]:
        with self.db.transaction() as cur:
            cur.execute(f"SELECT * FROM ({self.guard_select(sql)}) preview LIMIT {int(limit)}")
            return [d.name for d in cur.description], cur.fetchall()

    def query_params(self, sql: str, params: dict, limit: int = 100) -> tuple[list[str], list[tuple]]:
        import re
        bound = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", r"%(\1)s", self.guard_select(sql))
        with self.db.transaction() as cur:
            cur.execute(f"SELECT * FROM ({bound}) preview LIMIT {int(limit)}", params)
            return [d.name for d in cur.description], cur.fetchall()
