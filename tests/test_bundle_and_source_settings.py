"""Domain export/import bundles, and choosing the source engine from settings."""
import json

import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.bundle import export_bundle, import_bundle
from ontoforge.build import DatabricksSource, PostgresSource
from ontoforge.config import Settings
from ontoforge.registry import Registry, Status
ADMIN = Settings(auth_default_role="admin")
from tests.hr_fixture import built_domain, BASE


def test_export_then_import_recreates_domain_content(db):
    reg, store, v = built_domain(db)
    bundle = export_bundle(reg, "hr")
    assert bundle["format"] == "ontoforge-bundle/2" and bundle["domain"]["name"] == "hr"
    assert bundle["versions"][0]["ontology_ttl"] and bundle["versions"][0]["mapping"]["classes"]
    json.dumps(bundle)  # must be plain JSON
    (imported,) = import_bundle(reg, bundle, name="hr_copy", actor="importer").versions
    assert imported.status == Status.DRAFT and imported.version == 1
    assert imported.ontology_ttl == reg.get_version(v.id).ontology_ttl
    assert reg.get_domain("hr_copy").base_iri == BASE


def test_import_into_existing_domain_creates_next_draft(db):
    reg, store, v = built_domain(db)
    reg.transition(v.id, Status.IN_REVIEW, actor="a")
    reg.add_review(v.id, reviewer="b", approved=True)
    reg.transition(v.id, Status.PUBLISHED, actor="a")
    (imported,) = import_bundle(reg, export_bundle(reg, "hr"), actor="importer", on_conflict="overwrite").versions
    assert imported.version == 2 and imported.status == Status.PUBLISHED   # status travels with the bundle


def test_import_rejects_unknown_format(db):
    with pytest.raises(ValueError, match="format"):
        import_bundle(Registry(db), {"format": "something-else"}, actor="x")


def test_bundle_endpoints(db):
    reg, store, v = built_domain(db)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        r = c.get("/domains/hr/export")
        assert r.status_code == 200 and r.json()["format"] == "ontoforge-bundle/2"
        r = c.post("/domains/import", json={**r.json(), "name": "hr2"})
        assert r.status_code == 201 and r.json()["versions"][0]["version"] == 1
        assert c.get("/domains/hr2").status_code == 200


def test_source_engine_from_settings_defaults_to_postgres(db):
    app = create_app(db=db, settings=Settings(source_kind="postgres", auth_default_role="admin"))
    assert isinstance(app.state.sources.env, PostgresSource)


def test_source_engine_from_settings_databricks(db):
    settings = Settings(source_kind="databricks", databricks_host="h", databricks_http_path="/p", databricks_token="t",
                        databricks_catalog="main", databricks_schema="hr")
    app = create_app(db=db, settings=settings)
    assert isinstance(app.state.sources.env, DatabricksSource)
    assert app.state.sources.env.catalog.default_catalog == "main"


def test_databricks_settings_incomplete_is_an_error(db):
    """The deployment source is opened on first use (domains with their own connection never need it)."""
    app = create_app(db=db, settings=Settings(source_kind="databricks"))
    with pytest.raises(ValueError, match="DATABRICKS"):
        app.state.sources.env
