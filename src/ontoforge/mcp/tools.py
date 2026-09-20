"""The knowledge graph as a small set of LLM-facing tools.

Every tool takes a domain *name*; the served version is the latest PUBLISHED one, falling back
to the latest version of any status so a draft can be explored before release. Tools return
plain text or JSON strings — what an LLM client can consume directly.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from graphql import graphql_sync, print_schema

from ontoforge.graphql import build_schema
from ontoforge.ontology import DatatypeProperty, Ontology
from ontoforge.registry import DomainVersion, NotFound, Registry, Status
from ontoforge.store import TripleStore


class GraphTools:
    def __init__(self, registry: Registry, store: TripleStore) -> None:
        self.registry, self.store = registry, store

    # -- domain resolution ------------------------------------------------------

    def _version(self, domain: str) -> DomainVersion | None:
        try:
            d = self.registry.get_domain(domain)
        except NotFound:
            return None
        return self.registry.latest_version(d.id, status=Status.PUBLISHED) or self.registry.latest_version(d.id)

    def _ontology(self, version: DomainVersion) -> Ontology | None:
        return Ontology.from_turtle(version.ontology_ttl) if version.ontology_ttl else None

    # -- tools ------------------------------------------------------------------

    def list_domains(self) -> list[dict]:
        out = []
        for d in self.registry.list_domains():
            published = self.registry.latest_version(d.id, status=Status.PUBLISHED)
            v = published or self.registry.latest_version(d.id)
            out.append({"name": d.name, "description": d.description, "base_iri": d.base_iri,
                        "published_version": published.version if published else None,
                        "version": v.version if v else None, "status": v.status.value if v else None,
                        "triples": self.store.count(v.id) if v else 0})
        return out

    def describe_ontology(self, domain: str) -> str:
        v = self._version(domain)
        if v is None:
            return f"Unknown domain {domain!r}. Call list_domains to see what exists."
        o = self._ontology(v)
        if o is None:
            return f"Domain {domain!r} has no ontology yet."
        lines = [f"Ontology {o.label or o.iri} ({o.iri}) — {len(o.classes)} classes, "
                 f"{len(o.datatype_properties)} attributes, {len(o.object_properties)} relationships", ""]
        for c in sorted(o.classes.values(), key=lambda c: c.iri):
            head = f"Class {o.local_name(c.iri)}"
            if c.parents:
                head += " (subclass of " + ", ".join(o.local_name(p) for p in c.parents) + ")"
            if c.description:
                head += f": {c.description}"
            lines.append(head)
            for p in o.properties_of(c.iri):
                kind = "attribute" if isinstance(p, DatatypeProperty) else "relationship"
                rng = o.local_name(p.range) if p.range else "?"
                lines.append(f"  - {o.local_name(p.iri)} [{kind} -> {rng}]" + (f": {p.description}" if p.description else ""))
        return "\n".join(lines)

    def graph_status(self, domain: str) -> dict:
        v = self._version(domain)
        if v is None:
            return {"error": f"Unknown domain {domain!r}"}
        return {"domain": domain, "version": v.version, "status": v.status.value,
                "triples": self.store.count(v.id), "inferred": self.store.count(v.id, inferred=True),
                "types": dict(self.store.type_inventory(v.id))}

    def search_entities(self, domain: str, query: str, entity_type: str | None = None, limit: int = 10) -> list[dict]:
        v = self._version(domain)
        if v is None:
            return [{"error": f"Unknown domain {domain!r}"}]
        type_iri = self._resolve_type(v, entity_type) if entity_type else None
        return [asdict(e) for e in self.store.search(v.id, query, type_iri=type_iri, limit=max(1, min(limit, 100)))]

    def describe_entity(self, domain: str, entity: str, depth: int = 1) -> str:
        v = self._version(domain)
        if v is None:
            return f"Unknown domain {domain!r}."
        detail = self.store.describe(v.id, entity)
        if detail is None:
            hits = self.store.search(v.id, entity, limit=1)
            detail = self.store.describe(v.id, hits[0].iri) if hits else None
        if detail is None:
            return f"Entity {entity!r} not found in domain {domain!r}."
        o = self._ontology(v) or Ontology(iri="urn:none")
        ln = o.local_name
        lines = [f"{detail.label} <{detail.iri}>", "Types: " + ", ".join(ln(t) for t in detail.types) or "Types: (none)"]
        if detail.attributes:
            lines.append("Attributes:")
            lines += [f"  - {ln(a.predicate)}: {a.value}" + (" (inferred)" if a.inferred else "") for a in detail.attributes]
        if detail.outgoing:
            lines.append("Relationships:")
            for r in detail.outgoing:
                target = self.store.describe(v.id, r.target)
                lines.append(f"  - {ln(r.predicate)} -> {target.label if target else ln(r.target)} <{r.target}>"
                             + (" (inferred)" if r.inferred else ""))
        if detail.incoming:
            lines.append("Referenced by:")
            for r in detail.incoming:
                src = self.store.describe(v.id, r.source)
                lines.append(f"  - {src.label if src else ln(r.source)} <{r.source}> {ln(r.predicate)} -> this")
        if depth > 1:
            sub = self.store.neighbourhood(v.id, detail.iri, depth=depth, limit=100)
            lines.append(f"Neighbourhood (depth {depth}): {len(sub.nodes)} entities, {len(sub.edges)} edges")
            lines += [f"  - {ln(e.source)} --{ln(e.predicate)}--> {ln(e.target)}" for e in sub.edges[:60]]
        return "\n".join(lines)

    def get_graphql_schema(self, domain: str) -> str:
        v = self._version(domain)
        if v is None:
            return f"Unknown domain {domain!r}."
        return print_schema(build_schema(self.registry, self.store, v.id))

    def query_graphql(self, domain: str, query: str, variables: dict | None = None) -> str:
        v = self._version(domain)
        if v is None:
            return json.dumps({"errors": [{"message": f"Unknown domain {domain!r}"}]})
        result = graphql_sync(build_schema(self.registry, self.store, v.id), query, variable_values=variables)
        out: dict = {"data": result.data}
        if result.errors:
            out["errors"] = [{"message": e.message, "path": e.path} for e in result.errors]
        return json.dumps(out, default=str)

    # -- helpers ----------------------------------------------------------------

    def _resolve_type(self, v: DomainVersion, name: str) -> str | None:
        o = self._ontology(v)
        if o is None:
            return name
        for iri in o.classes:
            if iri == name or o.local_name(iri).lower() == name.lower():
                return iri
        return name
