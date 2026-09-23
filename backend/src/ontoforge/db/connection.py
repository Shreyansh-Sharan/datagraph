"""A small wrapper over a psycopg connection pool: one transaction per ``with`` block."""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def normalise_url(url: str) -> str:
    """A connection string as anyone might paste it.

    The connection module and most tooling spell the driver into the scheme
    (``postgresql+psycopg://``). psycopg reads plain ``postgresql://``, so the driver part is
    dropped rather than failing on a string that is otherwise exactly right.
    """
    scheme, sep, rest = url.partition("://")
    return f"{scheme.split('+', 1)[0]}{sep}{rest}" if sep else url


def idle_check(after: float = 30.0, check=ConnectionPool.check_connection):
    """Check a pooled connection, but only when it has been sitting idle long enough to have died.

    A check is a round trip. Against a database in the next rack that is free; against a managed
    one across a region it costs as much as the statement it protects, on every single hand-out.
    A connection handed back seconds ago is alive, so the check is worth making only after a gap.
    """
    seen: dict[int, float] = {}

    def maybe(conn) -> None:
        key, now = id(conn), time.monotonic()
        if now - seen.get(key, 0.0) >= after:
            check(conn)
        seen[key] = now

    return maybe


class Database:
    def __init__(self, url: str, schema: str | None = None, max_size: int = 8, min_size: int = 2) -> None:
        url = normalise_url(url)
        kwargs = {"options": f"-c search_path={schema},public"} if schema else {}
        self.schema = schema
        # min_size: connecting to a managed Postgres costs a TLS handshake, so keep a few warm;
        # timeout: a caller waits at most 30 s for a connection instead of for ever when slow reads hold them all;
        # check: a connection that died (a restart, an idle timeout) is dropped instead of handed out.
        self.pool = ConnectionPool(url, min_size=min(min_size, max_size), max_size=max_size, kwargs=kwargs,
                                   open=True, timeout=30, check=idle_check())

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Cursor]:
        with self.pool.connection() as conn:
            with conn.transaction():
                yield conn.cursor()

    @contextmanager
    def rows(self) -> Iterator[psycopg.Cursor]:
        """A transaction whose cursor returns dict rows (columns by name)."""
        with self.pool.connection() as conn:
            with conn.transaction():
                yield conn.cursor(row_factory=dict_row)

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with self.pool.connection() as conn:
            yield conn

    def close(self) -> None:
        self.pool.close()
