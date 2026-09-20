"""A small wrapper over a psycopg connection pool: one transaction per ``with`` block."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool


class Database:
    def __init__(self, url: str, schema: str | None = None, max_size: int = 8) -> None:
        kwargs = {"options": f"-c search_path={schema},public"} if schema else {}
        self.schema = schema
        self.pool = ConnectionPool(url, min_size=1, max_size=max_size, kwargs=kwargs, open=True)

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Cursor]:
        with self.pool.connection() as conn:
            with conn.transaction():
                yield conn.cursor()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with self.pool.connection() as conn:
            yield conn

    def close(self) -> None:
        self.pool.close()
