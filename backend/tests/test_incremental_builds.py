"""Incremental builds: a table that did not change since the last build is not read again."""
from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.registry import Registry
from ontoforge.store import TripleStore
from tests.hr_fixture import seed_tables, mapping, BASE, EX


def _env(db):
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="alice")
    reg.update_content(v.id, actor="alice", mapping=mapping().to_dict())
    return reg, TripleStore(db), BuildPipeline(reg, TripleStore(db), PostgresSource(db)), v


def _plan(run) -> dict:
    return next(s for s in run.steps if s["name"] == "plan")["detail"]


def test_first_build_is_full_and_tags_every_triple_with_its_source_table(db):
    reg, store, pipeline, v = _env(db)
    run = pipeline.run(v.id, actor="alice")
    assert run.status == "succeeded", run.error
    plan = _plan(run)
    assert plan["mode"] == "full" and plan["unchanged"] == 0 and set(plan["changed"]) >= {"employees", "departments"}
    with db.transaction() as cur:
        untagged = cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND source_table IS NULL", (v.id,)).fetchone()[0]
        tables = {r[0] for r in cur.execute("SELECT DISTINCT source_table FROM triples WHERE domain_version_id = %s", (v.id,))}
    assert untagged == 0 and "employees" in tables and "departments" in tables


def test_an_unchanged_source_is_not_read_again(db):
    reg, store, pipeline, v = _env(db)
    first = pipeline.run(v.id, actor="alice")
    second = pipeline.run(v.id, actor="alice")
    assert second.status == "succeeded" and second.triple_count == first.triple_count
    plan = _plan(second)
    assert plan["mode"] == "incremental" and plan["changed"] == [] and plan["unchanged"] >= 2
    load = next(s for s in second.steps if s["name"] == "load")
    assert load["detail"] == {"triples": 0, "skipped": True}


def test_only_the_changed_table_is_reloaded_and_its_new_values_arrive(db):
    reg, store, pipeline, v = _env(db)
    pipeline.run(v.id, actor="alice")
    with db.transaction() as cur:
        cur.execute("UPDATE employees SET ename = 'SMITHSON' WHERE empno = 1")
    run = pipeline.run(v.id, actor="alice")
    assert run.status == "succeeded", run.error
    plan = _plan(run)
    assert plan["mode"] == "incremental" and plan["changed"] == ["employees"] and "departments" not in plan["changed"]
    with db.transaction() as cur:
        names = {r[0] for r in cur.execute("SELECT object FROM triples WHERE domain_version_id = %s AND predicate = %s", (v.id, EX + "name"))}
    assert "SMITHSON" in names and "SMITH" not in names


def test_a_deleted_row_disappears_because_the_table_reloads_whole(db):
    reg, store, pipeline, v = _env(db)
    before = pipeline.run(v.id, actor="alice").triple_count
    with db.transaction() as cur:
        cur.execute("DELETE FROM employee_skills WHERE empno = 2")
        cur.execute("DELETE FROM collaborations WHERE b = 3")
        cur.execute("DELETE FROM employees WHERE empno = 3")
    run = pipeline.run(v.id, actor="alice")
    assert run.status == "succeeded", run.error
    assert run.triple_count < before and "employees" in _plan(run)["changed"]
    assert store.count(v.id) == run.triple_count


def test_a_mapping_change_reloads_only_the_tables_whose_selects_changed(db):
    reg, store, pipeline, v = _env(db)
    pipeline.run(v.id, actor="alice")
    forced = pipeline.run(v.id, actor="alice", full=True)
    assert _plan(forced)["mode"] == "full" and forced.status == "succeeded"
    spec = mapping().to_dict()
    reg.update_content(v.id, actor="alice", mapping=spec)          # same content: nothing to read
    assert _plan(pipeline.run(v.id, actor="alice"))["changed"] == []
    spec["classes"][0]["attributes"] = spec["classes"][0]["attributes"][:-1]        # Employee loses `hired`: only employees is re-read
    reg.update_content(v.id, actor="alice", mapping=spec)
    run = pipeline.run(v.id, actor="alice")
    plan = _plan(run)
    assert run.status == "succeeded" and plan["mode"] == "incremental" and plan["changed"] == ["employees"] and "mapping" in plan["reason"]
    with db.transaction() as cur:
        assert cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND predicate = %s", (v.id, EX + "hired")).fetchone()[0] == 0
        assert cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND source_table = 'departments'", (v.id,)).fetchone()[0] > 0
    # a relation dropped with its link table: its triples go, and nothing is read for it
    spec["relations"] = [r for r in spec["relations"] if r["table"] != "collaborations"]
    reg.update_content(v.id, actor="alice", mapping=spec)
    plan = _plan(pipeline.run(v.id, actor="alice"))
    assert plan["changed"] == [] and plan["dropped"] == ["collaborations"]
    with db.transaction() as cur:
        assert cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND source_table = 'collaborations'", (v.id,)).fetchone()[0] == 0
        assert cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND source_table = 'employees'", (v.id,)).fetchone()[0] > 0


def test_replace_tables_touches_only_the_named_tables(db):
    reg, store, pipeline, v = _env(db)
    pipeline.run(v.id, actor="alice")
    with db.transaction() as cur:
        dept_before = cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND source_table = 'departments'", (v.id,)).fetchone()[0]
    n = store.replace_tables(v.id, ["employees"], iter([("http://d/hr/Employee/1", EX + "name", "X", "literal", None, None, "employees")]))
    with db.transaction() as cur:
        dept_after = cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND source_table = 'departments'", (v.id,)).fetchone()[0]
        emp = cur.execute("SELECT count(*) FROM triples WHERE domain_version_id = %s AND source_table = 'employees'", (v.id,)).fetchone()[0]
    assert n == 1 and emp == 1 and dept_after == dept_before > 0


def test_postgres_signature_changes_with_the_data():
    from ontoforge.build import PostgresSource
    from tests.conftest import TEST_DATABASE_URL
    from ontoforge.db import Database
    import uuid
    schema = "t_" + uuid.uuid4().hex[:8]
    db = Database(TEST_DATABASE_URL, schema=schema)
    try:
        with db.transaction() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute("CREATE TABLE t (id int, v text)")
            cur.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
        src = PostgresSource(db)
        s1 = src.table_signature("t")
        with db.transaction() as cur:
            cur.execute("UPDATE t SET v = 'c' WHERE id = 2")
        s2 = src.table_signature("t")
        with db.transaction() as cur:
            cur.execute("UPDATE t SET v = 'b' WHERE id = 2")
        s3 = src.table_signature("t")
        assert s1 and s1 != s2 and s1 == s3
    finally:
        with db.transaction() as cur:
            cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        db.close()


def test_table_signatures_are_read_in_parallel(db):
    import time
    reg, store, _, v = _env(db)

    class SlowSignatures(PostgresSource):
        def table_signature(self, table):
            time.sleep(0.4)
            return super().table_signature(table)

    pipeline = BuildPipeline(reg, store, SlowSignatures(db))
    run = pipeline.run(v.id, actor="alice")
    plan = next(s for s in run.steps if s["name"] == "plan")
    assert run.status == "succeeded" and len(plan["detail"]["changed"]) == 3
    assert plan["seconds"] < 1.0                     # three 0.4 s reads side by side, not one after another


def test_compile_reads_column_types_from_the_snapshot_and_drift_looks_only_at_changed_tables(db):
    from ontoforge.metadata import MetadataService
    reg, store, _, v = _env(db)
    src = PostgresSource(db)
    meta = MetadataService(reg, src.catalog, db)
    meta.import_tables(v.id, ["employees", "departments", "collaborations"], actor="alice")
    calls = {"types": 0, "details": 0}
    real_types, real_details = src.catalog.column_types, src.catalog.column_details
    src.catalog.column_types = lambda t: calls.__setitem__("types", calls["types"] + 1) or real_types(t)
    src.catalog.column_details = lambda t: calls.__setitem__("details", calls["details"] + 1) or real_details(t)
    pipeline = BuildPipeline(reg, store, src, metadata=meta)
    first = pipeline.run(v.id, actor="alice")
    assert first.status == "succeeded", first.error
    assert [s["name"] for s in first.steps] == ["compile", "prepare", "plan", "drift", "load", "finalize"]
    assert calls["types"] == 0                                        # the snapshot knows every mapped column's type
    assert next(s for s in first.steps if s["name"] == "drift")["detail"] == {"issues": [], "tables": 3}
    calls["details"] = 0
    second = pipeline.run(v.id, actor="alice")
    assert next(s for s in second.steps if s["name"] == "drift")["detail"] == {"issues": [], "tables": 0}
    assert calls["details"] == 0                                      # nothing changed: the catalog was not asked at all
    with db.transaction() as cur:
        cur.execute("UPDATE departments SET dname = 'MARKETING' WHERE deptno = 10")
    third = pipeline.run(v.id, actor="alice")
    assert next(s for s in third.steps if s["name"] == "drift")["detail"]["tables"] == 1 and _plan(third)["changed"] == ["departments"]


def test_drift_answers_from_the_last_build_unless_asked_to_look_live(db):
    from ontoforge.metadata import MetadataService, drift_from_last_build
    from ontoforge.build import PostgresSource
    reg, store, _, v = _env(db)
    src = PostgresSource(db)
    meta = MetadataService(reg, src.catalog, db)
    meta.import_tables(v.id, ["employees", "departments"], actor="alice")
    assert drift_from_last_build(reg, v.id) == []                                  # nothing built yet: nothing found
    pipeline = BuildPipeline(reg, TripleStore(db), src, metadata=meta)
    assert pipeline.run(v.id, actor="alice").status == "succeeded"
    assert drift_from_last_build(reg, v.id) == []
    with db.transaction() as cur:
        cur.execute("ALTER TABLE employees DROP COLUMN hired")
    assert drift_from_last_build(reg, v.id) == []                                  # the last build saw no drift; only a live check or the next build will
    assert [i.column for i in meta.drift(v.id)] == ["hired"]
