"""Data-quality constraints: authored or derived from the ontology, exported as SHACL, and
validated by SQL over the triple table (no in-memory graph)."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from ontoforge.quality import Constraint, ConstraintSet, QualityEngine, QualityError, constraints_from_ontology
from tests.hr_fixture import built_domain, ontology, mapping, seed_tables, BASE, EX
from tests.test_ontology_axioms import rich

ADMIN = Settings(auth_default_role="admin")


def cs() -> ConstraintSet:
    return ConstraintSet([
        Constraint("dept-exists", EX + "Employee", EX + "worksIn", "class", EX + "Department", message="Department must exist"),
        Constraint("has-dept", EX + "Employee", EX + "worksIn", "min_count", 1, severity="warning"),
        Constraint("name-upper", EX + "Employee", EX + "name", "pattern", "^[A-Z ]+$"),
        Constraint("salary-floor", EX + "Employee", EX + "salary", "min_inclusive", 600),
        Constraint("salary-type", EX + "Employee", EX + "salary", "datatype", "http://www.w3.org/2001/XMLSchema#decimal"),
        Constraint("one-dept", EX + "Employee", EX + "worksIn", "max_count", 1),
        Constraint("dept-names", EX + "Department", EX + "name", "in", ["SALES", "RESEARCH"]),
        Constraint("unique-name", EX + "Employee", EX + "name", "unique", True, severity="info"),
    ])


def test_constraints_round_trip_through_shacl():
    ttl = cs().to_shacl()
    assert "sh:minCount" in ttl and "sh:pattern" in ttl and "sh:in" in ttl and "sh:severity sh:Warning" in ttl
    again = ConstraintSet.from_shacl(ttl)
    assert {c.name for c in again.constraints} == {c.name for c in cs().constraints}
    by = {c.name: c for c in again.constraints}
    assert by["dept-exists"].message == "Department must exist" and by["dept-names"].value == ["SALES", "RESEARCH"]
    assert by["has-dept"].severity == "warning" and by["unique-name"].kind == "unique"


def test_constraints_round_trip_through_dict():
    assert ConstraintSet.from_dict(cs().to_dict()) == cs()


def test_invalid_constraints_are_rejected():
    with pytest.raises(QualityError, match="kind"):
        Constraint("x", EX + "Employee", EX + "name", "sparkle", 1)
    with pytest.raises(QualityError, match="severity"):
        Constraint("x", EX + "Employee", EX + "name", "min_count", 1, severity="loud")
    with pytest.raises(QualityError, match="unique"):
        ConstraintSet([Constraint("a", EX + "E", EX + "p", "min_count", 1), Constraint("a", EX + "E", EX + "p", "max_count", 1)])


def test_constraints_derived_from_ontology_axioms():
    derived = constraints_from_ontology(rich())
    kinds = {(c.target_class, c.property, c.kind, c.value) for c in derived.constraints}
    assert (EX + "Employee", EX + "worksIn", "min_count", 1) in kinds
    assert (EX + "Employee", EX + "worksIn", "max_count", 1) in kinds
    assert (EX + "Employee", EX + "reportsTo", "max_count", 1) in kinds          # functional
    assert (EX + "Employee", EX + "worksIn", "class", EX + "Department") in kinds  # range
    assert (EX + "Employee", EX + "salary", "datatype", "http://www.w3.org/2001/XMLSchema#decimal") in kinds


def test_sql_validation_finds_the_expected_violations(db):
    reg, store, v = built_domain(db)
    reg.update_content(v.id, actor="alice", quality=cs().to_dict())
    report = QualityEngine(reg, store).run(v.id, include_ontology=False)
    by = {r.name: r for r in report.results}
    assert by["dept-exists"].violations == 1 and by["dept-exists"].samples[0]["focus"] == BASE + "Employee/4"
    assert by["dept-exists"].samples[0]["message"] == "Department must exist"
    assert by["has-dept"].violations == 1 and by["has-dept"].samples[0]["focus"] == BASE + "Employee/3"
    assert by["has-dept"].severity == "warning"
    assert by["name-upper"].violations == 0 and by["name-upper"].targets == 4
    assert by["salary-floor"].violations == 1 and by["salary-floor"].samples[0]["value"] == "500"
    assert by["salary-type"].violations == 0
    assert by["one-dept"].violations == 0
    assert by["dept-names"].violations == 0 and by["dept-names"].targets == 2
    assert by["unique-name"].violations == 0
    assert report.conforms is False and report.summary == {"violation": 2, "warning": 1, "info": 0}


def test_unique_and_max_count_detect_duplicates(db):
    reg, store, v = built_domain(db)
    store.add_inferred(v.id, [(BASE + "Employee/2", EX + "name", "SMITH", "literal", None, None),
                              (BASE + "Employee/2", EX + "worksIn", BASE + "Department/10", "iri", None, None)])
    reg.update_content(v.id, actor="alice", quality=cs().to_dict())
    by = {r.name: r for r in QualityEngine(reg, store).run(v.id, include_ontology=False).results}
    assert by["unique-name"].violations == 2 and {s["focus"] for s in by["unique-name"].samples} == {BASE + "Employee/1", BASE + "Employee/2"}
    assert by["one-dept"].violations == 1 and by["one-dept"].samples[0]["focus"] == BASE + "Employee/2"


def test_ontology_derived_constraints_run_alongside_authored_ones(db):
    reg, store, v = built_domain(db)
    reg.update_content(v.id, actor="alice", ontology_ttl=rich().to_turtle())
    report = QualityEngine(reg, store).run(v.id)
    names = {r.name for r in report.results}
    assert any(n.startswith("ontology:") for n in names)
    assert next(r for r in report.results if r.name == "ontology:Employee.worksIn.class").violations == 1   # GHOST -> Dept/99


def test_quality_api(db):
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        r = c.put(f"/versions/{v['id']}/quality", json=cs().to_dict())
        assert r.status_code == 200, r.text
        assert len(c.get(f"/versions/{v['id']}/quality").json()["constraints"]) == 8
        assert "sh:NodeShape" in c.get(f"/versions/{v['id']}/quality/shacl").text
        r = c.post(f"/versions/{v['id']}/quality/import-shacl", json={"turtle": cs().to_shacl()})
        assert r.status_code == 200 and len(r.json()["constraints"]) == 8
        assert "FROM triples" in c.get(f"/versions/{v['id']}/quality/sql").text
        c.post(f"/versions/{v['id']}/builds", params={"wait": "true"})
        report = c.post(f"/versions/{v['id']}/reasoning/quality").json()
        assert report["conforms"] is False and report["summary"]["violation"] >= 2
        assert c.put(f"/versions/{v['id']}/quality", json={"constraints": [{"name": "x", "target_class": EX + "Nope",
                     "property": EX + "name", "kind": "min_count", "value": 1}]}).status_code == 400
