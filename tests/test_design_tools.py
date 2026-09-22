"""The assistant can change the design, not only read it: classes, relationships with their keys,
attributes and class mappings on the working draft, under the caller's identity."""
from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.mapping import MappingSpec
from ontoforge.mcp import GraphTools
from ontoforge.mcp.tools import ACTOR
from ontoforge.ontology import Ontology
from ontoforge.metadata import MetadataService
from tests.hr_fixture import built_domain, EX, BASE


def _rebuild(reg, store, db, v):
    run = BuildPipeline(reg, store, PostgresSource(db)).run(v.id, actor="alice", full=True)
    assert run.status == "succeeded", run.error
    with db.transaction() as cur:
        return set(cur.execute("SELECT subject, predicate, object FROM triples WHERE domain_version_id = %s", (v.id,)).fetchall())


def test_add_relationship_with_the_foreign_key_on_the_target_table(db):
    reg, store, v = built_domain(db)
    tools = GraphTools(reg, store)
    ACTOR.set("alice")
    out = tools.add_relationship("hr", "employs", "Department", "Employee", fk_column="deptno", fk_on="to", label="employs")
    assert out["property"] == EX + "employs" and out["mapped"] is True and "start_build" in out["next"]
    o = Ontology.from_turtle(reg.get_version(v.id).ontology_ttl)
    assert o.object_properties[EX + "employs"].domain == EX + "Department" and o.object_properties[EX + "employs"].range == EX + "Employee"
    spec = MappingSpec.from_dict(reg.get_version(v.id).mapping)
    rel = next(r for r in spec.relations if r.property_iri == EX + "employs")
    assert rel.table == "employees" and rel.source_key == ("deptno",) and rel.target_key == ("empno",)
    assert (BASE + "Department/10", EX + "employs", BASE + "Employee/1") in _rebuild(reg, store, db, v)


def test_add_relationship_with_the_foreign_key_on_the_source_table_and_through_a_link_table(db):
    reg, store, v = built_domain(db)
    tools = GraphTools(reg, store)
    ACTOR.set("alice")
    tools.add_relationship("hr", "assignedTo", "Employee", "Department", fk_column="deptno")
    tools.add_relationship("hr", "pairsWith", "Employee", "Employee", link_table="collaborations", source_key=["a"], target_key=["b"])
    spec = MappingSpec.from_dict(reg.get_version(v.id).mapping)
    a = next(r for r in spec.relations if r.property_iri == EX + "assignedTo")
    assert a.table is None and a.target_key == ("deptno",)
    p = next(r for r in spec.relations if r.property_iri == EX + "pairsWith")
    assert p.table == "collaborations" and p.source_key == ("a",) and p.target_key == ("b",)
    got = _rebuild(reg, store, db, v)
    assert (BASE + "Employee/1", EX + "assignedTo", BASE + "Department/10") in got and (BASE + "Employee/2", EX + "pairsWith", BASE + "Employee/3") in got


def test_add_class_map_it_and_give_it_an_attribute(db):
    reg, store, v = built_domain(db)
    tools = GraphTools(reg, store)
    ACTOR.set("alice")
    c = tools.add_class("hr", "Team", description="A department seen as a team")
    assert c["class"] == EX + "Team" and c["mapped"] is False
    m = tools.map_class("hr", "Team", "departments", ["deptno"])
    assert m["table"] == "departments" and m["key_columns"] == ["deptno"]
    a = tools.add_attribute("hr", "Team", "teamName", column="dname", datatype="string")
    assert a["property"] == EX + "teamName" and a["column"] == "dname"
    got = _rebuild(reg, store, db, v)
    assert (BASE + "Team/10", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", EX + "Team") in got
    assert (BASE + "Team/10", EX + "teamName", "SALES") in got


def test_remove_relationship_and_errors_that_teach(db):
    reg, store, v = built_domain(db)
    meta = MetadataService(reg, PostgresSource(db).catalog, db)
    meta.import_tables(v.id, ["employees", "departments"], actor="alice")
    tools = GraphTools(reg, store, metadata=meta)
    ACTOR.set("alice")
    gone = tools.remove_relationship("hr", "works in")
    assert gone["removed"] == EX + "worksIn" and gone["unmapped"] is True
    assert EX + "worksIn" not in Ontology.from_turtle(reg.get_version(v.id).ontology_ttl).object_properties
    assert all(r.property_iri != EX + "worksIn" for r in MappingSpec.from_dict(reg.get_version(v.id).mapping).relations)
    assert "Employee" in tools.add_relationship("hr", "x", "Emp", "Department", fk_column="deptno")["error"]
    assert "not a column" in tools.add_relationship("hr", "y", "Employee", "Department", fk_column="nope")["error"]
    dup = tools.add_relationship("hr", "reports to", "Employee", "Employee", fk_column="manager")["error"]
    assert "already" in dup and "mapped" in dup and "manager" in dup                  # says how it is mapped, so nothing is guessed
    assert "not mapped" in tools.add_relationship("hr", "manages", "Employee", "Employee")["error"]
    assert "Unknown relationship" in tools.remove_relationship("hr", "nothing")["error"]
    assert "start_build" in tools.add_relationship("hr", "z", "Employee", "Department")["next"]   # ontology only: the mapping comes later


def test_design_edits_need_a_draft_the_caller_may_edit(db):
    reg, store, v = built_domain(db)
    tools = GraphTools(reg, store)
    ACTOR.set("alice")
    reg.acquire_lease(v.id, editor="bob", ttl=__import__("datetime").timedelta(hours=1), force=True)
    assert "bob" in tools.add_class("hr", "Blocked")["error"]
