"""MCP parity: session domain, versions, design status, entity types/context, per-domain policy, HTTP."""
import json

import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from ontoforge.mcp import GraphTools, create_mcp_server, MCP_TOOLS
from ontoforge.registry import Status
from tests.hr_fixture import built_domain, BASE, EX

ADMIN = Settings(auth_default_role="admin")


@pytest.fixture
def tools(db):
    reg, store, v = built_domain(db)
    return GraphTools(reg, store), reg, v


def test_select_domain_sets_the_session_default(tools):
    t, reg, v = tools
    assert "no domain selected" in t.describe_ontology().lower()
    out = t.select_domain("hr")
    assert out["selected"] == "hr" and out["version"] == 1 and "hr" in t.describe_ontology()
    assert "unknown domain" in t.select_domain("nope")["error"].lower()


def test_list_domain_versions_and_design_status(tools):
    t, reg, v = tools
    versions = t.list_domain_versions("hr")
    assert versions[0]["version"] == 1 and versions[0]["status"] == "draft" and versions[0]["built"] is True
    status = t.get_design_status("hr")
    assert status["ontology"] is True and status["mapping"]["completion"] > 0 and status["built"] is True
    assert status["triples"] > 0 and status["build_ready"] is True and status["drift_issues"] == 0


def test_list_entity_types_and_entity_context(tools):
    t, reg, v = tools
    types = t.list_entity_types("hr")
    assert {x["type"]: x["instances"] for x in types["types"]}[EX + "Employee"] == 4
    assert types["total_triples"] > 0 and any(p["predicate"] == EX + "worksIn" for p in types["predicates"])
    ctx = t.get_entity_context("hr", BASE + "Employee/1")
    assert ctx["iri"] == BASE + "Employee/1" and ctx["types"] == [EX + "Employee"]
    assert ctx["source"]["table"] == "employees" and ctx["source"]["key_columns"] == ["empno"]
    assert ctx["degree"]["outgoing"] >= 2 and ctx["degree"]["incoming"] >= 2
    assert "not found" in t.get_entity_context("hr", "http://nope")["error"].lower()


def test_policy_disables_tools_and_hides_domains(tools):
    t, reg, v = tools
    d = reg.get_domain("hr")
    reg.set_mcp_policy(d.id, {"exposed": True, "disabled_tools": ["query_graphql"]})
    assert "disabled" in t.query_graphql("hr", "{ departments { name } }").lower()
    assert "type Employee" in t.get_graphql_schema("hr")
    reg.set_mcp_policy(d.id, {"exposed": False})
    assert t.list_domains() == []
    assert "unknown domain" in t.describe_ontology("hr").lower()
    assert reg.get_domain("hr").mcp_policy == {"exposed": False}


def test_policy_rejects_unknown_tool_names(tools):
    t, reg, v = tools
    with pytest.raises(ValueError, match="fly"):
        reg.set_mcp_policy(reg.get_domain("hr").id, {"disabled_tools": ["fly"]})


@pytest.mark.anyio
async def test_server_registers_the_full_tool_surface(db):
    reg, store, v = built_domain(db)
    server = create_mcp_server(GraphTools(reg, store))
    names = {t.name for t in await server.list_tools()}
    assert set(MCP_TOOLS) <= names
    result = await server.call_tool("select_domain", {"domain": "hr"})
    assert "hr" in result.content[0].text
    result = await server.call_tool("get_design_status", {})
    assert "build_ready" in result.content[0].text


def test_policy_api_and_http_mount(db):
    reg, store, v = built_domain(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        r = c.put("/domains/hr/mcp-policy", json={"exposed": True, "disabled_tools": ["query_graphql"]})
        assert r.status_code == 200 and r.json()["disabled_tools"] == ["query_graphql"]
        assert c.get("/domains/hr/mcp-policy").json()["exposed"] is True
        assert c.put("/domains/hr/mcp-policy", json={"disabled_tools": ["fly"]}).status_code == 400
        assert c.get("/domains/hr").json()["mcp_policy"]["exposed"] is True
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        assert c.post("/mcp", json=init, headers={**headers, "X-Actor": ""}).status_code == 401
        r = c.post("/mcp", json=init, headers=headers)
        assert r.status_code == 200, r.text
        assert "ontoforge" in r.text


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_the_stdio_server_carries_the_same_services_and_a_caller(db, monkeypatch):
    """Over stdio a desktop client must reach the whole backend, as the HTTP transport does."""
    from ontoforge.api.app import stdio_mcp_server
    from ontoforge.config import Settings
    from ontoforge.mcp.tools import ACTOR, ROLE

    monkeypatch.setenv("ONTOFORGE_MCP_ACTOR", "desktop")
    server = stdio_mcp_server(db, Settings(auth_default_role="admin"))
    assert ACTOR.get() == "desktop" and ROLE.get() == "admin"

    tools = server.ontoforge_tools                     # the same GraphTools the HTTP app serves
    assert tools.services is not None                  # profiles, quality, glossary, builds, sources
    for name in ("profiles", "tabledq", "glossary", "scheduler", "sources", "jobs"):
        assert getattr(tools.services, name, None) is not None, name
    out = tools.create_domain("stdio-demo", "http://example.org/stdio/", description="made over stdio")
    assert out.get("name") == "stdio-demo", out


def test_without_a_caller_the_stdio_server_refuses_to_start(db, monkeypatch):
    from ontoforge.api.app import stdio_mcp_server
    from ontoforge.config import Settings

    monkeypatch.delenv("ONTOFORGE_MCP_ACTOR", raising=False)
    with pytest.raises(ValueError, match="ONTOFORGE_MCP_ACTOR"):
        stdio_mcp_server(db, Settings())
