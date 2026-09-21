"""Connections come from the Polestar connection module (a separate service, mf-studio-connectors).

datagraph reads connector types and connections from the hub, tests a saved connection through it
and stores hub connection ids on domains. It never creates connections or sees a secret: the UI
does that with the hub's own package. A stub hub with the real API shape stands in.
"""
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from ontoforge.connectors import HubConnections, result_from_report, spec_from_schema
from tests.hr_fixture import BASE

MASK = "********"

DBX_SCHEMA = {
    "title": "Databricks SQL Connection", "type": "object", "additionalProperties": False,
    "properties": {
        "host": {"type": "string", "title": "Workspace host", "description": "Workspace URL."},
        "http_path": {"type": "string", "title": "HTTP path"},
        "auth_type": {"type": "string", "title": "Authentication", "enum": ["pat", "service_principal"], "default": "pat",
                      "x-enum-titles": {"pat": "Personal access token", "service_principal": "Azure service principal"}},
        "token": {"type": "string", "title": "Personal access token", "format": "password", "writeOnly": True, "x-show-when": {"auth_type": "pat"}},
        "client_secret": {"type": "string", "title": "Client secret", "format": "password", "writeOnly": True, "x-show-when": {"auth_type": "service_principal"}},
        "catalog": {"type": "string", "title": "Catalog", "default": "hive_metastore"},
        "connect_timeout": {"type": "integer", "title": "Connect timeout (seconds)", "default": 30, "minimum": 1},
    },
    "required": ["host", "http_path"],
}
AI_SCHEMA = {
    "title": "Azure OpenAI Connection", "type": "object", "additionalProperties": False,
    "properties": {"endpoint": {"type": "string", "title": "Endpoint"}, "api_key": {"type": "string", "title": "API key", "format": "password", "writeOnly": True},
                   "deployment": {"type": "string", "title": "Deployment"}, "api_version": {"type": "string", "title": "API version", "default": "2024-08-01-preview"}},
    "required": ["endpoint", "api_key", "deployment"],
}


def stub_hub() -> FastAPI:
    """The hub's API surface datagraph uses, with in-memory state."""
    app = FastAPI()
    state: dict = {"connections": {}}
    types = {"databricks": ("database", DBX_SCHEMA), "azureopenai": ("ai", AI_SCHEMA)}
    secret_names = lambda t: {k for k, v in types[t][1]["properties"].items() if v.get("format") == "password"}

    def out(c):
        return {**{k: v for k, v in c.items() if k != "_secrets"}, "config": {**c["config"], **{k: MASK for k in c["_secrets"]}}}

    def report(t, config):
        ok = bool(config.get("host") or config.get("endpoint")) and config.get("token", config.get("api_key")) != "bad"
        return {"ok": ok, "steps": [
            {"name": "authenticate", "status": "passed" if ok else "failed", "description": "Authenticate.", "required": True, "duration_ms": 12,
             "summary": "3 deployment(s): a, b, c" if ok else "API key rejected", "error": None if ok else "401 from /openai/deployments: Access denied",
             "remediation": None if ok else "Copy Key 1 or Key 2 from Keys and Endpoint."},
            {"name": "complete", "status": "passed" if ok else "skipped", "description": "Ask for a completion.", "required": True, "duration_ms": 30 if ok else 0,
             "summary": "Deployment answered" if ok else "A previous required step failed.", "error": None, "remediation": None}]}

    @app.get("/connection-types")
    def list_types():
        return [{"type": t, "category": cat, "display_name": schema["title"].replace(" Connection", ""), "supports_introspection": True, "dialect": "databricks" if t == "databricks" else None} for t, (cat, schema) in types.items()]

    @app.get("/connection-types/{t}/schema")
    def schema(t: str):
        if t not in types:
            raise HTTPException(404, f"No connector installed for type {t!r}")
        return types[t][1]

    @app.post("/connections", status_code=201)
    def create(body: dict):   # the package's job in real life; here only to seed the stub
        cid = str(uuid.uuid4()); secrets = {k: v for k, v in body["config"].items() if k in secret_names(body["type"])}
        c = {"id": cid, "name": body["name"], "type": body["type"], "description": body.get("description"), "config": {k: v for k, v in body["config"].items() if k not in secrets},
             "_secrets": secrets, "created_at": "2026-09-21T12:00:00Z", "updated_at": "2026-09-21T12:00:00Z", "last_test_ok": None, "last_tested_at": None}
        state["connections"][cid] = c
        return out(c)

    @app.get("/connections")
    def list_connections():
        return [out(c) for c in state["connections"].values()]

    @app.get("/connections/{cid}")
    def get_one(cid: str):
        if cid not in state["connections"]:
            raise HTTPException(404, "Connection not found")
        return out(state["connections"][cid])

    @app.post("/connections/{cid}/test")
    def test_saved(cid: str):
        if cid not in state["connections"]:
            raise HTTPException(404, "Connection not found")
        c = state["connections"][cid]
        r = report(c["type"], {**c["config"], **c["_secrets"]})
        c["last_test_ok"] = r["ok"]; c["last_tested_at"] = "2026-09-21T12:45:00Z"
        return r

    return app


HUB = Settings(auth_default_role="admin", connections_hub_url="http://hub.local")


@pytest.fixture
def hub():
    # Starlette's TestClient is an httpx.Client with a synchronous ASGI transport.
    return TestClient(stub_hub(), base_url="http://hub.local")


@pytest.fixture
def client(db, hub):
    with TestClient(create_app(db=db, source_db=db, settings=HUB, hub_client=hub), headers={"X-Actor": "alice"}) as c:
        yield c


def seed(hub, name, kind, config):
    return hub.post("/connections", json={"name": name, "type": kind, "config": config}).json()


def test_specs_are_derived_from_the_hub_json_schemas():
    spec = spec_from_schema("databricks", "database", "Databricks SQL", DBX_SCHEMA)
    assert spec["kind"] == "databricks" and spec["category"] == "source" and spec["secret_field"] == "token"
    fields = {f["name"]: f for f in spec["fields"]}
    assert fields["host"]["required"] is True and fields["catalog"]["required"] is False and fields["catalog"]["default"] == "hive_metastore"
    assert fields["auth_type"] == {"name": "auth_type", "label": "Authentication", "kind": "select", "required": False, "default": "pat", "options": ["pat", "service_principal"], "help": None, "option_titles": {"pat": "Personal access token", "service_principal": "Azure service principal"}, "show_when": None}
    assert fields["token"]["kind"] == "password" and fields["token"]["show_when"] == {"auth_type": "pat"}
    assert fields["connect_timeout"]["kind"] == "number" and fields["connect_timeout"]["default"] == 30
    ai = spec_from_schema("azureopenai", "ai", "Azure OpenAI", AI_SCHEMA)
    assert ai["category"] == "ai" and ai["secret_field"] == "api_key"


def test_step_reports_fold_into_one_result():
    ok = result_from_report({"ok": True, "steps": [{"name": "authenticate", "status": "passed", "duration_ms": 12, "summary": "3 deployment(s)"}, {"name": "complete", "status": "passed", "duration_ms": 30}]})
    assert ok == {"ok": True, "title": "Connected", "detail": "authenticate: passed · 3 deployment(s)\ncomplete: passed", "latency_ms": 42, "action": None, "facts": {"steps": ok["facts"]["steps"]}}
    bad = result_from_report({"ok": False, "steps": [{"name": "authenticate", "status": "failed", "duration_ms": 5, "summary": "API key rejected", "error": "401", "remediation": "Copy Key 1."}, {"name": "complete", "status": "skipped", "duration_ms": 0}]})
    assert bad["title"] == "API key rejected" and bad["action"] == "Copy Key 1." and "401" in bad["detail"]


def test_datagraph_reads_types_and_connections_from_the_hub(client, hub):
    kinds = {s["kind"]: s for s in client.get("/connectors").json()}
    assert set(kinds) == {"databricks", "azureopenai"} and kinds["azureopenai"]["category"] == "ai" and kinds["databricks"]["source"] == "hub"
    c = seed(hub, "warehouse", "databricks", {"host": "adb-1.azuredatabricks.net", "http_path": "/sql/1.0/warehouses/x", "catalog": "rgm", "token": "dapi-secret"})
    listed = client.get("/connections").json()
    assert [x["name"] for x in listed] == ["warehouse"] and listed[0]["has_secret"] is True and listed[0]["source"] == "hub"
    assert "dapi-secret" not in client.get("/connections").text and "token" not in listed[0]["config"]
    one = client.get(f"/connections/{c['id']}").json()
    assert one["kind"] == "databricks" and one["config"]["catalog"] == "rgm"
    t = client.post(f"/connections/{c['id']}/test").json()
    assert t["ok"] is True and t["title"] == "Connected" and "3 deployment(s)" in t["detail"] and t["latency_ms"] == 42
    assert client.get(f"/connections/{c['id']}").json()["last_test"]["ok"] is True
    assert client.get(f"/connections/{uuid.uuid4()}").status_code == 404
    # writes are the package's job: datagraph does not proxy them
    assert client.post("/connections", json={"name": "x", "kind": "databricks", "config": {}}).status_code in (404, 405)


def test_domain_settings_reference_hub_connections(client, hub):
    client.post("/domains", json={"name": "hr", "description": "People", "base_iri": BASE})
    conn = seed(hub, "warehouse", "databricks", {"host": "adb-1.azuredatabricks.net", "http_path": "/p", "catalog": "rgm", "token": "t"})
    ai = seed(hub, "gpt", "azureopenai", {"endpoint": "https://x.openai.azure.com", "deployment": "gpt-5.1", "api_key": "k"})
    r = client.put("/domains/hr", json={"connection_id": conn["id"], "ai_connection_id": ai["id"], "default_schema": "gold"})
    assert r.status_code == 200, r.text
    assert client.put("/domains/hr", json={"connection_id": str(uuid.uuid4())}).status_code == 404
    src = client.get("/domains/hr/source").json()
    assert src["kind"] == "databricks" and src["connection"] == "warehouse" and src["catalog"] == "rgm" and src["schema"] == "gold" and src["host"] == "adb-1.azuredatabricks.net"
    assert src["ai"] == {"connection": "gpt", "kind": "azureopenai", "deployment": "gpt-5.1"} and src["connections_backend"] == "hub"
    card = client.get("/domains/cards").json()[0]
    assert card["source"] == {"kind": "databricks", "connection": "warehouse", "catalog": "rgm", "schema": "gold", "schemas": ["gold"]}
    # the package deleted it in the hub; the UI then asks datagraph to drop the references
    assert client.delete(f"/connections/{conn['id']}/references").status_code == 204
    assert client.get("/domains/hr").json()["connection_id"] is None
    assert client.delete("/connections/not-a-uuid/references").status_code == 404


def test_source_facts_survive_a_connection_the_hub_no_longer_knows(client, db):
    """A stale id (deleted in the hub without the reference cleanup) must not break the screen."""
    client.post("/domains", json={"name": "hr", "description": "People", "base_iri": BASE})
    stale = str(uuid.uuid4())
    with db.transaction() as cur:
        cur.execute("UPDATE domains SET connection_id = %s, ai_connection_id = %s WHERE name = 'hr'", (stale, stale))
    src = client.get("/domains/hr/source").json()
    assert src["connection"] is None and src["kind"] == "postgres" and src["missing_connection_id"] == stale and src["ai"] is None
    assert client.get("/domains/cards").json()[0]["source"]["connection"] is None


def test_without_a_hub_the_api_says_what_to_configure(db):
    with TestClient(create_app(db=db, settings=Settings(auth_default_role="admin")), headers={"X-Actor": "alice"}) as c:
        r = c.get("/connectors")
        assert r.status_code == 503 and "ONTOFORGE_CONNECTIONS_HUB_URL" in r.json()["detail"]
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        assert c.get("/domains/hr/source").json()["connection"] is None      # no hub, no connection: still renders
        assert c.put("/domains/hr", json={"connection_id": str(uuid.uuid4())}).status_code == 503


def test_hub_client_masks_and_maps(hub):
    api = HubConnections(hub)
    c = seed(hub, "w", "azureopenai", {"endpoint": "https://x.openai.azure.com", "deployment": "d", "api_key": "key"})
    got = api.get(c["id"])
    assert got["has_secret"] is True and got["config"] == {"endpoint": "https://x.openai.azure.com", "deployment": "d"}
    res = api.test(c["id"])
    assert res["ok"] and res["title"] == "Connected" and res["detail"].splitlines()[0].startswith("authenticate: passed")
