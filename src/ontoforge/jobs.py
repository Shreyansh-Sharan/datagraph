"""Background jobs for the slow AI tasks (drafting an ontology, suggesting a mapping).

A build has its own run table because its history matters; these are transient, so they live in
memory: the request returns the job at once and the screen polls it for progress until it settles.
"""
from __future__ import annotations

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


class JobRunner:
    def __init__(self, workers: int = 2) -> None:
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ontoforge-ai")
        self._jobs: dict[UUID, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, version_id: UUID, work: Callable[[Report], Any], *, actor: str | None = None) -> Job:
        job = Job(uuid4(), kind, version_id, actor, progress="Queued")
        with self._lock:
            self._jobs[job.id] = job

        def report(message: str) -> None:
            job.progress, job.progress_at = message, _now()

        def run() -> None:
            try:
                job.result = work(report)
                job.status, job.progress = "succeeded", "Done"
            except Exception as exc:  # noqa: BLE001 - the job records every failure
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
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
