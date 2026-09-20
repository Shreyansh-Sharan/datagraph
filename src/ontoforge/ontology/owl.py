"""Ontology <-> OWL 2 via rdflib."""
from __future__ import annotations

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .model import DatatypeProperty, ObjectProperty, OntoClass, Ontology


def to_turtle(o: Ontology) -> str:
    g = Graph()
    g.bind("owl", OWL)
    root = URIRef(o.iri)
    g.add((root, RDF.type, OWL.Ontology))
    _annotate(g, root, o.label, o.description)
    for c in o.classes.values():
        node = URIRef(c.iri)
        g.add((node, RDF.type, OWL.Class))
        _annotate(g, node, c.label, c.description)
        for p in c.parents:
            g.add((node, RDFS.subClassOf, URIRef(p)))
    for p in o.object_properties.values():
        node = URIRef(p.iri)
        g.add((node, RDF.type, OWL.ObjectProperty))
        _annotate(g, node, p.label, p.description)
        _link(g, node, RDFS.domain, p.domain)
        _link(g, node, RDFS.range, p.range)
        _link(g, node, OWL.inverseOf, p.inverse_of)
    for p in o.datatype_properties.values():
        node = URIRef(p.iri)
        g.add((node, RDF.type, OWL.DatatypeProperty))
        _annotate(g, node, p.label, p.description)
        _link(g, node, RDFS.domain, p.domain)
        _link(g, node, RDFS.range, p.range)
    return g.serialize(format="turtle")


def from_rdf(data: str, fmt: str = "turtle") -> Ontology:
    g = Graph()
    g.parse(data=data, format=fmt)
    root = next(g.subjects(RDF.type, OWL.Ontology), None)
    o = Ontology(iri=str(root) if root else "urn:ontoforge:imported",
                 label=_text(g, root, RDFS.label) if root else None,
                 description=_text(g, root, RDFS.comment) if root else None)
    for node in sorted(set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class)), key=str):
        if not isinstance(node, URIRef):
            continue  # anonymous class expressions are out of scope
        parents = tuple(sorted(str(p) for p in g.objects(node, RDFS.subClassOf) if isinstance(p, URIRef)))
        o.add_class(OntoClass(str(node), _label(g, node), _text(g, node, RDFS.comment), parents))
    for node in sorted(g.subjects(RDF.type, OWL.ObjectProperty), key=str):
        o.add_object_property(ObjectProperty(str(node), _label(g, node), _text(g, node, RDFS.comment),
                                             _iri(g, node, RDFS.domain), _iri(g, node, RDFS.range), _iri(g, node, OWL.inverseOf)))
    for node in sorted(g.subjects(RDF.type, OWL.DatatypeProperty), key=str):
        o.add_datatype_property(DatatypeProperty(str(node), _label(g, node), _text(g, node, RDFS.comment),
                                                 _iri(g, node, RDFS.domain), _iri(g, node, RDFS.range)))
    return o


def _annotate(g: Graph, node: URIRef, label: str | None, description: str | None) -> None:
    if label:
        g.add((node, RDFS.label, Literal(label)))
    if description:
        g.add((node, RDFS.comment, Literal(description)))


def _link(g: Graph, node: URIRef, prop: URIRef, target: str | None) -> None:
    if target:
        g.add((node, prop, URIRef(target)))


def _text(g: Graph, node, prop) -> str | None:
    v = next((x for x in g.objects(node, prop) if isinstance(x, Literal)), None)
    return str(v) if v is not None else None


def _iri(g: Graph, node, prop) -> str | None:
    v = next((x for x in g.objects(node, prop) if isinstance(x, URIRef)), None)
    return str(v) if v is not None else None


def _label(g: Graph, node: URIRef) -> str:
    return _text(g, node, RDFS.label) or Ontology.local_name(str(node))
