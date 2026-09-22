"""Table profiles: what a data scientist reads before modelling. Per table: rows, size, freshness,
duplicate rows, empty cells, the row key. Per column: nulls, distinct values, the mode and its
share, entropy, moments (mean, standard deviation, skew, kurtosis, a normality p-value), quartiles,
outliers, zeros, heaping at round numbers, a histogram or the value counts, a role, a kind and
hints for the modeller. A few aggregate passes over the source per table (sampled past
``sample_rows`` rows), saved on the version so the screens never touch the warehouse to read it."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
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
BINS = 10                 # histogram bins for a numeric column
VALUE_COUNT_LIMIT = 50    # value counts are kept for columns with at most this many distinct values
HIGH_CARDINALITY = 0.9    # distinct / rows above this: almost every value is distinct


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
    nulls: int                          # in the whole table (scaled up from the sample)
    null_rate: float
    distinct: int | None
    min: str | None
    max: str | None
    top: str | None                     # most frequent value
    top_share: float | None             # its share of the non-null rows
    role: str = "feature"               # row key | binary | feature
    kind: str = "numeric"               # numeric id | numeric | categorical | boolean | date
    non_null: int = 0
    unique_pct: float | None = None     # distinct / rows
    balance: float | None = None        # Shannon entropy of the values, in bits (from the value counts)
    mean: float | None = None
    mean_ci: float | None = None        # 95% half-width of the mean
    std: float | None = None
    median: float | None = None
    q1: float | None = None
    q3: float | None = None
    skew: float | None = None
    kurtosis: float | None = None       # excess kurtosis
    normal_p: float | None = None       # Jarque-Bera p-value: small means not normal
    outliers: int | None = None         # beyond 1.5 IQR from the quartiles
    outlier_rate: float | None = None
    zeros_rate: float | None = None
    heaped_rate: float | None = None    # share of values that are multiples of 5
    peaks: int | None = None            # local maxima of the histogram
    histogram: list = field(default_factory=list)   # [{lo, hi, n}]
    values: list = field(default_factory=list)      # [{value, n}] for low-cardinality columns
    hints: list = field(default_factory=list)


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
    duplicate_rows: int | None = None
    missing_cells: float | None = None
    row_key: list[str] = field(default_factory=list)

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
        cols = snap.columns
        kinds = {c["name"]: kind_of(c.get("type")) for c in cols}
        q = {c["name"]: d.quote_identifier(c["name"]) for c in cols}

        say("Counting rows")
        row_count = _int(_first(src.query(f"SELECT count(*) FROM {tq}", 1))) or 0
        pct = 100.0 if row_count <= self.sample_rows else round(100.0 * self.sample_rows / row_count, 2)
        from_sql = tq if pct >= 100 else f"{tq} {d.sample_clause(pct)}"

        # -- pass 1: counts, distinct, range, moments, quartiles, zeros, heaping, keys, duplicate rows ----
        say(f"Profiling {len(cols)} column{'s' if len(cols) != 1 else ''}" + (f" on a {pct:g}% sample" if pct < 100 else ""))
        exprs: list[str] = ["count(*)"]
        plan: list[tuple[str, str]] = []

        def want(name: str, what: str, expr: str) -> None:
            exprs.append(expr); plan.append((name, what))

        for c in cols:
            n, qc, k = c["name"], q[c["name"]], kinds[c["name"]]
            want(n, "nn", f"count({qc})")
            want(n, "distinct", d.approx_distinct(qc))
            if k == "numeric":
                x = d.to_double(qc)
                want(n, "min", f"min({qc})"); want(n, "max", f"max({qc})")
                want(n, "m1", f"avg({x})"); want(n, "m2", f"avg({x} * {x})"); want(n, "m3", f"avg({x} * {x} * {x})"); want(n, "m4", f"avg({x} * {x} * {x} * {x})")
                want(n, "std", d.stddev(x))
                want(n, "q1", d.quantile(x, 0.25)); want(n, "median", d.quantile(x, 0.5)); want(n, "q3", d.quantile(x, 0.75))
                want(n, "zeros", d.count_if(f"{qc} = 0")); want(n, "heaped", d.count_if(d.is_multiple(qc, 5)))
            elif k == "temporal":
                want(n, "min", f"min({qc})"); want(n, "max", f"max({qc})")
            elif k == "boolean":
                want(n, "true", d.count_if(f"{qc} = TRUE"))
            else:
                want(n, "top", d.to_text(d.top_value(qc)))
        pk = [k for k in snap.primary_key if any(c["name"] == k for c in cols)]
        if pk:
            want("", "dups", f"count(*) - {d.distinct_count([q[k] for k in pk])}")
        if 0 < len(cols) <= 60:
            want("", "duprows", f"count(*) - {d.distinct_count([q[c['name']] for c in cols])}")
        row = _row(src.query(f"SELECT {', '.join(exprs)} FROM {from_sql}", 1))
        total = _int(row[0]) or 0
        acc: dict[str, dict] = {c["name"]: {} for c in cols}
        dups = duprows = None
        for (name, what), v in zip(plan, row[1:]):
            if what == "dups":
                dups = _int(v)
            elif what == "duprows":
                duprows = _int(v)
            else:
                acc[name][what] = v

        # -- pass 2: histogram bins, outliers beyond the IQR fences, the mode's share ---------------------
        exprs, plan = [], []
        bins: dict[str, list[tuple[float, float]]] = {}
        for c in cols:
            n, qc, k, a = c["name"], q[c["name"]], kinds[c["name"]], acc[c["name"]]
            if k == "numeric":
                lo, hi = _float(a.get("min")), _float(a.get("max"))
                if lo is not None and hi is not None and hi > lo:
                    edges = [lo + (hi - lo) * i / BINS for i in range(BINS + 1)]
                    bins[n] = [(edges[i], edges[i + 1]) for i in range(BINS)]
                    for i, (b0, b1) in enumerate(bins[n]):
                        upper = f"{qc} <= {_lit(b1)}" if i == BINS - 1 else f"{qc} < {_lit(b1)}"
                        want(n, f"bin{i}", d.count_if(f"{qc} >= {_lit(b0)} AND {upper}"))
                q1, q3 = _float(a.get("q1")), _float(a.get("q3"))
                if q1 is not None and q3 is not None:
                    iqr = q3 - q1
                    want(n, "outliers", d.count_if(f"{qc} < {_lit(q1 - 1.5 * iqr)} OR {qc} > {_lit(q3 + 1.5 * iqr)}"))
            elif k == "string" and a.get("top") is not None:
                want(n, "topn", d.count_if(f"{d.to_text(qc)} = {d.string_literal(str(a['top']))}"))
        if exprs:
            say("Measuring distributions")
            row = _row(src.query(f"SELECT {', '.join(exprs)} FROM {from_sql}", 1))
            for (name, what), v in zip(plan, row):
                acc[name][what] = v

        # -- pass 3: value counts of low-cardinality columns (bar charts, entropy, the mode) -----------------
        counted: dict[str, list[tuple[str, int]]] = {}
        small = [c["name"] for c in cols if kinds[c["name"]] != "temporal"
                 and (_int(acc[c["name"]].get("distinct")) or 0) <= VALUE_COUNT_LIMIT and (_int(acc[c["name"]].get("nn")) or 0) > 0]
        if small:
            say(f"Counting the values of {len(small)} column{'s' if len(small) != 1 else ''}")
        for n in small[:40]:
            _, rows = src.query(f"SELECT {d.to_text(q[n])} AS v, count(*) AS n FROM {from_sql} WHERE {q[n]} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {VALUE_COUNT_LIMIT}", VALUE_COUNT_LIMIT)
            counted[n] = [(str(r[0]), (_int(r[1]) if len(r) > 1 else 0) or 0) for r in rows if r]

        # -- assemble --------------------------------------------------------------------------------------
        columns, total_nulls = [], 0
        for c in cols:
            n, k, a = c["name"], kinds[c["name"]], acc[c["name"]]
            nn = _int(a.get("nn")) or 0
            null_rate = (max(0, total - nn) / total) if total else 0.0
            nulls = int(round(null_rate * row_count))
            total_nulls += nulls
            distinct = None if a.get("distinct") is None else min(_int(a["distinct"]) or 0, nn)
            values = [{"value": v, "n": cnt} for v, cnt in counted.get(n, [])]
            if values and distinct is not None and distinct <= VALUE_COUNT_LIMIT:
                distinct = len(values)                                     # exact where the values were counted
            unique_pct = round(distinct / total, 4) if distinct is not None and total else None   # share of all rows, like the summary shows
            top, share = None, None
            if values:
                top, share = values[0]["value"], (round(values[0]["n"] / nn, 4) if nn else None)
            elif k == "boolean" and a.get("true") is not None and nn:
                t = (_int(a["true"]) or 0) / nn
                top, share = ("true", round(t, 4)) if t >= 0.5 else ("false", round(1 - t, 4))
            elif k == "string":
                top = _text(a.get("top"))
                share = round((_int(a.get("topn")) or 0) / total, 4) if total and a.get("topn") is not None else None
            balance = _entropy([cnt for _, cnt in counted[n]]) if n in counted and distinct is not None and distinct <= VALUE_COUNT_LIMIT else None

            stats: dict = {}
            hist: list = []
            if k == "numeric" and nn:
                m1, m2, m3, m4 = (_float(a.get(x)) for x in ("m1", "m2", "m3", "m4"))
                std = _float(a.get("std"))
                stats = {"mean": _r(m1), "std": _r(std), "median": _r(_float(a.get("median"))), "q1": _r(_float(a.get("q1"))), "q3": _r(_float(a.get("q3"))),
                         "mean_ci": _r(1.96 * std / math.sqrt(nn)) if std is not None else None,
                         "zeros_rate": _r((_int(a.get("zeros")) or 0) / nn), "heaped_rate": _r((_int(a.get("heaped")) or 0) / nn)}
                skew, kurt = _moments(m1, m2, m3, m4)
                stats.update({"skew": _r(skew), "kurtosis": _r(kurt), "normal_p": _r(_jarque_bera(nn, skew, kurt))})
                if a.get("outliers") is not None:
                    o = _int(a["outliers"]) or 0
                    stats.update({"outliers": o, "outlier_rate": _r(o / nn)})
                if n in bins:
                    hist = [{"lo": _r(b0), "hi": _r(b1), "n": _int(a.get(f"bin{i}")) or 0} for i, (b0, b1) in enumerate(bins[n])]
                    stats["peaks"] = _peaks([b["n"] for b in hist])
                elif values:
                    ordered = sorted(((_float(v), cnt) for v, cnt in counted[n] if _float(v) is not None), key=lambda x: x[0])
                    stats["peaks"] = _peaks([cnt for _, cnt in ordered])
            lo, hi = _float(a.get("min")), _float(a.get("max"))
            is_int = k == "numeric" and (lo is None or lo == int(lo)) and (hi is None or hi == int(hi))
            idlike = k == "numeric" or any(t in n.lower() for t in ("id", "key", "code", "guid", "uuid", "number", "no"))
            role = "row key" if nn and nulls == 0 and distinct == nn and nn == total and k in ("numeric", "string") and idlike else "binary" if distinct == 2 else "feature"
            kind = "date" if k == "temporal" else "boolean" if k == "boolean" else "categorical" if k == "string" else "numeric id" if role == "row key" and is_int else "numeric"
            hints = _hints(role, kind, distinct, nn, stats, share)
            columns.append(ColumnProfile(n, c.get("type") or "", nulls, round(null_rate, 6), distinct, _text(a.get("min")), _text(a.get("max")), top, share,
                                         role=role, kind=kind, non_null=nn, unique_pct=unique_pct, balance=balance, histogram=hist, values=values, hints=hints, **stats))

        say("Reading table size and freshness")
        try:
            size, modified = src.table_stats(table)
        except Exception:  # noqa: BLE001 - a warehouse without the statement still gets a profile
            size, modified = None, None
        row_key = list(pk) if pk else [c.name for c in columns if c.role == "row key"][:1]
        missing = round(total_nulls / (row_count * len(cols)), 6) if row_count and cols else 0.0
        prof = TableProfile(table, datetime.now(timezone.utc), actor, pct, row_count, size, modified, dups, columns,
                            duplicate_rows=duprows, missing_cells=missing, row_key=row_key)
        with self.db.rows() as cur:
            cur.execute(
                "INSERT INTO table_profiles (domain_version_id, table_name, profiled_at, actor, sample_pct, row_count, size_bytes, last_modified, duplicate_keys, columns, duplicate_rows, missing_cells, row_key) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (domain_version_id, table_name) DO UPDATE SET profiled_at = EXCLUDED.profiled_at, "
                "actor = EXCLUDED.actor, sample_pct = EXCLUDED.sample_pct, row_count = EXCLUDED.row_count, size_bytes = EXCLUDED.size_bytes, "
                "last_modified = EXCLUDED.last_modified, duplicate_keys = EXCLUDED.duplicate_keys, columns = EXCLUDED.columns, "
                "duplicate_rows = EXCLUDED.duplicate_rows, missing_cells = EXCLUDED.missing_cells, row_key = EXCLUDED.row_key",
                (version_id, table, prof.profiled_at, actor, pct, row_count, size, modified, dups, Jsonb([asdict(c) for c in columns]), duprows, missing, Jsonb(row_key)))
        return prof


# -- statistics ------------------------------------------------------------------------------------

def _moments(m1, m2, m3, m4) -> tuple[float | None, float | None]:
    """Skew and excess kurtosis from the raw moments E[x], E[x^2], E[x^3], E[x^4]."""
    if None in (m1, m2, m3, m4):
        return None, None
    var = m2 - m1 * m1
    if var <= 1e-12:
        return 0.0, 0.0
    sd = math.sqrt(var)
    skew = (m3 - 3 * m1 * var - m1 ** 3) / sd ** 3
    kurt = (m4 - 4 * m1 * m3 + 6 * m1 * m1 * m2 - 3 * m1 ** 4) / var ** 2 - 3
    return skew, kurt


def _jarque_bera(n: int, skew: float | None, kurt: float | None) -> float | None:
    if skew is None or kurt is None or n < 3:
        return None
    jb = n / 6.0 * (skew ** 2 + kurt ** 2 / 4.0)
    return math.exp(-jb / 2.0)            # chi-squared with two degrees of freedom


def _entropy(counts: list[int]) -> float | None:
    total = sum(counts)
    if not total:
        return None
    return round(-sum(c / total * math.log2(c / total) for c in counts if c), 4)


def _peaks(counts: list[int]) -> int:
    """Local maxima of a histogram, ignoring bins under 5% of the tallest."""
    if not counts:
        return 0
    floor = 0.05 * max(counts)
    peaks = 0
    for i, c in enumerate(counts):
        left = counts[i - 1] if i > 0 else -1
        right = counts[i + 1] if i + 1 < len(counts) else -1
        if c > floor and c >= left and c >= right and (c > left or c > right or len(counts) == 1):
            peaks += 1
    return peaks


def _hints(role: str, kind: str, distinct: int | None, nn: int, stats: dict, share: float | None) -> list[str]:
    hints = []
    if role == "row key":
        hints.append("Primary-key candidate: exclude from features; use for joins and dedup checks.")
    elif role == "binary":
        hints.append("Binary: encode as 0/1.")
    elif kind == "categorical" and distinct is not None and distinct <= 12:
        hints.append(f"Encode: one-hot ({distinct} levels).")
    elif kind == "categorical" and distinct is not None and nn and distinct / nn > HIGH_CARDINALITY:
        hints.append("High cardinality: almost every value is distinct; bar chart omitted.")
    if kind == "numeric" and (stats.get("peaks") or 0) >= 2:
        hints.append(f"Multimodal ({stats['peaks']} peaks): may mix distinct populations; consider a segment feature.")
    if kind == "numeric" and (stats.get("heaped_rate") or 0) > 0.4 and (distinct or 0) > 20:
        hints.append("Values heap at round numbers: likely rounded or self-reported; consider coarse binning.")
    if kind == "numeric" and (stats.get("outlier_rate") or 0) > 0.02:
        hints.append(f"Outliers: {stats['outlier_rate']:.1%} of rows sit beyond 1.5 IQR; winsorise or cap before modelling.")
    if kind == "numeric" and stats.get("skew") is not None and abs(stats["skew"]) > 2:
        hints.append("Strong skew: consider a log or Box-Cox transform.")
    if share is not None and share > 0.95 and role != "row key":
        hints.append("Nearly constant: one value covers over 95% of rows; little signal.")
    return hints


# -- plumbing --------------------------------------------------------------------------------------

def _profile(row: dict) -> TableProfile:
    return TableProfile(row["table_name"], row["profiled_at"], row["actor"], float(row["sample_pct"]), row["row_count"], row["size_bytes"],
                        row["last_modified"], row["duplicate_keys"], [ColumnProfile(**c) for c in row["columns"]],
                        duplicate_rows=row.get("duplicate_rows"), missing_cells=float(row["missing_cells"]) if row.get("missing_cells") is not None else None,
                        row_key=list(row.get("row_key") or []))


def _first(result) -> object:
    _, rows = result
    return rows[0][0] if rows and rows[0] else None


def _row(result) -> list:
    _, rows = result
    return list(rows[0]) if rows else []


def _lit(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def _r(x: float | None, digits: int = 4) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else round(x, digits)


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
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None
