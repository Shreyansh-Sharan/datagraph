"""Bundles v2: several versions per domain, conflict handling on import, Databricks post-materialise DDL."""
import pytest

from ontoforge.build import BuildPipeline, DatabricksSource, PublishConfig
from ontoforge.bundle import export_bundle, import_bundle
from ontoforge.dialects import DatabricksDialect
from ontoforge.registry import Registry, Status
from tests.hr_fixture import built_domain, BASE
from tests.test_databricks_source import FakeConnection
from tests.test_warehouse_publish import prepared


def publish(reg, v):
    reg.transition(v.id, Status.IN_REVIEW, actor="a")
    reg.add_review(v.id, reviewer="b", approved=True)
    reg.transition(v.id, Status.PUBLISHED, actor="a")


def test_export_all_versions_and_import_with_conflict_modes(db):
    reg, store, v1 = built_domain(db)
    publish(reg, v1)
    d = reg.get_domain("hr")
    v2 = reg.create_version(d.id, actor="a")
    reg.update_content(v2.id, actor="a", ontology_ttl="# v2 draft")
    bundle = export_bundle(reg, "hr", versions="all")
    assert bundle["format"] == "ontoforge-bundle/2" and [x["number"] for x in bundle["versions"]] == [1, 2]
    assert export_bundle(reg, "hr", versions="latest")["versions"][0]["number"] == 2
    assert export_bundle(reg, "hr", versions="active")["versions"][0]["number"] == 1     # active/served version

    with pytest.raises(ValueError, match="exists"):
        import_bundle(reg, bundle, actor="i", on_conflict="fail")
    skipped = import_bundle(reg, bundle, actor="i", on_conflict="skip")
    assert skipped.domain == "hr" and skipped.imported == [] and skipped.skipped == [1, 2]
    renamed = import_bundle(reg, bundle, actor="i", on_conflict="rename")
    assert renamed.domain == "hr_2" and renamed.imported == [1, 2]
    assert [x.version for x in reg.list_versions(reg.get_domain("hr_2").id)] == [2, 1]
    assert reg.get_version(reg.latest_version(reg.get_domain("hr_2").id).id).ontology_ttl == "# v2 draft"
    reg.update_content(v2.id, actor="a", ontology_ttl="# changed since export")
    over = import_bundle(reg, bundle, actor="i", on_conflict="overwrite")
    assert over.domain == "hr" and over.imported == [1, 2]
    assert reg.latest_version(d.id).version == 3 and reg.latest_version(d.id).status == Status.PUBLISHED   # bundle v1 appended
    assert reg.get_version(v2.id).ontology_ttl == "# v2 draft"                                          # existing draft overwritten


def test_v1_bundles_still_import(db):
    reg, store, v = built_domain(db)
    v1_bundle = {"format": "ontoforge-bundle/1", "domain": {"name": "old", "base_iri": BASE},
                 "version": {"number": 1, "status": "published", "ontology_ttl": "# old", "mapping": None, "r2rml_ttl": None}}
    result = import_bundle(reg, v1_bundle, actor="i")
    assert result.domain == "old" and result.imported == [1]


def test_databricks_table_publish_optimises_and_clusters(db):
    reg, store, v = prepared(db)
    rows = [("http://d/hr/Employee/1", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://d/hr#Employee", "iri", None, None)]

    class RoutingConnection(FakeConnection):
        def cursor(self):
            c = super().cursor()
            original = c.execute

            def execute(sql, params=None):
                original(sql, params)
                c.rows = list(rows) if sql.startswith("SELECT subject") else []
                return c
            c.execute = execute
            return c

    conn = RoutingConnection(rows)
    src = DatabricksSource(lambda: conn, default_catalog="main", default_schema="hr")
    run = BuildPipeline(reg, store, src, publish=PublishConfig(target_schema="main.kg", materialization="table")).run(v.id)
    assert run.status == "succeeded", run.error
    executed = [sql for cur in conn.cursors for sql, _ in cur.executed]
    assert "ALTER TABLE `main`.`kg`.`hr_v1_triples_mat` CLUSTER BY (predicate, subject)" in executed
    assert "OPTIMIZE `main`.`kg`.`hr_v1_triples_mat`" in executed
    assert DatabricksDialect().post_materialize_sql("`t`") == ["ALTER TABLE `t` CLUSTER BY (predicate, subject)", "OPTIMIZE `t`"]
