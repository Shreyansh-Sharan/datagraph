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
    # a slip on one column drops that binding and reports it; the rest of the suggestion survives
    bad = json.loads(json.dumps(MAPPING))
    bad["classes"][0]["attributes"][0]["column"] = "nope"
    s = MappingSuggester(FakeProvider([bad]))
    spec = s.suggest(onto, tables, base_iri=BASE)
    assert len(spec.classes) == len(MAPPING["classes"]) and len(s.skipped) == 1 and "nope" in s.skipped[0]
    # a class the ontology does not have is dropped with everything that hangs off it
    bad = json.loads(json.dumps(MAPPING))
    bad["classes"][0]["class"] = "Alien"
    s = MappingSuggester(FakeProvider([bad]))
    spec = s.suggest(onto, tables, base_iri=BASE)
    assert len(spec.classes) == len(MAPPING["classes"]) - 1 and any("Alien" in x for x in s.skipped)
    # only an answer with nothing usable is an error
    with pytest.raises(LLMOutputError, match="nothing usable"):
        MappingSuggester(FakeProvider([{"classes": [{"class": "Alien", "table": "employees", "key_columns": ["empno"]}], "relations": []}])).suggest(onto, tables, base_iri=BASE)


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
        assert c.post(f"/versions/{v['id']}/builds", params={"wait": "true"}).json()["status"] == "succeeded"


def test_api_without_llm_configured_returns_503(db):
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        assert c.post(f"/versions/{v['id']}/llm/draft-ontology", json={"ontology_iri": ONTO_IRI}).status_code == 503


def test_describe_tables_qualifies_names_with_the_schema():
    from ontoforge.llm import describe_tables

    class Cat:
        def table_comment(self, t): return None
        def column_details(self, t): return [{"name": "id", "type": "int", "comment": None}]
        def primary_key(self, t): return ("id",)
        def foreign_keys(self, t): return []
        def list_tables(self, schema=None): return []
    metas = describe_tables(Cat(), ["customer", "sales.store", "cat.sales.order"], "cat.sales")
    assert [m["table"] for m in metas] == ["cat.sales.customer", "sales.store", "cat.sales.order"]


def test_guarded_sampler_stops_after_the_first_failure():
    from ontoforge.llm import guarded_sampler
    calls = []

    def fetch(table):
        calls.append(table)
        raise PermissionError("no SELECT")
    sample = guarded_sampler(fetch)
    assert sample("a") == [] and sample("b") == [] and calls == ["a"]   # one failed attempt, then no more source round trips

    ok = guarded_sampler(lambda t: [(1,)])
    assert ok("a") == [(1,)] and ok("b") == [(1,)]


def test_ai_tasks_can_run_in_the_background_with_progress(db):
    """A long AI task returns a job at once; polling shows what it is doing and finally the result."""
    import time
    seed_tables(db)
    app = create_app(db=db, settings=ADMIN, llm=FakeProvider([DRAFT, MAPPING]))
    with TestClient(app, headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        r = c.post(f"/versions/{v['id']}/llm/draft-ontology", params={"background": "true"}, json={"ontology_iri": ONTO_IRI, "description": "HR"})
        assert r.status_code == 202, r.text
        job = r.json()
        assert job["kind"] == "draft-ontology" and job["status"] in ("running", "succeeded") and job["version_id"] == v["id"]
        for _ in range(100):
            job = c.get(f"/jobs/{job['id']}").json()
            if job["status"] != "running":
                break
            time.sleep(0.05)
        assert job["status"] == "succeeded", job
        assert job["result"]["classes"] == 2 and job["finished_at"] and "table" in (job["progress"] or "").lower() or job["progress"]
        r = c.post(f"/versions/{v['id']}/llm/suggest-mapping", params={"background": "true"}, json={})
        assert r.status_code == 202
        latest = c.get(f"/versions/{v['id']}/jobs", params={"kind": "suggest-mapping"}).json()
        assert latest and latest["id"] == r.json()["id"]
        for _ in range(100):
            job = c.get(f"/jobs/{r.json()['id']}").json()
            if job["status"] != "running":
                break
            time.sleep(0.05)
        assert job["status"] == "succeeded" and job["result"]["relations"] == 1
        assert c.get("/jobs/00000000-0000-0000-0000-000000000000").status_code == 404
        assert c.get(f"/versions/{v['id']}/jobs", params={"kind": "nothing"}).json() is None


def test_a_failing_background_task_reports_its_error(db):
    seed_tables(db)
    app = create_app(db=db, settings=ADMIN, llm=FakeProvider([]))     # nothing to answer with: the provider raises
    with TestClient(app, headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        job = c.post(f"/versions/{v['id']}/llm/draft-ontology", params={"background": "true"}, json={"ontology_iri": ONTO_IRI}).json()
        import time
        for _ in range(100):
            job = c.get(f"/jobs/{job['id']}").json()
            if job["status"] != "running":
                break
            time.sleep(0.05)
        assert job["status"] == "failed" and job["error"]


def test_suggested_mapping_skips_unknown_names_instead_of_failing(db):
    """A big ontology makes the model slip on a name now and then: keep what is valid, report the rest."""
    from ontoforge.llm import mapping_from_json
    onto = ontology()
    tables = [{"table": "employees", "comment": None, "columns": [{"name": "empno", "type": "int"}, {"name": "ename", "type": "text"}], "primary_key": ["empno"], "foreign_keys": [], "samples": []},
              {"table": "departments", "comment": None, "columns": [{"name": "deptno", "type": "int"}], "primary_key": ["deptno"], "foreign_keys": [], "samples": []}]
    data = {"classes": [
        {"class": "Employee", "table": "employees", "key_columns": ["empno"], "attributes": [{"property": "name", "column": "ename"}, {"property": "name", "column": "nope"}, {"property": "ghost", "column": "ename"}]},
        {"class": "Unicorn", "table": "employees", "key_columns": ["empno"], "attributes": []},
        {"class": "Department", "table": "no_such_table", "key_columns": ["deptno"], "attributes": []},
    ], "relations": [{"property": "worksIn", "source_class": "Employee", "target_class": "Department", "source_key": ["deptno"], "target_key": ["deptno"]}]}
    skipped: list[str] = []
    spec = mapping_from_json(onto, tables, BASE, data, skipped=skipped)
    assert [c.class_iri for c in spec.classes] == [EX + "Employee"]
    assert [a.column for a in spec.classes[0].attributes] == ["ename"]
    assert spec.relations == ()
    assert len(skipped) == 5 and any("Unicorn" in s for s in skipped) and any("no_such_table" in s for s in skipped)
    import pytest
    with pytest.raises(LLMOutputError, match="nothing usable"):
        mapping_from_json(onto, tables, BASE, {"classes": [{"class": "Unicorn", "table": "employees", "key_columns": ["empno"]}]})


def test_suggested_mapping_drops_only_the_uncompilable_parts(db):
    """A relation joining on the wrong number of key columns must not void the sixty classes around it."""
    from ontoforge.llm import mapping_from_json
    onto = ontology()
    tables = [{"table": "employees", "comment": None, "columns": [{"name": "empno", "type": "int"}, {"name": "deptno", "type": "int"}, {"name": "ename", "type": "text"}], "primary_key": ["empno"], "foreign_keys": [], "samples": []},
              {"table": "departments", "comment": None, "columns": [{"name": "deptno", "type": "int"}, {"name": "region", "type": "text"}], "primary_key": ["deptno", "region"], "foreign_keys": [], "samples": []}]
    data = {"classes": [
        {"class": "Employee", "table": "employees", "key_columns": ["empno"], "attributes": [{"property": "name", "column": "ename"}]},
        {"class": "Department", "table": "departments", "key_columns": ["deptno", "region"], "attributes": []},
    ], "relations": [
        {"property": "worksIn", "source_class": "Employee", "target_class": "Department", "source_key": ["empno"], "target_key": ["deptno"]},   # 1 column for a 2-column key
    ]}
    skipped: list[str] = []
    spec = mapping_from_json(onto, tables, BASE, data, skipped=skipped)
    assert [c.class_iri for c in spec.classes] == [EX + "Employee", EX + "Department"]
    assert spec.relations == () and len(skipped) == 1 and "worksIn" in skipped[0] and "key" in skipped[0]
    spec.to_r2rml()   # what is left compiles


def _rel_fixture():
    from ontoforge.mapping import ClassMapping, MappingSpec
    onto = ontology()
    spec = MappingSpec(base_iri=BASE, classes=(
        ClassMapping(EX + "Employee", table="employees", key_columns=("empno",)),
        ClassMapping(EX + "Department", table="departments", key_columns=("deptno",))), relations=())
    tables = [
        {"table": "employees", "comment": None, "columns": [{"name": "empno", "type": "int"}, {"name": "ename", "type": "text"}, {"name": "deptno", "type": "int"}, {"name": "mgr", "type": "int"}],
         "primary_key": ["empno"], "foreign_keys": [{"columns": ["deptno"], "references": "departments", "referenced_columns": ["deptno"]}], "samples": []},
        {"table": "departments", "comment": None, "columns": [{"name": "deptno", "type": "int"}, {"name": "dname", "type": "text"}], "primary_key": ["deptno"], "foreign_keys": [], "samples": []},
        {"table": "collaborations", "comment": None, "columns": [{"name": "emp_a", "type": "int"}, {"name": "emp_b", "type": "int"}], "primary_key": ["emp_a", "emp_b"], "foreign_keys": [], "samples": []},
    ]
    return onto, spec, tables


def test_relations_are_filled_from_declared_keys_then_the_model_one_pair_of_tables_at_a_time():
    from ontoforge.llm import RelationSuggester
    onto, spec, tables = _rel_fixture()
    answer = {"relations": [
        {"property": "reportsTo", "source_class": "Employee", "column": "mgr", "link_table": None, "link_source_column": None, "link_target_column": None},
        {"property": "manages", "source_class": "Employee", "column": "nope", "link_table": None, "link_source_column": None, "link_target_column": None},
        {"property": "collaboratesWith", "source_class": "Employee", "column": None, "link_table": "collaborations", "link_source_column": "emp_a", "link_target_column": "emp_b"},
    ]}
    provider = FakeProvider([answer])
    s = RelationSuggester(provider)
    out = s.suggest(onto, spec, tables)
    rels = {r.property_iri.split("#")[-1]: r for r in out.relations}
    assert rels["worksIn"].target_key == ("deptno",) and rels["worksIn"].source_key == ("empno",)          # declared foreign key, no model needed
    assert rels["reportsTo"].target_key == ("mgr",)                                                          # the model, from the two tables only
    assert rels["collaboratesWith"].table == "collaborations" and rels["collaboratesWith"].source_key == ("emp_a",) and rels["collaboratesWith"].target_key == ("emp_b",)
    assert "manages" not in rels and any("manages" in x and "nope" in x for x in s.report["skipped"])
    assert s.report["declared"] == ["worksIn"] and set(s.report["ai"]) == {"reportsTo", "collaboratesWith"}
    assert len(provider.calls) == 1 and "employees" in provider.calls[0][1] and "salespersonquota" not in provider.calls[0][1]
    out.to_r2rml()
    # a second run has nothing left to ask
    s2 = RelationSuggester(FakeProvider([]))
    again = s2.suggest(onto, out, tables)
    assert len(again.relations) == len(out.relations) and s2.report["ai"] == []


def test_relations_without_a_provider_use_declared_keys_and_names_only():
    from ontoforge.llm import RelationSuggester
    onto, spec, tables = _rel_fixture()
    s = RelationSuggester(None)
    out = s.suggest(onto, spec, tables)
    assert [r.property_iri.split("#")[-1] for r in out.relations] == ["worksIn"]
    assert {u.split(" ")[0] for u in s.report["unmappable"]} == {"reportsTo", "manages", "collaboratesWith"}   # need the model
    # a self-relationship never uses the class's own key column as the foreign key
    assert all(r.target_key != ("empno",) for r in out.relations)


def test_api_fill_relations(db):
    seed_tables(db)
    app = create_app(db=db, settings=ADMIN, llm=FakeProvider([{"relations": []}]))
    with TestClient(app, headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        from tests.hr_fixture import ontology as onto_fx, mapping as map_fx
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": onto_fx().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=map_fx().to_dict())
        r = c.post(f"/versions/{v['id']}/llm/suggest-relations", json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) >= {"added", "declared", "by_name", "ai", "skipped", "unmappable"}
