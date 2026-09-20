"""Constraints implied by the ontology: ranges, functional properties, class restrictions."""
from __future__ import annotations

from ontoforge.ontology import DatatypeProperty, ObjectProperty, Ontology

from .model import Constraint, ConstraintSet


def constraints_from_ontology(o: Ontology) -> ConstraintSet:
    found: dict[tuple[str, str, str], Constraint] = {}

    def put(cls: str, prop: str, kind: str, value, severity: str = "violation") -> None:
        key = (cls, prop, kind)
        prev = found.get(key)
        if prev is not None:
            if kind == "min_count":
                value = max(prev.value, value)
            elif kind == "max_count":
                value = min(prev.value, value)
        name = f"ontology:{o.local_name(cls)}.{o.local_name(prop)}.{kind}"
        found[key] = Constraint(name, cls, prop, kind, value, severity)

    for c in o.classes.values():
        for p in o.properties_of(c.iri, include_global=False):
            if isinstance(p, DatatypeProperty):
                if p.range:
                    put(c.iri, p.iri, "datatype", p.range)
                if p.functional:
                    put(c.iri, p.iri, "max_count", 1)
            elif isinstance(p, ObjectProperty):
                if p.range:
                    put(c.iri, p.iri, "class", p.range)
                if p.functional:
                    put(c.iri, p.iri, "max_count", 1)
        for r in o.restrictions_of(c.iri):
            if r.kind == "min":
                put(c.iri, r.property, "min_count", int(r.value))
            elif r.kind == "max":
                put(c.iri, r.property, "max_count", int(r.value))
            elif r.kind == "exactly":
                put(c.iri, r.property, "min_count", int(r.value))
                put(c.iri, r.property, "max_count", int(r.value))
            elif r.kind == "some":
                put(c.iri, r.property, "min_count", 1)
            elif r.kind == "only":
                kind = "class" if isinstance(o.property(r.property), ObjectProperty) else "datatype"
                put(c.iri, r.property, kind, str(r.value))
            elif r.kind == "has_value":
                put(c.iri, r.property, "in", [str(r.value)])
    return ConstraintSet(sorted(found.values(), key=lambda c: c.name))
