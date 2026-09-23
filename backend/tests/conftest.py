"""Postgres-backed tests get an isolated schema each: migrations run into it, it is dropped after."""
import os
import uuid

import pytest

# Tests never read the developer's .env: pin the source engine and LLM provider (env beats .env).
os.environ.setdefault("ONTOFORGE_SOURCE_KIND", "postgres")
os.environ.setdefault("ONTOFORGE_LLM_PROVIDER", "none")
os.environ.setdefault("ONTOFORGE_WAREHOUSE_MATERIALIZATION", "none")
os.environ.setdefault("ONTOFORGE_CONNECTIONS_HUB_URL", "")   # tests inject a stub hub explicitly
for _k in ("ONTOFORGE_DATABRICKS_HOST", "ONTOFORGE_DATABRICKS_HTTP_PATH", "ONTOFORGE_DATABRICKS_TOKEN"):
    os.environ.setdefault(_k, "")

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
