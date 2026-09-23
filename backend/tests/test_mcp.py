"""MCP server: the knowledge graph as tools for LLM clients."""
import json

import pytest

from ontoforge.mcp import GraphTools, create_mcp_server
from ontoforge.registry import Status
from tests.hr_fixture import built_domain, BASE, EX


@pytest.fixture
def tools(db):
    reg, store, v = built_domain(db)
    reg.transition(v.id, Status.IN_REVIEW, actor="a")
    reg.add_review(v.id, reviewer="b", approved=True)
    reg.transition(v.id, Status.PUBLISHED, actor="a")
    return GraphTools(reg, store)


def test_list_domains_reports_published_version(tools):
    (d,) = tools.list_domains()
    assert d["name"] == "hr" and d["published_version"] == 1 and d["triples"] > 0


def test_describe_ontology_is_llm_readable(tools):
    text = tools.describe_ontology("hr")
    assert "Employee" in text and "worksIn" in text and "Department" in text and "salary" in text


def test_search_and_describe_entity(tools):
    hits = tools.search_entities("hr", "smith")
    assert hits[0]["iri"] == BASE + "Employee/1"
    text = tools.describe_entity("hr", "SMITH")
    assert "SMITH" in text and "worksIn" in text and "SALES" in text
    assert "not found" in tools.describe_entity("hr", "nobody-here").lower()


def test_graphql_tools(tools):
    assert "type Employee" in tools.get_graphql_schema("hr")
    out = json.loads(tools.query_graphql("hr", '{ departments { name } }'))
    assert {d["name"] for d in out["data"]["departments"]} == {"SALES", "RESEARCH"}


def test_unknown_domain_message(tools):
    assert "unknown domain" in tools.describe_ontology("nope").lower()


def test_unpublished_domain_falls_back_to_latest_version(db):
    reg, store, v = built_domain(db)
    (d,) = GraphTools(reg, store).list_domains()
    assert d["published_version"] is None and d["version"] == 1 and d["status"] == "draft"


@pytest.mark.anyio
async def test_server_exposes_tools_over_mcp(db):
    reg, store, v = built_domain(db)
    server = create_mcp_server(GraphTools(reg, store))
    names = {t.name for t in await server.list_tools()}
    assert {"list_domains", "describe_ontology", "search_entities", "describe_entity", "query_graphql",
            "get_graphql_schema", "graph_status"} <= names
    result = await server.call_tool("search_entities", {"domain": "hr", "query": "smith"})
    assert BASE + "Employee/1" in result.content[0].text


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_an_unknown_role_is_refused_rather_than_trusted(db):
    """A caller whose role nobody established must not pass a gate that a viewer would fail."""
    from ontoforge.mcp.tools import ACTOR, GraphTools, ROLE
    from ontoforge.registry import Registry
    from ontoforge.store import TripleStore

    tools = GraphTools(Registry(db), TripleStore(db), None, None)
    a, r = ACTOR.set(None), ROLE.set(None)
    try:
        assert "nothing established who is calling" in tools._require("builder")
        assert tools._require("viewer") is not None
    finally:
        ACTOR.reset(a), ROLE.reset(r)


def test_a_role_that_is_high_enough_still_passes(db):
    from ontoforge.mcp.tools import ACTOR, GraphTools, ROLE
    from ontoforge.registry import Registry
    from ontoforge.store import TripleStore

    tools = GraphTools(Registry(db), TripleStore(db), None, None)
    a, r = ACTOR.set("alice"), ROLE.set("admin")
    try:
        assert tools._require("builder") is None
        ROLE.set("viewer")
        assert "alice is viewer" in tools._require("builder")
    finally:
        ACTOR.reset(a), ROLE.reset(r)
