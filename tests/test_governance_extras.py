"""Comments, active-version pinning, the My-Tasks worklist, and the admin lock view."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from ontoforge.api import create_app
from ontoforge.auth import Principals, Role
from ontoforge.bundle import export_bundle
from ontoforge.config import Settings
from ontoforge.mcp import GraphTools
from ontoforge.registry import LifecycleError, Registry, Status
from tests.hr_fixture import built_domain, BASE

ADMIN = Settings(auth_default_role="admin")


def publish(reg, v, actor="a", reviewer="b"):
    reg.transition(v.id, Status.IN_REVIEW, actor=actor)
    reg.add_review(v.id, reviewer=reviewer, approved=True)
    reg.transition(v.id, Status.PUBLISHED, actor=actor)


def test_comments_are_append_only_and_audited(db):
    reg, store, v = built_domain(db)
    c1 = reg.add_comment(v.id, author="alice", body="Looks **good**")
    c2 = reg.add_comment(v.id, author="bob", body="Salary range?")
    assert [c.body for c in reg.list_comments(v.id)] == ["Looks **good**", "Salary range?"]
    assert c1.id < c2.id and c2.author == "bob"
    assert reg.audit_trail(v.id)[-1].action == "comment.added"
    with pytest.raises(ValueError):
        reg.add_comment(v.id, author="alice", body="   ")


def test_active_version_must_be_published_and_is_served_first(db):
    reg, store, v1 = built_domain(db)
    d = reg.get_domain("hr")
    with pytest.raises(LifecycleError, match="published"):
        reg.set_active_version(d.id, v1.id)
    publish(reg, v1)
    reg.set_active_version(d.id, v1.id)
    v2 = reg.create_version(d.id, actor="a")
    publish(reg, v2)
    assert reg.get_domain("hr").active_version_id == v1.id
    assert reg.served_version(d.id).id == v1.id                      # pinned beats newer published
    assert GraphTools(reg, store).list_domains()[0]["published_version"] == 1
    assert export_bundle(reg, "hr")["version"]["number"] == 1
    reg.set_active_version(d.id, None)
    assert reg.served_version(d.id).id == v2.id                      # unpinned: latest published
    reg.set_active_version(d.id, v2.id)
    reg.transition(v2.id, Status.ARCHIVED, actor="root")
    assert reg.get_domain("hr").active_version_id is None            # archiving clears the pin
    assert reg.served_version(d.id).id == v1.id


def test_my_tasks_worklist(db):
    reg, store, v = built_domain(db)
    d = reg.get_domain("hr")
    reg.acquire_lease(v.id, editor="alice", ttl=timedelta(minutes=10))
    tasks = reg.tasks_for("alice")
    assert [t.version_id for t in tasks["drafts"]] == [v.id] and tasks["drafts"][0].editor == "alice"
    reg.transition(v.id, Status.IN_REVIEW, actor="alice")
    assert [t.version_id for t in reg.tasks_for("bob")["to_review"]] == [v.id]
    reg.add_review(v.id, reviewer="bob", approved=True)
    assert reg.tasks_for("bob")["to_review"] == []                   # already reviewed by bob
    assert [t.version_id for t in reg.tasks_for("carol")["to_review"]] == [v.id]
    assert [t.version_id for t in reg.tasks_for("alice")["publishable"]] == [v.id]   # quorum met


def test_admin_lock_view_and_force_unlock(db):
    reg, store, v = built_domain(db)
    reg.acquire_lease(v.id, editor="alice", ttl=timedelta(minutes=10))
    locks = reg.list_locks()
    assert len(locks) == 1 and locks[0].editor == "alice" and locks[0].stale is False and locks[0].domain == "hr"
    reg.acquire_lease(v.id, editor="alice", ttl=timedelta(seconds=-5))
    assert reg.list_locks()[0].stale is True
    reg.force_release(v.id, actor="root")
    assert reg.list_locks() == [] and reg.audit_trail(v.id)[-1].action == "lease.released"


def test_governance_endpoints(db):
    reg, store, v = built_domain(db)
    Principals(db).set_role("bob", Role.REVIEWER)
    with TestClient(create_app(db=db, settings=ADMIN), headers={"X-Actor": "alice"}) as c:
        assert c.post(f"/versions/{v.id}/comments", json={"body": "hello"}).status_code == 201
        assert c.get(f"/versions/{v.id}/comments").json()[0]["author"] == "alice"
        c.post(f"/versions/{v.id}/transition", json={"to": "in_review"})
        tasks = c.get("/tasks", headers={"X-Actor": "bob"}).json()
        assert [t["version_id"] for t in tasks["to_review"]] == [str(v.id)]
        c.post(f"/versions/{v.id}/reviews", json={"approved": True}, headers={"X-Actor": "bob"})
        c.post(f"/versions/{v.id}/transition", json={"to": "published"})
        assert c.post("/domains/hr/active", json={"version_id": str(v.id)}, headers={"X-Actor": "bob"}).status_code == 200
        assert c.get("/domains/hr").json()["active_version_id"] == str(v.id)
        assert c.post("/domains/hr/active", json={"version_id": None}).status_code == 200
        v2 = c.post("/domains/hr/versions").json()
        c.post(f"/versions/{v2['id']}/lease", json={"ttl_seconds": 600})
        assert c.get("/admin/locks").json()[0]["editor"] == "alice"
        assert c.delete(f"/admin/locks/{v2['id']}").status_code == 204
        assert c.get("/admin/locks").json() == []
