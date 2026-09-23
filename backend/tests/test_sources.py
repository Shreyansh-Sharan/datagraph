"""A domain reads through its own connection from the connection module; without one, the deployment's source."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.build import PostgresSource
from ontoforge.connectors import HubConnections, HubUnavailable
from ontoforge.registry import Registry
from ontoforge.sources import SourceResolver
from tests.conftest import TEST_DATABASE_URL
from tests.test_connections_hub import HUB, seed, stub_hub


def _pg_config():
    from urllib.parse import urlparse
    u = urlparse(TEST_DATABASE_URL)
    return {"host": u.hostname, "port": u.port or 5432, "database": u.path.lstrip("/"), "username": u.username, "password": u.password, "sslmode": "prefer"}


@pytest.fixture
def hub():
    return TestClient(stub_hub(), base_url="http://hub.local")


def test_domain_with_a_connection_opens_that_source_and_one_without_uses_the_deployment(db, hub):
    hub_types = hub.get("/connection-types").json()   # the stub offers databricks + azureopenai; postgres creds still open a Postgres source
    assert hub_types
    conn = seed(hub, "lake", "databricks", {**_pg_config(), "host": _pg_config()["host"], "http_path": "/x", "token": "t"})
    reg = Registry(db)
    ai = seed(hub, "gpt", "azureopenai", {"endpoint": "https://x", "deployment": "d", "api_key": "k"})
    d = reg.create_domain("lake", base_iri="http://d/lake/", ai_connection_id=ai["id"], sources=[{"connection_id": conn["id"], "catalog": None, "schemas": ["public"]}])
    env_calls = []
    resolver = SourceResolver(HUB, reg, HubConnections(hub, service_token="svc"), lambda: env_calls.append(1) or PostgresSource(db))
    # a Databricks-typed stub connection carries a PAT: opening it builds a Databricks engine (lazily, no network yet)
    src = resolver.for_domain(d)
    assert type(src).__name__ == "DatabricksSource" and src.catalog.default_schema == "public"
    assert resolver.for_domain(d) is src and env_calls == []                      # cached, env untouched
    plain = reg.create_domain("plain", base_iri="http://d/plain/", ai_connection_id=ai["id"])
    assert isinstance(resolver.for_domain(plain), PostgresSource) and env_calls == [1]   # deployment source, built once
    v = reg.create_version(plain.id, actor="a")
    assert resolver.for_version(v.id) is resolver.env


def test_postgres_credentials_open_a_postgres_source(db):
    cred = {"id": "x", "name": "pg", "kind": "postgres", "config": _pg_config()}
    src = SourceResolver._open(cred, None, db.schema)
    assert isinstance(src, PostgresSource) and src.catalog.list_tables() == []      # our own registry tables are never sources


def test_without_a_service_token_the_error_names_the_setting(db, hub):
    conn = seed(hub, "wh", "databricks", {"host": "h", "http_path": "/p", "token": "t"})
    reg = Registry(db)
    resolver = SourceResolver(HUB, reg, HubConnections(hub, service_token=None), lambda: PostgresSource(db))
    with pytest.raises(HubUnavailable, match="ONTOFORGE_CONNECTIONS_HUB_SERVICE_TOKEN"):
        resolver.for_connection(conn["id"])


def test_unsupported_kinds_are_refused_plainly():
    with pytest.raises(ValueError, match="Databricks and Postgres"):
        SourceResolver._open({"id": "1", "name": "srv", "kind": "mssql", "config": {}}, None, None)
    with pytest.raises(ValueError, match="personal access token"):
        SourceResolver._open({"id": "1", "name": "sp", "kind": "databricks", "config": {"auth_type": "service_principal"}}, None, None)
