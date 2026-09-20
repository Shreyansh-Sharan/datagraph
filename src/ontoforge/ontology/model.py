"""Ontology model: OWL 2 classes and properties, kept deliberately small.

Everything here maps 1:1 onto OWL/RDFS vocabulary: owl:Class, rdfs:subClassOf, owl:ObjectProperty,
owl:DatatypeProperty, rdfs:domain/range, owl:inverseOf, rdfs:subPropertyOf, owl:propertyChainAxiom,
the property-characteristic classes (owl:FunctionalProperty, ...), owl:equivalentClass,
owl:disjointWith, and owl:Restriction (cardinality / allValuesFrom / someValuesFrom / hasValue).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Iterator

XSD = "http://www.w3.org/2001/XMLSchema#"

CHARACTERISTICS = ("functional", "inverse_functional", "transitive", "symmetric", "asymmetric", "reflexive", "irreflexive")
RESTRICTION_KINDS = ("min", "max", "exactly", "some", "only", "has_value")


@dataclass(frozen=True)
class Restriction:
    """A class restriction on a property: cardinality (min/max/exactly: int) or value (some/only: class or
    datatype IRI; has_value: a literal or IRI string)."""
    property: str
    kind: str
    value: int | str

    def __post_init__(self) -> None:
        if self.kind not in RESTRICTION_KINDS:
            raise ValueError(f"Unknown restriction kind {self.kind!r}")


@dataclass(frozen=True)
class OntoClass:
    iri: str
    label: str | None = None
    description: str | None = None
    parents: tuple[str, ...] = ()
    equivalent_to: tuple[str, ...] = ()
    disjoint_with: tuple[str, ...] = ()
    restrictions: tuple[Restriction, ...] = ()

    def __post_init__(self) -> None:
        # Sets in OWL; normalise order so equality and round-trips are stable.
        object.__setattr__(self, "parents", tuple(sorted(self.parents)))
        object.__setattr__(self, "equivalent_to", tuple(sorted(self.equivalent_to)))
        object.__setattr__(self, "disjoint_with", tuple(sorted(self.disjoint_with)))
        object.__setattr__(self, "restrictions", tuple(sorted(self.restrictions, key=lambda r: (r.property, r.kind, str(r.value)))))


def _normalise_domains(obj) -> None:
    """``domains`` is the full (union) domain; ``domain`` stays the primary member for single-domain callers."""
    domains = tuple(sorted(set(obj.domains) | ({obj.domain} if obj.domain else set())))
    object.__setattr__(obj, "domains", domains if len(domains) > 1 else ())
    if obj.domain is None and domains:
        object.__setattr__(obj, "domain", domains[0])


@dataclass(frozen=True)
class ObjectProperty:
    iri: str
    label: str | None = None
    description: str | None = None
    domain: str | None = None
    range: str | None = None
    inverse_of: str | None = None
    characteristics: tuple[str, ...] = ()
    sub_property_of: tuple[str, ...] = ()
    chain: tuple[tuple[str, ...], ...] = ()   # owl:propertyChainAxiom(s)
    domains: tuple[str, ...] = ()             # union domain (owl:unionOf) when the property applies to several classes

    def __post_init__(self) -> None:
        known = [c for c in CHARACTERISTICS if c in self.characteristics]
        unknown = [c for c in self.characteristics if c not in CHARACTERISTICS]
        object.__setattr__(self, "characteristics", tuple(known + unknown))
        object.__setattr__(self, "sub_property_of", tuple(sorted(self.sub_property_of)))
        object.__setattr__(self, "chain", tuple(sorted(tuple(c) for c in self.chain)))
        _normalise_domains(self)

    @property
    def all_domains(self) -> tuple[str, ...]:
        return self.domains or ((self.domain,) if self.domain else ())

    @property
    def functional(self) -> bool:
        return "functional" in self.characteristics


@dataclass(frozen=True)
class DatatypeProperty:
    iri: str
    label: str | None = None
    description: str | None = None
    domain: str | None = None
    range: str | None = None  # an XSD datatype IRI
    functional: bool = False
    domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _normalise_domains(self)

    @property
    def all_domains(self) -> tuple[str, ...]:
        return self.domains or ((self.domain,) if self.domain else ())


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

    def properties_of(self, class_iri: str, include_global: bool = True) -> list[ObjectProperty | DatatypeProperty]:
        """Properties whose domain is the class or an ancestor; domain-less properties apply everywhere."""
        scope = {class_iri, *self.ancestors(class_iri)}
        out = []
        for p in (*self.object_properties.values(), *self.datatype_properties.values()):
            if p.domain is None:
                if include_global:
                    out.append(p)
            elif any(d in scope for d in p.all_domains):
                out.append(p)
        return out

    def all_properties(self) -> Iterator[ObjectProperty | DatatypeProperty]:
        yield from self.object_properties.values()
        yield from self.datatype_properties.values()

    def property(self, iri: str) -> ObjectProperty | DatatypeProperty | None:
        return self.object_properties.get(iri) or self.datatype_properties.get(iri)

    def restrictions_of(self, class_iri: str) -> list[Restriction]:
        """Own restrictions plus inherited ones."""
        out = []
        for iri in (class_iri, *self.ancestors(class_iri)):
            out.extend(self.classes.get(iri, OntoClass(iri)).restrictions)
        return out

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
            for d in c.disjoint_with:
                if d == c.iri or d in self.ancestors(c.iri):
                    issues.append(Issue("disjoint-with-ancestor", c.iri, f"Class is disjoint with itself or an ancestor ({d})", "error"))
                elif d not in self.classes:
                    issues.append(Issue("unknown-class-reference", c.iri, f"owl:disjointWith {d} is not defined", "error"))
            for e in c.equivalent_to:
                if e not in self.classes:
                    issues.append(Issue("unknown-class-reference", c.iri, f"owl:equivalentClass {e} is not defined", "error"))
            for r in c.restrictions:
                if self.property(r.property) is None:
                    issues.append(Issue("unknown-restriction-property", c.iri, f"Restriction on unknown property {r.property}", "error"))
        for p in self.all_properties():
            if not p.label:
                issues.append(Issue("missing-label", p.iri, "Property has no rdfs:label"))
            if p.domain is None:
                issues.append(Issue("missing-domain", p.iri, "Property has no rdfs:domain"))
            else:
                for d in p.all_domains:
                    if d not in self.classes:
                        issues.append(Issue("unknown-domain", p.iri, f"Domain {d} is not a class of this ontology", "error"))
            if p.range is None:
                issues.append(Issue("missing-range", p.iri, "Property has no rdfs:range"))
            elif isinstance(p, ObjectProperty) and p.range not in self.classes:
                issues.append(Issue("unknown-range", p.iri, f"Range {p.range} is not a class of this ontology", "error"))
            elif isinstance(p, DatatypeProperty) and not p.range.startswith(XSD):
                issues.append(Issue("non-xsd-range", p.iri, f"Datatype property range {p.range} is not an XSD type"))
            if isinstance(p, ObjectProperty):
                for ch in p.characteristics:
                    if ch not in CHARACTERISTICS:
                        issues.append(Issue("unknown-characteristic", p.iri, f"Unknown characteristic {ch}", "error"))
                if "symmetric" in p.characteristics and "asymmetric" in p.characteristics:
                    issues.append(Issue("contradictory-characteristics", p.iri, "Both symmetric and asymmetric", "error"))
                for sp in p.sub_property_of:
                    if sp not in self.object_properties:
                        issues.append(Issue("unknown-property-reference", p.iri, f"rdfs:subPropertyOf {sp} is not defined", "error"))
                for chain in p.chain:
                    for link in chain:
                        if link not in self.object_properties:
                            issues.append(Issue("unknown-property-reference", p.iri, f"Chain link {link} is not defined", "error"))
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
            o.add_class(OntoClass(c["iri"], c.get("label"), c.get("description"), tuple(c.get("parents", ())),
                                  tuple(c.get("equivalent_to", ())), tuple(c.get("disjoint_with", ())),
                                  tuple(Restriction(r["property"], r["kind"], r["value"]) for r in c.get("restrictions", ()))))
        for p in d.get("object_properties", []):
            o.add_object_property(ObjectProperty(p["iri"], p.get("label"), p.get("description"), p.get("domain"),
                                                 p.get("range"), p.get("inverse_of"), tuple(p.get("characteristics", ())),
                                                 tuple(p.get("sub_property_of", ())),
                                                 tuple(tuple(ch) for ch in p.get("chain", ())), tuple(p.get("domains", ()))))
        for p in d.get("datatype_properties", []):
            o.add_datatype_property(DatatypeProperty(p["iri"], p.get("label"), p.get("description"), p.get("domain"),
                                                     p.get("range"), bool(p.get("functional", False)), tuple(p.get("domains", ()))))
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
