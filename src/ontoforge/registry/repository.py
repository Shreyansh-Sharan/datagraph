"""Postgres-backed registry. Every mutating call is one transaction and writes an audit entry."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ontoforge.constants import MCP_REGISTRY_TOOLS, MCP_TOOLS
from ontoforge.db import Database

from .models import (
    DOMAIN_SETTINGS, MATERIALIZATIONS, TRANSITIONS, AnalyticsRun, AuditEntry, Comment, Lock, Task, BuildRun, Domain, DomainVersion, LifecycleError, LockedError, NotFound, Review, Status,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Registry:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- domains -------------------------------------------------------------

    def create_domain(self, name: str, description: str | None = None, *, base_iri: str,
                      review_quorum: int = 1) -> Domain:
        with self._cur() as cur:
            try:
                row = cur.execute(
                    "INSERT INTO domains (name, description, base_iri, review_quorum) VALUES (%s, %s, %s, %s) RETURNING *",
                    (name, description, base_iri, review_quorum)).fetchone()
            except psycopg.errors.UniqueViolation:
                raise LifecycleError(f"Domain {name!r} already exists") from None
            return Domain(**row)

    def get_domain(self, name: str) -> Domain:
        with self._cur() as cur:
            row = cur.execute("SELECT * FROM domains WHERE name = %s", (name,)).fetchone()
        if row is None:
            raise NotFound(f"Domain {name!r}")
        return Domain(**row)

    def get_domain_by_id(self, domain_id: UUID) -> Domain:
        with self._cur() as cur:
            row = cur.execute("SELECT * FROM domains WHERE id = %s", (domain_id,)).fetchone()
        if row is None:
            raise NotFound(f"Domain {domain_id}")
        return Domain(**row)

    def list_domains(self) -> list[Domain]:
        with self._cur() as cur:
            return [Domain(**r) for r in cur.execute("SELECT * FROM domains ORDER BY name")]

    def set_mcp_policy(self, domain_id: UUID, policy: dict) -> Domain:
        disabled = list(policy.get("disabled_tools", []))
        bad = [t for t in disabled if t not in MCP_TOOLS or t in MCP_REGISTRY_TOOLS]
        if bad:
            raise ValueError(f"Cannot disable tool(s) {', '.join(bad)}; domain-scoped tools are "
                             f"{', '.join(t for t in MCP_TOOLS if t not in MCP_REGISTRY_TOOLS)}")
        clean = {"exposed": bool(policy.get("exposed", True))}
        if disabled:
            clean["disabled_tools"] = sorted(set(disabled))
        with self._cur() as cur:
            row = cur.execute("UPDATE domains SET mcp_policy = %s WHERE id = %s RETURNING *", (Jsonb(clean), domain_id)).fetchone()
            if row is None:
                raise NotFound(f"Domain {domain_id}")
            self._audit(cur, None, None, "mcp_policy.updated", {"domain": str(domain_id), **clean})
            return Domain(**row)

    def set_active_version(self, domain_id: UUID, version_id: UUID | None, *, actor: str | None = None) -> Domain:
        with self._cur() as cur:
            if version_id is not None:
                row = self._lock_version(cur, version_id, lock=False)
                if row["domain_id"] != domain_id:
                    raise LifecycleError("Version belongs to another domain")
                if row["status"] != Status.PUBLISHED.value:
                    raise LifecycleError("Only published versions can be set active")
            d = cur.execute("UPDATE domains SET active_version_id = %s WHERE id = %s RETURNING *", (version_id, domain_id)).fetchone()
            if d is None:
                raise NotFound(f"Domain {domain_id}")
            self._audit(cur, version_id, actor, "version.activated" if version_id else "version.deactivated", {"domain": str(domain_id)})
            return Domain(**d)

    def served_version(self, domain_id: UUID) -> DomainVersion | None:
        """What API/MCP serve: the pinned active version, else latest published, else latest of any status."""
        d = self.get_domain_by_id(domain_id)
        if d.active_version_id:
            v = self.get_version(d.active_version_id)
            if v.status is Status.PUBLISHED:
                return v
        return self.latest_version(domain_id, status=Status.PUBLISHED) or self.latest_version(domain_id)

    def delete_domain(self, domain_id: UUID) -> None:
        with self._cur() as cur:
            cur.execute("DELETE FROM domains WHERE id = %s", (domain_id,))

    def update_domain(self, domain_id: UUID, changes: dict, *, actor: str | None = None) -> Domain:
        """Settings behind the Configure screen; unknown keys are rejected, None clears a nullable column."""
        bad = [k for k in changes if k not in DOMAIN_SETTINGS]
        if bad:
            raise ValueError(f"Unknown domain setting(s): {', '.join(bad)}")
        if "materialization" in changes and changes["materialization"] not in MATERIALIZATIONS:
            raise ValueError(f"materialization must be one of {', '.join(MATERIALIZATIONS)}")
        if "review_quorum" in changes and (changes["review_quorum"] is None or int(changes["review_quorum"]) < 0):
            raise ValueError("review_quorum must be 0 or more")
        if not changes:
            return self.get_domain_by_id(domain_id)
        cols = ", ".join(f"{k} = %s" for k in changes)
        with self._cur() as cur:
            row = cur.execute(f"UPDATE domains SET {cols} WHERE id = %s RETURNING *", (*changes.values(), domain_id)).fetchone()
            if row is None:
                raise NotFound(f"Domain {domain_id}")
            self._audit(cur, None, actor, "domain.updated", {"domain": str(domain_id), "fields": sorted(changes)})
            return Domain(**row)

    # -- connections (owned by the connection module; only the references live here) ----

    def detach_connection(self, connection_id: UUID) -> None:
        """Clear every domain reference to a connection (used when a hub connection is deleted)."""
        with self._cur() as cur:
            self._detach(cur, connection_id)

    @staticmethod
    def _detach(cur, connection_id: UUID) -> None:
        cur.execute("UPDATE domains SET connection_id = NULL WHERE connection_id = %s", (connection_id,))
        cur.execute("UPDATE domains SET ai_connection_id = NULL WHERE ai_connection_id = %s", (connection_id,))

    # -- versions ------------------------------------------------------------

    def create_version(self, domain_id: UUID, *, actor: str) -> DomainVersion:
        with self._cur() as cur:
            cur.execute("SELECT id FROM domains WHERE id = %s FOR UPDATE", (domain_id,))
            if cur.fetchone() is None:
                raise NotFound(f"Domain {domain_id}")
            latest = cur.execute(
                "SELECT * FROM domain_versions WHERE domain_id = %s ORDER BY version DESC LIMIT 1", (domain_id,)).fetchone()
            if latest and latest["status"] == Status.DRAFT.value:
                raise LifecycleError("A draft already exists for this domain")
            src = latest or {}
            row = cur.execute(
                "INSERT INTO domain_versions (domain_id, version, status, ontology_ttl, mapping, r2rml_ttl, rules, quality, attachments) "
                "VALUES (%s, %s, 'draft', %s, %s, %s, %s, %s, %s) RETURNING *",
                (domain_id, (latest["version"] + 1) if latest else 1, src.get("ontology_ttl"),
                 Jsonb(src["mapping"]) if src.get("mapping") is not None else None, src.get("r2rml_ttl"),
                 Jsonb(src["rules"]) if src.get("rules") is not None else None,
                 Jsonb(src["quality"]) if src.get("quality") is not None else None,
                 Jsonb(src["attachments"]) if src.get("attachments") is not None else None)).fetchone()
            self._audit(cur, row["id"], actor, "version.created", {"version": row["version"]})
            return _version(row)

    def import_version(self, domain_id: UUID, content: dict, status: Status, *, actor: str) -> DomainVersion:
        """Append a version with the given content and status (bundle import; bypasses review)."""
        with self._cur() as cur:
            cur.execute("SELECT id FROM domains WHERE id = %s FOR UPDATE", (domain_id,))
            if cur.fetchone() is None:
                raise NotFound(f"Domain {domain_id}")
            latest = cur.execute("SELECT version, status FROM domain_versions WHERE domain_id = %s ORDER BY version DESC LIMIT 1",
                                 (domain_id,)).fetchone()
            if status is Status.DRAFT and latest and latest["status"] == Status.DRAFT.value:
                raise LifecycleError("A draft already exists for this domain")
            json_cols = {"mapping", "rules", "quality", "attachments"}
            row = cur.execute(
                "INSERT INTO domain_versions (domain_id, version, status, ontology_ttl, mapping, r2rml_ttl, rules, quality, attachments) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (domain_id, (latest["version"] + 1) if latest else 1, status.value,
                 *[(Jsonb(content.get(k)) if k in json_cols and content.get(k) is not None else content.get(k))
                   for k in ("ontology_ttl", "mapping", "r2rml_ttl", "rules", "quality", "attachments")])).fetchone()
            self._audit(cur, row["id"], actor, "version.imported", {"version": row["version"], "status": status.value})
            return _version(row)

    def get_version(self, version_id: UUID) -> DomainVersion:
        with self._cur() as cur:
            return _version(self._lock_version(cur, version_id, lock=False))

    def list_versions(self, domain_id: UUID) -> list[DomainVersion]:
        with self._cur() as cur:
            return [_version(r) for r in cur.execute(
                "SELECT * FROM domain_versions WHERE domain_id = %s ORDER BY version DESC", (domain_id,))]

    def latest_version(self, domain_id: UUID, status: Status | None = None) -> DomainVersion | None:
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM domain_versions WHERE domain_id = %s AND (%s::text IS NULL OR status = %s) "
                "ORDER BY version DESC LIMIT 1",
                (domain_id, status.value if status else None, status.value if status else None)).fetchone()
        return _version(row) if row else None

    def update_content(self, version_id: UUID, *, actor: str, ontology_ttl: str | None = None,
                       mapping: dict | None = None, r2rml_ttl: str | None = None, rules: dict | None = None,
                       quality: dict | None = None, attachments: dict | None = None) -> DomainVersion:
        with self._cur() as cur:
            row = self._lock_version(cur, version_id)
            if row["status"] != Status.DRAFT.value:
                raise LifecycleError("Only draft versions can be edited")
            self._check_lease(row, actor)
            sets, params, changed = [], [], []
            for col, val in (("ontology_ttl", ontology_ttl), ("mapping", mapping), ("r2rml_ttl", r2rml_ttl), ("rules", rules),
                             ("quality", quality), ("attachments", attachments)):
                if val is not None:
                    sets.append(f"{col} = %s")
                    params.append(Jsonb(val) if col in ("mapping", "rules", "quality", "attachments") else val)
                    changed.append(col)
            if not sets:
                return _version(row)
            row = cur.execute(
                f"UPDATE domain_versions SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING *",
                (*params, version_id)).fetchone()
            self._audit(cur, version_id, actor, "content.updated", {"fields": changed})
            return _version(row)

    def assert_editable(self, version_id: UUID, actor: str) -> DomainVersion:
        """Raise unless the version is a draft the actor may edit (status + lease rules)."""
        with self._cur() as cur:
            row = self._lock_version(cur, version_id, lock=False)
            if row["status"] != Status.DRAFT.value:
                raise LifecycleError("Only draft versions can be edited")
            self._check_lease(row, actor)
            return _version(row)

    def store_r2rml(self, version_id: UUID, r2rml_ttl: str) -> None:
        """Persist the compiled R2RML (derived data; allowed in any status, not an edit)."""
        with self._cur() as cur:
            self._lock_version(cur, version_id)
            cur.execute("UPDATE domain_versions SET r2rml_ttl = %s WHERE id = %s", (r2rml_ttl, version_id))

    # -- lease ---------------------------------------------------------------

    def acquire_lease(self, version_id: UUID, *, editor: str, ttl: timedelta, force: bool = False) -> DomainVersion:
        with self._cur() as cur:
            row = self._lock_version(cur, version_id)
            holder, expires = row["editor"], row["lease_expires_at"]
            if holder and holder != editor and not force and expires and expires > _now():
                raise LockedError(f"Version is being edited by {holder} until {expires.isoformat()}")
            row = cur.execute(
                "UPDATE domain_versions SET editor = %s, lease_expires_at = %s WHERE id = %s RETURNING *",
                (editor, _now() + ttl, version_id)).fetchone()
            self._audit(cur, version_id, editor, "lease.acquired", {"forced": force, "previous": holder})
            return _version(row)

    def release_lease(self, version_id: UUID, *, editor: str) -> None:
        with self._cur() as cur:
            row = self._lock_version(cur, version_id)
            if row["editor"] not in (None, editor):
                raise LockedError(f"Lease is held by {row['editor']}")
            cur.execute("UPDATE domain_versions SET editor = NULL, lease_expires_at = NULL WHERE id = %s", (version_id,))
            self._audit(cur, version_id, editor, "lease.released", None)

    # -- lifecycle -----------------------------------------------------------

    def transition(self, version_id: UUID, to: Status, *, actor: str) -> DomainVersion:
        with self._cur() as cur:
            row = self._lock_version(cur, version_id)
            current = Status(row["status"])
            if to not in TRANSITIONS[current]:
                raise LifecycleError(f"Cannot move from {current.value} to {to.value}")
            if to is Status.PUBLISHED:
                self._check_quorum(cur, row)
            if to is Status.DRAFT and current is Status.IN_REVIEW:
                # Draft uniqueness: cannot reopen if another draft appeared meanwhile.
                other = cur.execute("SELECT 1 FROM domain_versions WHERE domain_id = %s AND status = 'draft' AND id <> %s",
                                    (row["domain_id"], version_id)).fetchone()
                if other:
                    raise LifecycleError("Another draft exists for this domain")
            row = cur.execute("UPDATE domain_versions SET status = %s, updated_at = now() WHERE id = %s RETURNING *",
                              (to.value, version_id)).fetchone()
            if to is Status.ARCHIVED:
                cur.execute("UPDATE domains SET active_version_id = NULL WHERE id = %s AND active_version_id = %s",
                            (row["domain_id"], version_id))
            self._audit(cur, version_id, actor, f"status.{to.value}", {"from": current.value})
            return _version(row)

    def add_review(self, version_id: UUID, *, reviewer: str, approved: bool, comment: str | None = None) -> Review:
        with self._cur() as cur:
            row = self._lock_version(cur, version_id)
            if row["status"] != Status.IN_REVIEW.value:
                raise LifecycleError("Reviews can only be added while a version is in review")
            rnd = self._review_round(cur, version_id)
            rev = cur.execute(
                "INSERT INTO reviews (domain_version_id, reviewer, approved, comment, review_round) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING *", (version_id, reviewer, approved, comment, rnd)).fetchone()
            self._audit(cur, version_id, reviewer, "review.added", {"approved": approved})
            return Review(**rev)

    def review_state(self, version_id: UUID) -> tuple[int, list[Review]]:
        """The current review round and the reviews cast in it (earlier rounds no longer count)."""
        with self._cur() as cur:
            rnd = self._review_round(cur, version_id)
            rows = cur.execute("SELECT * FROM reviews WHERE domain_version_id = %s AND review_round = %s ORDER BY id",
                               (version_id, rnd))
            return rnd, [Review(**r) for r in rows]

    def version_creators(self, domain_id: UUID) -> dict[UUID, str | None]:
        """version id -> who created (or imported) it, from the audit log."""
        with self._cur() as cur:
            rows = cur.execute(
                "SELECT a.domain_version_id, a.actor FROM audit_log a JOIN domain_versions v ON v.id = a.domain_version_id "
                "WHERE v.domain_id = %s AND a.action IN ('version.created', 'version.imported')", (domain_id,))
            return {r["domain_version_id"]: r["actor"] for r in rows}

    def delete_version(self, version_id: UUID, *, actor: str) -> None:
        """Drop a draft that never went anywhere; respects another editor's live lease. Everything hanging off it cascades."""
        with self._cur() as cur:
            row = self._lock_version(cur, version_id)
            if row["status"] != Status.DRAFT.value:
                raise LifecycleError("Only draft versions can be deleted")
            self._check_lease(row, actor)
            cur.execute("DELETE FROM domain_versions WHERE id = %s", (version_id,))
            self._audit(cur, None, actor, "version.deleted", {"domain": str(row["domain_id"]), "version": row["version"]})

    def list_reviews(self, version_id: UUID) -> list[Review]:
        with self._cur() as cur:
            return [Review(**r) for r in cur.execute(
                "SELECT * FROM reviews WHERE domain_version_id = %s ORDER BY id", (version_id,))]

    # -- builds --------------------------------------------------------------

    def start_build(self, version_id: UUID, *, actor: str | None = None) -> BuildRun:
        with self._cur() as cur:
            self._lock_version(cur, version_id, lock=False)
            row = cur.execute("INSERT INTO build_runs (domain_version_id, status, actor) VALUES (%s, 'running', %s) RETURNING *",
                              (version_id, actor)).fetchone()
            self._audit(cur, version_id, actor, "build.started", {"run": str(row["id"])})
            return BuildRun(**row)

    def finish_build(self, run_id: UUID, *, status: str, triple_count: int | None = None,
                     error: str | None = None, steps: list | None = None) -> BuildRun:
        with self._cur() as cur:
            row = cur.execute(
                "UPDATE build_runs SET status = %s, finished_at = now(), triple_count = %s, error = %s, "
                "steps = coalesce(%s, steps) WHERE id = %s RETURNING *",
                (status, triple_count, error, Jsonb(steps) if steps is not None else None, run_id)).fetchone()
            if row is None:
                raise NotFound(f"Build {run_id}")
            self._audit(cur, row["domain_version_id"], row["actor"], f"build.{status}", {"run": str(run_id), "triples": triple_count})
            return BuildRun(**row)

    def update_build_steps(self, run_id: UUID, steps: list) -> None:
        with self._cur() as cur:
            cur.execute("UPDATE build_runs SET steps = %s WHERE id = %s", (Jsonb(steps), run_id))

    def running_build(self, version_id: UUID) -> BuildRun | None:
        with self._cur() as cur:
            row = cur.execute("SELECT * FROM build_runs WHERE domain_version_id = %s AND status = 'running' "
                              "ORDER BY started_at DESC LIMIT 1", (version_id,)).fetchone()
        return BuildRun(**row) if row else None

    def fail_stale_builds(self, reason: str = "process restarted") -> list[BuildRun]:
        """Mark every 'running' run as failed: called at startup, when no worker can still own one."""
        with self._cur() as cur:
            rows = cur.execute("UPDATE build_runs SET status = 'failed', finished_at = now(), error = %s "
                               "WHERE status = 'running' RETURNING *", (reason,)).fetchall()
            for r in rows:
                self._audit(cur, r["domain_version_id"], None, "build.failed", {"run": str(r["id"]), "reason": reason})
            return [BuildRun(**r) for r in rows]

    def get_build(self, run_id: UUID) -> BuildRun:
        with self._cur() as cur:
            row = cur.execute("SELECT * FROM build_runs WHERE id = %s", (run_id,)).fetchone()
        if row is None:
            raise NotFound(f"Build {run_id}")
        return BuildRun(**row)

    def latest_build(self, version_id: UUID) -> BuildRun | None:
        with self._cur() as cur:
            row = cur.execute("SELECT * FROM build_runs WHERE domain_version_id = %s ORDER BY started_at DESC LIMIT 1",
                              (version_id,)).fetchone()
        return BuildRun(**row) if row else None

    def list_builds(self, version_id: UUID) -> list[BuildRun]:
        with self._cur() as cur:
            return [BuildRun(**r) for r in cur.execute(
                "SELECT * FROM build_runs WHERE domain_version_id = %s ORDER BY started_at DESC", (version_id,))]

    # -- comments ------------------------------------------------------------

    def add_comment(self, version_id: UUID, *, author: str, body: str) -> Comment:
        if not body or not body.strip():
            raise ValueError("Comment body is empty")
        with self._cur() as cur:
            self._lock_version(cur, version_id, lock=False)
            row = cur.execute("INSERT INTO comments (domain_version_id, author, body) VALUES (%s, %s, %s) RETURNING *",
                              (version_id, author, body.strip())).fetchone()
            self._audit(cur, version_id, author, "comment.added", {"comment": row["id"]})
            return Comment(**row)

    def list_comments(self, version_id: UUID) -> list[Comment]:
        with self._cur() as cur:
            return [Comment(**r) for r in cur.execute("SELECT * FROM comments WHERE domain_version_id = %s ORDER BY id", (version_id,))]

    # -- worklist & locks ----------------------------------------------------

    def tasks_for(self, actor: str) -> dict[str, list[Task]]:
        with self._cur() as cur:
            rows = cur.execute(
                "SELECT v.*, d.name AS domain, d.review_quorum FROM domain_versions v JOIN domains d ON d.id = v.domain_id "
                "WHERE v.status IN ('draft', 'in_review') ORDER BY d.name, v.version").fetchall()
            out: dict[str, list[Task]] = {"drafts": [], "to_review": [], "publishable": []}
            for r in rows:
                task = Task(r["domain"], r["id"], r["version"], Status(r["status"]), r["editor"], quorum=r["review_quorum"])
                if r["status"] == Status.DRAFT.value:
                    out["drafts"].append(task)
                    continue
                rnd = self._review_round(cur, r["id"])
                reviewers = {x["reviewer"]: x["approved"] for x in cur.execute(
                    "SELECT reviewer, approved FROM reviews WHERE domain_version_id = %s AND review_round = %s ORDER BY id",
                    (r["id"], rnd))}
                approvals = sum(1 for ok in reviewers.values() if ok)
                task = Task(r["domain"], r["id"], r["version"], Status.IN_REVIEW, r["editor"], approvals, r["review_quorum"])
                if actor not in reviewers:
                    out["to_review"].append(task)
                if approvals >= r["review_quorum"]:
                    out["publishable"].append(task)
            return out

    def list_locks(self) -> list[Lock]:
        with self._cur() as cur:
            rows = cur.execute(
                "SELECT v.id, v.version, v.status, v.editor, v.lease_expires_at, d.name AS domain FROM domain_versions v "
                "JOIN domains d ON d.id = v.domain_id WHERE v.editor IS NOT NULL ORDER BY d.name, v.version").fetchall()
        now = _now()
        return [Lock(r["domain"], r["id"], r["version"], Status(r["status"]), r["editor"], r["lease_expires_at"],
                     stale=bool(r["lease_expires_at"] and r["lease_expires_at"] <= now)) for r in rows]

    def force_release(self, version_id: UUID, *, actor: str) -> None:
        with self._cur() as cur:
            row = self._lock_version(cur, version_id)
            cur.execute("UPDATE domain_versions SET editor = NULL, lease_expires_at = NULL WHERE id = %s", (version_id,))
            self._audit(cur, version_id, actor, "lease.released", {"forced": True, "previous": row["editor"]})

    # -- analytics runs ------------------------------------------------------

    def start_analytics(self, version_id: UUID, scope: str, *, actor: str | None = None) -> AnalyticsRun:
        with self._cur() as cur:
            self._lock_version(cur, version_id, lock=False)
            row = cur.execute("INSERT INTO analytics_runs (domain_version_id, scope, status, actor) VALUES (%s, %s, 'running', %s) RETURNING *",
                              (version_id, scope, actor)).fetchone()
            return AnalyticsRun(**row)

    def finish_analytics(self, run_id: UUID, *, status: str, nodes: int | None = None, edges: int | None = None,
                         components: int | None = None, avg_degree: float | None = None, density: float | None = None,
                         duration: float | None = None, error: str | None = None, results: dict | None = None) -> AnalyticsRun:
        with self._cur() as cur:
            row = cur.execute(
                "UPDATE analytics_runs SET status = %s, finished_at = now(), nodes = %s, edges = %s, components = %s, avg_degree = %s, "
                "density = %s, duration_seconds = %s, error = %s, results = %s WHERE id = %s RETURNING *",
                (status, nodes, edges, components, avg_degree, density, duration, error,
                 Jsonb(results) if results is not None else None, run_id)).fetchone()
            if row is None:
                raise NotFound(f"Analytics run {run_id}")
            return AnalyticsRun(**row)

    def get_analytics(self, run_id: UUID) -> AnalyticsRun:
        with self._cur() as cur:
            row = cur.execute("SELECT * FROM analytics_runs WHERE id = %s", (run_id,)).fetchone()
        if row is None:
            raise NotFound(f"Analytics run {run_id}")
        return AnalyticsRun(**row)

    def list_analytics(self, version_id: UUID) -> list[AnalyticsRun]:
        with self._cur() as cur:
            return [AnalyticsRun(**r) for r in cur.execute(
                "SELECT * FROM analytics_runs WHERE domain_version_id = %s ORDER BY started_at DESC", (version_id,))]

    # -- audit ---------------------------------------------------------------

    def audit_trail(self, version_id: UUID) -> list[AuditEntry]:
        with self._cur() as cur:
            return [AuditEntry(**r) for r in cur.execute(
                "SELECT * FROM audit_log WHERE domain_version_id = %s ORDER BY id", (version_id,))]

    # -- internals -----------------------------------------------------------

    def _cur(self):
        return _DictCursor(self.db)

    @staticmethod
    def _lock_version(cur, version_id: UUID, lock: bool = True) -> dict:
        row = cur.execute(f"SELECT * FROM domain_versions WHERE id = %s{' FOR UPDATE' if lock else ''}", (version_id,)).fetchone()
        if row is None:
            raise NotFound(f"Version {version_id}")
        return row

    @staticmethod
    def _check_lease(row: dict, actor: str) -> None:
        holder, expires = row["editor"], row["lease_expires_at"]
        if holder and holder != actor and expires and expires > _now():
            raise LockedError(f"Version is being edited by {holder}")

    def _check_quorum(self, cur, row: dict) -> None:
        quorum = cur.execute("SELECT review_quorum FROM domains WHERE id = %s", (row["domain_id"],)).fetchone()["review_quorum"]
        rnd = self._review_round(cur, row["id"])
        approvals = cur.execute(
            "SELECT count(DISTINCT reviewer) FROM reviews WHERE domain_version_id = %s AND review_round = %s AND approved",
            (row["id"], rnd)).fetchone()["count"]
        if approvals < quorum:
            raise LifecycleError(f"Publishing needs {quorum} approval(s); have {approvals}")

    @staticmethod
    def _review_round(cur, version_id: UUID) -> int:
        # A review round starts each time the version enters review; reviews from earlier rounds don't count.
        return cur.execute("SELECT count(*) FROM audit_log WHERE domain_version_id = %s AND action = 'status.in_review'",
                           (version_id,)).fetchone()["count"]

    @staticmethod
    def _audit(cur, version_id: UUID | None, actor: str | None, action: str, detail: dict | None) -> None:
        cur.execute("INSERT INTO audit_log (domain_version_id, actor, action, detail) VALUES (%s, %s, %s, %s)",
                    (version_id, actor, action, Jsonb(detail) if detail is not None else None))


class _DictCursor:
    """Context manager yielding a dict-row cursor inside one transaction."""

    def __init__(self, db: Database) -> None:
        self._ctx = db.connection()

    def __enter__(self):
        self._conn = self._ctx.__enter__()
        self._tx = self._conn.transaction()
        self._tx.__enter__()
        return self._conn.cursor(row_factory=dict_row)

    def __exit__(self, *exc):
        try:
            self._tx.__exit__(*exc)
        finally:
            self._ctx.__exit__(*exc)


def _version(row: dict) -> DomainVersion:
    return DomainVersion(**{**row, "status": Status(row["status"])})
