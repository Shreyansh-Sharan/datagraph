"""Authentication (header / token modes) and role enforcement on the REST API."""
import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.auth import Principals, Role
from ontoforge.config import Settings
from tests.hr_fixture import seed_tables, ontology, mapping, BASE


def app_for(db, **overrides):
    return create_app(db=db, settings=Settings(**overrides))


def test_unknown_principal_gets_default_role_viewer(db):
    with TestClient(app_for(db), headers={"X-Actor": "nobody"}) as c:
        assert c.get("/domains").status_code == 200
        assert c.get("/me").json() == {"name": "nobody", "role": "viewer"}
        r = c.post("/domains", json={"name": "hr", "base_iri": BASE})
        assert r.status_code == 403 and "builder" in r.json()["detail"]


def test_missing_identity_is_401_in_header_mode(db):
    with TestClient(app_for(db)) as c:
        assert c.get("/domains").status_code == 401


def test_health_needs_no_auth(db):
    with TestClient(app_for(db)) as c:
        assert c.get("/health").status_code == 200


def test_role_matrix(db):
    seed_tables(db)
    Principals(db).set_role("alice", Role.BUILDER)
    Principals(db).set_role("bob", Role.REVIEWER)
    Principals(db).set_role("root", Role.ADMIN)
    app = app_for(db)
    alice, bob, root, eve = ({"X-Actor": n} for n in ("alice", "bob", "root", "eve"))
    with TestClient(app) as c:
        assert c.post("/domains", json={"name": "hr", "base_iri": BASE}, headers=alice).status_code == 201
        v = c.post("/domains/hr/versions", headers=alice).json()
        assert c.put(f"/versions/{v['id']}/ontology", json={"turtle": ontology().to_turtle()}, headers=alice).status_code == 200
        assert c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict(), headers=alice).status_code == 200
        assert c.put(f"/versions/{v['id']}/mapping", json=mapping().to_dict(), headers=eve).status_code == 403
        assert c.post(f"/versions/{v['id']}/builds", headers=eve, params={"wait": "true"}).status_code == 403
        assert c.post(f"/versions/{v['id']}/builds", headers=alice, params={"wait": "true"}).json()["status"] == "succeeded"
        # reviewers review; builders don't
        assert c.post(f"/versions/{v['id']}/transition", json={"to": "in_review"}, headers=alice).status_code == 200
        assert c.post(f"/versions/{v['id']}/reviews", json={"approved": True}, headers=alice).status_code == 403
        assert c.post(f"/versions/{v['id']}/reviews", json={"approved": True}, headers=bob).status_code == 201
        assert c.post(f"/versions/{v['id']}/transition", json={"to": "published"}, headers=alice).status_code == 403
        assert c.post(f"/versions/{v['id']}/transition", json={"to": "published"}, headers=bob).status_code == 200
        # admin-only: force lease takeover, delete domain, archive
        v2 = c.post("/domains/hr/versions", headers=alice).json()
        c.post(f"/versions/{v2['id']}/lease", json={"ttl_seconds": 600}, headers=alice)
        assert c.post(f"/versions/{v2['id']}/lease", json={"ttl_seconds": 600, "force": True}, headers=bob).status_code == 403
        assert c.post(f"/versions/{v2['id']}/lease", json={"ttl_seconds": 600, "force": True}, headers=root).status_code == 200
        assert c.post(f"/versions/{v['id']}/transition", json={"to": "archived"}, headers=bob).status_code == 403
        assert c.post(f"/versions/{v['id']}/transition", json={"to": "archived"}, headers=root).status_code == 200
        assert c.delete("/domains/hr", headers=alice).status_code == 403
        assert c.delete("/domains/hr", headers=root).status_code == 204
        # viewers read everything
        assert c.get("/domains", headers=eve).status_code == 200


def test_admin_manages_principals(db):
    Principals(db).set_role("root", Role.ADMIN)
    with TestClient(app_for(db)) as c:
        root = {"X-Actor": "root"}
        assert c.put("/admin/principals/alice", json={"role": "builder"}, headers=root).status_code == 200
        assert c.get("/admin/principals", headers=root).json() == [{"name": "alice", "role": "builder"}, {"name": "root", "role": "admin"}]
        assert c.put("/admin/principals/alice", json={"role": "builder"}, headers={"X-Actor": "alice"}).status_code == 403
        assert c.put("/admin/principals/x", json={"role": "god"}, headers=root).status_code == 422
        assert c.delete("/admin/principals/alice", headers=root).status_code == 204
        assert c.get("/me", headers={"X-Actor": "alice"}).json()["role"] == "viewer"


def test_token_mode_resolves_api_keys(db):
    Principals(db).set_role("root", Role.ADMIN)
    principals = Principals(db)
    key = principals.create_api_key("ci-bot", principal="ci", role=Role.BUILDER)
    assert key.secret.startswith("of_") and len(key.secret) > 30
    with TestClient(app_for(db, auth_mode="token")) as c:
        assert c.get("/domains").status_code == 401
        assert c.get("/domains", headers={"X-Actor": "root"}).status_code == 401            # headers are ignored
        bearer = {"Authorization": f"Bearer {key.secret}"}
        assert c.get("/me", headers=bearer).json() == {"name": "ci", "role": "builder"}
        assert c.post("/domains", json={"name": "hr", "base_iri": BASE}, headers=bearer).status_code == 201
        principals.revoke_api_key(key.id)
        assert c.get("/me", headers=bearer).status_code == 401
        assert c.get("/me", headers={"Authorization": "Bearer of_garbage"}).status_code == 401


def test_admin_issues_and_revokes_keys_over_api(db):
    Principals(db).set_role("root", Role.ADMIN)
    with TestClient(app_for(db), headers={"X-Actor": "root"}) as c:
        r = c.post("/admin/api-keys", json={"name": "bot", "principal": "bot", "role": "viewer"})
        assert r.status_code == 201 and r.json()["secret"].startswith("of_")
        listed = c.get("/admin/api-keys").json()
        assert listed[0]["name"] == "bot" and "secret" not in listed[0] and "key_hash" not in listed[0]
        assert c.delete(f"/admin/api-keys/{r.json()['id']}").status_code == 204
        assert c.get("/admin/api-keys").json()[0]["revoked_at"] is not None


def test_header_name_is_configurable(db):
    Principals(db).set_role("u@x.com", Role.BUILDER)
    with TestClient(app_for(db, auth_header="X-Forwarded-Email"), headers={"X-Forwarded-Email": "u@x.com"}) as c:
        assert c.get("/me").json()["role"] == "builder"
        assert c.get("/me", headers={"X-Actor": "u@x.com", "X-Forwarded-Email": ""}).status_code == 401
