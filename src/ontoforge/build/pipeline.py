"""Build: mapping spec -> R2RML -> SQL -> triple store, recorded as a build run."""
from __future__ import annotations

import time
from uuid import UUID

from ontoforge.compiler import compile_mapping
from ontoforge.mapping import MappingSpec
from ontoforge.r2rml import parse_r2rml, serialize_r2rml
from ontoforge.registry import BuildRun, Registry, RegistryError
from ontoforge.store import TripleStore

from .source import PostgresSource, SourceEngine


class BuildError(Exception):
    pass


class BuildPipeline:
    def __init__(self, registry: Registry, store: TripleStore, source: SourceEngine) -> None:
        self.registry, self.store, self.source = registry, store, source

    def run(self, version_id: UUID, *, actor: str | None = None) -> BuildRun:
        run = self.registry.start_build(version_id, actor=actor)
        steps: list[dict] = []
        try:
            with _step(steps, "compile"):
                version = self.registry.get_version(version_id)
                r2rml = self._r2rml(version)
                compiled = compile_mapping(r2rml, self.source.dialect, column_types=self.source.catalog.resolver())
                self.registry.store_r2rml(version_id, serialize_r2rml(r2rml))
                steps[-1]["detail"] = {"selects": len(compiled.selects)}
            with _step(steps, "prepare"):
                self.source.prepare()
            with _step(steps, "load"):
                if isinstance(self.source, PostgresSource) and self.source.db is self.store.db:
                    count = self.store.replace_from_sql(version_id, compiled.sql)
                else:
                    count = self.store.replace(version_id, self.source.stream(compiled.sql))
                steps[-1]["detail"] = {"triples": count}
            with _step(steps, "finalize"):
                counted = self.store.count(version_id)
            return self.registry.finish_build(run.id, status="succeeded", triple_count=counted, steps=steps)
        except Exception as exc:  # noqa: BLE001 - every failure must be recorded on the run
            return self.registry.finish_build(run.id, status="failed", error=f"{type(exc).__name__}: {exc}", steps=steps)

    @staticmethod
    def _r2rml(version):
        if version.mapping:
            return MappingSpec.from_dict(version.mapping).to_r2rml()
        if version.r2rml_ttl:
            return parse_r2rml(version.r2rml_ttl)
        raise BuildError("Version has neither a mapping spec nor an R2RML document")


class _step:
    def __init__(self, steps: list[dict], name: str) -> None:
        self.steps, self.name = steps, name

    def __enter__(self):
        self.t0 = time.perf_counter()
        self.steps.append({"name": self.name, "seconds": None})
        return self

    def __exit__(self, exc_type, exc, tb):
        self.steps[-1]["seconds"] = round(time.perf_counter() - self.t0, 4)
        if exc is not None:
            self.steps[-1]["error"] = str(exc)
        return False
