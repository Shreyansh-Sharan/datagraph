"""OWL 2 RL closure (owlrl) and SHACL validation (pyshacl) over a domain version's triples."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from uuid import UUID

import pyshacl
from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from ontoforge.ontology import Ontology
from ontoforge.registry import Registry
from ontoforge.store import TripleStore

from .rdf import rows_to_graph, triple_to_row
from .shapes import generate_shapes

SH = Namespace("http://www.w3.org/ns/shacl#")
_NOISE_TYPES = {OWL.Thing, RDFS.Resource, OWL.NamedIndividual, RDFS.Literal, OWL.Class, RDF.Property,
                OWL.ObjectProperty, OWL.DatatypeProperty, OWL.Ontology}
_NOISE_PREDICATES = {OWL.sameAs, OWL.differentFrom, RDFS.subClassOf, RDFS.subPropertyOf, OWL.equivalentClass,
                     OWL.equivalentProperty, RDFS.domain, RDFS.range, OWL.inverseOf}


@dataclass(frozen=True)
class InferenceReport:
    inferred: int
    seconds: float
    inconsistent: list[str] = field(default_factory=list)   # entities typed owl:Nothing (disjointness violations)


def infer_triples(tbox: Graph, data: Graph) -> list[tuple]:
    """OWL 2 RL closure of tbox+data; returns only new, interesting ABox triples.

    Disjoint-class violations are made explicit as ``x rdf:type owl:Nothing`` (the OWL RL cax-dw
    conclusion) so callers can report inconsistent entities instead of silently dropping them.
    """
    tbox_terms = set(tbox.subjects())
    asserted = set(data)
    work = Graph()
    for t in tbox:
        work.add(t)
    for t in data:
        work.add(t)
    DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False).expand(work)
    for c1, c2 in list(work.subject_objects(OWL.disjointWith)):
        for x in set(work.subjects(RDF.type, c1)) & set(work.subjects(RDF.type, c2)):
            work.add((x, RDF.type, OWL.Nothing))
    return [t for t in work if t not in asserted and t not in tbox and _keep(t, tbox_terms)]


def _keep(t, tbox_terms: set) -> bool:
    s, p, o = t
    if isinstance(s, (Literal, BNode)) or s in tbox_terms or p in _NOISE_PREDICATES:
        return False   # blank-node subjects are TBox structure or owlrl bookkeeping, never entities
    if Ontology.local_name(str(p)) == "error":   # owlrl's inconsistency notes; we report owl:Nothing instead
        return False
    if p == RDF.type and o in _NOISE_TYPES:
        return False
    if isinstance(o, Literal) and p in (RDFS.label, RDFS.comment):
        return False
    return True


@dataclass(frozen=True)
class ValidationResult:
    focus: str
    path: str | None
    value: str | None
    message: str
    severity: str
    source_shape: str | None


@dataclass
class ValidationReport:
    conforms: bool
    results: list[ValidationResult] = field(default_factory=list)
    text: str = ""


class Reasoner:
    def __init__(self, registry: Registry, store: TripleStore) -> None:
        self.registry, self.store = registry, store

    def owl_rl(self, version_id: UUID) -> InferenceReport:
        t0 = time.perf_counter()
        tbox = self._ontology_graph(version_id)
        data = rows_to_graph(self.store.iter_triples(version_id, inferred=False))
        new = infer_triples(tbox, data)
        self.store.clear_inferred(version_id)
        n = self.store.add_inferred(version_id, (triple_to_row(t) for t in new))
        inconsistent = sorted(str(s) for s, p, o in new if p == RDF.type and o == OWL.Nothing)
        return InferenceReport(inferred=n, seconds=round(time.perf_counter() - t0, 4), inconsistent=inconsistent)

    def validate(self, version_id: UUID, shapes_ttl: str | None = None) -> ValidationReport:
        version = self.registry.get_version(version_id)
        ont = self._ontology_graph(version_id)
        shapes = Graph()
        shapes.parse(data=shapes_ttl or generate_shapes(Ontology.from_turtle(version.ontology_ttl or "")), format="turtle")
        data = rows_to_graph(self.store.iter_triples(version_id, inferred=None))
        conforms, results_graph, text = pyshacl.validate(data, shacl_graph=shapes, ont_graph=ont, inference="none")
        report = ValidationReport(conforms=bool(conforms), text=text)
        for r in results_graph.subjects(RDF.type, SH.ValidationResult):
            report.results.append(ValidationResult(
                focus=str(results_graph.value(r, SH.focusNode)),
                path=_opt(results_graph.value(r, SH.resultPath)),
                value=_opt(results_graph.value(r, SH.value)),
                message=str(results_graph.value(r, SH.resultMessage) or ""),
                severity=Ontology.local_name(str(results_graph.value(r, SH.resultSeverity) or SH.Violation)),
                source_shape=_opt(results_graph.value(r, SH.sourceShape))))
        report.results.sort(key=lambda x: (x.focus, x.path or ""))
        return report

    def _ontology_graph(self, version_id: UUID) -> Graph:
        g = Graph()
        ttl = self.registry.get_version(version_id).ontology_ttl
        if ttl:
            g.parse(data=ttl, format="turtle")
        return g


def _opt(node) -> str | None:
    return None if node is None else str(node)
