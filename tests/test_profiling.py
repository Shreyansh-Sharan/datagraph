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


def test_profile_samples_big_tables_and_speaks_databricks(db):
    reg, meta, _, v = _setup(db)
    # The fake answers every query with the same row: 5,000,000 rows, then aggregate values.
    conn = FakeConnection([(5_000_000, 5_000_000, 3, 1, 5_000_000, 100, 250, "SMITH", 0.5, 1)])   # ename: 100 non-null rows, "250" approx distinct
    dbx = DatabricksSource(lambda: conn, default_catalog="main", default_schema="hr")
    dbx.table_stats = lambda table: (17_000_000, None)   # DESCRIBE DETAIL, stubbed
    p = ProfileService(reg, meta, dbx, db, sample_rows=1_000_000).run(v.id, "employees", actor="alice")
    assert p.row_count == 5_000_000 and p.sample_pct == 20 and p.size_bytes == 17_000_000
    by = {c.name: c for c in p.columns}
    assert by["ename"].distinct == 100                     # approx_count_distinct can overshoot: never more than the non-null rows
    sqls = [sql for c in conn.cursors for sql, _ in c.executed]
    assert any("TABLESAMPLE (20 PERCENT)" in s for s in sqls)
    assert any("approx_count_distinct(`sal`)" in s for s in sqls)
    assert any("mode(`ename`)" in s for s in sqls)
