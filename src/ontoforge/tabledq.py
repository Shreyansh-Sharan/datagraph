"""Data-quality rules on source tables. A rule is one measurable statement about a table or a
column; every enabled rule of a table is compiled into one aggregate pass over the source, each
result is kept, and the table's score is the mean pass rate of its rules."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Callable
from uuid import UUID

from psycopg.types.json import Jsonb

from ontoforge.build.source import SourceEngine
from ontoforge.db import Database
from ontoforge.dialects import SqlDialect
from ontoforge.llm.prompts import SUGGEST_DQ_RULES
from ontoforge.llm.schemas import DQ_RULES_SCHEMA
from ontoforge.metadata import MetadataService
from ontoforge.registry import Registry
from ontoforge.registry.models import NotFound

KINDS = {"not_null": "completeness", "unique": "uniqueness", "in_set": "validity", "range": "validity", "regex": "validity",
         "referential": "consistency", "freshness": "timeliness", "row_count": "volume", "custom": "validity"}
DIMENSIONS = ("completeness", "uniqueness", "validity", "consistency", "timeliness", "volume")
NEEDS_COLUMN = {"not_null", "unique", "in_set", "range", "regex", "referential", "freshness"}
WARN_BAND = 0.15   # below the threshold by up to this much is a warning, further down is failing


class DqError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    id: UUID
    domain_version_id: UUID
    table_name: str
    name: str
    column_name: str | None
    kind: str
    dimension: str
    params: dict
    threshold: float
    owner: str | None
    origin: str
    enabled: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"], d["domain_version_id"] = str(self.id), str(self.domain_version_id)
        d["created_at"], d["updated_at"] = self.created_at.isoformat(), self.updated_at.isoformat()
        return d


@dataclass(frozen=True)
class Run:
    id: UUID
    domain_version_id: UUID
    table_name: str
    started_at: datetime
    finished_at: datetime | None
    actor: str | None
    score: float | None
    status: str
    error: str | None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"], d["domain_version_id"] = str(self.id), str(self.domain_version_id)
        d["started_at"] = self.started_at.isoformat()
        d["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        d["score"] = float(self.score) if self.score is not None else None
        return d


def rule_sql(rule: dict, d: SqlDialect) -> tuple[str, str | None]:
    """(pass-rate expression in [0, 1], failing-row count expression or None) for one rule, both aggregates."""
    kind, col, p = rule["kind"], rule.get("column_name"), rule.get("params") or {}
    q = d.quote_identifier(col) if col else None
    if kind == "unique":
        return f"{d.to_double(f'count(DISTINCT {q})')} / nullif(count({q}), 0)", f"count({q}) - count(DISTINCT {q})"
    if kind == "freshness":
        return f"CASE WHEN max({q}) >= {d.hours_ago(int(p.get('hours', 24)))} THEN 1.0 ELSE 0.0 END", None
    if kind == "row_count":
        conds = [f"count(*) >= {int(p['min'])}" for _ in [0] if p.get("min") is not None] + [f"count(*) <= {int(p['max'])}" for _ in [0] if p.get("max") is not None]
        return f"CASE WHEN {' AND '.join(conds) or 'TRUE'} THEN 1.0 ELSE 0.0 END", None
    if kind == "not_null":
        pred = f"{q} IS NOT NULL"
    elif kind == "in_set":
        values = ", ".join(d.string_literal(str(v)) for v in p.get("values", [])) or "NULL"
        pred = f"{q} IS NULL OR {d.to_text(q)} IN ({values})"
    elif kind == "range":
        parts = [f"{q} >= {d.literal(p['min'])}" for _ in [0] if p.get("min") is not None] + [f"{q} <= {d.literal(p['max'])}" for _ in [0] if p.get("max") is not None]
        pred = f"{q} IS NULL OR ({' AND '.join(parts) or 'TRUE'})"
    elif kind == "regex":
        pred = f"{q} IS NULL OR {d.regex_match(d.to_text(q), str(p.get('pattern', '')))}"
    elif kind == "referential":
        pred = f"{q} IS NULL OR {q} IN (SELECT {d.quote_identifier(p['ref_column'])} FROM {d.quote_table(p['ref_table'])})"
    elif kind == "custom":
        pred = str(p.get("predicate") or "TRUE").strip()
        if ";" in pred:
            raise DqError("A custom predicate is one boolean SQL expression, without ';'")
    else:
        raise DqError(f"Unknown rule kind {kind!r}; choose from {', '.join(KINDS)}")
    return f"{d.to_double(d.count_if(pred))} / nullif(count(*), 0)", f"count(*) - {d.count_if(pred)}"


def status_of(pass_rate: float | None, threshold: float) -> str:
    if pass_rate is None:
        return "error"
    if pass_rate >= threshold:
        return "passing"
    return "warning" if pass_rate >= threshold - WARN_BAND else "failing"


class TableQuality:
    def __init__(self, registry: Registry, metadata: MetadataService, source: "SourceEngine | Callable[[UUID], SourceEngine]", db: Database) -> None:
        self.registry, self.metadata, self._source, self.db = registry, metadata, source, db

    def source_for(self, version_id: UUID) -> SourceEngine:
        return self._source(version_id) if callable(self._source) else self._source

    # -- rules -----------------------------------------------------------------------------------

    def list_rules(self, version_id: UUID, table: str) -> list[Rule]:
        with self.db.rows() as cur:
            return [_rule(r) for r in cur.execute("SELECT * FROM dq_rules WHERE domain_version_id = %s AND table_name = %s ORDER BY created_at, id",
                                                  (version_id, table)).fetchall()]

    def get_rule(self, rule_id: UUID) -> Rule:
        with self.db.rows() as cur:
            row = cur.execute("SELECT * FROM dq_rules WHERE id = %s", (rule_id,)).fetchone()
        if not row:
            raise NotFound(f"Rule {rule_id}")
        return _rule(row)

    def add_rule(self, version_id: UUID, table: str, *, actor: str, name: str, kind: str, column: str | None = None, params: dict | None = None,
                 dimension: str | None = None, threshold: float = 0.95, owner: str | None = None, origin: str = "manual", enabled: bool = True) -> Rule:
        self.registry.assert_editable(version_id, actor)
        fields = self._validate(version_id, table, name=name, kind=kind, column=column, params=params or {}, dimension=dimension, threshold=threshold)
        with self.db.rows() as cur:
            row = cur.execute(
                "INSERT INTO dq_rules (domain_version_id, table_name, name, column_name, kind, dimension, params, threshold, owner, origin, enabled, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (version_id, table, fields["name"], fields["column"], fields["kind"], fields["dimension"], Jsonb(fields["params"]), fields["threshold"],
                 owner, origin, enabled, actor)).fetchone()
        return _rule(row)

    def update_rule(self, rule_id: UUID, *, actor: str, **changes) -> Rule:
        rule = self.get_rule(rule_id)
        self.registry.assert_editable(rule.domain_version_id, actor)
        merged = {"name": rule.name, "kind": rule.kind, "column": rule.column_name, "params": rule.params, "dimension": rule.dimension, "threshold": rule.threshold}
        merged.update({k: v for k, v in changes.items() if k in merged})
        if "column_name" in changes:
            merged["column"] = changes["column_name"]
        fields = self._validate(rule.domain_version_id, rule.table_name, **merged)
        with self.db.rows() as cur:
            row = cur.execute(
                "UPDATE dq_rules SET name = %s, column_name = %s, kind = %s, dimension = %s, params = %s, threshold = %s, owner = %s, enabled = %s, updated_at = now() "
                "WHERE id = %s RETURNING *",
                (fields["name"], fields["column"], fields["kind"], fields["dimension"], Jsonb(fields["params"]), fields["threshold"],
                 changes.get("owner", rule.owner), bool(changes.get("enabled", rule.enabled)), rule_id)).fetchone()
        return _rule(row)

    def delete_rule(self, rule_id: UUID, *, actor: str) -> None:
        rule = self.get_rule(rule_id)
        self.registry.assert_editable(rule.domain_version_id, actor)
        with self.db.rows() as cur:
            cur.execute("DELETE FROM dq_rules WHERE id = %s", (rule_id,))

    def _validate(self, version_id: UUID, table: str, *, name: str, kind: str, column: str | None, params: dict, dimension: str | None, threshold: float) -> dict:
        if not name or not name.strip():
            raise DqError("A rule needs a name")
        if kind not in KINDS:
            raise DqError(f"Unknown rule kind {kind!r}; choose from {', '.join(KINDS)}")
        snap = self.metadata.get(version_id, table)
        if kind in NEEDS_COLUMN:
            if not column:
                raise DqError(f"A {kind} rule needs a column")
            found = snap.column(column)
            if found is None:
                raise DqError(f"Unknown column {column!r} on {table}")
            column = found["name"]
        elif column and snap.column(column) is None:
            raise DqError(f"Unknown column {column!r} on {table}")
        if kind == "referential" and not (params.get("ref_table") and params.get("ref_column")):
            raise DqError("A referential rule needs ref_table and ref_column")
        if kind == "in_set" and not params.get("values"):
            raise DqError("An in_set rule needs a list of values")
        if kind == "regex" and not params.get("pattern"):
            raise DqError("A regex rule needs a pattern")
        dimension = dimension or KINDS[kind]
        if dimension not in DIMENSIONS:
            raise DqError(f"Unknown dimension {dimension!r}; choose from {', '.join(DIMENSIONS)}")
        if not 0 < float(threshold) <= 1:
            raise DqError("The threshold is a fraction between 0 and 1")
        return {"name": name.strip(), "kind": kind, "column": column, "params": params, "dimension": dimension, "threshold": float(threshold)}

    # -- running ---------------------------------------------------------------------------------

    def run(self, version_id: UUID, table: str, *, actor: str | None = None, on_progress: Callable[[str], None] | None = None) -> Run:
        say = on_progress or (lambda _m: None)
        self.metadata.get(version_id, table)
        rules = [r for r in self.list_rules(version_id, table) if r.enabled]
        src = self.source_for(version_id)
        d = src.dialect
        tq = d.quote_table(table)
        with self.db.rows() as cur:
            run_id = cur.execute("INSERT INTO dq_runs (domain_version_id, table_name, actor) VALUES (%s, %s, %s) RETURNING id", (version_id, table, actor)).fetchone()["id"]
        results: dict[UUID, dict] = {}

        def measure(subset: list[Rule]) -> None:
            exprs, plan = ["count(*)"], []
            for r in subset:
                p, f = rule_sql(r.to_dict(), d)
                exprs += [p, f or "NULL"]
                plan.append(r)
            _, rows = src.query(f"SELECT {', '.join(exprs)} FROM {tq}", 1)
            row = list(rows[0]) if rows else [0]
            total = int(row[0] or 0)
            for i, r in enumerate(plan):
                p, f = row[1 + 2 * i], row[2 + 2 * i]
                rate = None if p is None else max(0.0, min(1.0, float(p)))
                failed = None if f is None else int(f)
                results[r.id] = {"pass_rate": rate, "passed": (total - failed) if failed is not None else None, "failed": failed, "total": total,
                                 "status": status_of(rate, r.threshold), "error": None}

        try:
            if rules:
                say(f"Running {len(rules)} rule{'s' if len(rules) != 1 else ''} on {table}")
                try:
                    measure(rules)
                except Exception:  # noqa: BLE001 - one bad rule must not hide the others: measure each alone
                    for r in rules:
                        try:
                            measure([r])
                        except Exception as exc:  # noqa: BLE001
                            results[r.id] = {"pass_rate": None, "passed": None, "failed": None, "total": None, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
            rates = [x["pass_rate"] for x in results.values() if x["pass_rate"] is not None]
            score = round(mean(rates), 4) if rates else None
            with self.db.rows() as cur:
                for r in rules:
                    x = results[r.id]
                    cur.execute("INSERT INTO dq_results (run_id, rule_id, pass_rate, passed, failed, total, status, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                                (run_id, r.id, x["pass_rate"], x["passed"], x["failed"], x["total"], x["status"], x["error"]))
                row = cur.execute("UPDATE dq_runs SET finished_at = now(), score = %s, status = 'succeeded' WHERE id = %s RETURNING *", (score, run_id)).fetchone()
        except Exception as exc:  # noqa: BLE001 - the run records its own failure
            with self.db.rows() as cur:
                row = cur.execute("UPDATE dq_runs SET finished_at = now(), status = 'failed', error = %s WHERE id = %s RETURNING *", (f"{type(exc).__name__}: {exc}", run_id)).fetchone()
        return _run(row)

    def status(self, version_id: UUID, table: str) -> dict:
        """Everything the data-quality screen shows: rules with their latest result, the table's score
        and its history, per-column scores (rules first, the profile's completeness otherwise)."""
        snap = self.metadata.get(version_id, table)
        rules = self.list_rules(version_id, table)
        with self.db.rows() as cur:
            runs = [_run(r) for r in cur.execute("SELECT * FROM dq_runs WHERE domain_version_id = %s AND table_name = %s ORDER BY started_at DESC LIMIT 14",
                                                 (version_id, table)).fetchall()][::-1]
            latest = {r["rule_id"]: r for r in cur.execute(
                "SELECT DISTINCT ON (rule_id) * FROM dq_results WHERE rule_id = ANY(%s) ORDER BY rule_id, ran_at DESC, id DESC", ([r.id for r in rules],)).fetchall()}
            prof = cur.execute("SELECT columns FROM table_profiles WHERE domain_version_id = %s AND table_name = %s", (version_id, table)).fetchone()
        last_run = next((r for r in reversed(runs) if r.status != "running"), None)
        out_rules = []
        for r in rules:
            x = latest.get(r.id)
            last = None if x is None else {"pass_rate": _f(x["pass_rate"]), "passed": x["passed"], "failed": x["failed"], "total": x["total"], "status": x["status"],
                                           "error": x["error"], "ran_at": x["ran_at"].isoformat()}
            out_rules.append({**r.to_dict(), "last": last})
        by_col: dict[str, list[float]] = {}
        for r in out_rules:
            if r["enabled"] and r["column_name"] and r["last"] and r["last"]["pass_rate"] is not None:
                by_col.setdefault(r["column_name"].lower(), []).append(r["last"]["pass_rate"])
        completeness = {c["name"].lower(): 1 - float(c["null_rate"]) for c in (prof["columns"] if prof else [])}
        columns = []
        for c in snap.columns:
            key = c["name"].lower()
            if key in by_col:
                columns.append({"name": c["name"], "score": round(mean(by_col[key]), 4), "source": "rules"})
            elif key in completeness:
                columns.append({"name": c["name"], "score": round(completeness[key], 4), "source": "profile"})
            else:
                columns.append({"name": c["name"], "score": None, "source": None})
        summary = {"passing": 0, "warning": 0, "failing": 0}
        for r in out_rules:
            if r["enabled"] and r["last"] and r["last"]["status"] in summary:
                summary[r["last"]["status"]] += 1
        return {"table": table, "score": _f(last_run.score) if last_run else None, "last_run": last_run.to_dict() if last_run else None,
                "history": [{"id": str(r.id), "started_at": r.started_at.isoformat(), "score": _f(r.score), "status": r.status} for r in runs],
                "rules": out_rules, "columns": columns, "summary": summary}

    # -- AI --------------------------------------------------------------------------------------

    def suggest(self, version_id: UUID, table: str, llm, *, actor: str, on_progress: Callable[[str], None] | None = None) -> dict:
        say = on_progress or (lambda _m: None)
        self.registry.assert_editable(version_id, actor)
        snap = self.metadata.get(version_id, table)
        with self.db.rows() as cur:
            prof = cur.execute("SELECT columns FROM table_profiles WHERE domain_version_id = %s AND table_name = %s", (version_id, table)).fetchone()
        profile = {c["name"]: c for c in (prof["columns"] if prof else [])}
        lines = []
        for c in snap.columns:
            p = profile.get(c["name"])
            facts = f" (null rate {float(p['null_rate']):.1%}, {p['distinct']} distinct, range {p['min']}..{p['max']}, top {p['top']!r})" if p else ""
            lines.append(f"- {c['name']} {c.get('type') or ''}{': ' + c['comment'] if c.get('comment') else ''}{facts}")
        existing = ", ".join(f"{r.kind} on {r.column_name}" for r in self.list_rules(version_id, table)) or "none"
        user = f"Table {table}" + (f" (primary key {', '.join(snap.primary_key)})" if snap.primary_key else "") + "\nColumns:\n" + "\n".join(lines) + f"\nRules already defined: {existing}."
        say(f"Asking the AI provider for rules on {table}")
        data = llm.complete_json(SUGGEST_DQ_RULES, user, DQ_RULES_SCHEMA)
        added, skipped = [], []
        for s in data.get("rules", []):
            kind, column = s.get("kind"), s.get("column")
            if kind not in KINDS:
                skipped.append(f"{s.get('name')} (unknown kind {kind})"); continue
            if column and snap.column(column) is None:
                skipped.append(f"{s.get('name')} (unknown column {column})"); continue
            try:
                params = {k: v for k, v in (s.get("params") or {}).items() if v is not None}
                rule = self.add_rule(version_id, table, actor=actor, name=s.get("name") or f"{kind} on {column}", kind=kind, column=column,
                                     params=params, threshold=float(s.get("threshold") or 0.95), origin="ai")
                added.append(rule.to_dict())
            except (DqError, ValueError) as exc:
                skipped.append(f"{s.get('name')} ({exc})")
        return {"added": len(added), "skipped": skipped, "rules": added}


def _rule(row: dict) -> Rule:
    return Rule(row["id"], row["domain_version_id"], row["table_name"], row["name"], row["column_name"], row["kind"], row["dimension"], row["params"] or {},
                float(row["threshold"]), row["owner"], row["origin"], row["enabled"], row["created_by"], row["created_at"], row["updated_at"])


def _run(row: dict) -> Run:
    return Run(row["id"], row["domain_version_id"], row["table_name"], row["started_at"], row["finished_at"], row["actor"],
               float(row["score"]) if row["score"] is not None else None, row["status"], row["error"])


def _f(v) -> float | None:
    return None if v is None else round(float(v), 4)
