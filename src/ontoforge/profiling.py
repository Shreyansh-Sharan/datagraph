"""Table profiles: rows, size, freshness, duplicates on the key and, per column, nulls, distinct
values, range and top value. One aggregate pass over the source per table (sampled past
``sample_rows`` rows), saved on the version so the screens read it without touching the warehouse."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from uuid import UUID

from psycopg.types.json import Jsonb

from ontoforge.build.source import SourceEngine
from ontoforge.db import Database
from ontoforge.metadata import MetadataService
from ontoforge.registry import Registry

_NUMERIC = ("int", "decimal", "numeric", "double", "float", "real", "number", "long", "short", "byte", "serial", "money")
_TEMPORAL = ("date", "time")


def kind_of(sql_type: str | None) -> str:
    """boolean | temporal | numeric | string: decides which aggregates a column gets."""
    t = (sql_type or "").lower()
    if "bool" in t:
        return "boolean"
    if any(k in t for k in _TEMPORAL):
        return "temporal"
    if any(k in t for k in _NUMERIC):
        return "numeric"
    return "string"


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    type: str
    nulls: int                 # in the whole table (scaled up from the sample)
    null_rate: float
    distinct: int | None
    min: str | None
    max: str | None
    top: str | None            # most frequent value (strings, booleans)
    top_share: float | None    # its share of the rows


@dataclass(frozen=True)
class TableProfile:
    table: str
    profiled_at: datetime
    actor: str | None
    sample_pct: float
    row_count: int | None
    size_bytes: int | None
    last_modified: datetime | None
    duplicate_keys: int | None
    columns: list[ColumnProfile]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["profiled_at"] = self.profiled_at.isoformat()
        d["last_modified"] = self.last_modified.isoformat() if self.last_modified else None
        return d


class ProfileService:
    def __init__(self, registry: Registry, metadata: MetadataService, source: "SourceEngine | Callable[[UUID], SourceEngine]",
                 db: Database, sample_rows: int = 2_000_000) -> None:
        self.registry, self.metadata, self._source, self.db, self.sample_rows = registry, metadata, source, db, sample_rows

    def source_for(self, version_id: UUID) -> SourceEngine:
        return self._source(version_id) if callable(self._source) else self._source

    def get(self, version_id: UUID, table: str) -> TableProfile | None:
        with self.db.rows() as cur:
            row = cur.execute("SELECT * FROM table_profiles WHERE domain_version_id = %s AND table_name = %s", (version_id, table)).fetchone()
        return _profile(row) if row else None

    def run(self, version_id: UUID, table: str, *, actor: str | None = None, on_progress: Callable[[str], None] | None = None) -> TableProfile:
        say = on_progress or (lambda _m: None)
        snap = self.metadata.get(version_id, table)
        src = self.source_for(version_id)
        d = src.dialect
        tq = d.quote_table(table)

        say("Counting rows")
        _, rows = src.query(f"SELECT count(*) FROM {tq}", 1)
        row_count = int(rows[0][0] or 0)
        pct = 100.0 if row_count <= self.sample_rows else round(100.0 * self.sample_rows / row_count, 2)
        from_sql = tq if pct >= 100 else f"{tq} {d.sample_clause(pct)}"

        cols = snap.columns
        kinds = {c["name"]: kind_of(c.get("type")) for c in cols}
        say(f"Profiling {len(cols)} column{'s' if len(cols) != 1 else ''}" + (f" on a {pct:g}% sample" if pct < 100 else ""))
        exprs, plan = ["count(*)"], []
        for c in cols:
            name, q, k = c["name"], d.quote_identifier(c["name"]), kinds[c["name"]]
            exprs += [f"count({q})", d.approx_distinct(q)]
            plan += [(name, "nn"), (name, "distinct")]
            if k in ("numeric", "temporal"):
                exprs += [f"min({q})", f"max({q})"]
                plan += [(name, "min"), (name, "max")]
            elif k == "boolean":
                exprs.append(d.count_if(f"{q} = TRUE"))
                plan.append((name, "true"))
            else:
                exprs.append(d.to_text(d.top_value(q)))
                plan.append((name, "top"))
        pk = [k for k in snap.primary_key if any(c["name"] == k for c in cols)]
        if pk:
            exprs.append(f"count(*) - {d.distinct_count([d.quote_identifier(k) for k in pk])}")
            plan.append(("", "dups"))
        _, rows = src.query(f"SELECT {', '.join(exprs)} FROM {from_sql}", 1)
        row = list(rows[0]) if rows else [0]
        total = int(row[0] or 0)
        acc: dict[str, dict] = {c["name"]: {"nn": 0, "distinct": None, "min": None, "max": None, "top": None, "true": None} for c in cols}
        dups: int | None = None
        for (name, what), v in zip(plan, row[1:]):
            if what == "dups":
                dups = int(v or 0)
            else:
                acc[name][what] = v

        # Share of the top value for text columns: one more pass, all columns at once.
        tops = {n: a["top"] for n, a in acc.items() if kinds[n] == "string" and a["top"] is not None}
        shares: dict[str, float] = {}
        if tops and total:
            exprs = [d.count_if(f"{d.to_text(d.quote_identifier(n))} = {d.string_literal(str(t))}") for n, t in tops.items()]
            _, r2 = src.query(f"SELECT {', '.join(exprs)} FROM {from_sql}", 1)
            shares = {n: int(v or 0) / total for n, v in zip(tops, r2[0] if r2 else [])}

        columns = []
        for c in cols:
            a, k = acc[c["name"]], kinds[c["name"]]
            nn = int(a["nn"] or 0)
            null_rate = (max(0, total - nn) / total) if total else 0.0
            top, share = None, None
            if k == "boolean" and a["true"] is not None and nn:
                t = float(a["true"]) / nn
                top, share = ("true", t) if t >= 0.5 else ("false", 1 - t)
            elif k == "string":
                top, share = _text(a["top"]), shares.get(c["name"])
            columns.append(ColumnProfile(c["name"], c.get("type") or "", int(round(null_rate * row_count)), round(null_rate, 6), _int(a["distinct"]),
                                         _text(a["min"]), _text(a["max"]), top, round(share, 4) if share is not None else None))

        say("Reading table size and freshness")
        try:
            size, modified = src.table_stats(table)
        except Exception:  # noqa: BLE001 - a warehouse without the statement still gets a profile
            size, modified = None, None
        prof = TableProfile(table, datetime.now(timezone.utc), actor, pct, row_count, size, modified, dups, columns)
        with self.db.rows() as cur:
            cur.execute(
                "INSERT INTO table_profiles (domain_version_id, table_name, profiled_at, actor, sample_pct, row_count, size_bytes, last_modified, duplicate_keys, columns) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (domain_version_id, table_name) DO UPDATE SET profiled_at = EXCLUDED.profiled_at, "
                "actor = EXCLUDED.actor, sample_pct = EXCLUDED.sample_pct, row_count = EXCLUDED.row_count, size_bytes = EXCLUDED.size_bytes, "
                "last_modified = EXCLUDED.last_modified, duplicate_keys = EXCLUDED.duplicate_keys, columns = EXCLUDED.columns",
                (version_id, table, prof.profiled_at, actor, pct, row_count, size, modified, dups, Jsonb([asdict(c) for c in columns])))
        return prof


def _profile(row: dict) -> TableProfile:
    return TableProfile(row["table_name"], row["profiled_at"], row["actor"], float(row["sample_pct"]), row["row_count"], row["size_bytes"],
                        row["last_modified"], row["duplicate_keys"], [ColumnProfile(**c) for c in row["columns"]])


def _text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    if isinstance(v, float):
        return format(v, "g")
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _int(v) -> int | None:
    return None if v is None else int(v)
