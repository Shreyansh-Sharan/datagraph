"""Datasets, class actions and virtual attributes attached to ontology classes; served on demand."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.attachments import Attachments, Dataset, Action, VirtualAttribute, AttachmentError, AttachmentService
from ontoforge.build import PostgresSource
from ontoforge.config import Settings
from ontoforge.mapping import MappingSpec
from ontoforge.mcp import GraphTools
from tests.hr_fixture import built_domain, mapping, BASE, EX

ADMIN = Settings(auth_default_role="admin")


def attachments() -> Attachments:
    return Attachments(
        datasets=(Dataset(EX + "Employee", "employee_skills", key_columns=("empno",), description="Skills per employee"),),
        actions=(Action(EX + "Employee", "skills", "SELECT skill FROM employee_skills WHERE empno = :empno ORDER BY skill",
                        description="List the employee's skills", kind="table"),
                 Action(EX + "Employee", "skill_count", "SELECT count(*) FROM employee_skills WHERE empno = :empno", kind="scalar")),
        virtual_attributes=(VirtualAttribute(EX + "Employee", "skillCount", "SELECT count(*) FROM employee_skills WHERE empno = :empno"),
                            VirtualAttribute(EX + "Employee", "deptName",
                                             "SELECT dname FROM departments d JOIN employees e ON e.deptno = d.deptno WHERE e.empno = :empno")),
    )


def test_key_values_are_recovered_from_entity_iris():
    spec = mapping()
    assert spec.key_values_from_iri(EX + "Employee", BASE + "Employee/42") == {"empno": "42"}
    assert spec.key_values_from_iri(EX + "Employee", BASE + "Department/42") is None
    composite = MappingSpec(BASE, classes=(__import__("ontoforge.mapping", fromlist=["ClassMapping"]).ClassMapping(
        EX + "Line", table="lines", key_columns=("order_id", "line_no")),))
    assert composite.key_values_from_iri(EX + "Line", BASE + "Line/A%2F1-7") == {"order_id": "A/1", "line_no": "7"}


def test_attachments_validate_sql_and_placeholders():
    with pytest.raises(AttachmentError, match=";"):
        Action(EX + "Employee", "x", "SELECT 1; DROP TABLE t")
    with pytest.raises(AttachmentError, match="SELECT"):
        Action(EX + "Employee", "x", "DELETE FROM t WHERE empno = :empno")
    with pytest.raises(AttachmentError, match="kind"):
        Action(EX + "Employee", "x", "SELECT 1", kind="magic")
    with pytest.raises(AttachmentError, match="unique"):
        Attachments(actions=(Action(EX + "E", "a", "SELECT 1"), Action(EX + "E", "a", "SELECT 2")))
    assert Attachments.from_dict(attachments().to_dict()) == attachments()


def test_virtual_attributes_and_actions_run_against_the_source(db):
    reg, store, v = built_domain(db)
    reg.update_content(v.id, actor="alice", attachments=attachments().to_dict())
    svc = AttachmentService(reg, PostgresSource(db))
    assert svc.compute_virtual(v.id, BASE + "Employee/1") == {"skillCount": "2", "deptName": "SALES"}
    assert svc.compute_virtual(v.id, BASE + "Employee/3") == {"skillCount": "0", "deptName": None}
    out = svc.invoke(v.id, BASE + "Employee/1", "skills")
    assert out["kind"] == "table" and out["columns"] == ["skill"] and [r["skill"] for r in out["rows"]] == ["python", "sql"]
    assert svc.invoke(v.id, BASE + "Employee/1", "skill_count") == {"kind": "scalar", "value": "2"}
    with pytest.raises(AttachmentError, match="no action"):
        svc.invoke(v.id, BASE + "Employee/1", "fire")
    with pytest.raises(AttachmentError, match="Department"):
        svc.invoke(v.id, BASE + "Department/10", "skills")   # action is declared on Employee only


def test_dataset_rows_for_an_entity(db):
    reg, store, v = built_domain(db)
    reg.update_content(v.id, actor="alice", attachments=attachments().to_dict())
    svc = AttachmentService(reg, PostgresSource(db))
    (ds,) = svc.dataset_rows(v.id, BASE + "Employee/1")
    assert ds["table"] == "employee_skills" and [r["skill"] for r in ds["rows"]] == ["python", "sql"]
    assert svc.for_class(v.id, EX + "Employee")["datasets"][0]["description"] == "Skills per employee"
    assert svc.for_class(v.id, EX + "Department") == {"datasets": [], "actions": [], "virtual_attributes": []}


def test_mcp_exposes_context_actions_and_virtual_attributes(db):
    reg, store, v = built_domain(db)
    reg.update_content(v.id, actor="alice", attachments=attachments().to_dict())
    t = GraphTools(reg, store, attachments=AttachmentService(reg, PostgresSource(db)))
    ctx = t.get_entity_context("hr", BASE + "Employee/1", compute_virtual_attributes=True)
    assert [a["name"] for a in ctx["actions"]] == ["skill_count", "skills"] and ctx["virtual_attributes"] == {"skillCount": "2", "deptName": "SALES"}
    assert ctx["datasets"][0]["table"] == "employee_skills" and len(ctx["datasets"][0]["rows"]) == 2
    assert t.compute_virtual_attributes("hr", BASE + "Employee/1")["deptName"] == "SALES"
    assert t.invoke_entity_action("hr", BASE + "Employee/1", "skills")["rows"][0]["skill"] == "python"
    assert "no action" in t.invoke_entity_action("hr", BASE + "Employee/1", "fire")["error"].lower()
    reg.set_mcp_policy(reg.get_domain("hr").id, {"disabled_tools": ["invoke_entity_action"]})
    assert "disabled" in t.invoke_entity_action("hr", BASE + "Employee/1", "skills")["error"].lower()


def test_attachment_endpoints(db):
    reg, store, v = built_domain(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        r = c.put(f"/versions/{v.id}/attachments", json=attachments().to_dict())
        assert r.status_code == 200, r.text
        assert len(c.get(f"/versions/{v.id}/attachments").json()["actions"]) == 2
        bad = attachments().to_dict()
        bad["actions"][0]["class_iri"] = EX + "Ghost"
        assert c.put(f"/versions/{v.id}/attachments", json=bad).status_code == 400
        r = c.get(f"/versions/{v.id}/graph/entity/virtual", params={"iri": BASE + "Employee/1"})
        assert r.status_code == 200 and r.json()["skillCount"] == "2"
        r = c.post(f"/versions/{v.id}/graph/entity/actions/skills", params={"iri": BASE + "Employee/1"})
        assert r.status_code == 200 and r.json()["rows"][1]["skill"] == "sql"
        assert c.post(f"/versions/{v.id}/graph/entity/actions/fire", params={"iri": BASE + "Employee/1"}).status_code == 404
        r = c.get(f"/versions/{v.id}/graph/entity/datasets", params={"iri": BASE + "Employee/1"})
        assert r.status_code == 200 and r.json()[0]["table"] == "employee_skills"
        entity = c.get(f"/versions/{v.id}/graph/entity", params={"iri": BASE + "Employee/1"}).json()
        assert entity["attachments"]["virtual_attributes"] == ["deptName", "skillCount"]
