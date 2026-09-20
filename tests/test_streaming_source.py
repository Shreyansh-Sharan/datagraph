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
