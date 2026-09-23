"""Graph analytics over the triple store: communities, centralities, health, recorded runs."""
from fastapi.testclient import TestClient

from ontoforge.analytics import GraphAnalytics, COMMUNITY_PREDICATE
from ontoforge.api import create_app
from ontoforge.config import Settings
from tests.hr_fixture import built_domain, ontology, mapping, seed_tables, BASE, EX

ADMIN = Settings(auth_default_role="admin")


def test_graph_is_built_from_relationship_triples_only(db):
    reg, store, v = built_domain(db)
    g = GraphAnalytics(reg, store).graph(v.id)
    assert g.number_of_nodes() == 7 and g.number_of_edges() == 7
    assert g.has_edge(BASE + "Employee/1", BASE + "Department/10")
    assert g.edges[BASE + "Employee/1", BASE + "Department/10"]["predicate"] == EX + "worksIn"
    assert not any(n.startswith("http://d/hr#") for n in g.nodes)   # classes are not nodes


def test_communities_cover_every_node_and_are_deterministic(db):
    reg, store, v = built_domain(db)
    ga = GraphAnalytics(reg, store)
    for algorithm in ("louvain", "label_propagation", "greedy_modularity"):
        report = ga.communities(v.id, algorithm=algorithm, seed=7)
        assert report.algorithm == algorithm and report.count >= 2
        assert sum(c.size for c in report.communities) == 7
        assert all(c.members and c.label for c in report.communities)
    a, b = ga.communities(v.id, seed=7), ga.communities(v.id, seed=7)
    assert a.membership == b.membership


def test_communities_can_be_persisted_as_inferred_triples(db):
    reg, store, v = built_domain(db)
    report = GraphAnalytics(reg, store).communities(v.id, persist=True)
    assert store.count(v.id, inferred=True) == 7
    smith = store.describe(v.id, BASE + "Employee/1")
    (rel,) = [r for r in smith.outgoing if r.predicate == COMMUNITY_PREDICATE]
    assert rel.target == BASE + f"community/{report.membership[BASE + 'Employee/1']}" and rel.inferred


def test_centralities_kpis_histograms_and_ranking(db):
    reg, store, v = built_domain(db)
    report = GraphAnalytics(reg, store).centralities(v.id, top_n=3)
    k = report.kpis
    assert (k["nodes"], k["edges"], k["components"]) == (7, 7, 2)
    assert 0 < k["density"] < 1 and k["avg_degree"] == 2.0 and k["elapsed_seconds"] >= 0
    assert set(report.metrics) == {"pagerank", "degree", "betweenness", "closeness", "clustering"}
    for name, h in report.histograms.items():
        assert len(h["bins"]) == 20 and sum(h["bins"]) == 7 and "median" in h and "p90" in h
    assert report.top[0]["iri"] == BASE + "Employee/1" and len(report.top) == 3
    assert set(report.top[0]) >= {"iri", "label", "pagerank", "degree", "betweenness", "closeness", "clustering"}


def test_data_model_health_flags_flat_and_time_series_types(db):
    reg, store, v = built_domain(db)
    store.add_inferred(v.id, [(BASE + f"Event/{i}", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", EX + "Event", "iri", None, None)
                              for i in range(25)] + [(BASE + f"Event/{i}", EX + "happenedTo", BASE + "Employee/1", "iri", None, None)
                                                     for i in range(25)])
    health = {h.entity_type: h for h in GraphAnalytics(reg, store).health(v.id)}
    assert health[EX + "Department"].flag == "flat" and health[EX + "Department"].relationship_predicates == 0
    assert health[EX + "Event"].flag == "time-series" and health[EX + "Event"].instances == 25
    assert health[EX + "Employee"].flag is None


def test_analytics_runs_are_recorded_and_served(db):
    seed_tables(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        c.post("/domains", json={"name": "hr", "base_iri": BASE})
        v = c.post("/domains/hr/versions").json()
        c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()})
        c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict())
        c.post(f"/versions/{v['id']}/builds", params={"wait": "true"})
        r = c.post(f"/versions/{v['id']}/analytics/centralities", json={"top_n": 5})
        assert r.status_code == 200, r.text
        run_id = r.json()["run_id"]
        assert r.json()["kpis"]["nodes"] == 7 and len(r.json()["top"]) == 5
        r = c.post(f"/versions/{v['id']}/analytics/communities", json={"algorithm": "louvain", "resolution": 1.0, "persist": False})
        assert r.status_code == 200 and r.json()["count"] >= 2
        runs = c.get(f"/versions/{v['id']}/analytics/runs").json()
        assert [x["scope"] for x in runs] == ["communities", "centralities"] and all(x["status"] == "succeeded" for x in runs)
        assert c.get(f"/analytics/runs/{run_id}").json()["results"]["kpis"]["edges"] == 7
        assert c.get(f"/versions/{v['id']}/analytics/health").json()[0]["entity_type"].startswith(EX)
        assert c.post(f"/versions/{v['id']}/analytics/communities", json={"algorithm": "magic"}).status_code == 400
