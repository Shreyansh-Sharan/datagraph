"""The assistant: a model that answers through the MCP tools, acts under the caller's identity, keeps the thread."""
import asyncio
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.assistant import Assistant
from ontoforge.config import Settings
from ontoforge.llm import FakeProvider
from ontoforge.llm.provider import ChatReply, ToolCall
from ontoforge.mcp import GraphTools, create_mcp_server
from tests.hr_fixture import built_domain, seed_tables, ontology, mapping, BASE

ADMIN = Settings(auth_default_role="admin")


def test_fake_provider_plays_scripted_chat_turns():
    llm = FakeProvider([], turns=[{"tool_calls": [{"name": "list_domains", "arguments": {}}]}, {"text": "There is one domain."}])
    first = llm.chat("sys", [{"role": "user", "content": "hi"}], [])
    assert isinstance(first, ChatReply) and first.tool_calls == [ToolCall("call_1", "list_domains", {})] and first.text == ""
    assert llm.chat("sys", [], []).text == "There is one domain."
    assert llm.calls[-1]["messages"] == []


def test_assistant_answers_through_the_mcp_tools_and_keeps_the_thread(db):
    reg, store, v = built_domain(db)
    server = create_mcp_server(GraphTools(reg, store))
    llm = FakeProvider([], turns=[
        {"tool_calls": [{"name": "search_entities", "arguments": {"query": "SMITH", "domain": "hr"}}]},
        {"text": "SMITH is an employee in the hr domain."},
        {"text": "Yes, and I remember you asked about SMITH."}])
    a = Assistant(server, llm, db, max_steps=4)
    events = []
    result = asyncio.run(a.chat(actor="alice", message="Who is SMITH?", context={"domain": "hr"}, on_event=events.append))
    assert result["answer"] == "SMITH is an employee in the hr domain."
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "text"]
    assert events[0]["name"] == "search_entities" and "Employee/1" in events[1]["result"]
    assert result["tools"][0]["name"] == "search_entities"
    tools = llm.calls[0]["tools"]
    assert any(t["name"] == "describe_entity" for t in tools) and all("input_schema" in t for t in tools)   # the MCP catalogue, as is
    assert "hr" in llm.calls[0]["system"]                                                                  # the screen's context reaches the model
    # the second turn carries the whole thread
    again = asyncio.run(a.chat(actor="alice", message="Was that in hr?", conversation_id=result["conversation_id"], context={"domain": "hr"}))
    roles = [m["role"] for m in llm.calls[-1]["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant", "user"] and again["conversation_id"] == result["conversation_id"]
    convs = a.conversations("alice")
    assert len(convs) == 1 and convs[0]["title"] == "Who is SMITH?"
    thread = a.conversation(result["conversation_id"])
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant", "tool", "assistant", "user", "assistant"]


def test_assistant_acts_under_the_callers_identity_and_survives_a_tool_error(db):
    seed_tables(db)
    app = create_app(db=db, source_db=db, settings=ADMIN, llm=FakeProvider([], turns=[
        {"tool_calls": [{"name": "add_quality_rule", "arguments": {"domain": "hr", "table": "employees", "name": "Salary present", "kind": "not_null", "column": "sal"}}]},
        {"tool_calls": [{"name": "add_quality_rule", "arguments": {"domain": "hr", "table": "employees", "name": "Bad", "kind": "teleport", "column": "sal"}}]},
        {"text": "Added the salary rule; the second kind does not exist."},
        {"text": "Hello."}]))
    with TestClient(app, headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "description": "People", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        c.post(f"/versions/{v['id']}/metadata/import", json={"tables": ["employees"]})
        r = c.post("/assistant/chat", params={"stream": "false"}, json={"message": "Add a rule that salary is present", "context": {"domain": "hr"}})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["answer"].startswith("Added the salary rule") and len(out["tools"]) == 2 and "teleport" in out["tools"][1]["result"]
        rules = c.get(f"/versions/{v['id']}/tables/employees/dq").json()["rules"]
        assert [x["name"] for x in rules] == ["Salary present"] and rules[0]["created_by"] == "alice"
        # the stream carries the same story as events
        s = c.post("/assistant/chat", json={"message": "hi", "context": {"domain": "hr"}}, headers={"X-Actor": "alice"})
        assert s.status_code == 200 and s.headers["content-type"].startswith("text/event-stream")
        assert any('"type": "done"' in line for line in s.text.splitlines())
        convs = c.get("/assistant/conversations").json()
        assert len(convs) == 2 and convs[0]["title"] in ("hi", "Add a rule that salary is present")
        assert c.delete(f"/assistant/conversations/{convs[0]['id']}").status_code == 204


def test_assistant_needs_a_provider(db):
    with TestClient(create_app(db=db, source_db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        assert c.post("/assistant/chat", params={"stream": "false"}, json={"message": "hi", "context": {}}).status_code == 503


def test_tools_resolve_table_names_the_way_people_type_them(db):
    from ontoforge.build import PostgresSource
    from ontoforge.metadata import MetadataService
    from ontoforge.registry import Registry
    from ontoforge.store import TripleStore
    from types import SimpleNamespace
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="alice")
    src = PostgresSource(db)
    meta = MetadataService(reg, src.catalog, db)
    meta.import_tables(v.id, ["employees", "departments"], actor="alice")
    from ontoforge.tabledq import TableQuality
    tools = GraphTools(reg, TripleStore(db), meta, services=SimpleNamespace(tabledq=TableQuality(reg, meta, src, db), profiles=None))
    listed = tools.list_tables("hr")
    assert [t["table"] for t in listed] == ["departments", "employees"] and listed[1]["columns"] == 6 and listed[1]["rules"] == 0
    assert tools.table_quality("hr", "EMPLOYEES")["table"] == "employees"                     # case does not matter
    assert tools.table_quality("hr", "hr.employees")["table"] == "employees"                  # a longer spelling still finds it
    missing = tools.table_quality("hr", "employeez")
    assert "employeez" in missing["error"] and "departments, employees" in missing["error"]  # the real names are offered
