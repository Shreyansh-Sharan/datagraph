"""The knowledge graph as a small set of LLM-facing tools.

Every tool takes a domain *name*; the served version is the latest PUBLISHED one, falling back
to the latest version of any status so a draft can be explored before release. Tools return
plain text or JSON strings — what an LLM client can consume directly.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import json
from dataclasses import asdict

from graphql import graphql_sync, print_schema

from ontoforge.constants import MCP_TOOLS
from ontoforge.graphql import build_schema
from ontoforge.mapping import MappingSpec, mapping_status
from ontoforge.ontology import DatatypeProperty, Ontology
from ontoforge.registry import Domain, DomainVersion, NotFound, Registry, Status
from ontoforge.store import TripleStore


ACTOR: ContextVar[str | None] = ContextVar("ontoforge_mcp_actor", default=None)   # who is calling: set by the API guard and by the assistant


def _plain(v):
    """JSON-safe copies of dataclasses, UUIDs, datetimes and Decimals, recursively."""
    if is_dataclass(v):
        return _plain(asdict(v))
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, (UUID, datetime, Decimal)):
        return str(v) if not isinstance(v, datetime) else v.isoformat()
    return v


class GraphTools:
    def __init__(self, registry: Registry, store: TripleStore, metadata=None, attachments=None, services=None) -> None:
        self.registry, self.store, self.metadata, self.attachments = registry, store, metadata, attachments
        self.services = services            # the app's state: profiles, tabledq, glossary, scheduler, sources
        self.current: str | None = None   # domain selected with select_domain (per server instance)

    # -- the working version and the caller ----------------------------------------------------------

    def _working(self, domain: str | None):
        """The version design work happens on: the newest draft, else what is served."""
        d = self._domain(domain)
        if d is None:
            return None, None
        return d, (self.registry.latest_version(d.id, Status.DRAFT) or self.registry.served_version(d.id))

    @staticmethod
    def _actor() -> str:
        actor = ACTOR.get()
        if not actor:
            raise ValueError("This action needs a signed-in caller")
        return actor

    def _need(self, name: str):
        svc = getattr(self.services, name, None) if self.services is not None else None
        if svc is None:
            raise ValueError(f"The {name} service is not available on this server")
        return svc

    # -- profile, quality, glossary, builds, SQL ------------------------------------------------------

    def table_profile(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        prof = self._need("profiles").get(v.id, table)
        if prof is None:
            return {"error": f"{table} has no profile yet; call run_profile to compute one"}
        out = _plain(prof.to_dict())
        for c in out["columns"]:
            c.pop("histogram", None); c["values"] = c.get("values", [])[:8]
        return out

    def run_profile(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        prof = self._need("profiles").run(v.id, table, actor=self._actor())
        return {"table": table, "row_count": prof.row_count, "columns": len(prof.columns), "row_key": prof.row_key, "missing_cells": prof.missing_cells}

    def table_quality(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        st = self._need("tabledq").status(v.id, table)
        return {"table": table, "score": st["score"], "summary": st["summary"], "last_run": st["last_run"],
                "rules": [{"id": r["id"], "name": r["name"], "kind": r["kind"], "column": r["column_name"], "params": r["params"], "threshold": r["threshold"], "enabled": r["enabled"],
                           "pass_rate": (r["last"] or {}).get("pass_rate"), "status": (r["last"] or {}).get("status"), "error": (r["last"] or {}).get("error")} for r in st["rules"]],
                "columns": [c for c in st["columns"] if c["score"] is not None and c["score"] < 0.95]}

    def run_quality_rules(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        run = self._need("tabledq").run(v.id, table, actor=self._actor())
        return {"run": _plain(run.to_dict()), "quality": self.table_quality(domain, table)}

    def add_quality_rule(self, domain: str | None, table: str, name: str, kind: str, column: str | None = None,
                         params: dict | None = None, threshold: float = 0.95) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        rule = self._need("tabledq").add_rule(v.id, table, actor=self._actor(), name=name, kind=kind, column=column, params=params or {}, threshold=threshold)
        return _plain(rule.to_dict())

    def suggest_quality_rules(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        return _plain(self._need("tabledq").auto_suggest(v.id, table, actor=self._actor()))

    def failing_rows(self, rule_id: str, limit: int = 10) -> dict:
        columns, rows = self._need("tabledq").failures(UUID(rule_id), limit)
        return {"columns": columns, "rows": _plain([list(r) for r in rows])}

    def glossary(self, domain: str | None, table: str | None = None, q: str | None = None) -> list[dict]:
        d = self._domain(domain)
        if d is None:
            return [{"error": self._unknown(domain)}]
        return [_plain(e.to_dict()) for e in self._need("glossary").list(d.id, table=table, q=q)]

    def list_builds(self, domain: str | None, limit: int = 5) -> list[dict]:
        d, v = self._working(domain)
        if v is None:
            return [{"error": self._unknown(domain)}]
        return [_plain(r) for r in self.registry.list_builds(v.id)[:limit]]

    def start_build(self, domain: str | None, full: bool = False) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        return _plain(self._need("scheduler").submit(v.id, actor=self._actor(), full=full))

    def preview_sql(self, domain: str | None, sql: str, limit: int = 20) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        columns, rows = self._need("sources").for_version(v.id).query(sql, max(1, min(int(limit), 100)))
        return {"columns": columns, "rows": _plain([list(r) for r in rows])}

    # -- domain resolution ------------------------------------------------------

    def _domain(self, domain: str | None) -> Domain | None:
        name = domain or self.current
        if not name:
            return None
        try:
            d = self.registry.get_domain(name)
        except NotFound:
            return None
        return d if d.mcp_exposed else None

    def _version(self, domain: str | None) -> DomainVersion | None:
        d = self._domain(domain)
        if d is None:
            return None
        return self.registry.served_version(d.id)

    def _disabled(self, tool: str, domain: str | None) -> str | None:
        d = self._domain(domain)
        if d is not None and d.tool_disabled(tool):
            return f"Tool {tool} is disabled for domain {d.name!r} by its MCP policy."
        return None

    def _unknown(self, domain: str | None) -> str:
        name = domain or self.current
        return (f"Unknown domain {name!r}. Call list_domains to see what exists." if name
                else "No domain selected. Call select_domain(domain) first or pass domain explicitly.")

    # -- registry-level tools ---------------------------------------------------

    def select_domain(self, domain: str) -> dict:
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        self.current = domain
        return {"selected": domain, "version": v.version, "status": v.status.value, "triples": self.store.count(v.id)}

    def list_domain_versions(self, domain: str | None = None) -> list[dict]:
        d = self._domain(domain)
        if d is None:
            return [{"error": self._unknown(domain)}]
        out = []
        for v in self.registry.list_versions(d.id):
            build = self.registry.latest_build(v.id)
            out.append({"version": v.version, "status": v.status.value, "has_ontology": bool(v.ontology_ttl),
                        "has_mapping": bool(v.mapping), "built": bool(build and build.status == "succeeded"),
                        "triples": self.store.count(v.id), "updated_at": v.updated_at.isoformat()})
        return out

    def get_design_status(self, domain: str | None = None) -> dict:
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        onto = self._ontology(v)
        mapping = None
        if onto and v.mapping:
            st = mapping_status(onto, MappingSpec.from_dict(v.mapping))
            mapping = {"completion": st.completion, "classes": st.summary["classes"], "complete_classes": st.summary["complete_classes"]}
        build = self.registry.latest_build(v.id)
        drift = len(self.metadata.drift(v.id)) if self.metadata else 0
        return {"domain": domain or self.current, "version": v.version, "status": v.status.value,
                "ontology": onto is not None, "classes": len(onto.classes) if onto else 0, "mapping": mapping,
                "build_ready": bool(onto and v.mapping), "built": bool(build and build.status == "succeeded"),
                "last_build": build.status if build else None, "triples": self.store.count(v.id), "drift_issues": drift}

    def _ontology(self, version: DomainVersion) -> Ontology | None:
        return Ontology.from_turtle(version.ontology_ttl) if version.ontology_ttl else None

    # -- tools ------------------------------------------------------------------

    def list_domains(self) -> list[dict]:
        out = []
        for d in self.registry.list_domains():
            if not d.mcp_exposed:
                continue
            v = self.registry.served_version(d.id)
            published = v if v and v.status is Status.PUBLISHED else None
            out.append({"name": d.name, "description": d.description, "base_iri": d.base_iri,
                        "published_version": published.version if published else None,
                        "version": v.version if v else None, "status": v.status.value if v else None,
                        "triples": self.store.count(v.id) if v else 0})
        return out

    def describe_ontology(self, domain: str | None = None) -> str:
        if msg := self._disabled("describe_ontology", domain):
            return msg
        v = self._version(domain)
        if v is None:
            return self._unknown(domain)
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

    def graph_status(self, domain: str | None = None) -> dict:
        if msg := self._disabled("graph_status", domain):
            return {"error": msg}
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        return {"domain": domain, "version": v.version, "status": v.status.value,
                "triples": self.store.count(v.id), "inferred": self.store.count(v.id, inferred=True),
                "types": dict(self.store.type_inventory(v.id))}

    def list_entity_types(self, domain: str | None = None) -> dict:
        if msg := self._disabled("list_entity_types", domain):
            return {"error": msg}
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        o = self._ontology(v) or Ontology(iri="urn:none")
        return {"total_triples": self.store.count(v.id),
                "types": [{"type": t, "name": o.local_name(t), "instances": n} for t, n in self.store.type_inventory(v.id)],
                "predicates": [{"predicate": p, "name": o.local_name(p), "triples": n} for p, n in self.store.predicate_inventory(v.id)]}

    def compute_virtual_attributes(self, domain: str | None, entity: str) -> dict:
        if msg := self._disabled("compute_virtual_attributes", domain):
            return {"error": msg}
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        if self.attachments is None:
            return {"error": "Attachments are not configured on this server"}
        try:
            return self.attachments.compute_virtual(v.id, entity)
        except Exception as exc:  # noqa: BLE001 - surface to the LLM
            return {"error": str(exc)}

    def invoke_entity_action(self, domain: str | None, entity: str, action: str) -> dict:
        if msg := self._disabled("invoke_entity_action", domain):
            return {"error": msg}
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        if self.attachments is None:
            return {"error": "Attachments are not configured on this server"}
        try:
            return self.attachments.invoke(v.id, entity, action)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def get_entity_context(self, domain: str | None, entity: str, compute_virtual_attributes: bool = False) -> dict:
        if msg := self._disabled("get_entity_context", domain):
            return {"error": msg}
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        detail = self.store.describe(v.id, entity)
        if detail is None:
            hits = self.store.search(v.id, entity, limit=1)
            detail = self.store.describe(v.id, hits[0].iri) if hits else None
        if detail is None:
            return {"error": f"Entity {entity!r} not found in domain {domain or self.current!r}."}
        source = None
        if v.mapping:
            spec = MappingSpec.from_dict(v.mapping)
            cm = next((c for c in spec.classes if c.class_iri in detail.types), None)
            if cm:
                source = {"table": cm.table, "sql_query": cm.sql_query, "key_columns": list(cm.key_columns),
                          "columns": {a.property_iri: a.column for a in cm.attributes}}
        ctx = {"iri": detail.iri, "label": detail.label, "types": list(detail.types), "source": source,
               "degree": {"outgoing": len(detail.outgoing), "incoming": len(detail.incoming)},
               "attributes": {a.predicate: a.value for a in detail.attributes},
               "predicates_out": sorted({r.predicate for r in detail.outgoing}),
               "predicates_in": sorted({r.predicate for r in detail.incoming}),
               "datasets": [], "actions": [], "virtual_attributes": [], "bridges": []}
        if self.attachments is not None:
            ctx["bridges"] = self.attachments.bridges_for(v.id, detail.iri)
            for t in detail.types:
                info = self.attachments.for_class(v.id, t)
                ctx["actions"] += info["actions"]
                ctx["virtual_attributes"] += info["virtual_attributes"]
            try:
                ctx["datasets"] = self.attachments.dataset_rows(v.id, detail.iri, limit=20)
            except Exception:  # noqa: BLE001 - unmapped entity: no datasets
                ctx["datasets"] = []
            if compute_virtual_attributes and ctx["virtual_attributes"]:
                try:
                    ctx["virtual_attributes"] = self.attachments.compute_virtual(v.id, detail.iri)
                except Exception as exc:  # noqa: BLE001
                    ctx["virtual_attributes_error"] = str(exc)
        return ctx

    def search_entities(self, domain: str | None, query: str, entity_type: str | None = None, limit: int = 10) -> list[dict]:
        if msg := self._disabled("search_entities", domain):
            return [{"error": msg}]
        v = self._version(domain)
        if v is None:
            return [{"error": self._unknown(domain)}]
        type_iri = self._resolve_type(v, entity_type) if entity_type else None
        return [asdict(e) for e in self.store.search(v.id, query, type_iri=type_iri, limit=max(1, min(limit, 100)))]

    def describe_entity(self, domain: str | None, entity: str, depth: int = 1) -> str:
        if msg := self._disabled("describe_entity", domain):
            return msg
        v = self._version(domain)
        if v is None:
            return self._unknown(domain)
        detail = self.store.describe(v.id, entity)
        if detail is None:
            hits = self.store.search(v.id, entity, limit=1)
            detail = self.store.describe(v.id, hits[0].iri) if hits else None
        if detail is None:
            return f"Entity {entity!r} not found in domain {domain or self.current!r}."
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
        if self.attachments is not None:
            bridges = self.attachments.bridges_for(v.id, detail.iri)
            if bridges:
                lines.append("Bridges to other domains:")
                lines += [f"  - {b['domain']}: {b['label'] or ln(b['class'])} <{b['iri']}>" + ("" if b["exists"] else " (not found there)")
                          if not b.get("error") else f"  - {b['domain']}: {b['error']}" for b in bridges]
        if depth > 1:
            sub = self.store.neighbourhood(v.id, detail.iri, depth=depth, limit=100)
            lines.append(f"Neighbourhood (depth {depth}): {len(sub.nodes)} entities, {len(sub.edges)} edges")
            lines += [f"  - {ln(e.source)} --{ln(e.predicate)}--> {ln(e.target)}" for e in sub.edges[:60]]
        return "\n".join(lines)

    def get_graphql_schema(self, domain: str | None = None) -> str:
        if msg := self._disabled("get_graphql_schema", domain):
            return msg
        v = self._version(domain)
        if v is None:
            return self._unknown(domain)
        return print_schema(build_schema(self.registry, self.store, v.id))

    def query_graphql(self, domain: str | None, query: str, variables: dict | None = None) -> str:
        if msg := self._disabled("query_graphql", domain):
            return json.dumps({"errors": [{"message": msg}]})
        v = self._version(domain)
        if v is None:
            return json.dumps({"errors": [{"message": self._unknown(domain)}]})
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
