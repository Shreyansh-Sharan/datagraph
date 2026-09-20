"""SHACL shapes derived from an ontology: one NodeShape per class, one property shape per property."""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from ontoforge.ontology import DatatypeProperty, Ontology

SH = Namespace("http://www.w3.org/ns/shacl#")


def generate_shapes(o: Ontology) -> str:
    g = Graph()
    g.bind("sh", SH)
    for c in o.classes.values():
        shape = URIRef(c.iri + "Shape")
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.targetClass, URIRef(c.iri)))
        for p in o.all_properties():
            if p.domain != c.iri or not p.range:
                continue
            ps = BNode()
            g.add((shape, SH.property, ps))
            g.add((ps, SH.path, URIRef(p.iri)))
            if isinstance(p, DatatypeProperty):
                g.add((ps, SH.datatype, URIRef(p.range)))
            else:
                g.add((ps, SH.nodeKind, SH.IRI))
                g.add((ps, SH["class"], URIRef(p.range)))
            if p.label:
                g.add((ps, SH.name, Literal(p.label)))
    return g.serialize(format="turtle")
