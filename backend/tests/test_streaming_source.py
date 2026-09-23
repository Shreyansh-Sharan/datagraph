from ontoforge.build import BuildPipeline, PostgresSource
from ontoforge.db import Database
from ontoforge.registry import Registry
from ontoforge.store import TripleStore
from tests.conftest import TEST_DATABASE_URL
from tests.hr_fixture import seed_tables, mapping, BASE


def test_remote_source_streams_rows_through_copy(db):
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="a")
    reg.update_content(v.id, actor="a", mapping=mapping().to_dict())
    remote = Database(TEST_DATABASE_URL, schema=db.schema)  # a different connection pool => streaming path
    try:
        streamed = BuildPipeline(reg, TripleStore(db), PostgresSource(remote)).run(v.id)
        assert streamed.status == "succeeded", streamed.error
        local = BuildPipeline(reg, TripleStore(db), PostgresSource(db)).run(v.id)
        assert streamed.triple_count == local.triple_count > 0
    finally:
        remote.close()


def test_load_step_is_visible_with_row_progress_while_streaming(db):
    """A poll during the load step sees the step itself and how many rows have arrived so far."""
    seed_tables(db)
    reg = Registry(db)
    v = reg.create_version(reg.create_domain("hr", base_iri=BASE).id, actor="a")
    reg.update_content(v.id, actor="a", mapping=mapping().to_dict())
    remote = Database(TEST_DATABASE_URL, schema=db.schema)
    run = reg.start_build(v.id, actor="a")
    seen: list[list[dict]] = []

    class Peeking(PostgresSource):
        def stream(self, sql, batch=10_000):
            for i, row in enumerate(super().stream(sql, batch)):
                if i == 12:   # mid-stream (the fixture streams 25 rows): what a GET /builds/{id} would return right now
                    seen.append(reg.get_build(run.id).steps)
                yield row

    try:
        done = BuildPipeline(reg, TripleStore(db), Peeking(remote), progress_rows=5).run(v.id, run=run)
        assert done.status == "succeeded", done.error
    finally:
        remote.close()
    (mid,) = seen
    assert mid[-1]["name"] == "load" and mid[-1]["seconds"] is None      # the running step is persisted when it starts
    assert mid[-1]["detail"]["rows"] == 10                        # and its progress every `progress_rows` rows
    assert done.steps[-2]["name"] == "load" and done.steps[-2]["detail"]["triples"] == done.triple_count
