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
