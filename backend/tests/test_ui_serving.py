"""The API serves the built React app when a deployment points it at one, and says so when not.

There is one interface, `frontend/`. The API carries no copy of it: either a build directory is
configured, or `/ui/` explains where the app lives instead of pretending to be it.
"""
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.config import Settings


def _build(tmp_path):
    """A directory shaped like a vite build."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<!doctype html><title>datagraph</title><script type="module" src="/ui/assets/app.js"></script>')
    (tmp_path / "assets" / "app.js").write_text("export const app = 1;\n")
    (tmp_path / "assets" / "app.css").write_text(".x{}\n")
    return tmp_path


def test_the_built_app_is_served_when_a_deployment_points_at_one(db, tmp_path):
    with TestClient(create_app(db=db, settings=Settings(ui_dir=str(_build(tmp_path))))) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"] == "/ui/"
        r = c.get("/ui/")
        assert r.status_code == 200 and "<title>datagraph</title>" in r.text
        assert c.get("/ui/assets/app.js").status_code == 200
        assert c.get("/ui/assets/app.css").headers["content-type"].startswith("text/css")


def test_a_route_inside_the_app_returns_the_app_rather_than_a_404(db, tmp_path):
    with TestClient(create_app(db=db, settings=Settings(ui_dir=str(_build(tmp_path))))) as c:
        r = c.get("/ui/d/rgm/ontology")                    # the browser asks for a deep link
        assert r.status_code == 200 and "<title>datagraph</title>" in r.text
        assert c.get("/ui/assets/missing.js").status_code == 404   # a missing asset is still missing


def test_without_a_build_the_api_says_where_the_interface_is(db):
    with TestClient(create_app(db=db, settings=Settings())) as c:
        r = c.get("/ui/")
        assert r.status_code == 503
        assert "frontend" in r.json()["detail"] and "ONTOFORGE_UI_DIR" in r.json()["detail"]


def test_a_missing_build_directory_is_reported_rather_than_crashing_at_startup(db, tmp_path):
    with TestClient(create_app(db=db, settings=Settings(ui_dir=str(tmp_path / "nope")))) as c:
        assert c.get("/health").json() == {"status": "ok"}
        assert c.get("/ui/").status_code == 503


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


def test_the_shell_is_never_cached_so_a_deploy_is_picked_up(db, tmp_path):
    with TestClient(create_app(db=db, settings=Settings(ui_dir=str(_build(tmp_path))))) as c:
        assert c.get("/ui/").headers["cache-control"] == "no-cache"
        assert "immutable" in c.get("/ui/assets/app.js").headers["cache-control"]
        assert "cache-control" not in c.get("/health").headers
