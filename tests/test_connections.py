"""Connections (source and AI adapters) and domain settings behind the Home and Configure screens."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from ontoforge.connectors import CONNECTORS, specs
from ontoforge.connectors.secrets import SecretBox
from tests.conftest import TEST_DATABASE_URL
from tests.hr_fixture import BASE

ADMIN = Settings(auth_default_role="admin", secret_key="unit-test-key")


@pytest.fixture
def client(db):
    with TestClient(create_app(db=db, source_db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        yield c


def pg_config() -> dict:
    # postgresql://user:pass@host:port/db  ->  fields
    rest = TEST_DATABASE_URL.split("://", 1)[1]
    creds, loc = rest.split("@", 1)
    user, password = creds.split(":", 1)
    hostport, database = loc.split("/", 1)
    host, port = hostport.split(":")
    return {"config": {"host": host, "port": int(port), "database": database, "user": user, "schema": "public"}, "secret": password}


def test_secret_box_round_trip_and_key_independence():
    box = SecretBox("unit-test-key")
    token = box.encrypt("dapi-123")
    assert token != "dapi-123" and box.decrypt(token) == "dapi-123"
    assert SecretBox("another-key").decrypt(token) is None
    assert box.encrypt(None) is None and box.decrypt(None) is None


def test_connector_specs_cover_the_four_adapters():
    kinds = {s["kind"] for s in specs()}
    assert kinds == {"postgres", "databricks", "sqlserver", "azure_openai"}
    dbx = next(s for s in specs() if s["kind"] == "databricks")
    assert dbx["category"] == "source" and dbx["secret_field"] == "token"
    assert {f["name"] for f in dbx["fields"]} >= {"host", "http_path", "catalog", "schema"}
    ai = next(s for s in specs() if s["kind"] == "azure_openai")
    assert ai["category"] == "ai" and ai["secret_field"] == "api_key"
    assert set(CONNECTORS) == kinds


def test_connection_crud_hides_secrets_and_keeps_them_on_update(client):
    body = {"name": "warehouse", "kind": "postgres", **pg_config()}
    r = client.post("/connections", json=body)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["kind"] == "postgres" and c["has_secret"] is True and "secret" not in c and c["config"]["host"]
    cid = c["id"]
    assert client.get("/connections").json()[0]["name"] == "warehouse"
    assert client.get("/connectors").status_code == 200
    # update without a secret keeps the stored one
    r = client.put(f"/connections/{cid}", json={"name": "warehouse", "config": {**body["config"], "schema": "hr"}})
    assert r.status_code == 200 and r.json()["config"]["schema"] == "hr" and r.json()["has_secret"] is True
    t = client.post(f"/connections/{cid}/test").json()
    assert t["ok"] is True, t
    assert "PostgreSQL" in t["detail"] and t["latency_ms"] >= 0
    assert client.get(f"/connections/{cid}").json()["last_test"]["ok"] is True
    # a duplicate name is a conflict, an unknown kind is a 400
    assert client.post("/connections", json=body).status_code == 409
    assert client.post("/connections", json={"name": "x", "kind": "oracle", "config": {}}).status_code == 400
    assert client.delete(f"/connections/{cid}").status_code == 204
    assert client.get(f"/connections/{cid}").status_code == 404


def test_connections_require_the_admin_role(db):
    with TestClient(create_app(db=db, settings=Settings(auth_default_role="builder")), headers={"X-Actor": "bob"}) as c:
        assert c.post("/connections", json={"name": "w", "kind": "postgres", **pg_config()}).status_code == 403
        assert c.get("/connections").status_code == 200          # listing (no secrets) is fine for builders


def test_testing_an_unsaved_configuration_reports_failures_verbatim(client):
    good = client.post("/connections/test", json={"kind": "postgres", **pg_config()}).json()
    assert good["ok"] is True
    bad = pg_config(); bad["secret"] = "wrong-password"
    r = client.post("/connections/test", json={"kind": "postgres", **bad}).json()
    assert r["ok"] is False and r["title"] and r["detail"]
    ss = client.post("/connections/test", json={"kind": "sqlserver", "config": {"host": "localhost", "port": 1433, "database": "x", "user": "sa"}, "secret": "p"}).json()
    assert ss["ok"] is False and ("driver" in ss["title"].lower() or "connect" in ss["title"].lower())
    ai = client.post("/connections/test", json={"kind": "azure_openai", "config": {"endpoint": "http://127.0.0.1:9", "deployment": "gpt-5.1", "api_version": "2024-08-01-preview"}, "secret": "k"}).json()
    assert ai["ok"] is False and ai["detail"]


def test_domain_settings_and_cards(client):
    client.post("/domains", json={"name": "hr", "description": "People", "base_iri": BASE, "review_quorum": 1})
    conn = client.post("/connections", json={"name": "warehouse", "kind": "postgres", **pg_config()}).json()
    ai = client.post("/connections", json={"name": "gpt", "kind": "azure_openai", "config": {"endpoint": "https://x.openai.azure.com", "deployment": "gpt-5.1"}, "secret": "k"}).json()
    r = client.put("/domains/hr", json={"description": "People and departments", "review_quorum": 2, "connection_id": conn["id"], "ai_connection_id": ai["id"],
                                        "default_schema": "hr", "materialization": "view", "target_schema": "hr_graph"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["description"] == "People and departments" and d["review_quorum"] == 2 and d["connection_id"] == conn["id"] and d["default_schema"] == "hr"
    assert client.put("/domains/hr", json={"materialization": "sideways"}).status_code == 400
    src = client.get("/domains/hr/source").json()
    assert src["kind"] == "postgres" and src["connection"] == "warehouse" and src["schema"] == "hr" and src["materialization"] == "view"
    assert src["ai"] == {"connection": "gpt", "kind": "azure_openai", "deployment": "gpt-5.1"}
    cards = client.get("/domains/cards").json()
    assert [c["name"] for c in cards] == ["hr"]
    card = cards[0]
    assert card["version_count"] == 0 and card["active_version"] is None and card["triples"] == 0 and card["last_build"] is None
    assert card["source"] == {"kind": "postgres", "connection": "warehouse", "catalog": None, "schema": "hr"}
    assert card["mcp"] == {"exposed": True, "disabled_tools": []}
    v = client.post("/domains/hr/versions").json()
    card = client.get("/domains/cards").json()[0]
    assert card["version_count"] == 1 and card["latest_version"] == {"version": 1, "status": "draft"}
    # deleting a connection detaches it from the domain instead of failing
    assert client.delete(f"/connections/{conn['id']}").status_code == 204
    assert client.get("/domains/hr").json()["connection_id"] is None
    assert client.get("/domains/hr/source").json()["connection"] is None
    assert v["version"] == 1
