"""In-memory model of an R2RML mapping document.

Mirrors the vocabulary of the W3C R2RML Recommendation (https://www.w3.org/TR/r2rml/):
a mapping is a set of triples maps; each has one logical table, one subject map and
zero or more predicate-object maps; every map position is a term map (constant-,
column- or template-valued) except referencing object maps, which point at another
triples map and optionally carry join conditions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MappingError(ValueError):
    """The mapping document violates an R2RML constraint or is unsupported."""


class TermKind(Enum):
    IRI = "iri"
    BLANK_NODE = "bnode"
    LITERAL = "literal"


@dataclass(frozen=True)
class LogicalTable:
    table_name: str | None = None
    sql_query: str | None = None

    def __post_init__(self) -> None:
        if (self.table_name is None) == (self.sql_query is None):
            raise MappingError("A logical table needs exactly one of rr:tableName / rr:sqlQuery")


@dataclass(frozen=True)
class TermMap:
    term_kind: TermKind
    constant: str | None = None
    column: str | None = None
    template: str | None = None
    datatype: str | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        sources = [s for s in (self.constant, self.column, self.template) if s is not None]
        if len(sources) != 1:
            raise MappingError("A term map must have exactly one of rr:constant / rr:column / rr:template")
        if (self.datatype or self.language) and self.term_kind is not TermKind.LITERAL:
            raise MappingError("rr:datatype / rr:language are only allowed on literal term maps")
        if self.datatype and self.language:
            raise MappingError("A term map may not carry both rr:datatype and rr:language")

    @property
    def is_constant(self) -> bool:
        return self.constant is not None


@dataclass(frozen=True)
class RefObjectMap:
    """rr:parentTriplesMap + rr:joinCondition* (R2RML §8)."""
    parent_triples_map: TriplesMap
    join_conditions: tuple[tuple[str, str], ...] = ()  # (child column, parent column)


@dataclass(frozen=True)
class PredicateObjectMap:
    predicates: tuple[TermMap, ...]
    objects: tuple[TermMap | RefObjectMap, ...]


@dataclass(frozen=True)
class TriplesMap:
    iri: str
    logical_table: LogicalTable
    subject: TermMap
    classes: tuple[str, ...] = ()
    predicate_object_maps: tuple[PredicateObjectMap, ...] = ()


@dataclass
class Mapping:
    triples_maps: dict[str, TriplesMap] = field(default_factory=dict)

    def only(self) -> TriplesMap:
        """The single triples map of a one-map document (test/CLI convenience)."""
        if len(self.triples_maps) != 1:
            raise MappingError(f"Expected exactly one triples map, found {len(self.triples_maps)}")
        return next(iter(self.triples_maps.values()))
