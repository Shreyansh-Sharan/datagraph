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

def _p(name: str, type_: str, required: bool = False, help: str = "") -> dict:
    return {"name": name, "type": type_, "required": required, "help": help}


FILTER = _p("filter", "sql", False, "Optional SQL condition: rows outside it are not checked (they count as passing).")
# The catalogue of rule kinds, in the spirit of DQX's check functions: each names its quality dimension, whether
# it judges rows or the whole table, whether it needs a column, and its parameters. It is what the API, the MCP
# tools and the screens offer; rule_sql compiles every kind for Postgres and Databricks alike.
KIND_CATALOG: list[dict] = [
    {"kind": "not_null", "label": "Not null", "dimension": "completeness", "level": "row", "column": True, "dqx": "is_not_null", "params": [FILTER], "help": "Every row has a value."},
    {"kind": "not_empty", "label": "Not null and not empty", "dimension": "completeness", "level": "row", "column": True, "dqx": "is_not_null_and_not_empty", "params": [FILTER], "help": "Every row has a value that is not blank once trimmed."},
    {"kind": "unique", "label": "Unique", "dimension": "uniqueness", "level": "table", "column": False, "dqx": "is_unique",
     "params": [_p("columns", "list", False, "The columns that together identify a row; the rule's column alone when omitted.")], "help": "No two rows share the value (or the combination of values)."},
    {"kind": "in_set", "label": "Value in allowed set", "dimension": "validity", "level": "row", "column": True, "dqx": "is_in_list", "params": [_p("values", "list", True, "The allowed values."), FILTER], "help": "Values (when present) are one of the allowed ones."},
    {"kind": "not_in_set", "label": "Value not in forbidden set", "dimension": "validity", "level": "row", "column": True, "dqx": "is_not_in_list", "params": [_p("values", "list", True, "The forbidden values."), FILTER], "help": "Values are never one of the forbidden ones."},
    {"kind": "range", "label": "Value within range", "dimension": "validity", "level": "row", "column": True, "dqx": "is_in_range", "params": [_p("min", "number"), _p("max", "number"), FILTER], "help": "Values (when present) lie between min and max, inclusive; give at least one bound."},
    {"kind": "not_in_range", "label": "Value outside range", "dimension": "validity", "level": "row", "column": True, "dqx": "is_not_in_range", "params": [_p("min", "number", True), _p("max", "number", True), FILTER], "help": "Values never fall between min and max."},
    {"kind": "equal_to", "label": "Equal to a value", "dimension": "validity", "level": "row", "column": True, "dqx": "is_equal_to", "params": [_p("value", "scalar", True), FILTER], "help": "Values (when present) equal the given value."},
    {"kind": "not_equal_to", "label": "Not equal to a value", "dimension": "validity", "level": "row", "column": True, "dqx": "is_not_equal_to", "params": [_p("value", "scalar", True), FILTER], "help": "Values never equal the given value."},
    {"kind": "not_less_than", "label": "Not less than", "dimension": "validity", "level": "row", "column": True, "dqx": "is_not_less_than", "params": [_p("limit", "number", True), FILTER], "help": "Values (when present) are at least the limit."},
    {"kind": "not_greater_than", "label": "Not greater than", "dimension": "validity", "level": "row", "column": True, "dqx": "is_not_greater_than", "params": [_p("limit", "number", True), FILTER], "help": "Values (when present) are at most the limit."},
    {"kind": "regex", "label": "Matches a pattern", "dimension": "validity", "level": "row", "column": True, "dqx": "regex_match", "params": [_p("pattern", "regex", True, "A regular expression the text must match."), FILTER], "help": "Values (when present) match the pattern."},
    {"kind": "valid_email", "label": "Valid email address", "dimension": "validity", "level": "row", "column": True, "dqx": "is_valid_email", "params": [FILTER], "help": "Values (when present) look like an email address."},
    {"kind": "valid_uuid", "label": "Valid UUID", "dimension": "validity", "level": "row", "column": True, "dqx": "is_valid_uuid", "params": [FILTER], "help": "Values (when present) are UUIDs."},
    {"kind": "valid_ipv4", "label": "Valid IPv4 address", "dimension": "validity", "level": "row", "column": True, "dqx": "is_valid_ipv4_address", "params": [FILTER], "help": "Values (when present) are IPv4 addresses."},
    {"kind": "valid_date", "label": "Valid date", "dimension": "validity", "level": "row", "column": True, "dqx": "is_valid_date", "params": [FILTER], "help": "Values (when present) read as ISO dates, YYYY-MM-DD."},
    {"kind": "valid_timestamp", "label": "Valid timestamp", "dimension": "validity", "level": "row", "column": True, "dqx": "is_valid_timestamp", "params": [FILTER], "help": "Values (when present) read as ISO timestamps, YYYY-MM-DD hh:mm."},
    {"kind": "string_case", "label": "Letter case", "dimension": "validity", "level": "row", "column": True, "dqx": "has_valid_string_case", "params": [_p("case", "enum:upper,lower", True), FILTER], "help": "Text values are all upper case or all lower case."},
    {"kind": "length_between", "label": "Text length within range", "dimension": "validity", "level": "row", "column": True, "dqx": "sql_expression", "params": [_p("min", "number"), _p("max", "number"), FILTER], "help": "Text length lies between min and max characters."},
    {"kind": "not_in_future", "label": "Not in the future", "dimension": "timeliness", "level": "row", "column": True, "dqx": "is_not_in_future", "params": [FILTER], "help": "Dates and timestamps are not later than now."},
    {"kind": "older_than_days", "label": "Older than N days", "dimension": "timeliness", "level": "row", "column": True, "dqx": "is_older_than_n_days", "params": [_p("days", "number", True), FILTER], "help": "Dates are at least N days in the past."},
    {"kind": "older_than_column", "label": "Older than another column", "dimension": "consistency", "level": "row", "column": True, "dqx": "is_older_than_col2_for_n_days",
     "params": [_p("column2", "column", True, "The later date."), _p("days", "number", False, "By at least this many days (0 by default)."), FILTER], "help": "The column's date precedes the other column's date."},
    {"kind": "referential", "label": "Referential integrity", "dimension": "consistency", "level": "row", "column": True, "dqx": "foreign_key",
     "params": [_p("ref_table", "table", True), _p("ref_column", "column", True), FILTER], "help": "Values (when present) exist in the referenced table's column."},
    {"kind": "freshness", "label": "Freshness", "dimension": "timeliness", "level": "table", "column": True, "dqx": "is_data_fresh", "params": [_p("hours", "number", False, "24 by default.")], "help": "The newest value is at most N hours old."},
    {"kind": "row_count", "label": "Row count within range", "dimension": "volume", "level": "table", "column": False, "dqx": "is_aggr_not_less_than", "params": [_p("min", "number"), _p("max", "number")], "help": "The table has between min and max rows."},
    {"kind": "aggregate", "label": "Aggregate within limit", "dimension": "volume", "level": "table", "column": False, "dqx": "is_aggr_not_greater_than",
     "params": [_p("aggr", "enum:count,count_distinct,sum,avg,min,max", True), _p("column", "column", False, "The column to aggregate (count needs none)."), _p("op", "enum:<=,>=,=,!=,<,>", True), _p("limit", "number", True)],
     "help": "An aggregate of the table (sum, average, count...) compares as stated with the limit."},
    {"kind": "custom", "label": "Custom predicate", "dimension": "validity", "level": "row", "column": False, "dqx": "sql_expression", "params": [_p("predicate", "sql", True, "One boolean SQL expression over the row."), FILTER], "help": "Every row satisfies the SQL condition."},
]
KINDS = {k["kind"]: k["dimension"] for k in KIND_CATALOG}
DIMENSIONS = ("completeness", "uniqueness", "validity", "consistency", "timeliness", "volume")
NEEDS_COLUMN = {k["kind"] for k in KIND_CATALOG if k["column"]}
_REQUIRED = {k["kind"]: [p["name"] for p in k["params"] if p["required"]] for k in KIND_CATALOG}
_PATTERNS = {"valid_email": r"^[^@\s]+@[^@\s]+\.[^@\s]+$", "valid_uuid": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
             "valid_ipv4": r"^((25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])$", "valid_date": r"^\d{4}-\d{2}-\d{2}", "valid_timestamp": r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"}
_AGGRS = ("count", "count_distinct", "sum", "avg", "min", "max")
_OPS = ("<=", ">=", "=", "!=", "<", ">")
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


def _unique_cols(rule: dict, d: SqlDialect) -> list[str]:
    cols = [str(c) for c in (rule.get("params") or {}).get("columns") or []] or ([rule["column_name"]] if rule.get("column_name") else [])
    if not cols:
        raise DqError("A unique rule needs a column, or params.columns")
    return [d.quote_identifier(c) for c in cols]


def _row_predicate(rule: dict, d: SqlDialect) -> str:
    """The boolean a row must satisfy for a row-level kind (nulls pass where the kind is about present values)."""
    kind, col, p = rule["kind"], rule.get("column_name"), rule.get("params") or {}
    q = d.quote_identifier(col) if col else None
    if kind == "not_null":
        return f"{q} IS NOT NULL"
    if kind == "not_empty":
        return f"{q} IS NOT NULL AND trim({d.to_text(q)}) <> ''"
    if kind == "in_set":
        values = ", ".join(d.string_literal(str(v)) for v in p.get("values", [])) or "NULL"
        return f"{q} IS NULL OR {d.to_text(q)} IN ({values})"
    if kind == "not_in_set":
        values = ", ".join(d.string_literal(str(v)) for v in p.get("values", [])) or "NULL"
        return f"{q} IS NULL OR {d.to_text(q)} NOT IN ({values})"
    if kind == "range":
        parts = [f"{q} >= {d.literal(p['min'])}" for _ in [0] if p.get("min") is not None] + [f"{q} <= {d.literal(p['max'])}" for _ in [0] if p.get("max") is not None]
        return f"{q} IS NULL OR ({' AND '.join(parts) or 'TRUE'})"
    if kind == "not_in_range":
        return f"{q} IS NULL OR {q} < {d.literal(p['min'])} OR {q} > {d.literal(p['max'])}"
    if kind == "equal_to":
        return f"{q} IS NULL OR {q} = {d.literal(p['value'])}"
    if kind == "not_equal_to":
        return f"{q} IS NULL OR {q} <> {d.literal(p['value'])}"
    if kind == "not_less_than":
        return f"{q} IS NULL OR {q} >= {d.literal(p['limit'])}"
    if kind == "not_greater_than":
        return f"{q} IS NULL OR {q} <= {d.literal(p['limit'])}"
    if kind == "regex":
        return f"{q} IS NULL OR {d.regex_match(d.to_text(q), str(p.get('pattern', '')))}"
    if kind in _PATTERNS:
        return f"{q} IS NULL OR {d.regex_match(d.to_text(q), _PATTERNS[kind])}"
    if kind == "string_case":
        fn = "upper" if str(p.get("case", "upper")).lower() == "upper" else "lower"
        return f"{q} IS NULL OR {d.to_text(q)} = {fn}({d.to_text(q)})"
    if kind == "length_between":
        parts = [f"length({d.to_text(q)}) >= {int(p['min'])}" for _ in [0] if p.get("min") is not None] + [f"length({d.to_text(q)}) <= {int(p['max'])}" for _ in [0] if p.get("max") is not None]
        return f"{q} IS NULL OR ({' AND '.join(parts) or 'TRUE'})"
    if kind == "not_in_future":
        return f"{q} IS NULL OR {q} <= {d.hours_ago(0)}"
    if kind == "older_than_days":
        return f"{q} IS NULL OR {q} <= {d.hours_ago(24 * int(p.get('days', 0)))}"
    if kind == "older_than_column":
        q2 = d.quote_identifier(str(p["column2"]))
        return f"{q} IS NULL OR {q2} IS NULL OR {q} <= {d.days_before(q2, int(p.get('days', 0) or 0))}"
    if kind == "referential":
        return f"{q} IS NULL OR {q} IN (SELECT {d.quote_identifier(p['ref_column'])} FROM {d.quote_table(p['ref_table'])})"
    if kind == "custom":
        pred = str(p.get("predicate") or "TRUE").strip()
        if ";" in pred:
            raise DqError("A custom predicate is one boolean SQL expression, without ';'")
        return pred
    raise DqError(f"Unknown rule kind {kind!r}; choose from {', '.join(KINDS)}")


def rule_sql(rule: dict, d: SqlDialect) -> tuple[str, str | None]:
    """(pass-rate expression in [0, 1], failing-row count expression or None) for one rule, both aggregates."""
    kind, col, p = rule["kind"], rule.get("column_name"), rule.get("params") or {}
    q = d.quote_identifier(col) if col else None
    if kind == "unique":
        cols = _unique_cols(rule, d)
        present = f"count({cols[0]})" if len(cols) == 1 else "count(*)"
        return f"{d.to_double(d.distinct_count(cols))} / nullif({present}, 0)", f"{present} - {d.distinct_count(cols)}"
    if kind == "freshness":
        return f"CASE WHEN max({q}) >= {d.hours_ago(int(p.get('hours', 24)))} THEN 1.0 ELSE 0.0 END", None
    if kind == "row_count":
        conds = [f"count(*) >= {int(p['min'])}" for _ in [0] if p.get("min") is not None] + [f"count(*) <= {int(p['max'])}" for _ in [0] if p.get("max") is not None]
        return f"CASE WHEN {' AND '.join(conds) or 'TRUE'} THEN 1.0 ELSE 0.0 END", None
    if kind == "aggregate":
        aggr, op = str(p.get("aggr", "count")).lower(), str(p.get("op", "<="))
        if aggr not in _AGGRS or op not in _OPS:
            raise DqError(f"An aggregate rule uses aggr in {', '.join(_AGGRS)} and op in {', '.join(_OPS)}")
        target = d.quote_identifier(str(p["column"])) if p.get("column") else None
        if aggr != "count" and not target:
            raise DqError(f"An aggregate rule with {aggr} needs a column")
        expr = "count(*)" if aggr == "count" and not target else f"count({target})" if aggr == "count" else f"count(DISTINCT {target})" if aggr == "count_distinct" else f"{aggr}({target})"
        return f"CASE WHEN {expr} {'<>' if op == '!=' else op} {d.literal(p['limit'])} THEN 1.0 ELSE 0.0 END", None
    pred = _row_predicate(rule, d)
    if p.get("filter"):
        flt = str(p["filter"]).strip()
        if ";" in flt:
            raise DqError("A filter is one boolean SQL expression, without ';'")
        pred = f"NOT ({flt}) OR ({pred})"
    return f"{d.to_double(d.count_if(pred))} / nullif(count(*), 0)", f"count(*) - {d.count_if(pred)}"


def failing_predicate(rule: dict, d: SqlDialect, table_sql: str) -> str:
    """A WHERE clause selecting the rows that break a row-level rule; DqError for table-level rules."""
    kind = rule["kind"]
    if kind == "unique":
        cols = _unique_cols(rule, d)
        tup = cols[0] if len(cols) == 1 else f"({', '.join(cols)})"
        notnull = " AND ".join(f"{c} IS NOT NULL" for c in cols)
        return f"{tup} IN (SELECT {', '.join(cols)} FROM {table_sql} WHERE {notnull} GROUP BY {', '.join(cols)} HAVING count(*) > 1)"
    if kind in ("freshness", "row_count", "aggregate"):
        raise DqError(f"A {kind.replace('_', ' ')} rule is about the whole table: it has no failing rows")
    pred = _row_predicate(rule, d)
    p = rule.get("params") or {}
    if p.get("filter"):
        return f"({str(p['filter']).strip()}) AND NOT ({pred})"
    return f"NOT ({pred})"


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
        missing = [k for k in _REQUIRED[kind] if params.get(k) in (None, "", [])]
        if missing:
            raise DqError(f"A {kind} rule needs {' and '.join(missing)}")
        if kind == "range" and params.get("min") is None and params.get("max") is None:
            raise DqError("A range rule needs min or max")
        if kind == "unique" and not column and not params.get("columns"):
            raise DqError("A unique rule needs a column or params.columns")
        for c in list(params.get("columns") or []) + ([params["column2"]] if kind == "older_than_column" else []) + ([params["column"]] if kind == "aggregate" and params.get("column") else []):
            if snap.column(str(c)) is None:
                raise DqError(f"Unknown column {c!r} on {table}")
        dimension = dimension or KINDS[kind]
        if dimension not in DIMENSIONS:
            raise DqError(f"Unknown dimension {dimension!r}; choose from {', '.join(DIMENSIONS)}")
        if not 0 < float(threshold) <= 1:
            raise DqError("The threshold is a fraction between 0 and 1")
        return {"name": name.strip(), "kind": kind, "column": column, "params": params, "dimension": dimension, "threshold": float(threshold)}

    def failures(self, rule_id: UUID, limit: int = 20) -> tuple[list[str], list[tuple]]:
        """A sample of the source rows that break the rule: (column names, rows)."""
        rule = self.get_rule(rule_id)
        src = self.source_for(rule.domain_version_id)
        d = src.dialect
        tq = d.quote_table(rule.table_name)
        where = failing_predicate(rule.to_dict(), d, tq)
        return src.query(f"SELECT * FROM {tq} WHERE {where}", max(1, min(int(limit), 200)))

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
            history: dict = {}
            for h in cur.execute("SELECT rule_id, pass_rate, ran_at FROM (SELECT rule_id, pass_rate, ran_at, row_number() OVER (PARTITION BY rule_id ORDER BY ran_at DESC, id DESC) AS rn "
                                 "FROM dq_results WHERE rule_id = ANY(%s)) x WHERE rn <= 14 ORDER BY ran_at", ([r.id for r in rules],)).fetchall():
                history.setdefault(h["rule_id"], []).append({"pass_rate": _f(h["pass_rate"]), "ran_at": h["ran_at"].isoformat()})
        last_run = next((r for r in reversed(runs) if r.status != "running"), None)
        out_rules = []
        for r in rules:
            x = latest.get(r.id)
            last = None if x is None else {"pass_rate": _f(x["pass_rate"]), "passed": x["passed"], "failed": x["failed"], "total": x["total"], "status": x["status"],
                                           "error": x["error"], "ran_at": x["ran_at"].isoformat()}
            out_rules.append({**r.to_dict(), "last": last, "history": history.get(r.id, [])})
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

    def overview(self, version_id: UUID) -> dict:
        """Every table that has rules, with its latest score and rule summary, and every rule with its last result."""
        with self.db.rows() as cur:
            rules = [_rule(r) for r in cur.execute("SELECT * FROM dq_rules WHERE domain_version_id = %s ORDER BY table_name, name", (version_id,)).fetchall()]
            runs = {r["table_name"]: r for r in cur.execute(
                "SELECT DISTINCT ON (table_name) * FROM dq_runs WHERE domain_version_id = %s AND status <> 'running' ORDER BY table_name, started_at DESC", (version_id,)).fetchall()}
            latest = {r["rule_id"]: r for r in cur.execute(
                "SELECT DISTINCT ON (rule_id) * FROM dq_results WHERE rule_id = ANY(%s) ORDER BY rule_id, ran_at DESC, id DESC", ([r.id for r in rules],)).fetchall()} if rules else {}
        out_rules, tables = [], {}
        for r in rules:
            x = latest.get(r.id)
            last = None if x is None else {"pass_rate": _f(x["pass_rate"]), "passed": x["passed"], "failed": x["failed"], "total": x["total"], "status": x["status"], "error": x["error"], "ran_at": x["ran_at"].isoformat()}
            out_rules.append({**r.to_dict(), "last": last})
            t = tables.setdefault(r.table_name, {"table": r.table_name, "rules": 0, "enabled": 0, "kinds": {}, "dimensions": {}, "summary": {"passing": 0, "warning": 0, "failing": 0, "error": 0}})
            t["rules"] += 1
            t["enabled"] += int(r.enabled)
            t["kinds"][r.kind] = t["kinds"].get(r.kind, 0) + 1
            t["dimensions"][r.dimension] = t["dimensions"].get(r.dimension, 0) + 1
            if r.enabled and last and last["status"] in t["summary"]:
                t["summary"][last["status"]] += 1
        for name, t in tables.items():
            run = runs.get(name)
            t["score"] = _f(run["score"]) if run else None
            t["last_run_at"] = run["started_at"].isoformat() if run else None
            t["last_run_status"] = run["status"] if run else None
        return {"tables": sorted(tables.values(), key=lambda t: t["table"]), "rules": out_rules, "kinds": KIND_CATALOG}

    # -- from the profile, without the AI --------------------------------------------------------

    def auto_suggest(self, version_id: UUID, table: str, *, actor: str) -> dict:
        """Rules the profile itself justifies: keys unique and present, never-null columns present,
        small code sets, numeric ranges widened by a tenth, GUID patterns, a row-count band."""
        self.registry.assert_editable(version_id, actor)
        snap = self.metadata.get(version_id, table)
        with self.db.rows() as cur:
            prof = cur.execute("SELECT row_count, columns FROM table_profiles WHERE domain_version_id = %s AND table_name = %s", (version_id, table)).fetchone()
        if not prof:
            raise DqError(f"Profile {table} first: the suggestions are read from its profile")
        rows = int(prof["row_count"] or 0)
        have = {(r.kind, (r.column_name or "").lower()) for r in self.list_rules(version_id, table)}
        proposals: list[dict] = []

        def propose(name: str, kind: str, column: str | None, params: dict | None = None, threshold: float = 0.99) -> None:
            proposals.append({"name": name, "kind": kind, "column": column, "params": params or {}, "threshold": threshold})

        for c in prof["columns"]:
            name, kind, nulls, distinct = c["name"], c.get("kind"), int(c.get("nulls") or 0), c.get("distinct")
            non_null = int(c.get("non_null") or 0)
            if c.get("role") == "row key":
                propose(f"{name} unique", "unique", name, threshold=1.0)
                propose(f"{name} present", "not_null", name, threshold=1.0)
                continue
            if nulls == 0 and non_null > 0:
                propose(f"{name} present", "not_null", name)
            values = [v["value"] for v in (c.get("values") or [])]
            if kind == "categorical" and values and distinct is not None and distinct <= 12 and non_null and distinct / non_null < 0.5:
                propose(f"{name} in its known set", "in_set", name, {"values": values})
            if kind == "numeric":
                lo, hi = _num(c.get("min")), _num(c.get("max"))
                if lo is not None and hi is not None and hi >= lo:
                    pad = (hi - lo) * 0.1 or abs(hi) * 0.1 or 1.0
                    low = max(0.0, lo - pad) if lo >= 0 else lo - pad
                    propose(f"{name} within range", "range", name, {"min": _tidy(low), "max": _tidy(hi + pad)})
            if kind == "categorical" and c.get("top") and _GUID.match(str(c["top"])) and (c.get("unique_pct") or 0) > 0.9:
                propose(f"{name} is a GUID", "regex", name, {"pattern": _GUID.pattern})
            if kind == "date" and c.get("max"):
                last = _date(c["max"])
                if last is not None and (datetime.now(timezone.utc) - last).days <= 30 and any(k in name.lower() for k in ("modif", "updat", "load", "ingest")):
                    propose(f"{name} fresh within 2 days", "freshness", name, {"hours": 48})
        if rows:
            propose("Row count within range", "row_count", None, {"min": max(0, int(rows * 0.8)), "max": int(rows * 1.2) + 1}, threshold=1.0)

        added, skipped = [], []
        for p in proposals:
            key = (p["kind"], (p["column"] or "").lower())
            if key in have:
                skipped.append(f"{p['name']} (already defined)"); continue
            try:
                rule = self.add_rule(version_id, table, actor=actor, name=p["name"], kind=p["kind"], column=p["column"], params=p["params"], threshold=p["threshold"], origin="auto")
                have.add(key)
                added.append(rule.to_dict())
            except (DqError, ValueError) as exc:
                skipped.append(f"{p['name']} ({exc})")
        return {"added": len(added), "skipped": skipped, "rules": added}

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


_GUID = __import__("re").compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")


def _num(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _tidy(x: float) -> float | int:
    return int(round(x)) if abs(x - round(x)) < 1e-9 else round(x, 4)


def _date(v: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _rule(row: dict) -> Rule:
    return Rule(row["id"], row["domain_version_id"], row["table_name"], row["name"], row["column_name"], row["kind"], row["dimension"], row["params"] or {},
                float(row["threshold"]), row["owner"], row["origin"], row["enabled"], row["created_by"], row["created_at"], row["updated_at"])


def _run(row: dict) -> Run:
    return Run(row["id"], row["domain_version_id"], row["table_name"], row["started_at"], row["finished_at"], row["actor"],
               float(row["score"]) if row["score"] is not None else None, row["status"], row["error"])


def _f(v) -> float | None:
    return None if v is None else round(float(v), 4)
