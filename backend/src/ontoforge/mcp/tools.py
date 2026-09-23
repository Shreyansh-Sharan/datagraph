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
from ontoforge.mapping import AttributeBinding, ClassMapping, MappingSpec, MappingSpecError, RelationMapping, mapping_status
from ontoforge.quality import Constraint, ConstraintSet, QualityError
from ontoforge.rules import Rule, RuleSet
from ontoforge.ontology import XSD, DatatypeProperty, ObjectProperty, OntoClass, Ontology
from ontoforge.registry import Domain, DomainVersion, NotFound, Registry, RegistryError, Status
from ontoforge.store import TripleStore


ACTOR: ContextVar[str | None] = ContextVar("ontoforge_mcp_actor", default=None)   # who is calling: set by the API guard and by the assistant
ROLE: ContextVar[str | None] = ContextVar("mcp_role", default=None)   # the caller's role (viewer | builder | reviewer | admin), or None when unknown
_RANK = {"viewer": 0, "builder": 1, "reviewer": 2, "admin": 3}


def _doms(p) -> tuple:
    d = getattr(p, "all_domains", ())
    return tuple(d() if callable(d) else d)


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


_NEXT_BUILD = "start_build to load it into the graph (incremental: only the tables it touches are read)."


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

    def _table(self, version, table: str) -> tuple[str | None, str | None]:
        """The snapshot's spelling of a table named the way people type it: exact, any case, or by
        its short name / a longer dotted form. (name, None) or (None, error naming what exists)."""
        if self.metadata is None:
            return table, None
        names = [s.table for s in self.metadata.list(version.id)]
        want = table.strip().lower()
        exact = [n for n in names if n.lower() == want]
        if exact:
            return exact[0], None
        short = want.split(".")[-1]
        loose = [n for n in names if n.lower().endswith("." + short) or n.lower() == short or want.endswith("." + n.lower())]
        if len(loose) == 1:
            return loose[0], None
        listed = ", ".join(sorted(names)) or "none: import tables on the Metadata screen first"
        hint = f"; several match {short!r}: {', '.join(sorted(loose))}" if len(loose) > 1 else ""
        return None, f"No table {table!r} in the snapshot of {version.version}{hint}. Tables in the snapshot: {listed}"

    def list_tables(self, domain: str | None = None) -> list[dict]:
        d, v = self._working(domain)
        if v is None or self.metadata is None:
            return [{"error": self._unknown(domain)}]
        dq = getattr(self.services, "tabledq", None) if self.services is not None else None
        profiles = getattr(self.services, "profiles", None) if self.services is not None else None
        out = []
        for snap in self.metadata.list(v.id):
            out.append({"table": snap.table, "columns": len(snap.columns), "primary_key": list(snap.primary_key),
                        "profiled": bool(profiles and profiles.get(v.id, snap.table)), "rules": len(dq.list_rules(v.id, snap.table)) if dq else 0})
        return out

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
        table, err = self._table(v, table)
        if err:
            return {"error": err}
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
        table, err = self._table(v, table)
        if err:
            return {"error": err}
        prof = self._need("profiles").run(v.id, table, actor=self._actor())
        return {"table": table, "row_count": prof.row_count, "columns": len(prof.columns), "row_key": prof.row_key, "missing_cells": prof.missing_cells}

    def table_quality(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        table, err = self._table(v, table)
        if err:
            return {"error": err}
        st = self._need("tabledq").status(v.id, table)
        return {"table": table, "score": st["score"], "summary": st["summary"], "last_run": st["last_run"],
                "rules": [{"id": r["id"], "name": r["name"], "kind": r["kind"], "column": r["column_name"], "params": r["params"], "threshold": r["threshold"], "enabled": r["enabled"],
                           "pass_rate": (r["last"] or {}).get("pass_rate"), "status": (r["last"] or {}).get("status"), "error": (r["last"] or {}).get("error")} for r in st["rules"]],
                "columns": [c for c in st["columns"] if c["score"] is not None and c["score"] < 0.95]}

    def quality_rule_kinds(self) -> list[dict]:
        from ontoforge.tabledq import KIND_CATALOG
        return KIND_CATALOG

    def quality_overview(self, domain: str | None) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        ov = self._need("tabledq").overview(v.id)
        return {"tables": _plain(ov["tables"]), "rules": _plain(ov["rules"])}

    def run_quality_rules(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        table, err = self._table(v, table)
        if err:
            return {"error": err}
        run = self._need("tabledq").run(v.id, table, actor=self._actor())
        return {"run": _plain(run.to_dict()), "quality": self.table_quality(domain, table)}

    def add_quality_rule(self, domain: str | None, table: str, name: str, kind: str, column: str | None = None,
                         params: dict | None = None, threshold: float = 0.95) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        table, err = self._table(v, table)
        if err:
            return {"error": err}
        rule = self._need("tabledq").add_rule(v.id, table, actor=self._actor(), name=name, kind=kind, column=column, params=params or {}, threshold=threshold)
        return _plain(rule.to_dict())

    def suggest_quality_rules(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        table, err = self._table(v, table)
        if err:
            return {"error": err}
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

    def list_notifications(self, since: int | None = None, limit: int = 30) -> dict:
        """What happened lately across the domains the caller may see, newest first; running builds and jobs carry their progress."""
        return _plain(self._need("notifier").feed(self._actor(), ROLE.get(), since=since, limit=limit))

    def mark_notifications_read(self, until: int | None = None, ids: list[int] | None = None) -> dict:
        self._need("notifier").mark_read(self._actor(), ids=ids, until=until)
        return {"unread": self._need("notifier").feed(self._actor(), ROLE.get(), limit=1)["unread"]}

    def preview_sql(self, domain: str | None, sql: str, limit: int = 20) -> dict:
        if msg := self._disabled("preview_sql", domain):
            return {"error": msg}
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        columns, rows = self._need("sources").for_version(v.id).query(sql, max(1, min(int(limit), 100)))
        return {"columns": columns, "rows": _plain([list(r) for r in rows])}

    # -- the rest of the backend: glossary, lifecycle, domains, metadata, mapping exclusions, rules, constraints --

    @staticmethod
    def _require(role: str) -> str | None:
        """An error unless the caller's role is known and at least the one this action needs.

        An unknown role is a refusal, not a pass: a transport that never establishes who is
        calling must not be the way every gate is walked through.
        """
        have = ROLE.get()
        if have is None:
            return f"This action needs {role}, and nothing established who is calling"
        if _RANK.get(have, 0) < _RANK[role]:
            return f"{ACTOR.get() or 'the caller'} is {have}; this action needs {role}"
        return None

    def _version_of(self, d: Domain, version: int | None):
        """A version by number, or the working one; (version, error)."""
        if version is None:
            v = self.registry.latest_version(d.id, Status.DRAFT) or self.registry.served_version(d.id)
            return (v, None) if v else (None, f"Domain {d.name!r} has no version yet")
        v = next((x for x in self.registry.list_versions(d.id) if x.version == int(version)), None)
        return (v, None) if v else (None, f"Domain {d.name!r} has no version {version}; list_domain_versions shows them")

    @staticmethod
    def _vsum(v: DomainVersion) -> dict:
        return {"id": str(v.id), "version": v.version, "status": v.status.value, "has_ontology": bool(v.ontology_ttl), "has_mapping": bool(v.mapping)}

    def _dsum(self, d: Domain) -> dict:
        active = next((v.version for v in self.registry.list_versions(d.id) if v.id == d.active_version_id), None) if d.active_version_id else None
        return {"name": d.name, "description": d.description, "base_iri": d.base_iri, "review_quorum": d.review_quorum, "active_version": active,
                "materialization": d.materialization, "target_schema": d.target_schema, "mcp_policy": d.mcp_policy}

    # glossary
    def add_term(self, domain: str | None, kind: str, name: str, definition: str = "", table: str | None = None, columns: list[str] | None = None,
                 class_name: str | None = None, formula: str | None = None, unit: str | None = None, frequency: str | None = None,
                 status: str = "draft", owner: str | None = None) -> dict:
        d, v = self._working(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        if table and v is not None:
            table, err = self._table(v, table)
            if err:
                return {"error": err}
            cols, err = self._columns_of(v, table, list(columns or []))
            if err:
                return {"error": err}
            columns = cols
        try:
            t = self._need("glossary").add(d.id, actor=self._actor(), kind=kind, name=name, definition=definition, table=table, columns=columns,
                                           status=status, owner=owner, class_name=class_name, formula=formula, unit=unit, frequency=frequency)
        except ValueError as exc:
            return {"error": str(exc)}
        return _plain(t.to_dict())

    def update_term(self, term_id: str, name: str | None = None, definition: str | None = None, status: str | None = None, table: str | None = None,
                    columns: list[str] | None = None, class_name: str | None = None, formula: str | None = None, unit: str | None = None,
                    frequency: str | None = None, owner: str | None = None) -> dict:
        changes = {k: val for k, val in dict(name=name, definition=definition, status=status, table=table, columns=columns, class_name=class_name,
                                              formula=formula, unit=unit, frequency=frequency, owner=owner).items() if val is not None}
        try:
            return _plain(self._need("glossary").update(UUID(term_id), actor=self._actor(), **changes).to_dict())
        except (ValueError, NotFound) as exc:
            return {"error": str(exc)}

    def delete_term(self, term_id: str) -> dict:
        try:
            self._need("glossary").delete(UUID(term_id), actor=self._actor())
        except (ValueError, NotFound) as exc:
            return {"error": str(exc)}
        return {"deleted": term_id}

    # lifecycle
    def create_version(self, domain: str | None) -> dict:
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        if err := self._require("builder"):
            return {"error": err}
        try:
            return {**self._vsum(self.registry.create_version(d.id, actor=self._actor())), "next": "The new draft copies the last version's design; edit it, build it, then transition_version to in_review."}
        except RegistryError as exc:
            return {"error": str(exc)}

    def transition_version(self, domain: str | None, to: str, version: int | None = None) -> dict:
        """Move a version along the lifecycle: draft -> in_review (builder), in_review -> draft or published (reviewer; publishing needs the review quorum), published -> archived (admin)."""
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        try:
            target = Status(to)
        except ValueError:
            return {"error": f"to must be one of {', '.join(s.value for s in Status)}"}
        if err := self._require({Status.IN_REVIEW: "builder", Status.DRAFT: "reviewer", Status.PUBLISHED: "reviewer", Status.ARCHIVED: "admin"}[target]):
            return {"error": err}
        v, err = self._version_of(d, version)
        if err:
            return {"error": err}
        try:
            return self._vsum(self.registry.transition(v.id, target, actor=self._actor()))
        except RegistryError as exc:
            return {"error": str(exc)}

    def review_version(self, domain: str | None, approved: bool, comment: str | None = None, version: int | None = None) -> dict:
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        if err := self._require("reviewer"):
            return {"error": err}
        v, err = self._version_of(d, version)
        if err:
            return {"error": err}
        try:
            return _plain(asdict(self.registry.add_review(v.id, reviewer=self._actor(), approved=approved, comment=comment)))
        except RegistryError as exc:
            return {"error": str(exc)}

    def comment_version(self, domain: str | None, body: str, version: int | None = None) -> dict:
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        v, err = self._version_of(d, version)
        if err:
            return {"error": err}
        return _plain(asdict(self.registry.add_comment(v.id, author=self._actor(), body=body)))

    def set_active_version(self, domain: str | None, version: int | None) -> dict:
        """Serve a published version (None serves nothing)."""
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        if err := self._require("reviewer"):
            return {"error": err}
        vid = None
        if version is not None:
            v, err = self._version_of(d, version)
            if err:
                return {"error": err}
            vid = v.id
        try:
            return self._dsum(self.registry.set_active_version(d.id, vid, actor=self._actor()))
        except RegistryError as exc:
            return {"error": str(exc)}

    def delete_version(self, domain: str | None, version: int) -> dict:
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        if err := self._require("builder"):
            return {"error": err}
        v, err = self._version_of(d, version)
        if err:
            return {"error": err}
        try:
            self.registry.delete_version(v.id, actor=self._actor())
        except RegistryError as exc:
            return {"error": str(exc)}
        return {"deleted": v.version}

    # domains
    def create_domain(self, name: str, base_iri: str, description: str | None = None, review_quorum: int = 1) -> dict:
        if err := self._require("builder"):
            return {"error": err}
        try:
            d = self.registry.create_domain(name, description, base_iri=base_iri, review_quorum=review_quorum)
        except (RegistryError, ValueError) as exc:
            return {"error": str(exc)}
        self.registry.create_version(d.id, actor=self._actor())
        return {**self._dsum(d), "next": "import_tables to snapshot its tables, add_class / map_class to design it, then start_build. Its source connection is set in Settings."}

    def update_domain(self, domain: str | None, description: str | None = None, base_iri: str | None = None, review_quorum: int | None = None,
                      materialization: str | None = None, target_schema: str | None = None) -> dict:
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        if err := self._require("builder"):
            return {"error": err}
        changes = {k: val for k, val in dict(description=description, base_iri=base_iri, review_quorum=review_quorum, materialization=materialization,
                                              target_schema=target_schema).items() if val is not None}
        try:
            return self._dsum(self.registry.update_domain(d.id, changes, actor=self._actor()))
        except (RegistryError, ValueError) as exc:
            return {"error": str(exc)}

    def set_mcp_policy(self, domain: str | None, disabled_tools: list[str] | None = None, exposed: bool = True) -> dict:
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        if err := self._require("builder"):
            return {"error": err}
        try:
            pol = self.registry.set_mcp_policy(d.id, {"exposed": exposed, "disabled_tools": list(disabled_tools or [])}).mcp_policy
        except ValueError as exc:
            return {"error": str(exc)}
        return {"exposed": pol.get("exposed", True), "disabled_tools": list(pol.get("disabled_tools", []))}

    def delete_domain(self, domain: str | None) -> dict:
        d = self._domain(domain)
        if d is None:
            return {"error": self._unknown(domain)}
        if err := self._require("admin"):
            return {"error": err}
        self.registry.delete_domain(d.id)
        if self.current == d.name:
            self.current = None
        return {"deleted": d.name}

    # metadata
    def import_tables(self, domain: str | None, tables: list[str], schema: str | None = None) -> list[dict]:
        d, v = self._working(domain)
        if v is None:
            return [{"error": self._unknown(domain)}]
        try:
            snaps = self._meta().import_tables(v.id, list(tables), actor=self._actor(), schema=schema)
        except Exception as exc:  # noqa: BLE001 - the catalog's reason is the answer
            return [{"error": f"{type(exc).__name__}: {exc}"}]
        return [self._snap(sn) for sn in snaps]

    def refresh_metadata(self, domain: str | None) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        try:
            changes = self._meta().refresh(v.id, actor=self._actor())
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        return {"changes": _plain([asdict(c) for c in changes])}

    def set_table_comment(self, domain: str | None, table: str, comment: str | None, column: str | None = None) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        table, err = self._table(v, table)
        if err:
            return {"error": err}
        if column:
            cols, err = self._columns_of(v, table, [column])
            if err:
                return {"error": err}
            column = cols[0]
        try:
            return self._snap(self._meta().set_comment(v.id, table, column, comment, actor=self._actor()))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    def remove_table(self, domain: str | None, table: str) -> dict:
        d, v = self._working(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        table, err = self._table(v, table)
        if err:
            return {"error": err}
        try:
            self._meta().remove(v.id, table, actor=self._actor())
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        return {"removed": table}

    def _meta(self):
        if self.metadata is None:
            raise ValueError("The metadata service is not available on this server")
        return self.metadata

    @staticmethod
    def _snap(sn) -> dict:
        return {"table": sn.table, "comment": sn.comment, "columns": {c["name"]: c.get("comment") for c in sn.columns}, "column_count": len(sn.columns),
                "primary_key": list(sn.primary_key or [])}

    # mapping exclusions
    def exclude_property(self, domain: str | None, cls: str, prop: str, excluded: bool = True) -> dict:
        """Mark a class's attribute or relationship as deliberately unmapped (or take that back)."""
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        ciri = self._class_of(o, cls)
        if not ciri:
            return {"error": self._unknown_class(o, cls)}
        piri = self._property_of(o, prop)
        if not piri:
            return {"error": f"Unknown property {prop!r}; class_schema lists the class's attributes and relationships"}
        spec = MappingSpec.from_dict(v.mapping) if v.mapping else None
        cm = next((c for c in (spec.classes if spec else ()) if c.class_iri == ciri), None)
        if cm is None:
            return {"error": f"{o.local_name(ciri)} is not mapped to a table yet; call map_class first"}
        ex = set(cm.excluded) | {piri} if excluded else set(cm.excluded) - {piri}
        classes = tuple(ClassMapping(c.class_iri, c.table, c.sql_query, c.key_columns, c.iri_template, c.attributes, tuple(sorted(ex))) if c.class_iri == ciri else c for c in spec.classes)
        if (err := self._save(v, mapping=MappingSpec(spec.base_iri, classes, spec.relations))):
            return {"error": err}
        return {"class": ciri, "excluded": sorted(ex)}

    def unmap_class(self, domain: str | None, cls: str) -> dict:
        """Drop a class's mapping and every relation that touches it (the ontology keeps the class)."""
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        ciri = self._class_of(o, cls)
        if not ciri:
            return {"error": self._unknown_class(o, cls)}
        spec = MappingSpec.from_dict(v.mapping) if v.mapping else MappingSpec(base_iri=d.base_iri)
        rels = tuple(r for r in spec.relations if ciri not in (r.source_class, r.target_class))
        new = MappingSpec(spec.base_iri, tuple(c for c in spec.classes if c.class_iri != ciri), rels)
        if (err := self._save(v, mapping=new)):
            return {"error": err}
        return {"unmapped": ciri, "relations_dropped": len(spec.relations) - len(rels), "next": _NEXT_BUILD}

    # reasoning rules and constraints
    def list_rules(self, domain: str | None) -> list[dict]:
        d, v = self._working(domain)
        if v is None:
            return [{"error": self._unknown(domain)}]
        return [{"name": r.name, "text": r.text, "mode": r.mode, "enabled": r.enabled} for r in RuleSet.from_dict(v.rules).rules]

    def add_rule(self, domain: str | None, name: str, text: str, mode: str = "materialize", enabled: bool = True) -> dict:
        """Add or replace a reasoning rule written as SWRL-style text over the ontology's names, e.g.
        'Employee(?e) ^ salary(?e, ?s) ^ swrlb:greaterThan(?s, 1000) -> HighEarner(?e)'. mode: materialize (adds triples at build) | violation (reports matches)."""
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        try:
            rule = Rule.from_text(text, o, name, mode, enabled)
        except Exception as exc:  # noqa: BLE001 - the parser's message is the answer
            return {"error": f"Cannot parse the rule: {exc}"}
        rs = RuleSet([r for r in RuleSet.from_dict(v.rules).rules if r.name != name] + [rule])
        try:
            self.registry.update_content(v.id, actor=self._actor(), rules=rs.to_dict())
        except RegistryError as exc:
            return {"error": str(exc)}
        return {"name": rule.name, "text": rule.text, "mode": rule.mode, "enabled": rule.enabled, "next": "start_build applies materialize rules; violation rules report at build."}

    def remove_rule(self, domain: str | None, name: str) -> dict:
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        rs = RuleSet.from_dict(v.rules)
        if all(r.name != name for r in rs.rules):
            return {"error": f"Unknown rule {name!r}; list_rules names them"}
        try:
            self.registry.update_content(v.id, actor=self._actor(), rules=RuleSet([r for r in rs.rules if r.name != name]).to_dict())
        except RegistryError as exc:
            return {"error": str(exc)}
        return {"removed": name}

    def list_constraints(self, domain: str | None) -> list[dict]:
        d, v = self._working(domain)
        if v is None:
            return [{"error": self._unknown(domain)}]
        return [_plain(c.to_dict()) for c in ConstraintSet.from_dict(v.quality).constraints]

    def add_constraint(self, domain: str | None, name: str, target_class: str, kind: str, property: str | None = None, value=None,
                       severity: str = "violation", message: str | None = None) -> dict:
        """Add or replace a data-quality constraint on the graph (SHACL-like). kind: min_count | max_count | datatype | class | pattern | in |
        min_inclusive | max_inclusive | min_exclusive | max_exclusive | unique | node_kind | require_label | no_orphans. severity: violation | warning | info."""
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        ciri = self._class_of(o, target_class)
        if not ciri:
            return {"error": self._unknown_class(o, target_class)}
        piri = None
        if property is not None:
            piri = self._property_of(o, property)
            if not piri:
                return {"error": f"Unknown property {property!r}; class_schema lists the class's attributes and relationships"}
        try:
            c = Constraint(name, ciri, piri, kind, value, severity, message)
            cs = ConstraintSet([x for x in ConstraintSet.from_dict(v.quality).constraints if x.name != name] + [c])
            self.registry.update_content(v.id, actor=self._actor(), quality=cs.to_dict())
        except (QualityError, RegistryError, ValueError) as exc:
            return {"error": str(exc)}
        return {**_plain(c.to_dict()), "next": "Constraints are checked on the built graph (Data quality screen, validate)."}

    def remove_constraint(self, domain: str | None, name: str) -> dict:
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        cs = ConstraintSet.from_dict(v.quality)
        if all(c.name != name for c in cs.constraints):
            return {"error": f"Unknown constraint {name!r}; list_constraints names them"}
        try:
            self.registry.update_content(v.id, actor=self._actor(), quality=ConstraintSet([c for c in cs.constraints if c.name != name]).to_dict())
        except RegistryError as exc:
            return {"error": str(exc)}
        return {"removed": name}

    # -- design: the assistant changes the working draft, not only reads it ---------------------------

    def add_class(self, domain: str | None, name: str, label: str | None = None, description: str | None = None, parent: str | None = None) -> dict:
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        if self._class_of(o, name):
            return {"error": f"Class {name!r} already exists as {self._class_of(o, name)}"}
        parents: tuple[str, ...] = ()
        if parent:
            piri = self._class_of(o, parent)
            if not piri:
                return {"error": self._unknown_class(o, parent)}
            parents = (piri,)
        c = o.add_class(OntoClass(o.mint(name, capitalize=True), label or name, description, parents))
        if (err := self._save(v, ontology=o)):
            return {"error": err}
        return {"class": c.iri, "label": c.label, "mapped": False,
                "next": "map_class(cls, table, key_columns) to tie it to a table, add_attribute for its columns, add_relationship for its links, then start_build."}

    def add_relationship(self, domain: str | None, name: str, from_cls: str, to_cls: str, label: str | None = None, description: str | None = None,
                         fk_column: str | None = None, fk_on: str = "from", link_table: str | None = None,
                         source_key: list[str] | None = None, target_key: list[str] | None = None) -> dict:
        """A relationship between two classes in the ontology, and, when a key is given, its mapping."""
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        src, tgt = self._class_of(o, from_cls), self._class_of(o, to_cls)
        if not src or not tgt:
            return {"error": self._unknown_class(o, from_cls if not src else to_cls)}
        if (have := self._property_of(o, name)):
            return {"error": f"Relationship {name!r} already exists as {have}, {self._mapped_as(v, o, have)}; map_relationship maps it, remove_relationship removes it"}
        p = ObjectProperty(o.mint(name), label or name, description, domain=src, range=tgt)
        spec = rel = None
        if fk_column or link_table:
            spec, rel, err = self._relation_spec(d, v, o, p, fk_column, fk_on, link_table, source_key, target_key)
            if err:
                return {"error": err}
        o.add_object_property(p)
        if (err := self._save(v, ontology=o, mapping=spec)):
            return {"error": err}
        if rel is None:
            return {"property": p.iri, "from": src, "to": tgt, "mapped": False,
                    "next": "map_relationship(relationship, fk_column, fk_on='from'|'to') or with link_table + source_key + target_key, then start_build."}
        return {"property": p.iri, "from": src, "to": tgt, "mapped": True, "relation": _plain(asdict(rel)), "next": _NEXT_BUILD}

    def map_relationship(self, domain: str | None, relationship: str, fk_column: str | None = None, fk_on: str = "from", link_table: str | None = None,
                         source_key: list[str] | None = None, target_key: list[str] | None = None) -> dict:
        """How the rows carry a relationship: a foreign-key column on the source ('from') or the target ('to') table, or a link table with a key to each side."""
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        iri = self._property_of(o, relationship)
        if not iri or iri not in o.object_properties:
            return {"error": f"Unknown relationship {relationship!r}; class_schema lists a class's relationships"}
        spec, rel, err = self._relation_spec(d, v, o, o.object_properties[iri], fk_column, fk_on, link_table, source_key, target_key)
        if err:
            return {"error": err}
        if (err := self._save(v, mapping=spec)):
            return {"error": err}
        return {"property": iri, "mapped": True, "relation": _plain(asdict(rel)), "next": _NEXT_BUILD}

    def _relation_spec(self, d, v, o: Ontology, p: ObjectProperty, fk_column, fk_on, link_table, source_key, target_key):
        """The mapping spec with the relation for property p, or (None, None, error). Nothing is saved here."""
        iri = p.iri
        src, tgt = (p.all_domains[0] if p.all_domains else None), p.range
        spec = MappingSpec.from_dict(v.mapping) if v.mapping else MappingSpec(base_iri=d.base_iri)
        by_class = {c.class_iri: c for c in spec.classes}
        if src not in by_class or tgt not in by_class:
            missing = o.local_name(src if src not in by_class else tgt)
            return None, None, f"Class {missing} is not mapped to a table yet; call map_class first"
        sm, tm = by_class[src], by_class[tgt]
        if link_table:
            if not source_key or not target_key:
                return None, None, "A link table needs source_key (its columns naming the source row) and target_key (naming the target row)"
            table, err = self._table(v, link_table)
            if err:
                return None, None, err
            cols, err = self._columns_of(v, table, list(source_key) + list(target_key))
            if err:
                return None, None, err
            rel = RelationMapping(iri, src, tgt, table=table, source_key=tuple(cols[:len(source_key)]), target_key=tuple(cols[len(source_key):]))
        elif fk_column:
            if fk_on not in ("from", "to"):
                return None, None, "fk_on is 'from' (the column sits on the source class's table) or 'to' (on the target class's table)"
            table = tm.table if fk_on == "to" else sm.table
            if not table:
                return None, None, f"{o.local_name(tgt if fk_on == 'to' else src)} is mapped to a query, not a table; use link_table"
            cols, err = self._columns_of(v, table, [fk_column])
            if err:
                return None, None, err
            rel = (RelationMapping(iri, src, tgt, table=table, source_key=(cols[0],), target_key=tm.key_columns) if fk_on == "to"
                   else RelationMapping(iri, src, tgt, target_key=(cols[0],)))
        else:
            return None, None, "Give fk_column (with fk_on 'from' or 'to') or link_table with source_key and target_key"
        rels = tuple(r for r in spec.relations if not (r.property_iri == iri and r.source_class == src)) + (rel,)
        spec = MappingSpec(spec.base_iri, spec.classes, rels)
        try:
            spec.to_r2rml()
        except MappingSpecError as exc:
            return None, None, str(exc)
        return spec, rel, None

    def add_attribute(self, domain: str | None, cls: str, name: str, column: str | None = None, datatype: str | None = None,
                      label: str | None = None, description: str | None = None) -> dict:
        """An attribute of a class in the ontology and, when a column is given, its binding in the mapping. datatype: string, integer, decimal, double, boolean, date, dateTime."""
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        ciri = self._class_of(o, cls)
        if not ciri:
            return {"error": self._unknown_class(o, cls)}
        rng = XSD + (datatype or "string").replace(XSD, "")
        iri = self._property_of(o, name)
        if iri and iri in o.object_properties:
            return {"error": f"{name!r} is a relationship, not an attribute"}
        if not iri:
            iri = o.add_datatype_property(DatatypeProperty(o.mint(name), label or name, description, domain=ciri, range=rng)).iri
            if (err := self._save(v, ontology=o)):
                return {"error": err}
        out = {"property": iri, "class": ciri, "column": None, "next": "add_attribute again with column to bind it, then start_build."}
        if column:
            spec = MappingSpec.from_dict(v.mapping) if v.mapping else None
            cm = next((c for c in (spec.classes if spec else ()) if c.class_iri == ciri), None)
            if cm is None:
                return {**out, "mapping_error": f"{o.local_name(ciri)} is not mapped to a table yet; call map_class first"}
            cols, err = self._columns_of(v, cm.table, [column]) if cm.table else ([column], None)
            if err:
                return {**out, "mapping_error": err}
            attrs = tuple(a for a in cm.attributes if a.property_iri != iri) + (AttributeBinding(iri, cols[0], datatype=rng),)
            classes = tuple(ClassMapping(c.class_iri, c.table, c.sql_query, c.key_columns, c.iri_template, attrs, c.excluded) if c.class_iri == ciri else c for c in spec.classes)
            if (err := self._save(v, mapping=MappingSpec(spec.base_iri, classes, spec.relations))):
                return {"error": err}
            out.update(column=cols[0], next="start_build to load it into the graph.")
        return out

    def map_class(self, domain: str | None, cls: str, table: str, key_columns: list[str]) -> dict:
        """Tie a class to a table: each row is one instance, identified by the key columns."""
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        ciri = self._class_of(o, cls)
        if not ciri:
            return {"error": self._unknown_class(o, cls)}
        table, err = self._table(v, table)
        if err:
            return {"error": err}
        cols, err = self._columns_of(v, table, list(key_columns or []))
        if err or not cols:
            return {"error": err or "key_columns must name at least one column"}
        spec = MappingSpec.from_dict(v.mapping) if v.mapping else MappingSpec(base_iri=d.base_iri)
        old = next((c for c in spec.classes if c.class_iri == ciri), None)
        cm = ClassMapping(ciri, table=table, key_columns=tuple(cols), attributes=old.attributes if old and old.table == table else (), excluded=old.excluded if old else ())
        spec = MappingSpec(spec.base_iri, tuple(c for c in spec.classes if c.class_iri != ciri) + (cm,), spec.relations)
        try:
            spec.to_r2rml()
        except MappingSpecError as exc:
            return {"error": str(exc)}
        if (err := self._save(v, mapping=spec)):
            return {"error": err}
        return {"class": ciri, "table": table, "key_columns": list(cols), "next": "add_attribute(cls, name, column) for its columns, add_relationship for its links, then start_build."}

    def remove_relationship(self, domain: str | None, relationship: str) -> dict:
        d, v, o, err = self._draft(domain)
        if err:
            return {"error": err}
        iri = self._property_of(o, relationship)
        if not iri or iri not in o.object_properties:
            return {"error": f"Unknown relationship {relationship!r}"}
        del o.object_properties[iri]
        spec = MappingSpec.from_dict(v.mapping) if v.mapping else None
        unmapped = bool(spec and any(r.property_iri == iri for r in spec.relations))
        if unmapped:
            spec = MappingSpec(spec.base_iri, spec.classes, tuple(r for r in spec.relations if r.property_iri != iri))
        if (err := self._save(v, ontology=o, mapping=spec if unmapped else None)):
            return {"error": err}
        return {"removed": iri, "unmapped": unmapped, "next": "start_build to drop its triples from the graph."}

    @staticmethod
    def _mapped_as(v: DomainVersion, o: Ontology, iri: str) -> str:
        spec = MappingSpec.from_dict(v.mapping) if v.mapping else None
        rel = next((r for r in (spec.relations if spec else ()) if r.property_iri == iri), None)
        if rel is None:
            return "not mapped"
        if rel.table:
            return f"mapped on table {rel.table} (source key {', '.join(rel.source_key or ())}; target key {', '.join(rel.target_key or ())})"
        return f"mapped by foreign key {', '.join(rel.target_key or ())} on the source class's table"

    def _draft(self, domain: str | None):
        """The working draft, its ontology (a new one for an empty domain) — or an error."""
        d, v = self._working(domain)
        if v is None:
            return None, None, None, self._unknown(domain)
        if v.status != Status.DRAFT:
            return d, v, None, f"Version {v.version} of {d.name!r} is {v.status.value}, not a draft; create a new version to change the design"
        o = self._ontology(v) or Ontology(iri=f"{d.base_iri.rstrip('/')}/ontology", label=d.name)
        return d, v, o, None

    def _save(self, v: DomainVersion, ontology: Ontology | None = None, mapping: MappingSpec | None = None) -> str | None:
        try:
            self.registry.update_content(v.id, actor=self._actor(), ontology_ttl=ontology.to_turtle() if ontology else None,
                                         mapping=mapping.to_dict() if mapping else None)
        except (RegistryError, ValueError) as exc:
            return str(exc)
        return None

    @staticmethod
    def _class_of(o: Ontology, name: str) -> str | None:
        for iri, c in o.classes.items():
            if iri == name or o.local_name(iri).lower() == name.strip().lower() or (c.label or "").lower() == name.strip().lower():
                return iri
        return None

    def _property_of(self, o: Ontology, name: str) -> str | None:
        return self._resolve_property(o, name.strip())

    def _columns_of(self, v: DomainVersion, table: str, wanted: list[str]) -> tuple[list[str], str | None]:
        """The snapshot's spelling of the wanted columns, or an error naming what the table has; unchecked without a snapshot."""
        if self.metadata is None:
            return list(wanted), None
        try:
            have = [c["name"] for c in self.metadata.get(v.id, table).columns]
        except Exception:   # noqa: BLE001 - no snapshot: trust the caller, the build will tell
            return list(wanted), None
        by_lower = {c.lower(): c for c in have}
        out = []
        for w in wanted:
            if w.lower() not in by_lower:
                return [], f"{w!r} is not a column of {table}; it has {', '.join(have[:40])}"
            out.append(by_lower[w.lower()])
        return out, None

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
        from ontoforge.metadata import drift_from_last_build
        checked = drift_from_last_build(self.registry, v.id)   # what the last build found; a live check is a build's or check_drift's job
        drift = len(checked["issues"]) if checked["checked"] else None   # None: nothing has looked yet
        return {"domain": domain or self.current, "version": v.version, "status": v.status.value,
                "ontology": onto is not None, "classes": len(onto.classes) if onto else 0, "mapping": mapping,
                "build_ready": bool(onto and v.mapping), "built": bool(build and build.status == "succeeded"),
                "last_build": build.status if build else None, "triples": self.store.count(v.id), "drift_issues": drift, "drift_checked": checked["checked"]}

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

    @staticmethod
    def _unknown_class(o: Ontology | None, cls: str) -> str:
        """The error for a class that is not in the ontology, naming the classes it most resembles."""
        import difflib
        names = {o.local_name(iri): iri for iri in (o.classes if o else {})}
        names.update({c.label: iri for iri, c in (o.classes.items() if o else []) if c.label})
        q = cls.rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower()
        close = [n for n in names if q and (q in n.lower() or n.lower() in q)] or difflib.get_close_matches(cls, list(names), n=4, cutoff=0.5)
        hint = f"; did you mean {', '.join(dict.fromkeys(close[:4]))}?" if close else "; call describe_ontology or list_entity_types"
        return f"Unknown class {cls!r}{hint}"

    def _resolve_property(self, o: Ontology, name: str) -> str | None:
        for iri, p in list(o.object_properties.items()) + list(o.datatype_properties.items()):
            if iri == name or o.local_name(iri).lower() == name.lower() or (p.label or "").lower() == name.lower():
                return iri
        return None

    def class_schema(self, domain: str | None, cls: str) -> dict:
        """What a class holds and how it connects: its attributes, its outgoing and incoming relationships."""
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        o = self._ontology(v)
        iri = self._resolve_type(v, cls)
        if o is None or iri not in o.classes:
            return {"error": self._unknown_class(o, cls)}
        family = {iri, *o.ancestors(iri)}
        attrs = [{"iri": p.iri, "label": p.label or o.local_name(p.iri), "range": o.local_name(p.range) if p.range else None}
                 for p in o.datatype_properties.values() if set(_doms(p)) & family]
        out = [{"iri": p.iri, "label": p.label or o.local_name(p.iri), "target": p.range} for p in o.object_properties.values() if set(_doms(p)) & family]
        inc = [{"iri": p.iri, "label": p.label or o.local_name(p.iri), "source": _doms(p)[0] if _doms(p) else None}
               for p in o.object_properties.values() if p.range in family]
        c = o.classes[iri]
        return {"class": iri, "label": c.label or o.local_name(iri), "description": c.description, "parents": list(c.parents), "attributes": attrs, "outgoing": out, "incoming": inc,
                "hint": "graph_aggregate(class, measure=<attribute>, group_by=<relationship or attribute>) counts and sums; filters walk relationships, '^' walks one backwards."}

    def ontology_paths(self, domain: str | None, from_cls: str, to_cls: str, max_depth: int = 6) -> dict:
        """Ways from one class to another through the relationships, shortest first, up to five."""
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        o = self._ontology(v)
        a, b = self._resolve_type(v, from_cls), self._resolve_type(v, to_cls)
        if o is None or a not in o.classes or b not in o.classes:
            return {"error": self._unknown_class(o, from_cls if a not in (o.classes if o else {}) else to_cls)}
        edges: dict[str, list[tuple[str, str, str]]] = {}
        for p in o.object_properties.values():
            for d in _doms(p):
                if p.range:
                    edges.setdefault(d, []).append((p.iri, "forward", p.range))
                    edges.setdefault(p.range, []).append((p.iri, "inverse", d))
        found, frontier = [], [(a, [])]
        seen = {a}
        depth = max(1, min(int(max_depth), 8))
        for _ in range(depth):
            nxt = []
            for node, path in frontier:
                for prop, direction, target in edges.get(node, []):
                    step = {"from": node, "property": prop, "direction": direction, "to": target}
                    if target == b:
                        found.append({"steps": path + [step]})
                    elif target not in seen:
                        seen.add(target); nxt.append((target, path + [step]))
            frontier = nxt
            if len(found) >= 5 or not frontier:
                break
        out = {"from": a, "to": b, "paths": found[:5], "hint": "In graph_aggregate filters and group_by, write a forward step as the property IRI and an inverse step as '^' + IRI."}
        if not found:
            out["note"] = f"No path within {depth} steps: the ontology lacks a relationship along the way (add_relationship adds one the tables carry)."
        return out

    def graph_aggregate(self, domain: str | None, cls: str, measure: str | None = None, group_by: "str | list[str] | None" = None,
                        group_kind: str = "value", filters: list[dict] | None = None, limit: int = 50) -> dict:
        v = self._version(domain)
        if v is None:
            return {"error": self._unknown(domain)}
        o = self._ontology(v)
        iri = self._resolve_type(v, cls)
        if o is not None and iri not in o.classes:
            return {"error": self._unknown_class(o, cls)}
        res = lambda name: (self._resolve_property(o, name) if o is not None else None) or name

        def steps(x):
            if not x:
                return None
            xs = [x] if isinstance(x, str) else list(x)
            return [("^" + res(st[1:])) if st.startswith("^") else res(st) for st in xs]
        m = res(measure) if measure else None
        gpath = steps(group_by) or []
        for st in gpath[:-1]:   # every step but the last must be a relationship: a literal has nothing behind it
            if o is not None and st.lstrip("^") in o.datatype_properties:
                return {"error": f"group_by is a path of steps, not a list of dimensions: {o.local_name(st.lstrip('^'))!r} is an attribute, so nothing follows it. "
                                 "Group by one dimension per call (group_by='<date attribute>' with group_kind='year', or group_by='<relationship>'); to combine two, filter on one and group by the other."}
        fl = [{"path": steps(f.get("path") or ([f["predicate"]] if f.get("predicate") else [])), "value": f.get("value")} for f in (filters or []) if f.get("value") is not None]
        if o is not None:   # every step must be a property of the ontology; a guessed one would silently match nothing
            known = set(o.object_properties) | set(o.datatype_properties)
            for st in ([m] if m else []) + gpath + [st for f in fl for st in (f["path"] or [])]:
                if st.lstrip("^") not in known:
                    import difflib
                    want = o.local_name(st.lstrip("^")).lower()
                    names = {o.local_name(i): i for i in known}
                    close = [n for n in names if want and (want in n.lower() or n.lower() in want)] or difflib.get_close_matches(o.local_name(st.lstrip("^")), list(names), n=4, cutoff=0.5)
                    hint = f" Did you mean {', '.join(dict.fromkeys(close[:4]))}?" if close else ""
                    return {"error": f"{o.local_name(st.lstrip('^'))!r} is not a property of the ontology, so the graph holds nothing behind it.{hint} "
                                     "class_schema lists a class's attributes and relationships; use the steps ontology_paths returns, and when it returns no path the relationship is missing: add_relationship adds it."}
        resolved: dict[str, str] = {}
        for f in fl:   # a plain value at a relationship's end names an entity: find it by label or key in the range class
            last = (f["path"] or [None])[-1]
            val = str(f["value"])
            if o is None or not last or last.startswith("^") or last not in o.object_properties or val.startswith(("http://", "https://", "urn:")):
                continue
            rng = o.object_properties[last].range
            hits = self.store.search(v.id, val, type_iri=rng, limit=8)
            exact = [e for e in hits if e.label.lower() == val.lower() or o.local_name(e.iri).lower() == val.lower()]
            pick = exact[0] if exact else (hits[0] if len(hits) == 1 else None)
            if pick is None:
                near = ", ".join(f"{e.label} ({o.local_name(e.iri)})" for e in hits[:5]) or ", ".join(f"{e.label} ({o.local_name(e.iri)})" for e in self.store.search(v.id, "", type_iri=rng, limit=5))
                return {"error": f"No {o.local_name(rng) if rng else 'entity'} named {val!r} at the end of the filter path; the graph has: {near}. "
                                 "Use one of those labels, or end the path with an attribute (e.g. its name) and give the value it holds."}
            resolved[val] = pick.iri
            f["value"] = pick.iri
        rows = self.store.aggregate(v.id, iri, measure=m, group_by=steps(group_by), group_kind=group_kind, filters=fl, limit=limit)
        return {"class": iri, "measure": m, "group_by": steps(group_by), "group_kind": group_kind, "rows": rows, "resolved": resolved,
                "note": "sum/avg/min/max are over the measure where present; count is instances. Check the source table's date coverage before reading a last-period drop as a decline."}

    def _resolve_type(self, v: DomainVersion, name: str) -> str | None:
        o = self._ontology(v)
        if o is None:
            return name
        for iri in o.classes:
            if iri == name or o.local_name(iri).lower() == name.lower():
                return iri
        return name
