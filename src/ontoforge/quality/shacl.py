"""ConstraintSet <-> SHACL Turtle. One property shape per constraint, named with sh:name."""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, XSD

from .model import Constraint, ConstraintSet

SH = Namespace("http://www.w3.org/ns/shacl#")
OF = Namespace("http://ontoforge.dev/shacl#")
_KIND_PRED = {"min_count": SH.minCount, "max_count": SH.maxCount, "datatype": SH.datatype, "class": SH["class"],
              "pattern": SH.pattern, "in": SH["in"], "min_inclusive": SH.minInclusive, "max_inclusive": SH.maxInclusive,
              "min_exclusive": SH.minExclusive, "max_exclusive": SH.maxExclusive, "unique": OF.unique, "node_kind": SH.nodeKind}
_PRED_KIND = {v: k for k, v in _KIND_PRED.items()}
_SEVERITY = {"violation": SH.Violation, "warning": SH.Warning, "info": SH.Info}
_SEVERITY_BACK = {v: k for k, v in _SEVERITY.items()}
_NODE_KIND = {"iri": SH.IRI, "literal": SH.Literal, "bnode": SH.BlankNode}
_NODE_KIND_BACK = {v: k for k, v in _NODE_KIND.items()}


def to_shacl(cs: ConstraintSet) -> str:
    g = Graph()
    g.bind("sh", SH)
    g.bind("of", OF)
    shapes: dict[str, URIRef] = {}
    for c in cs.constraints:
        shape = shapes.get(c.target_class)
        if shape is None:
            shape = shapes[c.target_class] = URIRef(c.target_class + "QualityShape")
            g.add((shape, RDF.type, SH.NodeShape))
            g.add((shape, SH.targetClass, URIRef(c.target_class)))
        ps = BNode()
        g.add((shape, SH.property, ps))
        g.add((ps, SH.path, URIRef(c.property)))
        g.add((ps, SH.name, Literal(c.name)))
        g.add((ps, SH.severity, _SEVERITY[c.severity]))
        if c.message:
            g.add((ps, SH.message, Literal(c.message)))
        pred = _KIND_PRED[c.kind]
        if c.kind in ("datatype", "class"):
            g.add((ps, pred, URIRef(c.value)))
        elif c.kind == "in":
            head = BNode()
            Collection(g, head, [Literal(v) for v in c.value])
            g.add((ps, pred, head))
        elif c.kind == "node_kind":
            g.add((ps, pred, _NODE_KIND[c.value]))
        elif c.kind == "unique":
            g.add((ps, pred, Literal(True)))
        else:
            g.add((ps, pred, Literal(c.value)))
    return g.serialize(format="turtle")


def from_shacl(turtle: str) -> ConstraintSet:
    g = Graph().parse(data=turtle, format="turtle")
    out: list[Constraint] = []
    for shape in g.subjects(RDF.type, SH.NodeShape):
        target = g.value(shape, SH.targetClass)
        if target is None:
            continue
        for ps in g.objects(shape, SH.property):
            path = g.value(ps, SH.path)
            if not isinstance(path, URIRef):
                continue
            base = str(g.value(ps, SH.name) or "")
            severity = _SEVERITY_BACK.get(g.value(ps, SH.severity), "violation")
            message = g.value(ps, SH.message)
            found = [(pred, obj) for pred, obj in g.predicate_objects(ps) if pred in _PRED_KIND]
            for i, (pred, obj) in enumerate(found):
                kind = _PRED_KIND[pred]
                if kind in ("datatype", "class"):
                    value = str(obj)
                elif kind == "in":
                    value = [str(x) for x in Collection(g, obj)]
                elif kind == "node_kind":
                    value = _NODE_KIND_BACK.get(obj, "iri")
                elif kind == "unique":
                    value = True
                elif kind in ("min_count", "max_count"):
                    value = int(obj)
                elif kind in ("min_inclusive", "max_inclusive", "min_exclusive", "max_exclusive"):
                    value = obj.toPython() if isinstance(obj, Literal) else float(obj)
                else:
                    value = str(obj)
                name = base if base and len(found) == 1 else f"{base or str(target).rsplit('#', 1)[-1] + '.' + str(path).rsplit('#', 1)[-1]}.{kind}"
                out.append(Constraint(name, str(target), str(path), kind, value, severity, str(message) if message else None))
    return ConstraintSet(sorted(out, key=lambda c: c.name))
