"""Table profiles: one pass over the source per table, saved on the version, Databricks SQL shape checked."""
from ontoforge.build import DatabricksSource, PostgresSource
from ontoforge.metadata import MetadataService
from ontoforge.profiling import ProfileService
from ontoforge.registry import Registry
from tests.hr_fixture import seed_tables, BASE
from tests.test_databricks_source import FakeConnection


def _setup(db):
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="alice")
    src = PostgresSource(db)
    meta = MetadataService(reg, src.catalog, db)
    meta.import_tables(v.id, ["employees"], actor="alice")
    return reg, meta, src, v


def test_profile_counts_rows_nulls_distinct_ranges_and_keys(db):
    reg, meta, src, v = _setup(db)
    svc = ProfileService(reg, meta, src, db)
    assert svc.get(v.id, "employees") is None
    seen = []
    p = svc.run(v.id, "employees", actor="alice", on_progress=seen.append)
    assert p.table == "employees" and p.row_count == 4 and p.sample_pct == 100 and p.duplicate_keys == 0
    assert p.size_bytes and p.size_bytes > 0
    by = {c.name: c for c in p.columns}
    assert by["sal"].nulls == 1 and abs(by["sal"].null_rate - 0.25) < 1e-9 and by["sal"].distinct == 3
    assert by["sal"].min == "500" and by["sal"].max == "1250"
    assert by["hired"].min == "2020-01-15" and by["hired"].nulls == 1
    assert by["ename"].distinct == 4 and by["ename"].top is not None and by["ename"].top_share == 0.25
    assert by["empno"].nulls == 0 and by["empno"].null_rate == 0
    assert svc.get(v.id, "employees").row_count == 4 and any("column" in s for s in seen)


def test_profile_has_moments_quartiles_histograms_value_counts_roles_and_hints(db):
    reg, meta, src, v = _setup(db)
    p = ProfileService(reg, meta, src, db).run(v.id, "employees", actor="alice")
    by = {c.name: c for c in p.columns}
    # table level
    assert p.duplicate_rows == 0 and abs(p.missing_cells - 5 / 24) < 1e-6 and p.row_key == ["empno"]   # sal, deptno, manager x2, hired
    # a numeric feature: 800, 1250, 500 (one null)
    sal = by["sal"]
    assert sal.role == "feature" and sal.kind == "numeric" and sal.non_null == 3 and sal.unique_pct == 0.75
    assert sal.mean == 850 and sal.median == 800 and sal.q1 == 650 and sal.q3 == 1025 and round(sal.std, 4) == 377.4917
    assert sal.mean_ci == round(1.96 * sal.std / 3 ** 0.5, 4)
    assert sal.zeros_rate == 0 and sal.outliers == 0 and sal.outlier_rate == 0
    assert sal.skew is not None and sal.kurtosis is not None and sal.normal_p is not None
    assert len(sal.histogram) == 10 and sum(b["n"] for b in sal.histogram) == 3 and sal.histogram[0]["lo"] == 500 and sal.histogram[-1]["hi"] == 1250
    assert sal.peaks >= 1
    # the key: unique, integer, never null
    emp = by["empno"]
    assert emp.role == "row key" and emp.kind == "numeric id" and emp.unique_pct == 1.0 and "Primary-key candidate" in " ".join(emp.hints)
    # a categorical: four distinct names, one row each
    en = by["ename"]
    assert en.role == "feature" and en.kind == "categorical" and en.balance == 2.0 and en.top_share == 0.25
    assert sorted(v["value"] for v in en.values) == ["ALLEN", "GHOST", "SMITH", "WARD"] and all(v["n"] == 1 for v in en.values)
    assert any(h.startswith("Encode: one-hot") for h in en.hints)
    # a low-cardinality number is still numeric, with its value counts for the bar chart
    dept = by["deptno"]
    assert dept.kind == "numeric" and {v["value"]: v["n"] for v in dept.values} == {"10": 1, "20": 1, "99": 1}
    # dates
    assert by["hired"].kind == "date" and by["hired"].histogram == [] and by["hired"].mean is None
    # everything survives a save and a load
    again = ProfileService(reg, meta, src, db).get(v.id, "employees")
    assert {c.name: c for c in again.columns}["sal"].histogram == sal.histogram and again.row_key == ["empno"]


def test_profile_samples_big_tables_and_speaks_databricks(db):
    reg, meta, _, v = _setup(db)
    # The fake answers every query with the same row: 5,000,000 rows, then aggregate values.
    conn = FakeConnection([(5_000_000, 5_000_000, 3, 1, 5_000_000, 100, 250, "SMITH", 0.5, 1)])   # ename: 100 non-null rows, "250" approx distinct
    dbx = DatabricksSource(lambda: conn, default_catalog="main", default_schema="hr")
    dbx.table_stats = lambda table: (17_000_000, None)   # DESCRIBE DETAIL, stubbed
    p = ProfileService(reg, meta, dbx, db, sample_rows=1_000_000).run(v.id, "employees", actor="alice")
    assert p.row_count == 5_000_000 and p.sample_pct == 20 and p.size_bytes == 17_000_000
    sqls = [sql for c in conn.cursors for sql, _ in c.executed]
    assert any("TABLESAMPLE (20 PERCENT)" in s for s in sqls)
    assert any("approx_count_distinct(`sal`)" in s for s in sqls)
    assert any("percentile_approx(CAST(`sal` AS DOUBLE), 0.5)" in s for s in sqls)
    assert any("mode(`ename`)" in s for s in sqls)
    assert all(c.distinct is None or c.distinct <= c.non_null for c in p.columns)   # approximate counts never exceed the rows


def test_databricks_counts_distinct_rows_through_a_struct_so_nulls_are_not_duplicates():
    from ontoforge.dialects import DatabricksDialect, PostgresDialect
    d = DatabricksDialect()
    assert d.distinct_count(["`a`", "`b`"]) == "count(DISTINCT struct(`a`, `b`))"   # count(DISTINCT a, b) skips rows with a null
    assert d.distinct_count(["`a`"]) == "count(DISTINCT `a`)"
    assert PostgresDialect().distinct_count(['"a"', '"b"']) == 'count(DISTINCT ("a", "b"))'


def test_entropy_of_a_constant_column_is_a_plain_zero():
    from ontoforge.profiling import _entropy
    assert _entropy([290]) == 0.0 and str(_entropy([290])) == "0.0"


def test_peaks_ignore_flat_histograms_and_count_real_maxima():
    from ontoforge.profiling import _peaks
    assert _peaks([29] * 10) == 0            # uniform: no peak at all
    assert _peaks([1, 5, 2, 7, 1]) == 2      # two hills
    assert _peaks([1, 2, 3, 4]) == 1         # a ramp peaks at its end
    assert _peaks([4, 3, 2, 1]) == 1 and _peaks([]) == 0 and _peaks([3]) == 1
