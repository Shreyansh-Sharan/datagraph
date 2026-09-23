"""Profile, data-quality and glossary endpoints, against the local Postgres source."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from tests.fakes import FakeProvider
from tests.hr_fixture import seed_tables, BASE

ADMIN = Settings(auth_default_role="admin")


@pytest.fixture
def client(db):
    seed_tables(db)
    llm = FakeProvider([{"rules": [{"name": "Employee number unique", "column": "empno", "kind": "unique", "params": {}, "threshold": 1.0, "rationale": "key"}]}])
    app = create_app(db=db, source_db=db, settings=ADMIN, llm=llm)
    with TestClient(app, headers={"X-Actor": "alice"}) as c:
        yield c


def _version(client) -> str:
    d = client.post("/domains", json={"name": "hr", "description": "People", "base_iri": BASE}).json()
    v = client.post(f"/domains/{d['name']}/versions").json()
    assert client.post(f"/versions/{v['id']}/metadata/import", json={"tables": ["employees", "departments"]}).status_code == 200
    return v["id"]


def test_profile_is_computed_on_demand_and_read_back(client):
    vid = _version(client)
    assert client.get(f"/versions/{vid}/tables/employees/profile").status_code == 404
    r = client.post(f"/versions/{vid}/tables/employees/profile")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["row_count"] == 4 and p["duplicate_keys"] == 0 and {c["name"]: c["nulls"] for c in p["columns"]}["sal"] == 1
    assert client.get(f"/versions/{vid}/tables/employees/profile").json()["row_count"] == 4
    job = client.post(f"/versions/{vid}/tables/employees/profile", params={"background": "true"})
    assert job.status_code == 202 and job.json()["kind"] == "profile"
    assert client.get(f"/versions/{vid}/tables/nope/profile").status_code == 404


def test_rules_crud_run_and_ai_suggestion(client):
    vid = _version(client)
    r = client.post(f"/versions/{vid}/tables/employees/dq/rules", json={"name": "Salary present", "column": "sal", "kind": "not_null", "owner": "Domain steward"})
    assert r.status_code == 201, r.text
    rule = r.json()
    assert rule["dimension"] == "completeness" and rule["owner"] == "Domain steward"
    assert client.post(f"/versions/{vid}/tables/employees/dq/rules", json={"name": "Bad", "column": "nope", "kind": "not_null"}).status_code == 400
    st = client.get(f"/versions/{vid}/tables/employees/dq").json()
    assert st["score"] is None and st["rules"][0]["last"] is None and [c["name"] for c in st["columns"]][:2] == ["empno", "ename"]
    run = client.post(f"/versions/{vid}/tables/employees/dq/run")
    assert run.status_code == 200 and run.json()["status"] == "succeeded", run.text
    st = client.get(f"/versions/{vid}/tables/employees/dq").json()
    assert st["score"] == 0.75 and st["rules"][0]["last"]["status"] == "failing" and st["summary"] == {"passing": 0, "warning": 0, "failing": 1}
    r = client.put(f"/dq/rules/{rule['id']}", json={"threshold": 0.7, "enabled": True})
    assert r.status_code == 200 and r.json()["threshold"] == 0.7
    sug = client.post(f"/versions/{vid}/tables/employees/dq/suggest")
    assert sug.status_code == 200 and sug.json()["added"] == 1, sug.text
    assert [x["origin"] for x in client.get(f"/versions/{vid}/tables/employees/dq").json()["rules"]] == ["manual", "ai"]
    assert client.delete(f"/dq/rules/{rule['id']}").status_code == 204
    assert len(client.get(f"/versions/{vid}/tables/employees/dq").json()["rules"]) == 1
    job = client.post(f"/versions/{vid}/tables/employees/dq/run", params={"background": "true"})
    assert job.status_code == 202 and job.json()["kind"] == "dq-run"


def test_glossary_endpoints(client):
    client.post("/domains", json={"name": "hr", "description": "People", "base_iri": BASE})
    r = client.post("/domains/hr/glossary", json={"kind": "term", "name": "Employee", "definition": "A person employed by the company.", "table": "hr.employees", "columns": ["empno"], "status": "approved", "owner": "Finance BI", "class_name": "Employee"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["schema_name"] == "hr" and t["status"] == "approved"
    m = client.post("/domains/hr/glossary", json={"kind": "metric", "name": "Headcount", "definition": "Active employees", "formula": "count(*)", "unit": "people", "frequency": "Monthly", "table": "hr.employees"}).json()
    assert client.post("/domains/hr/glossary", json={"kind": "term", "name": "Employee"}).status_code == 400
    assert [x["name"] for x in client.get("/domains/hr/glossary", params={"kind": "metric"}).json()] == ["Headcount"]
    assert [x["name"] for x in client.get("/domains/hr/glossary", params={"table": "hr.employees", "q": "count"}).json()] == ["Headcount"]
    assert client.put(f"/glossary/{m['id']}", json={"status": "certified"}).json()["status"] == "certified"
    assert client.delete(f"/glossary/{t['id']}").status_code == 204
    assert [x["name"] for x in client.get("/domains/hr/glossary").json()] == ["Headcount"]
    assert client.get("/domains/nope/glossary").status_code == 404


def test_failing_rows_and_glossary_suggestions_over_the_api(db):
    seed_tables(db)
    llm = FakeProvider([{"terms": [{"name": "Manager", "definition": "The employee a person reports to.", "columns": ["manager"], "class_name": None}],
                         "metrics": [{"name": "Headcount", "definition": "Employees on payroll", "formula": "count(*)", "unit": "people", "frequency": "Monthly", "columns": []}]}])
    app = create_app(db=db, source_db=db, settings=ADMIN, llm=llm)
    with TestClient(app, headers={"X-Actor": "alice"}) as client:
        vid = _version(client)
        rule = client.post(f"/versions/{vid}/tables/employees/dq/rules", json={"name": "Salary present", "column": "sal", "kind": "not_null"}).json()
        r = client.get(f"/dq/rules/{rule['id']}/failures", params={"limit": 5})
        assert r.status_code == 200 and r.json()["columns"][:2] == ["empno", "ename"] and [row[1] for row in r.json()["rows"]] == ["ALLEN"]
        table_rule = client.post(f"/versions/{vid}/tables/employees/dq/rules", json={"name": "Rows", "kind": "row_count", "params": {"min": 1}}).json()
        assert client.get(f"/dq/rules/{table_rule['id']}/failures").status_code == 400
        client.post(f"/versions/{vid}/tables/employees/dq/run")
        st = client.get(f"/versions/{vid}/tables/employees/dq").json()
        assert [h["pass_rate"] for h in st["rules"][0]["history"]] == [0.75]
        sug = client.post(f"/versions/{vid}/tables/employees/glossary/suggest")
        assert sug.status_code == 200 and sug.json()["added"] == 2, sug.text
        names = {e["name"]: e for e in client.get("/domains/hr/glossary", params={"table": "employees"}).json()}
        assert names["Manager"]["status"] == "draft" and names["Headcount"]["status"] == "pending"


def test_rule_kinds_and_the_version_wide_overview_are_served(client):
    vid = _version(client)
    kinds = client.get("/dq/kinds").json()
    assert {k["kind"] for k in kinds} >= {"not_null", "aggregate", "valid_email", "older_than_column"} and all("params" in k and "dqx" in k for k in kinds)
    assert client.post(f"/versions/{vid}/tables/employees/dq/rules", json={"name": "Salary present", "kind": "not_null", "column": "sal"}).status_code == 201
    assert client.post(f"/versions/{vid}/tables/employees/dq/rules", json={"name": "Work email", "kind": "valid_email", "column": "ename", "params": {"filter": "sal > 0"}}).status_code == 201
    assert client.post(f"/versions/{vid}/tables/employees/dq/run").status_code == 200
    ov = client.get(f"/versions/{vid}/dq").json()
    assert ov["tables"][0]["table"] == "employees" and ov["tables"][0]["rules"] == 2 and ov["tables"][0]["score"] is not None
    assert {r["kind"] for r in ov["rules"]} == {"not_null", "valid_email"} and all(r["last"] for r in ov["rules"])
