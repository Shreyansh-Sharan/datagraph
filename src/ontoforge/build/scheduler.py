"""Runs builds on a thread pool; one running build per version; cooperative cancellation."""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import UUID

from ontoforge.registry import BuildRun, LifecycleError, Registry

from .pipeline import BuildPipeline


class BuildScheduler:
    def __init__(self, pipeline: BuildPipeline, registry: Registry, workers: int = 2) -> None:
        self.pipeline, self.registry = pipeline, registry
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ontoforge-build")
        self._lock = threading.Lock()
        self._cancel: dict[UUID, threading.Event] = {}
        self._futures: dict[UUID, Future] = {}

    def submit(self, version_id: UUID, *, actor: str | None = None) -> BuildRun:
        with self._lock:
            if self.registry.running_build(version_id) is not None:
                raise LifecycleError("A build is already running for this version")
            run = self.registry.start_build(version_id, actor=actor)
            flag = threading.Event()
            self._cancel[run.id] = flag
            self._futures[run.id] = self.pool.submit(self._execute, version_id, run, flag)
        return run

    def wait(self, run_id: UUID, timeout: float | None = None) -> BuildRun:
        fut = self._futures.get(run_id)
        if fut is not None:
            fut.result(timeout=timeout)
        return self.registry.get_build(run_id)

    def cancel(self, run_id: UUID) -> bool:
        """True if a running build was asked to stop; False when there is nothing to cancel."""
        flag = self._cancel.get(run_id)
        if flag is None or self.registry.get_build(run_id).status != "running":
            return False
        flag.set()
        return True

    def shutdown(self, wait: bool = True) -> None:
        self.pool.shutdown(wait=wait)

    def _execute(self, version_id: UUID, run: BuildRun, flag: threading.Event) -> None:
        try:
            self.pipeline.run(version_id, run=run, cancel_check=flag.is_set)
        finally:
            with self._lock:
                self._cancel.pop(run.id, None)
                self._futures.pop(run.id, None)
