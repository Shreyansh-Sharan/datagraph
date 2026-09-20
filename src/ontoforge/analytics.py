"""Graph analytics over a domain version: communities, centralities, data-model health.

Runs in-process on networkx. Betweenness and closeness are sampled above ``SAMPLE_ABOVE`` nodes
so large graphs stay tractable; the report says when a metric was estimated.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from uuid import UUID

import networkx as nx
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ontoforge.compiler import RDF_TYPE
from ontoforge.ontology import Ontology
from ontoforge.registry import NotFound, Registry
from ontoforge.store import TripleStore

COMMUNITY_PREDICATE = "http://ontoforge.dev/analytics#inCommunity"
ALGORITHMS = ("louvain", "label_propagation", "greedy_modularity")
METRICS = ("pagerank", "degree", "betweenness", "closeness", "clustering")


class AnalyticsError(ValueError):
    pass


@dataclass
class Community:
    id: int
    size: int
    label: str
    members: list[str]


@dataclass
class CommunityReport:
    algorithm: str
    resolution: float
    count: int
    communities: list[Community]
    membership: dict[str, int]
    persisted: int = 0
    run_id: UUID | None = None


@dataclass
class CentralityReport:
    kpis: dict
    metrics: dict[str, dict[str, float]]
    histograms: dict[str, dict]
    top: list[dict]
    estimated: list[str] = field(default_factory=list)
    run_id: UUID | None = None


@dataclass
class HealthRow:
    entity_type: str
    instances: int
    relationship_predicates: int
    flag: str | None
    recommendation: str | None


class GraphAnalytics:
    SAMPLE_ABOVE = 5_000
    SAMPLE_K = 64

    def __init__(self, registry: Registry, store: TripleStore) -> None:
        self.registry, self.store = registry, store

    # -- graph ---------------------------------------------------------------

    def graph(self, version_id: UUID, include_inferred: bool = False) -> nx.DiGraph:
        g = nx.DiGraph()
        with self.store.db.transaction() as cur:
            rows = cur.execute(
                "SELECT subject, predicate, object FROM triples WHERE domain_version_id = %s AND predicate <> %s "
                "AND object_type <> 'literal' AND predicate <> %s AND (%s OR NOT inferred)",
                (version_id, RDF_TYPE, COMMUNITY_PREDICATE, include_inferred)).fetchall()
        for s, p, o in rows:
            g.add_edge(s, o, predicate=p)
        return g

    # -- communities ---------------------------------------------------------

    def communities(self, version_id: UUID, algorithm: str = "louvain", resolution: float = 1.0, seed: int = 42,
                    persist: bool = False, actor: str | None = None) -> CommunityReport:
        if algorithm not in ALGORITHMS:
            raise AnalyticsError(f"Unknown algorithm {algorithm!r}; choose from {ALGORITHMS}")
        run = self.registry.start_analytics(version_id, "communities", actor=actor)
        t0 = time.perf_counter()
        try:
            g = self.graph(version_id).to_undirected()
            if algorithm == "louvain":
                groups = nx.community.louvain_communities(g, resolution=resolution, seed=seed)
            elif algorithm == "label_propagation":
                groups = list(nx.community.label_propagation_communities(g))
            else:
                groups = list(nx.community.greedy_modularity_communities(g, resolution=resolution))
            groups = sorted((sorted(c) for c in groups), key=lambda c: (-len(c), c[0]))
            membership = {n: i for i, c in enumerate(groups) for n in c}
            labels = self._labels(version_id, [c[0] for c in groups] + [max(c, key=lambda n: g.degree(n)) for c in groups])
            communities = [Community(i, len(c), labels.get(max(c, key=lambda n: g.degree(n)), Ontology.local_name(c[0])), c[:50])
                           for i, c in enumerate(groups)]
            report = CommunityReport(algorithm, resolution, len(groups), communities, membership, run_id=run.id)
            if persist:
                base = self._base_iri(version_id)
                with self.store.db.transaction() as cur:
                    cur.execute("DELETE FROM triples WHERE domain_version_id = %s AND predicate = %s", (version_id, COMMUNITY_PREDICATE))
                report.persisted = self.store.add_inferred(
                    version_id, ((n, COMMUNITY_PREDICATE, f"{base}community/{i}", "iri", None, None) for n, i in membership.items()))
            self.registry.finish_analytics(run.id, status="succeeded", nodes=g.number_of_nodes(), edges=g.number_of_edges(),
                                           components=nx.number_connected_components(g) if g.number_of_nodes() else 0,
                                           duration=time.perf_counter() - t0,
                                           results={"algorithm": algorithm, "resolution": resolution, "count": len(groups),
                                                    "sizes": [len(c) for c in groups], "persisted": report.persisted})
            return report
        except Exception as exc:
            self.registry.finish_analytics(run.id, status="failed", error=str(exc), duration=time.perf_counter() - t0)
            raise

    # -- centralities --------------------------------------------------------

    def centralities(self, version_id: UUID, top_n: int = 20, actor: str | None = None) -> CentralityReport:
        run = self.registry.start_analytics(version_id, "centralities", actor=actor)
        t0 = time.perf_counter()
        try:
            g = self.graph(version_id)
            ug = g.to_undirected()
            n, m = g.number_of_nodes(), g.number_of_edges()
            estimated: list[str] = []
            k = self.SAMPLE_K if n > self.SAMPLE_ABOVE else None
            if k:
                estimated += ["betweenness", "closeness"]
            metrics = {
                "pagerank": nx.pagerank(g) if n else {},
                "degree": dict(nx.degree_centrality(ug)) if n else {},
                "betweenness": nx.betweenness_centrality(ug, k=k, seed=42) if n else {},
                "closeness": (nx.closeness_centrality(ug) if not k else self._sampled_closeness(ug, k)) if n else {},
                "clustering": nx.clustering(ug) if n else {},
            }
            kpis = {"nodes": n, "edges": m, "components": nx.number_connected_components(ug) if n else 0,
                    "avg_degree": round(2 * m / n, 4) if n else 0.0, "density": round(nx.density(ug), 6) if n > 1 else 0.0,
                    "elapsed_seconds": round(time.perf_counter() - t0, 4)}
            histograms = {name: _histogram(list(vals.values())) for name, vals in metrics.items()}
            ranked = sorted(g.nodes, key=lambda x: -metrics["pagerank"].get(x, 0.0))[:top_n]
            labels = self._labels(version_id, ranked)
            top = [{"iri": x, "label": labels.get(x, Ontology.local_name(x)), **{mname: round(metrics[mname].get(x, 0.0), 6) for mname in METRICS}}
                   for x in ranked]
            report = CentralityReport(kpis, metrics, histograms, top, estimated, run_id=run.id)
            self.registry.finish_analytics(run.id, status="succeeded", nodes=n, edges=m, components=kpis["components"],
                                           avg_degree=kpis["avg_degree"], density=kpis["density"], duration=kpis["elapsed_seconds"],
                                           results={"kpis": kpis, "histograms": histograms, "top": top, "estimated": estimated})
            return report
        except Exception as exc:
            self.registry.finish_analytics(run.id, status="failed", error=str(exc), duration=time.perf_counter() - t0)
            raise

    @staticmethod
    def _sampled_closeness(g: nx.Graph, k: int) -> dict[str, float]:
        import random
        rnd = random.Random(42)
        pivots = rnd.sample(list(g.nodes), min(k, g.number_of_nodes()))
        dist: dict[str, list[int]] = {n: [] for n in g.nodes}
        for p in pivots:
            for n, d in nx.single_source_shortest_path_length(g, p).items():
                dist[n].append(d)
        return {n: (len(ds) / sum(ds) if ds and sum(ds) else 0.0) for n, ds in dist.items()}

    # -- health --------------------------------------------------------------

    def health(self, version_id: UUID) -> list[HealthRow]:
        with self.store.db.transaction() as cur:
            rows = cur.execute("""
                WITH inst AS (SELECT object AS type, subject FROM triples WHERE domain_version_id = %s AND predicate = %s)
                SELECT inst.type, count(DISTINCT inst.subject) AS instances,
                       count(DISTINCT rel.predicate) AS rel_predicates
                FROM inst LEFT JOIN triples rel ON rel.domain_version_id = %s AND rel.subject = inst.subject
                     AND rel.predicate <> %s AND rel.object_type <> 'literal' AND rel.predicate <> %s
                GROUP BY inst.type ORDER BY 2 DESC, 1""", (version_id, RDF_TYPE, version_id, RDF_TYPE, COMMUNITY_PREDICATE)).fetchall()
        out = []
        for t, instances, rel_preds in rows:
            flag, rec = None, None
            if rel_preds == 0:
                flag, rec = "flat", "No outgoing relationships: consider excluding this type from the graph or adding relations"
            elif rel_preds == 1 and instances > 20:
                flag, rec = "time-series", "Many instances with a single relationship: looks like events/measurements; consider aggregating"
            out.append(HealthRow(t, instances, rel_preds, flag, rec))
        return out

    # -- helpers -------------------------------------------------------------

    def _labels(self, version_id: UUID, iris: list[str]) -> dict[str, str]:
        if not iris:
            return {}
        with self.store.db.transaction() as cur:
            return {e.iri: e.label for e in self.store._entities(cur, version_id, sorted(set(iris)))}

    def _base_iri(self, version_id: UUID) -> str:
        version = self.registry.get_version(version_id)
        return self.registry.get_domain_by_id(version.domain_id).base_iri


def _histogram(values: list[float], bins: int = 20) -> dict:
    if not values:
        return {"bins": [0] * bins, "min": 0.0, "max": 0.0, "median": 0.0, "p90": 0.0}
    lo, hi = min(values), max(values)
    width = (hi - lo) / bins if hi > lo else 1.0
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1) if hi > lo else 0
        counts[idx] += 1
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    return {"bins": counts, "min": lo, "max": hi, "median": statistics.median(values), "p90": p90}


def interpret_run(registry: Registry, store: TripleStore, run_id: UUID, provider) -> dict:
    """Ask the LLM provider to explain an analytics run; entities are labelled from the store."""
    import json
    from ontoforge.llm import prompts
    from ontoforge.llm.schemas import INSIGHT_SCHEMA

    run = registry.get_analytics(run_id)
    if run.status != "succeeded" or not run.results:
        raise AnalyticsError("Only successful analytics runs can be interpreted")
    ga = GraphAnalytics(registry, store)
    health = [asdict(h) for h in ga.health(run.domain_version_id)]
    payload = {"scope": run.scope, "kpis": run.results.get("kpis") or {"nodes": run.nodes, "edges": run.edges, "components": run.components},
               "top_entities": run.results.get("top", []), "communities": run.results.get("sizes"),
               "estimated_metrics": run.results.get("estimated", []), "data_model_health": health}
    data = provider.complete_json(prompts.INTERPRET_ANALYTICS, json.dumps(payload, indent=1, default=str), INSIGHT_SCHEMA)
    iris = [e["iri"] for e in data.get("notable_entities", [])]
    labels = ga._labels(run.domain_version_id, iris)
    return {"run_id": str(run_id), "key_findings": data["key_findings"],
            "notable_entities": [{"iri": e["iri"], "label": labels.get(e["iri"], Ontology.local_name(e["iri"])), "reason": e["reason"]}
                                 for e in data.get("notable_entities", [])],
            "recommendations": list(data.get("recommendations", []))}


def insight_markdown(insight: dict) -> str:
    lines = [f"**AI interpretation of analytics run {insight['run_id']}**", "", insight["key_findings"], ""]
    if insight["notable_entities"]:
        lines.append("Notable entities:")
        lines += [f"- {e['label']} (`{e['iri']}`): {e['reason']}" for e in insight["notable_entities"]]
        lines.append("")
    if insight["recommendations"]:
        lines.append("Recommendations:")
        lines += [f"- {r}" for r in insight["recommendations"]]
    return "\n".join(lines)
