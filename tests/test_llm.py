"""LLM automation: provider port, structured tasks, validation of model output, API wiring."""
import json

import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.catalog import PostgresCatalog
from ontoforge.llm import (
    AnthropicProvider, FakeProvider, LLMOutputError, MappingSuggester, OntologyAssistant, OntologyDrafter,
    describe_tables,
)
from ontoforge.registry import Registry
from ontoforge.store import TripleStore
ADMIN = Settings(auth_default_role="admin")
from tests.hr_fixture import seed_tables, ontology, EX, BASE

ONTO_IRI = "http://d/hr"

DRAFT = {"label": "HR", "description": "People and org units",
         "classes": [{"name": "Employee", "label": "Employee", "description": "A person on payroll", "parents": []},
                     {"name": "Department", "label": "Department", "parents": []}],
         "datatype_properties": [{"name": "name", "label": "name", "domain": None, "range": "string"},
                                 {"name": "salary", "label": "salary", "domain": "Employee", "range": "decimal"}],
         "object_properties": [{"name": "worksIn", "label": "works in", "domain": "Employee", "range": "Department"}]}

MAPPING = {"classes": [
    {"class": "Employee", "table": "employees", "key_columns": ["empno"],
     "attributes": [{"property": "name", "column": "ename"}, {"property": "salary", "column": "sal"}]},
    {"class": "Department", "table": "departments", "key_columns": ["deptno"], "attributes": [{"property": "name", "column": "dname"}]}],
    "relations": [{"property": "worksIn", "source_class": "Employee", "target_class": "Department", "target_key": ["deptno"]}]}


def test_describe_tables_gives_the_model_columns_keys_and_samples(db):
    seed_tables(db)
    meta = describe_tables(PostgresCatalog(db), ["employees"], sample_rows=lambda t: [(1, "SMITH")])
    (t,) = meta
    assert t["table"] == "employees" and t["primary_key"] == ["empno"]
    assert any(c["name"] == "sal" and "numeric" in c["type"] for c in t["columns"])
    assert t["foreign_keys"][0]["references"] in ("departments", "employees") and t["samples"] == [[1, "SMITH"]]


def test_drafter_turns_model_json_into_an_ontology():
    provider = FakeProvider([DRAFT])
    onto = OntologyDrafter(provider).draft(ONTO_IRI, tables=[{"table": "employees", "columns": []}], description="HR data")
    assert set(onto.classes) == {ONTO_IRI + "#Employee", ONTO_IRI + "#Department"}
    assert onto.object_properties[ONTO_IRI + "#worksIn"].range == ONTO_IRI + "#Department"
    assert onto.datatype_properties[ONTO_IRI + "#salary"].range.endswith("#decimal")
    assert onto.datatype_properties[ONTO_IRI + "#name"].domain is None
    system, user, schema = provider.calls[0]
    assert "employees" in user and schema["type"] == "object" and "classes" in schema["properties"]


def test_drafter_rejects_dangling_references():
    bad = {**DRAFT, "object_properties": [{"name": "x", "domain": "Employee", "range": "Ghost"}]}
    with pytest.raises(LLMOutputError, match="Ghost"):
        OntologyDrafter(FakeProvider([bad])).draft(ONTO_IRI, tables=[], description="")


def test_suggester_validates_against_catalog_and_ontology(db):
    seed_tables(db)
    onto = OntologyDrafter(FakeProvider([DRAFT])).draft(ONTO_IRI, tables=[], description="")
    tables = describe_tables(PostgresCatalog(db))
    spec = MappingSuggester(FakeProvider([MAPPING])).suggest(onto, tables, base_iri=BASE)
    assert spec.classes[0].class_iri == ONTO_IRI + "#Employee" and spec.relations[0].target_key == ("deptno",)
    bad = json.loads(json.dumps(MAPPING))
    bad["classes"][0]["attributes"][0]["column"] = "nope"
    with pytest.raises(LLMOutputError, match="nope"):
        MappingSuggester(FakeProvider([bad])).suggest(onto, tables, base_iri=BASE)
    bad = json.loads(json.dumps(MAPPING))
    bad["classes"][0]["class"] = "Alien"
    with pytest.raises(LLMOutputError, match="Alien"):
        MappingSuggester(FakeProvider([bad])).suggest(onto, tables, base_iri=BASE)


def test_suggested_mapping_is_buildable(db):
    seed_tables(db)
    onto = OntologyDrafter(FakeProvider([DRAFT])).draft(ONTO_IRI, tables=[], description="")
    spec = MappingSuggester(FakeProvider([MAPPING])).suggest(onto, describe_tables(PostgresCatalog(db)), base_iri=BASE)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="a")
    reg.update_content(v.id, actor="a", ontology_ttl=onto.to_turtle(), mapping=spec.to_dict())
    store = TripleStore(db)
    assert BuildPipeline(reg, store, PostgresSource(db)).run(v.id).status == "succeeded"
    assert dict(store.type_inventory(v.id))[ONTO_IRI + "#Employee"] == 4


def test_assistant_applies_natural_language_edit():
    edited = json.loads(json.dumps(DRAFT))
    edited["classes"].append({"name": "Manager", "label": "Manager", "parents": ["Employee"]})
    provider = FakeProvider([edited])
    onto = OntologyAssistant(provider).edit(ontology(), "Add a Manager subclass of Employee")
    assert onto.classes["http://d/hr#Manager"].parents == ("http://d/hr#Employee",)
    system, user, _ = provider.calls[0]
    assert "Manager subclass" in user and "owl:Class" in user  # current ontology is passed as Turtle


class StubMessages:
    def __init__(self, payload):
        self.payload, self.kwargs = payload, None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        payload = self.payload

        class _Block:
            type = "text"
            text = json.dumps(payload)

        class _Msg:
            content = [_Block()]
            stop_reason = "end_turn"

        class _Stream:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def get_final_message(self_inner):
                return _Msg()

        return _Stream()


class StubBeta:
    def __init__(self, payload):
        self.messages = StubMessages(payload)


class StubClient:
    def __init__(self, payload):
        self.beta = StubBeta(payload)


def test_anthropic_provider_uses_structured_output_and_adaptive_thinking():
    client = StubClient({"ok": True})
    out = AnthropicProvider(client=client).complete_json("sys", "user", {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                                          "required": ["ok"], "additionalProperties": False})
    assert out == {"ok": True}
    kw = client.beta.messages.kwargs
    assert kw["model"] == "claude-opus-5" and kw["system"] == "sys"
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["thinking"] == {"type": "adaptive"}
    assert kw["messages"] == [{"role": "user", "content": "user"}]
    assert kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in kw["betas"]


def test_api_llm_endpoints(db):
    seed_tables(db)
    app = create_app(db=db, settings=ADMIN, llm=FakeProvider([DRAFT, MAPPING]))
    with TestClient(app, headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        r = c.post(f"/versions/{v['id']}/llm/draft-ontology", json={"ontology_iri": ONTO_IRI, "description": "HR"})
        assert r.status_code == 200, r.text
        assert r.json()["classes"] == 2
        r = c.post(f"/versions/{v['id']}/llm/suggest-mapping", json={})
        assert r.status_code == 200, r.text
        assert r.json()["relations"] == 1
        assert c.post(f"/versions/{v['id']}/builds").json()["status"] == "succeeded"


def test_api_without_llm_configured_returns_503(db):
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        assert c.post(f"/versions/{v['id']}/llm/draft-ontology", json={"ontology_iri": ONTO_IRI}).status_code == 503
