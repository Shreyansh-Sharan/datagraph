"""Turtle -> Mapping. Uses rdflib for RDF parsing; all R2RML semantics live here."""
from __future__ import annotations

from rdflib import Graph, Literal, Namespace, URIRef, BNode
from rdflib.term import Node

from .model import (
    LogicalTable, Mapping, MappingError, PredicateObjectMap, RefObjectMap, TermKind, TermMap, TriplesMap,
)

RR = Namespace("http://www.w3.org/ns/r2rml#")

_TERM_TYPES = {RR.IRI: TermKind.IRI, RR.BlankNode: TermKind.BLANK_NODE, RR.Literal: TermKind.LITERAL}


def parse_r2rml(turtle: str, base: str = "http://ontoforge.local/mapping/") -> Mapping:
    g = Graph()
    g.parse(data=turtle, format="turtle", publicID=base)
    return _MappingReader(g).read()


class _MappingReader:
    def __init__(self, g: Graph) -> None:
        self.g = g
        self._cache: dict[Node, TriplesMap] = {}
        self._in_progress: set[Node] = set()

    def read(self) -> Mapping:
        nodes = set(self.g.subjects(RR.logicalTable, None)) | set(self.g.subjects(RR.subjectMap, None)) \
            | set(self.g.subjects(RR.subject, None)) | set(self.g.subjects(None, RR.TriplesMap))
        mapping = Mapping()
        for node in sorted(nodes, key=str):  # deterministic order => deterministic SQL
            tm = self._triples_map(node)
            mapping.triples_maps[tm.iri] = tm
        return mapping

    # -- triples map ---------------------------------------------------------

    def _triples_map(self, node: Node) -> TriplesMap:
        if node in self._cache:
            return self._cache[node]
        if node in self._in_progress:
            raise MappingError(f"Cyclic rr:parentTriplesMap reference involving {node}")
        self._in_progress.add(node)

        lt_node = self._one(node, RR.logicalTable, required=True)
        logical_table = self._logical_table(lt_node)
        subject = self._position_map(node, RR.subjectMap, RR.subject, default=TermKind.IRI)
        classes = tuple(sorted(str(c) for c in self.g.objects(self._one(node, RR.subjectMap), RR["class"])))
        poms = tuple(sorted((self._predicate_object_map(p) for p in self.g.objects(node, RR.predicateObjectMap)),
                            key=repr))  # RDF has no order; sort so output is stable

        tm = TriplesMap(iri=str(node), logical_table=logical_table, subject=subject,
                        classes=classes, predicate_object_maps=poms)
        self._in_progress.discard(node)
        self._cache[node] = tm
        return tm

    def _logical_table(self, node: Node) -> LogicalTable:
        name = self._one(node, RR.tableName)
        query = self._one(node, RR.sqlQuery)
        return LogicalTable(table_name=_text(name), sql_query=_text(query))

    def _predicate_object_map(self, node: Node) -> PredicateObjectMap:
        predicates = tuple(self._term_map(pm, TermKind.IRI) for pm in self.g.objects(node, RR.predicateMap)) + \
            tuple(self._constant_term(c, TermKind.IRI) for c in self.g.objects(node, RR.predicate))
        objects: list[TermMap | RefObjectMap] = []
        for om in self.g.objects(node, RR.objectMap):
            parent = self._one(om, RR.parentTriplesMap)
            objects.append(self._ref_object_map(om, parent) if parent is not None else self._object_map(om))
        objects += [self._constant_term(c, None) for c in self.g.objects(node, RR.object)]
        if not predicates or not objects:
            raise MappingError("A predicateObjectMap needs at least one predicate and one object")
        return PredicateObjectMap(predicates=predicates, objects=tuple(objects))

    def _ref_object_map(self, node: Node, parent: Node) -> RefObjectMap:
        joins = []
        for jc in self.g.objects(node, RR.joinCondition):
            child, par = _text(self._one(jc, RR.child)), _text(self._one(jc, RR.parent))
            if not child or not par:
                raise MappingError("rr:joinCondition needs both rr:child and rr:parent")
            joins.append((child, par))
        return RefObjectMap(parent_triples_map=self._triples_map(parent), join_conditions=tuple(joins))

    # -- term maps -----------------------------------------------------------

    def _position_map(self, node: Node, map_prop: URIRef, shortcut: URIRef, default: TermKind) -> TermMap:
        map_node, const = self._one(node, map_prop), self._one(node, shortcut)
        if (map_node is None) == (const is None):
            raise MappingError(f"Exactly one of {map_prop.n3()} / {shortcut.n3()} is required")
        return self._term_map(map_node, default) if map_node is not None else self._constant_term(const, default)

    def _object_map(self, node: Node) -> TermMap:
        column, template = _text(self._one(node, RR.column)), _text(self._one(node, RR.template))
        datatype, language = self._one(node, RR.datatype), _text(self._one(node, RR.language))
        explicit = self._one(node, RR.termType)
        # R2RML §7.4 default term type for object maps.
        if explicit is not None:
            kind = _TERM_TYPES.get(explicit)
            if kind is None:
                raise MappingError(f"Unknown rr:termType {explicit}")
        elif column is not None or datatype is not None or language is not None:
            kind = TermKind.LITERAL
        else:
            kind = TermKind.IRI
        return self._term_map(node, kind)

    def _term_map(self, node: Node, default: TermKind) -> TermMap:
        explicit = self._one(node, RR.termType)
        kind = default
        if explicit is not None:
            kind = _TERM_TYPES.get(explicit)
            if kind is None:
                raise MappingError(f"Unknown rr:termType {explicit}")
        const = self._one(node, RR.constant)
        datatype = self._one(node, RR.datatype)
        if const is not None:
            return self._constant_term(const, kind)
        return TermMap(term_kind=kind, column=_text(self._one(node, RR.column)),
                       template=_text(self._one(node, RR.template)),
                       datatype=str(datatype) if datatype is not None else None,
                       language=_text(self._one(node, RR.language)))

    @staticmethod
    def _constant_term(value: Node, default: TermKind | None) -> TermMap:
        if isinstance(value, Literal):
            return TermMap(term_kind=TermKind.LITERAL, constant=str(value),
                           datatype=str(value.datatype) if value.datatype else None,
                           language=value.language or None)
        if isinstance(value, URIRef):
            return TermMap(term_kind=TermKind.IRI, constant=str(value))
        if isinstance(value, BNode):
            return TermMap(term_kind=TermKind.BLANK_NODE, constant=str(value))
        raise MappingError(f"Unsupported constant {value!r}")

    # -- helpers -------------------------------------------------------------

    def _one(self, node: Node, prop: URIRef, required: bool = False) -> Node | None:
        values = list(self.g.objects(node, prop))
        if len(values) > 1:
            raise MappingError(f"{prop.n3()} must not be repeated on {node}")
        if not values:
            if required:
                raise MappingError(f"{prop.n3()} is required on {node}")
            return None
        return values[0]


def _text(node: Node | None) -> str | None:
    return None if node is None else str(node)
