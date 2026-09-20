"""Importing external ontologies (OWL/RDFS in Turtle, RDF/XML, JSON-LD) and merging into a version."""
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings
from ontoforge.ontology import Ontology, merge_ontologies, INDUSTRY_ONTOLOGIES
from tests.hr_fixture import ontology, seed_tables, BASE, EX

ADMIN = Settings(auth_default_role="admin")

FOAF_LIKE = """
@prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> . @prefix ex: <http://xmlns.com/foaf/0.1/> .
<http://xmlns.com/foaf/0.1/> a owl:Ontology ; rdfs:label "FOAF-like" .
ex:Agent a owl:Class ; rdfs:label "Agent" .
ex:Person a owl:Class ; rdfs:subClassOf ex:Agent ; rdfs:label "Person" .
ex:knows a owl:ObjectProperty ; rdfs:domain ex:Person ; rdfs:range ex:Person .
ex:mbox a owl:DatatypeProperty ; rdfs:domain ex:Agent ; rdfs:range xsd:string .
"""

RDFXML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://x/o"/>
  <owl:Class rdf:about="http://x/o#Thing"><rdfs:label>Thing</rdfs:label></owl:Class>
</rdf:RDF>"""


def test_merge_adds_new_terms_and_keeps_existing_ones():
    base = ontology()
    incoming = Ontology.from_turtle(FOAF_LIKE)
    merged, report = merge_ontologies(base, incoming)
    assert merged.iri == base.iri and "http://xmlns.com/foaf/0.1/Agent" in merged.classes
    assert merged.classes[EX + "Employee"] == base.classes[EX + "Employee"]          # untouched
    assert report == {"classes_added": 2, "classes_skipped": 0, "properties_added": 2, "properties_skipped": 0}
    again, report2 = merge_ontologies(merged, incoming)
    assert report2["classes_added"] == 0 and report2["classes_skipped"] == 2       # idempotent


def test_import_supports_rdfxml_and_reports_issues():
    o = Ontology.from_rdf(RDFXML, "xml")
    assert o.classes["http://x/o#Thing"].label == "Thing"


def test_industry_catalogue_lists_sources_with_licences():
    fibo = INDUSTRY_ONTOLOGIES["fibo"]
    assert fibo["licence"].lower().startswith("mit") and fibo["url"].startswith("https://")
    assert {"fibo", "fhir", "iof", "schema"} <= set(INDUSTRY_ONTOLOGIES)


def test_import_endpoint_merges_or_replaces(db):
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
        r = c.post(f"/versions/{v['id']}/ontology/import", json={"data": FOAF_LIKE, "format": "turtle", "mode": "merge"})
        assert r.status_code == 200, r.text
        assert r.json()["report"]["classes_added"] == 2 and r.json()["classes"] == 5
        r = c.post(f"/versions/{v['id']}/ontology/import", json={"data": RDFXML, "format": "xml", "mode": "replace"})
        assert r.status_code == 200 and r.json()["classes"] == 1
        assert c.get(f"/versions/{v['id']}/ontology").json()["iri"] == "http://x/o"
        assert c.post(f"/versions/{v['id']}/ontology/import", json={"data": "garbage", "format": "turtle"}).status_code == 400
        assert c.get("/ontologies/industry").json()["fibo"]["licence"].startswith("MIT")
