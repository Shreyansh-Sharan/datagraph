"""The rest of the backend as MCP tools: glossary, version lifecycle and reviews, domain settings and
policy, metadata snapshots, mapping exclusions, reasoning rules and constraints, each under the
caller's identity and role."""
from types import SimpleNamespace

from ontoforge.build import PostgresSource
from ontoforge.glossary import GlossaryService
from ontoforge.mapping import MappingSpec
from ontoforge.mcp import GraphTools
from ontoforge.mcp.tools import ACTOR, ROLE
from ontoforge.metadata import MetadataService
from tests.hr_fixture import built_domain, EX


def _tools(db, role="admin"):
    reg, store, v = built_domain(db)
    meta = MetadataService(reg, PostgresSource(db).catalog, db)
    tools = GraphTools(reg, store, metadata=meta, services=SimpleNamespace(glossary=GlossaryService(reg, db)))
    ACTOR.set("alice"); ROLE.set(role)
    return tools, reg, v


def test_glossary_terms_are_added_updated_and_deleted(db):
    tools, reg, v = _tools(db)
    tools.import_tables("hr", ["employees"])
    t = tools.add_term("hr", "metric", "Headcount", "Employees on payroll", table="employees", columns=["empno"], formula="count(*)", unit="people")
    assert t["kind"] == "metric" and t["status"] == "draft" and t["formula"] == "count(*)"
    assert tools.glossary("hr")[0]["name"] == "Headcount"
    u = tools.update_term(t["id"], status="approved", definition="Employees on payroll at month end")
    assert u["status"] == "approved" and "month end" in u["definition"]
    assert tools.delete_term(t["id"])["deleted"] == t["id"] and tools.glossary("hr") == []
    assert "not a column" in tools.add_term("hr", "term", "Ghost", "x", table="employees", columns=["nope"])["error"]


def test_versions_move_through_the_lifecycle_under_the_callers_role(db):
    tools, reg, v = _tools(db, role="builder")
    assert "draft already exists" in tools.create_version("hr")["error"]
    moved = tools.transition_version("hr", "in_review")
    assert moved["status"] == "in_review" and moved["version"] == 1
    assert "needs reviewer" in tools.review_version("hr", approved=True)["error"]          # a builder cannot approve
    ROLE.set("reviewer")
    assert tools.review_version("hr", approved=True, comment="Looks right")["approved"] is True
    published = tools.transition_version("hr", "published")
    assert published["status"] == "published"
    assert tools.set_active_version("hr", 1)["active_version"] == 1
    assert tools.comment_version("hr", "Served since today")["body"] == "Served since today"
    draft = tools.create_version("hr")
    assert draft["version"] == 2 and draft["status"] == "draft"
    assert tools.list_domain_versions("hr")[0]["version"] == 2
    assert "needs admin" in tools.transition_version("hr", "archived", version=1)["error"]
    ROLE.set("admin")
    assert tools.transition_version("hr", "archived", version=1)["status"] == "archived"
    assert tools.delete_version("hr", 2)["deleted"] == 2
    assert "Cannot move" in tools.transition_version("hr", "draft", version=1)["error"]


def test_domain_settings_policy_and_creation(db):
    tools, reg, v = _tools(db)
    assert tools.update_domain("hr", description="People and where they work", review_quorum=2)["review_quorum"] == 2
    assert "Unknown domain setting" in tools.update_domain("hr", materialization="marble")["error"] or "materialization" in tools.update_domain("hr", materialization="marble")["error"]
    pol = tools.set_mcp_policy("hr", disabled_tools=["preview_sql"])
    assert pol["disabled_tools"] == ["preview_sql"] and "disabled" in tools.preview_sql("hr", "SELECT 1")["error"]
    assert tools.set_mcp_policy("hr", disabled_tools=[])["disabled_tools"] == []
    d = tools.create_domain("finance", "http://d/finance/", description="Money")
    assert d["name"] == "finance" and tools.list_domain_versions("finance")[0]["version"] == 1
    ROLE.set("builder")
    assert "needs admin" in tools.delete_domain("finance")["error"]
    ROLE.set("admin")
    assert tools.delete_domain("finance")["deleted"] == "finance" and tools.select_domain("finance").get("error")


def test_metadata_snapshots_are_imported_commented_and_removed(db):
    tools, reg, v = _tools(db)
    out = tools.import_tables("hr", ["employees", "departments", "collaborations"])
    assert {t["table"] for t in out} == {"employees", "departments", "collaborations"} and out[0]["column_count"] > 0
    assert tools.set_table_comment("hr", "employees", "Everyone on payroll")["comment"] == "Everyone on payroll"
    assert tools.set_table_comment("hr", "employees", "Monthly pay", column="sal")["columns"]["sal"] == "Monthly pay"
    assert tools.refresh_metadata("hr")["changes"] == []
    assert "used by the mapping" in tools.remove_table("hr", "departments")["error"]            # a mapped table stays
    tools.unmap_class("hr", "Department")
    assert tools.remove_table("hr", "departments")["removed"] == "departments"
    assert sorted(t["table"] for t in tools.list_tables("hr")) == ["collaborations", "employees"]


def test_mapping_exclusions_and_unmapping_a_class(db):
    tools, reg, v = _tools(db)
    ex = tools.exclude_property("hr", "Employee", "skill")
    assert ex["excluded"] == [EX + "skill"]
    assert tools.exclude_property("hr", "Employee", "skill", excluded=False)["excluded"] == []
    gone = tools.unmap_class("hr", "Department")
    assert gone["unmapped"] == EX + "Department" and gone["relations_dropped"] == 1
    spec = MappingSpec.from_dict(reg.get_version(v.id).mapping)
    assert all(c.class_iri != EX + "Department" for c in spec.classes) and all(r.target_class != EX + "Department" for r in spec.relations)


def test_reasoning_rules_and_constraints_are_edited_by_name(db):
    tools, reg, v = _tools(db)
    r = tools.add_rule("hr", "managers", "Employee(?e) ^ reportsTo(?e, ?m) -> manages(?m, ?e)")
    assert r["name"] == "managers" and r["mode"] == "materialize" and [x["name"] for x in tools.list_rules("hr")] == ["managers"]
    assert "parse" in tools.add_rule("hr", "bad", "this is not a rule")["error"].lower() or "error" in tools.add_rule("hr", "bad", "this is not a rule")
    assert tools.remove_rule("hr", "managers")["removed"] == "managers" and tools.list_rules("hr") == []
    assert "Unknown rule" in tools.remove_rule("hr", "managers")["error"]
    c = tools.add_constraint("hr", "salary present", "Employee", "min_count", property="salary", value=1, severity="warning")
    assert c["target_class"] == EX + "Employee" and c["property"] == EX + "salary" and tools.list_constraints("hr")[0]["name"] == "salary present"
    assert "unknown kind" in tools.add_constraint("hr", "x", "Employee", "teleport", property="salary")["error"]
    assert tools.remove_constraint("hr", "salary present")["removed"] == "salary present" and tools.list_constraints("hr") == []
