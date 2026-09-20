from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entity:
    iri: str
    label: str
    types: tuple[str, ...]


@dataclass(frozen=True)
class Attribute:
    predicate: str
    value: str
    datatype: str | None = None
    lang: str | None = None
    inferred: bool = False


@dataclass(frozen=True)
class Relation:
    predicate: str
    target: str | None = None  # outgoing
    source: str | None = None  # incoming
    inferred: bool = False


@dataclass(frozen=True)
class EntityDetail:
    iri: str
    label: str
    types: tuple[str, ...]
    attributes: tuple[Attribute, ...]
    outgoing: tuple[Relation, ...]
    incoming: tuple[Relation, ...]


@dataclass(frozen=True)
class Edge:
    source: str
    predicate: str
    target: str


@dataclass
class Subgraph:
    nodes: list[Entity] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
