"""Bridges: the same real-world thing across two domains, joined on key values."""
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.attachments import Attachments, AttachmentService, Bridge
from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.config import Settings
from ontoforge.mapping import AttributeBinding, ClassMapping, MappingSpec
from ontoforge.mcp import GraphTools
from ontoforge.ontology import DatatypeProperty, OntoClass, Ontology, XSD
from ontoforge.store import TripleStore
from tests.hr_fixture import built_domain, BASE, EX

ADMIN = Settings(auth_default_role="admin")
PAY = "http://d/pay#"
PAY_BASE = "http://d/pay/"


def payroll(reg, store, db):
    o = Ontology(iri="http://d/pay", label="Payroll")
    o.add_class(OntoClass(PAY + "Worker", "Worker"))
    o.add_datatype_property(DatatypeProperty(PAY + "salary", "salary", domain=PAY + "Worker", range=XSD + "decimal"))
    spec = MappingSpec(base_iri=PAY_BASE, classes=(ClassMapping(
        PAY + "Worker", sql_query="SELECT empno, sal FROM employees WHERE empno < 4", key_columns=("empno",),
        attributes=(AttributeBinding(PAY + "salary", "sal"),)),))
    d = reg.create_domain("payroll", base_iri=PAY_BASE)
    v = reg.create_version(d.id, actor="a")
    reg.update_content(v.id, actor="a", ontology_ttl=o.to_turtle(), mapping=spec.to_dict())
    assert BuildPipeline(reg, store, PostgresSource(db)).run(v.id).status == "succeeded"
    return v


def test_bridges_resolve_counterparts_by_key(db):
    reg, store, v = built_domain(db)
    payroll(reg, store, db)
    att = Attachments(bridges=(Bridge(EX + "Employee", "payroll", PAY + "Worker", description="Same person in payroll"),))
    reg.update_content(v.id, actor="alice", attachments=att.to_dict())
    svc = AttachmentService(reg, PostgresSource(db), store)
    (b,) = svc.bridges_for(v.id, BASE + "Employee/1")
    assert b == {"domain": "payroll", "class": PAY + "Worker", "iri": PAY_BASE + "Worker/1", "exists": True,
                 "label": "Worker/1", "description": "Same person in payroll"}
    (b4,) = svc.bridges_for(v.id, BASE + "Employee/4")
    assert b4["exists"] is False and b4["iri"] == PAY_BASE + "Worker/4"
    assert svc.bridges_for(v.id, BASE + "Department/10") == []
    assert Attachments.from_dict(att.to_dict()) == att


def test_bridge_to_unknown_domain_is_reported_not_fatal(db):
    reg, store, v = built_domain(db)
    att = Attachments(bridges=(Bridge(EX + "Employee", "nowhere", PAY + "Worker"),))
    reg.update_content(v.id, actor="alice", attachments=att.to_dict())
    (b,) = AttachmentService(reg, PostgresSource(db), store).bridges_for(v.id, BASE + "Employee/1")
    assert b["exists"] is False and "nowhere" in b["error"]


def test_mcp_context_and_api_include_bridges(db):
    reg, store, v = built_domain(db)
    payroll(reg, store, db)
    reg.update_content(v.id, actor="alice", attachments=Attachments(bridges=(Bridge(EX + "Employee", "payroll", PAY + "Worker"),)).to_dict())
    t = GraphTools(reg, store, attachments=AttachmentService(reg, PostgresSource(db), store))
    ctx = t.get_entity_context("hr", BASE + "Employee/1")
    assert ctx["bridges"][0]["iri"] == PAY_BASE + "Worker/1"
    text = t.describe_entity("hr", "SMITH")
    assert "payroll" in text and PAY_BASE + "Worker/1" in text
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        r = c.get(f"/versions/{v.id}/graph/entity/bridges", params={"iri": BASE + "Employee/1"})
        assert r.status_code == 200 and r.json()[0]["exists"] is True
        bad = {"bridges": [{"class_iri": EX + "Employee", "target_domain": "nowhere", "target_class": PAY + "Worker"}]}
        assert c.put(f"/versions/{v.id}/attachments", json=bad).status_code == 400
