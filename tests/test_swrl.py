"""SWRL rules: presentation-syntax parsing, SQL compilation over the triple table, fixpoint
materialisation, violation reporting, storage on the version, API."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.compiler import RDF_TYPE
from ontoforge.config import Settings
from ontoforge.rules import Rule, RuleError, RuleEngine, parse_rule, RuleSet
from tests.hr_fixture import built_domain, ontology, mapping, seed_tables, BASE, EX

ADMIN = Settings(auth_default_role="admin")
HIGH = "Employee(?e) ^ salary(?e, ?s) ^ swrlb:greaterThan(?s, 1000) -> HighEarner(?e)"
CHAIN = "HighEarner(?e) ^ reportsTo(?e, ?m) -> managesHighEarner(?m, ?e)"
LOW = "Employee(?e) ^ salary(?e, ?s) ^ swrlb:lessThan(?s, 600) -> Underpaid(?e)"


def onto():
    o = ontology()
    o.new_class("HighEarner", parents=(EX + "Employee",))
    o.new_class("Underpaid")
    from ontoforge.ontology import ObjectProperty
    o.add_object_property(ObjectProperty(EX + "managesHighEarner", "manages high earner", domain=EX + "Employee", range=EX + "Employee"))
    return o


def test_parse_resolves_names_against_the_ontology():
    r = parse_rule(HIGH, onto(), name="high")
    assert r.name == "high"
    kinds = [a.kind for a in r.body]
    assert kinds == ["class", "property", "builtin"]
    assert r.body[0].predicate == EX + "Employee" and r.body[0].args == ("?e",)
    assert r.body[1].predicate == EX + "salary" and r.body[1].args == ("?e", "?s")
    assert r.body[2].predicate == "greaterThan" and r.body[2].args == ("?s", 1000)
    assert r.head[0].predicate == EX + "HighEarner"
    assert r.to_text(onto()) == HIGH


def test_parse_rejects_unknown_terms_and_unbound_head_variables():
    with pytest.raises(RuleError, match="Ghost"):
        parse_rule("Ghost(?e) -> Employee(?e)", onto())
    with pytest.raises(RuleError, match="swrlb:fly"):
        parse_rule("Employee(?e) ^ swrlb:fly(?e) -> HighEarner(?e)", onto())
    with pytest.raises(RuleError, match=r"\?z"):
        parse_rule("Employee(?e) -> reportsTo(?e, ?z)", onto())
    with pytest.raises(RuleError, match="->"):
        parse_rule("Employee(?e)", onto())


def test_string_literal_and_iri_constants():
    r = parse_rule('Employee(?e) ^ name(?e, "SMITH") ^ swrlb:notEqual(?e, <http://d/hr/Employee/9>) -> HighEarner(?e)', onto())
    assert r.body[1].args == ("?e", "SMITH") and r.body[2].args == ("?e", "http://d/hr/Employee/9")


def test_sql_compiles_to_joins_over_the_triple_table():
    sql = RuleEngine.compile_select(parse_rule(HIGH, onto()), "00000000-0000-0000-0000-000000000000")
    assert sql.count("FROM triples") == 1 and sql.count("JOIN triples") == 1
    assert "object_type = 'literal'" in sql and "> 1000" in sql
    assert f"'{RDF_TYPE}'" in sql and f"'{EX}salary'" in sql


def test_materialise_infers_and_reaches_fixpoint(db):
    reg, store, v = built_domain(db)
    reg.update_content(v.id, actor="alice", ontology_ttl=onto().to_turtle(),
                       rules=RuleSet([Rule.from_text(HIGH, onto(), "high"), Rule.from_text(CHAIN, onto(), "chain")]).to_dict())
    report = RuleEngine(reg, store).materialise(v.id)
    assert report.materialised == 2 and report.iterations == 2 and report.per_rule == {"high": 1, "chain": 1}
    ward, smith = store.describe(v.id, BASE + "Employee/3"), store.describe(v.id, BASE + "Employee/1")
    assert EX + "HighEarner" in ward.types
    assert (EX + "managesHighEarner", BASE + "Employee/3") in {(r.predicate, r.target) for r in smith.outgoing}
    assert store.count(v.id, inferred=True) == 2
    assert RuleEngine(reg, store).materialise(v.id).materialised == 0    # idempotent


def test_violation_rules_report_bindings_without_writing(db):
    reg, store, v = built_domain(db)
    rs = RuleSet([Rule.from_text(LOW, onto(), "underpaid", mode="violation")])
    reg.update_content(v.id, actor="alice", ontology_ttl=onto().to_turtle(), rules=rs.to_dict())
    engine = RuleEngine(reg, store)
    before = store.count(v.id)
    report = engine.check(v.id)
    assert report.violations == [{"rule": "underpaid", "bindings": {"e": BASE + "Employee/4", "s": "500"}}]
    assert store.count(v.id) == before
    assert engine.materialise(v.id).materialised == 0   # violation rules never materialise


def test_disabled_rules_are_skipped(db):
    reg, store, v = built_domain(db)
    rs = RuleSet([Rule.from_text(HIGH, onto(), "high", enabled=False)])
    reg.update_content(v.id, actor="alice", ontology_ttl=onto().to_turtle(), rules=rs.to_dict())
    assert RuleEngine(reg, store).materialise(v.id).materialised == 0


def test_ruleset_round_trips_through_dict_and_text():
    rs = RuleSet([Rule.from_text(HIGH, onto(), "high"), Rule.from_text(LOW, onto(), "low", mode="violation", enabled=False)])
    again = RuleSet.from_dict(rs.to_dict())
    assert again == rs and again.rules[1].mode == "violation" and again.rules[1].enabled is False
    assert again.rules[0].to_text(onto()) == HIGH


def test_rules_api(db):
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": onto().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        r = c.put(f"/versions/{v['id']}/rules", json={"rules": [
            {"name": "high", "text": HIGH}, {"name": "underpaid", "text": LOW, "mode": "violation"}]})
        assert r.status_code == 200, r.text
        assert [x["name"] for x in c.get(f"/versions/{v['id']}/rules").json()["rules"]] == ["high", "underpaid"]
        bad = c.put(f"/versions/{v['id']}/rules", json={"rules": [{"name": "x", "text": "Ghost(?e) -> Employee(?e)"}]})
        assert bad.status_code == 400 and "Ghost" in bad.json()["detail"]
        assert "FROM triples" in c.get(f"/versions/{v['id']}/rules/sql").text
        c.post(f"/versions/{v['id']}/builds", params={"wait": "true"})
        run = c.post(f"/versions/{v['id']}/reasoning/rules").json()
        assert run["materialised"] == 1 and run["violations"][0]["rule"] == "underpaid"
        assert c.get(f"/versions/{v['id']}/graph/status").json()["inferred"] == 1
