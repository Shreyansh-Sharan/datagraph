"""Business terms and KPI metrics per domain, filtered by table and searched."""
from ontoforge.glossary import GlossaryService
from ontoforge.registry import Registry
from tests.hr_fixture import BASE


def test_terms_and_metrics_crud_filters_and_search(db):
    reg = Registry(db)
    d = reg.create_domain("hr", base_iri=BASE)
    g = GlossaryService(reg, db)
    t1 = g.add(d.id, actor="alice", kind="term", name="Employee", definition="A person employed by the company.", table="hr.employees", columns=["empno", "ename"], status="approved", owner="Finance BI", class_name="Employee")
    t2 = g.add(d.id, actor="alice", kind="term", name="Tenure", definition="Years since hire.", table="hr.employees", columns=["hired"], owner="Sales ops")
    m1 = g.add(d.id, actor="alice", kind="metric", name="Headcount", definition="Active employees", formula="count(*)", unit="people", frequency="Monthly", owner="Data governance", status="certified", table="hr.employees")
    g.add(d.id, actor="alice", kind="metric", name="Cost", definition="Cloud spend", formula="sum(cost)", unit="EUR", frequency="Monthly", table="hr.billing")
    assert t1.status == "approved" and t2.status == "draft" and t1.schema_name == "hr"
    assert [t.name for t in g.list(d.id, kind="term")] == ["Employee", "Tenure"]
    assert [t.name for t in g.list(d.id, table="hr.employees")] == ["Employee", "Tenure", "Headcount"]
    assert [t.name for t in g.list(d.id, q="hire")] == ["Tenure"]                 # definition and columns are searched
    assert [t.name for t in g.list(d.id, kind="metric", q="count")] == ["Headcount"]
    t2 = g.update(t2.id, actor="bob", status="approved", definition="Elapsed time since HireDate, in years.")
    assert t2.status == "approved" and t2.updated_by == "bob"
    g.delete(m1.id, actor="alice")
    assert [t.name for t in g.list(d.id, kind="metric")] == ["Cost"]
    try:
        g.add(d.id, actor="alice", kind="term", name="Employee", definition="dup")
        assert False, "duplicate names must be refused"
    except ValueError as e:
        assert "Employee" in str(e)


def test_ai_suggests_terms_and_metrics_from_a_table_as_drafts(db):
    from ontoforge.build import PostgresSource
    from tests.fakes import FakeProvider
    from ontoforge.metadata import MetadataService
    from tests.hr_fixture import seed_tables
    seed_tables(db)
    reg = Registry(db)
    d = reg.create_domain("hr", base_iri=BASE)
    v = reg.create_version(d.id, actor="alice")
    meta = MetadataService(reg, PostgresSource(db).catalog, db)
    meta.import_tables(v.id, ["employees"], actor="alice")
    g = GlossaryService(reg, db)
    g.add(d.id, actor="alice", kind="term", name="Employee", definition="already here", table="employees")
    llm = FakeProvider([{"terms": [
        {"name": "Employee", "definition": "dup", "columns": ["empno"], "class_name": "Employee"},
        {"name": "Manager", "definition": "The employee a person reports to.", "columns": ["manager"], "class_name": None},
        {"name": "Ghost", "definition": "bad column", "columns": ["nope"], "class_name": None}],
        "metrics": [{"name": "Headcount", "definition": "Employees on payroll", "formula": "count(*)", "unit": "people", "frequency": "Monthly", "columns": ["empno"]}]}])
    report = g.suggest(d.id, v.id, "employees", meta, llm, actor="alice")
    assert report["added"] == 2 and report["skipped"] == ["Employee (already in the glossary)", "Ghost (unknown column nope)"]
    entries = {e.name: e for e in g.list(d.id, table="employees")}
    assert entries["Manager"].status == "draft" and entries["Manager"].columns == ["manager"] and entries["Manager"].schema_name is None
    assert entries["Headcount"].kind == "metric" and entries["Headcount"].status == "pending" and entries["Headcount"].formula == "count(*)"
