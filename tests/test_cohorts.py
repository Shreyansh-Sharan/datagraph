"""Cohorts: saved entity groups defined by explainable criteria, evaluated by SQL, optionally materialised."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.cohorts import Cohort, CohortEngine, CohortError, Criterion, COHORT_PREDICATE
from ontoforge.config import Settings
from tests.hr_fixture import built_domain, BASE, EX

ADMIN = Settings(auth_default_role="admin")


def cohort() -> Cohort:
    return Cohort("well-paid-in-sales", EX + "Employee", criteria=(
        Criterion("attribute", EX + "salary", "gte", 700),
        Criterion("relation", EX + "worksIn", "exists"),
        Criterion("related_attribute", EX + "worksIn", "eq", "SALES", via=EX + "name"),
    ), description="Employees in SALES earning >= 700", match="all")


def test_cohort_validation():
    with pytest.raises(CohortError, match="operator"):
        Criterion("attribute", EX + "salary", "between", 1)
    with pytest.raises(CohortError, match="kind"):
        Criterion("magic", EX + "salary", "eq", 1)
    with pytest.raises(CohortError, match="via"):
        Criterion("related_attribute", EX + "worksIn", "eq", "SALES")
    with pytest.raises(CohortError, match="match"):
        Cohort("x", EX + "Employee", criteria=(Criterion("attribute", EX + "salary", "gte", 1),), match="some")
    assert Cohort.from_dict(cohort().to_dict()) == cohort()


def test_evaluate_returns_members_with_explanations(db):
    reg, store, v = built_domain(db)
    result = CohortEngine(reg, store).evaluate(v.id, cohort())
    assert [m.iri for m in result.members] == [BASE + "Employee/1"]
    smith = result.members[0]
    assert smith.label == "SMITH" and len(smith.explanation) == 3
    assert any("salary" in e and "800" in e for e in smith.explanation)
    assert any("SALES" in e for e in smith.explanation)
    assert result.total_candidates == 4 and result.size == 1


def test_match_any_and_negation(db):
    reg, store, v = built_domain(db)
    engine = CohortEngine(reg, store)
    anyc = Cohort("any", EX + "Employee", criteria=(
        Criterion("attribute", EX + "salary", "gte", 1200), Criterion("relation", EX + "reportsTo", "not_exists")), match="any")
    assert {m.iri for m in engine.evaluate(v.id, anyc).members} == {BASE + "Employee/1", BASE + "Employee/3", BASE + "Employee/4"}
    missing = Cohort("no-salary", EX + "Employee", criteria=(Criterion("attribute", EX + "salary", "missing"),))
    assert [m.iri for m in engine.evaluate(v.id, missing).members] == [BASE + "Employee/2"]
    pattern = Cohort("s-names", EX + "Employee", criteria=(Criterion("attribute", EX + "name", "matches", "^S"),))
    assert [m.iri for m in engine.evaluate(v.id, pattern).members] == [BASE + "Employee/1"]


def test_cohorts_are_stored_and_materialised(db):
    reg, store, v = built_domain(db)
    engine = CohortEngine(reg, store)
    engine.save(v.id, cohort(), actor="alice")
    assert [c.name for c in engine.list(v.id)] == ["well-paid-in-sales"]
    report = engine.materialise(v.id, "well-paid-in-sales")
    assert report.size == 1 and store.count(v.id, inferred=True) == 1
    (rel,) = [r for r in store.describe(v.id, BASE + "Employee/1").outgoing if r.predicate == COHORT_PREDICATE]
    assert rel.target == BASE + "cohort/well-paid-in-sales" and rel.inferred
    engine.materialise(v.id, "well-paid-in-sales")           # idempotent: replaces its own triples
    assert store.count(v.id, inferred=True) == 1
    engine.delete(v.id, "well-paid-in-sales", actor="alice")
    assert engine.list(v.id) == [] and store.count(v.id, inferred=True) == 0


def test_cohort_endpoints(db):
    reg, store, v = built_domain(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        r = c.post(f"/versions/{v.id}/cohorts/evaluate", json=cohort().to_dict())
        assert r.status_code == 200 and r.json()["members"][0]["iri"] == BASE + "Employee/1"
        assert c.put(f"/versions/{v.id}/cohorts/well-paid-in-sales", json=cohort().to_dict()).status_code == 200
        assert [x["name"] for x in c.get(f"/versions/{v.id}/cohorts").json()] == ["well-paid-in-sales"]
        assert c.post(f"/versions/{v.id}/cohorts/well-paid-in-sales/materialise").json()["size"] == 1
        assert c.get(f"/versions/{v.id}/cohorts/well-paid-in-sales/members").json()["size"] == 1
        bad = cohort().to_dict()
        bad["class_iri"] = EX + "Nope"
        assert c.put(f"/versions/{v.id}/cohorts/x", json=bad).status_code == 400
        assert c.delete(f"/versions/{v.id}/cohorts/well-paid-in-sales").status_code == 204
        assert c.get(f"/versions/{v.id}/cohorts/well-paid-in-sales/members").status_code == 404
