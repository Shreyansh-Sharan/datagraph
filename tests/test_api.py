"""REST API over the whole backend, exercised through FastAPI's test client on a live Postgres."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
ADMIN = Settings(auth_default_role="admin")
from tests.hr_fixture import seed_tables, ontology, mapping, BASE, EX


@pytest.fixture
def client(db):
    seed_tables(db)
    app = create_app(db=db, source_db=db, settings=ADMIN)
    with TestClient(app, headers={"X-Actor": "alice"}) as c:
        yield c


def make_domain(client, name="hr") -> dict:
    r = client.post("/domains", json={"name": name, "description": "People", "base_iri": BASE})
    assert r.status_code == 201, r.text
    return r.json()


def make_draft(client, domain) -> dict:
    v = client.post(f"/domains/{domain['name']}/versions").json()
    r = client.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
    assert r.status_code == 200, r.text
    r = client.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
    assert r.status_code == 200, r.text
    return v


def test_health_and_domain_crud(client):
    assert client.get("/health").json()["status"] == "ok"
    d = make_domain(client)
    assert client.get("/domains").json()[0]["name"] == "hr"
    assert client.get("/domains/hr").json()["base_iri"] == BASE
    assert client.post("/domains", json={"name": "hr", "base_iri": BASE}).status_code == 409
    assert client.delete("/domains/hr").status_code == 204
    assert client.get("/domains/hr").status_code == 404


def test_version_content_and_lifecycle(client):
    d = make_domain(client)
    v = make_draft(client, d)
    got = client.get(f"/versions/{v['id']}").json()
    assert got["status"] == "draft" and got["version"] == 1 and got["has_ontology"] and got["has_mapping"]
    assert client.get(f"/versions/{v['id']}/ontology").json()["classes"][0]["iri"].startswith(EX)
    assert not [i for i in client.get(f"/versions/{v['id']}/ontology/checks").json() if i["severity"] == "error"]
    assert client.post(f"/versions/{v['id']}/transition", json={"to": "published"}).status_code == 409
    assert client.post(f"/versions/{v['id']}/transition", json={"to": "in_review"}).status_code == 200
    assert client.post(f"/versions/{v['id']}/reviews", json={"approved": True, "comment": "ok"},
                       headers={"X-Actor": "bob"}).status_code == 201
    assert client.post(f"/versions/{v['id']}/transition", json={"to": "published"}).json()["status"] == "published"
    assert client.put(f"/versions/{v['id']}/ontology", json={"turtle": "# x"}).status_code == 409
    assert [e["action"] for e in client.get(f"/versions/{v['id']}/audit").json()][-1] == "status.published"


def test_lease_conflict_returns_423(client):
    d = make_domain(client)
    v = make_draft(client, d)
    assert client.post(f"/versions/{v['id']}/lease", json={"ttl_seconds": 600}).status_code == 200
    r = client.post(f"/versions/{v['id']}/lease", json={"ttl_seconds": 600}, headers={"X-Actor": "bob"})
    assert r.status_code == 423 and "alice" in r.json()["detail"]
    assert client.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict(), headers={"X-Actor": "bob"}).status_code == 423
    assert client.delete(f"/versions/{v['id']}/lease").status_code == 204


def test_build_and_explore(client):
    d = make_domain(client)
    v = make_draft(client, d)
    run = client.post(f"/versions/{v['id']}/builds").json()
    assert run["status"] == "succeeded", run
    assert client.get(f"/versions/{v['id']}/builds").json()[0]["id"] == run["id"]
    status = client.get(f"/versions/{v['id']}/graph/status").json()
    assert status["triples"] == run["triple_count"] and status["types"][EX + "Employee"] == 4
    hits = client.get(f"/versions/{v['id']}/graph/search", params={"q": "smith"}).json()
    assert hits[0]["iri"] == BASE + "Employee/1"
    entity = client.get(f"/versions/{v['id']}/graph/entity", params={"iri": BASE + "Employee/1"}).json()
    assert {a["predicate"] for a in entity["attributes"]} >= {EX + "name", EX + "salary"}
    sub = client.get(f"/versions/{v['id']}/graph/neighbourhood", params={"iri": BASE + "Employee/1", "depth": 2}).json()
    assert len(sub["nodes"]) >= 4 and len(sub["edges"]) >= 3
    assert client.get(f"/versions/{v['id']}/graph/entity", params={"iri": "http://nope"}).status_code == 404


def test_compiled_sql_preview_and_r2rml(client):
    d = make_domain(client)
    v = make_draft(client, d)
    r = client.get(f"/versions/{v['id']}/mapping/sql", params={"dialect": "databricks"})
    assert r.status_code == 200 and "`employees`" in r.text and "UNION ALL" in r.text
    r = client.get(f"/versions/{v['id']}/mapping/r2rml")
    assert r.status_code == 200 and "TriplesMap" in r.text


def test_reasoning_endpoints(client):
    d = make_domain(client)
    v = make_draft(client, d)
    client.post(f"/versions/{v['id']}/builds")
    report = client.post(f"/versions/{v['id']}/reasoning/validate").json()
    assert report["conforms"] is False and report["results"][0]["focus"].startswith(BASE)
    inf = client.post(f"/versions/{v['id']}/reasoning/infer").json()
    assert inf["inferred"] > 0
    assert client.post(f"/versions/{v['id']}/reasoning/validate").json()["conforms"] is True
    assert "sh:NodeShape" in client.get(f"/versions/{v['id']}/reasoning/shapes").text


def test_graphql_endpoint(client):
    d = make_domain(client)
    v = make_draft(client, d)
    client.post(f"/versions/{v['id']}/builds")
    r = client.post(f"/versions/{v['id']}/graphql", json={"query": '{ employees(search: "SMITH") { name worksIn { name } } }'})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["employees"] == [{"name": "SMITH", "worksIn": [{"name": "SALES"}]}]
    assert "type Employee" in client.get(f"/versions/{v['id']}/graphql/schema").text


def test_catalog_and_autodraft(client):
    d = make_domain(client)
    v = client.post("/domains/hr/versions").json()
    tables = client.get("/catalog/tables").json()
    assert "employees" in tables
    cols = client.get("/catalog/tables/employees").json()
    assert cols["primary_key"] == ["empno"] and any(c["name"] == "ename" for c in cols["columns"])
    r = client.post(f"/versions/{v['id']}/autodraft", json={"ontology_iri": "http://d/hr"})
    assert r.status_code == 200 and r.json()["classes"] >= 3
    assert client.get(f"/versions/{v['id']}").json()["has_mapping"]
    assert client.post(f"/versions/{v['id']}/builds").json()["status"] == "succeeded"
