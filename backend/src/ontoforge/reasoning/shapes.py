"""SHACL shapes derived from an ontology.

One NodeShape per class. For every property that applies to the class (own or inherited domain,
or global) a property shape carries datatype / class constraints; class restrictions and
functional characteristics add sh:minCount / sh:maxCount / sh:hasValue / sh:class on the same
property shape.
"""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from ontoforge.ontology import DatatypeProperty, ObjectProperty, Ontology

SH = Namespace("http://www.w3.org/ns/shacl#")


def generate_shapes(o: Ontology) -> str:
    g = Graph()
    g.bind("sh", SH)
    for c in o.classes.values():
        shape = URIRef(c.iri + "Shape")
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.targetClass, URIRef(c.iri)))
        constraints: dict[str, dict] = {}

        def entry(prop_iri: str) -> dict:
            return constraints.setdefault(prop_iri, {})

        for p in o.properties_of(c.iri, include_global=False):
            e = entry(p.iri)
            if isinstance(p, DatatypeProperty):
                if p.range:
                    e["datatype"] = p.range
                if p.functional:
                    e["max"] = min(e.get("max", 1), 1)
            elif isinstance(p, ObjectProperty):
                e["nodeKind"] = "IRI"
                if p.range:
                    e["class"] = p.range
                if p.functional:
                    e["max"] = min(e.get("max", 1), 1)
        for r in o.restrictions_of(c.iri):
            e = entry(r.property)
            if r.kind == "min":
                e["min"] = max(e.get("min", 0), int(r.value))
            elif r.kind == "max":
                e["max"] = min(e.get("max", int(r.value)), int(r.value))
            elif r.kind == "exactly":
                e["min"], e["max"] = int(r.value), int(r.value)
            elif r.kind == "only":
                (e.__setitem__("class", str(r.value)) if isinstance(o.property(r.property), ObjectProperty)
                 else e.__setitem__("datatype", str(r.value)))
            elif r.kind == "has_value":
                e["hasValue"] = str(r.value)
            elif r.kind == "some":
                e["min"] = max(e.get("min", 0), 1)
        for prop_iri, e in constraints.items():
            if not e:
                continue
            ps = BNode()
            g.add((shape, SH.property, ps))
            g.add((ps, SH.path, URIRef(prop_iri)))
            if "datatype" in e:
                g.add((ps, SH.datatype, URIRef(e["datatype"])))
            if "class" in e:
                g.add((ps, SH["class"], URIRef(e["class"])))
            if "nodeKind" in e:
                g.add((ps, SH.nodeKind, SH.IRI))
            if "min" in e:
                g.add((ps, SH.minCount, Literal(e["min"])))
            if "max" in e:
                g.add((ps, SH.maxCount, Literal(e["max"])))
            if "hasValue" in e:
                v = e["hasValue"]
                g.add((ps, SH.hasValue, URIRef(v) if v.startswith(("http://", "https://", "urn:")) else Literal(v)))
            prop = o.property(prop_iri)
            if prop is not None and prop.label:
                g.add((ps, SH.name, Literal(prop.label)))
    return g.serialize(format="turtle")
