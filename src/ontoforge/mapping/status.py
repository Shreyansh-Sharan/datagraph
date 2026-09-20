"""Mapping completeness: which classes, attributes and relationships of the ontology are mapped,
excluded, or still missing."""
from __future__ import annotations

from dataclasses import dataclass, field

from ontoforge.ontology import DatatypeProperty, ObjectProperty, Ontology

from .spec import MappingSpec


@dataclass
class ClassStatus:
    class_iri: str
    state: str                       # unmapped | partial | complete
    table: str | None
    mapped_attributes: list[str] = field(default_factory=list)
    unmapped_attributes: list[str] = field(default_factory=list)
    mapped_relations: list[str] = field(default_factory=list)
    unmapped_relations: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    completion: float = 0.0


@dataclass
class MappingStatus:
    classes: list[ClassStatus]
    summary: dict
    completion: float


def mapping_status(o: Ontology, spec: MappingSpec) -> MappingStatus:
    by_class = {c.class_iri: c for c in spec.classes}
    relations_by_source: dict[str, set[str]] = {}
    for r in spec.relations:
        relations_by_source.setdefault(r.source_class, set()).add(r.property_iri)
    out: list[ClassStatus] = []
    totals = {"classes": 0, "mapped_classes": 0, "complete_classes": 0, "attributes": 0, "mapped_attributes": 0,
              "excluded_attributes": 0, "relations": 0, "mapped_relations": 0, "excluded_relations": 0}
    for c in o.classes.values():
        totals["classes"] += 1
        cm = by_class.get(c.iri)
        attrs = sorted(p.iri for p in o.properties_of(c.iri) if isinstance(p, DatatypeProperty))
        rels = sorted(p.iri for p in o.properties_of(c.iri) if isinstance(p, ObjectProperty))
        excluded = set(cm.excluded) if cm else set()
        mapped_a = sorted({a.property_iri for a in cm.attributes} & set(attrs)) if cm else []
        mapped_r = sorted(relations_by_source.get(c.iri, set()) & set(rels)) if cm else []
        unmapped_a = [a for a in attrs if a not in mapped_a and a not in excluded]
        unmapped_r = [r for r in rels if r not in mapped_r and r not in excluded]
        total = len(attrs) + len(rels)
        done = len(mapped_a) + len(mapped_r) + len(excluded & (set(attrs) | set(rels)))
        completion = round(done / total, 4) if total else (1.0 if cm else 0.0)
        state = "unmapped" if cm is None else ("complete" if not unmapped_a and not unmapped_r else "partial")
        out.append(ClassStatus(c.iri, state, cm.table if cm else None, mapped_a, unmapped_a, mapped_r, unmapped_r,
                               sorted(excluded), completion))
        totals["attributes"] += len(attrs)
        totals["mapped_attributes"] += len(mapped_a)
        totals["excluded_attributes"] += len(excluded & set(attrs))
        totals["relations"] += len(rels)
        totals["mapped_relations"] += len(mapped_r)
        totals["excluded_relations"] += len(excluded & set(rels))
        totals["mapped_classes"] += cm is not None
        totals["complete_classes"] += state == "complete"
    denom = totals["classes"] + totals["attributes"] + totals["relations"]
    num = totals["mapped_classes"] + totals["mapped_attributes"] + totals["excluded_attributes"] + totals["mapped_relations"] + totals["excluded_relations"]
    return MappingStatus(out, totals, round(num / denom, 4) if denom else 0.0)
