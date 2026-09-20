"""Publishing the triple view/table inside the source warehouse (two-layer model).

materialization = "none" (default) | "view" | "table". When publishing, the pipeline creates
<target_schema>.<domain>_v<version>_triples as a VIEW over the compiled SQL and, in table mode,
a snapshot TABLE ..._triples_mat, then loads the store from the published object.
"""
from ontoforge.build import BuildPipeline, DatabricksSource, PostgresSource, PublishConfig
from ontoforge.registry import Registry
from ontoforge.store import TripleStore
from tests.hr_fixture import seed_tables, mapping, ontology, BASE
from tests.test_databricks_source import FakeConnection


def prepared(db):
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="a")
    reg.update_content(v.id, actor="a", ontology_ttl=ontology().to_turtle(), mapping=mapping().to_dict())
    return reg, TripleStore(db), v


def test_default_is_no_publish(db):
    reg, store, v = prepared(db)
    run = BuildPipeline(reg, store, PostgresSource(db)).run(v.id)
    assert run.status == "succeeded" and "publish" not in [s["name"] for s in run.steps]


def test_postgres_view_publish(db):
    reg, store, v = prepared(db)
    cfg = PublishConfig(target_schema=db.schema, materialization="view")
    run = BuildPipeline(reg, store, PostgresSource(db), publish=cfg).run(v.id)
    assert run.status == "succeeded", run.error
    publish = next(s for s in run.steps if s["name"] == "publish")
    assert publish["detail"]["view"] == f"{db.schema}.hr_v1_triples" and publish["detail"]["table"] is None
    with db.transaction() as cur:
        assert cur.execute(f'SELECT count(*) FROM "{db.schema}"."hr_v1_triples"').fetchone()[0] == run.triple_count > 0
    assert run.triple_count == store.count(v.id)


def test_postgres_table_publish_snapshots_and_loads_from_table(db):
    reg, store, v = prepared(db)
    cfg = PublishConfig(target_schema=db.schema, materialization="table")
    run = BuildPipeline(reg, store, PostgresSource(db), publish=cfg).run(v.id)
    assert run.status == "succeeded", run.error
    publish = next(s for s in run.steps if s["name"] == "publish")
    assert publish["detail"]["table"] == f"{db.schema}.hr_v1_triples_mat"
    with db.transaction() as cur:
        n_table = cur.execute(f'SELECT count(*) FROM "{db.schema}"."hr_v1_triples_mat"').fetchone()[0]
        cur.execute("DELETE FROM employees")           # the snapshot must not follow source changes
        n_after = cur.execute(f'SELECT count(*) FROM "{db.schema}"."hr_v1_triples_mat"').fetchone()[0]
        n_view = cur.execute(f'SELECT count(*) FROM "{db.schema}"."hr_v1_triples"').fetchone()[0]
    assert n_table == n_after == run.triple_count and n_view < n_table


def test_publish_creates_target_schema_if_missing(db):
    reg, store, v = prepared(db)
    target = db.schema + "_kg"
    run = BuildPipeline(reg, store, PostgresSource(db), publish=PublishConfig(target_schema=target, materialization="view")).run(v.id)
    assert run.status == "succeeded", run.error
    with db.transaction() as cur:
        assert cur.execute(f'SELECT count(*) FROM "{target}"."hr_v1_triples"').fetchone()[0] > 0
        cur.execute(f'DROP SCHEMA "{target}" CASCADE')


def test_domain_names_become_safe_identifiers(db):
    reg, store, v = prepared(db)
    d = reg.create_domain("Sales-Ops 2026", base_iri="http://d/s/")
    v2 = reg.create_version(d.id, actor="a")
    reg.update_content(v2.id, actor="a", mapping=mapping().to_dict())
    run = BuildPipeline(reg, store, PostgresSource(db), publish=PublishConfig(target_schema=db.schema, materialization="view")).run(v2.id)
    assert run.status == "succeeded", run.error
    assert next(s for s in run.steps if s["name"] == "publish")["detail"]["view"] == f"{db.schema}.sales_ops_2026_v1_triples"


def test_databricks_publish_issues_ddl_then_streams_from_table(db):
    reg, store, v = prepared(db)
    rows = [("http://d/hr/Employee/1", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://d/hr#Employee", "iri", None, None)]
    conn = FakeConnection(rows)
    src = DatabricksSource(lambda: conn, default_catalog="main", default_schema="hr")
    run = BuildPipeline(reg, store, src, publish=PublishConfig(target_schema="main.kg", materialization="table")).run(v.id)
    assert run.status == "succeeded", run.error
    executed = [sql for cur in conn.cursors for sql, _ in cur.executed]
    ddl = [s for s in executed if s.startswith("CREATE OR REPLACE")]
    assert ddl[0].startswith("CREATE OR REPLACE VIEW `main`.`kg`.`hr_v1_triples` AS\n")
    assert ddl[1] == "CREATE OR REPLACE TABLE `main`.`kg`.`hr_v1_triples_mat` AS SELECT * FROM `main`.`kg`.`hr_v1_triples`"
    assert any(s.startswith("SELECT subject, predicate, object, object_type, datatype, lang FROM `main`.`kg`.`hr_v1_triples_mat`") for s in executed)
    assert store.count(v.id) == 1
