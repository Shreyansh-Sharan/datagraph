"""Ontology model: OWL 2 classes and properties, kept deliberately small.

Everything here maps 1:1 onto OWL/RDFS vocabulary (owl:Class, rdfs:subClassOf, owl:ObjectProperty,
owl:DatatypeProperty, rdfs:domain, rdfs:range, owl:inverseOf, rdfs:label, rdfs:comment).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Iterator

XSD = "http://www.w3.org/2001/XMLSchema#"


@dataclass(frozen=True)
class OntoClass:
    iri: str
    label: str | None = None
    description: str | None = None
    parents: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObjectProperty:
    iri: str
    label: str | None = None
    description: str | None = None
    domain: str | None = None
    range: str | None = None
    inverse_of: str | None = None


@dataclass(frozen=True)
class DatatypeProperty:
    iri: str
    label: str | None = None
    description: str | None = None
    domain: str | None = None
    range: str | None = None  # an XSD datatype IRI


@dataclass(frozen=True)
class Issue:
    code: str
    subject: str
    message: str
    severity: str = "warning"


@dataclass
class Ontology:
    iri: str
    label: str | None = None
    description: str | None = None
    classes: dict[str, OntoClass] = field(default_factory=dict)
    object_properties: dict[str, ObjectProperty] = field(default_factory=dict)
    datatype_properties: dict[str, DatatypeProperty] = field(default_factory=dict)

    # -- building ------------------------------------------------------------

    def add_class(self, c: OntoClass) -> OntoClass:
        self.classes[c.iri] = c
        return c

    def add_object_property(self, p: ObjectProperty) -> ObjectProperty:
        self.object_properties[p.iri] = p
        return p

    def add_datatype_property(self, p: DatatypeProperty) -> DatatypeProperty:
        self.datatype_properties[p.iri] = p
        return p

    def new_class(self, label: str, description: str | None = None, parents: tuple[str, ...] = ()) -> OntoClass:
        return self.add_class(OntoClass(self.mint(label, capitalize=True), label, description, parents))

    def mint(self, label: str, capitalize: bool = False) -> str:
        words = re.findall(r"[A-Za-z0-9]+", label)
        if not words:
            raise ValueError(f"Cannot derive a name from {label!r}")
        name = "".join(w[:1].upper() + w[1:] for w in words)
        if not capitalize:
            name = name[:1].lower() + name[1:]
        return f"{self.iri}#{name}"

    @staticmethod
    def local_name(iri: str) -> str:
        return re.split(r"[#/]", iri.rstrip("/"))[-1]

    # -- navigation ----------------------------------------------------------

    def ancestors(self, class_iri: str) -> tuple[str, ...]:
        seen: list[str] = []
        stack = list(self.classes.get(class_iri, OntoClass(class_iri)).parents)
        while stack:
            p = stack.pop(0)
            if p in seen:
                continue
            seen.append(p)
            stack.extend(self.classes.get(p, OntoClass(p)).parents)
        return tuple(seen)

    def descendants(self, class_iri: str) -> tuple[str, ...]:
        return tuple(c.iri for c in self.classes.values() if class_iri in self.ancestors(c.iri))

    def properties_of(self, class_iri: str) -> list[ObjectProperty | DatatypeProperty]:
        scope = {class_iri, *self.ancestors(class_iri)}
        return [p for p in (*self.object_properties.values(), *self.datatype_properties.values()) if p.domain in scope]

    def all_properties(self) -> Iterator[ObjectProperty | DatatypeProperty]:
        yield from self.object_properties.values()
        yield from self.datatype_properties.values()

    # -- checks --------------------------------------------------------------

    def check(self) -> list[Issue]:
        issues: list[Issue] = []
        for c in self.classes.values():
            if not c.label:
                issues.append(Issue("missing-label", c.iri, "Class has no rdfs:label"))
            for p in c.parents:
                if p not in self.classes:
                    issues.append(Issue("unknown-parent", c.iri, f"Parent class {p} is not defined", "error"))
            if c.iri in self.ancestors(c.iri):
                issues.append(Issue("subclass-cycle", c.iri, "Class is its own ancestor", "error"))
        for p in self.all_properties():
            if not p.label:
                issues.append(Issue("missing-label", p.iri, "Property has no rdfs:label"))
            if p.domain is None:
                issues.append(Issue("missing-domain", p.iri, "Property has no rdfs:domain"))
            elif p.domain not in self.classes:
                issues.append(Issue("unknown-domain", p.iri, f"Domain {p.domain} is not a class of this ontology", "error"))
            if p.range is None:
                issues.append(Issue("missing-range", p.iri, "Property has no rdfs:range"))
            elif isinstance(p, ObjectProperty) and p.range not in self.classes:
                issues.append(Issue("unknown-range", p.iri, f"Range {p.range} is not a class of this ontology", "error"))
            elif isinstance(p, DatatypeProperty) and not p.range.startswith(XSD):
                issues.append(Issue("non-xsd-range", p.iri, f"Datatype property range {p.range} is not an XSD type"))
        return issues

    # -- (de)serialisation ---------------------------------------------------

    def to_dict(self) -> dict:
        return {"iri": self.iri, "label": self.label, "description": self.description,
                "classes": [asdict(c) for c in self.classes.values()],
                "object_properties": [asdict(p) for p in self.object_properties.values()],
                "datatype_properties": [asdict(p) for p in self.datatype_properties.values()]}

    @classmethod
    def from_dict(cls, d: dict) -> Ontology:
        o = cls(iri=d["iri"], label=d.get("label"), description=d.get("description"))
        for c in d.get("classes", []):
            o.add_class(OntoClass(c["iri"], c.get("label"), c.get("description"), tuple(c.get("parents", ()))))
        for p in d.get("object_properties", []):
            o.add_object_property(ObjectProperty(p["iri"], p.get("label"), p.get("description"), p.get("domain"),
                                                 p.get("range"), p.get("inverse_of")))
        for p in d.get("datatype_properties", []):
            o.add_datatype_property(DatatypeProperty(p["iri"], p.get("label"), p.get("description"), p.get("domain"), p.get("range")))
        return o

    def to_turtle(self) -> str:
        from .owl import to_turtle
        return to_turtle(self)

    @classmethod
    def from_turtle(cls, turtle: str) -> Ontology:
        from .owl import from_rdf
        return from_rdf(turtle, "turtle")

    @classmethod
    def from_rdf(cls, data: str, fmt: str) -> Ontology:
        from .owl import from_rdf
        return from_rdf(data, fmt)
