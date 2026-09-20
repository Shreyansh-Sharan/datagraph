"""Mapping workflow: relationship direction, completeness status, exclusions, previews, unmap."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.compiler import compile_mapping
from ontoforge.config import Settings
from ontoforge.dialects import SQLiteDialect, register_functions
from ontoforge.mapping import AttributeBinding, ClassMapping, MappingSpec, RelationMapping, mapping_status
from tests.hr_fixture import ontology, mapping, seed_tables, BASE, EX

ADMIN = Settings(auth_default_role="admin")


def run_sqlite(spec: MappingSpec):
    conn = sqlite3.connect(":memory:")
    register_functions(conn)
    conn.execute("CREATE TABLE emp (empno, deptno)")
    conn.executemany("INSERT INTO emp VALUES (?,?)", [(1, 10), (2, 20)])
    conn.execute("CREATE TABLE dept (deptno)")
    conn.executemany("INSERT INTO dept VALUES (?)", [(10,), (20,)])
    return {(r[0], r[1], r[2]) for r in conn.execute(compile_mapping(spec.to_r2rml(), SQLiteDialect()).sql) if r[1] == EX + "worksIn"}


def spec(direction: str) -> MappingSpec:
    return MappingSpec(base_iri=BASE, classes=(
        ClassMapping(EX + "Employee", table="emp", key_columns=("empno",)),
        ClassMapping(EX + "Department", table="dept", key_columns=("deptno",))),
        relations=(RelationMapping(EX + "worksIn", EX + "Employee", EX + "Department", target_key=("deptno",), direction=direction),))


def test_relation_direction_forward_reverse_bidirectional():
    fwd = {(BASE + "Employee/1", EX + "worksIn", BASE + "Department/10"), (BASE + "Employee/2", EX + "worksIn", BASE + "Department/20")}
    rev = {(o, p, s) for s, p, o in fwd}
    assert run_sqlite(spec("forward")) == fwd
    assert run_sqlite(spec("reverse")) == rev
    assert run_sqlite(spec("bidirectional")) == fwd | rev
    with pytest.raises(ValueError, match="direction"):
        RelationMapping(EX + "x", EX + "A", EX + "B", target_key=("c",), direction="sideways")


def test_direction_and_exclusions_round_trip_through_dict():
    s = MappingSpec(base_iri=BASE, classes=(ClassMapping(EX + "Employee", table="emp", key_columns=("empno",),
                                                          excluded=(EX + "skill", EX + "manages")),),
                    relations=(RelationMapping(EX + "worksIn", EX + "Employee", EX + "Department", target_key=("d",), direction="reverse"),))
    again = MappingSpec.from_dict(s.to_dict())
    assert again == s and again.classes[0].excluded == (EX + "manages", EX + "skill") and again.relations[0].direction == "reverse"


def test_mapping_status_reports_completeness_per_class():
    status = mapping_status(ontology(), mapping())
    by = {c.class_iri: c for c in status.classes}
    emp = by[EX + "Employee"]
    assert emp.state == "partial" and emp.mapped_attributes == [EX + "hired", EX + "name", EX + "salary"]
    assert emp.unmapped_attributes == [EX + "skill"] and emp.unmapped_relations == [EX + "manages"]
    assert emp.mapped_relations == [EX + "collaboratesWith", EX + "reportsTo", EX + "worksIn"]
    assert emp.completion == 0.75
    assert by[EX + "Department"].state == "complete" and by[EX + "Person"].state == "unmapped"
    assert status.summary == {"classes": 3, "mapped_classes": 2, "complete_classes": 1, "attributes": 6,  # global `name` counts per class
                              "mapped_attributes": 4, "excluded_attributes": 0, "relations": 4, "mapped_relations": 3,
                              "excluded_relations": 0}
    assert 0 < status.completion < 1


def test_excluded_properties_count_as_done():
    m = mapping()
    m = MappingSpec(m.base_iri, tuple(
        ClassMapping(c.class_iri, c.table, c.sql_query, c.key_columns, c.iri_template, c.attributes, excluded=(EX + "skill", EX + "manages"))
        if c.class_iri == EX + "Employee" else c for c in m.classes), m.relations)
    status = mapping_status(ontology(), m)
    emp = next(c for c in status.classes if c.class_iri == EX + "Employee")
    assert emp.state == "complete" and emp.completion == 1.0 and emp.excluded == [EX + "manages", EX + "skill"]
    assert status.summary["excluded_attributes"] == 1 and status.summary["excluded_relations"] == 1


def test_mapping_workflow_endpoints(db):
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        st = c.get(f"/versions/{v['id']}/mapping/status").json()
        assert st["completion"] < 1 and next(x for x in st["classes"] if x["class_iri"] == EX + "Employee")["state"] == "partial"
        r = c.post(f"/versions/{v['id']}/mapping/exclude", json={"class_iri": EX + "Employee", "property_iri": EX + "skill", "excluded": True})
        assert r.status_code == 200 and EX + "skill" in r.json()["classes"][0]["excluded"]
        r = c.post(f"/versions/{v['id']}/mapping/exclude-unmapped")
        assert r.status_code == 200
        emp = next(x for x in c.get(f"/versions/{v['id']}/mapping/status").json()["classes"] if x["class_iri"] == EX + "Employee")
        assert emp["state"] == "complete"
        rows = c.get(f"/versions/{v['id']}/mapping/preview", params={"class_iri": EX + "Employee", "limit": 5}).json()
        assert 0 < len(rows["rows"]) <= 5 and rows["columns"][:3] == ["subject", "predicate", "object"]
        assert rows["rows"][0]["subject"].startswith(BASE + "Employee/")
        r = c.post(f"/versions/{v['id']}/mapping/test-sql", json={"sql": "SELECT empno, ename FROM employees ORDER BY empno", "limit": 2})
        assert r.status_code == 200 and r.json()["columns"] == ["empno", "ename"] and len(r.json()["rows"]) == 2
        assert c.post(f"/versions/{v['id']}/mapping/test-sql", json={"sql": "SELECT 1; DROP TABLE employees"}).status_code == 400
        assert c.delete(f"/versions/{v['id']}/mapping/classes", params={"class_iri": EX + "Department"}).status_code == 200
        st = c.get(f"/versions/{v['id']}/mapping/status").json()
        assert next(x for x in st["classes"] if x["class_iri"] == EX + "Department")["state"] == "unmapped"
        assert EX + "worksIn" in next(x for x in st["classes"] if x["class_iri"] == EX + "Employee")["unmapped_relations"]


def test_per_class_sql_and_table_preview_endpoints(db):
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        r = c.get(f"/versions/{v['id']}/mapping/sql", params={"dialect": "postgres", "class_iri": EX + "Department"})
        assert r.status_code == 200 and '"departments"' in r.text and '"employees"' not in r.text
        r = c.get(f"/versions/{v['id']}/mapping/table-preview", params={"table": "departments", "limit": 5})
        assert r.status_code == 200
        assert r.json()["columns"] == ["deptno", "dname"] and len(r.json()["rows"]) == 2
        assert r.json()["rows"][0]["deptno"] == "10"
        assert c.get(f"/versions/{v['id']}/mapping/table-preview", params={"table": "nope; drop table x"}).status_code == 400
