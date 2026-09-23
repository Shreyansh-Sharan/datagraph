"""Background jobs for the slow AI tasks (drafting an ontology, suggesting a mapping).

A build has its own run table because its history matters; these are transient, so they live in
memory: the request returns the job at once and the screen polls it for progress until it settles.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from ontoforge.registry import NotFound

Report = Callable[[str], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


log = logging.getLogger("ontoforge.jobs")


@dataclass
class Job:
    id: UUID
    kind: str
    version_id: UUID
    actor: str | None
    status: str = "running"            # running | succeeded | failed
    progress: str | None = None        # what it is doing right now
    progress_at: datetime = field(default_factory=_now)
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


TITLES = {"draft-ontology": "Drafting the ontology of {domain}", "suggest-mapping": "Suggesting the mapping of {domain}", "suggest-relations": "Filling the relationships of {domain}",
          "profile": "Profiling {label}", "dq-run": "Running the rules of {label}", "dq-suggest": "Suggesting rules for {label}", "glossary-suggest": "Suggesting glossary entries for {label}"}


class JobRunner:
    def __init__(self, workers: int = 2, notifier=None, registry=None) -> None:
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ontoforge-ai")
        self._jobs: dict[UUID, Job] = {}
        self._lock = threading.Lock()
        self.notifier, self.registry = notifier, registry   # a running notification per job, updated as it reports

    def _where(self, version_id: UUID) -> tuple[str | None, int | None]:
        try:
            v = self.registry.get_version(version_id) if self.registry else None
            return (self.registry.get_domain_by_id(v.domain_id).name, v.version) if v else (None, None)
        except Exception:  # noqa: BLE001 - a missing name never stops a job
            return None, None

    def submit(self, kind: str, version_id: UUID, work: Callable[[Report], Any], *, actor: str | None = None, label: str | None = None) -> Job:
        job = Job(uuid4(), kind, version_id, actor, progress="Queued")
        with self._lock:
            self._jobs[job.id] = job
        ref = ("job", str(job.id))
        domain, version = self._where(version_id) if self.notifier else (None, None)
        short = (label or "").split(".")[-1]
        title = TITLES.get(kind, "{kind} on {domain}").format(kind=kind, domain=domain or "?", label=short or domain or "?")
        screen = "table" if kind in ("profile", "dq-run", "dq-suggest", "glossary-suggest") else "ontology" if kind == "draft-ontology" else "mapping"
        tab = {"profile": "profile", "dq-run": "dq", "dq-suggest": "dq", "glossary-suggest": "glossary"}.get(kind)
        link = {"screen": screen, **({"tab": tab} if tab else {})}
        if label and "." in label:
            link.update({"schema": label.rsplit(".", 1)[0], "table": label.rsplit(".", 1)[1]})
        if self.notifier:
            try:
                self.notifier.emit(None, f"job.{kind}", title=title, actor=actor, domain=domain, version=version, table=label, link=link, status="running", ref=ref, audience="all")
            except Exception:  # noqa: BLE001
                log.warning("could not announce job %s", job.id, exc_info=True)
        last = {"at": 0.0}

        def report(message: str) -> None:
            job.progress, job.progress_at = message, _now()
            if self.notifier and (job.progress_at.timestamp() - last["at"]) >= 1.0:   # at most one write a second
                last["at"] = job.progress_at.timestamp()
                self.notifier.progress(ref, message)

        def run() -> None:
            try:
                job.result = work(report)
                job.status, job.progress = "succeeded", "Done"
                if self.notifier:
                    self.notifier.finish(ref, "done", title=title.replace("Drafting", "Drafted").replace("Suggesting", "Suggested").replace("Filling", "Filled").replace("Profiling", "Profiled").replace("Running the rules of", "Ran the rules of"))
            except Exception as exc:  # noqa: BLE001 - the job records every failure
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
                log.error("job %s (%s) failed: %s", job.id, kind, job.error, extra={"event": "job.failed", "job_id": str(job.id), "kind": kind, "version_id": str(version_id), "actor": actor}, exc_info=True)
                if self.notifier:
                    self.notifier.finish(ref, "failed", title=title.replace("ing ", "ing failed: ", 1) if "ing " in title else f"{title} failed", body=job.error)
            finally:
                job.finished_at = job.progress_at = _now()

        self.pool.submit(run)
        return job

    def get(self, job_id: UUID) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"Job {job_id}")
        return job

    def latest(self, version_id: UUID, kind: str | None = None) -> Job | None:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.version_id == version_id and (kind is None or j.kind == kind)]
        return max(jobs, key=lambda j: j.started_at) if jobs else None

    def shutdown(self, wait: bool = False) -> None:
        self.pool.shutdown(wait=wait, cancel_futures=True)
