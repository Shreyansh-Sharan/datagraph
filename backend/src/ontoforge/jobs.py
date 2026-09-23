"""Background jobs for the slow work: drafting an ontology, profiling a table, running rules.

The table is the record. A job started by one worker is readable by any other, and by the next
process: a dict would take its state down with the process that held it, so a restart used to
leave a screen polling a job that no longer existed anywhere. Cancellation is cooperative, so
work that can stop is handed a ``should_stop`` it polls.
"""
from __future__ import annotations

import inspect
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from ontoforge.registry import NotFound

Report = Callable[[str], None]

log = logging.getLogger("ontoforge.jobs")

HEARTBEAT = 5.0        # seconds between touches while a job runs
STALE_AFTER = "60 seconds"   # a heartbeat older than this means the worker is gone

_COLUMNS = ("id", "kind", "version_id", "actor", "label", "status", "progress", "cancel_requested",
            "created_at", "started_at", "heartbeat_at", "finished_at", "error", "result")


@dataclass
class Job:
    id: UUID
    kind: str
    version_id: UUID
    actor: str | None
    label: str | None
    status: str                        # queued | running | succeeded | failed | cancelled
    progress: str | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    error: str | None
    result: Any

    @property
    def settled(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _COLUMNS}


TITLES = {"draft-ontology": "Drafting the ontology of {domain}", "suggest-mapping": "Suggesting the mapping of {domain}", "suggest-relations": "Filling the relationships of {domain}",
          "profile": "Profiling {label}", "dq-run": "Running the rules of {label}", "dq-suggest": "Suggesting rules for {label}", "glossary-suggest": "Suggesting glossary entries for {label}"}

_DONE = (("Drafting", "Drafted"), ("Suggesting", "Suggested"), ("Filling", "Filled"), ("Profiling", "Profiled"), ("Running the rules of", "Ran the rules of"))


class JobRunner:
    def __init__(self, workers: int = 2, notifier=None, registry=None, db=None) -> None:
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ontoforge-ai")
        self.notifier, self.registry, self.db = notifier, registry, db
        self._lock = threading.Lock()

    # -- reading ---------------------------------------------------------------------------

    def get(self, job_id: UUID) -> Job:
        with self.db.rows() as cur:
            row = cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if row is None:
            raise NotFound(f"Job {job_id}")
        return _job(row)

    def list(self, version_id: UUID, kind: str | None = None, limit: int = 50) -> list[Job]:
        """The version's jobs, newest first."""
        sql = "SELECT * FROM jobs WHERE version_id = %s" + (" AND kind = %s" if kind else "") + " ORDER BY created_at DESC LIMIT %s"
        params = (version_id, kind, limit) if kind else (version_id, limit)
        with self.db.rows() as cur:
            return [_job(r) for r in cur.execute(sql, params)]

    def latest(self, version_id: UUID, kind: str | None = None) -> Job | None:
        found = self.list(version_id, kind, limit=1)
        return found[0] if found else None

    # -- writing ---------------------------------------------------------------------------

    def submit(self, kind: str, version_id: UUID, work: Callable[..., Any], *, actor: str | None = None, label: str | None = None) -> Job:
        with self.db.rows() as cur:
            row = cur.execute("INSERT INTO jobs (kind, version_id, actor, label, status, progress) "
                              "VALUES (%s, %s, %s, %s, 'queued', 'Queued') RETURNING *",
                              (kind, version_id, actor, label)).fetchone()
        job = _job(row)
        ref = ("job", str(job.id))
        domain, version = self._where(version_id) if self.notifier else (None, None)
        title = self._announce(job, kind, domain, version, label, ref)
        self.pool.submit(self._run, job, work, ref, title)
        return job

    def cancel(self, job_id: UUID) -> bool:
        """Ask a running job to stop. False when there is nothing left to cancel."""
        with self.db.rows() as cur:
            row = cur.execute("UPDATE jobs SET cancel_requested = true WHERE id = %s AND status IN ('queued', 'running') RETURNING id",
                              (job_id,)).fetchone()
        return row is not None

    def sweep_stale(self, reason: str = "the API restarted while this was running") -> int:
        """Every job the last process left behind is failed: no worker is coming back for it."""
        with self.db.rows() as cur:
            rows = cur.execute(
                "UPDATE jobs SET status = 'failed', error = %s, finished_at = now() "
                "WHERE status IN ('queued', 'running') AND (heartbeat_at IS NULL OR heartbeat_at < now() - %s::interval) "
                "RETURNING id", (reason, STALE_AFTER)).fetchall()
        if rows:
            log.warning("failed %d job(s) left running by a restart", len(rows), extra={"event": "jobs.swept", "count": len(rows)})
        return len(rows)

    def shutdown(self, wait: bool = False) -> None:
        self.pool.shutdown(wait=wait, cancel_futures=True)

    # -- the worker ------------------------------------------------------------------------

    def _run(self, job: Job, work: Callable[..., Any], ref: tuple[str, str], title: str) -> None:
        self._set(job.id, "status = 'running', started_at = now(), heartbeat_at = now(), progress = %s", ("Starting",))
        beating = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(job.id, beating), daemon=True, name=f"job-beat-{job.id}")
        beat.start()
        last = {"at": 0.0}

        def report(message: str) -> None:
            self._set(job.id, "progress = %s, heartbeat_at = now()", (message,))
            if self.notifier and (time.time() - last["at"]) >= 1.0:   # at most one notification a second
                last["at"] = time.time()
                self.notifier.progress(ref, message)

        cancelled = {"seen": 0.0, "value": False}

        def should_stop() -> bool:
            if time.time() - cancelled["seen"] >= 1.0:                # one read a second, not one per row
                cancelled["seen"] = time.time()
                with self.db.rows() as cur:
                    row = cur.execute("SELECT cancel_requested FROM jobs WHERE id = %s", (job.id,)).fetchone()
                cancelled["value"] = bool(row and row["cancel_requested"])
            return cancelled["value"]

        try:
            result = work(report, should_stop) if _wants_stop(work) else work(report)
            if should_stop.__call__() and result is None:
                self._finish(job, "cancelled", ref, title, error="Cancelled")
            else:
                self._finish(job, "succeeded", ref, title, result=result)
        except Exception as exc:  # noqa: BLE001 - the job records every failure
            error = f"{type(exc).__name__}: {exc}"
            log.error("job %s (%s) failed: %s", job.id, job.kind, error,
                      extra={"event": "job.failed", "job_id": str(job.id), "kind": job.kind, "version_id": str(job.version_id), "actor": job.actor}, exc_info=True)
            self._finish(job, "failed", ref, title, error=error)
        finally:
            beating.set()

    def _heartbeat(self, job_id: UUID, done: threading.Event) -> None:
        while not done.wait(HEARTBEAT):
            try:
                self._set(job_id, "heartbeat_at = now()", ())
            except Exception:  # noqa: BLE001 - a missed beat is not worth failing a job over
                log.debug("heartbeat failed for job %s", job_id, exc_info=True)

    def _finish(self, job: Job, status: str, ref: tuple[str, str], title: str, *, result: Any = None, error: str | None = None) -> None:
        payload = None
        if result is not None:
            try:
                payload = json.dumps(result, default=str)
            except (TypeError, ValueError):
                payload = json.dumps({"value": str(result)})
        self._set(job.id, "status = %s, finished_at = now(), heartbeat_at = now(), progress = %s, error = %s, result = %s::jsonb",
                  (status, {"succeeded": "Done", "cancelled": "Cancelled"}.get(status, "Failed"), error, payload))
        if not self.notifier:
            return
        if status == "succeeded":
            done = title
            for was, now in _DONE:
                done = done.replace(was, now)
            self.notifier.finish(ref, "done", title=done)
        elif status == "cancelled":
            self.notifier.finish(ref, "failed", title=f"{title} — cancelled")
        else:
            self.notifier.finish(ref, "failed", title=title.replace("ing ", "ing failed: ", 1) if "ing " in title else f"{title} failed", body=error)

    def _set(self, job_id: UUID, assignments: str, params: tuple) -> None:
        with self.db.rows() as cur:
            cur.execute(f"UPDATE jobs SET {assignments} WHERE id = %s", (*params, job_id))

    # -- announcing ------------------------------------------------------------------------

    def _where(self, version_id: UUID) -> tuple[str | None, int | None]:
        try:
            v = self.registry.get_version(version_id) if self.registry else None
            return (self.registry.get_domain_by_id(v.domain_id).name, v.version) if v else (None, None)
        except Exception:  # noqa: BLE001 - a missing name never stops a job
            return None, None

    def _announce(self, job: Job, kind: str, domain: str | None, version: int | None, label: str | None, ref: tuple[str, str]) -> str:
        short = (label or "").split(".")[-1]
        title = TITLES.get(kind, "{kind} on {domain}").format(kind=kind, domain=domain or "?", label=short or domain or "?")
        screen = "table" if kind in ("profile", "dq-run", "dq-suggest", "glossary-suggest") else "ontology" if kind == "draft-ontology" else "mapping"
        tab = {"profile": "profile", "dq-run": "dq", "dq-suggest": "dq", "glossary-suggest": "glossary"}.get(kind)
        link = {"screen": screen, **({"tab": tab} if tab else {})}
        if label and "." in label:
            link.update({"schema": label.rsplit(".", 1)[0], "table": label.rsplit(".", 1)[1]})
        if self.notifier:
            try:
                self.notifier.emit(None, f"job.{kind}", title=title, actor=job.actor, domain=domain, version=version,
                                   table=label, link=link, status="running", ref=ref, audience="all")
            except Exception:  # noqa: BLE001
                log.warning("could not announce job %s", job.id, exc_info=True)
        return title


def _wants_stop(work: Callable[..., Any]) -> bool:
    """True when the work can be cancelled: it takes a second argument to poll."""
    try:
        return len([p for p in inspect.signature(work).parameters.values()
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]) >= 2
    except (TypeError, ValueError):
        return False


def _job(row) -> Job:
    return Job(**{k: row[k] for k in _COLUMNS})
