"""Mapping -> Turtle. Emits explicit rr:termType on every non-constant term map so that a
re-parse yields an identical model regardless of R2RML's default-term-type rules."""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF

from .model import Mapping, RefObjectMap, TermKind, TermMap, TriplesMap
from .parser import RR

_TERM_TYPE = {TermKind.IRI: RR.IRI, TermKind.BLANK_NODE: RR.BlankNode, TermKind.LITERAL: RR.Literal}


def serialize_r2rml(mapping: Mapping) -> str:
    g = Graph()
    g.bind("rr", RR)
    for tm in mapping.triples_maps.values():
        _triples_map(g, tm)
    return g.serialize(format="turtle")


def _triples_map(g: Graph, tm: TriplesMap) -> URIRef:
    node = URIRef(tm.iri)
    if (node, RDF.type, RR.TriplesMap) in g:
        return node
    g.add((node, RDF.type, RR.TriplesMap))

    lt = BNode()
    g.add((node, RR.logicalTable, lt))
    if tm.logical_table.table_name is not None:
        g.add((lt, RR.tableName, Literal(tm.logical_table.table_name)))
    else:
        g.add((lt, RR.sqlQuery, Literal(tm.logical_table.sql_query)))

    sm = _term_map(g, tm.subject)
    g.add((node, RR.subjectMap, sm))
    for cls in tm.classes:
        g.add((sm, RR["class"], URIRef(cls)))

    for pom in tm.predicate_object_maps:
        pn = BNode()
        g.add((node, RR.predicateObjectMap, pn))
        for pred in pom.predicates:
            g.add((pn, RR.predicateMap, _term_map(g, pred)))
        for obj in pom.objects:
            g.add((pn, RR.objectMap, _ref_object_map(g, obj) if isinstance(obj, RefObjectMap) else _term_map(g, obj)))
    return node


def _ref_object_map(g: Graph, ref: RefObjectMap) -> BNode:
    node = BNode()
    g.add((node, RR.parentTriplesMap, _triples_map(g, ref.parent_triples_map)))
    for child, parent in ref.join_conditions:
        jc = BNode()
        g.add((node, RR.joinCondition, jc))
        g.add((jc, RR.child, Literal(child)))
        g.add((jc, RR.parent, Literal(parent)))
    return node


def _term_map(g: Graph, tm: TermMap) -> BNode:
    node = BNode()
    if tm.constant is not None:
        g.add((node, RR.constant, _constant(tm)))
        return node
    if tm.column is not None:
        g.add((node, RR.column, Literal(tm.column)))
    else:
        g.add((node, RR.template, Literal(tm.template)))
    g.add((node, RR.termType, _TERM_TYPE[tm.term_kind]))
    if tm.datatype:
        g.add((node, RR.datatype, URIRef(tm.datatype)))
    if tm.language:
        g.add((node, RR.language, Literal(tm.language)))
    return node


def _constant(tm: TermMap):
    if tm.term_kind is TermKind.IRI:
        return URIRef(tm.constant)
    if tm.term_kind is TermKind.BLANK_NODE:
        return BNode(tm.constant)
    return Literal(tm.constant, lang=tm.language, datatype=URIRef(tm.datatype) if tm.datatype else None)
