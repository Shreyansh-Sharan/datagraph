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
        assert c.get("/auth/config").json() == {"mode": "header", "header": "X-Forwarded-Email", "default_role": "viewer"}
    with TestClient(create_app(db=db, settings=Settings(auth_mode="token"))) as c:
        assert c.get("/auth/config").json()["mode"] == "token"
