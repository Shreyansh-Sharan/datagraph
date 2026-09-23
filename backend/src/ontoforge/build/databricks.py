"""Databricks SQL Warehouse as a source engine.

The connection is supplied by a factory so the engine can be exercised with a fake DB-API
connection in tests; production passes ``lambda: databricks.sql.connect(...)``.
"""
from __future__ import annotations

from typing import Callable, Iterator

from ontoforge.catalog import DatabricksCatalog
from ontoforge.dialects import DatabricksDialect

from .source import SourceEngine

ConnectionFactory = Callable[[], object]  # DB-API 2.0 connection with .cursor()


class DatabricksSource(SourceEngine):
    def __init__(self, connect: ConnectionFactory, default_catalog: str | None = None, default_schema: str | None = None) -> None:
        self.connect = connect
        self.dialect = DatabricksDialect()
        self.catalog = DatabricksCatalog(self._run_query, default_catalog, default_schema)

    def prepare(self) -> None:
        """Spark SQL has url_encode / concat built in: nothing to install."""

    def stream(self, sql: str, batch: int = 10_000) -> Iterator[tuple]:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                while True:
                    rows = cur.fetchmany(batch)
                    if not rows:
                        break
                    yield from (tuple(r) for r in rows)
        finally:
            conn.close()

    def execute(self, sql: str) -> None:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
        finally:
            conn.close()

    def query(self, sql: str, limit: int = 100) -> tuple[list[str], list[tuple]]:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM ({self.guard_select(sql)}) preview LIMIT {int(limit)}")
                return [d[0] for d in (getattr(cur, "description", None) or [])], [tuple(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def query_params(self, sql: str, params: dict, limit: int = 100) -> tuple[list[str], list[tuple]]:
        conn = self.connect()   # databricks-sql-connector binds :name markers natively
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM ({self.guard_select(sql)}) preview LIMIT {int(limit)}", params)
                return [d[0] for d in cur.description], [tuple(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def describe_detail(self, table: str) -> dict:
        """DESCRIBE DETAIL as a dict: Delta's size, file count and last modification time, among others."""
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"DESCRIBE DETAIL {self.dialect.quote_table(table)}")
                names = [d[0] for d in (getattr(cur, "description", None) or [])]
                rows = cur.fetchall()
                return dict(zip(names, rows[0])) if rows and names else {}
        finally:
            conn.close()

    def table_stats(self, table: str) -> tuple[int | None, "datetime | None"]:
        row = self.describe_detail(table)
        size = row.get("sizeInBytes")
        return (int(size) if size is not None else None), row.get("lastModified")

    def table_signature(self, table: str) -> str | None:
        """Every write to a Delta table moves lastModified; numFiles and sizeInBytes guard the rest."""
        row = self.describe_detail(table)
        if not row or row.get("lastModified") is None:
            return None
        return f"{row.get('lastModified')}|{row.get('numFiles')}|{row.get('sizeInBytes')}"

    def _run_query(self, sql: str, params: tuple) -> list[tuple]:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [tuple(r) for r in cur.fetchall()]
        finally:
            conn.close()


def databricks_connect_factory(server_hostname: str, http_path: str, access_token: str,
                               catalog: str | None = None, schema: str | None = None, socket_timeout: float = 600) -> ConnectionFactory:
    """Build a factory over ``databricks-sql-connector`` (optional dependency).

    ``catalog``/``schema`` become the session defaults, so mapping tables can be written as
    ``schema.table`` (or bare ``table``) instead of three-part names.
    """
    def connect():
        from databricks import sql  # imported lazily: optional extra
        # A socket without a timeout turns one dropped packet into a job that never ends.
        kwargs = {"server_hostname": server_hostname, "http_path": http_path, "access_token": access_token, "_socket_timeout": socket_timeout}
        if catalog:
            kwargs["catalog"] = catalog
        if schema:
            kwargs["schema"] = schema
        return sql.connect(**kwargs)
    return connect
