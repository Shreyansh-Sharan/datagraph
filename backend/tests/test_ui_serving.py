"""The single-page UI is served by the API without authentication; the API tells it how to identify."""
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings


def test_ui_is_served_and_root_redirects(db):
    with TestClient(create_app(db=db, settings=Settings())) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"] == "/ui/"
        r = c.get("/ui/")
        assert r.status_code == 200 and "<title>ontoforge</title>" in r.text and 'type="module"' in r.text
        assert c.get("/ui/app.js").status_code == 200
        assert c.get("/ui/app.css").headers["content-type"].startswith("text/css")
        assert c.get("/ui/views/domains.js").status_code == 200
        assert c.get("/ui/nope.js").status_code == 404


def test_auth_config_is_public(db):
    with TestClient(create_app(db=db, settings=Settings(auth_mode="header", auth_header="X-Forwarded-Email"))) as c:
        assert c.get("/auth/config").json() == {"mode": "header", "header": "X-Forwarded-Email", "default_role": "viewer",
                                                "source": {"kind": "postgres", "catalog": None}}
    with TestClient(create_app(db=db, settings=Settings(auth_mode="token"))) as c:
        assert c.get("/auth/config").json()["mode"] == "token"


def test_auth_config_names_the_source_without_secrets(db):
    s = Settings(source_kind="databricks", databricks_host="https://x.cloud.databricks.com", databricks_token="secret-token",
                 databricks_http_path="/sql/1.0/warehouses/abc", databricks_catalog="rgm")
    with TestClient(create_app(db=db, settings=s)) as c:
        body = c.get("/auth/config").json()
        assert body["source"] == {"kind": "databricks", "catalog": "rgm"}
        assert "secret-token" not in c.get("/auth/config").text and "warehouses" not in c.get("/auth/config").text


def test_ui_assets_revalidate_instead_of_caching(db):
    with TestClient(create_app(db=db, settings=Settings())) as c:
        assert c.get("/ui/app.js").headers["cache-control"] == "no-cache"
        assert c.get("/ui/").headers["cache-control"] == "no-cache"
        assert "cache-control" not in c.get("/health").headers
