"""Configure screen backed by the Polestar connection module (the hub) instead of the local table.

With ONTOFORGE_CONNECTIONS_HUB_URL set, /connectors and /connections proxy the hub: connector
specs come from its JSON Schemas, connections live there (secrets never touch datagraph), and
domain settings reference hub connection ids. A stub hub with the real API shape stands in.
"""
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from ontoforge.connectors.hub import HubConnections, spec_from_schema
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
    """The hub's API surface the Configure screen uses, with in-memory state."""
    app = FastAPI()
    state: dict = {"connections": {}, "tests": []}
    types = {"databricks": ("database", DBX_SCHEMA), "azureopenai": ("ai", AI_SCHEMA)}
    secret_names = lambda t: {k for k, v in types[t][1]["properties"].items() if v.get("format") == "password"}

    def out(c):
        return {**{k: v for k, v in c.items() if k != "_secrets"}, "config": {**c["config"], **{k: MASK for k in c["_secrets"]}}}

    def report(t, config):
        ok = bool(config.get("host") or config.get("endpoint")) and config.get("token", config.get("api_key")) != "bad"
        steps = [{"name": "authenticate", "status": "passed" if ok else "failed", "description": "Authenticate.", "required": True, "duration_ms": 12,
                  "summary": "3 deployment(s): a, b, c" if ok else "API key rejected", "error": None if ok else "401 from /openai/deployments: Access denied",
                  "remediation": None if ok else "Copy Key 1 or Key 2 from Keys and Endpoint."},
                 {"name": "complete", "status": "passed" if ok else "skipped", "description": "Ask for a completion.", "required": True, "duration_ms": 30 if ok else 0,
                  "summary": "Deployment answered" if ok else "A previous required step failed.", "error": None, "remediation": None}]
        return {"ok": ok, "steps": steps}

    @app.get("/connection-types")
    def list_types():
        return [{"type": t, "category": cat, "display_name": schema["title"].replace(" Connection", ""), "supports_introspection": True, "dialect": "databricks" if t == "databricks" else None} for t, (cat, schema) in types.items()]

    @app.get("/connection-types/{t}/schema")
    def schema(t: str):
        if t not in types:
            raise HTTPException(404, f"No connector installed for type {t!r}")
        return types[t][1]

    @app.post("/connection-types/test")
    def test_config(body: dict):
        missing = [k for k in types[body["type"]][1]["required"] if k not in body["config"]]
        if missing:
            raise HTTPException(422, detail={"detail": "Configuration is not valid for this connector.", "errors": [f"{m}: '{m}' is a required property" for m in missing]})
        return report(body["type"], body["config"])

    @app.post("/connections", status_code=201)
    def create(body: dict):
        if any(c["name"] == body["name"] for c in state["connections"].values()):
            raise HTTPException(409, "A connection with this name exists")
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

    @app.patch("/connections/{cid}")
    def update(cid: str, body: dict):
        c = state["connections"][cid]
        if body.get("name"): c["name"] = body["name"]
        if body.get("config") is not None:
            cfg = dict(body["config"])
            for k in secret_names(c["type"]):
                if cfg.get(k) and cfg[k] != MASK: c["_secrets"][k] = cfg[k]
                cfg.pop(k, None)
            c["config"] = cfg
        c["updated_at"] = "2026-09-21T12:30:00Z"
        return out(c)

    @app.delete("/connections/{cid}", status_code=204)
    def delete(cid: str):
        state["connections"].pop(cid, None)

    @app.post("/connections/{cid}/test")
    def test_saved(cid: str):
        c = state["connections"][cid]
        r = report(c["type"], {**c["config"], **c["_secrets"]})
        c["last_test_ok"] = r["ok"]; c["last_tested_at"] = "2026-09-21T12:45:00Z"
        return r

    return app


HUB = Settings(auth_default_role="admin", secret_key="unit-test-key", connections_hub_url="http://hub.local")


@pytest.fixture
def hub_client():
    # Starlette's TestClient is an httpx.Client with a synchronous ASGI transport.
    return TestClient(stub_hub(), base_url="http://hub.local")


@pytest.fixture
def client(db, hub_client):
    with TestClient(create_app(db=db, source_db=db, settings=HUB, hub_client=hub_client), headers={"X-Actor": "alice"}) as c:
        yield c


def test_specs_are_derived_from_the_hub_json_schemas():
    spec = spec_from_schema("databricks", "database", "Databricks SQL", DBX_SCHEMA)
    assert spec["kind"] == "databricks" and spec["category"] == "source" and spec["secret_field"] == "token"
    fields = {f["name"]: f for f in spec["fields"]}
    assert fields["host"]["required"] is True and fields["catalog"]["required"] is False and fields["catalog"]["default"] == "hive_metastore"
    assert fields["auth_type"] == {"name": "auth_type", "label": "Authentication", "kind": "select", "required": False, "default": "pat", "options": ["pat", "service_principal"], "help": None, "option_titles": {"pat": "Personal access token", "service_principal": "Azure service principal"}, "show_when": None}
    assert fields["token"]["kind"] == "password" and fields["token"]["show_when"] == {"auth_type": "pat"}
    assert fields["connect_timeout"]["kind"] == "number" and fields["connect_timeout"]["default"] == 30
    assert fields["host"]["help"] == "Workspace URL."
    ai = spec_from_schema("azureopenai", "ai", "Azure OpenAI", AI_SCHEMA)
    assert ai["category"] == "ai" and ai["secret_field"] == "api_key"


def test_connectors_and_connections_are_proxied_to_the_hub(client):
    kinds = {s["kind"]: s for s in client.get("/connectors").json()}
    assert set(kinds) == {"databricks", "azureopenai"} and kinds["azureopenai"]["category"] == "ai" and kinds["databricks"]["source"] == "hub"
    r = client.post("/connections", json={"name": "warehouse", "kind": "databricks", "config": {"host": "adb-1.azuredatabricks.net", "http_path": "/sql/1.0/warehouses/x", "catalog": "rgm"}, "secret": "dapi-secret"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["kind"] == "databricks" and c["has_secret"] is True and c["config"]["catalog"] == "rgm"
    assert "dapi-secret" not in r.text and c["config"].get("token") in (None, MASK)
    cid = c["id"]
    listed = client.get("/connections").json()
    assert [x["name"] for x in listed] == ["warehouse"] and listed[0]["source"] == "hub"
    # test against the hub: the step report becomes datagraph's result shape
    t = client.post(f"/connections/{cid}/test").json()
    assert t["ok"] is True and t["title"] == "Connected" and "3 deployment(s)" in t["detail"] and t["latency_ms"] == 42
    assert t["facts"]["steps"][0]["name"] == "authenticate"
    assert client.get(f"/connections/{cid}").json()["last_test"]["ok"] is True
    # update keeps the secret and does not echo the mask back as a value
    r = client.put(f"/connections/{cid}", json={"name": "warehouse", "config": {"host": "adb-1.azuredatabricks.net", "http_path": "/sql/1.0/warehouses/x", "catalog": "rgm", "token": MASK}})
    assert r.status_code == 200 and r.json()["has_secret"] is True and r.json()["config"]["catalog"] == "rgm"
    assert client.post("/connections", json={"name": "warehouse", "kind": "databricks", "config": {"host": "h", "http_path": "p"}}).status_code == 409
    assert client.delete(f"/connections/{cid}").status_code == 204
    assert client.get(f"/connections/{cid}").status_code == 404


def test_unsaved_config_test_and_failures_map_to_the_result_shape(client):
    good = client.post("/connections/test", json={"kind": "azureopenai", "config": {"endpoint": "https://x.openai.azure.com", "deployment": "gpt-5.1"}, "secret": "k"}).json()
    assert good["ok"] is True and good["title"] == "Connected"
    bad = client.post("/connections/test", json={"kind": "azureopenai", "config": {"endpoint": "https://x.openai.azure.com", "deployment": "gpt-5.1"}, "secret": "bad"}).json()
    assert bad["ok"] is False and bad["title"] == "API key rejected" and "401" in bad["detail"] and bad["action"].startswith("Copy Key 1")
    invalid = client.post("/connections/test", json={"kind": "azureopenai", "config": {"endpoint": "https://x"}})
    assert invalid.status_code == 400 and "deployment" in invalid.text


def test_domain_settings_reference_hub_connections(client):
    client.post("/domains", json={"name": "hr", "description": "People", "base_iri": BASE})
    conn = client.post("/connections", json={"name": "warehouse", "kind": "databricks", "config": {"host": "adb-1.azuredatabricks.net", "http_path": "/p", "catalog": "rgm"}, "secret": "t"}).json()
    ai = client.post("/connections", json={"name": "gpt", "kind": "azureopenai", "config": {"endpoint": "https://x.openai.azure.com", "deployment": "gpt-5.1"}, "secret": "k"}).json()
    r = client.put("/domains/hr", json={"connection_id": conn["id"], "ai_connection_id": ai["id"], "default_schema": "gold"})
    assert r.status_code == 200, r.text
    assert client.put("/domains/hr", json={"connection_id": str(uuid.uuid4())}).status_code == 404
    src = client.get("/domains/hr/source").json()
    assert src["kind"] == "databricks" and src["connection"] == "warehouse" and src["catalog"] == "rgm" and src["schema"] == "gold" and src["host"] == "adb-1.azuredatabricks.net"
    assert src["ai"] == {"connection": "gpt", "kind": "azureopenai", "deployment": "gpt-5.1"}
    card = client.get("/domains/cards").json()[0]
    assert card["source"] == {"kind": "databricks", "connection": "warehouse", "catalog": "rgm", "schema": "gold"}
    # deleting the hub connection detaches it from the domain
    assert client.delete(f"/connections/{conn['id']}").status_code == 204
    assert client.get("/domains/hr").json()["connection_id"] is None


def test_hub_client_maps_reports_and_masks():
    hub = HubConnections(TestClient(stub_hub(), base_url="http://hub.local"))
    c = hub.create("w", "azureopenai", {"endpoint": "https://x.openai.azure.com", "deployment": "d"}, "key")
    assert c["has_secret"] is True and c["config"] == {"endpoint": "https://x.openai.azure.com", "deployment": "d"}
    res = hub.test(c["id"])
    assert res["ok"] and res["title"] == "Connected" and res["detail"].splitlines()[0].startswith("authenticate: passed")
