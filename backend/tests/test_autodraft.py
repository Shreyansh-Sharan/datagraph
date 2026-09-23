"""Draft an ontology + mapping from catalog metadata alone (PK/FK heuristics, no LLM)."""
from ontoforge.autodraft import draft_from_catalog
from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.catalog import PostgresCatalog
from ontoforge.registry import Registry
from ontoforge.store import TripleStore
from tests.hr_fixture import seed_tables


def test_catalog_exposes_keys(db):
    seed_tables(db)
    cat = PostgresCatalog(db)
    assert cat.primary_key("employees") == ("empno",)
    fks = cat.foreign_keys("employees")
    assert (("deptno",), "departments", ("deptno",)) in fks and (("manager",), "employees", ("empno",)) in fks
    assert set(cat.list_tables()) == {"departments", "employees", "employee_skills", "collaborations"}


def test_draft_builds_classes_properties_and_relations(db):
    seed_tables(db)
    onto, spec = draft_from_catalog(PostgresCatalog(db), ontology_iri="http://d/hr", base_iri="http://d/hr/")
    names = {onto.local_name(c) for c in onto.classes}
    assert names == {"Department", "Employee", "EmployeeSkill"}          # collaborations is a pure link table
    emp = "http://d/hr#Employee"
    dprops = {onto.local_name(p.iri): p.range for p in onto.datatype_properties.values() if p.domain == emp}
    assert dprops["ename"].endswith("#string") and dprops["sal"].endswith("#decimal") and dprops["hired"].endswith("#date")
    assert "deptno" not in dprops and "manager" not in dprops                # FK columns become relations, not attributes
    oprops = {onto.local_name(p.iri): (p.domain, p.range) for p in onto.object_properties.values()}
    assert oprops["department"] == (emp, "http://d/hr#Department")
    assert oprops["manager"] == (emp, emp)
    assert oprops.get("collaboration") == (emp, emp)
    rel_props = {onto.local_name(r.property_iri) for r in spec.relations}
    assert {"department", "manager", "employee"} <= rel_props           # employee_skills -> employees FK too


def test_draft_is_buildable_end_to_end(db):
    seed_tables(db)
    onto, spec = draft_from_catalog(PostgresCatalog(db), ontology_iri="http://d/hr", base_iri="http://d/hr/")
    assert not [i for i in onto.check() if i.severity == "error"]
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri="http://d/hr/").id, actor="a")
    reg.update_content(v.id, actor="a", ontology_ttl=onto.to_turtle(), mapping=spec.to_dict())
    store = TripleStore(db)
    run = BuildPipeline(reg, store, PostgresSource(db)).run(v.id)
    assert run.status == "succeeded", run.error
    inv = dict(store.type_inventory(v.id))
    assert inv["http://d/hr#Employee"] == 4 and inv["http://d/hr#Department"] == 2 and inv["http://d/hr#EmployeeSkill"] == 3


def test_draft_refuses_tables_without_columns():
    import pytest
    from ontoforge.autodraft import AutodraftError
    from ontoforge.catalog import CatalogAdapter

    class Cat(CatalogAdapter):
        def list_tables(self, schema=None): return ["known", "ghost"]
        def column_types(self, table): return {"id": "int"} if table == "known" else {}

    with pytest.raises(AutodraftError, match="ghost"):
        draft_from_catalog(Cat(), ontology_iri="http://d/x", base_iri="http://d/x/")


def test_draft_names_tables_with_their_schema_when_one_is_given(db):
    """A snapshot is imported as schema.table; the draft must map the same names, or the two never meet."""
    seed_tables(db)
    sch = db.schema
    onto, spec = draft_from_catalog(PostgresCatalog(db), ontology_iri="http://d/hr", base_iri="http://d/hr/", schema=sch)
    assert {c.table for c in spec.classes} >= {f"{sch}.employees", f"{sch}.departments"}
    assert all(r.table is None or r.table.startswith(f"{sch}.") for r in spec.relations)
    assert len(spec.relations) >= 2 and {r.target_class for r in spec.relations} >= {"http://d/hr#Department"}   # the foreign keys still meet their classes
    onto2, spec2 = draft_from_catalog(PostgresCatalog(db, default_schema=sch), ontology_iri="http://d/hr", base_iri="http://d/hr/", tables=["employees"])
    assert [c.table for c in spec2.classes] == [f"{sch}.employees"]


def test_a_draft_from_the_snapshot_matches_the_draft_from_the_live_catalog(db):
    """The snapshot holds columns, keys and foreign keys; drafting from it needs no round trip to the source."""
    from ontoforge.catalog import SnapshotCatalog
    from ontoforge.metadata import MetadataService
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri="http://d/hr/").id, actor="alice")
    meta = MetadataService(reg, PostgresCatalog(db), db)
    meta.import_tables(v.id, ["employees", "departments", "employee_skills"], actor="alice")
    live = draft_from_catalog(PostgresCatalog(db), ontology_iri="http://d/hr", base_iri="http://d/hr/", tables=["employees", "departments", "employee_skills"])
    snap = draft_from_catalog(SnapshotCatalog(meta, v.id), ontology_iri="http://d/hr", base_iri="http://d/hr/", tables=["employees", "departments", "employee_skills"])
    assert snap[1].to_dict() == live[1].to_dict() and set(snap[0].classes) == set(live[0].classes)
    assert SnapshotCatalog(meta, v.id).column_types("employees")["sal"] == "numeric" and SnapshotCatalog(meta, v.id).list_tables() == ["departments", "employee_skills", "employees"]
