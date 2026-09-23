"""Build: mapping spec -> R2RML -> SQL -> triple store, recorded as a build run.

Steps are written to the run as they complete so a poller sees live progress. A ``cancel_check``
callable is consulted between steps; cancellation before the load step leaves the previous
triples untouched (the load itself is one transaction, so a cancel during it is a rollback).
"""
from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator
from uuid import UUID

from ontoforge.compiler import compile_mapping
from ontoforge.mapping import MappingSpec
from ontoforge.r2rml import parse_r2rml, serialize_r2rml
from ontoforge.registry import BuildRun, Registry
from ontoforge.store import COLUMNS, TripleStore

from .source import PostgresSource, SourceEngine


@dataclass(frozen=True)
class PublishConfig:
    """Where (and whether) to publish the triple view/table inside the source warehouse."""
    target_schema: str                  # e.g. "main.kg" on Databricks, "kg" on Postgres
    materialization: str = "view"       # "none" | "view" | "table"

    def __post_init__(self) -> None:
        if self.materialization not in ("none", "view", "table"):
            raise ValueError(f"materialization must be none|view|table, not {self.materialization!r}")

    @property
    def enabled(self) -> bool:
        return self.materialization != "none"


log = logging.getLogger("ontoforge.build")


class BuildError(Exception):
    pass


class BuildCancelled(Exception):
    pass


class BuildPipeline:
    def __init__(self, registry: Registry, store: TripleStore, source: "SourceEngine | Callable[[UUID], SourceEngine]",
                 *, progress_rows: int = 5000,
                 publish: PublishConfig | None = None, metadata=None, notifier=None) -> None:
        self.registry, self.store = registry, store
        self.notifier = notifier   # the build's notification row follows the steps
        self._source = source     # one engine, or a resolver giving the version's domain's engine
        self.publish = publish if publish and publish.enabled else None
        self.metadata = metadata  # MetadataService, optional: adds a non-blocking drift step
        self.progress_rows = progress_rows  # the load step records its row count this often

    def source_for(self, version_id: UUID) -> SourceEngine:
        return self._source(version_id) if callable(self._source) else self._source

    def run(self, version_id: UUID, *, actor: str | None = None, run: BuildRun | None = None,
            cancel_check: Callable[[], bool] | None = None, full: bool = False) -> BuildRun:
        run = run or self.registry.start_build(version_id, actor=actor)
        steps: list[dict] = []
        cancelled = cancel_check or (lambda: False)
        ctx = {"run_id": str(run.id), "version_id": str(version_id)}
        log.info("build started", extra={"event": "build.started", **ctx})

        NAMES = ["compile", "prepare", "plan", "drift", "publish", "load", "finalize"]

        def persist():   # what GET /builds/{id} returns while the run is still going
            self.registry.update_build_steps(run.id, steps)
            if self.notifier and steps:
                last = steps[-1]
                rows = (last.get("detail") or {}).get("rows") if isinstance(last.get("detail"), dict) else None
                where = f"step {NAMES.index(last['name']) + 1 if last['name'] in NAMES else len(steps)} of {len(NAMES)}: {last['name']}"
                self.notifier.progress(("build", str(run.id)), f"{where} · {rows:,} rows" if rows else where)

        def on_step_done():
            persist()
            log.info("step %s %.3fs", steps[-1]["name"], steps[-1]["seconds"],
                     extra={"event": "build.step", "step": steps[-1]["name"], "seconds": steps[-1]["seconds"], **ctx})

        def step(name: str):
            if cancelled():
                raise BuildCancelled(f"cancelled before {name}")
            return _step(steps, name, on_start=persist, on_done=on_step_done)

        def on_rows(n: int):   # progress of the load step, persisted every `progress_rows` rows
            steps[-1]["detail"] = {"rows": n}
            persist()

        try:
            with step("compile"):
                version = self.registry.get_version(version_id)
                r2rml = self._r2rml(version)
                self.source = self.source_for(version_id)   # the domain's own connection, or the deployment's source
                compiled = compile_mapping(r2rml, self.source.dialect, column_types=self._column_types(version_id))
                ttl = serialize_r2rml(r2rml)
                self.registry.store_r2rml(version_id, ttl)
                # The spec, canonically serialized: the Turtle carries fresh blank-node ids every time.
                mapping_hash = hashlib.sha256((json.dumps(version.mapping, sort_keys=True) if version.mapping else (version.r2rml_ttl or "")).encode()).hexdigest()
                steps[-1]["detail"] = {"selects": len(compiled.selects)}
            with step("prepare"):
                self._prepare()
            with step("plan"):
                plan = self._plan(version_id, compiled, mapping_hash, full=full or bool(self.publish))
                steps[-1]["detail"] = {"mode": plan.mode, "reason": plan.reason, "changed": plan.changed, "unchanged": len(plan.unchanged), "dropped": plan.dropped}
            if self.metadata is not None:
                with step("drift"):
                    from dataclasses import asdict
                    watched = None if plan.mode == "full" else plan.changed     # a table that did not move cannot have drifted
                    issues = [asdict(i) for i in (self.metadata.drift(version_id, watched) if watched != [] else [])]
                    steps[-1]["detail"] = {"issues": issues, "tables": len(plan.changed)}
                    if issues and self.notifier:
                        from ontoforge.notifications import where
                        dname, vno = where(self.registry, version_id)
                        self.notifier.emit(None, "drift.found", title=f"Schema drift in {dname or '?'} v{vno}: {len(issues)} issue{'s' if len(issues) != 1 else ''}", actor=actor,
                                           domain=dname, version=vno, body=", ".join(f"{i.get('table', '?')}.{i.get('column') or ''}".rstrip(".") for i in issues[:3]), link={"screen": "metadata"}, status="failed")
                    if issues:
                        log.warning("schema drift: %d issue(s)", len(issues), extra={"event": "build.drift", "issues": issues, **ctx})
            if self.publish:
                with step("publish"):
                    published = self._publish(version, compiled.sql)
                    steps[-1]["detail"] = published
                    load_sql = f"SELECT {', '.join(COLUMNS)} FROM {self._quote(published['table'] or published['view'])}"
                with step("load"):
                    count = self._load(version_id, load_sql, on_rows)
                    steps[-1]["detail"] = {"triples": count}
            else:
                with step("load"):
                    if plan.mode == "incremental" and not plan.changed and not plan.dropped:
                        count = 0
                        steps[-1]["detail"] = {"triples": 0, "skipped": True}
                    else:
                        count = self._load_tables(version_id, compiled, plan, on_rows)
                        steps[-1]["detail"] = {"triples": count}
            with step("finalize"):
                self.store.analyze()   # the planner must know the new rows, or graph queries on this version crawl
                counted = self.store.count(version_id)
                if not self.publish:
                    self.registry.save_build_state(version_id, mapping_hash, plan.signatures_after, _select_hashes(compiled))
            log.info("build succeeded: %d triples", counted, extra={"event": "build.succeeded", "triples": counted, **ctx})
            return self.registry.finish_build(run.id, status="succeeded", triple_count=counted, steps=steps)
        except BuildCancelled as exc:
            log.warning("build cancelled", extra={"event": "build.cancelled", **ctx})
            return self.registry.finish_build(run.id, status="cancelled", error=str(exc), steps=steps)
        except Exception as exc:  # noqa: BLE001 - every failure must be recorded on the run
            log.error("build failed: %s", exc, extra={"event": "build.failed", "error": str(exc), **ctx}, exc_info=True)
            return self.registry.finish_build(run.id, status="failed", error=f"{type(exc).__name__}: {exc}", steps=steps)

    # -- incremental planning and loading ----------------------------------------

    def _column_types(self, version_id: UUID):
        """Column types for the compiler: from the version's snapshot when it holds the table (no
        warehouse round trip), from the catalog otherwise."""
        live = self.source.catalog.resolver()
        if self.metadata is None:
            return live
        snaps = {s.table.lower(): {c["name"].lower(): c.get("type") for c in s.columns} for s in self.metadata.list(version_id)}

        def resolve(lt, column: str) -> str | None:
            if lt.table_name is not None and lt.table_name.lower() in snaps:
                return snaps[lt.table_name.lower()].get(column.lower())
            return live(lt, column)
        return resolve

    def _plan(self, version_id: UUID, compiled, mapping_hash: str, *, full: bool) -> "BuildPlan":
        """Which source tables must be read: all of them, or only those whose signature moved since the
        last successful load of this version with this mapping."""
        childs = list(dict.fromkeys(s.source_table for s in compiled.selects if s.source_table))
        deps: dict[str, set[str]] = {t: set() for t in childs}
        for sel in compiled.selects:
            if sel.source_table:
                deps[sel.source_table].update(sel.tables)
        every = sorted({t for ts in deps.values() for t in ts})
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(every)))) as pool:   # one statement per table: side by side, not in a row
            signatures = dict(zip(every, pool.map(self.source.table_signature, every)))
        state = self.registry.build_state(version_id)
        selects = _select_hashes(compiled)
        remapped = [t for t in childs if state and state["selects"].get(t) != selects[t]] if state and state.get("selects") else []
        dropped: list[str] = []
        if full:
            mode, reason = "full", "requested" if not self.publish else "published view"
        elif any(not s.tables for s in compiled.selects):
            mode, reason = "full", "query-based logical table"
        elif state is None:
            mode, reason = "full", "first build"
        elif state["mapping_hash"] != mapping_hash and not state.get("selects"):
            mode, reason = "full", "mapping changed"          # a state older than per-table select hashes: no way to tell which tables
        elif state["mapping_hash"] != mapping_hash:
            mode, reason = "incremental", f"mapping changed: {len(remapped)} table(s) re-mapped"
        else:
            mode, reason = "incremental", "signatures compared"
        if mode == "full":
            changed, unchanged = childs, []
        else:
            known = state["tables"]
            changed = [t for t in childs if t in remapped or any(signatures.get(d) is None or known.get(d) != signatures[d] for d in deps[t])]
            unchanged = [t for t in childs if t not in changed]
            dropped = sorted(t for t in state.get("selects", {}) if t not in childs)   # no select produces it any more: its triples go
        after = dict(state["tables"]) if state and mode == "incremental" else {}
        after.update({t: sig for t, sig in signatures.items() if sig is not None})
        return BuildPlan(mode, reason, changed, unchanged, after, dropped)

    def _load_tables(self, version_id: UUID, compiled, plan: "BuildPlan", on_rows: Callable[[int], None] | None = None) -> int:
        """Replace the triples of the changed source tables (every table on a full build) from a
        SELECT whose rows carry their source table as a seventh column."""
        d = self.source.dialect
        wanted = set(plan.changed)
        parts = [f"SELECT {', '.join(COLUMNS)}, {d.string_literal(s.source_table) if s.source_table else d.null_text()} AS source_table FROM (\n{s.sql}\n) AS t{i}"
                 for i, s in enumerate(compiled.selects) if plan.mode == "full" or s.source_table in wanted]
        sql = "\nUNION ALL\n".join(parts)
        tables = None if plan.mode == "full" else plan.changed + plan.dropped
        if not parts:                                   # only tables to drop: nothing to read
            return self.store.replace_tables(version_id, tables, iter(()))
        if isinstance(self.source, PostgresSource) and self.source.db is self.store.db:
            return self.store.replace_from_sql(version_id, sql, tables=tables, with_source=True)
        return self.store.replace_tables(version_id, tables, self._counted(self.source.stream(sql), on_rows))

    # -- overridable stages ---------------------------------------------------

    def _prepare(self) -> None:
        self.source.prepare()

    def _publish(self, version, sql: str) -> dict:
        """CREATE OR REPLACE VIEW <schema>.<domain>_v<n>_triples; optionally snapshot it into a TABLE."""
        cfg = self.publish
        domain = self.registry.get_domain_by_id(version.domain_id)
        base = f"{cfg.target_schema}.{safe_identifier(domain.name)}_v{version.version}_triples"
        view, table = base, (base + "_mat" if cfg.materialization == "table" else None)
        self.source.ensure_schema(cfg.target_schema)
        self.source.execute(f"CREATE OR REPLACE VIEW {self._quote(view)} AS\n{sql}")
        if table:
            for stmt in self.source.dialect.create_table_as(self._quote(table), f"SELECT * FROM {self._quote(view)}"):
                self.source.execute(stmt)
            for stmt in self.source.dialect.post_materialize_sql(self._quote(table)):
                self.source.execute(stmt)
        return {"view": view, "table": table, "materialization": cfg.materialization}

    def _quote(self, dotted: str) -> str:
        return self.source.dialect.quote_table(dotted)

    def _load(self, version_id: UUID, sql: str, on_rows: Callable[[int], None] | None = None) -> int:
        if isinstance(self.source, PostgresSource) and self.source.db is self.store.db:
            return self.store.replace_from_sql(version_id, sql)   # one server-side statement: no rows pass through here
        return self.store.replace(version_id, self._counted(self.source.stream(sql), on_rows))

    def _counted(self, rows: Iterable[tuple], on_rows: Callable[[int], None] | None) -> Iterator[tuple]:
        n = 0
        for row in rows:
            n += 1
            if on_rows and n % self.progress_rows == 0:
                on_rows(n)
            yield row

    @staticmethod
    def _r2rml(version):
        if version.mapping:
            return MappingSpec.from_dict(version.mapping).to_r2rml()
        if version.r2rml_ttl:
            return parse_r2rml(version.r2rml_ttl)
        raise BuildError("Version has neither a mapping spec nor an R2RML document")


def safe_identifier(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not ident or ident[0].isdigit():
        ident = "d_" + ident
    return ident


@dataclass(frozen=True)
class BuildPlan:
    mode: str                       # full | incremental
    reason: str
    changed: list[str]              # source tables to read
    unchanged: list[str]            # source tables left as they are
    signatures_after: dict[str, str]
    dropped: list[str] = field(default_factory=list)   # source tables no select produces any more: their triples are cleared


def _select_hashes(compiled) -> dict[str, str]:
    """Per source table, a hash of the SQL of the selects that produce its triples."""
    by_table: dict[str, list[str]] = {}
    for s in compiled.selects:
        if s.source_table:
            by_table.setdefault(s.source_table, []).append(s.sql)
    return {t: hashlib.sha256("\n".join(sorted(sqls)).encode()).hexdigest() for t, sqls in by_table.items()}


class _step:
    def __init__(self, steps: list[dict], name: str, on_start: Callable[[], None] | None = None,
                 on_done: Callable[[], None] | None = None) -> None:
        self.steps, self.name, self.on_start, self.on_done = steps, name, on_start, on_done

    def __enter__(self):
        self.t0 = time.perf_counter()
        self.steps.append({"name": self.name, "seconds": None})
        if self.on_start:
            self.on_start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.steps[-1]["seconds"] = round(time.perf_counter() - self.t0, 4)
        if exc is not None:
            self.steps[-1]["error"] = str(exc)
        if self.on_done:
            self.on_done()
        return False
