"""High-level mapping spec (what the UI / LLM produce) -> R2RML -> SQL, run on SQLite."""
import sqlite3

import pytest

from ontoforge.compiler import compile_mapping, RDF_TYPE
from ontoforge.dialects import SQLiteDialect, register_functions, XSD
from ontoforge.mapping import MappingSpec, ClassMapping, AttributeBinding, RelationMapping, MappingSpecError
from ontoforge.r2rml import serialize_r2rml, parse_r2rml

EX = "http://d/hr#"
BASE = "http://d/hr/"


def spec() -> MappingSpec:
    return MappingSpec(
        base_iri=BASE,
        classes=(
            ClassMapping(class_iri=EX + "Employee", table="emp", key_columns=("empno",),
                         attributes=(AttributeBinding(EX + "name", "ename"),
                                     AttributeBinding(EX + "salary", "sal", datatype=XSD + "decimal"))),
            ClassMapping(class_iri=EX + "Department", table="dept", key_columns=("deptno",),
                         attributes=(AttributeBinding(EX + "name", "dname"),)),
        ),
        relations=(
            RelationMapping(property_iri=EX + "worksIn", source_class=EX + "Employee", target_class=EX + "Department",
                            target_key=("deptno",)),  # FK on the source table identifies the target
            RelationMapping(property_iri=EX + "collaboratesWith", source_class=EX + "Employee",
                            target_class=EX + "Employee", table="collab", source_key=("a",), target_key=("b",)),
        ),
    )


def run(s: MappingSpec):
    conn = sqlite3.connect(":memory:")
    register_functions(conn)
    conn.execute("CREATE TABLE emp (empno, ename, deptno, sal)")
    conn.executemany("INSERT INTO emp VALUES (?,?,?,?)", [(1, "SMITH", 10, 800), (2, "ALLEN", 20, None), (3, "WARD", None, 1250)])
    conn.execute("CREATE TABLE dept (deptno, dname)")
    conn.executemany("INSERT INTO dept VALUES (?,?)", [(10, "SALES"), (20, "RESEARCH")])
    conn.execute("CREATE TABLE collab (a, b)")
    conn.executemany("INSERT INTO collab VALUES (?,?)", [(1, 2), (2, 3)])
    return set(conn.execute(compile_mapping(s.to_r2rml(), SQLiteDialect()).sql).fetchall())


def test_subject_iris_follow_base_class_key_convention():
    got = run(spec())
    assert (BASE + "Employee/1", RDF_TYPE, EX + "Employee", "iri", None, None) in got
    assert (BASE + "Department/10", RDF_TYPE, EX + "Department", "iri", None, None) in got


def test_attributes_become_datatype_triples():
    got = run(spec())
    assert (BASE + "Employee/1", EX + "name", "SMITH", "literal", None, None) in got
    assert (BASE + "Employee/1", EX + "salary", "800", "literal", XSD + "decimal", None) in got
    assert not any(r[0] == BASE + "Employee/2" and r[1] == EX + "salary" for r in got)


def test_fk_relation_on_source_table_needs_no_join():
    got = run(spec())
    assert (BASE + "Employee/1", EX + "worksIn", BASE + "Department/10", "iri", None, None) in got
    assert not any(r[0] == BASE + "Employee/3" and r[1] == EX + "worksIn" for r in got)


def test_link_table_relation():
    got = run(spec())
    assert (BASE + "Employee/1", EX + "collaboratesWith", BASE + "Employee/2", "iri", None, None) in got
    assert (BASE + "Employee/2", EX + "collaboratesWith", BASE + "Employee/3", "iri", None, None) in got


def test_composite_keys_join_with_dash():
    s = MappingSpec(base_iri=BASE, classes=(
        ClassMapping(class_iri=EX + "Line", table="lines", key_columns=("order_id", "line_no")),))
    tm = s.to_r2rml().only()
    assert tm.subject.template == BASE + "Line/{order_id}-{line_no}"


def test_custom_iri_template_overrides_convention():
    s = MappingSpec(base_iri=BASE, classes=(
        ClassMapping(class_iri=EX + "Employee", table="emp", key_columns=("empno",), iri_template="http://corp/people/{empno}"),))
    assert s.to_r2rml().only().subject.template == "http://corp/people/{empno}"


def test_relation_referencing_unknown_class_is_rejected():
    s = MappingSpec(base_iri=BASE, classes=(ClassMapping(class_iri=EX + "Employee", table="emp", key_columns=("empno",)),),
                    relations=(RelationMapping(EX + "x", EX + "Employee", EX + "Ghost", target_key=("deptno",)),))
    with pytest.raises(MappingSpecError, match="Ghost"):
        s.to_r2rml()


def test_relation_key_arity_must_match_target_key():
    s = MappingSpec(base_iri=BASE, classes=(
        ClassMapping(class_iri=EX + "Employee", table="emp", key_columns=("empno",)),
        ClassMapping(class_iri=EX + "Line", table="lines", key_columns=("order_id", "line_no"))),
        relations=(RelationMapping(EX + "x", EX + "Employee", EX + "Line", target_key=("deptno",)),))
    with pytest.raises(MappingSpecError, match="key"):
        s.to_r2rml()


def test_spec_round_trips_through_json_dict():
    s = spec()
    assert MappingSpec.from_dict(s.to_dict()) == s


def test_r2rml_from_spec_round_trips_through_turtle():
    s = spec()
    r2rml = s.to_r2rml()
    assert parse_r2rml(serialize_r2rml(r2rml)).triples_maps.keys() == r2rml.triples_maps.keys()
