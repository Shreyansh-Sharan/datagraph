"""Data-quality constraints: a small, SQL-checkable subset of SHACL property shapes."""
from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("min_count", "max_count", "datatype", "class", "pattern", "in", "min_inclusive", "max_inclusive",
         "min_exclusive", "max_exclusive", "unique", "node_kind", "require_label", "no_orphans")
GLOBAL_KINDS = ("require_label", "no_orphans")   # apply to the entity itself; property is None
SEVERITIES = ("violation", "warning", "info")
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


class QualityError(ValueError):
    pass


@dataclass(frozen=True)
class Constraint:
    name: str
    target_class: str
    property: str | None
    kind: str
    value: object = None
    severity: str = "violation"
    message: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise QualityError(f"Constraint {self.name!r}: unknown kind {self.kind!r}; use one of {KINDS}")
        if self.severity not in SEVERITIES:
            raise QualityError(f"Constraint {self.name!r}: severity must be one of {SEVERITIES}")
        if self.kind in ("min_count", "max_count") and (not isinstance(self.value, int) or self.value < 0):
            raise QualityError(f"Constraint {self.name!r}: {self.kind} needs a non-negative integer")
        if self.kind in ("min_inclusive", "max_inclusive", "min_exclusive", "max_exclusive") and not isinstance(self.value, (int, float)):
            raise QualityError(f"Constraint {self.name!r}: {self.kind} needs a number")
        if self.kind == "in" and not (isinstance(self.value, list) and self.value):
            raise QualityError(f"Constraint {self.name!r}: 'in' needs a non-empty list of values")
        if self.kind == "node_kind" and self.value not in ("iri", "literal", "bnode"):
            raise QualityError(f"Constraint {self.name!r}: node_kind must be iri, literal or bnode")
        if self.kind in ("datatype", "class", "pattern") and not isinstance(self.value, str):
            raise QualityError(f"Constraint {self.name!r}: {self.kind} needs a string value")
        if self.kind in GLOBAL_KINDS and self.property is not None:
            raise QualityError(f"Constraint {self.name!r}: {self.kind} applies to the entity; leave property empty")
        if self.kind not in GLOBAL_KINDS and not self.property:
            raise QualityError(f"Constraint {self.name!r}: {self.kind} needs a property")

    def default_message(self) -> str:
        return {
            "min_count": f"needs at least {self.value} value(s)", "max_count": f"allows at most {self.value} value(s)",
            "datatype": f"must be a {self.value.rsplit('#', 1)[-1] if isinstance(self.value, str) else self.value} literal",
            "class": f"must reference an instance of {str(self.value).rsplit('#', 1)[-1]}",
            "pattern": f"must match {self.value}", "in": f"must be one of {self.value}",
            "min_inclusive": f"must be >= {self.value}", "max_inclusive": f"must be <= {self.value}",
            "min_exclusive": f"must be > {self.value}", "max_exclusive": f"must be < {self.value}",
            "unique": "must be unique across instances", "node_kind": f"must be a(n) {self.value}",
            "require_label": "must have a label or name", "no_orphans": "must be connected to at least one other entity",
        }[self.kind]

    def to_dict(self) -> dict:
        return {"name": self.name, "target_class": self.target_class, "property": self.property, "kind": self.kind,
                "value": self.value, "severity": self.severity, "message": self.message}

    @classmethod
    def from_dict(cls, d: dict) -> Constraint:
        return cls(d["name"], d["target_class"], d["property"], d["kind"], d.get("value"),
                   d.get("severity", "violation"), d.get("message"))


@dataclass(frozen=True)
class ConstraintSet:
    constraints: tuple[Constraint, ...] = field(default_factory=tuple)

    def __init__(self, constraints=()) -> None:
        object.__setattr__(self, "constraints", tuple(constraints))
        names = [c.name for c in self.constraints]
        if len(set(names)) != len(names):
            raise QualityError("Constraint names must be unique")

    def to_dict(self) -> dict:
        return {"constraints": [c.to_dict() for c in self.constraints]}

    @classmethod
    def from_dict(cls, d: dict | None) -> ConstraintSet:
        return cls(Constraint.from_dict(c) for c in (d or {}).get("constraints", []))

    def to_shacl(self) -> str:
        from .shacl import to_shacl
        return to_shacl(self)

    @classmethod
    def from_shacl(cls, turtle: str) -> ConstraintSet:
        from .shacl import from_shacl
        return from_shacl(turtle)
