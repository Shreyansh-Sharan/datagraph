"""SWRL rules: Horn clauses over class, property and built-in atoms.

    Employee(?e) ^ salary(?e, ?s) ^ swrlb:greaterThan(?s, 1000) -> HighEarner(?e)

Atoms are stored with resolved IRIs so a rule set is self-contained; ``to_text`` renders the
presentation syntax back with local names.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ontoforge.ontology import Ontology

BUILTINS = ("equal", "notEqual", "lessThan", "lessThanOrEqual", "greaterThan", "greaterThanOrEqual")
MODES = ("materialize", "violation")
Arg = str | int | float   # "?var", "http://iri", "string literal", or a number


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Atom:
    kind: str            # class | property | builtin
    predicate: str       # class/property IRI, or built-in name
    args: tuple[Arg, ...]

    def variables(self) -> set[str]:
        return {a for a in self.args if isinstance(a, str) and a.startswith("?")}


@dataclass(frozen=True)
class Rule:
    name: str
    body: tuple[Atom, ...]
    head: tuple[Atom, ...]
    mode: str = "materialize"
    enabled: bool = True
    text: str = ""

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise RuleError(f"Rule {self.name!r}: mode must be one of {MODES}")
        bound = set().union(*(a.variables() for a in self.body if a.kind != "builtin")) if self.body else set()
        for atom in (*self.body, *self.head):
            for v in atom.variables() - bound:
                raise RuleError(f"Rule {self.name!r}: variable {v} is not bound by a class or property atom in the body")
        if not self.head:
            raise RuleError(f"Rule {self.name!r}: needs at least one head atom")
        for atom in self.head:
            if atom.kind == "builtin":
                raise RuleError(f"Rule {self.name!r}: built-ins are not allowed in the head")

    @classmethod
    def from_text(cls, text: str, ontology: Ontology, name: str, mode: str = "materialize", enabled: bool = True) -> Rule:
        from .parser import parse_rule
        return parse_rule(text, ontology, name=name, mode=mode, enabled=enabled)

    def to_text(self, ontology: Ontology | None = None) -> str:
        ln = (ontology.local_name if ontology else Ontology.local_name)
        return " ^ ".join(_atom_text(a, ln) for a in self.body) + " -> " + " ^ ".join(_atom_text(a, ln) for a in self.head)

    def to_dict(self) -> dict:
        return {"name": self.name, "mode": self.mode, "enabled": self.enabled, "text": self.text,
                "body": [_atom_dict(a) for a in self.body], "head": [_atom_dict(a) for a in self.head]}

    @classmethod
    def from_dict(cls, d: dict) -> Rule:
        return cls(d["name"], tuple(_atom_from(a) for a in d["body"]), tuple(_atom_from(a) for a in d["head"]),
                   d.get("mode", "materialize"), bool(d.get("enabled", True)), d.get("text", ""))


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...] = field(default_factory=tuple)

    def __init__(self, rules=()) -> None:
        object.__setattr__(self, "rules", tuple(rules))
        names = [r.name for r in self.rules]
        if len(set(names)) != len(names):
            raise RuleError("Rule names must be unique")

    def to_dict(self) -> dict:
        return {"rules": [r.to_dict() for r in self.rules]}

    @classmethod
    def from_dict(cls, d: dict | None) -> RuleSet:
        return cls(Rule.from_dict(r) for r in (d or {}).get("rules", []))

    def enabled(self, mode: str | None = None) -> list[Rule]:
        return [r for r in self.rules if r.enabled and (mode is None or r.mode == mode)]


def _atom_text(a: Atom, ln) -> str:
    name = f"swrlb:{a.predicate}" if a.kind == "builtin" else ln(a.predicate)
    return f"{name}({', '.join(_arg_text(x) for x in a.args)})"


def _arg_text(x: Arg) -> str:
    if isinstance(x, (int, float)):
        return str(x)
    if x.startswith("?"):
        return x
    if x.startswith(("http://", "https://", "urn:")):
        return f"<{x}>"
    return '"' + x.replace('"', '\\"') + '"'


def _atom_dict(a: Atom) -> dict:
    return {"kind": a.kind, "predicate": a.predicate, "args": list(a.args)}


def _atom_from(d: dict) -> Atom:
    return Atom(d["kind"], d["predicate"], tuple(d["args"]))
