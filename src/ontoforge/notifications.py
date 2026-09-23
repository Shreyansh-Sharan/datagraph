"""Notifications: one row per activity, for the bell in the top bar.

Builds, jobs, profiles, rule runs, design changes and lifecycle moves all land here; a running
activity keeps one row that updates in place (progress, then done or failed). Every caller sees
the rows meant for everyone, the rows it caused, and (reviewers) the rows for reviewers."""
from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from ontoforge.db import Database

log = logging.getLogger("ontoforge.notifications")
VIA: ContextVar[str | None] = ContextVar("notify_via", default=None)   # "assistant" | "mcp" | None: how the actor acted

Ref = tuple[str, str]   # ("build", run id) | ("job", job id)

# Audit actions that become notifications: title template, audience, screen to open.
TITLES: dict[str, tuple[str, str, str]] = {
    "build.started": ("Build of {domain} v{version} started", "all", "build"),
    "build.succeeded": ("Build of {domain} v{version} succeeded", "all", "build"),
    "build.failed": ("Build of {domain} v{version} failed", "all", "build"),
    "build.cancelled": ("Build of {domain} v{version} cancelled", "all", "build"),
    "status.in_review": ("{domain} v{version} is ready for review", "reviewers", "versions"),
    "status.draft": ("{domain} v{version} went back to draft", "all", "versions"),
    "status.published": ("{domain} v{version} was published", "all", "versions"),
    "status.archived": ("{domain} v{version} was archived", "all", "versions"),
    "review.added": ("{actor} reviewed {domain} v{version}", "all", "versions"),
    "comment.added": ("{actor} commented on {domain} v{version}", "all", "overview"),
    "lease.acquired": ("{actor} took the lease on {domain} v{version}", "all", "overview"),
    "lease.released": ("{actor} released the lease on {domain} v{version}", "all", "overview"),
    "version.created": ("Draft v{version} of {domain} created", "all", "overview"),
    "version.imported": ("{domain} v{version} imported", "all", "overview"),
    "version.activated": ("{domain} now serves v{version}", "all", "overview"),
    "version.deactivated": ("{domain} serves no version now", "all", "overview"),
    "version.deleted": ("{domain} v{version} deleted", "all", "versions"),
    "content.updated": ("{actor} changed the design of {domain} v{version}", "all", "ontology"),
    "domain.updated": ("{actor} changed the settings of {domain}", "all", "overview"),
    "mcp_policy.updated": ("MCP policy of {domain} changed", "all", "overview"),
}
_FIELD_SCREEN = {"mapping": "mapping", "rules": "rules", "quality": "quality", "ontology_ttl": "ontology", "attachments": "overview"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Notifier:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- producing ------------------------------------------------------------------------------------

    def emit(self, cur, kind: str, *, title: str, actor: str | None = None, domain: str | None = None, version: int | None = None,
             table: str | None = None, body: str | None = None, link: dict | None = None, audience: str = "all", status: str = "info",
             ref: Ref | None = None, detail: dict | None = None) -> int:
        """One notification; with an open cursor it joins the caller's transaction. A ref makes the row updatable."""
        link = dict(link or {})
        link.setdefault("domain", domain)
        if version is not None:
            link.setdefault("version", version)
        if table:
            link.setdefault("table", table)
        params = (kind, actor, VIA.get(), domain, version, table, title, body, Jsonb(link), status, ref[0] if ref else None, ref[1] if ref else None,
                  audience, Jsonb(detail) if detail is not None else None)
        sql = ("INSERT INTO notifications (kind, actor, via, domain_name, version, table_name, title, body, link, status, ref_kind, ref_id, audience, detail) "
               "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
               "ON CONFLICT (ref_kind, ref_id) WHERE ref_id IS NOT NULL DO UPDATE SET status = EXCLUDED.status, title = EXCLUDED.title, updated_at = now() RETURNING id")
        if cur is not None:
            return _col(cur.execute(sql, params).fetchone(), "id", 0)
        with self.db.transaction() as c:
            return _col(c.execute(sql, params).fetchone(), "id", 0)

    def progress(self, ref: Ref, text: str) -> None:
        try:
            with self.db.transaction() as cur:
                cur.execute("UPDATE notifications SET progress = %s, updated_at = now() WHERE ref_kind = %s AND ref_id = %s AND status = 'running'", (text, ref[0], ref[1]))
        except Exception:   # noqa: BLE001 - progress is a courtesy, never a failure of the work itself
            log.debug("progress note lost", exc_info=True)

    def finish(self, ref: Ref, status: str, *, title: str | None = None, body: str | None = None, cur=None) -> None:
        sql = ("UPDATE notifications SET status = %s, progress = NULL, title = coalesce(%s, title), body = coalesce(%s, body), updated_at = now() "
               "WHERE ref_kind = %s AND ref_id = %s")
        params = (status, title, body, ref[0], ref[1])
        if cur is not None:
            cur.execute(sql, params); return
        with self.db.transaction() as c:
            c.execute(sql, params)

    def fail_running(self, reason: str, ref_kind: str | None = None) -> int:
        """At startup: whatever was running belonged to a process that is gone."""
        with self.db.transaction() as cur:
            cur.execute("UPDATE notifications SET status = 'failed', progress = NULL, body = %s, updated_at = now() WHERE status = 'running'"
                        + (" AND ref_kind = %s" if ref_kind else ""), (reason, ref_kind) if ref_kind else (reason,))
            return cur.rowcount

    def from_audit(self, cur, action: str, *, actor: str | None, version_id: UUID | None, detail: dict | None) -> None:
        """The bridge the registry calls after every audit row: the actions people want to hear about become notifications."""
        tpl = TITLES.get(action)
        if tpl is None:
            return
        title_tpl, audience, screen = tpl
        domain, version = None, None
        if version_id is not None:
            row = cur.execute("SELECT d.name, v.version FROM domain_versions v JOIN domains d ON d.id = v.domain_id WHERE v.id = %s", (version_id,)).fetchone()
            if row:
                domain, version = _col(row, "name", 0), _col(row, "version", 1)
        if domain is None and detail and detail.get("domain"):
            row = cur.execute("SELECT name FROM domains WHERE id = %s::uuid", (str(detail["domain"]),)).fetchone() if _is_uuid(detail["domain"]) else None
            domain = _col(row, "name", 0) if row else str(detail["domain"])
        title = title_tpl.format(domain=domain or "?", version=version if version is not None else "?", actor=actor or "someone")
        body = None
        if action == "content.updated" and detail and detail.get("fields"):
            fields = [str(f) for f in detail["fields"]]
            body = ", ".join(fields)
            screen = next((_FIELD_SCREEN[f] for f in fields if f in _FIELD_SCREEN), screen)
        if action.startswith("build."):
            run = str((detail or {}).get("run") or "")
            if action == "build.started":
                self.emit(cur, action, title=title, actor=actor, domain=domain, version=version, link={"screen": "build"}, status="running", ref=("build", run), detail=detail)
            else:
                status = "done" if action == "build.succeeded" else "failed"
                triples = (detail or {}).get("triples")
                body = f"{triples:,} triples" if isinstance(triples, int) else (detail or {}).get("reason") or (detail or {}).get("error")
                self.finish(("build", run), status, title=title, body=body, cur=cur)
            return
        self.emit(cur, action, title=title, actor=actor, domain=domain, version=version, body=body, link={"screen": screen}, audience=audience, detail=detail)

    # -- reading ---------------------------------------------------------------------------------------

    def feed(self, actor: str, role: str | None = None, *, since: int | None = None, limit: int = 50) -> dict:
        """The rows this caller may see: newest first, running ones always, with the unread count."""
        reviewer = role in ("reviewer", "admin")
        with self.db.rows() as cur:
            wm = cur.execute("SELECT read_until FROM notification_watermarks WHERE principal = %s", (actor,)).fetchone()
            until = int(wm["read_until"]) if wm else 0
            visible = "(n.audience = 'all' OR n.actor = %s OR (n.audience = 'reviewers' AND %s))"
            params: list[Any] = [actor, reviewer]
            where = visible
            if since is not None:
                # newer rows, every running row, and rows that changed (finished, progressed) in the last few polls
                where += " AND (n.id > %s OR n.status = 'running' OR (n.updated_at > n.created_at AND n.updated_at > now() - interval '15 seconds'))"
                params.append(int(since))
            rows = cur.execute(
                f"SELECT n.*, (r.notification_id IS NOT NULL OR n.id <= %s) AS read FROM notifications n "
                f"LEFT JOIN notification_reads r ON r.notification_id = n.id AND r.principal = %s WHERE {where} ORDER BY n.id DESC LIMIT %s",
                [until, actor, *params, max(1, min(int(limit), 200))]).fetchall()
            unread = cur.execute(
                f"SELECT count(*) AS c FROM notifications n LEFT JOIN notification_reads r ON r.notification_id = n.id AND r.principal = %s "
                f"WHERE {visible} AND n.id > %s AND r.notification_id IS NULL", [actor, actor, reviewer, until]).fetchone()["c"]
            latest = cur.execute("SELECT coalesce(max(id), 0) AS m FROM notifications").fetchone()["m"]
        return {"items": [_row(r) for r in rows], "unread": int(unread), "latest_id": int(latest)}

    def mark_read(self, actor: str, *, ids: list[int] | None = None, until: int | None = None) -> None:
        with self.db.transaction() as cur:
            if until is not None:
                cur.execute("INSERT INTO notification_watermarks (principal, read_until) VALUES (%s, %s) "
                            "ON CONFLICT (principal) DO UPDATE SET read_until = greatest(notification_watermarks.read_until, EXCLUDED.read_until)", (actor, int(until)))
            for i in ids or []:
                cur.execute("INSERT INTO notification_reads (principal, notification_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (actor, int(i)))


class NullNotifier:
    """What a service holds when no notifier was wired (tests, scripts): every call is a no-op."""
    def emit(self, *a, **k) -> int: return 0
    def progress(self, *a, **k) -> None: return None
    def finish(self, *a, **k) -> None: return None
    def fail_running(self, *a, **k) -> int: return 0
    def from_audit(self, *a, **k) -> None: return None


def where(registry, version_id: UUID) -> tuple[str | None, int | None]:
    """(domain name, version number) of a version, or (None, None) when it is gone."""
    try:
        v = registry.get_version(version_id)
        return registry.get_domain_by_id(v.domain_id).name, v.version
    except Exception:  # noqa: BLE001
        return None, None


def _col(row, key: str, idx: int):
    """A column of a row that may be a dict (registry cursors) or a tuple (plain cursors)."""
    return row[key] if isinstance(row, dict) else row[idx]


def _is_uuid(v) -> bool:
    try:
        UUID(str(v)); return True
    except ValueError:
        return False


def _row(r: dict) -> dict:
    return {"id": int(r["id"]), "kind": r["kind"], "actor": r["actor"], "via": r["via"], "domain": r["domain_name"], "version": r["version"], "table": r["table_name"],
            "title": r["title"], "body": r["body"], "link": r["link"] or {}, "status": r["status"], "progress": r["progress"], "read": bool(r["read"]),
            "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()}
