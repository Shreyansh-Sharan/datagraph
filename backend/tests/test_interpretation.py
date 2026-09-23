"""AI interpretation of analytics runs, and global quality rules (labels, orphans)."""
from fastapi.testclient import TestClient

from ontoforge.analytics import GraphAnalytics, interpret_run
from ontoforge.api import create_app
from ontoforge.config import Settings
from tests.fakes import FakeProvider
from ontoforge.quality import Constraint, ConstraintSet, QualityEngine
from tests.hr_fixture import built_domain, BASE, EX

ADMIN = Settings(auth_default_role="admin")
INSIGHT = {"key_findings": "SMITH is the hub of the graph. Two components exist.",
           "notable_entities": [{"iri": BASE + "Employee/1", "reason": "highest PageRank and betweenness"}],
           "recommendations": ["Connect GHOST's department", "Review reporting lines"]}


def test_interpret_run_feeds_metrics_to_the_model_and_returns_insights(db):
    reg, store, v = built_domain(db)
    ga = GraphAnalytics(reg, store)
    run = ga.centralities(v.id, top_n=5)
    provider = FakeProvider([INSIGHT])
    insight = interpret_run(reg, store, run.run_id, provider)
    assert insight["key_findings"].startswith("SMITH") and insight["notable_entities"][0]["label"] == "SMITH"
    assert insight["recommendations"] == INSIGHT["recommendations"] and insight["run_id"] == str(run.run_id)
    system, user, schema = provider.calls[0]
    assert "pagerank" in user.lower() and BASE + "Employee/1" in user and "components" in user.lower()
    assert "key_findings" in schema["properties"]


def test_interpretation_endpoint_can_post_a_comment(db):
    reg, store, v = built_domain(db)
    run = GraphAnalytics(reg, store).centralities(v.id)
    with TestClient(create_app(db=db, settings=ADMIN, llm=FakeProvider([INSIGHT, INSIGHT])), headers={"X-Actor": "alice"}) as c:
        r = c.post(f"/analytics/runs/{run.run_id}/interpret")
        assert r.status_code == 200 and r.json()["notable_entities"][0]["iri"] == BASE + "Employee/1"
        r = c.post(f"/analytics/runs/{run.run_id}/interpret", params={"comment": "true"})
        assert r.status_code == 200
        comments = c.get(f"/versions/{v.id}/comments").json()
        assert len(comments) == 1 and "SMITH is the hub" in comments[0]["body"] and comments[0]["author"] == "alice"
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        assert c.post(f"/analytics/runs/{run.run_id}/interpret").status_code == 503


def test_global_quality_rules_labels_and_orphans(db):
    reg, store, v = built_domain(db)
    store.add_inferred(v.id, [(BASE + "Department/99", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", EX + "Department", "iri", None, None)])
    cs = ConstraintSet([Constraint("dept-labelled", EX + "Department", None, "require_label", None),
                        Constraint("emp-connected", EX + "Employee", None, "no_orphans", None, severity="warning")])
    reg.update_content(v.id, actor="alice", quality=cs.to_dict())
    by = {r.name: r for r in QualityEngine(reg, store).run(v.id, include_ontology=False).results}
    assert by["dept-labelled"].violations == 1 and by["dept-labelled"].samples[0]["focus"] == BASE + "Department/99"
    assert by["emp-connected"].violations == 0 and by["emp-connected"].targets == 4
    store.add_inferred(v.id, [(BASE + "Employee/9", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", EX + "Employee", "iri", None, None)])
    by = {r.name: r for r in QualityEngine(reg, store).run(v.id, include_ontology=False).results}
    assert by["emp-connected"].violations == 1 and by["emp-connected"].samples[0]["focus"] == BASE + "Employee/9"
    assert "sh:" in cs.to_shacl() and ConstraintSet.from_shacl(cs.to_shacl()) == cs


def test_an_entity_the_graph_does_not_hold_is_not_given_a_label(db):
    """A model can name an IRI that exists nowhere; minting a label for it makes it look real."""
    from ontoforge.analytics import interpret_run
    from ontoforge.registry import Registry
    from ontoforge.store import TripleStore
    from tests.fakes import FakeProvider
    from tests.hr_fixture import BASE, built_domain

    reg, store, v = built_domain(db)
    run = reg.start_analytics(v.id, scope="graph", actor="a")
    reg.finish_analytics(run.id, status="succeeded", nodes=3, edges=2, components=1, avg_degree=1.3, density=0.2,
                         duration=0.1, results={"top": []})
    provider = FakeProvider([{
        "key_findings": "The graph is small.",
        "notable_entities": [{"iri": BASE + "Employee/1", "reason": "central"},
                             {"iri": BASE + "Employee/9999", "reason": "invented by the model"}],
        "recommendations": ["look again"],
    }])
    out = interpret_run(Registry(db), TripleStore(db), run.id, provider)
    assert [e["iri"] for e in out["notable_entities"]] == [BASE + "Employee/1"]
    assert out["skipped_entities"] == [BASE + "Employee/9999"]
