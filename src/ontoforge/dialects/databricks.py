"""Spark SQL as spoken by Databricks SQL Warehouses."""
from __future__ import annotations

from .base import SqlDialect, _num


class DatabricksDialect(SqlDialect):
    name = "databricks"

    def quote_identifier(self, name: str) -> str:
        return "`" + name.replace("`", "``") + "`"

    def string_literal(self, value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    def concat(self, parts: list[str]) -> str:
        return parts[0] if len(parts) == 1 else "concat(" + ", ".join(parts) + ")"

    def to_text(self, expr: str) -> str:
        return f"CAST({expr} AS STRING)"

    def null_text(self) -> str:
        return "CAST(NULL AS STRING)"

    def post_materialize_sql(self, table_sql: str) -> list[str]:
        # Liquid clustering on (predicate, subject) matches the store's access paths; OPTIMIZE compacts.
        return [f"ALTER TABLE {table_sql} CLUSTER BY (predicate, subject)", f"OPTIMIZE {table_sql}"]

    def iri_encode(self, expr: str) -> str:
        # url_encode() is form-encoding (space -> '+'); IRIs want '%20'.
        return f"replace(url_encode({expr}), '+', '%20')"

    # -- profiling and data-quality primitives in Spark SQL ----------------------------------------

    def count_if(self, predicate: str) -> str:
        return f"count_if({predicate})"

    def approx_distinct(self, expr: str) -> str:
        return f"approx_count_distinct({expr})"

    def distinct_count(self, exprs: list[str]) -> str:
        # count(DISTINCT a, b) drops every row with a null in it; a struct is never null.
        return f"count(DISTINCT {exprs[0]})" if len(exprs) == 1 else f"count(DISTINCT struct({', '.join(exprs)}))"

    def regex_match(self, expr: str, pattern: str) -> str:
        return f"{expr} RLIKE {self.string_literal(pattern)}"

    def top_value(self, expr: str) -> str:
        return f"mode({expr})"

    def sample_clause(self, pct: float) -> str:
        return f"TABLESAMPLE ({_num(pct)} PERCENT)"

    def hours_ago(self, hours: int) -> str:
        return f"current_timestamp() - INTERVAL {int(hours)} HOURS"

    def to_double(self, expr: str) -> str:
        return f"CAST({expr} AS DOUBLE)"

    def quantile(self, expr: str, q: float) -> str:
        return f"percentile_approx({expr}, {_num(q)})"

    def is_multiple(self, expr: str, n: int) -> str:
        return f"MOD({expr}, {int(n)}) = 0"
