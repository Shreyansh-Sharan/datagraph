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
