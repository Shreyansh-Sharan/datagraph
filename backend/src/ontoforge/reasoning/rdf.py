"""Store rows <-> rdflib graphs."""
from __future__ import annotations

from typing import Iterable

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.term import Node


def to_node(value: str, kind: str, datatype: str | None = None, lang: str | None = None) -> Node:
    if kind == "literal":
        return Literal(value, lang=lang) if lang else Literal(value, datatype=URIRef(datatype) if datatype else None)
    if kind == "bnode" or value.startswith("_:"):
        return BNode(value[2:] if value.startswith("_:") else value)
    return URIRef(value)


def rows_to_graph(rows: Iterable[tuple], graph: Graph | None = None) -> Graph:
    g = graph if graph is not None else Graph()
    for s, p, o, ot, dt, lg in rows:
        g.add((to_node(s, "bnode" if s.startswith("_:") else "iri"), URIRef(p), to_node(o, ot, dt, lg)))
    return g


def triple_to_row(t: tuple[Node, Node, Node]) -> tuple:
    s, p, o = t
    subj = f"_:{s}" if isinstance(s, BNode) else str(s)
    if isinstance(o, Literal):
        return (subj, str(p), str(o), "literal", str(o.datatype) if o.datatype else None, o.language or None)
    if isinstance(o, BNode):
        return (subj, str(p), f"_:{o}", "bnode", None, None)
    return (subj, str(p), str(o), "iri", None, None)
