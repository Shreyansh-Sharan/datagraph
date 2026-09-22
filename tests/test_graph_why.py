"""Answering 'why': aggregating over the graph along the ontology, and knowing how classes connect."""
from ontoforge.mcp import GraphTools
from ontoforge.store import TripleStore
from tests.hr_fixture import built_domain, EX, BASE


def test_aggregate_measures_a_class_by_relationship_by_year_and_through_a_path(db):
    reg, store, v = built_domain(db)
    by_dept = store.aggregate(v.id, EX + "Employee", measure=EX + "salary", group_by=EX + "worksIn")
    rows = {r["label"]: r for r in by_dept}
    assert rows["SALES"]["count"] == 1 and rows["SALES"]["sum"] == 800 and rows["RESEARCH"]["sum"] is None    # ALLEN's salary is null
    assert rows["SALES"]["group"] == BASE + "Department/10"
    by_year = store.aggregate(v.id, EX + "Employee", group_by=EX + "hired", group_kind="year")
    assert {r["group"]: r["count"] for r in by_year} == {"2020": 1, "2021": 1, "2022": 1, None: 1}
    only_sales = store.aggregate(v.id, EX + "Employee", measure=EX + "salary", filters=[{"path": [EX + "worksIn"], "value": BASE + "Department/10"}])
    assert len(only_sales) == 1 and only_sales[0]["count"] == 1 and only_sales[0]["sum"] == 800
    # inverse step: departments counted by the employees that work in them ("^" walks the relationship backwards)
    depts = store.aggregate(v.id, EX + "Department", group_by=None, filters=[{"path": ["^" + EX + "worksIn", EX + "name"], "value": "SMITH"}])
    assert depts[0]["count"] == 1
    total = store.aggregate(v.id, EX + "Employee", measure=EX + "salary")
    assert total[0]["count"] == 4 and total[0]["sum"] == 2550 and total[0]["min"] == 500 and total[0]["max"] == 1250


def test_class_schema_and_paths_between_classes(db):
    reg, store, v = built_domain(db)
    tools = GraphTools(reg, store)
    schema = tools.class_schema("hr", "Employee")
    assert schema["class"] == EX + "Employee" and {a["label"] for a in schema["attributes"]} >= {"salary", "hired"}
    assert {o["target"] for o in schema["outgoing"]} >= {EX + "Department", EX + "Employee"} and any(i["source"] == EX + "Employee" for i in schema["incoming"])
    paths = tools.ontology_paths("hr", "Department", "Employee")
    assert paths["paths"][0]["steps"] == [{"from": EX + "Department", "property": EX + "worksIn", "direction": "inverse", "to": EX + "Employee"}]
    assert tools.ontology_paths("hr", "Department", "Nope")["error"].startswith("Unknown class")
    agg = tools.graph_aggregate("hr", "Employee", measure="salary", group_by="works in")
    assert {r["label"]: r["sum"] for r in agg["rows"]}["SALES"] == 800 and agg["measure"] == EX + "salary"


def test_group_by_is_a_path_and_says_so_when_given_two_dimensions(db):
    reg, store, v = built_domain(db)
    tools = GraphTools(reg, store)
    out = tools.graph_aggregate("hr", "Employee", group_by=["hired", "works in"], group_kind="year")
    assert "one dimension" in out["error"] and "hired" in out["error"]
    ok = tools.graph_aggregate("hr", "Employee", group_by=["works in", "name"])          # a real path: department, then its name
    assert {r["group"] for r in ok["rows"]} == {"SALES", "RESEARCH", None}


def test_unknown_class_names_the_closest_classes(db):
    reg, store, v = built_domain(db)
    tools = GraphTools(reg, store)
    for err in (tools.class_schema("hr", "Emp")["error"], tools.ontology_paths("hr", "Emp", "Department")["error"], tools.graph_aggregate("hr", "Emp")["error"]):
        assert err.startswith("Unknown class 'Emp'") and "Employee" in err and "Department" not in err


def test_aggregate_rejects_a_step_that_is_not_in_the_ontology(db):
    reg, store, v = built_domain(db)
    tools = GraphTools(reg, store)
    out = tools.graph_aggregate("hr", "Employee", measure="salary", filters=[{"path": ["works in", "hasCulture"], "value": "French"}])
    assert "hasCulture" in out["error"] and "ontology_paths" in out["error"]
    out = tools.graph_aggregate("hr", "Employee", measure="salary", filters=[{"path": ["works in", "name"], "value": "SALES"}])
    assert out["rows"][0]["sum"] == 800
