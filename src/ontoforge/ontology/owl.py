"""Ontology <-> OWL 2 via rdflib."""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

from .model import DatatypeProperty, ObjectProperty, OntoClass, Ontology, Restriction

_CHARACTERISTIC_CLASS = {
    "functional": OWL.FunctionalProperty, "inverse_functional": OWL.InverseFunctionalProperty,
    "transitive": OWL.TransitiveProperty, "symmetric": OWL.SymmetricProperty, "asymmetric": OWL.AsymmetricProperty,
    "reflexive": OWL.ReflexiveProperty, "irreflexive": OWL.IrreflexiveProperty,
}
_CLASS_CHARACTERISTIC = {v: k for k, v in _CHARACTERISTIC_CLASS.items()}
_CARDINALITY = {"min": OWL.minCardinality, "max": OWL.maxCardinality, "exactly": OWL.cardinality}
_VALUE = {"some": OWL.someValuesFrom, "only": OWL.allValuesFrom, "has_value": OWL.hasValue}


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
        for e in c.equivalent_to:
            g.add((node, OWL.equivalentClass, URIRef(e)))
        for d in c.disjoint_with:
            g.add((node, OWL.disjointWith, URIRef(d)))
        for r in c.restrictions:
            g.add((node, RDFS.subClassOf, _restriction(g, r)))
    for p in o.object_properties.values():
        node = URIRef(p.iri)
        g.add((node, RDF.type, OWL.ObjectProperty))
        _annotate(g, node, p.label, p.description)
        _domain(g, node, p)
        _link(g, node, RDFS.range, p.range)
        _link(g, node, OWL.inverseOf, p.inverse_of)
        for ch in p.characteristics:
            if ch in _CHARACTERISTIC_CLASS:
                g.add((node, RDF.type, _CHARACTERISTIC_CLASS[ch]))
        for sp in p.sub_property_of:
            g.add((node, RDFS.subPropertyOf, URIRef(sp)))
        for chain in p.chain:
            head = BNode()
            Collection(g, head, [URIRef(x) for x in chain])
            g.add((node, OWL.propertyChainAxiom, head))
    for p in o.datatype_properties.values():
        node = URIRef(p.iri)
        g.add((node, RDF.type, OWL.DatatypeProperty))
        _annotate(g, node, p.label, p.description)
        _domain(g, node, p)
        _link(g, node, RDFS.range, p.range)
        if p.functional:
            g.add((node, RDF.type, OWL.FunctionalProperty))
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
        parents, restrictions = [], []
        for sup in g.objects(node, RDFS.subClassOf):
            if isinstance(sup, URIRef):
                parents.append(str(sup))
            elif (sup, RDF.type, OWL.Restriction) in g:
                r = _parse_restriction(g, sup)
                if r:
                    restrictions.append(r)
        o.add_class(OntoClass(str(node), _label(g, node), _text(g, node, RDFS.comment), tuple(sorted(parents)),
                              tuple(sorted(str(x) for x in g.objects(node, OWL.equivalentClass) if isinstance(x, URIRef))),
                              tuple(sorted(str(x) for x in g.objects(node, OWL.disjointWith) if isinstance(x, URIRef))),
                              tuple(restrictions)))
    for node in sorted(g.subjects(RDF.type, OWL.ObjectProperty), key=str):
        chars = tuple(ch for t in g.objects(node, RDF.type) if (ch := _CLASS_CHARACTERISTIC.get(t)))
        chains = tuple(tuple(str(x) for x in Collection(g, head)) for head in g.objects(node, OWL.propertyChainAxiom))
        dom, doms = _domains(g, node)
        o.add_object_property(ObjectProperty(str(node), _label(g, node), _text(g, node, RDFS.comment),
                                             dom, _iri(g, node, RDFS.range), _iri(g, node, OWL.inverseOf),
                                             tuple(sorted(chars, key=_char_order)),
                                             tuple(sorted(str(x) for x in g.objects(node, RDFS.subPropertyOf) if isinstance(x, URIRef))),
                                             chains, doms))
    for node in sorted(g.subjects(RDF.type, OWL.DatatypeProperty), key=str):
        dom, doms = _domains(g, node)
        o.add_datatype_property(DatatypeProperty(str(node), _label(g, node), _text(g, node, RDFS.comment),
                                                 dom, _iri(g, node, RDFS.range),
                                                 (node, RDF.type, OWL.FunctionalProperty) in g, doms))
    return o


def _domain(g: Graph, node: URIRef, p) -> None:
    if len(p.domains) > 1:                       # rdfs:domain [ a owl:Class ; owl:unionOf ( A B ) ]
        union = BNode()
        g.add((union, RDF.type, OWL.Class))
        head = BNode()
        Collection(g, head, [URIRef(d) for d in p.domains])
        g.add((union, OWL.unionOf, head))
        g.add((node, RDFS.domain, union))
    else:
        _link(g, node, RDFS.domain, p.domain)


def _domains(g: Graph, node) -> tuple[str | None, tuple[str, ...]]:
    """(primary domain, union members) from rdfs:domain, unwrapping owl:unionOf."""
    for d in g.objects(node, RDFS.domain):
        if isinstance(d, URIRef):
            return str(d), ()
        head = g.value(d, OWL.unionOf)
        if head is not None:
            members = tuple(sorted(str(x) for x in Collection(g, head) if isinstance(x, URIRef)))
            return (members[0] if members else None), members
    return None, ()


def _restriction(g: Graph, r: Restriction) -> BNode:
    node = BNode()
    g.add((node, RDF.type, OWL.Restriction))
    g.add((node, OWL.onProperty, URIRef(r.property)))
    if r.kind in _CARDINALITY:
        g.add((node, _CARDINALITY[r.kind], Literal(int(r.value), datatype=XSD.nonNegativeInteger)))
    elif r.kind == "has_value":
        v = str(r.value)
        g.add((node, OWL.hasValue, URIRef(v) if v.startswith(("http://", "https://", "urn:")) else Literal(v)))
    else:
        g.add((node, _VALUE[r.kind], URIRef(str(r.value))))
    return node


def _parse_restriction(g: Graph, node) -> Restriction | None:
    prop = g.value(node, OWL.onProperty)
    if prop is None:
        return None
    for kind, pred in _CARDINALITY.items():
        v = g.value(node, pred)
        if v is not None:
            return Restriction(str(prop), kind, int(v))
    for pred, kind in ((OWL.minQualifiedCardinality, "min"), (OWL.maxQualifiedCardinality, "max"), (OWL.qualifiedCardinality, "exactly")):
        v = g.value(node, pred)
        if v is not None:
            return Restriction(str(prop), kind, int(v))
    for kind, pred in _VALUE.items():
        v = g.value(node, pred)
        if v is not None:
            return Restriction(str(prop), kind, str(v))
    return None


def _char_order(name: str) -> int:
    from .model import CHARACTERISTICS
    return CHARACTERISTICS.index(name)


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
