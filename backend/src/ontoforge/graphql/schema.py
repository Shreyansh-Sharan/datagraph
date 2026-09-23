"""A GraphQL schema generated from a domain's ontology and resolved against its triple store.

Each class becomes an object type with ``id``, ``label``, ``types``, one field per (inherited)
datatype property, and one list field per (inherited) object property whose range is a known
class. The root query gets ``<plural>(search, limit)`` and ``<singular>(id)`` per class.
"""
from __future__ import annotations

import re
from uuid import UUID

from graphql import (
    GraphQLArgument, GraphQLBoolean, GraphQLField, GraphQLFloat, GraphQLInt, GraphQLList, GraphQLNonNull,
    GraphQLObjectType, GraphQLSchema, GraphQLString,
)

from ontoforge.ontology import DatatypeProperty, ObjectProperty, Ontology, XSD
from ontoforge.registry import Registry
from ontoforge.store import EntityDetail, TripleStore

_SCALARS = {
    XSD + "integer": GraphQLInt, XSD + "int": GraphQLInt, XSD + "long": GraphQLInt,
    XSD + "decimal": GraphQLFloat, XSD + "double": GraphQLFloat, XSD + "float": GraphQLFloat,
    XSD + "boolean": GraphQLBoolean,
}
_CASTS = {GraphQLInt: int, GraphQLFloat: float, GraphQLBoolean: lambda v: str(v).lower() in ("true", "1")}


def build_schema(registry: Registry, store: TripleStore, version_id: UUID) -> GraphQLSchema:
    version = registry.get_version(version_id)
    ontology = Ontology.from_turtle(version.ontology_ttl or "")
    return schema_for(ontology, store, version_id)


def schema_for(ontology: Ontology, store: TripleStore, version_id: UUID) -> GraphQLSchema:
    types: dict[str, GraphQLObjectType] = {}
    type_names = _unique_names({c: pascal(Ontology.local_name(c)) for c in ontology.classes})

    def fields_for(class_iri: str):
        def thunk():
            fields = {
                "id": GraphQLField(GraphQLNonNull(GraphQLString), resolve=lambda e, info: e.iri),
                "label": GraphQLField(GraphQLNonNull(GraphQLString), resolve=lambda e, info: e.label),
                "types": GraphQLField(GraphQLNonNull(GraphQLList(GraphQLNonNull(GraphQLString))), resolve=lambda e, info: list(e.types)),
            }
            names = _unique_names({p.iri: camel(Ontology.local_name(p.iri)) for p in ontology.properties_of(class_iri)},
                                  taken=set(fields))
            for p in ontology.properties_of(class_iri):
                if isinstance(p, DatatypeProperty):
                    fields[names[p.iri]] = GraphQLField(_SCALARS.get(p.range or "", GraphQLString), resolve=_attr(p.iri))
                elif isinstance(p, ObjectProperty) and p.range in types:
                    if p.functional:
                        fields[names[p.iri]] = GraphQLField(types[p.range], resolve=_related(p.iri, store, version_id, single=True))
                    else:
                        fields[names[p.iri]] = GraphQLField(GraphQLNonNull(GraphQLList(GraphQLNonNull(types[p.range]))),
                                                            resolve=_related(p.iri, store, version_id))
            return fields
        return thunk

    for class_iri, name in type_names.items():
        types[class_iri] = GraphQLObjectType(name, fields=fields_for(class_iri))

    query_fields = {}
    for class_iri, gql_type in types.items():
        name = type_names[class_iri]
        single, many = camel(name), camel(plural(name))
        scope = [class_iri, *ontology.descendants(class_iri)]
        query_fields[many] = GraphQLField(
            GraphQLNonNull(GraphQLList(GraphQLNonNull(gql_type))),
            args={"search": GraphQLArgument(GraphQLString), "limit": GraphQLArgument(GraphQLInt)},
            resolve=_list(store, version_id, scope))
        query_fields[single] = GraphQLField(gql_type, args={"id": GraphQLArgument(GraphQLNonNull(GraphQLString))},
                                            resolve=_one(store, version_id, scope))
    return GraphQLSchema(query=GraphQLObjectType("Query", fields=query_fields))


# -- resolvers -----------------------------------------------------------------

def _attr(predicate: str):
    def resolve(entity: EntityDetail, info):
        for a in entity.attributes:
            if a.predicate == predicate:
                cast = _CASTS.get(info.return_type, str)
                try:
                    return cast(a.value)
                except (TypeError, ValueError):
                    return None
        return None
    return resolve


def _related(predicate: str, store: TripleStore, version_id: UUID, single: bool = False):
    def resolve(entity: EntityDetail, info):
        out = []
        for r in entity.outgoing:
            if r.predicate == predicate:
                target = store.describe(version_id, r.target)
                if target is not None:
                    out.append(target)
                    if single:
                        return target
        return None if single else out
    return resolve


def _list(store: TripleStore, version_id: UUID, scope: list[str]):
    def resolve(root, info, search: str | None = None, limit: int | None = None):
        out, budget = [], min(limit or 50, 500)
        for class_iri in scope:
            for hit in store.search(version_id, search or "", type_iri=class_iri, limit=budget):
                if len(out) >= budget:
                    return out
                detail = store.describe(version_id, hit.iri)
                if detail is not None and detail.iri not in {d.iri for d in out}:
                    out.append(detail)
        return out
    return resolve


def _one(store: TripleStore, version_id: UUID, scope: list[str]):
    def resolve(root, info, id: str):
        detail = store.describe(version_id, id)
        return detail if detail is not None and set(detail.types) & set(scope) else None
    return resolve


# -- naming --------------------------------------------------------------------

def pascal(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    return "".join(w[:1].upper() + w[1:] for w in words) or "T"


def camel(name: str) -> str:
    p = pascal(name)
    return p[:1].lower() + p[1:]


def plural(name: str) -> str:
    if name.endswith("y") and name[-2:-1].lower() not in "aeiou":
        return name[:-1] + "ies"
    if name.endswith(("s", "x", "ch", "sh")):
        return name + "es"
    return name + "s"


def _unique_names(candidates: dict[str, str], taken: set[str] | None = None) -> dict[str, str]:
    used, out = set(taken or ()), {}
    for key, name in candidates.items():
        base, n = name, 2
        while name in used:
            name, n = f"{base}{n}", n + 1
        used.add(name)
        out[key] = name
    return out
