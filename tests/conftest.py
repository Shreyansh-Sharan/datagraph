"""Postgres-backed tests get an isolated schema each: migrations run into it, it is dropped after."""
import os
import uuid

import pytest

from ontoforge.db import Database, run_migrations

TEST_DATABASE_URL = os.environ.get("ONTOFORGE_TEST_DATABASE_URL",
                                   "postgresql://ontoforge:ontoforge@localhost:5439/ontoforge")


@pytest.fixture
def db():
    schema = "t_" + uuid.uuid4().hex[:12]
    database = Database(TEST_DATABASE_URL, schema=schema)
    with database.transaction() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"')
    run_migrations(database)
    try:
        yield database
    finally:
        with database.transaction() as cur:
            cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        database.close()
